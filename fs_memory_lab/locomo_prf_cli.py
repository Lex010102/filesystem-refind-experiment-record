"""Aggregate LoCoMo token precision, recall, and official F1 offline.

The official LoCoMo evaluator exposes the category-aware F1 calculation.  This
module pairs that score with the token precision/recall diagnostics used by the
project's existing reports.  It deliberately writes aggregate metrics only: no
question, candidate answer, reference answer, or evidence text is persisted.
"""

from __future__ import annotations

import argparse
import json
import os
import secrets
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence

from .evaluation import (
    EVALUATION_PROTOCOL_VERSION,
    LOCOMO_EVALUATOR_COMMIT,
    LOCOMO_EVALUATOR_PATH,
    LOCOMO_EVALUATOR_REPOSITORY,
    LOCOMO_EVALUATOR_SHA256,
    LOCOMO_NLTK_VERSION,
    load_gold_records,
    locomo_category_f1,
    locomo_f1_score,
    normalize_answer,
)
from .evidence import EvidenceValidationError, canonical_json_bytes, sha256_bytes
from .run_records import verify_run_store
from .vendor.locomo_porter import PorterStemmer


PRF_PROTOCOL_VERSION = "locomo-e1-e7-prf-summary-v1"
_STEMMER = PorterStemmer()


@dataclass(frozen=True)
class ScorePartition:
    run_root: Path
    run_id: str
    gold_path: Path
    gold_sha256: str


def _token_precision_recall(prediction: str, truth: str) -> tuple[float, float]:
    predicted = [_STEMMER.stem(token) for token in normalize_answer(prediction).split()]
    expected = [_STEMMER.stem(token) for token in normalize_answer(truth).split()]
    common = sum((Counter(predicted) & Counter(expected)).values())
    precision = common / len(predicted) if predicted else 0.0
    recall = common / len(expected) if expected else 0.0
    return precision, recall


def _category_precision_recall(
    prediction: str, truth: str, category: int
) -> tuple[float, float]:
    if category == 1:
        candidates = prediction.split(",")
        truths = truth.split(",")
        matches: list[tuple[float, float]] = []
        for item in truths:
            # ``max`` retains the first candidate on ties, matching the stable
            # best-candidate selection used in the previously reported scores.
            best = max(candidates, key=lambda candidate: locomo_f1_score(candidate, item))
            matches.append(_token_precision_recall(best, item))
        return (
            sum(value[0] for value in matches) / len(matches),
            sum(value[1] for value in matches) / len(matches),
        )
    if category == 3:
        truth = truth.split(";")[0].strip()
    return _token_precision_recall(prediction, truth)


def _mean(values: Sequence[float]) -> float | None:
    return sum(values) / len(values) if values else None


