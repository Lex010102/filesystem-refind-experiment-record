"""Build and audit the automatic Chapter 5 Stage D mechanism analysis.

Stage D consumes the exact formal Stage A, B, and C publications.  It joins
their text-free question-level records by frozen identities and produces the
pre-declared mechanism tables used by the bounded RQ1 analysis:

* Evidence-Recall change by answer change, with Strict as the primary outcome;
* All-hit change by Strict change;
* descriptive C1--C4 simple-effect and interaction matrices;
* E1--E6 process summaries with architecture-specific units kept separate;
* deterministic, identifier-only candidates for later manual trace review.

This module implements only the automatic phase.  A successful build emits
``STAGE-D-AUTO.PASSED`` and leaves every trace candidate at ``pending``.  It
never emits ``STAGE-D.PASSED``: that final marker is reserved for a separate
future finalizer after the bounded manual review is genuinely complete.

No source trace, question, answer, Evidence text, or Judge rationale is read or
copied.  No model API is called, no bootstrap is run, and no RQ2, E7, Full
Context, global error census, Pareto analysis, recommendation, or final RQ1
conclusion is computed here.
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
from typing import Any, Iterable, Mapping, Sequence

from .chapter5_stage_a import STAGE_A_PROTOCOL_VERSION
from .chapter5_stage_b import (
    BACKBONES,
    EVIDENCE_ELIGIBLE_COUNT,
    EXPECTED_CATEGORIES,
    EXPECTED_EVIDENCE_CATEGORIES,
    EXPECTED_MULTI_GOLD_SOURCE_COUNT,
    QUESTION_COUNT,
    STAGE_B_PROTOCOL_VERSION,
    TIE_TOLERANCE,
    _csv_payload,
    _id,
    _is_close,
    _jsonl_payload,
    _mean,
    _median,
    _no_text_bearing_fields,
    _read_json,
    _read_jsonl,
    _relative,
    _require,
    _sha256_file,
    _state,
    _write,
)
from .chapter5_stage_c import (
    EXPECTED_DESIGN,
    STAGE_C_PROTOCOL_VERSION,
    _validate_input as _validate_stage_a_rows,
    audit_stage_c_output,
)
from .evidence import canonical_json_bytes, sha256_bytes


STAGE_D_PROTOCOL_VERSION = "chapter5-main60-stage-d-v1"
STAGE_D_CONDITIONS = ("E1", "E2", "E3", "E4", "E5", "E6")
INTERACTION_ID = "storage_retrieval_did_e4_e2_minus_e3_e1"

EXPECTED_STAGE_A_AUDIT_ID = "stage-a-audit-5f55ec411f097df7206fdae5e71742641aa8868b4128ac32262f034877a1d7f3"
EXPECTED_STAGE_A_SOURCE_MANIFEST_ID = "stage-a-sources-90efa256f7981450cf38503912406a1e30766e8440b443899cab953fe9fece3c"
EXPECTED_STAGE_A_HASHES = {
    "audit.json": "39aee6ea88c92df547cc98f7b6b343415a558d31a354184e30f0d36acc331966",
    "STAGE-A.PASSED": "f4b3aa6f80d2ee7bc4eb9682e37ec85780d4f37a15b22ef65eb78e46ee6f3e34",
    "source-manifest.json": "2b1f56d0897904fb9d4b8487111ecc2d7b55848f54f97dbfe34de53c16b59a65",
    "schema.json": "21295503a3b8e0cadcde9a61a46be1e383c38da329dbc66d716b78faa72ede09",
    "rq1-analysis-view.jsonl": "f7223ae5605cec0a00042022e41b5ac9e0c0ec438b0bdc05340813be415855df",
}

EXPECTED_STAGE_B_AUDIT_ID = "stage-b-audit-2c5061c3db5cba00f099648963eaa2175d1136954e4cf673720423e7ffed6932"
EXPECTED_STAGE_B_SOURCE_MANIFEST_ID = "stage-b-sources-430f42b4398f2859091ad42f74000e3b6f712ed2c7c43606fc3d318afa1b6686"
EXPECTED_STAGE_B_HASHES = {
    "audit.json": "67b638bccad3f664a8eec9f0e9f11554f777c336888c95d0594bbdb96d11e526",
    "STAGE-B.PASSED": "b137218da5cae7f2458dabf3322d6a88be6b616dcd57df6210cda02e0eabbfa2",
    "source-manifest.json": "71019dfb5af934645c45c073ae6eaeb5e9c6673ca90a627cdf03bee086f200bd",
    "schema.json": "d8a2bf7113e4cc5247ee6eaba7b660395acfef51dbfce3d2541b165103116362",
    "paired-question-effects.jsonl": "016cb6f6456d30b850285f4ea02dce761e7fff96aab907c4bb64b93259693fbe",
    "interaction-question-effects.jsonl": "6db2b26bf52a3ecc3f10b5c518abcbcb1ce3cf2e6f43c7eace86f04b0219ba43",
}

EXPECTED_STAGE_C_AUDIT_ID = "stage-c-audit-a199de52d8b0011d837334e6dbf37bbfac446653753b5b74a35732ae32da1a31"
EXPECTED_STAGE_C_SOURCE_MANIFEST_ID = "stage-c-sources-83a0e867422117fc9b92d14da11d960b5faf8c308cfb11d0d3bc49c47159455e"
EXPECTED_STAGE_C_HASHES = {
    "audit.json": "fef87f523a6850c0fd1a7940a1aceb526e2c94f6ff3722d9b400c49ea063ea5a",
    "STAGE-C.PASSED": "670b4f7161d2ab871a1af756dcbd6b55715f10c834adb6f4a1b718ce3f9c395c",
    "source-manifest.json": "f2cef85599a7bea814afd4c650a7d8cd64e0192197d8c52682d5ca4508091d54",
    "schema.json": "f0d890541090a452a47e2b3e539310999632ffa44830a0e69be68cbdddab435e",
    "paired-question-effects.jsonl": "43e4c47d3ebe2e81da9b3caf76415e968fe2e1d89aa35f675f7343cb747cacaa",
    "contrast-register.jsonl": "62e415965fb76888c4dcb68761ee3dd5465c71b43dea85820314f649c136e8b8",
}

EXPECTED_STAGE_B_PAIRED_ROWS = 5_192
EXPECTED_STAGE_B_INTERACTION_ROWS = 1_298
EXPECTED_STAGE_C_PAIRED_ROWS = 6_490
ANSWER_CHANGE_METRICS = ("strict_accuracy", "token_f1", "soft_semantic_score")
CATEGORY_METRICS = ("token_f1", "strict_accuracy", "soft_semantic_score", "evidence_recall")
METRIC_SOURCE_FIELDS = {
    "token_f1": "token_f1",
    "strict_accuracy": "strict_score",
    "soft_semantic_score": "soft_semantic_score",
    "evidence_recall": "evidence_recall",
}
EVIDENCE_STATES = ("up", "same", "down")
ANSWER_STATES = ("improve", "same", "decline")
CATEGORY_ORDER = (1, 2, 3, 4)
EXPECTED_CATEGORY_NAMES = {
    1: "multi-hop",
    2: "temporal",
    3: "open-domain",
    4: "single-hop",
}


@dataclass(frozen=True)
class ComparisonSpec:
    comparison_id: str
    source_stage: str
    comparison_type: str
    baseline_condition: str | None
    target_condition: str | None
    comparison_family: str
    publication_role: str
    analysis_module: str


MAIN_SIMPLE_COMPARISONS = (
    ComparisonSpec(
        "storage_r1_e3_minus_e1", "stage_b", "simple", "E1", "E3",
        "storage_organisation", "main_core", "5.2.1",
    ),
    ComparisonSpec(
        "storage_r2_e4_minus_e2", "stage_b", "simple", "E2", "E4",
        "storage_organisation", "main_core", "5.2.1",
    ),
    ComparisonSpec(
        "retrieval_s1_e2_minus_e1", "stage_b", "simple", "E1", "E2",
        "retrieval_system", "main_core", "5.2.2",
    ),
    ComparisonSpec(
        "retrieval_s2_e4_minus_e3", "stage_b", "simple", "E3", "E4",
        "retrieval_system", "main_core", "5.2.2",
    ),
    ComparisonSpec(
        "curated_access_e6_minus_e5", "stage_c", "simple", "E5", "E6",
        "curated_access_system", "main_core", "5.2.4",
    ),
    ComparisonSpec(
        "curated_vs_foldered_r1_e5_minus_e3", "stage_c", "simple", "E3", "E5",
        "curated_memory_complete_system", "main_descriptive", "5.2.4",
    ),
    ComparisonSpec(
        "curated_adapted_vs_foldered_raw_e6_minus_e4", "stage_c", "simple", "E4", "E6",
        "curated_adapted_complete_system", "main_descriptive", "5.2.4",
    ),
)

SENSITIVITY_COMPARISONS = (
    ComparisonSpec(
        "curated_vs_flat_r1_e5_minus_e1", "stage_c", "simple", "E1", "E5",
        "curated_memory_sensitivity", "appendix_sensitivity", "5.2.4",
    ),
    ComparisonSpec(
        "curated_adapted_vs_flat_raw_e6_minus_e2", "stage_c", "simple", "E2", "E6",
        "curated_adapted_sensitivity", "appendix_sensitivity", "5.2.4",
    ),
)

INTERACTION_COMPARISON = ComparisonSpec(
    INTERACTION_ID,
    "stage_b",
    "interaction",
    None,
    None,
    "storage_by_retrieval",
    "main_core_interaction",
    "5.2.3",
)
SIMPLE_COMPARISONS = MAIN_SIMPLE_COMPARISONS + SENSITIVITY_COMPARISONS
# Evidence-to-answer conversion is a main-analysis product.  The two frozen
# sensitivity anchors remain represented only in explicitly appendix-labelled
# category output and in the role-labelled process table.
CONVERSION_COMPARISONS = MAIN_SIMPLE_COMPARISONS
ALL_COMPARISONS = SIMPLE_COMPARISONS + (INTERACTION_COMPARISON,)
COMPARISON_BY_ID = {spec.comparison_id: spec for spec in ALL_COMPARISONS}
SIMPLE_COMPARISON_ORDER = {
    spec.comparison_id: index for index, spec in enumerate(SIMPLE_COMPARISONS)
}


@dataclass(frozen=True)
class ProcessMetricSpec:
    metric_id: str
    source_field: str
    unit: str
    applicability: str
    comparability_group: str


PROCESS_METRICS = (
    ProcessMetricSpec("retrieval_model_calls", "retrieval_model_calls", "calls", "all", "common"),
    ProcessMetricSpec("query_model_calls", "query_model_calls", "calls", "all", "common"),
    ProcessMetricSpec("answer_model_calls", "answer_model_calls", "calls", "all", "common"),
    ProcessMetricSpec("retrieval_prompt_tokens", "retrieval_prompt_tokens", "tokens", "all", "common"),
    ProcessMetricSpec("retrieval_completion_tokens", "retrieval_completion_tokens", "tokens", "all", "common"),
    ProcessMetricSpec("retrieval_total_tokens", "retrieval_total_tokens", "tokens", "all", "common"),
    ProcessMetricSpec("query_prompt_tokens", "derived_query_prompt_tokens", "tokens", "all", "common"),
    ProcessMetricSpec("query_completion_tokens", "derived_query_completion_tokens", "tokens", "all", "common"),
    ProcessMetricSpec("query_total_tokens", "query_total_tokens", "tokens", "all", "common"),
    ProcessMetricSpec("answer_prompt_tokens", "answer_prompt_tokens", "tokens", "all", "common"),
    ProcessMetricSpec("answer_completion_tokens", "answer_completion_tokens", "tokens", "all", "common"),
    ProcessMetricSpec("answer_total_tokens", "answer_total_tokens", "tokens", "all", "common"),
    ProcessMetricSpec(
        "retrieval_provider_request_attempts", "retrieval_provider_request_attempts", "attempts", "all", "common"
    ),
    ProcessMetricSpec(
        "answer_provider_request_attempts", "answer_provider_request_attempts", "attempts", "all", "common"
    ),
    ProcessMetricSpec(
        "query_provider_request_attempts", "derived_query_provider_request_attempts", "attempts", "all", "common"
    ),
    ProcessMetricSpec("failure_attempt_count", "failure_attempt_count", "attempts", "all", "common"),
    ProcessMetricSpec(
        "failed_attempt_tokens", "not_available_in_stage_a", "tokens", "unavailable", "unavailable"
    ),
    ProcessMetricSpec("evidence_bundle_characters", "evidence_bundle_characters", "characters", "all", "common"),
    ProcessMetricSpec("evidence_item_count", "evidence_item_count", "items", "all", "common"),
    ProcessMetricSpec("answer_characters", "answer_characters", "characters", "all", "common"),
    ProcessMetricSpec("answer_normalized_tokens", "answer_normalized_tokens", "tokens", "all", "common"),
    ProcessMetricSpec(
        "r1_provider_rounds", "retrieval_provider_rounds", "R1 provider rounds", "r1", "r1_rounds_only"
    ),
    ProcessMetricSpec(
        "r1_orchestration_calls", "retrieval_orchestration_calls", "R1 orchestration calls", "r1", "r1_only"
    ),
    ProcessMetricSpec(
        "r1_filesystem_tool_calls", "retrieval_filesystem_tool_calls", "R1 filesystem calls", "r1", "r1_only"
    ),
    ProcessMetricSpec(
        "ranked_retrieval_actions", "search_action_count", "R2/R3 actions", "ranked", "r2_r3_actions_only"
    ),
    ProcessMetricSpec("native_latency_ms", "elapsed_ms", "milliseconds", "unavailable", "unavailable"),
)


def _with_id(prefix: str, id_field: str, row: Mapping[str, Any]) -> dict[str, Any]:
    body = dict(row)
    return {id_field: _id(prefix, body), **body}


def _answer_state(value: float) -> str:
    raw = _state(value)
    return {"increase": "improve", "same": "same", "decrease": "decline"}[raw]


def _evidence_state(value: float) -> str:
    raw = _state(value)
    return {"increase": "up", "same": "same", "decrease": "down"}[raw]


def _sign(value: float) -> int:
    if value > TIE_TOLERANCE:
        return 1
    if value < -TIE_TOLERANCE:
        return -1
    return 0


def _validate_identity_object(
    *,
    directory: Path,
    protocol_version: str,
    audit_id: str,
    source_manifest_id: str,
    marker_name: str,
    hashes: Mapping[str, str],
) -> dict[str, Any]:
    audit = _read_json(directory / "audit.json")
    marker = _read_json(directory / marker_name)
    manifest = _read_json(directory / "source-manifest.json")
    _require(audit.get("status") == "passed", f"{directory.name} audit is not passed")
    _require(marker.get("status") == "passed", f"{directory.name} marker is not passed")
    _require(audit.get("protocol_version") == protocol_version, f"{directory.name} protocol differs")
    _require(marker.get("protocol_version") == protocol_version, f"{directory.name} marker protocol differs")
    _require(audit.get("audit_id") == audit_id, f"{directory.name} frozen audit identity differs")
    _require(marker.get("audit_id") == audit_id, f"{directory.name} marker audit identity differs")
    _require(
        marker.get("audit_sha256") == _sha256_file(directory / "audit.json"),
        f"{directory.name} marker audit hash differs",
    )
    audit_body = {key: value for key, value in audit.items() if key != "audit_id"}
    prefix = audit_id.split("audit-", 1)[0] + "audit-"
    _require(
        audit_id == prefix + sha256_bytes(canonical_json_bytes(audit_body)),
        f"{directory.name} audit identity does not recompute",
    )
    _require(
        manifest.get("source_manifest_id") == source_manifest_id,
        f"{directory.name} frozen source-manifest identity differs",
    )
    manifest_body = {key: value for key, value in manifest.items() if key != "source_manifest_id"}
    manifest_prefix = source_manifest_id.rsplit("-", 1)[0] + "-"
    _require(
        source_manifest_id == manifest_prefix + sha256_bytes(canonical_json_bytes(manifest_body)),
        f"{directory.name} source-manifest identity does not recompute",
    )
    for name, digest in hashes.items():
        _require(_sha256_file(directory / name) == digest, f"{directory.name} frozen hash differs: {name}")
    return audit


def _validate_lineage(
    stage_a_dir: Path,
    stage_b_dir: Path,
    stage_c_dir: Path,
) -> dict[str, Any]:
    # The Stage C byte-rebuild audit transitively reruns the complete Stage B
    # and Stage A audits.  The explicit checks below additionally pin every
    # identity and every Stage-D-consumed byte sequence.
    gate = audit_stage_c_output(
        stage_a_dir=stage_a_dir,
        stage_b_dir=stage_b_dir,
        output_dir=stage_c_dir,
    )
    _require(gate.get("status") == "passed", "Stage C transitive lineage gate is not passed")
    _validate_identity_object(
        directory=stage_a_dir,
        protocol_version=STAGE_A_PROTOCOL_VERSION,
        audit_id=EXPECTED_STAGE_A_AUDIT_ID,
        source_manifest_id=EXPECTED_STAGE_A_SOURCE_MANIFEST_ID,
        marker_name="STAGE-A.PASSED",
        hashes=EXPECTED_STAGE_A_HASHES,
    )
    _validate_identity_object(
        directory=stage_b_dir,
        protocol_version=STAGE_B_PROTOCOL_VERSION,
        audit_id=EXPECTED_STAGE_B_AUDIT_ID,
        source_manifest_id=EXPECTED_STAGE_B_SOURCE_MANIFEST_ID,
        marker_name="STAGE-B.PASSED",
        hashes=EXPECTED_STAGE_B_HASHES,
    )
    _validate_identity_object(
        directory=stage_c_dir,
        protocol_version=STAGE_C_PROTOCOL_VERSION,
        audit_id=EXPECTED_STAGE_C_AUDIT_ID,
        source_manifest_id=EXPECTED_STAGE_C_SOURCE_MANIFEST_ID,
        marker_name="STAGE-C.PASSED",
        hashes=EXPECTED_STAGE_C_HASHES,
    )
    return {
        "stage_a_protocol_version": STAGE_A_PROTOCOL_VERSION,
        "stage_a_audit_id": EXPECTED_STAGE_A_AUDIT_ID,
        "stage_a_source_manifest_id": EXPECTED_STAGE_A_SOURCE_MANIFEST_ID,
        **{f"stage_a_{name.replace('.', '_').replace('-', '_')}_sha256": digest for name, digest in EXPECTED_STAGE_A_HASHES.items()},
        "stage_b_protocol_version": STAGE_B_PROTOCOL_VERSION,
        "stage_b_audit_id": EXPECTED_STAGE_B_AUDIT_ID,
        "stage_b_source_manifest_id": EXPECTED_STAGE_B_SOURCE_MANIFEST_ID,
        **{f"stage_b_{name.replace('.', '_').replace('-', '_')}_sha256": digest for name, digest in EXPECTED_STAGE_B_HASHES.items()},
        "stage_c_protocol_version": STAGE_C_PROTOCOL_VERSION,
        "stage_c_audit_id": EXPECTED_STAGE_C_AUDIT_ID,
        "stage_c_source_manifest_id": EXPECTED_STAGE_C_SOURCE_MANIFEST_ID,
        **{f"stage_c_{name.replace('.', '_').replace('-', '_')}_sha256": digest for name, digest in EXPECTED_STAGE_C_HASHES.items()},
    }


def _validate_process_fields(rows: Sequence[Mapping[str, Any]]) -> None:
    numeric_fields = {
        spec.source_field
        for spec in PROCESS_METRICS
        if spec.applicability != "unavailable" and not spec.source_field.startswith("derived_")
    }
    numeric_fields.update({"global_position", "category"})
    for row in rows:
        _require(row.get("elapsed_ms") is None, "E1--E6 native latency must remain unavailable")
        _require(row.get("latency_available") is False, "E1--E6 latency availability differs")
        _require(row.get("failure_tokens_in_query_total") is False, "Failed-attempt token accounting differs")
        _require(
            int(row["query_total_tokens"])
            == int(row["retrieval_total_tokens"]) + int(row["answer_total_tokens"]),
            "Successful query-token total does not equal retrieval plus answer tokens",
        )
        _require(
            int(row["query_model_calls"])
            == int(row["retrieval_model_calls"]) + int(row["answer_model_calls"]),
            "Query model-call total does not equal retrieval plus answer calls",
        )
        _require(
            int(row["query_total_tokens"])
            == int(row["retrieval_prompt_tokens"])
            + int(row["retrieval_completion_tokens"])
            + int(row["answer_prompt_tokens"])
            + int(row["answer_completion_tokens"]),
            "Query prompt/completion token decomposition differs",
        )
        for field in numeric_fields:
            value = row.get(field)
            _require(isinstance(value, (int, float)) and not isinstance(value, bool), f"Process field is not numeric: {field}")
            _require(math.isfinite(float(value)) and float(value) >= 0.0, f"Process field is invalid: {field}")
        for field in (
            "analysis_row_id", "source_record_id", "source_record_path",
            "source_record_file_sha256", "source_record_payload_sha256",
        ):
            _require(isinstance(row.get(field), str) and bool(row[field]), f"Stage A provenance field differs: {field}")


def _ordered_questions(rows: Sequence[Mapping[str, Any]]) -> tuple[str, ...]:
    selected = sorted(
        (row for row in rows if row["backbone_id"] == "qwen" and row["condition_id"] == "E1"),
        key=lambda row: int(row["global_position"]),
    )
    _require(len(selected) == QUESTION_COUNT, "Stage D question order is not Main-60")
    return tuple(str(row["question_id"]) for row in selected)


def _stage_a_index(rows: Sequence[Mapping[str, Any]]) -> dict[tuple[str, str, str], Mapping[str, Any]]:
    index = {
        (str(row["backbone_id"]), str(row["condition_id"]), str(row["question_id"])): row
        for row in rows
    }
    _require(len(index) == len(rows), "Stage A identity collision in Stage D")
    return index


def _validate_pair_row(
    row: Mapping[str, Any],
    *,
    spec: ComparisonSpec,
    backbone: str,
    question_id: str,
    metric_id: str,
    a_index: Mapping[tuple[str, str, str], Mapping[str, Any]],
) -> None:
    _require(spec.baseline_condition is not None and spec.target_condition is not None, "Simple comparison lacks endpoints")
    baseline = a_index[(backbone, spec.baseline_condition, question_id)]
    target = a_index[(backbone, spec.target_condition, question_id)]
    source_field = METRIC_SOURCE_FIELDS[metric_id]
    baseline_value = baseline[source_field]
    target_value = target[source_field]
    _require(baseline_value is not None and target_value is not None, "Paired metric endpoint is null")
    difference = float(target_value) - float(baseline_value)
    _require(row.get("backbone_id") == backbone, "Paired backbone differs")
    _require(row.get("answer_set_id") == baseline.get("answer_set_id") == target.get("answer_set_id"), "Paired answer set differs")
    _require(row.get("contrast_id") == spec.comparison_id, "Paired comparison identity differs")
    _require(row.get("question_id") == question_id and row.get("metric_id") == metric_id, "Paired row identity differs")
    _require(
        row.get("baseline_condition") == spec.baseline_condition
        and row.get("target_condition") == spec.target_condition,
        "Paired endpoints differ",
    )
    _require(
        row.get("baseline_analysis_row_id") == baseline.get("analysis_row_id")
        and row.get("target_analysis_row_id") == target.get("analysis_row_id"),
        "Paired Stage A row identities differ",
    )
    _require(_is_close(float(row["baseline_value"]), float(baseline_value)), "Paired baseline value differs")
    _require(_is_close(float(row["target_value"]), float(target_value)), "Paired target value differs")
    _require(_is_close(float(row["raw_difference"]), difference), "Paired difference differs")
    _require(row.get("raw_state") == _state(difference), "Paired state differs")
    _require(row.get("oriented_state") == {"increase": "win", "same": "tie", "decrease": "loss"}[_state(difference)], "Paired oriented state differs")
    _require(row.get("evidence_eligible") == baseline.get("evidence_eligible") == target.get("evidence_eligible"), "Paired evidence mask differs")
    _require(int(row.get("global_position")) == int(baseline["global_position"]), "Paired global position differs")


def _index_and_validate_pairs(
    *,
    b_rows: Sequence[Mapping[str, Any]],
    c_rows: Sequence[Mapping[str, Any]],
    a_index: Mapping[tuple[str, str, str], Mapping[str, Any]],
    ordered_questions: Sequence[str],
) -> dict[tuple[str, str, str, str], Mapping[str, Any]]:
    _require(len(b_rows) == EXPECTED_STAGE_B_PAIRED_ROWS, "Formal Stage B paired row count differs")
    _require(len(c_rows) == EXPECTED_STAGE_C_PAIRED_ROWS, "Formal Stage C paired row count differs")
    index: dict[tuple[str, str, str, str], Mapping[str, Any]] = {}
    for source_rows, protocol, allowed in (
        (b_rows, STAGE_B_PROTOCOL_VERSION, {spec.comparison_id for spec in MAIN_SIMPLE_COMPARISONS if spec.source_stage == "stage_b"}),
        (c_rows, STAGE_C_PROTOCOL_VERSION, {spec.comparison_id for spec in SIMPLE_COMPARISONS if spec.source_stage == "stage_c"}),
    ):
        for row in source_rows:
            _require(row.get("protocol_version") == protocol, "Source paired protocol differs")
            comparison_id = str(row.get("contrast_id"))
            if comparison_id not in allowed or row.get("metric_id") not in CATEGORY_METRICS:
                continue
            key = (
                comparison_id,
                str(row["backbone_id"]),
                str(row["question_id"]),
                str(row["metric_id"]),
            )
            _require(key not in index, f"Duplicate Stage D paired source key: {key}")
            index[key] = row

    for spec in SIMPLE_COMPARISONS:
        for backbone in BACKBONES:
            for metric_id in CATEGORY_METRICS:
                questions = [
                    question_id
                    for question_id in ordered_questions
                    if metric_id != "evidence_recall"
                    or a_index[(backbone, str(spec.baseline_condition), question_id)]["evidence_eligible"]
                ]
                expected = QUESTION_COUNT if metric_id != "evidence_recall" else EVIDENCE_ELIGIBLE_COUNT
                _require(len(questions) == expected, "Stage D paired denominator differs")
                for question_id in questions:
                    key = (spec.comparison_id, backbone, question_id, metric_id)
                    _require(key in index, f"Missing Stage D paired source row: {key}")
                    _validate_pair_row(
                        index[key], spec=spec, backbone=backbone, question_id=question_id,
                        metric_id=metric_id, a_index=a_index,
                    )
    return index


def _index_and_validate_interactions(
    rows: Sequence[Mapping[str, Any]],
    *,
    a_index: Mapping[tuple[str, str, str], Mapping[str, Any]],
    ordered_questions: Sequence[str],
) -> dict[tuple[str, str, str], Mapping[str, Any]]:
    _require(len(rows) == EXPECTED_STAGE_B_INTERACTION_ROWS, "Formal Stage B interaction row count differs")
    index: dict[tuple[str, str, str], Mapping[str, Any]] = {}
    for row in rows:
        _require(row.get("protocol_version") == STAGE_B_PROTOCOL_VERSION, "Interaction protocol differs")
        if row.get("metric_id") not in CATEGORY_METRICS:
            continue
        key = (str(row["backbone_id"]), str(row["question_id"]), str(row["metric_id"]))
        _require(key not in index, f"Duplicate Stage D interaction source key: {key}")
        index[key] = row

    for backbone in BACKBONES:
        for metric_id in CATEGORY_METRICS:
            source_field = METRIC_SOURCE_FIELDS[metric_id]
            questions = [
                question_id for question_id in ordered_questions
                if metric_id != "evidence_recall" or a_index[(backbone, "E1", question_id)]["evidence_eligible"]
            ]
            expected = QUESTION_COUNT if metric_id != "evidence_recall" else EVIDENCE_ELIGIBLE_COUNT
            _require(len(questions) == expected, "Interaction denominator differs")
            for question_id in questions:
                key = (backbone, question_id, metric_id)
                _require(key in index, f"Missing Stage D interaction source row: {key}")
                row = index[key]
                values = {
                    condition: float(a_index[(backbone, condition, question_id)][source_field])
                    for condition in ("E1", "E2", "E3", "E4")
                }
                did_storage = (values["E4"] - values["E2"]) - (values["E3"] - values["E1"])
                did_retrieval = (values["E4"] - values["E3"]) - (values["E2"] - values["E1"])
                for condition in ("E1", "E2", "E3", "E4"):
                    source = a_index[(backbone, condition, question_id)]
                    _require(
                        row.get(f"{condition.lower()}_analysis_row_id") == source["analysis_row_id"],
                        "Interaction Stage A row identity differs",
                    )
                    _require(_is_close(float(row[f"{condition.lower()}_value"]), values[condition]), "Interaction endpoint differs")
                _require(_is_close(float(row["did_storage_form"]), did_storage), "Interaction storage-form DID differs")
                _require(_is_close(float(row["did_retrieval_form"]), did_retrieval), "Interaction retrieval-form DID differs")
                _require(_is_close(float(row["did_oriented"]), did_storage), "Interaction oriented DID differs")
                _require(_is_close(did_storage, did_retrieval), "Interaction algebra differs")
                _require(row.get("raw_state") == _state(did_storage), "Interaction state differs")
    return index


def _load_inputs(
    stage_a_dir: Path,
    stage_b_dir: Path,
    stage_c_dir: Path,
) -> tuple[
    list[dict[str, Any]],
    dict[tuple[str, str, str, str], Mapping[str, Any]],
    dict[tuple[str, str, str], Mapping[str, Any]],
    dict[str, Any],
    dict[str, Any],
]:
    provenance = _validate_lineage(stage_a_dir, stage_b_dir, stage_c_dir)
    a_rows = _read_jsonl(stage_a_dir / "rq1-analysis-view.jsonl")
    input_audit = _validate_stage_a_rows(a_rows)
    _validate_process_fields(a_rows)
    ordered = _ordered_questions(a_rows)
    a_index = _stage_a_index(a_rows)
    paired = _index_and_validate_pairs(
        b_rows=_read_jsonl(stage_b_dir / "paired-question-effects.jsonl"),
        c_rows=_read_jsonl(stage_c_dir / "paired-question-effects.jsonl"),
        a_index=a_index,
        ordered_questions=ordered,
    )
    interactions = _index_and_validate_interactions(
        _read_jsonl(stage_b_dir / "interaction-question-effects.jsonl"),
        a_index=a_index,
        ordered_questions=ordered,
    )
    joined_audit = {
        **dict(input_audit),
        "stage_a_process_fields_verified": True,
        "stage_b_paired_rows": EXPECTED_STAGE_B_PAIRED_ROWS,
        "stage_b_interaction_rows": EXPECTED_STAGE_B_INTERACTION_ROWS,
        "stage_c_paired_rows": EXPECTED_STAGE_C_PAIRED_ROWS,
        "required_simple_effect_rows_verified": len(paired),
        "required_interaction_rows_verified": len(interactions),
        "question_level_identity_and_value_alignment": True,
        "source_trace_content_read": False,
    }
    return a_rows, paired, interactions, provenance, joined_audit


def _comparison_register() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for order, spec in enumerate(ALL_COMPARISONS, start=1):
        for backbone in BACKBONES:
            source_hashes = EXPECTED_STAGE_B_HASHES if spec.source_stage == "stage_b" else EXPECTED_STAGE_C_HASHES
            body = {
                "protocol_version": STAGE_D_PROTOCOL_VERSION,
                "display_order": order,
                "comparison_id": spec.comparison_id,
                "backbone_id": backbone,
                "answer_set_id": "model1-qwen-main60" if backbone == "qwen" else "model2-deepseek-main60",
                "source_stage": spec.source_stage,
                "source_protocol_version": STAGE_B_PROTOCOL_VERSION if spec.source_stage == "stage_b" else STAGE_C_PROTOCOL_VERSION,
                "source_audit_id": EXPECTED_STAGE_B_AUDIT_ID if spec.source_stage == "stage_b" else EXPECTED_STAGE_C_AUDIT_ID,
                "source_question_effect_table": "interaction-question-effects.jsonl" if spec.comparison_type == "interaction" else "paired-question-effects.jsonl",
                "source_question_effect_sha256": (
                    source_hashes["interaction-question-effects.jsonl"]
                    if spec.comparison_type == "interaction"
                    else source_hashes["paired-question-effects.jsonl"]
                ),
                "comparison_type": spec.comparison_type,
                "baseline_condition": spec.baseline_condition,
                "target_condition": spec.target_condition,
                "comparison_family": spec.comparison_family,
                "publication_role": spec.publication_role,
                "interpretation_status": (
                    "descriptive_complete_system"
                    if spec.publication_role in {"main_descriptive", "appendix_sensitivity"}
                    else "core_effect"
                ),
                "analysis_module": spec.analysis_module,
                "difference_direction": "target_minus_baseline" if spec.comparison_type == "simple" else "difference_in_differences",
                "eligible_metrics": [
                    "token_f1", "strict_accuracy", "soft_semantic_score",
                    "evidence_recall", "evidence_any_hit", "evidence_all_hit",
                ],
                "answer_denominator": QUESTION_COUNT,
                "evidence_denominator": EVIDENCE_ELIGIBLE_COUNT,
                "multi_gold_source_denominator": EXPECTED_MULTI_GOLD_SOURCE_COUNT,
                "output_partition": "appendix_sensitivity" if spec.publication_role == "appendix_sensitivity" else ("interaction" if spec.comparison_type == "interaction" else "main"),
                "bootstrap_in_stage_d": False,
            }
            rows.append(_with_id("stage-d-comparison-", "comparison_register_id", body))
    return rows


def _evidence_answer_question_rows(
    *,
    a_index: Mapping[tuple[str, str, str], Mapping[str, Any]],
    paired: Mapping[tuple[str, str, str, str], Mapping[str, Any]],
    ordered_questions: Sequence[str],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for spec in CONVERSION_COMPARISONS:
        assert spec.baseline_condition is not None and spec.target_condition is not None
        for backbone in BACKBONES:
            for question_id in ordered_questions:
                baseline = a_index[(backbone, spec.baseline_condition, question_id)]
                if baseline["evidence_eligible"] is not True:
                    continue
                target = a_index[(backbone, spec.target_condition, question_id)]
                evidence = paired[(spec.comparison_id, backbone, question_id, "evidence_recall")]
                strict = paired[(spec.comparison_id, backbone, question_id, "strict_accuracy")]
                f1 = paired[(spec.comparison_id, backbone, question_id, "token_f1")]
                soft = paired[(spec.comparison_id, backbone, question_id, "soft_semantic_score")]
                body = {
                    "protocol_version": STAGE_D_PROTOCOL_VERSION,
                    "comparison_id": spec.comparison_id,
                    "source_stage": spec.source_stage,
                    "publication_role": spec.publication_role,
                    "backbone_id": backbone,
                    "answer_set_id": baseline["answer_set_id"],
                    "question_id": question_id,
                    "global_position": int(baseline["global_position"]),
                    "category": int(baseline["category"]),
                    "category_name": baseline["category_name"],
                    "gold_source_count": len(set(baseline["gold_dia_ids"])),
                    "multi_gold_source": len(set(baseline["gold_dia_ids"])) > 1,
                    "baseline_condition": spec.baseline_condition,
                    "target_condition": spec.target_condition,
                    "baseline_analysis_row_id": baseline["analysis_row_id"],
                    "target_analysis_row_id": target["analysis_row_id"],
                    "evidence_pair_effect_id": evidence["paired_effect_id"],
                    "strict_pair_effect_id": strict["paired_effect_id"],
                    "f1_pair_effect_id": f1["paired_effect_id"],
                    "soft_pair_effect_id": soft["paired_effect_id"],
                    "baseline_evidence_recall": float(evidence["baseline_value"]),
                    "target_evidence_recall": float(evidence["target_value"]),
                    "evidence_recall_difference": float(evidence["raw_difference"]),
                    "evidence_recall_state": _evidence_state(float(evidence["raw_difference"])),
                    "baseline_evidence_all_hit": bool(baseline["evidence_all_hit"]),
                    "target_evidence_all_hit": bool(target["evidence_all_hit"]),
                    "baseline_evidence_any_hit": bool(baseline["evidence_any_hit"]),
                    "target_evidence_any_hit": bool(target["evidence_any_hit"]),
                    "strict_difference": float(strict["raw_difference"]),
                    "strict_change": _answer_state(float(strict["raw_difference"])),
                    "f1_difference": float(f1["raw_difference"]),
                    "f1_change": _answer_state(float(f1["raw_difference"])),
                    "soft_difference": float(soft["raw_difference"]),
                    "soft_change": _answer_state(float(soft["raw_difference"])),
                }
                rows.append(_with_id("stage-d-conversion-question-", "evidence_answer_question_id", body))
    return rows


def _conversion_matrices(question_rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for spec in CONVERSION_COMPARISONS:
        for backbone in BACKBONES:
            effect_rows = [
                row for row in question_rows
                if row["comparison_id"] == spec.comparison_id and row["backbone_id"] == backbone
            ]
            _require(len(effect_rows) == EVIDENCE_ELIGIBLE_COUNT, "Conversion question denominator differs")
            for subset_id, expected, selected in (
                ("evidence_eligible_58", EVIDENCE_ELIGIBLE_COUNT, effect_rows),
                ("multi_gold_source_19", EXPECTED_MULTI_GOLD_SOURCE_COUNT, [row for row in effect_rows if row["multi_gold_source"]]),
            ):
                _require(len(selected) == expected, f"Conversion subset denominator differs: {subset_id}")
                for metric_id, change_field in (
                    ("strict_accuracy", "strict_change"),
                    ("token_f1", "f1_change"),
                    ("soft_semantic_score", "soft_change"),
                ):
                    counts = Counter(
                        (str(row["evidence_recall_state"]), str(row[change_field])) for row in selected
                    )
                    for evidence_state in EVIDENCE_STATES:
                        for answer_state in ANSWER_STATES:
                            count = counts[(evidence_state, answer_state)]
                            body = {
                                "protocol_version": STAGE_D_PROTOCOL_VERSION,
                                "comparison_id": spec.comparison_id,
                                "publication_role": spec.publication_role,
                                "backbone_id": backbone,
                                "subset_id": subset_id,
                                "denominator": expected,
                                "answer_metric_id": metric_id,
                                "answer_metric_role": "primary" if metric_id == "strict_accuracy" else "supplement",
                                "evidence_recall_state": evidence_state,
                                "answer_change": answer_state,
                                "count": count,
                                "proportion": count / expected,
                            }
                            rows.append(_with_id("stage-d-conversion-cell-", "conversion_cell_id", body))
    return rows


def _conversion_summaries(question_rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for spec in CONVERSION_COMPARISONS:
        for backbone in BACKBONES:
            effect_rows = [
                row for row in question_rows
                if row["comparison_id"] == spec.comparison_id and row["backbone_id"] == backbone
            ]
            for subset_id, expected, selected in (
                ("evidence_eligible_58", EVIDENCE_ELIGIBLE_COUNT, effect_rows),
                ("multi_gold_source_19", EXPECTED_MULTI_GOLD_SOURCE_COUNT, [row for row in effect_rows if row["multi_gold_source"]]),
            ):
                _require(len(selected) == expected, "Conversion summary denominator differs")
                for metric_id, change_field in (
                    ("strict_accuracy", "strict_change"),
                    ("token_f1", "f1_change"),
                    ("soft_semantic_score", "soft_change"),
                ):
                    evidence_up_answer_improve = sum(
                        row["evidence_recall_state"] == "up" and row[change_field] == "improve"
                        for row in selected
                    )
                    evidence_up_answer_not_improve = sum(
                        row["evidence_recall_state"] == "up" and row[change_field] != "improve"
                        for row in selected
                    )
                    evidence_same_answer_improve = sum(
                        row["evidence_recall_state"] == "same" and row[change_field] == "improve"
                        for row in selected
                    )
                    evidence_down_without_answer_harm = sum(
                        row["evidence_recall_state"] == "down" and row[change_field] != "decline"
                        for row in selected
                    )
                    body = {
                        "protocol_version": STAGE_D_PROTOCOL_VERSION,
                        "comparison_id": spec.comparison_id,
                        "publication_role": spec.publication_role,
                        "backbone_id": backbone,
                        "subset_id": subset_id,
                        "denominator": expected,
                        "answer_metric_id": metric_id,
                        "answer_metric_role": "primary" if metric_id == "strict_accuracy" else "supplement",
                        "evidence_up_answer_improve": evidence_up_answer_improve,
                        "evidence_up_answer_not_improve": evidence_up_answer_not_improve,
                        "evidence_same_answer_improve": evidence_same_answer_improve,
                        "evidence_down_without_answer_harm": evidence_down_without_answer_harm,
                        "interpretation_status": "descriptive_association",
                    }
                    rows.append(_with_id("stage-d-conversion-summary-", "conversion_summary_id", body))
    return rows


def _all_hit_strict_transitions(question_rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for spec in CONVERSION_COMPARISONS:
        for backbone in BACKBONES:
            selected = [
                row for row in question_rows
                if row["comparison_id"] == spec.comparison_id and row["backbone_id"] == backbone
            ]
            _require(len(selected) == EVIDENCE_ELIGIBLE_COUNT, "All-hit/Strict denominator differs")
            counts: Counter[tuple[str, str]] = Counter()
            for row in selected:
                all_hit_delta = int(bool(row["target_evidence_all_hit"])) - int(bool(row["baseline_evidence_all_hit"]))
                all_hit_state = {1: "up", 0: "same", -1: "down"}[all_hit_delta]
                counts[(all_hit_state, str(row["strict_change"]))] += 1
            for all_hit_state in EVIDENCE_STATES:
                for strict_change in ANSWER_STATES:
                    count = counts[(all_hit_state, strict_change)]
                    body = {
                        "protocol_version": STAGE_D_PROTOCOL_VERSION,
                        "comparison_id": spec.comparison_id,
                        "publication_role": spec.publication_role,
                        "backbone_id": backbone,
                        "denominator": EVIDENCE_ELIGIBLE_COUNT,
                        "evidence_all_hit_change": all_hit_state,
                        "strict_change": strict_change,
                        "count": count,
                        "proportion": count / EVIDENCE_ELIGIBLE_COUNT,
                    }
                    rows.append(_with_id("stage-d-allhit-strict-cell-", "all_hit_strict_cell_id", body))
    return rows


def _any_hit_strict_transitions(question_rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for spec in CONVERSION_COMPARISONS:
        for backbone in BACKBONES:
            selected = [
                row for row in question_rows
                if row["comparison_id"] == spec.comparison_id and row["backbone_id"] == backbone
            ]
            _require(len(selected) == EVIDENCE_ELIGIBLE_COUNT, "Any-hit/Strict denominator differs")
            counts: Counter[tuple[str, str]] = Counter()
            for row in selected:
                hit_delta = int(bool(row["target_evidence_any_hit"])) - int(bool(row["baseline_evidence_any_hit"]))
                hit_state = {1: "up", 0: "same", -1: "down"}[hit_delta]
                counts[(hit_state, str(row["strict_change"]))] += 1
            for hit_state in EVIDENCE_STATES:
                for strict_change in ANSWER_STATES:
                    count = counts[(hit_state, strict_change)]
                    body = {
                        "protocol_version": STAGE_D_PROTOCOL_VERSION,
                        "comparison_id": spec.comparison_id,
                        "publication_role": spec.publication_role,
                        "backbone_id": backbone,
                        "denominator": EVIDENCE_ELIGIBLE_COUNT,
                        "evidence_any_hit_change": hit_state,
                        "strict_change": strict_change,
                        "count": count,
                        "proportion": count / EVIDENCE_ELIGIBLE_COUNT,
                    }
                    rows.append(_with_id("stage-d-anyhit-strict-cell-", "any_hit_strict_cell_id", body))
    return rows


def _multi_source_coverage_transitions(question_rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for spec in CONVERSION_COMPARISONS:
        for backbone in BACKBONES:
            selected = [
                row for row in question_rows
                if row["comparison_id"] == spec.comparison_id
                and row["backbone_id"] == backbone
                and row["multi_gold_source"]
            ]
            _require(len(selected) == EXPECTED_MULTI_GOLD_SOURCE_COUNT, "Multi-source transition denominator differs")
            for hit_metric, baseline_field, target_field in (
                ("evidence_any_hit", "baseline_evidence_any_hit", "target_evidence_any_hit"),
                ("evidence_all_hit", "baseline_evidence_all_hit", "target_evidence_all_hit"),
            ):
                counts: Counter[tuple[str, str]] = Counter()
                for row in selected:
                    hit_delta = int(bool(row[target_field])) - int(bool(row[baseline_field]))
                    hit_state = {1: "up", 0: "same", -1: "down"}[hit_delta]
                    counts[(hit_state, str(row["strict_change"]))] += 1
                for hit_state in EVIDENCE_STATES:
                    for strict_change in ANSWER_STATES:
                        count = counts[(hit_state, strict_change)]
                        body = {
                            "protocol_version": STAGE_D_PROTOCOL_VERSION,
                            "comparison_id": spec.comparison_id,
                            "publication_role": spec.publication_role,
                            "backbone_id": backbone,
                            "subset_id": "multi_gold_source_19",
                            "denominator": EXPECTED_MULTI_GOLD_SOURCE_COUNT,
                            "coverage_metric_id": hit_metric,
                            "coverage_change": hit_state,
                            "strict_change": strict_change,
                            "count": count,
                            "proportion": count / EXPECTED_MULTI_GOLD_SOURCE_COUNT,
                        }
                        rows.append(_with_id("stage-d-multisource-cell-", "multi_source_transition_id", body))
    return rows


def _category_effect_rows(
    specs: Sequence[ComparisonSpec],
    *,
    paired: Mapping[tuple[str, str, str, str], Mapping[str, Any]],
    a_index: Mapping[tuple[str, str, str], Mapping[str, Any]],
    ordered_questions: Sequence[str],
    id_prefix: str,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for spec in specs:
        assert spec.baseline_condition is not None
        for backbone in BACKBONES:
            for category in CATEGORY_ORDER:
                category_questions = [
                    question_id for question_id in ordered_questions
                    if int(a_index[(backbone, spec.baseline_condition, question_id)]["category"]) == category
                ]
                _require(len(category_questions) == EXPECTED_CATEGORIES[category], "Category answer denominator differs")
                for metric_id in CATEGORY_METRICS:
                    selected_questions = [
                        question_id for question_id in category_questions
                        if metric_id != "evidence_recall"
                        or a_index[(backbone, spec.baseline_condition, question_id)]["evidence_eligible"]
                    ]
                    expected = (
                        EXPECTED_CATEGORIES[category]
                        if metric_id != "evidence_recall"
                        else EXPECTED_EVIDENCE_CATEGORIES[category]
                    )
                    _require(len(selected_questions) == expected, "Category metric denominator differs")
                    source_rows = [
                        paired[(spec.comparison_id, backbone, question_id, metric_id)]
                        for question_id in selected_questions
                    ]
                    differences = [float(row["raw_difference"]) for row in source_rows]
                    raw = Counter(_state(value) for value in differences)
                    body = {
                        "protocol_version": STAGE_D_PROTOCOL_VERSION,
                        "comparison_id": spec.comparison_id,
                        "source_stage": spec.source_stage,
                        "publication_role": spec.publication_role,
                        "backbone_id": backbone,
                        "category": category,
                        "category_name": EXPECTED_CATEGORY_NAMES[category],
                        "metric_id": metric_id,
                        "denominator_scope": "evidence_eligible" if metric_id == "evidence_recall" else "answer_all",
                        "denominator": expected,
                        "baseline_mean": _mean([float(row["baseline_value"]) for row in source_rows]),
                        "target_mean": _mean([float(row["target_value"]) for row in source_rows]),
                        "mean_difference": _mean(differences),
                        "median_difference": _median(differences),
                        "win_count": raw["increase"],
                        "tie_count": raw["same"],
                        "loss_count": raw["decrease"],
                        "bootstrap_computed": False,
                        "inferential_status": "descriptive_only",
                    }
                    rows.append(_with_id(id_prefix, "category_effect_id", body))
    return rows


def _category_interaction_rows(
    *,
    interactions: Mapping[tuple[str, str, str], Mapping[str, Any]],
    a_index: Mapping[tuple[str, str, str], Mapping[str, Any]],
    ordered_questions: Sequence[str],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for backbone in BACKBONES:
        for category in CATEGORY_ORDER:
            category_questions = [
                question_id for question_id in ordered_questions
                if int(a_index[(backbone, "E1", question_id)]["category"]) == category
            ]
            for metric_id in CATEGORY_METRICS:
                selected_questions = [
                    question_id for question_id in category_questions
                    if metric_id != "evidence_recall" or a_index[(backbone, "E1", question_id)]["evidence_eligible"]
                ]
                expected = EXPECTED_CATEGORIES[category] if metric_id != "evidence_recall" else EXPECTED_EVIDENCE_CATEGORIES[category]
                _require(len(selected_questions) == expected, "Category interaction denominator differs")
                source_rows = [interactions[(backbone, question_id, metric_id)] for question_id in selected_questions]
                did = [float(row["did_oriented"]) for row in source_rows]
                raw = Counter(_state(value) for value in did)
                body = {
                    "protocol_version": STAGE_D_PROTOCOL_VERSION,
                    "comparison_id": INTERACTION_ID,
                    "source_stage": "stage_b",
                    "publication_role": "main_core_interaction",
                    "backbone_id": backbone,
                    "category": category,
                    "category_name": EXPECTED_CATEGORY_NAMES[category],
                    "metric_id": metric_id,
                    "denominator_scope": "evidence_eligible" if metric_id == "evidence_recall" else "answer_all",
                    "denominator": expected,
                    "mean_e1": _mean([float(row["e1_value"]) for row in source_rows]),
                    "mean_e2": _mean([float(row["e2_value"]) for row in source_rows]),
                    "mean_e3": _mean([float(row["e3_value"]) for row in source_rows]),
                    "mean_e4": _mean([float(row["e4_value"]) for row in source_rows]),
                    "mean_storage_r1_e3_minus_e1": _mean([float(row["storage_r1_e3_minus_e1"]) for row in source_rows]),
                    "mean_storage_r2_e4_minus_e2": _mean([float(row["storage_r2_e4_minus_e2"]) for row in source_rows]),
                    "mean_retrieval_s1_e2_minus_e1": _mean([float(row["retrieval_s1_e2_minus_e1"]) for row in source_rows]),
                    "mean_retrieval_s2_e4_minus_e3": _mean([float(row["retrieval_s2_e4_minus_e3"]) for row in source_rows]),
                    "mean_did": _mean(did),
                    "median_did": _median(did),
                    "positive_count": raw["increase"],
                    "zero_count": raw["same"],
                    "negative_count": raw["decrease"],
                    "bootstrap_computed": False,
                    "inferential_status": "descriptive_only",
                }
                rows.append(_with_id("stage-d-category-interaction-", "category_interaction_id", body))
    return rows


def _process_applicable(spec: ProcessMetricSpec, retrieval_system: str) -> bool:
    if spec.applicability == "all":
        return True
    if spec.applicability == "r1":
        return retrieval_system == "R1"
    if spec.applicability == "ranked":
        return retrieval_system in {"R2", "R3"}
    if spec.applicability == "unavailable":
        return False
    raise ValueError(f"Unknown process applicability: {spec.applicability}")


def _process_value(row: Mapping[str, Any], spec: ProcessMetricSpec) -> float:
    if spec.source_field == "derived_query_prompt_tokens":
        return float(row["retrieval_prompt_tokens"]) + float(row["answer_prompt_tokens"])
    if spec.source_field == "derived_query_completion_tokens":
        return float(row["retrieval_completion_tokens"]) + float(row["answer_completion_tokens"])
    if spec.source_field == "derived_query_provider_request_attempts":
        return float(row["retrieval_provider_request_attempts"]) + float(row["answer_provider_request_attempts"])
    value = row.get(spec.source_field)
    _require(isinstance(value, (int, float)) and not isinstance(value, bool), f"Process value is not numeric: {spec.metric_id}")
    return float(value)


def _numeric_summary(values: Sequence[float]) -> dict[str, float | int | None]:
    if not values:
        return {"total": None, "mean": None, "median": None, "minimum": None, "maximum": None}
    return {
        "total": math.fsum(values),
        "mean": _mean(values),
        "median": _median(values),
        "minimum": min(values),
        "maximum": max(values),
    }


def _process_condition_summaries(
    *,
    a_index: Mapping[tuple[str, str, str], Mapping[str, Any]],
    ordered_questions: Sequence[str],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for backbone in BACKBONES:
        for condition in STAGE_D_CONDITIONS:
            source_rows = [a_index[(backbone, condition, question_id)] for question_id in ordered_questions]
            retrieval_system = str(source_rows[0]["retrieval_system"])
            for metric in PROCESS_METRICS:
                applicable = _process_applicable(metric, retrieval_system)
                values = [_process_value(row, metric) for row in source_rows] if applicable else []
                summary = _numeric_summary(values)
                body = {
                    "protocol_version": STAGE_D_PROTOCOL_VERSION,
                    "backbone_id": backbone,
                    "answer_set_id": source_rows[0]["answer_set_id"],
                    "condition_id": condition,
                    "storage_representation": source_rows[0]["storage_representation"],
                    "retrieval_system": retrieval_system,
                    "metric_id": metric.metric_id,
                    "source_field": metric.source_field,
                    "unit": metric.unit,
                    "comparability_group": metric.comparability_group,
                    "applicable": applicable,
                    "availability_status": "available" if applicable else "unavailable_or_not_applicable",
                    "failure_tokens_in_query_total": False,
                    "denominator": QUESTION_COUNT if applicable else 0,
                    **summary,
                }
                rows.append(_with_id("stage-d-process-condition-", "process_condition_summary_id", body))
    return rows


def _process_paired_summaries(
    *,
    a_index: Mapping[tuple[str, str, str], Mapping[str, Any]],
    ordered_questions: Sequence[str],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for comparison in SIMPLE_COMPARISONS:
        assert comparison.baseline_condition is not None and comparison.target_condition is not None
        for backbone in BACKBONES:
            baseline_rows = [a_index[(backbone, comparison.baseline_condition, qid)] for qid in ordered_questions]
            target_rows = [a_index[(backbone, comparison.target_condition, qid)] for qid in ordered_questions]
            baseline_system = str(baseline_rows[0]["retrieval_system"])
            target_system = str(target_rows[0]["retrieval_system"])
            for metric in PROCESS_METRICS:
                baseline_applicable = _process_applicable(metric, baseline_system)
                target_applicable = _process_applicable(metric, target_system)
                paired_allowed = baseline_applicable and target_applicable
                baseline_values = [_process_value(row, metric) for row in baseline_rows] if baseline_applicable else []
                target_values = [_process_value(row, metric) for row in target_rows] if target_applicable else []
                differences = [target - baseline for baseline, target in zip(baseline_values, target_values)] if paired_allowed else []
                states = Counter(_state(value) for value in differences)
                body = {
                    "protocol_version": STAGE_D_PROTOCOL_VERSION,
                    "comparison_id": comparison.comparison_id,
                    "source_stage": comparison.source_stage,
                    "publication_role": comparison.publication_role,
                    "backbone_id": backbone,
                    "baseline_condition": comparison.baseline_condition,
                    "target_condition": comparison.target_condition,
                    "baseline_retrieval_system": baseline_system,
                    "target_retrieval_system": target_system,
                    "metric_id": metric.metric_id,
                    "source_field": metric.source_field,
                    "unit": metric.unit,
                    "comparability_group": metric.comparability_group,
                    "baseline_applicable": baseline_applicable,
                    "target_applicable": target_applicable,
                    "paired_comparison_allowed": paired_allowed,
                    "comparison_status": "paired" if paired_allowed else ("unavailable" if metric.applicability == "unavailable" else "noncommensurate_endpoints"),
                    "failure_tokens_in_query_total": False,
                    "baseline_denominator": QUESTION_COUNT if baseline_applicable else 0,
                    "target_denominator": QUESTION_COUNT if target_applicable else 0,
                    "baseline_total": math.fsum(baseline_values) if baseline_values else None,
                    "target_total": math.fsum(target_values) if target_values else None,
                    "baseline_mean": _mean(baseline_values) if baseline_values else None,
                    "target_mean": _mean(target_values) if target_values else None,
                    "mean_paired_difference": _mean(differences) if differences else None,
                    "median_paired_difference": _median(differences) if differences else None,
                    "increase_count": states["increase"] if paired_allowed else None,
                    "same_count": states["same"] if paired_allowed else None,
                    "decrease_count": states["decrease"] if paired_allowed else None,
                }
                rows.append(_with_id("stage-d-process-pair-", "process_paired_summary_id", body))
    return rows


def _simple_counter_pattern(row: Mapping[str, Any]) -> tuple[int, str]:
    evidence = str(row["evidence_recall_state"])
    strict = str(row["strict_change"])
    f1 = str(row["f1_change"])
    soft = str(row["soft_change"])
    if evidence == "up" and strict != "improve":
        return 0, "evidence_up_strict_not_improve"
    if evidence == "down" and strict != "decline":
        return 1, "evidence_down_without_strict_harm"
    if _sign(float(row["strict_difference"])) != _sign(float(row["f1_difference"])):
        return 2, "strict_f1_direction_disagreement"
    if _sign(float(row["strict_difference"])) != _sign(float(row["soft_difference"])):
        return 3, "strict_soft_direction_disagreement"
    if evidence != "same" and strict == "same":
        return 4, "evidence_changed_strict_same"
    if len({strict, f1, soft}) > 1:
        return 5, "answer_metric_direction_disagreement"
    return 99, "deterministic_counterexample_fallback"


def _interaction_counter_pattern(
    *,
    strict_did: float,
    f1_did: float,
    soft_did: float,
    evidence_did: float,
) -> tuple[int, str]:
    if _sign(evidence_did) > 0 and _sign(strict_did) <= 0:
        return 0, "positive_evidence_did_nonpositive_strict_did"
    if _sign(evidence_did) < 0 and _sign(strict_did) >= 0:
        return 1, "negative_evidence_did_without_strict_harm"
    if _sign(strict_did) != _sign(f1_did):
        return 2, "strict_f1_did_direction_disagreement"
    if _sign(strict_did) != _sign(soft_did):
        return 3, "strict_soft_did_direction_disagreement"
    if _sign(evidence_did) != 0 and _sign(strict_did) == 0:
        return 4, "evidence_did_nonzero_strict_did_zero"
    return 99, "deterministic_interaction_counterexample_fallback"


def _candidate_provenance(
    stage_a_rows: Sequence[Mapping[str, Any]],
) -> dict[str, list[str]]:
    return {
        "condition_ids": [str(row["condition_id"]) for row in stage_a_rows],
        "analysis_row_ids": [str(row["analysis_row_id"]) for row in stage_a_rows],
        "source_record_ids": [str(row["source_record_id"]) for row in stage_a_rows],
        "source_record_paths": [str(row["source_record_path"]) for row in stage_a_rows],
        "source_record_file_sha256": [str(row["source_record_file_sha256"]) for row in stage_a_rows],
        "source_record_payload_sha256": [str(row["source_record_payload_sha256"]) for row in stage_a_rows],
    }


def _trace_review_candidates(
    *,
    question_rows: Sequence[Mapping[str, Any]],
    interactions: Mapping[tuple[str, str, str], Mapping[str, Any]],
    a_index: Mapping[tuple[str, str, str], Mapping[str, Any]],
    ordered_questions: Sequence[str],
) -> list[dict[str, Any]]:
    module_specs: dict[str, tuple[ComparisonSpec, ...]] = {
        "5.2.1": MAIN_SIMPLE_COMPARISONS[0:2],
        "5.2.2": MAIN_SIMPLE_COMPARISONS[2:4],
        "5.2.4": MAIN_SIMPLE_COMPARISONS[4:7],
    }
    selected_rows: list[dict[str, Any]] = []
    used_categories: dict[str, set[int]] = defaultdict(set)
    used_comparisons: dict[tuple[str, str], set[str]] = defaultdict(set)
    used_cases: set[tuple[str, str, str]] = set()

    def choose_simple(module_id: str, backbone: str, role: str) -> tuple[Mapping[str, Any], str, str]:
        comparison_ids = {spec.comparison_id for spec in module_specs[module_id]}
        candidates = [
            row for row in question_rows
            if row["comparison_id"] in comparison_ids
            and row["backbone_id"] == backbone
            and (str(row["comparison_id"]), backbone, str(row["question_id"])) not in used_cases
        ]
        if role == "repair":
            candidates = [row for row in candidates if row["strict_change"] == "improve"]
            pattern_for = lambda row: (0, "strict_not_correct_to_correct")
        elif role == "harm":
            candidates = [row for row in candidates if row["strict_change"] == "decline"]
            pattern_for = lambda row: (0, "strict_correct_to_not_correct")
        else:
            preferred = [row for row in candidates if _simple_counter_pattern(row)[0] < 99]
            candidates = preferred or candidates
            pattern_for = _simple_counter_pattern
        _require(bool(candidates), f"No deterministic trace candidate for {module_id}/{backbone}/{role}")

        def key(row: Mapping[str, Any]) -> tuple[Any, ...]:
            pattern_priority, _ = pattern_for(row)
            comparison_id = str(row["comparison_id"])
            coverage = (
                comparison_id in used_comparisons[(module_id, backbone)],
                int(row["category"]) in used_categories[module_id],
            )
            stable_tie = (
                int(row["global_position"]),
                str(row["question_id"]),
                SIMPLE_COMPARISON_ORDER[comparison_id],
            )
            if role == "counterexample":
                return (pattern_priority, *coverage, *stable_tie)
            return (*coverage, *stable_tie)

        selected = min(candidates, key=key)
        _, pattern = pattern_for(selected)
        rule = {
            "repair": "strict_repair_then_coverage_then_global_position_question_id",
            "harm": "strict_harm_then_coverage_then_global_position_question_id",
            "counterexample": "metric_pattern_priority_then_coverage_then_global_position_question_id",
        }[role]
        return selected, pattern, rule

    def append_simple(module_id: str, backbone: str, role: str) -> None:
        selected, pattern, rule = choose_simple(module_id, backbone, role)
        comparison_id = str(selected["comparison_id"])
        comparison = COMPARISON_BY_ID[comparison_id]
        assert comparison.baseline_condition is not None and comparison.target_condition is not None
        question_id = str(selected["question_id"])
        source_questions = [
            a_index[(backbone, comparison.baseline_condition, question_id)],
            a_index[(backbone, comparison.target_condition, question_id)],
        ]
        source_effect_ids = [
            str(selected_row_id)
            for selected_row_id in (
                selected["evidence_pair_effect_id"], selected["strict_pair_effect_id"],
                selected["f1_pair_effect_id"], selected["soft_pair_effect_id"],
            )
        ]
        body = {
            "protocol_version": STAGE_D_PROTOCOL_VERSION,
            "module_id": module_id,
            "backbone_id": backbone,
            "candidate_role": role,
            "selection_rule_id": rule,
            "metric_pattern": pattern,
            "comparison_id": comparison_id,
            "comparison_type": "simple",
            "source_stage": comparison.source_stage,
            "question_id": question_id,
            "global_position": int(selected["global_position"]),
            "category": int(selected["category"]),
            "source_effect_ids": source_effect_ids,
            **_candidate_provenance(source_questions),
            "review_status": "pending",
            "manual_content_inspected": False,
        }
        selected_rows.append(_with_id("stage-d-trace-candidate-", "trace_candidate_id", body))
        used_categories[module_id].add(int(selected["category"]))
        used_comparisons[(module_id, backbone)].add(comparison_id)
        used_cases.add((comparison_id, backbone, question_id))

    def append_interaction(backbone: str, role: str) -> None:
        candidates: list[tuple[str, Mapping[str, Any], Mapping[str, Any], Mapping[str, Any], Mapping[str, Any], int, str]] = []
        for question_id in ordered_questions:
            if (INTERACTION_ID, backbone, question_id) in used_cases:
                continue
            source = a_index[(backbone, "E1", question_id)]
            if source["evidence_eligible"] is not True:
                continue
            strict = interactions[(backbone, question_id, "strict_accuracy")]
            f1 = interactions[(backbone, question_id, "token_f1")]
            soft = interactions[(backbone, question_id, "soft_semantic_score")]
            evidence = interactions[(backbone, question_id, "evidence_recall")]
            strict_did = float(strict["did_oriented"])
            if role == "repair" and _sign(strict_did) <= 0:
                continue
            if role == "harm" and _sign(strict_did) >= 0:
                continue
            priority, pattern = _interaction_counter_pattern(
                strict_did=strict_did,
                f1_did=float(f1["did_oriented"]),
                soft_did=float(soft["did_oriented"]),
                evidence_did=float(evidence["did_oriented"]),
            )
            if role != "counterexample":
                priority = 0
                pattern = "positive_strict_difference_in_differences" if role == "repair" else "negative_strict_difference_in_differences"
            candidates.append((question_id, strict, f1, soft, evidence, priority, pattern))
        if role == "counterexample":
            preferred = [item for item in candidates if item[5] < 99]
            candidates = preferred or candidates
        _require(bool(candidates), f"No interaction trace candidate for {backbone}/{role}")

        def key(item: tuple[str, Mapping[str, Any], Mapping[str, Any], Mapping[str, Any], Mapping[str, Any], int, str]) -> tuple[Any, ...]:
            question_id, _, _, _, _, priority, _ = item
            source = a_index[(backbone, "E1", question_id)]
            coverage = (int(source["category"]) in used_categories["5.2.3"],)
            stable_tie = (int(source["global_position"]), question_id)
            if role == "counterexample":
                return (priority, *coverage, *stable_tie)
            return (*coverage, *stable_tie)

        question_id, strict, f1, soft, evidence, _, pattern = min(candidates, key=key)
        source_questions = [a_index[(backbone, condition, question_id)] for condition in ("E1", "E2", "E3", "E4")]
        body = {
            "protocol_version": STAGE_D_PROTOCOL_VERSION,
            "module_id": "5.2.3",
            "backbone_id": backbone,
            "candidate_role": role,
            "selection_rule_id": (
                "strict_did_sign_then_category_coverage_then_global_position_question_id"
                if role in {"repair", "harm"}
                else "did_metric_pattern_then_category_coverage_then_global_position_question_id"
            ),
            "metric_pattern": pattern,
            "comparison_id": INTERACTION_ID,
            "comparison_type": "interaction",
            "source_stage": "stage_b",
            "question_id": question_id,
            "global_position": int(source_questions[0]["global_position"]),
            "category": int(source_questions[0]["category"]),
            "source_effect_ids": [
                str(strict["interaction_effect_id"]), str(f1["interaction_effect_id"]),
                str(soft["interaction_effect_id"]), str(evidence["interaction_effect_id"]),
            ],
            **_candidate_provenance(source_questions),
            "review_status": "pending",
            "manual_content_inspected": False,
        }
        selected_rows.append(_with_id("stage-d-trace-candidate-", "trace_candidate_id", body))
        used_categories["5.2.3"].add(int(source_questions[0]["category"]))
        used_cases.add((INTERACTION_ID, backbone, question_id))

    for module_id in ("5.2.1", "5.2.2"):
        for backbone in BACKBONES:
            for role in ("repair", "harm", "counterexample"):
                append_simple(module_id, backbone, role)
    for backbone in BACKBONES:
        for role in ("repair", "harm", "counterexample"):
            append_interaction(backbone, role)
    for backbone in BACKBONES:
        for role in ("repair", "harm", "counterexample"):
            append_simple("5.2.4", backbone, role)

    _require(len(selected_rows) == 24, "Trace-review candidate slot count differs")
    return selected_rows


def _recompute_table_ids(tables: Mapping[str, Sequence[Mapping[str, Any]]]) -> bool:
    id_specs = {
        "comparison-register": ("comparison_register_id", "stage-d-comparison-"),
        "evidence-answer-question": ("evidence_answer_question_id", "stage-d-conversion-question-"),
        "conversion-matrices": ("conversion_cell_id", "stage-d-conversion-cell-"),
        "conversion-summaries": ("conversion_summary_id", "stage-d-conversion-summary-"),
        "all-hit-strict-transitions": ("all_hit_strict_cell_id", "stage-d-allhit-strict-cell-"),
        "any-hit-strict-transitions": ("any_hit_strict_cell_id", "stage-d-anyhit-strict-cell-"),
        "multi-source-coverage-transitions": ("multi_source_transition_id", "stage-d-multisource-cell-"),
        "category-effects": ("category_effect_id", "stage-d-category-effect-"),
        "category-interactions": ("category_interaction_id", "stage-d-category-interaction-"),
        "appendix-sensitivity-category-effects": ("category_effect_id", "stage-d-sensitivity-category-effect-"),
        "process-condition-summaries": ("process_condition_summary_id", "stage-d-process-condition-"),
        "process-paired-summaries": ("process_paired_summary_id", "stage-d-process-pair-"),
        "trace-review-candidates": ("trace_candidate_id", "stage-d-trace-candidate-"),
    }
    for table_name, rows in tables.items():
        id_field, prefix = id_specs[table_name]
        seen: set[str] = set()
        for row in rows:
            identifier = str(row.get(id_field))
            body = {key: value for key, value in row.items() if key != id_field}
            if identifier != _id(prefix, body) or identifier in seen:
                return False
            seen.add(identifier)
    return True


def _audit_tables(tables: Mapping[str, Sequence[Mapping[str, Any]]]) -> dict[str, Any]:
    expected_rows = {
        "comparison-register": len(ALL_COMPARISONS) * len(BACKBONES),
        "evidence-answer-question": len(CONVERSION_COMPARISONS) * len(BACKBONES) * EVIDENCE_ELIGIBLE_COUNT,
        "conversion-matrices": len(CONVERSION_COMPARISONS) * len(BACKBONES) * 2 * len(ANSWER_CHANGE_METRICS) * 9,
        "conversion-summaries": len(CONVERSION_COMPARISONS) * len(BACKBONES) * 2 * len(ANSWER_CHANGE_METRICS),
        "all-hit-strict-transitions": len(CONVERSION_COMPARISONS) * len(BACKBONES) * 9,
        "any-hit-strict-transitions": len(CONVERSION_COMPARISONS) * len(BACKBONES) * 9,
        "multi-source-coverage-transitions": len(CONVERSION_COMPARISONS) * len(BACKBONES) * 2 * 9,
        "category-effects": len(MAIN_SIMPLE_COMPARISONS) * len(BACKBONES) * len(CATEGORY_ORDER) * len(CATEGORY_METRICS),
        "category-interactions": len(BACKBONES) * len(CATEGORY_ORDER) * len(CATEGORY_METRICS),
        "appendix-sensitivity-category-effects": len(SENSITIVITY_COMPARISONS) * len(BACKBONES) * len(CATEGORY_ORDER) * len(CATEGORY_METRICS),
        "process-condition-summaries": len(BACKBONES) * len(STAGE_D_CONDITIONS) * len(PROCESS_METRICS),
        "process-paired-summaries": len(SIMPLE_COMPARISONS) * len(BACKBONES) * len(PROCESS_METRICS),
        "trace-review-candidates": 24,
    }
    actual_rows = {name: len(rows) for name, rows in tables.items()}
    _require(actual_rows == expected_rows, "Stage D table row counts differ")
    _require(_recompute_table_ids(tables), "Stage D deterministic table ID audit failed")
    _require(_no_text_bearing_fields(tables), "Stage D output contains a prohibited text-bearing field")
    for rows in tables.values():
        for row in rows:
            _require(
                not any(fragment in field.lower() for field in row for fragment in ("secret", "api_key", "credential")),
                "Stage D output contains a secret-bearing field",
            )

    register = tables["comparison-register"]
    _require(
        Counter((row["comparison_id"], row["backbone_id"]) for row in register)
        == Counter((spec.comparison_id, backbone) for spec in ALL_COMPARISONS for backbone in BACKBONES),
        "Comparison register coverage differs",
    )
    _require(
        all(row["output_partition"] == "appendix_sensitivity" for row in register if row["publication_role"] == "appendix_sensitivity"),
        "Sensitivity comparison register partition differs",
    )

    question_rows = tables["evidence-answer-question"]
    question_groups: dict[tuple[str, str], list[Mapping[str, Any]]] = defaultdict(list)
    for row in question_rows:
        question_groups[(str(row["comparison_id"]), str(row["backbone_id"]))].append(row)
        _require(row["evidence_recall_state"] in EVIDENCE_STATES, "Evidence state differs")
        _require(row["strict_change"] in ANSWER_STATES, "Strict state differs")
    _require(
        all(len(rows) == EVIDENCE_ELIGIBLE_COUNT for rows in question_groups.values())
        and len(question_groups) == len(CONVERSION_COMPARISONS) * len(BACKBONES),
        "Evidence-answer question grouping differs",
    )
    _require(
        all(sum(bool(row["multi_gold_source"]) for row in rows) == EXPECTED_MULTI_GOLD_SOURCE_COUNT for rows in question_groups.values()),
        "Evidence-answer multi-source mask differs",
    )

    for table_name, group_fields, expected_denominator in (
        (
            "conversion-matrices",
            ("comparison_id", "backbone_id", "subset_id", "answer_metric_id"),
            {"evidence_eligible_58": EVIDENCE_ELIGIBLE_COUNT, "multi_gold_source_19": EXPECTED_MULTI_GOLD_SOURCE_COUNT},
        ),
        (
            "all-hit-strict-transitions",
            ("comparison_id", "backbone_id"),
            EVIDENCE_ELIGIBLE_COUNT,
        ),
        (
            "any-hit-strict-transitions",
            ("comparison_id", "backbone_id"),
            EVIDENCE_ELIGIBLE_COUNT,
        ),
        (
            "multi-source-coverage-transitions",
            ("comparison_id", "backbone_id", "coverage_metric_id"),
            EXPECTED_MULTI_GOLD_SOURCE_COUNT,
        ),
    ):
        groups: dict[tuple[Any, ...], list[Mapping[str, Any]]] = defaultdict(list)
        for row in tables[table_name]:
            groups[tuple(row[field] for field in group_fields)].append(row)
        for key, rows in groups.items():
            denominator = expected_denominator[key[2]] if isinstance(expected_denominator, dict) else expected_denominator
            _require(len(rows) == 9, f"{table_name} is not a complete 3x3 matrix")
            _require(sum(int(row["count"]) for row in rows) == denominator, f"{table_name} denominator differs")
            _require(all(int(row["denominator"]) == denominator for row in rows), f"{table_name} declared denominator differs")

    main_ids = {spec.comparison_id for spec in MAIN_SIMPLE_COMPARISONS}
    sensitivity_ids = {spec.comparison_id for spec in SENSITIVITY_COMPARISONS}
    _require({str(row["comparison_id"]) for row in tables["category-effects"]} == main_ids, "Main category comparison set differs")
    _require(
        {str(row["comparison_id"]) for row in tables["appendix-sensitivity-category-effects"]} == sensitivity_ids,
        "Sensitivity category comparison set differs",
    )
    _require(
        {str(row["comparison_id"]) for row in tables["category-interactions"]} == {INTERACTION_ID},
        "Category interaction identity differs",
    )
    for table_name in ("category-effects", "appendix-sensitivity-category-effects"):
        for row in tables[table_name]:
            expected = (
                EXPECTED_EVIDENCE_CATEGORIES[int(row["category"])]
                if row["metric_id"] == "evidence_recall"
                else EXPECTED_CATEGORIES[int(row["category"])]
            )
            _require(int(row["denominator"]) == expected, "Category effect denominator differs")
            _require(int(row["win_count"]) + int(row["tie_count"]) + int(row["loss_count"]) == expected, "Category W/T/L differs")
            _require(row["bootstrap_computed"] is False, "Category bootstrap must not be computed")
    for row in tables["category-interactions"]:
        expected = (
            EXPECTED_EVIDENCE_CATEGORIES[int(row["category"])]
            if row["metric_id"] == "evidence_recall"
            else EXPECTED_CATEGORIES[int(row["category"])]
        )
        _require(int(row["denominator"]) == expected, "Category interaction denominator differs")
        _require(int(row["positive_count"]) + int(row["zero_count"]) + int(row["negative_count"]) == expected, "Category DID sign counts differ")

    condition_process = tables["process-condition-summaries"]
    for row in condition_process:
        condition = str(row["condition_id"])
        metric_id = str(row["metric_id"])
        if metric_id in {"native_latency_ms", "failed_attempt_tokens"}:
            _require(row["applicable"] is False and row["denominator"] == 0 and row["mean"] is None, "Unavailable process metric differs")
        if metric_id.startswith("r1_"):
            _require(bool(row["applicable"]) == (condition in {"E1", "E3", "E5"}), "R1 process applicability differs")
        if metric_id == "ranked_retrieval_actions":
            _require(bool(row["applicable"]) == (condition in {"E2", "E4", "E6"}), "R2/R3 process applicability differs")
        _require(row["failure_tokens_in_query_total"] is False, "Process token exclusion marker differs")
    for row in tables["process-paired-summaries"]:
        if row["comparability_group"] in {"r1_rounds_only", "r1_only", "r2_r3_actions_only"}:
            allowed = bool(row["baseline_applicable"]) and bool(row["target_applicable"])
            _require(row["paired_comparison_allowed"] is allowed, "Native search-unit comparability differs")
        if not row["paired_comparison_allowed"]:
            _require(row["mean_paired_difference"] is None and row["median_paired_difference"] is None, "Noncommensurate process delta was computed")

    candidates = tables["trace-review-candidates"]
    slot_counts = Counter((row["module_id"], row["backbone_id"], row["candidate_role"]) for row in candidates)
    expected_slots = Counter(
        (module, backbone, role)
        for module in ("5.2.1", "5.2.2", "5.2.3", "5.2.4")
        for backbone in BACKBONES
        for role in ("repair", "harm", "counterexample")
    )
    _require(slot_counts == expected_slots, "Trace-review candidate slots differ")
    _require(all(row["review_status"] == "pending" and row["manual_content_inspected"] is False for row in candidates), "Trace-review automatic status differs")
    _require(len({row["trace_candidate_id"] for row in candidates}) == len(candidates), "Trace candidate IDs repeat")
    category_coverage = sorted({int(row["category"]) for row in candidates})

    return {
        "table_rows": actual_rows,
        "deterministic_ids_verified": True,
        "prohibited_text_and_secret_fields_absent": True,
        "main_interaction_sensitivity_separation_verified": True,
        "answer_denominator": QUESTION_COUNT,
        "evidence_denominator": EVIDENCE_ELIGIBLE_COUNT,
        "multi_gold_source_denominator": EXPECTED_MULTI_GOLD_SOURCE_COUNT,
        "conversion_matrices_complete": True,
        "category_denominators_verified": True,
        "category_bootstrap_computed": False,
        "native_search_units_kept_noncommensurate": True,
        "latency_status": "unavailable",
        "failed_attempt_tokens_status": "unavailable_separate_from_successful_query_totals",
        "trace_candidate_count": len(candidates),
        "trace_candidate_category_coverage": category_coverage,
        "trace_review_status": "pending",
    }


def _compute_stage_d(
    stage_a_dir: Path,
    stage_b_dir: Path,
    stage_c_dir: Path,
) -> tuple[dict[str, list[dict[str, Any]]], dict[str, Any], dict[str, Any]]:
    a_rows, paired, interactions, provenance, input_audit = _load_inputs(
        stage_a_dir, stage_b_dir, stage_c_dir
    )
    a_index = _stage_a_index(a_rows)
    ordered_questions = _ordered_questions(a_rows)
    question_rows = _evidence_answer_question_rows(
        a_index=a_index, paired=paired, ordered_questions=ordered_questions
    )
    tables = {
        "comparison-register": _comparison_register(),
        "evidence-answer-question": question_rows,
        "conversion-matrices": _conversion_matrices(question_rows),
        "conversion-summaries": _conversion_summaries(question_rows),
        "all-hit-strict-transitions": _all_hit_strict_transitions(question_rows),
        "any-hit-strict-transitions": _any_hit_strict_transitions(question_rows),
        "multi-source-coverage-transitions": _multi_source_coverage_transitions(question_rows),
        "category-effects": _category_effect_rows(
            MAIN_SIMPLE_COMPARISONS,
            paired=paired,
            a_index=a_index,
            ordered_questions=ordered_questions,
            id_prefix="stage-d-category-effect-",
        ),
        "category-interactions": _category_interaction_rows(
            interactions=interactions,
            a_index=a_index,
            ordered_questions=ordered_questions,
        ),
        "appendix-sensitivity-category-effects": _category_effect_rows(
            SENSITIVITY_COMPARISONS,
            paired=paired,
            a_index=a_index,
            ordered_questions=ordered_questions,
            id_prefix="stage-d-sensitivity-category-effect-",
        ),
        "process-condition-summaries": _process_condition_summaries(
            a_index=a_index, ordered_questions=ordered_questions
        ),
        "process-paired-summaries": _process_paired_summaries(
            a_index=a_index, ordered_questions=ordered_questions
        ),
        "trace-review-candidates": _trace_review_candidates(
            question_rows=question_rows,
            interactions=interactions,
            a_index=a_index,
            ordered_questions=ordered_questions,
        ),
    }
    table_audit = _audit_tables(tables)
    return tables, provenance, {"input_audit": input_audit, "table_audit": table_audit}


def _readme() -> str:
    return """# Chapter 5 Stage D automatic mechanism analysis

