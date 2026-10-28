from __future__ import annotations

import hashlib
import json
import shutil
import tempfile
import unittest
from collections import Counter, defaultdict
from pathlib import Path

from fs_memory_lab.chapter5_stage_e import (
    EXPECTED_MULTI_GOLD_SOURCE_COUNT,
    EVIDENCE_ELIGIBLE_COUNT,
    QUESTION_COUNT,
    STAGE_E_PROTOCOL_VERSION,
    audit_stage_e_output,
    build_stage_e,
)
from fs_memory_lab.evidence import EvidenceValidationError


REPO_ROOT = Path(__file__).resolve().parents[1]
STAGE_A = REPO_ROOT / "artifacts/chapter5-main60-analysis-v1/stage-a"
STAGE_B = REPO_ROOT / "artifacts/chapter5-main60-analysis-v1/stage-b"
STAGE_C = REPO_ROOT / "artifacts/chapter5-main60-analysis-v1/stage-c"
STAGE_D = REPO_ROOT / "artifacts/chapter5-main60-analysis-v1/stage-d"
S3_MANIFEST = REPO_ROOT / "experiments/locomo-conv50-v1/manifests/s3-curated.json"


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


def _kwargs(output_dir: Path):
    return {
        "repo_root": REPO_ROOT,
        "stage_a_dir": STAGE_A,
        "stage_b_dir": STAGE_B,
        "stage_c_dir": STAGE_C,
        "stage_d_dir": STAGE_D,
        "s3_manifest_path": S3_MANIFEST,
        "output_dir": output_dir,
    }


