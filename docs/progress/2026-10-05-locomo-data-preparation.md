# 2026-10-05：固定 LoCoMo 官方数据与统一记录层

## 今天完成的内容

1. 从官方 `snap-research/locomo` 仓库固定 `data/locomo10.json`，使用数据文件最后修改所在的 commit `cbfbc1dba6bc53d00625212a0f22d55ffee7c1fc`。
2. 将官方原文件保存为 `data/raw/locomo10.json`，并把 CC BY-NC 4.0 许可保存为 `data/LICENSE.locomo.txt`。
3. 新增 `fs_memory_lab.locomo` 确定性转换器；每次运行都先验证官方文件 SHA-256。
4. 从 `conv-50` 生成 568 条统一 turn-level canonical records。
5. 生成 `source_map.json`，支持 `[SxTy]`、官方 `dia_id`、JSONL 行号和原 JSON Pointer 的相互定位。
6. 生成版本 manifest，固定来源、schema、计数、输出 hash、许可与异常处理。
7. 添加离线测试：原文件校验、568 条记录逐条回溯、双向映射、QA 隔离、确定性再生成和错误 hash 拒绝。

## 固定结果

| 对象 | 结果 |
| --- | --- |
| 官方原文件 | 2,805,274 bytes |
| 原文件 SHA-256 | `79fa87e90f04081343b8c8debecb80a9a6842b76a7aa537dc9fdf651ea698ff4` |
| 选定 conversation | `conv-50`（官方数组 index 9） |
| 说话人 | Calvin、Dave |
| 自然 session | 30 |
| turn | 568 |
| 官方 QA | 204；其中非 adversarial 158，adversarial 46 |
| canonical JSONL SHA-256 | `130a5a1e1b75083358ef27a98dd215a4e75c819ace6f2ee9b560ba394e0f0394` |
| source map SHA-256 | `6e99115961bae06a48bfb7e82dbdcc18dc32ccf6c5ce57e3c266dfc7a5d4d574` |

## 数据异常及处理

官方第 70 道 QA 的 evidence 使用 `D30:05`，而对应 turn 的真实 `dia_id` 是 `D30:5`。我们不修改官方原文件，也不静默改写，而是在 manifest 和 source map 中登记唯一别名：

```text
D30:05 -> D30:5 -> [S30T5]
```

另外，官方数据存在 2 道空 evidence 的 open-domain QA，以及 1 道 evidence 列表内重复引用的问题。这些都在 manifest 中计数；canonical 对话记录不含问题、答案或 evidence，避免答案泄漏。

## 为什么先做统一记录层

后续 S1 平铺原始 session、S2 文件夹化原始 session 和 S3 LLM 整理文件系统必须从同一批源 turn 派生。这样 E1–E7 的差异只来自存储和检索方法，而不是切片内容、顺序或数据版本。

## 实验范围与术语决策

### 主报告只使用 `conv-50`

当前主实验范围固定为 `conv-50` 的完整对话和 158 道非对抗问题。这与 Filesystem 论文的 LoCoMo 设置一致：该论文同样只使用一个 held-out conversation，即 `conv-50`，并从 204 道题中排除 46 道 adversarial 题。

这足以完成论文对齐的七条件受控比较，但报告中必须限定结论范围：

- 可以写“在 `conv-50` 上”或“在与 Filesystem 论文一致的 held-out conversation 上”；
- 不得写成“在完整 LoCoMo 上”或将结论直接推广到全部 conversation；
- 158 道题可以支持逐题配对比较和错误分析，但它们共享同一个 memory store，不能被表述为 158 个彼此独立的 conversation；
- 如果后续资源允许，再将关键条件扩展到其他 conversation，作为外部稳健性实验，而不是阻塞当前主实验。

完整 LoCoMo10 共 10 个 conversation、5,882 个 source turns、1,986 道题；其中 1,540 道属于 category 1–4。如果七个条件全部跑完整 LoCoMo，需要 10,780 个问答 episode，而 `conv-50` 主实验为 1,106 个，因此当前不把全量十组列为必做项。

### 固定术语

| 术语 | 本项目中的固定含义 |
| --- | --- |
| `source turn` | LoCoMo 原始数据中一个 speaker 的一次发言；对应一个唯一 `dia_id`。一来一回包含两个 source turns。 |
| `exchange` | 同一 session 内相邻的“发言＋回复”；通常包含两个 source turns。最后一个没有回复的 source turn 可以形成 singleton exchange。 |
| `session` | 有独立日期时间的一次完整聊天 episode，内部包含多个 source turns。 |
| `conversation` | 同一对人物跨多个日期的完整长期聊天；`conv-50` 包含 30 个 sessions。 |
| `retrieval unit` | 检索器实际建立索引和打分的条目；它可能是 source turn、exchange、chunk、文件或 Markdown section，不能与 source turn 混称。 |
| `dia_id` | LoCoMo 官方 source-turn 标识，例如 `D4:17`。官方 QA 的 evidence 使用它。 |
| `source locator` | 本项目及 Filesystem 风格的内联来源标记，例如 `[S4T17]`；通过 `source_map.json` 与 `D4:17` 对齐。 |

`conv-50` 的一个 source turn 平均约 142 个字符、26 个英文词，中位数约 128 个字符、24 个词；每个 session 平均 18.9 个 source turns。正式构建必须使用全部 568 个 source turns，不能根据 gold evidence 预筛选。

ReFind 原文对 `turn` 使用了不同定义：一个 user utterance 和对应 assistant response 合为一个 turn。为了避免歧义，本项目不直接沿用这个含混名称，而使用上表的 `source turn` 与 `exchange`。早期曾考虑派生 exchange-level retrieval units；该想法已被 2026-10-07 的正式实验地图取代。当前固定方案是：canonical records 始终保持 568 个 source turns；S1/S2 的 raw-chat ReFind-style 检索以一条 LoCoMo utterance/source turn 为最小 unit，以 session 为 group，并在同一 session 内返回命中 utterance 前后各 2 条。每个 unit 保留其 `dia_id` 和 source locator。报告必须把这项选择写成面向 LoCoMo 数据结构的适配，不能冒充 ReFind 原文的 paired-turn 定义。

## 图片 turn 的统一处理

### 哪个字段真正参与模型记忆和检索

主实验固定为纯文本执行，不下载图片，也不让视觉模型访问 URL。不同字段的作用如下：

| 字段 | 是否作为模型语义输入 | 用途 |
| --- | --- | --- |
| `text` | 是 | 原始发言文本。 |
| `blip_caption` | 是 | 官方 BLIP 生成的图片文字描述，作为图片的固定文本代理。 |
| `img_url` | 否 | 只作来源记录；不联网打开，避免链接失效、内容变化和额外视觉模型变量。 |
| `query` | 否 | 官方生成图片时使用的搜索词，只作 provenance。 |
| `re-download` | 否 | 数据维护标记，只作 provenance。 |

统一渲染格式为：

```text
{speaker}: {text}
[Image caption: {blip_caption}]
{source_locator} (dia_id: {dia_id})
```

没有 caption 时省略 caption 行。该表示必须在 S1、S2、S3 及基于原始聊天的 R2 条件中保持一致：

- S1/S2：caption 作为原始 session 文件中的一行可检索文字；
- S3：Management Agent 能读到 caption，并可把其中有用的视觉事实整理进记忆文件，同时保留 locator；
- ReFind-style R2：BM25 索引 `text + blip_caption`，因此问题中的词可以命中 caption；
- Answerer：只能看到检索出来的文本和 caption，不会看到图片像素，也不会访问 URL。

真实例子 `D4:17` / `[S4T17]`：原始 `text` 只说“这是我的店铺照片”，而 caption 是“一群人站在汽车前”。官方问题“Does Dave's shop employ a lot of people?”把该 turn 标为 evidence；如果只保留 URL 或删除图片 turn，文本模型无法得到人数线索，加入 caption 后才有可推理的文本证据。

`conv-50` 的 568 个 source turns 中有 125 个带 `blip_caption`。158 道非对抗题中，70 道的 gold evidence 至少涉及一个图片 turn；若删除全部图片 turn，46 道题会失去所有 gold evidence。因此不得删除图片 turn。Filesystem 论文没有披露媒体字段如何渲染；上述做法是本项目基于 LoCoMo 原论文 text-only QA 设置制定并公开的统一 protocol，不能冒充 Filesystem 作者原配置。

ReFind 论文没有在 LoCoMo 上实验，其报告范围是 text-only chat history，也没有 URL、caption 或视觉模型的处理规则。因此，将 `blip_caption` 纳入 LoCoMo 上的 ReFind-style 检索同样属于本项目的适配协议。当前已经实现共享 renderer、正式 S1 builder、正式 S2 store 与 S3 safe runner；正式 S3 store 与 R2 尚未构建或实现。S1/S2 中 caption 已作为文字写入，URL 仍未被写入或访问。

## Adversarial 问题的处理

### Filesystem 论文为什么排除

Filesystem 论文只明确说明排除 adversarial category，没有进一步公开解释原因。下面是根据 LoCoMo 数据结构和该论文评测目标作出的实验设计判断，而不是作者原话：

- category 1–4 都要求从 memory 中找到并利用可支持答案的内容，适合比较写入、检索和回答质量；
- category 5 故意把某个人的事实错误地归给另一个人，或对原文作误导性预设，目标是测试模型能否拒答；
- `conv-50` 的 46 道 category 5 记录没有普通 `answer` 字段，而是提供误导性的 `adversarial_answer`，正确行为通常是指出信息不足或问题前提错误；
- 因此它与普通 QA 的正确性、evidence recall 和 citation attribution 不属于完全相同的评分问题。把两类题直接混成一个平均分，会混淆“找不到证据”和“正确地拒绝错误前提”。

### 本项目的固定方案

- 主表：与 Filesystem 对齐，只评测 category 1–4，共 158 道题；
- 分类结果：分别报告 multi-hop 32、temporal 32、open-domain 7、single-hop 87；
- gold 缺陷敏感性：主表保留全部 158 题，同时补充剔除论文标记的 4 道缺陷 gold 后的 154 题结果；
- category 5：不混入主平均分。如果核心七条件完成后仍有资源，可将 46 道题作为独立的 abstention/hallucination 附加实验，单独定义拒答准确率、错误具体作答率和引用行为。

这样既能与 Filesystem 原结果直接比较，也不会把一种不同性质的安全/拒答任务混入主要检索结论。

## S1 平铺原始 session 已完成

从固定的 `data/processed/conv-50.jsonl` 构建了 `experiments/locomo-conv50-v1/stores/s1-flat/`：

- 30 个自然 session 对应 `session-01.md` 至 `session-30.md`，store 内没有子目录或 manifest；
- 全部 568 个 source turns 按原顺序出现，保留原 speaker、text、前后换行、locator 和 `dia_id`；
- 125 条 `blip_caption` 被写成统一的 `[Image caption: ...]` 行；图片 URL、query 和 `re-download` 不进入 store；
- 构建不调用模型，LLM、token 和 tool 成本均为 0；
- 独立校验清单位于 `experiments/locomo-conv50-v1/manifests/s1-flat.json`，包含输入、逐文件完整/正文和整体 store hash，以及 568 条 locator 的文件行号索引；
- store SHA-256 固定为 `5a58a8cca8616b91f3c231671271f6dbbedc669330b91e410980223ad2488ad8`。

新增的 `tests/test_stores.py` 会逐条反查全部记录，并检查原始换行、caption、顺序、唯一来源 ID、跨目录确定性、同目录幂等性、输入文件不变、防篡改与 gold 字段隔离。生成器遇到已存在但不同的 store 会拒绝覆盖。

这一步复现了 Filesystem 论文“一次 session 一个原文文件、平铺、零模型成本”的 S1 语义。论文未公开逐字节 Markdown 模板，因此 frontmatter、caption 和双来源标签的具体排版属于本项目已公开的确定性 protocol，而不是作者代码的原样复制。

## S2 Foldering Agent 与正式建库已完成

已新增独立 `foldering` 角色和 `fs_memory_lab/foldering_prompt.py`。论文没有公开 Foldered sessions 的建库 prompt 全文，因此该 prompt 明确标为 `paper-constrained-local-v1`：它复用论文的 taxonomy 原则，并把 Section 3 的 move-only、zero-byte-edits 要求操作化，禁止使用题目、答案、类别、gold evidence 或论文结果反推目录。

Foldering Agent 与 S3 Management Agent 完全分开：

