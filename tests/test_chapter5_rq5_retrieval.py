import json
import shutil
import tempfile
import unittest
from collections import Counter
from pathlib import Path

from fs_memory_lab.chapter5_rq5_retrieval import (
    EXPECTED_ELIGIBLE_PATHS,
    EXPECTED_ERROR_PATHS,
    EXPECTED_PATHS,
    EXPECTED_RETRIEVER_PATHS,
    PROTOCOL_VERSION,
    TABLES,
    audit_rq5_retrieval_output,
    build_rq5_retrieval_audit,
)


REPO_ROOT = Path(__file__).resolve().parents[1]


def _jsonl(path: Path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


class Chapter5RQ5RetrievalAuditTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix="rq5-retrieval-test-")
        cls.output = Path(cls.temp.name) / "rq5-retrieval-audit"
        cls.result = build_rq5_retrieval_audit(repo_root=REPO_ROOT, output_dir=cls.output)
        cls.tables = {name: _jsonl(cls.output / f"{name}.jsonl") for name in TABLES}

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def test_independent_audit_passes(self):
        audited = audit_rq5_retrieval_output(repo_root=REPO_ROOT, output_dir=self.output)
        self.assertEqual(audited["status"], "passed")
        self.assertEqual(audited["protocol_version"], PROTOCOL_VERSION)
        self.assertEqual(audited["audit_id"], self.result["audit_id"])
        self.assertEqual(audited["ranked_replay_paths_verified"], 360)
        self.assertEqual(audited["retrieval_causes_automatically_assigned"], 0)
        self.assertEqual(audited["downstream_states_modified"], 0)

    def test_complete_720_path_funnel_and_denominators(self):
        rows = self.tables["retrieval-funnel"]
        self.assertEqual(len(rows), EXPECTED_PATHS)
        self.assertEqual(len({row["retrieval_path_id"] for row in rows}), EXPECTED_PATHS)
        self.assertEqual(sum(row["evidence_eligible"] for row in rows), EXPECTED_ELIGIBLE_PATHS)
        self.assertEqual(Counter(row["retriever_id"] for row in rows), Counter(EXPECTED_RETRIEVER_PATHS))
        self.assertEqual(Counter(row["condition_id"] for row in rows), Counter({f"E{i}": 120 for i in range(1, 7)}))
        self.assertEqual(sum(row["strict_score"] == 0.0 for row in rows), EXPECTED_ERROR_PATHS)
        self.assertTrue(all("annotated_evidence_observation_state" in row for row in rows))
        self.assertTrue(all("decisive_observation_state" not in row for row in rows))

    def test_final_bundle_reconstruction_matches_frozen_metrics(self):
        rows = self.tables["retrieval-funnel"]
        for row in rows:
            if row["evidence_eligible"]:
                self.assertEqual(row["final_any_hit"], row["recorded_evidence_any_hit"])
                self.assertEqual(row["final_all_hit"], row["recorded_evidence_all_hit"])
                self.assertAlmostEqual(row["final_gold_fraction"], row["recorded_evidence_recall"])
                self.assertLessEqual(row["selected_gold_count"], row["observed_gold_count"])
                self.assertLessEqual(row["final_gold_count"], row["selected_gold_count"])
            else:
                self.assertEqual(row["annotated_source_presence_state"], "not_annotated")
                self.assertIsNone(row["final_any_hit"])

    def test_r2_r3_offline_replay_and_seen_state_are_exact(self):
        ranked = self.tables["r2-diagnostics"] + self.tables["r3-diagnostics"]
        self.assertEqual(len(ranked), 360)
        self.assertTrue(all(row["search_replay_verified"] for row in ranked))
        self.assertTrue(all(row["seen_state_exclusion_verified"] for row in ranked))
        self.assertTrue(all(len(row["replay_sha256"]) == 64 for row in ranked))
        self.assertTrue(all(row["search_action_count"] >= 1 for row in ranked))
        self.assertTrue(all("new_annotated_gold_search_count" in row for row in ranked))
        self.assertTrue(all("no_new_annotated_gold_search_count" in row for row in ranked))
        self.assertTrue(all("productive_gold_search_count" not in row for row in ranked))
        self.assertTrue(all("non_gold_search_count" not in row for row in ranked))

    def test_empty_and_nonempty_without_annotated_gold_are_explicit(self):
        rows = self.tables["retrieval-funnel"]
        observed = {
            retriever: {
                "eligible_empty": sum(row["evidence_eligible"] and row["empty_bundle"] for row in rows if row["retriever_id"] == retriever),
                "ineligible_empty": sum((not row["evidence_eligible"]) and row["empty_bundle"] for row in rows if row["retriever_id"] == retriever),
                "nonempty_without_annotated_gold": sum(bool(row["nonempty_bundle_without_annotated_gold"]) for row in rows if row["retriever_id"] == retriever),
            }
            for retriever in ("R1", "R2", "R3")
        }
        self.assertEqual(observed, {
            "R1": {"eligible_empty": 5, "ineligible_empty": 0, "nonempty_without_annotated_gold": 25},
            "R2": {"eligible_empty": 7, "ineligible_empty": 2, "nonempty_without_annotated_gold": 34},
            "R3": {"eligible_empty": 1, "ineligible_empty": 0, "nonempty_without_annotated_gold": 18},
        })

    def test_category_summary_freezes_funnel_and_quality_metrics(self):
        rows = self.tables["retriever-category-summary"]
        expected_category_n = {"single-hop": 27, "multi-hop": 13, "temporal": 13, "open-domain": 7}
        self.assertEqual(len(rows), 48)
        self.assertEqual(Counter((row["backbone_id"], row["condition_id"]) for row in rows), Counter({(b, f"E{i}"): 4 for b in ("qwen", "deepseek") for i in range(1, 7)}))
        self.assertEqual({row["category_name"] for row in rows}, {"single-hop", "multi-hop", "temporal", "open-domain"})
        for row in rows:
            self.assertIn("mean_evidence_recall", row)
            self.assertIn("strict_accuracy", row)
            self.assertIn("mean_soft_semantic_score", row)
            self.assertEqual(row["path_n"], expected_category_n[row["category_name"]])

    def test_native_cap_is_process_state_not_failure(self):
        rows = self.tables["retrieval-funnel"]
        capped = [row for row in rows if row["hit_native_cap"]]
        self.assertEqual(len(capped), 359)
        self.assertEqual(sum(row["strict_score"] == 1.0 for row in capped), 234)
        self.assertTrue(all(row["native_cap_is_not_automatic_failure"] for row in rows))
        self.assertTrue(any(row["final_all_hit"] and row["strict_score"] == 1.0 for row in capped if row["evidence_eligible"]))

    def test_stage_transitions_have_explicit_denominators(self):
        rows = self.tables["stage-transitions"]
        self.assertEqual(len(rows), 72)
        self.assertEqual(Counter((row["backbone_id"], row["condition_id"]) for row in rows), Counter({(b, f"E{i}"): 6 for b in ("qwen", "deepseek") for i in range(1, 7)}))
        for row in rows:
            self.assertGreaterEqual(row["source_n"], row["target_n"])
            self.assertEqual(row["attrition_n"], row["source_n"] - row["target_n"])
            if row["source_n"]:
                self.assertAlmostEqual(row["retention_rate"], row["target_n"] / row["source_n"])

    def test_controlled_and_cross_backbone_comparisons_are_complete(self):
        controlled = self.tables["controlled-comparisons"]
        cross = self.tables["cross-backbone-comparisons"]
        self.assertEqual(len(controlled), 600)
        self.assertEqual(Counter(row["contrast"] for row in controlled), Counter({
            "E2-E1": 120, "E4-E3": 120, "E6-E5": 120, "E3-E1": 120, "E4-E2": 120,
        }))
        self.assertEqual(len(cross), 360)
        self.assertEqual(Counter(row["condition_id"] for row in cross), Counter({f"E{i}": 60 for i in range(1, 7)}))

    def test_strict_error_linkage_is_diagnostic_not_automatic_causation(self):
        links = self.tables["strict-error-retrieval-linkage"]
        self.assertEqual(len(links), EXPECTED_ERROR_PATHS)
        self.assertEqual(sum(row["evidence_eligible"] for row in links), 191)
        self.assertTrue(all(row["retrieval_cause_decision"] == "diagnostic_only_no_automatic_causal_assignment" for row in links))
        self.assertTrue(all(row["causal_sufficiency"] == "not_established" for row in links))
        self.assertTrue(all(row["gold_annotation_is_diagnostic_not_causal"] for row in links))

    def test_only_retrieval_owned_state_fields_change(self):
        after = self.tables["root-cause-state-register-after-retrieval"]
        before = {row["case_id"]: row for row in _jsonl(REPO_ROOT / "artifacts/chapter5-main60-analysis-v1/rq5-storage-audit/root-cause-state-register-after-storage.jsonl")}
        self.assertEqual(len(after), 250)
        self.assertEqual(sum(row["retrieval_audit_applicable"] for row in after), 205)
        protected = (
            "evidence_retention_state", "final_input_sufficiency_state", "answerer_utilisation_state",
            "parent_e2_bundle_state", "parent_e6_bundle_state", "fusion_operation_state",
            "long_context_utilisation_state", "evaluation_agreement_state", "primary_cause",
            "secondary_causes", "attribution_status", "attribution_strength", "causal_sufficiency",
        )
        for row in after:
            old = before[row["case_id"]]
            for field in protected:
                self.assertEqual(row[field], old[field], (row["case_id"], field))
        eligible = [row for row in after if row["retrieval_audit_applicable"] and row["annotated_evidence_attribution_applicable"]]
        self.assertTrue(all(row["retriever_reach_state"] in {"reached", "not_reached"} for row in eligible))
        self.assertTrue(all(row["model_observation_state"] in {"observed", "not_observed"} for row in eligible))

    def test_public_tables_have_no_text_or_secret_fields(self):
        forbidden = {
            "question", "question_text", "answer", "answer_text", "reference_answer",
            "candidate_answer", "evidence", "evidence_text", "retrieved_text", "prompt",
            "rationale", "thought", "keywords", "query_text", "api_key", "authorization", "secret",
        }
        for table in self.tables.values():
            for row in table:
                self.assertFalse(set(key.casefold() for key in row) & forbidden)
        readme = (self.output / "README.md").read_text(encoding="utf-8")
        self.assertIn("do not automatically establish a causal retrieval failure", readme)

    def test_second_build_is_byte_identical(self):
        with tempfile.TemporaryDirectory(prefix="rq5-retrieval-repeat-") as tmp:
            target = Path(tmp) / "output"
            repeated = build_rq5_retrieval_audit(repo_root=REPO_ROOT, output_dir=target)
            self.assertEqual(repeated["audit_id"], self.result["audit_id"])
            self.assertEqual({path.name for path in target.iterdir()}, {path.name for path in self.output.iterdir()})
            for source in self.output.iterdir():
                self.assertEqual(source.read_bytes(), (target / source.name).read_bytes(), source.name)

    def test_existing_output_and_tampering_are_rejected(self):
        with self.assertRaises(Exception):
            build_rq5_retrieval_audit(repo_root=REPO_ROOT, output_dir=self.output)
        with tempfile.TemporaryDirectory(prefix="rq5-retrieval-tamper-") as tmp:
            target = Path(tmp) / "output"
            shutil.copytree(self.output, target)
            path = target / "retrieval-funnel.jsonl"
            path.write_bytes(path.read_bytes() + b"{}\n")
            with self.assertRaises(Exception):
                audit_rq5_retrieval_output(repo_root=REPO_ROOT, output_dir=target)


if __name__ == "__main__":
    unittest.main()
