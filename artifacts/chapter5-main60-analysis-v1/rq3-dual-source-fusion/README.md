# Chapter 5 RQ3: dual-source fusion

This directory is the audited, offline input for Section 5.4. It compares E7
with each of its two parent paths, E2 and E6, on the same unified Main-60
questions under both Qwen and DeepSeek.

`parent-effects` and `table-5-14-inputs` report paired E7-minus-parent answer
and Evidence Recall effects. `category-effects` reports the same contrasts by
the four unified question categories and is exploratory. `judge-transitions`
retains incorrect/partial/correct changes rather than collapsing all semantic
movement into Strict Accuracy.

`fusion-outcomes` classifies each question by Strict Accuracy as Repair,
Preserve, Harm, or Unresolved. Preserve means that at least one correct parent
remained correct; it does not mean that E7 exceeded both parents.
`figure-5-6-inputs` preserves the four parent-correctness profiles needed for
the flow diagram. `question-diagnostics` and `rq5-candidate-cases` contain
identifiers and numeric diagnostics only; causal review is deferred to RQ5.

`evidence-source-overlap` uses retrieved dialogue source IDs. It does not
measure evidence-text similarity and cannot by itself identify semantic
conflict. Gold IDs are annotated source locations, not complete reasoning
chains. Harm rows are therefore possible-interference candidates, not proven
conflict cases.

E7 performs no new search action. Its recorded retrieval calls and tokens are
the inherited sum of the E2 and E6 upstream retrievals, followed by one shared
Answerer call. This artifact contains no question, answer, evidence, rationale,
or secret text. It made no API or network call, reran no model, and computed no
new bootstrap interval or significance test. Cost ranking belongs to RQ6;
failure-stage attribution belongs to RQ5; Full Context belongs to RQ4.
