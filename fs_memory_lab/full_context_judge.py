"""Anonymous x-test-1 LLM-as-Judge scoring for one Full Context main-60 run.

This is a one-condition adapter around the exact judge used for the archived
Model 1 and Model 2 main-60 runs.  The judge sees only question, reference
answer, and candidate answer.  Source text and experimental identity are never
included in the prompt.
"""

from __future__ import annotations

import argparse
import fcntl
import json
import os
import re
from collections import Counter
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Mapping, Sequence

from .agent import CompatibleChatProvider
from .evidence import EvidenceValidationError, canonical_json_bytes, sha256_bytes
from .full_context_runner import (
    FULL_CONTEXT_CONDITION_ID,
    FULL_CONTEXT_MAIN_QUESTION_SET,
    _load_full_context_gold,
    full_context_record_from_mapping,
)
from .judge_main60 import (
    API_STYLE,
    BATCH_SIZE_QUESTIONS,
    MAX_COMPLETION_TOKENS,
    MAX_RESPONSE_BYTES,
    REQUESTED_MODEL,
    REQUIRED_SERVED_MODEL,
    SemanticJudge,
    TEMPERATURE,
    TIMEOUT_SECONDS,
)
from .judge_v1 import JUDGE_PROMPT_ID, JUDGE_PROMPT_SHA256


PROTOCOL_VERSION = "b3-full-context-anonymous-judge-x-test1-v1"
RUN_PROTOCOL_VERSION = "b3-full-context-anonymous-judge-run-v1"
EXPECTED_COUNT = 60
EXPECTED_BATCHES = 12
_SAFE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}\Z")
_KEY = re.compile(r"\b(?:clsk|sk)[_-][A-Za-z0-9_-]{10,}\b")


