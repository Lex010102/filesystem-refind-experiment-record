# Chapter 5 Results and Analysis — New Argument Framework

## 文件用途与使用边界

本文件只保存 Chapter 5 的新论证框架，不是正文，也不替代现有分析结果、数据文件或审计文件。现阶段已经冻结重新组织后的 RQ1–RQ6。

原始 Chapter 5 Markdown、LaTeX 与 PDF 保持不变；独立的重构版 Markdown 在对应框架确认后更新。目前 RQ1–RQ5 已完成正文重写，RQ6 的新框架已经确定，正文尚未按该框架重组。

Chapter 5 的每个 Research Question 统一采用以下论证顺序：

1. **Research Question**：明确这一节只回答什么问题；
2. **Direct Answer**：先给读者一个直接、可复述的答案；
3. **Main Evidence**：只保留支撑该答案不可缺少的比较与数字；
4. **Mechanism or Explanation**：解释证据为何呈现这种模式，但不超出实验能够支持的范围；
5. **Boundary of the Conclusion**：简短说明不能由本节推出什么，并把问题交给后续 RQ。

---

## 5.2 RQ1: Matching Memory Representation with Retrieval

### 5.2.0 RQ1 的总体论证骨架

#### 1. Research Question

**英文表述：**

> How should memory representation and retrieval be paired to support effective selective access?

**中文含义：**

> 存储表示与检索路径应当如何配合，才能把长期记忆中的信息转化为有效证据，并支持高质量回答？

RQ1 不再按照 E1–E6 逐项报分，也不再把“存储效应、检索效应、交互效应、S3 效应”写成彼此平行的多个问题。它沿下面一条主线推进：

```text
存储结构是否提供了有用的信息组织？
                    ↓
检索系统能否把这种组织转化为有效证据？
                    ↓
匹配后的存储—检索组合是否改善最终答案？
```

全文中心命题是：

> **存储结构只提供潜在机会，检索系统决定这种机会能否被兑现，最终效果取决于二者是否形成兼容的配对。**

#### 2. Direct Answer

RQ1 的直接答案由三部分构成：

1. **目录化存储没有普遍、自动的收益。** S2 只在 Qwen+R1 中出现正向点估计，而且收益主要集中在 Temporal 问题；DeepSeek 没有复现这一模式，R2 也没有从 folder/path cue 中获得稳定收益。
2. **当前 R1 是更稳定的质量导向检索路径。** 在 raw memory 和 Agent-Curated Memory 上，R1 更稳定地保留 annotated evidence 并取得较高语义质量。R2 和 R3 使用更少的 query-time calls/tokens，但这种效率伴随较低的 evidence coverage 和答案质量。
3. **Agent-Curated Memory 的收益依赖正确的访问路径。** S3+R1 相比 S2+R1 提高 Strict Accuracy、Soft Semantic Score 和 Evidence Recall，但降低 Token F1。它是最强的 curated-memory path，却不是所有 backbone 和所有指标上的统一冠军。

#### 3. Main Evidence

RQ1 正文只围绕三组证据展开：

| 递进问题 | 主要对照 | 主要用途 |
|---|---|---|
| 存储组织是否有帮助 | E3−E1；E4−E2 仅作辅助 | 判断原始内容不变时，目录或路径提示是否带来收益 |
| 检索器能否利用存储 | E2−E1、E4−E3、E6−E5 | 判断不同 retrieval path 是否把存储信息转化为有效证据 |
| Curated Memory 是否产生系统收益 | E5−E3；E1–E6 绝对均值作定位 | 判断 S3 与有效检索配对后的语义、证据和词面权衡 |

E6−E4 只保留为描述性 complete-system anchor。DID 只用于说明没有观察到可靠的 interface-level interaction，不再单列为核心研究问题。

#### 4. Mechanism or Explanation

RQ1 只解释到架构层，不进行完整根因归因。统一解释链为：

```text
Memory representation
    提供导航、组织、粒度和 provenance
                    ↓
Retrieval system
    决定搜索入口、查询更新、证据保留和停止位置
                    ↓
EvidenceBundle
    决定关键证据覆盖率、证据密度和干扰程度
                    ↓
Answerer
    将证据转化为最终答案
```

因此：

- 更清楚的目录不一定被检索器使用；
- 更大的 EvidenceBundle 不等于更完整或更集中的证据；
- 更高的 Evidence Recall 不保证 Answerer 正确利用证据；
- 更完整、更长的语义答案也可能获得较低 Token F1。

#### 5. Boundary of the Conclusion

RQ1 只回答架构质量效应，不负责回答：

- 效应是否正式跨 backbone 稳定——交给 RQ2；
- E7 双源融合是否有效——交给 RQ3；
- Full Context 是否更好——交给 RQ4；
- 错误具体发生在哪个阶段——交给 RQ5；
- 哪个系统最值得部署——交给 RQ6。

RQ1 不宣称目录化普遍有效，不把当前 R3 的结果外推到所有 curated-memory retriever，也不把 S3+R1 描述为无条件的全局冠军。

---

### 5.2.1 Does Storage Organisation Help When the Raw Information Is Unchanged?

#### 1. Research Question

> 当底层仍是相同的原始对话时，仅改变信息的目录与路径组织，能否改善检索和回答？

这一节只研究 S1 与 S2，不讨论 S3 的内容整理，也不讨论最终部署选择。

#### 2. Direct Answer

> 目录组织可以帮助特定的 Agentic Filesystem Retrieval 路径，但没有表现出普遍收益。最明确的正向信号来自 Qwen+R1，并主要集中在 Temporal 问题；这一结果没有在 DeepSeek 或 R2 路径中稳定复现。

因此，本节不是得出“目录化有效”或“目录化无效”，而是得出：

> **目录结构是一种可被利用的导航资源，其收益取决于检索器和 backbone 是否实际使用这种资源。**

#### 3. Main Evidence

**主要对照：E3−E1。** 两边都使用 R1，且保留原始 session 内容；主要变化是 S1 平铺存储变为 S2 目录化存储。

| Backbone | ΔF1 | ΔStrict | ΔSoft | ΔEvidence Recall |
|---|---:|---:|---:|---:|
| Qwen | +0.0462 | +0.0333 | +0.0250 | +0.0072 |
| DeepSeek | −0.0041 | −0.0500 | −0.0500 | −0.0302 |

Qwen 的 F1 为 19 wins、30 ties、11 losses；Strict 为 5 repairs、52 ties、3 harms。它表明存在正向观察信号，但 F1 与 Strict 的 paired-bootstrap intervals 均包含零。

Qwen 的收益主要来自 13 道 Temporal 问题：

- ΔF1 = +0.1994；
- ΔStrict = +0.3077；
- ΔSoft = +0.1923；
- ΔEvidence Recall = −0.0385。

**辅助对照：E4−E2。** R2 在 E2/E4 中使用相同的 raw-exchange index，folder name 不进入第一阶段 lexical ranking；S2 relative path 主要在 provenance observation 中出现，并可能影响后续 query。

| Backbone | ΔF1 | ΔStrict | ΔSoft | ΔEvidence Recall |
|---|---:|---:|---:|---:|
| Qwen | −0.0071 | +0.0333 | +0.0083 | −0.0014 |
| DeepSeek | −0.0141 | −0.0333 | 0.0000 | −0.0287 |

该对照只支持“R2 下 folder/path cue 没有带来稳定收益”，不能与 E3−E1 等同解释为完整目录导航效应。

#### 4. Mechanism or Explanation

Qwen Temporal 的答案质量大幅提高，但 Evidence Recall 没有同步提高。这说明其收益不太可能由“找到了更多 annotated turns”单独解释，更可能与以下现象一致：

- 目录提示帮助 R1 选择更合适的搜索入口；
- 主题路径缩小了需要继续浏览的范围；
- 时间相关信息以更容易导航和组织的形式出现；
- Answerer 更有效地利用了已经足够的证据。

这些解释是与结果一致的架构机制，不是已经完成频率估计的根因结论。正式 trace-level attribution 留给 RQ5。

#### 5. Boundary of the Conclusion

- 所有主要存储效应 interval 均包含零；
- Qwen 的收益集中在一个问题类型，而不是广泛分布；
- DeepSeek 没有复现这一方向；
- E4−E2 只识别 R2 的后续 path-cue effect；
- DID 不单列为结论，只简短报告未发现可靠的 interface-level interaction。

本节最终只说：**目录化可能帮助特定 retrieval–backbone 组合，但 Main-60 不支持普遍的目录优势。**

---

### 5.2.2 Which Retrieval Path Converts Stored Information into Useful Evidence?

#### 1. Research Question

> 当可用存储给定时，哪种 retrieval path 更能找到并保留决定答案的证据，而不是仅仅返回更多文本？

这一问题统一比较三种固定存储上的访问路径：

- S1：E2−E1；
- S2：E4−E3；
- S3：E6−E5。

#### 2. Direct Answer

> 当前 R1 是更稳定的质量导向访问路径。R2 和 R3 使用更少的记录到的 query-time model calls/tokens，但通常形成更大的 EvidenceBundle，并伴随更低的 annotated-evidence coverage 和语义质量。

因此不能把 R2/R3 简化为“更差的检索器”。准确定位是：

> **R1 更偏向质量；R2/R3 更偏向查询效率，但当前实现存在可观察的质量代价。**

#### 3. Main Evidence

**S1 上的 R2−R1：E2−E1。**

| Backbone | ΔF1 | ΔStrict | ΔSoft | ΔEvidence Recall |
|---|---:|---:|---:|---:|
| Qwen | +0.0082 | −0.0500 | −0.0500 | −0.0330 |
| DeepSeek | −0.0557 | −0.0500 | −0.1000 | −0.0805 |

Qwen 的轻微 F1 上升没有转化为语义提升，因此它是 lexical–semantic disagreement，而不是 R2 质量优势。

**S2 上的 R2−R1：E4−E3。**

| Backbone | ΔF1 | ΔStrict | ΔSoft | ΔEvidence Recall |
|---|---:|---:|---:|---:|
| Qwen | −0.0451 | −0.0500 | −0.0667 | −0.0417 |
| DeepSeek | −0.0657 | −0.0333 | −0.0500 | −0.0790 |

两个 backbone 的主要答案指标和 Evidence Recall 均同向下降，这是 raw-memory 部分最清楚的 retrieval-path pattern。

**S3 上的 R3−R1：E6−E5。**

