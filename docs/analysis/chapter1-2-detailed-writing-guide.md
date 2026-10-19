# 第 1–2 章详细写作指南

## 0. 今天的写作目标

今天要完成的不是结果分析，而是让读者在进入系统和实验章节前，清楚理解四件事：

1. 为什么长期对话 agent 需要外部记忆；
2. 为什么“记忆”不能只理解为更长的上下文窗口；
3. 现有 Filesystem、ReFind 和长期对话评测工作还留下了什么问题；
4. 本研究为什么要比较存储、检索、backbone、双源融合和 Full Context。

第 1 章负责提出问题和研究承诺；第 2 章负责提供概念、文献和研究定位。两章完成后，读者应当自然地产生下一步问题：

> 既然需要联合研究存储、检索和模型能力，那么本研究具体构建了怎样的系统？

这正好过渡到第 3 章“系统设计与方法”。

### 建议篇幅

| 章节 | 长报告版 | 压缩版 | 建议英文词数 |
|---|---:|---:|---:|
| 第 1 章 引言 | 4–5 页 | 2–3 页 | 1,800–2,500 |
| 第 2 章 背景与相关工作 | 6–8 页 | 3–4 页 | 3,000–4,500 |

页数只用于控制重心。第 1 章不能写成文献综述，第 2 章也不能提前变成实验配置说明。

---

# 第 1 章 引言

## 1.1 研究背景

这一节回答：**为什么这个研究问题值得被研究？**

建议使用“应用需求 → 技术矛盾 → 外部记忆系统”的漏斗结构，从广到窄，不要第一段就出现 E1–E7。

### 1.1.1 从单轮问答到长期交互式 Agent

**要讲的内容**

- LLM 应用正从一次性问答走向持续数小时、数天甚至更长时间的 agent 交互；
- 在个人助理、工作协作、客户支持和长期陪伴等场景中，系统需要记住人物、事件、偏好、计划、时间变化和跨 session 关系；
- 长期任务的困难不仅是信息量大，还包括事实分散、表达变化、时间更新和多跳组合。

**推荐段落顺序**

1. 第一段：介绍长期交互相较普通问答的新要求；
2. 第二段：给出一两个抽象例子，例如某项计划跨多个 session 更新，回答需要同时找到旧决定与新变化；
3. 第三段：指出模型如果不能持续访问过去信息，就难以保持一致性和个性化。

**建议引用**

- LoCoMo 论文的研究动机与长期对话设定；
- Filesystem 论文 Introduction 对长期 agent memory 的问题定义；
- 需要时补充一至两篇长期 agent memory 综述或 benchmark 论文。

**不要在这里写**

- 本项目具体用了 60 道题；
- 哪个实验条件得分最高；
- S1、R1、BM25 等实现细节。

### 1.1.2 长上下文窗口不等于长期记忆系统

**要讲的内容**

- 理论上可以把越来越多历史直接放入 context，但“可容纳”不等于“能有效定位和利用”；
- 上下文增长会带来 token 成本、延迟、重复信息、冲突信息和注意力分散；
- 真实长期记忆还需要增量更新、组织、删除、审计和来源追踪，这些不是扩大窗口本身解决的问题；
- 因此 Full Context 是重要对照，但不能被当作天然正确的 oracle。

**推荐段落顺序**

1. 先承认长上下文是一条合理路线；
2. 再说明它解决的是“输入容量”，而外部记忆还要解决“选择、组织、更新和使用”；
3. 最后提出本研究需要同时比较选择性检索和完整上下文。

**建议引用**

- ReFind 对 raw chat 与结构化记忆的动机；
- 长上下文利用或 lost-in-the-middle 类研究；
- 本报告后续引用 Full Context 时使用的方法来源。

**段末过渡**

> 因此，长期记忆问题不能被简化为“给模型更多文本”，而应被视为一个由存储、检索和利用共同构成的系统问题。

### 1.1.3 外部记忆是“存储—检索—利用”的系统

**要讲的内容**

- 外部记忆至少包含三个相互依赖的阶段：如何保存信息、如何找到信息、如何用证据回答；
- 相同信息可以平铺保存、目录化保存，或由 agent 整理为结构化记忆；
- 相同存储也可以由 agent 浏览、词项排序或迭代检索；
- 最终效果由存储表示、检索策略和下游模型能力共同决定。

**本节建议配图**

一张只包含概念层的简图：

```text
Dialogue History
      ↓
Memory Representation
      ↓
Retrieval / Evidence Selection
      ↓
Answer Utilization
      ↓
Quality, Cost and Reliability
```

该图不能提前画入 E1–E7 的全部实现细节；详细系统图留给第 3 章。

**本节收束句**

> 本研究由此把长期记忆视为端到端系统，而不是把存储格式、检索算法或模型能力中的任意一项单独等同于“记忆”。

---

## 1.2 问题陈述

这一节回答：**当前真正没有解决好的问题是什么？**

与 1.1 的区别是：1.1 说明问题重要，1.2 要把问题缩小为能够被实验回答的对象。

### 1.2.1 如何存储：保真、组织和压缩之间的矛盾

**要讲的内容**

