"""Build the compact, auditable Chapter 5 RQ2 robustness artifact.

RQ2 asks whether the architectural findings established by RQ1 retain their
observed direction across the Qwen and DeepSeek end-to-end pipelines.  This
module is deliberately descriptive and offline.  It reads only the frozen,
audited Stage A and Stage E-RQ1 artifacts.  It does not call a model, access
the network, rerun an experiment, compute a new bootstrap, or mutate a formal
result.

The published artifact contains three small result tables:

* seven same-condition Qwen/DeepSeek comparisons for F1, Strict, and Soft;
* seven lexical explanation rows for Precision, Recall, and answer length;
* six cross-backbone architecture-stability rows reused from RQ1.

E7 appears only in the condition-level overview.  Its fusion effects belong
to RQ3.  Full Context, mechanism attribution, cost, and error analysis are
outside RQ2.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import shutil
import tempfile
from collections import Counter, defaultdict
from dataclasses import dataclass
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
from .chapter5_stage_e import audit_stage_e_output
from .evidence import canonical_json_bytes, sha256_bytes


STAGE_RQ2_PROTOCOL_VERSION = "chapter5-main60-rq2-v1"

BACKBONES = ("qwen", "deepseek")
CONDITIONS = ("E1", "E2", "E3", "E4", "E5", "E6", "E7")
QUESTION_COUNT = 60
FLOAT_TOLERANCE = 1e-12

EXPECTED_STAGE_A_AUDIT_ID = (
    "stage-a-audit-5f55ec411f097df7206fdae5e71742641aa8868b4128ac32262f034877a1d7f3"
)
EXPECTED_STAGE_E_AUDIT_ID = (
    "stage-e-rq1-audit-eb62d71e3b89fd63833853e6a21ad306bdb637f4b8140bc57dc1fdbf572ecb24"
)
EXPECTED_STAGE_E_SOURCE_MANIFEST_ID = (
    "stage-e-rq1-sources-54f2eb5c01eb4699b06a3731e2d8b5b5cb51268f20f5cd81947c981422669e8f"
)

EXPECTED_FROZEN_SHA256 = {
    "stage_a_audit": "39aee6ea88c92df547cc98f7b6b343415a558d31a354184e30f0d36acc331966",
    "stage_a_marker": "f4b3aa6f80d2ee7bc4eb9682e37ec85780d4f37a15b22ef65eb78e46ee6f3e34",
    "stage_a_main": "4ccb595baddaec2ddf54a708e94102a45c72e0ddaff63a6c69c940232153f3f8",
    "stage_a_schema": "21295503a3b8e0cadcde9a61a46be1e383c38da329dbc66d716b78faa72ede09",
    "stage_e_audit": "e0b6e0e6bd559b25e2e33283e3d0782ac45c5f745f1f24b6a99887252be6c7eb",
    "stage_e_marker": "0169eebd9317b56540aadce68cfe1ae541c47f0770ed97d58371c59dd6a89464",
    "stage_e_architecture": "699ad7ed507600c690f73ed1193a66abe310c907a67157b48521918aa788f343",
    "stage_e_conditions": "6cdd5e780ccf37b7ba32558023f2e203f6a0fabe02b3196984b70c8689503ebb",
    "stage_e_schema": "478b26c859ed97345f156e7f073a93d4b2aa500bfb7ece096ac96d11249cdb82",
    "stage_e_source_manifest": "3317df737aef598344f57e7a2ada4cbbffa833c94134afa795c3d756efb6f48b",
}

MAIN_METRICS = (
    ("token_f1", "token_f1"),
    ("strict_accuracy", "strict_score"),
    ("soft_semantic_score", "soft_semantic_score"),
)
LEXICAL_METRICS = (
    ("token_precision", "token_precision"),
    ("token_recall", "token_recall"),
    ("answer_normalized_tokens", "answer_normalized_tokens"),
)


@dataclass(frozen=True)
class ComparisonSpec:
    comparison_id: str
    display_formula: str
    baseline_condition: str
    target_condition: str
    comparison_order: int


COMPARISON_SPECS = (
    ComparisonSpec("storage_r1_e3_minus_e1", "E3 - E1", "E1", "E3", 1),
    ComparisonSpec("storage_r2_e4_minus_e2", "E4 - E2", "E2", "E4", 2),
    ComparisonSpec("retrieval_s1_e2_minus_e1", "E2 - E1", "E1", "E2", 3),
    ComparisonSpec("retrieval_s2_e4_minus_e3", "E4 - E3", "E3", "E4", 4),
    ComparisonSpec("curated_access_e6_minus_e5", "E6 - E5", "E5", "E6", 5),
    ComparisonSpec(
        "curated_vs_foldered_r1_e5_minus_e3", "E5 - E3", "E3", "E5", 6
    ),
)


def _artifact_id(prefix: str, body: Mapping[str, Any]) -> str:
    return prefix + sha256_bytes(canonical_json_bytes(dict(body)))


def _mean(rows: Sequence[Mapping[str, Any]], field: str) -> float:
    _require(len(rows) == QUESTION_COUNT, f"RQ2 denominator differs for {field}")
    values = [float(row[field]) for row in rows]
    _require(all(math.isfinite(value) for value in values), f"RQ2 non-finite value: {field}")
    return math.fsum(values) / len(values)


def _close(left: float, right: float) -> bool:
    return math.isclose(float(left), float(right), rel_tol=0.0, abs_tol=FLOAT_TOLERANCE)


def _direction(value: float) -> str:
    if _close(value, 0.0):
        return "zero"
    return "positive" if value > 0.0 else "negative"


def _direction_relation(qwen: float, deepseek: float) -> str:
    qwen_direction = _direction(qwen)
    deepseek_direction = _direction(deepseek)
    if qwen_direction == deepseek_direction == "zero":
        return "both_zero"
    if qwen_direction == deepseek_direction:
        return f"same_direction_{qwen_direction}"
    if "zero" in {qwen_direction, deepseek_direction}:
        return "one_zero"
    return "opposite"


def _stability_classification(
    *, token_f1: tuple[float, float], strict_accuracy: tuple[float, float],
    soft_semantic_score: tuple[float, float],
) -> tuple[str, str, str]:
    pairs = (token_f1, strict_accuracy, soft_semantic_score)
    relations = tuple(_direction_relation(*pair) for pair in pairs)
    primary_relations = relations[:2]
    if any(relation in {"one_zero", "both_zero"} for relation in primary_relations):
        return (
            "indeterminate",
            "zero_primary_effect",
            "At least one primary point estimate is zero, so directional robustness is not assigned.",
        )
    if all(relation.startswith("same_direction_") for relation in primary_relations):
        qwen_primary_directions = tuple(_direction(pair[0]) for pair in pairs[:2])
        if len(set(qwen_primary_directions)) == 1:
            subtype = f"directionally_stable_{qwen_primary_directions[0]}"
            detail = "F1 and Strict Accuracy retain the same direction across backbones."
        else:
            subtype = "stable_metric_tradeoff"
            detail = "F1 and Strict Accuracy each retain their direction, but their directions differ by metric."
        return (
            "stable",
            subtype,
            f"{detail} Soft is reported only as an interpretive supplement ({relations[2]}).",
        )
    if primary_relations == ("opposite", "opposite"):
        return (
            "backbone_dependent",
            "both_primary_metrics_reverse",
            f"Both primary metrics reverse direction across backbones. Soft is supplementary ({relations[2]}).",
        )
    if primary_relations[0].startswith("same_direction_"):
        subtype = "lexical_stable_semantic_backbone_dependent"
    else:
        subtype = "semantic_stable_lexical_backbone_dependent"
    return (
        "partly_stable",
        subtype,
        f"Only one of F1 and Strict Accuracy retains direction across backbones. Soft is supplementary ({relations[2]}).",
    )


def _validate_frozen_inputs(
    *, repo_root: Path, stage_a_dir: Path, stage_e_dir: Path,
) -> dict[str, Any]:
    root = repo_root.resolve()
    stage_a = stage_a_dir.resolve()
    stage_e = stage_e_dir.resolve()
    expected_root = root / "artifacts/chapter5-main60-analysis-v1"
    _require(root.is_dir() and not root.is_symlink(), "Repository root is unsafe")
    _require(stage_a == (expected_root / "stage-a").resolve(), "Stage A is not the frozen repository artifact")
    _require(stage_e == (expected_root / "stage-e-rq1").resolve(), "Stage E is not the frozen repository artifact")
    _require(stage_a.is_dir() and not stage_a.is_symlink(), "Stage A directory is unsafe")
    _require(stage_e.is_dir() and not stage_e.is_symlink(), "Stage E directory is unsafe")

    frozen_files = {
        stage_a / "audit.json": EXPECTED_FROZEN_SHA256["stage_a_audit"],
        stage_a / "STAGE-A.PASSED": EXPECTED_FROZEN_SHA256["stage_a_marker"],
        stage_a / "e1-e7-main.jsonl": EXPECTED_FROZEN_SHA256["stage_a_main"],
        stage_a / "schema.json": EXPECTED_FROZEN_SHA256["stage_a_schema"],
        stage_e / "audit.json": EXPECTED_FROZEN_SHA256["stage_e_audit"],
        stage_e / "STAGE-E-RQ1.PASSED": EXPECTED_FROZEN_SHA256["stage_e_marker"],
        stage_e / "architecture-effects.jsonl": EXPECTED_FROZEN_SHA256["stage_e_architecture"],
        stage_e / "condition-summaries.jsonl": EXPECTED_FROZEN_SHA256["stage_e_conditions"],
        stage_e / "schema.json": EXPECTED_FROZEN_SHA256["stage_e_schema"],
        stage_e / "source-manifest.json": EXPECTED_FROZEN_SHA256["stage_e_source_manifest"],
    }
    for path, expected_sha256 in frozen_files.items():
        _require(path.is_file() and not path.is_symlink(), f"Unsafe or missing frozen input: {path}")
        _require(_sha256_file(path) == expected_sha256, f"Frozen input hash differs: {path.name}")

    stage_a_audit = audit_stage_a_output(stage_a)
    _require(stage_a_audit["audit_id"] == EXPECTED_STAGE_A_AUDIT_ID, "Stage A audit identity differs")
    stage_e_audit = audit_stage_e_output(
        repo_root=root,
        stage_a_dir=stage_a,
        stage_b_dir=expected_root / "stage-b",
        stage_c_dir=expected_root / "stage-c",
        stage_d_dir=expected_root / "stage-d",
        s3_manifest_path=root / "experiments/locomo-conv50-v1/manifests/s3-curated.json",
        output_dir=stage_e,
    )
    _require(stage_e_audit["audit_id"] == EXPECTED_STAGE_E_AUDIT_ID, "Stage E audit identity differs")
    stage_e_manifest = _read_json(stage_e / "source-manifest.json")
    _require(
        stage_e_manifest.get("source_manifest_id") == EXPECTED_STAGE_E_SOURCE_MANIFEST_ID,
        "Stage E source identity differs",
    )
    return {
        "stage_a_audit_id": stage_a_audit["audit_id"],
        "stage_e_audit_id": stage_e_audit["audit_id"],
        "stage_e_source_manifest_id": stage_e_manifest["source_manifest_id"],
        "stage_a_audit_sha256": EXPECTED_FROZEN_SHA256["stage_a_audit"],
        "stage_a_main_sha256": EXPECTED_FROZEN_SHA256["stage_a_main"],
        "stage_e_audit_sha256": EXPECTED_FROZEN_SHA256["stage_e_audit"],
        "stage_e_architecture_sha256": EXPECTED_FROZEN_SHA256["stage_e_architecture"],
        "stage_e_conditions_sha256": EXPECTED_FROZEN_SHA256["stage_e_conditions"],
    }


def _validate_stage_a_rows(rows: Sequence[Mapping[str, Any]]) -> dict[tuple[str, str], list[dict[str, Any]]]:
    _require(len(rows) == 840, "RQ2 Stage A row count differs")
    keys = [(str(row["backbone_id"]), str(row["condition_id"]), str(row["question_id"])) for row in rows]
    _require(len(set(keys)) == 840, "RQ2 Stage A keys are not unique")
    _require({str(row["backbone_id"]) for row in rows} == set(BACKBONES), "RQ2 backbones differ")
    _require({str(row["condition_id"]) for row in rows} == set(CONDITIONS), "RQ2 conditions differ")
    _require(all(row.get("is_e1_e7_main") is True for row in rows), "RQ2 includes a non-E1--E7 row")
    _require(
        all(
            str(row.get("access_regime"))
            == ("dual_source_fusion" if str(row["condition_id"]) == "E7" else "selective_retrieval")
            for row in rows
        ),
        "RQ2 access regimes differ",
    )

    grouped: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for source in rows:
        row = dict(source)
        grouped[(str(row["backbone_id"]), str(row["condition_id"]))].append(row)
    _require(len(grouped) == 14, "RQ2 backbone-condition groups differ")
    _require(all(len(group) == QUESTION_COUNT for group in grouped.values()), "RQ2 group denominator differs")

    expected_models = {
        "qwen": ("model1-qwen-main60", "coding", "qwen3.8:27b"),
        "deepseek": ("model2-deepseek-main60", "x-test-2", "deepseek-v4.1-flash"),
    }
    forbidden_fields = {
        "question", "reference_answer", "candidate_answer", "answer", "evidence_text",
        "judge_reason", "short_reason", "api_key", "authorization",
    }
    for row in rows:
        backbone = str(row["backbone_id"])
        answer_set, requested_model, served_model = expected_models[backbone]
        _require(
            (row["answer_set_id"], row["requested_model"], row["served_model"])
            == (answer_set, requested_model, served_model),
            f"RQ2 model identity differs: {backbone}",
        )
        _require(
            (row["judge_requested_model"], row["judge_served_model"])
            == ("x-test-1", "glm-5.3-flash"),
            "RQ2 Judge identity differs",
        )
        _require(not forbidden_fields.intersection(row), "RQ2 source unexpectedly contains text or secret fields")

    identity_fields = (
        "question_id", "question_sha256", "global_position", "category", "category_name",
        "evidence_eligible",
    )
    for condition in CONDITIONS:
        paired = []
        for backbone in BACKBONES:
            ordered = sorted(grouped[(backbone, condition)], key=lambda row: int(row["global_position"]))
            paired.append([tuple(row[field] for field in identity_fields) for row in ordered])
        _require(paired[0] == paired[1], f"RQ2 question pairing differs: {condition}")
    return grouped


def _condition_means(
    grouped: Mapping[tuple[str, str], Sequence[Mapping[str, Any]]]
) -> dict[tuple[str, str, str], float]:
    result: dict[tuple[str, str, str], float] = {}
    for backbone in BACKBONES:
        for condition in CONDITIONS:
            rows = grouped[(backbone, condition)]
            for published_name, source_field in MAIN_METRICS + LEXICAL_METRICS:
                result[(backbone, condition, published_name)] = _mean(rows, source_field)
    return result


def _reconcile_stage_e_conditions(
    means: Mapping[tuple[str, str, str], float], stage_e_rows: Sequence[Mapping[str, Any]]
) -> None:
    relevant_metrics = {published for published, _ in MAIN_METRICS} | {
        published for published, _ in LEXICAL_METRICS if published != "answer_normalized_tokens"
    }
    index: dict[tuple[str, str, str], Mapping[str, Any]] = {}
    for row in stage_e_rows:
        key = (str(row["backbone_id"]), str(row["condition_id"]), str(row["metric_id"]))
        if key[1] in CONDITIONS[:6] and key[2] in relevant_metrics:
            _require(key not in index, f"Duplicate Stage E condition summary: {key}")
            index[key] = row
    _require(len(index) == 2 * 6 * len(relevant_metrics), "Stage E condition reconciliation rows differ")
    for key, source in index.items():
        _require(int(source["denominator"]) == QUESTION_COUNT, f"Stage E denominator differs: {key}")
        _require(_close(means[key], float(source["mean"])), f"Stage A/E mean differs: {key}")


def _condition_comparison_rows(
    means: Mapping[tuple[str, str, str], float]
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for order, condition in enumerate(CONDITIONS, start=1):
        body: dict[str, Any] = {
            "protocol_version": STAGE_RQ2_PROTOCOL_VERSION,
            "condition_order": order,
            "condition_id": condition,
            "denominator": QUESTION_COUNT,
            "delta_definition": "deepseek_minus_qwen",
        }
        for metric, _ in MAIN_METRICS:
            qwen = means[("qwen", condition, metric)]
            deepseek = means[("deepseek", condition, metric)]
            body[f"qwen_{metric}"] = qwen
            body[f"deepseek_{metric}"] = deepseek
            body[f"delta_{metric}"] = deepseek - qwen
        body["descriptive_only"] = True
        rows.append({"result_id": _artifact_id("rq2-condition-", body), **body})
    return rows


def _lexical_explanation_rows(
    means: Mapping[tuple[str, str, str], float]
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for order, condition in enumerate(CONDITIONS, start=1):
        body: dict[str, Any] = {
            "protocol_version": STAGE_RQ2_PROTOCOL_VERSION,
            "condition_order": order,
            "condition_id": condition,
            "denominator": QUESTION_COUNT,
            "delta_definition": "deepseek_minus_qwen",
        }
        for metric, _ in LEXICAL_METRICS:
            qwen = means[("qwen", condition, metric)]
            deepseek = means[("deepseek", condition, metric)]
            body[f"qwen_{metric}"] = qwen
            body[f"deepseek_{metric}"] = deepseek
            body[f"delta_{metric}"] = deepseek - qwen
        body["interpretation_scope"] = "descriptive explanation of lexical-semantic disagreement only"
        rows.append({"result_id": _artifact_id("rq2-lexical-", body), **body})
    return rows


def _architecture_stability_rows(
    *, means: Mapping[tuple[str, str, str], float],
    architecture_rows: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    selected_ids = {spec.comparison_id for spec in COMPARISON_SPECS}
    selected = [row for row in architecture_rows if str(row.get("comparison_id")) in selected_ids]
    _require(len(selected) == 12, "RQ2 requires exactly six comparisons by two backbones")
    _require({str(row["backbone_id"]) for row in selected} == set(BACKBONES), "RQ2 architecture backbones differ")
    _require(all(row.get("comparison_type") == "simple" for row in selected), "RQ2 includes an interaction effect")
    _require(all(row.get("difference_direction") == "target_minus_baseline" for row in selected), "RQ2 effect direction differs")
    _require(all(row.get("target_condition") != "E7" for row in selected), "E7 fusion effect belongs to RQ3")
    index = {(str(row["backbone_id"]), str(row["comparison_id"])): row for row in selected}
    _require(len(index) == 12, "RQ2 architecture rows are not unique")

    rows: list[dict[str, Any]] = []
    for spec in COMPARISON_SPECS:
        source_by_backbone = {backbone: index[(backbone, spec.comparison_id)] for backbone in BACKBONES}
        body: dict[str, Any] = {
            "protocol_version": STAGE_RQ2_PROTOCOL_VERSION,
            "comparison_order": spec.comparison_order,
            "comparison_id": spec.comparison_id,
            "display_formula": spec.display_formula,
            "baseline_condition": spec.baseline_condition,
            "target_condition": spec.target_condition,
            "difference_direction": "target_minus_baseline",
            "cross_difference_definition": "deepseek_effect_minus_qwen_effect",
            "denominator": QUESTION_COUNT,
        }
        classification_pairs: dict[str, tuple[float, float]] = {}
        for metric, _ in MAIN_METRICS:
            field = f"delta_{metric}"
            qwen = float(source_by_backbone["qwen"][field])
            deepseek = float(source_by_backbone["deepseek"][field])
            for backbone, value in (("qwen", qwen), ("deepseek", deepseek)):
                expected = (
                    means[(backbone, spec.target_condition, metric)]
                    - means[(backbone, spec.baseline_condition, metric)]
                )
                _require(_close(value, expected), f"RQ2 effect does not reconcile: {backbone}/{spec.comparison_id}/{metric}")
            body[f"qwen_{metric}_effect"] = qwen
            body[f"deepseek_{metric}_effect"] = deepseek
            body[f"cross_backbone_{metric}_difference"] = deepseek - qwen
            body[f"qwen_{metric}_direction"] = _direction(qwen)
            body[f"deepseek_{metric}_direction"] = _direction(deepseek)
            body[f"{metric}_direction_relation"] = _direction_relation(qwen, deepseek)
            classification_pairs[metric] = (qwen, deepseek)
        classification, subtype, basis = _stability_classification(
            token_f1=classification_pairs["token_f1"],
            strict_accuracy=classification_pairs["strict_accuracy"],
            soft_semantic_score=classification_pairs["soft_semantic_score"],
        )
        body["stability_classification"] = classification
        body["stability_subtype"] = subtype
        body["classification_basis"] = basis
        body["descriptive_only"] = True
        rows.append({"result_id": _artifact_id("rq2-stability-", body), **body})
    return rows


def _table_5_13_rows(stability_rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Project the full audit table into the compact report-facing matrix."""

    fields = (
        "protocol_version",
        "comparison_order",
        "comparison_id",
        "display_formula",
        "qwen_token_f1_effect",
        "deepseek_token_f1_effect",
        "token_f1_direction_relation",
        "qwen_strict_accuracy_effect",
        "deepseek_strict_accuracy_effect",
        "strict_accuracy_direction_relation",
        "qwen_soft_semantic_score_effect",
        "deepseek_soft_semantic_score_effect",
        "soft_semantic_score_direction_relation",
        "stability_classification",
        "stability_subtype",
        "classification_basis",
        "descriptive_only",
    )
    return [{field: row[field] for field in fields} for row in stability_rows]


