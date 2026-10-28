"""Build and audit the Chapter 5 RQ3 dual-source-fusion artifact.

RQ3 evaluates E7 against its two parent evidence paths, E2 and E6.  The
analysis is paired by question and fully offline.  It reads only the frozen
Stage A table, validates the E7 parent-bundle and no-new-search contract, and
publishes answer effects, category effects, judge-label transitions, strict
fusion outcomes, source-ID overlap, and publication-safe RQ5 review
candidates.

The automatic analysis never interprets source-ID overlap as semantic
conflict.  Repair and Harm are observational Strict-Accuracy states; causal
mechanism attribution remains deferred to RQ5.
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
from pathlib import Path
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
from .fusion import FUSION_CONTRACT_SHA256


STAGE_RQ3_PROTOCOL_VERSION = "chapter5-main60-rq3-v1"

BACKBONES = ("qwen", "deepseek")
PARENTS = ("E2", "E6")
CONDITIONS = ("E2", "E6", "E7")
QUESTION_COUNT = 60
EVIDENCE_QUESTION_COUNT = 58
FLOAT_TOLERANCE = 1e-12

CATEGORIES = (
    (1, "multi-hop", 13, 13),
    (2, "temporal", 13, 13),
    (3, "open-domain", 7, 5),
    (4, "single-hop", 27, 27),
)
CATEGORY_ORDER = {category: order for order, (category, _, _, _) in enumerate(CATEGORIES, 1)}

ANSWER_METRICS = (
    ("token_precision", "token_precision"),
    ("token_recall", "token_recall"),
    ("token_f1", "token_f1"),
    ("strict_accuracy", "strict_score"),
    ("soft_semantic_score", "soft_semantic_score"),
)

JUDGE_LABELS = ("incorrect", "partial", "correct")
JUDGE_ORDINAL = {"incorrect": 0, "partial": 1, "correct": 2}
OUTCOME_STATES = ("repair", "preserve", "harm", "unresolved")
PARENT_PROFILES = (
    "both_correct",
    "e2_only_correct",
    "e6_only_correct",
    "neither_correct",
)

EXPECTED_STAGE_A_AUDIT_ID = (
    "stage-a-audit-5f55ec411f097df7206fdae5e71742641aa8868b4128ac32262f034877a1d7f3"
)
EXPECTED_STAGE_A_SOURCE_MANIFEST_ID = (
    "stage-a-sources-90efa256f7981450cf38503912406a1e30766e8440b443899cab953fe9fece3c"
)
EXPECTED_FUSION_CONTRACT_SHA256 = (
    "035770f66df01bfdc937227a819ada720163fd6fa03416d88e5484ea54ae0abb"
)
EXPECTED_FROZEN_SHA256 = {
    "stage_a_audit": "39aee6ea88c92df547cc98f7b6b343415a558d31a354184e30f0d36acc331966",
    "stage_a_marker": "f4b3aa6f80d2ee7bc4eb9682e37ec85780d4f37a15b22ef65eb78e46ee6f3e34",
    "stage_a_main": "4ccb595baddaec2ddf54a708e94102a45c72e0ddaff63a6c69c940232153f3f8",
    "stage_a_schema": "21295503a3b8e0cadcde9a61a46be1e383c38da329dbc66d716b78faa72ede09",
    "stage_a_source_manifest": "2b1f56d0897904fb9d4b8487111ecc2d7b55848f54f97dbfe34de53c16b59a65",
    "fusion_code": "ded6c52c82e0e383e26c8c10d26de23c0199c1d3f87e558ed28ee5c20f717238",
}

FORBIDDEN_FIELDS = {
    "question",
    "question_text",
    "reference_answer",
    "candidate_answer",
    "answer",
    "answer_text",
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


def _artifact_id(prefix: str, body: Mapping[str, Any]) -> str:
    return prefix + sha256_bytes(canonical_json_bytes(dict(body)))


def _close(left: float, right: float) -> bool:
    return math.isclose(float(left), float(right), rel_tol=0.0, abs_tol=FLOAT_TOLERANCE)


def _mean(values: Sequence[float]) -> float:
    _require(bool(values), "RQ3 cannot average an empty sequence")
    numeric = [float(value) for value in values]
    _require(all(math.isfinite(value) for value in numeric), "RQ3 contains a non-finite value")
    return math.fsum(numeric) / len(numeric)


def _optional_mean(values: Sequence[float | None]) -> float:
    present = [float(value) for value in values if value is not None]
    return _mean(present)


def _validate_frozen_input(
    *, repo_root: Path, stage_a_dir: Path,
) -> dict[str, Any]:
    root = repo_root.resolve()
    stage_a = stage_a_dir.resolve()
    expected = (root / "artifacts/chapter5-main60-analysis-v1/stage-a").resolve()
    _require(root.is_dir() and not root.is_symlink(), "Repository root is unsafe")
    _require(stage_a == expected, "Stage A is not the frozen repository artifact")
    _require(stage_a.is_dir() and not stage_a.is_symlink(), "Stage A directory is unsafe")

    frozen_files = {
        stage_a / "audit.json": EXPECTED_FROZEN_SHA256["stage_a_audit"],
        stage_a / "STAGE-A.PASSED": EXPECTED_FROZEN_SHA256["stage_a_marker"],
        stage_a / "e1-e7-main.jsonl": EXPECTED_FROZEN_SHA256["stage_a_main"],
        stage_a / "schema.json": EXPECTED_FROZEN_SHA256["stage_a_schema"],
        stage_a / "source-manifest.json": EXPECTED_FROZEN_SHA256["stage_a_source_manifest"],
        root / "fs_memory_lab/fusion.py": EXPECTED_FROZEN_SHA256["fusion_code"],
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
    _require(
        FUSION_CONTRACT_SHA256 == EXPECTED_FUSION_CONTRACT_SHA256,
        "E7 fusion contract identity differs",
    )
    return {
        "stage_a_audit_id": audit["audit_id"],
        "stage_a_source_manifest_id": source_manifest["source_manifest_id"],
        "stage_a_audit_sha256": EXPECTED_FROZEN_SHA256["stage_a_audit"],
        "stage_a_main_sha256": EXPECTED_FROZEN_SHA256["stage_a_main"],
        "fusion_contract_sha256": FUSION_CONTRACT_SHA256,
        "fusion_code_sha256": EXPECTED_FROZEN_SHA256["fusion_code"],
    }


def _row_key(row: Mapping[str, Any]) -> tuple[str, str, str]:
    return str(row["backbone_id"]), str(row["condition_id"]), str(row["question_id"])


def _validate_source_rows(
    rows: Sequence[Mapping[str, Any]],
) -> list[tuple[dict[str, Any], dict[str, Any], dict[str, Any]]]:
    _require(len(rows) == 840, "RQ3 Stage A row count differs")
    subset = [dict(row) for row in rows if str(row["condition_id"]) in CONDITIONS]
    _require(len(subset) == 360, "RQ3 requires exactly 360 E2/E6/E7 rows")
    index = {_row_key(row): row for row in subset}
    _require(len(index) == 360, "RQ3 source keys are not unique")
    _require({row["backbone_id"] for row in subset} == set(BACKBONES), "RQ3 backbones differ")
    _require({row["condition_id"] for row in subset} == set(CONDITIONS), "RQ3 conditions differ")
    _require(all(row.get("is_e1_e7_main") is True for row in subset), "RQ3 contains a non-main row")
    _require(all(FORBIDDEN_FIELDS.isdisjoint(row) for row in subset), "RQ3 source contains forbidden text")

    expected_models = {
        "qwen": ("model1-qwen-main60", "coding", "qwen3.8:27b"),
        "deepseek": ("model2-deepseek-main60", "x-test-2", "deepseek-v4.1-flash"),
    }
    for row in subset:
        answer_set, requested, served = expected_models[str(row["backbone_id"])]
        _require(
            (row["answer_set_id"], row["requested_model"], row["served_model"])
            == (answer_set, requested, served),
            "RQ3 answer-model identity differs",
        )
        _require(
            (row["judge_requested_model"], row["judge_served_model"])
            == ("x-test-1", "glm-5.3-flash"),
            "RQ3 Judge identity differs",
        )

    triples: list[tuple[dict[str, Any], dict[str, Any], dict[str, Any]]] = []
    identity_fields = (
        "question_id",
        "question_sha256",
        "global_position",
        "category",
        "category_name",
        "evidence_eligible",
        "gold_dia_ids",
    )
    retrieval_sum_fields = (
        "retrieval_provider_rounds",
        "retrieval_filesystem_tool_calls",
        "retrieval_orchestration_calls",
        "retrieval_provider_request_attempts",
        "retrieval_model_calls",
        "retrieval_prompt_tokens",
        "retrieval_completion_tokens",
        "retrieval_total_tokens",
    )
    category_counts: Counter[tuple[str, int]] = Counter()
    evidence_counts: Counter[tuple[str, int]] = Counter()
    for backbone in BACKBONES:
        question_rows = [row for row in subset if row["backbone_id"] == backbone and row["condition_id"] == "E2"]
        question_rows.sort(key=lambda row: int(row["global_position"]))
        _require(len(question_rows) == QUESTION_COUNT, f"RQ3 E2 denominator differs: {backbone}")
        _require([int(row["global_position"]) for row in question_rows] == list(range(1, 61)), "RQ3 positions differ")
        for e2 in question_rows:
            question_id = str(e2["question_id"])
            e6 = index[(backbone, "E6", question_id)]
            e7 = index[(backbone, "E7", question_id)]
            _require(
                all(tuple(row[field] for field in identity_fields) == tuple(e2[field] for field in identity_fields) for row in (e6, e7)),
                f"RQ3 paired identity differs: {backbone}/{question_id}",
            )
            _require(
                (e2["storage_representation"], e2["retrieval_system"], e2["access_regime"])
                == ("S1", "R2", "selective_retrieval"),
                "RQ3 E2 design differs",
            )
            _require(
                (e6["storage_representation"], e6["retrieval_system"], e6["access_regime"])
                == ("S3", "R3", "selective_retrieval"),
                "RQ3 E6 design differs",
            )
            _require(
                (e7["storage_representation"], e7["retrieval_system"], e7["access_regime"])
                == ("E2+E6", "fixed_fusion", "dual_source_fusion"),
                "RQ3 E7 design differs",
            )
            _require(
                e7["source_bundle_ids"] == [e2["evidence_bundle_id"], e6["evidence_bundle_id"]],
                f"RQ3 E7 parent bundles differ: {backbone}/{question_id}",
            )
            _require(
                int(e2["evidence_budget_characters"]) == 16000
                and int(e6["evidence_budget_characters"]) == 16000
                and int(e7["evidence_budget_characters"]) == 32000,
                "RQ3 evidence budgets differ",
            )
            _require(int(e7["search_action_count"]) == 0, "RQ3 E7 performed a new search action")
            _require(
                int(e7["evidence_item_count"]) == int(e2["evidence_item_count"]) + int(e6["evidence_item_count"])
                and int(e7["evidence_bundle_characters"]) == int(e2["evidence_bundle_characters"]) + int(e6["evidence_bundle_characters"]),
                "RQ3 E7 evidence accounting differs",
            )
            _require(
                set(e7["retrieved_dia_ids"]) == set(e2["retrieved_dia_ids"]) | set(e6["retrieved_dia_ids"]),
                "RQ3 E7 source-ID union differs",
            )
            for field in retrieval_sum_fields:
                _require(
                    int(e7[field]) == int(e2[field]) + int(e6[field]),
                    f"RQ3 E7 inherited retrieval accounting differs: {field}",
                )
            _require(
                int(e7["query_model_calls"]) == int(e7["retrieval_model_calls"]) + int(e7["answer_model_calls"])
                and int(e7["query_total_tokens"]) == int(e7["retrieval_total_tokens"]) + int(e7["answer_total_tokens"]),
                "RQ3 E7 query accounting differs",
            )
            category = int(e2["category"])
            category_counts[(backbone, category)] += 1
            if bool(e2["evidence_eligible"]):
                evidence_counts[(backbone, category)] += 1
            triples.append((e2, e6, e7))

    for backbone in BACKBONES:
        for category, name, answer_n, evidence_n in CATEGORIES:
            _require(category_counts[(backbone, category)] == answer_n, f"RQ3 category denominator differs: {backbone}/{name}")
            _require(evidence_counts[(backbone, category)] == evidence_n, f"RQ3 evidence denominator differs: {backbone}/{name}")
    _require(len(triples) == 120, "RQ3 paired triple count differs")
    return triples


def _strict_correct(row: Mapping[str, Any]) -> bool:
    value = float(row["strict_score"])
    _require(value in {0.0, 1.0}, "RQ3 Strict score is not binary")
    return value == 1.0


def _parent_profile(e2: Mapping[str, Any], e6: Mapping[str, Any]) -> str:
    left, right = _strict_correct(e2), _strict_correct(e6)
    if left and right:
        return "both_correct"
    if left:
        return "e2_only_correct"
    if right:
        return "e6_only_correct"
    return "neither_correct"


def _fusion_outcome(e2: Mapping[str, Any], e6: Mapping[str, Any], e7: Mapping[str, Any]) -> str:
    parent_correct = _strict_correct(e2) or _strict_correct(e6)
    fused_correct = _strict_correct(e7)
    if fused_correct:
        return "preserve" if parent_correct else "repair"
    return "harm" if parent_correct else "unresolved"


def _question_diagnostics(
    triples: Sequence[tuple[Mapping[str, Any], Mapping[str, Any], Mapping[str, Any]]]
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for e2, e6, e7 in triples:
        raw_ids = set(str(value) for value in e2["retrieved_dia_ids"])
        curated_ids = set(str(value) for value in e6["retrieved_dia_ids"])
        fused_ids = set(str(value) for value in e7["retrieved_dia_ids"])
        union = raw_ids | curated_ids
        intersection = raw_ids & curated_ids
        _require(fused_ids == union, "RQ3 fused source IDs do not equal the parent union")
        gold = set(str(value) for value in e2["gold_dia_ids"])
        shared_gold = gold & raw_ids & curated_ids
        e2_only_gold = (gold & raw_ids) - curated_ids
        e6_only_gold = (gold & curated_ids) - raw_ids
        missing_gold = gold - union
        _require(
            len(shared_gold) + len(e2_only_gold) + len(e6_only_gold) + len(missing_gold) == len(gold),
            "RQ3 annotated-source partition differs",
        )
        eligible = bool(e2["evidence_eligible"])
        _require(eligible == bool(gold), "RQ3 evidence eligibility differs from gold IDs")
        union_recall = (len(gold & union) / len(gold)) if eligible else None
        e2_marginal_recall = (len(e2_only_gold) / len(gold)) if eligible else None
        e6_marginal_recall = (len(e6_only_gold) / len(gold)) if eligible else None
        if eligible:
            _require(_close(float(e7["evidence_recall"]), float(union_recall)), "RQ3 E7 Evidence Recall differs from union recall")
        else:
            _require(e7["evidence_recall"] is None, "RQ3 ineligible Evidence Recall is not null")

        outcome = _fusion_outcome(e2, e6, e7)
        profile = _parent_profile(e2, e6)
        body: dict[str, Any] = {
            "protocol_version": STAGE_RQ3_PROTOCOL_VERSION,
            "backbone_order": BACKBONES.index(str(e2["backbone_id"])) + 1,
            "backbone_id": e2["backbone_id"],
            "answer_set_id": e2["answer_set_id"],
            "global_position": int(e2["global_position"]),
            "question_id": e2["question_id"],
            "question_sha256": e2["question_sha256"],
            "category_order": CATEGORY_ORDER[int(e2["category"])],
            "category": int(e2["category"]),
            "category_name": e2["category_name"],
            "evidence_eligible": eligible,
            "parent_profile": profile,
            "fusion_outcome": outcome,
            "rq5_review_candidate": outcome in {"repair", "harm"},
            "rq5_candidate_type": (
                "fusion_success" if outcome == "repair" else "possible_interference" if outcome == "harm" else "not_prioritised"
            ),
        }
        for condition, source in (("e2", e2), ("e6", e6), ("e7", e7)):
            body[f"{condition}_judge_label"] = source["judge_label"]
            body[f"{condition}_strict_score"] = float(source["strict_score"])
            body[f"{condition}_soft_semantic_score"] = float(source["soft_semantic_score"])
            body[f"{condition}_token_precision"] = float(source["token_precision"])
            body[f"{condition}_token_recall"] = float(source["token_recall"])
            body[f"{condition}_token_f1"] = float(source["token_f1"])
            body[f"{condition}_evidence_recall"] = source["evidence_recall"]
        body.update(
            {
                "e2_source_id_count": len(raw_ids),
                "e6_source_id_count": len(curated_ids),
                "shared_source_id_count": len(intersection),
                "union_source_id_count": len(union),
                "e2_only_source_id_count": len(raw_ids - curated_ids),
                "e6_only_source_id_count": len(curated_ids - raw_ids),
                # If both paths return no source ID, their sets are identical.
                # Use the standard empty-set Jaccard convention of 1.0 and
                # retain the zero union count so the case remains explicit.
                "source_id_jaccard": len(intersection) / len(union) if union else 1.0,
                "gold_source_id_count": len(gold),
                "shared_gold_source_id_count": len(shared_gold),
                "e2_only_gold_source_id_count": len(e2_only_gold),
                "e6_only_gold_source_id_count": len(e6_only_gold),
                "missing_gold_source_id_count": len(missing_gold),
                "union_gold_source_id_count": len(gold & union),
                "union_evidence_recall": union_recall,
                "e2_marginal_evidence_recall": e2_marginal_recall,
                "e6_marginal_evidence_recall": e6_marginal_recall,
                "evidence_contribution_class": (
                    "not_applicable_no_gold_annotation"
                    if not eligible
                    else "bidirectional_complementarity"
                    if e2_only_gold and e6_only_gold
                    else "e2_additive_only"
                    if e2_only_gold
                    else "e6_additive_only"
                    if e6_only_gold
                    else "no_marginal_annotated_coverage"
                ),
            }
        )
        rows.append({"result_id": _artifact_id("rq3-question-", body), **body})
    return rows


def _effect_row(
    *, backbone: str, parent: str, rows: Sequence[Mapping[str, Any]], category: int | None,
) -> dict[str, Any]:
    answer_n = len(rows)
    evidence_rows = [row for row in rows if row["evidence_eligible"]]
    body: dict[str, Any] = {
        "protocol_version": STAGE_RQ3_PROTOCOL_VERSION,
        "backbone_order": BACKBONES.index(backbone) + 1,
        "backbone_id": backbone,
        "comparison_order": PARENTS.index(parent) + 1,
        "comparison_id": "fusion_vs_raw_e7_minus_e2" if parent == "E2" else "fusion_vs_curated_e7_minus_e6",
        "baseline_condition": parent,
        "target_condition": "E7",
        "difference_direction": "e7_minus_parent",
        "answer_denominator": answer_n,
        "evidence_denominator": len(evidence_rows),
    }
    if category is not None:
        category_spec = next(item for item in CATEGORIES if item[0] == category)
        body.update(
            {
                "category_order": CATEGORY_ORDER[category],
                "category": category,
                "category_name": category_spec[1],
                "exploratory_category_analysis": True,
            }
        )
    parent_prefix = parent.lower()
    for published, source_field in ANSWER_METRICS:
        baseline = _mean([float(row[f"{parent_prefix}_{source_field}"]) for row in rows])
        target = _mean([float(row[f"e7_{source_field}"]) for row in rows])
        paired = _mean([float(row[f"e7_{source_field}"]) - float(row[f"{parent_prefix}_{source_field}"]) for row in rows])
        _require(_close(paired, target - baseline), f"RQ3 paired effect algebra differs: {backbone}/{parent}/{published}")
        body[f"parent_{published}"] = baseline
        body[f"e7_{published}"] = target
        body[f"delta_{published}"] = paired
    baseline_er = _mean([float(row[f"{parent_prefix}_evidence_recall"]) for row in evidence_rows])
    target_er = _mean([float(row["e7_evidence_recall"]) for row in evidence_rows])
    paired_er = _mean(
        [float(row["e7_evidence_recall"]) - float(row[f"{parent_prefix}_evidence_recall"]) for row in evidence_rows]
    )
    _require(_close(paired_er, target_er - baseline_er), "RQ3 Evidence Recall algebra differs")
    body.update(
        {
            "parent_evidence_recall": baseline_er,
            "e7_evidence_recall": target_er,
            "delta_evidence_recall": paired_er,
            "descriptive_only": True,
        }
    )
    prefix = "rq3-category-effect-" if category is not None else "rq3-parent-effect-"
    return {"result_id": _artifact_id(prefix, body), **body}


def _parent_effects(diagnostics: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for backbone in BACKBONES:
        rows = [row for row in diagnostics if row["backbone_id"] == backbone]
        for parent in PARENTS:
            output.append(_effect_row(backbone=backbone, parent=parent, rows=rows, category=None))
    return output


def _category_effects(diagnostics: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for backbone in BACKBONES:
        for category, _, answer_n, evidence_n in CATEGORIES:
            rows = [row for row in diagnostics if row["backbone_id"] == backbone and row["category"] == category]
            _require(len(rows) == answer_n, "RQ3 category answer denominator differs")
            _require(sum(bool(row["evidence_eligible"]) for row in rows) == evidence_n, "RQ3 category evidence denominator differs")
            for parent in PARENTS:
                output.append(_effect_row(backbone=backbone, parent=parent, rows=rows, category=category))
    return output


def _judge_transitions(diagnostics: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for backbone in BACKBONES:
        relevant = [row for row in diagnostics if row["backbone_id"] == backbone]
        for parent in PARENTS:
            prefix = parent.lower()
            counts = Counter((row[f"{prefix}_judge_label"], row["e7_judge_label"]) for row in relevant)
            _require(sum(counts.values()) == QUESTION_COUNT, "RQ3 judge-transition total differs")
            for source in JUDGE_LABELS:
                for target in JUDGE_LABELS:
                    count = counts[(source, target)]
                    direction = (
                        "improved" if JUDGE_ORDINAL[target] > JUDGE_ORDINAL[source]
                        else "worsened" if JUDGE_ORDINAL[target] < JUDGE_ORDINAL[source]
                        else "unchanged"
                    )
                    body = {
                        "protocol_version": STAGE_RQ3_PROTOCOL_VERSION,
                        "backbone_order": BACKBONES.index(backbone) + 1,
                        "backbone_id": backbone,
                        "comparison_order": PARENTS.index(parent) + 1,
                        "comparison_id": "fusion_vs_raw_e7_minus_e2" if parent == "E2" else "fusion_vs_curated_e7_minus_e6",
                        "baseline_condition": parent,
                        "target_condition": "E7",
                        "parent_label_order": JUDGE_LABELS.index(source) + 1,
                        "parent_label": source,
                        "e7_label_order": JUDGE_LABELS.index(target) + 1,
                        "e7_label": target,
                        "transition_direction": direction,
                        "denominator": QUESTION_COUNT,
                        "count": count,
                        "proportion": count / QUESTION_COUNT,
                    }
                    output.append({"result_id": _artifact_id("rq3-transition-", body), **body})
    return output


def _fusion_outcome_rows(diagnostics: Sequence[Mapping[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    overall: list[dict[str, Any]] = []
    summaries: list[dict[str, Any]] = []
    by_category: list[dict[str, Any]] = []
    for backbone in BACKBONES:
        relevant = [row for row in diagnostics if row["backbone_id"] == backbone]
        counts = Counter(str(row["fusion_outcome"]) for row in relevant)
        _require(sum(counts.values()) == QUESTION_COUNT, "RQ3 fusion outcomes do not partition Main-60")
        for state in OUTCOME_STATES:
            body = {
                "protocol_version": STAGE_RQ3_PROTOCOL_VERSION,
                "backbone_order": BACKBONES.index(backbone) + 1,
                "backbone_id": backbone,
                "outcome_order": OUTCOME_STATES.index(state) + 1,
                "fusion_outcome": state,
                "denominator": QUESTION_COUNT,
                "count": counts[state],
                "proportion": counts[state] / QUESTION_COUNT,
                "outcome_definition_metric": "strict_accuracy",
            }
            overall.append({"result_id": _artifact_id("rq3-outcome-", body), **body})

        parent_oracle = counts["preserve"] + counts["harm"]
        both_wrong = counts["repair"] + counts["unresolved"]
        e7_correct = counts["preserve"] + counts["repair"]
        body = {
            "protocol_version": STAGE_RQ3_PROTOCOL_VERSION,
            "backbone_order": BACKBONES.index(backbone) + 1,
            "backbone_id": backbone,
            "question_denominator": QUESTION_COUNT,
            "parent_oracle_correct_count": parent_oracle,
            "both_parents_wrong_count": both_wrong,
            "e7_correct_count": e7_correct,
            "repair_count": counts["repair"],
            "preserve_count": counts["preserve"],
            "harm_count": counts["harm"],
            "unresolved_count": counts["unresolved"],
            "conditional_repair_rate": counts["repair"] / both_wrong,
            "conditional_harm_rate": counts["harm"] / parent_oracle,
            "net_vs_parent_oracle_count": counts["repair"] - counts["harm"],
            "net_vs_parent_oracle_rate": (counts["repair"] - counts["harm"]) / QUESTION_COUNT,
            "outcome_definition_metric": "strict_accuracy",
        }
        summaries.append({"result_id": _artifact_id("rq3-outcome-summary-", body), **body})

        for category, name, answer_n, _ in CATEGORIES:
            category_rows = [row for row in relevant if row["category"] == category]
            category_counts = Counter(str(row["fusion_outcome"]) for row in category_rows)
            _require(sum(category_counts.values()) == answer_n, "RQ3 category outcome partition differs")
            for state in OUTCOME_STATES:
                body = {
                    "protocol_version": STAGE_RQ3_PROTOCOL_VERSION,
                    "backbone_order": BACKBONES.index(backbone) + 1,
                    "backbone_id": backbone,
                    "category_order": CATEGORY_ORDER[category],
                    "category": category,
                    "category_name": name,
                    "outcome_order": OUTCOME_STATES.index(state) + 1,
                    "fusion_outcome": state,
                    "denominator": answer_n,
                    "count": category_counts[state],
                    "proportion": category_counts[state] / answer_n,
                    "exploratory_category_analysis": True,
                }
                by_category.append({"result_id": _artifact_id("rq3-category-outcome-", body), **body})
    return overall, summaries, by_category


def _parent_complementarity(diagnostics: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for backbone in BACKBONES:
        relevant = [row for row in diagnostics if row["backbone_id"] == backbone]
        counts = Counter(str(row["parent_profile"]) for row in relevant)
        _require(sum(counts.values()) == QUESTION_COUNT, "RQ3 parent profiles do not partition Main-60")
        for profile in PARENT_PROFILES:
            body = {
                "protocol_version": STAGE_RQ3_PROTOCOL_VERSION,
                "backbone_order": BACKBONES.index(backbone) + 1,
                "backbone_id": backbone,
                "profile_order": PARENT_PROFILES.index(profile) + 1,
                "parent_profile": profile,
                "denominator": QUESTION_COUNT,
                "count": counts[profile],
                "proportion": counts[profile] / QUESTION_COUNT,
                "definition_metric": "strict_accuracy",
            }
            output.append({"result_id": _artifact_id("rq3-parent-profile-", body), **body})
    return output


def _evidence_overlap(diagnostics: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for backbone in BACKBONES:
        all_rows = [row for row in diagnostics if row["backbone_id"] == backbone]
        eligible = [row for row in all_rows if row["evidence_eligible"]]
        _require(len(eligible) == EVIDENCE_QUESTION_COUNT, "RQ3 evidence-eligible denominator differs")
        contribution = Counter(str(row["evidence_contribution_class"]) for row in eligible)
        gold_total = sum(int(row["gold_source_id_count"]) for row in eligible)
        shared_gold = sum(int(row["shared_gold_source_id_count"]) for row in eligible)
        e2_only_gold = sum(int(row["e2_only_gold_source_id_count"]) for row in eligible)
        e6_only_gold = sum(int(row["e6_only_gold_source_id_count"]) for row in eligible)
        missing_gold = sum(int(row["missing_gold_source_id_count"]) for row in eligible)
        _require(shared_gold + e2_only_gold + e6_only_gold + missing_gold == gold_total, "RQ3 gold-source totals differ")
        body = {
            "protocol_version": STAGE_RQ3_PROTOCOL_VERSION,
            "backbone_order": BACKBONES.index(backbone) + 1,
            "backbone_id": backbone,
            "question_denominator": QUESTION_COUNT,
            "evidence_denominator": EVIDENCE_QUESTION_COUNT,
            "mean_e2_source_id_count": _mean([row["e2_source_id_count"] for row in all_rows]),
            "mean_e6_source_id_count": _mean([row["e6_source_id_count"] for row in all_rows]),
            "mean_shared_source_id_count": _mean([row["shared_source_id_count"] for row in all_rows]),
            "mean_union_source_id_count": _mean([row["union_source_id_count"] for row in all_rows]),
            "mean_source_id_jaccard": _mean([row["source_id_jaccard"] for row in all_rows]),
            "mean_e2_evidence_recall": _mean([row["e2_evidence_recall"] for row in eligible]),
            "mean_e6_evidence_recall": _mean([row["e6_evidence_recall"] for row in eligible]),
            "mean_union_evidence_recall": _mean([row["union_evidence_recall"] for row in eligible]),
            "mean_e2_marginal_evidence_recall": _mean([row["e2_marginal_evidence_recall"] for row in eligible]),
            "mean_e6_marginal_evidence_recall": _mean([row["e6_marginal_evidence_recall"] for row in eligible]),
            "gold_source_occurrences": gold_total,
            "shared_gold_source_occurrences": shared_gold,
            "e2_only_gold_source_occurrences": e2_only_gold,
            "e6_only_gold_source_occurrences": e6_only_gold,
            "missing_gold_source_occurrences": missing_gold,
            "union_complete_question_count": sum(_close(float(row["union_evidence_recall"]), 1.0) for row in eligible),
            "e2_unique_gold_question_count": sum(int(row["e2_only_gold_source_id_count"]) > 0 for row in eligible),
            "e6_unique_gold_question_count": sum(int(row["e6_only_gold_source_id_count"]) > 0 for row in eligible),
            "either_unique_gold_question_count": sum(
                int(row["e2_only_gold_source_id_count"]) > 0 or int(row["e6_only_gold_source_id_count"]) > 0 for row in eligible
            ),
            "both_unique_gold_question_count": sum(
                int(row["e2_only_gold_source_id_count"]) > 0 and int(row["e6_only_gold_source_id_count"]) > 0 for row in eligible
            ),
            "bidirectional_complementarity_count": contribution["bidirectional_complementarity"],
            "e2_additive_only_count": contribution["e2_additive_only"],
            "e6_additive_only_count": contribution["e6_additive_only"],
            "no_marginal_annotated_coverage_count": contribution["no_marginal_annotated_coverage"],
            "overlap_unit": "retrieved_dialogue_source_id",
            "annotated_evidence_note": "gold IDs are annotated source locations, not full reasoning chains",
        }
        output.append({"result_id": _artifact_id("rq3-overlap-", body), **body})
    return output


def _figure_rows(diagnostics: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for backbone in BACKBONES:
        relevant = [row for row in diagnostics if row["backbone_id"] == backbone]
        counts = Counter((str(row["parent_profile"]), int(float(row["e7_strict_score"]))) for row in relevant)
        _require(sum(counts.values()) == QUESTION_COUNT, "RQ3 Figure 5.6 input total differs")
        for profile in PARENT_PROFILES:
            for fused in (0, 1):
                count = counts[(profile, fused)]
                parent_correct = profile != "neither_correct"
                outcome = (
                    "preserve" if parent_correct and fused else
                    "harm" if parent_correct else
                    "repair" if fused else "unresolved"
                )
                body = {
                    "protocol_version": STAGE_RQ3_PROTOCOL_VERSION,
                    "backbone_order": BACKBONES.index(backbone) + 1,
                    "backbone_id": backbone,
                    "parent_profile_order": PARENT_PROFILES.index(profile) + 1,
                    "parent_profile": profile,
                    "e7_strict_correct": bool(fused),
                    "fusion_outcome": outcome,
                    "denominator": QUESTION_COUNT,
                    "count": count,
                    "proportion": count / QUESTION_COUNT,
                }
                output.append({"result_id": _artifact_id("rq3-figure-5-6-", body), **body})
    return output


def _table_rows(parent_effects: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    fields = (
        "protocol_version",
        "backbone_order",
        "backbone_id",
        "comparison_order",
        "comparison_id",
        "baseline_condition",
        "target_condition",
        "answer_denominator",
        "evidence_denominator",
        "parent_token_f1",
        "e7_token_f1",
        "delta_token_f1",
        "parent_strict_accuracy",
        "e7_strict_accuracy",
        "delta_strict_accuracy",
        "parent_soft_semantic_score",
        "e7_soft_semantic_score",
        "delta_soft_semantic_score",
        "parent_evidence_recall",
        "e7_evidence_recall",
        "delta_evidence_recall",
        "delta_token_precision",
        "delta_token_recall",
        "descriptive_only",
    )
    return [{field: row[field] for field in fields} for row in parent_effects]


def _review_candidates(diagnostics: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    fields = (
        "protocol_version",
        "backbone_order",
        "backbone_id",
        "global_position",
        "question_id",
        "question_sha256",
        "category_order",
        "category",
        "category_name",
        "evidence_eligible",
        "parent_profile",
        "fusion_outcome",
        "rq5_candidate_type",
        "e2_judge_label",
        "e6_judge_label",
        "e7_judge_label",
        "e2_token_f1",
        "e6_token_f1",
        "e7_token_f1",
        "e2_soft_semantic_score",
        "e6_soft_semantic_score",
        "e7_soft_semantic_score",
        "source_id_jaccard",
        "e2_only_gold_source_id_count",
        "e6_only_gold_source_id_count",
        "union_evidence_recall",
        "evidence_contribution_class",
    )
    selected = [row for row in diagnostics if row["rq5_review_candidate"]]
    selected.sort(
        key=lambda row: (
            int(row["backbone_order"]),
            0 if row["fusion_outcome"] == "repair" else 1,
            int(row["global_position"]),
        )
    )
    output = []
    for row in selected:
        body = {field: row[field] for field in fields}
        body["review_status"] = "deferred_to_rq5"
        output.append({"result_id": _artifact_id("rq3-rq5-candidate-", body), **body})
    return output


def _compute_rq3(
    *, repo_root: Path, stage_a_dir: Path,
) -> tuple[dict[str, list[dict[str, Any]]], dict[str, Any], dict[str, Any]]:
    provenance = _validate_frozen_input(repo_root=repo_root, stage_a_dir=stage_a_dir)
    source_rows = _read_jsonl(stage_a_dir / "e1-e7-main.jsonl")
    triples = _validate_source_rows(source_rows)
    diagnostics = _question_diagnostics(triples)
    parent_effects = _parent_effects(diagnostics)
    category_effects = _category_effects(diagnostics)
    transitions = _judge_transitions(diagnostics)
    outcomes, outcome_summary, outcomes_by_category = _fusion_outcome_rows(diagnostics)
    complementarity = _parent_complementarity(diagnostics)
    overlap = _evidence_overlap(diagnostics)
    candidates = _review_candidates(diagnostics)
    tables = {
        "parent-effects": parent_effects,
        "category-effects": category_effects,
        "judge-transitions": transitions,
        "fusion-outcomes": outcomes,
        "fusion-outcome-summary": outcome_summary,
        "fusion-outcomes-by-category": outcomes_by_category,
        "parent-complementarity": complementarity,
        "evidence-source-overlap": overlap,
        "question-diagnostics": diagnostics,
        "rq5-candidate-cases": candidates,
        "table-5-14-inputs": _table_rows(parent_effects),
        "figure-5-6-inputs": _figure_rows(diagnostics),
    }
    counts = {name: len(rows) for name, rows in tables.items()}
    expected_counts = {
        "parent-effects": 4,
        "category-effects": 16,
        "judge-transitions": 36,
        "fusion-outcomes": 8,
        "fusion-outcome-summary": 2,
        "fusion-outcomes-by-category": 32,
        "parent-complementarity": 8,
        "evidence-source-overlap": 2,
        "question-diagnostics": 120,
        "rq5-candidate-cases": 12,
        "table-5-14-inputs": 4,
        "figure-5-6-inputs": 16,
    }
    checks = {
        "stage_a_rows_840": len(source_rows) == 840,
        "rq3_source_rows_360": len(triples) * 3 == 360,
        "paired_triples_120": len(triples) == 120,
        "table_row_counts_exact": counts == expected_counts,
        "diagnostic_rows_text_free": all(FORBIDDEN_FIELDS.isdisjoint(row) for row in diagnostics),
        "outcomes_partition_each_backbone": all(
            sum(int(row["count"]) for row in outcomes if row["backbone_id"] == backbone) == QUESTION_COUNT
            for backbone in BACKBONES
        ),
        "category_outcomes_partition": all(
            sum(
                int(row["count"])
                for row in outcomes_by_category
                if row["backbone_id"] == backbone and row["category"] == category
            ) == answer_n
            for backbone in BACKBONES
            for category, _, answer_n, _ in CATEGORIES
        ),
        "transition_matrices_sum_60": all(
            sum(
                int(row["count"])
                for row in transitions
                if row["backbone_id"] == backbone and row["baseline_condition"] == parent
            ) == QUESTION_COUNT
            for backbone in BACKBONES
            for parent in PARENTS
        ),
        "fusion_contract_exact": FUSION_CONTRACT_SHA256 == EXPECTED_FUSION_CONTRACT_SHA256,
        "no_full_context": all(
            "full context" not in str(value).lower()
            for table in tables.values()
            for row in table
            for value in row.values()
        ),
    }
    _require(all(checks.values()), "RQ3 table audit failed")
    return tables, provenance, {"checks": checks, "row_counts": counts}


def _value_type(value: Any) -> str:
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, float):
        return "number"
    if value is None:
        return "null"
    return "string"


def _field_schema(tables: Mapping[str, Sequence[Mapping[str, Any]]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for name, rows in tables.items():
        _require(bool(rows), f"RQ3 table is empty: {name}")
        fields = list(rows[0])
        _require(all(list(row) == fields for row in rows), f"RQ3 table schema differs: {name}")
        result[name] = {
            "row_count": len(rows),
            "fields": [
                {"name": field, "types": sorted({_value_type(row[field]) for row in rows})}
                for field in fields
            ],
        }
    return {
        "schema_version": 1,
        "protocol_version": STAGE_RQ3_PROTOCOL_VERSION,
        "tables": result,
        "effect_direction": "E7 minus parent",
        "answer_denominator": QUESTION_COUNT,
        "evidence_denominator": EVIDENCE_QUESTION_COUNT,
        "fusion_outcome_basis": "Strict Accuracy only",
        "overlap_unit": "retrieved dialogue source ID, not evidence text",
        "inference_scope": "descriptive paired analysis; no bootstrap or significance test",
    }


def _readme() -> str:
    return """# Chapter 5 RQ3: dual-source fusion

