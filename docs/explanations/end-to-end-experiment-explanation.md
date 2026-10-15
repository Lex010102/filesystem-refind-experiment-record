# Filesystem × ReFind 长期对话记忆实验：完整解释

> 本文用于向导师、师兄、评审或其他第一次接触项目的人，从头到尾解释实验研究什么、为什么这样设计、怎样执行、如何评价，以及目前得到什么结论。本文以冻结的 `formal-v1` 协议和已完成的 280 条正式结果为准。

## 1. 一句话说明这个实验

这项实验不是在比较七个互不相关的问答系统，而是在做一个受控的长期记忆实验：

> 对同一段长期对话、同一批问题和同一个回答模型，分别改变“记忆怎样存储”和“证据怎样检索”，观察答案效果、证据覆盖与计算成本如何变化。

完整链路是：

```text
LoCoMo 长期对话
    ↓
统一 canonical records 和 source map
    ↓
构造 S1 / S2 / S3 三种存储
    ↓
使用 R1 / R2 / R3 检索证据
    ↓
统一 EvidenceBundle
    ↓
同一个 Answerer 作答
    ↓
离线加载 gold，计算答案、证据、效率和可靠性指标
```

## 2. 为什么要做这个实验

### 2.1 长期对话不能简单全部塞给模型

长期对话可能包含多个日期、多个话题、旧状态和新状态、图片描述、重复和矛盾信息，以及数百甚至数千轮聊天。如果每次提问都把完整历史送给模型，会带来：

- token 成本过高；
- 上下文越来越长；
- 有关信息被无关内容淹没；
- 模型看到正确内容却没有利用；
- 超出上下文窗口。

因此长期记忆系统通常要先保存历史，再按问题检索有关证据。

### 2.2 存储和检索是两个不同问题

一个系统答错，可能发生在多个阶段：

```text
原始对话
   ↓
记忆写入：重要信息有没有保存下来？
   ↓
证据检索：保存的信息有没有被找到？
   ↓
证据选择：找到后有没有进入最终证据包？
   ↓
答案生成：模型有没有正确使用证据？
```

错误可以进一步分为：

- 写入遗漏：整理记忆时漏掉了信息；
- 写入污染：整理时把事实改错或过度合并；
- 检索遗漏：事实在记忆中，但搜索没有找到；
- 证据选择错误：搜索结果出现了，但没有保存；
- 预算损失：证据因为太长，没有进入最终上下文；
- 推理错误：正确证据已经送给 Answerer，但仍然答错。

因此本实验把系统拆成：

```text
Storage → Retrieval → EvidenceBundle → Answerer
```

## 3. 四个研究问题

### RQ1：文件夹分类本身有没有用

如果正文完全不变，只把原始 session 放进不同主题文件夹，是否能帮助模型更快、更准确地查找？核心比较是 `E1 vs E3`。

### RQ2：LLM 整理记忆究竟带来什么

LLM 整理可能合并分散信息、突出状态和减少跨 session 搜索，但也可能造成遗漏、污染或冗余。主要比较是 `E1 / E3 / E5`，但 S3 同时改变内容和结构，因此不是纯单变量对照。

### RQ3：ReFind 式检索能否修复 Filesystem 的检索错误

在同一存储上，把“LLM 自己翻文件”换成“BM25 排名＋多轮查询”，效果和成本怎样变化？对应 `E1 vs E2`、`E3 vs E4`、`E5 vs E6`。

### RQ4：原始聊天作为第二证据源是否有价值

如果整理记忆遗漏或污染了信息，同时保留 raw chat 检索源，能否恢复答案？对应 `E7 = E2 raw evidence + E6 curated evidence`。

## 4. 数据与术语

### 4.1 数据范围

实验使用官方 LoCoMo 中的 `conv-50`：

```text
自然 sessions：30
source turns：568
官方问题：204
```

三种存储都使用完整的 30 个 sessions 和 568 条 source turns，不是只使用一个 session。

### 4.2 术语

| 术语 | 含义 |
|---|---|
| source turn | 一个人的一次发言 |
| exchange | 同一 session 中相邻的一来一回，通常包含两个 source turns |
| session | 某一天发生的一次完整聊天 |
| conversation | 同一对人物跨多个日期的全部长期聊天 |
| `dia_id` | LoCoMo 官方为一条发言提供的编号 |
| `[SxTy]` | 本项目加入的 session-turn 定位标签 |

