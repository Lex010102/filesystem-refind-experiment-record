from __future__ import annotations

import hashlib
import json
import shutil
import tempfile
import unittest
from pathlib import Path

from fs_memory_lab.chapter5_rq2 import (
    STAGE_RQ2_PROTOCOL_VERSION,
    _stability_classification,
    audit_rq2_output,
    build_rq2,
)
from fs_memory_lab.evidence import EvidenceValidationError


REPO_ROOT = Path(__file__).resolve().parents[1]
STAGE_A = REPO_ROOT / "artifacts/chapter5-main60-analysis-v1/stage-a"
STAGE_E = REPO_ROOT / "artifacts/chapter5-main60-analysis-v1/stage-e-rq1"

CONDITION_IDS = tuple(f"E{number}" for number in range(1, 8))
COMPARISON_IDS = (
    "storage_r1_e3_minus_e1",
    "storage_r2_e4_minus_e2",
    "retrieval_s1_e2_minus_e1",
    "retrieval_s2_e4_minus_e3",
    "curated_access_e6_minus_e5",
    "curated_vs_foldered_r1_e5_minus_e3",
)
EXPECTED_CLASSIFICATIONS = {
    "storage_r1_e3_minus_e1": "backbone_dependent",
    "storage_r2_e4_minus_e2": "partly_stable",
    "retrieval_s1_e2_minus_e1": "partly_stable",
    "retrieval_s2_e4_minus_e3": "stable",
    "curated_access_e6_minus_e5": "stable",
    "curated_vs_foldered_r1_e5_minus_e3": "stable",
}
EXPECTED_SUBTYPES = {
    "storage_r1_e3_minus_e1": "both_primary_metrics_reverse",
    "storage_r2_e4_minus_e2": "lexical_stable_semantic_backbone_dependent",
    "retrieval_s1_e2_minus_e1": "semantic_stable_lexical_backbone_dependent",
    "retrieval_s2_e4_minus_e3": "directionally_stable_negative",
    "curated_access_e6_minus_e5": "directionally_stable_negative",
    "curated_vs_foldered_r1_e5_minus_e3": "stable_metric_tradeoff",
}
PRIMARY_METRICS = ("token_f1", "strict_accuracy", "soft_semantic_score")
FORBIDDEN_CONTENT_FIELDS = {
    "question",
    "question_text",
    "reference_answer",
    "candidate_answer",
    "answer_text",
    "evidence",
    "evidence_text",
    "retrieved_text",
    "gold_answer",
    "prompt",
    "response",
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


def _kwargs(output_dir: Path):
    return {
        "repo_root": REPO_ROOT,
        "stage_a_dir": STAGE_A,
        "stage_e_dir": STAGE_E,
        "output_dir": output_dir,
    }


class Chapter5RQ2ArtifactTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix="chapter5-rq2-test-")
        cls.output = Path(cls.temp.name) / "rq2-backbone-robustness"
        cls.build_result = build_rq2(**_kwargs(cls.output))
        cls.audit = _json(cls.output / "audit.json")
        cls.marker = _json(cls.output / "RQ2.PASSED")
        cls.schema = _json(cls.output / "schema.json")
        cls.conditions = _jsonl(cls.output / "condition-backbone-comparison.jsonl")
        cls.lexical = _jsonl(cls.output / "lexical-explanation.jsonl")
        cls.architecture = _jsonl(cls.output / "architecture-stability.jsonl")

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def test_normal_build_and_independent_audit(self):
        self.assertEqual(self.build_result["status"], "passed")
        self.assertEqual(
            self.build_result["protocol_version"], STAGE_RQ2_PROTOCOL_VERSION
        )
        result = audit_rq2_output(**_kwargs(self.output))
        self.assertEqual(result["status"], "passed")
        self.assertEqual(result["protocol_version"], STAGE_RQ2_PROTOCOL_VERSION)
        self.assertEqual(result["audit_id"], self.audit["audit_id"])
        self.assertEqual(self.marker["audit_id"], self.audit["audit_id"])
        self.assertEqual(
            self.marker["audit_sha256"], _sha256(self.output / "audit.json")
        )
        self.assertTrue((self.output / "RQ2.PASSED").is_file())
        for name, digest in self.audit["output_sha256"].items():
            self.assertEqual(_sha256(self.output / name), digest, name)

        expected_names = {
            "README.md",
            "condition-backbone-comparison.csv",
            "condition-backbone-comparison.jsonl",
            "lexical-explanation.csv",
            "lexical-explanation.jsonl",
            "architecture-stability.csv",
            "architecture-stability.jsonl",
            "table-5-13-inputs.csv",
            "table-5-13-inputs.jsonl",
            "schema.json",
            "source-manifest.json",
            "audit.json",
            "RQ2.PASSED",
        }
        self.assertEqual({path.name for path in self.output.iterdir()}, expected_names)

    def test_exact_seven_seven_six_rows_and_scope(self):
        self.assertEqual(len(self.conditions), 7)
        self.assertEqual(len(self.lexical), 7)
        self.assertEqual(len(self.architecture), 6)
        self.assertEqual(
            [row["condition_id"] for row in self.conditions], list(CONDITION_IDS)
        )
        self.assertEqual(
            [row["condition_id"] for row in self.lexical], list(CONDITION_IDS)
        )
        self.assertEqual(
            [row["comparison_id"] for row in self.architecture],
            list(COMPARISON_IDS),
        )
        self.assertEqual({row["denominator"] for row in self.conditions}, {60})
        self.assertEqual({row["denominator"] for row in self.lexical}, {60})
        self.assertEqual(
            {row["delta_definition"] for row in self.conditions},
            {"deepseek_minus_qwen"},
        )
        self.assertEqual(
            {row["delta_definition"] for row in self.lexical},
            {"deepseek_minus_qwen"},
        )
        self.assertTrue(all(row["descriptive_only"] for row in self.conditions))
        self.assertTrue(all(row["descriptive_only"] for row in self.architecture))

        self.assertEqual(
            self.schema["tables"]["condition-backbone-comparison"]["row_count"], 7
        )
        self.assertEqual(
            self.schema["tables"]["lexical-explanation"]["row_count"], 7
        )
        self.assertEqual(
            self.schema["tables"]["architecture-stability"]["row_count"], 6
        )
        self.assertEqual(
            self.schema["tables"]["table-5-13-inputs"]["row_count"], 6
        )

        report_rows = _jsonl(self.output / "table-5-13-inputs.jsonl")
        self.assertEqual(len(report_rows), 6)
        self.assertEqual(
            [row["comparison_id"] for row in report_rows], list(COMPARISON_IDS)
        )
        self.assertTrue(
            all("cross_backbone_token_f1_difference" not in row for row in report_rows)
        )
        self.assertLess(len(report_rows[0]), len(self.architecture[0]))

    def test_condition_numeric_anchors_and_deepseek_minus_qwen_algebra(self):
        rows = {row["condition_id"]: row for row in self.conditions}
        e1 = rows["E1"]
        self.assertAlmostEqual(e1["qwen_token_f1"], 0.39487411533501493, places=15)
        self.assertAlmostEqual(e1["deepseek_token_f1"], 0.3012519451505862, places=15)
        self.assertAlmostEqual(e1["qwen_strict_accuracy"], 43 / 60, places=15)
        self.assertAlmostEqual(e1["deepseek_strict_accuracy"], 45 / 60, places=15)
        self.assertAlmostEqual(e1["qwen_soft_semantic_score"], 46 / 60, places=15)
        self.assertAlmostEqual(
            e1["deepseek_soft_semantic_score"], 48.5 / 60, places=15
        )

        e7 = rows["E7"]
        self.assertAlmostEqual(e7["qwen_token_f1"], 0.3690638836963411, places=15)
        self.assertAlmostEqual(e7["deepseek_token_f1"], 0.28536784595670195, places=15)
        self.assertAlmostEqual(e7["qwen_strict_accuracy"], 44 / 60, places=15)
        self.assertAlmostEqual(e7["deepseek_strict_accuracy"], 45 / 60, places=15)

        for row in self.conditions:
            for metric in PRIMARY_METRICS:
                self.assertAlmostEqual(
                    row[f"delta_{metric}"],
                    row[f"deepseek_{metric}"] - row[f"qwen_{metric}"],
                    places=15,
                )

    def test_lexical_explanation_anchors_and_algebra(self):
        rows = {row["condition_id"]: row for row in self.lexical}
        e2 = rows["E2"]
        self.assertAlmostEqual(e2["qwen_token_precision"], 0.36059902732208127, places=15)
        self.assertAlmostEqual(
            e2["deepseek_token_precision"], 0.17201537508840695, places=15
        )
        self.assertAlmostEqual(e2["qwen_answer_normalized_tokens"], 12.633333333333333, places=15)
        self.assertAlmostEqual(
            e2["deepseek_answer_normalized_tokens"], 24.916666666666668, places=15
        )
        for row in self.lexical:
            self.assertTrue(row["interpretation_scope"])
            for metric in (
                "token_precision",
                "token_recall",
                "answer_normalized_tokens",
            ):
                self.assertAlmostEqual(
                    row[f"delta_{metric}"],
                    row[f"deepseek_{metric}"] - row[f"qwen_{metric}"],
                    places=15,
                )

    def test_architecture_reconciles_stage_e_and_classifies_stability(self):
        source_rows = _jsonl(STAGE_E / "architecture-effects.jsonl")
        source_index = {
            (row["comparison_id"], row["backbone_id"]): row
            for row in source_rows
        }
        self.assertEqual(
            {row["stability_classification"] for row in self.architecture},
            set(EXPECTED_CLASSIFICATIONS.values()),
        )
        for row in self.architecture:
            comparison_id = row["comparison_id"]
            self.assertEqual(
                row["stability_classification"],
                EXPECTED_CLASSIFICATIONS[comparison_id],
            )
            self.assertEqual(row["stability_subtype"], EXPECTED_SUBTYPES[comparison_id])
            self.assertTrue(row["classification_basis"])
            qwen = source_index[(comparison_id, "qwen")]
            deepseek = source_index[(comparison_id, "deepseek")]
            for metric in PRIMARY_METRICS:
                source_field = f"delta_{metric}"
                self.assertEqual(row[f"qwen_{metric}_effect"], qwen[source_field])
                self.assertEqual(
                    row[f"deepseek_{metric}_effect"], deepseek[source_field]
                )
                self.assertAlmostEqual(
                    row[f"cross_backbone_{metric}_difference"],
                    deepseek[source_field] - qwen[source_field],
                    places=15,
                )
                self.assertIn(
                    row[f"qwen_{metric}_direction"], {"positive", "zero", "negative"}
                )
                self.assertIn(
                    row[f"deepseek_{metric}_direction"],
                    {"positive", "zero", "negative"},
                )
                self.assertTrue(row[f"{metric}_direction_relation"])

        storage_r1 = next(
            row
            for row in self.architecture
            if row["comparison_id"] == "storage_r1_e3_minus_e1"
        )
        self.assertAlmostEqual(
            storage_r1["cross_backbone_token_f1_difference"],
            -0.05035988439155551,
            places=15,
        )
        self.assertEqual(storage_r1["token_f1_direction_relation"], "opposite")
        self.assertEqual(storage_r1["strict_accuracy_direction_relation"], "opposite")
        self.assertEqual(
            storage_r1["soft_semantic_score_direction_relation"], "opposite"
        )

        classification, subtype, _ = _stability_classification(
            token_f1=(0.0, 0.0),
            strict_accuracy=(0.1, 0.1),
            soft_semantic_score=(0.1, -0.1),
        )
        self.assertEqual(classification, "indeterminate")
        self.assertEqual(subtype, "zero_primary_effect")

    def test_e1_e6_condition_reconciliation_e7_scope_and_no_text_payloads(self):
        summaries = _jsonl(STAGE_E / "condition-summaries.jsonl")
        source_index = {
            (row["backbone_id"], row["condition_id"], row["metric_id"]): row["mean"]
            for row in summaries
            if row["metric_id"] in PRIMARY_METRICS
        }
        for row in self.conditions:
            if row["condition_id"] == "E7":
                continue
            for backbone in ("qwen", "deepseek"):
                for metric in PRIMARY_METRICS:
                    self.assertEqual(
                        row[f"{backbone}_{metric}"],
                        source_index[(backbone, row["condition_id"], metric)],
                    )

        self.assertNotIn("E7", {row["comparison_id"] for row in self.architecture})
        self.assertFalse(
            any(
                "full context" in str(value).lower()
                for rows in (self.conditions, self.lexical, self.architecture)
                for row in rows
                for value in row.values()
            )
        )
        for rows in (self.conditions, self.lexical, self.architecture):
            for row in rows:
                self.assertTrue(FORBIDDEN_CONTENT_FIELDS.isdisjoint(row))

    def test_manifest_freezes_offline_descriptive_scope(self):
        manifest = _json(self.output / "source-manifest.json")
        self.assertIs(manifest["no_api_calls"], True)
        self.assertIs(manifest["no_network_calls"], True)
        self.assertIs(manifest["new_bootstrap_computed"], False)
        self.assertIs(manifest["full_context_computed"], False)
        self.assertIs(manifest["cross_backbone_inference_computed"], False)
        self.assertEqual(manifest["answer_denominator"], 60)
        self.assertEqual(manifest["condition_ids"], list(CONDITION_IDS))
        self.assertEqual(manifest["architecture_comparison_ids"], list(COMPARISON_IDS))
        self.assertEqual(
            manifest["backbone_identities"],
            {
                "qwen": {
                    "answer_set_id": "model1-qwen-main60",
                    "requested_model": "coding",
                    "served_model": "qwen3.8:27b",
                },
                "deepseek": {
                    "answer_set_id": "model2-deepseek-main60",
                    "requested_model": "x-test-2",
                    "served_model": "deepseek-v4.1-flash",
                },
            },
        )
        self.assertEqual(
            manifest["judge_identity"],
            {"requested_model": "x-test-1", "served_model": "glm-5.3-flash"},
        )

    def test_tamper_and_extra_file_are_rejected(self):
        with tempfile.TemporaryDirectory(prefix="chapter5-rq2-tamper-") as directory:
            copied = Path(directory) / "rq2-backbone-robustness"
            shutil.copytree(self.output, copied)
            path = copied / "condition-backbone-comparison.jsonl"
            rows = _jsonl(path)
            rows[0]["delta_token_f1"] = float(rows[0]["delta_token_f1"]) + 0.001
            path.write_text(
                "".join(
                    json.dumps(
                        row,
                        ensure_ascii=False,
                        separators=(",", ":"),
                        sort_keys=True,
                    )
                    + "\n"
                    for row in rows
                ),
                encoding="utf-8",
            )
            with self.assertRaises(EvidenceValidationError):
                audit_rq2_output(**_kwargs(copied))

        with tempfile.TemporaryDirectory(prefix="chapter5-rq2-extra-") as directory:
            copied = Path(directory) / "rq2-backbone-robustness"
            shutil.copytree(self.output, copied)
            (copied / "unexpected.txt").write_text(
                "not part of the RQ2 artifact", encoding="utf-8"
            )
            with self.assertRaises(EvidenceValidationError):
                audit_rq2_output(**_kwargs(copied))

    def test_atomic_builder_refuses_existing_destination(self):
        with self.assertRaises(EvidenceValidationError):
            build_rq2(**_kwargs(self.output))


if __name__ == "__main__":
    unittest.main()
