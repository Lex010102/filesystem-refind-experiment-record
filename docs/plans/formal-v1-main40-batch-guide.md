# `formal-v1` main-40 正式跑批指南

状态：**运行协议已经冻结；Stage 5A 调度层已实现。必须先通过 Stage 5B dry-run，才允许启动真实 API 跑批。**

本文是后续正式跑批的操作地图。它说明要跑什么、按什么顺序跑、如何看进度、失败后
如何恢复、何时才能评分，以及最后应如何分析。本文不保存 API key，也不允许通过命令行
临时修改 prompt、预算、cap、模型或评分规则。

机器权威配置仍是：

- `experiments/locomo-conv50-v1/formal-v1/manifest.json`
- manifest ID：`formal-337ebb2061b34493a2e81cad19453eb85481d82a646ce4c40a750e2222d08925`
- 实现快照：`e2633826614fad8fdece74bc66150127f3a33082`
- 冻结声明：`a4094a73e2ac7341910e474bb1df009e434f43d7`
- Git tag：`formal-v1`

本文是操作说明，不替代上述机器 manifest。

## 1. 正式实验到底跑什么

正式题集为固定的 40 道 LoCoMo 问题。每道题在 E1–E7 七个条件下各产生一条
`RunRecord`：

| 条件 | 存储 | 检索 | 含义 |
| --- | --- | --- | --- |
| E1 | S1 平铺原始 session | R1 文件系统 Agent | 原始文件基线 |
| E2 | S1 平铺原始 session | R2-Raw | 原始聊天的增强检索 |
| E3 | S2 文件夹化原始 session | R1 文件系统 Agent | 测目录组织的作用 |
| E4 | S2 文件夹化原始 session | R2-Raw | 文件夹存储上的增强检索 |
| E5 | S3 LLM 整理文件系统 | R1 文件系统 Agent | Filesystem 主基线 |
| E6 | S3 LLM 整理文件系统 | R3 / R2-Curated | 整理记忆上的增强检索 |
| E7 | 复用 E2 原始证据 + E6 整理证据 | 确定性双源融合，不重新检索 | 双源证据条件 |

总规模是：

- 40 道题；
- 7 个条件；
- 280 条最终 `RunRecord`；
- E1–E6 各自调用检索和统一 Answerer；
- E7 不重新检索，只复用同一道题已经完成的 E2、E6 `EvidenceBundle`，再调用一次统一 Answerer。

## 2. 不能再改变的正式参数

| 项目 | `formal-v1` 固定值 |
| --- | --- |
| Evidence budget | E1–E6 每路 16,000 characters |
| E7 budget | 每个来源最多 16,000，总计最多 32,000 characters |
| R1 round cap | E1/E3 为 20；E5 为 40 |
| R2/R3 action cap | 4 |
| requested model | `coding` |
| required served model | `qwen3.8:27b`，每次响应都必须一致 |
| API style | `portable` |
| 单请求 timeout | 300 秒 |
| 最大响应 | 20,000,000 bytes |
| 并发 | 1，严格串行 |
| 主评分 | 官方 LoCoMo category-aware token F1 |
| LLM judge | 关闭 |

如果 main-40 分数不好，也不能调整这些值。如果发现会改变结果含义的程序错误，应建立
新的 formal 版本并重跑受影响条件，不能把两个版本的记录混在一起。

## 3. 固定路径和运行身份

推荐只使用下面这一个正式身份：

```text
repository  /Users/wangwenqi/Desktop/memory bench
output root /Users/wangwenqi/Desktop/memory bench/local-runs/formal-v1-main40
run id      formal-v1-main40-run-01
run root    /Users/wangwenqi/Desktop/memory bench/local-runs/formal-v1-main40/formal-v1-main40-run-01
```

不要用同一个 `run id` 做 smoke test，也不要同时启动两个正式进程。`run id` 一旦 prepare，
其计划和 manifest 就不可替换。

## 4. Stage 5A：先生成不可变运行计划

在 repository 根目录运行：

```bash
cd '/Users/wangwenqi/Desktop/memory bench'

python3 -m fs_memory_lab.formal_batch_cli \
  --repo-root '/Users/wangwenqi/Desktop/memory bench' \
  --output-root '/Users/wangwenqi/Desktop/memory bench/local-runs/formal-v1-main40' \
  --run-id 'formal-v1-main40-run-01' \
  prepare
```

`prepare` 不调用 API。它会：

1. 重新验证 `formal-v1`；
2. 固定 40 题顺序和 280 个 `(condition_id, question_id)`；
3. 绑定 S1/S2/S3、prompt、协议和 formal manifest hashes；
4. 绑定正式调度器的 Git commit 和文件 hash；
5. 写入 append-only 运行目录。

关键产物：

```text
formal-v1-main40-run-01/
├── plan.json                 # 280 项固定顺序
├── formal-run-manifest.json  # formal-v1 与本调度器的绑定
├── status.json               # 当前进度
├── events.jsonl              # 运行事件日志
├── records/E1...E7/          # 最终 RunRecord
└── failures/E1...E7/         # 失败尝试历史，不覆盖
```

