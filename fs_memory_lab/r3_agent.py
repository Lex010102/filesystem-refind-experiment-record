"""Four-action textual ReAct agent for R3 curated evidence collection."""

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
from .r3_index import R3CuratedIndex, R3SearchHit, R3SearchResult
from .r3_prompts import (
    R3_DERIVED_SYSTEM_PROMPT,
    render_r3_observation,
    render_r3_user_prompt,
    verify_r3_prompts,
)
from .r3_protocol import R3_PARAMETERS, R3_RUNTIME_LIMITS, verify_r3_protocol
from .r3_tools import (
    R3Action,
    R3ActionError,
    format_r3_error_observation,
    format_r3_search_observation,
    parse_r3_action,
    verify_r3_action_contract,
)


R3_AGENT_PROTOCOL_VERSION = "r3-curated-agent-v2-empty-content-repair"


@dataclass(frozen=True)
class R3PlannerConfig:
    model: str
    reasoning_effort: str
    max_completion_tokens: int
    max_rounds: int
    temperature: int


class R3AgentError(RuntimeError):
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


class _R3ProviderFailure(RuntimeError):
    def __init__(self, message: str, *, attempts: int) -> None:
        super().__init__(message)
        self.attempts = attempts


@dataclass(frozen=True)
class R3SavedNote:
    observation_id: str
    hit: R3SearchHit
    retrieval_round: int
    query_terms: tuple[str, ...]
    selection_ordinal: int


@dataclass(frozen=True)
class R3EpisodeOutcome:
    protocol_version: str
    episode_id: str
    cell_id: str
    store_id: str
    question: QuestionInput
    notes: tuple[R3SavedNote, ...]
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
        if self.protocol_version != R3_AGENT_PROTOCOL_VERSION:
            raise EvidenceValidationError("R3 episode protocol version differs")
        if self.cell_id != "E6" or self.store_id != "s3":
            raise EvidenceValidationError("R3 episode must map exactly to E6/S3")
        if self.api_style not in {"paper", "portable"}:
            raise EvidenceValidationError("R3 episode API style is invalid")
        if self.provider_rounds > int(R3_PARAMETERS["agent_action_cap"]):
            raise EvidenceValidationError("R3 episode exceeds the four-action cap")
        if self.stop.reason == "round_limit" and self.provider_rounds != int(
            R3_PARAMETERS["agent_action_cap"]
        ):
            raise EvidenceValidationError("R3 cap stop occurred before action four")
        if self.stop.reason == "evidence_sufficient" and not self.notes:
            raise EvidenceValidationError("R3 sufficient stop requires saved notes")
        if self.stop.reason == "no_relevant_evidence" and self.notes:
            raise EvidenceValidationError("R3 no-evidence stop cannot contain notes")
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


