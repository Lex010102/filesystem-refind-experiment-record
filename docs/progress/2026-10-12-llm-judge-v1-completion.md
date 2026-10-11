# 2026-10-12 LLM-as-Judge v1 完成记录

## 1. 完成状态

补充语义评分 `llm-judge-v1-main40-run-01` 已完成：

- 来源：`formal-v1-main40-run-02` 的 280 条冻结回答；
- 规模：E1–E7 各 40 条，共 280/280；
- 运行：8/8 batches passed；
- 活跃失败：0；
- 校验：`verification.json` status=`passed`；
- 最终审计：`final-audit.json` status=`passed`；
- requested model：`coding`；
- served model：`qwen3.8:27b`；
- Judge 总 tokens：182,951；
- 总标签：correct 168、partial 57、incorrect 55。

Judge 在输入中隐藏 condition、存储和检索方法，只看到问题、参考答案和候选答案。每条只生成一个 `correct / partial / incorrect` 标签，再映射出 Strict 和 Soft 指标。

## 2. 条件汇总

| 条件 | correct | partial | incorrect | Strict Accuracy | Partial Rate | Soft Semantic Score | Judge tokens |
|---|---:|---:|---:|---:|---:|---:|---:|
| E1 | 24 | 9 | 7 | 0.6000 | 0.2250 | 0.7125 | 26,052 |
| E2 | 20 | 11 | 9 | 0.5000 | 0.2750 | 0.6375 | 23,668 |
| E3 | 25 | 9 | 6 | 0.6250 | 0.2250 | 0.7375 | 23,889 |
| E4 | 25 | 6 | 9 | 0.6250 | 0.1500 | 0.7000 | 24,337 |
| E5 | 25 | 8 | 7 | 0.6250 | 0.2000 | 0.7250 | 29,249 |
| E6 | 25 | 5 | 10 | 0.6250 | 0.1250 | 0.6875 | 26,931 |
| E7 | 24 | 9 | 7 | 0.6000 | 0.2250 | 0.7125 | 28,825 |

计算方式：

- `Strict Accuracy = correct / 40`；
- `Partial Rate = partial / 40`；
- `Soft Semantic Score = (correct + 0.5 × partial) / 40`。

## 3. 追溯与完整性

本地权威运行路径：

`local-runs/llm-judge-v1/llm-judge-v1-main40-run-01/`

GitHub 可公开归档：

`experiments/locomo-conv50-v1/results/llm-judge-v1-main40-run-01/`

归档包括 280 个逐题 JSON、`results.json`、manifest、events、status、8 个 batch audit/PASSED/log、verification 和 final audit。API key 从未写入运行结果。公开归档不包含 PID、运行锁、空 launcher 日志或本机 shell 历史。

完整的数据分析计划另见 [E1–E7 结果分析框架与论文写作地图](../analysis/e1-e7-results-analysis-framework.md)。
