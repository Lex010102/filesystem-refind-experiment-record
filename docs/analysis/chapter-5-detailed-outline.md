# Chapter 5 Results and Analysis — Detailed Writing Outline

## Chapter purpose and boundary

Chapter 5 is the empirical centre of the report. Chapters 3 and 4 have already defined the system, experimental conditions, metrics, paired estimators, and error-review protocol. This chapter must therefore answer two questions:

1. **What happened under the tested conditions?**
2. **What evidence best explains the observed differences?**

The chapter should not repeat prompt text, engineering controls, metric formulas, or the full statistical protocol. Those belong in Chapters 3–4 and the appendices. It should also avoid an E1-to-E7 catalogue. Every subsection should follow one evidence chain:

```text
Research question
→ controlled comparison
→ paired result
→ evidence/process explanation
→ counterexample or boundary
→ concise finding
```

All main results use the unified Main-60 test set. C1–C4 are used only to explain heterogeneity. The analysis unit remains the question, not the 900 answer records. Literature comparison and broader implications belong mainly in Chapter 6.

## Authoritative research-question mapping

The following mapping is fixed for all later calculations, figures, tables, and subsection drafts:

| Research question | Chapter 5 location |
|---|---|
| RQ1: What effects do storage representation and retrieval strategy have, and do they interact? | Section 5.2 |
| RQ2: Are these architectural effects stable across Qwen and DeepSeek? | Section 5.3 |
| RQ3: When does dual-source fusion repair errors, and when does it introduce interference? | Section 5.4 |
| RQ4: Does Full Context outperform selective retrieval, and what bottlenecks does each approach reveal? | Section 5.5 |
| RQ5: Do errors mainly arise from storage fidelity, retrieval coverage, evidence packaging, answer utilisation, or long-context processing? | Section 5.6 |
| RQ6: Considering quality, cost, stability, and maintenance complexity, which conditions are most suitable for practical use? | Section 5.7 |

No subsection may change the meaning or numbering of these research questions. Section 5.8 consolidates the final answers to all six questions after the preceding analyses are complete.

## Shared analysis table and calculation set

Before drafting the prose, construct one auditable question-level table with one row for each evaluated answer path and question. The minimum fields are:

- `question_id`, C1–C4 category, and evidence-eligibility flag;
- backbone model, condition, storage representation, retrieval system, and access regime;
- Precision, Recall, F1, judge label, Strict indicator, Partial indicator, and Soft score;
- Evidence Recall, Any-hit, and All-hit where applicable;
- answer length, EvidenceBundle length, input/output/total tokens, model calls, latency, failure, and retry fields;
- retrieved canonical source identifiers, E7 parent identities, and error-review fields.

All paired comparisons join rows by `question_id`. The following calculations are shared across the chapter and should not be redefined in every subsection:

1. **Condition mean:** macro-average each answer metric over 60 questions and each evidence metric over the 58 eligible questions.
2. **Paired effect:** for conditions A and B, compute `d_i = metric_i(B) − metric_i(A)`, then report the mean, median, and question-level distribution.
3. **Win/tie/loss:** orient the sign so that a positive value always favours B; use the unrounded per-question values.
4. **Strict transition:** count baseline incorrect→target correct, correct→incorrect, unchanged correct, and unchanged incorrect cases.
5. **Auxiliary uncertainty:** use paired bootstrap intervals only for the limited central contrasts defined in Chapter 4. Do not make bootstrap output the organising principle of the chapter.
6. **Storage–retrieval interaction:** calculate `(E4−E2)−(E3−E1)` on each question before aggregation.
7. **Cross-backbone stability:** reuse the audited RQ1 effects, compare their direction and magnitude under Qwen and DeepSeek, and calculate a descriptive cross-backbone effect difference for the compact RQ2 table. Extensive inference remains supplementary.
8. **Evidence conversion:** compare Strict correctness under All-hit and not-All-hit, and count whether an evidence improvement is accompanied by an answer improvement.
9. **E7 outcome state:** classify each question as Repair, Preserve, Harm, or Unresolved from E2, E6, and E7 Strict states.
10. **Full Context quadrant:** classify each paired question as both correct, Full Context only correct, selective retrieval only correct, or neither correct.
11. **Cost comparison:** keep construction, query, recovery, and judge cost separate; compare conditions within each additive dimension and identify observed Pareto dominance.

Optional exact tests and confidence intervals remain supplementary. The main evidence is the paired effect size, question-level distribution, process evidence, and reviewed counterexamples.

## Recommended chapter scale

| Section | Main role | Suggested full-report length |
|---|---|---:|
| 5.1 | Establish the overall result map and explain metric disagreement | 2–2.5 pages |
| 5.2 | Identify storage, retrieval, interaction, and curated-memory effects | 4.5–5.5 pages |
| 5.3 | Test cross-backbone robustness without repeating the mechanism analysis | 1.5–2 pages |
| 5.4 | Analyse dual-source fusion | 2–2.5 pages |
| 5.5 | Compare Full Context with selective retrieval | 2–2.5 pages |
| 5.6 | Locate bottlenecks through one consolidated error review | 3–3.5 pages |
| 5.7 | Integrate quality, cost, and practical choice | 2–3 pages |
| 5.8 | Consolidate the answers to RQ1–RQ6 | 0.5–1 page |
| **Total** | **Core results and analysis** | **approximately 18–22 pages** |

Each research question now has one clear home. A shorter report can compress the tables and move secondary results to Appendices H and I without changing this argument structure.

---

## 5.1 Analysis Scope and Research Questions

**Purpose**

Provide a short reading guide before the detailed results. This section should
not repeat the complete result tables or the metric-disagreement analysis that
appears later in the chapter.

**Required content**

1. Restate the unified Main-60 scope, the two backbone models, and the separate
   DeepSeek-family Full Context diagnostic path.
2. Define E1–E7 in one compact condition table, including the storage source,
   retrieval or processing path, and analytical role.
3. State explicitly that Full Context is not E8.
4. Introduce RQ1–RQ6 in one roadmap table and point each question to Sections
   5.2–5.7.
5. Briefly name the answer-quality and evidence-access metric families, their
   60/58 denominators, and the inapplicability of retrieval-level Evidence
   Recall to Full Context.

**Required output**

- **Table 5.1:** E1–E7 and Full Context condition mapping;
- **Table 5.2:** RQ1–RQ6 chapter roadmap;
- one short transition to the detailed analyses in Sections 5.2–5.7.

**Interpretation boundary**

Section 5.1 introduces labels, scope, and questions only. Exact results,
paired effects, metric disagreements, mechanisms, and practical decisions are
reported in the corresponding later sections.

---

## 5.2 Architecture Effects: Storage, Retrieval, and Their Interaction

**RQ1 fixed scope and comparison inventory**

RQ1 asks what storage representation and retrieval strategy contribute, and whether the two factors interact. Its main analysis contains **six core effects** and **two descriptive complete-system anchors**. Every contrast is evaluated separately within Qwen and DeepSeek. This produces 12 model-specific core results and four model-specific descriptive results, for 16 main-text result units in total. These units organise paired estimation and reporting; they are not 16 independent confirmatory hypothesis tests.

| Analysis block | Contrast | Status | Identifiable question |
|---|---|---|---|
| Raw storage organisation under R1 | E3−E1 | Core | Does changing S1 flat raw sessions to S2 foldered raw sessions help R1? |
| Raw storage organisation under R2 | E4−E2 | Core | Does the same storage change help R2? |
| Retrieval system on S1 | E2−E1 | Core | Does R2 outperform R1 when the S1 store is fixed? |
| Retrieval system on S2 | E4−E3 | Core | Does R2 outperform R1 when the S2 store is fixed? |
| Storage–retrieval interaction | `(E4−E2)−(E3−E1)` | Core | Does folder organisation affect R1 and R2 differently? |
| Curated-memory access method | E6−E5 | Core | Does representation-adapted R3 improve access to the same frozen S3 store relative to R1? |
| Curated versus foldered raw under R1 | E5−E3 | Descriptive anchor | How does the deployed S3+R1 system compare with S2+R1? |
| Curated adapted system versus foldered raw system | E6−E4 | Descriptive anchor | How does the deployed S3+R3 system compare with S2+R2? |

E5−E1 and E6−E2 are retained as sensitivity anchors in the appendix. They should not crowd the main RQ1 narrative. E5−E3, E6−E4, E5−E1, and E6−E2 are complete-system comparisons: they do not isolate curation, summarisation, file organisation, provenance formatting, or retrieval adaptation as a single causal factor.

RQ1 places the Qwen and DeepSeek estimates side by side but does not yet calculate or interpret formal cross-backbone stability. Effect-sign agreement, contrast-of-contrasts, and claims about model dependence belong to RQ2 in Section 5.3. E7, Full Context, the global failure-stage distribution, and final quality–cost selection likewise remain in RQ3–RQ6.

**Shared RQ1 calculation contract**

Apply the following calculation contract consistently to the six core effects. Use the same fields for the two descriptive anchors where the comparison is meaningful.

1. **Condition summaries, `N=60`:** report Precision, Recall, token F1, Strict Accuracy, Partial Rate, and Soft Semantic Score. Treat F1, Strict Accuracy, and Soft Semantic Score as the main paired outcomes. Use Precision and Recall to explain answer breadth, omission, and verbosity. Do not orient Partial Rate as unconditionally better or worse; interpret it through the full judge-label transitions.
2. **Question-paired effects, `N=60`:** compute the target-minus-baseline difference per `question_id`, then report the mean, median, unrounded win/tie/loss counts, and the paired-difference distribution. For Strict outcomes, report not-correct→correct, correct→not-correct, unchanged-correct, and unchanged-not-correct counts, where `not-correct` combines the `partial` and `incorrect` Judge labels. Use a `correct`/`partial`/`incorrect` 3×3 transition matrix when Partial Rate needs explanation.
3. **Evidence outcomes, eligible `N=58`:** report Evidence Recall, Any-hit, All-hit, relevant multi-source coverage, and EvidenceBundle length. Never mix the 58-question evidence denominator with the 60-question answer denominator.
4. **Evidence-to-answer conversion:** cross evidence change with answer change. At minimum distinguish evidence improvement with answer improvement, evidence improvement without answer improvement, unchanged evidence with answer improvement, and evidence decline without corresponding answer harm. A full up/same/down matrix may be retained in the analysis artifact.
5. **Process evidence:** report calls, tokens, latency, failed attempts, and relevant search depth only where they explain an architectural effect. Keep R1 rounds and R2/R3 actions as different units. Final cost ranking and Pareto analysis belong to RQ6.
6. **Auxiliary uncertainty:** apply the paired-bootstrap procedure from Chapter 4 only to E3−E1, E4−E2, E2−E1, E4−E3, and the storage–retrieval interaction. The main text should prioritise F1 and Strict intervals; Soft intervals may be placed in the supplementary output. Bootstrap results support, rather than organise, the argument.
7. **Category mechanism analysis:** repeat the six core contrasts descriptively for C1–C4, concentrating on F1, Strict Accuracy, and Evidence Recall. Report direction and magnitude rather than separate category-level significance claims. Treat C3 especially cautiously because it contains only seven questions, of which five are evidence-eligible.
8. **Bounded trace review:** for each of the four analysis modules below, inspect at least one repair case, one harm case, and one counterexample or metric-disagreement case. Use the trace to explain the paired result; reserve the full stage-level error census for RQ5.

**Recommended staged computation workflow**

Use one frozen master analysis table and one reproducible analysis program, but execute and validate RQ1 in logical stages rather than producing one opaque output dump or writing a separate ad hoc script for every contrast:

1. **Stage A — master-table and denominator audit:** join all answer, judge, evidence, category, and process records by backbone, condition, and `question_id`; verify 60 answer rows per condition, the 58-question evidence-eligibility mask, uniqueness, missingness, score ranges, and condition identities.
2. **Stage B — E1–E4 raw 2×2 core:** calculate E3−E1, E4−E2, E2−E1, E4−E3, and the interaction together. Validate the algebraic equivalence of the two interaction forms and generate the selected bootstrap intervals only after the paired tables pass audit.
3. **Stage C — S3 and complete-system anchors:** calculate E6−E5, E5−E3, and E6−E4; generate E5−E1 and E6−E2 only as sensitivity outputs. Keep causal and complete-system labels separate in every table.
4. **Stage D — mechanism analyses:** generate evidence-to-answer conversion tables, category matrices, process summaries, and the bounded trace-review candidate lists from the already validated paired outputs.
5. **Stage E — final RQ1 audit:** reconcile every displayed number with the master table, check metric directions and denominators, freeze machine-readable tables and figure inputs, and only then draft the RQ1 prose.

This staged design calculates shared quantities once, prevents denominator or sign drift across contrasts, and makes failures easy to locate without fragmenting the analysis into incompatible scripts.

**Stage A execution record — completed and audited**

Stage A has been implemented as the read-only protocol `chapter5-main60-stage-a-v1`. It does not modify any formal run, call an API, calculate a paired condition effect, rank systems, or draw an RQ1 conclusion. The frozen outputs are stored under `artifacts/chapter5-main60-analysis-v1/stage-a/` and contain three explicitly nested scopes:

- `master-table.*`: 900 rows, comprising Qwen E1–E7 (420), DeepSeek E1–E7 (420), and DeepSeek-family Full Context (60);
- `e1-e7-main.*`: the symmetric 840-row E1–E7 view used across later selective-retrieval analyses;
- `rq1-analysis-view.*`: the 720-row E1–E6 view used for the six RQ1 core effects and the two descriptive system anchors. E7 and Full Context are excluded from this RQ1 input by construction.

The builder joins records only by explicit answer-set, condition, and `question_id` identities. It preserves the physical source partition only for provenance; the analytical question set is always the unified Main-60. It recomputes category-aware token Precision, Recall, and F1 for all 900 answers with one evaluator, verifies every E1–E7 F1 value and every Full Context F1 value against the stored run evaluation, and then removes all question, reference-answer, candidate-answer, evidence-text, and Judge-rationale fields from the published tables.

The Stage A audit verifies, among other checks:

- one set of 60 questions for every answer path and the fixed C1–C4 counts of 13/13/7/27;
- 60 answer rows per condition and one identical 58-question Evidence eligibility mask for every E1–E7 path;
- null Evidence Recall, Any-hit, and All-hit for Full Context, while retaining source coverage as a separate by-construction field;
- exact Qwen, DeepSeek, DeepSeek-family Full Context, and independent Judge identities recorded by the source runs;
- the 16,000-character E1–E6 limit, 32,000-character E7 fused limit, and E7 reuse of two parent bundles without a new search action;
- exact semantic label mappings, score ranges, token and call addition, source-record identities and hashes, completion gates, batch markers, and recorded failure-attempt counts;
- native per-answer latency as unavailable for E1–E7 rather than inferred from event timestamps, while preserving the native Full Context latency field;
- byte hashes for every materialised table, schema, source manifest, and the final `STAGE-A.PASSED` marker.

`audit.json` and `STAGE-A.PASSED` are the gate for Stage B. Any later computation must read the frozen RQ1 view and verify the audit before calculating a contrast.

**Stage B execution protocol — E1–E4 raw 2×2 core**

Stage B is the controlled raw-memory component analysis, not the whole of RQ1. It uses the four E1–E4 cells below to estimate storage-organisation effects, retrieval-system effects, and their interaction while the underlying dialogue content remains raw:

| Raw-memory representation | R1: Agentic Filesystem Retrieval | R2: ReFind-Style Retrieval |
|---|---|---|
| S1: flat raw sessions | E1 | E2 |
| S2: foldered raw sessions | E3 | E4 |

The stage reads the frozen `rq1-analysis-view` only after verifying the Stage A audit ID, `STAGE-A.PASSED`, source-manifest identity, and materialised-table hashes. It then filters to E1–E4. The exact input is 480 rows: two backbone models × four conditions × the same ordered Main-60 questions. Answer outcomes use `N=60` per condition. Evidence outcomes use the identical 58-question eligibility mask per condition. The physical source partition remains provenance only and is never analysed as an old/new split.

