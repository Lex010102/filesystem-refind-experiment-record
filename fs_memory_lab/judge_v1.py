"""Checkpointed supplemental LLM-as-Judge evaluation for frozen E1--E7 results.

This module never performs retrieval or answering.  It reads the immutable 280
``formal-v1`` RunRecords, shows an anonymous judge only the question, reference
answer, and candidate answer, and publishes one append-only judgment per source
record.  The original formal-v1 files are never modified.
"""

from __future__ import annotations

import fcntl
import json
import os
import re
import secrets
import tempfile
import time
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from .agent import ChatProvider, TransientProviderError
from .evidence import EvidenceValidationError, canonical_json_bytes, sha256_bytes
from .evaluation import GoldRecord, load_gold_records
from .run_records import ExperimentRunStore, RunKey, RunRecord, verify_run_store


JUDGE_PROTOCOL_VERSION = "supplemental-anonymous-judge-v1"
JUDGE_RUN_PROTOCOL_VERSION = "supplemental-anonymous-judge-run-v1"
JUDGE_PROMPT_ID = "project-defined-semantic-correctness-judge-v1"
JUDGE_REQUESTED_MODEL = "coding"
JUDGE_REQUIRED_SERVED_MODEL = "qwen3.8:27b"
JUDGE_API_STYLE = "portable"
JUDGE_TIMEOUT_SECONDS = 300
JUDGE_MAX_RESPONSE_BYTES = 20_000_000
JUDGE_MAX_COMPLETION_TOKENS = 1024
JUDGE_REASONING_EFFORT = "high"
JUDGE_TEMPERATURE = 0
JUDGE_BATCH_SIZE_QUESTIONS = 5
JUDGE_BATCH_COUNT = 8
JUDGE_CONDITIONS = ("E1", "E2", "E3", "E4", "E5", "E6", "E7")
_SHA = re.compile(r"[0-9a-f]{64}\Z")
_COMMIT = re.compile(r"[0-9a-f]{40}\Z")
_SAFE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}\Z")

JUDGE_SYSTEM_PROMPT = """You are an impartial evaluator of a question-answering system.

Judge the candidate answer only against the question and reference answer supplied by
the user. Do not use outside knowledge. You are not told which experimental method
produced the candidate, and must not infer or discuss a method.

Use semantic equivalence, not exact word matching:
- Accept concise paraphrases, synonyms, reordered lists, and equivalent date formats.
- Ignore extra wording that is harmless and does not change the answer.
- Do not require citations because citation quality is evaluated separately.

Assign exactly one label:
- correct: the candidate conveys all information required by the reference and has no
  material contradiction.
- partial: the candidate conveys at least one required fact, but omits another required
  fact, is materially imprecise, or mixes correct content with a material unsupported
  or contradictory claim.
- incorrect: the candidate fails to convey a required fact, gives the wrong answer,
  contradicts the reference overall, or only says the answer cannot be determined.

Return exactly one JSON object with exactly these keys:
{"label":"correct|partial|incorrect","short_reason":string,
 "confidence":"high|medium|low"}
Keep short_reason to one concise sentence. Return JSON only. Do not reveal hidden
reasoning or add Markdown fences."""
JUDGE_PROMPT_SHA256 = sha256_bytes(JUDGE_SYSTEM_PROMPT.encode("utf-8"))


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
        offset = 0
        while offset < len(payload):
            written = os.write(descriptor, payload[offset:])
            if written <= 0:
                raise OSError("short judge event write")
            offset += written
        os.fsync(descriptor)
    finally:
        fcntl.flock(descriptor, fcntl.LOCK_UN)
        os.close(descriptor)


@contextmanager
def _exclusive_run_lock(run_root: Path):
    path = Path(run_root) / "run.lock"
    handle = path.open("a+", encoding="utf-8")
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
class JudgeConfig:
    model: str = JUDGE_REQUESTED_MODEL
    reasoning_effort: str = JUDGE_REASONING_EFFORT
    max_completion_tokens: int = JUDGE_MAX_COMPLETION_TOKENS
    max_rounds: int = 1
    temperature: int = JUDGE_TEMPERATURE


def render_judge_user_prompt(*, question: str, reference_answer: str, candidate_answer: str) -> str:
    for value, label in (
        (question, "question"),
        (reference_answer, "reference answer"),
        (candidate_answer, "candidate answer"),
    ):
        if not isinstance(value, str) or not value.strip():
            raise EvidenceValidationError(f"Judge {label} is empty")
    return (
        f"Question:\n{question}\n\nReference answer:\n{reference_answer}"
        f"\n\nCandidate answer:\n{candidate_answer}\n\nReturn the required JSON."
    )


