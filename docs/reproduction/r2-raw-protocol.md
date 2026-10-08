# R2-Raw（S1/S2）正式检索协议

状态：**协议与离线运行结构已实现并通过测试；尚未调用 R2 API，尚未产生 R2 实验结果**
确认日期：2026-10-09（Asia/Shanghai）
适用条件：E2（S1 + R2-Raw）、E4（S2 + R2-Raw）
明确排除：E6/S3 的 R2-Curated（ReFind-inspired）暂不设计、不实现、不运行

## 1. 文档目的

本文冻结 S1/S2 上 `R2-Raw` 的方法合同，供后续实现、测试、实验报告和结果审计使用。它回答四个问题：

1. 哪些规则来自 ReFind 论文；
2. 哪些细节可参考作者公开代码；
3. 哪些是为了适配 LoCoMo、S1/S2 与统一 EvidenceBundle 而增加的本项目规则；
4. 什么条件全部通过以后，R2-Raw 才能进入真实 API smoke 和 main-40。

本文取代此前“单条 utterance/source turn 作为 R2-Raw 最小检索 unit”的草案。当前正式单位是 `exchange`。

## 2. 来源与冻结版本

### 2.1 论文

- 本地 PDF：`papers/primary/when-your-agent-opens-the-chat-app-refind.pdf`
- SHA-256：`a94658175d3ceb0c4790bdadd3955aa9acee367bddb5723a2b7306af58a9545c`
- 重点位置：§3（PDF 第 3–6 页）、Appendix A（第 13–16 页）、Appendix G 示例轨迹（第 21 页）
- 公开页面：<https://arxiv.org/abs/2608.12888>

### 2.2 作者公开实现

- 仓库：<https://github.com/imlrz/ReFind>
- 本次审阅的 HEAD：`a80175ca0eeb52a938d7cab7a602bc780de8a577`
- 重要边界：作者仓库明确是 Agent Memory Leaderboard 的 competition adaptation，不是论文离线实验 runner 的逐行发布。

公开代码可作为 tokenizer、BM25、RRF、相邻消息配对和 Agent loop 的实现参考，但本项目必须优先服从论文正式方法。特别是：

- 论文排除已经返回过的整个 session；竞赛代码因平台限制改成 seen-chunk。本项目采用论文的 seen-session。
- 论文描述时间和 seen-session 条件在评分前过滤；本项目按这一顺序实现。
- 公开仓库省略论文 Stage 2 Answerer；本项目使用 E1–E6 共用的统一 Answerer。

### 2.3 本地冻结输入

| 输入 | SHA-256 |
| --- | --- |
| `data/processed/conv-50.jsonl` | `130a5a1e1b75083358ef27a98dd215a4e75c819ace6f2ee9b560ba394e0f0394` |
| `data/manifests/source_map.json` | `6e99115961bae06a48bfb7e82dbdcc18dc32ccf6c5ce57e3c266dfc7a5d4d574` |
| `manifests/s1-flat.json` | `5c5900c333c8f85463f038448560cb4357f1161d6ed43e9fbc86809ba7916d3c` |
| `manifests/s2-foldered.json` | `4858e430f3c197d4f718ea5839596597c3dbbd885e3d1fc654e982a90dc707ac` |
| `manifests/s2-foldered-path-map.json` | `d98e2d8d00bd6081e35ac5a430cbf4679428a3c7bd21f155947444fc2f377a9f` |
| `manifests/s2-foldered.COMMITTED` | `af329bf6749b5909d809d81f52e41079d898a18d86c8bb2d80db0170fbb8b6a9` |

表中后三项路径均相对于 `experiments/locomo-conv50-v1/`。正式运行必须重新验证实际 store、manifest 和 commit marker，不能只信任本文记录的 hash。

## 3. 固定术语

