# Formal-v1 scoring result

The 280 final records have been scored offline with the frozen official LoCoMo
category-aware token/stem F1 evaluator. The final audit passed and no LLM judge
was used.

| Condition | micro F1 | category macro F1 | post-stratified F1 | evidence recall | total tokens |
|---|---:|---:|---:|---:|---:|
| E1 | 0.3646 | 0.3373 | 0.4396 | 0.8092 | 6,072,586 |
| E2 | 0.3972 | 0.3667 | 0.4678 | 0.7325 | 737,484 |
| E3 | 0.4146 | 0.3866 | 0.4842 | 0.8202 | 6,008,177 |
| E4 | 0.3971 | 0.3662 | 0.4701 | 0.7303 | 736,746 |
| E5 | 0.3488 | 0.3267 | 0.4082 | 0.9254 | 11,764,087 |
| E6 | 0.3594 | 0.3386 | 0.4094 | 0.8158 | 1,575,125 |
| E7 | 0.3380 | 0.3178 | 0.3895 | 0.8860 | 2,259,475 |

The primary formal-v1 aggregate is `micro_f1`. All seven conditions have
citation validity 1.0. Provider-reported deployment usage totals 29,153,680
tokens across 280 records.

Machine-readable outputs:

- `run/evaluation.json`: all 280 per-record scores plus condition summaries;
- `run/final-audit.json`: final passed audit;
- `run/events.jsonl`: includes the finalization event.

The full Chinese result interpretation and efficiency tables are in
`docs/progress/2026-10-11-formal-v1-scoring-results.md` in the repository.