- 平铺原始记录保留信息最多，但导航成本高；
- 文件夹或 taxonomy 可以提供路径线索，但未必改善内容级检索；
- agent-curated memory 可以压缩和聚合事实，但可能遗漏限定条件、时间关系或人物语气；
- 因而“结构更整齐”不能自动等同于“回答更准确”。

**应形成的问题**

> 在相同原始信息上，存储组织本身能否改善检索与回答，其作用是否依赖检索方式？

### 1.2.2 如何检索：覆盖、噪声和成本之间的矛盾

**要讲的内容**

- agentic 文件导航灵活，但可能需要多轮浏览和较高 token 成本；
- lexical/ranking retrieval 高效且可控，但依赖 query 表达、索引单元和候选扩展；
- 更多 evidence 可能提高 Recall，也可能加入无关或冲突信息；
- 检索是否成功不能只看最终答案，还要看 gold evidence 是否被找到、是否被保留进 EvidenceBundle。

**应形成的问题**

> 不同检索系统在不同存储表示上是否具有稳定优势，还是存在明显的存储 × 检索交互？

### 1.2.3 如何利用：证据可见不等于答案正确

**要讲的内容**

- 即使检索到完整证据，Answerer 仍可能在人物指代、时间顺序、多跳组合和冲突处理中失败；
- Full Context 即使包含全部原始信息，也可能因上下文过长和噪声而失败；
- 不同 backbone 可能对同一 EvidenceBundle 产生不同答案，也可能采用不同搜索策略；
- 因此必须区分 retrieval bottleneck 与 utilization bottleneck。

**应形成的问题**

> 最终错误究竟来自信息没有保存、证据没有找到、预算没有保留，还是模型没有正确利用？

### 1.2.4 如何评价：单一最终分数不足以解释系统

**要讲的内容**

- Token F1 可复现并适合与 LoCoMo 对齐，但受到措辞和答案长度影响；
- LLM Judge 能评价语义完整性，但自身也有偏差和稳定性问题；
- Evidence Recall 能检查检索过程，却不能代替最终答案质量；
- tokens、calls、latency 和维护成本决定系统是否实际可用。

**问题陈述的最终形式**

建议用一段正式陈述结束：

> 当前缺少一项在相同数据、问题、存储资产和评价协议下，系统地比较存储组织、检索策略、backbone 能力、双源融合与 Full Context，并进一步把最终差异追溯到证据覆盖、证据利用和成本阶段的受控研究。

---

## 1.3 研究缺口

这一节回答：**已有研究已经做了很多，为什么仍然需要本研究？**

写法应是“已有贡献 → 尚未解决 → 本研究如何承接”，不要把相关论文写成做得不够好。

### 1.3.1 存储与检索常被共同改变，组件作用难以分离

**已有工作**

- Filesystem 论文研究 memory store、management agent、search agent、tool harness 和 scale；
- ReFind 研究原始聊天上的 agent-controlled iterative search。

**缺口**

- 不同论文的存储、检索、Answerer 和评测口径不同，不能直接根据两个表格判断哪个组件更有效；
- 当结构化存储和新检索器一起改变时，最终差异无法简单归因于“目录”“摘要”或“BM25”。

**本研究的承接方式**

- 在统一管线中建立 S1/S2/S3 与 R1/R2/R3；
- 用 E1–E4 提供较清晰的存储 × 检索对照；
- 把 E5/E6 明确作为完整 curated-memory 系统，而不冒充纯组件消融。

### 1.3.2 单 Backbone 结果难以区分架构规律和模型特性

**缺口**

- 一个存储或检索方法在单一模型上有效，可能是该模型更会浏览文件、更会改写 query，或更善于利用长证据；
- 只比较总体模型分数，仍不能知道“架构改动的效果”是否跨模型稳定。

**本研究的承接方式**

- 在 Qwen 与 DeepSeek 下运行相同 E1–E7；
- 不只比较模型总分，还比较同一架构 contrast 的方向和幅度。

### 1.3.3 缺少对选择性检索与完整上下文的阶段化诊断

**缺口**

- 如果检索系统答错，不知道完整信息可见后是否能修复；
- 如果 Full Context 也答错，则错误可能不再只是“没找到信息”；
- 仅比较均值不能区分“检索遗漏”和“长上下文利用失败”。

**本研究的承接方式**

- 增加 DeepSeek Full Context；
- 使用同题四象限比较定位信息访问与信息利用边界。

### 1.3.4 结果排名多，过程、错误和成本解释不足

**缺口**

- 只报告最终准确率会掩盖检索覆盖、证据冲突、回答风格和成本差异；
- 系统可能平均分相近，却在失败原因、稳定性和部署成本上完全不同。

**本研究的承接方式**

- 同时报告 P/R/F1、Strict/Partial/Soft、Evidence Recall 和过程成本；
- 采用同题配对、错误链与人工案例复核；
- 最终给出条件化选型，而不是一个脱离场景的总冠军。

**1.3 的段末过渡**

> 上述缺口共同指向同一个需求：需要一套既能控制实验变量、又能解释端到端失败机制的统一比较框架。

---

## 1.4 研究目标

这一节回答：**本研究准备完成什么，而不是准备证明什么？**

目标不能提前写成“证明 S2 更好”之类带有结果倾向的陈述。

### 1.4.1 总体目标

建议写成一段正式目标：

