"""Checkpointed anonymous LLM-as-Judge scoring for one 60-question system.

This reuses the frozen judge-v1 rubric and three-way score mapping while allowing
the 60-question corpus to be composed from independently frozen main40 and
extension20 RunRecord stores.  It never mutates source runs and never persists
question, reference-answer, or candidate-answer text in its own artifacts.
"""

from __future__ import annotations

import argparse
import fcntl
import json
import os
import re
import secrets
import tempfile
import time
from collections import Counter
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from .agent import ChatProvider, CompatibleChatProvider, TransientProviderError
from .evidence import EvidenceValidationError, canonical_json_bytes, sha256_bytes
from .evaluation import GoldRecord, load_gold_records
from .judge_v1 import (
    JUDGE_PROMPT_ID,
    JUDGE_PROMPT_SHA256,
    JUDGE_SYSTEM_PROMPT,
    parse_judge_output,
    render_judge_user_prompt,
)
from .run_records import ExperimentRunStore, RunKey, RunRecord, verify_run_store


PROTOCOL_VERSION = "supplemental-anonymous-judge-main60-x-test1-v1"
RUN_PROTOCOL_VERSION = "supplemental-anonymous-judge-main60-run-v1"
REQUESTED_MODEL = "x-test-1"
REQUIRED_SERVED_MODEL = "glm-5.3-flash"
API_STYLE = "portable"
TIMEOUT_SECONDS = 300
MAX_RESPONSE_BYTES = 20_000_000
MAX_COMPLETION_TOKENS = 1024
REASONING_EFFORT = "high"
TEMPERATURE = 0
CONDITIONS = ("E1", "E2", "E3", "E4", "E5", "E6", "E7")
BATCH_SIZE_QUESTIONS = 5
BATCH_SIZE_JUDGMENTS = BATCH_SIZE_QUESTIONS * len(CONDITIONS)
EXPECTED_QUESTION_COUNT = 60
EXPECTED_JUDGMENT_COUNT = EXPECTED_QUESTION_COUNT * len(CONDITIONS)
EXPECTED_BATCH_COUNT = EXPECTED_QUESTION_COUNT // BATCH_SIZE_QUESTIONS
_SHA = re.compile(r"[0-9a-f]{64}\Z")
_SAFE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}\Z")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _file_sha256(path: Path) -> str:
    path = Path(path)
    if path.is_symlink() or not path.is_file():
        raise EvidenceValidationError(f"Required regular file is missing: {path}")
    return sha256_bytes(path.read_bytes())


def _read_json(path: Path) -> Mapping[str, Any]:
    path = Path(path)
    if path.is_symlink() or not path.is_file():
        raise EvidenceValidationError(f"Unsafe or missing JSON artifact: {path}")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise EvidenceValidationError(f"Unreadable JSON artifact: {path}") from exc
    if not isinstance(value, Mapping):
        raise EvidenceValidationError("JSON artifact must contain an object")
    return value


def _write_exclusive(path: Path, value: Mapping[str, Any], mode: int = 0o600) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = canonical_json_bytes(value) + b"\n"
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(path, flags, mode)
    try:
        offset = 0
        while offset < len(payload):
            written = os.write(descriptor, payload[offset:])
            if written <= 0:
                raise OSError("short judge artifact write")
            offset += written
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _write_atomic(path: Path, value: Mapping[str, Any], mode: int = 0o600) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = canonical_json_bytes(value) + b"\n"
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        os.fchmod(descriptor, mode)
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def _publish_idempotent(path: Path, value: Mapping[str, Any], mode: int = 0o600) -> None:
    if path.exists() or path.is_symlink():
        if dict(_read_json(path)) != dict(value):
            raise EvidenceValidationError(f"Existing judge artifact differs: {path.name}")
        return
    _write_exclusive(path, value, mode)


def _append_event(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = canonical_json_bytes(value) + b"\n"
    flags = os.O_WRONLY | os.O_CREAT | os.O_APPEND
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(path, flags, 0o600)
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX)
        os.write(descriptor, payload)
        os.fsync(descriptor)
    finally:
        fcntl.flock(descriptor, fcntl.LOCK_UN)
        os.close(descriptor)


@contextmanager
def _exclusive_run_lock(run_root: Path):
    handle = (run_root / "run.lock").open("a+", encoding="utf-8")
    try:
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise EvidenceValidationError("Another judge runner holds the run lock") from exc
        yield
    finally:
        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        handle.close()


@dataclass(frozen=True)
class PartitionSpec:
    name: str
    source_root: Path
    source_run_id: str
    gold_path: Path
    gold_sha256: str

    def __post_init__(self) -> None:
        if _SAFE.fullmatch(self.name) is None or _SAFE.fullmatch(self.source_run_id) is None:
            raise EvidenceValidationError("Partition name or source run ID is unsafe")
        if _SHA.fullmatch(self.gold_sha256) is None:
            raise EvidenceValidationError("Partition gold SHA-256 is invalid")


@dataclass(frozen=True)
class JudgeConfig:
    model: str = REQUESTED_MODEL
    reasoning_effort: str = REASONING_EFFORT
    max_completion_tokens: int = MAX_COMPLETION_TOKENS
    max_rounds: int = 1
    temperature: int = TEMPERATURE


def _safe_usage(value: Any) -> dict[str, int]:
    if not isinstance(value, Mapping):
        raise EvidenceValidationError("Judge usage is missing")
    keys = ("prompt_tokens", "completion_tokens", "total_tokens")
    if not set(keys).issubset(value):
        raise EvidenceValidationError("Judge usage token fields are missing")
    usage = {key: value[key] for key in keys}
    if any(isinstance(item, bool) or not isinstance(item, int) or item < 0 for item in usage.values()):
        raise EvidenceValidationError("Judge usage values are invalid")
    if usage["total_tokens"] != usage["prompt_tokens"] + usage["completion_tokens"]:
        raise EvidenceValidationError("Judge usage total differs")
    return usage


