"""Unified E1--E7 run records with atomic publication and safe resume.

The store is append-only at the logical record level.  A completed key is skipped on
resume only after its content hash, plan identity, evidence identity, answer identity,
and question/condition mapping have all been revalidated.  Failures are retained as
numbered attempts and remain pending; completed records are never overwritten.
"""

from __future__ import annotations

import json
import os
import re
import secrets
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any, Iterable, Mapping, Sequence

from .answerer import (
    AnswerResult,
    AnswerableEvidence,
    answer_result_from_mapping,
    validate_answer_result,
)
from .evidence import (
    EvidenceBundle,
    EvidenceValidationError,
    QuestionInput,
    canonical_json_bytes,
    evidence_bundle_from_mapping,
    sha256_bytes,
)
from .fusion import (
    FUSION_PROTOCOL_VERSION,
    FusionEvidenceBundle,
    fusion_bundle_from_mapping,
)


RUN_PLAN_PROTOCOL_VERSION = "e1-e7-run-plan-v1"
RUN_RECORD_PROTOCOL_VERSION = "e1-e7-run-record-v1"
RUN_FAILURE_PROTOCOL_VERSION = "e1-e7-run-failure-v1"
RUN_CHECKPOINT_PROTOCOL_VERSION = "e1-e7-run-checkpoint-v1"
CONDITION_IDS = ("E1", "E2", "E3", "E4", "E5", "E6", "E7")
_SAFE_SEGMENT = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}\Z")
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")


def _require_safe(value: Any, label: str) -> str:
    if not isinstance(value, str) or _SAFE_SEGMENT.fullmatch(value) is None:
        raise EvidenceValidationError(f"{label} is not a safe identifier")
    return value


def _require_sha(value: Any, label: str) -> str:
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        raise EvidenceValidationError(f"{label} must be a SHA-256 digest")
    return value


@dataclass(frozen=True, order=True)
class RunKey:
    condition_id: str
    question_id: str

    def __post_init__(self) -> None:
        if self.condition_id not in CONDITION_IDS:
            raise EvidenceValidationError("RunKey condition is invalid")
        _require_safe(self.question_id, "RunKey question_id")

    def to_dict(self) -> dict[str, str]:
        return {"condition_id": self.condition_id, "question_id": self.question_id}


@dataclass(frozen=True)
class ExperimentRunPlan:
    schema_version: int
    protocol_version: str
    plan_id: str
    run_id: str
    question_set_id: str
    question_ids: tuple[str, ...]
    condition_ids: tuple[str, ...]
    execution_order: tuple[RunKey, ...]
    config_hashes: Mapping[str, str]

    def __post_init__(self) -> None:
        if self.schema_version != 1 or self.protocol_version != RUN_PLAN_PROTOCOL_VERSION:
            raise EvidenceValidationError("Run plan protocol differs")
        if not self.plan_id.startswith("plan-") or len(self.plan_id) != 69:
            raise EvidenceValidationError("Run plan ID is invalid")
        _require_safe(self.run_id, "run_id")
        _require_safe(self.question_set_id, "question_set_id")
        questions = tuple(self.question_ids)
        conditions = tuple(self.condition_ids)
        order = tuple(self.execution_order)
        if not questions or len(questions) != len(set(questions)):
            raise EvidenceValidationError("Run plan questions must be nonempty and unique")
        if any(_SAFE_SEGMENT.fullmatch(value) is None for value in questions):
            raise EvidenceValidationError("Run plan question ID is unsafe")
        if (
            not conditions
            or len(conditions) != len(set(conditions))
            or any(value not in CONDITION_IDS for value in conditions)
        ):
            raise EvidenceValidationError("Run plan conditions are invalid")
        expected = {RunKey(condition, question) for question in questions for condition in conditions}
        if len(order) != len(expected) or set(order) != expected:
            raise EvidenceValidationError("Run plan execution order is incomplete")
        if not isinstance(self.config_hashes, Mapping) or not self.config_hashes:
            raise EvidenceValidationError("Run plan requires config hashes")
        config = dict(self.config_hashes)
        if any(
            not isinstance(key, str) or not key.strip() or _SHA256.fullmatch(value) is None
            for key, value in config.items()
        ):
            raise EvidenceValidationError("Run plan config hashes are invalid")
        object.__setattr__(self, "question_ids", questions)
        object.__setattr__(self, "condition_ids", conditions)
        object.__setattr__(self, "execution_order", order)
        object.__setattr__(self, "config_hashes", MappingProxyType(dict(sorted(config.items()))))

    def _body(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "protocol_version": self.protocol_version,
            "run_id": self.run_id,
            "question_set_id": self.question_set_id,
            "question_ids": list(self.question_ids),
            "condition_ids": list(self.condition_ids),
            "execution_order": [key.to_dict() for key in self.execution_order],
            "config_hashes": dict(self.config_hashes),
        }

    def to_dict(self) -> dict[str, Any]:
        return {"plan_id": self.plan_id, **self._body()}

    @classmethod
    def create(cls, **values: Any) -> "ExperimentRunPlan":
        placeholder = cls(plan_id="plan-" + "0" * 64, **values)
        plan_id = "plan-" + sha256_bytes(canonical_json_bytes(placeholder._body()))
        return cls(**{**placeholder.__dict__, "plan_id": plan_id})


