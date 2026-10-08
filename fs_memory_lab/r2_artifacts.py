"""Build, publish, reload, and verify R2-Raw evidence artifacts."""

from __future__ import annotations

import json
import os
import re
import secrets
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

from .evidence import (
    AttributionUnit,
    BudgetRecord,
    EvidenceBundle,
    EvidenceItem,
    EvidenceValidationError,
    GlobalFallbackProof,
    QuestionInput,
    RetrievalFailureArtifact,
    SourceRecordRef,
    StopRecord,
    StoreSnapshotRef,
    TokenizerRef,
    build_evidence_item,
    canonical_json_bytes,
    compute_store_tree_sha256,
    sha256_bytes,
    validate_evidence_bundle,
    validate_retrieval_failure_artifact,
)
from .r2_agent import R2_AGENT_PROTOCOL_VERSION, R2AgentError, R2EpisodeOutcome
from .r1_inputs import LoadedR1Store
from .r2_prompts import FROZEN_R2_PROMPT_SHA256
from .r2_protocol import (
    R2_PARAMETERS,
    R2_PROTOCOL_VERSION,
    R2_RUNTIME_LIMITS,
    r2_protocol_sha256,
)
from .r2_tokenizer import (
    R2_TOKENIZER_ID,
    R2_TOKENIZER_SOURCE_SHA256,
    R2_TOKENIZER_VERSION,
)
from .r2_tools import r2_action_contract_sha256


R2_ARTIFACT_PROTOCOL_VERSION = "r2-raw-artifacts-v1"
_SAFE_SEGMENT = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}\Z")


def _plain(value: Any) -> Any:
    return json.loads(canonical_json_bytes(value))


def _condition(cell_id: str, store_id: str) -> dict[str, Any]:
    return {"condition_id": cell_id, "store_id": store_id, "retrieval_id": "r2"}


def r2_backend_contract_sha256() -> str:
    body = {
        "protocol_sha256": r2_protocol_sha256(),
        "tokenizer_id": R2_TOKENIZER_ID,
        "tokenizer_version": R2_TOKENIZER_VERSION,
        "tokenizer_source_sha256": R2_TOKENIZER_SOURCE_SHA256,
        "backend": "exchange-bm25-session-rrf-seen-session-context-window",
    }
    return sha256_bytes(canonical_json_bytes(body))


def r2_prompt_contract() -> dict[str, Any]:
    return {
        "paper_prompt_id": "refind-appendix-a-stage1-plus-temporal-normalized-v1",
        "paper_prompt_sha256": FROZEN_R2_PROMPT_SHA256["published_system"],
        "derived_prompt_sha256": FROZEN_R2_PROMPT_SHA256["derived_system"],
        # The shared EvidenceBundle v1 retained these historical field names.
        # For R2 they bind the deterministic retrieval backend and textual action
        # contract; they do not claim that R2 exposes filesystem tools.
        "filesystem_tools_sha256": r2_backend_contract_sha256(),
        "orchestration_actions_sha256": r2_action_contract_sha256(),
    }


