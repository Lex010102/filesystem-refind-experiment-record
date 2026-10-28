# Chapter 5 RQ6: Quality, Cost, and Practical System Choice

## Status and scope

RQ6 is complete as an audited offline analysis over the unified Main-60 test
set. It combines the frozen quality results from RQ1--RQ4, the root-cause
findings from RQ5, successful-query resource records, S1--S3 construction
costs, and formal recovery artifacts. It made no model or network call and did
not modify any formal answer or score.

The analysis answers one practical question: **which condition should be used
when semantic quality, lexical agreement, construction cost, and online query
cost cannot all be optimised at the same time?**

Machine-readable source of truth:

`artifacts/chapter5-main60-analysis-v1/rq6-quality-cost/`

Independent audit:

`rq6-audit-49036128531db43c3bcb83e8e7f2f8f75b6258ebbfc0dda01899dd20352a1f25`

## Analysis procedure

The procedure has four steps.

1. Aggregate Token F1, Strict Accuracy, Soft Semantic Score, model calls, and
   tokens over the same 60 questions for every condition and backbone.
2. Keep construction, successful-query, recovery, and LLM-judge costs in
   separate accounts. Judge cost is evaluation-only and is not part of
   deployment cost.
3. Identify Pareto-efficient conditions separately for each backbone and each
   quality metric. The primary cost axis is mean query tokens; model-call count
   is secondary because one long-context call is not equivalent to one short
   call.
4. Translate the Pareto results, RQ5 bottleneck findings, and construction
   amortisation into conditional system recommendations.

E7 uses its reconstructed online cost: E2 retrieval plus E6 retrieval plus one
fused Answerer. Parent Answerer calls are excluded. Full Context is included
only as a DeepSeek-family diagnostic condition because its served-model
identifier differs from the selective DeepSeek run.

## Observed quality and successful-query cost

### Qwen

| Condition | Token F1 | Strict | Soft | Mean query tokens | Mean model calls |
|---|---:|---:|---:|---:|---:|
| E1 | 0.395 | 0.717 | 0.767 | 148,920 | 12.50 |
| E2 | 0.403 | 0.667 | 0.717 | **18,419** | 4.93 |
| E3 | **0.441** | 0.750 | 0.792 | 140,288 | 11.67 |
| E4 | 0.396 | 0.700 | 0.725 | 18,479 | 4.98 |
| E5 | 0.395 | **0.783** | **0.817** | 281,354 | 8.05 |
| E6 | 0.381 | 0.733 | 0.758 | 36,378 | **4.83** |
| E7 | 0.369 | 0.733 | 0.758 | 53,637 | 8.77 |

E2 is the cheapest online path, but E3 is the more useful Qwen balance. Relative
to E1, E3 raises F1 by 0.046, Strict by 0.033, and Soft by 0.025 while reducing
successful-query tokens by 5.8%. E5 adds another 0.033 Strict and 0.025 Soft
over E3, but doubles query tokens, reduces F1 by 0.046, and requires the much
more expensive S3 store. E5 is therefore a semantic-quality maximum, not the
default cost-effective condition.

### DeepSeek and the Full Context diagnostic

| Condition | Token F1 | Strict | Soft | Mean query tokens | Mean model calls |
|---|---:|---:|---:|---:|---:|
| E1 | **0.301** | 0.750 | **0.808** | 201,030 | 12.98 |
| E2 | 0.246 | 0.700 | 0.708 | **17,313** | 5.00 |
| E3 | 0.297 | 0.700 | 0.758 | 189,646 | 12.70 |
| E4 | 0.231 | 0.667 | 0.708 | 17,458 | 5.00 |
| E5 | 0.260 | 0.750 | 0.800 | 374,700 | 8.90 |
| E6 | 0.224 | 0.667 | 0.708 | 35,457 | 5.00 |
| E7 | 0.285 | **0.750** | 0.800 | 51,581 | 9.00 |
| Full Context* | 0.245 | **0.767** | **0.825** | 36,646 | **1.00** |

\* Full Context is a same-family diagnostic comparison, not an exact
served-model ablation.

E7 is the strongest DeepSeek **selective query-time** compromise. It matches
E1's Strict Accuracy, remains only 0.008 lower in Soft score and 0.016 lower in
F1, but uses 74.3% fewer successful-query tokens. Compared with E2, E7 gains
0.050 Strict, 0.092 Soft, and 0.040 F1 at 2.98 times the query tokens. This is a
clear cost--quality step rather than a universally free improvement.

Full Context has the highest observed DeepSeek-family semantic scores and uses
fewer tokens than E7 in this fixed 30-session setting. Its Strict lead over E7
is one question, while its F1 is 0.041 lower. Together with the served-model
mismatch and the fixed context length, this supports its use as a diagnostic or
recovery path, not a universal claim that retrieval should be removed.

