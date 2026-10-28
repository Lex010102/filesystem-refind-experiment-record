"""Offline audit for Chapter 5 Section 5.6.5.

The stage measures disagreement between category-aware LoCoMo token scores and
the frozen LLM-judge labels.  It then joins a bounded, text-free manual review
of four diagnostic tails to explain *why* the metrics disagree.  The screens
are candidate selectors, not definitions of evaluator error.

No model or network call is made.  Formal answers, references, scores, prompts,
and Judge records are read only.  Published artifacts contain identifiers,
metrics, hashes, and review codes, but no question, answer, evidence, prompt,
or Judge-rationale text.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import os
import shutil
import statistics
import tempfile
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from .chapter5_rq5_stage1 import audit_rq5_stage1_output
from .chapter5_stage_a import _load_gold, audit_stage_a_output
from .chapter5_stage_b import _csv_payload, _jsonl_payload, _require, _sha256_file, _write
from .evidence import canonical_json_bytes, sha256_bytes
from .evaluation import normalize_answer


PROTOCOL_VERSION = "chapter5-main60-rq5-evaluation-v1"
EXPECTED_POPULATION = 900
EXPECTED_LABEL_COUNTS = {"correct": 650, "partial": 74, "incorrect": 176}
EXPECTED_SCREEN_COUNTS = {
    "correct_low_f1": 92,
    "partial_low_f1": 31,
    "partial_high_f1": 11,
    "incorrect_nontrivial_f1": 34,
}
EXPECTED_SCREENED_ROWS = 168
EXPECTED_REVIEW_FAMILIES = 18

STAGE_A_DIR = "artifacts/chapter5-main60-analysis-v1/stage-a"
STAGE1_DIR = "artifacts/chapter5-main60-analysis-v1/rq5-root-cause-index"
DEFAULT_REVIEW_PATH = "docs/analysis/reviews/chapter5-rq5-evaluation-disagreement-review-v1.json"
DEFAULT_OUTPUT_DIR = "artifacts/chapter5-main60-analysis-v1/rq5-evaluation-audit"

JUDGE_PATHS = {
    "qwen": "experiments/locomo-conv50-v1/results/llm-judge-x-test1-main120/llm-judge-x-test1-model1-main60-run-01/results.json",
    "deepseek": "experiments/locomo-conv50-v1/results/llm-judge-x-test1-main120/llm-judge-x-test1-model2-main60-run-01/results.json",
    "deepseek_family_full_context": "local-runs/b3-full-context-v3-model2-1017-judge-x-test1/llm-judge-x-test1-b3-full-context-main60-run-01/results.json",
}

ARCHITECTURE_SOURCE_PATHS = {
    "rq1": "artifacts/chapter5-main60-analysis-v1/stage-e-rq1/architecture-effects.csv",
    "rq2": "artifacts/chapter5-main60-analysis-v1/rq2-backbone-robustness/architecture-stability.csv",
    "rq3": "artifacts/chapter5-main60-analysis-v1/rq3-dual-source-fusion/parent-effects.csv",
    "rq4": "artifacts/chapter5-main60-analysis-v1/rq4-full-context/condition-comparisons.csv",
}

LABEL_ORDER = {"incorrect": 1, "partial": 2, "correct": 3}
BACKBONE_ORDER = {"qwen": 1, "deepseek": 2, "deepseek_family_full_context": 3}
CONDITION_ORDER = {**{f"E{i}": i for i in range(1, 8)}, "B3-FullContext": 8}

F1_BINS = (
    ("[0.00,0.10)", 0.00, 0.10),
    ("[0.10,0.25)", 0.10, 0.25),
    ("[0.25,0.50)", 0.25, 0.50),
    ("[0.50,0.75)", 0.50, 0.75),
    ("[0.75,1.00]", 0.75, 1.000000000001),
)

PAIRWISE_COMPARISONS = (
    ("storage_r1_e3_minus_e1", "E1", "E3", ("qwen", "deepseek")),
    ("retrieval_s1_e2_minus_e1", "E1", "E2", ("qwen", "deepseek")),
    ("retrieval_s2_e4_minus_e3", "E3", "E4", ("qwen", "deepseek")),
    ("curated_access_e6_minus_e5", "E5", "E6", ("qwen", "deepseek")),
    ("curated_vs_foldered_r1_e5_minus_e3", "E3", "E5", ("qwen", "deepseek")),
    ("fusion_vs_raw_e7_minus_e2", "E2", "E7", ("qwen", "deepseek")),
    ("fusion_vs_curated_e7_minus_e6", "E6", "E7", ("qwen", "deepseek")),
    ("full_context_minus_e1", "E1", "B3-FullContext", ("deepseek",)),
    ("full_context_minus_e5", "E5", "B3-FullContext", ("deepseek",)),
    ("full_context_minus_e7", "E7", "B3-FullContext", ("deepseek",)),
)

TABLES = (
    "score-distributions",
    "judge-f1-crosstab",
    "disagreement-cases",
    "cause-summary",
    "cause-by-category",
    "exact-input-consistency",
    "metric-sensitive-architecture",
)

FORBIDDEN_FIELDS = {
    "question",
    "question_text",
    "reference",
    "reference_answer",
    "candidate",
    "candidate_answer",
    "answer",
    "answer_text",
    "evidence",
    "evidence_text",
    "short_reason",
    "rationale",
    "prompt",
    "response",
    "api_key",
    "authorization",
}


def _read_json(path: Path) -> dict[str, Any]:
    _require(path.is_file() and not path.is_symlink(), f"Missing or unsafe JSON: {path}")
    value = json.loads(path.read_text(encoding="utf-8"))
    _require(isinstance(value, dict), f"JSON root must be an object: {path}")
    return value


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    _require(path.is_file() and not path.is_symlink(), f"Missing or unsafe JSONL: {path}")
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        value = json.loads(line)
        _require(isinstance(value, dict), f"JSONL row must be an object: {path}")
        rows.append(dict(value))
    return rows


def _read_csv(path: Path) -> list[dict[str, str]]:
    _require(path.is_file() and not path.is_symlink(), f"Missing or unsafe CSV: {path}")
    with path.open(newline="", encoding="utf-8") as handle:
        return [dict(row) for row in csv.DictReader(handle)]


def _relative(root: Path, path: Path) -> str:
    return str(path.resolve().relative_to(root.resolve()))


def _artifact(root: Path, path: Path) -> dict[str, Any]:
    return {"path": _relative(root, path), "sha256": _sha256_file(path), "bytes": path.stat().st_size}


def _artifact_id(prefix: str, body: Mapping[str, Any]) -> str:
    return prefix + sha256_bytes(canonical_json_bytes(dict(body)))


def _quantile(values: Sequence[float], probability: float) -> float:
    _require(bool(values), "Cannot compute a quantile of an empty sequence")
    ordered = sorted(float(value) for value in values)
    position = (len(ordered) - 1) * probability
    lower = int(math.floor(position))
    upper = int(math.ceil(position))
    if lower == upper:
        return ordered[lower]
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)


def _pearson(left: Sequence[float], right: Sequence[float]) -> float:
    _require(len(left) == len(right) and bool(left), "Pearson inputs differ")
    left_mean = statistics.mean(left)
    right_mean = statistics.mean(right)
    numerator = sum((a - left_mean) * (b - right_mean) for a, b in zip(left, right))
    left_scale = math.sqrt(sum((a - left_mean) ** 2 for a in left))
    right_scale = math.sqrt(sum((b - right_mean) ** 2 for b in right))
    _require(left_scale > 0.0 and right_scale > 0.0, "Pearson scale is zero")
    return numerator / (left_scale * right_scale)


def _screen(row: Mapping[str, Any]) -> str | None:
    label = str(row["judge_label"])
    f1 = float(row["token_f1"])
    if label == "correct" and f1 < 0.10:
        return "correct_low_f1"
    if label == "partial" and f1 < 0.10:
        return "partial_low_f1"
    if label == "partial" and f1 >= 0.50:
        return "partial_high_f1"
    if label == "incorrect" and f1 >= 0.10:
        return "incorrect_nontrivial_f1"
    return None


def _load_judges(root: Path) -> tuple[dict[str, dict[tuple[str, str], dict[str, Any]]], list[dict[str, Any]]]:
    output: dict[str, dict[tuple[str, str], dict[str, Any]]] = {}
    artifacts: list[dict[str, Any]] = []
    expected_counts = {"qwen": 420, "deepseek": 420, "deepseek_family_full_context": 60}
    for backbone, relative in JUDGE_PATHS.items():
        path = root / relative
        value = _read_json(path)
        members = value.get("results")
        _require(isinstance(members, list) and len(members) == expected_counts[backbone], "Judge result count differs")
        rows: dict[tuple[str, str], dict[str, Any]] = {}
        for raw in members:
            _require(isinstance(raw, Mapping), "Judge result row is invalid")
            row = dict(raw)
            key = (str(row["condition_id"]), str(row["question_id"]))
            _require(key not in rows, "Judge result key repeats")
            rows[key] = row
        output[backbone] = rows
        artifacts.append(_artifact(root, path))
    return output, artifacts


def _validate_review(review: Mapping[str, Any], screened: Sequence[Mapping[str, Any]]) -> dict[tuple[str, str], dict[str, Any]]:
    _require(review.get("protocol_version") == "chapter5-rq5-evaluation-disagreement-review-v1", "Review protocol differs")
    _require(review.get("review_status") == "completed", "Review is incomplete")
    families = review.get("families")
    _require(isinstance(families, list) and len(families) == EXPECTED_REVIEW_FAMILIES, "Review family count differs")
    lookup: dict[tuple[str, str], dict[str, Any]] = {}
    for raw in families:
        _require(isinstance(raw, Mapping), "Review family is invalid")
        family = dict(raw)
        if "assignments" in family:
            _require("screens" not in family and "question_ids" not in family, "Review assignment styles mix")
            assignments = family["assignments"]
            _require(isinstance(assignments, list) and assignments, "Review assignments are invalid")
        else:
            assignments = [
                {"screen_id": screen, "question_ids": family["question_ids"]}
                for screen in family["screens"]
            ]
        family_keys: set[tuple[str, str]] = set()
        for assignment in assignments:
            _require(isinstance(assignment, Mapping), "Review assignment is invalid")
            screen = str(assignment["screen_id"])
            question_ids = assignment["question_ids"]
            _require(screen in EXPECTED_SCREEN_COUNTS, "Review assignment screen is invalid")
            _require(isinstance(question_ids, list) and question_ids, "Review assignment questions are invalid")
            for question_id in question_ids:
                key = (str(screen), str(question_id))
                _require(key not in lookup, f"Review family assignment repeats: {key}")
                lookup[key] = family
                family_keys.add(key)
        actual = sum((_screen(row), str(row["question_id"])) in family_keys for row in screened)
        _require(actual == int(family["expected_rows"]), f"Review family denominator differs: {family['family_id']}")
    expected = {(_screen(row), str(row["question_id"])) for row in screened}
    _require(None not in {key[0] for key in expected}, "Unscreened row entered review")
    _require(expected == set(lookup), "Review family declarations do not exactly match screened question families")
    _require(
        {str(family["family_id"]) for family in families}
        == {str(lookup[key]["family_id"]) for key in expected},
        "A declared review family has no screened member",
    )
    return lookup


def _score_distributions(rows: Sequence[Mapping[str, Any]], gold: Mapping[str, Any]) -> list[dict[str, Any]]:
    groups: list[tuple[str, Callable[[Mapping[str, Any]], bool]]] = [("all", lambda _: True)]
    groups.extend((label, lambda row, label=label: row["judge_label"] == label) for label in ("incorrect", "partial", "correct"))
    output: list[dict[str, Any]] = []
    for order, (group, predicate) in enumerate(groups, 1):
        selected = [row for row in rows if predicate(row)]
        f1 = [float(row["token_f1"]) for row in selected]
        precision = [float(row["token_precision"]) for row in selected]
        recall = [float(row["token_recall"]) for row in selected]
        answer_tokens = [int(row["answer_normalized_tokens"]) for row in selected]
        reference_tokens = [max(1, len(normalize_answer(gold[str(row["question_id"])].answer).split())) for row in selected]
        ratios = [answer / reference for answer, reference in zip(answer_tokens, reference_tokens)]
        output.append(
            {
                "group_order": order,
                "judge_group": group,
                "n": len(selected),
                "mean_token_precision": statistics.mean(precision),
                "mean_token_recall": statistics.mean(recall),
                "mean_token_f1": statistics.mean(f1),
                "median_token_f1": statistics.median(f1),
                "q1_token_f1": _quantile(f1, 0.25),
                "q3_token_f1": _quantile(f1, 0.75),
                "min_token_f1": min(f1),
                "max_token_f1": max(f1),
                "mean_answer_tokens": statistics.mean(answer_tokens),
                "median_answer_tokens": statistics.median(answer_tokens),
                "mean_reference_tokens": statistics.mean(reference_tokens),
                "median_reference_tokens": statistics.median(reference_tokens),
                "mean_answer_reference_token_ratio": statistics.mean(ratios),
                "median_answer_reference_token_ratio": statistics.median(ratios),
            }
        )
    return output


def _crosstab(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for bin_order, (name, lower, upper) in enumerate(F1_BINS, 1):
        in_bin = [row for row in rows if lower <= float(row["token_f1"]) < upper]
        for label in ("incorrect", "partial", "correct"):
            count = sum(row["judge_label"] == label for row in in_bin)
            label_total = EXPECTED_LABEL_COUNTS[label]
            output.append(
                {
                    "bin_order": bin_order,
                    "f1_bin": name,
                    "judge_label": label,
                    "count": count,
                    "share_of_bin": count / len(in_bin) if in_bin else 0.0,
                    "share_of_label": count / label_total,
                    "bin_total": len(in_bin),
                    "label_total": label_total,
                }
            )
    return output


def _disagreement_cases(
    *, rows: Sequence[Mapping[str, Any]], judges: Mapping[str, Mapping[tuple[str, str], Mapping[str, Any]]],
    review_lookup: Mapping[tuple[str, str], Mapping[str, Any]], gold: Mapping[str, Any], root: Path,
) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    screen_order = {name: index for index, name in enumerate(EXPECTED_SCREEN_COUNTS, 1)}
    for row in rows:
        screen = _screen(row)
        if screen is None:
            continue
        family = review_lookup[(screen, str(row["question_id"]))]
        judge = judges[str(row["backbone_id"])][(str(row["condition_id"]), str(row["question_id"]))]
        source_path = root / str(row["source_record_path"])
        _require(_sha256_file(source_path) == row["source_record_file_sha256"], "Source record hash differs")
        _require(judge["source_record_id"] == row["source_record_id"], "Judge/source record identity differs")
        _require(judge["label"] == row["judge_label"], "Judge label differs")
        reference_tokens = max(1, len(normalize_answer(gold[str(row["question_id"])].answer).split()))
        body = {
            "protocol_version": PROTOCOL_VERSION,
            "analysis_row_id": row["analysis_row_id"],
            "case_id": row["case_id"],
            "screen_order": screen_order[screen],
            "screen_id": screen,
            "family_id": family["family_id"],
            "primary_cause": family["primary_cause"],
            "interpretation_group": family["interpretation_group"],
            "evaluation_sensitive": bool(family["evaluation_sensitive"]),
            "backbone_id": row["backbone_id"],
            "condition_id": row["condition_id"],
            "question_id": row["question_id"],
            "category_name": row["category_name"],
            "judge_label": row["judge_label"],
            "judge_confidence": judge["confidence"],
            "token_precision": row["token_precision"],
            "token_recall": row["token_recall"],
            "token_f1": row["token_f1"],
            "answer_normalized_tokens": row["answer_normalized_tokens"],
            "reference_normalized_tokens": reference_tokens,
            "answer_reference_token_ratio": int(row["answer_normalized_tokens"]) / reference_tokens,
            "source_record_id": row["source_record_id"],
            "source_record_file_sha256": row["source_record_file_sha256"],
            "judgment_id": judge["judgment_id"],
            "judge_record_candidate_sha256": judge["candidate_answer_sha256"],
            "judge_record_reference_sha256": judge["reference_answer_sha256"],
        }
        output.append({"disagreement_case_id": _artifact_id("rq5-eval-case-", body), **body})
    return sorted(
        output,
        key=lambda row: (
            row["screen_order"], row["family_id"], BACKBONE_ORDER[str(row["backbone_id"])],
            CONDITION_ORDER[str(row["condition_id"])], str(row["question_id"]),
        ),
    )


def _cause_summary(cases: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    groups: dict[tuple[str, str, str, bool], list[Mapping[str, Any]]] = defaultdict(list)
    for row in cases:
        key = (str(row["primary_cause"]), str(row["interpretation_group"]), str(row["screen_id"]), bool(row["evaluation_sensitive"]))
        groups[key].append(row)
    output: list[dict[str, Any]] = []
    for order, (key, members) in enumerate(sorted(groups.items()), 1):
        cause, interpretation, screen, sensitive = key
        output.append(
            {
                "cause_order": order,
                "primary_cause": cause,
                "interpretation_group": interpretation,
                "screen_id": screen,
                "evaluation_sensitive": sensitive,
                "row_count": len(members),
                "unique_question_count": len({row["question_id"] for row in members}),
                "share_of_screen": len(members) / EXPECTED_SCREEN_COUNTS[screen],
                "share_of_population": len(members) / EXPECTED_POPULATION,
                "mean_token_precision": statistics.mean(float(row["token_precision"]) for row in members),
                "mean_token_recall": statistics.mean(float(row["token_recall"]) for row in members),
                "mean_token_f1": statistics.mean(float(row["token_f1"]) for row in members),
                "mean_answer_reference_token_ratio": statistics.mean(float(row["answer_reference_token_ratio"]) for row in members),
            }
        )
    return output


def _cause_by_category(cases: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    groups: dict[tuple[str, str, str], list[Mapping[str, Any]]] = defaultdict(list)
    for row in cases:
        groups[(str(row["screen_id"]), str(row["primary_cause"]), str(row["category_name"]))].append(row)
    return [
        {
            "screen_id": screen,
            "primary_cause": cause,
            "category_name": category,
            "row_count": len(members),
            "unique_question_count": len({row["question_id"] for row in members}),
            "mean_token_f1": statistics.mean(float(row["token_f1"]) for row in members),
        }
        for (screen, cause, category), members in sorted(groups.items())
    ]


def _exact_input_consistency(judges: Mapping[str, Mapping[tuple[str, str], Mapping[str, Any]]]) -> list[dict[str, Any]]:
    groups: dict[tuple[str, str, str], list[Mapping[str, Any]]] = defaultdict(list)
    confidence_counts: Counter[tuple[str, str]] = Counter()
    for backbone_rows in judges.values():
        for row in backbone_rows.values():
            key = (str(row["question_sha256"]), str(row["reference_answer_sha256"]), str(row["candidate_answer_sha256"]))
            groups[key].append(row)
            confidence_counts[(str(row["label"]), str(row["confidence"]))] += 1
    duplicate_groups = [members for members in groups.values() if len(members) > 1]
    conflicts = [members for members in duplicate_groups if len({str(row["label"]) for row in members}) > 1]
    output = [
        {
            "check_order": 1,
            "check_id": "exact_input_label_consistency",
            "record_count": sum(len(members) for members in duplicate_groups),
            "group_count": len(duplicate_groups),
            "conflict_group_count": len(conflicts),
            "status": "passed" if not conflicts else "failed",
            "interpretation": "Exact duplicate inputs were label-consistent; this does not establish stability near semantic decision boundaries.",
        }
    ]
    for order, ((label, confidence), count) in enumerate(sorted(confidence_counts.items()), 2):
        output.append(
            {
                "check_order": order,
                "check_id": f"confidence_{label}_{confidence}",
                "record_count": count,
                "group_count": None,
                "conflict_group_count": None,
                "status": "descriptive",
                "interpretation": "Judge confidence is self-reported and is not treated as a calibrated probability.",
            }
        )
    return output


def _direction(value: float, tolerance: float = 1e-12) -> str:
    if value > tolerance:
        return "positive"
    if value < -tolerance:
        return "negative"
    return "zero"


def _paired_effect(
    *, lookup: Mapping[tuple[str, str, str], Mapping[str, Any]], backbone: str,
    baseline: str, target: str, excluded_questions: set[str],
) -> dict[str, Any]:
    question_ids = sorted(
        question_id for bb, condition, question_id in lookup
        if bb == backbone and condition == baseline and question_id not in excluded_questions
    )
    _require(bool(question_ids), "Paired comparison is empty")
    differences: dict[str, list[float]] = {"token_f1": [], "strict_score": [], "soft_semantic_score": []}
    for question_id in question_ids:
        left = lookup[(backbone, baseline, question_id)]
        target_backbone = "deepseek_family_full_context" if target == "B3-FullContext" else backbone
        right = lookup[(target_backbone, target, question_id)]
        for metric in differences:
            differences[metric].append(float(right[metric]) - float(left[metric]))
    return {"n": len(question_ids), **{f"delta_{metric}": statistics.mean(values) for metric, values in differences.items()}}


def _architecture_sensitivity(rows: Sequence[Mapping[str, Any]], sensitive_questions: set[str]) -> list[dict[str, Any]]:
    lookup = {(str(row["backbone_id"]), str(row["condition_id"]), str(row["question_id"])): row for row in rows}
    output: list[dict[str, Any]] = []
    order = 0
    for comparison_id, baseline, target, backbones in PAIRWISE_COMPARISONS:
        for backbone in backbones:
            order += 1
            complete = _paired_effect(
                lookup=lookup, backbone=backbone, baseline=baseline, target=target, excluded_questions=set()
            )
            sensitivity = _paired_effect(
                lookup=lookup, backbone=backbone, baseline=baseline, target=target,
                excluded_questions=sensitive_questions,
            )
            f1_direction = _direction(float(complete["delta_token_f1"]))
            strict_direction = _direction(float(complete["delta_strict_score"]))
            output.append(
                {
                    "comparison_order": order,
                    "comparison_id": comparison_id,
                    "backbone_id": backbone,
                    "baseline_condition": baseline,
                    "target_condition": target,
                    "complete_n": complete["n"],
                    "complete_delta_token_f1": complete["delta_token_f1"],
                    "complete_delta_strict_accuracy": complete["delta_strict_score"],
                    "complete_delta_soft_semantic_score": complete["delta_soft_semantic_score"],
                    "f1_direction": f1_direction,
                    "strict_direction": strict_direction,
                    "metric_direction_relation": "same" if f1_direction == strict_direction else "different",
                    "diagnostic_exclusion_question_count": len(sensitive_questions),
                    "diagnostic_n": sensitivity["n"],
                    "diagnostic_delta_token_f1": sensitivity["delta_token_f1"],
                    "diagnostic_delta_strict_accuracy": sensitivity["delta_strict_score"],
                    "diagnostic_delta_soft_semantic_score": sensitivity["delta_soft_semantic_score"],
                    "f1_direction_after_exclusion": _direction(float(sensitivity["delta_token_f1"])),
                    "strict_direction_after_exclusion": _direction(float(sensitivity["delta_strict_score"])),
                    "f1_direction_preserved": f1_direction == _direction(float(sensitivity["delta_token_f1"])),
                    "strict_direction_preserved": strict_direction == _direction(float(sensitivity["delta_strict_score"])),
                    "descriptive_only": True,
                }
            )
    return output


def _validate_architecture_anchors(root: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    anchors: dict[tuple[str, str], dict[str, str]] = {}
    sources = (
        (root / ARCHITECTURE_SOURCE_PATHS["rq1"], None),
        (root / ARCHITECTURE_SOURCE_PATHS["rq3"], None),
        (root / ARCHITECTURE_SOURCE_PATHS["rq4"], "deepseek"),
    )
    required = {(str(row["comparison_id"]), str(row["backbone_id"])) for row in rows}
    for path, fixed_backbone in sources:
        for source in _read_csv(path):
            key = (str(source["comparison_id"]), fixed_backbone or str(source["backbone_id"]))
            if key not in required:
                continue
            _require(key not in anchors, f"Architecture anchor repeats: {key}")
            anchors[key] = source
    _require(set(anchors) == required, "Architecture anchors do not cover every diagnostic comparison")
    for row in rows:
        key = (str(row["comparison_id"]), str(row["backbone_id"]))
        source = anchors[key]
        for local_field, source_field in (
            ("complete_delta_token_f1", "delta_token_f1"),
            ("complete_delta_strict_accuracy", "delta_strict_accuracy"),
            ("complete_delta_soft_semantic_score", "delta_soft_semantic_score"),
        ):
            _require(
                math.isclose(float(row[local_field]), float(source[source_field]), rel_tol=0.0, abs_tol=1e-12),
                f"Architecture anchor differs: {key} {local_field}",
            )


def _contains_forbidden_key(value: Any) -> bool:
    if isinstance(value, Mapping):
        for key, child in value.items():
            if str(key).lower() in FORBIDDEN_FIELDS or _contains_forbidden_key(child):
                return True
    elif isinstance(value, list):
        return any(_contains_forbidden_key(item) for item in value)
    return False


def _compute(*, root: Path, review_path: Path) -> tuple[dict[str, list[dict[str, Any]]], dict[str, Any], dict[str, Any]]:
    stage_a_dir = root / STAGE_A_DIR
    stage1_dir = root / STAGE1_DIR
    stage_a_audit = audit_stage_a_output(stage_a_dir)
    stage1_audit = audit_rq5_stage1_output(repo_root=root, stage_a_dir=stage_a_dir, output_dir=stage1_dir)
    rows = _read_jsonl(stage1_dir / "case-index.jsonl")
    _require(len(rows) == EXPECTED_POPULATION, "Evaluation population differs")
    _require(Counter(str(row["judge_label"]) for row in rows) == Counter(EXPECTED_LABEL_COUNTS), "Judge label counts differ")
    judges, judge_artifacts = _load_judges(root)
    gold = _load_gold(root)
    review = _read_json(review_path)
    screened = [row for row in rows if _screen(row) is not None]
    screen_counts = Counter(_screen(row) for row in screened)
    _require(screen_counts == Counter(EXPECTED_SCREEN_COUNTS), "Diagnostic screen counts differ")
    _require(len(screened) == EXPECTED_SCREENED_ROWS, "Diagnostic screen total differs")
    review_lookup = _validate_review(review, screened)
    disagreement = _disagreement_cases(
        rows=rows, judges=judges, review_lookup=review_lookup, gold=gold, root=root
    )
    sensitive_questions = {
        str(question_id)
        for family in review["families"] if family["evaluation_sensitive"]
        for assignment in (
            family.get("assignments")
            or [{"screen_id": screen, "question_ids": family["question_ids"]} for screen in family["screens"]]
        )
        for question_id in assignment["question_ids"]
    }
    tables = {
        "score-distributions": _score_distributions(rows, gold),
        "judge-f1-crosstab": _crosstab(rows),
        "disagreement-cases": disagreement,
        "cause-summary": _cause_summary(disagreement),
        "cause-by-category": _cause_by_category(disagreement),
        "exact-input-consistency": _exact_input_consistency(judges),
        "metric-sensitive-architecture": _architecture_sensitivity(rows, sensitive_questions),
    }
    _require(set(tables) == set(TABLES), "Evaluation table set differs")
    _validate_architecture_anchors(root, tables["metric-sensitive-architecture"])
    exact = tables["exact-input-consistency"][0]
    checks = {
        "population_900": len(rows) == 900,
        "labels_650_74_176": Counter(str(row["judge_label"]) for row in rows) == Counter(EXPECTED_LABEL_COUNTS),
        "screens_92_31_11_34": screen_counts == Counter(EXPECTED_SCREEN_COUNTS),
        "screened_rows_168": len(disagreement) == 168,
        "review_families_18": len(review["families"]) == EXPECTED_REVIEW_FAMILIES,
        "screened_rows_unique": len({row["analysis_row_id"] for row in disagreement}) == 168,
        "screened_rows_fully_reviewed": all(row["primary_cause"] and row["family_id"] for row in disagreement),
        "exact_duplicate_groups_80": exact["group_count"] == 80,
        "exact_duplicate_records_305": exact["record_count"] == 305,
        "exact_duplicate_label_conflicts_0": exact["conflict_group_count"] == 0,
        "architecture_comparisons_17": len(tables["metric-sensitive-architecture"]) == 17,
        "architecture_source_values_exact": True,
        "published_tables_text_free": not _contains_forbidden_key(tables),
    }
    _require(all(checks.values()), "Evaluation disagreement audit checks failed")
    correlations = {
        "token_f1_vs_strict": _pearson(
            [float(row["token_f1"]) for row in rows], [float(row["strict_score"]) for row in rows]
        ),
        "token_f1_vs_soft": _pearson(
            [float(row["token_f1"]) for row in rows], [float(row["soft_semantic_score"]) for row in rows]
        ),
    }
    provenance = {
        "stage_a_audit_id": stage_a_audit["audit_id"],
        "stage1_audit_id": stage1_audit["audit_id"],
        "review_sha256": _sha256_file(review_path),
        "judge_artifacts": judge_artifacts,
        "architecture_artifacts": [_artifact(root, root / path) for path in ARCHITECTURE_SOURCE_PATHS.values()],
    }
    diagnostics = {
        "checks": checks,
        "screen_counts": dict(sorted(screen_counts.items())),
        "sensitive_question_count": len(sensitive_questions),
        "sensitive_question_ids": sorted(sensitive_questions),
        "correlations": correlations,
        "row_counts": {name: len(members) for name, members in tables.items()},
    }
    return tables, diagnostics, provenance


def _readme() -> str:
    return """# RQ5 evaluation disagreement audit\n\nThis offline artifact supports Section 5.6.5. It freezes the full 900-answer score distribution, four transparent diagnostic tails, a manually reviewed cause code for every screened row, exact-input Judge consistency, and metric-direction checks for the principal architecture comparisons.\n\nThe diagnostic thresholds select cases for inspection; they are not definitions of evaluator error. Question, answer, evidence, prompt, and Judge-rationale text are intentionally excluded. Full Context has no retrieval Evidence Recall. No API or network call is made.\n"""


