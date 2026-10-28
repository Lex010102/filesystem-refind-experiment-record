from __future__ import annotations

import hashlib
import json
import math
import shutil
import tempfile
import unittest
from collections import Counter
from pathlib import Path

from fs_memory_lab.chapter5_rq3 import (
    STAGE_RQ3_PROTOCOL_VERSION,
    audit_rq3_output,
    build_rq3,
)
from fs_memory_lab.evidence import EvidenceValidationError


REPO_ROOT = Path(__file__).resolve().parents[1]
STAGE_A = REPO_ROOT / "artifacts/chapter5-main60-analysis-v1/stage-a"

BACKBONES = ("qwen", "deepseek")
PARENTS = ("E2", "E6")
CONDITIONS = ("E2", "E6", "E7")
ANSWER_DENOMINATOR = 60
EVIDENCE_DENOMINATOR = 58
CATEGORY_ANSWER_DENOMINATORS = {1: 13, 2: 13, 3: 7, 4: 27}
CATEGORY_EVIDENCE_DENOMINATORS = {1: 13, 2: 13, 3: 5, 4: 27}
CATEGORY_NAMES = {
    1: "multi-hop",
    2: "temporal",
    3: "open-domain",
    4: "single-hop",
}
OUTCOMES = ("preserve", "harm", "repair", "unresolved")
LABELS = ("incorrect", "partial", "correct")
FLOAT_TOLERANCE = 1e-12

EXPECTED_EFFECTS = {
    ("qwen", "E2"): {
        "token_precision": -0.04247339426433532,
        "token_recall": 0.01939935064935065,
        "token_f1": -0.034047070556203755,
        "strict_accuracy": 0.06666666666666667,
        "soft_semantic_score": 0.041666666666666664,
        "evidence_recall": 0.11781609195402298,
    },
    ("qwen", "E6"): {
        "token_precision": -0.002815146041149209,
        "token_recall": -0.013100649350649352,
        "token_f1": -0.012247390703481157,
        "strict_accuracy": 0.0,
        "soft_semantic_score": 0.0,
        "evidence_recall": 0.0632183908045977,
    },
    ("deepseek", "E2"): {
        "token_precision": 0.04082491511060634,
        "token_recall": 0.03405303030303031,
        "token_f1": 0.039845438223614436,
        "strict_accuracy": 0.05,
        "soft_semantic_score": 0.09166666666666666,
        "evidence_recall": 0.09770114942528736,
    },
    ("deepseek", "E6"): {
        "token_precision": 0.049795217707525,
        "token_recall": 0.12798881673881674,
        "token_f1": 0.0613956480255325,
        "strict_accuracy": 0.08333333333333333,
        "soft_semantic_score": 0.09166666666666666,
        "evidence_recall": 0.1695402298850575,
    },
}

EXPECTED_OUTCOMES = {
    "qwen": {"preserve": 43, "harm": 4, "repair": 1, "unresolved": 12},
    "deepseek": {"preserve": 42, "harm": 4, "repair": 3, "unresolved": 11},
}

EXPECTED_CATEGORY_OUTCOMES = {
    ("qwen", 1): {"preserve": 9, "harm": 0, "repair": 1, "unresolved": 3},
    ("qwen", 2): {"preserve": 9, "harm": 1, "repair": 0, "unresolved": 3},
    ("qwen", 3): {"preserve": 4, "harm": 0, "repair": 0, "unresolved": 3},
    ("qwen", 4): {"preserve": 21, "harm": 3, "repair": 0, "unresolved": 3},
    ("deepseek", 1): {"preserve": 8, "harm": 1, "repair": 1, "unresolved": 3},
    ("deepseek", 2): {"preserve": 9, "harm": 1, "repair": 2, "unresolved": 1},
    ("deepseek", 3): {"preserve": 2, "harm": 1, "repair": 0, "unresolved": 4},
    ("deepseek", 4): {"preserve": 23, "harm": 1, "repair": 0, "unresolved": 3},
}

EXPECTED_PARENT_COMPLEMENTARITY = {
    "qwen": {
        "both_correct": (37, 37),
        "e2_only_correct": (3, 2),
        "e6_only_correct": (7, 4),
        "neither_correct": (13, 1),
    },
    "deepseek": {
        "both_correct": (36, 35),
        "e2_only_correct": (6, 4),
        "e6_only_correct": (4, 3),
        "neither_correct": (14, 3),
    },
}

