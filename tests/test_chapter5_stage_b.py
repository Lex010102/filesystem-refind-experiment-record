from __future__ import annotations

import hashlib
import json
import math
import random
import shutil
import tempfile
import unittest
from collections import Counter, defaultdict
from pathlib import Path

from fs_memory_lab.chapter5_stage_b import (
    ALGEBRA_TOLERANCE,
    BOOTSTRAP_REPLICATES,
    BOOTSTRAP_SEED,
    STAGE_B_PROTOCOL_VERSION,
    TIE_TOLERANCE,
    audit_stage_b_output,
)
from fs_memory_lab.evidence import EvidenceValidationError


REPO_ROOT = Path(__file__).resolve().parents[1]
STAGE_A = REPO_ROOT / "artifacts/chapter5-main60-analysis-v1/stage-a"
STAGE_B = REPO_ROOT / "artifacts/chapter5-main60-analysis-v1/stage-b"


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


def _type7(values: list[float], probability: float) -> float:
    ordered = sorted(values)
    position = (len(ordered) - 1) * probability
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    weight = position - lower
    return ordered[lower] * (1.0 - weight) + ordered[upper] * weight


@unittest.skipUnless((STAGE_B / "STAGE-B.PASSED").is_file(), "formal Stage B artifact not built")
class Chapter5StageBArtifactTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.audit = _json(STAGE_B / "audit.json")
        cls.marker = _json(STAGE_B / "STAGE-B.PASSED")
        cls.stage_a_rows = [
            row
            for row in _jsonl(STAGE_A / "rq1-analysis-view.jsonl")
            if row["condition_id"] in {"E1", "E2", "E3", "E4"}
        ]
        cls.aggregate = _jsonl(STAGE_B / "aggregate-effects.jsonl")
        cls.pairs = _jsonl(STAGE_B / "paired-question-effects.jsonl")
        cls.strict = _jsonl(STAGE_B / "strict-transitions.jsonl")
        cls.semantic = _jsonl(STAGE_B / "semantic-transitions.jsonl")
        cls.interaction = _jsonl(STAGE_B / "interaction-question-effects.jsonl")
        cls.interaction_aggregate = _jsonl(STAGE_B / "interaction-aggregates.jsonl")
        cls.bootstrap = _jsonl(STAGE_B / "bootstrap-intervals.jsonl")

    def test_gate_hashes_and_independent_audit(self):
        result = audit_stage_b_output(stage_a_dir=STAGE_A, output_dir=STAGE_B)
        self.assertEqual(result["status"], "passed")
        self.assertEqual(result["protocol_version"], STAGE_B_PROTOCOL_VERSION)
        self.assertEqual(result["input_rows"], 480)
        self.assertEqual(result["effect_units"], 10)
        self.assertEqual(self.marker["audit_id"], self.audit["audit_id"])
        self.assertEqual(self.marker["audit_sha256"], _sha256(STAGE_B / "audit.json"))
        for name, digest in self.audit["output_sha256"].items():
            self.assertEqual(_sha256(STAGE_B / name), digest, name)

    def test_scopes_denominators_and_no_text_leakage(self):
        self.assertEqual(len(self.stage_a_rows), 480)
        cells = Counter((row["backbone_id"], row["condition_id"]) for row in self.stage_a_rows)
        self.assertEqual(set(cells.values()), {60})
        question_sets = {
            (backbone, condition): {
                row["question_id"]
                for row in self.stage_a_rows
                if row["backbone_id"] == backbone and row["condition_id"] == condition
            }
            for backbone, condition in cells
        }
        self.assertEqual(len({frozenset(value) for value in question_sets.values()}), 1)
        evidence_masks = {
            (backbone, condition): {
                row["question_id"]
                for row in self.stage_a_rows
                if row["backbone_id"] == backbone
                and row["condition_id"] == condition
                and row["evidence_eligible"]
            }
            for backbone, condition in cells
        }
        self.assertEqual(len({frozenset(value) for value in evidence_masks.values()}), 1)
        self.assertEqual({len(value) for value in evidence_masks.values()}, {58})
        self.assertEqual(
            {
                len(
                    {
                        row["question_id"]
                        for row in self.stage_a_rows
                        if row["backbone_id"] == backbone
                        and row["condition_id"] == condition
                        and row["evidence_eligible"]
                        and len(set(row["gold_dia_ids"])) > 1
                    }
                )
                for backbone, condition in cells
            },
            {19},
        )
        forbidden = {
            "question",
            "answer",
            "reference_answer",
            "candidate_answer",
            "evidence_text",
            "short_reason",
            "rationale",
            "prompt",
        }
        for path in STAGE_B.glob("*.jsonl"):
            for row in _jsonl(path):
                self.assertTrue(forbidden.isdisjoint(row), path.name)
                self.assertNotIn("source_partition", row)

    def test_independent_numeric_anchors(self):
        expected = {
            ("qwen", "storage_r1_e3_minus_e1"): (
                (0.04621963205152648, 19, 30, 11),
                (0.03333333333333333, 5, 52, 3),
                (0.025, 6, 49, 5),
            ),
            ("qwen", "storage_r2_e4_minus_e2"): (
                (-0.007108679440410209, 13, 32, 15),
                (0.03333333333333333, 5, 52, 3),
                (0.008333333333333333, 5, 51, 4),
            ),
            ("qwen", "retrieval_s1_e2_minus_e1"): (
                (0.008236838917529887, 13, 27, 20),
                (-0.05, 2, 53, 5),
                (-0.05, 3, 50, 7),
            ),
            ("qwen", "retrieval_s2_e4_minus_e3"): (
                (-0.0450914725744068, 15, 26, 19),
                (-0.05, 4, 49, 7),
                (-0.06666666666666667, 4, 47, 9),
            ),
            ("deepseek", "storage_r1_e3_minus_e1"): (
                (-0.00414025234002903, 17, 25, 18),
                (-0.05, 1, 55, 4),
                (-0.05, 1, 54, 5),
            ),
            ("deepseek", "storage_r2_e4_minus_e2"): (
                (-0.014100228970124307, 20, 20, 20),
                (-0.03333333333333333, 1, 56, 3),
                (0.0, 4, 53, 3),
            ),
            ("deepseek", "retrieval_s1_e2_minus_e1"): (
                (-0.05572953741749869, 22, 14, 24),
                (-0.05, 4, 49, 7),
                (-0.1, 4, 45, 11),
            ),
            ("deepseek", "retrieval_s2_e4_minus_e3"): (
                (-0.06568951404759397, 22, 12, 26),
                (-0.03333333333333333, 4, 50, 6),
                (-0.05, 5, 46, 9),
            ),
        }
        for key, metric_values in expected.items():
            backbone, contrast = key
            for metric_id, expected_value in zip(
                ("token_f1", "strict_accuracy", "soft_semantic_score"), metric_values
            ):
                row = next(
                    item
                    for item in self.aggregate
                    if item["backbone_id"] == backbone
                    and item["contrast_id"] == contrast
                    and item["metric_id"] == metric_id
                )
                mean, wins, ties, losses = expected_value
                self.assertAlmostEqual(row["mean_difference"], mean, places=15)
                self.assertEqual((row["win_count"], row["tie_count"], row["loss_count"]), (wins, ties, losses))

        interaction_expected = {
            ("qwen", "token_f1"): (-0.05332831149193669, 13, 25, 22),
            ("qwen", "strict_accuracy"): (0.0, 5, 49, 6),
            ("qwen", "soft_semantic_score"): (-0.016666666666666666, 6, 46, 8),
            ("deepseek", "token_f1"): (-0.009959976630095279, 22, 12, 26),
            ("deepseek", "strict_accuracy"): (0.016666666666666666, 5, 51, 4),
            ("deepseek", "soft_semantic_score"): (0.05, 8, 48, 4),
        }
        for key, expected_value in interaction_expected.items():
            row = next(
                item
                for item in self.interaction_aggregate
                if item["backbone_id"] == key[0] and item["metric_id"] == key[1]
            )
            mean, wins, ties, losses = expected_value
            self.assertAlmostEqual(row["mean_did"], mean, places=15)
            self.assertEqual((row["win_count"], row["tie_count"], row["loss_count"]), (wins, ties, losses))

    def test_transitions_and_did_recompute(self):
        pair_groups = defaultdict(list)
        for row in self.pairs:
            pair_groups[(row["backbone_id"], row["contrast_id"], row["metric_id"])].append(row)
        for key, rows in pair_groups.items():
            denominator = rows[0]["denominator_scope"]
            expected_n = 60 if denominator == "answer_all" else 58 if denominator == "evidence_eligible" else 19
            self.assertEqual(len(rows), expected_n, key)
            self.assertTrue(
                all(
                    math.isclose(
                        row["raw_difference"],
                        row["target_value"] - row["baseline_value"],
                        abs_tol=TIE_TOLERANCE,
                    )
                    for row in rows
                )
            )
        for backbone in ("qwen", "deepseek"):
            for contrast in {
                "storage_r1_e3_minus_e1",
                "storage_r2_e4_minus_e2",
                "retrieval_s1_e2_minus_e1",
                "retrieval_s2_e4_minus_e3",
            }:
                self.assertEqual(
                    sum(
                        row["count"]
                        for row in self.strict
                        if row["backbone_id"] == backbone and row["contrast_id"] == contrast
                    ),
                    60,
                )
                self.assertEqual(
                    sum(
                        row["count"]
                        for row in self.semantic
                        if row["backbone_id"] == backbone and row["contrast_id"] == contrast
                    ),
                    60,
                )
        for row in self.interaction:
            did_a = (row["e4_value"] - row["e2_value"]) - (row["e3_value"] - row["e1_value"])
            did_b = (row["e4_value"] - row["e3_value"]) - (row["e2_value"] - row["e1_value"])
            self.assertLessEqual(abs(did_a - did_b), ALGEBRA_TOLERANCE)
            self.assertLessEqual(abs(row["did_storage_form"] - did_a), ALGEBRA_TOLERANCE)
            self.assertLessEqual(abs(row["did_retrieval_form"] - did_b), ALGEBRA_TOLERANCE)

    def test_bootstrap_independent_recomputation(self):
        index = {
            (row["backbone_id"], row["condition_id"], row["question_id"]): row
            for row in self.stage_a_rows
        }
        ordered_questions = [
            row["question_id"]
            for row in sorted(
                [r for r in self.stage_a_rows if r["backbone_id"] == "qwen" and r["condition_id"] == "E1"],
                key=lambda row: row["global_position"],
            )
        ]
        effects = {
            "storage_r1_e3_minus_e1": ("E3", "E1"),
            "storage_r2_e4_minus_e2": ("E4", "E2"),
            "retrieval_s1_e2_minus_e1": ("E2", "E1"),
            "retrieval_s2_e4_minus_e3": ("E4", "E3"),
        }
        fields = {
            "token_f1": "token_f1",
            "strict_accuracy": "strict_score",
            "soft_semantic_score": "soft_semantic_score",
        }
        vectors = {}
        for backbone in ("qwen", "deepseek"):
            for effect_id, (target, baseline) in effects.items():
                for metric_id, field in fields.items():
                    vectors[(backbone, effect_id, metric_id)] = [
                        index[(backbone, target, qid)][field] - index[(backbone, baseline, qid)][field]
                        for qid in ordered_questions
                    ]
            for metric_id, field in fields.items():
                vectors[(backbone, "storage_retrieval_interaction", metric_id)] = [
                    (
                        index[(backbone, "E4", qid)][field]
                        - index[(backbone, "E2", qid)][field]
                    )
                    - (
                        index[(backbone, "E3", qid)][field]
                        - index[(backbone, "E1", qid)][field]
                    )
                    for qid in ordered_questions
                ]
        rng = random.Random(BOOTSTRAP_SEED)
        digest = hashlib.sha256()
        distributions = {key: [] for key in vectors}
        for _ in range(BOOTSTRAP_REPLICATES):
            sample = [rng.randrange(60) for _ in range(60)]
            digest.update(bytes(sample))
            for key, vector in vectors.items():
                distributions[key].append(math.fsum(vector[index] for index in sample) / 60)
        for row in self.bootstrap:
            key = (row["backbone_id"], row["effect_id"], row["metric_id"])
            values = distributions[key]
            self.assertAlmostEqual(row["point_estimate"], math.fsum(vectors[key]) / 60, places=15)
            self.assertAlmostEqual(row["ci_lower"], _type7(values, 0.025), places=15)
            self.assertAlmostEqual(row["ci_upper"], _type7(values, 0.975), places=15)
            self.assertEqual(row["sample_index_sha256"], digest.hexdigest())

    def test_tamper_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            copied = Path(directory) / "stage-b"
            shutil.copytree(STAGE_B, copied)
            path = copied / "aggregate-effects.jsonl"
            path.write_bytes(path.read_bytes() + b"\n")
            with self.assertRaises(EvidenceValidationError):
                audit_stage_b_output(stage_a_dir=STAGE_A, output_dir=copied)


if __name__ == "__main__":
    unittest.main()
