"""Host-verified evidence artifacts shared by R1, R2, and E7.

The model may select only line ranges it has actually observed. It never supplies
evidence text or provenance. This module re-reads a frozen store, derives attribution
from canonical ``[SxTy]`` locators, and produces immutable, content-addressed records.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
from dataclasses import InitVar, asdict, dataclass, field
from pathlib import Path, PurePosixPath
from types import MappingProxyType
from typing import Any, Iterable, Mapping, Sequence


EVIDENCE_SCHEMA_VERSION = 1
EVIDENCE_PROTOCOL_VERSION = "shared-evidence-bundle-v1"
FORBIDDEN_QUESTION_KEYS = frozenset({
    "answer",
    "category",
    "category_name",
    "evidence",
    "gold_evidence_dia_ids",
    "gold_evidence_locators",
})
QUESTION_KEYS = frozenset({
    "schema_version",
    "question_set_id",
    "run_position",
    "question_id",
    "conversation_id",
    "question",
})
STORE_SOURCE_KINDS = MappingProxyType({"s1": "raw", "s2": "raw", "s3": "curated"})
RETRIEVAL_IDS = frozenset({"r1", "r2", "r3", "fusion"})
STOP_REASONS = frozenset({
    "evidence_sufficient",
    "not_found_after_global_fallback",
    "no_progress_after_global_fallback",
    "evidence_budget_reached",
    "round_limit",
    "protocol_failure",
})
COMPLETED_STOP_REASONS = frozenset({
    "evidence_sufficient",
    "not_found_after_global_fallback",
    "no_progress_after_global_fallback",
    "evidence_budget_reached",
})
CONDITION_KEYS = frozenset({"condition_id", "store_id", "retrieval_id"})
PROMPT_CONTRACT_KEYS = frozenset({
    "paper_prompt_id",
    "paper_prompt_sha256",
    "derived_prompt_sha256",
    "filesystem_tools_sha256",
    "orchestration_actions_sha256",
})
RUNTIME_CONTRACT_KEYS = frozenset({
    "runtime_sha256",
    "round_limit",
    "evidence_budget_unit",
    "evidence_budget_limit",
})
METRIC_KEYS = frozenset({
    "provider_rounds",
    "model_calls",
    "provider_request_attempts",
    "filesystem_tool_calls",
    "orchestration_calls",
    "prompt_tokens",
    "completion_tokens",
    "total_tokens",
    "token_usage_available",
})
MODEL_KEYS = frozenset({"requested_model", "served_models"})
INTEGRITY_KEYS = frozenset({
    "store_unchanged",
    "pre_tree_sha256",
    "post_tree_sha256",
    "verified",
})
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_LOCATOR = re.compile(r"\[S([1-9][0-9]*)T([1-9][0-9]*)\]")
_LOCATOR_CANDIDATE = re.compile(r"\[S[^\]\s]*T[^\]\s]*\]")
_RAW_LOCATOR_LINE = re.compile(
    r"^(\[S([1-9][0-9]*)T([1-9][0-9]*)\]) \(dia_id: (D[1-9][0-9]*:[1-9][0-9]*)\)$"
)
_OBSERVATION_ID = re.compile(r"obs-[0-9]{4,}\Z")
_VIRTUAL_PATH = re.compile(r"/memories/.+\.md\Z")
_HEADING = re.compile(r"^(#{1,6})\s+(.+?)\s*$")
_SOURCE_CATALOG_SEAL = object()
_VERIFIED_MANIFEST_SEAL = object()
_RAW_SOURCE_INDEX_KEYS = frozenset({
    "dia_id",
    "end_line",
    "file",
    "global_turn_index",
    "raw_turn_sha256",
    "source_sha256",
    "start_line",
    "turn_index",
})
_CURATED_SOURCE_OCCURRENCE_KEYS = frozenset({"file", "line"})


class EvidenceValidationError(ValueError):
    """Raised when an evidence artifact cannot be proven from frozen inputs."""


def _require_sha256(value: Any, label: str) -> str:
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        raise EvidenceValidationError(f"{label} must be a lowercase SHA-256 digest")
    return value


def _require_nonempty(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise EvidenceValidationError(f"{label} must be a nonempty string")
    return value


def _require_int(value: Any, label: str, *, minimum: int = 0) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < minimum:
        raise EvidenceValidationError(f"{label} must be an integer >= {minimum}")
    return value


def _stable_unique(values: Iterable[str]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(values))


def _ordered_tuple(value: Any, label: str) -> tuple[Any, ...]:
    """Freeze a caller-supplied ordered array without inventing an order.

    Protocol arrays accept only JSON-array-like Python values.  Sets, mappings,
    generators and strings are rejected because iterating them can be unstable or
    can silently reinterpret one value as many values.
    """
    if not isinstance(value, (list, tuple)):
        raise EvidenceValidationError(f"{label} must be an ordered list or tuple")
    return tuple(value)


def _plain_json(value: Any) -> Any:
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise EvidenceValidationError("JSON numbers must be finite")
        return value
    if isinstance(value, Mapping):
        plain: dict[str, Any] = {}
        for key, nested in value.items():
            if not isinstance(key, str):
                raise EvidenceValidationError("JSON object keys must be strings")
            plain[key] = _plain_json(nested)
        return plain
    if isinstance(value, (tuple, list)):
        return [_plain_json(nested) for nested in value]
    raise EvidenceValidationError(
        f"Value has a non-JSON type: {type(value).__name__}"
    )


def _freeze_json(value: Any) -> Any:
    plain = _plain_json(value)
    if isinstance(plain, dict):
        return MappingProxyType(
            {key: _freeze_json(plain[key]) for key in sorted(plain)}
        )
    if isinstance(plain, list):
        return tuple(_freeze_json(nested) for nested in plain)
    return plain


def _freeze_mapping(value: Mapping[str, Any], label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise EvidenceValidationError(f"{label} must be a JSON object")
    frozen = _freeze_json(value)
    if not isinstance(frozen, Mapping):
        raise EvidenceValidationError(f"{label} must be a JSON object")
    return frozen


def canonical_json_bytes(value: Any) -> bytes:
    """Serialize protocol JSON deterministically and reject invalid JSON values."""
    try:
        return json.dumps(
            _plain_json(value),
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise EvidenceValidationError(f"Value is not canonical JSON: {exc}") from exc


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


@dataclass(frozen=True)
class QuestionInput:
    schema_version: int
    question_set_id: str
    run_position: int
    question_id: str
    conversation_id: str
    question: str

    def __post_init__(self) -> None:
        if self.schema_version != 1:
            raise EvidenceValidationError("Online question schema_version must be 1")
        _require_nonempty(self.question_set_id, "question_set_id")
        _require_int(self.run_position, "run_position", minimum=1)
        _require_nonempty(self.question_id, "question_id")
        _require_nonempty(self.conversation_id, "conversation_id")
        _require_nonempty(self.question, "question")

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "QuestionInput":
        if not isinstance(value, Mapping):
            raise EvidenceValidationError("Online question must be an object")
        keys = set(value)
        forbidden = keys & FORBIDDEN_QUESTION_KEYS
        if forbidden:
            raise EvidenceValidationError(
                f"Online question contains forbidden gold keys: {sorted(forbidden)}"
            )
        if keys != QUESTION_KEYS:
            raise EvidenceValidationError(
                f"Online question keys must be exactly {sorted(QUESTION_KEYS)}"
            )
        return cls(**{key: value[key] for key in QUESTION_KEYS})

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @property
    def sha256(self) -> str:
        return sha256_bytes(canonical_json_bytes(self.to_dict()))


@dataclass(frozen=True)
class SourceRecordRef:
    locator: str
    dia_id: str
    session_id: str
    session_index: int
    turn_index: int
    global_turn_index: int
    session_date: str
    session_datetime: str
    speaker: str
    source_sha256: str
    raw_turn_sha256: str
    rendered_turn_sha256: str

    def __post_init__(self) -> None:
        if _LOCATOR.fullmatch(self.locator) is None:
            raise EvidenceValidationError("Source record locator is invalid")
        _require_nonempty(self.dia_id, "source dia_id")
        _require_nonempty(self.session_id, "source session_id")
        _require_int(self.session_index, "source session_index", minimum=1)
        _require_int(self.turn_index, "source turn_index", minimum=1)
        _require_int(self.global_turn_index, "source global_turn_index", minimum=1)
        _require_nonempty(self.session_date, "source session_date")
        _require_nonempty(self.session_datetime, "source session_datetime")
        _require_nonempty(self.speaker, "source speaker")
        _require_sha256(self.source_sha256, "source source_sha256")
        _require_sha256(self.raw_turn_sha256, "source raw_turn_sha256")
        _require_sha256(
            self.rendered_turn_sha256, "source rendered_turn_sha256"
        )
        if self.locator != f"[S{self.session_index}T{self.turn_index}]":
            raise EvidenceValidationError("Source locator coordinates are inconsistent")
        if self.dia_id != f"D{self.session_index}:{self.turn_index}":
            raise EvidenceValidationError("Source dia_id coordinates are inconsistent")
        if self.session_id != f"session_{self.session_index}":
            raise EvidenceValidationError("Source session_id coordinates are inconsistent")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _read_catalog_file(path: Path, label: str) -> bytes:
    lexical = Path(os.path.abspath(Path(path)))
    try:
        resolved = lexical.resolve(strict=True)
    except OSError as exc:
        raise EvidenceValidationError(f"Cannot resolve {label}: {exc}") from exc
    if lexical != resolved or lexical.is_symlink() or not lexical.is_file():
        raise EvidenceValidationError(f"{label} must be a non-symlink regular file")
    try:
        return lexical.read_bytes()
    except OSError as exc:
        raise EvidenceValidationError(f"Cannot read {label}: {exc}") from exc


@dataclass(frozen=True)
class SourceCatalog:
    """Hash-pinned locator-to-canonical-record mapping for one conversation."""

    conversation_id: str
    source_map_sha256: str
    records_sha256: str
    _by_locator: Mapping[str, SourceRecordRef]
    _verification_seal: InitVar[object]

    def __post_init__(self, _verification_seal: object) -> None:
        if _verification_seal is not _SOURCE_CATALOG_SEAL:
            raise EvidenceValidationError(
                "SourceCatalog must be produced by the hash-pinned loader"
            )
        _require_nonempty(self.conversation_id, "conversation_id")
        _require_sha256(self.source_map_sha256, "source_map_sha256")
        _require_sha256(self.records_sha256, "records_sha256")
        object.__setattr__(
            self, "_by_locator", MappingProxyType(dict(self._by_locator))
        )

    @classmethod
    def load(
        cls,
        source_map_path: Path,
        records_path: Path,
        *,
        expected_source_map_sha256: str,
        expected_records_sha256: str,
        expected_conversation_id: str,
    ) -> "SourceCatalog":
        expected_map_hash = _require_sha256(
            expected_source_map_sha256, "expected_source_map_sha256"
        )
        expected_record_hash = _require_sha256(
            expected_records_sha256, "expected_records_sha256"
        )
        expected_conversation_id = _require_nonempty(
            expected_conversation_id, "expected_conversation_id"
        )
        source_map_bytes = _read_catalog_file(Path(source_map_path), "source_map")
        records_bytes = _read_catalog_file(Path(records_path), "canonical records")
        actual_map_hash = sha256_bytes(source_map_bytes)
        actual_record_hash = sha256_bytes(records_bytes)
        if actual_map_hash != expected_map_hash:
            raise EvidenceValidationError("source_map does not match its frozen hash")
        if actual_record_hash != expected_record_hash:
            raise EvidenceValidationError("Canonical records do not match their frozen hash")
        try:
            source_map = json.loads(source_map_bytes.decode("utf-8"))
            records = [
                json.loads(line)
                for line in records_bytes.decode("utf-8").splitlines()
                if line
            ]
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise EvidenceValidationError(f"Cannot parse source catalog: {exc}") from exc
        if not isinstance(source_map, dict) or any(
            not isinstance(record, dict) for record in records
        ):
            raise EvidenceValidationError("Source catalog JSON has the wrong shape")
        if source_map.get("schema_version") != 1:
            raise EvidenceValidationError("source_map schema_version must be 1")
        if source_map.get("conversation_id") != expected_conversation_id:
            raise EvidenceValidationError("source_map conversation does not match the contract")
        if source_map.get("record_sha256") != actual_record_hash:
            raise EvidenceValidationError("Canonical-record hash does not match source_map")
        if source_map.get("record_bytes") != len(records_bytes):
            raise EvidenceValidationError("Canonical-record byte count does not match source_map")
        if source_map.get("record_count") != len(records):
            raise EvidenceValidationError("Canonical-record count does not match source_map")
        by_locator_map = source_map.get("by_locator")
        by_dia_id_map = source_map.get("by_dia_id")
        sessions_map = source_map.get("sessions")
        if not all(
            isinstance(value, dict)
            for value in (by_locator_map, by_dia_id_map, sessions_map)
        ):
            raise EvidenceValidationError("source_map indexes must be objects")

        resolved: dict[str, SourceRecordRef] = {}
        dia_ids: set[str] = set()
        records_by_session: dict[str, list[tuple[int, Mapping[str, Any]]]] = {}
        required_record_keys = {
            "schema_version",
            "conversation_id",
            "session_id",
            "session_index",
            "session_date",
            "session_datetime",
            "turn_index",
            "global_turn_index",
            "locator",
            "dia_id",
            "speaker",
            "source_sha256",
            "raw_turn_sha256",
        }
        for line_number, record in enumerate(records, start=1):
            if not required_record_keys.issubset(record):
                raise EvidenceValidationError(
                    f"Canonical record {line_number} lacks required fields"
                )
            if record.get("schema_version") != 1:
                raise EvidenceValidationError("Canonical record schema_version must be 1")
            if record.get("conversation_id") != expected_conversation_id:
                raise EvidenceValidationError("Canonical record conversation mismatch")
            session_index = _require_int(
                record.get("session_index"), "record session_index", minimum=1
            )
            turn_index = _require_int(
                record.get("turn_index"), "record turn_index", minimum=1
            )
            global_turn_index = _require_int(
                record.get("global_turn_index"), "record global_turn_index", minimum=1
            )
            if global_turn_index != line_number:
                raise EvidenceValidationError("Canonical global_turn_index is not contiguous")
            locator = _require_nonempty(record.get("locator"), "record locator")
            dia_id = _require_nonempty(record.get("dia_id"), "record dia_id")
            if locator in resolved or dia_id in dia_ids:
                raise EvidenceValidationError("Canonical locator or dia_id is duplicated")
            source_ref = SourceRecordRef(
                locator=locator,
                dia_id=dia_id,
                session_id=_require_nonempty(record.get("session_id"), "record session_id"),
                session_index=session_index,
                turn_index=turn_index,
                global_turn_index=global_turn_index,
                session_date=_require_nonempty(
                    record.get("session_date"), "record session_date"
                ),
                session_datetime=_require_nonempty(
                    record.get("session_datetime"), "record session_datetime"
                ),
                speaker=_require_nonempty(record.get("speaker"), "record speaker"),
                source_sha256=_require_sha256(
                    record.get("source_sha256"), "record source_sha256"
                ),
                raw_turn_sha256=_require_sha256(
                    record.get("raw_turn_sha256"), "record raw_turn_sha256"
                ),
                rendered_turn_sha256="0" * 64,
            )
            text = record.get("text")
            media = record.get("media")
            if not isinstance(text, str) or not text or "\r" in text:
                raise EvidenceValidationError("Canonical source text is invalid")
            if not isinstance(media, dict) or set(media) != {
                "img_url", "blip_caption", "query", "re-download"
            }:
                raise EvidenceValidationError("Canonical source media is invalid")
            if source_ref.source_sha256 != sha256_bytes(text.encode("utf-8")):
                raise EvidenceValidationError("Canonical source text hash is invalid")
            raw_turn = {"speaker": source_ref.speaker}
            raw_turn.update(
                {key: media[key] for key in ("img_url", "blip_caption", "query", "re-download")
                 if media[key] is not None}
            )
            raw_turn.update({"dia_id": dia_id, "text": text})
            if source_ref.raw_turn_sha256 != sha256_bytes(canonical_json_bytes(raw_turn)):
                raise EvidenceValidationError("Canonical raw-turn hash is invalid")
            rendered_lines = [f"{source_ref.speaker}: {text}"]
            caption = media.get("blip_caption")
            if caption is not None:
                if (
                    not isinstance(caption, str)
                    or not caption
                    or "\n" in caption
                    or "\r" in caption
                ):
                    raise EvidenceValidationError("Canonical BLIP caption is invalid")
                rendered_lines.append(f"[Image caption: {caption}]")
            rendered_lines.append(f"{locator} (dia_id: {dia_id})")
            source_ref = SourceRecordRef(
                **{
                    **source_ref.to_dict(),
                    "rendered_turn_sha256": sha256_bytes(
                        "\n".join(rendered_lines).encode("utf-8")
                    ),
                }
            )
            mapped = by_locator_map.get(locator)
            if not isinstance(mapped, dict):
                raise EvidenceValidationError(f"source_map lacks locator {locator}")
            expected_mapping = {
                "dia_id": dia_id,
                "jsonl_line": line_number,
                "raw_turn_sha256": record["raw_turn_sha256"],
                "session_id": source_ref.session_id,
                "session_index": session_index,
                "source_sha256": record["source_sha256"],
                "speaker": source_ref.speaker,
                "turn_index": turn_index,
            }
            for key, expected in expected_mapping.items():
                if mapped.get(key) != expected:
                    raise EvidenceValidationError(f"source_map drift for {locator}: {key}")
            dia_mapping = by_dia_id_map.get(dia_id)
            if dia_mapping != {"jsonl_line": line_number, "locator": locator}:
                raise EvidenceValidationError(f"source_map dia_id drift for {dia_id}")
            resolved[locator] = source_ref
            dia_ids.add(dia_id)
            records_by_session.setdefault(source_ref.session_id, []).append(
                (line_number, record)
            )

        if set(resolved) != set(by_locator_map) or dia_ids != set(by_dia_id_map):
            raise EvidenceValidationError("source_map and canonical-record indexes differ")
        if set(records_by_session) != set(sessions_map):
            raise EvidenceValidationError("source_map session index differs from records")
        for session_id, members in records_by_session.items():
            summary = sessions_map.get(session_id)
            if not isinstance(summary, dict):
                raise EvidenceValidationError(f"Invalid session summary: {session_id}")
            first_line = members[0][0]
            last_line = members[-1][0]
            first = members[0][1]
            expected_summary = {
                "first_jsonl_line": first_line,
                "last_jsonl_line": last_line,
                "session_date": first["session_date"],
                "session_datetime": first["session_datetime"],
                "session_datetime_raw": first.get("session_datetime_raw"),
                "session_index": first["session_index"],
                "turn_count": len(members),
            }
            for key, expected in expected_summary.items():
                if summary.get(key) != expected:
                    raise EvidenceValidationError(
                        f"source_map session drift for {session_id}: {key}"
                    )
            if [member[1]["turn_index"] for member in members] != list(
                range(1, len(members) + 1)
            ):
                raise EvidenceValidationError(
                    f"Canonical turn indexes are not contiguous for {session_id}"
                )
        return cls(
            conversation_id=expected_conversation_id,
            source_map_sha256=actual_map_hash,
            records_sha256=actual_record_hash,
            _by_locator=resolved,
            _verification_seal=_SOURCE_CATALOG_SEAL,
        )

    def resolve(self, locator: str) -> SourceRecordRef:
        try:
            return self._by_locator[locator]
        except KeyError as exc:
            raise EvidenceValidationError(
                f"Source locator is not in the frozen catalog: {locator}"
            ) from exc

    def resolve_many(self, locators: Sequence[str]) -> tuple[SourceRecordRef, ...]:
        ordered = _ordered_tuple(locators, "locators")
        return tuple(self.resolve(locator) for locator in ordered)

    @property
    def locators(self) -> frozenset[str]:
        return frozenset(self._by_locator)


def _canonical_relative_markdown_path(value: Any, label: str) -> str:
    path_text = _require_nonempty(value, label)
    try:
        path_text.encode("utf-8", errors="strict")
    except UnicodeEncodeError as exc:
        raise EvidenceValidationError(f"{label} must be valid UTF-8 text") from exc
    if "\\" in path_text or any(
        ord(character) < 32 or ord(character) == 127 for character in path_text
    ):
        raise EvidenceValidationError(
            f"{label} must use safe POSIX path characters"
        )
    path = PurePosixPath(path_text)
    if (
        path.is_absolute()
        or not path.parts
        or any(part in {"", ".", ".."} for part in path.parts)
        or path.suffix != ".md"
        or path.as_posix() != path_text
    ):
        raise EvidenceValidationError(f"{label} is not a canonical relative Markdown path")
    return path_text


@dataclass(frozen=True)
class SourceSpan:
    path: str
    line_start: int
    line_end: int
    locator: str
    dia_id: str

    def __post_init__(self) -> None:
        _canonical_relative_markdown_path(self.path, "source span path")
        _require_int(self.line_start, "source span line_start", minimum=1)
        _require_int(
            self.line_end, "source span line_end", minimum=self.line_start
        )
        if _LOCATOR.fullmatch(self.locator) is None:
            raise EvidenceValidationError("Source span locator is invalid")
        _require_nonempty(self.dia_id, "source span dia_id")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class AttributionIndex:
    """Frozen, store-specific locator placements from a verified store manifest."""

    store_id: str
    source_kind: str
    index_sha256: str
    _by_locator: Mapping[str, tuple[SourceSpan, ...]]

    def __post_init__(self) -> None:
        if self.store_id not in STORE_SOURCE_KINDS:
            raise EvidenceValidationError(f"Unknown attribution store_id: {self.store_id}")
        if self.source_kind != STORE_SOURCE_KINDS[self.store_id]:
            raise EvidenceValidationError("Attribution index store/source kind mismatch")
        _require_sha256(self.index_sha256, "attribution index_sha256")
        frozen: dict[str, tuple[SourceSpan, ...]] = {}
        for locator, spans in self._by_locator.items():
            if _LOCATOR.fullmatch(locator) is None:
                raise EvidenceValidationError("Attribution index contains an invalid locator")
            span_tuple = _ordered_tuple(spans, "attribution spans")
            if not span_tuple or any(span.locator != locator for span in span_tuple):
                raise EvidenceValidationError("Attribution span and locator index disagree")
            frozen[locator] = span_tuple
        object.__setattr__(self, "_by_locator", MappingProxyType(frozen))

    @classmethod
    def from_source_index(
        cls,
        *,
        store_id: str,
        source_index: Mapping[str, Any],
        catalog: SourceCatalog,
    ) -> "AttributionIndex":
        if store_id not in STORE_SOURCE_KINDS:
            raise EvidenceValidationError(f"Unknown attribution store_id: {store_id}")
        if not isinstance(source_index, Mapping) or not source_index:
            raise EvidenceValidationError("source_index must be a nonempty object")
        plain_index = _plain_json(source_index)
        by_locator: dict[str, tuple[SourceSpan, ...]] = {}
        for locator, raw_entry in plain_index.items():
            record = catalog.resolve(locator)
            raw_entries: Sequence[Any]
            if STORE_SOURCE_KINDS[store_id] == "raw":
                if not isinstance(raw_entry, dict):
                    raise EvidenceValidationError("Raw source_index entries must be objects")
                raw_entries = (raw_entry,)
            else:
                if not isinstance(raw_entry, list) or not raw_entry:
                    raise EvidenceValidationError(
                        "Curated source_index entries must be nonempty arrays"
                    )
                raw_entries = raw_entry
            spans: list[SourceSpan] = []
            for entry in raw_entries:
                if not isinstance(entry, dict):
                    raise EvidenceValidationError("source_index occurrence must be an object")
                if STORE_SOURCE_KINDS[store_id] == "raw":
                    if set(entry) != _RAW_SOURCE_INDEX_KEYS:
                        raise EvidenceValidationError(
                            "Raw source_index occurrence has an unexpected schema"
                        )
                    line_start = _require_int(
                        entry.get("start_line"), "source_index start_line", minimum=1
                    )
                    line_end = _require_int(
                        entry.get("end_line"),
                        "source_index end_line",
                        minimum=line_start,
                    )
                    if entry.get("dia_id") != record.dia_id:
                        raise EvidenceValidationError(
                            f"Raw source_index dia_id drift for {locator}"
                        )
                    if (
                        entry.get("turn_index") != record.turn_index
                        or entry.get("global_turn_index") != record.global_turn_index
                        or entry.get("source_sha256") != record.source_sha256
                        or entry.get("raw_turn_sha256") != record.raw_turn_sha256
                    ):
                        raise EvidenceValidationError(
                            f"Raw source_index canonical metadata drift for {locator}"
                        )
                else:
                    if set(entry) != _CURATED_SOURCE_OCCURRENCE_KEYS:
                        raise EvidenceValidationError(
                            "Curated source_index occurrence has an unexpected schema"
                        )
                    line_start = _require_int(
                        entry.get("line"), "source_index line", minimum=1
                    )
                    line_end = line_start
                spans.append(
                    SourceSpan(
                        path=_canonical_relative_markdown_path(
                            entry.get("file"), "source_index file"
                        ),
                        line_start=line_start,
                        line_end=line_end,
                        locator=locator,
                        dia_id=record.dia_id,
                    )
                )
            # The S3 writer records one occurrence per inline locator *mention*.
            # A model-authored fact may repeat the same locator on one physical
            # line, so the manifest can legitimately contain identical entries.
            # Preserve ``plain_index`` above for the manifest identity hash, but
            # expose a stable semantic set of placements to attribution logic.
            semantic_spans = tuple(dict.fromkeys(spans))
            if STORE_SOURCE_KINDS[store_id] == "raw" and len(semantic_spans) != 1:
                raise EvidenceValidationError("Raw locators must have exactly one span")
            by_locator[locator] = tuple(
                sorted(
                    semantic_spans,
                    key=lambda span: (span.path, span.line_start, span.line_end),
                )
            )
        return cls(
            store_id=store_id,
            source_kind=STORE_SOURCE_KINDS[store_id],
            index_sha256=sha256_bytes(canonical_json_bytes(plain_index)),
            _by_locator=by_locator,
        )

    def occurrences(self, locator: str) -> tuple[SourceSpan, ...]:
        try:
            return self._by_locator[locator]
        except KeyError as exc:
            raise EvidenceValidationError(
                f"Locator is absent from the store source_index: {locator}"
            ) from exc

    def spans_for_path(self, relative_path: str) -> tuple[SourceSpan, ...]:
        canonical = _canonical_relative_markdown_path(
            relative_path, "attribution lookup path"
        )
        return tuple(
            sorted(
                (
                    span
                    for spans in self._by_locator.values()
                    for span in spans
                    if span.path == canonical
                ),
                key=lambda span: (span.line_start, span.line_end, span.locator),
            )
        )


_S1_FILE_KEYS = frozenset({
    "body_bytes",
    "body_sha256",
    "bytes",
    "caption_count",
    "first_dia_id",
    "first_locator",
    "last_dia_id",
    "last_locator",
    "session_date",
    "session_index",
    "sha256",
    "turn_count",
})
_S2_FILE_KEYS = _S1_FILE_KEYS | frozenset({"basename", "source_path"})
_S3_FILE_KEYS = frozenset({
    "bytes",
    "cross_references",
    "headings",
    "lines",
    "locator_mentions",
    "section_cross_references",
    "sha256",
    "unique_locators",
})
_S2_MARKER_KEYS = frozenset({
    "artifact_id",
    "committed_at",
    "content_sha256",
    "layout_sha256",
    "manifest_sha256",
    "path_map_sha256",
    "run_id",
    "schema_version",
    "trace_sha256",
})
_S3_MARKER_KEYS = frozenset({
    "schema_version",
    "artifact_id",
    "run_id",
    "committed_at",
    "store_tree_sha256",
    "trace_tree_sha256",
    "manifest_sha256",
    "stream_manifest_sha256",
    "prompt_contract_sha256",
    "runtime_contract_sha256",
})


def _json_object_from_bytes(payload: bytes, label: str) -> dict[str, Any]:
    try:
        value = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise EvidenceValidationError(f"Cannot parse {label}: {exc}") from exc
    if not isinstance(value, dict):
        raise EvidenceValidationError(f"{label} must contain one JSON object")
    return value


def _body_bytes(payload: bytes) -> bytes:
    boundary = b"---\n\n"
    if not payload.startswith(b"---\n") or boundary not in payload:
        raise EvidenceValidationError("Raw session is missing its frontmatter boundary")
    return payload.split(boundary, 1)[1]


def _canonical_relative_directory_path(value: Any, label: str) -> str:
    path_text = _require_nonempty(value, label)
    try:
        path_text.encode("utf-8", errors="strict")
    except UnicodeEncodeError as exc:
        raise EvidenceValidationError(f"{label} must be valid UTF-8 text") from exc
    if "\\" in path_text or any(
        ord(character) < 32 or ord(character) == 127 for character in path_text
    ):
        raise EvidenceValidationError(
            f"{label} must use safe POSIX path characters"
        )
    path = PurePosixPath(path_text)
    if (
        path.is_absolute()
        or not path.parts
        or any(part in {"", ".", ".."} for part in path.parts)
        or path.as_posix() != path_text
    ):
        raise EvidenceValidationError(f"{label} is not a canonical relative path")
    return path_text


def _linked_directory_tree_sha256(root: Path, label: str) -> str:
    raw = Path(root)
    if raw.is_symlink() or not raw.is_dir():
        raise EvidenceValidationError(f"{label} must be a non-symlink directory")
    resolved = raw.resolve()
    paths = list(raw.rglob("*"))
    if any(path.is_symlink() for path in paths):
        raise EvidenceValidationError(f"{label} contains a symlink")
    if any(not path.is_file() and not path.is_dir() for path in paths):
        raise EvidenceValidationError(f"{label} contains a non-regular entry")
    index = {
        path.resolve().relative_to(resolved).as_posix(): sha256_bytes(path.read_bytes())
        for path in paths
        if path.is_file()
    }
    if not index:
        raise EvidenceValidationError(f"{label} contains no files")
    return sha256_bytes(canonical_json_bytes(index))


@dataclass(frozen=True)
class VerifiedStoreManifest:
    """A manifest accepted only after external-hash and mounted-store checks.

    ``expected_manifest_sha256`` and, for published LLM-built stores, the
    ``expected_commit_marker_sha256`` must come from a frozen runtime contract.
    They must never be calculated from the candidate files by the caller.
    """

    store_id: str
    source_kind: str
    conversation_id: str
    source_map_sha256: str
    records_sha256: str
    artifact_id: str
    directory_name: str
    manifest_sha256: str
    commit_marker_sha256: str | None
    official_store_sha256: str
    verified_tree_sha256: str
    file_count: int
    total_bytes: int
    attribution_index: AttributionIndex
    _resolved_root: str
    _file_sha256_by_path: Mapping[str, str] = field(repr=False, compare=False)
    _directories: tuple[str, ...] = field(repr=False, compare=False)
    _verification_seal: InitVar[object]

    def __post_init__(self, _verification_seal: object) -> None:
        if _verification_seal is not _VERIFIED_MANIFEST_SEAL:
            raise EvidenceValidationError(
                "VerifiedStoreManifest must be produced by its loader"
            )
        if self.store_id not in STORE_SOURCE_KINDS:
            raise EvidenceValidationError("Verified manifest has an unknown store_id")
        if self.source_kind != STORE_SOURCE_KINDS[self.store_id]:
            raise EvidenceValidationError("Verified manifest store/source kind mismatch")
        _require_nonempty(self.conversation_id, "manifest conversation_id")
        _require_sha256(self.source_map_sha256, "manifest source_map_sha256")
        _require_sha256(self.records_sha256, "manifest records_sha256")
        _require_nonempty(self.artifact_id, "manifest artifact_id")
        _require_nonempty(self.directory_name, "manifest directory_name")
        _require_sha256(self.manifest_sha256, "manifest_sha256")
        if self.store_id == "s1":
            if self.commit_marker_sha256 is not None:
                raise EvidenceValidationError("S1 must not claim a commit marker")
        else:
            _require_sha256(
                self.commit_marker_sha256, "commit_marker_sha256"
            )
        _require_sha256(self.official_store_sha256, "official_store_sha256")
        _require_sha256(self.verified_tree_sha256, "verified_tree_sha256")
        _require_int(self.file_count, "manifest file_count", minimum=1)
        _require_int(self.total_bytes, "manifest total_bytes", minimum=1)
        if self.attribution_index.store_id != self.store_id:
            raise EvidenceValidationError("Manifest and attribution index stores differ")
        resolved_root = Path(self._resolved_root)
        if not resolved_root.is_absolute() or resolved_root.as_posix() != self._resolved_root:
            raise EvidenceValidationError("Verified manifest root is not canonical")
        if not isinstance(self._file_sha256_by_path, Mapping):
            raise EvidenceValidationError("Verified manifest file index is invalid")
        file_index: dict[str, str] = {}
        for relative, digest in self._file_sha256_by_path.items():
            canonical = _canonical_relative_markdown_path(
                relative, "verified manifest file path"
            )
            if canonical in file_index:
                raise EvidenceValidationError("Verified manifest repeats a file path")
            file_index[canonical] = _require_sha256(
                digest, "verified manifest file digest"
            )
        if len(file_index) != self.file_count:
            raise EvidenceValidationError("Verified manifest file index count differs")
        directories = _ordered_tuple(
            self._directories, "verified manifest directories"
        )
        canonical_directories = tuple(
            _canonical_relative_directory_path(value, "verified manifest directory")
            for value in directories
        )
        if len(canonical_directories) != len(set(canonical_directories)):
            raise EvidenceValidationError("Verified manifest repeats a directory")
        object.__setattr__(
            self, "_file_sha256_by_path", MappingProxyType(dict(sorted(file_index.items())))
        )
        object.__setattr__(self, "_directories", tuple(sorted(canonical_directories)))

    def assert_mounted_root(self, root: Path) -> None:
        """Reject copies and staging directories, even when their bytes are identical."""
        raw_root = Path(root)
        if raw_root.is_symlink() or not raw_root.is_dir():
            raise EvidenceValidationError(
                "Evidence store root must be a non-symlink directory"
            )
        if raw_root.resolve().as_posix() != self._resolved_root:
            raise EvidenceValidationError(
                "Mounted store root differs from the verified published root"
            )

    @property
    def file_paths(self) -> tuple[str, ...]:
        return tuple(self._file_sha256_by_path)

    @property
    def directory_paths(self) -> tuple[str, ...]:
        return self._directories

    def assert_file_payload(self, relative_path: str, payload: bytes) -> None:
        canonical = _canonical_relative_markdown_path(
            relative_path, "verified read path"
        )
        expected = self._file_sha256_by_path.get(canonical)
        if expected is None:
            raise EvidenceValidationError(
                "Read path is absent from the verified store manifest"
            )
        if not isinstance(payload, bytes):
            raise EvidenceValidationError("Verified file payload must be bytes")
        if sha256_bytes(payload) != expected:
            raise EvidenceValidationError(
                "Read payload differs from the verified store manifest"
            )

    @classmethod
    def load(
        cls,
        *,
        root: Path,
        store_id: str,
        catalog: SourceCatalog,
        manifest_path: Path,
        expected_manifest_sha256: str,
        commit_marker_path: Path | None = None,
        expected_commit_marker_sha256: str | None = None,
        path_map_path: Path | None = None,
        trace_path: Path | None = None,
    ) -> "VerifiedStoreManifest":
        if store_id not in STORE_SOURCE_KINDS:
            raise EvidenceValidationError(f"Unknown manifest store_id: {store_id}")
        expected_manifest_sha256 = _require_sha256(
            expected_manifest_sha256, "expected_manifest_sha256"
        )
        manifest_payload = _read_catalog_file(Path(manifest_path), "store manifest")
        manifest_sha256 = sha256_bytes(manifest_payload)
        if manifest_sha256 != expected_manifest_sha256:
            raise EvidenceValidationError("Store manifest does not match its frozen hash")
        manifest = _json_object_from_bytes(manifest_payload, "store manifest")
        if manifest.get("schema_version") != 1:
            raise EvidenceValidationError("Store manifest schema_version must be 1")
        expected_artifact = {
            "s1": f"locomo/{catalog.conversation_id}/s1-flat/v1",
            "s2": f"locomo/{catalog.conversation_id}/s2-foldered/v1",
            "s3": f"locomo/{catalog.conversation_id}/s3-curated/v1",
        }[store_id]
        if manifest.get("artifact_id") != expected_artifact:
            raise EvidenceValidationError("Store manifest artifact_id mismatch")

        raw_root = Path(root)
        resolved_root, directories, actual_files = _regular_store_paths(raw_root)
        store = manifest.get("store")
        files = manifest.get("files")
        counts = manifest.get("counts")
        source_index = manifest.get("source_index")
        if not all(isinstance(value, dict) for value in (store, files, counts, source_index)):
            raise EvidenceValidationError("Store manifest has an invalid core schema")
        if store.get("directory_name") != raw_root.name:
            raise EvidenceValidationError("Store directory name differs from manifest")

        actual_by_relative = {
            path.resolve().relative_to(resolved_root).as_posix(): path
            for path in actual_files
        }
        expected_file_keys = {
            _canonical_relative_markdown_path(path, "manifest file path")
            for path in files
        }
        if len(expected_file_keys) != len(files) or set(actual_by_relative) != expected_file_keys:
            raise EvidenceValidationError("Mounted store file set differs from manifest")
        required_file_keys = {
            "s1": _S1_FILE_KEYS,
            "s2": _S2_FILE_KEYS,
            "s3": _S3_FILE_KEYS,
        }[store_id]
        file_digests: dict[str, str] = {}
        total_bytes = 0
        for relative in sorted(actual_by_relative):
            metadata = files.get(relative)
            if not isinstance(metadata, dict) or set(metadata) != required_file_keys:
                raise EvidenceValidationError(
                    f"Manifest file metadata schema mismatch: {relative}"
                )
            payload = actual_by_relative[relative].read_bytes()
            try:
                payload.decode("utf-8")
            except UnicodeDecodeError as exc:
                raise EvidenceValidationError(
                    f"Store file is not valid UTF-8: {relative}"
                ) from exc
            digest = sha256_bytes(payload)
            if metadata.get("sha256") != digest or metadata.get("bytes") != len(payload):
                raise EvidenceValidationError(
                    f"Mounted store bytes differ from manifest: {relative}"
                )
            if store_id in {"s1", "s2"}:
                body = _body_bytes(payload)
                if (
                    metadata.get("body_sha256") != sha256_bytes(body)
                    or metadata.get("body_bytes") != len(body)
                ):
                    raise EvidenceValidationError(
                        f"Mounted raw-session body differs from manifest: {relative}"
                    )
            file_digests[relative] = digest
            total_bytes += len(payload)
        if counts.get("files") != len(actual_files) or counts.get("bytes") != total_bytes:
            raise EvidenceValidationError("Manifest counts differ from mounted store")

        actual_directories = [
            path.resolve().relative_to(resolved_root).as_posix()
            for path in directories
        ]
        if store_id == "s1":
            if actual_directories:
                raise EvidenceValidationError("S1 store must be flat")
        else:
            manifest_directories = manifest.get("directories")
            if not isinstance(manifest_directories, list):
                raise EvidenceValidationError("Foldered store lacks a directory table")
            canonical_directories = [
                _canonical_relative_directory_path(value, "manifest directory")
                for value in manifest_directories
            ]
            if (
                len(canonical_directories) != len(set(canonical_directories))
                or sorted(canonical_directories) != sorted(actual_directories)
            ):
                raise EvidenceValidationError(
                    "Mounted store directories differ from manifest"
                )

        layout_sha256 = sha256_bytes(canonical_json_bytes(file_digests))
        if store_id == "s1":
            official_store_sha256 = _require_sha256(
                store.get("sha256"), "S1 store.sha256"
            )
            if official_store_sha256 != layout_sha256:
                raise EvidenceValidationError("S1 official store hash is invalid")
            input_identity = manifest.get("input")
            if not isinstance(input_identity, dict) or (
                input_identity.get("canonical_sha256") != catalog.records_sha256
                or input_identity.get("source_map_sha256") != catalog.source_map_sha256
            ):
                raise EvidenceValidationError("S1 canonical input identity mismatch")
        elif store_id == "s2":
            official_store_sha256 = _require_sha256(
                store.get("layout_sha256"), "S2 store.layout_sha256"
            )
            if official_store_sha256 != layout_sha256:
                raise EvidenceValidationError("S2 official layout hash is invalid")
            basename_digests = {Path(path).name: digest for path, digest in file_digests.items()}
            if len(basename_digests) != len(file_digests):
                raise EvidenceValidationError("S2 repeats a session basename")
            content_sha256 = sha256_bytes(canonical_json_bytes(basename_digests))
            if store.get("content_sha256") != content_sha256:
                raise EvidenceValidationError("S2 content hash is invalid")
            source = manifest.get("source")
            if not isinstance(source, dict) or (
                source.get("canonical_sha256") != catalog.records_sha256
                or source.get("source_map_sha256") != catalog.source_map_sha256
            ):
                raise EvidenceValidationError("S2 canonical input identity mismatch")
        else:
            official_store_sha256 = _require_sha256(
                store.get("tree_sha256"), "S3 store.tree_sha256"
            )
            if official_store_sha256 != layout_sha256:
                raise EvidenceValidationError("S3 official store hash is invalid")
            build = manifest.get("build")
            verification = manifest.get("verification")
            if (
                not isinstance(build, dict)
                or build.get("mode") != "formal"
                or build.get("chunks_completed") != 85
                or not isinstance(verification, dict)
                or verification.get("all_85_chunks_completed_in_order") is not True
                or verification.get("formal_outputs_published_from_staging") is not True
            ):
                raise EvidenceValidationError("S3 manifest is not a complete formal build")

        if store_id == "s3":
            recomputed_source_index: dict[str, list[dict[str, Any]]] = {}
            for relative, path in sorted(actual_by_relative.items()):
                text = path.read_text(encoding="utf-8")
                for line_number, line in enumerate(text.splitlines(), start=1):
                    for token in _LOCATOR_CANDIDATE.findall(line):
                        if _LOCATOR.fullmatch(token) is None:
                            raise EvidenceValidationError(
                                f"Malformed source locator in curated store: {token}"
                            )
                        catalog.resolve(token)
                        recomputed_source_index.setdefault(token, []).append(
                            {"file": relative, "line": line_number}
                        )
            if _plain_json(source_index) != recomputed_source_index:
                raise EvidenceValidationError(
                    "S3 source_index is not the exact locator projection of the store"
                )

        attribution_index = AttributionIndex.from_source_index(
            store_id=store_id,
            source_index=source_index,
            catalog=catalog,
        )
        if store_id in {"s1", "s2"} and set(source_index) != catalog.locators:
            raise EvidenceValidationError(
                "Raw manifest source_index does not cover the canonical catalog"
            )
        validate_attribution_index_against_store(
            root=raw_root,
            attribution_index=attribution_index,
            catalog=catalog,
        )

        commit_marker_sha256: str | None = None
        if store_id == "s1":
            if any(
                value is not None
                for value in (
                    commit_marker_path,
                    expected_commit_marker_sha256,
                    path_map_path,
                    trace_path,
                )
            ):
                raise EvidenceValidationError("S1 has no linked publication artifacts")
        else:
            if commit_marker_path is None or expected_commit_marker_sha256 is None:
                raise EvidenceValidationError(
                    f"{store_id.upper()} requires a hash-pinned COMMITTED marker"
                )
            expected_marker_hash = _require_sha256(
                expected_commit_marker_sha256,
                "expected_commit_marker_sha256",
            )
            marker_payload = _read_catalog_file(
                Path(commit_marker_path), "store COMMITTED marker"
            )
            commit_marker_sha256 = sha256_bytes(marker_payload)
            if commit_marker_sha256 != expected_marker_hash:
                raise EvidenceValidationError(
                    "COMMITTED marker does not match its frozen hash"
                )
            marker = _json_object_from_bytes(marker_payload, "store COMMITTED marker")
            expected_marker_keys = _S2_MARKER_KEYS if store_id == "s2" else _S3_MARKER_KEYS
            if set(marker) != expected_marker_keys or marker.get("schema_version") != 1:
                raise EvidenceValidationError("COMMITTED marker schema mismatch")
            if (
                marker.get("artifact_id") != expected_artifact
                or marker.get("manifest_sha256") != manifest_sha256
            ):
                raise EvidenceValidationError("COMMITTED marker identity mismatch")
            if store_id == "s2":
                episode = manifest.get("episode")
                path_map = manifest.get("path_map")
                if not isinstance(episode, dict) or (
                    marker.get("run_id") != episode.get("run_id")
                    or marker.get("committed_at") != episode.get("finished_at")
                    or marker.get("content_sha256") != store.get("content_sha256")
                    or marker.get("layout_sha256") != store.get("layout_sha256")
                    or marker.get("trace_sha256") != episode.get("trace_sha256")
                ):
                    raise EvidenceValidationError("S2 COMMITTED marker linkage mismatch")
                if (
                    not isinstance(path_map, dict)
                    or set(path_map) != {"filename", "sha256"}
                    or marker.get("path_map_sha256") != path_map.get("sha256")
                ):
                    raise EvidenceValidationError("S2 path-map linkage mismatch")
                if path_map_path is None or trace_path is None:
                    raise EvidenceValidationError(
                        "S2 requires its published path-map and trace artifacts"
                    )
                path_map_payload = _read_catalog_file(
                    Path(path_map_path), "S2 path-map"
                )
                trace_payload = _read_catalog_file(Path(trace_path), "S2 trace")
                if (
                    Path(path_map_path).name != path_map.get("filename")
                    or sha256_bytes(path_map_payload) != path_map.get("sha256")
                    or Path(trace_path).name != episode.get("trace_filename")
                    or sha256_bytes(trace_payload) != episode.get("trace_sha256")
                ):
                    raise EvidenceValidationError(
                        "S2 linked publication artifact hash mismatch"
                    )
            else:
                build = manifest["build"]
                source = manifest.get("source")
                trace = manifest.get("trace")
                if not isinstance(source, dict) or not isinstance(trace, dict) or (
                    marker.get("run_id") != build.get("run_id")
                    or marker.get("committed_at") != build.get("finished_at")
                    or marker.get("store_tree_sha256") != store.get("tree_sha256")
                    or marker.get("trace_tree_sha256") != trace.get("tree_sha256")
                    or marker.get("stream_manifest_sha256")
                    != source.get("stream_manifest_sha256")
                    or marker.get("prompt_contract_sha256")
                    != source.get("prompt_contract_sha256")
                    or marker.get("runtime_contract_sha256")
                    != source.get("runtime_contract_sha256")
                ):
                    raise EvidenceValidationError("S3 COMMITTED marker linkage mismatch")
                if path_map_path is not None:
                    raise EvidenceValidationError("S3 has no path-map artifact")
                if trace_path is None:
                    raise EvidenceValidationError(
                        "S3 requires its published trace directory"
                    )
                if (
                    Path(trace_path).name != trace.get("directory_name")
                    or _linked_directory_tree_sha256(Path(trace_path), "S3 trace")
                    != trace.get("tree_sha256")
                ):
                    raise EvidenceValidationError("S3 trace artifact hash mismatch")

        return cls(
            store_id=store_id,
            source_kind=STORE_SOURCE_KINDS[store_id],
            conversation_id=catalog.conversation_id,
            source_map_sha256=catalog.source_map_sha256,
            records_sha256=catalog.records_sha256,
            artifact_id=expected_artifact,
            directory_name=raw_root.name,
            manifest_sha256=manifest_sha256,
            commit_marker_sha256=commit_marker_sha256,
            official_store_sha256=official_store_sha256,
            verified_tree_sha256=compute_store_tree_sha256(raw_root)[0],
            file_count=len(actual_files),
            total_bytes=total_bytes,
            attribution_index=attribution_index,
            _resolved_root=resolved_root.as_posix(),
            _file_sha256_by_path=file_digests,
            _directories=tuple(actual_directories),
            _verification_seal=_VERIFIED_MANIFEST_SEAL,
        )


def validate_attribution_index_against_store(
    *,
    root: Path,
    attribution_index: AttributionIndex,
    catalog: SourceCatalog,
) -> None:
    """Prove every manifest placement against the exact mounted store bytes."""
    cache: dict[str, list[str]] = {}
    for locator, spans in attribution_index._by_locator.items():
        record = catalog.resolve(locator)
        for span in spans:
            if span.dia_id != record.dia_id:
                raise EvidenceValidationError(
                    f"Attribution index dia_id drift for {locator}"
                )
            virtual_path = "/memories/" + span.path
            source_file = _resolve_virtual_file(root, virtual_path)
            if span.path not in cache:
                try:
                    cache[span.path] = source_file.read_text(encoding="utf-8").splitlines()
                except (OSError, UnicodeDecodeError) as exc:
                    raise EvidenceValidationError(
                        f"Cannot read attributed store file: {exc}"
                    ) from exc
            lines = cache[span.path]
            if span.line_end > len(lines):
                raise EvidenceValidationError(
                    f"Attribution span exceeds its file for {locator}"
                )
            if attribution_index.source_kind == "raw":
                match = _RAW_LOCATOR_LINE.fullmatch(lines[span.line_end - 1])
                if match is None or match.group(1) != locator or match.group(4) != record.dia_id:
                    raise EvidenceValidationError(
                        f"Raw source_index endpoint mismatch for {locator}"
                    )
                if not lines[span.line_start - 1].startswith(record.speaker + ":"):
                    raise EvidenceValidationError(
                        f"Raw source_index start mismatch for {locator}"
                    )
                rendered = "\n".join(lines[span.line_start - 1:span.line_end])
                if sha256_bytes(rendered.encode("utf-8")) != record.rendered_turn_sha256:
                    raise EvidenceValidationError(
                        f"Raw source bytes differ from canonical turn for {locator}"
                    )
            elif locator not in _stable_unique(
                match.group(0)
                for match in _LOCATOR.finditer(lines[span.line_start - 1])
            ):
                raise EvidenceValidationError(
                    f"Curated source_index line mismatch for {locator}"
                )


def _regular_store_paths(
    root: Path,
) -> tuple[Path, tuple[Path, ...], tuple[Path, ...]]:
    raw_root = Path(root)
    if raw_root.is_symlink() or not raw_root.is_dir():
        raise EvidenceValidationError("Evidence store root must be a non-symlink directory")
    resolved_root = raw_root.resolve()
    paths = tuple(
        sorted(raw_root.rglob("*"), key=lambda path: path.relative_to(raw_root).as_posix())
    )
    if any(path.is_symlink() for path in paths):
        raise EvidenceValidationError("Evidence store contains a symlink")
    if any(not path.is_dir() and not path.is_file() for path in paths):
        raise EvidenceValidationError("Evidence store contains a non-regular entry")
    directories = tuple(path for path in paths if path.is_dir())
    files = tuple(path for path in paths if path.is_file())
    if not files:
        raise EvidenceValidationError("Evidence store is empty")
    if any(path.suffix != ".md" for path in files):
        raise EvidenceValidationError("Evidence store may contain only Markdown files")
    return resolved_root, directories, files


def compute_store_tree_sha256(root: Path) -> tuple[str, int, int]:
    resolved_root, directories, files = _regular_store_paths(root)
    index: dict[str, Mapping[str, Any]] = {
        path.resolve().relative_to(resolved_root).as_posix() + "/": {
            "type": "directory"
        }
        for path in directories
    }
    total_bytes = 0
    for path in files:
        payload = path.read_bytes()
        try:
            payload.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise EvidenceValidationError(
                f"Evidence store file is not valid UTF-8: {path.name}"
            ) from exc
        relative = path.resolve().relative_to(resolved_root).as_posix()
        index[relative] = {
            "type": "file",
            "sha256": sha256_bytes(payload),
            "bytes": len(payload),
        }
        total_bytes += len(payload)
    return sha256_bytes(canonical_json_bytes(index)), len(files), total_bytes


def compute_official_store_sha256(root: Path) -> str:
    """Recompute the builders' path-to-file-digest store identity."""
    resolved_root, _, files = _regular_store_paths(root)
    index = {
        path.resolve().relative_to(resolved_root).as_posix(): sha256_bytes(
            path.read_bytes()
        )
        for path in files
    }
    return sha256_bytes(canonical_json_bytes(index))


