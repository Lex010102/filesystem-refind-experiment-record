# Chapter 5 Stage D Process and Results Record

## Status and purpose

Stage D is complete and formally audited. It explains the already validated
Stage B and Stage C effects through four bounded views: Evidence-to-answer
conversion, category-level heterogeneity, process behaviour, and a fixed
trace-review sample. It does not yet write the final RQ1 conclusion; that
reconciliation belongs to Stage E.

The machine-readable source of truth is
`artifacts/chapter5-main60-analysis-v1/stage-d/`. The automatic intermediate
artifact remains frozen at
`artifacts/chapter5-main60-analysis-v1/stage-d-auto/`.

No API was called. No formal answer, retrieval trace, score, Judge result, or
Stage A--C artifact was changed.

## Frozen lineage and scope

- Stage A audit ID:
  `stage-a-audit-5f55ec411f097df7206fdae5e71742641aa8868b4128ac32262f034877a1d7f3`.
- Stage B audit ID:
  `stage-b-audit-2c5061c3db5cba00f099648963eaa2175d1136954e4cf673720423e7ffed6932`.
- Stage C audit ID:
  `stage-c-audit-a199de52d8b0011d837334e6dbf37bbfac446653753b5b74a35732ae32da1a31`.
- Stage D automatic audit ID:
  `stage-d-auto-audit-9cfae91b0639df31b427d2052798dfe30e0f5cb8b41c9996ae75448e6fdd4a4f`.
- Stage D final audit ID:
  `stage-d-final-audit-9f23da2369af468867b7f6ffdbdc040ebee67fac59820d59f0763a3ccd132640`.
- Final audit SHA-256:
  `3244cc96a43af998217730964bc41613151819e57f6aae413f808e0d6fc7c2f0`.

All analyses use the unified Main-60 test set. Answer outcomes use 60
questions. Evidence outcomes use the fixed 58-question eligible mask, and
multi-source coverage uses the fixed 19-question subset. Category
denominators are C1=13, C2=13, C3=7, and C4=27 for answer metrics, with C3=5
for Evidence metrics. No question-construction split is used.

The main simple comparisons are E3-E1, E4-E2, E2-E1, E4-E3, E6-E5, E5-E3,
and E6-E4. The storage--retrieval interaction is retained separately as
`(E4-E2)-(E3-E1)`. E5-E1 and E6-E2 remain appendix-only sensitivity
comparisons. All values are calculated separately within each backbone.

## Two-phase execution

Stage D used two publication gates.

1. The automatic phase reconstructed every comparison from the frozen Stage
   A--C data, generated identifier-only review candidates, and published
   `STAGE-D-AUTO.PASSED` only after byte-level audit.
2. The bounded-review phase inspected exactly the 24 frozen candidates. It
   verified every declared source path and hash, copied no raw question,
   answer, Evidence, or Judge-rationale text, and atomically published
   `STAGE-D.PASSED` only after a second independent audit.

The final artifact contains every automatic file byte-for-byte, plus the
review register, casebook, review schema, source manifest, final audit, and
passed marker. Its inherited `README.md` therefore still documents the
automatic subphase; `final-audit.json` and `STAGE-D.PASSED` are the
authoritative final-phase status files.

## Published automatic outputs

| Output | Rows |
|---|---:|
| Comparison register | 20 |
| Evidence-to-answer question rows | 812 |
| Conversion matrices | 756 |
| Conversion summaries | 84 |
| All-hit--Strict transitions | 126 |
| Any-hit--Strict transitions | 126 |
| Multi-source coverage transitions | 252 |
| Category effects | 224 |
| Category interactions | 32 |
| Appendix sensitivity category effects | 64 |
| Process condition summaries | 312 |
| Process paired summaries | 468 |
| Frozen trace-review candidates | 24 |

## Evidence-to-answer conversion

The primary conversion table crosses the direction of Evidence Recall change
with the direction of Strict outcome change on the same 58 eligible
questions. The four compact cells below are derived from the complete 3x3
matrix; they do not exhaust the matrix and must not be added together as a
denominator.

