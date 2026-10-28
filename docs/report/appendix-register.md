# Report Appendices: Content Register and Maintenance Plan

**Document status:** living register for the final report

**Chapters audited:** Chapters 1–4 and Chapter 5 Sections 5.2–5.4 and 5.6 (RQ1–RQ3 and RQ5)

**Last updated:** 26 October 2026

## 1. Purpose and Editorial Rule

This file records material that should appear in the final report appendices. It is not yet the final typeset appendix. When the report is migrated to LaTeX, the items below should be converted into numbered appendix chapters and linked from the relevant main-text sections.

The main report must remain understandable without consulting the appendices. The appendices should contain exact, reproducible, or supplementary details that would interrupt the argument if placed in the main text. In particular:

- conceptual motivation, research questions, methodological justification, and interpretation remain in the main chapters;
- complete prompts, schemas, algorithms, manifests, parameter tables, long inventories, supplementary results, and coding guides belong in the appendices;
- the report must distinguish material inherited from prior work, adapted from prior work, and defined by this project;
- Main-60 must always be treated as one unified 60-question test set, without an old-40/new-20 results split;
- local engineering details that do not affect the scientific method—such as shell commands, process identifiers, run locks, local absolute paths, API keys, or credential-handling procedures—must not appear in the report appendices;
- no appendix may expose credentials, private tokens, or other secrets.

### Status labels

- **Ready:** the authoritative information already exists and can be formatted for the appendix.
- **Compile:** the underlying artefacts exist, but they must be consolidated into a publication-facing table, listing, or example.
- **Deferred:** the item depends on Chapter 4, the final analysis, or manual review.
- **Optional:** useful supplementary material, but not required for reproducibility.
- **None:** no separate appendix material is needed.

## 2. Proposed Final Appendix Structure

### Appendix A. Complete Prompt Templates

This appendix should reproduce the exact frozen text, including system instructions, user templates, variable placeholders, allowed actions, output schemas, and version identifiers.

- **A.1 S3 Management Agent prompt and input wrapper**
- **A.2 R1 Retrieval Agent prompt: common instructions and S1/S2/S3 routing variants**
- **A.3 R2 raw-chat Retrieval Agent prompt and action schema**
- **A.4 R3 curated-memory Retrieval Agent prompt and action schema**
- **A.5 Shared Answerer prompt and evidence renderer**
- **A.6 Answer-format repair prompt**
- **A.7 Full Context Answerer wrapper and any deliberate difference from A.5**
- **A.8 LLM judge prompt, rubric, and structured-output schema**

For every prompt, report the prompt ID, scientific role, applicable conditions, input variables, output contract, and cryptographic hash or version identifier. Prompt text should be copied from the frozen source of record rather than reconstructed from prose.

### Appendix B. Dataset and Unified Main-60 Manifest

- LoCoMo release, source URL, licence, version or commit, and source-file fingerprint.
- Selected conversation identifier and its 30-session composition.
- Unified ordered list of all 60 question IDs.
- Category for each question and final category totals.
- Gold-answer and gold-evidence field formats.
- Evidence-metric eligibility for each question, including questions without usable annotated evidence.
- Inclusion and exclusion rules.
- Treatment of image captions and the decision not to rerun a vision model.

### Appendix C. Data Schemas, Notation, and Provenance

- Extended notation table.
- Canonical source-record schema.
- Exchange-unit schema.
- Source-map schema and locator rules.
- RetrievalTrace schema for R1, R2, and R3.
- EvidenceItem and EvidenceBundle schemas.
- RunRecord and offline evaluation-record schemas.
- Online field allowlist and evaluation-only field list.
- Worked provenance examples tracing one source item through S1, S2, S3, retrieval, EvidenceBundle construction, and evaluation.
- Validation rules and failure handling for invalid or unresolved provenance.

### Appendix D. Memory-Store Construction and Frozen Snapshots

- S1 directory tree, naming convention, file template, counts, sizes, and fingerprint.
- S2 directory tree, topic taxonomy, complete S1-to-S2 path map, byte-identity verification, counts, sizes, and fingerprint.
- S3 construction procedure, incremental update policy, entity/topic organisation, counts, sizes, source coverage, and fingerprint.
- One concise example showing how the same source information appears in S1, S2, and S3.
- Store-integrity checks and the boundary between content preservation and content transformation.
- Construction-call, token, and time totals where scientifically relevant.

### Appendix E. Retrieval, Fusion, and Full Context Specifications

- R1 tool schemas, observation format, action modes, round semantics, round caps, evidence-note validation, and stopping contract.
- R2 tokenisation, BM25 settings, exchange and session ranking, Reciprocal Rank Fusion, top-k, neighbourhood expansion, date filtering, seen-session state, tie-breaking, action cap, and evidence validation.
- R3 fact indexing, topic aggregation, Reciprocal Rank Fusion, neighbourhood and H2-boundary rules, date filtering, seen-topic state, tie-breaking, action cap, and evidence validation.
- Evidence ordering, merging, duplicate handling, and budget algorithm.
- E7 deterministic fusion pseudocode and parent-bundle validation.
- Full Context assembly order, included fields, source completeness, context-length statistics, and explanation of why retrieval metrics are not applicable.
- A paper-to-project deviation register for Filesystem-Based Memory and ReFind.

### Appendix F. Experimental Conditions, Model Identity, and Fixed Controls

- Complete E1–E7 and Full Context scientific condition matrix.
- Store, retriever, evidence source, Answerer interface, applicable metrics, and backbone coverage for every path.
- Fixed-control table: question order, frozen stores, evidence budgets, round/action caps, shared Answerer contract, and relevant decoding settings.
- Report-facing model names, requested aliases, actual served identities, and the roles changed together in each backbone pipeline.
- Contrast-validity table stating what changes, what is held fixed, what each comparison can identify, and what it cannot identify.
- Objective → research question → condition contrast → metric → result-location traceability matrix.

### Appendix G. Evaluation and Cost Protocols

- Exact token normalisation, tokenisation, stemming, category-specific handling, and per-question Precision, Recall, and F1 definitions.
- Macro-aggregation and zero-denominator rules.
- LLM judge label definitions and formulas for Strict Accuracy, Partial Rate, and Soft Semantic Score.
- Judge blindness, parsing, retry, and token-accounting rules.
- Gold-evidence matching procedure and formulas for Any-hit, All-hit, and Evidence Recall.
- Metric eligibility and Full Context `N/A` rules.
- Data dictionary for model calls, tool calls, input/output tokens, latency, failed attempts, retries, construction cost, query-time cost, and judge cost.
- Boundaries separating one-time construction cost, per-question cost, recovery cost, and evaluation cost.

### Appendix H. Statistical and Error-Analysis Protocols

- Exact paired contrasts for the research questions.
- Per-question difference, win/tie/loss, confidence-interval, bootstrap, and interaction definitions.
- Stage B bootstrap settings: 10,000 complete-question-block resamples, seed `20261021`, Type-7 percentile interpolation at 2.5% and 97.5%, and hard failure rather than missing-value imputation.
- Strict transition rule: `not-correct` combines `partial` and `incorrect`, while a separate 3×3 table preserves all three semantic Judge labels.
- Cross-backbone stability criteria and missing-record policy.
- E7 repair/preserve/harm/unresolved definitions.
- Full Context paired-diagnostic classification.
- Stage-based error taxonomy: storage, retrieval, evidence packaging, utilisation, long-context, scoring disagreement, mixed, and indeterminate.
- Manual-review form, sampling procedure, reviewer instructions, adjudication rule, and agreement statistics where applicable.
- Pareto-dominance, cost amortisation, sensitivity, and deployment-decision rules.

### Appendix I. Supplementary Results and Case Analyses

- Per-question results and paired-difference tables.
- Category-level results that are too detailed for the main chapter.
- Extended confidence intervals and robustness checks.
- E7 repair and interference examples.
- Full Context repair and long-context failure examples.
- Token-overlap versus LLM judge disagreement cases.
- Retrieval-success/answer-failure and storage-omission cases.
- Additional quality–cost and sensitivity plots.

### Appendix J. Prior-Work, Table, Figure, and Asset Provenance

- Claim-to-source location register for the core literature.
- Filesystem-Based Memory inherited/adapted/project-defined matrix.
- ReFind inherited/adapted/project-defined matrix.
- Optional explanation of excluded vector and graph baselines without implying that they were executed.
- Provenance for every report figure and synthesis table.
- Editable-source location, rendered asset, generator where applicable, and checksum for each figure.
- Explicit labels for project-defined diagrams, conceptually adapted diagrams, and empirical results.

The final References section remains separate. Appendix J supports verification and adaptation tracing; it does not replace the bibliography.

## 3. Chapter 1 Audit: Introduction

Nothing in Chapter 1 should be removed solely because an appendix exists. The chapter contains the motivation, research gap, objectives, questions, contributions, and scope required to understand the study. The appendix obligations below expand details that Chapter 1 deliberately summarises.

