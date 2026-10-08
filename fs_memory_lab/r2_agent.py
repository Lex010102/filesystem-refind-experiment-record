"""Four-action textual ReAct Retrieval Agent for R2-Raw evidence collection."""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Callable, Mapping, Sequence

from .agent import ChatProvider, TransientProviderError
from .evidence import (
    EvidenceValidationError,
    QuestionInput,
    StopRecord,
    canonical_json_bytes,
)
from .r2_index import R2RawIndex, R2SearchHit, R2SearchResult
from .r2_prompts import (
    R2_DERIVED_SYSTEM_PROMPT,
    render_r2_observation,
    render_r2_user_prompt,
    verify_r2_prompts,
)
from .r2_protocol import R2_PARAMETERS, R2_RUNTIME_LIMITS, verify_r2_protocol
from .r2_tools import (
    R2Action,
    R2ActionError,
    format_r2_error_observation,
    format_r2_search_observation,
    parse_r2_action,
    verify_r2_action_contract,
)


R2_AGENT_PROTOCOL_VERSION = "r2-raw-agent-v1"


@dataclass(frozen=True)
class R2PlannerConfig:
    model: str
    reasoning_effort: str
    max_completion_tokens: int
    max_rounds: int
    temperature: int


class R2AgentError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        stage: str,
        provider_round: int,
        provider_request_attempts: int,
        trace: Sequence[Mapping[str, Any]],
    ) -> None:
        super().__init__(message)
        self.stage = stage
        self.provider_round = provider_round
        self.provider_request_attempts = provider_request_attempts
        self.trace = tuple(dict(item) for item in trace)


class _R2ProviderFailure(RuntimeError):
    def __init__(self, message: str, *, attempts: int) -> None:
        super().__init__(message)
        self.attempts = attempts


@dataclass(frozen=True)
class R2SavedNote:
    observation_id: str
    hit: R2SearchHit
    retrieval_round: int
    query_terms: tuple[str, ...]
    selection_ordinal: int


@dataclass(frozen=True)
class R2EpisodeOutcome:
    protocol_version: str
    episode_id: str
    cell_id: str
    store_id: str
    question: QuestionInput
    notes: tuple[R2SavedNote, ...]
    stop: StopRecord
    trace: tuple[Mapping[str, Any], ...]
    usage: tuple[Mapping[str, Any], ...]
    provider_rounds: int
    provider_request_attempts: int
    searches: int
    note_actions: int
    finish_actions: int
    invalid_actions: int
    requested_model: str
    served_models: tuple[str, ...]
    api_style: str

    def __post_init__(self) -> None:
        if self.protocol_version != R2_AGENT_PROTOCOL_VERSION:
            raise EvidenceValidationError("R2 episode protocol version differs")
        if self.cell_id not in {"E2", "E4"}:
            raise EvidenceValidationError("R2-Raw episode cell must be E2 or E4")
        expected_store = "s1" if self.cell_id == "E2" else "s2"
        if self.store_id != expected_store:
            raise EvidenceValidationError("R2 episode cell/store mapping differs")
        if self.api_style not in {"paper", "portable"}:
            raise EvidenceValidationError("R2 episode API style is invalid")
        if self.provider_rounds > int(R2_PARAMETERS["agent_action_cap"]):
            raise EvidenceValidationError("R2 episode exceeds the four-action cap")
        if self.stop.reason == "round_limit" and self.provider_rounds != int(
            R2_PARAMETERS["agent_action_cap"]
        ):
            raise EvidenceValidationError("R2 cap stop occurred before action four")
        if self.stop.reason == "evidence_sufficient" and not self.notes:
            raise EvidenceValidationError("R2 sufficient stop requires saved notes")
        if self.stop.reason == "no_relevant_evidence" and self.notes:
            raise EvidenceValidationError("R2 no-evidence stop cannot contain notes")
        object.__setattr__(
            self, "trace", tuple(MappingProxyType(dict(item)) for item in self.trace)
        )
        object.__setattr__(
            self, "usage", tuple(MappingProxyType(dict(item)) for item in self.usage)
        )


