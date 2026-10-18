# B3 Full Context DeepSeek main-60 v2 操作与跑批指南

制定日期：2026-10-17  
协议范围：`B3-FullContext`，`main-60-v2`，DeepSeek 单模型版本  
当前状态：**只做实现、冻结准备和离线验证；尚未启动正式 API 答题**

## 1. 目标与边界

本版本只运行一个 Full Context baseline：

| 项目 | 固定值 |
| --- | --- |
| 条件 | `B3-FullContext` |
| 正式题集 | `main-60-v2`，共 60 题 |
| requested alias | `x-test-2` |
| required served model | `deepseek-v4.1-flash` |
| Answerer | 项目已有 `SharedAnswerer` |
| 正式答案数 | 60 |
| 批次 | 12 批，每批 5 题 |

本实验不运行 Qwen Full Context，也不覆盖旧的 Qwen/main-40 准备物。它使用新的 manifest、
run ID、checkpoint、audit 和输出目录；旧 Full Context v1 文档与本地目录只保留为历史材料。

这个 baseline 回答的问题是：**如果模型不做任何检索，而是每道题直接看到全部原始记忆，
DeepSeek 的答案质量和成本怎样？** 它可与 E1–E7 比较，但不是 E1–E7 中的第八种检索器，
也不是一种新的存储结构。

## 2. 一道题实际怎样运行

每题的固定流程如下：

```text
当前问题
  + S1 中全部 30 个原始 sessions（固定时间顺序）
  + 与主实验相同的 SharedAnswerer system prompt
  ↓
x-test-2（API 返回必须是 deepseek-v4.1-flash）
  ↓
答案 JSON + ev-* citations
```

关键点：

- 不运行 Retrieval Agent；
- 不运行 R1、R2 或 R3；
- 不使用 grep、BM25、目录导航、Top-K、重排或查询扩展；
- tools 始终为空；
- 正常情况每题一次 Answerer 调用；若输出 JSON 不合法，只允许沿用现有 Answerer 的一次格式修复；
- 初答和格式修复的每个响应都必须报告 `served_model=deepseek-v4.1-flash`，否则 fail closed；
- 不向模型提供 condition 名、gold answer、gold evidence 或其他题的答案。

因此，Full Context 的自变量不是“搜索策略”，而是“取消搜索，把全部 S1 直接作为回答上下文”。

## 3. 固定输入与公平性不变量

### 3.1 全量 S1 上下文

每题都使用相同的既有 S1 全量上下文包：

| 项目 | 固定值 |
| --- | ---: |
| sessions | 30 |
| source turns | 568 |
| 带 BLIP caption 的 turns | 125 |
| evidence text characters | 108,960 |
| evidence text bytes | 108,982 |

源文件仍是：

```text
experiments/locomo-conv50-v1/stores/s1-flat/session-01.md
...
experiments/locomo-conv50-v1/stores/s1-flat/session-30.md
```

发布的只读上下文包仍是：

```text
experiments/locomo-conv50-v1/baselines/b3-full-context-v1/
├── context-package.json
├── transcript.txt
├── manifest.json
└── verification.json
```

所有原始 turn 与已有 caption 都保留；不总结、不改写、不按当前问题重排，也不截断。

### 3.2 为什么没有 16,000-character evidence cap

E1–E7 的检索条件先选择证据，因此使用 `B=16,000 characters` 约束交给 Answerer 的检索证据。
Full Context 的定义恰好是“把全部上下文直接送给 Answerer”，所以这里的 evidence budget 为
`N/A`，不是 16,000 characters。若把 Full Context 截到 16,000 characters，它就不再是 Full
Context，而会变成另一种检索/截断 baseline。

### 3.3 与主实验保持相同的项目

- 同一 60 题及固定全局顺序；
- 同一 S1 snapshot 和同一个确定性 Full Context package；
- 同一 `SharedAnswerer` prompt、JSON schema、citation 校验和 temperature `0`；
- 同一 Answerer 最大完成 token 规划值 `2,048`；
- 同一 timeout `300 seconds`、最大响应 `20,000,000 bytes` 和串行并发 `1`；
- 同一 API adapter 的 `portable` wire profile；
- 同一重试、一次格式修复与成本记录口径；
- 答题阶段 no-gold、no-Judge。

