# Chapter 5 RQ5 Stage 1: unified case and error index

This immutable artifact implements Section 5.6.1. `case-index` contains all
900 audited Main-60 answer records. `strict-error-cases` is the exact
Strict-noncorrect subset: 250 rows, comprising both Partial and Incorrect LLM
judge labels. `question-packets` groups conditions by backbone and question so
later stages can compare an error with its same-question counterfactuals.
`error-census` freezes all denominators by answer set, condition, category,
and gold-evidence eligibility.

`root-cause-state-register` contains the same 250 errors with a condition-aware
state skeleton. All applicable analytical states and all causal attributions
remain `pending`; non-applicable stages are explicit. `state-model.json`
defines the ordered chain, applicability rules, allowed root-cause vocabulary,
and earliest-supported-break contract. Section 5.6.1 does not assign a root
cause and does not treat low Evidence Recall as causation.

E1--E6 have independent retrieval paths. E7 reuses the same-question E2 and
E6 EvidenceBundles and performs no new retrieval. Full Context receives the
complete raw history and has no retriever or selective EvidenceBundle, so its
Evidence Recall is not applicable.

The artifact contains source identifiers, hashes, metrics, and process counts
only. It contains no question, answer, evidence, prompt, rationale, or secret
text. It made no API or network call, reran no model, modified no formal run,
and computed no new statistical inference.