例如 `[S3T4]` 表示第 3 个 session 中的第 4 条 source turn。`source_map.json` 负责把它映射回官方 `dia_id` 和原始 JSON 记录。

### 4.3 Canonical records

原始 LoCoMo JSON 先被转换成 568 条统一标准记录，每条包含 conversation、session、日期、turn、全局顺序、speaker、文本、`dia_id`、`[SxTy]`、图片 caption 和内容 hash。S1、S2、S3 全部从同一份 canonical records 生成，避免预处理差异成为混杂变量。

### 4.4 图片处理

实验不重新访问图片 URL，也不运行新的视觉模型。如果原数据包含 `blip_caption`，就把 caption 作为固定文本和原发言一起存储与检索。因此这是一项文本记忆实验，而不是完整视觉理解实验。

### 4.5 正式问题

标准问题和答案全部来自 LoCoMo 官方。正式实验排除 adversarial，并排除 4 道 gold 与 transcript 有实质冲突的问题，冻结 40 道题：

| 类别 | 类型 | 数量 |
|---|---|---:|
| C1 | Multi-hop | 10 |
| C2 | Temporal | 10 |
| C3 | Open-domain | 7 |
| C4 | Single-hop | 13 |
| 合计 |  | 40 |

40 题覆盖全部 30 个 sessions。另有独立 dev-6 用于正式冻结前的预算测试，不能根据 main-40 的结果重新调参或换题。

## 5. 三种存储方式

### 5.1 S1：平铺原始会话

S1 将每个自然 session 原样保存为一个 Markdown 文件：

```text
/memories/
├── session-01.md
├── session-02.md
├── ...
└── session-30.md
```

它不摘要、不改写、不合并、不删除。speaker、text、caption、日期、locator 和原始顺序全部保留。S1 共 30 个文件、568 条 source turns、约 114,456 bytes，建库不需要 LLM。

可以把它理解为：把 30 次聊天原封不动放进同一个抽屉。

### 5.2 S2：文件夹化原始会话

S2 从 S1 出发，由 Foldering Agent 创建四个主题父目录：

```text
/memories/
├── cars-and-auto-work/
├── music-and-performance/
├── photography/
└── travel-and-outdoors/
```

Agent 只能查看、grep 和移动完整文件，不能改写正文、摘要、拆分、合并、复制或改文件名。于是 S1 与 S2 的正文逐字节相同，唯一变化是文件路径和主题目录。S2 仍为 30 个文件、568 条 turns、114,456 bytes。

这使 `E1 vs E3` 成为最干净的存储对照：同样的聊天内容，只增加主题导航。

### 5.3 S3：LLM 整理后的文件系统记忆

S3 让 Management Agent 按时间顺序维护长期记忆。

568 条 turns 被确定性切成 85 个输入 chunks：

- 每个 chunk 最多 8 条连续 source turns；
- payload 最多 3000 个 Unicode 字符；
- 不拆开一条 source turn；
- 不跨自然 session。

3000 字符是建库输入 chunk 上限，不是最终文件长度，也不是检索证据预算。

每个 chunk 启动新的管理 episode，但共享同一个持续存在的文件系统。Agent 可以使用 `view/create/str_replace/insert/delete/rename/grep` 创建和更新记忆。

最终 S3 不是 85 个文件，而是：

```text
/memories/
├── calvin.md
└── dave.md
```

其中包含 35 个 H2 主题和 390 条带 locator 的 fact bullets。555 个不同 source locators 出现在正文中；13 个 locator 未出现，但不能直接解释为已经证明丢失 13 个事实。

S3 约 304,640 bytes，比 S1/S2 更大，所以不能称为简单压缩。它测试的是内容重写、事实整合、人物归档和主题组织，同时也可能产生遗漏、污染和冗余。

S3 一次性构建共使用 85 个管理 episodes、842 次 LLM 调用和约 3,086 万 tokens。建库成本与逐题查询成本分开统计。

## 6. 两类检索思想与 R3 适配

研究层面主要比较两种检索范式：

1. R1：Filesystem 风格的 agentic 文件检索；
2. R2：ReFind 风格的排名检索。

