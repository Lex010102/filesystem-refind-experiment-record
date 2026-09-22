"""Paper-style file tools over one dedicated /memories directory.

No shell is exposed to the model. Paths are virtual, and every operation checks that
its target stays inside the configured memory root, including through symlinks.
"""

from __future__ import annotations

import os
import re
import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path


class ToolError(ValueError):
    """A safe, user-visible tool failure."""


_SLUG = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*\Z")
_HEADING = re.compile(r"^(#{1,6})\s+(.+?)\s*$")


def _frontmatter(text: str) -> tuple[int, str, str]:
    lines = text.splitlines()
    if not lines or lines[0] != "---":
        raise ToolError("File must start with YAML frontmatter on line 1")
    try:
        closing = lines.index("---", 1)
    except ValueError as exc:
        raise ToolError("Missing closing frontmatter fence") from exc
    fields: dict[str, str] = {}
    for line in lines[1:closing]:
        if line.startswith(("name:", "description:")):
            key, value = line.split(":", 1)
            fields[key] = value.strip().strip("\"'")
    name = fields.get("name", "")
    description = fields.get("description", "")
    if not _SLUG.fullmatch(name):
        raise ToolError("Frontmatter name must be a kebab-case slug")
    if not description or "\n" in description:
        raise ToolError("Frontmatter description must be one nonempty line")
    return closing + 1, name, description


def _numbered(text: str, first: int = 1) -> str:
    return "\n".join(f"L{index}: {line}" for index, line in enumerate(text.splitlines(), first))


