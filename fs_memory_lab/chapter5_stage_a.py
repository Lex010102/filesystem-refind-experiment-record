"""Build and audit the frozen Chapter 5 question-level analysis table.

Stage A is deliberately read-only with respect to every formal answer and
judgment run.  It validates the archived records, recomputes the unified
category-aware token metrics in memory, joins by explicit identities, and
publishes text-free numeric/provenance tables for later paired analysis.

The output contains three nested scopes:

* 900 rows in the complete master table (Qwen E1--E7, DeepSeek E1--E7,
  and DeepSeek-family Full Context);
* 840 rows in the symmetric E1--E7 view;
* 720 rows in the RQ1 E1--E6 view.

No RQ1 effect estimate is computed here.  That belongs to Stage B onward.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import shutil
import tempfile
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from .evaluation import (
    GoldRecord,
    evaluate_run_record,
    load_gold_records,
    locomo_category_f1,
    normalize_answer,
)
from .evidence import EvidenceValidationError, canonical_json_bytes, sha256_bytes
from .full_context_runner import (
    FULL_CONTEXT_CONDITION_ID,
    FULL_CONTEXT_REQUIRED_SERVED_MODEL,
    full_context_record_from_mapping,
)
from .judge_main60 import REQUIRED_SERVED_MODEL as JUDGE_REQUIRED_SERVED_MODEL
from .locomo_prf_cli import _category_precision_recall
from .run_records import (
    RunKey,
    RunRecord,
    run_failure_from_mapping,
    run_plan_from_mapping,
    run_record_from_mapping,
)


STAGE_A_PROTOCOL_VERSION = "chapter5-main60-stage-a-v1"
MASTER_ROW_COUNT = 900
E1_E7_ROW_COUNT = 840
RQ1_ROW_COUNT = 720
QUESTION_COUNT = 60
EVIDENCE_ELIGIBLE_COUNT = 58
CONDITIONS = tuple(f"E{index}" for index in range(1, 8))
RQ1_CONDITIONS = tuple(f"E{index}" for index in range(1, 7))
EXPECTED_CATEGORIES = {1: 13, 2: 13, 3: 7, 4: 27}
GOLD_HASHES = {
    "main40": "a6833ca585ca26efcdd038a5cf202fd46657999053ebd7b8cc73793f7544718b",
    "extension20": "c8b08771af27537579e418db0ace600076cd09108019fc86cd584740bb035ec8",
}

CONDITION_DESIGN: dict[str, dict[str, str]] = {
    "E1": {"storage_representation": "S1", "retrieval_system": "R1", "access_regime": "selective_retrieval"},
    "E2": {"storage_representation": "S1", "retrieval_system": "R2", "access_regime": "selective_retrieval"},
    "E3": {"storage_representation": "S2", "retrieval_system": "R1", "access_regime": "selective_retrieval"},
    "E4": {"storage_representation": "S2", "retrieval_system": "R2", "access_regime": "selective_retrieval"},
    "E5": {"storage_representation": "S3", "retrieval_system": "R1", "access_regime": "selective_retrieval"},
    "E6": {"storage_representation": "S3", "retrieval_system": "R3", "access_regime": "selective_retrieval"},
    "E7": {"storage_representation": "E2+E6", "retrieval_system": "fixed_fusion", "access_regime": "dual_source_fusion"},
    FULL_CONTEXT_CONDITION_ID: {
        "storage_representation": "complete_S1_raw_history",
        "retrieval_system": "none",
        "access_regime": "full_context",
    },
}


@dataclass(frozen=True)
class PartitionSpec:
    backbone_id: str
    answer_set_id: str
    source_partition: str
    run_root: Path
    run_id: str
    gold_path: Path
    gold_sha256: str


@dataclass(frozen=True)
class LoadedRecord:
    record: RunRecord
    path: Path
    file_sha256: str
    payload_sha256: str
    failure_attempts: int
    source_partition: str


def _sha256_file(path: Path) -> str:
    lexical = Path(path)
    if lexical.is_symlink() or not lexical.is_file():
        raise EvidenceValidationError(f"Unsafe or missing Stage A input: {lexical}")
    digest = hashlib.sha256()
    with lexical.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _read_json(path: Path) -> dict[str, Any]:
    lexical = Path(path)
    if lexical.is_symlink() or not lexical.is_file():
        raise EvidenceValidationError(f"Unsafe or missing Stage A JSON: {lexical}")
    try:
        value = json.loads(lexical.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise EvidenceValidationError(f"Unreadable Stage A JSON: {lexical}") from exc
    if not isinstance(value, dict):
        raise EvidenceValidationError(f"Stage A JSON must be an object: {lexical}")
    return value


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


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise EvidenceValidationError(message)


def _partitions(repo_root: Path) -> tuple[PartitionSpec, ...]:
    root = repo_root.resolve()
    return (
        PartitionSpec(
            "qwen",
            "model1-qwen-main60",
            "main40",
            root / "experiments/locomo-conv50-v1/results/formal-v1-main40-run-02/run",
            "formal-v1-main40-run-02",
            root / "experiments/locomo-conv50-v1/question-sets/main-40-gold.jsonl",
            GOLD_HASHES["main40"],
        ),
        PartitionSpec(
            "qwen",
            "model1-qwen-main60",
            "extension20",
            root / "experiments/locomo-conv50-v1/results/formal-v2-qwen-extension20-run-01/run",
            "formal-v2-qwen-extension20-run-01",
            root / "experiments/locomo-conv50-v1/question-sets-main60-v2/extension-20-gold.jsonl",
            GOLD_HASHES["extension20"],
        ),
        PartitionSpec(
            "deepseek",
            "model2-deepseek-main60",
            "main40",
            root
            / "experiments/locomo-conv50-v1/results/formal-v2-model2-main60-candidate-02/run/children/main40/formal-v2-model2-main60-candidate-02-main40",
            "formal-v2-model2-main60-candidate-02-main40",
            root / "experiments/locomo-conv50-v1/question-sets/main-40-gold.jsonl",
            GOLD_HASHES["main40"],
        ),
        PartitionSpec(
            "deepseek",
            "model2-deepseek-main60",
            "extension20",
            root
            / "experiments/locomo-conv50-v1/results/formal-v2-model2-main60-candidate-02/run/children/extension20/formal-v2-model2-main60-candidate-02-extension20",
            "formal-v2-model2-main60-candidate-02-extension20",
            root / "experiments/locomo-conv50-v1/question-sets-main60-v2/extension-20-gold.jsonl",
            GOLD_HASHES["extension20"],
        ),
    )


def _load_composition(repo_root: Path) -> tuple[dict[str, Any], ...]:
    path = repo_root / "experiments/locomo-conv50-v1/question-sets-main60-v2/main-60-composition.json"
    value = _read_json(path)
    rows = value.get("question_order")
    _require(
        value.get("question_count") == QUESTION_COUNT
        and isinstance(rows, list)
        and len(rows) == QUESTION_COUNT,
        "Main-60 composition count differs",
    )
    output = tuple(dict(row) for row in rows if isinstance(row, Mapping))
    _require(len(output) == QUESTION_COUNT, "Main-60 composition rows are invalid")
    _require(
        [row.get("global_position") for row in output] == list(range(1, QUESTION_COUNT + 1)),
        "Main-60 global order differs",
    )
    _require(
        len({str(row.get("question_id")) for row in output}) == QUESTION_COUNT,
        "Main-60 question IDs repeat",
    )
    return output


def _load_gold(repo_root: Path) -> dict[str, GoldRecord]:
    rows: list[GoldRecord] = []
    for spec in _partitions(repo_root)[:2]:
        rows.extend(load_gold_records(spec.gold_path, expected_sha256=spec.gold_sha256))
    _require(len(rows) == QUESTION_COUNT, "Unified Main-60 gold count differs")
    output = {row.question_id: row for row in rows}
    _require(len(output) == QUESTION_COUNT, "Unified Main-60 gold IDs repeat")
    _require(
        Counter(row.category for row in rows) == Counter(EXPECTED_CATEGORIES),
        "Unified Main-60 category counts differ",
    )
    _require(
        sum(bool(row.gold_evidence_dia_ids) for row in rows) == EVIDENCE_ELIGIBLE_COUNT,
        "Unified Main-60 evidence eligibility differs",
    )
    return output


def _load_partition_records(
    repo_root: Path, spec: PartitionSpec
) -> tuple[dict[tuple[str, str], LoadedRecord], dict[str, GoldRecord], dict[str, Any]]:
    plan_path = spec.run_root / "plan.json"
    plan = run_plan_from_mapping(_read_json(plan_path))
    _require(plan.run_id == spec.run_id, "Archived plan run identity differs")
    gold_rows = load_gold_records(spec.gold_path, expected_sha256=spec.gold_sha256)
    gold = {row.question_id: row for row in gold_rows}
    _require(
        set(gold) == set(plan.question_ids),
        f"Plan/gold membership differs for {spec.run_id}",
    )
    records: dict[tuple[str, str], LoadedRecord] = {}
    record_artifacts: list[dict[str, Any]] = []
    total_failures = 0
    for key in plan.execution_order:
        path = spec.run_root / "records" / key.condition_id / f"{key.question_id}.json"
        mapping = _read_json(path)
        record = run_record_from_mapping(mapping)
        _require(
            record.plan_id == plan.plan_id
            and record.run_id == plan.run_id
            and record.key == key,
            f"RunRecord identity differs: {spec.run_id}/{key.condition_id}/{key.question_id}",
        )
        failure_dir = spec.run_root / "failures" / key.condition_id / key.question_id
        failures = []
        if failure_dir.exists():
            _require(not failure_dir.is_symlink() and failure_dir.is_dir(), "Unsafe failure directory")
            for failure_path in sorted(failure_dir.glob("attempt-*.json")):
                failure = run_failure_from_mapping(_read_json(failure_path))
                _require(
                    failure.plan_id == plan.plan_id
                    and failure.run_id == plan.run_id
                    and failure.key == key,
                    "Failure record identity differs",
                )
                failures.append(failure)
            _require(
                [item.attempt for item in failures] == list(range(1, len(failures) + 1)),
                "Failure attempts are not contiguous",
            )
        total_failures += len(failures)
        identity = (key.condition_id, key.question_id)
        _require(identity not in records, "Partition record identity repeats")
        file_hash = _sha256_file(path)
        payload_hash = sha256_bytes(canonical_json_bytes(mapping))
        records[identity] = LoadedRecord(
            record=record,
            path=path,
            file_sha256=file_hash,
            payload_sha256=payload_hash,
            failure_attempts=len(failures),
            source_partition=spec.source_partition,
        )
        record_artifacts.append(
            {
                "path": _relative(repo_root, path),
                "file_sha256": file_hash,
                "payload_sha256": payload_hash,
                "record_id": record.record_id,
            }
        )
    _require(len(records) == len(plan.execution_order), "Partition record count differs")
    return records, gold, {
        "backbone_id": spec.backbone_id,
        "source_partition": spec.source_partition,
        "run_id": spec.run_id,
        "plan": _artifact(repo_root, plan_path),
        "record_count": len(records),
        "failure_attempt_count": total_failures,
        "records_manifest_sha256": sha256_bytes(canonical_json_bytes(record_artifacts)),
    }


def _load_selective_sources(
    repo_root: Path,
) -> tuple[
    dict[str, dict[tuple[str, str], LoadedRecord]],
    dict[str, GoldRecord],
    list[dict[str, Any]],
]:
    output: dict[str, dict[tuple[str, str], LoadedRecord]] = {"qwen": {}, "deepseek": {}}
    gold_by_id = _load_gold(repo_root)
    manifests: list[dict[str, Any]] = []
    for spec in _partitions(repo_root):
        records, gold, manifest = _load_partition_records(repo_root, spec)
        _require(set(gold).issubset(gold_by_id), "Partition gold exceeds Main-60")
        overlap = set(output[spec.backbone_id]) & set(records)
        _require(not overlap, "Physical run partitions overlap")
        output[spec.backbone_id].update(records)
        manifests.append(manifest)
    expected_keys = {(condition, question_id) for condition in CONDITIONS for question_id in gold_by_id}
    for backbone, records in output.items():
        _require(set(records) == expected_keys, f"{backbone} E1--E7 key set differs")
    _require(set(output["qwen"]) == set(output["deepseek"]), "Backbone key sets differ")
    return output, gold_by_id, manifests


def _evaluation_paths(repo_root: Path) -> dict[str, tuple[Path, ...]]:
    return {
        "qwen": (
            repo_root / "experiments/locomo-conv50-v1/results/formal-v1-main40-run-02/run/evaluation.json",
            repo_root / "experiments/locomo-conv50-v1/results/formal-v2-qwen-extension20-run-01/run/evaluation.json",
        ),
        "deepseek": (
            repo_root / "experiments/locomo-conv50-v1/results/formal-v2-model2-main60-candidate-02/run/evaluation.json",
        ),
    }


def _judge_paths(repo_root: Path) -> dict[str, tuple[Path, Path]]:
    base = repo_root / "experiments/locomo-conv50-v1/results/llm-judge-x-test1-main120"
    return {
        "qwen": (
            base / "llm-judge-x-test1-model1-main60-run-01/results.json",
            base / "llm-judge-x-test1-model1-main60-run-01/final-audit.json",
        ),
        "deepseek": (
            base / "llm-judge-x-test1-model2-main60-run-01/results.json",
            base / "llm-judge-x-test1-model2-main60-run-01/final-audit.json",
        ),
    }


def _validate_selective_run_gates(
    repo_root: Path,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Validate completion/audit gates that sit outside archived run roots."""

    configurations = (
        {
            "name": "qwen-main40",
            "status": repo_root
            / "experiments/locomo-conv50-v1/results/formal-v1-main40-run-02/run/status.json",
            "final_audit": repo_root
            / "experiments/locomo-conv50-v1/results/formal-v1-main40-run-02/run/final-audit.json",
            "control": repo_root
            / "experiments/locomo-conv50-v1/results/formal-v1-main40-run-02/control",
            "pre_gold_marker": "formal-pre-gold-verify.PASSED",
            "records": 280,
            "batches": 8,
        },
        {
            "name": "qwen-extension20",
            "status": repo_root
            / "experiments/locomo-conv50-v1/results/formal-v2-qwen-extension20-run-01/run/status.json",
            "final_audit": None,
            "control": repo_root
            / "experiments/locomo-conv50-v1/results/formal-v2-qwen-extension20-run-01/control",
            "pre_gold_marker": "formal-pre-gold-verify.PASSED",
            "records": 140,
            "batches": 4,
        },
        {
            "name": "deepseek-main60",
            "status": repo_root
            / "experiments/locomo-conv50-v1/results/formal-v2-model2-main60-candidate-02/run/status.json",
            "final_audit": None,
            "control": repo_root
            / "experiments/locomo-conv50-v1/results/formal-v2-model2-main60-candidate-02/run/control",
            "pre_gold_marker": "../continuation-pre-gold-verify.PASSED",
            "records": 420,
            "batches": 12,
        },
    )
    artifacts: list[dict[str, Any]] = []
    summaries: list[dict[str, Any]] = []
    for configuration in configurations:
        status_path = Path(configuration["status"])
        status = _read_json(status_path)
        expected_records = int(configuration["records"])
        _require(
            status.get("completed_records") == expected_records
            and status.get("pending_records") == 0
            and status.get("active_failed_keys") == 0,
            f"{configuration['name']} completion gate differs",
        )
        if configuration["name"] == "deepseek-main60":
            _require(
                status.get("model_identity_drift_halted") is False,
                "DeepSeek completion gate reports model identity drift",
            )
        artifacts.append(_artifact(repo_root, status_path))
        final_audit_path = configuration["final_audit"]
        if final_audit_path is not None:
            final_audit = _read_json(Path(final_audit_path))
            _require(
                final_audit.get("status") == "passed"
                and final_audit.get("evaluated_records") == expected_records,
                "Qwen main40 final audit differs",
            )
            artifacts.append(_artifact(repo_root, Path(final_audit_path)))
        control = Path(configuration["control"])
        markers = [control / f"batch-{batch:02d}.PASSED" for batch in range(1, int(configuration["batches"]) + 1)]
        pre_gold = (control / str(configuration["pre_gold_marker"])).resolve()
        for marker in (*markers, pre_gold):
            _sha256_file(marker)
            artifacts.append(_artifact(repo_root, marker))
        summaries.append(
            {
                "name": configuration["name"],
                "completed_records": expected_records,
                "pending_records": 0,
                "batch_markers": len(markers),
                "pre_gold_marker": _relative(repo_root, pre_gold),
                "failure_attempts": int(status.get("failure_attempts", 0)),
            }
        )
    return artifacts, summaries


