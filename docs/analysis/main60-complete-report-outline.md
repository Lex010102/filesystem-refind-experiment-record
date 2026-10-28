# Main-60 完整报告框架目录

## 0. 文档定位

这份目录是当前项目的**完整报告写作蓝图**。它面向冻结的 60 道题、两套 E1–E7 backbone 实验，以及一套 DeepSeek Full Context 诊断基线，不再沿用早期只覆盖 40 题的报告结构。

框架综合了两类参考：

1. 学校 sample report 的正式报告外壳：前置页、摘要、引言、文献与系统背景、实验章节、结论和参考文献；
2. Filesystem 论文的论证骨架：先形式化系统与变量，再说明实验配置，随后按研究问题组织结果，并把质量、检索行为、成本、失败案例和结论边界放进同一条证据链。

本报告不照搬任何一份参考材料。学校样本包含三个相对独立的应用，因此它的 70 页编号正文不能机械映射为本项目的页数；Filesystem 论文则非常紧凑，不适合直接作为学校长报告的章节粒度。这里借鉴的是二者的**完整度与论证方式**。

本报告的主线是：

```text
为什么长期对话需要外部记忆
→ 存储表示与检索方式如何共同构成记忆系统
→ 如何用公平的受控实验比较这些组合
→ 哪些效果跨 backbone 稳定、哪些依赖模型
→ 双源融合与 Full Context 揭示了什么机制
→ 错误发生在存储、检索、证据利用还是长上下文阶段
→ 在质量、成本和可维护性之间应该如何选型
→ 当前结论有哪些边界，后续应如何继续验证
```

---

## 1. 建议篇幅与版本

### 1.1 推荐的长报告版

如果希望在完整度上接近学校 sample report，建议把**编号正文**控制在约 55–70 页；加上前置材料、参考文献与附录，完整 PDF 可达到约 80–105 页。正文不应靠重复配置或堆表扩页，详细 prompt、完整统计表、案例记录和运行审计应主要进入附录。

| 部分 | 建议页数 |
|---|---:|
| 前置材料 | 8–12 |
| 第 1 章 引言 | 4–5 |
| 第 2 章 背景与相关工作 | 6–8 |
| 第 3 章 系统设计与方法 | 8–10 |
| 第 4 章 实验设计与评价方法 | 8–10 |
| 第 5 章 结果与问题分析 | 18–22 |
| 第 6 章 综合讨论 | 4–6 |
| 第 7 章 局限与有效性威胁 | 3–5 |
| 第 8 章 后续工作与开放性探索 | 4–6 |
| 第 9 章 结论 | 2 |
| 参考文献 | 4–8 |
| 附录 | 15–30 |

### 1.2 如仍需 25–30 页正文的压缩版

同一目录仍可使用，但应压缩为：第 1 章 2–3 页、第 2 章 3 页、第 3 章 4 页、第 4 章 4–5 页、第 5 章 8–10 页、第 6–8 章合计 4–5 页、第 9 章 1 页。完整配置、扩展统计和案例全部移入附录。

无论采用哪种长度，第 5 章都应是正文中篇幅最大、证据最密集的核心章节。

---

## 前置材料

### Title Page

- 学校、项目、作者、学号、导师、提交日期；
- 标题应同时体现“filesystem memory”“retrieval”“backbone robustness”与“long-context comparison”中的核心概念，但避免标题过长。

### Declaration / Statement of Originality

- 按学校模板填写原创性与提交声明。

### Acknowledgements

- 简要说明导师、师兄、数据和基础设施支持。

### Abstract

摘要建议采用五句式：

1. 长期对话记忆面临什么问题；
2. 现有研究还缺少什么受控比较；
3. 本研究构建了哪些存储、检索、backbone 与 Full Context 条件；
4. 使用哪些质量、证据和成本指标；
5. 最重要的发现、适用边界和贡献是什么。

摘要只报告最终确认的核心结果，不塞入所有 E1–E7 数字。

### Table of Contents

- 至少列到三级标题；四级标题是否显示按学校格式决定。

### List of Figures / List of Tables

- 对应正文中的系统图、实验矩阵、效果图、错误漏斗、Pareto 图和决策矩阵。

### List of Abbreviations and Symbols

- S1–S3、R1–R3、E1–E7、FC、P/R/F1、Strict、Soft、Evidence Recall、DID、CoC 等。

---

# 第 1 章 引言

## 1.1 研究背景

说明长对话、持续交互和个性化 agent 为什么需要外部记忆；解释模型上下文窗口变长仍不能自动解决组织、检索、更新、成本和可审计性问题。

## 1.2 问题陈述

把问题从“模型记不住”具体化为一条端到端链：

```text
原始对话 → 存储表示 → 检索与证据选择 → Answerer 利用 → 最终答案
```

指出最终错误可能来自任一阶段，因此不能只比较答案均值，也不能把所有提升都归因于单一检索器。

## 1.3 研究缺口

重点说明四个缺口：

1. 存储组织与检索策略常被一起改变，难以识别二者交互；
2. 单一 backbone 上的结果可能只是模型特性，而非架构规律；
3. 多数工作缺少对选择性检索与完整上下文的同题诊断；
4. 结果分析常停留在准确率排名，缺少证据覆盖、错误阶段和质量—成本联合解释。

## 1.4 研究目标

明确本研究不是寻找脱离场景的“唯一最佳方法”，而是建立一套受控实验，回答不同记忆架构在什么条件下有效、为什么有效，以及是否值得其成本。

## 1.5 研究问题

建议正式采用六个研究问题：

- **RQ1：** 存储表示和检索策略各自带来什么变化，二者是否存在交互？
- **RQ2：** 这些架构效果能否跨 Qwen 与 DeepSeek 稳定复现？
- **RQ3：** 双源融合在什么情况下修复错误，在什么情况下引入干扰？
- **RQ4：** Full Context 是否真正优于选择性检索，二者分别暴露什么瓶颈？
- **RQ5：** 端到端错误主要发生在存储保真、检索覆盖、证据打包、回答利用还是长上下文处理阶段？
- **RQ6：** 综合质量、成本、稳定性与维护复杂度，哪些条件最值得实际采用？

## 1.6 研究贡献

建议用 4–5 点概括：

