# Main-60 三系统结果分析框架与报告写作地图

本文档是 60 题正式实验的 Results / Analysis 主框架。它在原有 E1–E7 分析地图上加入第二个 backbone 和 Full Context baseline，用于回答三个层层递进的问题：不同存储与检索设计是否有效，这些效果是否跨模型稳定，以及当模型直接看到全部原始上下文时，选择性记忆检索还提供什么价值。

报告不应写成 E1 到 E7 的实验流水账，也不应只给三套系统排总榜。主线应从“总体表现”进入“组件效应”，再检查“跨模型稳定性”，随后用“双源融合和 Full Context”扩大证据范围，最后解释“错误发生在哪里、质量提升付出多少成本”。

这份框架取代旧 main-40 文档作为后续分析工作的主入口；旧文档继续保留为历史记录。

## 1. 分析对象与边界

### 1.1 数据范围

- 数据来源：LoCoMo `conv-50`；
- 测试集：冻结的 main-60，共 60 道题；
- 类别分布：C1 multi-hop 13 题、C2 temporal 13 题、C3 open-domain 7 题、C4 single-hop 27 题；
- Model 1：60 题 × E1–E7，共 420 个候选答案；
- Model 2：60 题 × E1–E7，共 420 个候选答案；
- Full Context：60 题 × 1 个无检索条件，共 60 个候选答案；
- 总计：900 个候选答案，均采用同一套 LoCoMo 评分口径和同一个匿名 LLM Judge 口径。

后续所有主分析都把冻结的 main-60 作为一个完整测试集，不再按题目加入时间或早期/新增来源拆分。只有 LoCoMo 的 C1–C4 题型可以作为机制解释的分层变量，主结论仍以全部 60 题为准。

### 1.2 三套实验系统

| 系统 | 回答与检索 backbone | 输入方式 | 条件数 | 候选答案数 |
|---|---|---|---:|---:|
| Model 1 | Qwen 3.8 27B | S1/S2/S3 与 E1–E7 | 7 | 420 |
| Model 2 | DeepSeek V4.1 Flash | 与 Model 1 相同的 S1/S2/S3 与 E1–E7 | 7 | 420 |
| Full Context | DeepSeek V4.1 Flash 模型家族 | 每题直接输入完整 30-session 原始上下文，不检索 | 1 | 60 |

这里应称为“三套实验系统”，而不是三个独立模型。Model 1 和 Model 2 是两种 backbone 下的 E1–E7 系统；Full Context 使用 DeepSeek 家族，但它改变的是上下文提供方式，不是新增一种存储或检索算法。

Model 2 E1–E7 的实际 served identifier 为 `deepseek-v4.1-flash`，Full Context 为 `deepseek-v4.1-flash-1017`。两者适合做同模型家族下的强描述性比较，但不能写成严格的“只改变检索方式”因果消融。

### 1.3 E1–E7 条件

| 条件 | 存储 | 检索 | 主要识别对象 |
|---|---|---|---|
| E1 | S1：平铺原始 session | R1：agentic 文件检索 | 原始文件基线 |
| E2 | S1：平铺原始 session | R2：ReFind-style 原始聊天检索 | S1 上的增强检索 |
| E3 | S2：文件夹化原始 session | R1 | 目录组织对 R1 的影响 |
| E4 | S2：文件夹化原始 session | R2 | 目录与增强检索的组合 |
| E5 | S3：LLM 整理记忆 | R1 | curated filesystem 系统 |
| E6 | S3：LLM 整理记忆 | R3：适配 curated memory 的检索 | curated memory 上的增强检索 |
| E7 | E2 原始证据 + E6 整理证据 | 固定融合，不重新检索 | 双源互补与干扰 |

E1–E4 构成最接近干净实验的 `2 storage layouts × 2 retrieval methods` 设计。E5/E6 不是这个 2×2 的自然延伸：S3 同时改变内容与组织，E6 又使用适配后的 R3，因此只能称为完整 curated-memory 系统对照，不能把差异单独归因于“文件夹”或“摘要”。

