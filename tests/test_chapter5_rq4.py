import csv
import hashlib
import json
import math
import shutil
import tempfile
import unittest
from collections import Counter
from pathlib import Path

from fs_memory_lab.chapter5_rq4 import (
    FULL_CONTEXT_CONDITION,
    SELECTIVE_CONDITIONS,
    STAGE_RQ4_PROTOCOL_VERSION,
    audit_rq4_output,
    build_rq4,
)


REPO_ROOT = Path(__file__).resolve().parents[1]
STAGE_A = REPO_ROOT / "artifacts/chapter5-main60-analysis-v1/stage-a"
FLOAT_TOLERANCE = 1e-12

TABLES = (
    "condition-summaries",
    "condition-comparisons",
    "question-quadrants",
    "quadrant-summary",
    "category-comparisons",
    "judge-transitions",
    "table-5-15-inputs",
    "figure-5-8-inputs",
    "rq5-candidate-cases",
)

EXPECTED_SUMMARIES = {
    FULL_CONTEXT_CONDITION: (0.1680173357965427, 0.729637445887446, 0.24453945132861443, 0.7666666666666667, 0.11666666666666667, 0.825),
    "E1": (0.2345278292824486, 0.7002669552669553, 0.3012519451505862, 0.75, 0.11666666666666667, 0.8083333333333333),
    "E2": (0.17201537508840695, 0.7023106060606061, 0.24552240773308748, 0.7, 0.016666666666666666, 0.7083333333333334),
    "E3": (0.23154572270046622, 0.6823629148629149, 0.29711169281055716, 0.7, 0.11666666666666667, 0.7583333333333333),
    "E4": (0.16303626348861605, 0.6503661616161617, 0.23142217876296317, 0.6666666666666666, 0.08333333333333333, 0.7083333333333334),
    "E5": (0.19301205313301492, 0.7389357864357865, 0.2603689457037844, 0.75, 0.1, 0.8),
    "E6": (0.16304507249148828, 0.6083748196248195, 0.22397219793116943, 0.6666666666666666, 0.08333333333333333, 0.7083333333333334),
    "E7": (0.21284029019901327, 0.7363636363636363, 0.2853678459567019, 0.75, 0.1, 0.8),
}

EXPECTED_STRICT_QUADRANTS = {
    "E1": (42, 4, 3, 11),
    "E2": (39, 7, 3, 11),
    "E3": (41, 5, 1, 13),
    "E4": (38, 8, 2, 12),
    "E5": (43, 3, 2, 12),
    "E6": (38, 8, 2, 12),
    "E7": (42, 4, 3, 11),
}

EXPECTED_F1_WTL = {
    "E1": (19, 14, 27),
    "E2": (22, 17, 21),
    "E3": (18, 16, 26),
    "E4": (20, 15, 25),
    "E5": (27, 9, 24),
    "E6": (30, 15, 15),
    "E7": (19, 16, 25),
}

EXPECTED_E7_CATEGORY = {
    1: {
        "metrics": (0.15197288092024935, 0.7025641025641025, 0.23657443878267678, 0.8461538461538461, 0.07692307692307693, 0.8846153846153846),
        "quadrants": (8, 3, 1, 1),
    },
    2: {
        "metrics": (0.21658690850387766, 0.658974358974359, 0.26360864410400014, 0.7692307692307693, 0.07692307692307693, 0.8076923076923077),
        "quadrants": (10, 0, 1, 2),
    },
    3: {
        "metrics": (0.032027356397104294, 0.6428571428571429, 0.06079216261958992, 0.42857142857142855, 0.14285714285714285, 0.5),
        "quadrants": (2, 1, 0, 4),
    },
    4: {
        "metrics": (0.1876137552036734, 0.7991943241943241, 0.2868311801427013, 0.8148148148148148, 0.14814814814814814, 0.8888888888888888),
        "quadrants": (22, 0, 1, 4),
    },
}

FORBIDDEN_FIELDS = {
    "question",
    "question_text",
    "reference_answer",
    "candidate_answer",
    "answer",
    "answer_text",
    "gold_answer",
    "evidence",
    "evidence_text",
    "retrieved_text",
    "judge_reason",
    "short_reason",
    "prompt",
    "response",
    "api_key",
    "authorization",
}


