"""Build the append-only LoCoMo conv-50 main-60 v2 question set.

``main-60-v2`` is deliberately a composite rather than a rewritten online
question file.  Positions 1--40 point to the immutable ``main-40-v1`` set and
positions 41--60 point to a new, disjoint ``extension-20-v2`` set.  Keeping
the two source set identities intact allows the already completed main-40
records to remain valid and auditable.

The extension selection is outcome-blind.  It excludes the frozen main-40,
the frozen dev-6, adversarial questions, and four catalogued defective gold
questions.  Within each category it ranks question IDs with SHA-256 and never
uses answer text, evidence text, or model results.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections import Counter
from pathlib import Path
from typing import Any, Iterable, Mapping

from .question_sets import (
    CATEGORY_NAMES,
    CONVERSATION_ID,
    DEFECTIVE_ORDERS,
    EXPECTED_DEFECTIVE_QUESTIONS,
    FORBIDDEN_ONLINE_KEYS,
    verify_question_sets,
)


COMPOSITE_SET_ID = "locomo-conv50-main60-v2"
EXTENSION_SET_ID = "locomo-conv50-extension20-v2"
GENERATOR_ID = "fs_memory_lab.question_sets_v2:v2"
SELECTION_SEED = 42
RUN_ORDER_SEED = 42
SELECTION_NAMESPACE = "main60-v2-extension"
RUN_ORDER_NAMESPACE = "main60-v2-extension-run-order"
CORE_QUOTAS = {1: 10, 2: 10, 3: 7, 4: 13}
EXTENSION_QUOTAS = {1: 3, 2: 3, 3: 0, 4: 14}
FINAL_QUOTAS = {1: 13, 2: 13, 3: 7, 4: 27}
RELIABLE_POOL_COUNTS = {1: 30, 2: 32, 3: 7, 4: 85}
EXPECTED_EXTENSION_IDS = (
    "conv-50-q147",
    "conv-50-q126",
    "conv-50-q075",
    "conv-50-q144",
    "conv-50-q019",
    "conv-50-q114",
    "conv-50-q121",
    "conv-50-q044",
    "conv-50-q057",
    "conv-50-q058",
    "conv-50-q111",
    "conv-50-q078",
    "conv-50-q074",
    "conv-50-q082",
    "conv-50-q104",
    "conv-50-q089",
    "conv-50-q012",
    "conv-50-q132",
    "conv-50-q028",
    "conv-50-q118",
)


def _canonical_json(value: Any) -> bytes:
    text = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return (text + "\n").encode("utf-8")


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _file_sha256(path: Path) -> str:
    return _sha256(path.read_bytes())


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text())


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text().splitlines() if line]


def _write_json(path: Path, value: Any) -> None:
    path.write_bytes(_canonical_json(value))


def _write_jsonl(path: Path, rows: Iterable[Mapping[str, Any]]) -> None:
    path.write_bytes(b"".join(_canonical_json(dict(row)) for row in rows))


def _rank(seed: int, namespace: str, question_id: str) -> bytes:
    return hashlib.sha256(f"{seed}|{namespace}|{question_id}".encode()).digest()


def _evidence_sessions(item: Mapping[str, Any]) -> set[int]:
    sessions: set[int] = set()
    for dia_id in item.get("evidence", []):
        match = re.fullmatch(r"D([1-9][0-9]*):([0-9]+)", dia_id)
        if match:
            sessions.add(int(match.group(1)))
    return sessions


def _zone(session_index: int) -> str:
    if session_index <= 10:
        return "early"
    if session_index <= 20:
        return "middle"
    return "late"


def _annotated_reliable_pool(
    raw_path: Path,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    raw = _load_json(raw_path)
    conversation = next(row for row in raw if row.get("sample_id") == CONVERSATION_ID)
    annotated: list[dict[str, Any]] = []
    non_adversarial_order = 0
    for source_qa_index, original in enumerate(conversation["qa"], start=1):
        if original["category"] not in CATEGORY_NAMES:
            continue
        non_adversarial_order += 1
        item = dict(original)
        item.update(
            source_qa_index=source_qa_index,
            non_adversarial_order=non_adversarial_order,
            question_id=f"conv-50-q{source_qa_index:03d}",
        )
        annotated.append(item)

    if len(annotated) != 158:
        raise ValueError("Expected 158 non-adversarial conv-50 questions")
    for order, expected_question in EXPECTED_DEFECTIVE_QUESTIONS.items():
        if annotated[order - 1]["question"] != expected_question:
            raise ValueError(f"Defective-gold catalog drifted at order {order}")

    reliable = [
        row
        for row in annotated
        if row["non_adversarial_order"] not in DEFECTIVE_ORDERS
    ]
    if Counter(row["category"] for row in reliable) != Counter(RELIABLE_POOL_COUNTS):
        raise ValueError("Reliable-pool category counts changed")
    return conversation, reliable


def _source_helpers(
    canonical_path: Path, source_map_path: Path
) -> tuple[dict[str, dict[str, Any]], dict[str, str], dict[str, Any]]:
    records = _load_jsonl(canonical_path)
    by_dia_id = {record["dia_id"]: record for record in records}
    source_map = _load_json(source_map_path)
    aliases = {
        alias: value["canonical_dia_id"]
        for alias, value in source_map.get("dia_id_aliases", {}).items()
    }
    return by_dia_id, aliases, source_map


def _has_caption_evidence(
    item: Mapping[str, Any],
    by_dia_id: Mapping[str, Mapping[str, Any]],
    aliases: Mapping[str, str],
) -> bool:
    return any(
        bool(
            (
                by_dia_id[aliases.get(dia_id, dia_id)].get("media") or {}
            ).get("blip_caption")
        )
        for dia_id in item.get("evidence", [])
    )


def _gold_row(
    row: Mapping[str, Any],
    *,
    source_map: Mapping[str, Any],
    aliases: Mapping[str, str],
    by_dia_id: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    official_ids = list(row.get("evidence", []))
    canonical_ids = [aliases.get(dia_id, dia_id) for dia_id in official_ids]
    if any(dia_id not in source_map["by_dia_id"] for dia_id in canonical_ids):
        raise ValueError(f"Unresolved evidence ID in {row['question_id']}")
    return {
        "schema_version": 1,
        "question_set_id": EXTENSION_SET_ID,
        "question_id": row["question_id"],
        "source_qa_index": row["source_qa_index"],
        "non_adversarial_order": row["non_adversarial_order"],
        "category": row["category"],
        "category_name": CATEGORY_NAMES[row["category"]],
        "answer": row["answer"],
        "gold_evidence_dia_ids_official": official_ids,
        "gold_evidence_dia_ids": canonical_ids,
        "gold_evidence_locators": [
            source_map["by_dia_id"][dia_id]["locator"] for dia_id in canonical_ids
        ],
        "gold_evidence_sessions": sorted(_evidence_sessions(row)),
        "has_caption_evidence": _has_caption_evidence(row, by_dia_id, aliases),
    }


def _select_extension(
    reliable: Iterable[Mapping[str, Any]], excluded_ids: set[str]
) -> list[dict[str, Any]]:
    available = [dict(row) for row in reliable if row["question_id"] not in excluded_ids]
    expected_available = {1: 18, 2: 20, 3: 0, 4: 70}
    if Counter(row["category"] for row in available) != Counter(expected_available):
        raise ValueError("Extension candidate-pool counts changed")

    selected: list[dict[str, Any]] = []
    for category in sorted(EXTENSION_QUOTAS):
        ranked = sorted(
            (row for row in available if row["category"] == category),
            key=lambda row, c=category: _rank(
                SELECTION_SEED,
                f"{SELECTION_NAMESPACE}|category-{c}",
                row["question_id"],
            ),
        )
        selected.extend(ranked[: EXTENSION_QUOTAS[category]])
    selected.sort(
        key=lambda row: _rank(
            RUN_ORDER_SEED, RUN_ORDER_NAMESPACE, row["question_id"]
        )
    )
    if tuple(row["question_id"] for row in selected) != EXPECTED_EXTENSION_IDS:
        raise ValueError("Deterministic extension selection drifted")
    return selected


def build_question_sets_v2(repo_root: Path, output_dir: Path) -> dict[str, Any]:
    """Generate extension-20-v2 and the append-only main-60 composition."""
    root = repo_root.resolve()
    output = output_dir.resolve()
    parent_dir = root / "experiments/locomo-conv50-v1/question-sets"
    raw_path = root / "data/raw/locomo10.json"
    canonical_path = root / "data/processed/conv-50.jsonl"
    source_map_path = root / "data/manifests/source_map.json"

    parent_verification = verify_question_sets(root, parent_dir)
    if parent_verification.get("status") != "passed":
        raise ValueError("Frozen main-40 parent verification failed")

    core_input_path = parent_dir / "main-40-input.jsonl"
    core_gold_path = parent_dir / "main-40-gold.jsonl"
    dev_input_path = parent_dir / "dev-6-input.jsonl"
    dev_gold_path = parent_dir / "dev-6-gold.jsonl"
    core_input = _load_jsonl(core_input_path)
    core_gold = _load_jsonl(core_gold_path)
    dev_input = _load_jsonl(dev_input_path)
    conversation, reliable = _annotated_reliable_pool(raw_path)
    by_dia_id, aliases, source_map = _source_helpers(canonical_path, source_map_path)

    core_ids = {row["question_id"] for row in core_input}
    dev_ids = {row["question_id"] for row in dev_input}
    if core_ids & dev_ids:
        raise ValueError("Frozen main-40 and dev-6 overlap")
    extension = _select_extension(reliable, core_ids | dev_ids)

    extension_input = [
        {
            "schema_version": 1,
            "question_set_id": EXTENSION_SET_ID,
            "run_position": position,
            "question_id": row["question_id"],
            "conversation_id": CONVERSATION_ID,
            "question": row["question"],
        }
        for position, row in enumerate(extension, start=1)
    ]
    extension_gold = [
        _gold_row(
            row,
            source_map=source_map,
            aliases=aliases,
            by_dia_id=by_dia_id,
        )
        for row in extension
    ]

    composition_rows: list[dict[str, Any]] = []
    for global_position, row in enumerate(core_input, start=1):
        composition_rows.append(
            {
                "global_position": global_position,
                "question_id": row["question_id"],
                "source_question_set_id": row["question_set_id"],
                "source_run_position": row["run_position"],
                "layer": "core-40-v1",
            }
        )
    for global_position, row in enumerate(extension_input, start=41):
        composition_rows.append(
            {
                "global_position": global_position,
                "question_id": row["question_id"],
                "source_question_set_id": row["question_set_id"],
                "source_run_position": row["run_position"],
                "layer": "extension-20-v2",
            }
        )
    composition = {
        "schema_version": 2,
        "composite_question_set_id": COMPOSITE_SET_ID,
        "composition_policy": "append-only-core40-plus-extension20",
        "question_count": 60,
        "question_order": composition_rows,
    }

    core_gold_by_id = {row["question_id"]: row for row in core_gold}
    extension_gold_by_id = {row["question_id"]: row for row in extension_gold}
    all_gold = {**core_gold_by_id, **extension_gold_by_id}
    audit = [
        "# LoCoMo conv-50 main-60-v2 composite audit view",
        "",
        "Positions 1--40 reference the immutable main-40-v1 set; positions 41--60 reference extension-20-v2.",
        "This is a human audit view, not an online model input.",
        "",
        "| Global | Layer | Source position | Question ID | Category | Caption evidence | Evidence sessions | Question |",
        "| ---: | --- | ---: | --- | --- | --- | --- | --- |",
    ]
    question_by_id = {
        row["question_id"]: row["question"] for row in core_input + extension_input
    }
    for item in composition_rows:
        gold = all_gold[item["question_id"]]
        sessions = ", ".join(map(str, gold["gold_evidence_sessions"])) or "none"
        question = question_by_id[item["question_id"]].replace("|", "\\|").replace("\n", " ")
        audit.append(
            f"| {item['global_position']} | {item['layer']} | {item['source_run_position']} | "
            f"`{item['question_id']}` | {gold['category_name']} | "
            f"{'yes' if gold['has_caption_evidence'] else 'no'} | {sessions} | {question} |"
        )

    output.mkdir(parents=True, exist_ok=True)
    paths = {
        "extension_input": output / "extension-20-input.jsonl",
        "extension_gold": output / "extension-20-gold.jsonl",
        "composition": output / "main-60-composition.json",
        "audit": output / "main-60-audit.md",
        "readme": output / "README.md",
    }
    _write_jsonl(paths["extension_input"], extension_input)
    _write_jsonl(paths["extension_gold"], extension_gold)
    _write_json(paths["composition"], composition)
    paths["audit"].write_text("\n".join(audit) + "\n")
    paths["readme"].write_text(
        "# LoCoMo conv-50 main-60-v2\n\n"
        "This is an append-only composite test set. Positions 1--40 remain in "
        "the frozen `locomo-conv50-main40-v1` files in `../question-sets/`; "
        "positions 41--60 come from the independent "
        "`locomo-conv50-extension20-v2` files in this directory.\n\n"
        "- `extension-20-input.jsonl`: safe online input for the 20 new questions.\n"
        "- `extension-20-gold.jsonl`: offline-only gold answers and evidence.\n"
        "- `main-60-composition.json`: global positions 1--60 and source-set identity.\n"
        "- `main-60-audit.md`: human-readable audit table.\n"
        "- `manifest.json` and `verification.json`: frozen provenance and checks.\n\n"
        "Do not rewrite the original 40 rows with a new question-set ID; doing so "
        "would invalidate the existing formal-v1 records. Regenerate with "
        "`python3 -m fs_memory_lab.question_sets_v2` and verify with "
        "`python3 -m fs_memory_lab.question_sets_v2 --verify-only`.\n"
    )

    extension_category_counts = Counter(row["category"] for row in extension_gold)
    extension_caption_counts = Counter(
        row["category"] for row in extension_gold if row["has_caption_evidence"]
    )
    extension_zone_counts = {
        str(category): dict(
            sorted(
                Counter(
                    _zone(session)
                    for row in extension_gold
                    if row["category"] == category
                    for session in row["gold_evidence_sessions"]
                ).items()
            )
        )
        for category in (1, 2, 4)
    }
    combined_category_counts = Counter(row["category"] for row in all_gold.values())
    combined_sessions = sorted(
        {
            session
            for row in all_gold.values()
            for session in row["gold_evidence_sessions"]
        }
    )
    combined_caption_count = sum(
        bool(row["has_caption_evidence"]) for row in all_gold.values()
    )
    combined_zero_evidence_count = sum(
        not row["gold_evidence_dia_ids"] for row in all_gold.values()
    )

    manifest = {
        "schema_version": 2,
        "artifact_id": "locomo-conv50-main60-v2-composite",
        "status": "frozen",
        "generator": GENERATOR_ID,
        "source": {
            "conversation_id": CONVERSATION_ID,
            "locomo10_path": "data/raw/locomo10.json",
            "locomo10_sha256": _file_sha256(raw_path),
            "canonical_records_path": "data/processed/conv-50.jsonl",
            "canonical_records_sha256": _file_sha256(canonical_path),
            "source_map_path": "data/manifests/source_map.json",
            "source_map_sha256": _file_sha256(source_map_path),
        },
        "parent_core": {
            "question_set_id": core_input[0]["question_set_id"],
            "question_count": len(core_input),
            "input_path": str(core_input_path.relative_to(root)),
            "input_sha256": _file_sha256(core_input_path),
            "gold_path": str(core_gold_path.relative_to(root)),
            "gold_sha256": _file_sha256(core_gold_path),
            "manifest_path": str((parent_dir / "manifest.json").relative_to(root)),
            "manifest_sha256": _file_sha256(parent_dir / "manifest.json"),
            "verification_path": str(
                (parent_dir / "verification.json").relative_to(root)
            ),
            "verification_sha256": _file_sha256(parent_dir / "verification.json"),
        },
        "excluded_development": {
            "question_set_id": dev_input[0]["question_set_id"],
            "question_count": len(dev_input),
            "input_path": str(dev_input_path.relative_to(root)),
            "input_sha256": _file_sha256(dev_input_path),
            "gold_path": str(dev_gold_path.relative_to(root)),
            "gold_sha256": _file_sha256(dev_gold_path),
        },
        "eligibility": {
            "official_qa_count": len(conversation["qa"]),
            "non_adversarial_count": 158,
            "reliable_pool_count": 154,
            "reliable_pool_category_counts": {
                str(key): value for key, value in RELIABLE_POOL_COUNTS.items()
            },
            "defective_non_adversarial_orders_excluded": sorted(DEFECTIVE_ORDERS),
            "core_and_dev_excluded_candidate_count": 108,
            "candidate_category_counts": {"1": 18, "2": 20, "3": 0, "4": 70},
        },
        "selection": {
            "design": "append-only extension after main-40 results existed",
            "selection_seed": SELECTION_SEED,
            "selection_algorithm": "sha256-rank-by-question-id-and-category-v2",
            "selection_namespace": SELECTION_NAMESPACE,
            "run_order_seed": RUN_ORDER_SEED,
            "run_order_namespace": RUN_ORDER_NAMESPACE,
            "extension_quotas": {
                str(key): value for key, value in EXTENSION_QUOTAS.items()
            },
            "final_quotas": {str(key): value for key, value in FINAL_QUOTAS.items()},
            "extension_question_ids_in_run_order": list(EXPECTED_EXTENSION_IDS),
            "uses_answer_text": False,
            "uses_evidence_text": False,
            "uses_model_outputs_or_scores": False,
            "metadata_not_used_for_selection": [
                "caption presence",
                "evidence session",
                "history zone",
            ],
        },
        "composition": {
            "composite_question_set_id": COMPOSITE_SET_ID,
            "core_layer": "positions 1-40 retain main-40-v1 identity and order",
            "extension_layer": "positions 41-60 use extension-20-v2",
            "question_count": 60,
            "category_counts": {
                str(key): value for key, value in sorted(combined_category_counts.items())
            },
        },
        "observed_coverage_not_used_for_selection": {
            "extension_caption_questions": sum(extension_caption_counts.values()),
            "extension_caption_counts_by_category": {
                str(key): value for key, value in sorted(extension_caption_counts.items())
            },
            "extension_evidence_sessions": sorted(
                {
                    session
                    for row in extension_gold
                    for session in row["gold_evidence_sessions"]
                }
            ),
            "extension_zone_counts_by_category": extension_zone_counts,
            "combined_caption_questions": combined_caption_count,
            "combined_text_only_questions": 60
            - combined_caption_count
            - combined_zero_evidence_count,
            "combined_zero_gold_evidence_questions": combined_zero_evidence_count,
            "combined_evidence_sessions": combined_sessions,
        },
        "outputs": {
            name: {
                "filename": path.name,
                "sha256": _file_sha256(path),
                "bytes": path.stat().st_size,
            }
            for name, path in paths.items()
        },
    }
    _write_json(output / "manifest.json", manifest)
    verification = verify_question_sets_v2(root, output)
    _write_json(output / "verification.json", verification)
    return {"manifest": manifest, "verification": verification}


def verify_question_sets_v2(repo_root: Path, output_dir: Path) -> dict[str, Any]:
    """Verify the append-only extension and its composite main-60 identity."""
    root = repo_root.resolve()
    output = output_dir.resolve()
    parent_dir = root / "experiments/locomo-conv50-v1/question-sets"
    verify_question_sets(root, parent_dir)

    manifest = _load_json(output / "manifest.json")
    extension_input = _load_jsonl(output / "extension-20-input.jsonl")
    extension_gold = _load_jsonl(output / "extension-20-gold.jsonl")
    composition = _load_json(output / "main-60-composition.json")
    core_input = _load_jsonl(parent_dir / "main-40-input.jsonl")
    core_gold = _load_jsonl(parent_dir / "main-40-gold.jsonl")
    dev_input = _load_jsonl(parent_dir / "dev-6-input.jsonl")

    if manifest.get("artifact_id") != "locomo-conv50-main60-v2-composite":
        raise ValueError("Unexpected main-60-v2 artifact identity")
    for meta in manifest["outputs"].values():
        path = output / meta["filename"]
        if _file_sha256(path) != meta["sha256"] or path.stat().st_size != meta["bytes"]:
            raise ValueError(f"Question-set-v2 artifact hash mismatch: {path.name}")
    for path_key, hash_key in (
        ("locomo10_path", "locomo10_sha256"),
        ("canonical_records_path", "canonical_records_sha256"),
        ("source_map_path", "source_map_sha256"),
    ):
        if _file_sha256(root / manifest["source"][path_key]) != manifest["source"][hash_key]:
            raise ValueError(f"Question-set-v2 source hash mismatch: {path_key}")
    for prefix in ("input", "gold", "manifest", "verification"):
        parent_path = root / manifest["parent_core"][f"{prefix}_path"]
        if _file_sha256(parent_path) != manifest["parent_core"][f"{prefix}_sha256"]:
            raise ValueError(f"Frozen parent {prefix} hash changed")
    for prefix in ("input", "gold"):
        dev_path = root / manifest["excluded_development"][f"{prefix}_path"]
        if _file_sha256(dev_path) != manifest["excluded_development"][f"{prefix}_sha256"]:
            raise ValueError(f"Frozen dev-6 {prefix} hash changed")

    if len(extension_input) != 20 or len(extension_gold) != 20:
        raise ValueError("Extension question set must contain exactly 20 rows")
    if [row["question_id"] for row in extension_input] != [
        row["question_id"] for row in extension_gold
    ]:
        raise ValueError("Extension input and gold order differ")
    if tuple(row["question_id"] for row in extension_input) != EXPECTED_EXTENSION_IDS:
        raise ValueError("Extension question order changed")
    if [row["run_position"] for row in extension_input] != list(range(1, 21)):
        raise ValueError("Extension run positions must be contiguous 1..20")
    if any(row["question_set_id"] != EXTENSION_SET_ID for row in extension_input):
        raise ValueError("Extension input set identity changed")
    if any(row["question_set_id"] != EXTENSION_SET_ID for row in extension_gold):
        raise ValueError("Extension gold set identity changed")
    if any(FORBIDDEN_ONLINE_KEYS & row.keys() for row in extension_input):
        raise ValueError("Extension online input leaks hidden evaluation fields")
    if Counter(row["category"] for row in extension_gold) != Counter(EXTENSION_QUOTAS):
        raise ValueError("Extension category quotas changed")

    core_ids = {row["question_id"] for row in core_input}
    dev_ids = {row["question_id"] for row in dev_input}
    extension_ids = {row["question_id"] for row in extension_input}
    if core_ids & extension_ids or dev_ids & extension_ids:
        raise ValueError("Extension overlaps frozen core or dev-6")
    if len(core_ids | extension_ids) != 60:
        raise ValueError("Composite main-60 IDs are not unique")

    order = composition.get("question_order")
    if not isinstance(order, list) or len(order) != 60:
        raise ValueError("Composite question order must contain 60 rows")
    if [row["global_position"] for row in order] != list(range(1, 61)):
        raise ValueError("Composite global positions must be contiguous 1..60")
    if [row["question_id"] for row in order[:40]] != [
        row["question_id"] for row in core_input
    ]:
        raise ValueError("Composite positions 1..40 no longer preserve main-40 order")
    if [row["question_id"] for row in order[40:]] != list(EXPECTED_EXTENSION_IDS):
        raise ValueError("Composite positions 41..60 no longer preserve extension order")
    if any(row["source_question_set_id"] != core_input[0]["question_set_id"] for row in order[:40]):
        raise ValueError("Composite core layer changed question-set identity")
    if any(row["source_question_set_id"] != EXTENSION_SET_ID for row in order[40:]):
        raise ValueError("Composite extension layer changed question-set identity")

    combined_gold = core_gold + extension_gold
    if Counter(row["category"] for row in combined_gold) != Counter(FINAL_QUOTAS):
        raise ValueError("Composite category quotas changed")
    if sorted(
        {
            session
            for row in combined_gold
            for session in row["gold_evidence_sessions"]
        }
    ) != list(range(1, 31)):
        raise ValueError("Composite main-60 no longer covers all 30 sessions")
    if any(
        row["non_adversarial_order"] in DEFECTIVE_ORDERS for row in extension_gold
    ):
        raise ValueError("A catalogued defective-gold question entered extension-20")

    # Re-run the outcome-blind selector against the frozen sources.
    _, reliable = _annotated_reliable_pool(root / manifest["source"]["locomo10_path"])
    regenerated = _select_extension(reliable, core_ids | dev_ids)
    if [row["question_id"] for row in regenerated] != list(EXPECTED_EXTENSION_IDS):
        raise ValueError("Extension selector is not reproducible")

    checks = [
        "frozen main-40-v1 parent files and hashes unchanged",
        "20 unique extension questions with quotas 3/3/0/14",
        "extension is disjoint from main-40 and dev-6",
        "no adversarial or four catalogued defective-gold questions",
        "selection uses only category and SHA-256-ranked question IDs",
        "extension input contains no answer, category, or gold evidence fields",
        "main-60 positions 1-40 preserve the original main-40 identity and order",
        "main-60 positions 41-60 append the deterministic extension order",
        "combined category quotas are 13/13/7/27",
        "combined gold evidence still covers all 30 sessions",
        "all output, parent, development, and source hashes match",
    ]
    return {
        "schema_version": 2,
        "status": "passed",
        "composite_question_set_id": COMPOSITE_SET_ID,
        "extension_question_set_id": EXTENSION_SET_ID,
        "checks": checks,
        "extension_question_ids": list(EXPECTED_EXTENSION_IDS),
        "manifest_sha256": _file_sha256(output / "manifest.json"),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", type=Path, default=Path.cwd())
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("experiments/locomo-conv50-v1/question-sets-main60-v2"),
    )
    parser.add_argument("--verify-only", action="store_true")
    args = parser.parse_args()
    if args.verify_only:
        result = verify_question_sets_v2(args.repo_root, args.output)
    else:
        result = build_question_sets_v2(args.repo_root, args.output)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