1. 建立存储 × 检索的受控比较框架；
2. 在同一 60 题集上完成双 backbone 的 E1–E7 对照；
3. 加入 Full Context 以诊断选择性检索与长上下文利用；
4. 联合使用词面、语义、证据和效率指标；
5. 给出阶段化错误分析与面向部署的条件化选择建议。

## 1.7 研究范围与边界

提前说明：研究聚焦一个 LoCoMo conversation 的 60 道冻结问题；不声称覆盖所有长期记忆场景；Full Context 是诊断基线，不是理论 oracle；E5/E6 是完整 curated-memory 系统对照，不是单一摘要组件消融。

## 1.8 报告结构

用一段话介绍第 2–9 章的逻辑关系，而不是简单罗列标题。

---

# 第 2 章 背景与相关工作

## 2.1 LLM 长期记忆的基本问题

介绍记忆写入、组织、检索、更新和使用的生命周期；区分参数记忆、上下文记忆和外部记忆。

## 2.2 外部记忆的主要表示形式

### 2.2.1 原始对话与日志式存储

讨论保真度高、维护简单，但上下文冗长、定位困难。

### 2.2.2 文件系统式记忆

讨论文件、目录、命名、层级和 agent 工具如何共同构成可导航记忆。

### 2.2.3 整理式或摘要式记忆

讨论压缩、主题化和事实条目带来的噪声降低，以及遗漏、失真和更新成本。

### 2.2.4 向量、图与其他结构化记忆

作为相关基线类别介绍，不需要在正文中详述本项目未运行的所有系统。

## 2.3 记忆检索方法

### 2.3.1 Agentic 文件导航与文本搜索

解释 agent 如何根据问题生成搜索策略、浏览文件和收集证据。

### 2.3.2 词项排序与迭代式检索

介绍 BM25、query reformulation、邻近扩展、多轮 action 和停止机制。

### 2.3.3 多源证据融合

区分“重新检索”和“复用两路已有证据再回答”。

### 2.3.4 Full Context 与长上下文模型

说明全量输入消除了显式检索筛选，但没有消除长上下文定位、注意力和推理困难。

## 2.4 Filesystem-Based Memory 论文

重点介绍其 memory store、tool harness、agent roles、固定与变化变量，以及“memory shape × searcher/backbone/harness/scale”的研究逻辑。不要只做论文摘要，要说明本研究从中继承了什么、又扩展了什么。

## 2.5 ReFind 及迭代检索思想

说明 ReFind 风格检索如何把 query、候选排序、证据扩展和 action cap 组织成可审计流程，并明确本项目的实现边界。

## 2.6 长期对话评测与 LoCoMo

介绍对话、问题类型、gold answer、gold evidence，以及长期记忆问答为何适合同时评价答案和证据过程。

## 2.7 评价方法综述

### 2.7.1 Token Precision、Recall 与 F1

解释词面覆盖、冗余和遗漏分别如何反映在三个指标上。

### 2.7.2 LLM-as-Judge

解释 Strict、Partial 与 Soft 的作用、优点和偏差来源。

### 2.7.3 检索与效率指标

介绍 Evidence Recall、Any-hit、All-hit、tokens、calls、latency 和维护成本。

## 2.8 本研究定位与差异表

用一张表比较 Filesystem、ReFind、LoCoMo 官方评价与本项目：研究对象、存储形式、检索形式、backbone、Full Context、指标和错误分析。结尾明确本项目填补的受控比较空白。

---

# 第 3 章 系统设计与方法

本章回答“系统是什么、各组件如何工作”；第 4 章才回答“怎样设计实验并公平评价”。二者必须分开。

## 3.1 任务形式化

定义 conversation、question、memory store、retrieval trace、EvidenceBundle、answer 与 evaluation record；给出端到端数据流和符号表。

## 3.2 总体系统架构

用一张总图展示：数据规范化、三种存储、三种检索、共享 Answerer、E7 融合、Full Context 和评价管线。

## 3.3 数据规范化与可追溯性

说明原始 turns 如何转换为 canonical records、exchange units、session 文件和 source map；解释为什么不同存储仍能追溯到同一原始信息。

## 3.4 三种存储表示

### 3.4.1 S1：平铺原始 Session

说明内容保真、文件布局和适合作为原始基线的原因。

### 3.4.2 S2：目录化原始 Session

说明只改变导航结构而尽量保持正文内容不变，从而用于识别目录组织的增量作用。

### 3.4.3 S3：Agent-Curated Memory

说明主题化、事实整理、引用与更新方式，同时承认它改变了内容和结构，因此属于完整系统条件。

## 3.5 三种检索系统

### 3.5.1 R1：Agentic Filesystem Retrieval

讲清工具、观察—行动循环、round、证据记笔记和结束搜索后的回答交接。

### 3.5.2 R2：ReFind-Style Raw-Chat Retrieval

讲清 query 生成、BM25/session ranking、邻近扩展、seen-state、action cap 和证据汇总。

### 3.5.3 R3：面向 Curated Memory 的适配检索

说明它如何适配 S3 的事实条目与主题结构，以及为什么不能直接等同于 R2。

## 3.6 共享 EvidenceBundle 与 Answerer

说明不同检索系统怎样被包装为统一证据接口、预算如何约束，以及 Answerer 如何在不接触实验标签的情况下生成最终答案。

## 3.7 E1–E7 条件映射

用主表给出每个条件的存储、检索、证据来源和可识别问题：

| 条件 | 存储/来源 | 检索/处理 | 主要角色 |
|---|---|---|---|
| E1 | S1 | R1 | 原始文件基线 |
| E2 | S1 | R2 | S1 上的增强检索 |
| E3 | S2 | R1 | 目录对 R1 的作用 |
| E4 | S2 | R2 | 目录与 R2 的组合 |
| E5 | S3 | R1 | Curated filesystem 系统 |
| E6 | S3 | R3 | Curated memory 适配检索 |
| E7 | E2 + E6 证据 | 固定融合后回答 | 双源互补与干扰 |

## 3.8 E7 双源融合机制

明确 E7 不重新执行第三种检索，而是复用 E2 与 E6 的 EvidenceBundle；说明去重、排序、预算与回答过程。

## 3.9 Full Context 诊断路径

