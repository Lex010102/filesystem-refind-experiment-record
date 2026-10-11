# B3 Full Context 独立实验操作与跑批指南

制定日期：2026-10-11
协议名称：`b3-full-context-v1`
实验条件：`B3-FullContext`
当前状态：**离线实现、源包、runner、批次审计与自动测试已完成；真实 API 容量预检尚未执行**

## 1. 名称与研究位置

本项目目前只增加一个外部 baseline：`B3-FullContext`。这里的 `B3` 是师兄建议的第三个
baseline，不是跑批编号。正式运行仍按 5 题一批划分，因此：

- `Full Context Batch 1`：main-40 的前 5 道题；
- `Full Context Batch 2`：第 6–10 道题；
- 依此类推，共 8 个 batch、40 道题。

A-MEM 和 Mem0 暂不实施。现有 E1–E7 的 280 条 formal-v1 结果保持不变，Full Context 使用
独立 manifest、run id 和结果目录，不能追加进原 E1–E7 run。

## 2. Full Context 到底怎么回答

每道题的流程是：

```text
当前问题
  + 全部 30 个 S1 原始 session 正文（固定时间顺序）
  + 原 formal-v1 的共享 Answerer prompt
  ↓
一次 Answerer episode
  ↓
答案 + ev-* citations
```

它**不先 search**，没有 R1/R2/R3、BM25、Top-K、文件导航、重排、上下文扩展或检索
Agent。每道题都重新发送同一份完整对话，只替换当前问题；工具列表始终为空。正常时一个
episode 只有一次模型调用，但网络重试或一次 JSON schema repair 可能产生多个 provider
attempts/model calls，这些都会单独计数。

该条件用于观察：当全部信息都可见时，效果和成本如何。它不是必然的准确率上界，因为
长上下文噪声和注意力分散仍可能导致错误。

## 3. 固定输入与上下文构造

### 3.1 权威数据

源数据是已冻结的 S1：

```text
experiments/locomo-conv50-v1/stores/s1-flat/session-01.md
...
experiments/locomo-conv50-v1/stores/s1-flat/session-30.md
```

固定不变量：

| 项目 | 值 |
| --- | ---: |
| conversation | `conv-50` |
| sessions | 30 |
| source turns | 568 |
| 带 BLIP caption 的 turns | 125 |
| S1 tree SHA-256 | `ca39361e8e23f204a9fda55fc83e3ce7f411c7c8d582939aa63688c1923c7679` |
| canonical records SHA-256 | `130a5a1e1b75083358ef27a98dd215a4e75c819ace6f2ee9b560ba394e0f0394` |
| source map SHA-256 | `6e99115961bae06a48bfb7e82dbdcc18dc32ccf6c5ce57e3c266dfc7a5d4d574` |

### 3.2 模型实际看到什么

每个 session 形成一个普通 `EvidenceItem`。item 文本从该文件第一个经过出处校验的 source
turn 开始，到最后一个 source turn 结束。因此：

- 全部 568 个原始 turn 都保留；
- 全部 125 个已有 BLIP caption 都保留；
- speaker、日期、`[SxTy]`、`dia_id` 等 source 内容保留；
- S1 的 YAML frontmatter、session Date 标题和纯文件系统路由标题不发送给模型；
- Answerer 会为每个 session 加上 `ev-*`、`Source`、标准化 `Timestamp` 和完整
  `Locators` 包装；
- 不总结、不改写、不去重、不按问题排序、不截断。

这样避免把只属于文件系统实现的 metadata 变成 Full Context 的额外优势，同时仍完整保留
真实聊天证据。

### 3.3 ID 与引用

- 正式 citation 使用现有 Answerer 要求的内容寻址 `ev-<64位SHA>`；
- `FC-S01` 至 `FC-S30` 存在于源包、manifest、transcript 及运行时 bundle/record 的映射
  metadata 中，但不出现在 Answerer prompt 中；
- citation 粒度是 **session-level**：一个 `ev-*` 指向包含该 session 全部 `[SxTy]` 和
  `dia_id` 的 EvidenceItem，可回溯到原文，但本身不精确标记其中某一个 supporting turn。

固定源包位于：

