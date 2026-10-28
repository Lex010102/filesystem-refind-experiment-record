# Chapter 5 RQ5 Section 5.6.5: Evaluation Disagreement and Metric Sensitivity

## Status and purpose

This offline analysis is complete and formally audited. It asks why Token F1
and the frozen LLM judge sometimes disagree, whether the disagreement comes
from the answer, the reference, or the metric, and whether those cases change
the architectural conclusions reported earlier in Chapter 5.

The analysis does not rescore any answer. It does not call a model or an API,
and it does not modify the frozen token scores or LLM-judge labels. Its
machine-readable source of truth is:

`artifacts/chapter5-main60-analysis-v1/rq5-evaluation-audit/`

The passed audit ID is:

`rq5-eval-audit-8937008b098d65d7f7a30ae1a290b7454aadbe6b738c9812059d1497f4b001f4`

## Population and diagnostic sets

The population contains all 900 frozen Main-60 answers:

- 420 Qwen E1--E7 answers;
- 420 DeepSeek E1--E7 answers;
- 60 DeepSeek-family Full Context answers.

The LLM judge labels 650 answers `Correct`, 74 `Partial`, and 176
`Incorrect`. Four deterministic tails were selected for detailed review:

| Diagnostic screen | Rule | Rows | Unique questions |
|---|---|---:|---:|
| Correct with very low F1 | Correct and F1 < 0.10 | 92 | 21 |
| Partial with very low F1 | Partial and F1 < 0.10 | 31 | 12 |
| Partial with high F1 | Partial and F1 >= 0.50 | 11 | 3 |
| Incorrect with non-trivial F1 | Incorrect and F1 >= 0.10 | 34 | 10 |
| **Total** |  | **168** | — |

The thresholds select cases for diagnosis. They do not define metric error or
Judge error. Each selected row was reviewed against the frozen candidate,
reference, Judge reason, and relevant upstream trace material. Repeated
condition-level rows were grouped by question before assigning a cause.

## Overall relationship between lexical and semantic scores

Token F1 and semantic correctness are positively related, but they are not
interchangeable.

| Frozen Judge label | N | Mean F1 | Median F1 | Q1--Q3 F1 |
|---|---:|---:|---:|---:|
| Correct | 650 | 0.4145 | 0.3333 | 0.1676--0.5714 |
| Partial | 74 | 0.2060 | 0.1483 | 0.0535--0.3054 |
| Incorrect | 176 | 0.0427 | 0.0000 | 0.0000--0.0788 |

The Pearson correlation is 0.4576 between F1 and Strict Accuracy and 0.4737
between F1 and the Soft Semantic Score. These values show useful association,
not evaluator equivalence.

The complete cross-tabulation makes the asymmetry visible:

| Token F1 range | Incorrect | Partial | Correct | Total |
|---|---:|---:|---:|---:|
| [0.00, 0.10) | 142 | 31 | 92 | 265 |
| [0.10, 0.25) | 32 | 18 | 157 | 207 |
| [0.25, 0.50) | 2 | 14 | 203 | 219 |
| [0.50, 0.75) | 0 | 11 | 68 | 79 |
| [0.75, 1.00] | 0 | 0 | 130 | 130 |

Low F1 is therefore not equivalent to semantic failure: 92 correct answers
fall below 0.10. The opposite error is smaller: no Judge-incorrect answer
reaches F1 0.50, and only 34 reach 0.10.

## Why semantically correct answers receive very low Token F1

Of the 92 `Correct` answers below F1 0.10, 87 are genuine lexical
under-credit. The other five belong to two evaluation-sensitive question
families involving a temporal boundary or reference granularity.

The 87 lexical under-credit cases divide into three mechanisms:

| Mechanism | Rows | Share of 87 | Diagnostic explanation |
|---|---:|---:|---|
| Supported elaboration around a short reference | 41 | 47.1% | The candidate gives the requested fact and additional supported explanation. Recall is often high, but the added tokens lower Precision. |
| Date or temporal normalisation | 24 | 27.6% | ISO dates, natural-language dates, and relative calendar expressions are semantically aligned but remain lexically different after normalisation. |
| Semantic paraphrase or morphology | 22 | 25.3% | A synonym, paraphrase, or morphological variant preserves the fact without reproducing the reference tokens. |

Within all 92 Correct/low-F1 cases, the candidate has a median of 22
normalised tokens, whereas the reference has a median of three. The median
candidate-to-reference length ratio is 6.0. This is direct evidence for a
length and granularity mismatch, not proof that length alone caused the low
score.

The backbone pattern is consistent with the earlier F1 analysis. The 92 cases
contain 50 DeepSeek answers, 36 Qwen answers, and six Full Context answers.
The median answer lengths in those groups are 25.5, 19, and 25 tokens,
respectively. DeepSeek therefore appears more often in this tail partly
because its correct answers tend to include more explanation. This supports
the interpretation that DeepSeek's lower aggregate F1 is partly a lexical
Precision effect rather than uniformly lower semantic correctness.

## Genuine partial answers versus reference-sensitive partial labels

The 42 reviewed Partial extremes cannot be treated as one type of metric
failure.

- 22 are genuinely incomplete or non-responsive. They omit a required item,
  attribute, date component, relation, or explicit decision.
- 13 low-F1 cases and seven high-F1 cases are sensitive to reference scope,
  reference granularity, or the Correct/Partial boundary.

The genuine partial cases show why neither low nor high F1 establishes answer
completeness. Some low-F1 answers contain only a small subset of the required
facts. Conversely, four high-F1 answers reproduce much of the reference but
still omit a required list item. Token overlap records shared words; it does
not verify that every requested component is present.