| 术语 | 正式含义 |
| --- | --- |
| `source turn` | LoCoMo 中一个 speaker 的一次发言，对应唯一 `[SxTy]` 和 `dia_id`。 |
| `exchange` | 同一 session 内相邻的一来一回，通常包含两个 source turns；奇数尾项允许 singleton。 |
| `unit` | BM25 建索引、打分和 RRF 排名的最小条目；R2-Raw 中就是 exchange。 |
| `group` | 用于分数聚合和 seen 去重的上层条目；R2-Raw 中就是自然 session。 |
| `center hit` | Top-5 RRF 结果中的一个 exchange。 |
| `context block` | 中心 exchange 加同 session 内前后各 2 个 exchanges。 |
| `note` | Retrieval Agent 从最近一次搜索结果中选择并保存的完整 context block，不是 LLM 摘要。 |

为了避免论文中 `turn` 的含义与 LoCoMo 单次发言混淆，报告统一写 `source turn` 和 `exchange`，不单独使用无修饰的 `turn`。

## 4. R2-Raw 的边界

R2-Raw 只负责找到并交付证据，不直接回答问题：

```text
S1/S2 raw store
  -> RawChatAdapter
  -> exchange-level BM25 + session RRF
  -> Retrieval Agent 多轮检索和 take_note
  -> host 验证、去重和 EvidenceBundle
  -> 统一 Answerer（另一个共享阶段）
```

R2-Raw 包含一个 Retrieval Agent 和三个逻辑工具：

- `search_chatrecord`
- `take_note`
- `finish_search`

BM25、RRF、时间过滤、seen-session、上下文扩展和 EvidenceBundle 校验均由确定性 host 程序完成，不是额外 Agent。

## 5. S1/S2 输入与 exchange 构造

### 5.1 数据来源

- 搜索文字必须来自已经发布并验证的 S1 或 S2 Markdown store。
- `source_map.json` 和 canonical records只用于完整性校验、日期解析和 provenance 回溯，不得向 Retrieval Agent 泄漏 gold answer、category 或 gold evidence。
- S2 中 session 文件正文必须与对应 S1 文件逐字节一致；S2 只改变相对路径。

### 5.2 确定性配对

在每个 session 内按 `turn_index` 升序配对：

```text
(T1,T2), (T3,T4), (T5,T6), ...
```

规则：

- 不跨 session 配对；
- 不按 speaker 名重新排序；
- 不因为图片、空 caption 或文本长度跳过 source turn；
- 奇数长度 session 的最后一个 source turn 形成 singleton exchange；
- 每条 source turn 在且只在一个 exchange 中出现。

`conv-50` 的固定规模为：

| 项目 | 数量 |
| --- | ---: |
| source turns | 568 |
| sessions | 30 |
| 奇数长度 sessions | 16 |
| exchange units | 292 |

计算为 `(568 + 16) / 2 = 292`。

### 5.3 exchange 检索文字

BM25 文档文字按 exchange 内原始顺序拼接：

- speaker 名；
- 原始 `text`；
- 若存在，则加入固定的 `blip_caption` 文本；
- 第二条 source turn 使用同样格式接在第一条之后。

以下字段不进入 BM25 文本：

- `[SxTy]`；
- `dia_id`；
- 图片 URL；
- gold evidence；
- category、gold answer；
- S1/S2 文件路径或 S2 topic 目录名；
- 文件 mtime、构建时间或 Git 信息。

locator、`dia_id`、相对路径和 session date 作为 metadata 保存，用于显示、过滤、校验和评测。

## 6. 确定性检索后端

### 6.1 分词和 BM25

正式参数：

| 参数 | 值 |
| --- | --- |
| lowercase | enabled |
| token splitting | punctuation/whitespace compatible lexical splitting |
| stopword removal | enabled；以冻结的作者代码表为实现基线 |
| stemming | 作者公开代码中的 Porter-style 实现 |
| BM25 `k1` | `1.2` |
| BM25 `b` | `0.75` |

实现时必须把 tokenizer 源码、stopword 列表、版本和 SHA-256 写入机器可读 manifest；不能依赖未固定版本的外部默认 stopword corpus。

### 6.2 单次 `search_chatrecord` 的顺序

固定执行顺序：

