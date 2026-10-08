"""Shared Markdown structure parsing for R1 reads and evidence attribution."""

from __future__ import annotations

import re
from typing import Sequence


Heading = tuple[int, int, str, tuple[str, ...]]


def parse_markdown_headings(lines: Sequence[str]) -> list[Heading]:
    """Return real ATX headings, excluding YAML frontmatter and fenced code."""
    headings: list[Heading] = []
    stack: list[str] = []
    in_fence = False
    fence_char = ""
    fence_length = 0
    frontmatter_end = 0
    if lines and lines[0] == "---":
        try:
            frontmatter_end = lines.index("---", 1) + 1
        except ValueError:
            frontmatter_end = len(lines)
    for number, line in enumerate(lines, 1):
        if number <= frontmatter_end:
            continue
        fence = re.match(r"^ {0,3}(`{3,}|~{3,})", line)
        if fence:
            marker = fence.group(1)
            if not in_fence:
                in_fence = True
                fence_char = marker[0]
                fence_length = len(marker)
            elif marker[0] == fence_char and len(marker) >= fence_length:
                in_fence = False
            continue
        if in_fence:
            continue
        match = re.match(r"^(#{1,6})[ \t]+(.+?)[ \t]*$", line)
        if not match:
            continue
        level = len(match.group(1))
        label = line.strip()
        stack = stack[: level - 1]
        stack.append(label)
        headings.append((number, level, label, tuple(stack)))
    return headings