class SemanticJudge:
    """Exact judge-v1 rubric with x-test-1 identity enforcement."""

    def __init__(self, *, provider: ChatProvider, sleeper: Callable[[float], None] = time.sleep) -> None:
        self.provider = provider
        self.sleeper = sleeper
        self.config = JudgeConfig()

    def _complete(self, messages: list[dict[str, str]]) -> tuple[dict[str, Any], int]:
        attempts = 0
        while True:
            attempts += 1
            try:
                response = self.provider.complete(messages, [], self.config)
                if not isinstance(response, Mapping):
                    raise EvidenceValidationError("Judge provider response must be an object")
                return dict(response), attempts
            except TransientProviderError as exc:
                maximum = 5 if exc.kind == "http" else 3
                backoff = (5, 15, 30, 60) if exc.kind == "http" else (2, 4)
                if attempts >= maximum:
                    raise
                self.sleeper(float(backoff[attempts - 1]))

    def run(self, *, question: str, reference_answer: str, candidate_answer: str) -> dict[str, Any]:
        messages = [
            {"role": "system", "content": JUDGE_SYSTEM_PROMPT},
            {
                "role": "user",
                "content": render_judge_user_prompt(
                    question=question,
                    reference_answer=reference_answer,
                    candidate_answer=candidate_answer,
                ),
            },
        ]
        usages: list[dict[str, int]] = []
        served_models: list[str] = []
        response_ids: list[str] = []
        attempts_total = 0
        repairs = 0
        while True:
            response, attempts = self._complete(messages)
            attempts_total += attempts
            message = response.get("message")
            if not isinstance(message, Mapping) or message.get("tool_calls") not in (None, []):
                raise EvidenceValidationError("Judge response message is invalid")
            content = message.get("content")
            served = response.get("served_model")
            if not isinstance(content, str) or not isinstance(served, str) or not served:
                raise EvidenceValidationError("Judge provider response is incomplete")
            usages.append(_safe_usage(response.get("usage")))
            served_models.append(served)
            response_id = response.get("response_id")
            response_ids.append(response_id if isinstance(response_id, str) else "")
            try:
                parsed = parse_judge_output(content)
                break
            except EvidenceValidationError:
                if repairs >= 1:
                    raise EvidenceValidationError("Judge format repair failed")
                repairs += 1
                messages = [
                    {
                        "role": "system",
                        "content": "Reformat the judgment into the exact required JSON. Do not change its decision.",
                    },
                    {"role": "user", "content": content},
                ]
        if set(served_models) != {REQUIRED_SERVED_MODEL}:
            raise EvidenceValidationError("Judge served model drifted")
        label = parsed["label"]
        return {
            **parsed,
            "strict_score": 1.0 if label == "correct" else 0.0,
            "soft_score": {"correct": 1.0, "partial": 0.5, "incorrect": 0.0}[label],
            "prompt_id": JUDGE_PROMPT_ID,
            "prompt_sha256": JUDGE_PROMPT_SHA256,
            "requested_model": REQUESTED_MODEL,
            "served_models": list(dict.fromkeys(served_models)),
            "provider_request_attempts": attempts_total,
            "model_calls": len(usages),
            "format_repairs": repairs,
            "usage": usages,
            "response_ids": response_ids,
        }


@dataclass(frozen=True)
class OpenPartition:
    spec: PartitionSpec
    store: ExperimentRunStore
    gold: Mapping[str, GoldRecord]
    evaluation_path: Path


@dataclass(frozen=True)
class ScheduleItem:
    partition_name: str
    key: RunKey


def _open_partitions(specs: Sequence[PartitionSpec]) -> tuple[OpenPartition, ...]:
    if len(specs) != 2 or {spec.name for spec in specs} != {"main40", "extension20"}:
        raise EvidenceValidationError("Exactly main40 and extension20 partitions are required")
    opened: list[OpenPartition] = []
    questions: set[str] = set()
    for spec in specs:
        store, checkpoint = verify_run_store(spec.source_root.resolve(), spec.source_run_id)
        if checkpoint["pending"] != 0 or checkpoint["completed"] != checkpoint["planned"]:
            raise EvidenceValidationError("Judge source store is incomplete")
        gold_rows = load_gold_records(spec.gold_path.resolve(), expected_sha256=spec.gold_sha256)
        gold = {row.question_id: row for row in gold_rows}
        if set(gold) != set(store.plan.question_ids):
            raise EvidenceValidationError("Judge source plan and gold differ")
        if questions & set(gold):
            raise EvidenceValidationError("Judge partitions overlap")
        questions.update(gold)
        evaluation_path = store.run_root / "evaluation.json"
        if not evaluation_path.is_file() or evaluation_path.is_symlink():
            raise EvidenceValidationError("Source offline evaluation is missing")
        opened.append(OpenPartition(spec, store, gold, evaluation_path))
    if len(questions) != EXPECTED_QUESTION_COUNT:
        raise EvidenceValidationError("Judge requires exactly 60 unique questions")
    return tuple(sorted(opened, key=lambda value: 0 if value.spec.name == "main40" else 1))


def _schedule(partitions: Sequence[OpenPartition]) -> tuple[ScheduleItem, ...]:
    schedule = tuple(
        ScheduleItem(partition.spec.name, key)
        for partition in partitions
        for key in partition.store.plan.execution_order
    )
    if len(schedule) != EXPECTED_JUDGMENT_COUNT:
        raise EvidenceValidationError("Judge requires exactly 420 source records")
    for start in range(0, len(schedule), BATCH_SIZE_JUDGMENTS):
        block = schedule[start : start + BATCH_SIZE_JUDGMENTS]
        if Counter(item.key.condition_id for item in block) != Counter({value: 5 for value in CONDITIONS}):
            raise EvidenceValidationError("Source order is not balanced in five-question batches")
    return schedule


def _partition_map(partitions: Sequence[OpenPartition]) -> dict[str, OpenPartition]:
    return {partition.spec.name: partition for partition in partitions}