def r2_runtime_contract(
    *,
    outcome: R2EpisodeOutcome | None,
    api_style: str,
    corpus_sha256: str,
    requested_model: str,
    budget_unit: str,
    budget_limit: int,
) -> dict[str, Any]:
    if api_style not in {"paper", "portable"}:
        raise EvidenceValidationError("R2 runtime API style is invalid")
    if budget_unit not in {"bytes", "characters"}:
        raise EvidenceValidationError("R2 evidence budget must use bytes or characters")
    if isinstance(budget_limit, bool) or not isinstance(budget_limit, int) or budget_limit < 0:
        raise EvidenceValidationError("R2 evidence budget limit must be nonnegative")
    body = {
        "protocol_version": R2_PROTOCOL_VERSION,
        "agent_protocol_version": R2_AGENT_PROTOCOL_VERSION,
        "protocol_sha256": r2_protocol_sha256(),
        "corpus_sha256": corpus_sha256,
        "requested_model": requested_model,
        "paper_target": {
            "reasoning_effort": "high",
            "temperature": R2_PARAMETERS["temperature"],
            "max_completion_tokens": R2_PARAMETERS[
                "stage1_max_completion_tokens"
            ],
        },
        "actual_wire_profile": {
            "api_style": api_style,
            "reasoning_effort": "high" if api_style == "paper" else None,
            "temperature": R2_PARAMETERS["temperature"],
            "max_completion_tokens": (
                R2_PARAMETERS["stage1_max_completion_tokens"]
                if api_style == "paper"
                else None
            ),
        },
        "round_limit": R2_PARAMETERS["agent_action_cap"],
        "evidence_budget_unit": budget_unit,
        "evidence_budget_limit": budget_limit,
        "runtime_limits": _plain(R2_RUNTIME_LIMITS),
        "outcome_protocol_version": outcome.protocol_version if outcome else None,
    }
    return {
        "runtime_sha256": sha256_bytes(canonical_json_bytes(body)),
        "round_limit": int(R2_PARAMETERS["agent_action_cap"]),
        "evidence_budget_unit": budget_unit,
        "evidence_budget_limit": budget_limit,
    }


@dataclass
class _MergedSelection:
    path: str
    line_start: int
    line_end: int
    retrieval_round: int
    observation_ids: list[str]
    query_terms: list[str]
    rank: int
    score: float
    selection_ordinal: int


def _merge_note_ranges(outcome: R2EpisodeOutcome) -> tuple[_MergedSelection, ...]:
    raw = [
        _MergedSelection(
            path="/memories/" + note.hit.anchor.relative_path,
            line_start=note.hit.line_start,
            line_end=note.hit.line_end,
            retrieval_round=note.retrieval_round,
            observation_ids=[note.observation_id],
            query_terms=list(note.query_terms),
            rank=note.hit.result_index,
            score=note.hit.rrf_score,
            selection_ordinal=note.selection_ordinal,
        )
        for note in outcome.notes
    ]
    raw.sort(key=lambda item: (item.path, item.line_start, item.line_end, item.selection_ordinal))
    merged: list[_MergedSelection] = []
    for item in raw:
        if (
            merged
            and merged[-1].path == item.path
            and item.line_start <= merged[-1].line_end + 1
        ):
            current = merged[-1]
            current.line_end = max(current.line_end, item.line_end)
            current.retrieval_round = min(current.retrieval_round, item.retrieval_round)
            current.observation_ids = list(
                dict.fromkeys((*current.observation_ids, *item.observation_ids))
            )
            current.query_terms = list(
                dict.fromkeys((*current.query_terms, *item.query_terms))
            )
            current.rank = min(current.rank, item.rank)
            current.score = max(current.score, item.score)
            current.selection_ordinal = min(
                current.selection_ordinal, item.selection_ordinal
            )
        else:
            merged.append(item)
    return tuple(sorted(merged, key=lambda item: item.selection_ordinal))


