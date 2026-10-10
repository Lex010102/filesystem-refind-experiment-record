# 2026-10-10：阶段 2——E1 真实单题端到端测试

状态：**通过**。本阶段只运行一题工程 smoke，没有启动完整 dev-6 或 main-40，也没有据此冻结正式 evidence budget。

## 1. 冻结输入

| 项目 | 本次值 |
| --- | --- |
| Condition | E1 = S1 flat raw sessions + R1 filesystem search |
| Question set | `locomo-conv50-dev6-v1` |
| Question ID | `conv-50-q129` |
| Question | What dish does Dave recommend Calvin to try in Tokyo? |
| Evidence budget | 6,000 characters，仅作工程 smoke |
| R1 prompt | Filesystem 论文 Prompt 7 的 evidence-only 派生版本 |
| R1 round cap | 20 |
| Shared Answerer | `shared-evidence-answerer-v1` |
| Requested model | NUS SoCLaas alias `coding` |
| Served model | `qwen3.8:27b` |
| Run ID | `stage2-e1-smoke-20261010T045911Z` |

运行前离线 preflight 再次验证 S1 为 30 个文件、114,456 bytes，tree SHA-256 为 `ca39361e8e23f204a9fda55fc83e3ce7f411c7c8d582939aa63688c1923c7679`，没有 store 漂移。

## 2. 执行链路

本次不是只检查检索连通性，而是第一次把 E1 真实请求接入阶段 1 的共同基础设施：

1. R1 Research Agent 在 S1 中执行论文式文件检索；
2. host 将检索结果发布成 content-addressed EvidenceBundle；
3. 共同 Answerer 只接收 question + EvidenceBundle，不能看到 condition 或 gold；
4. AnswerResult 与 EvidenceBundle 组合为不可覆盖的 RunRecord；
5. RunRecord 离线复验成功后才打开 dev-6 gold；
6. 自动计算 LoCoMo F1、evidence、citation 与 cost 指标。

## 3. 结果

Answerer 输出为 `Ramen`，`insufficient_evidence=false`，没有触发格式修复。检索取回 `D24:20` 与 `D24:21`，其中官方 gold evidence 为 `D24:20`。

| 指标 | 结果 |
| --- | ---: |
| LoCoMo F1 | 1.0 |
| Evidence Recall | 1.0 |
| Any-hit | true |
| All-hit | true |
| Citation validity | 1.0 |
| RunRecord completed / pending / failed attempts | 1 / 0 / 0 |

成本如下：

| 阶段 | Model calls | Prompt tokens | Completion tokens | Total tokens |
| --- | ---: | ---: | ---: | ---: |
| E1 retrieval | 12 | 81,409 | 3,708 | 85,117 |
| Shared Answerer | 1 | 592 | 231 | 823 |
| 合计 | 13 | — | — | 85,940 |

本题只说明链路正确，不能说明 E1 优于或劣于其他条件。相较 2026-10-08 的旧 E1 retry，本次新增验证了共享 Answerer、RunRecord、成本合并和自动评测，而不是复用旧结果冒充新流程。

## 4. 本地产物与隐私边界

本地产物位于：

- retrieval：`local-runs/stage2-e1-smoke/results/stage2-e1-smoke-20261010T045911Z/E1/conv-50-q129/`；
- RunRecord：`local-runs/stage2-e1-smoke/results/run-records/stage2-e1-smoke-20261010T045911Z/`；
- evaluation：`local-runs/stage2-e1-smoke/results/stage2-e1-smoke-20261010T045911Z/evaluation.json`。

`local-runs/` 被 Git 忽略，因为 R1 工作目录含权限为 0600 的 private episode secret。GitHub 只保存本记录中的非敏感摘要，不上传 key、private checkpoint 或真实 API trace。

## 5. 结论与下一步

E1 的真实端到端链路已经补齐，阶段 2 完成。6,000 characters 仍只是 smoke 参数，不能直接称为正式预算。下一步应先设计并运行完整 dev-6 的 E1–E6 工程检查，比较 evidence completeness、capped/failure rate 和成本分布，再在查看 main-40 结果前冻结所有单源条件共用的正式 evidence budget。
