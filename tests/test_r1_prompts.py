from __future__ import annotations

import json
from pathlib import Path

import pytest

from fs_memory_lab.paper_prompts import SEARCH_PROMPT
from fs_memory_lab.r1_prompts import (
    DERIVED_PROMPT_5,
    DERIVED_PROMPT_6,
    DERIVED_PROMPT_7,
    EVIDENCE_ONLY_USER_TEMPLATE,
    FROZEN_R1_PROMPT_SHA256,
    PAPER_PDF_SHA256,
    PUBLISHED_PROMPT_5,
    R1_PROMPT_PROFILES,
    current_prompt_hashes,
    verify_r1_prompts,
)


ROOT = Path(__file__).resolve().parents[1]
MANIFEST_PATH = ROOT / "docs/reproduction/r1-prompt-manifest.json"


def test_frozen_hashes_verify_and_prompt5_stays_compatible() -> None:
    verify_r1_prompts()
    assert current_prompt_hashes() == dict(FROZEN_R1_PROMPT_SHA256)
    assert PUBLISHED_PROMPT_5 == SEARCH_PROMPT


def test_profile_mapping_and_caps_are_frozen() -> None:
    expected = {
        "E1": ("S1", 7, 20),
        "E3": ("S2", 6, 20),
        "E5": ("S3", 5, 40),
    }
    assert {
        cell: (profile.store_id, profile.paper_prompt_number, profile.hard_round_cap)
        for cell, profile in R1_PROMPT_PROFILES.items()
    } == expected


@pytest.mark.parametrize(
    "prompt", [DERIVED_PROMPT_5, DERIVED_PROMPT_6, DERIVED_PROMPT_7]
)
def test_derived_prompts_enforce_evidence_only_boundary(prompt: str) -> None:
    required = (
        "never answer",
        "take_note",
        "finish_search",
        "observation_id",
        "not_found_after_global_fallback",
        "no_progress_after_global_fallback",
        "evidence_budget_reached",
        "round_limit",
        "protocol_failure",
        "Do not mix modes",
        "Never choose",
    )
    for phrase in required:
        assert phrase.casefold() in prompt.casefold()
    forbidden = (
        "answer NOW",
        "State the direct answer in your FIRST sentence",
        "commit to the option",
        "give the best-supported inference",
    )
    for phrase in forbidden:
        assert phrase not in prompt


def test_store_specific_routing_survives_controlled_redline() -> None:
    e1 = R1_PROMPT_PROFILES["E1"].derived_prompt
    e3 = R1_PROMPT_PROFILES["E3"].derived_prompt
    e5 = R1_PROMPT_PROFILES["E5"].derived_prompt
    assert "store is FLAT" in e1
    assert "grep two candidate sessions" in e1
    assert "folder names often reveal which sessions matter" in e3
    assert "grep two candidate topic folders" in e3
    assert "Names and descriptions often reveal" in e5
    assert "toc a candidate file" in e5


def test_user_template_has_question_only_and_no_gold_fields() -> None:
    assert EVIDENCE_ONLY_USER_TEMPLATE.count("{question}") == 1
    lowered = EVIDENCE_ONLY_USER_TEMPLATE.casefold()
    for forbidden in ("gold_answer", "gold_evidence", "category", "expected answer"):
        assert forbidden not in lowered


def test_manifest_agrees_with_code_and_primary_source() -> None:
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    assert manifest["primary_source"]["sha256"] == PAPER_PDF_SHA256
    hashes = current_prompt_hashes()
    for profile in manifest["profiles"]:
        number = profile["paper_prompt_number"]
        assert profile["published_sha256"] == hashes[f"published_prompt_{number}"]
        assert profile["derived_sha256"] == hashes[f"derived_prompt_{number}"]
    assert manifest["user_turn"]["sha256"] == hashes["evidence_only_user_template"]
    modified = manifest["redline_blocks"]
    assert modified["store_specific_routing_and_cost_guidance"] == (
        "paper_published_text_reused"
    )
    assert all(
        status.startswith("controlled_")
        for name, status in modified.items()
        if name != "store_specific_routing_and_cost_guidance"
    )