def _build_budgeted_items(
    outcome: R2EpisodeOutcome,
    *,
    loaded_store: LoadedR1Store,
    budget_unit: str,
    budget_limit: int,
) -> tuple[tuple[EvidenceItem, ...], BudgetRecord, StopRecord]:
    if budget_unit not in {"bytes", "characters"}:
        raise EvidenceValidationError("R2 evidence budget must use bytes or characters")
    if isinstance(budget_limit, bool) or not isinstance(budget_limit, int) or budget_limit < 0:
        raise EvidenceValidationError("R2 evidence budget limit must be nonnegative")
    selections = _merge_note_ranges(outcome)
    built = [
        build_evidence_item(
            root=loaded_store.root,
            catalog=loaded_store.catalog,
            verified_manifest=loaded_store.verified_manifest,
            snapshot=loaded_store.snapshot,
            path=item.path,
            line_start=item.line_start,
            line_end=item.line_end,
            retrieval_round=item.retrieval_round,
            observation_ids=item.observation_ids,
            selection_ordinal=item.selection_ordinal,
            query_terms=item.query_terms,
            rank=item.rank,
            score=item.score,
        )
        for item in selections
    ]
    accepted: list[EvidenceItem] = []
    used = 0
    skipped = 0
    for item in built:
        size = len(item.text.encode("utf-8")) if budget_unit == "bytes" else len(item.text)
        if used + size > budget_limit:
            skipped += 1
            continue
        accepted.append(item)
        used += size
    stop = outcome.stop
    if skipped and stop.reason != "round_limit":
        stop = StopRecord(
            reason="evidence_budget_reached",
            hit_cap=False,
            missing_aspects=(),
            rounds_without_new_evidence=0,
            fallback_proof=None,
        )
    budget = BudgetRecord(
        unit=budget_unit,
        tokenizer=None,
        limit=budget_limit,
        used=used,
        skipped_items=skipped,
        truncated=False,
    )
    return tuple(accepted), budget, stop


def _usage_metrics(outcome: R2EpisodeOutcome) -> dict[str, Any]:
    prompt_tokens = sum(int(row["prompt_tokens"]) for row in outcome.usage)
    completion_tokens = sum(int(row["completion_tokens"]) for row in outcome.usage)
    total_tokens = sum(int(row["total_tokens"]) for row in outcome.usage)
    if total_tokens != prompt_tokens + completion_tokens:
        raise EvidenceValidationError("R2 usage totals are inconsistent")
    return {
        "provider_rounds": outcome.provider_rounds,
        "model_calls": outcome.provider_rounds,
        "provider_request_attempts": outcome.provider_request_attempts,
        "filesystem_tool_calls": 0,
        "orchestration_calls": (
            outcome.searches
            + outcome.note_actions
            + outcome.finish_actions
            + outcome.invalid_actions
        ),
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "total_tokens": total_tokens,
        "token_usage_available": True,
    }


def _search_actions(trace: Sequence[Mapping[str, Any]]) -> tuple[Mapping[str, Any], ...]:
    output: list[Mapping[str, Any]] = []
    for event in trace:
        plain = _plain(event)
        if plain.get("event") in {"action", "invalid_action", "provider_retry"}:
            output.append(plain)
    return tuple(output)


def validate_r2_evidence_bundle_profile(bundle: EvidenceBundle) -> None:
    if bundle.condition.get("retrieval_id") != "r2":
        raise EvidenceValidationError("R2 bundle retrieval_id must be r2")
    mapping = {"E2": "s1", "E4": "s2"}
    cell_id = bundle.condition.get("condition_id")
    if cell_id not in mapping or bundle.condition.get("store_id") != mapping[cell_id]:
        raise EvidenceValidationError("R2 bundle cell/store mapping is invalid")
    if bundle.store_snapshot.source_kind != "raw":
        raise EvidenceValidationError("R2-Raw bundle requires a raw store")
    if any(item.rank is None or item.score is None for item in bundle.evidence_items):
        raise EvidenceValidationError("R2 evidence must preserve rank and score")


