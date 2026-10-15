# Model 2 x-test-2 准备与正式运行指南

更新日期：2026-10-15

本文规定第二个查询阶段 backbone（以下简称 Model 2）的准备、验证、冻结和正式运行流程。Model 2 使用学校 SoCLaaS API 的 `x-test-2` 别名，同时承担 Retrieval Agent 与 Answerer。师兄提供的映射是 DeepSeek V4.1 Flash；在 API 返回并冻结真实 `served_model` 之前，报告中只能把这一名称写成待验证的部署映射。

核心结论：**不能把现有 Qwen runner 的模型变量直接改成 `x-test-2` 后正式跑批。** 必须依次完成模型 preflight、独立运行基础设施、离线验证、dev-6 pilot 和 formal-v2 冻结，之后才能运行 60 题 × E1–E7 = 420 条正式记录。

## 1. 实验目标与范围

Model 2 用于检验：在完全相同的题目、固定记忆、检索方法和实验参数下，更换查询阶段 backbone 后，E1–E7 的效果、排序、错误模式和成本结论是否稳定。

正式矩阵如下：

| 查询阶段 backbone | Retrieval Agent | Answerer | 题目 | 条件 | 答案数 |
| --- | --- | --- | ---: | ---: | ---: |
| Model 1 | Qwen `qwen3.8:27b` | 同一 Qwen | 60 | 7 | 420（已完成） |
| Model 2 | `x-test-2` | 同一 `x-test-2` | 60 | 7 | 420（待运行） |

当前主实验只比较两条“同模型检索 + 同模型回答”的对角线，不增加 Qwen 检索/Model 2 回答或 Model 2 检索/Qwen 回答的角色交叉实验。因此，主实验回答的是整套查询阶段 backbone 的稳健性，不能单独识别 Retrieval Agent 与 Answerer 的因果贡献。

## 2. 固定边界

Model 2 与 Qwen 必须共享下列条件，唯一主要自变量是查询阶段 backbone：

- 同一 `main-60-v2` 题目、题目顺序与 category 分配；
- 同一 S1、S2、S3 store 内容和 snapshot hashes；
- 同一 E1–E7 条件定义；
- 同一 R1、R2、R3 与 Answerer prompts 和方法参数；
- 同一工具 schema、BM25/RRF 参数和停止条件；
- evidence budget `B = 16,000 characters`；
- R1 round cap：E1/E3 为 20，E5 为 40；
- R2/R3 action cap：4；
- E7 只融合同一 backbone 的 E2 与 E6 EvidenceBundle，每路最多 B、总计最多 2B，且不得重新检索；
- 同一 timeout、retry、串行并发 `1`、引用验证、store 不变性和成本统计口径；
- 正式答题阶段不得加载 semantic gold，也不得调用 Judge。

S2/S3 是此前由 Qwen 参与构建的固定记忆快照。Model 2 只替换查询阶段的 Retrieval Agent 和 Answerer，不重新构建记忆。因此论文应将该实验表述为“固定记忆上的下游 backbone 稳健性比较”，而不是两个模型的端到端记忆构建比较。

现有 R2/R3 冻结协议体包含 `formal_requested_model_alias="coding"`。因此 Model 2 不能把旧 R2/R3 protocol hash 直接描述为自己的完整 deployment contract。新 manifest 必须把两层身份分开：旧 prompt、工具和方法参数 hashes 作为算法来源；`x-test-2` alias、实际 served model 与 wire profile 形成新的 deployment contract hash。旧 Qwen protocol hash 只保留为 parent provenance，不得掩盖 alias 差异。

## 3. 为什么不能直接复用 Qwen runner

现有正式代码和启动器是 Qwen 专用版本：

- `formal_v1.py` 冻结 requested alias `coding` 和 served model `qwen3.8:27b`；
- `formal_v2_extension.py` 直接继承这些 Qwen 常量，并在 retrieval、Answerer 和最终审计中强制校验；
- `formal_batch.py` 的 provider 与 bundle 门禁会拒绝另一模型；
- `formal-v2-qwen-extension20/run-all.zsh` 固定 Qwen 的模型、run ID 和输出目录；
- 当前 formal-v2 extension runner 只处理新增 20 题和 140 条记录，不代表完整的 Model 2 main-60 运行结构。

直接修改这些文件会破坏已完成 Qwen 实验的冻结身份和可追溯性。Model 2 必须使用新增的独立 orchestration、manifest、run IDs 和 output root，底层 R1/R2/R3/Answerer 实现则继续复用。

## 4. 总体阶段与 Go/No-Go 门槛

| 阶段 | 内容 | 通过后才能进入 |
| --- | --- | --- |
| A | Model 2 身份与能力 preflight | B |
| B | 独立 runner、manifest 与运行控制 | C |
| C | 单元测试、dry-run 与故障测试 | D |
| D | dev-6 × E1–E7 pilot，42/42 | E |
| E | formal-v2-model2 冻结 | F |
| F | main-40 280 条 + extension-20 140 条 | 最终 pre-gold 审计 |

