# R1 evidence-only retrieval contract

Status: frozen implementation contract v1 (2026-10-07)

This document fixes the protocol that must be implemented before any R1 result is
accepted. It separates the published Filesystem search protocol from this project's
controlled evidence-only adaptation.

## 1. Scope

R1 is the filesystem-native retrieval family used in three experiment cells:

| Cell | Store | Published search prompt | Hard cap |
| --- | --- | --- | ---: |
| E1 | S1 flat verbatim sessions | Appendix A.3 Prompt 7 | 20 provider rounds |
| E3 | S2 foldered verbatim sessions | Appendix A.3 Prompt 6 | 20 provider rounds |
| E5 | S3 agent-curated filesystem | Appendix A.3 Prompt 5 | 40 provider rounds |

The Research Agent retrieves evidence only. It never answers the benchmark question.
A later shared Answerer will receive the frozen question and the validated
`EvidenceBundle`; that Answerer is outside the R1 retrieval score and must be shared by
R1, R2 and E7.

## 2. Primary-source provenance

Primary source:
`papers/primary/filesystem-based-memory-for-llm-agents.pdf`

PDF SHA-256:
`4186ea9a8ca5b5534e644a2a8c36e5594226df440b167093ea406e0e9a9bf42c`

| Contract element | Paper location | Status here |
| --- | --- | --- |
| Search Agent role | Section 2.2, PDF page 6 | published baseline |
| Store variants and prompt family | Section 3, pages 7–8 | published baseline |
| Variant-to-prompt mapping and common user-turn description | Appendix A.3, page 31 | published baseline |
| Prompt 5, hierarchical stores | Appendix A.3, pages 32–33 | published transcription to freeze |
| Prompt 6, Foldered sessions | Appendix A.3, pages 33–35 | published transcription to freeze |
| Prompt 7, Verbatim dump | Appendix A.3, pages 35–36 | published transcription to freeze |
| Model, caps, concurrency and compaction | Appendix C.1, Table 11, pages 47–48 | published baseline |
| Four read-only tool parameters/descriptions | Appendix C.4, Table 12, pages 49–50 | published text; JSON wrapper is local |

The PDF prints the prompt text and tool parameter tables, but not author source files,
an executable harness, the serialized function wrapper, observation serialization, or
all default values. Therefore the local prompt copies are called **published
transcriptions**, not byte-exact author source.

## 3. Fixed paper-derived behavior

- The Research Agent sees only a mounted `/memories` tree and the question.
- Its filesystem capability is exactly `view`, `grep`, `toc`, and `section_read`.
- Independent reads may be batched in one assistant turn.
- The agent surveys once, routes/probes, reads only needed context, verifies, and stops
  early when sufficient evidence has been collected.
- S1 is flat and uses raw-session-specific routing from Prompt 7.
- S2 uses the topic folders plus raw-session-specific routing from Prompt 6.
- S3 uses the hierarchical-store routing from Prompt 5.
- Search uses the paper target configuration `gpt-5.4-mini`, high effort and an
  8,192-token output cap. The local NUS portable provider may differ and must be
  reported separately as requested/served model and effective wire fields.
- Context compaction is triggered beyond 96k prompt tokens and keeps a running summary
  plus the three most recent rounds. The exact summarizer prompt is not published and
  remains a disclosed local reconstruction.
- Seed 42 and batch concurrency 8 are experiment-level settings. The current portable
  provider does not receive a seed; that limitation must be recorded, not hidden.

One **provider completion** counts as one local Research Agent round. Multiple tool
calls returned in that completion still count as one round. This is a project-defined
operationalization of the paper's “tool-round cap” wording and must remain fixed across
E1, E3 and E5.

The NUS-served model may occasionally return structurally valid tool calls together
with assistant prose. Such a response is never executed: neither its prose nor its
tool calls enter the observation ledger, message history, or EvidenceBundle. Agent
protocol v2 permits one content-free corrective re-request in that provider round and
at most three across an episode. The corrective prompt contains no rejected prose;
the trace stores only the error class, usage, model identity, correction counters and
prompt hash. A second polluted response in the same round, a content-only answer, an
unknown tool, or any other malformed response still fails closed. Corrective requests
count as model calls and token cost, but not as completed retrieval rounds.