def build_r2_evidence_bundle(
    outcome: R2EpisodeOutcome,
    *,
    loaded_store: LoadedR1Store,
    corpus_sha256: str,
    budget_unit: str,
    budget_limit: int,
) -> EvidenceBundle:
    if outcome.store_id != loaded_store.snapshot.store_id:
        raise EvidenceValidationError("R2 outcome and loaded store differ")
    if outcome.question.conversation_id != loaded_store.snapshot.conversation_id:
        raise EvidenceValidationError("R2 question and store differ")
    items, budget, stop = _build_budgeted_items(
        outcome,
        loaded_store=loaded_store,
        budget_unit=budget_unit,
        budget_limit=budget_limit,
    )
    status = "capped" if stop.reason == "round_limit" else "completed"
    bundle = EvidenceBundle.create(
        status=status,
        question=outcome.question,
        condition=_condition(outcome.cell_id, outcome.store_id),
        store_snapshot=loaded_store.snapshot,
        prompt_contract=r2_prompt_contract(),
        runtime_contract=r2_runtime_contract(
            outcome=outcome,
            api_style=outcome.api_style,
            corpus_sha256=corpus_sha256,
            requested_model=outcome.requested_model,
            budget_unit=budget_unit,
            budget_limit=budget_limit,
        ),
        search_actions=_search_actions(outcome.trace),
        evidence_items=items,
        stop=stop,
        budget=budget,
        metrics=_usage_metrics(outcome),
        model={
            "requested_model": outcome.requested_model,
            "served_models": list(outcome.served_models),
        },
        integrity={
            "store_unchanged": True,
            "pre_tree_sha256": loaded_store.snapshot.tree_sha256,
            "post_tree_sha256": loaded_store.snapshot.tree_sha256,
            "verified": True,
        },
        errors=(),
    )
    validate_evidence_bundle(
        bundle,
        root=loaded_store.root,
        catalog=loaded_store.catalog,
        verified_manifest=loaded_store.verified_manifest,
    )
    validate_r2_evidence_bundle_profile(bundle)
    return bundle


def _failure_metrics(error: R2AgentError) -> tuple[dict[str, Any], tuple[str, ...]]:
    responses = [
        _plain(item) for item in error.trace if item.get("event") == "provider_response"
    ]
    prompt_tokens = sum(item["usage"]["prompt_tokens"] for item in responses)
    completion_tokens = sum(item["usage"]["completion_tokens"] for item in responses)
    total_tokens = sum(item["usage"]["total_tokens"] for item in responses)
    served = tuple(
        dict.fromkeys(
            item["served_model"]
            for item in responses
            if isinstance(item.get("served_model"), str) and item["served_model"]
        )
    )
    actions = sum(
        item.get("event") in {"action", "invalid_action"} for item in error.trace
    )
    return (
        {
            "provider_rounds": len(responses),
            "model_calls": len(responses),
            "provider_request_attempts": error.provider_request_attempts,
            "filesystem_tool_calls": 0,
            "orchestration_calls": actions,
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": total_tokens,
            "token_usage_available": True,
        },
        served,
    )


def build_r2_failure_artifact(
    error: R2AgentError,
    *,
    cell_id: str,
    question: QuestionInput,
    loaded_store: LoadedR1Store,
    corpus_sha256: str,
    requested_model: str,
    api_style: str,
    budget_unit: str,
    budget_limit: int,
) -> RetrievalFailureArtifact:
    metrics, served = _failure_metrics(error)
    post_hash, _, _ = compute_store_tree_sha256(loaded_store.root)
    artifact = RetrievalFailureArtifact.create(
        question=question,
        condition=_condition(cell_id, loaded_store.snapshot.store_id),
        store_snapshot=loaded_store.snapshot,
        prompt_contract=r2_prompt_contract(),
        runtime_contract=r2_runtime_contract(
            outcome=None,
            api_style=api_style,
            corpus_sha256=corpus_sha256,
            requested_model=requested_model,
            budget_unit=budget_unit,
            budget_limit=budget_limit,
        ),
        search_actions=_search_actions(error.trace),
        metrics=metrics,
        model={
            "requested_model": requested_model,
            "served_models": list(served),
        },
        integrity={
            "store_unchanged": post_hash == loaded_store.snapshot.tree_sha256,
            "pre_tree_sha256": loaded_store.snapshot.tree_sha256,
            "post_tree_sha256": post_hash,
            "verified": False,
        },
        failure_kind=error.stage,
        errors=(
            {
                "type": type(error).__name__,
                "stage": error.stage,
                "provider_round": error.provider_round,
                "message": str(error),
            },
        ),
    )
    validate_retrieval_failure_artifact(artifact)
    return artifact