EXPECTED_JUDGE_MATRICES = {
    ("qwen", "E2"): [[11, 1, 2], [1, 2, 3], [1, 0, 39]],
    ("qwen", "E6"): [[11, 0, 2], [1, 1, 1], [1, 2, 41]],
    ("deepseek", "E2"): [[7, 5, 5], [0, 0, 1], [2, 1, 39]],
    ("deepseek", "E6"): [[8, 1, 6], [1, 3, 1], [0, 2, 38]],
}

EXPECTED_OVERLAP = {
    "qwen": {
        "mean_e2_source_id_count": 24.583333333333332,
        "mean_e6_source_id_count": 50.15,
        "mean_shared_source_id_count": 10.533333333333333,
        "mean_union_source_id_count": 64.2,
        "mean_source_id_jaccard": 0.1956449708918249,
        "evidence_denominator": 58,
        "gold_source_occurrences": 82,
        "shared_gold_source_occurrences": 53,
        "e2_only_gold_source_occurrences": 7,
        "e6_only_gold_source_occurrences": 11,
        "missing_gold_source_occurrences": 11,
        "e2_unique_gold_question_count": 6,
        "e6_unique_gold_question_count": 9,
        "either_unique_gold_question_count": 14,
        "both_unique_gold_question_count": 1,
        "union_complete_question_count": 49,
        "mean_union_evidence_recall": 0.8994252873563218,
    },
    "deepseek": {
        "mean_e2_source_id_count": 44.6,
        "mean_e6_source_id_count": 60.7,
        "mean_shared_source_id_count": 13.916666666666666,
        "mean_union_source_id_count": 91.38333333333334,
        "mean_source_id_jaccard": 0.15869318999963147,
        "evidence_denominator": 58,
        "gold_source_occurrences": 82,
        "shared_gold_source_occurrences": 48,
        "e2_only_gold_source_occurrences": 13,
        "e6_only_gold_source_occurrences": 10,
        "missing_gold_source_occurrences": 11,
        "e2_unique_gold_question_count": 12,
        "e6_unique_gold_question_count": 8,
        "either_unique_gold_question_count": 19,
        "both_unique_gold_question_count": 1,
        "union_complete_question_count": 49,
        "mean_union_evidence_recall": 0.8951149425287356,
    },
}

EXPECTED_CANDIDATES = {
    ("qwen", "conv-50-q051", "harm"),
    ("qwen", "conv-50-q046", "repair"),
    ("qwen", "conv-50-q126", "harm"),
    ("qwen", "conv-50-q114", "harm"),
    ("qwen", "conv-50-q111", "harm"),
    ("deepseek", "conv-50-q051", "harm"),
    ("deepseek", "conv-50-q022", "harm"),
    ("deepseek", "conv-50-q002", "repair"),
    ("deepseek", "conv-50-q069", "repair"),
    ("deepseek", "conv-50-q046", "harm"),
    ("deepseek", "conv-50-q032", "repair"),
    ("deepseek", "conv-50-q111", "harm"),
}

FORBIDDEN_CONTENT_FIELDS = {
    "question",
    "question_text",
    "reference_answer",
    "candidate_answer",
    "answer",
    "answer_text",
    "evidence",
    "evidence_text",
    "retrieved_text",
    "gold_answer",
    "prompt",
    "response",
    "judge_reason",
    "short_reason",
    "api_key",
    "authorization",
}

TABLES = (
    "parent-effects",
    "category-effects",
    "judge-transitions",
    "fusion-outcomes",
    "fusion-outcome-summary",
    "fusion-outcomes-by-category",
    "parent-complementarity",
    "evidence-source-overlap",
    "question-diagnostics",
    "rq5-candidate-cases",
    "table-5-14-inputs",
    "figure-5-6-inputs",
)


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
        "output_dir": output_dir,
    }


def _close(left: float, right: float) -> bool:
    return math.isclose(float(left), float(right), rel_tol=0.0, abs_tol=FLOAT_TOLERANCE)


def _outcome(e2: dict, e6: dict, e7: dict) -> str:
    parent_correct = bool(e2["strict_score"] or e6["strict_score"])
    fused_correct = bool(e7["strict_score"])
    if parent_correct and fused_correct:
        return "preserve"
    if parent_correct and not fused_correct:
        return "harm"
    if not parent_correct and fused_correct:
        return "repair"
    return "unresolved"


