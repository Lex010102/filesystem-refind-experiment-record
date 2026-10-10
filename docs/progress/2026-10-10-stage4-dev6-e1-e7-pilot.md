# 2026-10-10 阶段 4：完整 dev-6 × E1–E7 pilot

## 1. 目标与执行顺序

阶段 4 使用已经通过 dev-6 门槛并冻结的单源 evidence budget `B`：

1. 完成 E1–E6 共 36 个已验证 EvidenceBundle；
2. 用同一个 Shared Answerer 分别回答 E1–E6；
3. 对每题只复用本轮 E2 与 E6 的 EvidenceBundle，确定性构造 E7；
4. 用同一个 Shared Answerer 回答 E7；
5. 42/42 RunRecord 完成后才打开 dev-6 gold，执行官方 LoCoMo F1、证据、引用和成本评测；
6. 生成结构审计报告。

## 2. 新 runner

- `fs_memory_lab/pilot.py`：准备、续跑、回答、E7 融合、评测和验收；
- `fs_memory_lab/pilot_cli.py`：`prepare/run/status/finalize`；
- `tests/test_pilot.py`：预算门槛和 S1/S2 首轮底层排名一致性；
- `fs-dev-pilot`：命令行入口。

每个 E1–E6 bundle 在回答前都会重新走对应 artifact verifier，不能仅凭目录存在就复用。RunRecord 为不可覆盖、content-addressed 原子发布；已有成功记录只有在重新验证后才跳过。

## 3. E7 的严格边界

E7 只能读取本轮已完成的 E2 与 E6 record 中的 evidence bundle：

- 不调用检索模型；
- 不生成新摘要；
- 不读取 E2/E6 的最终答案作为证据；
- source bundle ID 必须与本轮 E2/E6 完全相同；
- retrieval cost 等于 E2+E6 retrieval cost 各一次；
- deployment cost 加 E7 自己的 Answerer cost，但不重复计入 E2/E6 Answerer cost。

## 4. 自动验收

pilot audit 检查：

1. 42 条结果完整；
2. retrieval 与 answer 系统失败尝试率低于 5%；
3. citations 全部属于实际输入 EvidenceBundle；
4. E1–E6 store 查询前后 hash 相同；
5. retrieval/answer served model 全程一致；
6. 对 E2、E4 各自的首轮 query，固定同一 query 后，S1/S2 的确定性 Top-5
   底层排序一致；controller 是否恰好生成逐字相同的关键词另作随机性诊断，
   不与 backend storage-layout invariant 混为一谈；
7. E7 `search_calls=0` 且标记为复用上游 retrieval；
8. E7 成本没有重复计入 E2/E6 Answerer；
9. 预算跳过 episode 比例低于 20%；
10. 无空 EvidenceBundle；
11. retrieval tokens 未触及 100 万安全熔断。

hit-cap 数量与 token 分布完整报告，但不事后发明有利阈值。E5 的高 token 成本作为 empirical finding 单列，而不是静默给予不同预算。

## 5. category 3 设计限制

dev-6 只有 category 1、2、4。category 3 的 7 道题全部保留在正式 main-40，不能为了让 pilot 覆盖 category 3 而查看正式题或据此调参。audit 会固定记录观察类别为 `[1,2,4]` 和这一限制。

## 6. 当前状态

阶段 4 runner 第一轮实现完成，相关聚焦测试 28/28 通过。正式 42 条运行等待 B=10000 的 36 条检索重跑通过预算冻结门槛后启动。

## 7. 第一轮 42/42 pilot 的结果与处置

运行 `stage4-dev6-e1-e7-b10000-20261010T064000Z` 已生成完整 42/42，API/schema
失败为 0，citations、store hash、served model、E7 无隐藏检索与成本口径均通过。
但该轮不能作为通过的 pilot：上游 B=10000 门槛存在一个实现缺陷，导致
E6/`conv-50-q129` 的唯一 15,242-character evidence item 被跳过后形成空 bundle，
却因 controller 先以 `round_limit` 停止而未触发预算重跑。

此外，原 audit 错把“E2/E4 的 controller 必须生成完全相同关键词”与
“相同 query 在 S1/S2 raw backend 上排名必须一致”合成一个条件。真实结果中
3/6 的首轮关键词有轻微随机差异，但把每个实际 query 分别送入 S1 与 S2 backend
时，12/12 排名不变量全部通过。audit 已拆分这两个概念；前者作为模型随机性
诊断，后者才是存储布局不应改变 R2-Raw 排名的工程验收。

下一步必须使用候选 B=16000 完整重跑 dev-6 的 36 条检索；只有新 summary
通过预算门槛，才能创建新的 42-record pilot。旧 run、旧 `audit.json` 和旧结果
全部保留，不覆盖、不删除。

## 8. B=16000 的正式 dev-6 pilot 已通过

新运行 `stage4-dev6-e1-e7-b16000-20261010T074000Z` 已完成 42/42 并通过 audit：

- E1–E7 各 6 条，pending 为 0；
- 系统失败率 0%，citations 全部指向真实 evidence ID；
- 所有 store hash 不变，served model 全程为 `qwen3.8:27b`；
- E2/E4 的 12/12 backend ranking invariant 全部通过；controller 首轮关键词
  逐字相同为 3/6，此项只作为模型随机性诊断；
- E7 六题均未重新检索，source bundle 与成本复用口径全部通过；
- 无空 EvidenceBundle，预算跳过 episode 比例 8.33%；
- retrieval token 最大值 527,367，低于 1,000,000 安全熔断；
- audit ID：`pilot-audit-f14d85476acb00a936cd0be311d3b691149ef9b66e7cce420f9600856e7e00a7`。

六题 pilot 的官方 LoCoMo micro-F1 仅作工程参考：E1 0.623、E2 0.535、
E3 0.592、E4 0.576、E5 0.598、E6 0.556、E7 0.408。样本只有 6 题，且
不包含 category 3，不能当作正式研究结论；它证明的是完整实验链路与审计口径
已经可执行。下一阶段才能在冻结协议下运行 main-40。
