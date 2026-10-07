"""Deterministically build the frozen LoCoMo conv-50 question subsets.

The online input is physically separated from category labels, gold answers,
and gold evidence.  Selection uses only frozen metadata and SHA-256 ranking;
it never uses model outputs or answer text.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections import Counter
from pathlib import Path
from typing import Any


CONVERSATION_ID = "conv-50"
MAIN_SET_ID = "locomo-conv50-main40-v1"
DEV_SET_ID = "locomo-conv50-dev6-v1"
SELECTION_SEED = 42
RUN_ORDER_SEED = 42
DEVELOPMENT_SEED = 42
DEFECTIVE_ORDERS = {20, 64, 112, 138}
MAIN_QUOTAS = {1: 10, 2: 10, 3: 7, 4: 13}
DEV_QUOTAS = {1: 2, 2: 2, 4: 2}
CAPTION_QUOTAS = {1: 7, 2: 4, 3: 4, 4: 5}
CATEGORY_NAMES = {
    1: "multi-hop",
    2: "temporal",
    3: "open-domain",
    4: "single-hop",
}
EXPECTED_DEFECTIVE_QUESTIONS = {
    20: "Which places or events has Calvin visited in Tokyo?",
    64: "What style of guitars does Calvin own?",
    112: "Which Disney movie did Dave mention as one of his favorites?",
    138: "When did Calvin first get interested in cars?",
}
FORBIDDEN_ONLINE_KEYS = {
    "answer",
    "evidence",
    "gold_evidence_dia_ids",
    "gold_evidence_locators",
    "category",
    "category_name",
}


def _canonical_json(value: Any) -> bytes:
    text = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return (text + "\n").encode("utf-8")


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _file_sha256(path: Path) -> str:
    return _sha256(path.read_bytes())


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text().splitlines() if line]


def _write_json(path: Path, value: Any) -> None:
    path.write_bytes(_canonical_json(value))


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.write_bytes(b"".join(_canonical_json(row) for row in rows))


def _evidence_sessions(item: dict[str, Any]) -> set[int]:
    sessions: set[int] = set()
    for dia_id in item.get("evidence", []):
        # Official LoCoMo has one documented zero-padded alias, D30:05.
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


def _rank(seed: int, label: str, question_id: str) -> bytes:
    return hashlib.sha256(f"{seed}|{label}|{question_id}".encode()).digest()


def build_question_sets(repo_root: Path, output_dir: Path) -> dict[str, Any]:
    """Generate the frozen main-40 and disjoint dev-6 artifacts."""
    root = repo_root.resolve()
    output = output_dir.resolve()
    raw_path = root / "data/raw/locomo10.json"
    canonical_path = root / "data/processed/conv-50.jsonl"
    source_map_path = root / "data/manifests/source_map.json"

    raw = json.loads(raw_path.read_text())
    conversation = next(row for row in raw if row.get("sample_id") == CONVERSATION_ID)
    source_map = json.loads(source_map_path.read_text())
    records = _load_jsonl(canonical_path)
    by_dia_id = {record["dia_id"]: record for record in records}
    aliases = {
        alias: value["canonical_dia_id"]
        for alias, value in source_map.get("dia_id_aliases", {}).items()
    }

    def normalize_dia_id(dia_id: str) -> str:
        return aliases.get(dia_id, dia_id)

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
    for order, expected in EXPECTED_DEFECTIVE_QUESTIONS.items():
        if annotated[order - 1]["question"] != expected:
            raise ValueError(f"Defective-gold catalog drifted at order {order}")

    eligible = [
        item
        for item in annotated
        if item["non_adversarial_order"] not in DEFECTIVE_ORDERS
    ]
    if Counter(item["category"] for item in eligible) != Counter(
        {1: 30, 2: 32, 3: 7, 4: 85}
    ):
        raise ValueError("Reliable-pool category counts changed")

    def has_caption_evidence(item: dict[str, Any]) -> bool:
        return any(
            bool(
                (by_dia_id[normalize_dia_id(dia_id)].get("media") or {}).get(
                    "blip_caption"
                )
            )
            for dia_id in item.get("evidence", [])
        )

    def candidate_is_valid(selected: list[dict[str, Any]]) -> bool:
        if Counter(row["category"] for row in selected) != Counter(MAIN_QUOTAS):
            return False
        sessions = set().union(*(_evidence_sessions(row) for row in selected))
        if sessions != set(range(1, 31)):
            return False
        captions = Counter(
            row["category"] for row in selected if has_caption_evidence(row)
        )
        if any(captions[category] != count for category, count in CAPTION_QUOTAS.items()):
            return False
        for category in (1, 2, 4):
            presence = Counter(
                _zone(session)
                for row in selected
                if row["category"] == category
                for session in _evidence_sessions(row)
            )
            if any(presence[name] < 2 for name in ("early", "middle", "late")):
                return False
        open_domain_zones = {
            _zone(session)
            for row in selected
            if row["category"] == 3
            for session in _evidence_sessions(row)
        }
        return open_domain_zones == {"early", "middle", "late"}

    by_category = {
        category: [row for row in eligible if row["category"] == category]
        for category in CATEGORY_NAMES
    }
    selected: list[dict[str, Any]] | None = None
    accepted_candidate = 0
    for candidate_number in range(1, 1_000_001):
        candidate: list[dict[str, Any]] = []
        for category in CATEGORY_NAMES:
            ranked = sorted(
                by_category[category],
                key=lambda row, c=category: _rank(
                    SELECTION_SEED,
                    f"candidate-{candidate_number}|category-{c}",
                    row["question_id"],
                ),
            )
            candidate.extend(ranked[: MAIN_QUOTAS[category]])
        if candidate_is_valid(candidate):
            selected = candidate
            accepted_candidate = candidate_number
            break
    if selected is None:
        raise ValueError("No question sample met the frozen coverage constraints")

    run_order = sorted(
        selected,
        key=lambda row: _rank(RUN_ORDER_SEED, "run-order", row["question_id"]),
    )
    selected_ids = {row["question_id"] for row in selected}
    development: list[dict[str, Any]] = []
    for category, count in DEV_QUOTAS.items():
        pool = [
            row for row in by_category[category] if row["question_id"] not in selected_ids
        ]
        pool.sort(
            key=lambda row, c=category: _rank(
                DEVELOPMENT_SEED, f"development-{c}", row["question_id"]
            )
        )
        development.extend(pool[:count])
    development.sort(
        key=lambda row: _rank(
            DEVELOPMENT_SEED, "development-run-order", row["question_id"]
        )
    )

    def input_rows(items: list[dict[str, Any]], set_id: str) -> list[dict[str, Any]]:
        return [
            {
                "schema_version": 1,
                "question_set_id": set_id,
                "run_position": position,
                "question_id": row["question_id"],
                "conversation_id": CONVERSATION_ID,
                "question": row["question"],
            }
            for position, row in enumerate(items, start=1)
        ]

    def gold_rows(items: list[dict[str, Any]], set_id: str) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []
        for row in items:
            official_ids = list(row.get("evidence", []))
            canonical_ids = [normalize_dia_id(dia_id) for dia_id in official_ids]
            if any(dia_id not in source_map["by_dia_id"] for dia_id in canonical_ids):
                raise ValueError(f"Unresolved evidence ID in {row['question_id']}")
            result.append(
                {
                    "schema_version": 1,
                    "question_set_id": set_id,
                    "question_id": row["question_id"],
                    "source_qa_index": row["source_qa_index"],
                    "non_adversarial_order": row["non_adversarial_order"],
                    "category": row["category"],
                    "category_name": CATEGORY_NAMES[row["category"]],
                    "answer": row["answer"],
                    "gold_evidence_dia_ids_official": official_ids,
                    "gold_evidence_dia_ids": canonical_ids,
                    "gold_evidence_locators": [
                        source_map["by_dia_id"][dia_id]["locator"]
                        for dia_id in canonical_ids
                    ],
                    "gold_evidence_sessions": sorted(_evidence_sessions(row)),
                    "has_caption_evidence": has_caption_evidence(row),
                }
            )
        return result

    main_input = input_rows(run_order, MAIN_SET_ID)
    main_gold = gold_rows(run_order, MAIN_SET_ID)
    dev_input = input_rows(development, DEV_SET_ID)
    dev_gold = gold_rows(development, DEV_SET_ID)
    gold_by_id = {row["question_id"]: row for row in main_gold}

    audit = [
        "# LoCoMo conv-50 main-40 audit view",
        "",
        "This is a human review view, not an online model input. Gold answers are kept only in `main-40-gold.jsonl`.",
        "",
        "| Run | Question ID | Category | Source QA | Non-adversarial order | Caption evidence | Evidence sessions | Question |",
        "| ---: | --- | --- | ---: | ---: | --- | --- | --- |",
    ]
    for row in main_input:
        gold = gold_by_id[row["question_id"]]
        question = row["question"].replace("|", "\\|").replace("\n", " ")
        sessions = ", ".join(map(str, gold["gold_evidence_sessions"])) or "none"
        audit.append(
            f"| {row['run_position']} | `{row['question_id']}` | {gold['category_name']} | "
            f"{gold['source_qa_index']} | {gold['non_adversarial_order']} | "
            f"{'yes' if gold['has_caption_evidence'] else 'no'} | {sessions} | {question} |"
        )

    output.mkdir(parents=True, exist_ok=True)
    paths = {
        "main_input": output / "main-40-input.jsonl",
        "main_gold": output / "main-40-gold.jsonl",
        "development_input": output / "dev-6-input.jsonl",
        "development_gold": output / "dev-6-gold.jsonl",
        "main_audit": output / "main-40-audit.md",
    }
    _write_jsonl(paths["main_input"], main_input)
    _write_jsonl(paths["main_gold"], main_gold)
    _write_jsonl(paths["development_input"], dev_input)
    _write_jsonl(paths["development_gold"], dev_gold)
    paths["main_audit"].write_text("\n".join(audit) + "\n")

    category_counts = Counter(row["category"] for row in main_gold)
    covered_sessions = sorted(
        {session for row in main_gold for session in row["gold_evidence_sessions"]}
    )
    text_only = sum(
        bool(row["gold_evidence_dia_ids"]) and not row["has_caption_evidence"]
        for row in main_gold
    )
    zero_evidence = sum(not row["gold_evidence_dia_ids"] for row in main_gold)
    manifest = {
        "schema_version": 1,
        "artifact_id": "locomo-conv50-question-subsets-v1",
        "status": "frozen",
        "generator": "fs_memory_lab.question_sets:v1",
        "source": {
            "conversation_id": CONVERSATION_ID,
            "locomo10_path": "data/raw/locomo10.json",
            "locomo10_sha256": _file_sha256(raw_path),
            "canonical_records_path": "data/processed/conv-50.jsonl",
            "canonical_records_sha256": _file_sha256(canonical_path),
            "source_map_path": "data/manifests/source_map.json",
            "source_map_sha256": _file_sha256(source_map_path),
        },
        "eligibility": {
            "official_qa_count": len(conversation["qa"]),
            "non_adversarial_count": len(annotated),
            "defective_non_adversarial_orders_excluded": sorted(DEFECTIVE_ORDERS),
            "reliable_pool_count": len(eligible),
            "reliable_pool_category_counts": {
                str(k): v
                for k, v in sorted(Counter(row["category"] for row in eligible).items())
            },
        },
        "selection": {
            "selection_seed": SELECTION_SEED,
            "selection_algorithm": "sha256-rank-v1",
            "accepted_candidate_number": accepted_candidate,
            "main_quotas": {str(k): v for k, v in MAIN_QUOTAS.items()},
            "caption_quotas": {str(k): v for k, v in CAPTION_QUOTAS.items()},
            "coverage_constraints": {
                "gold_evidence_sessions": "all 30 sessions",
                "history_zones": "early, middle, late represented within every category",
                "caption_evidence": "exactly 20 questions",
                "selection_uses_model_results": False,
                "selection_uses_answer_text": False,
            },
            "run_order_seed": RUN_ORDER_SEED,
            "development_seed": DEVELOPMENT_SEED,
            "development_quotas": {str(k): v for k, v in DEV_QUOTAS.items()},
        },
        "verified_counts": {
            "main_questions": len(main_input),
            "development_questions": len(dev_input),
            "main_category_counts": {
                str(k): v for k, v in sorted(category_counts.items())
            },
            "main_caption_evidence_questions": sum(
                row["has_caption_evidence"] for row in main_gold
            ),
            "main_text_only_evidence_questions": text_only,
            "main_zero_gold_evidence_questions": zero_evidence,
            "main_gold_evidence_sessions": covered_sessions,
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
    verification = verify_question_sets(root, output)
    _write_json(output / "verification.json", verification)
    return {"manifest": manifest, "verification": verification}


def verify_question_sets(repo_root: Path, output_dir: Path) -> dict[str, Any]:
    """Verify hashes, source bindings, leakage separation, and frozen coverage."""
    root = repo_root.resolve()
    output = output_dir.resolve()
    manifest = json.loads((output / "manifest.json").read_text())
    main_input = _load_jsonl(output / "main-40-input.jsonl")
    main_gold = _load_jsonl(output / "main-40-gold.jsonl")
    dev_input = _load_jsonl(output / "dev-6-input.jsonl")
    dev_gold = _load_jsonl(output / "dev-6-gold.jsonl")

    for meta in manifest["outputs"].values():
        path = output / meta["filename"]
        if _file_sha256(path) != meta["sha256"] or path.stat().st_size != meta["bytes"]:
            raise ValueError(f"Question-set artifact hash mismatch: {path.name}")
    source = manifest["source"]
    for path_key, hash_key in (
        ("locomo10_path", "locomo10_sha256"),
        ("canonical_records_path", "canonical_records_sha256"),
        ("source_map_path", "source_map_sha256"),
    ):
        if _file_sha256(root / source[path_key]) != source[hash_key]:
            raise ValueError(f"Question-set source hash mismatch: {source[path_key]}")

    if len(main_input) != 40 or len(main_gold) != 40:
        raise ValueError("Main question set must contain 40 rows")
    if Counter(row["category"] for row in main_gold) != Counter(MAIN_QUOTAS):
        raise ValueError("Main question category quotas changed")
    if any(FORBIDDEN_ONLINE_KEYS & row.keys() for row in main_input):
        raise ValueError("Online question input contains hidden evaluation fields")
    if [row["question_id"] for row in main_input] != [
        row["question_id"] for row in main_gold
    ]:
        raise ValueError("Online and gold rows are not aligned")
    if len({row["question_id"] for row in main_input}) != 40:
        raise ValueError("Main question IDs are not unique")
    if any(row["non_adversarial_order"] in DEFECTIVE_ORDERS for row in main_gold):
        raise ValueError("Defective-gold question entered the main set")
    if sorted(
        {session for row in main_gold for session in row["gold_evidence_sessions"]}
    ) != list(range(1, 31)):
        raise ValueError("Main set no longer covers all 30 evidence sessions")
    if sum(row["has_caption_evidence"] for row in main_gold) != 20:
        raise ValueError("Main caption-evidence coverage changed")
    if len(dev_input) != 6 or len(dev_gold) != 6:
        raise ValueError("Development set must contain six rows")
    if Counter(row["category"] for row in dev_gold) != Counter(DEV_QUOTAS):
        raise ValueError("Development question category quotas changed")
    if {row["question_id"] for row in main_input} & {
        row["question_id"] for row in dev_input
    }:
        raise ValueError("Development and main sets overlap")

    return {
        "status": "passed",
        "checks": [
            "40 unique main questions",
            "category quotas 10/10/7/13",
            "no adversarial questions",
            "four catalogued defective golds excluded",
            "all 30 evidence sessions covered",
            "20 caption-evidence, 18 text-only, 2 zero-gold-evidence questions",
            "online input contains no answer, category, or gold evidence fields",
            "six development questions are disjoint from the main set",
            "all output and source hashes match the frozen manifest",
        ],
        "manifest_sha256": _file_sha256(output / "manifest.json"),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", type=Path, default=Path.cwd())
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("experiments/locomo-conv50-v1/question-sets"),
    )
    parser.add_argument("--verify-only", action="store_true")
    args = parser.parse_args()
    if args.verify_only:
        result = verify_question_sets(args.repo_root, args.output)
    else:
        result = build_question_sets(args.repo_root, args.output)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
