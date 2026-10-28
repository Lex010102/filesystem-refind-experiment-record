# Chapter 5 RQ1 Stage E Final Audit Protocol

## Purpose

Stage E is the final audit and writing gate for RQ1. It reconciles the frozen Stage B--D results, freezes the exact numbers used in the report, and only then produces the final Section 5.2 prose. It does not rerun an experiment, call an API, rescore an answer, or alter any formal source result.

The protocol version is `chapter5-main60-stage-e-rq1-v1`.

## Frozen scope

RQ1 uses the unified Main-60 test set and E1--E6 only. All effects are calculated within one backbone and use the fixed target-minus-baseline direction.

The six core effects are:

1. E3−E1: storage organisation under R1;
2. E4−E2: storage organisation under R2;
3. E2−E1: R2 versus R1 on S1;
4. E4−E3: R2 versus R1 on S2;
5. `(E4−E2)−(E3−E1)`: storage--retrieval interaction;
6. E6−E5: R3 versus R1 on the same frozen S3 store.

The two main-text descriptive anchors are E5−E3 and E6−E4. E5−E1 and E6−E2 remain appendix sensitivity anchors. Each core effect and main-text anchor is reported separately for Qwen and DeepSeek, giving 16 model-specific main-text result units. These units organise the analysis; they are not treated as 16 independent hypothesis tests.

Stage E excludes E7, Full Context, formal cross-backbone effect comparison, a global error-stage census, Pareto analysis, and final system selection. These belong to RQ2--RQ6.

## Required lineage gates

The builder must independently validate the following frozen artifacts before publishing any Stage E file:

- Stage A master analysis view and `STAGE-A.PASSED`;
- Stage B E1--E4 paired effects, bootstrap intervals, Figure 5.3 input, audit, and `STAGE-B.PASSED`;
- Stage C S3 contrasts, Table 5.3 input, audit, and `STAGE-C.PASSED`;
- Stage D mechanism tables, bounded trace-review register, final audit, and `STAGE-D.PASSED`.

The source hashes, audit identities, condition identities, metric directions, and row counts must match the frozen publications. A lineage mismatch stops the build.

## Denominator and direction contract

- Answer outcomes use `N=60` per condition or contrast.
- Evidence outcomes use the fixed eligible set of `N=58`.
- Multi-source evidence outcomes use `N=19`.
- Category answer denominators are C1/C2/C3/C4 = 13/13/7/27.
- Category evidence denominators are C1/C2/C3/C4 = 13/13/5/27.
- All differences are target minus baseline.
- Precision, Recall, F1, Strict Accuracy, Soft Semantic Score, Evidence Recall, Any-hit, All-hit, and multi-source coverage are higher-is-better.
- Partial Rate is neutral and must be interpreted through the full semantic-label transition table.
- EvidenceBundle length and process measures are descriptive, not quality metrics.

The 60-question answer denominator must never be mixed with the 58-question or 19-question evidence denominators.

## Reconciliation rules

Stage E must freeze and audit:

1. the 16-result-unit register and identification boundary for every unit;
2. condition means and paired effects for Precision, Recall, F1, Strict Accuracy, Partial Rate, Soft Semantic Score, Evidence Recall, Any-hit, All-hit, multi-source coverage, and EvidenceBundle length where applicable;
3. Strict repair, harm, unchanged-correct, and unchanged-not-correct transitions;
4. the existing Stage B bootstrap intervals only: four raw-memory simple effects and the interaction, for F1, Strict, and Soft under both backbones;
5. Evidence-change × answer-change summaries, with an explicit warning that the four compact cells are selected diagnostic cells and do not exhaust the full denominator;
6. descriptive category effects and interaction inputs, without category-level significance claims;
7. process summaries in their native units, keeping R1 rounds/filesystem calls distinct from R2/R3 actions;
8. the byte-identical Figure 5.3 and Table 5.3 machine inputs;
9. the one-time S3 construction record from the frozen S3 manifest, clearly separated from per-question query cost;
10. a display-number register that maps report values to the audited machine-readable source rows.

No new bootstrap interval may be added for E6−E5, a descriptive anchor, a category subset, or a reviewed trace.

## Interpretation controls

The final prose must use the following controls:

- A bootstrap interval describes resampling stability across the observed Main-60 questions. It does not estimate variation across conversations.
- Storage effects are conditional descriptive effects. Their F1 and Strict intervals include or touch zero, so the report must not claim that folder organisation is generally beneficial.
- R1 and R2 are complete retrieval systems. Their contrast cannot be reduced to BM25 or to one controller action.
- E5−E3 and E6−E4 are complete-system anchors. They do not isolate a pure curation effect.
- The bounded 24-case review explains selected mechanisms. Its observed mechanism counts are not prevalence estimates.
- Changes in evidence access and answer quality are associations, not automatic causal explanations.
- The Qwen and DeepSeek estimates may be displayed side by side, but Stage E must not calculate or interpret cross-backbone stability.
- Native E1--E7 per-answer latency and independently attributable failed-attempt tokens remain unavailable. They must stay `N/A`, not be inferred or set to zero.
- Process and construction costs may be described, but cost ranking and whether an increase is "worth it" are deferred to RQ6.

## Publication gate

The formal output directory is `artifacts/chapter5-main60-analysis-v1/stage-e-rq1/`. Publication is atomic. The builder writes `STAGE-E-RQ1.PASSED` only after independent reconstruction verifies:

- all required lineage artifacts;
- all 16 main-text result units;
- target-minus-baseline direction;
- every 60/58/19 and category denominator;
- the unchanged 30-row bootstrap set;
- byte-identical Figure 5.3 and Table 5.3 inputs;
- absence of text-bearing source fields or credentials;
- absence of E7, Full Context, cross-backbone inference, global error census, Pareto ranking, and system recommendation;
- exact hashes for every published Stage E file.

Only after this marker exists may the final English Section 5.2 prose be written from the Stage E display-number register.
