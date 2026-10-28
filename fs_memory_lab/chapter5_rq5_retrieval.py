"""Offline R1--R3 retrieval audit for Chapter 5, Section 5.6.3.

The builder reconstructs every independent E1--E6 retrieval path from the
frozen run records.  R2 and R3 searches are replayed against the frozen local
indexes with the recorded action arguments and seen-state.  Published rows
contain identifiers, states, counts, ranks, hashes, and scores only; question,
answer, evidence, prompt, query, and rationale text are never published.

Gold-source annotations are used as a fixed diagnostic coordinate system.
Missing an annotated source is not, by itself, a causal retrieval label: an
unannotated equivalent source may exist.  Likewise, reaching a native cap is
a process state, not an automatic failure.  This stage updates only the
retriever-reach and model-observation fields of the RQ5 state register; final
input, evidence-retention, Answerer, fusion, long-context, and evaluation
states remain for Sections 5.6.4--5.6.5.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import shutil
import statistics
import tempfile
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from .chapter5_stage_b import (
    _csv_payload,
    _jsonl_payload,
    _read_json,
    _read_jsonl,
    _require,
    _sha256_file,
    _write,
)
from .evidence import canonical_json_bytes, sha256_bytes
from .r1_inputs import LoadedR1Store, load_r1_store
from .r2_index import R2RawIndex, R2SearchResult
from .r2_inputs import build_r2_raw_corpus
from .r3_index import R3CuratedIndex, R3SearchResult
from .r3_inputs import R3CuratedCorpus, load_r3_corpus


PROTOCOL_VERSION = "chapter5-main60-rq5-retrieval-audit-v1"
SELECTIVE_CONDITIONS = ("E1", "E2", "E3", "E4", "E5", "E6")
STORE_BY_CONDITION = {"E1": "S1", "E2": "S1", "E3": "S2", "E4": "S2", "E5": "S3", "E6": "S3"}
RETRIEVER_BY_CONDITION = {"E1": "R1", "E2": "R2", "E3": "R1", "E4": "R2", "E5": "R1", "E6": "R3"}
CONDITION_ORDER = {condition: index for index, condition in enumerate(SELECTIVE_CONDITIONS, 1)}
BACKBONE_ORDER = {"qwen": 1, "deepseek": 2}
EXPECTED_PATHS = 720
EXPECTED_ELIGIBLE_PATHS = 696
EXPECTED_ERROR_PATHS = 205
EXPECTED_ELIGIBLE_ERROR_PATHS = 191
EXPECTED_STATE_ROWS = 250
EXPECTED_RETRIEVER_PATHS = {"R1": 360, "R2": 240, "R3": 120}
EXPECTED_CONDITION_PATHS = {condition: 120 for condition in SELECTIVE_CONDITIONS}
EXPECTED_BACKBONE_CONDITION_PATHS = {(backbone, condition): 60 for backbone in BACKBONE_ORDER for condition in SELECTIVE_CONDITIONS}

STAGE_A_PATH = "artifacts/chapter5-main60-analysis-v1/stage-a/master-table.jsonl"
STAGE1_PATH = "artifacts/chapter5-main60-analysis-v1/rq5-root-cause-index"
STORAGE_PATH = "artifacts/chapter5-main60-analysis-v1/rq5-storage-audit"
GOLD_PATHS = (
    "experiments/locomo-conv50-v1/question-sets/main-40-gold.jsonl",
    "experiments/locomo-conv50-v1/question-sets-main60-v2/extension-20-gold.jsonl",
)
STORE_MANIFEST_PATHS = (
    "experiments/locomo-conv50-v1/manifests/s1-flat.json",
    "experiments/locomo-conv50-v1/manifests/s2-foldered.json",
    "experiments/locomo-conv50-v1/manifests/s3-curated.json",
)

TABLES = (
    "retrieval-funnel",
    "stage-transitions",
    "r1-diagnostics",
    "r2-diagnostics",
    "r3-diagnostics",
    "controlled-comparisons",
    "cross-backbone-comparisons",
    "strict-error-retrieval-linkage",
    "root-cause-state-register-after-retrieval",
    "retriever-summary",
    "retriever-category-summary",
)

FORBIDDEN_OUTPUT_FIELDS = {
    "question", "question_text", "answer", "answer_text", "reference_answer",
    "candidate_answer", "evidence", "evidence_text", "retrieved_text",
    "prompt", "rationale", "thought", "short_reason", "judge_reason",
    "keywords", "query_text", "api_key", "authorization", "secret",
}
SECRET_FIELD_FRAGMENTS = ("password", "secret", "bearer", "api_key", "authorization")


def _artifact_id(prefix: str, body: Mapping[str, Any]) -> str:
    return prefix + sha256_bytes(canonical_json_bytes(dict(body)))


def _ordered_unique(values: Iterable[str]) -> list[str]:
    return list(dict.fromkeys(str(value) for value in values))


def _gold_rows(repo_root: Path) -> dict[str, dict[str, Any]]:
    rows = [row for relative in GOLD_PATHS for row in _read_jsonl(repo_root / relative)]
    _require(len(rows) == 60 and len({row["question_id"] for row in rows}) == 60, "Main-60 gold population differs")
    return {str(row["question_id"]): row for row in rows}


def _validate_inputs(repo_root: Path) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    stage_a = _read_jsonl(repo_root / STAGE_A_PATH)
    rows = [dict(row) for row in stage_a if row.get("condition_id") in SELECTIVE_CONDITIONS]
    _require(len(rows) == EXPECTED_PATHS, "E1--E6 path count differs")
    _require(Counter(str(row["condition_id"]) for row in rows) == Counter(EXPECTED_CONDITION_PATHS), "E1--E6 condition counts differ")
    _require(Counter((str(row["backbone_id"]), str(row["condition_id"])) for row in rows) == Counter(EXPECTED_BACKBONE_CONDITION_PATHS), "Backbone-condition counts differ")
    _require(Counter(str(row["retrieval_system"]) for row in rows) == Counter(EXPECTED_RETRIEVER_PATHS), "Retriever counts differ")
    _require(sum(bool(row["evidence_eligible"]) for row in rows) == EXPECTED_ELIGIBLE_PATHS, "Eligible retrieval-path count differs")
    _require(len({str(row["analysis_row_id"]) for row in rows}) == EXPECTED_PATHS, "Analysis row IDs repeat")

    gold = _gold_rows(repo_root)
    storage_rows = _read_jsonl(repo_root / STORAGE_PATH / "storage-outcome-linkage.jsonl")
    _require(len(storage_rows) == EXPECTED_PATHS, "Storage outcome linkage count differs")
    storage_by_id = {str(row["analysis_row_id"]): row for row in storage_rows}
    _require(set(storage_by_id) == {str(row["analysis_row_id"]) for row in rows}, "Storage/RQ5 retrieval identities differ")

    storage_errors = _read_jsonl(repo_root / STORAGE_PATH / "case-storage-linkage.jsonl")
    _require(len(storage_errors) == EXPECTED_ERROR_PATHS, "Selective error linkage count differs")
    after_storage = _read_jsonl(repo_root / STORAGE_PATH / "root-cause-state-register-after-storage.jsonl")
    _require(len(after_storage) == EXPECTED_STATE_ROWS, "Post-storage state-register count differs")

    for row in rows:
        condition = str(row["condition_id"])
        _require(row["storage_representation"] == STORE_BY_CONDITION[condition], "Store/condition mapping differs")
        _require(row["retrieval_system"] == RETRIEVER_BY_CONDITION[condition], "Retriever/condition mapping differs")
        _require(str(row["question_id"]) in gold, "Gold question identity is missing")
        source_path = repo_root / str(row["source_record_path"])
        _require(source_path.is_file() and not source_path.is_symlink(), "Retrieval source record is unsafe or missing")
        _require(_sha256_file(source_path) == row["source_record_file_sha256"], "Retrieval source record hash differs")
    return rows, gold, storage_errors, after_storage


def _memory_relative(value: Any) -> str:
    path = str(value)
    return path[len("/memories/") :] if path.startswith("/memories/") else path


def _coverage_overlaps(span: Any, coverage: Mapping[str, Any]) -> bool:
    return (
        _memory_relative(coverage.get("path")) == _memory_relative(span.path)
        and int(coverage.get("line_start", 0)) <= int(span.line_end)
        and int(coverage.get("line_end", 0)) >= int(span.line_start)
    )


def _set_state(count: int, total: int, *, none: str = "none", partial: str = "partial", complete: str = "complete") -> str:
    if total == 0:
        return "not_annotated"
    if count == 0:
        return none
    if count == total:
        return complete
    return partial


def _final_locators(bundle: Mapping[str, Any]) -> set[str]:
    return {
        str(locator)
        for item in bundle.get("evidence_items", [])
        for locator in item.get("source_locators", [])
    }


def _final_dia_ids(bundle: Mapping[str, Any]) -> set[str]:
    return {
        str(dia_id)
        for item in bundle.get("evidence_items", [])
        for dia_id in item.get("dia_ids", [])
    }


def _r1_trace(
    *, bundle: Mapping[str, Any], store: LoadedR1Store, gold_locators: Sequence[str]
) -> tuple[dict[str, Any], dict[str, Any]]:
    spans = {locator: tuple(store.verified_manifest.attribution_index.occurrences(locator)) for locator in gold_locators}
    gold_paths = {_memory_relative(span.path) for values in spans.values() for span in values}
    observed: set[str] = set()
    selected: set[str] = set()
    reached_paths: set[str] = set()
    inspected_files: list[str] = []
    inspected_directories: list[str] = []
    productive_actions = 0
    repeat_file_actions = 0
    first_gold_round: int | None = None
    filesystem_actions = 0
    grep_actions = 0
    view_actions = 0
    toc_actions = 0
    accepted_notes = 0
    rejected_actions = 0
    seen_files: set[str] = set()

    for action in bundle.get("search_actions", []):
        kind = action.get("kind")
        if kind == "filesystem_observation":
            filesystem_actions += 1
            tool = str(action.get("tool_name"))
            grep_actions += int(tool == "grep")
            view_actions += int(tool == "view")
            toc_actions += int(tool == "toc")
            path = str(action.get("canonical_args", {}).get("path", ""))
            if path.endswith(".md"):
                inspected_files.append(path)
                if path in seen_files:
                    repeat_file_actions += 1
                seen_files.add(path)
            elif path:
                inspected_directories.append(path)
            coverage = [dict(value) for value in action.get("coverage", [])]
            reached_paths.update(
                _memory_relative(value.get("path"))
                for value in coverage
                if _memory_relative(value.get("path")) in gold_paths
            )
            before = len(observed)
            for locator, locator_spans in spans.items():
                if any(_coverage_overlaps(span, value) for span in locator_spans for value in coverage):
                    observed.add(locator)
            if len(observed) > before:
                productive_actions += 1
                if first_gold_round is None:
                    first_gold_round = int(action.get("provider_round", 0))
        elif kind == "take_note_resolution" and action.get("status") == "accepted":
            accepted_notes += 1
            selector = dict(action.get("selector", {}))
            for locator, locator_spans in spans.items():
                if any(_coverage_overlaps(span, selector) for span in locator_spans):
                    selected.add(locator)
        elif kind == "rejected_action":
            rejected_actions += 1

    final = _final_locators(bundle)
    provider_rounds = int(bundle.get("metrics", {}).get("provider_rounds", 0))
    stop = dict(bundle.get("stop", {}))
    diagnostic = {
        "source_reached_any": bool(reached_paths) if gold_locators else None,
        "observed_gold_locators": len(observed),
        "selected_gold_locators": len(set(gold_locators) & selected),
        "final_gold_locators": len(set(gold_locators) & final),
        "first_gold_action": None,
        "first_gold_round": first_gold_round,
        "first_gold_result_rank": None,
        "first_gold_backend_rank": None,
        "first_gold_group_rank": None,
        "search_replay_verified": None,
        "search_count": filesystem_actions,
        "note_action_count": accepted_notes,
        "finish_action_count": sum(action.get("kind") == "finish_search_accepted" for action in bundle.get("search_actions", [])),
    }
    retriever = {
        "filesystem_observation_count": filesystem_actions,
        "grep_attempt_count": grep_actions,
        "view_attempt_count": view_actions,
        "toc_attempt_count": toc_actions,
        "unique_files_inspected": len(set(inspected_files)),
        "unique_directories_inspected": len(set(inspected_directories)),
        "repeat_file_observation_count": repeat_file_actions,
        "productive_gold_observation_count": productive_actions,
        "productive_gold_observation_rate": None if filesystem_actions == 0 else productive_actions / filesystem_actions,
        "first_gold_observation_round": first_gold_round,
        "rounds_after_first_gold_observation": None if first_gold_round is None else max(0, provider_rounds - first_gold_round),
        "accepted_note_count": accepted_notes,
        "rejected_action_count": rejected_actions,
        "gold_source_file_count": len(gold_paths),
        "gold_source_files_reached": len(reached_paths),
        "search_replay_verified": None,
    }
    return diagnostic, retriever


def _replay_ranked_trace(
    *,
    bundle: Mapping[str, Any],
    index: R2RawIndex | R3CuratedIndex,
    gold_locators: Sequence[str],
    retriever: str,
    r3_corpus: R3CuratedCorpus | None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    is_r2 = retriever == "R2"
    seen: set[str] = set()
    noted_anchors: set[str] = set()
    last: R2SearchResult | R3SearchResult | None = None
    observed: set[str] = set()
    selected: set[str] = set()
    reached_sources: set[str] = set()
    first_gold_action: int | None = None
    first_gold_round: int | None = None
    first_result_rank: int | None = None
    first_backend_rank: int | None = None
    first_group_rank: int | None = None
    search_count = 0
    note_count = 0
    finish_count = 0
    new_annotated_gold_searches = 0
    no_new_annotated_gold_searches = 0
    selected_note_count = 0
    query_term_total = 0
    first_query_term_count: int | None = None
    first_query_gold_overlap_count: int | None = None
    first_query_gold_overlap_rate: float | None = None
    all_query_terms: set[str] = set()
    context_only_gold_hits = 0

    if is_r2:
        gold_source_ids = {
            index.corpus.store.catalog.resolve(locator).session_id for locator in gold_locators
        }
        source_tokens: set[str] = set()
        for exchange in index.exchanges:
            if set(exchange.locators) & set(gold_locators):
                source_tokens.update(index.tokenizer.tokenize(exchange.search_text))
    else:
        _require(r3_corpus is not None, "R3 corpus is required")
        gold_source_ids = {
            unit.group_id for unit in r3_corpus.units if set(unit.source_locators) & set(gold_locators)
        }
        source_tokens = set()
        for unit in r3_corpus.units:
            if set(unit.source_locators) & set(gold_locators):
                source_tokens.update(index.tokenizer.tokenize(unit.search_text))

    for action in bundle.get("search_actions", []):
        if action.get("event") != "action":
            continue
        name = action.get("action")
        if name == "search_chatrecord":
            search_count += 1
            args = dict(action.get("arguments", {}))
            if is_r2:
                last = index.search(
                    args["keywords"], top_k=args["top_k"], context_window=2,
                    seen_sessions=seen, date_from=args.get("date_from"), date_to=args.get("date_to"),
                )
                returned = list(last.returned_sessions)
                recorded = list(action.get("returned_sessions", []))
            else:
                last = index.search(
                    args["keywords"], top_k=args["top_k"], context_window=2,
                    seen_groups=seen, date_from=args.get("date_from"), date_to=args.get("date_to"),
                )
                returned = list(last.returned_groups)
                recorded = list(action.get("returned_groups", []))
            _require(returned == recorded, "Offline replay returned-source identity differs")
            _require(list(last.query_terms) == list(action.get("query_terms", [])), "Offline replay query terms differ")
            _require(len(last.hits) == int(action.get("result_count", -1)), "Offline replay result count differs")
            _require(not (set(returned) & seen), "Seen-state replay returned an excluded source")
            seen.update(returned)
            reached_sources.update(set(returned) & gold_source_ids)
            query_terms = set(last.query_terms)
            query_term_total += len(last.query_terms)
            all_query_terms.update(query_terms)
            if first_query_term_count is None:
                first_query_term_count = len(last.query_terms)
                first_query_gold_overlap_count = len(query_terms & source_tokens)
                first_query_gold_overlap_rate = None if not query_terms else first_query_gold_overlap_count / len(query_terms)
            before = len(observed)
            for hit in last.hits:
                hit_gold = set(hit.locators) & set(gold_locators)
                if not hit_gold:
                    continue
                observed.update(hit_gold)
                anchor_locators = set(hit.anchor.locators if is_r2 else hit.anchor.source_locators)
                if hit_gold - anchor_locators:
                    context_only_gold_hits += 1
                if first_gold_action is None:
                    first_gold_action = search_count
                    first_gold_round = int(action.get("provider_round", 0))
                    first_result_rank = int(hit.result_index)
                    first_backend_rank = int(hit.exchange_rank if is_r2 else hit.unit_rank)
                    first_group_rank = int(hit.session_rank if is_r2 else hit.group_rank)
            if len(observed) > before:
                new_annotated_gold_searches += 1
            else:
                no_new_annotated_gold_searches += 1
        elif name == "take_note":
            note_count += 1
            if last is None:
                continue
            indices = list(action.get("arguments", {}).get("indices", []))
            if any(int(index_value) > len(last.hits) for index_value in indices):
                continue
            for result_index in indices:
                hit = last.hits[int(result_index) - 1]
                anchor_id = hit.anchor.exchange_id if is_r2 else hit.anchor.unit_id
                if anchor_id in noted_anchors:
                    continue
                noted_anchors.add(anchor_id)
                selected_note_count += 1
                selected.update(set(hit.locators) & set(gold_locators))
        elif name == "finish_search":
            finish_count += 1

    final = _final_locators(bundle)
    diagnostic = {
        "source_reached_any": bool(reached_sources) if gold_locators else None,
        "observed_gold_locators": len(observed),
        "selected_gold_locators": len(selected),
        "final_gold_locators": len(set(gold_locators) & final),
        "first_gold_action": first_gold_action,
        "first_gold_round": first_gold_round,
        "first_gold_result_rank": first_result_rank,
        "first_gold_backend_rank": first_backend_rank,
        "first_gold_group_rank": first_group_rank,
        "search_replay_verified": True,
        "search_count": search_count,
        "note_action_count": note_count,
        "finish_action_count": finish_count,
    }
    retriever_specific = {
        "search_action_count": search_count,
        "note_action_count": note_count,
        "finish_action_count": finish_count,
        "saved_unique_note_count": selected_note_count,
        "new_annotated_gold_search_count": new_annotated_gold_searches,
        "no_new_annotated_gold_search_count": no_new_annotated_gold_searches,
        "first_gold_search_action": first_gold_action,
        "first_gold_result_rank": first_result_rank,
        "first_gold_backend_unit_rank": first_backend_rank,
        "first_gold_source_group_rank": first_group_rank,
        "gold_source_group_count": len(gold_source_ids),
        "gold_source_groups_reached": len(reached_sources),
        "context_only_gold_hit_count": context_only_gold_hits,
        "first_query_term_count": first_query_term_count,
        "first_query_gold_source_overlap_count": first_query_gold_overlap_count,
        "first_query_gold_source_overlap_rate": first_query_gold_overlap_rate,
        "all_query_term_count": len(all_query_terms),
        "all_query_gold_source_overlap_count": len(all_query_terms & source_tokens),
        "seen_state_exclusion_verified": True,
        "search_replay_verified": True,
        "replay_sha256": sha256_bytes(canonical_json_bytes({
            "retriever": retriever,
            "search_count": search_count,
            "note_count": note_count,
            "finish_count": finish_count,
            "observed_count": len(observed),
            "selected_count": len(selected),
            "returned_source_count": len(seen),
        })),
    }
    return diagnostic, retriever_specific


def _stop_alignment(*, eligible: bool, observed_all: bool | None, stop: Mapping[str, Any]) -> str:
    if not eligible:
        return "not_annotated"
    hit_cap = bool(stop.get("hit_cap"))
    complete = bool(observed_all)
    if hit_cap:
        return "cap_with_complete_annotation" if complete else "cap_with_incomplete_annotation"
    reason = str(stop.get("reason"))
    if reason == "evidence_sufficient":
        return "declared_sufficient_with_complete_annotation" if complete else "declared_sufficient_with_incomplete_annotation"
    return "other_stop_with_complete_annotation" if complete else "other_stop_with_incomplete_annotation"


def _funnel_row(
    *,
    source_row: Mapping[str, Any],
    storage_row: Mapping[str, Any],
    gold: Mapping[str, Any],
    record: Mapping[str, Any],
    diagnostic: Mapping[str, Any],
) -> dict[str, Any]:
    eligible = bool(source_row["evidence_eligible"])
    locators = [str(value) for value in gold.get("gold_evidence_locators", [])]
    total = len(locators)
    observed_count = int(diagnostic["observed_gold_locators"])
    selected_count = int(diagnostic["selected_gold_locators"])
    final_count = int(diagnostic["final_gold_locators"])
    source_reached = diagnostic["source_reached_any"]
    observed_any = None if not eligible else observed_count > 0
    observed_all = None if not eligible else observed_count == total
    selected_any = None if not eligible else selected_count > 0
    selected_all = None if not eligible else selected_count == total
    final_any = None if not eligible else final_count > 0
    final_all = None if not eligible else final_count == total
    bundle = dict(record["evidence_bundle"])
    evidence_item_count = len(bundle.get("evidence_items", []))
    budget = dict(bundle.get("budget", {}))
    stop = dict(bundle.get("stop", {}))
    return {
        "protocol_version": PROTOCOL_VERSION,
        "retrieval_path_id": _artifact_id("rq5-retrieval-path-", {"analysis_row_id": source_row["analysis_row_id"]}),
        "analysis_row_id": source_row["analysis_row_id"],
        "question_id": source_row["question_id"],
        "backbone_id": source_row["backbone_id"],
        "condition_id": source_row["condition_id"],
        "store_id": source_row["storage_representation"],
        "retriever_id": source_row["retrieval_system"],
        "category_name": source_row["category_name"],
        "evidence_eligible": eligible,
        "gold_locator_count": total,
        "store_availability_state": storage_row["store_availability_state"],
        "reference_support_sufficiency": storage_row["reference_support_sufficiency"],
        "annotated_source_presence_state": "present" if eligible else "not_annotated",
        "source_reach_state": "not_annotated" if not eligible else "reached" if source_reached else "not_reached",
        "annotated_evidence_observation_state": "not_annotated" if not eligible else "observed" if observed_any else "not_observed",
        "complete_acquisition_state": _set_state(observed_count, total),
        "selection_state": _set_state(selected_count, total),
        "final_bundle_state": "not_annotated" if not eligible else "all_hit" if final_all else "partial_hit" if final_any else "no_hit",
        "source_reached_any": source_reached,
        "observed_gold_count": observed_count if eligible else None,
        "observed_gold_fraction": None if not eligible else observed_count / total,
        "observed_any": observed_any,
        "observed_all": observed_all,
        "selected_gold_count": selected_count if eligible else None,
        "selected_gold_fraction": None if not eligible else selected_count / total,
        "selected_any": selected_any,
        "selected_all": selected_all,
        "final_gold_count": final_count if eligible else None,
        "final_gold_fraction": None if not eligible else final_count / total,
        "final_any_hit": final_any,
        "final_all_hit": final_all,
        "evidence_item_count": evidence_item_count,
        "empty_bundle": evidence_item_count == 0,
        "nonempty_bundle_without_annotated_gold": None if not eligible else evidence_item_count > 0 and final_count == 0,
        "recorded_evidence_recall": source_row["evidence_recall"],
        "recorded_evidence_any_hit": source_row["evidence_any_hit"],
        "recorded_evidence_all_hit": source_row["evidence_all_hit"],
        "first_gold_action": diagnostic["first_gold_action"],
        "first_gold_round": diagnostic["first_gold_round"],
        "first_gold_result_rank": diagnostic["first_gold_result_rank"],
        "first_gold_backend_rank": diagnostic["first_gold_backend_rank"],
        "first_gold_group_rank": diagnostic["first_gold_group_rank"],
        "native_search_or_observation_count": diagnostic["search_count"],
        "native_note_action_count": diagnostic["note_action_count"],
        "native_finish_action_count": diagnostic["finish_action_count"],
        "native_round_or_action_cap": int(bundle.get("runtime_contract", {}).get("round_limit", 0)),
        "stop_reason": stop.get("reason"),
        "hit_native_cap": bool(stop.get("hit_cap")),
        "stop_annotation_alignment": _stop_alignment(eligible=eligible, observed_all=observed_all, stop=stop),
        "budget_used_characters": int(budget.get("used", 0)),
        "budget_limit_characters": int(budget.get("limit", 0)),
        "budget_skipped_items": int(budget.get("skipped_items", 0)),
        "budget_truncated": bool(budget.get("truncated", False)),
        "partial_multi_hop_observation": bool(eligible and total > 1 and 0 < observed_count < total),
        "partial_multi_hop_selection": bool(eligible and total > 1 and 0 < selected_count < total),
        "partial_multi_hop_bundle": bool(eligible and total > 1 and 0 < final_count < total),
        "observed_gold_lost_before_selection": bool(eligible and observed_count > selected_count),
        "selected_gold_lost_before_bundle": bool(eligible and selected_count > final_count),
        "strict_score": float(source_row["strict_score"]),
        "judge_label": source_row["judge_label"],
        "soft_semantic_score": float(source_row["soft_semantic_score"]),
        "token_f1": float(source_row["token_f1"]),
        "search_replay_verified": diagnostic["search_replay_verified"],
        "gold_annotation_is_diagnostic_not_causal": True,
        "native_cap_is_not_automatic_failure": True,
    }


def _transition(left: bool | None, right: bool | None) -> str:
    if left is None or right is None:
        return "not_annotated"
    if left == right:
        return "both_true" if left else "both_false"
    return "repair" if right else "harm"


def _diagnostic_error_state(row: Mapping[str, Any]) -> str:
    if not row["evidence_eligible"]:
        return "not_annotated"
    if not row["source_reached_any"]:
        return "annotated_source_not_reached"
    if not row["observed_any"]:
        return "source_reached_gold_not_observed"
    if not row["observed_all"]:
        return "partial_annotated_acquisition"
    if not row["selected_all"]:
        return "complete_observation_incomplete_selection"
    if not row["final_all_hit"]:
        return "complete_selection_incomplete_bundle"
    return "complete_annotated_bundle_strict_noncorrect"


def _aggregate_summary_rows(
    funnel: Sequence[Mapping[str, Any]],
    *,
    include_category: bool,
) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    groups: dict[tuple[str, ...], list[Mapping[str, Any]]] = defaultdict(list)
    for row in funnel:
        key = (str(row["backbone_id"]), str(row["condition_id"]))
        if include_category:
            key += (str(row["category_name"]),)
        groups[key].append(row)
    for key in sorted(groups, key=lambda value: (BACKBONE_ORDER[value[0]], CONDITION_ORDER[value[1]], *value[2:])):
        rows = groups[key]
        eligible = [row for row in rows if row["evidence_eligible"]]
        all_hit = [row for row in eligible if row["final_all_hit"]]
        not_all = [row for row in eligible if not row["final_all_hit"]]
        backbone, condition = key[:2]
        summary = {
            "protocol_version": PROTOCOL_VERSION,
            "backbone_id": backbone,
            "condition_id": condition,
            "store_id": STORE_BY_CONDITION[condition],
            "retriever_id": RETRIEVER_BY_CONDITION[condition],
            "path_n": len(rows),
            "eligible_n": len(eligible),
            "source_reached_n": sum(bool(row["source_reached_any"]) for row in eligible),
            "source_reached_rate": sum(bool(row["source_reached_any"]) for row in eligible) / len(eligible),
            "observed_any_n": sum(bool(row["observed_any"]) for row in eligible),
            "observed_any_rate": sum(bool(row["observed_any"]) for row in eligible) / len(eligible),
            "observed_all_n": sum(bool(row["observed_all"]) for row in eligible),
            "observed_all_rate": sum(bool(row["observed_all"]) for row in eligible) / len(eligible),
            "selected_all_n": sum(bool(row["selected_all"]) for row in eligible),
            "selected_all_rate": sum(bool(row["selected_all"]) for row in eligible) / len(eligible),
            "final_any_hit_n": sum(bool(row["final_any_hit"]) for row in eligible),
            "final_any_hit_rate": sum(bool(row["final_any_hit"]) for row in eligible) / len(eligible),
            "final_all_hit_n": len(all_hit),
            "final_all_hit_rate": len(all_hit) / len(eligible),
            "mean_evidence_recall": math.fsum(float(row["recorded_evidence_recall"]) for row in eligible) / len(eligible),
            "empty_bundle_n": sum(bool(row["empty_bundle"]) for row in rows),
            "eligible_empty_bundle_n": sum(bool(row["empty_bundle"]) for row in eligible),
            "ineligible_empty_bundle_n": sum(bool(row["empty_bundle"]) for row in rows if not row["evidence_eligible"]),
            "nonempty_bundle_without_annotated_gold_n": sum(bool(row["nonempty_bundle_without_annotated_gold"]) for row in eligible),
            "strict_correct_n": sum(float(row["strict_score"]) == 1.0 for row in rows),
            "strict_accuracy": math.fsum(float(row["strict_score"]) for row in rows) / len(rows),
            "mean_soft_semantic_score": math.fsum(float(row["soft_semantic_score"]) for row in rows) / len(rows),
            "p_correct_given_all_hit": None if not all_hit else sum(float(row["strict_score"]) == 1.0 for row in all_hit) / len(all_hit),
            "p_correct_given_not_all_hit": None if not not_all else sum(float(row["strict_score"]) == 1.0 for row in not_all) / len(not_all),
            "native_cap_hit_n": sum(bool(row["hit_native_cap"]) for row in rows),
            "native_cap_hit_with_strict_correct_n": sum(bool(row["hit_native_cap"]) and float(row["strict_score"]) == 1.0 for row in rows),
            "declared_sufficient_incomplete_annotation_n": sum(row["stop_annotation_alignment"] == "declared_sufficient_with_incomplete_annotation" for row in eligible),
            "observed_gold_lost_before_selection_n": sum(bool(row["observed_gold_lost_before_selection"]) for row in eligible),
            "selected_gold_lost_before_bundle_n": sum(bool(row["selected_gold_lost_before_bundle"]) for row in eligible),
            "partial_multi_hop_bundle_n": sum(bool(row["partial_multi_hop_bundle"]) for row in eligible),
            "mean_native_search_or_observation_count": math.fsum(float(row["native_search_or_observation_count"]) for row in rows) / len(rows),
            "mean_retrieval_tokens": math.fsum(float(row["_retrieval_tokens"]) for row in rows) / len(rows),
        }
        if include_category:
            summary["category_name"] = key[2]
        output.append(summary)
    return output


def _summary_rows(funnel: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    return _aggregate_summary_rows(funnel, include_category=False)


def _category_summary_rows(funnel: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    return _aggregate_summary_rows(funnel, include_category=True)


def _stage_transition_rows(funnel: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    groups: dict[tuple[str, str], list[Mapping[str, Any]]] = defaultdict(list)
    for row in funnel:
        groups[(str(row["backbone_id"]), str(row["condition_id"]))].append(row)
    stages = (
        ("annotated_source_present", "source_reached", lambda row: True, lambda row: bool(row["source_reached_any"])),
        ("source_reached", "gold_observed_any", lambda row: bool(row["source_reached_any"]), lambda row: bool(row["observed_any"])),
        ("gold_observed_any", "gold_observed_all", lambda row: bool(row["observed_any"]), lambda row: bool(row["observed_all"])),
        ("gold_observed_all", "gold_selected_all", lambda row: bool(row["observed_all"]), lambda row: bool(row["selected_all"])),
        ("gold_selected_all", "final_bundle_all_hit", lambda row: bool(row["selected_all"]), lambda row: bool(row["final_all_hit"])),
        ("final_bundle_all_hit", "strict_correct", lambda row: bool(row["final_all_hit"]), lambda row: float(row["strict_score"]) == 1.0),
    )
    for key in sorted(groups, key=lambda value: (BACKBONE_ORDER[value[0]], CONDITION_ORDER[value[1]])):
        eligible = [row for row in groups[key] if row["evidence_eligible"]]
        for ordinal, (source_stage, target_stage, source_test, target_test) in enumerate(stages, 1):
            source_rows = [row for row in eligible if source_test(row)]
            retained = sum(target_test(row) for row in source_rows)
            rows.append({
                "protocol_version": PROTOCOL_VERSION,
                "backbone_id": key[0],
                "condition_id": key[1],
                "store_id": STORE_BY_CONDITION[key[1]],
                "retriever_id": RETRIEVER_BY_CONDITION[key[1]],
                "transition_ordinal": ordinal,
                "source_stage": source_stage,
                "target_stage": target_stage,
                "source_n": len(source_rows),
                "target_n": retained,
                "retention_rate": None if not source_rows else retained / len(source_rows),
                "attrition_n": len(source_rows) - retained,
            })
    return rows


def _comparison_rows(funnel: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    by_key = {(str(row["backbone_id"]), str(row["question_id"]), str(row["condition_id"])): row for row in funnel}
    contrasts = (
        ("E2-E1", "E1", "E2", "R2_vs_R1_on_S1"),
        ("E4-E3", "E3", "E4", "R2_vs_R1_on_S2"),
        ("E6-E5", "E5", "E6", "R3_vs_R1_on_S3"),
        ("E3-E1", "E1", "E3", "S2_effect_on_R1_path"),
        ("E4-E2", "E2", "E4", "R2_folder_invariance_check"),
    )
    output: list[dict[str, Any]] = []
    qids = sorted({str(row["question_id"]) for row in funnel})
    for backbone in BACKBONE_ORDER:
        for contrast, left_id, right_id, role in contrasts:
            for qid in qids:
                left = by_key[(backbone, qid, left_id)]
                right = by_key[(backbone, qid, right_id)]
                acquisition = _transition(left["observed_all"], right["observed_all"])
                final_bundle = _transition(left["final_all_hit"], right["final_all_hit"])
                strict = _transition(float(left["strict_score"]) == 1.0, float(right["strict_score"]) == 1.0)
                output.append({
                    "protocol_version": PROTOCOL_VERSION,
                    "comparison_id": _artifact_id("rq5-retrieval-contrast-", {"backbone": backbone, "question_id": qid, "contrast": contrast}),
                    "backbone_id": backbone,
                    "question_id": qid,
                    "category_name": left["category_name"],
                    "contrast": contrast,
                    "comparison_role": role,
                    "left_condition": left_id,
                    "right_condition": right_id,
                    "evidence_eligible": bool(left["evidence_eligible"]),
                    "source_reach_transition": _transition(left["source_reached_any"], right["source_reached_any"]),
                    "complete_acquisition_transition": acquisition,
                    "final_bundle_all_hit_transition": final_bundle,
                    "strict_transition": strict,
                    "evidence_recall_delta": None if not left["evidence_eligible"] else float(right["recorded_evidence_recall"]) - float(left["recorded_evidence_recall"]),
                    "soft_score_delta": float(right["soft_semantic_score"]) - float(left["soft_semantic_score"]),
                    "retrieval_improved_answer_not": acquisition == "repair" and strict in {"both_false", "harm"},
                    "final_bundle_improved_answer_not": final_bundle == "repair" and strict in {"both_false", "harm"},
                })
    return output


def _cross_backbone_rows(funnel: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    by_key = {(str(row["backbone_id"]), str(row["question_id"]), str(row["condition_id"])): row for row in funnel}
    output: list[dict[str, Any]] = []
    qids = sorted({str(row["question_id"]) for row in funnel})
    for condition in SELECTIVE_CONDITIONS:
        for qid in qids:
            qwen = by_key[("qwen", qid, condition)]
            deepseek = by_key[("deepseek", qid, condition)]
            output.append({
                "protocol_version": PROTOCOL_VERSION,
                "comparison_id": _artifact_id("rq5-retrieval-backbone-", {"condition": condition, "question_id": qid}),
                "question_id": qid,
                "category_name": qwen["category_name"],
                "condition_id": condition,
                "store_id": qwen["store_id"],
                "retriever_id": qwen["retriever_id"],
                "evidence_eligible": bool(qwen["evidence_eligible"]),
                "source_reach_agreement": qwen["source_reached_any"] == deepseek["source_reached_any"],
                "complete_acquisition_agreement": qwen["observed_all"] == deepseek["observed_all"],
                "final_bundle_all_hit_agreement": qwen["final_all_hit"] == deepseek["final_all_hit"],
                "strict_outcome_agreement": qwen["strict_score"] == deepseek["strict_score"],
                "qwen_source_reached": qwen["source_reached_any"],
                "deepseek_source_reached": deepseek["source_reached_any"],
                "qwen_complete_acquisition": qwen["observed_all"],
                "deepseek_complete_acquisition": deepseek["observed_all"],
                "qwen_final_all_hit": qwen["final_all_hit"],
                "deepseek_final_all_hit": deepseek["final_all_hit"],
                "qwen_strict_correct": float(qwen["strict_score"]) == 1.0,
                "deepseek_strict_correct": float(deepseek["strict_score"]) == 1.0,
                "native_cap_state_agreement": qwen["hit_native_cap"] == deepseek["hit_native_cap"],
            })
    return output


def _build_core(repo_root: Path) -> dict[str, list[dict[str, Any]]]:
    rows, gold_by_qid, storage_errors, after_storage = _validate_inputs(repo_root)
    storage_outcomes = {str(row["analysis_row_id"]): row for row in _read_jsonl(repo_root / STORAGE_PATH / "storage-outcome-linkage.jsonl")}
    stores = {store: load_r1_store(repo_root, store.casefold()) for store in ("S1", "S2", "S3")}
    r2_indexes = {store: R2RawIndex(build_r2_raw_corpus(repo_root, store.casefold())) for store in ("S1", "S2")}
    r3_corpus = load_r3_corpus(repo_root)
    r3_index = R3CuratedIndex(r3_corpus)

    funnel: list[dict[str, Any]] = []
    r1_rows: list[dict[str, Any]] = []
    r2_rows: list[dict[str, Any]] = []
    r3_rows: list[dict[str, Any]] = []
    for source_row in sorted(rows, key=lambda row: (BACKBONE_ORDER[str(row["backbone_id"])], int(row["global_position"]), CONDITION_ORDER[str(row["condition_id"])])):
        qid = str(source_row["question_id"])
        gold = gold_by_qid[qid]
        locators = [str(value) for value in gold.get("gold_evidence_locators", [])]
        record = _read_json(repo_root / str(source_row["source_record_path"]))
        _require(record.get("record_id") == source_row["source_record_id"], "Retrieval record identity differs")
        bundle = dict(record["evidence_bundle"])
        retriever = str(source_row["retrieval_system"])
        store_id = str(source_row["storage_representation"])
        if retriever == "R1":
            diagnostic, specific = _r1_trace(bundle=bundle, store=stores[store_id], gold_locators=locators)
        elif retriever == "R2":
            diagnostic, specific = _replay_ranked_trace(bundle=bundle, index=r2_indexes[store_id], gold_locators=locators, retriever="R2", r3_corpus=None)
        else:
            diagnostic, specific = _replay_ranked_trace(bundle=bundle, index=r3_index, gold_locators=locators, retriever="R3", r3_corpus=r3_corpus)
        row = _funnel_row(source_row=source_row, storage_row=storage_outcomes[str(source_row["analysis_row_id"])], gold=gold, record=record, diagnostic=diagnostic)
        row["_retrieval_tokens"] = int(source_row["retrieval_total_tokens"])
        # Independently confirm the final-bundle fields already frozen by Stage A.
        _require(row["final_any_hit"] == source_row["evidence_any_hit"], "Final Any-hit reconstruction differs")
        _require(row["final_all_hit"] == source_row["evidence_all_hit"], "Final All-hit reconstruction differs")
        if row["evidence_eligible"]:
            _require(math.isclose(float(row["final_gold_fraction"]), float(source_row["evidence_recall"])), "Final Evidence Recall reconstruction differs")
        funnel.append(row)
        common = {
            "protocol_version": PROTOCOL_VERSION,
            "retrieval_path_id": row["retrieval_path_id"],
            "analysis_row_id": row["analysis_row_id"],
            "question_id": row["question_id"],
            "backbone_id": row["backbone_id"],
            "condition_id": row["condition_id"],
            "store_id": row["store_id"],
            "category_name": row["category_name"],
            "evidence_eligible": row["evidence_eligible"],
            "gold_locator_count": row["gold_locator_count"],
            "observed_gold_count": row["observed_gold_count"],
            "selected_gold_count": row["selected_gold_count"],
            "final_gold_count": row["final_gold_count"],
            "stop_reason": row["stop_reason"],
            "hit_native_cap": row["hit_native_cap"],
            "strict_score": row["strict_score"],
        }
        if retriever == "R1":
            r1_rows.append({**common, **specific})
        elif retriever == "R2":
            r2_rows.append({**common, **specific})
        else:
            r3_rows.append({**common, **specific})

    # Private helper value is needed for aggregation only and is not published.
    summary = _summary_rows(funnel)
    category_summary = _category_summary_rows(funnel)
    for row in funnel:
        row.pop("_retrieval_tokens")

    funnel_by_analysis = {str(row["analysis_row_id"]): row for row in funnel}
    storage_error_by_case = {str(row["case_id"]): row for row in storage_errors}
    stage1_errors = _read_jsonl(repo_root / STAGE1_PATH / "strict-error-cases.jsonl")
    selective_errors = [row for row in stage1_errors if row["condition_id"] in SELECTIVE_CONDITIONS]
    _require(len(selective_errors) == EXPECTED_ERROR_PATHS, "Selective Strict-error count differs")
    error_links: list[dict[str, Any]] = []
    error_link_by_case: dict[str, dict[str, Any]] = {}
    for error in selective_errors:
        frow = funnel_by_analysis[str(error["analysis_row_id"])]
        storage = storage_error_by_case[str(error["case_id"])]
        link = {
            "protocol_version": PROTOCOL_VERSION,
            "case_id": error["case_id"],
            "analysis_row_id": error["analysis_row_id"],
            "question_id": error["question_id"],
            "packet_backbone": error["packet_backbone"],
            "condition_id": error["condition_id"],
            "store_id": frow["store_id"],
            "retriever_id": frow["retriever_id"],
            "category_name": frow["category_name"],
            "judge_label": error["judge_label"],
            "evidence_eligible": frow["evidence_eligible"],
            "store_availability_state": frow["store_availability_state"],
            "source_reach_state": frow["source_reach_state"],
            "model_observation_state": frow["annotated_evidence_observation_state"],
            "complete_acquisition_state": frow["complete_acquisition_state"],
            "selection_state": frow["selection_state"],
            "final_bundle_state": frow["final_bundle_state"],
            "diagnostic_retrieval_state": _diagnostic_error_state(frow),
            "hit_native_cap": frow["hit_native_cap"],
            "stop_annotation_alignment": frow["stop_annotation_alignment"],
            "storage_cause_decision": storage["storage_cause_decision"],
            "retrieval_cause_decision": "diagnostic_only_no_automatic_causal_assignment",
            "causal_sufficiency": "not_established",
            "gold_annotation_is_diagnostic_not_causal": True,
        }
        error_links.append(link)
        error_link_by_case[str(error["case_id"])] = link

    after_states: list[dict[str, Any]] = []
    for state in after_storage:
        updated = dict(state)
        link = error_link_by_case.get(str(state["case_id"]))
        if link is None:
            updated["retrieval_audit_applicable"] = False
            updated["retrieval_audit_decision"] = "not_applicable"
            updated["retrieval_diagnostic_state"] = "not_applicable"
        else:
            updated["retrieval_audit_applicable"] = True
            updated["retriever_reach_state"] = "indeterminate" if not link["evidence_eligible"] else "reached" if link["source_reach_state"] == "reached" else "not_reached"
            updated["model_observation_state"] = "indeterminate" if not link["evidence_eligible"] else "observed" if link["model_observation_state"] == "observed" else "not_observed"
            updated["retrieval_audit_decision"] = link["retrieval_cause_decision"]
            updated["retrieval_diagnostic_state"] = link["diagnostic_retrieval_state"]
        updated["retrieval_audit_protocol_version"] = PROTOCOL_VERSION
        after_states.append(updated)

    return {
        "retrieval-funnel": funnel,
        "stage-transitions": _stage_transition_rows(funnel),
        "r1-diagnostics": r1_rows,
        "r2-diagnostics": r2_rows,
        "r3-diagnostics": r3_rows,
        "controlled-comparisons": _comparison_rows(funnel),
        "cross-backbone-comparisons": _cross_backbone_rows(funnel),
        "strict-error-retrieval-linkage": error_links,
        "root-cause-state-register-after-retrieval": after_states,
        "retriever-summary": summary,
        "retriever-category-summary": category_summary,
    }


def _assert_no_forbidden_fields(tables: Mapping[str, Sequence[Mapping[str, Any]]]) -> None:
    for table, rows in tables.items():
        for row in rows:
            for key in row:
                lowered = key.casefold()
                _require(lowered not in FORBIDDEN_OUTPUT_FIELDS, f"Forbidden public field in {table}: {key}")
                _require(not any(fragment in lowered for fragment in SECRET_FIELD_FRAGMENTS), f"Secret-like public field in {table}: {key}")


def _schema(tables: Mapping[str, Sequence[Mapping[str, Any]]]) -> dict[str, Any]:
    return {
        "protocol_version": PROTOCOL_VERSION,
        "primary_unit": "backbone_id x condition_id x question_id retrieval path",
        "path_denominator": EXPECTED_PATHS,
        "eligible_path_denominator": EXPECTED_ELIGIBLE_PATHS,
        "strict_error_path_denominator": EXPECTED_ERROR_PATHS,
        "causal_rule": "gold annotations diagnose trace transitions but never establish causal sufficiency automatically",
        "cap_rule": "native cap hit is a process state, not an automatic failure",
        "state_update_scope": ["retriever_reach_state", "model_observation_state"],
        "diagnostic_terms": {
            "annotated_evidence_observation_state": "whether at least one official annotated locator or span was exposed to the retriever; it does not assert decisiveness or semantic sufficiency",
            "new_annotated_gold_search_count": "ranked-search actions that added at least one previously unseen official annotated locator",
            "no_new_annotated_gold_search_count": "ranked-search actions that added no previously unseen official annotated locator; this does not imply irrelevance",
            "nonempty_bundle_without_annotated_gold": "a nonempty final bundle with no official annotated locator; this does not imply that its contents are irrelevant",
        },
        "tables": {name: {"rows": len(rows), "fields": sorted(rows[0])} for name, rows in tables.items()},
    }


def _source_manifest(repo_root: Path) -> dict[str, Any]:
    stage_rows = [row for row in _read_jsonl(repo_root / STAGE_A_PATH) if row.get("condition_id") in SELECTIVE_CONDITIONS]
    relative_paths = [
        STAGE_A_PATH,
        *GOLD_PATHS,
        *STORE_MANIFEST_PATHS,
        f"{STAGE1_PATH}/strict-error-cases.jsonl",
        f"{STORAGE_PATH}/storage-outcome-linkage.jsonl",
        f"{STORAGE_PATH}/case-storage-linkage.jsonl",
        f"{STORAGE_PATH}/root-cause-state-register-after-storage.jsonl",
        f"{STORAGE_PATH}/audit.json",
        f"{STORAGE_PATH}/RQ5-STORAGE-AUDIT.PASSED",
        *_ordered_unique(str(row["source_record_path"]) for row in stage_rows),
    ]
    files = [
        {"path": relative, "sha256": _sha256_file(repo_root / relative), "bytes": (repo_root / relative).stat().st_size}
        for relative in relative_paths
    ]
    body = {"protocol_version": PROTOCOL_VERSION, "files": files}
    body["source_manifest_id"] = "rq5-retrieval-sources-" + sha256_bytes(canonical_json_bytes(body))
    return body


def audit_rq5_retrieval_output(*, repo_root: Path, output_dir: Path) -> dict[str, Any]:
    repo_root, output_dir = Path(repo_root).resolve(), Path(output_dir).resolve()
    _require(output_dir.is_dir() and not output_dir.is_symlink(), "Retrieval-audit output is unsafe")
    tables = {name: _read_jsonl(output_dir / f"{name}.jsonl") for name in TABLES}
    _assert_no_forbidden_fields(tables)
    expected_counts = {
        "retrieval-funnel": EXPECTED_PATHS,
        "stage-transitions": 72,
        "r1-diagnostics": 360,
        "r2-diagnostics": 240,
        "r3-diagnostics": 120,
        "controlled-comparisons": 600,
        "cross-backbone-comparisons": 360,
        "strict-error-retrieval-linkage": EXPECTED_ERROR_PATHS,
        "root-cause-state-register-after-retrieval": EXPECTED_STATE_ROWS,
        "retriever-summary": 12,
        "retriever-category-summary": 48,
    }
    _require({name: len(rows) for name, rows in tables.items()} == expected_counts, "Retrieval output counts differ")
    funnel = tables["retrieval-funnel"]
    _require(Counter(row["retriever_id"] for row in funnel) == Counter(EXPECTED_RETRIEVER_PATHS), "Published retriever census differs")
    _require(sum(row["evidence_eligible"] for row in funnel) == EXPECTED_ELIGIBLE_PATHS, "Published eligible-path count differs")
    _require(all(row["gold_annotation_is_diagnostic_not_causal"] for row in funnel), "Causal guard differs")
    _require(all(row["native_cap_is_not_automatic_failure"] for row in funnel), "Cap guard differs")
    _require(all(row["search_replay_verified"] is True for row in funnel if row["retriever_id"] in {"R2", "R3"}), "Ranked replay verification differs")
    _require(sum(row["strict_score"] == 0.0 for row in funnel) == EXPECTED_ERROR_PATHS, "Selective Strict-error count differs")
    bundle_diagnostics = {
        retriever: {
            "eligible_empty": sum(row["evidence_eligible"] and row["empty_bundle"] for row in funnel if row["retriever_id"] == retriever),
            "ineligible_empty": sum((not row["evidence_eligible"]) and row["empty_bundle"] for row in funnel if row["retriever_id"] == retriever),
            "nonempty_without_annotated_gold": sum(bool(row["nonempty_bundle_without_annotated_gold"]) for row in funnel if row["retriever_id"] == retriever),
        }
        for retriever in ("R1", "R2", "R3")
    }
    _require(bundle_diagnostics == {
        "R1": {"eligible_empty": 5, "ineligible_empty": 0, "nonempty_without_annotated_gold": 25},
        "R2": {"eligible_empty": 7, "ineligible_empty": 2, "nonempty_without_annotated_gold": 34},
        "R3": {"eligible_empty": 1, "ineligible_empty": 0, "nonempty_without_annotated_gold": 18},
    }, "Bundle annotation diagnostics differ")

    states = tables["root-cause-state-register-after-retrieval"]
    _require(sum(row["retrieval_audit_applicable"] for row in states) == EXPECTED_ERROR_PATHS, "Retrieval-state applicability differs")
    # This stage must not consume ownership of any downstream state.
    previous = {row["case_id"]: row for row in _read_jsonl(repo_root / STORAGE_PATH / "root-cause-state-register-after-storage.jsonl")}
    protected = (
        "evidence_retention_state", "final_input_sufficiency_state", "answerer_utilisation_state",
        "parent_e2_bundle_state", "parent_e6_bundle_state", "fusion_operation_state",
        "long_context_utilisation_state", "evaluation_agreement_state", "primary_cause",
        "secondary_causes", "attribution_status", "attribution_strength", "causal_sufficiency",
    )
    for row in states:
        before = previous[row["case_id"]]
        _require(all(row[field] == before[field] for field in protected), "Retrieval stage changed a downstream or causal field")

    rebuilt = _build_core(repo_root)
    for name in TABLES:
        _require(_jsonl_payload(rebuilt[name]) == (output_dir / f"{name}.jsonl").read_bytes(), f"Independent rebuild differs: {name}")
        _require(_csv_payload(rebuilt[name]) == (output_dir / f"{name}.csv").read_bytes(), f"CSV/JSONL parity differs: {name}")
    _require(_read_json(output_dir / "schema.json") == _schema(tables), "Retrieval schema differs")
    source_manifest = _read_json(output_dir / "source-manifest.json")
    _require(source_manifest == _source_manifest(repo_root), "Retrieval source manifest differs")
    output_sha256 = {
        path.name: _sha256_file(path)
        for path in sorted(output_dir.iterdir(), key=lambda path: path.name)
        if path.name not in {"audit.json", "RQ5-RETRIEVAL-AUDIT.PASSED"}
    }
    cap_rows = [row for row in funnel if row["hit_native_cap"]]
    body = {
        "protocol_version": PROTOCOL_VERSION,
        "status": "passed",
        "counts": expected_counts,
        "retriever_census": dict(sorted(Counter(row["retriever_id"] for row in funnel).items())),
        "eligible_paths": EXPECTED_ELIGIBLE_PATHS,
        "strict_error_paths": EXPECTED_ERROR_PATHS,
        "eligible_strict_error_paths": sum(row["evidence_eligible"] for row in tables["strict-error-retrieval-linkage"]),
        "ranked_replay_paths_verified": sum(row["search_replay_verified"] is True for row in funnel),
        "native_cap_hits": len(cap_rows),
        "native_cap_hits_with_strict_correct": sum(row["strict_score"] == 1.0 for row in cap_rows),
        "bundle_annotation_diagnostics": bundle_diagnostics,
        "retrieval_causes_automatically_assigned": 0,
        "downstream_states_modified": 0,
        "output_sha256": output_sha256,
        "source_manifest_id": source_manifest["source_manifest_id"],
    }
    body["audit_id"] = "rq5-retrieval-audit-" + sha256_bytes(canonical_json_bytes(body))
    return body


def build_rq5_retrieval_audit(*, repo_root: Path, output_dir: Path) -> dict[str, Any]:
    repo_root, output_dir = Path(repo_root).resolve(), Path(output_dir).resolve()
    _require(repo_root.is_dir() and not repo_root.is_symlink(), "Repository root is unsafe")
    _require(not output_dir.exists(), "Retrieval-audit output already exists")
    output_dir.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=".rq5-retrieval-", dir=output_dir.parent))
    try:
        tables = _build_core(repo_root)
        _assert_no_forbidden_fields(tables)
        for name in TABLES:
            _write(staging / f"{name}.jsonl", _jsonl_payload(tables[name]))
            _write(staging / f"{name}.csv", _csv_payload(tables[name]))
        _write(staging / "schema.json", json.dumps(_schema(tables), indent=2, sort_keys=True).encode() + b"\n")
        _write(staging / "source-manifest.json", json.dumps(_source_manifest(repo_root), indent=2, sort_keys=True).encode() + b"\n")
        readme = (
            "# RQ5 Section 5.6.3 retrieval audit\n\n"
            "This offline artifact reconstructs all 720 independent E1--E6 retrieval paths. "
            "R2 and R3 actions are replayed against the frozen local indexes with their recorded "
            "query terms, date filters, and seen-state. Gold annotations define diagnostic funnel "
            "coordinates; they do not automatically establish a causal retrieval failure. A native "
            "cap hit is reported as a process state, never as an automatic failure. Only retriever "
            "reach and model-observation fields are updated in the 250-case state register; downstream "
            "evidence-retention, sufficiency, Answerer, fusion, long-context, and evaluation states are unchanged. "
            "The observation state means exposure of official annotated evidence, not decisive or sufficient evidence. "
            "A ranked search with no newly observed annotated locator may still be semantically useful. Likewise, a "
            "nonempty bundle without an annotated locator is not labelled irrelevant. Condition and category summaries "
            "freeze these descriptive diagnostics explicitly.\n"
        )
        _write(staging / "README.md", readme.encode("utf-8"))
        os.replace(staging, output_dir)
        audit = audit_rq5_retrieval_output(repo_root=repo_root, output_dir=output_dir)
        _write(output_dir / "audit.json", json.dumps(audit, indent=2, sort_keys=True).encode() + b"\n")
        marker = {
            "protocol_version": PROTOCOL_VERSION,
            "status": "passed",
            "audit_id": audit["audit_id"],
            "audit_sha256": _sha256_file(output_dir / "audit.json"),
        }
        _write(output_dir / "RQ5-RETRIEVAL-AUDIT.PASSED", json.dumps(marker, indent=2, sort_keys=True).encode() + b"\n")
        return audit
    except Exception:
        if staging.exists():
            shutil.rmtree(staging)
        if output_dir.exists() and not (output_dir / "RQ5-RETRIEVAL-AUDIT.PASSED").exists():
            shutil.rmtree(output_dir)
        raise


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=Path.cwd())
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--audit-only", action="store_true")
    args = parser.parse_args(argv)
    result = audit_rq5_retrieval_output(repo_root=args.repo_root, output_dir=args.output_dir) if args.audit_only else build_rq5_retrieval_audit(repo_root=args.repo_root, output_dir=args.output_dir)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