> 本研究旨在构建并评价一个受控的长期对话记忆实验框架，在统一数据、问题、证据接口与评价协议下，研究存储表示、检索策略和 backbone 能力如何共同影响回答质量、证据覆盖和运行成本，并以双源融合与 Full Context 对照进一步定位系统瓶颈。

### 1.4.2 具体目标

建议列出六项，并与后续 RQ 对齐：

1. 构建三种可追溯存储表示；
2. 构建并统一三类检索路径；
3. 在两个 backbone 上完成相同 E1–E7 比较；
4. 使用 Full Context 诊断信息访问与长上下文利用；
5. 联合评价答案、证据、过程和成本；
6. 形成错误归因和实际系统选择建议。

**不要写**

- 尚未分析得到的最终结论；
- 实验运行过程的 checkpoint、batch 数和文件名；
- 过细的模型参数。

---

## 1.5 研究问题

这一节要把第 1.3 的缺口和第 1.4 的目标转成能够由实验回答的问题。正文中最好给一张 `Gap → RQ → Main evidence` 映射表。

### 1.5.1 架构问题：RQ1

> **RQ1：存储表示和检索策略各自带来什么变化，二者是否存在交互？**

解释该问题将主要通过 E1–E4 的同题组件对照，以及 E5/E6 的完整系统比较回答。

### 1.5.2 稳健性问题：RQ2

> **RQ2：这些架构效果能否跨 Qwen 与 DeepSeek 稳定复现？**

强调研究对象是“架构 contrast 是否稳定”，而不只是两个模型谁的平均分更高。

### 1.5.3 机制问题：RQ3–RQ5

- **RQ3：** 双源融合在何时修复错误、何时引入干扰？
- **RQ4：** Full Context 是否优于选择性检索，二者分别暴露什么瓶颈？
- **RQ5：** 错误主要发生在存储、检索、证据打包、回答利用还是长上下文阶段？

说明三者共同负责从“结果差异”深入到“为什么发生”。

### 1.5.4 决策问题：RQ6

> **RQ6：综合质量、成本、稳定性和维护复杂度，哪些条件最值得实际采用？**

强调最终答案应当是场景化建议，而不是无条件总排名。

### 建议的 RQ 映射表

| RQ | 主要实验材料 | 主要证据 |
|---|---|---|
| RQ1 | E1–E6 | 配对质量、Evidence Recall、DID |
| RQ2 | 两个 backbone 的 E1–E7 | CoC、方向一致率、标签转移 |
| RQ3 | E2、E6、E7 | Repair/Harm、证据互补与冲突 |
| RQ4 | DeepSeek E1–E7 与 Full Context | 四象限、质量、上下文与成本 |
| RQ5 | Store、trace、EvidenceBundle、答案 | 错误阶段、转化率、案例复核 |
| RQ6 | 所有正式条件 | Pareto、成本摊销、决策矩阵 |

该表只写“用什么回答”，统计细节留到第 4 章。

---

## 1.6 研究贡献

这一节回答：**相较已有工作，本研究实际增加了什么可复用的知识或方法？**

### 1.6.1 受控实验设计贡献

- 在统一数据和 Answerer 接口下组织存储、检索与融合条件；
- 区分较干净的组件对照与完整系统对照；
- 使存储 × 检索交互能够被显式分析。

### 1.6.2 跨 Backbone 与 Full Context 的经验贡献

- 在两个 backbone 上运行一致的 E1–E7；
- 增加无检索 Full Context 诊断；
- 检查哪些现象跨模型稳定、哪些依赖模型。

### 1.6.3 多层评价与错误诊断贡献

- 联合官方词面分数、独立语义 Judge、gold evidence 和过程成本；
- 构建从 store fidelity 到 evaluation 的错误链；
- 使用同题配对和人工案例避免仅凭均值猜测机制。

### 1.6.4 实践决策贡献

- 比较质量、token、calls、latency、建库和维护成本；
- 为质量优先、成本优先、持续增长和可审计场景提供条件化建议。

**写作提醒**

贡献必须与实际已完成或确定要完成的工作一致。不要把未来工作写成已有贡献，也不要声称完整复现了两篇论文的所有结果。

---

## 1.7 研究范围与边界

这一节主动限制结论范围，让后文更可信。

### 1.7.1 本研究包含的范围

- LoCoMo `conv-50` 的冻结 main-60；
- C1–C4 四类问题；
- S1/S2/S3、R1/R2/R3、E1–E7；
- Qwen 与 DeepSeek 两套端到端 backbone；
- DeepSeek Full Context；
- LoCoMo P/R/F1、独立 Judge、evidence 和成本评价。

### 1.7.2 本研究未覆盖的范围

- 不是 LoCoMo 全部 conversations 的完整复现实验；
- 尚未正式运行 A-Mem、Mem0、图记忆或向量 RAG baseline；
- 尚未模拟数月级持续写入、遗忘和冲突演化；
- 尚未分离检索模型与 Answerer 的完整交叉矩阵；
- Full Context 当前不用于证明跨 backbone 普遍规律。

### 1.7.3 允许的结论强度

- 可以陈述当前 60 题、当前存储快照和模型配置下的同题比较；
- E1–E4 可支持较强的组件和交互解释；
- E5/E6 只能支持完整 curated-memory 系统结论；
- Full Context 只能作为诊断性比较，不能称为理论上限。

