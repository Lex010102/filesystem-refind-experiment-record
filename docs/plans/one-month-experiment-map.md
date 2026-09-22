# 一个月实验地图：Filesystem Memory × ReFind-style Retrieval

版本：v1.0（实验开始前草案）
日期：2026-09-22
执行周期：4 周（D1–D28；D29–D30 作为缓冲）
正式数据：LoCoMo `locomo10.json` 中的 `conv-50`
正式规模：60 道预注册主测试题；资源允许时扩展到 154 道可靠题，并把 4 道已知缺陷题单列为附录

---

## 0. 这项研究最终要回答什么

本研究不是为了保证某个新方法一定取得最高分，而是要把下面四件事说清楚：

1. 原始聊天、带目录的原始聊天、LLM 整理后的文件系统，哪一种更容易被查询系统正确利用？
2. 把 ReFind 式多轮检索接到不同存储上，能修复多少原生文件检索错误，又会制造多少新错误？
3. 当整理后的文件丢失、扭曲或污染信息时，再检索原始聊天作为第二证据源，能恢复多少答案？
4. 每一种改进要付出多少构建成本、检索 Token、模型调用、工具调用和等待时间？

一句话研究主线：

> 固定同一段 LoCoMo 对话和同一回答模型，系统地改变“怎么存”与“怎么找”，并把每一道错题追溯到写入、检索或推理中的具体环节。

### 0.1 本月成功的最低标准

本月不是以“跑出一个最高分”为成功，而是以以下可复现闭环为成功：

- 三份存储都完成构建、校验、冻结；
- 六个单源条件和一个双源条件共享统一的证据与回答协议；
- 60 道正式题 × 7 个条件 = 420 个结果均可追溯；
- 每个答案能回到 evidence package、检索 trace、存储位置和 LoCoMo 原始 `dia_id`；
- 能自动输出效果、检索、成本、repair/harm 和错误类型表；
- 能人工复核所有关键翻转案例；
- 报告清楚区分“论文复现”“受控改造”“本研究新组合”。

---

## 1. 研究边界与表述边界

### 1.1 我们复现的是“方法”，不是原论文分数

Filesystem 论文使用 `gpt-5.4-mini`。本地 NUS SoC 网关目前请求别名为 `coding`，实际曾返回 `qwen3.8:27b`。因此最终报告应使用：

- “method reproduction / 方法复现”；
- “controlled extension / 受控扩展”；
- “under the NUS-served backbone / 在 NUS 实际服务模型下”。

不能写“完全复现论文分数”。每次调用都要同时记录 requested model 和 served model；若正式批次中 served model 改变，应立即暂停。

### 1.2 本月只做这些

- 一个 benchmark：LoCoMo；
- 一段主对话：`conv-50`；
- 三种存储；
- 两种检索；
- 一个双源融合；
- 一个固定的系统模型配置；
- 一个固定的 Judge 配置。

本月不加：向量检索、Cross Encoder、新 benchmark、第三种检索、第四种存储、自适应路由、查询后写回记忆、多模型能力对比。

### 1.3 论文依据与本研究改造

| 项目 | 论文情况 | 本研究处理 |
| --- | --- | --- |
| S1 Verbatim dump | Filesystem §3：每个 session 一个原文文件，平铺 | 尽量复现 |
| S2 Foldered sessions | Filesystem §3：在 S1 上只移动文件，零字节修改 | 尽量复现，并强制 hash 校验 |
| S3 Agent-curated | Filesystem §3、Appendix A.1：从空目录按 chunk 增量管理 | 使用当前论文 prompt 转录和 Center 工具 |
| R1 Center | Filesystem §3、Appendix A.3：文件工具检索后直接回答 | 改为只收集证据，再交给统一回答器 |
| R2 ReFind | ReFind §3：原始 chat 的 turn→session 两级多轮检索 | S1/S2 较接近原方法；S3 必须称 ReFind-inspired |
| E7 双源 | 两篇论文都没有 | 本研究新条件 |
| LoCoMo 60 题 | Filesystem 用 `conv-50` 的 158 道非对抗题 | 本月的预注册、资源受限子集 |

统一两阶段协议是最重要的公平性改造：

```text
检索器只收集证据
        ↓
统一 EvidenceBundle
        ↓
同一个 Answerer 生成最终答案和引用
```

这样最终答案差异主要来自“找到了什么证据”，而不是两个检索代理使用了不同回答 prompt。

### 1.4 我们今天站在哪里

当前仓库已经有：

- `/memories` 文件工具沙盒；
- S3 management prompt 与七个写工具；
- R1 的四个只读工具；
- 单条文本 `ingest` 和单题 `ask`；
- Alice 两批增量写入 trace；
- 分块、路径、权限、API 请求与工具循环的单元测试。

当前仓库还没有：

- LoCoMo dataset loader 和正式 split；
- S1/S2 builder；
- evidence-only R1；
- BM25、RRF、时间过滤、邻居扩展和多轮 notes；
- 统一 Answerer 和 E7 fusion；
- benchmark runner、断点续跑、批量评测和错误归因。

因此现在是“底层原型已跑通”，不是“七组实验已搭好”。后续必须按依赖顺序完成，不能直接开始花费大量 API 跑正式题。

---

## 2. 研究问题、假设和主要比较

### RQ1：存储组织是否改变效果与成本？

在 R1 固定时比较：

- E3 vs E1：只有目录分类是否有用？
- E5 vs E3：LLM 改写、整合和主题组织的净作用是什么？

不预设 S2/S3 一定更好。整理可能提高检索效率，也可能丢失细节或混淆历史状态。

### RQ2：ReFind 式检索能否修复不同存储的检索错误？

- E2 vs E1：原始聊天上的 R2 vs R1；
- E4 vs E3：目录化原文上的 R2 vs R1；
- **E6 vs E5：整理文件系统上的 R2 vs R1（核心主要比较）**。

