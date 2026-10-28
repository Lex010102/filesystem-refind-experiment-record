"""Build and audit the Chapter 5 RQ4 Full Context diagnostic artifact.

RQ4 compares the DeepSeek-family Full Context path with each DeepSeek
selective condition, E1--E7, on the same unified Main-60 questions.  The
analysis is paired by question and fully offline.  It reads only the frozen
Stage A master table and publishes complete condition comparisons,
question-level Strict quadrants, category results, judge-label transitions,
and publication-safe candidate identifiers for the later RQ5 review.

Full Context is a diagnostic access path, not E8, a memory representation, a
retrieval method, or an oracle.  Its complete source visibility is never
reported as Evidence Recall.  The selective and Full Context runs use the
same requested alias and model family but different served-model identifiers,
so this artifact is descriptive rather than a strict single-variable causal
ablation.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import shutil
import tempfile
from collections import Counter
from pathlib import Path
from typing import Any, Mapping, Sequence

from .chapter5_stage_a import audit_stage_a_output
from .chapter5_stage_b import (
    _csv_payload,
    _jsonl_payload,
    _read_json,
    _read_jsonl,
    _relative,
    _require,
    _sha256_file,
    _write,
)
from .evidence import canonical_json_bytes, sha256_bytes


STAGE_RQ4_PROTOCOL_VERSION = "chapter5-main60-rq4-v1"

SELECTIVE_CONDITIONS = ("E1", "E2", "E3", "E4", "E5", "E6", "E7")
PRINCIPAL_CONDITIONS = {"E1", "E5", "E7"}
FULL_CONTEXT_CONDITION = "B3-FullContext"
QUESTION_COUNT = 60
EVIDENCE_QUESTION_COUNT = 58
SOURCE_ROW_COUNT = 480
PAIRED_QUESTION_COUNT = 420
FLOAT_TOLERANCE = 1e-12

CATEGORIES = (
    (1, "multi-hop", 13, 13),
    (2, "temporal", 13, 13),
    (3, "open-domain", 7, 5),
    (4, "single-hop", 27, 27),
)
CATEGORY_ORDER = {category: order for order, (category, _, _, _) in enumerate(CATEGORIES, 1)}

SUMMARY_METRICS = (
    ("token_precision", "token_precision"),
    ("token_recall", "token_recall"),
    ("token_f1", "token_f1"),
    ("strict_accuracy", "strict_score"),
    ("partial_rate", "partial_indicator"),
    ("soft_semantic_score", "soft_semantic_score"),
)
ORDERED_QUALITY_METRICS = tuple(item for item in SUMMARY_METRICS if item[0] != "partial_rate")

STRICT_QUADRANTS = (
    "both_correct",
    "full_context_only",
    "selective_only",
    "neither_correct",
)
JUDGE_LABELS = ("incorrect", "partial", "correct")
JUDGE_ORDINAL = {label: order for order, label in enumerate(JUDGE_LABELS)}

EXPECTED_STAGE_A_AUDIT_ID = (
    "stage-a-audit-5f55ec411f097df7206fdae5e71742641aa8868b4128ac32262f034877a1d7f3"
)
EXPECTED_STAGE_A_SOURCE_MANIFEST_ID = (
    "stage-a-sources-90efa256f7981450cf38503912406a1e30766e8440b443899cab953fe9fece3c"
)
EXPECTED_FROZEN_SHA256 = {
    "stage_a_audit": "39aee6ea88c92df547cc98f7b6b343415a558d31a354184e30f0d36acc331966",
    "stage_a_marker": "f4b3aa6f80d2ee7bc4eb9682e37ec85780d4f37a15b22ef65eb78e46ee6f3e34",
    "stage_a_master": "8e54db42ae6eeb65fc4a47049af622fea4e7dc611b8028920486029885d65a01",
    "stage_a_schema": "21295503a3b8e0cadcde9a61a46be1e383c38da329dbc66d716b78faa72ede09",
    "stage_a_source_manifest": "2b1f56d0897904fb9d4b8487111ecc2d7b55848f54f97dbfe34de53c16b59a65",
}

FORBIDDEN_FIELDS = {
    "question",
    "question_text",
    "reference_answer",
    "candidate_answer",
    "answer",
    "answer_text",
    "gold_answer",
    "evidence",
    "evidence_text",
    "retrieved_text",
    "judge_reason",
    "short_reason",
    "prompt",
    "response",
    "api_key",
    "authorization",
}


def _artifact_id(prefix: str, body: Mapping[str, Any]) -> str:
    return prefix + sha256_bytes(canonical_json_bytes(dict(body)))


def _close(left: float, right: float) -> bool:
    return math.isclose(float(left), float(right), rel_tol=0.0, abs_tol=FLOAT_TOLERANCE)


def _mean(values: Sequence[float | int]) -> float:
    _require(bool(values), "RQ4 cannot average an empty sequence")
    numeric = [float(value) for value in values]
    _require(all(math.isfinite(value) for value in numeric), "RQ4 contains a non-finite value")
    return math.fsum(numeric) / len(numeric)


def _validate_frozen_input(*, repo_root: Path, stage_a_dir: Path) -> dict[str, Any]:
    root = repo_root.resolve()
    stage_a = stage_a_dir.resolve()
    expected = (root / "artifacts/chapter5-main60-analysis-v1/stage-a").resolve()
    _require(root.is_dir() and not root.is_symlink(), "Repository root is unsafe")
    _require(stage_a == expected, "Stage A is not the frozen repository artifact")
    _require(stage_a.is_dir() and not stage_a.is_symlink(), "Stage A directory is unsafe")

    frozen_files = {
        stage_a / "audit.json": EXPECTED_FROZEN_SHA256["stage_a_audit"],
        stage_a / "STAGE-A.PASSED": EXPECTED_FROZEN_SHA256["stage_a_marker"],
        stage_a / "master-table.jsonl": EXPECTED_FROZEN_SHA256["stage_a_master"],
        stage_a / "schema.json": EXPECTED_FROZEN_SHA256["stage_a_schema"],
        stage_a / "source-manifest.json": EXPECTED_FROZEN_SHA256["stage_a_source_manifest"],
    }
    for path, expected_sha256 in frozen_files.items():
        _require(path.is_file() and not path.is_symlink(), f"Unsafe or missing frozen input: {path}")
        _require(_sha256_file(path) == expected_sha256, f"Frozen input hash differs: {path.name}")

    audit = audit_stage_a_output(stage_a)
    _require(audit["audit_id"] == EXPECTED_STAGE_A_AUDIT_ID, "Stage A audit identity differs")
    source_manifest = _read_json(stage_a / "source-manifest.json")
    _require(
        source_manifest.get("source_manifest_id") == EXPECTED_STAGE_A_SOURCE_MANIFEST_ID,
        "Stage A source-manifest identity differs",
    )
    return {
        "stage_a_audit_id": audit["audit_id"],
        "stage_a_source_manifest_id": source_manifest["source_manifest_id"],
        "stage_a_audit_sha256": EXPECTED_FROZEN_SHA256["stage_a_audit"],
        "stage_a_master_sha256": EXPECTED_FROZEN_SHA256["stage_a_master"],
    }


def _strict_correct(row: Mapping[str, Any]) -> bool:
    score = float(row["strict_score"])
    _require(score in {0.0, 1.0}, "RQ4 Strict score is not binary")
    return score == 1.0


def _strict_quadrant(selective: Mapping[str, Any], full_context: Mapping[str, Any]) -> str:
    selective_correct = _strict_correct(selective)
    full_context_correct = _strict_correct(full_context)
    if selective_correct and full_context_correct:
        return "both_correct"
    if full_context_correct:
        return "full_context_only"
    if selective_correct:
        return "selective_only"
    return "neither_correct"


def _validate_score_fields(row: Mapping[str, Any]) -> None:
    for _, source in SUMMARY_METRICS:
        value = float(row[source])
        _require(math.isfinite(value) and 0.0 <= value <= 1.0, f"RQ4 invalid score: {source}")
    label = str(row["judge_label"])
    _require(label in JUDGE_LABELS, "RQ4 Judge label differs")
    expected_strict = 1.0 if label == "correct" else 0.0
    expected_partial = 1 if label == "partial" else 0
    expected_soft = 1.0 if label == "correct" else 0.5 if label == "partial" else 0.0
    _require(_close(float(row["strict_score"]), expected_strict), "RQ4 Strict/label mapping differs")
    _require(int(row["partial_indicator"]) == expected_partial, "RQ4 Partial/label mapping differs")
    _require(_close(float(row["soft_semantic_score"]), expected_soft), "RQ4 Soft/label mapping differs")


def _validate_source_rows(
    rows: Sequence[Mapping[str, Any]],
) -> list[tuple[dict[str, Any], dict[str, Any]]]:
    _require(len(rows) == 900, "RQ4 Stage A master row count differs")
    selective = [
        dict(row)
        for row in rows
        if row["answer_set_id"] == "model2-deepseek-main60"
        and row["condition_id"] in SELECTIVE_CONDITIONS
    ]
    full_context_rows = [
        dict(row)
        for row in rows
        if row["answer_set_id"] == "full-context-deepseek-family-main60"
        and row["condition_id"] == FULL_CONTEXT_CONDITION
    ]
    _require(len(selective) == 420, "RQ4 requires exactly 420 DeepSeek E1--E7 rows")
    _require(len(full_context_rows) == 60, "RQ4 requires exactly 60 Full Context rows")
    subset = selective + full_context_rows
    _require(all(FORBIDDEN_FIELDS.isdisjoint(row) for row in subset), "RQ4 source contains forbidden text")

    selective_index = {(str(row["condition_id"]), str(row["question_id"])): row for row in selective}
    full_context_index = {str(row["question_id"]): row for row in full_context_rows}
    _require(len(selective_index) == 420, "RQ4 selective source keys are not unique")
    _require(len(full_context_index) == 60, "RQ4 Full Context source keys are not unique")

    expected_questions = set(full_context_index)
    _require(len(expected_questions) == QUESTION_COUNT, "RQ4 Full Context question set differs")
    for condition in SELECTIVE_CONDITIONS:
        condition_rows = [row for row in selective if row["condition_id"] == condition]
        _require(len(condition_rows) == QUESTION_COUNT, f"RQ4 denominator differs: {condition}")
        _require({str(row["question_id"]) for row in condition_rows} == expected_questions, f"RQ4 questions differ: {condition}")
        _require(
            sorted(int(row["global_position"]) for row in condition_rows) == list(range(1, 61)),
            f"RQ4 positions differ: {condition}",
        )

    _require(
        sorted(int(row["global_position"]) for row in full_context_rows) == list(range(1, 61)),
        "RQ4 Full Context positions differ",
    )

    category_counts: Counter[tuple[str, int]] = Counter()
    evidence_counts: Counter[tuple[str, int]] = Counter()
    for row in selective:
        _validate_score_fields(row)
        _require(row["backbone_id"] == "deepseek", "RQ4 selective backbone differs")
        _require(
            (row["requested_model"], row["served_model"]) == ("x-test-2", "deepseek-v4.1-flash"),
            "RQ4 selective model identity differs",
        )
        _require(row["is_e1_e7_main"] is True, "RQ4 contains a non-main selective row")
        _require(row["access_regime"] in {"selective_retrieval", "dual_source_fusion"}, "RQ4 selective access regime differs")
        _require(row["evidence_recall"] is not None or row["evidence_eligible"] is False, "RQ4 selective Evidence Recall missing")
        _require(row["source_coverage_by_construction"] is None, "RQ4 selective source coverage is populated")
        category_counts[(str(row["condition_id"]), int(row["category"]))] += 1
        if bool(row["evidence_eligible"]):
            evidence_counts[(str(row["condition_id"]), int(row["category"]))] += 1

    for row in full_context_rows:
        _validate_score_fields(row)
        _require(row["backbone_id"] == "deepseek_family_full_context", "RQ4 Full Context backbone differs")
        _require(
            (row["requested_model"], row["served_model"]) == ("x-test-2", "deepseek-v4.1-flash-1017"),
            "RQ4 Full Context model identity differs",
        )
        _require(
            (row["storage_representation"], row["retrieval_system"], row["access_regime"])
            == ("complete_S1_raw_history", "none", "full_context"),
            "RQ4 Full Context design differs",
        )
        _require(int(row["evidence_item_count"]) == 30, "RQ4 Full Context session count differs")
        _require(int(row["evidence_bundle_characters"]) == 108960, "RQ4 Full Context character count differs")
        _require(row["evidence_budget_characters"] is None, "RQ4 Full Context has a selective budget")
        _require(row["evidence_recall"] is None, "RQ4 Full Context Evidence Recall must be null")
        _require(row["evidence_any_hit"] is None and row["evidence_all_hit"] is None, "RQ4 Full Context hit metrics must be null")
        _require(_close(float(row["source_coverage_by_construction"]), 1.0), "RQ4 source coverage differs")
        _require(row["retrieved_dia_ids"] == [], "RQ4 Full Context has retrieved source IDs")
        _require(row["source_bundle_ids"] == [], "RQ4 Full Context has selective parent bundles")
        _require(int(row["search_action_count"]) == 0, "RQ4 Full Context performed a search action")
        _require(int(row["retrieval_model_calls"]) == 0, "RQ4 Full Context performed a retrieval call")
        _require(int(row["retrieval_total_tokens"]) == 0, "RQ4 Full Context used retrieval tokens")
        _require(int(row["answer_model_calls"]) == 1 and int(row["query_model_calls"]) == 1, "RQ4 Full Context call count differs")
        _require(int(row["answer_total_tokens"]) == int(row["query_total_tokens"]), "RQ4 Full Context token accounting differs")
        category_counts[(FULL_CONTEXT_CONDITION, int(row["category"]))] += 1
        if bool(row["evidence_eligible"]):
            evidence_counts[(FULL_CONTEXT_CONDITION, int(row["category"]))] += 1

    _require(
        all(
            (row["judge_requested_model"], row["judge_served_model"]) == ("x-test-1", "glm-5.3-flash")
            for row in subset
        ),
        "RQ4 Judge identity differs",
    )

    for condition in (*SELECTIVE_CONDITIONS, FULL_CONTEXT_CONDITION):
        for category, name, answer_n, evidence_n in CATEGORIES:
            _require(category_counts[(condition, category)] == answer_n, f"RQ4 category denominator differs: {condition}/{name}")
            _require(evidence_counts[(condition, category)] == evidence_n, f"RQ4 eligibility mask differs: {condition}/{name}")

    identity_fields = (
        "question_id",
        "question_sha256",
        "global_position",
        "category",
        "category_name",
        "evidence_eligible",
        "gold_dia_ids",
    )
    pairs: list[tuple[dict[str, Any], dict[str, Any]]] = []
    for condition in SELECTIVE_CONDITIONS:
        ordered = sorted(
            (row for row in selective if row["condition_id"] == condition),
            key=lambda row: int(row["global_position"]),
        )
        for selective_row in ordered:
            full_context = full_context_index[str(selective_row["question_id"])]
            _require(
                tuple(selective_row[field] for field in identity_fields)
                == tuple(full_context[field] for field in identity_fields),
                f"RQ4 paired identity differs: {condition}/{selective_row['question_id']}",
            )
            pairs.append((selective_row, full_context))
    _require(len(pairs) == PAIRED_QUESTION_COUNT, "RQ4 paired-question count differs")
    return pairs


def _question_quadrants(
    pairs: Sequence[tuple[Mapping[str, Any], Mapping[str, Any]]],
) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for selective, full_context in pairs:
        condition = str(selective["condition_id"])
        quadrant = _strict_quadrant(selective, full_context)
        body: dict[str, Any] = {
            "protocol_version": STAGE_RQ4_PROTOCOL_VERSION,
            "comparison_order": SELECTIVE_CONDITIONS.index(condition) + 1,
            "comparison_id": f"full_context_minus_{condition.lower()}",
            "selective_condition": condition,
            "principal_comparison": condition in PRINCIPAL_CONDITIONS,
            "global_position": int(selective["global_position"]),
            "question_id": selective["question_id"],
            "question_sha256": selective["question_sha256"],
            "category_order": CATEGORY_ORDER[int(selective["category"])],
            "category": int(selective["category"]),
            "category_name": selective["category_name"],
            "evidence_eligible": bool(selective["evidence_eligible"]),
            "strict_quadrant_order": STRICT_QUADRANTS.index(quadrant) + 1,
            "strict_quadrant": quadrant,
            "rq5_review_candidate": quadrant in {"full_context_only", "selective_only"},
            "rq5_candidate_type": (
                "complete_visibility_repair"
                if quadrant == "full_context_only"
                else "selective_focus_success"
                if quadrant == "selective_only"
                else "not_prioritised"
            ),
            "selective_judge_label": selective["judge_label"],
            "full_context_judge_label": full_context["judge_label"],
        }
        for published, source in SUMMARY_METRICS:
            selective_value = float(selective[source])
            full_context_value = float(full_context[source])
            body[f"selective_{published}"] = selective_value
            body[f"full_context_{published}"] = full_context_value
            body[f"delta_{published}"] = full_context_value - selective_value
        body.update(
            {
                "selective_answer_normalized_tokens": int(selective["answer_normalized_tokens"]),
                "full_context_answer_normalized_tokens": int(full_context["answer_normalized_tokens"]),
                "delta_answer_normalized_tokens": int(full_context["answer_normalized_tokens"])
                - int(selective["answer_normalized_tokens"]),
                "selective_evidence_bundle_characters": int(selective["evidence_bundle_characters"]),
                "full_context_characters": int(full_context["evidence_bundle_characters"]),
                "selective_answer_prompt_tokens": int(selective["answer_prompt_tokens"]),
                "full_context_answer_prompt_tokens": int(full_context["answer_prompt_tokens"]),
                "selective_answer_total_tokens": int(selective["answer_total_tokens"]),
                "full_context_answer_total_tokens": int(full_context["answer_total_tokens"]),
                "selective_query_total_tokens": int(selective["query_total_tokens"]),
                "full_context_query_total_tokens": int(full_context["query_total_tokens"]),
                "selective_evidence_recall": selective["evidence_recall"],
                "full_context_evidence_recall": None,
                "full_context_source_coverage_by_construction": 1.0,
            }
        )
        output.append({"result_id": _artifact_id("rq4-question-", body), **body})
    return output


def _condition_summary_row(
    condition: str,
    rows: Sequence[Mapping[str, Any]],
    *,
    full_context: bool,
) -> dict[str, Any]:
    _require(len(rows) == QUESTION_COUNT, f"RQ4 condition summary denominator differs: {condition}")
    body: dict[str, Any] = {
        "protocol_version": STAGE_RQ4_PROTOCOL_VERSION,
        "condition_order": 1 if full_context else SELECTIVE_CONDITIONS.index(condition) + 2,
        "condition_id": condition,
        "access_regime": "full_context" if full_context else "selective_or_fused",
        "answer_denominator": QUESTION_COUNT,
        "evidence_recall_applicable": not full_context,
        "evidence_denominator": 0 if full_context else EVIDENCE_QUESTION_COUNT,
        "mean_evidence_recall": (
            None
            if full_context
            else _mean([float(row["selective_evidence_recall"]) for row in rows if row["evidence_eligible"]])
        ),
        "source_coverage_by_construction": 1.0 if full_context else None,
    }
    prefix = "full_context" if full_context else "selective"
    for published, _ in SUMMARY_METRICS:
        body[published] = _mean([float(row[f"{prefix}_{published}"]) for row in rows])
    if full_context:
        body.update(
            {
                "mean_evidence_or_context_characters": _mean([row["full_context_characters"] for row in rows]),
                "mean_answer_normalized_tokens": _mean([row["full_context_answer_normalized_tokens"] for row in rows]),
                "mean_answer_prompt_tokens": _mean([row["full_context_answer_prompt_tokens"] for row in rows]),
                "mean_answer_total_tokens": _mean([row["full_context_answer_total_tokens"] for row in rows]),
                "mean_query_total_tokens": _mean([row["full_context_query_total_tokens"] for row in rows]),
                "requested_model": "x-test-2",
                "served_model": "deepseek-v4.1-flash-1017",
            }
        )
    else:
        body.update(
            {
                "mean_evidence_or_context_characters": _mean([row["selective_evidence_bundle_characters"] for row in rows]),
                "mean_answer_normalized_tokens": _mean([row["selective_answer_normalized_tokens"] for row in rows]),
                "mean_answer_prompt_tokens": _mean([row["selective_answer_prompt_tokens"] for row in rows]),
                "mean_answer_total_tokens": _mean([row["selective_answer_total_tokens"] for row in rows]),
                "mean_query_total_tokens": _mean([row["selective_query_total_tokens"] for row in rows]),
                "requested_model": "x-test-2",
                "served_model": "deepseek-v4.1-flash",
            }
        )
    return {"result_id": _artifact_id("rq4-condition-summary-", body), **body}


def _condition_summaries(diagnostics: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    first_condition_rows = [row for row in diagnostics if row["selective_condition"] == "E1"]
    output.append(_condition_summary_row(FULL_CONTEXT_CONDITION, first_condition_rows, full_context=True))
    for condition in SELECTIVE_CONDITIONS:
        rows = [row for row in diagnostics if row["selective_condition"] == condition]
        output.append(_condition_summary_row(condition, rows, full_context=False))
    return output


def _win_tie_loss(values: Sequence[float]) -> tuple[int, int, int]:
    wins = sum(value > FLOAT_TOLERANCE for value in values)
    losses = sum(value < -FLOAT_TOLERANCE for value in values)
    ties = len(values) - wins - losses
    return wins, ties, losses


def _condition_comparisons(diagnostics: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for condition in SELECTIVE_CONDITIONS:
        rows = [row for row in diagnostics if row["selective_condition"] == condition]
        _require(len(rows) == QUESTION_COUNT, f"RQ4 comparison denominator differs: {condition}")
        body: dict[str, Any] = {
            "protocol_version": STAGE_RQ4_PROTOCOL_VERSION,
            "comparison_order": SELECTIVE_CONDITIONS.index(condition) + 1,
            "comparison_id": f"full_context_minus_{condition.lower()}",
            "selective_condition": condition,
            "full_context_condition": FULL_CONTEXT_CONDITION,
            "difference_direction": "full_context_minus_selective",
            "principal_comparison": condition in PRINCIPAL_CONDITIONS,
            "answer_denominator": QUESTION_COUNT,
            "full_context_evidence_recall_applicable": False,
            "selective_evidence_denominator": EVIDENCE_QUESTION_COUNT,
            "selective_evidence_recall": _mean(
                [float(row["selective_evidence_recall"]) for row in rows if row["evidence_eligible"]]
            ),
            "full_context_evidence_recall": None,
            "delta_evidence_recall": None,
        }
        for published, _ in SUMMARY_METRICS:
            selective_mean = _mean([row[f"selective_{published}"] for row in rows])
            full_context_mean = _mean([row[f"full_context_{published}"] for row in rows])
            paired_delta = _mean([row[f"delta_{published}"] for row in rows])
            _require(_close(paired_delta, full_context_mean - selective_mean), f"RQ4 paired algebra differs: {condition}/{published}")
            body[f"selective_{published}"] = selective_mean
            body[f"full_context_{published}"] = full_context_mean
            body[f"delta_{published}"] = paired_delta
        for published, _ in ORDERED_QUALITY_METRICS:
            wins, ties, losses = _win_tie_loss([float(row[f"delta_{published}"]) for row in rows])
            body[f"{published}_full_context_wins"] = wins
            body[f"{published}_ties"] = ties
            body[f"{published}_full_context_losses"] = losses
        quadrants = Counter(str(row["strict_quadrant"]) for row in rows)
        for quadrant in STRICT_QUADRANTS:
            body[f"strict_{quadrant}_count"] = quadrants[quadrant]
        body.update(
            {
                "selective_mean_evidence_bundle_characters": _mean([row["selective_evidence_bundle_characters"] for row in rows]),
                "full_context_mean_characters": _mean([row["full_context_characters"] for row in rows]),
                "selective_mean_answer_normalized_tokens": _mean([row["selective_answer_normalized_tokens"] for row in rows]),
                "full_context_mean_answer_normalized_tokens": _mean([row["full_context_answer_normalized_tokens"] for row in rows]),
                "delta_answer_normalized_tokens": _mean([row["delta_answer_normalized_tokens"] for row in rows]),
                "same_model_family": True,
                "exact_served_model_match": False,
                "descriptive_diagnostic_comparison": True,
            }
        )
        output.append({"result_id": _artifact_id("rq4-condition-comparison-", body), **body})
    return output


def _quadrant_summary(diagnostics: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for condition in SELECTIVE_CONDITIONS:
        rows = [row for row in diagnostics if row["selective_condition"] == condition]
        counts = Counter(str(row["strict_quadrant"]) for row in rows)
        _require(sum(counts.values()) == QUESTION_COUNT, f"RQ4 quadrants do not partition Main-60: {condition}")
        for quadrant in STRICT_QUADRANTS:
            body = {
                "protocol_version": STAGE_RQ4_PROTOCOL_VERSION,
                "comparison_order": SELECTIVE_CONDITIONS.index(condition) + 1,
                "comparison_id": f"full_context_minus_{condition.lower()}",
                "selective_condition": condition,
                "principal_comparison": condition in PRINCIPAL_CONDITIONS,
                "quadrant_order": STRICT_QUADRANTS.index(quadrant) + 1,
                "strict_quadrant": quadrant,
                "denominator": QUESTION_COUNT,
                "count": counts[quadrant],
                "proportion": counts[quadrant] / QUESTION_COUNT,
            }
            output.append({"result_id": _artifact_id("rq4-quadrant-summary-", body), **body})
    return output


def _category_comparisons(diagnostics: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for condition in SELECTIVE_CONDITIONS:
        for category, name, answer_n, _ in CATEGORIES:
            rows = [
                row
                for row in diagnostics
                if row["selective_condition"] == condition and int(row["category"]) == category
            ]
            _require(len(rows) == answer_n, f"RQ4 category comparison denominator differs: {condition}/{name}")
            body: dict[str, Any] = {
                "protocol_version": STAGE_RQ4_PROTOCOL_VERSION,
                "comparison_order": SELECTIVE_CONDITIONS.index(condition) + 1,
                "comparison_id": f"full_context_minus_{condition.lower()}",
                "selective_condition": condition,
                "principal_comparison": condition in PRINCIPAL_CONDITIONS,
                "category_order": CATEGORY_ORDER[category],
                "category": category,
                "category_name": name,
                "answer_denominator": answer_n,
                "exploratory_category_analysis": True,
            }
            for published, _ in SUMMARY_METRICS:
                selective_mean = _mean([row[f"selective_{published}"] for row in rows])
                full_context_mean = _mean([row[f"full_context_{published}"] for row in rows])
                delta = _mean([row[f"delta_{published}"] for row in rows])
                _require(_close(delta, full_context_mean - selective_mean), "RQ4 category paired algebra differs")
                body[f"selective_{published}"] = selective_mean
                body[f"full_context_{published}"] = full_context_mean
                body[f"delta_{published}"] = delta
            quadrants = Counter(str(row["strict_quadrant"]) for row in rows)
            for quadrant in STRICT_QUADRANTS:
                body[f"strict_{quadrant}_count"] = quadrants[quadrant]
            output.append({"result_id": _artifact_id("rq4-category-comparison-", body), **body})
    return output


def _judge_transitions(diagnostics: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for condition in SELECTIVE_CONDITIONS:
        rows = [row for row in diagnostics if row["selective_condition"] == condition]
        counts = Counter((str(row["selective_judge_label"]), str(row["full_context_judge_label"])) for row in rows)
        _require(sum(counts.values()) == QUESTION_COUNT, f"RQ4 Judge transitions differ: {condition}")
        for selective_label in JUDGE_LABELS:
            for full_context_label in JUDGE_LABELS:
                count = counts[(selective_label, full_context_label)]
                direction = (
                    "improved"
                    if JUDGE_ORDINAL[full_context_label] > JUDGE_ORDINAL[selective_label]
                    else "worsened"
                    if JUDGE_ORDINAL[full_context_label] < JUDGE_ORDINAL[selective_label]
                    else "unchanged"
                )
                body = {
                    "protocol_version": STAGE_RQ4_PROTOCOL_VERSION,
                    "comparison_order": SELECTIVE_CONDITIONS.index(condition) + 1,
                    "comparison_id": f"full_context_minus_{condition.lower()}",
                    "selective_condition": condition,
                    "selective_label_order": JUDGE_LABELS.index(selective_label) + 1,
                    "selective_label": selective_label,
                    "full_context_label_order": JUDGE_LABELS.index(full_context_label) + 1,
                    "full_context_label": full_context_label,
                    "transition_direction": direction,
                    "denominator": QUESTION_COUNT,
                    "count": count,
                    "proportion": count / QUESTION_COUNT,
                }
                output.append({"result_id": _artifact_id("rq4-judge-transition-", body), **body})
    return output


def _table_rows(comparisons: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    fields = (
        "protocol_version",
        "comparison_order",
        "comparison_id",
        "selective_condition",
        "principal_comparison",
        "answer_denominator",
        "selective_token_precision",
        "full_context_token_precision",
        "delta_token_precision",
        "selective_token_recall",
        "full_context_token_recall",
        "delta_token_recall",
        "selective_token_f1",
        "full_context_token_f1",
        "delta_token_f1",
        "selective_strict_accuracy",
        "full_context_strict_accuracy",
        "delta_strict_accuracy",
        "selective_partial_rate",
        "full_context_partial_rate",
        "delta_partial_rate",
        "selective_soft_semantic_score",
        "full_context_soft_semantic_score",
        "delta_soft_semantic_score",
        "strict_both_correct_count",
        "strict_full_context_only_count",
        "strict_selective_only_count",
        "strict_neither_correct_count",
        "same_model_family",
        "exact_served_model_match",
        "descriptive_diagnostic_comparison",
    )
    return [{field: row[field] for field in fields} for row in comparisons]


def _figure_rows(quadrants: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    fields = (
        "protocol_version",
        "comparison_order",
        "comparison_id",
        "selective_condition",
        "principal_comparison",
        "quadrant_order",
        "strict_quadrant",
        "denominator",
        "count",
        "proportion",
    )
    return [{field: row[field] for field in fields} for row in quadrants]


def _review_candidates(diagnostics: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    fields = (
        "protocol_version",
        "comparison_order",
        "comparison_id",
        "selective_condition",
        "principal_comparison",
        "global_position",
        "question_id",
        "question_sha256",
        "category_order",
        "category",
        "category_name",
        "evidence_eligible",
        "strict_quadrant",
        "rq5_candidate_type",
        "selective_judge_label",
        "full_context_judge_label",
        "selective_token_f1",
        "full_context_token_f1",
        "delta_token_f1",
        "selective_soft_semantic_score",
        "full_context_soft_semantic_score",
        "delta_soft_semantic_score",
        "selective_evidence_recall",
        "selective_evidence_bundle_characters",
        "full_context_characters",
    )
    selected = [row for row in diagnostics if row["rq5_review_candidate"]]
    selected.sort(key=lambda row: (int(row["comparison_order"]), int(row["global_position"])))
    output: list[dict[str, Any]] = []
    for row in selected:
        body = {field: row[field] for field in fields}
        body["review_status"] = "deferred_to_rq5"
        body["causal_attribution"] = "not_computed"
        output.append({"result_id": _artifact_id("rq4-rq5-candidate-", body), **body})
    return output


def _compute_rq4(
    *, repo_root: Path, stage_a_dir: Path,
) -> tuple[dict[str, list[dict[str, Any]]], dict[str, Any], dict[str, Any]]:
    provenance = _validate_frozen_input(repo_root=repo_root, stage_a_dir=stage_a_dir)
    source_rows = _read_jsonl(stage_a_dir / "master-table.jsonl")
    pairs = _validate_source_rows(source_rows)
    diagnostics = _question_quadrants(pairs)
    summaries = _condition_summaries(diagnostics)
    comparisons = _condition_comparisons(diagnostics)
    quadrants = _quadrant_summary(diagnostics)
    categories = _category_comparisons(diagnostics)
    transitions = _judge_transitions(diagnostics)
    candidates = _review_candidates(diagnostics)
    tables = {
        "condition-summaries": summaries,
        "condition-comparisons": comparisons,
        "question-quadrants": diagnostics,
        "quadrant-summary": quadrants,
        "category-comparisons": categories,
        "judge-transitions": transitions,
        "table-5-15-inputs": _table_rows(comparisons),
        "figure-5-8-inputs": _figure_rows(quadrants),
        "rq5-candidate-cases": candidates,
    }
    counts = {name: len(rows) for name, rows in tables.items()}
    expected_counts = {
        "condition-summaries": 8,
        "condition-comparisons": 7,
        "question-quadrants": 420,
        "quadrant-summary": 28,
        "category-comparisons": 28,
        "judge-transitions": 63,
        "table-5-15-inputs": 7,
        "figure-5-8-inputs": 28,
        "rq5-candidate-cases": 55,
    }
    checks = {
        "stage_a_rows_900": len(source_rows) == 900,
        "rq4_source_rows_480": len(
            {str(selective["analysis_row_id"]) for selective, _ in pairs}
            | {str(full_context["analysis_row_id"]) for _, full_context in pairs}
        )
        == SOURCE_ROW_COUNT,
        "paired_questions_420": len(pairs) == PAIRED_QUESTION_COUNT,
        "table_row_counts_exact": counts == expected_counts,
        "outputs_text_free": all(
            FORBIDDEN_FIELDS.isdisjoint(row)
            for table in tables.values()
            for row in table
        ),
        "no_qwen_rows": all(
            "qwen" not in str(value).lower()
            for table in tables.values()
            for row in table
            for value in row.values()
        ),
        "full_context_evidence_recall_null": all(
            row["full_context_evidence_recall"] is None for row in diagnostics
        ),
        "quadrants_partition_each_comparison": all(
            sum(int(row["count"]) for row in quadrants if row["selective_condition"] == condition)
            == QUESTION_COUNT
            for condition in SELECTIVE_CONDITIONS
        ),
        "category_quadrants_partition": all(
            sum(
                int(row[f"strict_{quadrant}_count"])
                for quadrant in STRICT_QUADRANTS
            )
            == answer_n
            for row in categories
            for category, _, answer_n, _ in CATEGORIES
            if int(row["category"]) == category
        ),
        "judge_transition_matrices_sum_60": all(
            sum(int(row["count"]) for row in transitions if row["selective_condition"] == condition)
            == QUESTION_COUNT
            for condition in SELECTIVE_CONDITIONS
        ),
        "model_identity_boundary_explicit": all(
            row["same_model_family"] is True and row["exact_served_model_match"] is False
            for row in comparisons
        ),
    }
    _require(all(checks.values()), "RQ4 table audit failed")
    return tables, provenance, {"checks": checks, "row_counts": counts}


def _value_type(value: Any) -> str:
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, float):
        return "number"
    if value is None:
        return "null"
    return "string"


def _field_schema(tables: Mapping[str, Sequence[Mapping[str, Any]]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for name, rows in tables.items():
        _require(bool(rows), f"RQ4 table is empty: {name}")
        fields = list(rows[0])
        _require(all(list(row) == fields for row in rows), f"RQ4 table schema differs: {name}")
        result[name] = {
            "row_count": len(rows),
            "fields": [
                {"name": field, "types": sorted({_value_type(row[field]) for row in rows})}
                for field in fields
            ],
        }
    return {
        "schema_version": 1,
        "protocol_version": STAGE_RQ4_PROTOCOL_VERSION,
        "tables": result,
        "comparison_direction": "Full Context minus selective condition",
        "answer_denominator": QUESTION_COUNT,
        "full_context_evidence_recall": "not applicable",
        "strict_quadrant_basis": "Strict Accuracy only",
        "inference_scope": "descriptive paired diagnostic; no bootstrap or significance test",
    }


def _readme() -> str:
    return """# Chapter 5 RQ4: Full Context versus selective retrieval