def _source_record(partitions: Mapping[str, OpenPartition], item: ScheduleItem) -> RunRecord:
    record = partitions[item.partition_name].store.load_completed(item.key)
    if record is None:
        raise EvidenceValidationError("Source record disappeared")
    return record


def _gold(partitions: Mapping[str, OpenPartition], item: ScheduleItem) -> GoldRecord:
    return partitions[item.partition_name].gold[item.key.question_id]


def _manifest_body(
    *, repo_root: Path, source_system_id: str, judge_run_id: str,
    partitions: Sequence[OpenPartition], self_judge_disclosure: bool,
) -> dict[str, Any]:
    schedule = _schedule(partitions)
    source_rows = []
    for partition in partitions:
        source_rows.append(
            {
                "partition_name": partition.spec.name,
                "source_root": str(partition.spec.source_root.resolve()),
                "source_run_id": partition.spec.source_run_id,
                "source_plan_id": partition.store.plan.plan_id,
                "source_plan_sha256": _file_sha256(partition.store.run_root / "plan.json"),
                "source_evaluation_sha256": _file_sha256(partition.evaluation_path),
                "gold_path": str(partition.spec.gold_path.resolve()),
                "gold_sha256": partition.spec.gold_sha256,
                "question_count": len(partition.store.plan.question_ids),
                "record_count": len(partition.store.plan.execution_order),
            }
        )
    module_path = Path(__file__).resolve()
    prompt_module_path = repo_root / "fs_memory_lab/judge_v1.py"
    return {
        "schema_version": 1,
        "protocol_version": RUN_PROTOCOL_VERSION,
        "status": "prepared",
        "judge_run_id": judge_run_id,
        "source_system_id": source_system_id,
        "planned_judgments": len(schedule),
        "question_count": EXPECTED_QUESTION_COUNT,
        "condition_ids": list(CONDITIONS),
        "batch_size_questions": BATCH_SIZE_QUESTIONS,
        "batch_size_judgments": BATCH_SIZE_JUDGMENTS,
        "batch_count": EXPECTED_BATCH_COUNT,
        "execution_order_sha256": sha256_bytes(
            canonical_json_bytes(
                [
                    {"partition_name": item.partition_name, **item.key.to_dict()}
                    for item in schedule
                ]
            )
        ),
        "sources": source_rows,
        "judge": {
            "labels": ["correct", "partial", "incorrect"],
            "strict_score_mapping": {"correct": 1.0, "partial": 0.0, "incorrect": 0.0},
            "soft_score_mapping": {"correct": 1.0, "partial": 0.5, "incorrect": 0.0},
            "prompt_id": JUDGE_PROMPT_ID,
            "prompt_sha256": JUDGE_PROMPT_SHA256,
            "anonymized_fields": ["source_system_id", "condition_id", "retrieval_method", "storage_method"],
            "self_judge_disclosure": self_judge_disclosure,
        },
        "deployment": {
            "requested_model_alias": REQUESTED_MODEL,
            "required_served_model": REQUIRED_SERVED_MODEL,
            "api_style": API_STYLE,
            "request_timeout_seconds": TIMEOUT_SECONDS,
            "max_response_bytes": MAX_RESPONSE_BYTES,
            "concurrency": 1,
            "max_completion_tokens": MAX_COMPLETION_TOKENS,
            "temperature": TEMPERATURE,
        },
        "implementation": {
            "module_sha256": _file_sha256(module_path),
            "prompt_module_sha256": _file_sha256(prompt_module_path),
        },
        "resume_policy": "revalidate-and-skip-only-content-addressed-completed-judgments",
        "source_mutation_forbidden": True,
        "contains_source_text": False,
    }


def _manifest_with_id(body: Mapping[str, Any]) -> dict[str, Any]:
    return {"judge_manifest_id": "judge-manifest-" + sha256_bytes(canonical_json_bytes(body)), **dict(body)}


def _load_manifest(run_root: Path) -> dict[str, Any]:
    manifest = dict(_read_json(run_root / "manifest.json"))
    identity = manifest.pop("judge_manifest_id", None)
    expected = "judge-manifest-" + sha256_bytes(canonical_json_bytes(manifest))
    if identity != expected:
        raise EvidenceValidationError("Judge manifest content hash differs")
    return {"judge_manifest_id": identity, **manifest}


def _run_root(output_root: Path, judge_run_id: str) -> Path:
    if _SAFE.fullmatch(judge_run_id) is None:
        raise EvidenceValidationError("Judge run ID is unsafe")
    return output_root.resolve() / judge_run_id


def prepare_run(
    *, repo_root: Path, output_root: Path, judge_run_id: str,
    source_system_id: str, specs: Sequence[PartitionSpec],
    self_judge_disclosure: bool,
) -> Path:
    if _SAFE.fullmatch(source_system_id) is None:
        raise EvidenceValidationError("Source system ID is unsafe")
    partitions = _open_partitions(specs)
    manifest = _manifest_with_id(
        _manifest_body(
            repo_root=repo_root.resolve(), source_system_id=source_system_id,
            judge_run_id=judge_run_id, partitions=partitions,
            self_judge_disclosure=self_judge_disclosure,
        )
    )
    run_root = _run_root(output_root, judge_run_id)
    run_root.mkdir(parents=True, exist_ok=True, mode=0o700)
    for partition in partitions:
        for condition in CONDITIONS:
            (run_root / "records" / partition.spec.name / condition).mkdir(parents=True, exist_ok=True)
            (run_root / "failures" / partition.spec.name / condition).mkdir(parents=True, exist_ok=True)
    (run_root / "control").mkdir(exist_ok=True)
    _publish_idempotent(run_root / "manifest.json", manifest)
    _append_event(
        run_root / "events.jsonl",
        {"event": "judge_run_prepared", "at": _now(), "judge_manifest_id": manifest["judge_manifest_id"]},
    )
    write_status(output_root=output_root, judge_run_id=judge_run_id, specs=specs)
    return run_root / "manifest.json"


