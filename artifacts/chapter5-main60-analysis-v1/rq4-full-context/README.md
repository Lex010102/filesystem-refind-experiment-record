# Chapter 5 RQ4: Full Context versus selective retrieval

This directory is the audited, offline input for Section 5.5. It compares the
DeepSeek-family Full Context path with DeepSeek E1--E7 on the same unified
Main-60 questions. The comparison direction is Full Context minus the named
selective condition. E1, E5, and E7 are the principal main-text comparisons;
all seven conditions are retained to avoid selective reporting.

`condition-comparisons` contains the complete paired quality table and
win/tie/loss counts. `question-quadrants` assigns every condition-question
pair to both correct, Full Context only, selective only, or neither correct,
using Strict Accuracy. `quadrant-summary` and `figure-5-8-inputs` aggregate
those states. `category-comparisons` reports the same descriptive analysis for
the four unified question categories. `judge-transitions` preserves movement
among incorrect, partial, and correct labels. `rq5-candidate-cases` contains
identifier-only asymmetric cases; it does not assign a causal failure stage.

Full Context receives all 30 ordered raw sessions and performs no explicit
retrieval. Its source coverage is 100% by construction, but Evidence Recall,
Any-hit, and All-hit are not applicable and remain null. Full Context is not
E8, a memory representation, a retrieval method, or an oracle.

The selective run used served model `deepseek-v4.1-flash`; Full Context used
`deepseek-v4.1-flash-1017`. They share the requested alias and model family but
not the exact served-model identifier. Results are therefore a strong
descriptive diagnostic, not a strict single-variable causal ablation.

This artifact contains no question, answer, evidence, rationale, prompt, or
secret text. It made no API or network call, reran no model, and computed no
bootstrap interval or significance test. Manual failure attribution belongs
to RQ5, and full quality--cost ranking belongs to RQ6.
