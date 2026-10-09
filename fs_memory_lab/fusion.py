"""Deterministic E7 fusion of E2 raw and E6 curated evidence.

Fusion performs no search and no LLM summarization.  It verifies both upstream
bundles, removes exact duplicates under the frozen key, preserves source order,
and alternates RAW/CURATED items before the shared Answerer sees them.
"""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Mapping, Sequence

from .answerer import validate_answerable_evidence
from .evidence import (
    EvidenceBundle,
    EvidenceItem,
    EvidenceValidationError,
    QuestionInput,
    canonical_json_bytes,
    evidence_item_from_mapping,
    sha256_bytes,
)


FUSION_PROTOCOL_VERSION = "e7-deterministic-fusion-v1"
FUSION_CONTRACT = {
    "condition_id": "E7",
    "inputs": ["E2", "E6"],
    "search": "none-reuse-upstream-evidence",
    "deduplication_key": ["source_kind", "dia_ids", "text_sha256"],
    "ordering": "round-robin-raw-then-curated-preserve-internal-order",
    "different_text_same_locator": "retain-both",
    "per_source_budget": "B",
    "total_budget": "2B",
}
FUSION_CONTRACT_SHA256 = sha256_bytes(canonical_json_bytes(FUSION_CONTRACT))


@dataclass(frozen=True)
class FusionBudget:
    unit: str
    per_source_limit: int
    total_limit: int
    raw_used: int
    curated_used: int
    fused_used: int
    deduplicated_items: int

    def __post_init__(self) -> None:
        if self.unit not in {"bytes", "characters"}:
            raise EvidenceValidationError("Fusion budget unit is invalid")
        for value, label in (
            (self.per_source_limit, "per_source_limit"),
            (self.total_limit, "total_limit"),
            (self.raw_used, "raw_used"),
            (self.curated_used, "curated_used"),
            (self.fused_used, "fused_used"),
            (self.deduplicated_items, "deduplicated_items"),
        ):
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise EvidenceValidationError(f"Fusion budget {label} is invalid")
        if self.total_limit != 2 * self.per_source_limit:
            raise EvidenceValidationError("Fusion total budget must equal 2B")
        if self.raw_used > self.per_source_limit or self.curated_used > self.per_source_limit:
            raise EvidenceValidationError("Fusion source budget exceeds B")
        if self.fused_used > self.total_limit:
            raise EvidenceValidationError("Fusion evidence exceeds 2B")

    def to_dict(self) -> dict[str, Any]:
        return {
            "unit": self.unit,
            "per_source_limit": self.per_source_limit,
            "total_limit": self.total_limit,
            "raw_used": self.raw_used,
            "curated_used": self.curated_used,
            "fused_used": self.fused_used,
            "deduplicated_items": self.deduplicated_items,
        }


