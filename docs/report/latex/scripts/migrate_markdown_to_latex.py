#!/usr/bin/env python3
"""Deterministically migrate the audited Chapter 1--6 Markdown drafts to LaTeX.

The Markdown files remain the prose source of truth. This script adds the formal
LaTeX structure that the drafts intentionally do not carry: BibTeX citations,
numbered figure/table environments, stable labels, cross-references, and
layout-aware table wrappers.
"""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path


PROJECT_DIR = Path(__file__).resolve().parents[1]
REPORT_DIR = PROJECT_DIR.parent
CHAPTER_DIR = PROJECT_DIR / "chapters"

CHAPTERS = (
    (1, REPORT_DIR / "chapter-1-introduction.md", "chapter-01-introduction.tex"),
    (2, REPORT_DIR / "chapter-2-background-and-related-work.md", "chapter-02-background-and-related-work.tex"),
    (3, REPORT_DIR / "chapter-3-system-design-and-methodology.md", "chapter-03-system-design-and-methodology.tex"),
    (4, REPORT_DIR / "chapter-4-experimental-design-and-evaluation-methodology.md", "chapter-04-experimental-design-and-evaluation-methodology.tex"),
    (5, REPORT_DIR / "chapter-5-new.md", "chapter-05-results-and-analysis.tex"),
    (6, REPORT_DIR / "chapter-6-general-discussion.md", "chapter-06-general-discussion.tex"),
)

MIGRATED_CHAPTER_NUMBERS = {chapter for chapter, _, _ in CHAPTERS}

CITATION_KEYS = {
    1: "maharana2024locomo",
    2: "hu2026memoryagentbench",
    3: "lewis2020rag",
    4: "zhou2026filesystem",
    5: "liu2024lost",
    6: "li2026refind",
    7: "yuan2026retrievalutilization",
    8: "zheng2023llmjudge",
    9: "packer2023memgpt",
    10: "chhikara2025mem0",
    11: "xu2025amem",
    12: "robertson2009bm25",
    13: "cormack2009rrf",
    14: "snapresearch2024locomoeval",
}

FIGURE_OPTIONS = {
    "2.1": r"width=0.56\linewidth,height=0.32\textheight,keepaspectratio",
    "2.4": r"width=0.58\linewidth,height=0.30\textheight,keepaspectratio",
    "3.4": r"width=0.62\linewidth,height=0.32\textheight,keepaspectratio",
    "3.5": r"width=0.54\linewidth,height=0.30\textheight,keepaspectratio",
    "5.4": r"width=0.60\linewidth,height=0.30\textheight,keepaspectratio",
}

# Most figures remain ordinary top/bottom/page floats.  Figure 5.1 follows a
# short explanatory paragraph after a dense table; forcing only this
# figure to remain in place prevents the paragraph from becoming an orphaned
# near-empty page while preserving the source order.
FIGURE_PLACEMENTS = {
    "5.1": "H",
    "5.7": "H",
}

# Short analytical lead-ins that should travel with the immediately following
# dense table.  Without this publication-only rule, a table page break can
# leave the lead-in alone on an almost empty portrait page.
TABLE_LEADIN_PREFIXES = (
    "The direct navigation contrast, E3 minus E1, does not show a monotonic relation",
)

ASCII_FIGURES = {
    "3.2": """Original turn
session 7, turn 12
       v
Canonical record: S07:T12
       |--> S1 raw session file
       |--> S2 topic folder / raw session file
       |--> Exchange unit used by R2
       `--> S3 curated fact [source: S07:T12]
                        v
                 Retrieved evidence
                        v
              Validated EvidenceItem""",
    "4.3": """Does the required information exist in the declared store?
       |-- No  -> Storage omission or distortion
       `-- Yes
             |
             v
Was it reached by the retrieval process?
       |-- No  -> Retrieval failure
       `-- Yes
             |
             v
Did it survive selection, fusion, and the evidence budget?
       |-- No  -> Packaging or budget loss
       `-- Yes
             |
             v
Was the final EvidenceBundle sufficient?
       |-- No  -> Incomplete evidence
       `-- Yes
             |
             v
Did the Answerer use it correctly?
       |-- No  -> Answerer utilisation failure
       `-- Yes
             |
             v
Do token and semantic scores disagree?
       |-- Yes -> Evaluation disagreement review
       `-- No  -> Mixed / indeterminate review""",
}


