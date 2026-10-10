"""Auditable, resumable dev-6 retrieval orchestration for E1--E6.

This module deliberately excludes answering.  It runs the six retrieval methods
with one shared character budget, verifies every published EvidenceBundle against
its frozen store, and only opens development gold after all 36 episodes finish.
"""

from __future__ import annotations

import json
import os
import re
import statistics
import tempfile
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

from .agent import ChatProvider
from .evaluation import load_gold_records
from .evidence import (
    EvidenceBundle,
    EvidenceValidationError,
    canonical_json_bytes,
    sha256_bytes,
)
from .r1_artifacts import verify_r1_episode_artifact, verify_r1_failure_artifact
from .r1_inputs import QUESTION_INPUTS, load_question_inputs, load_r1_store
from .r1_runner import execute_r1_question
from .r2_artifacts import verify_r2_episode_artifact, verify_r2_failure_artifact
from .r2_inputs import build_r2_raw_corpus
from .r2_runner import execute_r2_question
from .r3_artifacts import verify_r3_episode_artifact, verify_r3_failure_artifact
from .r3_inputs import load_r3_corpus
from .r3_runner import execute_r3_question
from .run_records import (
    ExperimentRunPlan,
    RunKey,
    build_run_plan,
    run_plan_from_mapping,
)


DEV_RETRIEVAL_PROTOCOL_VERSION = "dev6-retrieval-e1-e6-v1"
DEV_RECOVERY_PROTOCOL_VERSION = "dev6-explicit-provider-response-retry-v1"
DEV_HOTFIX_RECOVERY_PROTOCOL_VERSION = "dev6-empty-content-hotfix-retry-v1"
DEV_CONDITIONS = ("E1", "E2", "E3", "E4", "E5", "E6")
CONDITION_METHODS: Mapping[str, tuple[str, str]] = {
    "E1": ("r1", "s1"),
    "E2": ("r2", "s1"),
    "E3": ("r1", "s2"),
    "E4": ("r2", "s2"),
    "E5": ("r1", "s3"),
    "E6": ("r3", "s3"),
}
DEV_GOLD_SHA256 = "7df334500d8ae394a121674e38b0553bc3136f850df896a5e936e0dd952009f0"
_SAFE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}\Z")


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _write_exclusive(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = canonical_json_bytes(value) + b"\n"
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(path, flags, 0o644)
    try:
        offset = 0
        while offset < len(payload):
            written = os.write(descriptor, payload[offset:])
            if written <= 0:
                raise OSError("short exclusive write")
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


def _hash_mapping(value: Mapping[str, Any]) -> str:
    return sha256_bytes(canonical_json_bytes(value))


def _manifest_body(
    *, plan: ExperimentRunPlan, budget_limit: int, requested_model: str
) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "protocol_version": DEV_RETRIEVAL_PROTOCOL_VERSION,
        "plan": plan.to_dict(),
        "question_set": "dev-6",
        "conditions": list(DEV_CONDITIONS),
        "condition_methods": {
            cell: {"retrieval_id": method, "store_id": store}
            for cell, (method, store) in CONDITION_METHODS.items()
        },
        "planned_episode_count": 36,
        "budget_unit": "characters",
        "budget_limit": budget_limit,
        "requested_model": requested_model,
        "api_style": "portable",
        "execution_order_policy": "question-major-rotated-e1-e6",
        "stop_on_failure": True,
        "gold_access_policy": "only-after-all-retrieval-artifacts-verify",
        "budget_review_rule": {
            "rerun_if_budget_skips_episode_fraction_gte": 0.20,
            "rerun_if_any_empty_budget_stop": True,
            "rerun_scope": "all-36-episodes",
        },
        "e5_token_warning_rule": {
            "comparison": "E5 mean total tokens / median of other condition means",
            "warning_ratio_gte": 2.0,
        },
    }


def prepare_dev_run(
    *,
    repo_root: Path,
    output_root: Path,
    run_id: str,
    budget_limit: int,
    requested_model: str = "coding",
) -> Path:
    if _SAFE.fullmatch(run_id) is None:
        raise EvidenceValidationError("Stage 3 run_id is unsafe")
    if budget_limit < 1:
        raise EvidenceValidationError("Stage 3 evidence budget must be positive")
    if not requested_model.strip():
        raise EvidenceValidationError("Stage 3 requested model is empty")
    root = Path(repo_root).resolve()
    questions = load_question_inputs(root, "dev-6")
    if len(questions) != 6:
        raise EvidenceValidationError("Stage 3 requires exactly six dev questions")
    stores = {name: load_r1_store(root, name) for name in ("s1", "s2", "s3")}
    runtime = {
        "protocol_version": DEV_RETRIEVAL_PROTOCOL_VERSION,
        "budget_unit": "characters",
        "budget_limit": budget_limit,
        "requested_model": requested_model,
        "api_style": "portable",
        "conditions": list(DEV_CONDITIONS),
    }
    plan = build_run_plan(
        run_id=run_id,
        question_set_id=questions[0].question_set_id,
        question_ids=tuple(item.question_id for item in questions),
        condition_ids=DEV_CONDITIONS,
        config_hashes={
            "dev_input": str(QUESTION_INPUTS["dev-6"]["sha256"]),
            "runtime": _hash_mapping(runtime),
            "s1_tree": stores["s1"].snapshot.tree_sha256,
            "s2_tree": stores["s2"].snapshot.tree_sha256,
            "s3_tree": stores["s3"].snapshot.tree_sha256,
        },
    )
    body = _manifest_body(
        plan=plan, budget_limit=budget_limit, requested_model=requested_model
    )
    manifest = {"manifest_id": "manifest-" + _hash_mapping(body), **body}
    run_root = Path(output_root).resolve() / run_id
    run_root.mkdir(parents=True, exist_ok=True)
    manifest_path = run_root / "manifest.json"
    if manifest_path.exists():
        existing = load_manifest(manifest_path)
        if existing != manifest:
            raise EvidenceValidationError("Existing Stage 3 manifest differs")
    else:
        _write_exclusive(manifest_path, manifest)
        _append_event(
            run_root / "events.jsonl",
            {"event": "prepared", "at": _utc_now(), "manifest_id": manifest["manifest_id"]},
        )
    write_status(repo_root=root, output_root=output_root, run_id=run_id)
    return manifest_path


