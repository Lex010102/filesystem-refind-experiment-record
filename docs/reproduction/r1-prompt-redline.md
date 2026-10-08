# R1 Prompt 5/6/7 transcription and evidence-only redline

Status: frozen v1 (2026-10-08)

## Source and qualification

The primary source is `papers/primary/filesystem-based-memory-for-llm-agents.pdf`
(SHA-256 `4186ea9a8ca5b5534e644a2a8c36e5594226df440b167093ea406e0e9a9bf42c`).
Appendix A.3 prints Prompt 5 on PDF pages 32–33, Prompt 6 on pages 33–35,
and Prompt 7 on pages 35–36. The pages were text-extracted and visually checked
against rendered PDF pages before freezing.

The paper does not provide author prompt source files. The strings in
`fs_memory_lab/r1_prompts.py` are normalized transcriptions: line wrapping,
typographic quotation marks/dashes and code quoting are normalized while wording
and section order are retained. They are not described as byte-exact author source.

## Store mapping

| Cell | Store | Paper prompt | Cap | Why |
| --- | --- | ---: | ---: | --- |
| E1 | S1 flat verbatim sessions | 7 | 20 | Prompt 7 explicitly assumes flat session files. |
| E3 | S2 foldered verbatim sessions | 6 | 20 | Prompt 6 routes through topic folders into raw sessions. |
| E5 | S3 agent-curated hierarchy | 5 | 40 | Prompt 5 routes through semantic folders, files and headings. |

The 20/20/40 caps reproduce the paper configuration. One provider completion is
one round even when that completion batches multiple independent tool calls. This
round-counting rule is our disclosed operational definition because the paper does
not publish its executable loop.

## What remains paper-direct

The evidence-only prompts retain the variant-specific filesystem facts, cost model,
one-time survey rule, batching rule, route/probe behavior, short-regex guidance,
scoped-to-global fallback, completeness warning for open questions, and read-scope
guidance. Those blocks are labelled `paper_published_text_reused` in the manifest.

## Controlled changes

| Block | Paper-direct behavior | Evidence-only behavior | Reason |
| --- | --- | --- | --- |
| Role | Search and answer. | Search and select exact stored evidence; never answer. | Separate retrieval quality from the shared Answerer. |
| Cost-model commitment | Commit to a best-supported answer or absence statement. | Save validated notes and then call `finish_search`. | A retriever must terminate without generating a benchmark answer. |
| Raw-store instruction | The model may quote evidence and write path citations. | Select observed body lines; the host derives exact text and citations. | Prevent invented quotations and paths. |
| Verify/stop | Answer immediately once sufficient. | Select prior observed spans with `take_note`, then finish. | Produce an auditable retrieval artifact. |
| Inference | State and cite the inferred answer. | Select supporting stored facts only; do not state the inference as evidence. | Keep inference in the common Answerer. |
| Multiple choice | Choose an option, even with thin evidence. | Use options as retrieval cues only; never choose or eliminate one in output. | Avoid leaking answer behavior into R1. |
| Citation format | Model writes citations in prose. | Model supplies observation/path/line selectors; host re-reads and cites. | Make attribution mechanically verifiable. |
| Absence | Natural-language absence after fallback. | Structured `not_found_after_global_fallback` only after root survey and whole-tree body grep. | Make absence eligibility testable. |
| Output | Direct prose answer first. | Exactly one `finish_search` action and no free-form answer text. | Enforce the retrieval/answer boundary. |
| Action protocol | Not present. | Three exclusive modes: filesystem reads, `take_note`, or `finish_search`. | Keep the state machine deterministic and selections resolvable. |

These changes apply across the complete Prompt 5/6/7 family; they are not a simple
replacement of only the first or final paragraph.

## User turn

Appendix A.3 says all variants receive an identical question plus an instruction to
cite factual claims, but it does not print a separately delimited user-template source.
The local template is therefore explicitly project-defined. It supplies only the
online benchmark question and asks for evidence, not an answer. Gold answers,
categories, gold evidence and evaluation labels are excluded from this boundary.

## Frozen hashes

The authoritative hashes live in `FROZEN_R1_PROMPT_SHA256` and are duplicated in
`docs/reproduction/r1-prompt-manifest.json`. Import-time/test-time verification fails
closed on drift. Prompt 5 retains the pre-existing repository hash
`de03315ff999a8bcea7e08a10866f3a6dc74badf690d23a036e35c74ff81335c`.
