# Chapter 5 RQ5 Integrated Bottleneck Decomposition

## Status and scope

Section 5.6.6 is complete as an audited offline analysis. It integrates the
frozen Storage, Retrieval, Packaging, Answerer, E7, Full Context, and evaluation
audits. It does not call a model or API and does not modify any formal answer or
score.

The attribution population contains exactly 250 Strict-noncorrect answer paths:

| Access regime | Error paths |
|---|---:|
| E1--E6 selective retrieval | 205 |
| E7 dual-source fusion | 31 |
| Full Context | 14 |
| **Total** | **250** |

These are path-level observations across conditions and backbones. They are not
250 unique questions.

## Inputs and integration rule

The analysis consumes only the frozen, passed artifacts from Sections 5.6.1--
5.6.5:

- the 250-row Strict-noncorrect case index;
- S1--S3 storage-fidelity and source/reference review;
- R1--R3 trace, selection, and EvidenceBundle audit;
- Packaging, Answerer, and E7 mechanism review;
- Full Context diagnostic review;
- token-versus-LLM-judge disagreement review.

Each path receives one mutually exclusive primary attribution. The primary
cause is the earliest *validly supported* breakpoint in the applicable chain.
Later or interacting mechanisms are retained as non-exclusive co-occurrences.

The condition-specific chains are:

- E1--E6: Storage -> Retrieval/selection -> Packaging -> Answerer;
- E7: parent upstream paths -> deterministic fusion -> Answerer;
- Full Context: full-history localisation/competition -> Answerer.

Evaluation-sensitive and Mixed/Indeterminate are terminal attribution outcomes,
not physical system components.

### Source/reference mismatch guard

Trace review found that three question families contain a verified entity
mismatch between the question/reference and the annotated source. This affects
33 Strict-noncorrect paths. A retriever cannot be judged to have missed the
requested fact merely because it did not return a locator that refers to a
different entity. These paths are therefore assigned to Evaluation-sensitive,
not Retrieval, unless a separate valid system breakpoint is available. This
guard prevents annotation misalignment from being reported as a retrieval
defect.

## 5.6.6.1 Primary root-cause distribution

### Complete 250-path distribution

| Primary attribution | Count | Rate |
|---|---:|---:|
| Storage | 0 | 0.0% |
| Retrieval | 42 | 16.8% |
| Packaging | 7 | 2.8% |
| Answerer | 68 | 27.2% |
| Fusion / Long Context | 6 | 2.4% |
| Evaluation-sensitive | 53 | 21.2% |
| Mixed / Indeterminate | 74 | 29.6% |
| **Total** | **250** | **100.0%** |

The 74 Mixed/Indeterminate paths are retained rather than redistributed. Their
29.6% share is an uncertainty result: the available records do not support one
unique primary cause.

### Resolved views

There are 176 resolved attributions, 55 mixed attributions, and 19
indeterminate attributions.

Among all 176 resolved attributions:

| Primary attribution | Count | Rate among resolved |
|---|---:|---:|
| Answerer | 68 | 38.6% |
| Evaluation-sensitive | 53 | 30.1% |
| Retrieval | 42 | 23.9% |
| Packaging | 7 | 4.0% |
| Fusion / Long Context | 6 | 3.4% |
| Storage | 0 | 0.0% |

Evaluation-sensitive cases describe benchmark or scoring boundaries rather
than an internal architecture component. Restricting the denominator to the
123 resolved system-internal breakpoints gives the direct architectural answer:

| System-internal breakpoint | Count | Rate among 123 |
|---|---:|---:|
| Answerer | 68 | 55.3% |
| Retrieval | 42 | 34.1% |
| Packaging | 7 | 5.7% |
| Long Context | 6 | 4.9% |
| Storage | 0 | 0.0% |

The largest supported internal bottleneck is therefore evidence utilisation by
the Answerer. Retrieval is the second-largest supported internal bottleneck.

### Breakdown by access regime

| Access regime | N | Storage | Retrieval | Packaging | Answerer | Fusion / Long Context | Evaluation-sensitive | Mixed / Indeterminate |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| Selective retrieval | 205 | 0 | 41 | 7 | 56 | 0 | 39 | 62 |
| E7 dual-source fusion | 31 | 0 | 1 | 0 | 9 | 0 | 9 | 12 |
| Full Context | 14 | 0 | 0 | 0 | 3 | 6 | 5 | 0 |

E7 has no supported deterministic-fusion primary failure. Its eight Harm
outcomes preserve all parent EvidenceItems exactly, so Harm is treated as an
outcome and possible Answerer-interference signal, not proof that the fusion
operation dropped evidence.

### Breakdown by selective retriever

| Retriever | Error-path N | Retrieval | Packaging | Answerer | Evaluation-sensitive | Mixed / Indeterminate |
|---|---:|---:|---:|---:|---:|---:|
| R1 | 93 | 0 | 3 | 34 | 19 | 37 |
| R2 | 76 | 33 | 1 | 14 | 14 | 14 |
| R3 | 36 | 8 | 3 | 8 | 6 | 11 |