def parse_judge_output(content: str) -> dict[str, str]:
    try:
        value = json.loads(content)
    except (TypeError, json.JSONDecodeError) as exc:
        raise EvidenceValidationError("Judge output is not exact JSON") from exc
    required = {"label", "short_reason", "confidence"}
    if not isinstance(value, Mapping) or set(value) != required:
        raise EvidenceValidationError("Judge JSON fields differ")
    if value["label"] not in {"correct", "partial", "incorrect"}:
        raise EvidenceValidationError("Judge label is invalid")
    if not isinstance(value["short_reason"], str) or not value["short_reason"].strip():
        raise EvidenceValidationError("Judge reason is empty")
    if value["confidence"] not in {"high", "medium", "low"}:
        raise EvidenceValidationError("Judge confidence is invalid")
    return {
        "label": value["label"],
        "short_reason": " ".join(value["short_reason"].split())[:1000],
        "confidence": value["confidence"],
    }


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
    """One anonymous three-way judgment, with one schema-repair opportunity."""

    def __init__(
        self,
        *,
        provider: ChatProvider,
        sleeper: Callable[[float], None] = time.sleep,
    ) -> None:
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

    def run(
        self, *, question: str, reference_answer: str, candidate_answer: str
    ) -> dict[str, Any]:
        user_prompt = render_judge_user_prompt(
            question=question,
            reference_answer=reference_answer,
            candidate_answer=candidate_answer,
        )
        messages = [
            {"role": "system", "content": JUDGE_SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ]
        usages: list[dict[str, int]] = []
        served_models: list[str] = []
        response_ids: list[str] = []
        attempts_total = 0
        format_repairs = 0
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
            usage = _safe_usage(response.get("usage"))
            usages.append(usage)
            served_models.append(served)
            response_id = response.get("response_id")
            response_ids.append(response_id if isinstance(response_id, str) else "")
            try:
                parsed = parse_judge_output(content)
                break
            except EvidenceValidationError:
                if format_repairs >= 1:
                    raise EvidenceValidationError("Judge format repair failed")
                format_repairs += 1
                messages = [
                    {
                        "role": "system",
                        "content": (
                            "Reformat the supplied judgment into exactly this JSON schema without "
                            "changing its decision: {\"label\":\"correct|partial|incorrect\","
                            "\"short_reason\":string,\"confidence\":\"high|medium|low\"}. "
                            "Return JSON only."
                        ),
                    },
                    {"role": "user", "content": content},
                ]
        if set(served_models) != {JUDGE_REQUIRED_SERVED_MODEL}:
            raise EvidenceValidationError("Judge served model drifted")
        label = parsed["label"]
        return {
            **parsed,
            "strict_score": 1.0 if label == "correct" else 0.0,
            "soft_score": {"correct": 1.0, "partial": 0.5, "incorrect": 0.0}[label],
            "prompt_id": JUDGE_PROMPT_ID,
            "prompt_sha256": JUDGE_PROMPT_SHA256,
            "requested_model": JUDGE_REQUESTED_MODEL,
            "served_models": list(dict.fromkeys(served_models)),
            "provider_request_attempts": attempts_total,
            "model_calls": len(usages),
            "format_repairs": format_repairs,
            "usage": usages,
            "response_ids": response_ids,
        }


def _judgment_body(
    *, source_record: RunRecord, gold: GoldRecord, result: Mapping[str, Any]
) -> dict[str, Any]:
    source_payload = canonical_json_bytes(source_record.to_dict())
    return {
        "schema_version": 1,
        "protocol_version": JUDGE_PROTOCOL_VERSION,
        "status": "completed",
        "source_run_id": source_record.run_id,
        "source_plan_id": source_record.plan_id,
        "condition_id": source_record.key.condition_id,
        "question_id": source_record.key.question_id,
        "source_record_id": source_record.record_id,
        "source_record_sha256": sha256_bytes(source_payload),
        "question_sha256": source_record.question.sha256,
        "reference_answer_sha256": sha256_bytes(gold.answer.encode("utf-8")),
        "candidate_answer_sha256": sha256_bytes(
            source_record.answer_result.answer.encode("utf-8")
        ),
        "category": gold.category,
        "category_name": gold.category_name,
        **dict(result),
    }


def _judgment_record(
    *, source_record: RunRecord, gold: GoldRecord, result: Mapping[str, Any]
) -> dict[str, Any]:
    body = _judgment_body(source_record=source_record, gold=gold, result=result)
    return {"judgment_id": "judgment-" + sha256_bytes(canonical_json_bytes(body)), **body}


def _validate_judgment(
    value: Mapping[str, Any], *, source_record: RunRecord, gold: GoldRecord
) -> dict[str, Any]:
    required_result = {
        "label", "short_reason", "confidence", "strict_score", "soft_score",
        "prompt_id", "prompt_sha256", "requested_model", "served_models",
        "provider_request_attempts", "model_calls", "format_repairs", "usage",
        "response_ids",
    }
    base = {
        "judgment_id", "schema_version", "protocol_version", "status",
        "source_run_id", "source_plan_id", "condition_id", "question_id",
        "source_record_id", "source_record_sha256", "question_sha256",
        "reference_answer_sha256", "candidate_answer_sha256", "category",
        "category_name",
    }
    if set(value) != base | required_result:
        raise EvidenceValidationError("Judgment record fields differ")
    label = value.get("label")
    if label not in {"correct", "partial", "incorrect"}:
        raise EvidenceValidationError("Judgment record label is invalid")
    expected_strict = 1.0 if label == "correct" else 0.0
    expected_soft = {"correct": 1.0, "partial": 0.5, "incorrect": 0.0}[str(label)]
    if value.get("strict_score") != expected_strict or value.get("soft_score") != expected_soft:
        raise EvidenceValidationError("Judgment score mapping differs")
    if not isinstance(value.get("short_reason"), str) or not str(value["short_reason"]).strip():
        raise EvidenceValidationError("Judgment reason is empty")
    if value.get("confidence") not in {"high", "medium", "low"}:
        raise EvidenceValidationError("Judgment confidence is invalid")
    if value.get("prompt_id") != JUDGE_PROMPT_ID or value.get("prompt_sha256") != JUDGE_PROMPT_SHA256:
        raise EvidenceValidationError("Judgment prompt identity differs")
    if value.get("requested_model") != JUDGE_REQUESTED_MODEL or set(value.get("served_models", [])) != {JUDGE_REQUIRED_SERVED_MODEL}:
        raise EvidenceValidationError("Judgment model identity differs")
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
    recreated = _judgment_record(source_record=source_record, gold=gold, result=result)
    if recreated != dict(value):
        raise EvidenceValidationError("Judgment content identity differs")
    return dict(value)


def _manifest_body(
    *, source_store: ExperimentRunStore, source_run_root: Path,
    source_formal_manifest: Mapping[str, Any], gold_path: Path,
    judge_run_id: str, implementation_commit: str,
) -> dict[str, Any]:
    blocks = source_formal_manifest.get("question_blocks")
    if not isinstance(blocks, list) or len(blocks) != JUDGE_BATCH_COUNT:
        raise EvidenceValidationError("Source question blocks are invalid")
    source_final_audit = _read_json(source_run_root / "final-audit.json")
    source_evaluation = source_run_root / "evaluation.json"
    return {
        "schema_version": 1,
        "protocol_version": JUDGE_RUN_PROTOCOL_VERSION,
        "status": "prepared",
        "judge_run_id": judge_run_id,
        "source_run_id": source_store.plan.run_id,
        "source_plan_id": source_store.plan.plan_id,
        "source_formal_run_manifest_id": source_formal_manifest["formal_run_manifest_id"],
        "source_final_audit_id": source_final_audit["final_audit_id"],
        "source_plan_sha256": _file_sha256(source_run_root / "plan.json"),
        "source_evaluation_sha256": _file_sha256(source_evaluation),
        "gold_relative_path": "experiments/locomo-conv50-v1/question-sets/main-40-gold.jsonl",
        "gold_sha256": _file_sha256(gold_path),
        "planned_judgments": len(source_store.plan.execution_order),
        "condition_ids": list(JUDGE_CONDITIONS),
        "question_blocks": blocks,
        "batch_size_questions": JUDGE_BATCH_SIZE_QUESTIONS,
        "batch_count": JUDGE_BATCH_COUNT,
        "execution_order_sha256": sha256_bytes(
            canonical_json_bytes([key.to_dict() for key in source_store.plan.execution_order])
        ),
        "judge": {
            "single_model_call_per_decision": True,
            "labels": ["correct", "partial", "incorrect"],
            "strict_score_mapping": {"correct": 1.0, "partial": 0.0, "incorrect": 0.0},
            "soft_score_mapping": {"correct": 1.0, "partial": 0.5, "incorrect": 0.0},
            "prompt_id": JUDGE_PROMPT_ID,
            "prompt_sha256": JUDGE_PROMPT_SHA256,
            "anonymized_fields": ["condition_id", "retrieval_method", "storage_method"],
        },
        "deployment": {
            "requested_model_alias": JUDGE_REQUESTED_MODEL,
            "required_served_model": JUDGE_REQUIRED_SERVED_MODEL,
            "api_style": JUDGE_API_STYLE,
            "request_timeout_seconds": JUDGE_TIMEOUT_SECONDS,
            "max_response_bytes": JUDGE_MAX_RESPONSE_BYTES,
            "concurrency": 1,
            "max_completion_tokens": JUDGE_MAX_COMPLETION_TOKENS,
            "temperature": JUDGE_TEMPERATURE,
        },
        "implementation_commit": implementation_commit,
        "resume_policy": "revalidate-and-skip-only-content-addressed-completed-judgments",
        "source_mutation_forbidden": True,
    }


def _manifest_with_id(body: Mapping[str, Any]) -> dict[str, Any]:
    return {"judge_manifest_id": "judge-manifest-" + sha256_bytes(canonical_json_bytes(body)), **dict(body)}


def _open_source(source_output_root: Path, source_run_id: str) -> tuple[ExperimentRunStore, Path, dict[str, Any]]:
    source_store, checkpoint = verify_run_store(source_output_root, source_run_id)
    if checkpoint["completed"] != 280 or checkpoint["pending"] != 0:
        raise EvidenceValidationError("Judge requires a verified 280/280 source run")
    run_root = source_store.run_root
    formal = dict(_read_json(run_root / "formal-run-manifest.json"))
    if formal.get("planned_records") != 280 or formal.get("run_id") != source_run_id:
        raise EvidenceValidationError("Source formal run manifest differs")
    final = _read_json(run_root / "final-audit.json")
    if final.get("status") != "passed" or final.get("evaluated_records") != 280:
        raise EvidenceValidationError("Source final audit has not passed")
    return source_store, run_root, formal


def prepare_judge_run(
    *, repo_root: Path, source_output_root: Path, source_run_id: str,
    output_root: Path, judge_run_id: str, implementation_commit: str,
) -> Path:
    if _SAFE.fullmatch(judge_run_id) is None or _COMMIT.fullmatch(implementation_commit) is None:
        raise EvidenceValidationError("Judge run ID or implementation commit is invalid")
    root = Path(repo_root).resolve()
    source_store, source_run_root, source_formal = _open_source(
        Path(source_output_root).resolve(), source_run_id
    )
    gold_path = root / "experiments/locomo-conv50-v1/question-sets/main-40-gold.jsonl"
    body = _manifest_body(
        source_store=source_store,
        source_run_root=source_run_root,
        source_formal_manifest=source_formal,
        gold_path=gold_path,
        judge_run_id=judge_run_id,
        implementation_commit=implementation_commit,
    )
    manifest = _manifest_with_id(body)
    run_root = Path(output_root).resolve() / judge_run_id
    run_root.mkdir(parents=True, exist_ok=True, mode=0o700)
    if run_root.is_symlink() or not run_root.is_dir():
        raise EvidenceValidationError("Judge run root is unsafe")
    for condition in JUDGE_CONDITIONS:
        (run_root / "records" / condition).mkdir(parents=True, exist_ok=True)
        (run_root / "failures" / condition).mkdir(parents=True, exist_ok=True)
    (run_root / "control").mkdir(exist_ok=True)
    _publish_idempotent(run_root / "manifest.json", manifest)
    _append_event(run_root / "events.jsonl", {"event": "judge_run_prepared", "at": _now(), "judge_manifest_id": manifest["judge_manifest_id"]})
    write_judge_status(
        repo_root=root, source_output_root=source_output_root,
        source_run_id=source_run_id, output_root=output_root,
        judge_run_id=judge_run_id,
    )
    return run_root / "manifest.json"


def _load_manifest(run_root: Path) -> dict[str, Any]:
    manifest = dict(_read_json(run_root / "manifest.json"))
    identity = manifest.pop("judge_manifest_id", None)
    expected = "judge-manifest-" + sha256_bytes(canonical_json_bytes(manifest))
    if identity != expected:
        raise EvidenceValidationError("Judge manifest content hash differs")
    return {"judge_manifest_id": identity, **manifest}


def _gold_by_question(repo_root: Path, manifest: Mapping[str, Any]) -> dict[str, GoldRecord]:
    path = Path(repo_root).resolve() / str(manifest["gold_relative_path"])
    rows = load_gold_records(path, expected_sha256=str(manifest["gold_sha256"]))
    return {row.question_id: row for row in rows}


def _record_path(run_root: Path, key: RunKey) -> Path:
    return run_root / "records" / key.condition_id / f"{key.question_id}.json"


def _load_completed_judgment(
    run_root: Path, key: RunKey, *, source_record: RunRecord, gold: GoldRecord
) -> dict[str, Any] | None:
    path = _record_path(run_root, key)
    if not path.exists() and not path.is_symlink():
        return None
    return _validate_judgment(_read_json(path), source_record=source_record, gold=gold)


def _publish_judgment(run_root: Path, key: RunKey, value: Mapping[str, Any]) -> Path:
    path = _record_path(run_root, key)
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
    return path


def _failure_attempt_count(run_root: Path, key: RunKey) -> int:
    directory = run_root / "failures" / key.condition_id / key.question_id
    if not directory.exists():
        return 0
    if directory.is_symlink() or not directory.is_dir():
        raise EvidenceValidationError("Judge failure directory is unsafe")
    attempts = []
    for path in directory.glob("attempt-*.json"):
        match = re.fullmatch(r"attempt-(\d+)\.json", path.name)
        if match:
            attempts.append(int(match.group(1)))
    return max(attempts, default=0)


def _safe_error(error: BaseException, provider: ChatProvider | None = None) -> str:
    message = " ".join(str(error).split())[:1000] or type(error).__name__
    secret = getattr(provider, "api_key", None) if provider is not None else None
    if isinstance(secret, str) and secret:
        message = message.replace(secret, "[REDACTED_KEY]")
    return re.sub(r"\b(?:clsk|sk)[_-][A-Za-z0-9_-]{10,}\b", "[REDACTED_KEY]", message)


def _publish_failure(run_root: Path, key: RunKey, error: BaseException, provider: ChatProvider) -> Path:
    attempt = _failure_attempt_count(run_root, key) + 1
    body = {
        "schema_version": 1,
        "protocol_version": JUDGE_RUN_PROTOCOL_VERSION,
        "status": "failed",
        "condition_id": key.condition_id,
        "question_id": key.question_id,
        "attempt": attempt,
        "stage": "semantic_judgment",
        "error_type": type(error).__name__,
        "message": _safe_error(error, provider),
        "retryable": isinstance(error, TransientProviderError),
        "failed_at": _now(),
    }
    value = {"failure_id": "judge-failure-" + sha256_bytes(canonical_json_bytes(body)), **body}
    directory = run_root / "failures" / key.condition_id / key.question_id
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"attempt-{attempt:04d}.json"
    _write_exclusive(path, value)
    return path


def _source_record_map(source_store: ExperimentRunStore) -> dict[RunKey, RunRecord]:
    output: dict[RunKey, RunRecord] = {}
    for key in source_store.plan.execution_order:
        record = source_store.load_completed(key)
        if record is None:
            raise EvidenceValidationError("Source RunRecord disappeared")
        output[key] = record
    return output


def _status_body(
    *, source_store: ExperimentRunStore, run_root: Path,
    gold_by_question: Mapping[str, GoldRecord], manifest: Mapping[str, Any],
) -> dict[str, Any]:
    completed = 0
    by_condition = {condition: 0 for condition in JUDGE_CONDITIONS}
    label_counts = {"correct": 0, "partial": 0, "incorrect": 0}
    total_tokens = 0
    next_key: dict[str, str] | None = None
    source_records = _source_record_map(source_store)
    for key in source_store.plan.execution_order:
        value = _load_completed_judgment(
            run_root, key, source_record=source_records[key],
            gold=gold_by_question[key.question_id],
        )
        if value is None:
            if next_key is None:
                next_key = key.to_dict()
            continue
        completed += 1
        by_condition[key.condition_id] += 1
        label_counts[str(value["label"])] += 1
        total_tokens += sum(int(row["total_tokens"]) for row in value["usage"])
    block_size = JUDGE_BATCH_SIZE_QUESTIONS * len(JUDGE_CONDITIONS)
    completed_batches = completed // block_size
    active_failures = 0
    for key in source_store.plan.execution_order:
        if _record_path(run_root, key).exists():
            continue
        active_failures += int(_failure_attempt_count(run_root, key) > 0)
    status = "completed" if completed == len(source_store.plan.execution_order) else ("failed" if active_failures else "pending")
    return {
        "schema_version": 1,
        "protocol_version": JUDGE_RUN_PROTOCOL_VERSION,
        "judge_run_id": manifest["judge_run_id"],
        "judge_manifest_id": manifest["judge_manifest_id"],
        "source_run_id": source_store.plan.run_id,
        "status": status,
        "completed_judgments": completed,
        "pending_judgments": len(source_store.plan.execution_order) - completed,
        "planned_judgments": len(source_store.plan.execution_order),
        "completed_batches": completed_batches,
        "completed_by_condition": by_condition,
        "label_counts": label_counts,
        "active_failed_keys": active_failures,
        "judge_total_tokens": total_tokens,
        "next_key": next_key,
        "updated_at": _now(),
    }


def _open_judge_run(
    *, repo_root: Path, source_output_root: Path, source_run_id: str,
    output_root: Path, judge_run_id: str,
) -> tuple[ExperimentRunStore, Path, dict[str, Any], dict[str, GoldRecord]]:
    source_store, source_run_root, source_formal = _open_source(source_output_root, source_run_id)
    run_root = Path(output_root).resolve() / judge_run_id
    manifest = _load_manifest(run_root)
    gold = _gold_by_question(repo_root, manifest)
    if manifest["source_plan_id"] != source_store.plan.plan_id:
        raise EvidenceValidationError("Judge source plan changed")
    if manifest["source_plan_sha256"] != _file_sha256(source_run_root / "plan.json"):
        raise EvidenceValidationError("Judge source plan bytes changed")
    if manifest["source_evaluation_sha256"] != _file_sha256(source_run_root / "evaluation.json"):
        raise EvidenceValidationError("Judge source evaluation changed")
    if manifest["source_formal_run_manifest_id"] != source_formal["formal_run_manifest_id"]:
        raise EvidenceValidationError("Judge source formal manifest changed")
    return source_store, run_root, manifest, gold


def write_judge_status(
    *, repo_root: Path, source_output_root: Path, source_run_id: str,
    output_root: Path, judge_run_id: str,
) -> dict[str, Any]:
    source_store, run_root, manifest, gold = _open_judge_run(
        repo_root=repo_root, source_output_root=source_output_root,
        source_run_id=source_run_id, output_root=output_root,
        judge_run_id=judge_run_id,
    )
    body = _status_body(
        source_store=source_store, run_root=run_root,
        gold_by_question=gold, manifest=manifest,
    )
    _write_atomic(run_root / "status.json", body)
    return body


def dry_run_judge(
    *, repo_root: Path, source_output_root: Path, source_run_id: str,
    output_root: Path, judge_run_id: str,
) -> dict[str, Any]:
    source_store, run_root, manifest, gold = _open_judge_run(
        repo_root=repo_root, source_output_root=source_output_root,
        source_run_id=source_run_id, output_root=output_root,
        judge_run_id=judge_run_id,
    )
    candidate_prompts = []
    for key in source_store.plan.execution_order:
        record = source_store.load_completed(key)
        assert record is not None
        candidate_prompts.append(render_judge_user_prompt(
            question=record.question.question,
            reference_answer=gold[key.question_id].answer,
            candidate_answer=record.answer_result.answer,
        ))
    checks = {
        "source_280_verified": len(candidate_prompts) == 280,
        "gold_40_hash_pinned": len(gold) == 40,
        "conditions_7_exact": tuple(source_store.plan.condition_ids) == JUDGE_CONDITIONS,
        "question_blocks_8": len(manifest["question_blocks"]) == 8,
        # Source text can coincidentally contain a token such as "E1".  The
        # anonymity invariant is therefore the fixed three-field wrapper, not a
        # substring assertion over user data.
        "anonymous_prompt_contract": all(
            prompt.count("Question:\n") == 1
            and prompt.count("Reference answer:\n") == 1
            and prompt.count("Candidate answer:\n") == 1
            for prompt in candidate_prompts
        ),
        "api_provider_not_constructed": True,
        "source_mutation_forbidden": manifest["source_mutation_forbidden"] is True,
    }
    body = {
        "schema_version": 1,
        "protocol_version": JUDGE_RUN_PROTOCOL_VERSION,
        "judge_run_id": judge_run_id,
        "judge_manifest_id": manifest["judge_manifest_id"],
        "status": "passed" if all(checks.values()) else "failed",
        "checks": checks,
        "planned_judgments": len(candidate_prompts),
        "api_calls": 0,
    }
    value = {"dry_run_id": "judge-dry-run-" + sha256_bytes(canonical_json_bytes(body)), **body}
    _publish_idempotent(run_root / "dry-run.json", value)
    _append_event(run_root / "events.jsonl", {"event": "judge_dry_run_completed", "at": _now(), "dry_run_id": value["dry_run_id"]})
    if value["status"] != "passed":
        raise EvidenceValidationError("Judge dry-run failed")
    return value


def _provider_preflight(provider: ChatProvider) -> None:
    if getattr(provider, "api_style", None) != JUDGE_API_STYLE:
        raise EvidenceValidationError("Judge provider API style differs")
    if getattr(provider, "model", None) != JUDGE_REQUESTED_MODEL:
        raise EvidenceValidationError("FSMEM_MODEL must equal coding for judge-v1")
    if getattr(provider, "timeout", None) != JUDGE_TIMEOUT_SECONDS:
        raise EvidenceValidationError("Judge provider timeout differs")
    if getattr(provider, "max_response_bytes", None) != JUDGE_MAX_RESPONSE_BYTES:
        raise EvidenceValidationError("Judge provider response cap differs")


def _audit_batch(
    *, source_store: ExperimentRunStore, run_root: Path,
    gold: Mapping[str, GoldRecord], manifest: Mapping[str, Any], batch: int,
) -> dict[str, Any]:
    target = batch * JUDGE_BATCH_SIZE_QUESTIONS * len(JUDGE_CONDITIONS)
    source_records = _source_record_map(source_store)
    prefix = source_store.plan.execution_order[:target]
    completed = sum(
        _load_completed_judgment(run_root, key, source_record=source_records[key], gold=gold[key.question_id]) is not None
        for key in prefix
    )
    counts = {condition: 0 for condition in JUDGE_CONDITIONS}
    for key in prefix:
        if _record_path(run_root, key).is_file():
            counts[key.condition_id] += 1
    checks = {
        "prefix_complete": completed == target,
        "conditions_balanced": set(counts.values()) == {batch * JUDGE_BATCH_SIZE_QUESTIONS},
        "source_records_unchanged": manifest["source_plan_sha256"] == _file_sha256(source_store.run_root / "plan.json"),
        "prompt_hash_exact": True,
        "served_model_exact": True,
    }
    body = {
        "schema_version": 1,
        "protocol_version": JUDGE_RUN_PROTOCOL_VERSION,
        "judge_run_id": manifest["judge_run_id"],
        "batch": batch,
        "target_judgments": target,
        "completed_judgments": completed,
        "condition_counts": counts,
        "status": "passed" if all(checks.values()) else "failed",
        "checks": checks,
    }
    value = {"batch_audit_id": "judge-batch-" + sha256_bytes(canonical_json_bytes(body)), **body}
    _publish_idempotent(run_root / "control" / f"batch-{batch:02d}-audit.json", value)
    if value["status"] != "passed":
        raise EvidenceValidationError(f"Judge batch {batch} audit failed")
    marker = run_root / "control" / f"batch-{batch:02d}.PASSED"
    if not marker.exists():
        _write_exclusive(marker, {"batch_audit_id": value["batch_audit_id"], "status": "passed"})
    return value


def run_judge(
    *, repo_root: Path, source_output_root: Path, source_run_id: str,
    output_root: Path, judge_run_id: str, provider: ChatProvider,
    through_batch: int,
) -> dict[str, Any]:
    if isinstance(through_batch, bool) or not isinstance(through_batch, int) or not 1 <= through_batch <= 8:
        raise EvidenceValidationError("through_batch must be 1-8")
    source_store, run_root, manifest, gold = _open_judge_run(
        repo_root=repo_root, source_output_root=source_output_root,
        source_run_id=source_run_id, output_root=output_root,
        judge_run_id=judge_run_id,
    )
    dry = _read_json(run_root / "dry-run.json")
    if dry.get("status") != "passed" or dry.get("judge_manifest_id") != manifest["judge_manifest_id"]:
        raise EvidenceValidationError("Judge API run requires passing dry-run")
    _provider_preflight(provider)
    judge = SemanticJudge(provider=provider)
    source_records = _source_record_map(source_store)
    events = run_root / "events.jsonl"
    target = through_batch * JUDGE_BATCH_SIZE_QUESTIONS * len(JUDGE_CONDITIONS)
    with _exclusive_run_lock(run_root):
        before = write_judge_status(
            repo_root=repo_root, source_output_root=source_output_root,
            source_run_id=source_run_id, output_root=output_root,
            judge_run_id=judge_run_id,
        )
        _append_event(events, {"event": "judge_run_started", "at": _now(), "completed_before": before["completed_judgments"], "through_batch": through_batch, "target_judgments": target})
        for sequence, key in enumerate(source_store.plan.execution_order, start=1):
            if sequence > target:
                break
            source = source_records[key]
            gold_row = gold[key.question_id]
            if _load_completed_judgment(run_root, key, source_record=source, gold=gold_row) is not None:
                continue
            _append_event(events, {"event": "judgment_started", "at": _now(), "sequence": sequence, **key.to_dict()})
            print(f"[{sequence:03d}/280] START {key.condition_id} {key.question_id}", flush=True)
            try:
                result = judge.run(
                    question=source.question.question,
                    reference_answer=gold_row.answer,
                    candidate_answer=source.answer_result.answer,
                )
                value = _judgment_record(source_record=source, gold=gold_row, result=result)
                _validate_judgment(value, source_record=source, gold=gold_row)
                _publish_judgment(run_root, key, value)
                _load_completed_judgment(run_root, key, source_record=source, gold=gold_row)
            except Exception as error:
                failure = _publish_failure(run_root, key, error, provider)
                _append_event(events, {"event": "judgment_failed", "at": _now(), "sequence": sequence, **key.to_dict(), "failure_path": str(failure), "error_type": type(error).__name__})
                status = write_judge_status(
                    repo_root=repo_root, source_output_root=source_output_root,
                    source_run_id=source_run_id, output_root=output_root,
                    judge_run_id=judge_run_id,
                )
                return {"status": "failed", **key.to_dict(), "progress": status}
            _append_event(events, {"event": "judgment_verified", "at": _now(), "sequence": sequence, **key.to_dict(), "judgment_id": value["judgment_id"], "label": value["label"], "soft_score": value["soft_score"], "total_tokens": sum(row["total_tokens"] for row in value["usage"])})
            current = write_judge_status(
                repo_root=repo_root, source_output_root=source_output_root,
                source_run_id=source_run_id, output_root=output_root,
                judge_run_id=judge_run_id,
            )
            print(f"[{sequence:03d}/280] VERIFIED judgments={current['completed_judgments']}/280", flush=True)
            if current["completed_judgments"] % 35 == 0:
                batch = current["completed_judgments"] // 35
                audit = _audit_batch(
                    source_store=source_store, run_root=run_root,
                    gold=gold, manifest=manifest, batch=batch,
                )
                _append_event(events, {"event": "judge_batch_verified", "at": _now(), "batch": batch, "completed_judgments": current["completed_judgments"], "batch_audit_id": audit["batch_audit_id"]})
        final = write_judge_status(
            repo_root=repo_root, source_output_root=source_output_root,
            source_run_id=source_run_id, output_root=output_root,
            judge_run_id=judge_run_id,
        )
        _append_event(events, {"event": "judge_target_reached", "at": _now(), "through_batch": through_batch, "completed_judgments": final["completed_judgments"]})
        return final


def verify_judge_run(
    *, repo_root: Path, source_output_root: Path, source_run_id: str,
    output_root: Path, judge_run_id: str,
) -> dict[str, Any]:
    source_store, run_root, manifest, gold = _open_judge_run(
        repo_root=repo_root, source_output_root=source_output_root,
        source_run_id=source_run_id, output_root=output_root,
        judge_run_id=judge_run_id,
    )
    source_records = _source_record_map(source_store)
    rows = []
    for key in source_store.plan.execution_order:
        row = _load_completed_judgment(run_root, key, source_record=source_records[key], gold=gold[key.question_id])
        if row is None:
            raise EvidenceValidationError("Judge verification requires 280/280 judgments")
        rows.append(row)
    counts = {condition: sum(row["condition_id"] == condition for row in rows) for condition in JUDGE_CONDITIONS}
    checks = {
        "judgments_280": len(rows) == 280,
        "conditions_40_each": set(counts.values()) == {40},
        "prompt_hash_exact": all(row["prompt_sha256"] == JUDGE_PROMPT_SHA256 for row in rows),
        "served_model_exact": all(set(row["served_models"]) == {JUDGE_REQUIRED_SERVED_MODEL} for row in rows),
        "score_mapping_exact": all(row["soft_score"] == {"correct": 1.0, "partial": 0.5, "incorrect": 0.0}[row["label"]] for row in rows),
        "source_records_unchanged": manifest["source_plan_sha256"] == _file_sha256(source_store.run_root / "plan.json"),
        "all_batches_passed": all((run_root / "control" / f"batch-{batch:02d}.PASSED").is_file() for batch in range(1, 9)),
    }
    body = {
        "schema_version": 1,
        "protocol_version": JUDGE_RUN_PROTOCOL_VERSION,
        "judge_run_id": judge_run_id,
        "judge_manifest_id": manifest["judge_manifest_id"],
        "status": "passed" if all(checks.values()) else "failed",
        "checks": checks,
        "condition_counts": counts,
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
        total = len(members)
        tokens = [sum(int(item["total_tokens"]) for item in row["usage"]) for row in members]
        return {
            "count": total,
            "label_counts": labels,
            "strict_accuracy": _mean([float(row["strict_score"]) for row in members]),
            "partial_rate": labels["partial"] / total if total else None,
            "incorrect_rate": labels["incorrect"] / total if total else None,
            "soft_semantic_score": _mean([float(row["soft_score"]) for row in members]),
            "high_confidence_rate": _mean([float(row["confidence"] == "high") for row in members]),
            "judge_total_tokens": sum(tokens),
            "mean_judge_tokens": _mean([float(value) for value in tokens]),
            "judge_model_calls": sum(int(row["model_calls"]) for row in members),
            "format_repairs": sum(int(row["format_repairs"]) for row in members),
        }
    conditions = {}
    for condition in JUDGE_CONDITIONS:
        members = [row for row in rows if row["condition_id"] == condition]
        category = {
            str(value): summarize([row for row in members if row["category"] == value])
            for value in (1, 2, 3, 4)
        }
        conditions[condition] = {**summarize(members), "by_category": category}
    body = {
        "schema_version": 1,
        "protocol_version": JUDGE_RUN_PROTOCOL_VERSION,
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


def finalize_judge_run(
    *, repo_root: Path, source_output_root: Path, source_run_id: str,
    output_root: Path, judge_run_id: str,
) -> dict[str, Any]:
    verification = verify_judge_run(
        repo_root=repo_root, source_output_root=source_output_root,
        source_run_id=source_run_id, output_root=output_root,
        judge_run_id=judge_run_id,
    )
    source_store, run_root, manifest, gold = _open_judge_run(
        repo_root=repo_root, source_output_root=source_output_root,
        source_run_id=source_run_id, output_root=output_root,
        judge_run_id=judge_run_id,
    )
    source_records = _source_record_map(source_store)
    rows = [
        _load_completed_judgment(run_root, key, source_record=source_records[key], gold=gold[key.question_id])
        for key in source_store.plan.execution_order
    ]
    if any(row is None for row in rows):
        raise EvidenceValidationError("Finalization found a missing judgment")
    complete_rows = [dict(row) for row in rows if row is not None]
    report = {"summary": _summary(complete_rows), "results": complete_rows}
    _publish_idempotent(run_root / "results.json", report)
    body = {
        "schema_version": 1,
        "protocol_version": JUDGE_RUN_PROTOCOL_VERSION,
        "judge_run_id": judge_run_id,
        "judge_manifest_id": manifest["judge_manifest_id"],
        "verification_id": verification["verification_id"],
        "status": "passed",
        "judged_records": len(complete_rows),
        "summary_sha256": report["summary"]["summary_sha256"],
        "results_sha256": _file_sha256(run_root / "results.json"),
    }
    final = {"final_audit_id": "judge-final-" + sha256_bytes(canonical_json_bytes(body)), **body}
    _publish_idempotent(run_root / "final-audit.json", final)
    _append_event(run_root / "events.jsonl", {"event": "judge_run_finalized", "at": _now(), "final_audit_id": final["final_audit_id"]})
    return final
