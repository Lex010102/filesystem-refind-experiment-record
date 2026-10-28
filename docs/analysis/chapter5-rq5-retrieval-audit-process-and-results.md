# Chapter 5 RQ5 Section 5.6.3 Retrieval Audit: Process and Results

## Status and purpose

Section 5.6.3 is complete and formally audited. It asks why information that
exists in S1--S3 does or does not become usable evidence under R1--R3. The
machine-readable source of truth is:

`artifacts/chapter5-main60-analysis-v1/rq5-retrieval-audit/`

The passed marker is `RQ5-RETRIEVAL-AUDIT.PASSED`. The final audit identity is:

`rq5-retrieval-audit-1e2aacfe880ba84f21f22e6fee306533cde0c5e309d8211937e4af3de1b4925f`

The audit is fully offline. It did not call an API or modify any formal run,
answer, score, store, trace, or EvidenceBundle. It also did not assign a
causal root cause automatically. Only the retrieval-reach and model-observation
fields of the existing 250-case RQ5 state register were updated.

## Analysis population and denominators

The primary unit is one `backbone x condition x question` retrieval path. The
analysis contains all 720 independent E1--E6 paths:

| Retriever | Conditions | Paths | Evidence-eligible paths |
|---|---|---:|---:|
| R1 | E1, E3, E5 | 360 | 348 |
| R2 | E2, E4 | 240 | 232 |
| R3 | E6 | 120 | 116 |
| **Total** | **E1--E6** | **720** | **696** |

The 696 evidence-eligible paths come from 58 questions with official evidence
annotations, two backbones, and six conditions. The remaining 24 paths belong
to q040 and q043. Their actions, stops, and bundles remain auditable, but they
are excluded from gold-based reach, observation, All-hit, and Evidence Recall
rates.

The RQ5 error register contains 205 E1--E6 Strict-noncorrect paths. Of these,
191 are evidence-eligible. E7 is excluded because it reuses the E2 and E6
bundles and performs no new retrieval. Full Context is excluded because it has
no retriever or selected evidence set.

## Reconstruction method

### Common funnel

Every eligible path is reconstructed through the following diagnostic funnel:

1. the store contains the official annotated source;
2. the retriever reaches the source file, session, or H2 group;
3. a returned observation exposes an official annotated locator;
4. all required annotated locators are exposed;
5. all exposed annotated locators are retained by note selection;
6. all retained annotated locators survive in the final EvidenceBundle;
7. the Answerer produces a Strict-correct answer.

These are trace states, not automatic causal labels. In particular, an
official gold locator is a diagnostic coordinate rather than an exhaustive
relevance label. A bundle that does not contain a gold locator may still hold
semantically equivalent unannotated evidence.

### R1 reconstruction

R1 is reconstructed directly from each frozen filesystem action. The audit
matches action coverage and accepted note selectors against the verified S1,
S2, or S3 attribution index. It records files and directories inspected,
search and view actions, first annotated observation, repeated file visits,
accepted notes, stops, and native round-cap states.

`source reached` means that an observation touches a file containing an
annotated source. `annotated evidence observed` is stricter: the returned line
coverage must overlap an annotated source span.

### R2 and R3 reconstruction

R2 and R3 traces record query arguments and returned session or H2-group
identities, but not every ranked hit and context span. The audit therefore
replays all 360 ranked-retrieval paths against the frozen local indexes, in
action order, with the recorded query terms, date filters, top-k, local context
window, and seen-state.

- R2 replay uses the exchange-level BM25 and session-level RRF index.
- R3 replay uses the fact-level BM25 and H2-group RRF index.

For all 360 paths, replayed query terms, result counts, returned source
identities, and seen-state exclusions exactly match the formal records.

## Common retrieval-funnel results

