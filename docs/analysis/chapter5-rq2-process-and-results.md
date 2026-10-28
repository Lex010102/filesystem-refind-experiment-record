# Chapter 5 RQ2 Process and Results Record

## Status and purpose

RQ2 is complete and formally audited. It evaluates whether the architecture
effects established in RQ1 retain their observed direction across the Qwen
and DeepSeek end-to-end pipelines. It is a compact robustness analysis, not a
new experiment, mechanism study, cost analysis, or significance test.

The machine-readable source of truth is
`artifacts/chapter5-main60-analysis-v1/rq2-backbone-robustness/`. Its passed
marker is `RQ2.PASSED`. The final audit identity is:

`rq2-audit-ef0e571affac75cd8b6ad71d833411e7a41c10664132770f77d86712827ab00b`

No API or network call was made. No formal answer, score, trace, Stage A row,
or Stage E-RQ1 result was changed. No new bootstrap interval or inferential
cross-backbone test was computed.

## Frozen inputs and pairing contract

The program reads only the frozen Stage A and Stage E-RQ1 artifacts. It
independently verifies their audit identities and file hashes before doing any
calculation.

- Stage A contributes 840 symmetric rows: two backbones, seven conditions,
  and 60 questions per condition.
- Every Qwen row is paired with the DeepSeek row having the same question ID,
  question hash, global position, category, and evidence-eligibility state.
- Qwen is bound to answer set `model1-qwen-main60`, requested alias `coding`,
  and served model `qwen3.8:27b`.
- DeepSeek is bound to answer set `model2-deepseek-main60`, requested alias
  `x-test-2`, and served model `deepseek-v4.1-flash`.
- Both answer sets use the same LLM judge identity: requested model
  `x-test-1`, served model `glm-5.3-flash`.
- Stage E-RQ1 contributes the already audited within-backbone architecture
  effects. RQ2 does not recalculate or replace the RQ1 artifact.

Question, reference-answer, candidate-answer, EvidenceBundle, and judge-rationale
text are absent from the RQ2 output.

## Calculation 1: same-condition backbone performance

For every condition and metric, RQ2 calculates the mean over the fixed 60
questions. The same-condition difference is always:

```text
DeepSeek condition mean - Qwen condition mean
```

### Primary outcomes

All values are on the 0--1 scale. Each effect is DeepSeek minus Qwen.

| Condition | Qwen F1 | DeepSeek F1 | ΔF1 | Qwen Strict | DeepSeek Strict | ΔStrict | Qwen Soft | DeepSeek Soft | ΔSoft |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| E1 | 0.3949 | 0.3013 | −0.0936 | 0.7167 | 0.7500 | +0.0333 | 0.7667 | 0.8083 | +0.0417 |
| E2 | 0.4031 | 0.2455 | −0.1576 | 0.6667 | 0.7000 | +0.0333 | 0.7167 | 0.7083 | −0.0083 |
| E3 | 0.4411 | 0.2971 | −0.1440 | 0.7500 | 0.7000 | −0.0500 | 0.7917 | 0.7583 | −0.0333 |
| E4 | 0.3960 | 0.2314 | −0.1646 | 0.7000 | 0.6667 | −0.0333 | 0.7250 | 0.7083 | −0.0167 |
| E5 | 0.3948 | 0.2604 | −0.1344 | 0.7833 | 0.7500 | −0.0333 | 0.8167 | 0.8000 | −0.0167 |
| E6 | 0.3813 | 0.2240 | −0.1573 | 0.7333 | 0.6667 | −0.0667 | 0.7583 | 0.7083 | −0.0500 |
| E7 | 0.3691 | 0.2854 | −0.0837 | 0.7333 | 0.7500 | +0.0167 | 0.7583 | 0.8000 | +0.0417 |

Qwen has higher F1 in every condition. The semantic results are much closer
and change direction: DeepSeek has higher Strict Accuracy in E1, E2, and E7,
and higher Soft Semantic Score in E1 and E7. The equal-weight descriptive
means across the seven conditions are:

| Metric | Qwen | DeepSeek | DeepSeek−Qwen |
|---|---:|---:|---:|
| Token F1 | 0.3972 | 0.2636 | −0.1336 |
| Strict Accuracy | 0.7262 | 0.7119 | −0.0143 |
| Soft Semantic Score | 0.7619 | 0.7560 | −0.0060 |

These repeated condition paths contain the same questions. The 420 path-level
observations are therefore not treated as 420 independent samples.

### Lexical explanation

DeepSeek produces longer answers and lower Precision in every condition. Its
Recall is higher in E1, E2, and E7 but lower in E3--E6.

| Condition | ΔPrecision | ΔRecall | Δ normalised answer tokens |
|---|---:|---:|---:|
| E1 | −0.1036 | +0.0438 | +6.93 |
| E2 | −0.1886 | +0.0612 | +12.28 |
| E3 | −0.1444 | −0.0268 | +9.75 |
| E4 | −0.1783 | −0.0038 | +12.38 |
| E5 | −0.1393 | −0.0082 | +13.03 |
| E6 | −0.1579 | −0.0652 | +16.12 |
| E7 | −0.1053 | +0.0759 | +8.73 |

Across E1--E7, the descriptive mean Precision is 0.3411 for Qwen and 0.1957
for DeepSeek. Mean answer length is 14.03 versus 25.35 normalised tokens. The
DeepSeek answers are therefore about 80.7% longer, while their mean Precision
is about 42.6% lower. Token Precision divides matched answer tokens by all
candidate-answer tokens, so additional explanation and paraphrastic wording
can reduce Precision even when the required fact is present. Because F1 is
the harmonic mean of Precision and Recall, DeepSeek's small aggregate Recall
advantage cannot offset this much larger Precision deficit. This is the main
observable structure behind the aggregate F1 gap. It remains an association,
not an isolated causal effect, and it does not explain E3--E6 fully because
Recall and semantic scores also decline there. E1, E2, and E7 form a different
pattern: DeepSeek has higher Recall and Strict Accuracy despite lower F1,
which is consistent with a lexical-style penalty rather than uniformly worse
semantic correctness.

## Calculation 2: stability of the RQ1 architecture effects

RQ2 reuses six audited RQ1 contrasts. Every within-backbone effect is target
minus baseline. The descriptive cross-backbone effect difference is:

```text
DeepSeek effect - Qwen effect
```

F1 and Strict Accuracy are the primary classification metrics. Soft Semantic
Score is an interpretive supplement. The canonical taxonomy is `stable`,
`partly_stable`, `backbone_dependent`, or `indeterminate`. These labels record
point-estimate directions and do not imply statistical significance.

| Contrast | Qwen F1 / Strict / Soft | DeepSeek F1 / Strict / Soft | Cross difference F1 / Strict / Soft | Class |
|---|---:|---:|---:|---|
| E3−E1 | +0.0462 / +0.0333 / +0.0250 | −0.0041 / −0.0500 / −0.0500 | −0.0504 / −0.0833 / −0.0750 | Backbone-dependent |
| E4−E2 | −0.0071 / +0.0333 / +0.0083 | −0.0141 / −0.0333 / 0.0000 | −0.0070 / −0.0667 / −0.0083 | Partly stable |
| E2−E1 | +0.0082 / −0.0500 / −0.0500 | −0.0557 / −0.0500 / −0.1000 | −0.0640 / 0.0000 / −0.0500 | Partly stable |
| E4−E3 | −0.0451 / −0.0500 / −0.0667 | −0.0657 / −0.0333 / −0.0500 | −0.0206 / +0.0167 / +0.0167 | Stable, negative |
| E6−E5 | −0.0135 / −0.0500 / −0.0583 | −0.0364 / −0.0833 / −0.0917 | −0.0229 / −0.0333 / −0.0333 | Stable, negative |
| E5−E3 | −0.0463 / +0.0333 / +0.0250 | −0.0367 / +0.0500 / +0.0417 | +0.0096 / +0.0167 / +0.0167 | Stable metric trade-off |

The final counts are three stable findings, two partly stable findings, one
backbone-dependent finding, and no indeterminate finding.

## Bounded interpretation of the six contrasts