| Chapter 1 subsection | Appendix decision | Required appendix material | Destination and status |
|---|---|---|---|
| 1.1.1 From Single-Turn Question Answering to Long-Term Interactive Agents | None | Literature references remain in the bibliography; no experiment-specific supplement is needed. | None |
| 1.1.2 A Long Context Window Is Not a Long-Term Memory System | Required expansion | Exact Full Context serialisation, session ordering, included fields, shared Answerer contract, model/context limit, and input-length distribution. | E/F/G — Compile/Deferred |
| 1.1.3 External Memory as a Storage–Retrieval–Utilisation System | Required expansion | Formal stage-to-artifact mapping from stored source through retrieval trace, EvidenceBundle, candidate answer, and evaluation record. | C/E/G — Compile |
| 1.2.1 Storage: Fidelity, Organisation, and Compression | Required expansion | S1/S2/S3 directory examples, counts, sizes, fingerprints, S2 path map, S3 construction prompt and contract, provenance rules, and one cross-store example. | A/D — Compile |
| 1.2.2 Retrieval: Coverage, Noise, and Cost | Required expansion | Full R1/R2/R3 specifications, prompts, actions, ranked units, BM25/RRF parameters, expansion, temporal filtering, caps, budget, duplicate handling, and stopping. | A/E — Compile |
| 1.2.3 Utilisation: Visible Evidence Does Not Guarantee a Correct Answer | Required expansion | Shared Answerer prompt, input/output schema, evidence-only rule, citation handling, insufficient-evidence behaviour, and the utilisation-error coding rule. | A/C/H — Compile/Deferred |
| 1.2.4 Evaluation: One Final Score Is Insufficient | Required expansion | Exact deterministic metrics, evidence-eligibility list, judge rubric and mappings, evidence metrics, and process/cost-accounting boundaries. | B/G — Compile/Deferred |
| 1.3.1 Existing Memory Representations | Optional | Expanded prior-system representation matrix, included only after source-by-source verification. | J — Optional |
| 1.3.2 Retrieval Paradigms | Required expansion | Side-by-side R1/R2/R3/Full Context contract and parameter crosswalk. | E — Compile |
| 1.3.3 Evaluation Practices | Optional expansion | Extended metric limitations and carefully selected disagreement examples. | G/I — Deferred |
| 1.3.4 Unresolved Gaps | None directly | Operational responses are already covered by Appendices F–H. | None |
| 1.3.5 Response of This Study | Required expansion | Complete scientific condition matrix and fixed-control table. | F — Compile |
| 1.4.1 Overall Objective | None | No standalone appendix item. | None |
| 1.4.2 Specific Objectives | Useful expansion | Objective → RQ → contrast → metric → report output traceability matrix. | F — Deferred until result numbering is stable |
| 1.5.1 Architecture: RQ1 | Required expansion | Exact matched contrasts, pairing, win/tie/loss, paired mean difference, confidence intervals, and storage × retrieval interaction definition. | H — Deferred |
| 1.5.2 Robustness: RQ2 | Required expansion | Cross-backbone matching, stability rule, effect interaction, missing-record policy, and model-role mapping. | F/H — Deferred |
| 1.5.3 Mechanisms: RQ3–RQ5 | Required expansion | E7 outcome classes; Full Context paired-diagnostic rules; stage-error taxonomy; manual sampling, review, and adjudication. | H/I — Deferred |
| 1.5.4 Decision-Making: RQ6 | Required expansion | Cost formulas, accounting boundaries, Pareto rules, amortisation assumptions, deployment profiles, and sensitivity checks. | G/H/I — Deferred |
| RQ summary table following 1.5.4 | Useful expansion | A longer traceability matrix may extend the concise main-text table; do not duplicate it verbatim. | F — Deferred |
| 1.6.1 Controlled Experimental Design | No new item | Supported by the condition and contrast registers. | F/H |
| 1.6.2 Evidence Across Backbone Models and Full Context | Required expansion | Scientific model identity, role mapping, fixed stores, and Full Context backbone scope. | F — Compile |
| 1.6.3 Multi-Level Evaluation and Error Diagnosis | No new item | Supported by evaluation and error-analysis appendices. | G/H |
| 1.6.4 Practical Decision Support | No new item | Supported by Pareto, sensitivity, and decision-rule supplements. | H/I |
| 1.7.1 Included Scope | Required expansion | Unified Main-60 inventory, ordered IDs, category totals, evidence eligibility, dataset fingerprint, and condition/backbone coverage. | B/F — Compile |
| 1.7.2 Excluded Scope | Optional | A short excluded-baseline rationale may be added in Appendix J or the limitations chapter. | J — Optional |
| 1.7.3 Limits on Interpretation | Required expansion | Contrast-validity table, including coupled Retrieval Agent/Answerer backbone changes, integrated S3 comparisons, and diagnostic-only Full Context. | F/H — Compile |

## 4. Chapter 2 Audit: Background and Related Work

Chapter 2 should remain readable without the appendices. Its definitions, comparison tables, literature synthesis, and gap argument should stay in the main body. The appendices provide source locations, adaptation boundaries, and the exact operational details promised by the chapter.

| Chapter 2 subsection | Appendix decision | Required appendix material | Destination and status |
|---|---|---|---|
| 2.1.1 Parametric, Contextual, and External Memory | None | Keep a claim-to-source mapping internally; no dedicated report appendix item is required. | None/J internal register |
| 2.1.2 The Long-Term Memory Lifecycle | Optional | Glossary for writing, organisation, retrieval, utilisation, and maintenance; state which stages were or were not experimentally tested. | C/J — Optional |
| 2.1.3 Storage, Retrieval, and Utilisation as Distinct Problems | Required expansion | Stage-diagnosis coding guide with storage, retrieval, utilisation, mixed, and indeterminate cases; review form and adjudication rule. | H — Deferred |
| 2.1.4 Principal Design Axes of Long-Term Memory Systems | Required expansion | Axis-to-condition map stating which E1–E7/Full Context contrasts operationalise an axis and which axes remain observational. | F/H — Compile |
| 2.2.1 Raw Dialogue and Log-Based Storage | No new item | Concrete source schemas and maps are covered by Appendices B–D. | B/C/D |
| 2.2.2 Filesystem-Based Memory | Required expansion | Exact S1/S2 trees, naming, sample file, fingerprints, and exposed tools. | D/E — Compile |
| 2.2.3 Agent-Curated or Summarised Memory | Mandatory | Complete S3 construction prompt, wrapper, chunk/input policy, action/output schemas, attribution/update rules, snapshot fingerprint, and paper-derived versus project-defined boundary. | A/D/J — Compile |
| 2.2.4 Vector, Graph, and Other Structured Memories | Optional | Excluded-baseline rationale for vector, graph, Mem0, A-MEM, and related systems; do not add unrun implementation details. | J — Optional |
| 2.2.5 Comparison of Representations and Scope of This Study | Optional | Expanded source-support matrix while preserving that Table 2.1 is a conceptual synthesis, not an empirical ranking. | J — Optional |
| 2.3.1 Agentic File Navigation and Text Search | Mandatory | Complete R1 prompt, tools, loop, round definition and caps, `take_note`, `finish_search`, evidence budget, and one schematic trace. | A/E — Compile |
| 2.3.2 Lexical Ranking and Iterative Retrieval | Mandatory | Complete R2 specification, including tokenisation, BM25/RRF, units, aggregation, expansion, dates, seen-state, actions, cap, and tie-breaking. | A/E — Compile |
| 2.3.3 Multi-Source Retrieval and Evidence Fusion | Mandatory | E7 deterministic algorithm, parent validation, ordering, provenance-aware duplicate handling, budgets, conflict preservation, and no-new-retrieval guarantee. | E — Compile |
| 2.3.4 Full Context and Long-Context Answering | Mandatory | Full Context assembly, fields, shared versus changed instructions, input-length statistics, model/context limits, and evidence-metric `N/A` rule. | A/E/G — Compile/Deferred |
| 2.3.5 Framework for Comparing Retrieval Methods | No duplicate | Use the detailed parameter crosswalk in Appendix E rather than copying Table 2.2. | E — Compile |
| 2.4.1 Memory Store, Tool Harness, and Agent Roles | Required expansion | Paper-to-project role/tool crosswalk with inherited, adapted, and project-defined labels. | J — Compile |
| 2.4.2 Experimental Axes and Control Logic | Required expansion | Exact paper section/table/page references and paper-versus-project axis matrix. | J — Compile |
| 2.4.3 Main Findings and Open Questions | Required source register | Exact source locations for the qualitative findings and open questions. | J — Compile |
| 2.4.4 What This Study Inherits, Changes, and Extends | Mandatory | Full parity/deviation register covering roles, tools, prompts, data, models, budgets, metrics, and unavailable details. | J — Compile |
| 2.5.1 Motivation for Searching Raw Dialogue | None | No separate appendix item. | None |
| 2.5.2 Two-Level Ranking and Iterative Search | No new item | Exact algorithm and prompt details are already required under R2. | A/E |
| 2.5.3 Empirical Findings and Cost Perspective | Required source register | Source locations for main findings, ablations, and cost claims; avoid copying entire published result tables. | J — Compile |
| 2.5.4 Boundaries of the ReFind-Style Adaptation in This Study | Mandatory | Original-versus-local matrix covering units, grouping, singleton and caption handling, temporal logic, action cap, answer separation, and R3 adaptation. | E/J — Compile |
| 2.5.5 Complementarity of Filesystem Memory and ReFind | Provenance only | Record the conceptual sources and editable asset for Figure 2.2; do not repeat the figure. | J — Ready |
| 2.6.1 LoCoMo Data Structure | Mandatory | Release/version/licence/hash, selected conversation, schema, identifiers, caption handling, and source-map construction. | B/C — Compile |
| 2.6.2 Question Categories and Required Capabilities | Mandatory | Unified Main-60 IDs, frozen order, categories, evidence form, and inclusion/exclusion rules. | B — Compile |
| 2.6.3 Gold Answers, Gold Evidence, and Evaluation Boundaries | Mandatory | Annotation format, source-ID mapping, eligibility rule, missing/incomplete annotations, alternate-support caveat, and exact evidence-metric exclusions. | B/G — Compile |
| 2.6.4 Why LoCoMo Is Used | No new item | Link to the dataset manifest rather than adding repeated prose. | B |
| 2.7.1 Token Precision, Recall, and F1 | Mandatory | Full evaluator specification, formulas, normalisation, category rules, edge cases, aggregation, and status of official versus project-defined metrics. | G — Compile |
| 2.7.2 Semantic Evaluation with an LLM judge | Mandatory | Full judge prompt/rubric/schema, label meanings, metric mappings, judge identity, blindness, parsing/retries, cost, and validation procedure. | A/F/G — Compile/Deferred |
| 2.7.3 Evidence-Level Evaluation | Mandatory | Any-hit, All-hit, and Evidence Recall formulas; source matching, union/deduplication, denominator, eligibility, and Full Context `N/A`. | G — Compile |
| 2.7.4 Process, Efficiency, and Reliability Metrics | Mandatory | Metric data dictionary, measurement units, aggregation, failed attempts, recovery, construction/query/judge boundaries, and amortisation choice. | G — Compile/Deferred |
| 2.7.5 Why Multi-Perspective Evaluation Is Needed | Consolidate | One formula catalogue and metric-to-pipeline-stage map; do not duplicate Table 2.4 or Figure 2.4. | G — Compile |
| 2.8.1 Related-Work Comparison Matrix | Required source register | Detailed source-location and comparability register supporting the scope claims in Tables 2.5(a–b). | J — Compile |
| 2.8.2 From Literature Gaps to the Study Design | Required expansion | Gap → RQ → contrast → metric → planned inference map. | F/H — Deferred |
| 2.8.3 Boundaries Relative to the Two Core Papers | No new item | Link to the complete inherited/adapted/project-defined matrices. | J |
| 2.8.4 Transition to Chapter 3 | None | No appendix item. | None |

