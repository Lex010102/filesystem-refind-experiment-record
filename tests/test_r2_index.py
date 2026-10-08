import unittest
import math
from pathlib import Path

from fs_memory_lab.evidence import EvidenceValidationError
from fs_memory_lab.r2_index import R2RawIndex, parse_r2_date
from fs_memory_lab.r2_inputs import build_r2_raw_corpus
from fs_memory_lab.r2_tokenizer import (
    R2_TOKENIZER_SOURCE_SHA256,
    Tokenizer,
    tokenizer_source_sha256,
    verify_r2_tokenizer,
)


ROOT = Path(__file__).resolve().parents[1]


class R2IndexTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.s1_corpus = build_r2_raw_corpus(ROOT, "s1")
        cls.s2_corpus = build_r2_raw_corpus(ROOT, "s2")
        cls.s1 = R2RawIndex(cls.s1_corpus)
        cls.s2 = R2RawIndex(cls.s2_corpus)

    def test_official_tokenizer_is_byte_frozen(self) -> None:
        verify_r2_tokenizer()
        self.assertEqual(tokenizer_source_sha256(), R2_TOKENIZER_SOURCE_SHA256)
        self.assertEqual(
            Tokenizer().tokenize("The cats were running happily."),
            ["cat", "runn", "happili"],
        )

    def test_first_search_ranking_is_identical_for_s1_s2(self) -> None:
        left = self.s1.search(["Japan", "music"])
        right = self.s2.search(["Japan", "music"])
        self.assertEqual(
            [(hit.anchor.exchange_id, hit.rrf_score) for hit in left.hits],
            [(hit.anchor.exchange_id, hit.rrf_score) for hit in right.hits],
        )
        self.assertNotEqual(
            [hit.anchor.relative_path for hit in left.hits],
            [hit.anchor.relative_path for hit in right.hits],
        )

    def test_bm25_score_and_session_sum_match_the_frozen_formula(self) -> None:
        result = self.s1.search(["Japan"])
        hit = result.hits[0]
        index = self.s1.exchanges.index(hit.anchor)
        term = self.s1.tokenizer.tokenize("Japan")[0]
        frequency = self.s1.term_frequencies[index][term]
        documents = self.s1.document_frequency[term]
        count = len(self.s1.exchanges)
        length = self.s1.doc_lengths[index]
        inverse = math.log((count - documents + 0.5) / (documents + 0.5) + 1.0)
        expected = inverse * frequency * (self.s1.k1 + 1.0) / (
            frequency
            + self.s1.k1
            * (1.0 - self.s1.b + self.s1.b * length / self.s1.average_length)
        )
        self.assertAlmostEqual(hit.bm25_score, expected)
        session_total = sum(
            self.s1._score((term,), candidate)
            for candidate, exchange in enumerate(self.s1.exchanges)
            if exchange.session_id == hit.anchor.session_id
            and self.s1._score((term,), candidate) > 0
        )
        self.assertAlmostEqual(hit.session_score, session_total)
        self.assertAlmostEqual(
            hit.rrf_score,
            1.0 / (60 + hit.exchange_rank) + 1.0 / (60 + hit.session_rank),
        )

    def test_date_filter_is_inclusive_and_strict(self) -> None:
        result = self.s1.search(
            ["music"], date_from="2023/08/11", date_to="2023/08/11"
        )
        self.assertTrue(result.hits)
        self.assertTrue(
            all(hit.anchor.session_date == "2023-08-11" for hit in result.hits)
        )
        with self.assertRaises(EvidenceValidationError):
            parse_r2_date("2023-08-11", "date_from")
        with self.assertRaises(EvidenceValidationError):
            self.s1.search(["music"], date_from="2023/09/01", date_to="2023/08/01")

    def test_seen_session_filter_precedes_ranking(self) -> None:
        first = self.s1.search(["Japan"])
        self.assertTrue(first.hits)
        excluded = set(first.returned_sessions)
        second = self.s1.search(["Japan"], seen_sessions=excluded)
        self.assertTrue(
            all(hit.anchor.session_id not in excluded for hit in second.hits)
        )

    def test_context_is_exchange_window_and_never_crosses_session(self) -> None:
        result = self.s1.search(["Japan"])
        for hit in result.hits:
            self.assertLessEqual(len(hit.context), 5)
            self.assertTrue(
                all(item.session_id == hit.anchor.session_id for item in hit.context)
            )
            indexes = [item.exchange_index for item in hit.context]
            self.assertEqual(indexes, list(range(indexes[0], indexes[-1] + 1)))

    def test_top_k_and_window_are_frozen(self) -> None:
        with self.assertRaises(EvidenceValidationError):
            self.s1.search(["Japan"], top_k=4)
        with self.assertRaises(EvidenceValidationError):
            self.s1.search(["Japan"], context_window=1)


if __name__ == "__main__":
    unittest.main()