说明每题如何接收完整 30-session 原始上下文；明确它不使用 S2/S3、检索器或 16,000 字符 EvidenceBundle，因此不是 E8，也不是新的存储方式。

## 3.10 系统契约与审计设计

概述模型身份、prompt、store hash、checkpoint、failure record 和 batch audit 如何保证实验可追溯。完整字段和 hash 放附录。

---

# Chapter 4 Experimental Design and Evaluation Methodology

This chapter explains how the study was designed, controlled, evaluated, and analysed. Chapter 3 defines the system components and evidence-access paths. Chapter 4 specifies how those components are instantiated in the formal experiments and how fair comparisons are constructed. Chapter 5 reports and interprets the empirical results. This chapter does not present final scores or identify a winning condition.

## 4.1 Research Questions, Variables, and Identification Strategy

### 4.1.1 Mapping Research Questions to Experimental Comparisons

Map each research question to its experimental material, main contrast, and required evidence. The main table should connect RQ1–RQ6 to E1–E7, Full Context, the two backbone models, answer-quality metrics, evidence metrics, process records, and cost records. This subsection should operationalise the research questions rather than repeat their motivation from Chapter 1.

### 4.1.2 Independent, Dependent, and Controlled Variables

Define the independent variables as memory representation, retrieval system, backbone model, evidence-access regime, and single- or dual-source evidence. Define the dependent variables as token Precision, Recall, and F1; Strict Accuracy, Partial Rate, and Soft Semantic Score; Evidence Recall, Any-hit, and All-hit; and process or cost measures. Controlled variables include the unified Main-60 set, question order, frozen store snapshots, EvidenceBundle interface, Answerer contract, and evaluation rules.

### 4.1.3 Identifiable and Non-Identifiable Effects

State what each comparison can and cannot establish. E1–E4 provide the cleanest storage–retrieval comparisons. E5 and E6 are complete curated-memory systems. E7 evaluates evidence fusion rather than a new retrieval method. Full Context is a diagnostic baseline rather than an oracle. The backbone comparison changes the Retrieval Agent and Answerer together and therefore represents a change to the complete query-time pipeline.

### 4.1.4 Primary and Exploratory Analyses

Distinguish full-set paired comparisons from exploratory category, correlation, anomaly, and case analyses. Use the term *primary comparison* rather than imply formal preregistration. Main conclusions should rely on the unified Main-60 results; C1–C4 analyses should support mechanism interpretation.

## 4.2 Dataset and the Frozen Main-60 Test Set

### 4.2.1 LoCoMo Source and Conversation Scope

Describe the LoCoMo source and version, the selected `conv-50` conversation, its 30 sessions, and the included turns, speakers, timestamps, and existing image captions. State that the experiment did not rerun a vision model. Dataset fingerprints and the complete source manifest belong in Appendix B.

### 4.2.2 Composition of Main-60

Present Main-60 as one unified test set: 13 multi-hop questions, 13 temporal questions, 7 open-domain questions, and 27 single-hop questions. Report the fixed order and explain that no old-40/new-20 result split is used. Category-level results remain exploratory and do not replace the full-set analysis.

### 4.2.3 Gold Answers and Gold Evidence

Explain the separate roles of reference answers and annotated source-turn evidence. State that 58 questions are eligible for evidence-based metrics and explain why that denominator differs from 60. Note that annotated evidence may not exhaust every valid supporting passage. Gold answers and gold evidence are used only during offline evaluation and are not exposed to the Retrieval Agent or Answerer.

## 4.3 Experimental Matrix and Core Comparisons

### 4.3.1 Complete Experimental Matrix

Report the formal scale of the study: Qwen contributes 420 answers from 60 questions across E1–E7, DeepSeek contributes another 420, and DeepSeek Full Context contributes 60, giving 900 candidate answers. Clarify that these are repeated observations over the same 60 questions rather than 900 independent samples.

### 4.3.2 E1–E4: Controlled Storage–Retrieval Comparisons

Present the approximate `S1/S2 × R1/R2` design. Define `E3−E1` and `E4−E2` as the storage-organisation contrasts, and `E2−E1` and `E4−E3` as the retrieval-system contrasts. Define the interaction descriptively as `DID = (E4−E2)−(E3−E1)`.

### 4.3.3 E5–E6: Curated-Memory Systems

Explain that E5 and E6 use the same frozen S3 store and that `E6−E5` compares two access methods on that store. Comparisons with raw-memory conditions are complete-system comparisons and cannot isolate one effect of summarisation, structure, or compression.

### 4.3.4 E7: Dual-Source Fusion

Define E2 and E6 as the parent conditions, explain that E7 reuses their EvidenceBundles without new retrieval, and use `E7−E2` and `E7−E6` as the main comparisons. Distinguish the recorded experimental reuse cost from the full online cost of running two retrieval paths and a fused answer.

### 4.3.5 Full Context Diagnostic

Explain that Full Context receives all 30 raw sessions, performs no retrieval, and does not use the 16,000-character EvidenceBundle. Evidence-retrieval metrics are not applicable. The primary diagnostic anchors should be the DeepSeek raw-memory retrieval conditions, while comparisons with all E1–E7 conditions may also be reported. Full Context is neither E8 nor a theoretical upper bound.

## 4.4 Models and Evaluation Roles

### 4.4.1 Backbone Models and Query-Time Roles

Introduce Model 1 as the Qwen backbone, Model 2 as the DeepSeek backbone, and Full Context as using the DeepSeek model family. Within each E1–E7 system, one backbone performs both the Retrieval Agent and Answerer roles. The cross-backbone comparison therefore concerns the complete query-time pipeline, not an isolated retrieval or answering component. A compact table should report the publication-facing model name, requested alias, served identity, applicable conditions, and role; detailed service metadata belongs in Appendix F.

### 4.4.2 Independent LLM Judge

Explain that semantic evaluation uses an independent LLM judge from a different model family. The judge receives anonymised question, reference-answer, and candidate-answer inputs; it does not observe the condition, backbone, retrieval trace, cost, or token-overlap score. One fixed rubric assigns one `correct`, `partial`, or `incorrect` label, from which the three semantic metrics are derived.

## 4.5 Controlled Experimental Conditions