Stage B estimates the following five effects separately within Qwen and DeepSeek, yielding ten model-specific effect units:

1. **Storage organisation under R1, E3−E1:** the S1-to-S2 change with R1 fixed.
2. **Storage organisation under R2, E4−E2:** the same S1-to-S2 change with R2 fixed.
3. **Retrieval system on S1, E2−E1:** the R1-to-R2 change with S1 fixed.
4. **Retrieval system on S2, E4−E3:** the R1-to-R2 change with S2 fixed.
5. **Storage–retrieval interaction:** `(E4−E2)−(E3−E1)`, calculated per question and checked against the algebraically equivalent form `(E4−E3)−(E2−E1)`.

For a higher-is-better metric, a positive oriented interaction means that changing from S1 to S2 is more favourable under R2 than under R1. A negative value means that the foldered representation is more favourable to R1, or that it reduces R2's advantage. The interaction must always be displayed beside its four component contrasts so that its sign is interpretable.

Stage B should run as one reproducible program invocation, but the program must enforce the following internal gates in order. Failure at any gate stops the run and prevents publication of `STAGE-B.PASSED`.

1. **B0 — Stage A gate and input identity**
   - verify the Stage A audit, marker, hashes, schema, and source-manifest identity;
   - materialise exactly 480 E1–E4 rows from the frozen RQ1 view;
   - verify two backbones, four conditions, 60 unique questions per cell, the fixed C1–C4 counts, and the shared 58-question Evidence mask;
   - reject duplicate keys, missing condition records, unexpected model identities, out-of-range scores, or any denominator drift.
2. **B1 — E1–E4 condition summaries**
   - for each backbone and condition, report Precision, Recall, token F1, Strict Accuracy, Partial Rate, and Soft Semantic Score on `N=60`;
   - report Evidence Recall, Any-hit, All-hit, available multi-source coverage, and EvidenceBundle length on eligible `N=58` only;
   - reproduce the corresponding Stage A condition means exactly before any effect is estimated.
3. **B2 — four question-paired simple effects**
   - join target and baseline by backbone and `question_id`;
   - preserve the fixed target-minus-baseline directions listed above;
   - for each metric, store all question-level differences and report the target and baseline means, mean paired difference, median paired difference, unrounded win/tie/loss counts, and the complete paired-difference distribution;
   - treat F1, Strict Accuracy, and Soft Semantic Score as the primary answer outcomes; use Precision and Recall to explain omission, coverage, and verbosity rather than as isolated winners;
   - do not orient Partial Rate as unconditionally higher-is-better.
4. **B3 — semantic-label transitions**
   - for Strict outcomes, report not-correct→correct, correct→not-correct, unchanged-correct, and unchanged-not-correct counts, totalling 60; `not-correct` includes both `partial` and `incorrect` Judge labels;
   - where Partial Rate requires interpretation, generate the complete `correct`/`partial`/`incorrect` 3×3 transition matrix;
   - retain repair and harm question identifiers for the bounded trace-review stage without copying question or answer text into the Stage B tables.
5. **B4 — Evidence-paired outcomes**
   - calculate paired changes in Evidence Recall, Any-hit, All-hit, relevant multi-source coverage, and EvidenceBundle length on the eligible 58-question set;
   - verify that every Evidence win/tie/loss total equals 58 and never merge these values with the 60-question answer denominator;
   - retain the paired Evidence deltas needed by Stage D, but defer the Evidence-change × answer-change mechanism tables to Stage D.
6. **B5 — question-level interaction**
   - calculate raw and direction-oriented DID values for F1, Strict, Soft, and Evidence Recall, with supplementary machine-readable values for other valid metrics;
   - verify both DID formulae for every question within a fixed numerical tolerance and again after aggregation;
   - report component contrasts beside the interaction and generate the data required by the 2×2 interaction plot.
7. **B6 — selected paired-bootstrap intervals**
   - run only after B0–B5 pass;
   - resample `question_id` values as complete matched E1–E4 blocks, so all four condition values for one sampled question move together;
   - use 10,000 replicates, fixed seed `20261021`, no missing-value imputation, and the 2.5th/97.5th percentile interval;
   - apply the procedure only to E3−E1, E4−E2, E2−E1, E4−E3, and the interaction;
   - prioritise F1 and Strict intervals in the main result, retain Soft intervals as supplementary output, and describe all intervals only as resampling stability across the observed Main-60 questions—not across conversations.
8. **B7 — final Stage B audit and atomic publication**
   - recompute every aggregate from the question-level tables and reconcile all condition means with Stage A;
   - verify that answer win/tie/loss and Strict transitions total 60, Evidence results total 58, metric directions are fixed, DID identities agree, bootstrap settings match the frozen protocol, and no text-bearing source fields appear in the outputs;
   - hash every published artifact and write `STAGE-B.PASSED` only after all checks pass; a failed run may leave diagnostic files in a temporary directory but must not publish a partial formal Stage B result.

The formal Stage B artifact should contain, at minimum: E1–E4 condition summaries; a question-level paired-difference table; aggregate simple-effect and interaction tables; win/tie/loss counts; Strict and optional 3×3 semantic transition tables; eligible-question Evidence effects; selected bootstrap intervals; plot-ready data for the storage comparisons and Figure 5.1; a source manifest; an audit report; and the final passed marker. All tables should be machine-readable, with concise human-readable documentation.

Stage B deliberately stops at the validated raw 2×2 effects. E6−E5 and the E5−E3/E6−E4 complete-system anchors belong to Stage C. Category matrices, Evidence-to-answer conversion, process summaries, and trace-review candidate interpretation belong to Stage D. Formal cross-backbone contrast-of-contrasts belongs to RQ2. E7, Full Context, the global error census, Pareto analysis, system recommendation, and the final RQ1 prose are outside Stage B. Stage B may preserve the identifiers and fields needed by these later stages, but it must not pre-empt their conclusions.

**Formal Stage B execution record (21 October 2026).** The frozen program completed all B0–B7 gates and published the formal artifact at `artifacts/chapter5-main60-analysis-v1/stage-b`. The run consumed exactly 480 frozen Stage A rows and produced ten within-backbone effect units. Its machine-readable outputs contain 104 E1–E4 condition summaries, 5,192 question-level paired metric rows, 104 aggregate simple-effect rows, 32 Strict transition rows, 72 complete semantic-transition rows, 1,298 question-level interaction rows, 26 interaction aggregates, 30 selected bootstrap intervals, and 32 plot-ready Figure 5.1 rows. The bootstrap used 10,000 complete-question-block resamples with seed `20261021`, Type-7 2.5th/97.5th percentiles, and no imputation. The independently recomputed audit and tamper-rejection tests passed under audit ID `stage-b-audit-2c5061c3db5cba00f099648963eaa2175d1136954e4cf673720423e7ffed6932`. No API call was made, no formal source was modified, and no Stage C, Stage D, cross-backbone, E7, Full Context, error-census, Pareto, recommendation, or final RQ1 interpretation was computed.

**Provisional Stage B findings — recorded for later RQ1 synthesis, not final report prose.** These findings apply only to the E1–E4 raw-memory 2×2 core and should be revised only through the later audited stages, not by selectively replacing individual values.

| Backbone | Fixed component | Paired contrast | ΔF1 | ΔStrict | ΔSoft |
|---|---|---|---:|---:|---:|
| Qwen | R1 | E3−E1 | +0.0462 | +0.0333 | +0.0250 |
| Qwen | R2 | E4−E2 | −0.0071 | +0.0333 | +0.0083 |
| Qwen | S1 | E2−E1 | +0.0082 | −0.0500 | −0.0500 |
| Qwen | S2 | E4−E3 | −0.0451 | −0.0500 | −0.0667 |
| DeepSeek | R1 | E3−E1 | −0.0041 | −0.0500 | −0.0500 |
| DeepSeek | R2 | E4−E2 | −0.0141 | −0.0333 | 0.0000 |
| DeepSeek | S1 | E2−E1 | −0.0557 | −0.0500 | −0.1000 |
| DeepSeek | S2 | E4−E3 | −0.0657 | −0.0333 | −0.0500 |

The provisional interpretation is as follows:

1. **Folder organisation is not a backbone-invariant improvement.** S2 has a positive descriptive effect under Qwen with R1, but that direction is not reproduced under DeepSeek. Every storage-effect bootstrap interval includes or touches zero, so Stage B does not establish that S2 generally outperforms S1.
2. **R2 shows a broadly negative answer-quality pattern relative to R1.** Strict and Soft decrease in both storage conditions under both backbones; F1 decreases in three of the four comparisons. The only intervals among the 30 selected Stage B intervals that strictly exclude zero are DeepSeek E2−E1 for F1 (`−0.0557`, 95% bootstrap interval `[−0.1189, −0.0002]`) and Soft (`−0.1000`, interval `[−0.2000, −0.0083]`). The F1 upper bound is very close to zero and should be described cautiously.
3. **More selected text does not imply better gold-evidence access.** Relative to R1, R2 adds approximately 3,886–7,142 EvidenceBundle characters across the four backbone/storage comparisons, yet Evidence Recall declines by approximately 0.033–0.080 and Any-hit and All-hit also decline in every comparison. This is a consistent descriptive association, not yet a causal explanation; question-level evidence-to-answer conversion remains a Stage D task.
4. **No reliable storage–retrieval interaction is established.** All six F1, Strict, and Soft interaction intervals include zero. Qwen shows a negative F1 interaction trend (`−0.0533`), whereas DeepSeek is closer to zero (`−0.0100`), but neither supports a stable interaction claim.
5. **Metric disagreement justifies the multi-metric evaluation.** For Qwen E2−E1, token F1 rises slightly (`+0.0082`) while Strict and Soft both decline (`−0.0500`). Token overlap therefore cannot be treated as a sufficient proxy for semantic correctness.
6. **The descriptive best E1–E4 condition changes with the backbone.** E3 is highest for Qwen on the main answer metrics, whereas E1 is highest for DeepSeek. Stage B reports these within-backbone patterns only; formal effect-sign stability and cross-backbone contrast-of-contrasts remain RQ2 tasks.

The bounded Stage B conclusion is therefore: directory organisation may help a filesystem agent under some backbone settings, while R2 exhibits a consistent pattern of much larger evidence bundles, lower annotated-evidence coverage, and weaker semantic outcomes. Only the DeepSeek/S1 F1 and Soft declines currently receive non-zero paired-bootstrap support. Stage B alone does not justify a universal storage winner, a confirmed interaction, a causal evidence-dilution claim, or a final system recommendation.

**Formal Stage C execution record (22 October 2026).** The frozen program completed the Stage C lineage, denominator, pairing, transition, and publication gates and atomically published the formal artifact at `artifacts/chapter5-main60-analysis-v1/stage-c`. The computation read the complete 720-row Stage A RQ1 view directly; the formal Stage B artifact was used only as a lineage gate and as an exact E1–E4 condition-summary consistency check. It produced ten within-backbone effect units from five fixed contrasts: E6−E5, E5−E3, E6−E4, E5−E1, and E6−E2. The machine-readable outputs contain five registered contrasts, 52 E5/E6 condition summaries, 6,490 question-level paired metric rows, 130 aggregate-effect rows, 40 Strict transition rows, 90 complete semantic-transition rows, 24 main-text table rows, and 16 appendix sensitivity rows. The published artifact passed independent byte reconstruction, numeric-anchor, transition-folding, and tamper-rejection tests under audit ID `stage-c-audit-a199de52d8b0011d837334e6dbf37bbfac446653753b5b74a35732ae32da1a31`. No API call was made, and Stage C did not compute bootstrap intervals, interactions, category effects, Evidence-to-answer conversion, process or cost analysis, trace review, cross-backbone effects, E7, Full Context, Stage D, or a final RQ1 conclusion. The complete durable process-and-results note is stored in `docs/analysis/chapter5-stage-c-process-and-results.md`.

**Provisional Stage C findings — recorded for later RQ1 synthesis, not final report prose.** All differences below are target minus baseline and are descriptive within each backbone. E5−E3 and E6−E4 remain complete-system anchors rather than estimates of a pure curation effect.

| Backbone | Comparison | Interpretation status | ΔF1 | ΔStrict | ΔSoft | ΔEvidence Recall | ΔBundle characters |
|---|---|---|---:|---:|---:|---:|---:|
| Qwen | E6−E5 | Core S3 access-system effect | −0.0135 | −0.0500 | −0.0583 | −0.0891 | +5,109.1 |
| Qwen | E5−E3 | Descriptive R1 complete-system anchor | −0.0463 | +0.0333 | +0.0250 | +0.1034 | +3,034.0 |
| Qwen | E6−E4 | Descriptive adapted-system anchor | −0.0147 | +0.0333 | +0.0333 | +0.0560 | +4,257.6 |
| DeepSeek | E6−E5 | Core S3 access-system effect | −0.0364 | −0.0833 | −0.0917 | −0.2371 | +5,457.3 |
| DeepSeek | E5−E3 | Descriptive R1 complete-system anchor | −0.0367 | +0.0500 | +0.0417 | +0.1149 | +3,901.2 |
| DeepSeek | E6−E4 | Descriptive adapted-system anchor | −0.0074 | 0.0000 | 0.0000 | −0.0431 | +2,679.6 |

The bounded interpretation is as follows:

1. **R3 does not improve access to the frozen S3 store in this experiment.** Relative to E5, E6 lowers F1, Strict Accuracy, Soft Semantic Score, and Evidence Recall for both Qwen and DeepSeek while adding roughly 5.1–5.5 thousand EvidenceBundle characters. The question-level Strict transitions also show more harms than repairs: Qwen records two not-correct→correct repairs and five correct→not-correct harms; DeepSeek records two repairs and seven harms.
2. **The S3+R1 complete system shows a token–semantic metric disagreement.** Relative to E3, E5 lowers token F1 under both backbones but raises Strict Accuracy, Soft Semantic Score, and Evidence Recall. This pattern is consistent with the need to keep lexical overlap and semantic correctness separate; it does not by itself establish that curation caused the improvement because S2→S3 changes several representation properties together.
3. **The S3+R3 versus S2+R2 anchor is backbone-dependent descriptively.** Under Qwen, E6 raises Strict, Soft, and Evidence Recall despite a small F1 decrease. Under DeepSeek, Strict and Soft are unchanged, Evidence Recall declines, and F1 falls slightly. Formal sign stability and cross-backbone contrast-of-contrasts remain RQ2 tasks.
4. **The appendix sensitivity anchors do not overturn the main pattern.** Against E1/E2, Qwen's S3 conditions improve Strict and Soft while F1 remains nearly unchanged or decreases. DeepSeek's sensitivity comparisons show no semantic gain and lower F1. These comparisons remain descriptive complete-system checks, not isolated representation effects.
5. **Larger S3 bundles are not sufficient for better access or answers.** Every Stage C contrast increases mean EvidenceBundle length, yet E6−E5 worsens both annotated-evidence coverage and semantic answer quality. Explaining whether this reflects ranking, packaging, noise, or Answerer utilisation requires Stage D Evidence-to-answer tables and bounded trace review.

The bounded Stage C conclusion is therefore: Agent-Curated Memory with R1 improves semantic correctness and annotated-evidence coverage relative to the foldered raw R1 system despite lower token F1, whereas the representation-adapted R3 access path is consistently worse than R1 on the same S3 store. Complete-system comparisons involving E6 vary by backbone and cannot be reduced to a pure curation or retrieval-component effect. These are descriptive Stage C findings only; no final RQ1, cross-backbone, mechanism, or system-selection claim is made here.