def _validate_sources(manifest: Mapping[str, Any], partitions: Sequence[OpenPartition]) -> None:
    expected = {row["partition_name"]: row for row in manifest["sources"]}
    if set(expected) != {partition.spec.name for partition in partitions}:
        raise EvidenceValidationError("Judge source partition identity differs")
    for partition in partitions:
        row = expected[partition.spec.name]
        if (
            row["source_run_id"] != partition.spec.source_run_id
            or row["source_plan_id"] != partition.store.plan.plan_id
            or row["source_plan_sha256"] != _file_sha256(partition.store.run_root / "plan.json")
            or row["source_evaluation_sha256"] != _file_sha256(partition.evaluation_path)
            or row["gold_sha256"] != partition.spec.gold_sha256
        ):
            raise EvidenceValidationError("Judge frozen source changed")


def _open_run(
    *, output_root: Path, judge_run_id: str, specs: Sequence[PartitionSpec]
) -> tuple[Path, dict[str, Any], tuple[OpenPartition, ...], tuple[ScheduleItem, ...]]:
    run_root = _run_root(output_root, judge_run_id)
    manifest = _load_manifest(run_root)
    partitions = _open_partitions(specs)
    _validate_sources(manifest, partitions)
    schedule = _schedule(partitions)
    actual_hash = sha256_bytes(
        canonical_json_bytes(
            [{"partition_name": item.partition_name, **item.key.to_dict()} for item in schedule]
        )
    )
    if manifest["execution_order_sha256"] != actual_hash:
        raise EvidenceValidationError("Judge source execution order changed")
    return run_root, manifest, partitions, schedule


def _record_path(run_root: Path, item: ScheduleItem) -> Path:
    return run_root / "records" / item.partition_name / item.key.condition_id / f"{item.key.question_id}.json"


def _failure_dir(run_root: Path, item: ScheduleItem) -> Path:
    return run_root / "failures" / item.partition_name / item.key.condition_id / item.key.question_id


def _judgment_body(
    *, source_system_id: str, partition_name: str, source_record: RunRecord,
    gold: GoldRecord, result: Mapping[str, Any],
) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "protocol_version": PROTOCOL_VERSION,
        "status": "completed",
        "source_system_id": source_system_id,
        "partition_name": partition_name,
        "source_run_id": source_record.run_id,
        "source_plan_id": source_record.plan_id,
        "condition_id": source_record.key.condition_id,
        "question_id": source_record.key.question_id,
        "source_record_id": source_record.record_id,
        "source_record_sha256": sha256_bytes(canonical_json_bytes(source_record.to_dict())),
        "question_sha256": source_record.question.sha256,
        "reference_answer_sha256": sha256_bytes(gold.answer.encode("utf-8")),
        "candidate_answer_sha256": sha256_bytes(source_record.answer_result.answer.encode("utf-8")),
        "category": gold.category,
        "category_name": gold.category_name,
        **dict(result),
    }


def _judgment_record(**kwargs: Any) -> dict[str, Any]:
    body = _judgment_body(**kwargs)
    return {"judgment_id": "judgment-" + sha256_bytes(canonical_json_bytes(body)), **body}


def _validate_judgment(
    value: Mapping[str, Any], *, manifest: Mapping[str, Any], item: ScheduleItem,
    source_record: RunRecord, gold: GoldRecord,
) -> dict[str, Any]:
    required_result = {
        "label", "short_reason", "confidence", "strict_score", "soft_score",
        "prompt_id", "prompt_sha256", "requested_model", "served_models",
        "provider_request_attempts", "model_calls", "format_repairs", "usage", "response_ids",
    }
    base = {
        "judgment_id", "schema_version", "protocol_version", "status",
        "source_system_id", "partition_name", "source_run_id", "source_plan_id",
        "condition_id", "question_id", "source_record_id", "source_record_sha256",
        "question_sha256", "reference_answer_sha256", "candidate_answer_sha256",
        "category", "category_name",
    }
    if set(value) != base | required_result:
        raise EvidenceValidationError("Judgment record fields differ")
    label = value.get("label")
    if label not in {"correct", "partial", "incorrect"}:
        raise EvidenceValidationError("Judgment label is invalid")
    if value.get("strict_score") != (1.0 if label == "correct" else 0.0):
        raise EvidenceValidationError("Judgment strict score differs")
    if value.get("soft_score") != {"correct": 1.0, "partial": 0.5, "incorrect": 0.0}[str(label)]:
        raise EvidenceValidationError("Judgment soft score differs")
    if value.get("prompt_id") != JUDGE_PROMPT_ID or value.get("prompt_sha256") != JUDGE_PROMPT_SHA256:
        raise EvidenceValidationError("Judgment prompt identity differs")
    if value.get("requested_model") != REQUESTED_MODEL or set(value.get("served_models", [])) != {REQUIRED_SERVED_MODEL}:
        raise EvidenceValidationError("Judgment model identity differs")
    if value.get("confidence") not in {"high", "medium", "low"}:
        raise EvidenceValidationError("Judgment confidence is invalid")
    if not isinstance(value.get("short_reason"), str) or not str(value["short_reason"]).strip():
        raise EvidenceValidationError("Judgment reason is empty")
    usage = value.get("usage")
    if not isinstance(usage, list) or not usage:
        raise EvidenceValidationError("Judgment usage is empty")
    for row in usage:
        _safe_usage(row)
    if value.get("model_calls") != len(usage) or value.get("format_repairs") not in {0, 1}:
        raise EvidenceValidationError("Judgment call counters differ")
    if value.get("model_calls") != 1 + value.get("format_repairs"):
        raise EvidenceValidationError("Judgment repair counters differ")
    result = {key: value[key] for key in required_result}
    recreated = _judgment_record(
        source_system_id=str(manifest["source_system_id"]),
        partition_name=item.partition_name,
        source_record=source_record,
        gold=gold,
        result=result,
    )
    if recreated != dict(value):
        raise EvidenceValidationError("Judgment content identity differs")
    return dict(value)


