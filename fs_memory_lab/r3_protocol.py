"""Frozen method contract for E6 R3 / R2-Curated retrieval.

R3 keeps the ReFind-style ranking/controller contract but adapts its hierarchy
to the immutable S3 Markdown store.  This module performs no file loading and
never creates a provider request.
"""

from __future__ import annotations

from types import MappingProxyType
from typing import Any, Mapping

from .evidence import EvidenceValidationError, canonical_json_bytes, sha256_bytes
from .r2_protocol import R2_OFFICIAL_CODE_COMMIT, R2_RUNTIME_LIMITS


R3_PROTOCOL_VERSION = "r3-curated-refind-inspired-v1"
R3_CELL_ID = "E6"
R3_STORE_ID = "s3"

R3_INPUT_IDENTITY: Mapping[str, Any] = MappingProxyType(
    {
        "artifact_id": "locomo/conv-50/s3-curated/v1",
        "relative_root": "experiments/locomo-conv50-v1/stores/s3-curated",
        "manifest_relative_path": (
            "experiments/locomo-conv50-v1/manifests/s3-curated.json"
        ),
        "committed_relative_path": (
            "experiments/locomo-conv50-v1/manifests/s3-curated.COMMITTED"
        ),
        "manifest_sha256": (
            "70fb5ad56ff11bb849ce60b193cd6db29be601e613ca3afb76aac336e3b36e00"
        ),
        "s3_runner_tree_sha256": (
            "60cb8dac74bfb60de500d1721f385c13f5d0b5819420600e24ba40ba10f27acd"
        ),
        "shared_snapshot_tree_sha256": (
            "983238fddc77a88ef4ae3d06b50bcfd25a429f497e89c6af4d9477cefca9cad2"
        ),
        "expected_files": 2,
        "expected_bytes": 304_640,
        "expected_lines": 472,
        "expected_h1": 2,
        "expected_h2_groups": 35,
        "expected_fact_units": 390,
        "expected_nested_fact_units": 3,
        "expected_body_locator_mentions": 1_459,
        "expected_unique_locators": 555,
        "expected_source_locators": 568,
        "expected_missing_source_locators": 13,
        "expected_frontmatter_locator_mentions_excluded": 6,
    }
)

R3_PARAMETERS: Mapping[str, Any] = MappingProxyType(
    {
        "unit": "locator-bearing-markdown-list-item",
        "group": "relative-path-plus-h2-ordinal",
        "frontmatter_in_index": False,
        "h1_role": "entity-name",
        "h2_role": "topic-group",
        "nested_list_items_are_units": True,
        "unit_without_locator_policy": "reject-formal-snapshot",
        "search_text_fields": ("entity_name", "h2_heading", "fact_without_locators"),
        "path_in_bm25": False,
        "path_visible_in_observation": True,
        "bm25_k1": 1.2,
        "bm25_b": 0.75,
        "rrf_smoothing": 60,
        "group_score": "sum-positive-eligible-unit-bm25",
        "top_k": 5,
        "context_window": 2,
        "agent_action_cap": 4,
        "date_format": "YYYY/MM/DD",
        "date_bounds": "inclusive",
        "multi_date_semantics": "source-date-set-overlap",
        "date_filter_stage": "before-scoring-and-ranking",
        "seen_scope": "h2-group",
        "observation_overlap": "preserve-independent-numbered-blocks",
        "bundle_overlap": "transitive-merge-same-path-overlap-or-adjacency",
        "stage1_max_completion_tokens": 4096,
        "temperature": 0,
        "formal_requested_model_alias": "coding",
        "formal_local_api_style": "portable",
        "portable_omits_reasoning_effort": True,
        "portable_omits_max_completion_tokens": True,
    }
)

R3_RUNTIME_LIMITS: Mapping[str, Any] = MappingProxyType(dict(R2_RUNTIME_LIMITS))

R3_SOURCE_CLASSIFICATION: Mapping[str, str] = MappingProxyType(
    {
        "s3_agent_curated_store": "filesystem-paper-method-local-reproduction",
        "bm25_parameters": "refind-paper",
        "tokenizer_implementation": "refind-author-code-pinned",
        "unit_group_rrf": "refind-core-with-project-curated-adapter",
        "top_k_context_seen_group": "refind-core-with-project-curated-adapter",
        "fact_bullet_unit": "project-defined-curated-adapter",
        "file_h2_group": "project-defined-curated-adapter",
        "taxonomy_aware_search_text": "project-defined-curated-adapter",
        "multi_date_set_overlap": "project-defined-temporal-adapter",
        "stable_ids_nested_list_parser": "project-defined",
        "source_locator_attribution": "project-defined",
        "overlap_merge_evidence_budget": "project-defined-shared-contract",
        "three_react_actions": "refind-paper-with-project-evidence-only-contract",
        "nus_model_alias": "local-model-substitution",
        "nus_portable_wire_profile": "local-gateway-substitution",
    }
)

FROZEN_R3_PROTOCOL_SHA256 = (
    "0535a229b856dd73be89f4b617dfb9c046e9bde178e9e6689f3ac062397b0878"
)


def r3_protocol_body() -> dict[str, Any]:
    return {
        "protocol_version": R3_PROTOCOL_VERSION,
        "official_refind_code_commit": R2_OFFICIAL_CODE_COMMIT,
        "cell_id": R3_CELL_ID,
        "store_id": R3_STORE_ID,
        "input_identity": dict(R3_INPUT_IDENTITY),
        "parameters": {
            key: list(value) if isinstance(value, tuple) else value
            for key, value in R3_PARAMETERS.items()
        },
        "runtime_limits": {
            key: list(value) if isinstance(value, tuple) else value
            for key, value in R3_RUNTIME_LIMITS.items()
        },
        "source_classification": dict(R3_SOURCE_CLASSIFICATION),
    }


def r3_protocol_sha256() -> str:
    return sha256_bytes(canonical_json_bytes(r3_protocol_body()))


def verify_r3_protocol() -> None:
    if R3_CELL_ID != "E6" or R3_STORE_ID != "s3":
        raise EvidenceValidationError("R3 must map exactly to E6/S3")
    if (
        int(R3_INPUT_IDENTITY["expected_unique_locators"])
        + int(R3_INPUT_IDENTITY["expected_missing_source_locators"])
        != int(R3_INPUT_IDENTITY["expected_source_locators"])
    ):
        raise EvidenceValidationError("R3 locator coverage identity is inconsistent")
    if R3_PARAMETERS["formal_local_api_style"] != "portable":
        raise EvidenceValidationError("R3 formal local API style must be portable")
    if R3_PARAMETERS["multi_date_semantics"] != "source-date-set-overlap":
        raise EvidenceValidationError("R3 formal multi-date semantics changed")
    if r3_protocol_sha256() != FROZEN_R3_PROTOCOL_SHA256:
        raise EvidenceValidationError(
            "Reviewed R3 protocol changed without a frozen hash update"
        )
