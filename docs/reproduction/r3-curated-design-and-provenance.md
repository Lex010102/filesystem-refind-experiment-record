# R3 / R2-Curated 详细设计与溯源记录

状态：**设计协议 v1 已实现为独立离线 harness；尚未调用 R3 API；尚未产生 E6 实验结果**

记录日期：2026-10-09（Asia/Shanghai）

正式实验条件：E6 = S3 Agent-curated filesystem + R2-Curated ReFind-inspired retrieval

本地简称：R3

报告推荐名称：R2-Curated 或 ReFind-inspired retrieval over agent-curated filesystem

## 1. 文档目的

本文把此前散落在实验地图、S3 进度记录和 R2-Raw 讨论中的 R3 决策集中成一份可实现、可测试、可追溯的设计合同。它回答：

1. R3 与 R2-Raw 哪些部分完全相同；
2. S3 的真实 Markdown 结构怎样转换成检索 unit 和 group；
3. 哪些规则来自 ReFind，哪些是本项目为 curated filesystem 新增的适配；
4. 如何保证 E5 与 E6 的比较只改变检索方式；
5. 代码实现前必须冻结什么，代码完成后必须通过什么测试；
6. 哪些风险需要在报告中主动披露。

本文不是实验结果，也不表示 R3 已经运行。后续实现若改变 unit、group、BM25 文本、时间语义、上下文窗口、预算或停止规则，必须先更新本文件和机器可读 protocol hash，不能在查看 main-40 成绩后再调整。

## 2. 一句话理解

- R2-Raw 是在原始聊天中找证据：`exchange -> session`。
- R3 是在 LLM 整理后的 S3 记忆中找证据：`fact bullet -> H2 topic`。

两者复用相同的 ReFind 核心：tokenizer、BM25、group 聚合、RRF、Top-5、多轮关键词改写、时间过滤、seen-group 去重和 note-taking。R3 只替换输入 adapter、层级含义和相应 Prompt 说明。

R3 不能写成 ReFind 论文的直接复现。ReFind 原方法面向原始聊天，S3 已经经过 Management Agent 的压缩、改写、合并和重组，因此正式措辞必须是 **ReFind-inspired adaptation over agent-curated memory**。

## 3. 研究位置与问题

### 3.1 七条件中的位置

| 条件 | 存储 | 检索 | 作用 |
| --- | --- | --- | --- |
| E2 | S1 平铺原始 session | R2-Raw | 原始聊天增强检索 |
| E4 | S2 文件夹化原始 session | R2-Raw | 路径线索对多轮检索的影响 |
| E5 | S3 LLM 整理记忆 | R1 filesystem search | Filesystem 主基线 |
| E6 | S3 LLM 整理记忆 | R3 / R2-Curated | 本项目的跨论文组合 |

### 3.2 核心研究问题

E5 与 E6 使用同一份 S3，只改变检索器：

> 面对同一份 LLM 自主管理的文件系统记忆，ReFind-inspired 排名与多轮检索，能否比原生 code-agent 文件导航更稳定地找到正确证据；如果可以，改善来自哪里，代价又是多少？

### 3.3 不预设的结论

不能预先声称 R3 一定优于 R1，也不能预先声称 curated memory 一定更短。本项目正式 S3 为 304,640 bytes，而每个 S1/S2 raw store 为 114,456 bytes。S3 的价值可能来自主题组织和事实整合，而不是字节压缩。R3 也可能因为超长事实、group-size bias 或整理污染而更贵或更差。

## 4. 固定输入与来源身份

### 4.1 正式 S3 产物

| 项目 | 固定值 |
| --- | --- |
| Artifact ID | `locomo/conv-50/s3-curated/v1` |
| Store | `experiments/locomo-conv50-v1/stores/s3-curated/` |
| Files | `calvin.md`, `dave.md` |
| Files / bytes / lines | 2 / 304,640 / 472 |
| H1 / H2 | 2 / 35 |
| S3 manifest | `experiments/locomo-conv50-v1/manifests/s3-curated.json` |
| Commit marker | `experiments/locomo-conv50-v1/manifests/s3-curated.COMMITTED` |
| Manifest SHA-256 | `70fb5ad56ff11bb849ce60b193cd6db29be601e613ca3afb76aac336e3b36e00` |
| S3 runner tree SHA-256 | `60cb8dac74bfb60de500d1721f385c13f5d0b5819420600e24ba40ba10f27acd` |
| R1/shared snapshot tree SHA-256 | `983238fddc77a88ef4ae3d06b50bcfd25a429f497e89c6af4d9477cefca9cad2` |
| Source conversation | LoCoMo `conv-50` |
| Source turns available | 568 |
| S3 unique locators referenced | 555 |