@dataclass(frozen=True)
class FusionEvidenceBundle:
    schema_version: int
    protocol_version: str
    bundle_id: str
    status: str
    question: QuestionInput
    question_sha256: str
    condition_id: str
    retrieval_id: str
    source_bundle_ids: tuple[str, str]
    source_conditions: tuple[str, str]
    source_statuses: tuple[str, str]
    contract_sha256: str
    evidence_items: tuple[EvidenceItem, ...]
    evidence_channels: tuple[str, ...]
    budget: FusionBudget
    retrieval_metrics: Mapping[str, Any]

    def __post_init__(self) -> None:
        if self.schema_version != 1 or self.protocol_version != FUSION_PROTOCOL_VERSION:
            raise EvidenceValidationError("Fusion bundle protocol differs")
        if not self.bundle_id.startswith("fusion-") or len(self.bundle_id) != 71:
            raise EvidenceValidationError("Fusion bundle ID is invalid")
        if self.status != "completed":
            raise EvidenceValidationError("Fusion bundle status must be completed")
        if not isinstance(self.question, QuestionInput) or self.question_sha256 != self.question.sha256:
            raise EvidenceValidationError("Fusion question identity differs")
        if self.condition_id != "E7" or self.retrieval_id != "fusion":
            raise EvidenceValidationError("Fusion condition must be E7/fusion")
        if self.source_conditions != ("E2", "E6"):
            raise EvidenceValidationError("Fusion sources must be E2 then E6")
        if len(self.source_bundle_ids) != 2 or any(
            not isinstance(value, str) or not value.startswith("bundle-")
            for value in self.source_bundle_ids
        ):
            raise EvidenceValidationError("Fusion source bundle IDs are invalid")
        if len(self.source_statuses) != 2 or any(
            value not in {"completed", "capped"} for value in self.source_statuses
        ):
            raise EvidenceValidationError("Fusion source statuses are invalid")
        if self.contract_sha256 != FUSION_CONTRACT_SHA256:
            raise EvidenceValidationError("Fusion contract hash differs")
        items = tuple(self.evidence_items)
        channels = tuple(self.evidence_channels)
        if len(items) != len(channels) or any(
            channel not in {"RAW", "CURATED"} for channel in channels
        ):
            raise EvidenceValidationError("Fusion evidence channels differ")
        if any(not isinstance(item, EvidenceItem) for item in items):
            raise EvidenceValidationError("Fusion evidence item is invalid")
        if len({item.evidence_id for item in items}) != len(items):
            raise EvidenceValidationError("Fusion repeats an evidence ID")
        for item, channel in zip(items, channels):
            if (item.source_kind == "raw") != (channel == "RAW"):
                raise EvidenceValidationError("Fusion evidence channel/source differs")
        object.__setattr__(self, "evidence_items", items)
        object.__setattr__(self, "evidence_channels", channels)
        if not isinstance(self.budget, FusionBudget):
            raise EvidenceValidationError("Fusion budget is invalid")
        object.__setattr__(
            self,
            "retrieval_metrics",
            MappingProxyType(dict(self.retrieval_metrics)),
        )

    def _body(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "protocol_version": self.protocol_version,
            "status": self.status,
            "question": self.question.to_dict(),
            "question_sha256": self.question_sha256,
            "condition_id": self.condition_id,
            "retrieval_id": self.retrieval_id,
            "source_bundle_ids": list(self.source_bundle_ids),
            "source_conditions": list(self.source_conditions),
            "source_statuses": list(self.source_statuses),
            "contract_sha256": self.contract_sha256,
            "evidence_items": [item.to_dict() for item in self.evidence_items],
            "evidence_channels": list(self.evidence_channels),
            "budget": self.budget.to_dict(),
            "retrieval_metrics": dict(self.retrieval_metrics),
        }

    def to_dict(self) -> dict[str, Any]:
        return {"bundle_id": self.bundle_id, **self._body()}

    @classmethod
    def create(cls, **values: Any) -> "FusionEvidenceBundle":
        placeholder = cls(bundle_id="fusion-" + "0" * 64, **values)
        bundle_id = "fusion-" + sha256_bytes(canonical_json_bytes(placeholder._body()))
        return cls(**{**placeholder.__dict__, "bundle_id": bundle_id})

    def validate_identity(self) -> None:
        recreated = FusionEvidenceBundle.create(
            schema_version=self.schema_version,
            protocol_version=self.protocol_version,
            status=self.status,
            question=self.question,
            question_sha256=self.question_sha256,
            condition_id=self.condition_id,
            retrieval_id=self.retrieval_id,
            source_bundle_ids=self.source_bundle_ids,
            source_conditions=self.source_conditions,
            source_statuses=self.source_statuses,
            contract_sha256=self.contract_sha256,
            evidence_items=self.evidence_items,
            evidence_channels=self.evidence_channels,
            budget=self.budget,
            retrieval_metrics=self.retrieval_metrics,
        )
        if recreated != self:
            raise EvidenceValidationError("Fusion bundle identity is invalid")


def _validate_source_bundle(bundle: EvidenceBundle, *, condition: str) -> None:
    validate_answerable_evidence(bundle)
    expected = {
        "E2": {"condition_id": "E2", "store_id": "s1", "retrieval_id": "r2"},
        "E6": {"condition_id": "E6", "store_id": "s3", "retrieval_id": "r3"},
    }[condition]
    if dict(bundle.condition) != expected:
        raise EvidenceValidationError(f"Fusion {condition} source condition differs")
    if bundle.status not in {"completed", "capped"}:
        raise EvidenceValidationError("Fusion requires successful source bundles")
    if bundle.errors:
        raise EvidenceValidationError("Fusion source bundles cannot contain errors")
    if not bundle.integrity["verified"] or not bundle.integrity["store_unchanged"]:
        raise EvidenceValidationError("Fusion source integrity is not verified")


def _item_size(item: EvidenceItem, unit: str) -> int:
    if unit == "bytes":
        return len(item.text.encode("utf-8"))
    return len(item.text)


def _metric_sum(raw: EvidenceBundle, curated: EvidenceBundle) -> dict[str, Any]:
    keys = (
        "provider_rounds",
        "model_calls",
        "provider_request_attempts",
        "filesystem_tool_calls",
        "orchestration_calls",
        "prompt_tokens",
        "completion_tokens",
        "total_tokens",
    )
    return {
        "source_bundle_count": 2,
        "search_calls": 0,
        "reused_upstream_retrieval": True,
        **{key: int(raw.metrics[key]) + int(curated.metrics[key]) for key in keys},
    }


