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

ReFind 论文没有在 LoCoMo 上实验，其报告范围是 text-only chat history，也没有 URL、caption 或视觉模型的处理规则。因此，将 `blip_caption` 纳入 LoCoMo 上的 ReFind-style 检索同样属于本项目的适配协议。当前已经实现共享 renderer 和正式 S1 builder；S2、正式 S3 benchmark builder 与 R2 尚未实现。S1 中 caption 已作为文字写入，URL 仍未被写入或访问。

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

## 下一步

以已经通过 hash 验证的 S1 为不可变母版实现 S2：只允许把 30 个完整文件移动进主题目录，文件名和文件字节都不能改变，并输出 `S1_path -> S2_path` 映射。此时不应先运行 S3 管理 LLM，也不应为六个条件分别切一次原始数据。实现 ReFind-style R2 前还需将 exchange 派生规则、奇数 session 的 singleton 处理及 gold `dia_id` 命中规则写成测试。