### 1.4 Full Context 的角色

Full Context 每题接收相同的 30 个原始 sessions，共 568 turns、约 108,960 字符；不使用检索、摘要、16,000 字符 EvidenceBundle 或 E1–E7 条件。它回答的是：如果模型直接看到全部原始信息，选择性记忆检索是否仍然必要，以及检索系统的错误有多少来自“信息不可见”。

它不是：

- 第八个检索条件；
- 一种新的存储方式；
- Evidence Recall 等于 1 的检索器；
- 理论 oracle 或必然正确的上界。

Full Context 的 `source coverage=100%` 只是输入覆盖率由设计保证。模型仍可能无法定位、组合或正确使用长上下文中的信息。

## 2. 评分口径与分析单位

### 2.1 主要质量指标

| 层次 | 指标 | 用途 |
|---|---|---|
| 官方主指标 | LoCoMo category-aware token/stem F1 | 与 LoCoMo 和相关论文进行可重复比较 |
| 词面诊断 | Token Precision、Token Recall | 分析回答冗长、遗漏和词面贴合程度 |
| 语义主指标 | Judge Strict Accuracy | 回答是否完整正确 |
| 语义敏感性指标 | Judge Partial Rate、Soft Semantic Score | 区分部分正确与完全错误 |
| 检索指标 | Evidence Recall、Any-hit、All-hit | 只用于 E1–E7，定位检索覆盖问题 |
| 过程与成本 | tokens、model calls、latency、rounds/actions、cap、budget skip | 判断效果是否值得其成本 |

Precision/Recall 是逐题 token-overlap 诊断值的宏平均；F1 是官方类别感知逐题分数的平均。因此不能用表中的聚合 Precision 和 Recall 重新计算 F1。

Judge 对同一条答案只给一个 `correct / partial / incorrect` 标签：

- `Strict = correct / n`；
- `Partial Rate = partial / n`；
- `Soft = (correct + 0.5 × partial) / n`。

Partial Rate 是标签构成，不是越高越好的独立质量指标。Judge 使用独立于回答模型的 GLM 5.3 Flash，并且看不到模型、条件、存储、检索、成本和 token-F1。

### 2.2 正确的统计单位

900 个答案不是 900 个独立样本。同一道题在多个条件和模型下被重复回答，主统计单位必须是 `question_id`：

- 组件比较使用同题配对差值；
- backbone 比较使用同题、同条件配对；
- Full Context 与 E1–E7 使用同题配对；
- bootstrap 必须按题重采样，不能把 900 行当成相互独立；
- 类别分层可以在题目层进行，但 C3 只有 7 题，只能用来解释机制。

即使使用 question-level bootstrap，当前仍只有一个 conversation。置信区间只描述这 60 道题上的题目层不确定性，不能代表跨 conversation 的总体不确定性。

## 3. 当前结果地图

### 3.1 三套系统总体快照

| 系统 | n | Precision | Recall | 官方 F1 | Judge Strict | Partial Rate | Judge Soft |
|---|---:|---:|---:|---:|---:|---:|---:|
| Model 1 / Qwen，E1–E7 池化 | 420 | **0.3411** | 0.6774 | **0.3972** | 0.7262 | 0.0714 | 0.7619 |
| Model 2 / DeepSeek，E1–E7 池化 | 420 | 0.1957 | 0.6884 | 0.2636 | 0.7119 | 0.0881 | 0.7560 |
| Full Context / DeepSeek | 60 | 0.1571 | **0.7395** | 0.2445 | **0.7667** | 0.1167 | **0.8250** |

Model 1/2 的“总体”是七个备选条件的池化描述，不是一个可部署的单一系统。因此这张表只用于建立结果地图，正式机制比较必须回到同题、同条件的配对分析。

Judge 标签计数为：Model 1 `305 correct / 30 partial / 85 incorrect`，Model 2 `299 / 37 / 84`，Full Context `46 / 7 / 7`。