def build_e7_fusion_bundle(
    raw_bundle: EvidenceBundle, curated_bundle: EvidenceBundle
) -> FusionEvidenceBundle:
    _validate_source_bundle(raw_bundle, condition="E2")
    _validate_source_bundle(curated_bundle, condition="E6")
    if raw_bundle.question != curated_bundle.question:
        raise EvidenceValidationError("Fusion source questions differ")
    if raw_bundle.budget.unit != curated_bundle.budget.unit:
        raise EvidenceValidationError("Fusion source budget units differ")
    if raw_bundle.budget.limit != curated_bundle.budget.limit:
        raise EvidenceValidationError("Fusion source budget limits differ")

    seen: set[tuple[str, tuple[str, ...], str]] = set()
    raw_items: list[EvidenceItem] = []
    curated_items: list[EvidenceItem] = []
    duplicate_count = 0
    for bundle, target in (
        (raw_bundle, raw_items),
        (curated_bundle, curated_items),
    ):
        for item in bundle.evidence_items:
            key = (item.source_kind, item.dia_ids, item.text_sha256)
            if key in seen:
                duplicate_count += 1
                continue
            seen.add(key)
            target.append(item)

    fused: list[EvidenceItem] = []
    channels: list[str] = []
    maximum = max(len(raw_items), len(curated_items), 0)
    for index in range(maximum):
        if index < len(raw_items):
            fused.append(raw_items[index])
            channels.append("RAW")
        if index < len(curated_items):
            fused.append(curated_items[index])
            channels.append("CURATED")

    unit = raw_bundle.budget.unit
    per_source = raw_bundle.budget.limit
    budget = FusionBudget(
        unit=unit,
        per_source_limit=per_source,
        total_limit=2 * per_source,
        raw_used=sum(_item_size(item, unit) for item in raw_items),
        curated_used=sum(_item_size(item, unit) for item in curated_items),
        fused_used=sum(_item_size(item, unit) for item in fused),
        deduplicated_items=duplicate_count,
    )
    bundle = FusionEvidenceBundle.create(
        schema_version=1,
        protocol_version=FUSION_PROTOCOL_VERSION,
        status="completed",
        question=raw_bundle.question,
        question_sha256=raw_bundle.question.sha256,
        condition_id="E7",
        retrieval_id="fusion",
        source_bundle_ids=(raw_bundle.bundle_id, curated_bundle.bundle_id),
        source_conditions=("E2", "E6"),
        source_statuses=(raw_bundle.status, curated_bundle.status),
        contract_sha256=FUSION_CONTRACT_SHA256,
        evidence_items=tuple(fused),
        evidence_channels=tuple(channels),
        budget=budget,
        retrieval_metrics=_metric_sum(raw_bundle, curated_bundle),
    )
    bundle.validate_identity()
    return bundle


def fusion_bundle_from_mapping(value: Mapping[str, Any]) -> FusionEvidenceBundle:
    required = {
        "bundle_id", "schema_version", "protocol_version", "status", "question",
        "question_sha256", "condition_id", "retrieval_id", "source_bundle_ids",
        "source_conditions", "source_statuses", "contract_sha256", "evidence_items",
        "evidence_channels", "budget", "retrieval_metrics",
    }
    if not isinstance(value, Mapping) or set(value) != required:
        raise EvidenceValidationError("Serialized fusion bundle fields are invalid")
    recreated = FusionEvidenceBundle.create(
        schema_version=value["schema_version"],
        protocol_version=value["protocol_version"],
        status=value["status"],
        question=QuestionInput.from_mapping(value["question"]),
        question_sha256=value["question_sha256"],
        condition_id=value["condition_id"],
        retrieval_id=value["retrieval_id"],
        source_bundle_ids=tuple(value["source_bundle_ids"]),
        source_conditions=tuple(value["source_conditions"]),
        source_statuses=tuple(value["source_statuses"]),
        contract_sha256=value["contract_sha256"],
        evidence_items=tuple(
            evidence_item_from_mapping(item) for item in value["evidence_items"]
        ),
        evidence_channels=tuple(value["evidence_channels"]),
        budget=FusionBudget(**dict(value["budget"])),
        retrieval_metrics=value["retrieval_metrics"],
    )
    if recreated.bundle_id != value["bundle_id"]:
        raise EvidenceValidationError("Serialized fusion bundle ID is invalid")
    recreated.validate_identity()
    return recreated
