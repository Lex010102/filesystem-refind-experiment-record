"""Deterministic, read-only parser for the frozen E6/S3 curated store.

The parser converts the two published Markdown memories into fact-level BM25
documents and H2-level topic groups.  It authenticates every input through the
shared R1 loader before parsing and never writes to the S3 store.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from datetime import date
from pathlib import Path
from typing import Any, Iterable

from .evidence import EvidenceValidationError, canonical_json_bytes, sha256_bytes
from .r1_inputs import LoadedR1Store, load_r1_store
from .r3_protocol import (
    R3_INPUT_IDENTITY,
    R3_PROTOCOL_VERSION,
    verify_r3_protocol,
)


_LOCATOR_RE = re.compile(r"\[S([1-9][0-9]*)T([1-9][0-9]*)\]")
_LOCATOR_LIKE_RE = re.compile(r"\[S[^\]\r\n]*T[^\]\r\n]*\]")
_LIST_ITEM_RE = re.compile(r"^(?P<indent>[ \t]*)(?P<marker>[-*+])[ \t]+(?P<body>.*)$")
_H1_RE = re.compile(r"^#[ \t]+(?P<heading>\S.*)$")
_H2_RE = re.compile(r"^##[ \t]+(?P<heading>\S.*)$")
_ANY_HEADING_RE = re.compile(r"^#{1,6}(?:[ \t]+|$)")
_FRONTMATTER_NAME_RE = re.compile(r"^name:[ \t]*(?P<name>\S.*)$")

FROZEN_R3_CORPUS_SHA256 = (
    "9f968d7848b468e6519d428c40b24f30cb662bd0cc6b674e1c4deab4e263f086"
)


@dataclass(frozen=True)
class R3FactUnit:
    unit_id: str
    canonical_index: int
    relative_path: str
    file_ordinal: int
    entity_name: str
    h1_heading: str
    h2_heading: str
    h2_ordinal: int
    group_id: str
    unit_ordinal_in_group: int
    line_start: int
    line_end: int
    indentation: int
    nested: bool
    exact_markdown_text: str
    fact_text_without_locators: str
    search_text: str
    source_locators: tuple[str, ...]
    dia_ids: tuple[str, ...]
    source_session_ids: tuple[str, ...]
    source_dates: tuple[str, ...]
    min_source_date: str
    max_source_date: str
    content_sha256: str

    def __post_init__(self) -> None:
        expected_id = (
            f"fact-f{self.file_ordinal:02d}-h{self.h2_ordinal:03d}-"
            f"u{self.unit_ordinal_in_group:03d}"
        )
        if self.unit_id != expected_id:
            raise EvidenceValidationError("R3 fact unit_id is not canonical")
        if self.canonical_index < 1:
            raise EvidenceValidationError("R3 fact canonical_index must be positive")
        if self.group_id != f"{self.relative_path}::h2-{self.h2_ordinal:03d}":
            raise EvidenceValidationError("R3 fact group_id is not canonical")
        if self.line_start < 1 or self.line_end < self.line_start:
            raise EvidenceValidationError("R3 fact line range is invalid")
        if self.indentation < 0 or self.nested != (self.indentation > 0):
            raise EvidenceValidationError("R3 fact nesting metadata is invalid")
        if not self.exact_markdown_text or not self.fact_text_without_locators:
            raise EvidenceValidationError("R3 fact text must be non-empty")
        if _LOCATOR_RE.search(self.search_text):
            raise EvidenceValidationError("R3 BM25 text must not contain locators")
        if len(self.source_locators) != len(self.dia_ids):
            raise EvidenceValidationError("R3 locator/dia_id cardinality differs")
        if not self.source_locators or len(set(self.source_locators)) != len(
            self.source_locators
        ):
            raise EvidenceValidationError("R3 source locators must be unique and non-empty")
        if not self.source_dates or tuple(sorted(set(self.source_dates))) != self.source_dates:
            raise EvidenceValidationError("R3 source dates must be sorted and unique")
        if self.min_source_date != self.source_dates[0] or self.max_source_date != self.source_dates[-1]:
            raise EvidenceValidationError("R3 source date bounds are inconsistent")
        if self.content_sha256 != sha256_bytes(self.exact_markdown_text.encode("utf-8")):
            raise EvidenceValidationError("R3 fact content hash is invalid")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class R3TopicGroup:
    group_id: str
    relative_path: str
    file_ordinal: int
    entity_name: str
    h1_heading: str
    h2_heading: str
    h2_ordinal: int
    heading_line: int
    first_canonical_index: int
    unit_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        if self.group_id != f"{self.relative_path}::h2-{self.h2_ordinal:03d}":
            raise EvidenceValidationError("R3 topic group_id is not canonical")
        if self.heading_line < 1 or self.first_canonical_index < 1:
            raise EvidenceValidationError("R3 topic group coordinates are invalid")
        if not self.unit_ids or len(set(self.unit_ids)) != len(self.unit_ids):
            raise EvidenceValidationError("R3 topic group must have unique fact units")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class R3CorpusStats:
    file_count: int
    total_bytes: int
    total_lines: int
    h1_count: int
    h2_group_count: int
    fact_unit_count: int
    nested_fact_unit_count: int
    body_locator_mentions: int
    unique_body_locators: int
    source_locator_count: int
    missing_source_locator_count: int
    frontmatter_locator_mentions_excluded: int

    def to_dict(self) -> dict[str, int]:
        return asdict(self)


@dataclass(frozen=True)
class R3CuratedCorpus:
    protocol_version: str
    store: LoadedR1Store
    groups: tuple[R3TopicGroup, ...]
    units: tuple[R3FactUnit, ...]
    stats: R3CorpusStats
    corpus_sha256: str

    def __post_init__(self) -> None:
        if self.protocol_version != R3_PROTOCOL_VERSION:
            raise EvidenceValidationError("R3 corpus protocol version mismatch")
        if self.store.snapshot.store_id != "s3":
            raise EvidenceValidationError("R3 corpus must use the S3 store")
        if len(self.groups) != self.stats.h2_group_count:
            raise EvidenceValidationError("R3 corpus group count differs from stats")
        if len(self.units) != self.stats.fact_unit_count:
            raise EvidenceValidationError("R3 corpus unit count differs from stats")
        if tuple(unit.canonical_index for unit in self.units) != tuple(
            range(1, len(self.units) + 1)
        ):
            raise EvidenceValidationError("R3 canonical indexes are not contiguous")
        all_group_units = tuple(unit_id for group in self.groups for unit_id in group.unit_ids)
        if all_group_units != tuple(unit.unit_id for unit in self.units):
            raise EvidenceValidationError("R3 group membership differs from corpus order")
        if self.corpus_sha256 != _corpus_sha256(self.store, self.groups, self.units, self.stats):
            raise EvidenceValidationError("R3 corpus identity hash is invalid")

    def unit_by_id(self, unit_id: str) -> R3FactUnit:
        for unit in self.units:
            if unit.unit_id == unit_id:
                return unit
        raise EvidenceValidationError(f"Unknown R3 fact unit: {unit_id}")

    def group_by_id(self, group_id: str) -> R3TopicGroup:
        for group in self.groups:
            if group.group_id == group_id:
                return group
        raise EvidenceValidationError(f"Unknown R3 topic group: {group_id}")


@dataclass(frozen=True)
class _PendingFact:
    line_start: int
    lines: tuple[str, ...]


def _ordered_unique(values: Iterable[str]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(values))


def _strip_locator_tokens(text: str) -> str:
    stripped = _LOCATOR_RE.sub("", text)
    return "\n".join(line.rstrip() for line in stripped.splitlines()).strip()


def _parse_frontmatter(lines: list[str], relative_path: str) -> tuple[str, int, int]:
    if not lines or lines[0] != "---":
        raise EvidenceValidationError(f"R3 file lacks YAML frontmatter: {relative_path}")
    try:
        closing_index = lines.index("---", 1)
    except ValueError as exc:
        raise EvidenceValidationError(
            f"R3 file has unterminated YAML frontmatter: {relative_path}"
        ) from exc
    names = [
        match.group("name").strip()
        for line in lines[1:closing_index]
        if (match := _FRONTMATTER_NAME_RE.fullmatch(line)) is not None
    ]
    if len(names) != 1:
        raise EvidenceValidationError(
            f"R3 frontmatter must contain exactly one simple name: {relative_path}"
        )
    mentions = sum(len(_LOCATOR_RE.findall(line)) for line in lines[1:closing_index])
    return names[0], closing_index + 1, mentions


def _build_fact(
    *,
    pending: _PendingFact,
    store: LoadedR1Store,
    relative_path: str,
    file_ordinal: int,
    entity_name: str,
    h1_heading: str,
    h2_heading: str,
    h2_ordinal: int,
    unit_ordinal: int,
    canonical_index: int,
) -> R3FactUnit:
    lines = list(pending.lines)
    while len(lines) > 1 and not lines[-1].strip():
        lines.pop()
    exact = "\n".join(lines)
    marker_match = _LIST_ITEM_RE.match(lines[0])
    if marker_match is None:
        raise EvidenceValidationError("R3 internal fact boundary is invalid")
    locator_candidates = _LOCATOR_LIKE_RE.findall(exact)
    locators = _ordered_unique(match.group(0) for match in _LOCATOR_RE.finditer(exact))
    if any(_LOCATOR_RE.fullmatch(candidate) is None for candidate in locator_candidates):
        raise EvidenceValidationError(
            f"R3 fact contains a malformed source locator at {relative_path}:{pending.line_start}"
        )
    if not locators:
        raise EvidenceValidationError(
            f"R3 fact lacks a source locator at {relative_path}:{pending.line_start}"
        )
    refs = store.catalog.resolve_many(locators)
    fact_lines = [marker_match.group("body"), *lines[1:]]
    fact_without_locators = _strip_locator_tokens("\n".join(fact_lines))
    if not fact_without_locators:
        raise EvidenceValidationError("R3 fact becomes empty after locator removal")
    source_dates = tuple(sorted({ref.session_date for ref in refs}))
    for source_date in source_dates:
        try:
            date.fromisoformat(source_date)
        except ValueError as exc:
            raise EvidenceValidationError("R3 source date is not ISO YYYY-MM-DD") from exc
    group_id = f"{relative_path}::h2-{h2_ordinal:03d}"
    search_text = f"{entity_name}\n{h2_heading}\n{fact_without_locators}"
    return R3FactUnit(
        unit_id=(
            f"fact-f{file_ordinal:02d}-h{h2_ordinal:03d}-u{unit_ordinal:03d}"
        ),
        canonical_index=canonical_index,
        relative_path=relative_path,
        file_ordinal=file_ordinal,
        entity_name=entity_name,
        h1_heading=h1_heading,
        h2_heading=h2_heading,
        h2_ordinal=h2_ordinal,
        group_id=group_id,
        unit_ordinal_in_group=unit_ordinal,
        line_start=pending.line_start,
        line_end=pending.line_start + len(lines) - 1,
        indentation=len(marker_match.group("indent").expandtabs(4)),
        nested=bool(marker_match.group("indent")),
        exact_markdown_text=exact,
        fact_text_without_locators=fact_without_locators,
        search_text=search_text,
        source_locators=locators,
        dia_ids=tuple(ref.dia_id for ref in refs),
        source_session_ids=_ordered_unique(ref.session_id for ref in refs),
        source_dates=source_dates,
        min_source_date=source_dates[0],
        max_source_date=source_dates[-1],
        content_sha256=sha256_bytes(exact.encode("utf-8")),
    )


def _parse_file(
    *,
    store: LoadedR1Store,
    relative_path: str,
    file_ordinal: int,
    canonical_start: int,
) -> tuple[list[R3TopicGroup], list[R3FactUnit], dict[str, int]]:
    payload = store.verified_manifest.read_verified_file(store.root, relative_path)
    try:
        text = payload.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise EvidenceValidationError(f"R3 file is not UTF-8: {relative_path}") from exc
    if "\r" in text:
        raise EvidenceValidationError(f"R3 file uses non-canonical line endings: {relative_path}")
    lines = text.splitlines()
    entity_name, body_start, frontmatter_mentions = _parse_frontmatter(lines, relative_path)
    expected_stem = Path(relative_path).stem
    if entity_name.casefold() != expected_stem.casefold():
        raise EvidenceValidationError("R3 frontmatter name and filename differ")

    h1_heading: str | None = None
    h1_count = 0
    h2_heading: str | None = None
    h2_heading_line = 0
    h2_ordinal = 0
    pending: _PendingFact | None = None
    groups: list[R3TopicGroup] = []
    units: list[R3FactUnit] = []
    current_group_units: list[R3FactUnit] = []

    def flush_fact() -> None:
        nonlocal pending
        if pending is None:
            return
        if h1_heading is None or h2_heading is None:
            raise EvidenceValidationError("R3 fact appears outside an H1/H2 hierarchy")
        fact = _build_fact(
            pending=pending,
            store=store,
            relative_path=relative_path,
            file_ordinal=file_ordinal,
            entity_name=entity_name,
            h1_heading=h1_heading,
            h2_heading=h2_heading,
            h2_ordinal=h2_ordinal,
            unit_ordinal=len(current_group_units) + 1,
            canonical_index=canonical_start + len(units),
        )
        current_group_units.append(fact)
        units.append(fact)
        pending = None

    def flush_group() -> None:
        nonlocal current_group_units
        flush_fact()
        if h2_heading is None:
            return
        if not current_group_units:
            raise EvidenceValidationError(
                f"R3 H2 group contains no facts: {relative_path}:{h2_heading_line}"
            )
        groups.append(
            R3TopicGroup(
                group_id=f"{relative_path}::h2-{h2_ordinal:03d}",
                relative_path=relative_path,
                file_ordinal=file_ordinal,
                entity_name=entity_name,
                h1_heading=h1_heading or "",
                h2_heading=h2_heading,
                h2_ordinal=h2_ordinal,
                heading_line=h2_heading_line,
                first_canonical_index=current_group_units[0].canonical_index,
                unit_ids=tuple(unit.unit_id for unit in current_group_units),
            )
        )
        current_group_units = []

    for zero_index in range(body_start, len(lines)):
        line = lines[zero_index]
        line_number = zero_index + 1
        h2_match = _H2_RE.fullmatch(line)
        h1_match = _H1_RE.fullmatch(line)
        list_match = _LIST_ITEM_RE.match(line)
        if h2_match is not None:
            flush_group()
            if h1_heading is None:
                raise EvidenceValidationError("R3 H2 appears before H1")
            h2_ordinal += 1
            h2_heading = h2_match.group("heading").strip()
            h2_heading_line = line_number
            continue
        if h1_match is not None:
            flush_group()
            h1_count += 1
            if h1_count != 1:
                raise EvidenceValidationError("R3 file must contain exactly one H1")
            h1_heading = h1_match.group("heading").strip()
            if h1_heading.casefold() != entity_name.casefold():
                raise EvidenceValidationError("R3 H1 and frontmatter name differ")
            continue
        if _ANY_HEADING_RE.match(line):
            raise EvidenceValidationError(
                f"R3 only permits H1/H2 headings: {relative_path}:{line_number}"
            )
        if list_match is not None:
            flush_fact()
            if h2_heading is None:
                raise EvidenceValidationError("R3 list item appears outside an H2 group")
            pending = _PendingFact(line_start=line_number, lines=(line,))
            continue
        if not line.strip():
            if pending is not None:
                pending = _PendingFact(
                    line_start=pending.line_start, lines=(*pending.lines, line)
                )
            continue
        if pending is None:
            raise EvidenceValidationError(
                f"R3 has non-fact prose in the indexed body: {relative_path}:{line_number}"
            )
        if not line.startswith((" ", "\t")):
            raise EvidenceValidationError(
                f"R3 fact continuation must be indented: {relative_path}:{line_number}"
            )
        pending = _PendingFact(
            line_start=pending.line_start, lines=(*pending.lines, line)
        )

    flush_group()
    if h1_count != 1 or h1_heading is None:
        raise EvidenceValidationError("R3 file must contain exactly one H1")
    if not groups or h2_ordinal != len(groups):
        raise EvidenceValidationError("R3 file has an invalid H2 hierarchy")
    return groups, units, {
        "bytes": len(payload),
        "lines": len(lines),
        "h1": h1_count,
        "frontmatter_mentions": frontmatter_mentions,
    }


def _corpus_sha256(
    store: LoadedR1Store,
    groups: tuple[R3TopicGroup, ...],
    units: tuple[R3FactUnit, ...],
    stats: R3CorpusStats,
) -> str:
    body = {
        "protocol_version": R3_PROTOCOL_VERSION,
        "snapshot": asdict(store.snapshot),
        "stats": stats.to_dict(),
        "groups": [group.to_dict() for group in groups],
        "units": [unit.to_dict() for unit in units],
    }
    return sha256_bytes(canonical_json_bytes(body))


def load_r3_corpus(repo_root: Path) -> R3CuratedCorpus:
    """Load, authenticate and parse the formal S3 snapshot."""

    verify_r3_protocol()
    store = load_r1_store(Path(repo_root), "s3")
    identity = R3_INPUT_IDENTITY
    if store.snapshot.tree_sha256 != identity["shared_snapshot_tree_sha256"]:
        raise EvidenceValidationError("R3 S3 snapshot differs from the frozen protocol")
    if store.snapshot.manifest_sha256 != identity["manifest_sha256"]:
        raise EvidenceValidationError("R3 manifest differs from the frozen protocol")

    paths = store.verified_manifest.file_paths
    groups: list[R3TopicGroup] = []
    units: list[R3FactUnit] = []
    aggregate = {"bytes": 0, "lines": 0, "h1": 0, "frontmatter_mentions": 0}
    for file_ordinal, relative_path in enumerate(paths, start=1):
        parsed_groups, parsed_units, file_stats = _parse_file(
            store=store,
            relative_path=relative_path,
            file_ordinal=file_ordinal,
            canonical_start=len(units) + 1,
        )
        groups.extend(parsed_groups)
        units.extend(parsed_units)
        for key in aggregate:
            aggregate[key] += file_stats[key]

    # ``source_locators`` is a semantic ordered-unique list per fact.  The
    # frozen build metric counts physical inline mentions, including repeated
    # locators on the same list item, so compute that value from exact text.
    body_locator_mentions = tuple(
        match.group(0)
        for unit in units
        for match in _LOCATOR_RE.finditer(unit.exact_markdown_text)
    )
    source_locators = store.catalog.locators
    unique_body_locators = frozenset(body_locator_mentions)
    if not unique_body_locators.issubset(source_locators):
        raise EvidenceValidationError("R3 contains locators outside the source catalog")
    stats = R3CorpusStats(
        file_count=len(paths),
        total_bytes=aggregate["bytes"],
        total_lines=aggregate["lines"],
        h1_count=aggregate["h1"],
        h2_group_count=len(groups),
        fact_unit_count=len(units),
        nested_fact_unit_count=sum(unit.nested for unit in units),
        body_locator_mentions=len(body_locator_mentions),
        unique_body_locators=len(unique_body_locators),
        source_locator_count=len(source_locators),
        missing_source_locator_count=len(source_locators - unique_body_locators),
        frontmatter_locator_mentions_excluded=aggregate["frontmatter_mentions"],
    )
    expected_stats = {
        "file_count": int(identity["expected_files"]),
        "total_bytes": int(identity["expected_bytes"]),
        "total_lines": int(identity["expected_lines"]),
        "h1_count": int(identity["expected_h1"]),
        "h2_group_count": int(identity["expected_h2_groups"]),
        "fact_unit_count": int(identity["expected_fact_units"]),
        "nested_fact_unit_count": int(identity["expected_nested_fact_units"]),
        "body_locator_mentions": int(identity["expected_body_locator_mentions"]),
        "unique_body_locators": int(identity["expected_unique_locators"]),
        "source_locator_count": int(identity["expected_source_locators"]),
        "missing_source_locator_count": int(identity["expected_missing_source_locators"]),
        "frontmatter_locator_mentions_excluded": int(
            identity["expected_frontmatter_locator_mentions_excluded"]
        ),
    }
    if stats.to_dict() != expected_stats:
        raise EvidenceValidationError(
            f"R3 parsed corpus differs from frozen counts: {stats.to_dict()}"
        )

    group_tuple = tuple(groups)
    unit_tuple = tuple(units)
    digest = _corpus_sha256(store, group_tuple, unit_tuple, stats)
    if digest != FROZEN_R3_CORPUS_SHA256:
        raise EvidenceValidationError(
            "Parsed R3 corpus changed without a frozen corpus hash update"
        )
    return R3CuratedCorpus(
        protocol_version=R3_PROTOCOL_VERSION,
        store=store,
        groups=group_tuple,
        units=unit_tuple,
        stats=stats,
        corpus_sha256=digest,
    )


def preflight_r3_inputs(repo_root: Path) -> dict[str, Any]:
    corpus = load_r3_corpus(repo_root)
    group_sizes = tuple(len(group.unit_ids) for group in corpus.groups)
    unit_lengths = tuple(len(unit.exact_markdown_text) for unit in corpus.units)
    return {
        "protocol_version": corpus.protocol_version,
        "store_id": corpus.store.snapshot.store_id,
        "snapshot_tree_sha256": corpus.store.snapshot.tree_sha256,
        "corpus_sha256": corpus.corpus_sha256,
        "stats": corpus.stats.to_dict(),
        "group_size_min": min(group_sizes),
        "group_size_max": max(group_sizes),
        "fact_chars_min": min(unit_lengths),
        "fact_chars_max": max(unit_lengths),
    }