@dataclass(frozen=True)
class StoreSnapshotRef:
    store_id: str
    source_kind: str
    conversation_id: str
    tree_sha256: str
    file_count: int
    total_bytes: int
    source_map_sha256: str
    records_sha256: str
    attribution_index_sha256: str
    manifest_sha256: str
    commit_marker_sha256: str | None
    official_store_sha256: str

    def __post_init__(self) -> None:
        if self.store_id not in STORE_SOURCE_KINDS:
            raise EvidenceValidationError(f"Unknown store_id: {self.store_id}")
        if self.source_kind != STORE_SOURCE_KINDS[self.store_id]:
            raise EvidenceValidationError("store_id and source_kind are inconsistent")
        _require_nonempty(self.conversation_id, "snapshot conversation_id")
        _require_sha256(self.tree_sha256, "snapshot tree_sha256")
        _require_int(self.file_count, "snapshot file_count", minimum=1)
        _require_int(self.total_bytes, "snapshot total_bytes", minimum=1)
        _require_sha256(self.source_map_sha256, "snapshot source_map_sha256")
        _require_sha256(self.records_sha256, "snapshot records_sha256")
        _require_sha256(
            self.attribution_index_sha256,
            "snapshot attribution_index_sha256",
        )
        _require_sha256(self.manifest_sha256, "snapshot manifest_sha256")
        if self.store_id == "s1":
            if self.commit_marker_sha256 is not None:
                raise EvidenceValidationError("S1 snapshot cannot claim a commit marker")
        else:
            _require_sha256(
                self.commit_marker_sha256, "snapshot commit_marker_sha256"
            )
        _require_sha256(
            self.official_store_sha256, "snapshot official_store_sha256"
        )

    @classmethod
    def capture(
        cls,
        *,
        root: Path,
        catalog: SourceCatalog,
        verified_manifest: VerifiedStoreManifest,
    ) -> "StoreSnapshotRef":
        store_id = verified_manifest.store_id
        attribution_index = verified_manifest.attribution_index
        verified_manifest.assert_mounted_root(root)
        if (
            catalog.conversation_id != verified_manifest.conversation_id
            or catalog.source_map_sha256 != verified_manifest.source_map_sha256
            or catalog.records_sha256 != verified_manifest.records_sha256
        ):
            raise EvidenceValidationError(
                "Catalog identity differs from the verified manifest"
            )
        tree_sha256, file_count, total_bytes = compute_store_tree_sha256(root)
        if (
            tree_sha256 != verified_manifest.verified_tree_sha256
            or file_count != verified_manifest.file_count
            or total_bytes != verified_manifest.total_bytes
        ):
            raise EvidenceValidationError(
                "Mounted store tree differs from the verified manifest"
            )
        if compute_official_store_sha256(root) != verified_manifest.official_store_sha256:
            raise EvidenceValidationError(
                "Mounted store bytes differ from the verified manifest"
            )
        validate_attribution_index_against_store(
            root=root,
            attribution_index=attribution_index,
            catalog=catalog,
        )
        return cls(
            store_id=store_id,
            source_kind=STORE_SOURCE_KINDS[store_id],
            conversation_id=catalog.conversation_id,
            tree_sha256=tree_sha256,
            file_count=file_count,
            total_bytes=total_bytes,
            source_map_sha256=catalog.source_map_sha256,
            records_sha256=catalog.records_sha256,
            attribution_index_sha256=attribution_index.index_sha256,
            manifest_sha256=verified_manifest.manifest_sha256,
            commit_marker_sha256=verified_manifest.commit_marker_sha256,
            official_store_sha256=verified_manifest.official_store_sha256,
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def validate_store_snapshot(
    snapshot: StoreSnapshotRef,
    *,
    root: Path,
    catalog: SourceCatalog,
    verified_manifest: VerifiedStoreManifest,
) -> None:
    attribution_index = verified_manifest.attribution_index
    verified_manifest.assert_mounted_root(root)
    if (
        catalog.conversation_id != verified_manifest.conversation_id
        or catalog.source_map_sha256 != verified_manifest.source_map_sha256
        or catalog.records_sha256 != verified_manifest.records_sha256
    ):
        raise EvidenceValidationError(
            "Catalog identity differs from the verified manifest"
        )
    if snapshot.conversation_id != catalog.conversation_id:
        raise EvidenceValidationError("Snapshot and catalog conversation differ")
    if snapshot.source_map_sha256 != catalog.source_map_sha256:
        raise EvidenceValidationError("Snapshot source_map identity differs from catalog")
    if snapshot.records_sha256 != catalog.records_sha256:
        raise EvidenceValidationError("Snapshot record identity differs from catalog")
    if (
        snapshot.store_id != attribution_index.store_id
        or snapshot.source_kind != attribution_index.source_kind
        or snapshot.attribution_index_sha256 != attribution_index.index_sha256
    ):
        raise EvidenceValidationError(
            "Snapshot identity differs from the store attribution index"
        )
    if (
        snapshot.manifest_sha256 != verified_manifest.manifest_sha256
        or snapshot.commit_marker_sha256
        != verified_manifest.commit_marker_sha256
        or snapshot.official_store_sha256
        != verified_manifest.official_store_sha256
        or snapshot.tree_sha256 != verified_manifest.verified_tree_sha256
    ):
        raise EvidenceValidationError(
            "Snapshot identity differs from the verified store manifest"
        )
    if (
        snapshot.file_count != verified_manifest.file_count
        or snapshot.total_bytes != verified_manifest.total_bytes
    ):
        raise EvidenceValidationError(
            "Snapshot counts differ from the verified store manifest"
        )
    validate_attribution_index_against_store(
        root=root,
        attribution_index=attribution_index,
        catalog=catalog,
    )
    tree_sha256, file_count, total_bytes = compute_store_tree_sha256(root)
    if (
        tree_sha256 != snapshot.tree_sha256
        or file_count != snapshot.file_count
        or total_bytes != snapshot.total_bytes
    ):
        raise EvidenceValidationError("Evidence store no longer matches its snapshot")
    if compute_official_store_sha256(root) != verified_manifest.official_store_sha256:
        raise EvidenceValidationError(
            "Evidence store no longer matches its verified manifest"
        )


@dataclass(frozen=True)
class AttributionUnit:
    line_start: int
    line_end: int
    kind: str
    source_locators: tuple[str, ...]
    dia_ids: tuple[str, ...]
    text_sha256: str

    def __post_init__(self) -> None:
        _require_int(self.line_start, "attribution line_start", minimum=1)
        _require_int(self.line_end, "attribution line_end", minimum=self.line_start)
        if self.kind not in {"raw_turn", "curated_fact"}:
            raise EvidenceValidationError("Unknown attribution unit kind")
        locators = _ordered_tuple(self.source_locators, "attribution source_locators")
        dia_ids = _ordered_tuple(self.dia_ids, "attribution dia_ids")
        if not locators or any(_LOCATOR.fullmatch(value) is None for value in locators):
            raise EvidenceValidationError("Attribution unit requires valid locators")
        if len(locators) != len(dia_ids):
            raise EvidenceValidationError("Attribution locators and dia_ids differ")
        pairs: list[tuple[str, str]] = []
        seen: dict[str, str] = {}
        for locator, dia_id in zip(locators, dia_ids):
            prior = seen.get(locator)
            if prior is not None and prior != dia_id:
                raise EvidenceValidationError(
                    "One attribution locator cannot map to multiple dia_ids"
                )
            if prior is None:
                seen[locator] = dia_id
                pairs.append((locator, dia_id))
        object.__setattr__(self, "source_locators", tuple(x[0] for x in pairs))
        object.__setattr__(self, "dia_ids", tuple(x[1] for x in pairs))
        _require_sha256(self.text_sha256, "attribution text_sha256")

    def to_dict(self) -> dict[str, Any]:
        return {
            "line_start": self.line_start,
            "line_end": self.line_end,
            "kind": self.kind,
            "source_locators": list(self.source_locators),
            "dia_ids": list(self.dia_ids),
            "text_sha256": self.text_sha256,
        }


@dataclass(frozen=True)
class EvidenceItem:
    schema_version: int
    evidence_id: str
    source_kind: str
    store_id: str
    store_snapshot_sha256: str
    source_map_sha256: str
    records_sha256: str
    attribution_index_sha256: str
    path: str
    section: str | None
    line_start: int
    line_end: int
    session_id: str | None
    group_id: str
    source_locators: tuple[str, ...]
    dia_ids: tuple[str, ...]
    timestamp: str | None
    speaker: str | None
    source_records: tuple[SourceRecordRef, ...]
    attribution_units: tuple[AttributionUnit, ...]
    text: str
    text_sha256: str
    retrieval_round: int
    query_terms: tuple[str, ...]
    rank: int | None
    score: float | None
    observation_ids: tuple[str, ...]
    selection_ordinal: int

    def __post_init__(self) -> None:
        if self.schema_version != EVIDENCE_SCHEMA_VERSION:
            raise EvidenceValidationError("EvidenceItem schema version mismatch")
        if not isinstance(self.evidence_id, str) or not self.evidence_id.startswith("ev-"):
            raise EvidenceValidationError("EvidenceItem evidence_id is invalid")
        _require_sha256(self.evidence_id[3:], "EvidenceItem evidence_id digest")
        if self.store_id not in STORE_SOURCE_KINDS:
            raise EvidenceValidationError("EvidenceItem has an unknown store_id")
        if self.source_kind != STORE_SOURCE_KINDS[self.store_id]:
            raise EvidenceValidationError("EvidenceItem store/source kind mismatch")
        for label, value in (
            ("store_snapshot_sha256", self.store_snapshot_sha256),
            ("source_map_sha256", self.source_map_sha256),
            ("records_sha256", self.records_sha256),
            ("attribution_index_sha256", self.attribution_index_sha256),
            ("text_sha256", self.text_sha256),
        ):
            _require_sha256(value, label)
        if not isinstance(self.path, str) or _VIRTUAL_PATH.fullmatch(self.path) is None:
            raise EvidenceValidationError("EvidenceItem path is invalid")
        _require_int(self.line_start, "EvidenceItem line_start", minimum=1)
        _require_int(
            self.line_end, "EvidenceItem line_end", minimum=self.line_start
        )
        for label, value in (
            ("section", self.section),
            ("session_id", self.session_id),
            ("timestamp", self.timestamp),
            ("speaker", self.speaker),
        ):
            if value is not None:
                _require_nonempty(value, f"EvidenceItem {label}")
        _require_nonempty(self.group_id, "EvidenceItem group_id")
        locators = _ordered_tuple(self.source_locators, "EvidenceItem source_locators")
        dia_ids = _ordered_tuple(self.dia_ids, "EvidenceItem dia_ids")
        records = _ordered_tuple(self.source_records, "EvidenceItem source_records")
        units = _ordered_tuple(self.attribution_units, "EvidenceItem attribution_units")
        query_terms = _ordered_tuple(self.query_terms, "EvidenceItem query_terms")
        observation_ids = _ordered_tuple(
            self.observation_ids, "EvidenceItem observation_ids"
        )
        if not locators or any(_LOCATOR.fullmatch(value) is None for value in locators):
            raise EvidenceValidationError("EvidenceItem requires valid source locators")
        if len(locators) != len(dia_ids) or len(records) != len(locators):
            raise EvidenceValidationError("EvidenceItem attribution arrays differ")
        if any(not isinstance(record, SourceRecordRef) for record in records):
            raise EvidenceValidationError("EvidenceItem source_records are invalid")
        if any(not isinstance(unit, AttributionUnit) for unit in units):
            raise EvidenceValidationError("EvidenceItem attribution_units are invalid")
        if tuple(record.locator for record in records) != locators:
            raise EvidenceValidationError("EvidenceItem records and locators differ")
        if tuple(record.dia_id for record in records) != dia_ids:
            raise EvidenceValidationError("EvidenceItem records and dia_ids differ")
        if not units:
            raise EvidenceValidationError("EvidenceItem requires attribution units")
        if not isinstance(self.text, str) or not self.text:
            raise EvidenceValidationError("EvidenceItem text must be nonempty")
        if sha256_bytes(self.text.encode("utf-8")) != self.text_sha256:
            raise EvidenceValidationError("EvidenceItem text hash is invalid")
        _require_int(self.retrieval_round, "EvidenceItem retrieval_round", minimum=1)
        if any(not isinstance(value, str) or not value.strip() for value in query_terms):
            raise EvidenceValidationError("EvidenceItem query terms are invalid")
        if self.rank is not None:
            _require_int(self.rank, "EvidenceItem rank", minimum=1)
        if self.score is not None and (
            isinstance(self.score, bool)
            or not isinstance(self.score, (int, float))
            or not math.isfinite(self.score)
        ):
            raise EvidenceValidationError("EvidenceItem score must be finite or null")
        if self.score is not None:
            normalized_score = float(self.score)
            object.__setattr__(
                self, "score", 0.0 if normalized_score == 0.0 else normalized_score
            )
        if not observation_ids or any(
            not isinstance(value, str) or _OBSERVATION_ID.fullmatch(value) is None
            for value in observation_ids
        ):
            raise EvidenceValidationError("EvidenceItem observation_ids are invalid")
        _require_int(
            self.selection_ordinal, "EvidenceItem selection_ordinal", minimum=1
        )
        object.__setattr__(self, "source_locators", locators)
        object.__setattr__(self, "dia_ids", dia_ids)
        object.__setattr__(self, "source_records", records)
        object.__setattr__(self, "attribution_units", units)
        object.__setattr__(self, "query_terms", query_terms)
        object.__setattr__(self, "observation_ids", observation_ids)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "evidence_id": self.evidence_id,
            "source_kind": self.source_kind,
            "store_id": self.store_id,
            "store_snapshot_sha256": self.store_snapshot_sha256,
            "source_map_sha256": self.source_map_sha256,
            "records_sha256": self.records_sha256,
            "attribution_index_sha256": self.attribution_index_sha256,
            "path": self.path,
            "section": self.section,
            "line_start": self.line_start,
            "line_end": self.line_end,
            "session_id": self.session_id,
            "group_id": self.group_id,
            "source_locators": list(self.source_locators),
            "dia_ids": list(self.dia_ids),
            "timestamp": self.timestamp,
            "speaker": self.speaker,
            "source_records": [record.to_dict() for record in self.source_records],
            "attribution_units": [unit.to_dict() for unit in self.attribution_units],
            "text": self.text,
            "text_sha256": self.text_sha256,
            "retrieval_round": self.retrieval_round,
            "query_terms": list(self.query_terms),
            "rank": self.rank,
            "score": self.score,
            "observation_ids": list(self.observation_ids),
            "selection_ordinal": self.selection_ordinal,
        }


