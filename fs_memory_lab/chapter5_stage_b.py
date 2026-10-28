"""Build and audit the Chapter 5 Stage B raw 2x2 paired analysis.

Stage B consumes only the frozen Stage A RQ1 view.  It filters to E1--E4,
computes the four within-backbone simple contrasts plus the storage--retrieval
interaction, and publishes text-free machine-readable artifacts.  It never
reads answer text, calls a model API, modifies a formal run, or advances into
the Stage C/D analyses.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import math
import os
import random
import shutil
import statistics
import tempfile
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Sequence

from .chapter5_stage_a import STAGE_A_PROTOCOL_VERSION, audit_stage_a_output
from .evidence import EvidenceValidationError, canonical_json_bytes, sha256_bytes


STAGE_B_PROTOCOL_VERSION = "chapter5-main60-stage-b-v1"
STAGE_B_CONDITIONS = ("E1", "E2", "E3", "E4")
BACKBONES = ("qwen", "deepseek")
QUESTION_COUNT = 60
EVIDENCE_ELIGIBLE_COUNT = 58
EXPECTED_CATEGORIES = {1: 13, 2: 13, 3: 7, 4: 27}
EXPECTED_EVIDENCE_CATEGORIES = {1: 13, 2: 13, 3: 5, 4: 27}
EXPECTED_INELIGIBLE_QUESTION_IDS = {"conv-50-q040", "conv-50-q043"}
EXPECTED_STAGE_B_ROWS = 480
EXPECTED_MULTI_GOLD_SOURCE_COUNT = 19
TIE_TOLERANCE = 1e-12
ALGEBRA_TOLERANCE = 1e-12
BOOTSTRAP_REPLICATES = 10_000
BOOTSTRAP_SEED = 20_261_021
BOOTSTRAP_LOWER_QUANTILE = 0.025
BOOTSTRAP_UPPER_QUANTILE = 0.975
EXPECTED_STAGE_A_AUDIT_ID = "stage-a-audit-5f55ec411f097df7206fdae5e71742641aa8868b4128ac32262f034877a1d7f3"
EXPECTED_STAGE_A_SOURCE_MANIFEST_ID = "stage-a-sources-90efa256f7981450cf38503912406a1e30766e8440b443899cab953fe9fece3c"
EXPECTED_STAGE_A_RQ1_SHA256 = "f7223ae5605cec0a00042022e41b5ac9e0c0ec438b0bdc05340813be415855df"
EXPECTED_STAGE_A_SCHEMA_SHA256 = "21295503a3b8e0cadcde9a61a46be1e383c38da329dbc66d716b78faa72ede09"

EXPECTED_ANSWER_SETS = {
    "qwen": "model1-qwen-main60",
    "deepseek": "model2-deepseek-main60",
}
EXPECTED_MODELS = {
    "qwen": ("coding", "qwen3.8:27b"),
    "deepseek": ("x-test-2", "deepseek-v4.1-flash"),
}
EXPECTED_JUDGE = ("x-test-1", "glm-5.3-flash")
EXPECTED_DESIGN = {
    "E1": ("S1", "R1"),
    "E2": ("S1", "R2"),
    "E3": ("S2", "R1"),
    "E4": ("S2", "R2"),
}
EXPECTED_CATEGORY_NAMES = {
    1: "multi-hop",
    2: "temporal",
    3: "open-domain",
    4: "single-hop",
}

TEXT_BEARING_FIELD_FRAGMENTS = (
    "question_text",
    "reference_answer",
    "candidate_answer",
    "answer_text",
    "evidence_text",
    "short_reason",
    "rationale",
    "judge_reason",
)


@dataclass(frozen=True)
class MetricSpec:
    metric_id: str
    source_field: str
    family: str
    scope: str
    direction: int | None


@dataclass(frozen=True)
class ContrastSpec:
    contrast_id: str
    family: str
    baseline_condition: str
    target_condition: str


ANSWER_METRICS = (
    MetricSpec("token_precision", "token_precision", "answer", "answer_all", 1),
    MetricSpec("token_recall", "token_recall", "answer", "answer_all", 1),
    MetricSpec("token_f1", "token_f1", "answer", "answer_all", 1),
    MetricSpec("strict_accuracy", "strict_score", "answer", "answer_all", 1),
    MetricSpec("partial_rate", "partial_indicator", "answer", "answer_all", None),
    MetricSpec("soft_semantic_score", "soft_semantic_score", "answer", "answer_all", 1),
)
EVIDENCE_METRICS = (
    MetricSpec("evidence_recall", "evidence_recall", "evidence", "evidence_eligible", 1),
    MetricSpec("evidence_any_hit", "evidence_any_hit", "evidence", "evidence_eligible", 1),
    MetricSpec("evidence_all_hit", "evidence_all_hit", "evidence", "evidence_eligible", 1),
    MetricSpec(
        "evidence_bundle_characters",
        "evidence_bundle_characters",
        "evidence",
        "evidence_eligible",
        None,
    ),
)
MULTI_GOLD_SOURCE_METRICS = (
    MetricSpec(
        "multi_gold_source_evidence_recall",
        "evidence_recall",
        "evidence",
        "multi_gold_source_evidence_eligible",
        1,
    ),
    MetricSpec(
        "multi_gold_source_any_hit",
        "evidence_any_hit",
        "evidence",
        "multi_gold_source_evidence_eligible",
        1,
    ),
    MetricSpec(
        "multi_gold_source_all_hit",
        "evidence_all_hit",
        "evidence",
        "multi_gold_source_evidence_eligible",
        1,
    ),
)
METRICS = ANSWER_METRICS + EVIDENCE_METRICS + MULTI_GOLD_SOURCE_METRICS
METRIC_BY_ID = {spec.metric_id: spec for spec in METRICS}

CONTRASTS = (
    ContrastSpec("storage_r1_e3_minus_e1", "storage_organisation", "E1", "E3"),
    ContrastSpec("storage_r2_e4_minus_e2", "storage_organisation", "E2", "E4"),
    ContrastSpec("retrieval_s1_e2_minus_e1", "retrieval_system", "E1", "E2"),
    ContrastSpec("retrieval_s2_e4_minus_e3", "retrieval_system", "E3", "E4"),
)
CONTRAST_BY_ID = {spec.contrast_id: spec for spec in CONTRASTS}
BOOTSTRAP_METRICS = ("token_f1", "strict_accuracy", "soft_semantic_score")


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise EvidenceValidationError(message)


def _sha256_file(path: Path) -> str:
    lexical = Path(path)
    if lexical.is_symlink() or not lexical.is_file():
        raise EvidenceValidationError(f"Unsafe or missing Stage B input: {lexical}")
    digest = hashlib.sha256()
    with lexical.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _read_json(path: Path) -> dict[str, Any]:
    lexical = Path(path)
    if lexical.is_symlink() or not lexical.is_file():
        raise EvidenceValidationError(f"Unsafe or missing Stage B JSON: {lexical}")
    try:
        value = json.loads(lexical.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise EvidenceValidationError(f"Unreadable Stage B JSON: {lexical}") from exc
    _require(isinstance(value, dict), f"Stage B JSON must be an object: {lexical}")
    return value


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    lexical = Path(path)
    if lexical.is_symlink() or not lexical.is_file():
        raise EvidenceValidationError(f"Unsafe or missing Stage B JSONL: {lexical}")
    rows: list[dict[str, Any]] = []
    try:
        lines = lexical.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeError) as exc:
        raise EvidenceValidationError(f"Unreadable Stage B JSONL: {lexical}") from exc
    for index, line in enumerate(lines, start=1):
        try:
            value = json.loads(line)
        except json.JSONDecodeError as exc:
            raise EvidenceValidationError(f"Invalid JSONL row {index}: {lexical}") from exc
        _require(isinstance(value, dict), f"Stage B JSONL row {index} is not an object")
        rows.append(value)
    return rows


def _relative(root: Path, path: Path) -> str:
    try:
        return str(path.resolve().relative_to(root.resolve()))
    except ValueError:
        return str(path.resolve())


def _artifact(root: Path, path: Path) -> dict[str, Any]:
    return {
        "path": _relative(root, path),
        "sha256": _sha256_file(path),
        "bytes": path.stat().st_size,
    }


def _write(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(path, flags, 0o644)
    try:
        offset = 0
        while offset < len(payload):
            count = os.write(descriptor, payload[offset:])
            if count <= 0:
                raise OSError("short Stage B artifact write")
            offset += count
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _jsonl_payload(rows: Iterable[Mapping[str, Any]]) -> bytes:
    return b"".join(canonical_json_bytes(dict(row)) + b"\n" for row in rows)


def _csv_payload(rows: Sequence[Mapping[str, Any]]) -> bytes:
    _require(bool(rows), "Cannot serialize an empty Stage B table")
    fieldnames = list(rows[0])
    _require(all(list(row) == fieldnames for row in rows), "Stage B table fields or order differ")
    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=fieldnames, lineterminator="\n")
    writer.writeheader()
    for row in rows:
        writer.writerow(
            {
                key: json.dumps(value, ensure_ascii=False, separators=(",", ":"))
                if isinstance(value, (list, dict))
                else value
                for key, value in row.items()
            }
        )
    return buffer.getvalue().encode("utf-8")


def _mean(values: Sequence[float]) -> float:
    _require(bool(values), "Cannot calculate a mean from an empty sequence")
    return math.fsum(values) / len(values)


def _median(values: Sequence[float]) -> float:
    _require(bool(values), "Cannot calculate a median from an empty sequence")
    return float(statistics.median(values))


def _is_close(left: float, right: float, *, tolerance: float = TIE_TOLERANCE) -> bool:
    """Compare audited numeric identities with the frozen absolute tolerance only."""

    return math.isclose(float(left), float(right), rel_tol=0.0, abs_tol=tolerance)


def _type7_quantile(sorted_values: Sequence[float], probability: float) -> float:
    _require(bool(sorted_values), "Cannot calculate a quantile from an empty sequence")
    _require(0.0 <= probability <= 1.0, "Quantile probability is outside [0,1]")
    if len(sorted_values) == 1:
        return float(sorted_values[0])
    position = (len(sorted_values) - 1) * probability
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return float(sorted_values[lower])
    weight = position - lower
    return float(sorted_values[lower] * (1.0 - weight) + sorted_values[upper] * weight)


def _state(value: float) -> str:
    if value > TIE_TOLERANCE:
        return "increase"
    if value < -TIE_TOLERANCE:
        return "decrease"
    return "same"


def _oriented_state(value: float | None) -> str | None:
    if value is None:
        return None
    if value > TIE_TOLERANCE:
        return "win"
    if value < -TIE_TOLERANCE:
        return "loss"
    return "tie"


def _metric_value(row: Mapping[str, Any], spec: MetricSpec) -> float:
    value = row.get(spec.source_field)
    _require(value is not None, f"Metric {spec.metric_id} is unexpectedly null")
    _require(isinstance(value, (bool, int, float)), f"Metric {spec.metric_id} is not numeric")
    return float(value)


def _row_in_scope(row: Mapping[str, Any], spec: MetricSpec) -> bool:
    if spec.scope == "answer_all":
        return True
    if spec.scope == "evidence_eligible":
        return row.get("evidence_eligible") is True
    if spec.scope == "multi_gold_source_evidence_eligible":
        return row.get("evidence_eligible") is True and len(set(row.get("gold_dia_ids", []))) > 1
    raise EvidenceValidationError(f"Unknown Stage B metric scope: {spec.scope}")


def _expected_denominator(spec: MetricSpec) -> int:
    if spec.scope == "answer_all":
        return QUESTION_COUNT
    if spec.scope == "evidence_eligible":
        return EVIDENCE_ELIGIBLE_COUNT
    if spec.scope == "multi_gold_source_evidence_eligible":
        return EXPECTED_MULTI_GOLD_SOURCE_COUNT
    raise EvidenceValidationError(f"Unknown Stage B metric scope: {spec.scope}")


def _metric_direction_name(spec: MetricSpec) -> str:
    return "higher_is_better" if spec.direction == 1 else "neutral"


def _id(prefix: str, payload: Mapping[str, Any]) -> str:
    return prefix + sha256_bytes(canonical_json_bytes(dict(payload)))


def _load_stage_a_input(stage_a_dir: Path) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    root = stage_a_dir.resolve()
    gate = audit_stage_a_output(root)
    audit = _read_json(root / "audit.json")
    marker = _read_json(root / "STAGE-A.PASSED")
    source_manifest = _read_json(root / "source-manifest.json")
    _require(gate.get("status") == "passed", "Stage A gate is not passed")
    _require(audit.get("protocol_version") == STAGE_A_PROTOCOL_VERSION, "Stage A protocol differs")
    _require(audit.get("audit_id") == EXPECTED_STAGE_A_AUDIT_ID, "Frozen Stage A audit identity differs")
    _require(marker.get("audit_id") == audit.get("audit_id"), "Stage A marker audit ID differs")
    manifest_id = source_manifest.get("source_manifest_id")
    manifest_body = {key: value for key, value in source_manifest.items() if key != "source_manifest_id"}
    _require(
        manifest_id == "stage-a-sources-" + sha256_bytes(canonical_json_bytes(manifest_body)),
        "Stage A source manifest ID does not recompute",
    )
    _require(manifest_id == audit.get("source_manifest_id"), "Stage A source manifest identity differs")
    _require(manifest_id == EXPECTED_STAGE_A_SOURCE_MANIFEST_ID, "Frozen Stage A source manifest identity differs")
    _require(_sha256_file(root / "rq1-analysis-view.jsonl") == EXPECTED_STAGE_A_RQ1_SHA256, "Frozen Stage A RQ1 view hash differs")
    _require(_sha256_file(root / "schema.json") == EXPECTED_STAGE_A_SCHEMA_SHA256, "Frozen Stage A schema hash differs")
    all_rows = _read_jsonl(root / "rq1-analysis-view.jsonl")
    rows = [row for row in all_rows if row.get("condition_id") in STAGE_B_CONDITIONS]
    _require(len(all_rows) == 720, "Stage A RQ1 view is not 720 rows")
    _require(len(rows) == EXPECTED_STAGE_B_ROWS, "Stage B input is not 480 rows")
    provenance = {
        "stage_a_protocol_version": audit["protocol_version"],
        "stage_a_audit_id": audit["audit_id"],
        "stage_a_audit_sha256": _sha256_file(root / "audit.json"),
        "stage_a_marker_sha256": _sha256_file(root / "STAGE-A.PASSED"),
        "stage_a_source_manifest_id": manifest_id,
        "stage_a_source_manifest_sha256": _sha256_file(root / "source-manifest.json"),
        "stage_a_schema_sha256": _sha256_file(root / "schema.json"),
        "stage_a_rq1_view_sha256": _sha256_file(root / "rq1-analysis-view.jsonl"),
    }
    return rows, provenance


def _validate_input(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    _require(len(rows) == EXPECTED_STAGE_B_ROWS, "Stage B input row count differs")
    keyed: dict[tuple[str, str, str], Mapping[str, Any]] = {}
    cells: Counter[tuple[str, str]] = Counter()
    categories: dict[tuple[str, str], Counter[int]] = defaultdict(Counter)
    evidence_categories: dict[tuple[str, str], Counter[int]] = defaultdict(Counter)
    question_metadata: dict[str, tuple[Any, ...]] = {}
    evidence_sets: dict[tuple[str, str], tuple[str, ...]] = {}
    multi_sets: dict[tuple[str, str], tuple[str, ...]] = {}
    for row in rows:
        backbone = str(row.get("backbone_id"))
        condition = str(row.get("condition_id"))
        question_id = str(row.get("question_id"))
        answer_set = str(row.get("answer_set_id"))
        _require(backbone in BACKBONES, f"Unexpected Stage B backbone: {backbone}")
        _require(condition in STAGE_B_CONDITIONS, f"Unexpected Stage B condition: {condition}")
        _require(answer_set == EXPECTED_ANSWER_SETS[backbone], "Stage B answer-set identity differs")
        _require(row.get("protocol_version") == STAGE_A_PROTOCOL_VERSION, "Input protocol differs")
        _require(row.get("is_rq1_analysis_row") is True, "Input row is not marked for RQ1")
        storage, retrieval = EXPECTED_DESIGN[condition]
        _require(
            row.get("storage_representation") == storage
            and row.get("retrieval_system") == retrieval
            and row.get("access_regime") == "selective_retrieval",
            f"Condition design differs: {backbone}/{condition}/{question_id}",
        )
        _require(
            row.get("evidence_budget_characters") == 16_000,
            f"Evidence budget differs: {backbone}/{condition}/{question_id}",
        )
        requested, served = EXPECTED_MODELS[backbone]
        _require(
            row.get("requested_model") == requested and row.get("served_model") == served,
            f"Backbone model identity differs: {backbone}/{condition}/{question_id}",
        )
        _require(
            (row.get("judge_requested_model"), row.get("judge_served_model")) == EXPECTED_JUDGE,
            f"Judge identity differs: {backbone}/{condition}/{question_id}",
        )
        key = (answer_set, condition, question_id)
        _require(key not in keyed, f"Duplicate Stage B input key: {key}")
        keyed[key] = row
        cells[(backbone, condition)] += 1
        category = row.get("category")
        _require(category in EXPECTED_CATEGORIES, "Stage B category is invalid")
        _require(
            row.get("category_name") == EXPECTED_CATEGORY_NAMES[int(category)],
            f"Stage B category name differs: {question_id}",
        )
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
        expected_strict = {"incorrect": 0.0, "partial": 0.0, "correct": 1.0}[str(label)]
        expected_partial = {"incorrect": 0, "partial": 1, "correct": 0}[str(label)]
        expected_soft = {"incorrect": 0.0, "partial": 0.5, "correct": 1.0}[str(label)]
        _require(
            not isinstance(row.get("strict_score"), bool)
            and row.get("strict_score") == expected_strict,
            "Strict score mapping differs",
        )
        _require(
            not isinstance(row.get("partial_indicator"), bool)
            and row.get("partial_indicator") == expected_partial,
            "Partial indicator mapping differs",
        )
        _require(row.get("soft_semantic_score") == expected_soft, "Soft semantic mapping differs")
        for field in ("token_precision", "token_recall", "token_f1", "soft_semantic_score"):
            value = row.get(field)
            _require(isinstance(value, (int, float)) and 0.0 <= float(value) <= 1.0, f"{field} range differs")
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
        _require(row.get("elapsed_ms") is None and row.get("latency_available") is False, "Stage B latency must be unavailable")

    expected_cells = {(backbone, condition): QUESTION_COUNT for backbone in BACKBONES for condition in STAGE_B_CONDITIONS}
    _require(dict(cells) == expected_cells, "Stage B cell counts differ")
    for cell, counter in categories.items():
        _require(dict(counter) == EXPECTED_CATEGORIES, f"Category counts differ: {cell}")
    for cell, counter in evidence_categories.items():
        _require(dict(counter) == EXPECTED_EVIDENCE_CATEGORIES, f"Evidence category counts differ: {cell}")
    _require(len(question_metadata) == QUESTION_COUNT, "Stage B question count differs")
    ordered_questions = tuple(
        question_id for question_id, _ in sorted(question_metadata.items(), key=lambda item: int(item[1][1]))
    )
    _require(
        tuple(int(question_metadata[qid][1]) for qid in ordered_questions) == tuple(range(1, QUESTION_COUNT + 1)),
        "Stage B global positions differ",
    )
    for backbone in BACKBONES:
        for condition in STAGE_B_CONDITIONS:
            cell_rows = [
                row for row in rows if row["backbone_id"] == backbone and row["condition_id"] == condition
            ]
            evidence_sets[(backbone, condition)] = tuple(
                row["question_id"]
                for row in sorted(cell_rows, key=lambda item: int(item["global_position"]))
                if row["evidence_eligible"]
            )
            multi_sets[(backbone, condition)] = tuple(
                row["question_id"]
                for row in sorted(cell_rows, key=lambda item: int(item["global_position"]))
                if row["evidence_eligible"] and len(set(row["gold_dia_ids"])) > 1
            )
    _require(len(set(evidence_sets.values())) == 1, "Evidence eligibility mask differs across cells")
    _require(len(next(iter(evidence_sets.values()))) == EVIDENCE_ELIGIBLE_COUNT, "Evidence denominator differs")
    ineligible_question_ids = set(ordered_questions) - set(next(iter(evidence_sets.values())))
    _require(
        ineligible_question_ids == EXPECTED_INELIGIBLE_QUESTION_IDS,
        "Frozen Evidence-ineligible question IDs differ",
    )
    _require(len(set(multi_sets.values())) == 1, "Multi-gold-source mask differs across cells")
    _require(len(next(iter(multi_sets.values()))) == EXPECTED_MULTI_GOLD_SOURCE_COUNT, "Multi-source denominator differs")
    return {
        "input_rows": len(rows),
        "question_count": len(question_metadata),
        "cell_counts": {f"{backbone}/{condition}": cells[(backbone, condition)] for backbone in BACKBONES for condition in STAGE_B_CONDITIONS},
        "category_counts_per_cell": {
            f"{backbone}/{condition}": {str(category): categories[(backbone, condition)][category] for category in sorted(EXPECTED_CATEGORIES)}
            for backbone in BACKBONES
            for condition in STAGE_B_CONDITIONS
        },
        "evidence_category_counts_per_cell": {
            f"{backbone}/{condition}": {
                str(category): evidence_categories[(backbone, condition)][category]
                for category in sorted(EXPECTED_EVIDENCE_CATEGORIES)
            }
            for backbone in BACKBONES
            for condition in STAGE_B_CONDITIONS
        },
        "evidence_ineligible_question_ids": sorted(ineligible_question_ids),
        "evidence_denominator": EVIDENCE_ELIGIBLE_COUNT,
        "multi_gold_source_denominator": EXPECTED_MULTI_GOLD_SOURCE_COUNT,
        "ordered_question_ids_sha256": sha256_bytes(canonical_json_bytes(list(ordered_questions))),
    }


def _index_rows(rows: Sequence[Mapping[str, Any]]) -> tuple[dict[tuple[str, str, str], Mapping[str, Any]], tuple[str, ...]]:
    index = {
        (str(row["backbone_id"]), str(row["condition_id"]), str(row["question_id"])): row
        for row in rows
    }
    qwen_e1 = [row for row in rows if row["backbone_id"] == "qwen" and row["condition_id"] == "E1"]
    ordered_questions = tuple(
        str(row["question_id"]) for row in sorted(qwen_e1, key=lambda item: int(item["global_position"]))
    )
    return index, ordered_questions


def _condition_summaries(
    index: Mapping[tuple[str, str, str], Mapping[str, Any]], ordered_questions: Sequence[str]
) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for backbone in BACKBONES:
        for condition in STAGE_B_CONDITIONS:
            for spec in METRICS:
                rows = [index[(backbone, condition, question_id)] for question_id in ordered_questions]
                values = [_metric_value(row, spec) for row in rows if _row_in_scope(row, spec)]
                denominator = _expected_denominator(spec)
                _require(len(values) == denominator, f"Condition summary denominator differs: {backbone}/{condition}/{spec.metric_id}")
                identity = {
                    "backbone_id": backbone,
                    "condition_id": condition,
                    "metric_id": spec.metric_id,
                    "denominator_scope": spec.scope,
                }
                output.append(
                    {
                        "condition_summary_id": _id("stage-b-condition-", identity),
                        "protocol_version": STAGE_B_PROTOCOL_VERSION,
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
                    }
                )
    return output


def _paired_question_effects(
    index: Mapping[tuple[str, str, str], Mapping[str, Any]], ordered_questions: Sequence[str]
) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for backbone in BACKBONES:
        for contrast in CONTRASTS:
            for spec in METRICS:
                for question_id in ordered_questions:
                    baseline = index[(backbone, contrast.baseline_condition, question_id)]
                    target = index[(backbone, contrast.target_condition, question_id)]
                    _require(
                        _row_in_scope(baseline, spec) == _row_in_scope(target, spec),
                        "Paired metric scope differs",
                    )
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
                            "paired_effect_id": _id("stage-b-pair-", identity),
                            "protocol_version": STAGE_B_PROTOCOL_VERSION,
                            "backbone_id": backbone,
                            "answer_set_id": EXPECTED_ANSWER_SETS[backbone],
                            "contrast_id": contrast.contrast_id,
                            "contrast_family": contrast.family,
                            "baseline_condition": contrast.baseline_condition,
                            "target_condition": contrast.target_condition,
                            "question_id": question_id,
                            "global_position": int(baseline["global_position"]),
                            "category": int(baseline["category"]),
                            "category_name": str(baseline["category_name"]),
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
                rows = sorted(
                    groups[(backbone, contrast.contrast_id, spec.metric_id)],
                    key=lambda row: int(row["global_position"]),
                )
                denominator = _expected_denominator(spec)
                _require(len(rows) == denominator, "Aggregate paired denominator differs")
                baseline = [float(row["baseline_value"]) for row in rows]
                target = [float(row["target_value"]) for row in rows]
                differences = [float(row["raw_difference"]) for row in rows]
                raw_counts = Counter(str(row["raw_state"]) for row in rows)
                oriented_counts = Counter(str(row["oriented_state"]) for row in rows if row["oriented_state"] is not None)
                identity = {
                    "backbone_id": backbone,
                    "contrast_id": contrast.contrast_id,
                    "metric_id": spec.metric_id,
                }
                output.append(
                    {
                        "aggregate_effect_id": _id("stage-b-effect-", identity),
                        "protocol_version": STAGE_B_PROTOCOL_VERSION,
                        "backbone_id": backbone,
                        "answer_set_id": EXPECTED_ANSWER_SETS[backbone],
                        "contrast_id": contrast.contrast_id,
                        "contrast_family": contrast.family,
                        "baseline_condition": contrast.baseline_condition,
                        "target_condition": contrast.target_condition,
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
                        "increase_count": raw_counts["increase"],
                        "same_count": raw_counts["same"],
                        "decrease_count": raw_counts["decrease"],
                        "win_count": oriented_counts["win"] if spec.direction is not None else None,
                        "tie_count": oriented_counts["tie"] if spec.direction is not None else None,
                        "loss_count": oriented_counts["loss"] if spec.direction is not None else None,
                    }
                )
    return output


def _semantic_transitions(
    index: Mapping[tuple[str, str, str], Mapping[str, Any]], ordered_questions: Sequence[str]
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    strict_output: list[dict[str, Any]] = []
    semantic_output: list[dict[str, Any]] = []
    semantic_labels = ("correct", "partial", "incorrect")
    for backbone in BACKBONES:
        for contrast in CONTRASTS:
            strict_counts: Counter[tuple[bool, bool]] = Counter()
            semantic_counts: Counter[tuple[str, str]] = Counter()
            for question_id in ordered_questions:
                baseline = index[(backbone, contrast.baseline_condition, question_id)]
                target = index[(backbone, contrast.target_condition, question_id)]
                strict_counts[(bool(baseline["strict_score"]), bool(target["strict_score"]))] += 1
                semantic_counts[(str(baseline["judge_label"]), str(target["judge_label"]))] += 1
            for baseline_correct, target_correct, transition_id in (
                (False, True, "strict_not_correct_to_correct"),
                (True, False, "strict_correct_to_not_correct"),
                (True, True, "strict_unchanged_correct"),
                (False, False, "strict_unchanged_not_correct"),
            ):
                identity = {
                    "backbone_id": backbone,
                    "contrast_id": contrast.contrast_id,
                    "transition_id": transition_id,
                }
                strict_output.append(
                    {
                        "strict_transition_row_id": _id("stage-b-strict-transition-", identity),
                        "protocol_version": STAGE_B_PROTOCOL_VERSION,
                        "backbone_id": backbone,
                        "answer_set_id": EXPECTED_ANSWER_SETS[backbone],
                        "contrast_id": contrast.contrast_id,
                        "baseline_condition": contrast.baseline_condition,
                        "target_condition": contrast.target_condition,
                        "transition_id": transition_id,
                        "baseline_strict_correct": baseline_correct,
                        "target_strict_correct": target_correct,
                        "count": strict_counts[(baseline_correct, target_correct)],
                        "denominator": QUESTION_COUNT,
                    }
                )
            for baseline_label in semantic_labels:
                for target_label in semantic_labels:
                    identity = {
                        "backbone_id": backbone,
                        "contrast_id": contrast.contrast_id,
                        "baseline_label": baseline_label,
                        "target_label": target_label,
                    }
                    semantic_output.append(
                        {
                            "semantic_transition_row_id": _id("stage-b-semantic-transition-", identity),
                            "protocol_version": STAGE_B_PROTOCOL_VERSION,
                            "backbone_id": backbone,
                            "answer_set_id": EXPECTED_ANSWER_SETS[backbone],
                            "contrast_id": contrast.contrast_id,
                            "baseline_condition": contrast.baseline_condition,
                            "target_condition": contrast.target_condition,
                            "baseline_label": baseline_label,
                            "target_label": target_label,
                            "count": semantic_counts[(baseline_label, target_label)],
                            "denominator": QUESTION_COUNT,
                        }
                    )
    return strict_output, semantic_output


def _interaction_question_effects(
    index: Mapping[tuple[str, str, str], Mapping[str, Any]], ordered_questions: Sequence[str]
) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for backbone in BACKBONES:
        for spec in METRICS:
            for question_id in ordered_questions:
                cells = {condition: index[(backbone, condition, question_id)] for condition in STAGE_B_CONDITIONS}
                scopes = {_row_in_scope(row, spec) for row in cells.values()}
                _require(len(scopes) == 1, "Interaction metric scope differs across E1--E4")
                if not next(iter(scopes)):
                    continue
                values = {condition: _metric_value(cells[condition], spec) for condition in STAGE_B_CONDITIONS}
                storage_r1 = values["E3"] - values["E1"]
                storage_r2 = values["E4"] - values["E2"]
                retrieval_s1 = values["E2"] - values["E1"]
                retrieval_s2 = values["E4"] - values["E3"]
                did_storage_form = storage_r2 - storage_r1
                did_retrieval_form = retrieval_s2 - retrieval_s1
                residual = did_storage_form - did_retrieval_form
                _require(abs(residual) <= ALGEBRA_TOLERANCE, "Question-level DID identities differ")
                oriented = spec.direction * did_storage_form if spec.direction is not None else None
                e1 = cells["E1"]
                identity = {
                    "backbone_id": backbone,
                    "metric_id": spec.metric_id,
                    "question_id": question_id,
                }
                output.append(
                    {
                        "interaction_effect_id": _id("stage-b-interaction-", identity),
                        "protocol_version": STAGE_B_PROTOCOL_VERSION,
                        "backbone_id": backbone,
                        "answer_set_id": EXPECTED_ANSWER_SETS[backbone],
                        "question_id": question_id,
                        "global_position": int(e1["global_position"]),
                        "category": int(e1["category"]),
                        "category_name": str(e1["category_name"]),
                        "evidence_eligible": bool(e1["evidence_eligible"]),
                        "gold_source_count": len(set(e1["gold_dia_ids"])),
                        "metric_family": spec.family,
                        "metric_id": spec.metric_id,
                        "metric_direction": _metric_direction_name(spec),
                        "denominator_scope": spec.scope,
                        "e1_value": values["E1"],
                        "e2_value": values["E2"],
                        "e3_value": values["E3"],
                        "e4_value": values["E4"],
                        "storage_r1_e3_minus_e1": storage_r1,
                        "storage_r2_e4_minus_e2": storage_r2,
                        "retrieval_s1_e2_minus_e1": retrieval_s1,
                        "retrieval_s2_e4_minus_e3": retrieval_s2,
                        "did_storage_form": did_storage_form,
                        "did_retrieval_form": did_retrieval_form,
                        "algebraic_residual": residual,
                        "did_oriented": oriented,
                        "raw_state": _state(did_storage_form),
                        "oriented_state": _oriented_state(oriented),
                        "e1_analysis_row_id": str(cells["E1"]["analysis_row_id"]),
                        "e2_analysis_row_id": str(cells["E2"]["analysis_row_id"]),
                        "e3_analysis_row_id": str(cells["E3"]["analysis_row_id"]),
                        "e4_analysis_row_id": str(cells["E4"]["analysis_row_id"]),
                    }
                )
    return output


def _interaction_aggregates(interaction_rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    groups: dict[tuple[str, str], list[Mapping[str, Any]]] = defaultdict(list)
    for row in interaction_rows:
        groups[(str(row["backbone_id"]), str(row["metric_id"]))].append(row)
    output: list[dict[str, Any]] = []
    for backbone in BACKBONES:
        for spec in METRICS:
            rows = sorted(groups[(backbone, spec.metric_id)], key=lambda row: int(row["global_position"]))
            denominator = _expected_denominator(spec)
            _require(len(rows) == denominator, "Interaction aggregate denominator differs")
            did = [float(row["did_storage_form"]) for row in rows]
            residuals = [float(row["algebraic_residual"]) for row in rows]
            raw_counts = Counter(str(row["raw_state"]) for row in rows)
            oriented_counts = Counter(str(row["oriented_state"]) for row in rows if row["oriented_state"] is not None)
            identity = {"backbone_id": backbone, "metric_id": spec.metric_id}
            output.append(
                {
                    "interaction_aggregate_id": _id("stage-b-interaction-aggregate-", identity),
                    "protocol_version": STAGE_B_PROTOCOL_VERSION,
                    "backbone_id": backbone,
                    "answer_set_id": EXPECTED_ANSWER_SETS[backbone],
                    "metric_family": spec.family,
                    "metric_id": spec.metric_id,
                    "metric_direction": _metric_direction_name(spec),
                    "denominator_scope": spec.scope,
                    "denominator": denominator,
                    "mean_storage_r1_e3_minus_e1": _mean([float(row["storage_r1_e3_minus_e1"]) for row in rows]),
                    "mean_storage_r2_e4_minus_e2": _mean([float(row["storage_r2_e4_minus_e2"]) for row in rows]),
                    "mean_retrieval_s1_e2_minus_e1": _mean([float(row["retrieval_s1_e2_minus_e1"]) for row in rows]),
                    "mean_retrieval_s2_e4_minus_e3": _mean([float(row["retrieval_s2_e4_minus_e3"]) for row in rows]),
                    "mean_did": _mean(did),
                    "median_did": _median(did),
                    "minimum_did": min(did),
                    "maximum_did": max(did),
                    "maximum_absolute_algebraic_residual": max(abs(value) for value in residuals),
                    "increase_count": raw_counts["increase"],
                    "same_count": raw_counts["same"],
                    "decrease_count": raw_counts["decrease"],
                    "win_count": oriented_counts["win"] if spec.direction is not None else None,
                    "tie_count": oriented_counts["tie"] if spec.direction is not None else None,
                    "loss_count": oriented_counts["loss"] if spec.direction is not None else None,
                }
            )
    return output


def _bootstrap_intervals(
    paired_rows: Sequence[Mapping[str, Any]],
    interaction_rows: Sequence[Mapping[str, Any]],
) -> tuple[list[dict[str, Any]], str]:
    simple: dict[tuple[str, str, str], list[Mapping[str, Any]]] = defaultdict(list)
    for row in paired_rows:
        if row["metric_id"] in BOOTSTRAP_METRICS:
            simple[(str(row["backbone_id"]), str(row["contrast_id"]), str(row["metric_id"]))].append(row)
    interactions: dict[tuple[str, str], list[Mapping[str, Any]]] = defaultdict(list)
    for row in interaction_rows:
        if row["metric_id"] in BOOTSTRAP_METRICS:
            interactions[(str(row["backbone_id"]), str(row["metric_id"]))].append(row)
    vectors: dict[tuple[str, str, str], list[float]] = {}
    for backbone in BACKBONES:
        for contrast in CONTRASTS:
            for metric_id in BOOTSTRAP_METRICS:
                rows = sorted(
                    simple[(backbone, contrast.contrast_id, metric_id)],
                    key=lambda row: int(row["global_position"]),
                )
                _require(len(rows) == QUESTION_COUNT, "Bootstrap simple vector differs")
                vectors[(backbone, contrast.contrast_id, metric_id)] = [float(row["raw_difference"]) for row in rows]
        for metric_id in BOOTSTRAP_METRICS:
            rows = sorted(interactions[(backbone, metric_id)], key=lambda row: int(row["global_position"]))
            _require(len(rows) == QUESTION_COUNT, "Bootstrap interaction vector differs")
            vectors[(backbone, "storage_retrieval_interaction", metric_id)] = [
                float(row["did_storage_form"]) for row in rows
            ]

    rng = random.Random(BOOTSTRAP_SEED)
    sample_digest = hashlib.sha256()
    distributions: dict[tuple[str, str, str], list[float]] = {key: [] for key in vectors}
    for _ in range(BOOTSTRAP_REPLICATES):
        indices = [rng.randrange(QUESTION_COUNT) for _ in range(QUESTION_COUNT)]
        sample_digest.update(bytes(indices))
        for key, vector in vectors.items():
            distributions[key].append(math.fsum(vector[index] for index in indices) / QUESTION_COUNT)

    output: list[dict[str, Any]] = []
    effect_order = [contrast.contrast_id for contrast in CONTRASTS] + ["storage_retrieval_interaction"]
    for backbone in BACKBONES:
        for effect_id in effect_order:
            for metric_id in BOOTSTRAP_METRICS:
                values = sorted(distributions[(backbone, effect_id, metric_id)])
                point = _mean(vectors[(backbone, effect_id, metric_id)])
                identity = {"backbone_id": backbone, "effect_id": effect_id, "metric_id": metric_id}
                output.append(
                    {
                        "bootstrap_interval_id": _id("stage-b-bootstrap-", identity),
                        "protocol_version": STAGE_B_PROTOCOL_VERSION,
                        "backbone_id": backbone,
                        "answer_set_id": EXPECTED_ANSWER_SETS[backbone],
                        "effect_id": effect_id,
                        "effect_type": "interaction" if effect_id == "storage_retrieval_interaction" else "simple_contrast",
                        "metric_id": metric_id,
                        "point_estimate": point,
                        "confidence_level": 0.95,
                        "ci_lower": _type7_quantile(values, BOOTSTRAP_LOWER_QUANTILE),
                        "ci_upper": _type7_quantile(values, BOOTSTRAP_UPPER_QUANTILE),
                        "interval_method": "paired_percentile_type7",
                        "resampling_unit": "question_id_complete_e1_e4_block",
                        "question_count": QUESTION_COUNT,
                        "replicates": BOOTSTRAP_REPLICATES,
                        "random_seed": BOOTSTRAP_SEED,
                        "missing_value_policy": "hard_failure_no_imputation",
                        "sample_index_sha256": sample_digest.hexdigest(),
                    }
                )
    return output, sample_digest.hexdigest()


def _figure_5_3_data(condition_rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    selected = {"token_f1", "strict_accuracy", "soft_semantic_score", "evidence_recall"}
    output: list[dict[str, Any]] = []
    for row in condition_rows:
        if row["metric_id"] not in selected:
            continue
        identity = {
            "backbone_id": row["backbone_id"],
            "condition_id": row["condition_id"],
            "metric_id": row["metric_id"],
        }
        output.append(
            {
                "plot_row_id": _id("stage-b-figure-5-3-", identity),
                "protocol_version": STAGE_B_PROTOCOL_VERSION,
                "figure_id": "Figure 5.3",
                "backbone_id": row["backbone_id"],
                "condition_id": row["condition_id"],
                "storage_representation": row["storage_representation"],
                "retrieval_system": row["retrieval_system"],
                "metric_id": row["metric_id"],
                "denominator": row["denominator"],
                "mean": row["mean"],
            }
        )
    return output


def _no_text_bearing_fields(tables: Mapping[str, Sequence[Mapping[str, Any]]]) -> bool:
    for rows in tables.values():
        for row in rows:
            for field in row:
                lowered = field.lower()
                if any(fragment in lowered for fragment in TEXT_BEARING_FIELD_FRAGMENTS):
                    return False
    return True


def _field_schema(tables: Mapping[str, Sequence[Mapping[str, Any]]]) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "protocol_version": STAGE_B_PROTOCOL_VERSION,
        "row_key_policy": "artifact-specific deterministic SHA-256 identifiers",
        "tie_tolerance": TIE_TOLERANCE,
        "algebra_tolerance": ALGEBRA_TOLERANCE,
        "tables": {
            name: {
                "row_count": len(rows),
                "fields": list(rows[0]) if rows else [],
            }
            for name, rows in tables.items()
        },
        "multi_gold_source_definition": (
            "Questions with more than one distinct gold dialogue-turn ID; the reported coverage metric "
            "is Evidence Recall restricted to that frozen 19-question subset."
        ),
    }


def _source_manifest(
    repo_root: Path,
    stage_a_dir: Path,
    provenance: Mapping[str, Any],
    input_audit: Mapping[str, Any],
    bootstrap_sample_sha256: str,
) -> dict[str, Any]:
    body = {
        "schema_version": 1,
        "protocol_version": STAGE_B_PROTOCOL_VERSION,
        "scope": "unified Main-60 E1--E4 raw 2x2 core",
        "stage_a_directory": _relative(repo_root, stage_a_dir),
        **dict(provenance),
        "input_rows": EXPECTED_STAGE_B_ROWS,
        "backbones": list(BACKBONES),
        "conditions": list(STAGE_B_CONDITIONS),
        "answer_denominator": QUESTION_COUNT,
        "evidence_denominator": EVIDENCE_ELIGIBLE_COUNT,
        "multi_gold_source_denominator": EXPECTED_MULTI_GOLD_SOURCE_COUNT,
        "input_question_order_sha256": input_audit["ordered_question_ids_sha256"],
        "bootstrap": {
            "replicates": BOOTSTRAP_REPLICATES,
            "seed": BOOTSTRAP_SEED,
            "resampling_unit": "question_id_complete_e1_e4_block",
            "missing_value_policy": "hard_failure_no_imputation",
            "interval": [BOOTSTRAP_LOWER_QUANTILE, BOOTSTRAP_UPPER_QUANTILE],
            "quantile_method": "type7_linear",
            "sample_index_sha256": bootstrap_sample_sha256,
        },
        "no_api_calls": True,
        "formal_source_mutation": False,
    }
    return {"source_manifest_id": "stage-b-sources-" + sha256_bytes(canonical_json_bytes(body)), **body}


def _artifact_payloads(
    tables: Mapping[str, Sequence[Mapping[str, Any]]],
    source_manifest: Mapping[str, Any],
) -> dict[str, bytes]:
    schema = _field_schema(tables)
    payloads: dict[str, bytes] = {
        "README.md": _readme().encode("utf-8"),
        "schema.json": canonical_json_bytes(schema) + b"\n",
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
        "protocol_version": STAGE_B_PROTOCOL_VERSION,
        "status": "passed",
        "scope": "unified Main-60 E1--E4 raw 2x2 core",
        "no_api_calls": True,
        "formal_source_mutation": False,
        "stage_c_or_d_computed": False,
        "stage_c_or_later_computed": False,
        "cross_backbone_effect_computed": False,
        "input_audit": audits["input_audit"],
        "table_audit": audits["table_audit"],
        "source_manifest_id": source_manifest["source_manifest_id"],
        "stage_a_audit_id": provenance["stage_a_audit_id"],
        "output_sha256": dict(output_hashes),
    }


def _marker_body(audit: Mapping[str, Any], audit_sha256: str) -> dict[str, Any]:
    return {
        "status": "passed",
        "protocol_version": STAGE_B_PROTOCOL_VERSION,
        "audit_id": audit["audit_id"],
        "audit_sha256": audit_sha256,
        "input_rows": EXPECTED_STAGE_B_ROWS,
        "question_count": QUESTION_COUNT,
        "answer_denominator": QUESTION_COUNT,
        "evidence_denominator": EVIDENCE_ELIGIBLE_COUNT,
        "effect_units": len(BACKBONES) * (len(CONTRASTS) + 1),
        "bootstrap_replicates": BOOTSTRAP_REPLICATES,
    }


def _audit_tables(
    input_audit: Mapping[str, Any],
    tables: Mapping[str, Sequence[Mapping[str, Any]]],
    bootstrap_sample_sha256: str,
) -> dict[str, Any]:
    condition_rows = tables["condition-summaries"]
    paired_rows = tables["paired-question-effects"]
    aggregate_rows = tables["aggregate-effects"]
    strict_rows = tables["strict-transitions"]
    semantic_rows = tables["semantic-transitions"]
    interaction_rows = tables["interaction-question-effects"]
    interaction_aggregates = tables["interaction-aggregates"]
    bootstrap_rows = tables["bootstrap-intervals"]
    figure_rows = tables["figure-5-3-data"]

    answer_pair_rows = [row for row in paired_rows if row["denominator_scope"] == "answer_all"]
    evidence_pair_rows = [row for row in paired_rows if row["denominator_scope"] == "evidence_eligible"]
    multi_pair_rows = [row for row in paired_rows if row["denominator_scope"] == "multi_gold_source_evidence_eligible"]

    condition_map = {
        (str(row["backbone_id"]), str(row["condition_id"]), str(row["metric_id"])): row
        for row in condition_rows
    }
    aggregate_map = {
        (str(row["backbone_id"]), str(row["contrast_id"]), str(row["metric_id"])): row
        for row in aggregate_rows
    }
    interaction_map = {
        (str(row["backbone_id"]), str(row["metric_id"])): row for row in interaction_aggregates
    }
    paired_groups: dict[tuple[str, str, str], list[Mapping[str, Any]]] = defaultdict(list)
    for row in paired_rows:
        paired_groups[(str(row["backbone_id"]), str(row["contrast_id"]), str(row["metric_id"]))].append(row)
    interaction_groups: dict[tuple[str, str], list[Mapping[str, Any]]] = defaultdict(list)
    for row in interaction_rows:
        interaction_groups[(str(row["backbone_id"]), str(row["metric_id"]))].append(row)

    aggregate_recomputes = True
    condition_alignment = True
    state_totals = True
    neutral_metrics_unoriented = True
    for key, aggregate in aggregate_map.items():
        backbone, contrast_id, metric_id = key
        spec = METRIC_BY_ID[metric_id]
        contrast = CONTRAST_BY_ID[contrast_id]
        rows = paired_groups[key]
        differences = [float(row["raw_difference"]) for row in rows]
        raw = Counter(str(row["raw_state"]) for row in rows)
        oriented = Counter(str(row["oriented_state"]) for row in rows if row["oriented_state"] is not None)
        expected_denominator = _expected_denominator(spec)
        aggregate_recomputes = aggregate_recomputes and (
            len(rows) == expected_denominator
            and _is_close(float(aggregate["baseline_mean"]), _mean([float(row["baseline_value"]) for row in rows]))
            and _is_close(float(aggregate["target_mean"]), _mean([float(row["target_value"]) for row in rows]))
            and _is_close(float(aggregate["mean_difference"]), _mean(differences))
            and _is_close(float(aggregate["median_difference"]), _median(differences))
            and _is_close(
                float(aggregate["mean_difference"]),
                float(aggregate["target_mean"]) - float(aggregate["baseline_mean"]),
            )
            and int(aggregate["increase_count"]) == raw["increase"]
            and int(aggregate["same_count"]) == raw["same"]
            and int(aggregate["decrease_count"]) == raw["decrease"]
        )
        condition_alignment = condition_alignment and (
            _is_close(
                float(aggregate["baseline_mean"]),
                float(condition_map[(backbone, contrast.baseline_condition, metric_id)]["mean"]),
            )
            and _is_close(
                float(aggregate["target_mean"]),
                float(condition_map[(backbone, contrast.target_condition, metric_id)]["mean"]),
            )
        )
        state_totals = state_totals and (
            int(aggregate["increase_count"])
            + int(aggregate["same_count"])
            + int(aggregate["decrease_count"])
            == expected_denominator
        )
        if spec.direction is None:
            neutral_metrics_unoriented = neutral_metrics_unoriented and (
                aggregate["win_count"] is None
                and aggregate["tie_count"] is None
                and aggregate["loss_count"] is None
                and all(row["oriented_difference"] is None and row["oriented_state"] is None for row in rows)
            )
        else:
            state_totals = state_totals and (
                int(aggregate["win_count"])
                + int(aggregate["tie_count"])
                + int(aggregate["loss_count"])
                == expected_denominator
                and int(aggregate["win_count"]) == oriented["win"]
                and int(aggregate["tie_count"]) == oriented["tie"]
                and int(aggregate["loss_count"]) == oriented["loss"]
            )

    interaction_recomputes = True
    interaction_component_alignment = True
    interaction_condition_identity = True
    for key, aggregate in interaction_map.items():
        backbone, metric_id = key
        spec = METRIC_BY_ID[metric_id]
        rows = interaction_groups[key]
        did = [float(row["did_storage_form"]) for row in rows]
        expected_denominator = _expected_denominator(spec)
        interaction_recomputes = interaction_recomputes and (
            len(rows) == expected_denominator
            and _is_close(float(aggregate["mean_did"]), _mean(did))
            and _is_close(float(aggregate["median_did"]), _median(did))
            and max(abs(float(row["algebraic_residual"])) for row in rows) <= ALGEBRA_TOLERANCE
        )
        interaction_component_alignment = interaction_component_alignment and all(
            _is_close(
                float(aggregate[field]),
                float(aggregate_map[(backbone, contrast_id, metric_id)]["mean_difference"]),
            )
            for field, contrast_id in (
                ("mean_storage_r1_e3_minus_e1", "storage_r1_e3_minus_e1"),
                ("mean_storage_r2_e4_minus_e2", "storage_r2_e4_minus_e2"),
                ("mean_retrieval_s1_e2_minus_e1", "retrieval_s1_e2_minus_e1"),
                ("mean_retrieval_s2_e4_minus_e3", "retrieval_s2_e4_minus_e3"),
            )
        )
        condition_means = {
            condition: float(condition_map[(backbone, condition, metric_id)]["mean"])
            for condition in STAGE_B_CONDITIONS
        }
        expected_did = (condition_means["E4"] - condition_means["E2"]) - (
            condition_means["E3"] - condition_means["E1"]
        )
        interaction_condition_identity = interaction_condition_identity and _is_close(
            float(aggregate["mean_did"]), expected_did
        )

    strict_transition_alignment = True
    semantic_fold_alignment = True
    for backbone in BACKBONES:
        for contrast in CONTRASTS:
            strict_counts = {
                str(row["transition_id"]): int(row["count"])
                for row in strict_rows
                if row["backbone_id"] == backbone and row["contrast_id"] == contrast.contrast_id
            }
            strict_aggregate = aggregate_map[(backbone, contrast.contrast_id, "strict_accuracy")]
            strict_transition_alignment = strict_transition_alignment and (
                strict_counts.get("strict_not_correct_to_correct", -1) == strict_aggregate["win_count"]
                and strict_counts.get("strict_correct_to_not_correct", -1) == strict_aggregate["loss_count"]
                and strict_counts.get("strict_unchanged_correct", -1)
                + strict_counts.get("strict_unchanged_not_correct", -1)
                == strict_aggregate["tie_count"]
            )
            matrix = {
                (str(row["baseline_label"]), str(row["target_label"])): int(row["count"])
                for row in semantic_rows
                if row["backbone_id"] == backbone and row["contrast_id"] == contrast.contrast_id
            }
            labels = ("correct", "partial", "incorrect")
            semantic_fold_alignment = semantic_fold_alignment and (
                matrix[("correct", "correct")] == strict_counts["strict_unchanged_correct"]
                and sum(matrix[(label, "correct")] for label in labels if label != "correct")
                == strict_counts["strict_not_correct_to_correct"]
                and sum(matrix[("correct", label)] for label in labels if label != "correct")
                == strict_counts["strict_correct_to_not_correct"]
                and sum(
                    matrix[(baseline, target)]
                    for baseline in labels
                    if baseline != "correct"
                    for target in labels
                    if target != "correct"
                )
                == strict_counts["strict_unchanged_not_correct"]
            )

    bootstrap_point_alignment = True
    for row in bootstrap_rows:
        if row["effect_type"] == "interaction":
            expected = interaction_map[(str(row["backbone_id"]), str(row["metric_id"]))]["mean_did"]
        else:
            expected = aggregate_map[
                (str(row["backbone_id"]), str(row["effect_id"]), str(row["metric_id"]))
            ]["mean_difference"]
        bootstrap_point_alignment = bootstrap_point_alignment and _is_close(
            float(row["point_estimate"]), float(expected)
        )

    figure_alignment = all(
        _is_close(
            float(row["mean"]),
            float(condition_map[(str(row["backbone_id"]), str(row["condition_id"]), str(row["metric_id"]))]["mean"]),
        )
        and int(row["denominator"])
        == int(condition_map[(str(row["backbone_id"]), str(row["condition_id"]), str(row["metric_id"]))]["denominator"])
        for row in figure_rows
    )

    primary_id_fields = {
        "condition-summaries": "condition_summary_id",
        "paired-question-effects": "paired_effect_id",
        "aggregate-effects": "aggregate_effect_id",
        "strict-transitions": "strict_transition_row_id",
        "semantic-transitions": "semantic_transition_row_id",
        "interaction-question-effects": "interaction_effect_id",
        "interaction-aggregates": "interaction_aggregate_id",
        "bootstrap-intervals": "bootstrap_interval_id",
        "figure-5-3-data": "plot_row_id",
    }
    all_ids = [
        str(row[primary_id_fields[table_name]])
        for table_name, rows in tables.items()
        for row in rows
    ]
    checks = {
        "stage_a_input_rows_480": input_audit["input_rows"] == EXPECTED_STAGE_B_ROWS,
        "same_60_questions_in_eight_cells": input_audit["question_count"] == QUESTION_COUNT
        and set(input_audit["cell_counts"].values()) == {QUESTION_COUNT},
        "categories_13_13_7_27_each_cell": all(
            counts == {str(key): value for key, value in EXPECTED_CATEGORIES.items()}
            for counts in input_audit["category_counts_per_cell"].values()
        ),
        "evidence_categories_13_13_5_27_each_cell": all(
            counts == {str(key): value for key, value in EXPECTED_EVIDENCE_CATEGORIES.items()}
            for counts in input_audit["evidence_category_counts_per_cell"].values()
        ),
        "fixed_two_evidence_ineligible_questions": set(input_audit["evidence_ineligible_question_ids"])
        == EXPECTED_INELIGIBLE_QUESTION_IDS,
        "evidence_denominator_58": input_audit["evidence_denominator"] == EVIDENCE_ELIGIBLE_COUNT,
        "multi_gold_source_denominator_19": input_audit["multi_gold_source_denominator"] == EXPECTED_MULTI_GOLD_SOURCE_COUNT,
        "condition_summary_rows_104": len(condition_rows) == len(BACKBONES) * len(STAGE_B_CONDITIONS) * len(METRICS),
        "paired_question_rows_expected": len(paired_rows)
        == len(BACKBONES)
        * len(CONTRASTS)
        * (
            len(ANSWER_METRICS) * QUESTION_COUNT
            + len(EVIDENCE_METRICS) * EVIDENCE_ELIGIBLE_COUNT
            + len(MULTI_GOLD_SOURCE_METRICS) * EXPECTED_MULTI_GOLD_SOURCE_COUNT
        ),
        "answer_pair_denominators_60": len(answer_pair_rows)
        == len(BACKBONES) * len(CONTRASTS) * len(ANSWER_METRICS) * QUESTION_COUNT,
        "evidence_pair_denominators_58": len(evidence_pair_rows)
        == len(BACKBONES) * len(CONTRASTS) * len(EVIDENCE_METRICS) * EVIDENCE_ELIGIBLE_COUNT,
        "multi_source_pair_denominators_19": len(multi_pair_rows)
        == len(BACKBONES) * len(CONTRASTS) * len(MULTI_GOLD_SOURCE_METRICS) * EXPECTED_MULTI_GOLD_SOURCE_COUNT,
        "aggregate_effect_rows_104": len(aggregate_rows) == len(BACKBONES) * len(CONTRASTS) * len(METRICS),
        "strict_transition_rows_32": len(strict_rows) == len(BACKBONES) * len(CONTRASTS) * 4,
        "strict_transition_totals_60": all(
            sum(
                int(row["count"])
                for row in strict_rows
                if row["backbone_id"] == backbone and row["contrast_id"] == contrast.contrast_id
            )
            == QUESTION_COUNT
            for backbone in BACKBONES
            for contrast in CONTRASTS
        ),
        "semantic_transition_rows_72": len(semantic_rows) == len(BACKBONES) * len(CONTRASTS) * 9,
        "semantic_transition_totals_60": all(
            sum(
                int(row["count"])
                for row in semantic_rows
                if row["backbone_id"] == backbone and row["contrast_id"] == contrast.contrast_id
            )
            == QUESTION_COUNT
            for backbone in BACKBONES
            for contrast in CONTRASTS
        ),
        "interaction_question_rows_expected": len(interaction_rows)
        == len(BACKBONES)
        * (
            len(ANSWER_METRICS) * QUESTION_COUNT
            + len(EVIDENCE_METRICS) * EVIDENCE_ELIGIBLE_COUNT
            + len(MULTI_GOLD_SOURCE_METRICS) * EXPECTED_MULTI_GOLD_SOURCE_COUNT
        ),
        "interaction_aggregate_rows_26": len(interaction_aggregates) == len(BACKBONES) * len(METRICS),
        "did_formulae_equivalent": all(abs(float(row["algebraic_residual"])) <= ALGEBRA_TOLERANCE for row in interaction_rows),
        "aggregate_rows_recompute_from_question_pairs": aggregate_recomputes,
        "aggregate_condition_means_align": condition_alignment,
        "paired_state_totals_match_denominators": state_totals,
        "neutral_metrics_are_not_oriented": neutral_metrics_unoriented,
        "interaction_rows_recompute": interaction_recomputes,
        "interaction_components_align_with_simple_effects": interaction_component_alignment,
        "interaction_equals_condition_mean_did": interaction_condition_identity,
        "strict_transitions_align_with_strict_effects": strict_transition_alignment,
        "semantic_transitions_fold_to_strict_transitions": semantic_fold_alignment,
        "bootstrap_rows_30": len(bootstrap_rows)
        == len(BACKBONES) * (len(CONTRASTS) + 1) * len(BOOTSTRAP_METRICS),
        "bootstrap_protocol_exact": all(
            row["replicates"] == BOOTSTRAP_REPLICATES
            and row["random_seed"] == BOOTSTRAP_SEED
            and row["sample_index_sha256"] == bootstrap_sample_sha256
            and row["missing_value_policy"] == "hard_failure_no_imputation"
            and row["interval_method"] == "paired_percentile_type7"
            for row in bootstrap_rows
        ),
        "bootstrap_intervals_ordered": all(
            math.isfinite(float(row["ci_lower"]))
            and math.isfinite(float(row["point_estimate"]))
            and math.isfinite(float(row["ci_upper"]))
            and float(row["ci_lower"]) <= float(row["ci_upper"])
            for row in bootstrap_rows
        ),
        "bootstrap_points_align_with_effects": bootstrap_point_alignment,
        "figure_5_3_rows_32": len(figure_rows) == len(BACKBONES) * len(STAGE_B_CONDITIONS) * 4,
        "figure_5_3_values_align": figure_alignment,
        "artifact_row_ids_unique": len(all_ids) == len(set(all_ids)),
        "no_text_bearing_fields": _no_text_bearing_fields(tables),
        "only_frozen_backbones_and_answer_sets": all(
            row["backbone_id"] in BACKBONES
            and (
                "answer_set_id" not in row
                or row["answer_set_id"] == EXPECTED_ANSWER_SETS[row["backbone_id"]]
            )
            for rows in tables.values()
            for row in rows
            if "backbone_id" in row
        ),
        "only_e1_e4_conditions": all(
            condition in STAGE_B_CONDITIONS
            for rows in tables.values()
            for row in rows
            for condition in (
                [row["condition_id"]] if "condition_id" in row else []
            )
        ),
        "only_e1_e4_contrast_endpoints": all(
            row.get("baseline_condition") in STAGE_B_CONDITIONS
            and row.get("target_condition") in STAGE_B_CONDITIONS
            for rows in tables.values()
            for row in rows
            if "baseline_condition" in row or "target_condition" in row
        ),
    }
    _require(all(checks.values()), "Stage B table audit failed")
    return {
        "checks": checks,
        "table_rows": {name: len(rows) for name, rows in tables.items()},
        "answer_denominator": QUESTION_COUNT,
        "evidence_denominator": EVIDENCE_ELIGIBLE_COUNT,
        "multi_gold_source_denominator": EXPECTED_MULTI_GOLD_SOURCE_COUNT,
        "effect_units": len(BACKBONES) * (len(CONTRASTS) + 1),
        "bootstrap_sample_index_sha256": bootstrap_sample_sha256,
    }


def _compute_stage_b(stage_a_dir: Path) -> tuple[
    dict[str, list[dict[str, Any]]],
    dict[str, Any],
    dict[str, Any],
    str,
]:
    input_rows, provenance = _load_stage_a_input(stage_a_dir)
    input_audit = _validate_input(input_rows)
    index, ordered_questions = _index_rows(input_rows)
    condition_rows = _condition_summaries(index, ordered_questions)
    paired_rows = _paired_question_effects(index, ordered_questions)
    aggregate_rows = _aggregate_effects(paired_rows)
    strict_rows, semantic_rows = _semantic_transitions(index, ordered_questions)
    interaction_rows = _interaction_question_effects(index, ordered_questions)
    interaction_aggregates = _interaction_aggregates(interaction_rows)
    bootstrap_rows, bootstrap_sample_sha256 = _bootstrap_intervals(paired_rows, interaction_rows)
    figure_rows = _figure_5_3_data(condition_rows)
    tables = {
        "condition-summaries": condition_rows,
        "paired-question-effects": paired_rows,
        "aggregate-effects": aggregate_rows,
        "strict-transitions": strict_rows,
        "semantic-transitions": semantic_rows,
        "interaction-question-effects": interaction_rows,
        "interaction-aggregates": interaction_aggregates,
        "bootstrap-intervals": bootstrap_rows,
        "figure-5-3-data": figure_rows,
    }
    table_audit = _audit_tables(input_audit, tables, bootstrap_sample_sha256)
    return tables, provenance, {"input_audit": input_audit, "table_audit": table_audit}, bootstrap_sample_sha256


def _readme() -> str:
    return """# Chapter 5 Stage B: E1--E4 raw 2x2 core