预期机制不是“所有题都更好”，而是多跳、时间与旧新状态问题可能更受益；多轮搜索也可能引入噪声。

### RQ3：原始聊天第二证据源能否修复整理损失？

- **E7 vs E6：增加原始聊天后，是否修复 S3 中的遗漏或扭曲？（核心主要比较）**
- E7 vs E2：整理后的高层线索是否又能补充纯原文检索？

### RQ4：错误发生在哪一层，代价是多少？

对 E5→E6、E6→E7 的每个答案翻转，区分：

- 写入遗漏；
- 写入扭曲；
- 检索不到；
- 只检索到部分证据；
- 看到了证据但推理失败；
- 新旧事实冲突处理失败；
- benchmark gold 问题；
- 系统/API 失败。

### 2.1 统计上的主次关系

主要比较只设两个，避免看到结果后挑最有利的比较：

1. E6 vs E5；
2. E7 vs E6。

其他配对属于次要或复现性分析。结论优先报告效应大小与置信区间，p 值只作辅助。

---

## 3. 七个实验条件

| 条件 | 存储 | 检索 | 论文状态 | 研究作用 |
| --- | --- | --- | --- | --- |
| E1 | S1 平铺原始 session | R1 Center | Filesystem 已做 | 原始文件基线 |
| E2 | S1 平铺原始 session | R2 ReFind-style | 跨论文组合 | 原始聊天增强检索 |
| E3 | S2 文件夹化原始 session | R1 Center | Filesystem 已做 | 目录分类作用 |
| E4 | S2 文件夹化原始 session | R2 ReFind-style | 新组合 | 增强检索能否利用目录线索 |
| E5 | S3 Agent-curated | R1 Center | Filesystem 已做 | 整理文件系统基线 |
| E6 | S3 Agent-curated | R2 ReFind-inspired | 新组合 | 核心增强检索条件 |
| E7 | E2 raw evidence + E6 curated evidence | 确定性融合 + 统一回答 | 新条件 | 双源恢复与成本 |

关键公平性规则：

- S1 只构建一次，E1/E2 共享同一快照；
- S2 只构建一次，E3/E4 共享同一快照；
- S3 只正式构建一次，E5/E6 共享同一快照；
- E7 不重新搜索，复用 E2 和 E6 的 evidence；
- 七个条件使用同一个 Answerer、输出格式与判分流程；
- 查询期间所有存储只读，前后 hash 必须一致。

---

## 4. 数据前置处理

### 4.1 数据范围

下载并保存官方 `locomo10.json`，但本月正式实验只用 `conv-50`：

- 204 道 QA；
- 158 道非 adversarial QA；
- Multi-hop 32；
- Temporal 32；
- Open-domain 7；
- Single-hop 87；
- Adversarial 46，不进入本研究主实验。

Filesystem 论文指出评测顺序第 20、64、112、138 题的 gold 与 transcript 有实质冲突。我们的最低 60 题主实验从另外 154 道可靠题中抽取。若之后扩展：

1. 先扩到完整 154 道可靠题；
2. 再把 4 道缺陷题单独运行并放入附录；
3. 如需与论文 158 题口径比较，再给出包含缺陷题的结果，但不能把它当最可信结论。

### 4.2 原始数据不可变原则

保存三层数据：

```text
data/raw/locomo10.json             # 下载原件，只读
data/processed/conv-50.jsonl       # 统一后的聊天记录
data/manifests/source_map.json     # [SxTy]、dia_id 与原始记录映射
```

每条 processed record 至少包含：

```text
conversation_id
session_id
session_index
session_date
turn_index
locator             # [SxTy]
dia_id
speaker
text                 # 原文，不小写、不改标点
source_sha256
```

检索用的小写、分词和 stemming 只能进入 index，不得覆盖原始文本。

### 4.3 Loader 验收

自动断言：

- conversation 数、session 数、utterance 数和 QA 数符合官方文件；
- `conv-50` 为 30 sessions、204 QA；
- 类别 1–4 共 158 道；
- 每个 `dia_id` 唯一；
- 每个 `[SxTy]` 唯一并能双向映射到 `dia_id`；
- session 日期能解析；
- 原始文本 hash 在后续流程中不变；
- QA、gold answer 和 gold evidence 不进入任何存储构建输入。

### 4.4 正式题与开发题

主测试 60 题，抽样前剔除四个已知缺陷题：

| 类别 | 正式题数 |
| --- | ---: |
| Multi-hop | 13 |
| Temporal | 13 |
| Open-domain | 7 |
| Single-hop | 27 |
| 合计 | 60 |

使用 seed 42 在类别内部抽样，并立刻写出确切 question IDs 和 SHA-256。不能只保存 seed，因为库版本或排序变化可能使抽样结果改变。

另取 10 道不与正式题重叠的 `conv-50` QA 作为工程开发集，例如 3 Multi-hop、3 Temporal、4 Single-hop。Open-domain 全部保留给正式测试。开发集只用于：

- 检查输出 schema；
- 调整通用 prompt 表述；
- 选择 evidence budget；
- 校准 Judge 的解析规则；
- 发现工程 bug。

不得在 prompt 中加入 conv-50 的人物专用规则、问题答案或 gold evidence。Alice 小样本继续作为最便宜的写入与更新 smoke test。

### 4.5 防止数据泄漏

| 阶段 | 允许看到 | 禁止看到 |
| --- | --- | --- |
| S1/S2/S3 构建 | 对话、说话人、日期、来源 ID | 问题、gold answer、category、gold evidence |
| R1/R2 检索 | 问题、存储或索引 | gold answer、gold evidence |
| Answerer | 问题、EvidenceBundle | gold answer、条件分数、Judge 标签 |
| Judge | 问题、gold、匿名 candidate；attribution 时再看 evidence | E1–E7 条件名、研究假设、成本 |
| 分析程序 | 所有离线结果 | 不再调用或修改存储 |

