"""One-shot real-provider S3 smoke test; writes only below local-runs/."""

from __future__ import annotations

import json
import os
import secrets
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REPO = Path("/Users/wangwenqi/Desktop/memory bench")
sys.path.insert(0, str(REPO))

from fs_memory_lab.agent import AgentRunError, AgentRunner, CompatibleChatProvider, save_trace
from fs_memory_lab.filesystem import MemoryFS
from fs_memory_lab.management_prompt import MANAGEMENT_PROMPT
from fs_memory_lab.s3_protocol import render_s3_user_message
from fs_memory_lab.s3_runner import (
    S3BuildError,
    _validate_episode_provider_metadata,
    _validate_provider_profile,
    _validate_resource_limits,
    preflight_s3_build,
    validate_curated_store,
    validate_s3_stream,
)
from fs_memory_lab.s3_runtime import (
    EXPECTED_S3_SERVED_MODEL,
    S3_RESOURCE_LIMITS,
    sha256_bytes,
)


EXPERIMENT = REPO / "experiments" / "locomo-conv50-v1"
FORMAL_TARGETS = (
    EXPERIMENT / "stores" / "s3-curated",
    EXPERIMENT / "manifests" / "s3-curated.json",
    EXPERIMENT / "traces" / "s3-management",
    EXPERIMENT / "manifests" / "s3-curated.COMMITTED",
)
MAX_HTTP_REQUESTS = 4


def formal_targets_absent() -> None:
    unexpected = [str(path) for path in FORMAL_TARGETS if path.exists() or path.is_symlink()]
    if unexpected:
        raise S3BuildError(f"Formal S3 targets must remain absent during smoke: {unexpected}")


def write_json(path: Path, value: Any) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


class BoundedProvider:
    def __init__(self, inner: CompatibleChatProvider):
        self.inner = inner
        self.calls = 0

    def complete(self, messages: list[dict], tools: list[dict], config: Any) -> dict:
        if self.calls >= MAX_HTTP_REQUESTS:
            raise RuntimeError(f"Smoke HTTP request limit reached ({MAX_HTTP_REQUESTS})")
        self.calls += 1
        result = self.inner.complete(messages, tools, config)
        served = result.get("served_model")
        if served != EXPECTED_S3_SERVED_MODEL:
            raise RuntimeError(
                f"Unexpected served model: expected {EXPECTED_S3_SERVED_MODEL!r}, got {served!r}"
            )
        return result


def main() -> None:
    key = os.environ.get("FSMEM_API_KEY")
    if not key:
        raise RuntimeError("FSMEM_API_KEY is not available to the smoke process")
    formal_targets_absent()

    paths = {
        "stream_dir": EXPERIMENT / "streams" / "s3-management-v1",
        "stream_manifest": EXPERIMENT / "manifests" / "s3-management-stream.json",
        "prompt_contract": EXPERIMENT / "manifests" / "s3-management-prompt.json",
        "runtime_contract": EXPERIMENT / "manifests" / "s3-management-runtime.json",
        "s3_store": FORMAL_TARGETS[0],
        "s3_manifest": FORMAL_TARGETS[1],
        "trace_dir": FORMAL_TARGETS[2],
        "commit_marker": FORMAL_TARGETS[3],
        "work_root": REPO / "local-runs" / "s3-management",
    }
    preflight_s3_build(**paths)
    stream = validate_s3_stream(paths["stream_dir"], paths["stream_manifest"])
    chunk = stream.chunks[0]
    chunk_bytes = (stream.root / chunk["filename"]).read_bytes()
    if sha256_bytes(chunk_bytes) != chunk["sha256"]:
        raise S3BuildError("First frozen chunk changed after preflight")
    payload = chunk_bytes.decode("utf-8")
    user_message = render_s3_user_message(payload)

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    run_dir = REPO / "local-runs" / f"s3-smoke-{stamp}-{secrets.token_hex(4)}"
    run_dir.mkdir(parents=True, exist_ok=False)
    memory_root = run_dir / "memories"
    memory = MemoryFS(memory_root, run_dir / "trash")
    event_path = run_dir / "events.jsonl"

    provider = CompatibleChatProvider(
        base_url="https://soclaas-api.comp.nus.edu.sg/v1",
        model="coding",
        api_key=key,
        timeout=300,
        api_style="portable",
        max_response_bytes=20_000_000,
    )
    _validate_provider_profile(provider)
    bounded = BoundedProvider(provider)

    def event_sink(event: dict[str, Any]) -> None:
        with event_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(event, ensure_ascii=False, sort_keys=True) + "\n")
            handle.flush()
            os.fsync(handle.fileno())

    def tool_hook(stage: str, name: str, args: dict[str, Any]) -> None:
        if stage == "raw":
            raw = args.get("arguments")
            size = len(raw.encode("utf-8")) if isinstance(raw, str) else len(
                json.dumps(raw, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
            )
            if size > S3_RESOURCE_LIMITS["max_tool_arguments_bytes"]:
                raise S3BuildError(f"Tool arguments too large during smoke: {name}")
        elif stage == "after":
            _validate_resource_limits(memory_root)

    runner = AgentRunner(
        memory,
        bounded,
        max_rounds=MAX_HTTP_REQUESTS,
        event_sink=event_sink,
        tool_hook=tool_hook,
        max_tool_calls_per_response=8,
        max_tool_calls_per_episode=12,
    )
    try:
        result = runner.run("management", user_message)
        save_trace(result, run_dir / "trace.json")
        _validate_episode_provider_metadata(result)
        if result.prompt_sha256 != sha256_bytes(MANAGEMENT_PROMPT.encode("utf-8")):
            raise S3BuildError("Smoke used an unexpected management prompt")
        gate = validate_curated_store(memory_root, frozenset(chunk["locators"]))
        if not gate.files or gate.locator_mentions < 1:
            raise S3BuildError("Smoke did not create a cited memory file")
        formal_targets_absent()
        summary = {
            "status": "passed",
            "scope": "one frozen S3 chunk; local-runs only",
            "chunk": chunk["filename"],
            "chunk_sha256": chunk["sha256"],
            "source_turns": len(chunk["locators"]),
            "http_requests": bounded.calls,
            "rounds": result.rounds,
            "tool_calls": result.tool_calls,
            "usage": result.usage,
            "served_model": EXPECTED_S3_SERVED_MODEL,
            "files": sorted(gate.files),
            "locator_mentions": gate.locator_mentions,
            "store_sha256": gate.tree_sha256,
            "run_dir": str(run_dir),
            "formal_targets_untouched": True,
        }
        write_json(run_dir / "summary.json", summary)
        print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))
    except Exception as exc:
        partial: dict[str, Any] = {}
        if isinstance(exc, AgentRunError):
            partial = {"agent_partial": exc.partial}
        failure = {
            "status": "failed",
            "error_type": type(exc).__name__,
            "error": " ".join(str(exc).split())[:800],
            "http_requests": bounded.calls,
            "run_dir": str(run_dir),
            "formal_targets_untouched": all(
                not path.exists() and not path.is_symlink() for path in FORMAL_TARGETS
            ),
            **partial,
        }
        write_json(run_dir / "failure.json", failure)
        print(json.dumps(failure, ensure_ascii=False, indent=2, sort_keys=True))
        raise
    finally:
        key = ""
        os.environ.pop("FSMEM_API_KEY", None)


if __name__ == "__main__":
    main()
