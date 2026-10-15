"""Fail-closed, sanitized preflight support for the Model 2 deployment.

This module is deliberately separate from the frozen Qwen formal-v1 runner.  It
can inspect the OpenAI-compatible ``/models`` endpoint and issue small protocol
smokes, but it never writes credentials, prompts, questions, or model output to
an artifact.  Callers obtain credentials through :class:`CompatibleChatProvider`
so a Keychain launcher only needs to inject the existing ``FSMEM_*`` variables.
"""

from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass, is_dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping, Sequence

from .agent import (
    COMPACTION_SUMMARY_MAX_COMPLETION_TOKENS,
    COMPACTION_SUMMARY_MAX_ROUNDS,
    COMPACTION_SYSTEM_PROMPT,
    ChatProvider,
    CompatibleChatProvider,
)
from .answerer import (
    ANSWERER_SYSTEM_PROMPT,
    AnswererConfig,
    _parse_answer_payload,
)
from .evidence import EvidenceValidationError, canonical_json_bytes, sha256_bytes
from .paper_config import SEARCH, RoleConfig
from .r1_agent import _parse_tool_calls, r1_agent_tool_schemas
from .r1_orchestration import MISSING_ASPECT_LABELS, MODEL_FINISH_REASONS
from .r1_prompts import EVIDENCE_ONLY_USER_TEMPLATE, R1_PROMPT_PROFILES
from .r2_agent import R2PlannerConfig
from .r2_prompts import (
    R2_DERIVED_SYSTEM_PROMPT,
    render_r2_observation,
    render_r2_user_prompt,
)
from .r2_protocol import R2_PARAMETERS
from .r2_tools import parse_r2_action
from .r3_agent import R3PlannerConfig
from .r3_prompts import (
    R3_DERIVED_SYSTEM_PROMPT,
    render_r3_observation,
    render_r3_user_prompt,
)
from .r3_protocol import R3_PARAMETERS
from .r3_tools import parse_r3_action


MODEL2_PREFLIGHT_PROTOCOL_VERSION = "model2-x-test2-preflight-v1"
MODEL2_REQUESTED_ALIAS = "x-test-2"
MODEL2_EXPECTED_SERVED_MODEL = "deepseek-v4.1-flash"
MODEL2_API_STYLE = "portable"
MODEL2_BASE_URL = "https://soclaas-api.comp.nus.edu.sg/v1"
MODEL2_CHAT_ENDPOINT = MODEL2_BASE_URL + "/chat/completions"
MODEL2_MODELS_ENDPOINT = MODEL2_BASE_URL + "/models"
MODEL2_CONTEXT_LIMIT = 1_048_576
MODEL2_ROLE_ORDER = ("r1", "r1_compaction", "r2", "r3", "answerer")

_USAGE_KEYS = ("prompt_tokens", "completion_tokens", "total_tokens")
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_MODEL_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/-]{0,255}\Z")
_SAFE_RESPONSE_METADATA = re.compile(r"[A-Za-z0-9._:/-]{0,256}\Z")
_FINISH_REASON = re.compile(r"[a-z_][a-z0-9_-]{0,63}\Z")
_SYNTHETIC_QUESTION = "Which city is named in the supplied memory?"
_SYNTHETIC_EVIDENCE_ID = "ev-" + "0" * 64
_SYNTHETIC_EVIDENCE_TEXT = "The supplied memory names Kyoto."


class Model2PreflightError(EvidenceValidationError):
    """A preflight contract failure whose message is safe to show to a user."""


class Model2IdentityError(Model2PreflightError):
    """A missing or drifting requested/served model identity."""


