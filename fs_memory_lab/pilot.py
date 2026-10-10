"""Resumable dev-6 E1--E7 answer, fusion, evaluation, and audit pilot."""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from .agent import ChatProvider
from .answerer import ANSWERER_SYSTEM_PROMPT_SHA256, SharedAnswerer
from .dev_retrieval import DEV_GOLD_SHA256
from .evaluation import aggregate_evaluations, evaluate_run_store, load_gold_records
from .evidence import EvidenceBundle, EvidenceValidationError, canonical_json_bytes, sha256_bytes
from .fusion import FUSION_CONTRACT_SHA256, FusionEvidenceBundle, build_e7_fusion_bundle
from .r1_artifacts import verify_r1_episode_artifact
from .r1_inputs import load_question_inputs, load_r1_store
from .r2_artifacts import verify_r2_episode_artifact
from .r2_index import R2RawIndex
from .r2_inputs import build_r2_raw_corpus
from .r2_protocol import R2_PARAMETERS
from .r3_artifacts import verify_r3_episode_artifact
from .r3_inputs import load_r3_corpus
from .run_records import (
    ExperimentRunPlan,
    ExperimentRunStore,
    RunKey,
    RunRecord,
    build_run_plan,
    run_plan_from_mapping,
    verify_run_store,
)


