# RQ5 Integrated Bottleneck Decomposition

This directory contains the audited offline integration for Section 5.6.6.
It assigns one primary breakpoint to each Strict-noncorrect path and records
supported co-occurring mechanisms separately.

Primary cause counts:

- `storage`: 0
- `retrieval`: 42
- `packaging`: 7
- `answerer`: 68
- `fusion_or_long_context`: 6
- `evaluation_sensitive`: 53
- `mixed_or_indeterminate`: 74

Important guards:

- retrieval diagnostics are not treated as causation without final-input insufficiency;
- a source/reference entity mismatch invalidates retrieval-failure attribution based on that locator;
- E7 harm is not automatically assigned to the fusion operation;
- unscreened evaluation cases are not treated as evaluator agreement;
- the 12 shared representation limitations are not store-specific failures.

No model, API, or network call is used by this stage.
