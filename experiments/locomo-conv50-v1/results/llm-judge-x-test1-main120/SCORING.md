# Unified Judge results

| System | Correct | Partial | Incorrect | Strict | Partial Rate | Soft |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Model 1 / Qwen | 305 | 30 | 85 | 0.7262 | 0.0714 | 0.7619 |
| Model 2 / DeepSeek | 299 | 37 | 84 | 0.7119 | 0.0881 | 0.7560 |

Condition-level scores:

| Condition | Model 1 Strict | Model 1 Soft | Model 2 Strict | Model 2 Soft |
| --- | ---: | ---: | ---: | ---: |
| E1 | 0.7167 | 0.7667 | 0.7500 | 0.8083 |
| E2 | 0.6667 | 0.7167 | 0.7000 | 0.7083 |
| E3 | 0.7500 | 0.7917 | 0.7000 | 0.7583 |
| E4 | 0.7000 | 0.7250 | 0.6667 | 0.7083 |
| E5 | 0.7833 | 0.8167 | 0.7500 | 0.8000 |
| E6 | 0.7333 | 0.7583 | 0.6667 | 0.7083 |
| E7 | 0.7333 | 0.7583 | 0.7500 | 0.8000 |

The authoritative detailed outputs are each run's `results.json`, `verification.json`, and
`final-audit.json`.