def _nonempty(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise Model2PreflightError(f"{label} must be nonempty text")
    return value.strip()


def _model_id(value: Any, label: str) -> str:
    parsed = _nonempty(value, label)
    if _MODEL_ID.fullmatch(parsed) is None:
        raise Model2PreflightError(f"{label} is not a safe model identifier")
    return parsed


def _safe_usage(value: Any) -> Mapping[str, int]:
    if not isinstance(value, Mapping):
        raise Model2PreflightError("Provider usage must be an object")
    parsed: dict[str, int] = {}
    for key in _USAGE_KEYS:
        number = value.get(key)
        if isinstance(number, bool) or not isinstance(number, int) or number < 0:
            raise Model2PreflightError(
                "Provider usage requires nonnegative prompt/completion/total tokens"
            )
        parsed[key] = number
    if parsed["total_tokens"] != (
        parsed["prompt_tokens"] + parsed["completion_tokens"]
    ):
        raise Model2PreflightError("Provider total token usage is inconsistent")
    # Discard vendor-specific usage fields so artifacts cannot accidentally copy
    # arbitrary response data.
    return MappingProxyType(parsed)


def _models_endpoint(provider: CompatibleChatProvider) -> str:
    suffix = "/chat/completions"
    if not provider.endpoint.endswith(suffix):
        raise Model2PreflightError("Provider chat endpoint has an unexpected shape")
    return provider.endpoint[: -len(suffix)] + "/models"


def load_model2_provider_from_environment() -> CompatibleChatProvider:
    """Load the existing environment-only provider and enforce Model 2 wiring.

    A launcher may populate ``FSMEM_API_KEY`` from macOS Keychain.  This function
    does not invoke Keychain, echo environment values, or include credentials in
    any returned report.
    """

    provider = CompatibleChatProvider.from_environment()
    if provider.endpoint != MODEL2_CHAT_ENDPOINT:
        raise Model2PreflightError(
            "Model 2 preflight requires the frozen SoCLaaS /v1 endpoint"
        )
    if provider.model != MODEL2_REQUESTED_ALIAS:
        raise Model2IdentityError(
            "FSMEM_MODEL must equal the frozen Model 2 requested alias"
        )
    if provider.api_style != MODEL2_API_STYLE:
        raise Model2PreflightError(
            "Model 2 preflight requires FSMEM_API_STYLE=portable"
        )
    return provider


@dataclass(frozen=True)
class ModelCatalogCheck:
    requested_alias: str
    endpoint: str
    advertised_model_ids: tuple[str, ...]
    alias_context_limits: Mapping[str, int]

    def __post_init__(self) -> None:
        if self.requested_alias != MODEL2_REQUESTED_ALIAS:
            raise Model2IdentityError("Model catalog check used the wrong alias")
        if self.endpoint != MODEL2_MODELS_ENDPOINT:
            raise Model2PreflightError("Model catalog check used the wrong endpoint")
        if (
            not self.advertised_model_ids
            or len(self.advertised_model_ids) != len(set(self.advertised_model_ids))
            or any(
                not isinstance(item, str) or _MODEL_ID.fullmatch(item) is None
                for item in self.advertised_model_ids
            )
        ):
            raise Model2PreflightError("Model catalog contains invalid model IDs")
        if self.requested_alias not in self.advertised_model_ids:
            raise Model2IdentityError(
                "SoCLaaS /v1/models does not advertise the Model 2 alias"
            )
        allowed_context_fields = {
            "context_length",
            "max_context_length",
            "max_model_len",
        }
        if not isinstance(self.alias_context_limits, Mapping):
            raise Model2PreflightError("Model catalog context metadata is invalid")
        limits = dict(self.alias_context_limits)
        if not limits or not set(limits) <= allowed_context_fields:
            raise Model2PreflightError(
                "Model catalog lacks whitelisted x-test-2 context metadata"
            )
        for value in limits.values():
            if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                raise Model2PreflightError("Model catalog context limit is invalid")
        if set(limits.values()) != {MODEL2_CONTEXT_LIMIT}:
            raise Model2PreflightError(
                "Model catalog context limit differs from the confirmed deployment"
            )
        object.__setattr__(self, "alias_context_limits", MappingProxyType(limits))

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "artifact_type": "model2-models-check",
            "protocol_version": MODEL2_PREFLIGHT_PROTOCOL_VERSION,
            "status": "passed",
            "requested_alias": self.requested_alias,
            "endpoint": self.endpoint,
            "alias_present": True,
            "advertised_model_count": len(self.advertised_model_ids),
            "advertised_model_ids": list(self.advertised_model_ids),
            "alias_context_limits": dict(self.alias_context_limits),
        }


def check_model2_alias(
    provider: CompatibleChatProvider,
    *,
    opener: Any = urllib.request.urlopen,
) -> ModelCatalogCheck:
    """GET ``/v1/models`` and require an exact ``x-test-2`` ID.

    The provider owns the already-loaded credential.  It is used only while
    constructing the request header and is never copied into an exception,
    receipt, or artifact.
    """

    endpoint = _models_endpoint(provider)
    if endpoint != MODEL2_MODELS_ENDPOINT:
        raise Model2PreflightError("Refusing to probe a non-SoCLaaS models endpoint")
    request = urllib.request.Request(
        endpoint,
        headers={
            "Authorization": "Bearer " + provider.api_key,
            "Accept": "application/json",
        },
        method="GET",
    )
    try:
        with opener(request, timeout=provider.timeout) as response:
            raw = response.read(provider.max_response_bytes + 1)
    except urllib.error.HTTPError as exc:
        raise Model2PreflightError(
            f"SoCLaaS models endpoint returned HTTP {exc.code}"
        ) from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise Model2PreflightError("Cannot reach the SoCLaaS models endpoint") from exc
    if len(raw) > provider.max_response_bytes:
        raise Model2PreflightError("Models response exceeded the configured byte limit")
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise Model2PreflightError("Models endpoint did not return valid JSON") from exc
    data = payload.get("data") if isinstance(payload, Mapping) else None
    if not isinstance(data, list):
        raise Model2PreflightError("Models response lacks a data array")
    identifiers: list[str] = []
    alias_entry: Mapping[str, Any] | None = None
    for item in data:
        identifier = item.get("id") if isinstance(item, Mapping) else None
        if not isinstance(identifier, str) or not identifier.strip():
            raise Model2PreflightError("Models response contains an invalid model entry")
        if identifier not in identifiers:
            identifiers.append(identifier)
        if identifier == MODEL2_REQUESTED_ALIAS:
            alias_entry = item
    context_limits: dict[str, int] = {}
    if alias_entry is not None:
        for field in ("context_length", "max_context_length", "max_model_len"):
            if field in alias_entry:
                value = alias_entry[field]
                if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                    raise Model2PreflightError(
                        "x-test-2 context metadata is not a positive integer"
                    )
                context_limits[field] = value
    return ModelCatalogCheck(
        requested_alias=MODEL2_REQUESTED_ALIAS,
        endpoint=endpoint,
        advertised_model_ids=tuple(identifiers),
        alias_context_limits=context_limits,
    )


