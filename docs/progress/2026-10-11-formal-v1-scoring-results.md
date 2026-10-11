# 2026-10-11 formal-v1 main-40 评分结果

## 1. 评分完成状态

`formal-v1-main40-run-02` 已在 280/280 条最终 RunRecord 上完成纯离线评分，`final-audit.json` 状态为 `passed`。

- 题目：LoCoMo `conv-50` main-40；
- 条件：E1–E7，每个条件 40 题；
- 主指标：官方 LoCoMo category-aware token/stem F1；
- 主聚合方式：每个条件在 40 题上的 `micro_f1`；
- 附加聚合：四类题 `category_macro_f1` 和按 LoCoMo10 类别规模加权的 `post_stratified_f1`；
- 证据指标：Evidence Recall、Any-hit、All-hit 和 citation validity；
- 效率指标：tokens、model calls、retrieval rounds/actions、evidence characters、cap/empty/budget-skip；
- formal-v1 不使用 LLM-as-Judge，因此 judge 字段为 `null`、judge tokens 为 0。

评分使用冻结的 LoCoMo 官方 evaluator：

- repository: `https://github.com/snap-research/locomo`
- commit: `cbfbc1dba6bc53d00625212a0f22d55ffee7c1fc`
- file: `task_eval/evaluation.py`
- evaluator SHA-256: `8e3be5d57ff2ff9ec5cd05939592f468c5f3f1fd95d13e431932bdf6bf0fd6fd`
- NLTK: `3.8.1`

## 2. 主结果

F1 的范围是 0–1，越高越好。下表保留四位小数；例如 0.4146 也可写成 41.46%。

| 条件 | 存储 + 检索 | micro F1（主指标） | category macro F1 | post-stratified F1 | Evidence Recall | Any-hit | All-hit | Citation validity |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| E1 | S1 + R1 | 0.3646 | 0.3373 | 0.4396 | 0.8092 | 0.8947 | 0.7368 | 1.0000 |
| E2 | S1 + R2 | 0.3972 | 0.3667 | 0.4678 | 0.7325 | 0.7632 | 0.6842 | 1.0000 |
| E3 | S2 + R1 | **0.4146** | **0.3866** | **0.4842** | 0.8202 | 0.8684 | 0.7632 | 1.0000 |
| E4 | S2 + R2 | 0.3971 | 0.3662 | 0.4701 | 0.7303 | 0.7895 | 0.6579 | 1.0000 |
| E5 | S3 + R1 | 0.3488 | 0.3267 | 0.4082 | **0.9254** | **0.9737** | **0.8947** | 1.0000 |
| E6 | S3 + R3 | 0.3594 | 0.3386 | 0.4094 | 0.8158 | 0.8947 | 0.7368 | 1.0000 |
| E7 | E2 + E6 证据融合 | 0.3380 | 0.3178 | 0.3895 | 0.8860 | 0.9474 | 0.8158 | 1.0000 |

40 题包含 category 1/2/3/4 各 10/10/7/13 题。分类 F1 如下：

| 条件 | C1 multi-hop | C2 temporal | C3 open-domain | C4 single-hop |
|---|---:|---:|---:|---:|
| E1 | 0.4083 | 0.1444 | 0.2166 | 0.5801 |
| E2 | 0.5233 | 0.2078 | 0.1644 | 0.5711 |
| E3 | 0.4298 | 0.3036 | 0.2198 | 0.5932 |
| E4 | 0.4940 | 0.2252 | 0.1667 | 0.5789 |
| E5 | 0.3930 | 0.1746 | 0.2223 | 0.5169 |
| E6 | 0.4782 | 0.1709 | 0.2144 | 0.4910 |
| E7 | 0.4390 | 0.1432 | 0.2094 | 0.4795 |

## 3. Token 和运行效率

Token 是 provider 返回的使用量，包含检索模型和统一 Answerer。E7 按冻结规则计算 E2 + E6 retrieval 各一次，再加 E7 Answerer；不重复计入 E2/E6 Answerer。

