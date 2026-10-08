"""Deterministic exchange-level BM25 + session-RRF backend for R2-Raw."""

from __future__ import annotations

import math
import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import date
from typing import Iterable, Sequence

from .evidence import EvidenceValidationError
from .r2_inputs import R2Exchange, R2RawCorpus
from .r2_protocol import R2_PARAMETERS, verify_r2_protocol
from .r2_tokenizer import Tokenizer, verify_r2_tokenizer


_DATE_INPUT = re.compile(r"[0-9]{4}/[0-9]{2}/[0-9]{2}\Z")


@dataclass(frozen=True)
class R2SearchHit:
    result_index: int
    anchor: R2Exchange
    context: tuple[R2Exchange, ...]
    bm25_score: float
    exchange_rank: int
    session_score: float
    session_rank: int
    rrf_score: float

    def __post_init__(self) -> None:
        if self.result_index < 1 or self.bm25_score <= 0 or self.rrf_score <= 0:
            raise EvidenceValidationError("R2 search hit score/index is invalid")
        if self.anchor not in self.context:
            raise EvidenceValidationError("R2 search context omits its anchor")
        if any(item.session_id != self.anchor.session_id for item in self.context):
            raise EvidenceValidationError("R2 search context crosses a session")

    @property
    def line_start(self) -> int:
        return self.context[0].line_start

    @property
    def line_end(self) -> int:
        return self.context[-1].line_end

    @property
    def locators(self) -> tuple[str, ...]:
        return tuple(locator for item in self.context for locator in item.locators)


@dataclass(frozen=True)
class R2SearchResult:
    query_terms: tuple[str, ...]
    keywords: tuple[str, ...]
    date_from: str | None
    date_to: str | None
    excluded_sessions: tuple[str, ...]
    candidate_count: int
    hits: tuple[R2SearchHit, ...]

    @property
    def returned_sessions(self) -> tuple[str, ...]:
        return tuple(dict.fromkeys(hit.anchor.session_id for hit in self.hits))


def parse_r2_date(value: str | None, label: str) -> date | None:
    if value is None:
        return None
    if not isinstance(value, str) or _DATE_INPUT.fullmatch(value) is None:
        raise EvidenceValidationError(f"{label} must use YYYY/MM/DD")
    try:
        return date.fromisoformat(value.replace("/", "-"))
    except ValueError as exc:
        raise EvidenceValidationError(f"{label} is not a valid calendar date") from exc