def _parent_stratum(e2: dict, e6: dict) -> str:
    e2_correct = bool(e2["strict_score"])
    e6_correct = bool(e6["strict_score"])
    if e2_correct and e6_correct:
        return "both_correct"
    if e2_correct:
        return "e2_only_correct"
    if e6_correct:
        return "e6_only_correct"
    return "neither_correct"


class Chapter5RQ3ArtifactTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix="chapter5-rq3-test-")
        cls.output = Path(cls.temp.name) / "rq3-dual-source-fusion"
        cls.build_result = build_rq3(**_kwargs(cls.output))
        cls.audit = _json(cls.output / "audit.json")
        cls.marker = _json(cls.output / "RQ3.PASSED")
        cls.schema = _json(cls.output / "schema.json")
        cls.source_rows = _jsonl(STAGE_A / "e1-e7-main.jsonl")
        cls.source = {
            (row["backbone_id"], row["condition_id"], row["question_id"]): row
            for row in cls.source_rows
            if row["condition_id"] in CONDITIONS
        }
        cls.tables = {
            name: _jsonl(cls.output / f"{name}.jsonl") for name in TABLES
        }

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def test_normal_build_independent_audit_hashes_and_exact_file_set(self):
        self.assertEqual(self.build_result["status"], "passed")
        self.assertEqual(
            self.build_result["protocol_version"], STAGE_RQ3_PROTOCOL_VERSION
        )
        audited = audit_rq3_output(**_kwargs(self.output))
        self.assertEqual(audited["status"], "passed")
        self.assertEqual(audited["protocol_version"], STAGE_RQ3_PROTOCOL_VERSION)
        self.assertEqual(audited["audit_id"], self.audit["audit_id"])
        self.assertEqual(self.marker["audit_id"], self.audit["audit_id"])
        self.assertEqual(
            self.marker["audit_sha256"], _sha256(self.output / "audit.json")
        )
        for name, digest in self.audit["output_sha256"].items():
            self.assertEqual(_sha256(self.output / name), digest, name)

        expected = {
            "README.md",
            "schema.json",
            "source-manifest.json",
            "audit.json",
            "RQ3.PASSED",
        }
        for table in TABLES:
            expected.update({f"{table}.csv", f"{table}.jsonl"})
        self.assertEqual({path.name for path in self.output.iterdir()}, expected)

    def test_scope_is_exactly_360_rows_and_120_paired_triples(self):
        self.assertEqual(len(self.source), 360)
        self.assertEqual(
            Counter((key[0], key[1]) for key in self.source),
            Counter({(backbone, condition): 60 for backbone in BACKBONES for condition in CONDITIONS}),
        )
        identity_fields = (
            "question_id",
            "question_sha256",
            "global_position",
            "category",
            "category_name",
            "source_partition",
            "evidence_eligible",
            "gold_dia_ids",
        )
        for backbone in BACKBONES:
            question_ids = {
                key[2]
                for key in self.source
                if key[0] == backbone and key[1] == "E2"
            }
            self.assertEqual(len(question_ids), 60)
            for question_id in question_ids:
                rows = [
                    self.source[(backbone, condition, question_id)]
                    for condition in CONDITIONS
                ]
                for field in identity_fields:
                    self.assertEqual(rows[0][field], rows[1][field], (question_id, field))
                    self.assertEqual(rows[0][field], rows[2][field], (question_id, field))
        self.assertEqual(len(self.tables["fusion-outcomes"]), 8)
        self.assertEqual(len(self.tables["question-diagnostics"]), 120)

    def test_e7_parent_bundles_budget_union_and_inherited_retrieval_accounting(self):
        retrieval_sum_fields = (
            "retrieval_model_calls",
            "retrieval_prompt_tokens",
            "retrieval_completion_tokens",
            "retrieval_total_tokens",
            "retrieval_provider_rounds",
            "retrieval_filesystem_tool_calls",
            "retrieval_orchestration_calls",
            "retrieval_provider_request_attempts",
        )
        for backbone in BACKBONES:
            for question_id in {
                key[2]
                for key in self.source
                if key[0] == backbone and key[1] == "E2"
            }:
                e2 = self.source[(backbone, "E2", question_id)]
                e6 = self.source[(backbone, "E6", question_id)]
                e7 = self.source[(backbone, "E7", question_id)]
                self.assertEqual(e2["evidence_budget_characters"], 16000)
                self.assertEqual(e6["evidence_budget_characters"], 16000)
                self.assertEqual(e7["evidence_budget_characters"], 32000)
                self.assertLessEqual(e7["evidence_bundle_characters"], 32000)
                self.assertEqual(
                    e7["source_bundle_ids"],
                    [e2["evidence_bundle_id"], e6["evidence_bundle_id"]],
                )
                self.assertEqual(e7["search_action_count"], 0)
                self.assertEqual(e7["retrieval_system"], "fixed_fusion")
                self.assertEqual(e7["access_regime"], "dual_source_fusion")
                self.assertEqual(e7["storage_representation"], "E2+E6")
                self.assertEqual(
                    set(e7["retrieved_dia_ids"]),
                    set(e2["retrieved_dia_ids"]) | set(e6["retrieved_dia_ids"]),
                )
                self.assertEqual(
                    e7["evidence_bundle_characters"],
                    e2["evidence_bundle_characters"] + e6["evidence_bundle_characters"],
                )
                self.assertEqual(
                    e7["evidence_item_count"],
                    e2["evidence_item_count"] + e6["evidence_item_count"],
                )
                for field in retrieval_sum_fields:
                    self.assertEqual(e7[field], e2[field] + e6[field], (question_id, field))
                self.assertEqual(
                    e7["query_model_calls"],
                    e2["retrieval_model_calls"]
                    + e6["retrieval_model_calls"]
                    + e7["answer_model_calls"],
                )
                self.assertEqual(
                    e7["query_total_tokens"],
                    e2["retrieval_total_tokens"]
                    + e6["retrieval_total_tokens"]
                    + e7["answer_total_tokens"],
                )

    def test_parent_effects_exact_anchors_and_independent_paired_algebra(self):
        rows = {
            (row["backbone_id"], row["baseline_condition"]): row
            for row in self.tables["parent-effects"]
        }
        self.assertEqual(set(rows), set(EXPECTED_EFFECTS))
        source_fields = {
            "token_precision": "token_precision",
            "token_recall": "token_recall",
            "token_f1": "token_f1",
            "strict_accuracy": "strict_score",
            "soft_semantic_score": "soft_semantic_score",
            "evidence_recall": "evidence_recall",
        }
        for key, expected in EXPECTED_EFFECTS.items():
            backbone, parent = key
            row = rows[key]
            self.assertEqual(row["target_condition"], "E7")
            self.assertEqual(row["answer_denominator"], 60)
            self.assertEqual(row["evidence_denominator"], 58)
            self.assertIs(row["descriptive_only"], True)
            for metric, expected_value in expected.items():
                self.assertAlmostEqual(row[f"delta_{metric}"], expected_value, places=15)
                values = []
                for question_id in {
                    k[2] for k in self.source if k[0] == backbone and k[1] == "E2"
                }:
                    target_value = self.source[(backbone, "E7", question_id)][source_fields[metric]]
                    parent_value = self.source[(backbone, parent, question_id)][source_fields[metric]]
                    if target_value is not None and parent_value is not None:
                        values.append(float(target_value) - float(parent_value))
                denominator = 58 if metric == "evidence_recall" else 60
                self.assertEqual(len(values), denominator)
                self.assertTrue(
                    _close(row[f"delta_{metric}"], math.fsum(values) / len(values))
                )

        report_rows = self.tables["table-5-14-inputs"]
        self.assertEqual(len(report_rows), 4)
        for row in report_rows:
            source = rows[(row["backbone_id"], row["baseline_condition"])]
            for metric in source_fields:
                self.assertEqual(row[f"delta_{metric}"], source[f"delta_{metric}"])

    def test_category_effects_have_exact_denominators_and_numeric_anchors(self):
        rows = {
            (row["backbone_id"], row["baseline_condition"], int(row["category"])): row
            for row in self.tables["category-effects"]
        }
        self.assertEqual(len(rows), 16)
        self.assertEqual(
            set(rows),
            {
                (backbone, parent, category)
                for backbone in BACKBONES
                for parent in PARENTS
                for category in CATEGORY_ANSWER_DENOMINATORS
            },
        )
        for (backbone, parent, category), row in rows.items():
            self.assertEqual(row["category_name"], CATEGORY_NAMES[category])
            self.assertEqual(
                row["answer_denominator"], CATEGORY_ANSWER_DENOMINATORS[category]
            )
            self.assertEqual(
                row["evidence_denominator"], CATEGORY_EVIDENCE_DENOMINATORS[category]
            )
            self.assertIs(row["descriptive_only"], True)

        # Mechanism anchors used in the prose: Qwen gains semantically on
        # multi-hop, loses on simple S3-parent single-hop; DeepSeek benefits
        # most consistently on temporal questions, while open-domain is mixed.
        self.assertAlmostEqual(
            rows[("qwen", "E2", 1)]["delta_strict_accuracy"], 2 / 13, places=15
        )
        self.assertAlmostEqual(
            rows[("qwen", "E2", 1)]["delta_soft_semantic_score"], 1.5 / 13, places=15
        )
        self.assertAlmostEqual(
            rows[("qwen", "E6", 4)]["delta_strict_accuracy"], -2 / 27, places=15
        )
        self.assertAlmostEqual(
            rows[("deepseek", "E6", 2)]["delta_strict_accuracy"], 3 / 13, places=15
        )
        self.assertAlmostEqual(
            rows[("deepseek", "E6", 2)]["delta_soft_semantic_score"], 3 / 13, places=15
        )
        self.assertAlmostEqual(
            rows[("deepseek", "E2", 3)]["delta_token_f1"],
            0.131577118926112,
            places=15,
        )
        self.assertAlmostEqual(
            rows[("deepseek", "E2", 3)]["delta_strict_accuracy"], -1 / 7, places=15
        )

    def test_outcome_partition_overall_category_and_parent_complementarity(self):
        question_rows = self.tables["question-diagnostics"]
        self.assertEqual(len(question_rows), 120)
        keys = {(row["backbone_id"], row["question_id"]) for row in question_rows}
        self.assertEqual(len(keys), 120)
        observed = Counter((row["backbone_id"], row["fusion_outcome"]) for row in question_rows)
        for backbone, expected in EXPECTED_OUTCOMES.items():
            self.assertEqual(
                {outcome: observed[(backbone, outcome)] for outcome in OUTCOMES},
                expected,
            )
        aggregate_rows = {
            (row["backbone_id"], row["fusion_outcome"]): row
            for row in self.tables["fusion-outcomes"]
        }
        self.assertEqual(len(aggregate_rows), 8)
        for backbone, expected in EXPECTED_OUTCOMES.items():
            for outcome, count in expected.items():
                row = aggregate_rows[(backbone, outcome)]
                self.assertEqual(row["denominator"], 60)
                self.assertEqual(row["count"], count)
                self.assertAlmostEqual(row["proportion"], count / 60, places=15)
        for row in question_rows:
            key = (row["backbone_id"], row["question_id"])
            e2 = self.source[(key[0], "E2", key[1])]
            e6 = self.source[(key[0], "E6", key[1])]
            e7 = self.source[(key[0], "E7", key[1])]
            self.assertEqual(row["fusion_outcome"], _outcome(e2, e6, e7))
            self.assertEqual(row["parent_profile"], _parent_stratum(e2, e6))

        category_rows = {
            (row["backbone_id"], int(row["category"]), row["fusion_outcome"]): row
            for row in self.tables["fusion-outcomes-by-category"]
        }
        self.assertEqual(len(category_rows), 32)
        for key, expected in EXPECTED_CATEGORY_OUTCOMES.items():
            for outcome, count in expected.items():
                row = category_rows[(key[0], key[1], outcome)]
                self.assertEqual(row["denominator"], CATEGORY_ANSWER_DENOMINATORS[key[1]])
                self.assertEqual(row["category_name"], CATEGORY_NAMES[key[1]])
                self.assertEqual(row["count"], count)
            self.assertEqual(
                sum(category_rows[(key[0], key[1], outcome)]["count"] for outcome in OUTCOMES),
                CATEGORY_ANSWER_DENOMINATORS[key[1]],
            )

        complementarity = {
            (row["backbone_id"], row["parent_profile"]): row
            for row in self.tables["parent-complementarity"]
        }
        self.assertEqual(len(complementarity), 8)
        for backbone, strata in EXPECTED_PARENT_COMPLEMENTARITY.items():
            for stratum, (count, e7_correct) in strata.items():
                row = complementarity[(backbone, stratum)]
                self.assertEqual(row["count"], count)
                diagnostics = [
                    item
                    for item in question_rows
                    if item["backbone_id"] == backbone
                    and item["parent_profile"] == stratum
                ]
                self.assertEqual(sum(item["e7_strict_score"] == 1.0 for item in diagnostics), e7_correct)
                self.assertEqual(sum(item["e7_strict_score"] == 0.0 for item in diagnostics), count - e7_correct)

        figure_rows = {
            (
                row["backbone_id"],
                row["parent_profile"],
                bool(row["e7_strict_correct"]),
            ): row
            for row in self.tables["figure-5-6-inputs"]
        }
        self.assertEqual(len(figure_rows), 16)
        for backbone, strata in EXPECTED_PARENT_COMPLEMENTARITY.items():
            for stratum, (count, e7_correct) in strata.items():
                correct = figure_rows[(backbone, stratum, True)]
                incorrect = figure_rows[(backbone, stratum, False)]
                self.assertEqual(correct["count"], e7_correct)
                self.assertEqual(incorrect["count"], count - e7_correct)
                self.assertEqual(correct["count"] + incorrect["count"], count)

        summaries = {row["backbone_id"]: row for row in self.tables["fusion-outcome-summary"]}
        self.assertEqual(set(summaries), set(BACKBONES))
        expected_summary = {
            "qwen": (47, 44, 1 / 13, 4 / 47, -3 / 60),
            "deepseek": (46, 45, 3 / 14, 4 / 46, -1 / 60),
        }
        for backbone, (oracle, e7_correct, repair_rate, harm_rate, net) in expected_summary.items():
            row = summaries[backbone]
            self.assertEqual(row["question_denominator"], 60)
            self.assertEqual(row["parent_oracle_correct_count"], oracle)
            self.assertEqual(row["e7_correct_count"], e7_correct)
            self.assertAlmostEqual(row["conditional_repair_rate"], repair_rate, places=15)
            self.assertAlmostEqual(row["conditional_harm_rate"], harm_rate, places=15)
            self.assertAlmostEqual(row["net_vs_parent_oracle_rate"], net, places=15)

    def test_judge_transition_matrices_are_complete_and_exact(self):
        rows = self.tables["judge-transitions"]
        self.assertEqual(len(rows), 36)
        indexed = {
            (
                row["backbone_id"],
                row["baseline_condition"],
                row["parent_label"],
                row["e7_label"],
            ): row
            for row in rows
        }
        self.assertEqual(len(indexed), 36)
        for key, matrix in EXPECTED_JUDGE_MATRICES.items():
            backbone, parent = key
            total = 0
            for from_index, parent_label in enumerate(LABELS):
                for to_index, e7_label in enumerate(LABELS):
                    row = indexed[(backbone, parent, parent_label, e7_label)]
                    self.assertEqual(row["count"], matrix[from_index][to_index])
                    self.assertEqual(row["denominator"], 60)
                    total += row["count"]
            self.assertEqual(total, 60)

    def test_source_overlap_gold_marginals_and_e7_union_recall(self):
        rows = {
            row["backbone_id"]: row for row in self.tables["evidence-source-overlap"]
        }
        self.assertEqual(set(rows), set(BACKBONES))
        for backbone, expected in EXPECTED_OVERLAP.items():
            row = rows[backbone]
            for field, value in expected.items():
                if isinstance(value, float):
                    self.assertAlmostEqual(row[field], value, places=15)
                else:
                    self.assertEqual(row[field], value)
            self.assertEqual(
                row["shared_gold_source_occurrences"]
                + row["e2_only_gold_source_occurrences"]
                + row["e6_only_gold_source_occurrences"]
                + row["missing_gold_source_occurrences"],
                row["gold_source_occurrences"],
            )

        # Independently establish that E7 Evidence Recall is exactly the gold
        # recall of the union of the two parent source-ID sets on all 58
        # evidence-eligible questions, not an assumed 60-question denominator.
        for backbone in BACKBONES:
            eligible = 0
            for question_id in {
                key[2] for key in self.source if key[0] == backbone and key[1] == "E2"
            }:
                e2 = self.source[(backbone, "E2", question_id)]
                e6 = self.source[(backbone, "E6", question_id)]
                e7 = self.source[(backbone, "E7", question_id)]
                if not e2["evidence_eligible"]:
                    self.assertIsNone(e7["evidence_recall"])
                    continue
                eligible += 1
                gold = set(e2["gold_dia_ids"])
                parent_union = set(e2["retrieved_dia_ids"]) | set(e6["retrieved_dia_ids"])
                expected_recall = len(gold & parent_union) / len(gold)
                self.assertTrue(_close(e7["evidence_recall"], expected_recall))
            self.assertEqual(eligible, 58)

        ineligible = [
            row
            for row in self.tables["question-diagnostics"]
            if not row["evidence_eligible"]
        ]
        self.assertEqual(len(ineligible), 4)
        self.assertEqual(
            {row["evidence_contribution_class"] for row in ineligible},
            {"not_applicable_no_gold_annotation"},
        )

    def test_rq5_candidates_are_exactly_the_twelve_repair_or_harm_cases(self):
        rows = self.tables["rq5-candidate-cases"]
        self.assertEqual(len(rows), 12)
        observed = {
            (row["backbone_id"], row["question_id"], row["fusion_outcome"])
            for row in rows
        }
        self.assertEqual(observed, EXPECTED_CANDIDATES)
        self.assertTrue(all(row["fusion_outcome"] in {"repair", "harm"} for row in rows))
        self.assertTrue(all(FORBIDDEN_CONTENT_FIELDS.isdisjoint(row) for row in rows))

    def test_schema_manifest_scope_row_counts_and_no_text_payloads(self):
        expected_counts = {
            "parent-effects": 4,
            "category-effects": 16,
            "judge-transitions": 36,
            "fusion-outcomes": 8,
            "fusion-outcome-summary": 2,
            "fusion-outcomes-by-category": 32,
            "parent-complementarity": 8,
            "evidence-source-overlap": 2,
            "question-diagnostics": 120,
            "rq5-candidate-cases": 12,
            "table-5-14-inputs": 4,
            "figure-5-6-inputs": 16,
        }
        for table, count in expected_counts.items():
            self.assertEqual(len(self.tables[table]), count, table)
            self.assertEqual(self.schema["tables"][table]["row_count"], count, table)
            for row in self.tables[table]:
                self.assertTrue(FORBIDDEN_CONTENT_FIELDS.isdisjoint(row), (table, row.keys()))

        manifest = _json(self.output / "source-manifest.json")
        self.assertIs(manifest["no_api_calls"], True)
        self.assertIs(manifest["no_network_calls"], True)
        self.assertIs(manifest["new_bootstrap_computed"], False)
        self.assertIs(manifest["full_context_computed"], False)
        self.assertEqual(manifest["conditions"], list(CONDITIONS))
        self.assertEqual(manifest["question_denominator"], 60)
        self.assertEqual(manifest["evidence_denominator"], 58)
        self.assertEqual(
            manifest["stage_a_audit_id"],
            "stage-a-audit-5f55ec411f097df7206fdae5e71742641aa8868b4128ac32262f034877a1d7f3",
        )
        self.assertEqual(
            manifest["stage_a_main_sha256"],
            "4ccb595baddaec2ddf54a708e94102a45c72e0ddaff63a6c69c940232153f3f8",
        )
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

        self.assertIs(self.audit["no_api_calls"], True)
        self.assertIs(self.audit["no_network_calls"], True)
        self.assertIs(self.audit["new_bootstrap_computed"], False)
        self.assertIs(self.audit["formal_source_mutation"], False)

    def test_tamper_and_extra_file_are_rejected(self):
        with tempfile.TemporaryDirectory(prefix="chapter5-rq3-tamper-") as directory:
            copied = Path(directory) / "rq3-dual-source-fusion"
            shutil.copytree(self.output, copied)
            path = copied / "parent-effects.jsonl"
            rows = _jsonl(path)
            rows[0]["delta_token_f1"] = float(rows[0]["delta_token_f1"]) + 0.001
            path.write_text(
                "".join(
                    json.dumps(row, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
                    + "\n"
                    for row in rows
                ),
                encoding="utf-8",
            )
            with self.assertRaises(EvidenceValidationError):
                audit_rq3_output(**_kwargs(copied))

        with tempfile.TemporaryDirectory(prefix="chapter5-rq3-extra-") as directory:
            copied = Path(directory) / "rq3-dual-source-fusion"
            shutil.copytree(self.output, copied)
            (copied / "unexpected.txt").write_text(
                "not part of the RQ3 artifact", encoding="utf-8"
            )
            with self.assertRaises(EvidenceValidationError):
                audit_rq3_output(**_kwargs(copied))

    def test_atomic_builder_refuses_existing_destination(self):
        with self.assertRaises(EvidenceValidationError):
            build_rq3(**_kwargs(self.output))


if __name__ == "__main__":
    unittest.main()