1. **E3−E1 is a Qwen-specific conditional advantage.** Foldering with R1
   raises Qwen Precision, Recall, F1, Strict, and Soft, shortens the mean
   answer from 13.28 to 11.97 normalised tokens, and slightly reduces search
   effort. DeepSeek does not reproduce the profile: Precision and Recall fall,
   the answer becomes longer, and Strict and Soft each fall by 0.0500. Qwen
   Evidence Recall changes by only +0.0072, so the benefit is better described
   as a match with the current Qwen search--answer behaviour than as retrieval
   of substantially more annotated evidence. Concision is associated with the
   gain but has not been isolated as its cause.
2. **E4−E2 is partly stable.** F1 is slightly negative for both pipelines,
   while Strict reverses and Soft moves from a small positive value to zero.
3. **E2−E1 is partly stable.** Strict and Soft are negative under both
   pipelines, while F1 changes from a small Qwen gain to a DeepSeek loss.
4. **E4−E3 gives a stable quality conclusion within S2.** R2 is lower than
   R1 for F1, Strict, Soft, Evidence Recall, Any-hit, and All-hit under both
   pipelines. Within the tested S2 store and current implementations, R1 is
   therefore the stronger quality-oriented retrieval system. R2's advantage
   is substantially lower recorded retrieval calls and tokens, so the result
   is a quality--efficiency trade-off.
5. **E6−E5 is stably negative.** R3 is lower than R1 on the same frozen S3
   store for all three answer metrics under both pipelines.
6. **E5−E3 is a stable metric trade-off.** S3+R1 is lower on Token F1 but
   higher on Strict and Soft under both pipelines. This complete-system anchor
   must not be described as an isolated curation effect.

## Answer to RQ2

RQ2 supports several useful but conditional conclusions. In the tested
Main-60 setting, R1 is the stronger quality-oriented retriever on S2 and on S3
under both backbone pipelines. R2 is cheaper on S2 but gives lower answer
quality and lower annotated-evidence coverage. S3+R1 reproducibly trades lower
Token F1 for higher Strict and Soft scores relative to S2+R1. E4−E2 and
E2−E1 are only partly stable. E3−E1 is a Qwen-specific foldering advantage
that is not reproduced under DeepSeek.

The condition results also show why Token F1 and semantic evaluation must
remain separate. Qwen has uniformly higher lexical overlap, whereas semantic
correctness is much closer and reverses in selected conditions. RQ2 therefore
supports conditional architecture conclusions, not a universal ranking of
Qwen, DeepSeek, or storage representations.

## Interpretation boundaries

- The findings apply to two concrete end-to-end pipelines on the fixed
  Main-60 set. They are not universal Qwen-versus-DeepSeek family claims.
- The backbone changes both the Retrieval Agent and Answerer, so RQ2 cannot
  attribute a difference to one component.
- `Stable` means directionally reproduced point estimates. It does not mean
  significant, equal in magnitude, or universally invariant.
- No new bootstrap interval or p-value is computed.
- E7 appears only in the condition overview. Its fusion effects belong to RQ3.
- Full Context is excluded because no symmetric Qwen Full Context run exists.
- Retrieval, utilisation, fusion, and long-context mechanisms belong to RQ5.
- Cost, latency, and practical recommendation belong to RQ6.

## Published outputs

| Output | Rows | Purpose |
|---|---:|---|
| `condition-backbone-comparison.*` | 7 | Same-condition F1, Strict, and Soft comparison |
| `lexical-explanation.*` | 7 | Precision, Recall, and answer-length explanation |
| `architecture-stability.*` | 6 | Full audited architecture-stability rows |
| `table-5-13-inputs.*` | 6 | Compact report-facing stability projection |

The output directory also contains `schema.json`, `source-manifest.json`,
`audit.json`, `README.md`, and `RQ2.PASSED`.

## Verification

The formal builder and independent audit both passed. The RQ2 tests cover the
7/7/6 table contract, exact numerical anchors, algebraic differences, frozen
input reconciliation, model and judge identities, scope boundaries, tamper
rejection, extra-file rejection, and existing-output rejection. The combined
Stage A, Stage E-RQ1, and RQ2 regression run passed all 19 tests. A final
read-only review found no remaining actionable issue.
