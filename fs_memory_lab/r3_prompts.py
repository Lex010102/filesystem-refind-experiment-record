"""Published ReFind prompt material plus the frozen R3 curated adapter."""

from __future__ import annotations

from types import MappingProxyType
from typing import Mapping

from .evidence import EvidenceValidationError, sha256_bytes


R3_PUBLISHED_RETRIEVAL_PROMPT = """You are a research assistant collecting evidence from a user's conversation history. You are NOT answering — only gathering.

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

R3_PUBLISHED_TIME_ADDENDUM = """## Time Filtering

Optional date range: add date_from / date_to (YYYY/MM/DD) to search_chatrecord.
{"keywords": ["k1"], "date_from": "2023/06/01", "date_to": "2023/06/30"}

Broad first, narrow later: First search WITHOUT time filters (catches retrospective mentions). Then use time filters to find original events."""

R3_PUBLISHED_OBSERVATION_TEMPLATE = """Observation: {observation}
Respond with Thought + Action + Action Input ONLY. Do NOT generate Observation yourself."""

R3_CURATED_PROTOCOL_ADDENDUM = """## R3 Curated-Memory Adapter

The backend is the agent-curated S3 Markdown memory, not raw chat. The historical action name search_chatrecord is retained only for wire compatibility.

Each indexed document is one locator-bearing Markdown fact. Facts are grouped by file and H2 topic. Ranking combines fact BM25 rank with H2-group rank. Every returned result is one center fact plus up to two neighboring facts on each side within the same H2 group; it never crosses a topic or file boundary. Previously returned H2 groups are automatically excluded from later searches in this question.

A fact can cite several source dates. Date filtering keeps a fact when at least one cited source date lies inside the inclusive range. The result shows all source dates and the dates matched by the current filter.

The formal result budget is fixed at top_k=5. Save results by number. Never rewrite evidence and never answer the question yourself; only select evidence for the common downstream Answerer."""

R3_PUBLISHED_SYSTEM_PROMPT = "\n\n".join(
    (R3_PUBLISHED_RETRIEVAL_PROMPT, R3_PUBLISHED_TIME_ADDENDUM)
)
R3_DERIVED_SYSTEM_PROMPT = "\n\n".join(
    (
        R3_PUBLISHED_RETRIEVAL_PROMPT,
        R3_PUBLISHED_TIME_ADDENDUM,
        R3_CURATED_PROTOCOL_ADDENDUM,
    )
)

R3_USER_TEMPLATE = """Question to research:
{question}

Search the curated memory and collect all relevant evidence. Start with a broad keyword search without a date filter."""

# Filled from the exact UTF-8 prompt constants and checked on every formal run.
FROZEN_R3_PROMPT_SHA256: Mapping[str, str] = MappingProxyType(
    {
        "published_retrieval": "de7267ac2d1b927cb595715c2ff04b96f0eb07a9abf4e4a53ab3c69b9590a925",
        "published_time_addendum": "66bce0aca04ec05300f7e302161fd9180dde0733c4adaef3235398a3657f979c",
        "published_observation_template": "200d3c4d91e5a3dad05b1e40b5fcff29808addfcdeee8db733ea743aa59224a0",
        "published_system": "20422063cc471ee1de75c38e4250e1a141a731ea2970786a6c715dc3c83cf7de",
        "curated_protocol_addendum": "93c599be7031a7bd168801f0e5cd7322f0c0a0b07a14a8ef30733f56374a0858",
        "derived_system": "60d0c608bdda6e13c46a9e6cbf4cd7cae4f7eea8d7fcd2d8a4f8f9bde415df7c",
        "user_template": "53bed8501ade4999e7a1dc52a5119ce8cee29388e30e99d072fe82525b1bb00d",
    }
)


def r3_prompt_hashes() -> dict[str, str]:
    return {
        "published_retrieval": sha256_bytes(
            R3_PUBLISHED_RETRIEVAL_PROMPT.encode("utf-8")
        ),
        "published_time_addendum": sha256_bytes(
            R3_PUBLISHED_TIME_ADDENDUM.encode("utf-8")
        ),
        "published_observation_template": sha256_bytes(
            R3_PUBLISHED_OBSERVATION_TEMPLATE.encode("utf-8")
        ),
        "published_system": sha256_bytes(R3_PUBLISHED_SYSTEM_PROMPT.encode("utf-8")),
        "curated_protocol_addendum": sha256_bytes(
            R3_CURATED_PROTOCOL_ADDENDUM.encode("utf-8")
        ),
        "derived_system": sha256_bytes(R3_DERIVED_SYSTEM_PROMPT.encode("utf-8")),
        "user_template": sha256_bytes(R3_USER_TEMPLATE.encode("utf-8")),
    }


def verify_r3_prompts() -> None:
    if r3_prompt_hashes() != dict(FROZEN_R3_PROMPT_SHA256):
        raise EvidenceValidationError(
            "Reviewed R3 prompts changed without a frozen hash update"
        )


def render_r3_user_prompt(question: str) -> str:
    if not isinstance(question, str) or not question.strip():
        raise EvidenceValidationError("R3 question must be nonempty text")
    return R3_USER_TEMPLATE.format(question=question)


def render_r3_observation(observation: str) -> str:
    if not isinstance(observation, str) or not observation:
        raise EvidenceValidationError("R3 observation must be nonempty text")
    return R3_PUBLISHED_OBSERVATION_TEMPLATE.format(observation=observation)
