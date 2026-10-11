"""Deterministic, hash-pinned Full Context source package for ``conv-50``.

The Full Context baseline has no retrieval stage.  This module reuses the
verified S1 store and the shared :class:`~fs_memory_lab.answerer.SharedAnswerer`
contract, wrapping every raw session body as one ordinary ``EvidenceItem``.
Human-readable aliases (``FC-S01`` ... ``FC-S30``) are metadata only; the
Answerer continues to cite the existing content-addressed ``ev-...`` IDs.
"""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping, Sequence

from .evidence import (
    EvidenceItem,
    EvidenceValidationError,
    QuestionInput,
    StoreSnapshotRef,
    build_evidence_item,
    canonical_json_bytes,
    evidence_item_from_mapping,
    sha256_bytes,
)
from .r1_inputs import LoadedR1Store, load_r1_store


FULL_CONTEXT_PROTOCOL_VERSION = "b3-full-context-evidence-v1"
FULL_CONTEXT_SOURCE_PROTOCOL_VERSION = "b3-full-context-source-package-v1"
FULL_CONTEXT_CONDITION_ID = "B3-FullContext"
FULL_CONTEXT_RETRIEVAL_ID = "none"
FULL_CONTEXT_SESSION_COUNT = 30
FULL_CONTEXT_TURN_COUNT = 568
FULL_CONTEXT_CAPTION_TURN_COUNT = 125
FULL_CONTEXT_ALIAS_PREFIX = "FC-S"
FULL_CONTEXT_CONTEXT_POLICY = "all-30-s1-session-bodies-no-search-no-truncation"


