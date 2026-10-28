# Chapter 5 Stage D automatic mechanism analysis

This directory is the audited **automatic phase** of Stage D. It contains the
frozen comparison register, Evidence-to-answer conversions, hit/Strict and
multi-source transitions, descriptive C1--C4 matrices, E1--E6 process
summaries, and deterministic identifier-only candidates for bounded manual
trace review.

All simple effects are target minus baseline and remain separated by backbone.
The seven main simple comparisons, the storage--retrieval interaction, and the
two appendix sensitivity comparisons are kept in distinct roles. Answer
denominators are 60, Evidence denominators are 58, and the frozen multi-source
subset is 19. Category outputs are descriptive and contain no new bootstrap.

R1 rounds and filesystem calls are native R1 units. R2/R3 actions are a
separate native unit; noncommensurate endpoints receive no paired difference.
Native E1--E6 latency and failed-attempt token amounts are unavailable and are
published explicitly as such. Successful query-token totals exclude failed
attempt tokens.

No question, reference answer, candidate answer, Evidence text, Judge
rationale, source-trace content, or secret is copied into the machine-readable
tables. No API is called and no formal source is modified.

`STAGE-D-AUTO.PASSED` certifies only the deterministic automatic computation.
Every trace-review candidate remains `pending`. This artifact deliberately
does not contain `STAGE-D.PASSED`; that marker is reserved for a later bounded
manual-review finalizer.
