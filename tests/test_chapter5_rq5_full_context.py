from __future__ import annotations

import json
import copy
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import fs_memory_lab.chapter5_rq5_full_context as full_context
from fs_memory_lab.chapter5_stage_b import _read_jsonl
from fs_memory_lab.evidence import canonical_json_bytes


REPO_ROOT = Path(__file__).resolve().parents[1]


class Chapter5RQ5FullContextTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.repo_temp = tempfile.TemporaryDirectory(prefix=".rq5-full-context-test-", dir=REPO_ROOT)
        cls.fixture_dir = Path(cls.repo_temp.name) / "downstream"
        cls.fixture_dir.mkdir()
        cls.predecessor_path = cls.fixture_dir / "root-cause-state-register-after-downstream.jsonl"
        source = REPO_ROOT / "artifacts/chapter5-main60-analysis-v1/rq5-retrieval-audit/root-cause-state-register-after-retrieval.jsonl"
        shutil.copyfile(source, cls.predecessor_path)
        cls.fake_audit = {
            "status": "passed",
            "protocol_version": full_context.DOWNSTREAM_PROTOCOL_VERSION,
            "audit_id": "rq5-downstream-audit-" + "0" * 64,
        }
        (cls.fixture_dir / "audit.json").write_bytes(
            canonical_json_bytes(cls.fake_audit) + b"\n"
        )
        (cls.fixture_dir / "RQ5-DOWNSTREAM.PASSED").write_bytes(
            canonical_json_bytes(
                {
                    "status": "passed",
                    "protocol_version": full_context.DOWNSTREAM_PROTOCOL_VERSION,
                    "audit_id": cls.fake_audit["audit_id"],
                }
            )
            + b"\n"
        )
        cls.review_path = REPO_ROOT / full_context.DEFAULT_REVIEW_PATH
        cls.reviews = full_context._review_rows(REPO_ROOT, cls.review_path)
        cls.predecessor = _read_jsonl(cls.predecessor_path)

    @classmethod
    def tearDownClass(cls):
        cls.repo_temp.cleanup()

    def test_actual_review_covers_exact_unique_full_context_errors(self):
        self.assertEqual(len(self.reviews), 14)
        self.assertEqual(len({row["case_id"] for row in self.reviews}), 14)
        self.assertEqual(len({row["question_id"] for row in self.reviews}), 14)
        self.assertTrue(all("rationale" not in row for row in self.reviews))
        for row in self.reviews:
            if row["final_input_sufficiency_state"] != "sufficient":
                self.assertEqual(row["long_context_utilisation_state"], "indeterminate")
                self.assertEqual(row["answerer_utilisation_state"], "indeterminate")

    def test_rq4_and_review_sources_are_frozen(self):
        result = full_context._validate_rq4(REPO_ROOT)
        self.assertEqual(result["audit_id"], full_context.EXPECTED_RQ4_AUDIT_ID)
        self.assertEqual(full_context._sha256_file(self.review_path), full_context.EXPECTED_REVIEW_SHA256)

    def test_full_context_updates_only_three_owned_fields(self):
        after = full_context._updated_register(self.predecessor, self.reviews)
        self.assertEqual(len(after), 250)
        owned = set(full_context.OWNED_STATE_FIELDS)
        for old, new in zip(self.predecessor, after):
            changed = {key for key in set(old) | set(new) if old.get(key) != new.get(key)}
            self.assertLessEqual(changed, owned)
            if old["condition_id"] != full_context.FULL_CONTEXT_CONDITION:
                self.assertEqual(canonical_json_bytes(old), canonical_json_bytes(new))
            else:
                self.assertTrue(all(new[field] not in {"pending", "not_applicable"} for field in owned))
                self.assertEqual(new["evaluation_agreement_state"], old["evaluation_agreement_state"])
                self.assertEqual(new["primary_cause"], old["primary_cause"])
                self.assertEqual(new["secondary_causes"], old["secondary_causes"])

    def test_diagnostics_keep_unique_question_and_pair_denominators_separate(self):
        rows = full_context._diagnostics(REPO_ROOT)
        self.assertEqual(len(rows), 32)
        self.assertEqual({row["selective_condition"] for row in rows}, {f"E{i}" for i in range(1, 8)} | {"ANY_SELECTIVE"})
        self.assertTrue(all(row["comparison_is_descriptive"] for row in rows))
        self.assertTrue(all("full_context_evidence_recall" not in row for row in rows))
        pairwise = [row for row in rows if row["comparison_scope"] == "pairwise_selective_condition"]
        self.assertEqual(len(pairwise), 28)
        self.assertTrue(all(row["denominator"] == 60 for row in pairwise))
        for condition, expected in full_context.EXPECTED_PAIRWISE_COUNTS.items():
            actual = {row["strict_quadrant"]: row["count"] for row in pairwise if row["selective_condition"] == condition}
            self.assertEqual(actual, expected)
        any_selective = [row for row in rows if row["comparison_scope"] == "any_selective"]
        self.assertEqual(len(any_selective), 4)
        self.assertEqual({row["strict_quadrant"]: row["count"] for row in any_selective}, full_context.EXPECTED_ANY_SELECTIVE_COUNTS)
        self.assertTrue(all(row["oracle_style_descriptive"] and not row["deployable_comparison"] for row in any_selective))

        questions = full_context._question_diagnostics(REPO_ROOT)
        self.assertEqual(len(questions), 60)
        self.assertEqual(
            {state: sum(row["any_selective_quadrant"] == state for row in questions) for state in full_context.EXPECTED_ANY_SELECTIVE_COUNTS},
            full_context.EXPECTED_ANY_SELECTIVE_COUNTS,
        )
        self.assertEqual(
            {count: sum(row["selective_correct_count"] == count for row in questions if row["strict_score"] == 0.0) for count in (0, 1, 2, 4, 7)},
            {0: 8, 1: 3, 2: 1, 4: 1, 7: 1},
        )

    def test_evidence_positions_use_only_the_58_eligible_questions(self):
        questions = full_context._question_diagnostics(REPO_ROOT)
        positions = full_context._evidence_positions(REPO_ROOT, questions)
        self.assertEqual(len(positions), 58)
        self.assertTrue(all(row["evidence_recall_applicable"] is False for row in positions))
        self.assertTrue(all(row["full_context_turn_count"] == 568 for row in positions))
        self.assertTrue(all(row["full_context_characters"] == 108960 for row in positions))
        summary = full_context._position_summary(positions)
        overall = {row["strict_outcome"]: row for row in summary if row["category_scope"] == "ALL"}
        self.assertEqual({key: value["question_count"] for key, value in overall.items()}, {"strict_correct": 45, "strict_noncorrect": 13})
        self.assertAlmostEqual(overall["strict_noncorrect"]["mean_earliest_normalized_turn_position"], 0.40293040293040294)
        self.assertAlmostEqual(overall["strict_correct"]["mean_earliest_normalized_turn_position"], 0.5115030374289634)
        self.assertLess(
            overall["strict_noncorrect"]["mean_midrange_normalized_turn_position"],
            overall["strict_correct"]["mean_midrange_normalized_turn_position"],
        )
        self.assertTrue(
            all(
                row["position_normalization_basis"]
                == "zero_based_global_turn_ordinal_divided_by_567"
                and row["midrange_definition"]
                == "midpoint_of_earliest_and_latest_gold_turn_positions"
                for row in positions
            )
        )

    def test_strict_correct_record_payload_drift_is_rejected(self):
        questions = full_context._question_diagnostics(REPO_ROOT)
        target_question = next(
            row for row in questions
            if row["strict_score"] == 1.0 and row["evidence_eligible"]
        )
        stage = {
            str(row["question_id"]): row
            for row in _read_jsonl(REPO_ROOT / full_context.STAGE_A_PATH)
            if row["condition_id"] == full_context.FULL_CONTEXT_CONDITION
        }
        target_path = full_context._safe_file(
            REPO_ROOT,
            str(stage[target_question["question_id"]]["source_record_path"]),
        )
        original_read_json = full_context._read_json
        tampered = copy.deepcopy(original_read_json(target_path))
        tampered["deployment_metrics"]["elapsed_ms"] += 1

        def read_json_with_one_drift(path):
            if Path(path).resolve() == target_path.resolve():
                return tampered
            return original_read_json(path)

        with patch.object(full_context, "_read_json", side_effect=read_json_with_one_drift):
            with self.assertRaises(Exception):
                full_context._evidence_positions(REPO_ROOT, questions)

    def test_answer_profile_and_category_summary_use_unique_questions(self):
        questions = full_context._question_diagnostics(REPO_ROOT)
        profile = {row["strict_outcome"]: row for row in full_context._answer_profile(questions)}
        self.assertEqual(profile["strict_correct"]["question_count"], 46)
        self.assertEqual(profile["strict_noncorrect"]["question_count"], 14)
        self.assertAlmostEqual(profile["strict_correct"]["mean_answer_normalized_tokens"], 20.782608695652176)
        self.assertAlmostEqual(profile["strict_noncorrect"]["mean_answer_normalized_tokens"], 31.857142857142858)
        categories = {row["category_name"]: row for row in full_context._category_summary(questions)}
        self.assertEqual({key: value["strict_error_count"] for key, value in categories.items()}, {"multi-hop": 2, "open-domain": 4, "single-hop": 5, "temporal": 3})
        self.assertEqual({key: value["question_count"] for key, value in categories.items()}, {"multi-hop": 13, "open-domain": 7, "single-hop": 27, "temporal": 13})

    def test_summary_uses_fourteen_error_denominator_and_category_scopes(self):
        rows = full_context._summary(self.reviews)
        overall = [row for row in rows if row["category_scope"] == "ALL"]
        self.assertTrue(overall)
        self.assertTrue(all(row["denominator"] == 14 for row in overall))
        self.assertEqual(
            {row["dimension"] for row in overall},
            {"content_state", "final_input_sufficiency", "long_context_utilisation", "answerer_utilisation", "answer_form", "primary_mechanism"},
        )
        category_denominators = {"multi-hop": 2, "open-domain": 4, "single-hop": 5, "temporal": 3}
        for category, denominator in category_denominators.items():
            scoped = [row for row in rows if row["category_scope"] == category]
            self.assertTrue(scoped)
            self.assertTrue(all(row["denominator"] == denominator for row in scoped))

    def test_temp_build_emits_auditable_text_free_artifacts(self):
        with tempfile.TemporaryDirectory(prefix="rq5-full-context-output-") as temp:
            output = Path(temp) / "output"
            with patch.object(full_context, "audit_rq5_downstream_output", return_value=self.fake_audit):
                audit = full_context.build_rq5_full_context(
                    repo_root=REPO_ROOT,
                    output_dir=output,
                    downstream_dir=self.fixture_dir,
                    review_path=self.review_path,
                )
                repeated = full_context.audit_rq5_full_context_output(
                    repo_root=REPO_ROOT,
                    output_dir=output,
                    downstream_dir=self.fixture_dir,
                    review_path=self.review_path,
                )
            self.assertEqual(audit["audit_id"], repeated["audit_id"])
            self.assertEqual(audit["full_context_error_rows"], 14)
            self.assertEqual(audit["full_context_unique_question_rows"], 60)
            self.assertEqual(audit["evidence_position_rows"], 58)
            self.assertEqual(audit["selective_diagnostic_rows"], 32)
            self.assertFalse(audit["repair_mechanism_analysis_computed"])
            self.assertFalse(audit["evaluation_analysis_computed"])
            self.assertFalse(audit["primary_attribution_computed"])
            self.assertTrue((output / "RQ5-FULL-CONTEXT.PASSED").is_file())
            self.assertTrue((output / "README.md").is_file())
            schema = json.loads((output / "schema.json").read_text(encoding="utf-8"))
            self.assertEqual(schema["post_full_context_state_jsonl"], full_context.POST_FULL_CONTEXT_STATE_PATH)
            self.assertEqual(schema["tables"]["full-context-diagnostic-matrix"]["rows"], 32)
            self.assertEqual(schema["tables"]["full-context-question-diagnostics"]["rows"], 60)
            self.assertEqual(schema["tables"]["evidence-position-diagnostics"]["rows"], 58)
            for path in output.glob("*.jsonl"):
                for row in _read_jsonl(path):
                    self.assertFalse({key.casefold() for key in row} & full_context.FORBIDDEN_FIELDS)

    def test_tampered_review_and_output_are_rejected(self):
        with tempfile.TemporaryDirectory(prefix="rq5-full-context-tamper-") as temp:
            review = Path(temp) / "review.json"
            payload = json.loads(self.review_path.read_text(encoding="utf-8"))
            payload["cases"][0]["question_id"] = payload["cases"][1]["question_id"]
            review.write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaises(Exception):
                full_context._review_rows(REPO_ROOT, review)

        with tempfile.TemporaryDirectory(prefix="rq5-full-context-output-") as temp:
            output = Path(temp) / "output"
            with patch.object(full_context, "audit_rq5_downstream_output", return_value=self.fake_audit):
                full_context.build_rq5_full_context(
                    repo_root=REPO_ROOT,
                    output_dir=output,
                    downstream_dir=self.fixture_dir,
                    review_path=self.review_path,
                )
                path = output / "full-context-mechanisms.jsonl"
                path.write_bytes(path.read_bytes() + b"{}\n")
                with self.assertRaises(Exception):
                    full_context.audit_rq5_full_context_output(
                        repo_root=REPO_ROOT,
                        output_dir=output,
                        downstream_dir=self.fixture_dir,
                        review_path=self.review_path,
                    )


if __name__ == "__main__":
    unittest.main()
