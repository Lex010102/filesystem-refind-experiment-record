# Chapter 5 RQ5 Section 5.6.4: Downstream Conversion and Full Context Analysis

## Status and purpose

Section 5.6.4 is complete and formally audited. It asks what happens after
potentially relevant information has been reached. The analysis separates four
questions:

1. Is the final selective input semantically sufficient, and did packaging
   demonstrably remove relevant content?
2. When sufficient evidence is present, does the shared Answerer use it
   correctly?
3. Does E7 repair, preserve, harm, or leave unresolved the outcomes of its E2
   and E6 parents?
4. Which failures remain when all 30 raw sessions are visible through Full
   Context?

The two machine-readable sources of truth are:

- `artifacts/chapter5-main60-analysis-v1/rq5-downstream-audit/`
- `artifacts/chapter5-main60-analysis-v1/rq5-full-context-audit/`

Their passed markers are `RQ5-DOWNSTREAM.PASSED` and
`RQ5-FULL-CONTEXT.PASSED`. The final audit identities are:

- `rq5-downstream-audit-dea568099f1ba5aaca800c529685f079339fd06da20d3a6ead97e6bb07aa13f4`
- `rq5-full-context-audit-afb779c4dce7248c980e03f8c5e9b977dd846ce362d5ccfcd9e44fa7bd2736e4`

The analysis is fully offline. It does not call a model or API, alter a formal
answer or score, or expose question, answer, evidence, prompt, or rationale
text in the public tables.

Integrated primary-cause decomposition is deliberately excluded. It is the
next, separate RQ5 step because a final earliest-break label must reconcile the
storage, retrieval, downstream, Full Context, and evaluation audits.

## Analysis populations and denominator discipline

| Analysis unit | Population | Denominator |
|---|---|---:|
| E1--E6 content sufficiency, packaging, and Answerer review | Strict-noncorrect selective paths | 205 |
| Evidence-eligible E1--E6 error paths | Strict-noncorrect paths with official evidence locators | 191 |
| E7 fusion operation | All matched E2/E6/E7 triples | 120 |
| E7 error-mechanism review | E7 Strict-noncorrect paths | 31 |
| Full Context overall diagnostics | Unique Main-60 Full Context answers | 60 |
| Full Context error-mechanism review | Full Context Strict-noncorrect answers | 14 |
| Full Context evidence-position analysis | Questions with official evidence locators | 58 |
| Full Context pairwise comparison table | 60 questions x seven selective conditions | 420 |

The 205 selective paths are an error-conditioned population, not an error rate
over all 720 E1--E6 paths. The 420 Full Context comparison rows are also not
420 independent Full Context answers. They are seven views of the same 60
answers.

## Method and audit order

The downstream audit follows the information chain in a fixed order.

1. Freeze a content-based judgement of the final input without using the
   candidate answer or Judge outcome.
2. Distinguish demonstrated relevant loss from possible noise or ordering
   pressure. A recorded skipped item is not itself proof that relevant content
   was lost.
3. Assign an Answerer-utilisation failure only when the final input is already
   sufficient.
4. Reconstruct every E7 bundle from the frozen E2 and E6 parents and verify the
   exact fusion operation before interpreting the outcome.
5. Validate all 60 Full Context records against Stage A by file hash,
   canonical-payload hash, record ID, question identity, and bundle identity.
6. Review the 14 unique Full Context errors and keep source/reference ambiguity
   separate from supported model failure.

Only the state fields owned by each stage are changed. All other fields in the
250-row root-cause register remain byte-equivalent to their predecessor.

## 5.6.4.1 Evidence sufficiency and packaging

### Final-input content state

| Content state | Count | Share of 205 errors |
|---|---:|---:|
| Complete and focused | 16 | 7.8% |
| Complete but noisy | 72 | 35.1% |
| Partial | 70 | 34.1% |
| Irrelevant or empty | 41 | 20.0% |
| Indeterminate | 6 | 2.9% |

The first two states form the 88 semantically sufficient inputs. The remaining
paths contain 111 insufficient inputs and six indeterminate inputs.

| Final-input sufficiency | Qwen | DeepSeek | Total |
|---|---:|---:|---:|
| Sufficient | 43 | 45 | 88 |
| Insufficient | 52 | 59 | 111 |
| Indeterminate | 4 | 2 | 6 |
| **Strict-noncorrect paths** | **99** | **106** | **205** |

Among the 191 evidence-eligible errors, 111 have an annotated All-hit bundle.
Only 63 of those 111 are semantically sufficient; 48 still lack a required
relation, time anchor, entity link, or usable context. Conversely, 19 of the 80
non-All-hit paths contain sufficient alternative support. All-hit is therefore
informative, but it is neither a sufficient nor a necessary semantic test.