### 3.2 E1–E7 条件级快照

| Backbone | 条件 | Precision | Recall | F1 | Strict | Partial | Soft |
|---|---|---:|---:|---:|---:|---:|---:|
| Qwen | E1 | 0.3381 | 0.6565 | 0.3949 | 0.7167 | 0.1000 | 0.7667 |
| Qwen | E2 | 0.3606 | 0.6411 | 0.4031 | 0.6667 | 0.1000 | 0.7167 |
| Qwen | E3 | 0.3759 | 0.7091 | **0.4411** | 0.7500 | 0.0833 | 0.7917 |
| Qwen | E4 | 0.3413 | 0.6542 | 0.3960 | 0.7000 | 0.0500 | 0.7250 |
| Qwen | E5 | 0.3324 | **0.7472** | 0.3948 | **0.7833** | 0.0667 | **0.8167** |
| Qwen | E6 | 0.3209 | 0.6736 | 0.3813 | 0.7333 | 0.0500 | 0.7583 |
| Qwen | E7 | 0.3181 | 0.6605 | 0.3691 | 0.7333 | 0.0500 | 0.7583 |
| DeepSeek | E1 | **0.2345** | 0.7003 | **0.3013** | **0.7500** | 0.1167 | **0.8083** |
| DeepSeek | E2 | 0.1720 | 0.7023 | 0.2455 | 0.7000 | 0.0167 | 0.7083 |
| DeepSeek | E3 | 0.2315 | 0.6824 | 0.2971 | 0.7000 | 0.1167 | 0.7583 |
| DeepSeek | E4 | 0.1630 | 0.6504 | 0.2314 | 0.6667 | 0.0833 | 0.7083 |
| DeepSeek | E5 | 0.1930 | **0.7389** | 0.2604 | **0.7500** | 0.1000 | 0.8000 |
| DeepSeek | E6 | 0.1630 | 0.6084 | 0.2240 | 0.6667 | 0.0833 | 0.7083 |
| DeepSeek | E7 | 0.2128 | 0.7364 | 0.2854 | **0.7500** | 0.1000 | 0.8000 |

这些均值只用于提出需要检验的现象：Qwen 的词面 F1 明显更高，但两种 backbone 的 Judge 总体接近；条件冠军会随 backbone 和指标改变；Full Context 的语义分数高，但词面 Precision 和 F1 不高。原因必须通过逐题配对、答案长度、证据覆盖和错误案例验证，不能仅凭均值推断。

## 4. 报告的总体分析逻辑

Results / Analysis 应按以下顺序展开：

1. **结果层：** 三套系统表现怎样，token 指标与语义指标是否一致；
2. **组件层：** 存储组织、检索策略和双源融合分别改变了什么；
3. **稳健性层：** 组件效果在 Qwen 和 DeepSeek 上是否方向一致；
4. **诊断层：** Full Context 能否修复选择性检索遗漏，又会暴露什么长上下文问题；
5. **机制层：** 错误发生在存储、检索、打包、回答利用还是融合；
6. **决策层：** 在质量、成本和运行复杂度之间应选择哪个 operating point。

后续六个 RQ 对应这条主线。

## 5. RQ1：存储表示与检索策略各自贡献什么，二者是否交互？

### 5.1 核心对照

| 问题 | Qwen 对照 | DeepSeek 对照 | 可以识别什么 |
|---|---|---|---|
| 文件夹组织在 R1 下是否有用 | E3 − E1 | E3 − E1 | 正文近似不变时，目录导航的增量 |
| 文件夹组织在 R2 下是否有用 | E4 − E2 | E4 − E2 | 排名检索存在时，路径组织是否仍有增量 |
| R2 在 S1 上是否优于 R1 | E2 − E1 | E2 − E1 | 原始平铺聊天上的检索策略差异 |
| R2 在 S2 上是否优于 R1 | E4 − E3 | E4 − E3 | 有目录时的检索策略差异 |
| curated system 是否有整体优势 | E5 vs E1/E3；E6 vs E2/E4 | 同左 | 内容整理与相应检索系统的联合效果 |

