# E1–E7 结果分析框架与论文写作地图

本文档记录 `formal-v1-main40-run-02` 的结果分析思路。它的作用不是提前替结果找解释，而是把“观察到什么、如何验证、能够写出什么结论、哪些结论暂时不能写”固定下来，供后续统计、案例分析和论文 Results / Discussion 章节使用。

## 1. 分析对象与边界

- 数据：LoCoMo `conv-50` 的冻结 main-40 问题集；
- 问题类别：C1 multi-hop 10 题、C2 temporal 10 题、C3 open-domain 7 题、C4 single-hop 13 题；
- 条件：E1–E7，每个条件 40 个最终回答，共 280 条；
- 自动指标：LoCoMo category-aware token/stem F1，以及同一匹配过程下的 Precision / Recall 诊断值；
- 语义指标：匿名三档 LLM-as-Judge 的 Strict Accuracy、Partial Rate 和 Soft Semantic Score；
- 过程指标：Evidence Recall、Any-hit、All-hit、citation validity、tokens、model calls、轮数/动作数、cap、空证据和预算跳过；
- 结论边界：当前只有一个 conversation、40 道题和一次 Judge 运行，因此主结果应写成**描述性 empirical finding**，不能轻率声称普遍因果关系。

### 1.1 七个实验条件

| 条件 | 存储 | 检索 | 主要作用 |
|---|---|---|---|
| E1 | S1：平铺原始 session 文件 | R1：Filesystem 风格 agentic 文件检索 | 原始文件基线 |
| E2 | S1：平铺原始 session 文件 | R2：ReFind-style 原始聊天检索 | 原始聊天增强检索 |
| E3 | S2：文件夹化原始 session 文件 | R1 | 检验目录组织对 R1 的影响 |
| E4 | S2：文件夹化原始 session 文件 | R2 | 检验目录与增强检索的组合 |
| E5 | S3：LLM 整理的文件系统 | R1 | Filesystem 主条件 |
| E6 | S3：LLM 整理的文件系统 | R3：面向 curated memory 的 R2 变体 | curated memory 增强检索 |
| E7 | E2 原始证据 + E6 整理证据 | 固定双源融合，不重新检索 | 检验第二证据源能否修复丢失/污染 |

## 2. 两套评分怎样一起解释

### 2.1 LoCoMo token 指标

先按官方规则做小写化、去标点/冠词和 Porter stemming，再计算重合 token：

- `Precision = 重合 token 数 / 候选回答 token 数`；
- `Recall = 重合 token 数 / 参考答案 token 数`；
- `F1 = 2PR / (P + R)`；
- C1 对逗号分隔的多答案采用官方 multi-answer 匹配；
- C3 采用官方首个分号答案规则；
- 表中的 P/R 是逐题 category-aware 诊断值的均值；F1 是官方逐题分数的均值，因此不能用表中汇总后的 P/R 再反算 F1。

它擅长检查“答案词面是否贴近参考答案”，但会低估同义改写和正确的长句，也可能对碰巧共享关键词的错误答案给出部分分数。

### 2.2 LLM-as-Judge 指标

同一个匿名 Judge 对每条候选答案给出一个三档标签：

- `correct`：关键信息完整且没有实质矛盾；
- `partial`：包含部分必要信息，但不完整或混有实质性问题；
- `incorrect`：核心答案错误、无法回答或没有覆盖必要信息。

由同一个标签同时派生三项指标：

- `Strict Accuracy = correct / 40`；
- `Partial Rate = partial / 40`；
- `Soft Semantic Score = (correct + 0.5 × partial) / 40`。

因此不是两个 Judge，也不是先后运行两个模型。Strict 和 Soft 只是对同一批三档标签的两种汇总。

## 3. 当前完整结果快照

| 条件 | Token Precision | Token Recall | 官方 Token F1 | Judge Strict | Judge Partial | Judge Soft |
|---|---:|---:|---:|---:|---:|---:|
| E1 | 0.3074 | 0.6464 | 0.3646 | 0.6000 | 0.2250 | 0.7125 |
| E2 | 0.3661 | 0.6342 | 0.3972 | 0.5000 | 0.2750 | 0.6375 |
| E3 | **0.3483** | 0.6973 | **0.4146** | **0.6250** | 0.2250 | **0.7375** |
| E4 | 0.3456 | 0.6456 | 0.3971 | **0.6250** | 0.1500 | 0.7000 |
| E5 | 0.2907 | **0.7310** | 0.3488 | **0.6250** | 0.2000 | 0.7250 |
| E6 | 0.3020 | 0.6592 | 0.3594 | **0.6250** | **0.1250** | 0.6875 |
| E7 | 0.2948 | 0.6548 | 0.3380 | 0.6000 | 0.2250 | 0.7125 |

