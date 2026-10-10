# main-40 `formal-v1` 正式冻结说明

冻结日期：2026-10-10
状态：**已冻结、已离线验证；尚未启动 main-40**

## 1. 冻结结论

`formal-v1` 是 B=16000 的 dev-6 × E1–E7 pilot 通过后建立的正式实验协议。
它的机器可读权威文件是：

- `experiments/locomo-conv50-v1/formal-v1/manifest.json`
- manifest ID：`formal-337ebb2061b34493a2e81cad19453eb85481d82a646ce4c40a750e2222d08925`
- 实现快照 Git commit：`e2633826614fad8fdece74bc66150127f3a33082`
- Git release tag：`formal-v1`

manifest 保存了完整 40 题顺序和 280 个执行键，并逐项固定 store、prompt、
预算、cap、模型、retry、并发、融合和评分规则。`fs-formal-v1 verify` 会从当前
仓库重新计算这些值；任一文件、题目或协议漂移都会 fail closed。

本次操作没有调用 API，也没有运行任何 main-40 题目。

## 2. Pilot 通过依据

冻结依据为：

- retrieval：`stage3-dev6-b16000-20261010T074000Z`，36/36；
- retrieval summary：`summary-50f06ee8226af615bd595c007cc7a0156d7d52e674de418efd9e152c631451c7`；
- pilot：`stage4-dev6-e1-e7-b16000-20261010T074000Z`，42/42；
- audit：`pilot-audit-f14d85476acb00a936cd0be311d3b691149ef9b66e7cce420f9600856e7e00a7`；
- 系统失败率 0%，无空 EvidenceBundle；
- citation、store hash、served model、E2/E4 backend ranking、E7 无重检索和
  E7 成本口径全部通过；
- 预算跳过 episode 比例 8.33%，低于预注册 20% 门槛。

## 3. 三种存储快照

以下 `tree_sha256` 是正式查询前后都必须保持不变的内容树 hash：

| Store | 形式 | 文件数 | tree SHA-256 | manifest SHA-256 |
| --- | --- | ---: | --- | --- |
| S1 | 平铺原始 session | 30 | `ca39361e8e23f204a9fda55fc83e3ce7f411c7c8d582939aa63688c1923c7679` | `5c5900c333c8f85463f038448560cb4357f1161d6ed43e9fbc86809ba7916d3c` |
| S2 | 文件夹化原始 session | 30 | `e9b96bcd4e036f4ea4599edb06e9c0527c929442b09efe05d09ea416b8a4469d` | `4858e430f3c197d4f718ea5839596597c3dbbd885e3d1fc654e982a90dc707ac` |
| S3 | LLM 整理 filesystem | 2 | `983238fddc77a88ef4ae3d06b50bcfd25a429f497e89c6af4d9477cefca9cad2` | `70fb5ad56ff11bb849ce60b193cd6db29be601e613ca3afb76aac336e3b36e00` |

三者共享 canonical records hash
`130a5a1e1b75083358ef27a98dd215a4e75c819ace6f2ee9b560ba394e0f0394`
和 source map hash
`6e99115961bae06a48bfb7e82dbdcc18dc32ccf6c5ce57e3c266dfc7a5d4d574`。

## 4. 题目与执行顺序

- 输入：`main-40-input.jsonl`
- input SHA-256：`31a65ab18797abb4491cf8de2e172050d25000eb5c1f6ddb77383d3900b757af`
- gold SHA-256：`a6833ca585ca26efcdd038a5cf202fd46657999053ebd7b8cc73793f7544718b`
- 题目数：40；条件数：7；正式结果数：280。

题目顺序、每题文字、question hash 和每个执行键全部写进 manifest。执行策略是：
每题内部轮换 E1–E6 的首发顺序，随后才运行该题 E7；E7 永远位于本题 E2/E6
之后。gold 只能在 280 条 RunRecord 全部完成并通过验证以后由 evaluation module
加载。

## 5. R1 / R2 / R3 冻结值

### R1

- protocol：`r1-evidence-agent-v3`；
- E1/S1 round cap：20；E3/S2 round cap：20；E5/S3 round cap：40；
- agent limits hash：`ed5f6b5077da7406b5fa2919a3c8100f4379cde23939e661f4a8caf02281024a`；
- evidence-only user template hash：`f20cd087abf1f96cc228342c81be31af49c670c6933da54fc0fbb9b0d78e43f9`；
- E1 derived Prompt 7：`62b8b913b4150076b36955c9c8aa8ce9c72e8670988668ff57a4397171d44129`；
- E3 derived Prompt 6：`3a6c8a077746b1297c02152b53359533cbb02d6f8488ea56f51ce9894d112b3c`；
- E5 derived Prompt 5：`56a7ee328b702acf677218605c2d649afe0089eda09165e5aadb286969116965`。

论文转录 Prompt 5/6/7 及其 hashes 也全部保存在 manifest，不能只修改 derived prompt
而不触发 verifier。

### R2

- protocol：`r2-raw-refind-style-v1`；
- protocol hash：`b338aafc73f4f4fd674ad5433e624b1a4e2f44e3422e06b9f5bb1dfa7d1dacb2`；
- derived system prompt：`6930d93099ac20b76e881b68cbb63b46e1a0a3e2ff43453db685551c3339a6dc`；
- user template：`bbf8e2059f1123e9b8ae90c1d31cf3217d0a427387450a31d93032bd3e8e690c`；
- action cap：4；Top-K：5；context window：±2 exchanges。