@dataclass(frozen=True)
class ModelResponseReceipt:
    component: str
    call_index: int
    requested_alias: str
    served_model: str
    usage: Mapping[str, int]
    finish_reason: str
    response_id: str | None
    system_fingerprint: str | None

    def __post_init__(self) -> None:
        if self.component not in MODEL2_ROLE_ORDER:
            raise Model2PreflightError("Receipt component is invalid")
        if (
            isinstance(self.call_index, bool)
            or not isinstance(self.call_index, int)
            or self.call_index < 1
        ):
            raise Model2PreflightError("Receipt call index is invalid")
        if self.requested_alias != MODEL2_REQUESTED_ALIAS:
            raise Model2IdentityError("Receipt requested alias differs")
        _model_id(self.served_model, "served_model")
        object.__setattr__(self, "usage", _safe_usage(self.usage))
        if (
            not isinstance(self.finish_reason, str)
            or _FINISH_REASON.fullmatch(self.finish_reason) is None
        ):
            raise Model2PreflightError("Receipt finish_reason is invalid")
        for value, label in (
            (self.response_id, "response_id"),
            (self.system_fingerprint, "system_fingerprint"),
        ):
            if value is not None and (
                not isinstance(value, str)
                or _SAFE_RESPONSE_METADATA.fullmatch(value) is None
            ):
                raise Model2PreflightError(
                    f"Receipt {label} is not safe response metadata"
                )

    def to_dict(self) -> dict[str, Any]:
        return {
            "component": self.component,
            "call_index": self.call_index,
            "requested_alias": self.requested_alias,
            "served_model": self.served_model,
            "usage": dict(self.usage),
            "finish_reason": self.finish_reason,
            "response_id": self.response_id,
            "system_fingerprint": self.system_fingerprint,
        }


class Model2IdentityCheckingProvider:
    """Check alias, served model, and usage before consumers see a response."""

    def __init__(
        self,
        *,
        provider: ChatProvider,
        component: str,
        expected_served_model: str,
        requested_alias: str = MODEL2_REQUESTED_ALIAS,
    ) -> None:
        if component not in MODEL2_ROLE_ORDER:
            raise Model2PreflightError("Identity gate component is invalid")
        if requested_alias != MODEL2_REQUESTED_ALIAS:
            raise Model2IdentityError("Identity gate requested alias differs")
        self.provider = provider
        self.component = component
        self.requested_alias = requested_alias
        self.expected_served_model = _model_id(
            expected_served_model, "expected_served_model"
        )
        upstream_model = getattr(provider, "model", None)
        if upstream_model not in (None, requested_alias):
            raise Model2IdentityError("Upstream provider is configured for another alias")
        self._upstream_model = upstream_model
        upstream_style = getattr(provider, "api_style", None)
        if upstream_style not in (None, MODEL2_API_STYLE):
            raise Model2PreflightError("Upstream provider is not using portable API style")
        self._receipts: list[ModelResponseReceipt] = []

    @property
    def receipts(self) -> tuple[ModelResponseReceipt, ...]:
        return tuple(self._receipts)

    def complete(self, messages: list[dict], tools: list[dict], config: Any) -> dict:
        configured_model = getattr(config, "model", None)
        # CompatibleChatProvider gives its explicit ``model`` precedence over the
        # paper RoleConfig model.  R1 and compaction intentionally retain the
        # frozen paper config (gpt-5.4-mini), while the wire request is x-test-2.
        # If the upstream has no override, the config itself must carry x-test-2.
        if self._upstream_model is None and configured_model != self.requested_alias:
            raise Model2IdentityError("Request config does not use the Model 2 alias")
        response = self.provider.complete(messages, tools, config)
        if not isinstance(response, Mapping):
            raise Model2PreflightError("Provider response must be an object")
        served_model = response.get("served_model")
        if not isinstance(served_model, str) or not served_model.strip():
            raise Model2IdentityError("Provider response lacks served_model")
        if served_model != self.expected_served_model:
            raise Model2IdentityError("Provider served model differs from the frozen identity")
        usage = _safe_usage(response.get("usage"))
        finish_reason = response.get("finish_reason")
        if (
            not isinstance(finish_reason, str)
            or _FINISH_REASON.fullmatch(finish_reason) is None
        ):
            raise Model2PreflightError("Provider response lacks finish_reason")
        response_id = response.get("response_id")
        fingerprint = response.get("system_fingerprint")
        for value, label in (
            (response_id, "response_id"),
            (fingerprint, "system_fingerprint"),
        ):
            if value is not None and (
                not isinstance(value, str)
                or _SAFE_RESPONSE_METADATA.fullmatch(value) is None
            ):
                raise Model2PreflightError(
                    f"Provider {label} is not safe response metadata"
                )
        receipt = ModelResponseReceipt(
            component=self.component,
            call_index=len(self._receipts) + 1,
            requested_alias=self.requested_alias,
            served_model=served_model,
            usage=usage,
            finish_reason=finish_reason,
            response_id=response_id,
            system_fingerprint=fingerprint,
        )
        self._receipts.append(receipt)
        return dict(response)


def _config_dict(config: Any) -> dict[str, Any]:
    if is_dataclass(config):
        return asdict(config)
    values = getattr(config, "__dict__", None)
    if not isinstance(values, dict):
        raise Model2PreflightError("Smoke config is not serializable")
    return dict(values)


def _request_sha256(
    messages: Sequence[Mapping[str, Any]], tools: Sequence[Mapping[str, Any]], config: Any
) -> str:
    return sha256_bytes(
        canonical_json_bytes(
            {
                "messages": list(messages),
                "tools": list(tools),
                "config": _config_dict(config),
            }
        )
    )


def _message(response: Mapping[str, Any]) -> Mapping[str, Any]:
    message = response.get("message")
    if not isinstance(message, Mapping):
        raise Model2PreflightError("Provider response message is invalid")
    if message.get("role") not in (None, "assistant"):
        raise Model2PreflightError("Provider response role is not assistant")
    return message


