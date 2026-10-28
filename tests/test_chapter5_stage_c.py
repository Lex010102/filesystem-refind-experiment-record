from __future__ import annotations

import hashlib
import json
import math
import os
import shutil
import tempfile
import unittest
from collections import defaultdict
from pathlib import Path

from fs_memory_lab.chapter5_stage_c import (
    STAGE_C_PROTOCOL_VERSION,
    TIE_TOLERANCE,
    audit_stage_c_output,
)
from fs_memory_lab.evidence import EvidenceValidationError


REPO_ROOT = Path(__file__).resolve().parents[1]
STAGE_A = REPO_ROOT / "artifacts/chapter5-main60-analysis-v1/stage-a"
STAGE_B = REPO_ROOT / "artifacts/chapter5-main60-analysis-v1/stage-b"
STAGE_C = Path(
    os.environ.get(
        "CHAPTER5_STAGE_C_DIR",
        REPO_ROOT / "artifacts/chapter5-main60-analysis-v1/stage-c",
    )
).resolve()


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


CONTRAST_IDS = {
    "e65": "curated_access_e6_minus_e5",
    "e53": "curated_vs_foldered_r1_e5_minus_e3",
    "e64": "curated_adapted_vs_foldered_raw_e6_minus_e4",
    "e51": "curated_vs_flat_r1_e5_minus_e1",
    "e62": "curated_adapted_vs_flat_raw_e6_minus_e2",
}