These denominators contain only Strict-noncorrect paths and therefore do not
measure retriever accuracy. They describe the composition of each retriever's
observed errors.

- R1 errors are dominated by Answerer and unresolved mechanisms. Its apparent
  four-case Retrieval cluster was one repeated, source-misaligned question and
  was removed from pure Retrieval attribution.
- R2 has a clear Retrieval-heavy error profile: 33 of 76 error paths have a
  supported acquisition, observation, or selection break.
- R3 shows a mixed profile: eight Retrieval, three Packaging, eight Answerer,
  and eleven unresolved paths. Its curated-memory adaptation does not reduce to
  one failure mechanism.

## 5.6.6.2 Co-occurring mechanisms

Mechanism counts are non-exclusive and must not be added to 250.

| Supported co-occurring mechanism | Paths | Rate over 250 |
|---|---:|---:|
| Annotated retrieval attrition | 76 | 30.4% |
| Demonstrated relevant Packaging loss | 9 | 3.6% |
| Possible noise or ordering pressure | 42 | 16.8% |
| Explicit Answerer misuse or unsupported abstention | 74 | 29.6% |
| Long-context localisation or interference | 6 | 2.4% |
| Explicit evaluation sensitivity after branch review | 74 | 29.6% |
| Shared representation insufficiency | 12 | 4.8% |
| E7 Harm with exact parent-item preservation | 8 | 3.2% |

The difference between 76 retrieval-attrition mechanisms and 42 Retrieval
primary causes is intentional. Retrieval weakness can co-occur with an earlier
annotation limitation, a later Answerer failure, or an unresolved chain. The
same distinction applies to the nine demonstrated Packaging losses: seven are
the earliest primary breakpoint, while two occur after an earlier supported
Retrieval break.

## 5.6.6.3 Representative cases

Six trace-reviewed cases provide compact explanations. They illustrate the
distribution but do not replace it.

| Role | Backbone / condition | Question ID | Validated interpretation |
|---|---|---|---|
| R1 with sufficient evidence | Qwen / E1 | `conv-50-q037` | Evidence Recall is complete and the bundle is focused, but the Answerer returns only part of the required date. |
| R2 retrieval break | Qwen / E2 | `conv-50-q022` | Query/ranking and the four-action cap fail to reach both annotated sessions; the final bundle has zero annotated-evidence recall. |
| R3 Packaging break | Qwen / E6 | `conv-50-q052` | The trace finds and selects the key temporal item, but the 16,000-character budget excludes it from the final bundle. |
| Evaluation-sensitive entity mismatch | Qwen / E1 | `conv-50-q089` | The candidate follows the inspected source entity, while the question/reference names another entity. |
| E7 Harm without item loss | Qwen / E7 | `conv-50-q051` | E2 is correct; E7 preserves every parent item and full annotated coverage, but extra context changes the final Answerer decision. |
| Full Context localisation/composition | DeepSeek / Full Context | `conv-50-q019` | Both events are present in the full 108,960-character history, but the Answerer counts only one and fails the cross-session composition. |

The previous tentative R1 Retrieval example (`conv-50-q152`) was rejected by
manual trace review because its annotated source refers to a different person.
The previous Full Context example (`conv-50-q008`) was also rejected because
its image-caption source did not cleanly establish the reference inference.

## Final answer to RQ5

The primary system bottleneck is not one universal search failure. Among
resolved internal breakpoints, the Answerer is the largest component (55.3%),
followed by Retrieval (34.1%). The balance is architecture-specific: R2 errors
are retrieval-heavy; R1 errors are more often evidence-utilisation or
unresolved cases; R3 combines Retrieval, Packaging, and Answerer failures.

No store-specific primary failure is supported. S1--S3 sometimes inherit
source or shared-rendering limitations, but the audit found no decisive
condition-specific omission or distortion. E7 likewise has no confirmed
fusion-operation primary failure. Full Context removes selective retrieval but
introduces a distinct localisation and cross-event composition burden, which
accounts for six of its fourteen errors.

Evaluation sensitivity is material: 53 paths have it as the primary
attribution, and 74 have an explicitly supported evaluation-sensitive
mechanism after all branch reviews. This does not overturn the earlier
architecture comparisons; it limits causal interpretation of particular
cases. Finally, 74 paths remain Mixed/Indeterminate. The study therefore
supports a ranked set of bottlenecks, not a claim that every error has one
fully observed cause.

## Reproducibility and audit

- Program: `fs_memory_lab/chapter5_rq5_integrated.py`
- Tests: `tests/test_chapter5_rq5_integrated.py`
- Machine-readable artifact:
  `artifacts/chapter5-main60-analysis-v1/rq5-integrated-bottleneck/`
- Final audit ID:
  `rq5-integrated-audit-7c68cdb9c619409de661590729605b9c2d9c650003db223f8651f8de0c48eaf2`
- Unit and integration tests: 10/10 passed.
- Independent artifact reconstruction and hash audit: passed.
- API calls: none.
- Network calls: none.
- Formal answer/score mutation: none.