**与第 7 章的区别**

- 这里简要声明研究边界；
- 第 7 章再系统讨论这些边界如何影响有效性和推广。

---

## 1.8 报告结构

这一节控制在一至两段，不要重复目录中的每个小标题。

### 1.8.1 章节之间的论证关系

建议按逻辑而非机械列表说明：

- 第 2 章建立长期记忆、文件系统记忆、迭代检索和评价背景；
- 第 3 章说明本研究系统如何构成；
- 第 4 章说明实验如何公平运行和评价；
- 第 5 章按 RQ 分析结果与机制；
- 第 6–8 章分别讨论意义、局限和开放探索；
- 第 9 章总结结论。

### 1.8.2 过渡到第 2 章

最后一句应说明：在介绍本项目系统前，需要先明确现有长期记忆表示、检索和评价方法，以及 Filesystem、ReFind 和 LoCoMo 提供的基础。

---

# 第 2 章 背景与相关工作

## 2.1 LLM 长期记忆的基本问题

这一节回答：**什么是本文所说的长期记忆系统，它包含哪些阶段？**

它应提供后文共用术语，而不是再次重复第 1 章的研究动机。

### 2.1.1 参数记忆、上下文记忆与外部记忆

**要讲的内容**

- 参数记忆存在于模型权重中，部署后难以即时、局部和可审计地修改；
- 上下文记忆是当前 prompt 中可见的信息，会受到窗口、成本和会话边界限制；
- 外部记忆把历史保存到文件、日志、索引、向量库或图结构中，再按需要读回；
- 本研究关注的是以文本为主要载体的外部记忆，不研究重新训练、微调或参数编辑。

**建议引用**

- RAG 对参数与非参数知识的区分；
- MemGPT 或 MemoryAgentBench 对上下文管理和外部记忆能力的分类；
- Filesystem 论文 Introduction 对部署型 agent 外部文件记忆的界定。

**写作边界**

这里只建立术语，不要重复第 1 章“为什么长期记忆重要”的宏观动机，也不要介绍本项目的文件结构。

### 2.1.2 长期记忆的生命周期

**要讲的内容**

- 信息产生：conversation turns、events、preferences、plans；
- 写入：原文保存、抽取、摘要、合并；
- 组织：文件、目录、主题、实体、时间；
- 检索：根据问题定位候选证据；
- 使用：Answerer 组合证据并生成答案；
- 维护：增量更新、冲突、遗忘、重组和审计。

**建议图表**

一张 memory lifecycle 图。与第 1 章概念图相比，这张图可以加入写入和维护反馈环，但仍不放项目参数。

### 2.1.3 存储、检索和利用是不同问题

**要讲的内容**

- `storage fidelity`：正确事实是否被保留；
- `retrieval coverage`：相关事实是否被找到并送入证据包；
- `utilization`：模型是否正确理解、组合和表达；
- 三个阶段可以独立失败，也可能相互放大。

**应给出的例子**

用一个抽象的时间更新问题说明：事实可以存在于 store 中但检索不到；也可以已经检索到但 Answerer 仍使用旧日期。不要使用会泄露正式题目答案的具体案例。

### 2.1.4 长期记忆系统的主要设计轴

建议归纳为五个轴：

1. fidelity vs compression；
2. flat vs hierarchical organization；
3. passive retrieval vs agent-controlled retrieval；
4. selective evidence vs full context；
5. quality vs build/query/maintenance cost。

这五个轴将成为第 2.2–2.7 节的组织线索。

---

## 2.2 外部记忆的主要表示形式

这一节回答：**相同历史信息可以被存成什么形式，各自提供什么 inductive bias？**

### 2.2.1 原始对话与日志式存储

**要讲的内容**

- 保留原始 wording、speaker、时间和完整上下文；
- 适合审计和重新解释；
- 代价是重复、冗长、跨 session 事实分散和定位困难；
- raw log 本身不是“没有结构”，仍可有 session、turn 和 timestamp 层级。

**与本项目的关系**

只在段末说明它对应本研究 S1/S2 的信息来源；具体文件布局留给第 3 章。

### 2.2.2 文件系统式记忆

**要讲的内容**

- 文件名、目录路径、Markdown heading 和 metadata 可以成为检索线索；
- agent 可以用 list、grep、view 等工具主动导航；
- 文件系统的价值可能来自可编辑、可追溯、可分层和与工具生态兼容；
- hierarchy 也可能只是表面整齐，如果 searcher 不会利用结构，则不一定提高回答。

**建议引用**

- Filesystem 论文 §2.1–§2.2；
- 论文中的 memory store、harness 与 agent role 定义。

### 2.2.3 Agent-Curated 或摘要式记忆

**要讲的内容**

- 管理 agent 可以把分散信息按人物、主题或事件合并；
- 优点：压缩、去重、直接定位、支持更新；
- 风险：细节丢失、时间关系被扁平化、主观语气改变、过期事实继续存在；
- 写入质量和维护策略会成为新的系统变量。

**与本项目的关系**

说明 S3 属于这一类，但不要在本节写 chunk 数、prompt 或实际文件结构。

### 2.2.4 向量、图与其他结构化记忆

**要讲的内容**

