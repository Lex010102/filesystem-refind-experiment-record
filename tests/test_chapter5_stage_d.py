from __future__ import annotations

import hashlib
import json
import math
import os
import shutil
import tempfile
import unittest
from collections import Counter, defaultdict
from pathlib import Path

from fs_memory_lab.chapter5_stage_d import (
    STAGE_D_PROTOCOL_VERSION,
    TIE_TOLERANCE,
    audit_stage_d_output,
)
from fs_memory_lab.evidence import EvidenceValidationError, canonical_json_bytes


REPO_ROOT = Path(__file__).resolve().parents[1]
STAGE_A = REPO_ROOT / "artifacts/chapter5-main60-analysis-v1/stage-a"
STAGE_B = REPO_ROOT / "artifacts/chapter5-main60-analysis-v1/stage-b"
STAGE_C = REPO_ROOT / "artifacts/chapter5-main60-analysis-v1/stage-c"
_DEFAULT_STAGE_D = REPO_ROOT / "artifacts/chapter5-main60-analysis-v1/stage-d-auto"
if not _DEFAULT_STAGE_D.exists():
    _DEFAULT_STAGE_D = REPO_ROOT / "artifacts/chapter5-main60-analysis-v1/stage-d"
STAGE_D = Path(os.environ.get("CHAPTER5_STAGE_D_DIR", _DEFAULT_STAGE_D)).resolve()


TABLE_COUNTS = {
    "comparison-register": 20,
    "evidence-answer-question": 812,
    "conversion-matrices": 756,
    "conversion-summaries": 84,
    "all-hit-strict-transitions": 126,
    "any-hit-strict-transitions": 126,
    "multi-source-coverage-transitions": 252,
    "category-effects": 224,
    "category-interactions": 32,
    "appendix-sensitivity-category-effects": 64,
    "process-condition-summaries": 312,
    "process-paired-summaries": 468,
    "trace-review-candidates": 24,
}

MAIN_SIMPLE_IDS = {
    "storage_r1_e3_minus_e1",
    "storage_r2_e4_minus_e2",
    "retrieval_s1_e2_minus_e1",
    "retrieval_s2_e4_minus_e3",
    "curated_access_e6_minus_e5",
    "curated_vs_foldered_r1_e5_minus_e3",
    "curated_adapted_vs_foldered_raw_e6_minus_e4",
}
SENSITIVITY_IDS = {
    "curated_vs_flat_r1_e5_minus_e1",
    "curated_adapted_vs_flat_raw_e6_minus_e2",
}
INTERACTION_ID = "storage_retrieval_did_e4_e2_minus_e3_e1"
ANSWER_CATEGORY_DENOMINATORS = {1: 13, 2: 13, 3: 7, 4: 27}
EVIDENCE_CATEGORY_DENOMINATORS = {1: 13, 2: 13, 3: 5, 4: 27}
METRIC_FIELDS = {
    "token_f1": "token_f1",
    "strict_accuracy": "strict_score",
    "soft_semantic_score": "soft_semantic_score",
    "evidence_recall": "evidence_recall",
}