### Chapter 2 tables and figures

All six Chapter 2 tables and all four Chapter 2 figures should remain in the main body. They should not be duplicated in the appendices. Appendix J should record only their sources, adaptation status, editable artefacts, generators where applicable, and checksums.

Two audit inconsistencies were corrected on 19 October 2026. The Chapter 2 figure generator now states that Figures 2.1 and 2.4 are manually refined FigJam flowcharts rather than generated Mermaid assets. The citation audit for reference [2] now points to Section 2.1.2, which is its actual in-text location in Chapter 2.

## 5. Chapter 3 Audit: System Design and Methodology

Chapter 3 must explain the system well enough for a reader to understand every condition without reading raw prompts or implementation files. The appendices should preserve exact contracts and reproducibility details.

| Chapter 3 subsection | Appendix decision | Required appendix material | Destination and status |
|---|---|---|---|
| 3.1.1 Separating Storage, Retrieval, and Answering | Required expansion | Stage-to-artifact map and formal failure-attribution guide. | C/H — Compile/Deferred |
| 3.1.2 Requirement 1: Isolating Storage Organisation | Mandatory evidence | S1/S2 file-body identity proof, path map, directory trees, fingerprints, and controlled-variable statement. | D/F — Compile |
| 3.1.3 Requirement 2: Comparing Retrieval Strategies on the Same Memory | Mandatory evidence | Exact matched contrasts, exposed differences, R2 folder-path observation rule, and interaction estimator. | E/F/H — Compile/Deferred |
| 3.1.4 Requirement 3: Evaluating Curated Memory as a Complete System | Mandatory | S3 construction contract, complete prompt, store snapshot, coverage summary, and explicit reason it is not a single-factor ablation. | A/D/F — Compile |
| 3.1.5 Requirement 4: Testing Raw–Curated Complementarity | Mandatory | E7 parent identity, fusion pseudocode, ordering, duplicate key, budgets, and repair/harm analysis rule. | E/H — Compile/Deferred |
| 3.1.6 Requirement 5: Distinguishing Retrieval Failure from Long-Context Failure | Mandatory | Full Context assembly and paired-diagnostic classification; context-length and cost summary. | E/G/H — Compile/Deferred |
| 3.1.7 Requirement 6: Controlling the Answering Stage | Mandatory | Shared Answerer prompt, renderer, input allowlist, output schema, condition blindness, and decoding controls. | A/C/F — Compile |
| 3.1.8 Derivation of the Final Condition Set | Required expansion | Complete condition/control matrix; do not duplicate Table 3.1 verbatim. | F — Compile |
| 3.2.1 Conversation, Session, and Source Turn | Required expansion | Extended symbol glossary and canonical source-record schema. | B/C — Compile |
| 3.2.2 Question and Evaluation-Only Information | Mandatory | Online versus offline field allowlist, schema boundary, and leakage checks. | C/F/G — Compile |
| 3.2.3 Memory Representation | Required expansion | Transformation outputs and representation-level schema for S1/S2/S3. | C/D — Compile |
| 3.2.4 Retrieval Trace and Evidence Selection | Mandatory | Concrete trace schemas and example trace for each retriever. | C/E — Compile |
| 3.2.5 EvidenceBundle | Mandatory | Exact EvidenceItem/EvidenceBundle schema, types, invariants, ordering, and provenance fields. | C — Compile |
| 3.2.6 Answer Generation | Mandatory | Selective and Full Context input renderers, shared objective, and controlled differences. | A/C/E — Compile |
| 3.2.7 RunRecord and Offline Evaluation Record | Mandatory | Full field dictionary, optional/null fields, online/offline split, and metric attachment procedure. | C/G — Compile |
| 3.3.1 Layered System Structure | Useful expansion | Layer-to-artifact and layer-to-record-field map; keep the main architecture figure in Chapter 3. | C/E — Compile |
| 3.3.2 Selective-Retrieval Paths | Required expansion | Contract table for each single-source path and one representative trace per retrieval family. | E/F — Compile |
| 3.3.3 Fusion Path | Mandatory | Deterministic fusion pseudocode and validation preconditions. | E — Compile |
| 3.3.4 Full Context Path | Mandatory | Exact non-selective packaging specification and completeness verification. | E — Compile |
| 3.3.5 Online and Offline Boundaries | Mandatory | Field allowlist, evaluator attachment sequence, and leakage-test description. | C/G — Compile |
| 3.4.1 Canonical Source Records | Mandatory | Canonical schema, field meanings, selected-source manifest, locator grammar, caption handling, and record counts. | B/C — Compile |
| 3.4.2 Raw Session Serialisation | Required expansion | Exact Markdown template, filename convention, session ordering, and preservation checks. | D — Compile |
| 3.4.3 Exchange Construction | Required expansion | Deterministic algorithm, one worked odd/even example, coverage invariant, and validation totals. | C/E — Compile |
| 3.4.4 Source Map and Stable Provenance | Mandatory | Source-map schema, mapping rules, example records, and original-ID relationship. | C — Compile |
| 3.4.5 Traceability across S1, S2, and S3 | Mandatory | One worked cross-representation trace and source-coverage caveat for S3. | C/D — Compile |
| 3.4.6 Conceptual Integrity Requirements | Mandatory evidence | Integrity-check catalogue, expected invariants, validation method, and publication-facing outcomes. | C/D — Compile |
| 3.5.1 S1: Flat Raw Sessions | Mandatory | Directory tree, file template, counts, size, source coverage, and fingerprint. | D — Compile |
| 3.5.2 S2: Foldered Raw Sessions | Mandatory | Directory tree, folder taxonomy, S1-to-S2 map, byte-identity evidence, counts, size, and fingerprint. | D — Compile |
| 3.5.3 S3: Agent-Curated Memory | Mandatory | Full Management Agent prompt and wrapper, input/update policy, file/fact schema, provenance rules, construction procedure and cost, counts, source coverage, fingerprint, and one curation example. | A/D/J — Compile |
| 3.6.1 R1: Agentic Filesystem Retrieval | Mandatory | Full prompts, tool/action schemas, observation format, evidence-note rules, one-mode-per-round rule, cap by store, correction/compaction accounting, and stopping contract. | A/E/F — Compile |
| 3.6.2 R2: ReFind-Style Raw-Chat Retrieval | Mandatory | Full prompt, lexical-query action, BM25/tokenisation, aggregation, RRF, top-k, expansion, temporal rule, seen-state, cap, tie-breaking, and evidence reconstruction. | A/E/F — Compile |
| 3.6.3 R3: Retrieval Adapted to Curated Memory | Mandatory | Full prompt, fact/topic index, ranking, RRF, topic boundaries, date rule, seen-topic state, cap, tie-breaking, provenance parsing, and R2-to-R3 deviation table. | A/E/J — Compile |
| 3.7.1 Retrieval-Neutral Evidence Interface | Mandatory | Interface contract and conversion mapping from R1/R2/R3 outputs. | C/E — Compile |
| 3.7.2 EvidenceItem Structure | Mandatory | Machine-readable schema and human-readable field dictionary. | C — Compile |
| 3.7.3 Evidence Validation | Mandatory | Validation algorithm, rejection conditions, and source-byte reconstruction rule. | C/E — Compile |
| 3.7.4 Evidence Ordering, Merging, and Budget | Mandatory | Exact order/merge/skip algorithm, duplicate policy, 16,000-character calculation, and boundary tests. | E/F — Compile |
| 3.7.5 Shared Answerer Input | Mandatory | Exact renderer, evidence-ID format, Full Context wrapping difference, and example input using synthetic content. | A/C/E — Compile |
| 3.7.6 Condition-Blind Answering | Mandatory | Explicit hidden and visible field lists, including the fact that provenance remains visible while condition labels do not. | C/F — Compile |
| 3.7.7 Output Contract | Mandatory | JSON schema, citation validation, insufficient-evidence semantics, full format-repair prompt, and retry/accounting rule. | A/C/G — Compile |
| 3.8.1 Complete Condition Map | Mandatory | Full machine- and human-readable E1–E7/Full Context matrix, model coverage, budgets, caps, and applicable metrics. | F — Compile |
| 3.8.2 Controlled Raw-Memory Core | Mandatory analysis contract | Exact paired contrasts and folder-cue interpretation boundaries. | F/H — Deferred |
| 3.8.3 Curated-Memory Extension | Mandatory interpretation contract | Comparison-validity statement for E5/E6 and all raw-versus-curated system comparisons. | F/H — Compile |
| 3.8.4 Dual-Source Condition | Mandatory | Parent-bundle linkage, no-new-retrieval verification, and complete online-cost interpretation. | E/F/G — Compile |
| 3.8.5 Interpretation Boundaries | Mandatory | Contrast-validity matrix for every planned comparison. | F/H — Compile |
| 3.9.1 E7 Dual-Source Fusion | Mandatory | Executable-style pseudocode, duplicate key, ordering, budget checks, parent validation, invariants, and analysis labels. | E/H — Compile/Deferred |
| 3.9.2 Full Context Diagnostic Path | Mandatory | Exact 30-session assembly, ordering, fields, completeness checks, total/input-token distribution, shared Answerer differences, applicability matrix, and paired-diagnostic rules. | E/F/G/H — Compile/Deferred |