@unittest.skipUnless((STAGE_C / "STAGE-C.PASSED").is_file(), "formal Stage C artifact not built")
class Chapter5StageCArtifactTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.audit = _json(STAGE_C / "audit.json")
        cls.marker = _json(STAGE_C / "STAGE-C.PASSED")
        cls.register = _jsonl(STAGE_C / "contrast-register.jsonl")
        cls.conditions = _jsonl(STAGE_C / "condition-summaries.jsonl")
        cls.pairs = _jsonl(STAGE_C / "paired-question-effects.jsonl")
        cls.aggregate = _jsonl(STAGE_C / "aggregate-effects.jsonl")
        cls.strict = _jsonl(STAGE_C / "strict-transitions.jsonl")
        cls.semantic = _jsonl(STAGE_C / "semantic-transitions.jsonl")
        cls.main = _jsonl(STAGE_C / "table-5-3-data.jsonl")
        cls.sensitivity = _jsonl(STAGE_C / "appendix-sensitivity-data.jsonl")

    def test_gate_hashes_counts_and_independent_audit(self):
        result = audit_stage_c_output(stage_a_dir=STAGE_A, stage_b_dir=STAGE_B, output_dir=STAGE_C)
        self.assertEqual(result["status"], "passed")
        self.assertEqual(result["protocol_version"], STAGE_C_PROTOCOL_VERSION)
        self.assertEqual(result["input_rows"], 720)
        self.assertEqual(result["effect_units"], 10)
        self.assertEqual(self.marker["audit_id"], self.audit["audit_id"])
        self.assertEqual(self.marker["audit_sha256"], _sha256(STAGE_C / "audit.json"))
        self.assertEqual(
            {
                "contrast-register": len(self.register),
                "condition-summaries": len(self.conditions),
                "paired-question-effects": len(self.pairs),
                "aggregate-effects": len(self.aggregate),
                "strict-transitions": len(self.strict),
                "semantic-transitions": len(self.semantic),
                "table-5-3-data": len(self.main),
                "appendix-sensitivity-data": len(self.sensitivity),
            },
            {
                "contrast-register": 5,
                "condition-summaries": 52,
                "paired-question-effects": 6490,
                "aggregate-effects": 130,
                "strict-transitions": 40,
                "semantic-transitions": 90,
                "table-5-3-data": 24,
                "appendix-sensitivity-data": 16,
            },
        )
        for name, digest in self.audit["output_sha256"].items():
            self.assertEqual(_sha256(STAGE_C / name), digest, name)

    def test_protocol_scope_roles_and_no_forbidden_analysis(self):
        register = {row["contrast_id"]: row for row in self.register}
        self.assertEqual(set(register), set(CONTRAST_IDS.values()))
        main_ids = {CONTRAST_IDS["e65"], CONTRAST_IDS["e53"], CONTRAST_IDS["e64"]}
        sensitivity_ids = {CONTRAST_IDS["e51"], CONTRAST_IDS["e62"]}
        self.assertEqual({row["contrast_id"] for row in self.main}, main_ids)
        self.assertEqual({row["contrast_id"] for row in self.sensitivity}, sensitivity_ids)
        self.assertEqual({row["condition_id"] for row in self.conditions}, {"E5", "E6"})
        self.assertEqual({row["denominator"] for row in self.conditions}, {19, 58, 60})
        self.assertTrue(
            all(
                {"comparison_status", "publication_role", "identification_scope"}.issubset(row)
                for rows in (self.register, self.pairs, self.aggregate, self.strict, self.semantic)
                for row in rows
            )
        )
        forbidden_field_fragments = (
            "question_text",
            "reference_answer",
            "candidate_answer",
            "answer_text",
            "evidence_text",
            "rationale",
            "judge_reason",
            "prompt",
        )
        for path in STAGE_C.glob("*.jsonl"):
            for row in _jsonl(path):
                self.assertFalse(
                    any(fragment in field.lower() for field in row for fragment in forbidden_field_fragments),
                    path.name,
                )
        names = {path.name for path in STAGE_C.iterdir()}
        self.assertFalse(any("bootstrap" in name or "interaction" in name for name in names))
        for flag in (
            "bootstrap_computed",
            "interaction_computed",
            "category_effect_computed",
            "evidence_to_answer_conversion_computed",
            "process_analysis_computed",
            "cost_analysis_computed",
            "trace_review_computed",
            "cross_backbone_effect_computed",
            "stage_d_computed",
            "e7_computed",
            "full_context_computed",
            "final_rq1_conclusion_computed",
        ):
            self.assertIs(self.audit.get(flag), False, flag)

    def test_independent_numeric_anchors(self):
        # mean delta and metric-oriented W/T/L, recomputed independently before implementation
        expected = {
            ("qwen", "e65"): {
                "token_f1": (-0.013453968866442, 20, 23, 17),
                "strict_accuracy": (-0.05, 2, 53, 5),
                "soft_semantic_score": (-0.058333333333333, 3, 51, 6),
                "evidence_recall": (-0.089080459770115, 1, 50, 7),
            },
            ("qwen", "e53"): {
                "token_f1": (-0.046328504120277, 16, 20, 24),
                "strict_accuracy": (0.033333333333333, 4, 54, 2),
                "soft_semantic_score": (0.025, 6, 52, 2),
                "evidence_recall": (0.103448275862069, 9, 48, 1),
            },
            ("qwen", "e64"): {
                "token_f1": (-0.014691000412312, 20, 18, 22),
                "strict_accuracy": (0.033333333333333, 6, 50, 4),
                "soft_semantic_score": (0.033333333333333, 8, 47, 5),
                "evidence_recall": (0.056034482758621, 7, 48, 3),
            },
            ("qwen", "e51"): {
                "token_f1": (-0.000108872068751, 17, 21, 22),
                "strict_accuracy": (0.066666666666667, 5, 54, 1),
                "soft_semantic_score": (0.05, 6, 52, 2),
                "evidence_recall": (0.110632183908046, 10, 46, 2),
            },
            ("qwen", "e62"): {
                "token_f1": (-0.021799679852723, 19, 21, 20),
                "strict_accuracy": (0.066666666666667, 7, 50, 3),
                "soft_semantic_score": (0.041666666666667, 8, 49, 3),
                "evidence_recall": (0.054597701149425, 8, 45, 5),
            },
            ("deepseek", "e65"): {
                "token_f1": (-0.036396747772615, 16, 15, 29),
                "strict_accuracy": (-0.083333333333333, 2, 51, 7),
                "soft_semantic_score": (-0.091666666666667, 4, 46, 10),
                "evidence_recall": (-0.237068965517241, 2, 40, 16),
            },
            ("deepseek", "e53"): {
                "token_f1": (-0.036742747106773, 22, 13, 25),
                "strict_accuracy": (0.05, 5, 53, 2),
                "soft_semantic_score": (0.041666666666667, 7, 49, 4),
                "evidence_recall": (0.114942528735632, 10, 47, 1),
            },
            ("deepseek", "e64"): {
                "token_f1": (-0.007449980831794, 14, 17, 29),
                "strict_accuracy": (0.0, 4, 52, 4),
                "soft_semantic_score": (0.0, 6, 49, 5),
                "evidence_recall": (-0.043103448275862, 6, 44, 8),
            },
            ("deepseek", "e51"): {
                "token_f1": (-0.040882999446802, 22, 10, 28),
                "strict_accuracy": (0.0, 4, 52, 4),
                "soft_semantic_score": (-0.008333333333333, 5, 48, 7),
                "evidence_recall": (0.084770114942529, 8, 48, 2),
            },
            ("deepseek", "e62"): {
                "token_f1": (-0.021550209801918, 14, 15, 31),
                "strict_accuracy": (-0.033333333333333, 4, 50, 6),
                "soft_semantic_score": (0.0, 9, 45, 6),
                "evidence_recall": (-0.071839080459770, 7, 40, 11),
            },
        }
        aggregate = {
            (row["backbone_id"], row["contrast_id"], row["metric_id"]): row for row in self.aggregate
        }
        for (backbone, short_id), metrics in expected.items():
            for metric_id, (delta, wins, ties, losses) in metrics.items():
                row = aggregate[(backbone, CONTRAST_IDS[short_id], metric_id)]
                self.assertAlmostEqual(row["mean_difference"], delta, places=12)
                self.assertEqual((row["win_count"], row["tie_count"], row["loss_count"]), (wins, ties, losses))

    def test_pairs_aggregates_neutral_metrics_and_transitions(self):
        pair_groups = defaultdict(list)
        for row in self.pairs:
            pair_groups[(row["backbone_id"], row["contrast_id"], row["metric_id"])].append(row)
            self.assertTrue(
                math.isclose(
                    row["raw_difference"],
                    row["target_value"] - row["baseline_value"],
                    rel_tol=0.0,
                    abs_tol=TIE_TOLERANCE,
                )
            )
            if row["metric_id"] in {"partial_rate", "evidence_bundle_characters"}:
                self.assertIsNone(row["oriented_difference"])
                self.assertIsNone(row["oriented_state"])
        aggregate = {
            (row["backbone_id"], row["contrast_id"], row["metric_id"]): row for row in self.aggregate
        }
        for key, rows in pair_groups.items():
            scope = rows[0]["denominator_scope"]
            expected_n = 60 if scope == "answer_all" else 58 if scope == "evidence_eligible" else 19
            self.assertEqual(len(rows), expected_n, key)
            out = aggregate[key]
            self.assertAlmostEqual(
                out["mean_difference"],
                math.fsum(float(row["raw_difference"]) for row in rows) / expected_n,
                places=15,
            )
            self.assertEqual(
                out["increase_count"] + out["same_count"] + out["decrease_count"], expected_n
            )
            if key[2] in {"partial_rate", "evidence_bundle_characters"}:
                self.assertIsNone(out["win_count"])
                self.assertIsNone(out["tie_count"])
                self.assertIsNone(out["loss_count"])

        strict_groups = defaultdict(list)
        semantic_groups = defaultdict(list)
        for row in self.strict:
            strict_groups[(row["backbone_id"], row["contrast_id"])].append(row)
        for row in self.semantic:
            semantic_groups[(row["backbone_id"], row["contrast_id"])].append(row)
        for key, rows in strict_groups.items():
            self.assertEqual(len(rows), 4)
            self.assertEqual(sum(row["count"] for row in rows), 60)
            semantic = semantic_groups[key]
            self.assertEqual(len(semantic), 9)
            self.assertEqual(sum(row["count"] for row in semantic), 60)
            nc_to_c = sum(
                row["count"]
                for row in semantic
                if row["baseline_label"] in {"incorrect", "partial"} and row["target_label"] == "correct"
            )
            c_to_nc = sum(
                row["count"]
                for row in semantic
                if row["baseline_label"] == "correct" and row["target_label"] in {"incorrect", "partial"}
            )
            strict_map = {row["transition_id"]: row["count"] for row in rows}
            self.assertEqual(strict_map["strict_not_correct_to_correct"], nc_to_c)
            self.assertEqual(strict_map["strict_correct_to_not_correct"], c_to_nc)

    def test_tamper_is_rejected(self):
        with tempfile.TemporaryDirectory(prefix="chapter5-stage-c-tamper-") as temp:
            copied = Path(temp) / "stage-c"
            shutil.copytree(STAGE_C, copied)
            path = copied / "aggregate-effects.jsonl"
            rows = _jsonl(path)
            rows[0]["mean_difference"] = float(rows[0]["mean_difference"]) + 0.001
            path.write_text("".join(json.dumps(row, separators=(",", ":"), sort_keys=True) + "\n" for row in rows), encoding="utf-8")
            with self.assertRaises(EvidenceValidationError):
                audit_stage_c_output(stage_a_dir=STAGE_A, stage_b_dir=STAGE_B, output_dir=copied)


if __name__ == "__main__":
    unittest.main()
