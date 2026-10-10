"""A small Chat Completions-style tool loop with a provider-neutral HTTP adapter."""

from __future__ import annotations

import json
import hashlib
import os
import re
import signal
import threading
import time
import urllib.error
import urllib.request
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable, Protocol
from urllib.parse import urlparse

from .filesystem import MemoryFS, ToolError
from .foldering_prompt import FOLDERING_PROMPT, FOLDERING_TASK
from .paper_config import (CONTEXT_COMPACTION_KEEP_ROUNDS, CONTEXT_COMPACTION_TRIGGER,
                           FOLDERING, MANAGEMENT, SEARCH, RoleConfig)
from .paper_prompts import MANAGEMENT_PROMPT, SEARCH_PROMPT
from .paper_tools import (FOLDERING_PROFILE, FOLDERING_TOOL_DEFINITIONS,
                          MANAGEMENT_PROFILE, SEARCH_PROFILE, TOOL_DEFINITIONS)


COMPACTION_SYSTEM_PROMPT = (
    "Summarize the older memory-agent interaction for continuation. Preserve all facts, "
    "source locators, tool outcomes, unresolved work, and relevant file paths. Do not add "
    "new facts. Return only the running summary."
)
COMPACTION_USER_PREFIX = "Running summary of earlier turns:\n"
COMPACTION_SUMMARY_MAX_COMPLETION_TOKENS = 8192
COMPACTION_SUMMARY_MAX_ROUNDS = 1
COMPACTION_MAX_ATTEMPTS = 3
COMPACTION_RETRY_BACKOFF_SECONDS = (2, 4)
ORDINARY_REQUEST_MAX_ATTEMPTS = 3
ORDINARY_REQUEST_RETRY_BACKOFF_SECONDS = (2, 4)
RETRYABLE_HTTP_STATUS_CODES = frozenset({408, 429, 500, 502, 503, 504})
TRANSIENT_HTTP_MAX_ATTEMPTS = 5
TRANSIENT_HTTP_RETRY_BACKOFF_SECONDS = (5, 15, 30, 60)


@contextmanager
def _request_wall_clock_deadline(seconds: float):
    """Enforce a total POSIX request deadline, not only socket-idle time.

    ``urllib`` passes its timeout to the socket, where intermittent bytes can
    keep a non-streaming request alive indefinitely.  Formal runs are
    single-threaded on macOS, so an interval timer gives the configured timeout
    its intended whole-request meaning.  Non-main-thread/non-POSIX callers keep
    urllib's ordinary socket timeout as a portable fallback.
    """

    supported = (
        seconds > 0
        and threading.current_thread() is threading.main_thread()
        and hasattr(signal, "SIGALRM")
        and hasattr(signal, "setitimer")
        and hasattr(signal, "ITIMER_REAL")
    )
    if not supported:
        yield
        return

    started = time.monotonic()
    previous_handler = signal.getsignal(signal.SIGALRM)

    def expire(_signum, _frame):
        raise TimeoutError("API request exceeded its wall-clock deadline")

    signal.signal(signal.SIGALRM, expire)
    previous_delay, previous_interval = signal.setitimer(
        signal.ITIMER_REAL, float(seconds)
    )
    try:
        yield
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous_handler)
        if previous_delay > 0:
            elapsed = time.monotonic() - started
            signal.setitimer(
                signal.ITIMER_REAL,
                max(1e-6, previous_delay - elapsed),
                previous_interval,
            )


class TransientProviderError(RuntimeError):
    """A provider failure that is safe to retry for a read-only request."""

    def __init__(self, message: str, *, kind: str = "timeout",
                 http_status: int | None = None):
        if kind not in {"timeout", "http"}:
            raise ValueError("Transient provider error kind must be timeout or http")
        if kind == "http" and http_status not in RETRYABLE_HTTP_STATUS_CODES:
            raise ValueError("Transient HTTP status is not approved for retry")
        if kind == "timeout" and http_status is not None:
            raise ValueError("Timeout errors cannot carry an HTTP status")
        super().__init__(message)
        self.kind = kind
        self.http_status = http_status