## 6. Chapter 4 Audit: Experimental Design and Evaluation Methodology

Chapter 4 defines the controlled experimental protocol and evaluation methodology. Its main text must retain the research-question mapping, experimental matrix, core metric definitions, paired-analysis logic, and high-level error taxonomy. The appendices preserve exact manifests, prompts, configuration values, evaluator rules, statistical settings, and extended review materials.

| Chapter 4 subsection | Appendix decision | Required appendix material | Destination and status |
|---|---|---|---|
| 4.1.1 Mapping Research Questions to Experimental Comparisons | Required expansion | Complete RQ → contrast → metric → output traceability matrix and machine-readable contrast register. | F/H — Compile |
| 4.1.2 Independent, Dependent, and Controlled Variables | Mandatory | Full variable dictionary, held-fixed/varied/not-applicable matrix, and metric field mapping. | F/G — Compile |
| 4.1.3 Identifiable and Non-Identifiable Effects | Mandatory | Contrast-validity table covering raw-store controls, integrated curated-memory comparisons, coupled backbone roles, E7 fusion, and diagnostic Full Context. | F/H — Compile |
| 4.1.4 Primary and Exploratory Analyses | Mandatory | Primary comparison families, exploratory-analysis labels, and reporting boundaries. | H — Compile |
| 4.2.1 LoCoMo Source and Conversation Scope | Mandatory | Dataset release, licence, fingerprints, selected-conversation manifest, session/turn counts, and caption policy. | B/C — Compile |
| 4.2.2 Composition of Main-60 | Mandatory | Unified ordered 60-question manifest, category totals, evidence eligibility, fixed order, and selection exclusions. | B — Compile |
| 4.2.3 Gold Answers and Gold Evidence | Mandatory | Gold-field formats, online/offline allowlist, source-ID conversion, evidence eligibility, and annotation-coverage caveats. | B/C/G — Compile |
| 4.3.1 Complete Experimental Matrix | Mandatory | Machine-readable 900-answer matrix, condition/backbone coverage, and repeated-observation structure. | F — Compile |
| 4.3.2 E1–E4: Controlled Storage–Retrieval Comparisons | Mandatory | Exact four-cell contrast register, folder-cue exposure rule, and DID implementation. | F/H — Compile |
| 4.3.3 E5–E6: Curated-Memory Systems | Mandatory | S3 access comparison, integrated-system interpretation rules, and forbidden single-component claims. | F/H — Compile |
| 4.3.4 E7: Dual-Source Fusion | Mandatory | Parent linkage, deterministic fusion specification, no-new-retrieval proof, recorded cost, full online cost, and repair/harm definitions. | E/F/G/H — Compile |
| 4.3.5 Full Context Diagnostic | Mandatory | Complete-history assembly, served identity, no-retrieval proof, metric-applicability rule, and paired diagnostic states. | E/F/G/H — Compile |
| 4.4.1 Backbone Models and Query-Time Roles | Mandatory | Requested aliases, served identities, applicable conditions, coupled Retrieval Agent/Answerer roles, and Full Context family-level comparison boundary. | F — Ready/Compile |
| 4.4.2 Independent LLM Judge | Mandatory | Exact prompt, rubric, schema, judge identity, condition-blind input contract, retries, parsing, and cost. | A/F/G — Compile |
| 4.5 Controlled Experimental Conditions | Mandatory | Exact budgets, caps, decoding settings, prompt identities, store identities, and applicability matrix. | A/F — Compile |
| 4.6.1 Token Precision, Recall, and F1 | Mandatory | Exact category-aware evaluator, common offline rescoring of all 900 answers, normalisation, stemming, edge cases, zero rules, tests, and macro-aggregation. Legacy runner-local Precision/Recall must remain diagnostic and must not enter report aggregates. | G — Compile |
| 4.6.2 LLM Judge Metrics | Mandatory | Label definitions, formulas, aggregation, parsing, validation, and disagreement handling. | A/G — Compile |
| 4.6.3 Evidence-Access Metrics | Mandatory | Canonical source matching, set construction, 58-question eligibility, formulas, deduplication, E7 parent-bundle applicability, and Full Context `N/A` rule. | B/G — Compile |
| 4.6.4 Process and Efficiency Metrics | Mandatory | Cost-field dictionary, measurement units, dimension-wise accounting, explicit packaging/fusion treatment, E7 recorded and online cost views, sequential/parallel latency assumptions, construction/query/recovery/Judge boundaries, and amortisation inputs. | G — Compile |
| 4.6.5 Metric Aggregation and Applicability | Required expansion | Machine-readable metric catalogue, denominator, aggregation, applicability, and primary/diagnostic status. | G — Compile |
| 4.7.1 Unit of Analysis and Paired Design | Mandatory | Pairing keys, missing-record policy, estimators, and implementation tests. | H — Compile |
| 4.7.2 Overall Paired Differences and Win/Tie/Loss | Mandatory | Exact tie rule, paired summaries, distribution outputs, and table schema. | H — Compile |
| 4.7.3 Category-Level Analysis | Mandatory | Category grouping, small-group warning, and supplementary category tables. | H/I — Deferred |
| 4.7.4 Storage–Retrieval Interaction and Backbone Stability | Mandatory | DID, contrast-of-contrasts, direction agreement, and effect-stability rules. | H — Compile |
| 4.7.5 Auxiliary Paired Bootstrap Confidence Intervals | Mandatory | Resampling unit, statistic list, replicate count, seed, percentile rule, and scope limitation. | H — Compile |
| 4.7.6 Strict-Label Transitions | Mandatory | Transition table, repair/harm mapping, optional exact McNemar specification, and selected comparison family. | H — Compile |
| 4.7.7 Multiple Comparisons and Interpretation Boundaries | Mandatory | Primary and exploratory families, any correction procedure, and reporting language. | H — Compile |
| 4.8.1 Error Categories | Mandatory | Full codebook, inclusion/exclusion rules, earliest-supported-stage rule, mixed and indeterminate handling, and examples. | H — Deferred/Compile |
| 4.8.2 Review Procedure | Mandatory | Review form, case-sampling policy, reviewer instructions, adjudication, agreement reporting, and complete casebook. | H/I — Deferred |

All eight Chapter 4 tables should remain in the main body because they define the study. They should not be duplicated in the appendices. Appendix material should expand exact specifications and supplementary outputs rather than repeat the concise main-text tables.

### Chapter 4 visual provenance

| Figure | Main-text purpose | Source retained for final typesetting |
|---|---|---|
| Figure 4.1 | Summarises the frozen inputs, three answer-generation paths, condition-blind offline evaluation, paired analysis, and error review. | `docs/report/figures/chapter-4/figure-4-1-experimental-design-and-evaluation-workflow.png`; generation notes in `figure-4-1-generation-spec.md` |
| Figure 4.3 | Defines the concise selective-retrieval error-attribution sequence; E7 and Full Context exceptions are stated in the surrounding prose. | Exact plain-text source in `docs/report/figures/chapter-4/figure-4-3-error-attribution-decision-flow.md` |

Figure 4.2 is intentionally omitted. The numbering preserves the approved report plan and must not be closed by introducing an unrequested figure.

## 7. Chapter 5 Sections 5.2–5.4 Audit: Architecture, Backbone Robustness, and Dual-Source Fusion

Section 5.2 is the first completed part of Chapter 5. Its main text must retain
the paired architectural effects, the evidence needed to interpret them, and
the bounded conclusion to RQ1. The appendices preserve complete per-question
tables, semantic transitions, category and process supplements, and reviewed
case material that would interrupt the main argument.

