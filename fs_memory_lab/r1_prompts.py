"""Frozen paper-transcribed and evidence-only R1 search prompts.

The paper prints Prompts 5--7 in Appendix A.3 but does not publish author
source files.  ``PUBLISHED_PROMPT_*`` are therefore normalized transcriptions,
not claims of byte identity with an unavailable source file.  Prompt 5 reuses
the transcription already present in :mod:`fs_memory_lab.paper_prompts`.

The evidence-only prompts are controlled project adaptations.  They preserve
the paper's store-specific routing and cost guidance while replacing every
answering, citation, inference, absence and output responsibility with the
host-verified ``take_note`` / ``finish_search`` protocol.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from types import MappingProxyType
from typing import Mapping

from .paper_prompts import SEARCH_PROMPT as PUBLISHED_PROMPT_5


PAPER_PDF_SHA256 = "4186ea9a8ca5b5534e644a2a8c36e5594226df440b167093ea406e0e9a9bf42c"
PUBLISHED_TRANSCRIPTION_VERSION = "filesystem-paper-appendix-a3-normalized-v1"
EVIDENCE_ONLY_PROMPT_VERSION = "r1-evidence-only-search-v1"

# Appendix A.3 describes a common question turn and a citation instruction but
# does not print a separately delimited author-source user template.  R1 uses
# this project-defined evidence-only wrapper and freezes it independently.
EVIDENCE_ONLY_USER_TEMPLATE_VERSION = "r1-evidence-only-user-turn-v1"
EVIDENCE_ONLY_USER_TEMPLATE = """Retrieve exact stored evidence for the following benchmark question. Do not answer it. Use only the available filesystem tools and evidence orchestration actions.

Question:
{question}"""


def _replace_once(text: str, old: str, new: str, *, label: str) -> str:
    if text.count(old) != 1:
        raise RuntimeError(
            f"prompt construction failed for {label}: expected one source block, "
            f"found {text.count(old)}"
        )
    return text.replace(old, new, 1)


_PAPER_ROLE = (
    "You are a Memory Search Agent working over a persistent memory filesystem; "
    "all memory files are markdown (.md) and live under /memories. You receive an "
    "instruction and a query from an external agent: search the filesystem and "
    "answer the query from what is stored there. Answer quality comes first; "
    "minimize search cost subject to that."
)

_RAW_FILES = """## This store's files