**Formal Stage D launch record (22 October 2026).** Stage D has entered formal execution under the frozen protocol in `docs/analysis/chapter5-stage-d-protocol.md`. It is split into an audited automatic phase and a bounded trace-review phase. The automatic phase generates Evidence-to-answer conversion matrices, C1--C4 category effects, process summaries, and a deterministic identifier-only candidate register from the already validated Stage A--C artifacts. It may write `STAGE-D-AUTO.PASSED` only after independent reconstruction and denominator checks. The final `STAGE-D.PASSED` marker is reserved until every frozen trace candidate has completed the pre-declared review sequence. This stage makes no API call and excludes cross-backbone inference, E7, Full Context, the global error census, Pareto analysis, final system recommendation, and final RQ1 prose.

**Formal Stage D completion record (22 October 2026).** Both Stage D gates are complete. The automatic phase published 20 comparison-register rows, 812 Evidence-to-answer question rows, 756 conversion-matrix rows, 84 conversion summaries, 224 category-effect rows, 32 category-interaction rows, 64 appendix-sensitivity category rows, 312 process-condition summaries, 468 process-paired summaries, and 24 frozen identifier-only review candidates. The bounded phase reviewed exactly those 24 candidates: four RQ1 modules × two backbones × repair/harm/counterexample, with no substitutions. The final artifact is stored at `artifacts/chapter5-main60-analysis-v1/stage-d`, preserves every automatic file byte-for-byte, and carries final audit ID `stage-d-final-audit-9f23da2369af468867b7f6ffdbdc040ebee67fac59820d59f0763a3ccd132640`. All 40 Stage A--D regression and tamper-rejection tests passed. The durable process-and-results record is `docs/analysis/chapter5-stage-d-process-and-results.md`. Stage D made no API call and still makes no formal cross-backbone, E7, Full Context, global error-census, Pareto, recommendation, or final RQ1 claim. Stage E is the next RQ1 gate.

**Formal Stage E completion record (22 October 2026).** The final RQ1 gate verified the frozen Stage A--D lineage, reconciled all 16 main-text result units, preserved the existing 30-row bootstrap set, and atomically published `artifacts/chapter5-main60-analysis-v1/stage-e-rq1`. Its 1,470-row display-number register binds the final report values to the audited machine rows. The artifact also freezes complete condition and paired-effect summaries, semantic and Strict transitions, Evidence-to-answer matrices, category and process inputs, Figure 5.1, and the legacy single-table curated-memory inputs now presented as Tables 5.9--5.10, the one-time S3 construction record, and the 24 bounded trace records. The final audit ID is `stage-e-rq1-audit-eb62d71e3b89fd63833853e6a21ad306bdb637f4b8140bc57dc1fdbf572ecb24`; `STAGE-E-RQ1.PASSED` is present. The final English Section 5.2 is stored in `docs/report/chapter-5-rq1-architecture-effects.md`, and the durable execution record is `docs/analysis/chapter5-stage-e-process-and-results.md`. Stage E made no API call, changed no formal source, added no bootstrap, and did not perform RQ2--RQ6 analyses.

### 5.2.1 Effect of Storage Organisation under Each Retrieval System

**Research question**

Does changing from flat raw sessions to foldered raw sessions improve performance, and does the effect depend on the retrieval system?

**Core comparisons**

- E3−E1 under R1;
- E4−E2 under R2;
- each contrast reported separately for Qwen and DeepSeek.

**Required analysis**

1. Report the two condition means and the paired mean and median difference for F1, Strict Accuracy, and Soft Semantic Score.
2. Report metric-oriented win/tie/loss counts.
3. Use selected paired confidence intervals as supporting evidence for these central contrasts.
4. Link answer changes to Evidence Recall, Any-hit, and All-hit changes.
5. Separate cases where evidence and answer quality move together from cases where improved evidence does not improve the answer.
6. Inspect representative traces to determine whether folders aided navigation, later agent decisions, or neither.

**Mechanism table**

Cross evidence change with answer change:

- evidence improves and answer improves;
- evidence improves but answer does not;
- evidence is unchanged but answer improves;
- evidence declines but the answer remains correct or improves.

The last two groups are important counterexamples because they expose alternative evidence, utilisation differences, or limitations in gold evidence annotations.

**Required output**

- **Table 5.3:** storage-organisation effects on primary answer quality;
- **Table 5.4:** storage-organisation lexical and evidence diagnostics;
- paired-effect plot for E3−E1 and E4−E2 under both backbone models;
- evidence-change × answer-change results, consolidated later in Table 5.11;
- one bounded conclusion stating under which retriever and backbone directory organisation helped.

**Interpretation boundary**

Do not claim that directories are universally beneficial. The observed effect is conditional on the retrieval system, backbone model, and current conversation.

### 5.2.2 Effect of the Retrieval System under Each Raw Storage Representation

**Research question**

How does the complete R2 retrieval system compare with R1 when the underlying raw content is held fixed?

**Core comparisons**

- E2−E1 on S1;
- E4−E3 on S2;
- each contrast under both backbone models.

**Required analysis**

- paired F1, Strict, and Soft differences;
- Precision and Recall to explain answer breadth and concision;
- Evidence Recall, Any-hit, All-hit, and multi-source coverage;
- calls, tokens, latency, rounds or actions, and failures, while keeping R1 rounds and R2 actions as distinct units;
- retrieval-repair and retrieval-harm counts;
- trace review covering query formulation, result ranking, local expansion, accepted evidence, and final packaging.

**Questions to answer**

- Does R2 retrieve more complete evidence, or merely more evidence?
- Does S2 make R1 navigation more competitive with content ranking?
- Are quality gains large enough to justify extra model calls or tokens?

**Required output**

- **Table 5.5:** retrieval-system effects on primary answer quality;
- **Table 5.6:** retrieval-system lexical, evidence, and query-cost diagnostics;
- one repair case and one harm case.

**Interpretation boundary**

This is a comparison of two complete retrieval systems. It cannot be reduced to the isolated effect of BM25, one query term, or one agent action.

### 5.2.3 Storage–Retrieval Interaction and Question-Category Heterogeneity

**Research question**

Does storage organisation affect R1 and R2 differently, and are any differences concentrated in particular question categories?

**Required analysis**

- apply the difference-in-differences estimator defined in Section 4.3.2;
- report the component contrasts beside the interaction so the sign remains interpretable;
- evaluate F1, Strict, Soft, and Evidence Recall;
- use paired bootstrap intervals only as auxiliary evidence for the principal interactions;
- describe C1–C4 patterns for the component contrasts and interaction;
- connect category patterns to evidence requirements: multi-source composition, temporal detail, open-domain information, or local fact lookup.

**Questions to answer**

- Does folder structure add more value to filesystem navigation than to ranked retrieval?
- Does R2 substitute for directory organisation or complement it?
- Are apparent gains concentrated in C1 or C2 rather than shared across Main-60?

**Required output**

- **Figure 5.1:** 2×2 storage–retrieval interaction plot;
- **Table 5.7:** E1–E4 descriptive condition means underlying Figure 5.1;
- **Table 5.8:** storage–retrieval interaction estimates containing raw and oriented effects;
- compact category matrix showing direction, magnitude, and evidence strength.

**Interpretation boundary**

C1–C4 analyses are exploratory. C3 contains only seven questions, so category patterns should support mechanism interpretation rather than independent general claims.

### 5.2.4 Complete-System Effect of Agent-Curated Memory

**Research question**

When is Agent-Curated Memory useful as a complete system, and when does curation lose information or create new errors?

**Core comparisons**

- E6−E5 to compare two access methods on the same S3 store;
- E5−E3 as the principal R1 complete-system anchor;
- E6−E4 as the principal representation-adapted complete-system anchor;
- E5−E1 and E6−E2 as appendix sensitivity anchors.

**Required analysis**

- answer quality and evidence coverage;
- selected evidence and Answerer input length;
- one-time S3 construction cost and query-time cost;
- S3 fidelity review against the source conversation;
- cases of successful consolidation, omitted qualifiers, temporal distortion, and entity confusion;
- whether R3 improves access enough to compensate for its added complexity.

**Required output**

- **Table 5.9:** curated-memory effects on primary answer quality;
- **Table 5.10:** curated-memory lexical, evidence, and bundle diagnostics;
- **Figure 5.2:** Agent-Curated Memory architecture-effect profile;
- **Table 5.11:** selected Evidence Recall change × Strict change diagnostic cells across the RQ1 contrasts;
- **Table 5.12:** architecture evidence matrix summarising every conclusion from Section 5.2;
- an adjacent one-time S3 construction record and a bounded fidelity discussion, kept separate from the paired effect table and from the RQ6 cost ranking;
- three to four source-to-S3 cases covering repair, harm, and at least one counterexample or metric disagreement.

**Interpretation boundary**

Raw-versus-curated comparisons are complete-system comparisons. They cannot isolate summarisation, file organisation, provenance formatting, or R3 as independent causal components.

---

## 5.3 RQ2: Robustness across Backbone Models

RQ2 is a compact robustness check on the architectural findings established in Section 5.2. It is not a second mechanism, cost, or error-analysis chapter. Detailed fusion analysis belongs to RQ3, Full Context to RQ4, mechanism and error review to RQ5, and resource comparison to RQ6.

**Formal RQ2 completion record (24 October 2026).** The offline RQ2 program consumed only the frozen Stage A and Stage E-RQ1 artifacts. It verified the 840 symmetric E1--E7 rows, the exact Qwen and DeepSeek model identities, the shared GLM judge identity, and the Stage E architecture-effect lineage. It then atomically published `artifacts/chapter5-main60-analysis-v1/rq2-backbone-robustness`. The passed audit ID is `rq2-audit-ef0e571affac75cd8b6ad71d833411e7a41c10664132770f77d86712827ab00b`. No API or network call was made, no formal result was changed, and no new bootstrap or significance test was introduced. The durable calculation record is `docs/analysis/chapter5-rq2-process-and-results.md`.

### 5.3.1 Matched Backbone Performance and the Token-F1 Gap

**Purpose**

Describe whether the end-to-end Qwen and DeepSeek pipelines give the same overall performance picture under the same E1–E7 conditions.

**Completed calculation**

For backbone (b), condition (e), metric (m), and the fixed 60-question set, calculate the condition mean:

```text
condition_mean(b, e, m) = sum_i metric(i, b, e, m) / 60
```

Then calculate the descriptive same-condition backbone difference:

```text
condition_backbone_delta(e, m)
    = condition_mean(DeepSeek, e, m)
    - condition_mean(Qwen, e, m)
```

The same 60 question identities and hashes are present in both pipelines for every condition. The differences are descriptive point estimates; the seven repeated condition paths are not treated as 420 independent questions.

**Audited primary results**

All scores are on the 0--1 scale. Each cell is `Qwen / DeepSeek / (DeepSeek−Qwen)`.

| Condition | Token F1 | Strict Accuracy | Soft Semantic Score |
|---|---:|---:|---:|
| E1 | 0.3949 / 0.3013 / −0.0936 | 0.7167 / 0.7500 / +0.0333 | 0.7667 / 0.8083 / +0.0417 |
| E2 | 0.4031 / 0.2455 / −0.1576 | 0.6667 / 0.7000 / +0.0333 | 0.7167 / 0.7083 / −0.0083 |
| E3 | 0.4411 / 0.2971 / −0.1440 | 0.7500 / 0.7000 / −0.0500 | 0.7917 / 0.7583 / −0.0333 |
| E4 | 0.3960 / 0.2314 / −0.1646 | 0.7000 / 0.6667 / −0.0333 | 0.7250 / 0.7083 / −0.0167 |
| E5 | 0.3948 / 0.2604 / −0.1344 | 0.7833 / 0.7500 / −0.0333 | 0.8167 / 0.8000 / −0.0167 |
| E6 | 0.3813 / 0.2240 / −0.1573 | 0.7333 / 0.6667 / −0.0667 | 0.7583 / 0.7083 / −0.0500 |
| E7 | 0.3691 / 0.2854 / −0.0837 | 0.7333 / 0.7500 / +0.0167 | 0.7583 / 0.8000 / +0.0417 |

**Audited lexical explanation**

Normalised answer length is measured in the same offline scoring tokens used by the Stage A evaluator. Each cell is again `Qwen / DeepSeek / (DeepSeek−Qwen)`.

| Condition | Token Precision | Token Recall | Normalised answer tokens |
|---|---:|---:|---:|
| E1 | 0.3381 / 0.2345 / −0.1036 | 0.6565 / 0.7003 / +0.0438 | 13.28 / 20.22 / +6.93 |
| E2 | 0.3606 / 0.1720 / −0.1886 | 0.6411 / 0.7023 / +0.0612 | 12.63 / 24.92 / +12.28 |
| E3 | 0.3759 / 0.2315 / −0.1444 | 0.7091 / 0.6824 / −0.0268 | 11.97 / 21.72 / +9.75 |
| E4 | 0.3413 / 0.1630 / −0.1783 | 0.6542 / 0.6504 / −0.0038 | 13.25 / 25.63 / +12.38 |
| E5 | 0.3324 / 0.1930 / −0.1393 | 0.7472 / 0.7389 / −0.0082 | 16.13 / 29.17 / +13.03 |
| E6 | 0.3209 / 0.1630 / −0.1579 | 0.6736 / 0.6084 / −0.0652 | 14.82 / 30.93 / +16.12 |
| E7 | 0.3181 / 0.2128 / −0.1053 | 0.6605 / 0.7364 / +0.0759 | 16.13 / 24.87 / +8.73 |

**Findings to express in the final prose**

1. **The lexical backbone gap is uniform.** Qwen has higher Token F1 in all seven conditions. The DeepSeek−Qwen gap ranges from −0.0837 in E7 to −0.1646 in E4. The equal-weight descriptive means across E1--E7 are 0.3972 versus 0.2636, a difference of −0.1336. This average summarises repeated condition paths and is not an independent-sample estimate.
2. **The semantic gap is much smaller and changes direction.** DeepSeek has higher Strict Accuracy in E1, E2, and E7, whereas Qwen is higher in E3--E6. DeepSeek has higher Soft Semantic Score in E1 and E7 only. The equal-weight descriptive Strict and Soft differences are −0.0143 and −0.0060, respectively, far smaller than the F1 difference.
3. **The main observable structure behind DeepSeek's lower F1 is longer output and systematically lower Precision.** DeepSeek answers are longer in all seven conditions and have lower Precision in all seven. Across E1--E7, the descriptive mean answer length is 25.35 versus 14.03 normalised tokens, an increase of about 80.7%, while mean Precision is 0.1957 versus 0.3411, a relative reduction of about 42.6%. Token Precision divides matched answer tokens by all candidate-answer tokens. Extra explanations, qualifiers, and paraphrastic wording therefore increase the denominator even when the required fact is present. Because F1 is the harmonic mean of Precision and Recall, the small overall Recall advantage for DeepSeek cannot offset the much larger Precision deficit. This is the principal measured explanation for the aggregate F1 gap, although it remains an observed association rather than an isolated causal effect.
4. **The condition-level pattern separates a lexical-style penalty from broader quality loss.** DeepSeek Recall is higher in E1, E2, and E7, the same three conditions in which its Strict Accuracy is higher. In these conditions, lower F1 can coexist with equal or better semantic correctness, which is consistent with a longer-answer or lexical-mismatch penalty. In E3--E6, however, DeepSeek Recall and semantic scores also decline. Those four conditions cannot be explained by verbosity alone and point to additional differences in retrieval, evidence selection, or answer utilisation.
5. **Metric-specific rankings are not interchangeable.** Qwen's F1 leader is E3, while its Strict and Soft leader is E5. DeepSeek's F1 and Soft leader is E1, and E1/E5/E7 tie for its highest Strict Accuracy. E2 is second in Qwen F1 but last in Qwen Strict and Soft. A single lexical ranking would therefore misrepresent semantic answer quality.
6. **E2 shows a small Strict--Soft disagreement.** DeepSeek has two more fully correct E2 answers than Qwen, but its Soft total is slightly lower. This should be reported as a small label-distribution difference, not interpreted mechanistically here.

**Report construction**