@dataclass
class TableCaption:
    chapter: int
    number: int
    panel: str | None
    short_title: str
    full_title: str


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def replace_citations(text: str) -> str:
    """Replace the report's frozen numeric Markdown citations with BibTeX keys."""

    def range_repl(match: re.Match[str]) -> str:
        start, end = int(match.group(1)), int(match.group(2))
        if start not in CITATION_KEYS or end not in CITATION_KEYS or start > end:
            return match.group(0)
        keys = ",".join(CITATION_KEYS[index] for index in range(start, end + 1))
        return rf"\cite{{{keys}}}"

    text = re.sub(r"\[(\d{1,2})\](?:--|–|—)\[(\d{1,2})\]", range_repl, text)

    cluster_pattern = re.compile(
        r"(?:\[(?:[1-9]|1[0-4])\])(?:,\s*\[(?:[1-9]|1[0-4])\])+"
    )

    def cluster_repl(match: re.Match[str]) -> str:
        numbers = [int(value) for value in re.findall(r"\[(\d{1,2})\]", match.group(0))]
        keys = ",".join(CITATION_KEYS[number] for number in numbers)
        return rf"\cite{{{keys}}}"

    text = cluster_pattern.sub(cluster_repl, text)

    def single_repl(match: re.Match[str]) -> str:
        number = int(match.group(1))
        key = CITATION_KEYS.get(number)
        return rf"\cite{{{key}}}" if key else match.group(0)

    return re.sub(r"\[(\d{1,2})\]", single_repl, text)


def normalise_headings(markdown: str, chapter: int) -> str:
    lines: list[str] = []
    in_fence = False
    for line in markdown.splitlines():
        if line.startswith("```"):
            in_fence = not in_fence
            lines.append(line)
            continue
        if in_fence:
            lines.append(line)
            continue

        top = re.match(r"^#\s+Chapter\s+(\d+)\s+(.+?)\s*$", line)
        if top:
            lines.append(f"# {top.group(2)} {{#chap:ch{chapter}}}")
            continue

        heading = re.match(r"^(#{2,4})\s+(\d+(?:\.\d+)+)\s+(.+?)\s*$", line)
        if heading:
            marks, number, title = heading.groups()
            label = "sec:ch" + number.replace(".", "-")
            lines.append(f"{marks} {title} {{#{label}}}")
            continue

        lines.append(line)
    return "\n".join(lines) + "\n"


def pandoc_convert(markdown: str) -> str:
    command = [
        "pandoc",
        "--from=markdown+raw_tex+tex_math_dollars+pipe_tables+fenced_code_blocks",
        "--to=latex",
        "--top-level-division=chapter",
        "--wrap=none",
    ]
    result = subprocess.run(
        command,
        input=markdown,
        text=True,
        capture_output=True,
        check=True,
    )
    return result.stdout


def parse_braced_command(line: str, command: str) -> tuple[str, str] | None:
    prefix = f"\\{command}{{"
    if not line.startswith(prefix):
        return None
    depth = 1
    index = len(prefix)
    start = index
    while index < len(line) and depth:
        if line[index] == "{" and (index == 0 or line[index - 1] != "\\"):
            depth += 1
        elif line[index] == "}" and (index == 0 or line[index - 1] != "\\"):
            depth -= 1
        index += 1
    if depth != 0:
        raise ValueError(f"Unbalanced {command} command: {line}")
    return line[start : index - 1], line[index:].strip()


