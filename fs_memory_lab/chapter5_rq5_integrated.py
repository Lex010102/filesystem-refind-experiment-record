"""Build the audited integrated bottleneck decomposition for RQ5 Section 5.6.6.

This stage joins the already-audited Storage, Retrieval, Packaging, Answerer,
E7, Full Context, and evaluation-disagreement analyses.  It assigns exactly
one primary breakpoint to each of the 250 Strict-noncorrect paths and retains
all supported co-occurring mechanisms separately.

The assignment rule is deliberately conservative.  A diagnostic miss is not
treated as causal unless the final input was also insufficient.  An E7 harm
outcome is not treated as a fusion failure because the audited fusion operation
preserved the parent EvidenceItems exactly.  Unscreened evaluation rows are
never assumed to be evaluation agreement.

No model, API, or network call is made.  Formal experiments and scores are
read-only.  Published artifacts contain identifiers, coded states, counts,
hashes, and rates, but no question, answer, evidence, prompt, or rationale text.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import tempfile
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Mapping, Sequence

from .chapter5_rq5_downstream import audit_rq5_downstream_output
from .chapter5_rq5_evaluation import DEFAULT_REVIEW_PATH as EVALUATION_REVIEW_PATH
from .chapter5_rq5_evaluation import audit_rq5_evaluation
from .chapter5_rq5_full_context import audit_rq5_full_context_output
from .chapter5_rq5_retrieval import audit_rq5_retrieval_output
from .chapter5_rq5_stage1 import audit_rq5_stage1_output
from .chapter5_rq5_storage import audit_rq5_storage_output
from .chapter5_stage_b import _csv_payload, _jsonl_payload, _require, _sha256_file, _write
from .evidence import canonical_json_bytes, sha256_bytes


PROTOCOL_VERSION = "chapter5-main60-rq5-integrated-v1"
EXPECTED_ROWS = 250
EXPECTED_SELECTIVE = 205
EXPECTED_E7 = 31
EXPECTED_FULL_CONTEXT = 14

STAGE1_DIR = "artifacts/chapter5-main60-analysis-v1/rq5-root-cause-index"
STAGE_A_DIR = "artifacts/chapter5-main60-analysis-v1/stage-a"
STORAGE_DIR = "artifacts/chapter5-main60-analysis-v1/rq5-storage-audit"
RETRIEVAL_DIR = "artifacts/chapter5-main60-analysis-v1/rq5-retrieval-audit"
DOWNSTREAM_DIR = "artifacts/chapter5-main60-analysis-v1/rq5-downstream-audit"
FULL_CONTEXT_DIR = "artifacts/chapter5-main60-analysis-v1/rq5-full-context-audit"
EVALUATION_DIR = "artifacts/chapter5-main60-analysis-v1/rq5-evaluation-audit"
DEFAULT_OUTPUT_DIR = "artifacts/chapter5-main60-analysis-v1/rq5-integrated-bottleneck"

SELECTIVE_CONDITIONS = tuple(f"E{i}" for i in range(1, 7))
FUSED_CONDITION = "E7"
FULL_CONTEXT_CONDITION = "B3-FullContext"

RETRIEVAL_BREAK_STATES = {
    "annotated_source_not_reached": "retrieval_source_not_reached",
    "source_reached_gold_not_observed": "retrieval_source_not_observed",
    "partial_annotated_acquisition": "retrieval_partial_acquisition",
    "complete_observation_incomplete_selection": "retrieval_incomplete_selection",
}

LONG_CONTEXT_BREAK_STATES = {
    "missed_relevant_content",
    "distractor_confusion",
    "temporal_confusion",
}

E7_ANSWERER_MECHANISMS = {
    "answerer_unsupported_abstention",
    "answerer_temporal_inference_failure",
    "answerer_competing_clause_selection",
    "answerer_temporal_location_selection_failure",
}

E7_EVALUATION_MECHANISMS = {
    "evaluation_sensitive_source_reference_mismatch",
    "evaluation_sensitive_reference_granularity",
    "evaluation_threshold_instability",
}

PRIMARY_STAGE_ORDER = {
    "storage": 1,
    "retrieval": 2,
    "packaging": 3,
    "answerer": 4,
    "fusion_or_long_context": 5,
    "evaluation_sensitive": 6,
    "mixed_or_indeterminate": 7,
}

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

TABLES = (
    "integrated-attributions",
    "case-mechanisms",
    "primary-root-cause-summary",
    "cooccurring-mechanism-summary",
    "primary-secondary-matrix",
    "representative-cases",
    "root-cause-state-register-final",
)


def _read_json(path: Path) -> dict[str, Any]:
    _require(path.is_file() and not path.is_symlink(), f"Missing or unsafe JSON: {path}")
    value = json.loads(path.read_text(encoding="utf-8"))
    _require(isinstance(value, dict), f"JSON root must be an object: {path}")
    return dict(value)


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    _require(path.is_file() and not path.is_symlink(), f"Missing or unsafe JSONL: {path}")
    output: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            row = json.loads(line)
            _require(isinstance(row, dict), f"JSONL row must be an object: {path}")
            output.append(dict(row))
    return output


def _relative(root: Path, path: Path) -> str:
    return str(path.resolve().relative_to(root.resolve()))


def _artifact_id(prefix: str, body: Mapping[str, Any]) -> str:
    return prefix + sha256_bytes(canonical_json_bytes(dict(body)))


def _artifact(root: Path, path: Path) -> dict[str, Any]:
    return {
        "path": _relative(root, path),
        "sha256": _sha256_file(path),
        "bytes": path.stat().st_size,
    }


def _unique_index(rows: Sequence[Mapping[str, Any]], fields: Sequence[str], label: str) -> dict[tuple[str, ...], dict[str, Any]]:
    output: dict[tuple[str, ...], dict[str, Any]] = {}
    for source in rows:
        row = dict(source)
        key = tuple(str(row[field]) for field in fields)
        _require(key not in output, f"Duplicate {label} key: {key}")
        output[key] = row
    return output


def _validate_upstream(root: Path) -> dict[str, dict[str, Any]]:
    audits = {
        "stage1": audit_rq5_stage1_output(
            repo_root=root, stage_a_dir=root / STAGE_A_DIR, output_dir=root / STAGE1_DIR
        ),
        "storage": audit_rq5_storage_output(
            repo_root=root, output_dir=root / STORAGE_DIR
        ),
        "retrieval": audit_rq5_retrieval_output(
            repo_root=root, output_dir=root / RETRIEVAL_DIR
        ),
        "downstream": audit_rq5_downstream_output(
            repo_root=root, output_dir=root / DOWNSTREAM_DIR
        ),
        "full_context": audit_rq5_full_context_output(
            repo_root=root, output_dir=root / FULL_CONTEXT_DIR
        ),
        "evaluation": audit_rq5_evaluation(
            repo_root=root,
            review_path=root / EVALUATION_REVIEW_PATH,
            output_dir=root / EVALUATION_DIR,
        ),
    }
    _require(all(audit.get("status") == "passed" for audit in audits.values()), "An upstream RQ5 audit failed")
    return audits


def _load_inputs(root: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    upstream = _validate_upstream(root)
    paths = {
        "errors": root / STAGE1_DIR / "strict-error-cases.jsonl",
        "state": root / FULL_CONTEXT_DIR / "root-cause-state-register-after-full-context.jsonl",
        "storage": root / STORAGE_DIR / "case-storage-linkage.jsonl",
        "retrieval": root / RETRIEVAL_DIR / "strict-error-retrieval-linkage.jsonl",
        "sufficiency": root / DOWNSTREAM_DIR / "evidence-sufficiency.jsonl",
        "packaging": root / DOWNSTREAM_DIR / "packaging-loss.jsonl",
        "answerer": root / DOWNSTREAM_DIR / "answerer-conversion.jsonl",
        "e7": root / DOWNSTREAM_DIR / "e7-mechanisms.jsonl",
        "full_context": root / FULL_CONTEXT_DIR / "full-context-mechanisms.jsonl",
        "evaluation": root / EVALUATION_DIR / "disagreement-cases.jsonl",
    }
    rows = {name: _read_jsonl(path) for name, path in paths.items()}
    _require(len(rows["errors"]) == EXPECTED_ROWS, "Strict-error population differs")
    _require(len(rows["state"]) == EXPECTED_ROWS, "Latest state-register population differs")
    _require(len(rows["storage"]) == EXPECTED_SELECTIVE, "Storage linkage count differs")
    _require(len(rows["retrieval"]) == EXPECTED_SELECTIVE, "Retrieval linkage count differs")
    _require(len(rows["sufficiency"]) == EXPECTED_SELECTIVE, "Sufficiency review count differs")
    _require(len(rows["packaging"]) == EXPECTED_SELECTIVE, "Packaging review count differs")
    _require(len(rows["answerer"]) == EXPECTED_SELECTIVE, "Answerer review count differs")
    _require(len(rows["e7"]) == 120, "E7 mechanism population differs")
    _require(len(rows["full_context"]) == EXPECTED_FULL_CONTEXT, "Full Context error review count differs")
    _require(len(rows["evaluation"]) == 168, "Evaluation screen population differs")

    errors = _unique_index(rows["errors"], ("analysis_row_id",), "strict error")
    state = _unique_index(rows["state"], ("analysis_row_id",), "state")
    _require(set(errors) == set(state), "Strict errors and state register differ")
    indexes = {
        "errors": errors,
        "state": state,
        "storage": _unique_index(rows["storage"], ("case_id",), "storage"),
        "retrieval": _unique_index(rows["retrieval"], ("analysis_row_id",), "retrieval"),
        "sufficiency": _unique_index(rows["sufficiency"], ("analysis_row_id",), "sufficiency"),
        "packaging": _unique_index(rows["packaging"], ("analysis_row_id",), "packaging"),
        "answerer": _unique_index(rows["answerer"], ("analysis_row_id",), "answerer"),
        "e7": _unique_index(rows["e7"], ("backbone_id", "question_id"), "E7"),
        "full_context": _unique_index(rows["full_context"], ("analysis_row_id",), "Full Context"),
        "evaluation": _unique_index(rows["evaluation"], ("analysis_row_id",), "evaluation"),
    }
    metadata = {"upstream": upstream, "paths": paths, "raw_rows": rows}
    return indexes, metadata


def _mechanism(group: str, code: str, basis: str) -> tuple[str, str, str]:
    return group, code, basis


def _deduplicate_mechanisms(values: Sequence[tuple[str, str, str]]) -> list[tuple[str, str, str]]:
    output: list[tuple[str, str, str]] = []
    seen: set[tuple[str, str]] = set()
    for group, code, basis in values:
        key = (group, code)
        if key not in seen:
            seen.add(key)
            output.append((group, code, basis))
    return output


def _evaluation_details(row_id: str, evaluation: Mapping[tuple[str, ...], Mapping[str, Any]]) -> dict[str, Any] | None:
    value = evaluation.get((row_id,))
    return None if value is None else dict(value)


def _selective_attribution(
    *, base: Mapping[str, Any], state: Mapping[str, Any], storage: Mapping[str, Any],
    retrieval: Mapping[str, Any], sufficiency: Mapping[str, Any], packaging: Mapping[str, Any],
    answerer: Mapping[str, Any], evaluation: Mapping[str, Any] | None,
) -> tuple[dict[str, str], list[tuple[str, str, str]]]:
    mechanisms: list[tuple[str, str, str]] = []
    diag = str(retrieval["diagnostic_retrieval_state"])
    final_state = str(sufficiency["final_input_sufficiency_state"])
    packaging_state = str(packaging["packaging_causal_state"])
    answerer_state = str(answerer["answerer_utilisation_state"])
    evaluation_sensitive = bool(evaluation and evaluation["evaluation_sensitive"])
    source_reference_mismatch = (
        str(storage["store_availability_state"]) == "available_with_reference_entity_mismatch"
    )

    if bool(storage["shared_representation_insufficiency_present"]):
        mechanisms.append(_mechanism("storage_representation", "shared_representation_insufficiency", "storage_audit"))
    if str(storage["store_availability_state"]) in {
        "partial", "available_with_reference_entity_mismatch", "available_but_conflicting"
    }:
        mechanisms.append(_mechanism("source_reference", str(storage["store_availability_state"]), "storage_audit"))
    if diag in RETRIEVAL_BREAK_STATES:
        mechanisms.append(_mechanism("retrieval", diag, "retrieval_trace_audit"))
    if diag == "complete_selection_incomplete_bundle":
        mechanisms.append(_mechanism("packaging", diag, "retrieval_to_bundle_audit"))
    if final_state == "insufficient":
        mechanisms.append(_mechanism("evidence_sufficiency", "final_input_insufficient", "manual_evidence_review"))
    if packaging_state in {"demonstrated_relevant_loss", "possible_noise_or_ordering_contribution"}:
        mechanisms.append(_mechanism("packaging", packaging_state, "packaging_audit"))
    if answerer_state != "indeterminate":
        mechanisms.append(_mechanism("answerer", answerer_state, "manual_answerer_review"))
    if evaluation_sensitive:
        mechanisms.append(_mechanism("evaluation", str(evaluation["primary_cause"]), "evaluation_disagreement_review"))
    if source_reference_mismatch:
        mechanisms.append(_mechanism(
            "evaluation", "source_reference_entity_mismatch", "manual_storage_fidelity_review"
        ))

    if bool(storage["store_specific_limitation_present"]):
        primary = {
            "primary_stage": "storage",
            "primary_cause": "storage_omission_or_distortion",
            "primary_rule_id": "S1_STORE_SPECIFIC_LIMITATION",
            "attribution_status": "resolved",
            "attribution_strength": "direct",
        }
    elif source_reference_mismatch:
        primary = {
            "primary_stage": "evaluation_sensitive",
            "primary_cause": "source_reference_entity_mismatch",
            "primary_rule_id": "S0_SOURCE_REFERENCE_MISMATCH_INVALIDATES_PIPELINE_BREAK",
            "attribution_status": "resolved",
            "attribution_strength": "bounded_manual_review",
        }
    elif (
        final_state == "insufficient"
        and packaging_state == "demonstrated_relevant_loss"
        and diag in {"complete_observation_incomplete_selection", "complete_selection_incomplete_bundle"}
    ):
        primary = {
            "primary_stage": "packaging",
            "primary_cause": "retrieval_budget_or_packaging",
            "primary_rule_id": "S2_COMPLETE_OBSERVATION_THEN_DEMONSTRATED_LOSS",
            "attribution_status": "resolved",
            "attribution_strength": "direct",
        }
    elif (
        final_state == "insufficient"
        and str(sufficiency["alternative_support_state"]) == "not_found_in_final_input"
        and diag in RETRIEVAL_BREAK_STATES
    ):
        primary = {
            "primary_stage": "retrieval",
            "primary_cause": RETRIEVAL_BREAK_STATES[diag],
            "primary_rule_id": "S3_INSUFFICIENT_AFTER_RETRIEVAL_BREAK",
            "attribution_status": "resolved",
            "attribution_strength": "convergent",
        }
    elif final_state == "sufficient" and answerer_state in {"misused_evidence", "unsupported_abstention"}:
        primary = {
            "primary_stage": "answerer",
            "primary_cause": "answerer_utilisation",
            "primary_rule_id": "S4_SUFFICIENT_INPUT_ANSWERER_FAILURE",
            "attribution_status": "resolved",
            "attribution_strength": "direct",
        }
    elif evaluation_sensitive:
        primary = {
            "primary_stage": "evaluation_sensitive",
            "primary_cause": "evaluation_disagreement",
            "primary_rule_id": "S5_REVIEWED_EVALUATION_SENSITIVITY",
            "attribution_status": "resolved",
            "attribution_strength": "bounded_manual_review",
        }
    elif final_state == "insufficient" and diag in {
        "complete_annotated_bundle_strict_noncorrect", "complete_selection_incomplete_bundle"
    }:
        primary = {
            "primary_stage": "mixed_or_indeterminate",
            "primary_cause": "mixed",
            "primary_rule_id": "S6_INSUFFICIENT_WITHOUT_DEMONSTRATED_ACCESS_BREAK",
            "attribution_status": "mixed",
            "attribution_strength": "indeterminate",
        }
    else:
        primary = {
            "primary_stage": "mixed_or_indeterminate",
            "primary_cause": "indeterminate",
            "primary_rule_id": "S7_NO_UNIQUE_SUPPORTED_BREAK",
            "attribution_status": "indeterminate",
            "attribution_strength": "indeterminate",
        }
    return primary, _deduplicate_mechanisms(mechanisms)


def _e7_attribution(
    *, e7: Mapping[str, Any], evaluation: Mapping[str, Any] | None,
    source_reference_mismatch: bool,
) -> tuple[dict[str, str], list[tuple[str, str, str]]]:
    mechanism_code = str(e7["fusion_mechanism"])
    mechanisms: list[tuple[str, str, str]] = []
    if mechanism_code != "indeterminate":
        if mechanism_code == "parent_retrieval_non_acquisition":
            group = "retrieval"
        elif mechanism_code in E7_ANSWERER_MECHANISMS:
            group = "answerer"
        elif mechanism_code in E7_EVALUATION_MECHANISMS:
            group = (
                "review_conflict"
                if evaluation is not None and not bool(evaluation["evaluation_sensitive"])
                else "evaluation"
            )
        else:
            group = "evidence_sufficiency"
        mechanisms.append(_mechanism(group, mechanism_code, "manual_e7_mechanism_review"))
    if str(e7["final_input_sufficiency_state"]) == "insufficient":
        mechanisms.append(_mechanism("evidence_sufficiency", "final_input_insufficient", "manual_e7_mechanism_review"))
    if str(e7["answerer_utilisation_state"]) != "indeterminate":
        mechanisms.append(_mechanism("answerer", str(e7["answerer_utilisation_state"]), "manual_e7_mechanism_review"))
    if str(e7["fusion_outcome"]) == "harm":
        mechanisms.append(_mechanism("fusion", "harm_outcome_with_exact_parent_item_preservation", "e7_outcome_and_exact_fusion_audit"))
    if bool(evaluation and evaluation["evaluation_sensitive"]):
        mechanisms.append(_mechanism("evaluation", str(evaluation["primary_cause"]), "evaluation_disagreement_review"))
    if source_reference_mismatch:
        mechanisms.append(_mechanism(
            "evaluation", "source_reference_entity_mismatch", "manual_storage_fidelity_review"
        ))

    if source_reference_mismatch:
        primary = {
            "primary_stage": "evaluation_sensitive",
            "primary_cause": "source_reference_entity_mismatch",
            "primary_rule_id": "E7_0_SOURCE_REFERENCE_MISMATCH_INVALIDATES_PARENT_BREAK",
            "attribution_status": "resolved",
            "attribution_strength": "bounded_manual_review",
        }
    elif mechanism_code == "parent_retrieval_non_acquisition":
        primary = {
            "primary_stage": "retrieval",
            "primary_cause": "retrieval_navigation_or_ranking",
            "primary_rule_id": "E7_1_PARENT_RETRIEVAL_NON_ACQUISITION",
            "attribution_status": "resolved",
            "attribution_strength": "convergent",
        }
    elif mechanism_code in E7_ANSWERER_MECHANISMS:
        primary = {
            "primary_stage": "answerer",
            "primary_cause": "answerer_utilisation",
            "primary_rule_id": "E7_2_SUFFICIENT_FUSED_INPUT_ANSWERER_FAILURE",
            "attribution_status": "resolved",
            "attribution_strength": "direct",
        }
    elif mechanism_code in E7_EVALUATION_MECHANISMS and not (
        evaluation is not None and not bool(evaluation["evaluation_sensitive"])
    ):
        primary = {
            "primary_stage": "evaluation_sensitive",
            "primary_cause": "evaluation_disagreement",
            "primary_rule_id": "E7_3_MANUAL_EVALUATION_SENSITIVITY",
            "attribution_status": "resolved",
            "attribution_strength": "bounded_manual_review",
        }
    elif mechanism_code == "upstream_semantic_insufficiency" or (
        mechanism_code in E7_EVALUATION_MECHANISMS
        and evaluation is not None
        and not bool(evaluation["evaluation_sensitive"])
    ):
        primary = {
            "primary_stage": "mixed_or_indeterminate",
            "primary_cause": "mixed",
            "primary_rule_id": (
                "E7_4_LATER_EVALUATION_REVIEW_OVERRIDES_SENSITIVITY"
                if mechanism_code in E7_EVALUATION_MECHANISMS
                else "E7_4_PARENT_SEMANTIC_INSUFFICIENCY_WITHOUT_UNIQUE_BREAK"
            ),
            "attribution_status": "mixed",
            "attribution_strength": "indeterminate",
        }
    else:
        primary = {
            "primary_stage": "mixed_or_indeterminate",
            "primary_cause": "indeterminate",
            "primary_rule_id": "E7_5_NO_UNIQUE_SUPPORTED_BREAK",
            "attribution_status": "indeterminate",
            "attribution_strength": "indeterminate",
        }
    return primary, _deduplicate_mechanisms(mechanisms)


def _full_context_attribution(
    *, full_context: Mapping[str, Any], evaluation: Mapping[str, Any] | None,
    source_reference_mismatch: bool,
) -> tuple[dict[str, str], list[tuple[str, str, str]]]:
    long_state = str(full_context["long_context_utilisation_state"])
    answerer_state = str(full_context["answerer_utilisation_state"])
    primary_mechanism = str(full_context["primary_mechanism"])
    evaluation_sensitive = bool(evaluation and evaluation["evaluation_sensitive"])
    mechanisms: list[tuple[str, str, str]] = [
        _mechanism("full_context_diagnostic", primary_mechanism, "manual_full_context_review")
    ]
    if long_state in LONG_CONTEXT_BREAK_STATES:
        mechanisms.append(_mechanism("long_context", long_state, "manual_full_context_review"))
    if answerer_state != "indeterminate":
        mechanisms.append(_mechanism("answerer", answerer_state, "manual_full_context_review"))
    if evaluation_sensitive:
        mechanisms.append(_mechanism("evaluation", str(evaluation["primary_cause"]), "evaluation_disagreement_review"))
    if source_reference_mismatch:
        mechanisms.append(_mechanism(
            "evaluation", "source_reference_entity_mismatch", "manual_storage_fidelity_review"
        ))
    if primary_mechanism.startswith("source_"):
        mechanisms.append(_mechanism("source_reference", primary_mechanism, "manual_full_context_review"))

    if source_reference_mismatch:
        primary = {
            "primary_stage": "evaluation_sensitive",
            "primary_cause": "source_reference_entity_mismatch",
            "primary_rule_id": "FC_0_SOURCE_REFERENCE_MISMATCH_INVALIDATES_CONTEXT_BREAK",
            "attribution_status": "resolved",
            "attribution_strength": "bounded_manual_review",
        }
    elif long_state in LONG_CONTEXT_BREAK_STATES:
        primary = {
            "primary_stage": "fusion_or_long_context",
            "primary_cause": "long_context_utilisation",
            "primary_rule_id": "FC_1_LONG_CONTEXT_LOCALISATION_OR_INTERFERENCE",
            "attribution_status": "resolved",
            "attribution_strength": "direct",
        }
    elif long_state == "successful" and answerer_state in {"misused_evidence", "unsupported_abstention"}:
        primary = {
            "primary_stage": "answerer",
            "primary_cause": "answerer_utilisation",
            "primary_rule_id": "FC_2_SUCCESSFUL_LOCALISATION_ANSWERER_FAILURE",
            "attribution_status": "resolved",
            "attribution_strength": "direct",
        }
    elif evaluation_sensitive:
        primary = {
            "primary_stage": "evaluation_sensitive",
            "primary_cause": "evaluation_disagreement",
            "primary_rule_id": "FC_3_REVIEWED_EVALUATION_SENSITIVITY",
            "attribution_status": "resolved",
            "attribution_strength": "bounded_manual_review",
        }
    elif primary_mechanism in {"source_question_entity_mismatch", "source_reference_temporal_ambiguity"}:
        primary = {
            "primary_stage": "mixed_or_indeterminate",
            "primary_cause": "mixed",
            "primary_rule_id": "FC_4_SOURCE_REFERENCE_AMBIGUITY_WITHOUT_UNIQUE_BREAK",
            "attribution_status": "mixed",
            "attribution_strength": "indeterminate",
        }
    else:
        primary = {
            "primary_stage": "mixed_or_indeterminate",
            "primary_cause": "indeterminate",
            "primary_rule_id": "FC_5_NO_UNIQUE_SUPPORTED_BREAK",
            "attribution_status": "indeterminate",
            "attribution_strength": "indeterminate",
        }
    return primary, _deduplicate_mechanisms(mechanisms)


def _build_attributions(indexes: Mapping[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    output: list[dict[str, Any]] = []
    mechanism_rows: list[dict[str, Any]] = []
    source_reference_mismatch_questions = {
        str(row["question_id"])
        for row in indexes["storage"].values()
        if str(row["store_availability_state"]) == "available_with_reference_entity_mismatch"
    }
    for key, base in sorted(indexes["errors"].items(), key=lambda item: int(item[1]["error_order"])):
        row_id = key[0]
        state = indexes["state"][(row_id,)]
        condition = str(base["condition_id"])
        source_reference_mismatch = str(base["question_id"]) in source_reference_mismatch_questions
        evaluation = _evaluation_details(row_id, indexes["evaluation"])
        if condition in SELECTIVE_CONDITIONS:
            storage = indexes["storage"][(str(base["case_id"]),)]
            retrieval = indexes["retrieval"][(row_id,)]
            sufficiency = indexes["sufficiency"][(row_id,)]
            packaging = indexes["packaging"][(row_id,)]
            answerer = indexes["answerer"][(row_id,)]
            primary, mechanisms = _selective_attribution(
                base=base, state=state, storage=storage, retrieval=retrieval,
                sufficiency=sufficiency, packaging=packaging, answerer=answerer,
                evaluation=evaluation,
            )
            access_regime = "selective_retrieval"
            store_id = str(storage["store_id"])
            retriever_id = str(retrieval["retriever_id"])
            diagnostic_state = str(retrieval["diagnostic_retrieval_state"])
            final_sufficiency = str(sufficiency["final_input_sufficiency_state"])
            answerer_state = str(answerer["answerer_utilisation_state"])
            fusion_outcome = "not_applicable"
            long_context_state = "not_applicable"
            explicit_evaluation_sensitivity = (
                bool(evaluation and evaluation["evaluation_sensitive"])
                or source_reference_mismatch
            )
        elif condition == FUSED_CONDITION:
            e7 = indexes["e7"][(str(base["packet_backbone"]), str(base["question_id"]))]
            primary, mechanisms = _e7_attribution(
                e7=e7,
                evaluation=evaluation,
                source_reference_mismatch=source_reference_mismatch,
            )
            access_regime = "dual_source_fusion"
            store_id = "S1_plus_S3"
            retriever_id = "R2_plus_R3_reused"
            diagnostic_state = "parent_bundle_reuse"
            final_sufficiency = str(e7["final_input_sufficiency_state"])
            answerer_state = str(e7["answerer_utilisation_state"])
            fusion_outcome = str(e7["fusion_outcome"])
            long_context_state = "not_applicable"
            explicit_evaluation_sensitivity = (
                source_reference_mismatch
                or bool(evaluation and evaluation["evaluation_sensitive"])
                or (
                    str(e7["fusion_mechanism"]) in E7_EVALUATION_MECHANISMS
                    and not (evaluation is not None and not bool(evaluation["evaluation_sensitive"]))
                )
            )
        else:
            _require(condition == FULL_CONTEXT_CONDITION, "Unexpected integrated condition")
            full_context = indexes["full_context"][(row_id,)]
            primary, mechanisms = _full_context_attribution(
                full_context=full_context,
                evaluation=evaluation,
                source_reference_mismatch=source_reference_mismatch,
            )
            access_regime = "full_context"
            store_id = "all_30_raw_sessions"
            retriever_id = "not_applicable"
            diagnostic_state = "not_applicable"
            final_sufficiency = str(full_context["final_input_sufficiency_state"])
            answerer_state = str(full_context["answerer_utilisation_state"])
            fusion_outcome = "not_applicable"
            long_context_state = str(full_context["long_context_utilisation_state"])
            explicit_evaluation_sensitivity = (
                bool(evaluation and evaluation["evaluation_sensitive"])
                or source_reference_mismatch
            )

        primary_group_codes = {
            (group, code) for group, code, _ in mechanisms
            if (
                (primary["primary_stage"] == "retrieval" and group == "retrieval")
                or (primary["primary_stage"] == "packaging" and group == "packaging")
                or (primary["primary_stage"] == "answerer" and group == "answerer")
                or (primary["primary_stage"] == "fusion_or_long_context" and group in {"fusion", "long_context"})
                or (primary["primary_stage"] == "evaluation_sensitive" and group == "evaluation")
                or (primary["primary_stage"] == "storage" and group == "storage_representation")
            )
        }
        secondary = [code for group, code, _ in mechanisms if (group, code) not in primary_group_codes]
        body = {
            "protocol_version": PROTOCOL_VERSION,
            "analysis_row_id": row_id,
            "case_id": str(base["case_id"]),
            "error_order": int(base["error_order"]),
            "packet_backbone": str(base["packet_backbone"]),
            "condition_id": condition,
            "question_id": str(base["question_id"]),
            "category_name": str(base["category_name"]),
            "judge_label": str(base["judge_label"]),
            "access_regime": access_regime,
            "store_id": store_id,
            "retriever_id": retriever_id,
            "diagnostic_retrieval_state": diagnostic_state,
            "final_input_sufficiency_state": final_sufficiency,
            "answerer_utilisation_state": answerer_state,
            "fusion_outcome": fusion_outcome,
            "long_context_utilisation_state": long_context_state,
            "evaluation_screened": evaluation is not None,
            "evaluation_audit_sensitive": bool(evaluation and evaluation["evaluation_sensitive"]),
            "explicit_evaluation_sensitivity": explicit_evaluation_sensitivity,
            **primary,
            "secondary_mechanisms": secondary,
            "supported_mechanism_count": len(mechanisms),
        }
        attribution = {"attribution_id": _artifact_id("rq5-integrated-case-", body), **body}
        output.append(attribution)
        for group, code, basis in mechanisms:
            is_primary = (group, code) in primary_group_codes
            mechanism_body = {
                "protocol_version": PROTOCOL_VERSION,
                "attribution_id": attribution["attribution_id"],
                "analysis_row_id": row_id,
                "case_id": attribution["case_id"],
                "packet_backbone": attribution["packet_backbone"],
                "condition_id": condition,
                "category_name": attribution["category_name"],
                "access_regime": access_regime,
                "retriever_id": retriever_id,
                "primary_stage": primary["primary_stage"],
                "mechanism_group": group,
                "mechanism_code": code,
                "mechanism_role": "primary_support" if is_primary else "co_occurring",
                "evidence_basis": basis,
            }
            mechanism_rows.append({"mechanism_id": _artifact_id("rq5-mechanism-", mechanism_body), **mechanism_body})
    _require(len(output) == EXPECTED_ROWS, "Integrated attribution count differs")
    _require(len({row["analysis_row_id"] for row in output}) == EXPECTED_ROWS, "Integrated identities repeat")
    _require(all(row["primary_stage"] in PRIMARY_STAGE_ORDER for row in output), "Unknown primary stage")
    _require(all(row["primary_cause"] != "pending" for row in output), "A primary cause remains pending")
    return output, mechanism_rows


def _summary_rows(attributions: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    scopes: list[tuple[str, str, list[Mapping[str, Any]]]] = [("overall", "ALL", list(attributions))]
    for field, scope_type in (
        ("access_regime", "access_regime"),
        ("packet_backbone", "backbone"),
        ("condition_id", "condition"),
        ("category_name", "category"),
        ("retriever_id", "retriever"),
    ):
        for value in sorted({str(row[field]) for row in attributions}):
            if field == "retriever_id" and value == "not_applicable":
                continue
            scopes.append((scope_type, value, [row for row in attributions if str(row[field]) == value]))
    output: list[dict[str, Any]] = []
    for scope_type, scope_value, rows in scopes:
        denominator = len(rows)
        counts = Counter(str(row["primary_stage"]) for row in rows)
        for stage in PRIMARY_STAGE_ORDER:
            body = {
                "protocol_version": PROTOCOL_VERSION,
                "scope_type": scope_type,
                "scope_value": scope_value,
                "primary_stage": stage,
                "primary_stage_order": PRIMARY_STAGE_ORDER[stage],
                "count": counts[stage],
                "denominator": denominator,
                "rate": counts[stage] / denominator,
            }
            output.append({"summary_id": _artifact_id("rq5-primary-summary-", body), **body})
    return output


def _mechanism_summary_rows(
    attributions: Sequence[Mapping[str, Any]], mechanisms: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    by_id = {str(row["attribution_id"]): row for row in attributions}
    scopes = [("overall", "ALL", set(by_id))]
    for field, scope_type in (
        ("access_regime", "access_regime"),
        ("packet_backbone", "backbone"),
        ("condition_id", "condition"),
        ("category_name", "category"),
        ("retriever_id", "retriever"),
    ):
        for value in sorted({str(row[field]) for row in attributions}):
            if field == "retriever_id" and value == "not_applicable":
                continue
            scopes.append((scope_type, value, {str(row["attribution_id"]) for row in attributions if str(row[field]) == value}))
    output: list[dict[str, Any]] = []
    groups = sorted({str(row["mechanism_group"]) for row in mechanisms})
    for scope_type, scope_value, ids in scopes:
        for group in groups:
            group_rows = [
                row for row in mechanisms
                if str(row["attribution_id"]) in ids and str(row["mechanism_group"]) == group
            ]
            codes = ["ANY", *sorted({str(row["mechanism_code"]) for row in group_rows})]
            for code in codes:
                selected = {
                    str(row["attribution_id"]) for row in group_rows
                    if code == "ANY" or str(row["mechanism_code"]) == code
                }
                body = {
                    "protocol_version": PROTOCOL_VERSION,
                    "scope_type": scope_type,
                    "scope_value": scope_value,
                    "mechanism_group": group,
                    "mechanism_code": code,
                    "case_count": len(selected),
                    "denominator": len(ids),
                    "rate": len(selected) / len(ids),
                }
                output.append({"summary_id": _artifact_id("rq5-mechanism-summary-", body), **body})
    return output


def _primary_secondary_matrix(
    attributions: Sequence[Mapping[str, Any]], mechanisms: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    primary = {str(row["attribution_id"]): str(row["primary_stage"]) for row in attributions}
    grouped: dict[tuple[str, str], set[str]] = defaultdict(set)
    for row in mechanisms:
        if row["mechanism_role"] == "co_occurring":
            grouped[(primary[str(row["attribution_id"])], str(row["mechanism_group"]))].add(str(row["attribution_id"]))
    stage_totals = Counter(primary.values())
    output: list[dict[str, Any]] = []
    for stage in PRIMARY_STAGE_ORDER:
        groups = sorted({group for candidate, group in grouped if candidate == stage})
        for group in groups:
            count = len(grouped[(stage, group)])
            body = {
                "protocol_version": PROTOCOL_VERSION,
                "primary_stage": stage,
                "cooccurring_mechanism_group": group,
                "case_count": count,
                "primary_stage_denominator": stage_totals[stage],
                "rate_within_primary_stage": count / stage_totals[stage],
            }
            output.append({"matrix_id": _artifact_id("rq5-primary-secondary-", body), **body})
    return output


def _representative_cases(
    attributions: Sequence[Mapping[str, Any]], mechanisms: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    mechanism_codes: dict[str, set[str]] = defaultdict(set)
    for row in mechanisms:
        mechanism_codes[str(row["attribution_id"])].add(str(row["mechanism_code"]))

    # These six cases were selected only after trace-level content review.  The
    # predicates intentionally bind the reviewed question and path, rather than
    # taking the first machine-labelled row and risking a confounded example.
    specifications = (
        ("r1_sufficient_bundle_answerer_failure", lambda row: (
            row["packet_backbone"] == "qwen" and row["condition_id"] == "E1"
            and row["question_id"] == "conv-50-q037" and row["primary_stage"] == "answerer"
        )),
        ("r2_retrieval_break", lambda row: (
            row["packet_backbone"] == "qwen" and row["condition_id"] == "E2"
            and row["question_id"] == "conv-50-q022" and row["primary_stage"] == "retrieval"
        )),
        ("r3_packaging_break", lambda row: (
            row["packet_backbone"] == "qwen" and row["condition_id"] == "E6"
            and row["question_id"] == "conv-50-q052" and row["primary_stage"] == "packaging"
        )),
        ("evaluation_sensitive_source_reference_mismatch", lambda row: (
            row["packet_backbone"] == "qwen" and row["condition_id"] == "E1"
            and row["question_id"] == "conv-50-q089"
            and row["primary_stage"] == "evaluation_sensitive"
        )),
        ("e7_harm_without_item_loss", lambda row: (
            row["packet_backbone"] == "qwen" and row["condition_id"] == "E7"
            and row["question_id"] == "conv-50-q051" and row["fusion_outcome"] == "harm"
        )),
        ("full_context_localisation_or_interference", lambda row: (
            row["packet_backbone"] == "deepseek" and row["condition_id"] == "B3-FullContext"
            and row["question_id"] == "conv-50-q019"
            and row["primary_stage"] == "fusion_or_long_context"
        )),
    )
    output: list[dict[str, Any]] = []
    used: set[str] = set()
    for order, (role, predicate) in enumerate(specifications, start=1):
        candidates = [row for row in attributions if predicate(row) and row["attribution_id"] not in used]
        _require(bool(candidates), f"No representative candidate for {role}")
        candidates.sort(key=lambda row: (int(row["error_order"]), str(row["attribution_id"])))
        row = candidates[0]
        used.add(str(row["attribution_id"]))
        body = {
            "protocol_version": PROTOCOL_VERSION,
            "case_role_order": order,
            "case_role": role,
            "attribution_id": row["attribution_id"],
            "analysis_row_id": row["analysis_row_id"],
            "case_id": row["case_id"],
            "packet_backbone": row["packet_backbone"],
            "condition_id": row["condition_id"],
            "question_id": row["question_id"],
            "category_name": row["category_name"],
            "store_id": row["store_id"],
            "retriever_id": row["retriever_id"],
            "primary_stage": row["primary_stage"],
            "primary_cause": row["primary_cause"],
            "primary_rule_id": row["primary_rule_id"],
            "mechanism_codes": sorted(mechanism_codes[str(row["attribution_id"])]),
            "requires_prose_content_review_before_publication": True,
        }
        output.append({"representative_id": _artifact_id("rq5-representative-", body), **body})
    return output


def _final_state_register(
    states: Mapping[tuple[str, ...], Mapping[str, Any]], attributions: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    by_id = {str(row["analysis_row_id"]): row for row in attributions}
    output: list[dict[str, Any]] = []
    for key, source in sorted(states.items(), key=lambda item: int(item[1]["state_order"])):
        row_id = key[0]
        attribution = by_id[row_id]
        updated = dict(source)
        updated.update({
            "primary_cause": attribution["primary_cause"],
            "secondary_causes": attribution["secondary_mechanisms"],
            "attribution_status": attribution["attribution_status"],
            "attribution_strength": attribution["attribution_strength"],
            "causal_sufficiency": (
                "supported_primary_break"
                if attribution["attribution_status"] == "resolved"
                else "not_uniquely_established"
            ),
            "evaluation_agreement_state": (
                "evaluation_sensitive"
                if attribution["explicit_evaluation_sensitivity"]
                else "reviewed_not_sensitive"
                if attribution["evaluation_screened"]
                else "not_screened"
            ),
            "primary_stage": attribution["primary_stage"],
            "primary_rule_id": attribution["primary_rule_id"],
            "integration_protocol_version": PROTOCOL_VERSION,
        })
        output.append(updated)
    _require(len(output) == EXPECTED_ROWS, "Final state-register count differs")
    _require(all(row["primary_cause"] != "pending" for row in output), "Final state register contains pending causes")
    return output


def _assert_text_free(tables: Mapping[str, Sequence[Mapping[str, Any]]]) -> None:
    def inspect(value: Any, table: str) -> None:
        if isinstance(value, Mapping):
            for key, nested in value.items():
                _require(str(key).casefold() not in FORBIDDEN_FIELDS, f"Forbidden content field in {table}: {key}")
                inspect(nested, table)
        elif isinstance(value, (list, tuple)):
            for nested in value:
                inspect(nested, table)
    for table, rows in tables.items():
        inspect(rows, table)


def _core(root: Path) -> tuple[dict[str, list[dict[str, Any]]], dict[str, Any]]:
    indexes, metadata = _load_inputs(root)
    attributions, mechanisms = _build_attributions(indexes)
    tables = {
        "integrated-attributions": attributions,
        "case-mechanisms": mechanisms,
        "primary-root-cause-summary": _summary_rows(attributions),
        "cooccurring-mechanism-summary": _mechanism_summary_rows(attributions, mechanisms),
        "primary-secondary-matrix": _primary_secondary_matrix(attributions, mechanisms),
        "representative-cases": _representative_cases(attributions, mechanisms),
        "root-cause-state-register-final": _final_state_register(indexes["state"], attributions),
    }
    _assert_text_free(tables)
    return tables, metadata


def _diagnostics(tables: Mapping[str, Sequence[Mapping[str, Any]]]) -> dict[str, Any]:
    rows = tables["integrated-attributions"]
    mechanisms = tables["case-mechanisms"]
    counts = Counter(str(row["primary_stage"]) for row in rows)
    access = Counter(str(row["access_regime"]) for row in rows)
    status = Counter(str(row["attribution_status"]) for row in rows)
    evaluation_screened = sum(bool(row["evaluation_screened"]) for row in rows)
    evaluation_audit_sensitive = sum(bool(row["evaluation_audit_sensitive"]) for row in rows)
    explicit_evaluation_sensitive = sum(bool(row["explicit_evaluation_sensitivity"]) for row in rows)
    e7_harm = [row for row in rows if row["condition_id"] == "E7" and row["fusion_outcome"] == "harm"]
    expected_primary = {
        "storage": 0,
        "retrieval": 42,
        "packaging": 7,
        "answerer": 68,
        "fusion_or_long_context": 6,
        "evaluation_sensitive": 53,
        "mixed_or_indeterminate": 74,
    }
    _require({stage: counts[stage] for stage in PRIMARY_STAGE_ORDER} == expected_primary, "Integrated primary-cause census differs")
    _require(
        access == Counter({"selective_retrieval": 205, "dual_source_fusion": 31, "full_context": 14}),
        "Integrated access-regime census differs",
    )
    mechanism_ids: dict[tuple[str, str | None], set[str]] = defaultdict(set)
    for row in mechanisms:
        mechanism_ids[(str(row["mechanism_group"]), None)].add(str(row["attribution_id"]))
        mechanism_ids[(str(row["mechanism_group"]), str(row["mechanism_code"]))].add(str(row["attribution_id"]))
    expected_mechanisms = {
        ("retrieval", None): 76,
        ("packaging", "demonstrated_relevant_loss"): 9,
        ("packaging", "possible_noise_or_ordering_contribution"): 42,
        ("answerer", None): 74,
        ("long_context", None): 6,
        ("evaluation", None): 74,
        ("storage_representation", None): 12,
    }
    for key, expected in expected_mechanisms.items():
        _require(len(mechanism_ids[key]) == expected, f"Integrated mechanism census differs: {key}")
    return {
        "population_rows": len(rows),
        "access_regime_counts": dict(sorted(access.items())),
        "primary_stage_counts": {stage: counts[stage] for stage in PRIMARY_STAGE_ORDER},
        "attribution_status_counts": dict(sorted(status.items())),
        "evaluation_screened_strict_noncorrect_rows": evaluation_screened,
        "evaluation_audit_sensitive_strict_noncorrect_rows": evaluation_audit_sensitive,
        "explicit_evaluation_sensitive_rows_after_branch_review": explicit_evaluation_sensitive,
        "unscreened_rows_are_not_treated_as_agreement": True,
        "confirmed_store_specific_primary_failures": counts["storage"],
        "confirmed_fusion_operation_primary_failures": sum(
            row["primary_stage"] == "fusion_or_long_context" and row["access_regime"] == "dual_source_fusion"
            for row in rows
        ),
        "e7_harm_outcomes": len(e7_harm),
        "e7_harm_is_not_automatic_fusion_causation": True,
        "representative_case_count": len(tables["representative-cases"]),
    }


def _source_manifest(root: Path, metadata: Mapping[str, Any]) -> dict[str, Any]:
    fixed = [
        root / STAGE1_DIR / "audit.json",
        root / STAGE1_DIR / "RQ5-STAGE-1.PASSED",
        root / STORAGE_DIR / "audit.json",
        root / STORAGE_DIR / "RQ5-STORAGE-AUDIT.PASSED",
        root / RETRIEVAL_DIR / "audit.json",
        root / RETRIEVAL_DIR / "RQ5-RETRIEVAL-AUDIT.PASSED",
        root / DOWNSTREAM_DIR / "audit.json",
        root / DOWNSTREAM_DIR / "RQ5-DOWNSTREAM.PASSED",
        root / FULL_CONTEXT_DIR / "audit.json",
        root / FULL_CONTEXT_DIR / "RQ5-FULL-CONTEXT.PASSED",
        root / EVALUATION_DIR / "audit.json",
        root / EVALUATION_DIR / "RQ5-EVALUATION.PASSED",
        root / EVALUATION_REVIEW_PATH,
        *metadata["paths"].values(),
    ]
    unique = list(dict.fromkeys(Path(path).resolve() for path in fixed))
    files = [_artifact(root, path) for path in unique]
    upstream = {
        role: {key: value for key, value in audit.items() if key in {"protocol_version", "audit_id", "status"}}
        for role, audit in sorted(metadata["upstream"].items())
    }
    body = {
        "protocol_version": PROTOCOL_VERSION,
        "upstream_audits": upstream,
        "files": files,
        "no_api_calls": True,
        "no_network_calls": True,
        "formal_source_mutation": False,
    }
    return {"source_manifest_id": _artifact_id("rq5-integrated-sources-", body), **body}


def _schema(tables: Mapping[str, Sequence[Mapping[str, Any]]]) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "protocol_version": PROTOCOL_VERSION,
        "scope": "Chapter 5 Section 5.6.6 integrated bottleneck decomposition and answer to RQ5",
        "primary_rule": "earliest supported necessary break in the applicable information chain",
        "primary_stage_order": dict(PRIMARY_STAGE_ORDER),
        "condition_specific_chains": {
            "E1-E6": ["storage", "retrieval", "packaging", "answerer", "evaluation_sensitive"],
            "E7": ["parent_upstream", "fusion", "answerer", "evaluation_sensitive"],
            "B3-FullContext": ["full_history_localisation", "answerer", "evaluation_sensitive"],
        },
        "interpretive_guards": {
            "retrieval_diagnostic_is_not_automatic_causation": True,
            "misaligned_gold_locator_is_not_a_valid_retrieval_failure_test": True,
            "e7_harm_is_not_automatic_fusion_causation": True,
            "unscreened_evaluation_is_not_agreement": True,
            "shared_representation_issue_is_not_store_specific_failure": True,
        },
        "tables": {name: {"rows": len(rows), "fields": list(rows[0]) if rows else []} for name, rows in tables.items()},
        "public_tables_are_text_free": True,
    }


def _readme(diagnostics: Mapping[str, Any]) -> bytes:
    counts = diagnostics["primary_stage_counts"]
    lines = [
        "# RQ5 Integrated Bottleneck Decomposition",
        "",
        "This directory contains the audited offline integration for Section 5.6.6.",
        "It assigns one primary breakpoint to each Strict-noncorrect path and records",
        "supported co-occurring mechanisms separately.",
        "",
        "Primary cause counts:",
        "",
    ]
    lines.extend(f"- `{stage}`: {counts[stage]}" for stage in PRIMARY_STAGE_ORDER)
    lines.extend([
        "",
        "Important guards:",
        "",
        "- retrieval diagnostics are not treated as causation without final-input insufficiency;",
        "- a source/reference entity mismatch invalidates retrieval-failure attribution based on that locator;",
        "- E7 harm is not automatically assigned to the fusion operation;",
        "- unscreened evaluation cases are not treated as evaluator agreement;",
        "- the 12 shared representation limitations are not store-specific failures.",
        "",
        "No model, API, or network call is used by this stage.",
        "",
    ])
    return "\n".join(lines).encode("utf-8")


def _payloads(
    tables: Mapping[str, Sequence[Mapping[str, Any]]], diagnostics: Mapping[str, Any],
    manifest: Mapping[str, Any],
) -> dict[str, bytes]:
    output: dict[str, bytes] = {}
    for name in TABLES:
        output[f"{name}.jsonl"] = _jsonl_payload(tables[name])
        output[f"{name}.csv"] = _csv_payload(tables[name])
    output["diagnostics.json"] = canonical_json_bytes(dict(diagnostics)) + b"\n"
    output["schema.json"] = canonical_json_bytes(_schema(tables)) + b"\n"
    output["source-manifest.json"] = canonical_json_bytes(dict(manifest)) + b"\n"
    output["README.md"] = _readme(diagnostics)
    return output


def _audit_body(
    diagnostics: Mapping[str, Any], manifest: Mapping[str, Any], output_hashes: Mapping[str, str],
) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "protocol_version": PROTOCOL_VERSION,
        "status": "passed",
        "scope": "RQ5 Section 5.6.6 integrated primary and co-occurring bottleneck decomposition",
        "source_manifest_id": manifest["source_manifest_id"],
        "diagnostics": dict(diagnostics),
        "output_sha256": dict(sorted(output_hashes.items())),
        "primary_attribution_computed": True,
        "cooccurring_mechanisms_computed": True,
        "no_api_calls": True,
        "no_network_calls": True,
        "formal_source_mutation": False,
        "public_tables_are_text_free": True,
    }


def _marker(audit: Mapping[str, Any], audit_sha256: str) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "protocol_version": PROTOCOL_VERSION,
        "status": "passed",
        "audit_id": audit["audit_id"],
        "audit_sha256": audit_sha256,
        "population_rows": EXPECTED_ROWS,
        "primary_attribution_computed": True,
        "no_api_calls": True,
        "no_network_calls": True,
    }


def audit_rq5_integrated(*, repo_root: Path, output_dir: Path) -> dict[str, Any]:
    root, output = Path(repo_root).resolve(), Path(output_dir).resolve()
    _require(output.is_dir() and not output.is_symlink(), "Integrated output directory is unsafe")
    tables, metadata = _core(root)
    diagnostics = _diagnostics(tables)
    manifest = _source_manifest(root, metadata)
    payloads = _payloads(tables, diagnostics, manifest)
    hashes = {name: hashlib.sha256(payload).hexdigest() for name, payload in sorted(payloads.items())}
    body = _audit_body(diagnostics, manifest, hashes)
    audit = {"audit_id": _artifact_id("rq5-integrated-audit-", body), **body}
    audit_payload = canonical_json_bytes(audit) + b"\n"
    marker_payload = canonical_json_bytes(_marker(audit, hashlib.sha256(audit_payload).hexdigest())) + b"\n"
    expected_names = set(payloads) | {"audit.json", "RQ5-INTEGRATED.PASSED"}
    entries = list(output.iterdir())
    _require(all(path.is_file() and not path.is_symlink() for path in entries), "Integrated output contains an unsafe entry")
    _require({path.name for path in entries} == expected_names, "Integrated output file set differs")
    for name, payload in payloads.items():
        _require((output / name).read_bytes() == payload, f"Integrated artifact differs: {name}")
    _require((output / "audit.json").read_bytes() == audit_payload, "Integrated audit differs")
    _require((output / "RQ5-INTEGRATED.PASSED").read_bytes() == marker_payload, "Integrated marker differs")
    return audit


def build_rq5_integrated(*, repo_root: Path, output_dir: Path) -> dict[str, Any]:
    root, destination = Path(repo_root).resolve(), Path(output_dir).resolve()
    _require(root.is_dir() and not root.is_symlink(), "Repository root is unsafe")
    _require(not destination.exists(), "Integrated output already exists")
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=f".{destination.name}.in-progress-", dir=destination.parent))
    try:
        tables, metadata = _core(root)
        diagnostics = _diagnostics(tables)
        manifest = _source_manifest(root, metadata)
        payloads = _payloads(tables, diagnostics, manifest)
        for name, payload in payloads.items():
            _write(temporary / name, payload)
        hashes = {name: _sha256_file(temporary / name) for name in sorted(payloads)}
        body = _audit_body(diagnostics, manifest, hashes)
        audit = {"audit_id": _artifact_id("rq5-integrated-audit-", body), **body}
        _write(temporary / "audit.json", canonical_json_bytes(audit) + b"\n")
        _write(
            temporary / "RQ5-INTEGRATED.PASSED",
            canonical_json_bytes(_marker(audit, _sha256_file(temporary / "audit.json"))) + b"\n",
        )
        audited = audit_rq5_integrated(repo_root=root, output_dir=temporary)
        _require(audited["status"] == "passed", "Pre-publication integrated audit failed")
        os.rename(temporary, destination)
        descriptor = os.open(destination.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
    except Exception:
        shutil.rmtree(temporary, ignore_errors=True)
        raise
    return audit_rq5_integrated(repo_root=root, output_dir=destination)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("build", "audit"))
    parser.add_argument("--repo-root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--output-dir", type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    root = args.repo_root.resolve()
    output = (args.output_dir or root / DEFAULT_OUTPUT_DIR).resolve()
    result = (
        build_rq5_integrated(repo_root=root, output_dir=output)
        if args.command == "build"
        else audit_rq5_integrated(repo_root=root, output_dir=output)
    )
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
