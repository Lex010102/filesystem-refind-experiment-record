"""Dedicated evidence-only R1 Research Agent state machine.

This runner deliberately does not reuse the legacy direct-answer search loop.
It binds one online question to one verified store snapshot, exposes exactly the
four paper filesystem functions plus the two separately-counted project
orchestration actions, and terminates with host-validated evidence state.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any, Callable, Mapping, Protocol, Sequence

from .agent import (
    COMPACTION_SYSTEM_PROMPT,
    COMPACTION_USER_PREFIX,
    ChatProvider,
    TransientProviderError,
)
from .evidence import (
    EvidenceValidationError,
    QuestionInput,
    SourceCatalog,
    StopRecord,
    StoreSnapshotRef,
    VerifiedStoreManifest,
    canonical_json_bytes,
    sha256_bytes,
    validate_store_snapshot,
)
from .paper_config import (
    CONTEXT_COMPACTION_KEEP_ROUNDS,
    CONTEXT_COMPACTION_TRIGGER,
    SEARCH,
    RoleConfig,
)
from .r1_orchestration import (
    R1_ORCHESTRATION_ACTION_NAMES,
    R1_ROUND_LIMIT_BY_STORE,
    EvidenceNoteState,
    FinishSearchResolver,
    ObservationLedger,
    ProviderRoundLedger,
    R1OrchestrationError,
    TakeNoteResolution,
    TakeNoteResolver,
    r1_orchestration_action_schemas,
)
from .r1_prompts import (
    EVIDENCE_ONLY_USER_TEMPLATE,
    FROZEN_R1_PROMPT_SHA256,
    R1_PROMPT_PROFILES,
    verify_r1_prompts,
)
from .r1_tools import (
    R1_FILESYSTEM_TOOL_NAMES,
    R1ReadOnlyFilesystem,
    R1ToolError,
    r1_filesystem_tool_schemas,
)


R1_AGENT_PROTOCOL_VERSION = "r1-evidence-agent-v3"
R1_FREE_TEXT_CORRECTION_PROMPT = (
    "Protocol correction: the preceding response was not executed because "
    "evidence-only mode forbids assistant free text. Return only permitted "
    "tool calls with empty assistant content. Do not repeat, summarize, or "
    "answer the benchmark question in text."
)
R1_AGENT_LIMITS = MappingProxyType(
    {
        "max_tool_calls_per_response": 16,
        "max_tool_calls_per_episode": 320,
        "timeout_max_attempts": 3,
        "timeout_retry_backoff_seconds": (2, 4),
        "http_max_attempts": 5,
        "http_retry_backoff_seconds": (5, 15, 30, 60),
        "free_text_corrections_per_round": 1,
        "free_text_corrections_per_episode": 3,
        # Project-defined, condition-invariant emergency fuse.  This is not an
        # evidence budget and never clips file-view content.  It counts every
        # successful provider completion in the episode, including protocol
        # corrections and context compaction.
        "token_safety_fuse_unit": "provider_reported_total_tokens",
        "token_safety_fuse_limit": 1_000_000,
        "token_safety_fuse_scope": "per_episode_all_model_calls",
        "token_safety_fuse_requires_usage": True,
        "file_view_truncation": "none",
        "context_compaction_prompt_token_trigger": CONTEXT_COMPACTION_TRIGGER,
        "context_compaction_recent_rounds": CONTEXT_COMPACTION_KEEP_ROUNDS,
        "context_compaction_max_completion_tokens": 8192,
    }
)
FROZEN_R1_AGENT_LIMITS_SHA256 = (
    "ed5f6b5077da7406b5fa2919a3c8100f4379cde23939e661f4a8caf02281024a"
)
R1_TOOL_NAMES = (*R1_FILESYSTEM_TOOL_NAMES, *R1_ORCHESTRATION_ACTION_NAMES)


class EventSink(Protocol):
    def __call__(self, event: Mapping[str, Any]) -> None: ...


class R1AgentError(RuntimeError):
    """Safe episode failure with deterministic stage and partial audit state."""

    def __init__(
        self,
        message: str,
        *,
        stage: str,
        provider_round: int,
        provider_request_attempts: int,
        filesystem_tool_calls: int,
        orchestration_calls: int,
        trace: Sequence[Mapping[str, Any]],
    ) -> None:
        super().__init__(message)
        self.stage = stage
        self.provider_round = provider_round
        self.provider_request_attempts = provider_request_attempts
        self.filesystem_tool_calls = filesystem_tool_calls
        self.orchestration_calls = orchestration_calls
        self.trace = tuple(dict(item) for item in trace)


class _FreeTextWithValidToolCalls(ValueError):
    """A structurally valid tool response polluted by assistant prose."""


@dataclass(frozen=True)
class R1EpisodeOutcome:
    protocol_version: str
    episode_id: str
    cell_id: str
    store_id: str
    question: QuestionInput
    store_snapshot: StoreSnapshotRef
    observations: ObservationLedger
    notes: EvidenceNoteState
    rounds: ProviderRoundLedger
    stop: StopRecord
    trace: tuple[Mapping[str, Any], ...]
    usage: tuple[Mapping[str, Any], ...]
    provider_request_attempts: int
    model_calls: int
    compaction_calls: int
    protocol_correction_calls: int
    filesystem_tool_calls: int
    orchestration_calls: int
    requested_model: str
    served_models: tuple[str, ...]

    def __post_init__(self) -> None:
        if self.protocol_version != R1_AGENT_PROTOCOL_VERSION:
            raise EvidenceValidationError("R1 episode protocol version mismatch")
        if self.cell_id not in R1_PROMPT_PROFILES:
            raise EvidenceValidationError("R1 episode cell is invalid")
        profile = R1_PROMPT_PROFILES[self.cell_id]
        if self.store_id.casefold() != profile.store_id.casefold():
            raise EvidenceValidationError("R1 episode cell/store mapping differs")
        if self.store_snapshot.store_id != self.store_id.casefold():
            raise EvidenceValidationError("R1 episode snapshot store differs")
        if self.question.sha256 != self.observations.question_sha256:
            raise EvidenceValidationError("R1 episode question identity differs")
        if self.observations.episode_id != self.episode_id:
            raise EvidenceValidationError("R1 episode observation identity differs")
        if self.notes != self.rounds.note_state:
            raise EvidenceValidationError("R1 episode note state differs from rounds")
        if self.rounds.rounds_completed > profile.hard_round_cap:
            raise EvidenceValidationError("R1 episode exceeds its round cap")
        if self.stop.reason == "round_limit":
            if self.rounds.rounds_completed != profile.hard_round_cap:
                raise EvidenceValidationError("R1 cap stop occurred before the cap")
        if not isinstance(self.trace, (list, tuple)) or not isinstance(
            self.usage, (list, tuple)
        ):
            raise EvidenceValidationError("R1 episode arrays must be ordered")
        if not self.requested_model.strip() or not self.served_models:
            raise EvidenceValidationError("R1 episode model identity is incomplete")
        for value in (
            self.provider_request_attempts,
            self.model_calls,
            self.compaction_calls,
            self.protocol_correction_calls,
            self.filesystem_tool_calls,
            self.orchestration_calls,
        ):
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise EvidenceValidationError("R1 episode metric is invalid")
        if self.provider_request_attempts < self.rounds.rounds_completed:
            raise EvidenceValidationError("R1 provider attempts are undercounted")
        if self.model_calls != (
            self.rounds.rounds_completed
            + self.compaction_calls
            + self.protocol_correction_calls
        ):
            raise EvidenceValidationError("R1 model-call count is inconsistent")
        if self.provider_request_attempts < self.model_calls:
            raise EvidenceValidationError("R1 provider attempts are below model calls")
        object.__setattr__(
            self, "trace", tuple(MappingProxyType(dict(x)) for x in self.trace)
        )
        object.__setattr__(
            self, "usage", tuple(MappingProxyType(dict(x)) for x in self.usage)
        )
        object.__setattr__(self, "served_models", tuple(self.served_models))


def r1_agent_limits_sha256() -> str:
    return sha256_bytes(canonical_json_bytes(R1_AGENT_LIMITS))


def verify_r1_agent_limits() -> None:
    if r1_agent_limits_sha256() != FROZEN_R1_AGENT_LIMITS_SHA256:
        raise EvidenceValidationError(
            "Reviewed R1 agent limits changed without a hash update"
        )


def r1_agent_tool_schemas() -> list[dict[str, Any]]:
    """Return paper tools followed by separately-defined orchestration actions."""
    tools = [*r1_filesystem_tool_schemas(), *r1_orchestration_action_schemas()]
    names = tuple(item["function"]["name"] for item in tools)
    if names != R1_TOOL_NAMES:
        raise EvidenceValidationError("R1 provider tool order changed")
    return tools


def _safe_usage(value: Any) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise R1AgentError(
            "Provider usage must be a JSON object",
            stage="provider_response",
            provider_round=0,
            provider_request_attempts=0,
            filesystem_tool_calls=0,
            orchestration_calls=0,
            trace=(),
        )
    plain = json.loads(canonical_json_bytes(value))
    for key in ("prompt_tokens", "completion_tokens", "total_tokens"):
        if key in plain and (
            isinstance(plain[key], bool)
            or not isinstance(plain[key], int)
            or plain[key] < 0
        ):
            raise ValueError(f"Provider usage {key} must be a nonnegative integer")
    token_keys = {"prompt_tokens", "completion_tokens", "total_tokens"}
    present = token_keys & set(plain)
    if present and present != token_keys:
        raise ValueError("Provider usage token totals must be complete or absent")
    if present and plain["total_tokens"] != (
        plain["prompt_tokens"] + plain["completion_tokens"]
    ):
        raise ValueError("Provider usage token total is inconsistent")
    if R1_AGENT_LIMITS["token_safety_fuse_requires_usage"] and present != token_keys:
        raise ValueError(
            "Provider usage token totals are required by the token safety fuse"
        )
    return plain


def _parse_tool_calls(message: Mapping[str, Any]) -> tuple[dict[str, Any], ...]:
    if not isinstance(message, Mapping):
        raise ValueError("Provider message must be an object")
    if message.get("role") not in {None, "assistant"}:
        raise ValueError("Provider message role must be assistant")
    content = message.get("content")
    raw_calls = message.get("tool_calls")
    if not isinstance(raw_calls, list) or not raw_calls:
        raise ValueError("Evidence-only assistant response must contain tool calls")
    if len(raw_calls) > R1_AGENT_LIMITS["max_tool_calls_per_response"]:
        raise ValueError("Assistant response exceeds the tool-call limit")
    calls: list[dict[str, Any]] = []
    ids: set[str] = set()
    for raw in raw_calls:
        if not isinstance(raw, Mapping) or set(raw) != {"id", "type", "function"}:
            raise ValueError("Tool call has an invalid wrapper")
        call_id = raw["id"]
        if (
            not isinstance(call_id, str)
            or not call_id
            or call_id in ids
            or len(call_id) > 256
        ):
            raise ValueError("Tool call ID is invalid or duplicated")
        ids.add(call_id)
        if raw["type"] != "function" or not isinstance(raw["function"], Mapping):
            raise ValueError("Tool call must use the function wrapper")
        function = raw["function"]
        if set(function) != {"name", "arguments"}:
            raise ValueError("Tool function wrapper has invalid fields")
        name = function["name"]
        encoded = function["arguments"]
        if not isinstance(name, str) or name not in R1_TOOL_NAMES:
            raise ValueError("Assistant requested an unavailable R1 tool")
        if not isinstance(encoded, str):
            raise ValueError("Tool arguments must be a JSON string")
        try:
            arguments = json.loads(encoded)
        except json.JSONDecodeError:
            arguments = None
        calls.append(
            {
                "id": call_id,
                "type": "function",
                "function": {"name": name, "arguments": encoded},
                "parsed_arguments": arguments,
            }
        )
    names = {call["function"]["name"] for call in calls}
    if names <= set(R1_FILESYSTEM_TOOL_NAMES):
        mode = "filesystem"
    elif names == {"take_note"}:
        mode = "note"
    elif names == {"finish_search"} and len(calls) == 1:
        mode = "finish"
    else:
        raise ValueError("Assistant response mixes incompatible R1 action modes")
    for call in calls:
        call["mode"] = mode
    if content not in (None, ""):
        if not isinstance(content, str):
            raise ValueError("Assistant content must be null, empty, or text")
        raise _FreeTextWithValidToolCalls(
            "Evidence-only assistant responses cannot contain free text"
        )
    return tuple(calls)


class R1ResearchAgent:
    """Run one isolated evidence-only retrieval episode."""

    def __init__(
        self,
        *,
        root: Path,
        catalog: SourceCatalog,
        verified_manifest: VerifiedStoreManifest,
        snapshot: StoreSnapshotRef,
        provider: ChatProvider,
        requested_model: str,
        budget_unit: str,
        budget_limit: int,
        event_sink: Callable[[Mapping[str, Any]], None] | None = None,
        sleeper: Callable[[float], None] = time.sleep,
        private_checkpoint_path: Path | None = None,
    ) -> None:
        verify_r1_prompts()
        verify_r1_agent_limits()
        validate_store_snapshot(
            snapshot,
            root=root,
            catalog=catalog,
            verified_manifest=verified_manifest,
        )
        if not isinstance(requested_model, str) or not requested_model.strip():
            raise ValueError("requested_model must be a nonempty string")
        if budget_unit not in {"bytes", "characters"}:
            raise ValueError("budget_unit must be bytes or characters")
        if (
            isinstance(budget_limit, bool)
            or not isinstance(budget_limit, int)
            or budget_limit < 0
        ):
            raise ValueError("budget_limit must be a nonnegative integer")
        self._root = Path(root)
        self._catalog = catalog
        self._manifest = verified_manifest
        self._snapshot = snapshot
        self._provider = provider
        self._requested_model = requested_model
        self._budget_unit = budget_unit
        self._budget_limit = budget_limit
        self._event_sink = event_sink
        self._sleeper = sleeper
        self._private_checkpoint_path = (
            Path(private_checkpoint_path)
            if private_checkpoint_path is not None
            else None
        )
        self._filesystem = R1ReadOnlyFilesystem(
            root=root,
            catalog=catalog,
            verified_manifest=verified_manifest,
            snapshot=snapshot,
        )

    def _emit(self, trace: list[dict[str, Any]], event: Mapping[str, Any]) -> None:
        detached = json.loads(canonical_json_bytes(event))
        trace.append(detached)
        if self._event_sink is not None:
            self._event_sink(MappingProxyType(detached))

    @staticmethod
    def _tool_message(call_id: str, name: str, payload: Mapping[str, Any]) -> dict:
        return {
            "role": "tool",
            "tool_call_id": call_id,
            "name": name,
            "content": canonical_json_bytes(payload).decode("utf-8"),
        }

    def _fail(
        self,
        message: str,
        *,
        stage: str,
        provider_round: int,
        attempts: int,
        filesystem_calls: int,
        orchestration_calls: int,
        trace: Sequence[Mapping[str, Any]],
    ) -> R1AgentError:
        return R1AgentError(
            message,
            stage=stage,
            provider_round=provider_round,
            provider_request_attempts=attempts,
            filesystem_tool_calls=filesystem_calls,
            orchestration_calls=orchestration_calls,
            trace=trace,
        )

    def _record_token_usage(
        self,
        *,
        trace: list[dict[str, Any]],
        usage_rows: list[dict[str, Any]],
        stored_usage: Mapping[str, Any],
        request_kind: str,
        provider_round: int,
        attempts: int,
        filesystem_calls: int,
        orchestration_calls: int,
    ) -> None:
        """Record one complete provider usage row and enforce the shared fuse.

        The completed response is already billable when this runs.  If its
        cumulative usage reaches the fuse, none of that response's proposed
        actions are executed and no further provider request is made.
        """
        row = json.loads(canonical_json_bytes(stored_usage))
        for key in ("prompt_tokens", "completion_tokens", "total_tokens"):
            value = row.get(key)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise self._fail(
                    "Provider usage is unavailable for the token safety fuse",
                    stage="token_usage_unavailable",
                    provider_round=provider_round,
                    attempts=attempts,
                    filesystem_calls=filesystem_calls,
                    orchestration_calls=orchestration_calls,
                    trace=trace,
                )
        usage_rows.append(row)
        cumulative = {
            key: sum(item[key] for item in usage_rows)
            for key in ("prompt_tokens", "completion_tokens", "total_tokens")
        }
        limit = R1_AGENT_LIMITS["token_safety_fuse_limit"]
        self._emit(
            trace,
            {
                "kind": "token_usage_checkpoint",
                "request_kind": request_kind,
                "provider_round": provider_round,
                "usage": {
                    key: row[key]
                    for key in ("prompt_tokens", "completion_tokens", "total_tokens")
                },
                "cumulative_usage": cumulative,
                "fuse_unit": R1_AGENT_LIMITS["token_safety_fuse_unit"],
                "fuse_limit": limit,
                "fuse_reached": cumulative["total_tokens"] >= limit,
            },
        )
        if cumulative["total_tokens"] >= limit:
            self._emit(
                trace,
                {
                    "kind": "token_safety_fuse_triggered",
                    "request_kind": request_kind,
                    "provider_round": provider_round,
                    "cumulative_usage": cumulative,
                    "fuse_unit": R1_AGENT_LIMITS["token_safety_fuse_unit"],
                    "fuse_limit": limit,
                    "file_view_content_clipped": False,
                    "response_actions_executed": False,
                },
            )
            raise self._fail(
                "Episode reached the shared provider-token safety fuse; "
                "the triggering response was recorded but its actions were not executed",
                stage="token_safety_fuse",
                provider_round=provider_round,
                attempts=attempts,
                filesystem_calls=filesystem_calls,
                orchestration_calls=orchestration_calls,
                trace=trace,
            )

    def _complete_with_retry(
        self,
        *,
        messages: list[dict],
        tools: list[dict],
        config: RoleConfig,
        provider_round: int,
        trace: list[dict[str, Any]],
        prior_attempts: int,
        filesystem_calls: int,
        orchestration_calls: int,
        request_kind: str = "research",
    ) -> tuple[dict[str, Any], int]:
        local_attempt = 0
        while True:
            local_attempt += 1
            total_attempt = prior_attempts + local_attempt
            try:
                result = self._provider.complete(messages, tools, config)
                if not isinstance(result, dict):
                    raise TypeError("Provider response must be a JSON object")
                return result, total_attempt
            except TransientProviderError as exc:
                if exc.kind == "http":
                    maximum = R1_AGENT_LIMITS["http_max_attempts"]
                    backoff = R1_AGENT_LIMITS["http_retry_backoff_seconds"]
                else:
                    maximum = R1_AGENT_LIMITS["timeout_max_attempts"]
                    backoff = R1_AGENT_LIMITS["timeout_retry_backoff_seconds"]
                will_retry = local_attempt < maximum
                delay = backoff[local_attempt - 1] if will_retry else 0
                self._emit(
                    trace,
                    {
                        "kind": "provider_retry",
                        "request_kind": request_kind,
                        "provider_round": provider_round,
                        "attempt_in_request": local_attempt,
                        "provider_request_attempt": total_attempt,
                        "error_kind": exc.kind,
                        "http_status": exc.http_status,
                        "will_retry": will_retry,
                        "delay_seconds": delay,
                    },
                )
                if not will_retry:
                    raise self._fail(
                        "Provider request exhausted the frozen retry policy",
                        stage="provider",
                        provider_round=provider_round,
                        attempts=total_attempt,
                        filesystem_calls=filesystem_calls,
                        orchestration_calls=orchestration_calls,
                        trace=trace,
                    ) from exc
                self._sleeper(delay)
            except R1AgentError:
                raise
            except Exception as exc:
                raise self._fail(
                    "Provider request failed before returning a complete response",
                    stage="provider",
                    provider_round=provider_round,
                    attempts=total_attempt,
                    filesystem_calls=filesystem_calls,
                    orchestration_calls=orchestration_calls,
                    trace=trace,
                ) from exc

    def run(self, *, cell_id: str, question: QuestionInput) -> R1EpisodeOutcome:
        if cell_id not in R1_PROMPT_PROFILES:
            raise ValueError("R1 cell_id must be E1, E3, or E5")
        profile = R1_PROMPT_PROFILES[cell_id]
        store_id = self._snapshot.store_id
        if profile.store_id.casefold() != store_id:
            raise ValueError("R1 cell does not match the mounted store")
        if question.conversation_id != self._snapshot.conversation_id:
            raise ValueError("Question and mounted store conversation differ")
        cap = R1_ROUND_LIMIT_BY_STORE[store_id]
        if cap != profile.hard_round_cap:
            raise EvidenceValidationError("Prompt and orchestration round caps differ")
        config = RoleConfig(
            model=SEARCH.model,
            reasoning_effort=SEARCH.reasoning_effort,
            max_completion_tokens=SEARCH.max_completion_tokens,
            max_rounds=cap,
        )
        tools = r1_agent_tool_schemas()
        user_text = EVIDENCE_ONLY_USER_TEMPLATE.format(question=question.question)
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": profile.derived_prompt},
            {"role": "user", "content": user_text},
        ]
        observations = ObservationLedger.start(
            question_sha256=question.sha256,
            snapshot=self._snapshot,
        )
        if self._private_checkpoint_path is not None:
            observations.write_private_checkpoint(self._private_checkpoint_path)
        notes = EvidenceNoteState.start(
            question_sha256=question.sha256,
            snapshot=self._snapshot,
            budget_unit=self._budget_unit,
            budget_limit=self._budget_limit,
        )
        note_resolver = TakeNoteResolver(
            root=self._root,
            catalog=self._catalog,
            verified_manifest=self._manifest,
            snapshot=self._snapshot,
            question_sha256=question.sha256,
        )
        finish_resolver = FinishSearchResolver(
            root=self._root,
            catalog=self._catalog,
            verified_manifest=self._manifest,
            snapshot=self._snapshot,
            question_sha256=question.sha256,
        )
        rounds = ProviderRoundLedger.start(observations=observations, notes=notes)
        trace: list[dict[str, Any]] = []
        usage: list[dict[str, Any]] = []
        served_models: list[str] = []
        attempts = 0
        filesystem_calls = 0
        orchestration_calls = 0
        model_calls = 0
        compaction_calls = 0
        protocol_correction_calls = 0
        action_ordinal = 0
        round_starts: list[int] = []

        self._emit(
            trace,
            {
                "kind": "episode_started",
                "episode_id": observations.episode_id,
                "cell_id": cell_id,
                "store_id": store_id,
                "question_sha256": question.sha256,
                "derived_prompt_sha256": FROZEN_R1_PROMPT_SHA256[
                    f"derived_prompt_{profile.paper_prompt_number}"
                ],
                "round_limit": cap,
                "budget_unit": self._budget_unit,
                "budget_limit": self._budget_limit,
                "token_safety_fuse_unit": R1_AGENT_LIMITS["token_safety_fuse_unit"],
                "token_safety_fuse_limit": R1_AGENT_LIMITS["token_safety_fuse_limit"],
                "token_safety_fuse_scope": R1_AGENT_LIMITS["token_safety_fuse_scope"],
                "file_view_truncation": R1_AGENT_LIMITS["file_view_truncation"],
            },
        )

        stop: StopRecord | None = None
        for round_number in range(1, cap + 1):
            round_starts.append(len(messages))
            corrections_this_round = 0
            while True:
                result, attempts = self._complete_with_retry(
                    messages=messages,
                    tools=tools,
                    config=config,
                    provider_round=round_number,
                    trace=trace,
                    prior_attempts=attempts,
                    filesystem_calls=filesystem_calls,
                    orchestration_calls=orchestration_calls,
                )
                model_calls += 1
                round_usage: dict[str, Any] | None = None
                served = result.get("served_model")
                try:
                    round_usage = _safe_usage(result.get("usage", {}))
                    if not isinstance(served, str) or not served.strip():
                        raise ValueError(
                            "Provider response lacks a served model identity"
                        )
                    message = result["message"]
                    calls = _parse_tool_calls(message)
                except _FreeTextWithValidToolCalls as exc:
                    can_retry = (
                        corrections_this_round
                        < R1_AGENT_LIMITS["free_text_corrections_per_round"]
                        and protocol_correction_calls
                        < R1_AGENT_LIMITS["free_text_corrections_per_episode"]
                    )
                    self._emit(
                        trace,
                        {
                            "kind": "provider_response_rejected",
                            "provider_round": round_number,
                            "provider_request_attempts_total": attempts,
                            "served_model": served,
                            "usage": round_usage,
                            "error_type": type(exc).__name__,
                            "error_code": "free_text_with_valid_tool_calls",
                            "correction_will_retry": can_retry,
                        },
                    )
                    if not can_retry:
                        raise self._fail(
                            str(exc),
                            stage="provider_response",
                            provider_round=round_number,
                            attempts=attempts,
                            filesystem_calls=filesystem_calls,
                            orchestration_calls=orchestration_calls,
                            trace=trace,
                        ) from exc
                    self._record_token_usage(
                        trace=trace,
                        usage_rows=usage,
                        stored_usage={
                            "protocol_correction_rejected": True,
                            **round_usage,
                        },
                        request_kind="protocol_correction_rejected",
                        provider_round=round_number,
                        attempts=attempts,
                        filesystem_calls=filesystem_calls,
                        orchestration_calls=orchestration_calls,
                    )
                    served_models.append(served)
                    corrections_this_round += 1
                    protocol_correction_calls += 1
                    messages.append(
                        {"role": "user", "content": R1_FREE_TEXT_CORRECTION_PROMPT}
                    )
                    self._emit(
                        trace,
                        {
                            "kind": "protocol_correction_requested",
                            "provider_round": round_number,
                            "correction_in_round": corrections_this_round,
                            "corrections_in_episode": protocol_correction_calls,
                            "prompt_sha256": sha256_bytes(
                                R1_FREE_TEXT_CORRECTION_PROMPT.encode("utf-8")
                            ),
                        },
                    )
                    continue
                except Exception as exc:
                    self._emit(
                        trace,
                        {
                            "kind": "provider_response_rejected",
                            "provider_round": round_number,
                            "provider_request_attempts_total": attempts,
                            "served_model": (
                                served
                                if isinstance(served, str) and served.strip()
                                else None
                            ),
                            "usage": round_usage,
                            "error_type": type(exc).__name__,
                        },
                    )
                    raise self._fail(
                        str(exc),
                        stage="provider_response",
                        provider_round=round_number,
                        attempts=attempts,
                        filesystem_calls=filesystem_calls,
                        orchestration_calls=orchestration_calls,
                        trace=trace,
                    ) from exc
                break
            if (
                action_ordinal + len(calls)
                > R1_AGENT_LIMITS["max_tool_calls_per_episode"]
            ):
                raise self._fail(
                    "Episode exceeds the frozen tool-call limit",
                    stage="provider_response",
                    provider_round=round_number,
                    attempts=attempts,
                    filesystem_calls=filesystem_calls,
                    orchestration_calls=orchestration_calls,
                    trace=trace,
                )
            served_models.append(served)
            self._emit(
                trace,
                {
                    "kind": "provider_response",
                    "provider_round": round_number,
                    "provider_request_attempts_total": attempts,
                    "finish_reason": result.get("finish_reason"),
                    "response_id": result.get("response_id"),
                    "system_fingerprint": result.get("system_fingerprint"),
                    "served_model": served,
                    "usage": round_usage,
                    "tool_call_count": len(calls),
                    "mode": calls[0]["mode"],
                    "protocol_corrections_before_accept": corrections_this_round,
                },
            )
            self._record_token_usage(
                trace=trace,
                usage_rows=usage,
                stored_usage=round_usage,
                request_kind="research",
                provider_round=round_number,
                attempts=attempts,
                filesystem_calls=filesystem_calls,
                orchestration_calls=orchestration_calls,
            )
            assistant_wire = {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": call["id"],
                        "type": "function",
                        "function": dict(call["function"]),
                    }
                    for call in calls
                ],
            }
            messages.append(assistant_wire)
            mode = calls[0]["mode"]
            resolutions: list[TakeNoteResolution] = []
            pending_finish: Mapping[str, Any] | None = None
            for call in calls:
                action_ordinal += 1
                name = call["function"]["name"]
                arguments = call["parsed_arguments"]
                if mode == "filesystem":
                    filesystem_calls += 1
                    if not isinstance(arguments, Mapping):
                        payload = {
                            "ok": False,
                            "error": {
                                "code": "invalid_json",
                                "message": "Tool arguments must decode to a JSON object",
                            },
                        }
                    else:
                        try:
                            observations, observation = observations.execute_and_append(
                                filesystem=self._filesystem,
                                tool_name=name,
                                arguments=arguments,
                                provider_round=round_number,
                                action_ordinal=action_ordinal,
                            )
                            payload = {
                                "ok": True,
                                "observation_id": observation.observation_id,
                                "tool_name": name,
                                "content": observation.result.content,
                                "coverage": [
                                    item.to_dict()
                                    for item in observation.result.coverage
                                ],
                                "truncated": observation.result.truncated,
                                "result_count": observation.result.result_count,
                                "root_survey": observation.result.root_survey,
                                "whole_tree_grep": observation.result.whole_tree_grep,
                            }
                            self._emit(
                                trace,
                                {
                                    "kind": "filesystem_observation",
                                    **observation.to_dict(),
                                },
                            )
                        except R1ToolError as exc:
                            payload = {
                                "ok": False,
                                "error": {"code": exc.code, "message": str(exc)},
                            }
                    messages.append(self._tool_message(call["id"], name, payload))
                elif mode == "note":
                    orchestration_calls += 1
                    if not isinstance(arguments, Mapping):
                        payload = {
                            "ok": False,
                            "error": {
                                "code": "invalid_json",
                                "message": "Tool arguments must decode to a JSON object",
                            },
                        }
                    else:
                        try:
                            resolution = note_resolver.resolve(
                                ledger=observations,
                                state=notes,
                                arguments=arguments,
                                current_round=round_number,
                            )
                            notes = resolution.state
                            resolutions.append(resolution)
                            payload = {
                                "ok": True,
                                "status": resolution.status,
                                "evidence_id": resolution.evidence_id,
                                "replaced_evidence_ids": list(
                                    resolution.replaced_evidence_ids
                                ),
                                "budget_used": notes.budget_used,
                                "budget_limit": notes.budget_limit,
                            }
                            self._emit(
                                trace,
                                {
                                    "kind": "take_note_resolution",
                                    "action_ordinal": action_ordinal,
                                    **resolution.to_dict(),
                                },
                            )
                        except R1OrchestrationError as exc:
                            payload = {
                                "ok": False,
                                "error": {"code": exc.code, "message": str(exc)},
                            }
                    messages.append(self._tool_message(call["id"], name, payload))
                else:
                    orchestration_calls += 1
                    pending_finish = arguments

                if mode != "finish":
                    completed_payload = json.loads(messages[-1]["content"])
                    self._emit(
                        trace,
                        {
                            "kind": "action_completed",
                            "provider_round": round_number,
                            "action_ordinal": action_ordinal,
                            "tool_call_id": call["id"],
                            "tool_name": name,
                            "mode": mode,
                            "arguments": (
                                dict(arguments)
                                if isinstance(arguments, Mapping)
                                else None
                            ),
                            "arguments_wire_sha256": sha256_bytes(
                                call["function"]["arguments"].encode("utf-8")
                            ),
                            "ok": bool(completed_payload["ok"]),
                            "error_code": (
                                completed_payload.get("error", {}).get("code")
                                if not completed_payload["ok"]
                                else None
                            ),
                        },
                    )

            rounds = rounds.close_round(
                round_number=round_number,
                resolutions=resolutions,
                observations=observations,
                resolver=note_resolver,
            )
            notes = rounds.note_state
            self._emit(
                trace,
                {
                    "kind": "provider_round_closed",
                    "provider_round": round_number,
                    "mode": mode,
                    "round_sha256": rounds.records[-1].round_sha256,
                    "observation_count": len(observations.observations),
                    "evidence_count": len(notes.evidence_items),
                },
            )

            if mode == "finish":
                if not isinstance(pending_finish, Mapping):
                    payload = {
                        "ok": False,
                        "error": {
                            "code": "invalid_json",
                            "message": "Tool arguments must decode to a JSON object",
                        },
                    }
                    messages.append(
                        self._tool_message(calls[0]["id"], "finish_search", payload)
                    )
                    self._emit(
                        trace,
                        {
                            "kind": "finish_search_rejected",
                            "provider_round": round_number,
                            "action_ordinal": action_ordinal,
                            "error_code": "invalid_json",
                        },
                    )
                else:
                    try:
                        stop = finish_resolver.model_finish(
                            arguments=pending_finish,
                            observations=observations,
                            notes=notes,
                            rounds=rounds,
                        )
                    except R1OrchestrationError as exc:
                        messages.append(
                            self._tool_message(
                                calls[0]["id"],
                                "finish_search",
                                {
                                    "ok": False,
                                    "error": {
                                        "code": exc.code,
                                        "message": str(exc),
                                    },
                                },
                            )
                        )
                        self._emit(
                            trace,
                            {
                                "kind": "finish_search_rejected",
                                "provider_round": round_number,
                                "action_ordinal": action_ordinal,
                                "error_code": exc.code,
                            },
                        )
                    else:
                        self._emit(
                            trace,
                            {
                                "kind": "finish_search_accepted",
                                "provider_round": round_number,
                                "stop": stop.to_dict(),
                            },
                        )
                        break

            if round_number == cap:
                stop = finish_resolver.host_round_limit(
                    observations=observations,
                    notes=notes,
                    rounds=rounds,
                )
                self._emit(
                    trace,
                    {
                        "kind": "host_round_limit",
                        "provider_round": round_number,
                        "stop": stop.to_dict(),
                    },
                )

            prompt_tokens = round_usage.get("prompt_tokens")
            should_compact = (
                stop is None
                and round_number < cap
                and isinstance(prompt_tokens, int)
                and prompt_tokens > CONTEXT_COMPACTION_TRIGGER
                and len(round_starts) > CONTEXT_COMPACTION_KEEP_ROUNDS
            )
            if should_compact:
                keep_start = round_starts[-CONTEXT_COMPACTION_KEEP_ROUNDS]
                older_messages = messages[2:keep_start]
                compaction_input = canonical_json_bytes(older_messages).decode("utf-8")
                compact_config = RoleConfig(
                    model=SEARCH.model,
                    reasoning_effort=SEARCH.reasoning_effort,
                    max_completion_tokens=R1_AGENT_LIMITS[
                        "context_compaction_max_completion_tokens"
                    ],
                    max_rounds=1,
                )
                compact_result, attempts = self._complete_with_retry(
                    messages=[
                        {"role": "system", "content": COMPACTION_SYSTEM_PROMPT},
                        {"role": "user", "content": compaction_input},
                    ],
                    tools=[],
                    config=compact_config,
                    provider_round=round_number,
                    trace=trace,
                    prior_attempts=attempts,
                    filesystem_calls=filesystem_calls,
                    orchestration_calls=orchestration_calls,
                    request_kind="compaction",
                )
                model_calls += 1
                compaction_calls += 1
                compact_usage: dict[str, Any] | None = None
                compact_served = compact_result.get("served_model")
                try:
                    compact_message = compact_result["message"]
                    summary = compact_message.get("content")
                    if (
                        not isinstance(compact_message, Mapping)
                        or compact_message.get("role") not in {None, "assistant"}
                        or not isinstance(summary, str)
                        or not summary.strip()
                        or compact_message.get("tool_calls")
                        or compact_result.get("finish_reason") != "stop"
                    ):
                        raise ValueError(
                            "Context compaction did not return clean summary text"
                        )
                    compact_usage = _safe_usage(compact_result.get("usage", {}))
                    if (
                        not isinstance(compact_served, str)
                        or not compact_served.strip()
                    ):
                        raise ValueError(
                            "Context compaction lacks served model identity"
                        )
                except Exception as exc:
                    self._emit(
                        trace,
                        {
                            "kind": "context_compaction_rejected",
                            "after_provider_round": round_number,
                            "provider_request_attempts_total": attempts,
                            "served_model": (
                                compact_served
                                if isinstance(compact_served, str)
                                and compact_served.strip()
                                else None
                            ),
                            "usage": compact_usage,
                            "error_type": type(exc).__name__,
                        },
                    )
                    raise self._fail(
                        str(exc),
                        stage="compaction_response",
                        provider_round=round_number,
                        attempts=attempts,
                        filesystem_calls=filesystem_calls,
                        orchestration_calls=orchestration_calls,
                        trace=trace,
                    ) from exc
                served_models.append(compact_served)
                self._emit(
                    trace,
                    {
                        "kind": "context_compaction",
                        "after_provider_round": round_number,
                        "dropped_messages": len(older_messages),
                        "kept_rounds": CONTEXT_COMPACTION_KEEP_ROUNDS,
                        "input_sha256": sha256_bytes(compaction_input.encode("utf-8")),
                        "summary": summary,
                        "summary_sha256": sha256_bytes(summary.encode("utf-8")),
                        "served_model": compact_served,
                        "response_id": compact_result.get("response_id"),
                        "system_fingerprint": compact_result.get("system_fingerprint"),
                        "usage": compact_usage,
                    },
                )
                self._record_token_usage(
                    trace=trace,
                    usage_rows=usage,
                    stored_usage={"compaction": True, **compact_usage},
                    request_kind="compaction",
                    provider_round=round_number,
                    attempts=attempts,
                    filesystem_calls=filesystem_calls,
                    orchestration_calls=orchestration_calls,
                )
                messages = (
                    messages[:2]
                    + [{"role": "user", "content": COMPACTION_USER_PREFIX + summary}]
                    + messages[keep_start:]
                )
                round_starts = [
                    start - keep_start + 3
                    for start in round_starts[-CONTEXT_COMPACTION_KEEP_ROUNDS:]
                ]

        if stop is None:  # pragma: no cover - cap branch is exhaustive
            raise EvidenceValidationError("R1 episode ended without a stop record")
        validate_store_snapshot(
            self._snapshot,
            root=self._root,
            catalog=self._catalog,
            verified_manifest=self._manifest,
        )
        outcome = R1EpisodeOutcome(
            protocol_version=R1_AGENT_PROTOCOL_VERSION,
            episode_id=observations.episode_id,
            cell_id=cell_id,
            store_id=store_id,
            question=question,
            store_snapshot=self._snapshot,
            observations=observations,
            notes=notes,
            rounds=rounds,
            stop=stop,
            trace=tuple(trace),
            usage=tuple(usage),
            provider_request_attempts=attempts,
            model_calls=model_calls,
            compaction_calls=compaction_calls,
            protocol_correction_calls=protocol_correction_calls,
            filesystem_tool_calls=filesystem_calls,
            orchestration_calls=orchestration_calls,
            requested_model=self._requested_model,
            served_models=tuple(dict.fromkeys(served_models)),
        )
        return outcome
