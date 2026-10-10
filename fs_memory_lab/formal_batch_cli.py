"""CLI for formal-v1 main-40 preparation, dry-run, execution, and scoring."""

from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path

from .agent import CompatibleChatProvider
from .formal_batch import (
    dry_run_formal,
    finalize_formal_run,
    prepare_formal_run,
    run_formal,
    verify_formal_run,
    write_formal_status,
)


def _git_head(repo_root: Path) -> str:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repo_root,
        check=True,
        capture_output=True,
        text=True,
    )
    commit = result.stdout.strip()
    tracked = subprocess.run(
        ["git", "ls-files", "--error-unmatch", "fs_memory_lab/formal_batch.py"],
        cwd=repo_root,
        capture_output=True,
        text=True,
    )
    clean = subprocess.run(
        ["git", "diff", "--quiet", "HEAD", "--", "fs_memory_lab/formal_batch.py"],
        cwd=repo_root,
    )
    if tracked.returncode != 0 or clean.returncode != 0:
        raise RuntimeError(
            "Commit formal_batch.py before preparing the immutable formal run"
        )
    return commit


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Formal-v1 main-40 runner; method parameters are not overridable"
    )
    parser.add_argument("--repo-root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--run-id", required=True)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("prepare", help="freeze the 280-key plan; no API")
    sub.add_parser("dry-run", help="verify inputs and schedule; no API")
    sub.add_parser("status", help="verify checkpoint without API or gold")
    sub.add_parser("run", help="run or explicitly resume pending records via API")
    sub.add_parser("verify", help="require 280/280 and perform pre-gold audit")
    sub.add_parser("finalize", help="after verify, load gold and score; no judge")
    return parser


def main(argv: list[str] | None = None) -> None:
    args = _parser().parse_args(argv)
    root = args.repo_root.resolve()
    output = args.output_root.resolve()
    common = {"repo_root": root, "output_root": output, "run_id": args.run_id}
    if args.command == "prepare":
        path = prepare_formal_run(
            **common, orchestrator_commit=_git_head(root)
        )
        result = {"status": "prepared", "manifest": str(path)}
    elif args.command == "dry-run":
        result = dry_run_formal(**common)
    elif args.command == "status":
        result = write_formal_status(**common)
    elif args.command == "run":
        result = run_formal(
            **common, provider=CompatibleChatProvider.from_environment()
        )
    elif args.command == "verify":
        result = verify_formal_run(**common)
    else:
        result = finalize_formal_run(**common)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