class R2RawIndex:
    """Immutable full-corpus BM25 statistics with pre-ranking candidate filters."""

    def __init__(self, corpus: R2RawCorpus) -> None:
        verify_r2_protocol()
        verify_r2_tokenizer()
        self.corpus = corpus
        self.exchanges = corpus.exchanges
        self.k1 = float(R2_PARAMETERS["bm25_k1"])
        self.b = float(R2_PARAMETERS["bm25_b"])
        self.smoothing = int(R2_PARAMETERS["rrf_smoothing"])
        self.tokenizer = Tokenizer()
        self.term_frequencies: tuple[Counter[str], ...] = tuple(
            Counter(self.tokenizer.tokenize(item.search_text)) for item in self.exchanges
        )
        self.doc_lengths = tuple(sum(counts.values()) for counts in self.term_frequencies)
        document_frequency: dict[str, int] = defaultdict(int)
        for counts in self.term_frequencies:
            for term in counts:
                document_frequency[term] += 1
        self.document_frequency = dict(document_frequency)
        self.average_length = (
            sum(self.doc_lengths) / len(self.doc_lengths) if self.doc_lengths else 0.0
        )
        positions: dict[str, list[int]] = defaultdict(list)
        for index, exchange in enumerate(self.exchanges):
            positions[exchange.session_id].append(index)
        self._session_positions = {
            key: tuple(value) for key, value in positions.items()
        }

    def _score(self, query_terms: Sequence[str], index: int) -> float:
        if not self.average_length:
            return 0.0
        frequencies = self.term_frequencies[index]
        length = self.doc_lengths[index]
        count = len(self.exchanges)
        total = 0.0
        for term in query_terms:
            frequency = frequencies.get(term, 0)
            if not frequency:
                continue
            documents = self.document_frequency[term]
            inverse = math.log(
                (count - documents + 0.5) / (documents + 0.5) + 1.0
            )
            numerator = frequency * (self.k1 + 1.0)
            denominator = frequency + self.k1 * (
                1.0 - self.b + self.b * length / self.average_length
            )
            total += inverse * numerator / denominator
        return total

    def _context(self, index: int, window: int) -> tuple[R2Exchange, ...]:
        anchor = self.exchanges[index]
        positions = self._session_positions[anchor.session_id]
        position = positions.index(index)
        start = max(0, position - window)
        end = min(len(positions), position + window + 1)
        return tuple(self.exchanges[item] for item in positions[start:end])

    def search(
        self,
        keywords: Sequence[str],
        *,
        top_k: int = 5,
        context_window: int = 2,
        seen_sessions: Iterable[str] = (),
        date_from: str | None = None,
        date_to: str | None = None,
    ) -> R2SearchResult:
        if not isinstance(keywords, (list, tuple)) or not keywords:
            raise EvidenceValidationError("R2 keywords must be a nonempty ordered array")
        if any(not isinstance(item, str) or not item.strip() for item in keywords):
            raise EvidenceValidationError("R2 keywords must be nonempty strings")
        if top_k != int(R2_PARAMETERS["top_k"]):
            raise EvidenceValidationError("Formal R2-Raw top_k must be exactly 5")
        if context_window != int(R2_PARAMETERS["context_window"]):
            raise EvidenceValidationError("Formal R2-Raw context_window must be exactly 2")
        lower = parse_r2_date(date_from, "date_from")
        upper = parse_r2_date(date_to, "date_to")
        if lower is not None and upper is not None and lower > upper:
            raise EvidenceValidationError("date_from must not be later than date_to")
        query_terms = tuple(self.tokenizer.tokenize(" ".join(keywords)))
        excluded = frozenset(seen_sessions)
        if any(not isinstance(item, str) or not item for item in excluded):
            raise EvidenceValidationError("seen_sessions must contain nonempty strings")

        candidates: list[int] = []
        for index, exchange in enumerate(self.exchanges):
            session_date = date.fromisoformat(exchange.session_date)
            if exchange.session_id in excluded:
                continue
            if lower is not None and session_date < lower:
                continue
            if upper is not None and session_date > upper:
                continue
            candidates.append(index)

        scores = {
            index: self._score(query_terms, index)
            for index in candidates
            if query_terms
        }
        scores = {index: score for index, score in scores.items() if score > 0}
        exchange_order = sorted(
            scores, key=lambda index: (-scores[index], self.exchanges[index].canonical_index)
        )
        exchange_rank = {
            index: rank for rank, index in enumerate(exchange_order, start=1)
        }
        session_scores: dict[str, float] = defaultdict(float)
        for index, score in scores.items():
            session_scores[self.exchanges[index].session_id] += score
        session_first_index = {
            session_id: min(
                self.exchanges[index].canonical_index
                for index in scores
                if self.exchanges[index].session_id == session_id
            )
            for session_id in session_scores
        }
        session_order = sorted(
            session_scores,
            key=lambda session_id: (
                -session_scores[session_id],
                session_first_index[session_id],
            ),
        )
        session_rank = {
            session_id: rank for rank, session_id in enumerate(session_order, start=1)
        }
        rrf = {
            index: 1.0 / (self.smoothing + exchange_rank[index])
            + 1.0
            / (
                self.smoothing
                + session_rank[self.exchanges[index].session_id]
            )
            for index in scores
        }
        ranked = sorted(
            rrf, key=lambda index: (-rrf[index], self.exchanges[index].canonical_index)
        )[:top_k]
        hits = tuple(
            R2SearchHit(
                result_index=result_index,
                anchor=self.exchanges[index],
                context=self._context(index, context_window),
                bm25_score=scores[index],
                exchange_rank=exchange_rank[index],
                session_score=session_scores[self.exchanges[index].session_id],
                session_rank=session_rank[self.exchanges[index].session_id],
                rrf_score=rrf[index],
            )
            for result_index, index in enumerate(ranked, start=1)
        )
        return R2SearchResult(
            query_terms=query_terms,
            keywords=tuple(keywords),
            date_from=date_from,
            date_to=date_to,
            excluded_sessions=tuple(sorted(excluded)),
            candidate_count=len(candidates),
            hits=hits,
        )
