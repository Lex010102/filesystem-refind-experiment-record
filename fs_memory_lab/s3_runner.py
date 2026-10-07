"""Fail-closed builder and verifier for the formal S3 curated memory store."""

from __future__ import annotations

import copy
import hashlib
import json
import os
import re
import secrets
import shutil
import subprocess
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from .agent import (AgentRunError, AgentRunner, ChatProvider,
                    CompatibleChatProvider, EpisodeResult)
from .filesystem import MemoryFS, ToolError
from .management_prompt import MANAGEMENT_PROMPT
from .paper_config import MANAGEMENT, RANDOM_SEED
from .paper_tools import MANAGEMENT_PROFILE
from .s3_protocol import render_s3_user_message
from .s3_runtime import (
    EXPECTED_S3_PROMPT_CONTRACT_SHA256,
    EXPECTED_S3_RUNTIME_CONTRACT_SHA256,
    EXPECTED_S3_SERVED_MODEL,
    EXPECTED_S3_STREAM_MANIFEST_SHA256,
    FROZEN_MANAGEMENT_RUNTIME_CONFIG_SHA256,
    FROZEN_MANAGEMENT_TOOL_PROFILE_SHA256,
    FROZEN_MANAGEMENT_TOOL_SCHEMA_SHA256,
    LOCAL_S3_PROVIDER_PROFILE,
    S3_RESOURCE_LIMITS,
    S3_RUNNER_VERSION,
    canonical_json_bytes,
    runtime_contract_document,
    sha256_bytes,
    verify_s3_runtime_freeze,
)


S3_BUILD_SCHEMA_VERSION = 1
S3_ARTIFACT_ID = "locomo/conv-50/s3-curated/v1"
S3_TEST_ARTIFACT_ID = "locomo/conv-50/s3-curated/test-v1"
_RUN_ID = re.compile(r"[0-9]{8}T[0-9]{12}Z-[a-f0-9]{8}\Z")
_CHUNK_FILENAME = re.compile(r"session_\d+_chunk_\d+\.txt\Z")
_LOCATOR = re.compile(r"\[S(\d+)T(\d+)\]\Z")
_SOURCE_LINE = re.compile(r"(?m)^(\[S\d+T\d+\]) \(dia_id: (D\d+:\d+)\)$")
_LOCATOR_CANDIDATE = re.compile(
    r"\[(?:S\d+[^\]\n]*|S[A-Za-z]*T\d+[^\]\n]*)\]"
)
_CROSS_REFERENCE = re.compile(r"/memories/[^\n\[\]>]*?\.md")
_SECTION_REFERENCE = re.compile(
    r"(?P<path>/memories/(?:(?!/memories/)[^\n\[\]>])*?\.md)\s*>\s*"
    r"(?P<tail>[^\n\[]+)"
)
_HEADING = re.compile(r"^#{1,6}\s+", re.MULTILINE)
_HEADING_LINE = re.compile(r"^(#{1,6})\s+.+$")
_LIST_FACT_LINE = re.compile(r"^\s*(?:[-+*]\s+|\d+[.)]\s+)\S")
_LEGACY_RUNTIME_CONFIG_BY_CONTRACT = {
    # Runner v2: post-tool locator feedback, before cross-reference feedback/resume.
    "36b043ad7cc0afcab45d671e42f3e03b8ed339c3486bd396d2820d9d72c94f4a":
        "434d4dccd181668e2a2d0e4f1c13136c3611d6188b7acbf25d0df4af04864183",
    # Runner v3: validated resume and cross-reference repair, before compaction retries.
    "f9f02a125edad9fd16a1e2c9117e392b81794101c8a570312b2c04f46579389f":
        "434d4dccd181668e2a2d0e4f1c13136c3611d6188b7acbf25d0df4af04864183",
    # Runner v4: compaction-only timeout retries, before ordinary request retries.
    "bd3f429a532056513c0893b108023ad96a1bf5be4a74c9c419c4fd5293593eb5":
        "612fa89e9212ebec6c1cd78d44ad88388c53f5d801bd751fd78a6c3308a37005",
}
_LEGACY_RESUMABLE_RUNTIME_CONTRACTS = set(_LEGACY_RUNTIME_CONFIG_BY_CONTRACT)


class S3BuildError(RuntimeError):
    """Raised when an S3 build or verification cannot proceed safely."""


def _runtime_config_sha_for_contract(contract_sha256: str) -> str:
    if contract_sha256 == EXPECTED_S3_RUNTIME_CONTRACT_SHA256:
        return FROZEN_MANAGEMENT_RUNTIME_CONFIG_SHA256
    legacy = _LEGACY_RUNTIME_CONFIG_BY_CONTRACT.get(contract_sha256)
    if legacy is None:
        raise S3BuildError("Runtime contract is not approved for S3 resume")
    return legacy


def _approved_runtime_config_lineage() -> tuple[str, ...]:
    ordered = [*_LEGACY_RUNTIME_CONFIG_BY_CONTRACT.values(),
               FROZEN_MANAGEMENT_RUNTIME_CONFIG_SHA256]
    return tuple(dict.fromkeys(ordered))


def _validate_prefix_runtime_config_segments(
    value: Any, *, start_chunk: int, source_runtime_contract_sha256: str
) -> dict[int, str]:
    if not isinstance(value, list):
        raise S3BuildError("S3 resume runtime segments must be a list")
    lineage = _approved_runtime_config_lineage()
    source_config = _runtime_config_sha_for_contract(
        source_runtime_contract_sha256
    )
    source_rank = lineage.index(source_config)
    previous_rank = -1
    expected_start = 1
    by_chunk: dict[int, str] = {}
    for segment in value:
        if not isinstance(segment, dict) or set(segment) != {
            "start_chunk", "end_chunk", "runtime_config_sha256"
        }:
            raise S3BuildError("S3 resume runtime segment is invalid")
        first = segment.get("start_chunk")
        last = segment.get("end_chunk")
        runtime_config = segment.get("runtime_config_sha256")
        if (
            not isinstance(first, int)
            or isinstance(first, bool)
            or not isinstance(last, int)
            or isinstance(last, bool)
            or first != expected_start
            or last < first
            or last >= start_chunk
            or runtime_config not in lineage
        ):
            raise S3BuildError("S3 resume runtime segment bounds are invalid")
        rank = lineage.index(str(runtime_config))
        if rank < previous_rank or rank > source_rank:
            raise S3BuildError("S3 resume runtime segment lineage is invalid")
        previous_rank = rank
        by_chunk.update({index: str(runtime_config) for index in range(first, last + 1)})
        expected_start = last + 1
    if expected_start != start_chunk:
        raise S3BuildError("S3 resume runtime segments do not cover the prefix")
    if value and value[-1]["runtime_config_sha256"] != source_config:
        raise S3BuildError("S3 resume runtime segments do not end at the source runtime")
    return by_chunk


@dataclass(frozen=True)
class S3StreamSnapshot:
    root: Path
    manifest: dict[str, Any]
    manifest_sha256: str
    artifact_id: str
    chunks: list[dict[str, Any]]
    all_locators: frozenset[str]
    stream_sha256: str
    total_bytes: int


@dataclass(frozen=True)
class S3StoreGate:
    files: dict[str, dict[str, Any]]
    directories: list[str]
    source_index: dict[str, list[dict[str, Any]]]
    tree_sha256: str
    total_bytes: int
    total_lines: int
    heading_count: int
    locator_mentions: int
    unique_locators: int
    cross_reference_count: int
    max_depth: int


@dataclass(frozen=True)
class S3ResumePrefix:
    run_id: str
    run_dir: Path
    start_chunk: int
    started_at: str
    episodes: list[dict[str, Any]]
    checkpoint: Path
    previous_checkpoint: Path | None
    reconstructed_events: bytes
    prefix_runtime_config_segments: list[dict[str, Any]]
    source_runtime_contract_sha256: str
    source_code_revision: str
    resumed_at: str


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _pretty_json_bytes(value: Any) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, allow_nan=False, indent=2, sort_keys=True)
        + "\n"
    ).encode("utf-8")