### Packaging result

| Packaging judgement | Count | Share of 205 errors |
|---|---:|---:|
| Demonstrated relevant loss | 9 | 4.4% |
| Possible noise or ordering contribution | 42 | 20.5% |
| No demonstrated packaging failure | 148 | 72.2% |
| Indeterminate | 6 | 2.9% |

Six of the nine demonstrated-loss cases lose the relevant material completely;
three retain it only partially. Seventeen error paths have at least one
recorded skipped item, but only nine establish that the skipped material is
relevant to the required answer. No EvidenceItem is truncated internally in
any of the 205 paths.

The main packaging finding is therefore negative but useful: packaging is a
real mechanism in a small, directly supported subset, especially for E6, but
it is not the dominant explanation for the selective-path errors. The larger
downstream problem is either insufficient evidence before packaging or failure
to use evidence that survived.

## 5.6.4.2 Shared Answerer utilisation

Answerer attribution is gated on final-input sufficiency. Of the 205 selective
errors, 117 are not assessable as Answerer failures because the final input is
insufficient or indeterminate. The remaining 88 have sufficient final input.

| State within the 88 sufficient-input errors | Count | Share |
|---|---:|---:|
| Explicit Answerer failure | 56 | 63.6% |
| Evaluation-sensitive or indeterminate conversion | 32 | 36.4% |

The 56 explicit failures contain 36 cases of evidence misuse and 20 unsupported
abstentions. Qwen has 26 explicit failures among 43 sufficient-input errors;
DeepSeek has 30 among 45.

The category pattern is more informative than one aggregate label:

- all 20 sufficient-input Open-domain errors are unsupported abstentions;
- 11 of 14 sufficient-input Temporal errors are explicit evidence misuse;
- 20 of 43 sufficient-input Single-hop errors are explicit misuse, while the
  other 23 are mainly reference- or evaluation-sensitive;
- five of 11 sufficient-input Multi-hop errors are explicit misuse and six
  remain evaluation-sensitive or indeterminate.

Thus the shared Answerer is an important confirmed bottleneck once usable
evidence is available. This conclusion must not be expanded to all 205 errors:
111 have insufficient input and six remain indeterminate.

## 5.6.4.3 E7 dual-source fusion

### Operational verification

All 120 E7 bundles exactly reproduce the deterministic E2-plus-E6 fusion:

- 120/120 have the expected parent source IDs and item sums;
- 120/120 preserve all parent items;
- 120/120 use the expected interleaving order;
- no path performs new retrieval;
- no path deduplicates or truncates a parent item.

An E7 failure is therefore not explained by a hidden third retriever or by an
implementation loss of parent evidence.

### Outcome states

| E7 outcome | Qwen | DeepSeek | Total | Share of 120 |
|---|---:|---:|---:|---:|
| Preserve | 43 | 42 | 85 | 70.8% |
| Repair | 1 | 3 | 4 | 3.3% |
| Harm | 4 | 4 | 8 | 6.7% |
| Unresolved | 12 | 11 | 23 | 19.2% |

The four repairs occur only in Multi-hop and Temporal questions: two in each
category. One Temporal case is a directly demonstrated complementary repair.
One Multi-hop case is answer recovery without a demonstrated fusion cause.
The other two repairs remain indeterminate because the parent sufficiency
reviews do not support a unique causal fusion account.

Among the 31 E7 errors (eight Harm and 23 Unresolved), 17 fused inputs are
semantically sufficient and 14 are insufficient. Nine errors have explicit
Answerer failures: six unsupported abstentions and three evidence-misuse
cases. The remaining sufficient-input errors are evaluation-sensitive or not
causally separable from answer conversion.

Harm is not synonymous with fusion interference. Of the eight Harm cases, two
have insufficient fused input, two have explicit Answerer failures, and four
are sensitive to evaluation threshold or reference/source expression. The
evidence supports selective complementarity, but not the stronger claim that
fusion reliably chooses the correct parent or that every observed Harm is
caused by noisy fusion.

## 5.6.4.4 Full Context

### Overall and category outcomes

Full Context supplies all 30 raw sessions, totalling 568 turns and 108,960
evidence characters, to the shared Answerer. It has no retriever and no
16,000-character EvidenceBundle cap.

| Category | Correct / N | Strict Accuracy | Soft | Precision | Recall | F1 |
|---|---:|---:|---:|---:|---:|---:|
| Multi-hop | 11/13 | 84.6% | 0.8846 | 0.1520 | 0.7026 | 0.2366 |
| Open-domain | 3/7 | 42.9% | 0.5000 | 0.0320 | 0.6429 | 0.0608 |
| Single-hop | 22/27 | 81.5% | 0.8889 | 0.1876 | 0.7992 | 0.2868 |
| Temporal | 10/13 | 76.9% | 0.8077 | 0.2166 | 0.6590 | 0.2636 |
| **Overall** | **46/60** | **76.7%** | **0.8250** | **0.1680** | **0.7296** | **0.2445** |