---

## 5. 三种存储如何构建与核对

### 5.1 S1：Flat Verbatim Sessions

做法：

1. 每个 session 一个 Markdown 文件；
2. 30 个文件全部放在同一目录；
3. frontmatter 只记录 session 编号、日期、speakers 等必要元数据；
4. 正文逐条保留 speaker、locator、`dia_id` 和 text；
5. 不摘要、不重写、不删除、不合并；
6. 构建不调用 LLM，构建模型成本为零。

验收：

- 恰好 30 个 session 文件；
- 所有 utterance 按原顺序出现；
- 每个 `dia_id` 正文中恰好出现一次；
- 从 S1 反向解析出来的聊天与 processed records 完全相同；
- 生成逐文件 byte hash、body hash、字节数与 turn 数。

### 5.2 S2：Foldered Verbatim Sessions

做法：

1. 从已验证的 S1 做副本；
2. LLM 只能使用 `view`、`grep`、`rename`；
3. LLM 设计 topic folders，并把完整 session 文件移动进去；
4. 不允许 create、edit、insert、delete；
5. 文件正文和文件名不变，只改变父目录路径。

验收是硬门槛：

- S1 与 S2 的 body-hash 多重集合完全相同；
- 理想情况下完整 byte-hash 多重集合也完全相同；
- 文件数仍是 30；
- 生成 `S1_path -> S2_path` 映射；
- 任一正文 hash 变化都停止实验，不得解释为“目录效果”。

### 5.3 S3：Agent-curated Filesystem

做法：

1. 从空 `/memories` 开始；
2. 按 session 和 turn 的真实时间顺序生成 canonical stream；
3. 严格使用 Filesystem 论文主实验 chunk 规则：每块最多 8 个连续 turn，达到 3,000 characters 提前封块；
4. 每个 chunk 单独启动一个 management episode；
5. 使用论文管理 prompt、LoCoMo 来源 locator 扩展与 Center 七个写工具；
6. 每个 chunk 前保存快照，之后保存完整工具 trace；
7. 完成后冻结只读快照，E5/E6 共用。

说明：以自然 session 作为 S3 chunk 是一个值得研究的后续变量，但本月不做，因为会把“存储方式”与“输入粒度”同时改变。

验收：

- 每个 `.md` 都有合法 frontmatter；
- `name` 与文件 stem 一致；
- 所有 locator 均能在 `source_map.json` 中找到；
- 没有测试问题或答案进入文件；
- 没有写出 memory root；
- 报告 dirs/files/sections/KB/cross-references；
- 报告总 chunks、管理轮次、工具调用和 tokens；
- 记录 source-locator coverage，但不把 locator 存在自动等同于语义忠实。

### 5.4 为什么 S3 只正式构建一次

S3 会受模型随机性影响。一个月内如果给 E5、E6 分别重建，检索比较就混入了不同 store。正式协议固定一份 S3：

```text
同一个 S3 snapshot
     ├── E5 使用 R1
     └── E6 使用 R2
```

报告需说明结论条件化于这一份 store。重复构建属于未来工作，不是本月必做项。

---

## 6. 统一证据结构

所有检索器必须输出同一种 `EvidenceItem`，否则后面无法公平回答和定位错误。

```json
{
  "evidence_id": "stable-id",
  "source_kind": "raw|curated",
  "store_id": "s1|s2|s3",
  "path": "/memories/...",
  "section": "# ... > ## ...",
  "line_start": 10,
  "line_end": 18,
  "session_id": "...",
  "group_id": "...",
  "source_locators": ["[S3T4]"],
  "dia_ids": ["..."],
  "timestamp": "...",
  "speaker": "...",
  "text": "verbatim text actually sent to the answerer",
  "retrieval_round": 2,
  "query_terms": "...",
  "rank": 3,
  "score": null,
  "text_sha256": "..."
}
```

每题的 `EvidenceBundle` 还要记录：

- question ID 和 condition；
- 所有 search actions；
- seen groups；
- selected notes；
- evidence token count；
- 停止原因；
- store snapshot hash；
- requested/served model；
- usage、工具次数、延迟与错误。

`text` 必须是最终真正交给 Answerer 的文字，不能只记录检索器最初看到但后来没有保存的内容。

---

## 7. R1：原生文件检索如何运行

### 7.1 可用工具

- `view`
- `grep`
- `toc`
- `section_read`

工具均只读。对于 S1/S2，应使用论文给 raw session store 的相应搜索提示；对于 S3，使用 hierarchical store 提示。

### 7.2 从“直接回答”改成“只交证据”

当前本地 `ask` 是边找边直接回答。正式实验新增 evidence-only controller：

1. 查看 `/memories` 一次；
2. 根据文件名、description 和问题选择搜索路线；
3. 用短关键词 `grep`；
4. 用 `view/toc/section_read` 查看足够上下文；
5. 调用 `take_note` 把确切片段写入 EvidenceBundle；
6. 调用 `finish_search`，不回答问题。

原论文 R1 的 tool-round hard cap 可保留：S1/S2 最多 20，S3 最多 40。它们只是防失控上限，实际轮次和成本必须如实报告。如果出现 hit-cap，该题需要标记，不能与正常停止混在一起。

### 7.3 R1 停止条件

- Agent 判断所有子问题已有证据；
- 达到证据 token 上限；
- 达到 hard cap；
- 连续两轮没有新增 evidence，并已做一次全局兜底搜索。

### 7.4 R1 核对点

- note 中的 path/line/section 真实存在；
- note 文本与文件片段完全一致；
- note 的 locator 能映射回原始数据；
- 检索前后 store hash 一致；
- 不能把 Agent 自己的解释伪装成 evidence。

