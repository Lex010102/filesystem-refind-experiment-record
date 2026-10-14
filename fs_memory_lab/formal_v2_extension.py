"""Formal Qwen runner for the append-only LoCoMo extension-20 set.

This module deliberately leaves ``formal-v1-main40`` untouched.  It reuses
the frozen formal-v1 stores, retrieval protocols, Answerer, budgets, caps and
Qwen deployment, while binding a separate 140-record run to positions 41--60
of ``main-60-v2``.  The execution-order rotation continues from global
position 41, so the extension is a valid slice of the combined 60-question
schedule rather than a new schedule reset at E1.

The runner never loads semantic gold and has no Judge entry point.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from .agent import ChatProvider, TransientProviderError
from .answerer import SharedAnswerer
from .evidence import (
    EvidenceBundle,
    EvidenceValidationError,
    QuestionInput,
    canonical_json_bytes,
    sha256_bytes,
)
from .formal_batch import (
    CONDITION_METHODS,
    _append_event,
    _exclusive_run_lock,
    _file_sha256,
    _load_retrieval_bundle,
    _provider_preflight,
    _publish_idempotent,
    _read_json,
    _safe_error,
    _validate_retrieval_bundle,
    _write_atomic,
)
from .formal_v1 import (
    FORMAL_API_STYLE,
    FORMAL_CONCURRENCY,
    FORMAL_EVIDENCE_BUDGET_LIMIT,
    FORMAL_EVIDENCE_BUDGET_UNIT,
    FORMAL_MANIFEST_RELATIVE_PATH,
    FORMAL_MAX_RESPONSE_BYTES,
    FORMAL_REQUESTED_MODEL_ALIAS,
    FORMAL_REQUEST_TIMEOUT_SECONDS,
    FORMAL_SERVED_MODEL,
    verify_formal_manifest,
)
from .fusion import FusionEvidenceBundle, build_e7_fusion_bundle
from .r1_inputs import load_r1_store
from .r1_runner import execute_r1_question
from .r2_inputs import build_r2_raw_corpus, preflight_r2_raw_inputs
from .r2_runner import execute_r2_question
from .r3_inputs import load_r3_corpus
from .r3_runner import execute_r3_question
from .run_records import (
    CONDITION_IDS,
    RUN_PLAN_PROTOCOL_VERSION,
    ExperimentRunPlan,
    ExperimentRunStore,
    RunKey,
    RunRecord,
    verify_run_store,
)


PROTOCOL_VERSION = "formal-v2-qwen-extension20-orchestrator-v1"
RUNNER_RELATIVE_PATH = "fs_memory_lab/formal_v2_extension.py"
FORMAL_BATCH_HELPER_RELATIVE_PATH = "fs_memory_lab/formal_batch.py"
QUESTION_DIR_RELATIVE_PATH = (
    "experiments/locomo-conv50-v1/question-sets-main60-v2"
)
QUESTION_INPUT_RELATIVE_PATH = f"{QUESTION_DIR_RELATIVE_PATH}/extension-20-input.jsonl"
QUESTION_GOLD_RELATIVE_PATH = f"{QUESTION_DIR_RELATIVE_PATH}/extension-20-gold.jsonl"
QUESTION_MANIFEST_RELATIVE_PATH = f"{QUESTION_DIR_RELATIVE_PATH}/manifest.json"
QUESTION_VERIFICATION_RELATIVE_PATH = f"{QUESTION_DIR_RELATIVE_PATH}/verification.json"
COMPOSITION_RELATIVE_PATH = f"{QUESTION_DIR_RELATIVE_PATH}/main-60-composition.json"

QUESTION_SET_ID = "locomo-conv50-extension20-v2"
QUESTION_COUNT = 20
GLOBAL_POSITION_OFFSET = 40
QUESTION_BLOCK_SIZE = 5
QUESTION_BLOCKS = 4
PLANNED_RECORDS = 140

QUESTION_INPUT_SHA256 = "8e9e27e8cec7768144ca48df3a7a5b63d6f29af1acfd482d73c0b04fd854a565"
QUESTION_GOLD_SHA256 = "c8b08771af27537579e418db0ace600076cd09108019fc86cd584740bb035ec8"
QUESTION_MANIFEST_SHA256 = "de37d2da62d781e72a2a16624041c481e39ab004159dee3d63b2fde764c222af"
QUESTION_VERIFICATION_SHA256 = "c82e93d6db62be4e0cd54164cee34e304c59be4b85f9ef78c4bc3b8920286594"
COMPOSITION_SHA256 = "c6f5452a8f7491cb9c1fd553f636352f45c4774d1efdd7d4a1ac8a19370f7acd"

RUN_MANIFEST_NAME = "formal-run-manifest.json"
DRY_RUN_NAME = "dry-run.json"
PRE_GOLD_AUDIT_NAME = "pre-gold-audit.json"

_SAFE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}\Z")
_COMMIT = re.compile(r"[0-9a-f]{40}\Z")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _load_extension_questions(repo_root: Path) -> tuple[QuestionInput, ...]:
    root = Path(repo_root).resolve()
    pinned = {
        QUESTION_INPUT_RELATIVE_PATH: QUESTION_INPUT_SHA256,
        # Gold is intentionally hashed as opaque bytes and never parsed here.
        QUESTION_GOLD_RELATIVE_PATH: QUESTION_GOLD_SHA256,
        QUESTION_MANIFEST_RELATIVE_PATH: QUESTION_MANIFEST_SHA256,
        QUESTION_VERIFICATION_RELATIVE_PATH: QUESTION_VERIFICATION_SHA256,
        COMPOSITION_RELATIVE_PATH: COMPOSITION_SHA256,
    }
    for relative, expected in pinned.items():
        if _file_sha256(root / relative) != expected:
            raise EvidenceValidationError(f"Pinned extension artifact differs: {relative}")

    manifest = _read_json(root / QUESTION_MANIFEST_RELATIVE_PATH)
    verification = _read_json(root / QUESTION_VERIFICATION_RELATIVE_PATH)
    if verification.get("status") != "passed":
        raise EvidenceValidationError("Frozen question-set verification is not passing")
    output = manifest.get("outputs", {}).get("extension_input")
    if not isinstance(output, Mapping) or output.get("sha256") != QUESTION_INPUT_SHA256:
        raise EvidenceValidationError("Extension input is not bound by its manifest")

    payload = (root / QUESTION_INPUT_RELATIVE_PATH).read_bytes()
    questions: list[QuestionInput] = []
    for line_number, raw_line in enumerate(payload.splitlines(), start=1):
        try:
            value = json.loads(raw_line.decode("utf-8"))
            question = QuestionInput.from_mapping(value)
        except (UnicodeError, json.JSONDecodeError, EvidenceValidationError) as exc:
            raise EvidenceValidationError(
                f"Extension question input line {line_number} is invalid"
            ) from exc
        questions.append(question)
    if len(questions) != QUESTION_COUNT:
        raise EvidenceValidationError("Extension question count differs")
    if tuple(item.run_position for item in questions) != tuple(range(1, 21)):
        raise EvidenceValidationError("Extension run positions are not contiguous")
    if len({item.question_id for item in questions}) != QUESTION_COUNT:
        raise EvidenceValidationError("Extension repeats a question ID")
    if any(item.question_set_id != QUESTION_SET_ID for item in questions):
        raise EvidenceValidationError("Extension question-set identity differs")

    composition = _read_json(root / COMPOSITION_RELATIVE_PATH)
    order = composition.get("question_order")
    if not isinstance(order, list) or len(order) != 60:
        raise EvidenceValidationError("main-60-v2 composition differs")
    extension_order = order[GLOBAL_POSITION_OFFSET:]
    if [item.get("global_position") for item in extension_order] != list(range(41, 61)):
        raise EvidenceValidationError("Extension global positions differ")
    if [item.get("question_id") for item in extension_order] != [
        item.question_id for item in questions
    ]:
        raise EvidenceValidationError("Extension order differs from composition")
    if any(item.get("source_question_set_id") != QUESTION_SET_ID for item in extension_order):
        raise EvidenceValidationError("Extension source identity differs in composition")
    return tuple(questions)


def _execution_order(question_ids: tuple[str, ...]) -> tuple[RunKey, ...]:
    """Return the main-60 execution-order slice for global positions 41--60."""
    primary = tuple(value for value in CONDITION_IDS if value != "E7")
    output: list[RunKey] = []
    for local_index, question_id in enumerate(question_ids):
        global_zero_based_index = GLOBAL_POSITION_OFFSET + local_index
        offset = global_zero_based_index % len(primary)
        rotated = primary[offset:] + primary[:offset]
        output.extend(RunKey(condition, question_id) for condition in rotated)
        output.append(RunKey("E7", question_id))
    return tuple(output)


def _plan(repo_root: Path, run_id: str) -> ExperimentRunPlan:
    root = Path(repo_root).resolve()
    formal_path = root / FORMAL_MANIFEST_RELATIVE_PATH
    formal = _read_json(formal_path)
    questions = _load_extension_questions(root)
    return ExperimentRunPlan.create(
        schema_version=1,
        protocol_version=RUN_PLAN_PROTOCOL_VERSION,
        run_id=run_id,
        question_set_id=QUESTION_SET_ID,
        question_ids=tuple(item.question_id for item in questions),
        condition_ids=CONDITION_IDS,
        execution_order=_execution_order(tuple(item.question_id for item in questions)),
        config_hashes={
            "formal_v1_manifest": _file_sha256(formal_path),
            "formal_v1_core_files": formal["core_files_tree_sha256"],
            "extension_input": QUESTION_INPUT_SHA256,
            "extension_manifest": QUESTION_MANIFEST_SHA256,
            "extension_verification": QUESTION_VERIFICATION_SHA256,
            "main60_composition": COMPOSITION_SHA256,
            "answerer_prompt": formal["answerer"]["prompt_sha256"],
            "fusion_contract": formal["e7_fusion"]["contract_sha256"],
            "r1_limits": formal["retrieval"]["r1"]["limits_sha256"],
            "r2_protocol": formal["retrieval"]["r2"]["protocol_sha256"],
            "r3_protocol": formal["retrieval"]["r3"]["protocol_sha256"],
            "s1_tree": formal["stores"]["s1"]["tree_sha256"],
            "s2_tree": formal["stores"]["s2"]["tree_sha256"],
            "s3_tree": formal["stores"]["s3"]["tree_sha256"],
        },
    )


def _manifest_body(
    *, repo_root: Path, plan: ExperimentRunPlan, implementation_commit: str
) -> dict[str, Any]:
    root = Path(repo_root).resolve()
    formal_path = root / FORMAL_MANIFEST_RELATIVE_PATH
    formal = _read_json(formal_path)
    questions = _load_extension_questions(root)
    blocks = [
        [item.question_id for item in questions[start : start + QUESTION_BLOCK_SIZE]]
        for start in range(0, QUESTION_COUNT, QUESTION_BLOCK_SIZE)
    ]
    return {
        "schema_version": 1,
        "protocol_version": PROTOCOL_VERSION,
        "status": "prepared",
        "run_id": plan.run_id,
        "plan_id": plan.plan_id,
        "implementation_git_commit": implementation_commit,
        "runner_relative_path": RUNNER_RELATIVE_PATH,
        "runner_sha256": _file_sha256(root / RUNNER_RELATIVE_PATH),
        "formal_batch_helper_relative_path": FORMAL_BATCH_HELPER_RELATIVE_PATH,
        "formal_batch_helper_sha256": _file_sha256(
            root / FORMAL_BATCH_HELPER_RELATIVE_PATH
        ),
        "parent_formal_manifest_id": formal["formal_manifest_id"],
        "parent_formal_manifest_sha256": _file_sha256(formal_path),
        "question_set": {
            "question_set_id": QUESTION_SET_ID,
            "question_count": QUESTION_COUNT,
            "global_positions": [41, 60],
            "input_relative_path": QUESTION_INPUT_RELATIVE_PATH,
            "input_sha256": QUESTION_INPUT_SHA256,
            "gold_relative_path": QUESTION_GOLD_RELATIVE_PATH,
            "gold_sha256": QUESTION_GOLD_SHA256,
            "manifest_relative_path": QUESTION_MANIFEST_RELATIVE_PATH,
            "manifest_sha256": QUESTION_MANIFEST_SHA256,
            "verification_sha256": QUESTION_VERIFICATION_SHA256,
            "composition_sha256": COMPOSITION_SHA256,
            "question_order": [item.question_id for item in questions],
        },
        "condition_ids": list(CONDITION_IDS),
        "planned_records": PLANNED_RECORDS,
        "execution_order_policy": (
            "main60-question-major-rotated-e1-e6-then-e7-slice-global-41-60"
        ),
        "execution_order": [item.to_dict() for item in plan.execution_order],
        "execution_order_sha256": sha256_bytes(
            canonical_json_bytes([item.to_dict() for item in plan.execution_order])
        ),
        "evidence_budget": {
            "unit": FORMAL_EVIDENCE_BUDGET_UNIT,
            "limit": FORMAL_EVIDENCE_BUDGET_LIMIT,
            "e7_per_source_limit": FORMAL_EVIDENCE_BUDGET_LIMIT,
            "e7_total_limit": 2 * FORMAL_EVIDENCE_BUDGET_LIMIT,
        },
        "deployment": {
            "requested_model_alias": FORMAL_REQUESTED_MODEL_ALIAS,
            "required_served_model": FORMAL_SERVED_MODEL,
            "api_style": FORMAL_API_STYLE,
            "request_timeout_seconds": FORMAL_REQUEST_TIMEOUT_SECONDS,
            "max_response_bytes": FORMAL_MAX_RESPONSE_BYTES,
            "concurrency": FORMAL_CONCURRENCY,
        },
        "question_blocks": blocks,
        "block_size": QUESTION_BLOCK_SIZE,
        "execution_control": {
            "through_block_required_per_run_invocation": True,
            "allowed_blocks": list(range(1, QUESTION_BLOCKS + 1)),
            "semantics": "scheduling-only; no experimental parameter overrides",
        },
        "stop_on_failure": True,
        "resume_policy": (
            "explicit-new-invocation-revalidates-and-skips-only-completed-records"
        ),
        "gold_access_policy": "semantic gold is not loaded by this runner",
        "judge_policy": "forbidden-in-extension-answer-run",
        "configuration_overrides": "forbidden",
    }


def prepare_run(
    *, repo_root: Path, output_root: Path, run_id: str, implementation_commit: str
) -> Path:
    if _SAFE.fullmatch(run_id) is None:
        raise EvidenceValidationError("Extension run_id is unsafe")
    if _COMMIT.fullmatch(implementation_commit) is None:
        raise EvidenceValidationError("Implementation commit must be a full Git SHA")
    root = Path(repo_root).resolve()
    verify_formal_manifest(root)
    _load_extension_questions(root)
    plan = _plan(root, run_id)
    store = ExperimentRunStore.create_or_open(Path(output_root).resolve(), plan)
    body = _manifest_body(
        repo_root=root, plan=plan, implementation_commit=implementation_commit
    )
    manifest = {
        "formal_run_manifest_id": "formal-run-"
        + sha256_bytes(canonical_json_bytes(body)),
        **body,
    }
    path = store.run_root / RUN_MANIFEST_NAME
    _publish_idempotent(path, manifest)
    _append_event(
        store.run_root / "events.jsonl",
        {
            "event": "formal_run_prepared",
            "at": _now(),
            "formal_run_manifest_id": manifest["formal_run_manifest_id"],
        },
    )
    write_status(repo_root=root, output_root=output_root, run_id=run_id)
    return path


def _open_run(
    *, repo_root: Path, output_root: Path, run_id: str
) -> tuple[ExperimentRunStore, dict[str, Any], dict[str, Any]]:
    root = Path(repo_root).resolve()
    formal_verification = verify_formal_manifest(root)
    _load_extension_questions(root)
    store, _ = verify_run_store(Path(output_root).resolve(), run_id)
    manifest = _read_json(store.run_root / RUN_MANIFEST_NAME)
    identity = manifest.get("formal_run_manifest_id")
    body = {key: value for key, value in manifest.items() if key != "formal_run_manifest_id"}
    if identity != "formal-run-" + sha256_bytes(canonical_json_bytes(body)):
        raise EvidenceValidationError("Extension formal manifest hash differs")
    expected_plan = _plan(root, run_id)
    if store.plan != expected_plan:
        raise EvidenceValidationError("Extension formal plan differs")
    expected_body = _manifest_body(
        repo_root=root,
        plan=store.plan,
        implementation_commit=str(manifest.get("implementation_git_commit", "")),
    )
    if body != expected_body:
        raise EvidenceValidationError("Extension formal manifest or code drifted")
    formal = _read_json(root / FORMAL_MANIFEST_RELATIVE_PATH)
    if manifest["parent_formal_manifest_id"] != formal_verification["formal_manifest_id"]:
        raise EvidenceValidationError("Extension run binds another formal-v1 manifest")
    return store, manifest, formal


def _status_body(
    store: ExperimentRunStore, manifest: Mapping[str, Any]
) -> dict[str, Any]:
    checkpoint = store.checkpoint()
    completed_by_condition = {condition: 0 for condition in CONDITION_IDS}
    active_failed_keys = 0
    question_complete: dict[str, bool] = {}
    for key in store.plan.execution_order:
        if store.load_completed(key) is not None:
            completed_by_condition[key.condition_id] += 1
        elif store.failure_attempts(key):
            active_failed_keys += 1
    for question_id in store.plan.question_ids:
        question_complete[question_id] = all(
            store.load_completed(RunKey(condition, question_id)) is not None
            for condition in CONDITION_IDS
        )
    finished_questions = sum(question_complete.values())
    completed_blocks = sum(
        all(question_complete[question_id] for question_id in block)
        for block in manifest["question_blocks"]
    )
    status = (
        "completed"
        if checkpoint["pending"] == 0
        else "failed" if active_failed_keys else "pending"
    )
    next_key = checkpoint["pending_keys"][0] if checkpoint["pending_keys"] else None
    return {
        "schema_version": 1,
        "protocol_version": PROTOCOL_VERSION,
        "run_id": store.plan.run_id,
        "plan_id": store.plan.plan_id,
        "formal_run_manifest_id": manifest["formal_run_manifest_id"],
        "status": status,
        "planned_records": checkpoint["planned"],
        "completed_records": checkpoint["completed"],
        "pending_records": checkpoint["pending"],
        "failure_attempts": checkpoint["failed_attempts"],
        "active_failed_keys": active_failed_keys,
        "completed_by_condition": completed_by_condition,
        "finished_questions": finished_questions,
        "completed_blocks": completed_blocks,
        "next_key": next_key,
        "updated_at": _now(),
    }


def write_status(
    *, repo_root: Path, output_root: Path, run_id: str
) -> dict[str, Any]:
    store, manifest, _ = _open_run(
        repo_root=repo_root, output_root=output_root, run_id=run_id
    )
    body = _status_body(store, manifest)
    _write_atomic(store.run_root / "status.json", body)
    return body


def dry_run(
    *, repo_root: Path, output_root: Path, run_id: str
) -> dict[str, Any]:
    root = Path(repo_root).resolve()
    store, manifest, formal = _open_run(
        repo_root=root, output_root=output_root, run_id=run_id
    )
    checkpoint = store.checkpoint()
    if checkpoint["completed"] or checkpoint["failed_attempts"]:
        raise EvidenceValidationError("Dry-run is only valid before API work starts")
    questions = _load_extension_questions(root)
    stores = {name: load_r1_store(root, name) for name in ("s1", "s2", "s3")}
    r2_s1 = build_r2_raw_corpus(root, "s1")
    r2_s2 = build_r2_raw_corpus(root, "s2")
    r2_preflight = preflight_r2_raw_inputs(root)
    r3 = load_r3_corpus(root)

    condition_counts = {
        condition: sum(key.condition_id == condition for key in store.plan.execution_order)
        for condition in CONDITION_IDS
    }
    dependency_checks: dict[str, bool] = {}
    for question_id in store.plan.question_ids:
        positions = {
            key.condition_id: index
            for index, key in enumerate(store.plan.execution_order)
            if key.question_id == question_id
        }
        dependency_checks[question_id] = (
            positions["E7"] > positions["E2"] and positions["E7"] > positions["E6"]
        )
    expected_order = _execution_order(tuple(item.question_id for item in questions))
    checks = {
        "formal_v1_manifest_verified": True,
        "main60_question_set_verified": True,
        "run_plan_140_unique_keys": (
            checkpoint["planned"] == PLANNED_RECORDS
            and len(set(store.plan.execution_order)) == PLANNED_RECORDS
        ),
        "question_order_exact": list(store.plan.question_ids)
        == [item.question_id for item in questions],
        "global_rotation_order_exact": store.plan.execution_order == expected_order,
        "first_extension_condition_is_e5": expected_order[0].condition_id == "E5",
        "conditions_20_each": set(condition_counts.values()) == {20},
        "e7_after_e2_e6_for_every_question": all(dependency_checks.values()),
        "stores_exact": all(
            stores[name].snapshot.to_dict() == formal["stores"][name]
            for name in ("s1", "s2", "s3")
        ),
        "r2_s1_s2_same_exchange_count": (
            len(r2_s1.exchanges) == len(r2_s2.exchanges) == 292
        ),
        "r2_sessions_30": len(r2_s1.sessions) == len(r2_s2.sessions) == 30,
        "r2_content_parity": r2_preflight["content_parity"] is True,
        "r2_probe_ranking_parity": (
            r2_preflight["first_search_ranking_parity"] is True
        ),
        "r3_fact_units_390": len(r3.units) == 390,
        "r3_groups_35": len(r3.groups) == 35,
        "empty_run_store": checkpoint["completed"] == checkpoint["failed_attempts"] == 0,
        "api_provider_not_constructed": True,
        "semantic_gold_not_loaded": True,
        "judge_not_constructed": True,
        "no_runtime_method_overrides": manifest["configuration_overrides"] == "forbidden",
        "serial_concurrency": manifest["deployment"]["concurrency"] == 1,
    }
    body = {
        "schema_version": 1,
        "protocol_version": PROTOCOL_VERSION,
        "run_id": run_id,
        "plan_id": store.plan.plan_id,
        "formal_run_manifest_id": manifest["formal_run_manifest_id"],
        "status": "passed" if all(checks.values()) else "failed",
        "checks": checks,
        "question_count": len(questions),
        "condition_counts": condition_counts,
        "planned_records": checkpoint["planned"],
        "question_blocks": manifest["question_blocks"],
        "store_tree_sha256": {
            name: stores[name].snapshot.tree_sha256 for name in ("s1", "s2", "s3")
        },
        "corpus_stats": {
            "r2_s1_exchanges": len(r2_s1.exchanges),
            "r2_s2_exchanges": len(r2_s2.exchanges),
            "r2_sessions": len(r2_s1.sessions),
            "r3_fact_units": len(r3.units),
            "r3_groups": len(r3.groups),
        },
        "gold_boundary": {"semantic_records_loaded": False},
        "judge_boundary": {"judge_constructed": False},
    }
    report = {
        "dry_run_id": "dry-run-" + sha256_bytes(canonical_json_bytes(body)),
        **body,
    }
    _publish_idempotent(store.run_root / DRY_RUN_NAME, report)
    _append_event(
        store.run_root / "events.jsonl",
        {"event": "dry_run_completed", "at": _now(), "dry_run_id": report["dry_run_id"]},
    )
    if report["status"] != "passed":
        raise EvidenceValidationError("Extension dry-run checks failed")
    return report


def _load_dry_run(
    store: ExperimentRunStore, manifest: Mapping[str, Any]
) -> dict[str, Any]:
    report = _read_json(store.run_root / DRY_RUN_NAME)
    identity = report.get("dry_run_id")
    body = {key: value for key, value in report.items() if key != "dry_run_id"}
    if identity != "dry-run-" + sha256_bytes(canonical_json_bytes(body)):
        raise EvidenceValidationError("Extension dry-run report hash differs")
    if (
        report.get("status") != "passed"
        or report.get("plan_id") != store.plan.plan_id
        or report.get("formal_run_manifest_id") != manifest["formal_run_manifest_id"]
        or not all(report.get("checks", {}).values())
    ):
        raise EvidenceValidationError("Extension API run requires passing dry-run")
    return report


def run(
    *,
    repo_root: Path,
    output_root: Path,
    run_id: str,
    provider: ChatProvider,
    through_block: int,
) -> dict[str, Any]:
    if (
        not isinstance(through_block, int)
        or isinstance(through_block, bool)
        or not 1 <= through_block <= QUESTION_BLOCKS
    ):
        raise EvidenceValidationError("through_block must be an integer from 1 to 4")
    target_records = through_block * QUESTION_BLOCK_SIZE * len(CONDITION_IDS)
    root = Path(repo_root).resolve()
    output = Path(output_root).resolve()
    store, manifest, formal = _open_run(
        repo_root=root, output_root=output, run_id=run_id
    )
    _load_dry_run(store, manifest)
    _provider_preflight(provider)
    questions = {item.question_id: item for item in _load_extension_questions(root)}
    stores = {name: load_r1_store(root, name) for name in ("s1", "s2", "s3")}
    r2_corpora = {name: build_r2_raw_corpus(root, name) for name in ("s1", "s2")}
    r3_corpus = load_r3_corpus(root)
    answerer = SharedAnswerer(
        provider=provider, requested_model=FORMAL_REQUESTED_MODEL_ALIAS
    )
    events = store.run_root / "events.jsonl"

    with _exclusive_run_lock(store.run_root):
        before = _status_body(store, manifest)
        _append_event(
            events,
            {
                "event": "formal_run_started",
                "at": _now(),
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
            _append_event(
                events,
                {
                    "event": "record_started",
                    "at": _now(),
                    "sequence": sequence,
                    **key.to_dict(),
                },
            )
            print(
                f"[{sequence:03d}/{PLANNED_RECORDS}] START "
                f"{key.condition_id} {key.question_id}",
                flush=True,
            )
            try:
                if key.condition_id == "E7":
                    raw = store.load_completed(RunKey("E2", key.question_id))
                    curated = store.load_completed(RunKey("E6", key.question_id))
                    if raw is None or curated is None:
                        raise EvidenceValidationError(
                            "E7 reached before same-question E2 and E6"
                        )
                    if not isinstance(raw.evidence_bundle, EvidenceBundle) or not isinstance(
                        curated.evidence_bundle, EvidenceBundle
                    ):
                        raise EvidenceValidationError(
                            "E7 sources must be retrieval EvidenceBundles"
                        )
                    bundle: EvidenceBundle | FusionEvidenceBundle = (
                        build_e7_fusion_bundle(
                            raw.evidence_bundle, curated.evidence_bundle
                        )
                    )
                else:
                    artifact = store.run_root / key.condition_id / key.question_id
                    if artifact.exists():
                        bundle = _load_retrieval_bundle(
                            run_root=store.run_root,
                            key=key,
                            stores=stores,
                            r3_corpus=r3_corpus,
                        )
                    else:
                        method, store_id = CONDITION_METHODS[key.condition_id]
                        common = {
                            "repo_root": root,
                            "output_root": output,
                            "run_id": run_id,
                            "question": questions[key.question_id],
                            "provider": provider,
                            "requested_model": FORMAL_REQUESTED_MODEL_ALIAS,
                            "budget_unit": FORMAL_EVIDENCE_BUDGET_UNIT,
                            "budget_limit": FORMAL_EVIDENCE_BUDGET_LIMIT,
                        }
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
                            result = execute_r3_question(
                                **common,
                                corpus=r3_corpus,
                            )
                        if result.status == "failed":
                            raise EvidenceValidationError(
                                "retrieval failed and preserved its diagnostic artifact"
                            )
                        bundle = _load_retrieval_bundle(
                            run_root=store.run_root,
                            key=key,
                            stores=stores,
                            r3_corpus=r3_corpus,
                        )
                    _validate_retrieval_bundle(bundle, key=key, formal=formal)

                answer = answerer.run(bundle)
                if set(answer.served_models) != {FORMAL_SERVED_MODEL}:
                    raise EvidenceValidationError("Answerer served model drifted")
                record = RunRecord.create(
                    plan_id=store.plan.plan_id,
                    run_id=run_id,
                    condition_id=key.condition_id,
                    evidence_bundle=bundle,
                    answer_result=answer,
                )
                store.publish_success(record)
            except Exception as error:
                store.publish_failure(
                    key=key,
                    stage=getattr(error, "stage", "formal_record"),
                    error_type=type(error).__name__,
                    message=_safe_error(error, provider),
                    retryable=isinstance(error, TransientProviderError),
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
                failed_status = write_status(
                    repo_root=root, output_root=output, run_id=run_id
                )
                return {
                    "status": "failed",
                    **key.to_dict(),
                    "progress": failed_status,
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
            current = write_status(
                repo_root=root, output_root=output, run_id=run_id
            )
            print(
                f"[{sequence:03d}/{PLANNED_RECORDS}] VERIFIED "
                f"records={current['completed_records']}/{PLANNED_RECORDS}",
                flush=True,
            )
            if current["completed_records"] % (
                QUESTION_BLOCK_SIZE * len(CONDITION_IDS)
            ) == 0:
                _append_event(
                    events,
                    {
                        "event": "question_block_verified",
                        "at": _now(),
                        "completed_records": current["completed_records"],
                        "completed_blocks": current["completed_blocks"],
                    },
                )

        final_status = write_status(
            repo_root=root, output_root=output, run_id=run_id
        )
        event = (
            "formal_api_phase_completed"
            if final_status["completed_records"] == PLANNED_RECORDS
            else "formal_batch_target_reached"
        )
        _append_event(
            events,
            {
                "event": event,
                "at": _now(),
                "completed_records": final_status["completed_records"],
                "through_block": through_block,
                "target_records": target_records,
            },
        )
        return {
            **final_status,
            "execution_control": {
                "through_block": through_block,
                "target_records": target_records,
                "target_reached": final_status["completed_records"] >= target_records,
            },
        }


def verify_completed_run(
    *, repo_root: Path, output_root: Path, run_id: str
) -> dict[str, Any]:
    root = Path(repo_root).resolve()
    output = Path(output_root).resolve()
    store, manifest, formal = _open_run(
        repo_root=root, output_root=output, run_id=run_id
    )
    _load_dry_run(store, manifest)
    checkpoint = store.checkpoint()
    if checkpoint["completed"] != PLANNED_RECORDS or checkpoint["pending"] != 0:
        raise EvidenceValidationError(
            "Extension pre-gold verification requires 140/140 records"
        )
    stores = {name: load_r1_store(root, name) for name in ("s1", "s2", "s3")}
    r3_corpus = load_r3_corpus(root)
    counts = {condition: 0 for condition in CONDITION_IDS}
    capped = {condition: 0 for condition in CONDITION_IDS[:-1]}
    empty = {condition: 0 for condition in CONDITION_IDS[:-1]}
    budget_skipped = {condition: 0 for condition in CONDITION_IDS[:-1]}
    total_tokens = {condition: 0 for condition in CONDITION_IDS}
    e7_checks: list[dict[str, Any]] = []
    for key in store.plan.execution_order:
        record = store.load_completed(key)
        if record is None:
            raise EvidenceValidationError("Extension RunRecord disappeared")
        counts[key.condition_id] += 1
        total = record.deployment_metrics.get("total_tokens")
        if isinstance(total, int):
            total_tokens[key.condition_id] += total
        if set(record.answer_result.served_models) != {FORMAL_SERVED_MODEL}:
            raise EvidenceValidationError("Extension answer served model drifted")
        if not set(record.answer_result.citations).issubset(
            {item.evidence_id for item in record.evidence_bundle.evidence_items}
        ):
            raise EvidenceValidationError("Extension answer citation is not in evidence")
        if key.condition_id != "E7":
            bundle = record.evidence_bundle
            if not isinstance(bundle, EvidenceBundle):
                raise EvidenceValidationError("E1-E6 record lacks EvidenceBundle")
            _validate_retrieval_bundle(bundle, key=key, formal=formal)
            artifact_bundle = _load_retrieval_bundle(
                run_root=store.run_root,
                key=key,
                stores=stores,
                r3_corpus=r3_corpus,
            )
            if artifact_bundle.bundle_id != bundle.bundle_id:
                raise EvidenceValidationError("RunRecord and retrieval artifact differ")
            capped[key.condition_id] += int(bundle.stop.hit_cap)
            empty[key.condition_id] += int(not bundle.evidence_items)
            budget_skipped[key.condition_id] += int(bundle.budget.skipped_items > 0)
        else:
            raw = store.load_completed(RunKey("E2", key.question_id))
            curated = store.load_completed(RunKey("E6", key.question_id))
            fusion = record.evidence_bundle
            if raw is None or curated is None or not isinstance(
                fusion, FusionEvidenceBundle
            ):
                raise EvidenceValidationError("E7 sources are missing")
            expected_retrieval_tokens = int(
                raw.retrieval_metrics["total_tokens"]
            ) + int(curated.retrieval_metrics["total_tokens"])
            checks = {
                "source_bundle_ids_match": fusion.source_bundle_ids
                == (
                    raw.evidence_bundle.bundle_id,
                    curated.evidence_bundle.bundle_id,
                ),
                "no_new_search": fusion.retrieval_metrics.get("search_calls") == 0
                and fusion.retrieval_metrics.get("reused_upstream_retrieval") is True,
                "retrieval_cost_once": int(record.retrieval_metrics["total_tokens"])
                == expected_retrieval_tokens,
                "source_answer_cost_excluded": int(
                    record.deployment_metrics["total_tokens"]
                )
                == expected_retrieval_tokens
                + int(record.answer_metrics["total_tokens"]),
                "budget_2b": fusion.budget.per_source_limit
                == FORMAL_EVIDENCE_BUDGET_LIMIT
                and fusion.budget.total_limit
                == 2 * FORMAL_EVIDENCE_BUDGET_LIMIT,
            }
            if not all(checks.values()):
                raise EvidenceValidationError("Extension E7 audit failed")
            e7_checks.append({"question_id": key.question_id, **checks})

    checks = {
        "records_140_complete": checkpoint["completed"] == 140
        and checkpoint["pending"] == 0,
        "conditions_20_each": set(counts.values()) == {20},
        "served_model_exact": True,
        "citations_real": True,
        "stores_unchanged": True,
        "retrieval_artifacts_match_records": True,
        "e7_no_hidden_retrieval": all(item["no_new_search"] for item in e7_checks),
        "e7_cost_rule_exact": all(
            item["retrieval_cost_once"] and item["source_answer_cost_excluded"]
            for item in e7_checks
        ),
        "semantic_gold_not_loaded": True,
        "judge_not_run": True,
    }
    body = {
        "schema_version": 1,
        "protocol_version": PROTOCOL_VERSION,
        "run_id": run_id,
        "plan_id": store.plan.plan_id,
        "formal_run_manifest_id": manifest["formal_run_manifest_id"],
        "status": "passed" if all(checks.values()) else "failed",
        "checks": checks,
        "condition_counts": counts,
        "capped_retrieval_episodes": capped,
        "empty_retrieval_episodes": empty,
        "budget_skipped_episodes": budget_skipped,
        "deployment_total_tokens": total_tokens,
        "e7_checks": e7_checks,
        "gold_boundary": {"semantic_records_loaded": False},
        "judge_boundary": {"judge_run": False},
    }
    audit = {
        "pre_gold_audit_id": "pre-gold-"
        + sha256_bytes(canonical_json_bytes(body)),
        **body,
    }
    _publish_idempotent(store.run_root / PRE_GOLD_AUDIT_NAME, audit)
    _append_event(
        store.run_root / "events.jsonl",
        {
            "event": "formal_pre_gold_verified",
            "at": _now(),
            "pre_gold_audit_id": audit["pre_gold_audit_id"],
        },
    )
    return audit
