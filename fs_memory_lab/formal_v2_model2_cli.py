"""Control CLI for the independent Model 2 main-60 suite.

The only online command is ``run-child``.  The runner itself enforces the
immutable suite, preflight/dry-run gate, model identity, and single-process
locks before the first provider request.
"""

from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path

from .formal_v2_model2 import (
    MODEL2_REQUESTED_MODEL_ALIAS,
    MODEL2_REQUIRED_SERVED_MODEL,
    prepare_suite,
    run_child_with_recovery,
    resume_window,
    verify_pre_gold,
    write_batch_audit,
    write_suite_status,
)
from .model2_preflight import load_model2_provider_from_environment


def _git_head(repo_root: Path) -> str:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repo_root,
        check=True,
        capture_output=True,
        text=True,
    )
    for relative in (
        "fs_memory_lab/formal_v2_model2.py",
        "fs_memory_lab/formal_v2_model2_cli.py",
    ):
        tracked = subprocess.run(
            ["git", "ls-files", "--error-unmatch", relative],
            cwd=repo_root,
            capture_output=True,
            text=True,
        )
        clean = subprocess.run(
            ["git", "diff", "--quiet", "HEAD", "--", relative],
            cwd=repo_root,
        )
        if tracked.returncode != 0 or clean.returncode != 0:
            raise RuntimeError(f"Commit the Model 2 control code first: {relative}")
    return result.stdout.strip()


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Model 2 main-60 suite control")
    parser.add_argument(
        "--repo-root", type=Path, default=Path(__file__).resolve().parents[1]
    )
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--suite-id", required=True)
    sub = parser.add_subparsers(dest="command", required=True)

    prepare = sub.add_parser("prepare", help="freeze two child plans; no API")
    prepare.add_argument(
        "--requested-model-alias", default=MODEL2_REQUESTED_MODEL_ALIAS
    )
    prepare.add_argument(
        "--required-served-model", default=MODEL2_REQUIRED_SERVED_MODEL
    )
    prepare.add_argument("--models-check-report", type=Path, required=True)
    prepare.add_argument("--role-smoke-report", type=Path, required=True)

    sub.add_parser("status", help="verify both checkpoints; no API")
    resume = sub.add_parser("resume-plan", help="show pending keys; no API")
    resume.add_argument("--through-batch", type=int, choices=range(1, 13), required=True)
    audit = sub.add_parser("audit-batch", help="audit a completed global batch")
    audit.add_argument("--global-batch", type=int, choices=range(1, 13), required=True)
    run = sub.add_parser(
        "run-child", help="run/resume one gated child through a local block"
    )
    run.add_argument("--child", choices=("main40", "extension20"), required=True)
    run.add_argument("--through-block", type=int, choices=range(1, 9), required=True)
    sub.add_parser("verify", help="require 420/420 and emit pre-gold marker")
    return parser


def main(argv: list[str] | None = None) -> None:
    parser = _parser()
    args = parser.parse_args(argv)
    if (
        args.command == "run-child"
        and args.child == "extension20"
        and args.through_block > 4
    ):
        parser.error("extension20 through-block must be between 1 and 4")
    root = args.repo_root.resolve()
    output = args.output_root.resolve()
    common = {"repo_root": root, "output_root": output, "suite_id": args.suite_id}
    if args.command == "prepare":
        path = prepare_suite(
            **common,
            implementation_commit=_git_head(root),
            requested_model_alias=args.requested_model_alias,
            required_served_model=args.required_served_model,
            models_check_report_path=args.models_check_report,
            role_smoke_report_path=args.role_smoke_report,
        )
        result = {"status": "prepared", "manifest": str(path)}
    elif args.command == "status":
        result = write_suite_status(**common)
    elif args.command == "resume-plan":
        result = resume_window(**common, through_batch=args.through_batch)
    elif args.command == "audit-batch":
        result = write_batch_audit(**common, global_batch=args.global_batch)
    elif args.command == "run-child":
        result = run_child_with_recovery(
            **common,
            child_id=args.child,
            through_block=args.through_block,
            provider=load_model2_provider_from_environment(),
        )
    else:
        result = verify_pre_gold(**common)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