---

## 8. R2：ReFind-style 检索如何运行

### 8.1 固定算法参数

| 参数 | 固定值 |
| --- | --- |
| BM25 | `k1=1.2`, `b=0.75` |
| 预处理 | lowercase、空格/标点切分、Porter stemming、stopword removal |
| 两级融合 | unit rank + group rank 的 RRF |
| RRF 常数 | `k=60` |
| 每轮返回 | Top-K = 5 |
| 原始聊天上下文 | 命中 utterance 前后各 2 条，不跨 session |
| 最大搜索次数 | 4 |
| 时间 | Agent 可提供 date_from/date_to；打分前过滤 |
| 去重 | 后续轮排除已返回 group |
| 笔记 | 保存命中原文/文件原文片段，不让 LLM重新总结 |

### 8.2 S1/S2 上的 R2

- 最小 unit：一条 LoCoMo utterance；
- group：session；
- 上下文：同一 session 前后 ±2 utterances；
- 时间：session date；
- seen-group dedup：已返回 session 后续轮不再返回。

为了让 E4 有意义又不过度改变 ReFind：

- BM25 **不使用文件夹路径打分**；
- 返回结果的 provenance header 会显示相对文件路径；
- 多轮 controller 可以从 S2 的 topic path 获得线索并改变后续查询；
- E2/E4 第一轮 BM25 结果应完全相同，这是自动 sanity check；
- 后续若出现差异，应能从 controller trace 中看到它如何利用了目录词。

若路径完全隐藏，E2/E4 理论上会成为重复条件；若路径直接加入 BM25，又会把检索后端改成 taxonomy-weighted BM25。当前方案处在两者之间，并必须在方法部分写清楚。

### 8.3 S3 上的 R2（必须称 ReFind-inspired）

原始 ReFind 的层级是 turn→session；S3 已经改写为 Markdown taxonomy，不能假装完全相同。固定适配如下：

- unit：最小 leaf Markdown section；若文件没有 heading，则整文件为一个 unit；
- BM25 文本：frontmatter description + heading path + section body；文件系统 path 不直接进入打分；
- group：该 unit 所属的 top-level heading region；没有 top-level heading 时退回文件；
- group score：同 group 的 unit BM25 分数求和；
- context：同 group 内按文件顺序相邻的前后各 2 个 sibling/leaf sections；
- seen-group dedup：后续轮排除已返回 topic group，不能粗暴排除整个大型人物文件；
- 时间：从 section 内 locator 映射到原始 session 日期，绝不能用文件 mtime；
- source IDs：从 section 和返回上下文中的 locator 提取。

### 8.4 R2 的四轮决策

每轮 controller 可以：

1. `search_chatrecord(query, date_from?, date_to?)`；
2. 查看 Top-5 结果及上下文；
3. `take_note(result_ids)` 保存可能有用的完整片段；
4. 改写关键词、缩小时间或寻找另一个多跳事实；
5. 证据充分时 `finish_search`。

新搜索前必须保存上一轮有用结果，因为 observation 不应被当作永久记忆。最多 4 次 search，不要求跑满。

### 8.5 R2 单元测试

- toy corpus 的 BM25 排名可手工验证；
- RRF 公式与排名可手工验证；
- 多个命中同一 group 时能获得 group boost；
- ±2 不跨 session/topic boundary；
- 时间边界包含/排除正确；
- 已看 group 后续不返回；
- E2/E4 第一轮排名一致；
- note 文本是原返回片段，不是 LLM 摘要；
- 同一输入、同一 index 得到确定性 backend 结果。

---

## 9. 统一 Answerer

Answerer 对 E1–E7 完全相同，只接收：

- question；
- 按固定模板序列化的 EvidenceBundle；
- 回答与引用规则。

不接收 condition 名、gold answer、gold evidence、存储之外的背景知识指令。

正式系统角色建议统一请求已经验证过 function calling 的 `coding` 别名，并逐调用核对实际 `served_model`。Judge 不需要工具调用，可优先试固定的 `qwen3.6:35b`；只有在开发集上满足 JSON 可解析率至少 95%、基础 rubric 测试稳定时才采用，否则预先规定回退到 `coding`。这个选择必须在正式测试前完成并冻结，不能根据 test 分数换 Judge。若网关不接受 `temperature=0` 或 seed，也要在 manifest 中明确记录，而不是假装确定性。

建议输出：

```json
{
  "answer": "...",
  "citations": ["evidence-id-1", "evidence-id-4"],
  "insufficient_evidence": false
}
```

固定规则：

- 先直接回答；
- 每个事实只能引用 evidence IDs；
- 新旧状态冲突时结合时间选择当前状态，并保留必要历史；
- 没有证据时明确说不足，不得调用模型自身知识补齐；
- citation 必须程序化验证确实位于本题 EvidenceBundle。

### 9.1 Evidence budget

在 10 题开发集上只依据工程可用性确定单源 evidence 上限 `B`，建议起点为 4,000 tokens。冻结后所有 E1–E6 统一使用 `B`。

如果 bundle 超过 `B`：

- 保留完整 evidence item；
- 按 note 保存顺序添加；
- 下一个 item 放不下时跳过并记录 truncation；
- 不用 LLM 重新摘要压缩。

---

## 10. E7 双源融合

E7 复用：

- E2 的 raw EvidenceBundle；
- E6 的 curated EvidenceBundle。

不再次检索，不调用额外 LLM 做摘要。确定性融合步骤：

