from __future__ import annotations

import csv
import json
import tempfile
import unittest
from collections import Counter
from pathlib import Path

import fs_memory_lab.chapter5_rq5_evaluation as evaluation


REPO_ROOT = Path(__file__).resolve().parents[1]


class Chapter5RQ5EvaluationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.work = tempfile.TemporaryDirectory(prefix=".rq5-evaluation-test-", dir=REPO_ROOT)
        cls.work_dir = Path(cls.work.name)
        cls.output = cls.work_dir / "audit"
        cls.review = REPO_ROOT / evaluation.DEFAULT_REVIEW_PATH
        cls.result = evaluation.build_rq5_evaluation(
            repo_root=REPO_ROOT,
            review_path=cls.review,
            output_dir=cls.output,
        )

    @classmethod
    def tearDownClass(cls):
        cls.work.cleanup()

    def _csv(self, name):
        with (self.output / f"{name}.csv").open(newline="", encoding="utf-8") as handle:
            return list(csv.DictReader(handle))

    def test_formal_build_and_independent_audit_pass(self):
        self.assertEqual(self.result["status"], "passed")
        self.assertEqual(self.result["population_rows"], 900)
        self.assertEqual(self.result["screened_rows"], 168)
        self.assertEqual(self.result["review_family_count"], 18)
        audited = evaluation.audit_rq5_evaluation(
            repo_root=REPO_ROOT,
            review_path=self.review,
            output_dir=self.output,
        )
        self.assertEqual(audited["audit_id"], self.result["audit_id"])

    def test_frozen_label_and_screen_denominators(self):
        distributions = {row["judge_group"]: row for row in self._csv("score-distributions")}
        self.assertEqual({key: int(distributions[key]["n"]) for key in ("correct", "partial", "incorrect")},
                         {"correct": 650, "partial": 74, "incorrect": 176})
        cases = self._csv("disagreement-cases")
        self.assertEqual(
            Counter(row["screen_id"] for row in cases),
            Counter({
                "correct_low_f1": 92,
                "partial_low_f1": 31,
                "partial_high_f1": 11,
                "incorrect_nontrivial_f1": 34,
            }),
        )

    def test_screen_threshold_boundaries_are_explicit(self):
        self.assertIsNone(evaluation._screen({"judge_label": "correct", "token_f1": 0.10}))
        self.assertEqual(
            evaluation._screen({"judge_label": "correct", "token_f1": 0.099999}),
            "correct_low_f1",
        )
        self.assertEqual(
            evaluation._screen({"judge_label": "partial", "token_f1": 0.50}),
            "partial_high_f1",
        )
        self.assertIsNone(evaluation._screen({"judge_label": "incorrect", "token_f1": 0.099999}))
        self.assertEqual(
            evaluation._screen({"judge_label": "incorrect", "token_f1": 0.10}),
            "incorrect_nontrivial_f1",
        )

    def test_manual_review_matches_the_registered_cause_partition(self):
        cases = self._csv("disagreement-cases")
        under_credit = sum(row["interpretation_group"] == "lexical_under_credit" for row in cases)
        over_credit = sum(row["interpretation_group"] == "lexical_over_credit" for row in cases)
        genuine_partial = sum(
            row["interpretation_group"] in {
                "genuine_partial_answer", "answer_form_partial", "reference_or_annotation_sensitive"
            }
            for row in cases
        )
        reference_or_judge = sum(
            row["interpretation_group"] == "reference_or_judge_sensitive" for row in cases
        )
        self.assertEqual((under_credit, over_credit, genuine_partial, reference_or_judge), (87, 18, 22, 25))

    def test_exact_input_check_is_bounded_and_conflict_free(self):
        first = self._csv("exact-input-consistency")[0]
        self.assertEqual(int(first["group_count"]), 80)
        self.assertEqual(int(first["record_count"]), 305)
        self.assertEqual(int(first["conflict_group_count"]), 0)
        self.assertIn("does not establish", first["interpretation"])

    def test_public_artifacts_exclude_content_and_rationales(self):
        for path in self.output.iterdir():
            if path.suffix not in {".json", ".jsonl", ".csv"}:
                continue
            payload = path.read_text(encoding="utf-8").lower()
            for field in ('"question"', '"candidate_answer"', '"reference_answer"', '"evidence"', '"short_reason"'):
                self.assertNotIn(field, payload, f"forbidden field leaked in {path.name}")

    def test_tampered_artifact_is_rejected(self):
        path = self.output / "cause-summary.csv"
        original = path.read_bytes()
        path.write_bytes(original + b"\n")
        try:
            with self.assertRaises(Exception):
                evaluation.audit_rq5_evaluation(
                    repo_root=REPO_ROOT,
                    review_path=self.review,
                    output_dir=self.output,
                )
        finally:
            path.write_bytes(original)

    def test_architecture_sensitivity_keeps_major_directions_visible(self):
        rows = self._csv("metric-sensitive-architecture")
        self.assertEqual(len(rows), 17)
        by_key = {(row["comparison_id"], row["backbone_id"]): row for row in rows}
        for key in (
            ("retrieval_s2_e4_minus_e3", "qwen"),
            ("retrieval_s2_e4_minus_e3", "deepseek"),
            ("curated_access_e6_minus_e5", "qwen"),
            ("curated_access_e6_minus_e5", "deepseek"),
        ):
            self.assertEqual(by_key[key]["f1_direction"], "negative")
            self.assertEqual(by_key[key]["strict_direction"], "negative")
            self.assertEqual(by_key[key]["f1_direction_preserved"], "True")
            self.assertEqual(by_key[key]["strict_direction_preserved"], "True")

    def test_two_clean_builds_are_byte_identical(self):
        second = self.work_dir / "audit-second"
        evaluation.build_rq5_evaluation(
            repo_root=REPO_ROOT,
            review_path=self.review,
            output_dir=second,
        )
        self.assertEqual(
            {path.name for path in self.output.iterdir()},
            {path.name for path in second.iterdir()},
        )
        for path in self.output.iterdir():
            self.assertEqual(path.read_bytes(), (second / path.name).read_bytes(), path.name)


if __name__ == "__main__":
    unittest.main()