This directory is the audited, offline input for Section 5.5. It compares the
DeepSeek-family Full Context path with DeepSeek E1--E7 on the same unified
Main-60 questions. The comparison direction is Full Context minus the named
selective condition. E1, E5, and E7 are the principal main-text comparisons;
all seven conditions are retained to avoid selective reporting.

`condition-comparisons` contains the complete paired quality table and
win/tie/loss counts. `question-quadrants` assigns every condition-question
pair to both correct, Full Context only, selective only, or neither correct,
using Strict Accuracy. `quadrant-summary` and `figure-5-8-inputs` aggregate
those states. `category-comparisons` reports the same descriptive analysis for
the four unified question categories. `judge-transitions` preserves movement
among incorrect, partial, and correct labels. `rq5-candidate-cases` contains
identifier-only asymmetric cases; it does not assign a causal failure stage.

Full Context receives all 30 ordered raw sessions and performs no explicit
retrieval. Its source coverage is 100% by construction, but Evidence Recall,
Any-hit, and All-hit are not applicable and remain null. Full Context is not
E8, a memory representation, a retrieval method, or an oracle.

The selective run used served model `deepseek-v4.1-flash`; Full Context used
`deepseek-v4.1-flash-1017`. They share the requested alias and model family but
not the exact served-model identifier. Results are therefore a strong
descriptive diagnostic, not a strict single-variable causal ablation.

