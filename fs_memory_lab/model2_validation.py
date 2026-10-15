"""Offline Model 2 suite validation and dev-6 pilot gates.

This module is deliberately provider-free.  It may plan an empty pilot run and
validate frozen contracts, but it cannot construct a chat provider, make an API
request, retrieve evidence, answer a question, load semantic gold, or score an
answer.  The live Model 2 runner consumes the artifacts produced here only
after the separate preflight and dry-run gates have passed.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

from .evidence import (
    BudgetRecord,
    EvidenceValidationError,
    canonical_json_bytes,
    sha256_bytes,
)
from .formal_v1 import (
    FORMAL_EVIDENCE_BUDGET_LIMIT,
    FORMAL_EVIDENCE_BUDGET_UNIT,
    FORMAL_MANIFEST_RELATIVE_PATH,
    verify_formal_manifest,
)
from .formal_v2_extension import _execution_order as extension_execution_order
from .formal_v2_extension import _load_extension_questions
from .fusion import FUSION_CONTRACT, FUSION_CONTRACT_SHA256
from .r1_inputs import load_question_inputs
from .r1_orchestration import R1_ROUND_LIMIT_BY_STORE
from .r2_protocol import R2_PARAMETERS
from .r3_protocol import R3_PARAMETERS
from .run_records import (
    CONDITION_IDS,
    RUN_PLAN_PROTOCOL_VERSION,
    ExperimentRunPlan,
    ExperimentRunStore,
    RunKey,
    run_plan_from_mapping,
    verify_run_store,
)


MODEL2_VALIDATION_PROTOCOL_VERSION = "formal-v2-model2-validation-v1"
MODEL2_PILOT_PROTOCOL_VERSION = "formal-v2-model2-dev6-pilot-plan-v1"
MODEL2_REQUESTED_MODEL_ALIAS = "x-test-2"
MODEL2_PILOT_MANIFEST_NAME = "model2-pilot-manifest.json"
MODEL2_PILOT_GATE_NAME = "model2-pilot-gate.json"
MODEL2_OFFLINE_REPORT_NAME = "dry-run.json"

MAIN_QUESTION_COUNT = 40
EXTENSION_QUESTION_COUNT = 20
SUITE_QUESTION_COUNT = 60
SUITE_RECORD_COUNT = 420
QUESTION_BLOCK_SIZE = 5
SUITE_BATCH_COUNT = 12
RECORDS_PER_BATCH = 35
PILOT_QUESTION_COUNT = 6
PILOT_RECORD_COUNT = 42
RETRIEVAL_EPISODES_PER_PILOT = 36

R1_ROUND_CAP_BY_CONDITION = {"E1": 20, "E3": 20, "E5": 40}
R2_ACTION_CAP = 4
R3_ACTION_CAP = 4
SYSTEM_FAILURE_RATE_LIMIT = 0.05
BUDGET_SKIP_EPISODE_FRACTION_LIMIT = 0.20
TOKEN_SAFETY_FUSE_LIMIT = 1_000_000

_SHA256 = re.compile(r"[0-9a-f]{64}\Z")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _require_sha256(value: Any, label: str) -> str:
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        raise EvidenceValidationError(f"{label} must be a SHA-256 digest")
    return value


def _file_sha256(path: Path) -> str:
    lexical = Path(path)
    if lexical.is_symlink() or not lexical.is_file():
        raise EvidenceValidationError(f"Unsafe or missing artifact: {lexical}")
    digest = hashlib.sha256()
    with lexical.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _read_json(path: Path) -> dict[str, Any]:
    lexical = Path(path)
    if lexical.is_symlink() or not lexical.is_file():
        raise EvidenceValidationError(f"Unsafe or missing JSON artifact: {lexical}")
    try:
        value = json.loads(lexical.read_text(encoding="utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise EvidenceValidationError(f"Invalid JSON artifact: {lexical}") from exc
    if not isinstance(value, dict):
        raise EvidenceValidationError("JSON artifact must contain an object")
    return value


def _publish_idempotent(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = canonical_json_bytes(value) + b"\n"
    if path.exists():
        if path.is_symlink() or path.read_bytes() != payload:
            raise EvidenceValidationError(f"Existing artifact differs: {path}")
        return
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(path, flags, 0o644)
    try:
        os.write(descriptor, payload)
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


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


def _global_execution_order(question_ids: Sequence[str]) -> tuple[RunKey, ...]:
    """Build the one global position-1--60 condition rotation."""
    primary = tuple(value for value in CONDITION_IDS if value != "E7")
    output: list[RunKey] = []
    for zero_based_position, question_id in enumerate(tuple(question_ids)):
        offset = zero_based_position % len(primary)
        rotated = primary[offset:] + primary[:offset]
        output.extend(RunKey(condition, question_id) for condition in rotated)
        output.append(RunKey("E7", question_id))
    return tuple(output)


def expected_suite_layout(repo_root: Path) -> dict[str, Any]:
    """Return the frozen 60-question/420-key/12-batch suite layout."""
    root = Path(repo_root).resolve()
    verify_formal_manifest(root)
    main = load_question_inputs(root, "main-40")
    extension = _load_extension_questions(root)
    if len(main) != MAIN_QUESTION_COUNT or len(extension) != EXTENSION_QUESTION_COUNT:
        raise EvidenceValidationError("Model 2 suite question counts differ")

    main_ids = tuple(item.question_id for item in main)
    extension_ids = tuple(item.question_id for item in extension)
    question_ids = main_ids + extension_ids
    if len(question_ids) != SUITE_QUESTION_COUNT or len(set(question_ids)) != len(question_ids):
        raise EvidenceValidationError("Model 2 suite questions are not 60 unique IDs")

    composition = _read_json(
        root
        / "experiments/locomo-conv50-v1/question-sets-main60-v2/main-60-composition.json"
    )
    rows = composition.get("question_order")
    if not isinstance(rows, list) or len(rows) != SUITE_QUESTION_COUNT:
        raise EvidenceValidationError("main-60 composition has the wrong size")
    if [row.get("global_position") for row in rows] != list(range(1, 61)):
        raise EvidenceValidationError("main-60 global positions differ")
    if tuple(row.get("question_id") for row in rows) != question_ids:
        raise EvidenceValidationError("main-60 question order differs")

    global_order = _global_execution_order(question_ids)
    main_order = global_order[: MAIN_QUESTION_COUNT * len(CONDITION_IDS)]
    extension_order = global_order[MAIN_QUESTION_COUNT * len(CONDITION_IDS) :]
    formal = _read_json(root / FORMAL_MANIFEST_RELATIVE_PATH)
    formal_main_order = tuple(
        RunKey(value["condition_id"], value["question_id"])
        for value in formal["question_set"]["execution_order"]
    )
    if main_order != formal_main_order:
        raise EvidenceValidationError("Model 2 main-40 order differs from formal-v1")
    if extension_order != extension_execution_order(extension_ids):
        raise EvidenceValidationError("Model 2 extension order does not continue offset 40")
    if len(global_order) != SUITE_RECORD_COUNT or len(set(global_order)) != SUITE_RECORD_COUNT:
        raise EvidenceValidationError("Model 2 suite does not contain 420 unique keys")

    batches: list[dict[str, Any]] = []
    for index in range(SUITE_BATCH_COUNT):
        question_start = index * QUESTION_BLOCK_SIZE
        question_stop = question_start + QUESTION_BLOCK_SIZE
        record_start = index * RECORDS_PER_BATCH
        record_stop = record_start + RECORDS_PER_BATCH
        records = global_order[record_start:record_stop]
        child = "main40" if index < 8 else "extension20"
        local_batch = index + 1 if child == "main40" else index - 7
        batches.append(
            {
                "suite_batch_id": f"B{index + 1:02d}",
                "child": child,
                "child_batch_id": f"B{local_batch:02d}",
                "global_question_positions": [question_start + 1, question_stop],
                "question_ids": list(question_ids[question_start:question_stop]),
                "record_count": len(records),
                "keys": [key.to_dict() for key in records],
            }
        )

    return {
        "question_ids": list(question_ids),
        "main_question_ids": list(main_ids),
        "extension_question_ids": list(extension_ids),
        "execution_order": [key.to_dict() for key in global_order],
        "execution_order_sha256": sha256_bytes(
            canonical_json_bytes([key.to_dict() for key in global_order])
        ),
        "batches": batches,
    }


def _resume_projection_checks(order: Sequence[RunKey]) -> dict[str, bool]:
    """Project every batch checkpoint and prove resume cannot duplicate a key."""
    keys = tuple(order)
    checks: dict[str, bool] = {}
    for boundary in range(0, len(keys) + 1, RECORDS_PER_BATCH):
        completed = keys[:boundary]
        pending = keys[boundary:]
        checks[f"completed_{boundary}"] = (
            len(set(completed)) == len(completed)
            and len(set(pending)) == len(pending)
            and set(completed).isdisjoint(pending)
            and completed + pending == keys
        )
    return checks


def build_offline_dry_run_report(
    *,
    repo_root: Path,
    requested_model_alias: str,
    required_served_model: str,
    preflight_report_sha256: str,
) -> dict[str, Any]:
    """Validate the frozen repository contract without constructing a provider."""
    if requested_model_alias != MODEL2_REQUESTED_MODEL_ALIAS:
        raise EvidenceValidationError("Model 2 requested alias must be x-test-2")
    if not isinstance(required_served_model, str) or not required_served_model.strip():
        raise EvidenceValidationError("Model 2 required served model is empty")
    _require_sha256(preflight_report_sha256, "preflight_report_sha256")

    root = Path(repo_root).resolve()
    layout = expected_suite_layout(root)
    order = tuple(RunKey(**item) for item in layout["execution_order"])
    formal = _read_json(root / FORMAL_MANIFEST_RELATIVE_PATH)
    condition_counts = {
        condition: sum(key.condition_id == condition for key in order)
        for condition in CONDITION_IDS
    }
    e7_dependencies = {
        question_id: (
            next(i for i, key in enumerate(order) if key == RunKey("E7", question_id))
            > next(i for i, key in enumerate(order) if key == RunKey("E2", question_id))
            and next(i for i, key in enumerate(order) if key == RunKey("E7", question_id))
            > next(i for i, key in enumerate(order) if key == RunKey("E6", question_id))
        )
        for question_id in layout["question_ids"]
    }
    resume_checks = _resume_projection_checks(order)

    # The schema itself forbids character-level truncation.  This probe also
    # guards against accidentally relaxing BudgetRecord in a later refactor.
    whole_item_schema_enforced = False
    try:
        BudgetRecord(
            unit="characters",
            tokenizer=None,
            limit=FORMAL_EVIDENCE_BUDGET_LIMIT,
            used=1,
            skipped_items=1,
            truncated=True,
        )
    except EvidenceValidationError:
        whole_item_schema_enforced = True

    checks = {
        "questions_60_unique": len(layout["question_ids"])
        == len(set(layout["question_ids"]))
        == SUITE_QUESTION_COUNT,
        "main40_extension20_split_exact": (
            len(layout["main_question_ids"]) == MAIN_QUESTION_COUNT
            and len(layout["extension_question_ids"]) == EXTENSION_QUESTION_COUNT
        ),
        "run_plan_420_unique_keys": len(order) == len(set(order)) == SUITE_RECORD_COUNT,
        "conditions_60_each": set(condition_counts.values()) == {SUITE_QUESTION_COUNT},
        "twelve_batches_of_35": (
            len(layout["batches"]) == SUITE_BATCH_COUNT
            and all(batch["record_count"] == RECORDS_PER_BATCH for batch in layout["batches"])
        ),
        "suite_batches_map_to_8_plus_4_child_batches": (
            [batch["child"] for batch in layout["batches"]]
            == ["main40"] * 8 + ["extension20"] * 4
            and [batch["child_batch_id"] for batch in layout["batches"]]
            == [f"B{i:02d}" for i in range(1, 9)]
            + [f"B{i:02d}" for i in range(1, 5)]
        ),
        "condition_offset_order_exact": (
            order
            == _global_execution_order(tuple(layout["question_ids"]))
            and order[MAIN_QUESTION_COUNT * 7].condition_id == "E5"
        ),
        "e7_after_e2_e6_for_every_question": all(e7_dependencies.values()),
        "e7_no_retrieval_contract": (
            FUSION_CONTRACT["inputs"] == ["E2", "E6"]
            and FUSION_CONTRACT["search"] == "none-reuse-upstream-evidence"
            and formal["e7_fusion"]["contract_sha256"] == FUSION_CONTRACT_SHA256
        ),
        "evidence_budget_16000_characters": (
            FORMAL_EVIDENCE_BUDGET_UNIT == "characters"
            and FORMAL_EVIDENCE_BUDGET_LIMIT == 16_000
            and formal["retrieval"]["evidence_budget"]
            == {
                "unit": "characters",
                "single_source_limit": 16_000,
                "e7_per_source_limit": 16_000,
                "e7_total_limit": 32_000,
            }
        ),
        "whole_item_budget_schema_enforced": whole_item_schema_enforced,
        "r1_round_caps_frozen": (
            R1_ROUND_CAP_BY_CONDITION == {"E1": 20, "E3": 20, "E5": 40}
            and dict(R1_ROUND_LIMIT_BY_STORE) == {"s1": 20, "s2": 20, "s3": 40}
            and formal["retrieval"]["r1"]["round_cap_by_condition"]
            == R1_ROUND_CAP_BY_CONDITION
        ),
        "r2_r3_action_caps_frozen": (
            int(R2_PARAMETERS["agent_action_cap"]) == R2_ACTION_CAP
            and int(R3_PARAMETERS["agent_action_cap"]) == R3_ACTION_CAP
            and formal["retrieval"]["r2"]["action_cap"] == R2_ACTION_CAP
            and formal["retrieval"]["r3"]["action_cap"] == R3_ACTION_CAP
        ),
        "expected_model_identity_bound": (
            requested_model_alias == MODEL2_REQUESTED_MODEL_ALIAS
            and bool(required_served_model.strip())
            and bool(preflight_report_sha256)
        ),
        "checkpoint_resume_without_duplicates": all(resume_checks.values()),
        "api_provider_not_constructed": True,
        "semantic_gold_not_loaded": True,
        "judge_not_constructed": True,
        "formal_answers_not_generated": True,
    }
    body = {
        "schema_version": 1,
        "protocol_version": MODEL2_VALIDATION_PROTOCOL_VERSION,
        "status": "passed" if all(checks.values()) else "failed",
        "checks": checks,
        "deployment": {
            "requested_model_alias": requested_model_alias,
            "required_served_model": required_served_model,
            "preflight_report_sha256": preflight_report_sha256,
        },
        "question_count": len(layout["question_ids"]),
        "planned_records": len(order),
        "condition_counts": condition_counts,
        "execution_order_sha256": layout["execution_order_sha256"],
        "batches": layout["batches"],
        "resume_projection_checks": resume_checks,
        "gold_boundary": {"semantic_records_loaded": False},
        "judge_boundary": {"judge_constructed": False},
        "api_boundary": {"provider_constructed": False},
    }
    return {
        "dry_run_id": "model2-dry-run-"
        + sha256_bytes(canonical_json_bytes(body)),
        **body,
    }


def write_offline_dry_run_report(
    *,
    repo_root: Path,
    output_path: Path,
    requested_model_alias: str,
    required_served_model: str,
    preflight_report_sha256: str,
) -> dict[str, Any]:
    report = build_offline_dry_run_report(
        repo_root=repo_root,
        requested_model_alias=requested_model_alias,
        required_served_model=required_served_model,
        preflight_report_sha256=preflight_report_sha256,
    )
    _publish_idempotent(Path(output_path).resolve(), report)
    if report["status"] != "passed":
        raise EvidenceValidationError("Model 2 offline dry-run failed")
    return report


def run_prepared_suite_dry_run(
    *,
    repo_root: Path,
    output_root: Path,
    suite_id: str,
) -> dict[str, Any]:
    """Validate a prepared ``formal_v2_model2`` suite before any answer work.

    Imports of the suite and preflight modules are local so this provider-free
    validator remains independent of their CLIs and environment handling.
    """
    from .formal_v2_model2 import open_suite
    from .model2_preflight import verify_sanitized_preflight_artifact

    root = Path(repo_root).resolve()
    suite = open_suite(repo_root=root, output_root=output_root, suite_id=suite_id)
    deployment = suite.manifest.get("deployment")
    if not isinstance(deployment, Mapping):
        raise EvidenceValidationError("Prepared suite deployment is missing")
    bound_preflight = suite.manifest.get("preflight_artifacts")
    if (
        not isinstance(bound_preflight, Mapping)
        or set(bound_preflight) != {"models_check", "role_smoke"}
    ):
        raise EvidenceValidationError("Prepared suite preflight pair is missing")

    verified_preflight: dict[str, dict[str, Any]] = {}
    verified_hashes: dict[str, str] = {}
    for name in ("models_check", "role_smoke"):
        specification = bound_preflight.get(name)
        if not isinstance(specification, Mapping):
            raise EvidenceValidationError("Prepared suite preflight binding differs")
        relative = specification.get("relative_path")
        if (
            not isinstance(relative, str)
            or Path(relative).is_absolute()
            or ".." in Path(relative).parts
        ):
            raise EvidenceValidationError("Prepared suite preflight path is unsafe")
        artifact_path = suite.suite_root / relative
        artifact_hash = _file_sha256(artifact_path)
        if artifact_hash != specification.get("sha256"):
            raise EvidenceValidationError("Prepared suite preflight hash differs")
        verified_hashes[name] = artifact_hash
        verified_preflight[name] = verify_sanitized_preflight_artifact(
            artifact_path
        )
        if verified_preflight[name] != specification.get("summary"):
            raise EvidenceValidationError(
                "Prepared suite preflight summary differs"
            )

    preflight_summary = verified_preflight["role_smoke"]
    models_summary = verified_preflight["models_check"]
    preflight_sha256 = verified_hashes["role_smoke"]
    base = build_offline_dry_run_report(
        repo_root=root,
        requested_model_alias=str(deployment.get("requested_model_alias", "")),
        required_served_model=str(deployment.get("required_served_model", "")),
        preflight_report_sha256=preflight_sha256,
    )
    layout = expected_suite_layout(root)

    schedule_rows = suite.manifest.get("global_schedule")
    if not isinstance(schedule_rows, list):
        raise EvidenceValidationError("Prepared suite global schedule is missing")
    schedule_keys = [
        {"condition_id": row.get("condition_id"), "question_id": row.get("question_id")}
        for row in schedule_rows
    ]
    expected_batches = layout["batches"]
    actual_batches = suite.manifest.get("batch_map")
    if not isinstance(actual_batches, list):
        raise EvidenceValidationError("Prepared suite batch map is missing")

    main_checkpoint = suite.main_store.checkpoint()
    extension_checkpoint = suite.extension_store.checkpoint()
    main_pending = [key.to_dict() for key in suite.main_store.pending_keys()]
    extension_pending = [key.to_dict() for key in suite.extension_store.pending_keys()]
    manifest_invariants = suite.manifest.get("experimental_invariants", {})

    integration_checks = {
        "suite_manifest_content_address_verified": True,
        "preflight_role_smokes_verified": (
            preflight_summary.get("verified") is True
            and preflight_summary.get("requested_alias")
            == deployment.get("requested_model_alias")
            and preflight_summary.get("served_model")
            == deployment.get("required_served_model")
            and preflight_summary.get("role_smokes_passed") == 5
            and deployment.get("preflight_report_sha256") == preflight_sha256
            and models_summary.get("verified") is True
            and models_summary.get("artifact_type") == "model2-models-check"
            and models_summary.get("requested_alias")
            == deployment.get("requested_model_alias")
            and models_summary.get("alias_present") is True
            and models_summary.get("context_limit") == 1_048_576
            and deployment.get("models_check_report_sha256")
            == verified_hashes["models_check"]
        ),
        "suite_schedule_matches_global_420_order": (
            schedule_keys == layout["execution_order"]
            and [row.get("global_sequence") for row in schedule_rows]
            == list(range(1, SUITE_RECORD_COUNT + 1))
        ),
        "suite_batch_map_matches_twelve_blocks": (
            len(actual_batches) == SUITE_BATCH_COUNT
            and [row.get("batch_id") for row in actual_batches]
            == [f"B{i:02d}" for i in range(1, 13)]
            and [row.get("child_id") for row in actual_batches]
            == ["main40"] * 8 + ["extension20"] * 4
            and [row.get("child_local_batch") for row in actual_batches]
            == list(range(1, 9)) + list(range(1, 5))
            and [row.get("question_ids") for row in actual_batches]
            == [batch["question_ids"] for batch in expected_batches]
            and all(row.get("record_count") == RECORDS_PER_BATCH for row in actual_batches)
        ),
        "child_plans_are_physically_split_280_plus_140": (
            len(suite.main_store.plan.execution_order) == 280
            and len(suite.extension_store.plan.execution_order) == 140
            and [key.to_dict() for key in suite.main_store.plan.execution_order]
            == layout["execution_order"][:280]
            and [key.to_dict() for key in suite.extension_store.plan.execution_order]
            == layout["execution_order"][280:]
        ),
        "empty_child_checkpoints_exact": (
            main_checkpoint["planned"] == 280
            and main_checkpoint["completed"] == 0
            and main_checkpoint["failed_attempts"] == 0
            and main_checkpoint["pending"] == 280
            and extension_checkpoint["planned"] == 140
            and extension_checkpoint["completed"] == 0
            and extension_checkpoint["failed_attempts"] == 0
            and extension_checkpoint["pending"] == 140
        ),
        "checkpoint_pending_order_exact": (
            main_pending == layout["execution_order"][:280]
            and extension_pending == layout["execution_order"][280:]
        ),
        "manifest_budget_caps_and_e7_exact": (
            manifest_invariants.get("evidence_budget")
            == {
                "unit": "characters",
                "single_source_limit": 16_000,
                "e7_per_source_limit": 16_000,
                "e7_total_limit": 32_000,
            }
            and manifest_invariants.get("r1_round_cap")
            == R1_ROUND_CAP_BY_CONDITION
            and manifest_invariants.get("r2_action_cap") == R2_ACTION_CAP
            and manifest_invariants.get("r3_action_cap") == R3_ACTION_CAP
            and manifest_invariants.get("e7_retrieval")
            == "reuse same-run E2 and E6 bundles; no new search or LLM"
        ),
        "answer_run_boundaries_exact": (
            manifest_invariants.get("semantic_gold_access")
            == "forbidden during answer run"
            and manifest_invariants.get("judge_calls")
            == "forbidden during answer run"
            and manifest_invariants.get("configuration_overrides") == "forbidden"
        ),
        "separate_child_roots": suite.main_store.run_root
        != suite.extension_store.run_root,
    }
    checks = {**base["checks"], **integration_checks}
    body = {
        "schema_version": 1,
        "protocol_version": MODEL2_VALIDATION_PROTOCOL_VERSION,
        "suite_id": suite_id,
        "suite_manifest_id": suite.manifest["suite_manifest_id"],
        "status": "passed" if all(checks.values()) else "failed",
        "checks": checks,
        "deployment": dict(deployment),
        "preflight": dict(preflight_summary),
        "question_count": SUITE_QUESTION_COUNT,
        "planned_records": SUITE_RECORD_COUNT,
        "condition_counts": base["condition_counts"],
        "execution_order_sha256": layout["execution_order_sha256"],
        "batch_count": SUITE_BATCH_COUNT,
        "records_per_batch": RECORDS_PER_BATCH,
        "child_checkpoints": {
            "main40": main_checkpoint,
            "extension20": extension_checkpoint,
        },
        "resume_projection_checks": base["resume_projection_checks"],
        "api_boundary": {"provider_constructed": False, "calls": 0},
        "answer_boundary": {"records_generated": 0},
        "gold_boundary": {"semantic_records_loaded": False},
        "judge_boundary": {"judge_constructed": False, "calls": 0},
    }
    report = {
        "dry_run_id": "model2-suite-dry-run-"
        + sha256_bytes(canonical_json_bytes(body)),
        **body,
    }
    _publish_idempotent(suite.suite_root / MODEL2_OFFLINE_REPORT_NAME, report)
    if report["status"] != "passed":
        raise EvidenceValidationError("Prepared Model 2 suite dry-run checks failed")
    return report


def _pilot_gate_contract() -> dict[str, Any]:
    return {
        "planned_records": PILOT_RECORD_COUNT,
        "condition_records_each": PILOT_QUESTION_COUNT,
        "active_failed_keys": 0,
        "next_key": None,
        "retrieval_system_failure_rate_lt": SYSTEM_FAILURE_RATE_LIMIT,
        "answer_system_failure_rate_lt": SYSTEM_FAILURE_RATE_LIMIT,
        "budget_skipped_episode_fraction_lt": BUDGET_SKIP_EPISODE_FRACTION_LIMIT,
        "empty_evidence_bundles": 0,
        "token_safety_fuse_limit": TOKEN_SAFETY_FUSE_LIMIT,
        "token_safety_fuse_hits": 0,
        "citations_valid": True,
        "stores_unchanged": True,
        "e2_e4_fixed_query_top5_backend_invariant": True,
        "whole_item_budget_only": True,
        "e7_retrieval_calls": 0,
        "e7_records": PILOT_QUESTION_COUNT,
        "e7_per_source_budget": FORMAL_EVIDENCE_BUDGET_LIMIT,
        "e7_total_budget": 2 * FORMAL_EVIDENCE_BUDGET_LIMIT,
        "e7_cost_rule_verified": True,
        "r1_round_cap_by_condition": dict(R1_ROUND_CAP_BY_CONDITION),
        "r2_action_cap": R2_ACTION_CAP,
        "r3_action_cap": R3_ACTION_CAP,
        "runtime_metrics_complete": True,
    }


def prepare_model2_pilot(
    *,
    repo_root: Path,
    output_root: Path,
    run_id: str,
    required_served_model: str,
    preflight_report_path: Path,
    preflight_report_sha256: str,
    requested_model_alias: str = MODEL2_REQUESTED_MODEL_ALIAS,
) -> Path:
    """Plan an empty 42-key pilot; never call a provider or start execution."""
    if requested_model_alias != MODEL2_REQUESTED_MODEL_ALIAS:
        raise EvidenceValidationError("Model 2 pilot alias must be x-test-2")
    if not isinstance(required_served_model, str) or not required_served_model.strip():
        raise EvidenceValidationError("Model 2 pilot served model is empty")
    expected_preflight_sha = _require_sha256(
        preflight_report_sha256, "preflight_report_sha256"
    )
    if _file_sha256(Path(preflight_report_path).resolve()) != expected_preflight_sha:
        raise EvidenceValidationError("Model 2 preflight artifact hash differs")

    root = Path(repo_root).resolve()
    formal_verification = verify_formal_manifest(root)
    formal = _read_json(root / FORMAL_MANIFEST_RELATIVE_PATH)
    questions = load_question_inputs(root, "dev-6")
    if len(questions) != PILOT_QUESTION_COUNT:
        raise EvidenceValidationError("Model 2 pilot requires six dev questions")

    deployment_body = {
        "requested_model_alias": requested_model_alias,
        "required_served_model": required_served_model,
        "preflight_report_sha256": expected_preflight_sha,
        "identity_policy": "every-response-exact-match-fail-closed",
    }
    deployment_sha256 = sha256_bytes(canonical_json_bytes(deployment_body))
    plan = ExperimentRunPlan.create(
        schema_version=1,
        protocol_version=RUN_PLAN_PROTOCOL_VERSION,
        run_id=run_id,
        question_set_id=questions[0].question_set_id,
        question_ids=tuple(item.question_id for item in questions),
        condition_ids=CONDITION_IDS,
        execution_order=_global_execution_order(tuple(item.question_id for item in questions)),
        config_hashes={
            "formal_v1_manifest": _file_sha256(root / FORMAL_MANIFEST_RELATIVE_PATH),
            "formal_v1_core_files": formal["core_files_tree_sha256"],
            "preflight_report": expected_preflight_sha,
            "model2_deployment": deployment_sha256,
            "answerer_prompt": formal["answerer"]["prompt_sha256"],
            "fusion_contract": formal["e7_fusion"]["contract_sha256"],
            "r1_limits": formal["retrieval"]["r1"]["limits_sha256"],
            "r2_protocol_parent": formal["retrieval"]["r2"]["protocol_sha256"],
            "r3_protocol_parent": formal["retrieval"]["r3"]["protocol_sha256"],
            "s1_tree": formal["stores"]["s1"]["tree_sha256"],
            "s2_tree": formal["stores"]["s2"]["tree_sha256"],
            "s3_tree": formal["stores"]["s3"]["tree_sha256"],
        },
    )
    store = ExperimentRunStore.create_or_open(Path(output_root).resolve(), plan)
    checkpoint = store.checkpoint()
    if checkpoint["completed"] or checkpoint["failed_attempts"]:
        raise EvidenceValidationError("Model 2 pilot planning requires an empty run")

    body = {
        "schema_version": 1,
        "protocol_version": MODEL2_PILOT_PROTOCOL_VERSION,
        "status": "prepared-not-started",
        "run_id": run_id,
        "plan_id": plan.plan_id,
        "formal_manifest_id": formal_verification["formal_manifest_id"],
        "deployment": deployment_body,
        "deployment_contract_sha256": deployment_sha256,
        "preflight_artifact": {
            "path": str(Path(preflight_report_path).resolve()),
            "sha256": expected_preflight_sha,
        },
        "question_set_id": plan.question_set_id,
        "question_count": PILOT_QUESTION_COUNT,
        "condition_ids": list(CONDITION_IDS),
        "planned_records": PILOT_RECORD_COUNT,
        "execution_order": [key.to_dict() for key in plan.execution_order],
        "execution_order_sha256": sha256_bytes(
            canonical_json_bytes([key.to_dict() for key in plan.execution_order])
        ),
        "evidence_budget": {
            "unit": "characters",
            "single_source_limit": 16_000,
            "whole_items_only": True,
            "e7_per_source_limit": 16_000,
            "e7_total_limit": 32_000,
        },
        "caps": {
            "r1_round_cap_by_condition": dict(R1_ROUND_CAP_BY_CONDITION),
            "r2_action_cap": R2_ACTION_CAP,
            "r3_action_cap": R3_ACTION_CAP,
        },
        "e7": {
            "inputs": ["E2", "E6"],
            "retrieval": "none-reuse-upstream-evidence",
            "contract_sha256": FUSION_CONTRACT_SHA256,
        },
        "go_no_go_contract": _pilot_gate_contract(),
        "gold_access_policy": "semantic gold forbidden during pilot execution",
        "judge_policy": "forbidden",
        "api_calls_made_by_prepare": 0,
        "answers_generated_by_prepare": 0,
    }
    manifest = {
        "pilot_manifest_id": "model2-pilot-manifest-"
        + sha256_bytes(canonical_json_bytes(body)),
        **body,
    }
    path = store.run_root / MODEL2_PILOT_MANIFEST_NAME
    _publish_idempotent(path, manifest)
    return path


def _require_nonnegative_int(metrics: Mapping[str, Any], key: str) -> int:
    value = metrics.get(key)
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise EvidenceValidationError(f"Pilot metric {key} must be a nonnegative integer")
    return value


def evaluate_model2_pilot_gate(
    *,
    output_root: Path,
    run_id: str,
    metrics: Mapping[str, Any],
) -> dict[str, Any]:
    """Evaluate preregistered operational gates from sanitized pilot metrics.

    This function does not inspect answers or gold.  ``metrics`` must come from
    a separate completed-pilot audit that has already verified every record.
    """
    if not isinstance(metrics, Mapping):
        raise EvidenceValidationError("Pilot metrics must be an object")
    store_root = Path(output_root).resolve()
    # Parse the serialized plan through the canonical identity verifier before
    # inspecting any checkpoint or metric supplied by the pilot audit.
    serialized_plan = _read_json(store_root / run_id / "plan.json")
    run_plan_from_mapping(serialized_plan)
    store, checkpoint = verify_run_store(store_root, run_id)
    manifest = _read_json(store.run_root / MODEL2_PILOT_MANIFEST_NAME)
    if manifest.get("plan_id") != store.plan.plan_id:
        raise EvidenceValidationError("Pilot manifest and plan differ")
    completed_by_condition = metrics.get("completed_by_condition")
    if not isinstance(completed_by_condition, Mapping):
        raise EvidenceValidationError("Pilot completed_by_condition is missing")
    requested_aliases = metrics.get("requested_model_aliases")
    served_models = metrics.get("served_models")
    if not isinstance(requested_aliases, list) or not isinstance(served_models, list):
        raise EvidenceValidationError("Pilot model identity metrics are missing")

    retrieval_attempts = _require_nonnegative_int(metrics, "retrieval_attempts")
    retrieval_failures = _require_nonnegative_int(
        metrics, "retrieval_system_failure_attempts"
    )
    answer_attempts = _require_nonnegative_int(metrics, "answer_attempts")
    answer_failures = _require_nonnegative_int(metrics, "answer_system_failure_attempts")
    if retrieval_attempts < RETRIEVAL_EPISODES_PER_PILOT or answer_attempts < PILOT_RECORD_COUNT:
        raise EvidenceValidationError("Pilot attempt denominators are incomplete")
    retrieval_failure_rate = retrieval_failures / retrieval_attempts
    answer_failure_rate = answer_failures / answer_attempts
    skipped_episodes = _require_nonnegative_int(metrics, "budget_skipped_episode_count")
    retrieval_episodes = _require_nonnegative_int(metrics, "retrieval_episode_count")
    if retrieval_episodes != RETRIEVAL_EPISODES_PER_PILOT:
        raise EvidenceValidationError("Pilot retrieval episode denominator differs")
    budget_skip_fraction = skipped_episodes / retrieval_episodes

    required_served = manifest["deployment"]["required_served_model"]
    checks = {
        "records_42_complete": (
            metrics.get("planned_records") == PILOT_RECORD_COUNT
            and metrics.get("completed_records") == PILOT_RECORD_COUNT
            and checkpoint["planned"] == PILOT_RECORD_COUNT
            and checkpoint["completed"] == PILOT_RECORD_COUNT
            and checkpoint["pending"] == 0
        ),
        "conditions_6_each": dict(completed_by_condition)
        == {condition: PILOT_QUESTION_COUNT for condition in CONDITION_IDS},
        "no_active_failures": (
            metrics.get("active_failed_keys") == 0 and metrics.get("next_key") is None
        ),
        "requested_alias_exact": set(requested_aliases)
        == {MODEL2_REQUESTED_MODEL_ALIAS},
        "served_model_exact": set(served_models) == {required_served},
        "retrieval_failure_rate_lt_5_percent": retrieval_failure_rate
        < SYSTEM_FAILURE_RATE_LIMIT,
        "answer_failure_rate_lt_5_percent": answer_failure_rate
        < SYSTEM_FAILURE_RATE_LIMIT,
        "citations_valid": metrics.get("citations_valid") is True,
        "stores_unchanged": metrics.get("stores_unchanged") is True,
        "e2_e4_top5_backend_invariant": metrics.get(
            "e2_e4_fixed_query_top5_backend_invariant"
        )
        is True,
        "budget_skip_fraction_lt_20_percent": budget_skip_fraction
        < BUDGET_SKIP_EPISODE_FRACTION_LIMIT,
        "no_empty_evidence_bundles": metrics.get("empty_evidence_bundles") == 0,
        "token_safety_fuse_not_hit": (
            metrics.get("token_safety_fuse_hits") == 0
            and int(metrics.get("max_retrieval_episode_total_tokens", -1))
            < TOKEN_SAFETY_FUSE_LIMIT
        ),
        "caps_exact": (
            metrics.get("r1_round_cap_by_condition") == R1_ROUND_CAP_BY_CONDITION
            and metrics.get("r2_action_cap") == R2_ACTION_CAP
            and metrics.get("r3_action_cap") == R3_ACTION_CAP
        ),
        "runtime_metrics_complete": all(
            metrics.get(key) is True
            for key in (
                "cap_metrics_complete",
                "compaction_metrics_complete",
                "answer_repair_metrics_complete",
            )
        ),
        "whole_item_budget_only": (
            metrics.get("truncated_evidence_items") == 0
            and metrics.get("evidence_bundles_with_wrong_budget") == 0
        ),
        "e7_no_retrieval": (
            metrics.get("e7_records") == PILOT_QUESTION_COUNT
            and metrics.get("e7_retrieval_calls") == 0
            and metrics.get("e7_source_model_mismatches") == 0
        ),
        "e7_budget_and_cost_exact": (
            metrics.get("e7_per_source_budget_limit")
            == FORMAL_EVIDENCE_BUDGET_LIMIT
            and metrics.get("e7_total_budget_limit")
            == 2 * FORMAL_EVIDENCE_BUDGET_LIMIT
            and metrics.get("e7_cost_rule_verified") is True
        ),
        "semantic_gold_not_loaded": metrics.get("semantic_gold_loaded") is False,
        "judge_not_called": metrics.get("judge_calls") == 0,
    }
    body = {
        "schema_version": 1,
        "protocol_version": MODEL2_PILOT_PROTOCOL_VERSION,
        "run_id": run_id,
        "plan_id": store.plan.plan_id,
        "pilot_manifest_id": manifest["pilot_manifest_id"],
        "status": "passed" if all(checks.values()) else "failed",
        "checks": checks,
        "rates": {
            "retrieval_system_failure_rate": retrieval_failure_rate,
            "answer_system_failure_rate": answer_failure_rate,
            "budget_skipped_episode_fraction": budget_skip_fraction,
        },
        "evaluated_at": _now(),
    }
    report = {
        "pilot_gate_id": "model2-pilot-gate-"
        + sha256_bytes(canonical_json_bytes(body)),
        **body,
    }
    _write_atomic(store.run_root / MODEL2_PILOT_GATE_NAME, report)
    return report