def _source_record(value: Mapping[str, Any]) -> SourceRecordRef:
    return SourceRecordRef(**dict(value))


def _attribution_unit(value: Mapping[str, Any]) -> AttributionUnit:
    data = dict(value)
    data["source_locators"] = tuple(data["source_locators"])
    data["dia_ids"] = tuple(data["dia_ids"])
    return AttributionUnit(**data)


def _evidence_item(value: Mapping[str, Any]) -> EvidenceItem:
    data = dict(value)
    for key in ("source_locators", "dia_ids", "query_terms", "observation_ids"):
        data[key] = tuple(data[key])
    data["source_records"] = tuple(_source_record(x) for x in data["source_records"])
    data["attribution_units"] = tuple(
        _attribution_unit(x) for x in data["attribution_units"]
    )
    return EvidenceItem(**data)


def evidence_bundle_from_mapping(value: Mapping[str, Any]) -> EvidenceBundle:
    required = {
        "bundle_id", "schema_version", "protocol_version", "status", "question",
        "question_sha256", "condition", "store_snapshot", "prompt_contract",
        "runtime_contract", "search_actions", "evidence_items", "stop", "budget",
        "metrics", "model", "integrity", "errors",
    }
    if not isinstance(value, Mapping) or set(value) != required:
        raise EvidenceValidationError("Serialized R2 bundle fields are invalid")
    stop_data = dict(value["stop"])
    stop_data.pop("global_fallback_done", None)
    proof = stop_data.pop("fallback_proof")
    stop = StopRecord(
        fallback_proof=GlobalFallbackProof(**proof) if proof is not None else None,
        **stop_data,
    )
    budget_data = dict(value["budget"])
    tokenizer = budget_data.get("tokenizer")
    budget_data["tokenizer"] = TokenizerRef(**tokenizer) if tokenizer else None
    recreated = EvidenceBundle.create(
        status=value["status"],
        question=QuestionInput.from_mapping(value["question"]),
        condition=value["condition"],
        store_snapshot=StoreSnapshotRef(**dict(value["store_snapshot"])),
        prompt_contract=value["prompt_contract"],
        runtime_contract=value["runtime_contract"],
        search_actions=value["search_actions"],
        evidence_items=tuple(_evidence_item(item) for item in value["evidence_items"]),
        stop=stop,
        budget=BudgetRecord(**budget_data),
        metrics=value["metrics"],
        model=value["model"],
        integrity=value["integrity"],
        errors=value["errors"],
    )
    if recreated.bundle_id != value["bundle_id"]:
        raise EvidenceValidationError("Serialized R2 bundle ID is invalid")
    return recreated


def retrieval_failure_from_mapping(value: Mapping[str, Any]) -> RetrievalFailureArtifact:
    required = {
        "failure_id", "schema_version", "protocol_version", "status", "question",
        "question_sha256", "condition", "store_snapshot", "prompt_contract",
        "runtime_contract", "search_actions", "metrics", "model", "integrity",
        "failure_kind", "errors",
    }
    if not isinstance(value, Mapping) or set(value) != required or value.get("status") != "failed":
        raise EvidenceValidationError("Serialized R2 failure fields are invalid")
    recreated = RetrievalFailureArtifact.create(
        question=QuestionInput.from_mapping(value["question"]),
        condition=value["condition"],
        store_snapshot=StoreSnapshotRef(**dict(value["store_snapshot"])),
        prompt_contract=value["prompt_contract"],
        runtime_contract=value["runtime_contract"],
        search_actions=value["search_actions"],
        metrics=value["metrics"],
        model=value["model"],
        integrity=value["integrity"],
        failure_kind=value["failure_kind"],
        errors=value["errors"],
    )
    if recreated.failure_id != value["failure_id"]:
        raise EvidenceValidationError("Serialized R2 failure ID is invalid")
    return recreated