- Table 5.13 should be typeset as two visually separated panels under one table number: Panel A contains the compact E1--E7 backbone comparison above, and Panel B contains the architecture-stability matrix from Section 5.3.2.
- Panel A is generated from `condition-backbone-comparison.*`; the lexical explanation is generated from `lexical-explanation.*` and should remain a smaller supporting panel or appendix table if space is limited.
- The main paragraph should emphasise the uniform F1 gap, the much smaller condition-dependent semantic gap, and the answer-length/Precision pattern without treating length as the cause.

**Deliberately excluded**

- full win/tie/loss tables, judge-transition matrices, category breakdowns, calls, tokens, latency, trace review, and mechanism case studies.

**Interpretation boundary**

This is an end-to-end backbone comparison, not an isolated retriever or Answerer effect. Full Context is excluded because no Qwen Full Context run exists.

### 5.3.2 Stability of the Main Architectural Findings

**Purpose**

Test whether the principal RQ1 conclusions retain their observed direction under both backbone models without repeating the full RQ1 analysis.

**Writing position**

State the observed architecture conclusions directly when their direction is reproduced across the two tested pipelines. Limit each claim to Main-60, the declared store, the implemented retrieval systems, the fixed evidence budget, and the two backbone pipelines. Do not translate the absence of a new cross-backbone significance test into “no conclusion”; use it only to prevent universal or population-wide claims.

**Completed calculation**

For each pre-declared RQ1 contrast (c), backbone (b), and metric (m), reuse the audited within-backbone effect:

```text
effect(b, c, m) = target_condition_mean - baseline_condition_mean
```

Then calculate the descriptive cross-backbone effect difference:

```text
cross_backbone_effect_difference(c, m)
    = effect(DeepSeek, c, m)
    - effect(Qwen, c, m)
```

Token F1 and Strict Accuracy are the two primary classification metrics. Soft Semantic Score is an interpretive supplement. The canonical classification rule is:

- `stable`: both primary effect directions are retained across the two pipelines;
- `partly stable`: one primary effect direction is retained and the other reverses;
- `backbone-dependent`: both primary effect directions reverse;
- `indeterminate`: a primary point estimate is zero, so directional robustness is not assigned.

These are descriptive direction labels, not significance tests. They nevertheless support bounded empirical conclusions about the two tested pipelines. A subtype records whether a stable finding is uniformly positive or negative, or instead reproduces a cross-metric trade-off.

**Audited Table 5.13 Panel B inputs**

Each effect cell is `F1 / Strict / Soft`. Cross difference means `DeepSeek effect − Qwen effect`.

| Contrast | Qwen effect | DeepSeek effect | Cross-backbone effect difference | Canonical class |
|---|---:|---:|---:|---|
| E3−E1 | +0.0462 / +0.0333 / +0.0250 | −0.0041 / −0.0500 / −0.0500 | −0.0504 / −0.0833 / −0.0750 | Backbone-dependent |
| E4−E2 | −0.0071 / +0.0333 / +0.0083 | −0.0141 / −0.0333 / 0.0000 | −0.0070 / −0.0667 / −0.0083 | Partly stable |
| E2−E1 | +0.0082 / −0.0500 / −0.0500 | −0.0557 / −0.0500 / −0.1000 | −0.0640 / 0.0000 / −0.0500 | Partly stable |
| E4−E3 | −0.0451 / −0.0500 / −0.0667 | −0.0657 / −0.0333 / −0.0500 | −0.0206 / +0.0167 / +0.0167 | Stable, negative |
| E6−E5 | −0.0135 / −0.0500 / −0.0583 | −0.0364 / −0.0833 / −0.0917 | −0.0229 / −0.0333 / −0.0333 | Stable, negative |
| E5−E3 | −0.0463 / +0.0333 / +0.0250 | −0.0367 / +0.0500 / +0.0417 | +0.0096 / +0.0167 / +0.0167 | Stable metric trade-off |

The canonical counts are `stable = 3`, `partly stable = 2`, `backbone-dependent = 1`, and `indeterminate = 0`.

**Contrast-by-contrast interpretation**

1. **E3−E1 shows a conditional Qwen+R1 advantage rather than a model-independent storage benefit.** Under Qwen, foldering raises Precision by 0.0378, Recall by 0.0527, F1 by 0.0462, Strict by 0.0333, and Soft by 0.0250. The mean answer also becomes shorter, from 13.28 to 11.97 normalised tokens, while R1 uses fewer model calls, actions, and retrieval tokens. Under DeepSeek, the same change slightly lowers Precision and Recall, lengthens the answer, and lowers Strict and Soft by 0.0500. The gain is therefore best interpreted as S2 matching the current Qwen search--answer behaviour, which is more concise and precise in this path; concision itself has not been isolated as the cause. Qwen Evidence Recall changes by only +0.0072, and the positive answer effect is concentrated in temporal questions, so a plausible mechanism is improved navigation or evidence utilisation rather than retrieval of substantially more annotated evidence.
2. **E4−E2 is partly stable.** F1 is slightly negative under both pipelines, but Strict changes from +0.0333 under Qwen to −0.0333 under DeepSeek, while Soft changes from a small positive value to zero. The common F1 direction is small and must not be presented as a resolved disadvantage.
3. **E2−E1 is partly stable in the opposite metric pattern.** Strict falls by 0.0500 under both backbones and Soft falls under both, but F1 rises slightly under Qwen and falls under DeepSeek. This is direct evidence that the R2-versus-R1 conclusion depends on whether lexical overlap or semantic correctness is used.
4. **E4−E3 supports a clear quality conclusion within the tested S2 setting.** Replacing R1 with R2 lowers F1, Strict, and Soft under both backbones. Evidence Recall also falls by 0.0417 under Qwen and 0.0790 under DeepSeek, while Any-hit and All-hit decline in both pipelines. Thus, on the fixed S2 foldered raw store, Main-60, current R1/R2 implementations, and fixed evidence budget, R1 is the better quality-oriented retrieval system across both tested backbones. R2 remains substantially cheaper in recorded retrieval calls and tokens, so the result is a stable quality--efficiency trade-off rather than a universal theorem that R2 is always inferior.
5. **E6−E5 is stably negative.** Replacing R1 with R3 on the same frozen S3 store lowers all three answer metrics under both backbones, with larger observed losses under DeepSeek. The finding applies to the implemented R3 path, not every possible curated-memory retriever.
6. **E5−E3 reproduces a stable metric trade-off.** S3+R1 lowers Token F1 but raises Strict and Soft under both backbones. This is the strongest cross-backbone support for treating lexical overlap and semantic correctness separately. Because E5−E3 changes the complete representation, it remains a descriptive system anchor rather than a pure curation effect.

**Main-text contrasts retained**

- E3−E1: storage organisation with R1 fixed;
- E4−E2: storage organisation with R2 fixed;
- E2−E1: R2 versus R1 on S1;
- E4−E3: R2 versus R1 on S2;
- E6−E5: R3 versus R1 on S3;
- E5−E3: the descriptive S3+R1 versus S2+R1 complete-system anchor.

The storage–retrieval DID and E6−E4 remain supplementary. They are not used to increase the number of headline stability claims. E7−E2 and E7−E6 belong exclusively to RQ3.

Bootstrap intervals, complete win/tie/loss results, and category-level robustness are not required in the main text. If later requested by a reviewer, selected cross-backbone intervals may be added to the appendix without changing the main analysis.

**Required output**

- **Table 5.13, Panel A:** compact E1--E7 Qwen/DeepSeek condition comparison;
- **Table 5.13, Panel B:** compact architecture-stability matrix containing the two model-specific effects, cross-backbone effect difference, metric direction, and canonical classification;
- **Figure 5.3:** three-panel paired-effect plot for Token F1, Strict Accuracy, and Soft Semantic Score across the six architecture contrasts;
- one paragraph separating stable negative findings, stable metric trade-offs, partial stability, and backbone dependence.

**Interpretation boundary**

The classification describes robustness across the two tested pipelines only. It does not establish a universal backbone-invariant law.

### 5.3.3 Answer to RQ2

**Purpose**

State the cross-backbone conclusion without repeating the numeric tables.

**Audited answer to RQ2**

1. **Three of six architecture profiles support stable, bounded conclusions.** On S2, R1 provides higher answer quality and annotated-evidence coverage than R2 under both tested backbones, although R2 is cheaper. On S3, R1 also provides higher answer quality than the current R3 path under both backbones. Finally, S3+R1 consistently trades lower Token F1 for higher Strict and Soft scores relative to S2+R1.
2. **Two profiles are only partly stable.** E4−E2 retains only a small negative F1 direction; E2−E1 retains its negative Strict and Soft directions but reverses on F1.
3. **The clearest storage effect is a Qwen-specific conditional advantage.** E3−E1 improves lexical and semantic outcomes for Qwen while producing shorter answers and slightly lower search effort, but the same profile is not reproduced under DeepSeek. Folder organisation can therefore be recommended for the observed Qwen+R1 path, especially as a temporal-question result, but not claimed as a backbone-independent intervention.
4. **Condition-level backbone rankings are metric-dependent.** Qwen is higher on F1 in every condition, but DeepSeek matches or exceeds it semantically in selected conditions. Longer, lower-precision DeepSeek answers plausibly explain part, but not all, of this difference.
5. **Token F1 and semantic evaluation must remain separate.** E2−E1 and E5−E3 would produce materially different conclusions if only one evaluation family were retained.

**Draftable concluding statement**

RQ2 supports several useful but conditional conclusions. Within the tested Main-60 setting, R1 is the stronger quality-oriented retriever on both S2 and S3, whereas R2 offers a lower-cost but lower-quality path on S2. S3+R1 reproducibly improves semantic correctness relative to S2+R1 despite lower Token F1. Directory organisation benefits the Qwen+R1 pipeline but does not transfer to DeepSeek, showing that storage structure and backbone behaviour interact. The results therefore justify architecture recommendations within declared conditions rather than a single universal ranking.

**Interpretation boundaries**

- `Stable` means only that the observed point-estimate directions agree across the two tested end-to-end pipelines. It does not mean statistically significant, equal in magnitude, or universally backbone-invariant.
- The experiment changes both the Retrieval Agent and Answerer with the backbone. RQ2 cannot isolate which component causes a cross-backbone difference.
- The analysis uses the same fixed 60 questions under each condition and introduces no new confidence interval or significance test.
- Small effects, especially DeepSeek E3−E1 F1 and both E4−E2 F1 values, must be described as small point estimates.
- E7 appears only in the condition-level overview. Its effect relative to E2 and E6 belongs to RQ3.
- Full Context is excluded because no symmetric Qwen Full Context run exists.
- Detailed retrieval-side, utilisation-side, fusion, and long-context mechanisms remain deferred to RQ5.

**Source files for final writing**

- `condition-backbone-comparison.{csv,jsonl}`: seven primary same-condition comparisons;
- `lexical-explanation.{csv,jsonl}`: seven Precision/Recall/answer-length explanation rows;
- `architecture-stability.{csv,jsonl}`: complete six-row audited stability record;
- `table-5-13-inputs.{csv,jsonl}`: compact report-facing Panel B projection;
- `audit.json` and `RQ2.PASSED`: final integrity gate.

---

## 5.4 RQ3: Dual-Source Fusion

RQ3 asks whether the fixed E7 fusion condition benefits from combining two
different evidence-access paths: E2, which retrieves from raw dialogue, and
E6, which retrieves from Agent-Curated Memory. E7 is the only fusion condition
in the study. It reuses the two parent EvidenceBundles, performs no new
retrieval, and sends the deterministically merged evidence to the shared
Answerer. The section therefore evaluates evidence complementarity, fusion
quality, and interference without redefining E7 as a third retriever. Resource
cost is deferred to RQ6, while causal error attribution is deferred to RQ5.

**Required introductory output**

- **Figure 5.4:** composition of E7 from the S1+R2 parent path (E2), the
  S3+R3 parent path (E6), deterministic post-retrieval fusion, and one shared
  Answerer invocation. This is an explanatory system diagram rather than a
  measured result.

### 5.4.1 Does E7 Improve over Its Individual Parent Systems?

**Question addressed**

Does dual-source fusion improve answer quality over E2 and E6 when the
question, backbone model, Answerer contract, and evaluation protocol are held
fixed?

**Comparisons and calculations**

- calculate paired E7−E2 and E7−E6 differences separately for Qwen and
  DeepSeek;
- report Precision, Recall, F1, Strict Accuracy, Soft Semantic Score, and
  Evidence Recall;
- interpret lexical and semantic metrics separately rather than forcing them
  into one ranking;
- use Judge transitions to show how often E7 changes a parent answer from
  incorrect or partial to correct, and how often it moves in the opposite
  direction;
- describe all effects as paired descriptive changes; RQ3 introduces no new
  significance test.

**Backbone-specific argument**

- **Qwen:** present E7 as a modest but meaningful improvement in semantic
  correctness and evidence access relative to E2. Strict Accuracy rises by
  `0.0667`, Soft Semantic Score by `0.0417`, and Evidence Recall by `0.1178`.
  Relative to E6, E7 preserves Strict and Soft scores and raises Evidence
  Recall by `0.0632`, but does not improve lexical F1. The conclusion is a
  limited semantic-and-coverage benefit, not uniform superiority over both
  parents.
- **DeepSeek:** present E7 as a clear and broad descriptive improvement. All
  five answer-quality metrics and Evidence Recall increase relative to both
  E2 and E6. The F1 gains are `0.0398` over E2 and `0.0614` over E6; the Strict
  gains are `0.0500` and `0.0833`; the Soft gains are `0.0917` over both.

**Required output**

- **Table 5.14:** paired E7-minus-parent effects for both backbones;
- a short lexical-versus-semantic interpretation immediately below the table.

### 5.4.2 Are the Two Parent Paths Complementary, and How Much of That Opportunity Does E7 Capture?

**Question addressed**

Do E2 and E6 contribute non-redundant information and non-identical correct
answers, and does deterministic fusion convert that complementarity into all
of the correctness available from either parent?

**Evidence-access analysis**

- compare E2 and E6 retrieved source-ID sets using mean Jaccard overlap;
- compare parent Evidence Recall with the E7 source union;
- report marginal annotated-evidence coverage from each parent;
- emphasise that union Evidence Recall rises to `0.8994` under Qwen and
  `0.8951` under DeepSeek, while mean source-ID overlap remains low (`0.1956`
  and `0.1587`);
- interpret this as strong evidence that the two access paths retrieve
  different source locations and that fusion increases evidence coverage;
  do not equate source-ID difference with semantic conflict.

**Answer-level complementarity and parent-oracle gap**

- cross-tabulate whether E2 and E6 are Strict-correct on the same question;
- report the ten asymmetric parent cases under each backbone: Qwen has three
  E2-only and seven E6-only correct cases; DeepSeek has six E2-only and four
  E6-only correct cases;
- define the descriptive parent oracle as correct whenever either parent is
  correct;
- compare E7 with this diagnostic oracle-selector benchmark: Qwen E7 answers `44/60`
  questions correctly versus `47/60` for the parent oracle; DeepSeek answers
  `45/60` versus `46/60`;
- explain the combined conclusion: E2 and E6 are genuinely complementary,
  and E7 reaches or exceeds the best individual parent in Strict Accuracy,
  but fusion does not guarantee a correct answer whenever either parent is
  correct. The shared Answerer must still select, reconcile, and use the
  merged evidence.

**Required output**

- a compact parent-correctness profile table;
- an evidence-overlap and union-coverage table;
- one paragraph explaining why “better than an individual parent” and “below
  the parent oracle” are compatible findings.

### 5.4.3 When Does Fusion Repair Errors, and When Does It Introduce Interference?

**Question addressed**

Which questions and categories benefit from additional evidence, and where
does the merged EvidenceBundle fail to preserve an answer already available
from at least one parent?

**Question-level outcome analysis**

- classify every paired triple into four mutually exclusive Strict-based
  states: Repair, Preserve, Harm, and Unresolved;
- report Qwen as `1/43/4/12` and DeepSeek as `3/42/4/11` for
  Repair/Preserve/Harm/Unresolved;