The files here are RAW per-session conversation transcripts and can be very large, so locate the relevant content first (grep short distinctive tokens; the body is where the content lives), then read around the hits at the scope the query needs. Every turn carries an inline source locator (e.g. `[S<session>T<turn>]` or `[B<block>M<message>]`, per the benchmark); you may quote these inside your evidence, but cite by memory path per the Citation Format below.
"""

PUBLISHED_PROMPT_6 = _replace_once(
    PUBLISHED_PROMPT_5,
    _PAPER_ROLE + "\n",
    _PAPER_ROLE + "\n" + _RAW_FILES,
    label="Prompt 6 raw-session preamble",
)
PUBLISHED_PROMPT_6 = _replace_once(
    PUBLISHED_PROMPT_6,
    "grep two candidate subtrees + toc a candidate file together",
    "grep two candidate topic folders + grep a synonym across /memories together",
    label="Prompt 6 batching example",
)
PUBLISHED_PROMPT_6 = _replace_once(
    PUBLISHED_PROMPT_6,
    "Names and descriptions often reveal where the answer lives before any content search.",
    "The folder names often reveal which sessions matter before any content search.",
    label="Prompt 6 survey guidance",
)
PUBLISHED_PROMPT_6 = _replace_once(
    PUBLISHED_PROMPT_6,
    "the read tools cover every scope you might need: `toc` and `section_read` by heading, `view` by line range or whole file.",
    "the read tools cover every scope you might need: `view` by line range or whole file, and `toc`/`section_read` by heading (transcripts carry little heading structure, so those two rarely help here).",
    label="Prompt 6 read guidance",
)

_HIERARCHICAL_STRATEGY = PUBLISHED_PROMPT_6.split("## Strategy\n", 1)[1].split(
    "4. **Verify, then stop**", 1
)[0]
_FLAT_STRATEGY = """1. **Survey once**: View /memories ONCE to list the per-session files and their frontmatter descriptions. The store is FLAT — session-named files at the root, no subfolders to route through. Never re-view the listing.
2. **Probe**: The content lives in the file BODIES (raw transcripts), so grep is your primary tool. Grep for short, distinctive tokens using alternation (`"alpha|beta|gamma"`); scope to a single session with `path=` when you already know which one. The store's phrasing may differ from the query's, so a long literal phrase may miss. If the result reports truncation, tighten the pattern or narrow `path=` when the unshown matching lines would be noise; raise `max_results` when you need to see more of the matches. For open-ended queries (which / what / how many / all), a keyword probe alone undercounts — inspect every plausibly-relevant session and distinguish instances by their concrete attributes (dates, identifiers), not by how the text phrases them.
3. **Read only what you need**: Files open with a YAML `---` frontmatter block (`name`, `description`, optional `metadata`) — treat it as file-level annotation; cite body headings/lines, not frontmatter. Together with the matched lines grep already gave you, the read tools cover every scope you might need: `view` by line range or whole file, and `toc`/`section_read` by heading (transcripts carry little heading structure, so those two rarely help here). Take a promising file at whatever scope the query needs, no more.
"""

PUBLISHED_PROMPT_7 = _replace_once(
    PUBLISHED_PROMPT_6,
    "grep two candidate topic folders + grep a synonym across /memories together",
    "grep two candidate sessions + grep a synonym across /memories together",
    label="Prompt 7 batching example",
)
PUBLISHED_PROMPT_7 = _replace_once(
    PUBLISHED_PROMPT_7,
    _HIERARCHICAL_STRATEGY,
    _FLAT_STRATEGY,
    label="Prompt 7 flat strategy",
)
PUBLISHED_PROMPT_7 = _replace_once(
    PUBLISHED_PROMPT_7,
    "widening your scoped searches to the whole tree",
    "widening your scoped searches to the whole store",
    label="Prompt 7 whole-store fallback",
)
PUBLISHED_PROMPT_7 = _replace_once(
    PUBLISHED_PROMPT_7,
    "whose name, folder, or description is about a different subject",
    "whose name or description is about a different subject",
    label="Prompt 7 flat absence guidance",
)


_EVIDENCE_ROLE = """You are an Evidence Search Agent working over a persistent memory filesystem; all memory files are markdown (.md) and live under /memories. You receive a query from an external agent. Search the filesystem and select the exact stored source lines needed by a separate Answerer. Evidence quality comes first; minimize search cost subject to that.

You are a retriever, not an answerer. Never answer the query, choose an option, state an inferred answer, paraphrase evidence, or write citations yourself. The host validates source selections and constructs citations."""

_EVIDENCE_VERIFY = """4. **Verify, note, then stop**: After every filesystem result, ask whether prior observations contain lines supporting EVERY part of the query. A compound question is covered only when each part has source evidence. If coverage is sufficient, use `take_note` in a later provider round to select exact line ranges from the successful prior observation; do not search merely to reconfirm them. Cross-check only when sources disagree or a bare keyword hit lacks the surrounding statement. Facts may carry inline source locators (e.g. `[S12T3]`, `[B4M7]`) and dates; select the stored lines needed to preserve temporal order and conflicts. When stored facts could support an inference, select those facts only. Do not write the inference as evidence. After accepted notes cover the question, call `finish_search` with `evidence_sufficient`."""

_EVIDENCE_MULTIPLE_CHOICE = """## Multiple-choice queries

Options are retrieval cues only. Probe their distinctive terms and the question's subject, while respecting polarity such as NEW, not yet tried, or avoid repeating. An option-term hit is a lead, not proof; read its context. Never choose, rank, recommend, or eliminate an option in your output. Select only the stored source lines that a separate Answerer would need to decide."""