- 模型只会收到 `view`、`grep`、受限 `rename` 三个工具；
- 工具层拒绝 create、edit、insert、delete、TOC/section read、文件改名、移回根目录、移动目录和非法 folder slug；
- 成功的 `rename` 只能把普通 `.md` 文件移动到 topic folder，并在移动后逐字节核对；
- 固定 user task 阻止调用方把 QA/gold 信息追加到 foldering 指令；
- FakeProvider 测试已经验证工具列表、system prompt、配置、同名移动和字节保持。

### S2 父文件夹名称从哪里来

具体的父文件夹名称**没有预先写死在 prompt 中**。Prompt 只规定命名和分类原则；Foldering Agent 在正式运行时阅读全部 30 个原始 session，比较反复出现的主题及其关系，然后自行决定：

1. 需要多少个主题文件夹；
2. 是否需要多层目录；
3. 每个文件夹的具体名称；
4. 每个完整 session 唯一归入哪个文件夹。

例如，`travel-planning/`、`family-and-relationships/` 只能是说明机制的假设例子，并不是预定标签，也不是论文给出的固定 taxonomy。正式运行前没有任何已知目录名；最终出现的 4 个目录由 Agent 从 30 个 session 无监督归纳得到。Agent 没有读取 QA、gold answer、category、gold evidence，也没有为了模仿论文报告结果而追求固定目录数量。

职责划分如下：

| 层次 | 职责 |
| --- | --- |
| Foldering prompt | 规定分类目标、taxonomy 质量原则、命名格式、允许和禁止的操作，不给出具体主题标签。 |
| Foldering Agent | 阅读原始 session，动态决定目录数量、层级、名称和每个 session 的唯一位置。 |
| Harness | 提供工具、执行移动，并强制阻止改正文、改 basename、复制、删除、移回根目录或非法路径；它不替模型判断语义主题。 |

父文件夹通过 `rename` 的目标路径被创建，不单独提供 `mkdir`。例如 Agent 请求：

```text
old_path = /memories/session-03.md
new_path = /memories/travel-planning/session-03.md
```

Harness 会在需要时创建 `travel-planning/`，再移动完整文件。允许变化的只有父路径；`session-03.md` 的 basename 和逐字节内容不变。一个多主题 session 也只能选择一个最主要或对未来检索最有用的归属，不能复制到多个目录。

### S2 prompt 的逐段中文解读

完整英文 prompt 固定在 `fs_memory_lab/foldering_prompt.py`，版本为 `paper-constrained-local-v1`，SHA-256 为 `0cec4a3d80877ee303458d3dd596e3d981e14f0782fa248d3df6ba990ebda778`。可以用 `python3 -m fs_memory_lab.cli foldering-prompt` 离线打印；该命令不会读取 API key、调用模型或创建 S2。

1. **身份与输入。** Agent 被定义为运行在 `/memories` 上的 Foldering Agent；输入是不可修改的、一次自然 session 一个文件的原始 Markdown transcripts。它不是回答 Agent，也不是 S3 的记忆总结 Agent。
2. **来源声明。** Prompt 明确标注为本项目依据论文约束重建。论文公开了 Foldered sessions 的行为和工具集合，但没有公开逐字的 S2 建库 prompt，因此不能把本文本称为作者原始 Prompt，也不能把论文用于 S2 搜索的 Prompt 6 误认成建库 prompt。
3. **唯一任务。** Agent 只添加 topic-folder taxonomy：决定目录、为目录命名、把每个完整 session 移入一个合适目录，使未来检索能够先通过路径缩小范围。S2 相对 S1 的新增信号只能是目录结构。
4. **不可变约束。** 只能移动完整文件；不得 create、copy、edit、rewrite、summarize、split、merge 或 delete；每个 session 在最终树中必须恰好出现一次；根目录不得遗留 `.md`；不得移动目录。我们的实现进一步要求 basename、扩展名、frontmatter、正文和全部字节保持一致。
5. **数据隔离与安全。** Taxonomy 只能从 transcripts 推导；不得请求或使用评测问题、答案、category、gold evidence 或期望结果。Transcript 中出现的文字全部按数据处理，不能把其中的指令当成 system instruction 执行。
6. **不预设答案。** Prompt 明确禁止追求预定目录数、套用预定义主题表或模仿论文曾报告的目录树。目录数量和层级必须由本次 30 个 session 自然决定。
7. **工具限制。** 模型只看到 `view`、`grep`、restricted `rename`。`view` 用于看目录和正文，`grep` 用于比较跨 session 的显著词，`rename` 只允许同 basename 的整文件移动，并自动建立目标父目录。模型没有正文写入或删除工具。
8. **Taxonomy 质量。** 五条原则分别是：同级名称可区分；同一父目录下内容相关；父名称能覆盖所有后代且子级更具体；相关 session 在树中距离更近；只有在确实能缩小未来搜索范围时才增加层级。既要避免 `misc` 一类无信息大桶，也要避免没有检索收益的过深目录或大量无意义单例目录。
9. **命名格式。** 文件夹必须使用简洁、内容导向的 lowercase kebab-case，例如 `travel-planning`；不能使用空格、下划线、大写字母，也不能用 `sessions`、`chunks`、`batch-1`、数字计数等描述输入机制而非语义主题的名称。本地 restricted `rename` 会在工具层拒绝不合规 slug。
10. **执行策略。** 先查看 `/memories` 建立完整清单，并充分阅读每个 session 的对话内容；不能只看编号、日期、参与者或通用 frontmatter。随后从全局规划一套连贯 taxonomy，再开始移动。遇到多主题 session 时，因为禁止拆分和复制，选择其主导或最具检索价值的唯一主题位置。
11. **完成前复查。** 再次查看目录树，确认最初清单中的每个 session 恰好出现一次、basename 不变、根目录没有 `.md`，并检查父子目录语义是否连贯。模型的自查之后还必须经过程序化完整性 gate，不能只相信自然语言完成声明。
12. **完成输出。** Agent 最后只需简要报告整理的 session 数量和最终目录路径；真正的实验产物是文件系统树、路径映射、trace 和验收 manifest，而不是这段自然语言总结。

其中，“LLM 设计 taxonomy、完整文件 move-only、zero-byte edits、Foldering 工具为 `view/grep/rename`”来自论文公开协议；“同 basename、全部文件必须归类、kebab-case、gold 隔离、prompt-injection 防护和程序化复查”是本项目为使变量更纯、运行更安全、结果可验收而加入的操作化约束。报告中必须保持这一区分。

### S2 安全执行层已经实现

已新增 `fs_memory_lab/s2.py` 和正式 CLI 状态机，将 `run_foldering()` 包在不可绕过的 staging、验收和发布协议里：

```text
PRECHECK → LOCKED → STAGED → AGENT_RUNNING → AGENT_SUCCEEDED
→ GATE_RUNNING → GATE_PASSED → PUBLISHING → PUBLISHED
```

- 正式运行前重新计算 S1 manifest SHA、30个文件的 basename、完整/正文 SHA、总字节和 content hash，不只相信 manifest 声明；
- `paper-constrained-local-v1` Prompt 以固定 SHA fail-closed，文本若变化但没有显式升级版本/hash，模型调用前即停止；
- 使用独占 lock 和同文件系统唯一 staging，Foldering Agent 的 `MemoryFS` 根目录只指向 staging，从不指向正式 S1；
- 每个 provider response 和工具结果即时追加到本地 JSONL；API 异常、completion cap 或超轮时仍保留 partial trace；
- 全局 Gate 独立于模型工具限制，检查恰好30个普通 `.md`、同 basename、逐字节和正文 hash 相同、无根目录文件、无 symlink/额外文件、folder slug 合法，并清理和记录二次移动遗留的空目录；
- 同时保留与 S1 相同的内容身份 hash，以及对目录路径敏感的 `layout_sha256`；
- 生成稳定的 `S1 path → S2 path`、更新后的 source index、完整 trace、S2 manifest；requested alias 和每轮 API 返回的 served model/指纹分别记录；
- 发布时 manifest 是元数据承诺，`s2-foldered.COMMITTED` 最后写入作为下游唯一有效标志；中途发布异常会回滚正式文件并把 staging 隔离到 `local-runs/`；
- 不提供 `--force` 或静默覆盖。任一正式目标已存在都会在 API 前拒绝。

真实模型的目录树不能宣称确定性：当前 adapter 没有把 Python `RANDOM_SEED=42` 发送给 API。Manifest 会明确记录 `seed_sent_to_provider: false`；我们只保证同一输入和同一确定性 FakeProvider 脚本得到同一内容/layout hash。

专门的 S2 测试覆盖成功发布、正式30文件集成、输入篡改、分类不完整、provider 中途异常、completion 截断、round limit、畸形 tool calls、内容变化、改名、额外/重复文件、symlink、空目录、Prompt/task/tool-schema freeze、写路径与 S1 隔离、并发锁、密钥错误脱敏、发布阶段回滚和 artifact cross-link 验证；S2 专门测试及当前全套离线测试均通过。

正式 `conv-50` 离线 preflight 先确认了 30 个文件、114,456 bytes，S1 manifest SHA 为 `5c5900c333c8f85463f038448560cb4357f1161d6ed43e9fbc86809ba7916d3c`，content SHA 为 `5a58a8cca8616b91f3c231671271f6dbbedc669330b91e410980223ad2488ad8`，Prompt SHA 为 `0cec4a3d80877ee303458d3dd596e3d981e14f0782fa248d3df6ba990ebda778`。随后 `check-api` 确认 requested alias `coding` 的 function calling 正常，NUS 实际 served model 为 `qwen3.8:27b`。

### 正式 S2 一次运行结果

正式构建只执行一次，没有根据目录外观或未来问答结果重跑择优：

| 字段 | 结果 |
| --- | --- |
| Run ID | `20261005T155659458241Z-9391e1f0` |
| 本地时间 | 2026-10-05 23:56:59 至 2026-10-06 00:01:34（约 4 分 35 秒） |
| 代码版本 | `b05732e0886ea56d6813021e7e3c01b24c7d10a7` |
| 模型 | requested `coding`；served `qwen3.8:27b`；fingerprint `vllm-0.26.0-b73e56ef` |
| 模型/工具调用 | 12 次 LLM call；32 次 `view`；30 次 `rename`；总工具调用 62 |
| Token usage | prompt 380,653；completion 15,096；total 395,749 |
| 输入/输出 | 30 个 session；114,456 bytes；4 个一级主题目录；根目录 0 个 `.md` |
| 内容 hash | `5a58a8cca8616b91f3c231671271f6dbbedc669330b91e410980223ad2488ad8`，与 S1 完全一致 |
| 布局 hash | `13060ab52750d7b9ca0ab5b667a6aac69fb38021190bbff7ebd7336150508d6a` |

实际 taxonomy 和唯一归属如下：

| 目录 | 数量 | Sessions |
| --- | ---: | --- |
| `cars-and-auto-work/` | 11 | 04, 05, 09, 12, 13, 14, 17, 21, 22, 26, 28 |
| `music-and-performance/` | 14 | 02, 03, 06, 07, 11, 15, 16, 18, 19, 20, 23, 24, 25, 29 |
| `photography/` | 2 | 27, 30 |
| `travel-and-outdoors/` | 3 | 01, 08, 10 |

程序化 gate 和随后独立执行的 `verify-s2` 均通过：30 个 basename 恰好各出现一次，每个文件与 S1 逐字节相同，没有根目录残留、symlink、非 Markdown 文件或空目录；S1 在 episode 后也再次通过校验。正式产物位于 `experiments/locomo-conv50-v1/` 下的 `stores/s2-foldered/`、`manifests/s2-foldered.json`、`manifests/s2-foldered-path-map.json`、`traces/s2-foldering.json` 和最后发布的 `manifests/s2-foldered.COMMITTED`。

这次运行需要正确解读：它证明本地 S2 pipeline 和“LLM 自定 taxonomy、整文件零字节移动”已经真实跑通；它不证明这 4 个目录是唯一或最优 taxonomy，也不等于使用论文 `gpt-5.4-mini` 的分数复现。Adapter 没有把 seed 发送给服务端，所以不能声称重新运行会得到相同目录。

## S2 完成时记录的原下一步（已被 2026-10-06 决策调整）