E1–E4 可以进一步计算交互：

`DID = (E4 − E2) − (E3 − E1)`

它检验目录组织的效果是否依赖检索方法。该 DID 应在 Qwen 和 DeepSeek 内分别计算，再在 RQ2 比较两种 backbone 的 DID。

### 5.2 分析方法

- 每个对照输出逐题 `ΔF1 / ΔStrict / ΔSoft / ΔEvidence Recall / Δtokens`；
- 报告均值差、中位数差、95% paired bootstrap CI 和 win/tie/loss；
- Strict 使用标签转移和 exact McNemar test；
- 分别报告 C1–C4，但类别结果仅作异质性和机制解释；
- 对照 Any-hit、All-hit 和 Evidence Recall，判断质量差异是否来自覆盖变化；
- 比较 tokens、calls 和 latency，判断增强检索是否主要提供效率而非质量提升。

### 5.3 可以回答与不能回答的结论

可以回答：目录是否只在 agentic 文件导航下有用；增强检索的收益是否依赖存储布局；curated-memory 系统整体是否在某些题型或成本目标下更有优势。

不能回答：E5/E6 的差异不能被写成“LLM 摘要本身”的纯因果效应；R1 round 与 R2/R3 action 不是同一种资源单位，不能直接用次数多少判断算法更复杂。

## 6. RQ2：组件结论能否跨 backbone 保持？

仅比较 Model 1 和 Model 2 的总体平均值不能回答 backbone 稳健性。真正需要检验的是同一题、同一条件的变化，以及架构效果是否随 backbone 改变。

### 6.1 核心分析

1. 对每个 E 条件计算逐题 `DeepSeek − Qwen` 的 F1、Strict、Soft、答案长度、tokens 和标签转移；
2. 比较七个条件在两种 backbone 下的排序和方向一致率；
3. 计算 contrast-of-contrasts，例如：
   - `[(E3−E1)_DeepSeek] − [(E3−E1)_Qwen]`；
   - `[(E2−E1)_DeepSeek] − [(E2−E1)_Qwen]`；
   - `[(E7−E6)_DeepSeek] − [(E7−E6)_Qwen]`；
4. 分析回答长度、Token Precision 与 Judge 标签的关系，解释为什么 token F1 差距可能远大于语义差距；
5. 在全部 60 题上给出主结论，并用 C1–C4 分层检查效果是否集中在某类问题上。

### 6.2 结论边界

两种 backbone 同时承担 Retrieval Agent 和 Answerer，跨模型差异是端到端 backbone 效果，不能仅归因于“检索能力”或“推理能力”。S2/S3 存储在两个回答 backbone 间保持固定，这保证输入资产一致，但并不把写入模型的影响从存储中消除。

## 7. RQ3：双源融合 E7 是否产生互补，何时反而造成干扰？

### 7.1 核心对照

- `E7 − E2`：加入 curated-memory 证据后的变化；
- `E7 − E6`：加入 raw-chat 证据后的变化；
- 两个 backbone 分开计算，再比较方向是否一致。

### 7.2 按父系统状态分层

每道题先按 E2/E6 状态分成：

1. 两路都正确；
2. 只有 E2 正确；
3. 只有 E6 正确；
4. 两路都不正确。

再统计 E7 的：

- repair：父系统不正确而 E7 正确；
- harm：至少一路父系统正确而 E7 下降；
- preserve：E7 保持父系统的正确性；
- unresolved：两路与 E7 都未解决。

同时比较两路 evidence 的重叠、边际 gold coverage、答案长度和无关证据量。`max(E2,E6)` 可以作为描述性的父系统 oracle，表示“若事先知道哪一路更好”的潜在上限，但不能作为可部署 baseline。

E7 复用 E2 和 E6 的 EvidenceBundle，并不重新执行多源检索。因此结论只适用于当前固定证据融合方法，不能推广为所有多源检索架构。

