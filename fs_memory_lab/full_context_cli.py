"""Command-line interface for the independent B3 Full Context extension.

Offline commands never construct an API provider.  Online commands read the
existing provider configuration from the process environment and never persist
or print the API key.
"""

from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path
from typing import Any

from .agent import CompatibleChatProvider
from .full_context import publish_source_package
from .full_context_runner import (
    FULL_CONTEXT_DEV_PILOT_RUN_ID,
    FULL_CONTEXT_IMPLEMENTATION_FILES,
    FULL_CONTEXT_MAIN_QUESTION_SET,
    FULL_CONTEXT_MAIN_RUN_ID,
    FULL_CONTEXT_PUBLISHED_SOURCE_FILES,
    FULL_CONTEXT_PREFLIGHT_QUESTION_ID,
    FULL_CONTEXT_SOURCE_RELATIVE_DIR,
    dry_run_full_context,
    evaluate_full_context_run,
    inspect_full_context,
    prepare_full_context_run,
    run_full_context,
    verify_full_context_run,
    write_full_context_status,
)
from .model2_preflight import load_model2_provider_from_environment


_ONLINE_COMMANDS = frozenset({"preflight", "pilot", "run"})


def _result_exit_code(command: str, result: Any) -> int:
    """Make a checkpointed online failure visible to shells and monitors."""

    if (
        command in _ONLINE_COMMANDS
        and isinstance(result, dict)
        and result.get("status") == "failed"
    ):
        return 1
    return 0


def _git_head(repo_root: Path) -> str:
    """Return the commit that immutably contains every result-affecting file."""

    root = Path(repo_root).resolve()
    commit = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    for relative in (
        *FULL_CONTEXT_IMPLEMENTATION_FILES,
        *FULL_CONTEXT_PUBLISHED_SOURCE_FILES,
    ):
        tracked = subprocess.run(
            ["git", "ls-files", "--error-unmatch", relative],
            cwd=root,
            capture_output=True,
            text=True,
        )
        clean = subprocess.run(
            ["git", "diff", "--quiet", "HEAD", "--", relative],
            cwd=root,
        )
        if tracked.returncode != 0 or clean.returncode != 0:
            raise RuntimeError(
                "Commit all Full Context implementation files before preparing "
                f"an immutable run: {relative}"
            )
    return commit


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "B3 Full Context Model 2 baseline: all 30 S1 sessions, no search, "
            "one DeepSeek Answerer episode per question"
        )
    )
    parser.add_argument(
        "--repo-root", type=Path, default=Path(__file__).resolve().parents[1]
    )
    parser.add_argument("--output-root", type=Path)
    parser.add_argument("--run-id")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("build-source", help="publish and verify the 30-session package; no API")
    inspect = sub.add_parser("inspect", help="measure exact prompt sizes; no API")
    inspect.add_argument(
        "--question-set", choices=("dev-6", FULL_CONTEXT_MAIN_QUESTION_SET),
        required=True,
    )

    prepare = sub.add_parser("prepare", help="freeze one content-addressed run; no API")
    prepare.add_argument(
        "--question-set", choices=("dev-6", FULL_CONTEXT_MAIN_QUESTION_SET),
        required=True,
    )
    sub.add_parser("dry-run", help="verify a pristine prepared run; no API")
    sub.add_parser("status", help="verify checkpoints and report progress; no API")
    sub.add_parser(
        "preflight",
        help=(
            "run only the longest dev-6 request (q079) to test deployed context capacity"
        ),
    )
    sub.add_parser("pilot", help="complete the six-question dev pilot")

    run = sub.add_parser("run", help="run/resume one explicit main-60-v2 target")
    target = run.add_mutually_exclusive_group(required=True)
    target.add_argument("--question-id")
    target.add_argument("--through-block", type=int, choices=range(1, 13))
    target.add_argument("--all", action="store_true", dest="run_all")

    sub.add_parser("verify", help="require a complete run and perform pre-gold audit")
    sub.add_parser("evaluate", help="after verify, load pinned gold and score")
    return parser


def _run_args(args: argparse.Namespace) -> dict[str, Any]:
    if args.output_root is None or not args.run_id:
        raise SystemExit("--output-root and --run-id are required for this command")
    return {
        "repo_root": args.repo_root.resolve(),
        "output_root": args.output_root.resolve(),
        "run_id": args.run_id,
    }


def _provider() -> CompatibleChatProvider:
    # The adapter obtains the already-exported key from the process environment.
    # It never writes, prints, clears, or rotates the value.
    return load_model2_provider_from_environment()


def main(argv: list[str] | None = None) -> None:
    args = _parser().parse_args(argv)
    root = args.repo_root.resolve()
    if args.command == "build-source":
        result = publish_source_package(
            repo_root=root, output_dir=root / FULL_CONTEXT_SOURCE_RELATIVE_DIR
        )
    elif args.command == "inspect":
        result = inspect_full_context(repo_root=root, question_set=args.question_set)
    elif args.command == "prepare":
        common = _run_args(args)
        path = prepare_full_context_run(
            **common,
            question_set=args.question_set,
            implementation_commit=_git_head(root),
        )
        result = {"status": "prepared", "manifest": str(path)}
    elif args.command == "dry-run":
        result = dry_run_full_context(**_run_args(args))
    elif args.command == "status":
        result = write_full_context_status(**_run_args(args))
    elif args.command == "preflight":
        common = _run_args(args)
        status = write_full_context_status(**common)
        if (
            status["question_set"] != "dev-6"
            or args.run_id != FULL_CONTEXT_DEV_PILOT_RUN_ID
        ):
            raise SystemExit(
                "preflight requires the fixed prepared dev pilot run: "
                + FULL_CONTEXT_DEV_PILOT_RUN_ID
            )
        result = run_full_context(
            **common,
            provider=_provider(),
            question_id=FULL_CONTEXT_PREFLIGHT_QUESTION_ID,
        )
    elif args.command == "pilot":
        common = _run_args(args)
        status = write_full_context_status(**common)
        if (
            status["question_set"] != "dev-6"
            or args.run_id != FULL_CONTEXT_DEV_PILOT_RUN_ID
        ):
            raise SystemExit(
                "pilot requires the fixed prepared dev pilot run: "
                + FULL_CONTEXT_DEV_PILOT_RUN_ID
            )
        result = run_full_context(**common, provider=_provider(), run_all=True)
    elif args.command == "run":
        common = _run_args(args)
        status = write_full_context_status(**common)
        if (
            status["question_set"] != FULL_CONTEXT_MAIN_QUESTION_SET
            or args.run_id != FULL_CONTEXT_MAIN_RUN_ID
        ):
            raise SystemExit(
                "run is allowed only for the fixed prepared main-60-v2 run: "
                + FULL_CONTEXT_MAIN_RUN_ID
            )
        result = run_full_context(
            **common,
            provider=_provider(),
            question_id=args.question_id,
            through_block=args.through_block,
            run_all=args.run_all,
        )
    elif args.command == "verify":
        result = verify_full_context_run(**_run_args(args))
    else:
        result = evaluate_full_context_run(**_run_args(args))
    print(json.dumps(result, ensure_ascii=False, indent=2))
    exit_code = _result_exit_code(args.command, result)
    if exit_code:
        raise SystemExit(exit_code)


if __name__ == "__main__":
    main()