- Vector RAG：通过 embedding similarity 检索；
- graph memory：显式建模实体与关系，适合关系遍历但维护复杂；
- memory framework：可能组合摘要、向量、图和规则；
- 这些方法用于说明设计空间，不代表已经纳入本研究正式 baseline。

**建议相关工作**

- A-Mem、Mem0 及代表性 graph/vector memory 工作；
- 引用时说明它们和本项目在写入、索引、更新和 evaluation protocol 上不可直接横向比较。

### 2.2.5 表示形式比较与本研究选择

建议给出一张概念比较表：

| 表示形式 | 保真度 | 压缩 | 可导航性 | 更新难度 | 主要风险 |
|---|---|---|---|---|---|
| Raw logs | 高 | 低 | 中 | 低 | 冗长、分散 |
| Foldered raw files | 高 | 低 | 高 | 中 | taxonomy 未被利用 |
| Curated memory | 中到高 | 高 | 高 | 高 | 遗漏、失真、陈旧 |
| Vector memory | 取决于源 | 中 | 相似度检索 | 中 | semantic mismatch |
| Graph memory | 关系导向 | 中 | 关系遍历 | 高 | 构图与维护成本 |

表后说明本研究为什么选择前三类形成受控主线，而把向量和图方法留作相关工作与未来 baseline。

---

## 2.3 记忆检索方法

这一节回答：**当信息已经被保存后，系统如何决定把什么交给 Answerer？**

### 2.3.1 Agentic 文件导航与文本搜索

**要讲的内容**

- LLM 根据问题决定列目录、搜索字符串、打开文件或继续探索；
- `grep` 是定位匹配文本的工具，不等于检索策略本身；真正策略由 agent 的关键词、路径选择和多轮观察构成；
- 优点是灵活、可解释、能利用目录；
- 风险是轮数、token 和行为稳定性。

**建议引用**

- Filesystem 论文 §2.2、§3 和 search prompt 附录；
- 只介绍公开思想，项目新增的 evidence-only 与统一 Answerer 设计留到第 3 章。

### 2.3.2 词项排序与迭代式检索

**要讲的内容**

- BM25 等方法根据完整 query 或 query terms 对检索单元进行排序；
- unit 可以进一步聚合为 session/group，并通过 RRF 等方法融合层级排名；
- LLM controller 可以在看到候选后改写 query、筛选证据、加时间过滤或决定停止；
- 与 one-shot search 相比，iterative retrieval 允许依据中间结果调整方向，但增加调用和状态管理。

**建议引用**

- ReFind 的 search engine design、iterative actions 和主要 ablation；
- BM25 与 RRF 的原始或标准方法文献。

### 2.3.3 多源检索与证据融合

**要讲的内容**

- 多源系统可能联合 raw logs、curated memory、vector index 或其他来源；
- 潜在收益来自证据互补，风险来自重复、冲突、时效不一致和上下文膨胀；
- 必须区分“分别检索后融合证据”和“新的联合检索算法”。

**与本项目的关系**

段末指出 E7 属于已有两路证据的固定融合；具体父系统、去重和预算规则留到第 3 章。

### 2.3.4 Full Context 与长上下文回答

**要讲的内容**

- Full Context 取消显式检索，把完整历史交给模型；
- 它避免 search miss，但将选择压力转移给模型内部注意力和推理；
- 成本随历史增长，且可能受到位置、重复和冲突影响；
- 因而它既是实际方案，也是诊断 selective retrieval 的重要 baseline。

**写作边界**

不要说 Full Context 是存储方法、E8 或理论上限。

### 2.3.5 检索方法比较框架

建议用一张表总结：

| 方法 | 谁决定 query/路径 | 检索单元 | 是否迭代 | 能否利用目录 | 主要成本/风险 |
|---|---|---|---|---|---|
| Agentic filesystem | LLM agent | 文件/段落 | 是 | 是 | rounds、token、随机性 |
| Ranked retrieval | Query + ranker | exchange/fact | 可迭代 | 取决于 adapter | query mismatch |
| Multi-source fusion | 多路系统 | 多 EvidenceBundle | 取决于设计 | 间接 | 重复与冲突 |
| Full Context | 无外部选择 | 全部历史 | 否 | 不适用 | 长输入与注意力 |

这张表只比较检索范式，不出现实际实验分数。

---

## 2.4 Filesystem-Based Memory 论文

这一节不是普通摘要，而要回答：**它提供了什么方法论基础，我们继承了什么，仍有哪些问题需要研究？**

### 2.4.1 Memory Store、Tool Harness 与 Agent Roles

**要讲的内容**

- memory store 是 agent 可读写、可组织的外部文件系统；
- harness 约束 agent 如何通过工具访问 store；
- management/search/execution roles 分别对应写入维护、检索和任务执行；
- memory shape 的效果不能脱离 searcher、executor 和工具环境理解。

**原文位置**

- §2.1 The Memory Store；
- §2.2 Tool Harness and Agent Roles；
- §2.3 Two Instantiations, One Store。

### 2.4.2 论文的实验轴与控制逻辑

**要讲的内容**

- §2.4 明确 what is held fixed and what varies；
- 论文研究 builder/memory shape、stream scale、tool harness 和模型能力；
- 其核心方法论是每次改变一个主要轴，其余保持一致；
- 结果按 RQ 组织，而非只按指标或系统排名。