_EVIDENCE_SELECTION = """## Evidence selection contract

Filesystem results are immutable observations identified by `observation_id`. `take_note` accepts only selectors into a successful observation from an earlier provider round: the observation ID, memory path, and inclusive observed body-line range. Never supply evidence text, an answer, a citation, a source locator, a date, or a speaker in `take_note`; the host re-reads the frozen store and derives those fields. Frontmatter, directory listings, table-of-contents output, failed calls, unreturned gaps, and truncated-away matches are not selectable evidence.

Use one action mode per provider response:
- filesystem mode: call one or more independent `view`, `grep`, `toc`, or `section_read` tools;
- note mode: call one or more `take_note` actions referring only to earlier observations;
- finish mode: call exactly one `finish_search` action and nothing else.

Do not mix modes in one response. Do not emit free-form answer text. A note that is rejected by the host is not evidence."""

_EVIDENCE_ABSENCE = """## Concluding absence (open questions only)

Do not stop for absence until you have both surveyed `/memories` and widened a body search to `path="/memories"` using the subject plus plausible alternative names, synonyms, or pronouns. A fact may live in a file whose label concerns another subject. Re-check completeness for open-ended queries. Only after this verified global fallback may you call `finish_search` with `not_found_after_global_fallback`; do not guess or write a natural-language absence answer."""

_EVIDENCE_OUTPUT = """## Output

Terminate only through `finish_search`. Use `evidence_sufficient` after at least one accepted note covers the query. Otherwise use the applicable structured reason: `not_found_after_global_fallback`, `no_progress_after_global_fallback`, `evidence_budget_reached`, `round_limit`, or `protocol_failure`. Supply only concise missing-aspect labels when required. Never place an answer, evidence quotation, citation, option choice, or explanation in the finish action or assistant text."""


def _replace_section(
    text: str, heading: str, next_heading: str, replacement: str
) -> str:
    start = text.find(heading)
    if start < 0:
        raise RuntimeError(f"prompt section not found: {heading}")
    end = text.find(next_heading, start + len(heading))
    if end < 0:
        raise RuntimeError(f"next prompt section not found: {next_heading}")
    return text[:start] + replacement.rstrip() + "\n" + text[end:]


def _derive_evidence_only(published: str) -> str:
    first_heading = published.find("## ")
    if first_heading < 0:
        raise RuntimeError("published prompt has no section heading")
    derived = _EVIDENCE_ROLE + "\n" + published[first_heading:]
    derived = derived.replace(
        "you may quote these inside your evidence, but cite by memory path per the Citation Format below.",
        "treat these as source metadata; select observed body lines and let the host derive citations.",
    )
    derived = _replace_once(
        derived,
        "commit: deliver the best-supported answer, or, for an open question where nothing was found, state clearly that the store does not contain it.",
        "commit: save validated source selections with `take_note`, then terminate with `finish_search`; never deliver an answer yourself.",
        label="evidence-only cost commitment",
    )
    derived = derived.replace(
        "treat it as file-level annotation; cite body headings/lines, not frontmatter.",
        "treat it as file-level annotation; select body lines, not frontmatter.",
    )
    derived = _replace_section(
        derived,
        "4. **Verify, then stop**",
        "## Multiple-choice queries",
        _EVIDENCE_VERIFY,
    )
    derived = _replace_section(
        derived,
        "## Multiple-choice queries",
        "## Citation Format",
        _EVIDENCE_MULTIPLE_CHOICE,
    )
    derived = _replace_section(
        derived,
        "## Citation Format",
        "## Concluding absence (open questions only)",
        _EVIDENCE_SELECTION,
    )
    derived = _replace_section(
        derived,
        "## Concluding absence (open questions only)",
        "## Output",
        _EVIDENCE_ABSENCE,
    )
    output_start = derived.find("## Output")
    if output_start < 0:
        raise RuntimeError("published output section not found")
    return derived[:output_start] + _EVIDENCE_OUTPUT


