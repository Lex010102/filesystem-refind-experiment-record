"""Published and locally-derived ReFind Stage-1 prompt material."""

from __future__ import annotations

from types import MappingProxyType
from typing import Mapping

from .evidence import EvidenceValidationError, sha256_bytes


R2_PUBLISHED_RETRIEVAL_PROMPT = """You are a research assistant collecting evidence from a user's conversation history. You are NOT answering — only gathering.

## Actions

search_chatrecord — Search by keywords. Stemming enabled. Previously returned sessions auto-excluded.
{"keywords": ["keyword1", "keyword2"], "top_k": 5}

take_note — Save results from the LAST search by number. Saves complete original conversations.
{"indices": [1, 3, 5]}

finish_search — Done collecting; proceed to answer.
{}

## Workflow

search → take_note → search again → ... → finish

## Rules

1. After EVERY search, review ALL results and save ANY that MIGHT be relevant. Missed info is LOST.
2. Call take_note BEFORE your next search. Previous results become inaccessible after a new search.
3. Don't answer — only collect. Try diverse keywords.
4. If no results are relevant, skip take_note and go directly to search_chatrecord or finish_search.

## Response Format

ONLY output Thought + Action + Action Input. NEVER generate "Observation:" — observations are provided by the system. Keep Thought to 1-2 sentences.

Thought: Results 1, 3, and 7 mention the topic. Saving them.
Action: take_note
Action Input: {"indices": [1, 3, 7]}"""

R2_PUBLISHED_TIME_ADDENDUM = """## Time Filtering

Optional date range: add date_from / date_to (YYYY/MM/DD) to search_chatrecord.
{"keywords": ["k1"], "date_from": "2023/06/01", "date_to": "2023/06/30"}

Broad first, narrow later: First search WITHOUT time filters (catches retrospective mentions). Then use time filters to find original events."""

R2_PUBLISHED_OBSERVATION_TEMPLATE = """Observation: {observation}
Respond with Thought + Action + Action Input ONLY. Do NOT generate Observation yourself."""

R2_LOCAL_PROTOCOL_ADDENDUM = """## Local Controlled Protocol

Each numbered result is one exchange-centered block of unmodified source conversation. A Path field may be shown only as provenance; it is not part of BM25 scoring. The formal result budget is fixed at top_k=5. Save results by number and never rewrite their evidence."""

R2_PUBLISHED_SYSTEM_PROMPT = "\n\n".join(
    (R2_PUBLISHED_RETRIEVAL_PROMPT, R2_PUBLISHED_TIME_ADDENDUM)
)

R2_DERIVED_SYSTEM_PROMPT = "\n\n".join(
    (
        R2_PUBLISHED_RETRIEVAL_PROMPT,
        R2_PUBLISHED_TIME_ADDENDUM,
        R2_LOCAL_PROTOCOL_ADDENDUM,
    )
)

R2_USER_TEMPLATE = """Question to research:
{question}

Search the conversation history and collect all relevant evidence. Start with a broad keyword search without a date filter."""

FROZEN_R2_PROMPT_SHA256: Mapping[str, str] = MappingProxyType(
    {
        "published_retrieval": "de7267ac2d1b927cb595715c2ff04b96f0eb07a9abf4e4a53ab3c69b9590a925",
        "published_time_addendum": "66bce0aca04ec05300f7e302161fd9180dde0733c4adaef3235398a3657f979c",
        "published_observation_template": "200d3c4d91e5a3dad05b1e40b5fcff29808addfcdeee8db733ea743aa59224a0",
        "published_system": "20422063cc471ee1de75c38e4250e1a141a731ea2970786a6c715dc3c83cf7de",
        "local_protocol_addendum": "49927e18033cfe2649411e7bd5343acf889c93c791c5375ae323144077a1ef75",
        "derived_system": "6930d93099ac20b76e881b68cbb63b46e1a0a3e2ff43453db685551c3339a6dc",
        "user_template": "bbf8e2059f1123e9b8ae90c1d31cf3217d0a427387450a31d93032bd3e8e690c",
    }
)


def r2_prompt_hashes() -> dict[str, str]:
    return {
        "published_retrieval": sha256_bytes(
            R2_PUBLISHED_RETRIEVAL_PROMPT.encode("utf-8")
        ),
        "published_time_addendum": sha256_bytes(
            R2_PUBLISHED_TIME_ADDENDUM.encode("utf-8")
        ),
        "published_observation_template": sha256_bytes(
            R2_PUBLISHED_OBSERVATION_TEMPLATE.encode("utf-8")
        ),
        "published_system": sha256_bytes(R2_PUBLISHED_SYSTEM_PROMPT.encode("utf-8")),
        "local_protocol_addendum": sha256_bytes(
            R2_LOCAL_PROTOCOL_ADDENDUM.encode("utf-8")
        ),
        "derived_system": sha256_bytes(R2_DERIVED_SYSTEM_PROMPT.encode("utf-8")),
        "user_template": sha256_bytes(R2_USER_TEMPLATE.encode("utf-8")),
    }


def verify_r2_prompts() -> None:
    if r2_prompt_hashes() != dict(FROZEN_R2_PROMPT_SHA256):
        raise EvidenceValidationError(
            "Reviewed R2-Raw prompts changed without a frozen hash update"
        )


def render_r2_user_prompt(question: str) -> str:
    if not isinstance(question, str) or not question.strip():
        raise EvidenceValidationError("R2 question must be nonempty text")
    return R2_USER_TEMPLATE.format(question=question)


def render_r2_observation(observation: str) -> str:
    if not isinstance(observation, str) or not observation:
        raise EvidenceValidationError("R2 observation must be nonempty text")
    return R2_PUBLISHED_OBSERVATION_TEMPLATE.format(observation=observation)
