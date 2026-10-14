"""CLI for the Qwen extension-20 formal answer run; no Judge command exists."""

from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path

from .agent import CompatibleChatProvider
from .formal_v2_extension import (
    dry_run,
    prepare_run,
    run,
    verify_completed_run,
    write_status,
)


def _git_head(repo_root: Path) -> str:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repo_root,
        check=True,
        capture_output=True,
        text=True,
    )
    required_paths = (
        "fs_memory_lab/formal_v2_extension.py",
        "fs_memory_lab/formal_v2_extension_cli.py",
        "experiments/locomo-conv50-v1/question-sets-main60-v2/extension-20-input.jsonl",
        "experiments/locomo-conv50-v1/question-sets-main60-v2/extension-20-gold.jsonl",
        "experiments/locomo-conv50-v1/question-sets-main60-v2/main-60-composition.json",
        "experiments/locomo-conv50-v1/question-sets-main60-v2/manifest.json",
        "experiments/locomo-conv50-v1/question-sets-main60-v2/verification.json",
    )
    for relative in required_paths:
        tracked = subprocess.run(
            ["git", "ls-files", "--error-unmatch", relative],
            cwd=repo_root,
            capture_output=True,
            text=True,
        )
        clean = subprocess.run(
            ["git", "diff", "--quiet", "HEAD", "--", relative], cwd=repo_root
        )
        if tracked.returncode != 0 or clean.returncode != 0:
            raise RuntimeError(
                f"Commit the frozen extension implementation first: {relative}"
            )
    return result.stdout.strip()


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Formal-v2 Qwen extension-20 runner; parameters are frozen"
    )
    parser.add_argument(
        "--repo-root", type=Path, default=Path(__file__).resolve().parents[1]
    )
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--run-id", required=True)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("prepare", help="freeze the 140-key plan; no API")
    sub.add_parser("dry-run", help="verify inputs and schedule; no API")
    sub.add_parser("status", help="verify checkpoint without API or gold")
    execute = sub.add_parser("run", help="run or resume through one batch boundary")
    execute.add_argument("--through-block", type=int, choices=range(1, 5), required=True)
    sub.add_parser("verify", help="require 140/140 and run pre-gold audit")
    return parser


def main(argv: list[str] | None = None) -> None:
    args = _parser().parse_args(argv)
    root = args.repo_root.resolve()
    output = args.output_root.resolve()
    common = {"repo_root": root, "output_root": output, "run_id": args.run_id}
    if args.command == "prepare":
        path = prepare_run(
            **common, implementation_commit=_git_head(root)
        )
        result = {"status": "prepared", "manifest": str(path)}
    elif args.command == "dry-run":
        result = dry_run(**common)
    elif args.command == "status":
        result = write_status(**common)
    elif args.command == "run":
        result = run(
            **common,
            provider=CompatibleChatProvider.from_environment(),
            through_block=args.through_block,
        )
    else:
        result = verify_completed_run(**common)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