Keep this section concise. Explain that each comparison changes only the factor relevant to its research question while holding the question set, source conversation, frozen stores, EvidenceBundle and Answerer contracts, and evaluation procedures constant wherever applicable. Storage representation, retrieval system, backbone model, evidence-access regime, and evidence fusion are the intended sources of variation. Evidence budgets and search limits were frozen before formal evaluation, while Full Context was not subject to the selective EvidenceBundle limit.

Use one held-fixed/varied/not-applicable table rather than several configuration subsections. Exact budgets, caps, model identities, and frozen configuration values belong in Appendix F, while complete prompt versions belong in Appendix A. Do not include batch size, checkpoints, process identifiers, run locks, launcher commands, local paths, or marker filenames in the report.

## 4.6 Evaluation Metrics and Cost Accounting

### 4.6.1 Token Precision, Recall, and F1

Define per-question token Precision and Recall under the aligned normalisation procedure. Define F1 at the question level and report macro-averages across questions. Explain that aggregate F1 is the mean of per-question F1 values and cannot be reconstructed from aggregate Precision and Recall. Require one common offline evaluator for all 900 answers so that Full Context and E1–E7 use the same report-level Precision and Recall rules. Use Precision and Recall to diagnose verbosity and omission, while F1 supports comparison with LoCoMo-style evaluation.

### 4.6.2 LLM Judge Metrics

Define `Strict Accuracy = correct/n`, `Partial Rate = partial/n`, and `Soft Semantic Score = (correct + 0.5 × partial)/n`. Clarify that Partial Rate describes the label distribution rather than an independently maximised quality measure.

### 4.6.3 Evidence-Access Metrics

Define Any-hit, All-hit, and Evidence Recall. State that they apply to the 58 evidence-eligible questions for E1–E7, including the fused parent EvidenceBundles used by E7. Full Context should be reported as `N/A`, not as perfect Evidence Recall. Evidence-access metrics explain evidence coverage but do not replace answer-quality evaluation.

### 4.6.4 Process and Efficiency Metrics

Record retrieval and Answerer calls, input and output tokens, latency, retrieval rounds or actions, failed attempts, memory-construction cost, query-time cost, and evaluation-only Judge cost. Separate one-time construction cost, per-question cost, failure or recovery cost, and Judge cost.

### 4.6.5 Metric Aggregation and Applicability

Provide one table specifying, for every metric, its calculation unit, aggregation method, eligible denominator, applicable conditions, and role as a primary or diagnostic measure.

## 4.7 Statistical Analysis Plan

The analysis should remain primarily descriptive and paired. Confidence intervals are supporting evidence rather than the organising principle of the chapter.

### 4.7.1 Unit of Analysis and Paired Design

Define `question_id` as the primary analysis unit. For metric `m`, compare conditions through per-question paired differences `d_i = m_i(A) − m_i(B)`. All architecture, fusion, backbone, and Full Context comparisons should retain the pairing between answers to the same question.

### 4.7.2 Overall Paired Differences and Win/Tie/Loss

For each main comparison, report the mean paired difference, median paired difference, win/tie/loss counts, and the distribution of per-question differences. Fix metric direction before assigning wins: higher values are better for quality measures, while lower values are better for calls, tokens, latency, and cost. These are the main tools for determining whether an average improvement is broad or driven by a small number of questions.

### 4.7.3 Category-Level Analysis

Report paired differences for multi-hop, temporal, open-domain, and single-hop questions. Use these results to identify where an effect is concentrated. Because some groups are small, particularly the seven open-domain questions, category analyses remain descriptive and exploratory.

### 4.7.4 Storage–Retrieval Interaction and Backbone Stability

Use the DID contrast to examine whether folder organisation affects R1 and R2 differently. For backbone stability, compare the direction, magnitude, and question-level pattern of the same architecture contrast under Qwen and DeepSeek. Do not claim model dependence merely because one model-specific comparison is significant and another is not.

### 4.7.5 Auxiliary Paired Bootstrap Confidence Intervals

Use paired bootstrap confidence intervals only as supporting evidence for a limited set of primary contrasts, such as the main raw-memory storage and retrieval comparisons, E7 relative to its parents, and the principal Full Context diagnostic comparison. Resample `question_id` as a paired unit. The intervals describe uncertainty within Main-60 and do not estimate variation across conversations. Repetition count, random seed, and implementation details belong in Appendix H.

### 4.7.6 Strict-Label Transitions

For selected Strict comparisons, report incorrect-to-correct gains, correct-to-incorrect harms, and unchanged outcomes. An exact McNemar test may be included for a small number of central comparisons as supplementary evidence, but it should not dominate the analysis.

### 4.7.7 Multiple Comparisons and Interpretation Boundaries

Separate primary paired comparisons from exploratory category, correlation, anomaly, and case analyses. Emphasise effect direction, magnitude, distribution, and cross-backbone consistency rather than producing a large family of isolated significance tests. If a multiple-comparison correction is applied, define its comparison family and procedure in Appendix H.

## 4.8 Error Analysis Method

### 4.8.1 Error Categories

Use a concise stage-based taxonomy covering storage omission or distortion, retrieval failure, incomplete multi-hop evidence, evidence-budget or packaging loss, Answerer utilisation failure, fusion interference, long-context utilisation failure, lexical–semantic evaluation disagreement, and mixed or indeterminate errors. Only high-level definitions belong in Chapter 4; the complete codebook belongs in Appendix H.

### 4.8.2 Review Procedure

Explain that manual review follows the complete information path from the source conversation through the stored representation, retrieval trace, EvidenceBundle, candidate answer, and evaluation outputs. Sample cases should cover different backbone models, conditions, question categories, evidence–answer mismatches, E7 repair or interference, Full Context repair or failure, and F1–Judge disagreement. Chapter 4 defines the method; Chapter 5 reports the observed error distribution and representative cases, while the complete casebook belongs in Appendix H.

### Recommended Chapter Artefacts