def build_prf_summary(
    partitions: Sequence[ScorePartition], *, formal_eligibility: str
) -> dict[str, Any]:
    if not partitions:
        raise EvidenceValidationError("At least one scoring partition is required")
    rows: list[dict[str, Any]] = []
    partition_rows: list[dict[str, Any]] = []
    identities: set[tuple[str, str]] = set()

    for partition in partitions:
        store, checkpoint = verify_run_store(partition.run_root, partition.run_id)
        if checkpoint["pending"] != 0 or checkpoint["completed"] != checkpoint["planned"]:
            raise EvidenceValidationError("Run store is incomplete and cannot be scored")
        gold_records = load_gold_records(
            partition.gold_path, expected_sha256=partition.gold_sha256
        )
        gold_by_question = {record.question_id: record for record in gold_records}
        if (
            {record.question_set_id for record in gold_records}
            != {store.plan.question_set_id}
            or set(gold_by_question) != set(store.plan.question_ids)
        ):
            raise EvidenceValidationError("Frozen plan and gold question set differ")

        before = len(rows)
        for key in store.plan.execution_order:
            identity = (key.condition_id, key.question_id)
            if identity in identities:
                raise EvidenceValidationError("Combined scoring rows are not unique")
            identities.add(identity)
            record = store.load_completed(key)
            if record is None:
                raise EvidenceValidationError("Run record disappeared during scoring")
            reference = gold_by_question[key.question_id]
            precision, recall = _category_precision_recall(
                record.answer_result.answer, reference.answer, reference.category
            )
            rows.append(
                {
                    "condition_id": key.condition_id,
                    "category": reference.category,
                    "precision": precision,
                    "recall": recall,
                    "f1": locomo_category_f1(
                        record.answer_result.answer, reference.answer, reference.category
                    ),
                }
            )
        partition_rows.append(
            {
                "run_id": partition.run_id,
                "record_count": len(rows) - before,
                "gold_sha256": partition.gold_sha256,
            }
        )

    def aggregate(members: Sequence[dict[str, Any]]) -> dict[str, Any]:
        return {
            "count": len(members),
            "precision": _mean([float(row["precision"]) for row in members]),
            "recall": _mean([float(row["recall"]) for row in members]),
            "f1": _mean([float(row["f1"]) for row in members]),
        }

    conditions: dict[str, Any] = {}
    for condition in sorted({str(row["condition_id"]) for row in rows}):
        members = [row for row in rows if row["condition_id"] == condition]
        conditions[condition] = {
            **aggregate(members),
            "categories": {
                str(category): aggregate(
                    [row for row in members if row["category"] == category]
                )
                for category in (1, 2, 3, 4)
            },
        }

    body = {
        "schema_version": 1,
        "protocol_version": PRF_PROTOCOL_VERSION,
        "f1_protocol_version": EVALUATION_PROTOCOL_VERSION,
        "status": "passed",
        "formal_eligibility": formal_eligibility,
        "row_count": len(rows),
        "partitions": partition_rows,
        "overall": aggregate(rows),
        "conditions": conditions,
        "official_evaluator": {
            "repository": LOCOMO_EVALUATOR_REPOSITORY,
            "commit": LOCOMO_EVALUATOR_COMMIT,
            "path": LOCOMO_EVALUATOR_PATH,
            "sha256": LOCOMO_EVALUATOR_SHA256,
            "nltk_version": LOCOMO_NLTK_VERSION,
        },
        "metric_note": (
            "F1 is the pinned official LoCoMo category-aware score. Precision and "
            "recall are token-overlap diagnostics using the same normalization, "
            "stemming, C1 best-match rule, and C3 reference truncation."
        ),
        "contains_question_or_answer_text": False,
        "api_calls": 0,
    }
    return {**body, "report_id": "prf-" + sha256_bytes(canonical_json_bytes(body))}


def write_prf_summary(path: Path, report: dict[str, Any]) -> Path:
    path = path.resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() or path.is_symlink():
        raise EvidenceValidationError("PRF summary already exists")
    payload = canonical_json_bytes(report) + b"\n"
    staging = path.parent / f".{path.name}.in-progress-{secrets.token_hex(8)}"
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(staging, flags, 0o600)
    try:
        offset = 0
        while offset < len(payload):
            written = os.write(descriptor, payload[offset:])
            if written <= 0:
                raise OSError("short PRF summary write")
            offset += written
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    try:
        os.link(staging, path)
        directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        staging.unlink(missing_ok=True)
    return path


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Aggregate official LoCoMo F1 and matching token P/R diagnostics."
    )
    parser.add_argument(
        "--partition",
        action="append",
        nargs=4,
        metavar=("RUN_ROOT", "RUN_ID", "GOLD", "GOLD_SHA256"),
        required=True,
    )
    parser.add_argument("--formal-eligibility", required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    partitions = [
        ScorePartition(Path(run_root), run_id, Path(gold), gold_sha256)
        for run_root, run_id, gold, gold_sha256 in args.partition
    ]
    report = build_prf_summary(
        partitions, formal_eligibility=args.formal_eligibility
    )
    output = write_prf_summary(args.output, report)
    print(
        json.dumps(
            {
                "status": report["status"],
                "row_count": report["row_count"],
                "output": str(output),
                "api_calls": 0,
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