```text
experiments/locomo-conv50-v1/baselines/b3-full-context-v1/
├── context-package.json   # 机器可读的 30 个 EvidenceItem
├── transcript.txt        # 人工查看版
├── manifest.json         # 源包、S1 和文件 hashes
└── verification.json     # 30/568/125 等完整性检查
```

当前确定性结果：

| 项目 | 值 |
| --- | ---: |
| evidence text characters | 108,960 |
| evidence text bytes | 108,982 |
| evidence text SHA-256 | `12c3041b32cd7ff32bf6c913b95992cebf48ed3bd1d28ff9f1cdd29c8e927738` |
| source package ID | `full-context-source-4add27428aae2daed6df17e171379c7ea1a16a9f68690fbb2149403cd4062b55` |

## 4. 上下文长度与容量风险

“上下文长度”要区分三件事：

1. 原始证据正文：108,960 characters；
2. 加入 evidence ID、出处、问题和共享 prompt 后，最长 dev 请求 q079 为 118,939
   characters；
3. 同一 served model 历史调用校准后的估计为 33,983–41,013 input tokens。

项目为回答规划预留 2,048 output tokens，所以建议部署至少能容纳约 36,031–43,061 total
tokens；64k context 较稳妥，32k 很可能不够。

这里的 characters/bytes 是 system 与 user 两段消息正文之和，不含 HTTP、JSON 和 provider
chat framing；token 区间同样是正文估计。学校网关没有提供可信的部署 context-window
metadata，也没有本地完全一致的 tokenizer。真正权威的数值是成功请求返回的 provider
`prompt_tokens`。

q079 是 dev-6 中最长的非正式题请求。它比 Batch 1 中最长的 q081（118,928 characters）
略长，因此能覆盖 Batch 1 的本地正文长度；main-40 全局最长是 q043（119,004
characters），所以 q079 是近最坏情况预检，并非全部正式题的严格最大值。

学校 API 使用 `portable` 模式：本地 Answerer 的 2,048 只是规划预留，adapter 不会把
`max_completion_tokens` 或 `reasoning_effort` 发到 wire，不能写成服务端强制上限。

## 5. 为什么不能直接开始 main Batch 1

离线程序已经准备好，但正式 main-40 前必须依次过两个门槛：

1. **单题容量 preflight**：固定使用 dev-6 中本地 payload 最长的 `conv-50-q079`；
2. **dev-6 pilot**：完成固定 6 道开发题并通过审计。

只有二者通过，才能证明学校部署接受完整请求、返回正确 schema、served model 未漂移，且
实际 token/延迟可接受。不能跳过这一步直接消耗 40 道正式题。

若 q079 返回 context-length 或 request-size 错误：立即停止；不得自动截断、摘要、检索、
换题或改模型。若决定换长上下文模型，必须建立新版本，不能与同模型 E1–E7 无说明混比。

## 6. 代码结构

```text
fs_memory_lab/full_context.py         # 30-session 源包与 EvidenceBundle
fs_memory_lab/full_context_runner.py  # manifest、record、断点、审计、评分
fs_memory_lab/full_context_cli.py     # 独立 CLI，不改原 E1–E7 CLI
tests/test_full_context.py            # 构造、故障、恢复、评分测试
```

旧 `formal-v1` core 文件没有被修改。Full Context manifest 额外绑定所有直接依赖文件、
父 formal-v1 manifest、S1 snapshot、源包文件、问题顺序、Answerer、模型和评分器 hashes。

## 7. 冻结运行配置

| 项目 | 固定值 |
| --- | --- |
| requested model | `coding` |
| required served model | `qwen3.8:27b` |
| API style | `portable` |
| temperature | 0 |
| concurrency | 1 |
| timeout | 300 seconds |
| retryable HTTP | 408, 429, 500, 502, 503, 504 |
| HTTP attempts | 5；backoff 5/15/30/60 s |
| timeout attempts | 3；backoff 2/4 s |
| JSON repair | 最多 1 次 |
| search calls | 0 |
| evidence budget | N/A；完整 30 sessions，不截断 |
| main batch size | 5 questions |