| Backbone | ΔF1 | ΔStrict | ΔSoft | ΔEvidence Recall | ΔBundle characters |
|---|---:|---:|---:|---:|---:|
| Qwen | −0.0135 | −0.0500 | −0.0583 | −0.0891 | +5,109.1 |
| DeepSeek | −0.0364 | −0.0833 | −0.0917 | −0.2371 | +5,457.3 |

R3 返回更多文本，但 Evidence Recall 和答案质量同时下降。当前专门适配 S3 的检索路径没有优于通用 R1。

**查询效率只作为辅助证据。** R2/R3 使用更少的 query-time calls/tokens；详细 token、failure、recovery 与 Pareto 结果留给 RQ6，不在 RQ1 做最终性价比判断。

#### 4. Mechanism or Explanation

三组结果共同说明：

> **Evidence quantity is not evidence quality.**

较大的 EvidenceBundle 可能仍然：

- 包含大量相关但不决定答案的内容；
- 找到正确 session，却遗漏关键的相邻 turn；
- 因 query formulation 或 ranking 错过关键 locator；
- 因 action cap 或 early stopping 停在不完整证据上；
- 增加 Answerer 的筛选和组合负担。

R1 的优势更可能来自灵活的 observation–action loop：它可以查看文件、修正查询、继续搜索并根据当前证据决定下一步。这种灵活性在当前 S1、S2 和 S3 表示上更稳定地转化为有效证据。

#### 5. Boundary of the Conclusion

- E2−E1、E4−E3、E6−E5 比较的是完整 access system，不隔离 BM25、grep、query generation 或 local expansion 等单个组件；
- R1 rounds 与 R2/R3 actions 不是相同单位；
- E6−E5 没有预先声明 bootstrap interval，因此 R3 underperformance 应限定在 observed Main-60 pipelines；
- 具体证据在哪一步丢失属于 RQ5；
- 查询成本是否值得质量代价属于 RQ6。

本节最终只说：**当前 R1 更稳定地把存储内容转化为有效证据；当前 R2/R3 的效率收益并非无损替代。**

---

### 5.2.3 Does Curated Memory Add Value When Paired with Effective Retrieval?

#### 1. Research Question

> 当两种表示都通过当前更有效的 R1 访问时，Agent-Curated Memory 是否比目录化原始对话产生更高的端到端质量？

主要对照是 E5−E3：

```text
E3 = S2 + R1
E5 = S3 + R1
```

#### 2. Direct Answer

> S3+R1 在两个 backbone 中都提高语义正确性和 annotated-evidence coverage，但降低 Token F1。Agent-Curated Memory 的价值主要体现为更完整的证据和更好的语义回答，而不是更高的词面重合。

因此，E5 应定位为：

> **最强的 curated-memory path 和重要的 semantic/evidence leader，而不是所有指标上的统一冠军。**

#### 3. Main Evidence

**E5−E3 的完整系统表示对照：**

| Backbone | ΔF1 | ΔStrict | ΔSoft | ΔEvidence Recall |
|---|---:|---:|---:|---:|
| Qwen | −0.0463 | +0.0333 | +0.0250 | +0.1034 |
| DeepSeek | −0.0367 | +0.0500 | +0.0417 | +0.1149 |

两个 backbone 都呈现同一模式：

```text
Token F1 下降
        +
Strict / Soft 上升
        +
Evidence Recall 上升
```

**E1–E6 绝对均值用于定位，而不是重新做排行榜：**

- Qwen：E3 的 Token F1 最高；E5 的 Strict、Soft 和 Evidence Recall 最高；
- DeepSeek：E1 的 Token F1 和 Soft 最高；E1 与 E5 的 Strict 并列最高；E5 的 Evidence Recall 最高；
- E5 明显强于同一 S3 上的 E6，因此 S3 的收益依赖其访问方式。

#### 4. Mechanism or Explanation

从 E3 到 E5：

- Qwen 平均答案长度从 11.97 增至 16.13 normalised tokens，约增加 35%；
- DeepSeek 从 21.72 增至 29.17，约增加 34%；
- token Precision 下降而 Recall 上升；
- Evidence Recall 与语义分数同时上升。

这一模式与以下解释一致：

- S3 将跨 session 的相关事实共同组织；
- curated facts 提供更完整的属性和上下文；
- Answerer 因此生成更完整、解释性更强或措辞不同的答案；
- LLM judge 认可其语义完整性，但额外文字和表达差异降低 Token F1。

答案长度没有被独立控制，因此只能说这种模式与 broader-response explanation 一致，不能把长度写成 F1 下降的唯一原因。

#### 5. Boundary of the Conclusion

- E5−E3 同时改变文本表达、粒度、组织、去重和 provenance，不是纯粹的单变量 curation effect；
- E5 不是所有 backbone、所有指标和所有成本维度上的统一赢家；
- E6−E4 只作为描述性 complete-system anchor，不能隔离 curation；
- F1 与 LLM judge 分歧的系统性分析属于 RQ5；
- S3 construction cost 与最终部署建议属于 RQ6。

本节最终只说：**Agent-Curated Memory 在与有效检索路径配对时能够改善语义质量和证据覆盖，但这种收益伴随词面指标权衡。**

---

### 5.2 结尾的 RQ1 综合回答

RQ1 结尾不再重复全部数字，只用一段完成综合：

> RQ1 shows that memory structure does not improve performance automatically. Folder organisation provides a conditional benefit only when the retrieval path and backbone can exploit its navigation cues. Across the tested raw and curated representations, R1 more consistently converts stored information into annotated evidence and semantically correct answers, whereas R2 and R3 mainly reduce recorded query-time effort and incur observable quality losses. When paired with R1, Agent-Curated Memory improves semantic correctness and evidence coverage relative to foldered raw sessions, but lowers Token F1. The effective unit of design is therefore the storage–retrieval pairing rather than either component in isolation.

对应的中文逻辑是：

> 存储结构不会自动改善性能；它必须被合适的检索器利用。当前 R1 更稳定地把 raw memory 和 curated memory 转化为有效证据，而 R2/R3 的查询效率伴随质量损失。S3 与 R1 配对后能够提高语义正确性和证据覆盖，但降低 Token F1。因此，长期记忆系统真正需要优化的是存储—检索配对，而不是孤立地优化某一个组件。

---

## RQ1 主文与辅助材料的重新分工

### 正文保留

1. E3−E1 的核心结果及 Qwen Temporal 集中性；
2. E2−E1、E4−E3、E6−E5 的主要质量和 Evidence Recall 结果；
3. E5−E3 的 lexical–semantic trade-off；
4. 一张精简的 E1–E6 条件均值表；
5. 一张或两张直接服务于三问主线的图；
6. 每个子问题的一段简短 conclusion boundary。

### 降为辅助证据或移至附录

- E4−E2 的完整诊断矩阵；
- DID 的详细表格与 category-level DID；
- E6−E4 与其他 sensitivity anchors；
- 完整 Precision/Recall、Any-hit、All-hit 和 multi-source 表；
- Evidence Recall × Strict 的完整交叉矩阵；
- 详细 category 表，只在正文保留解释主结论所必需的 Temporal 结果；
- 具体 trace 与错误阶段归因，交给 RQ5；
- failed attempts、recovery、construction cost 和 Pareto 分析，交给 RQ6。

---

## 5.3 RQ2: Robustness across Backbone Models

### 5.3.0 RQ2 的总体论证骨架

#### 1. Research Question

RQ2 只回答一个核心问题：

> Which findings from RQ1 remain directionally consistent across the Qwen and DeepSeek pipelines, and which depend on the backbone model?

对应的中文含义是：

> RQ1 中哪些架构结论能够在 Qwen 和 DeepSeek 两个测试 pipeline 中保持方向，哪些结论依赖具体 backbone？

RQ2 不重新比较“哪个条件最好”，也不重新完整报告 E1–E7。分析范围必须明确区分：

- 架构稳定性分析使用 E1–E6 中五个主要 RQ1 contrasts；
- E4−E2 是受限的 path-cue 辅助比较，不进入主要稳定性矩阵；
- E7 只用于 E1–E7 总体回答风格的描述性背景，不分析融合效应；
- Full Context 没有匹配的 Qwen 运行，因此不进入 RQ2。

本节的主线是：

```text
RQ1 中哪些架构效应保持方向？
                    ↓
哪些效应依赖 backbone？
                    ↓
为什么词面差距远大于语义差距？
```

Token F1 差距是解释跨 backbone 结果时需要处理的测量现象，不是与架构稳健性并列的第二个研究问题。

#### 2. Direct Answer

直接答案分为三组，并保持以下顺序：

1. **方向稳定的架构结论。**在 S2 上，R1 的答案质量与 Evidence Recall 高于 R2；在 S3 上，R1 高于当前 R3；S3+R1 相对 S2+R1 稳定表现为 Token F1 下降、语义质量和 Evidence Recall 上升。
2. **依赖 backbone 的结论。**在 S1 上，R2 的语义质量和 Evidence Recall 均下降，但 Token F1 方向不同；S2 对 R1 的正向作用只出现在 Qwen pipeline 中。
3. **指标层面的结论。**Qwen 的 Token F1 明显高于 DeepSeek，但两个 pipeline 的平均 Strict Accuracy 和 Soft Semantic Score 接近。因此，Token F1 差距不能直接解释为同等规模的语义能力差距。

RQ2 的一句话总论点是：

> 固定存储上的检索路径排序，以及 S3+R1 的词面—语义权衡，在两个 backbone pipeline 中相对稳定；改变存储组织本身是否有帮助，则明显依赖 backbone。

#### 3. 指标判断层级

RQ2 不再用 Token F1 与 Strict Accuracy 任意合并成单一“稳定”标签。指标按以下层级解释：

| 判断层 | 指标 | 用途 |
|---|---|---|
| 主要质量判断 | Strict Accuracy、Soft Semantic Score | 判断语义质量方向；只有二者共同保持方向时，才称为 semantic direction 一致 |
| 证据支持 | Evidence Recall | 判断标注证据访问方向 |
| 诊断指标 | Token F1 | 判断词面重叠方向，以及它是否与语义方向一致 |

“Stable”只能写成 **directionally stable across the two tested pipelines**。它不表示统计显著、效应量相同或 model-independent。

---

### 5.3.1 Which RQ1 Findings Remain Directionally Stable?

本节是 RQ2 的核心证据，必须放在跨 backbone 汇总得分之前。

使用一张紧凑效应矩阵，保留五个主要 contrasts：

