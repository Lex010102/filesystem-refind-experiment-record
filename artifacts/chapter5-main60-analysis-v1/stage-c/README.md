# Chapter 5 Stage C: curated-memory comparisons

This directory contains the audited within-backbone Stage C comparisons for
S3 Agent-Curated Memory. Five target-minus-baseline contrasts are fixed in
`contrast-register`: one core S3 access-system contrast, two main descriptive
complete-system anchors, and two appendix sensitivity anchors.

Answer metrics use all 60 unified Main-60 questions. Evidence metrics use the
fixed 58-question Evidence-eligible mask. Multi-gold-source metrics use the
frozen 19-question subset with more than one distinct gold dialogue-turn ID.
Only E5 and E6 condition summaries are published here. E1--E4 endpoint means
are independently recomputed from Stage A and checked against the formal Stage
B condition summaries before any Stage C output is published.

Partial Rate and EvidenceBundle length are neutral descriptive metrics. They
therefore receive increase/same/decrease counts but no quality-oriented
win/tie/loss labels. Strict transitions treat both `partial` and `incorrect`
as `not_correct`; the separate 3x3 semantic matrix preserves all three labels.

No bootstrap interval, interaction, category effect, pooled-backbone effect,
E7, Full Context, cost, or error-stage analysis is computed in Stage C. No API
is called, no formal source result is modified, and no question, answer,
Evidence text, or Judge rationale is copied into these artifacts.