读取这张表时要注意：E3 是目前最稳健的总体条件；E5 的 Recall 最高，但 Precision 和 F1 不高；E2 的 token F1 高于 E1，但语义 Strict/Soft 反而更低；E7 的 token F1 不高，却比 E2/E6 有更高的 Soft 分数。这些冲突本身就是值得分析的结果。

## 4. 四个核心研究问题

### RQ1：文件组织方式何时有用？

主要对照：

- E1 vs E3：同为 R1，比较平铺原文与文件夹化原文；
- E2 vs E4：同为 R2，比较平铺原文与文件夹化原文；
- E1 vs E3 vs E5：同为 R1，比较三种存储方式。

需要分析：

1. 逐题的提升、持平和下降数量，而不只看平均值；
2. 提升是否集中在 temporal、multi-hop 或 single-hop；
3. 目录是否减少 R1 的无效读取、轮数或 token；
4. S3 的整理是否提高证据覆盖，却因摘要化、污染或冗余降低最终回答质量；
5. 文件数量、目录深度、平均文件大小和主题集中度与效果之间的关系。

当前可写的初步事实是：在 R1 下，E3 比 E1 的 F1 高 0.0500，Strict 高 0.025，Soft 高 0.025；但在 R2 下，E2 与 E4 的 token F1 几乎相同，而 E4 的语义分数更好。目录的价值可能依赖检索器，而不是一个独立、恒定的增益。

### RQ2：增强检索能否修复 Filesystem 的检索错误？

主要对照：

- E1 vs E2：S1 上 R1 与 R2；
- E3 vs E4：S2 上 R1 与 R2；
- E5 vs E6：S3 上 R1 与 R3。

每一对都要做四类逐题转移：

- repair：基线错，增强方法对；
- harm：基线对，增强方法错；
- both-correct；
- both-wrong。

同时比较 Evidence Recall、Judge 标签和最终回答，回答三个不同问题：

1. 是否真的找到了更多正确证据；
2. 找到证据后是否被 Answerer 正确使用；
3. 节省 token 是否以丢失答案完整性为代价。

不能只写“R2 比 R1 好/坏”。当前 E1→E2 在 token F1 上变好，但 Strict/Soft 下降；E3→E4 的 token F1 下降、Strict 不变、Soft 下降；E5→E6 的 token F1略升、Strict不变、Soft下降，但 token 降低 86.61%。更准确的结论是：增强检索有明显成本优势，但质量收益依赖存储和评分口径。

### RQ3：错误发生在写入、检索还是回答阶段？

可以用已有字段批量做第一层归因：

| 状态 | 判定信号 | 建议归因 |
|---|---|---|
| gold evidence 未命中，答案错 | Evidence Recall = 0 或 All-hit=false，Judge 非 correct | 检索遗漏候选 |
| gold evidence 已命中，答案错 | Any-hit/All-hit=true，Judge 非 correct | 证据利用/推理错误 |
| S3 中所需事实缺失或被污染 | S1/S2 可找到原文，S3 对应事实不存在或内容错误 | 写入/整理错误 |
| 双源包含正确证据但 E7 变差 | E2/E6 至少一路正确，E7 下降 | 融合干扰或 Answerer 过载 |
| 证据存在但因预算整项跳过 | `budget-skipped > 0` 且相关 item 未进入 bundle | 预算/打包错误 |
| evidence 足够但回答声明不足 | `insufficient_evidence=true` 且 gold evidence 已命中 | Answerer 校准错误 |

这套自动归因不是最终真相。对于边界样本，应抽取 12–16 个代表案例，人工沿“问题 → 检索动作 → EvidenceBundle → 回答 → Judge 理由”复查。案例选择应覆盖 repair、harm、高 Recall 低分、低 Recall 高分和双源融合冲突。

