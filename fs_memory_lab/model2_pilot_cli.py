"""CLI for the isolated Model 2 dev-6 pilot pipeline."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Sequence

from .model2_pilot import (
    authorize_model2_pilot_answer_retry,
    authorize_model2_pilot_retrieval_retry,
    finalize_model2_pilot,
    prepare_model2_pilot_pipeline,
    run_model2_pilot_answers,
    run_model2_pilot_all,
    run_model2_pilot_retrieval,
    write_model2_pilot_status,
)
from .model2_preflight import load_model2_provider_from_environment


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Prepare, run, resume, and audit the x-test-2 dev-6 E1-E7 pilot"
    )
    parser.add_argument("--repo-root", type=Path, default=Path.cwd())
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--pilot-id", required=True)
    commands = parser.add_subparsers(dest="command", required=True)

    prepare = commands.add_parser("prepare")
    prepare.add_argument("--implementation-commit", required=True)
    prepare.add_argument("--required-served-model", required=True)
    prepare.add_argument("--preflight-report", type=Path, required=True)
    prepare.add_argument("--preflight-report-sha256", required=True)
    prepare.add_argument("--models-check-report", type=Path, required=True)
    prepare.add_argument("--models-check-report-sha256", required=True)

    commands.add_parser("run-retrieval")
    commands.add_parser(
        "authorize-retrieval-retry",
        help="authorize one bounded same-protocol retry; no API call",
    )
    commands.add_parser("run-answers")
    commands.add_parser(
        "authorize-answer-retry",
        help="authorize one bounded same-protocol answer retry; no API call",
    )
    commands.add_parser(
        "run-all",
        help="run retrieval and answers with bounded automatic checkpoint recovery",
    )
    commands.add_parser("status")
    commands.add_parser("finalize")
    return parser


def _emit(value: object) -> None:
    print(json.dumps(value, ensure_ascii=False, sort_keys=True))


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    common = {
        "repo_root": args.repo_root,
        "output_root": args.output_root,
        "pilot_id": args.pilot_id,
    }
    if args.command == "prepare":
        path = prepare_model2_pilot_pipeline(
            **common,
            implementation_commit=args.implementation_commit,
            required_served_model=args.required_served_model,
            preflight_report_path=args.preflight_report,
            preflight_report_sha256=args.preflight_report_sha256,
            models_check_report_path=args.models_check_report,
            models_check_report_sha256=args.models_check_report_sha256,
        )
        _emit({"status": "prepared", "manifest": str(path), "api_calls": 0})
        return 0
    if args.command == "status":
        _emit(write_model2_pilot_status(**common))
        return 0
    if args.command == "finalize":
        _emit(finalize_model2_pilot(**common))
        return 0
    if args.command == "authorize-retrieval-retry":
        path = authorize_model2_pilot_retrieval_retry(**common)
        _emit({"status": "authorized", "recovery_policy": str(path), "api_calls": 0})
        return 0
    if args.command == "authorize-answer-retry":
        path = authorize_model2_pilot_answer_retry(**common)
        _emit({"status": "authorized", "recovery_policy": str(path), "api_calls": 0})
        return 0

    # Provider/environment construction is intentionally confined to the two
    # commands that are explicitly authorized to make Model 2 API calls.
    provider = load_model2_provider_from_environment()
    if args.command == "run-retrieval":
        _emit(run_model2_pilot_retrieval(**common, provider=provider))
        return 0
    if args.command == "run-all":
        _emit(run_model2_pilot_all(**common, provider=provider))
        return 0
    _emit(run_model2_pilot_answers(**common, provider=provider))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
