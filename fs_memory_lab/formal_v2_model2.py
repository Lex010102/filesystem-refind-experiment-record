"""Independent Model 2 suite planning, execution, and pre-gold audit control.

This module never constructs a network provider and never reads an API key;
callers must inject a provider.  It prepares and executes two append-only child
runs (main-40 and extension-20), binds them to one Model 2 deployment contract,
and exposes checkpoint/resume, batch, and pre-gold gates.

The old Qwen formal runners and their artifacts are deliberately not imported as
execution engines.  Only their reviewed algorithm/data manifest is used as
parent provenance; Model 2 receives a new deployment-contract hash and new run
plans.
"""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import re
import shutil
import tempfile
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

from .agent import ChatProvider, TransientProviderError
from .answerer import SharedAnswerer
from .evidence import (
    EvidenceBundle,
    EvidenceValidationError,
    QuestionInput,
    canonical_json_bytes,
    sha256_bytes,
)
from .formal_v1 import FORMAL_MANIFEST_RELATIVE_PATH, verify_formal_manifest
from .formal_v2_extension import (
    COMPOSITION_RELATIVE_PATH,
    COMPOSITION_SHA256,
    QUESTION_INPUT_SHA256 as EXTENSION_INPUT_SHA256,
    QUESTION_MANIFEST_SHA256 as EXTENSION_MANIFEST_SHA256,
    QUESTION_SET_ID as EXTENSION_QUESTION_SET_ID,
    QUESTION_VERIFICATION_SHA256 as EXTENSION_VERIFICATION_SHA256,
    _execution_order as extension_execution_order,
    _load_extension_questions,
)
from .fusion import FusionEvidenceBundle, build_e7_fusion_bundle
from .model2_preflight import verify_sanitized_preflight_artifact
from .r1_artifacts import verify_r1_episode_artifact, verify_r1_failure_artifact
from .r1_inputs import load_question_inputs, load_r1_store
from .r1_runner import execute_r1_question
from .r2_artifacts import verify_r2_episode_artifact, verify_r2_failure_artifact
from .r2_inputs import build_r2_raw_corpus
from .r2_runner import execute_r2_question
from .r3_artifacts import verify_r3_episode_artifact, verify_r3_failure_artifact
from .r3_inputs import load_r3_corpus
from .r3_runner import execute_r3_question
from .run_records import (
    CONDITION_IDS,
    RUN_CHECKPOINT_PROTOCOL_VERSION,
    RUN_PLAN_PROTOCOL_VERSION,
    ExperimentRunPlan,
    ExperimentRunStore,
    RunKey,
    RunRecord,
    build_run_plan,
    verify_run_store,
)


MODEL2_SUITE_PROTOCOL_VERSION = "formal-v2-model2-main60-suite-v1"
MODEL2_DEPLOYMENT_PROTOCOL_VERSION = "formal-v2-model2-deployment-v1"
MODEL2_DRY_RUN_PROTOCOL_VERSION = "formal-v2-model2-validation-v1"
MODEL2_REQUESTED_MODEL_ALIAS = "x-test-2"
MODEL2_REQUIRED_SERVED_MODEL = "deepseek-v4.1-flash"
MODEL2_API_STYLE = "portable"
MODEL2_API_BASE_URL = "https://soclaas-api.comp.nus.edu.sg/v1"
MODEL2_CHAT_ENDPOINT = MODEL2_API_BASE_URL + "/chat/completions"
MODEL2_CONTEXT_LIMIT = 1_048_576
MODEL2_REQUEST_TIMEOUT_SECONDS = 300
MODEL2_MAX_RESPONSE_BYTES = 20_000_000
MODEL2_CONCURRENCY = 1
MODEL2_EVIDENCE_BUDGET_UNIT = "characters"
MODEL2_EVIDENCE_BUDGET_LIMIT = 16_000
MODEL2_GLOBAL_BATCHES = 12
MODEL2_BATCH_RECORDS = 35
MODEL2_PLANNED_RECORDS = 420
MODEL2_QUESTION_COUNT = 60
MODEL2_OUTER_SAME_CONFIG_ATTEMPT_LIMIT = 8
MODEL2_RETRYABLE_FAILURE_STAGES = frozenset(
    {"provider_response", "compaction_response", "answer_schema"}
)

SUITE_MANIFEST_NAME = "suite-manifest.json"
SUITE_STATUS_NAME = "status.json"
SUITE_PRE_GOLD_AUDIT_NAME = "formal-pre-gold-verify.json"
SUITE_PRE_GOLD_MARKER_NAME = "formal-pre-gold-verify.PASSED"
SUITE_DRY_RUN_NAME = "dry-run.json"
SUITE_IDENTITY_DRIFT_NAME = "MODEL-IDENTITY-DRIFT.json"
SUITE_MODELS_CHECK_RELATIVE_PATH = "preflight/models-check.json"
SUITE_ROLE_SMOKE_RELATIVE_PATH = "preflight/role-smoke.json"
CHILD_STATUS_NAME = "status.json"
CHILD_FAILURE_METADATA_DIR = "model2-failure-metadata"
RUNNER_RELATIVE_PATH = "fs_memory_lab/formal_v2_model2.py"
CLI_RELATIVE_PATH = "fs_memory_lab/formal_v2_model2_cli.py"

MAIN_CHILD_ID = "main40"
EXTENSION_CHILD_ID = "extension20"
MAIN_QUESTION_SET_ID = "locomo-conv50-main40-v1"

CONDITION_METHODS: Mapping[str, tuple[str, str]] = {
    "E1": ("r1", "s1"),
    "E2": ("r2", "s1"),
    "E3": ("r1", "s2"),
    "E4": ("r2", "s2"),
    "E5": ("r1", "s3"),
    "E6": ("r3", "s3"),
}

MODEL2_DRY_RUN_REQUIRED_CHECKS = frozenset(
    {
        "questions_60_unique",
        "main40_extension20_split_exact",
        "run_plan_420_unique_keys",
        "conditions_60_each",
        "twelve_batches_of_35",
        "suite_batches_map_to_8_plus_4_child_batches",
        "condition_offset_order_exact",
        "e7_after_e2_e6_for_every_question",
        "e7_no_retrieval_contract",
        "evidence_budget_16000_characters",
        "whole_item_budget_schema_enforced",
        "r1_round_caps_frozen",
        "r2_r3_action_caps_frozen",
        "expected_model_identity_bound",
        "checkpoint_resume_without_duplicates",
        "api_provider_not_constructed",
        "semantic_gold_not_loaded",
        "judge_not_constructed",
        "formal_answers_not_generated",
        "suite_manifest_content_address_verified",
        "preflight_role_smokes_verified",
        "suite_schedule_matches_global_420_order",
        "suite_batch_map_matches_twelve_blocks",
        "child_plans_are_physically_split_280_plus_140",
        "empty_child_checkpoints_exact",
        "checkpoint_pending_order_exact",
        "manifest_budget_caps_and_e7_exact",
        "answer_run_boundaries_exact",
        "separate_child_roots",
    }
)

_SAFE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}\Z")
_SHA = re.compile(r"[0-9a-f]{64}\Z")
_COMMIT = re.compile(r"[0-9a-f]{40}\Z")


class ModelIdentityError(EvidenceValidationError):
    """A response used a deployment other than the suite's frozen Model 2."""

    stage = "model_identity"


class Model2RecordError(EvidenceValidationError):
    """Safe record-level failure retaining the frozen recovery stage."""

    def __init__(self, message: str, *, stage: str, retryable: bool) -> None:
        super().__init__(message)
        self.stage = stage
        self.retryable = retryable


class ModelIdentityProvider:
    """Fail-closed decorator that checks requested and served model every call.

    The decorator sits immediately around the wire provider, so ordinary R1
    turns, R1 compaction/corrections, R2/R3 actions, Answerer calls, and Answerer
    repair calls are all checked before their response reaches protocol code.
    """

    def __init__(
        self,
        provider: ChatProvider,
        *,
        requested_model_alias: str,
        required_served_model: str,
    ) -> None:
        self.provider = provider
        self.model = _require_model_name(requested_model_alias, "requested model alias")
        self.required_served_model = _require_model_name(
            required_served_model, "required served model"
        )
        underlying = getattr(provider, "model", None)
        if underlying is not None and underlying != self.model:
            raise ModelIdentityError("Provider requested model differs from frozen alias")
        self._wire_model_override = underlying
        self.endpoint = getattr(provider, "endpoint", None)
        self.api_style = getattr(provider, "api_style", None)
        self.timeout = getattr(provider, "timeout", None)
        self.max_response_bytes = getattr(provider, "max_response_bytes", None)
        if self.endpoint != MODEL2_CHAT_ENDPOINT:
            raise ModelIdentityError("Provider endpoint differs from Model 2 contract")
        if self.api_style != MODEL2_API_STYLE:
            raise ModelIdentityError("Provider API style differs from Model 2 contract")
        if self.timeout != MODEL2_REQUEST_TIMEOUT_SECONDS:
            raise ModelIdentityError("Provider timeout differs from Model 2 contract")
        if self.max_response_bytes != MODEL2_MAX_RESPONSE_BYTES:
            raise ModelIdentityError("Provider response cap differs from Model 2 contract")
        self.calls_checked = 0
        self.identity_error: ModelIdentityError | None = None
        self.observed_served_model: str | None = None
        self._usage_receipts: list[dict[str, Any]] = []
        self._provider_failures: list[dict[str, Any]] = []

    @property
    def api_key(self) -> Any:
        """Expose only for existing error redaction; never serialize the value."""
        return getattr(self.provider, "api_key", None)

    def complete(self, messages: list[dict], tools: list[dict], config: Any) -> dict:
        # CompatibleChatProvider uses its explicit ``model`` as the effective
        # wire model and otherwise falls back to RoleConfig.model.  R1's frozen
        # RoleConfig deliberately retains its paper label, so compare the same
        # effective value the adapter will actually send.
        self.observed_served_model = None
        if self._wire_model_override is None and getattr(config, "model", None) != self.model:
            self.identity_error = ModelIdentityError(
                "Request config model differs from frozen alias"
            )
            raise self.identity_error
        receipt_index = len(self._usage_receipts)
        # Count the provider invocation before crossing the boundary.  If the
        # call raises or returns no usable usage object, its token cost is
        # explicitly unknown rather than silently treated as zero calls.
        self._usage_receipts.append(
            {
                "call_index": receipt_index + 1,
                "usage_available": False,
                "prompt_tokens": 0,
                "completion_tokens": 0,
                "total_tokens": 0,
            }
        )
        try:
            response = self.provider.complete(messages, tools, config)
        except ModelIdentityError:
            raise
        except TransientProviderError as error:
            # Sanitize at the provider boundary.  R1/R2/R3 and Answerer preserve
            # exception text in their immutable failure artifacts, so outer
            # RunFailureRecord redaction would be too late.
            self._provider_failures.append(
                {
                    "call_index": receipt_index + 1,
                    "error_class": "transient",
                    "kind": error.kind,
                    "http_status": error.http_status,
                }
            )
            raise TransientProviderError(
                _safe_error(error, self),
                kind=error.kind,
                http_status=error.http_status,
            ) from None
        except Exception as error:
            self._provider_failures.append(
                {
                    "call_index": receipt_index + 1,
                    "error_class": "generic",
                    "kind": None,
                    "http_status": None,
                }
            )
            raise RuntimeError(_safe_error(error, self)) from None
        if not isinstance(response, dict):
            self.observed_served_model = None
            self.identity_error = ModelIdentityError("Provider response is not an object")
            raise self.identity_error
        usage = response.get("usage")
        available = (
            isinstance(usage, Mapping)
            and all(
                isinstance(usage.get(name), int)
                and not isinstance(usage.get(name), bool)
                and usage.get(name) >= 0
                for name in ("prompt_tokens", "completion_tokens", "total_tokens")
            )
            and usage.get("total_tokens")
            == usage.get("prompt_tokens") + usage.get("completion_tokens")
        )
        self._usage_receipts[receipt_index] = {
            "call_index": receipt_index + 1,
            "usage_available": available,
            "prompt_tokens": int(usage["prompt_tokens"]) if available else 0,
            "completion_tokens": (
                int(usage["completion_tokens"]) if available else 0
            ),
            "total_tokens": int(usage["total_tokens"]) if available else 0,
        }
        served = response.get("served_model")
        if not isinstance(served, str) or not served.strip():
            self.observed_served_model = None
            self.identity_error = ModelIdentityError(
                "Provider response omitted served_model"
            )
            raise self.identity_error
        self.observed_served_model = (
            served.strip()
            if len(served.strip()) <= 256
            and not any(ord(character) < 32 for character in served)
            else None
        )
        if served != self.required_served_model:
            self.identity_error = ModelIdentityError("Provider served model drifted")
            raise self.identity_error
        self.calls_checked += 1
        return response

    def usage_cursor(self) -> int:
        return len(self._usage_receipts)

    def provider_failure_cursor(self) -> int:
        return len(self._provider_failures)

    def provider_failures_since(self, cursor: int) -> tuple[Mapping[str, Any], ...]:
        if (
            isinstance(cursor, bool)
            or not isinstance(cursor, int)
            or not 0 <= cursor <= len(self._provider_failures)
        ):
            raise EvidenceValidationError("Model 2 provider failure cursor is invalid")
        return tuple(dict(row) for row in self._provider_failures[cursor:])

    def usage_since(self, cursor: int) -> dict[str, int]:
        if (
            isinstance(cursor, bool)
            or not isinstance(cursor, int)
            or not 0 <= cursor <= len(self._usage_receipts)
        ):
            raise EvidenceValidationError("Model 2 usage cursor is invalid")
        receipts = self._usage_receipts[cursor:]
        available = sum(row["usage_available"] is True for row in receipts)
        return {
            "model_calls": len(receipts),
            "usage_available_calls": available,
            "usage_unavailable_calls": len(receipts) - available,
            "prompt_tokens": sum(row["prompt_tokens"] for row in receipts),
            "completion_tokens": sum(row["completion_tokens"] for row in receipts),
            "total_tokens": sum(row["total_tokens"] for row in receipts),
        }

    def raise_if_identity_error(self) -> None:
        """Re-raise drift even when an underlying agent wrapped the provider error."""
        if self.identity_error is not None:
            raise self.identity_error


