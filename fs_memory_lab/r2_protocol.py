"""Frozen method contract for S1/S2 R2-Raw retrieval.

This module contains only protocol constants and deterministic hashes.  It does
not load an API key, create an index, or issue a model request.
"""

from __future__ import annotations

from types import MappingProxyType
from typing import Any, Mapping

from .evidence import EvidenceValidationError, canonical_json_bytes, sha256_bytes


R2_PROTOCOL_VERSION = "r2-raw-refind-style-v1"
R2_OFFICIAL_CODE_COMMIT = "a80175ca0eeb52a938d7cab7a602bc780de8a577"
R2_CELLS: Mapping[str, str] = MappingProxyType({"E2": "s1", "E4": "s2"})

R2_PARAMETERS: Mapping[str, Any] = MappingProxyType(
    {
        "unit": "exchange",
        "group": "session",
        "pairing": "adjacent-source-turns-with-singleton-tail",
        "expected_source_turns": 568,
        "expected_sessions": 30,
        "expected_odd_sessions": 16,
        "expected_exchange_units": 292,
        "bm25_k1": 1.2,
        "bm25_b": 0.75,
        "rrf_smoothing": 60,
        "top_k": 5,
        "context_window": 2,
        "agent_action_cap": 4,
        "date_format": "YYYY/MM/DD",
        "date_bounds": "inclusive",
        "seen_scope": "session",
        "path_in_bm25": False,
        "path_visible_in_observation": True,
        "stage1_max_completion_tokens": 4096,
        "temperature": 0,
        "formal_requested_model_alias": "coding",
        "formal_local_api_style": "portable",
        "portable_omits_reasoning_effort": True,
        "portable_omits_max_completion_tokens": True,
    }
)

# These are project-defined defensive limits.  They do not change the reported
# Top-K, context window, action cap, BM25, or RRF method.
R2_RUNTIME_LIMITS: Mapping[str, Any] = MappingProxyType(
    {
        "max_keywords": 32,
        "max_keyword_characters": 256,
        "max_action_input_characters": 16_384,
        "max_observation_characters": 250_000,
        "timeout_max_attempts": 3,
        "timeout_retry_backoff_seconds": (2, 4),
        "http_max_attempts": 5,
        "http_retry_backoff_seconds": (5, 15, 30, 60),
        "token_safety_fuse_unit": "provider_reported_total_tokens",
        "token_safety_fuse_limit": 1_000_000,
        "token_safety_fuse_scope": "per_episode_all_model_calls",
        "token_safety_fuse_requires_usage": True,
    }
)

R2_SOURCE_CLASSIFICATION: Mapping[str, str] = MappingProxyType(
    {
        "raw_chat_without_llm_rewrite": "paper",
        "paired_exchange_unit": "paper-with-locomo-role-adaptation",
        "singleton_tail": "project-defined-explicit-rule",
        "bm25_parameters": "paper",
        "session_aggregate_rrf": "paper",
        "top_k_and_context_window": "paper",
        "temporal_filtering": "paper",
        "seen_session_deduplication": "paper",
        "three_react_actions": "paper",
        "tokenizer_implementation": "author-competition-code-pinned",
        "s2_path_visible_not_scored": "project-defined-experimental-factor",
        "source_locator_attribution": "project-defined",
        "overlap_merge_and_evidence_budget": "project-defined-shared-contract",
        "nus_model_alias": "local-model-substitution",
        "nus_portable_wire_profile": "local-gateway-substitution",
    }
)

FROZEN_R2_PROTOCOL_SHA256 = (
    "b338aafc73f4f4fd674ad5433e624b1a4e2f44e3422e06b9f5bb1dfa7d1dacb2"
)


def r2_protocol_body() -> dict[str, Any]:
    return {
        "protocol_version": R2_PROTOCOL_VERSION,
        "official_code_commit": R2_OFFICIAL_CODE_COMMIT,
        "cells": dict(R2_CELLS),
        "parameters": dict(R2_PARAMETERS),
        "runtime_limits": {
            key: list(value) if isinstance(value, tuple) else value
            for key, value in R2_RUNTIME_LIMITS.items()
        },
        "source_classification": dict(R2_SOURCE_CLASSIFICATION),
    }


def r2_protocol_sha256() -> str:
    return sha256_bytes(canonical_json_bytes(r2_protocol_body()))


def verify_r2_protocol() -> None:
    if set(R2_CELLS) != {"E2", "E4"} or set(R2_CELLS.values()) != {"s1", "s2"}:
        raise EvidenceValidationError("R2-Raw cells must be exactly E2/S1 and E4/S2")
    if R2_PARAMETERS["expected_exchange_units"] != (
        R2_PARAMETERS["expected_source_turns"]
        + R2_PARAMETERS["expected_odd_sessions"]
    ) // 2:
        raise EvidenceValidationError("R2-Raw exchange-count contract is inconsistent")
    if R2_PARAMETERS["formal_local_api_style"] != "portable":
        raise EvidenceValidationError("R2-Raw formal local API style must be portable")
    if r2_protocol_sha256() != FROZEN_R2_PROTOCOL_SHA256:
        raise EvidenceValidationError(
            "Reviewed R2-Raw protocol changed without a frozen hash update"
        )
