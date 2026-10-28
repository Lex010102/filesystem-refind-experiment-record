# Chapter 5 RQ2: cross-backbone robustness

This directory is the audited, offline input for Section 5.3. It compares the
Qwen and DeepSeek end-to-end pipelines on the unified Main-60 E1--E7 test set.

`condition-backbone-comparison` reports F1, Strict Accuracy, and Soft Semantic
Score for the two backbones under the same condition. `lexical-explanation`
contains Precision, Recall, and normalised answer length only to explain major
lexical--semantic disagreement. `architecture-stability` reuses six audited
RQ1 contrasts and reports each model-specific effect plus the descriptive
cross-backbone difference. `table-5-13-inputs` is the report-ready copy of the
same six stability rows.

All deltas in the first two tables are DeepSeek minus Qwen. Cross-backbone
architecture differences are the DeepSeek effect minus the Qwen effect.
Stability labels describe observed directions across these two pipelines; they
are not tests of statistical significance or universal backbone invariance.

E7 appears only in the condition overview. E7 fusion effects belong to RQ3.
Full Context is absent because no symmetric Qwen Full Context run exists.
This artifact contains no question, answer, evidence, rationale, or secret
text. It made no API or network call and computed no new bootstrap interval.
