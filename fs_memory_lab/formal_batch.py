"""Formal-v1 main-40 orchestration, checkpointing, and pre-gold audit.

This module is deliberately an orchestration layer over the already frozen
R1/R2/R3, Answerer, fusion, RunRecord, and evaluation implementations.  It does
not offer command-line overrides for model, evidence budget, caps, prompts, or
search parameters.  A run manifest binds this file's SHA-256 and Git commit so
that later changes cannot silently alter an in-progress formal run.
"""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import re
import tempfile
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from .agent import ChatProvider, TransientProviderError
from .answerer import SharedAnswerer
from .evaluation import aggregate_evaluations, evaluate_run_store
from .evidence import EvidenceBundle, EvidenceValidationError, canonical_json_bytes, sha256_bytes
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
from .r1_artifacts import verify_r1_episode_artifact
from .r1_inputs import load_question_inputs, load_r1_store
from .r1_runner import execute_r1_question
from .r2_artifacts import verify_r2_episode_artifact
from .r2_inputs import build_r2_raw_corpus, preflight_r2_raw_inputs
from .r2_runner import execute_r2_question
from .r3_artifacts import verify_r3_episode_artifact
from .r3_inputs import load_r3_corpus
from .r3_runner import execute_r3_question
from .run_records import (
    CONDITION_IDS,
    ExperimentRunPlan,
    ExperimentRunStore,
    RunKey,
    RunRecord,
    build_run_plan,
    verify_run_store,
)


FORMAL_BATCH_PROTOCOL_VERSION = "formal-v1-main40-orchestrator-v1"
FORMAL_BATCH_MANIFEST_NAME = "formal-run-manifest.json"
FORMAL_DRY_RUN_NAME = "dry-run.json"
FORMAL_PRE_GOLD_AUDIT_NAME = "pre-gold-audit.json"
FORMAL_EVALUATION_NAME = "evaluation.json"
FORMAL_FINAL_AUDIT_NAME = "final-audit.json"
FORMAL_QUESTION_BLOCK_SIZE = 5
FORMAL_PLANNED_RECORDS = 280

CONDITION_METHODS: Mapping[str, tuple[str, str]] = {
    "E1": ("r1", "s1"),
    "E2": ("r2", "s1"),
    "E3": ("r1", "s2"),
    "E4": ("r2", "s2"),
    "E5": ("r1", "s3"),
    "E6": ("r3", "s3"),
}