- **Table 4.1:** Research questions, conditions, contrasts, and evidence.
- **Table 4.2:** Main-60 composition and evidence eligibility.
- **Table 4.3:** Complete experimental matrix.
- **Table 4.4:** Backbone models and evaluation roles.
- **Table 4.5:** Held-fixed and varied conditions.
- **Table 4.6:** Metric definitions and applicability.
- **Table 4.7:** Primary comparisons and analysis methods.
- **Table 4.8:** High-level error taxonomy.
- **Figure 4.1:** A polished experimental-design workflow from frozen inputs through Qwen E1–E7, DeepSeek E1–E7, and Full Context to 900 candidate answers, blind offline evaluation, paired analysis, and error review. It must show that gold answers and gold evidence enter only the offline evaluation stage.
- **Figure 4.3:** A plain Markdown decision flow for stage-based error attribution. It checks storage fidelity, retrieval access, evidence-budget or packaging loss, EvidenceBundle sufficiency, Answerer utilisation, and token–semantic evaluation disagreement.

Figure 4.2 is intentionally omitted. The paired statistical procedure is already defined by the formulas and tables in Sections 4.7.1–4.7.7 and does not require a separate diagram.

The chapter does not require a separate summary subsection. A short closing paragraph should state that this protocol produces the empirical evidence analysed in Chapter 5. Exact dataset inventories, model and condition configurations, evaluation rules, and statistical and review protocols should be transferred to Appendices B, F, G, and H, respectively.

---

# 第 5 章 结果与问题分析

本章的英文逐节写作与分析指南见 [Chapter 5 Results and Analysis — Detailed Writing Outline](chapter-5-detailed-outline.md)。本目录保留全报告层级与章节职责，详细指南负责每个小节的核心问题、对照、分析产物和结论边界。

本章不按 E1、E2、E3 逐项写流水账，也不把 Accuracy、Cost、Case Study 拆成彼此孤立的大块。它按 RQ 组织，每个小节都遵循：

```text
问题 → 核心对照 → 配对结果 → 过程证据 → 成本/反例
→ 人工复核 → 小结 → 本节结论边界
```

全章建议保持 **6 个三级标题、18 个四级标题**。

## 5.1 总体结果与评分解释

### 5.1.1 三套系统总体结果与 E1–E7 性能画像

- **讨论什么：** Qwen E1–E7、DeepSeek E1–E7 和 Full Context 在 P/R/F1、Strict、Partial、Soft 上呈现什么全局图景；
- **怎么分析：** 给总体表和 condition × metric 热力图，但不把七条件池化均值当作单一可部署系统；
- **应得到什么：** 识别真正需要后文解释的现象，例如词面指标与语义指标的冠军不同、不同 backbone 的条件排序不同；
- **结论边界：** 这里只建立结果地图，不用总体排名替代配对分析。

### 5.1.2 词面评分与语义评分的一致和分歧

- **讨论什么：** F1 与 Strict/Soft 是否一致，分歧来自同义改写、回答长度、冗余、遗漏限定条件，还是核心事实错误；
- **怎么分析：** F1 × Judge 交叉表、Spearman 相关、答案长度分布与四类冲突案例；
- **应得到什么：** 说明为什么必须同时保留官方可复现评分和语义评分；
- **结论边界：** Judge 不是绝对真值，F1 也不能覆盖全部语义等价。

### 5.1.3 关键现象与待验证解释

- **讨论什么：** 从全局结果中提出 3–5 个后续机制假设；
- **怎么分析：** 把每个现象映射到第 5.2–5.6 节所需的 contrast、证据与案例；
- **应得到什么：** 一张“现象—候选解释—验证章节”路线图；
- **结论边界：** 现象是待解释对象，不在本节提前写成因果结论。

## 5.2 架构线：存储、检索及其交互

### 5.2.1 存储组织在不同检索系统下的作用

- **核心对照：** E3−E1 与 E4−E2；
- **分析手段：** F1/Strict/Soft 配对差、win/tie/loss、95% CI、Evidence Recall 与答案转移联动；
- **要回答：** 目录是提高证据覆盖、改善导航，还是只改变外观；其作用是否依赖检索器；
- **案例复核：** “证据改善且答案改善”“证据改善但答案不变”“证据下降却答对”等路径；
- **结论形式：** 写成“目录在何种检索与 backbone 下有帮助”，不能写成普遍有效。

### 5.2.2 检索系统在不同存储表示下的作用

- **核心对照：** E2−E1 与 E4−E3；
- **分析手段：** 同题质量差、Any/All-hit、多跳覆盖、query/trace 复核、tokens/calls/latency；
- **要回答：** R1 与 R2 完整系统在 S1/S2 上谁更适合，目录导航与内容排序是互补还是替代；
- **结论边界：** 不能把完整系统差异简化为 BM25 单一算子的效果。

### 5.2.3 存储 × 检索交互与题型异质性

- **核心计算：** `DID = (E4−E2)−(E3−E1)`；
- **分析手段：** 对 F1、Strict、Soft、Evidence Recall 报告 DID 与 bootstrap CI，并按 C1–C4 展示方向；
- **要回答：** 目录是否更帮助 R1 或 R2，收益是否集中在多跳、时间或单跳问题；
- **结论边界：** C3 题数小，类别结果只用于机制解释。

### 5.2.4 Curated Memory 的系统级效果

- **核心对照：** E5 对 E1/E3、E6−E5，并与原始系统中的合理锚点描述性比较；
- **分析手段：** 质量、Evidence Recall、输入长度、建库/查询成本和信息保真案例联动；
- **要回答：** 整理式记忆何时降噪并改善访问，何时因压缩、时间失真或人物混淆损失信息；
- **结论边界：** 结论属于完整 curated-memory 系统，不能归因于单一摘要组件。

## 5.3 稳健性线：哪些结论跨 Backbone 成立

### 5.3.1 同条件的端到端 Backbone 差异

- **讨论什么：** 同一题、同一 E 条件下 DeepSeek 与 Qwen 的质量、长度、成本和标签如何变化；
- **怎么分析：** 七组同题配对、标签转移、答案长度—Precision/F1—Judge 联动；
- **要解释：** 为什么词面差距可能大于语义差距，backbone 是否更倾向详细或简洁回答；
- **结论边界：** 两个 backbone 同时承担检索与回答，差异不能单独归因于某一个角色。

### 5.3.2 架构效应的跨 Backbone 稳定性