def _load_completed(
    run_root: Path, manifest: Mapping[str, Any], item: ScheduleItem,
    source_record: RunRecord, gold: GoldRecord,
) -> dict[str, Any] | None:
    path = _record_path(run_root, item)
    if not path.exists() and not path.is_symlink():
        return None
    return _validate_judgment(
        _read_json(path), manifest=manifest, item=item,
        source_record=source_record, gold=gold,
    )


def _publish_judgment(run_root: Path, item: ScheduleItem, value: Mapping[str, Any]) -> None:
    path = _record_path(run_root, item)
    if path.exists() or path.is_symlink():
        raise EvidenceValidationError("Completed judgment already exists")
    staging = path.parent / f".{path.name}.in-progress-{secrets.token_hex(8)}"
    _write_exclusive(staging, value)
    os.replace(staging, path)
    directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(directory)
    finally:
        os.close(directory)


def _failure_count(run_root: Path, item: ScheduleItem) -> int:
    directory = _failure_dir(run_root, item)
    if not directory.exists():
        return 0
    if directory.is_symlink() or not directory.is_dir():
        raise EvidenceValidationError("Judge failure directory is unsafe")
    values = []
    for path in directory.glob("attempt-*.json"):
        match = re.fullmatch(r"attempt-(\d+)\.json", path.name)
        if match:
            values.append(int(match.group(1)))
    return max(values, default=0)


def _safe_error(error: BaseException, provider: ChatProvider | None = None) -> str:
    message = " ".join(str(error).split())[:1000] or type(error).__name__
    secret = getattr(provider, "api_key", None) if provider is not None else None
    if isinstance(secret, str) and secret:
        message = message.replace(secret, "[REDACTED_KEY]")
    return re.sub(r"\b(?:clsk|sk)[_-][A-Za-z0-9_-]{10,}\b", "[REDACTED_KEY]", message)


def _publish_failure(run_root: Path, item: ScheduleItem, error: BaseException, provider: ChatProvider) -> None:
    attempt = _failure_count(run_root, item) + 1
    body = {
        "schema_version": 1,
        "protocol_version": RUN_PROTOCOL_VERSION,
        "status": "failed",
        "partition_name": item.partition_name,
        "condition_id": item.key.condition_id,
        "question_id": item.key.question_id,
        "attempt": attempt,
        "stage": "semantic_judgment",
        "error_type": type(error).__name__,
        "message": _safe_error(error, provider),
        "retryable": isinstance(error, TransientProviderError),
        "failed_at": _now(),
    }
    value = {"failure_id": "judge-failure-" + sha256_bytes(canonical_json_bytes(body)), **body}
    directory = _failure_dir(run_root, item)
    directory.mkdir(parents=True, exist_ok=True)
    _write_exclusive(directory / f"attempt-{attempt:04d}.json", value)


def _status_body(
    *, run_root: Path, manifest: Mapping[str, Any], partitions: Sequence[OpenPartition],
    schedule: Sequence[ScheduleItem],
) -> dict[str, Any]:
    by_name = _partition_map(partitions)
    completed = 0
    by_condition = {condition: 0 for condition in CONDITIONS}
    labels = {label: 0 for label in ("correct", "partial", "incorrect")}
    total_tokens = 0
    active_failures = 0
    for item in schedule:
        source = _source_record(by_name, item)
        gold = _gold(by_name, item)
        value = _load_completed(run_root, manifest, item, source, gold)
        if value is None:
            active_failures += int(_failure_count(run_root, item) > 0)
            continue
        completed += 1
        by_condition[item.key.condition_id] += 1
        labels[str(value["label"])] += 1
        total_tokens += sum(int(row["total_tokens"]) for row in value["usage"])
    return {
        "schema_version": 1,
        "protocol_version": RUN_PROTOCOL_VERSION,
        "judge_run_id": manifest["judge_run_id"],
        "judge_manifest_id": manifest["judge_manifest_id"],
        "source_system_id": manifest["source_system_id"],
        "status": "completed" if completed == len(schedule) else ("failed" if active_failures else "pending"),
        "completed_judgments": completed,
        "pending_judgments": len(schedule) - completed,
        "planned_judgments": len(schedule),
        "completed_batches": completed // BATCH_SIZE_JUDGMENTS,
        "completed_by_condition": by_condition,
        "label_counts": labels,
        "active_failed_keys": active_failures,
        "judge_total_tokens": total_tokens,
        "updated_at": _now(),
    }


def write_status(*, output_root: Path, judge_run_id: str, specs: Sequence[PartitionSpec]) -> dict[str, Any]:
    run_root, manifest, partitions, schedule = _open_run(
        output_root=output_root, judge_run_id=judge_run_id, specs=specs
    )
    status = _status_body(
        run_root=run_root, manifest=manifest, partitions=partitions, schedule=schedule
    )
    _write_atomic(run_root / "status.json", status)
    return status


