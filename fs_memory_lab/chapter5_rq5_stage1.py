"""Build and audit the Chapter 5 RQ5 Section 5.6.1 index artifact.

This stage freezes the complete Main-60 analysis population, the exact set of
Strict-noncorrect cases, and the root-cause state contract used by Sections
5.6.2--5.6.5.  It is deliberately descriptive: no storage, retrieval,
packaging, Answerer, long-context, or evaluation cause is assigned here.

The builder is offline and reads only the frozen Stage A master table plus the
source-record files already named and hashed by Stage A.  Published tables are
identifier- and metric-only; they contain no question, answer, evidence,
prompt, rationale, or secret text.
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
from pathlib import Path, PurePosixPath
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


PROTOCOL_VERSION = "chapter5-main60-rq5-stage-1-v1"
SELECTIVE_CONDITIONS = ("E1", "E2", "E3", "E4", "E5", "E6")
FUSED_CONDITION = "E7"
FULL_CONTEXT_CONDITION = "B3-FullContext"
CONDITION_ORDER = {condition: index for index, condition in enumerate((*SELECTIVE_CONDITIONS, FUSED_CONDITION, FULL_CONTEXT_CONDITION), 1)}
ANSWER_SET_ORDER = {
    "model1-qwen-main60": 1,
    "model2-deepseek-main60": 2,
    "full-context-deepseek-family-main60": 3,
}
PACKET_BACKBONE_ORDER = {"qwen": 1, "deepseek": 2}
JUDGE_LABELS = ("incorrect", "partial", "correct")
EXPECTED_ROW_COUNT = 900
EXPECTED_ERROR_COUNT = 250
EXPECTED_ELIGIBLE_ERROR_COUNT = 233
EXPECTED_INELIGIBLE_ERROR_COUNT = 17
EXPECTED_PACKET_COUNT = 120
EXPECTED_ERROR_PACKET_COUNT = 58
EXPECTED_CONDITION_ERRORS = {
    "E1": 32,
    "E2": 38,
    "E3": 33,
    "E4": 38,
    "E5": 28,
    "E6": 36,
    "E7": 31,
    FULL_CONTEXT_CONDITION: 14,
}
EXPECTED_BACKBONE_CONDITION_ERRORS = {
    "qwen": {"E1": 17, "E2": 20, "E3": 15, "E4": 18, "E5": 13, "E6": 16, "E7": 16},
    "deepseek": {"E1": 15, "E2": 18, "E3": 18, "E4": 20, "E5": 15, "E6": 20, "E7": 15, FULL_CONTEXT_CONDITION: 14},
}

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
    "rationale",
    "prompt",
    "response",
    "api_key",
    "authorization",
}
SECRET_FIELD_FRAGMENTS = ("password", "secret", "bearer", "api_key", "authorization")

TABLE_NAMES = (
    "case-index",
    "strict-error-cases",
    "root-cause-state-register",
    "question-packets",
    "error-census",
)


def _artifact_id(prefix: str, body: Mapping[str, Any]) -> str:
    return prefix + sha256_bytes(canonical_json_bytes(dict(body)))


def _packet_backbone(row: Mapping[str, Any]) -> str:
    backbone = str(row["backbone_id"])
    if backbone == "qwen":
        return "qwen"
    if backbone in {"deepseek", "deepseek_family_full_context"}:
        return "deepseek"
    raise ValueError(f"Unexpected RQ5 backbone: {backbone}")


def _packet_id(packet_backbone: str, question_id: str) -> str:
    body = {"packet_backbone": packet_backbone, "question_id": question_id}
    return _artifact_id("rq5-packet-", body)


def _case_id(analysis_row_id: str) -> str:
    return _artifact_id("rq5-case-", {"analysis_row_id": analysis_row_id})


def _safe_source_file(repo_root: Path, relative_path: str) -> Path:
    _require(isinstance(relative_path, str) and bool(relative_path), "RQ5 source path must be repository-relative")
    pure = PurePosixPath(relative_path)
    _require(not pure.is_absolute(), "RQ5 source path must be repository-relative")
    _require(
        pure.as_posix() == relative_path and all(part not in {"", ".", ".."} for part in pure.parts),
        "RQ5 source path must be canonical",
    )
    root = repo_root.resolve()
    cursor = root
    for part in pure.parts:
        cursor = cursor / part
        _require(not cursor.is_symlink(), f"RQ5 source contains a symlink component: {relative_path}")
    resolved = cursor.resolve()
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise ValueError(f"RQ5 source escapes repository: {relative_path}") from exc
    _require(resolved.is_file() and not resolved.is_symlink(), f"RQ5 source is missing or unsafe: {relative_path}")
    return resolved


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


def _validate_score(row: Mapping[str, Any]) -> None:
    label = str(row["judge_label"])
    _require(label in JUDGE_LABELS, "RQ5 Judge label differs")
    strict = float(row["strict_score"])
    partial = int(row["partial_indicator"])
    soft = float(row["soft_semantic_score"])
    _require(strict in {0.0, 1.0}, "RQ5 Strict score is not binary")
    _require(strict == (1.0 if label == "correct" else 0.0), "RQ5 Strict/label mapping differs")
    _require(partial == (1 if label == "partial" else 0), "RQ5 Partial/label mapping differs")
    _require(math.isclose(soft, 1.0 if label == "correct" else 0.5 if label == "partial" else 0.0), "RQ5 Soft/label mapping differs")
    for field in ("token_precision", "token_recall", "token_f1"):
        value = float(row[field])
        _require(math.isfinite(value) and 0.0 <= value <= 1.0, f"RQ5 invalid score: {field}")


def _validate_rows(*, repo_root: Path, rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    _require(len(rows) == EXPECTED_ROW_COUNT, "RQ5 Stage A row count differs")
    _require(len({str(row["analysis_row_id"]) for row in rows}) == EXPECTED_ROW_COUNT, "RQ5 analysis row IDs repeat")
    _require(len({str(row["source_record_path"]) for row in rows}) == EXPECTED_ROW_COUNT, "RQ5 source paths repeat")
    _require(set(str(row["answer_set_id"]) for row in rows) == set(ANSWER_SET_ORDER), "RQ5 answer sets differ")

    normalised: list[dict[str, Any]] = []
    for raw in rows:
        row = dict(raw)
        _validate_score(row)
        answer_set = str(row["answer_set_id"])
        condition = str(row["condition_id"])
        _require(answer_set in ANSWER_SET_ORDER, "RQ5 answer set differs")
        if answer_set == "full-context-deepseek-family-main60":
            _require(condition == FULL_CONTEXT_CONDITION, "RQ5 Full Context condition differs")
            _require(row["access_regime"] == "full_context", "RQ5 Full Context access regime differs")
            _require(row["retrieval_system"] == "none", "RQ5 Full Context retrieval system differs")
            _require(row["evidence_recall"] is None, "RQ5 Full Context Evidence Recall must be null")
            _require(row["evidence_any_hit"] is None and row["evidence_all_hit"] is None, "RQ5 Full Context hit metrics must be null")
        else:
            _require(condition in (*SELECTIVE_CONDITIONS, FUSED_CONDITION), "RQ5 E1--E7 condition differs")
            _require(row["access_regime"] in {"selective_retrieval", "dual_source_fusion"}, "RQ5 selective access regime differs")
            if bool(row["evidence_eligible"]):
                _require(row["evidence_recall"] is not None, "RQ5 eligible Evidence Recall is missing")
            else:
                _require(row["evidence_recall"] is None, "RQ5 ineligible Evidence Recall must be null")
        source = _safe_source_file(repo_root, str(row["source_record_path"]))
        _require(_sha256_file(source) == row["source_record_file_sha256"], "RQ5 source-record hash differs")
        normalised.append(row)

    counts = Counter((str(row["answer_set_id"]), str(row["condition_id"])) for row in normalised)
    expected_counts = {
        **{("model1-qwen-main60", condition): 60 for condition in (*SELECTIVE_CONDITIONS, FUSED_CONDITION)},
        **{("model2-deepseek-main60", condition): 60 for condition in (*SELECTIVE_CONDITIONS, FUSED_CONDITION)},
        ("full-context-deepseek-family-main60", FULL_CONTEXT_CONDITION): 60,
    }
    _require(counts == Counter(expected_counts), "RQ5 answer-set/condition denominators differ")
    return normalised


def _observable_coverage_state(row: Mapping[str, Any]) -> str:
    if row["access_regime"] == "full_context":
        return "source_visible_by_construction"
    if not bool(row["evidence_eligible"]):
        return "not_annotated"
    recall = float(row["evidence_recall"])
    if math.isclose(recall, 1.0):
        return "all_hit"
    if recall > 0.0:
        return "partial_hit"
    return "no_hit"


def _case_index(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    ordered = sorted(
        rows,
        key=lambda row: (
            ANSWER_SET_ORDER[str(row["answer_set_id"])],
            CONDITION_ORDER[str(row["condition_id"])],
            int(row["global_position"]),
        ),
    )
    row_lookup = {(str(row["answer_set_id"]), str(row["condition_id"]), str(row["question_id"])): row for row in rows}
    output: list[dict[str, Any]] = []
    for case_order, row in enumerate(ordered, 1):
        answer_set = str(row["answer_set_id"])
        condition = str(row["condition_id"])
        question_id = str(row["question_id"])
        packet_backbone = _packet_backbone(row)
        parent_e2 = row_lookup.get((answer_set, "E2", question_id)) if condition == FUSED_CONDITION else None
        parent_e6 = row_lookup.get((answer_set, "E6", question_id)) if condition == FUSED_CONDITION else None
        if condition == FUSED_CONDITION:
            _require(parent_e2 is not None and parent_e6 is not None, "RQ5 E7 parent row is missing")
            _require(
                list(row["source_bundle_ids"]) == [parent_e2["evidence_bundle_id"], parent_e6["evidence_bundle_id"]],
                "RQ5 E7 source bundles differ from E2/E6",
            )
        body = {
            "protocol_version": PROTOCOL_VERSION,
            "case_order": case_order,
            "case_id": _case_id(str(row["analysis_row_id"])),
            "analysis_row_id": row["analysis_row_id"],
            "packet_id": _packet_id(packet_backbone, question_id),
            "packet_backbone": packet_backbone,
            "answer_set_order": ANSWER_SET_ORDER[answer_set],
            "answer_set_id": answer_set,
            "backbone_id": row["backbone_id"],
            "condition_order": CONDITION_ORDER[condition],
            "condition_id": condition,
            "global_position": int(row["global_position"]),
            "question_id": question_id,
            "question_sha256": row["question_sha256"],
            "source_partition": row["source_partition"],
            "category": int(row["category"]),
            "category_name": row["category_name"],
            "storage_representation": row["storage_representation"],
            "retrieval_system": row["retrieval_system"],
            "access_regime": row["access_regime"],
            "independent_retrieval_path": condition in SELECTIVE_CONDITIONS,
            "fusion_reuses_parent_bundles": condition == FUSED_CONDITION,
            "full_context_path": condition == FULL_CONTEXT_CONDITION,
            "requested_model": row["requested_model"],
            "served_model": row["served_model"],
            "judge_requested_model": row["judge_requested_model"],
            "judge_served_model": row["judge_served_model"],
            "evidence_eligible": bool(row["evidence_eligible"]),
            "gold_source_ids": list(row["gold_dia_ids"]),
            "gold_source_count": len(set(row["gold_dia_ids"])),
            "retrieved_source_ids": list(row["retrieved_dia_ids"]),
            "retrieved_source_count": len(set(row["retrieved_dia_ids"])),
            "observable_final_input_coverage": _observable_coverage_state(row),
            "evidence_any_hit": row["evidence_any_hit"],
            "evidence_all_hit": row["evidence_all_hit"],
            "evidence_recall": row["evidence_recall"],
            "evidence_bundle_id": row["evidence_bundle_id"],
            "source_bundle_ids": list(row["source_bundle_ids"]),
            "evidence_item_count": int(row["evidence_item_count"]),
            "evidence_bundle_characters": int(row["evidence_bundle_characters"]),
            "evidence_budget_characters": row["evidence_budget_characters"],
            "search_action_count": int(row["search_action_count"]),
            "retrieval_model_calls": int(row["retrieval_model_calls"]),
            "retrieval_total_tokens": int(row["retrieval_total_tokens"]),
            "answer_prompt_tokens": int(row["answer_prompt_tokens"]),
            "answer_completion_tokens": int(row["answer_completion_tokens"]),
            "answer_total_tokens": int(row["answer_total_tokens"]),
            "answer_normalized_tokens": int(row["answer_normalized_tokens"]),
            "answer_characters": int(row["answer_characters"]),
            "citation_count": int(row["citation_count"]),
            "citation_validity": float(row["citation_validity"]),
            "token_precision": float(row["token_precision"]),
            "token_recall": float(row["token_recall"]),
            "token_f1": float(row["token_f1"]),
            "judge_label": row["judge_label"],
            "strict_score": float(row["strict_score"]),
            "partial_indicator": int(row["partial_indicator"]),
            "soft_semantic_score": float(row["soft_semantic_score"]),
            "strict_noncorrect": float(row["strict_score"]) == 0.0,
            "parent_e2_case_id": _case_id(str(parent_e2["analysis_row_id"])) if parent_e2 else None,
            "parent_e6_case_id": _case_id(str(parent_e6["analysis_row_id"])) if parent_e6 else None,
            "parent_e2_analysis_row_id": parent_e2["analysis_row_id"] if parent_e2 else None,
            "parent_e6_analysis_row_id": parent_e6["analysis_row_id"] if parent_e6 else None,
            "source_record_id": row["source_record_id"],
            "source_record_path": row["source_record_path"],
            "source_record_file_sha256": row["source_record_file_sha256"],
            "source_record_payload_sha256": row["source_record_payload_sha256"],
            "source_run_id": row["source_run_id"],
        }
        output.append(body)
    _require(len(output) == EXPECTED_ROW_COUNT, "RQ5 case index count differs")
    _require(len({row["case_id"] for row in output}) == EXPECTED_ROW_COUNT, "RQ5 case IDs repeat")
    return output


def _strict_error_cases(case_index: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    fields = (
        "case_id", "analysis_row_id", "packet_id", "packet_backbone", "answer_set_id", "backbone_id",
        "condition_id", "global_position", "question_id", "question_sha256", "category", "category_name",
        "storage_representation", "retrieval_system", "access_regime", "evidence_eligible",
        "gold_source_count", "retrieved_source_count", "observable_final_input_coverage", "evidence_any_hit",
        "evidence_all_hit", "evidence_recall", "evidence_bundle_id", "source_bundle_ids",
        "evidence_item_count", "evidence_bundle_characters", "evidence_budget_characters",
        "token_precision", "token_recall", "token_f1", "judge_label", "strict_score", "partial_indicator",
        "soft_semantic_score", "parent_e2_case_id", "parent_e6_case_id", "source_record_id",
        "source_record_path", "source_record_file_sha256", "source_record_payload_sha256", "source_run_id",
    )
    errors = [row for row in case_index if row["strict_noncorrect"]]
    output: list[dict[str, Any]] = []
    for error_order, row in enumerate(errors, 1):
        body = {
            "protocol_version": PROTOCOL_VERSION,
            "error_order": error_order,
            **{field: row[field] for field in fields},
            "root_cause_status": "not_assigned_stage_1",
        }
        output.append(body)
    _require(len(output) == EXPECTED_ERROR_COUNT, "RQ5 Strict-error count differs")
    return output


def _state_value(condition: str, stage: str) -> str:
    if stage == "store_availability":
        return "pending" if condition in SELECTIVE_CONDITIONS else "not_applicable"
    if stage in {"retriever_reach", "model_observation"}:
        return "pending" if condition in SELECTIVE_CONDITIONS else "not_applicable"
    if stage in {"parent_e2_bundle", "parent_e6_bundle", "fusion_operation"}:
        return "pending" if condition == FUSED_CONDITION else "not_applicable"
    if stage == "evidence_retention":
        return "pending" if condition in (*SELECTIVE_CONDITIONS, FUSED_CONDITION) else "not_applicable"
    if stage == "long_context_utilisation":
        return "pending" if condition == FULL_CONTEXT_CONDITION else "not_applicable"
    if stage in {"final_input_sufficiency", "answerer_utilisation", "evaluation_agreement"}:
        return "pending"
    raise ValueError(f"Unknown RQ5 state stage: {stage}")


def _state_register(errors: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for row in errors:
        condition = str(row["condition_id"])
        body = {
            "protocol_version": PROTOCOL_VERSION,
            "state_order": int(row["error_order"]),
            "case_id": row["case_id"],
            "analysis_row_id": row["analysis_row_id"],
            "packet_id": row["packet_id"],
            "packet_backbone": row["packet_backbone"],
            "condition_id": condition,
            "question_id": row["question_id"],
            "category": int(row["category"]),
            "judge_label": row["judge_label"],
            "evidence_eligible": bool(row["evidence_eligible"]),
            "source_data_gate_status": "passed",
            "source_record_integrity_state": "passed",
            "question_identity_state": "passed",
            "gold_annotation_state": "available" if bool(row["evidence_eligible"]) else "not_available",
            "annotated_evidence_attribution_applicable": bool(row["evidence_eligible"]),
            "store_availability_state": _state_value(condition, "store_availability"),
            "retriever_reach_state": _state_value(condition, "retriever_reach"),
            "model_observation_state": _state_value(condition, "model_observation"),
            "parent_e2_bundle_state": _state_value(condition, "parent_e2_bundle"),
            "parent_e6_bundle_state": _state_value(condition, "parent_e6_bundle"),
            "fusion_operation_state": _state_value(condition, "fusion_operation"),
            "evidence_retention_state": _state_value(condition, "evidence_retention"),
            "final_input_sufficiency_state": _state_value(condition, "final_input_sufficiency"),
            "long_context_utilisation_state": _state_value(condition, "long_context_utilisation"),
            "answerer_utilisation_state": _state_value(condition, "answerer_utilisation"),
            "evaluation_agreement_state": _state_value(condition, "evaluation_agreement"),
            "attribution_status": "pending",
            "primary_cause": "pending",
            "secondary_causes": [],
            "attribution_strength": "pending",
            "parent_e2_case_id": row["parent_e2_case_id"],
            "parent_e6_case_id": row["parent_e6_case_id"],
            "source_record_id": row["source_record_id"],
            "source_record_path": row["source_record_path"],
            "source_record_file_sha256": row["source_record_file_sha256"],
            "source_record_payload_sha256": row["source_record_payload_sha256"],
        }
        output.append(body)
    _require(len(output) == EXPECTED_ERROR_COUNT, "RQ5 state-register count differs")
    return output


def _question_packets(case_index: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str], list[Mapping[str, Any]]] = {}
    for row in case_index:
        grouped.setdefault((str(row["packet_backbone"]), str(row["question_id"])), []).append(row)
    _require(len(grouped) == EXPECTED_PACKET_COUNT, "RQ5 question-packet count differs")
    output: list[dict[str, Any]] = []
    for packet_order, key in enumerate(sorted(grouped, key=lambda item: (PACKET_BACKBONE_ORDER[item[0]], int(grouped[item][0]["global_position"]))), 1):
        packet_backbone, question_id = key
        rows = sorted(grouped[key], key=lambda row: int(row["condition_order"]))
        expected_conditions = list((*SELECTIVE_CONDITIONS, FUSED_CONDITION))
        if packet_backbone == "deepseek":
            expected_conditions.append(FULL_CONTEXT_CONDITION)
        conditions = [str(row["condition_id"]) for row in rows]
        _require(conditions == expected_conditions, f"RQ5 packet conditions differ: {packet_backbone}/{question_id}")
        identity_fields = ("global_position", "question_sha256", "category", "category_name", "evidence_eligible")
        _require(all(tuple(row[field] for field in identity_fields) == tuple(rows[0][field] for field in identity_fields) for row in rows), "RQ5 packet identity differs")
        correct = [str(row["condition_id"]) for row in rows if not row["strict_noncorrect"]]
        errors = [str(row["condition_id"]) for row in rows if row["strict_noncorrect"]]
        body = {
            "protocol_version": PROTOCOL_VERSION,
            "packet_order": packet_order,
            "packet_id": _packet_id(packet_backbone, question_id),
            "packet_backbone": packet_backbone,
            "global_position": int(rows[0]["global_position"]),
            "question_id": question_id,
            "question_sha256": rows[0]["question_sha256"],
            "category": int(rows[0]["category"]),
            "category_name": rows[0]["category_name"],
            "evidence_eligible": bool(rows[0]["evidence_eligible"]),
            "condition_count": len(rows),
            "condition_ids": conditions,
            "case_ids": [row["case_id"] for row in rows],
            "strict_correct_conditions": correct,
            "strict_noncorrect_conditions": errors,
            "strict_correct_count": len(correct),
            "strict_noncorrect_count": len(errors),
            "contains_strict_error": bool(errors),
            "counterfactual_success_present": bool(errors) and bool(correct),
            "all_conditions_noncorrect": len(errors) == len(rows),
            "full_context_present": FULL_CONTEXT_CONDITION in conditions,
        }
        output.append(body)
    _require(sum(bool(row["contains_strict_error"]) for row in output) == EXPECTED_ERROR_PACKET_COUNT, "RQ5 error-packet count differs")
    return output


def _error_census(case_index: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str, int, bool], list[Mapping[str, Any]]] = {}
    for row in case_index:
        key = (str(row["answer_set_id"]), str(row["condition_id"]), int(row["category"]), bool(row["evidence_eligible"]))
        grouped.setdefault(key, []).append(row)
    output: list[dict[str, Any]] = []
    for census_order, key in enumerate(
        sorted(grouped, key=lambda item: (ANSWER_SET_ORDER[item[0]], CONDITION_ORDER[item[1]], item[2], 0 if item[3] else 1)),
        1,
    ):
        answer_set, condition, category, eligible = key
        rows = grouped[key]
        labels = Counter(str(row["judge_label"]) for row in rows)
        error_count = labels["partial"] + labels["incorrect"]
        body = {
            "protocol_version": PROTOCOL_VERSION,
            "census_order": census_order,
            "answer_set_id": answer_set,
            "packet_backbone": str(rows[0]["packet_backbone"]),
            "backbone_id": rows[0]["backbone_id"],
            "condition_id": condition,
            "access_regime": rows[0]["access_regime"],
            "category": category,
            "category_name": rows[0]["category_name"],
            "evidence_eligible": eligible,
            "population_n": len(rows),
            "strict_correct_n": labels["correct"],
            "partial_n": labels["partial"],
            "incorrect_n": labels["incorrect"],
            "strict_noncorrect_n": error_count,
            "strict_noncorrect_rate": error_count / len(rows),
        }
        output.append(body)
    _require(sum(int(row["strict_noncorrect_n"]) for row in output) == EXPECTED_ERROR_COUNT, "RQ5 census error total differs")
    _require(sum(int(row["population_n"]) for row in output) == EXPECTED_ROW_COUNT, "RQ5 census population differs")
    return output


def _state_model() -> dict[str, Any]:
    body = {
        "schema_version": 1,
        "protocol_version": PROTOCOL_VERSION,
        "scope": "root-cause state contract for the 250 Strict-noncorrect Main-60 cases",
        "strict_noncorrect_definition": "strict_score equals 0; includes both partial and incorrect Judge labels",
        "source_data_gate": {
            "role": "integrity screen only; source and normalisation are not a detailed RQ5 analysis target",
            "allowed_states": ["passed"],
            "component_states": {
                "source_record_integrity": ["passed"],
                "question_identity": ["passed"],
                "gold_annotation": ["available", "not_available"],
            },
            "gold_annotation_not_available_is_not_gate_failure": True,
        },
        "ordered_chains": {
            "E1-E6": [
                "store_availability",
                "retriever_reach",
                "model_observation",
                "evidence_retention",
                "final_input_sufficiency",
                "answerer_utilisation",
                "evaluation_agreement",
            ],
            "E7": [
                "parent_e2_bundle",
                "parent_e6_bundle",
                "fusion_operation",
                "evidence_retention",
                "final_input_sufficiency",
                "answerer_utilisation",
                "evaluation_agreement",
            ],
            "B3-FullContext": [
                "final_input_sufficiency",
                "long_context_utilisation",
                "answerer_utilisation",
                "evaluation_agreement",
            ],
        },
        "initial_state_values": ["pending", "not_applicable"],
        "stage_definitions": {
            "store_availability": {
                "terminal_values": ["available", "missing", "distorted_or_stale", "indeterminate"]
            },
            "retriever_reach": {
                "terminal_values": ["reached", "not_reached", "indeterminate"]
            },
            "model_observation": {
                "terminal_values": ["observed", "not_observed", "trace_unavailable", "indeterminate"]
            },
            "evidence_retention": {
                "terminal_values": ["retained", "partially_retained", "lost", "budget_skipped", "indeterminate"]
            },
            "parent_e2_bundle": {
                "terminal_values": ["sufficient", "insufficient", "indeterminate"]
            },
            "parent_e6_bundle": {
                "terminal_values": ["sufficient", "insufficient", "indeterminate"]
            },
            "fusion_operation": {
                "terminal_values": ["preserved", "repaired", "interfered", "no_effect", "indeterminate"]
            },
            "final_input_sufficiency": {
                "terminal_values": ["sufficient", "insufficient", "indeterminate"]
            },
            "long_context_utilisation": {
                "terminal_values": ["successful", "missed_relevant_content", "distractor_confusion", "temporal_confusion", "indeterminate"]
            },
            "answerer_utilisation": {
                "terminal_values": ["utilised_correctly", "misused_evidence", "unsupported_generation", "unsupported_abstention", "indeterminate"]
            },
            "evaluation_agreement": {
                "terminal_values": ["agreement", "token_undercredit", "token_overcredit", "judge_disagreement", "indeterminate"]
            },
        },
        "condition_applicability": {
            "E1-E6": {
                "store_availability": True,
                "retriever_reach": True,
                "model_observation": True,
                "evidence_retention": True,
                "parent_e2_bundle": False,
                "parent_e6_bundle": False,
                "fusion_operation": False,
                "long_context_utilisation": False,
            },
            "E7": {
                "store_availability": False,
                "retriever_reach": False,
                "model_observation": False,
                "evidence_retention": True,
                "parent_e2_bundle": True,
                "parent_e6_bundle": True,
                "fusion_operation": True,
                "long_context_utilisation": False,
            },
            "B3-FullContext": {
                "store_availability": False,
                "retriever_reach": False,
                "model_observation": False,
                "evidence_retention": False,
                "parent_e2_bundle": False,
                "parent_e6_bundle": False,
                "fusion_operation": False,
                "long_context_utilisation": True,
            },
        },
        "universal_stages": ["final_input_sufficiency", "answerer_utilisation", "evaluation_agreement"],
        "primary_cause_vocabulary": [
            "storage_omission",
            "storage_distortion_or_staleness",
            "retrieval_query_formulation",
            "retrieval_navigation_or_ranking",
            "retrieval_stopping_or_cap",
            "retrieval_budget_or_packaging",
            "fusion_interference",
            "final_input_insufficient",
            "answerer_utilisation",
            "long_context_utilisation",
            "evaluation_disagreement",
            "mixed",
            "indeterminate",
        ],
        "attribution_contract": {
            "primary": "earliest supported necessary break in the applicable chain",
            "secondary": "later or interacting supported mechanisms; may be empty",
            "strength_values": ["direct", "convergent", "indeterminate"],
            "evidence_recall_is_not_automatic_causation": True,
            "full_context_evidence_recall_applicable": False,
            "e7_runs_new_retrieval": False,
            "attribution_status_values": ["pending", "resolved", "mixed", "indeterminate"],
            "primary_cause_initial_value": "pending",
            "attribution_strength_initial_value": "pending",
        },
        "analysis_ownership": {
            "5.6.2": ["store_availability"],
            "5.6.3": ["retriever_reach", "model_observation"],
            "5.6.4": ["evidence_retention", "parent_e2_bundle", "parent_e6_bundle", "fusion_operation", "final_input_sufficiency", "long_context_utilisation", "answerer_utilisation"],
            "5.6.5": ["evaluation_agreement"],
        },
        "stage_1_assignment": {
            "causal_attribution_computed": False,
            "all_250_attribution_status": "pending",
            "primary_cause": "pending",
        },
    }
    return {"state_model_id": _artifact_id("rq5-state-model-", body), **body}


def _denominator_audit(
    case_index: Sequence[Mapping[str, Any]],
    errors: Sequence[Mapping[str, Any]],
    packets: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    labels = Counter(str(row["judge_label"]) for row in case_index)
    error_labels = Counter(str(row["judge_label"]) for row in errors)
    access = Counter(str(row["access_regime"]) for row in errors)
    categories = Counter(str(row["category_name"]) for row in errors)
    condition_errors = Counter(str(row["condition_id"]) for row in errors)
    backbone_condition: dict[str, dict[str, int]] = {}
    for backbone in PACKET_BACKBONE_ORDER:
        counter = Counter(str(row["condition_id"]) for row in errors if row["packet_backbone"] == backbone)
        backbone_condition[backbone] = {condition: counter[condition] for condition in CONDITION_ORDER if counter[condition]}
    body = {
        "schema_version": 1,
        "protocol_version": PROTOCOL_VERSION,
        "population_rows": len(case_index),
        "strict_correct_rows": labels["correct"],
        "partial_rows": labels["partial"],
        "incorrect_rows": labels["incorrect"],
        "strict_noncorrect_rows": len(errors),
        "strict_noncorrect_by_label": {"partial": error_labels["partial"], "incorrect": error_labels["incorrect"]},
        "strict_noncorrect_evidence_eligible": sum(bool(row["evidence_eligible"]) for row in errors),
        "strict_noncorrect_evidence_ineligible": sum(not bool(row["evidence_eligible"]) for row in errors),
        "strict_noncorrect_by_access_regime": {key: access[key] for key in sorted(access)},
        "strict_noncorrect_by_category": {key: categories[key] for key in sorted(categories)},
        "strict_noncorrect_by_condition": {condition: condition_errors[condition] for condition in CONDITION_ORDER},
        "strict_noncorrect_by_backbone_condition": backbone_condition,
        "question_packets": len(packets),
        "question_packets_with_error": sum(bool(row["contains_strict_error"]) for row in packets),
        "unique_error_question_ids": len({str(row["question_id"]) for row in errors}),
        "selective_retrieval_errors": access["selective_retrieval"],
        "dual_source_fusion_errors": access["dual_source_fusion"],
        "full_context_errors": access["full_context"],
    }
    return {"denominator_audit_id": _artifact_id("rq5-denominators-", body), **body}


def _contains_prohibited_key(value: Any) -> bool:
    if isinstance(value, Mapping):
        for key, item in value.items():
            lowered = str(key).lower()
            if lowered in FORBIDDEN_FIELDS or any(fragment in lowered for fragment in SECRET_FIELD_FRAGMENTS):
                return True
            if _contains_prohibited_key(item):
                return True
    elif isinstance(value, list):
        return any(_contains_prohibited_key(item) for item in value)
    return False


def _value_type(value: Any) -> str:
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, float):
        return "number"
    if value is None:
        return "null"
    if isinstance(value, list):
        return "array"
    if isinstance(value, dict):
        return "object"
    return "string"


def _field_schema(tables: Mapping[str, Sequence[Mapping[str, Any]]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for name, rows in tables.items():
        _require(bool(rows), f"RQ5 table is empty: {name}")
        fields = list(rows[0])
        _require(all(list(row) == fields for row in rows), f"RQ5 table schema differs: {name}")
        result[name] = {
            "row_count": len(rows),
            "fields": [
                {"name": field, "types": sorted({_value_type(row[field]) for row in rows})}
                for field in fields
            ],
        }
    return {
        "schema_version": 1,
        "protocol_version": PROTOCOL_VERSION,
        "tables": result,
        "population_definition": "all 900 audited Main-60 answer records",
        "error_definition": "Strict score equals zero, including Partial and Incorrect",
        "causal_attribution_computed": False,
    }


def _readme() -> str:
    return """# Chapter 5 RQ5 Stage 1: unified case and error index