当时的顺序设想是：冻结并提交正式 S2 后先实现 ReFind-style R2，再实现 evidence-only R1；当时还准备设计 exchange 派生、奇数 session 的 singleton 处理及 gold `dia_id` 命中规则。2026-10-06 决定先推进 S3 输入准备，因此实现顺序已调整；2026-10-07 的正式实验地图又以 utterance-level unit 取代了早期 exchange-level 设想，所以 singleton exchange 规则不再属于当前协议。“不应未经 prompt/runner 冻结就直接运行 S3 管理 LLM”和“不为六个条件分别切一次原始数据”两项约束继续有效。

## 2026-10-06：S3 路线与确定性 chunk 输入流

### 先冻结的完整 S3 执行顺序

S3 不应从“立刻把 568 条对话发给学校 API”开始。固定顺序如下：

1. **核对并冻结输入协议。** 从同一份 canonical records 出发，先区分论文明确规则、由论文产物推定的规则和本项目必须补齐的 byte-level 规则。
2. **确定性生成 chunks。** 纯本地切分并保存模型将看到的精确文本，同时生成逐 chunk 和逐 source-turn manifest；不调用 LLM。
3. **用自动测试锁住输入流。** 证明 568 条 source turns 恰好各出现一次、顺序不变、session 不交叉、双上限成立、caption 保留、内嵌换行未被拆成额外 turn，并验证重复生成一致与篡改拒绝。
4. **单独核对并冻结 S3 Management Prompt。** 使用论文公开的 Builder Prompt 1 和 LoCoMo source-attribution Prompt 2；把作者未公开的固定 user wrapper 单独标为本地协议并保存 hash。不能把 prompt 与切片同时临时调整。
5. **冻结运行配置和工具面。** Management Agent 使用 `view/create/str_replace/insert/delete/rename/grep`，每 chunk 一个全新的 tool-loop episode；episode 之间只共享持续演化的 `/memories`。记录 requested/served model、reasoning effort、round/output caps 和 tool schema hashes。
6. **实现安全 S3 runner。** Runner 只接受本次固定 manifest/hash，按 chunk 全局顺序从空 store 串行执行；每块前保存恢复点，逐轮追加 trace；失败不发布半成品。禁止问题、答案、gold evidence 或未来检索结果进入建库上下文。
7. **先做 smoke test，再做一次正式 build。** Smoke 只验证 API function calling、工具权限、日期/locator 可见性和失败恢复，输出隔离在 `local-runs/`；正式 85-chunk 建库只启动一次，不按最终树是否“好看”重跑择优。
8. **离线验收并冻结。** 检查 frontmatter、路径、locator 可追踪性、root 边界、完整 trace、每 chunk 成本、最终 dirs/files/sections/KB/cross-references，并写 COMMITTED 标记；之后 E5/E6 必须共用同一个只读 S3 snapshot。

本小节记录 chunk 冻结当时的阶段：当时只执行了第 1–3 步。后续第 4–6 步的完成情况见文末追加记录；截至目前仍没有创建正式 S3 memory store，没有调用学校 API，也没有用未来 QA 检查或优化 chunks。

### 论文规则核对与 session 边界修正

论文 Appendix C.1 明确写明：build stream 是 consecutive dialogue turns，每块最多 8 turns，达到 3,000 characters 时提前结束；Management Agent 每个 chunk 运行一个 build episode。Table 11 同样固定 `8 turns per chunk, 3,000-character cap`。这里的 turn 是一位 speaker 的一次 utterance：Figure 1 把三条相邻发言分别标为 `[S6T5]`、`[S6T6]`、`[S6T7]`；一来一回是两个 source turns。

正文没有用一句独立的话写 “never cross session boundaries”，但公开产物提供了强证据：

- 刊出的 Prompt 8（作者说明其中的文件命名已修订为与实际 store 对齐）使用 `session_04_chunk_02.md` 这一 session-scoped 示例结果路径；
- Figure 5 中 LoCoMo 的 per-chunk trajectory 有 85 个构建点；
- `conv-50` 三十个 session 分别计算 `ceil(session_turns/8)` 后总数恰好为 85；若无视 session，把 568 条 records 当作一条全局流，只会得到 71 块；
- 当前统一 renderer 下，任一 8-turn session 内候选都不超过 3,000 characters，因此 85 与 71 的差异不能由字符 cap 解释。

因此主复现改为“自然 session 是硬边界，session 内 greedy 双上限”。这比先前计划中的无边界全局流更符合论文实际产物。报告中要写“依据公开产物推定”，不能写成作者正文逐字规定。论文没有公开可执行的 byte-exact chunker；header、换行、characters 的精确定义、单 turn 超长行为和 user wrapper 都必须由本项目透明补齐。

### 本地固定协议

正式生成器为 `fs_memory_lab/s3_chunks.py`，输入只读 `data/processed/conv-50.jsonl`，并 fail-closed 地核对其固定 SHA-256 `130a5a1e1b75083358ef27a98dd215a4e75c819ace6f2ee9b560ba394e0f0394`。它不读取原始 `locomo10.json`、QA、answer、category、gold evidence 或包含 QA evidence alias 的 `source_map.json`。

每个 chunk 的模型可见文本精确为：

```text
Session {session_index} · {YYYY-MM-DD}

{speaker}: {original text}
[Image caption: {official BLIP caption}]   # 仅存在时
[SxTy] (dia_id: Dx:y)

...下一条 source turn...
```

Figure 1 的 chunk 示意本身提供 session/date；具体 header 字符串仍是本项目选择。每条 turn 复用 S1/S2 的 `render_source_turn()`，块间使用两个换行，chunk 文件不补终止换行。3,000 characters 指最终文件全文的 Python `len(str)`，即 Unicode code points；header 和所有分隔符都计入。加入下一完整 turn 会使 turns 超过 8 或 characters 超过 3,000 时，先封闭当前块；若单条 turn 连同 header 已超过 3,000，则构建失败，不截断。

S1 session header 还保留了 `session_datetime_raw` 的具体时分，而 S3 header 按 Figure 1 的形状只携带 ISO 日期；因此只能说二者共享逐 turn renderer，不能说完整模型输入逐字节相同。`conv-50` 的 30 个 session 日期彼此唯一，32 道 temporal QA 也没有一道需要区分同一天内的小时/分钟，所以这不会删除本次题集可见的时间答案信息；它仍属于需要在报告中披露的本地序列化选择。

文件保存于 `experiments/locomo-conv50-v1/streams/s3-management-v1/`，命名为 `session_01_chunk_01.txt` 等。它们是管理 Agent 的输入，不是 memory store，所以不放入 `stores/`。独立 manifest 为 `experiments/locomo-conv50-v1/manifests/s3-management-stream.json`，记录输入 hash、规则来源、逐 chunk hash/characters/bytes/turns、每个 locator 的字符与 UTF-8 byte offsets、有序 stream hash、零模型成本和 gold 隔离声明。

### 固定结果与完整性测试

| 项目 | 固定值 |
| --- | ---: |
| Sessions | 30 |
| Source turns | 568 |
| Chunks | 85 |
| Turns with caption | 125 |
| Turns per chunk | 1–8 |
| Characters per chunk | 121–2,387 |
| Total characters | 110,949 |
| Total UTF-8 bytes | 111,056 |
| Stream SHA-256 | `f599b8d35f55ac08b68595f728aaa7a20f30e14a529c7dcb0f1631857b6594ec` |
| Manifest SHA-256 | `6323382879ddafdb21c1207bf22a3d11c277d323faabfa28d1ae3144e78025d5` |
| Build cost | 0 LLM calls / 0 tokens / 0 tool calls |

`tests/test_s3_chunks.py` 会利用 manifest offsets 从文件中逐字节恢复全部 568 个 renderer blocks，并对照 canonical 顺序；同时覆盖 exact-3000 接纳、3001 触发换块、Unicode characters 与 UTF-8 bytes 的区别、正文内空行仍只算一个 turn、单条超长拒绝、跨 session 拒绝、跨目录确定性、重复运行 `verified-existing`、chunk/manifest 篡改拒绝及额外字段 fail-closed。正式数据中字符 cap 没有自然触发：58 块由 8-turn 上限封闭，另外 27 块在自然 session 末尾封闭，所以 synthetic boundary test 是必要的。

重新核对命令：

```bash
python3 -m fs_memory_lab.s3_chunks
python3 -m unittest tests.test_s3_chunks -v
```

这段结论是 chunk 冻结时的阶段性下一步；后文记录 prompt、工具/runtime contract 与 safe runner 已依序完成。

## 2026-10-06：S3 Management Prompt 原文提取与冻结

路线第 4 步已经完成。准确名称是 **Management Agent / Builder Agent**，不是单纯的 summary agent：它要先 survey 现有 `/memories`，再提炼值得保存的信息，同时可以创建、更新、移动、合并、拆分、重命名和删除文件，解决冲突并维护 frontmatter、时间历史、cross-reference 与 taxonomy。

本次直接读取论文官方 arXiv v1 TeX 源的 Appendix A.1，而不是继续依赖 PDF 视觉转录：

- Prompt 1（Builder system prompt）逐字节提取后为 12,521 characters、12,663 UTF-8 bytes，SHA-256 `6f122e1e4f222a6004a6dd8839c3d14225c7cfc1e9679dd1f44b224fc2f5a4a3`；
- Prompt 2（LoCoMo source-attribution extension）为 872 characters、874 bytes，SHA-256 `a8e35d244e6774c61ab26a0a3f4b7e1f762bab634e0ad516b969d306d572cf0b`；
- 运行时以单个换行连接 Prompt 1 和 Prompt 2，合并后为 13,394 characters、13,538 bytes，SHA-256 `2ceb39921adb3c5eb4da98964b4925b8886f8540f3663b8f64d1539137d6be26`。

此前仓库中的手工转录没有缺句或新增管理规则，但省略了部分 Markdown 空行，也调整了示例目录树的对齐空格，因此旧 hash 不能再作为“论文原文”使用。新的 active prompt 位于 `fs_memory_lab/management_prompt.py`，在 import 时 fail-closed 核对三个固定 hash；`python3 -m fs_memory_lab.cli management-prompt` 可以完全离线打印模型将收到的 system prompt。

论文只说 benchmark-specific Prompt 2 appended after Prompt 1，并没有独立序列化两块之间的连接字节；因此一个换行的合并边界仍明确标为本地冻结选择。论文也没有公开每个 chunk 的精确 user message。本项目把它单独冻结在 `fs_memory_lab/s3_protocol.py`：`Integrate this conversation chunk into the existing memory filesystem.` + 两个换行 + 原样 `chunk_payload`。该 wrapper 版本为 `project-defined-s3-user-wrapper-v1`，不能写成作者原 prompt。

机器可读 contract 位于 `experiments/locomo-conv50-v1/manifests/s3-management-prompt.json`。本步骤成本仍为 0 LLM calls / 0 tokens / 0 tool calls，也没有创建正式 S3 memory。随后已继续完成路线第 5–6 步，详见下一节。

## 2026-10-06：冻结 S3 七工具/runtime contract，并实现 safe runner

路线第 5–6 步已经完成，但真实 API 阶段尚未开始。本次没有读取 API key、没有向 NUS 发请求、没有做 smoke test，也没有生成正式 `stores/s3-curated/`。

### 冻结了什么

Management Agent 的有序七工具 profile 固定为 `view/create/str_replace/insert/delete/rename/grep`。论文 Table 12 提供工具描述、参数与 required 标志，但没有发布完整 function wrapper 或 JSON 序列化；所以 wrapper 继续明确标记为本地重建，而不是作者原代码。

机器可读 runtime contract 位于 `experiments/locomo-conv50-v1/manifests/s3-management-runtime.json`，同时锁住输入、prompt、工具、模型适配、上下文压缩、episode 顺序、安全上限和发布规则：

| 对象 | 固定 SHA-256 |
| --- | --- |
| S3 stream manifest 文件 | `6323382879ddafdb21c1207bf22a3d11c277d323faabfa28d1ae3144e78025d5` |
| S3 prompt contract 文件 | `2b16c9041829666e3825d2d349c689b6cc1ce4b9de6e367f35a123c485918a20` |
| S3 runtime contract 文件（初始 runner v1） | `ae480c40162e5262f74ef3fb5cb64314ad2507a744d59122c019039e8bb3017f` |
| Runtime config canonical JSON（初始 runner v1） | `da352bbdcbc12fa68169ac5ea8307fa5238f506b7040473f5272d7729ad18be2` |
| 有序七工具 profile | `e4541dedafbd645e6e11f8847c95283b8738c668915b006f06dd0dea57c0945e` |
| 有序七工具 schema canonical JSON | `3f4b2edc2045348743961231bc174c973e9c8a5147225bb9caece1fc7a254b56` |
| 实际 wire-order 紧凑 JSON | `f365069d4e826f8489273b85496ebdf3a61b93bbd7678baef531cec273f3c282` |