1. 验证所有 evidence IDs、locators 和 hashes；
2. 对完全相同的 `(source_kind, dia_ids, text_sha256)` 去重；
3. 若 raw 与 curated 指向同一 locator 但文字不同，两者都保留，因为差异本身可能揭示改写失真；
4. 显式标注 `[RAW]` 与 `[CURATED]`；
5. 各路内部保持原 note 顺序；
6. 两个队列 round-robin 交替加入；
7. 时间和来源元数据一起保留；
8. 交给同一个 Answerer。

主协议建议让 E7 总 evidence budget 为 `2B`，每路最多 `B`。这测量的是“多一个证据源能带来多少收益、付出多少额外上下文成本”的系统效果。必须承认 E7 的上下文更多，因此 E7−E6 不是纯粹等预算的因果估计。

如果主实验提前完成，可做一个**可选**的 `B` 总预算融合敏感性分析；本月不把它列为必做。

E7 部署成本定义：

```text
E2 的 raw retrieval 成本
+ E6 的 curated retrieval 成本
+ E7 自己的一次 Answerer 成本
```

不能把 E2/E6 各自已经生成最终答案的调用计入 E7 部署成本。

---

## 11. 一道题从开始到结束怎么跑

以任意正式问题 `q` 为例：

1. Runner 读取冻结的 `question_id`，但不把 gold 交给在线系统；
2. 验证目标 store snapshot hash；
3. 创建全新的、无历史消息的 retrieval episode；
4. R1 或 R2 搜索并输出 EvidenceBundle；
5. 验证 evidence 路径、locator、`dia_id` 和 token budget；
6. 统一 Answerer 读取 question + bundle，输出答案和 evidence citations；
7. 再次验证 store hash，证明查询没有写回；
8. 保存完整 RunRecord；
9. 离线程序才加载 gold answer/evidence；
10. 计算官方 F1、Evidence Recall、citation validity；
11. 匿名化 candidate，交给固定 Judge；
12. 所有条件结束后做 paired comparison 和错误归因。

每题每条件至少保存：

```text
dataset_hash, code_version, config_hash, prompt_hashes
conversation_id, question_id, category, condition
store_snapshot_hash, index_hash
question, gold_answer, gold_evidence_ids
retrieval_trace, evidence_bundle, retrieved_dia_ids
final_answer, citations
requested_model, served_models, response_ids
input/cached/output/reasoning_tokens
model_calls, search_calls, tool_calls, wall_time
status, retries, error, timestamps
```

---

## 12. 正式批跑、断点和异常规则

### 12.1 运行顺序

- 使用 seed 42 打乱 60 题顺序；
- E1–E6 按 question block 交错运行，条件顺序做确定性轮换，避免所有 E1 都在某一天、E6 都在另一天；
- 先得到 E1–E6 evidence 与答案；
- E2/E6 齐全后生成 E7；
- 初始并发 1，网关稳定后最多 2；不要为了模仿论文并发 8 而增加学校 API 失败；
- 每完成一个 question×condition 就原子写出结果并 flush；
- 重启时按唯一 key 跳过已成功记录。

### 12.2 API 异常

| 情况 | 处理 |
| --- | --- |
| 401 | 立即停止；检查 endpoint/key，不能重复轰炸 |
| 429、5xx、timeout | 相同配置指数退避，最多 3 次，记录全部失败 |
| requested/served model 改变 | 暂停整批，不能把不同后端混入同一结果表 |
| 无效 JSON | 允许一次仅修复格式的 repair；不得增加新证据 |
| 正常完成但答案错误 | 不得重试 |
| R1/R2 正常但没有证据 | 这是方法结果，不是系统失败 |
| store hash 变化 | 立即停止并废弃受影响查询 |
| 单条件系统失败率 >5% | 暂停正式运行并诊断 |

正式开始后如发现实质性代码或 prompt bug：

1. 停止当前 run；
2. 修改代码并生成新 config/version hash；
3. 明确标记旧 run 废弃；
4. 受影响条件从头重跑；
5. 不允许新旧版本拼在一张主表里。

### 12.3 每日运行核对单

- 今天新增多少成功/失败记录？
- 420 个矩阵单元还缺多少？
- served model 是否一致？
- 是否有异常高 token、hit-cap、空证据？
- store hash 是否始终不变？
- E2/E4 第一轮是否保持后端不变量？
- E7 是否只复用 E2/E6，不暗中重新检索？
- 失败是否是基础设施失败而非“答错”？
- 当前 API 配额和剩余时间是否足够？

---

## 13. 如何判分：不能只用 LLM-as-Judge

### 13.1 正确性指标

**A. 固定 LLM Correctness Judge（主语义指标）**

Judge 输入为 question、gold answer、匿名 candidate answer，输出固定 JSON：

```json
{
  "label": "correct|partial|incorrect",
  "binary_correct": 0,
  "short_reason": "...",
  "confidence": "high|medium|low"
}
```

主二元指标只把 `correct` 记为 1；`partial` 单独报告。Judge prompt 只在开发集校准，之后冻结。

**B. 官方 LoCoMo token/stem F1（确定性副指标）**

- Single-hop、Temporal、Open-domain：按官方规范计算 token/stem F1；
- Multi-hop：按官方对子答案拆分的逻辑计算；
- 保存官方 evaluator 的来源版本/hash；
- F1 与 Judge 不一致的案例进入人工抽查。

### 13.2 Attribution

程序先判断：

- citation ID 是否存在；
- 是否属于本题 bundle；
- citation 文本是否真实来自对应存储片段。

LLM Judge 再判断回答中的核心事实是否得到 citation 文字支持：fully / partially / unsupported。Correctness 与 Attribution 是两回事：答案偶然对但证据不支持，不能算高质量记忆回答。

### 13.3 Evidence retrieval

设：

- `G` = LoCoMo gold evidence `dia_id` 集；
- `R` = 最终送给 Answerer 的 evidence 所包含的 `dia_id` 集。

计算：