**为什么重要**

这正是本报告第 3–5 章分工和受控 contrast 的主要结构参考。

### 2.4.3 主要发现与未解问题

**要讲的内容**

- 总结论文关于 memory organization、retrieval、backbone capability、growth 和 harness 的条件化发现；
- 强调组织更复杂并不自动产生更高任务质量；
- store shape、agent 能力、工具和规模存在交互；
- 论文也提出更长时间跨度、store health 和主动诱导 hierarchy 等开放问题。

**写作要求**

- 只写原文真正支持的结论；
- 不把论文某个 benchmark 的数值直接与本项目分数横向比较；
- 具体一致/不一致趋势留到第 6 章 Discussion。

### 2.4.4 本研究的继承、改变与扩展

建议用三列说明：

- **继承：** filesystem store、agent roles、原始/目录化/curated memory 思想、agentic search；
- **改变：** 统一 EvidenceBundle 和 Answerer、冻结 main-60、校园 API backbone 和本项目审计；
- **扩展：** ReFind-style retrieval、双 backbone、E7 融合、Full Context、双评价与错误链。

结尾明确：本研究以论文为主要方法来源，但不是逐字或全条件复现。

---

## 2.5 ReFind 与迭代式原始聊天检索

这一节回答：**为什么不先重写记忆，而是让 agent 在原始聊天上主动搜索？**

### 2.5.1 原始聊天检索的动机

**要讲的内容**

- 预先结构化或摘要可能改变、遗漏信息；
- raw chat 保留完整来源和时间上下文；
- 核心挑战从“如何写 memory”转成“如何在长日志中高效搜索”。

### 2.5.2 两级排序与迭代搜索

**要讲的内容**

- exchange-level BM25 产生候选；
- session/group 聚合与 RRF 提供较高层排序；
- Top-k 和邻近扩展恢复局部对话上下文；
- LLM 在最多若干 iterations/actions 中生成或修改 query、选择证据并停止。

还要明确区分三个阶段：长期记忆写入、当前问题的临时 note、最终回答。搜索阶段可以通过 note-taking 保留当前问题的证据，`finish_search` 只表示检索结束；最终答案由之后的 Answerer 根据 notes/EvidenceBundle 生成。临时 note 不会反向改写长期 memory，结束搜索也不等于已经给出最终答案。

这里只讲论文层面的机制。分词器、参数、Top-5、±2、action cap 等本项目具体实现放第 3–4 章。

### 2.5.3 ReFind 的经验结论与成本视角

**要讲的内容**

- 论文如何比较 raw-chat search 与结构化 memory；
- iterative retrieval、检索组件和资源成本如何被分析；
- 说明原始聊天检索可以成为结构化记忆的竞争性替代，但效果依赖 query、模型和 benchmark。

具体表格位置可引用 ReFind 的 search engine design、主要结果表与 ablation 表。

### 2.5.4 本研究的 ReFind-Style 适配边界

**要讲的内容**

- R2 在 S1/S2 上保留 raw-chat、exchange/session、BM25、group aggregation、RRF 与 iterative controller 的核心思想；
- R3 把相同核心适配到 S3 的 fact/H2 topic 结构；
- S2 路径处理、LoCoMo 映射、EvidenceBundle 和 R3 adapter 属于本项目设计；
- 因此应称 ReFind-style 或 ReFind-inspired，而不是声称作者原文提出了 R3。

### 2.5.5 Filesystem 与 ReFind 的互补关系

用一段话明确：

- Filesystem 更强调 memory store、组织、维护和工具化访问；
- ReFind 更强调在 raw chat 上的 agent-controlled iterative retrieval；
- 本研究把二者放入统一矩阵，是为了研究“怎么存”与“怎么找”的交互，而不是判定哪篇论文整体更好。

---

## 2.6 长期对话评测与 LoCoMo

这一节回答：**本研究用什么任务检验记忆系统，为什么这些题能暴露不同失败？**

### 2.6.1 LoCoMo 的数据结构

**要讲的内容**

- 多 session、长时间跨度的对话；
- speaker、日期、文本、图片 caption 等来源；
- question、gold answer 与 evidence annotations；
- 它提供了从答案回到原始对话证据的可能。

### 2.6.2 问题类别与能力要求

先说明 LoCoMo 官方还包含 adversarial 类别，再介绍本项目正式实验使用的 C1–C4：

- multi-hop：组合多条证据；
- temporal：理解时间和变化；
- open-domain：结合对话事实与外部常识；
- single-hop：定位直接事实。

Adversarial 类别作为 benchmark 设计背景简要解释即可；本项目为何不纳入及正式题数放第 4.2，而不是在这里展开。

重点说明不同题型可用于解释机制，但本研究主结论仍基于统一 60 题，而不是把小类别单独当作主要实验。

### 2.6.3 Gold Answer、Gold Evidence 与评价边界

**要讲的内容**

- gold answer 支持自动答案评分；
- gold evidence 通常以来源 turn/dia ID 标注，可用于 Evidence Recall；
- gold evidence 可能不完备，且不是每道题都适合相同的 evidence 评价；
- benchmark QA 表现不能完整代表真实长期记忆维护能力。

### 2.6.4 为什么选择 LoCoMo