| RQ1 subsection | Appendix decision | Required appendix material | Destination and status |
|---|---|---|---|
| 5.2 scope and calculation contract | Mandatory | Six core effects, two descriptive anchors, target-minus-baseline directions, 60/58/19 denominator contract, the two open-domain questions with empty official gold-evidence sets, metric roles, and the 16-result-unit register. | H — Ready |
| 5.2.1 Storage organisation | Mandatory supplement | Complete paired effects, medians, F1/Soft win-tie-loss, Strict transitions, full semantic transitions, complete Evidence-to-answer matrices, category effects, and selected trace cases for E3−E1 and E4−E2. | H/I — Ready |
| 5.2.2 Retrieval-system effects | Mandatory supplement | The same complete outputs for E2−E1 and E4−E3, including multi-source evidence, process records, failure attempts, and explicit separation of R1 rounds from R2 actions. | H/I — Ready |
| 5.2.3 Storage–retrieval interaction | Mandatory | Question-level DID definition, four component effects, fixed bootstrap settings and intervals, category interactions, and Figure 5.1 machine input. | H/I/J — Ready/Compile |
| 5.2.4 Agent-Curated Memory | Mandatory supplement | E6−E5 core effect; E5−E3 and E6−E4 complete-system anchors; appendix sensitivity anchors; full evidence, semantic, category, process, and multi-source results; one-time S3 construction record; bounded S3 fidelity cases. | D/G/H/I — Ready |
| RQ1 architecture evidence matrix and conclusion | Mandatory provenance | Architecture-evidence codes, exact display-number register, table/figure input hashes, and final interpretation boundaries. | I/J — Ready/Compile |

### RQ1 tables, figure, and prose provenance

| Item | Main-text purpose | Source retained for final typesetting or appendix compilation |
|---|---|---|
| Section 5.2 final prose | Gives the audited English answer to RQ1. | `docs/report/chapter-5-rq1-architecture-effects.md` |
| Figure 5.1 | Displays the four raw 2×2 component effects and storage–retrieval interaction. | Frozen source `artifacts/chapter5-main60-analysis-v1/stage-e-rq1/figure-5-3-inputs.csv` and `.jsonl`; the frozen input filename retains its original pre-renumbering identifier. |
| Figure 5.2 | Displays the Agent-Curated Memory architecture-effect profile for E5−E3, E6−E5, and E6−E4. | Stage E `architecture-effects.*`, the rendered SVG/PNG, and `docs/report/figures/chapter-5/data-lineage.json` |
| Tables 5.3–5.4 | Separate storage-organisation answer-quality effects from lexical and evidence diagnostics. | Stage E `paired-effect-summaries.*`, `selected-bootstrap.*`, `category-summaries.*`, and `display-number-register.*` |
| Tables 5.5–5.6 | Separate retrieval-system answer-quality effects from lexical, evidence, bundle, and query-cost diagnostics. | Stage E `paired-effect-summaries.*`, `process-paired-summaries.*`, `selected-bootstrap.*`, and `display-number-register.*` |
| Table 5.7 | Reports the E1–E4 descriptive condition means underlying Figure 5.1. | Stage E `figure-5-3-inputs.*`, `condition-summaries.*`, and `display-number-register.*` |
| Table 5.8 | Reports the storage–retrieval DID estimates and question-level DID signs. | Stage E `interaction-effect-summaries.*`, `selected-bootstrap.*`, and `display-number-register.*` |
| Tables 5.9–5.10 | Separate curated-memory answer-quality effects from lexical, evidence, and bundle diagnostics. | Stage E `table-5-3-inputs.*` (a legacy artifact name), `paired-effect-summaries.*`, `process-paired-summaries.*`, and `display-number-register.*` |
| Table 5.11 | Shows selected non-exhaustive Evidence Recall × Strict cells while preserving the complete denominator in the supplement. | `conversion-summaries.*` for the compact cells and `conversion-matrices.*` for the complete matrices in the Stage E artifact |
| Table 5.12 | Summarises the audited RQ1 architectural findings and their interpretation boundaries. | Stage E `architecture-evidence-codes.*` and `display-number-register.*` |
| Exact report values | Maps every displayed value to its audited machine-readable source. | `artifacts/chapter5-main60-analysis-v1/stage-e-rq1/display-number-register.*` |

The 24 Stage D traces are a deliberately bounded explanatory sample. Appendix
I may reproduce the publication-safe casebook and review schema, but it must
not present the observed mechanism counts as a prevalence estimate. Likewise,
the six selected S3 cases do not estimate global S3 fidelity.

### RQ2 appendix audit

Section 5.3 reports the matched Qwen--DeepSeek condition means and the
directional stability of six architecture effects. The main text retains the
compact comparison and the bounded answer to RQ2. The appendices preserve the
full lexical diagnostics, effect records, classification contract, model-role
mapping, and machine-readable provenance.

| RQ2 subsection | Appendix decision | Required appendix material | Destination and status |
|---|---|---|---|
| 5.3 scope and pairing contract | Mandatory | Backbone identities, shared LLM-judge identity, 2 × 7 × 60 pairing keys, controlled fields, end-to-end attribution boundary, and Full Context exclusion. | F/H — Ready |
| 5.3.1 matched backbone performance | Mandatory supplement | Complete condition-level Precision, Recall, Token F1, Strict Accuracy, Soft Semantic Score, normalised answer length, and DeepSeek-minus-Qwen records. | H/I — Ready |
| 5.3.2 architecture robustness | Mandatory supplement | All six within-backbone effects, cross-backbone effect differences, stability taxonomy, classification basis, and complete machine-readable rows. | H/I — Ready |
| 5.3.3 answer to RQ2 | Mandatory provenance | Exact Table 5.13 inputs, audit identity, source hashes, scope exclusions, and interpretation boundaries. | I/J — Ready/Compile |

### RQ2 table and prose provenance

| Item | Main-text purpose | Source retained for final typesetting or appendix compilation |
|---|---|---|
| Section 5.3 final prose | Gives the audited English answer to RQ2. | `docs/report/chapter-5-rq1-architecture-effects.md` |
| Table 5.13, Panel A | Compares matched E1–E7 Token F1, Strict Accuracy, and Soft Semantic Score under Qwen and DeepSeek. | `artifacts/chapter5-main60-analysis-v1/rq2-backbone-robustness/condition-backbone-comparison.*` and `lexical-explanation.*` |
| Table 5.13, Panel B | Reports the six architecture effects, cross-backbone differences, and directional stability classes. | `artifacts/chapter5-main60-analysis-v1/rq2-backbone-robustness/table-5-13-inputs.*` and `architecture-stability.*` |
| Figure 5.3 | Visualises the Qwen and DeepSeek estimates for the six architecture effects on a common percentage-point scale. | `docs/report/figures/chapter-5/figure-5-3-cross-backbone-architecture-stability.{svg,png}`, `figure-5-3-data-lineage.json`, and `generate_chapter5_rq2_figure.js` |
| Exact RQ2 provenance | Preserves model identities, source hashes, scope gates, and the passed publication check. | `artifacts/chapter5-main60-analysis-v1/rq2-backbone-robustness/source-manifest.json`, `audit.json`, and `RQ2.PASSED`; `docs/analysis/chapter5-rq2-process-and-results.md` |

### RQ3 appendix audit

Section 5.4 reports the effect of the fixed E7 fusion condition relative to
its E2 and E6 parents. The main text retains the paired answer effects,
evidence-access complementarity, parent-correctness profiles, Strict outcome
states, and the principal category patterns. The appendices preserve the full
LLM-judge transition matrices, question-level diagnostics, complete category
tables, and publication-safe identifiers required for the RQ5 trace review.

| RQ3 subsection | Appendix decision | Required appendix material | Destination and status |
|---|---|---|---|
| 5.4 scope and fusion contract | Mandatory | E2/E6 parent identities, no-new-retrieval proof, 16,000-character parent budgets, 32,000-character fused budget, inherited retrieval accounting, one fused Answerer call, 120 triple pairing keys, and the 60/58 denominator contract including the two open-domain questions with empty official gold-evidence sets. | E/H — Ready |
| 5.4.1 E7 versus individual parents | Mandatory supplement | Complete Precision, Recall, Token F1, Strict, Soft, Evidence Recall, and 3×3 LLM-judge transition records for Qwen and DeepSeek E7−E2/E7−E6. | H/I — Ready |
| 5.4.2 complementarity and oracle-selector gap | Mandatory supplement | Parent Strict-correctness profiles, evidence source-ID overlap, annotated-source occurrence partitions, marginal gold coverage, union-complete counts, and the definition and limits of the descriptive oracle selector. | H/I — Ready |
| 5.4.3 Repair and possible interference | Mandatory supplement | Complete Repair/Preserve/Harm/Unresolved tables overall and by category, all 120 publication-safe diagnostics, and the four Repair plus eight Harm backbone-question records prepared for RQ5. | H/I — Ready |
| 5.4.4 answer to RQ3 | Mandatory provenance | Exact Table 5.14 and Figures 5.6–5.7 provenance, audit identity, source hashes, descriptive-only scope, and RQ5/RQ6 deferrals. | I/J — Ready/Compile |

### RQ3 table, figure, and prose provenance