def dry_run(*, output_root: Path, judge_run_id: str, specs: Sequence[PartitionSpec]) -> dict[str, Any]:
    run_root, manifest, partitions, schedule = _open_run(
        output_root=output_root, judge_run_id=judge_run_id, specs=specs
    )
    by_name = _partition_map(partitions)
    wrapper_ok = True
    for item in schedule:
        source = _source_record(by_name, item)
        gold = _gold(by_name, item)
        prompt = render_judge_user_prompt(
            question=source.question.question,
            reference_answer=gold.answer,
            candidate_answer=source.answer_result.answer,
        )
        wrapper_ok = wrapper_ok and all(
            prompt.count(marker) == 1
            for marker in ("Question:\n", "Reference answer:\n", "Candidate answer:\n")
        )
    counts = Counter(item.key.condition_id for item in schedule)
    checks = {
        "source_420_verified": len(schedule) == EXPECTED_JUDGMENT_COUNT,
        "questions_60_exact": sum(len(partition.gold) for partition in partitions) == EXPECTED_QUESTION_COUNT,
        "conditions_60_each": set(counts.values()) == {EXPECTED_QUESTION_COUNT},
        "batches_12_balanced": manifest["batch_count"] == EXPECTED_BATCH_COUNT,
        "anonymous_prompt_contract": wrapper_ok,
        "prompt_hash_reused_exactly": manifest["judge"]["prompt_sha256"] == JUDGE_PROMPT_SHA256,
        "api_provider_not_constructed": True,
        "source_mutation_forbidden": manifest["source_mutation_forbidden"] is True,
    }
    body = {
        "schema_version": 1,
        "protocol_version": RUN_PROTOCOL_VERSION,
        "judge_run_id": judge_run_id,
        "judge_manifest_id": manifest["judge_manifest_id"],
        "status": "passed" if all(checks.values()) else "failed",
        "checks": checks,
        "planned_judgments": len(schedule),
        "api_calls": 0,
    }
    value = {"dry_run_id": "judge-dry-run-" + sha256_bytes(canonical_json_bytes(body)), **body}
    _publish_idempotent(run_root / "dry-run.json", value)
    if value["status"] != "passed":
        raise EvidenceValidationError("Judge dry-run failed")
    return value


def _provider_preflight(provider: ChatProvider) -> None:
    if getattr(provider, "api_style", None) != API_STYLE:
        raise EvidenceValidationError("Judge provider API style differs")
    if getattr(provider, "model", None) != REQUESTED_MODEL:
        raise EvidenceValidationError("Judge provider model must equal x-test-1")
    if getattr(provider, "timeout", None) != TIMEOUT_SECONDS:
        raise EvidenceValidationError("Judge provider timeout differs")
    if getattr(provider, "max_response_bytes", None) != MAX_RESPONSE_BYTES:
        raise EvidenceValidationError("Judge provider response cap differs")


def preflight(
    *, output_root: Path, judge_run_id: str, specs: Sequence[PartitionSpec], provider: ChatProvider
) -> dict[str, Any]:
    run_root, manifest, _partitions, _schedule_items = _open_run(
        output_root=output_root, judge_run_id=judge_run_id, specs=specs
    )
    path = run_root / "preflight.json"
    if path.exists() or path.is_symlink():
        value = dict(_read_json(path))
        if (
            value.get("status") != "passed"
            or value.get("judge_manifest_id") != manifest["judge_manifest_id"]
            or value.get("requested_model") != REQUESTED_MODEL
            or value.get("served_model") != REQUIRED_SERVED_MODEL
        ):
            raise EvidenceValidationError("Existing judge preflight differs")
        return value
    _provider_preflight(provider)
    result = SemanticJudge(provider=provider).run(
        question="What is two plus two?", reference_answer="four", candidate_answer="four"
    )
    if result["label"] != "correct":
        raise EvidenceValidationError("Judge synthetic preflight decision differs")
    body = {
        "schema_version": 1,
        "protocol_version": RUN_PROTOCOL_VERSION,
        "judge_run_id": judge_run_id,
        "judge_manifest_id": manifest["judge_manifest_id"],
        "status": "passed",
        "requested_model": REQUESTED_MODEL,
        "served_model": REQUIRED_SERVED_MODEL,
        "prompt_sha256": JUDGE_PROMPT_SHA256,
        "json_schema_exact": True,
        "synthetic_decision_correct": True,
        "model_calls": result["model_calls"],
        "format_repairs": result["format_repairs"],
        "total_tokens": sum(row["total_tokens"] for row in result["usage"]),
        "contains_source_text": False,
    }
    value = {"preflight_id": "judge-preflight-" + sha256_bytes(canonical_json_bytes(body)), **body}
    _publish_idempotent(path, value)
    return value


def _audit_batch(
    *, run_root: Path, manifest: Mapping[str, Any], partitions: Sequence[OpenPartition],
    schedule: Sequence[ScheduleItem], batch: int,
) -> dict[str, Any]:
    target = batch * BATCH_SIZE_JUDGMENTS
    by_name = _partition_map(partitions)
    rows = []
    for item in schedule[:target]:
        row = _load_completed(
            run_root, manifest, item, _source_record(by_name, item), _gold(by_name, item)
        )
        if row is not None:
            rows.append(row)
    counts = Counter(row["condition_id"] for row in rows)
    checks = {
        "prefix_complete": len(rows) == target,
        "conditions_balanced": counts == Counter({value: batch * BATCH_SIZE_QUESTIONS for value in CONDITIONS}),
        "prompt_hash_exact": all(row["prompt_sha256"] == JUDGE_PROMPT_SHA256 for row in rows),
        "served_model_exact": all(set(row["served_models"]) == {REQUIRED_SERVED_MODEL} for row in rows),
        "source_records_unchanged": True,
    }
    body = {
        "schema_version": 1,
        "protocol_version": RUN_PROTOCOL_VERSION,
        "judge_run_id": manifest["judge_run_id"],
        "batch": batch,
        "target_judgments": target,
        "completed_judgments": len(rows),
        "status": "passed" if all(checks.values()) else "failed",
        "checks": checks,
    }
    value = {"batch_audit_id": "judge-batch-" + sha256_bytes(canonical_json_bytes(body)), **body}
    _publish_idempotent(run_root / "control" / f"batch-{batch:02d}-audit.json", value)
    if value["status"] != "passed":
        raise EvidenceValidationError("Judge batch audit failed")
    _publish_idempotent(
        run_root / "control" / f"batch-{batch:02d}.PASSED",
        {"status": "passed", "batch_audit_id": value["batch_audit_id"]},
    )
    return value