这里特意没有混写“论文目标配置”和“本地真实执行配置”：

- 论文目标角色配置仍是 `gpt-5.4-mini`、high reasoning、32,768 completion-token cap、每个 build episode 最多 60 rounds；
- 本地拟执行配置冻结为 NUS SoC `https://soclaas-api.comp.nus.edu.sg/v1/chat/completions`、`api_style=portable`、requested alias `coding`、预期 served model `qwen3.8:27b`、300 秒 timeout 和 20 MB response cap；
- portable adapter 不发送 `reasoning_effort`、`max_completion_tokens`、temperature 或 seed。Python seed 42 仍不会使真实模型采样确定；若返回的 served model 缺失或不是固定值，runner 会失败而不是悄悄接受另一 backbone；
- 96k token 触发、保留最近 3 轮的 compaction 形状来自论文，但具体摘要 prompt、旧消息序列化和 8,192-token 单轮摘要 cap 是作者未公开时采用的本地近似，也已经随 runtime contract 固定。

### Safe runner 的执行边界

新增 `fs_memory_lab/s3_runner.py` 以及三个 CLI：

```bash
python3 -m fs_memory_lab.cli s3-preflight  # 完全离线
python3 -m fs_memory_lab.cli build-s3      # 以后才运行的正式真实 API 构建
python3 -m fs_memory_lab.cli verify-s3     # 正式发布后完全离线复核
```

正式 `build-s3` 只允许 clean、40 位 Git commit 和 `CompatibleChatProvider`；测试运行必须显式使用隔离的 test artifact ID 与 `test-*` revision，不能产生正式 artifact。执行时从空 staging store 出发，85 chunks 按全局序号串行处理，每块都创建新的 Agent 聊天上下文，只有 filesystem 状态跨块保留。发送前重验 chunk hash，每块前复制 checkpoint，逐事件落盘并 `fsync` trace；工具执行后检查文件/目录/深度/字节/参数/调用次数上限，episode 后检查 frontmatter、合法且不超前的 locator、cross-reference、文件 hash chain 与列表/表格事实候选的内联 locator。

正式目标只会在 85 个 episodes 全部通过全局 gate 后发布：先 store 和 trace，再 manifest，最后写 `s3-curated.COMMITTED`。任何模型、API、tool、gate 或 publication 异常都会回滚已发布部分，把 staging、trace、checkpoints 和脱敏 failure record 隔离在 `local-runs/s3-management/`，不留下可被下游当成成功快照的正式结果。正式运行期间还会在首尾核对 Git commit，防止代码中途变化。

### 离线验收结果与不能声称的内容

deterministic fake provider 已把完整 85-episode 流从空 store 跑到发布与独立 `verify-s3`，并覆盖 freeze drift、输入篡改、provider/profile/served-model 漂移、未来 locator、缺 citation 的列表事实、资源上限、并发锁、失败 checkpoint/quarantine、发布回滚和 artifact 交叉校验；当前全套离线测试通过。

这只能证明安全 runner 和验证协议在受控响应下能完整执行，不能写成“学校 API 已跑通 S3”或“正式 S3 memory 已完成”。当前 verifier 也有两个需要在报告中公开的边界：

1. 它验证每轮 trace、工具事件、前后文件 inventory、store hash chain 与最终 artifact 的内部一致性，但不重新执行整段 tool trace，因此不是每个 tool call 与文件变化之间的独立因果 replay 证明。
2. 它能机械拒绝没有 locator 的列表/表格事实候选，并验证所有出现的 locator 合法且当时已经可见；但自由自然语言段落是否把每个可验证事实都完整引用，无法只靠正则完全判断，正式结果仍需抽样人工审计。

### 当前下一步

先在 `local-runs/` 做一次低成本、可丢弃的 NUS 真实 API smoke test，只检查当前路由、函数调用、locator 写入、受限文件操作和失败恢复。Smoke 通过后，冻结 clean commit，再执行唯一一次正式 `build-s3`；发布完成后立即运行 `verify-s3` 并记录成本与最终 hashes。在此之前，`stores/s3-curated/`、`manifests/s3-curated.json`、`traces/s3-management/` 和 `manifests/s3-curated.COMMITTED` 都应保持不存在。

## 2026-10-06：S3 真实 API 单 chunk smoke 通过

使用冻结输入的第一个文件 `session_01_chunk_01.txt`（8 source turns，`[S1T1]`–`[S1T8]`，SHA-256 `4fa1be2a828dc3e99cee29bf306bee6918ac8c4973bb0df7cdceffef306927ec`）完成了一次隔离的 NUS 真实 API smoke。该测试直接复用冻结的 Management Prompt、七工具 schema、portable provider profile、user wrapper 和 S3 store gate，但把上限收紧为最多 4 次 HTTP 请求、每次最多 8 个工具调用、全 episode 最多 12 个工具调用。输出仅写入被 Git 忽略的 `local-runs/`，不调用正式 `build_s3_store()`。

实际结果：

- requested alias：`coding`；每次响应报告的 served model 均为 `qwen3.8:27b`；
- 3 HTTP requests / 3 rounds / 3 tool calls，工具序列为 `view → create → create`；
- usage 合计：15,652 prompt tokens、1,009 completion tokens、16,661 total tokens；
- 创建 `people/calvin.md` 与 `people/dave.md`，共 7 次 locator mentions；
- store gate 通过，tree SHA-256 为 `2a532c744b95325120227d4bafc3d5866bfebe8628b05ea11675407bfad2974e`；
- 正式四个目标 `stores/s3-curated/`、`manifests/s3-curated.json`、`traces/s3-management/`、`manifests/s3-curated.COMMITTED` 在测试后仍全部不存在；
- 密钥通过一次性命名管道注入，测试进程结束后未保留在环境、代码或 trace 中。

第一次受限进程尝试在 DNS 阶段被本地网络沙盒拦截，没有到达学校 API；获准联网后没有自动重试，而是重新进行一次明确授权的 smoke。最终通过结果不能写成“正式 S3 已完成”，它只证明当前 NUS 路由、served-model 锁定、七工具函数调用、实际文件写入、locator 和单块 store gate 可以一起工作。

当前下一步更新为：把本次记录提交成 clean Git revision，然后执行唯一一次正式 85-chunk `build-s3`，完成后立即运行离线 `verify-s3` 并冻结成本与 artifact hashes。

## 2026-10-06：第一次正式 S3 尝试安全失败与 runner v2

第一次正式 85-chunk build 在 clean commit `648f384d52df16953b23767ff5137fcfbde02aa9` 上从空 store 启动，使用冻结的 v1 runtime contract。Chunk 1 完整通过；chunk 2 的模型写入中，把三处要求的 `[S{session}T{turn}]` 标签缩写成 `[S15]`、`[S11]`、`[S13]`。这些实际分别应为 `[S1T15]`、`[S1T11]`、`[S1T13]`。严格 episode gate 报出 `Malformed source locator '[S15]' in people/calvin.md` 并终止运行。

失败结果：

- 完成 1 个 chunk，在第 2 个 chunk 失败；
- 共 8 次 API responses、11 次工具调用；
- usage 合计 45,010 prompt tokens、3,997 completion tokens、49,007 total tokens；
- staging store、增量 events、checkpoints 和 quarantine 保留在本地诊断目录；
- 正式 `stores/s3-curated/`、manifest、trace directory 和 COMMITTED marker 均未发布；
- 没有手工改正文件、没有把畸形标签当成合法标签、没有从旧 checkpoint 拼接下一次正式运行；
- 脱敏机器摘要保存为 `experiments/locomo-conv50-v1/traces/s3-formal-attempt-001-failure-2026-10-06.json`。

这次失败暴露的是执行协议缺口：v1 只在 episode 结束后运行完整语义 gate，因此模型虽然在最终回答中写出了正确引用，却没有意识到文件里的三个缩写已经不合法。为保持规范同时让模型自己修复，runner 升级为 `s3-safe-runner-v2`：

1. 每个 episode 开始时，允许 locator 集固定为“此前已完成 chunks + 当前 chunk”；
2. 每次工具调用完成后扫描整个 staging store 的 locator；
3. malformed/future locator 按 `文件:行号` 聚合反馈给同一 Agent，工具动作明确标记为已生效；正常的 `view/grep` 观察不会因反馈而丢失；
4. 最多反馈 100 条诊断，超出时要求检查已列出的文件；
5. 不自动替换、不猜测 locator，也不放宽 episode/global strict gate；Agent 若不修正，构建仍失败。

新增测试用 malformed store 一次制造三个短标签，验证同一 episode 收到完整反馈后用 `str_replace` 修复，再完成全部 85-chunk fake-provider build；另验证不修复时终态 gate 仍失败、future locator 仍在即时反馈和终态两层被拒绝。当前全套 81 项离线测试全部通过。

v2 冻结值：runtime contract SHA-256 `36b043ad7cc0afcab45d671e42f3e03b8ed339c3486bd396d2820d9d72c94f4a`，runtime config canonical SHA-256 `434d4dccd181668e2a2d0e4f1c13136c3611d6188b7acbf25d0df4af04864183`。Management Prompt、user wrapper、85-chunk stream 及七工具 profile/schema/wire hashes 均未改变。下一次正式运行必须基于这个 v2 clean commit，从空 store 和 chunk 1 重新开始。

## 2026-10-06：第二次正式运行停在 chunk 10 与 runner v3 续跑修复

第二次正式运行在 clean commit `2d67f269e79dce68fed83f04044d9751864006ac` 上启动。Chunks 1–9 全部通过并保存完整 episode traces；chunk 10 的文件内容写入完成后，严格 episode gate 发现 `calvin.md` 使用 `/memories/dave.md > ## Auto maintenance shop)`，而目标文件的真实标题是 `## Auto maintenance shop (opened 2023-05-01)`。路径存在，但章节简称无法唯一、精确解析，因此运行安全停止。失败前共记录 55 次 responses、81 次工具调用和 419,651 total tokens；正式四个目标仍未发布。

Runner 随后升级为 `s3-safe-runner-v3`：

1. 每次工具调用后除 locator 外，也扫描文件路径和章节交叉引用；不精确章节会连同来源文件、行号和目标文件可用标题反馈给同一 Agent 自修复；
2. 新增 `resume-s3`，只允许使用 `failed` 且未留下正式输出的运行；续跑前逐一验证连续 episode 前缀、冻结输入、prompt/runtime 身份、provider metadata、store 文件 inventory/hash chain，以及失败 chunk 前的 checkpoint；
3. 失败 chunk 的写入不会复用。事件日志由已验证的 completed episode traces 重建，随后从该 chunk 的 `before` checkpoint 重新调用模型；
4. 最终 manifest 和 trace index 会记录续跑起点、复用的已完成 chunk 数、旧/新 runtime contract hashes 和来源代码 revision；
5. episode/global gate、85 块齐全后才发布及 marker-last 协议均未放宽。

v3 runtime contract SHA-256 为 `f9f02a125edad9fd16a1e2c9117e392b81794101c8a570312b2c04f46579389f`；runtime config、Management Prompt、user wrapper、85-chunk stream 和七工具 schema 均未改变。83 项离线测试通过，其中包含完整的“第 10 块失败→只运行 10–85→最终 85 traces 独立验证”测试。实际失败运行 `20261006T022525914538Z-a1352213` 的前 9 个 episodes 与 `chunk-010-before` checkpoint 也已通过只读续跑预检。

## 2026-10-07：chunk 66 压缩超时与 runner v4

正式运行随后成功推进并保留 chunks 1–65。Chunk 66 在第 20 个管理轮次后达到 96k prompt-token 压缩阈值；此前 32 次文件工具操作均发生在该失败 episode 内，runner 按事务规则回滚到 `chunk-066-before`，没有发布正式 store。失败原因是只读 context-compaction API 请求在 300 秒内未返回（`The read operation timed out`），不是 API key、locator 或文件内容错误。

Runner v4 只对 context-compaction 这类不执行文件工具的只读请求增加有限重试：最多 3 次，失败后分别退避 2 秒和 4 秒；普通管理请求、文件工具及整个 episode 均不自动重试，因此不会重复写文件。每次 retry 与最终成功所用 attempt 会写入 trace。旧 v3 前缀的 runtime config hash 与 v4 新 episodes 的 hash 分别保留，最终验证按 `resume.start_chunk` 校验混合前缀，不能把旧 episode 冒充新协议。

