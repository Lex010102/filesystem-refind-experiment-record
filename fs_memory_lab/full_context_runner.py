"""DeepSeek-only main-60 Full Context runner, checkpoints, audit, and evaluation.

This extension intentionally does not modify the frozen E1--E7 plan or its
``run_records`` implementation.  It reuses only frozen inputs, the unchanged
shared Answerer, and the pinned LoCoMo scoring primitives while fail-closing
every response to the frozen Model 2 identity.
"""

from __future__ import annotations

import fcntl
import hashlib
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
from typing import Any, Mapping, Sequence

from .agent import (
    RETRYABLE_HTTP_STATUS_CODES,
    ChatProvider,
    TransientProviderError,
)
from .answerer import (
    ANSWERER_FORMAT_REPAIR_LIMIT,
    ANSWERER_HTTP_BACKOFF_SECONDS,
    ANSWERER_HTTP_MAX_ATTEMPTS,
    ANSWERER_MAX_COMPLETION_TOKENS,
    ANSWERER_PROTOCOL_VERSION,
    ANSWERER_SYSTEM_PROMPT,
    ANSWERER_SYSTEM_PROMPT_SHA256,
    ANSWERER_TEMPERATURE,
    ANSWERER_TIMEOUT_BACKOFF_SECONDS,
    ANSWERER_TIMEOUT_MAX_ATTEMPTS,
    AnswererError,
    AnswerResult,
    SharedAnswerer,
    answer_result_from_mapping,
    render_answerer_user_prompt,
    validate_answer_result,
)
from .evaluation import (
    LOCOMO_EVALUATOR_COMMIT,
    LOCOMO_EVALUATOR_PATH,
    LOCOMO_EVALUATOR_REPOSITORY,
    LOCOMO_EVALUATOR_SHA256,
    LOCOMO_NLTK_VERSION,
    RELIABLE_POOL_CATEGORY_COUNTS,
    GoldRecord,
    load_gold_records,
    locomo_category_f1,
    normalize_answer,
)
from .evidence import EvidenceValidationError, QuestionInput, canonical_json_bytes, sha256_bytes
from .formal_v1 import verify_formal_manifest
from .formal_v2_extension import (
    COMPOSITION_RELATIVE_PATH,
    COMPOSITION_SHA256,
    QUESTION_GOLD_RELATIVE_PATH as EXTENSION_GOLD_RELATIVE_PATH,
    QUESTION_GOLD_SHA256 as EXTENSION_GOLD_SHA256,
    QUESTION_INPUT_RELATIVE_PATH as EXTENSION_INPUT_RELATIVE_PATH,
    QUESTION_INPUT_SHA256 as EXTENSION_INPUT_SHA256,
    QUESTION_MANIFEST_RELATIVE_PATH as MAIN60_MANIFEST_RELATIVE_PATH,
    QUESTION_MANIFEST_SHA256 as MAIN60_MANIFEST_SHA256,
    QUESTION_SET_ID as EXTENSION_QUESTION_SET_ID,
    QUESTION_VERIFICATION_RELATIVE_PATH as MAIN60_VERIFICATION_RELATIVE_PATH,
    QUESTION_VERIFICATION_SHA256 as MAIN60_VERIFICATION_SHA256,
    _load_extension_questions,
)
from .formal_v2_model2 import (
    MODEL2_API_STYLE,
    MODEL2_API_BASE_URL,
    MODEL2_CHAT_ENDPOINT,
    MODEL2_CONCURRENCY,
    MODEL2_CONTEXT_LIMIT,
    MODEL2_MAX_RESPONSE_BYTES,
    MODEL2_REQUESTED_MODEL_ALIAS,
    MODEL2_REQUEST_TIMEOUT_SECONDS,
    MODEL2_REQUIRED_SERVED_MODEL,
    ModelIdentityProvider,
)
from .full_context import (
    FULL_CONTEXT_CONDITION_ID,
    FULL_CONTEXT_CONTEXT_POLICY,
    FULL_CONTEXT_CONTRACT_SHA256,
    FULL_CONTEXT_PROTOCOL_VERSION,
    FullContextEvidenceBundle,
    build_full_context_items,
    build_full_context_bundle,
    full_context_stats,
    full_context_bundle_from_mapping,
    publish_source_package,
    source_package,
    verify_full_context_bundle,
)
from .r1_inputs import QUESTION_INPUTS, load_question_inputs, load_r1_store
from .model2_preflight import verify_sanitized_preflight_artifact
from .vendor.locomo_porter import PorterStemmer


FULL_CONTEXT_RUN_PROTOCOL_VERSION = "b3-full-context-model2-main60-run-v2"
FULL_CONTEXT_RECORD_PROTOCOL_VERSION = "b3-full-context-model2-main60-record-v2"
FULL_CONTEXT_FAILURE_PROTOCOL_VERSION = "b3-full-context-model2-main60-failure-v2"
FULL_CONTEXT_EVALUATION_PROTOCOL_VERSION = "b3-full-context-model2-main60-evaluation-v2"
FULL_CONTEXT_BATCH_SIZE = 5
FULL_CONTEXT_PREFLIGHT_QUESTION_ID = "conv-50-q079"
FULL_CONTEXT_DEV_PILOT_RUN_ID = "b3-full-context-v2-model2-dev6-run-01"
FULL_CONTEXT_MAIN_RUN_ID = "b3-full-context-v2-model2-main60-run-01"
FULL_CONTEXT_MAIN_QUESTION_SET = "main-60-v2"
FULL_CONTEXT_MAIN_QUESTION_SET_ID = "locomo-conv50-main60-v2"
FULL_CONTEXT_DEV_PASSED_MARKER = "FULL-CONTEXT-MODEL2-DEV6-6.PASSED"
FULL_CONTEXT_MAIN_PASSED_MARKER = "FULL-CONTEXT-MODEL2-MAIN60-60.PASSED"
FULL_CONTEXT_PREFLIGHT_PASSED_MARKER = (
    "FULL-CONTEXT-MODEL2-LONG-CONTEXT-PREFLIGHT.PASSED"
)
FULL_CONTEXT_IDENTITY_DRIFT_MARKER = "MODEL-IDENTITY-DRIFT.json"
FULL_CONTEXT_PARENT_FORMAL_MANIFEST_ID = (
    "formal-337ebb2061b34493a2e81cad19453eb85481d82a646ce4c40a750e2222d08925"
)
FULL_CONTEXT_MODEL2_FREEZE_MANIFEST_ID = (
    "formal-v2-model2-freeze-05bd1fbe832c471f20c5c855823d46c88e66601788391730f52ac04697fd79e8"
)
FULL_CONTEXT_MODEL2_FREEZE_MANIFEST_RELATIVE_PATH = (
    "experiments/locomo-conv50-v1/formal-v2-model2/manifest.json"
)
FULL_CONTEXT_MODEL2_FREEZE_MANIFEST_SHA256 = (
    "20d6a834e0beffafc7f1791f79eaaabfed0231800984e1267b423ce039d8dd4f"
)
FULL_CONTEXT_MODEL2_PREFLIGHT_RELATIVE_DIR = (
    "experiments/locomo-conv50-v1/results/"
    "formal-v2-model2-main60-candidate-02/run/preflight"
)
FULL_CONTEXT_MODEL2_PREFLIGHT_FILES = {
    "models_check": f"{FULL_CONTEXT_MODEL2_PREFLIGHT_RELATIVE_DIR}/models-check.json",
    "role_smoke": f"{FULL_CONTEXT_MODEL2_PREFLIGHT_RELATIVE_DIR}/role-smoke.json",
}
FULL_CONTEXT_SOURCE_RELATIVE_DIR = (
    "experiments/locomo-conv50-v1/baselines/b3-full-context-v1"
)
FULL_CONTEXT_PUBLISHED_SOURCE_FILES = tuple(
    f"{FULL_CONTEXT_SOURCE_RELATIVE_DIR}/{name}"
    for name in (
        "context-package.json",
        "manifest.json",
        "transcript.txt",
        "verification.json",
    )
)
FULL_CONTEXT_GOLD = {
    "dev-6": {
        "relative_path": "experiments/locomo-conv50-v1/question-sets/dev-6-gold.jsonl",
        "sha256": "7df334500d8ae394a121674e38b0553bc3136f850df896a5e936e0dd952009f0",
    },
    "main-40": {
        "relative_path": "experiments/locomo-conv50-v1/question-sets/main-40-gold.jsonl",
        "sha256": "a6833ca585ca26efcdd038a5cf202fd46657999053ebd7b8cc73793f7544718b",
    },
    "extension-20": {
        "relative_path": EXTENSION_GOLD_RELATIVE_PATH,
        "sha256": EXTENSION_GOLD_SHA256,
    },
}
FULL_CONTEXT_IMPLEMENTATION_FILES = (
    "fs_memory_lab/agent.py",
    "fs_memory_lab/answerer.py",
    "fs_memory_lab/evaluation.py",
    "fs_memory_lab/evidence.py",
    "fs_memory_lab/formal_v1.py",
    "fs_memory_lab/formal_v2_extension.py",
    "fs_memory_lab/formal_v2_model2.py",
    "fs_memory_lab/model2_preflight.py",
    "fs_memory_lab/r1_inputs.py",
    "fs_memory_lab/vendor/locomo_porter.py",
    "fs_memory_lab/full_context.py",
    "fs_memory_lab/full_context_runner.py",
    "fs_memory_lab/full_context_cli.py",
    "tests/test_full_context.py",
)

