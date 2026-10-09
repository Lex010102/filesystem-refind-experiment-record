"""Command line entry points for the frozen E6/R3 harness."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from .agent import CompatibleChatProvider
from .evidence import canonical_json_bytes
from .r1_inputs import load_question_inputs
from .r2_tokenizer import tokenizer_source_sha256, verify_r2_tokenizer
from .r3_artifacts import (
    r3_backend_contract_sha256,
    verify_r3_episode_artifact,
    verify_r3_failure_artifact,
)
from .r3_inputs import load_r3_corpus, preflight_r3_inputs
from .r3_prompts import r3_prompt_hashes, verify_r3_prompts
from .r3_protocol import (
    R3_PARAMETERS,
    r3_protocol_body,
    r3_protocol_sha256,
    verify_r3_protocol,
)
from .r3_runner import execute_r3_batch, execute_r3_question
from .r3_tools import r3_action_contract_sha256, verify_r3_action_contract


def _root() -> Path:
    return Path(__file__).resolve().parents[1]


def _print(value) -> None:
    print(canonical_json_bytes(value).decode("utf-8"))


def _validate_live_provider_contract(
    provider: CompatibleChatProvider, requested_model: str
) -> None:
    formal_style = str(R3_PARAMETERS["formal_local_api_style"])
    if provider.api_style != formal_style:
        raise SystemExit(
            f"Formal R3 requires FSMEM_API_STYLE={formal_style}; got {provider.api_style}"
        )
    if provider.model is not None and provider.model != requested_model:
        raise SystemExit(
            "FSMEM_MODEL and --model must match so the recorded requested "
            "model cannot differ from the model sent on the wire"
        )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Frozen E6/R3 retrieval harness")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("config", help="print frozen R3 contracts; no API call")
    sub.add_parser("preflight", help="verify S3 and build the R3 index; no API call")

    one = sub.add_parser("run-one", help="run one API-backed E6/R3 episode")
    one.add_argument("--question-set", choices=("dev-6", "main-40"), required=True)
    one.add_argument("--position", type=int, required=True)
    one.add_argument("--run-id", required=True)
    one.add_argument("--output-root", type=Path, required=True)
    one.add_argument("--model", default="coding")
    one.add_argument("--budget-unit", choices=("characters", "bytes"), default="characters")
    one.add_argument("--budget-limit", type=int, default=20_000)

    batch = sub.add_parser("run-batch", help="run a sequential API-backed E6/R3 batch")
    batch.add_argument("--question-set", choices=("dev-6", "main-40"), required=True)
    batch.add_argument("--run-id", required=True)
    batch.add_argument("--output-root", type=Path, required=True)
    batch.add_argument("--model", default="coding")
    batch.add_argument("--budget-unit", choices=("characters", "bytes"), default="characters")
    batch.add_argument("--budget-limit", type=int, default=20_000)

    verify = sub.add_parser("verify", help="verify one published episode; no API call")
    verify.add_argument("--path", type=Path, required=True)
    return parser


def main(argv: list[str] | None = None) -> None:
    args = _parser().parse_args(argv)
    root = _root()
    if args.command == "config":
        verify_r3_protocol()
        verify_r3_prompts()
        verify_r2_tokenizer()
        verify_r3_action_contract()
        _print(
            {
                "protocol": r3_protocol_body(),
                "protocol_sha256": r3_protocol_sha256(),
                "prompt_sha256": r3_prompt_hashes(),
                "tokenizer_sha256": tokenizer_source_sha256(),
                "action_contract_sha256": r3_action_contract_sha256(),
                "backend_contract_sha256": r3_backend_contract_sha256(),
            }
        )
        return
    if args.command == "preflight":
        summary = preflight_r3_inputs(root)
        # Constructing the index is part of preflight, even though no query is run.
        from .r3_index import R3CuratedIndex

        index = R3CuratedIndex(load_r3_corpus(root))
        summary["index_documents"] = len(index.units)
        summary["index_groups"] = len(index.corpus.groups)
        _print(summary)
        return
    if args.command in {"run-one", "run-batch"}:
        questions = load_question_inputs(root, args.question_set)
        provider = CompatibleChatProvider.from_environment()
        _validate_live_provider_contract(provider, args.model)
        if args.command == "run-one":
            if args.position < 1 or args.position > len(questions):
                raise SystemExit("--position is outside the selected question set")
            result = execute_r3_question(
                repo_root=root,
                output_root=args.output_root,
                run_id=args.run_id,
                question=questions[args.position - 1],
                provider=provider,
                requested_model=args.model,
                budget_unit=args.budget_unit,
                budget_limit=args.budget_limit,
            )
            _print(result.to_dict())
        else:
            results = execute_r3_batch(
                repo_root=root,
                output_root=args.output_root,
                run_id=args.run_id,
                questions=questions,
                provider=provider,
                requested_model=args.model,
                budget_unit=args.budget_unit,
                budget_limit=args.budget_limit,
            )
            _print([item.to_dict() for item in results])
        return
    episode = args.path.resolve()
    if (episode / "failure.json").exists():
        _print(verify_r3_failure_artifact(episode).to_dict())
        return
    # Read only enough to reject a non-R3 artifact before full verification.
    raw = json.loads((episode / "bundle.json").read_text(encoding="utf-8"))
    if raw.get("condition") != {"condition_id": "E6", "store_id": "s3", "retrieval_id": "r3"}:
        raise SystemExit("The selected artifact is not E6/R3")
    bundle = verify_r3_episode_artifact(episode, corpus=load_r3_corpus(root))
    _print(bundle.to_dict())


if __name__ == "__main__":
    main()