The formal R1 runtime also has one project-defined emergency token fuse shared
unchanged by E1, E3 and E5: `1,000,000 provider_reported_total_tokens` per question,
counting research completions, rejected-prose correction completions and context
compaction completions. This is not a paper setting, a retrieval budget, or an
EvidenceBundle size limit. The fuse never clips a `view` result; ordinary `grep`
`max_results` behavior remains part of the paper tool. E5 receives no
condition-specific read limit. Each completed response is recorded first; if its
cumulative reported total reaches the fuse, the proposed actions in that triggering
response are not executed, no later provider request is sent, and the run publishes a
`token_safety_fuse` failure artifact rather than a partial bundle. The same runtime
contract fields and threshold must be used in all three cells.

## 4. Controlled evidence-only redline

The following changes are required across the complete Prompt 5/6/7 family; changing
only the first and final paragraphs is forbidden.

| Prompt block | Published paper-direct behavior | Evidence-only behavior |
| --- | --- | --- |
| Role | search and answer | search and select source evidence; never answer |
| Cost-model commit | deliver best-supported answer or state absence | save validated notes, then call `finish_search` |
| Verify-then-stop | answer immediately when context is sufficient | select the supporting spans with `take_note`, then finish |
| Inference | give a cited inferred answer | select only the stored facts that could support an inference; do not state the inference as evidence |
| Multiple choice | choose/commit to one option | use options only as retrieval cues and polarity checks; never choose an option |
| Citation format | model writes path citations in prose | model supplies selectors into prior observations; host derives citations |
| Absence | natural-language “not found” after fallback | structured `not_found_after_global_fallback` stop only after a verified global fallback |
| Output | direct prose answer | `finish_search` is mandatory; free-form answer text is invalid |

Unchanged route/probe/read/search-cost language is marked
`paper_published_text_reused`. Every responsibility, stopping, evidence action and
output change is marked `controlled_modification` in the prompt manifest and redline.

## 5. Capability boundary

### 5.1 Paper filesystem tools

The ordered filesystem profile is:

1. `view`
2. `grep`
3. `toc`
4. `section_read`

Their descriptions and parameters are transcribed from Table 12. The complete JSON
function wrapper, `additionalProperties: false`, Python regex semantics, default
case-insensitivity, default `max_results`, stable path ordering, line-number rendering,
and heading parser behavior are project-defined and must be frozen by hash and tests.

### 5.2 Project orchestration actions

`take_note` and `finish_search` are not Filesystem paper tools. They are host-side
evidence-only orchestration actions and must be reported separately.

- `take_note` accepts selectors only. It cannot accept evidence text, source locators,
  dates, speakers, answers or model-authored quotations.
- Every selected inclusive line range must be wholly covered by a previous successful
  `view`, `grep`, or `section_read` observation in this episode.
- A directory `view`, `toc`, failed call, truncated/unreturned match, or unobserved gap
  creates no noteable evidence coverage.
- The host re-reads the frozen store and derives exact text, citation, locators and
  hashes. Model claims never become evidence by themselves.
- `finish_search` carries only a structured stop reason and missing-aspect labels. It
  cannot carry an answer or evidence text and must be the only action in its response.

Fixed stop reasons:

- `evidence_sufficient`
- `not_found_after_global_fallback`
- `no_progress_after_global_fallback`
- `evidence_budget_reached`
- `round_limit`
- `protocol_failure`

`evidence_sufficient` requires at least one validated EvidenceItem. The two global
fallback reasons require both a root survey and a whole-tree body grep. Round limit is
a completed retrieval outcome with `hit_cap=true`, not an infrastructure failure.
`no_progress_after_global_fallback` additionally requires two consecutive provider
rounds with no newly accepted evidence.

## 6. Evidence integrity

The host maintains an immutable observation ledger. Each successful filesystem result
receives an `observation_id` and explicit path/line coverage. A note resolver must:

1. reject any path or line not fully covered by the named observation;
2. reject frontmatter-only evidence, symlinks, invalid UTF-8, cross-section selections,
   and a store that changed after the observation;
3. re-read the source lines from disk;
4. compute exact text and SHA-256 without trusting model text;
5. extract only valid `[SxTy]` locators and resolve them through the frozen
   `source_map.json` and canonical records;
6. keep singular speaker/date fields null when an item has multiple values rather than
   guessing;
7. deduplicate identical selections and deterministically merge overlapping/adjacent
   ranges only when every line in the union was observed;
8. derive stable EvidenceItem and EvidenceBundle identifiers from canonical JSON.