DERIVED_PROMPT_5 = _derive_evidence_only(PUBLISHED_PROMPT_5)
DERIVED_PROMPT_6 = _derive_evidence_only(PUBLISHED_PROMPT_6)
DERIVED_PROMPT_7 = _derive_evidence_only(PUBLISHED_PROMPT_7)


@dataclass(frozen=True)
class R1PromptProfile:
    cell_id: str
    store_id: str
    paper_prompt_number: int
    hard_round_cap: int
    published_prompt: str
    derived_prompt: str


R1_PROMPT_PROFILES: Mapping[str, R1PromptProfile] = MappingProxyType(
    {
        "E1": R1PromptProfile(
            cell_id="E1",
            store_id="S1",
            paper_prompt_number=7,
            hard_round_cap=20,
            published_prompt=PUBLISHED_PROMPT_7,
            derived_prompt=DERIVED_PROMPT_7,
        ),
        "E3": R1PromptProfile(
            cell_id="E3",
            store_id="S2",
            paper_prompt_number=6,
            hard_round_cap=20,
            published_prompt=PUBLISHED_PROMPT_6,
            derived_prompt=DERIVED_PROMPT_6,
        ),
        "E5": R1PromptProfile(
            cell_id="E5",
            store_id="S3",
            paper_prompt_number=5,
            hard_round_cap=40,
            published_prompt=PUBLISHED_PROMPT_5,
            derived_prompt=DERIVED_PROMPT_5,
        ),
    }
)


def prompt_sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# Filled only after the normalized transcriptions and controlled redline have
# been visually reviewed against Appendix A.3.
FROZEN_R1_PROMPT_SHA256: Mapping[str, str] = MappingProxyType(
    {
        "published_prompt_5": "de03315ff999a8bcea7e08a10866f3a6dc74badf690d23a036e35c74ff81335c",
        "published_prompt_6": "4d89230b7718f28f8770faaabede2d4a3ea6ce2e174a1883f2923d371d36f6f2",
        "published_prompt_7": "6732049a8b94724d38473fc72f53f93310bfe4414d0eeba4450d3078dcf6d4d8",
        "derived_prompt_5": "56a7ee328b702acf677218605c2d649afe0089eda09165e5aadb286969116965",
        "derived_prompt_6": "3a6c8a077746b1297c02152b53359533cbb02d6f8488ea56f51ce9894d112b3c",
        "derived_prompt_7": "62b8b913b4150076b36955c9c8aa8ce9c72e8670988668ff57a4397171d44129",
        "evidence_only_user_template": "f20cd087abf1f96cc228342c81be31af49c670c6933da54fc0fbb9b0d78e43f9",
    }
)


def current_prompt_hashes() -> dict[str, str]:
    return {
        "published_prompt_5": prompt_sha256(PUBLISHED_PROMPT_5),
        "published_prompt_6": prompt_sha256(PUBLISHED_PROMPT_6),
        "published_prompt_7": prompt_sha256(PUBLISHED_PROMPT_7),
        "derived_prompt_5": prompt_sha256(DERIVED_PROMPT_5),
        "derived_prompt_6": prompt_sha256(DERIVED_PROMPT_6),
        "derived_prompt_7": prompt_sha256(DERIVED_PROMPT_7),
        "evidence_only_user_template": prompt_sha256(EVIDENCE_ONLY_USER_TEMPLATE),
    }


def verify_r1_prompts() -> None:
    current = current_prompt_hashes()
    if "PENDING" in FROZEN_R1_PROMPT_SHA256.values():
        raise RuntimeError("R1 prompt hashes have not been frozen")
    for name, expected in FROZEN_R1_PROMPT_SHA256.items():
        actual = current[name]
        if actual != expected:
            raise RuntimeError(
                f"{name} drifted: expected SHA-256 {expected}, got {actual}"
            )
