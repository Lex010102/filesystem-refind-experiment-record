"""Strict textual ReAct actions and curated observations for R3."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Mapping

from .evidence import EvidenceValidationError, canonical_json_bytes, sha256_bytes
from .r3_index import R3SearchResult, parse_r3_date
from .r3_protocol import R3_PARAMETERS, R3_RUNTIME_LIMITS


R3_ACTION_NAMES = ("search_chatrecord", "take_note", "finish_search")
_RESPONSE = re.compile(
    r"\AThought:\s*(?P<thought>[^\r\n]+)\r?\n"
    r"Action:\s*(?P<action>[a-z_]+)\r?\n"
    r"Action Input:\s*(?P<input>\{.*\})\s*\Z",
    re.DOTALL,
)

R3_ACTION_CONTRACT: Mapping[str, Any] = {
    "format": "Thought + Action + Action Input JSON object",
    "actions": {
        "search_chatrecord": {
            "required": ["keywords", "top_k"],
            "optional": ["date_from", "date_to"],
            "top_k": 5,
            "date_format": "YYYY/MM/DD",
            "backend": "s3-curated-facts",
        },
        "take_note": {"required": ["indices"], "optional": []},
        "finish_search": {"required": [], "optional": []},
    },
}
FROZEN_R3_ACTION_CONTRACT_SHA256 = (
    "115512fb955e8c7fca557e4b995c5bfd8717ca72dfb184810b04343bc595cd08"
)


class R3ActionError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class R3Action:
    thought: str
    name: str
    arguments: Mapping[str, Any]
    raw_text: str


def r3_action_contract_sha256() -> str:
    return sha256_bytes(canonical_json_bytes(R3_ACTION_CONTRACT))


def verify_r3_action_contract() -> None:
    if r3_action_contract_sha256() != FROZEN_R3_ACTION_CONTRACT_SHA256:
        raise EvidenceValidationError("R3 action contract changed without hash update")


def _validate_search(arguments: dict[str, Any]) -> None:
    required = {"keywords", "top_k"}
    optional = {"date_from", "date_to"}
    if not required <= set(arguments) or not set(arguments) <= required | optional:
        raise R3ActionError(
            "invalid_arguments",
            "search_chatrecord requires keywords/top_k and only optional date bounds",
        )
    keywords = arguments["keywords"]
    if not isinstance(keywords, list) or not keywords:
        raise R3ActionError("invalid_keywords", "keywords must be a nonempty array")
    if len(keywords) > int(R3_RUNTIME_LIMITS["max_keywords"]):
        raise R3ActionError("invalid_keywords", "keywords exceed the fixed limit")
    if any(not isinstance(item, str) or not item.strip() for item in keywords):
        raise R3ActionError("invalid_keywords", "keywords must be nonempty strings")
    if sum(len(item) for item in keywords) > int(
        R3_RUNTIME_LIMITS["max_keyword_characters"]
    ):
        raise R3ActionError("invalid_keywords", "keywords are too long")
    if isinstance(arguments["top_k"], bool) or arguments["top_k"] != int(
        R3_PARAMETERS["top_k"]
    ):
        raise R3ActionError("invalid_top_k", "formal R3 top_k must equal 5")
    for key in ("date_from", "date_to"):
        if key in arguments:
            try:
                parse_r3_date(arguments[key], key)
            except EvidenceValidationError as exc:
                raise R3ActionError("invalid_date", str(exc)) from exc
    if "date_from" in arguments and "date_to" in arguments:
        lower = parse_r3_date(arguments["date_from"], "date_from")
        upper = parse_r3_date(arguments["date_to"], "date_to")
        if lower is not None and upper is not None and lower > upper:
            raise R3ActionError("invalid_date", "date_from is later than date_to")


def _validate_note(arguments: dict[str, Any]) -> None:
    if set(arguments) != {"indices"}:
        raise R3ActionError("invalid_arguments", "take_note requires only indices")
    indices = arguments["indices"]
    if not isinstance(indices, list) or not indices:
        raise R3ActionError("invalid_indices", "indices must be a nonempty array")
    if any(
        isinstance(item, bool) or not isinstance(item, int) or item < 1
        for item in indices
    ):
        raise R3ActionError("invalid_indices", "indices must be positive integers")
    if len(indices) != len(set(indices)):
        raise R3ActionError("invalid_indices", "indices must not repeat")


def parse_r3_action(text: str) -> R3Action:
    if not isinstance(text, str) or not text.strip():
        raise R3ActionError("invalid_format", "planner response must be nonempty text")
    if len(text) > int(R3_RUNTIME_LIMITS["max_action_input_characters"]):
        raise R3ActionError("invalid_format", "planner response exceeds its size limit")
    match = _RESPONSE.fullmatch(text.strip())
    if match is None:
        raise R3ActionError(
            "invalid_format", "use exactly Thought, Action, and Action Input"
        )
    thought = match.group("thought").strip()
    action_name = match.group("action")
    if not thought:
        raise R3ActionError("invalid_format", "Thought must be nonempty")
    if action_name not in R3_ACTION_NAMES:
        raise R3ActionError("invalid_action", "unknown R3 action")
    try:
        arguments = json.loads(match.group("input"))
    except json.JSONDecodeError as exc:
        raise R3ActionError("invalid_json", "Action Input must be valid JSON") from exc
    if not isinstance(arguments, dict):
        raise R3ActionError("invalid_json", "Action Input must be a JSON object")
    if action_name == "search_chatrecord":
        _validate_search(arguments)
    elif action_name == "take_note":
        _validate_note(arguments)
    elif arguments:
        raise R3ActionError("invalid_arguments", "finish_search requires {}")
    frozen_arguments = dict(arguments)
    if action_name == "search_chatrecord":
        frozen_arguments["keywords"] = tuple(arguments["keywords"])
    elif action_name == "take_note":
        frozen_arguments["indices"] = tuple(arguments["indices"])
    return R3Action(
        thought=thought,
        name=action_name,
        arguments=MappingProxyType(frozen_arguments),
        raw_text=text.strip(),
    )


def format_r3_search_observation(result: R3SearchResult) -> str:
    if not result.hits:
        return "No matching curated memory found."
    blocks: list[str] = []
    for hit in result.hits:
        header = (
            f"Result {hit.result_index} | rrf={hit.rrf_score:.8f} | "
            f"unit_bm25={hit.bm25_score:.8f} rank={hit.unit_rank} | "
            f"group_score={hit.group_score:.8f} rank={hit.group_rank} | "
            f"path=/memories/{hit.anchor.relative_path} | "
            f"entity={hit.anchor.h1_heading} | topic={hit.anchor.h2_heading} | "
            f"center={hit.anchor.unit_id} | "
            f"center_lines={hit.anchor.line_start}-{hit.anchor.line_end} | "
            f"source_dates={','.join(value.replace('-', '/') for value in hit.anchor.source_dates)} | "
            f"matched_dates={','.join(value.replace('-', '/') for value in hit.matched_dates)}"
        )
        lines = [header]
        for unit in hit.context:
            marker = "[MATCH] " if unit.unit_id == hit.anchor.unit_id else ""
            lines.append(
                f"{marker}{unit.unit_id} | lines={unit.line_start}-{unit.line_end} | "
                f"locators={','.join(unit.source_locators)} | "
                f"dia_ids={','.join(unit.dia_ids)}"
            )
            lines.append(unit.exact_markdown_text)
        blocks.append("\n".join(lines))
    observation = "\n\n".join(blocks)
    if len(observation) > int(R3_RUNTIME_LIMITS["max_observation_characters"]):
        raise EvidenceValidationError("R3 observation exceeds the safety limit")
    return observation


def format_r3_error_observation(error: R3ActionError) -> str:
    return f"Error [{error.code}]: {error}"