S3 已经不是原始聊天，需要把 R2 适配到新的 fact/H2 结构，因此代码中称为 R3。R3 是本项目的 ReFind-inspired adapter，不是第三篇论文提出的独立算法。

## 7. R1：让 LLM 像人一样翻文件

R1 不预先为所有内容统一排名，而是让 LLM 自主决定看哪个目录、搜索什么关键词、打开哪个文件、读取哪些行和何时停止。

### 7.1 四个只读文件工具

| 工具 | 作用 |
|---|---|
| `view` | 查看目录、整个文件或指定行范围 |
| `grep` | 用正则表达式寻找匹配行 |
| `toc` | 查看 Markdown 标题及其行号范围 |
| `section_read` | 按标题路径读取完整 section |

本项目另外增加两个控制动作：

| 动作 | 作用 |
|---|---|
| `take_note` | 把已经真实观察过的来源范围保存为正式证据 |
| `finish_search` | 显式结束检索阶段 |

### 7.2 `grep` 的实际作用

`grep` 是逐行正则定位器，不是 BM25 或语义搜索。它返回路径、行号和匹配的完整行，默认最多 100 条结果；它不做相关度排名，也不自动返回上下文。

例如：

```text
grep(pattern="brand|expand", path="/memories")
```

可能返回：

```text
session-12.md:L44: Calvin: My plan is to expand my brand...
```

LLM 还要在下一轮调用 `view(session-12.md, lines=40-48)` 才能读取上下文。读取范围没有固定 ±N，由 LLM 根据问题和文件结构决定。

### 7.3 R1 在三种存储上的区别

- S1：先面对 30 个平铺 session，通常全局 grep 后再打开相关文件；
- S2：先看到 4 个主题目录，可以先缩小目录再 grep；
- S3：先选择人物文件，再用 `toc/section_read` 读取有关 H2 主题，或 grep 具体事实。

E1 与 E3 的工具相同，主要差别是目录结构以及与该结构相匹配的 store-aware 搜索提示。

### 7.4 `take_note`

`take_note` 不是让 LLM 自由撰写证据摘要。它只能引用先前成功观察中的 observation ID、路径和行范围。Host 重新从冻结 store 读取原文，生成 EvidenceItem。因此模型不能保存没看过的文字或把推理结论伪装成来源。

### 7.5 `finish_search`

`finish_search` 不回答问题，也不生成证据。它只表示检索结束。

Filesystem 论文中的 Search Agent 可以边搜边直接回答；本实验为了统一 Answerer，把过程改成：

```text
搜索 → take_note 保存证据 → finish_search → 统一 Answerer 回答
```

因此 `finish_search` 类似“结束搜索”按钮，不是“提交答案”按钮。它只能携带结构化停止原因，不能包含答案、证据引文或解释。

### 7.6 R1 的 round

一次 provider completion，也就是 LLM 做出一次新的工具决策，算一个 round。一轮属于 filesystem、note 或 finish 三种模式之一。`finish_search` 也需要一个正式决策，因此占一轮；最终 Answerer 在 R1 结束之后运行，不进入 round cap。

| 条件 | R1 上限 |
|---|---:|
| E1 / S1 | 20 rounds |
| E3 / S2 | 20 rounds |
| E5 / S3 | 40 rounds |

## 8. R2：BM25 找候选，LLM 修改查询

R2 把工作分成两部分：

```text
LLM：理解问题、生成关键词、判断还缺什么
确定性后端：BM25、group 聚合、RRF、Top-K、上下文扩展
```

### 8.1 检索单元

568 条 source turns 在每个 session 内配成 `(T1,T2)、(T3,T4)…`；若末尾只剩一条，则形成 singleton exchange。最终得到 292 个 exchange units 和 30 个 session groups。

BM25 索引 speaker、原始文本和 BLIP caption；不索引 locator、`dia_id`、图片 URL、gold 或 S2 路径。

### 8.2 查询词

Retrieval Agent 读取问题后生成一组关键词和可选日期，例如：

```json
{"keywords": ["Calvin", "brand", "expand"], "top_k": 5}
```

这些词共同形成一次 BM25 query，不是每个词分别对 292 个 exchange 运行独立搜索。

### 8.3 一次 R2 搜索