| Contrast | Semantic direction | Evidence Recall direction | Token F1 direction | 直接结论 |
|---|---|---|---|---|
| E4−E3 | 两个 backbone 的 Strict/Soft 均下降 | 均下降 | 均下降 | 稳定负向 |
| E6−E5 | 两个 backbone 的 Strict/Soft 均下降 | 均下降 | 均下降 | 稳定负向 |
| E5−E3 | 两个 backbone 的 Strict/Soft 均上升 | 均上升 | 均下降 | 稳定的词面—语义/证据权衡 |
| E2−E1 | 两个 backbone 的 Strict/Soft 均下降 | 均下降 | 方向不同 | 语义和证据方向稳定，词面方向依赖 backbone |
| E3−E1 | Strict/Soft 方向不同 | 方向不同 | 方向不同 | Backbone-dependent |

正文表格必须同时保留实际 effect values，不能只放箭头。关键数字如下：

| Contrast | Qwen ΔF1 / ΔStrict / ΔSoft / ΔER | DeepSeek ΔF1 / ΔStrict / ΔSoft / ΔER |
|---|---:|---:|
| E4−E3 | −0.0451 / −0.0500 / −0.0667 / −0.0417 | −0.0657 / −0.0333 / −0.0500 / −0.0790 |
| E6−E5 | −0.0135 / −0.0500 / −0.0583 / −0.0891 | −0.0364 / −0.0833 / −0.0917 / −0.2371 |
| E5−E3 | −0.0463 / +0.0333 / +0.0250 / +0.1034 | −0.0367 / +0.0500 / +0.0417 / +0.1149 |
| E2−E1 | +0.0082 / −0.0500 / −0.0500 / −0.0330 | −0.0557 / −0.0500 / −0.1000 / −0.0805 |
| E3−E1 | +0.0462 / +0.0333 / +0.0250 / +0.0072 | −0.0041 / −0.0500 / −0.0500 / −0.0302 |

正文只分三段解释：

1. 三个方向稳定结果：E4−E3、E6−E5、E5−E3；
2. 一个语义和证据方向稳定、词面方向依赖 backbone 的结果：E2−E1；
3. 一个全面依赖 backbone 的结果：E3−E1。

不要再次逐个 contrast 写成长篇分析，也不要在这里重复成本与题型结果。

**图片位置：**Figure 5.3 放在本节效应矩阵与文字解释之后。沿用现有六项 effect 图，其中 E4−E2 作为辅助 path-cue 比较；caption 明确 connector 不是 confidence interval 或 significance test。

---

### 5.3.2 Why Does Token F1 Diverge More Than Semantic Quality?

这一节是指标解释，不是 backbone 排名。

使用一张紧凑表报告 E1–E7 的等权描述性均值：

| Metric | Qwen | DeepSeek |
|---|---:|---:|
| Token Precision | 0.3411 | 0.1957 |
| Token Recall | 0.6774 | 0.6884 |
| Token F1 | 0.3972 | 0.2636 |
| Strict Accuracy | 0.7262 | 0.7119 |
| Soft Semantic Score | 0.7619 | 0.7560 |
| Mean normalised answer length | 14.03 | 25.35 |

必须紧邻表格说明：

- 这些是同一批 60 题在 E1–E7 上的 equal-weight descriptive means；
- 七个条件复用同一批问题，不能解释为每个 backbone 有 420 个独立样本；
- E7 在这里仅用于总体回答风格背景，其融合效应属于 RQ3。

解释分为两层：

1. **Answer-style interpretation。**DeepSeek 答案约长 80.7%，Token Recall 略高 0.0110，但 Token Precision 低 0.1454。额外解释、限定语和同义表达会增加候选答案 token 数，并在算术上压低 Token F1。该结果是 measured association 和 partial explanation，不证明答案长度是唯一原因。
2. **Architecture-adaptation interpretation。**在 E3–E6 中，DeepSeek 不仅 Precision 较低，Recall 与语义分数也下降。因此 verbosity 不能解释全部差异。剩余模式与搜索行为、证据选择或 EvidenceBundle 利用差异相一致，但 RQ2 不进行正式根因归因；根因统一留给 RQ5。

---

### 5.3.3 Answer to RQ2 and Boundary

本节先用下面一段直接回答 RQ2：

> Retrieval-path ordering is more robust across the two tested backbone pipelines than the benefit of changing storage organisation. R1 remains the stronger quality-oriented access path on S2 and S3, and S3+R1 preserves the same lexical–semantic trade-off. In contrast, the benefit of folder organisation under R1 is backbone-dependent.

然后只保留三个核心边界：

1. 结论只适用于 Qwen 和 DeepSeek 两个 tested end-to-end pipelines；
2. Backbone 同时控制 Retrieval Agent 与 Answerer，因此不能拆分两者对跨 backbone 差异的贡献；
3. 方向一致不等于统计显著、效应量相同或 model-independent。

Full Context 的排除、E7 的使用范围和五个主要 contrast 的选择已在 5.3 开头说明，不在结尾重复。

---

## RQ2 主文与辅助材料的重新分工

### 正文保留

1. 一张五个主要 contrast 的方向与实际效应矩阵；
2. 一张 Precision、Recall、F1、Strict、Soft 和答案长度的紧凑表；
3. 三段架构稳定性解释；
4. 两层 Token F1 差距解释；
5. 一段直接回答和三个结论边界；
6. Figure 5.3 沿用现有六项 effect 图，插入 5.3.1；E4−E2 仅作辅助结果，不进入五项主要效应矩阵。

### 删除、移交或保留在审计材料

- E1–E7 的逐条件完整得分表移至附录或审计材料；
- E4−E2 保留为辅助 path-cue 结果，不进入主要稳定性矩阵；
- 逐 contrast 的长篇重复解释删除；
- Evidence Recall 的详细诊断与题型结果不在 RQ2 重复；
- 查询成本和效率比较交给 RQ6；
- 检索、证据选择与 Answerer 利用的正式根因归因交给 RQ5；
- E7 的融合效应交给 RQ3；
- Full Context 的比较交给 RQ4。

---

## 后续更新规则

1. RQ2 正文已按上述三问顺序重写；后续修订也不得重新按 E1–E6 逐项陈列。
2. 每一问先写 Direct Answer，再放数字，不能让读者从表格中自行寻找结论。
3. Main Evidence 只保留回答该问题不可缺少的指标；完整审计数字继续保存在分析产物与附录中。
4. Mechanism 使用“supports”“is consistent with”等受约束表述；完整根因归因只在 RQ5 中完成。
5. RQ4–RQ6 后续也按 Research Question → Direct Answer → Main Evidence → Mechanism or Explanation → Boundary 的顺序重新组织。

---

## 5.4 RQ3: Dual-Source Fusion

### 5.4.0 RQ3 的总体论证骨架

#### 1. Research Question

RQ3 只回答一个核心问题：

> Does deterministic fusion of the E2 and E6 EvidenceBundles convert their complementary evidence into better answers without losing answers already solved by either parent?

对应的中文含义是：

> E2 与 E6 是否提供了互补的证据访问机会，E7 能否把这种互补转化为更好的答案，同时避免损失父系统已经答对的问题？

该核心问题通过三个操作性子问题展开：

1. E7 相对 E2 和 E6 的答案质量与 Evidence Recall 是否提高？
2. 两个父系统是否具有可观测的答案级互补和标注来源覆盖互补？
3. E7 修复、保留和损失了多少互补机会？

本节的单一论证链是：

```text
Observed fusion benefit
          ↓
Complementarity opportunity
          ↓
Conversion into Repair / Preserve / Harm / Unresolved
```

E7 不是第三个 retriever。它复用已经完成的 E2 与 E6 EvidenceBundles，不执行新检索，采用固定的确定性融合规则，并只调用一次共享 Answerer。

#### 2. Direct Answer

直接答案按以下顺序表达：

1. **互补机会存在。**E2 与 E6 在回答正确性和标注来源覆盖上均表现出可观测互补。每个 backbone 都有 10 题仅一个父系统 Strict-correct，且两条路径分别贡献独有的 gold-source coverage。
2. **证据覆盖稳定扩大。**E7 相对两个父系统均明显提高 Evidence Recall，但本节没有新增显著性检验，因此不能写成 statistically significant improvement。
3. **Qwen 的收益有限且依赖比较对象。**相对 E2，E7 的 Strict Accuracy、Soft Semantic Score 和 Evidence Recall 提高，但 Token F1 下降；相对 E6，Strict 与 Soft 持平，Evidence Recall 提高，而 Token F1 下降。
4. **DeepSeek 的收益更广泛。**E7 相对 E2 和 E6 的 Precision、Recall、Token F1、Strict Accuracy、Soft Semantic Score 与 Evidence Recall 均提高。
5. **互补机会没有被完全转化。**E7 没有达到 post-hoc parent oracle，也没有保留所有父系统已经答对的问题。它既产生 Repair，也产生 Harm。
6. **结论具有条件性。**E7 有效利用了部分互补性，但收益随 backbone 和题型变化，不能表述为无条件优于两个父系统。

RQ3 的一句话总论点是：

> E2 and E6 provide complementary access opportunities, but the value of E7 depends on whether the shared Answerer can convert the expanded evidence into a correct answer while preserving already-correct parent outcomes.

#### 3. 指标与诊断层级

RQ3 必须区分三个层面：

| 层面 | 主要指标 | 回答的问题 |
|---|---|---|
| 最终答案效果 | Strict Accuracy、Soft Semantic Score、Token F1 | E7 是否改善回答质量，以及词面与语义方向是否一致 |
| 互补机会 | 父系统 Strict-correctness profile、source-ID Jaccard、unique gold coverage、Evidence Recall | 两条父路径是否到达不同位置并解决不同问题 |
| 转化结果 | Repair、Preserve、Harm、Unresolved、parent-oracle gap | E7 将多少机会转化为正确答案，又损失多少已有正确答案 |

Strict Accuracy 与 Soft Semantic Score承担主要语义质量判断；Evidence Recall支持证据访问解释；Token F1作为词面诊断指标。Repair、Preserve、Harm 与 Unresolved 均由 Strict Accuracy 定义。

---

### 5.4.1 Main Evidence: Benefit, Opportunity, and Conversion

#### A. Observed Fusion Benefit: E7 versus Each Parent

先用四行紧凑表报告 E7 相对每个父系统的 paired mean difference。答案指标使用同一批 60 题；Evidence Recall 使用 58 道 evidence-eligible questions。