1. 校验关键词和可选日期；
2. 以 inclusive `date_from <= session_date <= date_to` 过滤；
3. 排除此前已经返回过的整个 session；
4. 对剩余 exchange units 计算 BM25；
5. 仅保留正分候选；
6. 将同一 session 的 unit BM25 分数求和，得到 session score；
7. 生成 1-based unit rank 和 1-based session rank；
8. 计算 RRF；
9. 以 RRF 降序、canonical exchange 顺序作为同分 tie-break；
10. 返回 Top-5 center exchanges；
11. 为每个 center 在同 session 内扩展 ±2 exchanges；
12. 把本轮返回结果涉及的所有 session 加入 seen-session set。

RRF 公式固定为：

```text
RRF(unit) = 1 / (60 + rank_unit)
          + 1 / (60 + rank_session)
```

Top-5 是 exchange hits，不是 Top-5 sessions；同一轮 Top-5 可以包含来自同一 session 的多个 exchanges。

### 6.3 上下文扩展

- `w = 2`；
- 每个 context block 最多包含 5 个 exchanges，即中心加前后各 2 个；
- 在 session 开头或结尾自然截断；
- 绝不跨 session；
- context exchanges 不因自身 BM25 分数为 0 而删除。

## 7. S1 与 S2 的唯一区别

R2-Raw 的 BM25 文本、exchange、session、日期和排序在 S1/S2 上必须相同。

S2 的相对路径：

- 不进入 BM25；
- 不进入 session aggregate 或 RRF；
- 可以出现在结果的 provenance header 中；
- Retrieval Agent 因而可以在看到第一轮结果后利用 topic path 形成后续关键词。

由此得到两个自动检查：

1. 同一问题、同一第一轮关键词和日期参数下，E2/E4 的确定性 BM25/RRF 排名必须完全相同；
2. 若后续轮出现差异，必须能在 Agent trace 中追溯到 S2 path 的可见性及后续 query 差异。

这是本项目为了研究 folder organization 与 adaptive retrieval 的交互而增加的设计，不是 ReFind 原论文条件。

## 8. Retrieval Agent 协议

### 8.1 Prompt 来源

- 以论文 Appendix A 的 Stage-1 Retrieval Agent Prompt 与 temporal addendum 为规范来源；
- 不直接把作者竞赛仓库中的缩短版 Prompt 冒充论文原文；
- 本地必须保存 normalized published transcription、project-derived 版本、逐段 redline 和 SHA-256。

### 8.2 交互格式

为贴近论文与作者公开实现，正式 R2-Raw 使用文本 ReAct 格式：

```text
Thought: ...
Action: search_chatrecord | take_note | finish_search
Action Input: {...}
```

不将 native API function calling 冒充论文原始接口。解析器只接受一个明确 action 和一个 JSON object；自由文本答案不得进入 evidence 或最终答案。

### 8.3 三个动作

`search_chatrecord`：

```json
{
  "keywords": ["keyword1", "keyword2"],
  "top_k": 5,
  "date_from": "YYYY/MM/DD",
  "date_to": "YYYY/MM/DD"
}
```

- `date_from/date_to` 可省略；
- 正式运行中 `top_k` 固定为 5，其他值产生结构化参数错误，不静默改写为 5。

`take_note`：

```json
{"indices": [1, 3, 5]}
```

- 只能引用最近一次成功搜索的 1-based result indices；
- 保存完整 context block，不允许模型提交或改写 evidence text；
- 新搜索会替换 last observation，因此 Agent 应在下一次搜索前保存有用结果。

`finish_search`：

```json
{}
```

- 只表示停止搜集；
- 不允许携带答案、选项、解释或新证据。

### 8.4 运行预算

- 最多 4 个 planner iterations/actions；
- `search_chatrecord`、`take_note`、`finish_search` 每次各消耗一个 action；
- 不是最多 4 次 BM25 搜索；
- Retrieval Agent 可以提前 finish；
- 到达 action cap 时，host 使用已经明确保存的 notes 结束检索；
- 不采用作者竞赛代码“notes 为空时自动保存最后一次 hits”的 fallback；
- 不采用 direct-BM25 静默降级。没有 notes 时产生空 EvidenceBundle 或明确的 retrieval stop/failure artifact，具体形式由共享 EvidenceBundle 合同约束。