- `Evidence Recall = |G∩R| / |G|`；
- `Any-hit = I(G∩R ≠ ∅)`；
- `All-hit = I(G ⊆ R)`；
- 第一条 gold evidence 的排名/首次出现轮次；
- 最终 evidence tokens。

有两道 open-domain 问题没有完整 gold evidence 时，它们仍参加 correctness/F1，但不进入 evidence 指标分母。gold evidence 也可能不完备，因此不把传统 Evidence Precision 作为主要指标。

### 13.4 成本与效率

查询阶段：

- retrieval controller calls；
- search calls；
- Answerer calls；
- 各工具调用数；
- input、cached input、output、reasoning tokens；
- evidence tokens；
- 本地 BM25 时间；
- API latency 和总 wall time；
- hit-cap / early-stop 比例。

构建阶段：

- 模型调用和工具调用；
- input/output tokens；
- 构建 wall time；
- dirs/files/sections/KB；
- locator coverage；
- S3 相对原始聊天的字节/token 比率。

NUS API 免费不意味着计算成本为零。真实美元成本应写“未收费/不适用”，主文报告 token、调用和时间。若换算公开价格，必须标成假设价格。

摊销：

```text
amortized_compute(Q) = build_compute / Q + mean_query_compute
```

建议展示 Q = 1、10、60、154、1000。

---

## 14. 错误归因：写错、没找到，还是不会答

### 14.1 三个集合

- `G`：gold evidence IDs；
- `M`：整个存储中能够追溯到的 source IDs；
- `R`：真正送给 Answerer 的 source IDs。

自动候选：

| 观察 | 候选标签 |
| --- | --- |
| `G` 的关键信息不在 S3 | BUILD_OMISSION |
| locator 在 S3，但时间、否定、人物或旧新状态变了 | BUILD_DISTORTION |
| 忠实信息在存储中，但没有进入 R | RETRIEVAL_MISS |
| 多跳所需证据只到了一部分 | RETRIEVAL_PARTIAL |
| 充分、忠实证据已进入 R，答案仍错 | REASONING_FAILURE |
| 新旧状态都在 R，但选择了过时状态 | CONFLICT_RESOLUTION |
| gold 与 transcript 冲突或含糊 | GOLD_PROBLEM |
| API/解析/程序未完成 | SYSTEM_FAILURE |

locator 存在不能证明表达忠实。S3 错题必须把四样内容并排：

1. 原始 gold turn；
2. S3 中的转述；
3. 检索后真正送入的 evidence；
4. 最终答案。

### 14.2 Repair / Harm

E5→E6：

```text
Repair: E5 错、E6 对
Harm:   E5 对、E6 错
Repair rate = Repair / E5 错题数
Harm rate   = Harm / E5 对题数
Net repair  = Repair - Harm
```

E6→E7 同样计算。另记录：

- 两个单源都错、融合独自答对（真正的融合协同）；
- 只有 raw 对、融合错；
- 只有 curated 对、融合错；
- 两路证据互相冲突时 Answerer 如何选择。

### 14.3 批量分析与人工复核

先由 deterministic rules + 结构化诊断 LLM 产生候选标签，再人工核对：

- 所有 E5→E6 repair/harm；
- 所有 E6→E7 repair/harm；
- 所有融合独自恢复或融合造成的新错误；
- 所有 Judge `low confidence` 或诊断 `uncertain`；
- 随机抽查至少 10% 的“方法都对/都错”稳定案例。

如果师兄可参与，从中选约 30 个案例进行双人独立标注并计算 Cohen's κ；若只有一人，报告中明确为单人复核。

---

## 15. 统计分析计划

### 15.1 每个条件报告

- Judge correctness：数量、百分比、Wilson 95% CI；
- partial 数；
- 官方 F1；
- Attribution；
- Evidence Recall / Any-hit / All-hit；
- 平均值和中位数 token、calls、rounds、latency；
- 四类问题分别结果；
- hit-cap、empty evidence、system failure 数。

60 题是分层抽样，不按 conv-50 原始类别比例。报告三种汇总：

1. 每类别分数；
2. 四类别 unweighted macro average；
3. 使用可靠 154 题类别规模（Multi-hop 30、Temporal 32、Open-domain 7、Single-hop 85）计算的 post-stratified estimate。

固定 60 题的直接 micro average 可以报告，但要写“该固定样本上的分数”，不能冒充完整 conv-50 分数。

### 15.2 成对比较

- 二元正确率：exact McNemar test；
- F1、Evidence Recall、token 差：按类别分层 paired bootstrap 10,000 次；
- 报告百分点差、repair/harm 数、95% CI；
- 主要比较 E6 vs E5、E7 vs E6 使用 Holm 校正；
- 其他比较标为 secondary/exploratory；
- 类别内只有 7–27 题，类别显著性只作描述，不作强结论。

### 15.3 Judge 稳定性

主结果每个答案判断一次。另在结果前预先固定一个跨条件、跨类别的 60-answer 样本，各额外重复判断两次，报告：

- 二元一致率；
- Cohen's κ；
- label flip rate；
- 分数可能波动的题数范围。

所有关键 repair/harm 遇到 Judge 分歧时必须人工复核。

### 15.4 系统随机性（推荐但可降级）

预先从正式 60 题中选 12 道稳定性题：Multi-hop 3、Temporal 3、Open-domain 2、Single-hop 4。若时间和配额允许，仅对核心 E5/E6/E7 额外运行两次，比较：

- answer 一致率；
- evidence ID Jaccard；
- correctness 波动；
- tokens/rounds 波动。

这不是正式主结果的替代，而是说明一次运行有多稳定。资源不足时可取消，但要在限制中说明。

---

## 16. 测试、冻结与质量门

### Gate A：数据正确

- loader 数量断言全过；
- source map 双向可逆；
- dev/test IDs 已写死且无重叠；
- raw/data/split hashes 已保存。

