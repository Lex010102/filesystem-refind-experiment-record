# Semantic scoring summary

One anonymous Judge assigns exactly one label to every candidate answer:

- `correct` maps to strict=1 and soft=1.0;
- `partial` maps to strict=0 and soft=0.5;
- `incorrect` maps to strict=0 and soft=0.0.

For each condition with 40 answers:

- `Strict Accuracy = correct / 40`;
- `Partial Rate = partial / 40`;
- `Soft Semantic Score = (correct + 0.5 × partial) / 40`.

| Condition | Correct | Partial | Incorrect | Strict Accuracy | Partial Rate | Soft Semantic Score | Judge tokens |
|---|---:|---:|---:|---:|---:|---:|---:|
| E1 | 24 | 9 | 7 | 0.6000 | 0.2250 | 0.7125 | 26,052 |
| E2 | 20 | 11 | 9 | 0.5000 | 0.2750 | 0.6375 | 23,668 |
| E3 | 25 | 9 | 6 | 0.6250 | 0.2250 | 0.7375 | 23,889 |
| E4 | 25 | 6 | 9 | 0.6250 | 0.1500 | 0.7000 | 24,337 |
| E5 | 25 | 8 | 7 | 0.6250 | 0.2000 | 0.7250 | 29,249 |
| E6 | 25 | 5 | 10 | 0.6250 | 0.1250 | 0.6875 | 26,931 |
| E7 | 24 | 9 | 7 | 0.6000 | 0.2250 | 0.7125 | 28,825 |

The overall run produced 168 correct, 57 partial and 55 incorrect judgments using 182,951 Judge tokens. These semantic scores supplement rather than replace the deterministic LoCoMo category-aware token/stem F1 in the source formal run.
