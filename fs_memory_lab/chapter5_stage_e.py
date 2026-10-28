"""Build the final, auditable Chapter 5 RQ1 Stage E artifact.

Stage E is a reconciliation and publication gate.  It does not recompute the
question-level experiment, add a new bootstrap, or write report prose.  Its
authoritative numerical inputs are the frozen Stage B, C, and final Stage D
artifacts.  Stage A is checked only as their common lineage root.  The one
additional source is the formal S3 manifest, from which a clearly labelled
one-time construction-cost row is copied.

The published artifact fixes the 16 within-backbone main-text result units,
their target-minus-baseline directions, the 60/58/19 denominator contract,
the pre-declared bootstrap set, and the machine-readable inputs for the RQ1
tables and figure.  E7, Full Context, cross-backbone inference, a global error
census, Pareto analysis, and system recommendation are deliberately absent.
"""

from __future__ import annotations

import argparse
import csv
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

from .chapter5_stage_b import (
    BACKBONES,
    EXPECTED_CATEGORIES,
    EXPECTED_EVIDENCE_CATEGORIES,
    EXPECTED_MULTI_GOLD_SOURCE_COUNT,
    EVIDENCE_ELIGIBLE_COUNT,
    QUESTION_COUNT,
    TIE_TOLERANCE,
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


STAGE_E_PROTOCOL_VERSION = "chapter5-main60-stage-e-rq1-v1"

EXPECTED_STAGE_A_AUDIT_ID = (
    "stage-a-audit-5f55ec411f097df7206fdae5e71742641aa8868b4128ac32262f034877a1d7f3"
)
EXPECTED_STAGE_B_AUDIT_ID = (
    "stage-b-audit-2c5061c3db5cba00f099648963eaa2175d1136954e4cf673720423e7ffed6932"
)
EXPECTED_STAGE_C_AUDIT_ID = (
    "stage-c-audit-a199de52d8b0011d837334e6dbf37bbfac446653753b5b74a35732ae32da1a31"
)
EXPECTED_STAGE_D_AUTO_AUDIT_ID = (
    "stage-d-auto-audit-9cfae91b0639df31b427d2052798dfe30e0f5cb8b41c9996ae75448e6fdd4a4f"
)
EXPECTED_STAGE_D_FINAL_AUDIT_ID = (
    "stage-d-final-audit-9f23da2369af468867b7f6ffdbdc040ebee67fac59820d59f0763a3ccd132640"
)

EXPECTED_FROZEN_SHA256 = {
    "stage_a_audit": "39aee6ea88c92df547cc98f7b6b343415a558d31a354184e30f0d36acc331966",
    "stage_a_marker": "f4b3aa6f80d2ee7bc4eb9682e37ec85780d4f37a15b22ef65eb78e46ee6f3e34",
    "stage_b_audit": "67b638bccad3f664a8eec9f0e9f11554f777c336888c95d0594bbdb96d11e526",
    "stage_b_marker": "b137218da5cae7f2458dabf3322d6a88be6b616dcd57df6210cda02e0eabbfa2",
    "stage_c_audit": "fef87f523a6850c0fd1a7940a1aceb526e2c94f6ff3722d9b400c49ea063ea5a",
    "stage_c_marker": "670b4f7161d2ab871a1af756dcbd6b55715f10c834adb6f4a1b718ce3f9c395c",
    "stage_d_auto_audit": "234323fbc22a39b51044d50866ff7b1e3b60acb1b8aad3622d2ddac942ba57e9",
    "stage_d_final_audit": "3244cc96a43af998217730964bc41613151819e57f6aae413f808e0d6fc7c2f0",
    "stage_d_marker": "9f55dec6e0979483aa8da1e08c7848f8c7bcf3b094f13a6e30e0d1ea6868deeb",
    "s3_manifest": "70fb5ad56ff11bb849ce60b193cd6db29be601e613ca3afb76aac336e3b36e00",
}

EXPECTED_SOURCE_MANIFEST_IDS = {
    "stage_a": "stage-a-sources-90efa256f7981450cf38503912406a1e30766e8440b443899cab953fe9fece3c",
    "stage_b": "stage-b-sources-430f42b4398f2859091ad42f74000e3b6f712ed2c7c43606fc3d318afa1b6686",
    "stage_c": "stage-c-sources-83a0e867422117fc9b92d14da11d960b5faf8c308cfb11d0d3bc49c47159455e",
    "stage_d": "stage-d-auto-sources-0526c3b483787ff99c4df43733e2ff21775179d159b9e0f1c9581388f9ecf5cc",
}

INTERACTION_ID = "storage_retrieval_did_e4_e2_minus_e3_e1"
STAGE_B_INTERACTION_ID = "storage_retrieval_interaction"
PRIMARY_METRICS = (
    "token_precision",
    "token_recall",
    "token_f1",
    "strict_accuracy",
    "soft_semantic_score",
    "evidence_recall",
)
BOOTSTRAP_METRICS = ("token_f1", "strict_accuracy", "soft_semantic_score")
STRICT_TRANSITIONS = (
    "strict_not_correct_to_correct",
    "strict_correct_to_not_correct",
    "strict_unchanged_correct",
    "strict_unchanged_not_correct",
)
SENSITIVITY_IDS = {
    "curated_vs_flat_r1_e5_minus_e1",
    "curated_adapted_vs_flat_raw_e6_minus_e2",
}


@dataclass(frozen=True)
class ResultSpec:
    comparison_id: str
    source_effect_id: str
    source_stage: str
    comparison_type: str
    baseline_condition: str | None
    target_condition: str | None
    effect_status: str
    publication_role: str
    section_id: str
    effect_order: int
    short_code: str
    display_formula: str
    identification_scope: str


RESULT_SPECS = (
    ResultSpec(
        "storage_r1_e3_minus_e1", "storage_r1_e3_minus_e1", "stage_b", "simple",
        "E1", "E3", "core_effect", "main_core", "5.2.1", 1, "STORAGE-R1",
        "E3 - E1",
        "Raw-memory storage organisation effect with the complete R1 retrieval system fixed.",
    ),
    ResultSpec(
        "storage_r2_e4_minus_e2", "storage_r2_e4_minus_e2", "stage_b", "simple",
        "E2", "E4", "core_effect", "main_core", "5.2.1", 2, "STORAGE-R2",
        "E4 - E2",
        "Raw-memory storage organisation effect with the complete R2 retrieval system fixed.",
    ),
    ResultSpec(
        "retrieval_s1_e2_minus_e1", "retrieval_s1_e2_minus_e1", "stage_b", "simple",
        "E1", "E2", "core_effect", "main_core", "5.2.2", 3, "RETRIEVAL-S1",
        "E2 - E1",
        "Complete R2-versus-R1 retrieval-system effect with the S1 raw store fixed.",
    ),
    ResultSpec(
        "retrieval_s2_e4_minus_e3", "retrieval_s2_e4_minus_e3", "stage_b", "simple",
        "E3", "E4", "core_effect", "main_core", "5.2.2", 4, "RETRIEVAL-S2",
        "E4 - E3",
        "Complete R2-versus-R1 retrieval-system effect with the S2 raw store fixed.",
    ),
    ResultSpec(
        INTERACTION_ID, STAGE_B_INTERACTION_ID, "stage_b", "interaction",
        None, None, "core_effect", "main_core_interaction", "5.2.3", 5, "INTERACTION",
        "(E4 - E2) - (E3 - E1)",
        "Within-backbone storage-by-retrieval difference in differences; positive means S2 is more favourable under R2 than under R1.",
    ),
    ResultSpec(
        "curated_access_e6_minus_e5", "curated_access_e6_minus_e5", "stage_c", "simple",
        "E5", "E6", "core_effect", "main_core", "5.2.4", 6, "S3-ACCESS",
        "E6 - E5",
        "S3 is fixed; this is the complete R3-versus-R1 access-system effect, not an isolated retrieval component.",
    ),
    ResultSpec(
        "curated_vs_foldered_r1_e5_minus_e3", "curated_vs_foldered_r1_e5_minus_e3",
        "stage_c", "simple", "E3", "E5", "descriptive_complete_system_anchor",
        "main_descriptive", "5.2.4", 7, "S3-VS-S2-R1", "E5 - E3",
        "R1 is fixed, but S2-to-S3 changes wording, granularity, organisation, and provenance; this is not a pure curation effect.",
    ),
    ResultSpec(
        "curated_adapted_vs_foldered_raw_e6_minus_e4",
        "curated_adapted_vs_foldered_raw_e6_minus_e4", "stage_c", "simple", "E4", "E6",
        "descriptive_complete_system_anchor", "main_descriptive", "5.2.4", 8,
        "S3R3-VS-S2R2", "E6 - E4",
        "S2+R2 versus S3+R3 changes representation and retrieval together; this is a complete-system comparison.",
    ),
)
RESULT_SPEC_BY_ID = {spec.comparison_id: spec for spec in RESULT_SPECS}
MAIN_SIMPLE_IDS = {spec.comparison_id for spec in RESULT_SPECS if spec.comparison_type == "simple"}


def _id(prefix: str, body: Mapping[str, Any]) -> str:
    return prefix + sha256_bytes(canonical_json_bytes(dict(body)))


def _row_sha256(row: Mapping[str, Any]) -> str:
    return sha256_bytes(canonical_json_bytes(dict(row)))


def _uniform_rows(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Return rows with one deterministic union schema for CSV publication."""

    fields: list[str] = []
    seen: set[str] = set()
    for row in rows:
        for field in row:
            if field not in seen:
                seen.add(field)
                fields.append(field)
    return [{field: row.get(field) for field in fields} for row in rows]


def _read_jsonl_in_csv_field_order(jsonl_path: Path, csv_path: Path) -> list[dict[str, Any]]:
    """Load JSONL values while retaining the frozen companion CSV column order."""

    rows = _read_jsonl(jsonl_path)
    _require(csv_path.is_file() and not csv_path.is_symlink(), f"Unsafe or missing frozen CSV: {csv_path}")
    with csv_path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.reader(handle)
        try:
            fields = next(reader)
        except StopIteration:
            _require(False, f"Empty frozen CSV: {csv_path}")
            fields = []  # pragma: no cover - _require raises
    _require(all(set(row) == set(fields) for row in rows), f"JSONL/CSV schema differs: {jsonl_path}")
    return [{field: row[field] for field in fields} for row in rows]


def _source_row_id(row: Mapping[str, Any]) -> str:
    for key, value in row.items():
        if key.endswith("_id") and key not in {
            "backbone_id", "condition_id", "contrast_id", "comparison_id", "metric_id",
            "answer_metric_id", "subset_id", "transition_id", "figure_id", "table_id",
        }:
            if isinstance(value, str):
                return value
    return "row-sha256-" + _row_sha256(row)


def _validate_hashed_files(directory: Path, hashes: Mapping[str, str], label: str) -> None:
    for name, digest in hashes.items():
        _require(_sha256_file(directory / name) == digest, f"{label} frozen file hash differs: {name}")


def _validate_stage_abc(
    directory: Path,
    *,
    label: str,
    marker_name: str,
    audit_id: str,
    audit_sha256: str,
    marker_sha256: str,
    source_manifest_id: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    _require(directory.is_dir() and not directory.is_symlink(), f"{label} directory is unsafe")
    _require(_sha256_file(directory / "audit.json") == audit_sha256, f"{label} audit hash differs")
    _require(_sha256_file(directory / marker_name) == marker_sha256, f"{label} marker hash differs")
    audit = _read_json(directory / "audit.json")
    marker = _read_json(directory / marker_name)
    manifest = _read_json(directory / "source-manifest.json")
    _require(audit.get("status") == "passed" and marker.get("status") == "passed", f"{label} did not pass")
    _require(audit.get("audit_id") == audit_id == marker.get("audit_id"), f"{label} audit identity differs")
    _require(marker.get("audit_sha256") == audit_sha256, f"{label} marker-to-audit hash differs")
    _require(manifest.get("source_manifest_id") == source_manifest_id, f"{label} source identity differs")
    _validate_hashed_files(directory, audit.get("output_sha256", {}), label)
    return audit, manifest


def _validate_inputs(
    *,
    repo_root: Path,
    stage_a_dir: Path,
    stage_b_dir: Path,
    stage_c_dir: Path,
    stage_d_dir: Path,
    s3_manifest_path: Path,
) -> tuple[dict[str, Any], dict[str, Any]]:
    root = repo_root.resolve()
    frozen = root / "artifacts/chapter5-main60-analysis-v1"
    expected_paths = {
        "Stage A": frozen / "stage-a",
        "Stage B": frozen / "stage-b",
        "Stage C": frozen / "stage-c",
        "Stage D": frozen / "stage-d",
    }
    supplied = {
        "Stage A": stage_a_dir.resolve(),
        "Stage B": stage_b_dir.resolve(),
        "Stage C": stage_c_dir.resolve(),
        "Stage D": stage_d_dir.resolve(),
    }
    _require(root.is_dir() and not root.is_symlink(), "Repository root is unsafe")
    for label, expected in expected_paths.items():
        _require(supplied[label] == expected.resolve(), f"{label} is not at the frozen repository location")

    stage_a_audit, stage_a_manifest = _validate_stage_abc(
        supplied["Stage A"], label="Stage A", marker_name="STAGE-A.PASSED",
        audit_id=EXPECTED_STAGE_A_AUDIT_ID,
        audit_sha256=EXPECTED_FROZEN_SHA256["stage_a_audit"],
        marker_sha256=EXPECTED_FROZEN_SHA256["stage_a_marker"],
        source_manifest_id=EXPECTED_SOURCE_MANIFEST_IDS["stage_a"],
    )
    stage_b_audit, stage_b_manifest = _validate_stage_abc(
        supplied["Stage B"], label="Stage B", marker_name="STAGE-B.PASSED",
        audit_id=EXPECTED_STAGE_B_AUDIT_ID,
        audit_sha256=EXPECTED_FROZEN_SHA256["stage_b_audit"],
        marker_sha256=EXPECTED_FROZEN_SHA256["stage_b_marker"],
        source_manifest_id=EXPECTED_SOURCE_MANIFEST_IDS["stage_b"],
    )
    stage_c_audit, stage_c_manifest = _validate_stage_abc(
        supplied["Stage C"], label="Stage C", marker_name="STAGE-C.PASSED",
        audit_id=EXPECTED_STAGE_C_AUDIT_ID,
        audit_sha256=EXPECTED_FROZEN_SHA256["stage_c_audit"],
        marker_sha256=EXPECTED_FROZEN_SHA256["stage_c_marker"],
        source_manifest_id=EXPECTED_SOURCE_MANIFEST_IDS["stage_c"],
    )

    stage_d = supplied["Stage D"]
    _require(stage_d.is_dir() and not stage_d.is_symlink(), "Stage D directory is unsafe")
    _require(
        _sha256_file(stage_d / "audit.json") == EXPECTED_FROZEN_SHA256["stage_d_auto_audit"],
        "Stage D automatic audit hash differs",
    )
    _require(
        _sha256_file(stage_d / "final-audit.json") == EXPECTED_FROZEN_SHA256["stage_d_final_audit"],
        "Stage D final audit hash differs",
    )
    _require(
        _sha256_file(stage_d / "STAGE-D.PASSED") == EXPECTED_FROZEN_SHA256["stage_d_marker"],
        "Stage D marker hash differs",
    )
    stage_d_auto_audit = _read_json(stage_d / "audit.json")
    stage_d_final_audit = _read_json(stage_d / "final-audit.json")
    stage_d_marker = _read_json(stage_d / "STAGE-D.PASSED")
    stage_d_manifest = _read_json(stage_d / "source-manifest.json")
    _require(
        stage_d_auto_audit.get("audit_id") == EXPECTED_STAGE_D_AUTO_AUDIT_ID,
        "Stage D automatic audit identity differs",
    )
    _require(
        stage_d_final_audit.get("audit_id") == EXPECTED_STAGE_D_FINAL_AUDIT_ID
        == stage_d_marker.get("audit_id"),
        "Stage D final audit identity differs",
    )
    _require(
        stage_d_marker.get("audit_sha256") == EXPECTED_FROZEN_SHA256["stage_d_final_audit"],
        "Stage D marker-to-final-audit hash differs",
    )
    _require(
        stage_d_final_audit.get("automatic_audit_id") == EXPECTED_STAGE_D_AUTO_AUDIT_ID
        == stage_d_marker.get("automatic_audit_id"),
        "Stage D automatic/final lineage differs",
    )
    _require(
        stage_d_manifest.get("source_manifest_id") == EXPECTED_SOURCE_MANIFEST_IDS["stage_d"],
        "Stage D source identity differs",
    )
    _validate_hashed_files(stage_d, stage_d_final_audit.get("output_sha256", {}), "Stage D")

    _require(stage_b_manifest.get("stage_a_audit_id") == EXPECTED_STAGE_A_AUDIT_ID, "Stage B->A lineage differs")
    _require(stage_c_manifest.get("stage_a_audit_id") == EXPECTED_STAGE_A_AUDIT_ID, "Stage C->A lineage differs")
    _require(stage_c_manifest.get("stage_b_audit_id") == EXPECTED_STAGE_B_AUDIT_ID, "Stage C->B lineage differs")
    for key, expected in (
        ("stage_a_audit_id", EXPECTED_STAGE_A_AUDIT_ID),
        ("stage_b_audit_id", EXPECTED_STAGE_B_AUDIT_ID),
        ("stage_c_audit_id", EXPECTED_STAGE_C_AUDIT_ID),
    ):
        _require(stage_d_manifest.get(key) == expected, f"Stage D lineage differs: {key}")

    s3_expected = root / "experiments/locomo-conv50-v1/manifests/s3-curated.json"
    s3_path = s3_manifest_path.resolve()
    _require(s3_path == s3_expected.resolve(), "S3 manifest is not at the frozen repository location")
    _require(_sha256_file(s3_path) == EXPECTED_FROZEN_SHA256["s3_manifest"], "S3 manifest hash differs")
    s3 = _read_json(s3_path)
    _require(s3.get("artifact_id") == "locomo/conv-50/s3-curated/v1", "S3 artifact identity differs")
    _require(s3.get("build", {}).get("mode") == "formal", "S3 build is not formal")
    _require(s3.get("build", {}).get("chunks_completed") == 85, "S3 chunk count differs")

    provenance = {
        "stage_a_audit_id": stage_a_audit["audit_id"],
        "stage_b_audit_id": stage_b_audit["audit_id"],
        "stage_c_audit_id": stage_c_audit["audit_id"],
        "stage_d_automatic_audit_id": stage_d_auto_audit["audit_id"],
        "stage_d_final_audit_id": stage_d_final_audit["audit_id"],
        "stage_a_audit_sha256": EXPECTED_FROZEN_SHA256["stage_a_audit"],
        "stage_b_audit_sha256": EXPECTED_FROZEN_SHA256["stage_b_audit"],
        "stage_c_audit_sha256": EXPECTED_FROZEN_SHA256["stage_c_audit"],
        "stage_d_final_audit_sha256": EXPECTED_FROZEN_SHA256["stage_d_final_audit"],
        "s3_manifest_sha256": EXPECTED_FROZEN_SHA256["s3_manifest"],
    }
    input_audit = {
        "frozen_stage_a_lineage_verified": True,
        "frozen_stage_b_verified": True,
        "frozen_stage_c_verified": True,
        "frozen_final_stage_d_verified": True,
        "s3_formal_manifest_verified": True,
        "stage_a_table_read_for_recalculation": False,
        "question_level_effect_recalculation": False,
        "new_bootstrap_computed": False,
    }
    return provenance, {"input_audit": input_audit, "s3": s3}


def _result_unit_id(spec: ResultSpec, backbone: str) -> str:
    return f"rq1-result-{spec.short_code.lower()}-{backbone}"


def _architecture_code(spec: ResultSpec, backbone: str) -> str:
    return f"RQ1-AE-{spec.effect_order:02d}-{backbone.upper()}"


def _load_source_tables(stage_b: Path, stage_c: Path, stage_d: Path) -> dict[str, list[dict[str, Any]]]:
    return {
        "b_condition": _read_jsonl(stage_b / "condition-summaries.jsonl"),
        "b_aggregate": _read_jsonl(stage_b / "aggregate-effects.jsonl"),
        "b_interaction": _read_jsonl(stage_b / "interaction-aggregates.jsonl"),
        "b_bootstrap": _read_jsonl(stage_b / "bootstrap-intervals.jsonl"),
        "b_strict": _read_jsonl(stage_b / "strict-transitions.jsonl"),
        "b_semantic": _read_jsonl(stage_b / "semantic-transitions.jsonl"),
        "b_figure": _read_jsonl_in_csv_field_order(
            stage_b / "figure-5-3-data.jsonl", stage_b / "figure-5-3-data.csv"
        ),
        "c_condition": _read_jsonl(stage_c / "condition-summaries.jsonl"),
        "c_aggregate": _read_jsonl(stage_c / "aggregate-effects.jsonl"),
        "c_strict": _read_jsonl(stage_c / "strict-transitions.jsonl"),
        "c_semantic": _read_jsonl(stage_c / "semantic-transitions.jsonl"),
        "c_table": _read_jsonl_in_csv_field_order(
            stage_c / "table-5-3-data.jsonl", stage_c / "table-5-3-data.csv"
        ),
        "d_register": _read_jsonl(stage_d / "comparison-register.jsonl"),
        "d_conversion_matrices": _read_jsonl(stage_d / "conversion-matrices.jsonl"),
        "d_conversion_summaries": _read_jsonl(stage_d / "conversion-summaries.jsonl"),
        "d_category": _read_jsonl(stage_d / "category-effects.jsonl"),
        "d_category_interaction": _read_jsonl(stage_d / "category-interactions.jsonl"),
        "d_process_condition": _read_jsonl(stage_d / "process-condition-summaries.jsonl"),
        "d_process_paired": _read_jsonl(stage_d / "process-paired-summaries.jsonl"),
        "d_trace_review": _read_jsonl(stage_d / "trace-review-register.jsonl"),
    }


def _result_unit_register(sources: Mapping[str, Sequence[Mapping[str, Any]]]) -> list[dict[str, Any]]:
    d_index = {
        (str(row["backbone_id"]), str(row["comparison_id"])): row
        for row in sources["d_register"]
    }
    rows: list[dict[str, Any]] = []
    result_order = 0
    for spec in RESULT_SPECS:
        for backbone in BACKBONES:
            result_order += 1
            source = d_index.get((backbone, spec.comparison_id))
            _require(source is not None, f"Stage D result-unit registration missing: {backbone}/{spec.comparison_id}")
            _require(source.get("publication_role") == spec.publication_role, "Result-unit publication role differs")
            _require(source.get("baseline_condition") == spec.baseline_condition, "Result-unit baseline differs")
            _require(source.get("target_condition") == spec.target_condition, "Result-unit target differs")
            expected_direction = "difference_in_differences" if spec.comparison_type == "interaction" else "target_minus_baseline"
            _require(source.get("difference_direction") == expected_direction, "Result-unit direction differs")
            body = {
                "protocol_version": STAGE_E_PROTOCOL_VERSION,
                "result_unit_id": _result_unit_id(spec, backbone),
                "architecture_evidence_code": _architecture_code(spec, backbone),
                "result_order": result_order,
                "effect_order": spec.effect_order,
                "backbone_id": backbone,
                "comparison_id": spec.comparison_id,
                "source_effect_id": spec.source_effect_id,
                "source_stage": spec.source_stage,
                "comparison_type": spec.comparison_type,
                "effect_status": spec.effect_status,
                "publication_role": spec.publication_role,
                "section_id": spec.section_id,
                "baseline_condition": spec.baseline_condition,
                "target_condition": spec.target_condition,
                "difference_direction": expected_direction,
                "display_formula": spec.display_formula,
                "answer_denominator": QUESTION_COUNT,
                "evidence_denominator": EVIDENCE_ELIGIBLE_COUNT,
                "multi_gold_source_denominator": EXPECTED_MULTI_GOLD_SOURCE_COUNT,
                "identification_scope": spec.identification_scope,
                "backbone_pooling_permitted": False,
            }
            rows.append(body)
    return rows


def _main_metrics(
    units: Sequence[Mapping[str, Any]], sources: Mapping[str, Sequence[Mapping[str, Any]]]
) -> list[dict[str, Any]]:
    b_index = {
        (str(row["backbone_id"]), str(row["contrast_id"]), str(row["metric_id"])): row
        for row in sources["b_aggregate"]
    }
    c_index = {
        (str(row["backbone_id"]), str(row["contrast_id"]), str(row["metric_id"])): row
        for row in sources["c_aggregate"]
    }
    interaction_index = {
        (str(row["backbone_id"]), str(row["metric_id"])): row
        for row in sources["b_interaction"]
    }
    rows: list[dict[str, Any]] = []
    for unit in units:
        for metric_id in PRIMARY_METRICS:
            if unit["comparison_type"] == "interaction":
                source = interaction_index.get((str(unit["backbone_id"]), metric_id))
                source_table = "stage-b/interaction-aggregates.jsonl"
                source_stage = "stage_b"
                estimate = source.get("mean_did") if source else None
                baseline_mean = target_mean = None
                component = {
                    "mean_storage_r1_e3_minus_e1": source.get("mean_storage_r1_e3_minus_e1") if source else None,
                    "mean_storage_r2_e4_minus_e2": source.get("mean_storage_r2_e4_minus_e2") if source else None,
                    "mean_retrieval_s1_e2_minus_e1": source.get("mean_retrieval_s1_e2_minus_e1") if source else None,
                    "mean_retrieval_s2_e4_minus_e3": source.get("mean_retrieval_s2_e4_minus_e3") if source else None,
                }
            else:
                index = b_index if unit["source_stage"] == "stage_b" else c_index
                source = index.get((str(unit["backbone_id"]), str(unit["comparison_id"]), metric_id))
                source_table = f"{str(unit['source_stage']).replace('_', '-')}/aggregate-effects.jsonl"
                source_stage = str(unit["source_stage"])
                estimate = source.get("mean_difference") if source else None
                baseline_mean = source.get("baseline_mean") if source else None
                target_mean = source.get("target_mean") if source else None
                component = {
                    "mean_storage_r1_e3_minus_e1": None,
                    "mean_storage_r2_e4_minus_e2": None,
                    "mean_retrieval_s1_e2_minus_e1": None,
                    "mean_retrieval_s2_e4_minus_e3": None,
                }
            _require(source is not None, f"Main metric missing: {unit['result_unit_id']}/{metric_id}")
            expected_denominator = EVIDENCE_ELIGIBLE_COUNT if metric_id == "evidence_recall" else QUESTION_COUNT
            _require(int(source["denominator"]) == expected_denominator, "Main metric denominator differs")
            _require(source.get("metric_direction") == "higher_is_better", "Main metric direction differs")
            body = {
                "protocol_version": STAGE_E_PROTOCOL_VERSION,
                "result_unit_id": unit["result_unit_id"],
                "architecture_evidence_code": unit["architecture_evidence_code"],
                "section_id": unit["section_id"],
                "backbone_id": unit["backbone_id"],
                "comparison_id": unit["comparison_id"],
                "comparison_type": unit["comparison_type"],
                "publication_role": unit["publication_role"],
                "baseline_condition": unit["baseline_condition"],
                "target_condition": unit["target_condition"],
                "metric_id": metric_id,
                "metric_family": "evidence" if metric_id == "evidence_recall" else "answer",
                "denominator_scope": "evidence_eligible" if metric_id == "evidence_recall" else "answer_all",
                "denominator": expected_denominator,
                "metric_direction": "higher_is_better",
                "difference_direction": unit["difference_direction"],
                "estimate_kind": "mean_did" if unit["comparison_type"] == "interaction" else "mean_target_minus_baseline",
                "point_estimate": float(estimate),
                "baseline_mean": baseline_mean,
                "target_mean": target_mean,
                "win_count": source.get("win_count"),
                "tie_count": source.get("tie_count"),
                "loss_count": source.get("loss_count"),
                **component,
                "source_stage": source_stage,
                "source_table": source_table,
                "source_row_id": _source_row_id(source),
                "source_row_sha256": _row_sha256(source),
            }
            rows.append({"main_metric_id": _id("stage-e-main-metric-", body), **body})
    return rows


def _strict_transitions(
    units: Sequence[Mapping[str, Any]], sources: Mapping[str, Sequence[Mapping[str, Any]]]
) -> list[dict[str, Any]]:
    indices = {
        "stage_b": defaultdict(list),
        "stage_c": defaultdict(list),
    }
    for stage, table_name in (("stage_b", "b_strict"), ("stage_c", "c_strict")):
        for row in sources[table_name]:
            indices[stage][(str(row["backbone_id"]), str(row["contrast_id"]))].append(row)
    rows: list[dict[str, Any]] = []
    for unit in units:
        if unit["comparison_type"] != "simple":
            continue
        selected = indices[str(unit["source_stage"])][(str(unit["backbone_id"]), str(unit["comparison_id"]))]
        _require(len(selected) == 4, "Strict-transition row count differs")
        _require({str(row["transition_id"]) for row in selected} == set(STRICT_TRANSITIONS), "Strict transitions differ")
        _require(sum(int(row["count"]) for row in selected) == QUESTION_COUNT, "Strict-transition denominator differs")
        by_transition = {str(row["transition_id"]): row for row in selected}
        for transition_id in STRICT_TRANSITIONS:
            source = by_transition[transition_id]
            body = {
                "protocol_version": STAGE_E_PROTOCOL_VERSION,
                "result_unit_id": unit["result_unit_id"],
                "architecture_evidence_code": unit["architecture_evidence_code"],
                "backbone_id": unit["backbone_id"],
                "comparison_id": unit["comparison_id"],
                "publication_role": unit["publication_role"],
                "baseline_condition": unit["baseline_condition"],
                "target_condition": unit["target_condition"],
                "difference_direction": "target_minus_baseline",
                "transition_id": transition_id,
                "baseline_strict_correct": source["baseline_strict_correct"],
                "target_strict_correct": source["target_strict_correct"],
                "count": int(source["count"]),
                "denominator": QUESTION_COUNT,
                "source_stage": unit["source_stage"],
                "source_table": f"{str(unit['source_stage']).replace('_', '-')}/strict-transitions.jsonl",
                "source_row_id": _source_row_id(source),
                "source_row_sha256": _row_sha256(source),
            }
            rows.append({"strict_transition_id": _id("stage-e-strict-transition-", body), **body})
    return rows


def _reconciliation_tables(
    sources: Mapping[str, Sequence[Mapping[str, Any]]]
) -> tuple[
    list[dict[str, Any]],
    list[dict[str, Any]],
    list[dict[str, Any]],
    list[dict[str, Any]],
]:
    """Freeze all 13 Stage B/C metric summaries and the 3x3 label tables.

    ``main-metrics`` remains the compact six-metric reporting table.  These
    reconciliation tables retain the neutral Partial Rate, Any/All-hit,
    multi-source, and EvidenceBundle-length rows so the reporting layer cannot
    silently change their direction or denominator.
    """

    conditions_raw = [dict(row) for row in sources["b_condition"]]
    conditions_raw.extend(dict(row) for row in sources["c_condition"])
    paired_raw = [dict(row) for row in sources["b_aggregate"]]
    paired_raw.extend(
        dict(row) for row in sources["c_aggregate"]
        if row.get("contrast_id") in MAIN_SIMPLE_IDS
    )
    interactions = [dict(row) for row in sources["b_interaction"]]
    semantic_raw = [dict(row) for row in sources["b_semantic"]]
    semantic_raw.extend(
        dict(row) for row in sources["c_semantic"]
        if row.get("contrast_id") in MAIN_SIMPLE_IDS
    )
    return (
        _uniform_rows(conditions_raw),
        _uniform_rows(paired_raw),
        interactions,
        _uniform_rows(semantic_raw),
    )


def _architecture_tables(
    units: Sequence[Mapping[str, Any]],
    metrics: Sequence[Mapping[str, Any]],
    strict: Sequence[Mapping[str, Any]],
    bootstrap: Sequence[Mapping[str, Any]],
    trace_reviews: Sequence[Mapping[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    metric_index = {(row["result_unit_id"], row["metric_id"]): row for row in metrics}
    strict_groups: dict[str, dict[str, Mapping[str, Any]]] = defaultdict(dict)
    for row in strict:
        strict_groups[str(row["result_unit_id"])][str(row["transition_id"])] = row
    bootstrap_keys = {
        (str(row["backbone_id"]), str(row["effect_id"]), str(row["metric_id"])) for row in bootstrap
    }
    trace_counts = Counter((str(row["module_id"]), str(row["backbone_id"])) for row in trace_reviews)
    effects: list[dict[str, Any]] = []
    codes: list[dict[str, Any]] = []
    for unit in units:
        spec = RESULT_SPEC_BY_ID[str(unit["comparison_id"])]
        values = {metric: metric_index[(unit["result_unit_id"], metric)] for metric in PRIMARY_METRICS}
        transitions = strict_groups.get(str(unit["result_unit_id"]), {})
        bootstrap_effect = spec.source_effect_id
        has_bootstrap = all(
            (str(unit["backbone_id"]), bootstrap_effect, metric) in bootstrap_keys
            for metric in BOOTSTRAP_METRICS
        )
        strict_metric = values["strict_accuracy"]
        body = {
            "protocol_version": STAGE_E_PROTOCOL_VERSION,
            "architecture_evidence_code": unit["architecture_evidence_code"],
            "result_unit_id": unit["result_unit_id"],
            "effect_order": unit["effect_order"],
            "backbone_id": unit["backbone_id"],
            "comparison_id": unit["comparison_id"],
            "comparison_type": unit["comparison_type"],
            "effect_status": unit["effect_status"],
            "publication_role": unit["publication_role"],
            "section_id": unit["section_id"],
            "baseline_condition": unit["baseline_condition"],
            "target_condition": unit["target_condition"],
            "difference_direction": unit["difference_direction"],
            "display_formula": unit["display_formula"],
            "delta_token_precision": values["token_precision"]["point_estimate"],
            "delta_token_recall": values["token_recall"]["point_estimate"],
            "delta_token_f1": values["token_f1"]["point_estimate"],
            "delta_strict_accuracy": values["strict_accuracy"]["point_estimate"],
            "delta_soft_semantic_score": values["soft_semantic_score"]["point_estimate"],
            "delta_evidence_recall": values["evidence_recall"]["point_estimate"],
            "answer_denominator": QUESTION_COUNT,
            "evidence_denominator": EVIDENCE_ELIGIBLE_COUNT,
            "multi_gold_source_denominator": EXPECTED_MULTI_GOLD_SOURCE_COUNT,
            "strict_repair_count": transitions.get("strict_not_correct_to_correct", {}).get("count"),
            "strict_harm_count": transitions.get("strict_correct_to_not_correct", {}).get("count"),
            "strict_unchanged_correct_count": transitions.get("strict_unchanged_correct", {}).get("count"),
            "strict_unchanged_not_correct_count": transitions.get("strict_unchanged_not_correct", {}).get("count"),
            "interaction_positive_count": strict_metric["win_count"] if unit["comparison_type"] == "interaction" else None,
            "interaction_zero_count": strict_metric["tie_count"] if unit["comparison_type"] == "interaction" else None,
            "interaction_negative_count": strict_metric["loss_count"] if unit["comparison_type"] == "interaction" else None,
            "bootstrap_available": has_bootstrap,
            "bootstrap_status": "predeclared_stage_b" if has_bootstrap else "not_predeclared_for_this_effect",
            "conversion_available": unit["comparison_type"] == "simple",
            "category_available": True,
            "process_paired_available": unit["comparison_type"] == "simple",
            "bounded_trace_review_count": trace_counts[(str(unit["section_id"]), str(unit["backbone_id"]))],
            "identification_scope": unit["identification_scope"],
        }
        effects.append({"architecture_effect_id": _id("stage-e-architecture-effect-", body), **body})

        code_body = {
            "protocol_version": STAGE_E_PROTOCOL_VERSION,
            "architecture_evidence_code": unit["architecture_evidence_code"],
            "result_unit_id": unit["result_unit_id"],
            "section_id": unit["section_id"],
            "backbone_id": unit["backbone_id"],
            "comparison_id": unit["comparison_id"],
            "effect_status": unit["effect_status"],
            "main_metric_evidence_code": f"METRIC-{unit['architecture_evidence_code']}",
            "bootstrap_evidence_code": (
                f"BOOT-{unit['architecture_evidence_code']}" if has_bootstrap else "BOOT-NOT-PREDECLARED"
            ),
            "strict_transition_evidence_code": (
                f"STRICT-{unit['architecture_evidence_code']}"
                if unit["comparison_type"] == "simple" else "STRICT-DID-SIGN-COUNTS"
            ),
            "conversion_evidence_code": (
                f"CONVERSION-{unit['architecture_evidence_code']}"
                if unit["comparison_type"] == "simple" else "CONVERSION-NOT-APPLICABLE-TO-DID"
            ),
            "category_evidence_code": f"CATEGORY-{unit['architecture_evidence_code']}",
            "process_evidence_code": (
                f"PROCESS-{unit['architecture_evidence_code']}"
                if unit["comparison_type"] == "simple" else "PROCESS-COMPONENTS-ONLY"
            ),
            "trace_evidence_code": f"TRACE-{unit['section_id']}-{str(unit['backbone_id']).upper()}",
            "claim_scope_code": (
                "CORE-WITHIN-BACKBONE" if unit["effect_status"] == "core_effect"
                else "DESCRIPTIVE-COMPLETE-SYSTEM-WITHIN-BACKBONE"
            ),
            "identified_architecture_effect_claim_permitted": unit["effect_status"] == "core_effect",
            "causal_component_claim_permitted": False,
            "cross_backbone_inference_permitted": False,
            "identification_scope": unit["identification_scope"],
        }
        codes.append(code_body)
    return effects, codes


def _s3_build_cost_summary(s3: Mapping[str, Any]) -> list[dict[str, Any]]:
    cost = s3["build_cost"]
    usage = cost["usage_totals"]
    counts = s3["counts"]
    row = {
        "protocol_version": STAGE_E_PROTOCOL_VERSION,
        "s3_artifact_id": s3["artifact_id"],
        "cost_scope": "one_time_s3_construction",
        "cost_role": "descriptive_build_provenance_only",
        "included_in_main_effect_estimates": False,
        "query_time_cost": False,
        "amortised_cost": False,
        "pareto_analysis_input": False,
        "episodes": int(cost["episodes"]),
        "llm_calls": int(cost["llm_calls"]),
        "rounds": int(cost["rounds"]),
        "tool_calls": int(cost["tool_calls"]),
        "prompt_tokens": int(usage["prompt_tokens"]),
        "completion_tokens": int(usage["completion_tokens"]),
        "total_tokens": int(usage["total_tokens"]),
        "store_bytes": int(counts["bytes"]),
        "store_files": int(counts["files"]),
        "store_headings": int(counts["headings"]),
        "store_lines": int(counts["lines"]),
        "locator_mentions": int(counts["locator_mentions"]),
        "unique_locators_referenced": int(counts["unique_locators_referenced"]),
        "source_locators_available": int(counts["source_locators_available"]),
        "source_manifest": "experiments/locomo-conv50-v1/manifests/s3-curated.json",
        "source_manifest_sha256": EXPECTED_FROZEN_SHA256["s3_manifest"],
    }
    _require(row["prompt_tokens"] + row["completion_tokens"] == row["total_tokens"], "S3 token total differs")
    return [row]


def _display_value(value: int | float, decimals: int, *, signed: bool) -> str:
    if decimals == 0:
        return str(int(value))
    return format(float(value), f"{'+' if signed else ''}.{decimals}f")


def _display_number_register(
    *,
    units: Sequence[Mapping[str, Any]],
    metrics: Sequence[Mapping[str, Any]],
    paired_effects: Sequence[Mapping[str, Any]],
    interaction_effects: Sequence[Mapping[str, Any]],
    bootstrap: Sequence[Mapping[str, Any]],
    strict: Sequence[Mapping[str, Any]],
    conversion: Sequence[Mapping[str, Any]],
    category: Sequence[Mapping[str, Any]],
    category_interactions: Sequence[Mapping[str, Any]],
    process_condition: Sequence[Mapping[str, Any]],
    process_paired: Sequence[Mapping[str, Any]],
    figure: Sequence[Mapping[str, Any]],
    table: Sequence[Mapping[str, Any]],
    s3_cost: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    unit_index = {(str(row["backbone_id"]), str(row["comparison_id"])): row for row in units}
    rows: list[dict[str, Any]] = []

    def add(
        *,
        context: str,
        section: str,
        backbone: str | None,
        comparison: str | None,
        metric: str,
        statistic: str,
        denominator_scope: str,
        denominator: int | None,
        value: int | float,
        decimals: int,
        direction: str,
        source_artifact: str,
        source_row: Mapping[str, Any],
        result_unit_id: str | None = None,
        evidence_code: str | None = None,
    ) -> None:
        body = {
            "protocol_version": STAGE_E_PROTOCOL_VERSION,
            "display_context": context,
            "section_id": section,
            "result_unit_id": result_unit_id,
            "architecture_evidence_code": evidence_code,
            "backbone_id": backbone,
            "comparison_id": comparison,
            "metric_id": metric,
            "statistic": statistic,
            "denominator_scope": denominator_scope,
            "denominator": denominator,
            "raw_value": value,
            "display_decimals": decimals,
            "display_value": _display_value(value, decimals, signed=direction in {"target_minus_baseline", "difference_in_differences"} and statistic not in {"count", "ci_lower", "ci_upper"}),
            "difference_direction": direction,
            "source_artifact": source_artifact,
            "source_row_id": _source_row_id(source_row),
            "source_row_sha256": _row_sha256(source_row),
        }
        rows.append({"display_number_id": _id("stage-e-display-number-", body), **body})

    for row in metrics:
        add(
            context="architecture_main_metric", section=str(row["section_id"]),
            backbone=str(row["backbone_id"]), comparison=str(row["comparison_id"]),
            metric=str(row["metric_id"]), statistic=str(row["estimate_kind"]),
            denominator_scope=str(row["denominator_scope"]), denominator=int(row["denominator"]),
            value=float(row["point_estimate"]), decimals=4, direction=str(row["difference_direction"]),
            source_artifact="main-metrics.jsonl", source_row=row,
            result_unit_id=str(row["result_unit_id"]), evidence_code=str(row["architecture_evidence_code"]),
        )
        if row["comparison_type"] == "simple":
            for statistic, value in (
                ("baseline_mean", row["baseline_mean"]),
                ("target_mean", row["target_mean"]),
            ):
                add(
                    context="architecture_condition_endpoint", section=str(row["section_id"]),
                    backbone=str(row["backbone_id"]), comparison=str(row["comparison_id"]),
                    metric=str(row["metric_id"]), statistic=statistic,
                    denominator_scope=str(row["denominator_scope"]), denominator=int(row["denominator"]),
                    value=float(value), decimals=4, direction="not_directional",
                    source_artifact="main-metrics.jsonl", source_row=row,
                    result_unit_id=str(row["result_unit_id"]),
                    evidence_code=str(row["architecture_evidence_code"]),
                )

    # Supplementary/diagnostic effect rows are registered without promoting
    # them into the six-metric architecture summary.  This covers Partial Rate,
    # Any/All-hit, multi-source coverage, and EvidenceBundle length.
    supplementary_metrics = {
        "partial_rate",
        "evidence_any_hit",
        "evidence_all_hit",
        "evidence_bundle_characters",
        "multi_gold_source_evidence_recall",
        "multi_gold_source_any_hit",
        "multi_gold_source_all_hit",
    }
    for row in paired_effects:
        if row["metric_id"] not in supplementary_metrics:
            continue
        unit = unit_index[(str(row["backbone_id"]), str(row["contrast_id"]))]
        add(
            context="supplementary_paired_metric", section=str(unit["section_id"]),
            backbone=str(row["backbone_id"]), comparison=str(row["contrast_id"]),
            metric=str(row["metric_id"]), statistic="mean_target_minus_baseline",
            denominator_scope=str(row["denominator_scope"]), denominator=int(row["denominator"]),
            value=float(row["mean_difference"]), decimals=4, direction="target_minus_baseline",
            source_artifact="paired-effect-summaries.jsonl", source_row=row,
            result_unit_id=str(unit["result_unit_id"]), evidence_code=str(unit["architecture_evidence_code"]),
        )
    interaction_units = {
        str(unit["backbone_id"]): unit for unit in units if unit["comparison_type"] == "interaction"
    }
    for row in interaction_effects:
        if row["metric_id"] not in supplementary_metrics:
            continue
        unit = interaction_units[str(row["backbone_id"])]
        add(
            context="supplementary_interaction_metric", section=str(unit["section_id"]),
            backbone=str(row["backbone_id"]), comparison=str(unit["comparison_id"]),
            metric=str(row["metric_id"]), statistic="mean_did",
            denominator_scope=str(row["denominator_scope"]), denominator=int(row["denominator"]),
            value=float(row["mean_did"]), decimals=4, direction="difference_in_differences",
            source_artifact="interaction-effect-summaries.jsonl", source_row=row,
            result_unit_id=str(unit["result_unit_id"]), evidence_code=str(unit["architecture_evidence_code"]),
        )

    bootstrap_unit = {
        (str(unit["backbone_id"]), str(unit["source_effect_id"])): unit for unit in units
    }
    for row in bootstrap:
        unit = bootstrap_unit[(str(row["backbone_id"]), str(row["effect_id"]))]
        for statistic in ("point_estimate", "ci_lower", "ci_upper"):
            add(
                context="selected_bootstrap", section=str(unit["section_id"]),
                backbone=str(row["backbone_id"]), comparison=str(unit["comparison_id"]),
                metric=str(row["metric_id"]), statistic=statistic,
                denominator_scope="answer_all", denominator=QUESTION_COUNT,
                value=float(row[statistic]), decimals=4, direction=str(unit["difference_direction"]),
                source_artifact="stage-b/bootstrap-intervals.jsonl", source_row=row,
                result_unit_id=str(unit["result_unit_id"]), evidence_code=str(unit["architecture_evidence_code"]),
            )

    for row in strict:
        add(
            context="strict_transition", section=str(RESULT_SPEC_BY_ID[str(row["comparison_id"])].section_id),
            backbone=str(row["backbone_id"]), comparison=str(row["comparison_id"]),
            metric="strict_accuracy", statistic=str(row["transition_id"]),
            denominator_scope="answer_all", denominator=QUESTION_COUNT, value=int(row["count"]),
            decimals=0, direction="target_minus_baseline", source_artifact="strict-transitions.jsonl",
            source_row=row, result_unit_id=str(row["result_unit_id"]),
            evidence_code=str(row["architecture_evidence_code"]),
        )

    strict_interactions = [
        row for row in metrics
        if row["comparison_type"] == "interaction" and row["metric_id"] == "strict_accuracy"
    ]
    for row in strict_interactions:
        for field, statistic in (("win_count", "positive_count"), ("tie_count", "zero_count"), ("loss_count", "negative_count")):
            add(
                context="interaction_sign_count", section=str(row["section_id"]),
                backbone=str(row["backbone_id"]), comparison=str(row["comparison_id"]),
                metric="strict_accuracy", statistic=statistic, denominator_scope="answer_all",
                denominator=QUESTION_COUNT, value=int(row[field]), decimals=0,
                direction="difference_in_differences", source_artifact=str(row["source_table"]), source_row=row,
                result_unit_id=str(row["result_unit_id"]), evidence_code=str(row["architecture_evidence_code"]),
            )

    # The compact conversion display uses Strict on the primary 58-question subset;
    # the complete 58/19 x three-metric matrices remain frozen separately.
    for row in conversion:
        if row["subset_id"] != "evidence_eligible_58" or row["answer_metric_id"] != "strict_accuracy":
            continue
        unit = unit_index[(str(row["backbone_id"]), str(row["comparison_id"]))]
        for field in (
            "evidence_up_answer_improve", "evidence_up_answer_not_improve",
            "evidence_same_answer_improve", "evidence_down_without_answer_harm",
        ):
            add(
                context="conversion_primary", section=str(unit["section_id"]),
                backbone=str(row["backbone_id"]), comparison=str(row["comparison_id"]),
                metric="evidence_recall_by_strict_accuracy", statistic=field,
                denominator_scope="evidence_eligible", denominator=EVIDENCE_ELIGIBLE_COUNT,
                value=int(row[field]), decimals=0, direction="target_minus_baseline",
                source_artifact="stage-d/conversion-summaries.jsonl", source_row=row,
                result_unit_id=str(unit["result_unit_id"]), evidence_code=str(unit["architecture_evidence_code"]),
            )

    for source_rows, context, estimate_field in (
        (category, "category_effect", "mean_difference"),
        (category_interactions, "category_interaction", "mean_did"),
    ):
        for row in source_rows:
            unit = unit_index[(str(row["backbone_id"]), str(row["comparison_id"]))]
            add(
                context=context, section=str(unit["section_id"]), backbone=str(row["backbone_id"]),
                comparison=str(row["comparison_id"]), metric=str(row["metric_id"]),
                statistic=f"C{row['category']}_{estimate_field}",
                denominator_scope=str(row["denominator_scope"]), denominator=int(row["denominator"]),
                value=float(row[estimate_field]), decimals=4, direction=str(unit["difference_direction"]),
                source_artifact=f"stage-d/{'category-effects' if context == 'category_effect' else 'category-interactions'}.jsonl",
                source_row=row, result_unit_id=str(unit["result_unit_id"]),
                evidence_code=str(unit["architecture_evidence_code"]),
            )

    for row in process_condition:
        if row.get("mean") is None:
            continue
        add(
            context="process_condition", section="5.2", backbone=str(row["backbone_id"]),
            comparison=None, metric=str(row["metric_id"]), statistic=f"{row['condition_id']}_mean",
            denominator_scope="answer_all", denominator=int(row["denominator"]), value=float(row["mean"]),
            decimals=1, direction="not_directional", source_artifact="stage-d/process-condition-summaries.jsonl",
            source_row=row,
        )
    for row in process_paired:
        if row.get("mean_paired_difference") is None:
            continue
        unit = unit_index[(str(row["backbone_id"]), str(row["comparison_id"]))]
        add(
            context="process_paired", section=str(unit["section_id"]), backbone=str(row["backbone_id"]),
            comparison=str(row["comparison_id"]), metric=str(row["metric_id"]), statistic="mean_paired_difference",
            denominator_scope="answer_all", denominator=QUESTION_COUNT,
            value=float(row["mean_paired_difference"]), decimals=1, direction="target_minus_baseline",
            source_artifact="stage-d/process-paired-summaries.jsonl", source_row=row,
            result_unit_id=str(unit["result_unit_id"]), evidence_code=str(unit["architecture_evidence_code"]),
        )

    for row in figure:
        add(
            context="Figure 5.3", section="5.2.3", backbone=str(row["backbone_id"]), comparison=None,
            metric=str(row["metric_id"]), statistic=f"{row['condition_id']}_mean",
            denominator_scope="evidence_eligible" if int(row["denominator"]) == 58 else "answer_all",
            denominator=int(row["denominator"]), value=float(row["mean"]), decimals=4,
            direction="not_directional", source_artifact="stage-b/figure-5-3-data.jsonl", source_row=row,
        )
    for row in table:
        comparison = str(row["contrast_id"])
        unit = unit_index[(str(row["backbone_id"]), comparison)]
        add(
            context="Table 5.3", section="5.2.4", backbone=str(row["backbone_id"]), comparison=comparison,
            metric=str(row["metric_id"]), statistic="mean_target_minus_baseline",
            denominator_scope="evidence_eligible" if int(row["denominator"]) == 58 else "answer_all",
            denominator=int(row["denominator"]), value=float(row["mean_difference"]), decimals=4,
            direction="target_minus_baseline", source_artifact="stage-c/table-5-3-data.jsonl", source_row=row,
            result_unit_id=str(unit["result_unit_id"]), evidence_code=str(unit["architecture_evidence_code"]),
        )
    cost = s3_cost[0]
    for field in (
        "episodes", "llm_calls", "rounds", "tool_calls", "prompt_tokens", "completion_tokens",
        "total_tokens", "store_bytes", "store_files", "store_headings", "store_lines",
        "locator_mentions", "unique_locators_referenced", "source_locators_available",
    ):
        add(
            context="Table 5.3 S3 one-time build cost", section="5.2.4", backbone=None,
            comparison=None, metric="s3_build_cost", statistic=field, denominator_scope="one_time_build",
            denominator=None, value=int(cost[field]), decimals=0, direction="not_directional",
            source_artifact="experiments/locomo-conv50-v1/manifests/s3-curated.json", source_row=cost,
        )
    return rows


def _audit_tables(tables: Mapping[str, Sequence[Mapping[str, Any]]]) -> dict[str, Any]:
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
    }
    actual = {name: len(rows) for name, rows in tables.items()}
    for name, count in expected_counts.items():
        _require(actual.get(name) == count, f"Stage E table row count differs: {name}")

    units = tables["result-unit-register"]
    _require(len({row["result_unit_id"] for row in units}) == 16, "Result-unit IDs repeat")
    _require(len({row["architecture_evidence_code"] for row in units}) == 16, "Architecture evidence codes repeat")
    _require(Counter(row["effect_status"] for row in units) == {"core_effect": 12, "descriptive_complete_system_anchor": 4}, "Result-unit roles differ")
    _require({row["backbone_id"] for row in units} == set(BACKBONES), "Result-unit backbones differ")
    _require(all(row["backbone_pooling_permitted"] is False for row in units), "Backbone pooling was enabled")
    for row in units:
        spec = RESULT_SPEC_BY_ID[str(row["comparison_id"])]
        if spec.comparison_type == "simple":
            _require(row["difference_direction"] == "target_minus_baseline", "Simple-effect direction differs")
            _require(row["baseline_condition"] == spec.baseline_condition, "Simple-effect baseline differs")
            _require(row["target_condition"] == spec.target_condition, "Simple-effect target differs")
        else:
            _require(row["difference_direction"] == "difference_in_differences", "DID direction differs")

    metrics = tables["main-metrics"]
    metric_groups = Counter(row["result_unit_id"] for row in metrics)
    _require(set(metric_groups.values()) == {len(PRIMARY_METRICS)}, "Main-metric coverage differs")
    for row in metrics:
        expected_n = EVIDENCE_ELIGIBLE_COUNT if row["metric_id"] == "evidence_recall" else QUESTION_COUNT
        _require(int(row["denominator"]) == expected_n, "Main-metric denominator differs")
        _require(math.isfinite(float(row["point_estimate"])), "Main-metric estimate is not finite")

    denominator_by_scope = {
        "answer_all": QUESTION_COUNT,
        "evidence_eligible": EVIDENCE_ELIGIBLE_COUNT,
        "multi_gold_source_evidence_eligible": EXPECTED_MULTI_GOLD_SOURCE_COUNT,
    }
    neutral_metrics = {"partial_rate", "evidence_bundle_characters"}
    condition_rows = tables["condition-summaries"]
    condition_groups = Counter((row["backbone_id"], row["condition_id"]) for row in condition_rows)
    _require(
        condition_groups
        == Counter((backbone, condition) for backbone in BACKBONES for condition in ("E1", "E2", "E3", "E4", "E5", "E6") for _ in range(13)),
        "Condition-summary metric coverage differs",
    )
    condition_index = {
        (str(row["backbone_id"]), str(row["condition_id"]), str(row["metric_id"])): row
        for row in condition_rows
    }
    for row in condition_rows:
        _require(int(row["denominator"]) == denominator_by_scope[str(row["denominator_scope"])], "Condition denominator differs")
        expected_direction = "neutral" if row["metric_id"] in neutral_metrics else "higher_is_better"
        _require(row["metric_direction"] == expected_direction, "Condition metric direction differs")

    paired_rows = tables["paired-effect-summaries"]
    paired_groups = Counter((row["backbone_id"], row["contrast_id"]) for row in paired_rows)
    _require(
        paired_groups == Counter((backbone, comparison) for backbone in BACKBONES for comparison in MAIN_SIMPLE_IDS for _ in range(13)),
        "Paired-effect metric coverage differs",
    )
    for row in paired_rows:
        _require(int(row["denominator"]) == denominator_by_scope[str(row["denominator_scope"])], "Paired-effect denominator differs")
        expected_direction = "neutral" if row["metric_id"] in neutral_metrics else "higher_is_better"
        _require(row["metric_direction"] == expected_direction, "Paired-effect metric direction differs")
        baseline = condition_index[(str(row["backbone_id"]), str(row["baseline_condition"]), str(row["metric_id"]))]
        target = condition_index[(str(row["backbone_id"]), str(row["target_condition"]), str(row["metric_id"]))]
        _require(math.isclose(float(row["baseline_mean"]), float(baseline["mean"]), abs_tol=TIE_TOLERANCE), "Paired baseline mean differs")
        _require(math.isclose(float(row["target_mean"]), float(target["mean"]), abs_tol=TIE_TOLERANCE), "Paired target mean differs")
        _require(
            math.isclose(float(row["mean_difference"]), float(row["target_mean"]) - float(row["baseline_mean"]), abs_tol=TIE_TOLERANCE),
            "Paired target-minus-baseline arithmetic differs",
        )

    interaction_rows = tables["interaction-effect-summaries"]
    interaction_groups = Counter(row["backbone_id"] for row in interaction_rows)
    _require(interaction_groups == Counter({"qwen": 13, "deepseek": 13}), "Interaction metric coverage differs")
    for row in interaction_rows:
        _require(int(row["denominator"]) == denominator_by_scope[str(row["denominator_scope"])], "Interaction denominator differs")
        expected_direction = "neutral" if row["metric_id"] in neutral_metrics else "higher_is_better"
        _require(row["metric_direction"] == expected_direction, "Interaction metric direction differs")
        expected_did = float(row["mean_storage_r2_e4_minus_e2"]) - float(row["mean_storage_r1_e3_minus_e1"])
        _require(math.isclose(float(row["mean_did"]), expected_did, abs_tol=TIE_TOLERANCE), "Interaction arithmetic differs")

    bootstrap = tables["selected-bootstrap"]
    expected_bootstrap = {
        (backbone, effect, metric)
        for backbone in BACKBONES
        for effect in (
            "storage_r1_e3_minus_e1", "storage_r2_e4_minus_e2",
            "retrieval_s1_e2_minus_e1", "retrieval_s2_e4_minus_e3",
            STAGE_B_INTERACTION_ID,
        )
        for metric in BOOTSTRAP_METRICS
    }
    _require(
        {(row["backbone_id"], row["effect_id"], row["metric_id"]) for row in bootstrap} == expected_bootstrap,
        "Selected bootstrap set differs",
    )
    _require(all(row["replicates"] == 10000 and row["random_seed"] == 20261021 for row in bootstrap), "Bootstrap settings differ")

    strict_groups: dict[tuple[str, str], list[Mapping[str, Any]]] = defaultdict(list)
    for row in tables["strict-transitions"]:
        strict_groups[(str(row["backbone_id"]), str(row["comparison_id"]))].append(row)
    _require(len(strict_groups) == 14, "Strict-transition result-unit count differs")
    for rows in strict_groups.values():
        _require(len(rows) == 4 and sum(int(row["count"]) for row in rows) == QUESTION_COUNT, "Strict-transition total differs")

    semantic_groups: dict[tuple[str, str], list[Mapping[str, Any]]] = defaultdict(list)
    for row in tables["semantic-transitions"]:
        semantic_groups[(str(row["backbone_id"]), str(row["contrast_id"]))].append(row)
    _require(len(semantic_groups) == 14, "Semantic-transition result-unit count differs")
    for rows in semantic_groups.values():
        _require(len(rows) == 9 and sum(int(row["count"]) for row in rows) == QUESTION_COUNT, "Semantic-transition total differs")
        _require(
            {(row["baseline_label"], row["target_label"]) for row in rows}
            == {(left, right) for left in ("correct", "partial", "incorrect") for right in ("correct", "partial", "incorrect")},
            "Semantic-transition matrix is incomplete",
        )

    for table_name in ("conversion-matrices", "conversion-summaries"):
        _require({row["comparison_id"] for row in tables[table_name]} == MAIN_SIMPLE_IDS, f"{table_name} comparison scope differs")
        _require({int(row["denominator"]) for row in tables[table_name]} == {19, 58}, f"{table_name} denominators differ")
    conversion_groups: dict[tuple[Any, ...], list[Mapping[str, Any]]] = defaultdict(list)
    for row in tables["conversion-matrices"]:
        conversion_groups[(row["comparison_id"], row["backbone_id"], row["subset_id"], row["answer_metric_id"])].append(row)
    _require(len(conversion_groups) == 84, "Conversion matrix group count differs")
    for key, rows in conversion_groups.items():
        expected_n = 58 if key[2] == "evidence_eligible_58" else 19
        _require(len(rows) == 9 and sum(int(row["count"]) for row in rows) == expected_n, "Conversion matrix total differs")

    for row in tables["category-effects"]:
        expected_n = EXPECTED_EVIDENCE_CATEGORIES[int(row["category"])] if row["metric_id"] == "evidence_recall" else EXPECTED_CATEGORIES[int(row["category"])]
        _require(int(row["denominator"]) == expected_n, "Category denominator differs")
    for row in tables["category-interactions"]:
        expected_n = EXPECTED_EVIDENCE_CATEGORIES[int(row["category"])] if row["metric_id"] == "evidence_recall" else EXPECTED_CATEGORIES[int(row["category"])]
        _require(int(row["denominator"]) == expected_n, "Category interaction denominator differs")

    _require(
        not ({row["comparison_id"] for row in tables["process-paired-summaries"]} & SENSITIVITY_IDS),
        "Appendix sensitivity leaked into main process table",
    )
    _require({row["comparison_id"] for row in tables["process-paired-summaries"]} == MAIN_SIMPLE_IDS, "Process comparison scope differs")
    for row in tables["process-condition-summaries"]:
        if row["metric_id"] in {"native_latency_ms", "failed_attempt_tokens"}:
            _require(
                row["applicable"] is False and int(row["denominator"]) == 0 and row["mean"] is None,
                "Unavailable process measure was materialised as a value",
            )
        if str(row["metric_id"]).startswith("r1_"):
            _require(bool(row["applicable"]) == (row["condition_id"] in {"E1", "E3", "E5"}), "R1 native-unit applicability differs")
        if row["metric_id"] == "ranked_retrieval_actions":
            _require(bool(row["applicable"]) == (row["condition_id"] in {"E2", "E4", "E6"}), "Ranked-action applicability differs")
    for row in tables["process-paired-summaries"]:
        if not row["paired_comparison_allowed"]:
            _require(
                row["mean_paired_difference"] is None and row["median_paired_difference"] is None,
                "Noncommensurate process units were subtracted",
            )
    _require({row["figure_id"] for row in tables["figure-5-3-inputs"]} == {"Figure 5.3"}, "Figure identity differs")
    _require({row["table_id"] for row in tables["table-5-3-inputs"]} == {"Table 5.3"}, "Table identity differs")

    cost = tables["s3-build-cost-summary"][0]
    _require(cost["cost_scope"] == "one_time_s3_construction", "S3 cost scope differs")
    _require(cost["included_in_main_effect_estimates"] is False, "S3 build cost entered a main effect")
    _require(cost["pareto_analysis_input"] is False and cost["amortised_cost"] is False, "S3 cost crossed the RQ1 boundary")
    _require(cost["total_tokens"] == 30_864_958, "S3 build token total differs")

    codes = tables["architecture-evidence-codes"]
    _require({row["architecture_evidence_code"] for row in codes} == {row["architecture_evidence_code"] for row in units}, "Architecture code coverage differs")
    _require(
        all(row["causal_component_claim_permitted"] is False for row in codes if row["effect_status"] == "descriptive_complete_system_anchor"),
        "Descriptive anchor was coded as causal",
    )
    _require(all(row["cross_backbone_inference_permitted"] is False for row in codes), "Cross-backbone inference was enabled")

    display = tables["display-number-register"]
    _require(bool(display), "Display-number register is empty")
    _require(len({row["display_number_id"] for row in display}) == len(display), "Display-number IDs repeat")
    _require(all(isinstance(row["raw_value"], (int, float)) and math.isfinite(float(row["raw_value"])) for row in display), "Display register contains non-finite number")
    _require(all(row["denominator"] in {None, 5, 7, 13, 19, 27, 58, 60} for row in display), "Display denominator escaped the contract")

    forbidden_ids = SENSITIVITY_IDS | {"E7", "Full Context", "full_context"}
    prohibited_fields = {
        "question", "question_text", "reference_answer", "gold_answer", "candidate_answer",
        "answer", "answer_text", "evidence", "evidence_text", "judge_rationale",
        "short_reason", "prompt", "api_key", "authorization", "credential", "secret",
    }
    for name, rows in tables.items():
        if name == "display-number-register":
            continue
        for row in rows:
            _require(prohibited_fields.isdisjoint(row), f"Text-bearing or credential field leaked into {name}")
            for field in ("condition_id", "baseline_condition", "target_condition", "comparison_id"):
                _require(row.get(field) not in forbidden_ids, f"Forbidden RQ1 scope leaked into {name}")

    return {
        "table_rows": actual,
        "result_units": 16,
        "core_result_units": 12,
        "descriptive_result_units": 4,
        "answer_denominator": QUESTION_COUNT,
        "evidence_denominator": EVIDENCE_ELIGIBLE_COUNT,
        "multi_gold_source_denominator": EXPECTED_MULTI_GOLD_SOURCE_COUNT,
        "target_minus_baseline_directions_verified": True,
        "bootstrap_set_frozen_without_recomputation": True,
        "architecture_evidence_codes_verified": True,
        "display_number_register_verified": True,
        "complete_thirteen_metric_reconciliation_verified": True,
        "partial_rate_semantic_transition_context_verified": True,
        "prohibited_text_and_credentials_absent": True,
        "process_native_units_and_unavailable_values_verified": True,
        "cross_backbone_inference_computed": False,
        "e7_computed": False,
        "full_context_computed": False,
        "global_error_census_computed": False,
        "pareto_analysis_computed": False,
    }


def _compute_stage_e(
    *,
    repo_root: Path,
    stage_a_dir: Path,
    stage_b_dir: Path,
    stage_c_dir: Path,
    stage_d_dir: Path,
    s3_manifest_path: Path,
) -> tuple[dict[str, list[dict[str, Any]]], dict[str, Any], dict[str, Any]]:
    provenance, inputs = _validate_inputs(
        repo_root=repo_root, stage_a_dir=stage_a_dir, stage_b_dir=stage_b_dir,
        stage_c_dir=stage_c_dir, stage_d_dir=stage_d_dir, s3_manifest_path=s3_manifest_path,
    )
    sources = _load_source_tables(stage_b_dir, stage_c_dir, stage_d_dir)
    units = _result_unit_register(sources)
    metrics = _main_metrics(units, sources)
    strict = _strict_transitions(units, sources)
    bootstrap = [dict(row) for row in sources["b_bootstrap"]]
    condition_summaries, paired_effects, interaction_effects, semantic_transitions = (
        _reconciliation_tables(sources)
    )
    process_paired = [
        dict(row) for row in sources["d_process_paired"]
        if row.get("comparison_id") in MAIN_SIMPLE_IDS
    ]
    architecture_effects, architecture_codes = _architecture_tables(
        units, metrics, strict, bootstrap, sources["d_trace_review"]
    )
    s3_cost = _s3_build_cost_summary(inputs["s3"])
    tables: dict[str, list[dict[str, Any]]] = {
        "result-unit-register": units,
        "main-metrics": metrics,
        "condition-summaries": condition_summaries,
        "paired-effect-summaries": paired_effects,
        "interaction-effect-summaries": interaction_effects,
        "architecture-effects": architecture_effects,
        "architecture-evidence-codes": architecture_codes,
        "selected-bootstrap": bootstrap,
        "strict-transitions": strict,
        "semantic-transitions": semantic_transitions,
        "conversion-matrices": [dict(row) for row in sources["d_conversion_matrices"]],
        "conversion-summaries": [dict(row) for row in sources["d_conversion_summaries"]],
        "category-effects": [dict(row) for row in sources["d_category"]],
        "category-interactions": [dict(row) for row in sources["d_category_interaction"]],
        "process-condition-summaries": [dict(row) for row in sources["d_process_condition"]],
        "process-paired-summaries": process_paired,
        "figure-5-3-inputs": [dict(row) for row in sources["b_figure"]],
        "table-5-3-inputs": [dict(row) for row in sources["c_table"]],
        "s3-build-cost-summary": s3_cost,
        "trace-review-evidence": [dict(row) for row in sources["d_trace_review"]],
    }
    tables["display-number-register"] = _display_number_register(
        units=units, metrics=metrics, paired_effects=paired_effects,
        interaction_effects=interaction_effects, bootstrap=bootstrap, strict=strict,
        conversion=tables["conversion-summaries"], category=tables["category-effects"],
        category_interactions=tables["category-interactions"],
        process_condition=tables["process-condition-summaries"],
        process_paired=tables["process-paired-summaries"],
        figure=tables["figure-5-3-inputs"], table=tables["table-5-3-inputs"], s3_cost=s3_cost,
    )
    table_audit = _audit_tables(tables)
    for table_name, source_stem in (
        ("figure-5-3-inputs", stage_b_dir / "figure-5-3-data"),
        ("table-5-3-inputs", stage_c_dir / "table-5-3-data"),
    ):
        _require(
            _jsonl_payload(tables[table_name]) == source_stem.with_suffix(".jsonl").read_bytes(),
            f"{table_name} JSONL is not byte-identical to its frozen input",
        )
        _require(
            _csv_payload(tables[table_name]) == source_stem.with_suffix(".csv").read_bytes(),
            f"{table_name} CSV is not byte-identical to its frozen input",
        )
    table_audit["figure_5_3_and_table_5_3_inputs_byte_identical"] = True
    return tables, provenance, {"input_audit": inputs["input_audit"], "table_audit": table_audit}


def _readme() -> str:
    return """# Chapter 5 Stage E — final RQ1 audit\n\nThis is the audited publication gate for Chapter 5 RQ1. It fixes exactly 16\nwithin-backbone main-text result units: six core effects and two descriptive\ncomplete-system anchors under each backbone. All simple effects are target\nminus baseline; the interaction is `(E4-E2)-(E3-E1)`.\n\nThe artifact freezes a compact six-metric main table and complete 13-metric\ncondition/effect reconciliation tables, the existing Stage B bootstrap set,\nStrict and 3x3 semantic transitions, Evidence-to-answer conversion, category\nand process inputs, Figure 5.3 and Table 5.3 inputs, bounded Stage D trace\nevidence, a display-number register, and architecture-evidence codes. Answer,\nEvidence, and multi-source denominators remain 60, 58, and 19 respectively.\nPartial Rate and EvidenceBundle length remain neutral/descriptive.\n\nThe four compact conversion counts are selected diagnostic cells, not an\nexhaustive partition; the complete 3x3 matrices are the denominator-preserving\nsource. The 24 reviewed traces explain selected cases and are not a prevalence\ncensus. Bootstrap intervals describe resampling stability across the observed\nMain-60 questions, not variation across conversations.\n\nThe S3 construction row is a one-time descriptive build cost. It is not a\nquery-time cost, a main effect, an amortised cost, or a Pareto input. No new\nbootstrap or question-level experiment is computed here. E7, Full Context,\ncross-backbone inference, a global error census, Pareto analysis, system\nrecommendation, and final report prose are outside this artifact.\n"""


def _field_schema(tables: Mapping[str, Sequence[Mapping[str, Any]]]) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "protocol_version": STAGE_E_PROTOCOL_VERSION,
        "tables": {
            name: {
                "row_count": len(rows),
                "fields": list(rows[0]) if rows else [],
                "field_types": {
                    field: sorted({type(row[field]).__name__ for row in rows})
                    for field in rows[0]
                } if rows else {},
            }
            for name, rows in tables.items()
        },
    }


def _source_manifest(
    *,
    repo_root: Path,
    stage_a_dir: Path,
    stage_b_dir: Path,
    stage_c_dir: Path,
    stage_d_dir: Path,
    s3_manifest_path: Path,
    provenance: Mapping[str, Any],
) -> dict[str, Any]:
    body = {
        "schema_version": 1,
        "protocol_version": STAGE_E_PROTOCOL_VERSION,
        "scope": "final audited RQ1 publication inputs; unified Main-60 E1--E6 within backbone",
        "stage_a_directory": _relative(repo_root, stage_a_dir),
        "stage_b_directory": _relative(repo_root, stage_b_dir),
        "stage_c_directory": _relative(repo_root, stage_c_dir),
        "stage_d_directory": _relative(repo_root, stage_d_dir),
        "s3_manifest_path": _relative(repo_root, s3_manifest_path),
        **dict(provenance),
        "backbones": list(BACKBONES),
        "conditions": ["E1", "E2", "E3", "E4", "E5", "E6"],
        "main_result_unit_count": 16,
        "core_result_unit_count": 12,
        "descriptive_result_unit_count": 4,
        "answer_denominator": QUESTION_COUNT,
        "evidence_denominator": EVIDENCE_ELIGIBLE_COUNT,
        "multi_gold_source_denominator": EXPECTED_MULTI_GOLD_SOURCE_COUNT,
        "difference_direction": "target_minus_baseline_except_declared_difference_in_differences",
        "s3_build_cost_scope": "one_time_non_main_effect",
        "compact_conversion_cells_exhaustive": False,
        "bounded_trace_review_is_prevalence_census": False,
        "bootstrap_generalisation_scope": "observed_main60_questions_not_conversations",
        "no_api_calls": True,
        "formal_source_mutation": False,
        "new_bootstrap_computed": False,
        "cross_backbone_inference_computed": False,
        "e7_computed": False,
        "full_context_computed": False,
        "global_error_census_computed": False,
        "pareto_analysis_computed": False,
        "system_recommendation_computed": False,
        "final_rq1_prose_computed": False,
        "old_new_question_split_computed": False,
    }
    return {"source_manifest_id": "stage-e-rq1-sources-" + sha256_bytes(canonical_json_bytes(body)), **body}


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
    *, audits: Mapping[str, Any], provenance: Mapping[str, Any],
    source_manifest: Mapping[str, Any], output_hashes: Mapping[str, str]
) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "protocol_version": STAGE_E_PROTOCOL_VERSION,
        "status": "passed",
        "scope": "final RQ1 numeric and architecture-evidence reconciliation",
        "no_api_calls": True,
        "formal_source_mutation": False,
        "new_bootstrap_computed": False,
        "cross_backbone_inference_computed": False,
        "e7_computed": False,
        "full_context_computed": False,
        "global_error_census_computed": False,
        "pareto_analysis_computed": False,
        "system_recommendation_computed": False,
        "final_rq1_prose_computed": False,
        "input_audit": audits["input_audit"],
        "table_audit": audits["table_audit"],
        "source_manifest_id": source_manifest["source_manifest_id"],
        **dict(provenance),
        "output_sha256": dict(output_hashes),
    }