@dataclass(frozen=True)
class RoleSmokeResult:
    component: str
    request_sha256: str
    system_prompt_sha256: str
    receipt: ModelResponseReceipt
    checks: Mapping[str, Any]
    additional_receipts: tuple[ModelResponseReceipt, ...] = ()
    additional_request_sha256s: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if (
            self.component not in MODEL2_ROLE_ORDER
            or self.receipt.component != self.component
            or self.receipt.call_index != 1
        ):
            raise Model2PreflightError("Role smoke component differs")
        for value, label in (
            (self.request_sha256, "request_sha256"),
            (self.system_prompt_sha256, "system_prompt_sha256"),
        ):
            if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
                raise Model2PreflightError(f"Role smoke {label} is invalid")
        parsed_checks = dict(self.checks)
        _validate_smoke_checks(self.component, parsed_checks)
        object.__setattr__(self, "checks", MappingProxyType(parsed_checks))
        receipts = tuple(self.additional_receipts)
        request_hashes = tuple(self.additional_request_sha256s)
        if len(receipts) != len(request_hashes):
            raise Model2PreflightError("Additional receipt/request counts differ")
        expected_additional = 2 if self.component == "r1" else 0
        if len(receipts) != expected_additional:
            raise Model2PreflightError("Role smoke response count differs")
        for offset, (receipt, request_hash) in enumerate(
            zip(receipts, request_hashes, strict=True), start=2
        ):
            if receipt.component != self.component or receipt.call_index != offset:
                raise Model2PreflightError("Additional receipt sequence differs")
            if not isinstance(request_hash, str) or _SHA256.fullmatch(request_hash) is None:
                raise Model2PreflightError("Additional request hash is invalid")
        object.__setattr__(self, "additional_receipts", receipts)
        object.__setattr__(self, "additional_request_sha256s", request_hashes)

    @property
    def receipts(self) -> tuple[ModelResponseReceipt, ...]:
        return (self.receipt, *self.additional_receipts)

    def to_dict(self) -> dict[str, Any]:
        return {
            "component": self.component,
            "status": "passed",
            "request_sha256": self.request_sha256,
            "system_prompt_sha256": self.system_prompt_sha256,
            "receipt": self.receipt.to_dict(),
            "additional_receipts": [
                item.to_dict() for item in self.additional_receipts
            ],
            "additional_request_sha256s": list(self.additional_request_sha256s),
            "checks": dict(self.checks),
        }


def _validate_smoke_checks(component: str, checks: Mapping[str, Any]) -> None:
    """Whitelist every persisted check field and value."""

    if component == "r1":
        if set(checks) != {
            "native_tool_calls",
            "tool_choice_auto_profile",
            "tool_call_count",
            "single_tool_mode",
            "json_arguments",
            "take_note_wire_compatibility",
            "finish_search_wire_compatibility",
        }:
            raise Model2PreflightError("R1 smoke check fields differ")
        if any(
            checks[key] is not True
            for key in (
                "native_tool_calls",
                "tool_choice_auto_profile",
                "json_arguments",
                "take_note_wire_compatibility",
                "finish_search_wire_compatibility",
            )
        ):
            raise Model2PreflightError("R1 smoke checks did not pass")
        count = checks["tool_call_count"]
        if isinstance(count, bool) or not isinstance(count, int) or count < 1:
            raise Model2PreflightError("R1 smoke tool-call count is invalid")
        if checks["single_tool_mode"] not in {"filesystem", "note", "finish"}:
            raise Model2PreflightError("R1 smoke tool mode is invalid")
        return
    if component == "r1_compaction":
        if set(checks) != {"plain_text", "no_tool_calls", "finish_stop"} or any(
            value is not True for value in checks.values()
        ):
            raise Model2PreflightError("R1 compaction smoke checks differ")
        return
    if component in {"r2", "r3"}:
        if set(checks) != {
            "textual_react",
            "no_native_tool_calls",
            "action",
            "action_input_json",
            "synthetic_stop_turn",
        }:
            raise Model2PreflightError("Textual retrieval smoke check fields differ")
        if any(
            checks[key] is not True
            for key in (
                "textual_react",
                "no_native_tool_calls",
                "action_input_json",
                "synthetic_stop_turn",
            )
        ):
            raise Model2PreflightError("Textual retrieval smoke checks did not pass")
        if checks["action"] not in {
            "search_chatrecord",
            "take_note",
            "finish_search",
        }:
            raise Model2PreflightError("Textual retrieval smoke action is invalid")
        return
    if component == "answerer":
        if set(checks) != {
            "exact_json",
            "no_tool_calls",
            "citation_subset",
            "citation_count",
        }:
            raise Model2PreflightError("Answerer smoke check fields differ")
        if any(
            checks[key] is not True
            for key in ("exact_json", "no_tool_calls", "citation_subset")
        ):
            raise Model2PreflightError("Answerer smoke checks did not pass")
        count = checks["citation_count"]
        if isinstance(count, bool) or not isinstance(count, int) or count < 0:
            raise Model2PreflightError("Answerer citation count is invalid")
        return
    raise Model2PreflightError("Unknown smoke check component")


def _call_smoke(
    *,
    provider: ChatProvider,
    component: str,
    expected_served_model: str,
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]],
    config: Any,
    identity_gate: Model2IdentityCheckingProvider | None = None,
) -> tuple[Mapping[str, Any], ModelResponseReceipt, str, str]:
    gate = identity_gate or Model2IdentityCheckingProvider(
        provider=provider,
        component=component,
        expected_served_model=expected_served_model,
    )
    if gate.component != component or gate.expected_served_model != expected_served_model:
        raise Model2PreflightError("Smoke identity gate differs from call contract")
    prior_receipts = len(gate.receipts)
    response = gate.complete(messages, tools, config)
    if len(gate.receipts) != prior_receipts + 1:
        raise Model2PreflightError("Smoke call must produce exactly one response receipt")
    system_prompt = messages[0].get("content") if messages else None
    if not isinstance(system_prompt, str):
        raise Model2PreflightError("Smoke system prompt is invalid")
    return (
        response,
        gate.receipts[-1],
        _request_sha256(messages, tools, config),
        sha256_bytes(system_prompt.encode("utf-8")),
    )