## 8. RQ4：Full Context 相对选择性记忆检索提供了什么边界？

### 8.1 主对照

- **主要锚点：** Full Context vs DeepSeek E1。两者都基于原始 S1 信息，区别是选择性 agentic 检索与完整上下文输入；
- **系统锚点：** Full Context vs DeepSeek E5，比较完整原文与 curated filesystem 主条件；
- **宽证据锚点：** Full Context vs DeepSeek E7，比较完整原文与双源选择性证据；
- 其余 E1–E7 作为补充描述性对照。

### 8.2 四类逐题结果

| Full Context | 检索系统 | 解释候选 |
|---|---|---|
| 正确 | 错误 | 检索遗漏、预算或整理可能是瓶颈 |
| 错误 | 正确 | 选择性压缩可能帮助注意力集中 |
| 正确 | 正确 | 检索在不损失答案的情况下压缩上下文 |
| 错误 | 错误 | 问题可能涉及利用、推理、校准或共同信息缺口 |

需要比较 Strict/Soft/F1、类别、答案长度、tokens 和标签转移。Full Context 全源可见却仍有非正确答案时，只能说明错误不完全由信息不可见造成；后续仍需区分长上下文定位、组合推理与回答校准。

Full Context 不是 oracle；其 source coverage 不等于 evidence recall。由于它与 Model 2 的精确 served identifier 不完全相同，结论写成同一模型家族下的诊断性对照，不写成严格单变量因果结果。项目没有 Qwen Full Context，因此也不能声称 Full Context 效果跨 backbone 稳定。

## 9. RQ5：错误主要发生在哪个阶段？

### 9.1 诊断链

`source/store fidelity → retrieval coverage → bundle/预算 → answer utilization/reasoning → fusion/long-context attention → evaluation`

### 9.2 自动初筛规则

| 信号 | 初步错误候选 | 需要复核什么 |
|---|---|---|
| S1/S2 有事实，S3 缺失或内容偏移 | 写入/整理错误 | S3 原文、引用和更新时间 |
| gold evidence 未命中且答案错误 | 检索遗漏 | query、trace、近邻扩展和 budget |
| gold evidence 部分命中、All-hit=false | 多证据覆盖不足 | 缺失的是哪一步推理证据 |
| gold evidence 命中但答案错误 | 利用/推理错误 | bundle 噪声、冲突与 Answerer 推理 |
| Judge correct 但 token F1 很低 | 词面/回答风格不一致 | 同义改写、冗长解释、答案边界 |
| E7 比正确父系统下降 | 融合干扰候选 | 重复、冲突和无关证据 |
| Full Context 错而检索系统对 | 长上下文注意或利用候选 | 相关位置、上下文距离与答案生成 |
| 所有系统都错 | 共性推理或数据难点 | gold、题意、图像 caption 和多跳链 |

Evidence Recall 只在 58 个 evidence-eligible 问题上统计；其余问题单列。自动标签是诊断信号，不是错误真相。Gold evidence 也未必穷尽所有可支持答案的片段，因此“未命中但答对”不能直接算作检索成功或失败。

### 9.3 人工案例分析

建议选择 16–24 个案例，覆盖：

- storage/retrieval repair 与 harm；
- 高 Evidence Recall 但答案错误；
- 低 Evidence Recall 但答案正确；
- 两种 backbone 方向相反；
- E7 互补与干扰；
- Full Context 修复与 Full Context 失败；
- token F1 与 Judge 明显冲突。

每个案例沿同一模板复查：`question → gold evidence → retrieval trace → EvidenceBundle/context → answer → token score → Judge label/reason`。正文展示 4–6 个最能说明机制的案例，其余放附录。

## 10. RQ6：质量提升需要付出多少成本？

### 10.1 三类成本分开计算

1. **每题查询成本：** retrieval/answer tokens、model calls、latency；
2. **一次性建库成本：** S2 foldering、S3 curated-memory construction；
3. **运行维护成本：** 失败尝试、重试、检查点恢复和人工介入。