PILOT_PROTOCOL_VERSION = "dev6-e1-e7-pilot-v1"
PILOT_CONDITIONS = ("E1", "E2", "E3", "E4", "E5", "E6", "E7")
RETRIEVAL_CONDITIONS = PILOT_CONDITIONS[:-1]
CONDITION_STORES = {
    "E1": "s1", "E2": "s1", "E3": "s2", "E4": "s2", "E5": "s3", "E6": "s3"
}
SYSTEM_FAILURE_RATE_LIMIT = 0.05
BUDGET_SKIP_FRACTION_LIMIT = 0.20
TOKEN_SAFETY_LIMIT = 1_000_000


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _read_json(path: Path) -> dict[str, Any]:
    lexical = Path(path)
    if lexical.is_symlink() or not lexical.is_file():
        raise EvidenceValidationError(f"Unsafe or missing JSON artifact: {lexical}")
    value = json.loads(lexical.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise EvidenceValidationError("Pilot JSON artifact must contain an object")
    return value


def _write_exclusive(path: Path, value: Mapping[str, Any], mode: int = 0o644) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = canonical_json_bytes(value) + b"\n"
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(path, flags, mode)
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


@dataclass(frozen=True)
class RetrievalSource:
    repo_root: Path
    output_root: Path
    run_id: str
    manifest: Mapping[str, Any]
    summary: Mapping[str, Any]

    @property
    def run_root(self) -> Path:
        return self.output_root / self.run_id

    @property
    def budget_limit(self) -> int:
        return int(self.manifest["budget_limit"])


def load_retrieval_source(
    *, repo_root: Path, retrieval_output_root: Path, retrieval_run_id: str,
    require_frozen_budget: bool = True,
) -> RetrievalSource:
    root = Path(repo_root).resolve()
    output = Path(retrieval_output_root).resolve()
    run_root = output / retrieval_run_id
    manifest = _read_json(run_root / "manifest.json")
    summary = _read_json(run_root / "summary.json")
    if summary.get("status") != "completed" or summary.get("episode_count") != 36:
        raise EvidenceValidationError("Retrieval source is not a completed 36-episode dev-6 run")
    if summary.get("manifest_id") != manifest.get("manifest_id"):
        raise EvidenceValidationError("Retrieval summary and manifest identities differ")
    if manifest.get("budget_unit") != "characters":
        raise EvidenceValidationError("Pilot requires the frozen character evidence budget")
    expected = f"freeze-candidate-{manifest.get('budget_limit')}"
    if require_frozen_budget and summary.get("budget_decision", {}).get("decision") != expected:
        raise EvidenceValidationError("Retrieval evidence budget has not passed the dev-6 gate")
    return RetrievalSource(root, output, retrieval_run_id, manifest, summary)


def _bundle_loader(source: RetrievalSource):
    stores = {name: load_r1_store(source.repo_root, name) for name in ("s1", "s2", "s3")}
    r3_corpus = load_r3_corpus(source.repo_root)

    def load(condition_id: str, question_id: str) -> EvidenceBundle:
        artifact = source.run_root / condition_id / question_id
        if condition_id in {"E1", "E3", "E5"}:
            bundle = verify_r1_episode_artifact(
                artifact, loaded_store=stores[CONDITION_STORES[condition_id]]
            )
        elif condition_id in {"E2", "E4"}:
            bundle = verify_r2_episode_artifact(
                artifact, loaded_store=stores[CONDITION_STORES[condition_id]]
            )
        elif condition_id == "E6":
            bundle = verify_r3_episode_artifact(artifact, corpus=r3_corpus)
        else:
            raise EvidenceValidationError("Retrieval source condition is invalid")
        if bundle.condition.get("condition_id") != condition_id:
            raise EvidenceValidationError("Retrieval bundle condition differs")
        if bundle.question.question_id != question_id:
            raise EvidenceValidationError("Retrieval bundle question differs")
        if bundle.budget.unit != "characters" or bundle.budget.limit != source.budget_limit:
            raise EvidenceValidationError("Retrieval bundle budget differs from manifest")
        return bundle

    return load


def prepare_pilot(
    *, repo_root: Path, retrieval_output_root: Path, retrieval_run_id: str,
    output_root: Path, run_id: str, requested_model: str,
) -> Path:
    source = load_retrieval_source(
        repo_root=repo_root, retrieval_output_root=retrieval_output_root,
        retrieval_run_id=retrieval_run_id,
    )
    questions = load_question_inputs(source.repo_root, "dev-6")
    retrieval_manifest_path = source.run_root / "manifest.json"
    retrieval_summary_path = source.run_root / "summary.json"
    plan = build_run_plan(
        run_id=run_id,
        question_set_id=questions[0].question_set_id,
        question_ids=tuple(item.question_id for item in questions),
        condition_ids=PILOT_CONDITIONS,
        config_hashes={
            "answerer_prompt": ANSWERER_SYSTEM_PROMPT_SHA256,
            "fusion_contract": FUSION_CONTRACT_SHA256,
            "retrieval_manifest": sha256_bytes(retrieval_manifest_path.read_bytes()),
            "retrieval_summary": sha256_bytes(retrieval_summary_path.read_bytes()),
            "question_inputs": sha256_bytes(
                (source.repo_root / "experiments/locomo-conv50-v1/question-sets/dev-6-input.jsonl").read_bytes()
            ),
        },
    )
    store = ExperimentRunStore.create_or_open(Path(output_root).resolve(), plan)
    body = {
        "schema_version": 1,
        "protocol_version": PILOT_PROTOCOL_VERSION,
        "run_id": run_id,
        "plan_id": plan.plan_id,
        "question_set_id": plan.question_set_id,
        "retrieval_run_id": retrieval_run_id,
        "retrieval_output_root": str(source.output_root),
        "retrieval_summary_id": source.summary["summary_id"],
        "budget_unit": "characters",
        "budget_limit": source.budget_limit,
        "requested_model": requested_model,
        "api_style": source.manifest["api_style"],
        "answerer_prompt_sha256": ANSWERER_SYSTEM_PROMPT_SHA256,
        "fusion_contract_sha256": FUSION_CONTRACT_SHA256,
        "gold_access_boundary": "only after all 42 RunRecords are complete",
        "category_design_limit": (
            "dev-6 contains categories 1, 2, and 4 only; category 3 remains sealed in main-40"
        ),
        "acceptance_thresholds": {
            "planned_records": 42,
            "system_failure_rate_lt": SYSTEM_FAILURE_RATE_LIMIT,
            "budget_skip_episode_fraction_lt": BUDGET_SKIP_FRACTION_LIMIT,
            "token_safety_limit": TOKEN_SAFETY_LIMIT,
        },
    }
    manifest = {"pilot_manifest_id": "pilot-manifest-" + sha256_bytes(canonical_json_bytes(body)), **body}
    path = store.run_root / "pilot-manifest.json"
    if path.exists():
        if _read_json(path) != manifest:
            raise EvidenceValidationError("Existing pilot manifest differs")
    else:
        _write_exclusive(path, manifest)
        _append_event(store.run_root / "events.jsonl", {"event": "pilot_prepared", "at": _now()})
    write_pilot_status(output_root=output_root, run_id=run_id)
    return path


def _open_pilot(*, output_root: Path, run_id: str) -> tuple[ExperimentRunStore, dict[str, Any]]:
    store, _ = verify_run_store(Path(output_root).resolve(), run_id)
    manifest = _read_json(store.run_root / "pilot-manifest.json")
    if manifest.get("run_id") != run_id or manifest.get("plan_id") != store.plan.plan_id:
        raise EvidenceValidationError("Pilot manifest and plan differ")
    return store, manifest


def write_pilot_status(*, output_root: Path, run_id: str) -> dict[str, Any]:
    store, checkpoint = verify_run_store(Path(output_root).resolve(), run_id)
    manifest = _read_json(store.run_root / "pilot-manifest.json")
    completed_by_condition = {condition: 0 for condition in PILOT_CONDITIONS}
    answer_failure_attempts = 0
    for key in store.plan.execution_order:
        if store.load_completed(key) is not None:
            completed_by_condition[key.condition_id] += 1
        answer_failure_attempts += len(store.failure_attempts(key))
    body = {
        "schema_version": 1,
        "protocol_version": PILOT_PROTOCOL_VERSION,
        "run_id": run_id,
        "plan_id": store.plan.plan_id,
        "retrieval_run_id": manifest["retrieval_run_id"],
        "planned_records": checkpoint["planned"],
        "completed_records": checkpoint["completed"],
        "pending_records": checkpoint["pending"],
        "answer_failure_attempts": answer_failure_attempts,
        "completed_by_condition": completed_by_condition,
        "status": "completed" if checkpoint["pending"] == 0 else "pending",
        "updated_at": _now(),
    }
    _write_atomic(store.run_root / "status.json", body)
    return body


def _safe_message(error: Exception) -> str:
    text = str(error).strip() or type(error).__name__
    return text[:1000]


def run_pilot(
    *, repo_root: Path, output_root: Path, run_id: str, provider: ChatProvider,
) -> dict[str, Any]:
    store, manifest = _open_pilot(output_root=output_root, run_id=run_id)
    if getattr(provider, "api_style", None) != manifest["api_style"]:
        raise EvidenceValidationError("Pilot provider API style differs")
    if getattr(provider, "model", None) not in {None, manifest["requested_model"]}:
        raise EvidenceValidationError("Pilot provider model differs")
    source = load_retrieval_source(
        repo_root=repo_root,
        retrieval_output_root=Path(manifest["retrieval_output_root"]),
        retrieval_run_id=manifest["retrieval_run_id"],
    )
    load_bundle = _bundle_loader(source)
    answerer = SharedAnswerer(provider=provider, requested_model=manifest["requested_model"])
    events = store.run_root / "events.jsonl"
    _append_event(events, {"event": "answer_run_started", "at": _now()})

    primary = [key for key in store.plan.execution_order if key.condition_id != "E7"]
    fusion = [key for key in store.plan.execution_order if key.condition_id == "E7"]
    for key in (*primary, *fusion):
        if store.load_completed(key) is not None:
            continue
        print(f"ANSWER START {key.condition_id} {key.question_id}", flush=True)
        _append_event(events, {"event": "answer_started", "at": _now(), **key.to_dict()})
        if key.condition_id == "E7":
            raw = store.load_completed(RunKey("E2", key.question_id))
            curated = store.load_completed(RunKey("E6", key.question_id))
            if raw is None or curated is None:
                raise EvidenceValidationError("E7 reached before E2 and E6")
            if not isinstance(raw.evidence_bundle, EvidenceBundle) or not isinstance(
                curated.evidence_bundle, EvidenceBundle
            ):
                raise EvidenceValidationError("E7 source records are not retrieval bundles")
            bundle: EvidenceBundle | FusionEvidenceBundle = build_e7_fusion_bundle(
                raw.evidence_bundle, curated.evidence_bundle
            )
        else:
            bundle = load_bundle(key.condition_id, key.question_id)
        try:
            answer = answerer.run(bundle)
        except Exception as error:
            store.publish_failure(
                key=key,
                stage=getattr(error, "stage", "answerer"),
                error_type=type(error).__name__,
                message=_safe_message(error),
                retryable=False,
            )
            _append_event(
                events,
                {"event": "answer_failed", "at": _now(), **key.to_dict(), "error_type": type(error).__name__},
            )
            write_pilot_status(output_root=output_root, run_id=run_id)
            return {"status": "failed", **key.to_dict(), "error_type": type(error).__name__}
        record = RunRecord.create(
            plan_id=store.plan.plan_id,
            run_id=run_id,
            condition_id=key.condition_id,
            evidence_bundle=bundle,
            answer_result=answer,
        )
        store.publish_success(record)
        _append_event(
            events,
            {
                "event": "answer_verified", "at": _now(), **key.to_dict(),
                "record_id": record.record_id, "answer_id": answer.answer_id,
                "citations": len(answer.citations), "answer_tokens": record.answer_metrics["total_tokens"],
                "served_models": list(answer.served_models),
            },
        )
        status = write_pilot_status(output_root=output_root, run_id=run_id)
        print(
            f"ANSWER VERIFIED {key.condition_id} {key.question_id} "
            f"({status['completed_records']}/42)", flush=True,
        )

    return finalize_pilot(repo_root=repo_root, output_root=output_root, run_id=run_id)


def _first_search(path: Path) -> Mapping[str, Any]:
    for line in (path / "trace.jsonl").read_text(encoding="utf-8").splitlines():
        event = json.loads(line)
        if event.get("event") == "action" and event.get("action") == "search_chatrecord":
            return event["arguments"]
    raise EvidenceValidationError("R2 trace lacks a first search action")


def _r2_first_rank_signature(source: RetrievalSource, condition: str, question_id: str) -> tuple[Any, ...]:
    store_id = "s1" if condition == "E2" else "s2"
    arguments = _first_search(source.run_root / condition / question_id)
    return (
        tuple(arguments.get("keywords", ())),
        arguments.get("date_from"),
        arguments.get("date_to"),
        _r2_rank_signature(source.repo_root, store_id, arguments),
    )


def _r2_rank_signature(
    repo_root: Path, store_id: str, arguments: Mapping[str, Any],
) -> tuple[Any, ...]:
    result = R2RawIndex(build_r2_raw_corpus(repo_root, store_id)).search(
        arguments["keywords"], top_k=arguments["top_k"],
        context_window=int(R2_PARAMETERS["context_window"]),
        date_from=arguments.get("date_from"), date_to=arguments.get("date_to"),
    )
    return tuple(
        (hit.anchor.dia_ids, tuple(x.dia_ids for x in hit.context), round(hit.rrf_score, 12))
        for hit in result.hits
    )


def _r2_first_rank_backend_invariant(
    source: RetrievalSource, condition: str, question_id: str,
) -> bool:
    """Check storage-layout invariance while holding the first query fixed."""

    arguments = _first_search(source.run_root / condition / question_id)
    return _r2_rank_signature(source.repo_root, "s1", arguments) == _r2_rank_signature(
        source.repo_root, "s2", arguments
    )


def build_pilot_audit(
    *, repo_root: Path, output_root: Path, run_id: str,
) -> dict[str, Any]:
    store, manifest = _open_pilot(output_root=output_root, run_id=run_id)
    checkpoint = store.checkpoint()
    if checkpoint["completed"] != 42 or checkpoint["pending"] != 0:
        raise EvidenceValidationError("Cannot audit an incomplete 42-record pilot")
    source = load_retrieval_source(
        repo_root=repo_root,
        retrieval_output_root=Path(manifest["retrieval_output_root"]),
        retrieval_run_id=manifest["retrieval_run_id"],
    )
    records = [store.load_completed(key) for key in store.plan.execution_order]
    if any(item is None for item in records):
        raise EvidenceValidationError("Pilot record disappeared during audit")
    completed = [item for item in records if item is not None]
    answer_failures = sum(len(store.failure_attempts(key)) for key in store.plan.execution_order)
    retrieval_failures = int(source.summary["recovery_overhead"]["failed_attempt_count"])
    system_failures = retrieval_failures + answer_failures
    failure_rate = system_failures / (36 + 42)
    citation_valid = all(
        set(record.answer_result.citations)
        <= {item.evidence_id for item in record.evidence_bundle.evidence_items}
        for record in completed
    )
    retrieval_records = [r for r in completed if r.key.condition_id != "E7"]
    stores_unchanged = all(
        isinstance(r.evidence_bundle, EvidenceBundle)
        and r.evidence_bundle.integrity.get("store_unchanged") is True
        and r.evidence_bundle.integrity.get("verified") is True
        for r in retrieval_records
    )
    served = {
        model
        for record in completed
        for model in (
            *record.answer_result.served_models,
            *((record.evidence_bundle.model["served_models"]) if isinstance(record.evidence_bundle, EvidenceBundle) else ()),
        )
    }
    rank_checks = {}
    controller_query_checks = {}
    for question_id in store.plan.question_ids:
        rank_checks[question_id] = {
            condition: _r2_first_rank_backend_invariant(
                source, condition, question_id
            )
            for condition in ("E2", "E4")
        }
        controller_query_checks[question_id] = (
            _first_search(source.run_root / "E2" / question_id)
            == _first_search(source.run_root / "E4" / question_id)
        )
    e7_checks = []
    for question_id in store.plan.question_ids:
        e2 = store.load_completed(RunKey("E2", question_id))
        e6 = store.load_completed(RunKey("E6", question_id))
        e7 = store.load_completed(RunKey("E7", question_id))
        assert e2 is not None and e6 is not None and e7 is not None
        fusion = e7.evidence_bundle
        if not isinstance(fusion, FusionEvidenceBundle):
            raise EvidenceValidationError("E7 record lacks FusionEvidenceBundle")
        expected_retrieval_tokens = int(e2.retrieval_metrics["total_tokens"]) + int(e6.retrieval_metrics["total_tokens"])
        e7_checks.append({
            "question_id": question_id,
            "source_bundle_ids_match": fusion.source_bundle_ids == (
                e2.evidence_bundle.bundle_id, e6.evidence_bundle.bundle_id
            ),
            "no_new_search": fusion.retrieval_metrics.get("search_calls") == 0
            and fusion.retrieval_metrics.get("reused_upstream_retrieval") is True,
            "retrieval_cost_reused_exactly_once": int(e7.retrieval_metrics["total_tokens"]) == expected_retrieval_tokens,
            "source_answer_cost_not_recounted": int(e7.deployment_metrics["total_tokens"])
            == expected_retrieval_tokens + int(e7.answer_metrics["total_tokens"]),
        })
    budget = source.summary["budget_decision"]
    overall = source.summary["overall"]
    max_tokens = max(
        row["total_tokens_max"] for row in source.summary["by_condition"].values()
    )
    gold = load_gold_records(
        Path(repo_root).resolve() / "experiments/locomo-conv50-v1/question-sets/dev-6-gold.jsonl",
        expected_sha256=DEV_GOLD_SHA256,
    )
    categories = sorted({item.category for item in gold})
    checks = {
        "records_42_complete": checkpoint["completed"] == 42 and checkpoint["pending"] == 0,
        "system_failure_rate_below_5_percent": failure_rate < SYSTEM_FAILURE_RATE_LIMIT,
        "all_citations_real": citation_valid,
        "all_store_hashes_unchanged": stores_unchanged,
        "served_model_consistent": len(served) == 1,
        "e2_e4_first_rank_backend_invariant": all(
            all(condition_checks.values())
            for condition_checks in rank_checks.values()
        ),
        "e7_no_hidden_retrieval": all(item["no_new_search"] for item in e7_checks),
        "e7_cost_excludes_source_answerers": all(
            item["retrieval_cost_reused_exactly_once"] and item["source_answer_cost_not_recounted"]
            for item in e7_checks
        ),
        "budget_skip_fraction_below_20_percent": budget["budget_skipped_episode_fraction"] < BUDGET_SKIP_FRACTION_LIMIT,
        "no_empty_retrieval_evidence": overall["empty_evidence_count"] == 0,
        "retrieval_tokens_below_safety_fuse": max_tokens < TOKEN_SAFETY_LIMIT,
        "dev6_categories_are_1_2_4_only": categories == [1, 2, 4],
    }
    body = {
        "schema_version": 1,
        "protocol_version": PILOT_PROTOCOL_VERSION,
        "run_id": run_id,
        "plan_id": store.plan.plan_id,
        "status": "passed" if all(checks.values()) else "failed",
        "checks": checks,
        "metrics": {
            "system_failure_attempts": system_failures,
            "system_failure_rate": failure_rate,
            "retrieval_failure_attempts": retrieval_failures,
            "answer_failure_attempts": answer_failures,
            "served_models": sorted(served),
            "capped_retrieval_episodes": overall["capped_episode_count"],
            "budget_skipped_episode_fraction": budget["budget_skipped_episode_fraction"],
            "retrieval_total_tokens_max": max_tokens,
        },
        "e2_e4_rank_checks": rank_checks,
        "e2_e4_controller_query_identity": controller_query_checks,
        "e7_checks": e7_checks,
        "category_design_limit": manifest["category_design_limit"],
        "observed_dev6_categories": categories,
    }
    return {"audit_id": "pilot-audit-" + sha256_bytes(canonical_json_bytes(body)), **body}


def finalize_pilot(*, repo_root: Path, output_root: Path, run_id: str) -> dict[str, Any]:
    store, checkpoint = verify_run_store(Path(output_root).resolve(), run_id)
    if checkpoint["completed"] != 42 or checkpoint["pending"] != 0:
        raise EvidenceValidationError("Pilot cannot be finalized before 42/42")
    evaluation_path = store.run_root / "evaluation.json"
    results = evaluate_run_store(
        run_root=Path(output_root).resolve(), run_id=run_id,
        gold_path=Path(repo_root).resolve() / "experiments/locomo-conv50-v1/question-sets/dev-6-gold.jsonl",
        expected_gold_sha256=DEV_GOLD_SHA256,
    )
    evaluation = {"summary": aggregate_evaluations(results), "results": [row.to_dict() for row in results]}
    if evaluation_path.exists():
        if _read_json(evaluation_path) != evaluation:
            raise EvidenceValidationError("Existing pilot evaluation differs")
    else:
        _write_exclusive(evaluation_path, evaluation, 0o600)
    audit = build_pilot_audit(repo_root=repo_root, output_root=output_root, run_id=run_id)
    audit_path = store.run_root / "audit.json"
    if audit_path.exists():
        if _read_json(audit_path) != audit:
            raise EvidenceValidationError("Existing pilot audit differs")
    else:
        _write_exclusive(audit_path, audit)
    _append_event(store.run_root / "events.jsonl", {"event": "pilot_finalized", "at": _now(), "audit_id": audit["audit_id"]})
    return {
        "status": audit["status"], "run_id": run_id, "records": 42,
        "evaluation_path": str(evaluation_path), "audit_path": str(audit_path),
        "audit_id": audit["audit_id"],
    }