| Backbone | Comparison | Evidence up and Strict up | Evidence up, Strict not up | Evidence same, Strict up | Evidence down without Strict harm |
|---|---|---:|---:|---:|---:|
| Qwen | E3-E1 | 0 | 4 | 5 | 3 |
| DeepSeek | E3-E1 | 0 | 1 | 1 | 4 |
| Qwen | E4-E2 | 2 | 2 | 3 | 2 |
| DeepSeek | E4-E2 | 0 | 4 | 1 | 3 |
| Qwen | E2-E1 | 0 | 9 | 2 | 6 |
| DeepSeek | E2-E1 | 0 | 5 | 3 | 4 |
| Qwen | E4-E3 | 1 | 6 | 3 | 4 |
| DeepSeek | E4-E3 | 0 | 8 | 2 | 7 |
| Qwen | E6-E5 | 0 | 1 | 2 | 5 |
| DeepSeek | E6-E5 | 0 | 2 | 2 | 10 |

The central descriptive observation is that improved annotated-source
coverage often did not convert into a Strict improvement, while some Strict
repairs occurred without improved Evidence Recall. Conversely, lower
Evidence Recall did not always harm the final answer. This indicates that
annotated-evidence access and answer correctness are related but not
interchangeable. The table is associational; it does not prove that an
Evidence change caused the answer change.

## Category-level mechanism observations

Category effects are descriptive only. No new category-level bootstrap or
significance claim was made.

- Under Qwen, the positive E3-E1 aggregate is concentrated in C2 temporal
  questions: C2 changes by +0.1994 F1, +0.3077 Strict, and +0.1923 Soft,
  whereas C4 Strict changes by -0.0741. The storage result is therefore not a
  uniform gain across categories.
- Under DeepSeek, C2 E3-E1 increases F1 by +0.0452, while Strict and Soft each
  decrease by -0.1538. This is a within-backbone descriptive pattern; formal
  cross-backbone inference is deferred to RQ2.
- The R2 comparisons E2-E1 and E4-E3 are especially weak on C2. Qwen E4-E3
  changes by -0.1373 F1 and -0.3077 Strict; DeepSeek E4-E3 changes by -0.2269
  F1 and -0.1538 Strict. C3 contains only seven answer questions and five
  Evidence-eligible questions, so its positive DeepSeek answer deltas require
  particular caution.
- E6-E5 reduces Evidence Recall in every category under both backbones. The
  largest DeepSeek category decreases occur in C3 (-0.4000) and C2
  (-0.2692); semantic effects are also non-positive across the category
  cells.
- E5-E3 increases category-level Evidence Recall broadly, but its semantic
  effects are heterogeneous. E6-E4 is also category-dependent rather than a
  uniform complete-system improvement.
- The category interaction table shows different signs and magnitudes across
  C1--C4. It is retained as descriptive mechanism evidence, not a new
  category-level inferential result.

## Process observations

Stage D keeps native process units separate. R1 provider rounds and
filesystem tool calls are not treated as equivalent to R2/R3 ranked-retrieval
actions.

- R1 conditions use more iterative model calls than R2/R3 conditions. Mean
  query-model calls range from 8.05 to 12.50 for Qwen R1 conditions and 8.90
  to 12.98 for DeepSeek R1 conditions, compared with approximately 4.83--5.00
  for R2/R3 conditions.
- Query-stage token totals are consequently much larger for the agentic R1
  paths. This is a process description only; the quality--cost ranking is
  reserved for RQ6.
- R2/R3 produce larger Answerer inputs in several comparisons, which is
  consistent with their larger EvidenceBundles. Larger bundles are not by
  themselves evidence of better source coverage or better answers.
- One Answerer call is expected per completed answer. Recorded means above
  one reflect preserved retry attempts rather than a different answering
  contract.