- interpret Repair as successful use of complementary evidence and Harm as a
  candidate interference case, not as a proven causal diagnosis;
- send all 12 Repair/Harm cases to the unified RQ5 root-cause analysis.

**Category analysis**

- **Qwen multi-hop:** identify this as the clearest semantic-benefit category.
  E7 gains `0.1538` Strict over E2 and `0.0769` over E6, with one Repair and
  no Harm, even though lexical F1 decreases;
- **DeepSeek temporal:** identify this as the clearest overall fusion-success
  category. It contains two Repairs and one Harm, with Strict gains of
  `0.1538` over E2 and `0.2308` over E6;
- **Qwen single-hop:** identify this as the main interference candidate. It
  contains three of the four Qwen Harm cases and no Repair;
- **DeepSeek single-hop:** state that fusion is stronger than E6 but is close
  to E2 on Strict Accuracy;
- **open-domain:** retain the lexical-versus-semantic disagreement as an
  exploratory observation only because the subgroup has seven answers and
  five evidence-eligible questions;
- where Precision or F1 falls while semantic scores or Evidence Recall rise,
  discuss possible redundancy, longer or more paraphrastic answers, and
  irrelevant evidence as hypotheses for RQ5. Do not label the cause as noise
  without trace evidence.

**Required output**

- **Figure 5.5:** E2/E6 parent-correctness profiles and the E7
  Repair/Preserve/Harm/Unresolved flow;
- a category-level effect table containing answer and evidence denominators;
- a short list of candidate mechanisms to be tested in RQ5.

### 5.4.4 Answer to RQ3

The final answer should make four linked claims.

1. **Fusion increases evidence coverage.** E2 and E6 retrieve substantially
   different source sets, and their union raises Evidence Recall under both
   backbones.
2. **The quality gain depends on the backbone.** Qwen receives a modest
   semantic-and-coverage benefit, mainly relative to E2, whereas DeepSeek
   converts the larger evidence pool into clear gains across all reported
   answer metrics relative to both parents.
3. **Complementarity creates an opportunity, not a guarantee.** E7 reaches or
   exceeds the best individual parent in Strict Accuracy, but remains below
   the descriptive parent oracle-selector benchmark because it does not
   preserve every answer that one parent gets right.
4. **The value of fusion depends on question type.** Multi-hop questions under
   Qwen and temporal questions under DeepSeek show the clearest benefits,
   while Qwen single-hop questions contain the strongest interference signal.

The overall conclusion is that E7 is useful and, under DeepSeek, clearly
effective, but its benefit is conditioned by the backbone and question type.
The section must not claim universal superiority, statistical significance,
or a causal failure mechanism without the RQ5 root-cause analysis.

**Completed-analysis status (25 October 2026)**

- The formal offline program is `fs_memory_lab/chapter5_rq3.py`, with tests in `tests/test_chapter5_rq3.py`.
- The audited source of truth is `artifacts/chapter5-main60-analysis-v1/rq3-dual-source-fusion/`; `RQ3.PASSED` binds audit ID `rq3-audit-e0ac8fc4a256b4fa5d016871163fc19243e99a9328985568b48b73ee35586378`.
- The calculation uses 360 Stage A rows and 120 paired `(E2, E6, E7)` triples. Answer metrics use `N = 60`; Evidence Recall uses `N = 58`.
- DeepSeek E7 improves Precision, Recall, F1, Strict, Soft, and Evidence Recall relative to both parents. Qwen E7 provides a modest semantic-and-coverage gain relative to E2, ties E6 semantically, increases evidence coverage relative to both, and lowers F1 relative to both parents.
- Strict outcomes are Qwen `Repair/Preserve/Harm/Unresolved = 1/43/4/12` and DeepSeek `3/42/4/11`.
- Each backbone has ten questions on which exactly one parent is Strict-correct, demonstrating answer-level complementarity. The descriptive parent oracle-selector benchmark remains above E7 by three Qwen questions and one DeepSeek question. It is not an implementable system or a strict mathematical upper bound on fusion.
- Source-ID overlap is low (`0.1956` Qwen; `0.1587` DeepSeek), while union Evidence Recall rises to `0.8994` and `0.8951`. Source-ID overlap is not interpreted as text overlap or semantic conflict.
- Qwen multi-hop and DeepSeek temporal questions provide the clearest positive category patterns. Qwen single-hop contains three of its four Harm cases. Open-domain results remain exploratory because they contain seven answers and five evidence-eligible questions.
- The 12 Repair/Harm identifiers are exported for the unified RQ5 root-cause analysis. RQ3 itself does not claim causal conflict or failure-stage attribution.

**Source files for final writing**

- `parent-effects.{csv,jsonl}` and `table-5-14-inputs.{csv,jsonl}`: main E7-minus-parent effects;
- `category-effects.{csv,jsonl}`: category-specific descriptive effects;
- `judge-transitions.{csv,jsonl}`: complete incorrect/partial/correct transitions;
- `fusion-outcomes*`, `parent-complementarity*`, and `figure-5-6-inputs*`: Strict outcome flow;
- `evidence-source-overlap.{csv,jsonl}`: source-ID and annotated-coverage summary;
- `question-diagnostics.{csv,jsonl}` and `rq5-candidate-cases.{csv,jsonl}`: publication-safe diagnostic inputs;
- `audit.json` and `RQ3.PASSED`: final integrity gate;
- `docs/analysis/chapter5-rq3-process-and-results.md`: human-readable calculation and interpretation record.

---

## 5.5 RQ4: Full Context versus Selective Retrieval

RQ4 treats Full Context as a DeepSeek-only diagnostic access path. It is not E8, a new storage representation, a retrieval method, or an oracle.

### 5.5.1 Paired Quality Comparison

**Comparison plan**

- compare Full Context with DeepSeek E1–E7 for completeness;
- emphasise Full Context versus E1, E5, and E7 in the main text;
- place the remaining complete comparison table in the appendix if space is constrained.

**Required analysis**

- paired Precision, Recall, F1, Strict Accuracy, and Soft Semantic Score;
- same-question outcome counts and the direction of the principal differences;
- answer and context length only where they explain quality differences.

**Required output**

- **Table 5.15:** Overall Full Context and DeepSeek E1–E7 quality results;
- **Table 5.16, Panel A:** paired Full Context-minus-selective effects.

**Interpretation boundary**

Full Context has no retrieval Evidence Recall. Complete source visibility must not be entered as Evidence Recall = 1.

### 5.5.2 Complete Visibility versus Evidence Focus

**Required analysis**

- form four paired outcome states: both correct, Full Context only correct, selective retrieval only correct, and neither correct;
- test whether complete visibility repairs likely access failures;
- test whether compact EvidenceBundles sometimes outperform complete history by reducing distraction;
- identify asymmetric cases for the unified RQ5 review.

**Required output**

- **Table 5.16, Panel B:** Full Context versus selective-retrieval Strict quadrants.

No additional RQ4 figure is required. The paired table carries the exact outcome counts without duplicating them in a chart.

### 5.5.3 Question-Category Differences

**Required analysis**

- compare Full Context and E7 within Multi-hop, Temporal, Open-domain, and Single-hop questions;
- use E1 and E3 as additional anchors when explaining the Single-hop focusing effect;
- distinguish semantic gains from token-overlap changes;
- treat the seven-question Open-domain group as exploratory.

**Required output**

- **Table 5.17:** category-specific Full Context and E7 quality results and Strict quadrants.

### 5.5.4 Answer to RQ4

State whether Full Context is generally stronger, which question patterns favour complete visibility or selective evidence, and why complete visibility does not guarantee correct utilisation.

Detailed failure-stage attribution, representative cases, and long-context error mechanisms are reported once in RQ5. Full Context token cost is compared in RQ6.

---

## 5.6 RQ5: Error Chain and Bottleneck Diagnosis

RQ5 is the single home for detailed mechanism attribution. It asks where the observed failures arise within the implemented memory systems: the declared storage representation, its matched retrieval process, evidence packaging, Answerer utilisation, E7 fusion, Full Context processing, or evaluation. Candidate mechanisms identified in RQ1–RQ4 are resolved here rather than repeated as unverified explanations in the earlier sections.

Source integrity and data normalisation are retained only as a short eligibility check. The analysis verifies that the question, reference, canonical source, and provenance mapping are available before examining a case, but it does not treat canonicalisation as an independent research question. The main analysis concerns the tested S1–S3 stores, R1–R3 retrieval systems, E7, Full Context, the shared Answerer, and the evaluation pipeline.

### 5.6.1 Root-Cause Model and Analysis Design

**Purpose**

Define the error chain, the units of analysis, and the attribution rules used throughout RQ5. The central question is not merely which condition produced an incorrect answer, but where the first supported break occurred between stored information and the evaluated answer.

**Research questions**

1. At which stage does the first supported failure occur: storage representation, retrieval access, evidence retention and packaging, Answerer utilisation, E7 fusion, Full Context processing, or evaluation?
2. Which failure mechanisms are shared across conditions, and which are specific to S1–S3, R1–R3, E7, Full Context, or one backbone model?
3. How often does sufficient evidence still fail to produce a correct answer, and how often does a correct answer arise without complete annotated-evidence coverage?
4. Which earlier interpretations from RQ1–RQ4 are supported by the end-to-end traces, and which must remain unresolved?

**Analysis population and units**

- use all 900 Main-60 answer records to describe the complete outcome space;
- use the 720 E1–E6 records as the independent selective-retrieval paths; E7 reuses E2 and E6 and is not counted as a new retrieval run;
- analyse the 120 E7 answer records as fusion outcomes and the 60 DeepSeek-family Full Context records as the long-context path;
- use the 250 Strict non-correct answers as the primary error-attribution population: 205 E1–E6 paths, 31 E7 paths, and 14 Full Context paths;
- of these error paths, 233 are evidence-eligible and 17 belong to the two questions without gold source annotations; the latter remain in answer and evaluation analysis but not in annotated-evidence attribution;
- retain Strict-correct rows from the same question and backbone as counterfactual paths that show where another condition succeeded;
- use all 60 questions for answer outcomes and only the fixed 58-question eligible set for annotated-evidence metrics;
- group records by `backbone × question` so that E1–E7, and Full Context where applicable, are interpreted as a connected set rather than as unrelated rows.

**Short eligibility gate**

Before a record enters the root-cause analysis, confirm only that the question, reference answer, canonical source, declared store version, and applicable source annotations are readable and correctly linked. This gate protects the analysis from malformed inputs. Source preparation and canonicalisation are not treated as an independent empirical result.

**End-to-end diagnostic chain**

For each selective path, reconstruct the following ordered states:

1. **Store availability:** the required fact or a valid equivalent exists in the declared store with adequate entity, relation, temporal state, and granularity.
2. **Retriever reach:** the process reaches the relevant file, exchange, topic, or fact entry.
3. **Model observation:** the relevant content is exposed in an actual tool result, ranked candidate, expansion, or retrieved entry.
4. **Evidence retention:** the observed support survives notes, selection, provenance conversion, and EvidenceItem construction.
5. **Final-input sufficiency:** the final EvidenceBundle contains enough information to answer the question, including every necessary hop or temporal anchor.
6. **Answer utilisation:** the Answerer converts that input into the correct entity, relation, time, list, or conclusion.
7. **Evaluation agreement:** token scoring and the LLM judge represent the answer in a way consistent with its substantive correctness.

Full Context enters the chain at final-input availability because it bypasses selective retrieval and EvidenceBundle construction. E7 enters after the two parent EvidenceBundles have been produced.

**Primary and secondary attribution rules**

- assign the earliest broken state supported by the record as the primary root cause;
- assign a secondary mechanism only when a later failure is independently visible and materially affects the outcome;
- do not infer a storage failure from a low score when the required fact is present in the store;
- do not infer a retrieval failure from low Evidence Recall alone, because the answer may rely on a valid alternative source;
- do not infer an Answerer failure unless the final input is sufficient for the required answer;
- retain `mixed` when two mechanisms cannot be separated and `indeterminate` when the available trace cannot support a defensible label.

Each attribution also receives an evidence-strength tag:

- **direct:** the failed transition is explicitly visible, such as a missing curated fact, an observed fact omitted from the bundle, or sufficient evidence followed by the wrong answer;
- **convergent:** multiple signals support the same mechanism, but no single event proves it;
- **indeterminate:** competing explanations remain.

**Core calculations**

- absolute counts and unconditional rates over the 60 questions for each condition and backbone;
- error-conditioned proportions using the number of Strict non-correct answers in that condition as the denominator;
- transition rates for `available → reached → observed → retained → sufficient → correct`;
- `P(correct | sufficient evidence)` and `P(correct | insufficient evidence)` by condition, backbone, and question category;
- primary and secondary root-cause distributions;
- cross-backbone agreement for the same condition and question, separating shared architecture failures from model-dependent failures;
- paired root-cause transitions for the main controlled contrasts: E3−E1, E4−E2, E2−E1, E4−E3, E5−E1/E3, and E6−E5;
- unresolved rate, reported explicitly rather than redistributed to a preferred mechanism.

**Main output**

Section 5.6.1 supplies the common denominator and attribution contract for the later RQ5 tables and figures. It does not present data-normalisation errors as a substantive finding.

**Formal Section 5.6.1 execution record (25 October 2026).** The audited offline builder consumed the frozen 900-row Stage A master table and atomically published `artifacts/chapter5-main60-analysis-v1/rq5-root-cause-index`. It produced a 900-row unified case index, an exact 250-row Strict-noncorrect list, a matching 250-row condition-aware root-cause state register, 120 `backbone × question` packets, and a 75-row denominator census. The 250 errors comprise 74 Partial and 176 Incorrect Judge labels: 205 E1–E6 paths, 31 E7 paths, and 14 Full Context paths. Of these, 233 are evidence-eligible and 17 are not. Fifty-eight question packets contain at least one Strict error (27 Qwen and 31 DeepSeek), covering 33 unique question IDs. The state model defines separate ordered chains for E1–E6, E7, and Full Context; all applicable analytical states and all primary/secondary attributions remain pending at this stage. The published artifact passed exact source-record hash checks, independent byte reconstruction, deterministic-order, denominator, lineage, applicability, forbidden-field, and tamper-rejection tests under audit ID `rq5-stage-1-audit-f1a9efe44c178464f8e04ae9eb224585df8f76a512d29dd48ab428579b61f7b6`. No API or network call was made, no formal source was modified, and no downstream causal label was assigned.

### 5.6.2 Storage Organisation, Fidelity, and Failure Attribution

**Purpose**

Determine what each representation preserves, removes, reorganises, or makes difficult to access before retrieval behaviour is considered. The analysis separates content fidelity from representational burden: a store can preserve every fact yet still make the relevant fact difficult to locate among flat, repeated, or temporally competing material.

**Storage-level unit and dimensions**

The principal unit is `question × store`, evaluated once for S1, S2, and S3 rather than duplicated by backbone. Backbone-specific answer outcomes are then linked to the same store diagnosis. Each store is assessed along five dimensions:

1. **fact survival:** whether all answer-bearing facts remain available;
2. **semantic fidelity:** whether entities, relations, quantities, polarity, and event status remain correct;
3. **temporal fidelity:** whether order, dates, updates, and current-versus-old states remain distinguishable;
4. **granularity:** whether the representation retains enough detail for the reference-level answer;
5. **access structure and provenance:** whether location, topic routing, and source links make the information traceable and discoverable.

#### 5.6.2.1 S1 Preserves Content but Leaves Cross-Session Composition

S1 is expected to preserve raw content, so the main question is not compression loss but the cost of an unstructured representation.

**Mechanisms to test**

- true content or metadata loss: missing turn, altered turn, incorrect speaker, broken chronology, session-boundary error, or source-locator mismatch;
- flat-navigation burden: the relevant session has no topic-level routing cue;
- evidence dispersion: the required hops occur in different sessions or far-apart turns;
- distractor density: repeated entities, similar events, or obsolete temporal states compete with the target fact;
- lexical opacity: the raw conversation uses wording that differs from the question or answer vocabulary.