| Item | Main-text purpose | Source retained for final typesetting or appendix compilation |
|---|---|---|
| Section 5.4 final prose | Gives the audited English answer to RQ3. | `docs/report/chapter-5-rq1-architecture-effects.md` |
| Table 5.14, Panel A | Reports paired E7-minus-E2/E6 answer and Evidence Recall effects. | `artifacts/chapter5-main60-analysis-v1/rq3-dual-source-fusion/parent-effects.*` and `table-5-14-inputs.*` |
| Table 5.14, Panels B–D | Reports parent correctness, source overlap and union coverage, and Strict fusion outcomes. | `parent-complementarity.*`, `evidence-source-overlap.*`, `fusion-outcomes.*`, and `fusion-outcome-summary.*` in the RQ3 artifact |
| Table 5.14, Panel E | Reports descriptive category effects and category outcome states. | `category-effects.*` and `fusion-outcomes-by-category.*` in the RQ3 artifact |
| Figure 5.4 | Explains how E2 and E6 are formed and then fused into the E7 EvidenceBundle without a new query or retrieval action. | `docs/report/figures/chapter-5/figure-5-4-e7-composition.{svg,png}` and `generate_chapter5_e7_composition_figure.js`; this explanatory diagram contains no measured result. |
| Figure 5.5 | Visualises the four parent correctness profiles and their E7 outcome flows for both backbones. | Frozen source `figure-5-6-inputs.*`; `figure-5-5-descriptive-fusion-outcome-flow.{svg,png}`, `generate_chapter5_rq3_figure.js`, and `figure-5-5-data-lineage.json` in `docs/report/figures/chapter-5/`. The frozen input filename retains its original number. |
| Exact RQ3 provenance | Preserves source hashes, pairing and budget gates, scope exclusions, and the passed publication check. | `artifacts/chapter5-main60-analysis-v1/rq3-dual-source-fusion/source-manifest.json`, `audit.json`, and `RQ3.PASSED`; `docs/analysis/chapter5-rq3-process-and-results.md` |

### RQ5 appendix audit

Section 5.6 keeps the root-cause argument and its compact evidence in the main
text. The appendices should preserve the complete case index, coding contract,
question-level diagnostics, and provenance required to reproduce or inspect
the attribution. They should not reproduce local launch, credential, or
process-control details.

| RQ5 subsection | Appendix decision | Required appendix material | Destination and status |
|---|---|---|---|
| 5.6.1 population and attribution model | Mandatory | The 900-answer population manifest, the 250-path Strict-noncorrect census, evidence-eligibility rules, ordered state model, primary-cause precedence, secondary-mechanism schema, attribution-strength tags, ambiguity policy, and publication-safe case identifiers. | H/I — Ready |
| 5.6.2 S1–S3 storage audit | Mandatory supplement | Complete storage-integrity, S2 routing, S3 source/reference-support, outcome-linkage, and 205-path storage-state records. | H/I — Ready |
| 5.6.3 R1–R3 retrieval audit | Mandatory supplement | Complete 720-path retrieval funnel, 696 evidence-eligible path records, 191 eligible Strict-error diagnostics, retriever/category profiles, controlled comparisons, cap diagnostics, and causal guards. | H/I — Ready |
| 5.6.4 downstream conversion, fusion, and Full Context | Mandatory supplement | Per-path evidence-sufficiency, packaging-loss, Answerer-conversion, E7 mechanism, Full Context category, answer-profile, and evidence-position diagnostics. | H/I — Ready |
| 5.6.5 evaluation disagreement | Mandatory supplement | Token-score distributions by LLM judge label, disagreement-case coding, cause summaries, exact-input consistency checks, and metric-sensitive architecture comparisons. | H/I — Ready |
| 5.6.6 integrated answer to RQ5 | Mandatory provenance | Mutually exclusive primary attributions for 250 paths, non-exclusive mechanisms, primary–secondary cross-tabulation, final state register, representative cases, interpretation guards, and passed audit records. | H/I — Ready |

### RQ5 storage-audit table, figure, and prose provenance

| Item | Main-text purpose | Source retained for final typesetting or appendix compilation |
|---|---|---|
| Section 5.6.2 prose | Distinguishes storage fidelity, semantic sufficiency, discoverability, and downstream failure candidates for S1–S3. | `docs/report/chapter-5-rq1-architecture-effects.md`; `docs/analysis/chapter5-rq5-storage-audit-process-and-results.md`; `fs_memory_lab/chapter5_rq5_storage.py` |
| Table 5.18, Panels A–D | Reports S1 dispersion, S2 routing quality and descriptive outcome linkage, and S3 source/reference support. | `store-integrity.*`, `s2-routing.*`, `s2-routing-session-review.*`, `s3-fact-preservation.*`, and `storage-summary.*` in `artifacts/chapter5-main60-analysis-v1/rq5-storage-audit/` |
| Table 5.19 | Links E5/E6 outcomes to S3 benchmark-reference support without treating the association as a curator effect. | `storage-outcome-linkage.*` and `s3-fact-preservation.*` in the RQ5 storage-audit artifact |
| Table 5.20 | Reports the storage state of all 205 E1–E6 Strict-noncorrect answer paths. | `case-storage-linkage.*` and `root-cause-state-register-after-storage.*` in the RQ5 storage-audit artifact |
| Figure 5.6 | Visualises the normalised storage-state distribution for the same 205 answer paths. | `figure-5-6-selective-error-storage-state.{svg,png}`, `generate_chapter5_rq5_storage_figure.js`, and `figure-5-6-data-lineage.json` in `docs/report/figures/chapter-5/` |
| Exact RQ5 storage provenance | Preserves source hashes, the outcome-blind label order, denominator gates, zero verified store-specific decisive omissions, and the passed publication check. | `artifacts/chapter5-main60-analysis-v1/rq5-storage-audit/source-manifest.json`, `audit.json`, and `RQ5-STORAGE-AUDIT.PASSED` |

### RQ5 retrieval-audit table, figure, and prose provenance

| Item | Main-text purpose | Source retained for final typesetting or appendix compilation |
|---|---|---|
| Section 5.6.3 analysis | Separates source reach, annotated-span observation, complete acquisition, note selection, and final-bundle retention for R1–R3, then distinguishes retrieval-stage attrition from errors that retain complete annotated evidence. | `docs/report/chapter-5-rq1-architecture-effects.md`; `docs/analysis/chapter5-rq5-retrieval-audit-process-and-results.md`; `fs_memory_lab/chapter5_rq5_retrieval.py` |
| Table 5.21 | Reports the R1–R3 retrieval funnel and annotated-evidence loss location among eligible Strict-error paths. | `retrieval-funnel.*`, `stage-transitions.*`, and `strict-error-retrieval-linkage.*` in `artifacts/chapter5-main60-analysis-v1/rq5-retrieval-audit/` |
| Tables 5.22–5.23 | Report retriever-level quality/cost profiles and the descriptive task-specific evidence-access recommendations. | `retriever-summary.*`, `retriever-category-summary.*`, `controlled-comparisons.*`, and `cross-backbone-comparisons.*` in the RQ5 retrieval-audit artifact |
| Figure 5.7 | Visualises the annotated-evidence state of the 191 evidence-eligible E1–E6 Strict-error paths, normalised within R1–R3 and in aggregate. | `docs/report/figures/chapter-5/figure-5-7-retrieval-error-stage-distribution.{svg,png}`, `generate_chapter5_rq5_retrieval_figure.js`, and `figure-5-7-data-lineage.json` |
| Exact RQ5 retrieval provenance | Preserves the 720/696 denominators, deterministic R2/R3 replay, canonical record hashes, causal guard, native-cap guard, and unchanged downstream state fields. | `artifacts/chapter5-main60-analysis-v1/rq5-retrieval-audit/source-manifest.json`, `schema.json`, `audit.json`, and `RQ5-RETRIEVAL-AUDIT.PASSED` |

### RQ5 downstream, evaluation, and integrated provenance

