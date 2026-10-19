# Report Appendices: Content Register and Maintenance Plan

**Document status:** living register for the final report

**Chapters audited:** Chapters 1–3

**Last updated:** 19 October 2026

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
- Token-overlap versus LLM-judge disagreement cases.
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

## 6. Authoritative Source-of-Record Inventory

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
| LLM judge | To be frozen during the Chapter 4 appendix pass; begin from `docs/plans/llm-as-judge-v1-protocol.md` and the final Main-60 scoring manifests | Do not use the early protocol document alone as the final source. Reconcile it with the completed rescoring manifest, served model, and final rubric before typesetting Appendix A.8. |

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

## 7. Immediate Appendix Build Queue after Chapters 1–3

The following items should be assembled before or alongside Chapter 4 because they define the scientific protocol:

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

The following items must wait until Chapter 4 or the results analysis is frozen:

1. Final statistical estimators and confidence-interval procedures.
2. Manual error-analysis rubric, sample, reviewer protocol, and adjudication outcomes.
3. Complete cost-amortisation and Pareto decision rules.
4. Supplementary per-question results, category results, robustness checks, and case studies.

## 8. Maintenance Rule for Every Later Chapter

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

- **Chapter 4:** primarily Appendices B, F, G, and H.
- **Chapter 5:** primarily Appendices H and I.
- **Discussion and limitations chapters:** primarily Appendix I, with optional links to J.
- **Conclusion:** normally no new appendix material unless it introduces a new decision table or deployment checklist.

This maintenance rule is part of the report workflow. A chapter is not considered fully complete until its appendix audit has been added to this register.