**Calculations**

- raw-source preservation rate and metadata-consistency rate;
- number of sessions and turns separating required evidence items;
- number of competing mentions of the target entity, relation, or event;
- association between dispersion/distractor measures and source reach, Evidence Recall, and Strict correctness under E1 and E2;
- E1/E2 error counts in which S1 is complete but the downstream path still fails.

If the raw fact is intact, the primary root cause is not labelled `S1 omission`; the S1 properties are retained as explanatory access burdens for the R1/R2 analysis.

#### 5.6.2.2 S2 Preserves Content but Provides an Imperfect Routing Cue

S2 is designed to change navigation while preserving the raw session body. Its analysis therefore asks whether organisation narrows the search space or misroutes it.

**Mechanisms to test**

- content mismatch between the S1 and S2 copies of the same session;
- correct routing of each gold-bearing session to a topic folder;
- ambiguous or overly broad folder labels;
- multi-topic sessions assigned to only one misleading location;
- evidence split across folders that encourages partial retrieval;
- duplicate routing that adds redundant search paths;
- folder hierarchy that reduces or increases the number of files inspected before the first relevant observation.

**Controlled comparisons and calculations**

- verify S1–S2 content equivalence separately from organisation quality;
- compare E3 with E1 under R1 as the direct navigation contrast;
- treat E4 versus E2 as a representation-invariance check rather than a folder-navigation effect, because R2 operates on the same raw exchange index and does not consume the S2 directory path;
- classify E3−E1 outcomes as organisational repair, neutral organisation, or organisational harm;
- compare E3/E1 source-reach rate, time or actions to first relevant observation, inspected-file breadth, Evidence Recall, and answer outcome;
- report any E4−E2 divergence as an invariance or run-variation diagnostic, never as evidence that R2 used the S2 folder hierarchy;
- stratify the E3−E1 repairs and harms by single-hop, multi-hop, temporal, and open-domain category;
- distinguish folder-induced misrouting from a retriever that ignored a correct folder cue.

#### 5.6.2.3 S3 Preserves Provenance but Does Not Guarantee Answer-Sufficient Facts

S3 changes both content form and organisation. It must therefore be evaluated as a lossy but potentially useful transformation rather than as a rearranged copy of S1.

Provenance presence is only the first check. The frozen S3 store contains the gold locators for all 58 evidence-eligible questions, but a locator attached to a broad summary does not prove that the required entity, relation, temporal state, or granularity survived. The analysis must therefore evaluate the stored statement itself.

**Canonical-source-to-curated mapping**

For each answer-bearing fact, classify the S3 representation as:

- `preserved_exactly`;
- `compressed_but_sufficient`;
- `partially_preserved`;
- `missing`;
- `distorted`;
- `stale_or_conflicting`.

**Mechanisms to test**

- curation omission;
- summarisation distortion or unsupported generalisation;
- loss of fine-grained attributes, quantities, or list members;
- entity conflation or fragmentation;
- relation loss;
- temporal-state collapse or stale update;
- duplicate or conflicting curated entries;
- missing, incorrect, or overly coarse provenance;
- vocabulary abstraction that helps conceptual matching but removes the wording needed for a precise answer.

**Calculations**

- fact-survival, sufficient-preservation, partial-preservation, omission, distortion, stale/conflict, and provenance-validity rates;
- compression and granularity measures linked to token Recall, F1, Strict Accuracy, and Soft Semantic Score;
- E5/E6 outcome rates conditional on whether the required fact is exactly preserved, sufficiently compressed, partial, or absent;
- error profiles by question category, especially temporal update and multi-hop relation cases;
- E5−E1 and E5−E3 comparisons as same-retriever complete-system contrasts, interpreted together with the direct store diagnosis;
- E6−E5 as an access-method contrast inside S3, not as a pure storage comparison.

#### 5.6.2.4 Storage Omission Is Not the Dominant Observed Bottleneck

Aggregate the E1--E6 Strict-noncorrect paths by audited storage state. Report how many paths retain unambiguous support, how many have only partial or conflicting support, and how many lack official annotations. This subsection connects the representation audit to downstream retrieval and utilisation without treating repeated answer paths as independent storage defects.

**Required storage outputs**

- **Table 5.18, Panels A–D:** S1 dispersion, S2 semantic routing and descriptive outcome linkage, and S3 source-fidelity/reference-support audits;
- **Table 5.19:** E5/E6 outcomes conditional on S3 reference-support sufficiency;
- **Table 5.20:** storage states of the 205 E1–E6 Strict-noncorrect paths;
- **Figure 5.6:** normalised storage-state distribution for those 205 paths;
- category and backbone breakdowns only where the denominator remains interpretable.

**Interpretation boundary**

Aggregate score differences do not identify a storage root cause. S2 benefits require organisation-mediated trace evidence, and S3 loss requires a direct canonical-to-curated mismatch. Comparisons that change both storage and retrieval remain complete-system evidence.

**Formal Section 5.6.2 execution record (25 October 2026).** The audited
offline builder published
`artifacts/chapter5-main60-analysis-v1/rq5-storage-audit` from the frozen
Main-60 sources, S1–S3 stores, Stage A table, and Section 5.6.1 register. The
primary register contains 180 `question × store` rows, including 174
evidence-eligible rows. Storage labels were frozen before 720 E1–E6 outcomes
were joined. S1 and S2 have 30/30 byte-identical session files; S2's
outcome-blind semantic audit found 55 aligned, six partially aligned, and 18
misleading `question × gold-bearing session` units. S3 contains all 68 unique
Main-60 gold locators but is 2.662 times the size of S1. The two-pass semantic
audit separates source-to-store fidelity from benchmark-reference support: 51
questions are faithful to source, five are compressed but source-faithful, one
preserves a source conflict, and one inherits a shared renderer detail loss;
no curator-introduced decisive loss was found. The shared q002 insufficiency is
not attributed to S1, S2, or S3 individually, and affected answer paths are
recorded as exposed to an upstream limitation whose path-level causal
sufficiency is not established. All 22 Section 5.6.1–5.6.2 tests and the final
deterministic reconstruction audit passed under audit ID
`rq5-storage-audit-5ff8638baf55d3e678e266ade364aafd6076e0d89c1193aad05b59bda631f5eb`.
The detailed method, denominators, results, limits, and output inventory are
recorded in
`docs/analysis/chapter5-rq5-storage-audit-process-and-results.md`.

### 5.6.3 Retrieval Bottlenecks and Task-Specific System Choice

**Purpose**

Explain why information that exists in the declared store is or is not converted into usable evidence. R1, R2, and R3 are analysed through a common retrieval funnel, then through retriever-specific mechanisms.

#### 5.6.3.1 Where Does the Pipeline Actually Fail?

**Common retrieval funnel**

For each of the 720 E1–E6 retrieval paths, identify:

1. whether a valid source is present in the store;
2. whether the source is ranked, navigated to, or otherwise reached;
3. whether an official annotated source span or fact is exposed to the retrieval model;
4. whether every officially annotated hop or temporal anchor is collected;
5. whether the observed evidence is retained in notes or the selected set;
6. whether it survives into the final EvidenceBundle.

This funnel distinguishes `source not reached`, `source reached but annotated span not observed`, `partial multi-hop acquisition`, and `observed but not retained`. These are different trace states and must not be collapsed into a single low-Evidence-Recall category. Because official evidence annotations are diagnostic anchors rather than exhaustive relevance labels, the trace state alone does not establish a causal retrieval failure.

#### 5.6.3.2 Why Do R1, R2, and R3 Fail Differently?

**R1: Agentic Filesystem Retrieval**

**Mechanisms to test**

- incorrect initial directory or file choice;
- failure to exploit an available S2 or S3 organisational cue;
- search-term mismatch in `grep`;
- search hit found but the wrong surrounding range viewed;
- decisive context located just outside the selected view range;
- relevant content observed but omitted or distorted in retrieval notes;
- repeated low-yield searches or unnecessary file revisits;
- premature `finish_search` despite missing hops;
- native round-cap exhaustion;
- relevant notes not promoted into the final EvidenceBundle.

**Process measures**

- directories and files inspected;
- grep/search attempts and productive-hit rate;
- round of first relevant observation;
- rounds after the first hit;
- repeat-visit rate;
- number of required hops observed and retained;
- stop state: sufficient stop, premature stop, or cap stop;
- observed-to-note and note-to-EvidenceBundle retention rates.

The analysis compares R1 on S1, S2, and S3 to determine whether a store changes navigation success without assuming that the same R1 trace behaviour has the same meaning in all three stores.

**R2: ReFind-Style Raw-Chat Retrieval**

**Mechanisms to test**

- initial query omits the decisive entity, relation, temporal cue, or event;
- BM25 lexical mismatch places the relevant exchange below the accessible range;
- relevant exchange is retrieved but its session loses in session-level fusion or ranking;
- the fixed local context window fails to include the adjacent turn that establishes acquisition, update, time, or causality;
- seen-state suppresses a necessary revisit or permits unproductive repetition;
- multiple hops are retrieved separately but not jointly retained;
- action budget is consumed before sufficient evidence is assembled;
- final selection drops a relevant exchange already reached.

**Process measures**

- rank of the first valid exchange and first gold-bearing session;
- query-to-source lexical overlap and the missing semantic role in failed queries;
- session-fusion outcome;
- distance from the retrieved exchange to the required adjacent turn, evaluated against the fixed context window;
- productive versus repeated actions;
- first-hit action, stop action, and action-cap status;
- reached-to-expanded and expanded-to-EvidenceBundle conversion rates.

**R3: Curated-Memory Retrieval**

**Mechanisms to test**

- incorrect H2-group ranking or routing under the curated BM25/RRF index;
- mismatch between question wording and curated terminology;
- correct topic but incorrect fact ranking;
- failure to expand to a related entry needed for a second hop;
- selection of a stale state rather than the current state;
- failure to resolve duplicates or conflicting entries;
- loss of provenance during fact retrieval or conversion;
- action-cap exhaustion or premature stop;
- correct curated fact reached but excluded from the EvidenceBundle.

**Process measures**

- first sufficient H2-group rank and H2-group reach rate;
- rank and action of the first sufficient curated fact;
- related-entry expansion success;
- current-state versus stale-state selection rate;
- conflict-resolution outcome;
- provenance survival;
- fact-observation-to-EvidenceBundle retention rate.

#### 5.6.3.3 Which Storage--Retrieval Pairing Fits Each Question Type?

Use paired questions to separate retriever behaviour from store effects:

- E2−E1 compares R2 with R1 on S1;
- E4−E3 compares R2 with R1 on S2;
- E6−E5 compares R3 with R1 on S3;
- E3−E1 tests whether S2 changes R1's filesystem access path, while E4−E2 acts as a negative-control-style invariance check because R2 does not use folder paths;
- the same condition across Qwen and DeepSeek tests whether query formulation, stopping, or evidence retention is backbone-dependent.

For every comparison, report source-reach transitions, complete-evidence transitions, Strict repair/harm transitions, and cases in which retrieval improves but answer quality does not.

**Required retrieval calculations and outputs**

- reach, observation, complete-acquisition, retention, and final-bundle rates by retriever, store, backbone, and category;
- attrition counts between each adjacent funnel stage;
- Any-hit, All-hit, Evidence Recall, and evidence-sufficiency cross-tabs with Strict and Soft outcomes;
- `P(correct | All-hit)` and `P(correct | not All-hit)`, clearly distinguished from the content-based sufficiency analysis;
- rate of relevant evidence observed but lost before the EvidenceBundle;
- rate of declared-sufficient stops with incomplete annotation, native cap hit, empty bundle, nonempty bundle without official annotated evidence, and partial multi-hop bundle; neither cap nor absence of an annotation is treated as an automatic failure label;
- **Table 5.21:** annotated-evidence loss location among eligible errors;
- **Table 5.22:** R1–R3 retrieval, answer-quality, and cost profiles;
- **Table 5.23:** task-specific evidence-access recommendations;
- **Figure 5.7:** normalised annotated-evidence states for evidence-eligible Strict-error paths, grouped by retriever.

#### 5.6.3.4 Section Synthesis

Summarise the dominant loss point by retriever and connect it to task-specific system choice. The synthesis must distinguish a complete annotated bundle from semantically sufficient final input, state that R1 offers the strongest evidence funnel at higher cost, and explain why R2 or R3 may still be preferable under narrower cost or representation constraints.

**Interpretation boundary**

R1 rounds, filesystem tool calls, R2/R3 actions, and offline BM25 operations are different process units. They are compared within their native systems, not treated as one interchangeable count. A native cap hit is a process state, not an automatic failure label: capped paths can still end with sufficient evidence and a correct answer. Better retrieval metrics do not establish better Answerer utilisation.

**Formal Section 5.6.3 execution record (25 October 2026).** The audited
offline builder published
`artifacts/chapter5-main60-analysis-v1/rq5-retrieval-audit` from the frozen
Main-60 records, R1 traces, deterministically replayed R2/R3 actions, Stage A
table, and the post-storage RQ5 state register. The primary register contains
720 E1--E6 retrieval paths, of which 696 are evidence-eligible. The formal
replay exactly reproduces all 360 R2/R3 ranked-search trajectories, including
query terms, date filters, returned sources, local expansion, and seen-state.
R1, R2, and R3 achieve mean Evidence Recall of 0.875, 0.782, and 0.781, with
final All-hit rates of 83.6%, 73.7%, and 73.3%, respectively. Among 191
evidence-eligible Strict-noncorrect paths, 111 (58.1%) already contain a
complete annotated EvidenceBundle; 80 (41.9%) show attrition at some annotated
evidence-funnel stage. Native caps are not treated as failures: 234 of 359
capped paths are Strict-correct. No causal root cause was assigned
automatically, and no Section 5.6.4 downstream state was modified. All 14
retrieval-audit tests, the combined 36-test Section 5.6.1--5.6.3 suite, the
independent raw-record reconstruction, and the deterministic final audit
passed under audit ID
`rq5-retrieval-audit-1e2aacfe880ba84f21f22e6fee306533cde0c5e309d8211937e4af3de1b4925f`.
The detailed method, denominators, results, limits, and output inventory are
recorded in
`docs/analysis/chapter5-rq5-retrieval-audit-process-and-results.md`.

### 5.6.4 Evidence Conversion, Answerer Utilisation, Fusion, and Full Context

**Purpose**

Determine what happens after potentially relevant material has been reached. This section separates four mechanisms that aggregate answer scores cannot distinguish: evidence loss before the final prompt, failure to use sufficient evidence, dual-source fusion behaviour, and long-context processing.

#### 5.6.4.1 Evidence Sufficiency and Packaging

**Evidence-state taxonomy**

Classify each final selective input as:

- `complete_and_focused`: sufficient support with little competing material;
- `complete_but_noisy`: sufficient support plus substantial redundancy, conflict, or distractors;
- `partial`: at least one useful fact is present but a required hop, time anchor, entity link, or list member is missing;
- `irrelevant_or_empty`: no usable support for the answer;
- `indeterminate`: the available record does not establish sufficiency.

Sufficiency is content-based. Annotated Evidence Recall is an important signal, but neither All-hit nor Evidence Recall of 1.0 automatically proves that the final text preserves the necessary relation and context.

**Packaging mechanisms to test**

- relevant information observed upstream but omitted from retrieval notes;
- note content preserved but not converted into an EvidenceItem;
- provenance validation rejects or detaches a relevant item;
- ordering places decisive material behind repeated or low-value evidence;
- duplicate handling suppresses a complementary rather than redundant note before EvidenceBundle construction;
- a relevant whole EvidenceItem is explicitly skipped by the 16,000-character budget;
- multi-hop evidence survives as isolated facts but loses the relation needed to compose them.

**Calculations**

