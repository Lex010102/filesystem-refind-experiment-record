"""Command-line entry points for evidence-only R1 retrieval."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from .agent import CompatibleChatProvider
from .evidence import EvidenceValidationError
from .paper_config import SEARCH
from .r1_agent import R1_AGENT_LIMITS
from .r1_artifacts import (
    verify_r1_episode_artifact,
    verify_r1_failure_artifact,
)
from .r1_inputs import load_question_inputs, load_r1_store
from .r1_prompts import R1_PROMPT_PROFILES
from .r1_runner import (
    execute_r1_batch,
    execute_r1_question,
    verify_r1_batch_summary,
)


def _question(repo_root: Path, question_set: str, question_id: str):
    questions = load_question_inputs(repo_root, question_set)
    matches = [item for item in questions if item.question_id == question_id]
    if len(matches) != 1:
        raise EvidenceValidationError(
            "question_id is not present exactly once in the selected set"
        )
    return matches[0]


def _preflight(repo_root: Path) -> dict:
    stores = {}
    for store_id in ("s1", "s2", "s3"):
        loaded = load_r1_store(repo_root, store_id)
        stores[store_id] = {
            "root": str(loaded.root),
            "tree_sha256": loaded.snapshot.tree_sha256,
            "file_count": loaded.snapshot.file_count,
            "total_bytes": loaded.snapshot.total_bytes,
            "manifest_sha256": loaded.snapshot.manifest_sha256,
        }
    sets = {}
    for name in ("dev-6", "main-40"):
        questions = load_question_inputs(repo_root, name)
        sets[name] = {
            "count": len(questions),
            "first_question_id": questions[0].question_id,
            "last_question_id": questions[-1].question_id,
        }
    return {
        "status": "ready",
        "repo_root": str(repo_root),
        "cells": {
            cell: {
                "store_id": profile.store_id,
                "round_limit": profile.hard_round_cap,
                "paper_prompt_number": profile.paper_prompt_number,
            }
            for cell, profile in R1_PROMPT_PROFILES.items()
        },
        "stores": stores,
        "question_sets": sets,
        "shared_token_safety_fuse": {
            "cells": list(R1_PROMPT_PROFILES),
            "unit": R1_AGENT_LIMITS["token_safety_fuse_unit"],
            "limit": R1_AGENT_LIMITS["token_safety_fuse_limit"],
            "scope": R1_AGENT_LIMITS["token_safety_fuse_scope"],
            "file_view_truncation": R1_AGENT_LIMITS["file_view_truncation"],
        },
        "api_called": False,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Verified evidence-only R1 filesystem retrieval"
    )
    parser.add_argument(
        "--repo-root", type=Path, default=Path(__file__).resolve().parents[1]
    )
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("preflight", help="Verify all frozen stores and question sets")

    one = sub.add_parser("run-one", help="Run one API-backed R1 episode")
    one.add_argument("--cell", choices=tuple(R1_PROMPT_PROFILES), required=True)
    one.add_argument("--question-set", choices=("dev-6", "main-40"), required=True)
    one.add_argument("--question-id", required=True)
    one.add_argument("--run-id", required=True)
    one.add_argument("--output-root", type=Path, required=True)
    one.add_argument("--budget-characters", type=int, required=True)

    batch = sub.add_parser("run-batch", help="Run a sequential API-backed R1 batch")
    batch.add_argument(
        "--cells", nargs="+", choices=tuple(R1_PROMPT_PROFILES), required=True
    )
    batch.add_argument("--question-set", choices=("dev-6", "main-40"), required=True)
    batch.add_argument("--run-id", required=True)
    batch.add_argument("--output-root", type=Path, required=True)
    batch.add_argument("--budget-characters", type=int, required=True)
    batch.add_argument(
        "--continue-on-failure",
        action="store_true",
        help="Continue later episodes after one atomically recorded failure",
    )

    verify = sub.add_parser("verify", help="Verify one published R1 artifact offline")
    verify.add_argument("--cell", choices=tuple(R1_PROMPT_PROFILES), required=True)
    verify.add_argument("--artifact", type=Path, required=True)
    verify_batch = sub.add_parser(
        "verify-batch", help="Verify a batch summary and every referenced artifact"
    )
    verify_batch.add_argument("--summary", type=Path, required=True)
    return parser


def main() -> None:
    args = build_parser().parse_args()
    repo_root = args.repo_root.resolve()
    if args.command == "preflight":
        print(json.dumps(_preflight(repo_root), ensure_ascii=False, indent=2))
        return
    if args.command == "verify-batch":
        results = verify_r1_batch_summary(args.summary.resolve(), repo_root=repo_root)
        print(
            json.dumps(
                {
                    "status": "verified",
                    "episode_count": len(results),
                    "artifact_ids": [item.artifact_id for item in results],
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return
    if args.command == "verify":
        loaded = load_r1_store(repo_root, R1_PROMPT_PROFILES[args.cell].store_id)
        artifact = args.artifact.resolve()
        if (artifact / "COMPLETED").is_file():
            value = verify_r1_episode_artifact(artifact, loaded_store=loaded)
            report = {
                "status": "verified",
                "artifact_kind": "evidence_bundle",
                "artifact_id": value.bundle_id,
            }
        elif (artifact / "FAILED").is_file():
            value = verify_r1_failure_artifact(artifact)
            if value.store_snapshot != loaded.snapshot:
                raise EvidenceValidationError(
                    "Failure artifact does not belong to the selected cell store"
                )
            report = {
                "status": "verified",
                "artifact_kind": "retrieval_failure",
                "artifact_id": value.failure_id,
            }
        else:
            raise EvidenceValidationError(
                "Artifact has neither COMPLETED nor FAILED marker"
            )
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return

    provider = CompatibleChatProvider.from_environment()
    requested_model = provider.model or SEARCH.model
    if args.budget_characters < 0:
        raise EvidenceValidationError("budget-characters must be nonnegative")
    if args.command == "run-one":
        result = execute_r1_question(
            repo_root=repo_root,
            output_root=args.output_root,
            run_id=args.run_id,
            cell_id=args.cell,
            question=_question(repo_root, args.question_set, args.question_id),
            provider=provider,
            requested_model=requested_model,
            budget_unit="characters",
            budget_limit=args.budget_characters,
        )
        print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))
        return
    results = execute_r1_batch(
        repo_root=repo_root,
        output_root=args.output_root,
        run_id=args.run_id,
        cell_ids=args.cells,
        questions=load_question_inputs(repo_root, args.question_set),
        provider=provider,
        requested_model=requested_model,
        budget_unit="characters",
        budget_limit=args.budget_characters,
        stop_on_failure=not args.continue_on_failure,
    )
    print(
        json.dumps(
            {
                "status": "finished",
                "episode_count": len(results),
                "results": [item.to_dict() for item in results],
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
