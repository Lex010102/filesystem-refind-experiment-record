"""Finalize the bounded Chapter 5 Stage D trace review.

The automatic Stage D artifact freezes 24 identifier-only candidates.  This
module accepts a completed, human-authored review register for exactly those
candidates, validates the reviewed sources, and publishes a separate final
artifact.  The automatic artifact and the formal Stage A--C inputs are never
modified.

The final artifact keeps every automatic file byte-for-byte, then adds a
text-free review register, a concise paraphrased casebook, an independently
rebuildable final audit, and ``STAGE-D.PASSED``.  The case review is bounded
qualitative evidence; it is not an error-prevalence census or a final RQ1
conclusion.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import tempfile
from collections import Counter
from pathlib import Path, PurePosixPath
from typing import Any, Mapping, Sequence

from .chapter5_stage_b import (
    BACKBONES,
    _csv_payload,
    _jsonl_payload,
    _read_json,
    _read_jsonl,
    _relative,
    _require,
    _sha256_file,
    _write,
)
from .chapter5_stage_d import STAGE_D_PROTOCOL_VERSION, audit_stage_d_output
from .evidence import canonical_json_bytes, sha256_bytes


STAGE_D_REVIEW_PROTOCOL_VERSION = "chapter5-main60-stage-d-review-v1"
EXPECTED_AUTO_AUDIT_ID = (
    "stage-d-auto-audit-"
    "9cfae91b0639df31b427d2052798dfe30e0f5cb8b41c9996ae75448e6fdd4a4f"
)
EXPECTED_AUTO_AUDIT_SHA256 = (
    "234323fbc22a39b51044d50866ff7b1e3b60acb1b8aad3622d2ddac942ba57e9"
)
EXPECTED_CANDIDATE_SHA256 = (
    "475d406413461d7564619fc0b5c384d61c965d24299471d09611f1e612aa11c6"
)
EXPECTED_REVIEW_COUNT = 24

MODULES = ("5.2.1", "5.2.2", "5.2.3", "5.2.4")
ROLES = ("repair", "harm", "counterexample")
OBSERVED_CASE_TYPES = {
    "repair",
    "harm",
    "counterexample",
    "metric_disagreement",
    "mixed",
    "ambiguous",
}
STORAGE_STATUSES = {"preserved", "omitted", "distorted", "not_applicable", "uncertain"}
RETRIEVAL_STATUSES = {"sufficient", "partial", "missed", "noisy", "not_applicable", "uncertain"}
PACKAGING_STATUSES = {"preserved", "partial_loss", "budget_loss", "not_applicable", "uncertain"}
EVIDENCE_STATUSES = {"sufficient", "partial", "insufficient", "uncertain"}
ANSWERER_STATUSES = {"correct_use", "partial_use", "failed_use", "not_assessable"}
EVALUATION_STATUSES = {
    "agreement",
    "token_semantic_disagreement",
    "judge_uncertain",
    "not_assessable",
}
MECHANISMS = {
    "storage_fidelity",
    "navigation_or_ranking",
    "query_choice",
    "local_expansion",
    "packaging_or_budget",
    "evidence_utilisation",
    "alternative_valid_evidence",
    "metric_disagreement",
    "indeterminate",
}
CONFIDENCE_LEVELS = {"high", "medium", "low"}

INPUT_FIELDS = {
    "review_id",
    "trace_candidate_id",
    "slot_id",
    "backbone_id",
    "comparison_id",
    "question_id",
    "category",
    "intended_case_type",
    "observed_case_type",
    "storage_status",
    "retrieval_status",
    "packaging_status",
    "evidence_sufficiency",
    "answerer_utilisation",
    "evaluation_agreement",
    "primary_mechanism",
    "secondary_mechanism",
    "confidence",
    "concise_finding",
    "uncertainty",
    "source_paths_checked",
    "module_id",
    "review_status",
    "manual_content_inspected",
}

PUBLIC_FIELDS = (
    "review_id",
    "trace_candidate_id",
    "slot_id",
    "module_id",
    "backbone_id",
    "comparison_id",
    "question_id",
    "category",
    "intended_case_type",
    "observed_case_type",
    "storage_status",
    "retrieval_status",
    "packaging_status",
    "evidence_sufficiency",
    "answerer_utilisation",
    "evaluation_agreement",
    "primary_mechanism",
    "secondary_mechanism",
    "confidence",
    "concise_finding",
    "uncertainty",
    "source_paths_checked",
    "review_status",
    "manual_content_inspected",
)

PROHIBITED_KEYS = {
    "question",
    "question_text",
    "reference_answer",
    "gold_answer",
    "candidate_answer",
    "answer",
    "evidence",
    "evidence_text",
    "judge_rationale",
    "api_key",
    "authorization",
    "secret",
}


def _slot(candidate: Mapping[str, Any]) -> str:
    return f"{candidate['module_id']}|{candidate['backbone_id']}|{candidate['candidate_role']}"


def _question_source_paths(question_id: str) -> tuple[str, str]:
    extension = {
        "conv-50-q147", "conv-50-q126", "conv-50-q075", "conv-50-q144",
        "conv-50-q019", "conv-50-q114", "conv-50-q121", "conv-50-q044",
        "conv-50-q057", "conv-50-q058", "conv-50-q111", "conv-50-q078",
        "conv-50-q074", "conv-50-q082", "conv-50-q104", "conv-50-q089",
        "conv-50-q012", "conv-50-q132", "conv-50-q028", "conv-50-q118",
    }
    if question_id in extension:
        root = "experiments/locomo-conv50-v1/question-sets-main60-v2"
        return f"{root}/extension-20-input.jsonl", f"{root}/extension-20-gold.jsonl"
    root = "experiments/locomo-conv50-v1/question-sets"
    return f"{root}/main-40-input.jsonl", f"{root}/main-40-gold.jsonl"


def _safe_repo_path(repo_root: Path, relative_path: str) -> Path:
    _require(isinstance(relative_path, str) and relative_path, "Review source path must be repository-relative")
    pure = PurePosixPath(relative_path)
    _require(not pure.is_absolute(), "Review source path must be repository-relative")
    _require(
        pure.as_posix() == relative_path and all(part not in {"", ".", ".."} for part in pure.parts),
        "Review source path must be canonical",
    )

    root = repo_root.resolve()
    cursor = root
    for part in pure.parts:
        cursor = cursor / part
        _require(not cursor.is_symlink(), f"Review source contains a symlink component: {relative_path}")

    path = cursor.resolve()
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise ValueError(f"Review source escapes repository: {relative_path}") from exc
    _require(path.exists(), f"Review source is missing or unsafe: {relative_path}")
    return path


def _tree_sha256(path: Path) -> str:
    if path.is_file():
        return _sha256_file(path)
    digest = hashlib.sha256()
    entries = sorted(path.rglob("*"))
    _require(all(not item.is_symlink() for item in entries), f"Review source tree is unsafe: {path}")
    files = [item for item in entries if item.is_file()]
    _require(files, f"Review source tree is empty or unsafe: {path}")
    for item in files:
        relative = item.relative_to(path).as_posix().encode("utf-8")
        digest.update(len(relative).to_bytes(8, "big"))
        digest.update(relative)
        payload = item.read_bytes()
        digest.update(len(payload).to_bytes(8, "big"))
        digest.update(payload)
    return digest.hexdigest()


def _nonempty_short_text(value: Any, label: str) -> str:
    _require(isinstance(value, str), f"{label} must be text")
    text = " ".join(value.split())
    _require(12 <= len(text) <= 480, f"{label} must be concise and nonempty")
    _require("\n" not in text and "\r" not in text, f"{label} must be one paragraph")
    return text


def _contains_prohibited_key(value: Any) -> bool:
    if isinstance(value, Mapping):
        for key, item in value.items():
            lowered = str(key).lower()
            if lowered in PROHIBITED_KEYS or any(token in lowered for token in ("password", "token_secret", "bearer")):
                return True
            if _contains_prohibited_key(item):
                return True
    elif isinstance(value, list):
        return any(_contains_prohibited_key(item) for item in value)
    return False


def _normalise_reviews(
    *,
    repo_root: Path,
    candidates: Sequence[Mapping[str, Any]],
    review_rows: Sequence[Mapping[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    _require(len(review_rows) == EXPECTED_REVIEW_COUNT, "Completed review count differs")
    candidate_index = {row["trace_candidate_id"]: row for row in candidates}
    _require(len(candidate_index) == EXPECTED_REVIEW_COUNT, "Candidate IDs are not unique")
    _require(len({row.get("trace_candidate_id") for row in review_rows}) == EXPECTED_REVIEW_COUNT, "Review candidate IDs repeat")
    _require(set(row.get("trace_candidate_id") for row in review_rows) == set(candidate_index), "Reviews substitute or omit frozen candidates")

    normalised: list[dict[str, Any]] = []
    source_bindings: dict[str, dict[str, Any]] = {}
    for supplied in review_rows:
        _require(isinstance(supplied, Mapping), "Review row must be an object")
        _require(set(supplied).issubset(INPUT_FIELDS), "Review input contains an undeclared field")
        _require(not _contains_prohibited_key(supplied), "Review input contains a prohibited field")
        candidate = candidate_index[str(supplied["trace_candidate_id"])]
        slot_id = _slot(candidate)
        identity = {
            "slot_id": slot_id,
            "backbone_id": candidate["backbone_id"],
            "comparison_id": candidate["comparison_id"],
            "question_id": candidate["question_id"],
            "category": candidate["category"],
            "intended_case_type": candidate["candidate_role"],
        }
        for field, expected in identity.items():
            _require(supplied.get(field) == expected, f"Review identity differs: {field}")
        if "module_id" in supplied:
            _require(supplied.get("module_id") == candidate["module_id"], "Review module differs")
        _require(supplied.get("review_status") == "completed", "Review status is not completed")
        _require(supplied.get("manual_content_inspected") is True, "Manual inspection flag differs")

        observed = str(supplied.get("observed_case_type"))
        storage = str(supplied.get("storage_status"))
        retrieval = str(supplied.get("retrieval_status"))
        packaging = str(supplied.get("packaging_status"))
        sufficiency = str(supplied.get("evidence_sufficiency"))
        utilisation = str(supplied.get("answerer_utilisation"))
        evaluation = str(supplied.get("evaluation_agreement"))
        primary = str(supplied.get("primary_mechanism"))
        secondary = str(supplied.get("secondary_mechanism"))
        confidence = str(supplied.get("confidence"))
        _require(observed in OBSERVED_CASE_TYPES, "Observed case type is invalid")
        _require(storage in STORAGE_STATUSES, "Storage status is invalid")
        _require(retrieval in RETRIEVAL_STATUSES, "Retrieval status is invalid")
        _require(packaging in PACKAGING_STATUSES, "Packaging status is invalid")
        _require(sufficiency in EVIDENCE_STATUSES, "Evidence sufficiency is invalid")
        _require(utilisation in ANSWERER_STATUSES, "Answerer utilisation is invalid")
        _require(evaluation in EVALUATION_STATUSES, "Evaluation agreement is invalid")
        _require(primary in MECHANISMS, "Primary mechanism is invalid")
        _require(secondary == "none" or secondary in MECHANISMS, "Secondary mechanism is invalid")
        _require(confidence in CONFIDENCE_LEVELS, "Confidence is invalid")

        raw_paths = supplied.get("source_paths_checked")
        _require(isinstance(raw_paths, list) and raw_paths, "Review source paths are missing")
        _require(all(isinstance(item, str) for item in raw_paths), "Review source paths must be text")
        checked_paths = {item: _safe_repo_path(repo_root, item) for item in raw_paths}
        paths = sorted(checked_paths)
        _require(len(paths) == len(raw_paths), "Review source paths repeat")
        required_records = set(candidate["source_record_paths"])
        required_question = set(_question_source_paths(str(candidate["question_id"])))
        required_global = {
            "data/processed/conv-50.jsonl",
            "data/manifests/source_map.json",
        }
        _require(required_records.issubset(paths), "Review did not check every frozen source record")
        _require(required_question.issubset(paths), "Review did not check question and reference files")
        _require(required_global.issubset(paths), "Review did not check canonical gold-source data")
        conditions = set(candidate["condition_ids"])
        store_prefixes = []
        if conditions & {"E1", "E2"}:
            store_prefixes.append("experiments/locomo-conv50-v1/stores/s1-flat")
        if conditions & {"E3", "E4"}:
            store_prefixes.append("experiments/locomo-conv50-v1/stores/s2-foldered")
        if conditions & {"E5", "E6"}:
            store_prefixes.append("experiments/locomo-conv50-v1/stores/s3-curated")
        for prefix in store_prefixes:
            _require(any(path == prefix or path.startswith(prefix + "/") for path in paths), f"Review did not check declared store: {prefix}")

        for relative in paths:
            source = checked_paths[relative]
            if relative not in source_bindings:
                source_bindings[relative] = {
                    "path": relative,
                    "kind": "directory_tree" if source.is_dir() else "file",
                    "sha256": _tree_sha256(source),
                }
        for relative, expected_hash in zip(candidate["source_record_paths"], candidate["source_record_file_sha256"]):
            _require(_sha256_file(_safe_repo_path(repo_root, relative)) == expected_hash, "Frozen source record hash differs")

        body = {
            "trace_candidate_id": candidate["trace_candidate_id"],
            "slot_id": slot_id,
            "module_id": candidate["module_id"],
            "backbone_id": candidate["backbone_id"],
            "comparison_id": candidate["comparison_id"],
            "question_id": candidate["question_id"],
            "category": candidate["category"],
            "intended_case_type": candidate["candidate_role"],
            "observed_case_type": observed,
            "storage_status": storage,
            "retrieval_status": retrieval,
            "packaging_status": packaging,
            "evidence_sufficiency": sufficiency,
            "answerer_utilisation": utilisation,
            "evaluation_agreement": evaluation,
            "primary_mechanism": primary,
            "secondary_mechanism": secondary,
            "confidence": confidence,
            "concise_finding": _nonempty_short_text(supplied.get("concise_finding"), "Concise finding"),
            "uncertainty": _nonempty_short_text(supplied.get("uncertainty"), "Uncertainty"),
            "source_paths_checked": paths,
            "review_status": "completed",
            "manual_content_inspected": True,
        }
        review_id = "stage-d-review-" + sha256_bytes(canonical_json_bytes(body))
        normalised.append({"review_id": review_id, **body})

    candidate_order = {row["trace_candidate_id"]: index for index, row in enumerate(candidates)}
    normalised.sort(key=lambda row: candidate_order[row["trace_candidate_id"]])
    _require(all(tuple(row) == PUBLIC_FIELDS for row in normalised), "Review field order differs")
    expected_slots = Counter((module, backbone, role) for module in MODULES for backbone in BACKBONES for role in ROLES)
    actual_slots = Counter((row["module_id"], row["backbone_id"], row["intended_case_type"]) for row in normalised)
    _require(actual_slots == expected_slots, "Completed review slots differ")
    return normalised, [source_bindings[key] for key in sorted(source_bindings)]


def _casebook(rows: Sequence[Mapping[str, Any]]) -> str:
    mechanism_counts = Counter(str(row["primary_mechanism"]) for row in rows)
    lines = [
        "# Chapter 5 Stage D bounded trace-review casebook",
        "",
        "This casebook records the 24 candidates frozen before source content was inspected. "
        "Findings are concise paraphrases. They explain selected cases and do not estimate "
        "global error prevalence or replace the later Stage E reconciliation.",
        "",
        "## Review coverage",
        "",
        "| Module | Backbone | Intended role | Question | Category | Primary mechanism | Confidence |",
        "|---|---|---|---|---:|---|---|",
    ]
    for row in rows:
        lines.append(
            f"| {row['module_id']} | {row['backbone_id']} | {row['intended_case_type']} | "
            f"`{row['question_id']}` | C{row['category']} | {row['primary_mechanism']} | {row['confidence']} |"
        )
    lines.extend([
        "",
        "## Bounded findings",
        "",
    ])
    for row in rows:
        lines.extend([
            f"### {row['slot_id']} — `{row['question_id']}`",
            "",
            f"- Observed case: {row['observed_case_type']}.",
            f"- Primary mechanism: {row['primary_mechanism']}; secondary: {row['secondary_mechanism']}.",
            f"- Finding: {row['concise_finding']}",
            f"- Uncertainty: {row['uncertainty']}",
            "",
        ])
    lines.extend([
        "## Sample composition (not prevalence)",
        "",
        "The following counts describe only the preselected review sample:",
        "",
    ])
    for mechanism in sorted(mechanism_counts):
        lines.append(f"- `{mechanism}`: {mechanism_counts[mechanism]} cases")
    lines.extend([
        "",
        "No cross-backbone stability claim, E7 analysis, Full Context comparison, global "
        "failure census, Pareto ranking, system recommendation, or final RQ1 conclusion is "
        "made by this bounded casebook.",
        "",
    ])
    return "\n".join(lines)


def _review_schema(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "protocol_version": STAGE_D_REVIEW_PROTOCOL_VERSION,
        "parent_protocol_version": STAGE_D_PROTOCOL_VERSION,
        "phase": "bounded_review_complete",
        "review_count": len(rows),
        "fields": list(PUBLIC_FIELDS),
        "allowed_values": {
            "observed_case_type": sorted(OBSERVED_CASE_TYPES),
            "storage_status": sorted(STORAGE_STATUSES),
            "retrieval_status": sorted(RETRIEVAL_STATUSES),
            "packaging_status": sorted(PACKAGING_STATUSES),
            "evidence_sufficiency": sorted(EVIDENCE_STATUSES),
            "answerer_utilisation": sorted(ANSWERER_STATUSES),
            "evaluation_agreement": sorted(EVALUATION_STATUSES),
            "primary_mechanism": sorted(MECHANISMS),
            "secondary_mechanism": ["none", *sorted(MECHANISMS)],
            "confidence": sorted(CONFIDENCE_LEVELS),
        },
        "interpretation": "bounded_case_explanations_not_prevalence_estimates",
        "raw_source_text_copied": False,
    }


def _review_manifest(
    *,
    auto_dir: Path,
    rows: Sequence[Mapping[str, Any]],
    source_bindings: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    body = {
        "schema_version": 1,
        "protocol_version": STAGE_D_REVIEW_PROTOCOL_VERSION,
        "phase": "bounded_review_complete",
        "automatic_artifact_directory": "artifacts/chapter5-main60-analysis-v1/stage-d-auto",
        "automatic_audit_id": EXPECTED_AUTO_AUDIT_ID,
        "automatic_audit_sha256": _sha256_file(auto_dir / "audit.json"),
        "candidate_register_sha256": _sha256_file(auto_dir / "trace-review-candidates.jsonl"),
        "review_count": len(rows),
        "review_ids": [row["review_id"] for row in rows],
        "review_source_bindings": list(source_bindings),
        "manual_trace_review_completed": True,
        "raw_source_text_copied": False,
        "no_api_calls": True,
        "formal_source_mutation": False,
        "global_error_census_computed": False,
        "final_rq1_conclusion_computed": False,
    }
    return {"review_manifest_id": "stage-d-review-sources-" + sha256_bytes(canonical_json_bytes(body)), **body}


def _extra_payloads(
    *,
    rows: Sequence[Mapping[str, Any]],
    source_manifest: Mapping[str, Any],
) -> dict[str, bytes]:
    return {
        "trace-review-register.jsonl": _jsonl_payload(rows),
        "trace-review-register.csv": _csv_payload(rows),
        "trace-review-casebook.md": _casebook(rows).encode("utf-8"),
        "review-schema.json": canonical_json_bytes(_review_schema(rows)) + b"\n",
        "review-source-manifest.json": canonical_json_bytes(dict(source_manifest)) + b"\n",
    }


def _final_audit_body(
    *,
    auto_dir: Path,
    rows: Sequence[Mapping[str, Any]],
    manifest: Mapping[str, Any],
    output_hashes: Mapping[str, str],
) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "protocol_version": STAGE_D_REVIEW_PROTOCOL_VERSION,
        "parent_protocol_version": STAGE_D_PROTOCOL_VERSION,
        "status": "passed",
        "phase": "bounded_review_complete",
        "scope": "unified Main-60 E1--E6 within-backbone RQ1 bounded mechanism review",
        "automatic_audit_id": EXPECTED_AUTO_AUDIT_ID,
        "automatic_audit_sha256": _sha256_file(auto_dir / "audit.json"),
        "candidate_register_sha256": _sha256_file(auto_dir / "trace-review-candidates.jsonl"),
        "review_manifest_id": manifest["review_manifest_id"],
        "review_count": len(rows),
        "unique_review_ids": len({row["review_id"] for row in rows}),
        "slot_count": len({row["slot_id"] for row in rows}),
        "category_coverage": sorted({row["category"] for row in rows}),
        "backbones": sorted({row["backbone_id"] for row in rows}),
        "manual_trace_review_completed": True,
        "all_frozen_candidates_reviewed": True,
        "candidate_substitution_detected": False,
        "source_hashes_verified": True,
        "raw_source_text_copied": False,
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
        "output_sha256": dict(output_hashes),
    }


def _marker(audit: Mapping[str, Any], audit_sha256: str) -> dict[str, Any]:
    return {
        "status": "passed",
        "protocol_version": STAGE_D_REVIEW_PROTOCOL_VERSION,
        "phase": "bounded_review_complete",
        "audit_id": audit["audit_id"],
        "audit_sha256": audit_sha256,
        "automatic_audit_id": EXPECTED_AUTO_AUDIT_ID,
        "review_count": EXPECTED_REVIEW_COUNT,
        "manual_trace_review_completed": True,
        "all_frozen_candidates_reviewed": True,
        "final_stage_d_marker_emitted": True,
        "no_api_calls": True,
    }


def _validate_auto(repo_root: Path, auto_dir: Path) -> None:
    frozen = repo_root / "artifacts/chapter5-main60-analysis-v1"
    _require(auto_dir == (frozen / "stage-d-auto").resolve(), "Automatic Stage D path is not frozen")
    result = audit_stage_d_output(
        stage_a_dir=frozen / "stage-a",
        stage_b_dir=frozen / "stage-b",
        stage_c_dir=frozen / "stage-c",
        output_dir=auto_dir,
    )
    _require(result["status"] == "passed" and result["audit_id"] == EXPECTED_AUTO_AUDIT_ID, "Automatic Stage D audit differs")
    _require(_sha256_file(auto_dir / "audit.json") == EXPECTED_AUTO_AUDIT_SHA256, "Automatic audit hash differs")
    _require(_sha256_file(auto_dir / "trace-review-candidates.jsonl") == EXPECTED_CANDIDATE_SHA256, "Candidate register hash differs")


def _assemble_stage_d_review(
    *,
    repo_root: Path,
    auto_dir: Path,
    review_rows: Sequence[Mapping[str, Any]],
    output_dir: Path,
) -> dict[str, Any]:
    """Assemble and audit one complete artifact in an existing empty staging directory."""

    root = repo_root.resolve()
    automatic = auto_dir.resolve()
    _require(root.is_dir() and not root.is_symlink(), "Repository root is unsafe")
    _validate_auto(root, automatic)
    _require(output_dir.is_dir() and not output_dir.is_symlink(), "Stage D staging directory is unsafe")
    staging = output_dir.resolve()
    _require(not any(staging.iterdir()), "Stage D staging directory is not empty")

    candidates = _read_jsonl(automatic / "trace-review-candidates.jsonl")
    rows, bindings = _normalise_reviews(repo_root=root, candidates=candidates, review_rows=review_rows)
    manifest = _review_manifest(auto_dir=automatic, rows=rows, source_bindings=bindings)
    extras = _extra_payloads(rows=rows, source_manifest=manifest)

    for item in sorted(automatic.iterdir(), key=lambda path: path.name):
        _require(item.is_file() and not item.is_symlink(), "Automatic artifact contains unsafe entry")
        _write(staging / item.name, item.read_bytes())
    for name, payload in extras.items():
        _write(staging / name, payload)
    hashed_names = sorted(path.name for path in staging.iterdir())
    hashes = {name: _sha256_file(staging / name) for name in hashed_names}
    body = _final_audit_body(auto_dir=automatic, rows=rows, manifest=manifest, output_hashes=hashes)
    audit = {"audit_id": "stage-d-final-audit-" + sha256_bytes(canonical_json_bytes(body)), **body}
    _write(staging / "final-audit.json", canonical_json_bytes(audit) + b"\n")
    _write(staging / "STAGE-D.PASSED", canonical_json_bytes(_marker(audit, _sha256_file(staging / "final-audit.json"))) + b"\n")
    return audit_stage_d_review(repo_root=root, auto_dir=automatic, output_dir=staging)


def build_stage_d_review(
    *,
    repo_root: Path,
    auto_dir: Path,
    review_input: Path,
    output_dir: Path,
) -> dict[str, Any]:
    root = repo_root.resolve()
    automatic = auto_dir.resolve()
    source = review_input.resolve()
    destination = output_dir.resolve()
    _require(root.is_dir() and not root.is_symlink(), "Repository root is unsafe")
    _require(source.is_file() and not source.is_symlink(), "Review input is unsafe")
    _require(destination == (root / "artifacts/chapter5-main60-analysis-v1/stage-d").resolve(), "Final Stage D path is not frozen")
    _require(not destination.exists() and not destination.is_symlink(), "Final Stage D output already exists")
    review_rows = _read_jsonl(source)

    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=f".{destination.name}.in-progress-", dir=destination.parent))
    try:
        result = _assemble_stage_d_review(
            repo_root=root,
            auto_dir=automatic,
            review_rows=review_rows,
            output_dir=temporary,
        )
        _require(result["status"] == "passed", "Final Stage D pre-publication audit failed")
        _require(not destination.exists(), "Final Stage D output appeared during build")
        os.rename(temporary, destination)
        descriptor = os.open(destination.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
    except Exception:
        shutil.rmtree(temporary, ignore_errors=True)
        raise
    return audit_stage_d_review(repo_root=root, auto_dir=automatic, output_dir=destination)


def audit_stage_d_review(*, repo_root: Path, auto_dir: Path, output_dir: Path) -> dict[str, Any]:
    root = repo_root.resolve()
    automatic = auto_dir.resolve()
    output = output_dir.resolve()
    _validate_auto(root, automatic)
    _require(output.is_dir() and not output.is_symlink(), "Final Stage D output is unsafe")
    entries = list(output.iterdir())
    _require(all(item.is_file() and not item.is_symlink() for item in entries), "Final Stage D contains unsafe entry")

    auto_names = {item.name for item in automatic.iterdir()}
    extra_names = {
        "trace-review-register.jsonl", "trace-review-register.csv", "trace-review-casebook.md",
        "review-schema.json", "review-source-manifest.json", "final-audit.json", "STAGE-D.PASSED",
    }
    _require({item.name for item in entries} == auto_names | extra_names, "Final Stage D file set differs")
    for name in auto_names:
        _require((output / name).read_bytes() == (automatic / name).read_bytes(), f"Automatic file changed in final artifact: {name}")

    candidates = _read_jsonl(automatic / "trace-review-candidates.jsonl")
    stored_rows = _read_jsonl(output / "trace-review-register.jsonl")
    rows, bindings = _normalise_reviews(repo_root=root, candidates=candidates, review_rows=stored_rows)
    _require(stored_rows == rows, "Stored review rows are not canonical")
    manifest = _review_manifest(auto_dir=automatic, rows=rows, source_bindings=bindings)
    extras = _extra_payloads(rows=rows, source_manifest=manifest)
    for name, payload in extras.items():
        _require((output / name).read_bytes() == payload, f"Final review bytes differ: {name}")

    hashed_names = sorted(auto_names | set(extras))
    hashes = {name: _sha256_file(output / name) for name in hashed_names}
    body = _final_audit_body(auto_dir=automatic, rows=rows, manifest=manifest, output_hashes=hashes)
    expected_audit = {"audit_id": "stage-d-final-audit-" + sha256_bytes(canonical_json_bytes(body)), **body}
    expected_audit_payload = canonical_json_bytes(expected_audit) + b"\n"
    expected_marker = _marker(expected_audit, hashlib.sha256(expected_audit_payload).hexdigest())
    _require((output / "final-audit.json").read_bytes() == expected_audit_payload, "Final Stage D audit differs")
    _require((output / "STAGE-D.PASSED").read_bytes() == canonical_json_bytes(expected_marker) + b"\n", "Final Stage D marker differs")
    for name, digest in hashes.items():
        _require(_sha256_file(output / name) == digest, f"Final output hash differs: {name}")
    return {
        "status": "passed",
        "protocol_version": STAGE_D_REVIEW_PROTOCOL_VERSION,
        "phase": "bounded_review_complete",
        "audit_id": expected_audit["audit_id"],
        "review_count": len(rows),
        "automatic_audit_id": EXPECTED_AUTO_AUDIT_ID,
        "all_frozen_candidates_reviewed": True,
        "manual_trace_review_completed": True,
        "final_stage_d_marker_emitted": True,
        "no_api_calls": True,
        "output_dir": str(output),
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Finalize or audit Chapter 5 Stage D bounded review")
    parser.add_argument("command", choices=("build", "audit"))
    parser.add_argument("--repo-root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--auto-dir", type=Path, required=True)
    parser.add_argument("--review-input", type=Path)
    parser.add_argument("--output-dir", type=Path, required=True)
    return parser


def main(argv: list[str] | None = None) -> None:
    args = _parser().parse_args(argv)
    if args.command == "build":
        _require(args.review_input is not None, "--review-input is required for build")
        result = build_stage_d_review(
            repo_root=args.repo_root,
            auto_dir=args.auto_dir,
            review_input=args.review_input,
            output_dir=args.output_dir,
        )
    else:
        result = audit_stage_d_review(
            repo_root=args.repo_root,
            auto_dir=args.auto_dir,
            output_dir=args.output_dir,
        )
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
