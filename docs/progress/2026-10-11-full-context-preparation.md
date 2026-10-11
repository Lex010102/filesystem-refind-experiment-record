# 2026-10-11 B3 Full Context 准备记录

## 目标

在既有 E1–E7 formal-v1 之外增加一个独立 `B3-FullContext` baseline。该 baseline 不构建
记忆、不搜索，直接把 `conv-50` 全部原始会话交给同一个共享 Answerer，用于比较完整信息
可见时的回答质量、token、延迟与检索式方法的效果—成本权衡。

## 本次完成内容

1. 确认 Full Context 与 E1–E7 分离，原 280 条结果和冻结配置不修改；
2. 从冻结 S1 确定性构造 30 个 session-level evidence items；
3. 生成并验证机器源包、人工 transcript、manifest 和 verification；
4. 实现独立 EvidenceBundle、runner、CLI、checkpoint、run lock、失败记录和恢复；
5. 实现每 5 题 batch audit、pre-gold audit 和完成后评分；
6. 实现 source/code/prompt/model/question/evaluator hash 绑定；
7. 完成真实数据上的无 API 自动测试与故障注入；
8. 编写独立操作与跑批指南。

## 关键设计决策

### 无检索

每道题只有一次完整上下文 Answerer episode，`tools=[]`。不存在 R1/R2/R3、BM25、Top-K、
reranking、上下文扩展或搜索 Agent。正常时 episode 只有一次模型调用；网络重试或一次
schema repair 可能增加 provider/model calls，并会被完整计数。

### session 正文而非文件系统包装

模型读取 30 个 S1 文件中经过 source attribution 验证的聊天正文，不读取 YAML frontmatter
和仅用于文件系统路由的标题。全部 568 个 source turns 和 125 个 BLIP captions 保留，且
按 session-01 至 session-30 排序。

### citation ID 修正

早期方案写过 `FC-S01` citation，但共享 Answerer 只接受内容寻址的 `ev-*`。最终协议为：

- 正式 citation：`ev-*`；
- 人工别名：`FC-S01` 至 `FC-S30`，存在于源包映射、transcript 标题和运行时映射
  metadata，但不进入 Answerer prompt。

这样无需改动共享 Answerer，B3 与 E1–E7 的回答 prompt 和引用验证保持一致。

### 源包而非问题相关 EvidenceBundle

固定发布物是 question-free 的 `context-package.json`。运行时再把同一个源包与当前问题
组合成 content-addressed bundle，避免把问题或 gold 写进共享源文件。

### portable API 边界

Answerer 仍以 2,048 tokens 作为 output 规划值；但学校的 portable adapter 不发送
`max_completion_tokens` 和 `reasoning_effort`，所以 manifest 明确记录 wire 值为 `null`，
不把本地规划值误写为服务端强制限制。

## 固定源包结果

```text
experiments/locomo-conv50-v1/baselines/b3-full-context-v1/
```

| 项目 | 结果 |
| --- | ---: |
| sessions | 30 |
| source turns | 568 |
| caption turns | 125 |
| evidence characters | 108,960 |
| evidence bytes | 108,982 |
| evidence text SHA-256 | `12c3041b32cd7ff32bf6c913b95992cebf48ed3bd1d28ff9f1cdd29c8e927738` |
| source package ID | `full-context-source-4add27428aae2daed6df17e171379c7ea1a16a9f68690fbb2149403cd4062b55` |

## Context size 检查

dev-6 六道题中，最长本地请求是 `conv-50-q079`：

| 项目 | 结果 |
| --- | ---: |
| complete message characters | 118,939 |
| complete message bytes | 118,961 |
| estimated input tokens | 33,983–41,013 |
| plus 2,048-token planning reserve | 36,031–43,061 |

因此 32k context 很可能不足，64k 更安全。但学校实际部署窗口未知，本地也没有精确同款
tokenizer，所以 q079 的真实 API preflight 是进入正式 Batch 1 前不可省略的第一个联网
门槛。上述 characters/bytes 只统计 system 与 user 消息正文，不含 HTTP/JSON/provider
framing；成功响应的 provider `prompt_tokens` 才是权威值。

q079 是 dev-6 最长题（118,939 characters），也略长于 main Batch 1 最长的 q081
（118,928），但 main-40 全局最长 q043 为 119,004，因此它是近最坏情况而非全体严格最大值。

## 安全与可追溯性修正

实现过程中发现并处理了以下问题：