1. 验证关键词和日期；
2. 执行可选日期过滤；
3. 排除已返回过的整个 session；
4. 为剩余 exchange 计算 BM25；
5. 汇总同一 session 的正分，得到 session score；
6. 分别得到 exchange rank 和 session rank；
7. 用 RRF 融合两个排名；
8. 选择 Top-5 exchange 中心命中；
9. 对每个中心扩展同 session 前后各 2 个 exchanges；
10. 将涉及的 session 标记为 seen。

公式为：

```text
RRF(unit)
= 1 / (60 + exchange_rank)
+ 1 / (60 + session_rank)
```

固定参数：

| 参数 | 值 |
|---|---:|
| BM25 `k1` | 1.2 |
| BM25 `b` | 0.75 |
| RRF 常数 | 60 |
| 中心命中 | Top-5 |
| 上下文 | 同 session ±2 exchanges |
| action cap | 4 |

Top-5 是 5 个中心 exchanges，不是 5 个 turns 或 5 个完整 sessions。

### 8.4 R2 actions

每一步 planner 只能选择：

```text
search_chatrecord
take_note
finish_search
```

最多 4 个 planner actions，不是最多 4 次 BM25 搜索。最终 Answerer 不计入这 4 个 actions。达到 cap 时，host 只使用已经明确 `take_note` 的证据，不自动保存最后一次搜索结果。

这是本项目对 ReFind “4 iterations”的正式操作化。后续可以测试 6/8 actions，但不能回头改变 formal-v1。

## 9. `grep` 与 BM25 的区别

| 方面 | R1 `grep` | R2 BM25 |
|---|---|---|
| 搜索对象 | 文件中的每一行 | 292 个 exchange units |
| 查询来源 | LLM 生成正则 | LLM 生成关键词列表 |
| 匹配方式 | 字面/正则 | 词频、IDF、长度归一化 |
| 排名 | 没有统一相关度排名 | 所有 exchange 统一评分和排序 |
| 返回 | 匹配行 | Top-5 中心命中 |
| 上下文 | 不自动返回 | 自动扩展 ±2 exchanges |
| 后续读取 | LLM 再调用 `view` | 后端直接给 context block |

最简洁的区别是：R1 中 LLM 既想关键词又自己翻文件；R2 中 LLM 主要负责查询规划，候选排名由确定性后端完成。

## 10. R3：把 ReFind 核心适配到 S3

ReFind 原本使用 `exchange → session`。S3 没有自然 exchange，因此 R3 改成 `fact bullet → H2 topic`。

| 方面 | R2 Raw | R3 Curated |
|---|---|---|
| 存储 | S1/S2 原始聊天 | S3 整理记忆 |
| unit | exchange | fact bullet |
| unit 数 | 292 | 390 |
| group | session | H2 topic |
| group 数 | 30 | 35 |
| 搜索文本 | speaker＋raw text＋caption | 人物＋H2 标题＋fact text |
| 上下文 | 同 session ±2 exchanges | 同 H2 ±2 facts |
| seen 去重 | 整个 session | 整个 H2 |
| Top-K | 5 | 5 |
| action cap | 4 | 4 |

R3 保留 tokenizer、BM25、group score、RRF、Top-5、多轮查询、时间过滤、`take_note` 和 `finish_search`，只改变 unit/group 和上下文结构。因此 E6 应称为 ReFind-inspired retrieval over agent-curated memory，而不是 ReFind 原论文的直接复现。

## 11. E1–E7 为什么这样组合

### 11.1 六个单源条件

| 条件 | 存储 | 检索 | 作用 |
|---|---|---|---|
| E1 | S1 平铺原始 session | R1 | 原始文件检索基线 |
| E2 | S1 平铺原始 session | R2 | 原始聊天增强检索 |
| E3 | S2 文件夹化原始 session | R1 | 测试目录分类 |
| E4 | S2 文件夹化原始 session | R2 | 测试目录与增强检索结合 |
| E5 | S3 LLM 整理记忆 | R1 | Filesystem 整理记忆主条件 |
| E6 | S3 LLM 整理记忆 | R3 | 整理记忆上的增强检索 |

矩阵是：