def convert_figures(tex: str) -> str:
    lines = tex.splitlines()
    output: list[str] = []
    index = 0
    while index < len(lines):
        if lines[index] == r"\begin{figure}":
            end = index
            while end < len(lines) and lines[end] != r"\end{figure}":
                end += 1
            if end >= len(lines):
                raise ValueError("Unclosed figure environment from Pandoc")
            next_line = end + 1
            while next_line < len(lines) and not lines[next_line].strip():
                next_line += 1
            if next_line < len(lines) and lines[next_line].startswith(r"\emph{Figure "):
                caption_line = lines[next_line]
                match = re.match(r"^\\emph\{Figure (\d+)\.(\d+)\. (.*)\}$", caption_line)
                if not match:
                    raise ValueError(f"Cannot parse figure caption: {caption_line}")
                chapter, number, caption = match.groups()
                block = "\n".join(lines[index : end + 1])
                image_match = re.search(r"\\includegraphics(?:\[[^]]*\])?\{([^}]+)\}", block)
                if not image_match:
                    raise ValueError(f"Cannot find image path for Figure {chapter}.{number}")
                image_path = image_match.group(1)
                if image_path.startswith("figures/"):
                    image_path = "../" + image_path
                identifier = f"{chapter}.{number}"
                options = FIGURE_OPTIONS.get(
                    identifier,
                    r"width=0.68\linewidth,height=0.27\textheight,keepaspectratio",
                )
                placement = FIGURE_PLACEMENTS.get(identifier, "tbp")
                output.extend(
                    [
                        rf"\begin{{figure}}[{placement}]",
                        r"  \centering",
                        rf"  \includegraphics[{options}]{{{image_path}}}",
                        rf"  \caption{{{caption}}}",
                        rf"  \label{{fig:ch{chapter}-{number}}}",
                        r"\end{figure}",
                    ]
                )
                index = next_line + 1
                continue

        if lines[index] == r"\begin{verbatim}":
            end = index
            while end < len(lines) and lines[end] != r"\end{verbatim}":
                end += 1
            next_line = end + 1
            while next_line < len(lines) and not lines[next_line].strip():
                next_line += 1
            if next_line < len(lines) and lines[next_line].startswith(r"\emph{Figure "):
                match = re.match(r"^\\emph\{Figure (\d+)\.(\d+)\. (.*)\}$", lines[next_line])
                if match:
                    chapter, number, caption = match.groups()
                    identifier = f"{chapter}.{number}"
                    diagram = ASCII_FIGURES.get(identifier)
                    if diagram is not None:
                        if identifier == "4.3":
                            output.append(r"\setcounter{figure}{2}")
                        output.extend(
                            [
                                r"\begin{figure}[tbp]",
                                r"  \centering",
                                r"  \begin{minipage}{0.68\linewidth}",
                                r"\begin{Verbatim}[frame=single,fontsize=\tiny]",
                                diagram,
                                r"\end{Verbatim}",
                                r"  \end{minipage}",
                                rf"  \caption{{{caption}}}",
                                rf"  \label{{fig:ch{chapter}-{number}}}",
                                r"\end{figure}",
                            ]
                        )
                        index = next_line + 1
                        continue

        output.append(lines[index])
        index += 1
    return "\n".join(output) + "\n"


def parse_table_caption(line: str) -> TableCaption | None:
    parsed = parse_braced_command(line, "textbf")
    if not parsed:
        return None
    inner, trailing = parsed
    match = re.match(
        r"^Table\s+(\d+)\.(\d+)(?:\(([^)]+)\)|,\s*Panel\s+([A-Za-z]))?\.\s*(.*)$",
        inner,
    )
    if not match:
        return None
    chapter, number, parenthetical, named_panel, title = match.groups()
    panel = (parenthetical or named_panel or "").lower() or None
    panel_prefix = f"Panel ({panel}). " if parenthetical else (f"Panel {panel.upper()}. " if panel else "")
    short_title = panel_prefix + title
    full_title = short_title + ((" " + trailing) if trailing else "")
    return TableCaption(
        chapter=int(chapter),
        number=int(number),
        panel=panel,
        short_title=short_title,
        full_title=full_title,
    )


def add_table_captions(tex: str) -> str:
    lines = tex.splitlines()
    output: list[str] = []
    pending: TableCaption | None = None
    inside_table = False

    for line in lines:
        caption = parse_table_caption(line)
        if caption:
            pending = caption
            continue

        if line.startswith(r"\begin{longtable}"):
            if pending and pending.panel not in {"b", "c", "d", "e", "f"}:
                output.append(rf"\setcounter{{table}}{{{pending.number - 1}}}")
            inside_table = True
            output.append(line)
            continue

        if inside_table and line == r"\toprule" and pending:
            panel_suffix = f"-{pending.panel}" if pending.panel else ""
            base_label = f"tab:ch{pending.chapter}-{pending.number}"
            if pending.panel in {"b", "c", "d", "e", "f"}:
                output.append(
                    rf"\caption*{{\textbf{{Table {pending.chapter}.{pending.number} (continued).}} {pending.full_title}}}\\"
                )
            else:
                labels = rf"\label{{{base_label}{panel_suffix}}}"
                if pending.panel == "a":
                    labels += rf"\label{{{base_label}}}"
                output.append(
                    rf"\caption[{pending.short_title}]{{{pending.full_title}}}{labels}\\"
                )
            output.append(line)
            pending = None
            continue

        output.append(line)
        if line == r"\end{longtable}":
            inside_table = False

    if pending:
        raise ValueError(f"Table caption was not followed by a table: {pending}")
    return "\n".join(output) + "\n"


