"""Local commands: safe tool demo, API-backed ingest and read-only ask."""

from __future__ import annotations

import argparse
import hashlib
import json
import random
import re
import shutil
import tempfile
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

from .agent import AgentRunner, CompatibleChatProvider, save_trace
from .filesystem import MemoryFS
from .foldering_prompt import (FOLDERING_PROMPT, FOLDERING_PROMPT_VERSION,
                               FROZEN_FOLDERING_PROMPT_SHA256,
                               FROZEN_FOLDERING_TASK_SHA256)
from .management_prompt import (BUILDER_PROMPT_VERSION,
                                FROZEN_BUILDER_PROMPT_SHA256,
                                FROZEN_LOCOMO_ATTRIBUTION_SHA256,
                                FROZEN_MANAGEMENT_PROMPT_SHA256,
                                LOCOMO_ATTRIBUTION_VERSION,
                                MANAGEMENT_PROMPT_VERSION)
from .paper_config import (CHUNK_MAX_CHARS, CHUNK_MAX_TURNS, CONTEXT_COMPACTION_KEEP_ROUNDS,
                           CONTEXT_COMPACTION_TRIGGER, FOLDERING, MANAGEMENT, RANDOM_SEED, SEARCH,
                           SEARCH_CONCURRENCY)
from .paper_prompts import MANAGEMENT_PROMPT, SEARCH_PROMPT
from .paper_tools import (FOLDERING_PROFILE, FROZEN_FOLDERING_TOOL_SCHEMA_SHA256,
                          MANAGEMENT_PROFILE, SEARCH_PROFILE, TOOL_DEFINITIONS)
from .s3_protocol import (FROZEN_S3_USER_INSTRUCTION_SHA256,
                          FROZEN_S3_USER_TEMPLATE_SHA256,
                          S3_USER_WRAPPER_VERSION, render_s3_user_message)
from .s3_runner import (build_s3_store, preflight_s3_build,
                        verify_published_s3)
from .s3_runtime import (EXPECTED_S3_PROMPT_CONTRACT_SHA256,
                         EXPECTED_S3_RUNTIME_CONTRACT_SHA256,
                         EXPECTED_S3_SERVED_MODEL,
                         EXPECTED_S3_STREAM_MANIFEST_SHA256,
                         FROZEN_MANAGEMENT_RUNTIME_CONFIG_SHA256,
                         FROZEN_MANAGEMENT_TOOL_PROFILE_SHA256,
                         FROZEN_MANAGEMENT_TOOL_SCHEMA_SHA256,
                         FROZEN_MANAGEMENT_TOOL_WIRE_SHA256,
                         LOCAL_S3_PROVIDER_PROFILE, S3_RESOURCE_LIMITS,
                         S3_RUNNER_VERSION)
from .s2 import (build_s2_store, git_state, preflight_s2_build,
                 verify_published_s2)


def chunk_lines(text: str, max_turns: int = CHUNK_MAX_TURNS, max_chars: int = CHUNK_MAX_CHARS) -> list[str]:
    """Each nonempty line is one supplied turn; benchmark loaders remain separate."""
    turns = [line for line in text.splitlines() if line.strip()]
    chunks: list[str] = []
    current: list[str] = []
    size = 0
    for turn in turns:
        if len(turn) > max_chars:
            raise ValueError("One dialogue line exceeds the 3,000-character chunk cap")
        if current and (len(current) == max_turns or size + len(turn) + 1 > max_chars):
            chunks.append("\n".join(current))
            current = []
            size = 0
        current.append(turn)
        size += len(turn) + 1
    if current:
        chunks.append("\n".join(current))
    return chunks


def validate_locomo_turns(text: str) -> None:
    """Prompt 2 assumes every supplied turn has an [S{session}T{turn}] tag."""
    for number, line in enumerate(text.splitlines(), 1):
        if line.strip() and not re.search(r"\[S\d+T\d+\]", line):
            raise ValueError(f"Input line {number} lacks a LoCoMo-style [SxTy] source locator")


def _run_directory(project: Path) -> Path:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    result = project / "runs" / stamp
    result.mkdir(parents=True, exist_ok=False)
    return result


def _memory(project: Path) -> MemoryFS:
    return MemoryFS(project / "memories", project / "runs" / "trash")


def _s2_paths(project: Path) -> dict[str, Path]:
    experiment = project / "experiments" / "locomo-conv50-v1"
    return {
        "s1_store": experiment / "stores" / "s1-flat",
        "s1_manifest": experiment / "manifests" / "s1-flat.json",
        "s2_store": experiment / "stores" / "s2-foldered",
        "s2_manifest": experiment / "manifests" / "s2-foldered.json",
        "path_map": experiment / "manifests" / "s2-foldered-path-map.json",
        "trace": experiment / "traces" / "s2-foldering.json",
        "commit_marker": experiment / "manifests" / "s2-foldered.COMMITTED",
        "work_root": project / "local-runs" / "s2-foldering",
    }


