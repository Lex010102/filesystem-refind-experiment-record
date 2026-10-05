"""Safe builder and verifier for the S2 Foldered verbatim-session store."""

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

from .agent import AgentRunError, AgentRunner, ChatProvider, EpisodeResult
from .filesystem import MemoryFS, ToolError
from .foldering_prompt import (
    FOLDERING_PROMPT,
    FOLDERING_PROMPT_VERSION,
    FOLDERING_TASK,
    FROZEN_FOLDERING_PROMPT_SHA256,
    FROZEN_FOLDERING_TASK_SHA256,
)
from .paper_config import FOLDERING, RANDOM_SEED
from .paper_tools import (FOLDERING_PROFILE, FOLDERING_TOOL_DEFINITIONS,
                          FROZEN_FOLDERING_TOOL_SCHEMA_SHA256)


S2_SCHEMA_VERSION = 1
S2_BUILDER_VERSION = "foldered-verbatim-safe-v1"
EXPECTED_CONV50_S1_MANIFEST_SHA256 = (
    "5c5900c333c8f85463f038448560cb4357f1161d6ed43e9fbc86809ba7916d3c"
)
_SLUG = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*\Z")
_RUN_ID = re.compile(r"[0-9]{8}T[0-9]{12}Z-[a-f0-9]{8}\Z")


class S2BuildError(RuntimeError):
    """Raised when a formal S2 artifact cannot be safely built or verified."""


@dataclass(frozen=True)
class S1Snapshot:
    root: Path
    manifest: dict[str, Any]
    manifest_sha256: str
    artifact_id: str
    files: dict[str, dict[str, Any]]
    content_sha256: str
    total_bytes: int


@dataclass(frozen=True)
class S2GateReport:
    mappings: dict[str, str]
    files: dict[str, dict[str, Any]]
    directories: list[str]
    pruned_empty_directories: list[str]
    content_sha256: str
    layout_sha256: str
    total_bytes: int
    max_depth: int


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _pretty_json_bytes(value: Any) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, allow_nan=False, indent=2, sort_keys=True)
        + "\n"
    ).encode("utf-8")


def _foldering_tool_schema_sha256() -> str:
    ordered = [FOLDERING_TOOL_DEFINITIONS[name] for name in FOLDERING_PROFILE]
    return _sha256_bytes(_canonical_json_bytes(ordered))