def _resolve_virtual_file(root: Path, virtual_path: str) -> Path:
    if not isinstance(virtual_path, str) or _VIRTUAL_PATH.fullmatch(virtual_path) is None:
        raise EvidenceValidationError("Evidence path must be a .md file under /memories")
    relative = Path(virtual_path[len("/memories/"):])
    if (
        relative.is_absolute()
        or not relative.parts
        or any(part in {"", ".", ".."} for part in relative.parts)
    ):
        raise EvidenceValidationError("Evidence path contains an unsafe component")
    canonical_path = "/memories/" + relative.as_posix()
    if virtual_path != canonical_path:
        raise EvidenceValidationError("Evidence path must use canonical POSIX spelling")
    raw_root = Path(root)
    if raw_root.is_symlink() or not raw_root.is_dir():
        raise EvidenceValidationError("Evidence store root must be a non-symlink directory")
    current = raw_root
    for part in relative.parts:
        current = current / part
        if current.is_symlink():
            raise EvidenceValidationError("Evidence path contains a symlink component")
    if not current.is_file():
        raise EvidenceValidationError("Evidence path is not an existing regular file")
    resolved_root = raw_root.resolve()
    resolved = current.resolve()
    if resolved_root not in resolved.parents:
        raise EvidenceValidationError("Evidence path escapes the store")
    return current