### Gate B：存储正确

- S1 可无损反解析；
- S2 与 S1 正文 hash 完全相同；
- S3 schema、路径与 locator 校验通过；
- 三份 snapshot manifest 完成；
- 查询挂载只读。

### Gate C：检索正确

- R1 evidence-only 能产生可解析 note；
- BM25/RRF/邻居/时间/去重单元测试全过；
- E2/E4 第一轮结果不变量通过；
- S3 section parser 无重叠/遗漏异常；
- evidence 文本可回查。

### Gate D：端到端 pilot 正确

10 dev × 7 条件完成；

- 每条都有 trace、bundle、answer、citations、usage；
- schema failure 低于 5%；
- store 前后 hash 不变；
- E7 成本未重复计算；
- 只修工程 bug，不按分数挑 prompt。

### Gate E：冻结

冻结并 hash：

- 数据和 split；
- 三份 stores/indexes；
- management/retrieval/answer/judge prompts；
- models、temperature、limits；
- BM25/RRF/evidence budget；
- 代码版本和依赖版本；
- retry/timeout/concurrency；
- 指标与主要比较。

### Gate F：正式矩阵完整

- 420 个单元均成功或有明确系统失败状态；
- 只对基础设施失败按固定规则重试；
- 正式结果没有跨 config hash 混合；
- 每条可追溯到 source。

### Gate G：分析可重算

删除生成的 CSV/图表后，能从原始 JSONL traces 一条命令重建所有指标、表和图。

---

## 17. 四周逐日地图

### 第一周：协议、数据、三种存储（D1–D7）

| 天 | 主要工作 | 当日必须交付 |
| --- | --- | --- |
| D1 | 固定 RQ、七条件、主要比较、停止规则、目录结构 | 本文 v1.0，不能再随结果改研究问题 |
| D2 | 下载/pin LoCoMo；实现 loader 和 source map | raw SHA、counts report、processed JSONL |
| D3 | 固定 10 dev、60 test、12 stability IDs | split manifests + SHA |
| D4 | 实现/测试 S1 builder | 30 文件 + 无损反解析测试 |
| D5 | 实现 S2 folder-only builder | S1/S2 hash equality report |
| D6 | 用 Alice/小样本完成 S3 builder 最后工程检查；冻结 builder prompt | builder tests 与 prompt hash |
| D7 | 正式构建一次 conv-50 S3；生成三份 store manifests | 冻结 stores、构建 trace、结构统计 |

第一周完成标准：问题和答案从未进入构建；S1/S2 内容严格相同；S3 后续不再因 dev 分数重建。

### 第二周：R1、R2、Answerer、Fusion、Evaluator（D8–D14）

| 天 | 工作 | 当日必须交付 |
| --- | --- | --- |
| D8 | R1 evidence-only、take_note、finish_search | E1/E3/E5 单题 evidence package |
| D9 | BM25 preprocessing/scoring + toy tests | 确定性 BM25 index |
| D10 | session aggregate + RRF + ±2 + 时间/去重 | R2 raw backend tests |
| D11 | 多轮 controller；S3 section/topic adapter | E2/E4/E6 单题 traces |
| D12 | EvidenceBundle validator + E7 deterministic fusion | E7 bundle tests |
| D13 | 统一 Answerer、RunRecord、断点、重试、usage/latency | 一题七条件端到端 |
| D14 | 官方 F1、evidence metrics、Judge、Attribution、cost | evaluator 单元/集成测试 |

### 第三周：Pilot、冻结、正式运行（D15–D21）

| 天 | 工作 | 当日必须交付 |
| --- | --- | --- |
| D15 | 10 dev × 7 全跑；人工看 trace，不只看分数 | pilot report、bug list |
| D16 | 只修工程问题；重跑 pilot；冻结 v1.0 | frozen config + prompt/code/store hashes |
| D17 | 正式问题 1–12，先跑 E1–E6；允许程序在非人工工作时间继续跑 | 约 72 个单源结果目标 |
| D18 | 正式问题 13–24 | 约 144 个累计单源结果目标 |
| D19 | 正式问题 25–36 | 约 216 个累计单源结果目标 |
| D20 | 正式问题 37–48 | 约 288 个累计单源结果目标 |
| D21 | 正式问题 49–60；生成 E7；只补基础设施失败 | 完整 420 项矩阵与 failure report |

每个“12 题批次”包含六个检索条件。支持断点的 runner 可在非人工操作期间继续运行；若网关较慢，则减小当日 batch，而不是通过提高并发破坏稳定性。

是否扩展到 154 在主矩阵提前完成时才讨论。go 条件：

- 核心 420 项已完整；
- 系统失败率 <5%；
- 指标与报告脚本已可用；
- 预计扩展仍能给错误分析和写作留下至少 7 天；
- API 配额/速度足够。

否则停止扩展，保护主实验完整性。按照当前工作量，154 题应视为 stretch goal，而不是默认承诺。

### 第四周：核对、机制分析、写报告（D22–D28）

| 天 | 工作 | 当日必须交付 |
| --- | --- | --- |
| D22 | 生成效果/类别/evidence/citation 主表 | 结果表 v1 |
| D23 | McNemar、bootstrap、repair/harm | 配对统计表 |
| D24 | build/query/amortized cost、Pareto | 成本表和图 |
| D25 | 自动生成错误候选，集中 E5/E6/E7 | diagnosis workbook/JSONL |
| D26 | 人工复核翻转、uncertain、10% 稳定案例 | final error labels |
| D27 | 写 Methods、Results、3 个完整案例链 | 报告主体初稿 |
| D28 | 写 Limitations、复现说明；从头重算表图 | 可交付草稿 + reproducibility checklist |

D29–D30 作为纯缓冲：只补已定义任务，不增加新方法。

