# 2026-10-16 至 2026-10-17：main-60、Model 2 与统一重评分完成记录

这份记录汇总 2026-10-16 至 2026-10-17 完成的主实验扩展、第二模型正式运行、
LoCoMo 官方评分和统一匿名 LLM-as-Judge 重评分。逐条答案、评分明细、审计文件和
校验和以 `experiments/locomo-conv50-v1/results/` 下的公开归档为准。

## 1. 最终完成状态

| 工作 | 完成状态 |
| --- | ---: |
| Model 1 新增 20 题 | 20 题 × E1–E7 = 140/140 |
| Model 1 main-60 答案总量 | 旧 280 + 新 140 = 420 |
| Model 2 main-60 | 60 题 × E1–E7 = 420/420 |
| Model 2 batch audit | 12/12 passed |
| Model 2 continuation pre-gold verify | passed |
| 新增 LoCoMo P/R/F1 | Model 1 新 140 条 + Model 2 全 420 条 |
| 统一匿名 LLM Judge | Model 1 420 + Model 2 420 = 840/840 |
| Judge batch audit | 两个 run 各 12/12 passed |
| Judge verification/final audit | 两个 run 均 passed |

Model 1 使用学校 API alias `coding`，served model 为 `qwen3.8:27b`；Model 2 使用
`x-test-2`，served model 为 `deepseek-v4.1-flash`。统一 Judge 使用独立 alias
`x-test-1`，preflight 验证实际 served model 为 `glm-5.3-flash`。

## 2. Model 1：append-only 新增 20 题

新增 20 题没有改写或重跑旧 main-40。运行 `formal-v2-qwen-extension20-run-01`
沿用冻结的 S1/S2/S3、E1–E7、R1/R2/R3、Answerer、B=16000、round/action caps、
timeout=300 和 concurrency=1：

- 140/140 条答案完成；
- E1–E7 各 20 条；
- 4/4 个 batch audit 通过；
- pre-gold verify 通过；
- 旧 main-40 的 280 条记录保持不变。

因此 Model 1 的 main-60 是两个兼容但独立的分区：旧 main-40 与 append-only
extension-20。任何统计都应保留 old-40、new-20 和 combined-60 的口径区别。

## 3. Model 2：第二 backbone 的 60 题正式运行

Model 2 使用冻结 candidate：`formal-v2-model2-main60-candidate-02`。计划中的科学变量
只有 backbone；问题、顺序、存储快照、检索逻辑、Answerer、预算、caps、E7 融合、
timeout 和并发均与 Model 1 保持一致。

### 3.1 安全 fuse 与混合协议披露

原始 candidate 在 88/420 时达到 1,000,000-token R1 安全 fuse。为保留已验证记录，用户
明确授权采用可审计的 mixed-protocol continuation：

1. 保留 88 条记录，把 R1 fuse 提高到 2,000,000；
2. 在 238/420 再次达到 fuse 后，保留全部 238 条，把上限提高到 4,000,000；
3. 仅绕过这两个内容寻址的 fuse failure，不改变其他科学参数；
4. 不删除、不重写、不重新绑定已完成记录。

最终结果：

- 420/420 条记录，E1–E7 各 60 条；
- 12/12 个 batch audit 通过；
- 23 个历史失败尝试均被验证并纳入审计；
- requested/served model 无漂移；
- `continuation-pre-gold-verify` 通过；
- 正式资格明确标记为 `not-eligible-mixed-protocol`。

这里的“非正式”只表示它不能冒充原始 1,000,000-token fuse 下的一次性 formal run；
它仍是完整、不可变、带失败链和授权链的补充实验结果。答案生成阶段保持 no-gold、
no-Judge，后续评分在独立流程中进行。

## 4. LoCoMo 官方 Precision、Recall、F1

评分复用 LoCoMo 官方 category-aware token/stem evaluator。Precision/Recall/F1 均为逐条
得分后求平均；F1 不是用表中的聚合 Precision 和 Recall 反算。评分是纯离线操作，API
调用数为 0。

### 4.1 Model 1 新增 20 题（140 条）

| 条件 | Precision | Recall | F1 |
| --- | ---: | ---: | ---: |
| E1 | 0.3994 | 0.6765 | 0.4554 |
| E2 | 0.3496 | 0.6549 | 0.4150 |
| E3 | **0.4311** | 0.7329 | **0.4941** |
| E4 | 0.3328 | 0.6713 | 0.3938 |
| E5 | 0.4156 | **0.7794** | 0.4867 |
| E6 | 0.3589 | 0.7024 | 0.4252 |
| E7 | 0.3647 | 0.6719 | 0.4311 |
| **总体** | **0.3789** | **0.6985** | **0.4430** |

这张表只覆盖新增 20 题，不应直接当作 Model 1 combined-60 的总体分数。

### 4.2 Model 2 全部 60 题（420 条）

| 条件 | Precision | Recall | F1 |
| --- | ---: | ---: | ---: |
| E1 | **0.2345** | 0.7003 | **0.3013** |
| E2 | 0.1720 | 0.7023 | 0.2455 |
| E3 | 0.2315 | 0.6824 | 0.2971 |
| E4 | 0.1630 | 0.6504 | 0.2314 |
| E5 | 0.1930 | **0.7389** | 0.2604 |
| E6 | 0.1630 | 0.6084 | 0.2240 |
| E7 | 0.2128 | 0.7364 | 0.2854 |
| **总体** | **0.1957** | **0.6884** | **0.2636** |