def _frontmatter_end(lines: Sequence[str]) -> int:
    if not lines or lines[0] != "---":
        raise EvidenceValidationError("Evidence file lacks YAML frontmatter")
    try:
        return lines.index("---", 1) + 1
    except ValueError as exc:
        raise EvidenceValidationError("Evidence file has incomplete frontmatter") from exc


def _section_for_range(
    lines: Sequence[str], line_start: int, line_end: int
) -> tuple[str | None, str | None]:
    headings: list[tuple[int, int, str]] = []
    for line_number, line in enumerate(lines, start=1):
        match = _HEADING.fullmatch(line)
        if match:
            headings.append((line_number, len(match.group(1)), line.strip()))
    if any(line_start < number <= line_end for number, _, _ in headings):
        raise EvidenceValidationError("Evidence selection crosses a Markdown section boundary")
    stack: list[str] = []
    for number, level, label in headings:
        if number > line_start:
            break
        stack = stack[: level - 1]
        stack.append(label)
    if not stack:
        return None, None
    return " > ".join(stack), stack[0]


def _attribution_unit(
    *,
    lines: Sequence[str],
    line_start: int,
    line_end: int,
    kind: str,
    locators: Sequence[str],
    catalog: SourceCatalog,
) -> AttributionUnit:
    records = catalog.resolve_many(locators)
    text = "\n".join(lines[line_start - 1:line_end])
    return AttributionUnit(
        line_start=line_start,
        line_end=line_end,
        kind=kind,
        source_locators=tuple(locators),
        dia_ids=tuple(record.dia_id for record in records),
        text_sha256=sha256_bytes(text.encode("utf-8")),
    )