- **讨论什么：** 不是比较两个模型谁总体更高，而是比较同一架构改动在两个模型上是否同方向；
- **怎么分析：** effect sign agreement、contrast-of-contrasts、区间和题级 win/loss；
- **要回答：** 哪些存储/检索结论可被视为较稳定架构规律，哪些只在一个 backbone 下成立；
- **结论边界：** “一个显著、一个不显著”不足以证明交互，必须直接比较效应差。

### 5.3.3 模型依赖现象及其机制候选

- **讨论什么：** 目录导航、迭代检索、curated memory 和融合中哪些现象明显依赖模型；
- **怎么分析：** 对方向翻转或效应差最大的题做 trace、EvidenceBundle 和答案人工复核；
- **要回答：** 差异更可能来自搜索策略、证据利用、回答风格还是冲突处理；
- **结论形式：** 输出“稳定结论 / 模型依赖结论 / 当前无法区分”的三级证据表。

## 5.4 机制线：双源融合与 Full Context

### 5.4.1 E7 何时修复错误，何时引入干扰

- **核心对照：** E7−E2、E7−E6；
- **怎么分析：** 按 E2/E6 父状态划分，统计 Repair、Preserve、Harm、Unresolved，并检查两路证据重合、互补和冲突；
- **要回答：** 融合收益是否来自真正互补证据，以及不同 backbone 是否具有不同冲突处理能力；
- **成本：** 同时报告实验记录成本和真实在线双检索加融合成本；
- **结论边界：** E7 不是新检索器，也不能只展示 Repair 而忽略 Harm。

### 5.4.2 Full Context 是否优于选择性检索

- **核心对照：** Full Context 与 DeepSeek E1–E7 的同题比较，主要锚点应预先指定；
- **怎么分析：** P/R/F1、Strict/Soft、win/tie/loss、题型、输入/输出长度、延迟和四象限状态；
- **要回答：** 完整信息可见修复了多少检索遗漏，又有多少题因长上下文噪声或定位困难不如精选证据；
- **结论边界：** Full Context 不是 E8、不是新存储方式，也不是 oracle。

### 5.4.3 信息选择与长上下文能力的边界

- **讨论什么：** 检索的价值究竟只是省 token，还是通过去噪提高证据利用；
- **怎么分析：** 交叉比较“FC 对/检索错”“FC 错/检索对”“都对”“都错”，并联动 Evidence Recall 与答案长度；
- **要回答：** 当前瓶颈更接近信息访问还是信息利用，以及选择性检索何时应作为默认路径；
- **结论形式：** 给出带条件的机制结论，而不是简单宣布 FC 或检索绝对更优。

## 5.5 错误链：瓶颈定位与人工复核

### 5.5.1 经复核的错误阶段分布与主要瓶颈

- **分析依据：** 直接应用第 4.8 节预先定义的错误链与 codebook，不在看完结果后另造分类；
- **怎么分析：** 汇总经人工复核后的 store fidelity、retrieval coverage、budget/packing、answer utilization、fusion/long-context 与 evaluation 各阶段错误；
- **要回答：** 各系统、题型和 backbone 的实际失败阶段占比，以及哪个阶段是当前主要瓶颈；
- **关键指标：** `P(Strict correct | All-hit)`、未命中时正确率、部分命中、多余证据、预算截断；
- **结论边界：** 证据命中与正确答案是关联证据，不自动构成严格因果。

### 5.5.2 Evidence 到答案的转化效率与代表性案例

- **讨论什么：** 完整 evidence 被命中后，多少能够转化为正确答案；证据改善为何有时没有带来答案改善；
- **怎么分析：** 联合 Evidence Recall、All-hit、Strict/Soft、无关证据量和已复核错误标签，并用统一案例模板展示成功链、失败链和关键反例；
- **复核材料：** 原始 session、S3 内容、query/trace、EvidenceBundle、答案、gold 与 Judge 标签；
- **要得到：** Evidence 覆盖到答案正确的转化率、主要失败机制，以及 16–24 个可审计案例；
- **正文/附录分工：** 正文展示 4–8 个最有解释力案例，完整 casebook 放附录。

## 5.6 决策线：质量、成本与实际采用

### 5.6.1 实测质量—成本与维护开销

- **报告什么：** 按第 4.6.4 节的统一记账规则，报告一次性建库、每题检索、Answerer、失败重试、延迟和单列的 Judge 实测成本；
- **怎么分析：** 比较各条件实际质量增益与资源增量，并计算不同查询量下的建库成本摊销；
- **要回答：** 哪些复杂度真正换来了稳定质量，哪些条件被更便宜且更好的方案支配；
- **边界：** API 网络波动下的小幅 latency 差异不能过度解释。

### 5.6.2 场景化系统选择

- **场景：** 质量优先、成本优先、低延迟、持续增长、频繁更新、可审计、多跳或时间问题；
- **怎么分析：** 结合质量区间、跨 backbone 稳定性、成本、维护和错误类型建立决策矩阵；
- **要得到：** 默认方案、质量优先方案、成本优先方案与 Full Context/融合回退条件；
- **结论边界：** 不给脱离需求的单一总冠军。

### 5.6.3 对 RQ1–RQ6 的集中回答

- 每个 RQ 用“结论—证据—边界”三句式回答；
- 区分：数据直接支持的结论、人工复核支持的机制解释、仍需后续验证的假设；
- 用一张总表收束第 5 章，为第 6 章的跨论文解释与设计启示铺垫。

---

# 第 6 章 综合讨论：走向证据受控的记忆系统

第 5 章回答“各实验条件表现如何、错误发生在哪里”；第 6 章只回答一个更普遍的问题：这些结果对长期记忆系统的架构意味着什么。本章不再次罗列 E1–E7 的排名与数字，而是围绕一个中心论点展开：当前系统缺少显式管理证据状态的中间控制层。

## 6.1 证据转换缺口

将传统的“存储 → 检索 → 回答”拆为“已存储信息 → 可访问的信息 → 可回答的证据 → 被正确使用的证据”。说明信息即使存在、被检索或完整可见，也不必然已经成为充分、聚焦、连贯且可被 Answerer 使用的证据。用第 5 章的综合诊断支撑这一概念，但不重复详细数字。

## 6.2 缺失的架构层：Evidence Controller