def load_manifest(path: Path) -> dict[str, Any]:
    lexical = Path(path)
    if lexical.is_symlink() or not lexical.is_file():
        raise EvidenceValidationError("Stage 3 manifest is not a regular file")
    value = json.loads(lexical.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise EvidenceValidationError("Stage 3 manifest must be an object")
    manifest_id = value.get("manifest_id")
    body = {key: nested for key, nested in value.items() if key != "manifest_id"}
    if manifest_id != "manifest-" + _hash_mapping(body):
        raise EvidenceValidationError("Stage 3 manifest hash differs")
    if (
        body.get("schema_version") != 1
        or body.get("protocol_version") != DEV_RETRIEVAL_PROTOCOL_VERSION
        or body.get("conditions") != list(DEV_CONDITIONS)
        or body.get("planned_episode_count") != 36
        or body.get("budget_unit") != "characters"
        or body.get("api_style") != "portable"
        or body.get("stop_on_failure") is not True
    ):
        raise EvidenceValidationError("Stage 3 manifest contract differs")
    plan = run_plan_from_mapping(body.get("plan"))
    if tuple(plan.condition_ids) != DEV_CONDITIONS or len(plan.execution_order) != 36:
        raise EvidenceValidationError("Stage 3 plan differs")
    return value


def _verify_success(
    *, repo_root: Path, artifact: Path, condition_id: str, cache: dict[str, Any]
) -> EvidenceBundle:
    method, store_id = CONDITION_METHODS[condition_id]
    if method == "r1":
        store = cache.setdefault(f"store-{store_id}", load_r1_store(repo_root, store_id))
        return verify_r1_episode_artifact(artifact, loaded_store=store)
    if method == "r2":
        store = cache.setdefault(f"store-{store_id}", load_r1_store(repo_root, store_id))
        return verify_r2_episode_artifact(artifact, loaded_store=store)
    corpus = cache.setdefault("r3-corpus", load_r3_corpus(repo_root))
    return verify_r3_episode_artifact(artifact, corpus=corpus)


def _verify_failure(path: Path, condition_id: str):
    method, _ = CONDITION_METHODS[condition_id]
    if method == "r1":
        return verify_r1_failure_artifact(path)
    elif method == "r2":
        return verify_r2_failure_artifact(path)
    else:
        return verify_r3_failure_artifact(path)


def _scan(
    *, repo_root: Path, output_root: Path, run_id: str
) -> tuple[dict[RunKey, EvidenceBundle], list[dict[str, str]], ExperimentRunPlan, dict[str, Any]]:
    run_root = Path(output_root).resolve() / run_id
    manifest = load_manifest(run_root / "manifest.json")
    plan = run_plan_from_mapping(manifest["plan"])
    completed: dict[RunKey, EvidenceBundle] = {}
    failures: list[dict[str, str]] = []
    cache: dict[str, Any] = {}
    for key in plan.execution_order:
        artifact = run_root / key.condition_id / key.question_id
        if artifact.exists():
            bundle = _verify_success(
                repo_root=repo_root,
                artifact=artifact,
                condition_id=key.condition_id,
                cache=cache,
            )
            if (
                bundle.question.question_id != key.question_id
                or bundle.condition["condition_id"] != key.condition_id
                or bundle.budget.unit != manifest["budget_unit"]
                or bundle.budget.limit != manifest["budget_limit"]
                or bundle.model["requested_model"] != manifest["requested_model"]
            ):
                raise EvidenceValidationError("Stage 3 artifact differs from its plan")
            completed[key] = bundle
        parent = artifact.parent
        if parent.is_dir():
            for failed in sorted(parent.glob(f"{key.question_id}.failed-*")):
                failure = _verify_failure(failed, key.condition_id)
                failures.append(
                    {
                        "condition_id": key.condition_id,
                        "question_id": key.question_id,
                        "artifact_path": str(failed.resolve()),
                        "failure_id": failure.failure_id,
                        "failure_kind": failure.failure_kind,
                        "total_tokens": int(failure.metrics["total_tokens"]),
                        "requested_model": str(failure.model["requested_model"]),
                        "served_models": list(failure.model["served_models"]),
                    }
                )
    return completed, failures, plan, manifest


def _state(
    *, completed: Mapping[RunKey, EvidenceBundle], failures: Sequence[Mapping[str, str]],
    plan: ExperimentRunPlan,
) -> dict[str, Any]:
    pending = [key for key in plan.execution_order if key not in completed]
    active_failures = [
        item
        for item in failures
        if RunKey(item["condition_id"], item["question_id"]) not in completed
    ]
    recovered_failures = [item for item in failures if item not in active_failures]
    status = "completed" if not pending else ("failed" if active_failures else "pending")
    return {
        "schema_version": 1,
        "protocol_version": DEV_RETRIEVAL_PROTOCOL_VERSION,
        "run_id": plan.run_id,
        "plan_id": plan.plan_id,
        "status": status,
        "planned_episode_count": len(plan.execution_order),
        "verified_episode_count": len(completed),
        "pending_episode_count": len(pending),
        "capped_episode_count": sum(bundle.status == "capped" for bundle in completed.values()),
        "failure_count": len(active_failures),
        "method_failure_attempt_count": len(failures),
        "recovered_failure_count": len(recovered_failures),
        "next_key": pending[0].to_dict() if pending and not active_failures else None,
        "failures": active_failures,
        "historical_failures": recovered_failures,
        "updated_at": _utc_now(),
    }


def write_status(*, repo_root: Path, output_root: Path, run_id: str) -> dict[str, Any]:
    completed, failures, plan, _ = _scan(
        repo_root=Path(repo_root).resolve(), output_root=output_root, run_id=run_id
    )
    state = _state(completed=completed, failures=failures, plan=plan)
    driver_failure_path = Path(output_root).resolve() / run_id / "driver-failure.json"
    if driver_failure_path.is_file() and state["status"] != "completed":
        driver_failure = json.loads(driver_failure_path.read_text(encoding="utf-8"))
        state["driver_failure"] = driver_failure
        failed_key = RunKey(
            driver_failure["condition_id"], driver_failure["question_id"]
        )
        # A duplicate launcher can lose the atomic publication race after the
        # original process has already published the same key.  Preserve that
        # incident, but do not mislabel the surviving run as failed once the
        # final artifact for the key has independently verified.
        state["driver_failure_historical"] = failed_key in completed
        if failed_key not in completed:
            state["status"] = "failed"
    else:
        state["driver_failure"] = None
        state["driver_failure_historical"] = False
    _write_atomic(Path(output_root).resolve() / run_id / "status.json", state)
    return state


def _safe_error(error: BaseException, provider: ChatProvider) -> str:
    message = " ".join(str(error).split())[:800]
    secret = getattr(provider, "api_key", None)
    if isinstance(secret, str) and secret:
        message = message.replace(secret, "[REDACTED_KEY]")
    return re.sub(r"\b(?:clsk|sk)[_-][A-Za-z0-9_-]{10,}\b", "[REDACTED_KEY]", message)


def authorize_provider_response_retry(
    *, repo_root: Path, output_root: Path, run_id: str
) -> Path:
    """Freeze one explicit whole-episode retry for one verified format failure."""
    root = Path(repo_root).resolve()
    completed, failures, plan, manifest = _scan(
        repo_root=root, output_root=output_root, run_id=run_id
    )
    active = [
        item
        for item in failures
        if RunKey(item["condition_id"], item["question_id"]) not in completed
    ]
    if len(active) != 1 or active[0]["failure_kind"] != "provider_response":
        raise EvidenceValidationError(
            "Recovery requires exactly one active provider_response failure"
        )
    failure = active[0]
    body = {
        "schema_version": 1,
        "protocol_version": DEV_RECOVERY_PROTOCOL_VERSION,
        "run_id": run_id,
        "plan_id": plan.plan_id,
        "manifest_id": manifest["manifest_id"],
        "retry_key": {
            "condition_id": failure["condition_id"],
            "question_id": failure["question_id"],
        },
        "eligible_failure_id": failure["failure_id"],
        "eligible_failure_kind": "provider_response",
        "maximum_whole_episode_retries": 1,
        "preserve_failure_artifact": True,
        "include_failed_attempt_cost_in_summary": True,
        "reason": "served model returned no textual ReAct content",
        "authorization": "explicit-user-approval-after-dev-failure",
    }
    policy = {"recovery_id": "recovery-" + _hash_mapping(body), **body}
    path = Path(output_root).resolve() / run_id / "recovery-policy.json"
    if path.exists():
        existing = load_recovery_policy(path)
        if existing != policy:
            raise EvidenceValidationError("Existing recovery policy differs")
    else:
        _write_exclusive(path, policy)
        _append_event(
            path.parent / "events.jsonl",
            {
                "event": "recovery_authorized",
                "at": _utc_now(),
                "recovery_id": policy["recovery_id"],
                **body["retry_key"],
                "failure_id": failure["failure_id"],
            },
        )
    return path


def load_recovery_policy(path: Path) -> dict[str, Any]:
    lexical = Path(path)
    if lexical.is_symlink() or not lexical.is_file():
        raise EvidenceValidationError("Recovery policy is not a regular file")
    value = json.loads(lexical.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise EvidenceValidationError("Recovery policy must be an object")
    recovery_id = value.get("recovery_id")
    body = {key: nested for key, nested in value.items() if key != "recovery_id"}
    if recovery_id != "recovery-" + _hash_mapping(body):
        raise EvidenceValidationError("Recovery policy hash differs")
    if (
        body.get("schema_version") != 1
        or body.get("protocol_version") != DEV_RECOVERY_PROTOCOL_VERSION
        or body.get("eligible_failure_kind") != "provider_response"
        or body.get("maximum_whole_episode_retries") != 1
        or body.get("preserve_failure_artifact") is not True
        or body.get("include_failed_attempt_cost_in_summary") is not True
    ):
        raise EvidenceValidationError("Recovery policy contract differs")
    return value


def authorize_empty_content_hotfix_retry(
    *, repo_root: Path, output_root: Path, run_id: str
) -> Path:
    """Bind one post-hotfix retry to all prior empty-content failures."""
    root = Path(repo_root).resolve()
    completed, failures, plan, manifest = _scan(
        repo_root=root, output_root=output_root, run_id=run_id
    )
    active = [
        item
        for item in failures
        if RunKey(item["condition_id"], item["question_id"]) not in completed
    ]
    keys = {RunKey(item["condition_id"], item["question_id"]) for item in active}
    if (
        len(active) < 2
        or len(keys) != 1
        or any(item["failure_kind"] != "provider_response" for item in active)
    ):
        raise EvidenceValidationError(
            "Hotfix recovery requires repeated provider_response failures for one key"
        )
    key = next(iter(keys))
    if key.condition_id not in {"E2", "E4", "E6"}:
        raise EvidenceValidationError("Hotfix recovery is only for textual ReAct cells")
    body = {
        "schema_version": 1,
        "protocol_version": DEV_HOTFIX_RECOVERY_PROTOCOL_VERSION,
        "run_id": run_id,
        "plan_id": plan.plan_id,
        "manifest_id": manifest["manifest_id"],
        "retry_key": key.to_dict(),
        "prior_failure_ids": sorted(item["failure_id"] for item in active),
        "prior_failure_kind": "provider_response",
        "prior_failed_attempt_total_tokens": sum(item["total_tokens"] for item in active),
        "maximum_post_hotfix_retries": 1,
        "hotfix": "empty or null textual content becomes invalid_action and consumes one of four actions",
        "r2_agent_protocol_version": "r2-raw-agent-v2-empty-content-repair",
        "r3_agent_protocol_version": "r3-curated-agent-v2-empty-content-repair",
        "preserve_all_failure_artifacts": True,
        "include_all_failed_attempt_cost_in_summary": True,
        "authorization": "explicit-user-approval-to-fix-and-continue",
    }
    policy = {"hotfix_recovery_id": "hotfix-recovery-" + _hash_mapping(body), **body}
    path = Path(output_root).resolve() / run_id / "hotfix-recovery-policy.json"
    if path.exists():
        existing = load_hotfix_recovery_policy(path)
        if existing != policy:
            raise EvidenceValidationError("Existing hotfix recovery policy differs")
    else:
        _write_exclusive(path, policy)
        _append_event(
            path.parent / "events.jsonl",
            {
                "event": "hotfix_recovery_authorized",
                "at": _utc_now(),
                "hotfix_recovery_id": policy["hotfix_recovery_id"],
                **key.to_dict(),
                "prior_failure_ids": body["prior_failure_ids"],
            },
        )
    return path


def load_hotfix_recovery_policy(path: Path) -> dict[str, Any]:
    lexical = Path(path)
    if lexical.is_symlink() or not lexical.is_file():
        raise EvidenceValidationError("Hotfix recovery policy is not a regular file")
    value = json.loads(lexical.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise EvidenceValidationError("Hotfix recovery policy must be an object")
    identity = value.get("hotfix_recovery_id")
    body = {key: nested for key, nested in value.items() if key != "hotfix_recovery_id"}
    if identity != "hotfix-recovery-" + _hash_mapping(body):
        raise EvidenceValidationError("Hotfix recovery policy hash differs")
    if (
        body.get("schema_version") != 1
        or body.get("protocol_version") != DEV_HOTFIX_RECOVERY_PROTOCOL_VERSION
        or body.get("prior_failure_kind") != "provider_response"
        or body.get("maximum_post_hotfix_retries") != 1
        or body.get("preserve_all_failure_artifacts") is not True
        or body.get("include_all_failed_attempt_cost_in_summary") is not True
    ):
        raise EvidenceValidationError("Hotfix recovery policy contract differs")
    return value


def recover_empty_content_and_continue(
    *, repo_root: Path, output_root: Path, run_id: str, provider: ChatProvider
) -> dict[str, Any]:
    root = Path(repo_root).resolve()
    run_root = Path(output_root).resolve() / run_id
    completed, failures, plan, manifest = _scan(
        repo_root=root, output_root=output_root, run_id=run_id
    )
    policy = load_hotfix_recovery_policy(run_root / "hotfix-recovery-policy.json")
    if (
        policy["run_id"] != run_id
        or policy["plan_id"] != plan.plan_id
        or policy["manifest_id"] != manifest["manifest_id"]
    ):
        raise EvidenceValidationError("Hotfix recovery identity differs")
    key = RunKey(**policy["retry_key"])
    if key in completed or key.condition_id not in {"E2", "E4", "E6"}:
        raise EvidenceValidationError("Hotfix recovery key is not a pending textual ReAct cell")
    active = [
        item for item in failures
        if RunKey(item["condition_id"], item["question_id"]) == key
    ]
    if sorted(item["failure_id"] for item in active) != policy["prior_failure_ids"]:
        raise EvidenceValidationError("Hotfix recovery failure history differs")
    if getattr(provider, "api_style", None) != manifest["api_style"]:
        raise EvidenceValidationError("Live provider API style differs")
    if getattr(provider, "model", None) not in {None, manifest["requested_model"]}:
        raise EvidenceValidationError("Live provider model differs")
    question = next(
        item for item in load_question_inputs(root, "dev-6")
        if item.question_id == key.question_id
    )
    store_id = CONDITION_METHODS[key.condition_id][1]
    events = run_root / "events.jsonl"
    _append_event(
        events,
        {
            "event": "hotfix_recovery_retry_started",
            "at": _utc_now(),
            "sequence": plan.execution_order.index(key) + 1,
            **key.to_dict(),
            "hotfix_recovery_id": policy["hotfix_recovery_id"],
        },
    )
    if key.condition_id in {"E2", "E4"}:
        result = execute_r2_question(
            repo_root=root,
            output_root=output_root,
            run_id=run_id,
            cell_id=key.condition_id,
            question=question,
            provider=provider,
            requested_model=manifest["requested_model"],
            budget_unit="characters",
            budget_limit=manifest["budget_limit"],
            corpus=build_r2_raw_corpus(root, store_id),
        )
    else:
        result = execute_r3_question(
            repo_root=root,
            output_root=output_root,
            run_id=run_id,
            question=question,
            provider=provider,
            requested_model=manifest["requested_model"],
            budget_unit="characters",
            budget_limit=manifest["budget_limit"],
            corpus=load_r3_corpus(root),
        )
    if result.status == "failed":
        _append_event(
            events,
            {"event": "hotfix_recovery_failed", "at": _utc_now(), **result.to_dict()},
        )
        write_status(repo_root=root, output_root=output_root, run_id=run_id)
        return {"status": "failed", "result": result.to_dict()}
    bundle = _verify_success(
        repo_root=root,
        artifact=result.artifact_path,
        condition_id=key.condition_id,
        cache={},
    )
    _append_event(
        events,
        {
            "event": "episode_verified",
            "at": _utc_now(),
            "sequence": plan.execution_order.index(key) + 1,
            **key.to_dict(),
            "status": bundle.status,
            "bundle_id": bundle.bundle_id,
            "evidence_items": len(bundle.evidence_items),
            "budget_used": bundle.budget.used,
            "budget_skipped_items": bundle.budget.skipped_items,
            "hit_cap": bundle.stop.hit_cap,
            "total_tokens": bundle.metrics["total_tokens"],
            "served_models": list(bundle.model["served_models"]),
            "store_tree_sha256": bundle.store_snapshot.tree_sha256,
            "recovered_by": policy["hotfix_recovery_id"],
        },
    )
    write_status(repo_root=root, output_root=output_root, run_id=run_id)
    return run_dev_retrieval(
        repo_root=root,
        output_root=output_root,
        run_id=run_id,
        provider=provider,
    )


def _validate_recovery(
    *, run_root: Path, plan: ExperimentRunPlan, manifest: Mapping[str, Any],
    completed: Mapping[RunKey, EvidenceBundle], failures: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    policy = load_recovery_policy(run_root / "recovery-policy.json")
    if policy["run_id"] != plan.run_id or policy["plan_id"] != plan.plan_id:
        raise EvidenceValidationError("Recovery policy plan identity differs")
    if policy["manifest_id"] != manifest["manifest_id"]:
        raise EvidenceValidationError("Recovery policy manifest identity differs")
    key = RunKey(**policy["retry_key"])
    eligible = [
        item
        for item in failures
        if RunKey(item["condition_id"], item["question_id"]) == key
        and item["failure_id"] == policy["eligible_failure_id"]
        and item["failure_kind"] == "provider_response"
    ]
    if len(eligible) != 1 or key in completed:
        raise EvidenceValidationError("Recovery policy no longer matches one pending failure")
    if len([item for item in failures if RunKey(item["condition_id"], item["question_id"]) == key]) != 1:
        raise EvidenceValidationError("Recovery retry limit has already been exhausted")
    return policy


def run_dev_retrieval(
    *, repo_root: Path, output_root: Path, run_id: str, provider: ChatProvider,
    allow_authorized_recovery: bool = False,
) -> dict[str, Any]:
    root = Path(repo_root).resolve()
    completed, failures, plan, manifest = _scan(
        repo_root=root, output_root=output_root, run_id=run_id
    )
    run_root = Path(output_root).resolve() / run_id
    active_failures = [
        item
        for item in failures
        if RunKey(item["condition_id"], item["question_id"]) not in completed
    ]
    recovery = None
    if active_failures:
        if not allow_authorized_recovery:
            raise EvidenceValidationError(
                "Stage 3 has a verified failure artifact; refusing automatic retry"
            )
        recovery = _validate_recovery(
            run_root=run_root,
            plan=plan,
            manifest=manifest,
            completed=completed,
            failures=failures,
        )
    if getattr(provider, "api_style", None) != manifest["api_style"]:
        raise EvidenceValidationError("Live provider API style differs from Stage 3 manifest")
    provider_model = getattr(provider, "model", None)
    if provider_model is not None and provider_model != manifest["requested_model"]:
        raise EvidenceValidationError("Live provider model differs from Stage 3 manifest")
    questions = {item.question_id: item for item in load_question_inputs(root, "dev-6")}
    stores = {name: load_r1_store(root, name) for name in ("s1", "s2", "s3")}
    r2_corpora = {name: build_r2_raw_corpus(root, name) for name in ("s1", "s2")}
    r3_corpus = load_r3_corpus(root)
    events = run_root / "events.jsonl"
    _append_event(events, {"event": "run_started", "at": _utc_now(), "completed_before": len(completed)})
    print(
        f"Stage 3 resume checkpoint: {len(completed)}/{len(plan.execution_order)} "
        "episodes verified.",
        flush=True,
    )
    for sequence, key in enumerate(plan.execution_order, 1):
        if key in completed:
            continue
        key_failures = [
            item for item in active_failures
            if RunKey(item["condition_id"], item["question_id"]) == key
        ]
        if key_failures:
            if recovery is None or key.to_dict() != recovery["retry_key"]:
                raise EvidenceValidationError("Pending key has no authorized recovery")
            _append_event(
                events,
                {
                    "event": "recovery_retry_started",
                    "at": _utc_now(),
                    "sequence": sequence,
                    **key.to_dict(),
                    "recovery_id": recovery["recovery_id"],
                    "prior_failure_id": key_failures[0]["failure_id"],
                },
            )
        print(
            f"[{sequence:02d}/{len(plan.execution_order)}] START "
            f"{key.condition_id} {key.question_id}",
            flush=True,
        )
        _append_event(events, {"event": "episode_started", "at": _utc_now(), "sequence": sequence, **key.to_dict()})
        question = questions[key.question_id]
        method, store_id = CONDITION_METHODS[key.condition_id]
        try:
            if method == "r1":
                result = execute_r1_question(
                    repo_root=root, output_root=output_root, run_id=run_id,
                    cell_id=key.condition_id, question=question, provider=provider,
                    requested_model=manifest["requested_model"], budget_unit="characters",
                    budget_limit=manifest["budget_limit"], loaded_store=stores[store_id],
                )
            elif method == "r2":
                result = execute_r2_question(
                    repo_root=root, output_root=output_root, run_id=run_id,
                    cell_id=key.condition_id, question=question, provider=provider,
                    requested_model=manifest["requested_model"], budget_unit="characters",
                    budget_limit=manifest["budget_limit"], corpus=r2_corpora[store_id],
                )
            else:
                result = execute_r3_question(
                    repo_root=root, output_root=output_root, run_id=run_id,
                    question=question, provider=provider,
                    requested_model=manifest["requested_model"], budget_unit="characters",
                    budget_limit=manifest["budget_limit"], corpus=r3_corpus,
                )
        except Exception as error:
            failure = {
                "schema_version": 1,
                "protocol_version": DEV_RETRIEVAL_PROTOCOL_VERSION,
                "run_id": run_id,
                "sequence": sequence,
                **key.to_dict(),
                "error_type": type(error).__name__,
                "message": _safe_error(error, provider),
                "at": _utc_now(),
            }
            _write_atomic(run_root / "driver-failure.json", failure)
            _append_event(events, {"event": "driver_failed", **failure})
            write_status(repo_root=root, output_root=output_root, run_id=run_id)
            raise
        if result.status == "failed":
            _append_event(events, {"event": "episode_failed", "at": _utc_now(), "sequence": sequence, **result.to_dict()})
            write_status(repo_root=root, output_root=output_root, run_id=run_id)
            print(
                f"[{sequence:02d}/{len(plan.execution_order)}] FAILED "
                f"{key.condition_id} {key.question_id}; stopping.",
                flush=True,
            )
            return {"status": "failed", "result": result.to_dict()}
        bundle = _verify_success(
            repo_root=root, artifact=result.artifact_path,
            condition_id=key.condition_id, cache={f"store-{store_id}": stores[store_id], "r3-corpus": r3_corpus},
        )
        completed[key] = bundle
        _append_event(
            events,
            {
                "event": "episode_verified", "at": _utc_now(), "sequence": sequence,
                **key.to_dict(), "status": bundle.status, "bundle_id": bundle.bundle_id,
                "evidence_items": len(bundle.evidence_items), "budget_used": bundle.budget.used,
                "budget_skipped_items": bundle.budget.skipped_items,
                "hit_cap": bundle.stop.hit_cap, "total_tokens": bundle.metrics["total_tokens"],
                "served_models": list(bundle.model["served_models"]),
                "store_tree_sha256": bundle.store_snapshot.tree_sha256,
            },
        )
        write_status(repo_root=root, output_root=output_root, run_id=run_id)
        print(
            f"[{sequence:02d}/{len(plan.execution_order)}] VERIFIED "
            f"status={bundle.status} evidence={len(bundle.evidence_items)} "
            f"budget={bundle.budget.used}/{bundle.budget.limit} "
            f"skipped={bundle.budget.skipped_items} cap={bundle.stop.hit_cap} "
            f"tokens={bundle.metrics['total_tokens']}",
            flush=True,
        )
    summary = build_summary(repo_root=root, output_root=output_root, run_id=run_id)
    _append_event(events, {"event": "run_completed", "at": _utc_now(), "summary_id": summary["summary_id"]})
    return summary


def _episode_row(sequence: int, key: RunKey, bundle: EvidenceBundle, gold: Any) -> dict[str, Any]:
    dia_ids = {dia for item in bundle.evidence_items for dia in item.dia_ids}
    locators = {locator for item in bundle.evidence_items for locator in item.source_locators}
    target = set(gold.gold_evidence_dia_ids)
    overlap = target & dia_ids
    recall = len(overlap) / len(target) if target else None
    return {
        "sequence": sequence,
        **key.to_dict(),
        "retrieval_id": bundle.condition["retrieval_id"],
        "store_id": bundle.condition["store_id"],
        "status": bundle.status,
        "stop_reason": bundle.stop.reason,
        "hit_cap": bundle.stop.hit_cap,
        "provider_rounds": bundle.metrics["provider_rounds"],
        "model_calls": bundle.metrics["model_calls"],
        "search_action_count": len(bundle.search_actions),
        "evidence_item_count": len(bundle.evidence_items),
        "unique_dia_id_count": len(dia_ids),
        "unique_locator_count": len(locators),
        "empty_evidence": len(bundle.evidence_items) == 0,
        "budget_unit": bundle.budget.unit,
        "budget_limit": bundle.budget.limit,
        "budget_used": bundle.budget.used,
        "budget_skipped_items": bundle.budget.skipped_items,
        "budget_truncated": bundle.budget.truncated,
        "prompt_tokens": bundle.metrics["prompt_tokens"],
        "completion_tokens": bundle.metrics["completion_tokens"],
        "total_tokens": bundle.metrics["total_tokens"],
        "requested_model": bundle.model["requested_model"],
        "served_models": list(bundle.model["served_models"]),
        "store_tree_sha256": bundle.store_snapshot.tree_sha256,
        "store_unchanged": bundle.integrity["store_unchanged"],
        "integrity_verified": bundle.integrity["verified"],
        "gold_evidence_count": len(target),
        "gold_evidence_hit_count": len(overlap),
        "evidence_recall": recall,
        "evidence_any_hit": bool(overlap) if target else None,
        "evidence_all_hit": target <= dia_ids if target else None,
        "bundle_id": bundle.bundle_id,
    }


def _has_empty_budget_outcome(rows: Sequence[Mapping[str, Any]]) -> bool:
    """Return whether budget packing erased every selected evidence item.

    The controller stop reason describes why model orchestration stopped, not
    necessarily what happened later when selected notes were packed into the
    shared evidence budget.  A round-capped episode can therefore still be an
    empty budget failure.
    """

    return any(
        bool(row["empty_evidence"]) and int(row["budget_skipped_items"]) > 0
        for row in rows
    )


def build_summary(*, repo_root: Path, output_root: Path, run_id: str) -> dict[str, Any]:
    root = Path(repo_root).resolve()
    completed, failures, plan, manifest = _scan(
        repo_root=root, output_root=output_root, run_id=run_id
    )
    active_failures = [
        item
        for item in failures
        if RunKey(item["condition_id"], item["question_id"]) not in completed
    ]
    if active_failures or len(completed) != len(plan.execution_order):
        raise EvidenceValidationError("Cannot summarize an incomplete Stage 3 run")
    gold_path = root / "experiments/locomo-conv50-v1/question-sets/dev-6-gold.jsonl"
    gold = {item.question_id: item for item in load_gold_records(gold_path, expected_sha256=DEV_GOLD_SHA256)}
    rows = [
        _episode_row(index, key, completed[key], gold[key.question_id])
        for index, key in enumerate(plan.execution_order, 1)
    ]
    by_condition: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        by_condition[row["condition_id"]].append(row)
    condition_summary: dict[str, Any] = {}
    for condition in DEV_CONDITIONS:
        items = by_condition[condition]
        condition_summary[condition] = {
            "episode_count": len(items),
            "capped_count": sum(item["hit_cap"] for item in items),
            "empty_evidence_count": sum(item["empty_evidence"] for item in items),
            "budget_skipped_episode_count": sum(item["budget_skipped_items"] > 0 for item in items),
            "budget_skipped_item_count": sum(item["budget_skipped_items"] for item in items),
            "evidence_item_count_total": sum(item["evidence_item_count"] for item in items),
            "evidence_item_count_mean": sum(item["evidence_item_count"] for item in items) / len(items),
            "evidence_recall_mean": sum(item["evidence_recall"] for item in items) / len(items),
            "evidence_any_hit_count": sum(item["evidence_any_hit"] for item in items),
            "evidence_all_hit_count": sum(item["evidence_all_hit"] for item in items),
            "prompt_tokens_total": sum(item["prompt_tokens"] for item in items),
            "total_tokens_total": sum(item["total_tokens"] for item in items),
            "total_tokens_mean": sum(item["total_tokens"] for item in items) / len(items),
            "total_tokens_max": max(item["total_tokens"] for item in items),
            "requested_models": sorted({item["requested_model"] for item in items}),
            "served_models": sorted({model for item in items for model in item["served_models"]}),
            "store_tree_hashes": sorted({item["store_tree_sha256"] for item in items}),
        }
    skipped_episodes = sum(row["budget_skipped_items"] > 0 for row in rows)
    empty_budget_stop = _has_empty_budget_outcome(rows)
    other_means = [condition_summary[cell]["total_tokens_mean"] for cell in DEV_CONDITIONS if cell != "E5"]
    e5_ratio = condition_summary["E5"]["total_tokens_mean"] / statistics.median(other_means)
    adjust = skipped_episodes / len(rows) >= 0.20 or empty_budget_stop
    recovered_failures = [
        item
        for item in failures
        if RunKey(item["condition_id"], item["question_id"]) in completed
    ]
    recovery_policy_paths = [
        Path(output_root).resolve() / run_id / "recovery-policy.json",
        Path(output_root).resolve() / run_id / "hotfix-recovery-policy.json",
    ]
    recovery_policies = []
    for recovery_path in recovery_policy_paths:
        if not recovery_path.exists():
            continue
        if recovery_path.name == "recovery-policy.json":
            recovery_policies.append(load_recovery_policy(recovery_path))
        else:
            recovery_policies.append(load_hotfix_recovery_policy(recovery_path))
    body = {
        "schema_version": 1,
        "protocol_version": DEV_RETRIEVAL_PROTOCOL_VERSION,
        "run_id": run_id,
        "plan_id": plan.plan_id,
        "manifest_id": manifest["manifest_id"],
        "status": "completed",
        "episode_count": len(rows),
        "budget_unit": manifest["budget_unit"],
        "budget_limit": manifest["budget_limit"],
        "episodes": rows,
        "overall": {
            "capped_episode_count": sum(row["hit_cap"] for row in rows),
            "empty_evidence_count": sum(row["empty_evidence"] for row in rows),
            "budget_skipped_episode_count": skipped_episodes,
            "budget_skipped_item_count": sum(row["budget_skipped_items"] for row in rows),
            "budget_truncated_episode_count": sum(row["budget_truncated"] for row in rows),
            "evidence_any_hit_count": sum(row["evidence_any_hit"] for row in rows),
            "evidence_all_hit_count": sum(row["evidence_all_hit"] for row in rows),
            "requested_models": sorted({row["requested_model"] for row in rows}),
            "served_models": sorted({model for row in rows for model in row["served_models"]}),
            "requested_model_consistent": len({row["requested_model"] for row in rows}) == 1,
            "served_model_consistent": len({model for row in rows for model in row["served_models"]}) == 1,
            "all_store_integrity_verified": all(row["store_unchanged"] and row["integrity_verified"] for row in rows),
        },
        "by_condition": condition_summary,
        "recovery_overhead": {
            "failed_attempt_count": len(recovered_failures),
            "failed_attempt_total_tokens": sum(item["total_tokens"] for item in recovered_failures),
            "failed_attempts": recovered_failures,
            "recovery_policies": recovery_policies if recovered_failures else [],
        },
        "budget_decision": {
            "decision": (
                "adjust-and-rerun-all-dev6"
                if adjust
                else f"freeze-candidate-{manifest['budget_limit']}"
            ),
            "budget_skipped_episode_fraction": skipped_episodes / len(rows),
            "empty_budget_stop": empty_budget_stop,
            "rule": manifest["budget_review_rule"],
        },
        "e5_token_cost_check": {
            "e5_mean_to_other_condition_median_ratio": e5_ratio,
            "warning": e5_ratio >= 2.0,
            "rule": manifest["e5_token_warning_rule"],
        },
    }
    summary = {"summary_id": "summary-" + _hash_mapping(body), **body}
    summary_path = Path(output_root).resolve() / run_id / "summary.json"
    if summary_path.exists():
        existing = json.loads(summary_path.read_text(encoding="utf-8"))
        if existing != summary:
            raise EvidenceValidationError("Existing Stage 3 summary differs")
    else:
        _write_exclusive(summary_path, summary)
    write_status(repo_root=root, output_root=output_root, run_id=run_id)
    return summary


def verify_dev_run(*, repo_root: Path, output_root: Path, run_id: str) -> dict[str, Any]:
    state = write_status(repo_root=repo_root, output_root=output_root, run_id=run_id)
    if state["status"] == "completed":
        summary = build_summary(repo_root=repo_root, output_root=output_root, run_id=run_id)
        state = {**state, "summary_id": summary["summary_id"]}
    return state
