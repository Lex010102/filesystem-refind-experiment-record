from __future__ import annotations

import csv
import json
import tempfile
import unittest
from collections import Counter
from pathlib import Path

import fs_memory_lab.chapter5_rq5_integrated as integrated


REPO_ROOT = Path(__file__).resolve().parents[1]


class Chapter5RQ5IntegratedTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.work = tempfile.TemporaryDirectory(prefix=".rq5-integrated-test-", dir=REPO_ROOT)
        cls.output = Path(cls.work.name) / "audit"
        cls.result = integrated.build_rq5_integrated(repo_root=REPO_ROOT, output_dir=cls.output)

    @classmethod
    def tearDownClass(cls):
        cls.work.cleanup()

    def _csv(self, name: str):
        with (self.output / f"{name}.csv").open(newline="", encoding="utf-8") as handle:
            return list(csv.DictReader(handle))

    def test_build_and_independent_audit_pass(self):
        self.assertEqual(self.result["status"], "passed")
        self.assertTrue(self.result["primary_attribution_computed"])
        audited = integrated.audit_rq5_integrated(repo_root=REPO_ROOT, output_dir=self.output)
        self.assertEqual(audited["audit_id"], self.result["audit_id"])

    def test_primary_distribution_is_complete_and_frozen(self):
        rows = self._csv("integrated-attributions")
        self.assertEqual(len(rows), 250)
        self.assertEqual(len({row["analysis_row_id"] for row in rows}), 250)
        self.assertEqual(
            Counter(row["primary_stage"] for row in rows),
            Counter({
                "storage": 0,
                "retrieval": 42,
                "packaging": 7,
                "answerer": 68,
                "fusion_or_long_context": 6,
                "evaluation_sensitive": 53,
                "mixed_or_indeterminate": 74,
            }),
        )

    def test_branch_scopes_and_causal_guards_hold(self):
        rows = self._csv("integrated-attributions")
        self.assertEqual(
            Counter(row["access_regime"] for row in rows),
            Counter({"selective_retrieval": 205, "dual_source_fusion": 31, "full_context": 14}),
        )
        e7_harm = [row for row in rows if row["condition_id"] == "E7" and row["fusion_outcome"] == "harm"]
        self.assertEqual(len(e7_harm), 8)
        self.assertFalse(any(row["primary_stage"] == "fusion_or_long_context" for row in e7_harm))
        self.assertFalse(any(row["primary_stage"] == "storage" for row in rows))

    def test_packaging_respects_earliest_supported_break(self):
        rows = self._csv("integrated-attributions")
        packaging = [row for row in rows if row["primary_stage"] == "packaging"]
        self.assertEqual(len(packaging), 7)
        self.assertTrue(all(row["primary_rule_id"] == "S2_COMPLETE_OBSERVATION_THEN_DEMONSTRATED_LOSS" for row in packaging))
        mechanisms = self._csv("case-mechanisms")
        demonstrated = {
            row["attribution_id"] for row in mechanisms
            if row["mechanism_group"] == "packaging" and row["mechanism_code"] == "demonstrated_relevant_loss"
        }
        self.assertEqual(len(demonstrated), 9)
        self.assertTrue({row["attribution_id"] for row in packaging} <= demonstrated)

    def test_cooccurring_mechanisms_do_not_form_a_partition(self):
        rows = self._csv("case-mechanisms")
        by_group = {}
        for group in {row["mechanism_group"] for row in rows}:
            by_group[group] = len({row["attribution_id"] for row in rows if row["mechanism_group"] == group})
        self.assertEqual(by_group["retrieval"], 76)
        self.assertEqual(by_group["answerer"], 74)
        self.assertEqual(by_group["long_context"], 6)
        self.assertEqual(by_group["evaluation"], 74)
        self.assertEqual(by_group["storage_representation"], 12)
        self.assertGreater(sum(by_group.values()), 250)

    def test_evaluation_screen_scope_is_not_overextended(self):
        rows = self._csv("integrated-attributions")
        self.assertEqual(sum(row["evaluation_screened"] == "True" for row in rows), 76)
        self.assertEqual(sum(row["evaluation_audit_sensitive"] == "True" for row in rows), 50)
        self.assertEqual(sum(row["explicit_evaluation_sensitivity"] == "True" for row in rows), 74)
        states = self._csv("root-cause-state-register-final")
        self.assertEqual(
            Counter(row["evaluation_agreement_state"] for row in states),
            Counter({"evaluation_sensitive": 74, "reviewed_not_sensitive": 26, "not_screened": 150}),
        )

    def test_source_reference_mismatch_does_not_masquerade_as_retrieval_failure(self):
        rows = self._csv("integrated-attributions")
        mismatch_questions = {"conv-50-q089", "conv-50-q126", "conv-50-q152"}
        affected = [row for row in rows if row["question_id"] in mismatch_questions]
        self.assertEqual(len(affected), 33)
        self.assertTrue(all(row["primary_stage"] == "evaluation_sensitive" for row in affected))
        self.assertFalse(any(row["primary_stage"] == "retrieval" for row in affected))

    def test_final_state_register_has_no_pending_attribution(self):
        states = self._csv("root-cause-state-register-final")
        self.assertEqual(len(states), 250)
        for row in states:
            self.assertNotEqual(row["primary_cause"], "pending")
            self.assertNotEqual(row["attribution_status"], "pending")
            self.assertNotEqual(row["attribution_strength"], "pending")
            self.assertEqual(row["integration_protocol_version"], integrated.PROTOCOL_VERSION)

    def test_representative_set_is_small_and_mechanistically_diverse(self):
        rows = self._csv("representative-cases")
        self.assertEqual(len(rows), 6)
        self.assertEqual(
            {row["case_role"] for row in rows},
            {
                "r1_sufficient_bundle_answerer_failure",
                "r2_retrieval_break",
                "r3_packaging_break",
                "evaluation_sensitive_source_reference_mismatch",
                "e7_harm_without_item_loss",
                "full_context_localisation_or_interference",
            },
        )
        self.assertEqual(
            {(row["case_role"], row["question_id"]) for row in rows},
            {
                ("r1_sufficient_bundle_answerer_failure", "conv-50-q037"),
                ("r2_retrieval_break", "conv-50-q022"),
                ("r3_packaging_break", "conv-50-q052"),
                ("evaluation_sensitive_source_reference_mismatch", "conv-50-q089"),
                ("e7_harm_without_item_loss", "conv-50-q051"),
                ("full_context_localisation_or_interference", "conv-50-q019"),
            },
        )

    def test_public_artifacts_exclude_content_fields(self):
        forbidden = ('"question"', '"answer"', '"reference"', '"evidence"', '"prompt"', '"rationale"')
        for path in self.output.iterdir():
            if path.suffix not in {".json", ".jsonl", ".csv"}:
                continue
            payload = path.read_text(encoding="utf-8").lower()
            for field in forbidden:
                self.assertNotIn(field, payload, f"forbidden field leaked in {path.name}")


if __name__ == "__main__":
    unittest.main()