def _answerer_user_prompt() -> str:
    return "\n".join(
        (
            "Question:",
            _SYNTHETIC_QUESTION,
            "",
            "Evidence:",
            "",
            f"[{_SYNTHETIC_EVIDENCE_ID}]",
            "Source: RAW",
            "Timestamp: 2026-01-01",
            "Locators: [S1T1]",
            "Text:",
            _SYNTHETIC_EVIDENCE_TEXT,
            "",
            "Return the required JSON object now. Citation values must be evidence_id values above.",
        )
    )


def run_model2_role_smokes(
    provider: ChatProvider,
    *,
    expected_served_model: str = MODEL2_EXPECTED_SERVED_MODEL,
) -> tuple[RoleSmokeResult, ...]:
    """Run five synthetic, one-response smokes with frozen protocol material."""

    results: list[RoleSmokeResult] = []

    r1_messages = [
        {"role": "system", "content": R1_PROMPT_PROFILES["E1"].derived_prompt},
        {
            "role": "user",
            "content": EVIDENCE_ONLY_USER_TEMPLATE.format(question=_SYNTHETIC_QUESTION),
        },
    ]
    r1_tools = r1_agent_tool_schemas()
    r1_config = RoleConfig(
        SEARCH.model,
        SEARCH.reasoning_effort,
        SEARCH.max_completion_tokens,
        R1_PROMPT_PROFILES["E1"].hard_round_cap,
    )
    r1_gate = Model2IdentityCheckingProvider(
        provider=provider,
        component="r1",
        expected_served_model=expected_served_model,
    )
    response, receipt, request_hash, prompt_hash = _call_smoke(
        provider=provider,
        component="r1",
        expected_served_model=expected_served_model,
        messages=r1_messages,
        tools=r1_tools,
        config=r1_config,
        identity_gate=r1_gate,
    )
    calls = _parse_tool_calls(_message(response))
    if any(not isinstance(call.get("parsed_arguments"), dict) for call in calls):
        raise Model2PreflightError("R1 tool arguments are not JSON objects")
    modes = {str(call["mode"]) for call in calls}
    if modes != {"filesystem"}:
        raise Model2PreflightError(
            "R1 first-response smoke did not return one filesystem tool mode"
        )

    synthetic_view_call = {
        "id": "preflight-view",
        "type": "function",
        "function": {
            "name": "view",
            "arguments": json.dumps(
                {
                    "path": "/memories/preflight.md",
                    "start_line": 1,
                    "end_line": 1,
                },
                separators=(",", ":"),
            ),
        },
    }
    synthetic_view_result = {
        "ok": True,
        "observation_id": "obs-0001",
        "tool_name": "view",
        "content": (
            "1: The stored memory names Kyoto. [S1T1]\n"
            "2: Protocol-smoke host note: this observation fully covers the "
            "single-part question. In the next response use only take_note for "
            "the exact observed source line; do not search again."
        ),
        "coverage": [
            {
                "path": "/memories/preflight.md",
                "line_start": 1,
                "line_end": 1,
            }
        ],
        "truncated": False,
        "result_count": 1,
        "root_survey": False,
        "whole_tree_grep": False,
    }
    r1_note_messages = [
        *r1_messages,
        {"role": "assistant", "content": None, "tool_calls": [synthetic_view_call]},
        {
            "role": "tool",
            "tool_call_id": "preflight-view",
            "name": "view",
            "content": canonical_json_bytes(synthetic_view_result).decode("utf-8"),
        },
    ]
    note_response, note_receipt, note_request_hash, _ = _call_smoke(
        provider=provider,
        component="r1",
        expected_served_model=expected_served_model,
        messages=r1_note_messages,
        tools=r1_tools,
        config=r1_config,
        identity_gate=r1_gate,
    )
    note_calls = _parse_tool_calls(_message(note_response))
    note_modes = {str(call["mode"]) for call in note_calls}
    if note_modes != {"note"} or any(
        not isinstance(call.get("parsed_arguments"), dict) for call in note_calls
    ):
        raise Model2PreflightError(
            "R1 take_note wire smoke failed; observed safe modes="
            + ",".join(sorted(note_modes))
        )
    for call in note_calls:
        arguments = call["parsed_arguments"]
        if (
            set(arguments)
            != {"observation_ids", "path", "line_start", "line_end"}
            or not isinstance(arguments["observation_ids"], list)
            or not arguments["observation_ids"]
            or not isinstance(arguments["path"], str)
            or isinstance(arguments["line_start"], bool)
            or not isinstance(arguments["line_start"], int)
            or isinstance(arguments["line_end"], bool)
            or not isinstance(arguments["line_end"], int)
        ):
            raise Model2PreflightError("R1 take_note arguments differ from the schema")

    synthetic_note_call = {
        "id": "preflight-note",
        "type": "function",
        "function": {
            "name": "take_note",
            "arguments": json.dumps(
                {
                    "observation_ids": ["obs-0001"],
                    "path": "/memories/preflight.md",
                    "line_start": 1,
                    "line_end": 1,
                },
                separators=(",", ":"),
            ),
        },
    }
    synthetic_note_result = {
        "ok": True,
        "status": "accepted",
        "evidence_id": _SYNTHETIC_EVIDENCE_ID,
        "replaced_evidence_ids": [],
        "budget_used": len(_SYNTHETIC_EVIDENCE_TEXT),
        "budget_limit": 16_000,
        "protocol_smoke_instruction": (
            "The accepted note covers every aspect. In the next response use only "
            "finish_search with reason evidence_sufficient."
        ),
    }
    r1_finish_messages = [
        *r1_note_messages,
        {"role": "assistant", "content": None, "tool_calls": [synthetic_note_call]},
        {
            "role": "tool",
            "tool_call_id": "preflight-note",
            "name": "take_note",
            "content": canonical_json_bytes(synthetic_note_result).decode("utf-8"),
        },
    ]
    finish_response, finish_receipt, finish_request_hash, _ = _call_smoke(
        provider=provider,
        component="r1",
        expected_served_model=expected_served_model,
        messages=r1_finish_messages,
        tools=r1_tools,
        config=r1_config,
        identity_gate=r1_gate,
    )
    finish_calls = _parse_tool_calls(_message(finish_response))
    if (
        len(finish_calls) != 1
        or finish_calls[0]["mode"] != "finish"
        or not isinstance(finish_calls[0].get("parsed_arguments"), dict)
    ):
        raise Model2PreflightError("R1 finish_search wire smoke failed")
    finish_arguments = finish_calls[0]["parsed_arguments"]
    if (
        set(finish_arguments) != {"reason", "missing_aspects"}
        or finish_arguments["reason"] not in MODEL_FINISH_REASONS
        or not isinstance(finish_arguments["missing_aspects"], list)
        or any(
            item not in MISSING_ASPECT_LABELS
            for item in finish_arguments["missing_aspects"]
        )
        or (
            finish_arguments["reason"] == "evidence_sufficient"
            and bool(finish_arguments["missing_aspects"])
        )
        or (
            finish_arguments["reason"] != "evidence_sufficient"
            and not finish_arguments["missing_aspects"]
        )
    ):
        raise Model2PreflightError("R1 finish_search arguments differ from the schema")
    results.append(
        RoleSmokeResult(
            component="r1",
            request_sha256=request_hash,
            system_prompt_sha256=prompt_hash,
            receipt=receipt,
            checks={
                "native_tool_calls": True,
                "tool_choice_auto_profile": True,
                "tool_call_count": len(calls),
                "single_tool_mode": next(iter(modes)),
                "json_arguments": True,
                "take_note_wire_compatibility": True,
                "finish_search_wire_compatibility": True,
            },
            additional_receipts=(note_receipt, finish_receipt),
            additional_request_sha256s=(note_request_hash, finish_request_hash),
        )
    )

    compact_messages = [
        {"role": "system", "content": COMPACTION_SYSTEM_PROMPT},
        {
            "role": "user",
            "content": "A prior tool observation named Kyoto; preserve that fact.",
        },
    ]
    compact_config = RoleConfig(
        SEARCH.model,
        SEARCH.reasoning_effort,
        COMPACTION_SUMMARY_MAX_COMPLETION_TOKENS,
        COMPACTION_SUMMARY_MAX_ROUNDS,
    )
    response, receipt, request_hash, prompt_hash = _call_smoke(
        provider=provider,
        component="r1_compaction",
        expected_served_model=expected_served_model,
        messages=compact_messages,
        tools=[],
        config=compact_config,
    )
    compact_message = _message(response)
    compact_content = compact_message.get("content")
    if (
        not isinstance(compact_content, str)
        or not compact_content.strip()
        or compact_message.get("tool_calls") not in (None, [])
        or receipt.finish_reason != "stop"
    ):
        raise Model2PreflightError("R1 compaction did not return clean plain text")
    results.append(
        RoleSmokeResult(
            component="r1_compaction",
            request_sha256=request_hash,
            system_prompt_sha256=prompt_hash,
            receipt=receipt,
            checks={"plain_text": True, "no_tool_calls": True, "finish_stop": True},
        )
    )

    for component, system_prompt, user_prompt, observation_renderer, config, parser in (
        (
            "r2",
            R2_DERIVED_SYSTEM_PROMPT,
            render_r2_user_prompt(_SYNTHETIC_QUESTION),
            render_r2_observation,
            R2PlannerConfig(
                MODEL2_REQUESTED_ALIAS,
                "high",
                int(R2_PARAMETERS["stage1_max_completion_tokens"]),
                int(R2_PARAMETERS["agent_action_cap"]),
                int(R2_PARAMETERS["temperature"]),
            ),
            parse_r2_action,
        ),
        (
            "r3",
            R3_DERIVED_SYSTEM_PROMPT,
            render_r3_user_prompt(_SYNTHETIC_QUESTION),
            render_r3_observation,
            R3PlannerConfig(
                MODEL2_REQUESTED_ALIAS,
                "high",
                int(R3_PARAMETERS["stage1_max_completion_tokens"]),
                int(R3_PARAMETERS["agent_action_cap"]),
                int(R3_PARAMETERS["temperature"]),
            ),
            parse_r3_action,
        ),
    ):
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
            {
                "role": "assistant",
                "content": (
                    "Thought: Search the named city broadly.\n"
                    "Action: search_chatrecord\n"
                    'Action Input: {"keywords":["Kyoto"],"top_k":5}'
                ),
            },
            {
                "role": "user",
                "content": observation_renderer(
                    "PROTOCOL COMPATIBILITY STOP TURN: the backend has no further "
                    "results and the host requires termination now. Return the "
                    "frozen textual ReAct format with Action: finish_search and a "
                    "valid JSON Action Input. Do not search or take another note."
                ),
            },
        ]
        response, receipt, request_hash, prompt_hash = _call_smoke(
            provider=provider,
            component=component,
            expected_served_model=expected_served_model,
            messages=messages,
            tools=[],
            config=config,
        )
        message = _message(response)
        if message.get("tool_calls") not in (None, []):
            raise Model2PreflightError(f"{component.upper()} returned native tool calls")
        if receipt.finish_reason != "stop":
            raise Model2PreflightError(
                f"{component.upper()} textual response did not finish with stop"
            )
        action = parser(message.get("content"))
        if action.name != "finish_search":
            raise Model2PreflightError(
                f"{component.upper()} stop smoke did not return finish_search"
            )
        results.append(
            RoleSmokeResult(
                component=component,
                request_sha256=request_hash,
                system_prompt_sha256=prompt_hash,
                receipt=receipt,
                checks={
                    "textual_react": True,
                    "no_native_tool_calls": True,
                    "action": action.name,
                    "action_input_json": True,
                    "synthetic_stop_turn": True,
                },
            )
        )

    answer_messages = [
        {"role": "system", "content": ANSWERER_SYSTEM_PROMPT},
        {"role": "user", "content": _answerer_user_prompt()},
    ]
    response, receipt, request_hash, prompt_hash = _call_smoke(
        provider=provider,
        component="answerer",
        expected_served_model=expected_served_model,
        messages=answer_messages,
        tools=[],
        config=AnswererConfig(model=MODEL2_REQUESTED_ALIAS),
    )
    answer_message = _message(response)
    if answer_message.get("tool_calls") not in (None, []):
        raise Model2PreflightError("Answerer returned tool calls")
    if receipt.finish_reason != "stop":
        raise Model2PreflightError("Answerer JSON response did not finish with stop")
    parsed = _parse_answer_payload(
        answer_message.get("content"), allowed_ids=frozenset({_SYNTHETIC_EVIDENCE_ID})
    )
    results.append(
        RoleSmokeResult(
            component="answerer",
            request_sha256=request_hash,
            system_prompt_sha256=prompt_hash,
            receipt=receipt,
            checks={
                "exact_json": True,
                "no_tool_calls": True,
                "citation_subset": True,
                "citation_count": len(parsed["citations"]),
            },
        )
    )

    if tuple(item.component for item in results) != MODEL2_ROLE_ORDER:
        raise Model2PreflightError("Role smoke order differs from the frozen plan")
    return tuple(results)