def _safe_usage(value: Any) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError("provider usage must be an object")
    plain = json.loads(canonical_json_bytes(value))
    required = {"prompt_tokens", "completion_tokens", "total_tokens"}
    if set(plain) & required != required:
        raise ValueError("provider usage token totals are required")
    if any(
        isinstance(plain[key], bool) or not isinstance(plain[key], int) or plain[key] < 0
        for key in required
    ):
        raise ValueError("provider token usage must use nonnegative integers")
    if plain["total_tokens"] != plain["prompt_tokens"] + plain["completion_tokens"]:
        raise ValueError("provider total_tokens is inconsistent")
    return plain


class R2RetrievalAgent:
    def __init__(
        self,
        *,
        index: R2RawIndex,
        provider: ChatProvider,
        requested_model: str,
        api_style: str = "portable",
        sleeper: Callable[[float], None] = time.sleep,
        event_sink: Callable[[Mapping[str, Any]], None] | None = None,
    ) -> None:
        verify_r2_protocol()
        verify_r2_prompts()
        verify_r2_action_contract()
        if not isinstance(requested_model, str) or not requested_model.strip():
            raise EvidenceValidationError("R2 requested_model must be nonempty")
        if api_style not in {"paper", "portable"}:
            raise EvidenceValidationError("R2 api_style must be paper or portable")
        self.index = index
        self.provider = provider
        self.requested_model = requested_model
        self.api_style = api_style
        self.sleeper = sleeper
        self.event_sink = event_sink
        self.config = R2PlannerConfig(
            requested_model,
            "high",
            int(R2_PARAMETERS["stage1_max_completion_tokens"]),
            int(R2_PARAMETERS["agent_action_cap"]),
            int(R2_PARAMETERS["temperature"]),
        )

    def _emit(self, trace: list[dict[str, Any]], event: dict[str, Any]) -> None:
        trace.append(event)
        if self.event_sink is not None:
            self.event_sink(event)

    def _complete(
        self,
        messages: list[dict[str, Any]],
        *,
        trace: list[dict[str, Any]],
    ) -> tuple[dict[str, Any], int]:
        attempts = 0
        while True:
            attempts += 1
            try:
                response = self.provider.complete(messages, [], self.config)
                if not isinstance(response, Mapping):
                    raise ValueError("provider response must be an object")
                return dict(response), attempts
            except TransientProviderError as exc:
                if exc.kind == "http":
                    maximum = int(R2_RUNTIME_LIMITS["http_max_attempts"])
                    backoff = tuple(R2_RUNTIME_LIMITS["http_retry_backoff_seconds"])
                else:
                    maximum = int(R2_RUNTIME_LIMITS["timeout_max_attempts"])
                    backoff = tuple(R2_RUNTIME_LIMITS["timeout_retry_backoff_seconds"])
                self._emit(
                    trace,
                    {
                        "event": "provider_retry",
                        "attempt": attempts,
                        "kind": exc.kind,
                        "http_status": exc.http_status,
                    },
                )
                if attempts >= maximum:
                    raise _R2ProviderFailure(str(exc), attempts=attempts) from exc
                self.sleeper(float(backoff[attempts - 1]))
            except Exception as exc:
                raise _R2ProviderFailure(str(exc), attempts=attempts) from exc

    def run(self, *, cell_id: str, question: QuestionInput) -> R2EpisodeOutcome:
        expected_store = {"E2": "s1", "E4": "s2"}.get(cell_id)
        if expected_store is None or self.index.corpus.store_id != expected_store:
            raise EvidenceValidationError("R2 cell and loaded store do not match")
        if question.conversation_id != self.index.corpus.store.snapshot.conversation_id:
            raise EvidenceValidationError("R2 question and corpus conversation differ")
        episode_id = f"r2-{cell_id.lower()}-{question.question_id}"
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": R2_DERIVED_SYSTEM_PROMPT},
            {"role": "user", "content": render_r2_user_prompt(question.question)},
        ]
        trace: list[dict[str, Any]] = []
        usage: list[dict[str, Any]] = []
        notes: list[R2SavedNote] = []
        noted_anchors: set[str] = set()
        seen_sessions: set[str] = set()
        last_search: R2SearchResult | None = None
        last_observation_id: str | None = None
        provider_attempts = 0
        searches = note_actions = finish_actions = invalid_actions = 0
        served_models: list[str] = []
        token_total = 0
        stop: StopRecord | None = None

        self._emit(
            trace,
            {
                "event": "runtime_start",
                "protocol_version": R2_AGENT_PROTOCOL_VERSION,
                "requested_model": self.requested_model,
                "api_style": self.api_style,
                "paper_target": {
                    "reasoning_effort": self.config.reasoning_effort,
                    "temperature": self.config.temperature,
                    "max_completion_tokens": self.config.max_completion_tokens,
                },
                "actual_wire_profile": {
                    "reasoning_effort": (
                        self.config.reasoning_effort
                        if self.api_style == "paper"
                        else None
                    ),
                    "temperature": self.config.temperature,
                    "max_completion_tokens": (
                        self.config.max_completion_tokens
                        if self.api_style == "paper"
                        else None
                    ),
                },
            },
        )

        action_cap = int(R2_PARAMETERS["agent_action_cap"])
        for provider_round in range(1, action_cap + 1):
            try:
                response, attempts = self._complete(messages, trace=trace)
            except _R2ProviderFailure as exc:
                raise R2AgentError(
                    f"R2 provider request failed: {exc}",
                    stage="provider_request",
                    provider_round=provider_round,
                    provider_request_attempts=provider_attempts + exc.attempts,
                    trace=trace,
                ) from exc
            provider_attempts += attempts
            try:
                round_usage = _safe_usage(response.get("usage"))
                token_total += round_usage["total_tokens"]
                served_model = response.get("served_model")
                if not isinstance(served_model, str) or not served_model.strip():
                    raise ValueError("provider must report served_model")
            except (TypeError, ValueError) as exc:
                raise R2AgentError(
                    f"R2 provider response is invalid: {exc}",
                    stage="provider_response",
                    provider_round=provider_round,
                    provider_request_attempts=provider_attempts,
                    trace=trace,
                ) from exc
            usage.append(round_usage)
            if served_model not in served_models:
                served_models.append(served_model)
            self._emit(
                trace,
                {
                    "event": "provider_response",
                    "provider_round": provider_round,
                    "attempts": attempts,
                    "served_model": served_model,
                    "finish_reason": response.get("finish_reason"),
                    "response_id": response.get("response_id"),
                    "usage": round_usage,
                },
            )
            if token_total > int(R2_RUNTIME_LIMITS["token_safety_fuse_limit"]):
                raise R2AgentError(
                    "R2 provider token safety fuse exceeded",
                    stage="token_safety_fuse",
                    provider_round=provider_round,
                    provider_request_attempts=provider_attempts,
                    trace=trace,
                )
            try:
                message = response.get("message")
                if not isinstance(message, Mapping):
                    raise ValueError("provider message must be an object")
                if message.get("role") not in {None, "assistant"}:
                    raise ValueError("provider message role must be assistant")
                if message.get("tool_calls") not in (None, []):
                    raise ValueError("R2 uses textual ReAct, not native tool calls")
                content = message.get("content")
                if not isinstance(content, str) or not content.strip():
                    raise ValueError("R2 planner must return textual ReAct content")
            except (TypeError, ValueError) as exc:
                raise R2AgentError(
                    f"R2 provider response is invalid: {exc}",
                    stage="provider_response",
                    provider_round=provider_round,
                    provider_request_attempts=provider_attempts,
                    trace=trace,
                ) from exc
            messages.append({"role": "assistant", "content": content})

            action: R2Action | None = None
            try:
                action = parse_r2_action(content)
            except R2ActionError as exc:
                invalid_actions += 1
                observation = format_r2_error_observation(exc)
                self._emit(
                    trace,
                    {
                        "event": "invalid_action",
                        "provider_round": provider_round,
                        "code": exc.code,
                        "assistant_content": content,
                    },
                )
                messages.append(
                    {"role": "user", "content": render_r2_observation(observation)}
                )
                continue

            event: dict[str, Any] = {
                "event": "action",
                "provider_round": provider_round,
                "thought": action.thought,
                "action": action.name,
                "arguments": dict(action.arguments),
            }
            if action.name == "search_chatrecord":
                searches += 1
                arguments = action.arguments
                last_search = self.index.search(
                    arguments["keywords"],
                    top_k=arguments["top_k"],
                    context_window=int(R2_PARAMETERS["context_window"]),
                    seen_sessions=seen_sessions,
                    date_from=arguments.get("date_from"),
                    date_to=arguments.get("date_to"),
                )
                seen_sessions.update(last_search.returned_sessions)
                last_observation_id = f"obs-{searches:04d}"
                observation = format_r2_search_observation(last_search)
                event.update(
                    {
                        "observation_id": last_observation_id,
                        "result_count": len(last_search.hits),
                        "returned_sessions": list(last_search.returned_sessions),
                        "query_terms": list(last_search.query_terms),
                    }
                )
            elif action.name == "take_note":
                note_actions += 1
                if last_search is None or last_observation_id is None:
                    observation = "Error [no_last_search]: take_note requires a prior search."
                    event.update({"saved": 0, "error": "no_last_search"})
                else:
                    indices = action.arguments["indices"]
                    if any(index > len(last_search.hits) for index in indices):
                        observation = (
                            "Error [invalid_indices]: an index exceeds the last result count."
                        )
                        event.update({"saved": 0, "error": "invalid_indices"})
                    else:
                        saved = 0
                        for index in indices:
                            hit = last_search.hits[index - 1]
                            if hit.anchor.exchange_id in noted_anchors:
                                continue
                            noted_anchors.add(hit.anchor.exchange_id)
                            notes.append(
                                R2SavedNote(
                                    observation_id=last_observation_id,
                                    hit=hit,
                                    retrieval_round=provider_round,
                                    query_terms=last_search.query_terms,
                                    selection_ordinal=len(notes) + 1,
                                )
                            )
                            saved += 1
                        observation = (
                            f"Saved {saved} new result(s). Total notes: {len(notes)}."
                        )
                        event.update({"saved": saved, "total_notes": len(notes)})
            else:
                finish_actions += 1
                reason = "evidence_sufficient" if notes else "no_relevant_evidence"
                stop = StopRecord(
                    reason=reason,
                    hit_cap=False,
                    missing_aspects=(),
                    rounds_without_new_evidence=0,
                    fallback_proof=None,
                )
                self._emit(trace, event)
                break

            self._emit(trace, event)
            messages.append(
                {"role": "user", "content": render_r2_observation(observation)}
            )

        if stop is None:
            stop = StopRecord(
                reason="round_limit",
                hit_cap=True,
                missing_aspects=(),
                rounds_without_new_evidence=0,
                fallback_proof=None,
            )
        return R2EpisodeOutcome(
            protocol_version=R2_AGENT_PROTOCOL_VERSION,
            episode_id=episode_id,
            cell_id=cell_id,
            store_id=expected_store,
            question=question,
            notes=tuple(notes),
            stop=stop,
            trace=tuple(trace),
            usage=tuple(usage),
            provider_rounds=len(usage),
            provider_request_attempts=provider_attempts,
            searches=searches,
            note_actions=note_actions,
            finish_actions=finish_actions,
            invalid_actions=invalid_actions,
            requested_model=self.requested_model,
            served_models=tuple(served_models),
            api_style=self.api_style,
        )