def wrap_longtables(tex: str) -> str:
    lines = tex.splitlines()
    output: list[str] = []
    index = 0
    longtable_serial = 0
    while index < len(lines):
        if not lines[index].startswith(r"\begin{longtable}"):
            output.append(lines[index])
            index += 1
            continue

        end = index
        while end < len(lines) and lines[end] != r"\end{longtable}":
            end += 1
        if end >= len(lines):
            raise ValueError("Unclosed longtable environment")
        block = lines[index : end + 1]
        longtable_serial += 1

        # Markdown multi-panel tables often place an italic ``Panel A/B``
        # label immediately before the physical table.  A page break before a
        # dense table can strand that label on an otherwise empty portrait
        # page, so move only such labels into the table wrapper.
        trailing_blanks: list[str] = []
        while output and not output[-1].strip():
            trailing_blanks.append(output.pop())

        # A numbered table may have a generated counter command between its
        # Markdown panel label and the longtable.  Carry that invisible command
        # into the wrapper as well so Panel A cannot remain outside.
        table_counter_command: str | None = None
        if output and output[-1].startswith(r"\setcounter{table}"):
            table_counter_command = output.pop()
            while output and not output[-1].strip():
                trailing_blanks.append(output.pop())

        panel_label: str | None = None
        if output and re.match(r"^\\emph\{Panel [A-Z](?:\.|\b)", output[-1]):
            panel_label = output.pop()
            if trailing_blanks:
                output.append("")
        else:
            if trailing_blanks:
                output.append("")

        trailing_blanks = []
        while output and not output[-1].strip():
            trailing_blanks.append(output.pop())
        table_leadin: str | None = None
        if output and any(
            output[-1].startswith(prefix) for prefix in TABLE_LEADIN_PREFIXES
        ):
            table_leadin = output.pop()
        else:
            output.extend(reversed(trailing_blanks))
        try:
            top = block.index(r"\toprule")
            header = block[top + 1]
            columns = header.count(" & ") + 1
        except (ValueError, IndexError):
            columns = 1

        # Pandoc emits a single ``\endhead`` marker after the first header.
        # Once a caption is inserted before that header, longtable repeats the
        # caption (and its label) on every page.  Split the first and repeated
        # heads explicitly so that the numbered caption appears exactly once.
        if any(line.startswith(r"\caption[") for line in block):
            try:
                top = block.index(r"\toprule")
                header = block[top + 1]
                midrule = block[top + 2]
                endhead = block.index(r"\endhead", top)
                if midrule != r"\midrule":
                    raise ValueError("Unexpected longtable header structure")
                block = (
                    block[: top + 3]
                    + [
                        r"\endfirsthead",
                        rf"\multicolumn{{{columns}}}{{r}}{{\small\itshape Continued from the previous page}}\\",
                        r"\toprule",
                        header,
                        r"\midrule",
                        r"\endhead",
                    ]
                    + block[endhead + 1 :]
                )
            except (ValueError, IndexError) as error:
                raise ValueError("Cannot split the longtable first head") from error

        # Rounded fractional widths from Pandoc can sum to slightly more than
        # one text width.  Apply a small inset to keep every rule and cell
        # inside the physical page without changing any table content.
        block = [
            line.replace(r"(\columnwidth -", r"(.96\columnwidth -")
            for line in block
        ]

        # Multi-panel tables use several physical longtables while retaining a
        # single printed table number.  Give each physical block a private PDF
        # destination suffix so Hyperref never emits duplicate anchors.
        common_prefix = [
            r"\begingroup",
            rf"\renewcommand{{\theHtable}}{{\thechapter.\arabic{{table}}.block{longtable_serial}}}",
        ]

        if table_counter_command:
            output.append(table_counter_command)

        output.extend(
            common_prefix
            + [
                r"\fontsize{5.0pt}{5.45pt}\selectfont",
                r"\setlength{\tabcolsep}{0.7pt}",
                r"\renewcommand{\arraystretch}{0.82}",
                r"\hfuzz=\maxdimen",
                r"\vfuzz=\maxdimen",
            ]
        )
        if table_leadin:
            output.extend([table_leadin, r"\smallskip"])
        if panel_label:
            output.extend([panel_label, ""])
        output.extend(block)
        output.append(r"\endgroup")
        index = end + 1
    return "\n".join(output) + "\n"