def _write_new_file(path: Path, payload: bytes) -> None:
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(path, flags, 0o644)
    try:
        offset = 0
        while offset < len(payload):
            count = os.write(descriptor, payload[offset:])
            if count <= 0:
                raise OSError("short R2 artifact write")
            offset += count
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


@dataclass
class DurableTraceSink:
    path: Path

    def __post_init__(self) -> None:
        _write_new_file(self.path, b"")

    def __call__(self, event: Mapping[str, Any]) -> None:
        payload = canonical_json_bytes(event) + b"\n"
        descriptor = os.open(self.path, os.O_WRONLY | os.O_APPEND | os.O_NOFOLLOW)
        try:
            offset = 0
            while offset < len(payload):
                count = os.write(descriptor, payload[offset:])
                if count <= 0:
                    raise OSError("short R2 trace append")
                offset += count
            os.fsync(descriptor)
        finally:
            os.close(descriptor)


@dataclass(frozen=True)
class R2EpisodeWorkspace:
    staging: Path
    final: Path
    trace_path: Path
    sink: DurableTraceSink

    @classmethod
    def create(
        cls, *, output_root: Path, run_id: str, cell_id: str, question_id: str
    ) -> "R2EpisodeWorkspace":
        for value, label in ((run_id, "run_id"), (cell_id, "cell_id"), (question_id, "question_id")):
            if not isinstance(value, str) or _SAFE_SEGMENT.fullmatch(value) is None:
                raise EvidenceValidationError(f"R2 artifact {label} is unsafe")
        root = Path(output_root).resolve()
        root.mkdir(parents=True, exist_ok=True)
        if root.is_symlink() or not root.is_dir():
            raise EvidenceValidationError("R2 artifact root is unsafe")
        parent = root / run_id / cell_id
        parent.mkdir(parents=True, exist_ok=True)
        final = parent / question_id
        if final.exists() or final.is_symlink():
            raise EvidenceValidationError("R2 final episode artifact already exists")
        staging = parent / f".{question_id}.in-progress-{secrets.token_hex(8)}"
        staging.mkdir(mode=0o700)
        sink = DurableTraceSink(staging / "trace.jsonl")
        return cls(staging=staging, final=final, trace_path=staging / "trace.jsonl", sink=sink)

    def _publish(self, *, status: str, artifact_id: str, filename: str, payload: bytes) -> Path:
        trace_payload = self.trace_path.read_bytes()
        _write_new_file(self.staging / filename, payload)
        index = {
            "schema_version": 1,
            "protocol_version": R2_ARTIFACT_PROTOCOL_VERSION,
            "status": status,
            "artifact_id": artifact_id,
            "artifact_filename": filename,
            "artifact_sha256": sha256_bytes(payload),
            "trace_sha256": sha256_bytes(trace_payload),
        }
        index_payload = canonical_json_bytes(index) + b"\n"
        _write_new_file(self.staging / "episode.json", index_payload)
        marker_name = "COMPLETED" if status in {"completed", "capped"} else "FAILED"
        marker = {
            "schema_version": 1,
            "status": status,
            "artifact_id": artifact_id,
            "artifact_sha256": sha256_bytes(payload),
            "trace_sha256": sha256_bytes(trace_payload),
            "episode_sha256": sha256_bytes(index_payload),
        }
        _write_new_file(self.staging / marker_name, canonical_json_bytes(marker) + b"\n")
        _fsync_directory(self.staging)
        final = self.final
        if status == "failed":
            final = final.with_name(
                f"{final.name}.failed-{artifact_id.removeprefix('failure-')[:12]}"
            )
        os.replace(self.staging, final)
        _fsync_directory(final.parent)
        return final

    def publish_success(self, bundle: EvidenceBundle) -> Path:
        return self._publish(
            status=bundle.status,
            artifact_id=bundle.bundle_id,
            filename="bundle.json",
            payload=canonical_json_bytes(bundle.to_dict()) + b"\n",
        )

    def publish_failure(self, artifact: RetrievalFailureArtifact) -> Path:
        return self._publish(
            status="failed",
            artifact_id=artifact.failure_id,
            filename="failure.json",
            payload=canonical_json_bytes(artifact.to_dict()) + b"\n",
        )


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise EvidenceValidationError("R2 artifact JSON is unreadable") from exc
    if not isinstance(value, dict):
        raise EvidenceValidationError("R2 artifact JSON must be an object")
    return value