def _compute_rq2(
    *, repo_root: Path, stage_a_dir: Path, stage_e_dir: Path,
) -> tuple[dict[str, list[dict[str, Any]]], dict[str, Any], dict[str, Any]]:
    provenance = _validate_frozen_inputs(
        repo_root=repo_root, stage_a_dir=stage_a_dir, stage_e_dir=stage_e_dir
    )
    stage_a_rows = _read_jsonl(stage_a_dir / "e1-e7-main.jsonl")
    grouped = _validate_stage_a_rows(stage_a_rows)
    means = _condition_means(grouped)
    stage_e_conditions = _read_jsonl(stage_e_dir / "condition-summaries.jsonl")
    _reconcile_stage_e_conditions(means, stage_e_conditions)
    architecture_source = _read_jsonl(stage_e_dir / "architecture-effects.jsonl")

    conditions = _condition_comparison_rows(means)
    lexical = _lexical_explanation_rows(means)
    stability = _architecture_stability_rows(means=means, architecture_rows=architecture_source)
    tables = {
        "condition-backbone-comparison": conditions,
        "lexical-explanation": lexical,
        "architecture-stability": stability,
        "table-5-13-inputs": _table_5_13_rows(stability),
    }
    classifications = Counter(row["stability_classification"] for row in stability)
    subtypes = Counter(row["stability_subtype"] for row in stability)
    checks = {
        "stage_a_rows_840": len(stage_a_rows) == 840,
        "backbone_condition_cells_14": len(grouped) == 14,
        "questions_per_cell_60": all(len(rows) == QUESTION_COUNT for rows in grouped.values()),
        "condition_rows_7": len(conditions) == 7,
        "lexical_rows_7": len(lexical) == 7,
        "architecture_rows_6": len(stability) == 6,
        "table_5_13_rows_6": len(tables["table-5-13-inputs"]) == 6,
        "e7_condition_only": "E7" in {row["condition_id"] for row in conditions}
        and all(row["target_condition"] != "E7" for row in stability),
        "full_context_absent": all("full" not in str(value).lower() for table in tables.values() for row in table for value in row.values()),
        "descriptive_only": all(row.get("descriptive_only") is True for row in conditions + stability),
        "classification_counts_expected": classifications
        == Counter({"stable": 3, "partly_stable": 2, "backbone_dependent": 1}),
        "classification_taxonomy_valid": set(classifications)
        <= {"stable", "partly_stable", "backbone_dependent", "indeterminate"},
    }
    _require(all(checks.values()), "RQ2 table audit failed")
    return tables, provenance, {
        "checks": checks,
        "row_counts": {name: len(rows) for name, rows in tables.items()},
        "stability_classification_counts": dict(classifications),
        "stability_subtype_counts": dict(subtypes),
    }


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
        _require(bool(rows), f"RQ2 table is empty: {name}")
        fields = list(rows[0])
        _require(all(list(row) == fields for row in rows), f"RQ2 table schema differs: {name}")
        result[name] = {
            "row_count": len(rows),
            "fields": [
                {
                    "name": field,
                    "types": sorted({_value_type(row[field]) for row in rows}),
                }
                for field in fields
            ],
        }
    return {
        "schema_version": 1,
        "protocol_version": STAGE_RQ2_PROTOCOL_VERSION,
        "tables": result,
        "delta_definition": "deepseek_minus_qwen",
        "cross_difference_definition": "deepseek_effect_minus_qwen_effect",
        "classification_scope": "descriptive direction robustness, not statistical significance",
    }


