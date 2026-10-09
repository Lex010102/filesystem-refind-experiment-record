import unittest
from pathlib import Path

from fs_memory_lab.r3_inputs import (
    FROZEN_R3_CORPUS_SHA256,
    load_r3_corpus,
    preflight_r3_inputs,
)


ROOT = Path(__file__).resolve().parents[1]


class R3InputTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.corpus = load_r3_corpus(ROOT)

    def test_frozen_corpus_identity_and_counts(self) -> None:
        corpus = self.corpus
        self.assertEqual(corpus.corpus_sha256, FROZEN_R3_CORPUS_SHA256)
        self.assertEqual(corpus.store.verified_manifest.file_paths, ("calvin.md", "dave.md"))
        self.assertEqual(
            corpus.stats.to_dict(),
            {
                "file_count": 2,
                "total_bytes": 304640,
                "total_lines": 472,
                "h1_count": 2,
                "h2_group_count": 35,
                "fact_unit_count": 390,
                "nested_fact_unit_count": 3,
                "body_locator_mentions": 1459,
                "unique_body_locators": 555,
                "source_locator_count": 568,
                "missing_source_locator_count": 13,
                "frontmatter_locator_mentions_excluded": 6,
            },
        )

    def test_stable_document_order_and_boundaries(self) -> None:
        corpus = self.corpus
        first = corpus.units[0]
        last = corpus.units[-1]
        self.assertEqual(first.unit_id, "fact-f01-h001-u001")
        self.assertEqual(first.group_id, "calvin.md::h2-001")
        self.assertEqual((first.line_start, first.line_end), (9, 9))
        self.assertEqual(last.unit_id, "fact-f02-h017-u053")
        self.assertEqual(last.group_id, "dave.md::h2-017")
        self.assertEqual((last.line_start, last.line_end), (225, 225))
        self.assertEqual(corpus.groups[0].h2_heading, "New home (2023-03-23)")
        self.assertEqual(corpus.groups[-1].h2_heading, "Relationships")
        self.assertEqual(max(len(group.unit_ids) for group in corpus.groups), 53)

    def test_fact_schema_and_canonical_attribution(self) -> None:
        corpus = self.corpus
        for unit in corpus.units:
            self.assertNotIn("---", unit.search_text)
            self.assertNotRegex(unit.search_text, r"\[S[1-9][0-9]*T[1-9][0-9]*\]")
            self.assertEqual(len(unit.source_locators), len(unit.dia_ids))
            for locator, dia_id in zip(unit.source_locators, unit.dia_ids):
                self.assertEqual(corpus.store.catalog.resolve(locator).dia_id, dia_id)
            self.assertEqual(tuple(sorted(set(unit.source_dates))), unit.source_dates)
            self.assertTrue(unit.search_text.startswith(f"{unit.entity_name}\n{unit.h2_heading}\n"))

    def test_nested_items_remain_independent_units(self) -> None:
        nested = [unit for unit in self.corpus.units if unit.nested]
        self.assertEqual(
            [unit.unit_id for unit in nested],
            [
                "fact-f02-h011-u003",
                "fact-f02-h011-u004",
                "fact-f02-h011-u005",
            ],
        )
        self.assertTrue(all(unit.indentation == 2 for unit in nested))

    def test_frontmatter_is_not_indexed(self) -> None:
        corpus = self.corpus
        self.assertTrue(all(unit.line_start >= 9 for unit in corpus.units))
        self.assertFalse(any(unit.h2_heading == "description" for unit in corpus.units))
        self.assertEqual(corpus.stats.frontmatter_locator_mentions_excluded, 6)

    def test_locator_coverage_is_explicit(self) -> None:
        indexed = {locator for unit in self.corpus.units for locator in unit.source_locators}
        missing = self.corpus.store.catalog.locators - indexed
        self.assertEqual(len(indexed), 555)
        self.assertEqual(len(missing), 13)
        self.assertEqual(len(indexed | missing), 568)

    def test_preflight_summary(self) -> None:
        summary = preflight_r3_inputs(ROOT)
        self.assertEqual(summary["corpus_sha256"], FROZEN_R3_CORPUS_SHA256)
        self.assertEqual(summary["group_size_min"], 1)
        self.assertEqual(summary["group_size_max"], 53)
        self.assertEqual(summary["fact_chars_max"], 7740)


if __name__ == "__main__":
    unittest.main()