The reference-sensitive cases concentrate in a few question families. A
plural question may have a non-exhaustive reference; a short reference may
omit source-supported specificity; and a relative-week expression may not map
cleanly to the reference's calendar-week wording. These are limits of the
evaluation target, not evidence that all Partial labels are unreliable.

## Why an incorrect answer can still receive non-trivial F1

Thirty-four Judge-incorrect answers have F1 of at least 0.10. Eighteen are
clear lexical over-credit cases:

| Lexical-over-credit mechanism | Rows | Why F1 remains non-zero |
|---|---:|---|
| Correct option copied inside an abstention | 13 | The candidate repeats the reference term but explicitly refuses the requested conclusion. |
| Implicit geography not resolved | 1 | The candidate retrieves the city but does not answer the requested country. |
| Wrong relation | 1 | Shared entities and context words remain, but the required relation is wrong. |
| Wrong cardinality | 1 | The answer frame matches, but the decisive count is wrong. |
| Negated or omitted event | 1 | Related event tokens appear under the wrong polarity. |
| Incidental keyword overlap | 1 | A few shared words occur in an answer about the wrong activity. |

The remaining 16 cases are source- or reference-sensitive rather than simple
token over-credit. Nine reproduce the relevant fact but expose an entity
attribution conflict between the inspected source and the question/reference.
Seven mention the expected entity, place, item, or period but dispute whether
the source establishes the requested predicate or temporal relation.

The central result is therefore asymmetric. Token F1 frequently under-credits
semantically correct answers, especially verbose or paraphrastic ones. It can
also over-credit wrong answers, but the observed high-overlap failure mode is
smaller and never reaches F1 0.50 in this population.

## Reference and annotation limits

The review found three recurring limitations.

1. **Reference scope.** A short or singular reference may not enumerate every
   source-supported response to a plural question.
2. **Reference granularity.** A candidate may add a source-supported location,
   time, or qualifier that the canonical reference omits.
3. **Source--reference alignment.** A small number of questions contain an
   entity, predicate, or time boundary that is not represented identically in
   the source and reference.

These limitations explain individual answer-score disagreements. They do not
change the frozen reference or score. They also do not imply that official
evidence annotations are generally invalid. Evidence Recall remains a
source-location measure and should not be interpreted as a complete semantic
rubric.

## Limited check of LLM-judge boundary sensitivity

This analysis deliberately keeps Judge sensitivity secondary. Across 80 exact
duplicate-input groups containing 305 records, the frozen Judge produces zero
label conflicts. Exact-input consistency is therefore strong in this run.
However, it does not establish stability for semantically similar inputs.

The clearest near-boundary behaviour is concentrated in two question families
and 18 reviewed rows. One concerns relative-week interpretation; the other
concerns whether omission of a secondary qualifier should separate Correct
from Partial. Materially similar answers cross that boundary. The Judge's
reported confidence is not treated as a calibrated probability, and one
frozen Judge run cannot support a claim about inter-judge reliability.

## Does metric disagreement change the architectural conclusions?

The analysis performs a conservative stress test. It removes all nine
questions flagged as evaluation-sensitive from every principal comparison,
reducing each paired denominator from 60 to 51. This is a diagnostic exclusion,
not a corrected estimate and not a replacement score.

The main directions are stable:

- Token F1 direction is preserved in all 17 checked architecture contrasts.
- Strict Accuracy direction is preserved in 15 of 17 contrasts.
- The negative E4−E3 result remains negative for both backbones in F1 and
  Strict Accuracy.
- The negative E6−E5 result remains negative for both backbones in F1 and
  Strict Accuracy.
- The E5−E3 lexical--semantic trade-off remains: F1 is negative while Strict
  Accuracy is positive for both backbones.
- DeepSeek E7 remains better than both E2 and E6 on F1 and Strict Accuracy.
- Qwen E7 remains below E2 and E6 on F1 while its semantic result is more
  favourable.

Two small semantic contrasts are sensitive to the exclusion. Qwen E7−E6 moves
from a Strict tie to a positive difference, while Full Context−E5 moves from a
small positive Strict difference to a small negative one. These contrasts
should therefore remain qualified. In particular, Full Context should not be
declared semantically superior to E5 on the basis of a one-question aggregate
margin.

The evaluation audit does not overturn the central architectural findings. It
does show why Chapter 5 must report Token F1 and semantic metrics separately.
Where they disagree, F1 describes lexical alignment and the LLM judge
describes semantic task completion; neither should silently replace the
other.

## Audit and reproducibility

The implementation is `fs_memory_lab/chapter5_rq5_evaluation.py`. It publishes:

- full score distributions and the Judge-label/F1 cross-tabulation;
- all 168 text-free reviewed disagreement rows;
- cause summaries overall and by question category;
- exact-input Judge consistency diagnostics;
- the 17 architecture-direction stress tests;
- schema, source manifest, diagnostics, audit, and passed marker files.

The public machine-readable tables contain identifiers, metrics, hashes, and
cause codes but no question, answer, reference, evidence, prompt, or Judge
rationale text. The test suite verifies denominators, threshold boundaries,
cause totals, exact-input consistency, architectural anchors, deterministic
rebuilding, content-field exclusion, and tamper rejection.

## Interpretation limits

- The four screens are diagnostic tails, not an exhaustive manual review of
  all 900 answers.
- Repeated rows from the same question are not independent evidence for a
  distinct cause; cause interpretation is grouped by question family.
- Exact duplicate consistency does not establish robustness near a semantic
  boundary.
- The nine-question exclusion is a conservative sensitivity analysis, not an
  alternative official evaluation.
- No claim is made that answer length alone causes lower F1.
- The official scores remain unchanged; this analysis explains their scope
  and failure modes.