@dataclass(frozen=True)
class OpenModel2Suite:
    repo_root: Path
    suite_root: Path
    manifest: Mapping[str, Any]
    main_store: ExperimentRunStore
    extension_store: ExperimentRunStore


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _require_model_name(value: Any, label: str) -> str:
    if (
        not isinstance(value, str)
        or not value.strip()
        or len(value) > 256
        or any(ord(character) < 32 for character in value)
    ):
        raise EvidenceValidationError(f"Model 2 {label} is invalid")
    return value.strip()


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _read_json(path: Path) -> dict[str, Any]:
    lexical = Path(path)
    if lexical.is_symlink() or not lexical.is_file():
        raise EvidenceValidationError(f"Unsafe or missing JSON artifact: {lexical}")
    try:
        value = json.loads(lexical.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise EvidenceValidationError(f"Unreadable JSON artifact: {lexical}") from exc
    if not isinstance(value, dict):
        raise EvidenceValidationError("Model 2 artifact must contain an object")
    return value


def _write_exclusive(path: Path, payload: bytes, mode: int = 0o644) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(path, flags, mode)
    try:
        offset = 0
        while offset < len(payload):
            written = os.write(descriptor, payload[offset:])
            if written <= 0:
                raise OSError("short Model 2 artifact write")
            offset += written
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _publish_json(path: Path, value: Mapping[str, Any]) -> None:
    payload = canonical_json_bytes(value) + b"\n"
    if path.exists() or path.is_symlink():
        if _read_json(path) != dict(value):
            raise EvidenceValidationError(f"Existing Model 2 artifact differs: {path.name}")
        return
    _write_exclusive(path, payload)


def _write_atomic_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(canonical_json_bytes(value) + b"\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def _append_event(path: Path, value: Mapping[str, Any]) -> None:
    payload = canonical_json_bytes(value) + b"\n"
    flags = os.O_WRONLY | os.O_CREAT | os.O_APPEND
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(path, flags, 0o644)
    try:
        os.write(descriptor, payload)
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _deployment_contract(
    *, requested_model_alias: str, required_served_model: str,
    models_check_report_sha256: str, role_smoke_report_sha256: str,
) -> dict[str, Any]:
    alias = _require_model_name(requested_model_alias, "requested model alias")
    served = _require_model_name(required_served_model, "required served model")
    if (
        _SHA.fullmatch(models_check_report_sha256) is None
        or _SHA.fullmatch(role_smoke_report_sha256) is None
    ):
        raise EvidenceValidationError("Preflight report hashes must be SHA-256 digests")
    body = {
        "schema_version": 1,
        "protocol_version": MODEL2_DEPLOYMENT_PROTOCOL_VERSION,
        "requested_model_alias": alias,
        "required_served_model": served,
        "models_check_report_sha256": models_check_report_sha256,
        # Retain the original field name for the role-smoke dry-run protocol.
        "preflight_report_sha256": role_smoke_report_sha256,
        "api_base_url": MODEL2_API_BASE_URL,
        "chat_endpoint": MODEL2_CHAT_ENDPOINT,
        "api_style": MODEL2_API_STYLE,
        "context_limit_tokens": MODEL2_CONTEXT_LIMIT,
        "request_timeout_seconds": MODEL2_REQUEST_TIMEOUT_SECONDS,
        "max_response_bytes": MODEL2_MAX_RESPONSE_BYTES,
        "concurrency": MODEL2_CONCURRENCY,
        "identity_policy": (
            "every response including compaction, correction, and repair must report "
            "the exact required_served_model"
        ),
        "runtime_model_override": "forbidden",
    }
    return {
        "deployment_contract_sha256": sha256_bytes(canonical_json_bytes(body)),
        **body,
    }


def _verify_preflight_pair(
    *,
    models_check_report_path: Path,
    role_smoke_report_path: Path,
    requested_model_alias: str,
    required_served_model: str,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    models_path = Path(models_check_report_path).resolve()
    role_path = Path(role_smoke_report_path).resolve()
    models = verify_sanitized_preflight_artifact(models_path)
    role = verify_sanitized_preflight_artifact(role_path)
    models_value = _read_json(models_path)
    role_value = _read_json(role_path)
    if (
        models.get("artifact_type") != "model2-models-check"
        or models.get("verified") is not True
        or models.get("requested_alias") != requested_model_alias
        or models.get("alias_present") is not True
        or models.get("context_limit") != MODEL2_CONTEXT_LIMIT
    ):
        raise EvidenceValidationError("Model 2 models-check contract differs")
    if (
        role.get("artifact_type") != "model2-role-smoke"
        or role.get("verified") is not True
        or role.get("requested_alias") != requested_model_alias
        or role.get("served_model") != required_served_model
        or role.get("role_smokes_passed") != 5
        or role.get("components")
        != ["r1", "r1_compaction", "r2", "r3", "answerer"]
    ):
        raise EvidenceValidationError("Model 2 role-smoke contract differs")
    artifacts = {
        "models_check": {
            "relative_path": SUITE_MODELS_CHECK_RELATIVE_PATH,
            "sha256": sha256_bytes(canonical_json_bytes(models_value) + b"\n"),
            "summary": models,
        },
        "role_smoke": {
            "relative_path": SUITE_ROLE_SMOKE_RELATIVE_PATH,
            "sha256": sha256_bytes(canonical_json_bytes(role_value) + b"\n"),
            "summary": role,
        },
    }
    return artifacts, models_value, role_value


def _publish_preflight_copy(path: Path, value: Mapping[str, Any]) -> None:
    """Copy only a verifier-approved sanitized artifact into the suite."""
    _publish_json(path, value)


def _verify_parent_algorithm_contract(formal: Mapping[str, Any]) -> None:
    budget = formal.get("retrieval", {}).get("evidence_budget", {})
    if (
        budget.get("unit") != MODEL2_EVIDENCE_BUDGET_UNIT
        or budget.get("single_source_limit") != MODEL2_EVIDENCE_BUDGET_LIMIT
        or budget.get("e7_per_source_limit") != MODEL2_EVIDENCE_BUDGET_LIMIT
        or budget.get("e7_total_limit") != 2 * MODEL2_EVIDENCE_BUDGET_LIMIT
    ):
        raise EvidenceValidationError("Parent evidence-budget contract differs")
    if formal.get("retrieval", {}).get("r1", {}).get("round_cap_by_condition") != {
        "E1": 20,
        "E3": 20,
        "E5": 40,
    }:
        raise EvidenceValidationError("Parent R1 round caps differ")
    if formal.get("retrieval", {}).get("r2", {}).get("action_cap") != 4:
        raise EvidenceValidationError("Parent R2 action cap differs")
    if formal.get("retrieval", {}).get("r3", {}).get("action_cap") != 4:
        raise EvidenceValidationError("Parent R3 action cap differs")


def _child_plans(
    repo_root: Path, suite_id: str, deployment_contract_sha256: str
) -> tuple[ExperimentRunPlan, ExperimentRunPlan]:
    formal_path = repo_root / FORMAL_MANIFEST_RELATIVE_PATH
    formal = _read_json(formal_path)
    _verify_parent_algorithm_contract(formal)
    main_questions = load_question_inputs(repo_root, "main-40")
    extension_questions = _load_extension_questions(repo_root)
    common = {
        "parent_algorithm_manifest": _file_sha256(formal_path),
        "parent_algorithm_core": formal["core_files_tree_sha256"],
        "model2_deployment_contract": deployment_contract_sha256,
        "answerer_prompt": formal["answerer"]["prompt_sha256"],
        "fusion_contract": formal["e7_fusion"]["contract_sha256"],
        "r1_limits": formal["retrieval"]["r1"]["limits_sha256"],
        # These are explicitly parent algorithm provenance, not deployment identity.
        "parent_r2_protocol": formal["retrieval"]["r2"]["protocol_sha256"],
        "parent_r3_protocol": formal["retrieval"]["r3"]["protocol_sha256"],
        "s1_tree": formal["stores"]["s1"]["tree_sha256"],
        "s2_tree": formal["stores"]["s2"]["tree_sha256"],
        "s3_tree": formal["stores"]["s3"]["tree_sha256"],
    }
    main_plan = build_run_plan(
        run_id=f"{suite_id}-main40",
        question_set_id=MAIN_QUESTION_SET_ID,
        question_ids=tuple(item.question_id for item in main_questions),
        condition_ids=CONDITION_IDS,
        config_hashes={**common, "question_inputs": formal["question_set"]["input_sha256"]},
    )
    extension_ids = tuple(item.question_id for item in extension_questions)
    extension_plan = ExperimentRunPlan.create(
        schema_version=1,
        protocol_version=RUN_PLAN_PROTOCOL_VERSION,
        run_id=f"{suite_id}-extension20",
        question_set_id=EXTENSION_QUESTION_SET_ID,
        question_ids=extension_ids,
        condition_ids=CONDITION_IDS,
        execution_order=extension_execution_order(extension_ids),
        config_hashes={
            **common,
            "extension_inputs": EXTENSION_INPUT_SHA256,
            "extension_manifest": EXTENSION_MANIFEST_SHA256,
            "extension_verification": EXTENSION_VERIFICATION_SHA256,
            "main60_composition": COMPOSITION_SHA256,
        },
    )
    if len(main_plan.execution_order) != 280 or len(extension_plan.execution_order) != 140:
        raise EvidenceValidationError("Model 2 child plan sizes differ")
    return main_plan, extension_plan


def _batch_map(
    main_plan: ExperimentRunPlan, extension_plan: ExperimentRunPlan
) -> list[dict[str, Any]]:
    batches: list[dict[str, Any]] = []
    for global_batch in range(1, MODEL2_GLOBAL_BATCHES + 1):
        child = MAIN_CHILD_ID if global_batch <= 8 else EXTENSION_CHILD_ID
        local_batch = global_batch if child == MAIN_CHILD_ID else global_batch - 8
        plan = main_plan if child == MAIN_CHILD_ID else extension_plan
        question_start = (local_batch - 1) * 5
        question_ids = list(plan.question_ids[question_start : question_start + 5])
        batches.append(
            {
                "batch_id": f"B{global_batch:02d}",
                "global_batch": global_batch,
                "child_id": child,
                "child_local_batch": local_batch,
                "question_ids": question_ids,
                "record_count": MODEL2_BATCH_RECORDS,
                "global_record_range": [
                    (global_batch - 1) * MODEL2_BATCH_RECORDS + 1,
                    global_batch * MODEL2_BATCH_RECORDS,
                ],
                "child_target_records": local_batch * MODEL2_BATCH_RECORDS,
                "suite_target_records": global_batch * MODEL2_BATCH_RECORDS,
            }
        )
    return batches


def _global_schedule(
    main_plan: ExperimentRunPlan, extension_plan: ExperimentRunPlan
) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for child_id, plan in ((MAIN_CHILD_ID, main_plan), (EXTENSION_CHILD_ID, extension_plan)):
        for local_sequence, key in enumerate(plan.execution_order, start=1):
            global_sequence = len(output) + 1
            output.append(
                {
                    "global_sequence": global_sequence,
                    "batch_id": f"B{((global_sequence - 1) // MODEL2_BATCH_RECORDS) + 1:02d}",
                    "child_id": child_id,
                    "child_local_sequence": local_sequence,
                    **key.to_dict(),
                }
            )
    if len(output) != MODEL2_PLANNED_RECORDS:
        raise EvidenceValidationError("Model 2 global schedule size differs")
    return output


def _manifest_body(
    *, repo_root: Path, suite_id: str, implementation_commit: str,
    deployment: Mapping[str, Any], main_plan: ExperimentRunPlan,
    extension_plan: ExperimentRunPlan,
    preflight_artifacts: Mapping[str, Any],
) -> dict[str, Any]:
    formal_path = repo_root / FORMAL_MANIFEST_RELATIVE_PATH
    formal = _read_json(formal_path)
    composition = _read_json(repo_root / COMPOSITION_RELATIVE_PATH)
    main_questions = load_question_inputs(repo_root, "main-40")
    extension_questions = _load_extension_questions(repo_root)
    global_ids = [item.get("question_id") for item in composition["question_order"]]
    expected_ids = [item.question_id for item in main_questions] + [
        item.question_id for item in extension_questions
    ]
    if global_ids != expected_ids:
        raise EvidenceValidationError("main-60 composition order differs")
    runner_path = repo_root / RUNNER_RELATIVE_PATH
    cli_path = repo_root / CLI_RELATIVE_PATH
    return {
        "schema_version": 1,
        "protocol_version": MODEL2_SUITE_PROTOCOL_VERSION,
        "status": "prepared",
        "suite_id": suite_id,
        "implementation_git_commit": implementation_commit,
        "runner_relative_path": RUNNER_RELATIVE_PATH,
        "runner_sha256": _file_sha256(runner_path),
        "cli_relative_path": CLI_RELATIVE_PATH,
        "cli_sha256": _file_sha256(cli_path),
        "parent_algorithm_manifest_relative_path": FORMAL_MANIFEST_RELATIVE_PATH,
        "parent_algorithm_manifest_sha256": _file_sha256(formal_path),
        "parent_algorithm_manifest_id": formal["formal_manifest_id"],
        "main60_composition_relative_path": COMPOSITION_RELATIVE_PATH,
        "main60_composition_sha256": COMPOSITION_SHA256,
        "deployment": dict(deployment),
        "preflight_artifacts": dict(preflight_artifacts),
        "experimental_invariants": {
            "question_count": MODEL2_QUESTION_COUNT,
            "condition_ids": list(CONDITION_IDS),
            "planned_records": MODEL2_PLANNED_RECORDS,
            "evidence_budget": {
                "unit": MODEL2_EVIDENCE_BUDGET_UNIT,
                "single_source_limit": MODEL2_EVIDENCE_BUDGET_LIMIT,
                "e7_per_source_limit": MODEL2_EVIDENCE_BUDGET_LIMIT,
                "e7_total_limit": 2 * MODEL2_EVIDENCE_BUDGET_LIMIT,
            },
            "r1_round_cap": {"E1": 20, "E3": 20, "E5": 40},
            "r2_action_cap": 4,
            "r3_action_cap": 4,
            "answerer_prompt_sha256": formal["answerer"]["prompt_sha256"],
            "e7_contract_sha256": formal["e7_fusion"]["contract_sha256"],
            "e7_retrieval": "reuse same-run E2 and E6 bundles; no new search or LLM",
            "semantic_gold_access": "forbidden during answer run",
            "judge_calls": "forbidden during answer run",
            "configuration_overrides": "forbidden",
        },
        "children": {
            MAIN_CHILD_ID: {
                "run_id": main_plan.run_id,
                "plan_id": main_plan.plan_id,
                "output_root_relative": "children/main40",
                "question_set_id": main_plan.question_set_id,
                "question_count": 40,
                "global_question_positions": [1, 40],
                "planned_records": 280,
                "local_batches": 8,
            },
            EXTENSION_CHILD_ID: {
                "run_id": extension_plan.run_id,
                "plan_id": extension_plan.plan_id,
                "output_root_relative": "children/extension20",
                "question_set_id": extension_plan.question_set_id,
                "question_count": 20,
                "global_question_positions": [41, 60],
                "planned_records": 140,
                "local_batches": 4,
            },
        },
        "batch_map": _batch_map(main_plan, extension_plan),
        "global_schedule": _global_schedule(main_plan, extension_plan),
        "execution_control": {
            "global_batches": MODEL2_GLOBAL_BATCHES,
            "records_per_batch": MODEL2_BATCH_RECORDS,
            "single_suite_lock": True,
            "child_run_locks": True,
            "resume_policy": (
                "revalidate immutable suite and child plans; skip only verified completed "
                "records; retry only the current failed key"
            ),
            "outer_same_config_attempt_limit": MODEL2_OUTER_SAME_CONFIG_ATTEMPT_LIMIT,
            "retryable_failure_stages": sorted(MODEL2_RETRYABLE_FAILURE_STAGES),
            "recovery_entrypoint": "formal_v2_model2_cli run-child",
        },
    }


def prepare_suite(
    *, repo_root: Path, output_root: Path, suite_id: str,
    implementation_commit: str,
    requested_model_alias: str = MODEL2_REQUESTED_MODEL_ALIAS,
    required_served_model: str = MODEL2_REQUIRED_SERVED_MODEL,
    models_check_report_path: Path,
    role_smoke_report_path: Path,
) -> Path:
    """Prepare both child stores and the immutable 420-key suite; no API call."""
    if _SAFE.fullmatch(suite_id) is None:
        raise EvidenceValidationError("Model 2 suite_id is unsafe")
    if _COMMIT.fullmatch(implementation_commit) is None:
        raise EvidenceValidationError("Implementation commit must be a full Git SHA")
    root = Path(repo_root).resolve()
    verify_formal_manifest(root)
    if _file_sha256(root / COMPOSITION_RELATIVE_PATH) != COMPOSITION_SHA256:
        raise EvidenceValidationError("main-60 composition hash differs")
    preflight_artifacts, models_value, role_value = _verify_preflight_pair(
        models_check_report_path=models_check_report_path,
        role_smoke_report_path=role_smoke_report_path,
        requested_model_alias=requested_model_alias,
        required_served_model=required_served_model,
    )
    deployment = _deployment_contract(
        requested_model_alias=requested_model_alias,
        required_served_model=required_served_model,
        models_check_report_sha256=preflight_artifacts["models_check"]["sha256"],
        role_smoke_report_sha256=preflight_artifacts["role_smoke"]["sha256"],
    )
    main_plan, extension_plan = _child_plans(
        root, suite_id, deployment["deployment_contract_sha256"]
    )
    base = Path(output_root).resolve()
    base.mkdir(parents=True, exist_ok=True)
    if base.is_symlink() or not base.is_dir():
        raise EvidenceValidationError("Model 2 output root is unsafe")
    suite_root = base / suite_id
    suite_root.mkdir(mode=0o700, exist_ok=True)
    if suite_root.is_symlink() or not suite_root.is_dir():
        raise EvidenceValidationError("Model 2 suite root is unsafe")
    _publish_preflight_copy(
        suite_root / SUITE_MODELS_CHECK_RELATIVE_PATH, models_value
    )
    _publish_preflight_copy(
        suite_root / SUITE_ROLE_SMOKE_RELATIVE_PATH, role_value
    )
    ExperimentRunStore.create_or_open(suite_root / "children/main40", main_plan)
    ExperimentRunStore.create_or_open(suite_root / "children/extension20", extension_plan)
    (suite_root / "control").mkdir(exist_ok=True)
    body = _manifest_body(
        repo_root=root,
        suite_id=suite_id,
        implementation_commit=implementation_commit,
        deployment=deployment,
        main_plan=main_plan,
        extension_plan=extension_plan,
        preflight_artifacts=preflight_artifacts,
    )
    manifest = {
        "suite_manifest_id": "model2-suite-" + sha256_bytes(canonical_json_bytes(body)),
        **body,
    }
    path = suite_root / SUITE_MANIFEST_NAME
    _publish_json(path, manifest)
    _append_event(
        suite_root / "events.jsonl",
        {
            "event": "model2_suite_prepared",
            "at": _now(),
            "suite_manifest_id": manifest["suite_manifest_id"],
        },
    )
    write_suite_status(repo_root=root, output_root=base, suite_id=suite_id)
    return path


def open_suite(
    *, repo_root: Path, output_root: Path, suite_id: str
) -> OpenModel2Suite:
    if _SAFE.fullmatch(suite_id) is None:
        raise EvidenceValidationError("Model 2 suite_id is unsafe")
    root = Path(repo_root).resolve()
    suite_root = Path(output_root).resolve() / suite_id
    manifest = _read_json(suite_root / SUITE_MANIFEST_NAME)
    identity = manifest.get("suite_manifest_id")
    body = {key: value for key, value in manifest.items() if key != "suite_manifest_id"}
    if identity != "model2-suite-" + sha256_bytes(canonical_json_bytes(body)):
        raise EvidenceValidationError("Model 2 suite manifest content hash differs")
    if manifest.get("suite_id") != suite_id:
        raise EvidenceValidationError("Model 2 suite directory identity differs")
    parent_verification = verify_formal_manifest(root)
    if parent_verification.get("formal_manifest_id") != manifest.get(
        "parent_algorithm_manifest_id"
    ):
        raise EvidenceValidationError("Parent algorithm identity drifted")
    if _file_sha256(root / RUNNER_RELATIVE_PATH) != manifest.get("runner_sha256"):
        raise EvidenceValidationError("Model 2 runner drifted")
    if _file_sha256(root / CLI_RELATIVE_PATH) != manifest.get("cli_sha256"):
        raise EvidenceValidationError("Model 2 CLI drifted")
    formal_path = root / FORMAL_MANIFEST_RELATIVE_PATH
    if _file_sha256(formal_path) != manifest.get("parent_algorithm_manifest_sha256"):
        raise EvidenceValidationError("Parent algorithm manifest drifted")
    if _file_sha256(root / COMPOSITION_RELATIVE_PATH) != manifest.get(
        "main60_composition_sha256"
    ):
        raise EvidenceValidationError("Model 2 composition drifted")
    deployment = manifest.get("deployment")
    if not isinstance(deployment, Mapping):
        raise EvidenceValidationError("Model 2 deployment contract is missing")
    contract_body = {
        key: value for key, value in deployment.items()
        if key != "deployment_contract_sha256"
    }
    if deployment.get("deployment_contract_sha256") != sha256_bytes(
        canonical_json_bytes(contract_body)
    ):
        raise EvidenceValidationError("Model 2 deployment contract hash differs")
    bound_preflight, _, _ = _verify_preflight_pair(
        models_check_report_path=suite_root / SUITE_MODELS_CHECK_RELATIVE_PATH,
        role_smoke_report_path=suite_root / SUITE_ROLE_SMOKE_RELATIVE_PATH,
        requested_model_alias=str(deployment["requested_model_alias"]),
        required_served_model=str(deployment["required_served_model"]),
    )
    if (
        manifest.get("preflight_artifacts") != bound_preflight
        or deployment.get("models_check_report_sha256")
        != bound_preflight["models_check"]["sha256"]
        or deployment.get("preflight_report_sha256")
        != bound_preflight["role_smoke"]["sha256"]
    ):
        raise EvidenceValidationError("Model 2 bound preflight artifacts drifted")
    expected_main, expected_extension = _child_plans(
        root, suite_id, str(deployment["deployment_contract_sha256"])
    )
    main_spec = manifest["children"][MAIN_CHILD_ID]
    extension_spec = manifest["children"][EXTENSION_CHILD_ID]
    main_store, _ = verify_run_store(
        suite_root / main_spec["output_root_relative"], main_spec["run_id"]
    )
    extension_store, _ = verify_run_store(
        suite_root / extension_spec["output_root_relative"], extension_spec["run_id"]
    )
    if main_store.plan != expected_main or extension_store.plan != expected_extension:
        raise EvidenceValidationError("Model 2 child plan drifted")
    expected_body = _manifest_body(
        repo_root=root,
        suite_id=suite_id,
        implementation_commit=str(manifest.get("implementation_git_commit", "")),
        deployment=deployment,
        main_plan=main_store.plan,
        extension_plan=extension_store.plan,
        preflight_artifacts=bound_preflight,
    )
    if body != expected_body:
        raise EvidenceValidationError("Model 2 suite manifest drifted")
    return OpenModel2Suite(
        repo_root=root,
        suite_root=suite_root,
        manifest=manifest,
        main_store=main_store,
        extension_store=extension_store,
    )


def _store_for_child(suite: OpenModel2Suite, child_id: str) -> ExperimentRunStore:
    if child_id == MAIN_CHILD_ID:
        return suite.main_store
    if child_id == EXTENSION_CHILD_ID:
        return suite.extension_store
    raise EvidenceValidationError("Unknown Model 2 child ID")


def guard_provider_for_suite(
    suite: OpenModel2Suite, provider: ChatProvider
) -> ModelIdentityProvider:
    """Bind a wire provider to the immutable deployment in ``suite``."""
    deployment = suite.manifest["deployment"]
    if (
        deployment.get("chat_endpoint") != MODEL2_CHAT_ENDPOINT
        or deployment.get("context_limit_tokens") != MODEL2_CONTEXT_LIMIT
    ):
        raise ModelIdentityError("Suite deployment endpoint/context contract differs")
    return ModelIdentityProvider(
        provider,
        requested_model_alias=str(deployment["requested_model_alias"]),
        required_served_model=str(deployment["required_served_model"]),
    )


def _assert_no_identity_drift(suite: OpenModel2Suite) -> None:
    if (suite.suite_root / SUITE_IDENTITY_DRIFT_NAME).exists():
        raise ModelIdentityError(
            "Model 2 suite is permanently halted after a model identity violation"
        )


def _seal_identity_drift(
    *, suite: OpenModel2Suite, key: RunKey, provider: ModelIdentityProvider
) -> None:
    """Make any observed served-model violation terminal for the whole suite."""
    if provider.identity_error is None:
        return
    deployment = suite.manifest["deployment"]
    _publish_json(
        suite.suite_root / SUITE_IDENTITY_DRIFT_NAME,
        {
            "schema_version": 1,
            "protocol_version": MODEL2_SUITE_PROTOCOL_VERSION,
            "status": "halted",
            "suite_id": suite.manifest["suite_id"],
            "suite_manifest_id": suite.manifest["suite_manifest_id"],
            "condition_id": key.condition_id,
            "question_id": key.question_id,
            "requested_model_alias": deployment["requested_model_alias"],
            "required_served_model": deployment["required_served_model"],
            "observed_served_model": provider.observed_served_model,
            "error_type": "ModelIdentityError",
            "reason": "provider response violated the frozen model identity",
            "recovery": "forbidden",
        },
    )


def _require_attempt_budget(store: ExperimentRunStore, key: RunKey) -> None:
    attempts = store.failure_attempts(key)
    if len(attempts) >= MODEL2_OUTER_SAME_CONFIG_ATTEMPT_LIMIT:
        raise EvidenceValidationError(
            "Model 2 current key exhausted the frozen same-config attempt limit"
        )
    if attempts and attempts[-1].retryable is not True:
        raise EvidenceValidationError(
            "Model 2 current key has a non-retryable preserved failure"
        )


def _validate_model2_retrieval_bundle(
    bundle: EvidenceBundle, *, key: RunKey, suite: OpenModel2Suite
) -> None:
    deployment = suite.manifest["deployment"]
    method, store_id = CONDITION_METHODS[key.condition_id]
    expected = {
        "condition_id": key.condition_id,
        "store_id": store_id,
        "retrieval_id": method,
    }
    if bundle.question.question_id != key.question_id or dict(bundle.condition) != expected:
        raise EvidenceValidationError("Model 2 retrieval question/condition differs")
    if bundle.model.get("requested_model") != deployment["requested_model_alias"]:
        raise ModelIdentityError("Model 2 retrieval requested model differs")
    if set(bundle.model.get("served_models", ())) != {
        deployment["required_served_model"]
    }:
        raise ModelIdentityError("Model 2 retrieval served model differs")
    if (
        bundle.budget.unit != MODEL2_EVIDENCE_BUDGET_UNIT
        or bundle.budget.limit != MODEL2_EVIDENCE_BUDGET_LIMIT
    ):
        raise EvidenceValidationError("Model 2 evidence budget differs")
    if bundle.integrity.get("verified") is not True or bundle.integrity.get(
        "store_unchanged"
    ) is not True:
        raise EvidenceValidationError("Model 2 retrieval integrity failed")
    formal = _read_json(suite.repo_root / FORMAL_MANIFEST_RELATIVE_PATH)
    if bundle.store_snapshot.to_dict() != formal["stores"][store_id]:
        raise EvidenceValidationError("Model 2 store snapshot differs")


def _load_suite_dry_run(suite: OpenModel2Suite) -> dict[str, Any]:
    """Require the content-addressed, provider-free suite dry-run gate."""
    report = _read_json(suite.suite_root / SUITE_DRY_RUN_NAME)
    expected_top_level = {
        "dry_run_id",
        "schema_version",
        "protocol_version",
        "suite_id",
        "suite_manifest_id",
        "status",
        "checks",
        "deployment",
        "preflight",
        "question_count",
        "planned_records",
        "condition_counts",
        "execution_order_sha256",
        "batch_count",
        "records_per_batch",
        "child_checkpoints",
        "resume_projection_checks",
        "api_boundary",
        "answer_boundary",
        "gold_boundary",
        "judge_boundary",
    }
    if set(report) != expected_top_level:
        raise EvidenceValidationError("Model 2 suite dry-run schema differs")
    identity = report.get("dry_run_id")
    body = {key: value for key, value in report.items() if key != "dry_run_id"}
    if identity != "model2-suite-dry-run-" + sha256_bytes(canonical_json_bytes(body)):
        raise EvidenceValidationError("Model 2 suite dry-run content hash differs")
    checks = report.get("checks")
    deployment = suite.manifest["deployment"]
    preflight = report.get("preflight")
    schedule = [
        {
            "condition_id": row.get("condition_id"),
            "question_id": row.get("question_id"),
        }
        for row in suite.manifest["global_schedule"]
    ]
    execution_order_sha256 = sha256_bytes(canonical_json_bytes(schedule))
    expected_condition_counts = {condition: 60 for condition in CONDITION_IDS}
    batch_map = suite.manifest.get("batch_map")
    expected_batch_records = (
        batch_map[0].get("record_count")
        if isinstance(batch_map, list) and len(batch_map) == MODEL2_GLOBAL_BATCHES
        else None
    )
    expected_resume_checks = {
        f"completed_{boundary}": True
        for boundary in range(0, MODEL2_PLANNED_RECORDS + 1, 35)
    }

    child_checkpoints = report.get("child_checkpoints")
    checkpoints_valid = (
        isinstance(child_checkpoints, Mapping)
        and set(child_checkpoints) == {MAIN_CHILD_ID, EXTENSION_CHILD_ID}
    )
    if checkpoints_valid:
        for child_id, expected_planned in (
            (MAIN_CHILD_ID, 280),
            (EXTENSION_CHILD_ID, 140),
        ):
            checkpoint = child_checkpoints[child_id]
            store = _store_for_child(suite, child_id)
            if not isinstance(checkpoint, Mapping):
                checkpoints_valid = False
                break
            checkpoint_body = {
                key: value
                for key, value in checkpoint.items()
                if key != "checkpoint_sha256"
            }
            checkpoints_valid = checkpoints_valid and (
                set(checkpoint)
                == {
                    "schema_version",
                    "protocol_version",
                    "plan_id",
                    "run_id",
                    "planned",
                    "completed",
                    "pending",
                    "failed_attempts",
                    "completed_records",
                    "pending_keys",
                    "checkpoint_sha256",
                }
                and checkpoint.get("schema_version") == 1
                and checkpoint.get("protocol_version")
                == RUN_CHECKPOINT_PROTOCOL_VERSION
                and checkpoint.get("plan_id") == store.plan.plan_id
                and checkpoint.get("run_id") == store.plan.run_id
                and checkpoint.get("planned") == expected_planned
                and checkpoint.get("completed") == 0
                and checkpoint.get("pending") == expected_planned
                and checkpoint.get("failed_attempts") == 0
                and checkpoint.get("completed_records") == []
                and checkpoint.get("pending_keys")
                == [key.to_dict() for key in store.plan.execution_order]
                and checkpoint.get("checkpoint_sha256")
                == sha256_bytes(canonical_json_bytes(checkpoint_body))
            )
            if not checkpoints_valid:
                break
    if (
        report.get("schema_version") != 1
        or report.get("protocol_version") != MODEL2_DRY_RUN_PROTOCOL_VERSION
        or report.get("suite_id") != suite.manifest["suite_id"]
        or report.get("status") != "passed"
        or report.get("suite_manifest_id") != suite.manifest["suite_manifest_id"]
        or not isinstance(checks, Mapping)
        or set(checks) != MODEL2_DRY_RUN_REQUIRED_CHECKS
        or not all(value is True for value in checks.values())
        or report.get("deployment") != deployment
        or not isinstance(preflight, Mapping)
        or preflight.get("verified") is not True
        or preflight.get("artifact_type") != "model2-role-smoke"
        or preflight.get("requested_alias") != deployment["requested_model_alias"]
        or preflight.get("served_model") != deployment["required_served_model"]
        or preflight.get("role_smokes_passed") != 5
        or preflight.get("components")
        != ["r1", "r1_compaction", "r2", "r3", "answerer"]
        or report.get("question_count") != MODEL2_QUESTION_COUNT
        or report.get("planned_records") != MODEL2_PLANNED_RECORDS
        or report.get("condition_counts") != expected_condition_counts
        or report.get("execution_order_sha256") != execution_order_sha256
        or report.get("batch_count") != MODEL2_GLOBAL_BATCHES
        or expected_batch_records != 35
        or report.get("records_per_batch") != expected_batch_records
        or not checkpoints_valid
        or report.get("resume_projection_checks") != expected_resume_checks
        or report.get("api_boundary") != {"provider_constructed": False, "calls": 0}
        or report.get("answer_boundary") != {"records_generated": 0}
        or report.get("gold_boundary") != {"semantic_records_loaded": False}
        or report.get("judge_boundary") != {"judge_constructed": False, "calls": 0}
    ):
        raise EvidenceValidationError("Model 2 answer run requires a passing suite dry-run")
    return report


def _child_status_body(
    suite: OpenModel2Suite, child_id: str
) -> dict[str, Any]:
    store = _store_for_child(suite, child_id)
    checkpoint = store.checkpoint()
    completed_by_condition = {condition: 0 for condition in CONDITION_IDS}
    for key in store.plan.execution_order:
        if store.load_completed(key) is not None:
            completed_by_condition[key.condition_id] += 1
    finished_questions = sum(
        all(
            store.load_completed(RunKey(condition, question_id)) is not None
            for condition in CONDITION_IDS
        )
        for question_id in store.plan.question_ids
    )
    active_failed = _active_failure_count(store)
    status = (
        "completed"
        if checkpoint["pending"] == 0
        else "failed"
        if active_failed
        else "running"
    )
    return {
        "schema_version": 1,
        "protocol_version": MODEL2_SUITE_PROTOCOL_VERSION,
        "suite_id": suite.manifest["suite_id"],
        "suite_manifest_id": suite.manifest["suite_manifest_id"],
        "child_id": child_id,
        "run_id": store.plan.run_id,
        "plan_id": store.plan.plan_id,
        "status": status,
        "planned_records": checkpoint["planned"],
        "completed_records": checkpoint["completed"],
        "pending_records": checkpoint["pending"],
        "failure_attempts": checkpoint["failed_attempts"],
        "active_failed_keys": active_failed,
        "completed_by_condition": completed_by_condition,
        "finished_questions": finished_questions,
        "completed_blocks": checkpoint["completed"] // MODEL2_BATCH_RECORDS,
        "next_key": checkpoint["pending_keys"][0] if checkpoint["pending_keys"] else None,
        "checkpoint_sha256": checkpoint["checkpoint_sha256"],
        "updated_at": _now(),
    }


def _write_child_status(suite: OpenModel2Suite, child_id: str) -> dict[str, Any]:
    status = _child_status_body(suite, child_id)
    store = _store_for_child(suite, child_id)
    _write_atomic_json(store.run_root / CHILD_STATUS_NAME, status)
    return status


def _safe_error(error: BaseException, provider: ChatProvider) -> str:
    message = " ".join(str(error).split())[:1000] or type(error).__name__
    secret = getattr(provider, "api_key", None)
    if isinstance(secret, str) and secret:
        message = message.replace(secret, "[REDACTED_KEY]")
    return re.sub(
        r"\b(?:clsk|sk)[_-][A-Za-z0-9_-]{10,}\b", "[REDACTED_KEY]", message
    )


def _publish_failure_metadata(
    *,
    suite: OpenModel2Suite,
    store: ExperimentRunStore,
    key: RunKey,
    provider: ModelIdentityProvider,
    attempt_usage: Mapping[str, int],
    provider_failures: Sequence[Mapping[str, Any]],
) -> Path:
    """Publish the safe deployment receipt paired with a RunFailureRecord."""
    attempts = store.failure_attempts(key)
    if not attempts:
        raise EvidenceValidationError("Model 2 failure metadata has no failure record")
    failure = attempts[-1]
    body = {
        "schema_version": 1,
        "protocol_version": MODEL2_SUITE_PROTOCOL_VERSION,
        "suite_id": suite.manifest["suite_id"],
        "suite_manifest_id": suite.manifest["suite_manifest_id"],
        "run_id": store.plan.run_id,
        "plan_id": store.plan.plan_id,
        **key.to_dict(),
        "attempt": failure.attempt,
        "failure_id": failure.failure_id,
        "stage": failure.stage,
        "error_type": failure.error_type,
        "retryable": failure.retryable,
        "requested_model_alias": suite.manifest["deployment"][
            "requested_model_alias"
        ],
        "required_served_model": suite.manifest["deployment"][
            "required_served_model"
        ],
        "observed_served_model": provider.observed_served_model,
        "failed_attempt_usage": dict(attempt_usage),
        "provider_failures": [dict(row) for row in provider_failures],
    }
    metadata = {
        "failure_metadata_id": "model2-failure-metadata-"
        + sha256_bytes(canonical_json_bytes(body)),
        **body,
    }
    path = (
        store.run_root
        / CHILD_FAILURE_METADATA_DIR
        / key.condition_id
        / key.question_id
        / f"attempt-{failure.attempt:04d}.json"
    )
    _publish_json(path, metadata)
    return path


def _verify_failure_metadata(
    *, suite: OpenModel2Suite, store: ExperimentRunStore, key: RunKey
) -> dict[str, int]:
    """Verify every prior outer failure has a bound, sanitized model receipt."""
    expected_alias = suite.manifest["deployment"]["requested_model_alias"]
    expected_served = suite.manifest["deployment"]["required_served_model"]
    failures = store.failure_attempts(key)
    aggregate = {
        "failure_attempts": 0,
        "model_calls": 0,
        "usage_available_calls": 0,
        "usage_unavailable_calls": 0,
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "total_tokens": 0,
    }
    for failure in failures:
        path = (
            store.run_root
            / CHILD_FAILURE_METADATA_DIR
            / key.condition_id
            / key.question_id
            / f"attempt-{failure.attempt:04d}.json"
        )
        metadata = _read_json(path)
        identity = metadata.get("failure_metadata_id")
        body = {
            name: value
            for name, value in metadata.items()
            if name != "failure_metadata_id"
        }
        if (
            set(metadata)
            != {
                "failure_metadata_id",
                "schema_version",
                "protocol_version",
                "suite_id",
                "suite_manifest_id",
                "run_id",
                "plan_id",
                "condition_id",
                "question_id",
                "attempt",
                "failure_id",
                "stage",
                "error_type",
                "retryable",
                "requested_model_alias",
                "required_served_model",
                "observed_served_model",
                "failed_attempt_usage",
                "provider_failures",
            }
            or identity
            != "model2-failure-metadata-"
            + sha256_bytes(canonical_json_bytes(body))
            or metadata.get("schema_version") != 1
            or metadata.get("protocol_version") != MODEL2_SUITE_PROTOCOL_VERSION
            or metadata.get("suite_id") != suite.manifest["suite_id"]
            or metadata.get("suite_manifest_id")
            != suite.manifest["suite_manifest_id"]
            or metadata.get("run_id") != store.plan.run_id
            or metadata.get("plan_id") != store.plan.plan_id
            or metadata.get("condition_id") != key.condition_id
            or metadata.get("question_id") != key.question_id
            or metadata.get("attempt") != failure.attempt
            or metadata.get("failure_id") != failure.failure_id
            or metadata.get("stage") != failure.stage
            or metadata.get("error_type") != failure.error_type
            or metadata.get("retryable") != failure.retryable
            or metadata.get("requested_model_alias") != expected_alias
            or metadata.get("required_served_model") != expected_served
            or metadata.get("observed_served_model") not in {None, expected_served}
        ):
            raise EvidenceValidationError("Model 2 failure metadata differs")
        usage = metadata.get("failed_attempt_usage")
        provider_failures = metadata.get("provider_failures")
        if not isinstance(provider_failures, list):
            raise EvidenceValidationError("Model 2 provider failures differ")
        for row in provider_failures:
            if (
                not isinstance(row, Mapping)
                or set(row)
                != {"call_index", "error_class", "kind", "http_status"}
                or isinstance(row.get("call_index"), bool)
                or not isinstance(row.get("call_index"), int)
                or row["call_index"] < 1
                or row.get("error_class") not in {"transient", "generic"}
                or (
                    row["error_class"] == "transient"
                    and (
                        row.get("kind") not in {"timeout", "http"}
                        or (
                            row.get("kind") == "timeout"
                            and row.get("http_status") is not None
                        )
                        or (
                            row.get("kind") == "http"
                            and (
                                isinstance(row.get("http_status"), bool)
                                or not isinstance(row.get("http_status"), int)
                            )
                        )
                    )
                )
                or (
                    row["error_class"] == "generic"
                    and (row.get("kind") is not None or row.get("http_status") is not None)
                )
            ):
                raise EvidenceValidationError("Model 2 provider failures differ")
        usage_fields = {
            "model_calls",
            "usage_available_calls",
            "usage_unavailable_calls",
            "prompt_tokens",
            "completion_tokens",
            "total_tokens",
        }
        if (
            not isinstance(usage, Mapping)
            or set(usage) != usage_fields
            or any(
                isinstance(usage.get(name), bool)
                or not isinstance(usage.get(name), int)
                or usage.get(name) < 0
                for name in usage_fields
            )
            or usage["model_calls"]
            != usage["usage_available_calls"] + usage["usage_unavailable_calls"]
            or usage["total_tokens"]
            != usage["prompt_tokens"] + usage["completion_tokens"]
        ):
            raise EvidenceValidationError("Model 2 failed-attempt usage differs")
        aggregate["failure_attempts"] += 1
        for name in usage_fields:
            aggregate[name] += int(usage[name])
    return aggregate


def _is_retryable_error(error: BaseException) -> bool:
    current: BaseException | None = error
    seen: set[int] = set()
    while current is not None and id(current) not in seen:
        if isinstance(current, TransientProviderError):
            return True
        if getattr(current, "retryable", None) is True:
            return True
        if getattr(current, "stage", None) in MODEL2_RETRYABLE_FAILURE_STAGES:
            return True
        seen.add(id(current))
        current = current.__cause__ or current.__context__
    return False


def _load_model2_retrieval_bundle(
    *, run_root: Path, key: RunKey, stores: Mapping[str, Any], r3_corpus: Any
) -> EvidenceBundle:
    """Verify a child retrieval artifact without importing the old batch runner."""
    path = Path(run_root) / key.condition_id / key.question_id
    method, store_id = CONDITION_METHODS[key.condition_id]
    if method == "r1":
        return verify_r1_episode_artifact(path, loaded_store=stores[store_id])
    if method == "r2":
        return verify_r2_episode_artifact(path, loaded_store=stores[store_id])
    return verify_r3_episode_artifact(path, corpus=r3_corpus)


def _verify_retrieval_failure(method: str, artifact_path: Path) -> Any:
    if method == "r1":
        return verify_r1_failure_artifact(artifact_path)
    if method == "r2":
        return verify_r2_failure_artifact(artifact_path)
    return verify_r3_failure_artifact(artifact_path)


def _retrieval_failure_metadata(
    method: str,
    artifact_path: Path,
    *,
    provider_failures: Sequence[Mapping[str, Any]],
) -> tuple[str, bool]:
    failure = _verify_retrieval_failure(method, artifact_path)
    stage = str(failure.failure_kind)
    retryable = stage in MODEL2_RETRYABLE_FAILURE_STAGES
    terminal_provider_failure_is_transient = bool(provider_failures) and all(
        row.get("error_class") == "transient" for row in provider_failures
    )
    if method == "r1" and stage == "provider":
        retryable = (
            terminal_provider_failure_is_transient
            and any(
                item.get("message")
                == "Provider request exhausted the frozen retry policy"
                for item in failure.errors
            )
        )
    elif stage == "provider_request":
        # A prior provider_retry event alone is insufficient: a later generic
        # DNS/HTTP-400 failure can terminate the same episode.  The boundary
        # decorator preserves a sanitized sequence, and every provider failure
        # in this episode must be transient before an outer replay is allowed.
        retryable = (
            terminal_provider_failure_is_transient
            and any(
                item.get("event") == "provider_retry"
                for item in failure.search_actions
            )
        )
    return stage, retryable


def _reuse_duplicate_retrieval_failure(
    *,
    method: str,
    artifact: Path,
    prior_staging: frozenset[Path],
) -> Path | None:
    """Deduplicate a replayed content-addressed low-level failure artifact.

    The R1/R2/R3 publishers intentionally derive the failure-directory suffix
    from content.  An identical retry therefore cannot publish a second copy.
    We verify both complete copies, reuse the existing immutable artifact, and
    remove only the newly-created byte-equivalent staging directory.  The
    outer RunFailureRecord still preserves this invocation as a new attempt.
    """
    parent = artifact.parent
    candidates = frozenset(parent.glob(f".{artifact.name}.in-progress-*")) - prior_staging
    complete: list[tuple[Path, Any]] = []
    for candidate in candidates:
        if candidate.is_symlink() or not candidate.is_dir():
            continue
        try:
            complete.append((candidate, _verify_retrieval_failure(method, candidate)))
        except EvidenceValidationError:
            continue
    if len(complete) != 1:
        return None
    staging, replayed = complete[0]
    final = artifact.with_name(
        f"{artifact.name}.failed-{replayed.failure_id.removeprefix('failure-')[:12]}"
    )
    if final.is_symlink() or not final.is_dir():
        return None
    existing = _verify_retrieval_failure(method, final)
    if existing != replayed:
        raise EvidenceValidationError(
            "Replayed retrieval failure collides with different preserved content"
        )
    shutil.rmtree(staging)
    return final


@contextmanager
def _exclusive_child_lock(run_root: Path):
    path = Path(run_root) / "run.lock"
    handle = path.open("a+", encoding="utf-8")
    try:
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise EvidenceValidationError(
                "Another Model 2 runner holds the child run.lock"
            ) from exc
        yield
    finally:
        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        handle.close()


def _require_main_child_gate(suite: OpenModel2Suite) -> None:
    checkpoint = suite.main_store.checkpoint()
    if checkpoint["completed"] != 280 or checkpoint["pending"] != 0:
        raise EvidenceValidationError("Model 2 extension20 requires completed main40")
    audit = _read_json(suite.suite_root / "control" / "batch-08-audit.json")
    marker = _read_json(suite.suite_root / "control" / "batch-08.PASSED")
    if (
        audit.get("status") != "passed"
        or audit.get("global_batch") != 8
        or marker.get("status") != "passed"
        or marker.get("batch_audit_id") != audit.get("batch_audit_id")
        or marker.get("suite_manifest_id") != suite.manifest["suite_manifest_id"]
    ):
        raise EvidenceValidationError("Model 2 main40 B08 gate is not valid")


def _run_retrieval(
    *,
    suite: OpenModel2Suite,
    store: ExperimentRunStore,
    key: RunKey,
    question: QuestionInput,
    provider: ChatProvider,
    stores: Mapping[str, Any],
    r2_corpora: Mapping[str, Any],
    r3_corpus: Any,
) -> EvidenceBundle:
    artifact = store.run_root / key.condition_id / key.question_id
    provider_failure_cursor = (
        provider.provider_failure_cursor()
        if isinstance(provider, ModelIdentityProvider)
        else 0
    )
    if not artifact.exists():
        method, store_id = CONDITION_METHODS[key.condition_id]
        prior_staging = frozenset(
            artifact.parent.glob(f".{artifact.name}.in-progress-*")
        )
        common = {
            "repo_root": suite.repo_root,
            "output_root": store.root,
            "run_id": store.plan.run_id,
            "question": question,
            "provider": provider,
            "requested_model": suite.manifest["deployment"]["requested_model_alias"],
            "budget_unit": MODEL2_EVIDENCE_BUDGET_UNIT,
            "budget_limit": MODEL2_EVIDENCE_BUDGET_LIMIT,
        }
        try:
            if method == "r1":
                result = execute_r1_question(
                    **common,
                    cell_id=key.condition_id,
                    loaded_store=stores[store_id],
                )
            elif method == "r2":
                result = execute_r2_question(
                    **common,
                    cell_id=key.condition_id,
                    corpus=r2_corpora[store_id],
                )
            else:
                result = execute_r3_question(**common, corpus=r3_corpus)
        except Exception:
            if isinstance(provider, ModelIdentityProvider):
                provider.raise_if_identity_error()
            reused = _reuse_duplicate_retrieval_failure(
                method=method, artifact=artifact, prior_staging=prior_staging
            )
            if reused is None:
                raise
            provider_failures = (
                provider.provider_failures_since(provider_failure_cursor)
                if isinstance(provider, ModelIdentityProvider)
                else ()
            )
            stage, retryable = _retrieval_failure_metadata(
                method, reused, provider_failures=provider_failures
            )
            raise Model2RecordError(
                "retrieval repeated an existing content-addressed failure artifact",
                stage=stage,
                retryable=retryable,
            )
        if result.status == "failed":
            if isinstance(provider, ModelIdentityProvider):
                provider.raise_if_identity_error()
            provider_failures = (
                provider.provider_failures_since(provider_failure_cursor)
                if isinstance(provider, ModelIdentityProvider)
                else ()
            )
            stage, retryable = _retrieval_failure_metadata(
                method,
                result.artifact_path,
                provider_failures=provider_failures,
            )
            raise Model2RecordError(
                f"retrieval failed and preserved artifact {result.artifact_id}",
                stage=stage,
                retryable=retryable,
            )
    bundle = _load_model2_retrieval_bundle(
        run_root=store.run_root,
        key=key,
        stores=stores,
        r3_corpus=r3_corpus,
    )
    _validate_model2_retrieval_bundle(bundle, key=key, suite=suite)
    return bundle


def run_child(
    *,
    repo_root: Path,
    output_root: Path,
    suite_id: str,
    child_id: str,
    through_block: int,
    provider: ChatProvider,
) -> dict[str, Any]:
    """Run/resume one isolated child through a five-question block boundary.

    This is the only online entry point for the main-60 suite.  It loads no
    semantic gold and constructs no evaluator or Judge.
    """
    maximum = {MAIN_CHILD_ID: 8, EXTENSION_CHILD_ID: 4}.get(child_id, 0)
    if (
        maximum == 0
        or isinstance(through_block, bool)
        or not isinstance(through_block, int)
        or not 1 <= through_block <= maximum
    ):
        raise EvidenceValidationError("Model 2 through_block is outside the child plan")
    root = Path(repo_root).resolve()
    output = Path(output_root).resolve()
    suite = open_suite(repo_root=root, output_root=output, suite_id=suite_id)
    _assert_no_identity_drift(suite)
    _load_suite_dry_run(suite)
    if child_id == EXTENSION_CHILD_ID:
        _require_main_child_gate(suite)
    store = _store_for_child(suite, child_id)
    target_records = through_block * MODEL2_BATCH_RECORDS
    question_rows = (
        load_question_inputs(root, "main-40")
        if child_id == MAIN_CHILD_ID
        else _load_extension_questions(root)
    )
    questions = {item.question_id: item for item in question_rows}
    if tuple(questions) != store.plan.question_ids:
        raise EvidenceValidationError("Model 2 child question order drifted")
    gated = guard_provider_for_suite(suite, provider)
    stores = {name: load_r1_store(root, name) for name in ("s1", "s2", "s3")}
    r2_corpora = {name: build_r2_raw_corpus(root, name) for name in ("s1", "s2")}
    r3_corpus = load_r3_corpus(root)
    answerer = SharedAnswerer(
        provider=gated,
        requested_model=suite.manifest["deployment"]["requested_model_alias"],
    )
    events = store.run_root / "events.jsonl"

    with exclusive_suite_lock(suite.suite_root), _exclusive_child_lock(store.run_root):
        before = _write_child_status(suite, child_id)
        _append_event(
            events,
            {
                "event": "model2_child_started",
                "at": _now(),
                "child_id": child_id,
                "completed_before": before["completed_records"],
                "through_block": through_block,
                "target_records": target_records,
            },
        )
        for sequence, key in enumerate(store.plan.execution_order, start=1):
            if sequence > target_records:
                break
            if store.load_completed(key) is not None:
                continue
            _require_attempt_budget(store, key)
            _append_event(
                events,
                {
                    "event": "record_started",
                    "at": _now(),
                    "sequence": sequence,
                    **key.to_dict(),
                },
            )
            usage_cursor = gated.usage_cursor()
            failure_usage_cursor = usage_cursor
            provider_failure_cursor = gated.provider_failure_cursor()
            try:
                if key.condition_id == "E7":
                    raw = store.load_completed(RunKey("E2", key.question_id))
                    curated = store.load_completed(RunKey("E6", key.question_id))
                    if (
                        raw is None
                        or curated is None
                        or not isinstance(raw.evidence_bundle, EvidenceBundle)
                        or not isinstance(curated.evidence_bundle, EvidenceBundle)
                    ):
                        raise EvidenceValidationError(
                            "Model 2 E7 reached before same-run E2 and E6"
                        )
                    bundle: EvidenceBundle | FusionEvidenceBundle = build_e7_fusion_bundle(
                        raw.evidence_bundle, curated.evidence_bundle
                    )
                else:
                    bundle = _run_retrieval(
                        suite=suite,
                        store=store,
                        key=key,
                        question=questions[key.question_id],
                        provider=gated,
                        stores=stores,
                        r2_corpora=r2_corpora,
                        r3_corpus=r3_corpus,
                    )
                # Retrieval bundles are immutable and reused by a later outer
                # retry.  Once one is durable, only post-retrieval calls are
                # failure overhead; counting retrieval again would duplicate
                # the same bundle cost in the eventual successful RunRecord.
                failure_usage_cursor = gated.usage_cursor()
                answer = answerer.run(bundle)
                record = RunRecord.create(
                    plan_id=store.plan.plan_id,
                    run_id=store.plan.run_id,
                    condition_id=key.condition_id,
                    evidence_bundle=bundle,
                    answer_result=answer,
                )
                _validate_record(record, suite)
                store.publish_success(record)
            except Exception as error:
                if gated.identity_error is not None:
                    _seal_identity_drift(suite=suite, key=key, provider=gated)
                    error = gated.identity_error
                store.publish_failure(
                    key=key,
                    stage=getattr(error, "stage", "model2_record"),
                    error_type=type(error).__name__,
                    message=_safe_error(error, gated),
                    retryable=_is_retryable_error(error),
                )
                _publish_failure_metadata(
                    suite=suite,
                    store=store,
                    key=key,
                    provider=gated,
                    attempt_usage=gated.usage_since(failure_usage_cursor),
                    provider_failures=gated.provider_failures_since(
                        provider_failure_cursor
                    ),
                )
                _append_event(
                    events,
                    {
                        "event": "record_failed",
                        "at": _now(),
                        "sequence": sequence,
                        **key.to_dict(),
                        "error_type": type(error).__name__,
                    },
                )
                child_status = _write_child_status(suite, child_id)
                suite_status = _write_suite_status_open(suite)
                return {
                    "status": "failed",
                    "child_id": child_id,
                    **key.to_dict(),
                    "progress": child_status,
                    "suite_progress": suite_status,
                }

            _append_event(
                events,
                {
                    "event": "record_verified",
                    "at": _now(),
                    "sequence": sequence,
                    **key.to_dict(),
                    "record_id": record.record_id,
                    "evidence_items": len(bundle.evidence_items),
                    "served_models": list(answer.served_models),
                    "total_tokens": record.deployment_metrics["total_tokens"],
                },
            )
            current = _write_child_status(suite, child_id)
            _write_suite_status_open(suite)
            if current["completed_records"] % MODEL2_BATCH_RECORDS == 0:
                _append_event(
                    events,
                    {
                        "event": "question_block_verified",
                        "at": _now(),
                        "completed_records": current["completed_records"],
                        "completed_blocks": current["completed_blocks"],
                    },
                )

        final_child = _write_child_status(suite, child_id)
        final_suite = _write_suite_status_open(suite)
        first_global = 1 if child_id == MAIN_CHILD_ID else 9
        last_global = through_block if child_id == MAIN_CHILD_ID else 8 + through_block
        for global_batch in range(first_global, last_global + 1):
            write_batch_audit(
                repo_root=root,
                output_root=output,
                suite_id=suite_id,
                global_batch=global_batch,
            )
        _append_event(
            events,
            {
                "event": (
                    "model2_child_completed"
                    if final_child["pending_records"] == 0
                    else "model2_batch_target_reached"
                ),
                "at": _now(),
                "child_id": child_id,
                "completed_records": final_child["completed_records"],
                "through_block": through_block,
                "target_records": target_records,
            },
        )
        return {
            **final_child,
            "suite_progress": final_suite,
            "execution_control": {
                "through_block": through_block,
                "target_records": target_records,
                "target_reached": final_child["completed_records"] >= target_records,
            },
        }


def run_child_with_recovery(
    *,
    repo_root: Path,
    output_root: Path,
    suite_id: str,
    child_id: str,
    through_block: int,
    provider: ChatProvider,
) -> dict[str, Any]:
    """Run one child with the manifest's bounded same-provider recovery policy.

    Recovery is intentionally narrow: only a failure whose preserved
    ``RunFailureRecord.retryable`` flag was derived from the frozen stage
    whitelist may be retried.  A model-identity violation is sealed before this
    function regains control and can never be retried.
    """
    invocations = 0
    while True:
        invocations += 1
        result = run_child(
            repo_root=repo_root,
            output_root=output_root,
            suite_id=suite_id,
            child_id=child_id,
            through_block=through_block,
            provider=provider,
        )
        if result.get("status") != "failed":
            return {
                **result,
                "recovery": {
                    "runner_invocations": invocations,
                    "status": "target-reached",
                },
            }
        suite = open_suite(
            repo_root=repo_root, output_root=output_root, suite_id=suite_id
        )
        _assert_no_identity_drift(suite)
        store = _store_for_child(suite, child_id)
        key = RunKey(str(result["condition_id"]), str(result["question_id"]))
        failures = store.failure_attempts(key)
        if not failures:
            raise EvidenceValidationError(
                "Model 2 failed result has no preserved failure attempt"
            )
        latest = failures[-1]
        if not latest.retryable:
            return {
                **result,
                "recovery": {
                    "runner_invocations": invocations,
                    "status": "non-retryable",
                    "attempts_for_key": len(failures),
                },
            }
        if len(failures) >= MODEL2_OUTER_SAME_CONFIG_ATTEMPT_LIMIT:
            return {
                **result,
                "recovery": {
                    "runner_invocations": invocations,
                    "status": "attempt-limit-exhausted",
                    "attempts_for_key": len(failures),
                },
            }


def _active_failure_count(store: ExperimentRunStore) -> int:
    return sum(
        store.load_completed(key) is None and bool(store.failure_attempts(key))
        for key in store.plan.execution_order
    )


def _suite_status_body(suite: OpenModel2Suite) -> dict[str, Any]:
    checkpoints = {
        MAIN_CHILD_ID: suite.main_store.checkpoint(),
        EXTENSION_CHILD_ID: suite.extension_store.checkpoint(),
    }
    completed_by_condition = {condition: 0 for condition in CONDITION_IDS}
    completed_keys: set[tuple[str, str, str]] = set()
    active_failed = 0
    finished_questions = 0
    for child_id in (MAIN_CHILD_ID, EXTENSION_CHILD_ID):
        store = _store_for_child(suite, child_id)
        active_failed += _active_failure_count(store)
        for key in store.plan.execution_order:
            if store.load_completed(key) is not None:
                completed_by_condition[key.condition_id] += 1
                completed_keys.add((child_id, key.condition_id, key.question_id))
        finished_questions += sum(
            all(
                store.load_completed(RunKey(condition, question_id)) is not None
                for condition in CONDITION_IDS
            )
            for question_id in store.plan.question_ids
        )
    completed = sum(item["completed"] for item in checkpoints.values())
    pending = MODEL2_PLANNED_RECORDS - completed
    next_key = None
    for item in suite.manifest["global_schedule"]:
        identity = (item["child_id"], item["condition_id"], item["question_id"])
        if identity not in completed_keys:
            next_key = item
            break
    completed_batches = sum(
        all(
            (
                entry["child_id"],
                entry["condition_id"],
                entry["question_id"],
            ) in completed_keys
            for entry in suite.manifest["global_schedule"][
                (batch - 1) * MODEL2_BATCH_RECORDS : batch * MODEL2_BATCH_RECORDS
            ]
        )
        for batch in range(1, MODEL2_GLOBAL_BATCHES + 1)
    )
    identity_drift = (suite.suite_root / SUITE_IDENTITY_DRIFT_NAME).is_file()
    status = (
        "halted-model-identity-drift"
        if identity_drift
        else "completed"
        if not pending
        else "failed"
        if active_failed
        else "pending"
    )
    return {
        "schema_version": 1,
        "protocol_version": MODEL2_SUITE_PROTOCOL_VERSION,
        "suite_id": suite.manifest["suite_id"],
        "suite_manifest_id": suite.manifest["suite_manifest_id"],
        "status": status,
        "planned_records": MODEL2_PLANNED_RECORDS,
        "completed_records": completed,
        "pending_records": pending,
        "failure_attempts": sum(item["failed_attempts"] for item in checkpoints.values()),
        "active_failed_keys": active_failed,
        "model_identity_drift_halted": identity_drift,
        "completed_by_condition": completed_by_condition,
        "finished_questions": finished_questions,
        "completed_batches": completed_batches,
        "next_key": next_key,
        "children": {
            child: {
                "run_id": checkpoint["run_id"],
                "plan_id": checkpoint["plan_id"],
                "planned": checkpoint["planned"],
                "completed": checkpoint["completed"],
                "pending": checkpoint["pending"],
                "failed_attempts": checkpoint["failed_attempts"],
            }
            for child, checkpoint in checkpoints.items()
        },
        "updated_at": _now(),
    }


def write_suite_status(
    *, repo_root: Path, output_root: Path, suite_id: str
) -> dict[str, Any]:
    suite = open_suite(repo_root=repo_root, output_root=output_root, suite_id=suite_id)
    return _write_suite_status_open(suite)


def _write_suite_status_open(suite: OpenModel2Suite) -> dict[str, Any]:
    status = _suite_status_body(suite)
    _write_atomic_json(suite.suite_root / SUITE_STATUS_NAME, status)
    return status


def resume_window(
    *, repo_root: Path, output_root: Path, suite_id: str, through_batch: int
) -> dict[str, Any]:
    """Return the immutable pending slice through one global batch; no API call."""
    if (
        isinstance(through_batch, bool)
        or not isinstance(through_batch, int)
        or not 1 <= through_batch <= MODEL2_GLOBAL_BATCHES
    ):
        raise EvidenceValidationError("through_batch must be an integer from 1 to 12")
    suite = open_suite(repo_root=repo_root, output_root=output_root, suite_id=suite_id)
    _assert_no_identity_drift(suite)
    target = through_batch * MODEL2_BATCH_RECORDS
    pending: list[dict[str, Any]] = []
    completed = 0
    for item in suite.manifest["global_schedule"][:target]:
        store = _store_for_child(suite, item["child_id"])
        key = RunKey(item["condition_id"], item["question_id"])
        if store.load_completed(key) is None:
            pending.append(item)
        else:
            completed += 1
    return {
        "schema_version": 1,
        "protocol_version": MODEL2_SUITE_PROTOCOL_VERSION,
        "suite_id": suite_id,
        "suite_manifest_id": suite.manifest["suite_manifest_id"],
        "through_batch": through_batch,
        "target_records": target,
        "already_completed_records": completed,
        "pending_records": len(pending),
        "next_key": pending[0] if pending else None,
        "pending_keys": pending,
        "execution": "not-started-by-this-command",
    }


def _validate_record(record: RunRecord, suite: OpenModel2Suite) -> None:
    deployment = suite.manifest["deployment"]
    alias = deployment["requested_model_alias"]
    served = deployment["required_served_model"]
    answer = record.answer_result
    if answer.requested_model != alias or set(answer.served_models) != {served}:
        raise ModelIdentityError("Model 2 Answerer identity differs")
    if not set(answer.citations).issubset(
        {item.evidence_id for item in record.evidence_bundle.evidence_items}
    ):
        raise EvidenceValidationError("Model 2 answer citation is outside evidence")
    bundle = record.evidence_bundle
    if isinstance(bundle, EvidenceBundle):
        _validate_model2_retrieval_bundle(bundle, key=record.key, suite=suite)
    elif isinstance(bundle, FusionEvidenceBundle):
        if (
            bundle.retrieval_metrics.get("search_calls") != 0
            or bundle.retrieval_metrics.get("reused_upstream_retrieval") is not True
        ):
            raise EvidenceValidationError("Model 2 E7 performed new retrieval")
        if (
            bundle.budget.per_source_limit != MODEL2_EVIDENCE_BUDGET_LIMIT
            or bundle.budget.total_limit != 2 * MODEL2_EVIDENCE_BUDGET_LIMIT
        ):
            raise EvidenceValidationError("Model 2 E7 budget differs")
        if record.run_id == suite.main_store.plan.run_id:
            source_store = suite.main_store
        elif record.run_id == suite.extension_store.plan.run_id:
            source_store = suite.extension_store
        else:
            raise EvidenceValidationError("Model 2 E7 record belongs to another run")
        raw = source_store.load_completed(RunKey("E2", record.key.question_id))
        curated = source_store.load_completed(RunKey("E6", record.key.question_id))
        if raw is None or curated is None:
            raise EvidenceValidationError("Model 2 E7 source records are missing")
        if bundle.source_bundle_ids != (
            raw.evidence_bundle.bundle_id,
            curated.evidence_bundle.bundle_id,
        ):
            raise EvidenceValidationError("Model 2 E7 source bundle IDs differ")
        expected_retrieval = int(raw.retrieval_metrics["total_tokens"]) + int(
            curated.retrieval_metrics["total_tokens"]
        )
        if int(record.retrieval_metrics["total_tokens"]) != expected_retrieval:
            raise EvidenceValidationError("Model 2 E7 retrieval cost differs")
        if int(record.deployment_metrics["total_tokens"]) != expected_retrieval + int(
            record.answer_metrics["total_tokens"]
        ):
            raise EvidenceValidationError("Model 2 E7 total cost differs")
    else:
        raise EvidenceValidationError("Model 2 record has unsupported evidence")


def write_batch_audit(
    *, repo_root: Path, output_root: Path, suite_id: str, global_batch: int
) -> dict[str, Any]:
    if (
        isinstance(global_batch, bool)
        or not isinstance(global_batch, int)
        or not 1 <= global_batch <= MODEL2_GLOBAL_BATCHES
    ):
        raise EvidenceValidationError("global_batch must be an integer from 1 to 12")
    suite = open_suite(repo_root=repo_root, output_root=output_root, suite_id=suite_id)
    _assert_no_identity_drift(suite)
    target = global_batch * MODEL2_BATCH_RECORDS
    records: list[RunRecord] = []
    failed_usage = {
        "failure_attempts": 0,
        "model_calls": 0,
        "usage_available_calls": 0,
        "usage_unavailable_calls": 0,
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "total_tokens": 0,
    }
    for item in suite.manifest["global_schedule"][:target]:
        store = _store_for_child(suite, item["child_id"])
        key = RunKey(item["condition_id"], item["question_id"])
        record = store.load_completed(key)
        if record is None:
            raise EvidenceValidationError("Batch audit target is not complete")
        _validate_record(record, suite)
        item_usage = _verify_failure_metadata(
            suite=suite, store=store, key=key
        )
        for name, value in item_usage.items():
            failed_usage[name] += value
        records.append(record)
    batch = suite.manifest["batch_map"][global_batch - 1]
    body = {
        "schema_version": 1,
        "protocol_version": MODEL2_SUITE_PROTOCOL_VERSION,
        "suite_id": suite_id,
        "suite_manifest_id": suite.manifest["suite_manifest_id"],
        "batch_id": batch["batch_id"],
        "global_batch": global_batch,
        "status": "passed",
        "target_records": target,
        "verified_records": len(records),
        "verified_failure_attempts": failed_usage["failure_attempts"],
        "failed_attempt_usage": failed_usage,
        "failed_attempt_token_cost_complete": (
            failed_usage["usage_unavailable_calls"] == 0
        ),
        "batch_mapping": batch,
        "deployment_contract_sha256": suite.manifest["deployment"][
            "deployment_contract_sha256"
        ],
        "model_identity_verified": True,
        "citations_verified": True,
        "e7_no_new_retrieval_verified": True,
    }
    audit = {
        "batch_audit_id": "model2-batch-audit-" + sha256_bytes(canonical_json_bytes(body)),
        **body,
    }
    control = suite.suite_root / "control"
    _publish_json(control / f"batch-{global_batch:02d}-audit.json", audit)
    _publish_json(
        control / f"batch-{global_batch:02d}.PASSED",
        {
            "status": "passed",
            "batch_id": batch["batch_id"],
            "batch_audit_id": audit["batch_audit_id"],
            "suite_manifest_id": suite.manifest["suite_manifest_id"],
        },
    )
    return audit


def verify_pre_gold(
    *, repo_root: Path, output_root: Path, suite_id: str
) -> dict[str, Any]:
    """Require 420/420 plus all batch gates; never load gold or call a Judge."""
    suite = open_suite(repo_root=repo_root, output_root=output_root, suite_id=suite_id)
    _assert_no_identity_drift(suite)
    status = _suite_status_body(suite)
    if status["completed_records"] != MODEL2_PLANNED_RECORDS or status["pending_records"]:
        raise EvidenceValidationError("Model 2 pre-gold verification requires 420/420")
    counts = {condition: 0 for condition in CONDITION_IDS}
    failed_usage = {
        "failure_attempts": 0,
        "model_calls": 0,
        "usage_available_calls": 0,
        "usage_unavailable_calls": 0,
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "total_tokens": 0,
    }
    for item in suite.manifest["global_schedule"]:
        store = _store_for_child(suite, item["child_id"])
        key = RunKey(item["condition_id"], item["question_id"])
        record = store.load_completed(key)
        if record is None:
            raise EvidenceValidationError("Model 2 completed record disappeared")
        _validate_record(record, suite)
        item_usage = _verify_failure_metadata(
            suite=suite, store=store, key=key
        )
        for name, value in item_usage.items():
            failed_usage[name] += value
        counts[item["condition_id"]] += 1
    batch_audits: list[str] = []
    for global_batch in range(1, MODEL2_GLOBAL_BATCHES + 1):
        audit = _read_json(
            suite.suite_root / "control" / f"batch-{global_batch:02d}-audit.json"
        )
        marker = _read_json(
            suite.suite_root / "control" / f"batch-{global_batch:02d}.PASSED"
        )
        if audit.get("status") != "passed" or marker.get("batch_audit_id") != audit.get(
            "batch_audit_id"
        ):
            raise EvidenceValidationError("Model 2 batch gate differs")
        batch_audits.append(str(audit["batch_audit_id"]))
    checks = {
        "records_420_complete": True,
        "conditions_60_each": set(counts.values()) == {60},
        "served_model_exact": True,
        "citations_real": True,
        "e7_no_new_retrieval": True,
        "e7_budget_and_cost_verified": True,
        "all_12_batch_gates_passed": len(batch_audits) == 12,
        "failure_model_receipts_verified": True,
        "semantic_gold_loaded": False,
        "judge_calls": 0,
    }
    if not all(
        value is True for key, value in checks.items()
        if key not in {"semantic_gold_loaded", "judge_calls"}
    ) or checks["semantic_gold_loaded"] is not False or checks["judge_calls"] != 0:
        raise EvidenceValidationError("Model 2 pre-gold checks failed")
    body = {
        "schema_version": 1,
        "protocol_version": MODEL2_SUITE_PROTOCOL_VERSION,
        "suite_id": suite_id,
        "suite_manifest_id": suite.manifest["suite_manifest_id"],
        "status": "passed",
        "completed_records": MODEL2_PLANNED_RECORDS,
        "condition_counts": counts,
        "verified_failure_attempts": failed_usage["failure_attempts"],
        "failed_attempt_usage": failed_usage,
        "failed_attempt_token_cost_complete": (
            failed_usage["usage_unavailable_calls"] == 0
        ),
        "checks": checks,
        "batch_audit_ids": batch_audits,
        "completion_marker": "ANSWER-RUN-COMPLETED-NO-JUDGE",
    }
    audit = {
        "pre_gold_audit_id": "model2-pre-gold-" + sha256_bytes(canonical_json_bytes(body)),
        **body,
    }
    _publish_json(suite.suite_root / SUITE_PRE_GOLD_AUDIT_NAME, audit)
    _publish_json(
        suite.suite_root / SUITE_PRE_GOLD_MARKER_NAME,
        {
            "status": "passed",
            "completion_marker": "ANSWER-RUN-COMPLETED-NO-JUDGE",
            "pre_gold_audit_id": audit["pre_gold_audit_id"],
            "suite_manifest_id": suite.manifest["suite_manifest_id"],
        },
    )
    return audit


@contextmanager
def exclusive_suite_lock(suite_root: Path):
    """Prevent main-40 and extension-20 Model 2 runners from overlapping."""
    path = Path(suite_root) / "suite.lock"
    handle = path.open("a+", encoding="utf-8")
    try:
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise EvidenceValidationError("Another Model 2 runner holds suite.lock") from exc
        yield
    finally:
        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        handle.close()