两个 tree hashes 来自两个已经冻结但 canonicalization 不同的验证器。R3 必须使用共享 `VerifiedStoreManifest` / `StoreSnapshotRef` 所采用的 `983238fd...cad2` 作为在线检索 snapshot 身份，同时保留 S3 build manifest 中的 `60cb8dac...acd` 作为构建溯源；不能把二者混写成同一种 hash。

### 4.2 正式 parser 的只读盘点结果

对当前两个 Markdown 文件按本协议预扫描得到：

| 项目 | 数值 |
| --- | ---: |
| H2 topic groups | 35 |
| Markdown fact list items | 390 |
| 带有效 locator 的 fact items | 390 |
| 不带 locator 的 fact items | 0 |
| Nested fact items | 3 |
| 正文 locator mentions | 1,459 |
| 正文 unique locators | 555 |
| 未被 S3 正文引用的 source locators | 13 |

S3 build manifest 的总 locator mentions 为 1,465；多出的 6 次出现在两个 YAML frontmatter descriptions 中。R3 正式 index 排除 frontmatter，因此以正文 fact 的 1,459 次为准。555 个 unique locators 与 manifest 一致。

### 4.3 事实长度盘点

| 指标 | 字符数 |
| --- | ---: |
| Fact 最短 | 21 |
| Fact 中位数 | 346 |
| Fact P90 | 1,161 |
| Fact P95 | 2,262 |
| Fact P99 | 4,378 |
| Fact 最长 | 7,740 |
| 390 facts 合计 | 236,427 |

同 H2 内中心 fact 的 `±2` 窗口长度：中位数 1,671、P95 11,599、最大 23,480 字符。这个事实决定 R3 不能把“整理后的 memory”直接等同于“短 memory”；必须完整记录 observation、EvidenceBundle 和 Answerer 输入成本。

## 5. S3 Markdown 的正式解析规则

### 5.1 文件级 gate

每次建 R3 index 前必须：

1. 通过现有 S3 manifest、COMMITTED marker 和共享 store loader 验证正式发布路径；
2. 验证文件清单、逐文件 bytes、SHA-256、locator index 与 snapshot tree hash；
3. 拒绝 staging、复制品、软链接、额外文件或修改后的 store；
4. 只读打开文件，不得让 R3 修改 S3。

### 5.2 排除 YAML frontmatter

每个文件开头 `--- ... ---` 内的 `name` 和 `description` 是文件级搜索面，不是事实证据。正式 R3：

- 完全排除 frontmatter description，不建 unit、不参与 BM25、不作为 evidence；
- 只读取 `name` 作为人物名称，并与正文 H1 / 文件名交叉验证；
- 不因为 frontmatter 中出现 locator 就把它计入正文事实覆盖。

原因是当前 description 极长、重复大量正文内容；把它复制到每个 unit 会造成严重重复、长度偏置和证据双计数。

### 5.3 H1 与 H2

- H1 表示人物实体，当前分别为 Calvin 和 Dave；它不是 group。
- H2 表示 topic group，是 R3 的正式上层分组。
- Group ID 使用结构身份，而不是仅使用标题文字：`<relative_path>::h2-<ordinal>`。
- 同时记录原始 H2 heading 供检索和 provenance 展示。
- 当前正式 snapshot 中每条 fact 都位于 H2 下；未来若出现 H2 之外的 bullet，preflight 必须失败，不能静默退回整文件 group。

### 5.4 Fact unit

一个 fact unit 是 H2 下的一条完整 Markdown list item：

- 起始匹配 `^\s*[-*+]\s+`，允许 nested list item；
- 保留 list item 的完整原文字节、缩进、行号和可能的 continuation lines；
- list item 必须含至少一个语法正确且能在 canonical source map 中解析的 `[SxTy]`；
- nested item 是独立 unit，但 group 仍是最近 H2；
- 不能把一个超长 fact 按字符切成多个 unit；
- 不能把同一 fact 中的多个 locator 拆成多份改写文本；
- 无 locator 的 list item不进入 index，并作为 build-quality failure 记录。当前正式 snapshot 的该数量必须为 0。