def _load_evaluations(
    repo_root: Path,
    records: Mapping[str, Mapping[tuple[str, str], LoadedRecord]],
    gold: Mapping[str, GoldRecord],
) -> tuple[dict[str, dict[tuple[str, str], dict[str, Any]]], list[dict[str, Any]]]:
    output: dict[str, dict[tuple[str, str], dict[str, Any]]] = {}
    artifacts: list[dict[str, Any]] = []
    for backbone, paths in _evaluation_paths(repo_root).items():
        rows: dict[tuple[str, str], dict[str, Any]] = {}
        for path in paths:
            value = _read_json(path)
            members = value.get("results")
            _require(isinstance(members, list), "Selective evaluation rows are missing")
            for raw in members:
                _require(isinstance(raw, Mapping), "Selective evaluation row is invalid")
                row = dict(raw)
                identity = (str(row.get("condition_id")), str(row.get("question_id")))
                _require(identity not in rows, "Selective evaluation key repeats")
                loaded = records[backbone].get(identity)
                _require(loaded is not None, "Selective evaluation lacks a source record")
                reference = gold[identity[1]]
                recomputed = evaluate_run_record(loaded.record, reference).to_dict()
                _require(row == recomputed, "Archived selective evaluation differs from recomputation")
                rows[identity] = row
            artifacts.append(_artifact(repo_root, path))
        _require(len(rows) == E1_E7_ROW_COUNT // 2, f"{backbone} evaluation count differs")
        output[backbone] = rows
    return output, artifacts


def _judge_usage(row: Mapping[str, Any]) -> dict[str, int]:
    usage = row.get("usage")
    _require(isinstance(usage, list) and usage, "Judge usage is missing")
    totals = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
    for item in usage:
        _require(isinstance(item, Mapping), "Judge usage row is invalid")
        for key in totals:
            value = item.get(key)
            _require(isinstance(value, int) and not isinstance(value, bool) and value >= 0, "Judge token value is invalid")
            totals[key] += value
        _require(item.get("total_tokens") == item.get("prompt_tokens") + item.get("completion_tokens"), "Judge token total differs")
    return totals


def _validate_judge_row(
    *,
    row: Mapping[str, Any],
    loaded: LoadedRecord,
    gold: GoldRecord,
    judge_hash_kind: str,
) -> None:
    mapping = {"correct": (1.0, 1.0), "partial": (0.0, 0.5), "incorrect": (0.0, 0.0)}
    label = row.get("label")
    _require(label in mapping, "Judge label is invalid")
    _require(
        (row.get("strict_score"), row.get("soft_score")) == mapping[str(label)],
        "Judge score mapping differs",
    )
    _require(row.get("status") == "completed", "Judge row is incomplete")
    _require(row.get("source_record_id") == loaded.record.record_id, "Judge source record differs")
    expected_source_hash = {
        "file": loaded.file_sha256,
        "payload": loaded.payload_sha256,
    }.get(judge_hash_kind)
    _require(expected_source_hash is not None, "Unknown Judge source-hash convention")
    _require(row.get("source_record_sha256") == expected_source_hash, "Judge source hash differs")
    _require(row.get("question_sha256") == loaded.record.question.sha256, "Judge question hash differs")
    _require(
        row.get("reference_answer_sha256") == sha256_bytes(gold.answer.encode("utf-8")),
        "Judge reference hash differs",
    )
    _require(
        row.get("candidate_answer_sha256")
        == sha256_bytes(loaded.record.answer_result.answer.encode("utf-8")),
        "Judge candidate hash differs",
    )
    _require(row.get("requested_model") == "x-test-1", "Judge requested alias differs")
    _require(set(row.get("served_models", [])) == {JUDGE_REQUIRED_SERVED_MODEL}, "Judge served model differs")
    _require(row.get("category") == gold.category and row.get("category_name") == gold.category_name, "Judge category differs")
    _judge_usage(row)


def _load_judges(
    repo_root: Path,
    records: Mapping[str, Mapping[tuple[str, str], LoadedRecord]],
    gold: Mapping[str, GoldRecord],
) -> tuple[dict[str, dict[tuple[str, str], dict[str, Any]]], list[dict[str, Any]]]:
    output: dict[str, dict[tuple[str, str], dict[str, Any]]] = {}
    artifacts: list[dict[str, Any]] = []
    for backbone, (results_path, audit_path) in _judge_paths(repo_root).items():
        audit = _read_json(audit_path)
        _require(audit.get("status") == "passed" and audit.get("judged_records") == 420, "Judge final audit differs")
        _require(audit.get("results_sha256") == _sha256_file(results_path), "Judge results hash differs from final audit")
        value = _read_json(results_path)
        members = value.get("results")
        _require(isinstance(members, list) and len(members) == 420, "Judge result count differs")
        rows: dict[tuple[str, str], dict[str, Any]] = {}
        for raw in members:
            _require(isinstance(raw, Mapping), "Judge row is invalid")
            row = dict(raw)
            identity = (str(row.get("condition_id")), str(row.get("question_id")))
            _require(identity not in rows, "Judge key repeats")
            loaded = records[backbone].get(identity)
            _require(loaded is not None, "Judge row lacks a source record")
            _validate_judge_row(
                row=row,
                loaded=loaded,
                gold=gold[identity[1]],
                judge_hash_kind="payload",
            )
            rows[identity] = row
        _require(set(rows) == set(records[backbone]), "Judge/source key sets differ")
        output[backbone] = rows
        artifacts.extend((_artifact(repo_root, results_path), _artifact(repo_root, audit_path)))
    return output, artifacts


def _sum_usage(answer_usage: Sequence[Mapping[str, Any]], key: str) -> int:
    return sum(int(item[key]) for item in answer_usage)


def _selective_row(
    *,
    repo_root: Path,
    backbone: str,
    loaded: LoadedRecord,
    evaluation: Mapping[str, Any],
    judge: Mapping[str, Any],
    reference: GoldRecord,
    global_position: int,
) -> dict[str, Any]:
    record = loaded.record
    condition = record.key.condition_id
    expected_requested = "coding" if backbone == "qwen" else "x-test-2"
    expected_served = "qwen3.8:27b" if backbone == "qwen" else "deepseek-v4.1-flash"
    _require(record.answer_result.requested_model == expected_requested, "Answerer requested model differs")
    _require(set(record.answer_result.served_models) == {expected_served}, "Answerer served model differs")
    precision, recall = _category_precision_recall(
        record.answer_result.answer, reference.answer, reference.category
    )
    f1 = locomo_category_f1(record.answer_result.answer, reference.answer, reference.category)
    _require(abs(float(evaluation["locomo_f1"]) - f1) <= 1e-12, "Selective F1 differs after unified rescoring")
    budget = record.evidence_bundle.to_dict().get("budget")
    _require(isinstance(budget, Mapping), "Selective EvidenceBundle budget is missing")
    if condition == "E7":
        evidence_characters = int(budget["fused_used"])
        evidence_limit = int(budget["total_limit"])
        _require(evidence_limit == 32000 and evidence_characters <= evidence_limit, "E7 evidence budget differs")
        source_bundle_ids = list(record.evidence_bundle.to_dict().get("source_bundle_ids", []))
        _require(len(source_bundle_ids) == 2, "E7 source bundles differ")
    else:
        evidence_characters = int(budget["used"])
        evidence_limit = int(budget["limit"])
        _require(evidence_limit == 16000 and evidence_characters <= evidence_limit, "Selective evidence budget differs")
        source_bundle_ids = []
    retrieval = dict(record.retrieval_metrics)
    answer = dict(record.answer_metrics)
    deployment = dict(record.deployment_metrics)
    judge_tokens = _judge_usage(judge)
    design = CONDITION_DESIGN[condition]
    body = {
        "protocol_version": STAGE_A_PROTOCOL_VERSION,
        "answer_set_id": "model1-qwen-main60" if backbone == "qwen" else "model2-deepseek-main60",
        "backbone_id": backbone,
        "requested_model": expected_requested,
        "served_model": expected_served,
        "condition_id": condition,
        **design,
        "global_position": global_position,
        "question_id": reference.question_id,
        "question_sha256": record.question.sha256,
        "category": reference.category,
        "category_name": reference.category_name,
        "source_partition": loaded.source_partition,
        "source_run_id": record.run_id,
        "source_record_id": record.record_id,
        "source_record_path": _relative(repo_root, loaded.path),
        "source_record_file_sha256": loaded.file_sha256,
        "source_record_payload_sha256": loaded.payload_sha256,
        "evidence_eligible": bool(reference.gold_evidence_dia_ids),
        "gold_dia_ids": list(evaluation["gold_dia_ids"]),
        "retrieved_dia_ids": list(evaluation["retrieved_dia_ids"]),
        "evidence_recall": evaluation["evidence_recall"],
        "evidence_any_hit": evaluation["evidence_any_hit"],
        "evidence_all_hit": evaluation["evidence_all_hit"],
        "source_coverage_by_construction": None,
        "token_precision": precision,
        "token_recall": recall,
        "token_f1": f1,
        "judge_label": judge["label"],
        "strict_score": float(judge["strict_score"]),
        "partial_indicator": int(judge["label"] == "partial"),
        "soft_semantic_score": float(judge["soft_score"]),
        "answer_characters": len(record.answer_result.answer),
        "answer_normalized_tokens": len(normalize_answer(record.answer_result.answer).split()),
        "citation_count": int(evaluation["citation_count"]),
        "citation_validity": float(evaluation["citation_validity"]),
        "evidence_bundle_id": record.evidence_bundle.bundle_id,
        "source_bundle_ids": source_bundle_ids,
        "evidence_item_count": len(record.evidence_bundle.evidence_items),
        "evidence_bundle_characters": evidence_characters,
        "evidence_budget_characters": evidence_limit,
        "search_action_count": len(getattr(record.evidence_bundle, "search_actions", ())),
        "retrieval_provider_rounds": retrieval.get("provider_rounds"),
        "retrieval_filesystem_tool_calls": retrieval.get("filesystem_tool_calls"),
        "retrieval_orchestration_calls": retrieval.get("orchestration_calls"),
        "retrieval_provider_request_attempts": retrieval.get("provider_request_attempts"),
        "retrieval_model_calls": int(deployment["retrieval_model_calls"]),
        "retrieval_prompt_tokens": retrieval.get("prompt_tokens"),
        "retrieval_completion_tokens": retrieval.get("completion_tokens"),
        "retrieval_total_tokens": int(deployment["retrieval_tokens"]),
        "answer_provider_request_attempts": answer.get("provider_request_attempts"),
        "answer_model_calls": int(deployment["answer_model_calls"]),
        "answer_prompt_tokens": answer.get("prompt_tokens"),
        "answer_completion_tokens": answer.get("completion_tokens"),
        "answer_total_tokens": int(deployment["answer_tokens"]),
        "query_model_calls": int(deployment["total_model_calls"]),
        "query_total_tokens": int(deployment["total_tokens"]),
        "elapsed_ms": None,
        "latency_available": False,
        "failure_attempt_count": loaded.failure_attempts,
        "failure_tokens_in_query_total": False,
        "judge_requested_model": str(judge["requested_model"]),
        "judge_served_model": JUDGE_REQUIRED_SERVED_MODEL,
        "judge_model_calls": int(judge["model_calls"]),
        "judge_prompt_tokens": judge_tokens["prompt_tokens"],
        "judge_completion_tokens": judge_tokens["completion_tokens"],
        "judge_total_tokens": judge_tokens["total_tokens"],
        "is_e1_e7_main": True,
        "is_rq1_analysis_row": condition in RQ1_CONDITIONS,
    }
    return {"analysis_row_id": "stage-a-row-" + sha256_bytes(canonical_json_bytes(body)), **body}


def _full_context_paths(repo_root: Path) -> dict[str, Path]:
    source = repo_root / "local-runs/b3-full-context-v3-model2-1017/b3-full-context-v3-model2-1017-main60-run-01"
    judge = repo_root / "local-runs/b3-full-context-v3-model2-1017-judge-x-test1/llm-judge-x-test1-b3-full-context-main60-run-01"
    return {
        "source": source,
        "evaluation": source / "evaluation.json",
        "status": source / "status.json",
        "pre_gold_audit": source / "pre-gold-audit.json",
        "passed_marker": source / "FULL-CONTEXT-MODEL2-1017-MAIN60-60.PASSED",
        "judge_results": judge / "results.json",
        "judge_final_audit": judge / "final-audit.json",
    }


def _full_context_rows(
    *,
    repo_root: Path,
    composition: Sequence[Mapping[str, Any]],
    gold: Mapping[str, GoldRecord],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    paths = _full_context_paths(repo_root)
    status = _read_json(paths["status"])
    audit = _read_json(paths["pre_gold_audit"])
    marker = _read_json(paths["passed_marker"])
    _require(
        status.get("status") == "completed"
        and status.get("completed_records") == QUESTION_COUNT
        and status.get("pending_records") == 0
        and status.get("identity_drift") is False,
        "Full Context status differs",
    )
    _require(
        audit.get("status") == "passed"
        and audit.get("record_count") == QUESTION_COUNT
        and all(audit.get("checks", {}).values()),
        "Full Context pre-gold audit differs",
    )
    _require(marker.get("status") == "passed" and marker.get("record_count") == QUESTION_COUNT, "Full Context PASSED marker differs")
    evaluation_report = _read_json(paths["evaluation"])
    evaluation_rows = evaluation_report.get("rows")
    _require(isinstance(evaluation_rows, list) and len(evaluation_rows) == QUESTION_COUNT, "Full Context evaluation count differs")
    evaluation_by_id = {str(row["question_id"]): dict(row) for row in evaluation_rows if isinstance(row, Mapping)}
    _require(len(evaluation_by_id) == QUESTION_COUNT, "Full Context evaluation keys repeat")
    judge_audit = _read_json(paths["judge_final_audit"])
    _require(
        judge_audit.get("status") == "passed"
        and judge_audit.get("judged_records") == QUESTION_COUNT
        and all(judge_audit.get("checks", {}).values()),
        "Full Context Judge audit differs",
    )
    _require(
        judge_audit.get("results_sha256") == _sha256_file(paths["judge_results"]),
        "Full Context Judge results hash differs",
    )
    judge_report = _read_json(paths["judge_results"])
    judge_rows = judge_report.get("results")
    _require(isinstance(judge_rows, list) and len(judge_rows) == QUESTION_COUNT, "Full Context Judge count differs")
    judge_by_id = {str(row["question_id"]): dict(row) for row in judge_rows if isinstance(row, Mapping)}
    _require(len(judge_by_id) == QUESTION_COUNT, "Full Context Judge keys repeat")
    output: list[dict[str, Any]] = []
    record_artifacts: list[dict[str, Any]] = []
    for position, composition_row in enumerate(composition, start=1):
        question_id = str(composition_row["question_id"])
        path = paths["source"] / "records" / FULL_CONTEXT_CONDITION_ID / question_id / "record.json"
        record_hash = _sha256_file(path)
        record = full_context_record_from_mapping(_read_json(path))
        reference = gold[question_id]
        observed = evaluation_by_id[question_id]
        judge = judge_by_id[question_id]
        _require(observed.get("record_id") == record.record_id, "Full Context evaluation record differs")
        _require(observed.get("category") == reference.category, "Full Context evaluation category differs")
        f1 = locomo_category_f1(record.answer_result.answer, reference.answer, reference.category)
        precision, recall = _category_precision_recall(record.answer_result.answer, reference.answer, reference.category)
        _require(abs(float(observed["locomo_f1"]) - f1) <= 1e-12, "Full Context F1 differs after unified rescoring")
        payload_hash = sha256_bytes(canonical_json_bytes(record.to_dict()))
        loaded = LoadedRecord(
            record=record,  # type: ignore[arg-type]
            path=path,
            file_sha256=record_hash,
            payload_sha256=payload_hash,
            failure_attempts=0,
            source_partition=str(composition_row["layer"]),
        )
        _validate_judge_row(
            row=judge,
            loaded=loaded,
            gold=reference,
            judge_hash_kind="file",
        )
        deployment = dict(record.deployment_metrics)
        judge_tokens = _judge_usage(judge)
        context_stats = dict(record.evidence_bundle.context_stats)
        _require(
            context_stats.get("retrieval_applicable") is False
            and context_stats.get("session_count") == 30
            and context_stats.get("source_coverage") == "100%-by-construction",
            "Full Context source visibility differs",
        )
        body = {
            "protocol_version": STAGE_A_PROTOCOL_VERSION,
            "answer_set_id": "full-context-deepseek-family-main60",
            "backbone_id": "deepseek_family_full_context",
            "requested_model": "x-test-2",
            "served_model": FULL_CONTEXT_REQUIRED_SERVED_MODEL,
            "condition_id": FULL_CONTEXT_CONDITION_ID,
            **CONDITION_DESIGN[FULL_CONTEXT_CONDITION_ID],
            "global_position": position,
            "question_id": question_id,
            "question_sha256": record.question.sha256,
            "category": reference.category,
            "category_name": reference.category_name,
            "source_partition": str(composition_row["layer"]),
            "source_run_id": record.run_id,
            "source_record_id": record.record_id,
            "source_record_path": _relative(repo_root, path),
            "source_record_file_sha256": record_hash,
            "source_record_payload_sha256": payload_hash,
            "evidence_eligible": bool(reference.gold_evidence_dia_ids),
            "gold_dia_ids": list(reference.gold_evidence_dia_ids),
            "retrieved_dia_ids": [],
            "evidence_recall": None,
            "evidence_any_hit": None,
            "evidence_all_hit": None,
            "source_coverage_by_construction": 1.0,
            "token_precision": precision,
            "token_recall": recall,
            "token_f1": f1,
            "judge_label": judge["label"],
            "strict_score": float(judge["strict_score"]),
            "partial_indicator": int(judge["label"] == "partial"),
            "soft_semantic_score": float(judge["soft_score"]),
            "answer_characters": len(record.answer_result.answer),
            "answer_normalized_tokens": len(normalize_answer(record.answer_result.answer).split()),
            "citation_count": int(observed["citation_count"]),
            "citation_validity": float(observed["citation_validity"]),
            "evidence_bundle_id": record.evidence_bundle.bundle_id,
            "source_bundle_ids": [],
            "evidence_item_count": len(record.evidence_bundle.evidence_items),
            "evidence_bundle_characters": int(context_stats["evidence_characters"]),
            "evidence_budget_characters": None,
            "search_action_count": 0,
            "retrieval_provider_rounds": None,
            "retrieval_filesystem_tool_calls": None,
            "retrieval_orchestration_calls": None,
            "retrieval_provider_request_attempts": 0,
            "retrieval_model_calls": 0,
            "retrieval_prompt_tokens": 0,
            "retrieval_completion_tokens": 0,
            "retrieval_total_tokens": 0,
            "answer_provider_request_attempts": int(deployment["provider_request_attempts"]),
            "answer_model_calls": int(deployment["model_calls"]),
            "answer_prompt_tokens": int(deployment["prompt_tokens"]),
            "answer_completion_tokens": int(deployment["completion_tokens"]),
            "answer_total_tokens": int(deployment["total_tokens"]),
            "query_model_calls": int(deployment["model_calls"]),
            "query_total_tokens": int(deployment["total_tokens"]),
            "elapsed_ms": int(deployment["elapsed_ms"]),
            "latency_available": True,
            "failure_attempt_count": 0,
            "failure_tokens_in_query_total": False,
            "judge_requested_model": str(judge["requested_model"]),
            "judge_served_model": JUDGE_REQUIRED_SERVED_MODEL,
            "judge_model_calls": int(judge["model_calls"]),
            "judge_prompt_tokens": judge_tokens["prompt_tokens"],
            "judge_completion_tokens": judge_tokens["completion_tokens"],
            "judge_total_tokens": judge_tokens["total_tokens"],
            "is_e1_e7_main": False,
            "is_rq1_analysis_row": False,
        }
        output.append({"analysis_row_id": "stage-a-row-" + sha256_bytes(canonical_json_bytes(body)), **body})
        record_artifacts.append(
            {
                "path": _relative(repo_root, path),
                "file_sha256": record_hash,
                "payload_sha256": payload_hash,
                "record_id": record.record_id,
            }
        )
    artifacts = [
        _artifact(repo_root, paths[name])
        for name in ("evaluation", "status", "pre_gold_audit", "passed_marker", "judge_results", "judge_final_audit")
    ]
    return output, artifacts, {
        "record_count": len(output),
        "failure_attempt_count": int(status.get("failure_attempts", 0)),
        "records_manifest_sha256": sha256_bytes(canonical_json_bytes(record_artifacts)),
    }


def _build_rows(repo_root: Path) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    composition = _load_composition(repo_root)
    position_by_id = {str(row["question_id"]): int(row["global_position"]) for row in composition}
    records, gold, partition_manifests = _load_selective_sources(repo_root)
    evaluations, evaluation_artifacts = _load_evaluations(repo_root, records, gold)
    judges, judge_artifacts = _load_judges(repo_root, records, gold)
    rows: list[dict[str, Any]] = []
    for backbone in ("qwen", "deepseek"):
        for condition in CONDITIONS:
            for composition_row in composition:
                question_id = str(composition_row["question_id"])
                identity = (condition, question_id)
                rows.append(
                    _selective_row(
                        repo_root=repo_root,
                        backbone=backbone,
                        loaded=records[backbone][identity],
                        evaluation=evaluations[backbone][identity],
                        judge=judges[backbone][identity],
                        reference=gold[question_id],
                        global_position=position_by_id[question_id],
                    )
                )
    full_context, full_context_artifacts, full_context_manifest = _full_context_rows(
        repo_root=repo_root, composition=composition, gold=gold
    )
    rows.extend(full_context)
    gate_artifacts, gate_summaries = _validate_selective_run_gates(repo_root)
    source_artifacts = [
        _artifact(repo_root, repo_root / "experiments/locomo-conv50-v1/question-sets/main-40-gold.jsonl"),
        _artifact(repo_root, repo_root / "experiments/locomo-conv50-v1/question-sets-main60-v2/extension-20-gold.jsonl"),
        _artifact(repo_root, repo_root / "experiments/locomo-conv50-v1/question-sets-main60-v2/main-60-composition.json"),
        _artifact(repo_root, repo_root / "experiments/locomo-conv50-v1/question-sets-main60-v2/verification.json"),
        *evaluation_artifacts,
        *judge_artifacts,
        *full_context_artifacts,
        *gate_artifacts,
    ]
    source_manifest = {
        "schema_version": 1,
        "protocol_version": STAGE_A_PROTOCOL_VERSION,
        "source_policy": "read-only validated sources; physical partitions retained as provenance only",
        "analytical_question_set": "unified Main-60",
        "partition_manifests": partition_manifests,
        "completion_gates": gate_summaries,
        "full_context_manifest": full_context_manifest,
        "artifacts": source_artifacts,
    }
    source_manifest["source_manifest_id"] = "stage-a-sources-" + sha256_bytes(canonical_json_bytes(source_manifest))
    return rows, source_manifest


def _field_schema() -> dict[str, Any]:
    nullable = {
        "evidence_recall", "evidence_any_hit", "evidence_all_hit",
        "source_coverage_by_construction", "evidence_budget_characters",
        "retrieval_provider_rounds", "retrieval_filesystem_tool_calls",
        "retrieval_orchestration_calls", "retrieval_provider_request_attempts",
        "retrieval_prompt_tokens", "retrieval_completion_tokens", "elapsed_ms",
    }
    arrays = {"gold_dia_ids", "retrieved_dia_ids", "source_bundle_ids"}
    descriptions = {
        "token_precision": "Unified category-aware token Precision, recomputed offline for all 900 answers.",
        "token_recall": "Unified category-aware token Recall, recomputed offline for all 900 answers.",
        "token_f1": "Pinned LoCoMo category-aware per-question F1.",
        "evidence_recall": "Annotated-source recall; null for ineligible questions and Full Context.",
        "source_coverage_by_construction": "Full Context source visibility only; never interpreted as Evidence Recall.",
        "elapsed_ms": "Native per-answer elapsed time; unavailable for E1--E7 and therefore null.",
        "failure_tokens_in_query_total": "False: successful-record query totals exclude separately recorded failed attempts.",
        "is_rq1_analysis_row": "True only for symmetric E1--E6 rows used by RQ1 (720 rows).",
        "source_partition": "Physical provenance only; never an analytical old/new subgroup.",
    }
    return {
        "schema_version": 1,
        "protocol_version": STAGE_A_PROTOCOL_VERSION,
        "row_key": ["answer_set_id", "condition_id", "question_id"],
        "array_serialization_in_csv": "compact JSON",
        "fields": {
            name: {
                "nullable": name in nullable,
                "kind": "array" if name in arrays else "scalar",
                "description": descriptions.get(name, "Stage A analysis or provenance field."),
            }
            for name in _ordered_fields()
        },
    }


def _ordered_fields() -> tuple[str, ...]:
    return (
        "analysis_row_id", "protocol_version", "answer_set_id", "backbone_id",
        "requested_model", "served_model", "condition_id", "storage_representation",
        "retrieval_system", "access_regime", "global_position", "question_id",
        "question_sha256", "category", "category_name", "source_partition",
        "source_run_id", "source_record_id", "source_record_path",
        "source_record_file_sha256", "source_record_payload_sha256",
        "evidence_eligible", "gold_dia_ids", "retrieved_dia_ids", "evidence_recall",
        "evidence_any_hit", "evidence_all_hit", "source_coverage_by_construction",
        "token_precision", "token_recall", "token_f1", "judge_label", "strict_score",
        "partial_indicator", "soft_semantic_score", "answer_characters",
        "answer_normalized_tokens", "citation_count", "citation_validity",
        "evidence_bundle_id", "source_bundle_ids", "evidence_item_count",
        "evidence_bundle_characters", "evidence_budget_characters", "search_action_count",
        "retrieval_provider_rounds", "retrieval_filesystem_tool_calls",
        "retrieval_orchestration_calls", "retrieval_provider_request_attempts",
        "retrieval_model_calls", "retrieval_prompt_tokens", "retrieval_completion_tokens",
        "retrieval_total_tokens", "answer_provider_request_attempts", "answer_model_calls",
        "answer_prompt_tokens", "answer_completion_tokens", "answer_total_tokens",
        "query_model_calls", "query_total_tokens", "elapsed_ms", "latency_available",
        "failure_attempt_count", "failure_tokens_in_query_total", "judge_requested_model",
        "judge_served_model", "judge_model_calls", "judge_prompt_tokens",
        "judge_completion_tokens", "judge_total_tokens", "is_e1_e7_main",
        "is_rq1_analysis_row",
    )


def _audit_rows(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    identities = [(row["answer_set_id"], row["condition_id"], row["question_id"]) for row in rows]
    e1_e7 = [row for row in rows if row["is_e1_e7_main"]]
    rq1 = [row for row in rows if row["is_rq1_analysis_row"]]
    answer_sets = Counter(str(row["answer_set_id"]) for row in rows)
    conditions_by_set = {
        answer_set: Counter(str(row["condition_id"]) for row in rows if row["answer_set_id"] == answer_set)
        for answer_set in sorted(answer_sets)
    }
    category_per_path = {
        f"{answer_set}/{condition}": Counter(
            int(row["category"])
            for row in rows
            if row["answer_set_id"] == answer_set and row["condition_id"] == condition
        )
        for answer_set, condition in sorted({(str(row["answer_set_id"]), str(row["condition_id"])) for row in rows})
    }
    evidence_paths = [
        (answer_set, condition)
        for answer_set, condition in sorted({(str(row["answer_set_id"]), str(row["condition_id"])) for row in e1_e7})
    ]
    answer_paths = sorted(
        {
            (str(row["answer_set_id"]), str(row["condition_id"]))
            for row in rows
        }
    )
    question_sets = {
        (answer_set, condition): {
            str(row["question_id"])
            for row in rows
            if row["answer_set_id"] == answer_set and row["condition_id"] == condition
        }
        for answer_set, condition in answer_paths
    }
    common_questions = next(iter(question_sets.values()))
    eligibility_masks = {
        (answer_set, condition): {
            str(row["question_id"])
            for row in rows
            if row["answer_set_id"] == answer_set
            and row["condition_id"] == condition
            and row["evidence_eligible"]
        }
        for answer_set, condition in evidence_paths
    }
    failure_attempts_by_answer_set = Counter()
    for row in rows:
        failure_attempts_by_answer_set[str(row["answer_set_id"])] += int(
            row["failure_attempt_count"]
        )
    checks = {
        "master_rows_900": len(rows) == MASTER_ROW_COUNT,
        "unique_master_keys": len(identities) == len(set(identities)),
        "unique_analysis_row_ids": len({row["analysis_row_id"] for row in rows}) == len(rows),
        "analysis_row_ids_recompute": all(
            str(row["analysis_row_id"])
            == "stage-a-row-"
            + sha256_bytes(
                canonical_json_bytes(
                    {key: value for key, value in row.items() if key != "analysis_row_id"}
                )
            )
            for row in rows
        ),
        "e1_e7_rows_840": len(e1_e7) == E1_E7_ROW_COUNT,
        "rq1_rows_720": len(rq1) == RQ1_ROW_COUNT,
        "answer_sets_420_420_60": answer_sets
        == Counter({"model1-qwen-main60": 420, "model2-deepseek-main60": 420, "full-context-deepseek-family-main60": 60}),
        "conditions_60_each": all(all(value == 60 for value in counts.values()) for counts in conditions_by_set.values()),
        "same_60_questions_each_answer_path": len(common_questions) == QUESTION_COUNT
        and all(value == common_questions for value in question_sets.values()),
        "global_positions_1_to_60_each_path": all(
            {
                int(row["global_position"])
                for row in rows
                if row["answer_set_id"] == answer_set and row["condition_id"] == condition
            }
            == set(range(1, QUESTION_COUNT + 1))
            for answer_set, condition in answer_paths
        ),
        "categories_13_13_7_27_each_path": all(counts == Counter(EXPECTED_CATEGORIES) for counts in category_per_path.values()),
        "evidence_eligible_58_each_e_path": all(
            sum(bool(row["evidence_eligible"]) for row in rows if row["answer_set_id"] == answer_set and row["condition_id"] == condition)
            == EVIDENCE_ELIGIBLE_COUNT
            for answer_set, condition in evidence_paths
        ),
        "evidence_eligibility_mask_identical": all(
            value == next(iter(eligibility_masks.values()))
            for value in eligibility_masks.values()
        ),
        "full_context_evidence_metrics_na": all(
            row["evidence_recall"] is None
            and row["evidence_any_hit"] is None
            and row["evidence_all_hit"] is None
            and row["source_coverage_by_construction"] == 1.0
            for row in rows
            if row["condition_id"] == FULL_CONTEXT_CONDITION_ID
        ),
        "scores_in_unit_interval": all(
            0.0 <= float(row[key]) <= 1.0
            for row in rows
            for key in ("token_precision", "token_recall", "token_f1", "strict_score", "soft_semantic_score")
        ),
        "semantic_mapping_exact": all(
            (row["strict_score"], row["partial_indicator"], row["soft_semantic_score"])
            == {"correct": (1.0, 0, 1.0), "partial": (0.0, 1, 0.5), "incorrect": (0.0, 0, 0.0)}[str(row["judge_label"])]
            for row in rows
        ),
        "model_identities_exact": all(
            (
                row["answer_set_id"] == "model1-qwen-main60"
                and row["requested_model"] == "coding"
                and row["served_model"] == "qwen3.8:27b"
            )
            or (
                row["answer_set_id"] == "model2-deepseek-main60"
                and row["requested_model"] == "x-test-2"
                and row["served_model"] == "deepseek-v4.1-flash"
            )
            or (
                row["answer_set_id"] == "full-context-deepseek-family-main60"
                and row["requested_model"] == "x-test-2"
                and row["served_model"] == FULL_CONTEXT_REQUIRED_SERVED_MODEL
            )
            for row in rows
        ),
        "judge_identity_exact": all(
            row["judge_requested_model"] == "x-test-1"
            and row["judge_served_model"] == JUDGE_REQUIRED_SERVED_MODEL
            for row in rows
        ),
        "query_cost_addition_exact": all(
            int(row["query_model_calls"])
            == int(row["retrieval_model_calls"]) + int(row["answer_model_calls"])
            and int(row["query_total_tokens"])
            == int(row["retrieval_total_tokens"]) + int(row["answer_total_tokens"])
            and int(row["judge_total_tokens"])
            == int(row["judge_prompt_tokens"]) + int(row["judge_completion_tokens"])
            for row in rows
        ),
        "observed_failure_attempts_18_23_0": failure_attempts_by_answer_set
        == Counter(
            {
                "model1-qwen-main60": 18,
                "model2-deepseek-main60": 23,
                "full-context-deepseek-family-main60": 0,
            }
        ),
        "selective_latency_unavailable": all(row["elapsed_ms"] is None and row["latency_available"] is False for row in e1_e7),
        "full_context_latency_available": all(row["elapsed_ms"] is not None and row["latency_available"] is True for row in rows if row["condition_id"] == FULL_CONTEXT_CONDITION_ID),
        "selective_budgets_valid": all(
            int(row["evidence_bundle_characters"]) <= int(row["evidence_budget_characters"])
            and int(row["evidence_budget_characters"]) == (32000 if row["condition_id"] == "E7" else 16000)
            for row in e1_e7
        ),
        "e7_reuses_two_bundles_without_new_actions": all(
            len(row["source_bundle_ids"]) == 2 and row["search_action_count"] == 0
            for row in e1_e7
            if row["condition_id"] == "E7"
        ),
        "full_context_has_30_sessions_without_retrieval_cost": all(
            row["evidence_item_count"] == 30
            and row["retrieval_model_calls"] == 0
            and row["retrieval_total_tokens"] == 0
            and row["evidence_budget_characters"] is None
            for row in rows
            if row["condition_id"] == FULL_CONTEXT_CONDITION_ID
        ),
        "row_field_contract_exact": all(set(row) == set(_ordered_fields()) for row in rows),
        "no_question_answer_or_evidence_text_fields": all(
            not any(name in row for name in ("question", "answer", "reference_answer", "candidate_answer", "evidence_text", "short_reason"))
            for row in rows
        ),
        "rq1_excludes_e7_and_full_context": {str(row["condition_id"]) for row in rq1} == set(RQ1_CONDITIONS),
        "physical_partition_not_analysis_factor": all(row["source_partition"] for row in rows),
    }
    _require(all(checks.values()), "Stage A row audit failed")
    return {
        "checks": checks,
        "row_counts": {"master": len(rows), "e1_e7": len(e1_e7), "rq1": len(rq1)},
        "answer_set_counts": dict(answer_sets),
        "condition_counts_by_answer_set": {key: dict(value) for key, value in conditions_by_set.items()},
        "category_counts_per_answer_path": {
            key: {str(category): count for category, count in value.items()}
            for key, value in category_per_path.items()
        },
        "evidence_denominator": EVIDENCE_ELIGIBLE_COUNT,
        "answer_denominator": QUESTION_COUNT,
        "failure_attempt_counts_by_answer_set": dict(failure_attempts_by_answer_set),
    }


def _jsonl_payload(rows: Iterable[Mapping[str, Any]]) -> bytes:
    return b"".join(canonical_json_bytes(dict(row)) + b"\n" for row in rows)


def _csv_payload(rows: Sequence[Mapping[str, Any]]) -> bytes:
    import io

    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=list(_ordered_fields()), lineterminator="\n")
    writer.writeheader()
    for row in rows:
        serialized = {
            key: json.dumps(value, ensure_ascii=False, separators=(",", ":"))
            if isinstance(value, (list, dict))
            else value
            for key, value in row.items()
        }
        writer.writerow(serialized)
    return buffer.getvalue().encode("utf-8")


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
                raise OSError("short Stage A artifact write")
            offset += count
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _readme() -> str:
    return """# Chapter 5 Stage A: frozen Main-60 analysis table

This directory is the audited, question-level input for later Chapter 5
analysis. It contains 900 answer paths: 420 Qwen E1--E7 rows, 420 DeepSeek
E1--E7 rows, and 60 DeepSeek-family Full Context rows.

`e1-e7-main.*` is the symmetric 840-row E1--E7 view. `rq1-analysis-view.*`
is the 720-row E1--E6 input for RQ1. E7 belongs to the later fusion analysis;
Full Context belongs to the later diagnostic comparison. No paired effect,
bootstrap interval, rank, or report conclusion is computed in Stage A.

Token Precision and Recall are recomputed for all 900 answers with the same
category-aware alignment described in Chapter 4. The pinned LoCoMo F1 is also
recomputed and checked against every source evaluation row. The computation
reads answer and reference text only in memory. No question, reference answer,
candidate answer, evidence text, or Judge rationale is persisted here.

Answer metrics use 60 questions per answer path. Evidence Recall, Any-hit, and
All-hit use the fixed 58-question eligibility mask. Full Context has complete
source visibility by construction but has no retrieval metrics; its evidence
metrics remain null. Native per-answer latency is unavailable for E1--E7 and
is therefore null rather than inferred from event timestamps.

Physical main40/extension20 labels are retained only as provenance. All report
analysis treats the questions as one unified Main-60 test set.
"""


def build_stage_a(*, repo_root: Path, output_dir: Path) -> dict[str, Any]:
    root = repo_root.resolve()
    destination = output_dir.resolve()
    _require(root.is_dir() and not root.is_symlink(), "Repository root is unsafe")
    _require(not destination.exists() and not destination.is_symlink(), "Stage A output already exists")
    rows, source_manifest = _build_rows(root)
    row_audit = _audit_rows(rows)
    e1_e7 = [row for row in rows if row["is_e1_e7_main"]]
    rq1 = [row for row in rows if row["is_rq1_analysis_row"]]
    parent = destination.parent
    parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=f".{destination.name}.in-progress-", dir=parent))
    try:
        payloads = {
            "master-table.jsonl": _jsonl_payload(rows),
            "master-table.csv": _csv_payload(rows),
            "e1-e7-main.jsonl": _jsonl_payload(e1_e7),
            "e1-e7-main.csv": _csv_payload(e1_e7),
            "rq1-analysis-view.jsonl": _jsonl_payload(rq1),
            "rq1-analysis-view.csv": _csv_payload(rq1),
            "schema.json": canonical_json_bytes(_field_schema()) + b"\n",
            "source-manifest.json": canonical_json_bytes(source_manifest) + b"\n",
            "README.md": _readme().encode("utf-8"),
        }
        for name, payload in payloads.items():
            _write(temporary / name, payload)
        output_hashes = {name: _sha256_file(temporary / name) for name in sorted(payloads)}
        body = {
            "schema_version": 1,
            "protocol_version": STAGE_A_PROTOCOL_VERSION,
            "status": "passed",
            "scope": "unified Main-60",
            "no_api_calls": True,
            "formal_source_mutation": False,
            "effect_estimates_computed": False,
            "token_metric_policy": "uniform category-aware offline rescore of all 900 answers",
            "row_audit": row_audit,
            "source_manifest_id": source_manifest["source_manifest_id"],
            "output_sha256": output_hashes,
        }
        audit = {"audit_id": "stage-a-audit-" + sha256_bytes(canonical_json_bytes(body)), **body}
        _write(temporary / "audit.json", canonical_json_bytes(audit) + b"\n")
        marker = {
            "status": "passed",
            "protocol_version": STAGE_A_PROTOCOL_VERSION,
            "audit_id": audit["audit_id"],
            "audit_sha256": _sha256_file(temporary / "audit.json"),
            "master_rows": MASTER_ROW_COUNT,
            "e1_e7_rows": E1_E7_ROW_COUNT,
            "rq1_rows": RQ1_ROW_COUNT,
        }
        _write(temporary / "STAGE-A.PASSED", canonical_json_bytes(marker) + b"\n")
        os.rename(temporary, destination)
        directory = os.open(parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    except Exception:
        shutil.rmtree(temporary, ignore_errors=True)
        raise
    return audit_stage_a_output(destination)


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    lexical = Path(path)
    if lexical.is_symlink() or not lexical.is_file():
        raise EvidenceValidationError(f"Unsafe or missing Stage A JSONL: {lexical}")
    rows = []
    for line in lexical.read_text(encoding="utf-8").splitlines():
        value = json.loads(line)
        _require(isinstance(value, dict), "Stage A JSONL row is invalid")
        rows.append(value)
    return rows


def audit_stage_a_output(output_dir: Path) -> dict[str, Any]:
    root = output_dir.resolve()
    _require(root.is_dir() and not root.is_symlink(), "Stage A output directory is unsafe")
    audit = _read_json(root / "audit.json")
    marker = _read_json(root / "STAGE-A.PASSED")
    rows = _read_jsonl(root / "master-table.jsonl")
    e1_e7 = _read_jsonl(root / "e1-e7-main.jsonl")
    rq1 = _read_jsonl(root / "rq1-analysis-view.jsonl")
    _require(audit.get("status") == "passed", "Stage A audit is not passed")
    _require(marker.get("status") == "passed" and marker.get("audit_id") == audit.get("audit_id"), "Stage A marker differs")
    _require(marker.get("audit_sha256") == _sha256_file(root / "audit.json"), "Stage A audit hash differs")
    for name, digest in audit.get("output_sha256", {}).items():
        _require(_sha256_file(root / name) == digest, f"Stage A output hash differs: {name}")
    independent = _audit_rows(rows)
    _require(
        len(e1_e7) == E1_E7_ROW_COUNT
        and len(rq1) == RQ1_ROW_COUNT
        and [row for row in rows if row["is_e1_e7_main"]] == e1_e7
        and [row for row in rows if row["is_rq1_analysis_row"]] == rq1,
        "Stage A materialized views differ from the master table",
    )
    _require(independent == audit.get("row_audit"), "Stage A independent row audit differs")
    return {
        "status": "passed",
        "protocol_version": STAGE_A_PROTOCOL_VERSION,
        "audit_id": audit["audit_id"],
        "master_rows": len(rows),
        "e1_e7_rows": len(e1_e7),
        "rq1_rows": len(rq1),
        "output_dir": str(root),
        "no_api_calls": True,
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build or audit Chapter 5 Stage A artifacts")
    parser.add_argument("--repo-root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("command", choices=("build", "audit"))
    return parser


def main(argv: list[str] | None = None) -> None:
    args = _parser().parse_args(argv)
    if args.command == "build":
        result = build_stage_a(repo_root=args.repo_root, output_dir=args.output_dir)
    else:
        result = audit_stage_a_output(args.output_dir)
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
