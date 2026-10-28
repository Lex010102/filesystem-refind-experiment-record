"""Offline S1--S3 storage audit for Chapter 5, Section 5.6.2.

The audit deliberately separates three questions:

1. Did a store preserve the frozen source representation?
2. Is the information in that representation sufficient for the benchmark answer?
3. Can a Strict-noncorrect answer be attributed directly to a representation loss?

The first two questions are evaluated once per question and store.  They are
not multiplied by backbone or retrieval condition.  Answer outcomes are joined
only after the question-store register has been frozen.
"""

from __future__ import annotations

import argparse
import hashlib
import itertools
import json
import math
import os
import shutil
import statistics
import tempfile
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from .chapter5_stage_b import _csv_payload, _jsonl_payload, _read_json, _read_jsonl, _require, _sha256_file, _write
from .evidence import EvidenceValidationError, canonical_json_bytes, sha256_bytes
from .r1_inputs import load_r1_store
from .r3_inputs import load_r3_corpus


PROTOCOL_VERSION = "chapter5-main60-rq5-storage-audit-v1"
REVIEW_PROTOCOL_VERSION = "chapter5-rq5-storage-review-v1"
S2_REVIEW_PROTOCOL_VERSION = "chapter5-rq5-s2-routing-review-v1"
STORES = ("S1", "S2", "S3")
SELECTIVE_CONDITIONS = ("E1", "E2", "E3", "E4", "E5", "E6")
STORE_BY_CONDITION = {"E1": "S1", "E2": "S1", "E3": "S2", "E4": "S2", "E5": "S3", "E6": "S3"}
EXPECTED_QUESTIONS = 60
EXPECTED_ELIGIBLE = 58
EXPECTED_GOLD_ASSOCIATIONS = 82
EXPECTED_UNIQUE_GOLD_LOCATORS = 68
EXPECTED_S2_ROUTING_UNITS = 79
EXPECTED_S2_ROUTING_CLASSES = {
    "aligned": 55,
    "partially_aligned": 6,
    "misleading": 18,
    "ambiguous": 0,
}
EXPECTED_S2_QUESTION_CLASSES = {
    "all_aligned": 36,
    "partially_aligned_no_misleading": 5,
    "at_least_one_misleading": 17,
}
EXPECTED_ERROR_PATHS = 205
EXPECTED_ELIGIBLE_ERROR_PATHS = 191
EXPECTED_ALL_PIPELINE_SHARED_INSUFFICIENCY_ERROR_PATHS = 14
EXPECTED_STORE_ERROR_PATHS = {"S1": 70, "S2": 71, "S3": 64}
EXPECTED_ELIGIBLE_STORE_ERROR_PATHS = {"S1": 65, "S2": 66, "S3": 60}
EXPECTED_S3_CLASSES = {
    "preserved_exactly": 48,
    "compressed_but_sufficient": 5,
    "partially_preserved": 4,
    "missing": 0,
    "distorted": 0,
    "stale_or_conflicting": 1,
}
EXPECTED_S3_SOURCE_FIDELITY = {
    "faithful_to_source": 51,
    "compressed_but_source_faithful": 5,
    "source_conflict_preserved": 1,
    "shared_renderer_detail_loss": 1,
}
EXPECTED_S3_REFERENCE_SUPPORT = {
    "sufficient": 50,
    "partial": 4,
    "available_but_conflicting": 1,
    "source_reference_mismatch": 3,
}
EXPECTED_S3_SEMANTIC = {"full": 48, "sufficient": 6, "partial": 4}
EXPECTED_S3_TEMPORAL = {"exact": 20, "ambiguous_or_lost": 2, "not_applicable": 36}
EXPECTED_S3_GRANULARITY = {"exact": 49, "sufficient": 5, "overcompressed": 2, "overbroad": 2}
SHARED_REPRESENTATION_INSUFFICIENCY_QUESTION = "conv-50-q002"
# Backward-compatible symbol for tests/importers; this is not a store-specific loss.
DIRECT_STORAGE_LOSS_QUESTION = SHARED_REPRESENTATION_INSUFFICIENCY_QUESTION
INELIGIBLE_QUESTIONS = {"conv-50-q040", "conv-50-q043"}

TABLES = (
    "store-integrity",
    "s1-s2-equivalence",
    "s2-routing",
    "s2-routing-session-review",
    "s3-fact-preservation",
    "storage-fidelity",
    "storage-outcome-linkage",
    "case-storage-linkage",
    "root-cause-state-register-after-storage",
    "storage-summary",
)

QUESTION_PATHS = (
    "experiments/locomo-conv50-v1/question-sets/main-40-input.jsonl",
    "experiments/locomo-conv50-v1/question-sets-main60-v2/extension-20-input.jsonl",
)
GOLD_PATHS = (
    "experiments/locomo-conv50-v1/question-sets/main-40-gold.jsonl",
    "experiments/locomo-conv50-v1/question-sets-main60-v2/extension-20-gold.jsonl",
)
CANONICAL_PATH = "data/processed/conv-50.jsonl"
S2_PATH_MAP = "experiments/locomo-conv50-v1/manifests/s2-foldered-path-map.json"
COMPOSITION_PATH = "experiments/locomo-conv50-v1/question-sets-main60-v2/main-60-composition.json"
REVIEW_PATH = "docs/analysis/reviews/chapter5-rq5-storage-review-v1.json"
S2_REVIEW_PATH = "docs/analysis/reviews/chapter5-rq5-s2-routing-review-v1.json"
STAGE_A_PATH = "artifacts/chapter5-main60-analysis-v1/stage-a/master-table.jsonl"
STAGE1_PATH = "artifacts/chapter5-main60-analysis-v1/rq5-root-cause-index"

FORBIDDEN_OUTPUT_FIELDS = {
    "question", "question_text", "answer", "answer_text", "reference_answer",
    "candidate_answer", "evidence", "evidence_text", "prompt", "rationale",
    "short_reason", "judge_reason", "api_key", "authorization", "secret",
}


def _read_lines(path: Path) -> list[dict[str, Any]]:
    return _read_jsonl(path)


def _load_questions(repo_root: Path) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]]]:
    inputs = [row for rel in QUESTION_PATHS for row in _read_lines(repo_root / rel)]
    golds = [row for rel in GOLD_PATHS for row in _read_lines(repo_root / rel)]
    _require(len(inputs) == EXPECTED_QUESTIONS and len(golds) == EXPECTED_QUESTIONS, "Main-60 question count differs")
    _require(len({row["question_id"] for row in inputs}) == EXPECTED_QUESTIONS, "Question IDs repeat")
    gold_by_qid = {str(row["question_id"]): row for row in golds}
    _require(set(gold_by_qid) == {str(row["question_id"]) for row in inputs}, "Input/gold identities differ")
    composition = _read_json(repo_root / COMPOSITION_PATH)
    order = composition.get("question_order")
    _require(isinstance(order, list) and len(order) == EXPECTED_QUESTIONS, "Main-60 composition differs")
    by_qid = {str(row["question_id"]): row for row in inputs}
    _require([int(row["global_position"]) for row in order] == list(range(1, 61)), "Main-60 global positions differ")
    ordered = [by_qid[str(row["question_id"])] for row in order]
    return ordered, gold_by_qid


