"""Hash-verified S1/S2 adapters for exchange-level R2-Raw retrieval."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from .evidence import (
    EvidenceValidationError,
    SourceRecordRef,
    canonical_json_bytes,
    sha256_bytes,
)
from .r1_inputs import LoadedR1Store, load_r1_store
from .r2_protocol import R2_PARAMETERS, verify_r2_protocol


@dataclass(frozen=True)
class R2SourceTurn:
    record: SourceRecordRef
    relative_path: str
    line_start: int
    line_end: int
    search_text: str
    rendered_text: str

    def __post_init__(self) -> None:
        if not self.search_text or not self.rendered_text:
            raise EvidenceValidationError("R2 source-turn text must be nonempty")
        if self.record.locator in self.search_text or self.record.dia_id in self.search_text:
            raise EvidenceValidationError("R2 search text must not contain provenance IDs")
        if self.record.locator not in self.rendered_text:
            raise EvidenceValidationError("R2 rendered turn must preserve its locator")


@dataclass(frozen=True)
class R2Exchange:
    exchange_id: str
    session_id: str
    session_index: int
    exchange_index: int
    session_date: str
    session_datetime: str
    relative_path: str
    line_start: int
    line_end: int
    source_turns: tuple[R2SourceTurn, ...]
    search_text: str
    display_text: str
    canonical_index: int

    def __post_init__(self) -> None:
        if len(self.source_turns) not in {1, 2}:
            raise EvidenceValidationError("An R2 exchange must contain one or two turns")
        if any(turn.record.session_id != self.session_id for turn in self.source_turns):
            raise EvidenceValidationError("R2 exchange crosses a session boundary")
        if any(turn.relative_path != self.relative_path for turn in self.source_turns):
            raise EvidenceValidationError("R2 exchange crosses a file boundary")
        turn_indexes = tuple(turn.record.turn_index for turn in self.source_turns)
        if len(turn_indexes) == 2 and turn_indexes[1] != turn_indexes[0] + 1:
            raise EvidenceValidationError("R2 exchange source turns are not adjacent")
        if self.exchange_index != (turn_indexes[0] + 1) // 2:
            raise EvidenceValidationError("R2 exchange index is inconsistent")
        expected_id = f"ex-s{self.session_index:02d}-e{self.exchange_index:03d}"
        if self.exchange_id != expected_id:
            raise EvidenceValidationError("R2 exchange ID is inconsistent")
        if self.line_start != self.source_turns[0].line_start:
            raise EvidenceValidationError("R2 exchange start line is inconsistent")
        if self.line_end != self.source_turns[-1].line_end:
            raise EvidenceValidationError("R2 exchange end line is inconsistent")

    @property
    def locators(self) -> tuple[str, ...]:
        return tuple(turn.record.locator for turn in self.source_turns)

    @property
    def dia_ids(self) -> tuple[str, ...]:
        return tuple(turn.record.dia_id for turn in self.source_turns)


@dataclass(frozen=True)
class R2RawCorpus:
    store: LoadedR1Store
    exchanges: tuple[R2Exchange, ...]
    corpus_sha256: str

    def __post_init__(self) -> None:
        if self.store.snapshot.store_id not in {"s1", "s2"}:
            raise EvidenceValidationError("R2-Raw accepts only S1 or S2")
        if not self.exchanges:
            raise EvidenceValidationError("R2-Raw corpus must be nonempty")

    @property
    def store_id(self) -> str:
        return self.store.snapshot.store_id

    @property
    def sessions(self) -> tuple[str, ...]:
        return tuple(dict.fromkeys(exchange.session_id for exchange in self.exchanges))

    def session_exchanges(self, session_id: str) -> tuple[R2Exchange, ...]:
        return tuple(item for item in self.exchanges if item.session_id == session_id)


def _sorted_records(store: LoadedR1Store) -> tuple[SourceRecordRef, ...]:
    return tuple(
        sorted(
            (store.catalog.resolve(locator) for locator in store.catalog.locators),
            key=lambda item: item.global_turn_index,
        )
    )


def _read_source_turns(store: LoadedR1Store) -> tuple[R2SourceTurn, ...]:
    cache: dict[str, list[str]] = {}
    turns: list[R2SourceTurn] = []
    for record in _sorted_records(store):
        occurrences = store.verified_manifest.attribution_index.occurrences(record.locator)
        if len(occurrences) != 1:
            raise EvidenceValidationError("Raw R2 source turn must have one occurrence")
        span = occurrences[0]
        if span.path not in cache:
            payload = store.verified_manifest.read_verified_file(store.root, span.path)
            try:
                cache[span.path] = payload.decode("utf-8").splitlines()
            except UnicodeDecodeError as exc:
                raise EvidenceValidationError("R2 source file is not UTF-8") from exc
        lines = cache[span.path]
        if span.line_end > len(lines):
            raise EvidenceValidationError("R2 source span exceeds its file")
        rendered_lines = lines[span.line_start - 1 : span.line_end]
        if not rendered_lines or rendered_lines[-1] != (
            f"{record.locator} (dia_id: {record.dia_id})"
        ):
            raise EvidenceValidationError("R2 raw locator line differs from the manifest")
        rendered = "\n".join(rendered_lines)
        search = "\n".join(rendered_lines[:-1])
        turns.append(
            R2SourceTurn(
                record=record,
                relative_path=span.path,
                line_start=span.line_start,
                line_end=span.line_end,
                search_text=search,
                rendered_text=rendered,
            )
        )
    return tuple(turns)


def _corpus_digest(exchanges: Iterable[R2Exchange]) -> str:
    return sha256_bytes(
        canonical_json_bytes(
            [
                {
                    "exchange_id": item.exchange_id,
                    "session_id": item.session_id,
                    "session_date": item.session_date,
                    "relative_path": item.relative_path,
                    "line_start": item.line_start,
                    "line_end": item.line_end,
                    "locators": item.locators,
                    "search_text": item.search_text,
                    "display_text": item.display_text,
                }
                for item in exchanges
            ]
        )
    )


def build_r2_raw_corpus(repo_root: Path, store_id: str) -> R2RawCorpus:
    """Load a frozen raw store and pair every adjacent source turn deterministically."""
    verify_r2_protocol()
    if not isinstance(store_id, str) or store_id.casefold() not in {"s1", "s2"}:
        raise EvidenceValidationError("R2-Raw store_id must be s1 or s2")
    store = load_r1_store(repo_root, store_id.casefold())
    source_turns = _read_source_turns(store)
    by_session: dict[str, list[R2SourceTurn]] = {}
    for turn in source_turns:
        by_session.setdefault(turn.record.session_id, []).append(turn)

    exchanges: list[R2Exchange] = []
    for session_id in sorted(
        by_session, key=lambda value: by_session[value][0].record.session_index
    ):
        session_turns = by_session[session_id]
        indexes = [turn.record.turn_index for turn in session_turns]
        if indexes != list(range(1, len(session_turns) + 1)):
            raise EvidenceValidationError("R2 session turn indexes are not contiguous")
        for offset in range(0, len(session_turns), 2):
            members = tuple(session_turns[offset : offset + 2])
            first = members[0]
            exchange_index = offset // 2 + 1
            exchanges.append(
                R2Exchange(
                    exchange_id=(
                        f"ex-s{first.record.session_index:02d}-e{exchange_index:03d}"
                    ),
                    session_id=session_id,
                    session_index=first.record.session_index,
                    exchange_index=exchange_index,
                    session_date=first.record.session_date,
                    session_datetime=first.record.session_datetime,
                    relative_path=first.relative_path,
                    line_start=members[0].line_start,
                    line_end=members[-1].line_end,
                    source_turns=members,
                    search_text="\n".join(turn.search_text for turn in members),
                    display_text="\n\n".join(turn.rendered_text for turn in members),
                    canonical_index=len(exchanges) + 1,
                )
            )

    expected_turns = int(R2_PARAMETERS["expected_source_turns"])
    expected_sessions = int(R2_PARAMETERS["expected_sessions"])
    expected_odd = int(R2_PARAMETERS["expected_odd_sessions"])
    expected_exchanges = int(R2_PARAMETERS["expected_exchange_units"])
    singletons = sum(len(item.source_turns) == 1 for item in exchanges)
    flattened = [turn.record.locator for item in exchanges for turn in item.source_turns]
    if len(source_turns) != expected_turns or len(flattened) != expected_turns:
        raise EvidenceValidationError("R2 source-turn count differs from the protocol")
    if len(set(flattened)) != expected_turns or set(flattened) != store.catalog.locators:
        raise EvidenceValidationError("R2 exchange coverage is not exactly-once")
    if len(by_session) != expected_sessions or singletons != expected_odd:
        raise EvidenceValidationError("R2 session/singleton count differs from protocol")
    if len(exchanges) != expected_exchanges:
        raise EvidenceValidationError("R2 exchange count differs from protocol")
    exchange_tuple = tuple(exchanges)
    return R2RawCorpus(
        store=store,
        exchanges=exchange_tuple,
        corpus_sha256=_corpus_digest(exchange_tuple),
    )


def preflight_r2_raw_inputs(repo_root: Path) -> dict[str, object]:
    """Verify S1/S2 parity and construct both deterministic search indexes."""
    s1 = build_r2_raw_corpus(repo_root, "s1")
    s2 = build_r2_raw_corpus(repo_root, "s2")
    if len(s1.exchanges) != len(s2.exchanges):
        raise EvidenceValidationError("S1/S2 R2 exchange counts differ")
    for left, right in zip(s1.exchanges, s2.exchanges, strict=True):
        comparable_left = (
            left.exchange_id,
            left.session_id,
            left.session_date,
            left.locators,
            left.search_text,
            left.display_text,
        )
        comparable_right = (
            right.exchange_id,
            right.session_id,
            right.session_date,
            right.locators,
            right.search_text,
            right.display_text,
        )
        if comparable_left != comparable_right:
            raise EvidenceValidationError("S1/S2 R2 exchange content differs")
    # Local import avoids an input/index module cycle while ensuring that the
    # CLI preflight really constructs the full deterministic backend.
    from .r2_index import R2RawIndex

    s1_index = R2RawIndex(s1)
    s2_index = R2RawIndex(s2)
    s1_probe = s1_index.search(["Japan"])
    s2_probe = s2_index.search(["Japan"])
    probe_left = tuple(
        (
            hit.anchor.exchange_id,
            hit.exchange_rank,
            hit.session_rank,
            hit.bm25_score,
            hit.rrf_score,
        )
        for hit in s1_probe.hits
    )
    probe_right = tuple(
        (
            hit.anchor.exchange_id,
            hit.exchange_rank,
            hit.session_rank,
            hit.bm25_score,
            hit.rrf_score,
        )
        for hit in s2_probe.hits
    )
    if probe_left != probe_right:
        raise EvidenceValidationError("S1/S2 R2 deterministic index probe differs")
    return {
        "source_turns": sum(len(item.source_turns) for item in s1.exchanges),
        "sessions": len(s1.sessions),
        "singleton_exchanges": sum(
            len(item.source_turns) == 1 for item in s1.exchanges
        ),
        "exchange_units": len(s1.exchanges),
        "s1_corpus_sha256": s1.corpus_sha256,
        "s2_corpus_sha256": s2.corpus_sha256,
        "content_parity": True,
        "path_difference_count": sum(
            left.relative_path != right.relative_path
            for left, right in zip(s1.exchanges, s2.exchanges, strict=True)
        ),
        "index_documents_per_store": len(s1_index.exchanges),
        "first_search_probe": "Japan",
        "first_search_ranking_parity": True,
    }