- observed→retained→packaged conversion rates;
- evidence-state distribution by condition, backbone, and category;
- decisive-evidence position within the final bundle;
- bundle length, item count, redundancy, and conflict measures by evidence state;
- Strict and Soft outcome rates for each evidence state;
- explicit budget-loss count, requiring a demonstrated relevant skipped item. Individual EvidenceItems are not truncated by this implementation, so `truncated=false` is an audit condition rather than a failure subtype.

#### 5.6.4.2 Shared Answerer Utilisation

An Answerer root cause is assigned only when the final input is sufficient. The analysis distinguishes reasoning and extraction failures from answer-form effects.

**Content-utilisation mechanisms**

- single-hop extraction of the wrong entity or attribute;
- failure to combine multiple supporting facts;
- entity or pronoun resolution error;
- incorrect temporal ordering, date inference, duration, or current-state selection;
- confusion between intention, plan, preference, and completed event;
- negation or polarity error;
- incomplete list or missing fine-grained attribute;
- unsupported inference or hallucinated relation;
- excessive caution despite direct support;
- failure to reconcile corroborating or conflicting evidence.

**Answer-form mechanisms**

- under-answering, which lowers Recall or omits a required component;
- over-answering, which adds unsupported or unnecessary material and can lower Precision;
- paraphrastic but semantically valid wording;
- correct core answer with an incorrect qualifier;
- correct evidence use but mismatch with reference granularity.

**Calculations**

- evidence-sufficient but Strict non-correct rate by condition and backbone;
- answer-utilisation subtype distribution by question category;
- Qwen–DeepSeek difference under the same condition and comparable evidence state;
- cases with identical or near-identical source-ID sets but different semantic outcomes;
- answer length and token Precision/Recall/F1 within each utilisation subtype;
- answer success without All-hit, separated into alternative-evidence success and annotation-sensitive cases.

#### 5.6.4.3 E7 Dual-Source Fusion

E7 must be analysed relative to both E2 and E6 parent bundles. It performs no third retrieval operation.

**Parent-state design**

Classify each question by whether the E2 and E6 bundles are individually sufficient, partially sufficient, or insufficient. Then relate that state to E7 Repair, Preserve, Harm, or Unresolved outcomes.

**Mechanisms to test**

- complementary repair: different parent bundles contribute different necessary facts;
- corroborative reinforcement: both parents support the answer and fusion stabilises the output;
- synthesis without parent-level correctness: individually incomplete parents become sufficient when combined;
- redundant fusion: additional evidence changes neither sufficiency nor outcome;
- salience dilution: decisive evidence remains present but becomes harder to prioritise;
- evidence conflict: raw and curated evidence express different temporal states, granularity, or entities;
- synthesis failure: complementary facts are present but the Answerer does not compose them;
- parent-sufficient harm: at least one parent is sufficient, yet E7 loses the correct outcome.

Because each parent is already capped at 16,000 characters and E7 permits their 32,000-character union, ordinary E7 tail truncation is not assumed. Parent-item loss must be demonstrated as an implementation anomaly. Otherwise, Harm is attributed only to supported salience, conflict, or synthesis mechanisms.

**Calculations**

- parent-sufficiency × E7-outcome matrix;
- source overlap, marginal gold coverage, union sufficiency, redundant-parent evidence, and conflict count;
- Repair, Preserve, Harm, and Unresolved mechanism distributions by backbone and category;
- probability of E7 correctness when neither, one, or both parents are sufficient;
- proportion of union-complete cases that still fail, interpreted as a fusion-to-Answerer conversion gap.

#### 5.6.4.4 Full Context and Selective-Focus Diagnostics

Full Context exposes all 30 raw sessions and bypasses S2, S3, R1–R3, and EvidenceBundle construction. It is therefore analysed as a separate access regime, not as E8 and not as a retrieval method.

**Diagnostic comparison states**

- `both_correct`: Full Context and the selective comparator are Strict-correct;
- `full_context_only`: complete visibility repairs a selective-path failure;
- `selective_only`: focused evidence succeeds while Full Context fails;
- `neither_correct`: both access regimes remain unsuccessful.

Use all seven DeepSeek E1–E7 comparisons for completeness. For root-cause synthesis, also use a clearly labelled descriptive `any-selective-correct` view; this is an oracle-style diagnostic and not a deployable system.

The seven pairings create 420 comparison rows, but they still describe only 60 Full Context answers. Root-cause counts must therefore be reported at the unique-question level unless a table explicitly states that it contains paired-comparison outcomes.

**Repair mechanisms to test**

- recovery of a source omitted by selective retrieval;
- access to a missing second hop or temporal anchor;
- relation or entity resolution supported by broader narrative context;
- recovery from curated-memory omission or excessive compression;
- use of an alternative valid source not captured by the annotated evidence set.

**Long-context failure mechanisms to test**

- localisation failure despite source presence;
- reduced attention to evidence in the middle of the prompt;
- competition among repeated entities, similar events, or multiple temporal states;
- preference for an obsolete state over a later update;
- cross-session ordering or multi-hop composition failure;
- excessive caution caused by apparently conflicting context;
- under-answering, over-answering, or fine-grained attribute omission;
- semantically correct but more explanatory wording that lowers token Precision or F1.

**Calculations**

- four-quadrant counts against each E1–E7 comparator and against the descriptive any-selective view;
- reuse the RQ4 Full Context/selective repair and harm quadrants by category,
  while limiting new causal mechanism review to the 14 unique Full Context
  errors; do not manufacture a repair-cause label from the oracle-style
  any-selective comparison;
- relative position of answer-bearing turns in the full prompt;
- distance between required multi-hop or temporal evidence items;
- number of competing mentions and temporal states;
- answer length and lexical–semantic disagreement within each quadrant;
- selective evidence state for Full-Context-only and selective-only cases.

Evidence-position and cross-session-span calculations use only the 58 evidence-eligible questions. The Full Context history length is fixed for this conversation and is reported once as a system property, not used as a within-run predictor. Full Context source visibility by construction is not reported as Evidence Recall of 1.0. A failed Full Context answer is not labelled a long-context localisation failure unless the location and competing-context evidence support that conclusion.

**Required downstream outputs**

- **Table 5.24, Panels A--B:** final-input sufficiency and demonstrated packaging loss;
- **Table 5.25:** Answerer outcomes within sufficient-input errors;
- **Table 5.26:** E7 fusion outcome states;
- **Tables 5.27--5.28:** Full Context category results and evidence-position diagnostics;
- evidence-state × answer-outcome conversion matrix;
- E7 parent-sufficiency matrix;
- Full Context versus selective diagnostic-state matrix;
- category and backbone breakdowns with explicit denominators.

**Formal Section 5.6.4 completion record (25 October 2026).** The downstream
audit classified all 205 E1--E6 Strict-noncorrect paths and published 205
evidence-sufficiency rows, 205 packaging rows, 205 Answerer-conversion rows,
120 exact E7 fusion rows, and the updated 250-row state register. Of the 205
selective errors, 88 have sufficient final input, 111 are insufficient, and
six are indeterminate. Nine paths have demonstrated relevant packaging loss;
among the 88 sufficient-input errors, 56 have an explicit Answerer failure and
32 remain evaluation-sensitive or indeterminate. E7 produces 85 Preserve,
four Repair, eight Harm, and 23 Unresolved outcomes, with exact parent-item
preservation in all 120 paths. This phase passed under audit ID
`rq5-downstream-audit-dea568099f1ba5aaca800c529685f079339fd06da20d3a6ead97e6bb07aa13f4`.
The separate Full Context audit validates all 60 source records against their
frozen Stage A identities, reviews all 14 Strict-noncorrect answers, preserves
the 60-question denominator despite 420 pairwise comparisons, and publishes
58 explicitly turn-ordinal-based evidence-position rows. Full Context is
Strict-correct on 46/60 questions; nine of its 14 errors have sufficient
complete-history input. This phase passed under audit ID
`rq5-full-context-audit-afb779c4dce7248c980e03f8c5e9b977dd846ce362d5ccfcd9e44fa7bd2736e4`.
Both phases are offline, text-free in their public tables, and leave final
primary-cause attribution pending. The durable method, denominators, results,
limits, and output inventory are recorded in
`docs/analysis/chapter5-rq5-downstream-audit-process-and-results.md`.

### 5.6.5 Evaluation Disagreement and Metric Sensitivity

This section treats evaluation disagreement as a substantive diagnostic problem rather than a brief caveat.

#### 5.6.5.1 Do Token F1 and Semantic Evaluation Measure the Same Outcome?

Establish how strongly Token F1 tracks the frozen LLM judge labels across all 900 answers. Report the Precision, Recall, and F1 distributions by Correct, Partial, and Incorrect label, and make clear that positive association does not make the evaluators interchangeable.

#### 5.6.5.2 Why Do Semantically Correct Answers Receive Very Low F1?

Identify lexical under-credit caused by supported elaboration, date or temporal normalisation, and semantic paraphrase. Use answer/reference length only as supporting association, not as an isolated causal explanation.

#### 5.6.5.3 Why Can Partial or Incorrect Answers Retain Token Credit?

Separate genuinely incomplete Partial answers from reference-scope or granularity cases. Identify lexical over-credit where an Incorrect answer repeats expected words but has the wrong entity, relation, count, polarity, time, or conclusion. Explain why gold source locators are not a complete semantic rubric.

#### 5.6.5.4 How Sensitive Is Semantic Judging Near the Decision Boundary?

Keep this check deliberately bounded. Inspect materially similar answers that cross the `Correct`/`Partial` boundary, especially temporal-granularity and secondary-qualifier cases. Exact duplicate-input consistency may be reported, but one frozen LLM judge run cannot establish inter-judge reliability.

#### 5.6.5.5 Do Evaluation-Sensitive Cases Change the Architectural Conclusions?

Run a conservative paired stress test after excluding every flagged evaluation-sensitive question. Report which F1 and Strict directions remain stable, identify the few small margins that change direction, and state explicitly that this diagnostic exclusion is not a corrected official score.

**Required calculations and outputs**

- full cross-tabulation of LLM-judge labels against Precision, Recall, and F1 distributions;
- deterministic diagnostic sets for Correct/low-F1, Incorrect/non-trivial-F1, Partial extremes, and same-question label inconsistencies;
- counts of lexical under-credit, lexical over-credit, reference limitation, annotation limitation, judge-sensitive, genuine partial, and unresolved cases;
- **Tables 5.29--5.30:** Token-score distributions and reviewed evaluation-disagreement causes;
- **Figure 5.8:** sequential-colour Token F1 distribution within each frozen LLM judge label, with exact counts and within-label percentages;
- a sensitivity statement showing whether the principal architectural conclusions survive after evaluation-sensitive cases are flagged.

The official token and LLM-judge scores remain unchanged. Trace-grounded sensitivity analysis supplies interpretation; it does not silently replace the frozen evaluation protocol.

**Formal Section 5.6.5 completion record (25 October 2026).** The offline
audit covers all 900 frozen answers and preserves the 650/74/176
Correct/Partial/Incorrect label totals. It reviews four deterministic tails:
92 Correct answers below F1 0.10, 31 Partial answers below 0.10, 11 Partial
answers at or above 0.50, and 34 Incorrect answers at or above 0.10. Of the
92 Correct/low-F1 rows, 87 are lexical under-credit: 41 supported elaboration,
24 date or temporal normalisation, and 22 semantic paraphrase. Across the 42
Partial extremes, 22 are genuinely incomplete and 20 are reference- or
boundary-sensitive. Among the 34 Incorrect/non-trivial-F1 rows, 18 are clear
lexical over-credit and 16 expose source/reference relation conflicts. Eighty
exact duplicate-input groups covering 305 records have zero label conflicts;
near-boundary sensitivity is concentrated in two question families and is
reported only as a limitation. A conservative exclusion of nine
evaluation-sensitive questions preserves F1 direction in all 17 checked
architecture contrasts and Strict direction in 15. The durable method,
results, and limits are recorded in
`docs/analysis/chapter5-rq5-evaluation-audit-process-and-results.md`; the
machine-readable source of truth is
`artifacts/chapter5-main60-analysis-v1/rq5-evaluation-audit/`, which passed
under audit ID
`rq5-eval-audit-8937008b098d65d7f7a30ae1a290b7454aadbe6b738c9812059d1497f4b001f4`.

### 5.6.6 Integrated Bottleneck Decomposition and Answer to RQ5

This final RQ5 section integrates the Storage, Retrieval, Packaging, Answerer,
E7, Full Context, and evaluation findings. Each of the 250 Strict-noncorrect
paths receives exactly one primary attribution. The primary attribution is the
earliest breakpoint supported by the available trace. Later or interacting
mechanisms remain visible as non-exclusive co-occurrences.

The analysis uses the condition-specific information chains rather than
forcing every architecture into one artificial pipeline:

- E1--E6: Storage → Retrieval/selection → Packaging → Answerer;
- E7: parent upstream paths → deterministic fusion → Answerer;
- Full Context: full-history localisation/competition → Answerer.

Evaluation-sensitive and mixed/indeterminate are terminal attribution
outcomes. They are not physical pipeline components.

#### 5.6.6.1 Primary Root-Cause Distribution

**Question.** At which supported stage does each Strict-noncorrect path first
break?

**Method.** Apply the following conservative precedence rule:

1. assign Storage only when a store-specific omission or distortion is
   directly demonstrated;
2. assign Retrieval only when an acquisition, observation, or selection break
   is accompanied by insufficient final evidence and no sufficient alternative
   support;
3. assign Packaging when complete observation is followed by directly
   demonstrated relevant-item loss;
4. assign Answerer when the final input is sufficient but the answer misuses it
   or abstains without support;
5. assign Long Context when Full Context review shows missed relevant content,
   distractor confusion, or temporal confusion before the later Answerer error;
6. assign Evaluation-sensitive when bounded review explicitly supports that
   interpretation and no valid earlier breakpoint takes precedence. A gold
   source whose entity conflicts with the question/reference cannot support a
   Retrieval-failure claim, because “missing” that locator is not a valid test
   of access to the requested fact;
7. otherwise retain Mixed or Indeterminate.

**Required result.** Report the complete 250-row distribution and a second
view conditional on the resolved attributions. Also report the resolved
system-internal subset after excluding Evaluation-sensitive rows. Keep every
Mixed/Indeterminate row visible rather than redistributing it.

**Required breakdowns.** Show the distribution for selective retrieval, E7,
and Full Context, and for R1, R2, and R3 error paths. These denominators are
error-path denominators, not accuracy denominators.

#### 5.6.6.2 Co-occurring Mechanisms

**Question.** Which supported mechanisms occur together even when only one is
the earliest primary breakpoint?

**Method.** Count mechanism incidence non-exclusively. An error may therefore
appear in several mechanism groups. Report at least:

- annotated retrieval attrition;
- demonstrated Packaging loss and possible noise/order pressure separately;
- explicit Answerer misuse or unsupported abstention;
- long-context localisation or interference;
- explicit evaluation sensitivity;
- shared representation insufficiency;
- E7 Harm with exact parent-item preservation.

The incidence counts must not be summed to 250. E7 Harm is an outcome
co-occurrence, not automatic evidence of fusion causation. Likewise, the 12
shared representation limitations are not S1-, S2-, or S3-specific storage
failures.

#### 5.6.6.3 Representative Cases and Final Answer to RQ5

Use six compact cases to illustrate distinct mechanisms without replacing the
full distribution:

1. an R1 path with sufficient evidence but an Answerer utilisation failure;
2. an R2 retrieval break;
3. an R3 selected-to-bundle Packaging loss;
4. a source/reference entity mismatch that invalidates a simple pipeline
   attribution;
5. an E7 Harm outcome with exact parent-item preservation;
6. a Full Context localisation or interference failure.

The R1 example should be a sufficient-evidence Answerer failure, not a forced
R1 Retrieval example: the only machine-labelled R1 Retrieval candidates share
one question whose annotated source refers to a different entity.

The final answer to RQ5 should state:

