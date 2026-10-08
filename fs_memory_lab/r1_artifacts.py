"""Build, atomically publish, reload, and verify R1 evidence artifacts."""

from __future__ import annotations

import json
import os
import re
import secrets
import stat
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping, Sequence

from .agent import COMPACTION_SYSTEM_PROMPT
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
    VerifiedStoreManifest,
    canonical_json_bytes,
    compute_store_tree_sha256,
    sha256_bytes,
    validate_evidence_bundle,
    validate_retrieval_failure_artifact,
    validate_r1_evidence_bundle_profile,
)
from .paper_config import SEARCH
from .r1_agent import (
    R1_AGENT_PROTOCOL_VERSION,
    R1_AGENT_LIMITS,
    R1EpisodeOutcome,
    R1AgentError,
    r1_agent_limits_sha256,
)
from .r1_inputs import LoadedR1Store, r1_input_contract_sha256
from .r1_orchestration import r1_orchestration_schema_sha256
from .r1_prompts import FROZEN_R1_PROMPT_SHA256, R1_PROMPT_PROFILES
from .r1_tools import r1_filesystem_tool_schema_sha256


R1_ARTIFACT_PROTOCOL_VERSION = "r1-evidence-artifacts-v1"
_SAFE_SEGMENT = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}\Z")


def _plain(value: Any) -> Any:
    return json.loads(canonical_json_bytes(value))


def _condition(cell_id: str, store_id: str) -> dict[str, Any]:
    return {"condition_id": cell_id, "store_id": store_id, "retrieval_id": "r1"}


def r1_prompt_contract(cell_id: str) -> dict[str, Any]:
    try:
        profile = R1_PROMPT_PROFILES[cell_id]
    except KeyError as exc:
        raise EvidenceValidationError("Unknown R1 cell for prompt contract") from exc
    number = profile.paper_prompt_number
    return {
        "paper_prompt_id": f"filesystem-appendix-a3-prompt-{number}-normalized-v1",
        "paper_prompt_sha256": FROZEN_R1_PROMPT_SHA256[f"published_prompt_{number}"],
        "derived_prompt_sha256": FROZEN_R1_PROMPT_SHA256[f"derived_prompt_{number}"],
        "filesystem_tools_sha256": r1_filesystem_tool_schema_sha256(),
        "orchestration_actions_sha256": r1_orchestration_schema_sha256(),
    }


def r1_runtime_contract(
    *,
    cell_id: str,
    requested_model: str,
    budget_unit: str,
    budget_limit: int,
) -> dict[str, Any]:
    profile = R1_PROMPT_PROFILES[cell_id]
    body = {
        "protocol_version": R1_AGENT_PROTOCOL_VERSION,
        "input_contract_sha256": r1_input_contract_sha256(),
        "requested_model": requested_model,
        "paper_target_model": SEARCH.model,
        "reasoning_effort": SEARCH.reasoning_effort,
        "max_completion_tokens": SEARCH.max_completion_tokens,
        "round_limit": profile.hard_round_cap,
        "evidence_budget_unit": budget_unit,
        "evidence_budget_limit": budget_limit,
        "agent_limits_sha256": r1_agent_limits_sha256(),
        "agent_limits": _plain(R1_AGENT_LIMITS),
        "compaction_system_prompt_sha256": sha256_bytes(
            COMPACTION_SYSTEM_PROMPT.encode("utf-8")
        ),
        "compaction_qualification": "project-defined approximation; author prompt not published",
    }
    return {
        "runtime_sha256": sha256_bytes(canonical_json_bytes(body)),
        "round_limit": profile.hard_round_cap,
        "evidence_budget_unit": budget_unit,
        "evidence_budget_limit": budget_limit,
    }


