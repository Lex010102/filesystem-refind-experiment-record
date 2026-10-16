# Deterministic LoCoMo scoring

The official category-aware LoCoMo token/stem evaluator was run offline over all 420 final
records. No API call was made.

| Condition | Precision | Recall | F1 |
| --- | ---: | ---: | ---: |
| E1 | 0.2345 | 0.7003 | 0.3013 |
| E2 | 0.1720 | 0.7023 | 0.2455 |
| E3 | 0.2315 | 0.6824 | 0.2971 |
| E4 | 0.1630 | 0.6504 | 0.2314 |
| E5 | 0.1930 | 0.7389 | 0.2604 |
| E6 | 0.1630 | 0.6084 | 0.2240 |
| E7 | 0.2128 | 0.7364 | 0.2854 |
| **Overall** | **0.1957** | **0.6884** | **0.2636** |

The authoritative machine-readable outputs are `run/evaluation.json` and
`run/locomo-prf-summary.json`. F1 is the mean of per-record official F1 values and must not
be reconstructed from the aggregate Precision and Recall shown above.