def _read_json(path: Path) -> dict[str, Any]:
    lexical = Path(path)
    if lexical.is_symlink() or not lexical.is_file():
        raise EvidenceValidationError(f"Unsafe or missing Judge JSON: {lexical}")
    value = json.loads(lexical.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise EvidenceValidationError("Judge JSON must be an object")
    return value


def _sha(path: Path) -> str:
    lexical = Path(path)
    if lexical.is_symlink() or not lexical.is_file():
        raise EvidenceValidationError(f"Unsafe or missing Judge input: {lexical}")
    return sha256_bytes(lexical.read_bytes())


def _publish(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() or path.is_symlink():
        if _read_json(path) != dict(value):
            raise EvidenceValidationError(f"Existing Judge artifact differs: {path}")
        return
    payload = canonical_json_bytes(value) + b"\n"
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(path, flags, 0o600)
    try:
        offset = 0
        while offset < len(payload):
            written = os.write(descriptor, payload[offset:])
            if written <= 0:
                raise OSError("short Judge artifact write")
            offset += written
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


@contextmanager
def _lock(run_root: Path):
    handle = (run_root / "run.lock").open("a+", encoding="utf-8")
    try:
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise EvidenceValidationError("Another Full Context Judge holds run.lock") from exc
        yield
    finally:
        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        handle.close()


def _safe_error(error: Exception, provider: Any) -> str:
    text = " ".join(str(error).split())[:600]
    secret = getattr(provider, "api_key", None)
    if isinstance(secret, str) and secret:
        text = text.replace(secret, "[REDACTED_KEY]")
    return _KEY.sub("[REDACTED_KEY]", text)


def _source_rows(repo_root: Path, source_root: Path) -> tuple[dict[str, Any], ...]:
    manifest = _read_json(source_root / "run-manifest.json")
    audit = _read_json(source_root / "pre-gold-audit.json")
    evaluation = _read_json(source_root / "evaluation.json")
    if (
        manifest.get("question_set", {}).get("name") != FULL_CONTEXT_MAIN_QUESTION_SET
        or manifest.get("question_set", {}).get("question_count") != EXPECTED_COUNT
        or audit.get("status") != "passed"
        or audit.get("record_count") != EXPECTED_COUNT
        or evaluation.get("count") != EXPECTED_COUNT
    ):
        raise EvidenceValidationError("Full Context Judge source is not a verified main-60 run")
    gold = {
        row.question_id: row
        for row in _load_full_context_gold(repo_root, FULL_CONTEXT_MAIN_QUESTION_SET)
    }
    rows: list[dict[str, Any]] = []
    for position, question in enumerate(manifest["question_set"]["question_order"], start=1):
        question_id = question["question_id"]
        path = source_root / "records" / FULL_CONTEXT_CONDITION_ID / question_id / "record.json"
        record = full_context_record_from_mapping(_read_json(path))
        reference = gold.get(question_id)
        if reference is None or record.question.question_id != question_id:
            raise EvidenceValidationError("Full Context Judge source order or gold differs")
        rows.append(
            {
                "position": position,
                "question_id": question_id,
                "question": record.question.question,
                "question_sha256": record.question.sha256,
                "reference_answer": reference.answer,
                "reference_answer_sha256": sha256_bytes(reference.answer.encode("utf-8")),
                "candidate_answer": record.answer_result.answer,
                "candidate_answer_sha256": sha256_bytes(
                    record.answer_result.answer.encode("utf-8")
                ),
                "category": reference.category,
                "category_name": reference.category_name,
                "source_record_id": record.record_id,
                "source_record_sha256": _sha(path),
            }
        )
    if len(rows) != EXPECTED_COUNT or len({row["question_id"] for row in rows}) != EXPECTED_COUNT:
        raise EvidenceValidationError("Full Context Judge requires 60 unique source rows")
    return tuple(rows)


def _manifest(repo_root: Path, source_root: Path, judge_run_id: str) -> dict[str, Any]:
    if _SAFE.fullmatch(judge_run_id) is None:
        raise EvidenceValidationError("Judge run ID is unsafe")
    rows = _source_rows(repo_root, source_root)
    source_manifest = _read_json(source_root / "run-manifest.json")
    body = {
        "schema_version": 1,
        "protocol_version": RUN_PROTOCOL_VERSION,
        "status": "prepared",
        "judge_run_id": judge_run_id,
        "source_run_id": source_manifest["run_id"],
        "source_manifest_id": source_manifest["manifest_id"],
        "source_manifest_sha256": _sha(source_root / "run-manifest.json"),
        "source_pre_gold_audit_sha256": _sha(source_root / "pre-gold-audit.json"),
        "source_evaluation_sha256": _sha(source_root / "evaluation.json"),
        "source_mutation_forbidden": True,
        "contains_source_text": False,
        "condition_id": FULL_CONTEXT_CONDITION_ID,
        "planned_judgments": EXPECTED_COUNT,
        "batch_size_questions": BATCH_SIZE_QUESTIONS,
        "batch_count": EXPECTED_BATCHES,
        "execution_order_sha256": sha256_bytes(
            canonical_json_bytes([row["question_id"] for row in rows])
        ),
        "judge": {
            "prompt_id": JUDGE_PROMPT_ID,
            "prompt_sha256": JUDGE_PROMPT_SHA256,
            "labels": ["correct", "partial", "incorrect"],
            "strict_score_mapping": {"correct": 1.0, "partial": 0.0, "incorrect": 0.0},
            "soft_score_mapping": {"correct": 1.0, "partial": 0.5, "incorrect": 0.0},
            "anonymized_fields": ["condition_id", "retrieval_method", "storage_method"],
            "self_judge_disclosure": False,
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
            "adapter_sha256": _sha(Path(__file__)),
            "judge_module_sha256": _sha(repo_root / "fs_memory_lab/judge_main60.py"),
            "prompt_module_sha256": _sha(repo_root / "fs_memory_lab/judge_v1.py"),
        },
    }
    return {"judge_manifest_id": "judge-manifest-" + sha256_bytes(canonical_json_bytes(body)), **body}


def prepare(repo_root: Path, source_root: Path, output_root: Path, judge_run_id: str) -> Path:
    run_root = output_root / judge_run_id
    run_root.mkdir(parents=True, exist_ok=True)
    manifest = _manifest(repo_root, source_root, judge_run_id)
    path = run_root / "manifest.json"
    _publish(path, manifest)
    checks = {
        "source_60_verified": True,
        "anonymous_prompt_contract": True,
        "prompt_hash_reused_exactly": manifest["judge"]["prompt_sha256"] == JUDGE_PROMPT_SHA256,
        "api_provider_not_constructed": True,
        "source_mutation_forbidden": True,
        "batches_12_of_5": manifest["batch_count"] == 12 and manifest["batch_size_questions"] == 5,
    }
    _publish(
        run_root / "dry-run.json",
        {
            "schema_version": 1,
            "protocol_version": RUN_PROTOCOL_VERSION,
            "status": "passed" if all(checks.values()) else "failed",
            "judge_manifest_id": manifest["judge_manifest_id"],
            "planned_judgments": EXPECTED_COUNT,
            "checks": checks,
            "api_calls": 0,
        },
    )
    return path


def _provider_preflight(provider: Any) -> None:
    if (
        getattr(provider, "api_style", None) != API_STYLE
        or getattr(provider, "model", None) != REQUESTED_MODEL
        or getattr(provider, "timeout", None) != TIMEOUT_SECONDS
        or getattr(provider, "max_response_bytes", None) != MAX_RESPONSE_BYTES
    ):
        raise EvidenceValidationError("Full Context Judge provider contract differs")


def _static(row: Mapping[str, Any], manifest: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "protocol_version": PROTOCOL_VERSION,
        "status": "completed",
        "judge_manifest_id": manifest["judge_manifest_id"],
        "source_run_id": manifest["source_run_id"],
        "source_record_id": row["source_record_id"],
        "source_record_sha256": row["source_record_sha256"],
        "condition_id": FULL_CONTEXT_CONDITION_ID,
        "position": row["position"],
        "question_id": row["question_id"],
        "question_sha256": row["question_sha256"],
        "reference_answer_sha256": row["reference_answer_sha256"],
        "candidate_answer_sha256": row["candidate_answer_sha256"],
        "category": row["category"],
        "category_name": row["category_name"],
    }


def _validate(value: Mapping[str, Any], row: Mapping[str, Any], manifest: Mapping[str, Any]) -> None:
    static = _static(row, manifest)
    if any(value.get(key) != expected for key, expected in static.items()):
        raise EvidenceValidationError("Full Context judgment source identity differs")
    label = value.get("label")
    if (
        label not in {"correct", "partial", "incorrect"}
        or value.get("prompt_id") != JUDGE_PROMPT_ID
        or value.get("prompt_sha256") != JUDGE_PROMPT_SHA256
        or value.get("requested_model") != REQUESTED_MODEL
        or value.get("served_models") != [REQUIRED_SERVED_MODEL]
        or value.get("strict_score") != (1.0 if label == "correct" else 0.0)
        or value.get("soft_score")
        != {"correct": 1.0, "partial": 0.5, "incorrect": 0.0}[label]
    ):
        raise EvidenceValidationError("Full Context judgment contract differs")
    body = {key: item for key, item in value.items() if key != "judgment_id"}
    if value.get("judgment_id") != "judgment-" + sha256_bytes(canonical_json_bytes(body)):
        raise EvidenceValidationError("Full Context judgment identity differs")


def _summarize(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    labels = Counter(str(row["label"]) for row in rows)
    tokens = [sum(int(item["total_tokens"]) for item in row["usage"]) for row in rows]
    return {
        "count": len(rows),
        "label_counts": {name: labels[name] for name in ("correct", "partial", "incorrect")},
        "strict_accuracy": sum(float(row["strict_score"]) for row in rows) / len(rows),
        "partial_rate": labels["partial"] / len(rows),
        "incorrect_rate": labels["incorrect"] / len(rows),
        "soft_semantic_score": sum(float(row["soft_score"]) for row in rows) / len(rows),
        "high_confidence_rate": sum(row["confidence"] == "high" for row in rows) / len(rows),
        "judge_total_tokens": sum(tokens),
        "mean_judge_tokens": sum(tokens) / len(tokens),
        "judge_model_calls": sum(int(row["model_calls"]) for row in rows),
        "format_repairs": sum(int(row["format_repairs"]) for row in rows),
    }


def run(repo_root: Path, source_root: Path, output_root: Path, judge_run_id: str, provider: Any) -> dict[str, Any]:
    run_root = output_root / judge_run_id
    manifest = _manifest(repo_root, source_root, judge_run_id)
    if _read_json(run_root / "manifest.json") != manifest or _read_json(run_root / "dry-run.json").get("status") != "passed":
        raise EvidenceValidationError("Full Context Judge prepare/dry-run differs")
    rows = _source_rows(repo_root, source_root)
    _provider_preflight(provider)
    preflight_path = run_root / "preflight.json"
    judge = SemanticJudge(provider=provider)
    if not preflight_path.exists():
        synthetic = judge.run(
            question="What is two plus two?",
            reference_answer="four",
            candidate_answer="four",
        )
        if synthetic["label"] != "correct":
            raise EvidenceValidationError("Full Context Judge synthetic preflight differs")
        _publish(
            preflight_path,
            {
                "schema_version": 1,
                "protocol_version": RUN_PROTOCOL_VERSION,
                "status": "passed",
                "judge_manifest_id": manifest["judge_manifest_id"],
                "requested_model": REQUESTED_MODEL,
                "served_model": REQUIRED_SERVED_MODEL,
                "prompt_sha256": JUDGE_PROMPT_SHA256,
                "synthetic_decision_correct": True,
                "model_calls": synthetic["model_calls"],
                "format_repairs": synthetic["format_repairs"],
                "total_tokens": sum(item["total_tokens"] for item in synthetic["usage"]),
                "contains_source_text": False,
            },
        )
    preflight = _read_json(preflight_path)
    if preflight.get("status") != "passed" or preflight.get("served_model") != REQUIRED_SERVED_MODEL:
        raise EvidenceValidationError("Full Context Judge preflight differs")
    with _lock(run_root):
        for row in rows:
            path = run_root / "records" / f"{int(row['position']):02d}-{row['question_id']}.json"
            if path.exists():
                _validate(_read_json(path), row, manifest)
                continue
            print(f"[{row['position']:02d}/{EXPECTED_COUNT}] START", flush=True)
            try:
                result = judge.run(
                    question=str(row["question"]),
                    reference_answer=str(row["reference_answer"]),
                    candidate_answer=str(row["candidate_answer"]),
                )
            except Exception as error:
                _publish(
                    run_root / "failures" / f"{int(row['position']):02d}-{row['question_id']}.json",
                    {
                        "schema_version": 1,
                        "protocol_version": RUN_PROTOCOL_VERSION,
                        "status": "failed",
                        "position": row["position"],
                        "question_id": row["question_id"],
                        "error_type": type(error).__name__,
                        "message": _safe_error(error, provider),
                    },
                )
                return {"status": "failed", "position": row["position"], "question_id": row["question_id"]}
            body = {**_static(row, manifest), **result}
            value = {"judgment_id": "judgment-" + sha256_bytes(canonical_json_bytes(body)), **body}
            _validate(value, row, manifest)
            _publish(path, value)
            print(f"[{row['position']:02d}/{EXPECTED_COUNT}] VERIFIED {value['label']}", flush=True)
            if int(row["position"]) % BATCH_SIZE_QUESTIONS == 0:
                batch = int(row["position"]) // BATCH_SIZE_QUESTIONS
                _publish(
                    run_root / "control" / f"batch-{batch:02d}.PASSED",
                    {
                        "schema_version": 1,
                        "protocol_version": RUN_PROTOCOL_VERSION,
                        "status": "passed",
                        "batch": batch,
                        "completed_judgments": batch * BATCH_SIZE_QUESTIONS,
                        "prompt_hash_exact": True,
                        "served_model_exact": True,
                        "source_records_unchanged": True,
                    },
                )
    completed = []
    for row in rows:
        value = _read_json(run_root / "records" / f"{int(row['position']):02d}-{row['question_id']}.json")
        _validate(value, row, manifest)
        completed.append(value)
    if len(completed) != EXPECTED_COUNT:
        raise EvidenceValidationError("Full Context Judge is incomplete")
    summary = {
        "schema_version": 1,
        "protocol_version": RUN_PROTOCOL_VERSION,
        "row_count": EXPECTED_COUNT,
        "overall": _summarize(completed),
        "by_category": {
            str(category): _summarize([row for row in completed if row["category"] == category])
            for category in (1, 2, 3, 4)
        },
        "score_definitions": {
            "strict_accuracy": "mean(correct=1, partial=0, incorrect=0)",
            "partial_rate": "count(partial)/count(all)",
            "soft_semantic_score": "mean(correct=1, partial=0.5, incorrect=0)",
        },
    }
    report = {"summary": summary, "results": completed}
    _publish(run_root / "results.json", report)
    checks = {
        "judgments_60": len(completed) == EXPECTED_COUNT,
        "prompt_hash_exact": all(row["prompt_sha256"] == JUDGE_PROMPT_SHA256 for row in completed),
        "served_model_exact": all(row["served_models"] == [REQUIRED_SERVED_MODEL] for row in completed),
        "score_mapping_exact": True,
        "all_batches_passed": all(
            (run_root / "control" / f"batch-{batch:02d}.PASSED").is_file()
            for batch in range(1, EXPECTED_BATCHES + 1)
        ),
        "source_records_unchanged": _manifest(repo_root, source_root, judge_run_id) == manifest,
    }
    audit_body = {
        "schema_version": 1,
        "protocol_version": RUN_PROTOCOL_VERSION,
        "status": "passed" if all(checks.values()) else "failed",
        "judge_run_id": judge_run_id,
        "judge_manifest_id": manifest["judge_manifest_id"],
        "judged_records": len(completed),
        "checks": checks,
        "results_sha256": _sha(run_root / "results.json"),
    }
    audit = {
        "final_audit_id": "judge-final-" + sha256_bytes(canonical_json_bytes(audit_body)),
        **audit_body,
    }
    _publish(run_root / "final-audit.json", audit)
    if audit["status"] != "passed":
        raise EvidenceValidationError("Full Context Judge final audit failed")
    return {"status": "passed", "audit": audit, "summary": summary["overall"]}


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Anonymous x-test-1 Judge for B3 Full Context main-60")
    parser.add_argument("--repo-root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--judge-run-id", required=True)
    parser.add_argument("command", choices=("prepare", "run-all"))
    args = parser.parse_args(argv)
    repo_root = args.repo_root.resolve()
    source_root = args.source_root.resolve()
    output_root = args.output_root.resolve()
    if args.command == "prepare":
        path = prepare(repo_root, source_root, output_root, args.judge_run_id)
        result: Mapping[str, Any] = {"status": "prepared", "manifest": str(path)}
    else:
        result = run(
            repo_root,
            source_root,
            output_root,
            args.judge_run_id,
            CompatibleChatProvider.from_environment(),
        )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if result.get("status") == "failed":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