## Construction and recovery cost

| Store | One-time model calls | One-time model tokens | Interpretation |
|---|---:|---:|---|
| S1 | 0 | 0 | No model-based construction; deterministic processing is not measured as zero total system cost. |
| S2 | 12 | 395,749 | Small organisation cost; raw session bytes remain unchanged. |
| S3 | 842 | 30,864,958 | Large curation cost; long-term update cost was not measured. |

S2 is inexpensive enough to change the Qwen decision. E3's cumulative token
cost falls below E1 after 46 Qwen queries, and E3 is already better on all three
quality measures. The same accounting crossover occurs after 35 DeepSeek
queries, but DeepSeek E3 is lower quality than E1; the crossover alone is not a
recommendation.

S3 changes the result only at larger reuse volumes. Against expensive E1,
E6/E7 amortise after 275/324 Qwen queries and 187/207 DeepSeek queries,
respectively. They never become token-saving alternatives to the low-cost E2
path, and E5 has no token break-even because its construction and query costs
are both higher than E1. These are token-accounting thresholds, not claims of
quality equivalence.

Formal recovery cost is also non-negligible:

| Backbone | Condition | Failed attempts | Usage known | Usage unknown | Known recovery tokens |
|---|---|---:|---:|---:|---:|
| Qwen | E1 | 1 | 1 | 0 | 87,303 |
| Qwen | E3 | 5 | 5 | 0 | 702,070 |
| Qwen | E5 | 12 | 10 | 2 | 2,245,594 |
| DeepSeek | E1 | 12 | 12 | 0 | 1,973,003 |
| DeepSeek | E3 | 6 | 6 | 0 | 707,690 |
| DeepSeek | E5 | 5 | 5 | 0 | 4,410,698 |
| **Total** |  | **41** | **39** | **2** | **10,126,358** |

All observed failures occur on R1 conditions. The two unknown attempts are DNS
failures and are not assigned zero tokens. Recovery tokens remain separate from
successful-query cost, so the 10.13 million total is a measured lower bound.
This strengthens the practical case for simpler R2/R3 paths when their quality
is sufficient.

## Pareto result

Using successful-query tokens as the primary cost axis, the semantic Pareto
frontiers are:

| Scope | Strict frontier, low to high cost | Soft frontier, low to high cost |
|---|---|---|
| Qwen selective | E2 -> E4 -> E6 -> E3 -> E5 | E2 -> E4 -> E6 -> E3 -> E5 |
| DeepSeek selective | E2 -> E7 | E2 -> E7 -> E1 |
| DeepSeek-family diagnostic | E2 -> Full Context | E2 -> Full Context |

The F1 frontiers differ: Qwen retains only E2 and E3, while DeepSeek retains
E2, E7, E3, and E1. This difference confirms that lexical and semantic quality
must not be collapsed into one score.

RQ5 also explains why the most expensive retrieval path should not be selected
automatically. Among 123 confirmed internal breakpoints, 68 (55.3%) are
Answerer-utilisation failures and 42 (34.1%) are Retrieval failures. More
retrieval work cannot repair evidence that is already present but used
incorrectly.

## Direct answer to RQ6

There is no context-free winner. The evidence supports the following compact
decision rule.

1. **Minimum online cost:** use E2. It is the lowest-token path under both
   backbones, with a measurable semantic-quality trade-off.
2. **Best Qwen balance:** use E3 once the modest S2 build is amortised. It
   improves all three quality metrics over E1 and is cheaper cumulatively after
   46 queries.
3. **Maximum Qwen semantic quality:** use E5 only when its additional semantic
   gain justifies the S3 construction, query, and recovery burden.
4. **Best DeepSeek selective query-time balance:** use E7 when S3 already
   exists or is reused at sufficient scale. It preserves E1-level Strict
   Accuracy with 74.3% fewer query tokens.
5. **No-build DeepSeek quality baseline:** use E1 when provenance and quality
   matter but S3 construction cannot be amortised.
6. **Diagnostic or recovery path:** use Full Context for suspected retrieval
   omission or difficult evidence composition. Its result is promising but is
   not an exact-model proof that complete context should replace retrieval.

The primary recommendation is therefore **conditional routing by objective**,
not a single global champion.

## Boundaries

- E1--E7 lack comparable native latency records, so no latency ranking is
  reported.
- No common monetary price schedule was defined; token counts are not dollar
  costs.
- Two DNS failures lack token usage, so recovery cost is a lower bound.
- Long-term memory update and maintenance cost was not executed.
- Full Context used a different served-model identifier within the same model
  family and is reported only as a diagnostic comparison.