No gold answer, category, gold evidence ID, or evaluation label may enter prompts,
tools, traces visible to the model, or the online question object.

## 7. Store mounting and identity

- S1 mounts `experiments/locomo-conv50-v1/stores/s1-flat` and validates
  `s1-flat.json`.
- S2 mounts `stores/s2-foldered` and validates its manifest, path map, trace and
  `s2-foldered.COMMITTED` marker.
- S3 mounts only the published `stores/s3-curated` and validates its manifest, trace and
  `s3-curated.COMMITTED` marker. A staging or quarantine tree is never a valid E5 input.

The store must exist before a filesystem object is constructed. A whole-store identity
is computed before the first model call and after finalization. Any byte, path or
manifest drift invalidates the cell; the runner never modifies the store.

The manifest and, for S2/S3, the `COMMITTED` marker are accepted only against hashes
already frozen in the runtime contract. The verifier binds that externally pinned
manifest to the canonical `source_map.json` and records, recomputes the exact file and
directory tree, validates every source-index placement against mounted bytes, and
remembers the canonical resolved mount root. A byte-identical copy at another path is
still rejected: content-addressing alone must not make a staging or quarantine copy a
formal input.

## 8. EvidenceBundle boundary

The shared `EvidenceBundle` will contain:

- schema/protocol version and deterministic bundle ID;
- the exact online question object and its hash;
- experiment cell, store ID and immutable store snapshot identity;
- published-prompt, derived-prompt, filesystem-tool, orchestration and runtime hashes;
- ordered search actions and observation coverage summary;
- selected notes and normalized EvidenceItems;
- stop reason, missing aspects, hit-cap and budget flags;
- provider rounds, model calls, four-tool calls, orchestration calls and aggregate
  prompt/completion/total token usage; the hash-bound trace retains the same usage for
  each individual normal, correction and compaction completion;
- requested/served model and safe provider metadata;
- pre/post store hashes and verification result;

`EvidenceBundle` is retrieval-neutral so R1, R2, R3 adapters and fusion can use one
validated boundary. Its R1 profile additionally requires `retrieval_id=r1` and null
rank/score fields. An unsuccessful or interrupted run must not emit a partially valid
bundle: it emits a separate, hash-addressed `RetrievalFailureArtifact` containing only
safe failure and recovery metadata.

R1 rank and score fields are null. Evidence text is the exact selected store text.
Token budgets will not be claimed until a tokenizer ID/version/hash suitable for the
served model is explicitly frozen; bytes and Unicode character counts may be recorded
without pretending they are tokens. Provider-reported API usage is a separate cost
measurement and safety signal; it does not truncate or rank evidence.

The schema implementation is fail-closed: online questions have an exact allow-list
that excludes gold answers, categories and gold evidence; provenance is derived from
the frozen catalog rather than model text; raw selections must contain complete
canonical source-turn blocks; curated selections must be physical fact lines with
valid inline locators; nested records are deeply immutable; deterministic IDs and
hashes are recomputed during validation; and evidence selection ordinals must be
unique and strictly increasing in serialized order. The bundle rejects overlapping
ranges from the same file; deterministic overlap/adjacency merging belongs to the
later observation-ledger resolver and cannot be deferred to the Answerer.
Protocol arrays accept only ordered list/tuple inputs—sets, mappings, generators and
strings are rejected rather than assigned an accidental iteration order. Numeric
retrieval scores have one canonical float representation, including normalization of
negative zero, so equivalent inputs cannot produce different artifact IDs.

## 9. Required implementation sequence and gates

1. Freeze Prompt 5/6/7 transcriptions, the three derived prompts, redlines and hashes.
2. Implement and validate the shared evidence schema and canonical serialization.
3. Freeze the four paper tools and the two orchestration-action schemas separately.
4. Implement the observation ledger and anti-forgery note resolver.
5. Implement the dedicated Research Agent state machine and 20/20/40 mappings.
6. Implement store preflight/snapshot validation for S1/S2/S3.
7. Implement atomic traces, bundles, verifier and safe failure artifacts.
8. Pass unit, property-style boundary, fake-provider end-to-end and tamper tests.
9. Run only a small dev-set API smoke test after S3 is formally published.
10. Add batch execution only after the single-cell protocol is frozen and verified.

Every gate must be completed in order. A later stage may not compensate for an
unfrozen or unverifiable earlier stage.