在完整 provider response 返回前发生的 timeout/指定 transient HTTP 可以重试；完整 response 一旦返回，其中 action 不得重放。

## 9. seen-session 与 Agent 状态

每道问题独立初始化：

```text
ControllerState
├── saved_notes
├── seen_session_ids
├── last_observation
└── action_count
```

固定规则：

- seen-session 在每次成功搜索结果形成后更新，不以是否 take_note 为条件；
- 排除的是本轮返回结果涉及的整个 session；
- 同一道题的后续搜索不能再返回这些 sessions；
- 不同题目之间不共享 seen-session 或 notes；
- S1 与 S2 的 episode 状态完全隔离。

## 10. Notes、重叠与 EvidenceBundle

### 10.1 Agent 看到什么

每个 Top-5 hit 在 observation 中保持为独立、带编号的 context block。即使不同命中的 ±2 窗口重叠，也不在观察阶段改变 hit 的编号或内容，以免 Agent 选择语义发生变化。

### 10.2 最终保存什么

Host 根据 result index 重新定位冻结 store 中的原始 source-turn blocks，不信任模型返回的文字。进入 EvidenceBundle 前：

- 相同 source turn 去重；
- 重叠窗口做传递合并；
- 以 session date、session index、turn index 确定性排序；
- 同一 source turn 只交给 Answerer一次、只计 evidence budget 一次；
- 所有 `[SxTy]` 必须能通过 `source_map.json` 映射到唯一 `dia_id`；
- 所有文字必须与已验证 S1/S2 store 一致。

R2-Raw 与 R1 使用同一个 EvidenceBundle schema和同一单源 evidence budget。预算数值不能根据 main-40 成绩调整；先在 dev-6 上按工程可运行性冻结。

## 11. 模型与运行配置

论文在不同实验中使用 GPT-4o-mini 或 GPT-5-mini。学校平台不提供这些完全相同的模型，因此本项目冻结的是算法和 Prompt 的受控复现，而不是 backbone-identical reproduction。

推荐正式配置：

| 项目 | 固定规则 |
| --- | --- |
| requested model | 学校 API 的 `coding` alias |
| served model | 每次响应必须记录，不能用 alias 冒充 |
| 论文目标 reasoning | `high` |
| temperature | `0`；正式 portable 请求也显式发送 |
| 论文目标 Stage-1 max output tokens | `4096` |
| 本地 API style | `portable` |
| portable 实际字段 | 省略 `reasoning_effort` 与 `max_completion_tokens`；这属于学校网关替代，不冒充论文字段已发送 |
| Agent action cap | `4` |
| internal Top-K | `5` |
| context window | `±2 exchanges` |
| RRF smoothing | `60` |

API key 只从环境变量读取；不得写入代码、trace、manifest、日志或 Git。

每个 episode 的 runtime trace 与 `runtime_sha256` 必须同时绑定两套信息：一套是论文目标配置（high / 4096 / temperature 0），另一套是实际 wire profile。正式 NUS `portable` profile 实际只发送 temperature 0，不发送该网关不接受的 reasoning/output-cap 字段。若未来改用 `paper` adapter，两字段才进入 wire request，而且会产生不同的 runtime hash；两类结果不能被当成完全相同配置混合。

## 12. 实际实现模块

```text
fs_memory_lab/
├── r2_protocol.py
├── r2_inputs.py
├── r2_tokenizer.py
├── r2_index.py
├── r2_tools.py
├── r2_prompts.py
├── r2_agent.py
├── r2_artifacts.py
├── r2_runner.py
├── r2_cli.py
└── vendor/refind_tokenizer.py
```

BM25、session aggregate、RRF 与 context expansion 集中在 `r2_index.py`，三动作和 observation 格式集中在 `r2_tools.py`，因此没有为了文件数量而额外拆出空的 `r2_ranking.py` 或 `r2_orchestration.py`。`vendor/refind_tokenizer.py` 与作者固定 commit 的原文件逐字节一致。

## 13. 实现顺序