def _load_review(repo_root: Path, eligible_qids: set[str]) -> dict[str, dict[str, Any]]:
    payload = _read_json(repo_root / REVIEW_PATH)
    _require(payload.get("protocol_version") == REVIEW_PROTOCOL_VERSION, "Storage-review protocol differs")
    _require(payload.get("review_blind_to_answer_outcomes") is True, "Storage review must be outcome-blind")
    _require(payload.get("review_passes") == 2, "Storage review must record two completed passes")
    _require(payload.get("whole_store_alternative_support_checked_for_every_row") is True, "Storage review must include whole-store alternate-support checks")
    _require(set(payload.get("terminal_classes", [])) == set(EXPECTED_S3_CLASSES), "Storage-review class vocabulary differs")
    rows = payload.get("rows")
    _require(isinstance(rows, list) and len(rows) == EXPECTED_ELIGIBLE, "Storage-review row count differs")
    by_qid = {str(row.get("question_id")): dict(row) for row in rows if isinstance(row, dict)}
    _require(set(by_qid) == eligible_qids, "Storage review does not cover exactly the eligible questions")
    _require(len(by_qid) == len(rows), "Storage review repeats a question")
    for row in by_qid.values():
        row["_review_passes"] = int(payload["review_passes"])
        row["_whole_store_alternative_support_checked"] = bool(payload["whole_store_alternative_support_checked_for_every_row"])
    forbidden = {"backbone", "condition", "judge_label", "strict_score", "token_f1", "evidence_recall"}
    for row in rows:
        _require(not (set(row) & forbidden), "Storage review leaks outcome fields")
        _require(row["class"] in EXPECTED_S3_CLASSES, "Unknown S3 preservation class")
        _require(row["semantic_fidelity"] in {"full", "sufficient", "partial"}, "Unknown S3 semantic state")
        _require(row["temporal_fidelity"] in {"exact", "ambiguous_or_lost", "not_applicable"}, "Unknown S3 temporal state")
        _require(row["granularity"] in {"exact", "sufficient", "overcompressed", "overbroad"}, "Unknown S3 granularity")
        _require(isinstance(row["representation_decisive_loss"], bool), "Invalid decisive-loss flag")
        _require(isinstance(row["curator_introduced_decisive_loss"], bool), "Invalid curator-loss flag")
    _require(Counter(row["class"] for row in rows) == Counter(EXPECTED_S3_CLASSES), "S3 class census differs")
    _require(Counter(row["semantic_fidelity"] for row in rows) == Counter(EXPECTED_S3_SEMANTIC), "S3 semantic census differs")
    _require(Counter(row["temporal_fidelity"] for row in rows) == Counter(EXPECTED_S3_TEMPORAL), "S3 temporal census differs")
    _require(Counter(row["granularity"] for row in rows) == Counter(EXPECTED_S3_GRANULARITY), "S3 granularity census differs")
    _require(
        {qid for qid, row in by_qid.items() if row["representation_decisive_loss"]}
        == {SHARED_REPRESENTATION_INSUFFICIENCY_QUESTION},
        "Shared representation-insufficiency set differs",
    )
    _require(not any(row["curator_introduced_decisive_loss"] for row in rows), "Review claims an unsupported curator-introduced decisive loss")
    return by_qid


def _load_s2_routing_review(
    repo_root: Path,
    *,
    eligible_qids: set[str],
    gold_by_qid: Mapping[str, Mapping[str, Any]],
    folder_by_session: Mapping[int, str],
) -> list[dict[str, Any]]:
    """Load the outcome-blind semantic audit of S2's directory assignment."""

    payload = _read_json(repo_root / S2_REVIEW_PATH)
    _require(payload.get("protocol_version") == S2_REVIEW_PROTOCOL_VERSION, "S2 routing-review protocol differs")
    _require(payload.get("review_blind_to_answer_outcomes") is True, "S2 routing review must be outcome-blind")
    rows = payload.get("rows")
    _require(isinstance(rows, list) and len(rows) == EXPECTED_S2_ROUTING_UNITS, "S2 routing-review row count differs")
    forbidden = {"backbone", "condition", "judge_label", "strict_score", "token_f1", "evidence_recall"}
    observed: set[tuple[str, int]] = set()
    for row in rows:
        _require(isinstance(row, dict), "Invalid S2 routing-review row")
        _require(not (set(row) & forbidden), "S2 routing review leaks outcome fields")
        qid, session = str(row.get("question_id")), int(row.get("session_index"))
        _require(qid in eligible_qids, "S2 routing review contains an ineligible question")
        _require((qid, session) not in observed, "S2 routing review repeats a question-session unit")
        observed.add((qid, session))
        _require(row.get("folder") == folder_by_session[session], "S2 routing review folder differs from the frozen path map")
        _require(row.get("routing_alignment") in EXPECTED_S2_ROUTING_CLASSES, "Unknown S2 routing label")

    expected = {
        (qid, int(session))
        for qid in eligible_qids
        for session in set(gold_by_qid[qid]["gold_evidence_sessions"])
    }
    _require(observed == expected, "S2 routing review does not cover exactly the eligible question-session units")
    _require(Counter(row["routing_alignment"] for row in rows) == Counter(EXPECTED_S2_ROUTING_CLASSES), "S2 routing-label census differs")
    return [dict(row) for row in rows]


def _load_canonical(repo_root: Path) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]]]:
    rows = _read_lines(repo_root / CANONICAL_PATH)
    _require(len(rows) == 568, "Canonical turn count differs")
    by_locator = {str(row["locator"]): row for row in rows}
    _require(len(by_locator) == 568, "Canonical locators repeat")
    return rows, by_locator


def _support_state(qid: str, *, eligible: bool) -> tuple[str, str, bool]:
    if not eligible:
        return "indeterminate", "no_gold_annotation", False
    if qid == "conv-50-q002":
        return "partial", "renderer_excluded_query", True
    if qid in {"conv-50-q008", "conv-50-q051", "conv-50-q068"}:
        return "partial", "gold_source_under_specification", False
    if qid == "conv-50-q052":
        return "available_but_conflicting", "source_conflict_preserved", False
    if qid in {"conv-50-q089", "conv-50-q126", "conv-50-q152"}:
        return "available_with_reference_entity_mismatch", "gold_source_reference_mismatch", False
    return "available", "none", False


def _s3_availability(review: Mapping[str, Any]) -> str:
    if review["gap_origin"] == "gold_source_reference_mismatch":
        return "available_with_reference_entity_mismatch"
    if review["class"] in {"preserved_exactly", "compressed_but_sufficient"}:
        return "available"
    if review["class"] == "stale_or_conflicting":
        return "available_but_conflicting"
    return "partial"


def _s3_source_fidelity(qid: str, review: Mapping[str, Any]) -> str:
    """Separate fidelity to the source from support for the benchmark reference."""

    if qid == SHARED_REPRESENTATION_INSUFFICIENCY_QUESTION:
        return "shared_renderer_detail_loss"
    if review["class"] == "compressed_but_sufficient":
        return "compressed_but_source_faithful"
    if review["class"] == "stale_or_conflicting":
        return "source_conflict_preserved"
    if review["class"] in {"missing", "distorted"}:
        return str(review["class"])
    # q008/q051/q068 are faithful to an under-specified source even though the
    # source is insufficient for the benchmark reference.
    return "faithful_to_source"


def _reference_support_sufficiency(qid: str) -> str:
    if qid in {"conv-50-q002", "conv-50-q008", "conv-50-q051", "conv-50-q068"}:
        return "partial"
    if qid == "conv-50-q052":
        return "available_but_conflicting"
    if qid in {"conv-50-q089", "conv-50-q126", "conv-50-q152"}:
        return "source_reference_mismatch"
    return "sufficient"


def _file_body(payload: bytes) -> bytes:
    boundary = b"---\n\n"
    _require(payload.startswith(b"---\n") and boundary in payload, "Session file lacks frontmatter boundary")
    return payload.split(boundary, 1)[1]


