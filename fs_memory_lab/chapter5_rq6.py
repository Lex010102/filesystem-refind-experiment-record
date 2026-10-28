"""Build and audit the Chapter 5 RQ6 quality--cost decision artifact.

RQ6 is an offline synthesis stage.  It joins the frozen Main-60 quality and
process records with the already-audited RQ2--RQ5 findings and the frozen
S1--S3 construction manifests.  It does not call a model, access the network,
or modify any formal result.

The analysis deliberately keeps unlike cost dimensions separate.  Query-time
model calls and tokens are observed.  Construction calls and tokens are
reported as one-time costs.  Failed-attempt counts and LLM-judge tokens are
reported separately.  Comparable E1--E7 latency, monetary price, and
long-term maintenance measurements are unavailable and are never inferred.
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
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

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


PROTOCOL_VERSION = "chapter5-main60-rq6-v1"
DEFAULT_OUTPUT_DIR = "artifacts/chapter5-main60-analysis-v1/rq6-quality-cost"
STAGE_A_DIR = "artifacts/chapter5-main60-analysis-v1/stage-a"
RQ2_DIR = "artifacts/chapter5-main60-analysis-v1/rq2-backbone-robustness"
RQ3_DIR = "artifacts/chapter5-main60-analysis-v1/rq3-dual-source-fusion"
RQ4_DIR = "artifacts/chapter5-main60-analysis-v1/rq4-full-context"
RQ5_DIR = "artifacts/chapter5-main60-analysis-v1/rq5-integrated-bottleneck"

S1_MANIFEST = "experiments/locomo-conv50-v1/manifests/s1-flat.json"
S2_MANIFEST = "experiments/locomo-conv50-v1/manifests/s2-foldered.json"
S3_MANIFEST = "experiments/locomo-conv50-v1/manifests/s3-curated.json"

FORMAL_RUNS = (
    (
        "model1-qwen-main60",
        "experiments/locomo-conv50-v1/results/formal-v1-main40-run-02/run",
    ),
    (
        "model1-qwen-main60",
        "experiments/locomo-conv50-v1/results/formal-v2-qwen-extension20-run-01/run",
    ),
    (
        "model2-deepseek-main60",
        "experiments/locomo-conv50-v1/results/formal-v2-model2-main60-candidate-02/run/children/main40/formal-v2-model2-main60-candidate-02-main40",
    ),
    (
        "model2-deepseek-main60",
        "experiments/locomo-conv50-v1/results/formal-v2-model2-main60-candidate-02/run/children/extension20/formal-v2-model2-main60-candidate-02-extension20",
    ),
)

QUESTION_COUNT = 60
SOURCE_ROW_COUNT = 900
SELECTIVE_CONDITIONS = tuple(f"E{index}" for index in range(1, 8))
FULL_CONTEXT_CONDITION = "B3-FullContext"
QUALITY_METRICS = ("strict_accuracy", "soft_semantic_score", "token_f1")
COST_METRICS = ("mean_query_total_tokens", "mean_query_model_calls")
WORKLOADS = (60, 600, 6000)
FLOAT_TOLERANCE = 1e-9

EXPECTED_AUDIT_IDS = {
    "stage_a": "stage-a-audit-5f55ec411f097df7206fdae5e71742641aa8868b4128ac32262f034877a1d7f3",
    "rq2": "rq2-audit-ef0e571affac75cd8b6ad71d833411e7a41c10664132770f77d86712827ab00b",
    "rq3": "rq3-audit-e0ac8fc4a256b4fa5d016871163fc19243e99a9328985568b48b73ee35586378",
    "rq4": "rq4-audit-2880a371169fcc1c1596fec7baccb795ef1a0bf49b830357dde002b511c2d923",
    "rq5": "rq5-integrated-audit-7c68cdb9c619409de661590729605b9c2d9c650003db223f8651f8de0c48eaf2",
}

ANSWER_SETS = {
    "model1-qwen-main60": ("qwen", "Qwen", "qwen3.8:27b"),
    "model2-deepseek-main60": ("deepseek", "DeepSeek", "deepseek-v4.1-flash"),
    "full-context-deepseek-family-main60": (
        "deepseek_family_full_context",
        "DeepSeek-family Full Context",
        "deepseek-v4.1-flash-1017",
    ),
}

CONDITION_STORES = {
    "E1": ("S1",),
    "E2": ("S1",),
    "E3": ("S2",),
    "E4": ("S2",),
    "E5": ("S3",),
    "E6": ("S3",),
    "E7": ("S1", "S3"),
    FULL_CONTEXT_CONDITION: ("S1",),
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
    "prompt",
    "response",
    "api_key",
    "authorization",
}

TABLES = (
    "condition-quality-cost",
    "store-construction-cost",
    "recovery-cost",
    "e7-cost-views",
    "amortisation-scenarios",
    "build-break-even",
    "pareto-membership",
    "pareto-frontiers",
    "scenario-decision-matrix",
    "table-5-33-inputs",
    "table-5-34-inputs",
    "figure-5-12-inputs",
)


def _artifact_id(prefix: str, body: Mapping[str, Any]) -> str:
    return prefix + sha256_bytes(canonical_json_bytes(dict(body)))


def _close(left: float, right: float, tolerance: float = FLOAT_TOLERANCE) -> bool:
    return math.isclose(float(left), float(right), rel_tol=0.0, abs_tol=tolerance)


def _mean(values: Sequence[float | int]) -> float:
    _require(bool(values), "RQ6 cannot average an empty sequence")
    numeric = [float(value) for value in values]
    _require(all(math.isfinite(value) for value in numeric), "RQ6 contains a non-finite value")
    return math.fsum(numeric) / len(numeric)


def _sum(values: Iterable[float | int]) -> float:
    numeric = [float(value) for value in values]
    _require(all(math.isfinite(value) for value in numeric), "RQ6 contains a non-finite value")
    return math.fsum(numeric)


def _artifact(root: Path, path: Path) -> dict[str, Any]:
    return {
        "path": _relative(root, path),
        "sha256": _sha256_file(path),
        "bytes": path.stat().st_size,
    }


def _validate_audit_bundle(root: Path, directory: str, marker_name: str, expected_id: str) -> dict[str, Any]:
    folder = (root / directory).resolve()
    _require(folder.is_dir() and not folder.is_symlink(), f"Unsafe upstream directory: {directory}")
    audit_path = folder / "audit.json"
    marker_path = folder / marker_name
    audit = _read_json(audit_path)
    marker = _read_json(marker_path)
    _require(audit.get("status") == "passed", f"Upstream audit did not pass: {directory}")
    _require(audit.get("audit_id") == expected_id, f"Upstream audit identity differs: {directory}")
    _require(marker.get("status") == "passed", f"Upstream marker did not pass: {directory}")
    _require(marker.get("audit_id") == expected_id, f"Upstream marker identity differs: {directory}")
    _require(
        marker.get("audit_sha256") == _sha256_file(audit_path),
        f"Upstream audit hash differs: {directory}",
    )
    for filename, digest in audit.get("output_sha256", {}).items():
        path = folder / filename
        _require(_sha256_file(path) == digest, f"Upstream output hash differs: {directory}/{filename}")
    return {
        "audit_id": expected_id,
        "audit": _artifact(root, audit_path),
        "marker": _artifact(root, marker_path),
    }


def _validate_upstream(root: Path) -> dict[str, Any]:
    stage_a = (root / STAGE_A_DIR).resolve()
    stage_a_audit = audit_stage_a_output(stage_a)
    _require(stage_a_audit.get("status") == "passed", "Stage A audit failed")
    _require(stage_a_audit.get("audit_id") == EXPECTED_AUDIT_IDS["stage_a"], "Stage A identity differs")

    bundles = {
        "rq2": _validate_audit_bundle(root, RQ2_DIR, "RQ2.PASSED", EXPECTED_AUDIT_IDS["rq2"]),
        "rq3": _validate_audit_bundle(root, RQ3_DIR, "RQ3.PASSED", EXPECTED_AUDIT_IDS["rq3"]),
        "rq4": _validate_audit_bundle(root, RQ4_DIR, "RQ4.PASSED", EXPECTED_AUDIT_IDS["rq4"]),
        "rq5": _validate_audit_bundle(root, RQ5_DIR, "RQ5-INTEGRATED.PASSED", EXPECTED_AUDIT_IDS["rq5"]),
    }
    bundles["stage_a"] = {
        "audit_id": stage_a_audit["audit_id"],
        "audit": _artifact(root, stage_a / "audit.json"),
        "marker": _artifact(root, stage_a / "STAGE-A.PASSED"),
        "master_table": _artifact(root, stage_a / "master-table.jsonl"),
    }
    return bundles


def _load_store_costs(root: Path) -> tuple[list[dict[str, Any]], dict[str, dict[str, float]]]:
    manifest_paths = {
        "S1": root / S1_MANIFEST,
        "S2": root / S2_MANIFEST,
        "S3": root / S3_MANIFEST,
    }
    manifests = {store: _read_json(path) for store, path in manifest_paths.items()}

    s1 = manifests["S1"]["build_cost"]
    s2 = manifests["S2"]["build_cost"]
    s3 = manifests["S3"]["build_cost"]
    _require((s1["llm_calls"], s1["model_tokens"], s1["tool_calls"]) == (0, 0, 0), "S1 build cost differs")
    _require(s2["llm_calls"] == 12 and s2["tool_calls"] == 62, "S2 build calls differ")
    _require(s2["usage_totals"]["total_tokens"] == 395749, "S2 build tokens differ")
    _require(s3["llm_calls"] == 842 and s3["tool_calls"] == 1350, "S3 build calls differ")
    _require(s3["usage_totals"]["total_tokens"] == 30864958, "S3 build tokens differ")
    _require(manifests["S2"]["verification"]["bytes_identical_to_s1"] is True, "S2 byte identity differs")
    _require(manifests["S3"]["verification"]["all_85_chunks_completed_in_order"] is True, "S3 build incomplete")

    numeric = {
        "S1": {"model_calls": 0.0, "tool_calls": 0.0, "prompt_tokens": 0.0, "completion_tokens": 0.0, "total_tokens": 0.0},
        "S2": {
            "model_calls": float(s2["llm_calls"]),
            "tool_calls": float(s2["tool_calls"]),
            "prompt_tokens": float(s2["usage_totals"]["prompt_tokens"]),
            "completion_tokens": float(s2["usage_totals"]["completion_tokens"]),
            "total_tokens": float(s2["usage_totals"]["total_tokens"]),
        },
        "S3": {
            "model_calls": float(s3["llm_calls"]),
            "tool_calls": float(s3["tool_calls"]),
            "prompt_tokens": float(s3["usage_totals"]["prompt_tokens"]),
            "completion_tokens": float(s3["usage_totals"]["completion_tokens"]),
            "total_tokens": float(s3["usage_totals"]["total_tokens"]),
        },
    }
    labels = {
        "S1": ("Flat raw sessions", "No model-based construction; deterministic source normalisation only"),
        "S2": ("Foldered raw sessions", "Small one-time organisation cost; session bytes remain identical to S1"),
        "S3": ("Agent-curated memory", "Large one-time curation cost; long-term update cost was not measured"),
    }
    rows: list[dict[str, Any]] = []
    for order, store in enumerate(("S1", "S2", "S3"), 1):
        label, implication = labels[store]
        values = numeric[store]
        row = {
            "record_id": _artifact_id("rq6-store-", {"store": store, **values}),
            "protocol_version": PROTOCOL_VERSION,
            "store_order": order,
            "storage_representation": store,
            "description": label,
            "construction_model_calls": int(values["model_calls"]),
            "construction_tool_calls": int(values["tool_calls"]),
            "construction_prompt_tokens": int(values["prompt_tokens"]),
            "construction_completion_tokens": int(values["completion_tokens"]),
            "construction_total_tokens": int(values["total_tokens"]),
            "maintenance_cost_measured": False,
            "qualitative_implication": implication,
            "source_manifest_path": _relative(root, manifest_paths[store]),
            "source_manifest_sha256": _sha256_file(manifest_paths[store]),
        }
        rows.append(row)
    return rows, numeric


def _load_recovery_costs(
    root: Path,
) -> tuple[list[dict[str, Any]], dict[str, list[dict[str, Any]]], dict[str, int]]:
    """Load formal failed attempts once and keep recovery cost separate.

    Launcher attempt files define the attempt census.  Archived ``failure.json``
    files define the available usage census.  The two are reconciled as a
    multiset by formal run, condition, and question.  This is necessary because
    nine Qwen-extension launcher messages omit the immutable artifact id even
    though their archived usage artifacts exist.  The two DNS attempts have no
    usage artifact and remain explicitly unknown rather than being treated as
    zero cost.
    """

    grouped_attempts: defaultdict[tuple[str, str], int] = defaultdict(int)
    grouped_usage: defaultdict[tuple[str, str], list[dict[str, int]]] = defaultdict(list)
    attempt_artifacts: list[dict[str, Any]] = []
    failure_artifacts: list[dict[str, Any]] = []
    seen_attempt_ids: set[str] = set()
    seen_failure_ids: set[str] = set()
    unknown_usage_groups: list[tuple[str, str, str, str, int]] = []
    embedded_failure = re.compile(r"(?<!run-)(failure-[0-9a-f]{64})")

    for answer_set, relative_run in FORMAL_RUNS:
        run_root = (root / relative_run).resolve()
        _require(run_root.is_dir() and not run_root.is_symlink(), f"Unsafe formal run: {relative_run}")
        local_attempts: defaultdict[tuple[str, str], int] = defaultdict(int)
        local_usage: defaultdict[tuple[str, str], list[dict[str, int]]] = defaultdict(list)
        token_failure_keys: dict[str, tuple[str, str]] = {}
        for failure_path in sorted(run_root.glob("E*/*.failed-*/failure.json")):
            failure = _read_json(failure_path)
            failure_id = str(failure.get("failure_id", ""))
            _require(re.fullmatch(r"failure-[0-9a-f]{64}", failure_id) is not None, "Invalid failure artifact id")
            _require(failure_id not in seen_failure_ids, "Duplicate token-bearing failure artifact")
            seen_failure_ids.add(failure_id)
            condition = str(failure.get("condition", {}).get("condition_id", ""))
            question_id = str(failure.get("question", {}).get("question_id", ""))
            _require(condition in SELECTIVE_CONDITIONS and bool(question_id), "Invalid token-bearing failure key")
            metrics = failure.get("metrics", {})
            _require(metrics.get("token_usage_available") is True, "Archived failure lacks token usage")
            for component in (
                "provider_request_attempts",
                "prompt_tokens",
                "completion_tokens",
                "total_tokens",
                "model_calls",
            ):
                _require(isinstance(metrics.get(component), int) and int(metrics[component]) >= 0, "Invalid failure usage")
            _require(
                int(metrics["prompt_tokens"]) + int(metrics["completion_tokens"]) == int(metrics["total_tokens"]),
                "Failure token components differ",
            )
            usage = {
                "provider_request_attempts": int(metrics["provider_request_attempts"]),
                "model_calls": int(metrics["model_calls"]),
                "prompt_tokens": int(metrics["prompt_tokens"]),
                "completion_tokens": int(metrics["completion_tokens"]),
                "total_tokens": int(metrics["total_tokens"]),
            }
            local_usage[(condition, question_id)].append(usage)
            token_failure_keys[failure_id] = (condition, question_id)
            failure_artifacts.append(_artifact(root, failure_path))

        for attempt_path in sorted(run_root.glob("failures/E*/*/attempt-*.json")):
            attempt = _read_json(attempt_path)
            attempt_id = str(attempt.get("failure_id", ""))
            _require(re.fullmatch(r"run-failure-[0-9a-f]{64}", attempt_id) is not None, "Invalid run failure id")
            _require(attempt_id not in seen_attempt_ids, "Duplicate formal failed attempt")
            seen_attempt_ids.add(attempt_id)
            key = attempt.get("key", {})
            condition = str(key.get("condition_id", ""))
            question_id = str(key.get("question_id", ""))
            _require(condition in SELECTIVE_CONDITIONS, "Unknown failed-attempt condition")
            _require(bool(question_id), "Missing failed-attempt question id")
            _require(attempt.get("status") == "failed", "Formal attempt is not failed")
            match = embedded_failure.search(str(attempt.get("message", "")))
            if match is not None:
                failure_id = match.group(1)
                _require(token_failure_keys.get(failure_id) == (condition, question_id), "Named failure artifact key differs")
            local_attempts[(condition, question_id)] += 1
            attempt_artifacts.append(_artifact(root, attempt_path))

        for key in set(local_attempts) | set(local_usage):
            _require(len(local_usage[key]) <= local_attempts[key], "More usage artifacts than failed attempts")
            condition, question_id = key
            unknown = local_attempts[key] - len(local_usage[key])
            if unknown:
                unknown_usage_groups.append((answer_set, relative_run, condition, question_id, unknown))
            grouped_attempts[(answer_set, condition)] += local_attempts[key]
            grouped_usage[(answer_set, condition)].extend(local_usage[key])

    _require(
        unknown_usage_groups
        == [
            (
                "model1-qwen-main60",
                "experiments/locomo-conv50-v1/results/formal-v2-qwen-extension20-run-01/run",
                "E5",
                "conv-50-q028",
                2,
            )
        ],
        "Unexpected formal attempt group lacks a token-bearing artifact",
    )

    rows: list[dict[str, Any]] = []
    answer_set_order = {
        "model1-qwen-main60": 1,
        "model2-deepseek-main60": 2,
        "full-context-deepseek-family-main60": 3,
    }
    for answer_set in answer_set_order:
        conditions = (FULL_CONTEXT_CONDITION,) if answer_set.startswith("full-context") else SELECTIVE_CONDITIONS
        for condition in conditions:
            attempt_count = grouped_attempts[(answer_set, condition)]
            known = grouped_usage[(answer_set, condition)]
            unknown = attempt_count - len(known)
            body = {"answer_set": answer_set, "condition": condition}
            rows.append(
                {
                    "record_id": _artifact_id("rq6-recovery-", body),
                    "protocol_version": PROTOCOL_VERSION,
                    "answer_set_order": answer_set_order[answer_set],
                    "answer_set_id": answer_set,
                    "backbone_id": ANSWER_SETS[answer_set][0],
                    "condition_id": condition,
                    "failure_attempt_count": attempt_count,
                    "token_usage_known_attempts": len(known),
                    "token_usage_unknown_attempts": unknown,
                    "known_recovery_provider_request_attempts": int(
                        _sum(item["provider_request_attempts"] for item in known)
                    ),
                    "known_recovery_model_calls": int(_sum(item["model_calls"] for item in known)),
                    "known_recovery_prompt_tokens": int(_sum(item["prompt_tokens"] for item in known)),
                    "known_recovery_completion_tokens": int(_sum(item["completion_tokens"] for item in known)),
                    "known_recovery_total_tokens": int(_sum(item["total_tokens"] for item in known)),
                    "known_recovery_tokens_per_60_successes": _sum(item["total_tokens"] for item in known) / QUESTION_COUNT,
                    "token_usage_coverage_ratio": len(known) / attempt_count if attempt_count else 1.0,
                    "recovery_token_cost_complete": unknown == 0,
                    "included_in_successful_query_cost": False,
                }
            )

    diagnostics = {
        "failure_attempts": sum(grouped_attempts.values()),
        "token_usage_known_attempts": sum(int(row["token_usage_known_attempts"]) for row in rows),
        "token_usage_unknown_attempts": sum(int(row["token_usage_unknown_attempts"]) for row in rows),
        "known_recovery_provider_request_attempts": sum(
            int(row["known_recovery_provider_request_attempts"]) for row in rows
        ),
        "known_recovery_model_calls": sum(int(row["known_recovery_model_calls"]) for row in rows),
        "known_recovery_prompt_tokens": sum(int(row["known_recovery_prompt_tokens"]) for row in rows),
        "known_recovery_completion_tokens": sum(int(row["known_recovery_completion_tokens"]) for row in rows),
        "known_recovery_total_tokens": sum(int(row["known_recovery_total_tokens"]) for row in rows),
    }
    _require(
        diagnostics
        == {
            "failure_attempts": 41,
            "token_usage_known_attempts": 39,
            "token_usage_unknown_attempts": 2,
            "known_recovery_provider_request_attempts": 390,
            "known_recovery_model_calls": 368,
            "known_recovery_prompt_tokens": 9669598,
            "known_recovery_completion_tokens": 456760,
            "known_recovery_total_tokens": 10126358,
        },
        "Formal recovery census differs",
    )
    _require(len(rows) == 15, "Recovery-cost condition count differs")
    _require(len(attempt_artifacts) == 41 and len(failure_artifacts) == 39, "Recovery provenance count differs")
    return rows, {
        "attempt_metadata": sorted(attempt_artifacts, key=lambda item: item["path"]),
        "token_bearing_failures": sorted(failure_artifacts, key=lambda item: item["path"]),
    }, diagnostics


def _attach_recovery_costs(
    condition_rows: list[dict[str, Any]], recovery_rows: Sequence[Mapping[str, Any]],
) -> None:
    recovery_index = {
        (str(row["answer_set_id"]), str(row["condition_id"])): row for row in recovery_rows
    }
    for row in condition_rows:
        recovery = recovery_index[(str(row["answer_set_id"]), str(row["condition_id"]))]
        _require(
            int(row["total_failure_attempts"]) == int(recovery["failure_attempt_count"]),
            "Stage A and formal recovery attempt counts differ",
        )
        row.update(
            {
                "failure_tokens_separately_available": int(recovery["token_usage_known_attempts"]) > 0,
                "recovery_token_cost_complete": bool(recovery["recovery_token_cost_complete"]),
                "known_recovery_provider_request_attempts": int(
                    recovery["known_recovery_provider_request_attempts"]
                ),
                "known_recovery_model_calls": int(recovery["known_recovery_model_calls"]),
                "known_recovery_total_tokens": int(recovery["known_recovery_total_tokens"]),
                "token_usage_unknown_failure_attempts": int(recovery["token_usage_unknown_attempts"]),
            }
        )


def _validate_stage_a_rows(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    _require(len(rows) == SOURCE_ROW_COUNT, "RQ6 Stage A population differs")
    _require(all(FORBIDDEN_FIELDS.isdisjoint(row) for row in rows), "RQ6 source contains forbidden text")
    counts: defaultdict[tuple[str, str], int] = defaultdict(int)
    question_sets: defaultdict[tuple[str, str], set[str]] = defaultdict(set)
    clean: list[dict[str, Any]] = []
    for source in rows:
        row = dict(source)
        answer_set = str(row["answer_set_id"])
        _require(answer_set in ANSWER_SETS, "RQ6 unknown answer set")
        expected_backbone, _, expected_model = ANSWER_SETS[answer_set]
        _require(row["backbone_id"] == expected_backbone, "RQ6 backbone identity differs")
        _require(row["served_model"] == expected_model, "RQ6 served model identity differs")
        condition = str(row["condition_id"])
        if answer_set == "full-context-deepseek-family-main60":
            _require(condition == FULL_CONTEXT_CONDITION, "RQ6 Full Context condition differs")
            _require(row["latency_available"] is True, "RQ6 Full Context latency availability differs")
        else:
            _require(condition in SELECTIVE_CONDITIONS, "RQ6 selective condition differs")
            _require(row["latency_available"] is False, "RQ6 E1--E7 latency must remain unavailable")
        for field in ("token_f1", "strict_score", "soft_semantic_score"):
            value = float(row[field])
            _require(math.isfinite(value) and 0.0 <= value <= 1.0, f"RQ6 invalid quality value: {field}")
        _require(int(row["query_model_calls"]) >= 1, "RQ6 query call count differs")
        _require(int(row["query_total_tokens"]) > 0, "RQ6 query token count differs")
        for prefix in ("retrieval", "answer", "judge"):
            _require(
                int(row[f"{prefix}_prompt_tokens"]) + int(row[f"{prefix}_completion_tokens"])
                == int(row[f"{prefix}_total_tokens"]),
                f"RQ6 {prefix} token components differ",
            )
        _require(
            int(row["retrieval_model_calls"]) + int(row["answer_model_calls"])
            == int(row["query_model_calls"]),
            "RQ6 query model-call components differ",
        )
        _require(
            int(row["retrieval_total_tokens"]) + int(row["answer_total_tokens"])
            == int(row["query_total_tokens"]),
            "RQ6 query token components differ",
        )
        _require(row["failure_tokens_in_query_total"] is False, "RQ6 failure token boundary differs")
        key = (answer_set, condition)
        counts[key] += 1
        question_sets[key].add(str(row["question_id"]))
        clean.append(row)
    _require(sum(counts.values()) == SOURCE_ROW_COUNT, "RQ6 condition census differs")
    _require(all(count == QUESTION_COUNT for count in counts.values()), "RQ6 condition denominator differs")
    _require(all(len(items) == QUESTION_COUNT for items in question_sets.values()), "RQ6 question pairing differs")
    _require(len(counts) == 15, "RQ6 condition count differs")
    return clean


def _condition_build_cost(condition: str, store_costs: Mapping[str, Mapping[str, float]]) -> dict[str, float]:
    stores = CONDITION_STORES[condition]
    # Shared S1 is cost-free in the recorded model-cost dimensions.  E7 needs
    # both S1 and S3, so only S3 contributes a non-zero construction cost.
    return {
        key: _sum(store_costs[store][key] for store in stores)
        for key in ("model_calls", "tool_calls", "prompt_tokens", "completion_tokens", "total_tokens")
    }


def _quality_cost_rows(
    rows: Sequence[Mapping[str, Any]], store_costs: Mapping[str, Mapping[str, float]],
) -> list[dict[str, Any]]:
    grouped: defaultdict[tuple[str, str], list[Mapping[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[(str(row["answer_set_id"]), str(row["condition_id"]))].append(row)
    output: list[dict[str, Any]] = []
    answer_set_order = {
        "model1-qwen-main60": 1,
        "model2-deepseek-main60": 2,
        "full-context-deepseek-family-main60": 3,
    }
    for (answer_set, condition), group in sorted(
        grouped.items(), key=lambda item: (answer_set_order[item[0][0]], item[0][1])
    ):
        group = sorted(group, key=lambda item: int(item["global_position"]))
        backbone_id, backbone_label, served_model = ANSWER_SETS[answer_set]
        build = _condition_build_cost(condition, store_costs)
        query_prompt = [int(row["retrieval_prompt_tokens"]) + int(row["answer_prompt_tokens"]) for row in group]
        query_completion = [int(row["retrieval_completion_tokens"]) + int(row["answer_completion_tokens"]) for row in group]
        latency_values = [int(row["elapsed_ms"]) for row in group if row["latency_available"] is True]
        row = {
            "record_id": _artifact_id("rq6-condition-", {"answer_set": answer_set, "condition": condition}),
            "protocol_version": PROTOCOL_VERSION,
            "answer_set_order": answer_set_order[answer_set],
            "answer_set_id": answer_set,
            "backbone_id": backbone_id,
            "backbone_label": backbone_label,
            "requested_model": group[0]["requested_model"],
            "served_model": served_model,
            "condition_id": condition,
            "storage_representation": group[0]["storage_representation"],
            "retrieval_system": group[0]["retrieval_system"],
            "access_regime": group[0]["access_regime"],
            "required_stores": list(CONDITION_STORES[condition]),
            "denominator": len(group),
            "token_f1": _mean([float(item["token_f1"]) for item in group]),
            "strict_accuracy": _mean([float(item["strict_score"]) for item in group]),
            "soft_semantic_score": _mean([float(item["soft_semantic_score"]) for item in group]),
            "mean_query_model_calls": _mean([int(item["query_model_calls"]) for item in group]),
            "mean_query_prompt_tokens": _mean(query_prompt),
            "mean_query_completion_tokens": _mean(query_completion),
            "mean_query_total_tokens": _mean([int(item["query_total_tokens"]) for item in group]),
            "mean_retrieval_total_tokens": _mean([int(item["retrieval_total_tokens"]) for item in group]),
            "mean_answer_total_tokens": _mean([int(item["answer_total_tokens"]) for item in group]),
            "main60_query_total_tokens": int(_sum(int(item["query_total_tokens"]) for item in group)),
            "total_failure_attempts": int(_sum(int(item["failure_attempt_count"]) for item in group)),
            "failure_tokens_separately_available": False,
            "mean_judge_model_calls": _mean([int(item["judge_model_calls"]) for item in group]),
            "mean_judge_total_tokens": _mean([int(item["judge_total_tokens"]) for item in group]),
            "main60_judge_total_tokens": int(_sum(int(item["judge_total_tokens"]) for item in group)),
            "latency_available_for_all_rows": len(latency_values) == len(group),
            "mean_elapsed_ms_when_available": _mean(latency_values) if latency_values else None,
            "construction_model_calls": int(build["model_calls"]),
            "construction_tool_calls": int(build["tool_calls"]),
            "construction_total_tokens": int(build["total_tokens"]),
            "exactly_comparable_to_deepseek_selective": condition != FULL_CONTEXT_CONDITION,
            "cost_scope": "online query" if condition != "E7" else "reconstructed online dual retrieval plus one fused Answerer",
        }
        _require(_close(row["mean_query_prompt_tokens"] + row["mean_query_completion_tokens"], row["mean_query_total_tokens"]), "RQ6 query token components differ")
        output.append(row)
    _require(len(output) == 15, "RQ6 condition summary count differs")
    return output


def _validate_e7_online_accounting(rows: Sequence[Mapping[str, Any]]) -> None:
    index = {
        (str(row["answer_set_id"]), str(row["condition_id"]), str(row["question_id"])): row
        for row in rows
    }
    for answer_set in ("model1-qwen-main60", "model2-deepseek-main60"):
        questions = sorted(
            str(row["question_id"])
            for row in rows
            if row["answer_set_id"] == answer_set and row["condition_id"] == "E7"
        )
        _require(len(questions) == QUESTION_COUNT, "RQ6 E7 denominator differs")
        for question_id in questions:
            e2 = index[(answer_set, "E2", question_id)]
            e6 = index[(answer_set, "E6", question_id)]
            e7 = index[(answer_set, "E7", question_id)]
            additive_fields = (
                "retrieval_provider_rounds",
                "retrieval_orchestration_calls",
                "retrieval_provider_request_attempts",
                "retrieval_model_calls",
                "retrieval_prompt_tokens",
                "retrieval_completion_tokens",
                "retrieval_total_tokens",
                "evidence_item_count",
                "evidence_bundle_characters",
            )
            for field in additive_fields:
                _require(
                    int(e7[field]) == int(e2[field]) + int(e6[field]),
                    f"RQ6 E7 additive field differs: {field}",
                )
            _require(e7["source_bundle_ids"] == [e2["evidence_bundle_id"], e6["evidence_bundle_id"]], "RQ6 E7 source bundles differ")
            _require(int(e2["evidence_budget_characters"]) == 16000, "RQ6 E2 evidence budget differs")
            _require(int(e6["evidence_budget_characters"]) == 16000, "RQ6 E6 evidence budget differs")
            _require(int(e7["evidence_budget_characters"]) == 32000, "RQ6 E7 evidence budget differs")
            _require(int(e7["search_action_count"]) == 0, "RQ6 E7 must not re-run retrieval")
            expected_calls = int(e7["retrieval_model_calls"])
            expected_tokens = int(e7["retrieval_total_tokens"])
            _require(
                int(e7["query_model_calls"]) == expected_calls + int(e7["answer_model_calls"]),
                "RQ6 E7 online query calls differ",
            )
            _require(
                int(e7["query_total_tokens"]) == expected_tokens + int(e7["answer_total_tokens"]),
                "RQ6 E7 online query tokens differ",
            )


def _e7_cost_views(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for order, answer_set in enumerate(("model1-qwen-main60", "model2-deepseek-main60"), 1):
        group = [row for row in rows if row["answer_set_id"] == answer_set and row["condition_id"] == "E7"]
        _require(len(group) == QUESTION_COUNT, "RQ6 E7 group count differs")
        for view_order, (view, calls_field, tokens_field, parents_available, description) in enumerate(
            (
                (
                    "incremental_fused_answer",
                    "answer_model_calls",
                    "answer_total_tokens",
                    True,
                    "Observed incremental cost when the E2 and E6 EvidenceBundles already exist",
                ),
                (
                    "reconstructed_online",
                    "query_model_calls",
                    "query_total_tokens",
                    False,
                    "E2 retrieval plus E6 retrieval plus one fused Answerer; parent Answerers excluded",
                ),
            ),
            1,
        ):
            body = {"answer_set": answer_set, "view": view}
            output.append(
                {
                    "record_id": _artifact_id("rq6-e7-cost-", body),
                    "protocol_version": PROTOCOL_VERSION,
                    "backbone_order": order,
                    "backbone_id": ANSWER_SETS[answer_set][0],
                    "answer_set_id": answer_set,
                    "cost_view_order": view_order,
                    "cost_view": view,
                    "parent_bundles_already_available": parents_available,
                    "mean_model_calls": _mean([int(item[calls_field]) for item in group]),
                    "mean_total_tokens": _mean([int(item[tokens_field]) for item in group]),
                    "main60_model_calls": int(_sum(int(item[calls_field]) for item in group)),
                    "main60_total_tokens": int(_sum(int(item[tokens_field]) for item in group)),
                    "parent_answerer_calls_included": False,
                    "description": description,
                }
            )
    return output


def _amortisation_rows(condition_rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for row in condition_rows:
        for workload in WORKLOADS:
            build_tokens = int(row["construction_total_tokens"])
            build_calls = int(row["construction_model_calls"])
            mean_query_tokens = float(row["mean_query_total_tokens"])
            mean_query_calls = float(row["mean_query_model_calls"])
            body = {"answer_set": row["answer_set_id"], "condition": row["condition_id"], "Q": workload}
            output.append(
                {
                    "record_id": _artifact_id("rq6-amortisation-", body),
                    "protocol_version": PROTOCOL_VERSION,
                    "answer_set_id": row["answer_set_id"],
                    "backbone_id": row["backbone_id"],
                    "condition_id": row["condition_id"],
                    "workload_questions": workload,
                    "construction_total_tokens": build_tokens,
                    "mean_query_total_tokens": mean_query_tokens,
                    "construction_tokens_per_question": build_tokens / workload,
                    "amortised_total_tokens_per_question": mean_query_tokens + build_tokens / workload,
                    "cumulative_total_tokens": build_tokens + workload * mean_query_tokens,
                    "construction_model_calls": build_calls,
                    "mean_query_model_calls": mean_query_calls,
                    "construction_calls_per_question": build_calls / workload,
                    "amortised_model_calls_per_question": mean_query_calls + build_calls / workload,
                    "maintenance_cost_included": False,
                }
            )
    _require(len(output) == 45, "RQ6 amortisation row count differs")
    return output


def _break_even_rows(condition_rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    index = {(str(row["answer_set_id"]), str(row["condition_id"])): row for row in condition_rows}
    comparisons = (
        ("E1", "E3", "controlled S1-to-S2 storage change under R1"),
        ("E2", "E4", "controlled S1-to-S2 storage change under R2"),
        ("E1", "E5", "S1-to-S3 system comparison under R1"),
        ("E2", "E6", "low-cost raw R2 versus curated R3 system comparison"),
        ("E2", "E7", "raw R2 versus online dual-source fusion"),
        ("E1", "E6", "raw R1 baseline versus curated R3 system comparison"),
        ("E1", "E7", "raw R1 baseline versus online dual-source fusion"),
    )
    output: list[dict[str, Any]] = []
    for answer_set in ("model1-qwen-main60", "model2-deepseek-main60"):
        for order, (baseline_condition, target_condition, label) in enumerate(comparisons, 1):
            baseline = index[(answer_set, baseline_condition)]
            target = index[(answer_set, target_condition)]
            incremental_build = int(target["construction_total_tokens"]) - int(baseline["construction_total_tokens"])
            per_query_saving = float(baseline["mean_query_total_tokens"]) - float(target["mean_query_total_tokens"])
            finite = incremental_build > 0 and per_query_saving > 0
            exact = incremental_build / per_query_saving if finite else None
            first_integer = math.ceil(exact) if exact is not None else None
            body = {"answer_set": answer_set, "baseline": baseline_condition, "target": target_condition}
            output.append(
                {
                    "record_id": _artifact_id("rq6-break-even-", body),
                    "protocol_version": PROTOCOL_VERSION,
                    "answer_set_id": answer_set,
                    "backbone_id": baseline["backbone_id"],
                    "comparison_order": order,
                    "comparison_label": label,
                    "baseline_condition": baseline_condition,
                    "target_condition": target_condition,
                    "incremental_construction_tokens": incremental_build,
                    "observed_query_tokens_saved_per_question": per_query_saving,
                    "finite_token_break_even": finite,
                    "break_even_questions_exact": exact,
                    "first_integer_question_after_break_even": first_integer,
                    "quality_equivalence_assumed": False,
                    "interpretation": (
                        "Token-accounting break-even only; quality still differs"
                        if finite
                        else "No token-cost break-even under the observed mean query rates"
                    ),
                }
            )
    _require(len(output) == 14, "RQ6 break-even row count differs")
    return output


def _pareto_scopes(condition_rows: Sequence[Mapping[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    qwen = [dict(row) for row in condition_rows if row["answer_set_id"] == "model1-qwen-main60"]
    deepseek = [dict(row) for row in condition_rows if row["answer_set_id"] == "model2-deepseek-main60"]
    full_context = [dict(row) for row in condition_rows if row["condition_id"] == FULL_CONTEXT_CONDITION]
    _require((len(qwen), len(deepseek), len(full_context)) == (7, 7, 1), "RQ6 Pareto scope count differs")
    return {
        "qwen_selective_exact": qwen,
        "deepseek_selective_exact": deepseek,
        "deepseek_family_diagnostic": deepseek + full_context,
    }


def _pareto_rows(condition_rows: Sequence[Mapping[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    membership: list[dict[str, Any]] = []
    frontiers: list[dict[str, Any]] = []
    scopes = _pareto_scopes(condition_rows)
    for scope_order, (scope, candidates) in enumerate(scopes.items(), 1):
        diagnostic = scope == "deepseek_family_diagnostic"
        for quality_order, quality_metric in enumerate(QUALITY_METRICS, 1):
            for cost_order, cost_metric in enumerate(COST_METRICS, 1):
                frontier_conditions: list[str] = []
                ordered_candidates = sorted(candidates, key=lambda item: (float(item[cost_metric]), str(item["condition_id"])))
                for candidate in ordered_candidates:
                    dominators: list[str] = []
                    quality_value = float(candidate[quality_metric])
                    cost_value = float(candidate[cost_metric])
                    for other in candidates:
                        if other["record_id"] == candidate["record_id"]:
                            continue
                        other_quality = float(other[quality_metric])
                        other_cost = float(other[cost_metric])
                        no_worse = other_quality >= quality_value - FLOAT_TOLERANCE and other_cost <= cost_value + FLOAT_TOLERANCE
                        strictly_better = other_quality > quality_value + FLOAT_TOLERANCE or other_cost < cost_value - FLOAT_TOLERANCE
                        if no_worse and strictly_better:
                            dominators.append(str(other["condition_id"]))
                    efficient = not dominators
                    if efficient:
                        frontier_conditions.append(str(candidate["condition_id"]))
                    body = {
                        "scope": scope,
                        "quality": quality_metric,
                        "cost": cost_metric,
                        "condition": candidate["condition_id"],
                    }
                    membership.append(
                        {
                            "record_id": _artifact_id("rq6-pareto-member-", body),
                            "protocol_version": PROTOCOL_VERSION,
                            "scope_order": scope_order,
                            "comparison_scope": scope,
                            "diagnostic_mixed_served_model_scope": diagnostic,
                            "quality_metric_order": quality_order,
                            "quality_metric": quality_metric,
                            "cost_metric_order": cost_order,
                            "cost_metric": cost_metric,
                            "answer_set_id": candidate["answer_set_id"],
                            "backbone_id": candidate["backbone_id"],
                            "condition_id": candidate["condition_id"],
                            "quality_value": quality_value,
                            "cost_value": cost_value,
                            "pareto_efficient": efficient,
                            "dominating_conditions": sorted(dominators),
                        }
                    )
                body = {"scope": scope, "quality": quality_metric, "cost": cost_metric}
                frontiers.append(
                    {
                        "record_id": _artifact_id("rq6-pareto-frontier-", body),
                        "protocol_version": PROTOCOL_VERSION,
                        "scope_order": scope_order,
                        "comparison_scope": scope,
                        "diagnostic_mixed_served_model_scope": diagnostic,
                        "quality_metric_order": quality_order,
                        "quality_metric": quality_metric,
                        "cost_metric_order": cost_order,
                        "cost_metric": cost_metric,
                        "candidate_count": len(candidates),
                        "frontier_conditions_in_ascending_cost": frontier_conditions,
                        "frontier_count": len(frontier_conditions),
                    }
                )
    _require(len(membership) == 132, "RQ6 Pareto membership count differs")
    _require(len(frontiers) == 18, "RQ6 Pareto frontier count differs")
    return membership, frontiers


def _scenario_rows(condition_rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    index = {(str(row["answer_set_id"]), str(row["condition_id"])): row for row in condition_rows}

    def stats(answer_set: str, condition: str) -> str:
        row = index[(answer_set, condition)]
        return (
            f"Strict={float(row['strict_accuracy']):.3f}; Soft={float(row['soft_semantic_score']):.3f}; "
            f"F1={float(row['token_f1']):.3f}; query tokens={float(row['mean_query_total_tokens']):.1f}"
        )

    specs = (
        (
            "semantic_quality_first",
            "Highest observed semantic quality",
            ["Qwen:E5", "DeepSeek-selective:E1", "DeepSeek-family:B3-FullContext"],
            f"{stats('model1-qwen-main60','E5')} | {stats('model2-deepseek-main60','E1')} | {stats('full-context-deepseek-family-main60',FULL_CONTEXT_CONDITION)}",
            "Full Context is diagnostic: its served-model identifier differs, and its Strict lead is one question.",
        ),
        (
            "lexical_quality_first",
            "Highest observed LoCoMo Token F1",
            ["Qwen:E3", "DeepSeek:E1"],
            f"{stats('model1-qwen-main60','E3')} | {stats('model2-deepseek-main60','E1')}",
            "Lexical and semantic rankings differ; this is not a semantic-quality recommendation.",
        ),
        (
            "minimum_online_tokens",
            "Lowest observed online query-token cost",
            ["Qwen:E2", "DeepSeek:E2"],
            f"{stats('model1-qwen-main60','E2')} | {stats('model2-deepseek-main60','E2')}",
            "E2 is cost-first; R2 is semantically weaker than R1 on both raw-store comparisons.",
        ),
        (
            "selective_quality_cost_ladder",
            "Selective quality--token balance without a single scalar score",
            ["Qwen:E2->E4->E6->E3->E5", "DeepSeek:E2->E7->E1"],
            "Choose the lowest-cost Pareto point that meets the required quality threshold.",
            "E3 needs modest S2 amortisation; E7 assumes that the expensive S3 asset already exists or is reused at scale.",
        ),
        (
            "cross_backbone_semantic_stability",
            "Stable semantic benefit across backbones",
            ["E5 over E3"],
            "E5-E3 raises Strict and Soft under both backbones while lowering F1 under both.",
            "E5 has the highest construction cost and high query cost; stability does not imply efficiency.",
        ),
        (
            "multi_hop_or_temporal_coverage",
            "Coverage-oriented multi-hop or temporal workload",
            ["E5", "DeepSeek escalation:E7"],
            "RQ1 identifies E5 as the strongest general evidence-coverage configuration; RQ3 shows DeepSeek E7 gains on multi-hop and temporal questions.",
            "E7 is not a universal Qwen default, and E5 requires expensive curation.",
        ),
        (
            "provenance_and_auditability",
            "Simple raw-source provenance and low construction complexity",
            ["E1"],
            "S1 has zero model-based build cost; R1 produces traceable source-selected EvidenceBundles.",
            "E1 is substantially more expensive per query than E2.",
        ),
        (
            "diagnostic_or_recovery",
            "Diagnose suspected retrieval omission or difficult evidence composition",
            ["B3-FullContext", "DeepSeek:E7"],
            "Full Context restores complete visibility; E7 combines complementary raw and curated evidence.",
            "Use as targeted escalation. Full Context is not an oracle, and E7 pays two retrieval paths online.",
        ),
    )
    rows: list[dict[str, Any]] = []
    for order, (scenario_id, objective, recommendations, evidence, caveat) in enumerate(specs, 1):
        body = {"scenario": scenario_id, "recommendations": recommendations}
        rows.append(
            {
                "record_id": _artifact_id("rq6-scenario-", body),
                "protocol_version": PROTOCOL_VERSION,
                "scenario_order": order,
                "scenario_id": scenario_id,
                "decision_objective": objective,
                "recommended_conditions": recommendations,
                "observed_evidence": evidence,
                "principal_caveat": caveat,
                "latency_claim_made": False,
                "monetary_price_claim_made": False,
            }
        )
    return rows


def _figure_rows(
    condition_rows: Sequence[Mapping[str, Any]], membership: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    membership_index = {
        (str(row["comparison_scope"]), str(row["quality_metric"]), str(row["cost_metric"]), str(row["answer_set_id"]), str(row["condition_id"])): row
        for row in membership
    }
    scopes = {
        "qwen_selective_exact": [row for row in condition_rows if row["answer_set_id"] == "model1-qwen-main60"],
        "deepseek_family_diagnostic": [row for row in condition_rows if row["answer_set_id"] != "model1-qwen-main60"],
    }
    output: list[dict[str, Any]] = []
    for scope_order, (scope, candidates) in enumerate(scopes.items(), 1):
        for metric_order, metric in enumerate(QUALITY_METRICS, 1):
            for candidate in sorted(candidates, key=lambda row: str(row["condition_id"])):
                key = (scope, metric, "mean_query_total_tokens", str(candidate["answer_set_id"]), str(candidate["condition_id"]))
                member = membership_index[key]
                body = {"scope": scope, "metric": metric, "condition": candidate["condition_id"]}
                output.append(
                    {
                        "record_id": _artifact_id("rq6-figure-5-12-", body),
                        "protocol_version": PROTOCOL_VERSION,
                        "scope_order": scope_order,
                        "comparison_scope": scope,
                        "quality_metric_order": metric_order,
                        "quality_metric": metric,
                        "condition_id": candidate["condition_id"],
                        "answer_set_id": candidate["answer_set_id"],
                        "mean_query_total_tokens": candidate["mean_query_total_tokens"],
                        "quality_value": candidate[metric],
                        "pareto_efficient": member["pareto_efficient"],
                        "diagnostic_mixed_served_model_scope": scope == "deepseek_family_diagnostic",
                    }
                )
    _require(len(output) == 45, "RQ6 Figure 5.12 input count differs")
    return output


def _decision_summary(
    condition_rows: Sequence[Mapping[str, Any]],
    break_even: Sequence[Mapping[str, Any]],
    recovery_rows: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    index = {(str(row["answer_set_id"]), str(row["condition_id"])): row for row in condition_rows}
    finite = [row for row in break_even if row["finite_token_break_even"]]
    _require(len(finite) == 6, "RQ6 finite break-even count differs")
    _require({row["target_condition"] for row in finite} == {"E3", "E6", "E7"}, "RQ6 unexpected finite break-even")
    qwen_e2 = index[("model1-qwen-main60", "E2")]
    deepseek_e2 = index[("model2-deepseek-main60", "E2")]
    qwen_e5 = index[("model1-qwen-main60", "E5")]
    deepseek_e7 = index[("model2-deepseek-main60", "E7")]
    full_context = index[("full-context-deepseek-family-main60", FULL_CONTEXT_CONDITION)]
    recovery_by_condition: defaultdict[str, int] = defaultdict(int)
    for row in recovery_rows:
        recovery_by_condition[str(row["condition_id"])] += int(row["known_recovery_total_tokens"])
    return {
        "schema_version": 1,
        "protocol_version": PROTOCOL_VERSION,
        "rq6_direct_answer": (
            "No single condition is best under every objective. E2 is the lowest-token path; E3 is the strongest "
            "Qwen balance after its modest S2 build is amortised; E5 is the Qwen semantic-quality maximum at very "
            "high cost; E7 is the strongest DeepSeek selective query-time compromise when S3 is already available; "
            "E1 remains the no-build auditable quality baseline; and Full Context is a diagnostic semantic-quality "
            "fallback rather than a universal replacement for retrieval."
        ),
        "findings": [
            {
                "finding_id": "cost_first",
                "conclusion": "E2 is the lowest-token online path under both backbones, but it trades away semantic quality.",
                "evidence": {
                    "qwen_mean_query_tokens": qwen_e2["mean_query_total_tokens"],
                    "qwen_strict": qwen_e2["strict_accuracy"],
                    "deepseek_mean_query_tokens": deepseek_e2["mean_query_total_tokens"],
                    "deepseek_strict": deepseek_e2["strict_accuracy"],
                },
            },
            {
                "finding_id": "qwen_quality",
                "conclusion": "For Qwen, E5 gives the highest Strict and Soft scores, but it is the most expensive store and query path.",
                "evidence": {
                    "strict": qwen_e5["strict_accuracy"],
                    "soft": qwen_e5["soft_semantic_score"],
                    "mean_query_tokens": qwen_e5["mean_query_total_tokens"],
                    "construction_tokens": qwen_e5["construction_total_tokens"],
                },
            },
            {
                "finding_id": "deepseek_selective_balance",
                "conclusion": "For DeepSeek selective retrieval, E7 reaches the joint-best Strict score at far lower query-token cost than E1 or E5, although E1 retains slightly higher Soft and F1.",
                "evidence": {
                    "e7_strict": deepseek_e7["strict_accuracy"],
                    "e7_soft": deepseek_e7["soft_semantic_score"],
                    "e7_mean_query_tokens": deepseek_e7["mean_query_total_tokens"],
                    "e1_mean_query_tokens": index[("model2-deepseek-main60", "E1")]["mean_query_total_tokens"],
                },
            },
            {
                "finding_id": "full_context_boundary",
                "conclusion": "Full Context has the highest DeepSeek-family Strict and Soft scores, but only by one Strict-correct question and with lower F1 than several selective systems.",
                "evidence": {
                    "strict": full_context["strict_accuracy"],
                    "soft": full_context["soft_semantic_score"],
                    "f1": full_context["token_f1"],
                    "mean_query_tokens": full_context["mean_query_total_tokens"],
                    "exact_served_model_match": False,
                },
            },
            {
                "finding_id": "construction_amortisation",
                "conclusion": (
                    "S2 construction is modest and E3 crosses E1 after 46 Qwen or 35 DeepSeek queries. "
                    "S3-backed E6/E7 can amortise only against the expensive E1 path after 187--324 repeated "
                    "queries; they never become token-saving alternatives to E2, and E5 has no token break-even."
                ),
                "evidence": {
                    "break_even_questions": {
                        f"{row['backbone_id']}:{row['baseline_condition']}->{row['target_condition']}": row[
                            "first_integer_question_after_break_even"
                        ]
                        for row in finite
                    },
                    "s3_construction_tokens": 30864958,
                },
            },
            {
                "finding_id": "recovery_overhead",
                "conclusion": (
                    "Observed recovery overhead is concentrated in R1 conditions; 39 of 41 failed attempts "
                    "account for 10.13 million additional tokens, while two DNS failures have unknown usage."
                ),
                "evidence": {
                    "known_attempts": 39,
                    "unknown_attempts": 2,
                    "known_recovery_total_tokens": sum(recovery_by_condition.values()),
                    "tokens_by_condition": dict(sorted(recovery_by_condition.items())),
                },
            },
            {
                "finding_id": "bottleneck_implication",
                "conclusion": "More retrieval work is not automatically better: RQ5 attributes more confirmed internal failures to Answerer utilisation than to retrieval.",
                "evidence": {"answerer_failures": 68, "retrieval_failures": 42, "confirmed_internal_failures": 123},
            },
        ],
        "unavailable_claims": {
            "cross_condition_latency_ranking": "E1--E7 native latency is unavailable",
            "monetary_ranking": "No common price schedule was defined",
            "complete_recovery_token_ranking": (
                "Recovery usage is isolated and reported separately for 39 of 41 attempts; "
                "two DNS failures have unknown token usage"
            ),
            "measured_maintenance_ranking": "Long-term updates were not executed",
        },
    }


def _compute(root: Path) -> tuple[dict[str, list[dict[str, Any]]], dict[str, Any], dict[str, Any]]:
    upstream = _validate_upstream(root)
    source_path = root / STAGE_A_DIR / "master-table.jsonl"
    source_rows = _validate_stage_a_rows(_read_jsonl(source_path))
    store_rows, store_costs = _load_store_costs(root)
    recovery_rows, recovery_provenance, recovery_diagnostics = _load_recovery_costs(root)
    _validate_e7_online_accounting(source_rows)
    condition_rows = _quality_cost_rows(source_rows, store_costs)
    _attach_recovery_costs(condition_rows, recovery_rows)
    e7_rows = _e7_cost_views(source_rows)
    amortisation = _amortisation_rows(condition_rows)
    break_even = _break_even_rows(condition_rows)
    membership, frontiers = _pareto_rows(condition_rows)
    scenarios = _scenario_rows(condition_rows)
    figure = _figure_rows(condition_rows, membership)
    summary = _decision_summary(condition_rows, break_even, recovery_rows)

    tables = {
        "condition-quality-cost": condition_rows,
        "store-construction-cost": store_rows,
        "recovery-cost": recovery_rows,
        "e7-cost-views": e7_rows,
        "amortisation-scenarios": amortisation,
        "build-break-even": break_even,
        "pareto-membership": membership,
        "pareto-frontiers": frontiers,
        "scenario-decision-matrix": scenarios,
        "table-5-33-inputs": [dict(row) for row in condition_rows],
        "table-5-34-inputs": [dict(row) for row in scenarios],
        "figure-5-12-inputs": figure,
    }
    provenance = {
        "upstream": upstream,
        "stage_a_master": _artifact(root, source_path),
        "store_manifests": {
            "S1": _artifact(root, root / S1_MANIFEST),
            "S2": _artifact(root, root / S2_MANIFEST),
            "S3": _artifact(root, root / S3_MANIFEST),
        },
        "formal_recovery_cost": recovery_provenance,
    }
    diagnostics = {
        "source_rows": len(source_rows),
        "condition_rows": len(condition_rows),
        "store_rows": len(store_rows),
        "recovery_rows": len(recovery_rows),
        "recovery": recovery_diagnostics,
        "pareto_membership_rows": len(membership),
        "scenario_rows": len(scenarios),
        "qwen_lowest_token_condition": min(
            (row for row in condition_rows if row["answer_set_id"] == "model1-qwen-main60"),
            key=lambda row: float(row["mean_query_total_tokens"]),
        )["condition_id"],
        "deepseek_lowest_token_condition": min(
            (row for row in condition_rows if row["answer_set_id"] == "model2-deepseek-main60"),
            key=lambda row: float(row["mean_query_total_tokens"]),
        )["condition_id"],
        "finite_build_break_even_rows": sum(bool(row["finite_token_break_even"]) for row in break_even),
        "latency_ranking_computed": False,
        "monetary_ranking_computed": False,
        "maintenance_numeric_ranking_computed": False,
        "failed_attempt_token_ranking_computed": True,
    }
    return tables, summary, {"provenance": provenance, "diagnostics": diagnostics}


def _schema(tables: Mapping[str, Sequence[Mapping[str, Any]]]) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "protocol_version": PROTOCOL_VERSION,
        "tables": {
            name: {"row_count": len(rows), "fields": list(rows[0])}
            for name, rows in tables.items()
        },
        "quality_direction": "higher_is_better",
        "cost_direction": "lower_is_better",
        "pareto_definition": (
            "A condition is dominated when another condition has no lower quality and no greater observed cost, "
            "with at least one strict inequality."
        ),
        "primary_cost_proxy": "mean_query_total_tokens",
        "secondary_cost_proxy": "mean_query_model_calls",
        "workload_questions": list(WORKLOADS),
    }


def _source_manifest(root: Path, metadata: Mapping[str, Any]) -> dict[str, Any]:
    body = {
        "schema_version": 1,
        "protocol_version": PROTOCOL_VERSION,
        "scope": "offline Main-60 RQ6 quality, cost, Pareto, and conditional system selection",
        "provenance": metadata["provenance"],
        "boundaries": {
            "new_model_calls": False,
            "network_calls": False,
            "formal_source_mutation": False,
            "latency_ranking": False,
            "monetary_pricing": False,
            "maintenance_numeric_ranking": False,
            "recovery_cost_separate_from_successful_query": True,
            "recovery_token_usage_complete": False,
            "recovery_token_usage_known_attempts": 39,
            "recovery_token_usage_unknown_attempts": 2,
            "full_context_exact_served_model_match": False,
            "judge_cost_is_evaluation_only": True,
            "e7_online_cost_excludes_parent_answerers": True,
        },
    }
    return {"source_manifest_id": _artifact_id("rq6-sources-", body), **body}


def _readme() -> str:
    return """# Chapter 5 RQ6: quality, cost, and practical system choice

