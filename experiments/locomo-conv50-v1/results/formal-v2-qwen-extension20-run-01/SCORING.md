# Deterministic LoCoMo scoring for extension-20

The official category-aware LoCoMo token/stem evaluator was run offline over the 140
append-only extension records. No API call was made.

| Condition | Precision | Recall | F1 |
| --- | ---: | ---: | ---: |
| E1 | 0.3994 | 0.6765 | 0.4554 |
| E2 | 0.3496 | 0.6549 | 0.4150 |
| E3 | 0.4311 | 0.7329 | 0.4941 |
| E4 | 0.3328 | 0.6713 | 0.3938 |
| E5 | 0.4156 | 0.7794 | 0.4867 |
| E6 | 0.3589 | 0.7024 | 0.4252 |
| E7 | 0.3647 | 0.6719 | 0.4311 |
| **Overall** | **0.3789** | **0.6985** | **0.4430** |

The authoritative outputs are `run/evaluation.json` and
`run/locomo-prf-summary.json`. These scores cover extension-20 only; they are not the
combined Model 1 main-60 aggregate.