def _usage_metrics(outcome: R1EpisodeOutcome) -> dict[str, Any]:
    token_rows = []
    available = True
    for row in outcome.usage:
        values = tuple(
            row.get(key)
            for key in ("prompt_tokens", "completion_tokens", "total_tokens")
        )
        if not all(
            isinstance(value, int) and not isinstance(value, bool) for value in values
        ):
            available = False
            break
        token_rows.append(values)
    if available:
        prompt_tokens = sum(row[0] for row in token_rows)
        completion_tokens = sum(row[1] for row in token_rows)
        total_tokens = sum(row[2] for row in token_rows)
        if total_tokens != prompt_tokens + completion_tokens:
            raise EvidenceValidationError("R1 usage totals are inconsistent")
    else:
        prompt_tokens = completion_tokens = total_tokens = None
    return {
        "provider_rounds": outcome.rounds.rounds_completed,
        "model_calls": outcome.model_calls,
        "provider_request_attempts": outcome.provider_request_attempts,
        "filesystem_tool_calls": outcome.filesystem_tool_calls,
        "orchestration_calls": outcome.orchestration_calls,
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "total_tokens": total_tokens,
        "token_usage_available": available,
    }


def _search_actions_from_trace(
    trace: Sequence[Mapping[str, Any]],
) -> tuple[Mapping[str, Any], ...]:
    actions: list[dict[str, Any]] = []
    for raw in trace:
        event = _plain(raw)
        kind = event.get("kind")
        if kind == "filesystem_observation":
            result = event["result"]
            actions.append(
                {
                    "kind": kind,
                    "observation_id": event["observation_id"],
                    "provider_round": event["provider_round"],
                    "action_ordinal": event["action_ordinal"],
                    "tool_name": result["tool_name"],
                    "canonical_args": result["canonical_args"],
                    "content_sha256": result["content_sha256"],
                    "coverage": result["coverage"],
                    "truncated": result["truncated"],
                    "result_count": result["result_count"],
                    "root_survey": result["root_survey"],
                    "whole_tree_grep": result["whole_tree_grep"],
                    "result_sha256": result["result_sha256"],
                    "observation_sha256": event["observation_sha256"],
                }
            )
        elif kind == "take_note_resolution":
            actions.append(
                {
                    "kind": kind,
                    "provider_round": event["provider_round"],
                    "action_ordinal": event["action_ordinal"],
                    "status": event["status"],
                    "selector": event["selector"],
                    "evidence_id": event["evidence_id"],
                    "replaced_evidence_ids": event["replaced_evidence_ids"],
                    "contributing_observation_ids": event[
                        "contributing_observation_ids"
                    ],
                    "resolution_sha256": event["resolution_sha256"],
                }
            )
        elif kind == "action_completed" and not event.get("ok"):
            actions.append(
                {
                    "kind": "rejected_action",
                    "provider_round": event["provider_round"],
                    "action_ordinal": event["action_ordinal"],
                    "tool_name": event["tool_name"],
                    "arguments": event["arguments"],
                    "arguments_wire_sha256": event["arguments_wire_sha256"],
                    "error_code": event["error_code"],
                }
            )
        elif kind in {
            "finish_search_rejected",
            "finish_search_accepted",
            "host_round_limit",
            "context_compaction",
        }:
            actions.append(event)
    return tuple(actions)


def _search_actions(outcome: R1EpisodeOutcome) -> tuple[Mapping[str, Any], ...]:
    return _search_actions_from_trace(outcome.trace)