def _schema(tables: Mapping[str, Sequence[Mapping[str, Any]]]) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "protocol_version": PROTOCOL_VERSION,
        "tables": {
            name: {"row_count": len(rows), "fields": list(rows[0].keys()) if rows else []}
            for name, rows in tables.items()
        },
    }


def _source_manifest(*, root: Path, review_path: Path, provenance: Mapping[str, Any]) -> dict[str, Any]:
    body = {
        "protocol_version": PROTOCOL_VERSION,
        "stage_a": _artifact(root, root / STAGE_A_DIR / "audit.json"),
        "stage1": _artifact(root, root / STAGE1_DIR / "audit.json"),
        "review": _artifact(root, review_path),
        "judge_artifacts": provenance["judge_artifacts"],
        "architecture_artifacts": provenance["architecture_artifacts"],
    }
    return {"source_manifest_id": _artifact_id("rq5-eval-sources-", body), **body}


def _payloads(
    *, tables: Mapping[str, Sequence[Mapping[str, Any]]], diagnostics: Mapping[str, Any], manifest: Mapping[str, Any]
) -> dict[str, bytes]:
    payloads = {
        "README.md": _readme().encode("utf-8"),
        "schema.json": canonical_json_bytes(_schema(tables)) + b"\n",
        "diagnostics.json": canonical_json_bytes(dict(diagnostics)) + b"\n",
        "source-manifest.json": canonical_json_bytes(dict(manifest)) + b"\n",
    }
    for name, rows in tables.items():
        payloads[f"{name}.jsonl"] = _jsonl_payload(rows)
        payloads[f"{name}.csv"] = _csv_payload(rows)
    return payloads