提出位于证据访问与 Answerer 之间的 Evidence Controller。它不替代存储、Retrieval Agent 或 Answerer，而是负责四项判断：证据是否充分、证据之间是否冲突、关键陈述是否可追溯，以及下一步应该回答、继续搜索、切换来源、融合、升级到 Full Context 还是拒答。必须明确该组件是由实验结果推导出的设计建议，并非本研究已经实现或验证的系统。

## 6.3 自适应证据访问策略

提出“使用能够达到可靠证据状态的最小访问模式”这一原则：

1. 默认采用 selective retrieval，以获得聚焦、可追溯的证据；
2. 在证据不完整且另一来源可能互补时，采用受控的 multi-source fusion；
3. 在仍怀疑选择性遗漏或需要广泛跨 session 检查时，升级到 Full Context recovery；
4. 在证据仍然冲突或不足时，拒答、标记不确定性或请求澄清。

本节用一张概念表总结“当前证据状态—控制动作—预期收益—必要保护”。结尾将本章的通用结论概括为：长期记忆系统应围绕显式的证据控制机制组织，并根据充分性、冲突与来源动态选择访问路径。

---

# 第 7 章 局限与有效性威胁

建议采用双层写法：第 5 章每个结果附近写局部 caveat；本章再统一归纳，不用一句“样本较少”带过所有问题。

## 7.1 外部有效性

- 当前主实验来自一个 conversation、60 道题；
- 不能直接推广到多用户、数月记忆、不同语言和其他 benchmark；
- 真实长期增长、冲突、遗忘和更新尚未被完整模拟。

## 7.2 构念有效性

- Token F1 对同义表达和答案长度敏感；
- Judge 可能存在模型偏好与一致性问题；
- gold evidence 可能不完备，Evidence Recall 不适用于所有题；
- latency 同时受到服务和网络影响，不是纯架构指标。

## 7.3 内部有效性与因果边界

- E1–E4 的组件对照较清晰，但 R1/R2 仍是完整检索系统差异；
- S3 同时改变内容与结构，E5/E6 不能拆成单一摘要效应；
- backbone 同时用于检索与回答，当前不能完全分离两个角色；
- Full Context 与 E1–E7 是诊断性对照，而不是所有变量都完全相同的单因素实验。

## 7.4 统计结论有效性

- n=60，且只有一个 conversation；
- C3 只有 7 题，题型分析统计功效有限；
- 多条件、多指标带来多重比较风险；
- question bootstrap 只描述当前题集的不确定性，不能代表跨 conversation 方差。

## 7.5 运行与可复现性威胁

- 远程模型服务可能升级或具有随机性；
- 单次运行不能完整刻画 run-to-run variance；
- API 超时、失败和服务延迟需要被记录但难以完全控制；
- 商业或校园服务的模型内部细节不可完全观察。

## 7.6 基线与研究范围限制

- 尚未把 A-Mem、Mem0、图记忆、向量 RAG 等系统纳入同一正式矩阵；
- Full Context 当前只运行一个 backbone；
- 未做完整的 retrieval-agent × answerer 交叉组合；
- 当前重点是问答质量与检索过程，不是长期在线写入和持续重组。

## 7.7 在上述局限下仍可支持什么

用一小节正面界定结论：本研究可以支持同一 60 题内的受控、配对和机制性比较，但不能声称得到对所有长期记忆系统的普遍最优方案。

---

# 第 8 章 后续工作与开放性探索

本章不能写成愿望清单。每一项都应由第 5 章的未解释现象或第 7 章的有效性缺口推出，并注明是近期可补做、需要新实验，还是更长期研究。

## 8.1 近期可完成的验证

### 8.1.1 完成离线配对统计与人工 Casebook

补齐置信区间、DID/CoC、错误 codebook 和代表性人工复核。

### 8.1.2 重复 Judge 与人工一致性检查

对边界案例做复判，估计 Judge 稳定性与人工一致率。

### 8.1.3 重复运行与随机性评估

对少量关键条件进行多次运行，测量检索轨迹、答案和成本方差。

## 8.2 扩展数据与时间跨度

### 8.2.1 多 Conversation 与更多 LoCoMo 问题

验证当前结论能否跨人物、主题和对话结构成立。

### 8.2.2 真正持续增长的 Memory Stream

观察 store health、taxonomy drift、重复、冲突和检索成本随时间演化。

### 8.2.3 跨数据集与真实部署任务

扩展到 PersonaMem、工作助理日志或长期个人 agent 场景。

## 8.3 分离模型角色与能力

### 8.3.1 Retrieval Agent × Answerer 交叉矩阵

固定检索模型换 Answerer，或固定 Answerer 换检索模型，以区分访问能力和利用能力。

### 8.3.2 更多 Backbone 与模型规模

研究架构效应是否随模型能力、推理风格和上下文窗口改变。

### 8.3.3 Qwen Full Context 与跨 Backbone 长上下文对照

补齐 Full Context 的跨模型稳健性，而不是只比较同一模型家族。

## 8.4 自适应检索与动态路由

### 8.4.1 Selective Retrieval / Full Context Router

根据问题类型、检索置信度、Evidence Recall proxy 或冲突信号动态选择路径。

### 8.4.2 动态 Evidence Budget 与停止策略

研究 16,000 字符预算、4/6/8 actions 或置信度停止如何影响质量—成本前沿。

### 8.4.3 失败后回退机制

当检索证据不足时升级到双源融合或 Full Context，而非所有问题默认支付最高成本。

## 8.5 更可靠的多源融合

### 8.5.1 证据重复、冲突与时效检测

在融合前识别同义重复、时间冲突和过期记忆。

### 8.5.2 来源置信度与可追溯生成

让 Answerer 显式考虑来源、日期和证据可靠性。

### 8.5.3 学习式或校准式融合

研究何时采用 raw evidence、curated evidence 或两者联合。

## 8.6 Memory Store 的长期维护

### 8.6.1 增量更新、遗忘和冲突消解

研究新事实如何加入、旧事实如何失效，以及如何避免历史陈述以当前时态保留。

### 8.6.2 自动重组与 Taxonomy Health

设计层级一致性、文件粒度、重复率、陈旧度和引用完整性指标。

### 8.6.3 构建与维护成本的长期摊销