成功路径成本用于算法公平比较；运行维护成本另表报告，不能混入后再把差异全部归因于算法。Judge token 不属于部署时的回答成本，应作为评测成本单列。

### 10.2 主要分析

- 每个 backbone 分别绘制 `tokens–F1`、`tokens–Strict`、`tokens–Soft` Pareto 图；
- 在图中标出 E1→E2、E3→E4、E5→E6 和 E2/E6→E7；
- Full Context 只放入 DeepSeek 家族的描述性成本图；
- 报告被其他条件在“更便宜且不更差”意义上严格支配的点；
- 计算 `总成本(N)=建库成本+N×平均查询成本`，展示不同查询量下 S2/S3 的摊销与 break-even；
- E7 的部署成本按两路检索加一次融合回答核算，不能因为实验中复用已生成 bundle 而记成零检索成本。

不同模型的 tokenization、服务实现和响应风格不同，因此跨模型 token 与 latency 比较应写成资源代理指标，不能直接等同美元、能耗或普适吞吐。

## 11. 统一分析数据表

离线分析应先生成一张只含必要字段的主表，每行代表一个 `question × system/condition`：

| 字段组 | 建议字段 |
|---|---|
| 身份 | question_id、category、system、backbone、condition、storage、retrieval |
| 质量 | precision、recall、official_f1、judge_label、strict、partial、soft |
| 检索 | evidence_eligible、evidence_recall、any_hit、all_hit、bundle_chars |
| 回答 | answer_tokens、normalized_answer_length、insufficient_evidence |
| 成本 | retrieval_tokens、answer_tokens、total_tokens、model_calls、latency |
| 行为 | rounds/actions、cap_reached、budget_skipped、empty_bundle、citation_validity |
| Full Context | source_coverage、context_chars、context_tokens；检索字段统一为 N/A |

主表应有 900 行。统计脚本必须验证：

- Model 1、Model 2 各 420 行，E1–E7 各 60；
- Full Context 60 行；
- 三套系统 question IDs 完全一致；
- 类别分布为 13/13/7/27；
- Judge、答案和评分哈希绑定到正确运行；
- 同一行不存在重复 key；
- Full Context 的 Evidence Recall/Any-hit/All-hit 保持 N/A。

## 12. 统计报告规则

### 12.1 主要与次要指标

- 主质量指标：官方 LoCoMo F1 与 Judge Strict；
- 语义敏感性指标：Judge Soft；
- 解释性指标：Precision、Recall、Evidence Recall、answer length；
- 决策指标：tokens、calls、latency、Pareto dominance。

所有表同时报告效果量和不确定性，不以单个 p-value 决定结论。

### 12.2 配对统计

- 连续指标：均值差、中位数差、win/tie/loss、10,000 次 question-level paired bootstrap 95% CI；
- Strict：correct/not-correct 配对表、exact McNemar test、差值与 CI；
- 三档 Judge：correct/partial/incorrect 转移矩阵；
- 类别：按 C1–C4 分层 bootstrap，但明确小样本限制；
- 多个预设对照按 RQ 分族报告，并对探索性显著性检验使用 Benjamini–Hochberg FDR；
- backbone×architecture 交互使用 question-level difference-in-differences 或 cluster bootstrap。

### 12.3 敏感性分析

1. 60 题整体结果与 C1–C4 题型分层结果；
2. 官方 F1 与 Judge Strict/Soft；
3. overall micro、category macro 与 post-stratified F1；
4. 答案长度控制前后的 Precision/F1；
5. evidence-eligible 58 题与全部 60 题；
6. correct vs not-correct 和 correct/partial/incorrect 两种 Judge 汇总。

## 13. 建议制作的表格与图

### 13.1 正文最小集合