def fix_known_layout_hazards(tex: str, chapter: int) -> str:
    """Keep long identifiers and display equations inside the A4 text area.

    These are deterministic presentation-only rewrites.  They do not alter
    any symbol, value, comparison, or claim in the Markdown source.
    """

    if chapter == 3:
        tex = tex.replace(
            r"""\[
\text{Conversation history}
\rightarrow
\text{Memory representation}
\rightarrow
\text{Retrieval and evidence selection}
\rightarrow
\text{Answer generation}.
\]""",
            r"""\[
\begin{aligned}
\text{Conversation history}
&\rightarrow \text{Memory representation} \\
&\rightarrow \text{Retrieval and evidence selection} \\
&\rightarrow \text{Answer generation}.
\end{aligned}
\]""",
        )
        tex = tex.replace(
            r"""\[
\text{Condition-specific retrieval}
\rightarrow
\text{Common EvidenceBundle}
\rightarrow
\text{Shared Answerer}
\rightarrow
\text{Common output schema}.
\]""",
            r"""\[
\begin{aligned}
\text{Condition-specific retrieval}
&\rightarrow \text{Common EvidenceBundle} \\
&\rightarrow \text{Shared Answerer} \\
&\rightarrow \text{Common output schema}.
\end{aligned}
\]""",
        )
        tex = tex.replace(
            r"""\[
\text{Question}
\rightarrow
\text{Condition-specific evidence access}
\rightarrow
\text{Common evidence interface}
\rightarrow
\text{Shared Answerer}
\rightarrow
\text{Candidate answer}.
\]""",
            r"""\[
\begin{aligned}
\text{Question}
&\rightarrow \text{Condition-specific evidence access} \\
&\rightarrow \text{Common evidence interface} \\
&\rightarrow \text{Shared Answerer} \\
&\rightarrow \text{Candidate answer}.
\end{aligned}
\]""",
        )
        tex = tex.replace(
            r"""\[
\text{Canonical conversation}
\rightarrow
\text{Memory representation}
\rightarrow
\text{Retriever}
\rightarrow
\text{EvidenceBundle}
\rightarrow
\text{Answerer}
\rightarrow
\text{Candidate answer}.
\]""",
            r"""\[
\begin{aligned}
\text{Canonical conversation}
&\rightarrow \text{Memory representation} \\
&\rightarrow \text{Retriever} \\
&\rightarrow \text{EvidenceBundle} \\
&\rightarrow \text{Answerer} \\
&\rightarrow \text{Candidate answer}.
\end{aligned}
\]""",
        )

    if chapter == 4:
        tex = tex.replace(
            r"\texttt{cbfbc1dba6bc53d00625212a0f22d55ffee7c1fc}",
            r"\nolinkurl{cbfbc1dba6bc53d00625212a0f22d55ffee7c1fc}",
        )
        tex = tex.replace(
            r"\texttt{deepseek-v4.1-flash-1017}",
            r"\texttt{deepseek-v4.1-\allowbreak{}flash-\allowbreak{}1017}",
        )
        tex = tex.replace(
            r"\texttt{deepseek-v4.1-flash}",
            r"\texttt{deepseek-v4.1-\allowbreak{}flash}",
        )
        tex = tex.replace(
            r"\texttt{Evaluation\ disagreement\ review}",
            r"\texttt{Evaluation\allowbreak\ disagreement\allowbreak\ review}",
        )
        tex = tex.replace(
            r"\texttt{Incomplete\ evidence}",
            r"\texttt{Incomplete\allowbreak\ evidence}",
        )
        tex = tex.replace(
            r"\texttt{Packaging\ or\ budget\ loss}",
            r"\texttt{Packaging\allowbreak\ or\allowbreak\ budget\allowbreak\ loss}",
        )
        tex = tex.replace(
            r"\texttt{Mixed\ /\ indeterminate}",
            r"\texttt{Mixed\allowbreak\ /\allowbreak\ indeterminate}",
        )
        tex = tex.replace(
            r"\texttt{Incomplete\allowbreak\ evidence}",
            r"\emph{Incomplete evidence}",
        )
        tex = tex.replace(
            r"\texttt{Packaging\allowbreak\ or\allowbreak\ budget\allowbreak\ loss}",
            r"\emph{Packaging or budget loss}",
        )
        tex = tex.replace(
            r"\texttt{Evaluation\allowbreak\ disagreement\allowbreak\ review}",
            r"\emph{Evaluation disagreement review}",
        )
        tex = tex.replace(
            r"\texttt{Mixed\allowbreak\ /\allowbreak\ indeterminate}",
            r"\emph{Mixed / indeterminate}",
        )

        # The E7 online-cost identity is unchanged; only the line breaking is
        # made explicit for the report page width.
        tex = tex.replace(
            r"""\[
C_{i,E7,d}^{\mathrm{online}}=
C_{i,E2,d}^{\mathrm{retrieval}}
+C_{i,E2,d}^{\mathrm{packaging}}
+C_{i,E6,d}^{\mathrm{retrieval}}
+C_{i,E6,d}^{\mathrm{packaging}}
+C_{i,E7,d}^{\mathrm{fusion}}
+C_{i,E7,d}^{\mathrm{answering}}
+C_{i,E2,d}^{\mathrm{recovery}}
+C_{i,E6,d}^{\mathrm{recovery}}
+C_{i,E7,d}^{\mathrm{recovery}}.
\]""",
            r"""\[
\begin{aligned}
C_{i,E7,d}^{\mathrm{online}}
={}& C_{i,E2,d}^{\mathrm{retrieval}}
 + C_{i,E2,d}^{\mathrm{packaging}} \\
&+ C_{i,E6,d}^{\mathrm{retrieval}}
 + C_{i,E6,d}^{\mathrm{packaging}} \\
&+ C_{i,E7,d}^{\mathrm{fusion}}
 + C_{i,E7,d}^{\mathrm{answering}} \\
&+ C_{i,E2,d}^{\mathrm{recovery}}
 + C_{i,E6,d}^{\mathrm{recovery}}
 + C_{i,E7,d}^{\mathrm{recovery}}.
\end{aligned}
\]""",
        )

    # Longtable installs its own output routine.  If a pending figure is still
    # waiting when a longtable starts, TeX can combine the float and the table
    # in one overfull page box and silently clip the table below the page.  The
    # barriers below preserve source order and content while ensuring that the
    # relevant figure is placed before the following table-heavy subsection.
    if chapter == 2:
        tex = tex.replace(
            r"\hypertarget{sec:ch2-8}{%",
            r"\newpage" + "\n\n" + r"\hypertarget{sec:ch2-8}{%",
            1,
        )

    return tex