建议稳定 Unit ID：`fact-f<file_ordinal>-h<h2_ordinal>-u<unit_ordinal>`。Canonical order 为文件名排序、文件内 H2 顺序、H2 内 list item 文档顺序。该顺序也是同分 tie-break 和 context expansion 的唯一顺序。

### 5.5 Cross-reference

事实中已有的 `/memories/...` cross-reference 保留在原文和 BM25 文本中，但检索器不会自动跟随引用、复制另一个 section 或把 cross-reference 当成额外 evidence。需要另一主题的证据时，由 controller 发起下一次搜索。

## 6. R3 unit schema

每个 unit 至少保存：

```text
unit_id
canonical_index
relative_path
file_ordinal
entity_name
h1_heading
h2_heading
h2_ordinal
group_id
unit_ordinal_in_group
line_start / line_end
exact_markdown_text
search_text
source_locators[]
dia_ids[]
source_session_ids[]
source_dates[]
min_source_date / max_source_date
content_sha256
```

`exact_markdown_text` 用于 observation 与最终 host re-read。`search_text` 只用于 BM25，两者不能混用。

## 7. BM25 文本与 tokenizer

### 7.1 Search text

每个 fact 的正式 BM25 文本为：

```text
<entity_name>
<h2_heading>
<fact text with inline [SxTy] tokens removed>
```

规则：

- 人物名进入文本，使询问 Calvin/Dave 的问题可以区分人物；
- H2 heading 进入文本，使 S3 的主题整理真正成为 R3 的检索信号；
- fact 正文完整保留，包括日期、图片 caption 文字和已有 cross-reference；
- locator token 和 `dia_id` 不参与 BM25；
- YAML description、文件系统绝对路径、manifest、trace 和 gold data 不参与 BM25；
- relative path 只显示在 provenance，不直接打分。

人物名和 H2 被重复注入各 unit 是项目定义的 taxonomy-aware adaptation，不是 ReFind 原文规则，报告必须披露。

### 7.2 Tokenizer 与 BM25 参数

R3 复用已经冻结的 R2 tokenizer 和参数：

- ReFind 官方 competition tokenizer 固定 commit：`a80175ca0eeb52a938d7cab7a602bc780de8a577`；
- tokenizer source SHA-256：`111744fff0a766bb8248319f9d38294c9954d9d47b12c7be4c1dd8592609b9b6`；
- lowercase、冻结 stopwords、compact Porter-style stemmer；
- BM25 `k1=1.2`，`b=0.75`；
- IDF 使用完整 390-unit corpus 的冻结全局统计；
- query 中关键词按输入顺序保存，但 BM25 使用 tokenizer 输出。

## 8. 两级排名与 RRF

### 8.1 Unit rank

对通过时间和 seen-group filter 的 fact units 计算 BM25，零分 unit 不进入候选。按：

```text
(-bm25_score, canonical_index)
```

确定 unit rank；rank 从 1 开始。

### 8.2 Group rank

对每个 H2 group，把本轮仍有资格、且 BM25 大于零的 unit 分数求和：

```text
group_score(g) = sum(BM25(unit))
```

按 `(-group_score, group_first_canonical_index)` 确定 group rank；rank 从 1 开始。

Group size 当前差异很大：最小 1 条，最大为 `dave.md::Relationships` 的 53 条；`calvin.md::Music` 有 52 条，`calvin.md::Relationships` 有 50 条。求和可能偏向大 topic，但为了保持 ReFind 核心不变，主实验不改成 mean/max normalization。Group-size bias 应作为误差分析项；若以后做 normalization，只能作为另行命名的 ablation，不能替换 E6 主条件。

### 8.3 RRF

保持与 R2 相同：

```text
RRF(unit) = 1 / (60 + unit_rank) + 1 / (60 + group_rank)
```

按 `(-rrf_score, canonical_index)` 排序，固定返回 Top-5 center facts。不能根据问题难度改变 Top-K。

## 9. 时间过滤

原始 ReFind turn 只有一个 timestamp，而一个 S3 fact 可能整合多个 sessions，因此 R3 必须明确自己的 project-defined 时间语义。

正式建议：

