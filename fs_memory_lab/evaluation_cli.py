"""Command-line entry point for deterministic, post-run experiment evaluation."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from .evaluation import evaluate_run_store, write_evaluation_report


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Verify and evaluate one completed E1-E7 RunRecord store."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    offline = subparsers.add_parser(
        "offline",
        help="Compute official LoCoMo F1 plus evidence/citation/cost metrics without API calls.",
    )
    offline.add_argument("--run-root", type=Path, required=True)
    offline.add_argument("--run-id", required=True)
    offline.add_argument("--gold", type=Path, required=True)
    offline.add_argument("--gold-sha256", required=True)
    offline.add_argument("--output", type=Path, required=True)
    return parser


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    if args.command == "offline":
        results = evaluate_run_store(
            run_root=args.run_root,
            run_id=args.run_id,
            gold_path=args.gold,
            expected_gold_sha256=args.gold_sha256,
        )
        output = write_evaluation_report(args.output, results)
        print(
            json.dumps(
                {
                    "status": "completed",
                    "run_id": args.run_id,
                    "evaluated_records": len(results),
                    "output": str(output),
                    "api_calls": 0,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return
    raise AssertionError(f"Unhandled command: {args.command}")


if __name__ == "__main__":
    main()