_SAFE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}\Z")
_COMMIT = re.compile(r"[0-9a-f]{40}\Z")
_KEY = re.compile(r"\b(?:clsk|sk)[_-][A-Za-z0-9_-]{10,}\b")
_STEMMER = PorterStemmer()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _read_json(path: Path) -> dict[str, Any]:
    lexical = Path(path)
    if lexical.is_symlink() or not lexical.is_file():
        raise EvidenceValidationError(f"Unsafe or missing Full Context JSON: {lexical}")
    try:
        value = json.loads(lexical.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise EvidenceValidationError(f"Unreadable Full Context JSON: {lexical}") from exc
    if not isinstance(value, dict):
        raise EvidenceValidationError("Full Context JSON must be an object")
    return value


def _write_exclusive(path: Path, value: Mapping[str, Any], mode: int = 0o644) -> None:
    """Publish one immutable JSON object without exposing a partial final file."""

    path.parent.mkdir(parents=True, exist_ok=True)
    payload = canonical_json_bytes(value) + b"\n"
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        os.fchmod(descriptor, mode)
        try:
            offset = 0
            while offset < len(payload):
                written = os.write(descriptor, payload[offset:])
                if written <= 0:
                    raise OSError("short Full Context artifact write")
                offset += written
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
            descriptor = -1
        try:
            # A same-directory hard link is atomic and, unlike replace(), can
            # never overwrite an existing immutable checkpoint.
            os.link(temporary, path, follow_symlinks=False)
        except FileExistsError as exc:
            raise EvidenceValidationError(
                f"Full Context artifact already exists: {path}"
            ) from exc
        directory_flags = os.O_RDONLY
        if hasattr(os, "O_DIRECTORY"):
            directory_flags |= os.O_DIRECTORY
        directory = os.open(path.parent, directory_flags)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        if os.path.exists(temporary):
            os.unlink(temporary)


def _write_atomic(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = canonical_json_bytes(value) + b"\n"
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def _publish_idempotent(path: Path, value: Mapping[str, Any]) -> None:
    if path.exists() or path.is_symlink():
        if _read_json(path) != dict(value):
            raise EvidenceValidationError(f"Existing Full Context artifact differs: {path}")
        return
    try:
        _write_exclusive(path, value)
    except EvidenceValidationError:
        # Another process may have won the no-clobber publication race.  The
        # result is idempotent only when the complete object is byte-equivalent.
        if (path.exists() or path.is_symlink()) and _read_json(path) == dict(value):
            return
        raise


def _append_event(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = canonical_json_bytes(value) + b"\n"
    flags = os.O_WRONLY | os.O_CREAT | os.O_APPEND
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(path, flags, 0o644)
    locked = False
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX)
        locked = True
        offset = 0
        while offset < len(payload):
            written = os.write(descriptor, payload[offset:])
            if written <= 0:
                raise OSError("short Full Context event write")
            offset += written
        os.fsync(descriptor)
    finally:
        if locked:
            fcntl.flock(descriptor, fcntl.LOCK_UN)
        os.close(descriptor)


def _safe_error(error: Exception, provider: ChatProvider | None = None) -> str:
    text = " ".join(str(error).split())[:600]
    secret = getattr(provider, "api_key", None) if provider is not None else None
    if isinstance(secret, str) and secret:
        text = text.replace(secret, "[REDACTED_KEY]")
    return _KEY.sub("[REDACTED_KEY]", text)


def _provider_preflight(provider: ChatProvider) -> None:
    """Fail closed before an online request can diverge from the frozen run."""

    if getattr(provider, "endpoint", None) != MODEL2_CHAT_ENDPOINT:
        raise EvidenceValidationError("Full Context provider endpoint differs")
    if getattr(provider, "api_style", None) != MODEL2_API_STYLE:
        raise EvidenceValidationError("Full Context provider API style differs")
    if getattr(provider, "model", None) != MODEL2_REQUESTED_MODEL_ALIAS:
        raise EvidenceValidationError("FSMEM_MODEL must equal the frozen alias x-test-2")
    if getattr(provider, "timeout", None) != MODEL2_REQUEST_TIMEOUT_SECONDS:
        raise EvidenceValidationError("Full Context provider timeout differs")
    if getattr(provider, "max_response_bytes", None) != MODEL2_MAX_RESPONSE_BYTES:
        raise EvidenceValidationError("Full Context provider response cap differs")


def _load_full_context_questions(
    repo_root: Path, question_set: str,
) -> tuple[QuestionInput, ...]:
    """Load dev-6 or the exact frozen main-40 + extension-20 composition.

    The composite deliberately preserves each source ``QuestionInput`` identity
    and local ``run_position``.  Global positions live only in the separately
    hash-pinned main-60 composition artifact.
    """

    root = Path(repo_root).resolve()
    if question_set == "dev-6":
        return load_question_inputs(root, "dev-6")
    if question_set != FULL_CONTEXT_MAIN_QUESTION_SET:
        raise EvidenceValidationError(
            "Full Context question_set must be dev-6 or main-60-v2"
        )
    if _file_sha256(root / COMPOSITION_RELATIVE_PATH) != COMPOSITION_SHA256:
        raise EvidenceValidationError("Pinned main-60 composition differs")
    core = load_question_inputs(root, "main-40")
    extension = _load_extension_questions(root)
    questions = core + extension
    composition = _read_json(root / COMPOSITION_RELATIVE_PATH)
    order = composition.get("question_order")
    if (
        composition.get("composite_question_set_id")
        != FULL_CONTEXT_MAIN_QUESTION_SET_ID
        or composition.get("question_count") != 60
        or not isinstance(order, list)
        or len(order) != 60
        or len({question.question_id for question in questions}) != 60
    ):
        raise EvidenceValidationError("Frozen main-60 composition header differs")
    expected = [
        {
            "global_position": index,
            "layer": "core-40-v1" if index <= 40 else "extension-20-v2",
            "question_id": question.question_id,
            "source_question_set_id": question.question_set_id,
            "source_run_position": question.run_position,
        }
        for index, question in enumerate(questions, start=1)
    ]
    observed = [
        {
            "global_position": row.get("global_position"),
            "layer": row.get("layer"),
            "question_id": row.get("question_id"),
            "source_question_set_id": row.get("source_question_set_id"),
            "source_run_position": row.get("source_run_position"),
        }
        for row in order
        if isinstance(row, Mapping)
    ]
    if observed != expected:
        raise EvidenceValidationError("Frozen main-60 question order differs")
    if any(question.question_set_id != EXTENSION_QUESTION_SET_ID for question in extension):
        raise EvidenceValidationError("Extension question identity differs")
    return questions


def _question_set_manifest(
    repo_root: Path, question_set: str, questions: Sequence[QuestionInput],
) -> dict[str, Any]:
    root = Path(repo_root).resolve()
    if question_set == "dev-6":
        spec = QUESTION_INPUTS["dev-6"]
        path = root / str(spec["relative_path"])
        return {
            "name": question_set,
            "question_set_id": spec["question_set_id"],
            "input_artifacts": {
                "dev6": {
                    "relative_path": str(spec["relative_path"]),
                    "sha256": _file_sha256(path),
                }
            },
            "composition": None,
            "question_count": len(questions),
            "question_order": [question.to_dict() for question in questions],
        }
    core_spec = QUESTION_INPUTS["main-40"]
    artifacts = {
        "main40_input": {
            "relative_path": str(core_spec["relative_path"]),
            "sha256": _file_sha256(root / str(core_spec["relative_path"])),
        },
        "extension20_input": {
            "relative_path": EXTENSION_INPUT_RELATIVE_PATH,
            "sha256": _file_sha256(root / EXTENSION_INPUT_RELATIVE_PATH),
        },
        "main60_manifest": {
            "relative_path": MAIN60_MANIFEST_RELATIVE_PATH,
            "sha256": _file_sha256(root / MAIN60_MANIFEST_RELATIVE_PATH),
        },
        "main60_verification": {
            "relative_path": MAIN60_VERIFICATION_RELATIVE_PATH,
            "sha256": _file_sha256(root / MAIN60_VERIFICATION_RELATIVE_PATH),
        },
    }
    expected_hashes = {
        "main40_input": str(core_spec["sha256"]),
        "extension20_input": EXTENSION_INPUT_SHA256,
        "main60_manifest": MAIN60_MANIFEST_SHA256,
        "main60_verification": MAIN60_VERIFICATION_SHA256,
    }
    if any(artifacts[key]["sha256"] != value for key, value in expected_hashes.items()):
        raise EvidenceValidationError("Frozen main-60 input artifact differs")
    return {
        "name": question_set,
        "question_set_id": FULL_CONTEXT_MAIN_QUESTION_SET_ID,
        "source_question_set_ids": [
            QUESTION_INPUTS["main-40"]["question_set_id"],
            EXTENSION_QUESTION_SET_ID,
        ],
        "input_artifacts": artifacts,
        "composition": {
            "relative_path": COMPOSITION_RELATIVE_PATH,
            "sha256": _file_sha256(root / COMPOSITION_RELATIVE_PATH),
        },
        "question_count": len(questions),
        "question_order": [question.to_dict() for question in questions],
    }


def _verify_model2_foundation(repo_root: Path) -> dict[str, Any]:
    """Bind the Full Context run to the already frozen Model 2 deployment."""

    root = Path(repo_root).resolve()
    freeze_path = root / FULL_CONTEXT_MODEL2_FREEZE_MANIFEST_RELATIVE_PATH
    if _file_sha256(freeze_path) != FULL_CONTEXT_MODEL2_FREEZE_MANIFEST_SHA256:
        raise EvidenceValidationError("Frozen Model 2 manifest differs")
    freeze = _read_json(freeze_path)
    deployment = freeze.get("deployment")
    if (
        freeze.get("freeze_manifest_id") != FULL_CONTEXT_MODEL2_FREEZE_MANIFEST_ID
        or freeze.get("status") != "frozen"
        or not isinstance(deployment, Mapping)
        or deployment.get("requested_model_alias") != MODEL2_REQUESTED_MODEL_ALIAS
        or deployment.get("required_served_model") != MODEL2_REQUIRED_SERVED_MODEL
        or deployment.get("api_base_url") != MODEL2_API_BASE_URL
        or deployment.get("chat_endpoint") != MODEL2_CHAT_ENDPOINT
        or deployment.get("api_style") != MODEL2_API_STYLE
        or deployment.get("context_limit_tokens") != MODEL2_CONTEXT_LIMIT
        or deployment.get("request_timeout_seconds")
        != MODEL2_REQUEST_TIMEOUT_SECONDS
        or deployment.get("max_response_bytes") != MODEL2_MAX_RESPONSE_BYTES
        or deployment.get("concurrency") != MODEL2_CONCURRENCY
        or deployment.get("identity_policy")
        != (
            "every response including compaction, correction, and repair must "
            "report the exact required_served_model"
        )
        or deployment.get("runtime_model_override") != "forbidden"
    ):
        raise EvidenceValidationError("Frozen Model 2 deployment contract differs")
    summaries: dict[str, Any] = {}
    files: dict[str, Any] = {}
    for name, relative in FULL_CONTEXT_MODEL2_PREFLIGHT_FILES.items():
        path = root / relative
        summaries[name] = verify_sanitized_preflight_artifact(path)
        files[name] = {"relative_path": relative, "sha256": _file_sha256(path)}
    expected_preflight_hashes = {
        "models_check": deployment.get("models_check_report_sha256"),
        "role_smoke": deployment.get("role_smoke_report_sha256"),
    }
    if (
        any(
            files[name]["sha256"] != expected_preflight_hashes[name]
            for name in files
        )
        or summaries["models_check"].get("requested_alias")
        != MODEL2_REQUESTED_MODEL_ALIAS
        or summaries["models_check"].get("context_limit") != MODEL2_CONTEXT_LIMIT
        or summaries["role_smoke"].get("requested_alias")
        != MODEL2_REQUESTED_MODEL_ALIAS
        or summaries["role_smoke"].get("served_model")
        != MODEL2_REQUIRED_SERVED_MODEL
    ):
        raise EvidenceValidationError("Archived Model 2 preflight differs")
    return {
        "freeze_manifest_id": FULL_CONTEXT_MODEL2_FREEZE_MANIFEST_ID,
        "freeze_manifest_relative_path": FULL_CONTEXT_MODEL2_FREEZE_MANIFEST_RELATIVE_PATH,
        "freeze_manifest_sha256": FULL_CONTEXT_MODEL2_FREEZE_MANIFEST_SHA256,
        "preflight_files": files,
        "preflight_summaries": summaries,
    }


def _implementation_hashes(repo_root: Path) -> dict[str, str]:
    root = Path(repo_root).resolve()
    values: dict[str, str] = {}
    for relative in FULL_CONTEXT_IMPLEMENTATION_FILES:
        path = root / relative
        if path.is_symlink() or not path.is_file():
            raise EvidenceValidationError(f"Full Context implementation file is missing: {relative}")
        values[relative] = _file_sha256(path)
    return values


def _prompt_metrics(bundle: FullContextEvidenceBundle) -> dict[str, Any]:
    user_prompt = render_answerer_user_prompt(bundle)
    system_bytes = ANSWERER_SYSTEM_PROMPT.encode("utf-8")
    user_bytes = user_prompt.encode("utf-8")
    messages = [
        {"role": "system", "content": ANSWERER_SYSTEM_PROMPT},
        {"role": "user", "content": user_prompt},
    ]
    characters = len(ANSWERER_SYSTEM_PROMPT) + len(user_prompt)
    payload_bytes = len(system_bytes) + len(user_bytes)
    # This is an explicitly labelled conservative planning estimate.  Provider
    # usage remains authoritative once an online request is made.
    low = round(characters / 3.5)
    high = round(characters / 2.9)
    return {
        "system_characters": len(ANSWERER_SYSTEM_PROMPT),
        "user_prompt_characters": len(user_prompt),
        "total_message_characters": characters,
        "system_bytes": len(system_bytes),
        "user_prompt_bytes": len(user_bytes),
        "total_message_bytes": payload_bytes,
        "messages_sha256": sha256_bytes(canonical_json_bytes(messages)),
        "estimated_input_tokens_low": low,
        "estimated_input_tokens_high": high,
        "estimated_total_context_with_2048_output_low": low + ANSWERER_MAX_COMPLETION_TOKENS,
        "estimated_total_context_with_2048_output_high": high + ANSWERER_MAX_COMPLETION_TOKENS,
        "planning_output_reservation_tokens": ANSWERER_MAX_COMPLETION_TOKENS,
        "portable_api_enforces_output_reservation": False,
        "estimate_method": "conservative chars-per-prompt-token planning range 2.9-3.5",
        "provider_prompt_tokens_authoritative": True,
    }


@dataclass(frozen=True)
class FullContextRunRecord:
    schema_version: int
    protocol_version: str
    record_id: str
    status: str
    plan_id: str
    run_id: str
    question: QuestionInput
    question_sha256: str
    evidence_bundle: FullContextEvidenceBundle
    evidence_payload_sha256: str
    answer_result: AnswerResult
    request_metrics: Mapping[str, Any]
    deployment_metrics: Mapping[str, Any]

    def __post_init__(self) -> None:
        if self.schema_version != 1 or self.protocol_version != FULL_CONTEXT_RECORD_PROTOCOL_VERSION:
            raise EvidenceValidationError("Full Context record protocol differs")
        if not self.record_id.startswith("full-context-record-") or len(self.record_id) != 84:
            raise EvidenceValidationError("Full Context record ID is invalid")
        if self.status != "completed" or not _SAFE.fullmatch(self.run_id):
            raise EvidenceValidationError("Full Context record status or run ID differs")
        if not self.plan_id.startswith("full-context-plan-") or len(self.plan_id) != 82:
            raise EvidenceValidationError("Full Context plan ID is invalid")
        if not isinstance(self.question, QuestionInput) or self.question_sha256 != self.question.sha256:
            raise EvidenceValidationError("Full Context record question differs")
        if self.evidence_bundle.question != self.question:
            raise EvidenceValidationError("Full Context bundle question differs")
        self.evidence_bundle.validate_identity()
        expected_payload = sha256_bytes(canonical_json_bytes(self.evidence_bundle.to_dict()))
        if self.evidence_payload_sha256 != expected_payload:
            raise EvidenceValidationError("Full Context evidence payload hash differs")
        validate_answer_result(self.answer_result, bundle=self.evidence_bundle)
        if self.answer_result.requested_model != MODEL2_REQUESTED_MODEL_ALIAS:
            raise EvidenceValidationError("Full Context requested model differs")
        if set(self.answer_result.served_models) != {MODEL2_REQUIRED_SERVED_MODEL}:
            raise EvidenceValidationError("Full Context served model differs")
        request = dict(self.request_metrics)
        deployment = dict(self.deployment_metrics)
        if request != _prompt_metrics(self.evidence_bundle):
            raise EvidenceValidationError("Full Context request metrics differ")
        for key in ("provider_request_attempts", "model_calls", "prompt_tokens", "completion_tokens", "total_tokens", "elapsed_ms"):
            if key not in deployment or isinstance(deployment[key], bool) or not isinstance(deployment[key], int) or deployment[key] < 0:
                raise EvidenceValidationError(f"Full Context deployment metric is invalid: {key}")
        expected_usage = {
            key: sum(row[key] for row in self.answer_result.usage)
            for key in ("prompt_tokens", "completion_tokens", "total_tokens")
        }
        if deployment["provider_request_attempts"] != self.answer_result.provider_request_attempts:
            raise EvidenceValidationError("Full Context provider-attempt count differs")
        if deployment["model_calls"] != self.answer_result.model_calls:
            raise EvidenceValidationError("Full Context model-call count differs")
        if any(deployment[key] != expected_usage[key] for key in expected_usage):
            raise EvidenceValidationError("Full Context deployment usage differs")
        if deployment["total_tokens"] != deployment["prompt_tokens"] + deployment["completion_tokens"]:
            raise EvidenceValidationError("Full Context deployment token total differs")
        object.__setattr__(self, "request_metrics", request)
        object.__setattr__(self, "deployment_metrics", deployment)

    def _body(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "protocol_version": self.protocol_version,
            "status": self.status,
            "plan_id": self.plan_id,
            "run_id": self.run_id,
            "condition_id": FULL_CONTEXT_CONDITION_ID,
            "question": self.question.to_dict(),
            "question_sha256": self.question_sha256,
            "evidence_bundle": self.evidence_bundle.to_dict(),
            "evidence_payload_sha256": self.evidence_payload_sha256,
            "answer_result": self.answer_result.to_dict(),
            "request_metrics": dict(self.request_metrics),
            "deployment_metrics": dict(self.deployment_metrics),
        }

    def to_dict(self) -> dict[str, Any]:
        return {"record_id": self.record_id, **self._body()}

    @classmethod
    def create(cls, **values: Any) -> "FullContextRunRecord":
        placeholder = cls(record_id="full-context-record-" + "0" * 64, **values)
        identity = "full-context-record-" + sha256_bytes(canonical_json_bytes(placeholder._body()))
        return cls(**{**placeholder.__dict__, "record_id": identity})


def full_context_record_from_mapping(value: Mapping[str, Any]) -> FullContextRunRecord:
    if not isinstance(value, Mapping):
        raise EvidenceValidationError("Serialized Full Context record must be an object")
    data = dict(value)
    record_id = data.pop("record_id", None)
    condition = data.pop("condition_id", None)
    if condition != FULL_CONTEXT_CONDITION_ID:
        raise EvidenceValidationError("Serialized Full Context condition differs")
    data["question"] = QuestionInput.from_mapping(data["question"])
    data["evidence_bundle"] = full_context_bundle_from_mapping(data["evidence_bundle"])
    data["answer_result"] = answer_result_from_mapping(data["answer_result"])
    recreated = FullContextRunRecord.create(**data)
    if recreated.record_id != record_id or recreated.to_dict() != dict(value):
        raise EvidenceValidationError("Serialized Full Context record identity differs")
    return recreated


def _manifest_body(
    *, repo_root: Path, run_id: str, question_set: str, implementation_commit: str,
) -> dict[str, Any]:
    root = Path(repo_root).resolve()
    if _SAFE.fullmatch(run_id) is None:
        raise EvidenceValidationError("Full Context run_id is unsafe")
    if _COMMIT.fullmatch(implementation_commit) is None:
        raise EvidenceValidationError("Full Context implementation commit must be a full Git SHA")
    questions = _load_full_context_questions(root, question_set)
    question_set_manifest = _question_set_manifest(root, question_set, questions)
    model2_foundation = _verify_model2_foundation(root)
    loaded = load_r1_store(root, "s1")
    package = source_package(loaded)
    formal_path = root / "experiments/locomo-conv50-v1/formal-v1/manifest.json"
    formal = _read_json(formal_path)
    if formal.get("formal_manifest_id") != FULL_CONTEXT_PARENT_FORMAL_MANIFEST_ID:
        raise EvidenceValidationError("Parent formal-v1 manifest identity differs")
    verify_formal_manifest(root, formal_path)
    source_root = root / FULL_CONTEXT_SOURCE_RELATIVE_DIR
    source_files = {
        name: _file_sha256(source_root / name)
        for name in (
            "context-package.json",
            "manifest.json",
            "transcript.txt",
            "verification.json",
        )
    }
    published_source_manifest = _read_json(source_root / "manifest.json")
    published_verification = _read_json(source_root / "verification.json")
    if (
        published_source_manifest.get("source_package_id") != package["source_package_id"]
        or published_verification.get("status") != "passed"
        or published_verification.get("source_package_id") != package["source_package_id"]
    ):
        raise EvidenceValidationError("Published Full Context source artifacts differ")
    implementation_hashes = _implementation_hashes(root)
    plan_body = {
        "run_id": run_id,
        "question_set": question_set,
        "question_set_id": question_set_manifest["question_set_id"],
        "question_ids": [question.question_id for question in questions],
        "condition_id": FULL_CONTEXT_CONDITION_ID,
        "source_package_id": package["source_package_id"],
        "answerer_prompt_sha256": ANSWERER_SYSTEM_PROMPT_SHA256,
        "requested_model": MODEL2_REQUESTED_MODEL_ALIAS,
        "required_served_model": MODEL2_REQUIRED_SERVED_MODEL,
        "required_dev_pilot_run_id": (
            FULL_CONTEXT_DEV_PILOT_RUN_ID
            if question_set == FULL_CONTEXT_MAIN_QUESTION_SET
            else None
        ),
    }
    plan_id = "full-context-plan-" + sha256_bytes(canonical_json_bytes(plan_body))
    return {
        "schema_version": 1,
        "protocol_version": FULL_CONTEXT_RUN_PROTOCOL_VERSION,
        "status": "prepared",
        "run_id": run_id,
        "plan_id": plan_id,
        "implementation_git_commit": implementation_commit,
        "implementation_files": implementation_hashes,
        "implementation_tree_sha256": sha256_bytes(canonical_json_bytes(implementation_hashes)),
        "parent_formal_manifest_id": FULL_CONTEXT_PARENT_FORMAL_MANIFEST_ID,
        "parent_formal_manifest_sha256": _file_sha256(formal_path),
        "model2_foundation": model2_foundation,
        "condition_id": FULL_CONTEXT_CONDITION_ID,
        "full_context_protocol_version": FULL_CONTEXT_PROTOCOL_VERSION,
        "full_context_contract_sha256": FULL_CONTEXT_CONTRACT_SHA256,
        "context_policy": FULL_CONTEXT_CONTEXT_POLICY,
        "source_package_id": package["source_package_id"],
        "source_package_sha256": source_files["context-package.json"],
        "source_artifact_files": source_files,
        "source_manifest_id": published_source_manifest["manifest_id"],
        "source_verification_id": published_verification["verification_id"],
        "source_snapshot": loaded.snapshot.to_dict(),
        "context_stats": package["context_stats"],
        "question_set": question_set_manifest,
        "answerer": {
            "protocol_version": ANSWERER_PROTOCOL_VERSION,
            "prompt_sha256": ANSWERER_SYSTEM_PROMPT_SHA256,
            "temperature": ANSWERER_TEMPERATURE,
            "planning_max_completion_tokens": ANSWERER_MAX_COMPLETION_TOKENS,
            "wire_max_completion_tokens": None,
            "portable_api_omits_max_completion_tokens": True,
            "configured_reasoning_effort": "high",
            "wire_reasoning_effort": None,
            "portable_api_omits_reasoning_effort": True,
            "tools": "none",
            "format_repair_limit": ANSWERER_FORMAT_REPAIR_LIMIT,
            "timeout_attempts": ANSWERER_TIMEOUT_MAX_ATTEMPTS,
            "timeout_backoff_seconds": list(ANSWERER_TIMEOUT_BACKOFF_SECONDS),
            "http_attempts": ANSWERER_HTTP_MAX_ATTEMPTS,
            "http_backoff_seconds": list(ANSWERER_HTTP_BACKOFF_SECONDS),
            "retryable_http_status_codes": sorted(RETRYABLE_HTTP_STATUS_CODES),
        },
        "deployment": {
            "requested_model_alias": MODEL2_REQUESTED_MODEL_ALIAS,
            "required_served_model": MODEL2_REQUIRED_SERVED_MODEL,
            "chat_endpoint": MODEL2_CHAT_ENDPOINT,
            "api_style": MODEL2_API_STYLE,
            "context_limit_tokens": MODEL2_CONTEXT_LIMIT,
            "request_timeout_seconds": MODEL2_REQUEST_TIMEOUT_SECONDS,
            "max_response_bytes": MODEL2_MAX_RESPONSE_BYTES,
            "concurrency": MODEL2_CONCURRENCY,
            "identity_policy": (
                "every response including Answerer format repair must report the "
                "exact required_served_model"
            ),
        },
        "execution": {
            "batch_size": FULL_CONTEXT_BATCH_SIZE,
            "batches": (len(questions) + FULL_CONTEXT_BATCH_SIZE - 1) // FULL_CONTEXT_BATCH_SIZE,
            "preflight_question_id": FULL_CONTEXT_PREFLIGHT_QUESTION_ID if question_set == "dev-6" else None,
            "require_verified_dev_pilot": question_set == FULL_CONTEXT_MAIN_QUESTION_SET,
            "required_dev_pilot_run_id": (
                FULL_CONTEXT_DEV_PILOT_RUN_ID
                if question_set == FULL_CONTEXT_MAIN_QUESTION_SET
                else None
            ),
            "search_calls_per_question": 0,
            "answerer_calls_per_question": 1,
            "stop_on_failure": True,
            "resume": "verify-and-skip-only-completed-records",
        },
        "gold_access": "forbidden-until-pre-gold-audit-passed",
    }


def prepare_full_context_run(
    *, repo_root: Path, output_root: Path, run_id: str, question_set: str,
    implementation_commit: str,
) -> Path:
    root = Path(repo_root).resolve()
    if question_set not in {"dev-6", FULL_CONTEXT_MAIN_QUESTION_SET}:
        raise EvidenceValidationError(
            "Full Context question_set must be dev-6 or main-60-v2"
        )
    if question_set == "dev-6" and run_id != FULL_CONTEXT_DEV_PILOT_RUN_ID:
        raise EvidenceValidationError("Full Context dev pilot run ID differs")
    if question_set == FULL_CONTEXT_MAIN_QUESTION_SET and run_id != FULL_CONTEXT_MAIN_RUN_ID:
        raise EvidenceValidationError("Full Context main-60 run ID differs")
    publish_source_package(
        repo_root=root, output_dir=root / FULL_CONTEXT_SOURCE_RELATIVE_DIR
    )
    body = _manifest_body(
        repo_root=root,
        run_id=run_id,
        question_set=question_set,
        implementation_commit=implementation_commit,
    )
    manifest = {
        "manifest_id": "full-context-run-manifest-" + sha256_bytes(canonical_json_bytes(body)),
        **body,
    }
    run_root = Path(output_root).resolve() / run_id
    run_root.mkdir(parents=True, exist_ok=True)
    path = run_root / "run-manifest.json"
    _publish_idempotent(path, manifest)
    _append_event(
        run_root / "events.jsonl",
        {"event": "full_context_run_prepared", "at": _now(), "manifest_id": manifest["manifest_id"]},
    )
    write_full_context_status(repo_root=root, output_root=output_root, run_id=run_id)
    return path


def _open_run(
    *, repo_root: Path, output_root: Path, run_id: str,
) -> tuple[Path, dict[str, Any], tuple[QuestionInput, ...]]:
    root = Path(repo_root).resolve()
    run_root = Path(output_root).resolve() / run_id
    manifest = _read_json(run_root / "run-manifest.json")
    identity = manifest.get("manifest_id")
    body = {key: value for key, value in manifest.items() if key != "manifest_id"}
    if identity != "full-context-run-manifest-" + sha256_bytes(canonical_json_bytes(body)):
        raise EvidenceValidationError("Full Context run manifest identity differs")
    expected = _manifest_body(
        repo_root=root,
        run_id=run_id,
        question_set=manifest["question_set"]["name"],
        implementation_commit=manifest["implementation_git_commit"],
    )
    if body != expected:
        raise EvidenceValidationError("Full Context run manifest or inputs drifted")
    questions = _load_full_context_questions(root, manifest["question_set"]["name"])
    return run_root, manifest, questions


def _record_path(run_root: Path, question_id: str) -> Path:
    if _SAFE.fullmatch(question_id) is None:
        raise EvidenceValidationError("Full Context question_id is unsafe")
    return run_root / "records" / FULL_CONTEXT_CONDITION_ID / question_id / "record.json"


def _load_record(path: Path) -> FullContextRunRecord:
    return full_context_record_from_mapping(_read_json(path))


def _publish_completed_batch_audits(
    *, run_root: Path, manifest: Mapping[str, Any],
    questions: Sequence[QuestionInput], completed_ids: set[str],
) -> list[str]:
    """Publish deterministic audits only for complete consecutive plan blocks."""

    published: list[str] = []
    total_batches = int(manifest["execution"]["batches"])
    for batch_number in range(1, total_batches + 1):
        start = (batch_number - 1) * FULL_CONTEXT_BATCH_SIZE
        stop = min(len(questions), batch_number * FULL_CONTEXT_BATCH_SIZE)
        members = tuple(questions[start:stop])
        if not members or any(row.question_id not in completed_ids for row in members):
            break
        records = tuple(
            _load_record(_record_path(run_root, row.question_id)) for row in members
        )
        checks = {
            "question_block_exact": tuple(
                record.question.question_id for record in records
            ) == tuple(row.question_id for row in members),
            "run_and_plan_exact": all(
                record.run_id == manifest["run_id"]
                and record.plan_id == manifest["plan_id"]
                for record in records
            ),
            "source_snapshot_exact": all(
                record.evidence_bundle.store_snapshot.to_dict()
                == manifest["source_snapshot"]
                for record in records
            ),
            "all_30_sessions": all(
                len(record.evidence_bundle.evidence_items) == 30 for record in records
            ),
            "served_model_constant": all(
                set(record.answer_result.served_models)
                == {MODEL2_REQUIRED_SERVED_MODEL}
                for record in records
            ),
            "record_ids_unique": len({record.record_id for record in records})
            == len(records),
        }
        body = {
            "schema_version": 1,
            "protocol_version": FULL_CONTEXT_RUN_PROTOCOL_VERSION,
            "status": "passed" if all(checks.values()) else "failed",
            "run_id": manifest["run_id"],
            "plan_id": manifest["plan_id"],
            "batch_number": batch_number,
            "question_positions": [start + 1, stop],
            "question_ids": [row.question_id for row in members],
            "record_ids": [record.record_id for record in records],
            "checks": checks,
        }
        if body["status"] != "passed":
            raise EvidenceValidationError(
                f"Full Context batch {batch_number:02d} audit failed"
            )
        audit = {
            "audit_id": "full-context-batch-audit-"
            + sha256_bytes(canonical_json_bytes(body)),
            **body,
        }
        audit_path = run_root / "audits" / f"batch-{batch_number:02d}-audit.json"
        marker_path = run_root / "audits" / f"batch-{batch_number:02d}.PASSED"
        _publish_idempotent(audit_path, audit)
        _publish_idempotent(
            marker_path,
            {
                "status": "passed",
                "audit_id": audit["audit_id"],
                "batch_number": batch_number,
            },
        )
        published.append(audit["audit_id"])
    return published


def write_full_context_status(
    *, repo_root: Path, output_root: Path, run_id: str,
) -> dict[str, Any]:
    run_root, manifest, questions = _open_run(
        repo_root=repo_root, output_root=output_root, run_id=run_id
    )
    completed: list[str] = []
    failures = 0
    failed_question_ids: set[str] = set()
    for question in questions:
        path = _record_path(run_root, question.question_id)
        if path.exists():
            record = _load_record(path)
            if record.run_id != run_id or record.plan_id != manifest["plan_id"] or record.question != question:
                raise EvidenceValidationError("Full Context completed record differs from plan")
            completed.append(question.question_id)
        failure_dir = run_root / "failures" / FULL_CONTEXT_CONDITION_ID / question.question_id
        if failure_dir.exists():
            attempts = tuple(failure_dir.glob("attempt-*.json"))
            failures += len(attempts)
            if attempts:
                failed_question_ids.add(question.question_id)
    pending = [question.question_id for question in questions if question.question_id not in set(completed)]
    completed_ids = set(completed)
    active_failed = sorted(failed_question_ids - completed_ids)
    identity_drift = False
    identity_marker_path = run_root / FULL_CONTEXT_IDENTITY_DRIFT_MARKER
    if identity_marker_path.exists() or identity_marker_path.is_symlink():
        identity_marker = _read_json(identity_marker_path)
        if (
            identity_marker.get("status") != "halted"
            or identity_marker.get("run_id") != run_id
            or identity_marker.get("manifest_id") != manifest["manifest_id"]
            or identity_marker.get("recovery") != "forbidden"
        ):
            raise EvidenceValidationError("Full Context identity-drift marker differs")
        identity_drift = True
    batch_audits = _publish_completed_batch_audits(
        run_root=run_root,
        manifest=manifest,
        questions=questions,
        completed_ids=completed_ids,
    )
    completed_prefix = 0
    for question in questions:
        if question.question_id not in completed_ids:
            break
        completed_prefix += 1
    body = {
        "schema_version": 1,
        "protocol_version": FULL_CONTEXT_RUN_PROTOCOL_VERSION,
        "run_id": run_id,
        "plan_id": manifest["plan_id"],
        "question_set": manifest["question_set"]["name"],
        "status": (
            "halted" if identity_drift else "completed" if not pending else "pending"
        ),
        "identity_drift": identity_drift,
        "planned_records": len(questions),
        "completed_records": len(completed),
        "pending_records": len(pending),
        "completed_question_ids": completed,
        "next_question_id": pending[0] if pending else None,
        "failure_attempts": failures,
        "active_failed_question_ids": active_failed,
        "active_failed_questions": len(active_failed),
        "completed_prefix_records": completed_prefix,
        "completed_batches": len(batch_audits),
        "batch_audit_ids": batch_audits,
        "updated_at": _now(),
    }
    _write_atomic(run_root / "status.json", body)
    return body


def inspect_full_context(*, repo_root: Path, question_set: str) -> dict[str, Any]:
    root = Path(repo_root).resolve()
    questions = _load_full_context_questions(root, question_set)
    loaded = load_r1_store(root, "s1")
    items = build_full_context_items(loaded)
    rows = []
    for question in questions:
        bundle = build_full_context_bundle(
            question=question,
            loaded_store=loaded,
            evidence_items=items,
        )
        rows.append({"question_id": question.question_id, **_prompt_metrics(bundle)})
    largest = max(rows, key=lambda row: (row["total_message_characters"], row["question_id"]))
    return {
        "status": "passed",
        "question_set": question_set,
        "question_count": len(questions),
        "condition_id": FULL_CONTEXT_CONDITION_ID,
        "online_flow": "one full-context Answerer call; no search",
        "source": full_context_stats(items),
        "largest_request": largest,
        "request_range": {
            "characters_min": min(row["total_message_characters"] for row in rows),
            "characters_max": max(row["total_message_characters"] for row in rows),
            "bytes_min": min(row["total_message_bytes"] for row in rows),
            "bytes_max": max(row["total_message_bytes"] for row in rows),
            "estimated_input_tokens_low": min(row["estimated_input_tokens_low"] for row in rows),
            "estimated_input_tokens_high": max(row["estimated_input_tokens_high"] for row in rows),
        },
        "deployment_context_window_known": True,
        "deployment_context_limit_tokens": MODEL2_CONTEXT_LIMIT,
        "estimated_request_with_output_fits_context": (
            largest["estimated_total_context_with_2048_output_high"]
            < MODEL2_CONTEXT_LIMIT
        ),
        "api_preflight_required": True,
        "rows": rows,
    }


def dry_run_full_context(
    *, repo_root: Path, output_root: Path, run_id: str,
) -> dict[str, Any]:
    root = Path(repo_root).resolve()
    run_root, manifest, questions = _open_run(
        repo_root=root, output_root=output_root, run_id=run_id
    )
    status = write_full_context_status(repo_root=root, output_root=output_root, run_id=run_id)
    if status["completed_records"] or status["failure_attempts"]:
        raise EvidenceValidationError("Full Context dry-run is only valid before API work")
    inspection = inspect_full_context(
        repo_root=root, question_set=manifest["question_set"]["name"]
    )
    checks = {
        "manifest_verified": True,
        "source_sessions_30": manifest["context_stats"]["session_count"] == 30,
        "source_turns_568": manifest["context_stats"]["turn_count"] == 568,
        "caption_turns_125": manifest["context_stats"]["caption_turn_count"] == 125,
        "no_search": manifest["execution"]["search_calls_per_question"] == 0,
        "no_truncation": manifest["context_policy"] == FULL_CONTEXT_CONTEXT_POLICY,
        "question_count_exact": len(questions) == manifest["question_set"]["question_count"],
        "api_provider_not_constructed": True,
        "semantic_gold_not_loaded": True,
    }
    report = {
        "schema_version": 1,
        "protocol_version": FULL_CONTEXT_RUN_PROTOCOL_VERSION,
        "status": "passed" if all(checks.values()) else "failed",
        "run_id": run_id,
        "manifest_id": manifest["manifest_id"],
        "checks": checks,
        "inspection": inspection,
        "run_root": str(run_root),
    }
    _publish_idempotent(run_root / "dry-run.json", report)
    return report


@contextmanager
def _run_lock(run_root: Path):
    path = run_root / "run.lock"
    descriptor = os.open(path, os.O_RDWR | os.O_CREAT, 0o600)
    try:
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise EvidenceValidationError("Another Full Context runner holds run.lock") from exc
        yield
    finally:
        fcntl.flock(descriptor, fcntl.LOCK_UN)
        os.close(descriptor)


def _assert_no_identity_drift(run_root: Path) -> None:
    if (run_root / FULL_CONTEXT_IDENTITY_DRIFT_MARKER).exists():
        raise EvidenceValidationError(
            "Full Context run is permanently halted after a model identity violation"
        )


def _seal_identity_drift(
    *, run_root: Path, manifest: Mapping[str, Any], question: QuestionInput,
    provider: ModelIdentityProvider,
) -> None:
    if provider.identity_error is None:
        return
    _publish_idempotent(
        run_root / FULL_CONTEXT_IDENTITY_DRIFT_MARKER,
        {
            "schema_version": 1,
            "protocol_version": FULL_CONTEXT_RUN_PROTOCOL_VERSION,
            "status": "halted",
            "run_id": manifest["run_id"],
            "manifest_id": manifest["manifest_id"],
            "question_id": question.question_id,
            "requested_model_alias": MODEL2_REQUESTED_MODEL_ALIAS,
            "required_served_model": MODEL2_REQUIRED_SERVED_MODEL,
            "observed_served_model": provider.observed_served_model,
            "error_type": "ModelIdentityError",
            "reason": "provider response violated the frozen model identity",
            "recovery": "forbidden",
        },
    )


def _preflight_marker_value(
    *, manifest: Mapping[str, Any], record: FullContextRunRecord,
) -> dict[str, Any]:
    metrics = _prompt_metrics(record.evidence_bundle)
    body = {
        "schema_version": 1,
        "protocol_version": FULL_CONTEXT_RUN_PROTOCOL_VERSION,
        "status": "passed",
        "run_id": manifest["run_id"],
        "manifest_id": manifest["manifest_id"],
        "question_id": record.question.question_id,
        "record_id": record.record_id,
        "requested_model_alias": MODEL2_REQUESTED_MODEL_ALIAS,
        "required_served_model": MODEL2_REQUIRED_SERVED_MODEL,
        "total_message_characters": metrics["total_message_characters"],
        "estimated_total_context_with_2048_output_high": metrics[
            "estimated_total_context_with_2048_output_high"
        ],
        "context_limit_tokens": MODEL2_CONTEXT_LIMIT,
        "full_context_session_count": len(record.evidence_bundle.evidence_items),
    }
    return {
        "preflight_id": "full-context-model2-preflight-"
        + sha256_bytes(canonical_json_bytes(body)),
        **body,
    }


def _publish_long_context_preflight(
    *, run_root: Path, manifest: Mapping[str, Any],
) -> dict[str, Any]:
    if manifest["question_set"]["name"] != "dev-6":
        raise EvidenceValidationError("Long-context preflight requires dev-6")
    record = _load_record(_record_path(run_root, FULL_CONTEXT_PREFLIGHT_QUESTION_ID))
    if (
        record.question.question_id != FULL_CONTEXT_PREFLIGHT_QUESTION_ID
        or record.run_id != manifest["run_id"]
        or record.plan_id != manifest["plan_id"]
        or set(record.answer_result.served_models)
        != {MODEL2_REQUIRED_SERVED_MODEL}
        or len(record.evidence_bundle.evidence_items) != 30
    ):
        raise EvidenceValidationError("Long-context preflight record differs")
    value = _preflight_marker_value(manifest=manifest, record=record)
    if value["estimated_total_context_with_2048_output_high"] >= MODEL2_CONTEXT_LIMIT:
        raise EvidenceValidationError("Long-context preflight exceeds context limit")
    _publish_idempotent(run_root / FULL_CONTEXT_PREFLIGHT_PASSED_MARKER, value)
    return value


def _verify_long_context_preflight(
    *, run_root: Path, manifest: Mapping[str, Any],
) -> dict[str, Any]:
    path = run_root / FULL_CONTEXT_PREFLIGHT_PASSED_MARKER
    if not path.is_file() or path.is_symlink():
        raise EvidenceValidationError(
            "Complete the fixed q079 long-context preflight before the pilot"
        )
    expected = _publish_long_context_preflight(run_root=run_root, manifest=manifest)
    observed = _read_json(path)
    if observed != expected:
        raise EvidenceValidationError("Long-context preflight marker differs")
    return observed


def _publish_failure(
    *, run_root: Path, manifest: Mapping[str, Any], question: QuestionInput,
    error: Exception, provider: ChatProvider,
    attempt_usage: Mapping[str, int],
    provider_failures: Sequence[Mapping[str, Any]],
) -> Path:
    directory = run_root / "failures" / FULL_CONTEXT_CONDITION_ID / question.question_id
    directory.mkdir(parents=True, exist_ok=True)
    attempt_numbers: list[int] = []
    for path in sorted(directory.glob("attempt-*.json")):
        if path.is_symlink() or not path.is_file():
            raise EvidenceValidationError("Unsafe Full Context failure checkpoint")
        match = re.fullmatch(r"attempt-([0-9]{4,})\.json", path.name)
        if match is None:
            raise EvidenceValidationError("Malformed Full Context failure checkpoint")
        attempt_numbers.append(int(match.group(1)))
    attempt = max(attempt_numbers, default=0) + 1
    cause: BaseException | None = error
    retryable = False
    while cause is not None:
        if isinstance(cause, TransientProviderError):
            retryable = True
            break
        cause = cause.__cause__
    if isinstance(error, AnswererError) and error.stage == "provider":
        retryable = retryable or isinstance(error.__cause__, TransientProviderError)
    body = {
        "schema_version": 1,
        "protocol_version": FULL_CONTEXT_FAILURE_PROTOCOL_VERSION,
        "status": "failed",
        "run_id": manifest["run_id"],
        "plan_id": manifest["plan_id"],
        "condition_id": FULL_CONTEXT_CONDITION_ID,
        "question_id": question.question_id,
        "question_sha256": question.sha256,
        "attempt": attempt,
        "stage": getattr(error, "stage", "full_context_answer"),
        "error_type": type(error).__name__,
        "message": _safe_error(error, provider),
        "retryable": retryable,
        "attempt_usage": dict(attempt_usage),
        "provider_failures": [dict(row) for row in provider_failures],
        "at": _now(),
    }
    value = {
        "failure_id": "full-context-failure-" + sha256_bytes(canonical_json_bytes(body)),
        **body,
    }
    path = directory / f"attempt-{attempt:04d}.json"
    _write_exclusive(path, value)
    return path


def _target_questions(
    *, questions: tuple[QuestionInput, ...], question_id: str | None,
    through_block: int | None, run_all: bool,
) -> tuple[QuestionInput, ...]:
    modes = sum(value is not None for value in (question_id, through_block)) + int(run_all)
    if modes != 1:
        raise EvidenceValidationError("Select exactly one run target")
    if question_id is not None:
        matches = tuple(question for question in questions if question.question_id == question_id)
        if len(matches) != 1:
            raise EvidenceValidationError("Requested Full Context question is outside the plan")
        return matches
    if through_block is not None:
        maximum = (len(questions) + FULL_CONTEXT_BATCH_SIZE - 1) // FULL_CONTEXT_BATCH_SIZE
        if through_block < 1 or through_block > maximum:
            raise EvidenceValidationError("Full Context batch boundary is invalid")
        return questions[: min(len(questions), through_block * FULL_CONTEXT_BATCH_SIZE)]
    return questions


def _verify_required_dev_pilot(
    *, repo_root: Path, output_root: Path, main_run_root: Path,
    main_manifest: Mapping[str, Any],
) -> dict[str, Any]:
    """Require the fixed, compatible dev-6 pilot before any main API call."""

    if main_manifest["question_set"]["name"] != FULL_CONTEXT_MAIN_QUESTION_SET:
        raise EvidenceValidationError("Dev-pilot gate applies only to main-60-v2")
    execution = dict(main_manifest["execution"])
    if (
        execution.get("require_verified_dev_pilot") is not True
        or execution.get("required_dev_pilot_run_id")
        != FULL_CONTEXT_DEV_PILOT_RUN_ID
    ):
        raise EvidenceValidationError("Full Context main run did not pin the dev pilot")

    dev_audit = verify_full_context_run(
        repo_root=repo_root,
        output_root=output_root,
        run_id=FULL_CONTEXT_DEV_PILOT_RUN_ID,
    )
    dev_root = Path(output_root).resolve() / FULL_CONTEXT_DEV_PILOT_RUN_ID
    dev_manifest = _read_json(dev_root / "run-manifest.json")
    dev_preflight = _verify_long_context_preflight(
        run_root=dev_root, manifest=dev_manifest
    )
    dev_question_ids = tuple(
        row["question_id"] for row in dev_manifest["question_set"]["question_order"]
    )
    checks = {
        "dev_pre_gold_audit_passed": dev_audit.get("status") == "passed",
        "dev_long_context_preflight_passed": dev_preflight.get("status") == "passed",
        "dev_question_set_exact": (
            dev_manifest["question_set"]["name"] == "dev-6"
            and dev_manifest["question_set"]["question_count"] == 6
            and FULL_CONTEXT_PREFLIGHT_QUESTION_ID in dev_question_ids
        ),
        "implementation_commit_exact": (
            dev_manifest["implementation_git_commit"]
            == main_manifest["implementation_git_commit"]
        ),
        "implementation_tree_exact": (
            dev_manifest["implementation_tree_sha256"]
            == main_manifest["implementation_tree_sha256"]
            and dev_manifest["implementation_files"]
            == main_manifest["implementation_files"]
        ),
        "parent_formal_manifest_exact": (
            dev_manifest["parent_formal_manifest_id"]
            == main_manifest["parent_formal_manifest_id"]
            and dev_manifest["parent_formal_manifest_sha256"]
            == main_manifest["parent_formal_manifest_sha256"]
        ),
        "model2_foundation_exact": (
            dev_manifest["model2_foundation"]
            == main_manifest["model2_foundation"]
        ),
        "protocol_contract_exact": all(
            dev_manifest[key] == main_manifest[key]
            for key in (
                "condition_id",
                "full_context_protocol_version",
                "full_context_contract_sha256",
                "context_policy",
            )
        ),
        "source_package_exact": all(
            dev_manifest[key] == main_manifest[key]
            for key in (
                "source_package_id",
                "source_package_sha256",
                "source_artifact_files",
                "source_manifest_id",
                "source_verification_id",
                "source_snapshot",
                "context_stats",
            )
        ),
        "answerer_exact": dev_manifest["answerer"] == main_manifest["answerer"],
        "deployment_exact": dev_manifest["deployment"] == main_manifest["deployment"],
    }
    body = {
        "schema_version": 1,
        "protocol_version": FULL_CONTEXT_RUN_PROTOCOL_VERSION,
        "status": "passed" if all(checks.values()) else "failed",
        "main_run_id": main_manifest["run_id"],
        "main_manifest_id": main_manifest["manifest_id"],
        "dev_run_id": FULL_CONTEXT_DEV_PILOT_RUN_ID,
        "dev_manifest_id": dev_manifest["manifest_id"],
        "dev_pre_gold_audit_id": dev_audit["audit_id"],
        "dev_long_context_preflight_id": dev_preflight["preflight_id"],
        "checks": checks,
    }
    if body["status"] != "passed":
        raise EvidenceValidationError("Full Context dev-pilot compatibility gate failed")
    report = {
        "gate_id": "full-context-dev-pilot-gate-"
        + sha256_bytes(canonical_json_bytes(body)),
        **body,
    }
    _publish_idempotent(main_run_root / "dev-pilot-gate.json", report)
    return report


def run_full_context(
    *, repo_root: Path, output_root: Path, run_id: str, provider: ChatProvider,
    question_id: str | None = None, through_block: int | None = None,
    run_all: bool = False, sleeper=time.sleep,
) -> dict[str, Any]:
    root = Path(repo_root).resolve()
    run_root, manifest, questions = _open_run(
        repo_root=root, output_root=output_root, run_id=run_id
    )
    _assert_no_identity_drift(run_root)
    targets = _target_questions(
        questions=questions, question_id=question_id,
        through_block=through_block, run_all=run_all,
    )
    if manifest["question_set"]["name"] == FULL_CONTEXT_MAIN_QUESTION_SET:
        _verify_required_dev_pilot(
            repo_root=root,
            output_root=output_root,
            main_run_root=run_root,
            main_manifest=manifest,
        )
    elif (
        question_id != FULL_CONTEXT_PREFLIGHT_QUESTION_ID
        or through_block is not None
        or run_all
    ):
        _verify_long_context_preflight(run_root=run_root, manifest=manifest)
    _provider_preflight(provider)
    loaded = load_r1_store(root, "s1")
    items = build_full_context_items(loaded)
    guarded_provider = ModelIdentityProvider(
        provider,
        requested_model_alias=MODEL2_REQUESTED_MODEL_ALIAS,
        required_served_model=MODEL2_REQUIRED_SERVED_MODEL,
    )
    answerer = SharedAnswerer(
        provider=guarded_provider,
        requested_model=MODEL2_REQUESTED_MODEL_ALIAS,
        sleeper=sleeper,
    )
    with _run_lock(run_root):
        for question in targets:
            path = _record_path(run_root, question.question_id)
            if path.exists():
                record = _load_record(path)
                if (
                    record.run_id != run_id
                    or record.plan_id != manifest["plan_id"]
                    or record.question != question
                ):
                    raise EvidenceValidationError(
                        "Full Context completed checkpoint differs from plan"
                    )
                verify_full_context_bundle(
                    record.evidence_bundle,
                    loaded_store=loaded,
                    expected_items=items,
                )
                continue
            bundle = build_full_context_bundle(
                question=question,
                loaded_store=loaded,
                evidence_items=items,
            )
            started = time.monotonic()
            usage_cursor = guarded_provider.usage_cursor()
            provider_failure_cursor = guarded_provider.provider_failure_cursor()
            try:
                answer = answerer.run(bundle)
                if set(answer.served_models) != {MODEL2_REQUIRED_SERVED_MODEL}:
                    raise EvidenceValidationError("Full Context Answerer served model drifted")
                elapsed_ms = max(0, round((time.monotonic() - started) * 1000))
                usage = {
                    key: sum(row[key] for row in answer.usage)
                    for key in ("prompt_tokens", "completion_tokens", "total_tokens")
                }
                record = FullContextRunRecord.create(
                    schema_version=1,
                    protocol_version=FULL_CONTEXT_RECORD_PROTOCOL_VERSION,
                    status="completed",
                    plan_id=manifest["plan_id"],
                    run_id=run_id,
                    question=question,
                    question_sha256=question.sha256,
                    evidence_bundle=bundle,
                    evidence_payload_sha256=sha256_bytes(canonical_json_bytes(bundle.to_dict())),
                    answer_result=answer,
                    request_metrics=_prompt_metrics(bundle),
                    deployment_metrics={
                        "provider_request_attempts": answer.provider_request_attempts,
                        "model_calls": answer.model_calls,
                        **usage,
                        "elapsed_ms": elapsed_ms,
                    },
                )
                _write_exclusive(path, record.to_dict())
            except Exception as error:
                if guarded_provider.identity_error is not None:
                    _seal_identity_drift(
                        run_root=run_root,
                        manifest=manifest,
                        question=question,
                        provider=guarded_provider,
                    )
                    error = guarded_provider.identity_error
                failure = _publish_failure(
                    run_root=run_root, manifest=manifest, question=question,
                    error=error, provider=guarded_provider,
                    attempt_usage=guarded_provider.usage_since(usage_cursor),
                    provider_failures=guarded_provider.provider_failures_since(
                        provider_failure_cursor
                    ),
                )
                _append_event(
                    run_root / "events.jsonl",
                    {
                        "event": "full_context_record_failed", "at": _now(),
                        "question_id": question.question_id, "failure": str(failure),
                        "error_type": type(error).__name__,
                    },
                )
                status = write_full_context_status(
                    repo_root=root, output_root=output_root, run_id=run_id
                )
                return {"status": "failed", "question_id": question.question_id, "progress": status}
            _append_event(
                run_root / "events.jsonl",
                {
                    "event": "full_context_record_verified", "at": _now(),
                    "question_id": question.question_id,
                    "record_id": record.record_id,
                    "prompt_tokens": record.deployment_metrics["prompt_tokens"],
                    "total_tokens": record.deployment_metrics["total_tokens"],
                    "elapsed_ms": record.deployment_metrics["elapsed_ms"],
                },
            )
            print(
                f"FULL_CONTEXT VERIFIED {question.question_id} "
                f"tokens={record.deployment_metrics['total_tokens']}",
                flush=True,
            )
        if (
            manifest["question_set"]["name"] == "dev-6"
            and _record_path(run_root, FULL_CONTEXT_PREFLIGHT_QUESTION_ID).is_file()
        ):
            _publish_long_context_preflight(run_root=run_root, manifest=manifest)
        status = write_full_context_status(
            repo_root=root, output_root=output_root, run_id=run_id
        )
        _append_event(
            run_root / "events.jsonl",
            {"event": "full_context_target_reached", "at": _now(), **status},
        )
        return status


def verify_full_context_run(
    *, repo_root: Path, output_root: Path, run_id: str,
) -> dict[str, Any]:
    root = Path(repo_root).resolve()
    run_root, manifest, questions = _open_run(
        repo_root=root, output_root=output_root, run_id=run_id
    )
    pilot_gate = None
    long_context_preflight = None
    if manifest["question_set"]["name"] == FULL_CONTEXT_MAIN_QUESTION_SET:
        pilot_gate = _verify_required_dev_pilot(
            repo_root=root,
            output_root=output_root,
            main_run_root=run_root,
            main_manifest=manifest,
        )
    else:
        long_context_preflight = _verify_long_context_preflight(
            run_root=run_root, manifest=manifest
        )
    status = write_full_context_status(repo_root=root, output_root=output_root, run_id=run_id)
    if status["completed_records"] != len(questions) or status["pending_records"] != 0:
        raise EvidenceValidationError("Full Context run is incomplete")
    loaded = load_r1_store(root, "s1")
    items = build_full_context_items(loaded)
    served: set[str] = set()
    record_ids: list[str] = []
    prompt_tokens: list[int] = []
    for question in questions:
        record = _load_record(_record_path(run_root, question.question_id))
        verify_full_context_bundle(
            record.evidence_bundle,
            loaded_store=loaded,
            expected_items=items,
        )
        served.update(record.answer_result.served_models)
        record_ids.append(record.record_id)
        prompt_tokens.append(int(record.deployment_metrics["prompt_tokens"]))
    checks = {
        "all_records_complete": len(record_ids) == len(questions),
        "record_ids_unique": len(record_ids) == len(set(record_ids)),
        "served_model_constant": served == {MODEL2_REQUIRED_SERVED_MODEL},
        "source_store_unchanged": loaded.snapshot.to_dict() == manifest["source_snapshot"],
        "all_30_sessions_each_record": all(
            len(_load_record(_record_path(run_root, question.question_id)).evidence_bundle.evidence_items) == 30
            for question in questions
        ),
        "all_batch_audits_passed": status["completed_batches"]
        == manifest["execution"]["batches"],
        "no_active_failures": status["active_failed_questions"] == 0,
        "required_dev_pilot_passed": (
            pilot_gate is not None
            if manifest["question_set"]["name"] == FULL_CONTEXT_MAIN_QUESTION_SET
            else True
        ),
        "long_context_preflight_passed": (
            long_context_preflight is not None
            if manifest["question_set"]["name"] == "dev-6"
            else True
        ),
        "gold_not_loaded": True,
    }
    body = {
        "schema_version": 1,
        "protocol_version": FULL_CONTEXT_RUN_PROTOCOL_VERSION,
        "status": "passed" if all(checks.values()) else "failed",
        "run_id": run_id,
        "manifest_id": manifest["manifest_id"],
        "checks": checks,
        "record_count": len(record_ids),
        "dev_pilot_gate_id": pilot_gate["gate_id"] if pilot_gate is not None else None,
        "long_context_preflight_id": (
            long_context_preflight["preflight_id"]
            if long_context_preflight is not None
            else None
        ),
        "records_sha256": sha256_bytes(canonical_json_bytes(record_ids)),
        "provider_prompt_tokens": {
            "min": min(prompt_tokens), "max": max(prompt_tokens),
            "mean": sum(prompt_tokens) / len(prompt_tokens),
        },
    }
    if body["status"] != "passed":
        raise EvidenceValidationError("Full Context pre-gold audit failed")
    report = {
        "audit_id": "full-context-pre-gold-" + sha256_bytes(canonical_json_bytes(body)),
        **body,
    }
    _publish_idempotent(run_root / "pre-gold-audit.json", report)
    marker_name = (
        FULL_CONTEXT_MAIN_PASSED_MARKER
        if manifest["question_set"]["name"] == FULL_CONTEXT_MAIN_QUESTION_SET
        else FULL_CONTEXT_DEV_PASSED_MARKER
    )
    _publish_idempotent(
        run_root / marker_name,
        {
            "status": "passed",
            "run_id": run_id,
            "audit_id": report["audit_id"],
            "record_count": len(record_ids),
        },
    )
    return report


def _token_precision_recall(prediction: str, truth: str) -> tuple[float, float]:
    predicted = [_STEMMER.stem(token) for token in normalize_answer(prediction).split()]
    expected = [_STEMMER.stem(token) for token in normalize_answer(truth).split()]
    common = sum((Counter(predicted) & Counter(expected)).values())
    precision = common / len(predicted) if predicted else 0.0
    recall = common / len(expected) if expected else 0.0
    return precision, recall


def _load_full_context_gold(
    repo_root: Path, question_set: str,
) -> tuple[GoldRecord, ...]:
    """Load semantic gold only after the pre-gold audit has passed."""

    root = Path(repo_root).resolve()
    if question_set == "dev-6":
        spec = FULL_CONTEXT_GOLD["dev-6"]
        return load_gold_records(
            root / spec["relative_path"], expected_sha256=spec["sha256"]
        )
    if question_set != FULL_CONTEXT_MAIN_QUESTION_SET:
        raise EvidenceValidationError("Unknown Full Context evaluation question set")
    output: list[GoldRecord] = []
    for name in ("main-40", "extension-20"):
        spec = FULL_CONTEXT_GOLD[name]
        output.extend(
            load_gold_records(
                root / spec["relative_path"], expected_sha256=spec["sha256"]
            )
        )
    if len(output) != 60 or len({row.question_id for row in output}) != 60:
        raise EvidenceValidationError("Composite main-60 gold membership differs")
    return tuple(output)


def _failure_overhead(
    *, run_root: Path, manifest: Mapping[str, Any],
    questions: Sequence[QuestionInput],
) -> dict[str, Any]:
    """Validate and total immutable costs from failed run attempts.

    Successful records already contain every request made within their own
    Answerer episode.  A failed episode is stored separately and would
    otherwise disappear from the reported cost after a later resume succeeds.
    Calls whose provider response omitted usable usage remain explicitly
    unknown; they are counted as calls, never silently converted into zero-cost
    requests.
    """

    totals = {
        "failure_attempts": 0,
        "model_calls": 0,
        "usage_available_calls": 0,
        "usage_unavailable_calls": 0,
        "prompt_tokens_known": 0,
        "completion_tokens_known": 0,
        "total_tokens_known": 0,
        "provider_failure_events": 0,
    }
    artifacts: list[dict[str, Any]] = []
    for question in questions:
        directory = (
            run_root / "failures" / FULL_CONTEXT_CONDITION_ID / question.question_id
        )
        if not directory.exists():
            continue
        if directory.is_symlink() or not directory.is_dir():
            raise EvidenceValidationError("Unsafe Full Context failure directory")
        for path in sorted(directory.iterdir()):
            match = re.fullmatch(r"attempt-([0-9]{4,})\.json", path.name)
            if path.is_symlink() or not path.is_file() or match is None:
                raise EvidenceValidationError("Malformed Full Context failure artifact")
            value = _read_json(path)
            identity = value.get("failure_id")
            body = {key: row for key, row in value.items() if key != "failure_id"}
            attempt = int(match.group(1))
            if (
                identity
                != "full-context-failure-" + sha256_bytes(canonical_json_bytes(body))
                or value.get("schema_version") != 1
                or value.get("protocol_version") != FULL_CONTEXT_FAILURE_PROTOCOL_VERSION
                or value.get("status") != "failed"
                or value.get("run_id") != manifest["run_id"]
                or value.get("plan_id") != manifest["plan_id"]
                or value.get("condition_id") != FULL_CONTEXT_CONDITION_ID
                or value.get("question_id") != question.question_id
                or value.get("question_sha256") != question.sha256
                or value.get("attempt") != attempt
            ):
                raise EvidenceValidationError("Full Context failure artifact differs")
            usage = value.get("attempt_usage")
            expected_usage_keys = {
                "model_calls",
                "usage_available_calls",
                "usage_unavailable_calls",
                "prompt_tokens",
                "completion_tokens",
                "total_tokens",
            }
            if not isinstance(usage, Mapping) or set(usage) != expected_usage_keys:
                raise EvidenceValidationError("Full Context failure usage differs")
            if any(
                isinstance(usage[key], bool)
                or not isinstance(usage[key], int)
                or usage[key] < 0
                for key in expected_usage_keys
            ):
                raise EvidenceValidationError("Full Context failure usage is invalid")
            if (
                usage["usage_available_calls"] + usage["usage_unavailable_calls"]
                != usage["model_calls"]
                or usage["prompt_tokens"] + usage["completion_tokens"]
                != usage["total_tokens"]
            ):
                raise EvidenceValidationError("Full Context failure usage is inconsistent")
            provider_failures = value.get("provider_failures")
            if not isinstance(provider_failures, list) or any(
                not isinstance(row, Mapping) for row in provider_failures
            ):
                raise EvidenceValidationError("Full Context provider failures differ")
            totals["failure_attempts"] += 1
            totals["model_calls"] += usage["model_calls"]
            totals["usage_available_calls"] += usage["usage_available_calls"]
            totals["usage_unavailable_calls"] += usage["usage_unavailable_calls"]
            totals["prompt_tokens_known"] += usage["prompt_tokens"]
            totals["completion_tokens_known"] += usage["completion_tokens"]
            totals["total_tokens_known"] += usage["total_tokens"]
            totals["provider_failure_events"] += len(provider_failures)
            artifacts.append(
                {
                    "failure_id": identity,
                    "question_id": question.question_id,
                    "attempt": attempt,
                }
            )
    return {
        **totals,
        "known_token_totals_exclude_usage_unavailable_calls": True,
        "artifacts": artifacts,
    }


def evaluate_full_context_run(
    *, repo_root: Path, output_root: Path, run_id: str,
) -> dict[str, Any]:
    root = Path(repo_root).resolve()
    run_root, manifest, questions = _open_run(
        repo_root=root, output_root=output_root, run_id=run_id
    )
    audit = verify_full_context_run(repo_root=root, output_root=output_root, run_id=run_id)
    if audit["status"] != "passed":  # pragma: no cover
        raise EvidenceValidationError("Full Context pre-gold gate did not pass")
    question_set = manifest["question_set"]["name"]
    gold = _load_full_context_gold(root, question_set)
    gold_by_id = {row.question_id: row for row in gold}
    if set(gold_by_id) != {question.question_id for question in questions}:
        raise EvidenceValidationError("Full Context plan and gold membership differ")
    rows: list[dict[str, Any]] = []
    for question in questions:
        record = _load_record(_record_path(run_root, question.question_id))
        reference: GoldRecord = gold_by_id[question.question_id]
        precision, recall = _token_precision_recall(record.answer_result.answer, reference.answer)
        valid_citations = sum(
            citation in {item.evidence_id for item in record.evidence_bundle.evidence_items}
            for citation in record.answer_result.citations
        )
        citation_count = len(record.answer_result.citations)
        rows.append(
            {
                "question_id": question.question_id,
                "category": reference.category,
                "category_name": reference.category_name,
                "token_precision_diagnostic": precision,
                "token_recall_diagnostic": recall,
                "locomo_f1": locomo_category_f1(
                    record.answer_result.answer, reference.answer, reference.category
                ),
                "citation_count": citation_count,
                "citation_validity": valid_citations / citation_count if citation_count else 1.0,
                "source_coverage": 1.0,
                "source_coverage_note": "100% by construction; not retrieval recall",
                "retrieval_metrics": None,
                "answer_prompt_tokens": record.deployment_metrics["prompt_tokens"],
                "answer_completion_tokens": record.deployment_metrics["completion_tokens"],
                "answer_total_tokens": record.deployment_metrics["total_tokens"],
                "answer_provider_request_attempts": record.deployment_metrics[
                    "provider_request_attempts"
                ],
                "answer_model_calls": record.deployment_metrics["model_calls"],
                "answer_format_repairs": record.answer_result.format_repairs,
                "elapsed_ms": record.deployment_metrics["elapsed_ms"],
                "record_id": record.record_id,
            }
        )

    def mean(values: Sequence[float]) -> float | None:
        return sum(values) / len(values) if values else None

    categories: dict[str, Any] = {}
    for category in (1, 2, 3, 4):
        members = [row for row in rows if row["category"] == category]
        categories[str(category)] = {
            "count": len(members),
            "token_precision_diagnostic": mean([row["token_precision_diagnostic"] for row in members]),
            "token_recall_diagnostic": mean([row["token_recall_diagnostic"] for row in members]),
            "locomo_f1": mean([row["locomo_f1"] for row in members]),
        }
    category_values = [
        categories[str(category)]["locomo_f1"]
        for category in (1, 2, 3, 4)
        if categories[str(category)]["locomo_f1"] is not None
    ]
    post_stratified_f1 = None
    if all(categories[str(category)]["locomo_f1"] is not None for category in (1, 2, 3, 4)):
        denominator = sum(RELIABLE_POOL_CATEGORY_COUNTS.values())
        post_stratified_f1 = sum(
            float(categories[str(category)]["locomo_f1"])
            * RELIABLE_POOL_CATEGORY_COUNTS[category]
            for category in (1, 2, 3, 4)
        ) / denominator
    prompt_tokens = [int(row["answer_prompt_tokens"]) for row in rows]
    completion_tokens = [int(row["answer_completion_tokens"]) for row in rows]
    total_tokens = [int(row["answer_total_tokens"]) for row in rows]
    attempts = [int(row["answer_provider_request_attempts"]) for row in rows]
    model_calls = [int(row["answer_model_calls"]) for row in rows]
    format_repairs = [int(row["answer_format_repairs"]) for row in rows]
    failure_overhead = _failure_overhead(
        run_root=run_root, manifest=manifest, questions=questions
    )
    successful_prompt_tokens = sum(prompt_tokens)
    successful_completion_tokens = sum(completion_tokens)
    successful_total_tokens = sum(total_tokens)
    successful_model_calls = sum(model_calls)
    summary = {
        "condition_id": FULL_CONTEXT_CONDITION_ID,
        "count": len(rows),
        "micro_f1": mean([row["locomo_f1"] for row in rows]),
        "category_f1": {
            str(category): categories[str(category)]["locomo_f1"]
            for category in (1, 2, 3, 4)
        },
        "category_macro_f1": mean(category_values),
        "post_stratified_f1": post_stratified_f1,
        "token_precision_diagnostic_macro": mean(
            [row["token_precision_diagnostic"] for row in rows]
        ),
        "token_recall_diagnostic_macro": mean(
            [row["token_recall_diagnostic"] for row in rows]
        ),
        "citation_validity": mean([row["citation_validity"] for row in rows]),
        "source_coverage": 1.0,
        "source_coverage_note": "100% by construction; retrieval metrics are N/A",
        "retrieval_metrics": None,
        "retrieval_tokens": 0,
        "retrieval_model_calls": 0,
        "answer_costs": {
            "prompt_tokens_total": successful_prompt_tokens,
            "prompt_tokens_mean": mean(prompt_tokens),
            "completion_tokens_total": successful_completion_tokens,
            "completion_tokens_mean": mean(completion_tokens),
            "total_tokens": successful_total_tokens,
            "total_tokens_mean": mean(total_tokens),
            "provider_request_attempts_total": sum(attempts),
            "model_calls_total": successful_model_calls,
            "format_repairs_total": sum(format_repairs),
            "elapsed_ms_total": sum(int(row["elapsed_ms"]) for row in rows),
            "elapsed_ms_mean": mean([float(row["elapsed_ms"]) for row in rows]),
        },
        "failed_attempt_overhead": failure_overhead,
        "all_attempts_observed_costs": {
            "model_calls_total": (
                successful_model_calls + failure_overhead["model_calls"]
            ),
            "usage_unavailable_calls": failure_overhead[
                "usage_unavailable_calls"
            ],
            "prompt_tokens_known_total": (
                successful_prompt_tokens
                + failure_overhead["prompt_tokens_known"]
            ),
            "completion_tokens_known_total": (
                successful_completion_tokens
                + failure_overhead["completion_tokens_known"]
            ),
            "total_tokens_known": (
                successful_total_tokens + failure_overhead["total_tokens_known"]
            ),
            "known_token_totals_exclude_usage_unavailable_calls": True,
        },
        "judge": None,
        "judge_note": "No LLM-as-Judge call is part of this deterministic evaluation",
    }
    body = {
        "schema_version": 1,
        "protocol_version": FULL_CONTEXT_EVALUATION_PROTOCOL_VERSION,
        "run_id": run_id,
        "condition_id": FULL_CONTEXT_CONDITION_ID,
        "count": len(rows),
        "summary": summary,
        "micro": {
            "token_precision_diagnostic_macro": mean(
                [row["token_precision_diagnostic"] for row in rows]
            ),
            "token_recall_diagnostic_macro": mean(
                [row["token_recall_diagnostic"] for row in rows]
            ),
            "locomo_f1": mean([row["locomo_f1"] for row in rows]),
            "citation_validity": mean([row["citation_validity"] for row in rows]),
            "mean_answer_total_tokens": mean([float(row["answer_total_tokens"]) for row in rows]),
            "total_answer_tokens": sum(row["answer_total_tokens"] for row in rows),
            "mean_elapsed_ms": mean([float(row["elapsed_ms"]) for row in rows]),
        },
        "by_category": categories,
        "metric_note": (
            "locomo_f1 is the pinned official category-specific metric; precision/recall "
            "are whole-answer diagnostic token-overlap means and category-1 is not their harmonic mean"
        ),
        "official_evaluator": {
            "repository": LOCOMO_EVALUATOR_REPOSITORY,
            "commit": LOCOMO_EVALUATOR_COMMIT,
            "path": LOCOMO_EVALUATOR_PATH,
            "sha256": LOCOMO_EVALUATOR_SHA256,
            "nltk_version": LOCOMO_NLTK_VERSION,
        },
        "rows": rows,
    }
    report = {
        "evaluation_id": "full-context-eval-" + sha256_bytes(canonical_json_bytes(body)),
        **body,
    }
    _publish_idempotent(run_root / "evaluation.json", report)
    return report