Model 2 的 token F1 低主要来自 Precision，而不是 Recall：回答更长、解释和展开更多，
导致参考答案之外的 token 增多。这个现象正是随后统一语义 Judge 的重要动机；不能只凭
token F1 断言 Model 2 的语义正确率同样很低。

## 5. 统一匿名 LLM-as-Judge 重评分

### 5.1 评分协议

统一 Judge 复用了已有 `judge-v1` 匿名 rubric 和 prompt，prompt SHA-256 为
`f5992f035a32f819858781ccd87221937124c3a924942db7449c75d75574df1a`。Judge 只看到：

1. question；
2. reference answer；
3. candidate answer。

Judge 看不到模型身份、E1–E7 条件、存储或检索方法、trace、成本和 token-F1。标签与指标为：

- `correct` / `partial` / `incorrect`；
- Strict：`correct=1`，其余为 0；
- Partial Rate：partial 占比；
- Soft：`correct=1, partial=0.5, incorrect=0`。

并发为 1、timeout 为 300 秒、最多一次仅修复格式的重试。两组各 420 条、12 个 batch；
总计 840 条全部完成，且没有 format repair。

### 5.2 Judge 模型纠正记录

最初操作口令误写成 `x-test-2`。对照 TODO 文档后发现，统一 Judge 应使用独立模型
`x-test-1`。错误的 x-test-2 目录在正式 API 调用前中止，正式题目调用数为 0，并生成
`ABORTED-BEFORE-API` 记录；其 launcher 被移除，未与任何正式结果合并。

正确 preflight 结果为：requested alias=`x-test-1`、served model=`glm-5.3-flash`、严格 JSON
schema 通过、synthetic decision 通过、prompt hash 匹配。随后才启动正式 840 条评分。

### 5.3 main-60 Judge 结果

| 系统 | correct | partial | incorrect | Strict | Partial Rate | Soft |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Model 1 / Qwen | 305 | 30 | 85 | **0.7262** | 0.0714 | **0.7619** |
| Model 2 / DeepSeek | 299 | 37 | 84 | 0.7119 | 0.0881 | 0.7560 |

两模型在统一独立 Judge 下非常接近：Strict 相差约 1.43 个百分点，Soft 相差约 0.60 个
百分点。这与 token F1 的大差距形成明显对照，支持“Model 2 的低 token F1 很大程度上受
冗长回答和低词面 Precision 影响”的解释，但仍需逐题配对检验后才能做统计结论。

### 5.4 条件级 Judge 结果

| 条件 | Model 1 Strict | Model 1 Soft | Model 2 Strict | Model 2 Soft |
| --- | ---: | ---: | ---: | ---: |
| E1 | 0.7167 | 0.7667 | 0.7500 | 0.8083 |
| E2 | 0.6667 | 0.7167 | 0.7000 | 0.7083 |
| E3 | 0.7500 | 0.7917 | 0.7000 | 0.7583 |
| E4 | 0.7000 | 0.7250 | 0.6667 | 0.7083 |
| E5 | **0.7833** | **0.8167** | **0.7500** | 0.8000 |
| E6 | 0.7333 | 0.7583 | 0.6667 | 0.7083 |
| E7 | 0.7333 | 0.7583 | **0.7500** | **0.8000** |

这些是描述性结果。下一阶段应以 question × condition 为配对单位，报告 bootstrap CI、
差值分布和类别分层，避免只比较总体均值。

## 6. 新增实现

- `fs_memory_lab/locomo_prf_cli.py`：对已冻结 RunRecord 运行官方 LoCoMo P/R/F1，输出逐条
  明细和条件/类别汇总，不调用 API。
- `fs_memory_lab/judge_main60.py`：支持两个分区组成的 main-60、匿名 3 档 Judge、35 条
  batch、断点续跑、身份 fail-closed、verification 和 final audit。

`judge_main60.py` 复用 `judge_v1` 的原始 prompt 和解析器，没有另起一套语义标准。

## 7. 公开归档与安全边界

新增或更新的归档：

- Model 1 extension-20 新评分：
  `experiments/locomo-conv50-v1/results/formal-v2-qwen-extension20-run-01/`
- Model 2 main-60 完整 mixed-protocol 运行：
  `experiments/locomo-conv50-v1/results/formal-v2-model2-main60-candidate-02/`
- x-test-1 统一 Judge：
  `experiments/locomo-conv50-v1/results/llm-judge-x-test1-main120/`
- 误写 x-test-2、正式调用前中止的审计记录：
  `experiments/locomo-conv50-v1/results/llm-judge-x-test2-main120-aborted-before-api/`

公开归档排除运行锁、PID、Python cache、本机 shell history 和凭据。API key 只从 macOS
Keychain 注入进程；扫描未发现 key、Authorization header 或 Bearer token。每个结果归档
均提供 `SHA256SUMS`，用于逐文件复核。

## 8. 后续分析 TODO

- [ ] 合并 Model 1 old-40 与 new-20 的逐条 LoCoMo 结果，生成显式 combined-60 汇总；
- [ ] 对两模型按 question × condition 做配对差值、bootstrap CI 和类别分层；
- [ ] 分析 Model 2 的回答长度、词面 Precision 与 Judge 标签之间的关系；
- [ ] 分离成功路径 token 成本与 fuse/重试带来的恢复成本；
- [ ] 在报告中明确 Model 2 的 mixed-protocol/non-formal 边界；
- [ ] 再决定是否运行 B3 Full Context 或增加其他 baseline。
