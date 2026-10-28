# Chapter 5 Stage C Process and Results Record

## Status and purpose

Stage C is complete and formally audited. It isolates the pre-declared
Agent-Curated Memory comparisons needed by RQ1 without advancing into the
mechanism analyses reserved for Stage D.

This document is a durable analysis note. The machine-readable source of
truth remains `artifacts/chapter5-main60-analysis-v1/stage-c/`.

## Frozen inputs and lineage

- Stage A input: the complete 720-row `rq1-analysis-view`, covering two
  backbone models, E1–E6, and the same unified Main-60 questions.
- Stage A audit ID:
  `stage-a-audit-5f55ec411f097df7206fdae5e71742641aa8868b4128ac32262f034877a1d7f3`.
- Stage B role: lineage gate and exact E1–E4 condition-summary consistency
  check only. Stage C values were not calculated from Stage B aggregates.
- Stage B audit ID:
  `stage-b-audit-2c5061c3db5cba00f099648963eaa2175d1136954e4cf673720423e7ffed6932`.
- Stage C audit ID:
  `stage-c-audit-a199de52d8b0011d837334e6dbf37bbfac446653753b5b74a35732ae32da1a31`.
- Stage C audit SHA-256:
  `fef87f523a6850c0fd1a7940a1aceb526e2c94f6ff3722d9b400c49ea063ea5a`.

No API was called and no formal answer, retrieval, Judge, or experiment run
was modified.

## Fixed comparison register

All differences use `target − baseline` and are estimated separately within
Qwen and DeepSeek.

| Contrast | Publication role | Permitted interpretation |
|---|---|---|
| E6−E5 | Main core effect | Complete R3-versus-R1 access-system effect on the same frozen S3 store |
| E5−E3 | Main descriptive anchor | S3+R1 versus S2+R1; not a pure curation effect |
| E6−E4 | Main descriptive anchor | S3+R3 versus S2+R2; representation and retrieval both change |
| E5−E1 | Appendix sensitivity | S3+R1 versus S1+R1; not a pure curation effect |
| E6−E2 | Appendix sensitivity | S3+R3 versus S1+R2; representation and retrieval both change |

No additional S3 contrast was introduced after observing the results.

## Calculation contract

- Answer metrics use all 60 questions: token Precision, token Recall, token
  F1, Strict Accuracy, Partial Rate, and Soft Semantic Score.
- Evidence metrics use the fixed 58-question eligible mask: Evidence Recall,
  Any-hit, All-hit, and EvidenceBundle characters.
- Multi-gold-source metrics use the fixed 19-question subset with more than
  one distinct annotated source turn.
- Question-level records are paired by backbone and `question_id`.
- Partial Rate and EvidenceBundle length are neutral metrics. They receive
  increase/same/decrease counts but no quality-oriented win/tie/loss label.
- Strict transitions use `not-correct = partial + incorrect`.
- The complete 3×3 `correct`/`partial`/`incorrect` matrix is retained so that
  Strict transitions do not hide partial-answer movement.
- Stage C deliberately contains no bootstrap, interaction, category,
  Evidence-to-answer conversion, process, cost, trace, cross-backbone, E7,
  Full Context, or final RQ1 computation.

## Published outputs

| Output | Rows |
|---|---:|
| Contrast register | 5 |
| E5/E6 condition summaries | 52 |
| Question-level paired effects | 6,490 |
| Aggregate effects | 130 |
| Strict transitions | 40 |
| Full semantic transitions | 90 |
| Main-text Table 5.3 data | 24 |
| Appendix sensitivity data | 16 |

The builder audited a complete temporary candidate before atomically
publishing the formal directory. A second audit reconstructed every expected
byte from Stage A and the frozen protocol. Numeric-anchor, transition-folding,
scope, identity, and tamper-rejection tests also passed.

## Main Stage C results

| Backbone | Comparison | ΔF1 | ΔStrict | ΔSoft | ΔEvidence Recall | ΔBundle characters |
|---|---|---:|---:|---:|---:|---:|
| Qwen | E6−E5 | −0.0135 | −0.0500 | −0.0583 | −0.0891 | +5,109.1 |
| Qwen | E5−E3 | −0.0463 | +0.0333 | +0.0250 | +0.1034 | +3,034.0 |
| Qwen | E6−E4 | −0.0147 | +0.0333 | +0.0333 | +0.0560 | +4,257.6 |
| DeepSeek | E6−E5 | −0.0364 | −0.0833 | −0.0917 | −0.2371 | +5,457.3 |
| DeepSeek | E5−E3 | −0.0367 | +0.0500 | +0.0417 | +0.1149 | +3,901.2 |
| DeepSeek | E6−E4 | −0.0074 | 0.0000 | 0.0000 | −0.0431 | +2,679.6 |

### Core S3 access comparison: E6−E5

- Qwen Strict transitions: 2 repairs, 5 harms, and 53 ties.
- DeepSeek Strict transitions: 2 repairs, 7 harms, and 51 ties.
- R3 produced much larger bundles but lower Evidence Recall and lower mean
  F1, Strict Accuracy, and Soft Semantic Score under both backbones.
- This supports a bounded statement about the complete R3-versus-R1 access
  systems on S3. It does not isolate BM25, query generation, or one action.

### Main complete-system anchors

- E5−E3 shows the same token–semantic disagreement under both backbones:
  token F1 decreases while Strict Accuracy, Soft Semantic Score, and Evidence
  Recall increase.
- E6−E4 is descriptively backbone-dependent. Qwen gains Strict, Soft, and
  Evidence Recall despite a small F1 loss. DeepSeek has unchanged Strict and
  Soft, a small F1 loss, and lower Evidence Recall.
- These are complete-system observations. They cannot be attributed solely
  to curation because the compared representations differ in wording,
  granularity, organisation, and provenance; E6−E4 also changes retrieval.

### Appendix sensitivity anchors

- Qwen E5−E1: ΔF1 −0.0001, ΔStrict +0.0667, ΔSoft +0.0500, and
  ΔEvidence Recall +0.1106.
- Qwen E6−E2: ΔF1 −0.0218, ΔStrict +0.0667, ΔSoft +0.0417, and
  ΔEvidence Recall +0.0546.
- DeepSeek E5−E1: ΔF1 −0.0409, ΔStrict 0.0000, ΔSoft −0.0083, and
  ΔEvidence Recall +0.0848.
- DeepSeek E6−E2: ΔF1 −0.0216, ΔStrict −0.0333, ΔSoft 0.0000, and
  ΔEvidence Recall −0.0718.

The sensitivity anchors do not replace the main E5−E3 and E6−E4 baselines.

## Bounded conclusions carried forward

1. R3 does not improve access to the same S3 store in the current experiment.
2. S3+R1 has higher semantic correctness and annotated-evidence coverage than
   S2+R1, but lower token F1.
3. The S3+R3 versus S2+R2 pattern is not descriptively identical across the
   two backbones.
4. Longer bundles are not sufficient for better evidence coverage or answer
   quality.
5. Stage C does not yet explain *why* these differences occur. That requires
   Stage D Evidence-to-answer conversion, category, process, and bounded trace
   analyses.

These conclusions are provisional RQ1 inputs. Formal cross-backbone stability
belongs to RQ2, and final system selection belongs to RQ6.

## Stage D hand-off

Stage D should join the audited Stage B and Stage C question-level effects to
the frozen Stage A rows by deterministic identities. It should use the Stage C
repair/harm identifiers and Evidence deltas to construct candidate lists, but
must reread source traces only during the bounded manual-review step. Stage D
must preserve the 60/58/19 denominators and must not overwrite any Stage A–C
artifact.