v4 runtime contract SHA-256 为 `bd3f429a532056513c0893b108023ad96a1bf5be4a74c9c419c4fd5293593eb5`，runtime config canonical SHA-256 为 `612fa89e9212ebec6c1cd78d44ad88388c53f5d801bd751fd78a6c3308a37005`。实际运行 `20261006T022525914538Z-a1352213` 已通过只读续跑预检：复用 65 个 completed episodes，从 `chunk-066-before` 恢复，不重跑 chunks 1–65。

## 2026-10-07：chunk 68 普通请求超时与 runner v5

使用 runner v4 从 `chunk-066-before` 恢复后，chunks 66–67 成功完成；chunk 68 在第 8 个管理轮次的普通 provider 请求上超时。该请求没有返回完整 assistant response，因此其后不存在待执行的工具调用；runner 回滚到 `chunk-068-before`，正式输出仍未发布，前 67 个 completed episodes 与文件 hash chain 均保留。

Runner v5 将相同的有限 timeout retry 扩展到普通 provider 请求：最多 3 次，退避 2/4 秒；只有在完整响应尚未返回时重试，任何已返回 response 中的文件工具都只执行一次。重试事件和成功响应所用 attempts 均写入 trace。为支持再次续跑，prefix validator 现在验证多代 runtime config 的连续分段：本次实际前缀为 chunks 1–65 使用 v3 config、chunks 66–67 使用 v4 config，新 episodes 使用 v5 config；分段必须连续、只能按批准的版本顺序前进，并以失败运行的 runtime 结束。

v5 runtime contract SHA-256 为 `76ba20c6b5b6d91f95371f61b85dada54de78ec6eb3514e8e89190a18c3e4d81`，runtime config canonical SHA-256 为 `2f866df6ce35c40c14c19aa1014771bd45cbbb901085898d73c7fde204a32128`。93 项离线测试通过，其中包含普通请求连续两次 timeout 后第三次成功、完整 85-episode build 只发布一次，以及 v3→v4→v5 混合前缀独立验证。实际运行已通过只读预检：复用 67 个 episodes，从 `chunk-068-before` 恢复。

## 2026-10-07：40 道正式题与 6 道开发题已确定性冻结

为控制七条件矩阵的时间与 API 成本，正式主测试由原计划的 60 题缩减为 40 题。七个条件因此产生 280 个最终答案，而不是 420 个。该改动在任何正式检索或答题结果产生前完成，不能再根据后续分数更换题目。

### 候选池与排除规则

抽样只使用官方 `conv-50` QA：

- 官方共 204 题；
- 排除 46 道 category 5 adversarial，剩余 158 道 category 1–4；
- 再排除 Filesystem 论文 catalog 的非对抗评测顺序第 20、64、112、138 题，因为其 gold 与 transcript 有实质冲突；
- 最终可靠候选池为 154 题：Multi-hop 30、Temporal 32、Open-domain 7、Single-hop 85。

Category 5 没有普通 `answer`，而是给出诱导性的 `adversarial_answer`，正确行为通常是拒答或指出前提错误；它需要拒答准确率、诱导答案采纳率等另一套指标，因此不混入主 QA 平均分。若资源允许，只能作为独立附加实验。

### 固定配额与覆盖约束

正式题配额固定为：

| Category | 类型 | 题数 |
| ---: | --- | ---: |
| 1 | Multi-hop | 10 |
| 2 | Temporal | 10 |
| 3 | Open-domain | 7（全部） |
| 4 | Single-hop | 13 |
|  | 合计 | 40 |

这不是按 154 题原比例抽样，而是覆盖优先的分层子集。生成器使用 seed 42 的 `sha256-rank-v1`，按 question ID 的 SHA-256 排序产生候选，接受第一个同时满足以下事前约束的候选；Python 内部随机实现或字典顺序不会改变结果：

1. 四类配额精确为 10/10/7/13；
2. 40 题的 gold evidence 合计覆盖 30/30 个 sessions；
3. 每个类别均覆盖对话早期（S1–S10）、中期（S11–S20）和后期（S21–S30）；
4. caption-evidence 配额按类别固定为 7/4/4/5，共 20 题；
5. 不读取任何模型输出或方法分数，也不按 answer 文本筛选。

冻结结果为 20 道涉及 BLIP caption 的题、18 道纯文本证据题和 2 道官方未给完整 gold evidence 的 Open-domain 题。后两题仍参加 correctness/F1，但不进入 Evidence Recall 分母。该子集在四类非对抗问题、全部时间区间和主要证据形态上覆盖较广，但不能声称代表完整 `conv-50`、完整 LoCoMo10 或 adversarial 能力；类别内仅 7–13 题，细分类结论以描述性分析为主。

### 在线输入、gold 与开发题物理隔离

正式产物位于 `experiments/locomo-conv50-v1/question-sets/`：

| 文件 | 用途 |
| --- | --- |
| `main-40-input.jsonl` | 在线检索器/Answerer 可读；只含 set ID、运行位置、question ID、conversation ID 和 question。 |
| `main-40-gold.jsonl` | 仅离线 evaluator/Judge 使用；含 category、answer、官方及 canonical evidence IDs、locators、sessions 和 caption 标记。 |
| `main-40-audit.md` | 人工核对40题、来源顺序、类别和覆盖情况；不是模型输入。 |
| `dev-6-input.jsonl` / `dev-6-gold.jsonl` | 2 Multi-hop、2 Temporal、2 Single-hop 的工程开发集，与正式40题不重合。 |
| `manifest.json` | 固定来源 hashes、排除规则、算法、配额、覆盖统计和所有输出 hashes。 |
| `verification.json` | 自动完整性验证报告。 |

正式输入中机械禁止 `answer`、`category` 和 gold evidence 字段。官方 QA 中的已知别名 `D30:05` 在 gold 层同时保留原始 ID，并规范化为 canonical `D30:5` / `[S30T5]`；在线输入看不到这些信息。

关键 hashes：

- `main-40-input.jsonl`：`31a65ab18797abb4491cf8de2e172050d25000eb5c1f6ddb77383d3900b757af`；
- `main-40-gold.jsonl`：`a6833ca585ca26efcdd038a5cf202fd46657999053ebd7b8cc73793f7544718b`；
- frozen manifest：`a58f07b3341ed7c79009fc233e7a9fc52ec2ba6f8ee59bc00c4602da759ba997`。

生成与验证入口为 `python3 -m fs_memory_lab.question_sets` 和 `python3 -m fs_memory_lab.question_sets --verify-only`。仓库测试要求从官方固定数据重新生成后与所有 checked-in 产物逐字节相同，同时验证40题唯一、四类配额、缺陷题排除、30 sessions 覆盖、20道 caption-evidence、开发/正式集合不重合、来源/输出 hashes 以及在线/gold 隔离。题集4项专项测试和当前全套97项离线测试均通过。

### 汇总与报告规则

因为40题不是按原始类别比例抽样，主结果必须同时报告：每类分数、四类等权 macro、按可靠154题规模（30/32/7/85）计算的 post-stratified estimate，以及明确标注为“固定40题样本”的 micro average。所有 E1–E7 使用相同运行顺序和相同40题，主要比较必须逐题配对；一两题的差异只能称为趋势，不能直接声称稳定提升。

## 2026-10-07：S3 从 chunk 68 续跑后停在 chunk 72

Runner v5 从 `chunk-068-before` 后台恢复后，chunks 68–71 成功完成；chunk 72（`session_27_chunk_01.txt`）运行到第 18 个管理轮次时，普通 provider 请求连续 3 次超时，按固定重试规则安全停止。失败 episode 内曾发生错误删除 `/memories/calvin.md` 的工具动作，但整个 chunk 72 store 与 trace 已进入 `quarantine/`；续跑只允许从保留的 `checkpoints/chunk-072-before` 恢复，不能采用失败 episode 的任何写入。

当前状态：前 71 个 completed episodes 保留；`formal_outputs_published=false`，没有残留正式 artifacts，也没有 cleanup error。后续不得自动重启；应先保持当前诊断资料，再基于 clean commit 运行只读 resume preflight，确认前缀、checkpoint 和 hash chain 后才可由用户明确启动 chunk 72。

## 2026-10-07：R1 Filesystem 与 R2 ReFind-style 检索说明

### 先区分“存储”和“检索”

S1、S2、S3 是三种**记忆存储形式**；R1、R2 是两种**从记忆中寻找证据的方式**。最简单的记忆方法是：

- R1 Filesystem/Center：让 LLM 像人一样打开文件夹、看目录、搜索关键词、阅读文件；
- R2 ReFind-style：先用 BM25 从记录中找候选，再让 LLM 根据上一轮结果多轮改写关键词、保存证据。

因此，实验比较的不是两个完全独立的系统，而是把同一份存储分别交给两种检索器：E1/E3/E5 使用 R1，E2/E4/E6 使用 R2。

### R1：Filesystem/Center 原生文件检索

Filesystem 论文主实验中的 filesystem variants 使用四个只读工具：

| 工具 | 作用 |
| --- | --- |
| `view` | 列出目录，或读取文件全文/指定行范围 |
| `grep` | 用正则表达式在 Markdown 文件中按行搜索 |
| `toc` | 查看 Markdown 文件的标题目录 |
| `section_read` | 读取指定标题路径下的章节 |

论文的层级存储 Searcher Prompt 给出的检索逻辑是：

```text
问题
  -> view /memories，一次性查看目录、文件名和 description
  -> 根据主题选择少量可能相关的子树或文件
  -> grep 短而有区分度的关键词及同义词
  -> 用 view/toc/section_read 阅读命中位置所需的上下文
  -> 检查问题的每个部分是否都有证据
  -> 证据充分便停止，并回答及给出文件/行号/章节引用
```

它没有一个固定排名器替模型决定哪个文件最相关。LLM 自己决定搜索路径、关键词、需要打开的章节以及停止时机。因此，文件夹名、文件名、frontmatter `description`、Markdown 标题和正文都会直接影响它能否找到答案。层级结构好时，模型可以先路由到人物或主题，再读取小章节；结构不好时，模型可能走错目录、漏掉同义表达，或者读取大量无关内容。

R1 可以多轮调用工具，但不是固定轮数。论文 hard cap 为：Verbatim dump/Foldered sessions 等较简单 store 最多 20 个 search tool rounds；Agent-curated/Reorganized 等层级 store 最多 40 个。hard cap 只是防止失控，容易的问题应提前停止；一次 assistant turn 也可并行发出多个互不依赖的只读工具调用。

需要避免一个常见误解：Filesystem 论文中虽然出现 BM25，但默认 filesystem 检索并不是 BM25。论文另有三个概念：

1. `Chunk retrieval` baseline：把对话切成原始 chunks，用 BM25 返回 Top-3；
2. `Center+BM25` harness ablation：在 Center 工具上额外增加 ranked keyword search；
3. 默认 filesystem variants：只用 `view/grep/toc/section_read`。本报告的 R1 指第三项。

论文依据：Filesystem §3（PDF 第 7–8 页）及 Appendix A.3 Prompt 5–7（第 31 页为导言，Prompt 正文位于 PDF 第 32–36 页）。原论文的 Search Agent 搜索后直接回答并引用文件。

### R2：ReFind 的 BM25 加 LLM 多轮检索

ReFind 不在提问前用 LLM 总结或重写聊天，也不构建人物卡、知识图谱或语义树。它保留原始聊天、session ID、时间戳和细粒度记录，并建立不需要 LLM 调用的 BM25 倒排索引。问题到来后，ReAct controller 决定搜索词和参数。

原方法分为两个阶段：

```text
Stage 1 Retrieval
问题
  -> LLM 提出关键词和可选日期范围
  -> BM25 在细粒度聊天记录上打分
  -> 细粒度排名与 session 聚合排名用 RRF 融合
  -> 返回 Top-5 命中，每个命中带同 session 内前后各 2 个单位
  -> LLM 用 take_note 保存可能有用的完整原文证据
  -> 根据结果更换关键词、补另一个多跳事实或缩小时间范围
  -> 最多 4 次 search；证据充分则 finish_search

Stage 2 Reasoning
保存的 notes 按 session 分组并按时间排序
  -> 独立 Answerer 只根据这些证据回答
```

ReFind Retrieval Agent 使用三个工具：