def _audit_body(
    *, diagnostics: Mapping[str, Any], provenance: Mapping[str, Any], manifest: Mapping[str, Any],
    output_hashes: Mapping[str, str],
) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "protocol_version": PROTOCOL_VERSION,
        "status": "passed",
        "scope": "RQ5 Section 5.6.5 token-versus-semantic evaluation disagreement and metric sensitivity",
        "no_api_calls": True,
        "no_network_calls": True,
        "formal_source_mutation": False,
        "diagnostic_thresholds_are_not_error_definitions": True,
        "source_manifest_id": manifest["source_manifest_id"],
        "stage_a_audit_id": provenance["stage_a_audit_id"],
        "stage1_audit_id": provenance["stage1_audit_id"],
        "diagnostics": dict(diagnostics),
        "output_sha256": dict(output_hashes),
    }


def _marker(audit: Mapping[str, Any], audit_sha256: str) -> dict[str, Any]:
    return {
        "status": "passed",
        "protocol_version": PROTOCOL_VERSION,
        "audit_id": audit["audit_id"],
        "audit_sha256": audit_sha256,
        "population_rows": EXPECTED_POPULATION,
        "screened_rows": EXPECTED_SCREENED_ROWS,
        "exact_duplicate_label_conflicts": 0,
        "no_api_calls": True,
        "no_network_calls": True,
    }