def _raw_attribution_units(
    *,
    lines: Sequence[str],
    frontmatter_end: int,
    line_start: int,
    line_end: int,
    path: str,
    catalog: SourceCatalog,
    attribution_index: AttributionIndex,
) -> tuple[AttributionUnit, ...]:
    conversation_lines = [
        number
        for number, line in enumerate(lines, start=1)
        if line == f"Conversation: {catalog.conversation_id}"
    ]
    if len(conversation_lines) != 1 or conversation_lines[0] <= frontmatter_end:
        raise EvidenceValidationError("Raw session has an invalid Conversation header")
    cursor = conversation_lines[0] + 1
    relative_path = path[len("/memories/"):]
    indexed_spans = attribution_index.spans_for_path(relative_path)
    if not indexed_spans:
        raise EvidenceValidationError("Raw file is absent from the store source_index")
    blocks: list[AttributionUnit] = []
    for number, line in enumerate(lines, start=1):
        match = _RAW_LOCATOR_LINE.fullmatch(line)
        if match is None:
            continue
        locator, session_text, turn_text, dia_id = (
            match.group(1), match.group(2), match.group(3), match.group(4)
        )
        record = catalog.resolve(locator)
        if record.dia_id != dia_id:
            raise EvidenceValidationError("Raw locator line has the wrong dia_id")
        if int(session_text) != record.session_index or int(turn_text) != record.turn_index:
            raise EvidenceValidationError("Raw locator line has inconsistent coordinates")
        while cursor <= number and not lines[cursor - 1].strip():
            cursor += 1
        if cursor >= number:
            raise EvidenceValidationError("Raw turn block has no source text")
        if not lines[cursor - 1].startswith(record.speaker + ":"):
            raise EvidenceValidationError("Raw turn block speaker differs from source_map")
        expected_span = SourceSpan(
            path=relative_path,
            line_start=cursor,
            line_end=number,
            locator=locator,
            dia_id=record.dia_id,
        )
        if expected_span not in attribution_index.occurrences(locator):
            raise EvidenceValidationError(
                "Raw turn placement differs from the store source_index"
            )
        blocks.append(
            _attribution_unit(
                lines=lines,
                line_start=cursor,
                line_end=number,
                kind="raw_turn",
                locators=(locator,),
                catalog=catalog,
            )
        )
        cursor = number + 1
    if not blocks:
        raise EvidenceValidationError("Raw session contains no complete source-turn blocks")
    if tuple(
        (unit.line_start, unit.line_end, unit.source_locators[0]) for unit in blocks
    ) != tuple(
        (span.line_start, span.line_end, span.locator) for span in indexed_spans
    ):
        raise EvidenceValidationError("Raw file blocks differ from the source_index")
    while cursor <= len(lines) and not lines[cursor - 1].strip():
        cursor += 1
    if cursor <= len(lines):
        raise EvidenceValidationError("Raw session has unattributed trailing content")
    selected = [
        unit
        for unit in blocks
        if unit.line_start >= line_start and unit.line_end <= line_end
    ]
    if not selected or selected[0].line_start != line_start or selected[-1].line_end != line_end:
        raise EvidenceValidationError(
            "Raw evidence must select one or more complete source-turn blocks"
        )
    first_index = blocks.index(selected[0])
    if tuple(blocks[first_index:first_index + len(selected)]) != tuple(selected):
        raise EvidenceValidationError("Raw evidence blocks must be contiguous")
    records = catalog.resolve_many(
        tuple(unit.source_locators[0] for unit in selected)
    )
    if len({record.session_id for record in records}) != 1:
        raise EvidenceValidationError("Raw evidence cannot span sessions")
    session_index = records[0].session_index
    if Path(path).name != f"session-{session_index:02d}.md":
        raise EvidenceValidationError("Raw session filename and locator disagree")
    return tuple(selected)