| Item | Main-text purpose | Source retained for final typesetting or appendix compilation |
|---|---|---|
| Section 5.6.1 | Defines the shared 900-answer population, the 250 Strict-noncorrect paths, evidence eligibility, the ordered diagnostic chain, and the primary/secondary attribution contract. | `artifacts/chapter5-main60-analysis-v1/rq5-root-cause-index/`; `fs_memory_lab/chapter5_rq5_stage1.py`; `docs/analysis/chapter5-rq5-stage1-process-and-results.md`; `docs/report/chapter-5-rq1-architecture-effects.md` |
| Section 5.6.4 and Tables 5.24–5.26 | Distinguish final-input sufficiency, demonstrated packaging loss, Answerer utilisation, and E7 mechanisms. | `evidence-sufficiency.*`, `packaging-loss.*`, `answerer-conversion.*`, `e7-mechanisms.*`, and `e7-parent-sufficiency-matrix.*` in `artifacts/chapter5-main60-analysis-v1/rq5-downstream-audit/`; `fs_memory_lab/chapter5_rq5_downstream.py`; `docs/analysis/chapter5-rq5-downstream-audit-process-and-results.md` |
| Tables 5.27–5.28 | Report Full Context category results, answer profiles, residual mechanisms, and evidence-position diagnostics. | `full-context-category-summary.*`, `full-context-answer-profile.*`, `full-context-mechanisms.*`, `evidence-position-summary.*`, and `evidence-position-diagnostics.*` in `artifacts/chapter5-main60-analysis-v1/rq5-full-context-audit/`; `fs_memory_lab/chapter5_rq5_full_context.py` |
| Section 5.6.5 and Tables 5.29–5.30 | Explain Token F1/LLM judge disagreement, reviewed lexical under-credit and over-credit, annotation limits, and sensitivity of the architecture findings. | `score-distributions.*`, `judge-f1-crosstab.*`, `disagreement-cases.*`, `cause-summary.*`, `cause-by-category.*`, and `metric-sensitive-architecture.*` in `artifacts/chapter5-main60-analysis-v1/rq5-evaluation-audit/`; `fs_memory_lab/chapter5_rq5_evaluation.py`; `docs/analysis/chapter5-rq5-evaluation-audit-process-and-results.md` |
| Figure 5.8 | Visualises the Token F1 distribution within each frozen LLM judge label. | `docs/report/figures/chapter-5/figure-5-8-token-f1-llm-judge-alignment.{svg,png}`, `generate_chapter5_rq5_evaluation_figure.js`, and `figure-5-8-data-lineage.json` |
| Section 5.6.6, Table 5.31 (Panels A–B), and Table 5.32 | Integrate mutually exclusive primary causes, attribution strength, co-occurring mechanisms, representative cases, and the final answer to RQ5. | `integrated-attributions.*`, `primary-root-cause-summary.*`, `cooccurring-mechanism-summary.*`, `primary-secondary-matrix.*`, `representative-cases.*`, and `root-cause-state-register-final.*` in `artifacts/chapter5-main60-analysis-v1/rq5-integrated-bottleneck/`; `fs_memory_lab/chapter5_rq5_integrated.py`; `docs/analysis/chapter5-rq5-integrated-process-and-results.md`; `docs/report/chapter-5-rq1-architecture-effects.md` |
| Figure 5.9 | Visualises all 250 primary attributions and the 123 confirmed system-internal failures under their explicitly different denominators. | `docs/report/figures/chapter-5/figure-5-9-integrated-bottleneck-decomposition.{svg,png}`, `generate_chapter5_rq5_integrated_figure.js`, and `figure-5-9-data-lineage.json` |
| Exact RQ5 downstream provenance | Preserves frozen inputs, state transitions, denominator checks, and passed audits for the downstream, Full Context, evaluation, and integrated analyses. | `source-manifest.json`, `schema.json`, `audit.json`, and the corresponding `RQ5-*.PASSED` marker in each RQ5 artifact directory listed above |

### RQ6 quality--cost and decision provenance

| Item | Main-text purpose | Source retained for final typesetting or appendix compilation |
|---|---|---|
| Section 5.7 and Tables 5.33--5.36 | Separate successful-query, construction, recovery, and evaluation costs; report Pareto membership, amortisation, and scenario-based system selection. | `artifacts/chapter5-main60-analysis-v1/rq6-quality-cost/`; `fs_memory_lab/chapter5_rq6.py`; `docs/analysis/chapter5-rq6-process-and-results.md`; `docs/report/chapter-5-rq1-architecture-effects.md` |
| Figure 5.10 | Visualises Soft Semantic Score against successful-query token cost for the exact Qwen scope and the DeepSeek-family diagnostic scope. | Frozen source `figure-5-12-inputs.*`; `docs/report/figures/chapter-5/figure-5-10-quality-cost-pareto-frontiers.{svg,png}`, `generate_chapter5_rq6_figure.js`, and `figure-5-10-data-lineage.json`. The frozen input filename retains its original pre-renumbering identifier. |
| Exact RQ6 provenance | Preserves the 900-answer source population, E7 reconstructed online-cost rule, Pareto labels, build-cost amortisation, recovery-cost separation, and Full Context comparison boundary. | `artifacts/chapter5-main60-analysis-v1/rq6-quality-cost/source-manifest.json`, `schema.json`, `audit.json`, and `RQ6.PASSED` |

## 8. Authoritative Source-of-Record Inventory

The final appendix must be compiled from the following frozen sources. Large run records and context packages should normally be cited by manifest and fingerprint rather than reproduced in full.

### A. Prompt templates and action contracts

| Component | Authoritative source(s) | Compilation note |
|---|---|---|
| S3 Management Agent | `fs_memory_lab/management_prompt.py`; `fs_memory_lab/s3_protocol.py`; `fs_memory_lab/s3_chunks.py`; `fs_memory_lab/paper_tools.py` | Copy the exact system prompt, per-chunk user template, chunk policy, and management-tool schemas. The frozen combined prompt hash is `2ceb39921adb3c5eb4da98964b4925b8886f8540f3663b8f64d1539137d6be26`. |
| S3 frozen runtime and completed construction | `experiments/locomo-conv50-v1/manifests/s3-management-runtime.json`; `experiments/locomo-conv50-v1/manifests/s3-curated.json` | Use the current runtime manifest for the contract and the curated manifest for completed build statistics and cost. Treat `s3-management-prompt.json` only as historical prompt provenance. |
| R1 | `fs_memory_lab/r1_prompts.py`; `fs_memory_lab/paper_prompts.py`; `fs_memory_lab/r1_tools.py`; `fs_memory_lab/r1_orchestration.py`; `fs_memory_lab/r1_agent.py`; `docs/reproduction/r1-prompt-manifest.json` | Preserve the distinction between the published base prompt, project-derived evidence-only variants, filesystem tools, and project-defined `take_note`/`finish_search`. |
| R2 | `fs_memory_lab/r2_prompts.py`; `fs_memory_lab/r2_tools.py`; `fs_memory_lab/r2_protocol.py`; `fs_memory_lab/r2_inputs.py`; `docs/reproduction/r2-prompt-manifest.json` | Extract exact prompt text, wire actions, cap, BM25/RRF values, expansion, seen-state, and exchange construction. |
| R3 | `fs_memory_lab/r3_prompts.py`; `fs_memory_lab/r3_tools.py`; `fs_memory_lab/r3_protocol.py`; `fs_memory_lab/r3_index.py`; `fs_memory_lab/r3_inputs.py` | Use code and formal manifests for the final status. `docs/reproduction/r3-protocol-manifest.json` is an implementation-stage provenance record, not the final status authority. |
| Shared Answerer and format repair | `fs_memory_lab/answerer.py`; `experiments/locomo-conv50-v1/formal-v1/manifest.json` | Copy the exact prompt, renderer, output keys, parser, citation validation, decoding settings, and one-repair rule. Full Context reuses this Answerer and has no independent answer prompt. |
| LLM judge | `experiments/locomo-conv50-v1/results/llm-judge-x-test1-main120/llm-judge-x-test1-model1-main60-run-01/manifest.json`; the corresponding Model 2 manifest; `local-runs/b3-full-context-v3-model2-1017-judge-x-test1/llm-judge-x-test1-b3-full-context-main60-run-01/manifest.json`; `fs_memory_lab/evaluation.py`; `fs_memory_lab/judge_main60.py` | Use the completed manifests and evaluator code as the authority for the prompt, rubric, served identity, blindness fields, label mapping, and scoring. The early protocol document remains design history rather than the final source of record. |

The repository's frozen S3, R1, R2, and R3 prompt/action/protocol verifier functions passed during this audit. They should be rerun when the exact prompt appendix is generated.

### B–D. Dataset, schemas, and stores

| Material | Authoritative source(s) | Compilation note |
|---|---|---|
| Canonical dataset and source provenance | `data/manifests/locomo-conv-50-v1.json`; `data/processed/conv-50.jsonl`; `data/manifests/source_map.json` | Use the manifest for source provenance and fingerprints, the JSONL for the canonical schema, and the source map for locator/original-ID resolution. |
| Unified Main-60 | `experiments/locomo-conv50-v1/question-sets-main60-v2/manifest.json`; `experiments/locomo-conv50-v1/question-sets-main60-v2/verification.json` | Preserve the frozen order and report one unified 60-question set. |
| Evidence schema | `fs_memory_lab/evidence.py` | Source of record for `EvidenceItem`, `StopRecord`, `BudgetRecord`, `EvidenceBundle`, serialisation, validation, and protocol ID `shared-evidence-bundle-v1`. |
| S1/S2/S3 store manifests | `experiments/locomo-conv50-v1/manifests/s1-flat.json`; `experiments/locomo-conv50-v1/manifests/s2-foldered.json`; `experiments/locomo-conv50-v1/manifests/s3-curated.json` | Compile directory, count, size, construction, and store-specific integrity information. |
| Frozen store contents | `experiments/locomo-conv50-v1/stores/` | Use only concise trees and controlled examples in the report; do not reproduce the entire stores. |
| Cross-store and formal hashes | `experiments/locomo-conv50-v1/formal-v1/manifest.json` | This manifest is the authority for the formal linked tree and cross-component identities. Do not compare its linked-tree hashes directly with differently defined store-manifest tree fields. |

### E–F. Fusion, Full Context, conditions, and models