| 工具 | 作用 |
| --- | --- |
| `search_chatrecord` | 用关键词以及可选 `date_from/date_to` 搜索聊天 |
| `take_note` | 保存上一轮中可能相关的完整原始结果 |
| `finish_search` | 结束证据收集，进入回答阶段 |

新搜索会替换上一轮 observation，因此有用结果必须先 `take_note`。Prompt 要求检索器只收集证据、不提前回答，并尝试不同关键词。它是真正的多轮搜索：后面的 query 应根据前一轮暴露的人名、事件、日期或缺失的多跳事实发生变化，而不是机械重复同一个问题。

#### BM25 与两级 RRF

ReFind 的 BM25 固定为 `k1=1.2`、`b=0.75`，预处理包括 lowercase、空格/标点切分、Porter stemming 和 stopword removal。对每个细粒度记录 `c` 计算两个排名：

1. `r1(c)`：该记录本身的 BM25 排名；
2. `r2(c)`：把同一 session 内所有记录的 BM25 分数相加，对 session 排名后，每个记录继承所属 session 的排名。

最终融合为：

```text
RRF(c) = 1 / (60 + r1(c)) + 1 / (60 + r2(c))
```

如果同一 session 中多条记录都命中查询，该 session 及其中的记录就会得到提升。每轮默认返回 Top-5。

#### 四个 chat-native controls

1. **Session-aware rank fusion**：把细粒度命中和 session 整体相关性结合；
2. **Local context expansion**：返回命中位置前后各 2 个单位，并在 session 边界截断；
3. **Temporal narrowing**：LLM 可以提供日期范围，在 BM25 打分前过滤；Prompt 建议先宽搜，再用发现的时间线索窄搜，以免遗漏后来的回顾性提及；
4. **Seen-session filtering**：已经在前一轮返回的 session 在后续轮中排除，减少重复、提高每轮的信息增益。

因此，ReFind 并不只是“BM25 搜四次”。它是“LLM 控制的多轮 BM25”，并在每一轮维护已保存证据、已看 session 和上一轮 observation 的状态。

论文依据：ReFind §3（PDF 第 4–6 页）及 Appendix A Retrieval Agent Prompt（PDF 第 13–14 页）。

### R1 与 R2 的核心差异

| 对比项 | R1 Filesystem/Center | R2 ReFind-style |
| --- | --- | --- |
| 直观理解 | LLM 自己翻文件夹 | BM25 先筛选，LLM 再多轮调整搜索 |
| 默认排名引擎 | 无 | BM25 + unit/group RRF |
| 主要路由信号 | 目录、文件名、description、标题、正文 | 关键词、时间、细粒度命中、group 聚合 |
| 上下文获取 | LLM 决定读哪些行/章节/文件 | 系统固定返回命中及同 group 的 ±2 邻居 |
| 跨轮去重 | 依靠 LLM 不重复搜索 | 系统排除已返回 group |
| 搜索预算 | S1/S2 20 rounds；S3 40 rounds hard cap | 最多 4 次 `search_chatrecord`，可提前停止 |
| 原论文回答方式 | Search Agent 边搜边回答 | Retrieval 与 Answerer 分离 |
| 主要优势 | 能直接利用 LLM 建出的文件结构 | 在原始记录上提供稳定、可审计的候选排名和多轮修正 |
| 主要风险 | 走错目录、同义词漏检、工具轮次和上下文成本高 | BM25 词汇不匹配；固定邻域或 group 设计可能不适合改写后的 store |

一句话概括：R1 把“怎么找”主要交给 LLM 和文件结构；R2 把“初步找候选”交给 BM25，把“下一轮怎么找”交给 LLM。

### “两种还是三种检索方式”的固定命名

研究层面仍定义为两个检索范式，不新增第三个独立算法：

| 固定名称 | 适用 store | 定位 |
| --- | --- | --- |
| R1 Filesystem/Center | S1、S2、S3 | LLM 使用只读文件工具自行路由和读取 |
| R2-Raw ReFind-style | S1、S2 | 在 utterance→session 两级结构上运行 ReFind 核心机制 |
| R2-Curated ReFind-inspired | S3 | 把同一核心机制适配为 section→topic-group 两级结构 |

因此，本地代码可以为了工程清晰把第三个适配器暂称 `R3`，但报告不能把它表述为与 R1、R2 并列的第三套独立检索算法。推荐实现为一个共享 `ReFindCore` 加 `RawChatAdapter` 和 `CuratedMarkdownAdapter`；报告使用 `R2-Raw` 与 `R2-Curated`，并明确后者是 ReFind-inspired。这样 BM25、RRF、多轮 controller、Top-K、时间过滤、去重和 note-taking 只实现一次，变化仅限 unit、group 和 context expansion 的定义。

### R2 的 Top-5 与“前后文”精确定义

ReFind 原文最终返回的是 **Top-5 turn-level hits，不是 Top-5 sessions**。对每个细粒度 turn 先取得 BM25 排名；再把同一 session 中所有 turn 的 BM25 分数相加形成 session 排名；每个 turn 继承所属 session 的排名；最后用 `1/(60+r_turn) + 1/(60+r_session)` 融合并选择分数最高的 5 个 turns。Session 只参与加分，Top-5 中可能有多个 turns 来自同一 session。

原文的 local context expansion 指：对每个中心命中，沿同一 session 的时间顺序返回它前面 2 个 turns、中心 turn 和后面 2 个 turns，并在 session 边界截断。它不是排名前后两个结果，也不跨到前后 session。例如命中一个七-turn session 的 Turn 4，会返回 Turn 2–6；命中 Turn 1，只能返回 Turn 1–3。

本项目的具体映射为：

- R2-Raw：Top-5 是 utterance/source-turn units；每个中心命中扩展同一 session 内前后各 2 条 utterances；
- R2-Curated：Top-5 是 leaf Markdown sections；每个中心命中扩展同一 top-level topic group 内前后各 2 个 sibling/leaf sections，不能跨 topic-group 边界。

若多个 Top-5 中心命中的 ±2 窗口重叠，重复文字会影响 EvidenceBundle 与 token 成本。正式 R2 runner 实现前必须冻结“重叠窗口合并、结果 ID、排序和 token 计数”规则，并用单元测试证明同一原文片段不会因重叠被重复计费或重复交给 Answerer；这一点不能在跑完结果后再决定。

### Alice 饮食问题的直观例子

问题：“Alice 现在的饮食习惯是什么，与过去相比有什么变化？”

R1 可能执行：

```text
view /memories
  -> 找到 people/alice.md
  -> grep "diet|vegetarian|yakiniku|seafood"
  -> 读取 Diet 章节和命中行附近内容
  -> 根据日期及 [SxTy] 比较新旧状态
```

R2 可能先搜索 `Alice + vegetarian`，保存开始吃素的原始对话；再搜索 `Alice + yakiniku + seafood`，排除已看 session，寻找更早的饮食偏好；最后由 Answerer 比较新旧证据。R2 的第二轮关键词来自第一轮之后仍缺失的“过去状态”，而不是预先写死。

### 本项目对两种检索的统一改造

为了公平比较，不能让 R1 自己回答而 R2 使用单独 Answerer。正式协议统一为：

```text
R1 或 R2 只收集证据
  -> 输出统一 EvidenceBundle
  -> 同一个 Answerer 生成最终答案和 citations
```

R1 因此会在论文四个文件工具之外增加实验控制动作 `take_note` 和 `finish_search`；它们只负责形成统一证据包，不改变 store，也不能伪造证据。R2 保留 ReFind 的 evidence-only 设计。这样 E1–E6 的主要区别是“证据如何被找到”，而不是最终回答模型或输入格式不同。

### R1 主实验协议已冻结为 evidence-only

2026-10-07 最终决定：为了控制实验规模并让 R1/R2 的比较能够归因于检索，E1、E3、E5 的正式主实验只运行 **R1 evidence-only**，不再把 `paper-direct` 作为另一套正式主条件。当前实现计划也不单独开发或运行一套 `paper-direct` runner；只保留论文 Prompt 5/6/7 原文、配置和行为说明作为审计基线，用派生 prompt diff 证明 evidence-only 改了什么。除非之后明确扩展范围，否则 `paper-direct` 不进入七条件主表，也不额外形成需要运行的结果。

Filesystem 论文原生 R1 是：Search Agent 使用 `view/grep/toc/section_read` 搜索，并由同一个 Agent 直接生成答案和文件引用。主实验的 evidence-only 版本保留其按 store 区分的检索策略、四个只读文件工具和搜索上限，但作如下受控改造：

1. Search Agent 的职责从“搜索并回答”改成“只搜索并选择证据”，不得输出最终答案；
2. 在论文四个只读文件工具之外增加 `take_note` 与 `finish_search` 两个 orchestration actions；它们不是文件系统工具，不能读写 store；
3. `take_note` 只能选择已经由文件工具返回的真实 path/line/section 片段，程序重新从冻结 store 解析原文，不接受模型自由改写成证据；
4. Search Agent 输出统一 `EvidenceBundle`，随后由 E1–E7 共用的固定 Answerer 根据 question + evidence 作答；
5. Answerer 不能看到 condition 名、gold answer、gold evidence 或检索器的隐藏推理；
6. 检索成本、Answerer 成本和总成本分开记录，避免把新增回答调用隐藏在汇总数字中。

三种 store 的 evidence-only R1 映射固定为：S1 使用 Appendix A.3 Prompt 7 的 flat/raw-session 搜索策略并保留 20-round hard cap；S2 使用 Prompt 6 的 foldered/raw-session 搜索策略并保留 20-round hard cap；S3 使用 Prompt 5 的 hierarchical-store 搜索策略并保留 40-round hard cap。由于原 prompt 的角色说明、Cost model、Verify-then-stop、Multiple-choice、Inference、Absence、Citation Format 和 Output 等位置都带有直接回答措辞，正式实现必须对三个 prompt 做完整 redline，不能只替换开头和 Output，也不能声称逐字使用 Prompt 5/6/7。应保存论文刊出文本、其 hash、派生 evidence-only prompt 的 hash 和明确 diff，把未改动的论文搜索文字标为 `paper_published_text_reused`，把所有角色/回答/证据动作改写标为 `controlled_modification`；只有后续从作者官方源文件完成逐字冻结后，才可使用 `verbatim` 或 `byte-exact` 表述。

#### evidence-only 与 paper-direct 的取舍

| 方面 | paper-direct | evidence-only（本项目选择） |
| --- | --- | --- |
| 与 Filesystem 原论文一致性 | 最高；Searcher 边搜边答 | 较低；改变角色输出并新增证据控制动作 |
| R1/R2 检索公平性 | 较弱；回答架构不同 | 较强；两者交给同一 Answerer |
| 错误归因 | 检索与推理混在一个 Agent 内 | 可区分 store 缺失、检索漏失和 Answerer 推理错误 |
| E7 双源融合 | 需要重新设计如何拆出证据 | 可直接融合两个 EvidenceBundle |
| API 成本 | 少一次回答调用 | 多统一 Answerer，但所有条件一致且可分项核算 |
| 论文表述 | 可称 native/paper-direct R1 | 必须称 `Center-derived evidence-only retrieval` 或 controlled adaptation |

选择 evidence-only 的原因不是预期它分数更高，而是本报告的核心问题是“不同检索方法找到了什么证据”，且需要对 E5→E6、E6→E7 做写入/检索/推理错误分解。统一 Answerer 可以去掉一项明显混杂因素，并让双源融合只发生在证据层。相应代价是 E1/E3/E5 结果不能与 Filesystem 论文的 paper-direct 分数作严格同协议对比；报告只能称为方法约束下的受控扩展，并同时披露不同 backbone、40题子集和 evidence-only 改造。

### R2 在三种 store 上的固定适配

**S1/S2（ReFind-style）**：

- unit：一条 LoCoMo utterance/source turn；
- group：自然 session；
- 上下文：同 session 前后各 2 条 utterances；
- 时间：session date；
- seen-group dedup：后续轮排除已返回 session；
- BM25 不把 S2 文件夹路径加入打分，保证 E2/E4 第一轮排名相同；但结果 provenance 显示路径，controller 可在后续轮利用主题目录词。

这与 ReFind 原文把一组 user utterance + assistant response 视为一个 turn 不完全相同，必须称为 LoCoMo 数据适配。

**S3（必须称 ReFind-inspired）**：