与主实验不同的只有：本条件没有 Retrieval Agent，且每题直接使用全部 S1。

## 4. 60 题组成与 12 个批次

`main-60-v2` 由冻结的 core-40 加 extension-20 组成。runner 必须保留每道题原来的
`question_set_id` 和局部 `run_position`，另外使用 composition 文件校验全局 1–60 顺序；
不能伪造一个新的统一 `QuestionInput` 身份。

权威 composition：

```text
experiments/locomo-conv50-v1/question-sets-main60-v2/main-60-composition.json
```

固定批次如下：

| Batch | 全局位置 | 题目 | 累计 |
| --- | ---: | --- | ---: |
| B01 | 1–5 | q023, q081, q051, q027, q022 | 5/60 |
| B02 | 6–10 | q151, q152, q016, q024, q043 | 10/60 |
| B03 | 11–15 | q052, q008, q002, q054, q090 | 15/60 |
| B04 | 16–20 | q037, q069, q145, q038, q013 | 20/60 |
| B05 | 21–25 | q010, q014, q154, q103, q128 | 25/60 |
| B06 | 26–30 | q068, q046, q040, q033, q087 | 30/60 |
| B07 | 31–35 | q070, q088, q125, q032, q005 | 35/60 |
| B08 | 36–40 | q117, q143, q042, q021, q047 | 40/60 |
| B09 | 41–45 | q147, q126, q075, q144, q019 | 45/60 |
| B10 | 46–50 | q114, q121, q044, q057, q058 | 50/60 |
| B11 | 51–55 | q111, q078, q074, q082, q104 | 55/60 |
| B12 | 56–60 | q089, q012, q132, q028, q118 | 60/60 |

## 5. DeepSeek 部署身份

Full Context v2 复用已经通过并冻结的 Model 2 部署身份：

| 项目 | 固定值 |
| --- | --- |
| API base URL | `https://soclaas-api.comp.nus.edu.sg/v1` |
| chat endpoint | `/chat/completions` |
| API style | `portable` |
| requested alias | `x-test-2` |
| required served model | `deepseek-v4.1-flash` |
| advertised context limit | 1,048,576 tokens |

依赖的 sanitized `/v1/models` 和角色 smoke 证据位于：

```text
experiments/locomo-conv50-v1/results/
  formal-v2-model2-main60-candidate-02/run/preflight/models-check.json
experiments/locomo-conv50-v1/results/
  formal-v2-model2-main60-candidate-02/run/preflight/role-smoke.json
```

这些证据说明 alias、served model 和基本 Answerer 兼容性已经成立，但不能替代 Full Context
自己的长上下文容量测试。每一次正式响应仍必须单独核验模型身份，不能只在 run 结束时抽查。

## 6. 上下文容量门与 dev-6 pilot

正式 main-60 前必须依次通过两个独立门槛。

### 6.1 最长上下文 preflight

固定使用 dev-6 的 `conv-50-q079` 做真实请求。其完整消息正文为 118,939 characters；
main-60 的最长题 `conv-50-q043` 为 119,004 characters，只多 65 characters。q079 因而是
接近正式最坏情况的安全预检，但不是正式 60 题的组成部分。

preflight 必须确认：

- 网关接受全量 30-session 上下文；
- 输出满足 Answerer JSON/citation 协议，或在唯一一次格式修复后满足；
- 所有响应均为 `deepseek-v4.1-flash`；
- usage、延迟和 provider attempts 被完整记录；
- 不发生自动截断、摘要、换模型或降级为检索。

如果出现 context-length、request-size 或模型身份错误，应停止并报告，不能改变 baseline 定义来
“让它跑通”。

### 6.2 dev-6 pilot

preflight 通过后，补齐固定 dev-6 的 6/6。preflight 已完成的 q079 必须从 checkpoint 验证并
跳过，不能重复计入。只有 pilot 完整、模型身份一致、active failures 为 0 且最终审计通过，
才能执行任何 main-60 正式在线请求；main-60 的 manifest 与离线 dry-run 可以提前生成和核验。

旧 Qwen pilot 或 Model 2 的 E1–E7 pilot 均不能代替这个 Full Context DeepSeek 长上下文 pilot。

## 7. 独立运行目录与恢复规则

固定建议目录和 run ID：

