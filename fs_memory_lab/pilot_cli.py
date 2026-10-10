"""CLI for the full dev-6 x E1--E7 pilot."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from .agent import CompatibleChatProvider
from .pilot import finalize_pilot, prepare_pilot, run_pilot, write_pilot_status


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser(description="Run the 42-record dev-6 E1--E7 pilot")
    value.add_argument("--repo-root", type=Path, required=True)
    value.add_argument("--output-root", type=Path, required=True)
    value.add_argument("--run-id", required=True)
    sub = value.add_subparsers(dest="command", required=True)
    prepare = sub.add_parser("prepare")
    prepare.add_argument("--retrieval-output-root", type=Path, required=True)
    prepare.add_argument("--retrieval-run-id", required=True)
    prepare.add_argument("--model", default="coding")
    sub.add_parser("run")
    sub.add_parser("status")
    sub.add_parser("finalize")
    return value


def main(argv: list[str] | None = None) -> None:
    args = parser().parse_args(argv)
    if args.command == "prepare":
        path = prepare_pilot(
            repo_root=args.repo_root, retrieval_output_root=args.retrieval_output_root,
            retrieval_run_id=args.retrieval_run_id, output_root=args.output_root,
            run_id=args.run_id, requested_model=args.model,
        )
        result = {"status": "prepared", "manifest": str(path)}
    elif args.command == "run":
        result = run_pilot(
            repo_root=args.repo_root, output_root=args.output_root, run_id=args.run_id,
            provider=CompatibleChatProvider.from_environment(),
        )
    elif args.command == "status":
        result = write_pilot_status(output_root=args.output_root, run_id=args.run_id)
    else:
        result = finalize_pilot(repo_root=args.repo_root, output_root=args.output_root, run_id=args.run_id)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