- audit 若包含当前时间会导致重复 verify 不幂等，最终 audit 身份改为纯确定性内容；
- provider 必须严格核验 `portable`、`coding`、300 秒和 20 MB response cap；
- RunRecord 的 attempts 和 P/C/T tokens 必须逐项等于 AnswerResult usage 汇总；
- 续跑跳过记录前必须核对 run、plan、question 和 frozen source；
- transient error 被 Answerer 包装后仍应正确标记 `retryable=true`；
- failure 文本自动移除 API key；
- runner 保存 failed checkpoint 后，online CLI 必须以非零状态退出，避免 launcher 把失败
  当成功并继续下一批；
- immutable record/failure 先写临时文件、fsync，再用同目录 hard link 原子 no-clobber
  发布，避免崩溃遗留“存在但截断”的假 checkpoint；
- event append 加文件锁和短写循环，失败编号按已有最大编号递增，避免并发交错或编号碰撞；
- batch 完成按问题顺序的连续 block 判定，不能用任意完成数除以 5；
- 源包 hash 使用磁盘真实 bytes（包含结尾换行），并绑定四个发布文件；
- Full Context manifest 校验父 formal-v1 core，并额外 hash 所有直接依赖；
- bundle 同时绑定 S1 tree、source map、records、attribution index、固定 paths 与 session IDs。
- main-40 在任何 provider 调用前必须通过固定
  `b3-full-context-v1-dev6-run-01` 的 6/6 pre-gold audit，并逐项比对 implementation
  commit/tree、源包、Answerer、部署配置；通过证明写入 `dev-pilot-gate.json`。

## 测试范围

测试使用真实冻结 S1/dev-6 和 fake provider，不调用学校 API。覆盖：

- 30/568/125 与固定文本 hash；
- 序列化、反序列化、content identity；
- prompt 首尾覆盖和无条件/gold 泄漏；
- `tools=[]`；
- 源包幂等；
- provider 配置 fail closed；
- q079 单题 checkpoint 复用、不重复调用；
- usage 篡改检测；
- timeout retry、失败记录和凭据脱敏；
- 原子 immutable 发布、event 短写恢复和 failure 编号间隙；
- 未完成 dev pilot 阻止 main provider 调用，完成后门禁可追溯；
- 未完成 run 拒绝 pre-gold verify；
- dev-6 完成、audit 重复验证和 deterministic evaluation。

本次最终离线验收结果：

- `tests.test_full_context`：8/8 通过（真实冻结数据 + fake provider）；
- 全仓库 `unittest discover`：325 项通过，唯一未导入项是既有
  `test_r1_prompts.py` 依赖当前系统 Python 未安装的 `pytest`，并非断言失败；
- 本机 Anaconda pytest 自身因环境级 `rlcompleter` segmentation fault 无法启动，因此随后
  用系统 Python 加最小参数化 shim 逐项执行该文件的 8 个断言 case，全部通过；
- `python3 -m fs_memory_lab.formal_v1_cli verify` 通过，证明既有 E1–E7 formal-v1 冻结清单
  未被 Full Context 扩展改变。

## 下一步

1. 提交并冻结本次实现和源包；
2. 离线 prepare/dry-run `b3-full-context-v1-dev6-run-01`；
3. 连接学校 VPN 后只运行 q079 preflight；
4. 成功后完成 dev-6 pilot 并审计；
5. main-40 可以预先离线 prepare/dry-run，但只有 pilot 通过后才能开始 Full Context
   Batch 1；runner 会机器强制执行该门禁。

完整命令见：

```text
docs/plans/full-context-baseline-v1-operation-plan.md
```

## 离线冻结完成状态

同日完成上述离线步骤：

- 实现冻结 commit：`78d5d88076dc43f14a5ee2e353b28991455b66d4`；
- dev run：`b3-full-context-v1-dev6-run-01`，manifest
  `full-context-run-manifest-1a7ad8e747a5a16e673975c301ad0f525bc3ec7b03e52e64c2c8368a4e3da3da`；
- main run：`b3-full-context-v1-main40-run-01`，manifest
  `full-context-run-manifest-8af39c115f4e956ca95d611399f31242a4cff041c24de6e76d608f5f654f129c`；
- 两套 dry-run 均通过全部 9 项检查；状态分别为 0/6 与 0/40，active failures 均为 0；
- 离线 prepare/dry-run 明确记录 `api_provider_not_constructed=true` 与
  `semantic_gold_not_loaded=true`，没有读取 API key、调用学校 API 或查看 gold；
- main manifest 已绑定固定 dev pilot 机器门禁。

因此，剩余工作不是继续写 runner，而是联网运行 q079 preflight、完成 dev-6 pilot 并通过
审计；随后才能启动已经准备好的 main Batch 1。