def build_execution_order(
    question_ids: Sequence[str], condition_ids: Sequence[str]
) -> tuple[RunKey, ...]:
    """Rotate E1--E6 per question, then schedule E7 after its sources."""
    questions = tuple(question_ids)
    conditions = tuple(condition_ids)
    primary = tuple(value for value in conditions if value != "E7")
    output: list[RunKey] = []
    for index, question_id in enumerate(questions):
        if primary:
            offset = index % len(primary)
            rotated = primary[offset:] + primary[:offset]
            output.extend(RunKey(condition, question_id) for condition in rotated)
        if "E7" in conditions:
            output.append(RunKey("E7", question_id))
    return tuple(output)


def build_run_plan(
    *,
    run_id: str,
    question_set_id: str,
    question_ids: Sequence[str],
    condition_ids: Sequence[str],
    config_hashes: Mapping[str, str],
) -> ExperimentRunPlan:
    return ExperimentRunPlan.create(
        schema_version=1,
        protocol_version=RUN_PLAN_PROTOCOL_VERSION,
        run_id=run_id,
        question_set_id=question_set_id,
        question_ids=tuple(question_ids),
        condition_ids=tuple(condition_ids),
        execution_order=build_execution_order(question_ids, condition_ids),
        config_hashes=config_hashes,
    )


def run_plan_from_mapping(value: Mapping[str, Any]) -> ExperimentRunPlan:
    required = {
        "plan_id", "schema_version", "protocol_version", "run_id",
        "question_set_id", "question_ids", "condition_ids", "execution_order",
        "config_hashes",
    }
    if not isinstance(value, Mapping) or set(value) != required:
        raise EvidenceValidationError("Serialized run plan fields are invalid")
    recreated = ExperimentRunPlan.create(
        schema_version=value["schema_version"],
        protocol_version=value["protocol_version"],
        run_id=value["run_id"],
        question_set_id=value["question_set_id"],
        question_ids=tuple(value["question_ids"]),
        condition_ids=tuple(value["condition_ids"]),
        execution_order=tuple(RunKey(**item) for item in value["execution_order"]),
        config_hashes=value["config_hashes"],
    )
    if recreated.plan_id != value["plan_id"]:
        raise EvidenceValidationError("Serialized run plan ID is invalid")
    return recreated


def _bundle_condition(bundle: AnswerableEvidence) -> str:
    if isinstance(bundle, EvidenceBundle):
        value = bundle.condition.get("condition_id")
    elif isinstance(bundle, FusionEvidenceBundle):
        value = bundle.condition_id
    else:
        raise EvidenceValidationError("Unsupported run-record evidence bundle")
    if value not in CONDITION_IDS:
        raise EvidenceValidationError("Evidence bundle condition is invalid")
    return str(value)


def _bundle_from_mapping(value: Mapping[str, Any]) -> AnswerableEvidence:
    protocol = value.get("protocol_version") if isinstance(value, Mapping) else None
    if protocol == FUSION_PROTOCOL_VERSION:
        return fusion_bundle_from_mapping(value)
    return evidence_bundle_from_mapping(value)


def _retrieval_metrics(bundle: AnswerableEvidence) -> dict[str, Any]:
    if isinstance(bundle, EvidenceBundle):
        return dict(bundle.metrics)
    if isinstance(bundle, FusionEvidenceBundle):
        return dict(bundle.retrieval_metrics)
    raise EvidenceValidationError("Unsupported evidence bundle metrics")