| Backbone | Contrast | ΔF1 | ΔStrict | ΔSoft | ΔEvidence Recall | 直接解释 |
|---|---|---:|---:|---:|---:|---|
| Qwen | E7−E2 | −0.0340 | +0.0667 | +0.0417 | +0.1178 | 语义质量和证据覆盖提高，但词面重叠下降 |
| Qwen | E7−E6 | −0.0122 | 0.0000 | 0.0000 | +0.0632 | 语义质量持平，证据覆盖提高，F1下降 |
| DeepSeek | E7−E2 | +0.0398 | +0.0500 | +0.0917 | +0.0977 | 主要质量和证据指标均提高 |
| DeepSeek | E7−E6 | +0.0614 | +0.0833 | +0.0917 | +0.1695 | 主要质量和证据指标均提高 |

正文不逐指标重复整张表，只总结两点：

1. Qwen 上的融合收益主要是相对 E2 的语义与覆盖提升，E7 并未语义上超过 E6；
2. DeepSeek 上的融合收益更广泛，E7 相对两个父系统均呈一致正向点估计。

Precision 与 Recall 的完整差值可继续保存在表格或审计材料中，但正文不逐项解释。若保留完整值：Qwen E7−E2 为 `−0.0425/+0.0194`，E7−E6 为 `−0.0028/−0.0131`；DeepSeek E7−E2 为 `+0.0408/+0.0341`，E7−E6 为 `+0.0498/+0.1280`。

**Figure 5.4 位置：**固定放在 Direct Answer 之后、5.4.1 的 effect table 之前，用现有图片说明 E7 复用 E2 与 E6 bundles、不执行新检索，并调用一次共享 Answerer。

#### B. Complementarity Opportunity

互补机会必须分别在答案层和证据访问层说明。

**答案级互补：**

| Backbone | Both correct | E2 only | E6 only | Neither | Exactly one parent correct | Parent oracle | E7 correct |
|---|---:|---:|---:|---:|---:|---:|---:|
| Qwen | 37 | 3 | 7 | 13 | 10 | 47 | 44 |
| DeepSeek | 36 | 6 | 4 | 14 | 10 | 46 | 45 |

每个 backbone 都有 10 题只被一个父系统答对。因此，E2 和 E6 的成功集合并不相同，存在可观测的答案级互补机会。

**标注来源覆盖互补：**

| Backbone | E2 Evidence Recall | E6 Evidence Recall | Union/E7 Evidence Recall | Mean source-ID Jaccard | Either parent adds unique gold coverage | Union complete |
|---|---:|---:|---:|---:|---:|---:|
| Qwen | 0.7816 | 0.8362 | 0.8994 | 0.1956 | 14/58 | 49/58 |
| DeepSeek | 0.7974 | 0.7256 | 0.8951 | 0.1587 | 19/58 | 49/58 |

这些结果只能证明两条路径到达了不同的记录位置，并分别贡献独有的标注来源覆盖。source-ID Jaccard 不测量文本或语义相似度，也不能证明证据之间不存在冲突。

若报告 occurrence-level 独有 gold coverage，必须与 question-level 数量分开：Qwen 的 E2-only/E6-only gold-source occurrences 为 `7/11`，DeepSeek 为 `13/10`；每个 backbone 共 82 个标注来源 occurrences。完整 occurrence 表和 Jaccard 空集处理规则可下沉附录或审计材料。

#### C. Conversion of the Opportunity

使用第二个紧凑 panel 报告 E7 如何处理父系统提供的机会：

| Backbone | Repair | Preserve | Harm | Unresolved | Preserve/oracle-correct | Repair/neither-correct | Harm/oracle-correct | E7−oracle |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| Qwen | 1 | 43 | 4 | 12 | 43/47 | 1/13 | 4/47 | −3 |
| DeepSeek | 3 | 42 | 4 | 11 | 42/46 | 3/14 | 4/46 | −1 |

三个恒等式用于连接 parent oracle 与 E7：

```text
E7 correct = Preserve + Repair
Parent oracle = Preserve + Harm
E7 − Parent oracle = Repair − Harm
```

因此：

- Qwen：`44 = 43 + 1`，`47 = 43 + 4`，净差为 `−3`；
- DeepSeek：`45 = 42 + 3`，`46 = 42 + 4`，净差为 `−1`。

“利用互补机会”还需要区分两个不同分母：

- 对仅一个父系统正确的 10 题，E7 保持正确的数量为 Qwen `6/10`、DeepSeek `7/10`；
- 对两个父系统都错的问题，Repair 为 Qwen `1/13`、DeepSeek `3/14`。

Harm 均为 4 题，但条件率分别为 Qwen `4/47 = 8.51%` 与 DeepSeek `4/46 = 8.70%`。

**Figure 5.5 位置：**放在 conversion 表之后，用现有流图展示 Both/E2-only/E6-only/Neither 如何流向 Repair、Preserve、Harm 与 Unresolved。正文不再逐格复述图片中的全部流量。

---

### 5.4.2 Interpretation of the Observed Pattern

本节解释观察模式，但不提前替 RQ5 完成根因归因。

#### A. Why Fusion Has an Opportunity to Help

低 source-ID overlap、父系统独有的 gold-source coverage，以及每个 backbone 各 10 道 exactly-one-parent-correct questions，共同说明 raw-dialogue path 与 curated-memory path 并非重复系统。

两种表示可能分别保留原始事实、主题组织、时间关系或跨 session 连接，但这些属于与架构设计一致的候选解释。RQ3 只证明访问位置和成功集合不同，不能仅凭 Jaccard 证明具体语义角色。

#### B. Why Complementarity Does Not Guarantee a Correct Fused Answer

E7 低于 parent oracle 的原因在结果层面表现为：

- 它没有保留所有 oracle-correct cases；
- 它只能修复一部分 neither-correct cases；
- Repair 与 Harm 同时存在。

因此，更多覆盖并不自动转化为正确答案。重复内容、竞争状态、额外回答长度或 Answerer 的证据选择都可能解释 conversion gap，但这些只能表述为候选机制。正式 trace 归因留给 RQ5。

#### C. Question-Type Heterogeneity

正文只保留三个最有解释力的描述性结果：

1. **DeepSeek Temporal：**`R/P/H/U = 2/9/1/1`，F1、Strict、Soft 与 Evidence Recall 相对两个父系统均提高，是观察到的最完整融合收益。
2. **Qwen Multi-hop：**`R/P/H/U = 1/9/0/3`，出现 1 个 Repair、没有 Harm，并且 Strict/Soft 相对两个父系统均提高；Token F1仍下降，因此语义与词面方向不同。
3. **Qwen Single-hop：**`R/P/H/U = 0/21/3/3`，包含 Qwen 四个 Harm 中的三个且没有 Repair，是最强的 possible-interference signal；它不能单独证明额外证据导致错误。

完整题型矩阵移至附录或审计材料。Open-domain 只有 7 道答案题和 5 道 evidence-eligible questions，不形成独立一般性结论。所有题型结果均为 exploratory subgroup patterns，而不是已证实的题型交互效应。

---

### 5.4.3 Answer to RQ3 and Boundary

RQ3 的最终直接答案是：E2 与 E6 提供可测量的答案级和标注来源覆盖互补性，E7 能够利用其中一部分。它在两个 backbone 上均扩大 Evidence Recall；在 Qwen 上形成有限且 parent-dependent 的语义收益，在 DeepSeek 上形成更广泛的答案质量提升。然而，E7 没有保留全部父系统正确答案，也没有达到 post-hoc parent oracle。因此，双源融合是有条件的改进，而不是对任一父系统的普遍替代。

正文只保留以下结论边界：

1. E7 不执行新检索；它评估的是两个既有访问路径的固定确定性融合，而不是第三个 retriever。
2. 答案指标使用每个 backbone 的 60 题，Evidence Recall 使用 58 道 evidence-eligible questions。Repair/Harm 仅由 Strict Accuracy 定义；Partial 与 Incorrect 均视为 non-correct。
3. source-ID Jaccard 与 gold source IDs 测量标注位置覆盖，不是语义互补度，也不是最小或穷尽的推理证据链。
4. Parent oracle 使用评估后的 gold outcome labels，是 post-hoc 诊断参照，不可部署，也不是严格数学上限；E7 可以修复两个父答案均不正确的问题。
5. 每个父 EvidenceBundle 的上限为 16,000 characters，E7 的合并输入最多为 32,000 characters。因此，本实验估计的是完整 E7 系统条件，不能把全部收益单独归因于来源多样性，而忽略更大的合并证据容量。
6. RQ3 没有新增置信区间或显著性检验。方向和题型结果均为描述性证据，不表示普遍或统计显著的融合优势。
7. Harm 只能称为 possible interference；正式根因归因交给 RQ5，双父路径的完整在线成本交给 RQ6。

---

## RQ3 主文与辅助材料的重新分工

### 正文保留

1. 一段 E7 构成说明和现有 Figure 5.4；
2. 一张四行 E7−parent effect 表；
3. 一组紧凑的 complementarity opportunity panels；
4. 一张 Repair/Preserve/Harm/Unresolved conversion 表和现有 Figure 5.5；
5. 三个题型观察；
6. 一段最终答案和七项简短边界。

### 下沉附录、审计材料或其他 RQ

- 完整 Precision/Recall 差值保留在表格或审计材料，不逐项写入正文；
- gold-source occurrence-level 完整分解与 Jaccard 空集规则移至附录；
- 完整题型矩阵移至附录；
- Repair/Harm 个案与因果 trace 归因交给 RQ5；
- E7 双父路径执行成本、token 开销和部署取舍交给 RQ6；
- 正文不再保留一个重复所有表格结论的长篇“Answer to RQ3”。

---

## RQ3 正文与后续修订规则

1. RQ3 正文已按 Observed benefit → Complementarity opportunity → Conversion 的顺序重写；后续修订继续保持该顺序。
2. 每个结论先说明比较对象，尤其区分 Qwen 的 E7−E2 与 E7−E6。
3. “Complementarity”必须限定为 answer-level 或 annotated-source-access level，不写成已证明的 semantic complementarity。
4. “Improvement”只报告描述性方向和实际 effect values，不使用 statistically significant 等未经检验的措辞。
5. Mechanism 使用“is consistent with”“may reflect”等限定表述，正式根因留给 RQ5。
6. Main text 不重复 Figure 5.5 中的全部流量，也不重复完整题型矩阵。

---

## 5.5 RQ4: Full Context versus Selective Retrieval

### 5.5.0 RQ4 的总体论证骨架

#### 1. Research Question