- the largest resolved system-internal bottleneck;
- the second-largest resolved system-internal bottleneck;
- why the bottleneck differs across R1, R2, R3, E7, and Full Context;
- why no store-specific primary failure or deterministic-fusion primary
  failure is supported;
- how evaluation sensitivity affects individual cases without overturning the
  earlier architectural results;
- the size and meaning of the Mixed/Indeterminate share.

**Main-text outputs**

- **Figure 5.9:** integrated primary-cause distribution for all 250
  non-Correct paths and the 123 confirmed system-internal failures;
- **Table 5.31, Panel A:** mutually exclusive primary root-cause distribution;
- **Table 5.31, Panel B:** non-exclusive co-occurring mechanism incidence;
- **Table 5.32:** six representative end-to-end cases;
- references back to **Tables 5.29--5.30** for the detailed evaluation audit.

**Interpretation boundaries**

- A storage or retrieval label requires direct trace evidence, not an aggregate
  score difference.
- All-hit is neither automatically sufficient nor automatically necessary for
  answer correctness.
- Full Context failure does not by itself prove generic lost-in-the-middle
  behaviour.
- E7 Harm does not by itself prove a defect in the fusion operation.
- Absence from the bounded evaluation screen does not establish evaluation
  agreement.
- When the records do not distinguish two stages, retain Mixed or
  Indeterminate.

**Formal Section 5.6.6 completion record (26 October 2026).** The offline
integration assigns one primary stage to all 250 Strict-noncorrect paths while
preserving secondary mechanisms. A trace-level representative-case review
identified a necessary attribution guard: source/reference entity mismatch
invalidates Retrieval-failure claims based on the misaligned gold locator. The
corrected primary counts are: Storage 0, Retrieval 42, Packaging 7, Answerer
68, Fusion/Long Context 6, Evaluation-sensitive 53, and
Mixed/Indeterminate 74. There are 176 resolved attributions. Across them,
Answerer is the largest class (68; 38.6%), Evaluation-sensitive is second (53;
30.1%), and Retrieval is third (42; 23.9%). Restricting the denominator to 123
resolved system-internal breakpoints, Answerer is the dominant bottleneck (68;
55.3%), followed by Retrieval (42; 34.1%), Packaging (7; 5.7%), and Long
Context (6; 4.9%). The non-exclusive mechanism audit records 76
retrieval-attrition paths, nine demonstrated Packaging losses, 42 possible
noise/order cases, 74 explicit Answerer failures, six long-context failures,
74 explicitly supported evaluation-sensitive paths, and 12 shared
representation insufficiencies. E7 has eight Harm outcomes but zero supported
deterministic-fusion primary failures because the parent EvidenceItems were
preserved exactly. The durable method and results are recorded in
`docs/analysis/chapter5-rq5-integrated-process-and-results.md`; the
machine-readable source of truth is
`artifacts/chapter5-main60-analysis-v1/rq5-integrated-bottleneck/`, which passed
independent reconstruction and hash verification under audit ID
`rq5-integrated-audit-7c68cdb9c619409de661590729605b9c2d9c650003db223f8651f8de0c48eaf2`.
All 10 integration and causal-guard tests passed. No API or network call was
made, and no frozen answer or score was changed.

---

## 5.7 RQ6: Quality, Cost, and Practical System Choice

### 5.7.1 Observed Quality–Cost and Maintenance Trade-offs

**Purpose**

Determine which quality gains required meaningful extra resources and which conditions are dominated by cheaper alternatives.

**Cost views to report**

- one-time S2/S3 construction cost;
- successful query-time retrieval and Answerer cost;
- failures, retries, recovery, and format-repair cost;
- LLM judge cost as evaluation-only expenditure;
- E7 experiment-recorded and reconstructed online cost;
- Full Context input cost despite its lack of retrieval calls.

**Required analysis**

- compare calls, input/output/total tokens, latency, and available monetary cost separately;
- do not combine unlike dimensions into one arbitrary scalar;
- prepare the quality and resource fields needed for the Pareto analysis;
- examine build-cost amortisation under different query volumes;
- treat small latency differences cautiously because of remote-service variation.

**Required output**

- **Table 5.33:** Build, query, recovery, and evaluation cost table;
- conditional amortisation scenarios for S2 and S3.

**Interpretation boundary**

Unmeasured long-term maintenance cannot be reported as an observed numeric cost. It should remain a qualitative deployment consideration.

### 5.7.2 Pareto-Efficient Conditions

**Purpose**

Identify conditions that are not strictly dominated in the observed quality–cost space.

**Required analysis**

- plot Strict Accuracy, Soft Semantic Score, and F1 against query tokens and model calls;
- identify dominated and non-dominated conditions separately by backbone;
- incorporate E7's two-parent online cost and Full Context's long input cost;
- keep latency descriptive because complete comparable latency is unavailable for the main E1–E7 records.

**Required output**

- **Figure 5.10:** Quality–cost Pareto plots by backbone model;
- Pareto membership table and interpretation boundary.

### 5.7.3 Scenario-Based System Selection

**Purpose**

Translate the empirical results into conditional system choices rather than one context-free ranking.

**Decision scenarios**

- highest complete semantic quality;
- strongest LoCoMo lexical performance;
- lowest online cost;
- lowest latency;
- strongest cross-backbone stability;
- best quality–cost balance;
- best support for multi-hop or temporal questions;
- strongest provenance and auditability;
- diagnostic or failure-recovery use of E7 or Full Context.

**Evidence required for each recommendation**

1. primary quality metric and paired effect;
2. question-level distribution and uncertainty;
3. cross-backbone stability;
4. principal error mechanism;
5. query and construction cost;
6. applicable question types and risks.

**Required output**

- **Table 5.34:** Scenario–condition decision matrix;
- short selection tree;
- separate quality-first, cost-first, and audit-first recommendations.

**Interpretation boundary**

If no condition is consistently best, the report should state that the evidence supports conditional selection. It should not manufacture a single champion.

### Formal RQ6 execution record (completed)

RQ6 has now been executed as an audited offline synthesis over all 900 frozen
Main-60 answer paths. The analysis keeps S1--S3 construction, successful-query,
formal recovery, and LLM-judge costs in separate accounts; reconstructs E7's
online cost without double-counting either parent Answerer; computes Pareto
membership by backbone for Strict, Soft, and Token F1; and evaluates build-cost
amortisation at 60, 600, and 6,000 queries. Token usage is the primary cost
proxy. Comparable E1--E7 latency and monetary prices remain unavailable.

The direct result is conditional. E2 is the minimum-token path under both
backbones. For Qwen, E3 is the strongest balance after the modest S2 build is
amortised, while E5 is the semantic-quality maximum at much higher construction
and query cost. For DeepSeek, E7 is the strongest selective query-time
quality--cost compromise when S3 already exists: it matches E1's 0.750 Strict
Accuracy with 74.3% fewer successful-query tokens. E1 remains the no-build,
auditable DeepSeek quality baseline. Full Context has the highest observed
DeepSeek-family Strict and Soft scores, but its one-question Strict lead,
lower F1, fixed 30-session setting, and served-model mismatch make it a
diagnostic or recovery path rather than a universal replacement for retrieval.

S2/E3 crosses E1 in cumulative token accounting after 46 Qwen or 35 DeepSeek
queries. S3-backed E6/E7 crosses expensive E1 only after 187--324 repeated
queries, never becomes cheaper than E2, and E5 has no token break-even. Formal
recovery auditing finds 41 failed attempts; 39 token-bearing artifacts account
for 10,126,358 additional tokens, while two DNS attempts remain usage-unknown.
All observed failures occur on R1 conditions. Together with RQ5's 68 Answerer
versus 42 Retrieval internal failures, this shows that adding retrieval work is
not automatically the most efficient correction.

The durable method and results are recorded in
`docs/analysis/chapter5-rq6-process-and-results.md`. The machine-readable source
of truth is `artifacts/chapter5-main60-analysis-v1/rq6-quality-cost/`, which
passed independent reconstruction and hash verification under audit ID
`rq6-audit-49036128531db43c3bcb83e8e7f2f8f75b6258ebbfc0dda01899dd20352a1f25`.
All nine RQ6-specific tests and the complete 161-test Chapter 5 regression suite
passed. No API or network call was made, and no formal answer or score was
changed.

## 5.8 Chapter Summary and Consolidated Answers to RQ1–RQ6

**Purpose**

Close the empirical chapter by answering every research question directly and then reducing the six answers to a small set of cross-cutting conclusions. Keep the section to approximately 0.5--1 page. Do not repeat the detailed results already reported in Sections 5.2--5.7.

### 5.8.1 Consolidated Answers to RQ1--RQ6

Use one compact row per research question:

| RQ | Direct answer | Strongest evidence | Main boundary |
|---|---|---|---|

Each row should do only three things:

1. state the direct answer in one sentence;
2. name the strongest quantitative or trace-based support;
3. state the main condition or limitation on that answer.

The six rows should cover:

- **RQ1:** the conditional effects of storage, retrieval, and their interaction;
- **RQ2:** which effects transfer across Qwen and DeepSeek and which are backbone-dependent;
- **RQ3:** the benefit and remaining limitation of E7 dual-source fusion;
- **RQ4:** why Full Context is useful but does not dominate selective retrieval;
- **RQ5:** the relative importance of Answerer utilisation, retrieval, and other failure mechanisms;
- **RQ6:** why practical system choice must be conditional on quality, cost, and available memory assets.

**Required output:** **Table 5.37. Consolidated answers to RQ1--RQ6.** The report already uses Tables 5.1--5.36, so the earlier placeholder number 5.35 must not be reused.

### 5.8.2 Overall Synthesis and Transition

Reduce the six RQ answers to three short, connected conclusions:

1. **Architecture effects are conditional.** Storage representation, retrieval design, and the backbone model must be considered jointly. No selective-retrieval condition dominates every metric.
2. **Evidence access and evidence utilisation are distinct bottlenecks.** Better coverage from curated memory, fusion, or Full Context does not guarantee that the Answerer will use the available evidence correctly.
3. **Deployment requires conditional routing.** The preferred condition depends on whether the application prioritises semantic quality, lexical precision, query cost, construction amortisation, provenance, or diagnostic coverage.

End with one short transition paragraph. Chapter 5 establishes bounded empirical findings for Main-60 and the implemented systems. Chapter 6 should relate those findings to prior work, limitations, external validity, and broader design implications.

**Do not repeat in Section 5.8**

- the E1--E7 definition table already provided in Section 5.1;
- complete condition scores, intervals, or category tables;
- repair/harm counts and representative cases;
- the full root-cause distribution;
- the Pareto and cost-accounting calculations;
- experimental methods or metric definitions.

**Interpretation boundary**

Clearly distinguish direct measurements, mechanism interpretations supported by manual review, and hypotheses that still require additional conversations or experiments.

---

## Minimum main-text figure and table set

### Tables

1. Table 5.1 — Complete quality and evidence results;
2. Table 5.2 — Lexical–semantic agreement;
3. Table 5.3 — Storage-organisation effects on primary answer quality;
4. Table 5.4 — Storage-organisation lexical and evidence diagnostics;
5. Table 5.5 — Retrieval-system effects on primary answer quality;
6. Table 5.6 — Retrieval-system lexical, evidence, and query-cost diagnostics;
7. Table 5.7 — E1–E4 descriptive condition means;
8. Table 5.8 — Storage–retrieval interaction estimates;
9. Table 5.9 — Curated-memory effects on primary answer quality;
10. Table 5.10 — Curated-memory lexical, evidence, and bundle diagnostics;
11. Table 5.11 — Evidence-to-answer diagnostic cells;
12. Table 5.12 — RQ1 architecture evidence matrix;
13. Table 5.13 — Cross-backbone condition comparison and architecture-stability matrix (Panels A–B);
14. Table 5.14 — E7 effects and fusion outcome states;
15. Table 5.15 — Overall Full Context and DeepSeek E1–E7 quality results;
16. Table 5.16 — Paired Full Context effects and Strict outcome quadrants (Panels A–B);
17. Table 5.17 — Full Context and E7 category results and quadrants (Panels A–B);
18. Table 5.18 — Storage audit evidence (Panels A–D);
19. Table 5.19 — E5/E6 outcomes conditional on S3 reference support;
20. Table 5.20 — Storage states of E1–E6 Strict-noncorrect paths;
21. Table 5.21 — Annotated-evidence loss location among eligible errors;
22. Table 5.22 — R1–R3 retrieval, answer-quality, and cost profiles;
23. Table 5.23 — Task-specific evidence-access recommendations;
24. Table 5.24 — Final-input sufficiency and demonstrated packaging loss (Panels A–B);
25. Table 5.25 — Answerer outcomes within sufficient-input errors;
26. Table 5.26 — E7 fusion outcome states;
27. Table 5.27 — Full Context category results;
28. Table 5.28 — Full Context evidence-position diagnostics;
29. Table 5.29 — Token-score distributions by LLM judge label;
30. Table 5.30 — Reviewed evaluation-disagreement causes;
31. Table 5.31, Panels A–B — Integrated primary root-cause and co-occurring-mechanism summary;
32. Table 5.32 — Representative end-to-end cases;
33. Table 5.33 — Observed build, query, recovery, and evaluation costs;
34. Table 5.34 — Scenario-based decision matrix;
35. Table 5.35 — Answers to RQ1–RQ6.

### Figures

1. Figure 5.1 — Storage–retrieval interaction;
2. Figure 5.2 — Agent-Curated Memory architecture-effect profile;
3. Figure 5.3 — Cross-backbone stability of architecture effects;
4. Figure 5.4 — E7 dual-source composition;
5. Figure 5.5 — E7 repair/preserve/harm/unresolved flow;
6. Figure 5.6 — Storage states of E1–E6 Strict-noncorrect paths;
7. Figure 5.7 — Annotated-evidence state of evidence-eligible E1–E6 Strict-error paths;
8. Figure 5.8 — Token F1 distribution within each frozen LLM judge label;
9. Figure 5.9 — Integrated bottleneck decomposition for all non-Correct paths and confirmed system-internal failures;
10. Figure 5.10 — Quality–cost Pareto frontier.

If space becomes constrained, combine Figures 5.1 and 5.2 into a multi-panel effect plot, and move complete metric or category tables to the appendices.

## Main text versus appendix

### Keep in Chapter 5

- exact aggregate values needed to support claims;
- principal paired contrasts and their distributions;
- selected auxiliary intervals;
- the compact RQ2 cross-backbone stability matrix;
- E7 outcome states;
- Full Context four-quadrant results;
- high-level root-cause distribution;
- Pareto and decision summaries;
- four to eight representative cases.

### Move to Appendix H

- complete paired-contrast tables;
- bootstrap settings and complete interval outputs;
- category-level supplementary analyses;
- all judge-label transitions and optional tests;
- supplementary DID, E6−E4, and any optional cross-backbone interval outputs;
- multiple-comparison details where used;
- complete cost calculations and amortisation assumptions.

### Move to Appendix I

- per-question result table;
- extended error codebook application;
- complete root-cause casebook;
- additional trace, evidence, and scoring disagreement examples.

## Required evidence status before drafting the final prose

The 900 candidate answers and their two answer-evaluation families are available. Before writing result claims, the analysis should also produce and verify:

1. one unified question-level analysis table;
2. all principal paired contrasts;
3. category labels and evidence eligibility;
4. evidence-access metrics for E1–E7;
5. E7 state transitions and parent-bundle overlap;
6. Full Context paired outcome quadrants;
7. process and cost records under the Chapter 4 accounting rules;
8. root-cause labels and the representative case set.

The prose should be written after these artefacts are frozen. This prevents the report from selecting only the comparisons or examples that support an early narrative.

## Final writing rule

Every major claim in Chapter 5 should allow the reader to answer:

- What was compared?
- Was the comparison paired by question?
- How large and how consistent was the difference?
- Did token and semantic metrics agree?
- Did evidence access change in the same direction?
- Was the pattern stable across backbone models?
- What process or case evidence supports the explanation?
- What did the improvement cost?
- What is the narrowest defensible conclusion?