def _atomic_write(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp-{secrets.token_hex(4)}")
    try:
        with temporary.open("xb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        _fsync_directory(path.parent)
    finally:
        temporary.unlink(missing_ok=True)


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _fsync_tree(root: Path) -> None:
    """Durably flush one non-symlink file tree before publishing its name."""
    if root.is_symlink() or not root.is_dir():
        raise S3BuildError(f"Cannot fsync non-directory tree: {root}")
    paths = list(root.rglob("*"))
    if any(path.is_symlink() for path in paths):
        raise S3BuildError(f"Cannot fsync a tree containing symlinks: {root}")
    for path in (item for item in paths if item.is_file()):
        with path.open("rb") as handle:
            os.fsync(handle.fileno())
    directories = sorted(
        (item for item in paths if item.is_dir()),
        key=lambda item: len(item.parts),
        reverse=True,
    )
    for directory in directories:
        _fsync_directory(directory)
    _fsync_directory(root)


def _load_json_object(path: Path, label: str) -> tuple[dict[str, Any], bytes]:
    if path.is_symlink() or not path.is_file():
        raise S3BuildError(f"{label} must be an existing non-symlink file")
    try:
        payload = path.read_bytes()
        value = json.loads(payload.decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise S3BuildError(f"Cannot read {label}: {exc}") from exc
    if not isinstance(value, dict):
        raise S3BuildError(f"{label} must contain one JSON object")
    return value, payload


def _redact_text(text: str) -> str:
    text = re.sub(r"\b(?:clsk|sk)[_-][A-Za-z0-9_-]{10,}\b", "[REDACTED_KEY]", text)
    text = re.sub(r"\bBearer\s+\S+", "Bearer [REDACTED_KEY]", text, flags=re.IGNORECASE)
    return " ".join(text.split())[:800]


def _redact_value(value: Any) -> Any:
    if isinstance(value, str):
        return _redact_text(value)
    if isinstance(value, list):
        return [_redact_value(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _redact_value(item) for key, item in value.items()}
    return value


def _usage_totals(usage: list[dict[str, Any]]) -> dict[str, int]:
    totals: dict[str, int] = {}
    for record in usage:
        if not isinstance(record, dict):
            continue
        for key, value in record.items():
            if isinstance(value, int) and not isinstance(value, bool):
                totals[key] = totals.get(key, 0) + value
    return dict(sorted(totals.items()))


def _safe_endpoint(provider: ChatProvider) -> str | None:
    endpoint = getattr(provider, "endpoint", None)
    if not isinstance(endpoint, str):
        return None
    parsed = urlsplit(endpoint)
    host = parsed.hostname or ""
    if parsed.port is not None:
        host += f":{parsed.port}"
    return f"{parsed.scheme}://{host}{parsed.path}"


def _validate_provider_profile(provider: ChatProvider) -> dict[str, Any]:
    actual = {
        "api_style": getattr(provider, "api_style", None),
        "endpoint": _safe_endpoint(provider),
        "max_response_bytes": getattr(provider, "max_response_bytes", None),
        "requested_model": getattr(provider, "model", None) or MANAGEMENT.model,
        "request_timeout_seconds": getattr(provider, "timeout", None),
    }
    if actual != LOCAL_S3_PROVIDER_PROFILE:
        raise S3BuildError(
            "Provider profile does not match the frozen local S3 runtime contract; "
            f"expected {LOCAL_S3_PROVIDER_PROFILE}, got {actual}"
        )
    return actual


def _assert_code_stable(repo_root: Path, code_revision: str) -> None:
    """Require the committed implementation to stay fixed during a formal run."""
    resolved = Path(repo_root).resolve()
    try:
        current = subprocess.run(
            ["git", "-C", str(resolved), "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        tracked_status = subprocess.run(
            [
                "git",
                "-C",
                str(resolved),
                "status",
                "--porcelain",
                "--untracked-files=no",
            ],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError) as exc:
        raise S3BuildError(f"Cannot verify Git state for formal S3 build: {exc}") from exc
    if current != code_revision or tracked_status:
        raise S3BuildError(
            "Committed S3 implementation changed during the run; refusing publication"
        )


def _validate_prompt_contract(path: Path) -> tuple[dict[str, Any], str]:
    document, payload = _load_json_object(path, "S3 prompt contract")
    digest = sha256_bytes(payload)
    if digest != EXPECTED_S3_PROMPT_CONTRACT_SHA256:
        raise S3BuildError(
            "S3 prompt contract hash mismatch: "
            f"expected {EXPECTED_S3_PROMPT_CONTRACT_SHA256}, got {digest}"
        )
    combined = document.get("system_prompt", {}).get("combined", {})
    if combined.get("sha256") != sha256_bytes(MANAGEMENT_PROMPT.encode("utf-8")):
        raise S3BuildError("S3 prompt contract does not match the active management prompt")
    if tuple(document.get("management_tool_profile", [])) != MANAGEMENT_PROFILE:
        raise S3BuildError("S3 prompt contract tool profile mismatch")
    return document, digest


def _validate_runtime_contract(path: Path) -> tuple[dict[str, Any], str]:
    document, payload = _load_json_object(path, "S3 runtime contract")
    digest = sha256_bytes(payload)
    if digest != EXPECTED_S3_RUNTIME_CONTRACT_SHA256:
        raise S3BuildError(
            "S3 runtime contract hash mismatch: "
            f"expected {EXPECTED_S3_RUNTIME_CONTRACT_SHA256}, got {digest}"
        )
    if document != runtime_contract_document():
        raise S3BuildError("S3 runtime contract differs from the reviewed runtime document")
    return document, digest


def validate_s3_stream(stream_dir: Path, manifest_path: Path) -> S3StreamSnapshot:
    """Recompute the complete frozen chunk stream before any model call."""
    raw_root = Path(stream_dir)
    if raw_root.is_symlink() or not raw_root.is_dir():
        raise S3BuildError("S3 stream must be an existing non-symlink directory")
    root = raw_root.resolve(strict=False)
    manifest, manifest_payload = _load_json_object(Path(manifest_path), "S3 stream manifest")
    manifest_sha256 = sha256_bytes(manifest_payload)
    if manifest_sha256 != EXPECTED_S3_STREAM_MANIFEST_SHA256:
        raise S3BuildError(
            "S3 stream manifest hash mismatch: "
            f"expected {EXPECTED_S3_STREAM_MANIFEST_SHA256}, got {manifest_sha256}"
        )
    if manifest.get("schema_version") != 1:
        raise S3BuildError("Unsupported S3 stream manifest schema")
    artifact_id = manifest.get("artifact_id")
    if artifact_id != "locomo/conv-50/s3-management-stream/v1":
        raise S3BuildError("Unexpected S3 stream artifact_id")
    chunks = manifest.get("chunks")
    source_index = manifest.get("source_index")
    if not isinstance(chunks, list) or not chunks or not isinstance(source_index, dict):
        raise S3BuildError("S3 stream manifest is missing chunks or source_index")

    entries = list(root.iterdir())
    if any(path.is_symlink() or not path.is_file() for path in entries):
        raise S3BuildError("S3 stream directory must contain only regular files")
    actual = {path.name: path for path in entries}
    expected_names: set[str] = set()
    ordered_index: list[dict[str, str]] = []
    flattened_locators: list[str] = []
    total_bytes = 0
    total_characters = 0
    sessions: set[int] = set()

    for expected_index, chunk in enumerate(chunks, start=1):
        if not isinstance(chunk, dict) or chunk.get("global_chunk_index") != expected_index:
            raise S3BuildError("S3 chunks are not in contiguous global order")
        filename = chunk.get("filename")
        if not isinstance(filename, str) or _CHUNK_FILENAME.fullmatch(filename) is None:
            raise S3BuildError(f"Invalid S3 chunk filename: {filename!r}")
        if filename in expected_names:
            raise S3BuildError(f"Duplicate S3 chunk filename: {filename}")
        expected_names.add(filename)
        path = actual.get(filename)
        if path is None:
            raise S3BuildError(f"Missing S3 chunk file: {filename}")
        payload = path.read_bytes()
        try:
            text = payload.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise S3BuildError(f"S3 chunk is not UTF-8: {filename}") from exc
        digest = sha256_bytes(payload)
        if (
            digest != chunk.get("sha256")
            or len(payload) != chunk.get("bytes")
            or len(text) != chunk.get("characters")
        ):
            raise S3BuildError(f"S3 chunk bytes/hash/character mismatch: {filename}")
        declared_locators = chunk.get("locators")
        declared_dia_ids = chunk.get("dia_ids")
        if not isinstance(declared_locators, list) or not isinstance(declared_dia_ids, list):
            raise S3BuildError(f"S3 chunk source ids are invalid: {filename}")
        source_lines = _SOURCE_LINE.findall(text)
        if [item[0] for item in source_lines] != declared_locators:
            raise S3BuildError(f"S3 chunk locator sequence mismatch: {filename}")
        if [item[1] for item in source_lines] != declared_dia_ids:
            raise S3BuildError(f"S3 chunk dia_id sequence mismatch: {filename}")
        if len(declared_locators) != chunk.get("turn_count"):
            raise S3BuildError(f"S3 chunk turn count mismatch: {filename}")
        for ordinal, locator in enumerate(declared_locators, start=1):
            entry = source_index.get(locator)
            if (
                not isinstance(entry, dict)
                or entry.get("chunk_file") != filename
                or entry.get("global_chunk_index") != expected_index
                or entry.get("ordinal_in_chunk") != ordinal
            ):
                raise S3BuildError(f"S3 source_index mismatch for {locator}")
        flattened_locators.extend(declared_locators)
        ordered_index.append({"filename": filename, "sha256": digest})
        total_bytes += len(payload)
        total_characters += len(text)
        if not isinstance(chunk.get("session_index"), int):
            raise S3BuildError(f"S3 chunk session index is invalid: {filename}")
        sessions.add(chunk["session_index"])

    if set(actual) != expected_names:
        raise S3BuildError(
            f"S3 stream file set mismatch; extra={sorted(set(actual) - expected_names)[:5]}"
        )
    if len(flattened_locators) != len(set(flattened_locators)):
        raise S3BuildError("S3 stream repeats a source locator")
    if set(flattened_locators) != set(source_index):
        raise S3BuildError("S3 stream source_index does not match chunk locators")
    stream_sha256 = sha256_bytes(canonical_json_bytes(ordered_index))
    stream = manifest.get("stream", {})
    counts = manifest.get("counts", {})
    if stream.get("ordered_index") != ordered_index or stream.get("sha256") != stream_sha256:
        raise S3BuildError("S3 ordered stream hash mismatch")
    if (
        counts.get("chunks") != len(chunks)
        or counts.get("source_turns") != len(flattened_locators)
        or counts.get("sessions") != len(sessions)
        or counts.get("bytes") != total_bytes
        or counts.get("characters") != total_characters
    ):
        raise S3BuildError("S3 stream counts mismatch")
    if manifest.get("input", {}).get("gold_bearing_files_read") is not False:
        raise S3BuildError("S3 stream does not carry the required gold-isolation declaration")
    return S3StreamSnapshot(
        root=root,
        manifest=manifest,
        manifest_sha256=manifest_sha256,
        artifact_id=artifact_id,
        chunks=copy.deepcopy(chunks),
        all_locators=frozenset(flattened_locators),
        stream_sha256=stream_sha256,
        total_bytes=total_bytes,
    )


def _prune_empty_directories(root: Path) -> list[str]:
    pruned: list[str] = []
    directories = sorted(
        (path for path in root.rglob("*") if path.is_dir() and not path.is_symlink()),
        key=lambda path: len(path.relative_to(root).parts),
        reverse=True,
    )
    for directory in directories:
        try:
            directory.rmdir()
        except OSError:
            continue
        pruned.append(directory.relative_to(root).as_posix())
    return sorted(pruned)


def _validate_resource_limits(root: Path) -> dict[str, int]:
    """Apply the frozen local ceilings without interpreting memory contents."""
    root = Path(root)
    if root.is_symlink() or not root.is_dir():
        raise S3BuildError("S3 store must be an existing non-symlink directory")
    paths = list(root.rglob("*"))
    if any(path.is_symlink() for path in paths):
        raise S3BuildError("S3 store contains a symlink")
    if any(
        part.startswith(".")
        for path in paths
        for part in path.relative_to(root).parts
    ):
        raise S3BuildError("S3 store contains a hidden path")
    directories = [path for path in paths if path.is_dir()]
    files = [path for path in paths if path.is_file()]
    if len(directories) + len(files) != len(paths):
        raise S3BuildError("S3 store contains a non-regular filesystem entry")
    sizes = [path.stat().st_size for path in files]
    max_depth = max(
        (len(path.relative_to(root).parts) - 1 for path in files),
        default=0,
    )
    stats = {
        "directories": len(directories),
        "files": len(files),
        "max_directory_depth": max(
            [len(path.relative_to(root).parts) for path in directories]
            + [max_depth],
        ),
        "max_file_bytes": max(sizes, default=0),
        "paths": len(paths),
        "total_bytes": sum(sizes),
    }
    comparisons = {
        "directories": "max_directories",
        "files": "max_files",
        "max_directory_depth": "max_directory_depth",
        "max_file_bytes": "max_file_bytes",
        "paths": "max_paths",
        "total_bytes": "max_total_bytes",
    }
    for measured, ceiling in comparisons.items():
        if stats[measured] > S3_RESOURCE_LIMITS[ceiling]:
            raise S3BuildError(
                f"S3 resource limit exceeded: {measured}={stats[measured]} > "
                f"{S3_RESOURCE_LIMITS[ceiling]}"
            )
    return stats


def _resolved_section_reference(text: str, tail: str) -> str | None:
    """Return the unique longest heading path at the start of a reference tail."""
    stack: list[str] = []
    candidate_counts: dict[str, int] = {}
    for line in text.splitlines():
        match = _HEADING_LINE.fullmatch(line.strip())
        if match is None:
            continue
        level = len(match.group(1))
        stack = stack[: level - 1]
        stack.append(line.strip())
        for start in range(len(stack)):
            candidate = " > ".join(stack[start:])
            candidate_counts[candidate] = candidate_counts.get(candidate, 0) + 1
    normalized_tail = tail.strip()
    for candidate in sorted(candidate_counts, key=len, reverse=True):
        if not normalized_tail.startswith(candidate):
            continue
        remainder = normalized_tail[len(candidate):].strip()
        if remainder and re.fullmatch(r"[.,;:!?)}]+", remainder) is None:
            continue
        if candidate_counts[candidate] == 1:
            return candidate
        return None
    return None


def validate_incremental_source_locators(
    root: Path,
    allowed_locators: frozenset[str] | set[str],
) -> int:
    """Reject every malformed/future locator while allowing transient cross-links.

    This is intentionally narrower than ``validate_curated_store`` so two files
    created in one parallel tool response may temporarily cross-reference a file
    that has not been created yet.  It runs after every tool action and returns
    all locator errors together so the agent can repair its own write before it
    finishes the episode.  The strict full store gate still runs afterwards.
    """
    raw_root = Path(root)
    if raw_root.is_symlink() or not raw_root.is_dir():
        raise S3BuildError("S3 store must be an existing non-symlink directory")
    root = raw_root.resolve(strict=False)
    _validate_resource_limits(root)
    issues: list[str] = []
    mentions = 0
    for path in sorted(root.rglob("*")):
        if path.is_dir():
            continue
        relative = path.relative_to(root).as_posix()
        if path.is_symlink() or not path.is_file() or path.suffix != ".md":
            issues.append(f"invalid memory entry {relative}")
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            issues.append(f"unreadable UTF-8 memory file {relative}: {exc}")
            continue
        for line_number, line in enumerate(text.splitlines(), start=1):
            for token in _LOCATOR_CANDIDATE.findall(line):
                if _LOCATOR.fullmatch(token) is None:
                    issues.append(
                        f"{relative}:L{line_number} malformed source locator {token!r}"
                    )
                elif token not in allowed_locators:
                    issues.append(
                        f"{relative}:L{line_number} unknown or future source locator {token}"
                    )
                else:
                    mentions += 1
    if issues:
        unique = list(dict.fromkeys(issues))
        limit = S3_RESOURCE_LIMITS["max_locator_diagnostics_per_tool"]
        displayed = unique[:limit]
        suffix = (
            f"; plus {len(unique) - limit} more; inspect the listed files"
            if len(unique) > limit
            else ""
        )
        raise S3BuildError("; ".join(displayed) + suffix)
    return mentions


def validate_incremental_cross_references(root: Path) -> int:
    """Report broken filesystem links immediately after a tool action.

    A parallel tool response may create a source file before its target file.  The
    write therefore remains applied and the diagnostic is returned to the same
    Agent as a repairable tool error.  The episode-level store gate remains the
    authority: it must still pass after all calls finish.
    """
    raw_root = Path(root)
    if raw_root.is_symlink() or not raw_root.is_dir():
        raise S3BuildError("S3 store must be an existing non-symlink directory")
    root = raw_root.resolve(strict=False)
    _validate_resource_limits(root)
    entries = list(root.rglob("*"))
    relative_files = {
        path.relative_to(root).as_posix(): path
        for path in entries
        if path.is_file() and not path.is_symlink() and path.suffix == ".md"
    }
    issues: list[str] = []
    references = 0
    for relative, path in sorted(relative_files.items()):
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            issues.append(f"unreadable UTF-8 memory file {relative}: {exc}")
            continue
        for match in _CROSS_REFERENCE.finditer(text):
            reference = match.group(0)
            line_number = text.count("\n", 0, match.start()) + 1
            target = relative_files.get(reference[len("/memories/"):])
            if target is None:
                issues.append(
                    f"{relative}:L{line_number} broken cross-reference {reference}"
                )
            references += 1
        for match in _SECTION_REFERENCE.finditer(text):
            reference = match.group("path")
            tail = match.group("tail").strip()
            line_number = text.count("\n", 0, match.start()) + 1
            target = relative_files.get(reference[len("/memories/"):])
            if target is None:
                # The path diagnostic above already identifies the missing file.
                continue
            target_text = target.read_text(encoding="utf-8")
            if _resolved_section_reference(target_text, tail) is not None:
                continue
            headings = [
                line.strip()
                for line in target_text.splitlines()
                if _HEADING_LINE.fullmatch(line.strip()) is not None
            ]
            available = ", ".join(repr(value) for value in headings[:20])
            if len(headings) > 20:
                available += f", plus {len(headings) - 20} more"
            issues.append(
                f"{relative}:L{line_number} broken or ambiguous section "
                f"cross-reference {reference} > {tail!r}; exact headings in target: "
                f"{available or '(none)'}"
            )
    if issues:
        unique = list(dict.fromkeys(issues))
        limit = S3_RESOURCE_LIMITS["max_locator_diagnostics_per_tool"]
        displayed = unique[:limit]
        suffix = (
            f"; plus {len(unique) - limit} more; inspect the listed files"
            if len(unique) > limit
            else ""
        )
        raise S3BuildError("; ".join(displayed) + suffix)
    return references


def validate_curated_store(
    root: Path,
    allowed_locators: frozenset[str] | set[str],
    *,
    allow_empty: bool = False,
) -> S3StoreGate:
    """Validate structure, frontmatter, locators and cross-references."""
    raw_root = Path(root)
    if raw_root.is_symlink() or not raw_root.is_dir():
        raise S3BuildError("S3 store must be an existing non-symlink directory")
    root = raw_root.resolve(strict=False)
    _validate_resource_limits(root)
    paths = list(root.rglob("*"))
    if any(path.is_symlink() for path in paths):
        raise S3BuildError("S3 store contains a symlink")
    directories = sorted(path for path in paths if path.is_dir())
    regular_files = sorted(path for path in paths if path.is_file())
    if len(directories) + len(regular_files) != len(paths):
        raise S3BuildError("S3 store contains a non-regular filesystem entry")
    if any(path.suffix != ".md" for path in regular_files):
        raise S3BuildError("S3 store contains a non-Markdown file")
    if not regular_files and not allow_empty:
        raise S3BuildError("S3 store is empty")

    relative_files = {path.relative_to(root).as_posix(): path for path in regular_files}
    files: dict[str, dict[str, Any]] = {}
    source_index: dict[str, list[dict[str, Any]]] = {}
    total_bytes = 0
    total_lines = 0
    heading_count = 0
    locator_mentions = 0
    cross_reference_count = 0

    for relative, path in sorted(relative_files.items()):
        payload = path.read_bytes()
        try:
            text = payload.decode("utf-8")
            MemoryFS._validate(path, text)
        except (UnicodeDecodeError, ToolError) as exc:
            raise S3BuildError(f"S3 memory file is invalid: {relative}: {exc}") from exc
        line_count = len(text.splitlines())
        headings = len(_HEADING.findall(text))
        candidates = _LOCATOR_CANDIDATE.findall(text)
        locators: list[str] = []
        for token in candidates:
            if _LOCATOR.fullmatch(token) is None:
                raise S3BuildError(f"Malformed source locator {token!r} in {relative}")
            if token not in allowed_locators:
                raise S3BuildError(f"Unknown or future source locator {token} in {relative}")
            locators.append(token)
        lines = text.splitlines()
        try:
            frontmatter_end = lines.index("---", 1)
        except ValueError as exc:
            raise S3BuildError(f"S3 memory file has incomplete frontmatter: {relative}") from exc
        table_separators = {
            index
            for index, line in enumerate(lines)
            if line.strip().startswith("|")
            and not line.strip().strip("|:- ")
        }
        for index, line in enumerate(lines):
            if index <= frontmatter_end or not line.strip():
                continue
            stripped = line.strip()
            list_candidate = _LIST_FACT_LINE.match(line) is not None
            table_candidate = stripped.startswith("|") and stripped.endswith("|")
            if table_candidate and (
                index in table_separators or index + 1 in table_separators
            ):
                table_candidate = False
            if not (list_candidate or table_candidate):
                continue
            line_locators = _LOCATOR_CANDIDATE.findall(line)
            if not any(_LOCATOR.fullmatch(token) for token in line_locators):
                raise S3BuildError(
                    f"Uncited list/table fact candidate in {relative}:L{index + 1}"
                )
        cross_references = sorted(set(_CROSS_REFERENCE.findall(text)))
        for reference in cross_references:
            target = reference[len("/memories/"):]
            if target not in relative_files:
                raise S3BuildError(f"Broken cross-reference {reference} in {relative}")
        section_cross_references: list[str] = []
        for match in _SECTION_REFERENCE.finditer(text):
            reference = match.group("path")
            tail = match.group("tail").strip()
            target = relative_files.get(reference[len("/memories/"):])
            target_text = target.read_text(encoding="utf-8") if target is not None else ""
            section = _resolved_section_reference(target_text, tail)
            if section is None:
                raise S3BuildError(
                    f"Broken or ambiguous section cross-reference {reference} > {tail} in {relative}"
                )
            section_cross_references.append(f"{reference} > {section}")
        for line_number, line in enumerate(lines, start=1):
            for locator in _LOCATOR_CANDIDATE.findall(line):
                source_index.setdefault(locator, []).append(
                    {"file": relative, "line": line_number}
                )
        files[relative] = {
            "bytes": len(payload),
            "cross_references": cross_references,
            "headings": headings,
            "lines": line_count,
            "locator_mentions": len(locators),
            "sha256": sha256_bytes(payload),
            "section_cross_references": sorted(set(section_cross_references)),
            "unique_locators": sorted(set(locators)),
        }
        total_bytes += len(payload)
        total_lines += line_count
        heading_count += headings
        locator_mentions += len(locators)
        cross_reference_count += len(cross_references)

    tree_sha256 = sha256_bytes(
        canonical_json_bytes({name: files[name]["sha256"] for name in sorted(files)})
    )
    max_depth = max((len(Path(name).parts) - 1 for name in files), default=0)
    return S3StoreGate(
        files=files,
        directories=[path.relative_to(root).as_posix() for path in directories],
        source_index={key: source_index[key] for key in sorted(source_index)},
        tree_sha256=tree_sha256,
        total_bytes=total_bytes,
        total_lines=total_lines,
        heading_count=heading_count,
        locator_mentions=locator_mentions,
        unique_locators=len(source_index),
        cross_reference_count=cross_reference_count,
        max_depth=max_depth,
    )


def _ensure_distinct_paths(paths: dict[str, Path]) -> dict[str, Path]:
    raw = {name: Path(path) for name, path in paths.items()}
    for name, path in raw.items():
        if path.is_symlink():
            raise S3BuildError(f"{name} must not be a symlink")
    resolved = {name: path.resolve(strict=False) for name, path in raw.items()}
    for left_name, left in resolved.items():
        for right_name, right in resolved.items():
            if left_name >= right_name:
                continue
            if left == right:
                raise S3BuildError(f"Paths for {left_name} and {right_name} must be distinct")
    readonly = {"stream_dir", "stream_manifest", "prompt_contract", "runtime_contract"}
    writable = set(resolved) - readonly
    for writable_name in writable:
        target = resolved[writable_name]
        for readonly_name in readonly:
            source = resolved[readonly_name]
            if target == source or target in source.parents or source in target.parents:
                raise S3BuildError(
                    f"Writable path {writable_name} must be isolated from {readonly_name}"
                )
    isolated_directories = ("s3_store", "trace_dir", "work_root")
    for index, left_name in enumerate(isolated_directories):
        left = resolved[left_name]
        for right_name in isolated_directories[index + 1:]:
            right = resolved[right_name]
            if left in right.parents or right in left.parents:
                raise S3BuildError(
                    f"{left_name} and {right_name} must not contain one another"
                )
    for name in ("s3_manifest", "commit_marker"):
        artifact = resolved[name]
        for directory_name in ("s3_store", "trace_dir", "work_root"):
            directory = resolved[directory_name]
            if artifact == directory or artifact in directory.parents or directory in artifact.parents:
                raise S3BuildError(f"{name} must live outside {directory_name}")
    return resolved


def _preflight_targets(paths: dict[str, Path]) -> None:
    for name in ("s3_store", "s3_manifest", "trace_dir", "commit_marker"):
        if paths[name].exists() or paths[name].is_symlink():
            raise S3BuildError(f"Refusing to overwrite existing {name}: {paths[name]}")
    lock = paths["s3_store"].parent / f".{paths['s3_store'].name}.lock"
    if lock.exists() or lock.is_symlink():
        raise S3BuildError(f"An S3 build lock already exists: {lock}")


def preflight_s3_build(
    stream_dir: Path,
    stream_manifest: Path,
    prompt_contract: Path,
    runtime_contract: Path,
    s3_store: Path,
    s3_manifest: Path,
    trace_dir: Path,
    commit_marker: Path,
    work_root: Path | None = None,
) -> dict[str, Any]:
    try:
        verify_s3_runtime_freeze()
    except RuntimeError as exc:
        raise S3BuildError(str(exc)) from exc
    paths = _ensure_distinct_paths(
        {
            "stream_dir": stream_dir,
            "stream_manifest": stream_manifest,
            "prompt_contract": prompt_contract,
            "runtime_contract": runtime_contract,
            "s3_store": s3_store,
            "s3_manifest": s3_manifest,
            "trace_dir": trace_dir,
            "commit_marker": commit_marker,
            "work_root": work_root
            if work_root is not None
            else Path(s3_store).parent / ".preflight-work-root-placeholder",
        }
    )
    _preflight_targets(paths)
    stream = validate_s3_stream(paths["stream_dir"], paths["stream_manifest"])
    _, prompt_hash = _validate_prompt_contract(paths["prompt_contract"])
    _, runtime_hash = _validate_runtime_contract(paths["runtime_contract"])
    return {
        "status": "ready",
        "source_artifact_id": stream.artifact_id,
        "stream_manifest_sha256": stream.manifest_sha256,
        "stream_sha256": stream.stream_sha256,
        "prompt_contract_sha256": prompt_hash,
        "runtime_contract_sha256": runtime_hash,
        "management_prompt_sha256": sha256_bytes(MANAGEMENT_PROMPT.encode("utf-8")),
        "tool_profile": list(MANAGEMENT_PROFILE),
        "tool_profile_sha256": FROZEN_MANAGEMENT_TOOL_PROFILE_SHA256,
        "tool_schema_sha256": FROZEN_MANAGEMENT_TOOL_SCHEMA_SHA256,
        "runtime_config_sha256": FROZEN_MANAGEMENT_RUNTIME_CONFIG_SHA256,
        "chunks": len(stream.chunks),
        "source_turns": len(stream.all_locators),
        "bytes": stream.total_bytes,
        "provider_profile_required_at_build": dict(LOCAL_S3_PROVIDER_PROFILE),
    }


def _acquire_lock(path: Path, run_id: str) -> tuple[bytes, int]:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError as exc:
        raise S3BuildError(f"An S3 build lock already exists: {path}") from exc
    payload = _pretty_json_bytes({"run_id": run_id, "created_at": _utc_now()})
    inode = -1
    try:
        inode = os.fstat(descriptor).st_ino
        written = 0
        while written < len(payload):
            count = os.write(descriptor, payload[written:])
            if count <= 0:
                raise OSError("short write while creating S3 build lock")
            written += count
        os.fsync(descriptor)
    except BaseException as exc:
        try:
            if inode >= 0 and not path.is_symlink() and path.stat().st_ino == inode:
                path.unlink()
        except OSError:
            pass
        if isinstance(exc, (KeyboardInterrupt, SystemExit)):
            raise
        raise S3BuildError("Cannot create durable S3 build lock") from None
    finally:
        os.close(descriptor)
    return payload, inode


def _release_owned_lock(path: Path, payload: bytes, inode: int) -> bool:
    try:
        if path.is_symlink() or not path.is_file() or path.stat().st_ino != inode:
            return False
        if path.read_bytes() != payload:
            return False
        path.unlink()
        return True
    except OSError:
        return False


def _publish_file_temporary(final_path: Path, payload: bytes, run_id: str) -> Path:
    final_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = final_path.with_name(f".{final_path.name}.publish-{run_id}")
    if temporary.exists() or temporary.is_symlink():
        raise S3BuildError(f"Publish temporary already exists: {temporary}")
    try:
        with temporary.open("xb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise
    return temporary


def _safe_unlink_current_run(path: Path, expected_payload: bytes) -> None:
    if path.is_file() and not path.is_symlink() and path.read_bytes() == expected_payload:
        path.unlink()


def _directory_tree_sha256(root: Path) -> str:
    if root.is_symlink() or not root.is_dir():
        raise S3BuildError(f"Expected a regular directory: {root}")
    files = sorted(path for path in root.rglob("*") if path.is_file() and not path.is_symlink())
    if any(path.is_symlink() for path in root.rglob("*")):
        raise S3BuildError(f"Directory contains a symlink: {root}")
    index = {
        path.relative_to(root).as_posix(): sha256_bytes(path.read_bytes()) for path in files
    }
    return sha256_bytes(canonical_json_bytes(index))


def _directory_total_bytes(root: Path) -> int:
    if not root.exists():
        return 0
    if root.is_symlink() or not root.is_dir():
        raise S3BuildError(f"Expected a regular directory for size accounting: {root}")
    paths = list(root.rglob("*"))
    if any(path.is_symlink() for path in paths):
        raise S3BuildError(f"Directory contains a symlink during size accounting: {root}")
    return sum(path.stat().st_size for path in paths if path.is_file())


def _episode_document(
    result: EpisodeResult,
    chunk: dict[str, Any],
    user_message: str,
    *,
    run_id: str,
    started_at: str,
    finished_at: str,
    store_before: S3StoreGate,
    store_after: S3StoreGate,
    checkpoint: str,
) -> dict[str, Any]:
    before_files = {
        name: metadata["sha256"] for name, metadata in store_before.files.items()
    }
    after_files = {
        name: metadata["sha256"] for name, metadata in store_after.files.items()
    }
    before_names = set(before_files)
    after_names = set(after_files)
    return {
        "schema_version": 1,
        "status": "completed",
        "run_id": run_id,
        "started_at": started_at,
        "finished_at": finished_at,
        "chunk": {
            "filename": chunk["filename"],
            "global_chunk_index": chunk["global_chunk_index"],
            "payload_sha256": chunk["sha256"],
            "locators": chunk["locators"],
            "user_message_sha256": sha256_bytes(user_message.encode("utf-8")),
        },
        "protocol": {
            "management_prompt_sha256": sha256_bytes(MANAGEMENT_PROMPT.encode("utf-8")),
            "runtime_config_sha256": FROZEN_MANAGEMENT_RUNTIME_CONFIG_SHA256,
            "tool_profile_sha256": FROZEN_MANAGEMENT_TOOL_PROFILE_SHA256,
            "tool_schema_sha256": FROZEN_MANAGEMENT_TOOL_SCHEMA_SHA256,
        },
        "checkpoint": checkpoint,
        "store_before_sha256": store_before.tree_sha256,
        "store_after_sha256": store_after.tree_sha256,
        "store_files_before": before_files,
        "store_files_after": after_files,
        "store_diff": {
            "added": sorted(after_names - before_names),
            "modified": sorted(
                name
                for name in before_names & after_names
                if before_files[name] != after_files[name]
            ),
            "removed": sorted(before_names - after_names),
        },
        "user_message": user_message,
        "result": {
            "answer": result.answer,
            "rounds": result.rounds,
            "tool_calls": result.tool_calls,
            "usage": result.usage,
            "trace": result.trace,
            "role": result.role,
            "configuration": result.configuration,
            "prompt_sha256": result.prompt_sha256,
            "input_sha256": result.input_sha256,
        },
    }


def _validate_episode_provider_metadata(result: EpisodeResult) -> None:
    response_events = [
        event
        for event in result.trace
        if isinstance(event, dict)
        and ("assistant_content" in event or event.get("compaction") is True)
    ]
    if not response_events:
        raise S3BuildError("S3 episode has no recorded provider response")
    for event in response_events:
        served = event.get("served_model")
        if served != EXPECTED_S3_SERVED_MODEL:
            raise S3BuildError(
                "S3 provider backend changed or was not reported: "
                f"expected {EXPECTED_S3_SERVED_MODEL!r}, got {served!r}"
            )
        if event.get("compaction") is True:
            if event.get("finish_reason") != "stop":
                raise S3BuildError("S3 context compaction did not finish cleanly")
            summary = event.get("summary")
            if (
                not isinstance(summary, str)
                or not summary.strip()
                or event.get("summary_sha256")
                != sha256_bytes(summary.encode("utf-8"))
                or not re.fullmatch(r"[0-9a-f]{64}", str(event.get("input_sha256")))
            ):
                raise S3BuildError("S3 context compaction trace is incomplete")
        elif "assistant_content" in event:
            finish_reason = event.get("finish_reason")
            has_calls = bool(event.get("tool_calls"))
            expected_reasons = {"tool_calls"} if has_calls else {"stop"}
            if finish_reason not in expected_reasons:
                raise S3BuildError(
                    "S3 provider returned an unexpected finish_reason: "
                    f"{finish_reason!r}"
                )


def _aggregate_model_metadata(
    provider: ChatProvider, episodes: list[dict[str, Any]]
) -> dict[str, Any]:
    served_models: set[str] = set()
    fingerprints: set[str] = set()
    for episode in episodes:
        for event in episode["result"]["trace"]:
            served = event.get("served_model")
            fingerprint = event.get("system_fingerprint")
            if isinstance(served, str) and served:
                served_models.add(served)
            if isinstance(fingerprint, str) and fingerprint:
                fingerprints.add(fingerprint)
    return {
        "paper_configuration": asdict(MANAGEMENT),
        "requested_model": getattr(provider, "model", None) or MANAGEMENT.model,
        "served_models": sorted(served_models),
        "system_fingerprints": sorted(fingerprints),
        "api_style": getattr(provider, "api_style", None),
        "endpoint": _safe_endpoint(provider),
        "sampling": {
            "configured_random_seed": RANDOM_SEED,
            "seed_sent_to_provider": False,
            "note": "The compatible API adapter does not send a seed parameter.",
        },
    }


def _build_cost(episodes: list[dict[str, Any]]) -> dict[str, Any]:
    usage: list[dict[str, Any]] = []
    tool_calls = 0
    rounds = 0
    llm_calls = 0
    for episode in episodes:
        result = episode["result"]
        usage.extend(result["usage"])
        tool_calls += result["tool_calls"]
        rounds += result["rounds"]
        llm_calls += sum(
            1
            for event in result["trace"]
            if "assistant_content" in event or event.get("compaction") is True
        )
    return {
        "episodes": len(episodes),
        "llm_calls": llm_calls,
        "rounds": rounds,
        "tool_calls": tool_calls,
        "usage_totals": _usage_totals(usage),
    }


def _load_resume_prefix(
    work_root: Path,
    run_id: str,
    stream: S3StreamSnapshot,
    *,
    prompt_contract_sha256: str,
    source_code_revision: str,
    test_mode: bool,
) -> S3ResumePrefix:
    """Validate an entire failed-run prefix before permitting an API resume."""
    if _RUN_ID.fullmatch(run_id) is None:
        raise S3BuildError("Resume run id is invalid")
    revision_pattern = r"test-[a-z0-9-]+" if test_mode else r"[0-9a-f]{40}"
    if re.fullmatch(revision_pattern, source_code_revision) is None:
        raise S3BuildError("Resume source code revision has the wrong form")
    run_dir = work_root / run_id
    if run_dir.is_symlink() or not run_dir.is_dir():
        raise S3BuildError(f"Resume run directory is missing: {run_dir}")
    failure, _ = _load_json_object(run_dir / "failure.json", "S3 failed-run record")
    state, _ = _load_json_object(run_dir / "run-state.json", "S3 failed-run state")
    if (
        failure.get("schema_version") != 1
        or failure.get("status") != "failed"
        or failure.get("run_id") != run_id
        or failure.get("formal_outputs_published") is not False
        or failure.get("residual_formal_outputs") != []
        or failure.get("cleanup_errors") != []
        or failure.get("checkpoints_retained") is not True
    ):
        raise S3BuildError("Failed-run record is not safe to resume")
    start_chunk = failure.get("current_chunk")
    if (
        not isinstance(start_chunk, int)
        or isinstance(start_chunk, bool)
        or not 1 <= start_chunk <= len(stream.chunks)
        or state.get("schema_version") != 1
        or state.get("run_id") != run_id
        or state.get("current_chunk") != start_chunk
        or state.get("stream_manifest_sha256") != stream.manifest_sha256
        or state.get("prompt_contract_sha256") != prompt_contract_sha256
    ):
        raise S3BuildError("Failed-run state does not match the frozen stream")
    source_runtime_hash = state.get("runtime_contract_sha256")
    if source_runtime_hash not in (
        _LEGACY_RESUMABLE_RUNTIME_CONTRACTS
        | {EXPECTED_S3_RUNTIME_CONTRACT_SHA256}
    ):
        raise S3BuildError("Failed run used an unapproved runtime contract")
    source_runtime_config_hash = _runtime_config_sha_for_contract(
        str(source_runtime_hash)
    )

    trace_source = run_dir / "quarantine" / "trace"
    if trace_source.is_symlink() or not trace_source.is_dir():
        raise S3BuildError("Failed-run trace quarantine is missing")
    trace_paths = list(trace_source.iterdir())
    if any(path.is_symlink() or not path.is_file() for path in trace_paths):
        raise S3BuildError("Failed-run trace quarantine must contain regular files only")
    expected_trace_names = {
        f"episode-{index:03d}.json" for index in range(1, start_chunk)
    }
    if {path.name for path in trace_paths} != expected_trace_names:
        raise S3BuildError("Failed-run completed episode set is not a contiguous prefix")

    episode_protocol_base = {
        "management_prompt_sha256": sha256_bytes(MANAGEMENT_PROMPT.encode("utf-8")),
        "tool_profile_sha256": FROZEN_MANAGEMENT_TOOL_PROFILE_SHA256,
        "tool_schema_sha256": FROZEN_MANAGEMENT_TOOL_SCHEMA_SHA256,
    }
    runtime_lineage = _approved_runtime_config_lineage()
    source_runtime_rank = runtime_lineage.index(source_runtime_config_hash)
    previous_runtime_rank = -1
    prefix_runtime_config_segments: list[dict[str, Any]] = []
    prior_store_sha = sha256_bytes(canonical_json_bytes({}))
    prior_store_files: dict[str, str] = {}
    episodes: list[dict[str, Any]] = []
    event_rows: list[dict[str, Any]] = []
    for chunk in stream.chunks[: start_chunk - 1]:
        index = chunk["global_chunk_index"]
        filename = f"episode-{index:03d}.json"
        episode, _ = _load_json_object(trace_source / filename, filename)
        payload = (stream.root / chunk["filename"]).read_text(encoding="utf-8")
        user_message = render_s3_user_message(payload)
        episode_chunk = episode.get("chunk", {})
        episode_protocol = episode.get("protocol")
        episode_runtime_config = (
            episode_protocol.get("runtime_config_sha256")
            if isinstance(episode_protocol, dict)
            else None
        )
        if episode_runtime_config not in runtime_lineage:
            raise S3BuildError(f"Resume episode runtime is unapproved: {filename}")
        episode_runtime_rank = runtime_lineage.index(str(episode_runtime_config))
        if (
            episode_runtime_rank < previous_runtime_rank
            or episode_runtime_rank > source_runtime_rank
        ):
            raise S3BuildError(f"Resume episode runtime lineage is invalid: {filename}")
        previous_runtime_rank = episode_runtime_rank
        expected_episode_protocol = {
            **episode_protocol_base,
            "runtime_config_sha256": episode_runtime_config,
        }
        if (
            episode.get("schema_version") != 1
            or episode.get("status") != "completed"
            or episode.get("run_id") != run_id
            or episode_protocol != expected_episode_protocol
            or episode.get("checkpoint") != f"checkpoints/chunk-{index:03d}-before"
            or episode_chunk.get("filename") != chunk["filename"]
            or episode_chunk.get("global_chunk_index") != index
            or episode_chunk.get("payload_sha256") != chunk["sha256"]
            or episode_chunk.get("locators") != chunk["locators"]
            or episode_chunk.get("user_message_sha256")
            != sha256_bytes(user_message.encode("utf-8"))
            or episode.get("user_message") != user_message
        ):
            raise S3BuildError(f"Resume episode identity mismatch: {filename}")
        if (
            not prefix_runtime_config_segments
            or prefix_runtime_config_segments[-1]["runtime_config_sha256"]
            != episode_runtime_config
        ):
            prefix_runtime_config_segments.append({
                "start_chunk": index,
                "end_chunk": index,
                "runtime_config_sha256": episode_runtime_config,
            })
        else:
            prefix_runtime_config_segments[-1]["end_chunk"] = index
        before_files = episode.get("store_files_before")
        after_files = episode.get("store_files_after")
        if (
            not isinstance(before_files, dict)
            or not isinstance(after_files, dict)
            or any(
                not isinstance(name, str)
                or re.fullmatch(r"[0-9a-f]{64}", str(digest)) is None
                for inventory in (before_files, after_files)
                for name, digest in inventory.items()
            )
            or before_files != prior_store_files
            or episode.get("store_before_sha256") != prior_store_sha
            or sha256_bytes(canonical_json_bytes(before_files)) != prior_store_sha
            or sha256_bytes(canonical_json_bytes(after_files))
            != episode.get("store_after_sha256")
        ):
            raise S3BuildError(f"Resume store hash chain is invalid: {filename}")
        before_names = set(before_files)
        after_names = set(after_files)
        expected_diff = {
            "added": sorted(after_names - before_names),
            "modified": sorted(
                name
                for name in before_names & after_names
                if before_files[name] != after_files[name]
            ),
            "removed": sorted(before_names - after_names),
        }
        if episode.get("store_diff") != expected_diff:
            raise S3BuildError(f"Resume store diff is invalid: {filename}")
        result = episode.get("result")
        if not isinstance(result, dict):
            raise S3BuildError(f"Resume result is invalid: {filename}")
        try:
            restored_result = EpisodeResult(
                answer=result["answer"],
                rounds=result["rounds"],
                tool_calls=result["tool_calls"],
                usage=result["usage"],
                trace=result["trace"],
                role=result["role"],
                configuration=result["configuration"],
                prompt_sha256=result["prompt_sha256"],
                input_sha256=result["input_sha256"],
            )
        except KeyError as exc:
            raise S3BuildError(f"Resume result is incomplete: {filename}") from exc
        assistant_events = [
            event
            for event in restored_result.trace
            if isinstance(event, dict) and "assistant_content" in event
        ]
        tool_events = [
            event
            for event in restored_result.trace
            if isinstance(event, dict) and "tool" in event
        ]
        if (
            restored_result.role != "management"
            or restored_result.configuration != asdict(MANAGEMENT)
            or restored_result.prompt_sha256
            != sha256_bytes(MANAGEMENT_PROMPT.encode("utf-8"))
            or restored_result.input_sha256
            != sha256_bytes(user_message.encode("utf-8"))
            or not isinstance(restored_result.answer, str)
            or not restored_result.answer.strip()
            or not isinstance(restored_result.rounds, int)
            or isinstance(restored_result.rounds, bool)
            or not 1 <= restored_result.rounds <= MANAGEMENT.max_rounds
            or len(assistant_events) != restored_result.rounds
            or not isinstance(restored_result.tool_calls, int)
            or isinstance(restored_result.tool_calls, bool)
            or restored_result.tool_calls < 0
            or len(tool_events) != restored_result.tool_calls
            or not isinstance(restored_result.usage, list)
        ):
            raise S3BuildError(f"Resume result metadata is invalid: {filename}")
        _validate_episode_provider_metadata(restored_result)
        event_rows.extend(
            {"event": "agent_trace", "chunk": index, **event}
            for event in restored_result.trace
        )
        episodes.append(episode)
        prior_store_files = after_files
        prior_store_sha = episode["store_after_sha256"]

    if episodes and prefix_runtime_config_segments[-1]["runtime_config_sha256"] != (
        source_runtime_config_hash
    ):
        raise S3BuildError("Resume prefix does not end with the failed run runtime")

    checkpoint = run_dir / "checkpoints" / f"chunk-{start_chunk:03d}-before"
    prefix_locators = {
        locator
        for chunk in stream.chunks[: start_chunk - 1]
        for locator in chunk["locators"]
    }
    checkpoint_gate = validate_curated_store(
        checkpoint, frozenset(prefix_locators), allow_empty=True
    )
    checkpoint_files = {
        name: metadata["sha256"] for name, metadata in checkpoint_gate.files.items()
    }
    if (
        checkpoint_gate.tree_sha256 != prior_store_sha
        or checkpoint_files != prior_store_files
    ):
        raise S3BuildError("Resume checkpoint does not match the validated episode prefix")
    previous_checkpoint = (
        run_dir / "checkpoints" / f"chunk-{start_chunk - 1:03d}-before"
        if start_chunk > 1
        else None
    )
    if previous_checkpoint is not None and (
        previous_checkpoint.is_symlink() or not previous_checkpoint.is_dir()
    ):
        raise S3BuildError("Resume rolling checkpoint predecessor is missing")

    raw_events = run_dir / "events.jsonl"
    if raw_events.is_symlink() or not raw_events.is_file():
        raise S3BuildError("Failed-run events log is missing")
    try:
        first_line = next(
            line for line in raw_events.read_text(encoding="utf-8").splitlines() if line
        )
        build_start = json.loads(first_line)
    except (StopIteration, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise S3BuildError("Failed-run build_start event is invalid") from exc
    if (
        not isinstance(build_start, dict)
        or build_start.get("event") != "build_start"
        or build_start.get("run_id") != run_id
        or not isinstance(build_start.get("time"), str)
        or not build_start["time"]
    ):
        raise S3BuildError("Failed-run build_start identity is invalid")
    reconstructed_events = b"".join(
        canonical_json_bytes(row) + b"\n" for row in [build_start, *event_rows]
    )
    return S3ResumePrefix(
        run_id=run_id,
        run_dir=run_dir,
        start_chunk=start_chunk,
        started_at=build_start["time"],
        episodes=episodes,
        checkpoint=checkpoint,
        previous_checkpoint=previous_checkpoint,
        reconstructed_events=reconstructed_events,
        prefix_runtime_config_segments=prefix_runtime_config_segments,
        source_runtime_contract_sha256=str(source_runtime_hash),
        source_code_revision=source_code_revision,
        resumed_at=_utc_now(),
    )


def build_s3_store(
    stream_dir: Path,
    stream_manifest: Path,
    prompt_contract: Path,
    runtime_contract: Path,
    s3_store: Path,
    s3_manifest: Path,
    trace_dir: Path,
    commit_marker: Path,
    work_root: Path,
    provider: ChatProvider,
    *,
    code_revision: str,
    code_dirty: bool,
    repo_root: Path | None = None,
    test_mode: bool = False,
    resume_run_id: str | None = None,
    resume_source_code_revision: str | None = None,
) -> dict[str, Any]:
    """Build all 85 episodes in staging and publish only after global validation."""
    if code_dirty:
        raise S3BuildError("Formal S3 build requires a clean committed Git worktree")
    if test_mode:
        if not re.fullmatch(r"test-[a-z0-9-]+", code_revision):
            raise S3BuildError("S3 test mode requires an explicit test-* code revision")
        target_artifact_id = S3_TEST_ARTIFACT_ID
    else:
        if re.fullmatch(r"[0-9a-f]{40}", code_revision) is None:
            raise S3BuildError("Formal S3 build requires a 40-character Git commit")
        if not isinstance(provider, CompatibleChatProvider):
            raise S3BuildError(
                "Formal S3 build requires the reviewed CompatibleChatProvider adapter"
            )
        if repo_root is None:
            raise S3BuildError("Formal S3 build requires repo_root for code stability checks")
        _assert_code_stable(repo_root, code_revision)
        target_artifact_id = S3_ARTIFACT_ID
    provider_profile = _validate_provider_profile(provider)
    preflight = preflight_s3_build(
        stream_dir,
        stream_manifest,
        prompt_contract,
        runtime_contract,
        s3_store,
        s3_manifest,
        trace_dir,
        commit_marker,
        work_root,
    )
    paths = _ensure_distinct_paths(
        {
            "stream_dir": stream_dir,
            "stream_manifest": stream_manifest,
            "prompt_contract": prompt_contract,
            "runtime_contract": runtime_contract,
            "s3_store": s3_store,
            "s3_manifest": s3_manifest,
            "trace_dir": trace_dir,
            "commit_marker": commit_marker,
            "work_root": work_root,
        }
    )
    stream = validate_s3_stream(paths["stream_dir"], paths["stream_manifest"])
    _, prompt_contract_hash = _validate_prompt_contract(paths["prompt_contract"])
    _, runtime_contract_hash = _validate_runtime_contract(paths["runtime_contract"])

    if (resume_run_id is None) != (resume_source_code_revision is None):
        raise S3BuildError(
            "Resume requires both run id and the attested source code revision"
        )
    run_id = resume_run_id or (
        datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ-") + secrets.token_hex(4)
    )
    if _RUN_ID.fullmatch(run_id) is None:
        raise S3BuildError("Internal S3 run id generation failed")
    run_dir = paths["work_root"] / run_id
    staging = paths["s3_store"].parent / f".{paths['s3_store'].name}.staging-{run_id}"
    trace_staging = paths["trace_dir"].parent / f".{paths['trace_dir'].name}.staging-{run_id}"
    lock_path = paths["s3_store"].parent / f".{paths['s3_store'].name}.lock"
    started_at = _utc_now()
    resume_prefix: S3ResumePrefix | None = None
    resume_metadata: dict[str, Any] | None = None
    current_state = "PRECHECK"
    current_chunk: int | None = None
    published_files: list[tuple[Path, bytes]] = []
    published_directories: list[tuple[Path, Path]] = []
    temporary_files: list[Path] = []
    release_lock = True
    runner: AgentRunner | None = None

    for parent in {
        paths["s3_store"].parent,
        paths["trace_dir"].parent,
        paths["s3_manifest"].parent,
        paths["commit_marker"].parent,
        paths["work_root"],
    }:
        parent.mkdir(parents=True, exist_ok=True)
    devices = {
        path.stat().st_dev
        for path in {
            paths["s3_store"].parent,
            paths["trace_dir"].parent,
            paths["s3_manifest"].parent,
            paths["commit_marker"].parent,
            paths["work_root"],
        }
    }
    if len(devices) != 1:
        raise S3BuildError("S3 staging, work and formal outputs must share one filesystem")

    if resume_run_id is not None:
        resume_prefix = _load_resume_prefix(
            paths["work_root"],
            resume_run_id,
            stream,
            prompt_contract_sha256=prompt_contract_hash,
            source_code_revision=str(resume_source_code_revision),
            test_mode=test_mode,
        )
        started_at = resume_prefix.started_at

    lock_payload, lock_inode = _acquire_lock(lock_path, run_id)
    try:
        for name in ("s3_store", "s3_manifest", "trace_dir", "commit_marker"):
            if paths[name].exists() or paths[name].is_symlink():
                raise S3BuildError(f"A formal artifact appeared while acquiring the lock: {name}")
        if resume_prefix is None:
            run_dir.mkdir(parents=False, exist_ok=False)
            (run_dir / "checkpoints").mkdir()
            staging.mkdir()
            trace_staging.mkdir()
        else:
            if staging.exists() or staging.is_symlink():
                raise S3BuildError("Resume staging store already exists")
            if trace_staging.exists() or trace_staging.is_symlink():
                raise S3BuildError("Resume staging trace already exists")
            shutil.copytree(resume_prefix.checkpoint, staging)
            trace_staging.mkdir()
            source_trace = run_dir / "quarantine" / "trace"
            for episode in resume_prefix.episodes:
                index = episode["chunk"]["global_chunk_index"]
                filename = f"episode-{index:03d}.json"
                shutil.copyfile(source_trace / filename, trace_staging / filename)
            suffix = 1
            while (run_dir / f"prior-failure-quarantine-{suffix:02d}").exists():
                suffix += 1
            os.rename(
                run_dir / "quarantine",
                run_dir / f"prior-failure-quarantine-{suffix:02d}",
            )
            os.rename(
                run_dir / "failure.json",
                run_dir / f"prior-failure-{suffix:02d}.json",
            )
            os.rename(
                run_dir / "events.jsonl",
                run_dir / f"prior-failure-events-{suffix:02d}.jsonl",
            )
            resume_metadata = {
                "resumed": True,
                "start_chunk": resume_prefix.start_chunk,
                "reused_completed_chunks": len(resume_prefix.episodes),
                "source_failed_run_id": run_id,
                "source_code_revision": resume_prefix.source_code_revision,
                "source_runtime_contract_sha256": (
                    resume_prefix.source_runtime_contract_sha256
                ),
                "prefix_runtime_config_segments": (
                    resume_prefix.prefix_runtime_config_segments
                ),
                "resume_runtime_contract_sha256": runtime_contract_hash,
                "resumed_at": resume_prefix.resumed_at,
            }

        def update_state(state: str, **extra: Any) -> None:
            nonlocal current_state
            current_state = state
            _atomic_write(
                run_dir / "run-state.json",
                _pretty_json_bytes(
                    {
                        "schema_version": 1,
                        "run_id": run_id,
                        "state": state,
                        "updated_at": _utc_now(),
                        "current_chunk": current_chunk,
                        "stream_manifest_sha256": stream.manifest_sha256,
                        "prompt_contract_sha256": prompt_contract_hash,
                        "runtime_contract_sha256": runtime_contract_hash,
                        **extra,
                    }
                ),
            )

        update_state("STAGED", resume=resume_metadata)
        event_path = run_dir / "events.jsonl"
        if resume_prefix is None:
            initial_events = canonical_json_bytes(
                {"event": "build_start", "run_id": run_id, "time": started_at}
            ) + b"\n"
        else:
            initial_events = resume_prefix.reconstructed_events
        _atomic_write(event_path, initial_events)

        def enforce_work_limits() -> None:
            event_bytes = event_path.stat().st_size if event_path.is_file() else 0
            trace_bytes = _directory_total_bytes(trace_staging)
            if not (trace_staging / "events.jsonl").is_file():
                trace_bytes += event_bytes
            if trace_bytes > S3_RESOURCE_LIMITS["max_trace_bytes"]:
                raise S3BuildError(
                    f"S3 trace limit exceeded: {trace_bytes} bytes"
                )
            work_bytes = (
                _directory_total_bytes(run_dir)
                + _directory_total_bytes(staging)
                + _directory_total_bytes(trace_staging)
            )
            if work_bytes > S3_RESOURCE_LIMITS["max_work_bytes"]:
                raise S3BuildError(
                    f"S3 run working-footprint limit exceeded: {work_bytes} bytes"
                )

        enforce_work_limits()
        memory = MemoryFS(staging, run_dir / "trash")
        episodes = list(resume_prefix.episodes) if resume_prefix is not None else []
        seen_locators = {
            locator
            for chunk in stream.chunks[: len(episodes)]
            for locator in chunk["locators"]
        }
        previous_checkpoint = (
            resume_prefix.previous_checkpoint if resume_prefix is not None else None
        )

        for chunk in stream.chunks[len(episodes):]:
            current_chunk = chunk["global_chunk_index"]
            episode_allowed_locators = frozenset(
                seen_locators.union(chunk["locators"])
            )
            checkpoint_name = f"chunk-{current_chunk:03d}-before"
            checkpoint = run_dir / "checkpoints" / checkpoint_name
            if resume_prefix is None or current_chunk != resume_prefix.start_chunk:
                shutil.copytree(staging, checkpoint)
            before_gate = validate_curated_store(
                staging, frozenset(seen_locators), allow_empty=True
            )
            checkpoint_sha256 = _directory_tree_sha256(checkpoint)
            if checkpoint_sha256 != before_gate.tree_sha256:
                raise S3BuildError("S3 diagnostic checkpoint does not match the store")
            enforce_work_limits()
            chunk_bytes = (stream.root / chunk["filename"]).read_bytes()
            if (
                sha256_bytes(chunk_bytes) != chunk["sha256"]
                or len(chunk_bytes) != chunk["bytes"]
            ):
                raise S3BuildError(
                    f"Frozen S3 chunk changed immediately before send: {chunk['filename']}"
                )
            try:
                payload = chunk_bytes.decode("utf-8")
            except UnicodeDecodeError as exc:
                raise S3BuildError(
                    f"Frozen S3 chunk is no longer UTF-8: {chunk['filename']}"
                ) from exc
            user_message = render_s3_user_message(payload)
            episode_started = _utc_now()

            def event_sink(event: dict[str, Any]) -> None:
                with event_path.open("ab") as handle:
                    handle.write(
                        canonical_json_bytes(
                            {
                                "event": "agent_trace",
                                "chunk": current_chunk,
                                **event,
                            }
                        )
                        + b"\n"
                    )
                    handle.flush()
                    os.fsync(handle.fileno())
                enforce_work_limits()

            def tool_hook(stage: str, name: str, args: dict[str, Any]) -> None:
                if stage == "raw":
                    raw_arguments = args.get("arguments")
                    if isinstance(raw_arguments, str):
                        argument_bytes = len(raw_arguments.encode("utf-8"))
                    else:
                        try:
                            argument_bytes = len(canonical_json_bytes(raw_arguments))
                        except (TypeError, ValueError) as exc:
                            raise S3BuildError(
                                f"Raw tool arguments are not JSON-compatible: {exc}"
                            ) from exc
                    if argument_bytes > S3_RESOURCE_LIMITS["max_tool_arguments_bytes"]:
                        raise S3BuildError(
                            f"S3 raw tool argument limit exceeded for {name}: "
                            f"{argument_bytes} bytes"
                        )
                    enforce_work_limits()
                    return
                if stage == "before":
                    try:
                        argument_bytes = len(canonical_json_bytes(args))
                    except (TypeError, ValueError) as exc:
                        raise S3BuildError(f"Tool arguments are not canonical JSON: {exc}") from exc
                    if argument_bytes > S3_RESOURCE_LIMITS["max_tool_arguments_bytes"]:
                        raise S3BuildError(
                            f"S3 tool argument limit exceeded for {name}: {argument_bytes} bytes"
                        )
                    return
                if stage != "after":
                    raise S3BuildError(f"Unknown S3 tool-hook stage: {stage}")
                _validate_resource_limits(staging)
                enforce_work_limits()
                try:
                    validate_incremental_source_locators(
                        staging, episode_allowed_locators
                    )
                except S3BuildError as exc:
                    raise ToolError(
                        "POST-WRITE S3 LOCATOR VALIDATION ERROR: the tool action was "
                        "applied, but every listed locator must be repaired before "
                        f"finishing the episode: {exc}"
                    ) from exc
                try:
                    validate_incremental_cross_references(staging)
                except S3BuildError as exc:
                    raise ToolError(
                        "POST-WRITE S3 CROSS-REFERENCE VALIDATION ERROR: the tool "
                        "action was applied, but every listed file or section link "
                        f"must be repaired before finishing the episode: {exc}"
                    ) from exc

            update_state("EPISODE_RUNNING", chunk_filename=chunk["filename"])
            runner = AgentRunner(
                memory,
                provider,
                max_rounds=MANAGEMENT.max_rounds,
                event_sink=event_sink,
                tool_hook=tool_hook,
                max_tool_calls_per_response=S3_RESOURCE_LIMITS[
                    "max_tool_calls_per_response"
                ],
                max_tool_calls_per_episode=S3_RESOURCE_LIMITS[
                    "max_tool_calls_per_episode"
                ],
            )
            result = runner.run("management", user_message)
            if result.prompt_sha256 != sha256_bytes(MANAGEMENT_PROMPT.encode("utf-8")):
                raise S3BuildError("AgentRunner used an unexpected management prompt")
            if result.input_sha256 != sha256_bytes(user_message.encode("utf-8")):
                raise S3BuildError("AgentRunner input hash mismatch")
            _validate_episode_provider_metadata(result)
            seen_locators.update(chunk["locators"])
            after_gate = validate_curated_store(
                staging, frozenset(seen_locators), allow_empty=True
            )
            episode_finished = _utc_now()
            episode = _episode_document(
                result,
                chunk,
                user_message,
                run_id=run_id,
                started_at=episode_started,
                finished_at=episode_finished,
                store_before=before_gate,
                store_after=after_gate,
                checkpoint=f"checkpoints/{checkpoint_name}",
            )
            episode_filename = f"episode-{current_chunk:03d}.json"
            episode_bytes = _pretty_json_bytes(episode)
            _atomic_write(trace_staging / episode_filename, episode_bytes)
            enforce_work_limits()
            episodes.append(episode)
            if previous_checkpoint is not None:
                shutil.rmtree(previous_checkpoint)
            previous_checkpoint = checkpoint
            update_state(
                "EPISODE_SUCCEEDED",
                chunk_filename=chunk["filename"],
                store_sha256=after_gate.tree_sha256,
            )

        current_chunk = None
        update_state("GLOBAL_GATE_RUNNING")
        pruned_empty_directories = _prune_empty_directories(staging)
        final_gate = validate_curated_store(staging, stream.all_locators)
        stream_after = validate_s3_stream(paths["stream_dir"], paths["stream_manifest"])
        if stream_after != stream:
            raise S3BuildError("Frozen S3 input stream changed during the model run")
        _, prompt_after = _validate_prompt_contract(paths["prompt_contract"])
        _, runtime_after = _validate_runtime_contract(paths["runtime_contract"])
        if prompt_after != prompt_contract_hash or runtime_after != runtime_contract_hash:
            raise S3BuildError("Frozen S3 contracts changed during the model run")
        if not test_mode:
            _assert_code_stable(Path(repo_root), code_revision)
        update_state("GLOBAL_GATE_PASSED", store_sha256=final_gate.tree_sha256)

        shutil.copyfile(event_path, trace_staging / "events.jsonl")
        enforce_work_limits()
        episode_index: list[dict[str, Any]] = []
        for episode in episodes:
            index = episode["chunk"]["global_chunk_index"]
            filename = f"episode-{index:03d}.json"
            episode_index.append(
                {
                    "filename": filename,
                    "global_chunk_index": index,
                    "chunk_filename": episode["chunk"]["filename"],
                    "sha256": sha256_bytes((trace_staging / filename).read_bytes()),
                    "store_before_sha256": episode["store_before_sha256"],
                    "store_after_sha256": episode["store_after_sha256"],
                }
            )
        finished_at = _utc_now()
        model_metadata = _aggregate_model_metadata(provider, episodes)
        build_cost = _build_cost(episodes)
        trace_index = {
            "schema_version": 1,
            "status": "completed",
            "run_id": run_id,
            "started_at": started_at,
            "finished_at": finished_at,
            "code_revision": code_revision,
            "protocol": {
                "stream_manifest_sha256": stream.manifest_sha256,
                "prompt_contract_sha256": prompt_contract_hash,
                "runtime_contract_sha256": runtime_contract_hash,
                "management_prompt_sha256": sha256_bytes(MANAGEMENT_PROMPT.encode("utf-8")),
                "system_prompt": MANAGEMENT_PROMPT,
                "runtime_config_sha256": FROZEN_MANAGEMENT_RUNTIME_CONFIG_SHA256,
                "tool_profile": list(MANAGEMENT_PROFILE),
                "tool_profile_sha256": FROZEN_MANAGEMENT_TOOL_PROFILE_SHA256,
                "tool_schema_sha256": FROZEN_MANAGEMENT_TOOL_SCHEMA_SHA256,
            },
            "model": model_metadata,
            "episodes": episode_index,
            "events": {
                "filename": "events.jsonl",
                "sha256": sha256_bytes((trace_staging / "events.jsonl").read_bytes()),
            },
            "build_cost": build_cost,
            "final_store_sha256": final_gate.tree_sha256,
        }
        if resume_metadata is not None:
            trace_index["resume"] = resume_metadata
        _atomic_write(trace_staging / "index.json", _pretty_json_bytes(trace_index))
        enforce_work_limits()
        trace_tree_sha256 = _directory_tree_sha256(trace_staging)
        _fsync_tree(staging)
        _fsync_tree(trace_staging)

        manifest_document = {
            "schema_version": S3_BUILD_SCHEMA_VERSION,
            "artifact_id": target_artifact_id,
            "generator": {
                "module": "fs_memory_lab.s3_runner",
                "version": S3_RUNNER_VERSION,
                "git_commit": code_revision,
            },
            "source": {
                "artifact_id": stream.artifact_id,
                "stream_manifest_sha256": stream.manifest_sha256,
                "stream_sha256": stream.stream_sha256,
                "prompt_contract_sha256": prompt_contract_hash,
                "runtime_contract_sha256": runtime_contract_hash,
            },
            "protocol": {
                "management_prompt_sha256": sha256_bytes(MANAGEMENT_PROMPT.encode("utf-8")),
                "runtime_config_sha256": FROZEN_MANAGEMENT_RUNTIME_CONFIG_SHA256,
                "tool_profile": list(MANAGEMENT_PROFILE),
                "tool_profile_sha256": FROZEN_MANAGEMENT_TOOL_PROFILE_SHA256,
                "tool_schema_sha256": FROZEN_MANAGEMENT_TOOL_SCHEMA_SHA256,
                "one_fresh_agent_context_per_chunk": True,
                "persistent_filesystem_across_chunks": True,
                "formal_store_started_empty": True,
                "gold_inputs_exposed_to_agent_messages_or_tools": False,
            },
            "model": model_metadata,
            "build": {
                "run_id": run_id,
                "mode": "test" if test_mode else "formal",
                "started_at": started_at,
                "finished_at": finished_at,
                "chunks_completed": len(episodes),
                "pruned_empty_directories": pruned_empty_directories,
            },
            "build_cost": build_cost,
            "counts": {
                "files": len(final_gate.files),
                "directories": len(final_gate.directories),
                "bytes": final_gate.total_bytes,
                "lines": final_gate.total_lines,
                "headings": final_gate.heading_count,
                "locator_mentions": final_gate.locator_mentions,
                "unique_locators_referenced": final_gate.unique_locators,
                "source_locators_available": len(stream.all_locators),
                "cross_references": final_gate.cross_reference_count,
                "max_file_depth": final_gate.max_depth,
            },
            "directories": final_gate.directories,
            "files": final_gate.files,
            "source_index": final_gate.source_index,
            "store": {
                "directory_name": paths["s3_store"].name,
                "tree_sha256": final_gate.tree_sha256,
            },
            "trace": {
                "directory_name": paths["trace_dir"].name,
                "index_filename": "index.json",
                "tree_sha256": trace_tree_sha256,
            },
            "verification": {
                "all_85_chunks_completed_in_order": len(episodes) == len(stream.chunks) == 85,
                "all_memory_files_valid_markdown_with_frontmatter": True,
                "all_stored_locators_exist_in_seen_source": True,
                "all_list_or_table_fact_candidates_have_inline_locator": True,
                "all_cross_references_resolve": True,
                "input_stream_revalidated_after_build": True,
                "contracts_revalidated_after_build": True,
                "gold_inputs_exposed_to_agent_messages_or_tools": False,
                "image_urls_fetched": False,
                "formal_outputs_published_from_staging": True,
            },
        }
        if resume_metadata is not None:
            manifest_document["build"]["resume"] = resume_metadata
        manifest_bytes = _pretty_json_bytes(manifest_document)
        marker_document = {
            "schema_version": 1,
            "artifact_id": target_artifact_id,
            "run_id": run_id,
            "committed_at": finished_at,
            "store_tree_sha256": final_gate.tree_sha256,
            "trace_tree_sha256": trace_tree_sha256,
            "manifest_sha256": sha256_bytes(manifest_bytes),
            "stream_manifest_sha256": stream.manifest_sha256,
            "prompt_contract_sha256": prompt_contract_hash,
            "runtime_contract_sha256": runtime_contract_hash,
        }
        marker_bytes = _pretty_json_bytes(marker_document)

        payloads = [
            (paths["s3_manifest"], manifest_bytes),
            (paths["commit_marker"], marker_bytes),
        ]
        for final, payload in payloads:
            temporary_files.append(_publish_file_temporary(final, payload, run_id))
        update_state("PUBLISHING")
        for name in ("s3_store", "trace_dir", "s3_manifest", "commit_marker"):
            if paths[name].exists() or paths[name].is_symlink():
                raise S3BuildError(f"A formal S3 artifact appeared during publication: {name}")
        os.rename(staging, paths["s3_store"])
        _fsync_directory(paths["s3_store"].parent)
        published_directories.append((paths["s3_store"], staging))
        os.rename(trace_staging, paths["trace_dir"])
        _fsync_directory(paths["trace_dir"].parent)
        published_directories.append((paths["trace_dir"], trace_staging))
        for temporary, (final, payload) in zip(temporary_files, payloads):
            os.rename(temporary, final)
            _fsync_directory(final.parent)
            published_files.append((final, payload))
        update_state("PUBLISHED", store_sha256=final_gate.tree_sha256)
        verification_report = verify_published_s3(
            paths["stream_dir"],
            paths["stream_manifest"],
            paths["prompt_contract"],
            paths["runtime_contract"],
            paths["s3_store"],
            paths["s3_manifest"],
            paths["trace_dir"],
            paths["commit_marker"],
            allow_test_artifact=test_mode,
        )
        shutil.rmtree(run_dir)
        return {
            "status": "published",
            "run_id": run_id,
            "source_artifact_id": stream.artifact_id,
            "target_artifact_id": target_artifact_id,
            "chunks": len(episodes),
            "files": len(final_gate.files),
            "directories": len(final_gate.directories),
            "store_tree_sha256": final_gate.tree_sha256,
            "trace_tree_sha256": trace_tree_sha256,
            "requested_model": model_metadata["requested_model"],
            "served_models": model_metadata["served_models"],
            "build_cost": build_cost,
            "preflight": preflight,
            "provider_profile": provider_profile,
            "resume": resume_metadata,
            "verification": verification_report,
        }
    except BaseException as exc:
        cleanup_errors: list[str] = []
        for temporary in temporary_files:
            try:
                temporary.unlink(missing_ok=True)
            except OSError as cleanup_exc:
                cleanup_errors.append(f"temporary cleanup: {cleanup_exc}")
        for final, payload in reversed(published_files):
            try:
                _safe_unlink_current_run(final, payload)
            except OSError as cleanup_exc:
                cleanup_errors.append(f"artifact rollback: {cleanup_exc}")
        for final, original_staging in reversed(published_directories):
            if final.is_dir() and not original_staging.exists():
                try:
                    os.rename(final, original_staging)
                except OSError as cleanup_exc:
                    cleanup_errors.append(f"directory rollback: {cleanup_exc}")
        run_dir.mkdir(parents=True, exist_ok=True)
        quarantine = run_dir / "quarantine"
        quarantine.mkdir(exist_ok=True)
        quarantine_records: dict[str, str] = {}
        for label, source in (("store", staging), ("trace", trace_staging)):
            if source.exists() and not (quarantine / label).exists():
                try:
                    os.rename(source, quarantine / label)
                    quarantine_records[label] = f"quarantine/{label}"
                except OSError as cleanup_exc:
                    cleanup_errors.append(f"{label} quarantine: {cleanup_exc}")
                    quarantine_records[label] = str(source)
        formal_names = ("s3_store", "s3_manifest", "trace_dir", "commit_marker")
        residual_formal_outputs = [
            name for name in formal_names if paths[name].exists() or paths[name].is_symlink()
        ]
        if residual_formal_outputs:
            release_lock = False
        partial = exc.partial if isinstance(exc, AgentRunError) else None
        failure = {
            "schema_version": 1,
            "status": "recovery_required" if residual_formal_outputs else "failed",
            "run_id": run_id,
            "failed_at": _utc_now(),
            "state": current_state,
            "current_chunk": current_chunk,
            "error": {"type": type(exc).__name__, "message": _redact_text(str(exc))},
            "partial_episode": _redact_value(partial),
            "quarantine": quarantine_records,
            "checkpoints_retained": (run_dir / "checkpoints").is_dir(),
            "formal_outputs_published": bool(residual_formal_outputs),
            "residual_formal_outputs": residual_formal_outputs,
            "cleanup_errors": _redact_value(cleanup_errors),
        }
        _atomic_write(run_dir / "failure.json", _pretty_json_bytes(failure))
        if isinstance(exc, (KeyboardInterrupt, SystemExit)):
            raise
        raise S3BuildError(
            f"S3 build failed during {current_state}; diagnostics retained in {run_dir}"
        ) from None
    finally:
        if release_lock:
            _release_owned_lock(lock_path, lock_payload, lock_inode)


def _validate_trace_directory(
    trace_dir: Path,
    stream: S3StreamSnapshot,
    final_gate: S3StoreGate,
) -> tuple[dict[str, Any], str]:
    raw = Path(trace_dir)
    if raw.is_symlink() or not raw.is_dir():
        raise S3BuildError("S3 trace must be an existing non-symlink directory")
    paths = list(raw.iterdir())
    if any(path.is_symlink() or not path.is_file() for path in paths):
        raise S3BuildError("S3 trace directory must contain only regular files")
    expected_names = {"index.json", "events.jsonl"} | {
        f"episode-{index:03d}.json" for index in range(1, len(stream.chunks) + 1)
    }
    if {path.name for path in paths} != expected_names:
        raise S3BuildError("S3 trace file set mismatch")
    index, _ = _load_json_object(raw / "index.json", "S3 trace index")
    if index.get("schema_version") != 1 or index.get("status") != "completed":
        raise S3BuildError("S3 trace index is not completed")
    expected_index_protocol = {
        "stream_manifest_sha256": stream.manifest_sha256,
        "prompt_contract_sha256": EXPECTED_S3_PROMPT_CONTRACT_SHA256,
        "runtime_contract_sha256": EXPECTED_S3_RUNTIME_CONTRACT_SHA256,
        "management_prompt_sha256": sha256_bytes(MANAGEMENT_PROMPT.encode("utf-8")),
        "system_prompt": MANAGEMENT_PROMPT,
        "runtime_config_sha256": FROZEN_MANAGEMENT_RUNTIME_CONFIG_SHA256,
        "tool_profile": list(MANAGEMENT_PROFILE),
        "tool_profile_sha256": FROZEN_MANAGEMENT_TOOL_PROFILE_SHA256,
        "tool_schema_sha256": FROZEN_MANAGEMENT_TOOL_SCHEMA_SHA256,
    }
    if index.get("protocol") != expected_index_protocol:
        raise S3BuildError("S3 trace index protocol mismatch")
    if not re.fullmatch(
        r"[0-9a-f]{40}|test-[a-z0-9-]+", str(index.get("code_revision"))
    ):
        raise S3BuildError("S3 trace code revision is invalid")
    model = index.get("model")
    if not isinstance(model, dict):
        raise S3BuildError("S3 trace model metadata is invalid")
    expected_model_fields = {
        "paper_configuration": asdict(MANAGEMENT),
        "requested_model": LOCAL_S3_PROVIDER_PROFILE["requested_model"],
        "served_models": [EXPECTED_S3_SERVED_MODEL],
        "api_style": LOCAL_S3_PROVIDER_PROFILE["api_style"],
        "endpoint": LOCAL_S3_PROVIDER_PROFILE["endpoint"],
        "sampling": {
            "configured_random_seed": RANDOM_SEED,
            "seed_sent_to_provider": False,
            "note": "The compatible API adapter does not send a seed parameter.",
        },
    }
    for key, expected in expected_model_fields.items():
        if model.get(key) != expected:
            raise S3BuildError(f"S3 trace model metadata mismatch for {key}")
    fingerprints = model.get("system_fingerprints")
    if not isinstance(fingerprints, list) or any(
        not isinstance(value, str) or not value for value in fingerprints
    ):
        raise S3BuildError("S3 trace system fingerprints are invalid")
    if set(model) != set(expected_model_fields) | {"system_fingerprints"}:
        raise S3BuildError("S3 trace model metadata has unexpected fields")
    episodes = index.get("episodes")
    if not isinstance(episodes, list) or len(episodes) != len(stream.chunks):
        raise S3BuildError("S3 trace episode index length mismatch")
    resume = index.get("resume")
    resumed_prefix_end = 0
    resumed_prefix_runtime_configs: dict[int, str] = {}
    if resume is not None:
        if not isinstance(resume, dict):
            raise S3BuildError("S3 trace resume metadata is invalid")
        start_chunk = resume.get("start_chunk")
        source_runtime_contract = resume.get("source_runtime_contract_sha256")
        if (
            not isinstance(start_chunk, int)
            or isinstance(start_chunk, bool)
            or not 1 <= start_chunk <= len(stream.chunks)
            or not isinstance(source_runtime_contract, str)
        ):
            raise S3BuildError("S3 trace resume prefix is invalid")
        resumed_prefix_end = start_chunk - 1
        resumed_prefix_runtime_configs = _validate_prefix_runtime_config_segments(
            resume.get("prefix_runtime_config_segments"),
            start_chunk=start_chunk,
            source_runtime_contract_sha256=source_runtime_contract,
        )
    prior_store_sha = sha256_bytes(canonical_json_bytes({}))
    prior_store_files: dict[str, str] = {}
    all_usage: list[dict[str, Any]] = []
    total_tools = 0
    total_rounds = 0
    total_llm_calls = 0
    expected_event_rows: list[dict[str, Any]] = []
    episode_protocol_base = {
        "management_prompt_sha256": sha256_bytes(MANAGEMENT_PROMPT.encode("utf-8")),
        "tool_profile_sha256": FROZEN_MANAGEMENT_TOOL_PROFILE_SHA256,
        "tool_schema_sha256": FROZEN_MANAGEMENT_TOOL_SCHEMA_SHA256,
    }
    for chunk, summary in zip(stream.chunks, episodes):
        expected_filename = f"episode-{chunk['global_chunk_index']:03d}.json"
        expected_runtime_config_sha = (
            resumed_prefix_runtime_configs[chunk["global_chunk_index"]]
            if chunk["global_chunk_index"] <= resumed_prefix_end
            else FROZEN_MANAGEMENT_RUNTIME_CONFIG_SHA256
        )
        episode_protocol = {
            **episode_protocol_base,
            "runtime_config_sha256": expected_runtime_config_sha,
        }
        if (
            not isinstance(summary, dict)
            or summary.get("filename") != expected_filename
            or summary.get("global_chunk_index") != chunk["global_chunk_index"]
            or summary.get("chunk_filename") != chunk["filename"]
        ):
            raise S3BuildError("S3 trace episode filename/order mismatch")
        episode, payload = _load_json_object(raw / expected_filename, expected_filename)
        if sha256_bytes(payload) != summary.get("sha256"):
            raise S3BuildError(f"S3 trace episode hash mismatch: {expected_filename}")
        if (
            episode.get("schema_version") != 1
            or episode.get("status") != "completed"
            or episode.get("run_id") != index.get("run_id")
            or episode.get("protocol") != episode_protocol
        ):
            raise S3BuildError(f"S3 trace episode status/run_id mismatch: {expected_filename}")
        episode_chunk = episode.get("chunk", {})
        payload_text = (stream.root / chunk["filename"]).read_text(encoding="utf-8")
        expected_user_message = render_s3_user_message(payload_text)
        if (
            episode_chunk.get("filename") != chunk["filename"]
            or episode_chunk.get("global_chunk_index") != chunk["global_chunk_index"]
            or episode_chunk.get("payload_sha256") != chunk["sha256"]
            or episode_chunk.get("locators") != chunk["locators"]
            or episode_chunk.get("user_message_sha256")
            != sha256_bytes(expected_user_message.encode("utf-8"))
            or episode.get("user_message") != expected_user_message
        ):
            raise S3BuildError(f"S3 trace chunk/input mismatch: {expected_filename}")
        result = episode.get("result", {})
        if (
            result.get("role") != "management"
            or result.get("configuration") != asdict(MANAGEMENT)
            or result.get("prompt_sha256") != sha256_bytes(MANAGEMENT_PROMPT.encode("utf-8"))
            or result.get("input_sha256")
            != sha256_bytes(expected_user_message.encode("utf-8"))
        ):
            raise S3BuildError(f"S3 trace result configuration mismatch: {expected_filename}")
        if episode.get("store_before_sha256") != prior_store_sha:
            raise S3BuildError(f"S3 trace store chain is broken before {expected_filename}")
        if summary.get("store_before_sha256") != prior_store_sha:
            raise S3BuildError(f"S3 trace summary store-before mismatch: {expected_filename}")
        before_files = episode.get("store_files_before")
        after_files = episode.get("store_files_after")
        if (
            not isinstance(before_files, dict)
            or not isinstance(after_files, dict)
            or any(
                not isinstance(name, str)
                or re.fullmatch(r"[0-9a-f]{64}", str(digest)) is None
                for inventory in (before_files, after_files)
                for name, digest in inventory.items()
            )
            or before_files != prior_store_files
            or sha256_bytes(canonical_json_bytes(before_files))
            != episode.get("store_before_sha256")
            or sha256_bytes(canonical_json_bytes(after_files))
            != episode.get("store_after_sha256")
        ):
            raise S3BuildError(f"S3 trace file inventory chain is invalid: {expected_filename}")
        before_names = set(before_files)
        after_names = set(after_files)
        expected_diff = {
            "added": sorted(after_names - before_names),
            "modified": sorted(
                name
                for name in before_names & after_names
                if before_files[name] != after_files[name]
            ),
            "removed": sorted(before_names - after_names),
        }
        if episode.get("store_diff") != expected_diff:
            raise S3BuildError(f"S3 trace store diff is invalid: {expected_filename}")
        prior_store_sha = episode.get("store_after_sha256")
        prior_store_files = after_files
        if summary.get("store_after_sha256") != prior_store_sha:
            raise S3BuildError(f"S3 trace summary store-after mismatch: {expected_filename}")
        usage = result.get("usage")
        trace = result.get("trace")
        if not isinstance(usage, list) or not isinstance(trace, list):
            raise S3BuildError(f"S3 trace result arrays are invalid: {expected_filename}")
        if any(not isinstance(event, dict) for event in trace):
            raise S3BuildError(f"S3 trace contains a non-object event: {expected_filename}")
        rounds = result.get("rounds")
        tool_calls = result.get("tool_calls")
        assistant_events = [event for event in trace if "assistant_content" in event]
        tool_events = [event for event in trace if "tool" in event]
        provider_events = [
            event
            for event in trace
            if "assistant_content" in event or event.get("compaction") is True
        ]
        if (
            not isinstance(result.get("answer"), str)
            or not result["answer"].strip()
            or not isinstance(rounds, int)
            or isinstance(rounds, bool)
            or not 1 <= rounds <= MANAGEMENT.max_rounds
            or len(assistant_events) != rounds
            or not isinstance(tool_calls, int)
            or isinstance(tool_calls, bool)
            or tool_calls < 0
            or len(tool_events) != tool_calls
        ):
            raise S3BuildError(f"S3 trace rounds/tool totals are invalid: {expected_filename}")
        for event in provider_events:
            if event.get("served_model") != EXPECTED_S3_SERVED_MODEL:
                raise S3BuildError(f"S3 trace served-model mismatch: {expected_filename}")
            if event.get("compaction") is True:
                summary_text = event.get("summary")
                if (
                    event.get("finish_reason") != "stop"
                    or not isinstance(summary_text, str)
                    or not summary_text.strip()
                    or event.get("summary_sha256")
                    != sha256_bytes(summary_text.encode("utf-8"))
                    or not re.fullmatch(
                        r"[0-9a-f]{64}", str(event.get("input_sha256"))
                    )
                ):
                    raise S3BuildError(
                        f"S3 trace compaction metadata mismatch: {expected_filename}"
                    )
            elif "assistant_content" in event:
                has_calls = bool(event.get("tool_calls"))
                expected_reason = "tool_calls" if has_calls else "stop"
                if event.get("finish_reason") != expected_reason:
                    raise S3BuildError(
                        f"S3 trace finish-reason mismatch: {expected_filename}"
                    )
        expected_event_rows.extend(
            {
                "event": "agent_trace",
                "chunk": chunk["global_chunk_index"],
                **event,
            }
            for event in trace
        )
        all_usage.extend(usage)
        total_tools += tool_calls
        total_rounds += rounds
        total_llm_calls += sum(
            1
            for event in trace
            if isinstance(event, dict)
            and ("assistant_content" in event or event.get("compaction") is True)
        )
    if prior_store_sha != final_gate.tree_sha256:
        raise S3BuildError("S3 trace final store hash does not match the published store")
    final_files = {name: metadata["sha256"] for name, metadata in final_gate.files.items()}
    if prior_store_files != final_files:
        raise S3BuildError("S3 trace final file inventory does not match the published store")
    expected_cost = {
        "episodes": len(stream.chunks),
        "llm_calls": total_llm_calls,
        "rounds": total_rounds,
        "tool_calls": total_tools,
        "usage_totals": _usage_totals(all_usage),
    }
    if index.get("build_cost") != expected_cost:
        raise S3BuildError("S3 trace build cost mismatch")
    events = index.get("events", {})
    events_payload = (raw / "events.jsonl").read_bytes()
    if events.get("filename") != "events.jsonl" or events.get("sha256") != sha256_bytes(
        events_payload
    ):
        raise S3BuildError("S3 trace events hash mismatch")
    try:
        event_rows = [
            json.loads(line)
            for line in events_payload.decode("utf-8").splitlines()
            if line
        ]
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise S3BuildError(f"S3 events JSONL is invalid: {exc}") from exc
    if (
        not event_rows
        or event_rows[0].get("event") != "build_start"
        or event_rows[0].get("run_id") != index.get("run_id")
        or event_rows[1:] != expected_event_rows
    ):
        raise S3BuildError("S3 events JSONL does not match episode traces")
    if index.get("final_store_sha256") != final_gate.tree_sha256:
        raise S3BuildError("S3 trace index final store hash mismatch")
    return index, _directory_tree_sha256(raw)


def verify_published_s3(
    stream_dir: Path,
    stream_manifest: Path,
    prompt_contract: Path,
    runtime_contract: Path,
    s3_store: Path,
    s3_manifest: Path,
    trace_dir: Path,
    commit_marker: Path,
    *,
    allow_test_artifact: bool = False,
) -> dict[str, Any]:
    """Recompute a published S3 artifact and every cross-link without API calls."""
    try:
        verify_s3_runtime_freeze()
    except RuntimeError as exc:
        raise S3BuildError(str(exc)) from exc
    stream = validate_s3_stream(stream_dir, stream_manifest)
    _, prompt_hash = _validate_prompt_contract(Path(prompt_contract))
    _, runtime_hash = _validate_runtime_contract(Path(runtime_contract))
    manifest, manifest_bytes = _load_json_object(Path(s3_manifest), "S3 manifest")
    marker, _ = _load_json_object(Path(commit_marker), "S3 commit marker")
    artifact_id = manifest.get("artifact_id")
    if artifact_id == S3_TEST_ARTIFACT_ID:
        if not allow_test_artifact:
            raise S3BuildError("Refusing to verify a test S3 artifact as formal output")
        expected_mode = "test"
        expected_revision = r"test-[a-z0-9-]+"
    elif artifact_id == S3_ARTIFACT_ID:
        expected_mode = "formal"
        expected_revision = r"[0-9a-f]{40}"
    else:
        raise S3BuildError("S3 manifest artifact_id mismatch")
    final_gate = validate_curated_store(Path(s3_store), stream.all_locators)
    trace_index, trace_tree_sha256 = _validate_trace_directory(
        Path(trace_dir), stream, final_gate
    )
    manifest_sha256 = sha256_bytes(manifest_bytes)
    expected_marker = {
        "schema_version": 1,
        "artifact_id": artifact_id,
        "run_id": trace_index.get("run_id"),
        "committed_at": trace_index.get("finished_at"),
        "store_tree_sha256": final_gate.tree_sha256,
        "trace_tree_sha256": trace_tree_sha256,
        "manifest_sha256": manifest_sha256,
        "stream_manifest_sha256": stream.manifest_sha256,
        "prompt_contract_sha256": prompt_hash,
        "runtime_contract_sha256": runtime_hash,
    }
    if marker != expected_marker:
        raise S3BuildError("S3 commit marker does not match published artifacts")
    if manifest.get("schema_version") != S3_BUILD_SCHEMA_VERSION:
        raise S3BuildError("S3 manifest schema mismatch")
    expected_source = {
        "artifact_id": stream.artifact_id,
        "stream_manifest_sha256": stream.manifest_sha256,
        "stream_sha256": stream.stream_sha256,
        "prompt_contract_sha256": prompt_hash,
        "runtime_contract_sha256": runtime_hash,
    }
    if manifest.get("source") != expected_source:
        raise S3BuildError("S3 manifest source identity mismatch")
    expected_protocol = {
        "management_prompt_sha256": sha256_bytes(MANAGEMENT_PROMPT.encode("utf-8")),
        "runtime_config_sha256": FROZEN_MANAGEMENT_RUNTIME_CONFIG_SHA256,
        "tool_profile": list(MANAGEMENT_PROFILE),
        "tool_profile_sha256": FROZEN_MANAGEMENT_TOOL_PROFILE_SHA256,
        "tool_schema_sha256": FROZEN_MANAGEMENT_TOOL_SCHEMA_SHA256,
        "one_fresh_agent_context_per_chunk": True,
        "persistent_filesystem_across_chunks": True,
        "formal_store_started_empty": True,
        "gold_inputs_exposed_to_agent_messages_or_tools": False,
    }
    if manifest.get("protocol") != expected_protocol:
        raise S3BuildError("S3 manifest protocol mismatch")
    if manifest.get("model") != trace_index.get("model"):
        raise S3BuildError("S3 manifest and trace model metadata mismatch")
    if manifest.get("build_cost") != trace_index.get("build_cost"):
        raise S3BuildError("S3 manifest and trace build cost mismatch")
    build = manifest.get("build", {})
    if (
        build.get("run_id") != trace_index.get("run_id")
        or build.get("started_at") != trace_index.get("started_at")
        or build.get("finished_at") != trace_index.get("finished_at")
        or build.get("chunks_completed") != len(stream.chunks)
        or build.get("mode") != expected_mode
    ):
        raise S3BuildError("S3 manifest build/trace cross-link mismatch")
    resume = build.get("resume")
    if resume != trace_index.get("resume"):
        raise S3BuildError("S3 manifest/trace resume provenance mismatch")
    if resume is not None:
        expected_resume_keys = {
            "resumed",
            "start_chunk",
            "reused_completed_chunks",
            "source_failed_run_id",
            "source_code_revision",
            "source_runtime_contract_sha256",
            "prefix_runtime_config_segments",
            "resume_runtime_contract_sha256",
            "resumed_at",
        }
        if (
            not isinstance(resume, dict)
            or set(resume) != expected_resume_keys
            or resume.get("resumed") is not True
            or resume.get("source_failed_run_id") != trace_index.get("run_id")
            or re.fullmatch(
                expected_revision, str(resume.get("source_code_revision"))
            )
            is None
            or resume.get("source_runtime_contract_sha256")
            not in (
                _LEGACY_RESUMABLE_RUNTIME_CONTRACTS
                | {EXPECTED_S3_RUNTIME_CONTRACT_SHA256}
            )
            or resume.get("resume_runtime_contract_sha256") != runtime_hash
            or not isinstance(resume.get("start_chunk"), int)
            or isinstance(resume.get("start_chunk"), bool)
            or not 1 <= resume["start_chunk"] <= len(stream.chunks)
            or resume.get("reused_completed_chunks") != resume["start_chunk"] - 1
            or not isinstance(resume.get("resumed_at"), str)
            or not resume["resumed_at"]
        ):
            raise S3BuildError("S3 resume provenance is invalid")
        _validate_prefix_runtime_config_segments(
            resume.get("prefix_runtime_config_segments"),
            start_chunk=resume["start_chunk"],
            source_runtime_contract_sha256=resume["source_runtime_contract_sha256"],
        )
    expected_counts = {
        "files": len(final_gate.files),
        "directories": len(final_gate.directories),
        "bytes": final_gate.total_bytes,
        "lines": final_gate.total_lines,
        "headings": final_gate.heading_count,
        "locator_mentions": final_gate.locator_mentions,
        "unique_locators_referenced": final_gate.unique_locators,
        "source_locators_available": len(stream.all_locators),
        "cross_references": final_gate.cross_reference_count,
        "max_file_depth": final_gate.max_depth,
    }
    if manifest.get("counts") != expected_counts:
        raise S3BuildError("S3 manifest counts mismatch")
    if manifest.get("directories") != final_gate.directories:
        raise S3BuildError("S3 manifest directory inventory mismatch")
    if manifest.get("files") != final_gate.files:
        raise S3BuildError("S3 manifest file inventory mismatch")
    if manifest.get("source_index") != final_gate.source_index:
        raise S3BuildError("S3 manifest source index mismatch")
    if manifest.get("store") != {
        "directory_name": Path(s3_store).resolve(strict=False).name,
        "tree_sha256": final_gate.tree_sha256,
    }:
        raise S3BuildError("S3 manifest store identity mismatch")
    if manifest.get("trace") != {
        "directory_name": Path(trace_dir).resolve(strict=False).name,
        "index_filename": "index.json",
        "tree_sha256": trace_tree_sha256,
    }:
        raise S3BuildError("S3 manifest trace identity mismatch")
    generator = manifest.get("generator", {})
    if (
        generator.get("module") != "fs_memory_lab.s3_runner"
        or generator.get("version") != S3_RUNNER_VERSION
        or not re.fullmatch(expected_revision, str(generator.get("git_commit")))
        or generator.get("git_commit") != trace_index.get("code_revision")
    ):
        raise S3BuildError("S3 manifest generator identity mismatch")
    expected_verification = {
        "all_85_chunks_completed_in_order": True,
        "all_memory_files_valid_markdown_with_frontmatter": True,
        "all_stored_locators_exist_in_seen_source": True,
        "all_list_or_table_fact_candidates_have_inline_locator": True,
        "all_cross_references_resolve": True,
        "input_stream_revalidated_after_build": True,
        "contracts_revalidated_after_build": True,
        "gold_inputs_exposed_to_agent_messages_or_tools": False,
        "image_urls_fetched": False,
        "formal_outputs_published_from_staging": True,
    }
    if manifest.get("verification") != expected_verification:
        raise S3BuildError("S3 manifest verification claims do not match the protocol")
    return {
        "status": "verified",
        "artifact_id": artifact_id,
        "run_id": trace_index["run_id"],
        "chunks": len(stream.chunks),
        "files": len(final_gate.files),
        "directories": len(final_gate.directories),
        "store_tree_sha256": final_gate.tree_sha256,
        "trace_tree_sha256": trace_tree_sha256,
        "manifest_sha256": manifest_sha256,
        "served_models": trace_index.get("model", {}).get("served_models", []),
        "build_cost": trace_index.get("build_cost"),
    }