def _readme() -> str:
    return """# Chapter 5 RQ2: cross-backbone robustness

This directory is the audited, offline input for Section 5.3. It compares the
Qwen and DeepSeek end-to-end pipelines on the unified Main-60 E1--E7 test set.

`condition-backbone-comparison` reports F1, Strict Accuracy, and Soft Semantic
Score for the two backbones under the same condition. `lexical-explanation`
contains Precision, Recall, and normalised answer length only to explain major
lexical--semantic disagreement. `architecture-stability` reuses six audited
RQ1 contrasts and reports each model-specific effect plus the descriptive
cross-backbone difference. `table-5-13-inputs` is the report-ready copy of the
same six stability rows.

All deltas in the first two tables are DeepSeek minus Qwen. Cross-backbone
architecture differences are the DeepSeek effect minus the Qwen effect.
Stability labels describe observed directions across these two pipelines; they
are not tests of statistical significance or universal backbone invariance.

E7 appears only in the condition overview. E7 fusion effects belong to RQ3.
Full Context is absent because no symmetric Qwen Full Context run exists.
This artifact contains no question, answer, evidence, rationale, or secret
text. It made no API or network call and computed no new bootstrap interval.
"""


def _source_manifest(
    *, repo_root: Path, stage_a_dir: Path, stage_e_dir: Path,
    provenance: Mapping[str, Any],
) -> dict[str, Any]:
    body = {
        "schema_version": 1,
        "protocol_version": STAGE_RQ2_PROTOCOL_VERSION,
        "scope": "compact descriptive cross-backbone robustness on unified Main-60 E1--E7",
        "stage_a_directory": _relative(repo_root, stage_a_dir),
        "stage_e_directory": _relative(repo_root, stage_e_dir),
        **dict(provenance),
        "backbones": list(BACKBONES),
        "backbone_identities": {
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
        "judge_identity": {
            "requested_model": "x-test-1",
            "served_model": "glm-5.3-flash",
        },
        "conditions": list(CONDITIONS),
        "question_denominator": QUESTION_COUNT,
        "answer_denominator": QUESTION_COUNT,
        "condition_ids": list(CONDITIONS),
        "main_architecture_comparisons": [spec.comparison_id for spec in COMPARISON_SPECS],
        "architecture_comparison_ids": [spec.comparison_id for spec in COMPARISON_SPECS],
        "condition_delta_definition": "deepseek_minus_qwen",
        "architecture_cross_difference_definition": "deepseek_effect_minus_qwen_effect",
        "no_api_calls": True,
        "no_network_calls": True,
        "formal_source_mutation": False,
        "new_bootstrap_computed": False,
        "cross_backbone_statistical_inference_computed": False,
        "cross_backbone_inference_computed": False,
        "descriptive_cross_backbone_differences_computed": True,
        "category_analysis_computed": False,
        "cost_analysis_computed": False,
        "trace_review_computed": False,
        "e7_fusion_effects_computed": False,
        "full_context_computed": False,
    }
    return {
        "source_manifest_id": "rq2-sources-" + sha256_bytes(canonical_json_bytes(body)),
        **body,
    }


def _artifact_payloads(
    tables: Mapping[str, Sequence[Mapping[str, Any]]], source_manifest: Mapping[str, Any]
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
        "protocol_version": STAGE_RQ2_PROTOCOL_VERSION,
        "status": "passed",
        "scope": "compact descriptive RQ2 cross-backbone robustness",
        "no_api_calls": True,
        "no_network_calls": True,
        "formal_source_mutation": False,
        "new_bootstrap_computed": False,
        "cross_backbone_statistical_inference_computed": False,
        "descriptive_cross_backbone_differences_computed": True,
        "e7_fusion_effects_computed": False,
        "full_context_computed": False,
        "source_manifest_id": source_manifest["source_manifest_id"],
        **dict(provenance),
        "table_audit": dict(table_audit),
        "output_sha256": dict(output_hashes),
    }


def _marker(audit: Mapping[str, Any], audit_sha256: str) -> dict[str, Any]:
    return {
        "status": "passed",
        "protocol_version": STAGE_RQ2_PROTOCOL_VERSION,
        "audit_id": audit["audit_id"],
        "audit_sha256": audit_sha256,
        "condition_rows": 7,
        "lexical_rows": 7,
        "architecture_rows": 6,
        "question_denominator": QUESTION_COUNT,
        "no_api_calls": True,
        "no_network_calls": True,
        "new_bootstrap_computed": False,
    }


def build_rq2(
    *, repo_root: Path, stage_a_dir: Path, stage_e_dir: Path, output_dir: Path,
) -> dict[str, Any]:
    root = repo_root.resolve()
    destination = output_dir.resolve()
    _require(not destination.exists() and not destination.is_symlink(), "RQ2 output already exists")
    for label, source in (("Stage A", stage_a_dir.resolve()), ("Stage E", stage_e_dir.resolve())):
        try:
            destination.relative_to(source)
        except ValueError:
            continue
        _require(False, f"RQ2 output may not be published inside frozen {label}")

    tables, provenance, table_audit = _compute_rq2(
        repo_root=root, stage_a_dir=stage_a_dir.resolve(), stage_e_dir=stage_e_dir.resolve()
    )
    manifest = _source_manifest(
        repo_root=root,
        stage_a_dir=stage_a_dir.resolve(),
        stage_e_dir=stage_e_dir.resolve(),
        provenance=provenance,
    )
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
        audit = {"audit_id": "rq2-audit-" + sha256_bytes(canonical_json_bytes(body)), **body}
        _write(temporary / "audit.json", canonical_json_bytes(audit) + b"\n")
        _write(
            temporary / "RQ2.PASSED",
            canonical_json_bytes(_marker(audit, _sha256_file(temporary / "audit.json"))) + b"\n",
        )
        result = audit_rq2_output(
            repo_root=root,
            stage_a_dir=stage_a_dir,
            stage_e_dir=stage_e_dir,
            output_dir=temporary,
        )
        _require(result["status"] == "passed", "RQ2 pre-publication audit failed")
        _require(not destination.exists(), "RQ2 output appeared during build")
        os.rename(temporary, destination)
        descriptor = os.open(destination.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
    except Exception:
        shutil.rmtree(temporary, ignore_errors=True)
        raise
    return audit_rq2_output(
        repo_root=root,
        stage_a_dir=stage_a_dir,
        stage_e_dir=stage_e_dir,
        output_dir=destination,
    )


def audit_rq2_output(
    *, repo_root: Path, stage_a_dir: Path, stage_e_dir: Path, output_dir: Path,
) -> dict[str, Any]:
    root = repo_root.resolve()
    output = output_dir.resolve()
    _require(output.is_dir() and not output.is_symlink(), "RQ2 output directory is unsafe")
    tables, provenance, table_audit = _compute_rq2(
        repo_root=root, stage_a_dir=stage_a_dir.resolve(), stage_e_dir=stage_e_dir.resolve()
    )
    manifest = _source_manifest(
        repo_root=root,
        stage_a_dir=stage_a_dir.resolve(),
        stage_e_dir=stage_e_dir.resolve(),
        provenance=provenance,
    )
    payloads = _artifact_payloads(tables, manifest)
    hashes = {name: hashlib.sha256(payload).hexdigest() for name, payload in sorted(payloads.items())}
    body = _audit_body(
        source_manifest=manifest,
        provenance=provenance,
        table_audit=table_audit,
        output_hashes=hashes,
    )
    expected_audit = {"audit_id": "rq2-audit-" + sha256_bytes(canonical_json_bytes(body)), **body}
    audit_payload = canonical_json_bytes(expected_audit) + b"\n"
    marker_payload = canonical_json_bytes(
        _marker(expected_audit, hashlib.sha256(audit_payload).hexdigest())
    ) + b"\n"

    expected_names = set(payloads) | {"audit.json", "RQ2.PASSED"}
    entries = list(output.iterdir())
    _require(all(entry.is_file() and not entry.is_symlink() for entry in entries), "RQ2 output contains unsafe entry")
    _require({entry.name for entry in entries} == expected_names, "RQ2 output file set differs")
    for name, payload in payloads.items():
        _require((output / name).read_bytes() == payload, f"RQ2 artifact bytes differ: {name}")
    _require((output / "audit.json").read_bytes() == audit_payload, "RQ2 audit bytes differ")
    _require((output / "RQ2.PASSED").read_bytes() == marker_payload, "RQ2 marker bytes differ")
    return {
        "status": "passed",
        "protocol_version": STAGE_RQ2_PROTOCOL_VERSION,
        "audit_id": expected_audit["audit_id"],
        "condition_rows": 7,
        "lexical_rows": 7,
        "architecture_rows": 6,
        "question_denominator": QUESTION_COUNT,
        "output_dir": str(output),
        "no_api_calls": True,
        "no_network_calls": True,
    }


build_chapter5_rq2 = build_rq2
audit_chapter5_rq2_output = audit_rq2_output


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build or audit Chapter 5 RQ2 artifacts")
    parser.add_argument("command", choices=("build", "audit"))
    parser.add_argument("--repo-root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--stage-a-dir", type=Path, required=True)
    parser.add_argument("--stage-e-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    return parser


def main(argv: list[str] | None = None) -> None:
    args = _parser().parse_args(argv)
    kwargs = {
        "repo_root": args.repo_root,
        "stage_a_dir": args.stage_a_dir,
        "stage_e_dir": args.stage_e_dir,
        "output_dir": args.output_dir,
    }
    result = build_rq2(**kwargs) if args.command == "build" else audit_rq2_output(**kwargs)
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
