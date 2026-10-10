"""CLI for the dev-6 E1--E6 retrieval-only engineering run."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from .agent import CompatibleChatProvider
from .dev_retrieval import (
    authorize_empty_content_hotfix_retry,
    authorize_provider_response_retry,
    prepare_dev_run,
    recover_empty_content_and_continue,
    run_dev_retrieval,
    verify_dev_run,
    write_status,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run and audit 36 dev-6 retrieval episodes")
    parser.add_argument("--repo-root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--run-id", required=True)
    sub = parser.add_subparsers(dest="command", required=True)
    prepare = sub.add_parser("prepare", help="freeze the no-API run manifest")
    prepare.add_argument("--budget-characters", type=int, default=6000)
    prepare.add_argument("--model", default="coding")
    run = sub.add_parser("run", help="run or resume pending episodes using the API")
    run.add_argument(
        "--authorized-recovery",
        action="store_true",
        help="use the immutable recovery policy for one prior provider-response failure",
    )
    sub.add_parser(
        "authorize-provider-response-retry",
        help="freeze one explicit whole-episode retry; no API call",
    )
    sub.add_parser(
        "authorize-empty-content-hotfix-retry",
        help="freeze one post-hotfix retry after repeated empty responses; no API call",
    )
    sub.add_parser(
        "recover-empty-content-and-continue",
        help="run the bound hotfix retry, then continue remaining episodes",
    )
    sub.add_parser("status", help="verify completed artifacts and print progress; no API")
    sub.add_parser("verify", help="verify the complete run and summary; no API")
    return parser


def main(argv: list[str] | None = None) -> None:
    args = _parser().parse_args(argv)
    root = args.repo_root.resolve()
    output = args.output_root.resolve()
    if args.command == "prepare":
        path = prepare_dev_run(
            repo_root=root,
            output_root=output,
            run_id=args.run_id,
            budget_limit=args.budget_characters,
            requested_model=args.model,
        )
        result = {"status": "prepared", "manifest": str(path)}
    elif args.command == "authorize-provider-response-retry":
        path = authorize_provider_response_retry(
            repo_root=root, output_root=output, run_id=args.run_id
        )
        result = {"status": "recovery-authorized", "policy": str(path)}
    elif args.command == "authorize-empty-content-hotfix-retry":
        path = authorize_empty_content_hotfix_retry(
            repo_root=root, output_root=output, run_id=args.run_id
        )
        result = {"status": "hotfix-recovery-authorized", "policy": str(path)}
    elif args.command == "recover-empty-content-and-continue":
        run_result = recover_empty_content_and_continue(
            repo_root=root,
            output_root=output,
            run_id=args.run_id,
            provider=CompatibleChatProvider.from_environment(),
        )
        if run_result.get("status") == "completed":
            result = {
                "status": "completed",
                "run_id": args.run_id,
                "summary_id": run_result["summary_id"],
                "episode_count": run_result["episode_count"],
                "budget_decision": run_result["budget_decision"],
                "e5_token_cost_check": run_result["e5_token_cost_check"],
                "summary_path": str(output / args.run_id / "summary.json"),
            }
        else:
            result = run_result
    elif args.command == "run":
        run_result = run_dev_retrieval(
            repo_root=root,
            output_root=output,
            run_id=args.run_id,
            provider=CompatibleChatProvider.from_environment(),
            allow_authorized_recovery=args.authorized_recovery,
        )
        if run_result.get("status") == "completed":
            result = {
                "status": "completed",
                "run_id": args.run_id,
                "summary_id": run_result["summary_id"],
                "episode_count": run_result["episode_count"],
                "budget_decision": run_result["budget_decision"],
                "e5_token_cost_check": run_result["e5_token_cost_check"],
                "summary_path": str(output / args.run_id / "summary.json"),
            }
        else:
            result = run_result
    elif args.command == "status":
        result = write_status(repo_root=root, output_root=output, run_id=args.run_id)
    else:
        result = verify_dev_run(repo_root=root, output_root=output, run_id=args.run_id)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
