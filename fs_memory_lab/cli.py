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
from .paper_config import (CHUNK_MAX_CHARS, CHUNK_MAX_TURNS, CONTEXT_COMPACTION_KEEP_ROUNDS,
                           CONTEXT_COMPACTION_TRIGGER, MANAGEMENT, RANDOM_SEED, SEARCH,
                           SEARCH_CONCURRENCY)
from .paper_prompts import MANAGEMENT_PROMPT, SEARCH_PROMPT
from .paper_tools import MANAGEMENT_PROFILE, SEARCH_PROFILE, TOOL_DEFINITIONS


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
    if args.command == "config":
        output = {
            "paper": "Filesystem-Based Memory for LLM Agents, Center / Agent-curated",
            "management": asdict(MANAGEMENT), "search": asdict(SEARCH),
            "chunking": {"max_turns": CHUNK_MAX_TURNS, "max_chars": CHUNK_MAX_CHARS},
            "random_seed": RANDOM_SEED,
            "search_concurrency_paper_batch_only": SEARCH_CONCURRENCY,
            "compaction": {"prompt_token_trigger": CONTEXT_COMPACTION_TRIGGER,
                           "recent_rounds": CONTEXT_COMPACTION_KEEP_ROUNDS,
                           "summarizer": "local approximation; author prompt not published"},
            "tool_profiles": {"management": MANAGEMENT_PROFILE, "search": SEARCH_PROFILE},
            "prompt_sha256": {
                "management": hashlib.sha256(MANAGEMENT_PROMPT.encode("utf-8")).hexdigest(),
                "search": hashlib.sha256(SEARCH_PROMPT.encode("utf-8")).hexdigest(),
            },
            "api": {"default_base_url": "https://api.openai.com/v1",
                    "default_style": "paper",
                    "environment_overrides": ["FSMEM_API_BASE_URL", "FSMEM_MODEL", "FSMEM_API_KEY",
                                              "FSMEM_API_STYLE"]},
        }
        print(json.dumps(output, ensure_ascii=False, indent=2))
        return

    project = args.project.resolve()
    # API configuration is checked before touching persistent directories.
    provider = CompatibleChatProvider.from_environment() if args.command in {"ingest", "ask", "check-api"} else None
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
            result = runner.run("management", f"Integrate this conversation chunk into the existing memory filesystem.\n\n{chunk}")
        except Exception:
            print(f"Chunk {index} failed. The pre-chunk snapshot is at {run_dir / f'before-chunk-{index:03d}'}")
            raise
        save_trace(result, run_dir / f"chunk-{index:03d}.json")
        print(f"Chunk {index}/{len(chunks)}: {result.answer} [rounds={result.rounds}, tools={result.tool_calls}]")
    print(f"Memory: {memory.root}\nTraces and pre-chunk snapshots: {run_dir}")


if __name__ == "__main__":
    main()