### RQ4：保留原始聊天作为第二检索源是否值得？

主要比较 E7 与 E2、E6：

- E7 vs E6：加入原始聊天证据后，是否修复 S3 整理丢失；
- E7 vs E2：加入整理证据后，是否改善原始聊天检索；
- E7 的 Evidence Recall 增量是否能转化为 Strict/Soft 增量；
- 增量效果是否抵得过 token、model calls 和证据长度成本；
- 哪类题最容易发生“双源互补”，哪类题更容易发生“证据冲突/噪声过载”。

当前结果显示 E7 的 Evidence Recall 高于 E2 和 E6，但官方 F1 低于两者；Soft 高于两者，而 Strict 介于两者之间。这更像“部分修复、同时引入干扰”，不能写成双源融合已全面获胜。

## 5. 必做的数据分析

### 5.1 逐题配对差值

对每个关键对照计算每道题的：

- `ΔF1`、`ΔSoft`、`ΔStrict`；
- `ΔEvidence Recall`；
- `Δtokens`、`Δmodel calls`；
- win / tie / loss；
- correct / partial / incorrect 标签转移矩阵。

统计报告建议使用：均值差、中央値、95% paired bootstrap confidence interval、win/tie/loss 计数。Strict 是配对二元结果，可补充 McNemar exact test；样本仅 40，显著性结果必须与效果量和置信区间一起解释，并注明探索性多重比较。

### 5.2 按类别分层

分别对 C1–C4 输出 F1、Strict、Soft、Evidence Recall 和 token。重点看：

- multi-hop 是否更依赖多轮搜索或双源证据；
- temporal 是否更受摘要化和日期标准化影响；
- open-domain 是否因仅 7 题而方差过大；
- single-hop 是否更容易被冗长检索拖累。

类别样本很小，类别结果用于解释机制，不应包装成稳健总体排名。

### 5.3 自动指标与语义 Judge 的一致性

需要计算：

- 每条件 Token F1 与 Soft/Strict 的相关关系；
- `token F1 高但 Judge 错` 的案例；
- `token F1 低但 Judge 对` 的案例；
- correct / partial / incorrect 三档下的 token F1 分布。

这能解释为什么 E2、E7 在两套指标中的相对排名不同，也能说明只用单一指标会隐藏什么。

### 5.4 检索覆盖与证据利用

把每条结果放进二维表：

|  | Judge correct | Judge partial/incorrect |
|---|---:|---:|
| gold evidence 命中 | 成功检索并利用 | utilization bottleneck |
| gold evidence 未命中 | 可能靠背景知识/偶然猜中 | retrieval bottleneck |

进一步比较 Any-hit、All-hit、Evidence Recall 与 F1/Soft 的关系。E5“Evidence Recall 最高但答案分数不最高”是这里的核心案例：更多证据不等于更好答案，可能存在证据噪声、冗余、摘要污染或 Answerer 使用失败。

### 5.5 效果—成本分析

至少画两张 Pareto 图：

- x 轴：平均总 tokens/题；y 轴：Token F1；
- x 轴：平均总 tokens/题；y 轴：Judge Soft。

同时报告 retrieval tokens、answer tokens、model calls、round/action cap 和空证据。重点比较：

- E1→E2、E3→E4 的约 88% token 节省；
- E5→E6 的 86.61% token 节省；
- E7 相对 E6 的额外成本是否换来足够的 Soft 增益；
- 哪些点被其他条件在“更便宜且更好”意义上严格支配。

### 5.6 运行可靠性与协议行为

把工程运行也作为 empirical finding 的一部分：

- 到达 R1 round cap 或 R2/R3 action cap 的比例；
- 空 EvidenceBundle、budget-skip、insufficient answer 的频率；
- requested model 与 served model 一致性；
- store hash 前后不变；
- 失败类型、重试次数和检查点恢复；
- citation validity。

它们用于说明结果不是由存储被意外修改、模型漂移或漏跑造成的，也能揭示方法在真实运行中的维护成本。

## 6. 可借鉴的两篇论文分析方式

页码以下述仓库内 PDF 为准：

- [Filesystem-Based Memory for LLM Agents](../../papers/primary/filesystem-based-memory-for-llm-agents.pdf)
- [When Your Agent Opens the Chat App: ReFind](../../papers/primary/when-your-agent-opens-the-chat-app-refind.pdf)