def replace_cross_references(tex: str, section_labels: set[str]) -> str:
    def range_repl(kind: str, label_prefix: str, match: re.Match[str]) -> str:
        chapter_a, number_a, chapter_b, number_b = match.groups()
        return (
            f"{kind}~\\ref{{{label_prefix}:ch{chapter_a}-{number_a}}}--"
            f"\\ref{{{label_prefix}:ch{chapter_b}-{number_b}}}"
        )

    tex = re.sub(
        r"Figures?\s+(\d+)\.(\d+)--(\d+)\.(\d+)",
        lambda match: range_repl("Figures", "fig", match),
        tex,
    )
    tex = re.sub(
        r"Tables?\s+(\d+)\.(\d+)--(\d+)\.(\d+)",
        lambda match: range_repl("Tables", "tab", match),
        tex,
    )

    def chapter_pair_repl(match: re.Match[str]) -> str:
        first, second = match.groups()
        first_exists = int(first) in MIGRATED_CHAPTER_NUMBERS
        second_exists = int(second) in MIGRATED_CHAPTER_NUMBERS
        if first_exists and second_exists:
            return rf"Chapters~\ref{{chap:ch{first}}} and~\ref{{chap:ch{second}}}"
        if first_exists:
            return rf"Chapter~\ref{{chap:ch{first}}} and Chapter {second}"
        return match.group(0)

    tex = re.sub(r"\bChapters\s+([1-9])\s+and\s+([1-9])", chapter_pair_repl, tex)

    def section_range_repl(match: re.Match[str]) -> str:
        start, end = match.groups()
        start_label = "sec:ch" + start.replace(".", "-")
        end_label = "sec:ch" + end.replace(".", "-")
        if start_label not in section_labels or end_label not in section_labels:
            return match.group(0)
        return rf"Sections~\ref{{{start_label}}}--\ref{{{end_label}}}"

    tex = re.sub(
        r"Sections\s+(\d+(?:\.\d+)+)--(\d+(?:\.\d+)+)",
        section_range_repl,
        tex,
    )
    tex = re.sub(
        r"\bFigure\s+(\d+)\.(\d+)",
        lambda match: rf"Figure~\ref{{fig:ch{match.group(1)}-{match.group(2)}}}",
        tex,
    )
    tex = re.sub(
        r"\bTable\s+(\d+)\.(\d+)",
        lambda match: rf"Table~\ref{{tab:ch{match.group(1)}-{match.group(2)}}}",
        tex,
    )

    def section_repl(match: re.Match[str]) -> str:
        number = match.group(1)
        label = "sec:ch" + number.replace(".", "-")
        return rf"Section~\ref{{{label}}}" if label in section_labels else match.group(0)

    tex = re.sub(r"\bSection\s+(\d+(?:\.\d+)+)", section_repl, tex)
    def chapter_repl(match: re.Match[str]) -> str:
        chapter = int(match.group(1))
        if chapter not in MIGRATED_CHAPTER_NUMBERS:
            return match.group(0)
        return rf"Chapter~\ref{{chap:ch{chapter}}}"

    tex = re.sub(r"\bChapter\s+([1-9])\b", chapter_repl, tex)
    return tex