RQ4 只提出一个核心问题：

> **Does complete context visibility outperform selective evidence access, or do the two access regimes provide different advantages?**

中文含义是：

> 在 DeepSeek-family 的诊断比较中，完整提供全部 30 个 session 是否真正优于选择性检索，还是两种 evidence-access regime 分别具有不同优势？

RQ4 不再并列提出“总体得分、题型差异、错误机制”三个问题。它沿一条主线推进：

```text
Full Context 是否在总体质量上支配选择性检索？
                         ↓
如果没有，双方互有胜负体现了什么访问取舍？
                         ↓
完整覆盖与选择性聚焦分别适合什么信息需求？
```

分析范围作如下限定：

- E7 是同题不对称分析的主要选择性检索参照；
- E1 与 E5 用于确认总体结论并非只依赖 E7；
- 完整 E1–E7 分数保留在附录或审计材料；
- Full Context 与 E1–E7 属于 DeepSeek-family 比较，但 served-model identifier 不完全相同，因此不是严格的单变量 backbone ablation。

#### 2. Direct Answer

正文开头直接给出三个结论：

1. **Full Context 具有轻微的平均语义优势，但不形成全面支配。**它取得最高 Strict Accuracy 与 Soft Semantic Score，但只比 E1、E5 和 E7 各多答对 1 道题。
2. **两种访问方式在同一批题目上互有胜负。**相对 E7，Full Context 独有 4 个 Strict-correct cases，而 E7 独有 3 个；Full Context 的 Token F1 也低于 E1、E5 和 E7。
3. **核心关系是 coverage–focus trade-off。**Full Context 更可能帮助需要跨 session 聚合的分散证据；选择性检索仍可能通过压缩输入、突出时间锚点和减少竞争信息而获益。

最后补充一句直接回答：

> **Complete visibility reduces some access failures, but it does not remove long-context reasoning and evidence-utilisation errors.**

#### 3. 指标与证据层级

RQ4 使用明确的判断层级，避免不同指标承担相同作用：

1. **Strict Accuracy 与 Soft Semantic Score：**主要回答最终语义质量是否提高；
2. **同题四象限：**主要判断 Full Context 是否真正支配选择性检索；
3. **题型结果：**解释 coverage–focus trade-off 在何种信息需求上表现出来；
4. **Token F1、Precision 与 Recall：**用于诊断词面匹配和回答风格，不单独决定优劣；
5. **输入字符规模：**支持“完整覆盖与证据聚焦”的访问差异，不在 RQ4 中承担部署成本排序；
6. **Evidence Recall：**不适用于 Full Context，因为它没有构造检索级 EvidenceBundle。

---

### 5.5.1 Does Full Context Dominate Selective Retrieval?

本节只回答“Full Context 是否全面优于选择性检索”，不提前展开根因。

#### A. Aggregate Semantic Advantage Is Small

正文使用一张紧凑主表，只保留 Full Context 与三个有解释力的选择性锚点：

| Condition | Correct | Strict | Soft | Token F1 |
|---|---:|---:|---:|---:|
| Full Context | 46/60 | 0.7667 | 0.8250 | 0.2445 |
| E1 | 45/60 | 0.7500 | 0.8083 | 0.3013 |
| E5 | 45/60 | 0.7500 | 0.8000 | 0.2604 |
| E7 | 45/60 | 0.7500 | 0.8000 | 0.2854 |

该表只支持以下直接结论：

- Full Context 的 Strict 优势仅为 `1/60`；
- 它的 Soft 均值最高，但幅度有限；
- 它在 Token F1 上低于三个选择性锚点；
- 因此“最高平均语义分数”不能改写成“所有质量指标均更好”。

完整 E1–E7 表不在正文重复，可移至附录。

#### B. Same-Question Outcomes Show No One-Way Dominance

Full Context 与 E7 的 60 道同题比较是 RQ4 的主要配对证据：

| Strict outcome | Questions |
|---|---:|
| Both correct | 42 |
| Full Context only | 4 |
| E7 only | 3 |
| Neither correct | 11 |

净优势为 `4 − 3 = 1`，与总体 Strict 差异一致。正文应直接写：

> Full Context has the highest mean semantic score, but it does not dominate selective retrieval. Each access regime solves questions missed by the other.

“Full Context only”说明完整覆盖能够修复一部分选择性路径未解决的问题；“E7 only”则说明增加全部上下文也可能失去选择性证据的聚焦优势。两组结果都只描述观察到的不对称，不在本节直接赋予因果标签。

---

### 5.5.2 Why Does Neither Access Regime Dominate?

本节使用一个统一解释，而不是罗列多组平行机制：

> **Complete coverage and selective focus solve different information-access problems.**

#### A. Coverage Side of the Trade-off

Full Context 将全部 30 个 raw sessions 按时间顺序提供给 Answerer。它不会因显式检索选择而漏掉某个 session 或 source，因此更适合需要跨 session 汇集多个分散事实的问题。

主要描述性证据来自 Multi-hop：

- Multi-hop 共 13 题；
- Full Context 与 E7 的 `Both / FC-only / E7-only / Neither` 为 `8 / 3 / 1 / 1`；
- Full Context Strict 为 `0.8462`，E7 为 `0.6923`；
- Full Context Soft 为 `0.8846`，E7 为 `0.8077`。

这些结果与“完整覆盖有助于分散证据组合”一致，但不能单独证明每个 FC-only case 都由检索遗漏造成。具体 trace 归因留给 RQ5。

#### B. Focus Side of the Trade-off

选择性检索通过缩小输入范围，可能减少无关对话、相似实体、重复事件和不同时间状态之间的竞争，并突出目标属性或时间锚点。

题型不对称提供支持：

- Temporal 的 Full Context/E7 四象限为 `10 / 0 / 1 / 2`，没有 FC-only case，却存在 1 个 E7-only case；
- Single-hop 为 `22 / 0 / 1 / 4`，同样没有 FC-only case，并存在 1 个 E7-only case；
- Open-domain 为 `2 / 1 / 0 / 4`，但仅有 7 题，因此只作探索性观察。

输入规模进一步说明两种 regime 的访问差异：

| Access regime | Evidence/context payload supplied to the Answerer | Share of Full Context |
|---|---:|---:|
| Full Context | 108,960.0 characters | 100.00% |
| E1 | 1,720.9 characters | 1.58% |
| E7 | 19,758.6 characters | 18.13% |

Full Context 的数值是每题提供的完整 raw-context characters；E1 与 E7 是平均 EvidenceBundle characters。该表只用于说明选择性路径提供了更集中的 Answerer 输入。它不等于完整 prompt tokens 或在线成本结论，也不能单独证明输入越短越好。质量—成本推荐留给 RQ6。

#### C. Interpretation Limit

RQ4 的机制语言统一采用：

- `is consistent with a coverage advantage`；
- `is consistent with a focusing benefit`；
- `may reduce competition or localisation burden`。

不写成：

- “Full Context proves that retrieval caused the error”；
- “E7 noise caused Harm”；
- “long context necessarily lowers quality”。

正式的 storage、retrieval、packaging、Answerer、fusion 与 long-context 根因归因统一留给 RQ5。

---

### 5.5.3 Answer to RQ4 and Boundary

RQ4 的最终直接答案是：Full Context 获得轻微的平均语义优势，但没有在 Token F1、所有题型或同题结果上支配选择性检索。Full Context 更适合保留分散在完整历史中的证据；选择性检索则在需要精确定位、时间聚焦或避免竞争信息时保持价值。因此，Full Context 是与选择性检索互补的 evidence-access regime，而不是 oracle。

完整可见性也没有消除错误：Full Context 仍有 14 个 non-Correct answers。RQ4 只据此说明“完整可见性不足以保证正确答案”，不在本节细分长上下文定位、时间推理、证据组合或利用错误；这些属于 RQ5。

正文只保留四项边界：

1. Full Context 不是 E8、新的存储方式或 oracle；它是绕过显式选择性检索的诊断访问条件。
2. Full Context 没有检索级 Evidence Recall，不能与 E1–E7 进行该指标的直接比较。
3. Full Context 与 E1–E7 使用不同的 DeepSeek served-model identifier；同时没有 Qwen Full Context，因此该比较不是严格的 backbone-matched 单变量消融。
4. 实验只覆盖一个固定的 30-session conversation。RQ4 只能报告与 coverage 或 focus 机制一致的模式；正式根因归因交给 RQ5，部署价值与成本取舍交给 RQ6。

---

## RQ4 主文与辅助材料的重新分工

### 正文保留

1. 一段单一 Research Question 与三点 Direct Answer；
2. 一张 Full Context、E1、E5、E7 的紧凑总体质量表；
3. 一张 Full Context–E7 的 `42/4/3/11` 同题四象限表；
4. Multi-hop、Temporal、Single-hop 三个有解释力的题型方向；
5. 一张用于说明聚焦程度的输入字符规模表；
6. 一段最终回答与四项结论边界。

### 下沉附录、审计材料或其他 RQ

- 完整 E1–E7 总体分数表移至附录；
- 完整题型矩阵与逐题四象限结果移至附录或审计材料；
- 个案 trace、具体错误阶段与因果归因交给 RQ5；
- construction cost、query tokens、model calls 与部署推荐交给 RQ6；
- RQ4 不新增图片，以紧凑表格和直接论证为主。

---

## RQ4 正文与后续修订规则

1. RQ4 始终围绕“是否支配”与“coverage–focus trade-off”两步推进，不重新展开完整条件排名。
2. Full Context 的优势写成 `small semantic advantage`，不能写成 `uniformly superior`。
3. 同题四象限优先于只比较总体均值；`4 versus 3` 是无单向支配的关键证据。
4. 题型结果用于解释总体取舍，不另起一条平行研究主线。
5. 机制统一使用 `consistent with` 或 `may reflect`，正式根因留给 RQ5。
6. 输入字符数用于描述聚焦程度，不在 RQ4 中转化为成本或部署结论。
7. Full Context 的 served-model 差异、无 Qwen 对照和单一 conversation 范围必须保留。

---

## 5.6 RQ5: Error Chain and Bottleneck Diagnosis

### 5.6.0 RQ5 的总体论证骨架

#### 1. Research Question

RQ5 只提出一个核心问题：

> **Across the non-Correct answer paths, where is the earliest evidence-supported break in the information chain, and which stage is the largest confirmed system-internal bottleneck?**

中文含义是：