- Native per-answer latency is unavailable for E1--E7 and remains `N/A`.
  Failed-attempt tokens are also unavailable as a quantity separate from
  successful query totals. Neither value was inferred from timestamps or
  silently estimated.

## Bounded trace review

The review register contains 24 fixed slots: four RQ1 modules multiplied by
two backbones and three intended roles (repair, harm, and counterexample).
The sample covers all four categories and verifies 142 unique source
bindings. No candidate was replaced after source content was inspected.

| Sample property | Count |
|---|---:|
| Qwen cases | 12 |
| DeepSeek cases | 12 |
| Intended repair slots | 8 |
| Intended harm slots | 8 |
| Intended counterexample slots | 8 |
| Observed repair | 4 |
| Observed harm | 5 |
| Observed counterexample | 8 |
| Observed metric disagreement | 7 |
| High-confidence interpretations | 15 |
| Medium-confidence interpretations | 9 |

The primary-mechanism counts in this selected sample are: metric disagreement
8, alternative valid evidence 7, local expansion 4, evidence utilisation 4,
and query choice 1. These counts describe the deliberately selected sample;
they are not prevalence estimates for all questions.

The reviewed cases support five bounded observations.

1. Several apparent repairs or harms arise from token/semantic or
   Judge-boundary disagreement rather than a clear storage or retrieval
   change, especially for temporally phrased answers and non-exhaustive
   references.
2. Annotated Evidence Recall can understate sufficient access when a bundle
   contains an alternative valid source, and it can overstate sufficiency
   when the annotated turn does not contain every attribute required by the
   reference answer.
3. Some R2/R3 harms are consistent with local-expansion or selection failures:
   a relevant region is reached, but the adjacent decisive item is not
   retained in the final EvidenceBundle.
4. Some answer failures occur after sufficient evidence survives storage,
   retrieval, packaging, and the budget. These cases are most consistent
   with partial or failed Answerer utilisation, sometimes in a
   distractor-heavy bundle.
5. A larger or more complete EvidenceBundle can saturate rather than improve
   the answer when the baseline bundle already contains sufficient evidence.

These case findings explain selected paired outcomes. They do not constitute
the global failure-stage census required by RQ5.

## Audit and verification

The final audit verified:

- exact Stage A--D lineage and source hashes;
- the fixed 60/58/19 denominators and category subtotals;
- comparison direction, role, and main/interaction/appendix separation;
- exact agreement with Stage B and Stage C paired effects;
- byte-identical preservation of every automatic Stage D file;
- exactly 24 completed frozen reviews with no substitutions or duplicates;
- canonical repository-relative review paths with path traversal and symlink
  rejection;
- absence of raw question, reference-answer, candidate-answer, Evidence,
  Judge-rationale, or secret fields from the published tables;
- marker-to-audit hash consistency and rejection of tampered review,
  automatic, marker, and extra-file content.

The complete Stage A--D test suite ran 40 tests and passed all 40.

## Bounded conclusions carried to Stage E

1. Evidence access and final answer quality do not move in lockstep.
2. Qwen's E3-E1 gain is concentrated in temporal questions rather than being
   a broad category-independent improvement.
3. R2's weaker aggregate outcomes are consistent with both lower annotated
   coverage and selected local selection failures, but the trace sample does
   not establish a single universal cause.
4. R3's larger S3 bundles do not repair its lower Evidence Recall or lower
   semantic outcome relative to R1; selected cases include both local
   selection failure and downstream utilisation failure.
5. Complete-system S3 comparisons remain heterogeneous across category and
   metric, and cannot be interpreted as a pure curation effect.
6. Metric disagreement and annotation coverage limitations are material
   enough that RQ1 should retain token, semantic, and Evidence views rather
   than nominate one metric as a complete explanation.

These are provisional Stage D inputs. Stage E must reconcile them with the
Stage B intervals and Stage C complete-system labels before drafting the final
RQ1 narrative. Cross-backbone inference, E7, Full Context, the global error
census, Pareto analysis, and final system recommendation remain outside Stage
D.
