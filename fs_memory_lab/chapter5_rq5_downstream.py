"""Offline downstream audit for Chapter 5 Sections 5.6.4.1--5.6.4.3.

This stage is deliberately narrower than the complete RQ5 decomposition.  It
first freezes content-based sufficiency and packaging judgements for every
E1--E6 path, then evaluates Answerer utilisation, and only then joins the E2
and E6 parent states to the exact deterministic E7 fusion.  Full Context,
evaluation disagreement, and primary/secondary causal attribution belong to
later stages and are never changed here.

Review inputs may inspect private source text, but every published table is
identifier-, category-, state-, count-, metric-, and hash-only.  No question,
answer, evidence, prompt, rationale, or secret text is copied to the output.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import shutil
import tempfile
from collections import Counter, defaultdict
from pathlib import Path, PurePosixPath
from typing import Any, Iterable, Mapping, Sequence

from .chapter5_rq3 import audit_rq3_output
from .chapter5_rq5_retrieval import audit_rq5_retrieval_output
from .chapter5_rq5_stage1 import audit_rq5_stage1_output
from .chapter5_rq5_storage import audit_rq5_storage_output
from .chapter5_stage_b import (
    _csv_payload,
    _jsonl_payload,
    _read_json,
    _read_jsonl,
    _require,
    _sha256_file,
    _write,
)
from .evidence import EvidenceBundle, canonical_json_bytes, sha256_bytes
from .fusion import (
    FusionEvidenceBundle,
    build_e7_fusion_bundle,
)
from .run_records import RunRecord, run_record_from_mapping


PROTOCOL_VERSION = "chapter5-main60-rq5-downstream-v1"
DOWNSTREAM_REVIEW_PROTOCOL_VERSIONS = {
    "qwen": "chapter5-rq5-qwen-downstream-content-review-v1",
    "deepseek": "chapter5-rq5-deepseek-downstream-review-v1",
}
E7_MECHANISM_REVIEW_PROTOCOL_VERSION = "chapter5-rq5-e7-mechanism-review-v1"
E7_ERROR_REVIEW_PROTOCOL_VERSION = "chapter5-rq5-e7-error-downstream-review-v1"

BACKBONES = ("qwen", "deepseek")
SELECTIVE_CONDITIONS = ("E1", "E2", "E3", "E4", "E5", "E6")
FUSED_CONDITION = "E7"
FULL_CONTEXT_CONDITION = "B3-FullContext"
CONDITION_ORDER = {condition: index for index, condition in enumerate((*SELECTIVE_CONDITIONS, FUSED_CONDITION), 1)}
EXPECTED_SELECTIVE_PATHS = 720
EXPECTED_SELECTIVE_ERRORS = 205
EXPECTED_SELECTIVE_ERRORS_BY_BACKBONE = {"qwen": 99, "deepseek": 106}
EXPECTED_FUSED_PATHS = 120
EXPECTED_FUSED_ERRORS = 31
EXPECTED_MECHANISM_CANDIDATES = 12
EXPECTED_STATE_ROWS = 250

STAGE_A_DIR = "artifacts/chapter5-main60-analysis-v1/stage-a"
STAGE_A_PATH = f"{STAGE_A_DIR}/master-table.jsonl"
STAGE1_PATH = "artifacts/chapter5-main60-analysis-v1/rq5-root-cause-index"
STORAGE_PATH = "artifacts/chapter5-main60-analysis-v1/rq5-storage-audit"
RETRIEVAL_PATH = "artifacts/chapter5-main60-analysis-v1/rq5-retrieval-audit"
RQ3_PATH = "artifacts/chapter5-main60-analysis-v1/rq3-dual-source-fusion"
DEFAULT_OUTPUT_DIR = "artifacts/chapter5-main60-analysis-v1/rq5-downstream-audit"
POST_DOWNSTREAM_STATE_BASENAME = "root-cause-state-register-after-downstream"
POST_DOWNSTREAM_STATE_PATH = f"{DEFAULT_OUTPUT_DIR}/{POST_DOWNSTREAM_STATE_BASENAME}.jsonl"

DEFAULT_REVIEW_PATHS = {
    "qwen": "docs/analysis/reviews/chapter5-rq5-qwen-downstream-review-v1.json",
    "deepseek": "docs/analysis/reviews/chapter5-rq5-deepseek-downstream-review-v1.json",
    "e7_mechanism": "docs/analysis/reviews/chapter5-rq5-e7-mechanism-review-v1.json",
    "e7_error": "docs/analysis/reviews/chapter5-rq5-e7-error-downstream-review-v1.json",
}

EXPECTED_UPSTREAM_AUDITS = {
    "stage1": "rq5-stage-1-audit-f1a9efe44c178464f8e04ae9eb224585df8f76a512d29dd48ab428579b61f7b6",
    "storage": "rq5-storage-audit-5ff8638baf55d3e678e266ade364aafd6076e0d89c1193aad05b59bda631f5eb",
    "retrieval": "rq5-retrieval-audit-1e2aacfe880ba84f21f22e6fee306533cde0c5e309d8211937e4af3de1b4925f",
    "rq3": "rq3-audit-e0ac8fc4a256b4fa5d016871163fc19243e99a9328985568b48b73ee35586378",
}
EXPECTED_UPSTREAM_FILE_SHA256 = {
    "stage1": {
        "audit": "be0f44924f397e367d2caca8df9d5446c6124a09ad3743bc7c7a4a7cc31ab338",
        "marker": "dd45b47bd7c390e49538f72631bcd4a64eca94b053d26c6f639e540be31ed160",
    },
    "storage": {
        "audit": "76b13e626457eaeaa1f4f18b2b348b911e1c733ca7ddce58cc845b1cf0b631e6",
        "marker": "8f94e4f2ac370efb0a24651463d5e4af102af29ba2179a9edb3ee04e30dd4b0f",
    },
    "retrieval": {
        "audit": "a234ea454ef069b334de83d81d65e9adcb13662b2494892c41a06f694e60d155",
        "marker": "c8a831d24bdd693ecb179b288ab517ae1199bb9f9fd482fec38ec10af41c5de9",
    },
    "rq3": {
        "audit": "af30f293bcfa10b9b31335294223dca0afe46be49d635904f382fc6f81d4bf31",
        "marker": "99806983faf9df0315a8c5b099415b34b994924d259a1a55bac33d0e75547ad9",
    },
}

EVIDENCE_STATES = {
    "complete_and_focused",
    "complete_but_noisy",
    "partial",
    "irrelevant_or_empty",
    "indeterminate",
}
SUFFICIENT_EVIDENCE_STATES = {"complete_and_focused", "complete_but_noisy"}
INSUFFICIENT_EVIDENCE_STATES = {"partial", "irrelevant_or_empty"}
SUFFICIENCY_STATES = {"sufficient", "insufficient", "indeterminate"}
PARENT_SUFFICIENCY_STATES = {
    "sufficient",
    "partially_sufficient",
    "insufficient",
    "indeterminate",
}
RETENTION_STATES = {"retained", "partially_retained", "lost", "budget_skipped", "indeterminate"}
PACKAGING_MECHANISMS = {
    "none",
    "note_omission",
    "conversion_loss",
    "provenance_rejection",
    "ordering_or_noise",
    "duplicate_suppression",
    "budget_skip",
    "relation_loss",
    "indeterminate",
}
ANSWERER_STATES = {
    "utilised_correctly",
    "misused_evidence",
    "unsupported_generation",
    "unsupported_abstention",
    "indeterminate",
}
ANSWERER_MECHANISMS = {
    "correct_use",
    "wrong_entity_or_attribute",
    "multi_hop_composition_failure",
    "entity_resolution_failure",
    "temporal_reasoning_failure",
    "state_or_event_type_confusion",
    "negation_or_polarity_error",
    "incomplete_list_or_attribute",
    "unsupported_inference",
    "excessive_caution",
    "conflict_reconciliation_failure",
    "indeterminate",
}
ANSWER_FORMS = {
    "adequate",
    "under_answering",
    "over_answering",
    "valid_paraphrase",
    "incorrect_qualifier",
    "reference_granularity_mismatch",
    "indeterminate",
}
ALTERNATIVE_EVIDENCE_STATES = {
    "not_needed",
    "present",
    "absent",
    "annotation_sensitive",
    "indeterminate",
}
CONFIDENCE_LEVELS = {"high", "medium", "low"}
FUSION_OPERATION_STATES = {"preserved", "repaired", "interfered", "no_effect", "indeterminate"}
FUSION_MECHANISMS = {
    "complementary_repair",
    "corroborative_reinforcement",
    "synthesis_without_parent_correctness",
    "redundant_fusion",
    "salience_dilution",
    "explicit_evidence_conflict",
    "synthesis_failure",
    "parent_sufficient_harm",
    "answer_recovery_without_demonstrated_fusion_cause",
    "no_effect",
    "indeterminate",
}

QWEN_REVIEW_TOP_FIELDS = {
    "protocol_version", "review_status", "scope", "review_passes", "guards",
    "codebooks", "source_provenance", "rows", "audit",
}
QWEN_REVIEW_ROW_FIELDS = {
    "review_order",
    "analysis_row_id",
    "case_id",
    "question_id",
    "condition_id",
    "backbone_id",
    "source_record_id",
    "evidence_bundle_id",
    "answer_id",
    "evidence_eligibility",
    "locator_coverage_state",
    "gold_annotation_scope",
    "content_state",
    "focus_state",
    "conflict_state",
    "relation_preservation_state",
    "alternative_support_state",
    "packaging_causal_state",
    "utilisation_state",
    "utilisation_subtype",
    "content_confidence",
    "packaging_confidence",
    "utilisation_confidence",
    "content_rationale",
    "packaging_rationale",
    "utilisation_rationale",
    "source_paths",
    "hashes",
}
DEEPSEEK_REVIEW_TOP_FIELDS = {
    "protocol_version", "schema_version", "review_scope", "review_passes",
    "packaging_causality_contract", "revision_history", "review_guards",
    "field_enums", "source_manifest", "rows", "audit",
}
DEEPSEEK_REVIEW_ROW_FIELDS = {
    "review_order", "case_id", "analysis_row_id", "backbone_id", "condition_id",
    "question_id", "category_name", "judge_label", "evidence_eligible",
    "evidence_any_hit", "evidence_all_hit", "evidence_recall",
    "evidence_item_count", "evidence_bundle_characters", "content_state",
    "focus_state", "conflict_state", "relation_preservation_state",
    "alternative_support_state", "packaging_causal_state", "utilisation_state",
    "utilisation_subtype", "confidence", "rationale", "identifiers_and_hashes",
    "source_paths_and_hashes", "content_state_answer_blind_revalidated",
    "retrieval_funnel_state", "packaging_review_note",
}

DEEPSEEK_FUNNEL_FIELDS = {
    "store_availability_state", "source_reach_state", "model_observation_state",
    "selection_state", "final_bundle_state", "complete_acquisition_state",
    "diagnostic_retrieval_state",
}
DEEPSEEK_PACKAGING_REVIEW_NOTES = {
    "No missing answer-bearing content is shown to have been acquired and then omitted; final insufficiency alone does not prove packaging loss.",
    "Semantically sufficient content survives; noise or ordering may contribute, but relevant-content loss is not demonstrated.",
    "The missing required content was not observed; this is non-acquisition rather than demonstrated packaging loss.",
    "Answer-bearing content was observed but not selected into the final EvidenceBundle.",
    "Answer-bearing content was observed and selected but did not fully survive into the final EvidenceBundle.",
    "Source-level ambiguity prevents a stable acquisition-to-bundle loss decision.",
}

FOCUS_STATES = {"focused", "moderately_noisy", "substantially_noisy", "not_assessable", "indeterminate"}
CONFLICT_STATES = {"none_detected", "competing_temporal_states", "entity_conflict", "source_reference_conflict", "other_conflict", "indeterminate"}
RELATION_STATES = {"preserved", "partially_preserved", "not_preserved", "not_required", "indeterminate"}
ALTERNATIVE_SUPPORT_STATES = {"present_in_final_input", "not_found_in_final_input", "not_needed", "indeterminate"}
PACKAGING_CAUSAL_STATES = {"demonstrated_relevant_loss", "possible_noise_or_ordering_contribution", "no_demonstrated_packaging_failure", "indeterminate"}
UTILISATION_REVIEW_STATES = {"failure_identified", "evaluation_sensitive_or_indeterminate", "not_assessable"}
UTILISATION_SUBTYPES = {
    "wrong_entity_or_attribute", "multi_hop_composition_failure",
    "entity_or_pronoun_resolution", "temporal_order_or_current_state",
    "plan_vs_completed_event", "negation_or_polarity",
    "incomplete_list_or_attribute", "unsupported_inference",
    "unsupported_abstention", "conflict_reconciliation_failure",
    "under_answering", "over_answering", "incorrect_qualifier",
    "reference_granularity_mismatch", "semantic_paraphrase_or_evaluation_sensitive",
    "source_reference_mismatch", "indeterminate", "not_assessable",
}

E7_ERROR_REVIEW_ROW_FIELDS = {
    "review_id",
    "case_id",
    "analysis_row_id",
    "backbone_id",
    "condition_id",
    "question_id",
    "question_sha256",
    "record_ids",
    "bundle_ids",
    "parent_evidence_states",
    "fused_evidence_state",
    "fusion_operation_state",
    "answerer_utilisation_state",
    "fusion_mechanism",
    "secondary_mechanisms",
    "confidence",
    "review_status",
    "manual_content_inspected",
}
E7_ERROR_REVIEW_TOP_FIELDS = {
    "protocol_version",
    "review_status",
    "review_unit",
    "guards",
    "cases",
}
E7_MECHANISM_REVIEW_TOP_FIELDS = {
    "protocol_version",
    "review_date",
    "review_status",
    "scope",
    "source_provenance",
    "review_inputs",
    "guards",
    "evidence_state_codebook",
    "primary_mechanism_codebook",
    "secondary_mechanism_codebook",
    "cases",
    "audit",
}
E7_MECHANISM_REVIEW_ROW_FIELDS = {
    "case_order",
    "review_id",
    "candidate_result_id",
    "backbone_id",
    "question_id",
    "question_sha256",
    "category_name",
    "outcome",
    "record_ids",
    "bundle_ids",
    "judge_labels",
    "evidence_eligible",
    "locator_evidence_recall",
    "parent_evidence_states",
    "fused_evidence_state",
    "primary_mechanism",
    "secondary_mechanisms",
    "confidence",
    "rationale",
}
E7_SECONDARY_MECHANISMS = {
    "ambiguity_amplification",
    "ambiguity_resolution",
    "competing_clause_selection",
    "evaluation_boundary_instability",
    "implicit_evidence_discounting",
    "omission_of_secondary_reference_detail",
    "question_premise_mismatch",
    "reference_under_specification",
    "specificity_relaxation",
    "synthesis_change",
    "temporal_inference_correction",
    "unsupported_extra_detail",
    "answer_verbosity",
}
E7_ERROR_FUSION_MECHANISMS = {
    "answerer_competing_clause_selection",
    "answerer_temporal_inference_failure",
    "answerer_temporal_location_selection_failure",
    "answerer_unsupported_abstention",
    "evaluation_sensitive_reference_granularity",
    "evaluation_sensitive_source_reference_mismatch",
    "evaluation_threshold_instability",
    "parent_retrieval_non_acquisition",
    "upstream_semantic_insufficiency",
}

OWNED_STATE_FIELDS = (
    "evidence_retention_state",
    "final_input_sufficiency_state",
    "answerer_utilisation_state",
    "parent_e2_bundle_state",
    "parent_e6_bundle_state",
    "fusion_operation_state",
)

TABLES = (
    "evidence-sufficiency",
    "packaging-loss",
    "answerer-conversion",
    "evidence-state-outcome-matrix",
    "e7-parent-sufficiency",
    "e7-parent-sufficiency-matrix",
    "e7-mechanisms",
    POST_DOWNSTREAM_STATE_BASENAME,
    "downstream-summary",
)

FORBIDDEN_OUTPUT_FIELDS = {
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
    "prompt",
    "response",
    "rationale",
    "reason",
    "short_reason",
    "judge_reason",
    "api_key",
    "authorization",
    "secret",
}
SECRET_FIELD_FRAGMENTS = ("password", "secret", "bearer", "api_key", "authorization")


def _artifact_id(prefix: str, body: Mapping[str, Any]) -> str:
    return prefix + sha256_bytes(canonical_json_bytes(dict(body)))


def _safe_repo_file(repo_root: Path, path: str | Path) -> Path:
    root = Path(repo_root).resolve()
    supplied = Path(path)
    if supplied.is_absolute():
        resolved = supplied.resolve()
        try:
            relative = resolved.relative_to(root)
        except ValueError as exc:
            raise ValueError(f"RQ5 downstream source escapes repository: {path}") from exc
        pure = PurePosixPath(relative.as_posix())
    else:
        pure = PurePosixPath(str(path))
        _require(pure.as_posix() == str(path), "RQ5 downstream path must be canonical")
    _require(not pure.is_absolute(), "RQ5 downstream path must be repository-relative")
    _require(all(part not in {"", ".", ".."} for part in pure.parts), "RQ5 downstream path is unsafe")
    cursor = root
    for part in pure.parts:
        cursor = cursor / part
        _require(not cursor.is_symlink(), f"RQ5 downstream source contains a symlink: {pure}")
    resolved = cursor.resolve()
    _require(resolved.is_file() and not resolved.is_symlink(), f"Missing or unsafe RQ5 downstream source: {pure}")
    return resolved


def _relative(repo_root: Path, path: Path) -> str:
    try:
        return path.resolve().relative_to(repo_root.resolve()).as_posix()
    except ValueError as exc:
        raise ValueError(f"RQ5 downstream source is outside repository: {path}") from exc


def _resolved_review_paths(
    repo_root: Path, review_paths: Mapping[str, str | Path] | None,
) -> dict[str, Path]:
    supplied = dict(DEFAULT_REVIEW_PATHS if review_paths is None else review_paths)
    _require(set(supplied) == set(DEFAULT_REVIEW_PATHS), "RQ5 downstream review path roles differ")
    return {role: _safe_repo_file(repo_root, value) for role, value in supplied.items()}


def _marker_binding(directory: Path, marker_name: str, role: str) -> dict[str, Any]:
    audit_path = directory / "audit.json"
    marker_path = directory / marker_name
    audit = _read_json(audit_path)
    marker = _read_json(marker_path)
    _require(audit.get("status") == "passed" and marker.get("status") == "passed", "Upstream RQ5 audit is not passed")
    _require(marker.get("audit_id") == audit.get("audit_id"), "Upstream RQ5 marker audit ID differs")
    _require(marker.get("audit_sha256") == _sha256_file(audit_path), "Upstream RQ5 marker hash differs")
    _require(_sha256_file(audit_path) == EXPECTED_UPSTREAM_FILE_SHA256[role]["audit"], f"Upstream {role} audit file hash differs")
    _require(_sha256_file(marker_path) == EXPECTED_UPSTREAM_FILE_SHA256[role]["marker"], f"Upstream {role} marker file hash differs")
    output_hashes = audit.get("output_sha256")
    _require(isinstance(output_hashes, Mapping) and output_hashes, f"Upstream {role} output hash register is missing")
    expected_names = set(output_hashes) | {"audit.json", marker_name}
    entries = list(directory.iterdir())
    _require(all(entry.is_file() and not entry.is_symlink() for entry in entries), f"Upstream {role} contains an unsafe entry")
    _require({entry.name for entry in entries} == expected_names, f"Upstream {role} file set differs")
    for name, digest in output_hashes.items():
        _require(_sha256_file(directory / name) == digest, f"Upstream {role} output hash differs: {name}")
    return {
        "audit_id": str(audit["audit_id"]),
        "audit_sha256": _sha256_file(audit_path),
        "marker_sha256": _sha256_file(marker_path),
    }


def _validate_upstream(repo_root: Path) -> dict[str, dict[str, Any]]:
    root = repo_root.resolve()
    stage_a = root / STAGE_A_DIR
    stage1 = root / STAGE1_PATH
    storage = root / STORAGE_PATH
    retrieval = root / RETRIEVAL_PATH
    rq3 = root / RQ3_PATH
    audited = {
        "stage1": audit_rq5_stage1_output(repo_root=root, stage_a_dir=stage_a, output_dir=stage1),
        "storage": audit_rq5_storage_output(repo_root=root, output_dir=storage),
        "retrieval": audit_rq5_retrieval_output(repo_root=root, output_dir=retrieval),
        "rq3": audit_rq3_output(repo_root=root, stage_a_dir=stage_a, output_dir=rq3),
    }
    markers = {
        "stage1": _marker_binding(stage1, "RQ5-STAGE-1.PASSED", "stage1"),
        "storage": _marker_binding(storage, "RQ5-STORAGE-AUDIT.PASSED", "storage"),
        "retrieval": _marker_binding(retrieval, "RQ5-RETRIEVAL-AUDIT.PASSED", "retrieval"),
        "rq3": _marker_binding(rq3, "RQ3.PASSED", "rq3"),
    }
    for role in EXPECTED_UPSTREAM_AUDITS:
        _require(audited[role]["status"] == "passed", f"Upstream {role} audit failed")
        _require(audited[role]["audit_id"] == EXPECTED_UPSTREAM_AUDITS[role], f"Upstream {role} audit identity differs")
        _require(markers[role]["audit_id"] == EXPECTED_UPSTREAM_AUDITS[role], f"Upstream {role} marker identity differs")
    return markers


def _stage_rows(repo_root: Path) -> tuple[list[dict[str, Any]], dict[tuple[str, str, str], dict[str, Any]]]:
    rows = [dict(row) for row in _read_jsonl(repo_root / STAGE_A_PATH)]
    selective = [row for row in rows if row.get("condition_id") in SELECTIVE_CONDITIONS]
    fused = [row for row in rows if row.get("condition_id") == FUSED_CONDITION]
    _require(len(selective) == EXPECTED_SELECTIVE_PATHS, "RQ5 downstream E1--E6 path count differs")
    _require(len(fused) == EXPECTED_FUSED_PATHS, "RQ5 downstream E7 path count differs")
    index = {(str(row["backbone_id"]), str(row["condition_id"]), str(row["question_id"])): row for row in (*selective, *fused)}
    _require(len(index) == EXPECTED_SELECTIVE_PATHS + EXPECTED_FUSED_PATHS, "RQ5 downstream Stage A keys repeat")
    _require(Counter((row["backbone_id"], row["condition_id"]) for row in selective) == Counter({(b, c): 60 for b in BACKBONES for c in SELECTIVE_CONDITIONS}), "RQ5 downstream selective design differs")
    _require(Counter(row["backbone_id"] for row in fused) == Counter({b: 60 for b in BACKBONES}), "RQ5 downstream E7 design differs")
    return rows, index


def _load_record(repo_root: Path, row: Mapping[str, Any]) -> RunRecord:
    source = _safe_repo_file(repo_root, str(row["source_record_path"]))
    _require(_sha256_file(source) == row["source_record_file_sha256"], "RQ5 downstream formal record hash differs")
    record = run_record_from_mapping(_read_json(source))
    _require(record.record_id == row["source_record_id"], "RQ5 downstream formal record ID differs")
    _require(record.question.sha256 == row["question_sha256"], "RQ5 downstream question hash differs")
    _require(record.evidence_bundle.bundle_id == row["evidence_bundle_id"], "RQ5 downstream bundle ID differs")
    _require(record.answer_result.evidence_bundle_id == record.evidence_bundle.bundle_id, "RQ5 downstream Answerer/bundle identity differs")
    return record


def _expected_sufficiency(evidence_state: str) -> str:
    if evidence_state in SUFFICIENT_EVIDENCE_STATES:
        return "sufficient"
    if evidence_state in INSUFFICIENT_EVIDENCE_STATES:
        return "insufficient"
    return "indeterminate"


def _parent_sufficiency(evidence_state: str) -> str:
    if evidence_state in SUFFICIENT_EVIDENCE_STATES:
        return "sufficient"
    if evidence_state == "partial":
        return "partially_sufficient"
    if evidence_state == "irrelevant_or_empty":
        return "insufficient"
    return "indeterminate"


def _require_path_hash(repo_root: Path, path: Any, digest: Any, label: str) -> Path:
    _require(isinstance(path, str) and isinstance(digest, str), f"{label} path/hash is invalid")
    resolved = _safe_repo_file(repo_root, path)
    _require(_sha256_file(resolved) == digest, f"{label} hash differs")
    return resolved


def _derived_retention(content_state: str, packaging_state: str) -> str:
    if packaging_state == "demonstrated_relevant_loss":
        return "lost" if content_state == "irrelevant_or_empty" else "partially_retained"
    if packaging_state == "indeterminate":
        return "indeterminate"
    return "retained"


def _derived_answerer_state(utilisation_state: str, utilisation_subtype: str) -> str:
    if utilisation_state != "failure_identified":
        return "indeterminate"
    if utilisation_subtype == "unsupported_abstention":
        return "unsupported_abstention"
    if utilisation_subtype == "unsupported_inference":
        return "unsupported_generation"
    return "misused_evidence"


def _derived_answer_form(utilisation_subtype: str) -> str:
    return {
        "under_answering": "under_answering",
        "over_answering": "over_answering",
        "semantic_paraphrase_or_evaluation_sensitive": "valid_paraphrase",
        "incorrect_qualifier": "incorrect_qualifier",
        "reference_granularity_mismatch": "reference_granularity_mismatch",
    }.get(utilisation_subtype, "indeterminate")


def _validate_review_codebooks(value: Any) -> None:
    _require(isinstance(value, Mapping), "Downstream-review codebooks are missing")
    expected = {
        "content_state": EVIDENCE_STATES,
        "focus_state": FOCUS_STATES,
        "conflict_state": CONFLICT_STATES,
        "relation_preservation_state": RELATION_STATES,
        "alternative_support_state": ALTERNATIVE_SUPPORT_STATES,
        "packaging_causal_state": PACKAGING_CAUSAL_STATES,
        "utilisation_state": UTILISATION_REVIEW_STATES,
        "utilisation_subtype": UTILISATION_SUBTYPES,
    }
    _require(set(value) >= set(expected), "Downstream-review codebook fields differ")
    for field, allowed in expected.items():
        _require(set(value[field]) == allowed, f"Downstream-review codebook differs: {field}")


def _validate_qwen_review_header(repo_root: Path, payload: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    _require(set(payload) == QWEN_REVIEW_TOP_FIELDS, "Qwen downstream-review top-level fields differ")
    _require(payload.get("protocol_version") == DOWNSTREAM_REVIEW_PROTOCOL_VERSIONS["qwen"], "Qwen downstream-review protocol differs")
    _require(payload.get("review_status") == "completed", "Qwen downstream review is incomplete")
    scope = payload.get("scope")
    _require(isinstance(scope, Mapping) and set(scope) == {"backbone_id", "conditions", "selection_rule", "expected_case_count", "actual_case_count"}, "Qwen downstream-review scope differs")
    _require(scope["backbone_id"] == "qwen" and scope["conditions"] == list(SELECTIVE_CONDITIONS), "Qwen downstream-review scope identity differs")
    _require(scope["selection_rule"] == "strict_score_zero" and scope["expected_case_count"] == 99 and scope["actual_case_count"] == 99, "Qwen downstream-review population differs")
    passes = payload.get("review_passes")
    _require(isinstance(passes, list) and len(passes) == 2, "Qwen downstream-review pass order differs")
    _require(passes[0].get("order") == 1 and passes[0].get("name") == "evidence_content_and_packaging" and passes[0].get("candidate_outcome_used") is False, "Qwen evidence review was not outcome-blind")
    _require(passes[1].get("order") == 2 and passes[1].get("name") == "answerer_utilisation" and passes[1].get("candidate_outcome_used") is True, "Qwen Answerer review gate differs")
    _validate_review_codebooks(payload.get("codebooks"))
    provenance = payload.get("source_provenance")
    _require(isinstance(provenance, list) and len(provenance) == 6, "Qwen downstream-review provenance differs")
    for binding in provenance:
        _require(isinstance(binding, Mapping) and set(binding) == {"role", "path", "sha256"}, "Qwen downstream-review provenance fields differ")
        _require_path_hash(repo_root, binding["path"], binding["sha256"], "Qwen downstream-review provenance")
    rows = payload.get("rows")
    _require(isinstance(rows, list) and len(rows) == 99, "Qwen downstream-review rows differ")
    audit = payload.get("audit")
    _require(isinstance(audit, Mapping) and audit.get("pass") is True and audit.get("unique_case_ids") == 99 and audit.get("unique_analysis_row_ids") == 99 and audit.get("raw_text_fields_absent") is True, "Qwen downstream-review audit differs")
    return rows


def _validate_deepseek_review_header(repo_root: Path, payload: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    _require(set(payload) == DEEPSEEK_REVIEW_TOP_FIELDS, "DeepSeek downstream-review top-level fields differ")
    _require(payload.get("schema_version") == 2 and payload.get("protocol_version") == DOWNSTREAM_REVIEW_PROTOCOL_VERSIONS["deepseek"], "DeepSeek downstream-review protocol differs")
    scope = payload.get("review_scope")
    _require(isinstance(scope, Mapping) and scope.get("backbone_id") == "deepseek" and scope.get("conditions") == list(SELECTIVE_CONDITIONS) and scope.get("row_count") == 106, "DeepSeek downstream-review scope differs")
    passes = payload.get("review_passes")
    _require(isinstance(passes, list) and len(passes) == 2, "DeepSeek downstream-review pass order differs")
    _require(
        passes[0].get("order") == 1
        and passes[0].get("name") == "answer_blind_evidence_content_and_packaging"
        and passes[0].get("candidate_answer_or_judge_outcome_used") is False,
        "DeepSeek evidence and packaging review was not answer-blind",
    )
    _require(
        passes[1].get("order") == 2
        and passes[1].get("name") == "answerer_utilisation"
        and passes[1].get("candidate_answer_or_judge_outcome_used") is True
        and passes[1].get("gate") == "content_state in {complete_and_focused, complete_but_noisy}",
        "DeepSeek Answerer review gate differs",
    )
    packaging_contract = payload.get("packaging_causality_contract")
    _require(
        isinstance(packaging_contract, Mapping)
        and set(packaging_contract)
        == {
            "demonstrated_relevant_loss",
            "possible_noise_or_ordering_contribution",
            "no_demonstrated_packaging_failure",
            "indeterminate",
            "retrieval_non_acquisition_rule",
            "partial_acquisition_rule",
        }
        and all(isinstance(value, str) and value for value in packaging_contract.values()),
        "DeepSeek packaging-causality contract differs",
    )
    revision = payload.get("revision_history")
    _require(
        isinstance(revision, Mapping)
        and set(revision)
        == {
            "revision_reason", "prior_artifact_sha256",
            "content_state_revalidation_count", "content_state_change_count",
            "utilisation_label_change_count", "packaging_label_change_count",
        }
        and revision.get("content_state_revalidation_count") == 106
        and revision.get("content_state_change_count") == 0
        and revision.get("utilisation_label_change_count") == 0
        and revision.get("packaging_label_change_count") == 28,
        "DeepSeek downstream-review revision record differs",
    )
    _validate_review_codebooks(payload.get("field_enums"))
    manifest = payload.get("source_manifest")
    _require(isinstance(manifest, Mapping), "DeepSeek downstream-review source manifest is missing")
    for role in ("strict_error_index", "retrieval_linkage", "storage_review", "judge_run_results"):
        binding = manifest.get(role)
        _require(isinstance(binding, Mapping) and set(binding) == {"path", "sha256"}, f"DeepSeek review source binding differs: {role}")
        _require_path_hash(repo_root, binding["path"], binding["sha256"], f"DeepSeek review source: {role}")
    gold = manifest.get("gold_files")
    _require(isinstance(gold, list) and len(gold) == 2, "DeepSeek review gold bindings differ")
    for binding in gold:
        _require(isinstance(binding, Mapping) and set(binding) == {"path", "sha256"}, "DeepSeek review gold binding fields differ")
        _require_path_hash(repo_root, binding["path"], binding["sha256"], "DeepSeek review gold source")
    _require(manifest.get("unique_answer_record_count") == 106 and manifest.get("unique_judge_record_count") == 106, "DeepSeek review source census differs")
    rows = payload.get("rows")
    _require(isinstance(rows, list) and len(rows) == 106, "DeepSeek downstream-review rows differ")
    audit = payload.get("audit")
    _require(isinstance(audit, Mapping) and audit.get("status") == "passed" and audit.get("expected_row_count") == 106 and audit.get("actual_row_count") == 106 and audit.get("sufficiency_utilisation_invariant") is True and audit.get("raw_content_fields_absent") is True, "DeepSeek downstream-review audit differs")
    revalidation = audit.get("answer_blind_content_revalidation")
    harmonisation = audit.get("packaging_harmonisation")
    _require(
        isinstance(revalidation, Mapping)
        and revalidation.get("row_count") == 106
        and revalidation.get("content_state_change_count") == 0
        and revalidation.get("pass_1_frozen_before_candidate_review") is True,
        "DeepSeek answer-blind revalidation audit differs",
    )
    _require(
        isinstance(harmonisation, Mapping)
        and harmonisation.get("changed_row_count") == 28
        and harmonisation.get("revised_counts")
        == {
            "demonstrated_relevant_loss": 7,
            "indeterminate": 2,
            "no_demonstrated_packaging_failure": 72,
            "possible_noise_or_ordering_contribution": 25,
        },
        "DeepSeek packaging-harmonisation audit differs",
    )
    return rows


def _validate_downstream_review_payload(
    *, repo_root: Path, path: Path, backbone: str,
    stage_index: Mapping[tuple[str, str, str], Mapping[str, Any]],
    record_index: Mapping[str, RunRecord],
    strict_errors: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    payload = _read_json(path)
    rows = (
        _validate_qwen_review_header(repo_root, payload)
        if backbone == "qwen"
        else _validate_deepseek_review_header(repo_root, payload)
    )
    expected = {
        (str(row["packet_backbone"]), str(row["condition_id"]), str(row["question_id"])): row
        for row in strict_errors
        if row["packet_backbone"] == backbone and row["condition_id"] in SELECTIVE_CONDITIONS
    }
    _require(len(expected) == EXPECTED_SELECTIVE_ERRORS_BY_BACKBONE[backbone], "Downstream-review frozen error population differs")
    observed: set[tuple[str, str, str]] = set()
    output: list[dict[str, Any]] = []
    for ordinal, supplied in enumerate(rows, 1):
        required_fields = QWEN_REVIEW_ROW_FIELDS if backbone == "qwen" else DEEPSEEK_REVIEW_ROW_FIELDS
        _require(isinstance(supplied, Mapping) and set(supplied) == required_fields, f"{backbone} downstream-review row fields differ")
        key = (str(supplied["backbone_id"]), str(supplied["condition_id"]), str(supplied["question_id"]))
        _require(key in expected and key not in observed, "Downstream-review identity is missing, repeated, or unexpected")
        _require(supplied["review_order"] == ordinal, "Downstream-review order differs")
        observed.add(key)
        error = expected[key]
        source = stage_index[key]
        _require(supplied["case_id"] == error["case_id"] and supplied["analysis_row_id"] == source["analysis_row_id"], "Downstream-review case identity differs")
        record = record_index[str(source["analysis_row_id"])]
        bundle = record.evidence_bundle
        _require(isinstance(bundle, EvidenceBundle) and bundle.budget.truncated is False, "Downstream review references an invalid E1--E6 bundle")

        if backbone == "qwen":
            _require(supplied["source_record_id"] == source["source_record_id"] and supplied["evidence_bundle_id"] == source["evidence_bundle_id"] and supplied["answer_id"] == record.answer_result.answer_id, "Qwen downstream-review record identity differs")
            _require(supplied["evidence_eligibility"] == ("eligible" if source["evidence_eligible"] else "ineligible"), "Qwen review eligibility differs")
            expected_locator = "not_annotated" if not source["evidence_eligible"] else "all_hit" if source["evidence_all_hit"] else "partial_hit" if source["evidence_any_hit"] else "no_hit"
            _require(supplied["locator_coverage_state"] == expected_locator and supplied["gold_annotation_scope"] == "diagnostic_non_exhaustive", "Qwen review locator state differs")
            hashes = supplied["hashes"]
            source_paths = supplied["source_paths"]
            _require(isinstance(hashes, Mapping) and set(hashes) == {"question_sha256", "source_record_file_sha256", "source_record_payload_sha256", "evidence_payload_sha256", "answer_prompt_sha256", "answer_evidence_input_sha256"}, "Qwen review hash fields differ")
            _require(isinstance(source_paths, Mapping) and set(source_paths) == {"frozen_source_record", "gold_record_file", "canonical_conversation", "retrieval_linkage"}, "Qwen review source-path fields differ")
            _require(source_paths["frozen_source_record"] == source["source_record_path"], "Qwen review source-record path differs")
            _require_path_hash(repo_root, source_paths["frozen_source_record"], hashes["source_record_file_sha256"], "Qwen review answer record")
            _require(hashes["source_record_file_sha256"] == source["source_record_file_sha256"], "Qwen review source-record file hash differs")
            _require(hashes["question_sha256"] == source["question_sha256"] and hashes["source_record_payload_sha256"] == source["source_record_payload_sha256"], "Qwen review source hashes differ")
            _require(hashes["evidence_payload_sha256"] == record.evidence_payload_sha256 and hashes["answer_prompt_sha256"] == record.answer_result.prompt_sha256 and hashes["answer_evidence_input_sha256"] == record.answer_result.evidence_input_sha256, "Qwen review Answerer hashes differ")
            alternative = str(supplied["alternative_support_state"])
            content_confidence = str(supplied["content_confidence"])
            packaging_confidence = str(supplied["packaging_confidence"])
            utilisation_confidence = str(supplied["utilisation_confidence"])
        else:
            _require(supplied["category_name"] == source["category_name"] and supplied["judge_label"] == source["judge_label"], "DeepSeek review outcome identity differs")
            for field in ("evidence_eligible", "evidence_any_hit", "evidence_all_hit", "evidence_recall", "evidence_item_count", "evidence_bundle_characters"):
                _require(supplied[field] == source[field], f"DeepSeek review Stage A field differs: {field}")
            identities = supplied["identifiers_and_hashes"]
            paths = supplied["source_paths_and_hashes"]
            _require(isinstance(identities, Mapping) and set(identities) == {"question_sha256", "reference_answer_sha256", "candidate_answer_sha256", "evidence_bundle_id", "evidence_payload_sha256", "source_record_id", "source_record_payload_sha256", "judgment_id"}, "DeepSeek review identity/hash fields differ")
            _require(isinstance(paths, Mapping) and set(paths) == {"answer_record_path", "answer_record_file_sha256", "judge_record_path", "judge_record_file_sha256", "gold_file_path", "gold_file_sha256"}, "DeepSeek review source-path/hash fields differ")
            _require(paths["answer_record_path"] == source["source_record_path"] and identities["source_record_id"] == source["source_record_id"] and identities["evidence_bundle_id"] == source["evidence_bundle_id"], "DeepSeek review source identity differs")
            _require_path_hash(repo_root, paths["answer_record_path"], paths["answer_record_file_sha256"], "DeepSeek review answer record")
            _require(paths["answer_record_file_sha256"] == source["source_record_file_sha256"], "DeepSeek review answer-record file hash differs")
            judge_path = _require_path_hash(repo_root, paths["judge_record_path"], paths["judge_record_file_sha256"], "DeepSeek review Judge record")
            _require_path_hash(repo_root, paths["gold_file_path"], paths["gold_file_sha256"], "DeepSeek review gold file")
            judge = _read_json(judge_path)
            _require(judge.get("judgment_id") == identities["judgment_id"] and judge.get("label") == source["judge_label"] and judge.get("source_record_id") == source["source_record_id"], "DeepSeek review Judge identity differs")
            _require(judge.get("question_sha256") == identities["question_sha256"] and judge.get("reference_answer_sha256") == identities["reference_answer_sha256"] and judge.get("candidate_answer_sha256") == identities["candidate_answer_sha256"], "DeepSeek review Judge hashes differ")
            _require(identities["question_sha256"] == source["question_sha256"] and identities["source_record_payload_sha256"] == source["source_record_payload_sha256"] and identities["evidence_payload_sha256"] == record.evidence_payload_sha256, "DeepSeek review source hashes differ")
            _require(identities["candidate_answer_sha256"] == sha256_bytes(record.answer_result.answer.encode("utf-8")), "DeepSeek review candidate-answer hash differs")
            _require(supplied["content_state_answer_blind_revalidated"] is True, "DeepSeek content state was not answer-blind revalidated")
            funnel = supplied["retrieval_funnel_state"]
            _require(isinstance(funnel, Mapping) and set(funnel) == DEEPSEEK_FUNNEL_FIELDS, "DeepSeek retrieval-funnel state differs")
            _require(
                all(isinstance(funnel[field], str) and funnel[field] for field in DEEPSEEK_FUNNEL_FIELDS),
                "DeepSeek retrieval-funnel state is incomplete",
            )
            _require(supplied["packaging_review_note"] in DEEPSEEK_PACKAGING_REVIEW_NOTES, "DeepSeek packaging review note differs")
            alternative = str(supplied["alternative_support_state"])
            content_confidence = packaging_confidence = utilisation_confidence = str(supplied["confidence"])

        content = str(supplied["content_state"])
        focus = str(supplied["focus_state"])
        conflict = str(supplied["conflict_state"])
        relation = str(supplied["relation_preservation_state"])
        packaging = str(supplied["packaging_causal_state"])
        utilisation_review = str(supplied["utilisation_state"])
        subtype = str(supplied["utilisation_subtype"])
        _require(content in EVIDENCE_STATES and focus in FOCUS_STATES and conflict in CONFLICT_STATES and relation in RELATION_STATES, "Downstream-review evidence taxonomy differs")
        _require(alternative in ALTERNATIVE_SUPPORT_STATES and packaging in PACKAGING_CAUSAL_STATES, "Downstream-review packaging taxonomy differs")
        _require(utilisation_review in UTILISATION_REVIEW_STATES and subtype in UTILISATION_SUBTYPES, "Downstream-review utilisation taxonomy differs")
        _require(content_confidence in CONFIDENCE_LEVELS and packaging_confidence in CONFIDENCE_LEVELS and utilisation_confidence in (CONFIDENCE_LEVELS | {"not_applicable"}), "Downstream-review confidence differs")
        sufficient = _expected_sufficiency(content) == "sufficient"
        _require(sufficient or (utilisation_review == "not_assessable" and subtype == "not_assessable"), "Answerer utilisation was assigned before sufficiency passed")
        _require((utilisation_review == "not_assessable") == (subtype == "not_assessable"), "Downstream-review utilisation gate is inconsistent")

        normalized = {
            "review_id": str(supplied["case_id"]),
            "case_id": str(supplied["case_id"]),
            "analysis_row_id": str(supplied["analysis_row_id"]),
            "source_record_id": str(source["source_record_id"]),
            "evidence_bundle_id": str(source["evidence_bundle_id"]),
            "question_id": key[2],
            "question_sha256": str(source["question_sha256"]),
            "backbone_id": backbone,
            "condition_id": key[1],
            "evidence_state": content,
            "focus_state": focus,
            "conflict_state": conflict,
            "relation_preservation_state": relation,
            "alternative_support_state": alternative,
            "packaging_causal_state": packaging,
            "evidence_retention_state": _derived_retention(content, packaging),
            "final_input_sufficiency_state": _expected_sufficiency(content),
            "utilisation_review_state": utilisation_review,
            "utilisation_subtype": subtype,
            "answerer_utilisation_state": _derived_answerer_state(utilisation_review, subtype),
            "answer_form": _derived_answer_form(subtype),
            "content_confidence": content_confidence,
            "packaging_confidence": packaging_confidence,
            "utilisation_confidence": utilisation_confidence,
        }
        output.append(normalized)
    _require(observed == set(expected), "Downstream review does not cover exactly the frozen E1--E6 Strict errors")
    output.sort(key=lambda row: int(expected[(backbone, str(row["condition_id"]), str(row["question_id"]))]["error_order"]))
    return output


def _validate_review_provenance(repo_root: Path, payload: Mapping[str, Any]) -> None:
    bindings = payload.get("source_provenance")
    _require(isinstance(bindings, list) and bindings, "E7 mechanism review provenance is missing")
    seen: set[str] = set()
    for binding in bindings:
        _require(isinstance(binding, Mapping) and set(binding) >= {"path", "sha256"}, "Invalid E7 mechanism provenance row")
        relative = str(binding["path"])
        _require(relative not in seen, "E7 mechanism provenance repeats a source")
        seen.add(relative)
        _require(_sha256_file(_safe_repo_file(repo_root, relative)) == binding["sha256"], "E7 mechanism provenance hash differs")


def _load_e7_mechanism_review(
    *, repo_root: Path, path: Path,
    stage_index: Mapping[tuple[str, str, str], Mapping[str, Any]],
    record_index: Mapping[str, RunRecord],
    downstream_by_key: Mapping[tuple[str, str, str], Mapping[str, Any]],
) -> dict[tuple[str, str], dict[str, Any]]:
    payload = _read_json(path)
    _require(set(payload) == E7_MECHANISM_REVIEW_TOP_FIELDS, "E7 mechanism-review top-level fields differ")
    _require(payload.get("protocol_version") == E7_MECHANISM_REVIEW_PROTOCOL_VERSION, "E7 mechanism-review protocol differs")
    _require(payload.get("review_status") == "completed", "E7 mechanism review is incomplete")
    scope = payload.get("scope")
    _require(
        isinstance(scope, Mapping)
        and scope.get("unit") == "backbone_id x question_id"
        and scope.get("included_outcomes") == ["repair", "harm"]
        and scope.get("row_count") == EXPECTED_MECHANISM_CANDIDATES
        and scope.get("repair_count") == 4
        and scope.get("harm_count") == 8,
        "E7 mechanism-review scope differs",
    )
    _require(
        isinstance(payload.get("evidence_state_codebook"), Mapping)
        and set(payload["evidence_state_codebook"]) == EVIDENCE_STATES,
        "E7 mechanism-review evidence codebook differs",
    )
    _require(
        isinstance(payload.get("primary_mechanism_codebook"), Mapping)
        and set(payload["primary_mechanism_codebook"]) <= FUSION_MECHANISMS
        and set(payload["primary_mechanism_codebook"]),
        "E7 mechanism-review primary-mechanism codebook differs",
    )
    _require(
        isinstance(payload.get("secondary_mechanism_codebook"), list)
        and set(payload["secondary_mechanism_codebook"]) == E7_SECONDARY_MECHANISMS
        and len(payload["secondary_mechanism_codebook"]) == len(E7_SECONDARY_MECHANISMS),
        "E7 mechanism-review secondary-mechanism codebook differs",
    )
    guards = payload.get("guards")
    _require(isinstance(guards, Mapping) and guards.get("e7_has_no_new_retrieval") is True and guards.get("e7_has_no_observed_post_fusion_item_loss_or_budget_truncation") is True and guards.get("no_new_model_calls") is True and guards.get("no_source_mutation") is True, "E7 mechanism-review guards differ")
    _validate_review_provenance(repo_root, payload)
    candidates = _read_jsonl(repo_root / RQ3_PATH / "rq5-candidate-cases.jsonl")
    candidate_index = {(str(row["backbone_id"]), str(row["question_id"])): row for row in candidates}
    _require(len(candidate_index) == EXPECTED_MECHANISM_CANDIDATES, "RQ3 candidate identity count differs")
    cases = payload.get("cases")
    _require(isinstance(cases, list) and len(cases) == EXPECTED_MECHANISM_CANDIDATES, "E7 mechanism-review case count differs")
    output: dict[tuple[str, str], dict[str, Any]] = {}
    for ordinal, case in enumerate(cases, 1):
        _require(isinstance(case, Mapping) and set(case) == E7_MECHANISM_REVIEW_ROW_FIELDS, "Invalid E7 mechanism-review case")
        key = (str(case.get("backbone_id")), str(case.get("question_id")))
        _require(key in candidate_index and key not in output, "E7 mechanism-review identity differs")
        _require(case.get("case_order") == ordinal and case.get("review_id") == f"e7-review-{key[0]}-{key[1]}", "E7 mechanism-review order or ID differs")
        candidate = candidate_index[key]
        e2 = stage_index[(key[0], "E2", key[1])]
        e6 = stage_index[(key[0], "E6", key[1])]
        e7 = stage_index[(key[0], "E7", key[1])]
        _require(case.get("candidate_result_id") == candidate["result_id"], "E7 mechanism candidate ID differs")
        _require(case.get("question_sha256") == e7["question_sha256"] and case.get("category_name") == e7["category_name"], "E7 mechanism question identity differs")
        _require(case.get("outcome") == candidate["fusion_outcome"], "E7 mechanism outcome differs")
        _require(case.get("record_ids") == {"E2": e2["source_record_id"], "E6": e6["source_record_id"], "E7": e7["source_record_id"]}, "E7 mechanism record identities differ")
        _require(case.get("bundle_ids") == {"E2": e2["evidence_bundle_id"], "E6": e6["evidence_bundle_id"], "E7": e7["evidence_bundle_id"]}, "E7 mechanism bundle identities differ")
        _require(case.get("judge_labels") == {"E2": e2["judge_label"], "E6": e6["judge_label"], "E7": e7["judge_label"]}, "E7 mechanism Judge labels differ")
        _require(case.get("evidence_eligible") == e7["evidence_eligible"], "E7 mechanism evidence eligibility differs")
        recalls = case.get("locator_evidence_recall")
        expected_recalls = {"E2": e2["evidence_recall"], "E6": e6["evidence_recall"], "E7": e7["evidence_recall"]}
        _require(isinstance(recalls, Mapping) and all((recalls[k] is None and expected_recalls[k] is None) or math.isclose(float(recalls[k]), float(expected_recalls[k]), rel_tol=0.0, abs_tol=1e-12) for k in expected_recalls), "E7 mechanism Evidence Recall differs")
        parent_states = case.get("parent_evidence_states")
        fused_state = case.get("fused_evidence_state")
        mechanism = case.get("primary_mechanism")
        _require(isinstance(parent_states, Mapping) and set(parent_states) == {"E2", "E6"} and set(parent_states.values()) <= EVIDENCE_STATES, "E7 mechanism parent evidence states differ")
        _require(fused_state in EVIDENCE_STATES, "E7 mechanism fused evidence state differs")
        _require(mechanism in FUSION_MECHANISMS, "E7 mechanism taxonomy differs")
        secondary = case.get("secondary_mechanisms")
        _require(
            isinstance(secondary, list)
            and len(secondary) == len(set(secondary))
            and set(secondary) <= E7_SECONDARY_MECHANISMS,
            "E7 mechanism secondary taxonomy differs",
        )
        _require(case.get("confidence") in CONFIDENCE_LEVELS, "E7 mechanism confidence differs")
        normalized = dict(case)
        normalized["gated_parent_state_consistent"] = all(
            downstream_by_key.get((key[0], condition, key[1])) is None
            or parent_states[condition]
            == downstream_by_key[(key[0], condition, key[1])]["evidence_state"]
            for condition in ("E2", "E6")
        )
        output[key] = normalized
    _require(set(output) == set(candidate_index), "E7 mechanism review substitutes or omits an RQ3 candidate")
    audit = payload.get("audit")
    _require(
        isinstance(audit, Mapping)
        and audit.get("audit_status") == "passed"
        and audit.get("row_count") == EXPECTED_MECHANISM_CANDIDATES
        and audit.get("outcome_counts") == {"repair": 4, "harm": 8}
        and audit.get("all_boundary_candidates_accounted_for") is True
        and audit.get("question_answer_and_evidence_text_embedded") is False
        and audit.get("causal_claims_made") is False,
        "E7 mechanism-review audit differs",
    )
    return output


def _load_e7_error_review(
    *, path: Path, errors: Sequence[Mapping[str, Any]],
    stage_index: Mapping[tuple[str, str, str], Mapping[str, Any]],
    downstream_by_key: Mapping[tuple[str, str, str], Mapping[str, Any]],
    mechanism_by_key: Mapping[tuple[str, str], Mapping[str, Any]],
) -> dict[tuple[str, str], dict[str, Any]]:
    payload = _read_json(path)
    _require(set(payload) == E7_ERROR_REVIEW_TOP_FIELDS, "E7 error-review top-level fields differ")
    _require(payload.get("protocol_version") == E7_ERROR_REVIEW_PROTOCOL_VERSION, "E7 error-review protocol differs")
    _require(payload.get("review_status") == "completed", "E7 error review is incomplete")
    review_unit = payload.get("review_unit")
    enriched_review = isinstance(review_unit, Mapping)
    review_details: Mapping[str, Any] = {}
    error_mechanism_codebook = E7_ERROR_FUSION_MECHANISMS
    if enriched_review:
        _require(
            set(review_unit)
            == {
                "unit", "scope_counts", "selection_rule", "two_pass_contract",
                "source_manifest", "codebooks", "case_details", "audit",
            },
            "E7 enriched error-review unit fields differ",
        )
        _require(
            review_unit.get("unit") == "backbone_id x question_id for every E7 Strict-noncorrect path",
            "E7 enriched error-review unit differs",
        )
        _require(
            review_unit.get("scope_counts")
            == {"total": 31, "harm": 8, "unresolved": 23, "qwen": 16, "deepseek": 15},
            "E7 enriched error-review scope differs",
        )
        passes = review_unit.get("two_pass_contract")
        _require(isinstance(passes, list) and len(passes) == 2, "E7 enriched error-review pass order differs")
        _require(
            passes[0].get("order") == 1
            and passes[0].get("name") == "fused_content_and_operation"
            and passes[0].get("candidate_or_judge_outcome_used") is False,
            "E7 fused-content review was not answer-blind",
        )
        _require(
            passes[1].get("order") == 2
            and passes[1].get("name") == "answerer_utilisation"
            and passes[1].get("candidate_or_judge_outcome_used") is True
            and passes[1].get("gate") == "fused_evidence_state in {complete_and_focused, complete_but_noisy}",
            "E7 Answerer review gate differs",
        )
        bindings = review_unit.get("source_manifest")
        _require(isinstance(bindings, list) and len(bindings) == 9, "E7 enriched error-review provenance differs")
        for binding in bindings:
            _require(isinstance(binding, Mapping) and set(binding) == {"role", "path", "sha256"}, "E7 enriched provenance fields differ")
            _require_path_hash(path.parents[3], binding["path"], binding["sha256"], "E7 enriched review provenance")
        codebooks = review_unit.get("codebooks")
        _require(isinstance(codebooks, Mapping), "E7 enriched review codebooks are missing")
        _require(set(codebooks.get("evidence_state", [])) == EVIDENCE_STATES, "E7 enriched evidence-state codebook differs")
        _require(set(codebooks.get("answerer_utilisation_state", [])) == ANSWERER_STATES, "E7 enriched Answerer codebook differs")
        _require(codebooks.get("fusion_operation_state") == ["all_parent_items_preserved_no_deduplication"], "E7 enriched structural-fusion codebook differs")
        error_mechanism_codebook = set(codebooks.get("fusion_mechanism", []))
        _require(error_mechanism_codebook == E7_ERROR_FUSION_MECHANISMS, "E7 enriched mechanism codebook differs")
        review_details = review_unit.get("case_details")
        _require(isinstance(review_details, Mapping) and len(review_details) == EXPECTED_FUSED_ERRORS, "E7 enriched case details differ")
        review_audit = review_unit.get("audit")
        _require(
            isinstance(review_audit, Mapping)
            and review_audit.get("case_count") == EXPECTED_FUSED_ERRORS
            and review_audit.get("observed_outcome_counts") == {"harm": 8, "unresolved": 23}
            and review_audit.get("manual_content_inspected_count") == EXPECTED_FUSED_ERRORS
            and review_audit.get("every_parent_item_survives_fusion_count") == EXPECTED_FUSED_ERRORS
            and review_audit.get("schema_and_denominator_checks_passed") is True,
            "E7 enriched error-review audit differs",
        )
    else:
        _require(review_unit == "backbone_id x E7 strict-noncorrect question", "E7 error-review unit differs")
    guards = payload.get("guards")
    if enriched_review:
        required_guard_names = {
            "no_new_model_calls", "no_source_mutation",
            "no_raw_question_reference_candidate_or_evidence_text",
            "evidence_content_was_classified_before_candidate_or_judge_outcome",
            "locator_all_hit_is_not_semantic_sufficiency",
            "gold_locator_set_is_not_assumed_exhaustive",
            "unresolved_is_not_automatically_answerer_failure",
            "answerer_attribution_requires_semantically_sufficient_fused_input",
            "fusion_outcome_is_observational_not_causal",
            "all_harm_boundary_rows_cross_checked_against_existing_boundary_review",
            "ambiguity_preserved_as_indeterminate",
        }
        _require(
            isinstance(guards, Mapping)
            and set(guards) == required_guard_names
            and all(guards.get(name) is True for name in required_guard_names),
            "E7 enriched error-review guards differ",
        )
    else:
        required_guards = {
            "strict_noncorrect_cases_only": True,
            "parent_sufficiency_precedes_fusion_review": True,
            "exact_fusion_verified_separately": True,
            "answerer_assessed_only_after_sufficiency": True,
            "no_new_model_calls": True,
            "no_source_mutation": True,
        }
        _require(isinstance(guards, Mapping) and set(guards) == set(required_guards) and all(guards.get(k) is v for k, v in required_guards.items()), "E7 error-review guards differ")
    ordered_expected = [row for row in errors if row["condition_id"] == FUSED_CONDITION]
    expected = {(str(row["packet_backbone"]), str(row["question_id"])): row for row in ordered_expected}
    _require(len(expected) == EXPECTED_FUSED_ERRORS, "Frozen E7 error count differs")
    cases = payload.get("cases")
    _require(isinstance(cases, list) and len(cases) == EXPECTED_FUSED_ERRORS, "E7 error-review case count differs")
    output: dict[tuple[str, str], dict[str, Any]] = {}
    for ordinal, supplied in enumerate(cases):
        _require(isinstance(supplied, Mapping) and set(supplied) == E7_ERROR_REVIEW_ROW_FIELDS, "E7 error-review row fields differ")
        key = (str(supplied["backbone_id"]), str(supplied["question_id"]))
        _require(key in expected and key not in output, "E7 error-review identity differs")
        expected_at_ordinal = ordered_expected[ordinal]
        _require(key == (str(expected_at_ordinal["packet_backbone"]), str(expected_at_ordinal["question_id"])), "E7 error-review order differs")
        error = expected[key]
        e2 = stage_index[(key[0], "E2", key[1])]
        e6 = stage_index[(key[0], "E6", key[1])]
        e7 = stage_index[(key[0], "E7", key[1])]
        _require(supplied["review_id"] == f"e7-error-review-{key[0]}-{key[1]}", "E7 error-review ID differs")
        _require(supplied["case_id"] == error["case_id"] and supplied["analysis_row_id"] == e7["analysis_row_id"], "E7 error-review case identity differs")
        _require(supplied["condition_id"] == "E7" and supplied["question_sha256"] == e7["question_sha256"], "E7 error-review question identity differs")
        _require(supplied["record_ids"] == {"E2": e2["source_record_id"], "E6": e6["source_record_id"], "E7": e7["source_record_id"]}, "E7 error-review record identities differ")
        _require(supplied["bundle_ids"] == {"E2": e2["evidence_bundle_id"], "E6": e6["evidence_bundle_id"], "E7": e7["evidence_bundle_id"]}, "E7 error-review bundle identities differ")
        parent = supplied["parent_evidence_states"]
        _require(isinstance(parent, Mapping) and set(parent) == {"E2", "E6"} and set(parent.values()) <= EVIDENCE_STATES, "E7 error-review parent states differ")
        for condition in ("E2", "E6"):
            reviewed_parent = downstream_by_key.get((key[0], condition, key[1]))
            if reviewed_parent is not None:
                if not enriched_review:
                    _require(parent[condition] == reviewed_parent["evidence_state"], "E7 error-review parent state differs from gated E2/E6 review")
        fused_state = str(supplied["fused_evidence_state"])
        supplied_operation = str(supplied["fusion_operation_state"])
        utilisation = str(supplied["answerer_utilisation_state"])
        mechanism = str(supplied["fusion_mechanism"])
        _require(fused_state in EVIDENCE_STATES, "E7 error-review fused-evidence state differs")
        if enriched_review:
            _require(supplied_operation == "all_parent_items_preserved_no_deduplication", "E7 structural-fusion state differs")
            details = review_details.get(str(supplied["review_id"]))
            _require(isinstance(details, Mapping), "E7 enriched case detail is missing")
            observed_outcome = details.get("observed_rq3_outcome")
            _require(observed_outcome in {"harm", "unresolved"}, "E7 enriched observed outcome differs")
            operation = "interfered" if observed_outcome == "harm" else "no_effect"
        else:
            _require(supplied_operation in FUSION_OPERATION_STATES, "E7 error-review fusion-operation state differs")
            operation = supplied_operation
        _require(utilisation in ANSWERER_STATES and mechanism in (FUSION_MECHANISMS | error_mechanism_codebook), "E7 error-review utilisation/mechanism differs")
        secondary = supplied["secondary_mechanisms"]
        if enriched_review:
            _require(
                isinstance(secondary, list)
                and len(secondary) == len(set(secondary))
                and all(isinstance(value, str) and len(value) <= 80 and re.fullmatch(r"[a-z0-9_]+", value) for value in secondary),
                "E7 enriched secondary mechanisms differ",
            )
        else:
            _require(
                isinstance(secondary, list)
                and secondary == sorted(set(secondary))
                and set(secondary) <= E7_SECONDARY_MECHANISMS,
                "E7 error-review secondary mechanisms differ",
            )
        _require(supplied["confidence"] in CONFIDENCE_LEVELS and supplied["review_status"] == "completed" and supplied["manual_content_inspected"] is True, "E7 error-review completion differs")
        _require((_expected_sufficiency(fused_state) == "sufficient") or utilisation == "indeterminate", "E7 Answerer utilisation was assigned before sufficiency passed")
        boundary = mechanism_by_key.get(key)
        if boundary is not None and boundary["outcome"] == "harm":
            if enriched_review:
                if fused_state != boundary["fused_evidence_state"]:
                    _require(
                        review_details[str(supplied["review_id"])].get("cross_checks", {}).get("q051_semantic_sufficiency_reassessed_as_partial") is True
                        and key[1] == "conv-50-q051"
                        and fused_state == "partial",
                        "E7 overlapping fused-state revision is not documented",
                    )
            else:
                _require(fused_state == boundary["fused_evidence_state"], "E7 overlapping fused review differs")
                _require(mechanism == boundary["primary_mechanism"], "E7 overlapping mechanism review differs")
        normalized = dict(supplied)
        normalized["fusion_operation_state"] = operation
        output[key] = normalized
    _require(set(output) == set(expected), "E7 error review does not cover exactly the frozen Strict errors")
    return output


def _verify_exact_fusion(
    *, stage_index: Mapping[tuple[str, str, str], Mapping[str, Any]],
    record_index: Mapping[str, RunRecord],
) -> dict[tuple[str, str], dict[str, Any]]:
    verified: dict[tuple[str, str], dict[str, Any]] = {}
    for backbone in BACKBONES:
        e2_rows = sorted(
            (row for (candidate, condition, _), row in stage_index.items() if candidate == backbone and condition == "E2"),
            key=lambda row: int(row["global_position"]),
        )
        _require(len(e2_rows) == 60, "E7 parent population differs")
        for e2_row in e2_rows:
            qid = str(e2_row["question_id"])
            e6_row = stage_index[(backbone, "E6", qid)]
            e7_row = stage_index[(backbone, "E7", qid)]
            e2 = record_index[str(e2_row["analysis_row_id"])]
            e6 = record_index[str(e6_row["analysis_row_id"])]
            e7 = record_index[str(e7_row["analysis_row_id"])]
            _require(isinstance(e2.evidence_bundle, EvidenceBundle) and isinstance(e6.evidence_bundle, EvidenceBundle), "E7 parent bundle type differs")
            _require(isinstance(e7.evidence_bundle, FusionEvidenceBundle), "E7 fused bundle type differs")
            expected = build_e7_fusion_bundle(e2.evidence_bundle, e6.evidence_bundle)
            _require(e7.evidence_bundle == expected, f"E7 exact fusion differs: {backbone}/{qid}")
            _require(tuple(e7_row["source_bundle_ids"]) == expected.source_bundle_ids, "E7 Stage A parent bundle IDs differ")
            verified[(backbone, qid)] = {
                "exact_fusion_verified": True,
                "e2_item_count": len(e2.evidence_bundle.evidence_items),
                "e6_item_count": len(e6.evidence_bundle.evidence_items),
                "fused_item_count": len(expected.evidence_items),
                "deduplicated_item_count": expected.budget.deduplicated_items,
                "parent_items_preserved_exactly": len(expected.evidence_items) + expected.budget.deduplicated_items == len(e2.evidence_bundle.evidence_items) + len(e6.evidence_bundle.evidence_items),
                "no_new_search": expected.retrieval_metrics["search_calls"] == 0 and expected.retrieval_metrics["reused_upstream_retrieval"] is True,
            }
    _require(len(verified) == EXPECTED_FUSED_PATHS, "E7 exact-fusion verification count differs")
    _require(all(row["parent_items_preserved_exactly"] and row["no_new_search"] for row in verified.values()), "E7 exact-fusion invariant differs")
    return verified


def _evidence_rows(
    *, selective_rows: Sequence[Mapping[str, Any]], reviews: Mapping[tuple[str, str, str], Mapping[str, Any]],
) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for source in sorted(selective_rows, key=lambda row: (BACKBONES.index(str(row["backbone_id"])), CONDITION_ORDER[str(row["condition_id"])], int(row["global_position"]))):
        key = (str(source["backbone_id"]), str(source["condition_id"]), str(source["question_id"]))
        review = reviews[key]
        body = {
            "protocol_version": PROTOCOL_VERSION,
            "analysis_row_id": source["analysis_row_id"],
            "backbone_id": source["backbone_id"],
            "condition_id": source["condition_id"],
            "global_position": int(source["global_position"]),
            "question_id": source["question_id"],
            "category": int(source["category"]),
            "category_name": source["category_name"],
            "evidence_eligible": bool(source["evidence_eligible"]),
            "evidence_state": review["evidence_state"],
            "focus_state": review["focus_state"],
            "conflict_state": review["conflict_state"],
            "relation_preservation_state": review["relation_preservation_state"],
            "alternative_support_state": review["alternative_support_state"],
            "final_input_sufficiency_state": review["final_input_sufficiency_state"],
            "recorded_evidence_recall": source["evidence_recall"],
            "recorded_evidence_all_hit": source["evidence_all_hit"],
            "evidence_item_count": int(source["evidence_item_count"]),
            "evidence_bundle_characters": int(source["evidence_bundle_characters"]),
            "judge_label": source["judge_label"],
            "strict_score": float(source["strict_score"]),
            "soft_semantic_score": float(source["soft_semantic_score"]),
            "review_id": review["review_id"],
            "content_confidence": review["content_confidence"],
        }
        output.append({"result_id": _artifact_id("rq5-evidence-sufficiency-", body), **body})
    return output


def _packaging_rows(
    *, selective_rows: Sequence[Mapping[str, Any]], reviews: Mapping[tuple[str, str, str], Mapping[str, Any]],
    record_index: Mapping[str, RunRecord],
) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for source in sorted(selective_rows, key=lambda row: (BACKBONES.index(str(row["backbone_id"])), CONDITION_ORDER[str(row["condition_id"])], int(row["global_position"]))):
        key = (str(source["backbone_id"]), str(source["condition_id"]), str(source["question_id"]))
        review = reviews[key]
        bundle = record_index[str(source["analysis_row_id"])].evidence_bundle
        assert isinstance(bundle, EvidenceBundle)
        body = {
            "protocol_version": PROTOCOL_VERSION,
            "analysis_row_id": source["analysis_row_id"],
            "backbone_id": source["backbone_id"],
            "condition_id": source["condition_id"],
            "global_position": int(source["global_position"]),
            "question_id": source["question_id"],
            "category_name": source["category_name"],
            "evidence_retention_state": review["evidence_retention_state"],
            "packaging_causal_state": review["packaging_causal_state"],
            "recorded_skipped_item_count": int(bundle.budget.skipped_items),
            "whole_items_truncated": bool(bundle.budget.truncated),
            "focus_state": review["focus_state"],
            "conflict_state": review["conflict_state"],
            "relation_preservation_state": review["relation_preservation_state"],
            "evidence_item_count": len(bundle.evidence_items),
            "bundle_characters": int(bundle.budget.used),
            "budget_characters": int(bundle.budget.limit),
            "review_id": review["review_id"],
            "packaging_confidence": review["packaging_confidence"],
        }
        output.append({"result_id": _artifact_id("rq5-packaging-", body), **body})
    return output


def _answerer_rows(
    *, selective_rows: Sequence[Mapping[str, Any]], reviews: Mapping[tuple[str, str, str], Mapping[str, Any]],
) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for source in sorted(selective_rows, key=lambda row: (BACKBONES.index(str(row["backbone_id"])), CONDITION_ORDER[str(row["condition_id"])], int(row["global_position"]))):
        key = (str(source["backbone_id"]), str(source["condition_id"]), str(source["question_id"]))
        review = reviews[key]
        body = {
            "protocol_version": PROTOCOL_VERSION,
            "analysis_row_id": source["analysis_row_id"],
            "backbone_id": source["backbone_id"],
            "condition_id": source["condition_id"],
            "global_position": int(source["global_position"]),
            "question_id": source["question_id"],
            "category": int(source["category"]),
            "category_name": source["category_name"],
            "final_input_sufficiency_state": review["final_input_sufficiency_state"],
            "answerer_utilisation_state": review["answerer_utilisation_state"],
            "utilisation_review_state": review["utilisation_review_state"],
            "utilisation_subtype": review["utilisation_subtype"],
            "answer_form": review["answer_form"],
            "alternative_support_state": review["alternative_support_state"],
            "judge_label": source["judge_label"],
            "strict_score": float(source["strict_score"]),
            "token_precision": float(source["token_precision"]),
            "token_recall": float(source["token_recall"]),
            "token_f1": float(source["token_f1"]),
            "soft_semantic_score": float(source["soft_semantic_score"]),
            "answer_characters": int(source["answer_characters"]),
            "review_id": review["review_id"],
            "utilisation_confidence": review["utilisation_confidence"],
        }
        output.append({"result_id": _artifact_id("rq5-answerer-", body), **body})
    return output


def _evidence_outcome_matrix(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    groups: dict[tuple[str, str, str, str, str], list[Mapping[str, Any]]] = defaultdict(list)
    expanded: list[Mapping[str, Any]] = []
    for row in rows:
        expanded.extend(({**row, "_category_scope": "ALL"}, {**row, "_category_scope": str(row["category_name"])}))
    for row in expanded:
        key = (str(row["backbone_id"]), str(row["condition_id"]), str(row["_category_scope"]), str(row["evidence_state"]), str(row["judge_label"]))
        groups[key].append(row)
    output: list[dict[str, Any]] = []
    denominators = Counter((str(row["backbone_id"]), str(row["condition_id"]), str(row["_category_scope"]), str(row["evidence_state"])) for row in expanded)
    for key in sorted(groups, key=lambda x: (BACKBONES.index(x[0]), CONDITION_ORDER[x[1]], x[2], x[3], x[4])):
        backbone, condition, category, evidence_state, label = key
        values = groups[key]
        denominator = denominators[(backbone, condition, category, evidence_state)]
        body = {
            "protocol_version": PROTOCOL_VERSION,
            "backbone_id": backbone,
            "condition_id": condition,
            "category_scope": category,
            "evidence_state": evidence_state,
            "judge_label": label,
            "denominator": denominator,
            "count": len(values),
            "rate": len(values) / denominator,
            "mean_strict_score": math.fsum(float(row["strict_score"]) for row in values) / len(values),
            "mean_soft_semantic_score": math.fsum(float(row["soft_semantic_score"]) for row in values) / len(values),
        }
        output.append({"result_id": _artifact_id("rq5-evidence-outcome-", body), **body})
    return output


def _build_e7_rows(
    *, repo_root: Path,
    stage_index: Mapping[tuple[str, str, str], Mapping[str, Any]],
    reviews: Mapping[tuple[str, str, str], Mapping[str, Any]],
    error_reviews: Mapping[tuple[str, str], Mapping[str, Any]],
    mechanism_reviews: Mapping[tuple[str, str], Mapping[str, Any]],
    exact: Mapping[tuple[str, str], Mapping[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    diagnostics = {(str(row["backbone_id"]), str(row["question_id"])): row for row in _read_jsonl(repo_root / RQ3_PATH / "question-diagnostics.jsonl")}
    _require(len(diagnostics) == EXPECTED_FUSED_PATHS, "RQ3 question-diagnostic count differs")
    parents: list[dict[str, Any]] = []
    mechanisms: list[dict[str, Any]] = []
    for key in sorted(diagnostics, key=lambda value: (BACKBONES.index(value[0]), int(diagnostics[value]["global_position"]))):
        backbone, qid = key
        diagnostic = diagnostics[key]
        error_review = error_reviews.get(key)
        mechanism_review = mechanism_reviews.get(key)

        def parent_state(condition: str) -> str:
            reviewed = reviews.get((backbone, condition, qid))
            if reviewed is not None:
                return str(reviewed["evidence_state"])
            if error_review is not None:
                return str(error_review["parent_evidence_states"][condition])
            if mechanism_review is not None:
                return str(mechanism_review["parent_evidence_states"][condition])
            return "indeterminate"

        e2_state = parent_state("E2")
        e6_state = parent_state("E6")
        e2_suff = _parent_sufficiency(e2_state)
        e6_suff = _parent_sufficiency(e6_state)
        if error_review is not None:
            fused_state = str(error_review["fused_evidence_state"])
            operation = str(error_review["fusion_operation_state"])
            utilisation = str(error_review["answerer_utilisation_state"])
            mechanism = str(error_review["fusion_mechanism"])
            confidence = str(error_review["confidence"])
            review_id = str(error_review["review_id"])
            review_source = "e7_error_review"
            parent_review_consistent = all(
                reviews.get((backbone, condition, qid)) is None
                or str(error_review["parent_evidence_states"][condition])
                == str(reviews[(backbone, condition, qid)]["evidence_state"])
                for condition in ("E2", "E6")
            )
        elif mechanism_review is not None:
            fused_state = str(mechanism_review["fused_evidence_state"])
            parent_review_consistent = bool(mechanism_review["gated_parent_state_consistent"])
            operation = "repaired" if diagnostic["fusion_outcome"] == "repair" and parent_review_consistent else "indeterminate"
            utilisation = "utilised_correctly" if parent_review_consistent and _expected_sufficiency(fused_state) == "sufficient" else "indeterminate"
            mechanism = str(mechanism_review["primary_mechanism"]) if parent_review_consistent else "indeterminate"
            confidence = str(mechanism_review["confidence"]) if parent_review_consistent else "low"
            review_id = str(mechanism_review["review_id"])
            review_source = "e7_mechanism_review" if parent_review_consistent else "e7_mechanism_review_parent_state_conflict"
        else:
            fused_state = (
                "complete_but_noisy"
                if e2_suff == "sufficient" or e6_suff == "sufficient"
                else "indeterminate"
            )
            operation = "indeterminate"
            utilisation = "indeterminate"
            mechanism = "indeterminate"
            confidence = "high" if fused_state != "indeterminate" else "low"
            review_id = None
            review_source = "exact_parent_sufficiency_derivation"
            parent_review_consistent = True
        fused_suff = _expected_sufficiency(fused_state)
        e7 = stage_index[(backbone, "E7", qid)]
        parent_body = {
            "protocol_version": PROTOCOL_VERSION,
            "backbone_id": backbone,
            "global_position": int(e7["global_position"]),
            "question_id": qid,
            "category": int(e7["category"]),
            "category_name": e7["category_name"],
            "e2_evidence_state": e2_state,
            "e2_sufficiency_state": e2_suff,
            "e6_evidence_state": e6_state,
            "e6_sufficiency_state": e6_suff,
            "e7_evidence_state": fused_state,
            "e7_sufficiency_state": fused_suff,
            "fusion_outcome": diagnostic["fusion_outcome"],
            "e7_strict_score": float(diagnostic["e7_strict_score"]),
            "e2_source_id_count": int(diagnostic["e2_source_id_count"]),
            "e6_source_id_count": int(diagnostic["e6_source_id_count"]),
            "shared_source_id_count": int(diagnostic["shared_source_id_count"]),
            "union_source_id_count": int(diagnostic["union_source_id_count"]),
            "source_id_jaccard": float(diagnostic["source_id_jaccard"]),
            "e2_only_gold_source_id_count": int(diagnostic["e2_only_gold_source_id_count"]),
            "e6_only_gold_source_id_count": int(diagnostic["e6_only_gold_source_id_count"]),
            "union_evidence_recall": diagnostic["union_evidence_recall"],
            "exact_fusion_verified": bool(exact[key]["exact_fusion_verified"]),
        }
        parents.append({"result_id": _artifact_id("rq5-e7-parent-", parent_body), **parent_body})
        mechanism_body = {
            "protocol_version": PROTOCOL_VERSION,
            "backbone_id": backbone,
            "global_position": int(e7["global_position"]),
            "question_id": qid,
            "category_name": e7["category_name"],
            "fusion_outcome": diagnostic["fusion_outcome"],
            "fusion_operation_state": operation,
            "fusion_mechanism": mechanism,
            "fused_evidence_state": fused_state,
            "final_input_sufficiency_state": fused_suff,
            "answerer_utilisation_state": utilisation,
            "confidence": confidence,
            "review_source": review_source,
            "review_id": review_id,
            "parent_review_consistent": parent_review_consistent,
            "exact_fusion_verified": True,
            "parent_items_preserved_exactly": bool(exact[key]["parent_items_preserved_exactly"]),
            "deduplicated_item_count": int(exact[key]["deduplicated_item_count"]),
            "no_new_search": bool(exact[key]["no_new_search"]),
        }
        mechanisms.append({"result_id": _artifact_id("rq5-e7-mechanism-", mechanism_body), **mechanism_body})
    return parents, mechanisms


def _e7_matrix(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    groups: dict[tuple[str, str, str, str, str], list[Mapping[str, Any]]] = defaultdict(list)
    for row in rows:
        key = (str(row["backbone_id"]), str(row["e2_sufficiency_state"]), str(row["e6_sufficiency_state"]), str(row["e7_sufficiency_state"]), str(row["fusion_outcome"]))
        groups[key].append(row)
    output: list[dict[str, Any]] = []
    for key in sorted(groups):
        values = groups[key]
        backbone, e2, e6, e7, outcome = key
        parent_profile_n = sum(1 for row in rows if row["backbone_id"] == backbone and row["e2_sufficiency_state"] == e2 and row["e6_sufficiency_state"] == e6)
        correct = sum(float(row["e7_strict_score"]) == 1.0 for row in values)
        body = {
            "protocol_version": PROTOCOL_VERSION,
            "backbone_id": backbone,
            "e2_sufficiency_state": e2,
            "e6_sufficiency_state": e6,
            "e7_sufficiency_state": e7,
            "fusion_outcome": outcome,
            "parent_profile_denominator": parent_profile_n,
            "count": len(values),
            "e7_strict_correct_count": correct,
            "e7_strict_accuracy_within_cell": correct / len(values),
        }
        output.append({"result_id": _artifact_id("rq5-e7-matrix-", body), **body})
    return output


def _updated_state_register(
    *, repo_root: Path,
    reviews: Mapping[tuple[str, str, str], Mapping[str, Any]],
    e7_errors: Mapping[tuple[str, str], Mapping[str, Any]],
) -> list[dict[str, Any]]:
    previous = _read_jsonl(repo_root / RETRIEVAL_PATH / "root-cause-state-register-after-retrieval.jsonl")
    _require(len(previous) == EXPECTED_STATE_ROWS, "Post-retrieval state-register count differs")
    output: list[dict[str, Any]] = []
    for source in previous:
        before = dict(source)
        updated = dict(source)
        condition = str(source["condition_id"])
        backbone = str(source["packet_backbone"])
        qid = str(source["question_id"])
        if condition in SELECTIVE_CONDITIONS:
            review = reviews[(backbone, condition, qid)]
            updated["evidence_retention_state"] = review["evidence_retention_state"]
            updated["final_input_sufficiency_state"] = review["final_input_sufficiency_state"]
            updated["answerer_utilisation_state"] = review["answerer_utilisation_state"]
        elif condition == FUSED_CONDITION:
            review = e7_errors[(backbone, qid)]
            updated["parent_e2_bundle_state"] = _expected_sufficiency(str(review["parent_evidence_states"]["E2"]))
            updated["parent_e6_bundle_state"] = _expected_sufficiency(str(review["parent_evidence_states"]["E6"]))
            updated["fusion_operation_state"] = review["fusion_operation_state"]
            updated["evidence_retention_state"] = "retained"
            updated["final_input_sufficiency_state"] = _expected_sufficiency(str(review["fused_evidence_state"]))
            updated["answerer_utilisation_state"] = review["answerer_utilisation_state"]
        else:
            _require(condition == FULL_CONTEXT_CONDITION, "Unexpected RQ5 state-register condition")
        changed = {field for field in set(before) | set(updated) if before.get(field) != updated.get(field)}
        _require(changed <= set(OWNED_STATE_FIELDS), "Downstream stage changed an unowned state field")
        if condition in SELECTIVE_CONDITIONS:
            _require(
                all(updated[field] not in {"pending", "not_applicable"} for field in ("evidence_retention_state", "final_input_sufficiency_state", "answerer_utilisation_state")),
                "Downstream E1--E6 state remained nonterminal",
            )
        elif condition == FUSED_CONDITION:
            _require(
                all(updated[field] not in {"pending", "not_applicable"} for field in OWNED_STATE_FIELDS),
                "Downstream E7 state remained nonterminal",
            )
        if condition == FULL_CONTEXT_CONDITION:
            _require(updated == before, "Downstream stage changed a Full Context state row")
        for field in ("evaluation_agreement_state", "long_context_utilisation_state", "primary_cause", "secondary_causes", "attribution_status", "attribution_strength", "causal_sufficiency"):
            _require(updated[field] == before[field], f"Downstream stage changed protected field: {field}")
        output.append(updated)
    _require(Counter(row["condition_id"] for row in output) == Counter(row["condition_id"] for row in previous), "Downstream state-register condition census differs")
    return output


def _summary_rows(
    *, evidence: Sequence[Mapping[str, Any]], packaging: Sequence[Mapping[str, Any]],
    answerer: Sequence[Mapping[str, Any]], e7: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []

    def add(family: str, backbone: str, condition: str, category: str, state: str, count: int, denominator: int) -> None:
        body = {
            "protocol_version": PROTOCOL_VERSION,
            "summary_family": family,
            "backbone_id": backbone,
            "condition_id": condition,
            "category_scope": category,
            "state": state,
            "count": count,
            "denominator": denominator,
            "rate": count / denominator,
        }
        output.append({"result_id": _artifact_id("rq5-downstream-summary-", body), **body})

    for family, rows, field in (
        ("evidence_state", evidence, "evidence_state"),
        ("packaging_state", packaging, "evidence_retention_state"),
        ("answerer_utilisation", answerer, "answerer_utilisation_state"),
    ):
        for backbone in BACKBONES:
            for condition in SELECTIVE_CONDITIONS:
                selected = [row for row in rows if row["backbone_id"] == backbone and row["condition_id"] == condition]
                counts = Counter(str(row[field]) for row in selected)
                for state in sorted(counts):
                    add(family, backbone, condition, "ALL", state, counts[state], len(selected))
                for category in sorted({str(row["category_name"]) for row in selected}):
                    category_rows = [row for row in selected if row["category_name"] == category]
                    category_counts = Counter(str(row[field]) for row in category_rows)
                    for state in sorted(category_counts):
                        add(family, backbone, condition, category, state, category_counts[state], len(category_rows))
    for backbone in BACKBONES:
        selected = [row for row in e7 if row["backbone_id"] == backbone]
        counts = Counter(str(row["fusion_operation_state"]) for row in selected)
        for state in sorted(counts):
            add("e7_fusion_operation", backbone, "E7", "ALL", state, counts[state], len(selected))
    return output


def _assert_text_free(tables: Mapping[str, Sequence[Mapping[str, Any]]]) -> None:
    def inspect(value: Any, table: str) -> None:
        if isinstance(value, Mapping):
            for key, nested in value.items():
                lowered = str(key).casefold()
                _require(lowered not in FORBIDDEN_OUTPUT_FIELDS, f"Forbidden text field in {table}: {key}")
                _require(not any(fragment in lowered for fragment in SECRET_FIELD_FRAGMENTS), f"Secret-like field in {table}: {key}")
                inspect(nested, table)
        elif isinstance(value, (list, tuple)):
            for nested in value:
                inspect(nested, table)

    for table, rows in tables.items():
        inspect(rows, table)


def _load_inputs(
    *, repo_root: Path, review_paths: Mapping[str, str | Path] | None,
) -> tuple[
    list[dict[str, Any]],
    dict[tuple[str, str, str], dict[str, Any]],
    dict[str, RunRecord],
    dict[tuple[str, str, str], dict[str, Any]],
    dict[tuple[str, str], dict[str, Any]],
    dict[tuple[str, str], dict[str, Any]],
    dict[tuple[str, str], dict[str, Any]],
    dict[str, Path],
    dict[str, dict[str, Any]],
]:
    upstream = _validate_upstream(repo_root)
    all_rows, stage_index = _stage_rows(repo_root)
    relevant = [row for row in all_rows if row.get("condition_id") in (*SELECTIVE_CONDITIONS, FUSED_CONDITION)]
    record_index = {str(row["analysis_row_id"]): _load_record(repo_root, row) for row in relevant}
    paths = _resolved_review_paths(repo_root, review_paths)
    errors = _read_jsonl(repo_root / STAGE1_PATH / "strict-error-cases.jsonl")
    downstream_rows = []
    for backbone in BACKBONES:
        downstream_rows.extend(
            _validate_downstream_review_payload(
                repo_root=repo_root,
                path=paths[backbone],
                backbone=backbone,
                stage_index=stage_index,
                record_index=record_index,
                strict_errors=errors,
            )
        )
    downstream_by_key = {(str(row["backbone_id"]), str(row["condition_id"]), str(row["question_id"])): row for row in downstream_rows}
    _require(len(downstream_by_key) == EXPECTED_SELECTIVE_ERRORS, "Downstream review identities repeat")
    mechanism = _load_e7_mechanism_review(
        repo_root=repo_root,
        path=paths["e7_mechanism"],
        stage_index=stage_index,
        record_index=record_index,
        downstream_by_key=downstream_by_key,
    )
    e7_errors = _load_e7_error_review(path=paths["e7_error"], errors=errors, stage_index=stage_index, downstream_by_key=downstream_by_key, mechanism_by_key=mechanism)
    exact = _verify_exact_fusion(stage_index=stage_index, record_index=record_index)
    return all_rows, stage_index, record_index, downstream_by_key, mechanism, e7_errors, exact, paths, upstream


def _build_core(
    *, repo_root: Path, review_paths: Mapping[str, str | Path] | None = None,
) -> tuple[dict[str, list[dict[str, Any]]], dict[str, Path], dict[str, dict[str, Any]]]:
    all_rows, stage_index, records, reviews, mechanism, e7_errors, exact, paths, upstream = _load_inputs(repo_root=repo_root, review_paths=review_paths)
    selective = [stage_index[key] for key in reviews]
    evidence = _evidence_rows(selective_rows=selective, reviews=reviews)
    packaging = _packaging_rows(selective_rows=selective, reviews=reviews, record_index=records)
    answerer = _answerer_rows(selective_rows=selective, reviews=reviews)
    e7_parents, e7_mechanisms = _build_e7_rows(repo_root=repo_root, stage_index=stage_index, reviews=reviews, error_reviews=e7_errors, mechanism_reviews=mechanism, exact=exact)
    tables = {
        "evidence-sufficiency": evidence,
        "packaging-loss": packaging,
        "answerer-conversion": answerer,
        "evidence-state-outcome-matrix": _evidence_outcome_matrix(evidence),
        "e7-parent-sufficiency": e7_parents,
        "e7-parent-sufficiency-matrix": _e7_matrix(e7_parents),
        "e7-mechanisms": e7_mechanisms,
        POST_DOWNSTREAM_STATE_BASENAME: _updated_state_register(repo_root=repo_root, reviews=reviews, e7_errors=e7_errors),
        "downstream-summary": _summary_rows(evidence=evidence, packaging=packaging, answerer=answerer, e7=e7_mechanisms),
    }
    _assert_text_free(tables)
    return tables, paths, upstream


def _source_manifest(
    *, repo_root: Path, review_paths: Mapping[str, Path], upstream: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    rows = [row for row in _read_jsonl(repo_root / STAGE_A_PATH) if row.get("condition_id") in (*SELECTIVE_CONDITIONS, FUSED_CONDITION)]
    fixed = [
        STAGE_A_PATH,
        f"{STAGE1_PATH}/strict-error-cases.jsonl",
        f"{STAGE1_PATH}/state-model.json",
        f"{STAGE1_PATH}/audit.json",
        f"{STAGE1_PATH}/RQ5-STAGE-1.PASSED",
        f"{STORAGE_PATH}/audit.json",
        f"{STORAGE_PATH}/RQ5-STORAGE-AUDIT.PASSED",
        f"{RETRIEVAL_PATH}/root-cause-state-register-after-retrieval.jsonl",
        f"{RETRIEVAL_PATH}/audit.json",
        f"{RETRIEVAL_PATH}/RQ5-RETRIEVAL-AUDIT.PASSED",
        f"{RQ3_PATH}/question-diagnostics.jsonl",
        f"{RQ3_PATH}/rq5-candidate-cases.jsonl",
        f"{RQ3_PATH}/audit.json",
        f"{RQ3_PATH}/RQ3.PASSED",
        *(_relative(repo_root, review_paths[role]) for role in sorted(review_paths)),
        *(str(row["source_record_path"]) for row in rows),
    ]
    relative_paths = list(dict.fromkeys(fixed))
    files = [
        {"path": relative, "sha256": _sha256_file(_safe_repo_file(repo_root, relative)), "bytes": _safe_repo_file(repo_root, relative).stat().st_size}
        for relative in relative_paths
    ]
    body = {
        "protocol_version": PROTOCOL_VERSION,
        "upstream_audits": {role: dict(upstream[role]) for role in sorted(upstream)},
        "files": files,
        "review_roles": {role: _relative(repo_root, review_paths[role]) for role in sorted(review_paths)},
        "no_api_calls": True,
        "formal_source_mutation": False,
    }
    return {"source_manifest_id": _artifact_id("rq5-downstream-sources-", body), **body}


def _schema(tables: Mapping[str, Sequence[Mapping[str, Any]]]) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "protocol_version": PROTOCOL_VERSION,
        "scope": "Chapter 5 Sections 5.6.4.1--5.6.4.3 only",
        "gate_order": ["e1_e6_evidence_sufficiency_and_packaging", "answerer_utilisation", "e7_parent_sufficiency_and_exact_fusion"],
        "state_update_scope": list(OWNED_STATE_FIELDS),
        "protected_scope": ["B3-FullContext", "evaluation_agreement_state", "long_context_utilisation_state", "primary_cause", "secondary_causes", "attribution_status", "attribution_strength", "causal_sufficiency"],
        "tables": {name: {"rows": len(rows), "fields": list(rows[0]) if rows else []} for name, rows in tables.items()},
        "public_tables_are_text_free": True,
    }


def _payloads(
    *, tables: Mapping[str, Sequence[Mapping[str, Any]]], manifest: Mapping[str, Any],
) -> dict[str, bytes]:
    output: dict[str, bytes] = {}
    for name in TABLES:
        output[f"{name}.jsonl"] = _jsonl_payload(tables[name])
        output[f"{name}.csv"] = _csv_payload(tables[name])
    output["schema.json"] = canonical_json_bytes(_schema(tables)) + b"\n"
    output["source-manifest.json"] = canonical_json_bytes(dict(manifest)) + b"\n"
    return output


def _audit_body(
    *, tables: Mapping[str, Sequence[Mapping[str, Any]]], manifest: Mapping[str, Any], output_hashes: Mapping[str, str],
) -> dict[str, Any]:
    states = tables[POST_DOWNSTREAM_STATE_BASENAME]
    return {
        "schema_version": 1,
        "protocol_version": PROTOCOL_VERSION,
        "status": "passed",
        "scope": "RQ5 evidence sufficiency, packaging, Answerer utilisation, and E7 fusion",
        "counts": {name: len(tables[name]) for name in TABLES},
        "selective_error_paths": len(tables["evidence-sufficiency"]),
        "e7_paths": len(tables["e7-parent-sufficiency"]),
        "state_rows": len(states),
        "full_context_rows_unchanged": sum(row["condition_id"] == FULL_CONTEXT_CONDITION for row in states),
        "e7_exact_fusion_verified": sum(row["exact_fusion_verified"] for row in tables["e7-mechanisms"]),
        "whole_item_truncations": sum(row["whole_items_truncated"] for row in tables["packaging-loss"]),
        "source_manifest_id": manifest["source_manifest_id"],
        "output_sha256": dict(sorted(output_hashes.items())),
        "public_tables_are_text_free": True,
        "no_api_calls": True,
        "formal_source_mutation": False,
        "full_context_analysis_computed": False,
        "evaluation_analysis_computed": False,
        "primary_attribution_computed": False,
    }


def _marker(audit: Mapping[str, Any], audit_sha256: str) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "protocol_version": PROTOCOL_VERSION,
        "status": "passed",
        "audit_id": audit["audit_id"],
        "audit_sha256": audit_sha256,
        "selective_error_paths": audit["selective_error_paths"],
        "e7_paths": audit["e7_paths"],
        "state_rows": audit["state_rows"],
        "no_api_calls": True,
    }


def audit_rq5_downstream_output(
    *, repo_root: Path, output_dir: Path,
    review_paths: Mapping[str, str | Path] | None = None,
) -> dict[str, Any]:
    root, output = Path(repo_root).resolve(), Path(output_dir).resolve()
    _require(output.is_dir() and not output.is_symlink(), "RQ5 downstream output is unsafe")
    tables, paths, upstream = _build_core(repo_root=root, review_paths=review_paths)
    manifest = _source_manifest(repo_root=root, review_paths=paths, upstream=upstream)
    payloads = _payloads(tables=tables, manifest=manifest)
    hashes = {name: hashlib.sha256(payload).hexdigest() for name, payload in sorted(payloads.items())}
    body = _audit_body(tables=tables, manifest=manifest, output_hashes=hashes)
    audit = {"audit_id": _artifact_id("rq5-downstream-audit-", body), **body}
    audit_payload = canonical_json_bytes(audit) + b"\n"
    marker_payload = canonical_json_bytes(_marker(audit, hashlib.sha256(audit_payload).hexdigest())) + b"\n"
    expected_names = set(payloads) | {"audit.json", "RQ5-DOWNSTREAM.PASSED"}
    entries = list(output.iterdir())
    _require(all(entry.is_file() and not entry.is_symlink() for entry in entries), "RQ5 downstream output contains an unsafe entry")
    _require({entry.name for entry in entries} == expected_names, "RQ5 downstream output file set differs")
    for name, payload in payloads.items():
        _require((output / name).read_bytes() == payload, f"RQ5 downstream artifact differs: {name}")
    _require((output / "audit.json").read_bytes() == audit_payload, "RQ5 downstream audit differs")
    _require((output / "RQ5-DOWNSTREAM.PASSED").read_bytes() == marker_payload, "RQ5 downstream marker differs")
    return audit


def build_rq5_downstream(
    *, repo_root: Path, output_dir: Path,
    review_paths: Mapping[str, str | Path] | None = None,
) -> dict[str, Any]:
    root, destination = Path(repo_root).resolve(), Path(output_dir).resolve()
    _require(root.is_dir() and not root.is_symlink(), "Repository root is unsafe")
    _require(not destination.exists(), "RQ5 downstream output already exists")
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=".rq5-downstream-", dir=destination.parent))
    try:
        tables, paths, upstream = _build_core(repo_root=root, review_paths=review_paths)
        manifest = _source_manifest(repo_root=root, review_paths=paths, upstream=upstream)
        payloads = _payloads(tables=tables, manifest=manifest)
        for name, payload in payloads.items():
            _write(temporary / name, payload)
        hashes = {name: _sha256_file(temporary / name) for name in sorted(payloads)}
        body = _audit_body(tables=tables, manifest=manifest, output_hashes=hashes)
        audit = {"audit_id": _artifact_id("rq5-downstream-audit-", body), **body}
        _write(temporary / "audit.json", canonical_json_bytes(audit) + b"\n")
        _write(temporary / "RQ5-DOWNSTREAM.PASSED", canonical_json_bytes(_marker(audit, _sha256_file(temporary / "audit.json"))) + b"\n")
        result = audit_rq5_downstream_output(repo_root=root, output_dir=temporary, review_paths=review_paths)
        _require(result["status"] == "passed", "RQ5 downstream pre-publication audit failed")
        _require(not destination.exists(), "RQ5 downstream destination appeared during build")
        os.rename(temporary, destination)
        descriptor = os.open(destination.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
    except Exception:
        shutil.rmtree(temporary, ignore_errors=True)
        raise
    return audit_rq5_downstream_output(repo_root=root, output_dir=destination, review_paths=review_paths)


def review_contract() -> dict[str, Any]:
    """Return the strict, text-free review and artifact handoff contract."""

    return {
        "artifact_handoff": {
            "output_directory": DEFAULT_OUTPUT_DIR,
            "post_downstream_state_jsonl": POST_DOWNSTREAM_STATE_PATH,
            "post_downstream_state_csv": f"{DEFAULT_OUTPUT_DIR}/{POST_DOWNSTREAM_STATE_BASENAME}.csv",
            "owned_state_fields": list(OWNED_STATE_FIELDS),
        },
        "downstream_review": {
            "protocol_versions": dict(DOWNSTREAM_REVIEW_PROTOCOL_VERSIONS),
            "files": {backbone: DEFAULT_REVIEW_PATHS[backbone] for backbone in BACKBONES},
            "rows_per_file": dict(EXPECTED_SELECTIVE_ERRORS_BY_BACKBONE),
            "qwen_row_fields": sorted(QWEN_REVIEW_ROW_FIELDS),
            "deepseek_row_fields": sorted(DEEPSEEK_REVIEW_ROW_FIELDS),
            "evidence_states": sorted(EVIDENCE_STATES),
            "retention_states": sorted(RETENTION_STATES),
            "packaging_causal_states": sorted(PACKAGING_CAUSAL_STATES),
            "answerer_states": sorted(ANSWERER_STATES),
            "utilisation_subtypes": sorted(UTILISATION_SUBTYPES),
            "answer_forms": sorted(ANSWER_FORMS),
        },
        "e7_error_review": {
            "protocol_version": E7_ERROR_REVIEW_PROTOCOL_VERSION,
            "file": DEFAULT_REVIEW_PATHS["e7_error"],
            "rows": EXPECTED_FUSED_ERRORS,
            "top_level_fields": sorted(E7_ERROR_REVIEW_TOP_FIELDS),
            "row_fields": sorted(E7_ERROR_REVIEW_ROW_FIELDS),
            "fusion_operation_states": sorted(FUSION_OPERATION_STATES),
            "fusion_mechanisms": sorted(FUSION_MECHANISMS),
        },
        "e7_mechanism_review": {
            "protocol_version": E7_MECHANISM_REVIEW_PROTOCOL_VERSION,
            "file": DEFAULT_REVIEW_PATHS["e7_mechanism"],
            "rows": EXPECTED_MECHANISM_CANDIDATES,
        },
        "gate_order": ["evidence_and_packaging", "answerer_utilisation", "e7_parent_and_fusion"],
        "no_api_calls": True,
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("contract", "build", "audit"))
    parser.add_argument("--repo-root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--qwen-review", type=Path)
    parser.add_argument("--deepseek-review", type=Path)
    parser.add_argument("--e7-mechanism-review", type=Path)
    parser.add_argument("--e7-error-review", type=Path)
    args = parser.parse_args(argv)
    if args.command == "contract":
        print(json.dumps(review_contract(), ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    _require(args.output_dir is not None, "--output-dir is required for build/audit")
    supplied = (args.qwen_review, args.deepseek_review, args.e7_mechanism_review, args.e7_error_review)
    _require(all(value is None for value in supplied) or all(value is not None for value in supplied), "Review path overrides must be supplied together")
    review_paths = None if supplied[0] is None else {
        "qwen": args.qwen_review,
        "deepseek": args.deepseek_review,
        "e7_mechanism": args.e7_mechanism_review,
        "e7_error": args.e7_error_review,
    }
    kwargs = {"repo_root": args.repo_root, "output_dir": args.output_dir, "review_paths": review_paths}
    result = build_rq5_downstream(**kwargs) if args.command == "build" else audit_rq5_downstream_output(**kwargs)
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