def migrate_chapter(chapter: int, source: Path, destination: Path) -> dict[str, object]:
    markdown = source.read_text(encoding="utf-8")
    normalised = normalise_headings(markdown, chapter)
    normalised = replace_citations(normalised)
    section_labels = set(re.findall(r"\{#(sec:ch[^}]+)\}", normalised))

    tex = pandoc_convert(normalised)
    tex = convert_figures(tex)
    tex = add_table_captions(tex)
    tex = wrap_longtables(tex)
    tex = replace_cross_references(tex, section_labels)
    tex = fix_known_layout_hazards(tex, chapter)

    header = (
        "% AUTO-GENERATED FILE. DO NOT EDIT DIRECTLY.\n"
        f"% Source: {source.relative_to(REPORT_DIR.parent.parent)}\n"
        "% Regenerate with: python3 scripts/migrate_markdown_to_latex.py\n\n"
    )
    destination.write_text(header + tex, encoding="utf-8")

    return {
        "chapter": chapter,
        "source": str(source.relative_to(REPORT_DIR.parent.parent)),
        "source_sha256": sha256(source),
        "output": str(destination.relative_to(PROJECT_DIR)),
        "output_sha256": sha256(destination),
        "figures": len(re.findall(r"\\begin\{figure\}", tex)),
        "captioned_tables": len(re.findall(r"\\caption\[", tex)),
        "citations": len(re.findall(r"\\cite\{", tex)),
        "display_math_blocks": len(re.findall(r"\\\[", tex)),
    }


def main() -> None:
    CHAPTER_DIR.mkdir(parents=True, exist_ok=True)
    manifest = {
        "schema": "report-latex-migration-v1",
        "generator": "scripts/migrate_markdown_to_latex.py",
        "chapters": [],
    }
    for chapter, source, output_name in CHAPTERS:
        manifest["chapters"].append(
            migrate_chapter(chapter, source, CHAPTER_DIR / output_name)
        )
    manifest_path = PROJECT_DIR / "migration-manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(f"Migrated {len(CHAPTERS)} chapters to {CHAPTER_DIR}")
    print(f"Wrote {manifest_path}")


if __name__ == "__main__":
    main()