> 对全部 non-Correct answer paths，信息链中最早能够得到证据支持的断点在哪里；在能够确认的系统内部故障中，哪个阶段是最主要的瓶颈？

RQ5 不再把存储、检索、Answerer、融合、长上下文和评价写成六个彼此平行的问题，而是沿一条信息链推进：

```text
信息是否保存在声明的 store 中？
                ↓
retriever 是否到达并保留相关来源？
                ↓
证据是否进入最终 EvidenceBundle？
                ↓
最终输入是否足以回答问题？
                ↓
Answerer 是否正确使用了足够证据？
                ↓
错误是否主要来自评价敏感性？
```

Source integrity 与数据规范化只作为 eligibility check，不形成独立研究结论。RQ5 也不重新比较哪个 E 条件总体得分最高；系统选择与部署推荐留给 RQ6。

#### 2. Population and Attribution Rule

正文必须先解释两个不同分母。

**全部错误路径：250。**这是全部 900 个冻结答案中被 Strict Accuracy 标为 non-Correct 的 answer paths，包括：

- E1–E6 selective paths：205；
- E7 fusion paths：31；
- Full Context paths：14。

**Confirmed system-internal failures：123。**这是从 250 条中排除 53 条 evaluation-sensitive paths 和 74 条 mixed/indeterminate paths 后，能够定位到明确内部阶段的子集。

分析单位是一个 `backbone × condition × question` answer path。同一道题可以在不同条件或 backbone 下重复出现，因此这些路径不是完全独立样本。

Primary attribution 遵循 **earliest supported break**：只把每条路径归入信息链中最早获得充分证据支持的断点。Secondary 或 co-occurring mechanisms 可以同时记录多个后续问题，但不改变主因分布。证据不足时必须保留 Mixed/Indeterminate，不能强制赋值。

#### 3. Direct Answer

正文先展示全部 250 条路径的互斥主因分布：

| Primary attribution | Count | Share of all 250 non-Correct paths |
|---|---:|---:|
| Mixed/Indeterminate | 74 | 29.6% |
| Answerer utilisation | 68 | 27.2% |
| Evaluation-sensitive | 53 | 21.2% |
| Retrieval | 42 | 16.8% |
| Packaging/budget | 7 | 2.8% |
| Fusion/long context | 6 | 2.4% |
| Storage | 0 | 0.0% |

随后明确：Mixed/Indeterminate 与 Evaluation-sensitive 不能计作已经确认的内部组件故障。对剩余 123 条 confirmed system-internal failures：

| Confirmed internal cause | Count | Share of 123 confirmed failures |
|---|---:|---:|
| Answerer utilisation | 68 | 55.3% |
| Retrieval | 42 | 34.1% |
| Packaging/budget | 7 | 5.7% |
| Long-context processing | 6 | 4.9% |
| Storage | 0 | 0.0% |

统一 taxonomy 中的 `Fusion/long context` 是一个合并阶段，但观察到的 6 条全部来自 Full Context 的 long-context processing；没有 E7 path 以 fusion 作为 primary cause。

RQ5 的直接结论是：

> **Among the confirmed system-internal failures, Answerer utilisation is the largest observed bottleneck, accounting for 68 of 123 paths (55.3%). Retrieval is the second-largest bottleneck, with 42 paths (34.1%). No decisive store-specific omission is confirmed.**

因此，当前最大可确认内部瓶颈不是信息未被写入存储，也不只是信息没有被检索到，而是 Answerer 没有正确使用已经可用的证据。

---

### 5.6.1 Where Does the Information Chain First Break?

本节从最终分解向上游证据链回溯。读者先看到总体答案，再阅读支持它的局部审计。

#### A. Integrated Primary-Cause Distribution

RQ5 开头首先放置 integrated bottleneck decomposition 主图，而不是先展示详细存储审计。主图同时呈现：

- 全部 250 条 non-Correct paths 的互斥主因；
- 排除 53 条 Evaluation-sensitive 和 74 条 Mixed/Indeterminate 后，123 条 confirmed internal failures 的内部构成；
- 两个不同分母及其不可互换性。

图后只用一段文字解释核心结果：

- Answerer utilisation 是最大 confirmed internal category；
- Retrieval 为第二大类别；
- Packaging 与 long-context processing 数量较少但得到直接支持；
- Storage 没有确认的 primary failure；
- 127 条 evaluation-sensitive 或 unresolved paths 被显式保留，而不是强制归因。

#### B. From Stored Information to Final Evidence

Storage、Retrieval 与 Packaging 合并为上游证据链，而不是三个彼此独立的大节。

**Storage evidence 只保留四项结论：**

- S1 保留原始内容，但跨 session 组合负担较高；
- S2 增加导航提示，但目录提示不总与答案局部信息一致；
- S3 改善主题共置和 provenance，但不保证每个条目都是 answer-sufficient fact；
- Main-60 中没有确认到决定性的 store-specific omission。

一个问题存在跨表示共享的 representation insufficiency，并在 12 条重复 answer paths 中出现；它不是某一个 store 特有的缺失，因此不计为 primary storage failure。`Storage = 0` 不能被解释为所有表示在所有细节上都无损。

详细 S1–S3 构造统计、locator coverage 和逐题存储审计下沉附录。

**Retrieval 与 packaging 使用同一个 funnel：**在 191 条 evidence-eligible E1–E6 Strict-error paths 中：

| Annotated-evidence state | Paths |
|---|---:|
| Complete annotated bundle | 111 |
| Retrieval-stage attrition | 73 |
| Selected-to-bundle or bundle-boundary loss | 7 |
| **Total** | **191** |

这里必须明确：`complete annotated bundle` 只表示全部官方标注 locator 进入最终 bundle，不等于 final input 在语义上一定 answer-sufficient。官方 locator 也不保证是最小、完整或唯一有效的推理证据链。

该 funnel 描述诊断位置，不与 integrated primary-cause counts 一一对应。7 条 `complete-selection/incomplete-bundle` paths 与最终 7 条 Packaging primary attributions 只重合 3 条：另有 4 条 Packaging primaries 位于 `complete-observation/incomplete-selection`；同时有 4 条 bundle-boundary diagnostic cases 未满足 Packaging primary 的因果门槛，其中 2 条因最终输入仍足够而归为 Answerer，另 2 条保留为 Mixed/Indeterminate。按 co-occurring mechanism 统计，共有 9 条 demonstrated packaging-loss paths，其中 7 条以 Packaging 为主因。

同样，integrated decomposition 中的 42 条 Retrieval primaries 由 41 条 E1–E6 selective paths 和 1 条 E7 inherited-parent retrieval break 组成，不能直接视为上述 73 条 selective retrieval-stage attrition 的简单子集。

主文保留 retrieval-stage distribution 图和上述紧凑 funnel。完整 retriever × stage × category 表下沉附录。

#### C. From Final-Input Sufficiency to Answerer Failure

下一步判断最终输入是否已经足以支持答案。在 205 条 E1–E6 selective errors 中：

| Final-input state | Paths |
|---|---:|
| Sufficient | 88 |
| Insufficient | 111 |
| Indeterminate | 6 |
| **Total** | **205** |

在 88 条 sufficient-input errors 中，56 条存在明确 Answerer failure。这些错误包括：

- 忽略已经出现的关键属性；
- 错误组合多个可用事实；
- 时间关系或实体关系解释错误；
- 无依据增加内容；
- 在证据足够时仍不必要地拒答或过度保守。

56 是 E1–E6 selective subset 中的 Answerer attribution。综合 E7 的 9 条和 Full Context 的 3 条后，primary Answerer attribution 总数为 `56 + 9 + 3 = 68`。这一步建立从局部 sufficiency audit 到总体 68 条 Answerer bottleneck 的清楚连接。

#### D. Evaluation Robustness Check

Evaluation sensitivity 不与 Storage、Retrieval 或 Answerer 并列为同一种内部机制，而作为结论稳健性检查。

正文只保留三个结果：

- Token F1 与 Strict/Soft 相关，但不等价；
- lexical under-credit 主要出现在正确日期的不同表达、同义表达和语义正确但更长的解释中；
- 冻结稳健性检查排除 9 个 evaluation-sensitive questions，并在全部 17 个 paired contrasts 上将 `N = 60` 降为 `N = 51`；Token F1 方向保持 `17/17`，Strict 方向保持 `15/17`。Qwen `E7−E6` 从 tie 变为 positive，而 `Full Context−E5` 从 positive 变为 negative，因此不能写成所有指标方向完全不变。

9 个 evaluation-sensitive questions 用于跨条件 stress test；53 条 Evaluation-sensitive paths 则属于 250 条错误路径的 primary-attribution population。二者分母和用途不同，不能互换。完整 Token F1 × LLM judge 分布图、阈值尾部案例和逐路径标签下沉附录。

---

### 5.6.2 Architecture-Specific Failure Signatures

本节解释为什么不同访问架构形成不同错误模式，不重新进行系统排名。原来的 `Retrieval Bottlenecks and Task-Specific System Choice` 改为：

> **Retrieval Bottlenecks and Architecture-Specific Failure Signatures**

#### A. R1–R3 Retrieval Signatures

- **R1：**多数 Strict-error paths 已经获得完整标注 locator。R1 的剩余问题更常出现在证据解释、跨来源组合或 Answerer utilisation，而不是简单地没有到达相关来源。
- **R2：**错误更集中在 query formulation、session ranking、局部扩展和四次 action cap 内未完成足够探索。其 failure signature 是较早的 retrieval-stage attrition。
- **R3：**进入正确主题或 fact group 不等于暴露全部 source locator。较长的 curated entries 还可能在共同 EvidenceBundle budget 下形成 selected-to-bundle 或 boundary loss。

该小节可以报告不同题型上的错误集中位置，但不能把它改写成“哪一种retriever适合部署”；后者属于RQ6。

#### B. E7 and Full Context Signatures

- **E7：**它复用两个父 EvidenceBundles，不执行新检索。没有 E7 path 以 fusion 作为 primary cause，但增加的证据可能改变 Answerer 的选择、组合或回答长度。Repair 与 Harm 仍属于结果模式，具体因果只能由 trace 支持。
- **Full Context：**它消除了选择性检索和 EvidenceBundle packaging，却把负担转移到长上下文 localisation、时间排序和 cross-event composition。6 条 long-context primary failures 全部来自 Full Context；另有 3 条 primary Answerer failures。

#### C. Representative Traces

正文只保留 4–5 个具有不同功能的代表案例：