| 条件 | 总 tokens | 平均/题 | 中位数/题 | P95/题 | retrieval tokens | answer tokens | 平均 model calls |
|---|---:|---:|---:|---:|---:|---:|---:|
| E1 | 6,072,586 | 151,814.6 | 109,099 | 360,975 | 5,986,561 | 86,025 | 12.95 |
| E2 | 737,484 | 18,437.1 | 18,595 | 24,111 | 601,284 | 136,200 | 4.95 |
| E3 | 6,008,177 | 150,204.4 | 129,740 | 304,698 | 5,926,331 | 81,846 | 12.53 |
| E4 | **736,746** | **18,418.7** | 17,849 | 23,781 | 610,412 | 126,334 | 4.97 |
| E5 | 11,764,087 | 294,102.2 | 263,934 | 490,639 | 11,622,531 | 141,556 | 8.20 |
| E6 | 1,575,125 | 39,378.1 | 36,335 | 62,412 | 1,363,903 | 211,222 | 4.83 |
| E7 | 2,259,475 | 56,486.9 | 53,464 | 78,179 | 1,965,187 | 294,288 | 8.78 |

- 280 条合计 29,153,680 tokens；
- retrieval 28,076,209，Answerer 1,077,471；
- 总 model calls 2,288；
- E4 的总 token 最低，但与 E2 几乎相同；
- E6 比 E5 节省 86.61% token（E5 约是 E6 的 7.47 倍），同时 micro F1 高 0.0106；
- E2 比 E1 节省 87.86% token，micro F1 高 0.0325；
- E4 比 E3 节省 87.74% token，但 micro F1 低 0.0175。

## 4. 检索运行诊断

| 条件 | cap | 空证据 | budget-skip episodes | 平均 evidence chars | 平均 evidence items | insufficient answers |
|---|---:|---:|---:|---:|---:|---:|
| E1 | 7 | 0 | 0 | 1,168.8 | 3.15 | 5 |
| E2 | 33 | 3 | 0 | 5,097.4 | 2.73 | 8 |
| E3 | 7 | 1 | 0 | 1,223.9 | 3.08 | 4 |
| E4 | 31 | 5 | 1 | 5,244.6 | 2.70 | 9 |
| E5 | 0 | 0 | 1 | 4,557.9 | 3.25 | 6 |
| E6 | 32 | 1 | 22 | 9,895.6 | 3.05 | 8 |
| E7 | N/A | 1 | N/A | 14,993.0 | 5.78 | 7 |

E1–E6 没有发生 evidence item 文本截断。`budget-skip` 表示完整 item 因放不下而整个跳过，不是将 item 从中间切断。证据指标的分母是 38 题；两道缺完整 gold evidence 的 open-domain 题仍参加 F1，但不参加 Evidence Recall/Any-hit/All-hit。

## 5. 描述性发现

以下是当前 40 题的描述性结果，尚未做显著性推断：

1. E3（S2 + R1）的主 F1 最高，比 E1（S1 + R1）高 0.0500；文件夹化对 R1 在这组数据上有正向结果。
2. E2 与 E4 的 F1 几乎一样（相差 0.00005），说明在 R2 下，S1/S2 的目录差异没有带来明显的描述性差距。
3. E5 的 Evidence Recall 最高，但它的 F1 不高且 token 最大。“看到更多 gold evidence”并没有自动变成更好的最终回答。
4. E6 相对 E5 同时提高 F1 并大幅减少 token，但 Evidence Recall 下降；它表现出更好的效果–成本折中。
5. E7 提高了相对 E6 的 Evidence Recall，但 F1 下降且 token 增加 43.45%。当前的确定性双源融合并没有修复最终答案，这是后续错误归因的重点。

## 6. 运行时间的可用边界

RunRecord 冻结了 token/call/round 指标，但没有冻结 provider 端精确 latency。可以从 `events.jsonl` 的最后一次 `record_started` 到 `record_verified` 计算“最终成功尝试的墙钟时间”，但它不包含早先失败尝试、VPN/API 等待和人工停顿，也不是纯 provider latency。E7 的事件时间只包含确定性融合和 Answerer，因为上游 E2/E6 检索已经完成，所以不能与 E1–E6 直接比较端到端 latency。论文效率主表应优先使用 provider-reported tokens、calls 和 rounds/actions。

## 7. 结果文件与完整性

- `evaluation.json`：280 条逐题评分及 E1–E7 汇总；
- `final-audit.json`：最终审计，状态 `passed`；
- evaluation summary SHA-256: `e9bce2242401002bb38c87aa0b8682a69a2edafd5550a4c3c9b2f67b6ca0fea8`；
- `evaluation.json` SHA-256: `84e843ba73ba3930f60c2652947c95b9aa888c27effa1ff81666a594e02df13e`；
- `final-audit.json` SHA-256: `174a3bfe28049eff235e92767e4664e419e0b731561590be798420255b7f8c1a`。

本地权威路径：`local-runs/formal-v1-main40/formal-v1-main40-run-02/`

GitHub 公开归档：`experiments/locomo-conv50-v1/results/formal-v1-main40-run-02/`