This directory is the audited, offline input for Section 5.4. It compares E7
with each of its two parent paths, E2 and E6, on the same unified Main-60
questions under both Qwen and DeepSeek.

`parent-effects` and `table-5-14-inputs` report paired E7-minus-parent answer
and Evidence Recall effects. `category-effects` reports the same contrasts by
the four unified question categories and is exploratory. `judge-transitions`
retains incorrect/partial/correct changes rather than collapsing all semantic
movement into Strict Accuracy.

`fusion-outcomes` classifies each question by Strict Accuracy as Repair,
Preserve, Harm, or Unresolved. Preserve means that at least one correct parent
remained correct; it does not mean that E7 exceeded both parents.
`figure-5-6-inputs` preserves the four parent-correctness profiles needed for
the flow diagram. `question-diagnostics` and `rq5-candidate-cases` contain
identifiers and numeric diagnostics only; causal review is deferred to RQ5.

`evidence-source-overlap` uses retrieved dialogue source IDs. It does not
measure evidence-text similarity and cannot by itself identify semantic
conflict. Gold IDs are annotated source locations, not complete reasoning
chains. Harm rows are therefore possible-interference candidates, not proven
conflict cases.

E7 performs no new search action. Its recorded retrieval calls and tokens are
the inherited sum of the E2 and E6 upstream retrievals, followed by one shared
Answerer call. This artifact contains no question, answer, evidence, rationale,
or secret text. It made no API or network call, reran no model, and computed no
new bootstrap interval or significance test. Cost ranking belongs to RQ6;
failure-stage attribution belongs to RQ5; Full Context belongs to RQ4.
"""


def _source_manifest(
    *, repo_root: Path, stage_a_dir: Path, provenance: Mapping[str, Any],
) -> dict[str, Any]:
    body = {
        "schema_version": 1,
        "protocol_version": STAGE_RQ3_PROTOCOL_VERSION,
        "scope": "paired E7 dual-source-fusion analysis on unified Main-60",
        "stage_a_directory": _relative(repo_root, stage_a_dir),
        **dict(provenance),
        "source_row_count": 360,
        "paired_question_triples": 120,
        "backbones": list(BACKBONES),
        "conditions": list(CONDITIONS),
        "comparisons": ["E7-E2", "E7-E6"],
        "question_denominator": QUESTION_COUNT,
        "evidence_denominator": EVIDENCE_QUESTION_COUNT,
        "backbone_identities": {
            "qwen": {"answer_set_id": "model1-qwen-main60", "requested_model": "coding", "served_model": "qwen3.8:27b"},
            "deepseek": {"answer_set_id": "model2-deepseek-main60", "requested_model": "x-test-2", "served_model": "deepseek-v4.1-flash"},
        },
        "judge_identity": {"requested_model": "x-test-1", "served_model": "glm-5.3-flash"},
        "fusion_contract": {
            "parents": ["E2", "E6"],
            "new_search_actions": 0,
            "per_parent_budget_characters": 16000,
            "total_budget_characters": 32000,
            "retrieval_accounting": "inherited sum of parent retrieval calls and tokens",
            "shared_answerer_calls_per_question": 1,
        },
        "strict_outcome_definitions": {
            "repair": "both parents incorrect and E7 correct",
            "preserve": "at least one parent correct and E7 correct",
            "harm": "at least one parent correct and E7 incorrect",
            "unresolved": "both parents incorrect and E7 incorrect",
        },
        "source_overlap_unit": "retrieved_dialogue_source_id",
        "automatic_semantic_conflict_inference": False,
        "no_api_calls": True,
        "no_network_calls": True,
        "formal_source_mutation": False,
        "new_bootstrap_computed": False,
        "statistical_inference_computed": False,
        "cost_ranking_computed": False,
        "causal_stage_attribution_computed": False,
        "full_context_computed": False,
    }
    return {"source_manifest_id": "rq3-sources-" + sha256_bytes(canonical_json_bytes(body)), **body}


def _artifact_payloads(
    tables: Mapping[str, Sequence[Mapping[str, Any]]], source_manifest: Mapping[str, Any],
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
    *, source_manifest: Mapping[str, Any], provenance: Mapping[str, Any],
    table_audit: Mapping[str, Any], output_hashes: Mapping[str, str],
) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "protocol_version": STAGE_RQ3_PROTOCOL_VERSION,
        "status": "passed",
        "scope": "paired E7 dual-source-fusion analysis",
        "no_api_calls": True,
        "no_network_calls": True,
        "formal_source_mutation": False,
        "new_bootstrap_computed": False,
        "statistical_inference_computed": False,
        "cost_ranking_computed": False,
        "causal_stage_attribution_computed": False,
        "full_context_computed": False,
        "source_manifest_id": source_manifest["source_manifest_id"],
        **dict(provenance),
        "table_audit": dict(table_audit),
        "output_sha256": dict(output_hashes),
    }


def _marker(audit: Mapping[str, Any], audit_sha256: str) -> dict[str, Any]:
    counts = audit["table_audit"]["row_counts"]
    return {
        "status": "passed",
        "protocol_version": STAGE_RQ3_PROTOCOL_VERSION,
        "audit_id": audit["audit_id"],
        "audit_sha256": audit_sha256,
        "source_rows": 360,
        "paired_question_triples": 120,
        "question_denominator": QUESTION_COUNT,
        "evidence_denominator": EVIDENCE_QUESTION_COUNT,
        "parent_effect_rows": counts["parent-effects"],
        "category_effect_rows": counts["category-effects"],
        "rq5_candidate_rows": counts["rq5-candidate-cases"],
        "no_api_calls": True,
        "no_network_calls": True,
    }


def build_rq3(
    *, repo_root: Path, stage_a_dir: Path, output_dir: Path,
) -> dict[str, Any]:
    root = repo_root.resolve()
    source = stage_a_dir.resolve()
    destination = output_dir.resolve()
    _require(not destination.exists() and not destination.is_symlink(), "RQ3 output already exists")
    try:
        destination.relative_to(source)
    except ValueError:
        pass
    else:
        _require(False, "RQ3 output may not be published inside frozen Stage A")

    tables, provenance, table_audit = _compute_rq3(repo_root=root, stage_a_dir=source)
    manifest = _source_manifest(repo_root=root, stage_a_dir=source, provenance=provenance)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=f".{destination.name}.in-progress-", dir=destination.parent))
    try:
        payloads = _artifact_payloads(tables, manifest)
        for name, payload in payloads.items():
            _write(temporary / name, payload)
        hashes = {name: _sha256_file(temporary / name) for name in sorted(payloads)}
        body = _audit_body(source_manifest=manifest, provenance=provenance, table_audit=table_audit, output_hashes=hashes)
        audit = {"audit_id": "rq3-audit-" + sha256_bytes(canonical_json_bytes(body)), **body}
        _write(temporary / "audit.json", canonical_json_bytes(audit) + b"\n")
        _write(
            temporary / "RQ3.PASSED",
            canonical_json_bytes(_marker(audit, _sha256_file(temporary / "audit.json"))) + b"\n",
        )
        result = audit_rq3_output(repo_root=root, stage_a_dir=source, output_dir=temporary)
        _require(result["status"] == "passed", "RQ3 pre-publication audit failed")
        _require(not destination.exists(), "RQ3 output appeared during build")
        os.rename(temporary, destination)
        descriptor = os.open(destination.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
    except Exception:
        shutil.rmtree(temporary, ignore_errors=True)
        raise
    return audit_rq3_output(repo_root=root, stage_a_dir=source, output_dir=destination)


def audit_rq3_output(
    *, repo_root: Path, stage_a_dir: Path, output_dir: Path,
) -> dict[str, Any]:
    root = repo_root.resolve()
    source = stage_a_dir.resolve()
    output = output_dir.resolve()
    _require(output.is_dir() and not output.is_symlink(), "RQ3 output directory is unsafe")
    tables, provenance, table_audit = _compute_rq3(repo_root=root, stage_a_dir=source)
    manifest = _source_manifest(repo_root=root, stage_a_dir=source, provenance=provenance)
    payloads = _artifact_payloads(tables, manifest)
    hashes = {name: hashlib.sha256(payload).hexdigest() for name, payload in sorted(payloads.items())}
    body = _audit_body(source_manifest=manifest, provenance=provenance, table_audit=table_audit, output_hashes=hashes)
    expected_audit = {"audit_id": "rq3-audit-" + sha256_bytes(canonical_json_bytes(body)), **body}
    audit_payload = canonical_json_bytes(expected_audit) + b"\n"
    marker_payload = canonical_json_bytes(_marker(expected_audit, hashlib.sha256(audit_payload).hexdigest())) + b"\n"

    expected_names = set(payloads) | {"audit.json", "RQ3.PASSED"}
    entries = list(output.iterdir())
    _require(all(entry.is_file() and not entry.is_symlink() for entry in entries), "RQ3 output contains unsafe entry")
    _require({entry.name for entry in entries} == expected_names, "RQ3 output file set differs")
    for name, payload in payloads.items():
        _require((output / name).read_bytes() == payload, f"RQ3 artifact bytes differ: {name}")
    _require((output / "audit.json").read_bytes() == audit_payload, "RQ3 audit bytes differ")
    _require((output / "RQ3.PASSED").read_bytes() == marker_payload, "RQ3 marker bytes differ")
    return {
        "status": "passed",
        "protocol_version": STAGE_RQ3_PROTOCOL_VERSION,
        "audit_id": expected_audit["audit_id"],
        "source_rows": 360,
        "paired_question_triples": 120,
        "question_denominator": QUESTION_COUNT,
        "evidence_denominator": EVIDENCE_QUESTION_COUNT,
        "rq5_candidate_rows": table_audit["row_counts"]["rq5-candidate-cases"],
        "output_dir": str(output),
        "no_api_calls": True,
        "no_network_calls": True,
    }


build_chapter5_rq3 = build_rq3
audit_chapter5_rq3_output = audit_rq3_output


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build or audit Chapter 5 RQ3 artifacts")
    parser.add_argument("command", choices=("build", "audit"))
    parser.add_argument("--repo-root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--stage-a-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    return parser


def main(argv: list[str] | None = None) -> None:
    args = _parser().parse_args(argv)
    kwargs = {
        "repo_root": args.repo_root,
        "stage_a_dir": args.stage_a_dir,
        "output_dir": args.output_dir,
    }
    result = build_rq3(**kwargs) if args.command == "build" else audit_rq3_output(**kwargs)
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