@dataclass(frozen=True)
class Model2SmokeReport:
    requested_alias: str
    expected_served_model: str
    roles: tuple[RoleSmokeResult, ...]

    def __post_init__(self) -> None:
        if self.requested_alias != MODEL2_REQUESTED_ALIAS:
            raise Model2IdentityError("Smoke report requested alias differs")
        if self.expected_served_model != MODEL2_EXPECTED_SERVED_MODEL:
            raise Model2IdentityError("Smoke report expected served model differs")
        if tuple(item.component for item in self.roles) != MODEL2_ROLE_ORDER:
            raise Model2PreflightError("Smoke report role coverage differs")
        if {
            receipt.served_model
            for item in self.roles
            for receipt in item.receipts
        } != {self.expected_served_model}:
            raise Model2IdentityError("Smoke report contains served model drift")

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "artifact_type": "model2-role-smoke",
            "protocol_version": MODEL2_PREFLIGHT_PROTOCOL_VERSION,
            "status": "passed",
            "requested_alias": self.requested_alias,
            "expected_served_model": self.expected_served_model,
            "observed_served_models": [self.expected_served_model],
            "api_style": MODEL2_API_STYLE,
            "identity_policy": "every response must match exactly or fail closed",
            "roles": [item.to_dict() for item in self.roles],
        }