def _answer_metrics(answer: AnswerResult) -> dict[str, Any]:
    return {
        "provider_request_attempts": answer.provider_request_attempts,
        "model_calls": answer.model_calls,
        "prompt_tokens": sum(row["prompt_tokens"] for row in answer.usage),
        "completion_tokens": sum(row["completion_tokens"] for row in answer.usage),
        "total_tokens": sum(row["total_tokens"] for row in answer.usage),
        "format_repairs": answer.format_repairs,
    }


@dataclass(frozen=True)
class RunRecord:
    schema_version: int
    protocol_version: str
    record_id: str
    status: str
    plan_id: str
    run_id: str
    key: RunKey
    question: QuestionInput
    question_sha256: str
    evidence_bundle: AnswerableEvidence
    evidence_payload_sha256: str
    answer_result: AnswerResult
    retrieval_metrics: Mapping[str, Any]
    answer_metrics: Mapping[str, Any]
    deployment_metrics: Mapping[str, Any]

    def __post_init__(self) -> None:
        if self.schema_version != 1 or self.protocol_version != RUN_RECORD_PROTOCOL_VERSION:
            raise EvidenceValidationError("RunRecord protocol differs")
        if not self.record_id.startswith("record-") or len(self.record_id) != 71:
            raise EvidenceValidationError("RunRecord ID is invalid")
        if self.status != "completed":
            raise EvidenceValidationError("RunRecord status must be completed")
        if not self.plan_id.startswith("plan-") or len(self.plan_id) != 69:
            raise EvidenceValidationError("RunRecord plan ID is invalid")
        _require_safe(self.run_id, "RunRecord run_id")
        if not isinstance(self.key, RunKey) or not isinstance(self.question, QuestionInput):
            raise EvidenceValidationError("RunRecord key or question is invalid")
        if self.key.question_id != self.question.question_id:
            raise EvidenceValidationError("RunRecord question ID differs")
        if self.question_sha256 != self.question.sha256:
            raise EvidenceValidationError("RunRecord question hash differs")
        if _bundle_condition(self.evidence_bundle) != self.key.condition_id:
            raise EvidenceValidationError("RunRecord condition differs from evidence")
        if self.evidence_bundle.question != self.question:
            raise EvidenceValidationError("RunRecord evidence question differs")
        payload_sha = sha256_bytes(canonical_json_bytes(self.evidence_bundle.to_dict()))
        if self.evidence_payload_sha256 != payload_sha:
            raise EvidenceValidationError("RunRecord evidence payload hash differs")
        validate_answer_result(self.answer_result, bundle=self.evidence_bundle)
        for name in ("retrieval_metrics", "answer_metrics", "deployment_metrics"):
            value = dict(getattr(self, name))
            object.__setattr__(self, name, MappingProxyType(value))

    def _body(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "protocol_version": self.protocol_version,
            "status": self.status,
            "plan_id": self.plan_id,
            "run_id": self.run_id,
            "key": self.key.to_dict(),
            "question": self.question.to_dict(),
            "question_sha256": self.question_sha256,
            "evidence_bundle": self.evidence_bundle.to_dict(),
            "evidence_payload_sha256": self.evidence_payload_sha256,
            "answer_result": self.answer_result.to_dict(),
            "retrieval_metrics": dict(self.retrieval_metrics),
            "answer_metrics": dict(self.answer_metrics),
            "deployment_metrics": dict(self.deployment_metrics),
        }

    def to_dict(self) -> dict[str, Any]:
        return {"record_id": self.record_id, **self._body()}

    @classmethod
    def create(
        cls,
        *,
        plan_id: str,
        run_id: str,
        condition_id: str,
        evidence_bundle: AnswerableEvidence,
        answer_result: AnswerResult,
    ) -> "RunRecord":
        question = evidence_bundle.question
        retrieval = _retrieval_metrics(evidence_bundle)
        answer = _answer_metrics(answer_result)
        retrieval_tokens = retrieval.get("total_tokens")
        answer_tokens = answer["total_tokens"]
        deployment = {
            "retrieval_model_calls": int(retrieval.get("model_calls", 0)),
            "answer_model_calls": answer["model_calls"],
            "total_model_calls": int(retrieval.get("model_calls", 0)) + answer["model_calls"],
            "retrieval_tokens": retrieval_tokens,
            "answer_tokens": answer_tokens,
            "total_tokens": (
                int(retrieval_tokens) + answer_tokens
                if isinstance(retrieval_tokens, int)
                else None
            ),
        }
        placeholder = cls(
            schema_version=1,
            protocol_version=RUN_RECORD_PROTOCOL_VERSION,
            record_id="record-" + "0" * 64,
            status="completed",
            plan_id=plan_id,
            run_id=run_id,
            key=RunKey(condition_id, question.question_id),
            question=question,
            question_sha256=question.sha256,
            evidence_bundle=evidence_bundle,
            evidence_payload_sha256=sha256_bytes(
                canonical_json_bytes(evidence_bundle.to_dict())
            ),
            answer_result=answer_result,
            retrieval_metrics=retrieval,
            answer_metrics=answer,
            deployment_metrics=deployment,
        )
        record_id = "record-" + sha256_bytes(canonical_json_bytes(placeholder._body()))
        return cls(**{**placeholder.__dict__, "record_id": record_id})


