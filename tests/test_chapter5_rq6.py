from __future__ import annotations

import json
import math
import tempfile
import unittest
from pathlib import Path

import fs_memory_lab.chapter5_rq6 as rq6


REPO_ROOT = Path(__file__).resolve().parents[1]


def _json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def _jsonl(path: Path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def _close(left: float, right: float) -> bool:
    return math.isclose(float(left), float(right), rel_tol=0.0, abs_tol=1e-9)


class Chapter5RQ6ArtifactTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix="chapter5-rq6-test-")
        cls.output = Path(cls.temp.name) / "rq6-quality-cost"
        cls.result = rq6.build_rq6(repo_root=REPO_ROOT, output_dir=cls.output)
        cls.tables = {name: _jsonl(cls.output / f"{name}.jsonl") for name in rq6.TABLES}
        cls.summary = _json(cls.output / "decision-summary.json")
        cls.audit = _json(cls.output / "audit.json")
        cls.marker = _json(cls.output / "RQ6.PASSED")

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def test_build_reaudit_and_exact_file_set(self):
        self.assertEqual(self.result["status"], "passed")
        audited = rq6.audit_rq6_output(repo_root=REPO_ROOT, output_dir=self.output)
        self.assertEqual(audited["audit_id"], self.audit["audit_id"])
        self.assertEqual(self.marker["audit_id"], self.audit["audit_id"])
        expected = {
            "README.md",
            "schema.json",
            "source-manifest.json",
            "decision-summary.json",
            "audit.json",
            "RQ6.PASSED",
        }
        for table in rq6.TABLES:
            expected.update({f"{table}.csv", f"{table}.jsonl"})
        self.assertEqual({path.name for path in self.output.iterdir()}, expected)

    def test_quality_cost_rows_match_frozen_main60_anchors(self):
        rows = self.tables["condition-quality-cost"]
        self.assertEqual(len(rows), 15)
        index = {(row["answer_set_id"], row["condition_id"]): row for row in rows}
        anchors = {
            ("model1-qwen-main60", "E2"): (0.403111, 0.6666666666666666, 0.7166666666666667, 18418.766666666666),
            ("model1-qwen-main60", "E5"): (0.394765, 0.7833333333333333, 0.8166666666666667, 281354.23333333334),
            ("model2-deepseek-main60", "E1"): (0.301252, 0.75, 0.8083333333333333, 201029.88333333333),
            ("model2-deepseek-main60", "E7"): (0.285368, 0.75, 0.8, 51581.05),
            ("full-context-deepseek-family-main60", rq6.FULL_CONTEXT_CONDITION): (
                0.24453945132861443,
                0.7666666666666667,
                0.825,
                36646.166666666664,
            ),
        }
        for key, expected in anchors.items():
            row = index[key]
            for field, value in zip(
                ("token_f1", "strict_accuracy", "soft_semantic_score", "mean_query_total_tokens"), expected
            ):
                # Two historical display anchors were rounded to six decimals.
                tolerance = 5e-7 if field == "token_f1" and value in {0.403111, 0.394765, 0.301252, 0.285368} else 1e-9
                self.assertTrue(math.isclose(float(row[field]), value, rel_tol=0.0, abs_tol=tolerance), (key, field))

    def test_recovery_census_is_separate_complete_where_observed_and_deduplicated(self):
        rows = self.tables["recovery-cost"]
        self.assertEqual(len(rows), 15)
        totals = {
            "attempts": sum(row["failure_attempt_count"] for row in rows),
            "known": sum(row["token_usage_known_attempts"] for row in rows),
            "unknown": sum(row["token_usage_unknown_attempts"] for row in rows),
            "provider_attempts": sum(row["known_recovery_provider_request_attempts"] for row in rows),
            "model_calls": sum(row["known_recovery_model_calls"] for row in rows),
            "tokens": sum(row["known_recovery_total_tokens"] for row in rows),
        }
        self.assertEqual(
            totals,
            {"attempts": 41, "known": 39, "unknown": 2, "provider_attempts": 390, "model_calls": 368, "tokens": 10126358},
        )
        index = {(row["answer_set_id"], row["condition_id"]): row for row in rows}
        self.assertEqual(
            (
                index[("model1-qwen-main60", "E5")]["failure_attempt_count"],
                index[("model1-qwen-main60", "E5")]["token_usage_known_attempts"],
                index[("model1-qwen-main60", "E5")]["token_usage_unknown_attempts"],
                index[("model1-qwen-main60", "E5")]["known_recovery_total_tokens"],
            ),
            (12, 10, 2, 2245594),
        )
        self.assertEqual(index[("model2-deepseek-main60", "E5")]["known_recovery_total_tokens"], 4410698)
        self.assertTrue(all(row["included_in_successful_query_cost"] is False for row in rows))

    def test_e7_incremental_and_online_cost_views_are_not_conflated(self):
        rows = self.tables["e7-cost-views"]
        self.assertEqual(len(rows), 4)
        index = {(row["answer_set_id"], row["cost_view"]): row for row in rows}
        self.assertTrue(_close(index[("model1-qwen-main60", "incremental_fused_answer")]["mean_total_tokens"], 7270.9))
        self.assertTrue(_close(index[("model1-qwen-main60", "reconstructed_online")]["mean_total_tokens"], 53636.833333333336))
        self.assertTrue(_close(index[("model2-deepseek-main60", "incremental_fused_answer")]["mean_total_tokens"], 8471.133333333333))
        self.assertTrue(_close(index[("model2-deepseek-main60", "reconstructed_online")]["mean_total_tokens"], 51581.05))

    def test_construction_cost_and_token_break_even_are_frozen(self):
        stores = {row["storage_representation"]: row for row in self.tables["store-construction-cost"]}
        self.assertEqual(stores["S1"]["construction_total_tokens"], 0)
        self.assertEqual(stores["S2"]["construction_total_tokens"], 395749)
        self.assertEqual(stores["S3"]["construction_total_tokens"], 30864958)
        finite = [row for row in self.tables["build-break-even"] if row["finite_token_break_even"]]
        self.assertEqual(len(finite), 6)
        self.assertEqual(
            {(row["backbone_id"], row["target_condition"], row["first_integer_question_after_break_even"]) for row in finite},
            {
                ("qwen", "E3", 46),
                ("qwen", "E6", 275),
                ("qwen", "E7", 324),
                ("deepseek", "E3", 35),
                ("deepseek", "E6", 187),
                ("deepseek", "E7", 207),
            },
        )

    def test_token_cost_pareto_frontiers_are_exact(self):
        rows = {
            (row["comparison_scope"], row["quality_metric"], row["cost_metric"]): row[
                "frontier_conditions_in_ascending_cost"
            ]
            for row in self.tables["pareto-frontiers"]
        }
        expected = {
            ("qwen_selective_exact", "strict_accuracy"): ["E2", "E4", "E6", "E3", "E5"],
            ("qwen_selective_exact", "soft_semantic_score"): ["E2", "E4", "E6", "E3", "E5"],
            ("qwen_selective_exact", "token_f1"): ["E2", "E3"],
            ("deepseek_selective_exact", "strict_accuracy"): ["E2", "E7"],
            ("deepseek_selective_exact", "soft_semantic_score"): ["E2", "E7", "E1"],
            ("deepseek_selective_exact", "token_f1"): ["E2", "E7", "E3", "E1"],
            ("deepseek_family_diagnostic", "strict_accuracy"): ["E2", rq6.FULL_CONTEXT_CONDITION],
            ("deepseek_family_diagnostic", "soft_semantic_score"): ["E2", rq6.FULL_CONTEXT_CONDITION],
            ("deepseek_family_diagnostic", "token_f1"): ["E2", "E7", "E3", "E1"],
        }
        for (scope, metric), frontier in expected.items():
            self.assertEqual(rows[(scope, metric, "mean_query_total_tokens")], frontier)

    def test_decision_summary_is_conditional_and_respects_boundaries(self):
        self.assertIn("No single condition is best", self.summary["rq6_direct_answer"])
        self.assertIn("E2 is the lowest-token path", self.summary["rq6_direct_answer"])
        finding_ids = {row["finding_id"] for row in self.summary["findings"]}
        self.assertEqual(
            finding_ids,
            {
                "cost_first",
                "qwen_quality",
                "deepseek_selective_balance",
                "full_context_boundary",
                "construction_amortisation",
                "recovery_overhead",
                "bottleneck_implication",
            },
        )
        manifest = _json(self.output / "source-manifest.json")
        self.assertFalse(manifest["boundaries"]["full_context_exact_served_model_match"])
        self.assertFalse(manifest["boundaries"]["recovery_token_usage_complete"])
        self.assertFalse(self.audit["cross_condition_latency_ranking_computed"])
        self.assertFalse(self.audit["monetary_ranking_computed"])

    def test_public_tables_do_not_include_content_fields(self):
        for name in rq6.TABLES:
            for row in self.tables[name]:
                self.assertTrue(rq6.FORBIDDEN_FIELDS.isdisjoint(row), (name, set(row) & rq6.FORBIDDEN_FIELDS))

    def test_z_output_mutation_fails_closed(self):
        path = self.output / "decision-summary.json"
        original = path.read_bytes()
        try:
            path.write_bytes(original + b"\n")
            with self.assertRaises(Exception):
                rq6.audit_rq6_output(repo_root=REPO_ROOT, output_dir=self.output)
        finally:
            path.write_bytes(original)
        self.assertEqual(rq6.audit_rq6_output(repo_root=REPO_ROOT, output_dir=self.output)["status"], "passed")


if __name__ == "__main__":
    unittest.main()