| Retriever | Eligible | Any annotated source reached | Observed all | Selected all | Final All-hit | Mean Evidence Recall | Strict Accuracy |
|---|---:|---:|---:|---:|---:|---:|---:|
| R1 | 348 | 348 (100.0%) | 323 (92.8%) | 291 (83.6%) | 291 (83.6%) | 0.875 | 74.2% |
| R2 | 232 | 215 (92.7%) | 174 (75.0%) | 171 (73.7%) | 171 (73.7%) | 0.782 | 68.3% |
| R3 | 116 | 116 (100.0%) | 96 (82.8%) | 95 (81.9%) | 85 (73.3%) | 0.781 | 70.0% |

R1 has the strongest overall annotated-evidence funnel. R2 loses more paths
before complete observation: the relevant session may not be reached, or the
fixed ranked result and local expansion may not expose every annotated turn.
R3 reaches every annotated H2 group, but group reach does not guarantee that
the correct fact enters the returned local window. R3 also has a visible
selected-to-final boundary loss under the 16,000-character EvidenceBundle
budget.

The retrieval systems differ substantially in recorded retrieval-token cost:

| Retriever | Mean retrieval tokens per path | Mean native search/observation count |
|---|---:|---:|
| R1 | 220,205.7 | 7.79 |
| R2 | 14,050.2 | 2.32 |
| R3 | 30,830.6 | 2.07 |

The token totals are comparable descriptive costs. The native action counts
are not treated as interchangeable units: an R1 filesystem observation and an
R2/R3 ranked search perform different work.

## Strict-error localisation

The 191 evidence-eligible E1--E6 errors divide as follows:

| Diagnostic state | R1 | R2 | R3 | Total |
|---|---:|---:|---:|---:|
| Annotated source not reached | 0 | 15 | 0 | 15 |
| Source reached, annotated locator not observed | 2 | 16 | 7 | 25 |
| Only part of the required annotated evidence observed | 2 | 11 | 4 | 17 |
| Complete observation, incomplete selection | 13 | 2 | 1 | 16 |
| Complete selection, incomplete final bundle | 0 | 0 | 7 | 7 |
| Complete annotated bundle, Strict-noncorrect | 68 | 28 | 15 | 111 |
| **Eligible Strict errors** | **85** | **72** | **34** | **191** |

Overall, 111/191 errors (58.1%) already have a complete annotated
EvidenceBundle. The remaining 80/191 (41.9%) show attrition somewhere in the
annotated-evidence funnel. This result rules out a simple claim that most
errors are caused by missing retrieval evidence.

The distribution differs by retriever:

- R1 retains complete annotated bundles for 68/85 eligible errors (80.0%).
  Its remaining errors are therefore more likely to require the later
  sufficiency, packaging, or Answerer analysis in Section 5.6.4.
- R2 retains complete annotated bundles for only 28/72 eligible errors
  (38.9%). Its main diagnostic losses occur at source reach, ranked exposure,
  and complete multi-evidence acquisition.
- R3 retains complete annotated bundles for 15/34 eligible errors (44.1%).
  Seven additional errors cross the selected-to-final bundle boundary. The
  cause of that boundary loss is deliberately deferred to Section 5.6.4.

These are mechanism fingerprints, not final causal assignments. Alternate
evidence, source ambiguity, and semantic sufficiency still require the unified
trace review.

## Retriever-specific findings

### R1: Agentic Filesystem Retrieval

R1 reaches at least one annotated source file on every eligible path and
observes all annotated locators on 323/348 eligible paths. The main measurable R1 attrition occurs between
observation and note selection: 39 eligible paths observe more annotated
locators than they finally select. No R1 path loses an already selected gold
locator at the final bundle boundary.

The store changes this behaviour. E5, which applies R1 to S3, has the strongest
condition-level retrieval coverage: Evidence Recall is 0.925 for Qwen and
0.963 for DeepSeek. However, S2 does not provide a stable R1 gain. Relative to
E1, E3 has a small positive Evidence Recall change for Qwen (+0.007) but a
negative change for DeepSeek (-0.030). Directory organisation can alter the
agent's navigation path, but it does not guarantee a backbone-independent
benefit.

### R2: ReFind-style raw-chat retrieval