def _atomic_write(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp-{secrets.token_hex(4)}")
    try:
        with temporary.open("xb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _load_json_object(path: Path, label: str) -> tuple[dict[str, Any], bytes]:
    if path.is_symlink() or not path.is_file():
        raise S2BuildError(f"{label} must be an existing non-symlink file")
    try:
        payload = path.read_bytes()
        value = json.loads(payload.decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise S2BuildError(f"Cannot read {label}: {exc}") from exc
    if not isinstance(value, dict):
        raise S2BuildError(f"{label} must contain one JSON object")
    return value, payload


def _body_bytes(payload: bytes) -> bytes:
    boundary = b"---\n\n"
    if not payload.startswith(b"---\n") or boundary not in payload:
        raise S2BuildError("Session file is missing its YAML frontmatter boundary")
    return payload.split(boundary, 1)[1]


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


def _ensure_distinct_paths(paths: dict[str, Path]) -> dict[str, Path]:
    raw = {name: Path(path) for name, path in paths.items()}
    for name, path in raw.items():
        if path.is_symlink():
            raise S2BuildError(f"{name} must not be a symlink")
    resolved = {name: path.resolve(strict=False) for name, path in raw.items()}
    reverse: dict[Path, str] = {}
    for name, path in resolved.items():
        if path in reverse:
            raise S2BuildError(f"Paths for {reverse[path]} and {name} must be distinct")
        reverse[path] = name
    source = resolved["s1_store"]
    output = resolved["s2_store"]
    if source in output.parents or output in source.parents:
        raise S2BuildError("S1 and S2 store paths must not contain one another")
    artifact_names = ("s2_manifest", "path_map", "trace", "commit_marker")
    for name in artifact_names:
        artifact = resolved[name]
        if artifact == output or output in artifact.parents or artifact in output.parents:
            raise S2BuildError(f"{name} must live outside the S2 store")
    for index, left_name in enumerate(artifact_names):
        for right_name in artifact_names[index + 1:]:
            left = resolved[left_name]
            right = resolved[right_name]
            if left in right.parents or right in left.parents:
                raise S2BuildError(
                    f"Artifact paths {left_name} and {right_name} must not contain one another"
                )
    writable_names = [
        name for name in resolved
        if name not in {"s1_store", "s1_manifest"}
    ]
    for name in writable_names:
        writable = resolved[name]
        if writable == source or writable in source.parents or source in writable.parents:
            raise S2BuildError(f"Writable path {name} must be isolated from the S1 store")
    work_root = resolved.get("work_root")
    if work_root is not None:
        if work_root == output or work_root in output.parents or output in work_root.parents:
            raise S2BuildError("work_root and S2 store must not contain one another")
        for name in artifact_names:
            artifact = resolved[name]
            if (
                artifact == work_root
                or artifact in work_root.parents
                or work_root in artifact.parents
            ):
                raise S2BuildError(f"{name} must live outside work_root")
    return resolved


def validate_s1_store(
    store_dir: Path,
    manifest_path: Path,
    *,
    expected_manifest_sha256: str | None = EXPECTED_CONV50_S1_MANIFEST_SHA256,
) -> S1Snapshot:
    """Recompute every S1 file invariant instead of trusting the manifest."""
    raw_store_dir = Path(store_dir)
    raw_manifest_path = Path(manifest_path)
    if raw_store_dir.is_symlink() or not raw_store_dir.is_dir():
        raise S2BuildError("S1 store must be an existing non-symlink directory")
    if raw_manifest_path.is_symlink() or not raw_manifest_path.is_file():
        raise S2BuildError("S1 manifest must be an existing regular file")
    store_dir = raw_store_dir.resolve(strict=False)
    manifest_path = raw_manifest_path.resolve(strict=False)

    manifest, manifest_payload = _load_json_object(manifest_path, "S1 manifest")
    manifest_sha256 = _sha256_bytes(manifest_payload)
    if expected_manifest_sha256 is not None and manifest_sha256 != expected_manifest_sha256:
        raise S2BuildError(
            "S1 manifest hash differs from the frozen experiment input: "
            f"expected {expected_manifest_sha256}, got {manifest_sha256}"
        )
    expected_files = manifest.get("files")
    if not isinstance(expected_files, dict) or not expected_files:
        raise S2BuildError("S1 manifest has no file table")
    artifact_id = manifest.get("artifact_id")
    if not isinstance(artifact_id, str) or not artifact_id:
        raise S2BuildError("S1 manifest has no artifact_id")
    if "/s1-flat/" not in artifact_id:
        raise S2BuildError("S1 artifact_id must identify an s1-flat artifact")

    entries = list(store_dir.iterdir())
    if any(path.is_symlink() or not path.is_file() or path.suffix != ".md" for path in entries):
        raise S2BuildError("S1 store must be flat and contain only regular .md files")
    actual_names = {path.name for path in entries}
    if actual_names != set(expected_files):
        missing = sorted(set(expected_files) - actual_names)
        extra = sorted(actual_names - set(expected_files))
        raise S2BuildError(f"S1 file set mismatch; missing={missing[:5]} extra={extra[:5]}")

    files: dict[str, dict[str, Any]] = {}
    total_bytes = 0
    for name in sorted(actual_names):
        metadata = expected_files[name]
        if not isinstance(metadata, dict):
            raise S2BuildError(f"S1 manifest metadata is invalid for {name}")
        path = store_dir / name
        payload = path.read_bytes()
        try:
            text = payload.decode("utf-8")
            MemoryFS._validate(path, text)
        except (UnicodeDecodeError, ToolError) as exc:
            raise S2BuildError(f"S1 file validation failed for {name}: {exc}") from exc
        body = _body_bytes(payload)
        checks = {
            "bytes": len(payload),
            "sha256": _sha256_bytes(payload),
            "body_bytes": len(body),
            "body_sha256": _sha256_bytes(body),
        }
        for field, actual in checks.items():
            if metadata.get(field) != actual:
                raise S2BuildError(f"S1 {field} mismatch for {name}")
        files[name] = {**copy.deepcopy(metadata), **checks}
        total_bytes += len(payload)

    content_sha256 = _sha256_bytes(
        _canonical_json_bytes({name: files[name]["sha256"] for name in sorted(files)})
    )
    if manifest.get("store", {}).get("sha256") != content_sha256:
        raise S2BuildError("S1 store hash does not match its files")
    counts = manifest.get("counts")
    if not isinstance(counts, dict):
        raise S2BuildError("S1 manifest has no counts")
    if counts.get("files") != len(files) or counts.get("bytes") != total_bytes:
        raise S2BuildError("S1 manifest counts do not match the store")

    return S1Snapshot(
        root=store_dir,
        manifest=manifest,
        manifest_sha256=manifest_sha256,
        artifact_id=artifact_id,
        files=files,
        content_sha256=content_sha256,
        total_bytes=total_bytes,
    )


def _copy_s1_to_staging(snapshot: S1Snapshot, staging: Path) -> None:
    staging.mkdir(parents=False, exist_ok=False)
    for name in sorted(snapshot.files):
        source = snapshot.root / name
        destination = staging / name
        shutil.copyfile(source, destination)
        if _sha256_bytes(destination.read_bytes()) != snapshot.files[name]["sha256"]:
            raise S2BuildError(f"Staging copy hash mismatch for {name}")


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


def validate_s2_staging(
    s1: S1Snapshot,
    staging_root: Path,
    *,
    pruned_empty_directories: list[str] | None = None,
) -> S2GateReport:
    """Apply a store-wide gate independently of the model-facing tool guards."""
    raw_staging_root = Path(staging_root)
    if raw_staging_root.is_symlink() or not raw_staging_root.is_dir():
        raise S2BuildError("S2 staging must be an existing non-symlink directory")
    staging_root = raw_staging_root.resolve(strict=False)

    paths = list(staging_root.rglob("*"))
    if any(path.is_symlink() for path in paths):
        raise S2BuildError("S2 staging contains a symlink")
    directories = sorted(path for path in paths if path.is_dir())
    regular_files = sorted(path for path in paths if path.is_file())
    if len(directories) + len(regular_files) != len(paths):
        raise S2BuildError("S2 staging contains a non-regular filesystem entry")
    if any(path.suffix != ".md" for path in regular_files):
        raise S2BuildError("S2 staging contains a non-Markdown file")
    if any(path.parent == staging_root for path in regular_files):
        raise S2BuildError("S2 staging still has unclassified root-level .md files")
    if any(not any(child.is_file() for child in directory.rglob("*")) for directory in directories):
        raise S2BuildError("S2 staging contains an empty topic directory")
    for directory in directories:
        relative = directory.relative_to(staging_root)
        if any(_SLUG.fullmatch(part) is None for part in relative.parts):
            raise S2BuildError(f"S2 directory is not lowercase kebab-case: {relative}")

    basenames = [path.name for path in regular_files]
    if len(basenames) != len(set(basenames)):
        raise S2BuildError("S2 staging contains duplicate session basenames")
    if set(basenames) != set(s1.files):
        missing = sorted(set(s1.files) - set(basenames))
        extra = sorted(set(basenames) - set(s1.files))
        raise S2BuildError(f"S2 file set mismatch; missing={missing[:5]} extra={extra[:5]}")

    mappings: dict[str, str] = {}
    files: dict[str, dict[str, Any]] = {}
    total_bytes = 0
    layout_hash_input: dict[str, str] = {}
    for path in regular_files:
        relative = path.relative_to(staging_root).as_posix()
        payload = path.read_bytes()
        digest = _sha256_bytes(payload)
        expected = s1.files[path.name]
        if digest != expected["sha256"] or len(payload) != expected["bytes"]:
            raise S2BuildError(f"S2 changed immutable file bytes: {path.name}")
        body = _body_bytes(payload)
        if (
            _sha256_bytes(body) != expected["body_sha256"]
            or len(body) != expected["body_bytes"]
        ):
            raise S2BuildError(f"S2 changed immutable file body: {path.name}")
        mappings[path.name] = relative
        files[relative] = {
            **copy.deepcopy(expected),
            "basename": path.name,
            "source_path": path.name,
        }
        layout_hash_input[relative] = digest
        total_bytes += len(payload)

    content_sha256 = _sha256_bytes(
        _canonical_json_bytes(
            {name: s1.files[name]["sha256"] for name in sorted(mappings)}
        )
    )
    if content_sha256 != s1.content_sha256 or total_bytes != s1.total_bytes:
        raise S2BuildError("S2 content identity does not match S1")
    layout_sha256 = _sha256_bytes(_canonical_json_bytes(layout_hash_input))
    relative_directories = [path.relative_to(staging_root).as_posix() for path in directories]
    max_depth = max(len(Path(relative).parts) - 1 for relative in mappings.values())
    return S2GateReport(
        mappings=dict(sorted(mappings.items())),
        files=dict(sorted(files.items())),
        directories=relative_directories,
        pruned_empty_directories=sorted(pruned_empty_directories or []),
        content_sha256=content_sha256,
        layout_sha256=layout_sha256,
        total_bytes=total_bytes,
        max_depth=max_depth,
    )


def _path_map_document(s1: S1Snapshot, gate: S2GateReport) -> dict[str, Any]:
    target_artifact = s1.artifact_id.replace("/s1-flat/", "/s2-foldered/")
    return {
        "schema_version": S2_SCHEMA_VERSION,
        "artifact_id": target_artifact + "/path-map",
        "source_artifact_id": s1.artifact_id,
        "target_artifact_id": target_artifact,
        "source_content_sha256": s1.content_sha256,
        "target_content_sha256": gate.content_sha256,
        "target_layout_sha256": gate.layout_sha256,
        "entries": [
            {
                "basename": name,
                "bytes": s1.files[name]["bytes"],
                "s1_path": name,
                "s2_path": gate.mappings[name],
                "sha256": s1.files[name]["sha256"],
            }
            for name in sorted(gate.mappings)
        ],
    }


def _episode_document(result: EpisodeResult, provider: ChatProvider, run_id: str,
                      started_at: str, finished_at: str) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "status": "completed",
        "run_id": run_id,
        "started_at": started_at,
        "finished_at": finished_at,
        "protocol": {
            "prompt_version": FOLDERING_PROMPT_VERSION,
            "prompt_sha256": FROZEN_FOLDERING_PROMPT_SHA256,
            "system_prompt": FOLDERING_PROMPT,
            "task": FOLDERING_TASK,
            "task_sha256": FROZEN_FOLDERING_TASK_SHA256,
            "tool_profile": list(FOLDERING_PROFILE),
            "tool_schema_sha256": FROZEN_FOLDERING_TOOL_SCHEMA_SHA256,
        },
        "model": _provider_metadata(provider, result),
        "episode": {
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


def _usage_totals(usage: list[dict]) -> dict[str, int]:
    totals: dict[str, int] = {}
    for record in usage:
        if not isinstance(record, dict):
            continue
        for key, value in record.items():
            if isinstance(value, int) and not isinstance(value, bool):
                totals[key] = totals.get(key, 0) + value
    return dict(sorted(totals.items()))


def _provider_metadata(provider: ChatProvider, result: EpisodeResult) -> dict[str, Any]:
    endpoint = getattr(provider, "endpoint", None)
    safe_endpoint = None
    if isinstance(endpoint, str):
        parsed = urlsplit(endpoint)
        host = parsed.hostname or ""
        if parsed.port is not None:
            host += f":{parsed.port}"
        safe_endpoint = f"{parsed.scheme}://{host}{parsed.path}"
    served_models = sorted(
        {
            event["served_model"]
            for event in result.trace
            if isinstance(event.get("served_model"), str) and event["served_model"]
        }
    )
    fingerprints = sorted(
        {
            event["system_fingerprint"]
            for event in result.trace
            if isinstance(event.get("system_fingerprint"), str)
            and event["system_fingerprint"]
        }
    )
    return {
        "paper_configuration": asdict(FOLDERING),
        "requested_model": getattr(provider, "model", None) or FOLDERING.model,
        "served_models": served_models,
        "system_fingerprints": fingerprints,
        "api_style": getattr(provider, "api_style", None),
        "endpoint": safe_endpoint,
        "sampling": {
            "configured_random_seed": RANDOM_SEED,
            "seed_sent_to_provider": False,
            "note": "The current compatible API adapter does not send a seed parameter.",
        },
    }


def _updated_source_index(s1: S1Snapshot, gate: S2GateReport) -> dict[str, Any]:
    source_index = copy.deepcopy(s1.manifest.get("source_index", {}))
    if not isinstance(source_index, dict):
        raise S2BuildError("S1 manifest source_index is invalid")
    for locator, entry in source_index.items():
        if not isinstance(entry, dict) or entry.get("file") not in gate.mappings:
            raise S2BuildError(f"S1 source_index entry is invalid for {locator}")
        entry["file"] = gate.mappings[entry["file"]]
    return source_index


def _manifest_document(
    s1: S1Snapshot,
    gate: S2GateReport,
    result: EpisodeResult,
    provider: ChatProvider,
    *,
    run_id: str,
    started_at: str,
    finished_at: str,
    output_dir: Path,
    path_map_path: Path,
    path_map_sha256: str,
    trace_path: Path,
    trace_sha256: str,
    code_revision: str,
) -> dict[str, Any]:
    target_artifact = s1.artifact_id.replace("/s1-flat/", "/s2-foldered/")
    counts = copy.deepcopy(s1.manifest.get("counts", {}))
    counts.update(
        {
            "files": len(gate.files),
            "bytes": gate.total_bytes,
            "directories": len(gate.directories),
            "root_md_files": 0,
            "max_topic_depth": gate.max_depth,
        }
    )
    return {
        "schema_version": S2_SCHEMA_VERSION,
        "artifact_id": target_artifact,
        "generator": {
            "module": "fs_memory_lab.s2",
            "version": S2_BUILDER_VERSION,
            "git_commit": code_revision,
        },
        "source": {
            "artifact_id": s1.artifact_id,
            "manifest_sha256": s1.manifest_sha256,
            "content_sha256": s1.content_sha256,
            "canonical_sha256": s1.manifest.get("input", {}).get("canonical_sha256"),
            "source_map_sha256": s1.manifest.get("input", {}).get("source_map_sha256"),
        },
        "protocol": {
            "condition": "S2 Foldered verbatim sessions",
            "prompt_version": FOLDERING_PROMPT_VERSION,
            "prompt_sha256": FROZEN_FOLDERING_PROMPT_SHA256,
            "prompt_provenance": "project-defined reconstruction; author build prompt not published",
            "task_sha256": FROZEN_FOLDERING_TASK_SHA256,
            "tool_profile": list(FOLDERING_PROFILE),
            "tool_schema_sha256": FROZEN_FOLDERING_TOOL_SCHEMA_SHA256,
            "invariants": [
                "whole-session move only",
                "same basename",
                "byte-identical to S1",
                "exactly one topic path per session",
                "no QA or gold inputs mounted",
            ],
        },
        "model": _provider_metadata(provider, result),
        "episode": {
            "run_id": run_id,
            "started_at": started_at,
            "finished_at": finished_at,
            "rounds": result.rounds,
            "tool_calls": result.tool_calls,
            "answer_sha256": _sha256_bytes(result.answer.encode("utf-8")),
            "trace_filename": trace_path.name,
            "trace_sha256": trace_sha256,
        },
        "build_cost": {
            "llm_calls": sum(
                1 for event in result.trace
                if "assistant_content" in event or event.get("compaction") is True
            ),
            "tool_calls": result.tool_calls,
            "usage_totals": _usage_totals(result.usage),
        },
        "counts": counts,
        "directories": gate.directories,
        "pruned_empty_directories": gate.pruned_empty_directories,
        "files": gate.files,
        "source_index": _updated_source_index(s1, gate),
        "path_map": {
            "filename": path_map_path.name,
            "sha256": path_map_sha256,
        },
        "store": {
            "directory_name": output_dir.name,
            "content_sha256": gate.content_sha256,
            "layout_sha256": gate.layout_sha256,
        },
        "verification": {
            "s1_revalidated_after_episode": True,
            "file_count_unchanged": True,
            "basename_set_unchanged": True,
            "bytes_identical_to_s1": True,
            "content_sha256_matches_s1": True,
            "all_sessions_nested_once": True,
            "root_has_no_markdown_files": True,
            "no_symlinks_or_non_markdown_files": True,
            "folder_names_are_kebab_case": True,
            "gold_inputs_mounted": False,
            "image_urls_fetched": False,
        },
    }


def git_state(repo_root: Path) -> dict[str, Any]:
    """Return the committed code identity used by a formal model run."""
    repo_root = Path(repo_root).resolve()
    try:
        revision = subprocess.run(
            ["git", "-C", str(repo_root), "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        status = subprocess.run(
            ["git", "-C", str(repo_root), "status", "--porcelain"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout
    except (OSError, subprocess.CalledProcessError) as exc:
        raise S2BuildError(f"Cannot resolve Git state for formal S2 build: {exc}") from exc
    if not re.fullmatch(r"[0-9a-f]{40}", revision):
        raise S2BuildError("Git returned an invalid commit id")
    return {"commit": revision, "dirty": bool(status.strip())}


def _preflight_targets(paths: dict[str, Path]) -> None:
    for name in ("s2_store", "s2_manifest", "path_map", "trace", "commit_marker"):
        if paths[name].exists() or paths[name].is_symlink():
            raise S2BuildError(f"Refusing to overwrite existing {name}: {paths[name]}")
    lock = paths["s2_store"].parent / f".{paths['s2_store'].name}.lock"
    if lock.exists() or lock.is_symlink():
        raise S2BuildError(f"An S2 build lock already exists: {lock}")


def preflight_s2_build(
    s1_store: Path,
    s1_manifest: Path,
    s2_store: Path,
    s2_manifest: Path,
    path_map: Path,
    trace: Path,
    commit_marker: Path,
    *,
    expected_s1_manifest_sha256: str | None = EXPECTED_CONV50_S1_MANIFEST_SHA256,
) -> dict[str, Any]:
    actual_prompt_hash = _sha256_bytes(FOLDERING_PROMPT.encode("utf-8"))
    if actual_prompt_hash != FROZEN_FOLDERING_PROMPT_SHA256:
        raise S2BuildError(
            "Reviewed foldering prompt changed without an explicit version/hash update"
        )
    actual_task_hash = _sha256_bytes(FOLDERING_TASK.encode("utf-8"))
    if actual_task_hash != FROZEN_FOLDERING_TASK_SHA256:
        raise S2BuildError(
            "Reviewed foldering task changed without an explicit version/hash update"
        )
    actual_tool_schema_hash = _foldering_tool_schema_sha256()
    if actual_tool_schema_hash != FROZEN_FOLDERING_TOOL_SCHEMA_SHA256:
        raise S2BuildError(
            "Reviewed foldering tool schema changed without an explicit hash update"
        )
    paths = _ensure_distinct_paths(
        {
            "s1_store": Path(s1_store),
            "s1_manifest": Path(s1_manifest),
            "s2_store": Path(s2_store),
            "s2_manifest": Path(s2_manifest),
            "path_map": Path(path_map),
            "trace": Path(trace),
            "commit_marker": Path(commit_marker),
        }
    )
    _preflight_targets(paths)
    snapshot = validate_s1_store(
        paths["s1_store"],
        paths["s1_manifest"],
        expected_manifest_sha256=expected_s1_manifest_sha256,
    )
    return {
        "status": "ready",
        "source_artifact_id": snapshot.artifact_id,
        "s1_manifest_sha256": snapshot.manifest_sha256,
        "s1_content_sha256": snapshot.content_sha256,
        "files": len(snapshot.files),
        "bytes": snapshot.total_bytes,
        "foldering_prompt_version": FOLDERING_PROMPT_VERSION,
        "foldering_prompt_sha256": actual_prompt_hash,
        "foldering_task_sha256": actual_task_hash,
        "tool_profile": list(FOLDERING_PROFILE),
        "tool_schema_sha256": actual_tool_schema_hash,
    }


def _acquire_lock(path: Path, run_id: str) -> tuple[bytes, int]:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError as exc:
        raise S2BuildError(f"An S2 build lock already exists: {path}") from exc
    payload = _pretty_json_bytes({"run_id": run_id, "created_at": _utc_now()})
    inode = -1
    try:
        inode = os.fstat(descriptor).st_ino
        written = 0
        while written < len(payload):
            count = os.write(descriptor, payload[written:])
            if count <= 0:
                raise OSError("short write while creating S2 build lock")
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
        raise S2BuildError("Cannot create durable S2 build lock") from None
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
        raise S2BuildError(f"Publish temporary already exists: {temporary}")
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


def build_s2_store(
    s1_store: Path,
    s1_manifest: Path,
    s2_store: Path,
    s2_manifest: Path,
    path_map: Path,
    trace: Path,
    commit_marker: Path,
    work_root: Path,
    provider: ChatProvider,
    *,
    code_revision: str,
    code_dirty: bool,
    expected_s1_manifest_sha256: str | None = EXPECTED_CONV50_S1_MANIFEST_SHA256,
    max_rounds: int | None = None,
) -> dict[str, Any]:
    """Build S2 once in staging and publish only after every invariant passes."""
    if code_dirty:
        raise S2BuildError("Formal S2 build requires a clean committed Git worktree")
    if not re.fullmatch(r"[0-9a-f]{40}|test-[a-z0-9-]+", code_revision):
        raise S2BuildError("code_revision must be a Git commit or an explicit test id")

    preflight = preflight_s2_build(
        s1_store,
        s1_manifest,
        s2_store,
        s2_manifest,
        path_map,
        trace,
        commit_marker,
        expected_s1_manifest_sha256=expected_s1_manifest_sha256,
    )
    paths = _ensure_distinct_paths(
        {
            "s1_store": Path(s1_store),
            "s1_manifest": Path(s1_manifest),
            "s2_store": Path(s2_store),
            "s2_manifest": Path(s2_manifest),
            "path_map": Path(path_map),
            "trace": Path(trace),
            "commit_marker": Path(commit_marker),
            "work_root": Path(work_root),
        }
    )
    snapshot = validate_s1_store(
        paths["s1_store"],
        paths["s1_manifest"],
        expected_manifest_sha256=expected_s1_manifest_sha256,
    )
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ-") + secrets.token_hex(4)
    if _RUN_ID.fullmatch(run_id) is None:
        raise S2BuildError("Internal run id generation failed")

    work_root = paths["work_root"]
    run_dir = work_root / run_id
    staging = paths["s2_store"].parent / f".{paths['s2_store'].name}.staging-{run_id}"
    lock_path = paths["s2_store"].parent / f".{paths['s2_store'].name}.lock"
    started_at = _utc_now()
    current_state = "PRECHECK"
    published_files: list[tuple[Path, bytes]] = []
    published_store = False
    temporary_files: list[Path] = []
    runner: AgentRunner | None = None
    event_path: Path | None = None
    release_lock = True

    paths["s2_store"].parent.mkdir(parents=True, exist_ok=True)
    work_root.mkdir(parents=True, exist_ok=True)
    if work_root.stat().st_dev != paths["s2_store"].parent.stat().st_dev:
        raise S2BuildError("S2 work_root and output must be on the same filesystem")
    lock_payload, lock_inode = _acquire_lock(lock_path, run_id)
    try:
        for name in ("s2_store", "s2_manifest", "path_map", "trace", "commit_marker"):
            if paths[name].exists() or paths[name].is_symlink():
                raise S2BuildError(
                    f"A formal artifact appeared while acquiring the lock: {name}"
                )
        run_dir.mkdir(parents=False, exist_ok=False)

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
                        "source_artifact_id": snapshot.artifact_id,
                        "source_manifest_sha256": snapshot.manifest_sha256,
                        "prompt_sha256": FROZEN_FOLDERING_PROMPT_SHA256,
                        **extra,
                    }
                ),
            )

        update_state("LOCKED")
        _copy_s1_to_staging(snapshot, staging)
        update_state("STAGED")
        event_path = run_dir / "events.jsonl"
        event_path.write_bytes(
            _canonical_json_bytes(
                {"event": "agent_start", "run_id": run_id, "time": _utc_now()}
            )
            + b"\n"
        )

        def event_sink(event: dict) -> None:
            with event_path.open("ab") as handle:
                handle.write(_canonical_json_bytes({"event": "agent_trace", **event}) + b"\n")
                handle.flush()
                os.fsync(handle.fileno())

        update_state("AGENT_RUNNING")
        memory = MemoryFS(staging, run_dir / "trash")
        runner = AgentRunner(
            memory,
            provider,
            max_rounds=max_rounds,
            event_sink=event_sink,
        )
        result = runner.run_foldering()
        update_state("AGENT_SUCCEEDED", rounds=result.rounds, tool_calls=result.tool_calls)

        update_state("GATE_RUNNING")
        pruned = _prune_empty_directories(staging)
        gate = validate_s2_staging(
            snapshot,
            staging,
            pruned_empty_directories=pruned,
        )
        update_state("GATE_PASSED", layout_sha256=gate.layout_sha256)

        after_snapshot = validate_s1_store(
            paths["s1_store"],
            paths["s1_manifest"],
            expected_manifest_sha256=expected_s1_manifest_sha256,
        )
        if (
            after_snapshot.manifest_sha256 != snapshot.manifest_sha256
            or after_snapshot.content_sha256 != snapshot.content_sha256
            or after_snapshot.files != snapshot.files
        ):
            raise S2BuildError("Formal S1 changed while S2 was running")

        finished_at = _utc_now()
        path_map_document = _path_map_document(snapshot, gate)
        path_map_bytes = _pretty_json_bytes(path_map_document)
        trace_document = _episode_document(
            result, provider, run_id, started_at, finished_at
        )
        trace_bytes = _pretty_json_bytes(trace_document)
        path_map_sha256 = _sha256_bytes(path_map_bytes)
        trace_sha256 = _sha256_bytes(trace_bytes)
        manifest_document = _manifest_document(
            snapshot,
            gate,
            result,
            provider,
            run_id=run_id,
            started_at=started_at,
            finished_at=finished_at,
            output_dir=paths["s2_store"],
            path_map_path=paths["path_map"],
            path_map_sha256=path_map_sha256,
            trace_path=paths["trace"],
            trace_sha256=trace_sha256,
            code_revision=code_revision,
        )
        manifest_bytes = _pretty_json_bytes(manifest_document)
        marker_document = {
            "schema_version": 1,
            "artifact_id": manifest_document["artifact_id"],
            "run_id": run_id,
            "committed_at": finished_at,
            "content_sha256": gate.content_sha256,
            "layout_sha256": gate.layout_sha256,
            "manifest_sha256": _sha256_bytes(manifest_bytes),
            "path_map_sha256": path_map_sha256,
            "trace_sha256": trace_sha256,
        }
        marker_bytes = _pretty_json_bytes(marker_document)

        payloads = [
            (paths["trace"], trace_bytes),
            (paths["path_map"], path_map_bytes),
            (paths["s2_manifest"], manifest_bytes),
            (paths["commit_marker"], marker_bytes),
        ]
        for final, payload in payloads:
            temporary_files.append(_publish_file_temporary(final, payload, run_id))
        update_state("PUBLISHING")
        if any(final.exists() or final.is_symlink() for final, _ in payloads):
            raise S2BuildError("A formal S2 artifact appeared during the run; refusing overwrite")
        if paths["s2_store"].exists() or paths["s2_store"].is_symlink():
            raise S2BuildError("S2 output appeared during the run; refusing overwrite")
        os.rename(staging, paths["s2_store"])
        published_store = True
        for temporary, (final, payload) in zip(temporary_files, payloads):
            os.rename(temporary, final)
            published_files.append((final, payload))
        update_state("PUBLISHED", layout_sha256=gate.layout_sha256)
        shutil.rmtree(run_dir)
        return {
            "status": "published",
            "run_id": run_id,
            "source_artifact_id": snapshot.artifact_id,
            "target_artifact_id": manifest_document["artifact_id"],
            "files": len(gate.files),
            "directories": len(gate.directories),
            "content_sha256": gate.content_sha256,
            "layout_sha256": gate.layout_sha256,
            "rounds": result.rounds,
            "tool_calls": result.tool_calls,
            "requested_model": manifest_document["model"]["requested_model"],
            "served_models": manifest_document["model"]["served_models"],
            "preflight": preflight,
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
        if published_store and paths["s2_store"].is_dir() and not staging.exists():
            try:
                os.rename(paths["s2_store"], staging)
            except OSError as cleanup_exc:
                cleanup_errors.append(f"store rollback: {cleanup_exc}")
        run_dir.mkdir(parents=True, exist_ok=True)
        quarantine = run_dir / "quarantine"
        quarantine_path: str | None = None
        if staging.exists() and not quarantine.exists():
            try:
                os.rename(staging, quarantine)
                quarantine_path = "quarantine"
            except OSError:
                quarantine_path = staging.name
        formal_names = ("s2_store", "s2_manifest", "path_map", "trace", "commit_marker")
        residual_formal_outputs = [
            name for name in formal_names
            if paths[name].exists() or paths[name].is_symlink()
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
            "error": {
                "type": type(exc).__name__,
                "message": _redact_text(str(exc)),
            },
            "partial_episode": _redact_value(partial),
            "quarantine": quarantine_path,
            "formal_outputs_published": bool(residual_formal_outputs),
            "residual_formal_outputs": residual_formal_outputs,
            "cleanup_errors": _redact_value(cleanup_errors),
        }
        _atomic_write(run_dir / "failure.json", _pretty_json_bytes(failure))
        if isinstance(exc, (KeyboardInterrupt, SystemExit)):
            raise
        raise S2BuildError(
            f"S2 build failed during {current_state}; diagnostics retained in {run_dir}"
        ) from None
    finally:
        if release_lock:
            _release_owned_lock(lock_path, lock_payload, lock_inode)


def verify_published_s2(
    s1_store: Path,
    s1_manifest: Path,
    s2_store: Path,
    s2_manifest: Path,
    path_map: Path,
    trace: Path,
    commit_marker: Path,
    *,
    expected_s1_manifest_sha256: str | None = EXPECTED_CONV50_S1_MANIFEST_SHA256,
) -> dict[str, Any]:
    """Recompute a published artifact from bytes; never call a model."""
    if _sha256_bytes(FOLDERING_PROMPT.encode("utf-8")) != FROZEN_FOLDERING_PROMPT_SHA256:
        raise S2BuildError("Local foldering prompt no longer matches the published protocol")
    if _sha256_bytes(FOLDERING_TASK.encode("utf-8")) != FROZEN_FOLDERING_TASK_SHA256:
        raise S2BuildError("Local foldering task no longer matches the published protocol")
    if _foldering_tool_schema_sha256() != FROZEN_FOLDERING_TOOL_SCHEMA_SHA256:
        raise S2BuildError("Local foldering tool schema no longer matches the published protocol")
    snapshot = validate_s1_store(
        s1_store,
        s1_manifest,
        expected_manifest_sha256=expected_s1_manifest_sha256,
    )
    manifest, manifest_bytes = _load_json_object(Path(s2_manifest), "S2 manifest")
    path_map_document, path_map_bytes = _load_json_object(Path(path_map), "S2 path map")
    trace_document, trace_bytes = _load_json_object(Path(trace), "S2 trace")
    marker, _ = _load_json_object(Path(commit_marker), "S2 commit marker")
    expected_artifact_hashes = {
        "manifest_sha256": _sha256_bytes(manifest_bytes),
        "path_map_sha256": _sha256_bytes(path_map_bytes),
        "trace_sha256": _sha256_bytes(trace_bytes),
    }
    for field, actual in expected_artifact_hashes.items():
        if marker.get(field) != actual:
            raise S2BuildError(f"S2 commit marker {field} mismatch")
    gate = validate_s2_staging(snapshot, s2_store)
    expected_map = _path_map_document(snapshot, gate)
    if path_map_document != expected_map:
        raise S2BuildError("S2 path map does not match the published tree")

    target_artifact = snapshot.artifact_id.replace("/s1-flat/", "/s2-foldered/")
    run_ids = {
        marker.get("run_id"),
        manifest.get("episode", {}).get("run_id"),
        trace_document.get("run_id"),
    }
    if len(run_ids) != 1 or not all(isinstance(run_id, str) for run_id in run_ids):
        raise S2BuildError("S2 marker, manifest, and trace run_id values disagree")
    if marker.get("artifact_id") != target_artifact or manifest.get("artifact_id") != target_artifact:
        raise S2BuildError("S2 artifact_id cross-link mismatch")
    if marker.get("schema_version") != 1 or manifest.get("schema_version") != S2_SCHEMA_VERSION:
        raise S2BuildError("S2 schema version mismatch")
    if trace_document.get("schema_version") != 1 or trace_document.get("status") != "completed":
        raise S2BuildError("S2 trace is not a completed episode")

    expected_source = {
        "artifact_id": snapshot.artifact_id,
        "manifest_sha256": snapshot.manifest_sha256,
        "content_sha256": snapshot.content_sha256,
        "canonical_sha256": snapshot.manifest.get("input", {}).get("canonical_sha256"),
        "source_map_sha256": snapshot.manifest.get("input", {}).get("source_map_sha256"),
    }
    if manifest.get("source") != expected_source:
        raise S2BuildError("S2 manifest source identity mismatch")

    expected_manifest_protocol = {
        "condition": "S2 Foldered verbatim sessions",
        "prompt_version": FOLDERING_PROMPT_VERSION,
        "prompt_sha256": FROZEN_FOLDERING_PROMPT_SHA256,
        "prompt_provenance": "project-defined reconstruction; author build prompt not published",
        "task_sha256": FROZEN_FOLDERING_TASK_SHA256,
        "tool_profile": list(FOLDERING_PROFILE),
        "tool_schema_sha256": FROZEN_FOLDERING_TOOL_SCHEMA_SHA256,
        "invariants": [
            "whole-session move only",
            "same basename",
            "byte-identical to S1",
            "exactly one topic path per session",
            "no QA or gold inputs mounted",
        ],
    }
    if manifest.get("protocol") != expected_manifest_protocol:
        raise S2BuildError("S2 manifest protocol mismatch")
    expected_trace_protocol = {
        "prompt_version": FOLDERING_PROMPT_VERSION,
        "prompt_sha256": FROZEN_FOLDERING_PROMPT_SHA256,
        "system_prompt": FOLDERING_PROMPT,
        "task": FOLDERING_TASK,
        "task_sha256": FROZEN_FOLDERING_TASK_SHA256,
        "tool_profile": list(FOLDERING_PROFILE),
        "tool_schema_sha256": FROZEN_FOLDERING_TOOL_SCHEMA_SHA256,
    }
    if trace_document.get("protocol") != expected_trace_protocol:
        raise S2BuildError("S2 trace protocol snapshot mismatch")
    if manifest.get("model") != trace_document.get("model"):
        raise S2BuildError("S2 manifest and trace model metadata disagree")

    expected_counts = copy.deepcopy(snapshot.manifest.get("counts", {}))
    expected_counts.update(
        {
            "files": len(gate.files),
            "bytes": gate.total_bytes,
            "directories": len(gate.directories),
            "root_md_files": 0,
            "max_topic_depth": gate.max_depth,
        }
    )
    if manifest.get("counts") != expected_counts:
        raise S2BuildError("S2 manifest counts mismatch")
    if manifest.get("directories") != gate.directories or manifest.get("files") != gate.files:
        raise S2BuildError("S2 manifest tree inventory mismatch")
    if manifest.get("source_index") != _updated_source_index(snapshot, gate):
        raise S2BuildError("S2 manifest source_index mismatch")
    pruned = manifest.get("pruned_empty_directories")
    if not isinstance(pruned, list) or pruned != sorted(set(pruned)) or not all(
        isinstance(path, str) and path for path in pruned
    ):
        raise S2BuildError("S2 manifest pruned-directory record is invalid")

    expected_store = {
        "directory_name": Path(s2_store).resolve(strict=False).name,
        "content_sha256": gate.content_sha256,
        "layout_sha256": gate.layout_sha256,
    }
    if manifest.get("store") != expected_store:
        raise S2BuildError("S2 manifest store identity mismatch")
    if marker.get("content_sha256") != gate.content_sha256:
        raise S2BuildError("S2 commit marker content hash mismatch")
    if marker.get("layout_sha256") != gate.layout_sha256:
        raise S2BuildError("S2 commit marker layout hash mismatch")
    if marker.get("committed_at") != manifest.get("episode", {}).get("finished_at"):
        raise S2BuildError("S2 commit time cross-link mismatch")

    expected_path_map_ref = {
        "filename": Path(path_map).name,
        "sha256": expected_artifact_hashes["path_map_sha256"],
    }
    if manifest.get("path_map") != expected_path_map_ref:
        raise S2BuildError("S2 manifest path-map reference mismatch")
    episode = manifest.get("episode")
    traced_episode = trace_document.get("episode")
    if not isinstance(episode, dict) or not isinstance(traced_episode, dict):
        raise S2BuildError("S2 episode metadata is invalid")
    expected_episode = {
        "run_id": trace_document.get("run_id"),
        "started_at": trace_document.get("started_at"),
        "finished_at": trace_document.get("finished_at"),
        "rounds": traced_episode.get("rounds"),
        "tool_calls": traced_episode.get("tool_calls"),
        "answer_sha256": _sha256_bytes(str(traced_episode.get("answer", "")).encode("utf-8")),
        "trace_filename": Path(trace).name,
        "trace_sha256": expected_artifact_hashes["trace_sha256"],
    }
    if episode != expected_episode:
        raise S2BuildError("S2 manifest episode reference mismatch")
    if (
        traced_episode.get("role") != "foldering"
        or traced_episode.get("configuration") != asdict(FOLDERING)
        or traced_episode.get("prompt_sha256") != FROZEN_FOLDERING_PROMPT_SHA256
        or traced_episode.get("input_sha256")
        != _sha256_bytes(FOLDERING_TASK.encode("utf-8"))
    ):
        raise S2BuildError("S2 trace episode configuration mismatch")
    trace_events = traced_episode.get("trace")
    usage = traced_episode.get("usage")
    if not isinstance(trace_events, list) or not isinstance(usage, list):
        raise S2BuildError("S2 trace events or usage are invalid")
    tool_call_count = sum("tool" in event for event in trace_events if isinstance(event, dict))
    if traced_episode.get("tool_calls") != tool_call_count:
        raise S2BuildError("S2 trace tool-call count mismatch")
    served_models = sorted(
        {
            event["served_model"]
            for event in trace_events
            if isinstance(event, dict)
            and isinstance(event.get("served_model"), str)
            and event["served_model"]
        }
    )
    fingerprints = sorted(
        {
            event["system_fingerprint"]
            for event in trace_events
            if isinstance(event, dict)
            and isinstance(event.get("system_fingerprint"), str)
            and event["system_fingerprint"]
        }
    )
    model = manifest.get("model", {})
    if model.get("served_models") != served_models or model.get("system_fingerprints") != fingerprints:
        raise S2BuildError("S2 served-model trace mismatch")
    expected_build_cost = {
        "llm_calls": sum(
            1 for event in trace_events
            if isinstance(event, dict)
            and ("assistant_content" in event or event.get("compaction") is True)
        ),
        "tool_calls": tool_call_count,
        "usage_totals": _usage_totals(usage),
    }
    if manifest.get("build_cost") != expected_build_cost:
        raise S2BuildError("S2 build-cost record mismatch")

    expected_verification = {
        "s1_revalidated_after_episode": True,
        "file_count_unchanged": True,
        "basename_set_unchanged": True,
        "bytes_identical_to_s1": True,
        "content_sha256_matches_s1": True,
        "all_sessions_nested_once": True,
        "root_has_no_markdown_files": True,
        "no_symlinks_or_non_markdown_files": True,
        "folder_names_are_kebab_case": True,
        "gold_inputs_mounted": False,
        "image_urls_fetched": False,
    }
    if manifest.get("verification") != expected_verification:
        raise S2BuildError("S2 verification claims mismatch")
    generator = manifest.get("generator", {})
    if (
        generator.get("module") != "fs_memory_lab.s2"
        or generator.get("version") != S2_BUILDER_VERSION
        or not isinstance(generator.get("git_commit"), str)
    ):
        raise S2BuildError("S2 generator metadata mismatch")
    return {
        "status": "verified",
        "artifact_id": manifest.get("artifact_id"),
        "files": len(gate.files),
        "directories": len(gate.directories),
        "content_sha256": gate.content_sha256,
        "layout_sha256": gate.layout_sha256,
        "run_id": marker.get("run_id"),
    }