| 存储 | Filesystem 式 R1 | 增强排名检索 |
|---|---|---|
| S1 平铺原文 | E1 | E2 / R2 |
| S2 文件夹化原文 | E3 | E4 / R2 |
| S3 整理记忆 | E5 | E6 / R3 |

这不是完全正交的 3×2，因为 S3 不能直接使用 raw exchange/session 结构，需要 R3 适配。E1–E4 是最接近干净 2×2 对照的部分。

### 11.2 固定存储，比较检索

```text
E1 vs E2：S1 上 R1 与 R2
E3 vs E4：S2 上 R1 与 R2
E5 vs E6：S3 上 R1 与 R3
```

### 11.3 固定检索思想，比较存储

```text
E1 vs E3：正文相同，只增加目录
E1 vs E3 vs E5：在 R1 下比较三种存储
E2 vs E4：原始检索正文相同，比较路径线索
```

S2 路径不进入 BM25，因此 E2/E4 第一轮在相同 query 下的底层排名必须一致。路径只在 provenance header 中可见，可能影响 controller 后续查询。

## 12. E7 双源融合

E7 不重新检索，而是复用同题已经生成的：

```text
E2：原始聊天证据
E6：整理记忆证据
```

然后验证问题一致、保留各路顺序、按 RAW/CURATED 交替加入、精确去重，不调用 LLM 摘要，再交给统一 Answerer。

选择 E2＋E6 而非 E1＋E6，是因为两路都采用“排名检索＋多轮 controller＋EvidenceBundle”的总体范式，可以减少融合时混入 R1 文件导航协议的差异。

E7 每路最多使用一个完整预算，总预算可达 2B。它是系统级融合实验，不是严格等上下文预算的纯因果比较。

## 13. 统一 EvidenceBundle 和 Answerer

E1–E6 都必须先产生统一 EvidenceBundle，记录问题、store 身份、证据原文、路径、行号、section、locator、`dia_id`、trace、停止原因、成本、模型身份和查询前后 hash。

模型不能自由写一段“证据摘要”；host 从冻结 store 重新读取真实文本并计算 hash。

之后 E1–E7 共用一个 Answerer。它只能看到 question 和 EvidenceBundle，看不到条件名、gold、完整 trace 或工具。它必须只用给定证据，处理时间冲突，只引用真实 evidence ID，并输出：

```json
{
  "answer": "...",
  "citations": ["ev-001", "ev-003"],
  "insufficient_evidence": false
}
```

正式参数为 `temperature=0`、`max completion tokens=2048`。统一 Answerer 是本项目为公平比较设计的，不是两篇论文逐字提供的 prompt。

## 14. 单题运行流程

每一道问题按以下顺序处理：

1. 在线 runner 只读取 question ID、conversation ID 和 question text；
2. 验证 S1/S2/S3 正式快照与 hash；
3. 根据条件执行 R1、R2 或 R3；E7 复用 E2/E6；
4. Host 验证 evidence path、行号、locator 和预算；
5. 统一 Answerer 作答并生成 citations；
6. 再次计算 store hash，确认查询只读；
7. 保存 RunRecord、EvidenceBundle、AnswerResult 和成本；
8. 280 条在线记录全部完成并通过 audit 后，离线加载 gold 评分。

## 15. 公平性和冻结配置

| 项目 | 正式设置 |
|---|---|
| 问题 | 同一 40 题、同一顺序 |
| Evidence budget B | E1–E6 均为 16,000 characters |
| E7 预算 | 每路 16,000，总计最多 32,000 |
| R1 cap | E1/E3 为 20 rounds，E5 为 40 |
| R2/R3 cap | 最多 4 actions |
| requested model | `coding` |
| required served model | `qwen3.8:27b` |
| Answerer | E1–E7 完全相同 |
| temperature | 0 |
| 并发 | 1 |
| store | 查询期间严格只读 |
| gold | 在线阶段不可见 |

16,000 字符限制的是最终送给 Answerer 的 EvidenceBundle，不直接限制搜索 Agent 观察了多少文件内容。因此 E5 即使最终 bundle 预算相同，也可能在搜索阶段读取很长的 S3 文件，产生高额 retrieval tokens。

如果下一个完整 EvidenceItem 放不进预算，就整项跳过并记录 `budget-skipped`，不会从中间截断或用 LLM 压缩。另有 1,000,000 provider-reported tokens 安全熔断，仅用于防止异常失控，不是常规证据预算。