def _marker(audit: Mapping[str, Any], audit_sha256: str) -> dict[str, Any]:
    return {
        "status": "passed",
        "protocol_version": STAGE_E_PROTOCOL_VERSION,
        "audit_id": audit["audit_id"],
        "audit_sha256": audit_sha256,
        "main_result_units": 16,
        "core_result_units": 12,
        "descriptive_result_units": 4,
        "answer_denominator": QUESTION_COUNT,
        "evidence_denominator": EVIDENCE_ELIGIBLE_COUNT,
        "multi_gold_source_denominator": EXPECTED_MULTI_GOLD_SOURCE_COUNT,
        "bootstrap_rows": 30,
        "new_bootstrap_computed": False,
        "no_api_calls": True,
    }


def build_stage_e(
    *,
    repo_root: Path,
    stage_a_dir: Path,
    stage_b_dir: Path,
    stage_c_dir: Path,
    stage_d_dir: Path,
    s3_manifest_path: Path,
    output_dir: Path,
) -> dict[str, Any]:
    root = repo_root.resolve()
    destination = output_dir.resolve()
    _require(not destination.exists() and not destination.is_symlink(), "Stage E output already exists")
    for label, source in (
        ("Stage A", stage_a_dir.resolve()),
        ("Stage B", stage_b_dir.resolve()),
        ("Stage C", stage_c_dir.resolve()),
        ("Stage D", stage_d_dir.resolve()),
    ):
        try:
            destination.relative_to(source)
        except ValueError:
            continue
        _require(False, f"Stage E output may not be published inside frozen {label}")
    tables, provenance, audits = _compute_stage_e(
        repo_root=root, stage_a_dir=stage_a_dir.resolve(), stage_b_dir=stage_b_dir.resolve(),
        stage_c_dir=stage_c_dir.resolve(), stage_d_dir=stage_d_dir.resolve(),
        s3_manifest_path=s3_manifest_path.resolve(),
    )
    manifest = _source_manifest(
        repo_root=root, stage_a_dir=stage_a_dir.resolve(), stage_b_dir=stage_b_dir.resolve(),
        stage_c_dir=stage_c_dir.resolve(), stage_d_dir=stage_d_dir.resolve(),
        s3_manifest_path=s3_manifest_path.resolve(), provenance=provenance,
    )
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=f".{destination.name}.in-progress-", dir=destination.parent))
    try:
        payloads = _artifact_payloads(tables, manifest)
        for name, payload in payloads.items():
            _write(temporary / name, payload)
        hashes = {name: _sha256_file(temporary / name) for name in sorted(payloads)}
        body = _audit_body(audits=audits, provenance=provenance, source_manifest=manifest, output_hashes=hashes)
        audit = {"audit_id": "stage-e-rq1-audit-" + sha256_bytes(canonical_json_bytes(body)), **body}
        _write(temporary / "audit.json", canonical_json_bytes(audit) + b"\n")
        marker = _marker(audit, _sha256_file(temporary / "audit.json"))
        _write(temporary / "STAGE-E-RQ1.PASSED", canonical_json_bytes(marker) + b"\n")
        result = audit_stage_e_output(
            repo_root=root, stage_a_dir=stage_a_dir, stage_b_dir=stage_b_dir,
            stage_c_dir=stage_c_dir, stage_d_dir=stage_d_dir,
            s3_manifest_path=s3_manifest_path, output_dir=temporary,
        )
        _require(result["status"] == "passed", "Stage E pre-publication audit failed")
        _require(not destination.exists(), "Stage E output appeared during build")
        os.rename(temporary, destination)
        descriptor = os.open(destination.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
    except Exception:
        shutil.rmtree(temporary, ignore_errors=True)
        raise
    return audit_stage_e_output(
        repo_root=root, stage_a_dir=stage_a_dir, stage_b_dir=stage_b_dir,
        stage_c_dir=stage_c_dir, stage_d_dir=stage_d_dir,
        s3_manifest_path=s3_manifest_path, output_dir=destination,
    )


def audit_stage_e_output(
    *,
    repo_root: Path,
    stage_a_dir: Path,
    stage_b_dir: Path,
    stage_c_dir: Path,
    stage_d_dir: Path,
    s3_manifest_path: Path,
    output_dir: Path,
) -> dict[str, Any]:
    root = repo_root.resolve()
    output = output_dir.resolve()
    _require(output.is_dir() and not output.is_symlink(), "Stage E output directory is unsafe")
    tables, provenance, audits = _compute_stage_e(
        repo_root=root, stage_a_dir=stage_a_dir.resolve(), stage_b_dir=stage_b_dir.resolve(),
        stage_c_dir=stage_c_dir.resolve(), stage_d_dir=stage_d_dir.resolve(),
        s3_manifest_path=s3_manifest_path.resolve(),
    )
    manifest = _source_manifest(
        repo_root=root, stage_a_dir=stage_a_dir.resolve(), stage_b_dir=stage_b_dir.resolve(),
        stage_c_dir=stage_c_dir.resolve(), stage_d_dir=stage_d_dir.resolve(),
        s3_manifest_path=s3_manifest_path.resolve(), provenance=provenance,
    )
    payloads = _artifact_payloads(tables, manifest)
    hashes = {name: hashlib.sha256(payload).hexdigest() for name, payload in sorted(payloads.items())}
    body = _audit_body(audits=audits, provenance=provenance, source_manifest=manifest, output_hashes=hashes)
    expected_audit = {"audit_id": "stage-e-rq1-audit-" + sha256_bytes(canonical_json_bytes(body)), **body}
    audit_payload = canonical_json_bytes(expected_audit) + b"\n"
    expected_marker = _marker(expected_audit, hashlib.sha256(audit_payload).hexdigest())
    marker_payload = canonical_json_bytes(expected_marker) + b"\n"
    expected_names = set(payloads) | {"audit.json", "STAGE-E-RQ1.PASSED"}
    entries = list(output.iterdir())
    _require(all(entry.is_file() and not entry.is_symlink() for entry in entries), "Stage E output contains unsafe entry")
    _require({entry.name for entry in entries} == expected_names, "Stage E output file set differs")
    for name, payload in payloads.items():
        _require((output / name).read_bytes() == payload, f"Stage E artifact bytes differ: {name}")
    _require((output / "audit.json").read_bytes() == audit_payload, "Stage E audit bytes differ")
    _require((output / "STAGE-E-RQ1.PASSED").read_bytes() == marker_payload, "Stage E marker bytes differ")
    return {
        "status": "passed",
        "protocol_version": STAGE_E_PROTOCOL_VERSION,
        "audit_id": expected_audit["audit_id"],
        "main_result_units": 16,
        "core_result_units": 12,
        "descriptive_result_units": 4,
        "answer_denominator": QUESTION_COUNT,
        "evidence_denominator": EVIDENCE_ELIGIBLE_COUNT,
        "multi_gold_source_denominator": EXPECTED_MULTI_GOLD_SOURCE_COUNT,
        "bootstrap_rows": 30,
        "table_rows": audits["table_audit"]["table_rows"],
        "output_dir": str(output),
        "no_api_calls": True,
    }


# Descriptive aliases make the public API explicit without breaking the shorter
# convention used by Stages B--D.
build_stage_e_rq1 = build_stage_e
audit_stage_e_rq1_output = audit_stage_e_output


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build or audit Chapter 5 Stage E RQ1 artifacts")
    parser.add_argument("command", choices=("build", "audit"))
    parser.add_argument("--repo-root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--stage-a-dir", type=Path, required=True)
    parser.add_argument("--stage-b-dir", type=Path, required=True)
    parser.add_argument("--stage-c-dir", type=Path, required=True)
    parser.add_argument("--stage-d-dir", type=Path, required=True)
    parser.add_argument("--s3-manifest", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    return parser


def main(argv: list[str] | None = None) -> None:
    args = _parser().parse_args(argv)
    kwargs = {
        "repo_root": args.repo_root,
        "stage_a_dir": args.stage_a_dir,
        "stage_b_dir": args.stage_b_dir,
        "stage_c_dir": args.stage_c_dir,
        "stage_d_dir": args.stage_d_dir,
        "s3_manifest_path": args.s3_manifest,
        "output_dir": args.output_dir,
    }
    result = build_stage_e(**kwargs) if args.command == "build" else audit_stage_e_output(**kwargs)
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
