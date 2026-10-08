"""Command line entry points for the frozen R2-Raw harness."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from .agent import CompatibleChatProvider
from .evidence import canonical_json_bytes
from .r1_inputs import load_question_inputs, load_r1_store
from .r2_artifacts import (
    r2_backend_contract_sha256,
    verify_r2_episode_artifact,
    verify_r2_failure_artifact,
)
from .r2_inputs import preflight_r2_raw_inputs
from .r2_prompts import r2_prompt_hashes, verify_r2_prompts
from .r2_protocol import (
    R2_PARAMETERS,
    r2_protocol_body,
    r2_protocol_sha256,
    verify_r2_protocol,
)
from .r2_runner import R2_CELL_STORES, execute_r2_batch, execute_r2_question
from .r2_tokenizer import tokenizer_source_sha256, verify_r2_tokenizer
from .r2_tools import r2_action_contract_sha256, verify_r2_action_contract


def _root() -> Path:
    return Path(__file__).resolve().parents[1]


def _print(value) -> None:
    print(canonical_json_bytes(value).decode("utf-8"))


def _validate_live_provider_contract(
    provider: CompatibleChatProvider, requested_model: str
) -> None:
    formal_style = str(R2_PARAMETERS["formal_local_api_style"])
    if provider.api_style != formal_style:
        raise SystemExit(
            f"Formal R2-Raw requires FSMEM_API_STYLE={formal_style}; "
            f"got {provider.api_style}"
        )
    if provider.model is not None and provider.model != requested_model:
        raise SystemExit(
            "FSMEM_MODEL and --model must match so the recorded requested "
            "model cannot differ from the model sent on the wire"
        )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Frozen R2-Raw retrieval harness")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("config", help="print frozen R2 contracts; no API call")
    sub.add_parser("preflight", help="verify S1/S2 and build indexes; no API call")

    one = sub.add_parser("run-one", help="run one API-backed R2 episode")
    one.add_argument("--cell", choices=tuple(R2_CELL_STORES), required=True)
    one.add_argument("--question-set", choices=("dev-6", "main-40"), required=True)
    one.add_argument("--position", type=int, required=True)
    one.add_argument("--run-id", required=True)
    one.add_argument("--output-root", type=Path, required=True)
    one.add_argument("--model", default="coding")
    one.add_argument("--budget-unit", choices=("characters", "bytes"), default="characters")
    one.add_argument("--budget-limit", type=int, default=20_000)

    batch = sub.add_parser("run-batch", help="run a sequential API-backed R2 batch")
    batch.add_argument("--cells", nargs="+", choices=tuple(R2_CELL_STORES), required=True)
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
        verify_r2_protocol()
        verify_r2_prompts()
        verify_r2_tokenizer()
        verify_r2_action_contract()
        _print(
            {
                "protocol": r2_protocol_body(),
                "protocol_sha256": r2_protocol_sha256(),
                "prompt_sha256": r2_prompt_hashes(),
                "tokenizer_sha256": tokenizer_source_sha256(),
                "action_contract_sha256": r2_action_contract_sha256(),
                "backend_contract_sha256": r2_backend_contract_sha256(),
            }
        )
        return
    if args.command == "preflight":
        _print(preflight_r2_raw_inputs(root))
        return
    if args.command in {"run-one", "run-batch"}:
        questions = load_question_inputs(root, args.question_set)
        provider = CompatibleChatProvider.from_environment()
        _validate_live_provider_contract(provider, args.model)
        if args.command == "run-one":
            if args.position < 1 or args.position > len(questions):
                raise SystemExit("--position is outside the selected question set")
            result = execute_r2_question(
                repo_root=root,
                output_root=args.output_root,
                run_id=args.run_id,
                cell_id=args.cell,
                question=questions[args.position - 1],
                provider=provider,
                requested_model=args.model,
                budget_unit=args.budget_unit,
                budget_limit=args.budget_limit,
            )
            _print(result.to_dict())
        else:
            results = execute_r2_batch(
                repo_root=root,
                output_root=args.output_root,
                run_id=args.run_id,
                cell_ids=args.cells,
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
        _print(verify_r2_failure_artifact(episode).to_dict())
        return
    raw = json.loads((episode / "bundle.json").read_text(encoding="utf-8"))
    store_id = raw.get("condition", {}).get("store_id")
    bundle = verify_r2_episode_artifact(
        episode, loaded_store=load_r1_store(root, store_id)
    )
    _print(bundle.to_dict())


if __name__ == "__main__":
    main()