R2 is much cheaper than R1 but has lower complete-evidence coverage. Across
both stores and backbones, it fails to reach an annotated session on 17/232
eligible paths and reaches the session without exposing an annotated locator
on another 17 paths. A further 24 paths expose some but not all required
locators. Note selection is a smaller measured bottleneck than initial query,
ranking, session fusion, and local context expansion.

The fixed local context window contributes useful evidence: 181 context-only
annotated hits are observed across the E2 and E4 replays. At the same time,
reaching a relevant session does not ensure that the decisive turn lies inside
the returned window.

E4--E2 is a negative-control-style check because R2 does not consume S2 folder
paths. Qwen is nearly invariant in mean Evidence Recall (-0.001). DeepSeek
differs by -0.029, which reflects a separate model-generated action trajectory,
not use of the folder hierarchy.

### R3: curated-memory retrieval

R3 reaches at least one annotated H2 group on every eligible path, but complete
observation falls to 96/116. Thus topic-group reach is easier than exact-fact
exposure. The local fact window and model-generated query trajectory determine
whether every required fact is actually shown.

R3 also has the clearest final-budget pressure. Sixty-five of 120 paths have at
least one skipped EvidenceItem, and 12 eligible paths lose at least one
selected annotated locator before the final bundle. These losses correspond to
the frozen `skipped_items` records. The formal root cause of the
selected-to-final transition remains a Section 5.6.4 packaging question.

R3 is not superior to R1 on the same curated store. E6--E5 reduces Evidence
Recall by 0.089 for Qwen and 0.237 for DeepSeek. The final All-hit transition is
0 repairs/7 harms for Qwen and 1 repair/15 harms for DeepSeek. This establishes
a strong descriptive result for the present system: S3's organisation is used
more successfully by agentic filesystem navigation than by the adapted R3
ranked retriever.

## Category structure

| Retriever | Category | Eligible paths | Final All-hit | Mean Evidence Recall |
|---|---|---:|---:|---:|
| R1 | Multi-hop | 78 | 65.4% | 0.756 |
| R1 | Temporal | 78 | 97.4% | 0.987 |
| R1 | Open-domain | 30 | 60.0% | 0.750 |
| R1 | Single-hop | 162 | 90.1% | 0.901 |
| R2 | Multi-hop | 52 | 53.8% | 0.662 |
| R2 | Temporal | 52 | 61.5% | 0.644 |
| R2 | Open-domain | 20 | 40.0% | 0.525 |
| R2 | Single-hop | 108 | 95.4% | 0.954 |
| R3 | Multi-hop | 26 | 65.4% | 0.747 |
| R3 | Temporal | 26 | 76.9% | 0.808 |
| R3 | Open-domain | 10 | 30.0% | 0.517 |
| R3 | Single-hop | 54 | 83.3% | 0.833 |

R2 is highly effective for single-hop evidence access but loses coverage on
multi-hop, temporal, and open-domain questions. R1 is especially strong on
temporal evidence access. R1's temporal All-hit rate is 97.4%, yet its temporal
Strict Accuracy is only 73.1%; complete annotated access is therefore not
sufficient for correct temporal reasoning. Open-domain denominators are small
and include only five evidence-eligible questions per backbone, so those rates
are treated as descriptive.

## Controlled retrieval comparisons

| Backbone | Contrast | Delta Evidence Recall | Complete-observation repair/harm | Final-All-hit repair/harm | Strict repair/harm |
|---|---|---:|---:|---:|---:|
| Qwen | E2-E1 | -0.033 | 5/10 | 7/8 | 2/5 |
| Qwen | E4-E3 | -0.042 | 2/11 | 5/8 | 4/7 |
| Qwen | E6-E5 | -0.089 | 1/5 | 0/7 | 2/5 |
| Qwen | E3-E1 | +0.007 | 3/1 | 4/3 | 5/3 |
| Qwen | E4-E2 | -0.001 | 1/3 | 2/3 | 5/3 |
| DeepSeek | E2-E1 | -0.080 | 1/12 | 3/8 | 4/7 |
| DeepSeek | E4-E3 | -0.079 | 3/14 | 6/11 | 4/6 |
| DeepSeek | E6-E5 | -0.237 | 0/13 | 1/15 | 2/7 |
| DeepSeek | E3-E1 | -0.030 | 0/2 | 1/3 | 1/4 |
| DeepSeek | E4-E2 | -0.029 | 1/3 | 1/3 | 1/3 |