1. 由 unit 的全部 locators 查 canonical source map，得到 ordered unique `source_dates`；
2. `date_from` / `date_to` 继续使用 inclusive `YYYY/MM/DD`；
3. 一个 unit 在其日期集合中至少有一个日期落入查询区间时保留，即 set-overlap 语义；
4. 时间过滤在 BM25 打分和两级排名之前执行；
5. observation 显示完整 source-date set，并标记本轮 matched dates；
6. 不使用文件 mtime、H2 标题中的日期或总结文字猜日期；
7. 不按日期拆开 fact，因为那会生成并不存在于 S3 的改写证据。

Set-overlap 可能让一个整合事实同时携带区间外内容，这是 curated unit 不可避免的边界，必须在报告中说明。实现前此规则进入 machine-readable protocol；若团队改选 all-dates-in-range 语义，也必须在任何 API 运行前修改并重新冻结，不能根据结果选择。

## 10. Top-5 上下文扩展

每个 center fact 返回：

- 同 group 内前 2 个 fact units；
- center fact；
- 同 group 内后 2 个 fact units；
- 到 H2 边界停止，绝不跨 H2 或跨文件；
- nested fact 依文档顺序参与前后窗口。

Observation 阶段保持五个 Top-5 hits 各自独立编号，即使窗口相互重叠也不提前合并，以保证 `take_note(indices)` 的编号语义稳定。每个 result block 显示：

```text
result index
relative path
H1 entity
H2 topic
center unit ID
center line range
source dates / matched dates
BM25 unit score and rank
group score and rank
RRF score
exact ±2 fact context
locators and dia_ids
```

进入 EvidenceBundle 时才传递合并同一路径内重叠或紧邻的已选择 ranges，使同一 fact 只交付一次、只计费一次。不能在 observation 中合并后重新编号。

## 11. Seen-group 去重

一次搜索返回 Top-5 后，把出现过的 H2 group IDs 加入 `seen_groups`。后续搜索在打分前排除这些 groups。

- 排除范围是 H2 topic，不是整个人物文件；
- 命中 Calvin 的一个 topic 不能导致 Calvin 其他 topics 全部消失；
- 同一 group 中多个 Top-5 hits 只记一个 seen group；
- seen state 只在当前问题 episode 内有效；
- 新问题必须从空 seen set 开始。

这对应 ReFind 的 seen-session 去重，但 group 含义已经由 session 改为 H2 topic，因此属于 ReFind-inspired adapter。

## 12. Retrieval Agent

### 12.1 Evidence-only 边界

R3 只收集证据，不直接回答。统一 Answerer 后续接收 EvidenceBundle 并生成答案，使 E1-E6 的回答模型和输入合同一致。

### 12.2 动作

为尽量减少 R2/R3 controller 差异，R3 复用 R2 的三动作 wire contract：

1. `search_chatrecord`
2. `take_note`
3. `finish_search`

`search_chatrecord` 名称属于历史兼容；在 R3 Prompt 中必须明确其 backend 是 curated memory facts，而不是 raw chat。参数 schema、Top-5、日期格式和错误处理保持 R2 一致。

### 12.3 四动作上限

每个 provider completion 最多产生一个文本 ReAct action：

```text
Thought: ...
Action: ...
Action Input: {...}
```

每题最多 4 个 planner actions。`search_chatrecord`、`take_note` 和 `finish_search` 每次都消耗一个 action，因此不是“最多四次 BM25 搜索”。达到 cap 时：

- 只使用已经明确保存的 notes；
- 不自动保存最后一次 hits；
- 不退回 direct BM25；
- 没有 notes 时仍生成可审计的 capped bundle，而不是让 host 偷选证据。

### 12.4 Prompt 来源

R3 Prompt 应从已冻结的 R2 published Retrieval Prompt 和 temporal addendum派生，并对以下内容做受控 redline：

- `turn` 改为 curated fact；
- `session` 改为 H2 topic group；
- observation 解释增加 path、heading、source-date set 和 locator；
- 明确 frontmatter 不可引用；
- 明确 controller 不得回答问题；
- 三动作格式和四动作上限保持不变。

该 Prompt 必须标为 `paper-text-plus-project-curated-adaptation`，不能标成 ReFind 作者原 Prompt。实现阶段要同时保存 normalized source、redline、derived prompt 和 SHA-256 manifest。

## 13. EvidenceBundle 与真实性