def _json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def _jsonl(path: Path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _close(left: float, right: float) -> bool:
    return math.isclose(float(left), float(right), rel_tol=0.0, abs_tol=FLOAT_TOLERANCE)


def _kwargs(output_dir: Path):
    return {"repo_root": REPO_ROOT, "stage_a_dir": STAGE_A, "output_dir": output_dir}


class Chapter5RQ4ArtifactTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix="chapter5-rq4-test-")
        cls.output = Path(cls.temp.name) / "rq4-full-context"
        cls.build_result = build_rq4(**_kwargs(cls.output))
        cls.audit = _json(cls.output / "audit.json")
        cls.marker = _json(cls.output / "RQ4.PASSED")
        cls.manifest = _json(cls.output / "source-manifest.json")
        cls.tables = {name: _jsonl(cls.output / f"{name}.jsonl") for name in TABLES}
        cls.source_rows = _jsonl(STAGE_A / "master-table.jsonl")

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def test_normal_build_independent_audit_hashes_and_exact_file_set(self):
        self.assertEqual(self.build_result["status"], "passed")
        self.assertEqual(self.build_result["protocol_version"], STAGE_RQ4_PROTOCOL_VERSION)
        audited = audit_rq4_output(**_kwargs(self.output))
        self.assertEqual(audited["status"], "passed")
        self.assertEqual(audited["audit_id"], self.audit["audit_id"])
        self.assertEqual(self.marker["audit_id"], self.audit["audit_id"])
        self.assertEqual(self.marker["audit_sha256"], _sha256(self.output / "audit.json"))
        for name, digest in self.audit["output_sha256"].items():
            self.assertEqual(_sha256(self.output / name), digest, name)

        expected = {"README.md", "schema.json", "source-manifest.json", "audit.json", "RQ4.PASSED"}
        for table in TABLES:
            expected.update({f"{table}.csv", f"{table}.jsonl"})
        self.assertEqual({path.name for path in self.output.iterdir()}, expected)

    def test_frozen_input_scope_pairing_and_model_identity(self):
        self.assertEqual(len(self.source_rows), 900)
        selective = [
            row
            for row in self.source_rows
            if row["answer_set_id"] == "model2-deepseek-main60" and row["condition_id"] in SELECTIVE_CONDITIONS
        ]
        full_context = [
            row
            for row in self.source_rows
            if row["answer_set_id"] == "full-context-deepseek-family-main60"
        ]
        self.assertEqual(len(selective), 420)
        self.assertEqual(len(full_context), 60)
        self.assertEqual(
            Counter(row["condition_id"] for row in selective),
            Counter({condition: 60 for condition in SELECTIVE_CONDITIONS}),
        )
        self.assertEqual({(row["requested_model"], row["served_model"]) for row in selective}, {("x-test-2", "deepseek-v4.1-flash")})
        self.assertEqual({(row["requested_model"], row["served_model"]) for row in full_context}, {("x-test-2", "deepseek-v4.1-flash-1017")})
        self.assertEqual({(row["judge_requested_model"], row["judge_served_model"]) for row in selective + full_context}, {("x-test-1", "glm-5.3-flash")})
        self.assertTrue(self.manifest["same_model_family"])
        self.assertFalse(self.manifest["exact_served_model_match"])
        self.assertFalse(self.manifest["strict_single_variable_ablation"])

    def test_full_context_contract_and_evidence_recall_na(self):
        full_context = [
            row
            for row in self.source_rows
            if row["answer_set_id"] == "full-context-deepseek-family-main60"
        ]
        for row in full_context:
            self.assertEqual(row["storage_representation"], "complete_S1_raw_history")
            self.assertEqual(row["retrieval_system"], "none")
            self.assertEqual(row["access_regime"], "full_context")
            self.assertEqual(row["evidence_item_count"], 30)
            self.assertEqual(row["evidence_bundle_characters"], 108960)
            self.assertIsNone(row["evidence_budget_characters"])
            self.assertIsNone(row["evidence_recall"])
            self.assertIsNone(row["evidence_any_hit"])
            self.assertIsNone(row["evidence_all_hit"])
            self.assertEqual(row["source_coverage_by_construction"], 1.0)
            self.assertEqual(row["retrieved_dia_ids"], [])
            self.assertEqual(row["search_action_count"], 0)
            self.assertEqual(row["retrieval_model_calls"], 0)
            self.assertEqual(row["retrieval_total_tokens"], 0)
        for row in self.tables["question-quadrants"]:
            self.assertIsNone(row["full_context_evidence_recall"])
            self.assertEqual(row["full_context_source_coverage_by_construction"], 1.0)
        full_summary = next(row for row in self.tables["condition-summaries"] if row["condition_id"] == FULL_CONTEXT_CONDITION)
        self.assertFalse(full_summary["evidence_recall_applicable"])
        self.assertEqual(full_summary["evidence_denominator"], 0)
        self.assertIsNone(full_summary["mean_evidence_recall"])

    def test_condition_summaries_match_independent_direct_means(self):
        summaries = {row["condition_id"]: row for row in self.tables["condition-summaries"]}
        self.assertEqual(set(summaries), set(EXPECTED_SUMMARIES))
        fields = ("token_precision", "token_recall", "token_f1", "strict_accuracy", "partial_rate", "soft_semantic_score")
        for condition, expected in EXPECTED_SUMMARIES.items():
            for field, value in zip(fields, expected):
                self.assertTrue(_close(summaries[condition][field], value), (condition, field))

        # Independently recompute the unified Stage-A macro means.
        source_condition = {FULL_CONTEXT_CONDITION: "full-context-deepseek-family-main60"}
        for condition in EXPECTED_SUMMARIES:
            if condition == FULL_CONTEXT_CONDITION:
                rows = [row for row in self.source_rows if row["answer_set_id"] == source_condition[condition]]
            else:
                rows = [
                    row
                    for row in self.source_rows
                    if row["answer_set_id"] == "model2-deepseek-main60" and row["condition_id"] == condition
                ]
            direct_fields = ("token_precision", "token_recall", "token_f1", "strict_score", "partial_indicator", "soft_semantic_score")
            for published, source in zip(fields, direct_fields):
                mean = math.fsum(float(row[source]) for row in rows) / 60
                self.assertTrue(_close(summaries[condition][published], mean), (condition, published))

    def test_comparison_deltas_win_tie_loss_and_strict_quadrants(self):
        comparisons = {row["selective_condition"]: row for row in self.tables["condition-comparisons"]}
        quadrant_rows = self.tables["quadrant-summary"]
        quadrant_order = ("both_correct", "full_context_only", "selective_only", "neither_correct")
        for condition in SELECTIVE_CONDITIONS:
            row = comparisons[condition]
            expected_delta = EXPECTED_SUMMARIES[FULL_CONTEXT_CONDITION][2] - EXPECTED_SUMMARIES[condition][2]
            self.assertTrue(_close(row["delta_token_f1"], expected_delta), condition)
            self.assertEqual(
                (row["token_f1_full_context_wins"], row["token_f1_ties"], row["token_f1_full_context_losses"]),
                EXPECTED_F1_WTL[condition],
            )
            observed_quadrants = tuple(
                next(
                    item["count"]
                    for item in quadrant_rows
                    if item["selective_condition"] == condition and item["strict_quadrant"] == quadrant
                )
                for quadrant in quadrant_order
            )
            self.assertEqual(observed_quadrants, EXPECTED_STRICT_QUADRANTS[condition])
            self.assertEqual(sum(observed_quadrants), 60)
            self.assertIsNone(row["full_context_evidence_recall"])
            self.assertIsNone(row["delta_evidence_recall"])

    def test_e7_category_results_and_quadrants(self):
        rows = {
            int(row["category"]): row
            for row in self.tables["category-comparisons"]
            if row["selective_condition"] == "E7"
        }
        self.assertEqual(set(rows), {1, 2, 3, 4})
        fields = (
            "full_context_token_precision",
            "full_context_token_recall",
            "full_context_token_f1",
            "full_context_strict_accuracy",
            "full_context_partial_rate",
            "full_context_soft_semantic_score",
        )
        quadrant_fields = (
            "strict_both_correct_count",
            "strict_full_context_only_count",
            "strict_selective_only_count",
            "strict_neither_correct_count",
        )
        for category, expected in EXPECTED_E7_CATEGORY.items():
            row = rows[category]
            for field, value in zip(fields, expected["metrics"]):
                self.assertTrue(_close(row[field], value), (category, field))
            self.assertEqual(tuple(row[field] for field in quadrant_fields), expected["quadrants"])
            self.assertEqual(sum(row[field] for field in quadrant_fields), row["answer_denominator"])

    def test_question_quadrants_and_rq5_candidates_are_complete_and_text_free(self):
        diagnostics = self.tables["question-quadrants"]
        candidates = self.tables["rq5-candidate-cases"]
        self.assertEqual(len(diagnostics), 420)
        self.assertEqual(len(candidates), 55)
        self.assertEqual(
            Counter((row["selective_condition"], row["strict_quadrant"]) for row in diagnostics),
            Counter(
                {
                    (condition, quadrant): count
                    for condition, counts in EXPECTED_STRICT_QUADRANTS.items()
                    for quadrant, count in zip(
                        ("both_correct", "full_context_only", "selective_only", "neither_correct"), counts
                    )
                }
            ),
        )
        self.assertTrue(all(row["strict_quadrant"] in {"full_context_only", "selective_only"} for row in candidates))
        for table in self.tables.values():
            for row in table:
                self.assertTrue(FORBIDDEN_FIELDS.isdisjoint(row))
                self.assertFalse(any("qwen" in str(value).lower() for value in row.values()))

    def test_judge_transitions_table_and_figure_inputs_are_complete(self):
        transitions = self.tables["judge-transitions"]
        self.assertEqual(len(transitions), 63)
        for condition in SELECTIVE_CONDITIONS:
            relevant = [row for row in transitions if row["selective_condition"] == condition]
            self.assertEqual(len(relevant), 9)
            self.assertEqual(sum(row["count"] for row in relevant), 60)
        self.assertEqual(len(self.tables["table-5-15-inputs"]), 7)
        self.assertEqual(len(self.tables["figure-5-8-inputs"]), 28)
        self.assertEqual(
            [(row["selective_condition"], row["strict_quadrant"], row["count"]) for row in self.tables["figure-5-8-inputs"]],
            [(row["selective_condition"], row["strict_quadrant"], row["count"]) for row in self.tables["quadrant-summary"]],
        )

    def test_csv_and_jsonl_tables_have_matching_values(self):
        for name in TABLES:
            with (self.output / f"{name}.csv").open(encoding="utf-8", newline="") as handle:
                csv_rows = list(csv.DictReader(handle))
            json_rows = self.tables[name]
            self.assertEqual(len(csv_rows), len(json_rows), name)
            self.assertEqual(set(csv_rows[0]), set(json_rows[0]), name)
            for csv_row, json_row in zip(csv_rows, json_rows):
                for field, value in json_row.items():
                    if value is None:
                        self.assertEqual(csv_row[field], "")
                    elif isinstance(value, bool):
                        self.assertEqual(csv_row[field], "True" if value else "False")
                    else:
                        self.assertEqual(csv_row[field], str(value))

    def test_existing_output_is_never_overwritten(self):
        with self.assertRaises(ValueError):
            build_rq4(**_kwargs(self.output))

    def test_tamper_missing_extra_and_symlink_are_rejected(self):
        cases = ("tamper", "missing", "extra", "symlink")
        for case in cases:
            with self.subTest(case=case), tempfile.TemporaryDirectory(prefix=f"rq4-{case}-") as tmp:
                target = Path(tmp) / "artifact"
                shutil.copytree(self.output, target)
                if case == "tamper":
                    path = target / "condition-comparisons.csv"
                    path.write_bytes(path.read_bytes() + b"tamper")
                elif case == "missing":
                    (target / "table-5-15-inputs.jsonl").unlink()
                elif case == "extra":
                    (target / "unexpected.txt").write_text("extra", encoding="utf-8")
                else:
                    path = target / "README.md"
                    path.unlink()
                    path.symlink_to(self.output / "README.md")
                with self.assertRaises(ValueError):
                    audit_rq4_output(**_kwargs(target))


if __name__ == "__main__":
    unittest.main()