All three matched retriever contrasts favour R1 in net complete-evidence
coverage: E2--E1, E4--E3, and E6--E5 have more harms than repairs under both
backbones. R2 and R3 remain much cheaper, so this is a quality--cost trade-off,
not evidence that they are useless.

The same retrieval metric does not guarantee the same answer transition.
Across the paired records, some paths improve complete acquisition without
repairing Strict correctness, while other paths answer correctly without an
All-hit bundle. This motivates the content-based sufficiency and Answerer
analysis in Section 5.6.4.

## Cap, stop, and final-bundle diagnostics

| Retriever | Native-cap paths | Strict-correct among capped | Eligible empty bundles | Nonempty bundles with no annotated gold |
|---|---:|---:|---:|---:|
| R1 | 41 | 25 | 5 | 25 |
| R2 | 212 | 137 | 7 | 34 |
| R3 | 106 | 72 | 1 | 18 |
| **Total** | **359** | **234** | **13** | **77** |

Overall, 234/359 capped paths (65.2%) are Strict-correct. A cap hit is therefore
a process state, not a failure label. Likewise, `nonempty bundle with no
annotated gold` does not mean `irrelevant bundle`: the annotation is not an
exhaustive relevance judgement.

## Relationship between All-hit and answer correctness

| Retriever | P(Strict correct given All-hit) | P(Strict correct given not All-hit) |
|---|---:|---:|
| R1 | 76.6% | 70.2% |
| R2 | 83.6% | 27.9% |
| R3 | 82.4% | 38.7% |

For R2 and R3, All-hit is strongly associated with Strict correctness. For R1,
the gap is much smaller. This does not make All-hit unimportant; it shows that
the official evidence annotations are neither a complete necessity test nor a
content-based sufficiency test. R1 can retrieve useful unannotated support,
and it can also fail after all annotated evidence is present.

## Interpretation limits and deferred work

The following constraints are frozen with the analysis:

- Gold annotations diagnose trace transitions but do not automatically prove a
  causal retrieval failure.
- R1 source reach denotes a file touch; exact annotated-span exposure is
  reported separately.
- Query-to-source lexical overlap is a mechanical token measure, not a semantic
  query-quality judgement.
- A native cap hit is not equivalent to premature stopping.
- R1 rounds, filesystem observations, and R2/R3 ranked-search actions are not
  interchangeable units.
- Selected-to-bundle loss, final evidence sufficiency, and Answerer use belong
  to Section 5.6.4.
- R3 stale-state selection, conflict resolution, query-semantic mismatch, and
  alternate unannotated evidence remain part of the final unified trace review.
- The experiment contains one conversation and one formal trace per
  `backbone x condition x question`; it does not estimate run-to-run variance.

## Output inventory and verification

The formal directory includes:

- `retrieval-funnel`: 720 path-level rows;
- `stage-transitions`: 72 adjacent-stage summaries;
- `r1-diagnostics`, `r2-diagnostics`, and `r3-diagnostics`: 720
  retriever-specific rows;
- `controlled-comparisons`: 600 paired condition rows;
- `cross-backbone-comparisons`: 360 paired backbone rows;
- `retriever-summary`: 12 backbone-condition summaries;
- `retriever-category-summary`: 48 backbone-condition-category summaries;
- `strict-error-retrieval-linkage`: 205 linked error rows;
- `root-cause-state-register-after-retrieval`: 250 state rows;
- schema, source manifest, audit, and passed marker.

Fourteen retrieval-audit tests pass. The combined Section 5.6.1--5.6.3 suite
passes 36/36 tests. An independent reconstruction from the 720 frozen records
and the local indexes reports zero differences at source reach, annotated
observation, selection, and final-bundle stages. The independent category
summaries also match all 48 published groups.