| Component | Authoritative source(s) | Compilation note |
|---|---|---|
| E7 fusion | `fs_memory_lab/fusion.py`; `experiments/locomo-conv50-v1/formal-v1/manifest.json` | Record E2+E6 parents, no-new-search rule, interleaving, provenance-aware duplicate key, per-source budget, and total budget. Frozen contract hash: `035770f66df01bfdc937227a819ada720163fd6fa03416d88e5484ea54ae0abb`. |
| Full Context construction | `fs_memory_lab/full_context.py`; `fs_memory_lab/full_context_runner.py`; `experiments/locomo-conv50-v1/baselines/b3-full-context-v1/context-package.json`; `experiments/locomo-conv50-v1/baselines/b3-full-context-v1/manifest.json`; `experiments/locomo-conv50-v1/baselines/b3-full-context-v1/verification.json` | Extract the complete-session renderer, inclusion rules, verification, and shared-Answerer relationship. Cite the large context package by manifest/hash rather than reproducing it. |
| Full Context Main-60 run provenance | `local-runs/b3-full-context-v3-model2-1017/b3-full-context-v3-model2-1017-main60-run-01/run-manifest.json`; `local-runs/b3-full-context-v3-model2-1017/b3-full-context-v3-model2-1017-main60-run-01/pre-gold-audit.json`; `local-runs/b3-full-context-v3-model2-1017/b3-full-context-v3-model2-1017-main60-run-01/FULL-CONTEXT-MODEL2-1017-MAIN60-60.PASSED` | Use publication-safe fields only. Do not include local absolute paths or launcher details in the final appendix. |
| Qwen E1–E7 condition contract | `experiments/locomo-conv50-v1/formal-v1/manifest.json` | Source of record for the condition map, Qwen model identity, budgets, prompts, stores, Answerer, and fusion contract. |
| DeepSeek E1–E7 condition contract | `experiments/locomo-conv50-v1/formal-v2-model2/manifest.json`; `experiments/locomo-conv50-v1/results/formal-v2-model2-main60-candidate-02/run/suite-manifest.json` | Use the frozen overlay for scientific identity and the suite manifest for completed Main-60 execution provenance. |
| Qwen Main-60 extension provenance | `experiments/locomo-conv50-v1/results/formal-v2-qwen-extension20-run-01/run/formal-run-manifest.json`, interpreted with the formal-v1 and Main-60 manifests | This is provenance for completion of the unified Main-60, not a separate test-set definition or an independent result subset. |

### H–I. Completed RQ1–RQ3 and RQ5 analysis sources

| Material | Authoritative source(s) | Compilation note |
|---|---|---|
| RQ1 final audit and display values | `artifacts/chapter5-main60-analysis-v1/stage-e-rq1/`; `docs/analysis/chapter5-stage-e-protocol.md`; `docs/analysis/chapter5-stage-e-process-and-results.md` | Treat `STAGE-E-RQ1.PASSED` and `audit.json` as the publication gate. Use the display-number register rather than copying values from narrative notes. |
| RQ1 master analysis view | `artifacts/chapter5-main60-analysis-v1/stage-a/` | Use the 720-row E1–E6 view only for RQ1. Do not split Main-60 by question-construction history. |
| Raw 2×2 effects and selected bootstrap | `artifacts/chapter5-main60-analysis-v1/stage-b/` | Preserve the pre-declared 10,000-resample, seed-`20261021` bootstrap set. Do not add post hoc intervals. |
| S3 effects and sensitivity anchors | `artifacts/chapter5-main60-analysis-v1/stage-c/` | Keep core, main descriptive, and appendix sensitivity roles distinct. |
| Mechanism tables and bounded trace review | `artifacts/chapter5-main60-analysis-v1/stage-d/`; `docs/analysis/chapter5-stage-d-process-and-results.md` | Full Evidence-to-answer, category, process, and publication-safe trace records; the sample is explanatory, not a census. |
| RQ2 backbone-robustness results | `artifacts/chapter5-main60-analysis-v1/rq2-backbone-robustness/`; `docs/analysis/chapter5-rq2-process-and-results.md` | Treat `RQ2.PASSED` and `audit.json` as the publication gate. Preserve the descriptive-only scope, six-effect stability taxonomy, E7 overview-only role, and Full Context exclusion. |
| RQ3 dual-source-fusion results | `artifacts/chapter5-main60-analysis-v1/rq3-dual-source-fusion/`; `fs_memory_lab/chapter5_rq3.py`; `docs/analysis/chapter5-rq3-process-and-results.md` | Treat `RQ3.PASSED` and `audit.json` as the publication gate. Preserve the E7-minus-parent direction, the 60/58 answer/evidence denominators, Strict-only Repair/Preserve/Harm/Unresolved definitions, inherited parent-retrieval accounting, source-ID rather than text-overlap interpretation, and RQ5/RQ6 deferrals. |
| RQ5 root-cause results | `artifacts/chapter5-main60-analysis-v1/rq5-root-cause-index/`, `rq5-storage-audit/`, `rq5-retrieval-audit/`, `rq5-downstream-audit/`, `rq5-full-context-audit/`, `rq5-evaluation-audit/`, and `rq5-integrated-bottleneck/`; the corresponding `docs/analysis/chapter5-rq5-*-process-and-results.md` records | Treat each `RQ5-*.PASSED` marker and `audit.json` as a stage gate. Preserve the 900/250/233 and retrieval-specific 720/696/205/191 denominators, primary-versus-secondary attribution distinction, evaluation-sensitive category, causal guards, and publication-safe case identifiers. |

## 9. Immediate Appendix Build Queue after Chapters 1–4 and Completed Chapter 5 Analyses

The following items should be assembled before or alongside Chapter 5 because they define the scientific protocol and analysis inputs:

1. Complete prompt archive for S3, R1, R2, R3, the shared Answerer, format repair, Full Context, and the LLM judge.
2. Unified Main-60 question and evidence-eligibility manifest.
3. Canonical-record, source-map, EvidenceItem, EvidenceBundle, RunRecord, and evaluation-record schemas.
4. S1/S2/S3 store trees, counts, source coverage, and fingerprints.
5. Exact R1/R2/R3 parameter and action-contract tables.
6. Exact E7 fusion pseudocode and Full Context assembly specification.
7. Complete E1–E7/Full Context condition, model, budget, and applicability matrix.
8. Full deterministic, semantic, evidence, process, and cost evaluation specifications.
9. Filesystem-Based Memory and ReFind adaptation/deviation matrices.
10. Figure and table provenance register.

The following items still depend on the remaining Chapter 5 appendix passes or later report chapters:

1. RQ4 Full Context paired-diagnostic appendix audit and supplementary question-level table.
2. Complete cost-amortisation, Pareto, and scenario-decision outputs for RQ6.
3. Supplementary results and case studies outside the completed RQ1--RQ3 and RQ5 scope.

## 10. Chapter 6 Appendix Audit

Chapter 6 is a conceptual synthesis of the audited Chapter 5 results. It introduces no new experiment, prompt, dataset, metric, or runtime parameter. Its Evidence Controller and adaptive routing policy are explicitly presented as proposed design implications rather than implemented components. The chapter therefore requires no new appendix artifact.

| Subsection | Main-text role | Appendix decision | Exact appendix content | Destination | Source of record | Status |
|---|---|---|---|---|---|---|
| 6.1 | Defines the evidence-conversion gap by synthesising the audited failure chain | None | No new material; detailed empirical evidence already belongs to the Chapter 5 analysis appendices | Existing Appendices H–I | Chapter 5 report and frozen RQ5 artifacts | Ready |
| 6.2 | Proposes the Evidence Controller and its four responsibilities | None | No implementation exists; the conceptual responsibility list and deployment-visible signals remain in the main text | Main text only | `docs/report/chapter-6-general-discussion.md` | Ready |
| 6.3 | Proposes adaptive escalation from selective retrieval to fusion, Full Context recovery, or abstention | None | Table 6.1 is a conceptual policy table, not a measured result or deployable routing specification | Main text only | `docs/report/chapter-6-general-discussion.md` | Ready |

The references pass confirms that Chapter 6 reuses existing sources `[4]`, `[6]`, and `[7]` and introduces no new bibliography entry.

## 11. Maintenance Rule for Every Later Chapter

After the main text of each new chapter is completed, perform the following appendix pass before treating the chapter as finished:

1. List every subsection in the chapter.
2. Identify every claim that promises exact parameters, prompts, schemas, inventories, formulas, source locations, or supplementary evidence elsewhere.
3. Decide whether each item belongs in the main text, an appendix, the References section, or nowhere.
4. Add one row to this register for every subsection, including an explicit **None** decision where appropriate.
5. Assign a final appendix destination and a status label.
6. Link each required appendix item to its authoritative frozen source; never reconstruct exact prompts or parameters from memory.
7. Check that the appendix does not contradict the main chapter or duplicate a main table without adding detail.
8. Check that inherited, adapted, and project-defined components are labelled correctly.
9. Remove private implementation details and scan for credentials or secrets.
10. When the item is typeset, replace the planning status with the final appendix section and page/table/figure reference.

### Template for future chapter audits

| Subsection | Main-text role | Appendix decision | Exact appendix content | Destination | Source of record | Status |
|---|---|---|---|---|---|---|
| X.Y.Z | Brief description | Required / Optional / None | Exact reproducibility or supplementary material | Appendix ? | Frozen file or manifest | Ready / Compile / Deferred |

### Provisional future-chapter destinations

- **Chapter 4:** primarily Appendices B, F, G, and H; its register is complete, while appendix typesetting remains.
- **Chapter 5:** primarily Appendices H and I; RQ1--RQ3 and RQ5 are registered, while the RQ4 appendix pass and RQ6 remain pending.
- **Discussion and limitations chapters:** primarily Appendix I, with optional links to J.
- **Conclusion:** normally no new appendix material unless it introduces a new decision table or deployment checklist.

This maintenance rule is part of the report workflow. A chapter is not considered fully complete until its appendix audit has been added to this register.