def _transient_retry_policy(
    error: TransientProviderError, *, compaction: bool
) -> tuple[int, tuple[int, ...]]:
    if error.kind == "http":
        return TRANSIENT_HTTP_MAX_ATTEMPTS, TRANSIENT_HTTP_RETRY_BACKOFF_SECONDS
    if compaction:
        return COMPACTION_MAX_ATTEMPTS, COMPACTION_RETRY_BACKOFF_SECONDS
    return ORDINARY_REQUEST_MAX_ATTEMPTS, ORDINARY_REQUEST_RETRY_BACKOFF_SECONDS


def _transient_failure_message(
    scope: str, error: TransientProviderError, attempts: int
) -> str:
    if error.kind == "http":
        return (
            f"{scope} failed with retryable HTTP {error.http_status} after "
            f"{attempts} attempts: {error}"
        )
    return f"{scope} timed out after {attempts} attempts"


class ChatProvider(Protocol):
    def complete(self, messages: list[dict], tools: list[dict], config: RoleConfig) -> dict: ...


class CompatibleChatProvider:
    """Non-streaming /chat/completions adapter; no vendor SDK or key file required."""

    def __init__(self, base_url: str, model: str | None, api_key: str, timeout: int = 300,
                 api_style: str = "paper", max_response_bytes: int = 20_000_000):
        if not base_url or not api_key:
            raise ValueError("Base URL and API key are required")
        parsed = urlparse(base_url)
        if parsed.scheme != "https" and not (parsed.scheme == "http" and parsed.hostname in {"localhost", "127.0.0.1"}):
            raise ValueError("Use HTTPS for remote API endpoints")
        if api_style not in {"paper", "portable"}:
            raise ValueError("FSMEM_API_STYLE must be paper or portable")
        if max_response_bytes < 1:
            raise ValueError("max_response_bytes must be positive")
        self.endpoint = base_url.rstrip("/") + "/chat/completions"
        self.model = model
        self.api_key = api_key
        self.timeout = timeout
        self.api_style = api_style
        self.max_response_bytes = max_response_bytes

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
        temperature = getattr(config, "temperature", None)
        if temperature is not None:
            payload["temperature"] = temperature
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
            with _request_wall_clock_deadline(self.timeout):
                with urllib.request.urlopen(request, timeout=self.timeout) as response:
                    raw = response.read(self.max_response_bytes + 1)
                    if len(raw) > self.max_response_bytes:
                        raise RuntimeError(
                            f"API response exceeded {self.max_response_bytes} bytes"
                        )
                    data = json.loads(raw.decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = self._safe_http_error(exc)
            if exc.code in RETRYABLE_HTTP_STATUS_CODES:
                raise TransientProviderError(
                    detail, kind="http", http_status=exc.code
                ) from exc
            raise RuntimeError(detail) from exc
        except urllib.error.URLError as exc:
            if isinstance(exc.reason, TimeoutError):
                raise TransientProviderError("API request timed out") from exc
            raise RuntimeError(f"Cannot connect to API endpoint: {exc.reason}") from exc
        except TimeoutError as exc:
            raise TransientProviderError("API request timed out") from exc
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


class AgentRunError(RuntimeError):
    """An episode failure carrying the safe partial trace accumulated so far."""

    def __init__(self, message: str, *, role: str, configuration: dict,
                 prompt_sha256: str, input_sha256: str, rounds: int,
                 tool_calls: int, usage: list[dict], trace: list[dict], stage: str):
        super().__init__(message)
        self.partial = {
            "status": "failed",
            "error": {"message": message, "stage": stage, "type": type(self).__name__},
            "rounds": rounds,
            "tool_calls": tool_calls,
            "usage": list(usage),
            "trace": list(trace),
            "role": role,
            "configuration": configuration,
            "prompt_sha256": prompt_sha256,
            "input_sha256": input_sha256,
        }


class AgentRunner:
    def __init__(self, memory: MemoryFS, provider: ChatProvider, *, max_rounds: int | None = None,
                 event_sink: Callable[[dict], None] | None = None,
                 tool_hook: Callable[[str, str, dict], None] | None = None,
                 max_tool_calls_per_response: int | None = None,
                 max_tool_calls_per_episode: int | None = None):
        if max_rounds is not None and max_rounds < 1:
            raise ValueError("max_rounds must be positive")
        if max_tool_calls_per_response is not None and max_tool_calls_per_response < 1:
            raise ValueError("max_tool_calls_per_response must be positive")
        if max_tool_calls_per_episode is not None and max_tool_calls_per_episode < 1:
            raise ValueError("max_tool_calls_per_episode must be positive")
        self.memory = memory
        self.provider = provider
        self.max_rounds = max_rounds
        self.event_sink = event_sink
        self.tool_hook = tool_hook
        self.max_tool_calls_per_response = max_tool_calls_per_response
        self.max_tool_calls_per_episode = max_tool_calls_per_episode

    def _emit(self, trace: list[dict], event: dict) -> None:
        trace.append(event)
        if self.event_sink is not None:
            self.event_sink(event)

    def _compact(self, messages: list[dict], round_starts: list[int], config: RoleConfig,
                 usage: list[dict], trace: list[dict], round_number: int) -> tuple[list[dict], list[int]]:
        """Paper-shaped summary+3-round compaction; exact summarizer is unpublished."""
        keep_start = round_starts[-CONTEXT_COMPACTION_KEEP_ROUNDS]
        old_text = json.dumps(messages[2:keep_start], ensure_ascii=False)
        summary_config = RoleConfig(
            config.model,
            config.reasoning_effort,
            COMPACTION_SUMMARY_MAX_COMPLETION_TOKENS,
            COMPACTION_SUMMARY_MAX_ROUNDS,
        )
        request = [
            {"role": "system", "content": COMPACTION_SYSTEM_PROMPT},
            {"role": "user", "content": old_text},
        ]
        result: dict | None = None
        attempt = 0
        while result is None:
            attempt += 1
            try:
                result = self.provider.complete(request, [], summary_config)
            except TransientProviderError as exc:
                max_attempts, backoff = _transient_retry_policy(
                    exc, compaction=True
                )
                will_retry = attempt < max_attempts
                delay = (
                    backoff[attempt - 1]
                    if will_retry
                    else 0
                )
                self._emit(trace, {
                    "round": round_number,
                    "compaction_retry": True,
                    "attempt": attempt,
                    "max_attempts": max_attempts,
                    "will_retry": will_retry,
                    "delay_seconds": delay,
                    "error_type": "TransientProviderError",
                    "error_kind": exc.kind,
                    "http_status": exc.http_status,
                    "error_message": str(exc),
                })
                if not will_retry:
                    raise RuntimeError(_transient_failure_message(
                        "Context compaction API request", exc, attempt
                    )) from exc
                time.sleep(delay)
        if result is None:  # pragma: no cover - defensive invariant
            raise RuntimeError("Context compaction produced no provider result")
        if result.get("finish_reason") != "stop":
            raise RuntimeError(
                "Context compaction did not finish cleanly; expected finish_reason='stop'"
            )
        summary = result["message"].get("content")
        if not isinstance(summary, str) or not summary.strip():
            raise RuntimeError("Context compaction did not return a summary")
        usage.append({"compaction": True, **result.get("usage", {})})
        self._emit(trace, {"round": round_number, "compaction": True,
                           "dropped_messages": keep_start - 2,
                           "kept_rounds": CONTEXT_COMPACTION_KEEP_ROUNDS,
                           "attempts": attempt,
                           "usage": result.get("usage", {}),
                           "finish_reason": result.get("finish_reason"),
                           "response_id": result.get("response_id"),
                           "served_model": result.get("served_model"),
                           "system_fingerprint": result.get("system_fingerprint"),
                           "summary": summary,
                           "summary_sha256": hashlib.sha256(summary.encode("utf-8")).hexdigest(),
                           "input_sha256": hashlib.sha256(old_text.encode("utf-8")).hexdigest()})
        new_messages = messages[:2] + [{
            "role": "user",
            "content": COMPACTION_USER_PREFIX + summary,
        }] + messages[keep_start:]
        new_starts = [start - keep_start + 3 for start in round_starts[-CONTEXT_COMPACTION_KEEP_ROUNDS:]]
        return new_messages, new_starts

    def run(self, role: str, input_text: str) -> EpisodeResult:
        if role == "management":
            prompt = MANAGEMENT_PROMPT
            config = MANAGEMENT
            allowed = MANAGEMENT_PROFILE
            definitions = TOOL_DEFINITIONS
            user_text = input_text
        elif role == "foldering":
            if input_text != FOLDERING_TASK:
                raise ValueError("Foldering Agent accepts only its fixed, versioned task instruction")
            prompt = FOLDERING_PROMPT
            config = FOLDERING
            allowed = FOLDERING_PROFILE
            definitions = FOLDERING_TOOL_DEFINITIONS
            user_text = input_text
        elif role == "search":
            prompt = SEARCH_PROMPT
            config = SEARCH
            allowed = SEARCH_PROFILE
            definitions = TOOL_DEFINITIONS
            user_text = input_text + "\n\nCite every factual claim in bracket notation."
        else:
            raise ValueError("Role must be management, foldering, or search")
        tools = [definitions[name] for name in allowed]
        messages: list[dict] = [{"role": "system", "content": prompt}, {"role": "user", "content": user_text}]
        trace: list[dict] = []
        usage: list[dict] = []
        total_calls = 0
        round_starts: list[int] = []
        limit = self.max_rounds or config.max_rounds

        prompt_sha256 = hashlib.sha256(prompt.encode("utf-8")).hexdigest()
        input_sha256 = hashlib.sha256(input_text.encode("utf-8")).hexdigest()

        def failure(message: str, stage: str, rounds: int) -> AgentRunError:
            return AgentRunError(
                message,
                role=role,
                configuration=asdict(config),
                prompt_sha256=prompt_sha256,
                input_sha256=input_sha256,
                rounds=rounds,
                tool_calls=total_calls,
                usage=usage,
                trace=trace,
                stage=stage,
            )

        for round_number in range(1, limit + 1):
            round_starts.append(len(messages))
            result: dict | None = None
            attempt = 0
            while result is None:
                attempt += 1
                try:
                    result = self.provider.complete(messages, tools, config)
                except TransientProviderError as exc:
                    max_attempts, backoff = _transient_retry_policy(
                        exc, compaction=False
                    )
                    will_retry = attempt < max_attempts
                    delay = (
                        backoff[attempt - 1]
                        if will_retry
                        else 0
                    )
                    self._emit(trace, {
                        "round": round_number,
                        "provider_retry": True,
                        "attempt": attempt,
                        "max_attempts": max_attempts,
                        "will_retry": will_retry,
                        "delay_seconds": delay,
                        "error_type": "TransientProviderError",
                        "error_kind": exc.kind,
                        "http_status": exc.http_status,
                        "error_message": str(exc),
                    })
                    if not will_retry:
                        raise failure(
                            _transient_failure_message(
                                "Provider API request", exc, attempt
                            ),
                            "provider",
                            round_number,
                        ) from exc
                    time.sleep(delay)
                except Exception as exc:
                    raise failure(str(exc), "provider", round_number) from exc
            if result is None:  # pragma: no cover - defensive invariant
                raise failure("Provider returned no result", "provider", round_number)
            if not isinstance(result, dict):
                raise failure(
                    "Provider response must be a JSON object",
                    "provider-response",
                    round_number,
                )
            try:
                message = result["message"]
                if not isinstance(message, dict):
                    raise TypeError("message is not an object")
            except (KeyError, TypeError) as exc:
                raise failure(
                    "Provider response is missing a valid message object",
                    "provider-response",
                    round_number,
                ) from exc
            round_usage = result.get("usage", {})
            if not isinstance(round_usage, dict):
                raise failure(
                    "Provider usage must be a JSON object",
                    "provider-response",
                    round_number,
                )
            usage.append(round_usage)
            calls = message.get("tool_calls") or []
            if not isinstance(calls, list) or any(not isinstance(call, dict) for call in calls):
                raise failure(
                    "Provider tool_calls must be a list of objects",
                    "provider-response",
                    round_number,
                )
            if any(not isinstance(call.get("function"), dict) for call in calls):
                raise failure(
                    "Every provider tool call must contain a function object",
                    "provider-response",
                    round_number,
                )
            if (
                self.max_tool_calls_per_response is not None
                and len(calls) > self.max_tool_calls_per_response
            ):
                raise failure(
                    "Provider returned too many tool calls in one response",
                    "tool-call-limit",
                    round_number,
                )
            if (
                self.max_tool_calls_per_episode is not None
                and total_calls + len(calls) > self.max_tool_calls_per_episode
            ):
                raise failure(
                    "Episode exceeded the total tool-call safety limit",
                    "tool-call-limit",
                    round_number,
                )
            self._emit(trace, {"round": round_number,
                               "attempts": attempt,
                               "assistant_content": message.get("content"),
                               "tool_calls": [
                                   {"id": call.get("id"),
                                    "name": call.get("function", {}).get("name")}
                                   for call in calls
                               ],
                               "usage": result.get("usage", {}),
                               "finish_reason": result.get("finish_reason"),
                               "response_id": result.get("response_id"),
                               "served_model": result.get("served_model"),
                               "system_fingerprint": result.get("system_fingerprint")})
            if result.get("finish_reason") == "length":
                raise failure(
                    "Model hit the completion cap; refusing a truncated episode",
                    "completion-cap",
                    round_number,
                )
            if not calls:
                content = message.get("content")
                if not isinstance(content, str) or not content.strip():
                    raise failure(
                        "Model finished without an answer or tool calls",
                        "empty-response",
                        round_number,
                    )
                return EpisodeResult(content, round_number, total_calls, usage, trace, role,
                                     asdict(config), prompt_sha256, input_sha256)
            messages.append({"role": "assistant", "content": message.get("content"), "tool_calls": calls})
            for call in calls:
                function = call.get("function") or {}
                name = function.get("name", "")
                args: dict | None = None
                completed_observation: str | None = None
                try:
                    arguments = function.get("arguments", "{}")
                    if self.tool_hook is not None:
                        self.tool_hook("raw", name, {"arguments": arguments})
                    args = json.loads(arguments) if isinstance(arguments, str) else arguments
                    if not isinstance(args, dict):
                        raise ToolError("Tool arguments must be a JSON object")
                    if self.tool_hook is not None:
                        self.tool_hook("before", name, args)
                    observation = self.memory.call(role, name, args)
                    completed_observation = observation
                    if self.tool_hook is not None:
                        self.tool_hook("after", name, args)
                    ok = True
                except (json.JSONDecodeError, ToolError) as exc:
                    if completed_observation is None:
                        observation = f"TOOL ERROR: {exc}"
                    else:
                        observation = (
                            f"{completed_observation}\n\n"
                            f"POST-TOOL VALIDATION ERROR: {exc}"
                        )
                    ok = False
                except Exception as exc:
                    total_calls += 1
                    self._emit(trace, {"round": round_number, "tool": name,
                                       "arguments": args, "ok": False,
                                       "observation": f"TOOL FAILURE: {exc}"})
                    raise failure(str(exc), "tool-execution", round_number) from exc
                total_calls += 1
                self._emit(trace, {"round": round_number, "tool": name,
                                   "arguments": args, "ok": ok,
                                   "observation": observation})
                messages.append({"role": "tool", "tool_call_id": call.get("id"), "content": observation})
            if (result.get("usage", {}).get("prompt_tokens", 0) > CONTEXT_COMPACTION_TRIGGER
                    and len(round_starts) > CONTEXT_COMPACTION_KEEP_ROUNDS):
                try:
                    messages, round_starts = self._compact(
                        messages, round_starts, config, usage, trace, round_number
                    )
                except Exception as exc:
                    raise failure(str(exc), "context-compaction", round_number) from exc
        raise failure(
            f"Agent exceeded {limit} model rounds; inspect trace before retrying",
            "round-limit",
            limit,
        )

    def run_foldering(self) -> EpisodeResult:
        """Run the fixed S2 foldering task; the caller must mount a disposable S1 copy."""
        return self.run("foldering", FOLDERING_TASK)


def save_trace(result: EpisodeResult, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"answer": result.answer, "rounds": result.rounds,
                                "tool_calls": result.tool_calls, "usage": result.usage,
                                "trace": result.trace, "role": result.role,
                                "configuration": result.configuration,
                                "prompt_sha256": result.prompt_sha256,
                                "input_sha256": result.input_sha256}, ensure_ascii=False, indent=2), encoding="utf-8")