This directory is the audited **automatic phase** of Stage D. It contains the
frozen comparison register, Evidence-to-answer conversions, hit/Strict and
multi-source transitions, descriptive C1--C4 matrices, E1--E6 process
summaries, and deterministic identifier-only candidates for bounded manual
trace review.

All simple effects are target minus baseline and remain separated by backbone.
The seven main simple comparisons, the storage--retrieval interaction, and the
two appendix sensitivity comparisons are kept in distinct roles. Answer
denominators are 60, Evidence denominators are 58, and the frozen multi-source
subset is 19. Category outputs are descriptive and contain no new bootstrap.

R1 rounds and filesystem calls are native R1 units. R2/R3 actions are a
separate native unit; noncommensurate endpoints receive no paired difference.
Native E1--E6 latency and failed-attempt token amounts are unavailable and are
published explicitly as such. Successful query-token totals exclude failed
attempt tokens.

No question, reference answer, candidate answer, Evidence text, Judge
rationale, source-trace content, or secret is copied into the machine-readable
tables. No API is called and no formal source is modified.

`STAGE-D-AUTO.PASSED` certifies only the deterministic automatic computation.
Every trace-review candidate remains `pending`. This artifact deliberately
does not contain `STAGE-D.PASSED`; that marker is reserved for a later bounded
manual-review finalizer.
"""


def _field_schema(tables: Mapping[str, Sequence[Mapping[str, Any]]]) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "protocol_version": STAGE_D_PROTOCOL_VERSION,
        "phase": "automatic",
        "row_key_policy": "artifact-specific deterministic SHA-256 identifiers",
        "difference_direction": "target_minus_baseline_for_simple_effects",
        "interaction_direction": "(E4-E2)-(E3-E1)",
        "tie_tolerance": TIE_TOLERANCE,
        "answer_denominator": QUESTION_COUNT,
        "evidence_denominator": EVIDENCE_ELIGIBLE_COUNT,
        "multi_gold_source_denominator": EXPECTED_MULTI_GOLD_SOURCE_COUNT,
        "evidence_state_order": list(EVIDENCE_STATES),
        "answer_state_order": list(ANSWER_STATES),
        "category_answer_denominators": {str(key): value for key, value in EXPECTED_CATEGORIES.items()},
        "category_evidence_denominators": {str(key): value for key, value in EXPECTED_EVIDENCE_CATEGORIES.items()},
        "process_unit_contract": {
            "r1_provider_rounds": "R1_only_not_commensurate_with_R2_R3_actions",
            "r1_filesystem_tool_calls": "R1_only_not_commensurate_with_R2_R3_actions",
            "ranked_retrieval_actions": "R2_R3_only_not_commensurate_with_R1_rounds_or_tool_calls",
            "native_latency_ms": "unavailable_NA",
            "failed_attempt_tokens": "unavailable_separate_from_successful_query_totals",
            "failure_tokens_in_query_total": False,
        },
        "trace_review_status": "pending",
        "final_stage_d_marker_emitted": False,
        "tables": {
            name: {"row_count": len(rows), "fields": list(rows[0]) if rows else []}
            for name, rows in tables.items()
        },
    }


def _source_manifest(
    *,
    repo_root: Path,
    stage_a_dir: Path,
    stage_b_dir: Path,
    stage_c_dir: Path,
    provenance: Mapping[str, Any],
    input_audit: Mapping[str, Any],
) -> dict[str, Any]:
    body = {
        "schema_version": 1,
        "protocol_version": STAGE_D_PROTOCOL_VERSION,
        "phase": "automatic",
        "scope": "unified Main-60 E1--E6 within-backbone RQ1 mechanism analysis",
        "stage_a_directory": _relative(repo_root, stage_a_dir),
        "stage_b_directory": _relative(repo_root, stage_b_dir),
        "stage_c_directory": _relative(repo_root, stage_c_dir),
        **dict(provenance),
        "input_rows": 720,
        "backbones": list(BACKBONES),
        "conditions": list(STAGE_D_CONDITIONS),
        "main_simple_comparison_ids": [spec.comparison_id for spec in MAIN_SIMPLE_COMPARISONS],
        "interaction_id": INTERACTION_ID,
        "appendix_sensitivity_comparison_ids": [spec.comparison_id for spec in SENSITIVITY_COMPARISONS],
        "answer_denominator": QUESTION_COUNT,
        "evidence_denominator": EVIDENCE_ELIGIBLE_COUNT,
        "multi_gold_source_denominator": EXPECTED_MULTI_GOLD_SOURCE_COUNT,
        "input_question_order_sha256": input_audit["ordered_question_ids_sha256"],
        "automatic_phase_completed": True,
        "trace_candidates_frozen": True,
        "trace_review_status": "pending",
        "manual_trace_review_completed": False,
        "final_stage_d_marker_emitted": False,
        "source_trace_content_read": False,
        "text_bearing_source_fields_read": False,
        "text_bearing_fields_copied": False,
        "no_api_calls": True,
        "formal_source_mutation": False,
        "bootstrap_computed": False,
        "cross_backbone_effect_computed": False,
        "e7_computed": False,
        "full_context_computed": False,
        "global_error_census_computed": False,
        "pareto_analysis_computed": False,
        "system_recommendation_computed": False,
        "final_rq1_conclusion_computed": False,
        "old_new_question_split_computed": False,
    }
    return {"source_manifest_id": "stage-d-auto-sources-" + sha256_bytes(canonical_json_bytes(body)), **body}


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
    *,
    audits: Mapping[str, Any],
    source_manifest: Mapping[str, Any],
    provenance: Mapping[str, Any],
    output_hashes: Mapping[str, str],
) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "protocol_version": STAGE_D_PROTOCOL_VERSION,
        "status": "passed",
        "phase": "automatic",
        "scope": "unified Main-60 E1--E6 within-backbone RQ1 mechanism analysis",
        "automatic_phase_completed": True,
        "trace_candidates_frozen": True,
        "trace_review_status": "pending",
        "manual_trace_review_completed": False,
        "final_stage_d_marker_emitted": False,
        "no_api_calls": True,
        "formal_source_mutation": False,
        "source_trace_content_read": False,
        "text_bearing_fields_copied": False,
        "bootstrap_computed": False,
        "cross_backbone_effect_computed": False,
        "e7_computed": False,
        "full_context_computed": False,
        "global_error_census_computed": False,
        "pareto_analysis_computed": False,
        "system_recommendation_computed": False,
        "final_rq1_conclusion_computed": False,
        "old_new_question_split_computed": False,
        "input_audit": audits["input_audit"],
        "table_audit": audits["table_audit"],
        "source_manifest_id": source_manifest["source_manifest_id"],
        "stage_a_audit_id": provenance["stage_a_audit_id"],
        "stage_b_audit_id": provenance["stage_b_audit_id"],
        "stage_c_audit_id": provenance["stage_c_audit_id"],
        "output_sha256": dict(output_hashes),
    }


def _marker_body(audit: Mapping[str, Any], audit_sha256: str) -> dict[str, Any]:
    return {
        "status": "passed",
        "protocol_version": STAGE_D_PROTOCOL_VERSION,
        "phase": "automatic",
        "audit_id": audit["audit_id"],
        "audit_sha256": audit_sha256,
        "automatic_phase_completed": True,
        "trace_review_status": "pending",
        "manual_trace_review_completed": False,
        "final_stage_d_marker_emitted": False,
        "input_rows": 720,
        "question_count": QUESTION_COUNT,
        "answer_denominator": QUESTION_COUNT,
        "evidence_denominator": EVIDENCE_ELIGIBLE_COUNT,
        "multi_gold_source_denominator": EXPECTED_MULTI_GOLD_SOURCE_COUNT,
        "main_simple_comparison_count": len(MAIN_SIMPLE_COMPARISONS),
        "interaction_count": 1,
        "appendix_sensitivity_comparison_count": len(SENSITIVITY_COMPARISONS),
        "trace_candidate_count": int(audit["table_audit"]["trace_candidate_count"]),
    }


def build_stage_d(
    *,
    repo_root: Path,
    stage_a_dir: Path,
    stage_b_dir: Path,
    stage_c_dir: Path,
    output_dir: Path,
) -> dict[str, Any]:
    root = repo_root.resolve()
    stage_a = stage_a_dir.resolve()
    stage_b = stage_b_dir.resolve()
    stage_c = stage_c_dir.resolve()
    destination = output_dir.resolve()
    _require(root.is_dir() and not root.is_symlink(), "Repository root is unsafe")
    for label, directory in (("A", stage_a), ("B", stage_b), ("C", stage_c)):
        _require(directory.is_dir() and not directory.is_symlink(), f"Stage {label} directory is unsafe")
    frozen = root / "artifacts/chapter5-main60-analysis-v1"
    _require(stage_a == (frozen / "stage-a").resolve(), "Stage A is not at the frozen repository location")
    _require(stage_b == (frozen / "stage-b").resolve(), "Stage B is not at the frozen repository location")
    _require(stage_c == (frozen / "stage-c").resolve(), "Stage C is not at the frozen repository location")
    _require(not destination.exists() and not destination.is_symlink(), "Stage D automatic output already exists")

    tables, provenance, audits = _compute_stage_d(stage_a, stage_b, stage_c)
    source_manifest = _source_manifest(
        repo_root=root,
        stage_a_dir=stage_a,
        stage_b_dir=stage_b,
        stage_c_dir=stage_c,
        provenance=provenance,
        input_audit=audits["input_audit"],
    )
    parent = destination.parent
    parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=f".{destination.name}.in-progress-", dir=parent))
    try:
        payloads = _artifact_payloads(tables, source_manifest)
        for name, payload in payloads.items():
            _write(temporary / name, payload)
        output_hashes = {name: _sha256_file(temporary / name) for name in sorted(payloads)}
        body = _audit_body(
            audits=audits,
            source_manifest=source_manifest,
            provenance=provenance,
            output_hashes=output_hashes,
        )
        audit = {"audit_id": "stage-d-auto-audit-" + sha256_bytes(canonical_json_bytes(body)), **body}
        _write(temporary / "audit.json", canonical_json_bytes(audit) + b"\n")
        marker = _marker_body(audit, _sha256_file(temporary / "audit.json"))
        _write(temporary / "STAGE-D-AUTO.PASSED", canonical_json_bytes(marker) + b"\n")

        prepublish = audit_stage_d_output(
            stage_a_dir=stage_a,
            stage_b_dir=stage_b,
            stage_c_dir=stage_c,
            output_dir=temporary,
        )
        _require(prepublish.get("status") == "passed", "Stage D automatic pre-publication audit failed")
        _require(not destination.exists(), "Stage D output appeared during build")
        os.rename(temporary, destination)
        descriptor = os.open(parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
    except Exception:
        shutil.rmtree(temporary, ignore_errors=True)
        raise
    return audit_stage_d_output(
        stage_a_dir=stage_a,
        stage_b_dir=stage_b,
        stage_c_dir=stage_c,
        output_dir=destination,
    )


def audit_stage_d_output(
    *,
    stage_a_dir: Path,
    stage_b_dir: Path,
    stage_c_dir: Path,
    output_dir: Path,
) -> dict[str, Any]:
    stage_a = stage_a_dir.resolve()
    stage_b = stage_b_dir.resolve()
    stage_c = stage_c_dir.resolve()
    output_root = output_dir.resolve()
    for label, directory in (("A", stage_a), ("B", stage_b), ("C", stage_c)):
        _require(directory.is_dir() and not directory.is_symlink(), f"Stage {label} directory is unsafe")
    _require(output_root.is_dir() and not output_root.is_symlink(), "Stage D output directory is unsafe")
    repo_root = stage_a.parents[2]
    frozen = repo_root / "artifacts/chapter5-main60-analysis-v1"
    _require(stage_a == (frozen / "stage-a").resolve(), "Stage A is not at the frozen repository location")
    _require(stage_b == (frozen / "stage-b").resolve(), "Stage B is not at the frozen repository location")
    _require(stage_c == (frozen / "stage-c").resolve(), "Stage C is not at the frozen repository location")

    tables, provenance, audits = _compute_stage_d(stage_a, stage_b, stage_c)
    expected_manifest = _source_manifest(
        repo_root=repo_root,
        stage_a_dir=stage_a,
        stage_b_dir=stage_b,
        stage_c_dir=stage_c,
        provenance=provenance,
        input_audit=audits["input_audit"],
    )
    expected_payloads = _artifact_payloads(tables, expected_manifest)
    expected_output_hashes = {
        name: hashlib.sha256(payload).hexdigest() for name, payload in sorted(expected_payloads.items())
    }
    expected_body = _audit_body(
        audits=audits,
        source_manifest=expected_manifest,
        provenance=provenance,
        output_hashes=expected_output_hashes,
    )
    expected_audit = {
        "audit_id": "stage-d-auto-audit-" + sha256_bytes(canonical_json_bytes(expected_body)),
        **expected_body,
    }
    expected_audit_payload = canonical_json_bytes(expected_audit) + b"\n"
    expected_marker = _marker_body(expected_audit, hashlib.sha256(expected_audit_payload).hexdigest())
    expected_marker_payload = canonical_json_bytes(expected_marker) + b"\n"
    expected_names = set(expected_payloads) | {"audit.json", "STAGE-D-AUTO.PASSED"}

    entries = list(output_root.iterdir())
    _require(all(entry.is_file() and not entry.is_symlink() for entry in entries), "Stage D output contains a non-regular entry")
    _require({entry.name for entry in entries} == expected_names, "Stage D output file set differs")
    _require(not (output_root / "STAGE-D.PASSED").exists(), "Final Stage D marker exists before manual review")
    for name, expected_payload in expected_payloads.items():
        _require((output_root / name).read_bytes() == expected_payload, f"Stage D bytes differ: {name}")
    _require((output_root / "audit.json").read_bytes() == expected_audit_payload, "Stage D audit bytes differ")
    _require((output_root / "STAGE-D-AUTO.PASSED").read_bytes() == expected_marker_payload, "Stage D marker bytes differ")

    audit = _read_json(output_root / "audit.json")
    marker = _read_json(output_root / "STAGE-D-AUTO.PASSED")
    audit_body = {key: value for key, value in audit.items() if key != "audit_id"}
    _require(
        audit.get("audit_id") == "stage-d-auto-audit-" + sha256_bytes(canonical_json_bytes(audit_body)),
        "Stage D automatic audit ID does not recompute",
    )
    _require(audit == expected_audit, "Stage D automatic audit differs from independent recomputation")
    _require(marker == expected_marker, "Stage D automatic marker differs from independent recomputation")
    for name, digest in expected_output_hashes.items():
        _require(_sha256_file(output_root / name) == digest, f"Stage D output hash differs: {name}")

    return {
        "status": "passed",
        "protocol_version": STAGE_D_PROTOCOL_VERSION,
        "phase": "automatic",
        "audit_id": expected_audit["audit_id"],
        "input_rows": 720,
        "question_count": QUESTION_COUNT,
        "main_simple_comparison_count": len(MAIN_SIMPLE_COMPARISONS),
        "interaction_count": 1,
        "appendix_sensitivity_comparison_count": len(SENSITIVITY_COMPARISONS),
        "table_rows": audits["table_audit"]["table_rows"],
        "automatic_phase_completed": True,
        "trace_candidate_count": audits["table_audit"]["trace_candidate_count"],
        "trace_review_status": "pending",
        "manual_trace_review_completed": False,
        "final_stage_d_marker_emitted": False,
        "output_dir": str(output_root),
        "no_api_calls": True,
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build or audit Chapter 5 Stage D automatic artifacts")
    parser.add_argument("command", choices=("build", "audit"))
    parser.add_argument("--repo-root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--stage-a-dir", type=Path, required=True)
    parser.add_argument("--stage-b-dir", type=Path, required=True)
    parser.add_argument("--stage-c-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    return parser


def main(argv: list[str] | None = None) -> None:
    args = _parser().parse_args(argv)
    if args.command == "build":
        result = build_stage_d(
            repo_root=args.repo_root,
            stage_a_dir=args.stage_a_dir,
            stage_b_dir=args.stage_b_dir,
            stage_c_dir=args.stage_c_dir,
            output_dir=args.output_dir,
        )
    else:
        result = audit_stage_d_output(
            stage_a_dir=args.stage_a_dir,
            stage_b_dir=args.stage_b_dir,
            stage_c_dir=args.stage_c_dir,
            output_dir=args.output_dir,
        )
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