This audited artifact performs the final offline RQ6 synthesis over the frozen
Main-60 results. It reports observed quality and query resources, S1--S3
construction cost, E7's incremental and reconstructed-online cost views,
conditional construction amortisation, Pareto membership, and a scenario-based
decision matrix.

The central result is conditional rather than a single ranking. E2 is the
lowest-token online path under both backbones but gives up semantic quality.
E5 is the Qwen quality-and-coverage option, with very high S3 construction and
query cost. Under DeepSeek, E7 is the strongest selective quality--token
compromise, while E1 retains slightly higher Soft score and F1. Full Context
has the highest DeepSeek-family Strict and Soft scores, but the lead is one
question, its served-model identifier differs, and its F1 is lower than several
selective systems. It is therefore a diagnostic or recovery path rather than a
universal retrieval replacement.

No cross-condition latency, monetary, or numeric maintenance ranking is
inferred. Recovery usage is reported separately for 39 of 41 formal
failed attempts; two DNS failures have unknown token usage. Judge tokens are
evaluation-only and remain separate from deployment query cost. No API or
network call was made, and no experiment output was modified.
"""


def _payloads(
    tables: Mapping[str, Sequence[Mapping[str, Any]]],
    summary: Mapping[str, Any],
    manifest: Mapping[str, Any],
) -> dict[str, bytes]:
    payloads: dict[str, bytes] = {
        "README.md": _readme().encode("utf-8"),
        "schema.json": canonical_json_bytes(_schema(tables)) + b"\n",
        "source-manifest.json": canonical_json_bytes(dict(manifest)) + b"\n",
        "decision-summary.json": canonical_json_bytes(dict(summary)) + b"\n",
    }
    for name, rows in tables.items():
        payloads[f"{name}.csv"] = _csv_payload(rows)
        payloads[f"{name}.jsonl"] = _jsonl_payload(rows)
    return payloads


def _audit_body(
    manifest: Mapping[str, Any], metadata: Mapping[str, Any], hashes: Mapping[str, str],
) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "protocol_version": PROTOCOL_VERSION,
        "status": "passed",
        "scope": "RQ6 observed quality--cost, Pareto, amortisation, and scenario-based decision synthesis",
        "source_manifest_id": manifest["source_manifest_id"],
        "diagnostics": metadata["diagnostics"],
        "output_sha256": dict(sorted(hashes.items())),
        "quality_cost_computed": True,
        "pareto_computed": True,
        "construction_amortisation_computed": True,
        "recovery_cost_computed_separately": True,
        "recovery_token_usage_known_attempts": 39,
        "recovery_token_usage_unknown_attempts": 2,
        "scenario_selection_computed": True,
        "no_api_calls": True,
        "no_network_calls": True,
        "formal_source_mutation": False,
        "cross_condition_latency_ranking_computed": False,
        "monetary_ranking_computed": False,
        "maintenance_numeric_ranking_computed": False,
    }


def _marker(audit: Mapping[str, Any], audit_sha256: str) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "protocol_version": PROTOCOL_VERSION,
        "status": "passed",
        "audit_id": audit["audit_id"],
        "audit_sha256": audit_sha256,
        "source_rows": SOURCE_ROW_COUNT,
        "condition_rows": 15,
        "no_api_calls": True,
        "no_network_calls": True,
    }


def audit_rq6_output(*, repo_root: Path, output_dir: Path) -> dict[str, Any]:
    root, output = Path(repo_root).resolve(), Path(output_dir).resolve()
    _require(output.is_dir() and not output.is_symlink(), "RQ6 output directory is unsafe")
    tables, summary, metadata = _compute(root)
    manifest = _source_manifest(root, metadata)
    payloads = _payloads(tables, summary, manifest)
    hashes = {name: hashlib.sha256(payload).hexdigest() for name, payload in sorted(payloads.items())}
    body = _audit_body(manifest, metadata, hashes)
    audit = {"audit_id": _artifact_id("rq6-audit-", body), **body}
    audit_payload = canonical_json_bytes(audit) + b"\n"
    marker_payload = canonical_json_bytes(_marker(audit, hashlib.sha256(audit_payload).hexdigest())) + b"\n"
    expected_names = set(payloads) | {"audit.json", "RQ6.PASSED"}
    entries = list(output.iterdir())
    _require(all(path.is_file() and not path.is_symlink() for path in entries), "RQ6 output contains an unsafe entry")
    _require({path.name for path in entries} == expected_names, "RQ6 output file set differs")
    for name, payload in payloads.items():
        _require((output / name).read_bytes() == payload, f"RQ6 artifact differs: {name}")
    _require((output / "audit.json").read_bytes() == audit_payload, "RQ6 audit differs")
    _require((output / "RQ6.PASSED").read_bytes() == marker_payload, "RQ6 marker differs")
    return audit


def build_rq6(*, repo_root: Path, output_dir: Path) -> dict[str, Any]:
    root, destination = Path(repo_root).resolve(), Path(output_dir).resolve()
    _require(root.is_dir() and not root.is_symlink(), "Repository root is unsafe")
    _require(not destination.exists(), "RQ6 output already exists")
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=f".{destination.name}.in-progress-", dir=destination.parent))
    try:
        tables, summary, metadata = _compute(root)
        manifest = _source_manifest(root, metadata)
        payloads = _payloads(tables, summary, manifest)
        for name, payload in payloads.items():
            _write(temporary / name, payload)
        hashes = {name: _sha256_file(temporary / name) for name in sorted(payloads)}
        body = _audit_body(manifest, metadata, hashes)
        audit = {"audit_id": _artifact_id("rq6-audit-", body), **body}
        _write(temporary / "audit.json", canonical_json_bytes(audit) + b"\n")
        _write(
            temporary / "RQ6.PASSED",
            canonical_json_bytes(_marker(audit, _sha256_file(temporary / "audit.json"))) + b"\n",
        )
        audited = audit_rq6_output(repo_root=root, output_dir=temporary)
        _require(audited["status"] == "passed", "RQ6 pre-publication audit failed")
        os.rename(temporary, destination)
        descriptor = os.open(destination.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
    except Exception:
        shutil.rmtree(temporary, ignore_errors=True)
        raise
    return audit_rq6_output(repo_root=root, output_dir=destination)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build or audit Chapter 5 RQ6 artifacts")
    parser.add_argument("command", choices=("build", "audit"))
    parser.add_argument("--repo-root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--output-dir", type=Path)
    return parser


def main(argv: list[str] | None = None) -> None:
    args = _parser().parse_args(argv)
    root = args.repo_root.resolve()
    output = (args.output_dir or root / DEFAULT_OUTPUT_DIR).resolve()
    result = build_rq6(repo_root=root, output_dir=output) if args.command == "build" else audit_rq6_output(repo_root=root, output_dir=output)
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