调度器没有提供 `--budget`、`--model`、`--cap` 或 prompt override。这是有意设计：正式运行
不能被一条临时命令悄悄改参数。

## 5. Stage 5B：无 API dry-run

紧接着运行：

```bash
python3 -m fs_memory_lab.formal_batch_cli \
  --repo-root '/Users/wangwenqi/Desktop/memory bench' \
  --output-root '/Users/wangwenqi/Desktop/memory bench/local-runs/formal-v1-main40' \
  --run-id 'formal-v1-main40-run-01' \
  dry-run
```

这一阶段不读取 API key、不构造 provider、不发网络请求，也不读取 gold 的语义内容。
它必须同时验证：

- `formal-v1` manifest 仍然有效；
- 40 题顺序完全一致；
- 280 个 key 唯一且每个条件恰好 40 个；
- 每道题的 E7 都排在它自己的 E2、E6 后面；
- S1/S2/S3 tree hash 与冻结值一致；
- S1/S2 都能确定性生成 292 个 exchange、30 个 session；
- S1/S2 原始内容一致，路径组织不同；
- S1/S2 的确定性 R2 排名探针一致；
- S3 能生成固定的 390 个 fact units 和 35 个 groups；
- 运行目录仍为空，没有旧结果或失败尝试混入；
- 并发仍为 1，运行时方法参数不可覆盖。

通过后会生成 `dry-run.json`。真实 `run` 命令会再次验证该报告；缺失、被修改或失败的
dry-run 都会阻止 API 跑批。

## 6. 正式开跑前的一次人工检查

只有 Stage 5B 通过后再做以下检查：

1. 学校 VPN 已连接；
2. 当前终端已经有 `FSMEM_API_KEY`，但不要打印 key；
3. `FSMEM_API_BASE_URL` 指向学校网关；
4. `FSMEM_MODEL=coding`；
5. `FSMEM_API_STYLE=portable`；
6. 确认没有另一个相同 `run id` 的进程；
7. 再运行一次 `status`，应显示 `completed_records=0`、`pending_records=280`。

安全查看环境是否存在，只打印布尔值：

```bash
python3 -c 'import os; print({k: bool(os.getenv(k)) for k in ("FSMEM_API_KEY", "FSMEM_API_BASE_URL", "FSMEM_MODEL", "FSMEM_API_STYLE")})'
```

不要在聊天、截图、日志或 Git 中粘贴完整 key。runner 不会主动清除、轮换或展示 key。

## 7. 正式 API 跑批方式

真实运行命令是：

```bash
python3 -m fs_memory_lab.formal_batch_cli \
  --repo-root '/Users/wangwenqi/Desktop/memory bench' \
  --output-root '/Users/wangwenqi/Desktop/memory bench/local-runs/formal-v1-main40' \
  --run-id 'formal-v1-main40-run-01' \
  run
```

### 7.1 顺序

程序按 question-major 顺序运行：同一道题先完成旋转后的 E1–E6，再生成 E7；下一道题
会把 E1–E6 的起点向后轮换，以减轻固定条件总是在最前或最后的顺序偏差。E7 永远在
本题 E2、E6 之后。

40 题被标记成 8 个逻辑块，每块 5 题、35 条记录。逻辑块只用于检查点和进度报告，
不是重新切题，也不会改变题目顺序。程序仍是串行的一条正式运行。

### 7.2 每条记录的流程

对于 E1–E6：

```text
加载并验证 store
  → 执行冻结的检索方法
  → 发布并重新读取 EvidenceBundle
  → 检查 B、store hash、requested/served model
  → 统一 Answerer 作答
  → 检查 citation
  → 原子发布 RunRecord
  → 更新 status 与 events
```

对于 E7：

```text
读取本题已完成的 E2 + E6 RunRecord
  → 确定性融合两份 EvidenceBundle
  → 不进行新检索
  → 统一 Answerer 作答
  → 原子发布 E7 RunRecord
```

### 7.3 进度查看

随时可在另一个终端运行：

```bash
python3 -m fs_memory_lab.formal_batch_cli \
  --repo-root '/Users/wangwenqi/Desktop/memory bench' \
  --output-root '/Users/wangwenqi/Desktop/memory bench/local-runs/formal-v1-main40' \
  --run-id 'formal-v1-main40-run-01' \
  status
```

重点看：

- `completed_records / 280`；
- `completed_by_condition`；
- `finished_questions` 与 `completed_blocks`；
- `next_key`；
- `failure_attempts` 与 `active_failed_keys`。

## 8. 失败与恢复规则

runner 在第一条明确失败时停止，不会跳过后继续，也不会自动启动另一个并发进程。

处理顺序：

1. 查看终端错误、`status.json`、`events.jsonl` 和对应 `failures/` 记录；
2. 判断是 VPN/API 临时错误、served model 漂移，还是实质性程序错误；
3. 临时外部错误解决后，重新执行完全相同的 `run` 命令；
4. runner 会重新验证全部冻结输入，只跳过已经通过内容校验的 `RunRecord`；
5. 若检索已经成功但 Answerer 失败，会复用已验证的检索 artifact，不重复检索；
6. 不删除历史 failure，不手工伪造 completed marker，不复制别的 run 的结果。