def run_record_from_mapping(value: Mapping[str, Any]) -> RunRecord:
    required = {
        "record_id", "schema_version", "protocol_version", "status", "plan_id",
        "run_id", "key", "question", "question_sha256", "evidence_bundle",
        "evidence_payload_sha256", "answer_result", "retrieval_metrics",
        "answer_metrics", "deployment_metrics",
    }
    if not isinstance(value, Mapping) or set(value) != required:
        raise EvidenceValidationError("Serialized RunRecord fields are invalid")
    bundle = _bundle_from_mapping(value["evidence_bundle"])
    answer = answer_result_from_mapping(value["answer_result"])
    recreated = RunRecord.create(
        plan_id=value["plan_id"],
        run_id=value["run_id"],
        condition_id=value["key"]["condition_id"],
        evidence_bundle=bundle,
        answer_result=answer,
    )
    if (
        recreated.record_id != value["record_id"]
        or recreated.to_dict() != dict(value)
    ):
        raise EvidenceValidationError("Serialized RunRecord identity is invalid")
    return recreated


@dataclass(frozen=True)
class RunFailureRecord:
    schema_version: int
    protocol_version: str
    failure_id: str
    status: str
    plan_id: str
    run_id: str
    key: RunKey
    attempt: int
    stage: str
    error_type: str
    message: str
    retryable: bool

    def __post_init__(self) -> None:
        if self.schema_version != 1 or self.protocol_version != RUN_FAILURE_PROTOCOL_VERSION:
            raise EvidenceValidationError("Run failure protocol differs")
        if not self.failure_id.startswith("run-failure-") or len(self.failure_id) != 76:
            raise EvidenceValidationError("Run failure ID is invalid")
        if self.status != "failed" or not isinstance(self.key, RunKey):
            raise EvidenceValidationError("Run failure status or key is invalid")
        if isinstance(self.attempt, bool) or not isinstance(self.attempt, int) or self.attempt < 1:
            raise EvidenceValidationError("Run failure attempt is invalid")
        for value, label in (
            (self.stage, "stage"),
            (self.error_type, "error_type"),
            (self.message, "message"),
        ):
            if not isinstance(value, str) or not value.strip():
                raise EvidenceValidationError(f"Run failure {label} is invalid")
        if not isinstance(self.retryable, bool):
            raise EvidenceValidationError("Run failure retryable must be boolean")

    def _body(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "protocol_version": self.protocol_version,
            "status": self.status,
            "plan_id": self.plan_id,
            "run_id": self.run_id,
            "key": self.key.to_dict(),
            "attempt": self.attempt,
            "stage": self.stage,
            "error_type": self.error_type,
            "message": self.message,
            "retryable": self.retryable,
        }

    def to_dict(self) -> dict[str, Any]:
        return {"failure_id": self.failure_id, **self._body()}

    @classmethod
    def create(cls, **values: Any) -> "RunFailureRecord":
        placeholder = cls(failure_id="run-failure-" + "0" * 64, **values)
        failure_id = "run-failure-" + sha256_bytes(canonical_json_bytes(placeholder._body()))
        return cls(**{**placeholder.__dict__, "failure_id": failure_id})