说明选择理由：长对话、可追溯 evidence、多种题型、已有研究可比较。随后简要说明局限：一个 conversation、main-60 和固定快照不能代表全部 LoCoMo 或真实数月记忆。

具体题数、抽样和冻结规则放第 4.2。

---

## 2.7 评价长期记忆系统的方法

这一节回答：**“回答得好”与“系统做得好”分别需要哪些指标？**

### 2.7.1 Token Precision、Recall 与 F1

**要讲的内容**

- Precision 反映候选答案中的词有多少得到 gold 支持；
- Recall 反映 gold 内容被覆盖多少；
- F1 平衡二者；
- 它们可重复、成本低，但对同义改写、措辞和答案长度敏感。

本节解释概念，不需要给本项目实际分数；具体 category-aware 计算方式放第 4.7。

### 2.7.2 LLM-as-Judge 的语义评价

**要讲的内容**

- Judge 可判断语义是否完整正确、部分正确或错误；
- Strict 关注完整正确，Soft 给 partial 部分权重；
- Judge 能缓解词面不一致，但受模型偏好、prompt 和重复判定稳定性影响；
- 独立于回答 backbone、匿名化条件可以减少明显偏差。

### 2.7.3 Evidence-Level 评价

**要讲的内容**

- Any-hit：至少找到一条 gold evidence；
- All-hit：所需 gold evidence 是否全部覆盖；
- Evidence Recall：命中比例；
- evidence 指标帮助区分检索失败和利用失败，但 gold evidence 的缺失会限制解释。

### 2.7.4 过程、效率与可靠性指标

**要讲的内容**

- 输入/输出 token、model calls、rounds/actions、tool calls、latency；
- 一次性建库成本与每题查询成本；
- 失败、重试和恢复成本；
- store size、文件数、层级等描述性 store metrics。

强调 R1 round 与 R2/R3 action 不是同一种单位，不能只比较数值大小。

### 2.7.5 为什么需要多视角评价

建议用一张“指标—回答的问题—不能回答什么”表：

| 指标 | 主要回答 | 不能单独回答 |
|---|---|---|
| Precision/Recall/F1 | 词面匹配与冗余/遗漏 | 完整语义正确性 |
| Strict/Soft | 语义完整性 | 检索为什么失败 |
| Evidence metrics | 检索覆盖 | Answerer 是否正确利用 |
| Cost/process | 效率与复杂度 | 质量是否足够 |

结尾提出本研究采用多层评价，是为了从排名走向机制解释和系统决策。

---

## 2.8 本研究定位与差异

这一节是第 2 章最重要的收束，回答：**综合已有工作，本研究处在什么位置？**

### 2.8.1 相关工作比较矩阵

建议制作正式表格：

| 研究 | 主要问题 | 存储 | 检索 | Backbone 比较 | Full Context | 评价 | 过程/错误分析 |
|---|---|---|---|---|---|---|---|
| Filesystem | memory organization / sustainability | raw、foldered、curated | filesystem agent | 有能力轴 | 非本项目同款 | quality + cost + shape | 部分错误与增长分析 |
| ReFind | raw-chat agent search | raw chat | BM25 + iterative controller | 按论文设置 | 作为相关比较填写 | answer + retrieval + cost | ablation / process |
| LoCoMo | 长期对话记忆评测 | benchmark conversation | 不规定 | 多模型评测 | 取决于 baseline | QA + evidence | benchmark error categories |
| 本研究 | 存储 × 检索 × backbone | S1/S2/S3 | R1/R2/R3 + E7 | Qwen/DeepSeek | DeepSeek FC | 词面 + Judge + evidence + cost | 阶段错误链 + 人工复核 |

表中 Filesystem、ReFind 和 LoCoMo 的描述必须回到原文核对，不凭印象填数。

### 2.8.2 从文献缺口到本研究设计

逐条对应：

- 存储与检索难分离 → E1–E4 与 DID；
- structured vs raw 难直接比较 → 统一 EvidenceBundle 和 Answerer；
- 单 backbone 结论不稳 → 双 backbone E1–E7；
- 检索遗漏与利用失败难区分 → gold evidence + Full Context；
- 排名缺少机制 → error chain + human review；
- 高分未必可部署 → quality–cost analysis。

这里只说明设计逻辑；具体系统组件放第 3 章，统计方法放第 4 章。

### 2.8.3 本研究相对两篇核心论文的边界

必须明确三点：

1. 本研究借鉴 Filesystem 的 store、agent role 和 harness 思想，但改变为统一证据收集后再由共享 Answerer 回答；
2. 本研究在原始聊天上实现 ReFind-style 核心，并对 curated memory 做项目级适配，不声称完全复现所有原实验；
3. 本研究关注统一实验矩阵中的相互作用与诊断，而不是复刻两篇论文的完整排行榜。

### 2.8.4 过渡到第 3 章

建议最后一段这样组织：

1. 现有研究说明存储形状、搜索能力、模型和上下文规模都可能影响记忆效果；
2. 仍需要一套统一、可追溯、可比较的系统；
3. 下一章将介绍本研究如何从同一份对话构建 S1–S3，如何实现 R1–R3、E1–E7、统一 Answerer 与 Full Context。

---

# 3. 两章之间如何避免重复