def _freeze_mapping(value: Mapping[str, Any], label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise EvidenceValidationError(f"{label} must be an object")
    try:
        plain = json.loads(canonical_json_bytes(value).decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:  # pragma: no cover
        raise EvidenceValidationError(f"{label} is not canonical JSON") from exc
    return MappingProxyType(dict(plain))


def _write_atomic(path: Path, payload: bytes) -> None:
    """Atomically publish bytes without overwriting an existing artifact."""

    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        try:
            offset = 0
            while offset < len(payload):
                written = os.write(descriptor, payload[offset:])
                if written <= 0:
                    raise OSError("short Full Context source-artifact write")
                offset += written
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
            descriptor = -1
        os.link(temporary, path, follow_symlinks=False)
        directory_flags = os.O_RDONLY
        if hasattr(os, "O_DIRECTORY"):
            directory_flags |= os.O_DIRECTORY
        directory = os.open(path.parent, directory_flags)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        if os.path.exists(temporary):
            os.unlink(temporary)


def _publish_idempotent(path: Path, payload: bytes) -> None:
    if path.is_symlink():
        raise EvidenceValidationError(f"Full Context artifact cannot be a symlink: {path}")
    if path.exists():
        if not path.is_file() or path.read_bytes() != payload:
            raise EvidenceValidationError(f"Existing Full Context artifact differs: {path}")
        return
    try:
        _write_atomic(path, payload)
    except FileExistsError:
        if path.is_symlink() or not path.is_file() or path.read_bytes() != payload:
            raise EvidenceValidationError(f"Existing Full Context artifact differs: {path}")


def _alias(index: int) -> str:
    return f"{FULL_CONTEXT_ALIAS_PREFIX}{index:02d}"


def build_full_context_items(
    loaded_store: LoadedR1Store,
) -> tuple[EvidenceItem, ...]:
    """Build one verified evidence item per S1 session in chronological order.

    S1 YAML frontmatter and routing headers are deliberately not model evidence.
    Each item begins at the first source turn and ends at the final ``[SxTy]``
    locator.  Consequently all 568 raw turns and every BLIP caption are retained,
    while filesystem-only metadata does not become a Full Context advantage.
    """

    if loaded_store.snapshot.store_id != "s1":
        raise EvidenceValidationError("Full Context must be built from frozen S1")
    manifest = loaded_store.verified_manifest
    expected_paths = tuple(f"session-{index:02d}.md" for index in range(1, 31))
    if manifest.file_paths != expected_paths:
        raise EvidenceValidationError("S1 session file order or membership differs")

    items: list[EvidenceItem] = []
    for index, relative_path in enumerate(expected_paths, start=1):
        spans = manifest.attribution_index.spans_for_path(relative_path)
        if not spans:
            raise EvidenceValidationError(f"S1 session has no source turns: {relative_path}")
        item = build_evidence_item(
            root=loaded_store.root,
            catalog=loaded_store.catalog,
            verified_manifest=manifest,
            snapshot=loaded_store.snapshot,
            path="/memories/" + relative_path,
            line_start=spans[0].line_start,
            line_end=spans[-1].line_end,
            retrieval_round=1,
            observation_ids=(f"obs-{index:04d}",),
            selection_ordinal=index,
            query_terms=("full-context",),
        )
        expected_session = f"session_{index}"
        if item.session_id != expected_session or item.group_id != expected_session:
            raise EvidenceValidationError("Full Context session identity differs")
        if tuple(span.locator for span in spans) != item.source_locators:
            raise EvidenceValidationError("Full Context item does not cover its whole session")
        items.append(item)

    result = tuple(items)
    locators = tuple(locator for item in result for locator in item.source_locators)
    dia_ids = tuple(dia_id for item in result for dia_id in item.dia_ids)
    if len(result) != FULL_CONTEXT_SESSION_COUNT:
        raise EvidenceValidationError("Full Context requires exactly 30 sessions")
    if len(locators) != FULL_CONTEXT_TURN_COUNT or len(set(locators)) != len(locators):
        raise EvidenceValidationError("Full Context locator coverage differs from 568 turns")
    if len(dia_ids) != len(set(dia_ids)) or set(locators) != set(loaded_store.catalog.locators):
        raise EvidenceValidationError("Full Context source coverage is not one-to-one")
    captions = sum(item.text.count("[Image caption:") for item in result)
    if captions != FULL_CONTEXT_CAPTION_TURN_COUNT:
        raise EvidenceValidationError("Full Context caption coverage differs from 125 turns")
    return result


def full_context_stats(items: Sequence[EvidenceItem]) -> dict[str, Any]:
    ordered = tuple(items)
    text = "".join(item.text for item in ordered)
    return {
        "session_count": len(ordered),
        "turn_count": sum(len(item.source_locators) for item in ordered),
        "caption_turn_count": sum(item.text.count("[Image caption:") for item in ordered),
        "evidence_characters": sum(len(item.text) for item in ordered),
        "evidence_bytes": sum(len(item.text.encode("utf-8")) for item in ordered),
        "evidence_text_sha256": sha256_bytes(text.encode("utf-8")),
        "source_coverage": "100%-by-construction",
        "retrieval_applicable": False,
    }


def full_context_contract() -> dict[str, Any]:
    body = {
        "protocol_version": FULL_CONTEXT_PROTOCOL_VERSION,
        "condition_id": FULL_CONTEXT_CONDITION_ID,
        "retrieval_id": FULL_CONTEXT_RETRIEVAL_ID,
        "source_store": "s1",
        "source_unit": "session-body",
        "source_order": "session-01-through-session-30",
        "context_policy": FULL_CONTEXT_CONTEXT_POLICY,
        "search": "none",
        "ranking": "none",
        "top_k": None,
        "summarization": "none",
        "truncation": "forbidden",
        "formal_evidence_budget": "not-applicable",
        "citation_id": "content-addressed-ev-id",
        "human_alias": "FC-S01-through-FC-S30",
    }
    return {**body, "contract_sha256": sha256_bytes(canonical_json_bytes(body))}


FULL_CONTEXT_CONTRACT_SHA256 = full_context_contract()["contract_sha256"]


@dataclass(frozen=True)
class FullContextEvidenceBundle:
    schema_version: int
    protocol_version: str
    bundle_id: str
    status: str
    question: QuestionInput
    question_sha256: str
    condition_id: str
    retrieval_id: str
    contract_sha256: str
    store_snapshot: StoreSnapshotRef
    item_aliases: tuple[str, ...]
    evidence_items: tuple[EvidenceItem, ...]
    context_stats: Mapping[str, Any]
    retrieval_metrics: Mapping[str, Any]

    def __post_init__(self) -> None:
        if self.schema_version != 1 or self.protocol_version != FULL_CONTEXT_PROTOCOL_VERSION:
            raise EvidenceValidationError("Full Context bundle protocol differs")
        if not self.bundle_id.startswith("full-context-") or len(self.bundle_id) != 77:
            raise EvidenceValidationError("Full Context bundle ID is invalid")
        if self.status != "completed":
            raise EvidenceValidationError("Full Context bundle must be completed")
        if not isinstance(self.question, QuestionInput) or self.question_sha256 != self.question.sha256:
            raise EvidenceValidationError("Full Context question identity differs")
        if self.condition_id != FULL_CONTEXT_CONDITION_ID or self.retrieval_id != "none":
            raise EvidenceValidationError("Full Context condition identity differs")
        if self.contract_sha256 != FULL_CONTEXT_CONTRACT_SHA256:
            raise EvidenceValidationError("Full Context contract hash differs")
        if not isinstance(self.store_snapshot, StoreSnapshotRef) or self.store_snapshot.store_id != "s1":
            raise EvidenceValidationError("Full Context snapshot must be frozen S1")
        aliases = tuple(self.item_aliases)
        items = tuple(self.evidence_items)
        expected_aliases = tuple(_alias(index) for index in range(1, 31))
        if aliases != expected_aliases or len(items) != FULL_CONTEXT_SESSION_COUNT:
            raise EvidenceValidationError("Full Context item aliases or count differ")
        if any(not isinstance(item, EvidenceItem) for item in items):
            raise EvidenceValidationError("Full Context contains a non-EvidenceItem")
        if tuple(item.selection_ordinal for item in items) != tuple(range(1, 31)):
            raise EvidenceValidationError("Full Context session order differs")
        expected_paths = tuple(
            f"/memories/session-{index:02d}.md" for index in range(1, 31)
        )
        expected_sessions = tuple(f"session_{index}" for index in range(1, 31))
        if tuple(item.path for item in items) != expected_paths:
            raise EvidenceValidationError("Full Context session paths differ")
        if tuple(item.session_id for item in items) != expected_sessions:
            raise EvidenceValidationError("Full Context session IDs differ")
        if tuple(item.group_id for item in items) != expected_sessions:
            raise EvidenceValidationError("Full Context group IDs differ")
        if len({item.evidence_id for item in items}) != len(items):
            raise EvidenceValidationError("Full Context evidence IDs repeat")
        for item in items:
            if (
                item.store_id != "s1"
                or item.source_kind != "raw"
                or item.store_snapshot_sha256 != self.store_snapshot.tree_sha256
                or item.source_map_sha256 != self.store_snapshot.source_map_sha256
                or item.records_sha256 != self.store_snapshot.records_sha256
                or item.attribution_index_sha256
                != self.store_snapshot.attribution_index_sha256
            ):
                raise EvidenceValidationError("Full Context item source identity differs")
        stats = _freeze_mapping(self.context_stats, "Full Context stats")
        if dict(stats) != full_context_stats(items):
            raise EvidenceValidationError("Full Context statistics differ")
        if (
            stats["session_count"] != FULL_CONTEXT_SESSION_COUNT
            or stats["turn_count"] != FULL_CONTEXT_TURN_COUNT
            or stats["caption_turn_count"] != FULL_CONTEXT_CAPTION_TURN_COUNT
            or stats["source_coverage"] != "100%-by-construction"
            or stats["retrieval_applicable"] is not False
        ):
            raise EvidenceValidationError("Full Context source coverage differs")
        metrics = _freeze_mapping(self.retrieval_metrics, "Full Context retrieval metrics")
        expected_metrics = {
            "retrieval_applicable": False,
            "search_calls": 0,
            "provider_request_attempts": 0,
            "model_calls": 0,
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
        }
        if dict(metrics) != expected_metrics:
            raise EvidenceValidationError("Full Context retrieval metrics differ")
        object.__setattr__(self, "item_aliases", aliases)
        object.__setattr__(self, "evidence_items", items)
        object.__setattr__(self, "context_stats", stats)
        object.__setattr__(self, "retrieval_metrics", metrics)

    def _body(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "protocol_version": self.protocol_version,
            "status": self.status,
            "question": self.question.to_dict(),
            "question_sha256": self.question_sha256,
            "condition_id": self.condition_id,
            "retrieval_id": self.retrieval_id,
            "contract_sha256": self.contract_sha256,
            "store_snapshot": self.store_snapshot.to_dict(),
            "item_aliases": list(self.item_aliases),
            "evidence_items": [item.to_dict() for item in self.evidence_items],
            "context_stats": dict(self.context_stats),
            "retrieval_metrics": dict(self.retrieval_metrics),
        }

    def to_dict(self) -> dict[str, Any]:
        return {"bundle_id": self.bundle_id, **self._body()}

    @classmethod
    def create(cls, **values: Any) -> "FullContextEvidenceBundle":
        placeholder = cls(bundle_id="full-context-" + "0" * 64, **values)
        identity = "full-context-" + sha256_bytes(canonical_json_bytes(placeholder._body()))
        return cls(**{**placeholder.__dict__, "bundle_id": identity})

    def validate_identity(self) -> None:
        recreated = FullContextEvidenceBundle.create(
            schema_version=self.schema_version,
            protocol_version=self.protocol_version,
            status=self.status,
            question=self.question,
            question_sha256=self.question_sha256,
            condition_id=self.condition_id,
            retrieval_id=self.retrieval_id,
            contract_sha256=self.contract_sha256,
            store_snapshot=self.store_snapshot,
            item_aliases=self.item_aliases,
            evidence_items=self.evidence_items,
            context_stats=self.context_stats,
            retrieval_metrics=self.retrieval_metrics,
        )
        if recreated != self:
            raise EvidenceValidationError("Full Context bundle identity is invalid")


def build_full_context_bundle(
    *, question: QuestionInput, loaded_store: LoadedR1Store | None = None,
    repo_root: Path | None = None,
    evidence_items: Sequence[EvidenceItem] | None = None,
) -> FullContextEvidenceBundle:
    if loaded_store is None:
        if repo_root is None:
            raise EvidenceValidationError("repo_root is required when S1 is not preloaded")
        loaded_store = load_r1_store(Path(repo_root), "s1")
    if question.conversation_id != loaded_store.snapshot.conversation_id:
        raise EvidenceValidationError("Question and Full Context conversation differ")
    items = (
        tuple(evidence_items)
        if evidence_items is not None
        else build_full_context_items(loaded_store)
    )
    return FullContextEvidenceBundle.create(
        schema_version=1,
        protocol_version=FULL_CONTEXT_PROTOCOL_VERSION,
        status="completed",
        question=question,
        question_sha256=question.sha256,
        condition_id=FULL_CONTEXT_CONDITION_ID,
        retrieval_id=FULL_CONTEXT_RETRIEVAL_ID,
        contract_sha256=FULL_CONTEXT_CONTRACT_SHA256,
        store_snapshot=loaded_store.snapshot,
        item_aliases=tuple(_alias(index) for index in range(1, 31)),
        evidence_items=items,
        context_stats=full_context_stats(items),
        retrieval_metrics={
            "retrieval_applicable": False,
            "search_calls": 0,
            "provider_request_attempts": 0,
            "model_calls": 0,
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
        },
    )


def full_context_bundle_from_mapping(value: Mapping[str, Any]) -> FullContextEvidenceBundle:
    required = {
        "bundle_id", "schema_version", "protocol_version", "status", "question",
        "question_sha256", "condition_id", "retrieval_id", "contract_sha256",
        "store_snapshot", "item_aliases", "evidence_items", "context_stats",
        "retrieval_metrics",
    }
    if not isinstance(value, Mapping) or set(value) != required:
        raise EvidenceValidationError("Serialized Full Context bundle fields are invalid")
    recreated = FullContextEvidenceBundle.create(
        schema_version=value["schema_version"],
        protocol_version=value["protocol_version"],
        status=value["status"],
        question=QuestionInput.from_mapping(value["question"]),
        question_sha256=value["question_sha256"],
        condition_id=value["condition_id"],
        retrieval_id=value["retrieval_id"],
        contract_sha256=value["contract_sha256"],
        store_snapshot=StoreSnapshotRef(**dict(value["store_snapshot"])),
        item_aliases=tuple(value["item_aliases"]),
        evidence_items=tuple(evidence_item_from_mapping(item) for item in value["evidence_items"]),
        context_stats=value["context_stats"],
        retrieval_metrics=value["retrieval_metrics"],
    )
    if recreated.bundle_id != value["bundle_id"]:
        raise EvidenceValidationError("Serialized Full Context bundle ID differs")
    return recreated


def verify_full_context_bundle(
    bundle: FullContextEvidenceBundle, *, loaded_store: LoadedR1Store,
    expected_items: Sequence[EvidenceItem] | None = None,
) -> None:
    bundle.validate_identity()
    expected = build_full_context_bundle(
        question=bundle.question,
        loaded_store=loaded_store,
        evidence_items=expected_items,
    )
    if bundle != expected:
        raise EvidenceValidationError("Full Context bundle differs from frozen S1")


def source_package(
    loaded_store: LoadedR1Store,
    *, evidence_items: Sequence[EvidenceItem] | None = None,
) -> dict[str, Any]:
    items = (
        tuple(evidence_items)
        if evidence_items is not None
        else build_full_context_items(loaded_store)
    )
    aliases = tuple(_alias(index) for index in range(1, 31))
    body = {
        "schema_version": 1,
        "protocol_version": FULL_CONTEXT_SOURCE_PROTOCOL_VERSION,
        "status": "verified",
        "condition_id": FULL_CONTEXT_CONDITION_ID,
        "contract": full_context_contract(),
        "store_snapshot": loaded_store.snapshot.to_dict(),
        "item_aliases": [
            {"alias": alias, "evidence_id": item.evidence_id, "path": item.path}
            for alias, item in zip(aliases, items)
        ],
        "evidence_items": [item.to_dict() for item in items],
        "context_stats": full_context_stats(items),
    }
    return {
        "source_package_id": "full-context-source-" + sha256_bytes(canonical_json_bytes(body)),
        **body,
    }


def render_human_transcript(package: Mapping[str, Any]) -> str:
    aliases = package["item_aliases"]
    items = package["evidence_items"]
    blocks = []
    for alias_row, item in zip(aliases, items):
        blocks.append(
            f"===== {alias_row['alias']} | {item['evidence_id']} | {item['path']} =====\n\n"
            + item["text"]
        )
    return "\n\n".join(blocks) + "\n"


def publish_source_package(*, repo_root: Path, output_dir: Path) -> dict[str, Any]:
    loaded = load_r1_store(Path(repo_root), "s1")
    package = source_package(loaded)
    transcript = render_human_transcript(package)
    package_payload = canonical_json_bytes(package) + b"\n"
    transcript_payload = transcript.encode("utf-8")
    manifest_body = {
        "schema_version": 1,
        "protocol_version": FULL_CONTEXT_SOURCE_PROTOCOL_VERSION,
        "source_package_id": package["source_package_id"],
        "source_package_sha256": sha256_bytes(package_payload),
        "transcript_sha256": sha256_bytes(transcript_payload),
        "contract_sha256": FULL_CONTEXT_CONTRACT_SHA256,
        "store_snapshot": loaded.snapshot.to_dict(),
        "counts": package["context_stats"],
        "formal_prompt_item_policy": (
            "one verified S1 session body per ev-* item; FC-Sxx is a display alias only"
        ),
    }
    manifest = {
        "manifest_id": "full-context-manifest-" + sha256_bytes(canonical_json_bytes(manifest_body)),
        **manifest_body,
    }
    verification_body = {
        "schema_version": 1,
        "status": "passed",
        "checks": {
            "sessions_30": package["context_stats"]["session_count"] == 30,
            "turns_568": package["context_stats"]["turn_count"] == 568,
            "caption_turns_125": package["context_stats"]["caption_turn_count"] == 125,
            "all_source_locators_once": len({
                locator
                for item in package["evidence_items"]
                for locator in item["source_locators"]
            }) == 568,
            "no_search": package["contract"]["search"] == "none",
            "no_truncation": package["contract"]["truncation"] == "forbidden",
            "content_addressed_citations": all(
                row["evidence_id"].startswith("ev-") for row in package["item_aliases"]
            ),
        },
        "source_package_id": package["source_package_id"],
        "manifest_id": manifest["manifest_id"],
    }
    if not all(verification_body["checks"].values()):  # pragma: no cover
        raise EvidenceValidationError("Full Context source verification failed")
    verification = {
        "verification_id": "full-context-verification-"
        + sha256_bytes(canonical_json_bytes(verification_body)),
        **verification_body,
    }
    output = Path(output_dir).resolve()
    _publish_idempotent(output / "context-package.json", package_payload)
    _publish_idempotent(output / "transcript.txt", transcript_payload)
    _publish_idempotent(output / "manifest.json", canonical_json_bytes(manifest) + b"\n")
    _publish_idempotent(
        output / "verification.json", canonical_json_bytes(verification) + b"\n"
    )
    return {
        "status": "passed",
        "output_dir": str(output),
        "source_package_id": package["source_package_id"],
        "manifest_id": manifest["manifest_id"],
        "counts": package["context_stats"],
    }