API key 只从当前进程环境的 `FSMEM_API_KEY` 读取；base URL 来自
`FSMEM_API_BASE_URL`。CLI 若读不到配置会直接失败，不会弹出输入提示，也不显示、不清除、
不轮换或保存 key。

## 8. 命令与运行顺序

以下命令都在仓库根目录执行：

```bash
cd '/Users/wangwenqi/Desktop/memory bench'
```

### 8.1 无 API 的离线检查

```bash
python3 -m fs_memory_lab.full_context_cli build-source
python3 -m fs_memory_lab.full_context_cli inspect --question-set dev-6
python3 -m fs_memory_lab.full_context_cli inspect --question-set main-40
```

### 8.2 准备 dev-6 run

准备前，所有结果相关代码与源包必须已经提交到 Git；CLI 会拒绝未跟踪或未提交的实现。

```bash
python3 -m fs_memory_lab.full_context_cli \
  --output-root 'local-runs/b3-full-context-v1' \
  --run-id 'b3-full-context-v1-dev6-run-01' \
  prepare --question-set dev-6

python3 -m fs_memory_lab.full_context_cli \
  --output-root 'local-runs/b3-full-context-v1' \
  --run-id 'b3-full-context-v1-dev6-run-01' \
  dry-run
```

### 8.3 真实容量 preflight 与 pilot

连接学校 VPN，并保证当前运行环境已有 `FSMEM_API_KEY`、
`FSMEM_API_BASE_URL=https://soclaas-api.comp.nus.edu.sg/v1`、`FSMEM_MODEL=coding`、
`FSMEM_API_STYLE=portable`。CLI 只读取这些环境变量；缺失时直接失败，不会主动提示输入。

```bash
python3 -m fs_memory_lab.full_context_cli \
  --output-root 'local-runs/b3-full-context-v1' \
  --run-id 'b3-full-context-v1-dev6-run-01' \
  preflight

python3 -m fs_memory_lab.full_context_cli \
  --output-root 'local-runs/b3-full-context-v1' \
  --run-id 'b3-full-context-v1-dev6-run-01' \
  pilot

python3 -m fs_memory_lab.full_context_cli \
  --output-root 'local-runs/b3-full-context-v1' \
  --run-id 'b3-full-context-v1-dev6-run-01' \
  verify
```

`preflight` 只运行 q079。若它已经形成有效 completed record，`pilot` 会校验并跳过 q079，
只补齐其余 5 题；若 preflight 失败，`pilot` 会重新尝试 q079。

### 8.4 准备并运行 main-40

```bash
python3 -m fs_memory_lab.full_context_cli \
  --output-root 'local-runs/b3-full-context-v1' \
  --run-id 'b3-full-context-v1-main40-run-01' \
  prepare --question-set main-40

python3 -m fs_memory_lab.full_context_cli \
  --output-root 'local-runs/b3-full-context-v1' \
  --run-id 'b3-full-context-v1-main40-run-01' \
  dry-run
```

固定批次与题目顺序：

| Batch | 题目（固定顺序） | 累计完成 |
| --- | --- | ---: |
| 1 | q023, q081, q051, q027, q022 | 5/40 |
| 2 | q151, q152, q016, q024, q043 | 10/40 |
| 3 | q052, q008, q002, q054, q090 | 15/40 |
| 4 | q037, q069, q145, q038, q013 | 20/40 |
| 5 | q010, q014, q154, q103, q128 | 25/40 |
| 6 | q068, q046, q040, q033, q087 | 30/40 |
| 7 | q070, q088, q125, q032, q005 | 35/40 |
| 8 | q117, q143, q042, q021, q047 | 40/40 |

Batch 1：

```bash
python3 -m fs_memory_lab.full_context_cli \
  --output-root 'local-runs/b3-full-context-v1' \
  --run-id 'b3-full-context-v1-main40-run-01' \
  run --through-block 1
```

后续依次把 `--through-block` 改为 2 至 8。该参数表示“运行或恢复到这个累计边界”；已经
验证的 record 会被跳过，不会重复调用。

`run` 在任何模型调用之前会机器校验固定的
`b3-full-context-v1-dev6-run-01` 已 6/6 完成且 pre-gold audit 通过，并要求 dev/main 的
implementation commit、源包、Answerer 和部署配置完全一致。门禁结果写入
`dev-pilot-gate.json`；不满足时 Batch 1 会直接拒绝启动。

