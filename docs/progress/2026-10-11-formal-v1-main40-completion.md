# 2026-10-11 formal-v1 main-40 完成记录

## 1. 最终状态

正式运行 `formal-v1-main40-run-02` 已完成并通过 pre-gold 审计：

- 固定问题：LoCoMo `conv-50` main-40；
- 条件：E1–E7；
- 最终 RunRecords：280/280；
- 每个条件：40 条；
- 完整问题块：40/40；
- 批次：B01–B08 全部通过；
- 未完成记录：0；
- 活动失败键：0；
- requested model：`coding`；
- served model：`qwen3.8:27b`。

所有最终结果均以 `records/E1` 至 `records/E7` 内的 JSON 为准。检索目录中的
`.failed-*` 与 `failures/` 是失败尝试和恢复证据，不参与280条最终结果计数。

## 2. 运行期间的失败与恢复

状态中保留7次失败尝试。它们包括 API/超时和模型工具协议违规等运行期失败；每次均在
不改变 formal-v1 冻结协议的前提下，从准确检查点重试。恢复时复验已有 RunRecord，
跳过已经完成的记录，避免重复计数。最终没有未解决失败。

其中，E5 `conv-50-q005` 曾在 R1 provider round 6 输出不兼容的动作模式，触发
`EvidenceValidationError`；失败 artifact 显示 store 查询前后 hash 相同。随后仅重试该记录，
成功后继续 B07。长时间无进展的 API 调用也通过释放唯一 run lock 后单进程恢复，没有启动
并发重复 runner。

## 3. pre-gold 审计

`formal-pre-gold-verify.json` 的全部检查通过：

- 280条记录完整，E1–E7 各40条；
- requested/served model 一致；
- 所有 citation 指向所属 EvidenceBundle 中的真实 evidence ID；
- 所有存储查询前后 hash 不变；
- RunRecord 与已发布检索 artifact 一致；
- E7 严格复用 E2+E6 EvidenceBundle，没有隐藏检索；
- E7 检索成本只计算 E2、E6 retrieval 各一次，并排除上游 Answerer 成本；
- 整个 API 阶段没有加载 gold 语义内容。

pre-gold 运行快照如下：

| 条件 | capped episodes | empty evidence | budget-skipped | deployment tokens |
|---|---:|---:|---:|---:|
| E1 | 7 | 0 | 0 | 6,072,586 |
| E2 | 33 | 3 | 0 | 737,484 |
| E3 | 7 | 1 | 0 | 6,008,177 |
| E4 | 31 | 5 | 1 | 736,746 |
| E5 | 0 | 0 | 1 | 11,764,087 |
| E6 | 32 | 1 | 22 | 1,575,125 |
| E7 | 不适用（融合） | 不适用 | 不适用 | 2,259,475 |

七个条件的 provider-reported deployment tokens 合计为29,153,680。该数包含项目冻结
口径下的检索与 Answerer token；E7 遵守不重复计上游 Answerer 的成本规则。

## 4. GitHub 公开归档

公开归档位于：

`experiments/locomo-conv50-v1/results/formal-v1-main40-run-02/`

内容包括：

- `run/records/`：280条最终结果；
- `run/E1`–`run/E6`：成功检索 bundle、episode 与 trace，以及保留的失败尝试；
- `run/failures/`：正式 orchestrator 的失败记录；
- `control/`：B01–B08 的日志、状态、审计和 PASSED marker；
- `SHA256SUMS`：归档文件逐文件 SHA-256。

公开归档有意排除本地 `episode-secret.json`、run lock、PID 和未发布临时目录。
`episode-secret.json` 保存读取回执使用的本地 MAC secret，不是科学结果，也不应发布。
归档已扫描，未发现 `clsk_`、`FSMEM_API_KEY`、Authorization 或 Bearer 凭据。

## 5. 评分状态

280 条结果已由 `formal_batch_cli finalize` 完成纯离线评分，并生成
`evaluation.json` 和 `final-audit.json`。最终审计状态为 `passed`，已评分记录为
280/280，anonymous LLM judge 为关闭状态。

主指标 micro F1 中，E3 最高（0.4146），其次是 E2（0.3972）和 E4（0.3971）。
E5 的 Evidence Recall 最高（0.9254），但 token 成本也最高（11,764,087）。
完整的分类 F1、证据、token、calls、cap 和解读见
[`2026-10-11-formal-v1-scoring-results.md`](2026-10-11-formal-v1-scoring-results.md)。