### 13.1 模型只能选择，不能提交证据文字

`take_note` 只允许选择最近一次 observation 的 result IDs。模型不能传入自写 evidence、locator、日期、speaker 或答案。

Host 在构造 bundle 时重新：

1. 从冻结 S3 snapshot 打开真实文件；
2. 验证 path、H2、line range、unit ID 和内容 hash；
3. 读取完整 fact blocks；
4. 解析全部 locators；
5. 通过 canonical source map补充 `dia_id`、session date 和 source record；
6. 合并重叠窗口；
7. 生成共享 EvidenceItem。

因此 EvidenceBundle 中的文字来源是 host 重读的 S3，而不是模型重述。

### 13.2 Evidence budget

E5 与 E6 必须使用同一单源 evidence budget、同一计量单位和同一统一 Answerer：

- 预算按完整合并后的 evidence item计量；
- 超出预算时整项跳过，不截断事实；
- `truncated=false`；
- 预算数值先在 dev-6 工程检查后冻结，不能看 main-40 分数再改；
- 不为 E6 单独设置更宽或更窄的正常证据预算。

R3 保留 R2 的 `max_observation_characters=250000` 防失控熔断。它不是正常检索预算；触发时应产生 failure artifact，不能静默截断 observation。当前单窗口最大 23,480 字符，但多个 Top-5 blocks 和多轮消息仍需要真实记录成本。

### 13.3 成功、封顶和失败产物

复用 R2 的原子 artifact 结构：

```text
trace.jsonl
bundle.json OR failure.json
episode.json
COMPLETED OR FAILED
```

Trace 必须记录 query、时间范围、seen groups、候选数、Top-5 IDs、scores、notes、停止原因、requested/served model、usage、API style 和 runtime hashes。API key 永不进入任何产物。

## 14. 与 R2-Raw 的异同

| 项目 | R2-Raw | R3 / R2-Curated |
| --- | --- | --- |
| 条件 | E2、E4 | E6 |
| Store | S1/S2 raw sessions | S3 curated Markdown |
| Unit | exchange | locator-bearing fact list item |
| 当前 unit 数 | 292 | 390 |
| Group | natural session | relative file + H2 topic |
| 当前 group 数 | 30 | 35 |
| BM25 text | exchange raw text | entity + H2 + fact text |
| Timestamp | one session date | locator-derived date set |
| Context | same session ±2 exchanges | same H2 ±2 facts |
| Seen dedup | session | H2 topic |
| Top-K / RRF | 5 / k=60 | 5 / k=60 |
| Controller | 三动作，最多四 actions | 相同三动作与 cap |
| Evidence | raw source-turn ranges | curated fact ranges，回链 source records |
| 主要风险 | 噪声和长对话 | 写入遗漏、污染、超长整合事实、group-size bias |
| 方法归属 | ReFind-style raw retrieval | 本项目 ReFind-inspired adaptation |

## 15. 与 E5/R1 的公平比较

E5 与 E6 必须固定相同：

- S3 snapshot；
- dev-6 / main-40 questions；
- online question whitelist；
- requested model alias、served-model记录和 API style；
- evidence budget；
- EvidenceBundle schema；
- Answerer Prompt、模型和输出上限；
- gold 隔离；
- 最终评分脚本。

唯一主要差异：

- E5：LLM 用 `view/grep/toc/section_read` 在文件系统中自行导航；
- E6：LLM 用 ReFind-inspired query controller 驱动 BM25 + H2 group RRF。

两者轮数不能直接比较成同一种单位。E5 是最多 40 个 filesystem-agent provider rounds；E6 是最多 4 个 ReFind planner actions。报告应分别记录 provider calls、tool/actions、prompt/completion tokens、evidence characters 和 latency，而不是只写“轮数”。

## 16. 评测与错误分析

### 16.1 最终回答指标

沿用 main-40 固定问题和 gold answer，不自造新问题。最终 Answerer 指标与其他条件完全一致，至少保存：

- 自动答案分数；
- 按 LoCoMo category 1-4 分层结果；
- caption-evidence 与纯文本 evidence 分层结果；
- 每题答案、引用、停止状态与成本。

### 16.2 检索指标

在 Answerer 前单独计算：