def run_model2_smoke_report(
    provider: ChatProvider,
    *,
    expected_served_model: str = MODEL2_EXPECTED_SERVED_MODEL,
) -> Model2SmokeReport:
    if expected_served_model != MODEL2_EXPECTED_SERVED_MODEL:
        raise Model2IdentityError(
            "Preflight report must bind the independently confirmed served model"
        )
    return Model2SmokeReport(
        requested_alias=MODEL2_REQUESTED_ALIAS,
        expected_served_model=expected_served_model,
        roles=run_model2_role_smokes(
            provider, expected_served_model=expected_served_model
        ),
    )


def _write_exclusive(path: Path, value: Mapping[str, Any]) -> Path:
    destination = Path(path).resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    payload = canonical_json_bytes(value) + b"\n"
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(destination, flags, 0o644)
    except FileExistsError as exc:
        raise Model2PreflightError("Refusing to replace an existing preflight artifact") from exc
    try:
        offset = 0
        while offset < len(payload):
            written = os.write(descriptor, payload[offset:])
            if written < 1:  # pragma: no cover - defensive OS invariant
                raise OSError("preflight artifact write made no progress")
            offset += written
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    return destination


def write_model_catalog_check(path: Path, check: ModelCatalogCheck) -> Path:
    return _write_exclusive(path, check.to_dict())


def write_model2_smoke_report(path: Path, report: Model2SmokeReport) -> Path:
    return _write_exclusive(path, report.to_dict())


def _read_json(path: Path) -> Mapping[str, Any]:
    source = Path(path)
    if source.is_symlink() or not source.is_file():
        raise Model2PreflightError("Preflight artifact must be a regular file")
    try:
        value = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise Model2PreflightError("Preflight artifact is not valid UTF-8 JSON") from exc
    if not isinstance(value, Mapping):
        raise Model2PreflightError("Preflight artifact root must be an object")
    return value


def _validate_receipt(
    value: Any, *, component: str, expected_call_index: int = 1
) -> ModelResponseReceipt:
    required = {
        "component",
        "call_index",
        "requested_alias",
        "served_model",
        "usage",
        "finish_reason",
        "response_id",
        "system_fingerprint",
    }
    if not isinstance(value, Mapping) or set(value) != required:
        raise Model2PreflightError("Serialized response receipt fields differ")
    receipt = ModelResponseReceipt(
        component=value["component"],
        call_index=value["call_index"],
        requested_alias=value["requested_alias"],
        served_model=value["served_model"],
        usage=value["usage"],
        finish_reason=value["finish_reason"],
        response_id=value["response_id"],
        system_fingerprint=value["system_fingerprint"],
    )
    if value["component"] != component:
        raise Model2PreflightError("Serialized receipt component differs")
    if receipt.call_index != expected_call_index:
        raise Model2PreflightError("Serialized smoke receipt call index differs")
    return receipt