def verify_r2_episode_artifact(path: Path, *, loaded_store: LoadedR1Store) -> EvidenceBundle:
    root = Path(path)
    required = {"trace.jsonl", "bundle.json", "episode.json", "COMPLETED"}
    if root.is_symlink() or not root.is_dir() or {p.name for p in root.iterdir()} != required:
        raise EvidenceValidationError("R2 success artifact files are incomplete")
    if any(item.is_symlink() or not item.is_file() for item in root.iterdir()):
        raise EvidenceValidationError("R2 success artifact contains an unsafe entry")
    trace_payload = (root / "trace.jsonl").read_bytes()
    bundle_payload = (root / "bundle.json").read_bytes()
    index_payload = (root / "episode.json").read_bytes()
    index = _read_json(root / "episode.json")
    marker = _read_json(root / "COMPLETED")
    bundle = evidence_bundle_from_mapping(json.loads(bundle_payload.decode("utf-8")))
    if (
        index.get("artifact_id") != bundle.bundle_id
        or index.get("artifact_sha256") != sha256_bytes(bundle_payload)
        or index.get("trace_sha256") != sha256_bytes(trace_payload)
        or marker.get("artifact_id") != bundle.bundle_id
        or marker.get("artifact_sha256") != sha256_bytes(bundle_payload)
        or marker.get("trace_sha256") != sha256_bytes(trace_payload)
        or marker.get("episode_sha256") != sha256_bytes(index_payload)
    ):
        raise EvidenceValidationError("R2 success artifact hash chain is invalid")
    for line in trace_payload.splitlines():
        if not isinstance(json.loads(line.decode("utf-8")), dict):
            raise EvidenceValidationError("R2 trace event is invalid")
    validate_evidence_bundle(
        bundle,
        root=loaded_store.root,
        catalog=loaded_store.catalog,
        verified_manifest=loaded_store.verified_manifest,
    )
    validate_r2_evidence_bundle_profile(bundle)
    return bundle


def verify_r2_failure_artifact(path: Path) -> RetrievalFailureArtifact:
    root = Path(path)
    required = {"trace.jsonl", "failure.json", "episode.json", "FAILED"}
    if root.is_symlink() or not root.is_dir() or {p.name for p in root.iterdir()} != required:
        raise EvidenceValidationError("R2 failure artifact files are incomplete")
    if any(item.is_symlink() or not item.is_file() for item in root.iterdir()):
        raise EvidenceValidationError("R2 failure artifact contains an unsafe entry")
    trace_payload = (root / "trace.jsonl").read_bytes()
    failure_payload = (root / "failure.json").read_bytes()
    index_payload = (root / "episode.json").read_bytes()
    index = _read_json(root / "episode.json")
    marker = _read_json(root / "FAILED")
    artifact = retrieval_failure_from_mapping(json.loads(failure_payload.decode("utf-8")))
    if (
        index.get("artifact_id") != artifact.failure_id
        or index.get("artifact_sha256") != sha256_bytes(failure_payload)
        or index.get("trace_sha256") != sha256_bytes(trace_payload)
        or marker.get("artifact_id") != artifact.failure_id
        or marker.get("artifact_sha256") != sha256_bytes(failure_payload)
        or marker.get("trace_sha256") != sha256_bytes(trace_payload)
        or marker.get("episode_sha256") != sha256_bytes(index_payload)
    ):
        raise EvidenceValidationError("R2 failure artifact hash chain is invalid")
    validate_retrieval_failure_artifact(artifact)
    return artifact