class R3RetrievalAgent:
    def __init__(
        self,
        *,
        index: R3CuratedIndex,
        provider: ChatProvider,
        requested_model: str,
        api_style: str = "portable",
        sleeper: Callable[[float], None] = time.sleep,
        event_sink: Callable[[Mapping[str, Any]], None] | None = None,
    ) -> None:
        verify_r3_protocol()
        verify_r3_prompts()
        verify_r3_action_contract()
        if not isinstance(requested_model, str) or not requested_model.strip():
            raise EvidenceValidationError("R3 requested_model must be nonempty")
        if api_style not in {"paper", "portable"}:
            raise EvidenceValidationError("R3 api_style must be paper or portable")
        self.index = index
        self.provider = provider
        self.requested_model = requested_model
        self.api_style = api_style
        self.sleeper = sleeper
        self.event_sink = event_sink
        self.config = R3PlannerConfig(
            requested_model,
            "high",
            int(R3_PARAMETERS["stage1_max_completion_tokens"]),
            int(R3_PARAMETERS["agent_action_cap"]),
            int(R3_PARAMETERS["temperature"]),
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
                    maximum = int(R3_RUNTIME_LIMITS["http_max_attempts"])
                    backoff = tuple(R3_RUNTIME_LIMITS["http_retry_backoff_seconds"])
                else:
                    maximum = int(R3_RUNTIME_LIMITS["timeout_max_attempts"])
                    backoff = tuple(R3_RUNTIME_LIMITS["timeout_retry_backoff_seconds"])
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
                    raise _R3ProviderFailure(str(exc), attempts=attempts) from exc
                self.sleeper(float(backoff[attempts - 1]))
            except Exception as exc:
                raise _R3ProviderFailure(str(exc), attempts=attempts) from exc

    def run(self, *, cell_id: str, question: QuestionInput) -> R3EpisodeOutcome:
        if cell_id != "E6" or self.index.corpus.store.snapshot.store_id != "s3":
            raise EvidenceValidationError("R3 cell and loaded store must be E6/S3")
        if question.conversation_id != self.index.corpus.store.snapshot.conversation_id:
            raise EvidenceValidationError("R3 question and corpus conversation differ")
        episode_id = f"r3-e6-{question.question_id}"
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": R3_DERIVED_SYSTEM_PROMPT},
            {"role": "user", "content": render_r3_user_prompt(question.question)},
        ]
        trace: list[dict[str, Any]] = []
        usage: list[dict[str, Any]] = []
        notes: list[R3SavedNote] = []
        noted_anchors: set[str] = set()
        seen_groups: set[str] = set()
        last_search: R3SearchResult | None = None
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
                "protocol_version": R3_AGENT_PROTOCOL_VERSION,
                "cell_id": "E6",
                "store_id": "s3",
                "snapshot_tree_sha256": self.index.corpus.store.snapshot.tree_sha256,
                "corpus_sha256": self.index.corpus.corpus_sha256,
                "requested_model": self.requested_model,
                "api_style": self.api_style,
                "paper_target": {
                    "reasoning_effort": self.config.reasoning_effort,
                    "temperature": self.config.temperature,
                    "max_completion_tokens": self.config.max_completion_tokens,
                },
                "actual_wire_profile": {
                    "reasoning_effort": (
                        self.config.reasoning_effort if self.api_style == "paper" else None
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

        action_cap = int(R3_PARAMETERS["agent_action_cap"])
        for provider_round in range(1, action_cap + 1):
            try:
                response, attempts = self._complete(messages, trace=trace)
            except _R3ProviderFailure as exc:
                raise R3AgentError(
                    f"R3 provider request failed: {exc}",
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
                raise R3AgentError(
                    f"R3 provider response is invalid: {exc}",
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
            if token_total > int(R3_RUNTIME_LIMITS["token_safety_fuse_limit"]):
                raise R3AgentError(
                    "R3 provider token safety fuse exceeded",
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
                    raise ValueError("R3 uses textual ReAct, not native tool calls")
                content = message.get("content")
                if content is not None and not isinstance(content, str):
                    raise ValueError("R3 planner content must be text or null")
            except (TypeError, ValueError) as exc:
                raise R3AgentError(
                    f"R3 provider response is invalid: {exc}",
                    stage="provider_response",
                    provider_round=provider_round,
                    provider_request_attempts=provider_attempts,
                    trace=trace,
                ) from exc
            content = content or ""
            if not content.strip():
                invalid_actions += 1
                observation = (
                    "Error [empty_content]: the previous response contained no textual "
                    "ReAct action. Return exactly Thought, Action, and Action Input."
                )
                self._emit(
                    trace,
                    {
                        "event": "invalid_action",
                        "provider_round": provider_round,
                        "code": "empty_content",
                        "assistant_content": "",
                    },
                )
                messages.append(
                    {"role": "user", "content": render_r3_observation(observation)}
                )
                continue
            messages.append({"role": "assistant", "content": content})

            action: R3Action | None = None
            try:
                action = parse_r3_action(content)
            except R3ActionError as exc:
                invalid_actions += 1
                observation = format_r3_error_observation(exc)
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
                    {"role": "user", "content": render_r3_observation(observation)}
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
                try:
                    last_search = self.index.search(
                        arguments["keywords"],
                        top_k=arguments["top_k"],
                        context_window=int(R3_PARAMETERS["context_window"]),
                        seen_groups=seen_groups,
                        date_from=arguments.get("date_from"),
                        date_to=arguments.get("date_to"),
                    )
                    observation = format_r3_search_observation(last_search)
                except EvidenceValidationError as exc:
                    raise R3AgentError(
                        f"R3 search action failed: {exc}",
                        stage="action_execution",
                        provider_round=provider_round,
                        provider_request_attempts=provider_attempts,
                        trace=trace,
                    ) from exc
                seen_groups.update(last_search.returned_groups)
                last_observation_id = f"obs-{searches:04d}"
                event.update(
                    {
                        "observation_id": last_observation_id,
                        "result_count": len(last_search.hits),
                        "returned_groups": list(last_search.returned_groups),
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
                        for result_index in indices:
                            hit = last_search.hits[result_index - 1]
                            if hit.anchor.unit_id in noted_anchors:
                                continue
                            noted_anchors.add(hit.anchor.unit_id)
                            notes.append(
                                R3SavedNote(
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
                {"role": "user", "content": render_r3_observation(observation)}
            )

        if stop is None:
            stop = StopRecord(
                reason="round_limit",
                hit_cap=True,
                missing_aspects=(),
                rounds_without_new_evidence=0,
                fallback_proof=None,
            )
        return R3EpisodeOutcome(
            protocol_version=R3_AGENT_PROTOCOL_VERSION,
            episode_id=episode_id,
            cell_id="E6",
            store_id="s3",
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