- unit：最小 leaf Markdown section；无 heading 时整文件为一个 unit；
- BM25 文本：frontmatter description + heading path + section body；文件系统 path 不直接参加打分；
- group：unit 所属 top-level heading region；没有一级标题时退回文件；
- group score：同 group 的 unit BM25 分数求和；
- context：同 group 内相邻的前后各 2 个 sibling/leaf sections；
- seen-group dedup：排除已经返回的 topic group，而不是整个大型人物文件；
- 时间：通过 section 中的 source locators 映射回原始 session 日期，绝不用文件 mtime。

原始 ReFind 的层级是细粒度聊天记录→session；S3 已被 LLM 改写成 section→topic hierarchy，所以 E6 不能写成“复现 ReFind”，只能写成“把 ReFind 的多轮检索机制适配到 agent-curated filesystem”。

### 六个主条件中的位置

| 条件 | Store | Retrieval | 研究作用 |
| --- | --- | --- | --- |
| E1 | S1 平铺原始 session | R1 | 原始文件基线 |
| E2 | S1 平铺原始 session | R2 ReFind-style | 原始聊天增强检索 |
| E3 | S2 文件夹化原始 session | R1 | 目录分类是否帮助文件 Agent |
| E4 | S2 文件夹化原始 session | R2 ReFind-style | 多轮检索能否利用路径线索 |
| E5 | S3 LLM 整理文件系统 | R1 | Filesystem 主基线 |
| E6 | S3 LLM 整理文件系统 | R2 ReFind-inspired | 核心跨论文组合 |

E7 再融合 E2 的原始聊天证据和 E6 的整理后证据；它不是第三种独立检索器，而是两路已有 evidence bundles 的确定性融合加统一 Answerer。

### 当前实现状态边界

本节记录的是已经冻结的实验方法，不代表检索 runner 已经完成。截至本节记录时，S1/S2 stores 已完成，S3 正式构建仍在续跑；正式 evidence-only R1、BM25/RRF R2、统一 Answerer、E7 fusion 和批量评测 runner 尚待实现和测试。后续代码必须以 `docs/plans/one-month-experiment-map.md` 的固定参数为准，若改变 unit、group、Top-K、上下文窗口或搜索轮数，必须更新 manifest 和本笔记，不能静默漂移。

### 两篇论文对 S1/S2 与检索细节的公开程度审计

本项目的 `S1`、`S2` 是我们为实验方便使用的名称，分别对应 Filesystem 论文的 `Verbatim dump` 与 `Foldered sessions`；ReFind 论文没有把条件命名为 S1/S2。

| 项目 | 论文是否明确给出 | 是否逐项完整 | 本地处理 |
| --- | --- | --- | --- |
| S1 建库原则 | 是。Filesystem §3（PDF 第 7 页）规定：每个自然 session 一个文件、正文 verbatim、frontmatter description 只写 session 编号、日期和说话人、根目录平铺、确定性构建、零模型成本 | 否。论文未公开构建脚本、精确文件名、逐字节 Markdown 模板、空白/换行规则、LoCoMo 图片 caption/URL 的序列化规则 | 使用确定性 builder 固定这些未公开的工程细节，并在 manifest 中记录 hashes；不能称为作者源码复刻 |
| S1 建库 prompt | 不适用。S1 不调用 LLM，因此没有建库 prompt | — | 不自行伪造一个 LLM prompt；只使用确定性代码 |
| S1 查询 prompt | 是。Filesystem Appendix A.3 Prompt 7（PDF 第 35–36 页）完整给出 Verbatim dump Search Agent system prompt | 核心文本完整；仍需把问题作为固定 user turn 注入，工具 schema 由函数调用接口单独提供 | 后续应逐字冻结 Prompt 7，并把本项目 evidence-only 改造明确标为实验控制，而非论文原文 |
| S2 建库原则 | 是。Filesystem §3（PDF 第 7 页）规定：从 S1 开始，让 LLM 自己设计 folder taxonomy，只移动完整 session 文件，正文零字节修改，目录是相对 S1 唯一新增信号 | 否。目录名称和数量本来就由模型自定；论文也没有公开这次 foldering pass 的完整 system/user prompt、终止措辞、路径冲突处理、校验和恢复程序 | `foldering_prompt.py` 是 `paper-constrained-local-v1` 重建版，不是作者 prompt；本地额外加入同 basename、zero-byte hash、staging、rollback 和完整性 gates |
| S2 查询 prompt | 是。Filesystem Appendix A.3 Prompt 6（PDF 第 33–35 页）完整给出 Foldered sessions Search Agent system prompt | 核心文本完整；它是查询 prompt，不是建库 prompt | 后续逐字冻结 Prompt 6；不能拿 Prompt 6 冒充 S2 foldering prompt |
| S1/S2 查询工具与配置 | 是。Filesystem Table 12（PDF 第 49–50 页）逐项给出 `view/grep/toc/section_read` schema；Table 11（PDF 第 47–48 页）给出模型、effort、round cap、output cap、并发和 compaction 等共同配置 | 接近实验合同级完整，但仍不是可直接运行的代码库；API wrapper、日志格式、失败恢复、结果排序等工程实现没有全部公开 | 本地 runner 需冻结这些工程选择，并逐项标注 paper-specified 或 project-defined |
| ReFind 与 S1 | ReFind §3（PDF 第 3–6 页）明确规定保留 raw chat，不做 LLM 总结/重写，以 turn、session、timestamp 和 raw text 建 BM25 索引；概念上接近原始聊天存储 | 它没有规定“一个 Markdown 文件一个 session”，也不是 Filesystem 的 S1 文件布局 | 本项目的 R2-Raw 是把 ReFind 检索适配到 S1/S2 原始 session 文件，不能说 ReFind 原文实现了 S1 |
| ReFind 与 S2 | 没有。ReFind 不让 LLM 设计文件夹 taxonomy，也没有 Foldered sessions 条件 | 不适用 | S2+ReFind 是本项目新增组合 |
| ReFind 检索 prompt/参数 | 是。Appendix A（PDF 第 13–16 页）完整给出 Stage 1 Retrieval Agent、时间过滤 addendum、observation user message、Stage 2 answer templates；Appendix B 给出 BM25 `k1=1.2,b=0.75`、Top-5、±2、RRF `k=60`、最多4轮、去重/时间过滤、模型与 token caps | 仍非逐行可执行实现：论文未给出完整源码、索引库与版本、具体 stopword 表、同分 tie-break、重叠 ±2 窗口合并/排序/计费、日期边界和部分 backend JSON/result-ID 细节 | 正式 R2 前必须把这些未公开决定冻结到 protocol、manifest 和单元测试中；S3 的 section→topic-group 映射必须标为 ReFind-inspired |

结论：S1 的核心建库规则和查询 prompt 足够明确，但逐字节文件格式不是全部公开；S2 的核心约束和查询 prompt 明确，**真正负责“设计目录并移动文件”的建库 prompt 没有公开**。因此我们可以做高保真、可审计的 constrained reproduction，但不能声称 S2 是作者代码与 prompt 的完全一比一复现。ReFind 对自己的原始聊天检索流程与两阶段 prompt 公布得更完整，但它本身没有 S1/S2 文件系统条件，尤其没有 S2 foldering。

## 2026-10-07：chunk 73 网关 503 与 runner v6

使用 runner v5 从 `chunk-072-before` 恢复后，chunk 72 成功完成；chunk 73（`session_27_chunk_02.txt`）在第 11 个管理轮次的普通 provider 请求上收到 HTTP 503：学校网关报告 backend group `180` 暂无健康后端。该失败不是 API key、输入、文件系统 gate 或模型工具格式问题。失败 episode 的 17 次文件工具调用已随整个 chunk 73 一起隔离并回滚；前 72 个 completed episodes、`chunk-073-before` checkpoint 和 hash chain 保留，正式 store 仍未发布，也没有 cleanup error。

Runner 随后升级为 `s3-safe-runner-v6`。Provider adapter 只把 HTTP 408、429、500、502、503、504 分类为可恢复的 `TransientProviderError`；400/401 等配置或认证错误仍立即失败，不能用 retry 掩盖。Timeout 继续最多尝试 3 次并退避 2/4 秒；retryable HTTP 最多尝试 5 次并退避 5/15/30/60 秒。普通管理请求和 context-compaction 请求都使用该分类，但只允许在完整 assistant response 尚未返回时重试；已经返回的 response 及其文件工具永不重放。每次 retry 记录错误种类、HTTP 状态、脱敏错误文本、attempt、上限、退避和是否继续。

v6 canonical runtime config SHA-256 为 `ec9c97275f4ea8d353ea235f772c2893de6293a75a9d0bef843f4060d5663970`；runtime contract 文件 SHA-256 为 `fc8c6d73da256181e8ca22b8d6af147c2038e2804875fef559e5b62bf98b21b8`。v5 contract/config 已加入批准的续跑 lineage，因此后续只读 preflight 必须证明 chunks 1–72 的多版本前缀连续且以 v5 结束，再从 `chunk-073-before` 用 v6 继续。

## 2026-10-07：chunk 74 缺少行内来源与 runner v7

chunk 73 使用 v6 成功写入后，chunk 74（`session_28_chunk_01.txt`）在 episode 结束后的严格 store gate 被拒绝。失败不是 API、checkpoint 或既有记忆污染：模型在 `dave.md:L70` 新增了一条关于 car-mod blog 与既往改装经历关系的列表事实，但该行没有任何 `[SxTy]` 来源标签。隔离 store 的完整扫描只发现这一处漏引；失败 chunk 的全部改动被 quarantine，chunks 1–73、`chunk-074-before` checkpoint 与 trace/hash chain 保持完整。

根因是本地 runner 的反馈时机不完整：v6 已会在每次工具调用后即时检查 malformed/future locator 与 cross-reference，但“列表/表格事实是否有行内 locator”只在 Agent 停止之后由最终 gate 检查。于是最终 gate 正确拒绝了漏引，却没有给同一 Agent 留下修复机会。

runner 因此升级为 `s3-safe-runner-v7`：每次工具调用后新增 citation-completeness 检查，并与最终 gate 复用同一套列表/表格识别规则。写入动作仍然保留，错误以可恢复的 tool observation 返回文件路径和行号，Agent 必须补充有效的已见 source locator 或删除/改写该事实后才能结束；最终严格 gate 没有删除或放宽。新增回归覆盖“先写无引用事实、收到即时反馈、同 episode 补引并通过”、Markdown 表头/分隔行排除与数据行检查，以及完整 85-episode fake build/verify。全套 102 项离线测试通过。

v7 不改变 Management Prompt、七工具 schema、provider 参数或 retry 参数，因此 canonical runtime config SHA-256 仍为 `ec9c97275f4ea8d353ea235f772c2893de6293a75a9d0bef843f4060d5663970`；新的 runtime contract 文件 SHA-256 为 `43e6317efddb3a3509b16d48feafb52317bf416c807e61326a45f0d214ec6819`。v6 contract/config 已加入批准的恢复 lineage。真实恢复 preflight 已重新证明：应复用 chunks 1–73，从未经污染的 `checkpoints/chunk-074-before` 重放 chunk 74，不能手改或继续使用失败的 quarantine store。

## 2026-10-07：R1 evidence-only 实现启动

为避免正在运行的正式 S3 在结束时因主仓库变脏而失败，R1 开发被隔离到 `codex/r1-evidence-only` worktree；主目录在 S3 完成前不接收 R1 修改。第一阶段完成了论文与现有代码的只读审计，并冻结 `docs/reproduction/r1-evidence-only-contract.md` 作为施工合同。

审计确认的映射为 S1→Prompt 7/20 rounds、S2→Prompt 6/20 rounds、S3→Prompt 5/40 rounds；论文正文位置为 Appendix A.3 第 31 页导言、Prompt 5 第 32–33 页、Prompt 6 第 33–35 页、Prompt 7 第 35–36 页，Table 11 第 47–48 页，Table 12 第 49–50 页。此前把 Prompt 5 起始页写成 31 的记录需要在本分支中更正。

第一阶段同时冻结了边界：`view/grep/toc/section_read` 是论文四个文件工具；`take_note/finish_search` 与 `EvidenceBundle` 是本项目的 controlled adaptation，必须分开统计和披露。正式 R1 不能复用当前 `AgentRunner.run("search")`，因为它把三个 store 都绑定到 Prompt 5/40 rounds，并允许自然语言直接作答；后续将实现独立 evidence-only 状态机、observation ledger、host re-read 防伪以及 S1/S2/S3 store snapshot gate。截至本节，尚未调用 R1 API，也没有产生任何 R1 实验结果。