def _json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def _jsonl(path: Path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _mean(values):
    return math.fsum(float(value) for value in values) / len(values)


def _change(value: float) -> str:
    if value > TIE_TOLERANCE:
        return "up"
    if value < -TIE_TOLERANCE:
        return "down"
    return "same"


def _answer_change(value: float) -> str:
    return {"up": "improve", "same": "same", "down": "decline"}[_change(value)]


@unittest.skipUnless(
    (STAGE_D / "STAGE-D-AUTO.PASSED").is_file(),
    "formal Stage D automatic artifact not built",
)
class Chapter5StageDAutomaticArtifactTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.audit = _json(STAGE_D / "audit.json")
        cls.marker = _json(STAGE_D / "STAGE-D-AUTO.PASSED")
        cls.tables = {name: _jsonl(STAGE_D / f"{name}.jsonl") for name in TABLE_COUNTS}
        cls.a_rows = _jsonl(STAGE_A / "rq1-analysis-view.jsonl")
        cls.a_index = {
            (row["backbone_id"], row["condition_id"], row["question_id"]): row
            for row in cls.a_rows
        }
        cls.a_id_index = {row["analysis_row_id"]: row for row in cls.a_rows}
        cls.register = {
            (row["backbone_id"], row["comparison_id"]): row
            for row in cls.tables["comparison-register"]
        }

    def test_independent_audit_exact_file_set_hashes_and_auto_only_marker(self):
        result = audit_stage_d_output(
            stage_a_dir=STAGE_A,
            stage_b_dir=STAGE_B,
            stage_c_dir=STAGE_C,
            output_dir=STAGE_D,
        )
        self.assertEqual(result["status"], "passed")
        self.assertEqual(result["protocol_version"], STAGE_D_PROTOCOL_VERSION)
        self.assertEqual(result["phase"], "automatic")
        self.assertEqual(result["table_rows"], TABLE_COUNTS)
        self.assertEqual(self.marker["audit_id"], self.audit["audit_id"])
        self.assertEqual(self.marker["audit_sha256"], _sha256(STAGE_D / "audit.json"))
        self.assertTrue((STAGE_D / "STAGE-D-AUTO.PASSED").is_file())
        self.assertFalse((STAGE_D / "STAGE-D.PASSED").exists())

        expected_names = {"README.md", "schema.json", "source-manifest.json", "audit.json", "STAGE-D-AUTO.PASSED"}
        for name in TABLE_COUNTS:
            expected_names.update({f"{name}.jsonl", f"{name}.csv"})
        self.assertEqual({path.name for path in STAGE_D.iterdir()}, expected_names)
        self.assertEqual({name: len(rows) for name, rows in self.tables.items()}, TABLE_COUNTS)
        for name, digest in self.audit["output_sha256"].items():
            self.assertEqual(_sha256(STAGE_D / name), digest, name)

    def test_register_has_frozen_roles_and_backbone_separation(self):
        rows = self.tables["comparison-register"]
        self.assertEqual({row["backbone_id"] for row in rows}, {"qwen", "deepseek"})
        self.assertEqual(len({row["comparison_register_id"] for row in rows}), 20)
        expected_ids = MAIN_SIMPLE_IDS | SENSITIVITY_IDS | {INTERACTION_ID}
        for backbone in ("qwen", "deepseek"):
            selected = [row for row in rows if row["backbone_id"] == backbone]
            self.assertEqual({row["comparison_id"] for row in selected}, expected_ids)
            self.assertEqual(
                Counter(row["publication_role"] for row in selected),
                Counter({
                    "main_core": 5,
                    "main_descriptive": 2,
                    "main_core_interaction": 1,
                    "appendix_sensitivity": 2,
                }),
            )
            self.assertEqual(
                {row["comparison_id"] for row in selected if row["comparison_type"] == "simple"},
                MAIN_SIMPLE_IDS | SENSITIVITY_IDS,
            )
            interaction = [row for row in selected if row["comparison_type"] == "interaction"]
            self.assertEqual(len(interaction), 1)
            self.assertEqual(interaction[0]["comparison_id"], INTERACTION_ID)
        self.assertEqual(
            {row["comparison_id"] for row in rows if row["output_partition"] == "appendix_sensitivity"},
            SENSITIVITY_IDS,
        )

    def test_conversion_question_rows_and_matrix_summary_folding(self):
        questions = self.tables["evidence-answer-question"]
        self.assertEqual(
            Counter((row["comparison_id"], row["backbone_id"]) for row in questions),
            Counter({(comparison, backbone): 58 for comparison in MAIN_SIMPLE_IDS for backbone in ("qwen", "deepseek")}),
        )
        self.assertTrue({row["comparison_id"] for row in questions}.isdisjoint(SENSITIVITY_IDS))

        for row in questions:
            self.assertEqual(row["evidence_recall_state"], _change(row["evidence_recall_difference"]))
            self.assertEqual(row["strict_change"], _answer_change(row["strict_difference"]))
            self.assertEqual(row["f1_change"], _answer_change(row["f1_difference"]))
            self.assertEqual(row["soft_change"], _answer_change(row["soft_difference"]))
            self.assertEqual(row["multi_gold_source"], row["gold_source_count"] > 1)

        matrices = self.tables["conversion-matrices"]
        summaries = self.tables["conversion-summaries"]
        qgroups = defaultdict(list)
        for row in questions:
            qgroups[(row["comparison_id"], row["backbone_id"])].append(row)
        mgroups = defaultdict(list)
        for row in matrices:
            mgroups[(row["comparison_id"], row["backbone_id"], row["subset_id"], row["answer_metric_id"])].append(row)
        summary_index = {
            (row["comparison_id"], row["backbone_id"], row["subset_id"], row["answer_metric_id"]): row
            for row in summaries
        }
        metric_fields = {
            "strict_accuracy": "strict_change",
            "token_f1": "f1_change",
            "soft_semantic_score": "soft_change",
        }
        for key2, source in qgroups.items():
            for subset_id, subset in (
                ("evidence_eligible_58", source),
                ("multi_gold_source_19", [row for row in source if row["multi_gold_source"]]),
            ):
                expected_n = 58 if subset_id == "evidence_eligible_58" else 19
                self.assertEqual(len(subset), expected_n)
                for metric_id, change_field in metric_fields.items():
                    key = (*key2, subset_id, metric_id)
                    cells = mgroups[key]
                    self.assertEqual(len(cells), 9)
                    self.assertEqual(sum(row["count"] for row in cells), expected_n)
                    counts = Counter((row["evidence_recall_state"], row[change_field]) for row in subset)
                    for cell in cells:
                        expected = counts[(cell["evidence_recall_state"], cell["answer_change"])]
                        self.assertEqual(cell["count"], expected)
                        self.assertAlmostEqual(cell["proportion"], expected / expected_n, places=15)
                    out = summary_index[key]
                    self.assertEqual(out["denominator"], expected_n)
                    self.assertEqual(
                        out["evidence_up_answer_improve"],
                        sum(row["evidence_recall_state"] == "up" and row[change_field] == "improve" for row in subset),
                    )
                    self.assertEqual(
                        out["evidence_up_answer_not_improve"],
                        sum(row["evidence_recall_state"] == "up" and row[change_field] != "improve" for row in subset),
                    )
                    self.assertEqual(
                        out["evidence_same_answer_improve"],
                        sum(row["evidence_recall_state"] == "same" and row[change_field] == "improve" for row in subset),
                    )
                    self.assertEqual(
                        out["evidence_down_without_answer_harm"],
                        sum(row["evidence_recall_state"] == "down" and row[change_field] != "decline" for row in subset),
                    )

    def test_any_all_hit_and_multi_source_folds(self):
        questions = self.tables["evidence-answer-question"]
        qgroups = defaultdict(list)
        for row in questions:
            qgroups[(row["comparison_id"], row["backbone_id"])].append(row)
        for table_name, source_prefix, baseline_field, target_field in (
            ("all-hit-strict-transitions", "evidence_all_hit_change", "baseline_evidence_all_hit", "target_evidence_all_hit"),
            ("any-hit-strict-transitions", "evidence_any_hit_change", "baseline_evidence_any_hit", "target_evidence_any_hit"),
        ):
            groups = defaultdict(list)
            for row in self.tables[table_name]:
                groups[(row["comparison_id"], row["backbone_id"])].append(row)
            for key, source in qgroups.items():
                counts = Counter()
                for row in source:
                    delta = int(row[target_field]) - int(row[baseline_field])
                    counts[({1: "up", 0: "same", -1: "down"}[delta], row["strict_change"])] += 1
                cells = groups[key]
                self.assertEqual(len(cells), 9)
                self.assertEqual(sum(row["count"] for row in cells), 58)
                for cell in cells:
                    self.assertEqual(cell["count"], counts[(cell[source_prefix], cell["strict_change"])])

        multi_groups = defaultdict(list)
        for row in self.tables["multi-source-coverage-transitions"]:
            multi_groups[(row["comparison_id"], row["backbone_id"], row["coverage_metric_id"])].append(row)
        for key2, source_all in qgroups.items():
            source = [row for row in source_all if row["multi_gold_source"]]
            self.assertEqual(len(source), 19)
            for metric, baseline_field, target_field in (
                ("evidence_any_hit", "baseline_evidence_any_hit", "target_evidence_any_hit"),
                ("evidence_all_hit", "baseline_evidence_all_hit", "target_evidence_all_hit"),
            ):
                counts = Counter()
                for row in source:
                    delta = int(row[target_field]) - int(row[baseline_field])
                    counts[({1: "up", 0: "same", -1: "down"}[delta], row["strict_change"])] += 1
                cells = multi_groups[(*key2, metric)]
                self.assertEqual(len(cells), 9)
                self.assertEqual(sum(row["count"] for row in cells), 19)
                for cell in cells:
                    self.assertEqual(cell["count"], counts[(cell["coverage_change"], cell["strict_change"])])

    def _verify_category_effect_table(self, table_name: str, expected_ids: set[str]):
        rows = self.tables[table_name]
        self.assertEqual({row["comparison_id"] for row in rows}, expected_ids)
        for out in rows:
            reg = self.register[(out["backbone_id"], out["comparison_id"])]
            baseline = reg["baseline_condition"]
            target = reg["target_condition"]
            field = METRIC_FIELDS[out["metric_id"]]
            source = [
                row for row in self.a_rows
                if row["backbone_id"] == out["backbone_id"]
                and row["condition_id"] == baseline
                and row["category"] == out["category"]
                and (out["metric_id"] != "evidence_recall" or row["evidence_eligible"] is True)
            ]
            expected_n = (
                EVIDENCE_CATEGORY_DENOMINATORS[out["category"]]
                if out["metric_id"] == "evidence_recall"
                else ANSWER_CATEGORY_DENOMINATORS[out["category"]]
            )
            self.assertEqual(len(source), expected_n)
            target_rows = [
                self.a_index[(out["backbone_id"], target, row["question_id"])] for row in source
            ]
            differences = [float(t[field]) - float(b[field]) for b, t in zip(source, target_rows)]
            self.assertEqual(out["denominator"], expected_n)
            self.assertAlmostEqual(out["baseline_mean"], _mean([row[field] for row in source]), places=15)
            self.assertAlmostEqual(out["target_mean"], _mean([row[field] for row in target_rows]), places=15)
            self.assertAlmostEqual(out["mean_difference"], _mean(differences), places=15)
            self.assertEqual(out["win_count"], sum(value > TIE_TOLERANCE for value in differences))
            self.assertEqual(out["tie_count"], sum(abs(value) <= TIE_TOLERANCE for value in differences))
            self.assertEqual(out["loss_count"], sum(value < -TIE_TOLERANCE for value in differences))
            self.assertFalse(out["bootstrap_computed"])
            self.assertEqual(out["inferential_status"], "descriptive_only")

    def test_category_effects_and_sensitivity_recompute_from_stage_a(self):
        self._verify_category_effect_table("category-effects", MAIN_SIMPLE_IDS)
        self._verify_category_effect_table("appendix-sensitivity-category-effects", SENSITIVITY_IDS)

    def test_category_interaction_did_recomputes_from_stage_a(self):
        rows = self.tables["category-interactions"]
        self.assertEqual(len(rows), 32)
        self.assertEqual({row["comparison_id"] for row in rows}, {INTERACTION_ID})
        for out in rows:
            field = METRIC_FIELDS[out["metric_id"]]
            questions = [
                row for row in self.a_rows
                if row["backbone_id"] == out["backbone_id"]
                and row["condition_id"] == "E1"
                and row["category"] == out["category"]
                and (out["metric_id"] != "evidence_recall" or row["evidence_eligible"] is True)
            ]
            expected_n = (
                EVIDENCE_CATEGORY_DENOMINATORS[out["category"]]
                if out["metric_id"] == "evidence_recall"
                else ANSWER_CATEGORY_DENOMINATORS[out["category"]]
            )
            self.assertEqual(len(questions), expected_n)
            values = {
                condition: [
                    float(self.a_index[(out["backbone_id"], condition, row["question_id"])][field])
                    for row in questions
                ]
                for condition in ("E1", "E2", "E3", "E4")
            }
            did = [
                (values["E4"][i] - values["E2"][i]) - (values["E3"][i] - values["E1"][i])
                for i in range(expected_n)
            ]
            self.assertEqual(out["denominator"], expected_n)
            self.assertAlmostEqual(out["mean_did"], _mean(did), places=15)
            for condition in values:
                self.assertAlmostEqual(out[f"mean_{condition.lower()}"], _mean(values[condition]), places=15)
            self.assertEqual(out["positive_count"], sum(value > TIE_TOLERANCE for value in did))
            self.assertEqual(out["zero_count"], sum(abs(value) <= TIE_TOLERANCE for value in did))
            self.assertEqual(out["negative_count"], sum(value < -TIE_TOLERANCE for value in did))
            self.assertFalse(out["bootstrap_computed"])

    def test_process_availability_noncommensurability_and_token_contract(self):
        conditions = self.tables["process-condition-summaries"]
        pairs = self.tables["process-paired-summaries"]
        self.assertTrue(all(row["failure_tokens_in_query_total"] is False for row in conditions + pairs))

        unavailable = [
            row for row in conditions
            if row["metric_id"] in {"native_latency_ms", "failed_attempt_tokens"}
        ]
        self.assertEqual(len(unavailable), 24)
        for row in unavailable:
            self.assertFalse(row["applicable"])
            self.assertEqual(row["availability_status"], "unavailable_or_not_applicable")
            self.assertEqual(row["denominator"], 0)
            self.assertIsNone(row["mean"])

        normalized = [row for row in conditions if row["metric_id"] == "answer_normalized_tokens"]
        self.assertEqual(len(normalized), 12)
        for out in normalized:
            values = [
                row["answer_normalized_tokens"] for row in self.a_rows
                if row["backbone_id"] == out["backbone_id"] and row["condition_id"] == out["condition_id"]
            ]
            self.assertEqual(len(values), 60)
            self.assertTrue(out["applicable"])
            self.assertEqual(out["denominator"], 60)
            self.assertAlmostEqual(out["mean"], _mean(values), places=15)

        r1_conditions = {"E1", "E3", "E5"}
        for row in conditions:
            if row["metric_id"] in {"r1_provider_rounds", "r1_filesystem_tool_calls"}:
                self.assertEqual(row["applicable"], row["condition_id"] in r1_conditions)
                self.assertIn(row["comparability_group"], {"r1_rounds_only", "r1_only"})
            if row["metric_id"] == "ranked_retrieval_actions":
                self.assertEqual(row["applicable"], row["condition_id"] in {"E2", "E4", "E6"})
                self.assertEqual(row["comparability_group"], "r2_r3_actions_only")

        for row in pairs:
            if row["metric_id"] in {"native_latency_ms", "failed_attempt_tokens"}:
                self.assertFalse(row["paired_comparison_allowed"])
                self.assertEqual(row["comparison_status"], "unavailable")
                self.assertIsNone(row["mean_paired_difference"])
            if row["metric_id"] in {"r1_provider_rounds", "r1_filesystem_tool_calls", "ranked_retrieval_actions"}:
                if not (row["baseline_applicable"] and row["target_applicable"]):
                    self.assertFalse(row["paired_comparison_allowed"])
                    self.assertEqual(row["comparison_status"], "noncommensurate_endpoints")
                    self.assertIsNone(row["mean_paired_difference"])

    def test_trace_candidates_are_frozen_identifier_only_and_source_valid(self):
        candidates = self.tables["trace-review-candidates"]
        expected_slots = {
            (module, backbone, role)
            for module in ("5.2.1", "5.2.2", "5.2.3", "5.2.4")
            for backbone in ("qwen", "deepseek")
            for role in ("repair", "harm", "counterexample")
        }
        self.assertEqual(
            {(row["module_id"], row["backbone_id"], row["candidate_role"]) for row in candidates},
            expected_slots,
        )
        self.assertEqual({row["category"] for row in candidates}, {1, 2, 3, 4})
        self.assertEqual(len({row["trace_candidate_id"] for row in candidates}), 24)
        prohibited = (
            "question_text", "reference_answer", "candidate_answer", "answer_text",
            "evidence_text", "rationale", "judge_reason", "prompt",
        )
        for row in candidates:
            self.assertEqual(row["review_status"], "pending")
            self.assertFalse(row["manual_content_inspected"])
            self.assertFalse(any(fragment in field.lower() for field in row for fragment in prohibited))
            sizes = {
                len(row["analysis_row_ids"]), len(row["source_record_ids"]),
                len(row["source_record_paths"]), len(row["source_record_file_sha256"]),
                len(row["source_record_payload_sha256"]), len(row["condition_ids"]),
            }
            self.assertEqual(len(sizes), 1)
            for analysis_id, record_id, relative_path, file_hash, payload_hash in zip(
                row["analysis_row_ids"], row["source_record_ids"], row["source_record_paths"],
                row["source_record_file_sha256"], row["source_record_payload_sha256"],
            ):
                self.assertIn(analysis_id, self.a_id_index)
                source = (REPO_ROOT / relative_path).resolve()
                self.assertTrue(source.is_relative_to(REPO_ROOT.resolve()))
                self.assertTrue(source.is_file())
                self.assertEqual(_sha256(source), file_hash)
                payload = _json(source)
                self.assertEqual(payload["record_id"], record_id)
                self.assertEqual(hashlib.sha256(canonical_json_bytes(payload)).hexdigest(), payload_hash)

    def test_prohibited_scope_flags_and_no_text_fields(self):
        for flag in (
            "bootstrap_computed",
            "cross_backbone_effect_computed",
            "e7_computed",
            "full_context_computed",
            "global_error_census_computed",
            "pareto_analysis_computed",
            "system_recommendation_computed",
            "final_rq1_conclusion_computed",
            "old_new_question_split_computed",
        ):
            self.assertIs(self.audit.get(flag), False, flag)
        self.assertTrue(self.audit["automatic_phase_completed"])
        self.assertTrue(self.audit["trace_candidates_frozen"])
        self.assertEqual(self.audit["trace_review_status"], "pending")
        self.assertFalse(self.audit["manual_trace_review_completed"])
        self.assertFalse(self.audit["final_stage_d_marker_emitted"])
        self.assertFalse(self.audit["source_trace_content_read"])
        self.assertFalse(self.audit["text_bearing_fields_copied"])
        prohibited = (
            "question_text", "reference_answer", "candidate_answer", "answer_text",
            "evidence_text", "rationale", "judge_reason", "prompt",
        )
        for table_name, rows in self.tables.items():
            for row in rows:
                self.assertFalse(
                    any(fragment in field.lower() for field in row for fragment in prohibited),
                    table_name,
                )

    def test_tamper_is_rejected(self):
        with tempfile.TemporaryDirectory(prefix="chapter5-stage-d-test-") as temp:
            target = Path(temp) / "stage-d"
            shutil.copytree(STAGE_D, target)
            path = target / "conversion-summaries.jsonl"
            path.write_bytes(path.read_bytes() + b"\n")
            with self.assertRaises(EvidenceValidationError):
                audit_stage_d_output(
                    stage_a_dir=STAGE_A,
                    stage_b_dir=STAGE_B,
                    stage_c_dir=STAGE_C,
                    output_dir=target,
                )


if __name__ == "__main__":
    unittest.main()