This directory contains the audited within-backbone paired analysis for the
E1--E4 raw-memory 2x2 experiment. It estimates four simple contrasts and the
storage--retrieval interaction separately for Qwen and DeepSeek.

Answer metrics use all 60 Main-60 questions. Evidence metrics use only the
fixed 58-question Evidence-eligible mask. `multi_gold_source_*` metrics are
explicitly restricted to the frozen 19-question subset with more than one
distinct annotated gold dialogue-turn ID; they are not a renamed All-hit
metric and are never mixed with the 58-question denominator.

The paired tables use fixed target-minus-baseline directions. Partial Rate and
EvidenceBundle length are neutral descriptive metrics, so they have raw
increase/same/decrease states but no quality-oriented win/tie/loss label.
Strict binary transitions use `not_correct` for all non-correct Judge labels;
the separate 3x3 semantic table preserves correct/partial/incorrect.

Bootstrap intervals use 10,000 complete-question-block resamples, seed
20261021, Type-7 percentile interpolation, and no missing-value imputation.
They describe resampling stability over the observed Main-60 questions only.

No API is called, no formal source result is modified, and no question,
reference answer, candidate answer, Evidence text, or Judge rationale is
stored. Stage C/D analyses and final RQ1 conclusions are outside this stage.
"""


def build_stage_b(*, repo_root: Path, stage_a_dir: Path, output_dir: Path) -> dict[str, Any]:
    root = repo_root.resolve()
    source = stage_a_dir.resolve()
    destination = output_dir.resolve()
    _require(root.is_dir() and not root.is_symlink(), "Repository root is unsafe")
    _require(source.is_dir() and not source.is_symlink(), "Stage A input directory is unsafe")
    _require(not destination.exists() and not destination.is_symlink(), "Stage B output already exists")
    tables, provenance, audits, sample_sha256 = _compute_stage_b(source)
    source_manifest = _source_manifest(root, source, provenance, audits["input_audit"], sample_sha256)
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
        audit = {"audit_id": "stage-b-audit-" + sha256_bytes(canonical_json_bytes(body)), **body}
        _write(temporary / "audit.json", canonical_json_bytes(audit) + b"\n")
        marker = _marker_body(audit, _sha256_file(temporary / "audit.json"))
        _write(temporary / "STAGE-B.PASSED", canonical_json_bytes(marker) + b"\n")

        # The complete candidate is independently recomputed and byte-audited
        # before its directory can become the formal Stage B publication.
        prepublish = audit_stage_b_output(stage_a_dir=source, output_dir=temporary)
        _require(prepublish.get("status") == "passed", "Stage B pre-publication audit failed")
        _require(not destination.exists(), "Stage B output appeared during the build")
        os.rename(temporary, destination)
        descriptor = os.open(parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
    except Exception:
        shutil.rmtree(temporary, ignore_errors=True)
        raise
    return audit_stage_b_output(stage_a_dir=source, output_dir=destination)


def audit_stage_b_output(*, stage_a_dir: Path, output_dir: Path) -> dict[str, Any]:
    source = stage_a_dir.resolve()
    output_root = output_dir.resolve()
    _require(source.is_dir() and not source.is_symlink(), "Stage A input directory is unsafe")
    _require(output_root.is_dir() and not output_root.is_symlink(), "Stage B output directory is unsafe")
    tables, provenance, audits, sample_sha256 = _compute_stage_b(source)
    repo_root = source.parents[2]
    _require(
        (repo_root / "artifacts/chapter5-main60-analysis-v1/stage-a").resolve() == source,
        "Stage A directory is not the frozen repository location",
    )
    expected_manifest = _source_manifest(
        repo_root,
        source,
        provenance,
        audits["input_audit"],
        sample_sha256,
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
        "audit_id": "stage-b-audit-" + sha256_bytes(canonical_json_bytes(expected_body)),
        **expected_body,
    }
    expected_audit_payload = canonical_json_bytes(expected_audit) + b"\n"
    expected_marker = _marker_body(expected_audit, hashlib.sha256(expected_audit_payload).hexdigest())
    expected_marker_payload = canonical_json_bytes(expected_marker) + b"\n"
    expected_names = set(expected_payloads) | {"audit.json", "STAGE-B.PASSED"}
    entries = list(output_root.iterdir())
    _require(
        all(entry.is_file() and not entry.is_symlink() for entry in entries),
        "Stage B output contains a non-regular entry",
    )
    _require({entry.name for entry in entries} == expected_names, "Stage B output file set differs")

    for name, expected_payload in expected_payloads.items():
        _require(
            (output_root / name).read_bytes() == expected_payload,
            f"Stage B artifact bytes differ from independent recomputation: {name}",
        )
    _require((output_root / "audit.json").read_bytes() == expected_audit_payload, "Stage B audit bytes differ")
    _require((output_root / "STAGE-B.PASSED").read_bytes() == expected_marker_payload, "Stage B marker bytes differ")

    audit = _read_json(output_root / "audit.json")
    marker = _read_json(output_root / "STAGE-B.PASSED")
    audit_body = {key: value for key, value in audit.items() if key != "audit_id"}
    _require(
        audit.get("audit_id") == "stage-b-audit-" + sha256_bytes(canonical_json_bytes(audit_body)),
        "Stage B audit ID does not recompute",
    )
    _require(audit == expected_audit, "Stage B audit differs from independent recomputation")
    _require(marker == expected_marker, "Stage B marker differs from independent recomputation")
    for name, digest in expected_output_hashes.items():
        _require(_sha256_file(output_root / name) == digest, f"Stage B output hash differs: {name}")

    return {
        "status": "passed",
        "protocol_version": STAGE_B_PROTOCOL_VERSION,
        "audit_id": expected_audit["audit_id"],
        "input_rows": audits["input_audit"]["input_rows"],
        "question_count": QUESTION_COUNT,
        "effect_units": audits["table_audit"]["effect_units"],
        "table_rows": audits["table_audit"]["table_rows"],
        "bootstrap_replicates": BOOTSTRAP_REPLICATES,
        "output_dir": str(output_root),
        "no_api_calls": True,
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build or audit Chapter 5 Stage B artifacts")
    parser.add_argument("command", choices=("build", "audit"))
    parser.add_argument("--repo-root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--stage-a-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    return parser


def main(argv: list[str] | None = None) -> None:
    args = _parser().parse_args(argv)
    if args.command == "build":
        result = build_stage_b(
            repo_root=args.repo_root,
            stage_a_dir=args.stage_a_dir,
            output_dir=args.output_dir,
        )
    else:
        result = audit_stage_b_output(stage_a_dir=args.stage_a_dir, output_dir=args.output_dir)
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
