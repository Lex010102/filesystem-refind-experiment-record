# Chapter 5 Stage A: frozen Main-60 analysis table

This directory is the audited, question-level input for later Chapter 5
analysis. It contains 900 answer paths: 420 Qwen E1--E7 rows, 420 DeepSeek
E1--E7 rows, and 60 DeepSeek-family Full Context rows.

`e1-e7-main.*` is the symmetric 840-row E1--E7 view. `rq1-analysis-view.*`
is the 720-row E1--E6 input for RQ1. E7 belongs to the later fusion analysis;
Full Context belongs to the later diagnostic comparison. No paired effect,
bootstrap interval, rank, or report conclusion is computed in Stage A.

Token Precision and Recall are recomputed for all 900 answers with the same
category-aware alignment described in Chapter 4. The pinned LoCoMo F1 is also
recomputed and checked against every source evaluation row. The computation
reads answer and reference text only in memory. No question, reference answer,
candidate answer, evidence text, or Judge rationale is persisted here.

Answer metrics use 60 questions per answer path. Evidence Recall, Any-hit, and
All-hit use the fixed 58-question eligibility mask. Full Context has complete
source visibility by construction but has no retrieval metrics; its evidence
metrics remain null. Native per-answer latency is unavailable for E1--E7 and
is therefore null rather than inferred from event timestamps.

Physical main40/extension20 labels are retained only as provenance. All report
analysis treats the questions as one unified Main-60 test set.