class MemoryFS:
    """Nine tools: seven management operations and two search-only read tools."""

    management_tools = frozenset({"view", "grep", "create", "str_replace", "insert", "delete", "rename"})
    search_tools = frozenset({"view", "grep", "toc", "section_read"})

    def __init__(self, root: Path, trash_root: Path | None = None):
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.trash_root = Path(trash_root).resolve() if trash_root else None
        if self.trash_root:
            if self.trash_root == self.root or self.root in self.trash_root.parents:
                raise ToolError("Trash must live outside the memory root")
            self.trash_root.mkdir(parents=True, exist_ok=True)

    def _path(self, virtual: str, *, allow_root: bool = True) -> Path:
        if virtual == "/memories":
            if not allow_root:
                raise ToolError("Cannot mutate /memories root")
            return self.root
        if not isinstance(virtual, str) or not virtual.startswith("/memories/"):
            raise ToolError("Path must be /memories or start with /memories/")
        relative = Path(virtual[len("/memories/"):])
        if not relative.parts or any(part in {"", ".", ".."} for part in relative.parts):
            raise ToolError("Invalid memory path")
        candidate = self.root.joinpath(*relative.parts)
        # resolve(strict=False) also follows an existing symlink in a parent directory.
        resolved = candidate.resolve(strict=False)
        if resolved != self.root and self.root not in resolved.parents:
            raise ToolError("Path escapes the memory root")
        if candidate.is_symlink():
            raise ToolError("Symlink targets are not memory files")
        return candidate

    @staticmethod
    def _markdown(path: Path) -> None:
        if path.suffix != ".md":
            raise ToolError("Memory files must end in .md")

    @staticmethod
    def _validate(path: Path, text: str) -> str:
        _, name, description = _frontmatter(text)
        if name != path.stem:
            raise ToolError(f"Frontmatter name {name!r} must equal filename stem {path.stem!r}")
        return description

    @staticmethod
    def _write_atomic(path: Path, text: str) -> None:
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
            handle.write(text)
            temporary = Path(handle.name)
        try:
            os.replace(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)

    def _virtual(self, path: Path) -> str:
        relative = path.relative_to(self.root).as_posix()
        return "/memories" if relative == "." else "/memories/" + relative

    def view(self, path: str, start_line: int = 1, end_line: int = -1) -> str:
        target = self._path(path)
        if not target.exists():
            raise ToolError("Path does not exist")
        if target.is_dir():
            origin_depth = len(target.relative_to(self.root).parts)
            rows: list[str] = []
            for child in sorted(target.rglob("*")):
                depth = len(child.relative_to(self.root).parts) - origin_depth
                if depth > 3 or child.is_symlink():
                    continue
                if child.is_dir():
                    size = sum(file.stat().st_size for file in child.rglob("*")
                               if file.is_file() and not file.is_symlink() and self.root in file.resolve().parents)
                    rows.append(f"{self._virtual(child)}/ ({size} bytes)")
                elif child.suffix == ".md":
                    text = child.read_text(encoding="utf-8")
                    try:
                        description = _frontmatter(text)[2]
                    except ToolError:
                        description = "INVALID FRONTMATTER"
                    rows.append(f"{self._virtual(child)} ({child.stat().st_size} bytes) [description: {description}]")
            return "\n".join(rows) if rows else "(empty memory directory)"
        self._markdown(target)
        lines = target.read_text(encoding="utf-8").splitlines()
        if start_line < 1 or end_line != -1 and end_line < start_line:
            raise ToolError("Invalid line range")
        last = len(lines) if end_line == -1 else min(end_line, len(lines))
        return _numbered("\n".join(lines[start_line - 1:last]), start_line)

    def grep(self, pattern: str, path: str = "/memories", case_sensitive: bool = False, max_results: int = 100) -> str:
        target = self._path(path)
        if not target.exists():
            raise ToolError("Path does not exist")
        if target.is_file():
            self._markdown(target)
        if max_results < 1:
            raise ToolError("max_results must be positive")
        try:
            compiled = re.compile(pattern, 0 if case_sensitive else re.IGNORECASE)
        except re.error as exc:
            raise ToolError(f"Invalid regex: {exc}") from exc
        files = [target] if target.is_file() else sorted(target.rglob("*.md"))
        rows: list[str] = []
        for file in files:
            if file.is_symlink() or self.root not in file.resolve().parents:
                continue
            for number, line in enumerate(file.read_text(encoding="utf-8").splitlines(), 1):
                if compiled.search(line):
                    rows.append(f"{self._virtual(file)}:L{number}: {line}")
                    if len(rows) == max_results:
                        return "\n".join(rows) + "\n(max_results reached)"
        return "\n".join(rows) if rows else "(no matches)"

    def create(self, path: str, file_text: str) -> str:
        target = self._path(path, allow_root=False)
        self._markdown(target)
        self._validate(target, file_text)
        if target.exists():
            raise ToolError("File already exists")
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("x", encoding="utf-8") as handle:
            handle.write(file_text)
        return f"Created {path}"

    def str_replace(self, path: str, old_str: str, new_str: str) -> str:
        target = self._path(path, allow_root=False)
        self._markdown(target)
        if not target.is_file() or not old_str:
            raise ToolError("Existing .md file and nonempty old_str required")
        text = target.read_text(encoding="utf-8")
        closing, _, _ = _frontmatter(text)
        lines = text.splitlines(keepends=True)
        boundary = sum(len(line) for line in lines[:closing])
        front, body = text[:boundary], text[boundary:]
        if body.count(old_str) == 1:
            updated = front + body.replace(old_str, new_str, 1)
        elif body.count(old_str) > 1:
            raise ToolError("old_str occurs more than once in body")
        elif front.count(old_str) == 1:
            updated = front.replace(old_str, new_str, 1) + body
        else:
            raise ToolError("old_str must occur exactly once in body or frontmatter")
        self._validate(target, updated)
        self._write_atomic(target, updated)
        return f"Replaced unique string in {path}"

    def insert(self, path: str, insert_line: int, insert_text: str) -> str:
        target = self._path(path, allow_root=False)
        self._markdown(target)
        if not target.is_file():
            raise ToolError("File does not exist")
        text = target.read_text(encoding="utf-8")
        closing, _, _ = _frontmatter(text)
        lines = text.splitlines(keepends=True)
        if not closing <= insert_line <= len(lines):
            raise ToolError(f"insert_line must be between closing fence line {closing} and {len(lines)}")
        prefix = "".join(lines[:insert_line])
        suffix = "".join(lines[insert_line:])
        if prefix and not prefix.endswith("\n"):
            prefix += "\n"
        updated = prefix + insert_text + ("\n" if insert_text and not insert_text.endswith("\n") else "") + suffix
        self._validate(target, updated)
        self._write_atomic(target, updated)
        return f"Inserted text after L{insert_line} in {path}"

    def delete(self, path: str) -> str:
        target = self._path(path, allow_root=False)
        if not target.exists():
            raise ToolError("Path does not exist")
        if self.trash_root:
            stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
            destination = self.trash_root / stamp / target.relative_to(self.root)
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(target), str(destination))
            # Keep the safety copy local, but do not expose a host path to the model.
            return f"Deleted {path}"
        if target.is_dir():
            shutil.rmtree(target)
        else:
            target.unlink()
        return f"Deleted {path}"

    def rename(self, old_path: str, new_path: str) -> str:
        source = self._path(old_path, allow_root=False)
        destination = self._path(new_path, allow_root=False)
        if not source.exists() or destination.exists():
            raise ToolError("Source must exist and destination must not exist")
        if source.is_dir() and (source == destination or source in destination.parents):
            raise ToolError("Cannot move directory into itself")
        if source.is_file():
            self._markdown(source)
            self._markdown(destination)
            current_name = _frontmatter(source.read_text(encoding="utf-8"))[1]
        else:
            if destination.suffix == ".md":
                raise ToolError("Directory cannot be renamed to a .md path")
            current_name = None
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(source), str(destination))
        note = f"; frontmatter name is still {current_name!r} and may need editing" if current_name else ""
        return f"Moved {old_path} to {new_path}{note}"

    def _headings(self, path: str) -> tuple[Path, list[tuple[int, int, str]]]:
        target = self._path(path, allow_root=False)
        self._markdown(target)
        if not target.is_file():
            raise ToolError("File does not exist")
        headings = []
        for number, line in enumerate(target.read_text(encoding="utf-8").splitlines(), 1):
            match = _HEADING.match(line)
            if match:
                headings.append((number, len(match.group(1)), line.strip()))
        return target, headings

    def toc(self, path: str) -> str:
        target, headings = self._headings(path)
        total = len(target.read_text(encoding="utf-8").splitlines())
        rows = []
        for index, (start, level, label) in enumerate(headings):
            stop = total
            for next_start, next_level, _ in headings[index + 1:]:
                if next_level <= level:
                    stop = next_start - 1
                    break
            rows.append(f"L{start}-{stop}: {label}")
        return "\n".join(rows) if rows else "(no headings)"

    def section_read(self, path: str, section_path: str) -> str:
        target, headings = self._headings(path)
        segments = [piece.strip() for piece in section_path.split(" > ")]
        if not segments or len(segments) == 1 and not segments[0].startswith("# "):
            raise ToolError("section_path must start with a top-level '# ' heading")
        stack: list[str] = []
        selected: tuple[int, int] | None = None
        for start, level, label in headings:
            stack = stack[:level - 1]
            stack.append(label)
            if stack == segments:
                selected = (start, level)
                break
        if selected is None:
            raise ToolError("Section not found")
        start, level = selected
        lines = target.read_text(encoding="utf-8").splitlines()
        stop = len(lines)
        for next_start, next_level, _ in headings:
            if next_start > start and next_level <= level:
                stop = next_start - 1
                break
        return _numbered("\n".join(lines[start - 1:stop]), start)

    def call(self, role: str, name: str, args: dict) -> str:
        allowed = self.management_tools if role == "management" else self.search_tools if role == "search" else None
        if allowed is None or name not in allowed:
            raise ToolError(f"Tool {name!r} is not available to role {role!r}")
        method = getattr(self, name)
        try:
            return method(**args)
        except TypeError as exc:
            raise ToolError(f"Invalid arguments for {name}: {exc}") from exc