def verify_sanitized_preflight_artifact(path: Path) -> dict[str, Any]:
    """Validate one sanitized artifact and return a safe, compact summary."""

    value = _read_json(path)
    common = {
        "schema_version",
        "artifact_type",
        "protocol_version",
        "status",
    }
    if (
        value.get("schema_version") != 1
        or value.get("protocol_version") != MODEL2_PREFLIGHT_PROTOCOL_VERSION
        or value.get("status") != "passed"
    ):
        raise Model2PreflightError("Preflight artifact header differs")
    artifact_type = value.get("artifact_type")
    if artifact_type == "model2-models-check":
        required = common | {
            "requested_alias",
            "endpoint",
            "alias_present",
            "advertised_model_count",
            "advertised_model_ids",
            "alias_context_limits",
        }
        if set(value) != required or value.get("alias_present") is not True:
            raise Model2PreflightError("Models-check artifact fields differ")
        model_ids = value.get("advertised_model_ids")
        if not isinstance(model_ids, list):
            raise Model2PreflightError("Models-check IDs must be an array")
        check = ModelCatalogCheck(
            requested_alias=value["requested_alias"],
            endpoint=value["endpoint"],
            advertised_model_ids=tuple(model_ids),
            alias_context_limits=value.get("alias_context_limits"),
        )
        if value.get("advertised_model_count") != len(check.advertised_model_ids):
            raise Model2PreflightError("Models-check count differs")
        return {
            "verified": True,
            "artifact_type": artifact_type,
            "requested_alias": check.requested_alias,
            "alias_present": True,
            "advertised_model_count": len(check.advertised_model_ids),
            "context_limit": next(iter(check.alias_context_limits.values())),
        }
    if artifact_type == "model2-role-smoke":
        required = common | {
            "requested_alias",
            "expected_served_model",
            "observed_served_models",
            "api_style",
            "identity_policy",
            "roles",
        }
        if set(value) != required:
            raise Model2PreflightError("Smoke artifact fields differ")
        if (
            value.get("requested_alias") != MODEL2_REQUESTED_ALIAS
            or value.get("expected_served_model") != MODEL2_EXPECTED_SERVED_MODEL
            or value.get("observed_served_models") != [MODEL2_EXPECTED_SERVED_MODEL]
            or value.get("api_style") != MODEL2_API_STYLE
            or value.get("identity_policy")
            != "every response must match exactly or fail closed"
        ):
            raise Model2IdentityError("Smoke artifact deployment identity differs")
        roles = value.get("roles")
        if not isinstance(roles, list) or len(roles) != len(MODEL2_ROLE_ORDER):
            raise Model2PreflightError("Smoke artifact role count differs")
        for expected_component, row in zip(MODEL2_ROLE_ORDER, roles, strict=True):
            required_role = {
                "component",
                "status",
                "request_sha256",
                "system_prompt_sha256",
                "receipt",
                "additional_receipts",
                "additional_request_sha256s",
                "checks",
            }
            if (
                not isinstance(row, Mapping)
                or set(row) != required_role
                or row.get("component") != expected_component
                or row.get("status") != "passed"
                or not isinstance(row.get("checks"), Mapping)
            ):
                raise Model2PreflightError("Smoke role record differs")
            for field in ("request_sha256", "system_prompt_sha256"):
                candidate = row.get(field)
                if not isinstance(candidate, str) or _SHA256.fullmatch(candidate) is None:
                    raise Model2PreflightError("Smoke role hash is invalid")
            receipt = _validate_receipt(
                row.get("receipt"), component=expected_component
            )
            if receipt.served_model != MODEL2_EXPECTED_SERVED_MODEL:
                raise Model2IdentityError("Smoke receipt served model drifted")
            if expected_component == "r1":
                if receipt.finish_reason not in {"tool_calls", "stop"}:
                    raise Model2PreflightError("R1 smoke finish reason is invalid")
            elif receipt.finish_reason != "stop":
                raise Model2PreflightError("Plain smoke finish reason differs")
            additional_receipts = row.get("additional_receipts")
            additional_hashes = row.get("additional_request_sha256s")
            if not isinstance(additional_receipts, list) or not isinstance(
                additional_hashes, list
            ):
                raise Model2PreflightError("Additional smoke metadata is invalid")
            expected_additional = 2 if expected_component == "r1" else 0
            if (
                len(additional_receipts) != expected_additional
                or len(additional_hashes) != expected_additional
            ):
                raise Model2PreflightError("Additional smoke response count differs")
            for offset, (extra_receipt_value, request_hash) in enumerate(
                zip(additional_receipts, additional_hashes, strict=True), start=2
            ):
                extra_receipt = _validate_receipt(
                    extra_receipt_value,
                    component=expected_component,
                    expected_call_index=offset,
                )
                if extra_receipt.served_model != MODEL2_EXPECTED_SERVED_MODEL:
                    raise Model2IdentityError("Additional smoke receipt model drifted")
                if extra_receipt.finish_reason not in {"tool_calls", "stop"}:
                    raise Model2PreflightError(
                        "Additional R1 smoke finish reason is invalid"
                    )
                if not isinstance(request_hash, str) or _SHA256.fullmatch(
                    request_hash
                ) is None:
                    raise Model2PreflightError("Additional smoke request hash is invalid")
            _validate_smoke_checks(expected_component, row["checks"])
        return {
            "verified": True,
            "artifact_type": artifact_type,
            "requested_alias": MODEL2_REQUESTED_ALIAS,
            "served_model": MODEL2_EXPECTED_SERVED_MODEL,
            "role_smokes_passed": len(roles),
            "components": list(MODEL2_ROLE_ORDER),
        }
    raise Model2PreflightError("Unknown preflight artifact type")