1. 一个 R1 complete-bundle 但 Answerer 未正确利用的案例；
2. 一个 R2 在 query/ranking/action cap 前发生 attrition 的案例；
3. 一个 R3 locator exposure 或 budget-boundary loss 案例；
4. 一个 E7 evidence preserved but decision changed 的案例；
5. 一个 Full Context localisation 或 cross-event composition 案例。

案例必须遵循相同格式：`observed trace → earliest supported break → co-occurring mechanism → conclusion limit`。不再在正文逐题罗列完整错误清单。

---

### 5.6.3 Answer to RQ5 and Boundary

RQ5 的最终回答应先用一段直接结论收束：

> **Across the 123 confirmed system-internal failures, Answerer utilisation is the largest observed bottleneck, accounting for 68 paths (55.3%). Retrieval is the second-largest source, with 42 paths (34.1%). Packaging contributes seven paths, and long-context processing contributes six. No decisive store-specific omission is confirmed. The system therefore fails less often because information is absent from memory than because available information is not reached, packaged, or used correctly.**

随后解释这一结论的层次：

- Storage 主要改变 organisation 与 discoverability，而不是在本样本中删除答案事实；
- Retrieval 和 packaging 仍解释 49 条 confirmed internal failures，不能被忽略；
- 一旦最终输入足够，Answerer utilisation 成为主要剩余问题；
- Full Context 说明消除检索遗漏只会转移、而不会消除所有瓶颈；
- Evaluation-sensitive 与 Mixed/Indeterminate paths 仍占全部错误的一半以上，必须与内部故障分开报告。

正文保留以下边界：

1. 这些数字是 error-conditioned path counts，不是各组件在全部请求上的故障率。
2. 同一道题可以在不同 condition 和 backbone 下重复出现，路径不是完全独立的统计样本。
3. Primary attribution 使用 earliest supported break；它不是唯一可能原因，也不排除后续机制共同作用。
4. Co-occurring mechanisms 允许一条错误同时涉及 retrieval、Answerer 和 evaluation。
5. 53 条 Evaluation-sensitive 与 74 条 Mixed/Indeterminate 必须显式保留，不能强行计入某个组件。
6. 官方 locator 用于定位信息链位置，不等同于最小、穷尽或唯一有效证据。
7. RQ5 不重新宣布哪个 E 条件最好，也不承担最终部署推荐；质量—成本选择留给 RQ6。

---

## RQ5 主文与辅助材料的重新分工

### 正文保留

1. 两个分母及 attribution rule；
2. 一张 integrated primary-cause table；
3. Figure 5.6 Integrated Bottleneck Decomposition，用于直接展示全部 250 条 non-Correct paths 与 123 条 confirmed system-internal failures 的主因分解；
4. 一张 191 条 evidence-eligible retrieval funnel；
5. Figure 5.7 Retrieval Error-Stage Distribution，用于解释 R1、R2、R3 的 annotated-evidence states；
6. 一张 205 条 selective-error final-input sufficiency 表；
7. 一张 R1、R2、R3、E7 和 Full Context failure-signature 表；
8. 一张包含 5 个代表性 trace 的紧凑表；
9. 一段最终答案与结论边界。

### 下沉附录或审计材料

- 完整 250 条 case index 和逐路径 primary/secondary labels；
- S1–S3 的完整存储审计表、locator coverage 与原 Storage-State Distribution 图；
- retriever × stage × category 的完整交叉表；
- 完整 evidence sufficiency 与 Answerer-error trace 表；
- Token F1 × LLM judge 完整分布图和评价敏感尾部案例；
- 所有未选入正文的逐题代表案例；
- attribution taxonomy、人工复核字段和审计 hash。

---

## RQ5 图片处理

当前精简版 RQ5 主文只保留两张承担核心论证功能的图片：

1. **Figure 5.6, Integrated Bottleneck Decomposition**：放在 Table 5.13 后、Section 5.6.1 前。它直接回答 RQ5 的总体问题，并严格区分全部 250 条 non-Correct paths 与排除 53 条 Evaluation-sensitive、74 条 Mixed/Indeterminate 后的 123 条 confirmed system-internal failures。
2. **Figure 5.7, Retrieval Error-Stage Distribution**：放在 Table 5.14 后。它按 retriever 展示 191 条 evidence-eligible E1--E6 Strict-noncorrect paths 的 annotated-evidence state，用于解释 R1、R2、R3 的差异，而不将诊断状态误写成 primary cause 或总体失败率。

原 Storage-State Distribution 和 Token F1–LLM Judge Alignment 不进入主文，保留为附录候选。RQ6 的 Quality–Cost Pareto Frontiers 作为 Figure 5.8 插入 5.7.1。为保持已有审计链与资产 hash，旧图片文件名和其内部 lineage ID 不改；`README-new-chapter5.md` 记录新版正文的可见编号映射。

---

## RQ5 正文与后续修订规则

1. 正文第一屏先解释 250 与 123 两个分母，并展示最终主因分解。
2. Main Evidence 始终沿 store → retrieval → packaging → final-input sufficiency → Answerer → evaluation 的信息链展开。
3. `Complete annotated bundle` 不得写成 `answer-sufficient input`；两者必须保持概念分离。
4. 56 条 selective Answerer failures 与综合 68 条 Answerer primary attributions必须明确区分。
5. Evaluation-sensitive 作为 measurement robustness check，不写成已确认的系统内部组件故障。
6. R1–R3、E7 与 Full Context 只报告 failure signature，不在 RQ5 进行系统选择。
7. 所有机制结论必须由 trace 支持；没有充分证据时保留 Mixed/Indeterminate。
8. 正文案例总量控制在 4–5 个，完整 case inventory 下沉附录。
9. Figure 和 Table 必须按照新的首次出现顺序重新编号，并同步更新所有正文交叉引用。

---

## 5.7 RQ6: Quality, Cost, and Practical System Choice

### 5.7.0 RQ6 的总体论证骨架

#### 1. Research Question

RQ6 只提出一个决策问题：

> **Given a deployment scenario, an existing set of memory assets, and a chosen quality target, which tested condition offers the most appropriate quality--cost trade-off?**

中文含义是：

> 在 backbone model、已有存储资产和质量目标已经明确的情况下，哪个已测试条件提供最合适的质量—成本取舍？

RQ6 不寻找一个脱离场景的全局冠军。它按照以下顺序形成决策：

```text
确定 backbone model 与已有 S1/S2/S3 资产
                    ↓
识别在线质量—成本 Pareto frontier
                    ↓
加入 construction 与 recovery 修正
                    ↓
根据部署目标选择条件
```

RQ6 不重新判断存储或检索为什么有效，也不重新进行错误归因。前者已经由 RQ1–RQ4 回答，后者已经由 RQ5 回答。本节只把这些结果转化为条件性的实践选择。

#### 2. Direct Answer

RQ6 的直接答案必须写成场景化选择，而不是统一排名：

1. **Minimum online token cost: E2.** E2 在两个 backbone pipeline 中都具有最低的 mean successful-query tokens，但其语义质量低于更强的 R1 或融合路径。
2. **Qwen balanced default: E3.** E3 同时改善 Qwen 的 Token F1、Strict Accuracy 和 Soft Semantic Score，并略低于 E1 的在线 token 成本；S2 的一次性建设成本也能在中等查询规模下摊销。
3. **Maximum Qwen semantic quality: E5.** E5 取得最高 Qwen Strict 和 Soft，但 S3 construction 与 successful-query cost 都很高，因此它是质量优先选项，而不是默认高效选项。
4. **DeepSeek with an existing S3 asset: E7.** E7 保持与 E1 相同的 Strict Accuracy，Soft 和 Token F1 仅略低，同时减少约 74.3% 的 successful-query tokens。该建议以 S3 已存在或能够被充分复用为前提。
5. **DeepSeek without S3: E1.** 如果没有 curated-memory asset，E1 是更简单的 no-build quality baseline。
6. **Diagnostic or escalation path: Full Context.** Full Context 在当前 DeepSeek-family 诊断中具有竞争力，但因 served-model identifier 不同、只有一个固定 conversation 且没有实际 recovery intervention，不能被写成默认部署架构。

RQ6 的一句话结论是：

> **There is no global winner. E2 defines the online cost floor, E3 is the strongest observed Qwen balance, E7 is the preferred DeepSeek selective path when S3 already exists, and Full Context remains a competitive diagnostic or escalation path rather than a universal replacement for retrieval.**

#### 3. Metric and Decision Hierarchy

正文必须先声明指标等级，避免为每个指标分别宣布一个“最佳系统”。

**质量指标：**

1. `Strict Accuracy` 与 `Soft Semantic Score` 是主要质量判断；
2. `Token F1` 是词面匹配与回答风格的诊断指标，不单独决定部署选择。

**在线成本指标：**

1. `mean successful-query tokens` 是主要在线成本代理；
2. `mean model calls` 是操作复杂度的补充指标，不能与 token 数直接互换。

**生命周期修正因素：**

1. store construction tokens、model calls 与 tool calls；
2. formal recovery attempts 与已知 recovery tokens；
3. S2 或 S3 是否已经存在，以及预期复用次数。

本报告不把这些量强行合成为一个 utility score，因为货币价格、wall-clock latency、质量权重和维护权重均未预先定义。决策必须先限定场景，再在该场景内解释 Pareto-efficient 条件。

---

### 5.7.1 Online Quality--Cost Frontier

#### Question

> **Before one-time construction and recovery costs are considered, which conditions lie on the relevant online quality--cost frontier?**

#### Main Evidence

正文保留一张两面板的统一质量—成本表。Qwen panel 包含 E1–E7；DeepSeek panel 包含 E1–E7，并将 Full Context 作为单独标记的 same-family diagnostic point。每行报告：

- Token F1；
- Strict Accuracy；
- Soft Semantic Score；
- mean successful-query tokens；
- mean model calls。

主文只解释改变决策的结果：

| Pipeline / condition | Token F1 | Strict | Soft | Mean query tokens | Mean model calls | Decision role |
|---|---:|---:|---:|---:|---:|---|
| Qwen E2 | 0.403 | 0.667 | 0.717 | 18,419 | 4.93 | Online cost floor |
| Qwen E3 | 0.441 | 0.750 | 0.792 | 140,288 | 11.67 | Balanced Qwen frontier point |
| Qwen E5 | 0.395 | 0.783 | 0.817 | 281,354 | 8.05 | Maximum Qwen semantic quality |
| DeepSeek E2 | 0.246 | 0.700 | 0.708 | 17,313 | 5.00 | Online cost floor |
| DeepSeek E1 | 0.301 | 0.750 | 0.808 | 201,030 | 12.98 | No-build quality baseline |
| DeepSeek E7 | 0.285 | 0.750 | 0.800 | 51,581 | 9.00 | Selective balance when S3 exists |
| Full Context* | 0.245 | 0.767 | 0.825 | 36,646 | 1.00 | Same-family diagnostic point |