任何阶段未通过都不得跳过门槛直接运行正式 420 条。

## 5. 阶段 A：模型身份与能力 preflight

### 5.1 API 身份确认

- [ ] 只读确认 `/v1/models` 暴露 `x-test-2`；
- [ ] 用最小请求记录 requested alias `x-test-2`；
- [ ] 记录 API 响应的真实 `served_model`；
- [ ] 记录 system fingerprint（若提供）、API style、可接受参数和 context limit；
- [ ] 确认 usage 至少包含 prompt、completion 和 total tokens；
- [ ] 确认所有正式响应都能返回模型身份；缺失或漂移时必须 fail closed。

如果 API 只返回 `x-test-2` 而不公开底层模型名，正式报告应写“学校 API 的 `x-test-2` deployment”，并把 DeepSeek V4.1 Flash 标注为师兄提供的映射，而不是 API 独立验证结论。

### 5.2 分角色协议 smoke

必须用冻结 prompt 和工具协议分别验证：

| 组件 | 必须验证的行为 |
| --- | --- |
| R1 | 原生 `tool_calls`、`tool_choice=auto`、同轮单一工具模式、take_note、finish_search、自由文本纠正 |
| R1 compaction | 无工具摘要请求、纯文本 summary、`finish_reason=stop`、usage 和 served model |
| R2/R3 | 不使用原生工具调用；输出严格的 Thought / Action / Action Input 文本，Action Input 为 JSON |
| R2/R3 stop | `finish_search` 可被解析并在四动作上限内正确停止 |
| Answerer | 只返回规定 JSON；citation 只能引用允许的 evidence IDs；格式修复至多沿用现有一次机会 |

### 5.3 参数公平性

优先沿用 Qwen 的 portable wire profile：temperature 规则保持一致，且不发送学校网关不接受的 `reasoning_effort` 和 `max_completion_tokens`。如果 `x-test-2` 因 API 接口要求必须采用不同 payload，必须在 pilot 前版本化、记录并冻结；不得在看过正式分数后修改。

### 5.4 阶段 A 通过标准

- `x-test-2` 的 alias 和实际 served model 已记录；
- R1、R2、R3、Answerer 和 compaction 均至少成功一次；
- 无无法解释的 schema、usage、context 或工具兼容问题；
- 未修改题目、store、prompt、预算或 cap。

## 6. 阶段 B：独立 Model 2 运行基础设施

### 6.1 两层物理运行

`main-60-v2` 是两个真实 question set 的组合，不能伪造为单一新 question-set ID：

| Child run | 题目 | 记录 | 批次 |
| --- | ---: | ---: | ---: |
| `model2-main40` | 原 main-40 | 280 | 8 × 35 |
| `model2-extension20` | 新 extension-20 | 140 | 4 × 35 |
| suite 合计 | 60 | 420 | 12 批 |

suite manifest 负责冻结两层的组合关系和全局 1–60 顺序；最终只读 combined audit 按 question ID 合并为 420/420。extension 的条件轮换继续使用全局位置 41–60 的 offset，不从 E1 重新起算。

### 6.2 新增而不修改旧冻结文件

建议新增：

- `fs_memory_lab/formal_v2_x_test2.py`；
- `fs_memory_lab/formal_v2_x_test2_cli.py`；
- `tests/test_formal_v2_x_test2.py`；
- Model 2 suite manifest 与 sanitized preflight report；
- 独立的 `local-runs/formal-v2-x-test2/` 启动与控制目录。

不得覆盖或复用 Qwen 的 run root、RunRecord、retrieval artifact、checkpoint、PID、日志或 PASSED marker。

### 6.3 模型字段与身份门禁

现有 RunRecord schema 保持不变，不能为了 Model 2 增加 Judge 字段。retrieval/answer 的 requested 与 served model 继续写入现有 retrieval artifacts 和 AnswerResult；run/suite manifest 另外冻结：

- retrieval requested model；
- retrieval served models；
- answer requested model；
- answer served models；
- model identity policy 和 expected served model。

Judge 未运行这一边界只写入 run/suite manifest 和 pre-gold audit，不修改 RunRecord 字段集合。

Retrieval Agent 与 Answerer 必须同时是冻结后的同一 Model 2 deployment。任何 Qwen artifact 或错误模型 artifact 都不得被复用。

为实现逐响应门禁，应在底层 provider 外增加 Model 2 identity-checking decorator：每次 `complete()` 返回后、R1/R2/R3/Answerer 接收结果前检查 `served_model`。缺失或与 expected served model 不同即 fail closed，不能等到 episode 发布后才发现。该门禁也覆盖 R1 compaction、R1 协议纠正和 Answerer repair。