---

## 18. 目标目录与代码边界

建议最终结构：

```text
repository-root/
  data/
    raw/
    processed/
    manifests/
  splits/
  configs/
  experiments/locomo-conv50-v1/
    stores/s1-flat/
    stores/s2-foldered/
    stores/s3-curated/
    indexes/
    runs/e1/ ... runs/e7/
    evaluation/
    analysis/
    reports/
  fs_memory_lab/
    locomo.py
    evidence.py
    stores.py
    retrieval_center.py
    retrieval_refind.py
    answering.py
    fusion.py
    benchmark.py
    evaluation.py
    diagnostics.py
```

目标 CLI（目前尚未实现，不能现在直接运行）：

```bash
python3 -m fs_memory_lab.benchmark prepare --dataset data/raw/locomo10.json --conversation conv-50
python3 -m fs_memory_lab.benchmark build-stores --config configs/draft.yaml
python3 -m fs_memory_lab.benchmark pilot --split splits/dev10.json --conditions all
python3 -m fs_memory_lab.benchmark freeze --config configs/draft.yaml
python3 -m fs_memory_lab.benchmark run --split splits/test60.json --conditions e1,e2,e3,e4,e5,e6
python3 -m fs_memory_lab.benchmark fuse --split splits/test60.json --condition e7
python3 -m fs_memory_lab.benchmark evaluate --run experiments/locomo-conv50-v1
python3 -m fs_memory_lab.benchmark report --run experiments/locomo-conv50-v1
```

---

## 19. 最终报告至少需要哪些表和图

1. 七条件总体效果表；
2. 四类别效果与 post-stratified estimate；
3. Evidence Recall / Any-hit / All-hit；
4. 查询 tokens、calls、rounds、latency；
5. 三种 store 的构建成本和结构；
6. E5→E6、E6→E7 repair/harm 配对表；
7. 错误类型分布；
8. correctness–token 和 correctness–time Pareto 图；
9. Judge 重复判断稳定性；
10. 至少三个完整 trace 案例：
    - S3 写入遗漏或扭曲；
    - S3 中证据存在但 R1 漏掉、R2 找到；
    - S3 不可靠但 raw 第二来源恢复；
11. 一张“论文已有 vs 本研究新做”的定位表；
12. reproducibility manifest 表。

---

## 20. 风险、触发信号和应对

| 风险 | 早期信号 | 应对 |
| --- | --- | --- |
| NUS 模型/网关变化 | served model 改变、function call 格式变 | 暂停；不混跑；固定新版本后重启受影响批次 |
| S3 构建太慢/失败 | 单 chunk 多次 timeout/hit-cap | 串行、断点、同 snapshot 重试；不降低 prompt 后混用 |
| S2 内容被改 | body hash 不同 | Gate B 失败，重新构建；绝不继续 |
| R2 scope 失控 | 空结果、重复 group、时间边界错 | 先修 toy/integration tests，再调 API |
| 420 项耗时过高 | D17 日吞吐不足 | 保住 60×7；取消稳定性复跑和 154 扩展 |
| Judge 不稳定 | 重判 flip 多、JSON 错 | 固定更稳定 Judge；增加人工复核；保留 F1 |
| gold evidence 不完整 | 答案明显对但 Evidence Recall=0 | evidence 指标作为辅助，人工核对，不强求 precision |
| 双源只是“更多 token” | E7 budget 为 2B | 如实作系统比较；等预算版仅作为可选消融 |
| 结论不显著 | CI 跨 0 | 报告 repair/harm 与错误机制；不追加方法追分 |

---

## 21. 最终可以说什么，不能说什么

可以说：

- “在固定的 LoCoMo conv-50 子集、固定 S3 快照与 NUS 服务模型下，观察到……”；
- “R2 修复了多少 R1 错误，同时损害了多少原本正确答案”；
- “双源方案以多少额外 tokens/latency 恢复了多少答案”；
- “错误主要来自写入、检索还是推理”；
- “结果支持某个经验性机制解释”。

不能说：

- “完全复现了两篇论文”；
- “证明方法普遍优于所有记忆系统”；
- “60 题结果代表整个 LoCoMo10”；
- “E7 的所有收益都由双源本身造成”，因为它有更多 evidence budget；
- “有 locator 就说明记忆忠实”；
- “一两道题的差异就是稳定提升”。

---

## 22. 最终 Definition of Done

在提交前逐项打勾：

- [ ] `locomo10.json` 来源、版本、SHA 可追溯；
- [ ] loader counts 与 source map 全通过；
- [ ] dev/test/stability IDs 预先冻结；
- [ ] S1 无损、S2 body-hash 与 S1 相同；
- [ ] S3 仅正式构建一次并冻结；
- [ ] R1/R2 都输出统一 EvidenceBundle；
- [ ] E2/E4 第一轮 BM25 不变量通过；
- [ ] E7 只复用 E2/E6 evidence；
- [ ] Answerer/Judge/prompts/config 均有 hash；
- [ ] 420 个正式单元完整或有明确 failure 状态；
- [ ] 每个 answer→evidence→store→dia_id 可追溯；
- [ ] store 查询前后 hash 不变；
- [ ] F1、Judge、Attribution、Evidence Recall 与成本表齐全；
- [ ] E5→E6、E6→E7 repair/harm 完成；
- [ ] 关键翻转和 uncertain 案例人工复核；
- [ ] 表图可从 raw results 一键重建；
- [ ] 方法改造和研究限制写清楚；
- [ ] 没有 API key 进入代码、日志、截图或报告。

只要这份清单完成，即使 E6/E7 没有成为最高分，研究仍然形成一篇有价值的 empirical finding 报告：它不仅告诉读者“哪个条件分高”，还解释“为什么错、增强检索修复了什么、双源解决了什么，以及代价是多少”。
