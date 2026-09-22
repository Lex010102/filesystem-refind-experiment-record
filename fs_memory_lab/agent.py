"""A small Chat Completions-style tool loop with a provider-neutral HTTP adapter."""

from __future__ import annotations

import json
import hashlib
import os
import re
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Protocol
from urllib.parse import urlparse

from .filesystem import MemoryFS, ToolError
from .paper_config import (CONTEXT_COMPACTION_KEEP_ROUNDS, CONTEXT_COMPACTION_TRIGGER,
                           MANAGEMENT, SEARCH, RoleConfig)
from .paper_prompts import MANAGEMENT_PROMPT, SEARCH_PROMPT
from .paper_tools import MANAGEMENT_PROFILE, SEARCH_PROFILE, TOOL_DEFINITIONS


class ChatProvider(Protocol):
    def complete(self, messages: list[dict], tools: list[dict], config: RoleConfig) -> dict: ...


class CompatibleChatProvider:
    """Non-streaming /chat/completions adapter; no vendor SDK or key file required."""

    def __init__(self, base_url: str, model: str | None, api_key: str, timeout: int = 300,
                 api_style: str = "paper"):
        if not base_url or not api_key:
            raise ValueError("Base URL and API key are required")
        parsed = urlparse(base_url)
        if parsed.scheme != "https" and not (parsed.scheme == "http" and parsed.hostname in {"localhost", "127.0.0.1"}):
            raise ValueError("Use HTTPS for remote API endpoints")
        if api_style not in {"paper", "portable"}:
            raise ValueError("FSMEM_API_STYLE must be paper or portable")
        self.endpoint = base_url.rstrip("/") + "/chat/completions"
        self.model = model
        self.api_key = api_key
        self.timeout = timeout
        self.api_style = api_style

    @classmethod
    def from_environment(cls) -> "CompatibleChatProvider":
        return cls(
            os.environ.get("FSMEM_API_BASE_URL", "https://api.openai.com/v1"),
            os.environ.get("FSMEM_MODEL") or None,
            os.environ.get("FSMEM_API_KEY", ""),
            api_style=os.environ.get("FSMEM_API_STYLE", "paper"),
        )

    def _safe_http_error(self, exc: urllib.error.HTTPError) -> str:
        """Surface useful API diagnostics without echoing keys or full responses."""
        fields: list[str] = []
        try:
            body = json.loads(exc.read(4096).decode("utf-8", errors="replace"))
            if isinstance(body, dict):
                error = body.get("error", body)
                if isinstance(error, dict):
                    for name in ("type", "code", "param", "message"):
                        value = error.get(name)
                        if isinstance(value, (str, int)) and str(value):
                            fields.append(f"{name}={value}")
                    if not fields and isinstance(error.get("detail"), str):
                        fields.append(f"detail={error['detail']}")
                elif isinstance(error, str):
                    fields.append(error)
        except (ValueError, OSError, UnicodeError):
            pass
        if not fields:
            return f"API returned HTTP {exc.code}; provider supplied no structured error details"
        detail = " ".join(fields)
        detail = detail.replace(self.api_key, "[REDACTED_KEY]")
        detail = re.sub(r"\b(?:clsk|sk)[_-][A-Za-z0-9_-]{10,}\b", "[REDACTED_KEY]", detail)
        detail = re.sub(r"\bBearer\s+\S+", "Bearer [REDACTED_KEY]", detail, flags=re.IGNORECASE)
        detail = " ".join(detail.split())[:400]
        return f"API returned HTTP {exc.code}: {detail}"

    def complete(self, messages: list[dict], tools: list[dict], config: RoleConfig) -> dict:
        payload = {"model": self.model or config.model, "messages": messages,
                   "stream": False}
        if tools or self.api_style == "paper":
            payload["tools"] = tools
        if self.api_style == "paper":
            payload["reasoning_effort"] = config.reasoning_effort
            payload["max_completion_tokens"] = config.max_completion_tokens
        if tools:
            payload["tool_choice"] = "auto"
        request = urllib.request.Request(
            self.endpoint,
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={"Authorization": "Bearer " + self.api_key, "Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                data = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            raise RuntimeError(self._safe_http_error(exc)) from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(f"Cannot connect to API endpoint: {exc.reason}") from exc
        try:
            choice = data["choices"][0]
            return {"message": choice["message"], "usage": data.get("usage", {}),
                    "finish_reason": choice.get("finish_reason"),
                    "response_id": data.get("id"), "system_fingerprint": data.get("system_fingerprint"),
                    "served_model": data.get("model")}
        except (KeyError, IndexError, TypeError) as exc:
            raise RuntimeError("API response is not a compatible Chat Completions response") from exc


@dataclass
class EpisodeResult:
    answer: str
    rounds: int
    tool_calls: int
    usage: list[dict]
    trace: list[dict]
    role: str
    configuration: dict
    prompt_sha256: str
    input_sha256: str


class AgentRunner:
    def __init__(self, memory: MemoryFS, provider: ChatProvider, *, max_rounds: int | None = None):
        if max_rounds is not None and max_rounds < 1:
            raise ValueError("max_rounds must be positive")
        self.memory = memory
        self.provider = provider
        self.max_rounds = max_rounds

    def _compact(self, messages: list[dict], round_starts: list[int], config: RoleConfig,
                 usage: list[dict], trace: list[dict], round_number: int) -> tuple[list[dict], list[int]]:
        """Paper-shaped summary+3-round compaction; exact summarizer is unpublished."""
        keep_start = round_starts[-CONTEXT_COMPACTION_KEEP_ROUNDS]
        old_text = json.dumps(messages[2:keep_start], ensure_ascii=False)
        summary_config = RoleConfig(config.model, config.reasoning_effort, 8192, 1)
        request = [
            {"role": "system", "content": "Summarize the older memory-agent interaction for continuation. Preserve all facts, source locators, tool outcomes, unresolved work, and relevant file paths. Do not add new facts. Return only the running summary."},
            {"role": "user", "content": old_text},
        ]
        result = self.provider.complete(request, [], summary_config)
        summary = result["message"].get("content")
        if not isinstance(summary, str) or not summary.strip():
            raise RuntimeError("Context compaction did not return a summary")
        usage.append({"compaction": True, **result.get("usage", {})})
        trace.append({"round": round_number, "compaction": True,
                      "dropped_messages": keep_start - 2,
                      "kept_rounds": CONTEXT_COMPACTION_KEEP_ROUNDS,
                      "usage": result.get("usage", {})})
        new_messages = messages[:2] + [{"role": "user", "content": "Running summary of earlier turns:\n" + summary}] + messages[keep_start:]
        new_starts = [start - keep_start + 3 for start in round_starts[-CONTEXT_COMPACTION_KEEP_ROUNDS:]]
        return new_messages, new_starts

    def run(self, role: str, input_text: str) -> EpisodeResult:
        if role not in {"management", "search"}:
            raise ValueError("Role must be management or search")
        prompt = MANAGEMENT_PROMPT if role == "management" else SEARCH_PROMPT
        config = MANAGEMENT if role == "management" else SEARCH
        allowed = MANAGEMENT_PROFILE if role == "management" else SEARCH_PROFILE
        tools = [TOOL_DEFINITIONS[name] for name in allowed]
        user_text = input_text if role == "management" else input_text + "\n\nCite every factual claim in bracket notation."
        messages: list[dict] = [{"role": "system", "content": prompt}, {"role": "user", "content": user_text}]
        trace: list[dict] = []
        usage: list[dict] = []
        total_calls = 0
        round_starts: list[int] = []
        limit = self.max_rounds or config.max_rounds
        for round_number in range(1, limit + 1):
            round_starts.append(len(messages))
            result = self.provider.complete(messages, tools, config)
            if result.get("finish_reason") == "length":
                raise RuntimeError("Model hit the completion cap; refusing a truncated episode")
            message = result["message"]
            usage.append(result.get("usage", {}))
            calls = message.get("tool_calls") or []
            trace.append({"round": round_number, "assistant_content": message.get("content"),
                          "tool_calls": [{"id": call.get("id"), "name": call.get("function", {}).get("name")}
                                         for call in calls], "usage": result.get("usage", {}),
                          "response_id": result.get("response_id"),
                          "served_model": result.get("served_model"),
                          "system_fingerprint": result.get("system_fingerprint")})
            if not calls:
                content = message.get("content")
                if not isinstance(content, str) or not content.strip():
                    raise RuntimeError("Model finished without an answer or tool calls")
                return EpisodeResult(content, round_number, total_calls, usage, trace, role,
                                     asdict(config), hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
                                     hashlib.sha256(input_text.encode("utf-8")).hexdigest())
            messages.append({"role": "assistant", "content": message.get("content"), "tool_calls": calls})
            for call in calls:
                function = call.get("function") or {}
                name = function.get("name", "")
                args: dict | None = None
                try:
                    arguments = function.get("arguments", "{}")
                    args = json.loads(arguments) if isinstance(arguments, str) else arguments
                    if not isinstance(args, dict):
                        raise ToolError("Tool arguments must be a JSON object")
                    observation = self.memory.call(role, name, args)
                    ok = True
                except (json.JSONDecodeError, ToolError) as exc:
                    observation = f"TOOL ERROR: {exc}"
                    ok = False
                total_calls += 1
                trace.append({"round": round_number, "tool": name, "arguments": args,
                              "ok": ok, "observation": observation})
                messages.append({"role": "tool", "tool_call_id": call.get("id"), "content": observation})
            if (result.get("usage", {}).get("prompt_tokens", 0) > CONTEXT_COMPACTION_TRIGGER
                    and len(round_starts) > CONTEXT_COMPACTION_KEEP_ROUNDS):
                messages, round_starts = self._compact(messages, round_starts, config, usage, trace, round_number)
        raise RuntimeError(f"Agent exceeded {limit} model rounds; inspect trace before retrying")


def save_trace(result: EpisodeResult, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"answer": result.answer, "rounds": result.rounds,
                                "tool_calls": result.tool_calls, "usage": result.usage,
                                "trace": result.trace, "role": result.role,
                                "configuration": result.configuration,
                                "prompt_sha256": result.prompt_sha256,
                                "input_sha256": result.input_sha256}, ensure_ascii=False, indent=2), encoding="utf-8")
