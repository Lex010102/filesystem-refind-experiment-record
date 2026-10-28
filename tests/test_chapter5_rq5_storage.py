import json
import tempfile
import unittest
from collections import Counter
from pathlib import Path

from fs_memory_lab.chapter5_rq5_storage import (
    DIRECT_STORAGE_LOSS_QUESTION,
    EXPECTED_S2_QUESTION_CLASSES,
    EXPECTED_S2_ROUTING_CLASSES,
    EXPECTED_S3_CLASSES,
    EXPECTED_S3_REFERENCE_SUPPORT,
    EXPECTED_S3_SOURCE_FIDELITY,
    PROTOCOL_VERSION,
    TABLES,
    audit_rq5_storage_output,
    build_rq5_storage_audit,
)


REPO_ROOT = Path(__file__).resolve().parents[1]


def _jsonl(path: Path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


class Chapter5RQ5StorageAuditTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix="rq5-storage-test-")
        cls.output = Path(cls.temp.name) / "rq5-storage-audit"
        cls.result = build_rq5_storage_audit(repo_root=REPO_ROOT, output_dir=cls.output)
        cls.tables = {name: _jsonl(cls.output / f"{name}.jsonl") for name in TABLES}

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def test_independent_audit_passes_and_is_deterministic(self):
        audited = audit_rq5_storage_output(repo_root=REPO_ROOT, output_dir=self.output)
        self.assertEqual(audited["status"], "passed")
        self.assertEqual(audited["protocol_version"], PROTOCOL_VERSION)
        self.assertEqual(audited["audit_id"], self.result["audit_id"])

    def test_primary_question_store_denominators_are_not_inflated(self):
        rows = self.tables["storage-fidelity"]
        self.assertEqual(len(rows), 180)
        self.assertEqual(len({row["question_store_id"] for row in rows}), 180)
        self.assertEqual(sum(row["evidence_eligible"] for row in rows), 174)
        self.assertEqual(Counter(row["store_id"] for row in rows), Counter({"S1": 60, "S2": 60, "S3": 60}))

    def test_s1_s2_are_exactly_equivalent_but_layout_differs(self):
        rows = self.tables["s1-s2-equivalence"]
        self.assertEqual(len(rows), 30)
        self.assertTrue(all(row["byte_equal"] and row["body_equal"] for row in rows))
        self.assertEqual(sum(row["turn_count"] for row in rows), 568)
        integrity = {row["store_id"]: row for row in self.tables["store-integrity"]}
        self.assertEqual(integrity["S1"]["content_identity"], integrity["S2"]["content_identity"])
        self.assertNotEqual(integrity["S1"]["tree_sha256"], integrity["S2"]["tree_sha256"])

    def test_s2_routing_reports_oracle_scope_not_actual_discoverability(self):
        rows = [row for row in self.tables["s2-routing"] if row["evidence_eligible"]]
        self.assertEqual(len(rows), 58)
        self.assertEqual(sum(row["cross_folder_evidence_required"] for row in rows), 8)
        self.assertTrue(all(2 <= row["candidate_sessions_if_gold_folders_known"] <= 25 for row in rows))
        self.assertTrue(all("gold" in row["routing_finding"] or row["routing_finding"] == "cross_folder_required" for row in rows))
        self.assertEqual(Counter(row["question_routing_class"] for row in rows), Counter(EXPECTED_S2_QUESTION_CLASSES))

    def test_s2_semantic_routing_review_is_complete_and_outcome_blind(self):
        rows = self.tables["s2-routing-session-review"]
        self.assertEqual(len(rows), 79)
        self.assertEqual(Counter(row["routing_alignment"] for row in rows), Counter(EXPECTED_S2_ROUTING_CLASSES))
        self.assertTrue(all(row["review_blind_to_answer_outcomes"] for row in rows))

    def test_s3_locator_coverage_is_not_used_as_semantic_label(self):
        rows = [row for row in self.tables["s3-fact-preservation"] if row["evidence_eligible"]]
        self.assertTrue(all(row["all_gold_locators_present_in_body"] for row in rows))
        self.assertEqual(Counter(row["curated_form_class"] for row in rows), Counter(EXPECTED_S3_CLASSES))
        self.assertEqual(Counter(row["source_to_store_fidelity"] for row in rows), Counter(EXPECTED_S3_SOURCE_FIDELITY))
        self.assertEqual(Counter(row["reference_support_sufficiency"] for row in rows), Counter(EXPECTED_S3_REFERENCE_SUPPORT))
        self.assertEqual(sum(row["curated_form_class"] == "partially_preserved" for row in rows), 4)
        self.assertTrue(all(row["whole_store_alternative_support_checked"] for row in rows))
        self.assertEqual(sum(row["all_gold_colocated_in_one_fact_unit"] for row in rows), 41)
        self.assertEqual(sum(row["all_gold_colocated_in_one_h2_group"] for row in rows), 54)
        self.assertEqual(sum(row["all_gold_colocated_in_one_file"] for row in rows), 58)
        self.assertEqual(
            Counter(row["minimum_fact_units_for_gold_locator_cover"] for row in rows),
            Counter({1: 41, 2: 14, 3: 2, 4: 1}),
        )
        multi = [row for row in rows if row["gold_locator_count"] > 1]
        self.assertEqual(len(multi), 19)
        self.assertEqual(sum(row["all_gold_colocated_in_one_fact_unit"] for row in multi), 2)
        self.assertEqual(sum(row["all_gold_colocated_in_one_h2_group"] for row in multi), 15)
        self.assertEqual(sum(row["all_gold_colocated_in_one_file"] for row in multi), 19)

    def test_storage_review_is_outcome_blind(self):
        review = json.loads((REPO_ROOT / "docs/analysis/reviews/chapter5-rq5-storage-review-v1.json").read_text(encoding="utf-8"))
        forbidden = {"backbone", "condition", "judge_label", "strict_score", "token_f1", "evidence_recall"}
        self.assertTrue(review["review_blind_to_answer_outcomes"])
        self.assertEqual(len(review["rows"]), 58)
        self.assertTrue(all(not (set(row) & forbidden) for row in review["rows"]))

    def test_shared_renderer_limitation_is_not_mislabelled_as_twelve_store_defects(self):
        links = self.tables["case-storage-linkage"]
        self.assertEqual(len(links), 205)
        exposed = [row for row in links if row["shared_representation_insufficiency_present"]]
        self.assertEqual(len(exposed), 12)
        self.assertEqual({row["question_id"] for row in exposed}, {DIRECT_STORAGE_LOSS_QUESTION})
        self.assertEqual({row["attribution_strength"] for row in exposed}, {"direct_upstream_limitation"})
        self.assertEqual({row["causal_sufficiency"] for row in exposed}, {"not_established"})
        self.assertEqual(len({row["question_store_id"] for row in exposed}), 3)
        self.assertFalse(any(row["store_specific_limitation_present"] for row in links))

    def test_curator_did_not_introduce_a_decisive_loss(self):
        rows = [row for row in self.tables["s3-fact-preservation"] if row["evidence_eligible"]]
        self.assertFalse(any(row["curator_introduced_decisive_loss"] for row in rows))
        q002 = next(row for row in rows if row["question_id"] == DIRECT_STORAGE_LOSS_QUESTION)
        self.assertTrue(q002["representation_decisive_loss"])
        self.assertFalse(q002["store_specific_decisive_loss"])
        self.assertEqual(q002["loss_scope"], "shared_renderer_before_store_construction")
        self.assertEqual(q002["gap_origin"], "renderer_excluded_query_inherited_by_s3")


if __name__ == "__main__":
    unittest.main()