def run_failure_from_mapping(value: Mapping[str, Any]) -> RunFailureRecord:
    required = {
        "failure_id", "schema_version", "protocol_version", "status", "plan_id",
        "run_id", "key", "attempt", "stage", "error_type", "message", "retryable",
    }
    if not isinstance(value, Mapping) or set(value) != required:
        raise EvidenceValidationError("Serialized run failure fields are invalid")
    recreated = RunFailureRecord.create(
        schema_version=value["schema_version"],
        protocol_version=value["protocol_version"],
        status=value["status"],
        plan_id=value["plan_id"],
        run_id=value["run_id"],
        key=RunKey(**value["key"]),
        attempt=value["attempt"],
        stage=value["stage"],
        error_type=value["error_type"],
        message=value["message"],
        retryable=value["retryable"],
    )
    if recreated.failure_id != value["failure_id"]:
        raise EvidenceValidationError("Serialized run failure ID is invalid")
    return recreated


def _write_new(path: Path, payload: bytes, mode: int = 0o644) -> None:
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(path, flags, mode)
    try:
        offset = 0
        while offset < len(payload):
            count = os.write(descriptor, payload[offset:])
            if count <= 0:
                raise OSError("short run artifact write")
            offset += count
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _read_json(path: Path) -> Mapping[str, Any]:
    if path.is_symlink() or not path.is_file():
        raise EvidenceValidationError("Run artifact is not a regular file")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise EvidenceValidationError("Run artifact is unreadable") from exc
    if not isinstance(value, Mapping):
        raise EvidenceValidationError("Run artifact must contain an object")
    return value


