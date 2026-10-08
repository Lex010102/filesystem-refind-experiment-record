"""Frozen, read-only filesystem surface for R1 evidence retrieval.

The four function descriptions and parameter declarations are transcribed from
Filesystem-Based Memory for LLM Agents, Appendix C.4, Table 12.  The complete
JSON function wrapper, ordering, defaults and runtime semantics are local,
versioned reconstruction choices and are never described as author source code.
"""

from __future__ import annotations

import json
import os
import re
import signal
import stat
import threading
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from pathlib import Path, PurePosixPath
from types import MappingProxyType
from typing import Any, Iterator, Mapping

from .evidence import (
    EvidenceValidationError,
    SourceCatalog,
    StoreSnapshotRef,
    VerifiedStoreManifest,
    canonical_json_bytes,
    sha256_bytes,
    validate_store_snapshot,
)
from .markdown_structure import parse_markdown_headings
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
FROZEN_R1_PROJECT_LIMITS_SHA256 = (
    "776bbabd5946fba68acc3cbcaec02e82b81ba023002502c8281f1f364c81ecf7"
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
R1_PROJECT_LIMITS = MappingProxyType(
    {
        "max_output_bytes": 1_048_576,
        "max_pattern_chars": 512,
        "max_results_limit": 1_000,
        "regex_timeout_millis": 1_000,
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


def r1_project_limits_sha256() -> str:
    return sha256_bytes(canonical_json_bytes(R1_PROJECT_LIMITS))


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
        "project limits": (
            r1_project_limits_sha256(),
            FROZEN_R1_PROJECT_LIMITS_SHA256,
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


class R1ToolError(ValueError):
    """Safe, model-visible failure from a read-only filesystem call."""

    def __init__(self, code: str, message: str):
        if not isinstance(code, str) or not re.fullmatch(r"[a-z][a-z0-9_]*", code):
            raise ValueError("R1 tool error code is invalid")
        if not isinstance(message, str) or not message:
            raise ValueError("R1 tool error message is invalid")
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class LineCoverage:
    """Inclusive source lines actually returned to the model."""

    path: str
    line_start: int
    line_end: int

    def __post_init__(self) -> None:
        if not isinstance(self.path, str) or not self.path.startswith("/memories/"):
            raise EvidenceValidationError("Coverage path is invalid")
        try:
            self.path.encode("utf-8", errors="strict")
        except UnicodeEncodeError as exc:
            raise EvidenceValidationError("Coverage path must be valid UTF-8") from exc
        relative_text = self.path[len("/memories/") :]
        relative = PurePosixPath(relative_text)
        if (
            not relative.parts
            or relative.suffix != ".md"
            or relative.as_posix() != relative_text
            or any(part in {"", ".", ".."} for part in relative.parts)
            or any(
                ord(character) < 32 or ord(character) == 127
                for character in relative_text
            )
        ):
            raise EvidenceValidationError("Coverage path is invalid")
        for value, label in (
            (self.line_start, "coverage line_start"),
            (self.line_end, "coverage line_end"),
        ):
            if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                raise EvidenceValidationError(f"{label} must be a positive integer")
        if self.line_end < self.line_start:
            raise EvidenceValidationError("Coverage line range is reversed")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _freeze_scalar_arguments(value: Mapping[str, Any]) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise EvidenceValidationError("Tool canonical_args must be an object")
    plain = json.loads(canonical_json_bytes(value))
    if any(isinstance(nested, (dict, list)) for nested in plain.values()):
        raise EvidenceValidationError("Tool canonical_args must contain only scalars")
    return MappingProxyType(plain)


@dataclass(frozen=True)
class ReadToolResult:
    """Content-addressed successful result; Stage 4 assigns observation IDs."""

    protocol_version: str
    tool_name: str
    canonical_args: Mapping[str, Any]
    content: str
    content_sha256: str
    coverage: tuple[LineCoverage, ...]
    truncated: bool
    result_count: int
    root_survey: bool
    whole_tree_grep: bool
    pre_tree_sha256: str
    post_tree_sha256: str
    result_sha256: str

    def __post_init__(self) -> None:
        if self.protocol_version != R1_FILESYSTEM_PROTOCOL_VERSION:
            raise EvidenceValidationError("Read result protocol version mismatch")
        if self.tool_name not in R1_FILESYSTEM_TOOL_NAMES:
            raise EvidenceValidationError("Read result tool name is invalid")
        frozen_args = _freeze_scalar_arguments(self.canonical_args)
        if not isinstance(self.content, str):
            raise EvidenceValidationError("Read result content must be text")
        if not self.content:
            raise EvidenceValidationError("Read result content must not be empty")
        if sha256_bytes(self.content.encode("utf-8")) != self.content_sha256:
            raise EvidenceValidationError("Read result content hash is invalid")
        if not isinstance(self.coverage, (list, tuple)):
            raise EvidenceValidationError("Read result coverage must be ordered")
        coverage = tuple(self.coverage)
        if any(not isinstance(item, LineCoverage) for item in coverage):
            raise EvidenceValidationError("Read result coverage item is invalid")
        if not isinstance(self.truncated, bool):
            raise EvidenceValidationError("Read result truncated must be bool")
        if (
            isinstance(self.result_count, bool)
            or not isinstance(self.result_count, int)
            or self.result_count < 0
        ):
            raise EvidenceValidationError("Read result count must be nonnegative")
        if not isinstance(self.root_survey, bool) or not isinstance(
            self.whole_tree_grep, bool
        ):
            raise EvidenceValidationError("Read result scope flags must be bool")
        for digest, label in (
            (self.pre_tree_sha256, "pre_tree_sha256"),
            (self.post_tree_sha256, "post_tree_sha256"),
            (self.result_sha256, "result_sha256"),
        ):
            if not isinstance(digest, str) or re.fullmatch(r"[0-9a-f]{64}", digest) is None:
                raise EvidenceValidationError(f"{label} is invalid")
        if self.pre_tree_sha256 != self.post_tree_sha256:
            raise EvidenceValidationError("Successful read result cannot span tree drift")
        path = frozen_args.get("path")
        expected_root_survey = self.tool_name == "view" and path == "/memories"
        if self.root_survey != expected_root_survey:
            raise EvidenceValidationError("Read result root_survey flag is inconsistent")
        expected_whole_tree_grep = (
            self.tool_name == "grep" and path == "/memories" and not self.truncated
        )
        if self.whole_tree_grep != expected_whole_tree_grep:
            raise EvidenceValidationError(
                "Read result whole_tree_grep flag is inconsistent"
            )
        if self.truncated and self.tool_name != "grep":
            raise EvidenceValidationError("Only grep results may be truncated")
        if self.tool_name == "grep" and self.result_count != len(coverage):
            raise EvidenceValidationError("Grep result_count differs from coverage")
        if self.tool_name == "toc" and coverage:
            raise EvidenceValidationError("TOC routing output cannot claim line coverage")
        if self.tool_name == "view" and path == "/memories" and coverage:
            raise EvidenceValidationError("Directory view cannot claim line coverage")
        object.__setattr__(self, "canonical_args", frozen_args)
        object.__setattr__(self, "coverage", coverage)
        expected = sha256_bytes(canonical_json_bytes(self._body()))
        if expected != self.result_sha256:
            raise EvidenceValidationError("Read result identity is invalid")

    def _body(self) -> dict[str, Any]:
        return {
            "protocol_version": self.protocol_version,
            "tool_name": self.tool_name,
            "canonical_args": dict(self.canonical_args),
            "content": self.content,
            "content_sha256": self.content_sha256,
            "coverage": [item.to_dict() for item in self.coverage],
            "truncated": self.truncated,
            "result_count": self.result_count,
            "root_survey": self.root_survey,
            "whole_tree_grep": self.whole_tree_grep,
            "pre_tree_sha256": self.pre_tree_sha256,
            "post_tree_sha256": self.post_tree_sha256,
        }

    def to_dict(self) -> dict[str, Any]:
        return {**self._body(), "result_sha256": self.result_sha256}

    @classmethod
    def create(
        cls,
        *,
        tool_name: str,
        canonical_args: Mapping[str, Any],
        content: str,
        coverage: tuple[LineCoverage, ...],
        truncated: bool,
        result_count: int,
        root_survey: bool,
        whole_tree_grep: bool,
        pre_tree_sha256: str,
        post_tree_sha256: str,
    ) -> "ReadToolResult":
        frozen_args = _freeze_scalar_arguments(canonical_args)
        content_sha256 = sha256_bytes(content.encode("utf-8"))
        body = {
            "protocol_version": R1_FILESYSTEM_PROTOCOL_VERSION,
            "tool_name": tool_name,
            "canonical_args": dict(frozen_args),
            "content": content,
            "content_sha256": content_sha256,
            "coverage": [item.to_dict() for item in coverage],
            "truncated": truncated,
            "result_count": result_count,
            "root_survey": root_survey,
            "whole_tree_grep": whole_tree_grep,
            "pre_tree_sha256": pre_tree_sha256,
            "post_tree_sha256": post_tree_sha256,
        }
        return cls(
            protocol_version=R1_FILESYSTEM_PROTOCOL_VERSION,
            tool_name=tool_name,
            canonical_args=frozen_args,
            content=content,
            content_sha256=content_sha256,
            coverage=coverage,
            truncated=truncated,
            result_count=result_count,
            root_survey=root_survey,
            whole_tree_grep=whole_tree_grep,
            pre_tree_sha256=pre_tree_sha256,
            post_tree_sha256=post_tree_sha256,
            result_sha256=sha256_bytes(canonical_json_bytes(body)),
        )


@dataclass(frozen=True)
class _RawRead:
    content: str
    coverage: tuple[LineCoverage, ...] = ()
    truncated: bool = False
    result_count: int = 0
    root_survey: bool = False
    whole_tree_grep: bool = False


@dataclass(frozen=True)
class _MountedPath:
    """Manifest-derived path classification; never inferred from live directory state."""

    relative: str
    is_file: bool

    @property
    def is_directory(self) -> bool:
        return not self.is_file


class _RegexDeadlineExpired(Exception):
    pass


@contextmanager
def _regex_deadline(milliseconds: int) -> Iterator[None]:
    """Bound Python ``re`` execution on the formal macOS/Linux main thread."""
    if threading.current_thread() is not threading.main_thread():
        raise R1ToolError("regex_environment", "Regex search requires the main thread")
    if not all(hasattr(signal, name) for name in ("SIGALRM", "setitimer", "getitimer")):
        raise R1ToolError("regex_environment", "Regex timeout is unavailable")
    if signal.getitimer(signal.ITIMER_REAL) != (0.0, 0.0):
        raise R1ToolError("regex_environment", "Another real-time alarm is active")
    previous_handler = signal.getsignal(signal.SIGALRM)

    def expire(_signum: int, _frame: Any) -> None:
        raise _RegexDeadlineExpired

    signal.signal(signal.SIGALRM, expire)
    signal.setitimer(signal.ITIMER_REAL, milliseconds / 1000.0)
    try:
        yield
    except _RegexDeadlineExpired as exc:
        raise R1ToolError("regex_timeout", "Regex search exceeded its time limit") from exc
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0.0)
        signal.signal(signal.SIGALRM, previous_handler)


class R1ReadOnlyFilesystem:
    """Strict four-tool executor bound to one verified immutable store."""

    def __init__(
        self,
        *,
        root: Path,
        catalog: SourceCatalog,
        verified_manifest: VerifiedStoreManifest,
        snapshot: StoreSnapshotRef,
    ) -> None:
        verify_r1_filesystem_tool_freeze()
        raw_root = Path(root)
        if raw_root.is_symlink() or not raw_root.is_dir():
            raise EvidenceValidationError(
                "R1 store root must already exist as a non-symlink directory"
            )
        validate_store_snapshot(
            snapshot,
            root=raw_root,
            catalog=catalog,
            verified_manifest=verified_manifest,
        )
        self._root = raw_root.resolve()
        self._catalog = catalog
        self._verified_manifest = verified_manifest
        self._snapshot = snapshot
        self._file_paths = frozenset(verified_manifest.file_paths)
        self._directory_paths = frozenset(("", *verified_manifest.directory_paths))

    @property
    def store_id(self) -> str:
        return self._snapshot.store_id

    @property
    def snapshot_tree_sha256(self) -> str:
        return self._snapshot.tree_sha256

    def authenticate_result(self, result: ReadToolResult) -> None:
        """Replay a claimed result locally before an evidence ledger trusts it."""
        if not isinstance(result, ReadToolResult):
            raise EvidenceValidationError("Claimed read result has the wrong type")
        if (
            result.pre_tree_sha256 != self._snapshot.tree_sha256
            or result.post_tree_sha256 != self._snapshot.tree_sha256
        ):
            raise EvidenceValidationError("Read result belongs to another store snapshot")
        replay_args = dict(result.canonical_args)
        directory_view = False
        if result.tool_name == "view":
            replay_path = replay_args.get("path")
            if not isinstance(replay_path, str):
                raise EvidenceValidationError("View result lacks a valid path argument")
            directory_view = self._resolve(replay_path).is_directory
        if directory_view:
            expected_directory_args = {
                "path": replay_args["path"],
                "start_line": R1_PROJECT_DEFAULTS["view"]["start_line"],
                "end_line": R1_PROJECT_DEFAULTS["view"]["end_line"],
            }
            if replay_args != expected_directory_args:
                raise EvidenceValidationError(
                    "Directory view result has noncanonical arguments"
                )
            self._validate_snapshot()
            try:
                raw = self._view(replay_args, {"path": replay_args["path"]})
            except Exception:
                self._validate_snapshot()
                raise
            self._validate_snapshot()
            replayed = ReadToolResult.create(
                tool_name="view",
                canonical_args=replay_args,
                content=raw.content,
                coverage=raw.coverage,
                truncated=raw.truncated,
                result_count=raw.result_count,
                root_survey=raw.root_survey,
                whole_tree_grep=raw.whole_tree_grep,
                pre_tree_sha256=self._snapshot.tree_sha256,
                post_tree_sha256=self._snapshot.tree_sha256,
            )
        else:
            replayed = self.execute(result.tool_name, replay_args)
        if replayed != result:
            raise EvidenceValidationError(
                "Read result does not match a verified local replay"
            )

    def _validate_snapshot(self) -> None:
        validate_store_snapshot(
            self._snapshot,
            root=self._root,
            catalog=self._catalog,
            verified_manifest=self._verified_manifest,
        )

    @staticmethod
    def _require_exact_keys(
        args: Mapping[str, Any], *, required: set[str], allowed: set[str], name: str
    ) -> None:
        if not isinstance(args, Mapping):
            raise R1ToolError("invalid_arguments", f"{name} arguments must be an object")
        if any(not isinstance(key, str) for key in args):
            raise R1ToolError("invalid_arguments", f"{name} argument keys must be strings")
        keys = set(args)
        missing = required - keys
        extra = keys - allowed
        if missing:
            raise R1ToolError(
                "invalid_arguments", f"{name} is missing required arguments: {sorted(missing)}"
            )
        if extra:
            raise R1ToolError(
                "invalid_arguments", f"{name} has unexpected arguments: {sorted(extra)}"
            )

    @staticmethod
    def _string(value: Any, label: str, *, nonempty: bool = True) -> str:
        if not isinstance(value, str) or (nonempty and not value):
            raise R1ToolError("invalid_arguments", f"{label} must be a string")
        if "\x00" in value:
            raise R1ToolError("invalid_arguments", f"{label} contains a null byte")
        try:
            value.encode("utf-8", errors="strict")
        except UnicodeEncodeError as exc:
            raise R1ToolError(
                "invalid_arguments", f"{label} must be valid UTF-8 text"
            ) from exc
        return value

    @staticmethod
    def _integer(value: Any, label: str) -> int:
        if isinstance(value, bool) or not isinstance(value, int):
            raise R1ToolError("invalid_arguments", f"{label} must be an integer")
        return value

    @staticmethod
    def _boolean(value: Any, label: str) -> bool:
        if not isinstance(value, bool):
            raise R1ToolError("invalid_arguments", f"{label} must be a boolean")
        return value

    def _canonical_arguments(self, name: str, args: Mapping[str, Any]) -> dict[str, Any]:
        if name == "view":
            self._require_exact_keys(
                args,
                required={"path"},
                allowed={"path", "start_line", "end_line"},
                name=name,
            )
            path = self._string(args["path"], "path")
            start = self._integer(args.get("start_line", 1), "start_line")
            end = self._integer(args.get("end_line", -1), "end_line")
            if start < 1 or (end != -1 and end < start):
                raise R1ToolError("invalid_arguments", "view line range is invalid")
            return {"path": path, "start_line": start, "end_line": end}
        if name == "grep":
            self._require_exact_keys(
                args,
                required={"pattern"},
                allowed={"pattern", "path", "case_sensitive", "max_results"},
                name=name,
            )
            pattern = self._string(args["pattern"], "pattern")
            path = self._string(args.get("path", "/memories"), "path")
            case_sensitive = self._boolean(
                args.get("case_sensitive", False), "case_sensitive"
            )
            max_results = self._integer(args.get("max_results", 100), "max_results")
            if len(pattern) > R1_PROJECT_LIMITS["max_pattern_chars"]:
                raise R1ToolError("resource_limit", "Regex pattern is too long")
            if not 1 <= max_results <= R1_PROJECT_LIMITS["max_results_limit"]:
                raise R1ToolError("resource_limit", "max_results is outside the frozen limit")
            return {
                "pattern": pattern,
                "path": path,
                "case_sensitive": case_sensitive,
                "max_results": max_results,
            }
        if name == "toc":
            self._require_exact_keys(args, required={"path"}, allowed={"path"}, name=name)
            return {"path": self._string(args["path"], "path")}
        if name == "section_read":
            self._require_exact_keys(
                args,
                required={"path", "section_path"},
                allowed={"path", "section_path"},
                name=name,
            )
            return {
                "path": self._string(args["path"], "path"),
                "section_path": self._string(args["section_path"], "section_path"),
            }
        raise R1ToolError("unknown_tool", "Only the four frozen R1 tools are available")

    def _resolve(self, virtual: str) -> _MountedPath:
        if virtual == "/memories":
            return _MountedPath(relative="", is_file=False)
        if not virtual.startswith("/memories/") or "\\" in virtual or virtual.endswith("/"):
            raise R1ToolError("invalid_path", "Path must use canonical /memories POSIX form")
        relative_text = virtual[len("/memories/") :]
        if any(ord(character) < 32 or ord(character) == 127 for character in relative_text):
            raise R1ToolError("invalid_path", "Path contains a control character")
        relative = PurePosixPath(relative_text)
        if (
            not relative.parts
            or relative.as_posix() != relative_text
            or any(part in {"", ".", ".."} for part in relative.parts)
        ):
            raise R1ToolError("invalid_path", "Path is not canonical")
        if relative_text in self._file_paths:
            return _MountedPath(relative=relative_text, is_file=True)
        if relative_text in self._directory_paths:
            return _MountedPath(relative=relative_text, is_file=False)
        raise R1ToolError("not_found", "Path is absent from the verified store")

    @staticmethod
    def _virtual(relative: str) -> str:
        return "/memories" if not relative else "/memories/" + relative

    @staticmethod
    def _require_markdown_file(path: _MountedPath) -> None:
        if not path.is_file or PurePosixPath(path.relative).suffix != ".md":
            raise R1ToolError("wrong_path_type", "Tool requires a Markdown file")

    @staticmethod
    def _is_below(parent: str, candidate: str) -> bool:
        parent_parts = PurePosixPath(parent).parts if parent else ()
        candidate_parts = PurePosixPath(candidate).parts
        return (
            len(candidate_parts) > len(parent_parts)
            and candidate_parts[: len(parent_parts)] == parent_parts
        )

    def _read_file_bytes_no_follow(self, relative: str) -> bytes:
        """Read untrusted bytes through no-follow descriptors for later hash proof."""
        if relative not in self._file_paths:
            raise R1ToolError("not_found", "File is absent from the verified store")
        if any(not hasattr(os, flag) for flag in ("O_NOFOLLOW", "O_DIRECTORY")):
            raise R1ToolError(
                "unsafe_environment", "No-follow filesystem reads are unavailable"
            )
        directory_flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
        file_flags = os.O_RDONLY | os.O_NOFOLLOW
        if hasattr(os, "O_CLOEXEC"):
            directory_flags |= os.O_CLOEXEC
            file_flags |= os.O_CLOEXEC
        current_fd: int | None = None
        file_fd: int | None = None
        try:
            current_fd = os.open(self._root, directory_flags)
            parts = PurePosixPath(relative).parts
            for part in parts[:-1]:
                next_fd = os.open(part, directory_flags, dir_fd=current_fd)
                os.close(current_fd)
                current_fd = next_fd
            file_fd = os.open(parts[-1], file_flags, dir_fd=current_fd)
            if not stat.S_ISREG(os.fstat(file_fd).st_mode):
                raise R1ToolError("unsafe_path", "Memory path is not a regular file")
            chunks: list[bytes] = []
            total = 0
            while True:
                chunk = os.read(file_fd, 64 * 1024)
                if not chunk:
                    break
                total += len(chunk)
                if total > self._verified_manifest.total_bytes:
                    raise R1ToolError(
                        "resource_limit", "Memory file exceeds the verified store size"
                    )
                chunks.append(chunk)
            return b"".join(chunks)
        except OSError as exc:
            raise R1ToolError("read_error", "Memory file could not be read") from exc
        finally:
            if file_fd is not None:
                os.close(file_fd)
            if current_fd is not None:
                os.close(current_fd)

    def _read_verified_bytes(self, relative: str) -> bytes:
        payload = self._read_file_bytes_no_follow(relative)
        self._verified_manifest.assert_file_payload(relative, payload)
        return payload

    def _read_verified_text(self, relative: str) -> str:
        payload = self._read_verified_bytes(relative)
        try:
            return payload.decode("utf-8", errors="strict")
        except UnicodeDecodeError as exc:  # manifest loader already proves UTF-8
            raise EvidenceValidationError(
                "Verified memory payload is not valid UTF-8"
            ) from exc

    @staticmethod
    def _description(text: str) -> str:
        lines = text.splitlines()
        if not lines or lines[0] != "---":
            raise R1ToolError("invalid_frontmatter", "Memory file has no YAML frontmatter")
        try:
            closing = lines.index("---", 1)
        except ValueError as exc:
            raise R1ToolError("invalid_frontmatter", "Memory frontmatter is incomplete") from exc
        values = []
        for line in lines[1:closing]:
            if line.startswith("description:"):
                values.append(line.split(":", 1)[1].strip().strip("\"'"))
        if len(values) != 1 or not values[0]:
            raise R1ToolError(
                "invalid_frontmatter", "Memory frontmatter needs one description"
            )
        return values[0]

    @staticmethod
    def _numbered(lines: list[str], first: int) -> str:
        return "\n".join(
            f"L{number}: {line}" for number, line in enumerate(lines, first)
        )

    def _bounded_content(self, content: str) -> str:
        if len(content.encode("utf-8")) > R1_PROJECT_LIMITS["max_output_bytes"]:
            raise R1ToolError("resource_limit", "Tool output exceeds the frozen byte limit")
        return content

    def _view(self, args: Mapping[str, Any], supplied: Mapping[str, Any]) -> _RawRead:
        target = self._resolve(args["path"])
        if target.is_directory:
            if "start_line" in supplied or "end_line" in supplied:
                raise R1ToolError(
                    "invalid_arguments", "Line ranges cannot be used on a directory"
                )
            byte_cache: dict[str, bytes] = {}

            def payload(relative: str) -> bytes:
                if relative not in byte_cache:
                    byte_cache[relative] = self._read_verified_bytes(relative)
                return byte_cache[relative]

            target_depth = len(PurePosixPath(target.relative).parts) if target.relative else 0
            entries = sorted(
                [
                    *((relative, False) for relative in self._directory_paths if relative),
                    *((relative, True) for relative in self._file_paths),
                ],
                key=lambda item: item[0],
            )
            rows: list[str] = []
            for relative, is_file in entries:
                if not self._is_below(target.relative, relative):
                    continue
                depth = len(PurePosixPath(relative).parts) - target_depth
                if depth > 3:
                    continue
                if not is_file:
                    size = sum(
                        len(payload(nested))
                        for nested in self._file_paths
                        if self._is_below(relative, nested)
                    )
                    rows.append(f"{self._virtual(relative)}/ ({size} bytes)")
                else:
                    file_payload = payload(relative)
                    try:
                        text = file_payload.decode("utf-8", errors="strict")
                    except UnicodeDecodeError as exc:  # proven by manifest loader
                        raise EvidenceValidationError(
                            "Verified memory payload is not valid UTF-8"
                        ) from exc
                    description = self._description(text)
                    rows.append(
                        f"{self._virtual(relative)} ({len(file_payload)} bytes) "
                        f"[description: {description}]"
                    )
            content = "\n".join(rows) if rows else "(empty memory directory)"
            return _RawRead(
                content=self._bounded_content(content),
                result_count=len(rows),
                root_survey=not target.relative,
            )
        self._require_markdown_file(target)
        lines = self._read_verified_text(target.relative).splitlines()
        start = args["start_line"]
        if start > len(lines):
            raise R1ToolError("invalid_range", "start_line exceeds the file length")
        stop = len(lines) if args["end_line"] == -1 else min(args["end_line"], len(lines))
        selected = lines[start - 1 : stop]
        content = self._bounded_content(self._numbered(selected, start))
        return _RawRead(
            content=content,
            coverage=(LineCoverage(args["path"], start, stop),),
            result_count=len(selected),
        )

    def _grep(self, args: Mapping[str, Any]) -> _RawRead:
        target = self._resolve(args["path"])
        if target.is_file:
            self._require_markdown_file(target)
            files = [target.relative]
        else:
            files = sorted(
                relative
                for relative in self._file_paths
                if self._is_below(target.relative, relative)
            )
        try:
            compiled = re.compile(
                args["pattern"], 0 if args["case_sensitive"] else re.IGNORECASE
            )
        except (re.error, RecursionError, OverflowError) as exc:
            raise R1ToolError(
                "invalid_regex", "Regex could not be compiled safely"
            ) from exc
        matches: list[tuple[str, int, str]] = []
        truncated = False
        try:
            with _regex_deadline(R1_PROJECT_LIMITS["regex_timeout_millis"]):
                for relative in files:
                    for number, line in enumerate(
                        self._read_verified_text(relative).splitlines(), 1
                    ):
                        if compiled.search(line):
                            if len(matches) == args["max_results"]:
                                truncated = True
                                break
                            matches.append((relative, number, line))
                    if truncated:
                        break
        except (RecursionError, OverflowError) as exc:
            raise R1ToolError(
                "invalid_regex", "Regex could not be evaluated safely"
            ) from exc
        rows = [
            f"{self._virtual(relative)}:L{number}: {line}"
            for relative, number, line in matches
        ]
        if truncated:
            rows.append("(max_results reached)")
        content = "\n".join(rows) if rows else "(no matches)"
        coverage = tuple(
            LineCoverage(self._virtual(relative), number, number)
            for relative, number, _line in matches
        )
        whole_tree = args["path"] == "/memories" and not truncated
        return _RawRead(
            content=self._bounded_content(content),
            coverage=coverage,
            truncated=truncated,
            result_count=len(matches),
            whole_tree_grep=whole_tree,
        )

    @staticmethod
    def _headings(lines: list[str]) -> list[tuple[int, int, str, tuple[str, ...]]]:
        return parse_markdown_headings(lines)

    def _toc(self, args: Mapping[str, Any]) -> _RawRead:
        target = self._resolve(args["path"])
        self._require_markdown_file(target)
        lines = self._read_verified_text(target.relative).splitlines()
        headings = self._headings(lines)
        rows: list[str] = []
        for index, (start, level, label, _path) in enumerate(headings):
            stop = len(lines)
            for next_start, next_level, _next_label, _next_path in headings[index + 1 :]:
                if next_level <= level:
                    stop = next_start - 1
                    break
            rows.append(f"L{start}-{stop}: {label}")
        content = "\n".join(rows) if rows else "(no headings)"
        return _RawRead(content=self._bounded_content(content), result_count=len(rows))

    def _section_read(self, args: Mapping[str, Any]) -> _RawRead:
        target = self._resolve(args["path"])
        self._require_markdown_file(target)
        section_path = args["section_path"]
        if any(ord(character) < 32 or ord(character) == 127 for character in section_path):
            raise R1ToolError(
                "invalid_section_path", "section_path contains a control character"
            )
        segments = section_path.split(" > ")
        if (
            not segments
            or " > ".join(segments) != section_path
            or not segments[0].startswith("# ")
            or any(re.fullmatch(r"#{1,6} .+", segment) is None for segment in segments)
        ):
            raise R1ToolError(
                "invalid_section_path",
                "section_path must start at '# ' and use exact ' > ' delimiters",
            )
        levels = [len(segment) - len(segment.lstrip("#")) for segment in segments]
        if levels[0] != 1 or any(
            current <= previous for previous, current in zip(levels, levels[1:])
        ):
            raise R1ToolError(
                "invalid_section_path", "section_path heading levels must be nested"
            )
        lines = self._read_verified_text(target.relative).splitlines()
        headings = self._headings(lines)
        candidates = [entry for entry in headings if entry[3] == tuple(segments)]
        if not candidates:
            raise R1ToolError("section_not_found", "Section was not found")
        if len(candidates) > 1:
            raise R1ToolError("ambiguous_section", "Section path is ambiguous")
        start, level, _label, _path = candidates[0]
        stop = len(lines)
        for next_start, next_level, _next_label, _next_path in headings:
            if next_start > start and next_level <= level:
                stop = next_start - 1
                break
        content = self._bounded_content(self._numbered(lines[start - 1 : stop], start))
        return _RawRead(
            content=content,
            coverage=(LineCoverage(args["path"], start, stop),),
            result_count=stop - start + 1,
        )

    def execute(self, name: str, args: Mapping[str, Any]) -> ReadToolResult:
        """Execute one reviewed read call and prove the store stayed unchanged."""
        if not isinstance(name, str):
            raise R1ToolError("unknown_tool", "Tool name must be a string")
        canonical_args = self._canonical_arguments(name, args)
        self._validate_snapshot()
        try:
            if name == "view":
                raw = self._view(canonical_args, args)
            elif name == "grep":
                raw = self._grep(canonical_args)
            elif name == "toc":
                raw = self._toc(canonical_args)
            elif name == "section_read":
                raw = self._section_read(canonical_args)
            else:  # guarded by _canonical_arguments
                raise R1ToolError("unknown_tool", "Unknown R1 filesystem tool")
        except Exception:
            self._validate_snapshot()
            raise
        self._validate_snapshot()
        tree = self._snapshot.tree_sha256
        return ReadToolResult.create(
            tool_name=name,
            canonical_args=canonical_args,
            content=raw.content,
            coverage=raw.coverage,
            truncated=raw.truncated,
            result_count=raw.result_count,
            root_survey=raw.root_survey,
            whole_tree_grep=raw.whole_tree_grep,
            pre_tree_sha256=tree,
            post_tree_sha256=tree,
        )