### R3

- protocol：`r3-curated-refind-inspired-v1`；
- protocol hash：`0535a229b856dd73be89f4b617dfb9c046e9bde178e9e6689f3ac062397b0878`；
- derived system prompt：`60d0c608bdda6e13c46a9e6cbf4cd7cae4f7eea8d7fcd2d8a4f8f9bde415df7c`；
- user template：`53bed8501ade4999e7a1dc52a5119ce8cee29388e30e99d072fe82525b1bb00d`；
- action cap：4；Top-K：5；context window：±2 fact units。

R2/R3 的论文 prompt 分块、本地 addendum 和 observation template 的所有 hashes
均在 manifest 中逐项记录，这里只列正式组合最关键的 hash。

## 6. 统一 Answerer

- protocol / prompt ID：`shared-evidence-answerer-v1` /
  `project-defined-shared-evidence-answerer-v1`；
- prompt SHA-256：`6ee299d5a5095aaaac19c0a7b61321af3b1c87e7f6aec818f47749097b87a572`；
- temperature：0；max completion tokens：2048；格式修复最多一次；
- 输入只包含 question 与 EvidenceBundle；看不到 condition、gold、trace 或工具。

正式 prompt 原文已直接写入 manifest，而不是只保存 hash。其核心要求是：只使用输入
证据、不猜测、按日期解决冲突、只引用真实 evidence ID；输出严格为
`answer`、`citations`、`insufficient_evidence` 三字段 JSON。

## 7. E7 融合规则

- protocol：`e7-deterministic-fusion-v1`；
- contract hash：`035770f66df01bfdc937227a819ada720163fd6fa03416d88e5484ea54ae0abb`；
- 只复用同题 E2 raw 与 E6 curated EvidenceBundle，不重新搜索、不调用 LLM、
  不生成摘要；
- 源内顺序不变，按 RAW → CURATED 交替；
- 精确去重键 `(source_kind, dia_ids, text_sha256)`；
- locator 相同但文字不同的 raw/curated 证据都保留；
- 每路最多 B，总预算最多 2B；
- E7 成本计 E2+E6 retrieval 各一次及 E7 Answerer，不重复计 E2/E6 Answerer。

## 8. 预算、模型与运行配置

| 项目 | `formal-v1` |
| --- | --- |
| Evidence budget B | **16,000 characters**，E1–E6 完全相同 |
| E7 budget | 每路 16,000；总计最多 32,000 characters |
| requested model | `coding` |
| required served model | `qwen3.8:27b`，任一次响应不同即失败 |
| API style | `portable` |
| 单请求 timeout | 300 秒 socket timeout + macOS 主线程 wall-clock deadline |
| timeout retry | 最多 3 次；退避 2、4 秒 |
| retryable HTTP | 408/429/500/502/503/504；最多 5 次；退避 5/15/30/60 秒 |
| retry 边界 | 只在完整 provider response 返回前；已返回 action 永不重放 |
| response cap | 20,000,000 bytes |
| 并发 | **1**；retrieval episode 与 Answerer 均串行 |
| failure | 立即停止；续跑只跳过重新验证成功的 content-addressed record |

R1/R2/R3 每 episode 另有 1,000,000 provider-reported total-token 安全熔断；
它只是异常保护，不是 evidence budget，也不会给 E5 额外证据额度。

## 9. 评分规则

正式主指标是固定 LoCoMo 官方 category-aware token F1：

- 官方仓库 commit：`cbfbc1dba6bc53d00625212a0f22d55ffee7c1fc`；
- 官方 evaluator SHA-256：`8e3be5d57ff2ff9ec5cd05939592f468c5f3f1fd95d13e431932bdf6bf0fd6fd`；
- NLTK 规则版本：3.8.1；
- category 1：逗号分隔 multi-answer F1；
- category 2/4：stemmed token F1；
- category 3：gold 在首个分号处截断，再算 stemmed token F1；
- 主汇总：每个条件 40 题的 micro F1；同时报告 category F1、category macro
  F1 和按可靠池 30/32/7/85 加权的 post-stratified F1；
- 次指标：Evidence Recall、Any-hit、All-hit、citation validity、tokens、
  rounds/actions 和 cap rate；
- incomplete run 不出部分条件分数。

匿名 LLM judge 在 `formal-v1` 中明确关闭，因为通过的 pilot 没有验证这一额外 API
环节。若以后增加 judge，必须建立新版本，不能把 judge 结果混进 `formal-v1` 主结果。

## 10. 冻结后的变更控制

从本文件与 manifest 提交开始，不得因为 main-40 分数不好修改 prompt、B、搜索
参数、cap、题目顺序、模型或评分规则。若发现实质性程序错误：

1. 保留 `formal-v1` 与其已产生记录；
2. 建立新的 formal 版本和独立 manifest；
3. 明确列出受影响条件；
4. 对所有受影响条件完整重跑；
5. 不得在同一结果表中混用两个版本的 RunRecord。

纯文档更正可以提交，但不能改变 manifest、算法、输入或结果口径。

## 11. 离线验证

以下命令不读取 API key、不联网、不运行题目：

```bash
cd '/Users/wangwenqi/Desktop/memory bench'
python3 -m fs_memory_lab.formal_v1_cli --repo-root . verify
```

预期输出包括同一个 manifest ID、实现 commit、40 questions、280 planned records、
B=16000 和 served model `qwen3.8:27b`。