### 6.4 运行控制

- 每个 child run 有独立 `run.lock`；
- suite launcher 再增加一个总锁，保证两个 child run 不并发；
- 已验证记录按内容和 plan identity 跳过，失败记录只从当前 key 恢复；
- 每批结束生成 status、audit 与 PASSED marker；
- API key 只从 macOS Keychain 注入进程环境，不写入命令参数、项目文件或日志；
- 后台串行运行，每 10 分钟只报告安全的计数和失败位置。

## 7. 阶段 C：离线测试与 dry-run

在任何正式答案 API 调用前，至少验证：

- [ ] main-40 为 280 keys，extension-20 为 140 keys，合计 420；
- [ ] E1–E7 最终各 60 条；
- [ ] 60 题顺序、两层 question-set identity 和全局 rotation 正确；
- [ ] core/extension/composition hashes 正确；
- [ ] S1/S2/S3、方法层 prompt/tool hashes、Model 2 deployment contract、Answerer、E7 与预算 hashes 正确；
- [ ] 新 deployment contract 不把含 `coding` 的旧 R2/R3 protocol body 误称为 Model 2 身份；
- [ ] Model 2 alias 或 served model 缺失/漂移会被逐响应 provider decorator 立即拒绝；
- [ ] R1 compaction、纠错调用和 Answerer repair 也受 served-model 门禁约束；
- [ ] E7 必须在同题 E2/E6 完成后生成，且不产生 retrieval 调用；
- [ ] E7 成本不重复计入 E2/E6 的 Answerer；
- [ ] checkpoint 重启不会重复计数或覆盖已完成结果；
- [ ] main-40 与 extension-20 的目录、锁和 marker 相互隔离；
- [ ] dry-run 不加载 semantic gold、不调用 API、不运行 Judge。

## 8. 阶段 D：dev-6 pilot

正式跑批前，Model 2 必须独立完成：

```text
6 道开发题 × E1–E7 = 42 条最终结果
```

旧 dev runner 不能原样充当 Model 2 验收门：它只检查 served model 是否唯一，未锁定 preflight 得到的 expected model，也未完全强制 Retrieval Agent 与 Answerer 的 requested model 相同。必须新增 Model 2 pilot wrapper 或补齐等价外层门禁。

pilot 采用与 formal-v1 相同的预注册判据：

- 42/42 记录完整，E1–E7 各 6 条；
- requested 与 served model 全程一致，无漂移；
- retrieval 与 answer 的系统失败尝试率低于 5%；
- 所有 citation 指向真实 evidence IDs；
- 所有 store 查询前后 hash 不变；
- 对 E2/E4 各自固定同一首轮 query 后，S1/S2 的确定性 Top-5 底层排序一致；
- 预算候选跳过 episode 比例低于 20%；
- 空 EvidenceBundle 数量为 0；
- retrieval token 未触及 100 万安全熔断；
- R1 round cap、R2/R3 action cap、hit-cap、token、compaction 和 Answerer repair 完整报告，但不事后新增有利阈值；
- evidence item 不做字符级截断；超出 B 的候选整条跳过，并记录 `budget_skipped_items`；
- E7 只复用同一 Model 2 的 E2/E6 bundle，不暗中重新检索；
- E7 的 2B 与成本口径正确；
- pilot 不用于修改题目，也不因分数高低调整 prompt、预算或检索参数。

pilot 的作用是发现接口、schema、运行控制和成本异常，不是选择对 Model 2 更有利的配置。

## 9. 阶段 E：formal-v2-model2 冻结

pilot 通过后冻结：

- [ ] Git commit；
- [ ] runner、CLI、测试和 suite manifest hashes；
- [ ] main-40、extension-20、composition 和 60 题顺序；
- [ ] S1/S2/S3 snapshot hashes；
- [ ] R1/R2/R3 方法层 prompt/tool hashes、Model 2 deployment contract、Answerer 与 E7 hashes；
- [ ] requested alias `x-test-2` 与真实 served model；
- [ ] portable wire profile 与 endpoint 标识；
- [ ] B=16,000、round/action caps、E7 规则；
- [ ] timeout、retry、并发、失败恢复和成本口径；
- [ ] 正式答题阶段 no-gold、no-Judge 规则。

从冻结开始，不得因 main-60 分数不好而修改参数。如果发现实质性程序错误，应建立新版本并重跑所有受影响记录，不能混用两个版本。

## 10. 阶段 F：正式 420 条跑批

### 10.1 顺序