def run(
    *, output_root: Path, judge_run_id: str, specs: Sequence[PartitionSpec],
    provider: ChatProvider, through_batch: int,
) -> dict[str, Any]:
    if isinstance(through_batch, bool) or not isinstance(through_batch, int) or not 1 <= through_batch <= EXPECTED_BATCH_COUNT:
        raise EvidenceValidationError("through_batch must be 1-12")
    run_root, manifest, partitions, schedule = _open_run(
        output_root=output_root, judge_run_id=judge_run_id, specs=specs
    )
    dry = _read_json(run_root / "dry-run.json")
    preflight_row = _read_json(run_root / "preflight.json")
    if dry.get("status") != "passed" or preflight_row.get("status") != "passed":
        raise EvidenceValidationError("Judge run requires dry-run and preflight")
    _provider_preflight(provider)
    judge = SemanticJudge(provider=provider)
    by_name = _partition_map(partitions)
    target = through_batch * BATCH_SIZE_JUDGMENTS
    events = run_root / "events.jsonl"
    with _exclusive_run_lock(run_root):
        before = write_status(output_root=output_root, judge_run_id=judge_run_id, specs=specs)
        _append_event(
            events,
            {"event": "judge_run_started", "at": _now(), "completed_before": before["completed_judgments"], "target_judgments": target},
        )
        for sequence, item in enumerate(schedule[:target], start=1):
            source = _source_record(by_name, item)
            gold = _gold(by_name, item)
            if _load_completed(run_root, manifest, item, source, gold) is not None:
                if (
                    sequence % BATCH_SIZE_JUDGMENTS == 0
                    and not (run_root / "control" / f"batch-{sequence // BATCH_SIZE_JUDGMENTS:02d}.PASSED").is_file()
                ):
                    _audit_batch(
                        run_root=run_root, manifest=manifest, partitions=partitions,
                        schedule=schedule, batch=sequence // BATCH_SIZE_JUDGMENTS,
                    )
                continue
            print(f"[{sequence:03d}/{EXPECTED_JUDGMENT_COUNT}] START", flush=True)
            try:
                result = judge.run(
                    question=source.question.question,
                    reference_answer=gold.answer,
                    candidate_answer=source.answer_result.answer,
                )
                value = _judgment_record(
                    source_system_id=str(manifest["source_system_id"]),
                    partition_name=item.partition_name,
                    source_record=source,
                    gold=gold,
                    result=result,
                )
                _validate_judgment(
                    value, manifest=manifest, item=item, source_record=source, gold=gold
                )
                _publish_judgment(run_root, item, value)
            except Exception as error:
                _publish_failure(run_root, item, error, provider)
                status = write_status(output_root=output_root, judge_run_id=judge_run_id, specs=specs)
                _append_event(
                    events,
                    {"event": "judgment_failed", "at": _now(), "sequence": sequence, "error_type": type(error).__name__},
                )
                return {"status": "failed", "sequence": sequence, "progress": status}
            _append_event(
                events,
                {"event": "judgment_verified", "at": _now(), "sequence": sequence, "judgment_id": value["judgment_id"], "label": value["label"], "soft_score": value["soft_score"], "total_tokens": sum(row["total_tokens"] for row in value["usage"])},
            )
            print(f"[{sequence:03d}/{EXPECTED_JUDGMENT_COUNT}] VERIFIED", flush=True)
            if sequence % BATCH_SIZE_JUDGMENTS == 0:
                batch = sequence // BATCH_SIZE_JUDGMENTS
                _audit_batch(
                    run_root=run_root, manifest=manifest, partitions=partitions,
                    schedule=schedule, batch=batch,
                )
                write_status(output_root=output_root, judge_run_id=judge_run_id, specs=specs)
        final = write_status(output_root=output_root, judge_run_id=judge_run_id, specs=specs)
        _append_event(events, {"event": "judge_target_reached", "at": _now(), "completed_judgments": final["completed_judgments"]})
        return final


def verify(*, output_root: Path, judge_run_id: str, specs: Sequence[PartitionSpec]) -> dict[str, Any]:
    run_root, manifest, partitions, schedule = _open_run(
        output_root=output_root, judge_run_id=judge_run_id, specs=specs
    )
    by_name = _partition_map(partitions)
    rows = []
    for item in schedule:
        row = _load_completed(
            run_root, manifest, item, _source_record(by_name, item), _gold(by_name, item)
        )
        if row is None:
            raise EvidenceValidationError("Judge verification requires 420/420 judgments")
        rows.append(row)
    counts = Counter(row["condition_id"] for row in rows)
    checks = {
        "judgments_420": len(rows) == EXPECTED_JUDGMENT_COUNT,
        "conditions_60_each": counts == Counter({value: EXPECTED_QUESTION_COUNT for value in CONDITIONS}),
        "prompt_hash_exact": all(row["prompt_sha256"] == JUDGE_PROMPT_SHA256 for row in rows),
        "served_model_exact": all(set(row["served_models"]) == {REQUIRED_SERVED_MODEL} for row in rows),
        "score_mapping_exact": all(row["soft_score"] == {"correct": 1.0, "partial": 0.5, "incorrect": 0.0}[row["label"]] for row in rows),
        "all_batches_passed": all((run_root / "control" / f"batch-{batch:02d}.PASSED").is_file() for batch in range(1, EXPECTED_BATCH_COUNT + 1)),
        "source_records_unchanged": True,
    }
    body = {
        "schema_version": 1,
        "protocol_version": RUN_PROTOCOL_VERSION,
        "judge_run_id": judge_run_id,
        "judge_manifest_id": manifest["judge_manifest_id"],
        "status": "passed" if all(checks.values()) else "failed",
        "checks": checks,
        "condition_counts": dict(counts),
        "judged_records": len(rows),
    }
    value = {"verification_id": "judge-verify-" + sha256_bytes(canonical_json_bytes(body)), **body}
    _publish_idempotent(run_root / "verification.json", value)
    if value["status"] != "passed":
        raise EvidenceValidationError("Judge verification failed")
    return value


def _mean(values: Sequence[float]) -> float | None:
    return sum(values) / len(values) if values else None


