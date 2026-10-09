"""Deterministic fact-level BM25 + H2-group RRF backend for R3-Curated."""

from __future__ import annotations

import math
import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import date
from typing import Iterable, Sequence

from .evidence import EvidenceValidationError
from .r2_tokenizer import Tokenizer, verify_r2_tokenizer
from .r3_inputs import R3CuratedCorpus, R3FactUnit
from .r3_protocol import R3_PARAMETERS, verify_r3_protocol


_DATE_INPUT = re.compile(r"[0-9]{4}/[0-9]{2}/[0-9]{2}\Z")


@dataclass(frozen=True)
class R3SearchHit:
    result_index: int
    anchor: R3FactUnit
    context: tuple[R3FactUnit, ...]
    matched_dates: tuple[str, ...]
    bm25_score: float
    unit_rank: int
    group_score: float
    group_rank: int
    rrf_score: float

    def __post_init__(self) -> None:
        if (
            self.result_index < 1
            or self.bm25_score <= 0
            or self.group_score <= 0
            or self.rrf_score <= 0
            or self.unit_rank < 1
            or self.group_rank < 1
        ):
            raise EvidenceValidationError("R3 search hit score/rank is invalid")
        if self.anchor not in self.context:
            raise EvidenceValidationError("R3 search context omits its anchor")
        if any(item.group_id != self.anchor.group_id for item in self.context):
            raise EvidenceValidationError("R3 search context crosses an H2 group")
        if not self.matched_dates or not set(self.matched_dates).issubset(
            self.anchor.source_dates
        ):
            raise EvidenceValidationError("R3 matched dates are invalid")

    @property
    def line_start(self) -> int:
        return self.context[0].line_start

    @property
    def line_end(self) -> int:
        return self.context[-1].line_end

    @property
    def locators(self) -> tuple[str, ...]:
        return tuple(
            dict.fromkeys(
                locator for item in self.context for locator in item.source_locators
            )
        )

    @property
    def dia_ids(self) -> tuple[str, ...]:
        return tuple(
            dict.fromkeys(dia_id for item in self.context for dia_id in item.dia_ids)
        )


@dataclass(frozen=True)
class R3SearchResult:
    query_terms: tuple[str, ...]
    keywords: tuple[str, ...]
    date_from: str | None
    date_to: str | None
    excluded_groups: tuple[str, ...]
    candidate_count: int
    hits: tuple[R3SearchHit, ...]

    @property
    def returned_groups(self) -> tuple[str, ...]:
        return tuple(dict.fromkeys(hit.anchor.group_id for hit in self.hits))


def parse_r3_date(value: str | None, label: str) -> date | None:
    if value is None:
        return None
    if not isinstance(value, str) or _DATE_INPUT.fullmatch(value) is None:
        raise EvidenceValidationError(f"{label} must use YYYY/MM/DD")
    try:
        return date.fromisoformat(value.replace("/", "-"))
    except ValueError as exc:
        raise EvidenceValidationError(f"{label} is not a valid calendar date") from exc