1. `model2-main40`：B01–B08，共 280 条；
2. main-40 pre-gold verify；
3. `model2-extension20`：suite 全局记为 B09–B12，共 140 条；extension child CLI 内部仍使用 local B01–B04 / `through-block=1..4`，不得把 9–12 传给 child runner；
4. extension pre-gold verify；
5. suite combined audit：420/420；
6. 生成 `ANSWER-RUN-COMPLETED-NO-JUDGE` 类完成标记；
7. 停止，不启动任何评分。

每批包含 5 道题 × 7 个条件 = 35 条。每批通过后必须确认累计记录数、各条件计数、finished questions、active failures、next key、batch audit 和 PASSED marker。

### 10.2 自动恢复边界

冻结的自动恢复规则必须精确区分请求内重试、协议内纠正和整个 episode 续跑：

- timeout 按各组件现有最大次数和 backoff 做请求内重试；
- 只有 HTTP `408, 429, 500, 502, 503, 504` 属请求内可重试状态；
- R1 自由文本纠正最多每轮 1 次、每 episode 3 次；
- Answerer 格式修复最多 1 次；
- R2/R3 invalid action 消耗四动作额度，不额外增加 action；
- 外层 launcher 最多 8 次同配置恢复；只跳过已验证记录，当前失败 key 重新执行；
- DNS/VPN 连接错误当前不属于 `TransientProviderError`：应停止 launcher，连通恢复后从原 checkpoint 新开单实例，而不是在断网状态下循环消耗恢复次数。

整个 episode 是否重跑、最大次数以及允许重跑的错误类型必须在 freeze 中列成白名单。模型身份漂移、hash/plan 变化和数据完整性错误永远不进入自动重试。

必须停止并报告：

- requested/served model 漂移；
- store、题集、prompt、runner 或 manifest hash 变化；
- plan/order/question-set identity 不一致；
- citation、E7 provenance 或成本口径无法验证；
- 需要改变冻结参数才能继续的错误。

每次失败尝试应保存 sanitized failure artifact。若 provider 已返回模型元数据，失败 artifact 也必须记录并审计 served model；若尚未收到响应，则明确记录 `served_model=null` 和安全错误类型。任何失败响应中的模型漂移同样立即停止正式运行。

## 11. 最终 pre-gold 验收

正式答案阶段完成必须同时满足：

- main-40：280/280；
- extension-20：140/140；
- suite：420/420；
- E1–E7 各 60 条；
- active failed keys = 0，next key = null；
- 全部 12 个 batch audit 和 PASSED marker 存在；
- 所有成功模型响应，以及所有已返回模型元数据的失败响应，均为冻结的真实 served model；
- citations 全部有效；
- stores 全程不变；
- retrieval artifacts 与 RunRecords 对应；
- E7 无隐藏检索且成本规则正确；
- semantic gold 未加载；
- Judge calls = 0。

## 12. 后续评分不属于本指南的答题阶段

Model 2 的 420 条通过 pre-gold 验收后，再进入统一评分：

- 对 Qwen 420 条与 Model 2 420 条计算 LoCoMo Precision、Recall、F1；
- 使用独立 `x-test-1` 对全部 840 条做匿名三分类 Judge；
- 计算 Strict Accuracy、Partial Rate 和 Soft Semantic Score；
- 旧 Qwen Judge 结果只用于 Judge 敏感性分析，不能与新 `x-test-1` 标签混合。

`x-test-1` 的身份、JSON 能力、pilot 和冻结应另立 Judge 指南，不与 Model 2 答题 runner 混在一起。

## 13. 启动前需要的用户授权与环境

正式开始 Model 2 准备时，需要一次明确授权：允许将 dev/formal 问题文本、检索证据与回答请求发送至学校 SoCLaaS `x-test-2`，并允许仅为该实验使用 Keychain 中已保存的 API key。

不需要重新输入 API key。运行期间需要学校 VPN 可用；启动器应在正式调用前做无密钥连通性检查，并在 VPN 不可用时保留断点而不是反复消耗恢复次数。

## 14. 当前状态与下一步

截至 2026-10-15：

- [x] main-60-v2 题集和 composition 已生成；
- [x] Qwen 原 main-40 280 条已完成；
- [x] Qwen extension-20 140 条已完成并通过 pre-gold verify；
- [x] Qwen 逻辑 combined-60 已有 420 条答案；
- [ ] Model 2 API identity/capability preflight；
- [ ] Model 2 独立 runner 与离线测试；
- [ ] Model 2 dev-6 pilot 42/42；
- [ ] Model 2 formal freeze；
- [ ] Model 2 main-60 正式 420/420；
- [ ] 独立 `x-test-1` Judge 准备与统一 840 条评分。

因此，下一次执行顺序固定为：

```text
x-test-2 preflight
→ Model 2 独立 runner 与 dry-run
→ dev-6 × E1–E7 pilot 42/42
→ formal-v2-model2 freeze
→ main-40 280 + extension-20 140
→ combined pre-gold audit 420/420
→ 停止，等待统一评分
```