class Chapter5StageERQ1ArtifactTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix="chapter5-stage-e-test-")
        cls.output = Path(cls.temp.name) / "stage-e-rq1"
        cls.build_result = build_stage_e(**_kwargs(cls.output))
        cls.audit = _json(cls.output / "audit.json")
        cls.marker = _json(cls.output / "STAGE-E-RQ1.PASSED")
        cls.schema = _json(cls.output / "schema.json")

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def test_normal_build_and_independent_audit(self):
        self.assertEqual(self.build_result["status"], "passed")
        self.assertEqual(self.build_result["protocol_version"], STAGE_E_PROTOCOL_VERSION)
        result = audit_stage_e_output(**_kwargs(self.output))
        self.assertEqual(result["status"], "passed")
        self.assertEqual(result["audit_id"], self.audit["audit_id"])
        self.assertEqual(self.marker["audit_id"], self.audit["audit_id"])
        self.assertEqual(self.marker["audit_sha256"], _sha256(self.output / "audit.json"))
        self.assertTrue((self.output / "STAGE-E-RQ1.PASSED").is_file())
        for name, digest in self.audit["output_sha256"].items():
            self.assertEqual(_sha256(self.output / name), digest, name)

    def test_sixteen_units_directions_boundaries_and_exact_rows(self):
        expected_counts = {
            "result-unit-register": 16,
            "main-metrics": 96,
            "condition-summaries": 156,
            "paired-effect-summaries": 182,
            "interaction-effect-summaries": 26,
            "architecture-effects": 16,
            "architecture-evidence-codes": 16,
            "selected-bootstrap": 30,
            "strict-transitions": 56,
            "semantic-transitions": 126,
            "conversion-matrices": 756,
            "conversion-summaries": 84,
            "category-effects": 224,
            "category-interactions": 32,
            "process-condition-summaries": 312,
            "process-paired-summaries": 364,
            "figure-5-3-inputs": 32,
            "table-5-3-inputs": 24,
            "s3-build-cost-summary": 1,
            "trace-review-evidence": 24,
            "display-number-register": 1470,
        }
        self.assertEqual(
            {name: details["row_count"] for name, details in self.schema["tables"].items()},
            expected_counts,
        )
        units = _jsonl(self.output / "result-unit-register.jsonl")
        self.assertEqual(Counter(row["effect_status"] for row in units), {
            "core_effect": 12,
            "descriptive_complete_system_anchor": 4,
        })
        self.assertEqual(Counter(row["backbone_id"] for row in units), {"qwen": 8, "deepseek": 8})
        self.assertEqual(len({row["result_unit_id"] for row in units}), 16)
        self.assertEqual(len({row["architecture_evidence_code"] for row in units}), 16)
        for row in units:
            self.assertFalse(row["backbone_pooling_permitted"])
            self.assertEqual(row["answer_denominator"], QUESTION_COUNT)
            self.assertEqual(row["evidence_denominator"], EVIDENCE_ELIGIBLE_COUNT)
            self.assertEqual(row["multi_gold_source_denominator"], EXPECTED_MULTI_GOLD_SOURCE_COUNT)
            if row["comparison_type"] == "simple":
                self.assertEqual(row["difference_direction"], "target_minus_baseline")
                self.assertIsNotNone(row["baseline_condition"])
                self.assertIsNotNone(row["target_condition"])
            else:
                self.assertEqual(row["difference_direction"], "difference_in_differences")
                self.assertEqual(row["display_formula"], "(E4 - E2) - (E3 - E1)")

        comparisons = {row["comparison_id"] for row in units}
        self.assertNotIn("curated_vs_flat_r1_e5_minus_e1", comparisons)
        self.assertNotIn("curated_adapted_vs_flat_raw_e6_minus_e2", comparisons)
        self.assertNotIn("E7", {row.get("condition_id") for row in units})

    def test_denominators_bootstrap_transitions_and_conversion(self):
        metrics = _jsonl(self.output / "main-metrics.jsonl")
        groups = defaultdict(list)
        for row in metrics:
            groups[row["result_unit_id"]].append(row)
            expected_n = 58 if row["metric_id"] == "evidence_recall" else 60
            self.assertEqual(row["denominator"], expected_n)
            if row["comparison_type"] == "simple":
                self.assertEqual(row["difference_direction"], "target_minus_baseline")
        self.assertEqual(set(map(len, groups.values())), {6})

        bootstrap = _jsonl(self.output / "selected-bootstrap.jsonl")
        self.assertEqual(len(bootstrap), 30)
        self.assertEqual({row["replicates"] for row in bootstrap}, {10_000})
        self.assertEqual({row["random_seed"] for row in bootstrap}, {20_261_021})
        self.assertEqual(
            {row["metric_id"] for row in bootstrap},
            {"token_f1", "strict_accuracy", "soft_semantic_score"},
        )

        strict_groups = defaultdict(list)
        for row in _jsonl(self.output / "strict-transitions.jsonl"):
            strict_groups[(row["backbone_id"], row["comparison_id"])].append(row)
        self.assertEqual(len(strict_groups), 14)
        for rows in strict_groups.values():
            self.assertEqual(len(rows), 4)
            self.assertEqual(sum(row["count"] for row in rows), 60)

        condition_groups = defaultdict(list)
        for row in _jsonl(self.output / "condition-summaries.jsonl"):
            condition_groups[(row["backbone_id"], row["condition_id"])].append(row)
            expected_n = {"answer_all": 60, "evidence_eligible": 58,
                          "multi_gold_source_evidence_eligible": 19}[row["denominator_scope"]]
            self.assertEqual(row["denominator"], expected_n)
            if row["metric_id"] in {"partial_rate", "evidence_bundle_characters"}:
                self.assertEqual(row["metric_direction"], "neutral")
        self.assertEqual(len(condition_groups), 12)
        self.assertEqual({len(rows) for rows in condition_groups.values()}, {13})

        semantic_groups = defaultdict(list)
        for row in _jsonl(self.output / "semantic-transitions.jsonl"):
            semantic_groups[(row["backbone_id"], row["contrast_id"])].append(row)
        self.assertEqual(len(semantic_groups), 14)
        for rows in semantic_groups.values():
            self.assertEqual(len(rows), 9)
            self.assertEqual(sum(row["count"] for row in rows), 60)

        matrix_groups = defaultdict(list)
        matrices = _jsonl(self.output / "conversion-matrices.jsonl")
        for row in matrices:
            key = (
                row["comparison_id"], row["backbone_id"], row["subset_id"],
                row["answer_metric_id"],
            )
            matrix_groups[key].append(row)
        self.assertEqual(len(matrix_groups), 84)
        for key, rows in matrix_groups.items():
            denominator = 58 if key[2] == "evidence_eligible_58" else 19
            self.assertEqual(len(rows), 9)
            self.assertEqual(sum(row["count"] for row in rows), denominator)
            self.assertEqual({row["denominator"] for row in rows}, {denominator})

    def test_figure_table_cost_display_and_architecture_codes(self):
        figure = _jsonl(self.output / "figure-5-3-inputs.jsonl")
        table = _jsonl(self.output / "table-5-3-inputs.jsonl")
        self.assertEqual({row["figure_id"] for row in figure}, {"Figure 5.3"})
        self.assertEqual({row["table_id"] for row in table}, {"Table 5.3"})
        self.assertEqual({row["denominator"] for row in figure}, {58, 60})
        self.assertEqual({row["denominator"] for row in table}, {58, 60})
        for target, source in (
            ("figure-5-3-inputs.jsonl", STAGE_B / "figure-5-3-data.jsonl"),
            ("figure-5-3-inputs.csv", STAGE_B / "figure-5-3-data.csv"),
            ("table-5-3-inputs.jsonl", STAGE_C / "table-5-3-data.jsonl"),
            ("table-5-3-inputs.csv", STAGE_C / "table-5-3-data.csv"),
        ):
            self.assertEqual((self.output / target).read_bytes(), source.read_bytes(), target)

        cost = _jsonl(self.output / "s3-build-cost-summary.jsonl")[0]
        self.assertEqual(cost["cost_scope"], "one_time_s3_construction")
        self.assertFalse(cost["included_in_main_effect_estimates"])
        self.assertFalse(cost["query_time_cost"])
        self.assertFalse(cost["amortised_cost"])
        self.assertFalse(cost["pareto_analysis_input"])
        self.assertEqual(
            (cost["episodes"], cost["llm_calls"], cost["rounds"], cost["tool_calls"]),
            (85, 842, 837, 1350),
        )
        self.assertEqual(
            (cost["prompt_tokens"], cost["completion_tokens"], cost["total_tokens"]),
            (29_669_563, 1_195_395, 30_864_958),
        )

        codes = _jsonl(self.output / "architecture-evidence-codes.jsonl")
        self.assertEqual(len(codes), 16)
        self.assertTrue(all(row["cross_backbone_inference_permitted"] is False for row in codes))
        self.assertTrue(
            all(
                row["causal_component_claim_permitted"] is False
                for row in codes
                if row["effect_status"] == "descriptive_complete_system_anchor"
            )
        )
        display = _jsonl(self.output / "display-number-register.jsonl")
        self.assertEqual(len({row["display_number_id"] for row in display}), len(display))
        self.assertEqual(
            {row["display_context"] for row in display},
            {
                "architecture_main_metric", "selected_bootstrap", "strict_transition",
                "architecture_condition_endpoint", "supplementary_paired_metric",
                "supplementary_interaction_metric",
                "interaction_sign_count", "conversion_primary", "category_effect",
                "category_interaction", "process_condition", "process_paired",
                "Figure 5.3", "Table 5.3", "Table 5.3 S3 one-time build cost",
            },
        )

        manifest = _json(self.output / "source-manifest.json")
        for flag in (
            "new_bootstrap_computed", "cross_backbone_inference_computed", "e7_computed",
            "full_context_computed", "global_error_census_computed",
            "pareto_analysis_computed", "system_recommendation_computed",
            "final_rq1_prose_computed", "old_new_question_split_computed",
        ):
            self.assertIs(manifest[flag], False, flag)

    def test_tamper_and_extra_file_are_rejected(self):
        with tempfile.TemporaryDirectory(prefix="chapter5-stage-e-tamper-") as directory:
            copied = Path(directory) / "stage-e-rq1"
            shutil.copytree(self.output, copied)
            path = copied / "main-metrics.jsonl"
            rows = _jsonl(path)
            rows[0]["point_estimate"] = float(rows[0]["point_estimate"]) + 0.001
            path.write_text(
                "".join(json.dumps(row, ensure_ascii=False, separators=(",", ":"), sort_keys=True) + "\n" for row in rows),
                encoding="utf-8",
            )
            with self.assertRaises(EvidenceValidationError):
                audit_stage_e_output(**_kwargs(copied))

        with tempfile.TemporaryDirectory(prefix="chapter5-stage-e-extra-") as directory:
            copied = Path(directory) / "stage-e-rq1"
            shutil.copytree(self.output, copied)
            (copied / "unexpected.txt").write_text("not part of the artifact", encoding="utf-8")
            with self.assertRaises(EvidenceValidationError):
                audit_stage_e_output(**_kwargs(copied))

    def test_atomic_builder_refuses_existing_destination(self):
        with self.assertRaises(EvidenceValidationError):
            build_stage_e(**_kwargs(self.output))


if __name__ == "__main__":
    unittest.main()