1. **主结果表：** 两个 backbone × E1–E7，加 Full Context 单行；列 F1、Strict、Soft、Evidence Recall、tokens；
2. **组件效果 forest plot：** RQ1 关键配对差与 95% CI；
3. **Backbone × condition 热力图：** 两模型的 F1/Strict/Soft 和方向翻转；
4. **E7 repair/harm 图：** 从 E2/E6 父系统状态流向 E7；
5. **Full Context 标签转移图：** FC 与 E1/E5/E7 三个锚点；
6. **错误归因堆叠图：** storage、retrieval、budget、utilization、fusion、long-context；
7. **质量—成本 Pareto 图：** tokens 对 F1/Soft，按 backbone 分面。

### 13.2 附录内容

- C1–C4 全部条件明细；
- C1–C4 题型分层、逐题配对差值与标签转移明细；
- 全部 paired contrasts 与多重比较；
- cap、budget skip、empty bundle、citation validity 和恢复统计；
- 代表案例扩展表；
- Judge rubric、prompt hash 和运行身份摘要。

## 14. Results / Analysis 章节建议

建议给中心分析章节 8–10 页。最终目录已将原先较零散的分析项压缩为 6 个三级标题、18 个四级标题，并为每节规定“核心问题—必要对照—分析方法—核心产物—结论边界”。可直接写作的完整指南见 [Main-60 问题分析：精简目录与逐节分析指南](main60-problem-analysis-detailed-outline.md)。

| 小节 | 内容 | 建议页数 |
|---|---|---:|
| 5.1 | 总体结果、统一统计规则与评分分歧 | 1.0–1.2 |
| 5.2 | 架构线：存储、检索、DID 与 curated memory | 2.0–2.5 |
| 5.3 | 稳健性线：跨 backbone contrast 与机制 | 1.2–1.5 |
| 5.4 | 机制线：E7 双源融合与 Full Context | 1.3–1.7 |
| 5.5 | 错误归因线：自动初筛、人工复核与瓶颈 | 1.2–1.5 |
| 5.6 | 决策线：成本、Pareto 与场景化选择 | 1.0–1.3 |

Discussion 另用 2–3 页解释论文关系、设计含义和限制，不要在 Results 中重复大段背景。完整配对统计、C1–C4 明细、全部人工案例和成本细表放入附录。

## 15. 当前完成状态与下一步

| 工作 | 状态 | 下一步 |
|---|---|---|
| 60 题三套答案与双评分 | 已完成 | 固定为分析输入，不再修改答案 |
| Model 1 main-60 LoCoMo 汇总 | 已可只读精确重算 | 生成显式、可审计的 main-60 分析产物 |
| Model 2 与 Full Context 汇总 | 已完成 | 合并到统一 900 行主表 |
| question-level 配对统计 | 未完成 | 按六个 RQ 生成差值、CI、转移矩阵 |
| C1–C4 分层 | 原始字段已具备 | 生成类别表和异质性图 |
| token 指标与 Judge 一致性 | 未完成 | 加入答案长度和 Precision 分析 |
| retrieval/utilization 自动归因 | 未完成 | 先规则初筛，再人工复核 |
| E7 融合分析 | 未完成 | 生成父系统状态与 repair/harm 表 |
| Full Context 诊断 | 总分已完成 | 完成逐题标签转移与错误集合对照 |
| 成本与 Pareto | 成本字段已具备 | 分离建库、成功查询、维护和 Judge 成本 |
| 人工案例 | 未开始 | 按预定义类别抽取 16–24 条 |

### 推荐执行顺序

1. 生成并验证 900 行统一主表；
2. 完成 RQ1/RQ2 的预设配对统计；
3. 完成 RQ3/RQ4 的 E7 与 Full Context 转移分析；
4. 完成 RQ5 自动归因与人工案例复核；
5. 完成 RQ6 Pareto 与摊销分析；
6. 生成正文最小图表；
7. 最后撰写 Discussion，避免先写结论再选择证据。

## 16. 可写结论与禁止越界

### 16.1 在配对分析后可以写