## 16. 正式运行规模

```text
40 道问题 × 7 个条件 = 280 条最终记录
```

正式运行分为 8 个 batches，每个 batch 为 5 道问题 × 7 个条件 = 35 条。E1–E6 的起始顺序在题目间轮换；E7 永远在同题 E2 和 E6 完成后运行。每条记录都验证 citations、served model、schema 和 store hash。

## 17. 评价指标

### 17.1 LoCoMo token/stem 指标

官方评分会做小写化、去标点/冠词和 stemming，再计算 token 重合：

```text
Precision = 重合 token / 候选答案 token
Recall    = 重合 token / 参考答案 token
F1        = 2PR / (P + R)
```

它不是要求整句话逐字一样；部分重合会获得部分分数。但同义改写可能被低估，冗长回答会损害 Precision。

### 17.2 Evidence Recall

通过 `source_map.json` 将检索证据 locator 映射到官方 gold `dia_id`：

```text
Evidence Recall = |检索到的 gold dia_id| / |全部 gold dia_id|
```

同时记录 Any-hit、All-hit 和 citation validity。两道 open-domain 题缺完整 gold evidence，因此 evidence 指标按 38 题计算，答案 F1 仍按全部 40 题计算。

### 17.3 LLM-as-Judge

同一个匿名 Judge 为每条候选答案给出 `correct / partial / incorrect` 三档标签，由同一批标签计算：

```text
Strict Accuracy = correct / 40
Partial Rate = partial / 40
Soft Score = (correct + 0.5 × partial) / 40
```

它是后续辅助语义评价，不替代官方 F1，也不是两个 Judge。

### 17.4 效率与可靠性

同时统计 retrieval/answer/total tokens、model calls、rounds/actions、evidence characters、cap、空证据、预算跳过、API/schema failures、served-model consistency 和 store hash。

## 18. 正式结果

所有效果分数范围为 0–1；tokens 为每题平均值。

| 条件 | Precision | Recall | Token F1 | Judge Strict | Partial | Judge Soft | Evidence Recall | 平均 tokens |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| E1 | 0.3074 | 0.6464 | 0.3646 | 0.6000 | 0.2250 | 0.7125 | 0.8092 | 151,814.6 |
| E2 | 0.3661 | 0.6342 | 0.3972 | 0.5000 | 0.2750 | 0.6375 | 0.7325 | 18,437.1 |
| E3 | 0.3483 | 0.6973 | **0.4146** | **0.6250** | 0.2250 | **0.7375** | 0.8202 | 150,204.4 |
| E4 | 0.3456 | 0.6456 | 0.3971 | **0.6250** | 0.1500 | 0.7000 | 0.7303 | **18,418.7** |
| E5 | 0.2907 | **0.7310** | 0.3488 | **0.6250** | 0.2000 | 0.7250 | **0.9254** | 294,102.2 |
| E6 | 0.3020 | 0.6592 | 0.3594 | **0.6250** | **0.1250** | 0.6875 | 0.8158 | 39,378.1 |
| E7 | 0.2948 | 0.6548 | 0.3380 | 0.6000 | 0.2250 | 0.7125 | 0.8860 | 56,486.9 |

## 19. 当前结果怎样解释

### 19.1 文件夹分类在 R1 下有效

E3 相对 E1 的 F1 从 0.3646 提升到 0.4146，Soft 从 0.7125 提升到 0.7375。正文完全相同，说明主题目录在当前数据中为 agentic 文件导航提供了有效信号。

### 19.2 在 R2 下目录价值减弱

E2 与 E4 的 F1 分别为 0.3972 和 0.3971，几乎相同。R2 已经对 exchange 进行细粒度排名，而路径又不参与 BM25，因此目录没有继续产生明显的 token-F1 增益。

### 19.3 R2/R3 的主要优势是效率

- E2 比 E1 节省约 87.86% tokens，同时 F1 更高；
- E4 比 E3 节省约 87.74% tokens，但 F1 略低；
- E6 比 E5 节省约 86.61% tokens，同时 F1 略高。

所以 ReFind-style 检索显著降低查询成本，但准确率收益依赖存储、问题和评价口径。