class ExperimentRunStore:
    def __init__(self, root: Path, plan: ExperimentRunPlan) -> None:
        self.root = Path(root).resolve()
        self.plan = plan
        self.run_root = self.root / plan.run_id
        self.records_root = self.run_root / "records"
        self.failures_root = self.run_root / "failures"

    @classmethod
    def create_or_open(
        cls, root: Path, plan: ExperimentRunPlan
    ) -> "ExperimentRunStore":
        base = Path(root).resolve()
        base.mkdir(parents=True, exist_ok=True)
        if base.is_symlink() or not base.is_dir():
            raise EvidenceValidationError("Run output root is unsafe")
        store = cls(base, plan)
        store.run_root.mkdir(mode=0o700, exist_ok=True)
        store.records_root.mkdir(exist_ok=True)
        store.failures_root.mkdir(exist_ok=True)
        for condition in plan.condition_ids:
            (store.records_root / condition).mkdir(exist_ok=True)
            (store.failures_root / condition).mkdir(exist_ok=True)
        plan_path = store.run_root / "plan.json"
        payload = canonical_json_bytes(plan.to_dict()) + b"\n"
        if plan_path.exists() or plan_path.is_symlink():
            existing = run_plan_from_mapping(_read_json(plan_path))
            if existing != plan:
                raise EvidenceValidationError("Existing run plan differs")
        else:
            _write_new(plan_path, payload)
        return store

    def _assert_key(self, key: RunKey) -> None:
        if key not in set(self.plan.execution_order):
            raise EvidenceValidationError("Run key is outside the frozen plan")

    def record_path(self, key: RunKey) -> Path:
        self._assert_key(key)
        return self.records_root / key.condition_id / f"{key.question_id}.json"

    def load_completed(self, key: RunKey) -> RunRecord | None:
        path = self.record_path(key)
        if not path.exists() and not path.is_symlink():
            return None
        record = run_record_from_mapping(_read_json(path))
        if record.plan_id != self.plan.plan_id or record.run_id != self.plan.run_id or record.key != key:
            raise EvidenceValidationError("Completed record does not match the run plan")
        return record

    def publish_success(self, record: RunRecord) -> Path:
        key = record.key
        self._assert_key(key)
        if record.plan_id != self.plan.plan_id or record.run_id != self.plan.run_id:
            raise EvidenceValidationError("RunRecord plan identity differs")
        if key.condition_id == "E7":
            raw = self.load_completed(RunKey("E2", key.question_id))
            curated = self.load_completed(RunKey("E6", key.question_id))
            if raw is None or curated is None:
                raise EvidenceValidationError("E7 requires completed E2 and E6 records")
            if not isinstance(record.evidence_bundle, FusionEvidenceBundle):
                raise EvidenceValidationError("E7 requires a fusion evidence bundle")
            expected_sources = (
                raw.evidence_bundle.bundle_id,
                curated.evidence_bundle.bundle_id,
            )
            if record.evidence_bundle.source_bundle_ids != expected_sources:
                raise EvidenceValidationError("E7 source bundles differ from this run")
        final = self.record_path(key)
        if final.exists() or final.is_symlink():
            raise EvidenceValidationError("Completed RunRecord already exists")
        staging = final.parent / f".{final.name}.in-progress-{secrets.token_hex(8)}"
        _write_new(staging, canonical_json_bytes(record.to_dict()) + b"\n", 0o600)
        os.replace(staging, final)
        descriptor = os.open(final.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        verified = self.load_completed(key)
        if verified != record:
            raise EvidenceValidationError("Published RunRecord failed verification")
        return final

    def failure_attempts(self, key: RunKey) -> tuple[RunFailureRecord, ...]:
        self._assert_key(key)
        directory = self.failures_root / key.condition_id / key.question_id
        if not directory.exists():
            return ()
        if directory.is_symlink() or not directory.is_dir():
            raise EvidenceValidationError("Failure history directory is unsafe")
        output: list[RunFailureRecord] = []
        for path in sorted(directory.glob("attempt-*.json")):
            failure = run_failure_from_mapping(_read_json(path))
            if failure.plan_id != self.plan.plan_id or failure.run_id != self.plan.run_id or failure.key != key:
                raise EvidenceValidationError("Failure history differs from the run plan")
            output.append(failure)
        if [item.attempt for item in output] != list(range(1, len(output) + 1)):
            raise EvidenceValidationError("Failure attempts are not contiguous")
        return tuple(output)

    def publish_failure(
        self,
        *,
        key: RunKey,
        stage: str,
        error_type: str,
        message: str,
        retryable: bool,
    ) -> Path:
        self._assert_key(key)
        if self.load_completed(key) is not None:
            raise EvidenceValidationError("Cannot fail an already completed key")
        attempts = self.failure_attempts(key)
        failure = RunFailureRecord.create(
            schema_version=1,
            protocol_version=RUN_FAILURE_PROTOCOL_VERSION,
            status="failed",
            plan_id=self.plan.plan_id,
            run_id=self.plan.run_id,
            key=key,
            attempt=len(attempts) + 1,
            stage=stage,
            error_type=error_type,
            message=message,
            retryable=retryable,
        )
        directory = self.failures_root / key.condition_id / key.question_id
        directory.mkdir(exist_ok=True)
        path = directory / f"attempt-{failure.attempt:04d}.json"
        _write_new(path, canonical_json_bytes(failure.to_dict()) + b"\n")
        return path

    def pending_keys(self) -> tuple[RunKey, ...]:
        return tuple(
            key for key in self.plan.execution_order if self.load_completed(key) is None
        )

    def checkpoint(self) -> dict[str, Any]:
        completed: list[dict[str, Any]] = []
        failed_attempts = 0
        for key in self.plan.execution_order:
            record = self.load_completed(key)
            if record is not None:
                completed.append({**key.to_dict(), "record_id": record.record_id})
            failed_attempts += len(self.failure_attempts(key))
        pending = [key.to_dict() for key in self.pending_keys()]
        body = {
            "schema_version": 1,
            "protocol_version": RUN_CHECKPOINT_PROTOCOL_VERSION,
            "plan_id": self.plan.plan_id,
            "run_id": self.plan.run_id,
            "planned": len(self.plan.execution_order),
            "completed": len(completed),
            "pending": len(pending),
            "failed_attempts": failed_attempts,
            "completed_records": completed,
            "pending_keys": pending,
        }
        return {**body, "checkpoint_sha256": sha256_bytes(canonical_json_bytes(body))}


def verify_run_store(root: Path, run_id: str) -> tuple[ExperimentRunStore, dict[str, Any]]:
    _require_safe(run_id, "run_id")
    run_root = Path(root).resolve() / run_id
    plan = run_plan_from_mapping(_read_json(run_root / "plan.json"))
    if plan.run_id != run_id:
        raise EvidenceValidationError("Run directory and plan identity differ")
    store = ExperimentRunStore.create_or_open(Path(root), plan)
    checkpoint = store.checkpoint()
    return store, checkpoint