- 某个存储或检索对照在当前 60 题上的平均方向、效果量和不确定性；
- 某个组件效果是否在 Qwen 与 DeepSeek 上方向一致；
- Full Context 在当前 DeepSeek 家族运行中修复了哪些检索错误，又在哪些题上不如选择性检索；
- 主要错误候选更集中在检索覆盖、证据利用、融合还是长上下文注意；
- 哪些条件在当前质量—成本空间中位于 Pareto 前沿。

### 16.2 不能写

- 不能把一个 conversation 的结果推广为所有长期记忆任务；
- 不能把 900 个答案当成 900 个独立样本；
- 不能把 S3 系统差异归因成纯存储或纯摘要效应；
- 不能把 Full Context 称为 oracle、理论上限或 E8；
- 不能把 source coverage 100% 当作 Evidence Recall 100%；
- 不能因为 Judge 分高就忽略官方 F1，也不能因为 F1 低就断言语义错误；
- 不能把 Partial Rate 当成越高越好的分数；
- 不能把相关性、自动错误标签或个别案例写成已证明的因果机制。

## 17. 与相关论文的连接

| 来源 | 可借鉴分析 | 本项目对应位置 |
|---|---|---|
| Filesystem-Based Memory，§3、Table 1、§4.2 | 组织、写入和检索作为完整系统；主结果与消融 | RQ1 的 S1/S2/S3 与 R1/R2/R3 组件分析 |
| Filesystem-Based Memory，§4.5、Appendix D | 结构规模、成本、检索与利用、失败案例 | RQ5 错误链与 RQ6 成本分析 |
| ReFind，Search Engine Design、Table 2、Table 4 | 迭代检索、baseline、组件消融、资源成本 | RQ1 检索对照和 RQ6 效果—成本 |
| Diagnosing Retrieval vs Utilization Bottlenecks | 区分 retrieval、utilization 和 hallucination | RQ5 二阶段及多阶段错误归因 |
| Evaluating Very Long-Term Conversational Memory | 分开报告 answer quality 与 retrieval recall；比较 long context 与 RAG | RQ4 Full Context 与 RQ5 检索/利用分离 |

相关本地材料：

- [旧 E1–E7 分析框架](e1-e7-results-analysis-framework.md)
- [实验完整解释](../explanations/end-to-end-experiment-explanation.md)
- [main-60 与双 backbone 评分记录](../progress/2026-10-16-to-17-main60-model2-and-rescoring.md)
- [Full Context main-60 操作方案](../plans/full-context-deepseek-main60-v2-operation-plan.md)
- [Full Context 最终模型身份与运行冻结方案](../plans/full-context-deepseek-main60-v3-repin-plan.md)
- [Filesystem-Based Memory 原文](../../papers/primary/filesystem-based-memory-for-llm-agents.pdf)
- [ReFind 原文](../../papers/primary/when-your-agent-opens-the-chat-app-refind.pdf)

### 17.1 权威结果入口

- Model 1 Judge：`experiments/locomo-conv50-v1/results/llm-judge-x-test1-main120/llm-judge-x-test1-model1-main60-run-01/results.json`；
- Model 2 LoCoMo：`experiments/locomo-conv50-v1/results/formal-v2-model2-main60-candidate-02/run/locomo-prf-summary.json`；
- Model 2 Judge：`experiments/locomo-conv50-v1/results/llm-judge-x-test1-main120/llm-judge-x-test1-model2-main60-run-01/results.json`；
- Full Context LoCoMo：`local-runs/b3-full-context-v3-model2-1017/b3-full-context-v3-model2-1017-main60-run-01/evaluation.json`；
- Full Context Judge：`local-runs/b3-full-context-v3-model2-1017-judge-x-test1/llm-judge-x-test1-b3-full-context-main60-run-01/results.json`。

Model 1 main-60 的 LoCoMo 汇总目前可由冻结的逐题结果只读重算；正式生成统一 900 行分析表时，应把该汇总另存为带输入哈希和审计信息的显式产物。