def _s3_paths(project: Path) -> dict[str, Path]:
    experiment = project / "experiments" / "locomo-conv50-v1"
    return {
        "stream_dir": experiment / "streams" / "s3-management-v1",
        "stream_manifest": experiment / "manifests" / "s3-management-stream.json",
        "prompt_contract": experiment / "manifests" / "s3-management-prompt.json",
        "runtime_contract": experiment / "manifests" / "s3-management-runtime.json",
        "s3_store": experiment / "stores" / "s3-curated",
        "s3_manifest": experiment / "manifests" / "s3-curated.json",
        "trace_dir": experiment / "traces" / "s3-management",
        "commit_marker": experiment / "manifests" / "s3-curated.COMMITTED",
        "work_root": project / "local-runs" / "s3-management",
    }


def _demo() -> None:
    with tempfile.TemporaryDirectory(prefix="fsmem-demo-") as temporary:
        memory = MemoryFS(Path(temporary) / "memories", Path(temporary) / "trash")
        memory.create("/memories/people/alice.md", "---\nname: alice\ndescription: Alice's diet and travel plans.\n---\n\n# Diet\n- Vegetarian since May 2026 [S6T5]\n")
        print("1. view /memories\n" + memory.view("/memories"))
        print("\n2. grep Alice's diet\n" + memory.grep("vegetarian"))
        print("\n3. toc\n" + memory.toc("/memories/people/alice.md"))
        print("\n4. section_read\n" + memory.section_read("/memories/people/alice.md", "# Diet"))
        print("\nDemo uses a temporary memory directory and makes no API call.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Center/Agent-curated filesystem-memory harness")
    parser.add_argument("--project", type=Path, default=Path(__file__).resolve().parents[1],
                        help="Project directory; memories/ and runs/ are created beneath it")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("demo", help="Run deterministic file-tool demo without API")
    sub.add_parser("config", help="Show effective paper-aligned defaults without API")
    sub.add_parser("foldering-prompt", help="Print the project-defined S2 prompt without API")
    sub.add_parser("management-prompt", help="Print the paper-derived frozen S3 management prompt without API")
    sub.add_parser("s2-preflight", help="Validate frozen S1 and S2 targets without API")
    sub.add_parser("build-s2", help="Safely build and atomically publish formal S2 with API")
    sub.add_parser("verify-s2", help="Recompute and verify the published S2 without API")
    sub.add_parser("s3-preflight", help="Validate frozen S3 inputs/contracts/targets without API")
    sub.add_parser("build-s3", help="Safely build all 85 S3 episodes and publish after verification")
    resume_s3 = sub.add_parser(
        "resume-s3",
        help="Resume a validated failed S3 run from its retained pre-chunk checkpoint",
    )
    resume_s3.add_argument("--run-id", required=True)
    resume_s3.add_argument(
        "--source-code-revision",
        required=True,
        help="Git revision that produced the failed prefix (recorded as operator attestation)",
    )
    sub.add_parser("verify-s3", help="Recompute and verify the published S3 without API")
    sub.add_parser("check-api", help="Make one read-only function-call request without writing memory")
    ingest = sub.add_parser("ingest", help="Send each dialogue chunk to the management agent")
    ingest.add_argument("--input", type=Path, required=True, help="UTF-8 file with one dialogue turn per line")
    ingest.add_argument("--allow-untagged", action="store_true",
                        help="Debug-only: bypass LoCoMo source-locator contract; breaks attribution parity")
    ingest.add_argument("--max-rounds", type=int, default=None, help="Override paper default (60) for debugging")
    ask = sub.add_parser("ask", help="Ask the read-only search agent")
    ask.add_argument("--question", required=True)
    ask.add_argument("--max-rounds", type=int, default=None, help="Override paper default (40) for debugging")
    sub.add_parser("show", help="List the existing memory without API")
    args = parser.parse_args()
    random.seed(RANDOM_SEED)

    if args.command == "demo":
        _demo()
        return
    if args.command == "foldering-prompt":
        print(FOLDERING_PROMPT)
        return
    if args.command == "management-prompt":
        print(MANAGEMENT_PROMPT, end="")
        return
    if args.command == "config":
        output = {
            "paper": "Filesystem-Based Memory for LLM Agents; Center plus local S2/S3 operationalization",
            "management": asdict(MANAGEMENT), "foldering": asdict(FOLDERING),
            "search": asdict(SEARCH),
            "chunking": {"max_turns": CHUNK_MAX_TURNS, "max_chars": CHUNK_MAX_CHARS},
            "random_seed": RANDOM_SEED,
            "search_concurrency_paper_batch_only": SEARCH_CONCURRENCY,
            "compaction": {"prompt_token_trigger": CONTEXT_COMPACTION_TRIGGER,
                           "recent_rounds": CONTEXT_COMPACTION_KEEP_ROUNDS,
                           "summarizer": "local approximation; author prompt not published"},
            "tool_profiles": {"management": MANAGEMENT_PROFILE,
                              "foldering": FOLDERING_PROFILE,
                              "search": SEARCH_PROFILE},
            "prompt_sha256": {
                "management": hashlib.sha256(MANAGEMENT_PROMPT.encode("utf-8")).hexdigest(),
                "foldering": hashlib.sha256(FOLDERING_PROMPT.encode("utf-8")).hexdigest(),
                "search": hashlib.sha256(SEARCH_PROMPT.encode("utf-8")).hexdigest(),
            },
            "management_prompt": {
                "version": MANAGEMENT_PROMPT_VERSION,
                "provenance": "paper Appendix A.1 Prompt 1 plus LoCoMo Prompt 2",
                "builder_version": BUILDER_PROMPT_VERSION,
                "builder_sha256": FROZEN_BUILDER_PROMPT_SHA256,
                "attribution_version": LOCOMO_ATTRIBUTION_VERSION,
                "attribution_sha256": FROZEN_LOCOMO_ATTRIBUTION_SHA256,
                "combined_sha256": FROZEN_MANAGEMENT_PROMPT_SHA256,
                "user_wrapper_version": S3_USER_WRAPPER_VERSION,
                "user_wrapper_provenance": "project-defined; exact paper wrapper not published",
                "user_instruction_sha256": FROZEN_S3_USER_INSTRUCTION_SHA256,
                "user_template_sha256": FROZEN_S3_USER_TEMPLATE_SHA256,
            },
            "foldering_prompt": {
                "version": FOLDERING_PROMPT_VERSION,
                "provenance": "project-defined reconstruction; author build prompt not published",
                "frozen_prompt_sha256": FROZEN_FOLDERING_PROMPT_SHA256,
                "frozen_task_sha256": FROZEN_FOLDERING_TASK_SHA256,
                "frozen_tool_schema_sha256": FROZEN_FOLDERING_TOOL_SCHEMA_SHA256,
            },
            "s3_runtime": {
                "status": (
                    f"{S3_RUNNER_VERSION}; timeout and retryable HTTP recovery enabled; "
                    "formal store publishes only after all 85 chunks pass"
                ),
                "stream_manifest_sha256": EXPECTED_S3_STREAM_MANIFEST_SHA256,
                "prompt_contract_sha256": EXPECTED_S3_PROMPT_CONTRACT_SHA256,
                "runtime_contract_sha256": EXPECTED_S3_RUNTIME_CONTRACT_SHA256,
                "runtime_config_sha256": FROZEN_MANAGEMENT_RUNTIME_CONFIG_SHA256,
                "tool_profile_sha256": FROZEN_MANAGEMENT_TOOL_PROFILE_SHA256,
                "tool_schema_sha256": FROZEN_MANAGEMENT_TOOL_SCHEMA_SHA256,
                "tool_wire_sha256": FROZEN_MANAGEMENT_TOOL_WIRE_SHA256,
                "local_provider_profile": LOCAL_S3_PROVIDER_PROFILE,
                "expected_served_model": EXPECTED_S3_SERVED_MODEL,
                "resource_limits": S3_RESOURCE_LIMITS,
            },
            "api": {"default_base_url": "https://api.openai.com/v1",
                    "default_style": "paper",
                    "environment_overrides": ["FSMEM_API_BASE_URL", "FSMEM_MODEL", "FSMEM_API_KEY",
                                              "FSMEM_API_STYLE"]},
        }
        print(json.dumps(output, ensure_ascii=False, indent=2))
        return

    project = args.project.resolve()
    s2_paths = _s2_paths(project)
    s3_paths = _s3_paths(project)
    if args.command == "s2-preflight":
        report = preflight_s2_build(
            s2_paths["s1_store"],
            s2_paths["s1_manifest"],
            s2_paths["s2_store"],
            s2_paths["s2_manifest"],
            s2_paths["path_map"],
            s2_paths["trace"],
            s2_paths["commit_marker"],
        )
        print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
        return
    if args.command == "verify-s2":
        report = verify_published_s2(
            s2_paths["s1_store"],
            s2_paths["s1_manifest"],
            s2_paths["s2_store"],
            s2_paths["s2_manifest"],
            s2_paths["path_map"],
            s2_paths["trace"],
            s2_paths["commit_marker"],
        )
        print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
        return
    if args.command == "s3-preflight":
        report = preflight_s3_build(
            s3_paths["stream_dir"],
            s3_paths["stream_manifest"],
            s3_paths["prompt_contract"],
            s3_paths["runtime_contract"],
            s3_paths["s3_store"],
            s3_paths["s3_manifest"],
            s3_paths["trace_dir"],
            s3_paths["commit_marker"],
            s3_paths["work_root"],
        )
        print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
        return
    if args.command == "verify-s3":
        report = verify_published_s3(
            s3_paths["stream_dir"],
            s3_paths["stream_manifest"],
            s3_paths["prompt_contract"],
            s3_paths["runtime_contract"],
            s3_paths["s3_store"],
            s3_paths["s3_manifest"],
            s3_paths["trace_dir"],
            s3_paths["commit_marker"],
        )
        print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
        return
    # API configuration is checked before touching persistent directories.
    provider = CompatibleChatProvider.from_environment() if args.command in {
        "ingest", "ask", "check-api", "build-s2", "build-s3", "resume-s3"
    } else None
    if args.command == "check-api":
        result = provider.complete(
            [{"role": "system", "content": "This is a function-calling test. Call the available view tool; do not answer in prose."},
             {"role": "user", "content": "Call view with path /memories exactly once."}],
            [TOOL_DEFINITIONS["view"]], SEARCH,
        )
        calls = result["message"].get("tool_calls") or []
        if not any(call.get("function", {}).get("name") == "view" for call in calls):
            raise RuntimeError("API responded, but the model did not call view; this harness needs function calling")
        print(f"API function calling OK: requested_model={provider.model or SEARCH.model}, "
              f"served_model={result.get('served_model') or 'not reported'}")
        return
    if args.command == "build-s2":
        code = git_state(project)
        report = build_s2_store(
            s2_paths["s1_store"],
            s2_paths["s1_manifest"],
            s2_paths["s2_store"],
            s2_paths["s2_manifest"],
            s2_paths["path_map"],
            s2_paths["trace"],
            s2_paths["commit_marker"],
            s2_paths["work_root"],
            provider,
            code_revision=code["commit"],
            code_dirty=code["dirty"],
        )
        print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
        return
    if args.command == "build-s3":
        code = git_state(project)
        report = build_s3_store(
            s3_paths["stream_dir"],
            s3_paths["stream_manifest"],
            s3_paths["prompt_contract"],
            s3_paths["runtime_contract"],
            s3_paths["s3_store"],
            s3_paths["s3_manifest"],
            s3_paths["trace_dir"],
            s3_paths["commit_marker"],
            s3_paths["work_root"],
            provider,
            code_revision=code["commit"],
            code_dirty=code["dirty"],
            repo_root=project,
        )
        print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
        return
    if args.command == "resume-s3":
        code = git_state(project)
        report = build_s3_store(
            s3_paths["stream_dir"],
            s3_paths["stream_manifest"],
            s3_paths["prompt_contract"],
            s3_paths["runtime_contract"],
            s3_paths["s3_store"],
            s3_paths["s3_manifest"],
            s3_paths["trace_dir"],
            s3_paths["commit_marker"],
            s3_paths["work_root"],
            provider,
            code_revision=code["commit"],
            code_dirty=code["dirty"],
            repo_root=project,
            resume_run_id=args.run_id,
            resume_source_code_revision=args.source_code_revision,
        )
        print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
        return
    memory = _memory(project)
    if args.command == "show":
        print(memory.view("/memories"))
        return

    runner = AgentRunner(memory, provider, max_rounds=args.max_rounds)
    if args.command == "ask":
        run_dir = _run_directory(project)
        result = runner.run("search", args.question)
        save_trace(result, run_dir / "search.json")
        print(result.answer)
        print(f"\n[rounds={result.rounds}, tool_calls={result.tool_calls}, trace={run_dir / 'search.json'}]")
        return

    source = args.input.resolve()
    text = source.read_text(encoding="utf-8")
    if not args.allow_untagged:
        validate_locomo_turns(text)
    chunks = chunk_lines(text)
    if not chunks:
        raise ValueError("Input contains no dialogue turns")
    run_dir = _run_directory(project)
    for index, chunk in enumerate(chunks, 1):
        # A pre-chunk copy allows recovery if a model makes a bad write.
        shutil.copytree(memory.root, run_dir / f"before-chunk-{index:03d}", symlinks=True)
        try:
            result = runner.run("management", render_s3_user_message(chunk))
        except Exception:
            print(f"Chunk {index} failed. The pre-chunk snapshot is at {run_dir / f'before-chunk-{index:03d}'}")
            raise
        save_trace(result, run_dir / f"chunk-{index:03d}.json")
        print(f"Chunk {index}/{len(chunks)}: {result.answer} [rounds={result.rounds}, tools={result.tool_calls}]")
    print(f"Memory: {memory.root}\nTraces and pre-chunk snapshots: {run_dir}")


if __name__ == "__main__":
    main()