This immutable artifact implements Section 5.6.1. `case-index` contains all
900 audited Main-60 answer records. `strict-error-cases` is the exact
Strict-noncorrect subset: 250 rows, comprising both Partial and Incorrect LLM
judge labels. `question-packets` groups conditions by backbone and question so
later stages can compare an error with its same-question counterfactuals.
`error-census` freezes all denominators by answer set, condition, category,
and gold-evidence eligibility.

`root-cause-state-register` contains the same 250 errors with a condition-aware
state skeleton. All applicable analytical states and all causal attributions
remain `pending`; non-applicable stages are explicit. `state-model.json`
defines the ordered chain, applicability rules, allowed root-cause vocabulary,
and earliest-supported-break contract. Section 5.6.1 does not assign a root
cause and does not treat low Evidence Recall as causation.

E1--E6 have independent retrieval paths. E7 reuses the same-question E2 and
E6 EvidenceBundles and performs no new retrieval. Full Context receives the
complete raw history and has no retriever or selective EvidenceBundle, so its
Evidence Recall is not applicable.

The artifact contains source identifiers, hashes, metrics, and process counts
only. It contains no question, answer, evidence, prompt, rationale, or secret
text. It made no API or network call, reran no model, modified no formal run,
and computed no new statistical inference.
"""


def _source_manifest(*, repo_root: Path, stage_a_dir: Path, provenance: Mapping[str, Any]) -> dict[str, Any]:
    body = {
        "schema_version": 1,
        "protocol_version": PROTOCOL_VERSION,
        "scope": "unified Main-60 case index and Strict-error population for RQ5",
        "stage_a_directory": _relative(repo_root, stage_a_dir),
        **dict(provenance),
        "stage_a_row_count": EXPECTED_ROW_COUNT,
        "strict_noncorrect_definition": "strict_score == 0",
        "strict_noncorrect_includes": ["partial", "incorrect"],
        "expected_strict_noncorrect_rows": EXPECTED_ERROR_COUNT,
        "expected_question_packets": EXPECTED_PACKET_COUNT,
        "causal_stage_attribution_computed": False,
        "no_api_calls": True,
        "no_network_calls": True,
        "formal_source_mutation": False,
        "statistical_inference_computed": False,
    }
    return {"source_manifest_id": _artifact_id("rq5-stage-1-sources-", body), **body}


def _compute(
    *, repo_root: Path, stage_a_dir: Path,
) -> tuple[dict[str, list[dict[str, Any]]], dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]]:
    provenance = _validate_frozen_input(repo_root=repo_root, stage_a_dir=stage_a_dir)
    source_rows = _validate_rows(repo_root=repo_root, rows=_read_jsonl(stage_a_dir / "master-table.jsonl"))
    cases = _case_index(source_rows)
    errors = _strict_error_cases(cases)
    states = _state_register(errors)
    packets = _question_packets(cases)
    census = _error_census(cases)
    tables = {
        "case-index": cases,
        "strict-error-cases": errors,
        "root-cause-state-register": states,
        "question-packets": packets,
        "error-census": census,
    }
    state_model = _state_model()
    denominators = _denominator_audit(cases, errors, packets)
    condition_errors = Counter(str(row["condition_id"]) for row in errors)
    access_errors = Counter(str(row["access_regime"]) for row in errors)
    backbone_condition_errors = {
        backbone: Counter(
            str(row["condition_id"])
            for row in errors
            if row["packet_backbone"] == backbone
        )
        for backbone in PACKET_BACKBONE_ORDER
    }
    packet_errors = Counter(
        str(row["packet_backbone"])
        for row in packets
        if row["contains_strict_error"]
    )
    state_fields = {
        "store_availability": "store_availability_state",
        "retriever_reach": "retriever_reach_state",
        "model_observation": "model_observation_state",
        "parent_e2_bundle": "parent_e2_bundle_state",
        "parent_e6_bundle": "parent_e6_bundle_state",
        "fusion_operation": "fusion_operation_state",
        "evidence_retention": "evidence_retention_state",
        "final_input_sufficiency": "final_input_sufficiency_state",
        "long_context_utilisation": "long_context_utilisation_state",
        "answerer_utilisation": "answerer_utilisation_state",
        "evaluation_agreement": "evaluation_agreement_state",
    }
    checks = {
        "population_900": len(cases) == EXPECTED_ROW_COUNT,
        "strict_noncorrect_250": len(errors) == EXPECTED_ERROR_COUNT,
        "partial_74": sum(row["judge_label"] == "partial" for row in errors) == 74,
        "incorrect_176": sum(row["judge_label"] == "incorrect" for row in errors) == 176,
        "eligible_errors_233": sum(bool(row["evidence_eligible"]) for row in errors) == EXPECTED_ELIGIBLE_ERROR_COUNT,
        "ineligible_errors_17": sum(not bool(row["evidence_eligible"]) for row in errors) == EXPECTED_INELIGIBLE_ERROR_COUNT,
        "condition_errors_exact": {condition: condition_errors[condition] for condition in CONDITION_ORDER} == EXPECTED_CONDITION_ERRORS,
        "backbone_condition_errors_exact": all(
            backbone_condition_errors[backbone] == Counter(expected)
            for backbone, expected in EXPECTED_BACKBONE_CONDITION_ERRORS.items()
        ),
        "access_regime_errors_205_31_14": access_errors == Counter(
            {"selective_retrieval": 205, "dual_source_fusion": 31, "full_context": 14}
        ),
        "question_packets_120": len(packets) == EXPECTED_PACKET_COUNT,
        "error_packets_58": sum(bool(row["contains_strict_error"]) for row in packets) == EXPECTED_ERROR_PACKET_COUNT,
        "error_packets_by_backbone_27_31": packet_errors == Counter({"qwen": 27, "deepseek": 31}),
        "unique_error_questions_33": len({str(row["question_id"]) for row in errors}) == 33,
        "error_view_exact_filter": [row["case_id"] for row in errors] == [row["case_id"] for row in cases if row["strict_noncorrect"]],
        "state_register_exact_error_view": [row["case_id"] for row in states] == [row["case_id"] for row in errors],
        "all_attributions_pending": all(row["attribution_status"] == "pending" and row["primary_cause"] == "pending" for row in states),
        "all_initial_states_declared": all(
            row[field] in set(state_model["initial_state_values"])
            for row in states
            for field in state_fields.values()
        ),
        "condition_chain_applicability_exact": all(
            row[field] == (
                "pending"
                if stage in set(
                    state_model["ordered_chains"][
                        "E1-E6" if row["condition_id"] in SELECTIVE_CONDITIONS else row["condition_id"]
                    ]
                )
                else "not_applicable"
            )
            for row in states
            for stage, field in state_fields.items()
        ),
        "eligibility_gate_explicit": all(
            row["source_data_gate_status"] == "passed"
            and row["source_record_integrity_state"] == "passed"
            and row["question_identity_state"] == "passed"
            and row["gold_annotation_state"] == ("available" if row["evidence_eligible"] else "not_available")
            and row["annotated_evidence_attribution_applicable"] == row["evidence_eligible"]
            for row in states
        ),
        "e7_parent_states_explicit": all(
            (
                row["parent_e2_bundle_state"] == "pending"
                and row["parent_e6_bundle_state"] == "pending"
                and row["fusion_operation_state"] == "pending"
                and row["parent_e2_case_id"] is not None
                and row["parent_e6_case_id"] is not None
            )
            if row["condition_id"] == FUSED_CONDITION
            else (
                row["parent_e2_bundle_state"] == "not_applicable"
                and row["parent_e6_bundle_state"] == "not_applicable"
                and row["fusion_operation_state"] == "not_applicable"
            )
            for row in states
        ),
        "no_causal_stage_attribution": state_model["stage_1_assignment"]["causal_attribution_computed"] is False,
        "outputs_text_and_secret_free": not _contains_prohibited_key({"tables": tables, "state_model": state_model, "denominators": denominators}),
    }
    _require(all(checks.values()), "RQ5 Stage 1 table audit failed")
    table_audit = {"checks": checks, "row_counts": {name: len(rows) for name, rows in tables.items()}}
    return tables, state_model, denominators, provenance, table_audit


def _artifact_payloads(
    *, tables: Mapping[str, Sequence[Mapping[str, Any]]], state_model: Mapping[str, Any],
    denominators: Mapping[str, Any], source_manifest: Mapping[str, Any],
) -> dict[str, bytes]:
    payloads = {
        "README.md": _readme().encode("utf-8"),
        "schema.json": canonical_json_bytes(_field_schema(tables)) + b"\n",
        "state-model.json": canonical_json_bytes(dict(state_model)) + b"\n",
        "denominator-audit.json": canonical_json_bytes(dict(denominators)) + b"\n",
        "source-manifest.json": canonical_json_bytes(dict(source_manifest)) + b"\n",
    }
    for name, rows in tables.items():
        payloads[f"{name}.jsonl"] = _jsonl_payload(rows)
        payloads[f"{name}.csv"] = _csv_payload(rows)
    return payloads


def _audit_body(
    *, source_manifest: Mapping[str, Any], state_model: Mapping[str, Any], denominators: Mapping[str, Any],
    provenance: Mapping[str, Any], table_audit: Mapping[str, Any], output_hashes: Mapping[str, str],
) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "protocol_version": PROTOCOL_VERSION,
        "status": "passed",
        "scope": "RQ5 Section 5.6.1 unified case index, Strict-error list, and root-cause state model",
        "no_api_calls": True,
        "no_network_calls": True,
        "formal_source_mutation": False,
        "statistical_inference_computed": False,
        "causal_stage_attribution_computed": False,
        "source_manifest_id": source_manifest["source_manifest_id"],
        "state_model_id": state_model["state_model_id"],
        "denominator_audit_id": denominators["denominator_audit_id"],
        **dict(provenance),
        "table_audit": dict(table_audit),
        "output_sha256": dict(output_hashes),
    }


def _marker(audit: Mapping[str, Any], audit_sha256: str) -> dict[str, Any]:
    counts = audit["table_audit"]["row_counts"]
    return {
        "status": "passed",
        "protocol_version": PROTOCOL_VERSION,
        "audit_id": audit["audit_id"],
        "audit_sha256": audit_sha256,
        "population_rows": counts["case-index"],
        "strict_noncorrect_rows": counts["strict-error-cases"],
        "state_register_rows": counts["root-cause-state-register"],
        "question_packets": counts["question-packets"],
        "causal_stage_attribution_computed": False,
        "no_api_calls": True,
        "no_network_calls": True,
    }


def build_rq5_stage1(*, repo_root: Path, stage_a_dir: Path, output_dir: Path) -> dict[str, Any]:
    root = repo_root.resolve()
    source = stage_a_dir.resolve()
    destination = output_dir.resolve()
    _require(not destination.exists() and not destination.is_symlink(), "RQ5 Stage 1 output already exists")
    try:
        destination.relative_to(source)
    except ValueError:
        pass
    else:
        _require(False, "RQ5 Stage 1 output may not be published inside frozen Stage A")

    tables, state_model, denominators, provenance, table_audit = _compute(repo_root=root, stage_a_dir=source)
    manifest = _source_manifest(repo_root=root, stage_a_dir=source, provenance=provenance)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=f".{destination.name}.in-progress-", dir=destination.parent))
    try:
        payloads = _artifact_payloads(
            tables=tables,
            state_model=state_model,
            denominators=denominators,
            source_manifest=manifest,
        )
        for name, payload in payloads.items():
            _write(temporary / name, payload)
        hashes = {name: _sha256_file(temporary / name) for name in sorted(payloads)}
        body = _audit_body(
            source_manifest=manifest,
            state_model=state_model,
            denominators=denominators,
            provenance=provenance,
            table_audit=table_audit,
            output_hashes=hashes,
        )
        audit = {"audit_id": _artifact_id("rq5-stage-1-audit-", body), **body}
        _write(temporary / "audit.json", canonical_json_bytes(audit) + b"\n")
        _write(
            temporary / "RQ5-STAGE-1.PASSED",
            canonical_json_bytes(_marker(audit, _sha256_file(temporary / "audit.json"))) + b"\n",
        )
        result = audit_rq5_stage1_output(repo_root=root, stage_a_dir=source, output_dir=temporary)
        _require(result["status"] == "passed", "RQ5 Stage 1 pre-publication audit failed")
        _require(not destination.exists(), "RQ5 Stage 1 output appeared during build")
        os.rename(temporary, destination)
        descriptor = os.open(destination.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
    except Exception:
        shutil.rmtree(temporary, ignore_errors=True)
        raise
    return audit_rq5_stage1_output(repo_root=root, stage_a_dir=source, output_dir=destination)


def audit_rq5_stage1_output(*, repo_root: Path, stage_a_dir: Path, output_dir: Path) -> dict[str, Any]:
    root = repo_root.resolve()
    source = stage_a_dir.resolve()
    output = output_dir.resolve()
    _require(output.is_dir() and not output.is_symlink(), "RQ5 Stage 1 output directory is unsafe")
    tables, state_model, denominators, provenance, table_audit = _compute(repo_root=root, stage_a_dir=source)
    manifest = _source_manifest(repo_root=root, stage_a_dir=source, provenance=provenance)
    payloads = _artifact_payloads(
        tables=tables,
        state_model=state_model,
        denominators=denominators,
        source_manifest=manifest,
    )
    hashes = {name: hashlib.sha256(payload).hexdigest() for name, payload in sorted(payloads.items())}
    body = _audit_body(
        source_manifest=manifest,
        state_model=state_model,
        denominators=denominators,
        provenance=provenance,
        table_audit=table_audit,
        output_hashes=hashes,
    )
    expected_audit = {"audit_id": _artifact_id("rq5-stage-1-audit-", body), **body}
    audit_payload = canonical_json_bytes(expected_audit) + b"\n"
    marker_payload = canonical_json_bytes(_marker(expected_audit, hashlib.sha256(audit_payload).hexdigest())) + b"\n"
    expected_names = set(payloads) | {"audit.json", "RQ5-STAGE-1.PASSED"}
    entries = list(output.iterdir())
    _require(all(entry.is_file() and not entry.is_symlink() for entry in entries), "RQ5 Stage 1 output contains unsafe entry")
    _require({entry.name for entry in entries} == expected_names, "RQ5 Stage 1 output file set differs")
    for name, payload in payloads.items():
        _require((output / name).read_bytes() == payload, f"RQ5 Stage 1 artifact bytes differ: {name}")
    _require((output / "audit.json").read_bytes() == audit_payload, "RQ5 Stage 1 audit bytes differ")
    _require((output / "RQ5-STAGE-1.PASSED").read_bytes() == marker_payload, "RQ5 Stage 1 marker bytes differ")
    return {
        "status": "passed",
        "protocol_version": PROTOCOL_VERSION,
        "audit_id": expected_audit["audit_id"],
        "population_rows": EXPECTED_ROW_COUNT,
        "strict_noncorrect_rows": EXPECTED_ERROR_COUNT,
        "eligible_strict_noncorrect_rows": EXPECTED_ELIGIBLE_ERROR_COUNT,
        "ineligible_strict_noncorrect_rows": EXPECTED_INELIGIBLE_ERROR_COUNT,
        "question_packets": EXPECTED_PACKET_COUNT,
        "question_packets_with_error": EXPECTED_ERROR_PACKET_COUNT,
        "causal_stage_attribution_computed": False,
        "output_dir": str(output),
        "no_api_calls": True,
        "no_network_calls": True,
    }


build_chapter5_rq5_stage1 = build_rq5_stage1
audit_chapter5_rq5_stage1_output = audit_rq5_stage1_output


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build or audit Chapter 5 RQ5 Stage 1 artifacts")
    parser.add_argument("command", choices=("build", "audit"))
    parser.add_argument("--repo-root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--stage-a-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    return parser


def main(argv: list[str] | None = None) -> None:
    args = _parser().parse_args(argv)
    kwargs = {"repo_root": args.repo_root, "stage_a_dir": args.stage_a_dir, "output_dir": args.output_dir}
    result = build_rq5_stage1(**kwargs) if args.command == "build" else audit_rq5_stage1_output(**kwargs)
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