```text
output root: local-runs/b3-full-context-v2-model2/

dev run:     b3-full-context-v2-model2-dev6-run-01
formal run:  b3-full-context-v2-model2-main60-run-01
```

每个 run 必须具有独立 manifest、records、failures、events、status、lock 和 audit。恢复时：

1. 先确认没有另一个进程持有同一 run lock；
2. 校验 manifest、模型身份、题目顺序、S1/package hashes 和实现 commit；
3. 校验并跳过已完成记录；
4. 只从 next key 恢复，不能覆盖或重复计入已完成记录；
5. 网络瞬时错误按冻结重试规则处理；hash、顺序、模型漂移或数据完整性错误立即停止；
6. 每 5 题边界生成 batch audit 和 PASSED marker；B12 后再做整体 pre-gold audit。

成本统计必须保留两层：成功记录内的全部 Answerer 调用；以及恢复前失败 episode 的额外
model calls、provider failure 和可获得的 usage。API 没有返回 usage 的失败调用必须显示为
`usage_unavailable_calls`，不能按零 token 混入总成本；因此汇总中的 `total_tokens_known` 只是
可观测下界。

旧 `local-runs/b3-full-context-v1/` 不能复制、续跑或计入新 DeepSeek run。

## 8. 命令与执行顺序

以下命令均从仓库根目录执行：

```bash
cd '/Users/wangwenqi/Desktop/memory bench'
```

### 8.1 只读构造与 prompt 检查（无 API）

```bash
python3 -m fs_memory_lab.full_context_cli build-source

python3 -m fs_memory_lab.full_context_cli \
  inspect --question-set dev-6

python3 -m fs_memory_lab.full_context_cli \
  inspect --question-set main-60-v2
```

必须确认 source 为 30 sessions / 568 turns / 108,960 characters，main-60 题数为 60、顺序
与 composition 完全一致，并识别出 main-60 最大 prompt 为 q043。

### 8.2 准备 dev run 并离线 dry-run（无 API）

```bash
python3 -m fs_memory_lab.full_context_cli \
  --output-root 'local-runs/b3-full-context-v2-model2' \
  --run-id 'b3-full-context-v2-model2-dev6-run-01' \
  prepare --question-set dev-6

python3 -m fs_memory_lab.full_context_cli \
  --output-root 'local-runs/b3-full-context-v2-model2' \
  --run-id 'b3-full-context-v2-model2-dev6-run-01' \
  dry-run
```

dry-run 至少验证：题目与顺序、模型 deployment、S1/package、Answerer prompt、provider 约束、
计划记录数、checkpoint 恢复规则以及 preflight/pilot gate。它不得创建正式答案、读取 semantic
gold 或调用 API。

### 8.3 在线 preflight 与 pilot（当前不要执行）

下面两条命令会把问题、完整 S1 上下文和 Answerer 请求发送至 NUS SoCLaaS API。**当前只记录
命令，不执行。开始前必须取得用户针对本次 Full Context DeepSeek 请求的明确数据发送授权，
并确认 VPN 与进程环境中的凭据配置可用。** API key 只能注入进程环境，不能写入项目文件、
命令参数、日志或报告。

```bash
python3 -m fs_memory_lab.full_context_cli \
  --output-root 'local-runs/b3-full-context-v2-model2' \
  --run-id 'b3-full-context-v2-model2-dev6-run-01' \
  preflight

python3 -m fs_memory_lab.full_context_cli \
  --output-root 'local-runs/b3-full-context-v2-model2' \
  --run-id 'b3-full-context-v2-model2-dev6-run-01' \
  pilot
```

pilot 结束后的离线核验：

```bash
python3 -m fs_memory_lab.full_context_cli \
  --output-root 'local-runs/b3-full-context-v2-model2' \
  --run-id 'b3-full-context-v2-model2-dev6-run-01' \
  verify
```

### 8.4 准备 main-60 run 并离线 dry-run（无 API）

main-60 manifest 与离线 dry-run 可以提前准备，以便核对 60 题、12 批及所有冻结哈希；这两步
不会调用 API。真正执行任何 main-60 在线请求时，runner 仍会强制要求同版本 dev
preflight/pilot 审计已经通过：