`*` Full Context 使用 `deepseek-v4.1-flash-1017`，E1–E7 使用 `deepseek-v4.1-flash`。它不是严格的 served-model-matched ablation。

必要的直接比较为：

- E2 相对 E1 将 successful-query tokens 降低 87.6%（Qwen）和 91.4%（DeepSeek），但两个 backbone 的 Strict Accuracy 都下降 0.050；
- Qwen E3 相对 E1：Token F1 `+0.046`、Strict `+0.033`、Soft `+0.025`，successful-query tokens 还低 5.8%；
- DeepSeek E7 相对 E1：Strict 持平，Soft `−0.008`、Token F1 `−0.016`，successful-query tokens 低 74.3%；
- Qwen E5 提供最高 Strict 与 Soft，但 query tokens 约为 E3 的两倍。

#### Pareto Evidence

**Figure 5.8, Quality--Cost Pareto Frontiers** 是 RQ6 主图。它使用 mean successful-query tokens 为横轴、Soft Semantic Score 为纵轴；实心点表示 panel 内的 Pareto-efficient conditions，浅色点表示 dominated conditions。Panel A 是 Qwen E1--E7 的 exact selective scope；Panel B 加入不同 served-model identifier 的 Full Context，因此只作为 DeepSeek-family diagnostic scope。

正文只解释主要前沿，不再保留与图重复的完整 Pareto-membership 表：

- Qwen 的关键前沿选择依次体现 E2 的成本下界、E3 的平衡点与 E5 的语义质量上界；
- DeepSeek selective scope 中，E7 是从 E2 向更高质量移动的主要中间点，E1 提供更高的 no-build quality baseline；
- 加入 Full Context 后，它在 Strict/Soft 视图中形成有竞争力的诊断点，但由于 served-model 差异，不能被解释为对 E1–E7 的严格支配。

Token F1 frontier 与 Strict/Soft frontier 不完全一致。该差异用于提醒读者词面和语义质量不可折叠，不再另起一条平行结论。

#### Direct Interpretation

最低成本系统不是最高质量系统。E2 是 cost-first choice；E3 是 Qwen 的 balanced choice；E7 是已有 S3 时的 DeepSeek selective choice；E5 是 Qwen semantic-quality maximum。此时仍未考虑建设与恢复成本，因此不能直接形成最终部署建议。

---

### 5.7.2 Construction and Recovery Modifiers

#### Question

> **Do one-time store construction and observed recovery burden change the online frontier recommendation?**

#### Construction Evidence

正文不再保留完整逐条件 construction 与 break-even 表，只报告会改变选择的数字：

- S1 没有 model-based construction cost；deterministic normalisation 与 file-processing cost 未测量，不能写成总成本为零；
- S2 construction 使用 395,749 tokens；
- Qwen E3 相对 E1 的累计 token 成本约在第 46 次查询后交叉，并且 E3 的三个质量指标均高于 E1；
- S3 construction 使用 30,864,958 tokens；
- DeepSeek E7 相对 E1 的累计 token 成本约在第 207 次查询后交叉；
- E7 相对 E2 不会产生 token break-even，因为 E7 的 construction 与每次 successful-query cost 都更高。

`Break-even` 只表示累计 token 使用交叉，不表示两个系统质量等价。尤其是 DeepSeek E7 与 E1：Strict 持平，但 Soft 与 Token F1 略低。

#### Recovery Evidence

正文保留三个汇总量：

- 观察到 41 次 formal failed attempts；
- 39 次具有可计量 usage，已知 recovery tokens 合计约 10.13 million；
- 两次 Qwen E5 DNS failures 的 usage 未知，不能按零计入。

这些 formal failures 在本次运行中全部发生于 R1 条件 E1、E3 与 E5。该结果只能作为 observed-run operational modifier，不能证明 R1 在一般情况下必然不可靠，也不能将未知 usage 推断为零。

#### Direct Interpretation

- S2 是相对低成本的结构化投资，因此 E3 可以在中等查询规模下成为合理的长期 Qwen default；
- S3 是昂贵的长期资产。E5 或 E7 只有在 S3 已存在、查询规模足够大或语义质量价值足够高时才合理；
- recovery burden 会削弱仅依据成功查询成本形成的推荐，但当前数据不足以建立通用 failure-rate ranking。

完整 store-construction、break-even 和 recovery 表下沉附录，主文不再逐项枚举所有无决策影响的交叉点。

---

### 5.7.3 Scenario-Based Recommendation and Answer to RQ6

#### A. Scenario-Based Decision Table

RQ6 最终用一张情景决策表收束，不再追加新的全局排名：

| Deployment scenario | Recommended condition | Main reason | Required qualification |
|---|---|---|---|
| Minimum online token cost | E2 | Lowest successful-query tokens under both backbone models | Lower Strict and Soft than stronger paths |
| Qwen balanced default | E3 | Best observed combination of Qwen F1, semantic quality, and reusable S2 cost | Depends on the tested S2/R1 pairing |
| Maximum Qwen semantic quality | E5 | Highest Qwen Strict and Soft | High S3 construction and query cost |
| DeepSeek selective quality with existing S3 | E7 | Near-E1 quality with 74.3% fewer successful-query tokens | Requires both parent retrieval paths and an existing S3 asset |
| DeepSeek quality without S3 | E1 | Strong no-build selective baseline | High successful-query token use and observed R1 recovery burden |
| Diagnostic or escalation path | Full Context | Complete source visibility and competitive tested semantic quality | Different served model; not a default or universal retrieval replacement |

#### B. Mechanism or Explanation

机制解释只服务于上述选择，不重复各条件全部分数：

1. **Why E2 is cheap.** R2 使用固定的 query、ranking、expansion 与 action-cap 流程，model calls 和 tokens 较少；RQ1 与 RQ2 已表明这种节省伴随语义质量下降。
2. **Why E3 can amortise.** S2 只增加导航结构而保留 raw-session content。它的 construction cost 远低于 S3，并能在 Qwen 中改善 R1 的质量—成本组合。
3. **Why S3 changes the decision.** S3 是昂贵的长期资产。其价值不来自一次查询，而来自重复复用、较高语义质量需求或对 E7 的支持。
4. **Why E7 is not a free improvement.** E7 必须执行 E2 与 E6 两条父检索路径，再运行一次 fused Answerer；互补证据提高质量的同时增加 online work。
5. **Why Full Context is an escalation path.** Full Context 移除 retriever calls，但把定位、时间排序和跨事件组合负担转移给一个长输入 Answerer。它在当前固定 conversation 上有竞争力，但没有建立普遍扩展规律。
6. **Why more retrieval is not always the next investment.** RQ5 显示，在 123 条 confirmed system-internal failures 中，Answerer utilisation 占 55.3%，高于 Retrieval 的 34.1%。因此，继续增加检索复杂度不一定比改善 evidence utilisation 更有效。

#### C. Final Answer to RQ6

正文最后直接回答：

> **Practical system choice is conditional on the backbone model, the available memory assets, and the target point on the quality--cost frontier. E2 is the cost floor. E3 is the strongest observed Qwen default because its modest S2 investment improves quality without increasing successful-query tokens. E5 is justified only when maximum Qwen semantic quality outweighs S3 cost. For DeepSeek, E7 is the preferred selective balance when S3 already exists, whereas E1 remains the simpler no-build baseline. Full Context is best treated as a competitive diagnostic or escalation path under the tested setting, not as a universal replacement for selective retrieval.**

#### D. Boundary of the Conclusion

边界压缩为四组，不再逐条重复工程细节：

1. **Cost proxy boundary.** Tokens 是主要成本代理，不等于货币价格或 wall-clock latency；model calls 单独报告。LLM judge 是 evaluation-only cost，不计入部署查询成本。
2. **Lifecycle boundary.** S3 的更新、维护与失效成本未测量；两次 Qwen E5 failed attempts 的 usage 未知，因此已知 recovery tokens 是下界。
3. **Comparison boundary.** Full Context 使用不同 served-model identifier，且只覆盖一个固定 30-session conversation；它只能作为 same-family diagnostic point。
4. **Decision boundary.** Pareto membership 会随 F1、Strict 或 Soft 的选择而变化；break-even 只表示 token 累计成本交叉，不表示质量等价。所有推荐只适用于 Main-60 和冻结配置。

---

## RQ6 主文与辅助材料的重新分工

### 正文保留

1. Research Question、指标层级与场景化 Direct Answer；
2. 一张两面板 quality--successful-query cost 主表；
3. Figure 5.8 Quality--Cost Pareto Frontiers；
4. construction、break-even 与 recovery 的少量决策性数字；
5. 一张 scenario-based decision table；
6. 简短机制解释与四组结论边界。

### 下沉附录或审计材料

- 完整 Pareto-membership 表与 F1/Strict/Soft 三套 frontier 明细；
- 全部 store-construction model/tool-call 明细；
- 所有 condition-to-condition break-even 交叉点；
- 逐条件 formal-failure 与 recovery-token 表；
- E7 cost reconstruction 明细；
- model pricing、latency 与 maintenance 未测量项说明。

---

## RQ6 正文与后续修订规则

1. RQ6 始终沿 `online frontier → lifecycle modifiers → scenario decision` 推进。
2. Strict 与 Soft 是主要质量指标；Token F1 只作为诊断，不单独决定部署选择。
3. successful-query tokens 是主要在线成本代理；model calls、construction 与 recovery 只作为独立修正因素，不合成为未经定义的总分。
4. E2 写成 cost-first option，不写成无代价替代方案。
5. E3 的推荐限定为 Qwen tested pipeline；不能推广为所有 backbone 的目录化收益。
6. E7 的推荐必须注明 S3 已存在或可以充分复用，并明确它同时执行两条父检索路径。
7. Full Context 写成 competitive diagnostic or escalation path，不写成默认架构、oracle 或严格 served-model-matched winner。
8. Figure 5.8 是新版正文的可见编号；底层 audited asset 文件名仍保留 `figure-5-10-quality-cost-pareto-frontiers.*`。
9. 所有 break-even 陈述必须同时说明质量是否等价；未知 recovery usage 不得按零处理。
