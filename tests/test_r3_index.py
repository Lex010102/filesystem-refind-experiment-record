import unittest
from pathlib import Path

from fs_memory_lab.evidence import EvidenceValidationError
from fs_memory_lab.r3_index import R3CuratedIndex
from fs_memory_lab.r3_inputs import load_r3_corpus


ROOT = Path(__file__).resolve().parents[1]


class R3IndexTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.corpus = load_r3_corpus(ROOT)
        cls.index = R3CuratedIndex(cls.corpus)

    def test_search_is_deterministic_top5(self) -> None:
        left = self.index.search(["octopus", "guitar"])
        right = self.index.search(["octopus", "guitar"])
        self.assertEqual(len(left.hits), 5)
        self.assertEqual(
            [(hit.anchor.unit_id, hit.rrf_score) for hit in left.hits],
            [(hit.anchor.unit_id, hit.rrf_score) for hit in right.hits],
        )
        self.assertTrue(all(hit.anchor in hit.context for hit in left.hits))

    def test_group_aggregate_and_rrf_formula(self) -> None:
        result = self.index.search(["music", "artist"])
        self.assertTrue(result.hits)
        for hit in result.hits:
            expected = 1 / (60 + hit.unit_rank) + 1 / (60 + hit.group_rank)
            self.assertAlmostEqual(hit.rrf_score, expected)
            self.assertGreaterEqual(hit.group_score, hit.bm25_score)

    def test_context_stops_at_h2_boundary(self) -> None:
        result = self.index.search(["mansion"])
        for hit in result.hits:
            self.assertLessEqual(len(hit.context), 5)
            self.assertTrue(all(unit.group_id == hit.anchor.group_id for unit in hit.context))
            indexes = [unit.canonical_index for unit in hit.context]
            self.assertEqual(indexes, list(range(indexes[0], indexes[-1] + 1)))

    def test_seen_group_filter_precedes_ranking(self) -> None:
        first = self.index.search(["octopus", "guitar"])
        excluded = first.returned_groups
        second = self.index.search(["octopus", "guitar"], seen_groups=excluded)
        self.assertTrue(set(second.returned_groups).isdisjoint(excluded))
        self.assertLess(second.candidate_count, first.candidate_count)

    def test_multi_date_filter_uses_set_overlap(self) -> None:
        result = self.index.search(
            ["music"], date_from="2023/11/17", date_to="2023/11/17"
        )
        self.assertTrue(result.hits)
        self.assertTrue(
            all("2023-11-17" in hit.matched_dates for hit in result.hits)
        )
        self.assertTrue(
            all(
                any(date == "2023-11-17" for date in hit.anchor.source_dates)
                for hit in result.hits
            )
        )

    def test_empty_and_invalid_requests_fail_closed(self) -> None:
        with self.assertRaises(EvidenceValidationError):
            self.index.search([])
        with self.assertRaises(EvidenceValidationError):
            self.index.search(["music"], top_k=4)
        with self.assertRaises(EvidenceValidationError):
            self.index.search(["music"], date_from="2023-11-17")
        with self.assertRaises(EvidenceValidationError):
            self.index.search(["music"], seen_groups=["unknown::h2-001"])

    def test_no_match_is_explicit(self) -> None:
        result = self.index.search(["zzzznotpresenttokenzzzz"])
        self.assertEqual(result.hits, ())
        self.assertEqual(result.candidate_count, 390)


if __name__ == "__main__":
    unittest.main()
