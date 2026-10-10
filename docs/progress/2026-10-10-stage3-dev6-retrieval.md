# 2026-10-10 阶段 3：dev-6 × E1–E6 检索预算校准

## 1. 第一轮 6000-character 结果

运行 ID：`stage3-dev6-20261010T051101Z`。

- 36/36 retrieval episodes 已完成并通过离线 hash 验证；
- 当前失败为 0；E2/q007 曾出现两次学校网关空正文响应，两个失败 artifact 与 16,739 failed-attempt tokens 均保留；
- 兼容修复把 `null/empty content` 记为一次 `invalid_action`，占用原有四动作上限，不增加动作、不伪造证据；
- 11/36 命中方法上限，0/36 空证据；
- requested model 始终为 `coding`，served model 始终为 `qwen3.8:27b`；
- 所有 store 查询前后 hash 相同；
- Evidence Any-hit 为 35/36，All-hit 为 30/36；
- E5 平均 retrieval tokens 相对其他条件均值中位数的比率为 5.94，必须在报告中单独披露。

离线 verifier 最终返回 36/36 completed，summary ID 为
`summary-c4c5d0b3b9ece5fbb7096573be0bc0a4daf896f3685d4a9cbd01bf7682aac072`。

## 2. 为什么 6000 不能直接冻结

预注册工程规则是：若至少 20% 的 episode 因 evidence budget 跳过候选，则只在 dev 阶段调整一次并完整重跑。6000 characters 下有 8/36，即 22.2%，超过门槛，因此结论是 `adjust-and-rerun-all-dev6`。

这不是答案分数调参，也没有查看 main-40；判断只使用 dev-6 的检索审计信息。

## 3. 新预算为什么选择 10000

对第一轮已冻结 action trace 做确定性回放，重建 R2/R3 已选择 note 的真实字符长度：

| 候选预算 | 仍发生候选跳过的 episode | 占 36 条比例 |
| --- | ---: | ---: |
| 6000 | 8 | 22.2% |
| 8000 | 7 | 19.4% |
| 10000 | 6 | 16.7% |
| 12000 | 3 | 8.3% |

8000 只是勉强越过门槛，缺乏随机服务波动余量；12000 会明显扩大 Answerer 上下文。正式校准候选因此选择 **B=10000 characters**，在检索完整性与回答成本之间留出适度余量。该结论仍需新一轮 36 条真实检索验证；若新一轮未通过冻结门槛，阶段 4 必须停止并报告，不能继续追着 dev 结果调参。

## 4. 修复与可追溯性

新增内容包括：

- R2/R3 空正文兼容处理和单元测试；
- 两级恢复策略，严格绑定具体失败 ID；
- 所有历史失败和成本进入 summary；
- summary 只阻止 active failure，不再把已经成功恢复的历史 failure 当作未完成；
- API key 通过 macOS Keychain 使用，不写入仓库、日志或实验 artifact。

## 5. 下一步

运行 `stage3-dev6-b10000-20261010T064000Z` 的 36 条检索。只有当其预算决策为 `freeze-candidate-10000` 后，阶段 4 才能创建 42-record pilot plan。

## 6. B=10000 真实运行后的更正

该轮后来完成了 36/36，但 E6 的 `conv-50-q129` 选择到一个长度为
15,242 characters 的 S3 evidence item。它超过 B=10000，被预算打包器
跳过，最终 EvidenceBundle 为空。

原门槛实现只在 `stop_reason == evidence_budget_reached` 时把空 bundle 判为
预算失败；本题先到达 R3 四 action 上限，因此保留 `round_limit`，错误得到
`freeze-candidate-10000`。现已修正为依据最终预算结果判断：只要
`empty_evidence == true` 且 `budget_skipped_items > 0`，无论 controller
为何停止，都必须 `adjust-and-rerun-all-dev6`。

离线重放显示 B=12000 仍装不下该 item；B=16000 可以装下，并消除当前
六道 E6 trace 中的空 bundle。因此 **16000 只是下一轮候选值，不是已冻结值**；
必须重新运行完整 36 条 dev-6 才能决定是否冻结。旧 summary 与旧 Stage 4
结果保留为审计证据，不覆盖，也不能视为正式通过结果。

## 7. B=16000 最终冻结结果

修正后的运行 `stage3-dev6-b16000-20261010T074000Z` 已完成并通过离线验证：

- 36/36 EvidenceBundle 完整，0 个系统失败，0 个空证据；
- 3/36 episode 发生预算候选跳过，占 8.33%，低于 20% 门槛；
- 10/36 命中各方法预先冻结的 action/round cap；
- Evidence Any-hit 为 36/36，All-hit 为 27/36；
- requested model 始终为 `coding`，served model 始终为 `qwen3.8:27b`；
- 所有 store 查询前后 hash 不变；
- 预算决策为 `freeze-candidate-16000`；
- summary ID：`summary-50f06ee8226af615bd595c007cc7a0156d7d52e674de418efd9e152c631451c7`。

E5 平均 retrieval token 仍为其他条件均值中位数的 7.18 倍，是必须在报告中
披露的效率 finding，而不是系统失败。运行期间曾有一次学校网关在 HTTPS 响应
读取阶段长期悬挂；已增加 300 秒整次请求 wall-clock deadline，并从 26/36
检查点恢复，没有重跑或覆盖已验证 episode。
