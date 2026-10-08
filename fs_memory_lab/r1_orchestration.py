"""Project-defined orchestration actions for R1 evidence-only retrieval.

These two actions are a controlled experimental adaptation.  They are not part
of the four filesystem tools published in Filesystem-Based Memory for LLM
Agents.  Schemas remain separate so the report and metrics cannot conflate the
paper's retrieval surface with local evidence bookkeeping.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import secrets
import stat
from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping, Sequence

from .evidence import (
    BudgetRecord,
    EvidenceItem,
    EvidenceValidationError,
    GlobalFallbackProof,
    SourceCatalog,
    StopRecord,
    StoreSnapshotRef,
    VerifiedStoreManifest,
    build_evidence_item,
    canonical_json_bytes,
    sha256_bytes,
    validate_evidence_item,
    validate_store_snapshot,
)
from .r1_tools import LineCoverage, R1ReadOnlyFilesystem, ReadToolResult


R1_ORCHESTRATION_PROTOCOL_VERSION = "r1-evidence-orchestration-v2"
R1_OBSERVATION_SCHEMA_VERSION = 2
R1_ORCHESTRATION_ACTION_NAMES = ("take_note", "finish_search")
MODEL_FINISH_REASONS = (
    "evidence_sufficient",
    "not_found_after_global_fallback",
    "no_progress_after_global_fallback",
    "evidence_budget_reached",
)
MISSING_ASPECT_LABELS = (
    "subject_identity",
    "event_or_fact",
    "time",
    "location",
    "cause_or_reason",
    "sequence_or_relation",
    "comparison_or_choice",
    "corroborating_evidence",
)
R1_ROUND_LIMIT_BY_STORE = MappingProxyType({"s1": 20, "s2": 20, "s3": 40})

R1_ORCHESTRATION_LIMITS = MappingProxyType(
    {
        "max_observation_ids_per_note": 32,
        "max_missing_aspects": 16,
        "missing_aspect_taxonomy_size": len(MISSING_ASPECT_LABELS),
        "round_limit_by_store": R1_ROUND_LIMIT_BY_STORE,
    }
)


def _tool(
    name: str,
    description: str,
    properties: Mapping[str, Any],
    required: list[str],
) -> dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": {
                "type": "object",
                "properties": dict(properties),
                "required": required,
                "additionalProperties": False,
            },
        },
    }


_ACTION_DEFINITIONS = {
    "take_note": _tool(
        "take_note",
        "Select an exact line range from prior successful filesystem observations as candidate evidence. Supply selectors only: never quote, paraphrase, answer, or provide source IDs. The host verifies complete observation coverage and re-reads the frozen store before accepting evidence.",
        {
            "observation_ids": {
                "type": "array",
                "description": "One or more prior observation IDs whose returned line coverage jointly and continuously covers the selected range.",
                "items": {"type": "string", "pattern": "^obs-[0-9]{4,}$"},
                "minItems": 1,
                "maxItems": R1_ORCHESTRATION_LIMITS["max_observation_ids_per_note"],
                "uniqueItems": True,
            },
            "path": {
                "type": "string",
                "description": "Observed Markdown file path under /memories.",
            },
            "line_start": {
                "type": "integer",
                "description": "First selected line, 1-indexed and inclusive.",
                "minimum": 1,
            },
            "line_end": {
                "type": "integer",
                "description": "Last selected line, 1-indexed and inclusive.",
                "minimum": 1,
            },
        },
        ["observation_ids", "path", "line_start", "line_end"],
    ),
    "finish_search": _tool(
        "finish_search",
        "Finish evidence retrieval without answering the benchmark question. Report only a structured stop reason and short labels for any missing evidence aspects. This action must be the only action in its assistant response.",
        {
            "reason": {
                "type": "string",
                "description": "Why evidence retrieval is stopping.",
                "enum": list(MODEL_FINISH_REASONS),
            },
            "missing_aspects": {
                "type": "array",
                "description": "Short labels for evidence still missing; use an empty array when nothing is missing.",
                "items": {
                    "type": "string",
                    "enum": list(MISSING_ASPECT_LABELS),
                },
                "maxItems": R1_ORCHESTRATION_LIMITS["max_missing_aspects"],
                "uniqueItems": True,
            },
        },
        ["reason", "missing_aspects"],
    ),
}


# Filled only after reviewing the exact schema bytes below.  Any subsequent
# change must update tests, documentation and these hashes deliberately.
FROZEN_R1_ORCHESTRATION_PROFILE_SHA256 = (
    "a9c58a8d9c366618e2dd185b9f22299897d10148818b8edef2b2d9425517e9e1"
)
FROZEN_R1_ORCHESTRATION_SCHEMA_SHA256 = (
    "3506af86ae75acd7ce07f88bae7a25e1bfec56a5b1c9f44abd3d71a2e6f4eb2d"
)
FROZEN_R1_ORCHESTRATION_WIRE_SHA256 = (
    "677fdd4d675152fc64635392db2bc4085f051d38c5cd1457f7cb96ace26e9f16"
)
FROZEN_R1_ORCHESTRATION_LIMITS_SHA256 = (
    "0d9d7220960a1769cf8346e5a45e08289636f5ab63525d2e49da30a1e339ca60"
)


def _current_schema_payload() -> list[dict[str, Any]]:
    selected = [_ACTION_DEFINITIONS[name] for name in R1_ORCHESTRATION_ACTION_NAMES]
    canonical_json_bytes(selected)
    return json.loads(
        json.dumps(selected, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
    )


def r1_orchestration_profile_sha256() -> str:
    return sha256_bytes(canonical_json_bytes(list(R1_ORCHESTRATION_ACTION_NAMES)))


def r1_orchestration_schema_sha256() -> str:
    return sha256_bytes(canonical_json_bytes(_current_schema_payload()))


def r1_orchestration_wire_sha256() -> str:
    payload = json.dumps(
        _current_schema_payload(),
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
    ).encode("utf-8")
    return sha256_bytes(payload)


def r1_orchestration_limits_sha256() -> str:
    return sha256_bytes(canonical_json_bytes(R1_ORCHESTRATION_LIMITS))


def verify_r1_orchestration_freeze() -> None:
    checks = {
        "profile": (
            r1_orchestration_profile_sha256(),
            FROZEN_R1_ORCHESTRATION_PROFILE_SHA256,
        ),
        "canonical schema": (
            r1_orchestration_schema_sha256(),
            FROZEN_R1_ORCHESTRATION_SCHEMA_SHA256,
        ),
        "wire schema": (
            r1_orchestration_wire_sha256(),
            FROZEN_R1_ORCHESTRATION_WIRE_SHA256,
        ),
        "limits": (
            r1_orchestration_limits_sha256(),
            FROZEN_R1_ORCHESTRATION_LIMITS_SHA256,
        ),
    }
    for label, (actual, expected) in checks.items():
        if actual != expected:
            raise EvidenceValidationError(
                f"Reviewed R1 orchestration {label} changed without a hash update"
            )


def r1_orchestration_action_schemas() -> list[dict[str, Any]]:
    """Return detached action schemas after verifying their reviewed identity."""
    verify_r1_orchestration_freeze()
    return _current_schema_payload()


_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_OBSERVATION_ID = re.compile(r"obs-[0-9]{4,}\Z")


class R1OrchestrationError(ValueError):
    """Safe, model-visible failure from a project-defined orchestration action."""

    def __init__(self, code: str, message: str):
        if not isinstance(code, str) or re.fullmatch(r"[a-z][a-z0-9_]*", code) is None:
            raise ValueError("R1 orchestration error code is invalid")
        if not isinstance(message, str) or not message:
            raise ValueError("R1 orchestration error message is invalid")
        super().__init__(message)
        self.code = code


def _positive_integer(value: Any, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise EvidenceValidationError(f"{label} must be a positive integer")
    return value


def _ordered_tuple(value: Any, label: str) -> tuple[Any, ...]:
    """Reject unordered containers instead of silently canonicalizing them."""
    if not isinstance(value, (list, tuple)):
        raise EvidenceValidationError(f"{label} must be an ordered array")
    return tuple(value)


_EPISODE_ISSUER = object()
_EXECUTION_ISSUER = object()


class _EpisodeReceipt:
    """Opaque HMAC capability issued only by ``ObservationLedger.start``."""

    __slots__ = (
        "episode_id",
        "question_sha256",
        "store_snapshot",
        "snapshot_ref_sha256",
        "key_id",
        "_secret",
    )

    def __init__(
        self,
        *,
        episode_id: str,
        question_sha256: str,
        store_snapshot: StoreSnapshotRef,
        secret: bytes,
        _issuer: object,
    ) -> None:
        if _issuer is not _EPISODE_ISSUER:
            raise EvidenceValidationError("Episode receipt was not host-issued")
        self.episode_id = episode_id
        self.question_sha256 = question_sha256
        self.store_snapshot = store_snapshot
        if not isinstance(secret, bytes) or len(secret) != 32:
            raise EvidenceValidationError("Episode HMAC secret is invalid")
        self.snapshot_ref_sha256 = sha256_bytes(
            canonical_json_bytes(store_snapshot.to_dict())
        )
        self.key_id = sha256_bytes(secret)
        self._secret = secret


class _ExecutionReceipt:
    """Serializable binding between one episode and one executed read result."""

    __slots__ = (
        "episode_receipt",
        "schema_version",
        "episode_id",
        "key_id",
        "question_sha256",
        "snapshot_ref_sha256",
        "ordinal",
        "provider_round",
        "action_ordinal",
        "result_sha256",
        "receipt_mac",
    )

    def __init__(
        self,
        *,
        episode_receipt: _EpisodeReceipt,
        ordinal: int,
        provider_round: int,
        action_ordinal: int,
        result_sha256: str,
        receipt_mac: str,
        _issuer: object,
    ) -> None:
        if _issuer is not _EXECUTION_ISSUER:
            raise EvidenceValidationError("Execution receipt was not host-issued")
        self.episode_receipt = episode_receipt
        self.schema_version = R1_OBSERVATION_SCHEMA_VERSION
        self.episode_id = episode_receipt.episode_id
        self.key_id = episode_receipt.key_id
        self.question_sha256 = episode_receipt.question_sha256
        self.snapshot_ref_sha256 = episode_receipt.snapshot_ref_sha256
        self.ordinal = ordinal
        self.provider_round = provider_round
        self.action_ordinal = action_ordinal
        self.result_sha256 = result_sha256
        self.receipt_mac = receipt_mac

    def _body(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "episode_id": self.episode_id,
            "key_id": self.key_id,
            "question_sha256": self.question_sha256,
            "snapshot_ref_sha256": self.snapshot_ref_sha256,
            "ordinal": self.ordinal,
            "provider_round": self.provider_round,
            "action_ordinal": self.action_ordinal,
            "result_sha256": self.result_sha256,
        }

    def to_dict(self) -> dict[str, Any]:
        return {**self._body(), "receipt_mac": self.receipt_mac}

    @classmethod
    def issue(
        cls,
        *,
        episode_receipt: _EpisodeReceipt,
        ordinal: int,
        provider_round: int,
        action_ordinal: int,
        result_sha256: str,
    ) -> "_ExecutionReceipt":
        body = {
            "schema_version": R1_OBSERVATION_SCHEMA_VERSION,
            "episode_id": episode_receipt.episode_id,
            "key_id": episode_receipt.key_id,
            "question_sha256": episode_receipt.question_sha256,
            "snapshot_ref_sha256": episode_receipt.snapshot_ref_sha256,
            "ordinal": ordinal,
            "provider_round": provider_round,
            "action_ordinal": action_ordinal,
            "result_sha256": result_sha256,
        }
        mac = hmac.new(
            episode_receipt._secret,
            canonical_json_bytes(body),
            hashlib.sha256,
        ).hexdigest()
        return cls(
            episode_receipt=episode_receipt,
            ordinal=ordinal,
            provider_round=provider_round,
            action_ordinal=action_ordinal,
            result_sha256=result_sha256,
            receipt_mac=mac,
            _issuer=_EXECUTION_ISSUER,
        )

    def verify(self, episode_receipt: _EpisodeReceipt) -> None:
        if (
            self.episode_receipt is not episode_receipt
            or self.episode_id != episode_receipt.episode_id
            or self.key_id != episode_receipt.key_id
            or self.question_sha256 != episode_receipt.question_sha256
            or self.snapshot_ref_sha256 != episode_receipt.snapshot_ref_sha256
        ):
            raise EvidenceValidationError("Read receipt belongs to another episode")
        expected = hmac.new(
            episode_receipt._secret,
            canonical_json_bytes(self._body()),
            hashlib.sha256,
        ).hexdigest()
        if not hmac.compare_digest(expected, self.receipt_mac):
            raise EvidenceValidationError("Read receipt HMAC is invalid")


def _new_episode_id() -> str:
    return f"r1ep-{secrets.token_hex(16)}"


def _validate_episode_id(value: Any) -> str:
    if (
        not isinstance(value, str)
        or re.fullmatch(r"r1ep-[a-zA-Z0-9][a-zA-Z0-9._-]{7,127}", value) is None
    ):
        raise EvidenceValidationError("R1 episode ID is invalid")
    return value


def _round_limit(store_id: str) -> int:
    try:
        return R1_ROUND_LIMIT_BY_STORE[store_id]
    except (KeyError, TypeError) as exc:
        raise EvidenceValidationError("R1 store has no frozen round limit") from exc


def _require_round_within_limit(store_id: str, round_number: int) -> int:
    _positive_integer(round_number, "provider round")
    if round_number > _round_limit(store_id):
        raise EvidenceValidationError("Provider round exceeds the frozen store limit")
    return round_number


def _validate_genesis_note_state(state: "EvidenceNoteState") -> None:
    if (
        state.evidence_items
        or state.next_selection_ordinal != 1
        or state.skipped_items != 0
        or state.budget_used != 0
    ):
        raise EvidenceValidationError(
            "Provider round ledger must start from an empty note state"
        )


@dataclass(frozen=True)
class ObservationRecord:
    """One authenticated successful filesystem result in deterministic call order."""

    schema_version: int
    episode_id: str
    observation_id: str
    ordinal: int
    question_sha256: str
    store_id: str
    store_snapshot_sha256: str
    provider_round: int
    action_ordinal: int
    result: ReadToolResult
    observation_sha256: str
    _execution_receipt: _ExecutionReceipt = field(repr=False, compare=False)

    def __post_init__(self) -> None:
        if self.schema_version != R1_OBSERVATION_SCHEMA_VERSION:
            raise EvidenceValidationError("Observation schema version mismatch")
        _validate_episode_id(self.episode_id)
        _positive_integer(self.ordinal, "observation ordinal")
        if self.observation_id != f"obs-{self.ordinal:04d}":
            raise EvidenceValidationError("Observation ID and ordinal differ")
        if (
            not isinstance(self.question_sha256, str)
            or _SHA256.fullmatch(self.question_sha256) is None
        ):
            raise EvidenceValidationError("Observation question hash is invalid")
        if not isinstance(self.store_id, str) or not self.store_id:
            raise EvidenceValidationError("Observation store_id is invalid")
        if (
            not isinstance(self.store_snapshot_sha256, str)
            or _SHA256.fullmatch(self.store_snapshot_sha256) is None
        ):
            raise EvidenceValidationError("Observation store hash is invalid")
        _require_round_within_limit(self.store_id, self.provider_round)
        _positive_integer(self.action_ordinal, "observation action_ordinal")
        if not isinstance(self.result, ReadToolResult):
            raise EvidenceValidationError("Observation result has the wrong type")
        if not isinstance(self._execution_receipt, _ExecutionReceipt):
            raise EvidenceValidationError("Observation lacks a host execution receipt")
        receipt = self._execution_receipt
        episode = receipt.episode_receipt
        if (
            episode.episode_id != self.episode_id
            or episode.question_sha256 != self.question_sha256
            or episode.store_snapshot.store_id != self.store_id
            or episode.store_snapshot.tree_sha256 != self.store_snapshot_sha256
            or receipt.ordinal != self.ordinal
            or receipt.provider_round != self.provider_round
            or receipt.action_ordinal != self.action_ordinal
            or receipt.result_sha256 != self.result.result_sha256
        ):
            raise EvidenceValidationError("Observation execution receipt differs")
        if (
            self.result.pre_tree_sha256 != self.store_snapshot_sha256
            or self.result.post_tree_sha256 != self.store_snapshot_sha256
        ):
            raise EvidenceValidationError("Observation result uses another snapshot")
        if (
            not isinstance(self.observation_sha256, str)
            or _SHA256.fullmatch(self.observation_sha256) is None
        ):
            raise EvidenceValidationError("Observation identity is invalid")
        if sha256_bytes(canonical_json_bytes(self._body())) != self.observation_sha256:
            raise EvidenceValidationError("Observation content hash is invalid")

    def _body(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "episode_id": self.episode_id,
            "observation_id": self.observation_id,
            "ordinal": self.ordinal,
            "question_sha256": self.question_sha256,
            "store_id": self.store_id,
            "store_snapshot_sha256": self.store_snapshot_sha256,
            "provider_round": self.provider_round,
            "action_ordinal": self.action_ordinal,
            "result": self.result.to_dict(),
            "read_receipt": self._execution_receipt.to_dict(),
        }

    def to_dict(self) -> dict[str, Any]:
        return {**self._body(), "observation_sha256": self.observation_sha256}

    def to_action_dict(self) -> dict[str, Any]:
        """Compact bundle action; full content remains in the episode trace."""
        return {
            "kind": "filesystem_observation",
            "observation_id": self.observation_id,
            "provider_round": self.provider_round,
            "action_ordinal": self.action_ordinal,
            "tool_name": self.result.tool_name,
            "canonical_args": dict(self.result.canonical_args),
            "content_sha256": self.result.content_sha256,
            "coverage": [coverage.to_dict() for coverage in self.result.coverage],
            "truncated": self.result.truncated,
            "result_count": self.result.result_count,
            "root_survey": self.result.root_survey,
            "whole_tree_grep": self.result.whole_tree_grep,
            "result_sha256": self.result.result_sha256,
            "observation_sha256": self.observation_sha256,
        }

    @classmethod
    def _create_trusted(
        cls,
        *,
        episode_receipt: _EpisodeReceipt,
        ordinal: int,
        question_sha256: str,
        store_id: str,
        store_snapshot_sha256: str,
        provider_round: int,
        action_ordinal: int,
        result: ReadToolResult,
    ) -> "ObservationRecord":
        observation_id = f"obs-{ordinal:04d}"
        execution_receipt = _ExecutionReceipt.issue(
            episode_receipt=episode_receipt,
            ordinal=ordinal,
            provider_round=provider_round,
            action_ordinal=action_ordinal,
            result_sha256=result.result_sha256,
        )
        body = {
            "schema_version": R1_OBSERVATION_SCHEMA_VERSION,
            "episode_id": episode_receipt.episode_id,
            "observation_id": observation_id,
            "ordinal": ordinal,
            "question_sha256": question_sha256,
            "store_id": store_id,
            "store_snapshot_sha256": store_snapshot_sha256,
            "provider_round": provider_round,
            "action_ordinal": action_ordinal,
            "result": result.to_dict(),
            "read_receipt": execution_receipt.to_dict(),
        }
        return cls(
            schema_version=R1_OBSERVATION_SCHEMA_VERSION,
            episode_id=episode_receipt.episode_id,
            observation_id=observation_id,
            ordinal=ordinal,
            question_sha256=question_sha256,
            store_id=store_id,
            store_snapshot_sha256=store_snapshot_sha256,
            provider_round=provider_round,
            action_ordinal=action_ordinal,
            result=result,
            observation_sha256=sha256_bytes(canonical_json_bytes(body)),
            _execution_receipt=execution_receipt,
        )


@dataclass(frozen=True)
class ObservationLedger:
    """Immutable, episode-local ledger of authenticated filesystem observations."""

    episode_id: str
    question_sha256: str
    store_snapshot: StoreSnapshotRef
    observations: tuple[ObservationRecord, ...]
    _episode_receipt: _EpisodeReceipt = field(repr=False, compare=False)

    def __post_init__(self) -> None:
        _validate_episode_id(self.episode_id)
        if (
            not isinstance(self.question_sha256, str)
            or _SHA256.fullmatch(self.question_sha256) is None
        ):
            raise EvidenceValidationError("Ledger question hash is invalid")
        if not isinstance(self.store_snapshot, StoreSnapshotRef):
            raise EvidenceValidationError("Ledger snapshot has the wrong type")
        if not isinstance(self._episode_receipt, _EpisodeReceipt) or (
            self._episode_receipt.episode_id != self.episode_id
            or self._episode_receipt.question_sha256 != self.question_sha256
            or self._episode_receipt.store_snapshot != self.store_snapshot
        ):
            raise EvidenceValidationError(
                "Ledger lacks a matching host episode receipt"
            )
        if not isinstance(self.observations, (list, tuple)):
            raise EvidenceValidationError("Ledger observations must be ordered")
        observations = tuple(self.observations)
        prior_round = 0
        prior_action = 0
        for expected_ordinal, observation in enumerate(observations, 1):
            if not isinstance(observation, ObservationRecord):
                raise EvidenceValidationError("Ledger observation has the wrong type")
            if observation.ordinal != expected_ordinal:
                raise EvidenceValidationError(
                    "Ledger observation ordinals are not contiguous"
                )
            if (
                observation.episode_id != self.episode_id
                or observation._execution_receipt.episode_receipt
                is not self._episode_receipt
                or observation.question_sha256 != self.question_sha256
                or observation.store_id != self.store_snapshot.store_id
                or observation.store_snapshot_sha256 != self.store_snapshot.tree_sha256
            ):
                raise EvidenceValidationError("Ledger observation identity differs")
            observation._execution_receipt.verify(self._episode_receipt)
            if observation.provider_round < prior_round:
                raise EvidenceValidationError("Ledger provider rounds moved backwards")
            if observation.action_ordinal <= prior_action:
                raise EvidenceValidationError(
                    "Ledger action ordinals are not increasing"
                )
            prior_round = observation.provider_round
            prior_action = observation.action_ordinal
        object.__setattr__(self, "observations", observations)

    @classmethod
    def start(
        cls,
        *,
        question_sha256: str,
        snapshot: StoreSnapshotRef,
        episode_id: str | None = None,
    ) -> "ObservationLedger":
        if episode_id is None:
            episode_id = _new_episode_id()
        _validate_episode_id(episode_id)
        receipt = _EpisodeReceipt(
            episode_id=episode_id,
            question_sha256=question_sha256,
            store_snapshot=snapshot,
            secret=secrets.token_bytes(32),
            _issuer=_EPISODE_ISSUER,
        )
        return cls(
            episode_id=episode_id,
            question_sha256=question_sha256,
            store_snapshot=snapshot,
            observations=(),
            _episode_receipt=receipt,
        )

    def execute_and_append(
        self,
        *,
        filesystem: R1ReadOnlyFilesystem,
        tool_name: str,
        arguments: Mapping[str, Any],
        provider_round: int,
        action_ordinal: int,
    ) -> tuple["ObservationLedger", ObservationRecord]:
        _require_round_within_limit(self.store_snapshot.store_id, provider_round)
        _positive_integer(action_ordinal, "action_ordinal")
        if filesystem.store_id != self.store_snapshot.store_id or (
            filesystem.snapshot_tree_sha256 != self.store_snapshot.tree_sha256
        ):
            raise EvidenceValidationError("Filesystem and ledger snapshots differ")
        if self.observations:
            last = self.observations[-1]
            if provider_round < last.provider_round:
                raise EvidenceValidationError(
                    "Observation provider_round moved backwards"
                )
            if action_ordinal <= last.action_ordinal:
                raise EvidenceValidationError(
                    "Observation action_ordinal must increase"
                )
        result = filesystem.execute(tool_name, arguments)
        filesystem.authenticate_result(result)
        observation = ObservationRecord._create_trusted(
            episode_receipt=self._episode_receipt,
            ordinal=len(self.observations) + 1,
            question_sha256=self.question_sha256,
            store_id=self.store_snapshot.store_id,
            store_snapshot_sha256=self.store_snapshot.tree_sha256,
            provider_round=provider_round,
            action_ordinal=action_ordinal,
            result=result,
        )
        return (
            ObservationLedger(
                episode_id=self.episode_id,
                question_sha256=self.question_sha256,
                store_snapshot=self.store_snapshot,
                observations=(*self.observations, observation),
                _episode_receipt=self._episode_receipt,
            ),
            observation,
        )

    def validate_authenticated(self, filesystem: R1ReadOnlyFilesystem) -> None:
        """Replay every result at the trusted filesystem boundary.

        ``ObservationRecord`` is intentionally serializable, so callers must not
        treat direct dataclass construction as proof that a model-visible result
        came from this episode.  Replaying here closes that constructor bypass.
        """
        if filesystem.store_id != self.store_snapshot.store_id or (
            filesystem.snapshot_tree_sha256 != self.store_snapshot.tree_sha256
        ):
            raise EvidenceValidationError("Filesystem and ledger snapshots differ")
        for observation in self.observations:
            observation._execution_receipt.verify(self._episode_receipt)
            filesystem.authenticate_result(observation.result)

    def require(self, observation_id: str) -> ObservationRecord:
        if (
            not isinstance(observation_id, str)
            or _OBSERVATION_ID.fullmatch(observation_id) is None
        ):
            raise EvidenceValidationError("Observation ID is invalid")
        for observation in self.observations:
            if observation.observation_id == observation_id:
                return observation
        raise EvidenceValidationError("Observation ID is not in this episode")

    def prove_coverage(
        self,
        *,
        observation_ids: Sequence[str],
        path: str,
        line_start: int,
        line_end: int,
        current_round: int,
    ) -> tuple[ObservationRecord, ...]:
        if not isinstance(observation_ids, (list, tuple)) or not observation_ids:
            raise EvidenceValidationError(
                "Coverage proof needs ordered observation IDs"
            )
        if (
            len(observation_ids)
            > R1_ORCHESTRATION_LIMITS["max_observation_ids_per_note"]
        ):
            raise EvidenceValidationError("Coverage proof has too many observations")
        _positive_integer(current_round, "current_round")
        selector = LineCoverage(path, line_start, line_end)
        if len(set(observation_ids)) != len(observation_ids):
            raise EvidenceValidationError("Coverage proof repeats an observation ID")
        selected = [self.require(observation_id) for observation_id in observation_ids]
        selected.sort(key=lambda observation: observation.ordinal)
        intervals: list[tuple[int, int]] = []
        for observation in selected:
            if observation.provider_round >= current_round:
                raise EvidenceValidationError(
                    "Evidence may use only observations from an earlier provider round"
                )
            if observation.result.tool_name not in {
                "view",
                "grep",
                "section_read",
            }:
                raise EvidenceValidationError("Observation tool cannot expose evidence")
            contributing = [
                coverage
                for coverage in observation.result.coverage
                if coverage.path == selector.path
                and coverage.line_end >= selector.line_start
                and coverage.line_start <= selector.line_end
            ]
            if not contributing:
                raise EvidenceValidationError(
                    "Every named observation must cover part of the selected range"
                )
            intervals.extend(
                (
                    max(coverage.line_start, selector.line_start),
                    min(coverage.line_end, selector.line_end),
                )
                for coverage in contributing
            )
        cursor = selector.line_start
        for start, end in sorted(intervals):
            if end < cursor:
                continue
            if start > cursor:
                raise EvidenceValidationError("Selected evidence has an unobserved gap")
            cursor = max(cursor, end + 1)
            if cursor > selector.line_end:
                return tuple(selected)
        raise EvidenceValidationError("Selected evidence is not fully observed")

    def derive_global_fallback(
        self,
    ) -> tuple[GlobalFallbackProof, int] | None:
        roots = [
            observation
            for observation in self.observations
            if observation.result.root_survey
        ]
        greps = [
            observation
            for observation in self.observations
            if observation.result.whole_tree_grep
        ]
        for grep in greps:
            preceding = [
                root for root in roots if root.action_ordinal < grep.action_ordinal
            ]
            if preceding:
                root = preceding[0]
                return (
                    GlobalFallbackProof(
                        root_survey_observation_id=root.observation_id,
                        whole_tree_grep_observation_id=grep.observation_id,
                    ),
                    grep.provider_round,
                )
        return None

    @property
    def ledger_sha256(self) -> str:
        return sha256_bytes(canonical_json_bytes(self.to_dict()))

    @property
    def episode_key_id(self) -> str:
        """Return the public identifier of the private episode capability."""
        return self._episode_receipt.key_id

    def prefix_through_round(self, round_number: int) -> "ObservationLedger":
        _positive_integer(round_number, "round_number")
        return ObservationLedger(
            episode_id=self.episode_id,
            question_sha256=self.question_sha256,
            store_snapshot=self.store_snapshot,
            observations=tuple(
                observation
                for observation in self.observations
                if observation.provider_round <= round_number
            ),
            _episode_receipt=self._episode_receipt,
        )

    def prefix_before_round(self, round_number: int) -> "ObservationLedger":
        _positive_integer(round_number, "round_number")
        return ObservationLedger(
            episode_id=self.episode_id,
            question_sha256=self.question_sha256,
            store_snapshot=self.store_snapshot,
            observations=tuple(
                observation
                for observation in self.observations
                if observation.provider_round < round_number
            ),
            _episode_receipt=self._episode_receipt,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "episode_id": self.episode_id,
            "episode_key_id": self._episode_receipt.key_id,
            "question_sha256": self.question_sha256,
            "store_snapshot": self.store_snapshot.to_dict(),
            "observations": [
                observation.to_dict() for observation in self.observations
            ],
        }

    def to_action_dicts(self) -> tuple[Mapping[str, Any], ...]:
        return tuple(observation.to_action_dict() for observation in self.observations)

    def write_private_checkpoint(self, path: Path) -> None:
        """Persist the episode HMAC secret once, outside public traces.

        The checkpoint is intentionally not sufficient to resume a provider
        conversation by itself.  It is the private capability required by any
        future recovery implementation to authenticate serialized observations;
        absence, wrong mode or wrong key fails closed.
        """
        target = Path(path)
        parent = target.parent
        if parent.is_symlink() or not parent.is_dir():
            raise EvidenceValidationError(
                "Private checkpoint parent must be an existing regular directory"
            )
        body = {
            "schema_version": 1,
            "episode_id": self.episode_id,
            "episode_key_id": self._episode_receipt.key_id,
            "question_sha256": self.question_sha256,
            "snapshot_ref_sha256": self._episode_receipt.snapshot_ref_sha256,
            "secret_hex": self._episode_receipt._secret.hex(),
        }
        payload = canonical_json_bytes(body) + b"\n"
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        descriptor: int | None = None
        try:
            descriptor = os.open(target, flags, 0o600)
            written = 0
            while written < len(payload):
                count = os.write(descriptor, payload[written:])
                if count <= 0:
                    raise OSError("short private-checkpoint write")
                written += count
            os.fsync(descriptor)
        except FileExistsError as exc:
            raise EvidenceValidationError(
                "Private episode checkpoint already exists"
            ) from exc
        except OSError as exc:
            try:
                if target.is_file() and not target.is_symlink():
                    target.unlink()
            except OSError:
                pass
            raise EvidenceValidationError(
                "Private episode checkpoint could not be written"
            ) from exc
        finally:
            if descriptor is not None:
                os.close(descriptor)
        self.verify_private_checkpoint(target)

    def verify_private_checkpoint(self, path: Path) -> None:
        target = Path(path)
        if target.is_symlink() or not target.is_file():
            raise EvidenceValidationError("Private episode checkpoint is missing")
        mode = stat.S_IMODE(target.stat().st_mode)
        if mode != 0o600:
            raise EvidenceValidationError(
                "Private episode checkpoint mode must be exactly 0600"
            )
        try:
            value = json.loads(target.read_bytes().decode("utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise EvidenceValidationError(
                "Private episode checkpoint is unreadable"
            ) from exc
        expected_keys = {
            "schema_version",
            "episode_id",
            "episode_key_id",
            "question_sha256",
            "snapshot_ref_sha256",
            "secret_hex",
        }
        if not isinstance(value, dict) or set(value) != expected_keys:
            raise EvidenceValidationError(
                "Private episode checkpoint fields are invalid"
            )
        try:
            secret = bytes.fromhex(value["secret_hex"])
        except (TypeError, ValueError) as exc:
            raise EvidenceValidationError(
                "Private episode checkpoint secret is invalid"
            ) from exc
        if (
            value["schema_version"] != 1
            or value["episode_id"] != self.episode_id
            or value["episode_key_id"] != self._episode_receipt.key_id
            or value["question_sha256"] != self.question_sha256
            or value["snapshot_ref_sha256"] != self._episode_receipt.snapshot_ref_sha256
            or secret != self._episode_receipt._secret
            or sha256_bytes(secret) != self._episode_receipt.key_id
        ):
            raise EvidenceValidationError(
                "Private episode checkpoint does not authenticate this episode"
            )


@dataclass(frozen=True)
class NoteSelector:
    observation_ids: tuple[str, ...]
    path: str
    line_start: int
    line_end: int

    def __post_init__(self) -> None:
        if not isinstance(self.observation_ids, (list, tuple)):
            raise R1OrchestrationError(
                "invalid_arguments", "observation_ids must be an ordered array"
            )
        observation_ids = tuple(self.observation_ids)
        if (
            not observation_ids
            or len(observation_ids)
            > R1_ORCHESTRATION_LIMITS["max_observation_ids_per_note"]
        ):
            raise R1OrchestrationError(
                "invalid_arguments", "observation_ids has an invalid size"
            )
        if any(
            not isinstance(value, str) or _OBSERVATION_ID.fullmatch(value) is None
            for value in observation_ids
        ):
            raise R1OrchestrationError(
                "invalid_arguments", "observation_ids contains an invalid ID"
            )
        if len(set(observation_ids)) != len(observation_ids):
            raise R1OrchestrationError(
                "invalid_arguments", "observation_ids must be unique"
            )
        try:
            LineCoverage(self.path, self.line_start, self.line_end)
        except EvidenceValidationError as exc:
            raise R1OrchestrationError(
                "invalid_arguments", "take_note path or line range is invalid"
            ) from exc
        object.__setattr__(self, "observation_ids", observation_ids)

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "NoteSelector":
        if not isinstance(value, Mapping):
            raise R1OrchestrationError(
                "invalid_arguments", "take_note arguments must be an object"
            )
        expected = {"observation_ids", "path", "line_start", "line_end"}
        if set(value) != expected:
            raise R1OrchestrationError(
                "invalid_arguments", "take_note arguments have the wrong fields"
            )
        return cls(
            observation_ids=value["observation_ids"],
            path=value["path"],
            line_start=value["line_start"],
            line_end=value["line_end"],
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "observation_ids": list(self.observation_ids),
            "path": self.path,
            "line_start": self.line_start,
            "line_end": self.line_end,
        }


def _item_cost(item: EvidenceItem, unit: str) -> int:
    if unit == "bytes":
        return len(item.text.encode("utf-8"))
    if unit == "characters":
        return len(item.text)
    raise EvidenceValidationError("Unsupported evidence budget unit")


@dataclass(frozen=True)
class EvidenceNoteState:
    question_sha256: str
    snapshot: StoreSnapshotRef
    evidence_items: tuple[EvidenceItem, ...]
    next_selection_ordinal: int
    budget_unit: str
    budget_limit: int
    skipped_items: int

    def __post_init__(self) -> None:
        if (
            not isinstance(self.question_sha256, str)
            or _SHA256.fullmatch(self.question_sha256) is None
        ):
            raise EvidenceValidationError("Note state question identity is invalid")
        if not isinstance(self.snapshot, StoreSnapshotRef):
            raise EvidenceValidationError("Note state snapshot has the wrong type")
        if not isinstance(self.evidence_items, (list, tuple)):
            raise EvidenceValidationError("Note state evidence_items must be ordered")
        items = tuple(self.evidence_items)
        if any(not isinstance(item, EvidenceItem) for item in items):
            raise EvidenceValidationError("Note state contains a non-evidence item")
        if any(
            item.store_id != self.snapshot.store_id
            or item.source_kind != self.snapshot.source_kind
            or item.store_snapshot_sha256 != self.snapshot.tree_sha256
            or item.source_map_sha256 != self.snapshot.source_map_sha256
            or item.records_sha256 != self.snapshot.records_sha256
            or item.attribution_index_sha256 != self.snapshot.attribution_index_sha256
            or item.rank is not None
            or item.score is not None
            for item in items
        ):
            raise EvidenceValidationError("Note state item identity differs")
        ids = [item.evidence_id for item in items]
        if len(ids) != len(set(ids)):
            raise EvidenceValidationError("Note state repeats an evidence ID")
        ordinals = [item.selection_ordinal for item in items]
        if any(left >= right for left, right in zip(ordinals, ordinals[1:])):
            raise EvidenceValidationError("Note state ordinals must strictly increase")
        by_path: dict[str, list[EvidenceItem]] = {}
        for item in items:
            by_path.setdefault(item.path, []).append(item)
        for path_items in by_path.values():
            ordered = sorted(path_items, key=lambda item: item.line_start)
            if any(
                current.line_start <= previous.line_end + 1
                for previous, current in zip(ordered, ordered[1:])
            ):
                raise EvidenceValidationError(
                    "Note state contains overlapping or adjacent evidence"
                )
        _positive_integer(self.next_selection_ordinal, "next_selection_ordinal")
        if ordinals and self.next_selection_ordinal <= max(ordinals):
            raise EvidenceValidationError(
                "next_selection_ordinal must exceed accepted ordinals"
            )
        if self.budget_unit not in {"bytes", "characters"}:
            raise EvidenceValidationError("Note state budget unit is invalid")
        if (
            isinstance(self.budget_limit, bool)
            or not isinstance(self.budget_limit, int)
            or self.budget_limit < 0
        ):
            raise EvidenceValidationError("Note state budget limit is invalid")
        if (
            isinstance(self.skipped_items, bool)
            or not isinstance(self.skipped_items, int)
            or self.skipped_items < 0
        ):
            raise EvidenceValidationError("Note state skipped_items is invalid")
        if (
            sum(_item_cost(item, self.budget_unit) for item in items)
            > self.budget_limit
        ):
            raise EvidenceValidationError("Note state exceeds its evidence budget")
        object.__setattr__(self, "evidence_items", items)

    @classmethod
    def start(
        cls,
        *,
        question_sha256: str,
        snapshot: StoreSnapshotRef,
        budget_unit: str,
        budget_limit: int,
    ) -> "EvidenceNoteState":
        return cls(
            question_sha256=question_sha256,
            snapshot=snapshot,
            evidence_items=(),
            next_selection_ordinal=1,
            budget_unit=budget_unit,
            budget_limit=budget_limit,
            skipped_items=0,
        )

    @property
    def store_id(self) -> str:
        return self.snapshot.store_id

    @property
    def source_kind(self) -> str:
        return self.snapshot.source_kind

    @property
    def store_snapshot_sha256(self) -> str:
        return self.snapshot.tree_sha256

    @property
    def budget_used(self) -> int:
        return sum(_item_cost(item, self.budget_unit) for item in self.evidence_items)

    @property
    def state_sha256(self) -> str:
        return sha256_bytes(canonical_json_bytes(self.to_dict()))

    def to_budget_record(self) -> BudgetRecord:
        return BudgetRecord(
            unit=self.budget_unit,
            tokenizer=None,
            limit=self.budget_limit,
            used=self.budget_used,
            skipped_items=self.skipped_items,
            truncated=False,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "question_sha256": self.question_sha256,
            "snapshot": self.snapshot.to_dict(),
            "evidence_items": [item.to_dict() for item in self.evidence_items],
            "next_selection_ordinal": self.next_selection_ordinal,
            "budget_unit": self.budget_unit,
            "budget_limit": self.budget_limit,
            "skipped_items": self.skipped_items,
        }


@dataclass(frozen=True)
class TakeNoteResolution:
    question_sha256: str
    observation_ledger_sha256: str
    provider_round: int
    status: str
    selector: NoteSelector
    prior_state_sha256: str
    state: EvidenceNoteState
    evidence_id: str | None
    replaced_evidence_ids: tuple[str, ...]
    contributing_observation_ids: tuple[str, ...]
    new_evidence: bool
    budget_delta: int
    resolution_sha256: str

    def __post_init__(self) -> None:
        for value, label in (
            (self.question_sha256, "question"),
            (self.observation_ledger_sha256, "observation ledger"),
        ):
            if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
                raise EvidenceValidationError(
                    f"take_note resolution {label} identity is invalid"
                )
        if not isinstance(self.state, EvidenceNoteState):
            raise EvidenceValidationError("take_note resolution state is invalid")
        _require_round_within_limit(self.state.store_id, self.provider_round)
        if self.status not in {"accepted", "duplicate", "budget_skipped"}:
            raise EvidenceValidationError("Unknown take_note resolution status")
        if not isinstance(self.selector, NoteSelector):
            raise EvidenceValidationError("take_note resolution selector is invalid")
        if (
            not isinstance(self.prior_state_sha256, str)
            or _SHA256.fullmatch(self.prior_state_sha256) is None
        ):
            raise EvidenceValidationError("take_note prior state identity is invalid")
        if self.state.question_sha256 != self.question_sha256:
            raise EvidenceValidationError(
                "take_note resolution state belongs to another question"
            )
        replaced = _ordered_tuple(self.replaced_evidence_ids, "replaced evidence IDs")
        observations = _ordered_tuple(
            self.contributing_observation_ids, "contributing observation IDs"
        )
        if any(
            not isinstance(value, str) or not value.startswith("ev-")
            for value in replaced
        ):
            raise EvidenceValidationError("Replaced evidence ID is invalid")
        if not observations or any(
            not isinstance(value, str) or _OBSERVATION_ID.fullmatch(value) is None
            for value in observations
        ):
            raise EvidenceValidationError("Resolution observation IDs are invalid")
        if len(set(replaced)) != len(replaced) or len(set(observations)) != len(
            observations
        ):
            raise EvidenceValidationError("Resolution IDs must be unique")
        if not isinstance(self.new_evidence, bool):
            raise EvidenceValidationError("Resolution new_evidence must be bool")
        if isinstance(self.budget_delta, bool) or not isinstance(
            self.budget_delta, int
        ):
            raise EvidenceValidationError("Resolution budget_delta must be an integer")
        if self.status == "accepted":
            if not self.new_evidence or self.evidence_id is None:
                raise EvidenceValidationError("Accepted resolution must add evidence")
            if self.evidence_id not in {
                item.evidence_id for item in self.state.evidence_items
            }:
                raise EvidenceValidationError(
                    "Accepted resolution evidence is absent from its state"
                )
            if any(
                replaced_id in {item.evidence_id for item in self.state.evidence_items}
                for replaced_id in replaced
            ):
                raise EvidenceValidationError(
                    "Replaced evidence must be absent from accepted state"
                )
        else:
            if self.new_evidence:
                raise EvidenceValidationError(
                    "Non-accepted resolution cannot add evidence"
                )
            if self.status == "budget_skipped" and self.evidence_id is not None:
                raise EvidenceValidationError(
                    "Budget-skipped resolution has evidence_id"
                )
            if self.status == "duplicate" and self.evidence_id not in {
                item.evidence_id for item in self.state.evidence_items
            }:
                raise EvidenceValidationError(
                    "Duplicate resolution evidence is absent from its state"
                )
            if replaced:
                raise EvidenceValidationError(
                    "Non-accepted resolution cannot replace evidence"
                )
        if self.evidence_id is not None and (
            not isinstance(self.evidence_id, str)
            or not self.evidence_id.startswith("ev-")
        ):
            raise EvidenceValidationError("Resolution evidence_id is invalid")
        object.__setattr__(self, "replaced_evidence_ids", replaced)
        object.__setattr__(self, "contributing_observation_ids", observations)
        if (
            not isinstance(self.resolution_sha256, str)
            or _SHA256.fullmatch(self.resolution_sha256) is None
            or sha256_bytes(canonical_json_bytes(self._body()))
            != self.resolution_sha256
        ):
            raise EvidenceValidationError("take_note resolution identity is invalid")

    def _body(self) -> dict[str, Any]:
        return {
            "question_sha256": self.question_sha256,
            "observation_ledger_sha256": self.observation_ledger_sha256,
            "provider_round": self.provider_round,
            "status": self.status,
            "selector": self.selector.to_dict(),
            "prior_state_sha256": self.prior_state_sha256,
            "state_sha256": self.state.state_sha256,
            "evidence_id": self.evidence_id,
            "replaced_evidence_ids": list(self.replaced_evidence_ids),
            "contributing_observation_ids": list(self.contributing_observation_ids),
            "new_evidence": self.new_evidence,
            "budget_delta": self.budget_delta,
        }

    def to_dict(self) -> dict[str, Any]:
        return {**self._body(), "resolution_sha256": self.resolution_sha256}

    @classmethod
    def create(
        cls,
        *,
        question_sha256: str,
        observation_ledger_sha256: str,
        provider_round: int,
        status: str,
        selector: NoteSelector,
        prior_state_sha256: str,
        state: EvidenceNoteState,
        evidence_id: str | None,
        replaced_evidence_ids: Sequence[str],
        contributing_observation_ids: Sequence[str],
        new_evidence: bool,
        budget_delta: int,
    ) -> "TakeNoteResolution":
        replaced = _ordered_tuple(replaced_evidence_ids, "replaced evidence IDs")
        observations = _ordered_tuple(
            contributing_observation_ids, "contributing observation IDs"
        )
        body = {
            "question_sha256": question_sha256,
            "observation_ledger_sha256": observation_ledger_sha256,
            "provider_round": provider_round,
            "status": status,
            "selector": selector.to_dict(),
            "prior_state_sha256": prior_state_sha256,
            "state_sha256": state.state_sha256,
            "evidence_id": evidence_id,
            "replaced_evidence_ids": list(replaced),
            "contributing_observation_ids": list(observations),
            "new_evidence": new_evidence,
            "budget_delta": budget_delta,
        }
        return cls(
            question_sha256=question_sha256,
            observation_ledger_sha256=observation_ledger_sha256,
            provider_round=provider_round,
            status=status,
            selector=selector,
            prior_state_sha256=prior_state_sha256,
            state=state,
            evidence_id=evidence_id,
            replaced_evidence_ids=replaced,
            contributing_observation_ids=observations,
            new_evidence=new_evidence,
            budget_delta=budget_delta,
            resolution_sha256=sha256_bytes(canonical_json_bytes(body)),
        )


class TakeNoteResolver:
    """Resolve selectors to immutable R1 evidence without trusting model text."""

    def __init__(
        self,
        *,
        root: Path,
        catalog: SourceCatalog,
        verified_manifest: VerifiedStoreManifest,
        snapshot: StoreSnapshotRef,
        question_sha256: str,
    ) -> None:
        validate_store_snapshot(
            snapshot,
            root=root,
            catalog=catalog,
            verified_manifest=verified_manifest,
        )
        self._root = Path(root)
        self._catalog = catalog
        self._verified_manifest = verified_manifest
        self._snapshot = snapshot
        if (
            not isinstance(question_sha256, str)
            or _SHA256.fullmatch(question_sha256) is None
        ):
            raise EvidenceValidationError("Resolver question hash is invalid")
        self._question_sha256 = question_sha256
        self._filesystem = R1ReadOnlyFilesystem(
            root=root,
            catalog=catalog,
            verified_manifest=verified_manifest,
            snapshot=snapshot,
        )

    def _build(
        self,
        *,
        path: str,
        line_start: int,
        line_end: int,
        current_round: int,
        observation_ids: Sequence[str],
        selection_ordinal: int,
    ) -> EvidenceItem:
        try:
            return build_evidence_item(
                root=self._root,
                catalog=self._catalog,
                verified_manifest=self._verified_manifest,
                snapshot=self._snapshot,
                path=path,
                line_start=line_start,
                line_end=line_end,
                retrieval_round=current_round,
                observation_ids=observation_ids,
                selection_ordinal=selection_ordinal,
                query_terms=(),
                rank=None,
                score=None,
            )
        except EvidenceValidationError as exc:
            # If the store drifted, the second validation raises a fatal integrity
            # error.  Otherwise this was a recoverable bad evidence selector.
            validate_store_snapshot(
                self._snapshot,
                root=self._root,
                catalog=self._catalog,
                verified_manifest=self._verified_manifest,
            )
            raise R1OrchestrationError(
                "invalid_evidence_selection",
                "Selected lines are not a complete valid evidence unit",
            ) from exc

    @staticmethod
    def _ordered_observation_ids(
        ledger: ObservationLedger, values: Sequence[str]
    ) -> tuple[str, ...]:
        return tuple(
            observation.observation_id
            for observation in sorted(
                (ledger.require(value) for value in dict.fromkeys(values)),
                key=lambda observation: observation.ordinal,
            )
        )

    def resolve(
        self,
        *,
        ledger: ObservationLedger,
        state: EvidenceNoteState,
        arguments: Mapping[str, Any],
        current_round: int,
    ) -> TakeNoteResolution:
        selector = NoteSelector.from_mapping(arguments)
        _require_round_within_limit(self._snapshot.store_id, current_round)
        if (
            ledger.question_sha256 != self._question_sha256
            or state.question_sha256 != self._question_sha256
            or ledger.store_snapshot != self._snapshot
            or state.snapshot != self._snapshot
            or state.store_id != self._snapshot.store_id
            or state.source_kind != self._snapshot.source_kind
            or state.store_snapshot_sha256 != self._snapshot.tree_sha256
        ):
            raise EvidenceValidationError(
                "Question, ledger, note state and resolver differ"
            )
        ledger.validate_authenticated(self._filesystem)
        prior_ledger_sha256 = ledger.prefix_before_round(current_round).ledger_sha256
        for item in state.evidence_items:
            validate_evidence_item(
                item,
                root=self._root,
                catalog=self._catalog,
                verified_manifest=self._verified_manifest,
                snapshot=self._snapshot,
            )
        try:
            proven = ledger.prove_coverage(
                observation_ids=selector.observation_ids,
                path=selector.path,
                line_start=selector.line_start,
                line_end=selector.line_end,
                current_round=current_round,
            )
        except EvidenceValidationError as exc:
            raise R1OrchestrationError(
                "unobserved_selection",
                "Selected lines are not continuously covered by the named observations",
            ) from exc
        current_observation_ids = tuple(
            observation.observation_id for observation in proven
        )
        candidate = self._build(
            path=selector.path,
            line_start=selector.line_start,
            line_end=selector.line_end,
            current_round=current_round,
            observation_ids=current_observation_ids,
            selection_ordinal=state.next_selection_ordinal,
        )

        union_start = candidate.line_start
        union_end = candidate.line_end
        component: list[EvidenceItem] = []
        changed = True
        while changed:
            changed = False
            for item in state.evidence_items:
                if item in component or item.path != candidate.path:
                    continue
                if (
                    union_start <= item.line_end + 1
                    and union_end >= item.line_start - 1
                ):
                    component.append(item)
                    union_start = min(union_start, item.line_start)
                    union_end = max(union_end, item.line_end)
                    changed = True

        selected_item = candidate
        contributing_ids = current_observation_ids
        selection_ordinal = state.next_selection_ordinal
        if component:
            selection_ordinal = min(item.selection_ordinal for item in component)
            contributing_ids = self._ordered_observation_ids(
                ledger,
                [
                    *(value for item in component for value in item.observation_ids),
                    *current_observation_ids,
                ],
            )
            try:
                ledger.prove_coverage(
                    observation_ids=contributing_ids,
                    path=candidate.path,
                    line_start=union_start,
                    line_end=union_end,
                    current_round=current_round,
                )
            except EvidenceValidationError as exc:
                raise R1OrchestrationError(
                    "unobserved_selection",
                    "Merged evidence would contain an unobserved line",
                ) from exc
            if (
                len(component) == 1
                and union_start == component[0].line_start
                and union_end == component[0].line_end
            ):
                return TakeNoteResolution.create(
                    question_sha256=self._question_sha256,
                    observation_ledger_sha256=prior_ledger_sha256,
                    provider_round=current_round,
                    status="duplicate",
                    selector=selector,
                    prior_state_sha256=state.state_sha256,
                    state=state,
                    evidence_id=component[0].evidence_id,
                    replaced_evidence_ids=(),
                    contributing_observation_ids=contributing_ids,
                    new_evidence=False,
                    budget_delta=0,
                )
            selected_item = self._build(
                path=candidate.path,
                line_start=union_start,
                line_end=union_end,
                current_round=current_round,
                observation_ids=contributing_ids,
                selection_ordinal=selection_ordinal,
            )

        old_cost = sum(_item_cost(item, state.budget_unit) for item in component)
        new_cost = _item_cost(selected_item, state.budget_unit)
        delta = new_cost - old_cost
        if state.budget_used + delta > state.budget_limit:
            skipped_state = EvidenceNoteState(
                question_sha256=state.question_sha256,
                snapshot=state.snapshot,
                evidence_items=state.evidence_items,
                next_selection_ordinal=state.next_selection_ordinal,
                budget_unit=state.budget_unit,
                budget_limit=state.budget_limit,
                skipped_items=state.skipped_items + 1,
            )
            return TakeNoteResolution.create(
                question_sha256=self._question_sha256,
                observation_ledger_sha256=prior_ledger_sha256,
                provider_round=current_round,
                status="budget_skipped",
                selector=selector,
                prior_state_sha256=state.state_sha256,
                state=skipped_state,
                evidence_id=None,
                replaced_evidence_ids=(),
                contributing_observation_ids=contributing_ids,
                new_evidence=False,
                budget_delta=delta,
            )

        component_ids = {item.evidence_id for item in component}
        items = [
            item
            for item in state.evidence_items
            if item.evidence_id not in component_ids
        ]
        items.append(selected_item)
        items.sort(key=lambda item: item.selection_ordinal)
        accepted_state = EvidenceNoteState(
            question_sha256=state.question_sha256,
            snapshot=state.snapshot,
            evidence_items=tuple(items),
            next_selection_ordinal=(
                state.next_selection_ordinal
                if component
                else state.next_selection_ordinal + 1
            ),
            budget_unit=state.budget_unit,
            budget_limit=state.budget_limit,
            skipped_items=state.skipped_items,
        )
        return TakeNoteResolution.create(
            question_sha256=self._question_sha256,
            observation_ledger_sha256=prior_ledger_sha256,
            provider_round=current_round,
            status="accepted",
            selector=selector,
            prior_state_sha256=state.state_sha256,
            state=accepted_state,
            evidence_id=selected_item.evidence_id,
            replaced_evidence_ids=tuple(item.evidence_id for item in component),
            contributing_observation_ids=contributing_ids,
            new_evidence=True,
            budget_delta=delta,
        )


@dataclass(frozen=True)
class ProviderRoundRecord:
    round_number: int
    observation_count: int
    observation_ledger_sha256: str
    note_state_before_sha256: str
    note_state_after_sha256: str
    resolutions: tuple[TakeNoteResolution, ...]
    take_note_resolution_ids: tuple[str, ...]
    newly_accepted_evidence_ids: tuple[str, ...]
    global_fallback_available: bool
    round_sha256: str

    def __post_init__(self) -> None:
        _positive_integer(self.round_number, "round_number")
        if (
            isinstance(self.observation_count, bool)
            or not isinstance(self.observation_count, int)
            or self.observation_count < 0
        ):
            raise EvidenceValidationError("Round observation count is invalid")
        for value, label in (
            (self.observation_ledger_sha256, "observation ledger"),
            (self.note_state_before_sha256, "prior note state"),
            (self.note_state_after_sha256, "resulting note state"),
        ):
            if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
                raise EvidenceValidationError(f"Round {label} identity is invalid")
        if not isinstance(self.take_note_resolution_ids, (list, tuple)):
            raise EvidenceValidationError("Round resolution IDs must be ordered")
        if not isinstance(self.resolutions, (list, tuple)) or any(
            not isinstance(resolution, TakeNoteResolution)
            for resolution in self.resolutions
        ):
            raise EvidenceValidationError("Round resolutions must be ordered objects")
        resolution_objects = tuple(self.resolutions)
        if not isinstance(self.newly_accepted_evidence_ids, (list, tuple)):
            raise EvidenceValidationError("Round evidence IDs must be ordered")
        resolutions = tuple(self.take_note_resolution_ids)
        evidence_ids = tuple(self.newly_accepted_evidence_ids)
        if any(
            not isinstance(value, str) or _SHA256.fullmatch(value) is None
            for value in resolutions
        ):
            raise EvidenceValidationError("Round resolution ID is invalid")
        if (
            tuple(resolution.resolution_sha256 for resolution in resolution_objects)
            != resolutions
        ):
            raise EvidenceValidationError("Round resolution objects and IDs differ")
        if any(
            not isinstance(value, str)
            or not value.startswith("ev-")
            or _SHA256.fullmatch(value[3:]) is None
            for value in evidence_ids
        ):
            raise EvidenceValidationError("Round evidence ID is invalid")
        if len(set(resolutions)) != len(resolutions) or len(set(evidence_ids)) != len(
            evidence_ids
        ):
            raise EvidenceValidationError("Round record repeats an ID")
        expected_evidence_ids = tuple(
            dict.fromkeys(
                resolution.evidence_id
                for resolution in resolution_objects
                if resolution.new_evidence and resolution.evidence_id is not None
            )
        )
        if evidence_ids != expected_evidence_ids:
            raise EvidenceValidationError(
                "Round new evidence IDs differ from authenticated resolutions"
            )
        if not isinstance(self.global_fallback_available, bool):
            raise EvidenceValidationError("Round fallback flag must be bool")
        object.__setattr__(self, "take_note_resolution_ids", resolutions)
        object.__setattr__(self, "resolutions", resolution_objects)
        object.__setattr__(self, "newly_accepted_evidence_ids", evidence_ids)
        if (
            not isinstance(self.round_sha256, str)
            or _SHA256.fullmatch(self.round_sha256) is None
            or sha256_bytes(canonical_json_bytes(self._body())) != self.round_sha256
        ):
            raise EvidenceValidationError("Provider round identity is invalid")

    def _body(self) -> dict[str, Any]:
        return {
            "round_number": self.round_number,
            "observation_count": self.observation_count,
            "observation_ledger_sha256": self.observation_ledger_sha256,
            "note_state_before_sha256": self.note_state_before_sha256,
            "note_state_after_sha256": self.note_state_after_sha256,
            "take_note_resolution_ids": list(self.take_note_resolution_ids),
            "newly_accepted_evidence_ids": list(self.newly_accepted_evidence_ids),
            "global_fallback_available": self.global_fallback_available,
        }

    def to_dict(self) -> dict[str, Any]:
        return {**self._body(), "round_sha256": self.round_sha256}

    @classmethod
    def create(
        cls,
        *,
        round_number: int,
        observation_prefix: ObservationLedger,
        note_state_before_sha256: str,
        resolutions: Sequence[TakeNoteResolution],
        global_fallback_available: bool,
    ) -> "ProviderRoundRecord":
        if not isinstance(resolutions, (list, tuple)) or any(
            not isinstance(resolution, TakeNoteResolution) for resolution in resolutions
        ):
            raise EvidenceValidationError("Round resolutions must be ordered objects")
        if any(resolution.provider_round != round_number for resolution in resolutions):
            raise EvidenceValidationError(
                "Resolution belongs to another provider round"
            )
        prior_observation_sha256 = observation_prefix.prefix_before_round(
            round_number
        ).ledger_sha256
        if any(
            resolution.question_sha256 != observation_prefix.question_sha256
            or resolution.observation_ledger_sha256 != prior_observation_sha256
            for resolution in resolutions
        ):
            raise EvidenceValidationError(
                "Resolution belongs to another question or observation history"
            )
        expected_state_sha256 = note_state_before_sha256
        for resolution in resolutions:
            if resolution.prior_state_sha256 != expected_state_sha256:
                raise EvidenceValidationError(
                    "Round take_note resolutions do not form a state chain"
                )
            expected_state_sha256 = resolution.state.state_sha256
        resolution_ids = tuple(
            resolution.resolution_sha256 for resolution in resolutions
        )
        evidence_ids = tuple(
            dict.fromkeys(
                resolution.evidence_id
                for resolution in resolutions
                if resolution.new_evidence and resolution.evidence_id is not None
            )
        )
        body = {
            "round_number": round_number,
            "observation_count": len(observation_prefix.observations),
            "observation_ledger_sha256": observation_prefix.ledger_sha256,
            "note_state_before_sha256": note_state_before_sha256,
            "note_state_after_sha256": expected_state_sha256,
            "take_note_resolution_ids": list(resolution_ids),
            "newly_accepted_evidence_ids": list(evidence_ids),
            "global_fallback_available": global_fallback_available,
        }
        return cls(
            round_number=round_number,
            observation_count=len(observation_prefix.observations),
            observation_ledger_sha256=observation_prefix.ledger_sha256,
            note_state_before_sha256=note_state_before_sha256,
            note_state_after_sha256=expected_state_sha256,
            resolutions=tuple(resolutions),
            take_note_resolution_ids=resolution_ids,
            newly_accepted_evidence_ids=evidence_ids,
            global_fallback_available=global_fallback_available,
            round_sha256=sha256_bytes(canonical_json_bytes(body)),
        )


@dataclass(frozen=True)
class ProviderRoundLedger:
    episode_id: str
    episode_key_id: str
    question_sha256: str
    store_id: str
    source_kind: str
    store_snapshot_sha256: str
    initial_note_state: EvidenceNoteState
    note_state: EvidenceNoteState
    initial_note_state_sha256: str
    note_state_sha256: str
    records: tuple[ProviderRoundRecord, ...]

    def __post_init__(self) -> None:
        _validate_episode_id(self.episode_id)
        if (
            not isinstance(self.episode_key_id, str)
            or _SHA256.fullmatch(self.episode_key_id) is None
        ):
            raise EvidenceValidationError("Round ledger episode key ID is invalid")
        if (
            not isinstance(self.question_sha256, str)
            or _SHA256.fullmatch(self.question_sha256) is None
        ):
            raise EvidenceValidationError("Round ledger question identity is invalid")
        if not isinstance(self.store_id, str) or not self.store_id:
            raise EvidenceValidationError("Round ledger store_id is invalid")
        if self.source_kind not in {"raw", "curated"}:
            raise EvidenceValidationError("Round ledger source_kind is invalid")
        for value, label in (
            (self.store_snapshot_sha256, "store snapshot"),
            (self.initial_note_state_sha256, "initial note state"),
            (self.note_state_sha256, "current note state"),
        ):
            if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
                raise EvidenceValidationError(
                    f"Round ledger {label} identity is invalid"
                )
        if not isinstance(self.initial_note_state, EvidenceNoteState) or not isinstance(
            self.note_state, EvidenceNoteState
        ):
            raise EvidenceValidationError("Round ledger note states are invalid")
        for state in (self.initial_note_state, self.note_state):
            if (
                state.question_sha256 != self.question_sha256
                or state.snapshot != self.initial_note_state.snapshot
                or state.store_id != self.store_id
                or state.source_kind != self.source_kind
                or state.store_snapshot_sha256 != self.store_snapshot_sha256
            ):
                raise EvidenceValidationError(
                    "Round ledger note state belongs to another episode"
                )
        if (
            self.initial_note_state.state_sha256 != self.initial_note_state_sha256
            or self.note_state.state_sha256 != self.note_state_sha256
        ):
            raise EvidenceValidationError("Round ledger note-state hash differs")
        _validate_genesis_note_state(self.initial_note_state)
        if not isinstance(self.records, (list, tuple)):
            raise EvidenceValidationError("Provider round records must be ordered")
        records = tuple(self.records)
        if len(records) > _round_limit(self.store_id):
            raise EvidenceValidationError("Provider round ledger exceeds frozen limit")
        expected_note_state = self.initial_note_state_sha256
        for expected, record in enumerate(records, 1):
            if not isinstance(record, ProviderRoundRecord):
                raise EvidenceValidationError("Provider round record has wrong type")
            if record.round_number != expected:
                raise EvidenceValidationError("Provider rounds must be contiguous")
            _require_round_within_limit(self.store_id, record.round_number)
            if record.note_state_before_sha256 != expected_note_state:
                raise EvidenceValidationError(
                    "Provider round note-state chain is broken"
                )
            expected_note_state = record.note_state_after_sha256
            if expected > 1 and (
                records[expected - 2].global_fallback_available
                and not record.global_fallback_available
            ):
                raise EvidenceValidationError("Global fallback state cannot revert")
        if expected_note_state != self.note_state_sha256:
            raise EvidenceValidationError("Round ledger current note state differs")
        object.__setattr__(self, "records", records)

    @classmethod
    def start(
        cls,
        *,
        observations: ObservationLedger,
        notes: EvidenceNoteState,
    ) -> "ProviderRoundLedger":
        if (
            notes.question_sha256 != observations.question_sha256
            or notes.snapshot != observations.store_snapshot
            or notes.store_id != observations.store_snapshot.store_id
            or notes.source_kind != observations.store_snapshot.source_kind
            or notes.store_snapshot_sha256 != observations.store_snapshot.tree_sha256
        ):
            raise EvidenceValidationError(
                "Initial round ledger states belong to different stores"
            )
        if observations.observations:
            raise EvidenceValidationError(
                "Provider round ledger must start before filesystem observations"
            )
        _validate_genesis_note_state(notes)
        return cls(
            episode_id=observations.episode_id,
            episode_key_id=observations._episode_receipt.key_id,
            question_sha256=observations.question_sha256,
            store_id=notes.store_id,
            source_kind=notes.source_kind,
            store_snapshot_sha256=notes.store_snapshot_sha256,
            initial_note_state=notes,
            note_state=notes,
            initial_note_state_sha256=notes.state_sha256,
            note_state_sha256=notes.state_sha256,
            records=(),
        )

    def _validate_episode_identity(
        self,
        *,
        observations: ObservationLedger,
    ) -> None:
        if (
            observations.episode_id != self.episode_id
            or observations._episode_receipt.key_id != self.episode_key_id
            or observations.question_sha256 != self.question_sha256
            or observations.store_snapshot != self.initial_note_state.snapshot
            or observations.store_snapshot.store_id != self.store_id
            or observations.store_snapshot.source_kind != self.source_kind
            or observations.store_snapshot.tree_sha256 != self.store_snapshot_sha256
        ):
            raise EvidenceValidationError(
                "Provider rounds and observations belong to different episodes"
            )

    def validate_against(
        self,
        *,
        observations: ObservationLedger,
        notes: EvidenceNoteState | None = None,
        resolver: TakeNoteResolver | None = None,
    ) -> None:
        self._validate_episode_identity(observations=observations)
        for record in self.records:
            prefix = observations.prefix_through_round(record.round_number)
            if (
                len(prefix.observations) != record.observation_count
                or prefix.ledger_sha256 != record.observation_ledger_sha256
                or (prefix.derive_global_fallback() is not None)
                != record.global_fallback_available
            ):
                raise EvidenceValidationError(
                    "Provider round observation history does not match the episode"
                )
        working_state = self.initial_note_state
        for record in self.records:
            for resolution in record.resolutions:
                if resolver is None:
                    raise EvidenceValidationError(
                        "Provider round resolutions require trusted replay"
                    )
                expected = resolver.resolve(
                    ledger=observations,
                    state=working_state,
                    arguments=resolution.selector.to_dict(),
                    current_round=record.round_number,
                )
                if expected != resolution:
                    raise EvidenceValidationError(
                        "Provider round contains an unauthenticated take_note transition"
                    )
                working_state = expected.state
            if working_state.state_sha256 != record.note_state_after_sha256:
                raise EvidenceValidationError(
                    "Provider round resulting note state differs"
                )
        if working_state != self.note_state:
            raise EvidenceValidationError("Provider round final note state differs")
        if notes is not None:
            if (
                notes.question_sha256 != self.question_sha256
                or notes.snapshot != self.initial_note_state.snapshot
                or notes.store_id != self.store_id
                or notes.source_kind != self.source_kind
                or notes.store_snapshot_sha256 != self.store_snapshot_sha256
                or notes.state_sha256 != self.note_state_sha256
            ):
                raise EvidenceValidationError(
                    "Provider rounds and note state do not match"
                )

    def close_round(
        self,
        *,
        round_number: int,
        resolutions: Sequence[TakeNoteResolution],
        observations: ObservationLedger,
        resolver: TakeNoteResolver,
    ) -> "ProviderRoundLedger":
        if not isinstance(resolver, TakeNoteResolver):
            raise EvidenceValidationError(
                "Provider round needs a trusted note resolver"
            )
        if round_number != len(self.records) + 1:
            raise EvidenceValidationError("Provider round closed out of order")
        _require_round_within_limit(self.store_id, round_number)
        self.validate_against(observations=observations, resolver=resolver)
        if any(
            observation.provider_round > round_number
            for observation in observations.observations
        ):
            raise EvidenceValidationError(
                "Provider round cannot include a future observation"
            )
        prefix = observations.prefix_through_round(round_number)
        fallback = prefix.derive_global_fallback()
        working_state = self.note_state
        for resolution in resolutions:
            expected = resolver.resolve(
                ledger=observations,
                state=working_state,
                arguments=resolution.selector.to_dict(),
                current_round=round_number,
            )
            if expected != resolution:
                raise EvidenceValidationError(
                    "take_note resolution failed trusted replay"
                )
            working_state = expected.state
        record = ProviderRoundRecord.create(
            round_number=round_number,
            observation_prefix=prefix,
            note_state_before_sha256=self.note_state_sha256,
            resolutions=resolutions,
            global_fallback_available=fallback is not None,
        )
        updated = ProviderRoundLedger(
            episode_id=self.episode_id,
            episode_key_id=self.episode_key_id,
            question_sha256=self.question_sha256,
            store_id=self.store_id,
            source_kind=self.source_kind,
            store_snapshot_sha256=self.store_snapshot_sha256,
            initial_note_state=self.initial_note_state,
            note_state=working_state,
            initial_note_state_sha256=self.initial_note_state_sha256,
            note_state_sha256=record.note_state_after_sha256,
            records=(*self.records, record),
        )
        updated.validate_against(observations=observations, resolver=resolver)
        return updated

    @property
    def rounds_completed(self) -> int:
        return len(self.records)

    @property
    def fallback_round(self) -> int | None:
        for record in self.records:
            if record.global_fallback_available:
                return record.round_number
        return None

    @property
    def rounds_without_new_evidence(self) -> int:
        fallback_round = self.fallback_round
        if fallback_round is None:
            return 0
        count = 0
        for record in self.records:
            if record.round_number <= fallback_round:
                continue
            if record.newly_accepted_evidence_ids:
                count = 0
            else:
                count += 1
        return count

    def to_dict(self) -> dict[str, Any]:
        return {
            "episode_id": self.episode_id,
            "episode_key_id": self.episode_key_id,
            "question_sha256": self.question_sha256,
            "store_id": self.store_id,
            "source_kind": self.source_kind,
            "store_snapshot_sha256": self.store_snapshot_sha256,
            "initial_note_state_sha256": self.initial_note_state_sha256,
            "note_state_sha256": self.note_state_sha256,
            "records": [record.to_dict() for record in self.records],
            "rounds_completed": self.rounds_completed,
            "fallback_round": self.fallback_round,
            "rounds_without_new_evidence": self.rounds_without_new_evidence,
        }


@dataclass(frozen=True)
class FinishSearchRequest:
    reason: str
    missing_aspects: tuple[str, ...]

    def __post_init__(self) -> None:
        if self.reason not in MODEL_FINISH_REASONS:
            raise R1OrchestrationError(
                "invalid_arguments", "finish_search reason is not model-selectable"
            )
        if not isinstance(self.missing_aspects, (list, tuple)):
            raise R1OrchestrationError(
                "invalid_arguments", "missing_aspects must be an ordered array"
            )
        aspects = tuple(self.missing_aspects)
        if len(aspects) > R1_ORCHESTRATION_LIMITS["max_missing_aspects"]:
            raise R1OrchestrationError(
                "invalid_arguments", "missing_aspects contains too many labels"
            )
        for value in aspects:
            if not isinstance(value, str) or value != value.strip() or not value:
                raise R1OrchestrationError(
                    "invalid_arguments", "missing aspect must be a trimmed label"
                )
            try:
                value.encode("utf-8", errors="strict")
            except UnicodeEncodeError as exc:
                raise R1OrchestrationError(
                    "invalid_arguments", "missing aspect must be valid UTF-8"
                ) from exc
            if value not in MISSING_ASPECT_LABELS:
                raise R1OrchestrationError(
                    "invalid_arguments",
                    "missing aspect must use the frozen non-evidence taxonomy",
                )
        if len(set(aspects)) != len(aspects):
            raise R1OrchestrationError(
                "invalid_arguments", "missing_aspects must be unique"
            )
        if self.reason == "evidence_sufficient" and aspects:
            raise R1OrchestrationError(
                "invalid_arguments", "Sufficient evidence cannot report missing aspects"
            )
        if self.reason != "evidence_sufficient" and not aspects:
            raise R1OrchestrationError(
                "invalid_arguments", "This stop reason requires a missing-aspect label"
            )
        object.__setattr__(self, "missing_aspects", aspects)

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "FinishSearchRequest":
        if not isinstance(value, Mapping) or set(value) != {
            "reason",
            "missing_aspects",
        }:
            raise R1OrchestrationError(
                "invalid_arguments", "finish_search arguments have the wrong fields"
            )
        return cls(
            reason=value["reason"],
            missing_aspects=value["missing_aspects"],
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "reason": self.reason,
            "missing_aspects": list(self.missing_aspects),
        }


class FinishSearchResolver:
    """Validate model-requested or host-enforced retrieval termination."""

    def __init__(
        self,
        *,
        root: Path,
        catalog: SourceCatalog,
        verified_manifest: VerifiedStoreManifest,
        snapshot: StoreSnapshotRef,
        question_sha256: str,
    ) -> None:
        validate_store_snapshot(
            snapshot,
            root=root,
            catalog=catalog,
            verified_manifest=verified_manifest,
        )
        self._root = Path(root)
        self._catalog = catalog
        self._verified_manifest = verified_manifest
        self._snapshot = snapshot
        if (
            not isinstance(question_sha256, str)
            or _SHA256.fullmatch(question_sha256) is None
        ):
            raise EvidenceValidationError("Resolver question hash is invalid")
        self._question_sha256 = question_sha256
        try:
            self._round_limit = R1_ROUND_LIMIT_BY_STORE[snapshot.store_id]
        except KeyError as exc:  # defensive: StoreSnapshotRef already validates IDs
            raise EvidenceValidationError("R1 store has no frozen round limit") from exc
        self._filesystem = R1ReadOnlyFilesystem(
            root=root,
            catalog=catalog,
            verified_manifest=verified_manifest,
            snapshot=snapshot,
        )
        self._note_resolver = TakeNoteResolver(
            root=root,
            catalog=catalog,
            verified_manifest=verified_manifest,
            snapshot=snapshot,
            question_sha256=question_sha256,
        )

    def _validate_shared_state(
        self,
        *,
        observations: ObservationLedger,
        notes: EvidenceNoteState,
    ) -> None:
        validate_store_snapshot(
            self._snapshot,
            root=self._root,
            catalog=self._catalog,
            verified_manifest=self._verified_manifest,
        )
        if (
            observations.question_sha256 != self._question_sha256
            or notes.question_sha256 != self._question_sha256
            or observations.store_snapshot != self._snapshot
            or notes.snapshot != self._snapshot
            or (
                notes.store_id != self._snapshot.store_id
                or notes.source_kind != self._snapshot.source_kind
                or notes.store_snapshot_sha256 != self._snapshot.tree_sha256
            )
        ):
            raise EvidenceValidationError(
                "Finish state belongs to another question or store"
            )
        observations.validate_authenticated(self._filesystem)
        for item in notes.evidence_items:
            validate_evidence_item(
                item,
                root=self._root,
                catalog=self._catalog,
                verified_manifest=self._verified_manifest,
                snapshot=self._snapshot,
            )

    @property
    def round_limit(self) -> int:
        return self._round_limit

    def _validate_round_alignment(
        self,
        *,
        observations: ObservationLedger,
        notes: EvidenceNoteState,
        rounds: ProviderRoundLedger,
    ) -> None:
        rounds.validate_against(
            observations=observations,
            notes=notes,
            resolver=self._note_resolver,
        )
        if (
            observations.observations
            and max(item.provider_round for item in observations.observations)
            > rounds.rounds_completed
        ):
            raise EvidenceValidationError(
                "Finish state has an unclosed observation round"
            )
        if (
            notes.evidence_items
            and max(item.retrieval_round for item in notes.evidence_items)
            > rounds.rounds_completed
        ):
            raise EvidenceValidationError("Finish state has an unclosed evidence round")

    def model_finish(
        self,
        *,
        arguments: Mapping[str, Any],
        observations: ObservationLedger,
        notes: EvidenceNoteState,
        rounds: ProviderRoundLedger,
    ) -> StopRecord:
        request = FinishSearchRequest.from_mapping(arguments)
        self._validate_shared_state(observations=observations, notes=notes)
        self._validate_round_alignment(
            observations=observations, notes=notes, rounds=rounds
        )
        fallback = observations.derive_global_fallback()
        proof = fallback[0] if fallback is not None else None
        no_progress = rounds.rounds_without_new_evidence
        if request.reason == "evidence_sufficient" and not notes.evidence_items:
            raise R1OrchestrationError(
                "invalid_stop", "evidence_sufficient requires accepted evidence"
            )
        if (
            request.reason
            in {
                "not_found_after_global_fallback",
                "no_progress_after_global_fallback",
            }
            and proof is None
        ):
            raise R1OrchestrationError(
                "invalid_stop", "Global fallback has not been proven"
            )
        if request.reason == "no_progress_after_global_fallback" and no_progress < 2:
            raise R1OrchestrationError(
                "invalid_stop",
                "No-progress stop requires two completed post-fallback rounds",
            )
        if request.reason == "evidence_budget_reached" and notes.skipped_items < 1:
            raise R1OrchestrationError(
                "invalid_stop", "Evidence budget has not rejected an item"
            )
        return StopRecord(
            reason=request.reason,
            hit_cap=False,
            missing_aspects=request.missing_aspects,
            rounds_without_new_evidence=no_progress,
            fallback_proof=(
                proof
                if request.reason
                in {
                    "not_found_after_global_fallback",
                    "no_progress_after_global_fallback",
                }
                else None
            ),
        )

    def host_round_limit(
        self,
        *,
        observations: ObservationLedger,
        notes: EvidenceNoteState,
        rounds: ProviderRoundLedger,
    ) -> StopRecord:
        self._validate_shared_state(observations=observations, notes=notes)
        self._validate_round_alignment(
            observations=observations, notes=notes, rounds=rounds
        )
        if rounds.rounds_completed != self._round_limit:
            raise EvidenceValidationError(
                "Host round-limit stop requires the exact configured cap"
            )
        return StopRecord(
            reason="round_limit",
            hit_cap=True,
            missing_aspects=(),
            rounds_without_new_evidence=rounds.rounds_without_new_evidence,
            fallback_proof=None,
        )
