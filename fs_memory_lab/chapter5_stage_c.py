"""Build and audit Chapter 5 Stage C curated-memory paired analyses.

Stage C consumes only the frozen Stage A RQ1 analysis view and treats the
audited Stage B publication as a required lineage gate.  It computes five
pre-declared, within-backbone target-minus-baseline contrasts involving S3
(E5 or E6), publishes only E5/E6 condition summaries, and keeps the main
complete-system anchors separate from appendix sensitivity anchors.

This module deliberately does not compute bootstrap intervals, interactions,
category effects, cross-backbone pooled effects, E7, Full Context, costs, or
error-stage diagnoses.  It never reads text-bearing answer/evidence fields,
calls a model API, or modifies a formal source run.
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

from .chapter5_stage_a import STAGE_A_PROTOCOL_VERSION, audit_stage_a_output
from .chapter5_stage_b import (
    ANSWER_METRICS,
    BACKBONES,
    EVIDENCE_ELIGIBLE_COUNT,
    EVIDENCE_METRICS,
    EXPECTED_ANSWER_SETS,
    EXPECTED_CATEGORIES,
    EXPECTED_CATEGORY_NAMES,
    EXPECTED_EVIDENCE_CATEGORIES,
    EXPECTED_INELIGIBLE_QUESTION_IDS,
    EXPECTED_JUDGE,
    EXPECTED_MODELS,
    EXPECTED_MULTI_GOLD_SOURCE_COUNT,
    EXPECTED_STAGE_A_AUDIT_ID,
    EXPECTED_STAGE_A_RQ1_SHA256,
    EXPECTED_STAGE_A_SCHEMA_SHA256,
    EXPECTED_STAGE_A_SOURCE_MANIFEST_ID,
    METRICS,
    METRIC_BY_ID,
    MULTI_GOLD_SOURCE_METRICS,
    QUESTION_COUNT,
    STAGE_B_PROTOCOL_VERSION,
    TIE_TOLERANCE,
    MetricSpec,
    _csv_payload,
    _expected_denominator,
    _id,
    _is_close,
    _jsonl_payload,
    _mean,
    _median,
    _metric_direction_name,
    _metric_value,
    _no_text_bearing_fields,
    _oriented_state,
    _read_json,
    _read_jsonl,
    _relative,
    _require,
    _row_in_scope,
    _sha256_file,
    _state,
    _write,
    audit_stage_b_output,
)
from .evidence import canonical_json_bytes, sha256_bytes


STAGE_C_PROTOCOL_VERSION = "chapter5-main60-stage-c-v1"
STAGE_C_CONDITIONS = ("E1", "E2", "E3", "E4", "E5", "E6")
STAGE_C_SUMMARY_CONDITIONS = ("E5", "E6")
EXPECTED_STAGE_C_ROWS = 720
EXPECTED_PAIRED_ROWS = 6_490
EXPECTED_AGGREGATE_ROWS = 130
EXPECTED_STRICT_TRANSITION_ROWS = 40
EXPECTED_SEMANTIC_TRANSITION_ROWS = 90
# Summing large character counts through mathematically equivalent paths can
# differ by a few binary floating-point ulps.  This tolerance is used only for
# audited aggregate identities; question-level tie classification continues
# to use the frozen TIE_TOLERANCE imported from Stage B.
AGGREGATE_IDENTITY_TOLERANCE = 1e-9

EXPECTED_STAGE_A_AUDIT_SHA256 = "39aee6ea88c92df547cc98f7b6b343415a558d31a354184e30f0d36acc331966"
EXPECTED_STAGE_A_MARKER_SHA256 = "f4b3aa6f80d2ee7bc4eb9682e37ec85780d4f37a15b22ef65eb78e46ee6f3e34"
EXPECTED_STAGE_A_SOURCE_MANIFEST_SHA256 = "2b1f56d0897904fb9d4b8487111ecc2d7b55848f54f97dbfe34de53c16b59a65"

EXPECTED_STAGE_B_AUDIT_ID = "stage-b-audit-2c5061c3db5cba00f099648963eaa2175d1136954e4cf673720423e7ffed6932"
EXPECTED_STAGE_B_SOURCE_MANIFEST_ID = "stage-b-sources-430f42b4398f2859091ad42f74000e3b6f712ed2c7c43606fc3d318afa1b6686"
EXPECTED_STAGE_B_AUDIT_SHA256 = "67b638bccad3f664a8eec9f0e9f11554f777c336888c95d0594bbdb96d11e526"
EXPECTED_STAGE_B_MARKER_SHA256 = "b137218da5cae7f2458dabf3322d6a88be6b616dcd57df6210cda02e0eabbfa2"
EXPECTED_STAGE_B_SOURCE_MANIFEST_SHA256 = "71019dfb5af934645c45c073ae6eaeb5e9c6673ca90a627cdf03bee086f200bd"
EXPECTED_STAGE_B_SCHEMA_SHA256 = "d8a2bf7113e4cc5247ee6eaba7b660395acfef51dbfce3d2541b165103116362"

EXPECTED_DESIGN = {
    "E1": ("S1", "R1"),
    "E2": ("S1", "R2"),
    "E3": ("S2", "R1"),
    "E4": ("S2", "R2"),
    "E5": ("S3", "R1"),
    "E6": ("S3", "R3"),
}


@dataclass(frozen=True)
class ContrastSpec:
    """A frozen Stage C comparison and its permitted interpretation."""

    contrast_id: str
    contrast_family: str
    baseline_condition: str
    target_condition: str
    comparison_status: str
    publication_role: str
    identification_scope: str


CONTRASTS = (
    ContrastSpec(
        "curated_access_e6_minus_e5",
        "curated_access_system",
        "E5",
        "E6",
        "core_effect",
        "main_core",
        "S3 is fixed; this identifies the complete R3-versus-R1 access-system effect, not an individual retrieval component.",
    ),
    ContrastSpec(
        "curated_vs_foldered_r1_e5_minus_e3",
        "curated_memory_complete_system",
        "E3",
        "E5",
        "descriptive_complete_system_anchor",
        "main_descriptive",
        "R1 is fixed, but S2-to-S3 changes content wording, granularity, organisation, and provenance; this is not a pure curation effect.",
    ),
    ContrastSpec(
        "curated_adapted_vs_foldered_raw_e6_minus_e4",
        "curated_adapted_complete_system",
        "E4",
        "E6",
        "descriptive_complete_system_anchor",
        "main_descriptive",
        "S2+R2 versus S3+R3 changes the representation and retrieval system together; this is a complete-system comparison.",
    ),
    ContrastSpec(
        "curated_vs_flat_r1_e5_minus_e1",
        "curated_memory_sensitivity",
        "E1",
        "E5",
        "descriptive_sensitivity_anchor",
        "appendix_sensitivity",
        "R1 is fixed; the flat-raw baseline is a sensitivity anchor and does not isolate curation from all representation changes.",
    ),
    ContrastSpec(
        "curated_adapted_vs_flat_raw_e6_minus_e2",
        "curated_adapted_sensitivity",
        "E2",
        "E6",
        "descriptive_sensitivity_anchor",
        "appendix_sensitivity",
        "S1+R2 versus S3+R3 is a sensitivity anchor that changes representation and retrieval together.",
    ),
)
CONTRAST_BY_ID = {spec.contrast_id: spec for spec in CONTRASTS}
MAIN_CONTRASTS = tuple(spec for spec in CONTRASTS if spec.publication_role != "appendix_sensitivity")
SENSITIVITY_CONTRASTS = tuple(spec for spec in CONTRASTS if spec.publication_role == "appendix_sensitivity")
PRIMARY_TABLE_METRICS = ("token_f1", "strict_accuracy", "soft_semantic_score", "evidence_recall")


def _validate_stage_a_lineage(stage_a_dir: Path) -> dict[str, Any]:
    gate = audit_stage_a_output(stage_a_dir)
    audit = _read_json(stage_a_dir / "audit.json")
    marker = _read_json(stage_a_dir / "STAGE-A.PASSED")
    manifest = _read_json(stage_a_dir / "source-manifest.json")
    _require(gate.get("status") == "passed", "Stage A gate is not passed")
    _require(audit.get("protocol_version") == STAGE_A_PROTOCOL_VERSION, "Stage A protocol differs")
    _require(audit.get("audit_id") == EXPECTED_STAGE_A_AUDIT_ID, "Frozen Stage A audit identity differs")
    _require(marker.get("audit_id") == EXPECTED_STAGE_A_AUDIT_ID, "Stage A marker audit identity differs")
    _require(
        manifest.get("source_manifest_id") == EXPECTED_STAGE_A_SOURCE_MANIFEST_ID,
        "Frozen Stage A source-manifest identity differs",
    )
    checks = {
        "audit.json": EXPECTED_STAGE_A_AUDIT_SHA256,
        "STAGE-A.PASSED": EXPECTED_STAGE_A_MARKER_SHA256,
        "source-manifest.json": EXPECTED_STAGE_A_SOURCE_MANIFEST_SHA256,
        "rq1-analysis-view.jsonl": EXPECTED_STAGE_A_RQ1_SHA256,
        "schema.json": EXPECTED_STAGE_A_SCHEMA_SHA256,
    }
    for name, digest in checks.items():
        _require(_sha256_file(stage_a_dir / name) == digest, f"Frozen Stage A hash differs: {name}")
    return {
        "stage_a_protocol_version": STAGE_A_PROTOCOL_VERSION,
        "stage_a_audit_id": EXPECTED_STAGE_A_AUDIT_ID,
        "stage_a_audit_sha256": EXPECTED_STAGE_A_AUDIT_SHA256,
        "stage_a_marker_sha256": EXPECTED_STAGE_A_MARKER_SHA256,
        "stage_a_source_manifest_id": EXPECTED_STAGE_A_SOURCE_MANIFEST_ID,
        "stage_a_source_manifest_sha256": EXPECTED_STAGE_A_SOURCE_MANIFEST_SHA256,
        "stage_a_rq1_view_sha256": EXPECTED_STAGE_A_RQ1_SHA256,
        "stage_a_schema_sha256": EXPECTED_STAGE_A_SCHEMA_SHA256,
    }


def _validate_stage_b_lineage(stage_a_dir: Path, stage_b_dir: Path) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    gate = audit_stage_b_output(stage_a_dir=stage_a_dir, output_dir=stage_b_dir)
    audit = _read_json(stage_b_dir / "audit.json")
    marker = _read_json(stage_b_dir / "STAGE-B.PASSED")
    manifest = _read_json(stage_b_dir / "source-manifest.json")
    _require(gate.get("status") == "passed", "Stage B lineage gate is not passed")
    _require(audit.get("protocol_version") == STAGE_B_PROTOCOL_VERSION, "Stage B protocol differs")
    _require(audit.get("audit_id") == EXPECTED_STAGE_B_AUDIT_ID, "Frozen Stage B audit identity differs")
    _require(marker.get("audit_id") == EXPECTED_STAGE_B_AUDIT_ID, "Stage B marker audit identity differs")
    _require(
        manifest.get("source_manifest_id") == EXPECTED_STAGE_B_SOURCE_MANIFEST_ID,
        "Frozen Stage B source-manifest identity differs",
    )
    checks = {
        "audit.json": EXPECTED_STAGE_B_AUDIT_SHA256,
        "STAGE-B.PASSED": EXPECTED_STAGE_B_MARKER_SHA256,
        "source-manifest.json": EXPECTED_STAGE_B_SOURCE_MANIFEST_SHA256,
        "schema.json": EXPECTED_STAGE_B_SCHEMA_SHA256,
    }
    for name, digest in checks.items():
        _require(_sha256_file(stage_b_dir / name) == digest, f"Frozen Stage B hash differs: {name}")
    summaries = _read_jsonl(stage_b_dir / "condition-summaries.jsonl")
    return (
        {
            "stage_b_protocol_version": STAGE_B_PROTOCOL_VERSION,
            "stage_b_audit_id": EXPECTED_STAGE_B_AUDIT_ID,
            "stage_b_audit_sha256": EXPECTED_STAGE_B_AUDIT_SHA256,
            "stage_b_marker_sha256": EXPECTED_STAGE_B_MARKER_SHA256,
            "stage_b_source_manifest_id": EXPECTED_STAGE_B_SOURCE_MANIFEST_ID,
            "stage_b_source_manifest_sha256": EXPECTED_STAGE_B_SOURCE_MANIFEST_SHA256,
            "stage_b_schema_sha256": EXPECTED_STAGE_B_SCHEMA_SHA256,
            "stage_b_condition_summaries_sha256": _sha256_file(stage_b_dir / "condition-summaries.jsonl"),
        },
        summaries,
    )


def _load_inputs(
    stage_a_dir: Path,
    stage_b_dir: Path,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    stage_a_provenance = _validate_stage_a_lineage(stage_a_dir)
    stage_b_provenance, stage_b_summaries = _validate_stage_b_lineage(stage_a_dir, stage_b_dir)
    rows = _read_jsonl(stage_a_dir / "rq1-analysis-view.jsonl")
    _require(len(rows) == EXPECTED_STAGE_C_ROWS, "Stage C input is not the frozen 720-row RQ1 view")
    return rows, stage_b_summaries, {**stage_a_provenance, **stage_b_provenance}


def _validate_input(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    _require(len(rows) == EXPECTED_STAGE_C_ROWS, "Stage C input row count differs")
    keyed: set[tuple[str, str, str]] = set()
    cells: Counter[tuple[str, str]] = Counter()
    categories: dict[tuple[str, str], Counter[int]] = defaultdict(Counter)
    evidence_categories: dict[tuple[str, str], Counter[int]] = defaultdict(Counter)
    question_metadata: dict[str, tuple[Any, ...]] = {}
    evidence_masks: dict[tuple[str, str], tuple[str, ...]] = {}
    multi_masks: dict[tuple[str, str], tuple[str, ...]] = {}

    for row in rows:
        backbone = str(row.get("backbone_id"))
        condition = str(row.get("condition_id"))
        question_id = str(row.get("question_id"))
        _require(backbone in BACKBONES, f"Unexpected Stage C backbone: {backbone}")
        _require(condition in STAGE_C_CONDITIONS, f"Unexpected Stage C condition: {condition}")
        _require(row.get("answer_set_id") == EXPECTED_ANSWER_SETS[backbone], "Answer-set identity differs")
        _require(row.get("protocol_version") == STAGE_A_PROTOCOL_VERSION, "Stage A row protocol differs")
        _require(row.get("is_rq1_analysis_row") is True, "Input row is not marked for RQ1")
        expected_storage, expected_retrieval = EXPECTED_DESIGN[condition]
        _require(
            row.get("storage_representation") == expected_storage
            and row.get("retrieval_system") == expected_retrieval
            and row.get("access_regime") == "selective_retrieval",
            f"Condition design differs: {backbone}/{condition}/{question_id}",
        )
        _require(row.get("evidence_budget_characters") == 16_000, "Evidence budget differs")
        requested, served = EXPECTED_MODELS[backbone]
        _require(
            (row.get("requested_model"), row.get("served_model")) == (requested, served),
            f"Backbone identity differs: {backbone}/{condition}/{question_id}",
        )
        _require(
            (row.get("judge_requested_model"), row.get("judge_served_model")) == EXPECTED_JUDGE,
            f"Judge identity differs: {backbone}/{condition}/{question_id}",
        )
        key = (backbone, condition, question_id)
        _require(key not in keyed, f"Duplicate Stage C key: {key}")
        keyed.add(key)
        cells[(backbone, condition)] += 1

        category = row.get("category")
        _require(category in EXPECTED_CATEGORIES, f"Invalid category metadata: {question_id}")
        _require(row.get("category_name") == EXPECTED_CATEGORY_NAMES[int(category)], "Category name differs")
        categories[(backbone, condition)][int(category)] += 1
        if row.get("evidence_eligible") is True:
            evidence_categories[(backbone, condition)][int(category)] += 1

        metadata = (
            row.get("question_sha256"),
            row.get("global_position"),
            row.get("category"),
            row.get("category_name"),
            row.get("evidence_eligible"),
            tuple(row.get("gold_dia_ids", [])),
        )
        if question_id in question_metadata:
            _require(question_metadata[question_id] == metadata, f"Question metadata differs: {question_id}")
        else:
            question_metadata[question_id] = metadata

        label = row.get("judge_label")
        _require(label in {"correct", "partial", "incorrect"}, "Judge label differs")
        _require(row.get("strict_score") == {"correct": 1.0, "partial": 0.0, "incorrect": 0.0}[str(label)], "Strict mapping differs")
        _require(row.get("partial_indicator") == {"correct": 0, "partial": 1, "incorrect": 0}[str(label)], "Partial mapping differs")
        _require(row.get("soft_semantic_score") == {"correct": 1.0, "partial": 0.5, "incorrect": 0.0}[str(label)], "Soft mapping differs")
        for field in ("token_precision", "token_recall", "token_f1", "soft_semantic_score"):
            value = row.get(field)
            _require(isinstance(value, (int, float)) and not isinstance(value, bool), f"{field} is not numeric")
            _require(0.0 <= float(value) <= 1.0, f"{field} is outside [0,1]")
        if row.get("evidence_eligible") is True:
            _require(
                isinstance(row.get("evidence_recall"), (int, float))
                and 0.0 <= float(row["evidence_recall"]) <= 1.0
                and isinstance(row.get("evidence_any_hit"), bool)
                and isinstance(row.get("evidence_all_hit"), bool),
                "Eligible Evidence fields differ",
            )
        else:
            _require(
                row.get("evidence_recall") is None
                and row.get("evidence_any_hit") is None
                and row.get("evidence_all_hit") is None,
                "Ineligible Evidence fields must be null",
            )
        _require(row.get("elapsed_ms") is None and row.get("latency_available") is False, "Selective latency contract differs")

    expected_cells = {
        (backbone, condition): QUESTION_COUNT
        for backbone in BACKBONES
        for condition in STAGE_C_CONDITIONS
    }
    _require(dict(cells) == expected_cells, "Stage C cell counts differ")
    _require(
        all(dict(categories[cell]) == EXPECTED_CATEGORIES for cell in expected_cells),
        "Frozen category composition differs",
    )
    _require(
        all(dict(evidence_categories[cell]) == EXPECTED_EVIDENCE_CATEGORIES for cell in expected_cells),
        "Frozen Evidence-eligible category composition differs",
    )
    _require(len(question_metadata) == QUESTION_COUNT, "Stage C question count differs")
    ordered_questions = tuple(
        question_id
        for question_id, metadata in sorted(question_metadata.items(), key=lambda item: int(item[1][1]))
    )
    _require(
        tuple(int(question_metadata[qid][1]) for qid in ordered_questions) == tuple(range(1, QUESTION_COUNT + 1)),
        "Global question positions differ",
    )
    for backbone in BACKBONES:
        for condition in STAGE_C_CONDITIONS:
            ordered_cell = sorted(
                (row for row in rows if row["backbone_id"] == backbone and row["condition_id"] == condition),
                key=lambda row: int(row["global_position"]),
            )
            evidence_masks[(backbone, condition)] = tuple(
                str(row["question_id"]) for row in ordered_cell if row["evidence_eligible"]
            )
            multi_masks[(backbone, condition)] = tuple(
                str(row["question_id"])
                for row in ordered_cell
                if row["evidence_eligible"] and len(set(row["gold_dia_ids"])) > 1
            )
    _require(len(set(evidence_masks.values())) == 1, "Evidence eligibility mask differs across cells")
    evidence_mask = next(iter(evidence_masks.values()))
    _require(len(evidence_mask) == EVIDENCE_ELIGIBLE_COUNT, "Evidence denominator differs")
    _require(
        set(ordered_questions) - set(evidence_mask) == EXPECTED_INELIGIBLE_QUESTION_IDS,
        "Frozen Evidence-ineligible question IDs differ",
    )
    _require(len(set(multi_masks.values())) == 1, "Multi-gold-source mask differs across cells")
    _require(len(next(iter(multi_masks.values()))) == EXPECTED_MULTI_GOLD_SOURCE_COUNT, "Multi-source denominator differs")
    return {
        "input_rows": len(rows),
        "question_count": len(question_metadata),
        "cell_counts": {
            f"{backbone}/{condition}": cells[(backbone, condition)]
            for backbone in BACKBONES
            for condition in STAGE_C_CONDITIONS
        },
        "design_verified": True,
        "model_identities_verified": True,
        "judge_identity_verified": True,
        "category_composition_verified_without_analysis": True,
        "evidence_ineligible_question_ids": sorted(EXPECTED_INELIGIBLE_QUESTION_IDS),
        "answer_denominator": QUESTION_COUNT,
        "evidence_denominator": EVIDENCE_ELIGIBLE_COUNT,
        "multi_gold_source_denominator": EXPECTED_MULTI_GOLD_SOURCE_COUNT,
        "ordered_question_ids_sha256": sha256_bytes(canonical_json_bytes(list(ordered_questions))),
    }


def _index_rows(rows: Sequence[Mapping[str, Any]]) -> tuple[dict[tuple[str, str, str], Mapping[str, Any]], tuple[str, ...]]:
    index = {
        (str(row["backbone_id"]), str(row["condition_id"]), str(row["question_id"])): row
        for row in rows
    }
    qwen_e1 = sorted(
        (row for row in rows if row["backbone_id"] == "qwen" and row["condition_id"] == "E1"),
        key=lambda row: int(row["global_position"]),
    )
    return index, tuple(str(row["question_id"]) for row in qwen_e1)


def _all_condition_summaries(
    index: Mapping[tuple[str, str, str], Mapping[str, Any]],
    ordered_questions: Sequence[str],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for backbone in BACKBONES:
        for condition in STAGE_C_CONDITIONS:
            for spec in METRICS:
                cell = [index[(backbone, condition, question_id)] for question_id in ordered_questions]
                values = [_metric_value(row, spec) for row in cell if _row_in_scope(row, spec)]
                denominator = _expected_denominator(spec)
                _require(len(values) == denominator, "Condition-summary denominator differs")
                identity = {
                    "backbone_id": backbone,
                    "condition_id": condition,
                    "metric_id": spec.metric_id,
                    "denominator_scope": spec.scope,
                }
                rows.append(
                    {
                        "condition_summary_id": _id("stage-c-condition-", identity),
                        "protocol_version": STAGE_C_PROTOCOL_VERSION,
                        "backbone_id": backbone,
                        "answer_set_id": EXPECTED_ANSWER_SETS[backbone],
                        "condition_id": condition,
                        "storage_representation": EXPECTED_DESIGN[condition][0],
                        "retrieval_system": EXPECTED_DESIGN[condition][1],
                        "metric_family": spec.family,
                        "metric_id": spec.metric_id,
                        "metric_direction": _metric_direction_name(spec),
                        "denominator_scope": spec.scope,
                        "denominator": denominator,
                        "mean": _mean(values),
                        "median": _median(values),
                        "minimum": min(values),
                        "maximum": max(values),
                        "sum": math.fsum(values),
                        "comparison_status": "condition_summary",
                        "publication_role": "main_context",
                        "identification_scope": "descriptive_condition_level_summary",
                    }
                )
    return rows


def _contrast_register() -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for contrast in CONTRASTS:
        identity = {"contrast_id": contrast.contrast_id}
        output.append(
            {
                "contrast_register_id": _id("stage-c-contrast-", identity),
                "protocol_version": STAGE_C_PROTOCOL_VERSION,
                "contrast_id": contrast.contrast_id,
                "contrast_family": contrast.contrast_family,
                "baseline_condition": contrast.baseline_condition,
                "baseline_storage_representation": EXPECTED_DESIGN[contrast.baseline_condition][0],
                "baseline_retrieval_system": EXPECTED_DESIGN[contrast.baseline_condition][1],
                "target_condition": contrast.target_condition,
                "target_storage_representation": EXPECTED_DESIGN[contrast.target_condition][0],
                "target_retrieval_system": EXPECTED_DESIGN[contrast.target_condition][1],
                "difference_direction": "target_minus_baseline",
                "comparison_status": contrast.comparison_status,
                "publication_role": contrast.publication_role,
                "identification_scope": contrast.identification_scope,
            }
        )
    return output


def _comparison_fields(contrast: ContrastSpec) -> dict[str, str]:
    return {
        "comparison_status": contrast.comparison_status,
        "publication_role": contrast.publication_role,
        "identification_scope": contrast.identification_scope,
    }


def _paired_question_effects(
    index: Mapping[tuple[str, str, str], Mapping[str, Any]],
    ordered_questions: Sequence[str],
) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for backbone in BACKBONES:
        for contrast in CONTRASTS:
            for spec in METRICS:
                for question_id in ordered_questions:
                    baseline = index[(backbone, contrast.baseline_condition, question_id)]
                    target = index[(backbone, contrast.target_condition, question_id)]
                    _require(_row_in_scope(baseline, spec) == _row_in_scope(target, spec), "Paired scope differs")
                    if not _row_in_scope(baseline, spec):
                        continue
                    baseline_value = _metric_value(baseline, spec)
                    target_value = _metric_value(target, spec)
                    raw_difference = target_value - baseline_value
                    oriented_difference = spec.direction * raw_difference if spec.direction is not None else None
                    identity = {
                        "backbone_id": backbone,
                        "contrast_id": contrast.contrast_id,
                        "metric_id": spec.metric_id,
                        "question_id": question_id,
                    }
                    output.append(
                        {
                            "paired_effect_id": _id("stage-c-pair-", identity),
                            "protocol_version": STAGE_C_PROTOCOL_VERSION,
                            "backbone_id": backbone,
                            "answer_set_id": EXPECTED_ANSWER_SETS[backbone],
                            "contrast_id": contrast.contrast_id,
                            "contrast_family": contrast.contrast_family,
                            "baseline_condition": contrast.baseline_condition,
                            "target_condition": contrast.target_condition,
                            **_comparison_fields(contrast),
                            "question_id": question_id,
                            "global_position": int(baseline["global_position"]),
                            "evidence_eligible": bool(baseline["evidence_eligible"]),
                            "gold_source_count": len(set(baseline["gold_dia_ids"])),
                            "metric_family": spec.family,
                            "metric_id": spec.metric_id,
                            "metric_direction": _metric_direction_name(spec),
                            "denominator_scope": spec.scope,
                            "baseline_value": baseline_value,
                            "target_value": target_value,
                            "raw_difference": raw_difference,
                            "oriented_difference": oriented_difference,
                            "raw_state": _state(raw_difference),
                            "oriented_state": _oriented_state(oriented_difference),
                            "baseline_analysis_row_id": str(baseline["analysis_row_id"]),
                            "target_analysis_row_id": str(target["analysis_row_id"]),
                        }
                    )
    return output


def _aggregate_effects(paired_rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    groups: dict[tuple[str, str, str], list[Mapping[str, Any]]] = defaultdict(list)
    for row in paired_rows:
        groups[(str(row["backbone_id"]), str(row["contrast_id"]), str(row["metric_id"]))].append(row)
    output: list[dict[str, Any]] = []
    for backbone in BACKBONES:
        for contrast in CONTRASTS:
            for spec in METRICS:
                rows = sorted(groups[(backbone, contrast.contrast_id, spec.metric_id)], key=lambda row: int(row["global_position"]))
                denominator = _expected_denominator(spec)
                _require(len(rows) == denominator, "Aggregate denominator differs")
                baseline = [float(row["baseline_value"]) for row in rows]
                target = [float(row["target_value"]) for row in rows]
                differences = [float(row["raw_difference"]) for row in rows]
                raw = Counter(str(row["raw_state"]) for row in rows)
                oriented = Counter(str(row["oriented_state"]) for row in rows if row["oriented_state"] is not None)
                identity = {
                    "backbone_id": backbone,
                    "contrast_id": contrast.contrast_id,
                    "metric_id": spec.metric_id,
                }
                output.append(
                    {
                        "aggregate_effect_id": _id("stage-c-effect-", identity),
                        "protocol_version": STAGE_C_PROTOCOL_VERSION,
                        "backbone_id": backbone,
                        "answer_set_id": EXPECTED_ANSWER_SETS[backbone],
                        "contrast_id": contrast.contrast_id,
                        "contrast_family": contrast.contrast_family,
                        "baseline_condition": contrast.baseline_condition,
                        "target_condition": contrast.target_condition,
                        **_comparison_fields(contrast),
                        "metric_family": spec.family,
                        "metric_id": spec.metric_id,
                        "metric_direction": _metric_direction_name(spec),
                        "denominator_scope": spec.scope,
                        "denominator": denominator,
                        "baseline_mean": _mean(baseline),
                        "target_mean": _mean(target),
                        "mean_difference": _mean(differences),
                        "median_difference": _median(differences),
                        "minimum_difference": min(differences),
                        "maximum_difference": max(differences),
                        "increase_count": raw["increase"],
                        "same_count": raw["same"],
                        "decrease_count": raw["decrease"],
                        "win_count": oriented["win"] if spec.direction is not None else None,
                        "tie_count": oriented["tie"] if spec.direction is not None else None,
                        "loss_count": oriented["loss"] if spec.direction is not None else None,
                    }
                )
    return output


def _transitions(
    index: Mapping[tuple[str, str, str], Mapping[str, Any]],
    ordered_questions: Sequence[str],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    strict_output: list[dict[str, Any]] = []
    semantic_output: list[dict[str, Any]] = []
    labels = ("correct", "partial", "incorrect")
    strict_spec = (
        (False, True, "strict_not_correct_to_correct"),
        (True, False, "strict_correct_to_not_correct"),
        (True, True, "strict_unchanged_correct"),
        (False, False, "strict_unchanged_not_correct"),
    )
    for backbone in BACKBONES:
        for contrast in CONTRASTS:
            strict_counts: Counter[tuple[bool, bool]] = Counter()
            semantic_counts: Counter[tuple[str, str]] = Counter()
            for question_id in ordered_questions:
                baseline = index[(backbone, contrast.baseline_condition, question_id)]
                target = index[(backbone, contrast.target_condition, question_id)]
                strict_counts[(bool(baseline["strict_score"]), bool(target["strict_score"]))] += 1
                semantic_counts[(str(baseline["judge_label"]), str(target["judge_label"]))] += 1
            for baseline_correct, target_correct, transition_id in strict_spec:
                identity = {
                    "backbone_id": backbone,
                    "contrast_id": contrast.contrast_id,
                    "transition_id": transition_id,
                }
                strict_output.append(
                    {
                        "strict_transition_row_id": _id("stage-c-strict-transition-", identity),
                        "protocol_version": STAGE_C_PROTOCOL_VERSION,
                        "backbone_id": backbone,
                        "answer_set_id": EXPECTED_ANSWER_SETS[backbone],
                        "contrast_id": contrast.contrast_id,
                        "baseline_condition": contrast.baseline_condition,
                        "target_condition": contrast.target_condition,
                        **_comparison_fields(contrast),
                        "transition_id": transition_id,
                        "baseline_strict_correct": baseline_correct,
                        "target_strict_correct": target_correct,
                        "count": strict_counts[(baseline_correct, target_correct)],
                        "denominator": QUESTION_COUNT,
                    }
                )
            for baseline_label in labels:
                for target_label in labels:
                    identity = {
                        "backbone_id": backbone,
                        "contrast_id": contrast.contrast_id,
                        "baseline_label": baseline_label,
                        "target_label": target_label,
                    }
                    semantic_output.append(
                        {
                            "semantic_transition_row_id": _id("stage-c-semantic-transition-", identity),
                            "protocol_version": STAGE_C_PROTOCOL_VERSION,
                            "backbone_id": backbone,
                            "answer_set_id": EXPECTED_ANSWER_SETS[backbone],
                            "contrast_id": contrast.contrast_id,
                            "baseline_condition": contrast.baseline_condition,
                            "target_condition": contrast.target_condition,
                            **_comparison_fields(contrast),
                            "baseline_label": baseline_label,
                            "target_label": target_label,
                            "count": semantic_counts[(baseline_label, target_label)],
                            "denominator": QUESTION_COUNT,
                        }
                    )
    return strict_output, semantic_output


def _table_ready(
    aggregate_rows: Sequence[Mapping[str, Any]],
    *,
    contrasts: Sequence[ContrastSpec],
    table_id: str,
) -> list[dict[str, Any]]:
    aggregate_map = {
        (str(row["backbone_id"]), str(row["contrast_id"]), str(row["metric_id"])): row
        for row in aggregate_rows
    }
    output: list[dict[str, Any]] = []
    for backbone in BACKBONES:
        for contrast in contrasts:
            for metric_id in PRIMARY_TABLE_METRICS:
                aggregate = aggregate_map[(backbone, contrast.contrast_id, metric_id)]
                identity = {
                    "table_id": table_id,
                    "backbone_id": backbone,
                    "contrast_id": contrast.contrast_id,
                    "metric_id": metric_id,
                }
                output.append(
                    {
                        "table_row_id": _id("stage-c-table-", identity),
                        "protocol_version": STAGE_C_PROTOCOL_VERSION,
                        "table_id": table_id,
                        "backbone_id": backbone,
                        "answer_set_id": EXPECTED_ANSWER_SETS[backbone],
                        "contrast_id": contrast.contrast_id,
                        "baseline_condition": contrast.baseline_condition,
                        "target_condition": contrast.target_condition,
                        **_comparison_fields(contrast),
                        "metric_id": metric_id,
                        "denominator": aggregate["denominator"],
                        "baseline_mean": aggregate["baseline_mean"],
                        "target_mean": aggregate["target_mean"],
                        "mean_difference": aggregate["mean_difference"],
                        "win_count": aggregate["win_count"],
                        "tie_count": aggregate["tie_count"],
                        "loss_count": aggregate["loss_count"],
                    }
                )
    return output


def _validate_stage_b_summary_alignment(
    all_condition_rows: Sequence[Mapping[str, Any]],
    stage_b_rows: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    internal = {
        (str(row["backbone_id"]), str(row["condition_id"]), str(row["metric_id"])): row
        for row in all_condition_rows
        if row["condition_id"] in {"E1", "E2", "E3", "E4"}
    }
    official = {
        (str(row["backbone_id"]), str(row["condition_id"]), str(row["metric_id"])): row
        for row in stage_b_rows
    }
    _require(len(internal) == 104 and len(official) == 104, "Stage B condition-summary lineage shape differs")
    _require(set(internal) == set(official), "Stage B condition-summary keys differ")
    for key in sorted(internal):
        left = internal[key]
        right = official[key]
        _require(left["denominator_scope"] == right["denominator_scope"], f"Stage B scope differs: {key}")
        _require(int(left["denominator"]) == int(right["denominator"]), f"Stage B denominator differs: {key}")
        for field in ("mean", "median", "minimum", "maximum", "sum"):
            _require(_is_close(float(left[field]), float(right[field])), f"Stage B {field} differs: {key}")
    return {
        "aligned_rows": len(internal),
        "condition_ids": ["E1", "E2", "E3", "E4"],
        "metric_count": len(METRICS),
        "status": "passed",
    }


def _audit_tables(
    input_audit: Mapping[str, Any],
    tables: Mapping[str, Sequence[Mapping[str, Any]]],
    all_condition_rows: Sequence[Mapping[str, Any]],
    stage_b_alignment: Mapping[str, Any],
) -> dict[str, Any]:
    register = tables["contrast-register"]
    condition_rows = tables["condition-summaries"]
    paired_rows = tables["paired-question-effects"]
    aggregate_rows = tables["aggregate-effects"]
    strict_rows = tables["strict-transitions"]
    semantic_rows = tables["semantic-transitions"]
    main_rows = tables["table-5-3-data"]
    sensitivity_rows = tables["appendix-sensitivity-data"]

    expected_contrast_ids = [contrast.contrast_id for contrast in CONTRASTS]
    register_ids = [str(row["contrast_id"]) for row in register]
    aggregate_map = {
        (str(row["backbone_id"]), str(row["contrast_id"]), str(row["metric_id"])): row
        for row in aggregate_rows
    }
    condition_map = {
        (str(row["backbone_id"]), str(row["condition_id"]), str(row["metric_id"])): row
        for row in all_condition_rows
    }
    paired_groups: dict[tuple[str, str, str], list[Mapping[str, Any]]] = defaultdict(list)
    for row in paired_rows:
        paired_groups[(str(row["backbone_id"]), str(row["contrast_id"]), str(row["metric_id"]))].append(row)

    aggregate_recomputes = True
    endpoints_align = True
    state_totals = True
    neutral_unoriented = True
    metadata_exact = True
    for key, aggregate in aggregate_map.items():
        backbone, contrast_id, metric_id = key
        contrast = CONTRAST_BY_ID[contrast_id]
        spec = METRIC_BY_ID[metric_id]
        rows = paired_groups[key]
        denominator = _expected_denominator(spec)
        differences = [float(row["raw_difference"]) for row in rows]
        raw = Counter(str(row["raw_state"]) for row in rows)
        oriented = Counter(str(row["oriented_state"]) for row in rows if row["oriented_state"] is not None)
        aggregate_recomputes = aggregate_recomputes and (
            len(rows) == denominator
            and _is_close(float(aggregate["baseline_mean"]), _mean([float(row["baseline_value"]) for row in rows]))
            and _is_close(float(aggregate["target_mean"]), _mean([float(row["target_value"]) for row in rows]))
            and _is_close(float(aggregate["mean_difference"]), _mean(differences))
            and _is_close(float(aggregate["median_difference"]), _median(differences))
            and _is_close(
                float(aggregate["mean_difference"]),
                float(aggregate["target_mean"]) - float(aggregate["baseline_mean"]),
                tolerance=AGGREGATE_IDENTITY_TOLERANCE,
            )
            and int(aggregate["increase_count"]) == raw["increase"]
            and int(aggregate["same_count"]) == raw["same"]
            and int(aggregate["decrease_count"]) == raw["decrease"]
        )
        endpoints_align = endpoints_align and (
            _is_close(float(aggregate["baseline_mean"]), float(condition_map[(backbone, contrast.baseline_condition, metric_id)]["mean"]))
            and _is_close(float(aggregate["target_mean"]), float(condition_map[(backbone, contrast.target_condition, metric_id)]["mean"]))
        )
        state_totals = state_totals and raw["increase"] + raw["same"] + raw["decrease"] == denominator
        expected_metadata = _comparison_fields(contrast)
        metadata_exact = metadata_exact and all(
            all(row[field] == value for field, value in expected_metadata.items())
            for row in [aggregate, *rows]
        )
        if spec.direction is None:
            neutral_unoriented = neutral_unoriented and (
                aggregate["win_count"] is None
                and aggregate["tie_count"] is None
                and aggregate["loss_count"] is None
                and all(row["oriented_difference"] is None and row["oriented_state"] is None for row in rows)
            )
        else:
            state_totals = state_totals and (
                int(aggregate["win_count"]) == oriented["win"]
                and int(aggregate["tie_count"]) == oriented["tie"]
                and int(aggregate["loss_count"]) == oriented["loss"]
                and oriented["win"] + oriented["tie"] + oriented["loss"] == denominator
            )

    strict_alignment = True
    semantic_fold_alignment = True
    transition_metadata_exact = True
    labels = ("correct", "partial", "incorrect")
    for backbone in BACKBONES:
        for contrast in CONTRASTS:
            strict_subset = [row for row in strict_rows if row["backbone_id"] == backbone and row["contrast_id"] == contrast.contrast_id]
            semantic_subset = [row for row in semantic_rows if row["backbone_id"] == backbone and row["contrast_id"] == contrast.contrast_id]
            strict_counts = {str(row["transition_id"]): int(row["count"]) for row in strict_subset}
            matrix = {(str(row["baseline_label"]), str(row["target_label"])): int(row["count"]) for row in semantic_subset}
            strict_aggregate = aggregate_map[(backbone, contrast.contrast_id, "strict_accuracy")]
            strict_alignment = strict_alignment and (
                sum(strict_counts.values()) == QUESTION_COUNT
                and strict_counts["strict_not_correct_to_correct"] == strict_aggregate["win_count"]
                and strict_counts["strict_correct_to_not_correct"] == strict_aggregate["loss_count"]
                and strict_counts["strict_unchanged_correct"] + strict_counts["strict_unchanged_not_correct"] == strict_aggregate["tie_count"]
            )
            semantic_fold_alignment = semantic_fold_alignment and (
                sum(matrix.values()) == QUESTION_COUNT
                and matrix[("correct", "correct")] == strict_counts["strict_unchanged_correct"]
                and sum(matrix[(label, "correct")] for label in labels if label != "correct") == strict_counts["strict_not_correct_to_correct"]
                and sum(matrix[("correct", label)] for label in labels if label != "correct") == strict_counts["strict_correct_to_not_correct"]
                and sum(matrix[(left, right)] for left in labels if left != "correct" for right in labels if right != "correct") == strict_counts["strict_unchanged_not_correct"]
            )
            expected_metadata = _comparison_fields(contrast)
            transition_metadata_exact = transition_metadata_exact and all(
                all(row[field] == value for field, value in expected_metadata.items())
                for row in [*strict_subset, *semantic_subset]
            )

    def table_ready_aligned(rows: Sequence[Mapping[str, Any]], contrasts: Sequence[ContrastSpec]) -> bool:
        allowed = {contrast.contrast_id for contrast in contrasts}
        if {str(row["contrast_id"]) for row in rows} != allowed:
            return False
        for row in rows:
            key = (str(row["backbone_id"]), str(row["contrast_id"]), str(row["metric_id"]))
            aggregate = aggregate_map[key]
            contrast = CONTRAST_BY_ID[str(row["contrast_id"])]
            if row["metric_id"] not in PRIMARY_TABLE_METRICS:
                return False
            if not all(row[field] == value for field, value in _comparison_fields(contrast).items()):
                return False
            for field in ("baseline_mean", "target_mean", "mean_difference"):
                if not _is_close(float(row[field]), float(aggregate[field])):
                    return False
            if int(row["denominator"]) != int(aggregate["denominator"]):
                return False
        return True

    id_fields = {
        "contrast-register": "contrast_register_id",
        "condition-summaries": "condition_summary_id",
        "paired-question-effects": "paired_effect_id",
        "aggregate-effects": "aggregate_effect_id",
        "strict-transitions": "strict_transition_row_id",
        "semantic-transitions": "semantic_transition_row_id",
        "table-5-3-data": "table_row_id",
        "appendix-sensitivity-data": "table_row_id",
    }
    all_ids = [str(row[id_fields[name]]) for name, rows in tables.items() for row in rows]
    forbidden_analysis_fields = ("category", "bootstrap", "interaction")
    no_forbidden_fields = all(
        not any(fragment in field.lower() for fragment in forbidden_analysis_fields)
        for rows in tables.values()
        for row in rows
        for field in row
    )
    checks = {
        "stage_a_rq1_input_rows_720": input_audit["input_rows"] == EXPECTED_STAGE_C_ROWS,
        "twelve_cells_of_60": set(input_audit["cell_counts"].values()) == {QUESTION_COUNT} and len(input_audit["cell_counts"]) == 12,
        "answer_denominator_60": input_audit["answer_denominator"] == QUESTION_COUNT,
        "evidence_denominator_58": input_audit["evidence_denominator"] == EVIDENCE_ELIGIBLE_COUNT,
        "multi_gold_source_denominator_19": input_audit["multi_gold_source_denominator"] == EXPECTED_MULTI_GOLD_SOURCE_COUNT,
        "stage_b_lineage_summary_alignment_104": stage_b_alignment.get("status") == "passed" and stage_b_alignment.get("aligned_rows") == 104,
        "contrast_register_exact_five": register_ids == expected_contrast_ids,
        "condition_summaries_e5_e6_only_52": len(condition_rows) == 52 and {row["condition_id"] for row in condition_rows} == {"E5", "E6"},
        "paired_question_rows_6490": len(paired_rows) == EXPECTED_PAIRED_ROWS,
        "aggregate_effect_rows_130": len(aggregate_rows) == EXPECTED_AGGREGATE_ROWS,
        "strict_transition_rows_40": len(strict_rows) == EXPECTED_STRICT_TRANSITION_ROWS,
        "semantic_transition_rows_90": len(semantic_rows) == EXPECTED_SEMANTIC_TRANSITION_ROWS,
        "aggregate_rows_recompute_from_pairs": aggregate_recomputes,
        "aggregate_endpoint_means_align": endpoints_align,
        "paired_state_totals_match_denominators": state_totals,
        "neutral_metrics_are_unoriented": neutral_unoriented,
        "comparison_metadata_exact": metadata_exact and transition_metadata_exact,
        "strict_transitions_align_with_strict_effects": strict_alignment,
        "semantic_transitions_fold_to_strict": semantic_fold_alignment,
        "main_table_rows_24": len(main_rows) == 24,
        "main_table_exact_three_contrasts": table_ready_aligned(main_rows, MAIN_CONTRASTS),
        "sensitivity_table_rows_16": len(sensitivity_rows) == 16,
        "sensitivity_table_exact_two_contrasts": table_ready_aligned(sensitivity_rows, SENSITIVITY_CONTRASTS),
        "main_and_sensitivity_disjoint": {row["contrast_id"] for row in main_rows}.isdisjoint({row["contrast_id"] for row in sensitivity_rows}),
        "artifact_row_ids_unique": len(all_ids) == len(set(all_ids)),
        "no_text_bearing_fields": _no_text_bearing_fields(tables),
        "no_category_bootstrap_or_interaction_fields": no_forbidden_fields,
        "no_pooled_backbone_effects": all(
            row.get("backbone_id") in BACKBONES
            for name, rows in tables.items()
            if name != "contrast-register"
            for row in rows
        ),
        "only_fixed_contrast_endpoints": all(
            row.get("baseline_condition") == CONTRAST_BY_ID[str(row["contrast_id"])].baseline_condition
            and row.get("target_condition") == CONTRAST_BY_ID[str(row["contrast_id"])].target_condition
            for name, rows in tables.items()
            if name != "condition-summaries"
            for row in rows
            if "contrast_id" in row
        ),
    }
    _require(all(checks.values()), "Stage C table audit failed")
    return {
        "checks": checks,
        "table_rows": {name: len(rows) for name, rows in tables.items()},
        "answer_denominator": QUESTION_COUNT,
        "evidence_denominator": EVIDENCE_ELIGIBLE_COUNT,
        "multi_gold_source_denominator": EXPECTED_MULTI_GOLD_SOURCE_COUNT,
        "contrast_count": len(CONTRASTS),
        "effect_units": len(BACKBONES) * len(CONTRASTS),
        "main_effect_units": len(BACKBONES) * len(MAIN_CONTRASTS),
        "sensitivity_effect_units": len(BACKBONES) * len(SENSITIVITY_CONTRASTS),
    }


def _compute_stage_c(
    stage_a_dir: Path,
    stage_b_dir: Path,
) -> tuple[dict[str, list[dict[str, Any]]], dict[str, Any], dict[str, Any]]:
    input_rows, stage_b_summaries, provenance = _load_inputs(stage_a_dir, stage_b_dir)
    input_audit = _validate_input(input_rows)
    index, ordered_questions = _index_rows(input_rows)
    all_condition_rows = _all_condition_summaries(index, ordered_questions)
    stage_b_alignment = _validate_stage_b_summary_alignment(all_condition_rows, stage_b_summaries)
    condition_rows = [row for row in all_condition_rows if row["condition_id"] in STAGE_C_SUMMARY_CONDITIONS]
    paired_rows = _paired_question_effects(index, ordered_questions)
    aggregate_rows = _aggregate_effects(paired_rows)
    strict_rows, semantic_rows = _transitions(index, ordered_questions)
    tables = {
        "contrast-register": _contrast_register(),
        "condition-summaries": condition_rows,
        "paired-question-effects": paired_rows,
        "aggregate-effects": aggregate_rows,
        "strict-transitions": strict_rows,
        "semantic-transitions": semantic_rows,
        "table-5-3-data": _table_ready(aggregate_rows, contrasts=MAIN_CONTRASTS, table_id="Table 5.3"),
        "appendix-sensitivity-data": _table_ready(aggregate_rows, contrasts=SENSITIVITY_CONTRASTS, table_id="Appendix Stage C sensitivity"),
    }
    table_audit = _audit_tables(input_audit, tables, all_condition_rows, stage_b_alignment)
    return tables, provenance, {
        "input_audit": input_audit,
        "stage_b_summary_alignment": stage_b_alignment,
        "table_audit": table_audit,
    }


def _readme() -> str:
    return """# Chapter 5 Stage C: curated-memory comparisons