```bash
python3 -m fs_memory_lab.full_context_cli \
  --output-root 'local-runs/b3-full-context-v2-model2' \
  --run-id 'b3-full-context-v2-model2-main60-run-01' \
  prepare --question-set main-60-v2

python3 -m fs_memory_lab.full_context_cli \
  --output-root 'local-runs/b3-full-context-v2-model2' \
  --run-id 'b3-full-context-v2-model2-main60-run-01' \
  dry-run
```

### 8.5 正式跑批（当前不要执行）

正式 60 题发送同样需要前述明确授权。可按 batch 逐步运行；命令天然支持 checkpoint 续跑：

```bash
python3 -m fs_memory_lab.full_context_cli \
  --output-root 'local-runs/b3-full-context-v2-model2' \
  --run-id 'b3-full-context-v2-model2-main60-run-01' \
  run --through-block 1

# 依次将 1 改为 2 ... 12；或在受控后台单实例中一次跑完：
python3 -m fs_memory_lab.full_context_cli \
  --output-root 'local-runs/b3-full-context-v2-model2' \
  --run-id 'b3-full-context-v2-model2-main60-run-01' \
  run --all
```

只读查看状态：

```bash
python3 -m fs_memory_lab.full_context_cli \
  --output-root 'local-runs/b3-full-context-v2-model2' \
  --run-id 'b3-full-context-v2-model2-main60-run-01' \
  status
```

## 9. main-60 完成与 pre-gold 验收

60/60 后先运行只读核验，而不是立即评分：

```bash
python3 -m fs_memory_lab.full_context_cli \
  --output-root 'local-runs/b3-full-context-v2-model2' \
  --run-id 'b3-full-context-v2-model2-main60-run-01' \
  verify
```

验收必须同时确认：

- completed records = 60，pending = 0，next key = null；
- B01–B12 均为 5 条且 audit/marker 通过；
- active failed keys = 0；
- 所有请求 alias 为 `x-test-2`，所有响应 served model 为 `deepseek-v4.1-flash`；
- 每条记录都使用完整的同一 S1 package，search calls = 0；
- 所有 citations 均指向本题 Full Context bundle 中真实的 `ev-*`；
- S1 和 source package hashes 未变化；
- semantic gold 未加载，Judge calls = 0；
- API attempts、format repairs、prompt/completion/total tokens 与延迟均完整记录。

全部检查通过后，除 `pre-gold-audit.json` 外还应生成最终只读标记
`FULL-CONTEXT-MODEL2-MAIN60-60.PASSED`。

只有这个 pre-gold audit 通过后，才允许进入评分阶段。

## 10. 评分边界

离线评分命令为：

```bash
python3 -m fs_memory_lab.full_context_cli \
  --output-root 'local-runs/b3-full-context-v2-model2' \
  --run-id 'b3-full-context-v2-model2-main60-run-01' \
  evaluate
```

`evaluate` 必须在 `verify` 已通过后才可读取两层冻结 gold：core-40 gold 与 extension-20 gold。
评分器须先验证两层合计恰好覆盖正式 60 个 question IDs，不能混入 dev-6、旧 main-40 run、
Qwen 答案或其他题目。

该命令只代表离线确定性评分。LLM-as-Judge 是另一阶段、另一模型、另一授权和另一份审计，
不得在本次答案生成或 pre-gold verify 中自动启动。

## 11. Go / No-Go 清单

正式在线运行前必须全部满足：

- [ ] 新 runner/CLI/test 已提交，结果影响文件没有未提交改动；
- [ ] `main-60-v2` 为 60 个唯一 question IDs，顺序与 composition 一致；
- [ ] S1 与 Full Context package hashes 通过；
- [ ] DeepSeek deployment 与 sanitized preflight hashes 通过；
- [ ] 离线单元测试及 dev/main dry-run 通过；
- [ ] q079 长上下文 preflight 通过；
- [ ] dev-6 pilot 6/6 且最终审计通过；
- [ ] 独立输出目录为空或为同一 manifest 的可恢复 checkpoint；
- [ ] 没有其他进程持有 run lock；
- [ ] 用户已明确授权把本次 Full Context 输入发送至 NUS SoCLaaS API；
- [ ] 正式过程不加载 gold、不运行 Judge、不启动 Qwen Full Context。

任一项未满足均为 No-Go；不得通过缩短上下文、换模型、改题、放宽 schema 或混用旧产物绕过。