def build_r1_evidence_bundle(
    outcome: R1EpisodeOutcome, *, loaded_store: LoadedR1Store
) -> EvidenceBundle:
    if outcome.store_snapshot != loaded_store.snapshot:
        raise EvidenceValidationError("R1 outcome and loaded store snapshots differ")
    validate_evidence_bundle_inputs(outcome=outcome, loaded_store=loaded_store)
    prompt_contract = r1_prompt_contract(outcome.cell_id)
    runtime_contract = r1_runtime_contract(
        cell_id=outcome.cell_id,
        requested_model=outcome.requested_model,
        budget_unit=outcome.notes.budget_unit,
        budget_limit=outcome.notes.budget_limit,
    )
    status = "capped" if outcome.stop.reason == "round_limit" else "completed"
    bundle = EvidenceBundle.create(
        status=status,
        question=outcome.question,
        condition=_condition(outcome.cell_id, outcome.store_id),
        store_snapshot=outcome.store_snapshot,
        prompt_contract=prompt_contract,
        runtime_contract=runtime_contract,
        search_actions=_search_actions(outcome),
        evidence_items=outcome.notes.evidence_items,
        stop=outcome.stop,
        budget=outcome.notes.to_budget_record(),
        metrics=_usage_metrics(outcome),
        model={
            "requested_model": outcome.requested_model,
            "served_models": list(outcome.served_models),
        },
        integrity={
            "store_unchanged": True,
            "pre_tree_sha256": outcome.store_snapshot.tree_sha256,
            "post_tree_sha256": outcome.store_snapshot.tree_sha256,
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
    validate_r1_evidence_bundle_profile(bundle)
    return bundle


def validate_evidence_bundle_inputs(
    *, outcome: R1EpisodeOutcome, loaded_store: LoadedR1Store
) -> None:
    if outcome.store_snapshot != loaded_store.snapshot:
        raise EvidenceValidationError("R1 outcome snapshot is not the formal store")
    loaded_store.verified_manifest.assert_mounted_root(loaded_store.root)


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
    if not isinstance(value, Mapping):
        raise EvidenceValidationError("Serialized R1 bundle must be an object")
    required = {
        "bundle_id",
        "schema_version",
        "protocol_version",
        "status",
        "question",
        "question_sha256",
        "condition",
        "store_snapshot",
        "prompt_contract",
        "runtime_contract",
        "search_actions",
        "evidence_items",
        "stop",
        "budget",
        "metrics",
        "model",
        "integrity",
        "errors",
    }
    if set(value) != required:
        raise EvidenceValidationError("Serialized R1 bundle fields are invalid")
    question = QuestionInput.from_mapping(value["question"])
    snapshot = StoreSnapshotRef(**dict(value["store_snapshot"]))
    stop_data = dict(value["stop"])
    stop_data.pop("global_fallback_done", None)
    proof_data = stop_data.pop("fallback_proof")
    stop = StopRecord(
        fallback_proof=(
            GlobalFallbackProof(**proof_data) if proof_data is not None else None
        ),
        **stop_data,
    )
    budget_data = dict(value["budget"])
    if budget_data.get("tokenizer") is not None:
        raise EvidenceValidationError("R1 serialized token budget is unsupported")
    budget_data["tokenizer"] = None
    recreated = EvidenceBundle.create(
        status=value["status"],
        question=question,
        condition=value["condition"],
        store_snapshot=snapshot,
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
        raise EvidenceValidationError("Serialized R1 bundle ID is invalid")
    return recreated


def _write_new_file(path: Path, payload: bytes, *, mode: int = 0o644) -> None:
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(path, flags, mode)
    try:
        written = 0
        while written < len(payload):
            count = os.write(descriptor, payload[written:])
            if count <= 0:
                raise OSError("short artifact write")
            written += count
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
        flags = os.O_WRONLY | os.O_APPEND
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        descriptor = os.open(self.path, flags)
        try:
            written = 0
            while written < len(payload):
                count = os.write(descriptor, payload[written:])
                if count <= 0:
                    raise OSError("short trace append")
                written += count
            os.fsync(descriptor)
        finally:
            os.close(descriptor)


@dataclass(frozen=True)
class R1EpisodeWorkspace:
    staging: Path
    final: Path
    trace_path: Path
    private_checkpoint_path: Path
    sink: DurableTraceSink

    @classmethod
    def create(
        cls, *, output_root: Path, run_id: str, cell_id: str, question_id: str
    ) -> "R1EpisodeWorkspace":
        for value, label in (
            (run_id, "run_id"),
            (cell_id, "cell_id"),
            (question_id, "question_id"),
        ):
            if not isinstance(value, str) or _SAFE_SEGMENT.fullmatch(value) is None:
                raise EvidenceValidationError(f"R1 artifact {label} is unsafe")
        root = Path(output_root)
        root.mkdir(parents=True, exist_ok=True)
        if root.is_symlink() or not root.is_dir():
            raise EvidenceValidationError("R1 artifact root is unsafe")
        run = root / run_id / cell_id
        run.mkdir(parents=True, exist_ok=True)
        final = run / question_id
        if final.exists() or final.is_symlink():
            raise EvidenceValidationError("R1 final episode artifact already exists")
        staging = run / f".{question_id}.in-progress-{secrets.token_hex(8)}"
        staging.mkdir(mode=0o700)
        sink = DurableTraceSink(staging / "trace.jsonl")
        return cls(
            staging=staging,
            final=final,
            trace_path=staging / "trace.jsonl",
            private_checkpoint_path=staging / "episode-secret.json",
            sink=sink,
        )

    def publish_success(
        self, *, bundle: EvidenceBundle, outcome: R1EpisodeOutcome
    ) -> Path:
        trace_payload = self.trace_path.read_bytes()
        bundle_payload = canonical_json_bytes(bundle.to_dict()) + b"\n"
        _write_new_file(self.staging / "bundle.json", bundle_payload)
        index = {
            "schema_version": 1,
            "protocol_version": R1_ARTIFACT_PROTOCOL_VERSION,
            "status": bundle.status,
            "episode_id": outcome.episode_id,
            "cell_id": outcome.cell_id,
            "question_id": outcome.question.question_id,
            "bundle_id": bundle.bundle_id,
            "bundle_sha256": sha256_bytes(bundle_payload),
            "trace_sha256": sha256_bytes(trace_payload),
            "private_checkpoint_key_id": outcome.observations.episode_key_id,
        }
        index_payload = canonical_json_bytes(index) + b"\n"
        _write_new_file(self.staging / "episode.json", index_payload)
        marker = {
            "schema_version": 1,
            "status": "published",
            "bundle_id": bundle.bundle_id,
            "bundle_sha256": sha256_bytes(bundle_payload),
            "trace_sha256": sha256_bytes(trace_payload),
            "episode_sha256": sha256_bytes(index_payload),
        }
        _write_new_file(
            self.staging / "COMPLETED",
            canonical_json_bytes(marker) + b"\n",
        )
        outcome.observations.verify_private_checkpoint(self.private_checkpoint_path)
        _fsync_directory(self.staging)
        os.replace(self.staging, self.final)
        _fsync_directory(self.final.parent)
        return self.final

    def publish_failure(self, *, artifact: RetrievalFailureArtifact) -> Path:
        trace_payload = self.trace_path.read_bytes()
        failure_payload = canonical_json_bytes(artifact.to_dict()) + b"\n"
        _write_new_file(self.staging / "failure.json", failure_payload)
        index = {
            "schema_version": 1,
            "protocol_version": R1_ARTIFACT_PROTOCOL_VERSION,
            "status": "failed",
            "question_id": artifact.question.question_id,
            "failure_id": artifact.failure_id,
            "failure_sha256": sha256_bytes(failure_payload),
            "trace_sha256": sha256_bytes(trace_payload),
        }
        index_payload = canonical_json_bytes(index) + b"\n"
        _write_new_file(self.staging / "episode.json", index_payload)
        marker = {
            "schema_version": 1,
            "status": "failed",
            "failure_id": artifact.failure_id,
            "failure_sha256": sha256_bytes(failure_payload),
            "trace_sha256": sha256_bytes(trace_payload),
            "episode_sha256": sha256_bytes(index_payload),
        }
        _write_new_file(self.staging / "FAILED", canonical_json_bytes(marker) + b"\n")
        if self.private_checkpoint_path.exists():
            if (
                self.private_checkpoint_path.is_symlink()
                or stat.S_IMODE(self.private_checkpoint_path.stat().st_mode) != 0o600
            ):
                raise EvidenceValidationError("R1 failure checkpoint is unsafe")
        _fsync_directory(self.staging)
        failed_final = self.final.with_name(
            f"{self.final.name}.failed-{artifact.failure_id.removeprefix('failure-')[:12]}"
        )
        if failed_final.exists() or failed_final.is_symlink():
            raise EvidenceValidationError("R1 failure artifact already exists")
        os.replace(self.staging, failed_final)
        _fsync_directory(failed_final.parent)
        return failed_final


def _failure_metrics(error: R1AgentError) -> tuple[dict[str, Any], tuple[str, ...]]:
    events = [_plain(item) for item in error.trace]
    usage_rows: list[Mapping[str, Any]] = []
    served: list[str] = []
    model_call_kinds = {
        "provider_response",
        "provider_response_rejected",
        "context_compaction",
        "context_compaction_rejected",
    }
    model_call_events = [
        event for event in events if event.get("kind") in model_call_kinds
    ]
    for event in model_call_events:
        usage = event.get("usage")
        model = event.get("served_model")
        if isinstance(usage, Mapping):
            usage_rows.append(usage)
        if isinstance(model, str) and model.strip():
            served.append(model)
    available = len(usage_rows) == len(model_call_events) and all(
        all(
            isinstance(row.get(key), int) and not isinstance(row.get(key), bool)
            for key in ("prompt_tokens", "completion_tokens", "total_tokens")
        )
        for row in usage_rows
    )
    if available:
        prompt_tokens = sum(row["prompt_tokens"] for row in usage_rows)
        completion_tokens = sum(row["completion_tokens"] for row in usage_rows)
        total_tokens = sum(row["total_tokens"] for row in usage_rows)
    else:
        prompt_tokens = completion_tokens = total_tokens = None
    metrics = {
        "provider_rounds": sum(
            event.get("kind") == "provider_round_closed" for event in events
        ),
        "model_calls": len(model_call_events),
        "provider_request_attempts": error.provider_request_attempts,
        "filesystem_tool_calls": error.filesystem_tool_calls,
        "orchestration_calls": error.orchestration_calls,
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "total_tokens": total_tokens,
        "token_usage_available": available,
    }
    return metrics, tuple(dict.fromkeys(served))


def build_r1_failure_artifact(
    error: R1AgentError,
    *,
    cell_id: str,
    question: QuestionInput,
    loaded_store: LoadedR1Store,
    requested_model: str,
    budget_unit: str,
    budget_limit: int,
) -> RetrievalFailureArtifact:
    metrics, served_models = _failure_metrics(error)
    post_tree_sha256, _, _ = compute_store_tree_sha256(loaded_store.root)
    store_unchanged = post_tree_sha256 == loaded_store.snapshot.tree_sha256
    # A failure artifact deliberately does not claim end-to-end verification,
    # even if the last readable store bytes still match the preflight snapshot.
    artifact = RetrievalFailureArtifact.create(
        question=question,
        condition=_condition(cell_id, loaded_store.snapshot.store_id),
        store_snapshot=loaded_store.snapshot,
        prompt_contract=r1_prompt_contract(cell_id),
        runtime_contract=r1_runtime_contract(
            cell_id=cell_id,
            requested_model=requested_model,
            budget_unit=budget_unit,
            budget_limit=budget_limit,
        ),
        search_actions=_search_actions_from_trace(error.trace),
        metrics=metrics,
        model={
            "requested_model": requested_model,
            "served_models": list(served_models),
        },
        integrity={
            "store_unchanged": store_unchanged,
            "pre_tree_sha256": loaded_store.snapshot.tree_sha256,
            "post_tree_sha256": post_tree_sha256,
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


def retrieval_failure_from_mapping(
    value: Mapping[str, Any],
) -> RetrievalFailureArtifact:
    if not isinstance(value, Mapping):
        raise EvidenceValidationError("Serialized R1 failure must be an object")
    required = {
        "failure_id",
        "schema_version",
        "protocol_version",
        "status",
        "question",
        "question_sha256",
        "condition",
        "store_snapshot",
        "prompt_contract",
        "runtime_contract",
        "search_actions",
        "metrics",
        "model",
        "integrity",
        "failure_kind",
        "errors",
    }
    if set(value) != required or value.get("status") != "failed":
        raise EvidenceValidationError("Serialized R1 failure fields are invalid")
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
        raise EvidenceValidationError("Serialized R1 failure ID is invalid")
    return recreated


def verify_r1_episode_artifact(
    path: Path, *, loaded_store: LoadedR1Store
) -> EvidenceBundle:
    root = Path(path)
    if root.is_symlink() or not root.is_dir():
        raise EvidenceValidationError("R1 episode artifact directory is invalid")
    required = {
        "trace.jsonl",
        "episode-secret.json",
        "bundle.json",
        "episode.json",
        "COMPLETED",
    }
    if {item.name for item in root.iterdir()} != required or any(
        item.is_symlink() or not item.is_file() for item in root.iterdir()
    ):
        raise EvidenceValidationError("R1 episode artifact files are incomplete")
    if stat.S_IMODE((root / "episode-secret.json").stat().st_mode) != 0o600:
        raise EvidenceValidationError("R1 private checkpoint mode is invalid")
    bundle_payload = (root / "bundle.json").read_bytes()
    trace_payload = (root / "trace.jsonl").read_bytes()
    index_payload = (root / "episode.json").read_bytes()
    marker = json.loads((root / "COMPLETED").read_text(encoding="utf-8"))
    index = json.loads(index_payload.decode("utf-8"))
    bundle = evidence_bundle_from_mapping(json.loads(bundle_payload.decode("utf-8")))
    if (
        index.get("bundle_id") != bundle.bundle_id
        or index.get("bundle_sha256") != sha256_bytes(bundle_payload)
        or index.get("trace_sha256") != sha256_bytes(trace_payload)
        or marker.get("bundle_id") != bundle.bundle_id
        or marker.get("bundle_sha256") != sha256_bytes(bundle_payload)
        or marker.get("trace_sha256") != sha256_bytes(trace_payload)
        or marker.get("episode_sha256") != sha256_bytes(index_payload)
    ):
        raise EvidenceValidationError("R1 episode artifact hash chain is invalid")
    for line_number, line in enumerate(trace_payload.splitlines(), 1):
        try:
            value = json.loads(line.decode("utf-8"))
        except (UnicodeError, json.JSONDecodeError) as exc:
            raise EvidenceValidationError(
                f"R1 trace line {line_number} is invalid"
            ) from exc
        if not isinstance(value, dict):
            raise EvidenceValidationError("R1 trace event must be an object")
    validate_evidence_bundle(
        bundle,
        root=loaded_store.root,
        catalog=loaded_store.catalog,
        verified_manifest=loaded_store.verified_manifest,
    )
    validate_r1_evidence_bundle_profile(bundle)
    return bundle


def verify_r1_failure_artifact(path: Path) -> RetrievalFailureArtifact:
    root = Path(path)
    if root.is_symlink() or not root.is_dir():
        raise EvidenceValidationError("R1 failure artifact directory is invalid")
    names = {item.name for item in root.iterdir()}
    required = {
        "trace.jsonl",
        "episode-secret.json",
        "failure.json",
        "episode.json",
        "FAILED",
    }
    if names != required or any(
        item.is_symlink() or not item.is_file() for item in root.iterdir()
    ):
        raise EvidenceValidationError("R1 failure artifact files are incomplete")
    if stat.S_IMODE((root / "episode-secret.json").stat().st_mode) != 0o600:
        raise EvidenceValidationError("R1 failure checkpoint mode is invalid")
    failure_payload = (root / "failure.json").read_bytes()
    trace_payload = (root / "trace.jsonl").read_bytes()
    index_payload = (root / "episode.json").read_bytes()
    marker = json.loads((root / "FAILED").read_text(encoding="utf-8"))
    index = json.loads(index_payload.decode("utf-8"))
    artifact = retrieval_failure_from_mapping(
        json.loads(failure_payload.decode("utf-8"))
    )
    if (
        index.get("status") != "failed"
        or index.get("failure_id") != artifact.failure_id
        or index.get("failure_sha256") != sha256_bytes(failure_payload)
        or index.get("trace_sha256") != sha256_bytes(trace_payload)
        or marker.get("status") != "failed"
        or marker.get("failure_id") != artifact.failure_id
        or marker.get("failure_sha256") != sha256_bytes(failure_payload)
        or marker.get("trace_sha256") != sha256_bytes(trace_payload)
        or marker.get("episode_sha256") != sha256_bytes(index_payload)
    ):
        raise EvidenceValidationError("R1 failure artifact hash chain is invalid")
    for line_number, line in enumerate(trace_payload.splitlines(), 1):
        try:
            event = json.loads(line.decode("utf-8"))
        except (UnicodeError, json.JSONDecodeError) as exc:
            raise EvidenceValidationError(
                f"R1 failure trace line {line_number} is invalid"
            ) from exc
        if not isinstance(event, dict):
            raise EvidenceValidationError("R1 failure trace event must be an object")
    validate_retrieval_failure_artifact(artifact)
    return artifact