_SAFE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}\Z")
_COMMIT = re.compile(r"[0-9a-f]{40}\Z")


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
        raise EvidenceValidationError(f"Unsafe or missing JSON artifact: {lexical}")
    try:
        value = json.loads(lexical.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise EvidenceValidationError(f"Unreadable JSON artifact: {lexical}") from exc
    if not isinstance(value, dict):
        raise EvidenceValidationError("Formal batch JSON artifact must be an object")
    return value


def _write_exclusive(path: Path, value: Mapping[str, Any], mode: int = 0o644) -> None:
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
                raise OSError("short formal artifact write")
            offset += written
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


def _publish_idempotent(path: Path, value: Mapping[str, Any], mode: int = 0o644) -> None:
    if path.exists() or path.is_symlink():
        if _read_json(path) != dict(value):
            raise EvidenceValidationError(f"Existing formal artifact differs: {path.name}")
        return
    _write_exclusive(path, value, mode)


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


def _manifest_body(
    *, repo_root: Path, plan: ExperimentRunPlan, orchestrator_commit: str,
) -> dict[str, Any]:
    root = Path(repo_root).resolve()
    formal_path = root / FORMAL_MANIFEST_RELATIVE_PATH
    formal = _read_json(formal_path)
    questions = load_question_inputs(root, "main-40")
    blocks = [
        [item.question_id for item in questions[start : start + FORMAL_QUESTION_BLOCK_SIZE]]
        for start in range(0, len(questions), FORMAL_QUESTION_BLOCK_SIZE)
    ]
    return {
        "schema_version": 1,
        "protocol_version": FORMAL_BATCH_PROTOCOL_VERSION,
        "status": "prepared",
        "run_id": plan.run_id,
        "plan_id": plan.plan_id,
        "formal_manifest_id": formal["formal_manifest_id"],
        "formal_manifest_sha256": _file_sha256(formal_path),
        "formal_implementation_commit": formal["implementation_git_commit"],
        "orchestrator_git_commit": orchestrator_commit,
        "orchestrator_relative_path": "fs_memory_lab/formal_batch.py",
        "orchestrator_sha256": _file_sha256(root / "fs_memory_lab/formal_batch.py"),
        "question_set_id": "locomo-conv50-main40-v1",
        "question_count": 40,
        "condition_ids": list(CONDITION_IDS),
        "planned_records": FORMAL_PLANNED_RECORDS,
        "execution_order_sha256": formal["question_set"]["execution_order_sha256"],
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
        "block_size": FORMAL_QUESTION_BLOCK_SIZE,
        "stop_on_failure": True,
        "resume_policy": "explicit-new-run-invocation-revalidates-and-skips-only-completed-records",
        "gold_access_policy": (
            "formal verifier may hash gold bytes for integrity; semantic gold records are "
            "loaded only by finalize after 280/280 pre-gold verification"
        ),
        "configuration_overrides": "forbidden",
    }


def _formal_plan(repo_root: Path, run_id: str) -> ExperimentRunPlan:
    root = Path(repo_root).resolve()
    formal_path = root / FORMAL_MANIFEST_RELATIVE_PATH
    formal = _read_json(formal_path)
    questions = load_question_inputs(root, "main-40")
    config_hashes = {
        "formal_manifest": _file_sha256(formal_path),
        "formal_core_files": formal["core_files_tree_sha256"],
        "question_inputs": formal["question_set"]["input_sha256"],
        "answerer_prompt": formal["answerer"]["prompt_sha256"],
        "fusion_contract": formal["e7_fusion"]["contract_sha256"],
        "r1_limits": formal["retrieval"]["r1"]["limits_sha256"],
        "r2_protocol": formal["retrieval"]["r2"]["protocol_sha256"],
        "r3_protocol": formal["retrieval"]["r3"]["protocol_sha256"],
        "s1_tree": formal["stores"]["s1"]["tree_sha256"],
        "s2_tree": formal["stores"]["s2"]["tree_sha256"],
        "s3_tree": formal["stores"]["s3"]["tree_sha256"],
    }
    return build_run_plan(
        run_id=run_id,
        question_set_id="locomo-conv50-main40-v1",
        question_ids=tuple(item.question_id for item in questions),
        condition_ids=CONDITION_IDS,
        config_hashes=config_hashes,
    )


def prepare_formal_run(
    *, repo_root: Path, output_root: Path, run_id: str,
    orchestrator_commit: str,
) -> Path:
    """Create the immutable 280-key plan and run manifest without an API call."""
    if _SAFE.fullmatch(run_id) is None:
        raise EvidenceValidationError("Formal run_id is unsafe")
    if _COMMIT.fullmatch(orchestrator_commit) is None:
        raise EvidenceValidationError("Orchestrator commit must be a full Git SHA")
    root = Path(repo_root).resolve()
    verify_formal_manifest(root)
    plan = _formal_plan(root, run_id)
    store = ExperimentRunStore.create_or_open(Path(output_root).resolve(), plan)
    body = _manifest_body(
        repo_root=root, plan=plan, orchestrator_commit=orchestrator_commit
    )
    manifest = {
        "formal_run_manifest_id": "formal-run-" + sha256_bytes(canonical_json_bytes(body)),
        **body,
    }
    path = store.run_root / FORMAL_BATCH_MANIFEST_NAME
    _publish_idempotent(path, manifest)
    _append_event(
        store.run_root / "events.jsonl",
        {
            "event": "formal_run_prepared",
            "at": _now(),
            "formal_run_manifest_id": manifest["formal_run_manifest_id"],
        },
    )
    write_formal_status(repo_root=root, output_root=output_root, run_id=run_id)
    return path


def _open_formal_run(
    *, repo_root: Path, output_root: Path, run_id: str,
) -> tuple[ExperimentRunStore, dict[str, Any], dict[str, Any]]:
    root = Path(repo_root).resolve()
    formal_verification = verify_formal_manifest(root)
    store, _ = verify_run_store(Path(output_root).resolve(), run_id)
    path = store.run_root / FORMAL_BATCH_MANIFEST_NAME
    manifest = _read_json(path)
    identity = manifest.get("formal_run_manifest_id")
    body = {key: value for key, value in manifest.items() if key != "formal_run_manifest_id"}
    if identity != "formal-run-" + sha256_bytes(canonical_json_bytes(body)):
        raise EvidenceValidationError("Formal run manifest content hash differs")
    expected_plan = _formal_plan(root, run_id)
    if store.plan != expected_plan:
        raise EvidenceValidationError("Formal run plan differs from formal-v1")
    expected = _manifest_body(
        repo_root=root,
        plan=store.plan,
        orchestrator_commit=str(manifest.get("orchestrator_git_commit", "")),
    )
    if body != expected:
        raise EvidenceValidationError("Formal run manifest or orchestrator drifted")
    if manifest["formal_manifest_id"] != formal_verification["formal_manifest_id"]:
        raise EvidenceValidationError("Formal run binds another formal manifest")
    return store, manifest, formal_verification


def _status_body(store: ExperimentRunStore, manifest: Mapping[str, Any]) -> dict[str, Any]:
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
    if checkpoint["pending"] == 0:
        status = "completed"
    elif active_failed_keys:
        status = "failed"
    else:
        status = "pending"
    next_key = checkpoint["pending_keys"][0] if checkpoint["pending_keys"] else None
    return {
        "schema_version": 1,
        "protocol_version": FORMAL_BATCH_PROTOCOL_VERSION,
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


def write_formal_status(
    *, repo_root: Path, output_root: Path, run_id: str,
) -> dict[str, Any]:
    store, manifest, _ = _open_formal_run(
        repo_root=repo_root, output_root=output_root, run_id=run_id
    )
    body = _status_body(store, manifest)
    _write_atomic(store.run_root / "status.json", body)
    return body


def dry_run_formal(
    *, repo_root: Path, output_root: Path, run_id: str,
) -> dict[str, Any]:
    """Validate all inputs and the 280-key schedule without constructing a provider."""
    root = Path(repo_root).resolve()
    store, manifest, formal_verification = _open_formal_run(
        repo_root=root, output_root=output_root, run_id=run_id
    )
    checkpoint = store.checkpoint()
    if checkpoint["completed"] or checkpoint["failed_attempts"]:
        raise EvidenceValidationError("Dry-run is only valid before formal API work starts")
    formal = _read_json(root / FORMAL_MANIFEST_RELATIVE_PATH)
    questions = load_question_inputs(root, "main-40")
    stores = {name: load_r1_store(root, name) for name in ("s1", "s2", "s3")}
    r2_s1 = build_r2_raw_corpus(root, "s1")
    r2_s2 = build_r2_raw_corpus(root, "s2")
    r2_preflight = preflight_r2_raw_inputs(root)
    r3 = load_r3_corpus(root)

    expected_order = formal["question_set"]["execution_order"]
    actual_order = [item.to_dict() for item in store.plan.execution_order]
    condition_counts = {
        condition: sum(item.condition_id == condition for item in store.plan.execution_order)
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
    question_order = [item.question_id for item in questions]
    formal_question_order = [
        item["question_id"] for item in formal["question_set"]["question_order"]
    ]
    checks = {
        "formal_manifest_verified": formal_verification["status"] == "verified",
        "run_plan_280_unique_keys": (
            checkpoint["planned"] == FORMAL_PLANNED_RECORDS
            and len(set(store.plan.execution_order)) == FORMAL_PLANNED_RECORDS
        ),
        "question_order_exact": question_order == formal_question_order,
        "execution_order_exact": actual_order == expected_order,
        "conditions_40_each": set(condition_counts.values()) == {40},
        "e7_after_e2_e6_for_every_question": all(dependency_checks.values()),
        "stores_exact": all(
            stores[name].snapshot.to_dict() == formal["stores"][name]
            for name in ("s1", "s2", "s3")
        ),
        "r2_s1_s2_same_exchange_count": (
            len(r2_s1.exchanges) == len(r2_s2.exchanges) == 292
        ),
        "r2_sessions_30": len(r2_s1.sessions) == len(r2_s2.sessions) == 30,
        "r2_s1_s2_content_parity": r2_preflight["content_parity"] is True,
        "r2_s1_s2_probe_ranking_parity": (
            r2_preflight["first_search_ranking_parity"] is True
        ),
        "r3_fact_units_390": len(r3.units) == 390,
        "r3_groups_35": len(r3.groups) == 35,
        "empty_run_store": checkpoint["completed"] == checkpoint["failed_attempts"] == 0,
        "api_provider_not_constructed": True,
        "semantic_gold_not_loaded": True,
        "no_runtime_method_overrides": manifest["configuration_overrides"] == "forbidden",
        "serial_concurrency": manifest["deployment"]["concurrency"] == 1,
    }
    body = {
        "schema_version": 1,
        "protocol_version": FORMAL_BATCH_PROTOCOL_VERSION,
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
            "r2_path_difference_count": r2_preflight["path_difference_count"],
            "r2_index_documents_per_store": r2_preflight[
                "index_documents_per_store"
            ],
            "r3_fact_units": len(r3.units),
            "r3_groups": len(r3.groups),
        },
        "gold_boundary": {
            "semantic_records_loaded": False,
            "integrity_hash_checked_by_formal_verifier": True,
        },
    }
    report = {
        "dry_run_id": "dry-run-" + sha256_bytes(canonical_json_bytes(body)),
        **body,
    }
    _publish_idempotent(store.run_root / FORMAL_DRY_RUN_NAME, report)
    _append_event(
        store.run_root / "events.jsonl",
        {"event": "dry_run_completed", "at": _now(), "dry_run_id": report["dry_run_id"]},
    )
    if report["status"] != "passed":
        raise EvidenceValidationError("Formal dry-run checks failed")
    return report


def _load_dry_run(store: ExperimentRunStore, manifest: Mapping[str, Any]) -> dict[str, Any]:
    report = _read_json(store.run_root / FORMAL_DRY_RUN_NAME)
    identity = report.get("dry_run_id")
    body = {key: value for key, value in report.items() if key != "dry_run_id"}
    if identity != "dry-run-" + sha256_bytes(canonical_json_bytes(body)):
        raise EvidenceValidationError("Dry-run report content hash differs")
    if (
        report.get("status") != "passed"
        or report.get("plan_id") != store.plan.plan_id
        or report.get("formal_run_manifest_id") != manifest["formal_run_manifest_id"]
        or not all(report.get("checks", {}).values())
    ):
        raise EvidenceValidationError("Formal API run requires a passing dry-run")
    return report


def _load_retrieval_bundle(
    *, run_root: Path, key: RunKey,
    stores: Mapping[str, Any], r3_corpus: Any,
) -> EvidenceBundle:
    path = run_root / key.condition_id / key.question_id
    method, store_id = CONDITION_METHODS[key.condition_id]
    if method == "r1":
        return verify_r1_episode_artifact(path, loaded_store=stores[store_id])
    if method == "r2":
        return verify_r2_episode_artifact(path, loaded_store=stores[store_id])
    return verify_r3_episode_artifact(path, corpus=r3_corpus)


def _validate_retrieval_bundle(
    bundle: EvidenceBundle, *, key: RunKey, formal: Mapping[str, Any],
) -> None:
    _, store_id = CONDITION_METHODS[key.condition_id]
    if (
        bundle.question.question_id != key.question_id
        or bundle.condition.get("condition_id") != key.condition_id
        or bundle.condition.get("store_id") != store_id
    ):
        raise EvidenceValidationError("Retrieval bundle question/condition differs")
    if (
        bundle.budget.unit != FORMAL_EVIDENCE_BUDGET_UNIT
        or bundle.budget.limit != FORMAL_EVIDENCE_BUDGET_LIMIT
    ):
        raise EvidenceValidationError("Retrieval bundle evidence budget differs")
    if bundle.model.get("requested_model") != FORMAL_REQUESTED_MODEL_ALIAS:
        raise EvidenceValidationError("Retrieval requested model differs")
    if set(bundle.model.get("served_models", ())) != {FORMAL_SERVED_MODEL}:
        raise EvidenceValidationError("Retrieval served model drifted")
    if bundle.store_snapshot.to_dict() != formal["stores"][store_id]:
        raise EvidenceValidationError("Retrieval store snapshot drifted")
    if bundle.integrity.get("verified") is not True or bundle.integrity.get("store_unchanged") is not True:
        raise EvidenceValidationError("Retrieval store integrity is not verified")


def _provider_preflight(provider: ChatProvider) -> None:
    if getattr(provider, "api_style", None) != FORMAL_API_STYLE:
        raise EvidenceValidationError("Formal provider API style differs")
    if getattr(provider, "model", None) != FORMAL_REQUESTED_MODEL_ALIAS:
        raise EvidenceValidationError("FSMEM_MODEL must equal the frozen alias coding")
    if getattr(provider, "timeout", None) != FORMAL_REQUEST_TIMEOUT_SECONDS:
        raise EvidenceValidationError("Formal provider timeout differs")
    if getattr(provider, "max_response_bytes", None) != FORMAL_MAX_RESPONSE_BYTES:
        raise EvidenceValidationError("Formal provider response cap differs")


def _safe_error(error: BaseException, provider: ChatProvider) -> str:
    message = " ".join(str(error).split())[:1000] or type(error).__name__
    secret = getattr(provider, "api_key", None)
    if isinstance(secret, str) and secret:
        message = message.replace(secret, "[REDACTED_KEY]")
    return re.sub(r"\b(?:clsk|sk)[_-][A-Za-z0-9_-]{10,}\b", "[REDACTED_KEY]", message)


@contextmanager
def _exclusive_run_lock(run_root: Path):
    path = run_root / "run.lock"
    handle = path.open("a+", encoding="utf-8")
    try:
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise EvidenceValidationError("Another formal runner already holds the run lock") from exc
        yield
    finally:
        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        handle.close()


def run_formal(
    *, repo_root: Path, output_root: Path, run_id: str, provider: ChatProvider,
) -> dict[str, Any]:
    """Run or explicitly resume formal-v1 in its frozen 280-key order."""
    root = Path(repo_root).resolve()
    output = Path(output_root).resolve()
    store, manifest, _ = _open_formal_run(repo_root=root, output_root=output, run_id=run_id)
    _load_dry_run(store, manifest)
    _provider_preflight(provider)
    formal = _read_json(root / FORMAL_MANIFEST_RELATIVE_PATH)
    questions = {item.question_id: item for item in load_question_inputs(root, "main-40")}
    stores = {name: load_r1_store(root, name) for name in ("s1", "s2", "s3")}
    r2_corpora = {name: build_r2_raw_corpus(root, name) for name in ("s1", "s2")}
    r3_corpus = load_r3_corpus(root)
    answerer = SharedAnswerer(provider=provider, requested_model=FORMAL_REQUESTED_MODEL_ALIAS)
    events = store.run_root / "events.jsonl"

    with _exclusive_run_lock(store.run_root):
        status = _status_body(store, manifest)
        _append_event(
            events,
            {"event": "formal_run_started", "at": _now(), "completed_before": status["completed_records"]},
        )
        for sequence, key in enumerate(store.plan.execution_order, start=1):
            if store.load_completed(key) is not None:
                continue
            _append_event(events, {"event": "record_started", "at": _now(), "sequence": sequence, **key.to_dict()})
            print(
                f"[{sequence:03d}/{FORMAL_PLANNED_RECORDS}] START "
                f"{key.condition_id} {key.question_id}",
                flush=True,
            )
            try:
                if key.condition_id == "E7":
                    raw = store.load_completed(RunKey("E2", key.question_id))
                    curated = store.load_completed(RunKey("E6", key.question_id))
                    if raw is None or curated is None:
                        raise EvidenceValidationError("E7 reached before same-question E2 and E6")
                    if not isinstance(raw.evidence_bundle, EvidenceBundle) or not isinstance(
                        curated.evidence_bundle, EvidenceBundle
                    ):
                        raise EvidenceValidationError("E7 sources must be retrieval EvidenceBundles")
                    bundle: EvidenceBundle | FusionEvidenceBundle = build_e7_fusion_bundle(
                        raw.evidence_bundle, curated.evidence_bundle
                    )
                else:
                    artifact = store.run_root / key.condition_id / key.question_id
                    if artifact.exists():
                        bundle = _load_retrieval_bundle(
                            run_root=store.run_root, key=key,
                            stores=stores, r3_corpus=r3_corpus,
                        )
                    else:
                        method, store_id = CONDITION_METHODS[key.condition_id]
                        if method == "r1":
                            result = execute_r1_question(
                                repo_root=root, output_root=output, run_id=run_id,
                                cell_id=key.condition_id, question=questions[key.question_id],
                                provider=provider, requested_model=FORMAL_REQUESTED_MODEL_ALIAS,
                                budget_unit=FORMAL_EVIDENCE_BUDGET_UNIT,
                                budget_limit=FORMAL_EVIDENCE_BUDGET_LIMIT,
                                loaded_store=stores[store_id],
                            )
                        elif method == "r2":
                            result = execute_r2_question(
                                repo_root=root, output_root=output, run_id=run_id,
                                cell_id=key.condition_id, question=questions[key.question_id],
                                provider=provider, requested_model=FORMAL_REQUESTED_MODEL_ALIAS,
                                budget_unit=FORMAL_EVIDENCE_BUDGET_UNIT,
                                budget_limit=FORMAL_EVIDENCE_BUDGET_LIMIT,
                                corpus=r2_corpora[store_id],
                            )
                        else:
                            result = execute_r3_question(
                                repo_root=root, output_root=output, run_id=run_id,
                                question=questions[key.question_id], provider=provider,
                                requested_model=FORMAL_REQUESTED_MODEL_ALIAS,
                                budget_unit=FORMAL_EVIDENCE_BUDGET_UNIT,
                                budget_limit=FORMAL_EVIDENCE_BUDGET_LIMIT,
                                corpus=r3_corpus,
                            )
                        if result.status == "failed":
                            raise EvidenceValidationError(
                                f"retrieval failed and preserved artifact {result.artifact_id}"
                            )
                        bundle = _load_retrieval_bundle(
                            run_root=store.run_root, key=key,
                            stores=stores, r3_corpus=r3_corpus,
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
                    {"event": "record_failed", "at": _now(), "sequence": sequence, **key.to_dict(), "error_type": type(error).__name__},
                )
                failed_status = write_formal_status(
                    repo_root=root, output_root=output, run_id=run_id
                )
                return {"status": "failed", **key.to_dict(), "progress": failed_status}

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
            current = write_formal_status(repo_root=root, output_root=output, run_id=run_id)
            print(
                f"[{sequence:03d}/{FORMAL_PLANNED_RECORDS}] VERIFIED "
                f"records={current['completed_records']}/{FORMAL_PLANNED_RECORDS}",
                flush=True,
            )
            if current["completed_records"] % (FORMAL_QUESTION_BLOCK_SIZE * len(CONDITION_IDS)) == 0:
                _append_event(
                    events,
                    {"event": "question_block_verified", "at": _now(), "completed_records": current["completed_records"], "completed_blocks": current["completed_blocks"]},
                )

        final_status = write_formal_status(repo_root=root, output_root=output, run_id=run_id)
        _append_event(events, {"event": "formal_api_phase_completed", "at": _now(), "completed_records": final_status["completed_records"]})
        return final_status


def _verify_completed_run(
    *, repo_root: Path, output_root: Path, run_id: str,
) -> tuple[dict[str, Any], ExperimentRunStore]:
    root = Path(repo_root).resolve()
    store, manifest, _ = _open_formal_run(repo_root=root, output_root=output_root, run_id=run_id)
    _load_dry_run(store, manifest)
    checkpoint = store.checkpoint()
    if checkpoint["completed"] != FORMAL_PLANNED_RECORDS or checkpoint["pending"] != 0:
        raise EvidenceValidationError("Formal pre-gold verification requires 280/280 records")
    formal = _read_json(root / FORMAL_MANIFEST_RELATIVE_PATH)
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
            raise EvidenceValidationError("Formal RunRecord disappeared during verification")
        counts[key.condition_id] += 1
        total = record.deployment_metrics.get("total_tokens")
        if isinstance(total, int):
            total_tokens[key.condition_id] += total
        if set(record.answer_result.served_models) != {FORMAL_SERVED_MODEL}:
            raise EvidenceValidationError("Formal answer served model drifted")
        if not set(record.answer_result.citations).issubset(
            {item.evidence_id for item in record.evidence_bundle.evidence_items}
        ):
            raise EvidenceValidationError("Formal answer citation is not in evidence")
        if key.condition_id != "E7":
            bundle = record.evidence_bundle
            if not isinstance(bundle, EvidenceBundle):
                raise EvidenceValidationError("E1-E6 record lacks an EvidenceBundle")
            _validate_retrieval_bundle(bundle, key=key, formal=formal)
            artifact_bundle = _load_retrieval_bundle(
                run_root=store.run_root, key=key,
                stores=stores, r3_corpus=r3_corpus,
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
            if raw is None or curated is None or not isinstance(fusion, FusionEvidenceBundle):
                raise EvidenceValidationError("E7 verification sources are missing")
            expected_retrieval_tokens = int(raw.retrieval_metrics["total_tokens"]) + int(
                curated.retrieval_metrics["total_tokens"]
            )
            checks = {
                "source_bundle_ids_match": fusion.source_bundle_ids == (
                    raw.evidence_bundle.bundle_id, curated.evidence_bundle.bundle_id
                ),
                "no_new_search": fusion.retrieval_metrics.get("search_calls") == 0
                and fusion.retrieval_metrics.get("reused_upstream_retrieval") is True,
                "retrieval_cost_once": int(record.retrieval_metrics["total_tokens"])
                == expected_retrieval_tokens,
                "source_answer_cost_excluded": int(record.deployment_metrics["total_tokens"])
                == expected_retrieval_tokens + int(record.answer_metrics["total_tokens"]),
                "budget_2b": fusion.budget.per_source_limit == FORMAL_EVIDENCE_BUDGET_LIMIT
                and fusion.budget.total_limit == 2 * FORMAL_EVIDENCE_BUDGET_LIMIT,
            }
            if not all(checks.values()):
                raise EvidenceValidationError("E7 pre-gold audit failed")
            e7_checks.append({"question_id": key.question_id, **checks})

    checks = {
        "records_280_complete": checkpoint["completed"] == 280 and checkpoint["pending"] == 0,
        "conditions_40_each": set(counts.values()) == {40},
        "served_model_exact": True,
        "citations_real": True,
        "stores_unchanged": True,
        "retrieval_artifacts_match_records": True,
        "e7_no_hidden_retrieval": all(item["no_new_search"] for item in e7_checks),
        "e7_cost_rule_exact": all(
            item["retrieval_cost_once"] and item["source_answer_cost_excluded"]
            for item in e7_checks
        ),
        "one_formal_manifest": True,
        "semantic_gold_not_loaded": True,
    }
    body = {
        "schema_version": 1,
        "protocol_version": FORMAL_BATCH_PROTOCOL_VERSION,
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
    }
    audit = {
        "pre_gold_audit_id": "pre-gold-" + sha256_bytes(canonical_json_bytes(body)),
        **body,
    }
    _publish_idempotent(store.run_root / FORMAL_PRE_GOLD_AUDIT_NAME, audit)
    return audit, store


def verify_formal_run(
    *, repo_root: Path, output_root: Path, run_id: str,
) -> dict[str, Any]:
    audit, _ = _verify_completed_run(
        repo_root=repo_root, output_root=output_root, run_id=run_id
    )
    return audit


def finalize_formal_run(
    *, repo_root: Path, output_root: Path, run_id: str,
) -> dict[str, Any]:
    """Open gold only after pre-gold 280/280 verification, then score without a judge."""
    root = Path(repo_root).resolve()
    output = Path(output_root).resolve()
    pre_gold, store = _verify_completed_run(
        repo_root=root, output_root=output, run_id=run_id
    )
    formal = _read_json(root / FORMAL_MANIFEST_RELATIVE_PATH)
    results = evaluate_run_store(
        run_root=output,
        run_id=run_id,
        gold_path=root / formal["question_set"]["gold_relative_path"],
        expected_gold_sha256=formal["question_set"]["gold_sha256"],
        judge=None,
    )
    evaluation = {
        "summary": aggregate_evaluations(results),
        "results": [item.to_dict() for item in results],
    }
    _publish_idempotent(store.run_root / FORMAL_EVALUATION_NAME, evaluation, 0o600)
    body = {
        "schema_version": 1,
        "protocol_version": FORMAL_BATCH_PROTOCOL_VERSION,
        "run_id": run_id,
        "plan_id": store.plan.plan_id,
        "status": "passed",
        "formal_manifest_id": formal["formal_manifest_id"],
        "pre_gold_audit_id": pre_gold["pre_gold_audit_id"],
        "evaluation_summary_sha256": evaluation["summary"]["summary_sha256"],
        "evaluated_records": len(results),
        "anonymous_llm_judge_enabled": False,
    }
    final = {
        "final_audit_id": "formal-final-" + sha256_bytes(canonical_json_bytes(body)),
        **body,
    }
    _publish_idempotent(store.run_root / FORMAL_FINAL_AUDIT_NAME, final)
    _append_event(
        store.run_root / "events.jsonl",
        {"event": "formal_run_finalized", "at": _now(), "final_audit_id": final["final_audit_id"]},
    )
    return final
