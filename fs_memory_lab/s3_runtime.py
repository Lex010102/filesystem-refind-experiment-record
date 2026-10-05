"""Frozen tool and runtime contract for the formal S3 management build."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict
from typing import Any

from .agent import (
    COMPACTION_SUMMARY_MAX_COMPLETION_TOKENS,
    COMPACTION_SUMMARY_MAX_ROUNDS,
    COMPACTION_SYSTEM_PROMPT,
    COMPACTION_USER_PREFIX,
)
from .management_prompt import (
    BUILDER_PROMPT_VERSION,
    FROZEN_BUILDER_PROMPT_SHA256,
    FROZEN_LOCOMO_ATTRIBUTION_SHA256,
    FROZEN_MANAGEMENT_PROMPT_SHA256,
    LOCOMO_ATTRIBUTION_VERSION,
    MANAGEMENT_PROMPT_VERSION,
)
from .paper_config import (
    CONTEXT_COMPACTION_KEEP_ROUNDS,
    CONTEXT_COMPACTION_TRIGGER,
    MANAGEMENT,
    RANDOM_SEED,
)
from .paper_tools import MANAGEMENT_PROFILE, TOOL_DEFINITIONS
from .s3_protocol import (
    FROZEN_S3_USER_INSTRUCTION_SHA256,
    FROZEN_S3_USER_TEMPLATE_SHA256,
    S3_USER_WRAPPER_VERSION,
)


S3_RUNTIME_CONTRACT_SCHEMA_VERSION = "s3-management-runtime-contract-v1"
S3_RUNNER_VERSION = "s3-safe-runner-v1"

EXPECTED_S3_STREAM_MANIFEST_SHA256 = (
    "6323382879ddafdb21c1207bf22a3d11c277d323faabfa28d1ae3144e78025d5"
)
EXPECTED_S3_PROMPT_CONTRACT_SHA256 = (
    "2b16c9041829666e3825d2d349c689b6cc1ce4b9de6e367f35a123c485918a20"
)
EXPECTED_S3_RUNTIME_CONTRACT_SHA256 = (
    "ae480c40162e5262f74ef3fb5cb64314ad2507a744d59122c019039e8bb3017f"
)
FROZEN_MANAGEMENT_TOOL_PROFILE_SHA256 = (
    "e4541dedafbd645e6e11f8847c95283b8738c668915b006f06dd0dea57c0945e"
)
FROZEN_MANAGEMENT_TOOL_SCHEMA_SHA256 = (
    "3f4b2edc2045348743961231bc174c973e9c8a5147225bb9caece1fc7a254b56"
)
FROZEN_MANAGEMENT_TOOL_WIRE_SHA256 = (
    "f365069d4e826f8489273b85496ebdf3a61b93bbd7678baef531cec273f3c282"
)
FROZEN_MANAGEMENT_RUNTIME_CONFIG_SHA256 = (
    "da352bbdcbc12fa68169ac5ea8307fa5238f506b7040473f5272d7729ad18be2"
)

# This is the local experimental provider profile, not the paper's model.
LOCAL_S3_PROVIDER_PROFILE = {
    "api_style": "portable",
    "endpoint": "https://soclaas-api.comp.nus.edu.sg/v1/chat/completions",
    "max_response_bytes": 20_000_000,
    "requested_model": "coding",
    "request_timeout_seconds": 300,
}
EXPECTED_S3_SERVED_MODEL = "qwen3.8:27b"

# These are local safety ceilings, not values reported by the paper.  They are
# deliberately generous for one LoCoMo conversation while preventing a bad
# model response from growing an unbounded filesystem.
S3_RESOURCE_LIMITS = {
    "max_directories": 1_024,
    "max_directory_depth": 8,
    "max_file_bytes": 1_000_000,
    "max_files": 512,
    "max_paths": 1_536,
    "max_tool_arguments_bytes": 2_000_000,
    "max_tool_calls_per_episode": 256,
    "max_tool_calls_per_response": 32,
    "max_total_bytes": 20_000_000,
    "max_trace_bytes": 100_000_000,
    "max_work_bytes": 300_000_000,
}


def canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def management_tool_definitions() -> list[dict[str, Any]]:
    return [TOOL_DEFINITIONS[name] for name in MANAGEMENT_PROFILE]


def management_runtime_config() -> dict[str, Any]:
    return {
        "context_compaction": {
            "prompt_token_trigger": CONTEXT_COMPACTION_TRIGGER,
            "recent_rounds": CONTEXT_COMPACTION_KEEP_ROUNDS,
            "provenance": "local approximation; author prompt not published",
            "system_prompt": COMPACTION_SYSTEM_PROMPT,
            "system_prompt_sha256": sha256_bytes(
                COMPACTION_SYSTEM_PROMPT.encode("utf-8")
            ),
            "user_prefix": COMPACTION_USER_PREFIX,
            "user_prefix_sha256": sha256_bytes(
                COMPACTION_USER_PREFIX.encode("utf-8")
            ),
            "older_messages_serialization": (
                "json.dumps(messages[2:keep_start], ensure_ascii=False)"
            ),
            "required_finish_reason": "stop",
            "summary_role_config": {
                "model": "same active role model/provider override",
                "reasoning_effort": "same active role reasoning effort",
                "max_completion_tokens": COMPACTION_SUMMARY_MAX_COMPLETION_TOKENS,
                "max_rounds": COMPACTION_SUMMARY_MAX_ROUNDS,
            },
            "trace_records": [
                "exact_summary",
                "summary_sha256",
                "input_sha256",
                "served_model",
                "finish_reason",
                "response_id",
                "system_fingerprint",
            ],
        },
        "episode_policy": {
            "chunk_order": "ascending global_chunk_index",
            "chunk_count": 85,
            "one_fresh_agent_context_per_chunk": True,
            "persistent_filesystem_across_chunks": True,
        },
        "effective_local_execution": {
            "provider_profile": dict(LOCAL_S3_PROVIDER_PROFILE),
            "expected_served_model": EXPECTED_S3_SERVED_MODEL,
            "request_fields": {
                "max_completion_tokens": "omitted by portable adapter",
                "reasoning_effort": "omitted by portable adapter",
                "seed": "omitted",
                "stream": False,
                "temperature": "omitted",
                "tool_choice": "auto when tools are present",
                "tools": "ordered frozen seven-tool schema",
            },
            "automatic_retries": 0,
            "local_max_rounds_per_episode": MANAGEMENT.max_rounds,
        },
        "paper_target_role_config": asdict(MANAGEMENT),
        "random_seed": {
            "configured": RANDOM_SEED,
            "sent_to_provider": False,
        },
        "resource_limits": dict(S3_RESOURCE_LIMITS),
        "role": "management",
    }


def runtime_contract_document() -> dict[str, Any]:
    runtime_config = management_runtime_config()
    return {
        "schema_version": S3_RUNTIME_CONTRACT_SCHEMA_VERSION,
        "condition": "S3 Agent-curated filesystem",
        "status": "frozen-runner-ready-formal-build-not-started",
        "runner": {
            "module": "fs_memory_lab.s3_runner",
            "version": S3_RUNNER_VERSION,
        },
        "input_stream": {
            "artifact_id": "locomo/conv-50/s3-management-stream/v1",
            "manifest_filename": "s3-management-stream.json",
            "manifest_sha256": EXPECTED_S3_STREAM_MANIFEST_SHA256,
            "chunks": 85,
            "source_turns": 568,
            "stream_sha256": "f599b8d35f55ac08b68595f728aaa7a20f30e14a529c7dcb0f1631857b6594ec",
        },
        "prompt": {
            "prompt_contract_filename": "s3-management-prompt.json",
            "prompt_contract_sha256": EXPECTED_S3_PROMPT_CONTRACT_SHA256,
            "builder_version": BUILDER_PROMPT_VERSION,
            "builder_sha256": FROZEN_BUILDER_PROMPT_SHA256,
            "attribution_version": LOCOMO_ATTRIBUTION_VERSION,
            "attribution_sha256": FROZEN_LOCOMO_ATTRIBUTION_SHA256,
            "combined_version": MANAGEMENT_PROMPT_VERSION,
            "combined_sha256": FROZEN_MANAGEMENT_PROMPT_SHA256,
            "user_wrapper_version": S3_USER_WRAPPER_VERSION,
            "user_instruction_sha256": FROZEN_S3_USER_INSTRUCTION_SHA256,
            "user_template_sha256": FROZEN_S3_USER_TEMPLATE_SHA256,
        },
        "tools": {
            "profile": list(MANAGEMENT_PROFILE),
            "profile_sha256": FROZEN_MANAGEMENT_TOOL_PROFILE_SHA256,
            "ordered_schema_sha256": FROZEN_MANAGEMENT_TOOL_SCHEMA_SHA256,
            "schema_serialization": "canonical JSON: UTF-8, sorted keys, compact separators",
            "wire_order_compact_sha256": FROZEN_MANAGEMENT_TOOL_WIRE_SHA256,
            "wire_serialization": (
                "JSON list in profile order: UTF-8, insertion-order keys, compact separators"
            ),
            "provenance": (
                "paper Table 12 descriptions/parameters/required; complete function wrapper "
                "is the local reconstruction in fs_memory_lab.paper_tools"
            ),
        },
        "runtime_config": runtime_config,
        "runtime_config_sha256": FROZEN_MANAGEMENT_RUNTIME_CONFIG_SHA256,
        "safety_policy": {
            "formal_store_starts_empty": True,
            "one_new_agent_context_per_chunk": True,
            "filesystem_persists_between_chunks": True,
            "checkpoint_before_every_chunk": True,
            "incremental_events_fsynced": True,
            "failure_outputs_quarantined": True,
            "formal_outputs_published_only_after_global_gate": True,
            "commit_marker_published_last": True,
            "overwrite_existing_formal_artifacts": False,
            "per_episode_file_hash_inventories_recorded": True,
            "gold_inputs_exposed_to_agent_messages_or_tools": False,
            "image_urls_fetched": False,
            "publication_fsyncs_files_and_parent_directories": True,
            "resource_limits_enforced_after_every_tool_call": True,
            "uncited_list_or_table_fact_candidates_rejected": True,
        },
    }


def verify_s3_runtime_freeze() -> None:
    checks = {
        "management tool profile": (
            canonical_json_bytes(list(MANAGEMENT_PROFILE)),
            FROZEN_MANAGEMENT_TOOL_PROFILE_SHA256,
        ),
        "management tool schema": (
            canonical_json_bytes(management_tool_definitions()),
            FROZEN_MANAGEMENT_TOOL_SCHEMA_SHA256,
        ),
        "management tool wire schema": (
            json.dumps(
                management_tool_definitions(),
                ensure_ascii=False,
                allow_nan=False,
                separators=(",", ":"),
            ).encode("utf-8"),
            FROZEN_MANAGEMENT_TOOL_WIRE_SHA256,
        ),
        "management runtime config": (
            canonical_json_bytes(management_runtime_config()),
            FROZEN_MANAGEMENT_RUNTIME_CONFIG_SHA256,
        ),
    }
    for label, (payload, expected) in checks.items():
        actual = sha256_bytes(payload)
        if actual != expected:
            raise RuntimeError(
                f"Frozen {label} drifted: expected SHA-256 {expected}, got {actual}"
            )


verify_s3_runtime_freeze()
