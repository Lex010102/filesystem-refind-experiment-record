"""Frozen, read-only filesystem surface for R1 evidence retrieval.

The four function descriptions and parameter declarations are transcribed from
Filesystem-Based Memory for LLM Agents, Appendix C.4, Table 12.  The complete
JSON function wrapper, ordering, defaults and runtime semantics are local,
versioned reconstruction choices and are never described as author source code.
"""

from __future__ import annotations

import json
from types import MappingProxyType
from typing import Any

from .evidence import EvidenceValidationError, canonical_json_bytes, sha256_bytes
from .paper_tools import SEARCH_PROFILE, TOOL_DEFINITIONS


R1_FILESYSTEM_PROTOCOL_VERSION = "center-table12-readonly-v1"
R1_FILESYSTEM_TOOL_NAMES = ("view", "grep", "toc", "section_read")
FROZEN_R1_FILESYSTEM_TOOL_PROFILE_SHA256 = (
    "d100442f84ec64f3021b109e881c204612ffd813e136f5903801a24cee08a483"
)
FROZEN_R1_FILESYSTEM_TOOL_SCHEMA_SHA256 = (
    "6d9d68f047917d20adb9133168d5726233c9719dbefd54627e08827832d963c6"
)
FROZEN_R1_FILESYSTEM_TOOL_WIRE_SHA256 = (
    "d6130495f85e19afadbe39529268c6b9659756e57b87c4a8dbb7c4627dae6d1b"
)
FROZEN_R1_PROJECT_DEFAULTS_SHA256 = (
    "59a34c9754baa8d5e25ced312677cc93db22fd2f68594abce11fea9cfc41152d"
)

# Table 12 marks only the fields present in each schema's ``required`` array.
# It does not publish executable-language defaults for omitted optional fields.
# These values preserve the existing local harness behavior and are disclosed as
# project-defined rather than paper-specified.
R1_PROJECT_DEFAULTS = MappingProxyType(
    {
        "view": MappingProxyType({"start_line": 1, "end_line": -1}),
        "grep": MappingProxyType(
            {"path": "/memories", "case_sensitive": False, "max_results": 100}
        ),
        "toc": MappingProxyType({}),
        "section_read": MappingProxyType({}),
    }
)


def _current_schema_payload() -> list[dict[str, Any]]:
    if tuple(SEARCH_PROFILE) != R1_FILESYSTEM_TOOL_NAMES:
        raise EvidenceValidationError("R1 paper tool profile changed")
    try:
        selected = [TOOL_DEFINITIONS[name] for name in R1_FILESYSTEM_TOOL_NAMES]
    except KeyError as exc:  # pragma: no cover - defensive import-time drift guard
        raise EvidenceValidationError(f"R1 paper tool is missing: {exc}") from exc
    # Validate as canonical JSON, then detach while preserving the insertion order
    # used on the provider wire.  Canonical and wire hashes are frozen separately.
    canonical_json_bytes(selected)
    return json.loads(
        json.dumps(selected, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
    )


def r1_filesystem_tool_profile_sha256() -> str:
    return sha256_bytes(canonical_json_bytes(list(R1_FILESYSTEM_TOOL_NAMES)))


def r1_filesystem_tool_schema_sha256() -> str:
    """Return the hash of the exact ordered wire schemas currently selected."""
    return sha256_bytes(canonical_json_bytes(_current_schema_payload()))


def r1_filesystem_tool_wire_sha256() -> str:
    payload = json.dumps(
        _current_schema_payload(),
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
    ).encode("utf-8")
    return sha256_bytes(payload)


def r1_project_defaults_sha256() -> str:
    return sha256_bytes(canonical_json_bytes(R1_PROJECT_DEFAULTS))


def verify_r1_filesystem_tool_freeze() -> None:
    checks = {
        "profile": (
            r1_filesystem_tool_profile_sha256(),
            FROZEN_R1_FILESYSTEM_TOOL_PROFILE_SHA256,
        ),
        "ordered schema": (
            r1_filesystem_tool_schema_sha256(),
            FROZEN_R1_FILESYSTEM_TOOL_SCHEMA_SHA256,
        ),
        "wire schema": (
            r1_filesystem_tool_wire_sha256(),
            FROZEN_R1_FILESYSTEM_TOOL_WIRE_SHA256,
        ),
        "project defaults": (
            r1_project_defaults_sha256(),
            FROZEN_R1_PROJECT_DEFAULTS_SHA256,
        ),
    }
    for label, (actual, expected) in checks.items():
        if actual != expected:
            raise EvidenceValidationError(
                f"Reviewed R1 filesystem {label} changed without a hash update"
            )


def r1_filesystem_tool_schemas() -> list[dict[str, Any]]:
    """Return a detached schema copy, failing closed if reviewed bytes drifted."""
    verify_r1_filesystem_tool_freeze()
    return _current_schema_payload()