| 内容 | 第 1 章 | 第 2 章 | 第 3/4 章 |
|---|---|---|---|
| 为什么长期记忆重要 | 重点提出 | 不重复动机 | 不写 |
| 存储/检索/利用概念 | 概念性提出 | 系统定义与文献 | 具体实现 |
| Filesystem/ReFind | 用于指出缺口 | 系统综述与比较 | 本项目如何实现/适配 |
| Main-60 | 只声明范围 | 解释 LoCoMo | 具体抽样、题数、冻结 |
| E1–E7 | 只为解释贡献/RQ简述 | 不展开参数 | 完整映射和配置 |
| 评价指标 | 说明为何需多视角 | 解释指标思想 | 给公式、实现与统计 |
| 实际分数 | 不写 | 不写 | 第 5 章才写 |

---

# 4. 今天的推荐写作顺序

不要机械从 1.1 开始写。更高效的顺序是：

1. 先写 **1.2 问题陈述**，确定研究真正要解决什么；
2. 写 **1.3 研究缺口**，把 Filesystem、ReFind 和现有评价的空白接上；
3. 写 **1.4–1.6 目标、RQ 与贡献**，确保三者一一对应；
4. 再回写 **1.1 背景**，只保留能把读者带到问题陈述的材料；
5. 写 **1.7–1.8 边界和结构**；
6. 第 2 章优先写 **2.4 Filesystem** 与 **2.5 ReFind**；
7. 再写 **2.2 存储表示**、**2.3 检索方法**，把两篇论文放回更广的设计空间；
8. 写 **2.6 LoCoMo** 与 **2.7 评价**；
9. 最后完成 **2.1 基本概念** 和 **2.8 研究定位**，统一术语并形成过渡。

---

# 5. 今天的完成标准

第 1–2 章初稿完成时，应通过以下检查：

- [ ] 第 1 章可以用一句话说清问题、缺口、目标和贡献；
- [ ] 六个 RQ 都能追溯到一个明确研究缺口；
- [ ] 贡献没有把未来工作或尚未完成的分析写成成果；
- [ ] 第 2 章不是论文 A 摘要加论文 B 摘要，而是围绕存储、检索、模型和评价形成比较；
- [ ] Filesystem、ReFind、LoCoMo 与本项目的继承和差异均被明确标注；
- [ ] Full Context 被正确描述为无检索诊断基线，而非存储方式或 oracle；
- [ ] 没有拆分 60 题的来源，所有主叙述都使用统一 main-60；
- [ ] 没有提前写第 5 章的具体结果或最终赢家；
- [ ] 所有方法性数字都准备在第 3–4 章展开，而不是挤进背景；
- [ ] 每节结尾都自然推动下一节，而不是孤立文献笔记；
- [ ] 引用占位已标出，并准备回到原文核对章节、页码和表格；
- [ ] 第 2.8 最终能够自然引出第 3 章系统设计。

---

# 6. 优先参考材料

- [Main-60 完整报告框架目录](main60-complete-report-outline.md)
- [Filesystem × ReFind 实验完整解释](../explanations/end-to-end-experiment-explanation.md)
- [Main-60 三系统结果分析框架](main60-three-system-results-analysis-framework.md)
- [Filesystem 论文原文](../../papers/primary/filesystem-based-memory-for-llm-agents.pdf)
- [ReFind 论文原文](../../papers/primary/when-your-agent-opens-the-chat-app-refind.pdf)
- [LoCoMo 论文原文](../../papers/related/evaluating-very-long-term-conversational-memory-of-llm-agents.pdf)
- [Filesystem 论文配置对齐记录](../reproduction/filesystem-paper-parity.md)
- [R2 Raw 正式检索协议](../reproduction/r2-raw-protocol.md)
- [R3 Curated 设计与溯源](../reproduction/r3-curated-design-and-provenance.md)

使用顺序应为：先读论文原文确定论点与引用，再用本地复现文档核对本项目到底继承、改变或扩展了什么。

---

# 7. 核心引用地图

| 文献 | 主要使用位置 | 优先核对内容 |
|---|---|---|
| Filesystem-Based Memory | 1.1、1.3、2.1–2.4、2.7–2.8 | §2 系统与角色、§2.4 固定/变化变量、§3 实验设置、§4 RQ1–RQ5、Appendix A/C/D |
| ReFind | 1.1–1.3、2.3、2.5、2.8 | raw-chat 动机、search engine design、iterative actions、主要结果与 ablation、prompt/trace |
| LoCoMo | 1.1、2.6、2.7、2.8 | benchmark 动机、数据构成、QA 类别、gold answer/evidence、long-context 与 retrieval 结果 |
| MemoryAgentBench | 2.1–2.3 | memory-agent 能力分类与长期交互评价 |
| Retrieval vs. Utilization | 1.2、1.3、2.1、2.7 | 检索失败和利用失败的区分与诊断方法 |
| Long-context utilization | 1.1、1.3、2.3 | lost-in-the-middle、噪声、位置和上下文长度问题 |
| RAG、MemGPT、MemoryBank、Mem0、A-Mem、GraphRAG 等 | 2.1–2.2 | 作为设计类别代表，避免逐篇流水账 |

正式写作时，每个经验性结论都必须回到论文原文核对章节、表格和页码；本地说明文档只能帮助确认本项目实现边界，不能替代原论文引用。