### The 14 Full Context errors

Nine errors occur despite a sufficient complete-history input. They contain
five evidence-misuse cases and four unsupported abstentions. The other five
cases remain indeterminate because the source, question, reference, or task
boundary does not support a clean model-failure label.

The supported long-context utilisation states are three missed-relevant-content
cases, two distractor-confusion cases, and one temporal-confusion case. Three
other errors successfully locate relevant material but still fail at answer
formation. The remaining five are indeterminate. Complete visibility therefore
removes retrieval omission but does not remove localisation, competition,
composition, calibration, or benchmark-ambiguity failures.

Open-domain is the weakest category: four errors among seven questions. Three
of these occur with sufficient input and unsupported abstention. This pattern
points to excessive caution or underuse of background knowledge, not missing
conversation access.

| Full Context outcome | N | Mean answer length | Precision | Recall | F1 | Soft |
|---|---:|---:|---:|---:|---:|---:|
| Strict-correct | 46 | 20.78 | 0.2031 | 0.8414 | 0.2929 | 1.000 |
| Strict-noncorrect | 14 | 31.86 | 0.0529 | 0.3624 | 0.0857 | 0.250 |

The error answers are about 11.07 normalised tokens longer on average, while
all three lexical metrics are lower. This is a descriptive post-outcome
association. It does not show that answer length itself causes failure.

### Position and selective-path diagnostics

Evidence-position analysis uses only the 58 questions with official source
locators. Position is the zero-based global-turn ordinal divided by 567, not a
character or token offset. The reported midrange is the midpoint of the
earliest and latest annotated turns, not the mean of all source positions.

| Eligible Full Context outcome | N | Mean earliest turn position | Mean latest turn position | Mean midrange turn position |
|---|---:|---:|---:|---:|
| Strict-correct | 45 | 0.5115 | 0.5846 | 0.5480 |
| Strict-noncorrect | 13 | 0.4029 | 0.4193 | 0.4111 |

The errors are not concentrated in the middle of the prompt; their annotated
evidence is earlier on average. This does not support a single generic
lost-in-the-middle explanation. The result is descriptive, based on one fixed
conversation, and does not rule out position effects within particular
categories.

The oracle-style any-selective view gives 46 both-correct, zero Full-Context-
only, six selective-only, and eight neither-correct questions. Thus every Full
Context success is also solved by at least one of the seven selective
conditions, while six Full Context failures are repaired by at least one
selective condition. This is not a deployable comparison because it selects
the best result after observing seven systems. Against individual conditions,
Full Context still has three to eight exclusive successes.

The per-condition repair and harm quadrants are reused from RQ4. This RQ5
stage does not assign a new causal repair mechanism to Full Context successes:
the any-selective view has no Full-Context-only case, and post-hoc selection
among seven parents cannot identify one deployable counterfactual cause.

## Section-level conclusion

Section 5.6.4 supports a conditional downstream conclusion rather than one
universal bottleneck claim:

- 117 of 205 selective errors do not have demonstrated sufficient final input;
- among the 88 that do, 56 contain an explicit Answerer failure;
- demonstrated packaging loss is limited to nine paths, although 42 more show
  possible noise or ordering pressure;
- E7 preserves most outcomes and can repair complementary Multi-hop or
  Temporal cases, but repair is rare and Harm cannot be equated with fusion
  interference;
- Full Context reaches 46/60 Strict accuracy yet retains six supported
  long-context-use failures, nine sufficient-input answer failures, and five
  ambiguity-limited cases.

These findings establish that retrieval quality and downstream utilisation are
both material. They do not yet assign one primary cause to every error. That
single-count decomposition belongs to the subsequent integrated RQ5 step.

## Formal verification

The downstream audit publishes 205 evidence-sufficiency rows, 205 packaging
rows, 205 Answerer-conversion rows, 120 exact E7 mechanism rows, and a 250-row
post-downstream state register. The Full Context audit publishes 60 unique
question rows, 14 reviewed error rows, 58 evidence-position rows, 32 aggregate
quadrant rows, and a 250-row post-Full-Context state register.

The Full Context v2 audit also fails closed if any of the 60 source records
drifts from its frozen Stage A file hash, canonical-payload hash, record ID,
question identity, or EvidenceBundle identity. Its source manifest binds the
upstream RQ4 and downstream audit files and passed markers as well as all 60
record files.
