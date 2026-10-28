# Chapter 5 RQ6: quality, cost, and practical system choice

This audited artifact performs the final offline RQ6 synthesis over the frozen
Main-60 results. It reports observed quality and query resources, S1--S3
construction cost, E7's incremental and reconstructed-online cost views,
conditional construction amortisation, Pareto membership, and a scenario-based
decision matrix.

The central result is conditional rather than a single ranking. E2 is the
lowest-token online path under both backbones but gives up semantic quality.
E5 is the Qwen quality-and-coverage option, with very high S3 construction and
query cost. Under DeepSeek, E7 is the strongest selective quality--token
compromise, while E1 retains slightly higher Soft score and F1. Full Context
has the highest DeepSeek-family Strict and Soft scores, but the lead is one
question, its served-model identifier differs, and its F1 is lower than several
selective systems. It is therefore a diagnostic or recovery path rather than a
universal retrieval replacement.

No cross-condition latency, monetary, or numeric maintenance ranking is
inferred. Recovery usage is reported separately for 39 of 41 formal
failed attempts; two DNS failures have unknown token usage. Judge tokens are
evaluation-only and remain separate from deployment query cost. No API or
network call was made, and no experiment output was modified.