- gold source locator recall；
- 至少命中一个 gold locator 的 Hit@Evidence；
- evidence locator precision；
- Top-5 center hit 与扩展窗口分别贡献了多少 gold；
- note selection 是否丢掉了已经出现在 observation 的 gold；
- S3 中不存在的 gold locator比例；
- retrieved evidence characters、source turns 和 topics 数量。

Gold 只用于离线评分，绝不能进入 Agent Prompt、BM25 query、index 或停止判断。

### 16.3 成本指标

至少记录：

- index unit/group 数与字符数；
- search count、note count、finish count；
- provider calls / attempts；
- prompt、completion、total tokens；
- observation characters；
- EvidenceBundle characters；
- Answerer tokens；
- wall-clock latency；
- S3 build cost单独报告，不能混入单题 retrieval cost，也不能完全忽略。

### 16.4 错误归因

R3 答错时依次判断：

1. **Write loss**：gold source locator 根本不在 S3 的 555 个 locators 中；
2. **Write corruption**：locator存在，但 S3 事实改错、混合或产生冲突；
3. **Index/adapter error**：正确事实存在，却没有形成合法 unit/group/date；
4. **Backend retrieval error**：正确 unit 没进入 Top-5 observation；
5. **Controller error**：第一次没找到后，关键词/时间/seen-group 策略不当；
6. **Selection error**：正确证据已显示，但没有 `take_note`；
7. **Budget loss**：正确 note 因统一预算被整项跳过；
8. **Answerer error**：正确证据已进入 bundle，但答案仍错误。

这套分解是本项目的重要 empirical finding来源；不能只报告总分。

## 17. 来源分类

| 设计项 | 来源分类 |
| --- | --- |
| S3 由 Management Agent 管理 Markdown memory | Filesystem 论文方法 + 本地受控复现 |
| BM25 `k1=1.2,b=0.75` | ReFind 论文 |
| 官方 tokenizer 实现 | ReFind 作者 competition repository，固定 commit |
| unit/group 两级打分与 RRF `k=60` | ReFind 论文/作者实现 |
| Top-5、±2、时间过滤、seen-group、多轮 controller | ReFind 论文 |
| fact bullet 作为 unit | 本项目 curated adapter |
| file + H2 作为 group | 本项目 curated adapter |
| entity + H2 + fact 作为 BM25 text | 本项目 taxonomy-aware adaptation |
| multi-date set-overlap | 本项目时间适配 |
| nested list parsing与稳定 ID | 本项目工程补全 |
| locator/dia_id/source-map 回链 | 本项目评测与审计补全 |
| overlap merge、共享预算、EvidenceBundle | 本项目统一实验协议 |
| NUS `coding` / `portable` | 本地模型与网关替代 |

## 18. 推荐代码结构

在不修改已冻结 R2 行为的前提下新增：

```text
fs_memory_lab/
├── r3_protocol.py       # R3 参数、输入 identities、来源分类、hash
├── r3_inputs.py         # S3 gate、Markdown parser、390 facts / 35 groups
├── r3_prompts.py        # R2 source prompt + curated redline + hashes
├── r3_index.py          # fact/H2 adapter；复用相同 BM25/RRF 公式
├── r3_agent.py          # 三动作 evidence-only controller
├── r3_artifacts.py      # host re-read、S3 evidence、failure/verifier
├── r3_runner.py         # E6 单题与批量入口
└── r3_cli.py            # config、preflight、run-one、run-batch、verify
```

长期可以抽取共享 `ReFindCore`，但不应在没有等价性测试时重构已经冻结的 R2。安全顺序是：

1. 先用 R3 独立 adapter复现相同数学公式；
2. 用 synthetic corpus证明 R2/R3 core 公式一致；
3. 再决定是否抽取公共模块；
4. 任何重构后，R2 的 33 项专项测试和所有固定 hashes 都必须继续通过。

## 19. 实现顺序

1. 冻结本文和机器可读 R3 protocol manifest；
2. 实现只读 S3 parser 与输入 preflight；
3. 固定 390 units、35 groups、locator/date mappings 和 corpus hash；
4. 实现 fact BM25、H2 aggregation、RRF、Top-5、±2 和 seen-group；
5. 冻结 R3 derived Prompt 与三动作 contract；
6. 接入 EvidenceBundle、预算、trace、failure artifact 和 verifier；
7. 使用 deterministic fake provider完成 E6 离线端到端测试；
8. 用 dev-6 一题做真实 API smoke；
9. 用 dev-6 检查格式、成本和 evidence completeness；
10. 在看 main-40 结果之前冻结正式 evidence budget；
11. 才运行 E6 main-40。