每批完成后查看：

```bash
python3 -m fs_memory_lab.full_context_cli \
  --output-root 'local-runs/b3-full-context-v1' \
  --run-id 'b3-full-context-v1-main40-run-01' \
  status
```

### 8.5 完成后审计与评分

```bash
python3 -m fs_memory_lab.full_context_cli \
  --output-root 'local-runs/b3-full-context-v1' \
  --run-id 'b3-full-context-v1-main40-run-01' \
  verify

python3 -m fs_memory_lab.full_context_cli \
  --output-root 'local-runs/b3-full-context-v1' \
  --run-id 'b3-full-context-v1-main40-run-01' \
  evaluate
```

`evaluate` 先再次通过 pre-gold gate，之后才读取固定 gold。

## 9. 输出结构与恢复

```text
local-runs/b3-full-context-v1/<run-id>/
├── run-manifest.json
├── dry-run.json
├── dev-pilot-gate.json          # 仅 main run；绑定已通过的固定 dev pilot
├── status.json
├── events.jsonl
├── run.lock
├── records/B3-FullContext/<question-id>/record.json
├── failures/B3-FullContext/<question-id>/attempt-XXXX.json
├── audits/batch-XX-audit.json
├── audits/batch-XX.PASSED
├── pre-gold-audit.json
└── evaluation.json
```

恢复规则：

- 每次只允许一个 runner 持有 `run.lock`；
- 已完成记录先通过 content hash、plan、question、bundle 和 model 校验才会跳过；
- 失败历史保留，但成功重试后不再算 active failure；
- provider 瞬时错误只重试当前题；
- online command 若留下 failed checkpoint，会打印失败状态并以非零退出码停止，调度器不得
  继续下一题或下一批；
- context-size、served-model、schema 或输入 hash 错误 fail closed；
- 不允许在失败后偷偷改变问题、prompt、顺序、模型或上下文内容。

## 10. 自动验收

自动测试覆盖：

- 30/568/125、固定文本 hash、session 顺序和唯一 citations；
- source package 重复生成幂等；
- Answerer prompt 无条件名、别名或 gold 泄漏；
- 工具列表为空，即无搜索；
- q079 是本地最长 dev payload；
- provider model/style/timeout/response cap fail closed；
- token/attempt 计费字段篡改被拒绝；
- timeout 失败可重试标记与 API key 脱敏；
- immutable checkpoint 原子 no-clobber 发布、短写保护和失败编号防碰撞；
- main API 调用前的固定 dev-6 pilot 机器门禁；
- 单题 checkpoint 不重复计费；
- 未完成 run 拒绝评分；
- batch audit、pre-gold audit 和 evaluation 可重复验证。

## 11. 评分与 E1–E7 的可比口径

完成后报告：

- 官方 LoCoMo category-aware token/stem F1；
- category 1–4 F1、category macro F1、post-stratified F1；
- 诊断性 whole-answer token precision/recall；
- citation validity；
- prompt/completion/total tokens 的逐题、均值与总和；
- attempts、model calls、format repairs 和 latency。

Full Context 没有检索，因此 retrieval recall、Top-K、round/action、ranking 和检索 latency
记为 `N/A`；检索调用和检索 token 记为 0。`source coverage=100%` 是构造属性，不应包装
成检索算法的 recall 成绩。

当前 deterministic evaluation 不调用 LLM-as-Judge。若以后加入 Judge，必须使用与 E1–E7
完全相同的匿名 Judge extension，并单独记录版本和成本。

## 12. 开跑判定

截至本文状态：

- 可以生成、冻结和 dry-run dev/main 计划；
- 还不能直接开始 main Batch 1；
- 进入正式题前有两级联网门槛：先运行 q079 容量 preflight，再完成其余 dev-6 pilot；
- pilot 6/6 审计通过后，机器门禁才允许开始 main Batch 1。

这条顺序既避免浪费正式题 API 成本，也保证 Full Context 与既有 E1–E7 使用同一问题、
Answerer、served model 和评分边界。