def build_rq5_evaluation(*, repo_root: Path, review_path: Path, output_dir: Path) -> dict[str, Any]:
    root = repo_root.resolve()
    review = review_path.resolve()
    destination = output_dir.resolve()
    _require(not destination.exists() and not destination.is_symlink(), "Evaluation output already exists")
    tables, diagnostics, provenance = _compute(root=root, review_path=review)
    manifest = _source_manifest(root=root, review_path=review, provenance=provenance)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=f".{destination.name}.in-progress-", dir=destination.parent))
    try:
        payloads = _payloads(tables=tables, diagnostics=diagnostics, manifest=manifest)
        for name, payload in payloads.items():
            _write(temporary / name, payload)
        hashes = {name: _sha256_file(temporary / name) for name in sorted(payloads)}
        body = _audit_body(
            diagnostics=diagnostics, provenance=provenance, manifest=manifest, output_hashes=hashes
        )
        audit = {"audit_id": _artifact_id("rq5-eval-audit-", body), **body}
        _write(temporary / "audit.json", canonical_json_bytes(audit) + b"\n")
        _write(
            temporary / "RQ5-EVALUATION.PASSED",
            canonical_json_bytes(_marker(audit, _sha256_file(temporary / "audit.json"))) + b"\n",
        )
        result = audit_rq5_evaluation(repo_root=root, review_path=review, output_dir=temporary)
        _require(result["status"] == "passed", "Pre-publication evaluation audit failed")
        os.rename(temporary, destination)
        descriptor = os.open(destination.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
    except Exception:
        shutil.rmtree(temporary, ignore_errors=True)
        raise
    return audit_rq5_evaluation(repo_root=root, review_path=review, output_dir=destination)


def audit_rq5_evaluation(*, repo_root: Path, review_path: Path, output_dir: Path) -> dict[str, Any]:
    root = repo_root.resolve()
    review = review_path.resolve()
    output = output_dir.resolve()
    _require(output.is_dir() and not output.is_symlink(), "Evaluation output directory is unsafe")
    tables, diagnostics, provenance = _compute(root=root, review_path=review)
    manifest = _source_manifest(root=root, review_path=review, provenance=provenance)
    payloads = _payloads(tables=tables, diagnostics=diagnostics, manifest=manifest)
    hashes = {name: hashlib.sha256(payload).hexdigest() for name, payload in sorted(payloads.items())}
    body = _audit_body(
        diagnostics=diagnostics, provenance=provenance, manifest=manifest, output_hashes=hashes
    )
    expected_audit = {"audit_id": _artifact_id("rq5-eval-audit-", body), **body}
    audit_payload = canonical_json_bytes(expected_audit) + b"\n"
    marker_payload = canonical_json_bytes(_marker(expected_audit, hashlib.sha256(audit_payload).hexdigest())) + b"\n"
    expected_names = set(payloads) | {"audit.json", "RQ5-EVALUATION.PASSED"}
    entries = list(output.iterdir())
    _require(all(entry.is_file() and not entry.is_symlink() for entry in entries), "Evaluation output contains unsafe entry")
    _require({entry.name for entry in entries} == expected_names, "Evaluation output file set differs")
    for name, payload in payloads.items():
        _require((output / name).read_bytes() == payload, f"Evaluation artifact bytes differ: {name}")
    _require((output / "audit.json").read_bytes() == audit_payload, "Evaluation audit bytes differ")
    _require((output / "RQ5-EVALUATION.PASSED").read_bytes() == marker_payload, "Evaluation marker bytes differ")
    return {
        "status": "passed",
        "protocol_version": PROTOCOL_VERSION,
        "audit_id": expected_audit["audit_id"],
        "population_rows": EXPECTED_POPULATION,
        "screened_rows": EXPECTED_SCREENED_ROWS,
        "review_family_count": EXPECTED_REVIEW_FAMILIES,
        "exact_duplicate_label_conflicts": 0,
        "output_dir": str(output),
        "no_api_calls": True,
        "no_network_calls": True,
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build or audit Chapter 5 RQ5 evaluation-disagreement artifacts")
    parser.add_argument("command", choices=("build", "audit"))
    parser.add_argument("--repo-root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--review-path", type=Path)
    parser.add_argument("--output-dir", type=Path)
    return parser


def main(argv: list[str] | None = None) -> None:
    args = _parser().parse_args(argv)
    root = args.repo_root.resolve()
    review = (args.review_path or root / DEFAULT_REVIEW_PATH).resolve()
    output = (args.output_dir or root / DEFAULT_OUTPUT_DIR).resolve()
    kwargs = {"repo_root": root, "review_path": review, "output_dir": output}
    result = build_rq5_evaluation(**kwargs) if args.command == "build" else audit_rq5_evaluation(**kwargs)
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