This directory contains the audited within-backbone Stage C comparisons for
S3 Agent-Curated Memory. Five target-minus-baseline contrasts are fixed in
`contrast-register`: one core S3 access-system contrast, two main descriptive
complete-system anchors, and two appendix sensitivity anchors.

Answer metrics use all 60 unified Main-60 questions. Evidence metrics use the
fixed 58-question Evidence-eligible mask. Multi-gold-source metrics use the
frozen 19-question subset with more than one distinct gold dialogue-turn ID.
Only E5 and E6 condition summaries are published here. E1--E4 endpoint means
are independently recomputed from Stage A and checked against the formal Stage
B condition summaries before any Stage C output is published.

Partial Rate and EvidenceBundle length are neutral descriptive metrics. They
therefore receive increase/same/decrease counts but no quality-oriented
win/tie/loss labels. Strict transitions treat both `partial` and `incorrect`
as `not_correct`; the separate 3x3 semantic matrix preserves all three labels.

No bootstrap interval, interaction, category effect, pooled-backbone effect,
E7, Full Context, cost, or error-stage analysis is computed in Stage C. No API
is called, no formal source result is modified, and no question, answer,
Evidence text, or Judge rationale is copied into these artifacts.
"""


def _field_schema(tables: Mapping[str, Sequence[Mapping[str, Any]]]) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "protocol_version": STAGE_C_PROTOCOL_VERSION,
        "row_key_policy": "artifact-specific deterministic SHA-256 identifiers",
        "difference_direction": "target_minus_baseline",
        "tie_tolerance": TIE_TOLERANCE,
        "answer_denominator": QUESTION_COUNT,
        "evidence_denominator": EVIDENCE_ELIGIBLE_COUNT,
        "multi_gold_source_denominator": EXPECTED_MULTI_GOLD_SOURCE_COUNT,
        "tables": {
            name: {"row_count": len(rows), "fields": list(rows[0]) if rows else []}
            for name, rows in tables.items()
        },
    }


def _source_manifest(
    repo_root: Path,
    stage_a_dir: Path,
    stage_b_dir: Path,
    provenance: Mapping[str, Any],
    input_audit: Mapping[str, Any],
) -> dict[str, Any]:
    body = {
        "schema_version": 1,
        "protocol_version": STAGE_C_PROTOCOL_VERSION,
        "scope": "unified Main-60 S3 curated-memory paired comparisons",
        "stage_a_directory": _relative(repo_root, stage_a_dir),
        "stage_b_directory": _relative(repo_root, stage_b_dir),
        **dict(provenance),
        "input_rows": EXPECTED_STAGE_C_ROWS,
        "backbones": list(BACKBONES),
        "conditions": list(STAGE_C_CONDITIONS),
        "published_condition_summaries": list(STAGE_C_SUMMARY_CONDITIONS),
        "contrast_ids": [contrast.contrast_id for contrast in CONTRASTS],
        "answer_denominator": QUESTION_COUNT,
        "evidence_denominator": EVIDENCE_ELIGIBLE_COUNT,
        "multi_gold_source_denominator": EXPECTED_MULTI_GOLD_SOURCE_COUNT,
        "input_question_order_sha256": input_audit["ordered_question_ids_sha256"],
        "difference_direction": "target_minus_baseline",
        "bootstrap_computed": False,
        "interaction_computed": False,
        "category_effect_computed": False,
        "evidence_to_answer_conversion_computed": False,
        "process_analysis_computed": False,
        "cost_analysis_computed": False,
        "trace_review_computed": False,
        "cross_backbone_effect_computed": False,
        "stage_d_computed": False,
        "e7_computed": False,
        "full_context_computed": False,
        "final_rq1_conclusion_computed": False,
        "no_api_calls": True,
        "formal_source_mutation": False,
    }
    return {"source_manifest_id": "stage-c-sources-" + sha256_bytes(canonical_json_bytes(body)), **body}


def _artifact_payloads(
    tables: Mapping[str, Sequence[Mapping[str, Any]]],
    source_manifest: Mapping[str, Any],
) -> dict[str, bytes]:
    payloads: dict[str, bytes] = {
        "README.md": _readme().encode("utf-8"),
        "schema.json": canonical_json_bytes(_field_schema(tables)) + b"\n",
        "source-manifest.json": canonical_json_bytes(dict(source_manifest)) + b"\n",
    }
    for name, rows in tables.items():
        payloads[f"{name}.jsonl"] = _jsonl_payload(rows)
        payloads[f"{name}.csv"] = _csv_payload(rows)
    return payloads


def _audit_body(
    audits: Mapping[str, Any],
    source_manifest: Mapping[str, Any],
    provenance: Mapping[str, Any],
    output_hashes: Mapping[str, str],
) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "protocol_version": STAGE_C_PROTOCOL_VERSION,
        "status": "passed",
        "scope": "unified Main-60 S3 curated-memory paired comparisons",
        "no_api_calls": True,
        "formal_source_mutation": False,
        "bootstrap_computed": False,
        "interaction_computed": False,
        "category_effect_computed": False,
        "evidence_to_answer_conversion_computed": False,
        "process_analysis_computed": False,
        "cost_analysis_computed": False,
        "trace_review_computed": False,
        "cross_backbone_effect_computed": False,
        "stage_d_computed": False,
        "stage_d_or_later_computed": False,
        "e7_computed": False,
        "full_context_computed": False,
        "final_rq1_conclusion_computed": False,
        "input_audit": audits["input_audit"],
        "stage_b_summary_alignment": audits["stage_b_summary_alignment"],
        "table_audit": audits["table_audit"],
        "source_manifest_id": source_manifest["source_manifest_id"],
        "stage_a_audit_id": provenance["stage_a_audit_id"],
        "stage_b_audit_id": provenance["stage_b_audit_id"],
        "output_sha256": dict(output_hashes),
    }


def _marker_body(audit: Mapping[str, Any], audit_sha256: str) -> dict[str, Any]:
    return {
        "status": "passed",
        "protocol_version": STAGE_C_PROTOCOL_VERSION,
        "audit_id": audit["audit_id"],
        "audit_sha256": audit_sha256,
        "input_rows": EXPECTED_STAGE_C_ROWS,
        "question_count": QUESTION_COUNT,
        "answer_denominator": QUESTION_COUNT,
        "evidence_denominator": EVIDENCE_ELIGIBLE_COUNT,
        "multi_gold_source_denominator": EXPECTED_MULTI_GOLD_SOURCE_COUNT,
        "contrast_count": len(CONTRASTS),
        "effect_units": len(BACKBONES) * len(CONTRASTS),
        "bootstrap_computed": False,
    }


def build_stage_c(
    *,
    repo_root: Path,
    stage_a_dir: Path,
    stage_b_dir: Path,
    output_dir: Path,
) -> dict[str, Any]:
    root = repo_root.resolve()
    stage_a = stage_a_dir.resolve()
    stage_b = stage_b_dir.resolve()
    destination = output_dir.resolve()
    _require(root.is_dir() and not root.is_symlink(), "Repository root is unsafe")
    _require(stage_a.is_dir() and not stage_a.is_symlink(), "Stage A directory is unsafe")
    _require(stage_b.is_dir() and not stage_b.is_symlink(), "Stage B directory is unsafe")
    _require(stage_a == (root / "artifacts/chapter5-main60-analysis-v1/stage-a").resolve(), "Stage A is not at the frozen repository location")
    _require(stage_b == (root / "artifacts/chapter5-main60-analysis-v1/stage-b").resolve(), "Stage B is not at the frozen repository location")
    _require(not destination.exists() and not destination.is_symlink(), "Stage C output already exists")

    tables, provenance, audits = _compute_stage_c(stage_a, stage_b)
    source_manifest = _source_manifest(root, stage_a, stage_b, provenance, audits["input_audit"])
    parent = destination.parent
    parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=f".{destination.name}.in-progress-", dir=parent))
    try:
        payloads = _artifact_payloads(tables, source_manifest)
        for name, payload in payloads.items():
            _write(temporary / name, payload)
        output_hashes = {name: _sha256_file(temporary / name) for name in sorted(payloads)}
        body = _audit_body(audits, source_manifest, provenance, output_hashes)
        audit = {"audit_id": "stage-c-audit-" + sha256_bytes(canonical_json_bytes(body)), **body}
        _write(temporary / "audit.json", canonical_json_bytes(audit) + b"\n")
        marker = _marker_body(audit, _sha256_file(temporary / "audit.json"))
        _write(temporary / "STAGE-C.PASSED", canonical_json_bytes(marker) + b"\n")

        prepublish = audit_stage_c_output(
            stage_a_dir=stage_a,
            stage_b_dir=stage_b,
            output_dir=temporary,
        )
        _require(prepublish.get("status") == "passed", "Stage C pre-publication audit failed")
        _require(not destination.exists(), "Stage C output appeared during the build")
        os.rename(temporary, destination)
        descriptor = os.open(parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
    except Exception:
        shutil.rmtree(temporary, ignore_errors=True)
        raise
    return audit_stage_c_output(stage_a_dir=stage_a, stage_b_dir=stage_b, output_dir=destination)


def audit_stage_c_output(
    *,
    stage_a_dir: Path,
    stage_b_dir: Path,
    output_dir: Path,
) -> dict[str, Any]:
    stage_a = stage_a_dir.resolve()
    stage_b = stage_b_dir.resolve()
    output_root = output_dir.resolve()
    _require(stage_a.is_dir() and not stage_a.is_symlink(), "Stage A directory is unsafe")
    _require(stage_b.is_dir() and not stage_b.is_symlink(), "Stage B directory is unsafe")
    _require(output_root.is_dir() and not output_root.is_symlink(), "Stage C output directory is unsafe")
    repo_root = stage_a.parents[2]
    _require(stage_a == (repo_root / "artifacts/chapter5-main60-analysis-v1/stage-a").resolve(), "Stage A is not at the frozen repository location")
    _require(stage_b == (repo_root / "artifacts/chapter5-main60-analysis-v1/stage-b").resolve(), "Stage B is not at the frozen repository location")

    tables, provenance, audits = _compute_stage_c(stage_a, stage_b)
    expected_manifest = _source_manifest(repo_root, stage_a, stage_b, provenance, audits["input_audit"])
    expected_payloads = _artifact_payloads(tables, expected_manifest)
    expected_output_hashes = {
        name: hashlib.sha256(payload).hexdigest() for name, payload in sorted(expected_payloads.items())
    }
    expected_body = _audit_body(audits, expected_manifest, provenance, expected_output_hashes)
    expected_audit = {
        "audit_id": "stage-c-audit-" + sha256_bytes(canonical_json_bytes(expected_body)),
        **expected_body,
    }
    expected_audit_payload = canonical_json_bytes(expected_audit) + b"\n"
    expected_marker = _marker_body(expected_audit, hashlib.sha256(expected_audit_payload).hexdigest())
    expected_marker_payload = canonical_json_bytes(expected_marker) + b"\n"
    expected_names = set(expected_payloads) | {"audit.json", "STAGE-C.PASSED"}

    entries = list(output_root.iterdir())
    _require(all(entry.is_file() and not entry.is_symlink() for entry in entries), "Stage C output contains a non-regular entry")
    _require({entry.name for entry in entries} == expected_names, "Stage C output file set differs")
    for name, expected_payload in expected_payloads.items():
        _require((output_root / name).read_bytes() == expected_payload, f"Stage C bytes differ: {name}")
    _require((output_root / "audit.json").read_bytes() == expected_audit_payload, "Stage C audit bytes differ")
    _require((output_root / "STAGE-C.PASSED").read_bytes() == expected_marker_payload, "Stage C marker bytes differ")

    audit = _read_json(output_root / "audit.json")
    marker = _read_json(output_root / "STAGE-C.PASSED")
    audit_body = {key: value for key, value in audit.items() if key != "audit_id"}
    _require(audit.get("audit_id") == "stage-c-audit-" + sha256_bytes(canonical_json_bytes(audit_body)), "Stage C audit ID does not recompute")
    _require(audit == expected_audit, "Stage C audit differs from independent recomputation")
    _require(marker == expected_marker, "Stage C marker differs from independent recomputation")
    for name, digest in expected_output_hashes.items():
        _require(_sha256_file(output_root / name) == digest, f"Stage C output hash differs: {name}")

    return {
        "status": "passed",
        "protocol_version": STAGE_C_PROTOCOL_VERSION,
        "audit_id": expected_audit["audit_id"],
        "input_rows": EXPECTED_STAGE_C_ROWS,
        "question_count": QUESTION_COUNT,
        "contrast_count": len(CONTRASTS),
        "effect_units": len(BACKBONES) * len(CONTRASTS),
        "table_rows": audits["table_audit"]["table_rows"],
        "bootstrap_computed": False,
        "interaction_computed": False,
        "category_effect_computed": False,
        "output_dir": str(output_root),
        "no_api_calls": True,
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build or audit Chapter 5 Stage C artifacts")
    parser.add_argument("command", choices=("build", "audit"))
    parser.add_argument("--repo-root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--stage-a-dir", type=Path, required=True)
    parser.add_argument("--stage-b-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    return parser


def main(argv: list[str] | None = None) -> None:
    args = _parser().parse_args(argv)
    if args.command == "build":
        result = build_stage_c(
            repo_root=args.repo_root,
            stage_a_dir=args.stage_a_dir,
            stage_b_dir=args.stage_b_dir,
            output_dir=args.output_dir,
        )
    else:
        result = audit_stage_c_output(
            stage_a_dir=args.stage_a_dir,
            stage_b_dir=args.stage_b_dir,
            output_dir=args.output_dir,
        )
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
