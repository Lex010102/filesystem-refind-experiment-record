# 2026-10-09：阶段 1 共同基础设施

本次按既定顺序完成了四项离线基础设施，未调用学校 API、未开始 main-40 正式运行。

1. 新建共享 evidence-only Answerer：E1–E7 使用同一 prompt、同一严格 JSON 输出、同一重试与格式修复规则；Answerer 不接收 condition、gold 或检索 trace。
2. 新建 E7 确定性融合：只组合 E2 raw 与 E6 curated 的既有证据，以精确键去重并交替排列，不搜索、不摘要、不再次调用 retrieval model。
3. 新建统一 RunPlan、RunRecord、失败记录和续跑存储：成功记录不可覆盖并进行 hash 复验；失败 attempt 保留且仍待运行；E7 必须引用本轮已经完成的 E2/E6 source bundle。
4. 新建自动评测器：按固定 commit 的官方 LoCoMo 规则计算 category 1–4 F1，并统计 evidence、citation、cost；提供可选匿名 LLM judge 和整批离线 CLI。

实现说明与正式使用命令见 `docs/reproduction/common-experiment-infrastructure.md`。

本阶段新增聚焦测试共 20 项，全部通过。最终全仓标准库 discovery 共报告 300 项，其中实际功能测试 299 项通过；唯一 error 是既有 `tests/test_r1_prompts.py` 因当前系统 Python 未安装 pytest 而无法由 unittest loader 导入。随后用不修改仓库的 environment-neutral runner 执行该模块当前 8 个参数化/普通 cases，全部通过。改动后的四个新模块又执行聚焦回归并全部通过。