### 19.4 更多 evidence 不等于更好答案

E5 的 Evidence Recall 最高（0.9254），但 F1 只有 0.3488，并且查询成本最高。可能原因包括证据冗余、整理污染、旁边噪声和 Answerer 使用失败。

### 19.5 E6 是更好的效果-成本折中

E6 相对 E5 略微提高 F1 并节省 86.61% tokens，但 Evidence Recall 和 Judge Soft 有所下降。因此它不是全面胜出，而是明显更经济的折中。

### 19.6 简单双源融合没有自动获胜

E7 的 Evidence Recall 高于 E2/E6，但 F1 更低、成本更高；其 Soft 高于 E2/E6而 Strict 介于两者之间。这表明双源证据可能恢复部分语义信息，同时引入重复、冲突或噪声。

## 20. 论文来源与本项目扩展

| 组成 | 来源与性质 |
|---|---|
| S1/S2/S3 | Filesystem 论文的存储思想 |
| S3 的 8-turn/3000-character 输入约束 | Filesystem 论文设置 |
| R1 文件工具、Prompt 5/6/7、20/20/40 caps | Filesystem-derived |
| R1 evidence-only、`take_note`、`finish_search` | 本项目公平性改造 |
| exchange/session 两级检索、BM25、RRF、Top-5、±2 | ReFind 核心思想 |
| R2 的 LoCoMo 适配 | 本项目实现 |
| R3 fact→H2 adapter | 本项目提出 |
| E4、E6、E7 | 本项目新增条件 |
| 统一 EvidenceBundle 和 Answerer | 本项目公平性设计 |
| main-40、hash、审计和 LLM Judge | 本项目实验基础设施与扩展 |

这项工作应描述为：以 Filesystem 和 ReFind 为方法来源，构造统一、可审计的受控比较，并增加 curated retrieval 和 raw-curated 双源融合，而不是声称逐字复现了两篇论文的全部实现。

## 21. 结论边界和后续工作

当前只有一个 conversation、40 道题、一个 served model、一次 S3 build 和一次 Judge 运行；不含 adversarial，图片只使用 caption。S3 同时改变内容、组织和文件大小；R1 round 与 R2/R3 action 也不是同一种资源单位。E7 总预算高于单源。

因此当前结论应写成描述性 empirical findings，而不是普遍因果定律。

后续可以：

- 将 R2/R3 action cap 扩展到 6/8；
- 增加 Full Context baseline；
- 扩展到 LoCoMo10 的更多 conversations；
- 增加模型和 S3 多次独立构建；
- 设计带冲突识别和来源选择的双源融合；
- 对写入、检索、预算和回答错误做逐题归因。

## 22. 可直接用于口头汇报的总结

我们研究的是长期对话记忆中的“怎么存”和“怎么找”。首先把同一段 LoCoMo 长期对话构造成三种记忆：平铺的原始 session 文件、正文不变但增加主题目录的 session 文件，以及由 LLM 持续整理形成的主题化人物记忆。然后比较两类检索：一种让 LLM 像人一样浏览目录、grep 和读取文件；另一种先用 BM25 和两级 RRF 对聊天单元排名，再由 LLM 多轮修改查询和选择证据。六个单源条件形成存储与检索的配对比较，第七个条件再融合原始聊天证据和整理记忆证据。所有方法最后都输出统一 EvidenceBundle，并由同一个 Answerer 回答，因此差异可以更清楚地归因到存储和检索。结果显示，主题文件夹能明显帮助文件式检索；ReFind 式检索能大幅降低 token 成本，但并非在所有存储和评分口径下都提高准确率；LLM 整理记忆具有很高的证据召回，却不一定带来更好的最终答案；简单的双源融合也会在恢复信息的同时引入噪声。实验的核心结论不是某一种方法全面获胜，而是存储、检索、证据质量和回答能力之间存在明显的交互与权衡。

## 23. 相关权威文档

- `docs/plans/one-month-experiment-map.md`
- `docs/reproduction/formal-v1-freeze.md`
- `docs/reproduction/r1-evidence-only-contract.md`
- `docs/reproduction/r2-raw-protocol.md`
- `docs/reproduction/r3-curated-design-and-provenance.md`
- `docs/analysis/e1-e7-results-analysis-framework.md`