def _build_core(repo_root: Path) -> dict[str, list[dict[str, Any]]]:
    questions, gold_by_qid = _load_questions(repo_root)
    eligible_qids = {qid for qid, row in gold_by_qid.items() if row["gold_evidence_locators"]}
    _require(len(eligible_qids) == EXPECTED_ELIGIBLE, "Evidence-eligible count differs")
    _require(set(gold_by_qid) - eligible_qids == INELIGIBLE_QUESTIONS, "Ineligible question identities differ")
    review = _load_review(repo_root, eligible_qids)
    canonical, canonical_by_locator = _load_canonical(repo_root)

    s1 = load_r1_store(repo_root, "s1")
    s2 = load_r1_store(repo_root, "s2")
    s3 = load_r1_store(repo_root, "s3")
    corpus = load_r3_corpus(repo_root)
    s2_map = _read_json(repo_root / S2_PATH_MAP)
    path_entries = list(s2_map["entries"])
    _require(len(path_entries) == 30, "S2 path map must contain 30 sessions")
    s2_path_by_session: dict[int, str] = {}
    folder_by_session: dict[int, str] = {}
    for entry in path_entries:
        basename = str(entry["basename"])
        session = int(basename.removeprefix("session-").removesuffix(".md"))
        s2_path_by_session[session] = str(entry["s2_path"])
        folder_by_session[session] = str(entry["s2_path"]).split("/", 1)[0]
    folder_sizes = Counter(folder_by_session.values())
    s2_review = _load_s2_routing_review(
        repo_root,
        eligible_qids=eligible_qids,
        gold_by_qid=gold_by_qid,
        folder_by_session=folder_by_session,
    )
    s2_review_by_question: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in s2_review:
        s2_review_by_question[str(row["question_id"])].append(row)
    s2_review_table = [
        {
            "protocol_version": PROTOCOL_VERSION,
            "question_id": str(row["question_id"]),
            "session_id": f"session_{int(row['session_index'])}",
            "session_index": int(row["session_index"]),
            "s2_topic_directory": str(row["folder"]),
            "routing_alignment": str(row["routing_alignment"]),
            "routing_reason_code": (
                "direct_topic_match" if row["routing_alignment"] == "aligned"
                else "secondary_or_contextual_match" if row["routing_alignment"] == "partially_aligned"
                else "dominant_topic_mismatch" if row["routing_alignment"] == "misleading"
                else "insufficient_local_topic_signal"
            ),
            "review_blind_to_answer_outcomes": True,
        }
        for row in s2_review
    ]

    # Recompute S1--S2 byte and body equality instead of trusting manifests.
    equivalence: list[dict[str, Any]] = []
    for session in range(1, 31):
        s1_rel = f"session-{session:02d}.md"
        s2_rel = s2_path_by_session[session]
        p1, p2 = s1.root / s1_rel, s2.root / s2_rel
        b1, b2 = p1.read_bytes(), p2.read_bytes()
        equivalence.append({
            "protocol_version": PROTOCOL_VERSION,
            "session_id": f"session_{session}",
            "s1_path": s1_rel,
            "s2_path": s2_rel,
            "s2_topic_directory": folder_by_session[session],
            "bytes": len(b1),
            "s1_sha256": hashlib.sha256(b1).hexdigest(),
            "s2_sha256": hashlib.sha256(b2).hexdigest(),
            "byte_equal": b1 == b2,
            "body_equal": _file_body(b1) == _file_body(b2),
            "turn_count": sum(1 for row in canonical if int(row["session_index"]) == session),
        })
    _require(all(row["byte_equal"] and row["body_equal"] for row in equivalence), "S1/S2 content differs")
    _require(sum(row["turn_count"] for row in equivalence) == 568, "S1/S2 turn count differs")

    all_gold_locators = [loc for gold in gold_by_qid.values() for loc in gold["gold_evidence_locators"]]
    _require(len(all_gold_locators) == EXPECTED_GOLD_ASSOCIATIONS, "Gold locator association count differs")
    unique_gold_locators = set(all_gold_locators)
    _require(len(unique_gold_locators) == EXPECTED_UNIQUE_GOLD_LOCATORS, "Unique gold locator count differs")
    s3_body_locators = {loc for unit in corpus.units for loc in unit.source_locators}
    _require(unique_gold_locators <= s3_body_locators, "A Main-60 gold locator is absent from S3 body")
    gold_units = [unit for unit in corpus.units if set(unit.source_locators) & unique_gold_locators]

    excluded_media_keys = ("img_url", "query", "re-download")
    has_excluded_media = lambda row: any(
        row["media"].get(key) not in (None, "", [], {}, False)
        for key in excluded_media_keys
    )
    media_turn_counts = {
        key: sum(row["media"].get(key) not in (None, "", [], {}, False) for row in canonical)
        for key in excluded_media_keys
    }
    gold_media_association_counts = {
        key: sum(canonical_by_locator[loc]["media"].get(key) not in (None, "", [], {}, False) for loc in all_gold_locators)
        for key in excluded_media_keys
    }
    gold_media_question_counts = {
        key: sum(
            any(canonical_by_locator[loc]["media"].get(key) not in (None, "", [], {}, False) for loc in gold["gold_evidence_locators"])
            for gold in gold_by_qid.values()
        )
        for key in excluded_media_keys
    }
    total_query_turns = media_turn_counts["query"]
    total_excluded_media_turns = sum(has_excluded_media(row) for row in canonical)
    gold_query_associations = sum(bool(canonical_by_locator[loc]["media"].get("query")) for loc in all_gold_locators)
    gold_excluded_media_associations = sum(has_excluded_media(canonical_by_locator[loc]) for loc in all_gold_locators)
    gold_query_questions = sum(
        any(canonical_by_locator[loc]["media"].get("query") for loc in gold["gold_evidence_locators"])
        for gold in gold_by_qid.values()
    )
    gold_excluded_media_questions = sum(
        any(has_excluded_media(canonical_by_locator[loc]) for loc in gold["gold_evidence_locators"])
        for gold in gold_by_qid.values()
    )

    integrity = [
        {
            "protocol_version": PROTOCOL_VERSION, "store_id": "S1", "source_kind": "raw_flat",
            "files": s1.snapshot.file_count, "directories": 0, "bytes": s1.snapshot.total_bytes,
            "source_turns": 568, "h2_groups": None, "body_fact_units": None,
            "body_locator_mentions": 568, "body_unique_locators": 568,
            "frontmatter_locator_mentions_excluded": 0, "missing_source_locators": 0,
            "all_main60_gold_locators_present": True, "gold_locator_coverage": 1.0,
            "canonical_text_caption_preserved": True, "query_metadata_preserved": False,
            "tree_sha256": s1.snapshot.tree_sha256, "content_identity": s2_map["source_content_sha256"],
        },
        {
            "protocol_version": PROTOCOL_VERSION, "store_id": "S2", "source_kind": "raw_foldered",
            "files": s2.snapshot.file_count, "directories": len(folder_sizes), "bytes": s2.snapshot.total_bytes,
            "source_turns": 568, "h2_groups": None, "body_fact_units": None,
            "body_locator_mentions": 568, "body_unique_locators": 568,
            "frontmatter_locator_mentions_excluded": 0, "missing_source_locators": 0,
            "all_main60_gold_locators_present": True, "gold_locator_coverage": 1.0,
            "canonical_text_caption_preserved": True, "query_metadata_preserved": False,
            "tree_sha256": s2.snapshot.tree_sha256, "content_identity": s2_map["target_content_sha256"],
        },
        {
            "protocol_version": PROTOCOL_VERSION, "store_id": "S3", "source_kind": "agent_curated",
            "files": s3.snapshot.file_count, "directories": 0, "bytes": s3.snapshot.total_bytes,
            "source_turns": None, "h2_groups": corpus.stats.h2_group_count,
            "body_fact_units": corpus.stats.fact_unit_count,
            "body_locator_mentions": corpus.stats.body_locator_mentions,
            "body_unique_locators": corpus.stats.unique_body_locators,
            "frontmatter_locator_mentions_excluded": corpus.stats.frontmatter_locator_mentions_excluded,
            "missing_source_locators": corpus.stats.missing_source_locator_count,
            "all_main60_gold_locators_present": True, "gold_locator_coverage": 1.0,
            "canonical_text_caption_preserved": False, "query_metadata_preserved": False,
            "tree_sha256": s3.snapshot.tree_sha256, "content_identity": corpus.corpus_sha256,
        },
    ]

    routing: list[dict[str, Any]] = []
    s3_preservation: list[dict[str, Any]] = []
    fidelity: list[dict[str, Any]] = []
    for position, question in enumerate(questions, 1):
        qid = str(question["question_id"])
        gold = gold_by_qid[qid]
        locators = list(gold["gold_evidence_locators"])
        eligible = bool(locators)
        sessions = sorted({int(value) for value in gold["gold_evidence_sessions"]})
        folders = sorted({folder_by_session[value] for value in sessions})
        candidate_sessions = sum(folder_sizes[folder] for folder in folders) if folders else None
        reviewed_routes = s2_review_by_question.get(qid, [])
        _require(len(reviewed_routes) == len(sessions), "S2 routing-review question coverage differs")
        route_counts = Counter(row["routing_alignment"] for row in reviewed_routes)
        if not eligible:
            question_routing_class = "not_annotated"
        elif route_counts["misleading"]:
            question_routing_class = "at_least_one_misleading"
        elif route_counts["partially_aligned"] or route_counts["ambiguous"]:
            question_routing_class = "partially_aligned_no_misleading"
        else:
            question_routing_class = "all_aligned"
        routing.append({
            "protocol_version": PROTOCOL_VERSION,
            "question_id": qid,
            "run_position": position,
            "category": int(gold["category"]),
            "category_name": str(gold["category_name"]),
            "evidence_eligible": eligible,
            "gold_session_count": len(sessions),
            "gold_folder_count": len(folders),
            "gold_topic_directories": folders,
            "cross_folder_evidence_required": len(folders) > 1,
            "candidate_sessions_if_gold_folders_known": candidate_sessions,
            "candidate_pool_reduction_vs_flat": None if candidate_sessions is None else (30 - candidate_sessions) / 30,
            "aligned_gold_sessions": route_counts["aligned"],
            "partially_aligned_gold_sessions": route_counts["partially_aligned"],
            "misleading_gold_sessions": route_counts["misleading"],
            "ambiguous_gold_sessions": route_counts["ambiguous"],
            "question_routing_class": question_routing_class,
            "routing_finding": "not_adjudicable_without_gold" if not eligible else "cross_folder_required" if len(folders) > 1 else "single_folder_contains_gold_sessions",
        })

        if eligible:
            reviewed = review[qid]
            units_for_gold = [unit for unit in corpus.units if set(unit.source_locators) & set(locators)]
            required = set(locators)
            group_coverage: dict[str, set[str]] = defaultdict(set)
            file_coverage: dict[str, set[str]] = defaultdict(set)
            for unit in units_for_gold:
                group_coverage[unit.group_id].update(unit.source_locators)
                file_coverage[unit.relative_path].update(unit.source_locators)
            minimum_units = None
            for size in range(1, len(required) + 1):
                if any(
                    required <= set().union(*(set(unit.source_locators) for unit in combination))
                    for combination in itertools.combinations(units_for_gold, size)
                ):
                    minimum_units = size
                    break
            _require(minimum_units is not None, "S3 gold locators cannot be covered by linked units")
            s3_row = {
                "protocol_version": PROTOCOL_VERSION,
                "question_id": qid,
                "run_position": position,
                "category": int(gold["category"]),
                "category_name": str(gold["category_name"]),
                "evidence_eligible": True,
                "gold_locator_count": len(locators),
                "gold_source_locators": locators,
                "gold_locators_present_in_body": len({loc for loc in locators if loc in s3_body_locators}),
                "all_gold_locators_present_in_body": all(loc in s3_body_locators for loc in locators),
                "gold_linked_fact_unit_count": len(units_for_gold),
                "gold_linked_support_refs": [
                    {
                        "unit_id": unit.unit_id,
                        "path": unit.relative_path,
                        "line_start": unit.line_start,
                        "line_end": unit.line_end,
                        "content_sha256": unit.content_sha256,
                    }
                    for unit in units_for_gold
                ],
                "all_gold_colocated_in_one_fact_unit": any(required <= set(unit.source_locators) for unit in units_for_gold),
                "all_gold_colocated_in_one_h2_group": any(required <= values for values in group_coverage.values()),
                "all_gold_colocated_in_one_file": any(required <= values for values in file_coverage.values()),
                "minimum_fact_units_for_gold_locator_cover": minimum_units,
                "curated_form_class": reviewed["class"],
                "source_to_store_fidelity": _s3_source_fidelity(qid, reviewed),
                "reference_support_sufficiency": _reference_support_sufficiency(qid),
                "reference_semantic_fidelity": reviewed["semantic_fidelity"],
                "reference_temporal_fidelity": reviewed["temporal_fidelity"],
                "reference_granularity": reviewed["granularity"],
                "provenance_validity": "all_gold_locators_valid",
                "review_basis_ref_count": len(units_for_gold),
                "review_passes": reviewed["_review_passes"],
                "whole_store_alternative_support_checked": reviewed["_whole_store_alternative_support_checked"],
                "confidence": reviewed["confidence"],
                "issue_code": reviewed["issue_code"],
                "gap_origin": reviewed["gap_origin"],
                "representation_decisive_loss": reviewed["representation_decisive_loss"],
                "loss_scope": "shared_renderer_before_store_construction" if reviewed["representation_decisive_loss"] else "none",
                "store_specific_decisive_loss": False,
                "curator_introduced_decisive_loss": reviewed["curator_introduced_decisive_loss"],
            }
        else:
            s3_row = {
                "protocol_version": PROTOCOL_VERSION,
                "question_id": qid,
                "run_position": position,
                "category": int(gold["category"]),
                "category_name": str(gold["category_name"]),
                "evidence_eligible": False,
                "gold_locator_count": 0,
                "gold_source_locators": [],
                "gold_locators_present_in_body": 0,
                "all_gold_locators_present_in_body": None,
                "gold_linked_fact_unit_count": 0,
                "gold_linked_support_refs": [],
                "all_gold_colocated_in_one_fact_unit": None,
                "all_gold_colocated_in_one_h2_group": None,
                "all_gold_colocated_in_one_file": None,
                "minimum_fact_units_for_gold_locator_cover": None,
                "curated_form_class": "indeterminate",
                "source_to_store_fidelity": "indeterminate",
                "reference_support_sufficiency": "indeterminate",
                "reference_semantic_fidelity": "indeterminate",
                "reference_temporal_fidelity": "indeterminate",
                "reference_granularity": "indeterminate",
                "provenance_validity": "not_annotated",
                "review_basis_ref_count": 0,
                "review_passes": 0,
                "whole_store_alternative_support_checked": False,
                "confidence": "not_applicable",
                "issue_code": "no_gold_annotation",
                "gap_origin": "no_gold_annotation",
                "representation_decisive_loss": False,
                "loss_scope": "none",
                "store_specific_decisive_loss": False,
                "curator_introduced_decisive_loss": False,
            }
        s3_preservation.append(s3_row)

        support_state, support_origin, decisive = _support_state(qid, eligible=eligible)
        query_gold_count = sum(bool(canonical_by_locator[loc]["media"].get("query")) for loc in locators)
        source_rows = [canonical_by_locator[loc] for loc in locators]
        global_turn_span = None if len(source_rows) < 2 else max(int(row["global_turn_index"]) for row in source_rows) - min(int(row["global_turn_index"]) for row in source_rows)
        source_dates = [date.fromisoformat(str(row["session_date"])) for row in source_rows]
        date_span_days = None if len(source_dates) < 2 else (max(source_dates) - min(source_dates)).days
        for store_id in STORES:
            if store_id == "S3":
                availability = "indeterminate" if not eligible else _s3_availability(review[qid])
                curated_form_class = s3_row["curated_form_class"]
                source_fidelity = s3_row["source_to_store_fidelity"]
                reference_support = s3_row["reference_support_sufficiency"]
                source_semantic = (
                    "faithful" if source_fidelity == "faithful_to_source"
                    else "faithful_compressed" if source_fidelity == "compressed_but_source_faithful"
                    else "conflict_preserved" if source_fidelity == "source_conflict_preserved"
                    else "partial"
                )
                reference_temporal = s3_row["reference_temporal_fidelity"]
                reference_granularity = s3_row["reference_granularity"]
                issue_code = s3_row["issue_code"]
                gap_origin = s3_row["gap_origin"]
                representation_loss = bool(s3_row["representation_decisive_loss"])
                curator_loss = bool(s3_row["curator_introduced_decisive_loss"])
            else:
                availability = support_state
                curated_form_class = "not_applicable" if eligible else "indeterminate"
                source_fidelity = "verbatim_rendered_source" if eligible else "indeterminate"
                reference_support = _reference_support_sufficiency(qid) if eligible else "indeterminate"
                source_semantic = "full_to_rendered_source" if eligible else "indeterminate"
                reference_temporal = "preserved_as_source" if eligible else "indeterminate"
                reference_granularity = "exact_to_rendered_source" if eligible else "indeterminate"
                issue_code = "vehicle_model_query_excluded" if decisive else "none" if support_origin == "none" else support_origin
                gap_origin = support_origin
                representation_loss = decisive
                curator_loss = False
            fidelity.append({
                "protocol_version": PROTOCOL_VERSION,
                "question_store_id": f"{qid}::{store_id}",
                "question_id": qid,
                "run_position": position,
                "store_id": store_id,
                "category": int(gold["category"]),
                "category_name": str(gold["category_name"]),
                "evidence_eligible": eligible,
                "gold_locator_count": len(locators),
                "gold_source_locators": locators,
                "gold_session_count": len(sessions),
                "multi_session_evidence": len(sessions) > 1,
                "gold_global_turn_span": global_turn_span,
                "gold_date_span_days": date_span_days,
                "gold_query_metadata_count": query_gold_count,
                "all_gold_locators_traceable": None if not eligible else True,
                "curated_form_class": curated_form_class,
                "source_to_store_fidelity": source_fidelity,
                "reference_support_sufficiency": reference_support,
                "source_semantic_fidelity": source_semantic,
                "reference_temporal_fidelity": reference_temporal,
                "reference_granularity": reference_granularity,
                "store_availability_state": availability,
                "issue_code": issue_code,
                "gap_origin": gap_origin,
                "representation_decisive_loss": representation_loss,
                "loss_scope": "shared_renderer_before_store_construction" if representation_loss else "none",
                "store_specific_decisive_loss": False,
                "curator_introduced_decisive_loss": curator_loss,
                "finding_basis": "direct_structural" if store_id in {"S1", "S2"} else "direct_semantic_review",
            })

    # Freeze question-store states before importing answer outcomes.
    fidelity_by_key = {(row["question_id"], row["store_id"]): row for row in fidelity}
    stage_a_rows = _read_lines(repo_root / STAGE_A_PATH)
    selective_rows = [row for row in stage_a_rows if row["condition_id"] in SELECTIVE_CONDITIONS]
    _require(len(selective_rows) == 720, "E1--E6 outcome population differs")
    outcome_linkage: list[dict[str, Any]] = []
    for row in selective_rows:
        store_id = STORE_BY_CONDITION[str(row["condition_id"])]
        frozen = fidelity_by_key[(str(row["question_id"]), store_id)]
        outcome_linkage.append({
            "protocol_version": PROTOCOL_VERSION,
            "analysis_row_id": row["analysis_row_id"],
            "question_store_id": frozen["question_store_id"],
            "question_id": row["question_id"],
            "backbone_id": row["backbone_id"],
            "condition_id": row["condition_id"],
            "store_id": store_id,
            "retrieval_system": row["retrieval_system"],
            "category_name": row["category_name"],
            "store_availability_state": frozen["store_availability_state"],
            "curated_form_class": frozen["curated_form_class"],
            "source_to_store_fidelity": frozen["source_to_store_fidelity"],
            "reference_support_sufficiency": frozen["reference_support_sufficiency"],
            "strict_score": float(row["strict_score"]),
            "soft_semantic_score": float(row["soft_semantic_score"]),
            "token_f1": float(row["token_f1"]),
            "evidence_eligible": bool(row["evidence_eligible"]),
            "evidence_recall": row["evidence_recall"],
            "storage_state_frozen_before_outcome_join": True,
        })

    stage1_dir = repo_root / STAGE1_PATH
    errors = _read_lines(stage1_dir / "strict-error-cases.jsonl")
    states = _read_lines(stage1_dir / "root-cause-state-register.jsonl")
    selective_errors = [row for row in errors if row["condition_id"] in SELECTIVE_CONDITIONS]
    _require(len(selective_errors) == EXPECTED_ERROR_PATHS, "Selective Strict-error count differs")
    all_pipeline_shared_insufficiency_errors = [
        row for row in errors
        if row["question_id"] == SHARED_REPRESENTATION_INSUFFICIENCY_QUESTION
    ]
    _require(
        len(all_pipeline_shared_insufficiency_errors) == EXPECTED_ALL_PIPELINE_SHARED_INSUFFICIENCY_ERROR_PATHS,
        "All-pipeline shared-insufficiency error-path count differs",
    )
    linkage: list[dict[str, Any]] = []
    linkage_by_case: dict[str, dict[str, Any]] = {}
    for row in selective_errors:
        store_id = STORE_BY_CONDITION[str(row["condition_id"])]
        frozen = fidelity_by_key[(str(row["question_id"]), store_id)]
        shared_insufficiency = bool(frozen["representation_decisive_loss"])
        link = {
            "protocol_version": PROTOCOL_VERSION,
            "case_id": row["case_id"],
            "question_store_id": frozen["question_store_id"],
            "question_id": row["question_id"],
            "packet_backbone": row["packet_backbone"],
            "condition_id": row["condition_id"],
            "store_id": store_id,
            "retrieval_system": row["retrieval_system"],
            "judge_label": row["judge_label"],
            "evidence_eligible": bool(row["evidence_eligible"]),
            "store_availability_state": frozen["store_availability_state"],
            "issue_code": frozen["issue_code"],
            "shared_representation_insufficiency_present": shared_insufficiency,
            "store_specific_limitation_present": False,
            "storage_cause_decision": "shared_renderer_scope_loss" if shared_insufficiency else "not_assigned_at_storage_stage",
            "attribution_strength": "direct_upstream_limitation" if shared_insufficiency else "pending",
            "causal_sufficiency": "not_established" if shared_insufficiency else "pending",
            "attribution_unit": "unique_question_store_state_joined_to_error_path",
        }
        linkage.append(link)
        linkage_by_case[str(row["case_id"])] = link

    after_states: list[dict[str, Any]] = []
    for state in states:
        updated = dict(state)
        link = linkage_by_case.get(str(state["case_id"]))
        if link is None:
            updated["storage_audit_applicable"] = False
            updated["storage_audit_decision"] = "not_applicable"
            updated["causal_sufficiency"] = "not_applicable"
        else:
            updated["storage_audit_applicable"] = True
            updated["store_availability_state"] = link["store_availability_state"]
            updated["storage_audit_decision"] = link["storage_cause_decision"]
            updated["causal_sufficiency"] = "pending"
            if link["shared_representation_insufficiency_present"]:
                updated["primary_cause"] = "shared_representation_insufficiency"
                updated["attribution_status"] = "assigned_stage_2"
                updated["attribution_strength"] = "direct_upstream_limitation"
                updated["causal_sufficiency"] = "not_established"
        updated["storage_audit_protocol_version"] = PROTOCOL_VERSION
        after_states.append(updated)

    # Long-form summary: every denominator is explicit.
    summary: list[dict[str, Any]] = []
    def add(section: str, store_id: str, metric: str, numerator: float, denominator: float, unit: str) -> None:
        summary.append({
            "protocol_version": PROTOCOL_VERSION, "section": section, "store_id": store_id,
            "metric": metric, "numerator": numerator, "denominator": denominator,
            "value": None if denominator == 0 else numerator / denominator, "unit": unit,
        })

    add("source_integrity", "S1", "canonical_text_caption_turns_preserved", 568, 568, "source_turn")
    add("source_integrity", "S2", "files_byte_identical_to_s1", sum(row["byte_equal"] for row in equivalence), 30, "session_file")
    add("source_integrity", "S3", "source_locator_coverage_in_body", corpus.stats.unique_body_locators, 568, "source_locator")
    add("gold_traceability", "S3", "main60_unique_gold_locators_in_body", len(unique_gold_locators & s3_body_locators), len(unique_gold_locators), "unique_gold_locator")
    add("rendering", "S1/S2", "canonical_turns_with_any_excluded_media_field", total_excluded_media_turns, 568, "source_turn")
    add("rendering", "S1/S2", "gold_associations_touching_any_excluded_media_field", gold_excluded_media_associations, EXPECTED_GOLD_ASSOCIATIONS, "gold_locator_association")
    add("rendering", "S1/S2", "eligible_questions_touching_any_excluded_media_field", gold_excluded_media_questions, EXPECTED_ELIGIBLE, "eligible_question")
    for key, label in (("img_url", "image_url"), ("query", "query_metadata"), ("re-download", "redownload_metadata")):
        add("rendering", "S1/S2", f"canonical_turns_with_excluded_{label}", media_turn_counts[key], 568, "source_turn")
        add("rendering", "S1/S2", f"gold_associations_with_excluded_{label}", gold_media_association_counts[key], EXPECTED_GOLD_ASSOCIATIONS, "gold_locator_association")
        add("rendering", "S1/S2", f"eligible_questions_touching_excluded_{label}", gold_media_question_counts[key], EXPECTED_ELIGIBLE, "eligible_question")
    image_turns = [row for row in canonical if row["media"].get("img_url")]
    add("rendering", "S1/S2", "image_turns_with_preserved_blip_caption", sum(bool(row["media"].get("blip_caption")) for row in image_turns), len(image_turns), "image_turn")
    add("rendering", "S1/S2", "gold_associations_with_excluded_query_metadata", gold_query_associations, EXPECTED_GOLD_ASSOCIATIONS, "gold_locator_association")
    add("rendering", "S1/S2", "eligible_questions_touching_excluded_query_metadata", gold_query_questions, EXPECTED_ELIGIBLE, "eligible_question")
    eligible_fidelity_s1 = [row for row in fidelity if row["store_id"] == "S1" and row["evidence_eligible"]]
    multi_locator_s1 = [row for row in eligible_fidelity_s1 if row["gold_locator_count"] > 1]
    multi_session_s1 = [row for row in eligible_fidelity_s1 if row["multi_session_evidence"]]
    add("dispersion", "S1", "questions_with_multiple_gold_locators", len(multi_locator_s1), EXPECTED_ELIGIBLE, "eligible_question")
    add("dispersion", "S1", "questions_with_cross_session_gold_evidence", len(multi_session_s1), EXPECTED_ELIGIBLE, "eligible_question")
    add("dispersion", "S1", "mean_global_turn_span_for_cross_session_questions", sum(row["gold_global_turn_span"] for row in multi_session_s1), len(multi_session_s1), "global_turn")
    add("dispersion", "S1", "median_global_turn_span_for_cross_session_questions", statistics.median(row["gold_global_turn_span"] for row in multi_session_s1), 1, "global_turn")
    add("dispersion", "S1", "minimum_global_turn_span_for_cross_session_questions", min(row["gold_global_turn_span"] for row in multi_session_s1), 1, "global_turn")
    add("dispersion", "S1", "maximum_global_turn_span_for_cross_session_questions", max(row["gold_global_turn_span"] for row in multi_session_s1), 1, "global_turn")
    add("dispersion", "S1", "mean_date_span_days_for_cross_session_questions", sum(row["gold_date_span_days"] for row in multi_session_s1), len(multi_session_s1), "day")
    add("dispersion", "S1", "median_date_span_days_for_cross_session_questions", statistics.median(row["gold_date_span_days"] for row in multi_session_s1), 1, "day")
    add("dispersion", "S1", "minimum_date_span_days_for_cross_session_questions", min(row["gold_date_span_days"] for row in multi_session_s1), 1, "day")
    add("dispersion", "S1", "maximum_date_span_days_for_cross_session_questions", max(row["gold_date_span_days"] for row in multi_session_s1), 1, "day")
    add("layout", "S2", "cross_folder_questions", sum(row["cross_folder_evidence_required"] for row in routing), EXPECTED_ELIGIBLE, "eligible_question")
    single_or_cross = [row for row in routing if row["evidence_eligible"]]
    add("layout", "S2", "mean_candidate_session_fraction_if_gold_folders_known", sum(row["candidate_sessions_if_gold_folders_known"] for row in single_or_cross), 30 * len(single_or_cross), "eligible_question")
    candidate_sessions_values = [row["candidate_sessions_if_gold_folders_known"] for row in single_or_cross]
    add("layout", "S2", "median_candidate_sessions_if_gold_folders_known", statistics.median(candidate_sessions_values), 1, "session")
    add("layout", "S2", "minimum_candidate_sessions_if_gold_folders_known", min(candidate_sessions_values), 1, "session")
    add("layout", "S2", "maximum_candidate_sessions_if_gold_folders_known", max(candidate_sessions_values), 1, "session")
    cross_session_questions = [row for row in routing if row["evidence_eligible"] and row["gold_session_count"] > 1]
    add("layout", "S2", "cross_session_questions_remaining_within_one_folder", sum(row["gold_folder_count"] == 1 for row in cross_session_questions), len(cross_session_questions), "cross_session_question")
    for category_name in sorted({row["category_name"] for row in eligible_fidelity_s1}):
        category_rows = [row for row in eligible_fidelity_s1 if row["category_name"] == category_name]
        add("dispersion_by_category", "S1", f"{category_name}:cross_session", sum(row["multi_session_evidence"] for row in category_rows), len(category_rows), "eligible_question")
    for label, count in EXPECTED_S2_ROUTING_CLASSES.items():
        add("routing_semantics", "S2", f"gold_bearing_sessions_{label}", count, EXPECTED_S2_ROUTING_UNITS, "question_session")
    for label, count in EXPECTED_S2_QUESTION_CLASSES.items():
        add("routing_semantics", "S2", f"eligible_questions_{label}", count, EXPECTED_ELIGIBLE, "eligible_question")
    for folder in sorted(folder_sizes):
        folder_rows = [row for row in s2_review_table if row["s2_topic_directory"] == folder]
        for label in ("aligned", "partially_aligned", "misleading", "ambiguous"):
            add("routing_semantics_by_folder", "S2", f"{folder}:{label}", sum(row["routing_alignment"] == label for row in folder_rows), len(folder_rows), "question_session")
    for name, count in EXPECTED_S3_CLASSES.items():
        add("curated_form", "S3", name, count, EXPECTED_ELIGIBLE, "eligible_question")
    for name, count in EXPECTED_S3_SOURCE_FIDELITY.items():
        add("source_to_store_fidelity", "S3", name, count, EXPECTED_ELIGIBLE, "eligible_question")
    for name, count in EXPECTED_S3_REFERENCE_SUPPORT.items():
        add("reference_support", "S3", name, count, EXPECTED_ELIGIBLE, "eligible_question")
    add("source_to_store_fidelity", "S3", "curator_introduced_decisive_loss", 0, EXPECTED_ELIGIBLE, "eligible_question")
    add("temporal_fidelity", "S3", "exact_when_temporal_applicable", 20, 22, "temporal_applicable_question")
    add("provenance", "S3", "eligible_questions_with_all_gold_locators", EXPECTED_ELIGIBLE, EXPECTED_ELIGIBLE, "eligible_question")
    add("provenance", "S3", "all_gold_locators_colocated_in_one_fact_unit", sum(row["all_gold_colocated_in_one_fact_unit"] is True for row in s3_preservation), EXPECTED_ELIGIBLE, "eligible_question")
    add("provenance", "S3", "all_gold_locators_colocated_in_one_h2_group", sum(row["all_gold_colocated_in_one_h2_group"] is True for row in s3_preservation), EXPECTED_ELIGIBLE, "eligible_question")
    add("provenance", "S3", "all_gold_locators_colocated_in_one_file", sum(row["all_gold_colocated_in_one_file"] is True for row in s3_preservation), EXPECTED_ELIGIBLE, "eligible_question")
    multi_locator_s3 = [row for row in s3_preservation if row["evidence_eligible"] and row["gold_locator_count"] > 1]
    add("provenance_multiloc", "S3", "multi_locator_questions", len(multi_locator_s3), EXPECTED_ELIGIBLE, "eligible_question")
    add("provenance_multiloc", "S3", "all_gold_locators_colocated_in_one_fact_unit", sum(row["all_gold_colocated_in_one_fact_unit"] is True for row in multi_locator_s3), len(multi_locator_s3), "multi_locator_question")
    add("provenance_multiloc", "S3", "all_gold_locators_colocated_in_one_h2_group", sum(row["all_gold_colocated_in_one_h2_group"] is True for row in multi_locator_s3), len(multi_locator_s3), "multi_locator_question")
    add("provenance_multiloc", "S3", "all_gold_locators_colocated_in_one_file", sum(row["all_gold_colocated_in_one_file"] is True for row in multi_locator_s3), len(multi_locator_s3), "multi_locator_question")
    for cover_size in (1, 2, 3, 4):
        add("provenance", "S3", f"minimum_fact_unit_cover_equals_{cover_size}", sum(row["minimum_fact_units_for_gold_locator_cover"] == cover_size for row in s3_preservation), EXPECTED_ELIGIBLE, "eligible_question")
    add("size", "S3_vs_S1", "byte_ratio", s3.snapshot.total_bytes, s1.snapshot.total_bytes, "byte_ratio")
    add("root_cause", "ALL", "unique_questions_with_shared_representation_insufficiency", 1, EXPECTED_ELIGIBLE, "eligible_question")
    add("root_cause", "ALL", "store_specific_decisive_omissions", 0, EXPECTED_ELIGIBLE * len(STORES), "eligible_question_store")
    add("root_cause", "ALL", "eligible_selective_error_paths_exposed_to_shared_representation_insufficiency", sum(row["shared_representation_insufficiency_present"] and row["evidence_eligible"] for row in linkage), EXPECTED_ELIGIBLE_ERROR_PATHS, "eligible_selective_error_path")
    add("root_cause", "ALL", "selective_error_paths_exposed_to_shared_representation_insufficiency", sum(row["shared_representation_insufficiency_present"] for row in linkage), EXPECTED_ERROR_PATHS, "selective_error_path")
    add("root_cause", "ALL", "all_pipeline_error_paths_exposed_to_shared_representation_insufficiency", len(all_pipeline_shared_insufficiency_errors), len(errors), "strict_noncorrect_path")
    add("root_cause", "ALL", "eligible_all_pipeline_error_paths_exposed_to_shared_representation_insufficiency", len(all_pipeline_shared_insufficiency_errors), sum(bool(row["evidence_eligible"]) for row in errors), "eligible_strict_noncorrect_path")
    add("provenance_granularity", "S3", "gold_linked_units_with_more_than_8_locators", sum(len(unit.source_locators) > 8 for unit in gold_units), len(gold_units), "gold_linked_fact_unit")

    # Aggregate answer conversion without treating repeated paths as store samples.
    groups: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in outcome_linkage:
        groups[(str(row["backbone_id"]), str(row["condition_id"]), str(row["store_availability_state"]))].append(row)
    for (backbone, condition, availability), rows in sorted(groups.items()):
        add("answer_conversion", STORE_BY_CONDITION[condition], f"{backbone}:{condition}:{availability}:strict_accuracy", sum(row["strict_score"] for row in rows), len(rows), "answer_path")
        add("answer_conversion", STORE_BY_CONDITION[condition], f"{backbone}:{condition}:{availability}:mean_soft", sum(row["soft_semantic_score"] for row in rows), len(rows), "answer_path")
        add("answer_conversion", STORE_BY_CONDITION[condition], f"{backbone}:{condition}:{availability}:mean_token_f1", sum(row["token_f1"] for row in rows), len(rows), "answer_path")

    s3_groups: dict[tuple[str, str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in outcome_linkage:
        if row["store_id"] == "S3" and row["evidence_eligible"]:
            s3_groups[(str(row["backbone_id"]), str(row["condition_id"]), str(row["source_to_store_fidelity"]), str(row["reference_support_sufficiency"]))].append(row)
    for (backbone, condition, source_fidelity, reference_support), rows in sorted(s3_groups.items()):
        prefix = f"{backbone}:{condition}:{source_fidelity}:{reference_support}"
        add("answer_conversion_by_storage_state", "S3", f"{prefix}:strict_accuracy", sum(row["strict_score"] for row in rows), len(rows), "answer_path")
        add("answer_conversion_by_storage_state", "S3", f"{prefix}:mean_soft", sum(row["soft_semantic_score"] for row in rows), len(rows), "answer_path")
        add("answer_conversion_by_storage_state", "S3", f"{prefix}:mean_token_f1", sum(row["token_f1"] for row in rows), len(rows), "answer_path")
        eligible_recall_rows = [row for row in rows if row["evidence_recall"] is not None]
        add("answer_conversion_by_storage_state", "S3", f"{prefix}:mean_evidence_recall", sum(float(row["evidence_recall"]) for row in eligible_recall_rows), len(eligible_recall_rows), "answer_path")

    # Persist auxiliary values in a compact audit-only pseudo row.
    add("audit_detail", "S3", "gold_linked_fact_units", len(gold_units), len(corpus.units), "fact_unit")
    locator_counts = sorted(len(unit.source_locators) for unit in gold_units)
    add("audit_detail", "S3", "median_locators_per_gold_linked_unit", statistics.median(locator_counts), 1, "locator_count")
    p90 = locator_counts[math.ceil(0.9 * len(locator_counts)) - 1]
    add("audit_detail", "S3", "p90_locators_per_gold_linked_unit", p90, 1, "locator_count")
    add("audit_detail", "S3", "max_locators_per_gold_linked_unit", max(locator_counts), 1, "locator_count")
    add("audit_detail", "S1/S2", "canonical_turns_with_query_metadata", total_query_turns, 568, "source_turn")

    return {
        "store-integrity": integrity,
        "s1-s2-equivalence": equivalence,
        "s2-routing": routing,
        "s2-routing-session-review": s2_review_table,
        "s3-fact-preservation": s3_preservation,
        "storage-fidelity": fidelity,
        "storage-outcome-linkage": outcome_linkage,
        "case-storage-linkage": linkage,
        "root-cause-state-register-after-storage": after_states,
        "storage-summary": summary,
    }


def _assert_no_forbidden_fields(tables: Mapping[str, Sequence[Mapping[str, Any]]]) -> None:
    for table, rows in tables.items():
        for row in rows:
            bad = {key.casefold() for key in row} & FORBIDDEN_OUTPUT_FIELDS
            _require(not bad, f"Forbidden public fields in {table}: {sorted(bad)}")


def _schema(tables: Mapping[str, Sequence[Mapping[str, Any]]]) -> dict[str, Any]:
    return {
        "protocol_version": PROTOCOL_VERSION,
        "primary_unit": "question_id x store_id",
        "question_store_denominator": 180,
        "eligible_question_store_denominator": 174,
        "causal_rule": "outcome-blind store state is frozen before answer outcomes are joined",
        "tables": {name: {"rows": len(rows), "fields": list(rows[0])} for name, rows in tables.items()},
    }


def _source_manifest(repo_root: Path) -> dict[str, Any]:
    paths = [
        *QUESTION_PATHS, *GOLD_PATHS, CANONICAL_PATH, S2_PATH_MAP, COMPOSITION_PATH, REVIEW_PATH, S2_REVIEW_PATH, STAGE_A_PATH,
        f"{STAGE1_PATH}/strict-error-cases.jsonl", f"{STAGE1_PATH}/root-cause-state-register.jsonl",
        "experiments/locomo-conv50-v1/manifests/s1-flat.json",
        "experiments/locomo-conv50-v1/manifests/s2-foldered.json",
        "experiments/locomo-conv50-v1/manifests/s3-curated.json",
    ]
    files = [
        {"path": rel, "sha256": _sha256_file(repo_root / rel), "bytes": (repo_root / rel).stat().st_size}
        for rel in paths
    ]
    body = {"protocol_version": PROTOCOL_VERSION, "files": files}
    body["source_manifest_id"] = "rq5-storage-sources-" + sha256_bytes(canonical_json_bytes(body))
    return body


def _read_table(path: Path) -> list[dict[str, Any]]:
    return _read_jsonl(path)


def audit_rq5_storage_output(*, repo_root: Path, output_dir: Path) -> dict[str, Any]:
    repo_root, output_dir = Path(repo_root).resolve(), Path(output_dir).resolve()
    _require(output_dir.is_dir() and not output_dir.is_symlink(), "Storage-audit output is unsafe")
    tables = {name: _read_table(output_dir / f"{name}.jsonl") for name in TABLES}
    _assert_no_forbidden_fields(tables)
    expected_counts = {
        "store-integrity": 3, "s1-s2-equivalence": 30, "s2-routing": 60,
        "s2-routing-session-review": EXPECTED_S2_ROUTING_UNITS,
        "s3-fact-preservation": 60, "storage-fidelity": 180,
        "storage-outcome-linkage": 720, "case-storage-linkage": 205,
        "root-cause-state-register-after-storage": 250,
    }
    for name, count in expected_counts.items():
        _require(len(tables[name]) == count, f"{name} row count differs")
    _require(sum(row["evidence_eligible"] for row in tables["storage-fidelity"]) == 174, "Eligible question-store count differs")
    _require(all(row["byte_equal"] for row in tables["s1-s2-equivalence"]), "S1/S2 byte equivalence failed")
    s2_review_rows = tables["s2-routing-session-review"]
    _require(Counter(row["routing_alignment"] for row in s2_review_rows) == Counter(EXPECTED_S2_ROUTING_CLASSES), "Published S2 routing-label census differs")
    eligible_routing = [row for row in tables["s2-routing"] if row["evidence_eligible"]]
    _require(Counter(row["question_routing_class"] for row in eligible_routing) == Counter(EXPECTED_S2_QUESTION_CLASSES), "Published S2 question-routing census differs")
    eligible_s3 = [row for row in tables["s3-fact-preservation"] if row["evidence_eligible"]]
    _require(Counter(row["curated_form_class"] for row in eligible_s3) == Counter(EXPECTED_S3_CLASSES), "Published S3 curated-form census differs")
    _require(Counter(row["source_to_store_fidelity"] for row in eligible_s3) == Counter(EXPECTED_S3_SOURCE_FIDELITY), "Published S3 source-fidelity census differs")
    _require(Counter(row["reference_support_sufficiency"] for row in eligible_s3) == Counter(EXPECTED_S3_REFERENCE_SUPPORT), "Published S3 reference-support census differs")
    _require(all(row["all_gold_locators_present_in_body"] for row in eligible_s3), "Published S3 locator coverage differs")
    _require(sum(row["curator_introduced_decisive_loss"] for row in eligible_s3) == 0, "Unsupported curator loss published")
    links = tables["case-storage-linkage"]
    _require(Counter(row["store_id"] for row in links) == Counter(EXPECTED_STORE_ERROR_PATHS), "Error-path store census differs")
    _require(Counter(row["store_id"] for row in links if row["evidence_eligible"]) == Counter(EXPECTED_ELIGIBLE_STORE_ERROR_PATHS), "Eligible error-path store census differs")
    shared = [row for row in links if row["shared_representation_insufficiency_present"]]
    _require(len(shared) == 12 and {row["question_id"] for row in shared} == {SHARED_REPRESENTATION_INSUFFICIENCY_QUESTION}, "Shared-insufficiency path exposure differs")
    _require(not any(row["store_specific_limitation_present"] for row in links), "A store-specific decisive loss was published without direct support")

    # Rebuild the core tables from the frozen sources and compare canonical bytes.
    # This is a deterministic reconstruction and tamper check, not a second algorithm.
    rebuilt = _build_core(repo_root)
    for name in TABLES:
        _require(_jsonl_payload(rebuilt[name]) == (output_dir / f"{name}.jsonl").read_bytes(), f"Independent rebuild differs: {name}")
        _require(_csv_payload(rebuilt[name]) == (output_dir / f"{name}.csv").read_bytes(), f"CSV/JSONL parity differs: {name}")

    source_manifest = _read_json(output_dir / "source-manifest.json")
    _require(source_manifest == _source_manifest(repo_root), "Source manifest differs")
    output_sha256 = {
        path.name: _sha256_file(path)
        for path in sorted(output_dir.iterdir(), key=lambda p: p.name)
        if path.name not in {"audit.json", "RQ5-STORAGE-AUDIT.PASSED"}
    }
    body = {
        "protocol_version": PROTOCOL_VERSION,
        "status": "passed",
        "counts": {name: len(rows) for name, rows in tables.items()},
        "s2_routing_census": dict(sorted(Counter(row["routing_alignment"] for row in s2_review_rows).items())),
        "curated_form_census": dict(sorted(Counter(row["curated_form_class"] for row in eligible_s3).items())),
        "source_fidelity_census": dict(sorted(Counter(row["source_to_store_fidelity"] for row in eligible_s3).items())),
        "reference_support_census": dict(sorted(Counter(row["reference_support_sufficiency"] for row in eligible_s3).items())),
        "shared_representation_insufficiency_unique_questions": 1,
        "selective_error_paths_exposed_to_shared_representation_insufficiency": len(shared),
        "all_pipeline_error_paths_exposed_to_shared_representation_insufficiency": EXPECTED_ALL_PIPELINE_SHARED_INSUFFICIENCY_ERROR_PATHS,
        "store_specific_decisive_losses": 0,
        "curator_introduced_decisive_losses": 0,
        "output_sha256": output_sha256,
        "source_manifest_id": source_manifest["source_manifest_id"],
    }
    body["audit_id"] = "rq5-storage-audit-" + sha256_bytes(canonical_json_bytes(body))
    return body


def build_rq5_storage_audit(*, repo_root: Path, output_dir: Path) -> dict[str, Any]:
    repo_root, output_dir = Path(repo_root).resolve(), Path(output_dir).resolve()
    _require(repo_root.is_dir() and not repo_root.is_symlink(), "Repository root is unsafe")
    _require(not output_dir.exists(), "Storage-audit output already exists")
    output_dir.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=".rq5-storage-", dir=output_dir.parent))
    try:
        tables = _build_core(repo_root)
        _assert_no_forbidden_fields(tables)
        for name in TABLES:
            _write(staging / f"{name}.jsonl", _jsonl_payload(tables[name]))
            _write(staging / f"{name}.csv", _csv_payload(tables[name]))
        _write(staging / "schema.json", json.dumps(_schema(tables), indent=2, sort_keys=True).encode() + b"\n")
        _write(staging / "source-manifest.json", json.dumps(_source_manifest(repo_root), indent=2, sort_keys=True).encode() + b"\n")
        readme = (
            "# RQ5 Section 5.6.2 storage audit\n\n"
            "This artifact audits S1--S3 once per question-store pair, before joining answer outcomes. "
            "S1/S2 fidelity is structural; S2 routing and S3 fidelity use completed outcome-blind semantic reviews. "
            "Fidelity to the source is kept separate from support for the benchmark reference. "
            "A locator hit is never treated as proof of semantic preservation, and q002 is recorded as a shared renderer-scope limitation rather than a store-specific defect.\n"
        )
        _write(staging / "README.md", readme.encode("utf-8"))
        # audit function expects the final path only for path identity, but all sources are external.
        os.replace(staging, output_dir)
        audit = audit_rq5_storage_output(repo_root=repo_root, output_dir=output_dir)
        _write(output_dir / "audit.json", json.dumps(audit, indent=2, sort_keys=True).encode() + b"\n")
        marker = {"protocol_version": PROTOCOL_VERSION, "status": "passed", "audit_id": audit["audit_id"], "audit_sha256": _sha256_file(output_dir / "audit.json")}
        _write(output_dir / "RQ5-STORAGE-AUDIT.PASSED", json.dumps(marker, indent=2, sort_keys=True).encode() + b"\n")
        return audit
    except Exception:
        if staging.exists():
            shutil.rmtree(staging)
        if output_dir.exists() and not (output_dir / "RQ5-STORAGE-AUDIT.PASSED").exists():
            shutil.rmtree(output_dir)
        raise


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=Path.cwd())
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--audit-only", action="store_true")
    args = parser.parse_args(argv)
    result = audit_rq5_storage_output(repo_root=args.repo_root, output_dir=args.output_dir) if args.audit_only else build_rq5_storage_audit(repo_root=args.repo_root, output_dir=args.output_dir)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