class R3CuratedIndex:
    """Immutable global BM25 statistics and filtered H2-group RRF search."""

    def __init__(self, corpus: R3CuratedCorpus) -> None:
        verify_r3_protocol()
        verify_r2_tokenizer()
        self.corpus = corpus
        self.units = corpus.units
        self.k1 = float(R3_PARAMETERS["bm25_k1"])
        self.b = float(R3_PARAMETERS["bm25_b"])
        self.smoothing = int(R3_PARAMETERS["rrf_smoothing"])
        self.tokenizer = Tokenizer()
        self.term_frequencies: tuple[Counter[str], ...] = tuple(
            Counter(self.tokenizer.tokenize(unit.search_text)) for unit in self.units
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
        for index, unit in enumerate(self.units):
            positions[unit.group_id].append(index)
        self._group_positions = {key: tuple(value) for key, value in positions.items()}
        self._group_first_index = {
            group.group_id: group.first_canonical_index for group in corpus.groups
        }

    def _score(self, query_terms: Sequence[str], index: int) -> float:
        if not self.average_length:
            return 0.0
        frequencies = self.term_frequencies[index]
        length = self.doc_lengths[index]
        document_count = len(self.units)
        total = 0.0
        for term in query_terms:
            frequency = frequencies.get(term, 0)
            if not frequency:
                continue
            documents = self.document_frequency[term]
            inverse = math.log(
                (document_count - documents + 0.5) / (documents + 0.5) + 1.0
            )
            numerator = frequency * (self.k1 + 1.0)
            denominator = frequency + self.k1 * (
                1.0 - self.b + self.b * length / self.average_length
            )
            total += inverse * numerator / denominator
        return total

    def _context(self, index: int, window: int) -> tuple[R3FactUnit, ...]:
        anchor = self.units[index]
        positions = self._group_positions[anchor.group_id]
        group_position = positions.index(index)
        start = max(0, group_position - window)
        end = min(len(positions), group_position + window + 1)
        return tuple(self.units[item] for item in positions[start:end])

    @staticmethod
    def _matched_dates(
        unit: R3FactUnit,
        lower: date | None,
        upper: date | None,
    ) -> tuple[str, ...]:
        matched: list[str] = []
        for value in unit.source_dates:
            source_date = date.fromisoformat(value)
            if lower is not None and source_date < lower:
                continue
            if upper is not None and source_date > upper:
                continue
            matched.append(value)
        return tuple(matched)

    def search(
        self,
        keywords: Sequence[str],
        *,
        top_k: int = 5,
        context_window: int = 2,
        seen_groups: Iterable[str] = (),
        date_from: str | None = None,
        date_to: str | None = None,
    ) -> R3SearchResult:
        if not isinstance(keywords, (list, tuple)) or not keywords:
            raise EvidenceValidationError("R3 keywords must be a nonempty ordered array")
        if any(not isinstance(item, str) or not item.strip() for item in keywords):
            raise EvidenceValidationError("R3 keywords must be nonempty strings")
        if top_k != int(R3_PARAMETERS["top_k"]):
            raise EvidenceValidationError("Formal R3 top_k must be exactly 5")
        if context_window != int(R3_PARAMETERS["context_window"]):
            raise EvidenceValidationError("Formal R3 context_window must be exactly 2")
        lower = parse_r3_date(date_from, "date_from")
        upper = parse_r3_date(date_to, "date_to")
        if lower is not None and upper is not None and lower > upper:
            raise EvidenceValidationError("date_from must not be later than date_to")
        query_terms = tuple(self.tokenizer.tokenize(" ".join(keywords)))
        excluded = frozenset(seen_groups)
        known_groups = frozenset(self._group_positions)
        if any(not isinstance(item, str) or not item for item in excluded):
            raise EvidenceValidationError("seen_groups must contain nonempty strings")
        if not excluded.issubset(known_groups):
            raise EvidenceValidationError("seen_groups contains an unknown H2 group")

        candidates: list[int] = []
        matched_dates: dict[int, tuple[str, ...]] = {}
        for index, unit in enumerate(self.units):
            if unit.group_id in excluded:
                continue
            dates = self._matched_dates(unit, lower, upper)
            if not dates:
                continue
            candidates.append(index)
            matched_dates[index] = dates

        scores = {
            index: self._score(query_terms, index)
            for index in candidates
            if query_terms
        }
        scores = {index: score for index, score in scores.items() if score > 0}
        unit_order = sorted(
            scores,
            key=lambda index: (-scores[index], self.units[index].canonical_index),
        )
        unit_rank = {index: rank for rank, index in enumerate(unit_order, start=1)}

        group_scores: dict[str, float] = defaultdict(float)
        for index, score in scores.items():
            group_scores[self.units[index].group_id] += score
        group_order = sorted(
            group_scores,
            key=lambda group_id: (
                -group_scores[group_id],
                self._group_first_index[group_id],
            ),
        )
        group_rank = {
            group_id: rank for rank, group_id in enumerate(group_order, start=1)
        }
        rrf = {
            index: 1.0 / (self.smoothing + unit_rank[index])
            + 1.0 / (self.smoothing + group_rank[self.units[index].group_id])
            for index in scores
        }
        ranked = sorted(
            rrf,
            key=lambda index: (-rrf[index], self.units[index].canonical_index),
        )[:top_k]
        hits = tuple(
            R3SearchHit(
                result_index=result_index,
                anchor=self.units[index],
                context=self._context(index, context_window),
                matched_dates=matched_dates[index],
                bm25_score=scores[index],
                unit_rank=unit_rank[index],
                group_score=group_scores[self.units[index].group_id],
                group_rank=group_rank[self.units[index].group_id],
                rrf_score=rrf[index],
            )
            for result_index, index in enumerate(ranked, start=1)
        )
        return R3SearchResult(
            query_terms=query_terms,
            keywords=tuple(keywords),
            date_from=date_from,
            date_to=date_to,
            excluded_groups=tuple(sorted(excluded)),
            candidate_count=len(candidates),
            hits=hits,
        )
