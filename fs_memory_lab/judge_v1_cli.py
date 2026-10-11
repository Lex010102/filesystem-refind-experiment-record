"""CLI for the supplemental anonymous semantic judge."""

from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path

from .agent import CompatibleChatProvider
from .judge_v1 import (
    dry_run_judge,
    finalize_judge_run,
    prepare_judge_run,
    run_judge,
    verify_judge_run,
    write_judge_status,
)


def _git_head(repo_root: Path) -> str:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=repo_root,
        check=True, capture_output=True, text=True,
    )
    commit = result.stdout.strip()
    for relative in ("fs_memory_lab/judge_v1.py", "fs_memory_lab/judge_v1_cli.py"):
        tracked = subprocess.run(
            ["git", "ls-files", "--error-unmatch", relative], cwd=repo_root,
            capture_output=True, text=True,
        )
        clean = subprocess.run(
            ["git", "diff", "--quiet", "HEAD", "--", relative], cwd=repo_root,
        )
        if tracked.returncode != 0 or clean.returncode != 0:
            raise RuntimeError("Commit judge-v1 code before preparing its immutable run")
    return commit


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Checkpointed E1-E7 anonymous LLM judge")
    parser.add_argument("--repo-root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--source-output-root", type=Path, required=True)
    parser.add_argument("--source-run-id", required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--judge-run-id", required=True)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("prepare")
    sub.add_parser("dry-run")
    sub.add_parser("status")
    run = sub.add_parser("run")
    run.add_argument("--through-batch", type=int, choices=range(1, 9), required=True)
    sub.add_parser("verify")
    sub.add_parser("finalize")
    return parser


def main(argv: list[str] | None = None) -> None:
    args = _parser().parse_args(argv)
    root = args.repo_root.resolve()
    common = {
        "repo_root": root,
        "source_output_root": args.source_output_root.resolve(),
        "source_run_id": args.source_run_id,
        "output_root": args.output_root.resolve(),
        "judge_run_id": args.judge_run_id,
    }
    if args.command == "prepare":
        result = {"status": "prepared", "manifest": str(prepare_judge_run(**common, implementation_commit=_git_head(root)))}
    elif args.command == "dry-run":
        result = dry_run_judge(**common)
    elif args.command == "status":
        result = write_judge_status(**common)
    elif args.command == "run":
        result = run_judge(
            **common, provider=CompatibleChatProvider.from_environment(),
            through_batch=args.through_batch,
        )
    elif args.command == "verify":
        result = verify_judge_run(**common)
    else:
        result = finalize_judge_run(**common)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if result.get("status") == "failed":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