def _summary(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    def summarize(members: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
        labels = {label: sum(row["label"] == label for row in members) for label in ("correct", "partial", "incorrect")}
        tokens = [sum(int(item["total_tokens"]) for item in row["usage"]) for row in members]
        return {
            "count": len(members),
            "label_counts": labels,
            "strict_accuracy": _mean([float(row["strict_score"]) for row in members]),
            "partial_rate": labels["partial"] / len(members) if members else None,
            "incorrect_rate": labels["incorrect"] / len(members) if members else None,
            "soft_semantic_score": _mean([float(row["soft_score"]) for row in members]),
            "high_confidence_rate": _mean([float(row["confidence"] == "high") for row in members]),
            "judge_total_tokens": sum(tokens),
            "mean_judge_tokens": _mean([float(value) for value in tokens]),
            "judge_model_calls": sum(int(row["model_calls"]) for row in members),
            "format_repairs": sum(int(row["format_repairs"]) for row in members),
        }
    conditions = {}
    for condition in CONDITIONS:
        members = [row for row in rows if row["condition_id"] == condition]
        conditions[condition] = {
            **summarize(members),
            "by_category": {
                str(category): summarize([row for row in members if row["category"] == category])
                for category in (1, 2, 3, 4)
            },
        }
    body = {
        "schema_version": 1,
        "protocol_version": RUN_PROTOCOL_VERSION,
        "row_count": len(rows),
        "overall": summarize(rows),
        "conditions": conditions,
        "score_definitions": {
            "strict_accuracy": "mean(correct=1, partial=0, incorrect=0)",
            "partial_rate": "count(partial)/count(all)",
            "soft_semantic_score": "mean(correct=1, partial=0.5, incorrect=0)",
        },
    }
    return {**body, "summary_sha256": sha256_bytes(canonical_json_bytes(body))}


def finalize(*, output_root: Path, judge_run_id: str, specs: Sequence[PartitionSpec]) -> dict[str, Any]:
    verification = verify(output_root=output_root, judge_run_id=judge_run_id, specs=specs)
    run_root, manifest, partitions, schedule = _open_run(
        output_root=output_root, judge_run_id=judge_run_id, specs=specs
    )
    by_name = _partition_map(partitions)
    rows = [
        _load_completed(run_root, manifest, item, _source_record(by_name, item), _gold(by_name, item))
        for item in schedule
    ]
    if any(row is None for row in rows):
        raise EvidenceValidationError("Finalization found a missing judgment")
    complete = [dict(row) for row in rows if row is not None]
    report = {"summary": _summary(complete), "results": complete}
    _publish_idempotent(run_root / "results.json", report)
    body = {
        "schema_version": 1,
        "protocol_version": RUN_PROTOCOL_VERSION,
        "judge_run_id": judge_run_id,
        "judge_manifest_id": manifest["judge_manifest_id"],
        "verification_id": verification["verification_id"],
        "status": "passed",
        "judged_records": len(complete),
        "summary_sha256": report["summary"]["summary_sha256"],
        "results_sha256": _file_sha256(run_root / "results.json"),
        "self_judge_disclosure": manifest["judge"]["self_judge_disclosure"],
    }
    value = {"final_audit_id": "judge-final-" + sha256_bytes(canonical_json_bytes(body)), **body}
    _publish_idempotent(run_root / "final-audit.json", value)
    _append_event(run_root / "events.jsonl", {"event": "judge_run_finalized", "at": _now(), "final_audit_id": value["final_audit_id"]})
    return value


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Checkpointed main60 anonymous x-test-1 judge")
    parser.add_argument("--repo-root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--judge-run-id", required=True)
    parser.add_argument("--source-system-id", required=True)
    parser.add_argument("--self-judge-disclosure", action="store_true")
    parser.add_argument(
        "--partition", action="append", nargs=5,
        metavar=("NAME", "SOURCE_ROOT", "SOURCE_RUN_ID", "GOLD", "GOLD_SHA256"),
        required=True,
    )
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("prepare")
    sub.add_parser("dry-run")
    sub.add_parser("preflight")
    sub.add_parser("status")
    run_parser = sub.add_parser("run")
    run_parser.add_argument("--through-batch", type=int, choices=range(1, EXPECTED_BATCH_COUNT + 1), required=True)
    sub.add_parser("run-all")
    sub.add_parser("verify")
    sub.add_parser("finalize")
    return parser


def _specs(values: Sequence[Sequence[str]]) -> tuple[PartitionSpec, ...]:
    return tuple(
        PartitionSpec(name, Path(root), run_id, Path(gold), gold_sha)
        for name, root, run_id, gold, gold_sha in values
    )


def main(argv: list[str] | None = None) -> None:
    args = _parser().parse_args(argv)
    specs = _specs(args.partition)
    common = {
        "output_root": args.output_root,
        "judge_run_id": args.judge_run_id,
        "specs": specs,
    }
    if args.command == "prepare":
        path = prepare_run(
            repo_root=args.repo_root,
            source_system_id=args.source_system_id,
            self_judge_disclosure=args.self_judge_disclosure,
            **common,
        )
        result: Mapping[str, Any] = {"status": "prepared", "manifest": str(path)}
    elif args.command == "dry-run":
        result = dry_run(**common)
    elif args.command == "preflight":
        result = preflight(provider=CompatibleChatProvider.from_environment(), **common)
    elif args.command == "status":
        result = write_status(**common)
    elif args.command == "run":
        result = run(
            provider=CompatibleChatProvider.from_environment(),
            through_batch=args.through_batch,
            **common,
        )
    elif args.command == "run-all":
        provider = CompatibleChatProvider.from_environment()
        preflight(provider=provider, **common)
        progress = run(provider=provider, through_batch=EXPECTED_BATCH_COUNT, **common)
        if progress.get("status") == "failed":
            result = progress
        else:
            result = finalize(**common)
    elif args.command == "verify":
        result = verify(**common)
    else:
        result = finalize(**common)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if result.get("status") == "failed":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
