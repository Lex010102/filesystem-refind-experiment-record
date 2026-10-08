"""Strict textual ReAct actions and observations for the R2-Raw planner."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Mapping

from .evidence import EvidenceValidationError, canonical_json_bytes, sha256_bytes
from .r2_index import R2SearchResult, parse_r2_date
from .r2_protocol import R2_PARAMETERS, R2_RUNTIME_LIMITS


R2_ACTION_NAMES = ("search_chatrecord", "take_note", "finish_search")
_RESPONSE = re.compile(
    r"\AThought:\s*(?P<thought>[^\r\n]+)\r?\n"
    r"Action:\s*(?P<action>[a-z_]+)\r?\n"
    r"Action Input:\s*(?P<input>\{.*\})\s*\Z",
    re.DOTALL,
)

R2_ACTION_CONTRACT: Mapping[str, Any] = {
    "format": "Thought + Action + Action Input JSON object",
    "actions": {
        "search_chatrecord": {
            "required": ["keywords", "top_k"],
            "optional": ["date_from", "date_to"],
            "top_k": 5,
            "date_format": "YYYY/MM/DD",
        },
        "take_note": {"required": ["indices"], "optional": []},
        "finish_search": {"required": [], "optional": []},
    },
}
FROZEN_R2_ACTION_CONTRACT_SHA256 = (
    "3fa6b1160c2f7f9b2a8b3e232721d4ca78a161abb31af0d4f1f2e307b7354581"
)


class R2ActionError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class R2Action:
    thought: str
    name: str
    arguments: Mapping[str, Any]
    raw_text: str


def r2_action_contract_sha256() -> str:
    return sha256_bytes(canonical_json_bytes(R2_ACTION_CONTRACT))


def verify_r2_action_contract() -> None:
    if r2_action_contract_sha256() != FROZEN_R2_ACTION_CONTRACT_SHA256:
        raise EvidenceValidationError("R2 action contract changed without hash update")


def _validate_search(arguments: dict[str, Any]) -> None:
    required = {"keywords", "top_k"}
    optional = {"date_from", "date_to"}
    if not required <= set(arguments) or not set(arguments) <= required | optional:
        raise R2ActionError(
            "invalid_arguments",
            "search_chatrecord requires keywords/top_k and only optional date bounds",
        )
    keywords = arguments["keywords"]
    if not isinstance(keywords, list) or not keywords:
        raise R2ActionError("invalid_keywords", "keywords must be a nonempty array")
    if len(keywords) > int(R2_RUNTIME_LIMITS["max_keywords"]):
        raise R2ActionError("invalid_keywords", "keywords exceed the fixed limit")
    if any(not isinstance(item, str) or not item.strip() for item in keywords):
        raise R2ActionError("invalid_keywords", "keywords must be nonempty strings")
    if sum(len(item) for item in keywords) > int(
        R2_RUNTIME_LIMITS["max_keyword_characters"]
    ):
        raise R2ActionError("invalid_keywords", "keywords are too long")
    if isinstance(arguments["top_k"], bool) or arguments["top_k"] != int(
        R2_PARAMETERS["top_k"]
    ):
        raise R2ActionError("invalid_top_k", "formal R2-Raw top_k must equal 5")
    for key in ("date_from", "date_to"):
        if key in arguments:
            try:
                parse_r2_date(arguments[key], key)
            except EvidenceValidationError as exc:
                raise R2ActionError("invalid_date", str(exc)) from exc
    if "date_from" in arguments and "date_to" in arguments:
        lower = parse_r2_date(arguments["date_from"], "date_from")
        upper = parse_r2_date(arguments["date_to"], "date_to")
        if lower is not None and upper is not None and lower > upper:
            raise R2ActionError("invalid_date", "date_from is later than date_to")


def _validate_note(arguments: dict[str, Any]) -> None:
    if set(arguments) != {"indices"}:
        raise R2ActionError("invalid_arguments", "take_note requires only indices")
    indices = arguments["indices"]
    if not isinstance(indices, list) or not indices:
        raise R2ActionError("invalid_indices", "indices must be a nonempty array")
    if any(isinstance(item, bool) or not isinstance(item, int) or item < 1 for item in indices):
        raise R2ActionError("invalid_indices", "indices must be positive integers")
    if len(indices) != len(set(indices)):
        raise R2ActionError("invalid_indices", "indices must not repeat")


def parse_r2_action(text: str) -> R2Action:
    if not isinstance(text, str) or not text.strip():
        raise R2ActionError("invalid_format", "planner response must be nonempty text")
    if len(text) > int(R2_RUNTIME_LIMITS["max_action_input_characters"]):
        raise R2ActionError("invalid_format", "planner response exceeds its size limit")
    match = _RESPONSE.fullmatch(text.strip())
    if match is None:
        raise R2ActionError(
            "invalid_format", "use exactly Thought, Action, and Action Input"
        )
    thought = match.group("thought").strip()
    action_name = match.group("action")
    if not thought:
        raise R2ActionError("invalid_format", "Thought must be nonempty")
    if action_name not in R2_ACTION_NAMES:
        raise R2ActionError("invalid_action", "unknown R2 action")
    try:
        arguments = json.loads(match.group("input"))
    except json.JSONDecodeError as exc:
        raise R2ActionError("invalid_json", "Action Input must be valid JSON") from exc
    if not isinstance(arguments, dict):
        raise R2ActionError("invalid_json", "Action Input must be a JSON object")
    if action_name == "search_chatrecord":
        _validate_search(arguments)
    elif action_name == "take_note":
        _validate_note(arguments)
    elif arguments:
        raise R2ActionError("invalid_arguments", "finish_search requires {}")
    frozen_arguments = dict(arguments)
    if action_name == "search_chatrecord":
        frozen_arguments["keywords"] = tuple(arguments["keywords"])
    elif action_name == "take_note":
        frozen_arguments["indices"] = tuple(arguments["indices"])
    return R2Action(
        thought=thought,
        name=action_name,
        arguments=MappingProxyType(frozen_arguments),
        raw_text=text.strip(),
    )


def format_r2_search_observation(result: R2SearchResult) -> str:
    if not result.hits:
        return "No matching memory found."
    blocks: list[str] = []
    for hit in result.hits:
        lines = [
            (
                f"Result {hit.result_index} | score={hit.rrf_score:.8f} | "
                f"session={hit.anchor.session_id} | "
                f"date={hit.anchor.session_date.replace('-', '/')} | "
                f"path=/memories/{hit.anchor.relative_path} | "
                f"center={hit.anchor.exchange_id}"
            )
        ]
        for exchange in hit.context:
            marker = "[MATCH] " if exchange.exchange_id == hit.anchor.exchange_id else ""
            lines.append(marker + exchange.display_text)
        blocks.append("\n".join(lines))
    observation = "\n\n".join(blocks)
    if len(observation) > int(R2_RUNTIME_LIMITS["max_observation_characters"]):
        raise EvidenceValidationError("R2 observation exceeds the safety limit")
    return observation


def format_r2_error_observation(error: R2ActionError) -> str:
    return f"Error [{error.code}]: {error}"