def _curated_attribution_units(
    *,
    lines: Sequence[str],
    line_start: int,
    line_end: int,
    catalog: SourceCatalog,
    attribution_index: AttributionIndex,
    path: str,
) -> tuple[AttributionUnit, ...]:
    if not lines[line_start - 1].strip() or not lines[line_end - 1].strip():
        raise EvidenceValidationError("Curated evidence cannot start or end with a blank line")
    units: list[AttributionUnit] = []
    for number in range(line_start, line_end + 1):
        line = lines[number - 1]
        if not line.strip():
            continue
        if _HEADING.fullmatch(line):
            raise EvidenceValidationError(
                "Curated headings are routing metadata, not evidence"
            )
        candidates = _LOCATOR_CANDIDATE.findall(line)
        if any(_LOCATOR.fullmatch(value) is None for value in candidates):
            raise EvidenceValidationError("Curated fact contains a malformed locator")
        locators = _stable_unique(match.group(0) for match in _LOCATOR.finditer(line))
        if not locators:
            raise EvidenceValidationError(
                "Every selected curated fact line must carry a source locator"
            )
        content_without_locators = _LOCATOR.sub("", line).strip(" -|\t")
        if not content_without_locators:
            raise EvidenceValidationError("Curated evidence line contains no factual text")
        relative_path = path[len("/memories/"):]
        for locator in locators:
            expected_span = SourceSpan(
                path=relative_path,
                line_start=number,
                line_end=number,
                locator=locator,
                dia_id=catalog.resolve(locator).dia_id,
            )
            if expected_span not in attribution_index.occurrences(locator):
                raise EvidenceValidationError(
                    "Curated locator placement differs from the store source_index"
                )
        units.append(
            _attribution_unit(
                lines=lines,
                line_start=number,
                line_end=number,
                kind="curated_fact",
                locators=locators,
                catalog=catalog,
            )
        )
    if not units:
        raise EvidenceValidationError("Curated evidence contains no attributed fact line")
    return tuple(units)


def build_evidence_item(
    *,
    root: Path,
    catalog: SourceCatalog,
    verified_manifest: VerifiedStoreManifest,
    snapshot: StoreSnapshotRef,
    path: str,
    line_start: int,
    line_end: int,
    retrieval_round: int,
    observation_ids: Sequence[str],
    selection_ordinal: int,
    query_terms: Sequence[str] = (),
    rank: int | None = None,
    score: float | None = None,
) -> EvidenceItem:
    """Re-read and attribute an exact EvidenceItem from a frozen store."""
    ordered_observation_ids = _ordered_tuple(observation_ids, "observation_ids")
    ordered_query_terms = _ordered_tuple(query_terms, "query_terms")
    validate_store_snapshot(
        snapshot,
        root=root,
        catalog=catalog,
        verified_manifest=verified_manifest,
    )
    attribution_index = verified_manifest.attribution_index
    for label, value in (
        ("line_start", line_start),
        ("line_end", line_end),
        ("retrieval_round", retrieval_round),
        ("selection_ordinal", selection_ordinal),
    ):
        _require_int(value, label, minimum=1)
    if line_end < line_start:
        raise EvidenceValidationError("line_end must be at least line_start")
    frozen_observation_ids = _stable_unique(
        _require_nonempty(value, "observation_id") for value in ordered_observation_ids
    )
    if not frozen_observation_ids or any(
        _OBSERVATION_ID.fullmatch(value) is None for value in frozen_observation_ids
    ):
        raise EvidenceValidationError("Evidence requires valid observation_ids")
    frozen_query_terms = _stable_unique(
        _require_nonempty(value, "query term") for value in ordered_query_terms
    )
    if rank is not None:
        _require_int(rank, "rank", minimum=1)
    if score is not None and (
        isinstance(score, bool)
        or not isinstance(score, (int, float))
        or not math.isfinite(score)
    ):
        raise EvidenceValidationError("score must be a finite JSON number or null")
    frozen_score = float(score) if score is not None else None
    source_file = _resolve_virtual_file(root, path)
    try:
        lines = source_file.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError) as exc:
        raise EvidenceValidationError(f"Cannot read evidence source: {exc}") from exc
    if line_end > len(lines):
        raise EvidenceValidationError("Evidence line range exceeds the source file")
    frontmatter_end = _frontmatter_end(lines)
    if line_start <= frontmatter_end:
        raise EvidenceValidationError("Frontmatter cannot be selected as evidence")
    section, top_level_section = _section_for_range(lines, line_start, line_end)
    if snapshot.source_kind == "raw":
        units = _raw_attribution_units(
            lines=lines,
            frontmatter_end=frontmatter_end,
            line_start=line_start,
            line_end=line_end,
            path=path,
            catalog=catalog,
            attribution_index=attribution_index,
        )
    else:
        units = _curated_attribution_units(
            lines=lines,
            line_start=line_start,
            line_end=line_end,
            catalog=catalog,
            attribution_index=attribution_index,
            path=path,
        )
    source_locators = _stable_unique(
        locator for unit in units for locator in unit.source_locators
    )
    source_records = catalog.resolve_many(source_locators)
    text = "\n".join(lines[line_start - 1:line_end])
    dia_ids = tuple(record.dia_id for record in source_records)
    session_ids = _stable_unique(record.session_id for record in source_records)
    timestamps = _stable_unique(record.session_datetime for record in source_records)
    speakers = _stable_unique(record.speaker for record in source_records)
    session_id = session_ids[0] if len(session_ids) == 1 else None
    timestamp = timestamps[0] if len(timestamps) == 1 else None
    speaker = speakers[0] if len(speakers) == 1 else None
    if snapshot.source_kind == "raw":
        if session_id is None:
            raise EvidenceValidationError("Raw evidence must resolve to one session")
        group_id = session_id
    else:
        group_id = path + (f" > {top_level_section}" if top_level_section else "")
    text_sha256 = sha256_bytes(text.encode("utf-8"))
    identity = {
        "schema_version": EVIDENCE_SCHEMA_VERSION,
        "store_id": snapshot.store_id,
        "store_snapshot_sha256": snapshot.tree_sha256,
        "source_map_sha256": catalog.source_map_sha256,
        "records_sha256": catalog.records_sha256,
        "attribution_index_sha256": attribution_index.index_sha256,
        "path": path,
        "line_start": line_start,
        "line_end": line_end,
        "text_sha256": text_sha256,
        "attribution_units": [unit.to_dict() for unit in units],
    }
    evidence_id = "ev-" + sha256_bytes(canonical_json_bytes(identity))
    item = EvidenceItem(
        schema_version=EVIDENCE_SCHEMA_VERSION,
        evidence_id=evidence_id,
        source_kind=snapshot.source_kind,
        store_id=snapshot.store_id,
        store_snapshot_sha256=snapshot.tree_sha256,
        source_map_sha256=catalog.source_map_sha256,
        records_sha256=catalog.records_sha256,
        attribution_index_sha256=attribution_index.index_sha256,
        path=path,
        section=section,
        line_start=line_start,
        line_end=line_end,
        session_id=session_id,
        group_id=group_id,
        source_locators=source_locators,
        dia_ids=dia_ids,
        timestamp=timestamp,
        speaker=speaker,
        source_records=source_records,
        attribution_units=units,
        text=text,
        text_sha256=text_sha256,
        retrieval_round=retrieval_round,
        query_terms=frozen_query_terms,
        rank=rank,
        score=frozen_score,
        observation_ids=frozen_observation_ids,
        selection_ordinal=selection_ordinal,
    )
    # Close the read window: a mutation between the first snapshot check and the
    # exact line read invalidates the item instead of producing a mixed snapshot.
    validate_store_snapshot(
        snapshot,
        root=root,
        catalog=catalog,
        verified_manifest=verified_manifest,
    )
    return item