This artifact contains no question, answer, evidence, rationale, prompt, or
secret text. It made no API or network call, reran no model, and computed no
bootstrap interval or significance test. Manual failure attribution belongs
to RQ5, and full quality--cost ranking belongs to RQ6.
"""


def _source_manifest(
    *, repo_root: Path, stage_a_dir: Path, provenance: Mapping[str, Any],
) -> dict[str, Any]:
    body = {
        "schema_version": 1,
        "protocol_version": STAGE_RQ4_PROTOCOL_VERSION,
        "scope": "paired Full Context versus DeepSeek selective-retrieval diagnostic on unified Main-60",
        "stage_a_directory": _relative(repo_root, stage_a_dir),
        **dict(provenance),
        "stage_a_row_count": 900,
        "source_row_count": SOURCE_ROW_COUNT,
        "paired_question_pairs": PAIRED_QUESTION_COUNT,
        "question_denominator": QUESTION_COUNT,
        "conditions": list(SELECTIVE_CONDITIONS),
        "full_context_condition": FULL_CONTEXT_CONDITION,
        "principal_conditions": sorted(PRINCIPAL_CONDITIONS, key=SELECTIVE_CONDITIONS.index),
        "comparison_direction": "Full Context minus selective condition",
        "selective_model_identity": {
            "answer_set_id": "model2-deepseek-main60",
            "requested_model": "x-test-2",
            "served_model": "deepseek-v4.1-flash",
        },
        "full_context_model_identity": {
            "answer_set_id": "full-context-deepseek-family-main60",
            "requested_model": "x-test-2",
            "served_model": "deepseek-v4.1-flash-1017",
        },
        "judge_identity": {"requested_model": "x-test-1", "served_model": "glm-5.3-flash"},
        "full_context_contract": {
            "raw_sessions": 30,
            "context_characters": 108960,
            "question_dependent_retrieval": False,
            "selective_evidence_budget": None,
            "retrieval_model_calls": 0,
            "source_coverage_by_construction": 1.0,
            "evidence_recall_applicable": False,
        },
        "strict_quadrant_definitions": {
            "both_correct": "Full Context and selective condition are Strict-correct",
            "full_context_only": "only Full Context is Strict-correct",
            "selective_only": "only the selective condition is Strict-correct",
            "neither_correct": "neither condition is Strict-correct",
        },
        "same_model_family": True,
        "exact_served_model_match": False,
        "strict_single_variable_ablation": False,
        "descriptive_diagnostic_comparison": True,
        "full_context_is_e8": False,
        "full_context_is_oracle": False,
        "source_partition_used_as_analytical_subgroup": False,
        "no_api_calls": True,
        "no_network_calls": True,
        "formal_source_mutation": False,
        "new_bootstrap_computed": False,
        "statistical_inference_computed": False,
        "cost_ranking_computed": False,
        "causal_stage_attribution_computed": False,
    }
    return {"source_manifest_id": "rq4-sources-" + sha256_bytes(canonical_json_bytes(body)), **body}


def _artifact_payloads(
    tables: Mapping[str, Sequence[Mapping[str, Any]]], source_manifest: Mapping[str, Any],
) -> dict[str, bytes]:
    payloads = {
        "README.md": _readme().encode("utf-8"),
        "schema.json": canonical_json_bytes(_field_schema(tables)) + b"\n",
        "source-manifest.json": canonical_json_bytes(dict(source_manifest)) + b"\n",
    }
    for name, rows in tables.items():
        payloads[f"{name}.jsonl"] = _jsonl_payload(rows)
        payloads[f"{name}.csv"] = _csv_payload(rows)
    return payloads


def _audit_body(
    *, source_manifest: Mapping[str, Any], provenance: Mapping[str, Any],
    table_audit: Mapping[str, Any], output_hashes: Mapping[str, str],
) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "protocol_version": STAGE_RQ4_PROTOCOL_VERSION,
        "status": "passed",
        "scope": "paired Full Context versus DeepSeek selective-retrieval diagnostic",
        "no_api_calls": True,
        "no_network_calls": True,
        "formal_source_mutation": False,
        "new_bootstrap_computed": False,
        "statistical_inference_computed": False,
        "cost_ranking_computed": False,
        "causal_stage_attribution_computed": False,
        "full_context_evidence_recall_applicable": False,
        "same_model_family": True,
        "exact_served_model_match": False,
        "strict_single_variable_ablation": False,
        "source_manifest_id": source_manifest["source_manifest_id"],
        **dict(provenance),
        "table_audit": dict(table_audit),
        "output_sha256": dict(output_hashes),
    }


def _marker(audit: Mapping[str, Any], audit_sha256: str) -> dict[str, Any]:
    counts = audit["table_audit"]["row_counts"]
    return {
        "status": "passed",
        "protocol_version": STAGE_RQ4_PROTOCOL_VERSION,
        "audit_id": audit["audit_id"],
        "audit_sha256": audit_sha256,
        "source_rows": SOURCE_ROW_COUNT,
        "paired_question_pairs": PAIRED_QUESTION_COUNT,
        "question_denominator": QUESTION_COUNT,
        "condition_comparison_rows": counts["condition-comparisons"],
        "question_quadrant_rows": counts["question-quadrants"],
        "category_comparison_rows": counts["category-comparisons"],
        "rq5_candidate_rows": counts["rq5-candidate-cases"],
        "full_context_evidence_recall_applicable": False,
        "no_api_calls": True,
        "no_network_calls": True,
    }


def build_rq4(
    *, repo_root: Path, stage_a_dir: Path, output_dir: Path,
) -> dict[str, Any]:
    root = repo_root.resolve()
    source = stage_a_dir.resolve()
    destination = output_dir.resolve()
    _require(not destination.exists() and not destination.is_symlink(), "RQ4 output already exists")
    try:
        destination.relative_to(source)
    except ValueError:
        pass
    else:
        _require(False, "RQ4 output may not be published inside frozen Stage A")

    tables, provenance, table_audit = _compute_rq4(repo_root=root, stage_a_dir=source)
    manifest = _source_manifest(repo_root=root, stage_a_dir=source, provenance=provenance)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=f".{destination.name}.in-progress-", dir=destination.parent))
    try:
        payloads = _artifact_payloads(tables, manifest)
        for name, payload in payloads.items():
            _write(temporary / name, payload)
        hashes = {name: _sha256_file(temporary / name) for name in sorted(payloads)}
        body = _audit_body(
            source_manifest=manifest,
            provenance=provenance,
            table_audit=table_audit,
            output_hashes=hashes,
        )
        audit = {"audit_id": "rq4-audit-" + sha256_bytes(canonical_json_bytes(body)), **body}
        _write(temporary / "audit.json", canonical_json_bytes(audit) + b"\n")
        _write(
            temporary / "RQ4.PASSED",
            canonical_json_bytes(_marker(audit, _sha256_file(temporary / "audit.json"))) + b"\n",
        )
        result = audit_rq4_output(repo_root=root, stage_a_dir=source, output_dir=temporary)
        _require(result["status"] == "passed", "RQ4 pre-publication audit failed")
        _require(not destination.exists(), "RQ4 output appeared during build")
        os.rename(temporary, destination)
        descriptor = os.open(destination.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
    except Exception:
        shutil.rmtree(temporary, ignore_errors=True)
        raise
    return audit_rq4_output(repo_root=root, stage_a_dir=source, output_dir=destination)


def audit_rq4_output(
    *, repo_root: Path, stage_a_dir: Path, output_dir: Path,
) -> dict[str, Any]:
    root = repo_root.resolve()
    source = stage_a_dir.resolve()
    output = output_dir.resolve()
    _require(output.is_dir() and not output.is_symlink(), "RQ4 output directory is unsafe")
    tables, provenance, table_audit = _compute_rq4(repo_root=root, stage_a_dir=source)
    manifest = _source_manifest(repo_root=root, stage_a_dir=source, provenance=provenance)
    payloads = _artifact_payloads(tables, manifest)
    hashes = {name: hashlib.sha256(payload).hexdigest() for name, payload in sorted(payloads.items())}
    body = _audit_body(
        source_manifest=manifest,
        provenance=provenance,
        table_audit=table_audit,
        output_hashes=hashes,
    )
    expected_audit = {"audit_id": "rq4-audit-" + sha256_bytes(canonical_json_bytes(body)), **body}
    audit_payload = canonical_json_bytes(expected_audit) + b"\n"
    marker_payload = canonical_json_bytes(
        _marker(expected_audit, hashlib.sha256(audit_payload).hexdigest())
    ) + b"\n"

    expected_names = set(payloads) | {"audit.json", "RQ4.PASSED"}
    entries = list(output.iterdir())
    _require(all(entry.is_file() and not entry.is_symlink() for entry in entries), "RQ4 output contains unsafe entry")
    _require({entry.name for entry in entries} == expected_names, "RQ4 output file set differs")
    for name, payload in payloads.items():
        _require((output / name).read_bytes() == payload, f"RQ4 artifact bytes differ: {name}")
    _require((output / "audit.json").read_bytes() == audit_payload, "RQ4 audit bytes differ")
    _require((output / "RQ4.PASSED").read_bytes() == marker_payload, "RQ4 marker bytes differ")
    return {
        "status": "passed",
        "protocol_version": STAGE_RQ4_PROTOCOL_VERSION,
        "audit_id": expected_audit["audit_id"],
        "source_rows": SOURCE_ROW_COUNT,
        "paired_question_pairs": PAIRED_QUESTION_COUNT,
        "question_denominator": QUESTION_COUNT,
        "rq5_candidate_rows": table_audit["row_counts"]["rq5-candidate-cases"],
        "output_dir": str(output),
        "no_api_calls": True,
        "no_network_calls": True,
    }


build_chapter5_rq4 = build_rq4
audit_chapter5_rq4_output = audit_rq4_output


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build or audit Chapter 5 RQ4 artifacts")
    parser.add_argument("command", choices=("build", "audit"))
    parser.add_argument("--repo-root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--stage-a-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    return parser


def main(argv: list[str] | None = None) -> None:
    args = _parser().parse_args(argv)
    kwargs = {
        "repo_root": args.repo_root,
        "stage_a_dir": args.stage_a_dir,
        "output_dir": args.output_dir,
    }
    result = build_rq4(**kwargs) if args.command == "build" else audit_rq4_output(**kwargs)
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