## 2026-10-08：R1 阶段 2——EvidenceBundle 与存储真实性基础

R1 开发继续只发生在隔离 worktree `/Users/wangwenqi/.codex/worktrees/r1-evidence-only/memory bench` 的 `codex/r1-evidence-only` 分支，没有修改仍承载正式 S3 运行的主目录，也没有调用学校 API。阶段 2 新增 `fs_memory_lab/evidence.py` 与专项测试 `tests/test_evidence.py`，先把“什么才算一份可信证据”固定下来，再进入文件工具和 Agent 实现。

本阶段实现的共享边界包括：严格白名单的 online question（禁止 gold answer、category、gold evidence 泄漏）；由固定 `source_map.json` 与 canonical records 构造的 `SourceCatalog`；由外部冻结 hash、manifest、S2/S3 `COMMITTED` marker、path-map/trace 和实际挂载字节共同验证的 `VerifiedStoreManifest`；不可变的 `StoreSnapshotRef`、`AttributionUnit`、`EvidenceItem`、`EvidenceBundle`；以及与成功 bundle 分离的 `RetrievalFailureArtifact`。共享 bundle 可供后续 R1/R2/R3/fusion 使用，但 R1 profile 会额外禁止 rank/score。

来源规则也已固定。S1/S2 的一个 evidence unit 必须是完整的 canonical source-turn block，不能只截一半发言；S3 的 evidence unit 必须是实际 Markdown 事实行，并逐行带可解析的 `[SxTy]`。证据文字、locator、`dia_id`、日期、speaker 和 hashes 全部由 host 重读冻结 store 后生成，模型后续只能选择已经观察到的位置，不能提交自写引文。真正的 observation ledger 将在阶段 4 接上；当前 schema 已预留并校验 observation IDs，但不会把“模型声称看过”直接当成证明。

独立对抗审查中发现并修复了多类 fail-open 风险：重复 locator occurrence 的 hash 语义、caller 自签 manifest、S2 path-map/trace 未绑定、S3 trace/publication 未绑定、目录空节点未进入 tree hash、catalog 与 manifest 可错配、深层可变对象可篡改、failure artifact 可篡改、停止理由与 fallback proof 不一致、证据顺序重复/倒序、同一路径重叠或紧邻证据被拆开计费、无序 set/dict 被误当协议数组、整数/浮点 score 产生不同 canonical bytes，以及“把正式 store 原样复制到 staging 路径后仍被接受”。最终规则要求 manifest loader 保存已验证 published root；即使内容逐字节相同，另一路径也会被拒绝。所有协议数组只接受有序 list/tuple，score 统一成 float（包括负零归一化）；`no_progress_after_global_fallback` 也已与冻结计划对齐为全局兜底后连续两轮无新增证据。

当前专项测试覆盖真实 S1/S2 固定产物以及合成的 formal S3 fixture。真实 S3 在 85 chunks 完成并正式发布前仍会被 fail-closed 拒绝，这是预期行为，不以测试夹具冒充实验结果。阶段 2 最后一轮专项回归为 31/31 通过；加入既有 S1/S2/S3、数据与题集测试后的全仓库离线回归为 133/133 通过。独立 PASS gate 放行后才进入阶段 3 的四个只读 filesystem tools。本文记录的是基础设施验证结果，不是 40 道题的检索或回答结果。

## 2026-10-08：R1 阶段 3A——论文四工具的 wire schema 冻结

阶段 2 已通过独立最终 gate 并提交为 `0e0d947`。阶段 3 先只冻结论文 Appendix C.4 Table 12 的四个只读 filesystem functions，顺序严格为 `view → grep → toc → section_read`，没有混入 `take_note` 或 `finish_search`。`fs_memory_lab/r1_tools.py` 以现有 Table 12 转录为唯一来源，分别冻结有序 profile hash `d100442f…a483`、递归键排序的 ordered schema hash `6d9d68f0…3c6`、保留 dict 插入顺序的 compact wire hash `d6130495…6d1b`。任何名称、顺序、description、参数、required 数组、wrapper 或 key insertion order 漂移都会 fail closed。

论文没有公开可执行语言的默认参数，因此本地默认值单独标为 project-defined：`view(start_line=1,end_line=-1)`；`grep(path=/memories,case_sensitive=false,max_results=100)`；`toc/section_read` 无补充默认值。默认值没有偷偷写入论文 schema，并另有 hash `59a34c97…52d`。3A 专项 schema 测试为 3/3 通过。下一小步 3B 才实现严格只读 executor、结构化 coverage 与调用前后 snapshot gate；现有会创建目录且仍带写方法的 `MemoryFS` 不会直接作为正式 R1 executor。

## 2026-10-08：R1 阶段 3B——严格只读执行器与恢复型 TOCTOU 防护

阶段 3B 完成 `R1ReadOnlyFilesystem`。它只暴露论文 Table 12 的 `view`、`grep`、`toc`、`section_read`，不复用带写能力且会自动创建目录的旧 `MemoryFS`。路径解析只接受冻结 manifest 中已经验证的文件和目录；目录浏览也从 manifest inventory 生成，而不是信任运行时 `rglob` 的结果。每次实际文件读取都逐级使用 no-follow 文件描述符，要求最终节点是普通文件，并在文字进入 tool result 之前与 `VerifiedStoreManifest` 中冻结的逐文件 SHA-256 再核对。`view` 与 `section_read` 只为真正返回的行生成 inclusive coverage；`grep` 只记录实际返回的命中行；目录 `view` 与 `toc` 不产生可选证据 coverage。成功结果是不可变、内容寻址的 `ReadToolResult`，记录 canonical arguments、内容 hash、coverage、截断状态、root survey/whole-tree grep 标志和相同的 pre/post tree identity。

这里要区分论文原文与本地补全。四个工具的名称、描述和参数来自论文 Table 12；但完整 JSON wrapper、默认值、Python regex 行为、稳定排序、行号输出、Markdown heading parser、1 MiB 输出上限、regex 512 字符/1000 ms 限制、逐文件 hash、no-follow 读取、manifest namespace、错误码、coverage/result schema 和 snapshot gate 都是论文未公开时为本实验补充并冻结的工程规则，不能写成作者源码。

独立对抗审查先后发现并关闭了三项真实问题：

1. 只有调用前后整树 hash 时，攻击者可以临时替换文件、让工具读到污染内容，再在 post-check 前恢复；现在每次读取的 payload 必须单独匹配 frozen file hash，因此这种恢复型 TOCTOU 无法产出结果。
2. 未配对 Unicode surrogate 曾会泄漏为原始 `UnicodeEncodeError`；现在 path、pattern、section path 和 coverage path 都要求严格 UTF-8，并把不可信参数稳定映射为结构化 `R1ToolError`。
3. 512 字符以内的畸形 regex 仍可让 `re.compile` 抛出 `RecursionError` 或 `OverflowError`；现在编译和执行阶段均被收口为安全 `invalid_regex`/`regex_timeout` 工具错误，失败后照常执行 post-snapshot 检查。

真实 S1 平铺 store 与真实 S2 四层主题目录产物均已通过同一执行器集成测试；S3 fixture 用于验证 manifest 的嵌套 inventory，但在真实 85-chunk S3 正式发布并通过其 manifest/COMMITTED/trace gate 前，R1 不会把 staging 或 fixture 当作 E5 输入。最终独立 Gate 为 PASS：Evidence + R1 共 50/50、全仓离线测试 152/152、`git diff --check` 均通过。此阶段仍未调用学校 API，也没有生成任何 40 题实验答案；下一阶段是 observation ledger 与 `take_note` 防伪解析器。

## 2026-10-08：R1 阶段 4——Observation Ledger、`take_note` 与可信停止

阶段 4 在隔离 worktree 中完成，未调用学校 API，也未读写正式 S3 进程。新增 `fs_memory_lab/r1_orchestration.py`，把论文四个只读文件工具的结果接到本项目 evidence-only 控制层。这里必须继续区分来源：`view/grep/toc/section_read` 来自 Filesystem 论文 Table 12；`take_note`、`finish_search`、Observation Ledger、证据预算、状态链、全局回退证明与 EvidenceBundle 都是为了统一 R1/R2 Answerer 而增加的 project-defined controlled adaptation，并非论文作者公开的工具或源码。

`take_note` 的模型参数只允许 `observation_ids + path + line_start + line_end`。模型不能传 evidence text、答案、locator、`dia_id`、日期或 speaker。每个成功文件工具结果由本题、本次 episode 的 host 执行入口产生，再得到连续的 `obs-0001...`；裸 `ReadToolResult` 已不能事后写入 ledger。每个 observation 同时带 HMAC execution receipt，绑定 episode ID、题目 hash、完整 StoreSnapshotRef hash、轮次、动作序号与结果 hash。公开 trace 字段可以保存 key ID、receipt body 与 MAC，但不包含 HMAC secret；后续 runner/恢复阶段必须把 secret 放入独立的私有 checkpoint，缺少或错误 secret 时 fail closed，不能退化为只验证公开 SHA。

被选择的证据区间必须由更早 provider round 的成功 `view`、`grep` 或 `section_read` 连续覆盖；目录 `view`、`toc`、失败调用、截断后未返回的 grep 行和 coverage gap 都不能成为证据。Host 随后重读冻结文件，按 manifest 的逐文件 hash 与完整 StoreSnapshot 验证，再由 `build_evidence_item` 生成精确文字与来源。S1/S2 必须选择完整 source-turn block；S3 必须选择带合法 inline `[SxTy]` 的真实事实行。相同文件的重叠/相邻区间按传递闭包确定性合并；完全重复不算进展；范围扩张或桥接会原子替换旧 items。预算只使用明确的 bytes 或 Unicode characters，超限时整项跳过、绝不截断 evidence。

Evidence note state 绑定 question SHA-256 和完整 `StoreSnapshotRef`。每个 `TakeNoteResolution` 绑定题目、先前 observation-ledger hash、selector、prior/output state hash 和完整结果。`ProviderRoundLedger` 在构造、关闭每轮和最终停止时重放全部 `take_note` transition；同一轮多次 notes 必须形成严格状态链。初始 note state 必须为空，不能通过直接 dataclass constructor 预置一条真实 evidence。每轮的 `newly_accepted_evidence_ids` 由经过重放的 resolutions 唯一推导，调用者不能删掉真实进展来提前制造“连续两轮无进展”，也不能塞假 ID 重置计数。

`finish_search` 不能携带答案。`missing_aspects` 冻结为八个非证据标签：`subject_identity`、`event_or_fact`、`time`、`location`、`cause_or_reason`、`sequence_or_relation`、`comparison_or_choice`、`corroborating_evidence`。`evidence_sufficient` 至少需要一项已验证 evidence；absence/no-progress 必须由“先 root survey、后未截断 whole-tree grep”的真实 observations 证明；fallback 完成轮本身不计入 dry rounds，新 evidence 会重置计数，连续两轮无新增后才允许 no-progress stop；budget stop 必须来自被可信重放的 budget-skipped transition。

轮数上限现在是所有构造边界的硬约束，不是停止时才检查的提示：S1=20、S2=20、S3=40，并纳入 canonical limits freeze。达到上限后，observation、take-note resolution、round record 与 direct-constructor ledger 都不能产生 cap+1；只有 host 可以生成 `round_limit` stop。Observation/orchestration protocol 因 episode receipt 升为 v2；论文四工具 schema 及 `take_note/finish_search` 模型 wire schema没有因此改变。

本阶段的对抗回归实际覆盖：cross-question 与同题跨运行 observation rebound、伪造初始 evidence、伪造 budget transition、tampered/cross-snapshot EvidenceItem、答案夹带、任意 caller cap、S1 第 21 轮/S3 第 41 轮、HMAC receipt 篡改、无序 set/dict IDs，以及篡改本轮新增 evidence 统计。真实 S1、真实 S2 nested store 与 formal S3-shaped fixture 使用同一控制层；S3 fixture 仅验证 curated evidence 规则和 Unicode 预算，不冒充尚未发布的正式 S3 artifact。最终 Evidence + 四工具 + orchestration 联合测试为 84/84，全仓离线回归为 186/186，`black --check` 与 `git diff --check` 通过。当前仍没有运行正式 R1 问题；下一阶段才冻结 Prompt 5/6/7 的 published transcription、evidence-only derived prompts 与 hashes，随后实现 Research Agent 状态机。
