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

ReFind 原文对 `turn` 使用了不同定义：一个 user utterance 和对应 assistant response 合为一个 turn。为了避免歧义，本项目不直接沿用这个含混名称，而使用上表的 `source turn` 与 `exchange`。当前计划是：canonical records 始终保持 568 个 source turns；实现 raw-chat ReFind-style 检索时再派生 exchange-level retrieval units，并让每个 exchange 保留其包含的全部 `dia_id` 和 source locators。该派生视图不得改写或删除 canonical records。

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

ReFind 论文没有在 LoCoMo 上实验，其报告范围是 text-only chat history，也没有 URL、caption 或视觉模型的处理规则。因此，将 `blip_caption` 纳入 LoCoMo 上的 ReFind-style 检索同样属于本项目的适配协议。当前已经实现共享 renderer、正式 S1 builder 和正式 S2 store；正式 S3 benchmark builder 与 R2 尚未实现。S1/S2 中 caption 已作为文字写入，URL 仍未被写入或访问。

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

专门的 S2 测试覆盖成功发布、正式30文件集成、输入篡改、分类不完整、provider 中途异常、completion 截断、round limit、畸形 tool calls、内容变化、改名、额外/重复文件、symlink、空目录、Prompt/task/tool-schema freeze、写路径与 S1 隔离、并发锁、密钥错误脱敏、发布阶段回滚和 artifact cross-link 验证。当前全套离线测试为47项，全部通过。

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

当时的顺序设想是：冻结并提交正式 S2 后先实现 ReFind-style R2，再实现 evidence-only R1；R2 仍需先将 exchange 派生规则、奇数 session 的 singleton 处理及 gold `dia_id` 命中规则写成测试。2026-10-06 决定先推进 S3 输入准备，因此该顺序已调整；“不应未经 prompt/runner 冻结就直接运行 S3 管理 LLM”和“不为六个条件分别切一次原始数据”两项约束继续有效。

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

本次只执行了第 1–3 步。还没有创建正式 S3 memory store，没有调用学校 API，也没有用未来 QA 检查或优化 chunks。

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

下一步不是重新切片，也不是立刻跑正式 85 块；应先完成上面第 4 步：逐字核对并冻结 S3 Builder Prompt、LoCoMo locator extension 和固定 user wrapper，再实现只接受本 manifest 的安全 runner。