1. ✅ 固定 R2-Raw protocol、Prompt transcription 和机器可读 manifest；
2. ✅ 实现 S1/S2 preflight 与 raw-store adapter；
3. ✅ 生成并验证 292 个 exchange units；
4. ✅ 实现 tokenizer、BM25、session aggregate、RRF 和 ±2；
5. ✅ 实现时间过滤、seen-session 和稳定 tie-break；
6. ✅ 实现三动作 parser、Agent 状态机与 fake-provider 测试；
7. ✅ 接入共享 EvidenceBundle、预算、原子 artifact 与 verifier；
8. ✅ 执行不调用 API 的完整离线回归；
9. ⏳ 用 dev-6 做小规模真实 API smoke 与 evidence budget 冻结；
10. ⏳ 所有真实运行参数确认后，才允许 main-40。

## 14. 必须通过的自动测试

### 14.1 输入完整性

- 30 个 sessions 全部存在；
- 568 个 source turns 各出现一次且仅一次；
- 精确生成 292 个 exchanges；
- 16 个 singleton exchanges 对应 16 个奇数长度 sessions；
- 每个正常 exchange 包含同 session 的连续两个 source turns；
- S2 文件正文与 S1 对应文件逐字节相同。

### 14.2 检索数学

- toy corpus 的 BM25 可手算复核；
- session score 等于所属正分 units 的 BM25 和；
- RRF 使用 1-based ranks 和 `k=60`；
- 同分使用 canonical exchange 顺序；
- Top-5 是 units，不是 sessions；
- S1/S2 相同 query 的第一轮 backend 排名完全一致。

### 14.3 控制规则

- 日期边界 inclusive；
- 过滤在打分和排名前发生；
- seen-session 后续整组排除；
- ±2 不跨 session；
- singleton 可正常命中和扩展；
- take_note 只能选最近一次搜索结果；
- 模型不能伪造 evidence text；
- 达到 action cap 不自动保存未选择 hits；
- 完整响应后的 action 不因 retry 被重放。

### 14.4 EvidenceBundle

- locator 与 `dia_id` 映射唯一；
- 重叠窗口确定性合并；
- 相同 source turn 只计一次预算；
- bundle 中文字与冻结 store 完全一致；
- 检索前后 store hash 不变；
- question input 不包含 gold answer、gold evidence 或 category。

## 15. 来源归属总表

| 规则 | 归属 |
| --- | --- |
| raw chat、不做 LLM 索引改写 | ReFind 论文 |
| paired-turn/exchange 粒度 | ReFind 论文；LoCoMo 角色名映射为本项目适配 |
| BM25 `k1=1.2,b=0.75` | ReFind 论文 |
| session aggregate + RRF `k=60` | ReFind 论文 |
| Top-5、±2、时间过滤、seen-session | ReFind 论文 |
| 三动作与 evidence-only Retrieval Prompt | ReFind 论文 Appendix A |
| 具体 stopword 表和 Porter-style 代码 | 作者公开 competition repository，按 commit 冻结 |
| singleton exchange | 作者公开相邻配对实现可参考；LoCoMo 明确规则由本项目冻结 |
| S2 path 显示但不打分 | 本项目实验设计 |
| source locator/`dia_id` 回溯 | 本项目实验设计 |
| `blip_caption` 作为文本输入、URL 不访问 | 本项目 LoCoMo 协议 |
| overlap merge、预算、EvidenceBundle | 本项目统一评测协议 |
| NUS `coding` controller | 本地模型替代 |
| NUS `portable` 请求省略 reasoning/output cap | 本地网关替代；论文目标值与实际 wire 分开记录 |
| retry、artifact、hash、offline verifier | 本项目可复现性与安全补全 |

## 16. 当前结论

截至 2026-10-09，E2/E4 的 R2-Raw 离线 harness 已经搭建完成。固定输入预检得到 S1/S2 各 292 个 exchange units；两者检索正文完全一致，路径差异为 292/292。离线 fake-provider 可以完整走通 search→take_note→finish、EvidenceBundle、原子发布、失败产物和批量 summary；这只证明代码与协议连通，**不代表学校 API smoke 已通过，也不代表 dev-6/main-40 已经运行**。实现、命令和产物结构见 `r2-raw-implementation.md`。