如果是会改变结果含义的实质性 bug，应停止 `formal-v1`，建立新版本并按影响范围完整
重跑；不能在原 run 内偷偷修代码继续混跑。

## 9. 280/280 后的 pre-gold 核验

API 阶段完成后先运行：

```bash
python3 -m fs_memory_lab.formal_batch_cli \
  --repo-root '/Users/wangwenqi/Desktop/memory bench' \
  --output-root '/Users/wangwenqi/Desktop/memory bench/local-runs/formal-v1-main40' \
  --run-id 'formal-v1-main40-run-01' \
  verify
```

`verify` 要求 280/280 才能运行，并在不读取 gold 语义的情况下检查：

- 每个条件 40 条；
- 每条 citation 都属于该 EvidenceBundle；
- store 查询前后未改变；
- RunRecord 与原检索 artifact 完全一致；
- requested/served model 没有漂移；
- 记录 capped、空 evidence、预算跳过和 token 成本；
- E7 source bundle ID 正确；
- E7 没有隐藏检索；
- E7 只计 E2+E6 retrieval 各一次及自己的 Answerer，不重复计上游 Answerer。

通过后生成 `pre-gold-audit.json`。

## 10. 最后评分

只有 pre-gold audit 通过后才能运行：

```bash
python3 -m fs_memory_lab.formal_batch_cli \
  --repo-root '/Users/wangwenqi/Desktop/memory bench' \
  --output-root '/Users/wangwenqi/Desktop/memory bench/local-runs/formal-v1-main40' \
  --run-id 'formal-v1-main40-run-01' \
  finalize
```

这时才打开固定 hash 的 `main-40-gold.jsonl`，使用官方 LoCoMo category-aware token
F1 评分。结果写入：

- `evaluation.json`：280 条评分结果和各条件汇总；
- `final-audit.json`：最终身份、记录数、evaluation summary hash；
- `events.jsonl`：追加 finalized 事件。

主结果至少报告：

- 每个条件的 `micro_f1`；
- category 1–4 F1；
- category macro F1；
- post-stratified F1；
- evidence recall、any-hit、all-hit；
- citation validity；
- retrieval、Answerer 和总 token 成本；
- round/action cap rate、预算跳过率和空证据率。

## 11. 预先固定的主要比较

避免看到结果后才挑比较，主分析按以下配对问题解释：

| 比较 | 回答的问题 |
| --- | --- |
| E1 vs E3 | 仅把同一原始聊天放入主题父文件夹，是否帮助 R1？ |
| E3 vs E5 | 从“只改位置”到“LLM 整理内容”，效果与成本如何变化？ |
| E1 vs E2 | 原始平铺聊天上，R2 是否优于文件系统 Agent 搜索？ |
| E3 vs E4 | 文件夹化原始聊天上，R2 是否优于 R1？ |
| E5 vs E6 | ReFind-inspired 检索能否修复 S3 的检索失败？ |
| E2 vs E6 vs E7 | 原始证据、整理证据及双源融合的效果/成本权衡是什么？ |

每道题是配对单位。后续统计分析应至少保存逐题差值，并使用固定 `seed=42` 的 10,000
次 paired bootstrap 给出均值差和 95% 区间；样本只有 40 题，区间和逐题案例应与点估计
一起报告，不能只报告“谁最高”。这一步属于结果分析，不改变已冻结的检索或评分结果。

## 12. 错误归因框架

对答错题按可观察证据分层归因：

1. **写入/存储损失**：正确原文存在，但 S3 中缺失、错误或被旧信息污染；
2. **检索失败**：目标来源存在于该存储，但 EvidenceBundle 没取到；
3. **预算/上限失败**：候选出现，但因 B、round/action cap 没进入最终证据；
4. **回答推理失败**：正确证据已经进入 bundle，Answerer 仍答错；
5. **证据冲突/融合失败**：E2 与 E6 提供矛盾或重复证据，E7 没有正确化解；
6. **题目或指标边界**：参考答案、时间推理或 token-F1 口径造成的特殊案例。

结构化归因优先使用 trace、bundle、citation 和 gold locator 的确定性规则；只有确实无法
自动判断的剩余案例再做盲法人工复核。`formal-v1` 不临时加入 LLM-as-judge。

## 13. 最终完成标准

正式跑批只有同时满足以下条件才算完成：

- 280/280 `RunRecord` 可重新加载并通过 hash 校验；
- E1–E7 各 40 条；
- `formal-v1`、正式运行 manifest、计划和调度器身份一致；
- pre-gold audit 通过；
- `evaluation.json` 和 `final-audit.json` 已生成；
- 所有失败尝试、恢复过程和成本仍可追溯；
- 没有依据 main-40 结果改变正式参数；
- 研究报告清楚区分论文原方法、本项目适配和新增的 E7 双源条件。

