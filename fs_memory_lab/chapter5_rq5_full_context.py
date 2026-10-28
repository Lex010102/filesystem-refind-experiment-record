"""Offline Chapter 5.6.4.4 Full Context root-cause audit.

The stage consumes the completed post-downstream state register, validates the
frozen Full Context review, and updates only the three Full Context-owned state
fields.  It never treats complete source visibility as Evidence Recall and it
does not perform evaluation or primary-cause attribution.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import statistics
import tempfile
from collections import Counter
from pathlib import Path
from typing import Any, Mapping, Sequence

from .chapter5_rq4 import audit_rq4_output
from .chapter5_rq5_downstream import (
    DEFAULT_OUTPUT_DIR as DEFAULT_DOWNSTREAM_DIR,
    POST_DOWNSTREAM_STATE_BASENAME,
    PROTOCOL_VERSION as DOWNSTREAM_PROTOCOL_VERSION,
    audit_rq5_downstream_output,
)
from .chapter5_stage_b import _csv_payload, _jsonl_payload, _read_json, _read_jsonl, _require, _sha256_file, _write
from .evidence import canonical_json_bytes, sha256_bytes
from .full_context_runner import full_context_record_from_mapping


PROTOCOL_VERSION = "chapter5-main60-rq5-full-context-v2"
REVIEW_PROTOCOL_VERSION = "chapter5-rq5-full-context-review-v1"
FULL_CONTEXT_CONDITION = "B3-FullContext"
STAGE_A_PATH = "artifacts/chapter5-main60-analysis-v1/stage-a/master-table.jsonl"
STAGE1_DIR = "artifacts/chapter5-main60-analysis-v1/rq5-root-cause-index"
RQ4_DIR = "artifacts/chapter5-main60-analysis-v1/rq4-full-context"
DEFAULT_REVIEW_PATH = "docs/analysis/reviews/chapter5-rq5-full-context-review-v1.json"
DEFAULT_OUTPUT_DIR = "artifacts/chapter5-main60-analysis-v1/rq5-full-context-audit"
POST_FULL_CONTEXT_STATE_BASENAME = "root-cause-state-register-after-full-context"
POST_FULL_CONTEXT_STATE_PATH = f"{DEFAULT_OUTPUT_DIR}/{POST_FULL_CONTEXT_STATE_BASENAME}.jsonl"

EXPECTED_ERROR_CASES = 14
EXPECTED_STATE_ROWS = 250
EXPECTED_DIAGNOSTIC_ROWS = 32
EXPECTED_RQ4_ROWS = 420
EXPECTED_FULL_CONTEXT_QUESTIONS = 60
EXPECTED_EVIDENCE_ELIGIBLE_QUESTIONS = 58
EXPECTED_FULL_CONTEXT_TURNS = 568
EXPECTED_FULL_CONTEXT_CHARACTERS = 108960
EXPECTED_PAIRWISE_COUNTS = {
    "E1": {"both_correct": 42, "full_context_only": 4, "selective_only": 3, "neither_correct": 11},
    "E2": {"both_correct": 39, "full_context_only": 7, "selective_only": 3, "neither_correct": 11},
    "E3": {"both_correct": 41, "full_context_only": 5, "selective_only": 1, "neither_correct": 13},
    "E4": {"both_correct": 38, "full_context_only": 8, "selective_only": 2, "neither_correct": 12},
    "E5": {"both_correct": 43, "full_context_only": 3, "selective_only": 2, "neither_correct": 12},
    "E6": {"both_correct": 38, "full_context_only": 8, "selective_only": 2, "neither_correct": 12},
    "E7": {"both_correct": 42, "full_context_only": 4, "selective_only": 3, "neither_correct": 11},
}
EXPECTED_ANY_SELECTIVE_COUNTS = {
    "both_correct": 46,
    "full_context_only": 0,
    "selective_only": 6,
    "neither_correct": 8,
}
EXPECTED_RQ4_AUDIT_ID = "rq4-audit-2880a371169fcc1c1596fec7baccb795ef1a0bf49b830357dde002b511c2d923"
EXPECTED_RQ4_SHA256 = {
    "audit": "d1639b99cae5e42eb60e73b02f46418fa1a5e2bded056fb39e99bb72b0cd732c",
    "marker": "9d27da8e052b2795abb5a49b9949bd9e075fff96043254ee54dc7ce20875f147",
    "quadrants": "215d0140f40d2b643d5c59df44fc1a70c7d7f21f8121aab2995505804081157f",
}
EXPECTED_REVIEW_SHA256 = "f6cadf5853818ac97379311b4d52c5a6b7b84079e4e2aead179312f16cb9ab7b"

OWNED_STATE_FIELDS = (
    "final_input_sufficiency_state",
    "long_context_utilisation_state",
    "answerer_utilisation_state",
)
CONTENT_STATES = {"complete_but_noisy", "indeterminate"}
SUFFICIENCY_STATES = {"sufficient", "indeterminate"}
LONG_CONTEXT_STATES = {"successful", "missed_relevant_content", "distractor_confusion", "temporal_confusion", "indeterminate"}
ANSWERER_STATES = {"misused_evidence", "unsupported_abstention", "indeterminate"}
ANSWER_FORMS = {"under_answering", "over_answering_with_missing_relation", "incorrect_temporal_or_state_selection", "fine_grained_attribute_omission", "indeterminate"}
PRIMARY_MECHANISMS = {
    "source_reference_temporal_ambiguity", "source_question_entity_mismatch",
    "implicit_visual_or_count_inference_missed", "excessive_caution",
    "competing_location_or_state", "external_knowledge_required_without_gold_locator",
    "background_knowledge_underuse", "multi_episode_composition_failure",
    "target_attribute_dilution", "target_relation_dilution", "fine_grained_attribute_omission",
}
SECONDARY_MECHANISMS = {
    "relative_date_boundary", "excessive_caution", "multi_item_under_answering",
    "open_domain_transfer_underuse", "stale_location_selection", "annotation_unavailable",
    "period_boundary_ambiguity", "similar_event_conflation", "over_answering",
    "under_answering", "adjacent_caption_dependency",
}
CONFIDENCE_LEVELS = {"high", "medium", "low"}
REVIEW_TOP_FIELDS = {"protocol_version", "review_status", "review_unit", "guards", "review_passes", "codebooks", "source_manifest", "cases", "audit"}
REVIEW_ROW_FIELDS = {
    "review_order", "case_id", "analysis_row_id", "question_id", "question_sha256",
    "category_name", "judge_label", "evidence_eligible", "gold_dia_ids",
    "content_state", "final_input_sufficiency_state", "long_context_utilisation_state",
    "answerer_utilisation_state", "answer_form", "primary_mechanism",
    "secondary_mechanisms", "confidence", "review_status", "manual_content_inspected",
    "rationale", "source_record_id", "source_record_path", "source_record_file_sha256",
    "source_record_payload_sha256", "reference_answer_sha256", "candidate_answer_sha256",
    "judgment_id",
}
TABLES = (
    "full-context-mechanisms",
    "full-context-diagnostic-matrix",
    "full-context-question-diagnostics",
    "full-context-category-summary",
    "full-context-answer-profile",
    "evidence-position-diagnostics",
    "evidence-position-summary",
    "full-context-summary",
    POST_FULL_CONTEXT_STATE_BASENAME,
)
FORBIDDEN_FIELDS = {"question", "question_text", "answer", "answer_text", "candidate_answer", "reference_answer", "evidence", "evidence_text", "rationale", "prompt", "response", "api_key", "authorization", "secret"}


def _artifact_id(prefix: str, body: Mapping[str, Any]) -> str:
    return prefix + sha256_bytes(canonical_json_bytes(dict(body)))


def _safe_file(root: Path, relative: str) -> Path:
    path = (root / relative).resolve()
    try:
        path.relative_to(root.resolve())
    except ValueError as exc:
        raise ValueError(f"Full Context source escapes repository: {relative}") from exc
    cursor = root.resolve()
    for part in Path(relative).parts:
        _require(part not in {"", ".", ".."}, "Unsafe Full Context source path")
        cursor /= part
        _require(not cursor.is_symlink(), f"Full Context source contains a symlink: {relative}")
    _require(path.is_file() and not path.is_symlink(), f"Missing Full Context source: {relative}")
    return path


def _validate_rq4(root: Path) -> dict[str, Any]:
    directory = root / RQ4_DIR
    result = audit_rq4_output(repo_root=root, stage_a_dir=root / "artifacts/chapter5-main60-analysis-v1/stage-a", output_dir=directory)
    _require(result["audit_id"] == EXPECTED_RQ4_AUDIT_ID, "RQ4 audit identity differs")
    _require(_sha256_file(directory / "audit.json") == EXPECTED_RQ4_SHA256["audit"], "RQ4 audit hash differs")
    _require(_sha256_file(directory / "RQ4.PASSED") == EXPECTED_RQ4_SHA256["marker"], "RQ4 marker hash differs")
    _require(_sha256_file(directory / "question-quadrants.jsonl") == EXPECTED_RQ4_SHA256["quadrants"], "RQ4 diagnostics hash differs")
    return result


def _validate_predecessor(root: Path, downstream_dir: Path) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    audit = audit_rq5_downstream_output(repo_root=root, output_dir=downstream_dir)
    _require(audit.get("status") == "passed" and audit.get("protocol_version") == DOWNSTREAM_PROTOCOL_VERSION, "Post-downstream audit differs")
    rows = _read_jsonl(downstream_dir / f"{POST_DOWNSTREAM_STATE_BASENAME}.jsonl")
    _require(len(rows) == EXPECTED_STATE_ROWS and len({row["case_id"] for row in rows}) == EXPECTED_STATE_ROWS, "Post-downstream state register differs")
    return rows, audit


def _review_rows(root: Path, review_path: Path) -> list[dict[str, Any]]:
    _require(review_path.is_file() and not review_path.is_symlink(), "Full Context review is missing or unsafe")
    _require(_sha256_file(review_path) == EXPECTED_REVIEW_SHA256, "Full Context review hash differs")
    payload = _read_json(review_path)
    _require(set(payload) == REVIEW_TOP_FIELDS and payload.get("protocol_version") == REVIEW_PROTOCOL_VERSION and payload.get("review_status") == "completed", "Full Context review header differs")
    _require(payload.get("review_unit") == "unique Main-60 Full Context Strict-noncorrect question", "Full Context review unit differs")
    guards = payload.get("guards")
    required_guards = {"unique_question_denominator": 60, "strict_noncorrect_review_count": 14, "full_context_has_no_retrieval": True, "source_visibility_is_not_evidence_recall": True, "source_reference_ambiguity_not_forced_into_model_failure": True, "no_new_model_calls": True, "no_source_mutation": True, "raw_text_fields_absent": True}
    _require(isinstance(guards, Mapping) and dict(guards) == required_guards, "Full Context review guards differ")
    passes = payload.get("review_passes")
    _require(isinstance(passes, list) and len(passes) == 2 and passes[0] == {"order": 1, "name": "source_and_final_input_sufficiency", "candidate_answer_used": False, "judge_outcome_used": False} and passes[1] == {"order": 2, "name": "long_context_and_answerer_utilisation", "candidate_answer_used": True, "judge_outcome_used": True}, "Full Context review pass order differs")
    expected_codebooks = {"content_state": CONTENT_STATES, "final_input_sufficiency_state": SUFFICIENCY_STATES, "long_context_utilisation_state": LONG_CONTEXT_STATES, "answerer_utilisation_state": ANSWERER_STATES, "answer_form": ANSWER_FORMS, "mechanism": PRIMARY_MECHANISMS}
    codebooks = payload.get("codebooks")
    _require(isinstance(codebooks, Mapping) and set(codebooks) == set(expected_codebooks), "Full Context codebook fields differ")
    for key, values in expected_codebooks.items():
        _require(set(codebooks[key]) == values, f"Full Context codebook differs: {key}")
    source_manifest = payload.get("source_manifest")
    _require(isinstance(source_manifest, list) and len(source_manifest) == 5 and {row.get("role") for row in source_manifest if isinstance(row, Mapping)} == {"strict_error_index", "rq4_question_quadrants", "main40_gold", "extension20_gold", "full_context_judge_results"}, "Full Context source manifest differs")
    for binding in source_manifest:
        _require(isinstance(binding, Mapping) and set(binding) == {"role", "path", "sha256"}, "Full Context source binding differs")
        _require(_sha256_file(_safe_file(root, str(binding["path"]))) == binding["sha256"], "Full Context source binding hash differs")

    stage_rows = _read_jsonl(root / STAGE_A_PATH)
    stage = {str(row["question_id"]): row for row in stage_rows if row["condition_id"] == FULL_CONTEXT_CONDITION}
    strict = [row for row in _read_jsonl(root / STAGE1_DIR / "strict-error-cases.jsonl") if row["condition_id"] == FULL_CONTEXT_CONDITION]
    judge_binding = next(binding for binding in payload["source_manifest"] if binding["role"] == "full_context_judge_results")
    judge_rows = _read_json(_safe_file(root, judge_binding["path"]))["results"]
    judges = {str(row["question_id"]): row for row in judge_rows}
    gold_rows = []
    for role in ("main40_gold", "extension20_gold"):
        binding = next(row for row in source_manifest if row["role"] == role)
        gold_rows.extend(_read_jsonl(_safe_file(root, binding["path"])))
    gold = {str(row["question_id"]): row for row in gold_rows}
    cases = payload.get("cases")
    _require(isinstance(cases, list) and len(cases) == EXPECTED_ERROR_CASES and len(strict) == EXPECTED_ERROR_CASES, "Full Context review population differs")
    output = []
    observed_cases: set[str] = set()
    observed_analysis: set[str] = set()
    observed_questions: set[str] = set()
    observed_records: set[str] = set()
    observed_judgments: set[str] = set()
    for ordinal, (case, error) in enumerate(zip(cases, strict), 1):
        _require(isinstance(case, Mapping) and set(case) == REVIEW_ROW_FIELDS and case["review_order"] == ordinal, "Full Context review row fields/order differ")
        qid = str(case["question_id"])
        _require(case["case_id"] not in observed_cases and case["analysis_row_id"] not in observed_analysis and qid not in observed_questions and case["source_record_id"] not in observed_records and case["judgment_id"] not in observed_judgments, "Full Context review identities repeat")
        observed_cases.add(str(case["case_id"])); observed_analysis.add(str(case["analysis_row_id"])); observed_questions.add(qid); observed_records.add(str(case["source_record_id"])); observed_judgments.add(str(case["judgment_id"]))
        source = stage[qid]
        _require(qid == error["question_id"] and case["case_id"] == error["case_id"] and case["analysis_row_id"] == source["analysis_row_id"], "Full Context review case identity differs")
        _require(case["question_sha256"] == source["question_sha256"] and case["category_name"] == source["category_name"] and case["judge_label"] == source["judge_label"] and case["evidence_eligible"] == source["evidence_eligible"], "Full Context review Stage A identity differs")
        _require(case["source_record_id"] == source["source_record_id"] and case["source_record_path"] == source["source_record_path"] and case["source_record_file_sha256"] == source["source_record_file_sha256"] and case["source_record_payload_sha256"] == source["source_record_payload_sha256"], "Full Context record binding differs")
        record_path = _safe_file(root, case["source_record_path"])
        _require(_sha256_file(record_path) == case["source_record_file_sha256"], "Full Context record file hash differs")
        record_mapping = _read_json(record_path)
        record = full_context_record_from_mapping(record_mapping)
        _require(sha256_bytes(canonical_json_bytes(record_mapping)) == case["source_record_payload_sha256"] and record.record_id == case["source_record_id"], "Full Context record payload identity differs")
        judge = judges[qid]
        _require(case["judgment_id"] == judge["judgment_id"] and case["reference_answer_sha256"] == judge["reference_answer_sha256"] and case["candidate_answer_sha256"] == judge["candidate_answer_sha256"] and judge["source_record_id"] == case["source_record_id"] and judge["question_sha256"] == case["question_sha256"] and judge["label"] == case["judge_label"], "Full Context Judge identity differs")
        _require(case["candidate_answer_sha256"] == sha256_bytes(record.answer_result.answer.encode("utf-8")), "Full Context answer hash differs")
        gold_row = gold[qid]
        _require(case["reference_answer_sha256"] == sha256_bytes(str(gold_row["answer"]).encode("utf-8")) and case["gold_dia_ids"] == gold_row["gold_evidence_dia_ids"] and case["category_name"] == gold_row["category_name"], "Full Context gold identity differs")
        content, sufficiency = str(case["content_state"]), str(case["final_input_sufficiency_state"])
        long_state, answerer = str(case["long_context_utilisation_state"]), str(case["answerer_utilisation_state"])
        _require(content in CONTENT_STATES and sufficiency in SUFFICIENCY_STATES and long_state in LONG_CONTEXT_STATES and answerer in ANSWERER_STATES, "Full Context review state differs")
        _require(sufficiency == ("sufficient" if content == "complete_but_noisy" else "indeterminate"), "Full Context sufficiency derivation differs")
        _require(sufficiency == "sufficient" or (long_state == "indeterminate" and answerer == "indeterminate"), "Full Context utilisation gate differs")
        _require(case["answer_form"] in ANSWER_FORMS and case["primary_mechanism"] in PRIMARY_MECHANISMS and case["confidence"] in CONFIDENCE_LEVELS and case["review_status"] == "completed" and case["manual_content_inspected"] is True, "Full Context review completion differs")
        _require(isinstance(case["secondary_mechanisms"], list) and len(case["secondary_mechanisms"]) == len(set(case["secondary_mechanisms"])) and set(case["secondary_mechanisms"]) <= SECONDARY_MECHANISMS, "Full Context secondary mechanisms differ")
        output.append({key: case[key] for key in REVIEW_ROW_FIELDS - {"rationale"}})
    _require(Counter(row["judge_label"] for row in output) == {"partial": 7, "incorrect": 7}, "Full Context Judge-label distribution differs")
    _require(Counter(row["category_name"] for row in output) == {"single-hop": 5, "open-domain": 4, "temporal": 3, "multi-hop": 2}, "Full Context category distribution differs")
    _require(Counter(bool(row["evidence_eligible"]) for row in output) == {True: 13, False: 1}, "Full Context eligibility distribution differs")
    _require(Counter(row["content_state"] for row in output) == {"complete_but_noisy": 9, "indeterminate": 5}, "Full Context content-state distribution differs")
    _require(Counter(row["final_input_sufficiency_state"] for row in output) == {"sufficient": 9, "indeterminate": 5}, "Full Context sufficiency distribution differs")
    _require(Counter(row["long_context_utilisation_state"] for row in output) == {"successful": 3, "missed_relevant_content": 3, "indeterminate": 5, "distractor_confusion": 2, "temporal_confusion": 1}, "Full Context utilisation distribution differs")
    _require(Counter(row["answerer_utilisation_state"] for row in output) == {"misused_evidence": 5, "unsupported_abstention": 4, "indeterminate": 5}, "Full Context Answerer distribution differs")
    _require(Counter(row["answer_form"] for row in output) == {"under_answering": 5, "indeterminate": 5, "over_answering_with_missing_relation": 2, "incorrect_temporal_or_state_selection": 1, "fine_grained_attribute_omission": 1}, "Full Context answer-form distribution differs")
    _require(Counter(row["confidence"] for row in output) == {"high": 13, "medium": 1}, "Full Context confidence distribution differs")
    audit = payload.get("audit")
    _require(isinstance(audit, Mapping) and audit.get("status") == "passed" and audit.get("actual_case_count") == 14 and audit.get("unique_case_ids") == 14 and audit.get("sufficiency_gate_respected") is True and audit.get("raw_text_fields_absent") is True, "Full Context review audit differs")
    return output


def _public_review_rows(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    fields = ("case_id", "analysis_row_id", "question_id", "question_sha256", "category_name", "judge_label", "evidence_eligible", "content_state", "final_input_sufficiency_state", "long_context_utilisation_state", "answerer_utilisation_state", "answer_form", "primary_mechanism", "secondary_mechanisms", "confidence", "source_record_id", "judgment_id")
    return [{"result_id": _artifact_id("rq5-full-context-review-", body), **body} for row in rows for body in ({"protocol_version": PROTOCOL_VERSION, **{field: row[field] for field in fields}},)]


def _summary(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    dimensions = (
        ("content_state", "content_state"),
        ("final_input_sufficiency", "final_input_sufficiency_state"),
        ("long_context_utilisation", "long_context_utilisation_state"),
        ("answerer_utilisation", "answerer_utilisation_state"),
        ("answer_form", "answer_form"),
        ("primary_mechanism", "primary_mechanism"),
    )
    category_scopes = ("ALL", *sorted({str(row["category_name"]) for row in rows}))
    for category_scope in category_scopes:
        scoped = list(rows) if category_scope == "ALL" else [row for row in rows if row["category_name"] == category_scope]
        _require(scoped, f"Empty Full Context summary category: {category_scope}")
        for dimension, field in dimensions:
            counts = Counter(str(row[field]) for row in scoped)
            for state in sorted(counts):
                body = {
                    "protocol_version": PROTOCOL_VERSION,
                    "dimension": dimension,
                    "state": state,
                    "category_scope": category_scope,
                    "count": counts[state],
                    "denominator": len(scoped),
                    "rate": counts[state] / len(scoped),
                }
                output.append({"result_id": _artifact_id("rq5-full-context-summary-", body), **body})
    return output


def _diagnostics(root: Path) -> list[dict[str, Any]]:
    source = _read_jsonl(root / RQ4_DIR / "question-quadrants.jsonl")
    conditions = tuple(f"E{index}" for index in range(1, 8))
    quadrants = ("both_correct", "full_context_only", "selective_only", "neither_correct")
    _require(len(source) == EXPECTED_RQ4_ROWS, "RQ4 Full Context diagnostic population differs")
    _require({str(row["selective_condition"]) for row in source} == set(conditions), "RQ4 selective condition set differs")
    _require({str(row["strict_quadrant"]) for row in source} == set(quadrants), "RQ4 strict quadrant set differs")
    question_ids = {str(row["question_id"]) for row in source}
    _require(len(question_ids) == 60, "RQ4 unique-question denominator differs")
    by_question: dict[str, list[Mapping[str, Any]]] = {question_id: [] for question_id in question_ids}
    output: list[dict[str, Any]] = []
    for condition in conditions:
        selected = [row for row in source if row["selective_condition"] == condition]
        _require(len(selected) == 60 and len({str(row["question_id"]) for row in selected}) == 60, f"RQ4 {condition} denominator differs")
        counts = Counter(str(row["strict_quadrant"]) for row in selected)
        _require(dict(counts) == EXPECTED_PAIRWISE_COUNTS[condition], f"RQ4 {condition} quadrant counts differ")
        for row in selected:
            by_question[str(row["question_id"])].append(row)
        for quadrant in quadrants:
            body = {
                "protocol_version": PROTOCOL_VERSION,
                "comparison_scope": "pairwise_selective_condition",
                "selective_condition": condition,
                "strict_quadrant": quadrant,
                "count": counts[quadrant],
                "denominator": 60,
                "rate": counts[quadrant] / 60,
                "source_pairings": EXPECTED_RQ4_ROWS,
                "comparison_is_descriptive": True,
                "oracle_style_descriptive": False,
                "deployable_comparison": True,
            }
            output.append({"result_id": _artifact_id("rq5-full-context-diagnostic-", body), **body})

    any_counts: Counter[str] = Counter()
    for question_id, question_rows in by_question.items():
        _require(len(question_rows) == 7, f"RQ4 question does not have seven selective comparisons: {question_id}")
        full_context_values = {float(row["full_context_strict_accuracy"]) for row in question_rows}
        _require(len(full_context_values) == 1, f"RQ4 Full Context outcome differs within question: {question_id}")
        full_context_correct = next(iter(full_context_values)) == 1.0
        any_selective_correct = any(float(row["selective_strict_accuracy"]) == 1.0 for row in question_rows)
        if full_context_correct and any_selective_correct:
            any_counts["both_correct"] += 1
        elif full_context_correct:
            any_counts["full_context_only"] += 1
        elif any_selective_correct:
            any_counts["selective_only"] += 1
        else:
            any_counts["neither_correct"] += 1
    _require({quadrant: any_counts[quadrant] for quadrant in quadrants} == EXPECTED_ANY_SELECTIVE_COUNTS, "RQ4 any-selective quadrant counts differ")
    for quadrant in quadrants:
        body = {
            "protocol_version": PROTOCOL_VERSION,
            "comparison_scope": "any_selective",
            "selective_condition": "ANY_SELECTIVE",
            "strict_quadrant": quadrant,
            "count": any_counts[quadrant],
            "denominator": 60,
            "rate": any_counts[quadrant] / 60,
            "source_pairings": EXPECTED_RQ4_ROWS,
            "comparison_is_descriptive": True,
            "oracle_style_descriptive": True,
            "deployable_comparison": False,
        }
        output.append({"result_id": _artifact_id("rq5-full-context-diagnostic-", body), **body})
    _require(len(output) == EXPECTED_DIAGNOSTIC_ROWS, "Full Context selective diagnostic count differs")
    return output


def _question_diagnostics(root: Path) -> list[dict[str, Any]]:
    """Collapse the 420 frozen pairings to the 60 unique Full Context answers."""

    source = _read_jsonl(root / RQ4_DIR / "question-quadrants.jsonl")
    stage_rows = [
        row for row in _read_jsonl(root / STAGE_A_PATH)
        if row["condition_id"] == FULL_CONTEXT_CONDITION
    ]
    _require(len(stage_rows) == EXPECTED_FULL_CONTEXT_QUESTIONS, "Full Context Stage A population differs")
    stage = {str(row["question_id"]): row for row in stage_rows}
    _require(len(stage) == EXPECTED_FULL_CONTEXT_QUESTIONS, "Full Context Stage A questions repeat")
    by_question: dict[str, list[Mapping[str, Any]]] = {}
    for row in source:
        by_question.setdefault(str(row["question_id"]), []).append(row)
    _require(set(by_question) == set(stage), "RQ4 and Stage A Full Context questions differ")

    output: list[dict[str, Any]] = []
    for qid, full_context in sorted(stage.items(), key=lambda item: int(item[1]["global_position"])):
        comparisons = by_question[qid]
        _require(
            len(comparisons) == 7
            and {str(row["selective_condition"]) for row in comparisons} == {f"E{i}" for i in range(1, 8)},
            f"Full Context question lacks seven selective comparisons: {qid}",
        )
        for field, rq4_field in (
            ("strict_score", "full_context_strict_accuracy"),
            ("soft_semantic_score", "full_context_soft_semantic_score"),
            ("token_precision", "full_context_token_precision"),
            ("token_recall", "full_context_token_recall"),
            ("token_f1", "full_context_token_f1"),
            ("answer_normalized_tokens", "full_context_answer_normalized_tokens"),
            ("answer_prompt_tokens", "full_context_answer_prompt_tokens"),
            ("answer_total_tokens", "full_context_answer_total_tokens"),
            ("evidence_bundle_characters", "full_context_characters"),
        ):
            _require(
                all(row[rq4_field] == full_context[field] for row in comparisons),
                f"RQ4 Full Context field differs within question: {qid}/{field}",
            )
        full_correct = float(full_context["strict_score"]) == 1.0
        selective_correct_count = sum(float(row["selective_strict_accuracy"]) == 1.0 for row in comparisons)
        any_selective_correct = selective_correct_count > 0
        any_quadrant = (
            "both_correct" if full_correct and any_selective_correct
            else "full_context_only" if full_correct
            else "selective_only" if any_selective_correct
            else "neither_correct"
        )
        body = {
            "protocol_version": PROTOCOL_VERSION,
            "analysis_row_id": full_context["analysis_row_id"],
            "global_position": int(full_context["global_position"]),
            "question_id": qid,
            "question_sha256": full_context["question_sha256"],
            "category": int(full_context["category"]),
            "category_name": full_context["category_name"],
            "evidence_eligible": bool(full_context["evidence_eligible"]),
            "gold_source_count": len(full_context["gold_dia_ids"]),
            "judge_label": full_context["judge_label"],
            "strict_score": float(full_context["strict_score"]),
            "soft_semantic_score": float(full_context["soft_semantic_score"]),
            "token_precision": float(full_context["token_precision"]),
            "token_recall": float(full_context["token_recall"]),
            "token_f1": float(full_context["token_f1"]),
            "answer_normalized_tokens": int(full_context["answer_normalized_tokens"]),
            "answer_prompt_tokens": int(full_context["answer_prompt_tokens"]),
            "answer_total_tokens": int(full_context["answer_total_tokens"]),
            "full_context_characters": int(full_context["evidence_bundle_characters"]),
            "selective_correct_count": selective_correct_count,
            "any_selective_correct": any_selective_correct,
            "any_selective_quadrant": any_quadrant,
            "oracle_style_descriptive": True,
            "deployable_comparison": False,
            "source_record_id": full_context["source_record_id"],
        }
        output.append({"result_id": _artifact_id("rq5-full-context-question-", body), **body})
    _require(len(output) == EXPECTED_FULL_CONTEXT_QUESTIONS, "Full Context unique-question table differs")
    counts = Counter(row["any_selective_quadrant"] for row in output)
    _require(
        {state: counts[state] for state in EXPECTED_ANY_SELECTIVE_COUNTS} == EXPECTED_ANY_SELECTIVE_COUNTS,
        "Full Context any-selective question states differ",
    )
    return output


def _category_summary(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for category in sorted({str(row["category_name"]) for row in rows}):
        selected = [row for row in rows if row["category_name"] == category]
        quadrants = Counter(str(row["any_selective_quadrant"]) for row in selected)
        correct = sum(float(row["strict_score"]) == 1.0 for row in selected)
        body = {
            "protocol_version": PROTOCOL_VERSION,
            "category_name": category,
            "question_count": len(selected),
            "strict_correct_count": correct,
            "strict_error_count": len(selected) - correct,
            "strict_accuracy": correct / len(selected),
            "mean_soft_semantic_score": sum(float(row["soft_semantic_score"]) for row in selected) / len(selected),
            "mean_token_precision": sum(float(row["token_precision"]) for row in selected) / len(selected),
            "mean_token_recall": sum(float(row["token_recall"]) for row in selected) / len(selected),
            "mean_token_f1": sum(float(row["token_f1"]) for row in selected) / len(selected),
            "mean_answer_normalized_tokens": sum(int(row["answer_normalized_tokens"]) for row in selected) / len(selected),
            "both_correct_count": quadrants["both_correct"],
            "full_context_only_count": quadrants["full_context_only"],
            "selective_only_count": quadrants["selective_only"],
            "neither_correct_count": quadrants["neither_correct"],
            "oracle_style_descriptive": True,
        }
        output.append({"result_id": _artifact_id("rq5-full-context-category-", body), **body})
    _require(len(output) == 4 and sum(row["question_count"] for row in output) == EXPECTED_FULL_CONTEXT_QUESTIONS, "Full Context category summary differs")
    return output


def _answer_profile(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for outcome, selected in (
        ("strict_correct", [row for row in rows if float(row["strict_score"]) == 1.0]),
        ("strict_noncorrect", [row for row in rows if float(row["strict_score"]) == 0.0]),
    ):
        _require(selected, f"Full Context answer-profile cell is empty: {outcome}")
        body = {
            "protocol_version": PROTOCOL_VERSION,
            "strict_outcome": outcome,
            "question_count": len(selected),
            "mean_answer_normalized_tokens": sum(int(row["answer_normalized_tokens"]) for row in selected) / len(selected),
            "median_answer_normalized_tokens": statistics.median(int(row["answer_normalized_tokens"]) for row in selected),
            "mean_token_precision": sum(float(row["token_precision"]) for row in selected) / len(selected),
            "mean_token_recall": sum(float(row["token_recall"]) for row in selected) / len(selected),
            "mean_token_f1": sum(float(row["token_f1"]) for row in selected) / len(selected),
            "mean_soft_semantic_score": sum(float(row["soft_semantic_score"]) for row in selected) / len(selected),
        }
        output.append({"result_id": _artifact_id("rq5-full-context-answer-profile-", body), **body})
    _require({row["strict_outcome"]: row["question_count"] for row in output} == {"strict_correct": 46, "strict_noncorrect": 14}, "Full Context answer-profile denominator differs")
    return output


def _evidence_positions(root: Path, questions: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    stage = {
        str(row["question_id"]): row
        for row in _read_jsonl(root / STAGE_A_PATH)
        if row["condition_id"] == FULL_CONTEXT_CONDITION
    }
    output: list[dict[str, Any]] = []
    for question in questions:
        source = stage[str(question["question_id"])]
        record_path = _safe_file(root, str(source["source_record_path"]))
        _require(
            _sha256_file(record_path) == source["source_record_file_sha256"],
            f"Full Context record file hash differs: {question['question_id']}",
        )
        mapping = _read_json(record_path)
        _require(
            sha256_bytes(canonical_json_bytes(mapping)) == source["source_record_payload_sha256"],
            f"Full Context record payload hash differs: {question['question_id']}",
        )
        record = full_context_record_from_mapping(mapping)
        _require(
            record.record_id == source["source_record_id"]
            and record.question.question_id == question["question_id"]
            and record.question.sha256 == source["question_sha256"]
            and record.evidence_bundle.bundle_id == source["evidence_bundle_id"],
            f"Full Context record identity differs: {question['question_id']}",
        )
        if not question["evidence_eligible"]:
            continue
        items = mapping["evidence_bundle"]["evidence_items"]
        context_stats = mapping["evidence_bundle"]["context_stats"]
        _require(context_stats["turn_count"] == EXPECTED_FULL_CONTEXT_TURNS and context_stats["evidence_characters"] == EXPECTED_FULL_CONTEXT_CHARACTERS, "Full Context dimensions differ")
        index: dict[str, Mapping[str, Any]] = {}
        for item in items:
            for record in item["source_records"]:
                dia_id = str(record["dia_id"])
                _require(dia_id not in index, "Full Context source record repeats")
                index[dia_id] = record
        _require(len(index) == EXPECTED_FULL_CONTEXT_TURNS, "Full Context source-record census differs")
        gold_ids = list(source["gold_dia_ids"])
        _require(gold_ids and all(dia_id in index for dia_id in gold_ids), "Eligible Full Context gold source is missing")
        records = [index[dia_id] for dia_id in gold_ids]
        turns = sorted(int(record["global_turn_index"]) for record in records)
        sessions = sorted(int(record["session_index"]) for record in records)
        divisor = EXPECTED_FULL_CONTEXT_TURNS - 1
        earliest = (turns[0] - 1) / divisor
        latest = (turns[-1] - 1) / divisor
        body = {
            "protocol_version": PROTOCOL_VERSION,
            "analysis_row_id": question["analysis_row_id"],
            "global_position": int(question["global_position"]),
            "question_id": question["question_id"],
            "category_name": question["category_name"],
            "strict_outcome": "strict_correct" if float(question["strict_score"]) == 1.0 else "strict_noncorrect",
            "gold_source_count": len(gold_ids),
            "earliest_normalized_turn_position": earliest,
            "latest_normalized_turn_position": latest,
            "midrange_normalized_turn_position": (earliest + latest) / 2,
            "position_normalization_basis": "zero_based_global_turn_ordinal_divided_by_567",
            "midrange_definition": "midpoint_of_earliest_and_latest_gold_turn_positions",
            "global_turn_span": turns[-1] - turns[0],
            "session_span": sessions[-1] - sessions[0],
            "full_context_turn_count": EXPECTED_FULL_CONTEXT_TURNS,
            "full_context_characters": EXPECTED_FULL_CONTEXT_CHARACTERS,
            "source_visibility_by_construction": True,
            "evidence_recall_applicable": False,
        }
        output.append({"result_id": _artifact_id("rq5-full-context-position-", body), **body})
    _require(len(output) == EXPECTED_EVIDENCE_ELIGIBLE_QUESTIONS, "Full Context evidence-position denominator differs")
    return output


def _position_summary(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for category_scope in ("ALL", *sorted({str(row["category_name"]) for row in rows})):
        category_rows = list(rows) if category_scope == "ALL" else [row for row in rows if row["category_name"] == category_scope]
        for strict_outcome in ("strict_correct", "strict_noncorrect"):
            selected = [row for row in category_rows if row["strict_outcome"] == strict_outcome]
            if not selected:
                continue
            body = {
                "protocol_version": PROTOCOL_VERSION,
                "category_scope": category_scope,
                "strict_outcome": strict_outcome,
                "question_count": len(selected),
                "mean_earliest_normalized_turn_position": sum(float(row["earliest_normalized_turn_position"]) for row in selected) / len(selected),
                "median_earliest_normalized_turn_position": statistics.median(float(row["earliest_normalized_turn_position"]) for row in selected),
                "mean_latest_normalized_turn_position": sum(float(row["latest_normalized_turn_position"]) for row in selected) / len(selected),
                "median_latest_normalized_turn_position": statistics.median(float(row["latest_normalized_turn_position"]) for row in selected),
                "mean_midrange_normalized_turn_position": sum(float(row["midrange_normalized_turn_position"]) for row in selected) / len(selected),
                "median_midrange_normalized_turn_position": statistics.median(float(row["midrange_normalized_turn_position"]) for row in selected),
                "position_normalization_basis": "zero_based_global_turn_ordinal_divided_by_567",
                "midrange_definition": "midpoint_of_earliest_and_latest_gold_turn_positions",
                "mean_global_turn_span": sum(int(row["global_turn_span"]) for row in selected) / len(selected),
                "median_global_turn_span": statistics.median(int(row["global_turn_span"]) for row in selected),
                "mean_session_span": sum(int(row["session_span"]) for row in selected) / len(selected),
                "median_session_span": statistics.median(int(row["session_span"]) for row in selected),
                "mean_gold_source_count": sum(int(row["gold_source_count"]) for row in selected) / len(selected),
                "evidence_recall_applicable": False,
            }
            output.append({"result_id": _artifact_id("rq5-full-context-position-summary-", body), **body})
    overall = {row["strict_outcome"]: row["question_count"] for row in output if row["category_scope"] == "ALL"}
    _require(overall == {"strict_correct": 45, "strict_noncorrect": 13}, "Eligible Full Context outcome denominator differs")
    return output


def _updated_register(predecessor: Sequence[Mapping[str, Any]], rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    reviews = {str(row["case_id"]): row for row in rows}
    output = []
    for source in predecessor:
        before, updated = dict(source), dict(source)
        if source["condition_id"] == FULL_CONTEXT_CONDITION:
            review = reviews[str(source["case_id"])]
            for field in OWNED_STATE_FIELDS:
                updated[field] = review[field]
        changed = {field for field in set(before) | set(updated) if before.get(field) != updated.get(field)}
        _require(changed <= set(OWNED_STATE_FIELDS), "Full Context stage changed an unowned state field")
        if source["condition_id"] != FULL_CONTEXT_CONDITION:
            _require(canonical_json_bytes(before) == canonical_json_bytes(updated), "Full Context stage changed a non-Full-Context row")
        else:
            _require(all(updated[field] not in {"pending", "not_applicable"} for field in OWNED_STATE_FIELDS), "Full Context state remained nonterminal")
        output.append(updated)
    _require(len(output) == EXPECTED_STATE_ROWS and len(reviews) == EXPECTED_ERROR_CASES, "Full Context state register count differs")
    return output


def _assert_text_free(tables: Mapping[str, Sequence[Mapping[str, Any]]]) -> None:
    def inspect(value: Any) -> None:
        if isinstance(value, Mapping):
            for key, nested in value.items():
                lowered = str(key).casefold()
                _require(lowered not in FORBIDDEN_FIELDS and not any(token in lowered for token in ("password", "api_key", "authorization", "secret")), f"Forbidden Full Context output field: {key}")
                inspect(nested)
        elif isinstance(value, (list, tuple)):
            for nested in value:
                inspect(nested)
    inspect(tables)


def _core(root: Path, downstream_dir: Path, review_path: Path) -> tuple[dict[str, list[dict[str, Any]]], dict[str, Any]]:
    _validate_rq4(root)
    predecessor, upstream = _validate_predecessor(root, downstream_dir)
    reviews = _review_rows(root, review_path)
    questions = _question_diagnostics(root)
    positions = _evidence_positions(root, questions)
    tables = {
        "full-context-mechanisms": _public_review_rows(reviews),
        "full-context-diagnostic-matrix": _diagnostics(root),
        "full-context-question-diagnostics": questions,
        "full-context-category-summary": _category_summary(questions),
        "full-context-answer-profile": _answer_profile(questions),
        "evidence-position-diagnostics": positions,
        "evidence-position-summary": _position_summary(positions),
        "full-context-summary": _summary(reviews),
        POST_FULL_CONTEXT_STATE_BASENAME: _updated_register(predecessor, reviews),
    }
    _assert_text_free(tables)
    return tables, upstream


def _payloads(tables: Mapping[str, Sequence[Mapping[str, Any]]], root: Path, downstream_dir: Path, review_path: Path, upstream: Mapping[str, Any]) -> dict[str, bytes]:
    output = {}
    for name in TABLES:
        output[f"{name}.jsonl"] = _jsonl_payload(tables[name])
        output[f"{name}.csv"] = _csv_payload(tables[name])
    stage_rows = [row for row in _read_jsonl(root / STAGE_A_PATH) if row["condition_id"] == FULL_CONTEXT_CONDITION]
    source_paths = (
        downstream_dir / f"{POST_DOWNSTREAM_STATE_BASENAME}.jsonl",
        downstream_dir / "audit.json",
        downstream_dir / "RQ5-DOWNSTREAM.PASSED",
        review_path,
        root / RQ4_DIR / "question-quadrants.jsonl",
        root / RQ4_DIR / "audit.json",
        root / RQ4_DIR / "RQ4.PASSED",
        root / STAGE_A_PATH,
        *(root / str(row["source_record_path"]) for row in stage_rows),
    )
    manifest = {"protocol_version": PROTOCOL_VERSION, "downstream_audit_id": upstream["audit_id"], "files": [{"path": path.resolve().relative_to(root.resolve()).as_posix(), "sha256": _sha256_file(path)} for path in source_paths], "no_api_calls": True, "formal_source_mutation": False}
    manifest = {"source_manifest_id": _artifact_id("rq5-full-context-sources-", manifest), **manifest}
    schema = {"schema_version": 1, "protocol_version": PROTOCOL_VERSION, "scope": "Chapter 5 Section 5.6.4.4 only", "owned_state_fields": list(OWNED_STATE_FIELDS), "post_full_context_state_jsonl": POST_FULL_CONTEXT_STATE_PATH, "tables": {name: {"rows": len(tables[name]), "fields": list(tables[name][0]) if tables[name] else []} for name in TABLES}, "public_tables_are_text_free": True}
    output["source-manifest.json"] = canonical_json_bytes(manifest) + b"\n"
    output["schema.json"] = canonical_json_bytes(schema) + b"\n"
    output["README.md"] = (
        "# Chapter 5 RQ5 Full Context audit\n\n"
        "This offline stage reviews the 14 unique Main-60 Full Context Strict-noncorrect questions. "
        "It updates only Full Context final-input sufficiency, long-context utilisation, and Answerer-utilisation states.\n\n"
        "The diagnostic matrix aggregates the frozen 420 paired RQ4 comparisons over 60 questions. "
        "Its any-selective view is oracle-style, descriptive, and not deployable. Complete source visibility is not Evidence Recall.\n\n"
        "The unique-question table prevents the 420 pairings from inflating the 60-answer denominator. "
        "All 60 Full Context records are bound to Stage A by file hash, canonical-payload hash, record ID, question identity, and bundle identity. "
        "Evidence-position diagnostics cover only the 58 questions with gold source annotations and never report Full Context Evidence Recall. "
        "Position is the zero-based global-turn ordinal divided by 567, not a character or token offset; midrange is the midpoint of the earliest and latest gold-turn positions.\n\n"
        "The review supports failure-mechanism analysis only; repair mechanisms for Full-Context-only successes were not computed. "
        "This stage performs no evaluation and no primary-cause attribution.\n\n"
        f"Final post-stage register: `{POST_FULL_CONTEXT_STATE_PATH}`.\n"
    ).encode("utf-8")
    return output


def build_rq5_full_context(*, repo_root: Path, output_dir: Path, downstream_dir: Path | None = None, review_path: Path | None = None) -> dict[str, Any]:
    root, destination = Path(repo_root).resolve(), Path(output_dir).resolve()
    predecessor = (root / DEFAULT_DOWNSTREAM_DIR).resolve() if downstream_dir is None else Path(downstream_dir).resolve()
    review = (root / DEFAULT_REVIEW_PATH).resolve() if review_path is None else Path(review_path).resolve()
    _require(not destination.exists(), "RQ5 Full Context output already exists")
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=".rq5-full-context-", dir=destination.parent))
    try:
        tables, upstream = _core(root, predecessor, review)
        payloads = _payloads(tables, root, predecessor, review, upstream)
        for name, payload in payloads.items():
            _write(temporary / name, payload)
        hashes = {name: _sha256_file(temporary / name) for name in sorted(payloads)}
        body = {"schema_version": 1, "protocol_version": PROTOCOL_VERSION, "status": "passed", "counts": {name: len(tables[name]) for name in TABLES}, "downstream_audit_id": upstream["audit_id"], "output_sha256": hashes, "state_rows": EXPECTED_STATE_ROWS, "full_context_error_rows": EXPECTED_ERROR_CASES, "full_context_unique_question_rows": EXPECTED_FULL_CONTEXT_QUESTIONS, "evidence_position_rows": EXPECTED_EVIDENCE_ELIGIBLE_QUESTIONS, "selective_diagnostic_rows": EXPECTED_DIAGNOSTIC_ROWS, "repair_mechanism_analysis_computed": False, "evaluation_analysis_computed": False, "primary_attribution_computed": False, "public_tables_are_text_free": True, "no_api_calls": True, "formal_source_mutation": False}
        audit = {"audit_id": _artifact_id("rq5-full-context-audit-", body), **body}
        _write(temporary / "audit.json", canonical_json_bytes(audit) + b"\n")
        marker = {"schema_version": 1, "protocol_version": PROTOCOL_VERSION, "status": "passed", "audit_id": audit["audit_id"], "audit_sha256": _sha256_file(temporary / "audit.json"), "state_rows": EXPECTED_STATE_ROWS, "no_api_calls": True}
        _write(temporary / "RQ5-FULL-CONTEXT.PASSED", canonical_json_bytes(marker) + b"\n")
        _audit_existing(root, temporary, predecessor, review)
        os.rename(temporary, destination)
    except Exception:
        shutil.rmtree(temporary, ignore_errors=True)
        raise
    return _audit_existing(root, destination, predecessor, review)


def _audit_existing(root: Path, output: Path, downstream_dir: Path, review_path: Path) -> dict[str, Any]:
    tables, upstream = _core(root, downstream_dir, review_path)
    payloads = _payloads(tables, root, downstream_dir, review_path, upstream)
    hashes = {name: hashlib.sha256(payload).hexdigest() for name, payload in sorted(payloads.items())}
    body = {"schema_version": 1, "protocol_version": PROTOCOL_VERSION, "status": "passed", "counts": {name: len(tables[name]) for name in TABLES}, "downstream_audit_id": upstream["audit_id"], "output_sha256": hashes, "state_rows": EXPECTED_STATE_ROWS, "full_context_error_rows": EXPECTED_ERROR_CASES, "full_context_unique_question_rows": EXPECTED_FULL_CONTEXT_QUESTIONS, "evidence_position_rows": EXPECTED_EVIDENCE_ELIGIBLE_QUESTIONS, "selective_diagnostic_rows": EXPECTED_DIAGNOSTIC_ROWS, "repair_mechanism_analysis_computed": False, "evaluation_analysis_computed": False, "primary_attribution_computed": False, "public_tables_are_text_free": True, "no_api_calls": True, "formal_source_mutation": False}
    audit = {"audit_id": _artifact_id("rq5-full-context-audit-", body), **body}
    audit_payload = canonical_json_bytes(audit) + b"\n"
    marker = {"schema_version": 1, "protocol_version": PROTOCOL_VERSION, "status": "passed", "audit_id": audit["audit_id"], "audit_sha256": hashlib.sha256(audit_payload).hexdigest(), "state_rows": EXPECTED_STATE_ROWS, "no_api_calls": True}
    expected = set(payloads) | {"audit.json", "RQ5-FULL-CONTEXT.PASSED"}
    entries = list(output.iterdir()) if output.is_dir() and not output.is_symlink() else []
    _require(output.is_dir() and not output.is_symlink() and all(path.is_file() and not path.is_symlink() for path in entries) and {path.name for path in entries} == expected, "RQ5 Full Context output file set differs")
    for name, payload in payloads.items():
        _require((output / name).read_bytes() == payload, f"RQ5 Full Context artifact differs: {name}")
    _require((output / "audit.json").read_bytes() == audit_payload and (output / "RQ5-FULL-CONTEXT.PASSED").read_bytes() == canonical_json_bytes(marker) + b"\n", "RQ5 Full Context audit or marker differs")
    return audit


def audit_rq5_full_context_output(*, repo_root: Path, output_dir: Path, downstream_dir: Path | None = None, review_path: Path | None = None) -> dict[str, Any]:
    root = Path(repo_root).resolve()
    return _audit_existing(root, Path(output_dir).resolve(), (root / DEFAULT_DOWNSTREAM_DIR).resolve() if downstream_dir is None else Path(downstream_dir).resolve(), (root / DEFAULT_REVIEW_PATH).resolve() if review_path is None else Path(review_path).resolve())


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("build", "audit"))
    parser.add_argument("--repo-root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--downstream-dir", type=Path)
    parser.add_argument("--review", type=Path)
    args = parser.parse_args(argv)
    kwargs = {"repo_root": args.repo_root, "output_dir": args.output_dir, "downstream_dir": args.downstream_dir, "review_path": args.review}
    result = build_rq5_full_context(**kwargs) if args.command == "build" else audit_rq5_full_context_output(**kwargs)
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
