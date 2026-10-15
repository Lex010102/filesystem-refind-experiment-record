"""Command-line entry point for the isolated Model 2 preflight layer.

Run as ``python -m fs_memory_lab.model2_preflight_cli``.  A Keychain launcher
may inject ``FSMEM_API_KEY`` into this process; this CLI itself reads only the
existing environment and never prints credential values.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Sequence

from .model2_preflight import (
    MODEL2_EXPECTED_SERVED_MODEL,
    check_model2_alias,
    load_model2_provider_from_environment,
    run_model2_smoke_report,
    verify_sanitized_preflight_artifact,
    write_model2_smoke_report,
    write_model_catalog_check,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Fail-closed x-test-2 identity and protocol preflight"
    )
    commands = parser.add_subparsers(dest="command", required=True)

    models = commands.add_parser(
        "models-check", help="Require x-test-2 in the SoCLaaS /v1/models list"
    )
    models.add_argument("--output", type=Path, required=True)

    smoke = commands.add_parser(
        "smoke", help="Run sanitized R1/R2/R3/Answerer protocol smokes"
    )
    smoke.add_argument("--output", type=Path, required=True)
    smoke.add_argument(
        "--expected-served-model",
        default=MODEL2_EXPECTED_SERVED_MODEL,
        help="must remain the independently confirmed deployment identity",
    )

    verify = commands.add_parser("verify", help="Verify a sanitized artifact")
    verify.add_argument("--input", type=Path, required=True)

    summary = commands.add_parser(
        "summary", help="Print a verified, credential-free artifact summary"
    )
    summary.add_argument("--input", type=Path, required=True)
    return parser


def _emit(value: dict) -> None:
    print(json.dumps(value, ensure_ascii=False, sort_keys=True))


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.command == "models-check":
        provider = load_model2_provider_from_environment()
        check = check_model2_alias(provider)
        path = write_model_catalog_check(args.output, check)
        _emit(
            {
                "status": "passed",
                "artifact_type": "model2-models-check",
                "output": str(path),
                "requested_alias": "x-test-2",
                "alias_present": True,
                "context_limit": next(iter(check.alias_context_limits.values())),
            }
        )
        return 0
    if args.command == "smoke":
        provider = load_model2_provider_from_environment()
        report = run_model2_smoke_report(
            provider, expected_served_model=args.expected_served_model
        )
        path = write_model2_smoke_report(args.output, report)
        _emit(
            {
                "status": "passed",
                "artifact_type": "model2-role-smoke",
                "output": str(path),
                "requested_alias": report.requested_alias,
                "served_model": report.expected_served_model,
                "role_smokes_passed": len(report.roles),
            }
        )
        return 0
    result = verify_sanitized_preflight_artifact(args.input)
    _emit(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
