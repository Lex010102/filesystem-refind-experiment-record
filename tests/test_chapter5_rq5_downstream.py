from __future__ import annotations

import copy
import json
import tempfile
import unittest
from collections import Counter
from pathlib import Path

import fs_memory_lab.chapter5_rq5_downstream as downstream
from fs_memory_lab.chapter5_stage_b import _read_jsonl
from fs_memory_lab.evidence import canonical_json_bytes


REPO_ROOT = Path(__file__).resolve().parents[1]


class Chapter5RQ5DownstreamTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.work = tempfile.TemporaryDirectory(prefix=".rq5-downstream-test-", dir=REPO_ROOT)
        cls.work_dir = Path(cls.work.name)
        cls.upstream = downstream._validate_upstream(REPO_ROOT)
        cls.stage_rows, cls.stage_index = downstream._stage_rows(REPO_ROOT)
        relevant = [
            row
            for row in cls.stage_rows
            if row.get("condition_id") in (*downstream.SELECTIVE_CONDITIONS, downstream.FUSED_CONDITION)
        ]
        cls.record_index = {
            str(row["analysis_row_id"]): downstream._load_record(REPO_ROOT, row)
            for row in relevant
        }
        cls.strict_errors = _read_jsonl(REPO_ROOT / downstream.STAGE1_PATH / "strict-error-cases.jsonl")
        review_rows = []
        for backbone in downstream.BACKBONES:
            review_rows.extend(
                downstream._validate_downstream_review_payload(
                    repo_root=REPO_ROOT,
                    path=REPO_ROOT / downstream.DEFAULT_REVIEW_PATHS[backbone],
                    backbone=backbone,
                    stage_index=cls.stage_index,
                    record_index=cls.record_index,
                    strict_errors=cls.strict_errors,
                )
            )
        cls.reviews = {
            (str(row["backbone_id"]), str(row["condition_id"]), str(row["question_id"])): row
            for row in review_rows
        }
        cls.mechanisms = downstream._load_e7_mechanism_review(
            repo_root=REPO_ROOT,
            path=REPO_ROOT / downstream.DEFAULT_REVIEW_PATHS["e7_mechanism"],
            stage_index=cls.stage_index,
            record_index=cls.record_index,
            downstream_by_key=cls.reviews,
        )
        cls.exact = downstream._verify_exact_fusion(
            stage_index=cls.stage_index,
            record_index=cls.record_index,
        )
        cls.e7_payload = cls._synthetic_e7_error_payload()
        cls.e7_path = cls.work_dir / "chapter5-rq5-e7-error-review-v1.json"
        cls.e7_path.write_text(
            json.dumps(cls.e7_payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        cls.e7_errors = downstream._load_e7_error_review(
            path=cls.e7_path,
            errors=cls.strict_errors,
            stage_index=cls.stage_index,
            downstream_by_key=cls.reviews,
            mechanism_by_key=cls.mechanisms,
        )

    @classmethod
    def tearDownClass(cls):
        cls.work.cleanup()

    @classmethod
    def _synthetic_e7_error_payload(cls):
        cases = []
        for error in cls.strict_errors:
            if error["condition_id"] != downstream.FUSED_CONDITION:
                continue
            backbone = str(error["packet_backbone"])
            question_id = str(error["question_id"])
            key = (backbone, question_id)
            e2 = cls.stage_index[(backbone, "E2", question_id)]
            e6 = cls.stage_index[(backbone, "E6", question_id)]
            e7 = cls.stage_index[(backbone, "E7", question_id)]
            boundary = cls.mechanisms.get(key)

            def parent_state(condition):
                reviewed = cls.reviews.get((backbone, condition, question_id))
                if reviewed is not None:
                    return reviewed["evidence_state"]
                if boundary is not None:
                    return boundary["parent_evidence_states"][condition]
                return "indeterminate"

            if boundary is not None and boundary["outcome"] == "harm":
                fused_state = boundary["fused_evidence_state"]
                operation = "interfered"
                mechanism = boundary["primary_mechanism"]
                secondary = sorted(boundary["secondary_mechanisms"])
                confidence = boundary["confidence"]
            else:
                fused_state = "indeterminate"
                operation = "indeterminate"
                mechanism = "indeterminate"
                secondary = []
                confidence = "low"
            cases.append(
                {
                    "review_id": f"e7-error-review-{backbone}-{question_id}",
                    "case_id": error["case_id"],
                    "analysis_row_id": e7["analysis_row_id"],
                    "backbone_id": backbone,
                    "condition_id": "E7",
                    "question_id": question_id,
                    "question_sha256": e7["question_sha256"],
                    "record_ids": {
                        "E2": e2["source_record_id"],
                        "E6": e6["source_record_id"],
                        "E7": e7["source_record_id"],
                    },
                    "bundle_ids": {
                        "E2": e2["evidence_bundle_id"],
                        "E6": e6["evidence_bundle_id"],
                        "E7": e7["evidence_bundle_id"],
                    },
                    "parent_evidence_states": {
                        "E2": parent_state("E2"),
                        "E6": parent_state("E6"),
                    },
                    "fused_evidence_state": fused_state,
                    "fusion_operation_state": operation,
                    "answerer_utilisation_state": "indeterminate",
                    "fusion_mechanism": mechanism,
                    "secondary_mechanisms": secondary,
                    "confidence": confidence,
                    "review_status": "completed",
                    "manual_content_inspected": True,
                }
            )
        return {
            "protocol_version": downstream.E7_ERROR_REVIEW_PROTOCOL_VERSION,
            "review_status": "completed",
            "review_unit": "backbone_id x E7 strict-noncorrect question",
            "guards": {
                "strict_noncorrect_cases_only": True,
                "parent_sufficiency_precedes_fusion_review": True,
                "exact_fusion_verified_separately": True,
                "answerer_assessed_only_after_sufficiency": True,
                "no_new_model_calls": True,
                "no_source_mutation": True,
            },
            "cases": cases,
        }

    def _write_payload(self, name, payload):
        path = self.work_dir / name
        path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        return path

    def test_contract_freezes_gate_order_and_post_downstream_handoff(self):
        contract = downstream.review_contract()
        self.assertEqual(contract["downstream_review"]["rows_per_file"], {"qwen": 99, "deepseek": 106})
        self.assertEqual(contract["e7_error_review"]["rows"], 31)
        self.assertEqual(
            contract["artifact_handoff"]["post_downstream_state_jsonl"],
            "artifacts/chapter5-main60-analysis-v1/rq5-downstream-audit/root-cause-state-register-after-downstream.jsonl",
        )
        self.assertEqual(
            contract["gate_order"],
            ["evidence_and_packaging", "answerer_utilisation", "e7_parent_and_fusion"],
        )
        self.assertTrue(contract["no_api_calls"])

    def test_upstream_audits_hashes_and_markers_are_pinned(self):
        self.assertEqual(set(self.upstream), {"stage1", "storage", "retrieval", "rq3"})
        for role, binding in self.upstream.items():
            self.assertEqual(binding["audit_id"], downstream.EXPECTED_UPSTREAM_AUDITS[role])
            self.assertEqual(binding["audit_sha256"], downstream.EXPECTED_UPSTREAM_FILE_SHA256[role]["audit"])
            self.assertEqual(binding["marker_sha256"], downstream.EXPECTED_UPSTREAM_FILE_SHA256[role]["marker"])

    def test_actual_qwen_and_deepseek_reviews_are_exact_and_sequentially_gated(self):
        self.assertEqual(len(self.reviews), 205)
        self.assertEqual(
            Counter(key[0] for key in self.reviews),
            Counter({"qwen": 99, "deepseek": 106}),
        )
        for row in self.reviews.values():
            if row["final_input_sufficiency_state"] != "sufficient":
                self.assertEqual(row["utilisation_review_state"], "not_assessable")
                self.assertEqual(row["answerer_utilisation_state"], "indeterminate")
            self.assertNotIn("rationale", row)
            self.assertNotIn("answer", row)
            self.assertNotIn("evidence", row)

    def test_downstream_review_unknown_field_and_substitution_are_rejected(self):
        payload = json.loads(
            (REPO_ROOT / downstream.DEFAULT_REVIEW_PATHS["qwen"]).read_text(encoding="utf-8")
        )
        unknown = copy.deepcopy(payload)
        unknown["rows"][0]["unexpected"] = True
        with self.assertRaises(Exception):
            downstream._validate_downstream_review_payload(
                repo_root=REPO_ROOT,
                path=self._write_payload("qwen-unknown.json", unknown),
                backbone="qwen",
                stage_index=self.stage_index,
                record_index=self.record_index,
                strict_errors=self.strict_errors,
            )
        substituted = copy.deepcopy(payload)
        substituted["rows"][0]["question_id"] = substituted["rows"][1]["question_id"]
        with self.assertRaises(Exception):
            downstream._validate_downstream_review_payload(
                repo_root=REPO_ROOT,
                path=self._write_payload("qwen-substituted.json", substituted),
                backbone="qwen",
                stage_index=self.stage_index,
                record_index=self.record_index,
                strict_errors=self.strict_errors,
            )

    def test_e7_boundary_review_is_strict_and_conflicts_are_not_silently_promoted(self):
        self.assertEqual(len(self.mechanisms), 12)
        self.assertEqual(sum(not row["gated_parent_state_consistent"] for row in self.mechanisms.values()), 4)
        payload = json.loads(
            (REPO_ROOT / downstream.DEFAULT_REVIEW_PATHS["e7_mechanism"]).read_text(encoding="utf-8")
        )
        payload["cases"][0]["secondary_mechanisms"].append("free_text_mechanism")
        with self.assertRaises(Exception):
            downstream._load_e7_mechanism_review(
                repo_root=REPO_ROOT,
                path=self._write_payload("e7-mechanism-tampered.json", payload),
                stage_index=self.stage_index,
                record_index=self.record_index,
                downstream_by_key=self.reviews,
            )

    def test_e7_error_review_covers_exact_31_errors_and_rejects_reordering(self):
        self.assertEqual(len(self.e7_errors), 31)
        self.assertEqual(set(self.e7_errors), {
            (str(row["packet_backbone"]), str(row["question_id"]))
            for row in self.strict_errors
            if row["condition_id"] == "E7"
        })
        reordered = copy.deepcopy(self.e7_payload)
        reordered["cases"][0], reordered["cases"][1] = reordered["cases"][1], reordered["cases"][0]
        with self.assertRaises(Exception):
            downstream._load_e7_error_review(
                path=self._write_payload("e7-errors-reordered.json", reordered),
                errors=self.strict_errors,
                stage_index=self.stage_index,
                downstream_by_key=self.reviews,
                mechanism_by_key=self.mechanisms,
            )

    def test_all_120_e7_bundles_are_exact_parent_fusions(self):
        self.assertEqual(len(self.exact), 120)
        self.assertTrue(all(row["exact_fusion_verified"] for row in self.exact.values()))
        self.assertTrue(all(row["parent_items_preserved_exactly"] for row in self.exact.values()))
        self.assertTrue(all(row["no_new_search"] for row in self.exact.values()))
        changed = dict(self.record_index)
        e7_rows = [row for row in self.stage_index.values() if row["condition_id"] == "E7"]
        changed[str(e7_rows[0]["analysis_row_id"])] = self.record_index[str(e7_rows[1]["analysis_row_id"])]
        with self.assertRaises(Exception):
            downstream._verify_exact_fusion(stage_index=self.stage_index, record_index=changed)

    def test_public_rows_are_text_free_and_e7_unreviewed_mechanisms_remain_indeterminate(self):
        evidence = downstream._evidence_rows(
            selective_rows=[self.stage_index[key] for key in self.reviews],
            reviews=self.reviews,
        )
        packaging = downstream._packaging_rows(
            selective_rows=[self.stage_index[key] for key in self.reviews],
            reviews=self.reviews,
            record_index=self.record_index,
        )
        answerer = downstream._answerer_rows(
            selective_rows=[self.stage_index[key] for key in self.reviews],
            reviews=self.reviews,
        )
        parents, mechanisms = downstream._build_e7_rows(
            repo_root=REPO_ROOT,
            stage_index=self.stage_index,
            reviews=self.reviews,
            error_reviews=self.e7_errors,
            mechanism_reviews=self.mechanisms,
            exact=self.exact,
        )
        self.assertEqual((len(evidence), len(packaging), len(answerer), len(parents), len(mechanisms)), (205, 205, 205, 120, 120))
        unresolved_without_content_review = [
            row for row in mechanisms
            if row["fusion_outcome"] == "unresolved" and row["review_source"] == "exact_parent_sufficiency_derivation"
        ]
        self.assertTrue(all(row["fusion_mechanism"] == "indeterminate" for row in unresolved_without_content_review))
        downstream._assert_text_free({
            "evidence": evidence,
            "packaging": packaging,
            "answerer": answerer,
            "parents": parents,
            "mechanisms": mechanisms,
        })
        with self.assertRaises(Exception):
            downstream._assert_text_free({"bad": [{"nested": {"rationale": "must not publish"}}]})

    def test_state_register_changes_only_owned_fields_and_preserves_full_context(self):
        before = _read_jsonl(
            REPO_ROOT / downstream.RETRIEVAL_PATH / "root-cause-state-register-after-retrieval.jsonl"
        )
        after = downstream._updated_state_register(
            repo_root=REPO_ROOT,
            reviews=self.reviews,
            e7_errors=self.e7_errors,
        )
        self.assertEqual(len(after), 250)
        self.assertEqual([row["case_id"] for row in after], [row["case_id"] for row in before])
        owned = set(downstream.OWNED_STATE_FIELDS)
        for old, new in zip(before, after):
            if old["condition_id"] == downstream.FULL_CONTEXT_CONDITION:
                self.assertEqual(canonical_json_bytes(old), canonical_json_bytes(new))
            for field in set(old) - owned:
                self.assertEqual(
                    canonical_json_bytes({"value": old[field]}),
                    canonical_json_bytes({"value": new[field]}),
                    (old["case_id"], field),
                )
        applicable = [row for row in after if row["condition_id"] != downstream.FULL_CONTEXT_CONDITION]
        self.assertTrue(all(row["final_input_sufficiency_state"] not in {"pending", "not_applicable"} for row in applicable))


if __name__ == "__main__":
    unittest.main()