回答 curated memory 或 sharding 的收益何时能覆盖持续维护成本。

## 8.7 扩展基线与系统形态

在同一数据、问题、Answerer 和评分协议下加入 A-Mem、Mem0、图记忆、向量 RAG 与其他长期记忆系统，避免因接口和评测差异造成不可比。

## 8.8 更开放的科学问题

建议用问题形式结尾，而不是假装已有答案：

1. 当 backbone 足够强时，memory organization 仍然重要吗？
2. 文件层级何时是有用的检索先验，何时只是维护负担？
3. 能否从 store health 指标提前预测问答退化？
4. Selective Retrieval 的真正价值是压缩、去噪，还是提供结构化推理路径？
5. 长上下文与外部记忆会趋于替代关系，还是形成自适应混合系统？
6. 多源融合能否在不显著增加成本的情况下可靠处理冲突与时效？
7. 一个 memory system 的最优形式是否本质上由其 downstream consumer 决定？

---

# 第 9 章 结论

## 9.1 研究回顾

用一段话回到研究问题、系统设计和实验范围。

## 9.2 核心结论

按 RQ1–RQ6 归纳最终发现，只保留最可靠的 3–5 条结论，不重复第 5 章全部数字。

## 9.3 理论与实践价值

说明本研究对“存储—检索—模型能力”联合设计和真实系统选型分别提供了什么价值。

## 9.4 最终边界与展望

用一句严谨的边界和一句开放展望结束全文，避免宣称存在普遍最优记忆架构。

---

# References

- 统一引用格式；
- 优先引用论文、官方数据集、官方代码与模型文档；
- 网页资料只用于必要的服务和实现说明；
- 正文所有关键方法、数据与比较均应有对应来源。

---

# Appendices

## Appendix A：完整 Prompts 与 Agent 角色说明

- S3 management prompt；
- R1/R2/R3 prompt；
- Answerer prompt；
- E7 fusion prompt；
- LLM Judge prompt。

## Appendix B：工具 Schema 与系统契约

- 工具输入输出；
- round/action 定义；
- EvidenceBundle schema；
- RunRecord、checkpoint 与 failure schema。

## Appendix C：数据、题集与存储快照

- 60 题 ID 与 C1–C4 分布；
- 数据 provenance；
- S1/S2/S3 目录树和代表性文件；
- store 与 manifest hashes。

## Appendix D：完整实验配置

- 模型 alias 与 served identity；
- temperature、timeout、concurrency；
- budget 与 caps；
- batch 划分、runner 与审计规则。

## Appendix E：完整统计结果

- 所有条件的 P/R/F1、Strict/Partial/Soft；
- paired differences、win/tie/loss、CI、McNemar、DID、CoC；
- C1–C4 分层和多重比较校正结果。

## Appendix F：Evidence 与过程分析

- Evidence Recall、Any-hit、All-hit；
- rounds/actions、tool calls、budget skip；
- 检索 trace 摘要。

## Appendix G：成本核算

- 建库成本、每题查询成本、失败尝试、Judge 成本；
- E7 完整在线管线成本；
- 不同查询量下的摊销表。

## Appendix H：人工错误 Casebook

- 统一案例模板；
- 自动归因与人工复核结果；
- 评分冲突、融合 repair/harm、Full Context 四象限案例。

## Appendix I：复现与审计材料

- 版本、commit、manifest、hash；
- batch audit、PASSED markers 和 final audit；
- 环境说明与复现命令。

## Appendix J：补充图表

- 正文未放入的热力图、题型图、成本图、增长假设图和敏感性分析。

---

## 10. 全文写作规则

### 10.1 第 3、4、5 章的职责必须分开

| 章节 | 回答的问题 | 不应做什么 |
|---|---|---|
| 第 3 章 系统设计 | 系统是什么、组件如何工作 | 不解释谁分数更高 |
| 第 4 章 实验设计 | 如何公平比较、如何打分与检验 | 不提前宣布结果 |
| 第 5 章 问题分析 | 结果是什么、为什么、结论边界是什么 | 不重复长篇配置说明 |

因此，原先独立分析指南里的“分析对象、比较地图与统一统计规则”，在完整报告中应主要放入第 4.3、4.5 和 4.7；第 5.1.1 直接从总体结果开始。

### 10.2 每个结果小节使用同一证据闭环

```text
研究问题
→ 为什么选择这组对照
→ 同题效果量和不确定性
→ Evidence/trace/成本解释
→ 代表性反例与人工复核
→ 条件化结论
→ 局部 caveat
```

### 10.3 正文与附录的分工

- 正文只放决定结论的表、图和案例；
- 配置、prompt、完整逐题表和审计材料放附录；
- 正文引用附录，但不能把关键结论完全藏在附录；
- 任何“最优”“更稳定”“更省成本”的说法，都必须能追溯到正文中的效果量、区间和成本口径。

### 10.4 最终报告应形成的五个层次

1. **描述层：** 哪些条件得分高或低；
2. **比较层：** 同题改动后提高还是下降；
3. **机制层：** 变化发生在证据覆盖、利用、融合还是长上下文；
4. **边界层：** 结论在哪些模型、题型和实验范围内成立；
5. **决策层：** 不同实际需求应选择哪种系统。

只有五层都完成，第 5 章才不只是结果罗列，而能成为整份报告的中心贡献。

---

## 11. 参考结构来源

- 学校样本：[sample report.pdf](/Users/wangwenqi/Desktop/memory%20bench/sample%20report.pdf)。该报告共 92 个物理页面，采用完整学校报告前置材料，并以“问题—方法—实验—结果—小结”组织三个应用章节。
- Filesystem 论文：[filesystem-based-memory-for-llm-agents.pdf](/Users/wangwenqi/Desktop/memory%20bench/papers/primary/filesystem-based-memory-for-llm-agents.pdf)。重点参考其 §2 的系统形式化与变量边界、§3 的实验配置、§4 按 RQ 组织的结果分析，以及附录中的 prompts、配置、错误与成本材料。

本目录最终采用的是：

> 学校报告的完整外壳 + Filesystem 的 RQ 驱动证据链 + 本项目自己的双 backbone、E1–E7、Full Context、错误归因与质量—成本决策结构。