def validate_evidence_item(
    item: EvidenceItem,
    *,
    root: Path,
    catalog: SourceCatalog,
    verified_manifest: VerifiedStoreManifest,
    snapshot: StoreSnapshotRef,
) -> None:
    rebuilt = build_evidence_item(
        root=root,
        catalog=catalog,
        verified_manifest=verified_manifest,
        snapshot=snapshot,
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
    if rebuilt != item:
        raise EvidenceValidationError("EvidenceItem does not match its frozen source")


@dataclass(frozen=True)
class GlobalFallbackProof:
    root_survey_observation_id: str
    whole_tree_grep_observation_id: str

    def __post_init__(self) -> None:
        for value in (
            self.root_survey_observation_id,
            self.whole_tree_grep_observation_id,
        ):
            if not isinstance(value, str) or _OBSERVATION_ID.fullmatch(value) is None:
                raise EvidenceValidationError("Fallback proof requires observation IDs")
        if self.root_survey_observation_id == self.whole_tree_grep_observation_id:
            raise EvidenceValidationError("Fallback proof observations must be distinct")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class StopRecord:
    reason: str
    hit_cap: bool
    missing_aspects: tuple[str, ...]
    rounds_without_new_evidence: int
    fallback_proof: GlobalFallbackProof | None

    def __post_init__(self) -> None:
        if self.reason not in STOP_REASONS:
            raise EvidenceValidationError(f"Unknown stop reason: {self.reason}")
        if not isinstance(self.hit_cap, bool):
            raise EvidenceValidationError("hit_cap must be bool")
        _require_int(
            self.rounds_without_new_evidence,
            "rounds_without_new_evidence",
            minimum=0,
        )
        ordered_missing = _ordered_tuple(self.missing_aspects, "missing_aspects")
        missing = tuple(
            _require_nonempty(value, "missing aspect") for value in ordered_missing
        )
        object.__setattr__(self, "missing_aspects", missing)
        if self.fallback_proof is not None and not isinstance(
            self.fallback_proof, GlobalFallbackProof
        ):
            raise EvidenceValidationError(
                "fallback_proof must be a GlobalFallbackProof or null"
            )
        if self.reason in {
            "not_found_after_global_fallback",
            "no_progress_after_global_fallback",
        } and self.fallback_proof is None:
            raise EvidenceValidationError("Fallback stop requires global fallback proof")
        if (
            self.reason == "no_progress_after_global_fallback"
            and self.rounds_without_new_evidence < 2
        ):
            raise EvidenceValidationError(
                "No-progress stop requires at least two rounds without new evidence"
            )

    @property
    def global_fallback_done(self) -> bool:
        return self.fallback_proof is not None

    def to_dict(self) -> dict[str, Any]:
        return {
            "reason": self.reason,
            "hit_cap": self.hit_cap,
            "missing_aspects": list(self.missing_aspects),
            "rounds_without_new_evidence": self.rounds_without_new_evidence,
            "global_fallback_done": self.global_fallback_done,
            "fallback_proof": (
                self.fallback_proof.to_dict() if self.fallback_proof else None
            ),
        }


@dataclass(frozen=True)
class TokenizerRef:
    tokenizer_id: str
    version: str
    artifact_sha256: str

    def __post_init__(self) -> None:
        _require_nonempty(self.tokenizer_id, "tokenizer_id")
        _require_nonempty(self.version, "tokenizer version")
        _require_sha256(self.artifact_sha256, "tokenizer artifact_sha256")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class BudgetRecord:
    unit: str
    tokenizer: TokenizerRef | None
    limit: int
    used: int
    skipped_items: int
    truncated: bool

    def __post_init__(self) -> None:
        if self.unit not in {"bytes", "characters", "tokens"}:
            raise EvidenceValidationError("Unknown evidence budget unit")
        if self.unit == "tokens":
            raise EvidenceValidationError(
                "Token evidence budgets are disabled until a deterministic counter is frozen"
            )
        if self.unit != "tokens" and self.tokenizer is not None:
            raise EvidenceValidationError("Non-token budgets cannot claim a tokenizer")
        _require_int(self.limit, "budget limit", minimum=0)
        _require_int(self.used, "budget used", minimum=0)
        _require_int(self.skipped_items, "budget skipped_items", minimum=0)
        if self.used > self.limit:
            raise EvidenceValidationError("Evidence budget used exceeds its limit")
        if self.truncated is not False:
            raise EvidenceValidationError("Evidence items must never be truncated")

    def to_dict(self) -> dict[str, Any]:
        return {
            "unit": self.unit,
            "tokenizer": self.tokenizer.to_dict() if self.tokenizer else None,
            "limit": self.limit,
            "used": self.used,
            "skipped_items": self.skipped_items,
            "truncated": self.truncated,
        }


def _validate_exact_keys(
    value: Mapping[str, Any], expected: frozenset[str], label: str
) -> None:
    if set(value) != expected:
        raise EvidenceValidationError(f"{label} keys must be exactly {sorted(expected)}")


def _validate_bundle_mappings(
    *,
    condition: Mapping[str, Any],
    prompt_contract: Mapping[str, Any],
    runtime_contract: Mapping[str, Any],
    metrics: Mapping[str, Any],
    model: Mapping[str, Any],
    integrity: Mapping[str, Any],
    snapshot: StoreSnapshotRef,
) -> None:
    _validate_exact_keys(condition, CONDITION_KEYS, "condition")
    if condition["store_id"] != snapshot.store_id:
        raise EvidenceValidationError("Condition store_id differs from snapshot")
    if condition["retrieval_id"] not in RETRIEVAL_IDS:
        raise EvidenceValidationError("Condition retrieval_id is not registered")
    _require_nonempty(condition["condition_id"], "condition_id")
    _validate_exact_keys(prompt_contract, PROMPT_CONTRACT_KEYS, "prompt_contract")
    _require_nonempty(prompt_contract["paper_prompt_id"], "paper_prompt_id")
    for key in PROMPT_CONTRACT_KEYS - {"paper_prompt_id"}:
        _require_sha256(prompt_contract[key], key)
    _validate_exact_keys(runtime_contract, RUNTIME_CONTRACT_KEYS, "runtime_contract")
    _require_sha256(runtime_contract["runtime_sha256"], "runtime_sha256")
    _require_int(runtime_contract["round_limit"], "round_limit", minimum=1)
    if runtime_contract["evidence_budget_unit"] not in {"bytes", "characters"}:
        raise EvidenceValidationError("Runtime evidence budget unit is invalid")
    _require_int(
        runtime_contract["evidence_budget_limit"],
        "evidence_budget_limit",
        minimum=0,
    )
    _validate_exact_keys(metrics, METRIC_KEYS, "metrics")
    for key in (
        "provider_rounds",
        "model_calls",
        "provider_request_attempts",
        "filesystem_tool_calls",
        "orchestration_calls",
    ):
        _require_int(metrics[key], key, minimum=0)
    if metrics["model_calls"] < metrics["provider_rounds"]:
        raise EvidenceValidationError("model_calls cannot be below provider_rounds")
    if metrics["provider_request_attempts"] < metrics["model_calls"]:
        raise EvidenceValidationError("request attempts cannot be below model_calls")
    if not isinstance(metrics["token_usage_available"], bool):
        raise EvidenceValidationError("token_usage_available must be bool")
    token_values = (
        metrics["prompt_tokens"],
        metrics["completion_tokens"],
        metrics["total_tokens"],
    )
    if metrics["token_usage_available"]:
        for key, value in zip(
            ("prompt_tokens", "completion_tokens", "total_tokens"), token_values
        ):
            _require_int(value, key, minimum=0)
        if metrics["total_tokens"] != (
            metrics["prompt_tokens"] + metrics["completion_tokens"]
        ):
            raise EvidenceValidationError("Token usage totals are inconsistent")
    elif any(value is not None for value in token_values):
        raise EvidenceValidationError("Unavailable token usage must use null counts")
    _validate_exact_keys(model, MODEL_KEYS, "model")
    _require_nonempty(model["requested_model"], "requested_model")
    served_models = model["served_models"]
    if not isinstance(served_models, (tuple, list)) or any(
        not isinstance(value, str) or not value.strip() for value in served_models
    ):
        raise EvidenceValidationError("served_models must be a string array")
    if metrics["model_calls"] > 0 and not served_models:
        raise EvidenceValidationError("Model calls require at least one served model")
    _validate_exact_keys(integrity, INTEGRITY_KEYS, "integrity")
    if not all(
        isinstance(integrity[key], bool) for key in ("store_unchanged", "verified")
    ):
        raise EvidenceValidationError("Integrity flags must be bool")
    for key in ("pre_tree_sha256", "post_tree_sha256"):
        _require_sha256(integrity[key], key)
    if integrity["pre_tree_sha256"] != snapshot.tree_sha256:
        raise EvidenceValidationError("Integrity pre-hash differs from snapshot")
    if integrity["store_unchanged"]:
        if integrity["post_tree_sha256"] != snapshot.tree_sha256:
            raise EvidenceValidationError("Unchanged store post-hash differs from snapshot")
    elif integrity["post_tree_sha256"] == snapshot.tree_sha256:
        raise EvidenceValidationError("Changed store must report a different post-hash")


@dataclass(frozen=True)
class EvidenceBundle:
    schema_version: int
    protocol_version: str
    bundle_id: str
    status: str
    question: QuestionInput
    question_sha256: str
    condition: Mapping[str, Any]
    store_snapshot: StoreSnapshotRef
    prompt_contract: Mapping[str, Any]
    runtime_contract: Mapping[str, Any]
    search_actions: tuple[Mapping[str, Any], ...]
    evidence_items: tuple[EvidenceItem, ...]
    stop: StopRecord
    budget: BudgetRecord
    metrics: Mapping[str, Any]
    model: Mapping[str, Any]
    integrity: Mapping[str, Any]
    errors: tuple[Mapping[str, Any], ...]

    def __post_init__(self) -> None:
        if not isinstance(self.question, QuestionInput):
            raise EvidenceValidationError("EvidenceBundle question type is invalid")
        if not isinstance(self.store_snapshot, StoreSnapshotRef):
            raise EvidenceValidationError("EvidenceBundle snapshot type is invalid")
        if not isinstance(self.stop, StopRecord):
            raise EvidenceValidationError("EvidenceBundle stop type is invalid")
        if not isinstance(self.budget, BudgetRecord):
            raise EvidenceValidationError("EvidenceBundle budget type is invalid")
        items = _ordered_tuple(self.evidence_items, "EvidenceBundle evidence_items")
        if any(not isinstance(item, EvidenceItem) for item in items):
            raise EvidenceValidationError("EvidenceBundle evidence item type is invalid")
        object.__setattr__(self, "condition", _freeze_mapping(self.condition, "condition"))
        object.__setattr__(
            self,
            "prompt_contract",
            _freeze_mapping(self.prompt_contract, "prompt_contract"),
        )
        object.__setattr__(
            self,
            "runtime_contract",
            _freeze_mapping(self.runtime_contract, "runtime_contract"),
        )
        object.__setattr__(
            self,
            "search_actions",
            tuple(
                _freeze_mapping(value, "search action")
                for value in _ordered_tuple(
                    self.search_actions, "EvidenceBundle search_actions"
                )
            ),
        )
        object.__setattr__(self, "evidence_items", items)
        object.__setattr__(self, "metrics", _freeze_mapping(self.metrics, "metrics"))
        object.__setattr__(self, "model", _freeze_mapping(self.model, "model"))
        object.__setattr__(
            self, "integrity", _freeze_mapping(self.integrity, "integrity")
        )
        object.__setattr__(
            self,
            "errors",
            tuple(
                _freeze_mapping(value, "error")
                for value in _ordered_tuple(self.errors, "EvidenceBundle errors")
            ),
        )

    def _body(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "protocol_version": self.protocol_version,
            "status": self.status,
            "question": self.question.to_dict(),
            "question_sha256": self.question_sha256,
            "condition": _plain_json(self.condition),
            "store_snapshot": self.store_snapshot.to_dict(),
            "prompt_contract": _plain_json(self.prompt_contract),
            "runtime_contract": _plain_json(self.runtime_contract),
            "search_actions": [_plain_json(value) for value in self.search_actions],
            "evidence_items": [item.to_dict() for item in self.evidence_items],
            "stop": self.stop.to_dict(),
            "budget": self.budget.to_dict(),
            "metrics": _plain_json(self.metrics),
            "model": _plain_json(self.model),
            "integrity": _plain_json(self.integrity),
            "errors": [_plain_json(value) for value in self.errors],
        }

    def to_dict(self) -> dict[str, Any]:
        return {"bundle_id": self.bundle_id, **self._body()}

    @classmethod
    def create(
        cls,
        *,
        status: str,
        question: QuestionInput,
        condition: Mapping[str, Any],
        store_snapshot: StoreSnapshotRef,
        prompt_contract: Mapping[str, Any],
        runtime_contract: Mapping[str, Any],
        search_actions: Sequence[Mapping[str, Any]],
        evidence_items: Sequence[EvidenceItem],
        stop: StopRecord,
        budget: BudgetRecord,
        metrics: Mapping[str, Any],
        model: Mapping[str, Any],
        integrity: Mapping[str, Any],
        errors: Sequence[Mapping[str, Any]] = (),
    ) -> "EvidenceBundle":
        if not isinstance(question, QuestionInput):
            raise EvidenceValidationError("EvidenceBundle question type is invalid")
        if not isinstance(store_snapshot, StoreSnapshotRef):
            raise EvidenceValidationError("EvidenceBundle snapshot type is invalid")
        if not isinstance(stop, StopRecord):
            raise EvidenceValidationError("EvidenceBundle stop type is invalid")
        if not isinstance(budget, BudgetRecord):
            raise EvidenceValidationError("EvidenceBundle budget type is invalid")
        if status not in {"completed", "capped"}:
            raise EvidenceValidationError("Unknown bundle status")
        frozen_condition = _freeze_mapping(condition, "condition")
        frozen_prompt = _freeze_mapping(prompt_contract, "prompt_contract")
        frozen_runtime = _freeze_mapping(runtime_contract, "runtime_contract")
        frozen_actions = tuple(
            _freeze_mapping(value, "search action")
            for value in _ordered_tuple(search_actions, "search_actions")
        )
        frozen_metrics = _freeze_mapping(metrics, "metrics")
        frozen_model = _freeze_mapping(model, "model")
        frozen_integrity = _freeze_mapping(integrity, "integrity")
        frozen_errors = tuple(
            _freeze_mapping(value, "error")
            for value in _ordered_tuple(errors, "errors")
        )
        items = _ordered_tuple(evidence_items, "evidence_items")
        if any(not isinstance(item, EvidenceItem) for item in items):
            raise EvidenceValidationError("EvidenceBundle evidence item type is invalid")
        _validate_bundle_mappings(
            condition=frozen_condition,
            prompt_contract=frozen_prompt,
            runtime_contract=frozen_runtime,
            metrics=frozen_metrics,
            model=frozen_model,
            integrity=frozen_integrity,
            snapshot=store_snapshot,
        )
        if question.conversation_id != store_snapshot.conversation_id:
            raise EvidenceValidationError("Question and store conversation differ")
        if any(
            item.store_id != store_snapshot.store_id
            or item.source_kind != store_snapshot.source_kind
            or item.store_snapshot_sha256 != store_snapshot.tree_sha256
            or item.source_map_sha256 != store_snapshot.source_map_sha256
            or item.records_sha256 != store_snapshot.records_sha256
            or item.attribution_index_sha256
            != store_snapshot.attribution_index_sha256
            for item in items
        ):
            raise EvidenceValidationError("EvidenceItem identity differs from bundle store")
        evidence_ids = [item.evidence_id for item in items]
        if len(evidence_ids) != len(set(evidence_ids)):
            raise EvidenceValidationError("EvidenceBundle contains duplicate evidence IDs")
        by_path: dict[str, list[EvidenceItem]] = {}
        for item in items:
            by_path.setdefault(item.path, []).append(item)
        for path, path_items in by_path.items():
            ordered = sorted(
                path_items,
                key=lambda item: (item.line_start, item.line_end, item.evidence_id),
            )
            for previous, current in zip(ordered, ordered[1:]):
                if current.line_start <= previous.line_end + 1:
                    raise EvidenceValidationError(
                        f"EvidenceBundle contains overlapping or adjacent ranges for {path}"
                    )
        ordinals = [item.selection_ordinal for item in items]
        if any(left >= right for left, right in zip(ordinals, ordinals[1:])):
            raise EvidenceValidationError(
                "EvidenceBundle selection ordinals must be strictly increasing"
            )
        if status == "completed":
            if stop.reason not in COMPLETED_STOP_REASONS or stop.hit_cap:
                raise EvidenceValidationError("Completed bundle has an invalid stop state")
            if frozen_errors:
                raise EvidenceValidationError("Completed bundle cannot contain errors")
        elif status == "capped":
            if stop.reason != "round_limit" or not stop.hit_cap:
                raise EvidenceValidationError("Capped bundle must be a round-limit stop")
            if frozen_errors:
                raise EvidenceValidationError("Capped bundle cannot contain errors")
        if frozen_errors:
            raise EvidenceValidationError(
                "EvidenceBundle cannot contain failures; use a failure artifact"
            )
        if stop.reason == "evidence_sufficient" and not items:
            raise EvidenceValidationError("Sufficient stop requires evidence")
        if stop.reason == "evidence_budget_reached" and budget.skipped_items < 1:
            raise EvidenceValidationError("Budget stop requires at least one skipped item")
        if budget.unit != frozen_runtime["evidence_budget_unit"]:
            raise EvidenceValidationError("Budget unit differs from runtime contract")
        if budget.limit != frozen_runtime["evidence_budget_limit"]:
            raise EvidenceValidationError("Budget limit differs from runtime contract")
        if budget.unit == "bytes":
            expected_used = sum(len(item.text.encode("utf-8")) for item in items)
        elif budget.unit == "characters":
            expected_used = sum(len(item.text) for item in items)
        else:  # pragma: no cover - token budgets fail in BudgetRecord
            raise EvidenceValidationError("Token evidence budgets are not enabled")
        if budget.used != expected_used:
            raise EvidenceValidationError("Budget usage does not match evidence text")
        rounds = frozen_metrics["provider_rounds"]
        round_limit = frozen_runtime["round_limit"]
        if stop.rounds_without_new_evidence > rounds:
            raise EvidenceValidationError(
                "No-progress round count exceeds reported provider rounds"
            )
        if rounds > round_limit:
            raise EvidenceValidationError("Provider rounds exceed the runtime limit")
        if status == "capped" and rounds != round_limit:
            raise EvidenceValidationError("Round-limit stop must reach the configured limit")
        if items and max(item.retrieval_round for item in items) > rounds:
            raise EvidenceValidationError(
                "Evidence retrieval_round exceeds reported provider rounds"
            )
        if not (frozen_integrity["store_unchanged"] and frozen_integrity["verified"]):
            raise EvidenceValidationError(
                "Valid retrieval bundles require verified store integrity"
            )
        placeholder = cls(
            schema_version=EVIDENCE_SCHEMA_VERSION,
            protocol_version=EVIDENCE_PROTOCOL_VERSION,
            bundle_id="",
            status=status,
            question=question,
            question_sha256=question.sha256,
            condition=frozen_condition,
            store_snapshot=store_snapshot,
            prompt_contract=frozen_prompt,
            runtime_contract=frozen_runtime,
            search_actions=frozen_actions,
            evidence_items=items,
            stop=stop,
            budget=budget,
            metrics=frozen_metrics,
            model=frozen_model,
            integrity=frozen_integrity,
            errors=frozen_errors,
        )
        bundle_id = "bundle-" + sha256_bytes(canonical_json_bytes(placeholder._body()))
        return cls(**{**placeholder.__dict__, "bundle_id": bundle_id})


@dataclass(frozen=True)
class RetrievalFailureArtifact:
    """A deterministic audit record for a run that produced no valid bundle.

    This is intentionally separate from :class:`EvidenceBundle`. In particular,
    store drift can be recorded without pretending the old snapshot is still valid.
    """

    schema_version: int
    protocol_version: str
    failure_id: str
    question: QuestionInput
    question_sha256: str
    condition: Mapping[str, Any]
    store_snapshot: StoreSnapshotRef
    prompt_contract: Mapping[str, Any]
    runtime_contract: Mapping[str, Any]
    search_actions: tuple[Mapping[str, Any], ...]
    metrics: Mapping[str, Any]
    model: Mapping[str, Any]
    integrity: Mapping[str, Any]
    failure_kind: str
    errors: tuple[Mapping[str, Any], ...]

    def __post_init__(self) -> None:
        if not isinstance(self.question, QuestionInput):
            raise EvidenceValidationError("Failure artifact question type is invalid")
        if not isinstance(self.store_snapshot, StoreSnapshotRef):
            raise EvidenceValidationError("Failure artifact snapshot type is invalid")
        object.__setattr__(self, "condition", _freeze_mapping(self.condition, "condition"))
        object.__setattr__(
            self,
            "prompt_contract",
            _freeze_mapping(self.prompt_contract, "prompt_contract"),
        )
        object.__setattr__(
            self,
            "runtime_contract",
            _freeze_mapping(self.runtime_contract, "runtime_contract"),
        )
        object.__setattr__(
            self,
            "search_actions",
            tuple(
                _freeze_mapping(value, "search action")
                for value in _ordered_tuple(
                    self.search_actions, "Failure artifact search_actions"
                )
            ),
        )
        object.__setattr__(self, "metrics", _freeze_mapping(self.metrics, "metrics"))
        object.__setattr__(self, "model", _freeze_mapping(self.model, "model"))
        object.__setattr__(
            self, "integrity", _freeze_mapping(self.integrity, "integrity")
        )
        object.__setattr__(
            self,
            "errors",
            tuple(
                _freeze_mapping(value, "error")
                for value in _ordered_tuple(self.errors, "Failure artifact errors")
            ),
        )

    def _body(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "protocol_version": self.protocol_version,
            "status": "failed",
            "question": self.question.to_dict(),
            "question_sha256": self.question_sha256,
            "condition": _plain_json(self.condition),
            "store_snapshot": self.store_snapshot.to_dict(),
            "prompt_contract": _plain_json(self.prompt_contract),
            "runtime_contract": _plain_json(self.runtime_contract),
            "search_actions": [_plain_json(value) for value in self.search_actions],
            "metrics": _plain_json(self.metrics),
            "model": _plain_json(self.model),
            "integrity": _plain_json(self.integrity),
            "failure_kind": self.failure_kind,
            "errors": [_plain_json(value) for value in self.errors],
        }

    def to_dict(self) -> dict[str, Any]:
        return {"failure_id": self.failure_id, **self._body()}

    @classmethod
    def create(
        cls,
        *,
        question: QuestionInput,
        condition: Mapping[str, Any],
        store_snapshot: StoreSnapshotRef,
        prompt_contract: Mapping[str, Any],
        runtime_contract: Mapping[str, Any],
        search_actions: Sequence[Mapping[str, Any]],
        metrics: Mapping[str, Any],
        model: Mapping[str, Any],
        integrity: Mapping[str, Any],
        failure_kind: str,
        errors: Sequence[Mapping[str, Any]],
    ) -> "RetrievalFailureArtifact":
        if not isinstance(question, QuestionInput):
            raise EvidenceValidationError("Failure artifact question type is invalid")
        if not isinstance(store_snapshot, StoreSnapshotRef):
            raise EvidenceValidationError("Failure artifact snapshot type is invalid")
        frozen_condition = _freeze_mapping(condition, "condition")
        frozen_prompt = _freeze_mapping(prompt_contract, "prompt_contract")
        frozen_runtime = _freeze_mapping(runtime_contract, "runtime_contract")
        frozen_actions = tuple(
            _freeze_mapping(value, "search action")
            for value in _ordered_tuple(search_actions, "search_actions")
        )
        frozen_metrics = _freeze_mapping(metrics, "metrics")
        frozen_model = _freeze_mapping(model, "model")
        frozen_integrity = _freeze_mapping(integrity, "integrity")
        frozen_errors = tuple(
            _freeze_mapping(value, "error")
            for value in _ordered_tuple(errors, "errors")
        )
        _validate_bundle_mappings(
            condition=frozen_condition,
            prompt_contract=frozen_prompt,
            runtime_contract=frozen_runtime,
            metrics=frozen_metrics,
            model=frozen_model,
            integrity=frozen_integrity,
            snapshot=store_snapshot,
        )
        if question.conversation_id != store_snapshot.conversation_id:
            raise EvidenceValidationError("Question and store conversation differ")
        _require_nonempty(failure_kind, "failure_kind")
        if not frozen_errors:
            raise EvidenceValidationError("Failure artifact requires at least one error")
        if frozen_integrity["verified"]:
            raise EvidenceValidationError("Failure artifact cannot claim verified=true")
        placeholder = cls(
            schema_version=EVIDENCE_SCHEMA_VERSION,
            protocol_version=EVIDENCE_PROTOCOL_VERSION,
            failure_id="",
            question=question,
            question_sha256=question.sha256,
            condition=frozen_condition,
            store_snapshot=store_snapshot,
            prompt_contract=frozen_prompt,
            runtime_contract=frozen_runtime,
            search_actions=frozen_actions,
            metrics=frozen_metrics,
            model=frozen_model,
            integrity=frozen_integrity,
            failure_kind=failure_kind,
            errors=frozen_errors,
        )
        failure_id = "failure-" + sha256_bytes(
            canonical_json_bytes(placeholder._body())
        )
        return cls(**{**placeholder.__dict__, "failure_id": failure_id})


def validate_retrieval_failure_artifact(
    artifact: RetrievalFailureArtifact,
) -> None:
    """Validate failure identity without requiring the failed store to be healthy."""
    if artifact.schema_version != EVIDENCE_SCHEMA_VERSION:
        raise EvidenceValidationError("Failure artifact schema version mismatch")
    if artifact.protocol_version != EVIDENCE_PROTOCOL_VERSION:
        raise EvidenceValidationError("Failure artifact protocol version mismatch")
    if artifact.question_sha256 != artifact.question.sha256:
        raise EvidenceValidationError("Failure artifact question hash is invalid")
    recreated = RetrievalFailureArtifact.create(
        question=artifact.question,
        condition=artifact.condition,
        store_snapshot=artifact.store_snapshot,
        prompt_contract=artifact.prompt_contract,
        runtime_contract=artifact.runtime_contract,
        search_actions=artifact.search_actions,
        metrics=artifact.metrics,
        model=artifact.model,
        integrity=artifact.integrity,
        failure_kind=artifact.failure_kind,
        errors=artifact.errors,
    )
    if recreated != artifact:
        raise EvidenceValidationError("Failure artifact identity or content is invalid")


def validate_evidence_bundle(
    bundle: EvidenceBundle,
    *,
    root: Path,
    catalog: SourceCatalog,
    verified_manifest: VerifiedStoreManifest,
) -> None:
    if bundle.schema_version != EVIDENCE_SCHEMA_VERSION:
        raise EvidenceValidationError("EvidenceBundle schema version mismatch")
    if bundle.protocol_version != EVIDENCE_PROTOCOL_VERSION:
        raise EvidenceValidationError("EvidenceBundle protocol version mismatch")
    if bundle.question_sha256 != bundle.question.sha256:
        raise EvidenceValidationError("EvidenceBundle question hash is invalid")
    validate_store_snapshot(
        bundle.store_snapshot,
        root=root,
        catalog=catalog,
        verified_manifest=verified_manifest,
    )
    for item in bundle.evidence_items:
        validate_evidence_item(
            item,
            root=root,
            catalog=catalog,
            verified_manifest=verified_manifest,
            snapshot=bundle.store_snapshot,
        )
    recreated = EvidenceBundle.create(
        status=bundle.status,
        question=bundle.question,
        condition=bundle.condition,
        store_snapshot=bundle.store_snapshot,
        prompt_contract=bundle.prompt_contract,
        runtime_contract=bundle.runtime_contract,
        search_actions=bundle.search_actions,
        evidence_items=bundle.evidence_items,
        stop=bundle.stop,
        budget=bundle.budget,
        metrics=bundle.metrics,
        model=bundle.model,
        integrity=bundle.integrity,
        errors=bundle.errors,
    )
    if recreated != bundle:
        raise EvidenceValidationError("EvidenceBundle identity or content is invalid")


def validate_r1_evidence_bundle_profile(bundle: EvidenceBundle) -> None:
    """Apply R1-only constraints on top of the retrieval-neutral bundle schema.

    R2/R3 may attach deterministic ranks or scores to the same shared evidence
    objects.  Native filesystem R1 has neither concept, so accepting either in
    an R1 run would silently mix retrieval protocols.
    """
    if bundle.condition.get("retrieval_id") != "r1":
        raise EvidenceValidationError("R1 bundle retrieval_id must be r1")
    if any(item.rank is not None or item.score is not None for item in bundle.evidence_items):
        raise EvidenceValidationError("R1 evidence must not carry rank or score")