| 来源 | 原文位置 | 可借鉴方法 | 本项目对应分析 |
|---|---|---|---|
| Filesystem | §3，pp. 7–8 | 把组织、写入和检索视为完整系统，而非只比较答案分数 | 解释 S1/S2/S3 和 R1/R2/R3 的组件关系 |
| Filesystem | Table 1，p. 9；§4.2，pp. 13–14 | 主任务效果和消融对照 | E1/E3/E5 与 E2/E4/E6 的配对/分组比较 |
| Filesystem | §4.5，pp. 20–21 | 文件结构、规模与可持续性分析 | 文件数、目录深度、平均大小、token 成本 |
| Filesystem | Appendix D.1，pp. 51–52 | 区分检索到证据与正确使用证据 | retrieval vs utilization 二阶段错误归因 |
| Filesystem | Appendix D.2，pp. 52–53；D.4，pp. 53–54 | 失败案例、成本和运行细节 | cap、空证据、失败恢复和代表性 trace |
| ReFind | Search Engine Design，pp. 5–6 | 分解候选召回、重排、上下文扩展与迭代查询 | 分析 R2/R3 各阶段的增益和 action cap |
| ReFind | §4 / Table 2，pp. 6–7 | 主结果与 baseline 对比 | E1–E7 主表及 Full Context 后续 baseline |
| ReFind | §5 / Table 4，pp. 7–9 | 组件消融和 one-shot / iterative 行为比较 | 后续可做 4/6/8 action 或单轮/多轮消融 |
| ReFind | evaluation/repeat，pp. 17–19 | 重复评测与稳定性说明 | Judge 重复性、置信区间、人工抽查 |
| ReFind | resources，pp. 19–20 | 资源消耗和延迟/成本报告 | tokens、calls、动作数、Pareto 前沿 |
| ReFind | example trace，p. 21 | 用完整检索轨迹解释机制 | 论文中展示 3–5 个代表 trace |

与两篇论文的趋势关系目前应概括为：

- **一致**：结构化目录在 agentic 文件检索下可能有帮助；找到更多证据不保证回答更好；更受控的检索能大幅降低 token；不同存储/检索组合不存在一个对所有指标都占优的方案。
- **不完全一致或尚未复现**：本项目的 ReFind-style 方法没有在所有语义指标上稳定超过 R1；双源融合没有带来稳定 strict 提升；尚未进行 ReFind 的单轮 vs 多轮严格消融，因此不能声称复现了其 iterative-search 增益。

## 7. 建议制作的论文表格与图

1. **主结果表**：E1–E7 的 Token P/R/F1、Strict、Partial、Soft、Evidence Recall、平均 tokens；
2. **类别热力图**：7 条件 × 4 类别的 F1/Soft；
3. **配对转移图**：关键对照的 correct/partial/incorrect 转移矩阵；
4. **检索—利用二维图**：Evidence Recall 与 Judge Soft 的散点图；
5. **效果—成本 Pareto 图**：tokens 对 F1、tokens 对 Soft；
6. **错误归因堆叠图**：写入、检索、预算、利用、融合错误占比；
7. **代表案例表**：每类案例展示问题、gold evidence、命中证据、回答、Judge 标签与原因。

## 8. 推荐执行顺序

### P0：不再调用 API 即可完成

1. 生成逐题合并表：官方分数 + Judge + 检索 + 成本；
2. 完成六组关键配对的 win/tie/loss、标签转移和 bootstrap CI；
3. 完成四类别分层表；
4. 完成 retrieval/utilization 自动归因；
5. 完成两张 Pareto 图和运行诊断表。

### P1：人工核查

从自动归因中抽取 12–16 个代表样本，逐条阅读 trace，确认“写错、没找到、看到了没用好、融合干扰”是否成立。

### P2：可选后续实验

- R2/R3 action cap 4 vs 6 vs 8；
- one-shot vs iterative retrieval；
- Full Context baseline；
- 在更多 conversation 上做外部验证；
- Judge 重复运行或小规模人工双标，估计 Judge 稳定性。

正式论文应把 P0 作为主结果，把 P1 作为机制解释，把 P2 明确写成扩展或未来工作。不要因为 main-40 结果不理想而修改已冻结的 prompt、预算、cap 或模型。