## 20. 必须通过的自动验收

### 20.1 输入与 parser

- 正式 S3 snapshot / manifest / COMMITTED 全部通过；
- 精确 2 files、304,640 bytes、472 lines；
- 精确 35 H2 groups、390 fact units；
- 精确 3 nested units；
- 390/390 units 含 locator；
- 精确 1,459 body locator mentions、555 unique locators；
- 13 个 source locators缺失只被报告，不伪造补齐；
- frontmatter 中 6 次 locator mentions 全部不进入 index；
- 每个 locator 都能解析到 canonical source record 和 `dia_id`；
- 不允许 unit 跨 H2。

### 20.2 检索数学

- tokenizer source hash固定；
- BM25 用独立公式复算；
- group sum、1-based ranks 和 RRF `k=60` 独立复算；
- 时间与 seen-group 在打分前过滤；
- 同分按 canonical index；
- Top-K 必须等于 5；
- context 必须是同 H2 ±2；
- group-size bias 保持主协议中的 sum，不被无声归一化。

### 20.3 Agent 与产物

- 只允许三动作，最多四 actions；
- 不允许 native function calling、自由文本答案或 host fallback；
- 只能 note 最近一次 observation 的有效 result IDs；
- timeout retry 不重放已经返回的 action；
- requested/served model、usage 和 API style 完整记录；
- host 重读证据并验证 locator；
- overlap 只在 bundle阶段传递合并；
- 预算整项接受/跳过，绝不截断；
- 成功、capped、失败均可离线 reload/verify；
- 任意 bundle、trace、store 字节篡改均被检测。

## 21. 主要风险与报告解释

### 21.1 写入遗漏是检索无法修复的

S3 只包含 555/568 source locators。若问题所需事实属于缺失的 13 个 locator，R3 无论如何改写 query 都不能恢复。这应归为 write loss，而不是 retrieval failure。

### 21.2 整理污染可能被排名放大

R3 搜索的是 LLM 整理文字。如果一条事实把多个原始事件错误合并，BM25 可能因为语义更匹配而优先返回错误摘要。Locator 只能证明来源被引用，不能证明总结逻辑正确。

### 21.3 大 group 的求和偏置

Music / Relationships 的 50+ facts 可能获得更高 group score。主条件保留 ReFind 的 sum 以避免改算法，但必须按 group size 分析命中。

### 21.4 超长 facts 和窗口

最长事实 7,740 字符，最大 ±2 窗口 23,480 字符。Curated 不等于 short。必须记录真实 observation 和 Answerer cost，不允许只比较最终 evidence 数量。

### 21.5 多日期事实

Set-overlap 是为不可拆分 curated fact 做的工程适配。它可能让区间外的同一事实内容随 unit 一起出现，应在 temporal questions 中单独审计。

### 21.6 不是第三套独立论文算法

代码和日常讨论可以简称 R3，但报告方法章节应写成：

> R2-Curated: a ReFind-inspired adaptation that applies the same BM25, group aggregation, reciprocal-rank fusion, iterative retrieval, and note-taking mechanism to an LLM-curated filesystem, using citable fact bullets as units and H2 topic sections as groups.

不要写成“ReFind 原文提出 R3”，也不要把 H2 adapter、multi-date 和 EvidenceBundle归给 ReFind 作者。

## 22. 当前结论与下一步

当前已经完成：

- 正式 S3 结构复核；
- R2/R3 异同定义；
- fact/H2 adapter规则；
- 时间、排名、上下文、去重、预算与溯源设计；
- 实现步骤、测试 gate 和报告措辞。
- machine-readable protocol、确定性 parser/index、三动作四步 Agent、EvidenceBundle、runner、CLI 与 fake-provider 回归。

当前尚未完成：

- 真实 API smoke；
- dev-6 或 main-40 的 E6 结果。

实现状态、代码地图、冻结 hashes、离线命令和未来 smoke 入口见 `r3-curated-implementation.md`。下一步先运行一题 E6/dev-6 真实 API smoke；验证 wire compatibility、artifact、成本与 evidence 完整性后，再决定是否运行完整 dev-6，不能直接跳到 main-40。
