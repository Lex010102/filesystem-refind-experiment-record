import unittest
from pathlib import Path

from fs_memory_lab.r2_inputs import build_r2_raw_corpus, preflight_r2_raw_inputs


ROOT = Path(__file__).resolve().parents[1]


class R2InputTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.s1 = build_r2_raw_corpus(ROOT, "s1")
        cls.s2 = build_r2_raw_corpus(ROOT, "s2")

    def test_frozen_exchange_counts(self) -> None:
        self.assertEqual(len(self.s1.exchanges), 292)
        self.assertEqual(len(self.s1.sessions), 30)
        self.assertEqual(
            sum(len(item.source_turns) == 1 for item in self.s1.exchanges), 16
        )
        self.assertEqual(
            sum(len(item.source_turns) for item in self.s1.exchanges), 568
        )

    def test_each_source_turn_occurs_once(self) -> None:
        locators = [
            turn.record.locator
            for exchange in self.s1.exchanges
            for turn in exchange.source_turns
        ]
        self.assertEqual(len(locators), len(set(locators)))
        self.assertEqual(set(locators), self.s1.store.catalog.locators)

    def test_search_text_excludes_provenance(self) -> None:
        for exchange in self.s1.exchanges:
            self.assertNotIn("dia_id:", exchange.search_text)
            for turn in exchange.source_turns:
                self.assertNotIn(turn.record.locator, exchange.search_text)
            self.assertNotIn(exchange.relative_path, exchange.search_text)

    def test_s1_s2_content_is_identical_but_paths_differ(self) -> None:
        result = preflight_r2_raw_inputs(ROOT)
        self.assertTrue(result["content_parity"])
        self.assertEqual(result["path_difference_count"], 292)
        self.assertEqual(result["index_documents_per_store"], 292)
        self.assertTrue(result["first_search_ranking_parity"])

    def test_pairing_is_adjacent_and_does_not_cross_sessions(self) -> None:
        for exchange in self.s1.exchanges:
            turns = exchange.source_turns
            self.assertTrue(all(t.record.session_id == exchange.session_id for t in turns))
            if len(turns) == 2:
                self.assertEqual(
                    turns[1].record.turn_index, turns[0].record.turn_index + 1
                )


if __name__ == "__main__":
    unittest.main()
