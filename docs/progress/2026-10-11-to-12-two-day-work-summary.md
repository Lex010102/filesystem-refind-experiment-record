# 项目工作长笔记（始于 2026-10-11 至 2026-10-12）

本文最初汇总 2026-10-11 至 2026-10-12 的研究与工程工作，后续继续按时间追加重要讨论、计划和已核验进展。它集中回答三件事：**做了什么、怎么做、为什么做**。详细运行日志、逐题结果和协议仍以各专项文档与结果目录为准；本文是以后写报告、向师兄汇报和追溯实验版本时使用的总入口。

这两天项目从“正式实验已经冻结、准备开始跑批”推进到：

- E1–E7 的 40 道正式题全部完成，共 280 条最终回答；
- LoCoMo 官方离线评分、证据指标和效率指标全部生成；
- B3 Full Context baseline 的源包、程序和离线门禁全部完成，但尚未真实联网运行；
- 280 条回答的匿名 LLM-as-Judge 补充评分全部完成；
- 形成了面向四个研究问题的数据分析框架和 25–30 页报告写作思路；
- 代码、文档、正式结果与校验文件均已归档到 GitHub，凭据和本机运行临时文件未上传。

## 1. 实验对象与条件回顾

本轮实验使用 LoCoMo `conv-50` 的冻结 main-40 问题集。40 道题由 category 1–4 的 10、10、7、13 题组成。七个条件共享同一 Answerer、问题顺序、模型和证据预算，差异只来自存储与检索方案。

| 条件 | 存储 | 检索/融合 | 主要研究作用 |
|---|---|---|---|
| E1 | S1：平铺原始 session 文件 | R1：Filesystem 风格 agentic 文件检索 | 原始文件基线 |
| E2 | S1：平铺原始 session 文件 | R2：ReFind-style 原始聊天检索 | 原始聊天增强检索 |
| E3 | S2：文件夹化原始 session 文件 | R1 | 检验目录组织是否帮助文件检索 |
| E4 | S2：文件夹化原始 session 文件 | R2 | 检验目录与增强检索的组合 |
| E5 | S3：LLM 整理的文件系统 | R1 | Filesystem 主条件 |
| E6 | S3：LLM 整理的文件系统 | R3：面向 curated memory 的 R2 变体 | 检验整理记忆上的增强检索 |
| E7 | E2 原始证据 + E6 整理证据 | 确定性双源融合，不重新检索 | 检验原始聊天能否补回整理损失 |

正式版本继续遵守 `formal-v1` 的冻结配置：证据预算为每路 16,000 characters；E1/E3 的 R1 上限为 20 rounds，E5 为 40 rounds；R2/R3 上限为 4 actions；requested model 为 `coding`，实际 served model 必须是 `qwen3.8:27b`；并发为 1。正式结果出现好坏都不反向修改这些参数。

## 2. 10 月 11 日：完成正式主实验

### 2.1 做了什么

完成 `formal-v1-main40-run-02`：

- 40 道问题 × E1–E7，共 280/280 条最终 RunRecord；
- E1–E7 各 40 条；
- B01–B08 共 8 个批次全部通过，每批为 5 题 × 7 条件 = 35 条；
- 40/40 个问题块完整；
- 活动失败键为 0；
- requested/served model 全程一致；
- 最终 citation validity 为 1.0，所有存储查询前后 hash 不变。

### 2.2 怎么做

正式运行采用“冻结协议 + 小批次 + 检查点恢复”的方式：

1. 按固定题目顺序串行运行，每条记录独立保存；
2. 每完成 5 道题，对累计 35 条结果做 batch audit；
3. 每个通过的批次生成 `batch-XX.PASSED`，再进入下一批；
4. API 超时或模型工具协议不合规时，只保存该失败尝试；
5. 恢复前重新验证已有 RunRecord，已完成项直接跳过，只重跑失败项；
6. 通过唯一 `run.lock` 保证任何时刻只有一个 runner，防止重复计数；
7. 280 条完成后执行 pre-gold audit，再执行纯离线评分和最终审计。

运行期间保留了 7 次失败尝试，主要是 API/超时和模型工具协议违规。例如 E5 `conv-50-q005` 曾在 R1 provider round 6 输出不兼容动作，触发 `EvidenceValidationError`。处理时没有改变 prompt、预算、cap、模型或题目，只重试当前记录并从检查点继续。最终所有失败均被恢复，没有遗留活动失败。

### 2.3 为什么这样做

正式实验必须同时满足“结果完整”和“条件公平”。如果失败后从头重跑，容易重复计费、覆盖已完成结果或混入不同版本；如果临时放宽 cap 或改 prompt，则七个条件无法公平比较。检查点、不可变记录、单 runner 和逐批审计让 280 条结果既能在不稳定网络下完成，又保持冻结版本不变。

### 2.4 完成后怎样核验

`formal-pre-gold-verify.json` 检查并通过了以下内容：

- 280 条记录和七个条件的数量完整；
- requested/served model 一致；
- citation 均指向对应 EvidenceBundle 的真实 evidence ID；
- 查询前后 store hash 不变；
- RunRecord 与已发布 retrieval artifact 一致；
- E7 只复用 E2 和 E6 的 EvidenceBundle，没有暗中重新检索；
- E7 没有重复计算 E2/E6 的 Answerer 成本；
- API 阶段没有加载 gold 语义内容。

详细记录见：

- [formal-v1 main-40 完成记录](2026-10-11-formal-v1-main40-completion.md)
- [formal-v1 main-40 评分结果](2026-10-11-formal-v1-scoring-results.md)

正式结果位置：

- 本地权威运行：`local-runs/formal-v1-main40/formal-v1-main40-run-02/`
- GitHub 归档：`experiments/locomo-conv50-v1/results/formal-v1-main40-run-02/`

## 3. 10 月 11 日：完成 LoCoMo 官方评分与效率统计

### 3.1 做了什么

对 280 条冻结回答完成纯离线评分，并生成：

- LoCoMo 官方 category-aware token/stem Precision、Recall 和 F1；
- C1–C4 分类结果；
- Evidence Recall、Any-hit、All-hit 和 citation validity；
- retrieval/answer tokens、总 tokens、model calls；
- rounds/actions、cap、空证据、budget-skip 和 insufficient answer；
- `evaluation.json` 与 `final-audit.json`，最终审计状态为 `passed`。

主结果如下：

| 条件 | Token Precision | Token Recall | 官方 Token F1 | Evidence Recall | 总 tokens |
|---|---:|---:|---:|---:|---:|
| E1 | 0.3074 | 0.6464 | 0.3646 | 0.8092 | 6,072,586 |
| E2 | 0.3661 | 0.6342 | 0.3972 | 0.7325 | 737,484 |
| E3 | **0.3483** | 0.6973 | **0.4146** | 0.8202 | 6,008,177 |
| E4 | 0.3456 | 0.6456 | 0.3971 | 0.7303 | **736,746** |
| E5 | 0.2907 | **0.7310** | 0.3488 | **0.9254** | 11,764,087 |
| E6 | 0.3020 | 0.6592 | 0.3594 | 0.8158 | 1,575,125 |
| E7 | 0.2948 | 0.6548 | 0.3380 | 0.8860 | 2,259,475 |

七个条件总计使用 29,153,680 个 provider-reported deployment tokens。其中 retrieval 为 28,076,209，Answerer 为 1,077,471。

### 3.2 怎么做

评分使用冻结的 LoCoMo 官方 evaluator：

- 官方仓库 commit：`cbfbc1dba6bc53d00625212a0f22d55ffee7c1fc`；
- `task_eval/evaluation.py` SHA-256：`8e3be5d57ff2ff9ec5cd05939592f468c5f3f1fd95d13e431932bdf6bf0fd6fd`；
- NLTK 版本：`3.8.1`。

Token 指标先执行小写化、去标点/冠词和 Porter stemming，再对候选答案与参考答案计算 token 重合。C1 多答案和 C3 分号答案遵守官方 category-aware 规则。表中的 Precision/Recall 是逐题诊断值的平均；F1 是官方逐题 F1 的平均，不能使用表中聚合后的 P/R 再反算。

该阶段完全离线，不重新调用学校 API，也不重新生成任何答案。

### 3.3 为什么做

官方 F1 是与 LoCoMo 及已有论文最容易复核的主指标；Evidence Recall 和 token/call 数据则用于区分：

- 是没有找到证据；
- 找到了证据但 Answerer 没用好；
- 还是方法虽然有效，却付出了过高的运行成本。

当前最重要的描述性观察是：

1. E3 的官方 F1 最高，说明文件夹目录对 R1 在这组题上可能有帮助；
2. E2 相对 E1 节省 87.86% token，同时 F1 上升；
3. E6 相对 E5 节省 86.61% token，同时 F1 略升；
4. E5 的 Evidence Recall 最高，但成本最高且最终 F1 并不高；
5. E7 提高了相对 E2/E6 的证据覆盖，却没有提高官方 F1。

这些结果说明“找到更多证据”不等于“最终回答更好”，效果和成本必须一起报告。

## 4. 10 月 11 日：明确评分、论文和新增 baseline 的方向

### 4.1 评分口径的决定

确定论文采用两层评分：

1. **主评分**：LoCoMo 官方 token/stem F1；
2. **补充评分**：匿名 LLM-as-Judge 的语义 Strict/Partial/Soft。

这样安排的原因是：token F1 可重复、便于与论文对照，但会低估同义改写；LLM Judge 更接近“意思是否正确”，但自身存在模型偏差，不能替代官方主指标。

### 4.2 与两篇论文的对照

重新梳理了 Filesystem Memory 与 ReFind 的实验和分析方式，并把可借鉴内容写入后续分析框架。当前结果与论文方向较一致的部分包括：

- 结构化目录在 agentic 文件检索下可能有帮助；
- 证据召回更高不保证答案更好；
- 受控检索能显著减少 token；
- 不存在一个在所有效果与成本指标上都占优的方法。

当前不完全一致或尚未复现的部分包括：

- 本项目的 ReFind-style 检索没有在所有语义指标上稳定超过 R1；
- 双源融合没有带来稳定的 Strict 提升；
- 尚未做 one-shot 与 iterative、4/6/8 actions 的严格消融，因此不能声称完整复现 ReFind 的多轮收益。

具体原文章节、页码和可借鉴分析见 [E1–E7 结果分析框架与论文写作地图](../analysis/e1-e7-results-analysis-framework.md)。

### 4.3 报告结构与向师兄汇报

参考根目录的 `sample report.pdf`，形成了正文约 28 页的报告框架：Introduction 3 页、Background/Related Work 4 页、System Design/Methodology 7 页、Experimental Design 4 页、Results/Analysis 7 页、Discussion/Limitations 2 页、Conclusion 1 页，参考文献约 2 页。

报告不按 E1、E2……逐个写章节，而按四个研究问题组织结果。这样做是为了让论文主线从“跑了七组实验”提升为“存储组织、LLM 整理、检索增强和双源融合分别在何时有效、为何失效、付出多少成本”。同时整理了包含 E1–E7 条件、核心分数和初步结论的师兄汇报口径。

`sample report.pdf` 是第三方参考材料，只用于观察结构和篇幅，不是本项目产物，因此没有上传 GitHub。

### 4.4 新 baseline 的取舍

师兄建议加入 A-MEM、Mem0 和 Full Context 三个 baseline。综合一个月工期、实现成本和比较价值后，当前只实施 **B3 Full Context**：

- A-MEM 和 Mem0 涉及外部框架适配、图/记忆写入流程、模型与检索配置对齐，暂缓；
- Full Context 无需新增记忆算法，能够直接回答“如果把所有原始信息都给模型，结果和成本如何”；
- Full Context 可作为诊断信息不可见、检索失败和长上下文注意力问题的参照。

“只做 Full Context”是当前范围决定，不代表 A-MEM/Mem0 已经实现或运行。

## 5. 10 月 11 日：完成 B3 Full Context 的离线实现

### 5.1 做了什么

新增独立 `B3-FullContext` baseline：

- 从冻结 S1 确定性构造完整上下文源包；
- 保留 30 sessions、568 source turns 和 125 个 BLIP captions；
- 实现独立 EvidenceBundle、runner、CLI、检查点、run lock、失败记录、批次审计和评分；
- 准备 dev-6 和 main-40 两套运行 manifest；
- 完成离线 prepare/dry-run 和故障注入测试。

固定源包位于：

`experiments/locomo-conv50-v1/baselines/b3-full-context-v1/`

| 项目 | 固定结果 |
|---|---:|
| sessions | 30 |
| source turns | 568 |
| BLIP caption turns | 125 |
| evidence characters | 108,960 |
| evidence text SHA-256 | `12c3041b32cd7ff32bf6c913b95992cebf48ed3bd1d28ff9f1cdd29c8e927738` |

### 5.2 怎么做

Full Context 的每道题采用以下流程：

```text
当前问题 + 30 个 S1 原始 session 正文
                 ↓
       同一个共享 Answerer
                 ↓
          回答 + ev-* citations
```

它不先搜索，不使用 R1/R2/R3、BM25、Top-K、reranking、上下文扩展或检索 Agent；`tools=[]`。每道题都重新发送同一份完整聊天，只替换问题。

为保证公平，模型只读取经过 source attribution 验证的聊天正文，不读取 S1 的 YAML frontmatter 和纯路由标题；不总结、不改写、不去重、不截断。正式 citation 继续使用共享 Answerer 支持的内容寻址 `ev-*`，`FC-S01` 至 `FC-S30` 只作为人工别名保存于 metadata。

离线检查发现：dev-6 最长请求约 118,939 characters，估计为 33,983–41,013 input tokens；加 2,048-token 回答预留后约为 36,031–43,061 tokens。因此 32k context 可能不足，64k 更安全，但学校部署的真实窗口必须通过 API 返回确认。

### 5.3 为什么做

Full Context 是“没有记忆、没有检索、全部信息可见”的参照。它用于回答：

- E1–E7 的错误是否主要来自检索不到信息；
- 即使所有信息可见，长上下文噪声是否仍会让 Answerer 出错；
- 省去检索是否值得每题重复发送完整上下文的巨大成本。

### 5.4 工程问题与解决

构建过程中处理了以下关键问题：

- `FC-Sxx` 不符合共享 Answerer 的引用 schema，改用正式 `ev-*`；
- audit 中动态时间会破坏重复验证的幂等性，改为纯确定性身份；
- portable adapter 实际不发送 `max_completion_tokens` 和 `reasoning_effort`，manifest 按 wire 真实值记录；
- immutable record/failure 使用临时文件、`fsync` 和同目录 hard link 原子发布；
- events 使用文件锁和短写循环，避免崩溃或并发交错；
- batch 完成必须是题目顺序上的连续 block，不能只看任意完成数量；
- main-40 之前增加机器强制的 q079 preflight 与 dev-6 pilot 门禁。

测试结果：

- `tests.test_full_context`：8/8 通过；
- 全仓库 `unittest discover`：325 项通过；
- 既有 R1 prompt 的 8 个额外断言 case 全部通过；
- `formal-v1` verify 通过，证明新增 baseline 没有改变原 E1–E7 冻结实验。

### 5.5 当前边界

Full Context **尚未真实联网运行**：

- dev-6 为 0/6，仅完成离线准备；
- main-40 为 0/40，仅完成离线准备；
- q079 真实 API context preflight 尚未执行；
- 当前没有 Full Context 的真实分数或 provider token。

详细说明见：

- [B3 Full Context 准备记录](2026-10-11-full-context-preparation.md)
- [B3 Full Context 操作与跑批指南](../plans/full-context-baseline-v1-operation-plan.md)

## 6. 10 月 11–12 日：构建并完成 LLM-as-Judge v1

### 6.1 为什么增加 Judge

官方 token F1 要求候选回答与参考答案在词面上重合。正确同义改写可能被低估，带有部分正确事实的答案也难以区分“完全错误”和“部分正确”。因此增加一个补充语义 Judge，但不修改 280 条原答案，也不替代官方 F1。

### 6.2 评分方案

每条答案只由**同一个匿名 Judge 判断一次**。Judge 只看到问题、参考答案和候选答案，不看到 E1–E7、存储方法、检索方法、EvidenceBundle 或 token F1。

Judge 输出一个标签，再派生两个评分：

| 标签 | 含义 | Strict | Soft |
|---|---|---:|---:|
| `correct` | 语义完整正确、无实质矛盾 | 1 | 1.0 |
| `partial` | 有必要事实正确，但存在遗漏或实质问题 | 0 | 0.5 |
| `incorrect` | 核心答案错误、拒答或未覆盖必要信息 | 0 | 0.0 |

因此不是两个 LLM，也不是先打 partial 再进行第二次评分：

- `Strict Accuracy = correct / 40`；
- `Partial Rate = partial / 40`；
- `Soft Semantic Score = (correct + 0.5 × partial) / 40`。

### 6.3 怎么实现与运行

新增：

- `fs_memory_lab/judge_v1.py`；
- `fs_memory_lab/judge_v1_cli.py`；
- `tests/test_judge_v1.py`；
- [LLM-as-Judge v1 评分协议](../plans/llm-as-judge-v1-protocol.md)。

运行仍采用 8 batches × 35 条：固定输入顺序、串行、temperature=0、精确 JSON schema、最多一次仅修格式的 repair、有限 API retry、逐条内容寻址和原子发布、逐批 audit/PASSED、最后 verification 与 final audit。served model 不等于 `qwen3.8:27b` 时直接失败。

实现时发现 initial validator 错把 Git implementation commit 当成 64 位 SHA-256；Git commit 实际是 40 位十六进制。随后增加独立 `_COMMIT` 规则并加入回归测试。修复没有改变 Judge prompt、标签、输入、模型或得分映射。

学校 API key 只进入评分进程环境，不显示、不写入项目文件，也不进入公开归档。

### 6.4 完成结果

`llm-judge-v1-main40-run-01` 已完成：

- 280/280 judgments；
- E1–E7 各 40 条；
- 8/8 batches passed；
- 活动失败为 0；
- format repair 为 0；
- verification 和 final audit 均为 `passed`；
- correct 168、partial 57、incorrect 55；
- Judge 总 tokens 为 182,951。

| 条件 | correct | partial | incorrect | Strict Accuracy | Partial Rate | Soft Semantic Score | Judge tokens |
|---|---:|---:|---:|---:|---:|---:|---:|
| E1 | 24 | 9 | 7 | 0.6000 | 0.2250 | 0.7125 | 26,052 |
| E2 | 20 | 11 | 9 | 0.5000 | 0.2750 | 0.6375 | 23,668 |
| E3 | 25 | 9 | 6 | **0.6250** | 0.2250 | **0.7375** | 23,889 |
| E4 | 25 | 6 | 9 | **0.6250** | 0.1500 | 0.7000 | 24,337 |
| E5 | 25 | 8 | 7 | **0.6250** | 0.2000 | 0.7250 | 29,249 |
| E6 | 25 | 5 | 10 | **0.6250** | **0.1250** | 0.6875 | 26,931 |
| E7 | 24 | 9 | 7 | 0.6000 | 0.2250 | 0.7125 | 28,825 |

本地与公开位置：

- 本地权威运行：`local-runs/llm-judge-v1/llm-judge-v1-main40-run-01/`
- GitHub 归档：`experiments/locomo-conv50-v1/results/llm-judge-v1-main40-run-01/`
- 详细记录：[LLM-as-Judge v1 完成记录](2026-10-12-llm-judge-v1-completion.md)

Judge 结果归档包含 280 个逐题 JSON、8 组 audit/PASSED/log、manifest、events、status、results、verification、final-audit 和逐文件 `SHA256SUMS`。313 个归档文件的 SHA-256 已复验通过，凭据扫描未发现 API key。

## 7. 10 月 12 日：建立结果分析与论文写作地图

### 7.1 做了什么

新增独立文档 [E1–E7 结果分析框架与论文写作地图](../analysis/e1-e7-results-analysis-framework.md)，统一记录：

- 七个实验条件和两套评分；
- 四个核心研究问题；
- 逐题、分类别、证据、成本和可靠性分析；
- 与 Filesystem Memory、ReFind 论文的对应位置；
- 推荐表格、图和案例选择方式；
- 哪些结论现在可以写，哪些需要进一步实验。

### 7.2 为什么做

主实验已经看到结果，如果此时只挑有利数字，容易形成 post-hoc 解释。分析框架先固定“要比较什么、如何验证、结论边界是什么”，让报告不仅给出排名，还能回答机制问题。

四个核心研究问题确定为：

1. 文件组织方式何时有用？
2. 增强检索能否修复 Filesystem 的检索错误？
3. 错误发生在写入、检索还是回答阶段？
4. 保留原始聊天作为第二检索源是否值得？

### 7.3 准备采用的分析方法

- 关键条件的逐题配对差值与 win/tie/loss；
- correct/partial/incorrect 标签转移矩阵；
- C1–C4 分类别分析；
- token F1 与 Judge Strict/Soft 的一致性和冲突案例；
- retrieval bottleneck 与 utilization bottleneck 分解；
- Evidence Recall 与最终答案质量的关系；
- tokens–F1 和 tokens–Soft Pareto 图；
- cap、空证据、budget-skip、重试和 store hash 的工程可靠性分析；
- paired bootstrap confidence interval 与 McNemar exact test；
- 按固定规则人工复查 12–16 个代表性 trace。

### 7.4 当前尚未完成的分析

- P0：逐题合并表、bootstrap、转移矩阵和正式图表尚未生成；
- P1：12–16 个案例的人工 trace 复查尚未执行；
- P2：R2/R3 action cap 4/6/8、one-shot/iterative、更多 conversation 与 Judge 重复性属于可选扩展。

这些工作属于下一阶段，不能把分析计划写成已经得到的实验结论。

## 8. 当前结果可以支持的初步结论

两套评分合起来看，当前可以谨慎写出以下描述性结论：

1. **E3 最稳定**：官方 F1 最高，Judge Soft 也最高；S2 的目录结构对 R1 可能有实际帮助。
2. **目录收益依赖检索器**：E2 与 E4 的官方 F1 几乎一致，说明 R2 下目录本身没有明显词面收益；但 E4 的语义 Strict/Soft 好于 E2。
3. **增强检索的主要优势目前是成本**：E2/E4/E6 的 token 明显低于各自 R1 对照，但质量收益随存储和评分口径变化，并非总是提升。
4. **高证据召回不等于高答案质量**：E5 的 Evidence Recall 最高，官方 F1 和 Judge Soft 却都不是最高，说明瓶颈可能在噪声、整理质量或证据利用。
5. **双源融合是部分互补而非全面胜利**：E7 的 Evidence Recall 与 Soft 较高，但官方 F1 没有超过 E2/E6，Strict 也没有稳定提升；它可能同时恢复信息和引入干扰。
6. **单一指标不足以解释结果**：例如 E2 的 token F1 高于 E1，但 Strict/Soft 低于 E1；E7 的 token F1 较低，却有高于 E2/E6 的 Soft。论文必须同时报告词面、语义、证据和成本。

当前样本只有一个 conversation、40 道题和一次 Judge 运行，因此这些都是 empirical/descriptive findings，不能直接声称具有普遍因果性。

## 9. 两天内解决的主要问题

| 问题 | 处理方式 | 为什么这样处理 |
|---|---|---|
| API 超时、偶发协议违规导致正式跑批中断 | 只重试失败记录，检查点续跑，已完成记录复验后跳过 | 保持 formal-v1 冻结协议并避免重复计数 |
| 长时间运行可能启动重复进程 | 唯一 run lock、单进程、逐批 PASSED 门禁 | 防止相同问题被并发重复调用 |
| 只看 F1 无法识别语义等价 | 新增匿名三档 Judge，但保留 F1 为主指标 | 同时保留可复现性与语义解释力 |
| Judge 容易看到方法身份而产生偏差 | 输入只含 question/reference/candidate | 让七个条件接受同一匿名标准 |
| Judge implementation commit 校验错误 | 64-hex SHA-256 与 40-hex Git commit 分开校验 | 修复程序错误而不改评分协议 |
| Full Context 的 `FC-Sxx` 与共享引用 schema 不兼容 | 正式使用 `ev-*`，人工别名只放 metadata | 复用统一 Answerer 与 citation validator |
| Full Context 可能超过模型上下文窗口 | 固定 q079 近最坏情况 preflight，再完成 dev-6 gate | 在消耗 main-40 前先验证部署能力 |
| 动态 audit 字段破坏可复现性 | audit 身份改为确定性内容 | 同一输入重复验证必须得到同一结果 |
| 运行结果可能包含凭据或本机临时状态 | key 只进进程环境；归档排除 secret、PID、lock，并做扫描 | GitHub 只保存科学结果和可公开证据 |
| 看到结果后容易选择性分析 | 单独冻结分析框架、RQ 和统计方法 | 限制 post-hoc 叙事，便于论文复核 |

## 10. 两天形成的主要文件

### 10.1 正式 E1–E7

- `experiments/locomo-conv50-v1/results/formal-v1-main40-run-02/`
- [formal-v1 main-40 完成记录](2026-10-11-formal-v1-main40-completion.md)
- [formal-v1 main-40 评分结果](2026-10-11-formal-v1-scoring-results.md)

### 10.2 Full Context

- `experiments/locomo-conv50-v1/baselines/b3-full-context-v1/`
- `fs_memory_lab/full_context.py`
- `fs_memory_lab/full_context_runner.py`
- `fs_memory_lab/full_context_cli.py`
- `tests/test_full_context.py`
- [B3 Full Context 准备记录](2026-10-11-full-context-preparation.md)
- [B3 Full Context 操作指南](../plans/full-context-baseline-v1-operation-plan.md)

### 10.3 LLM-as-Judge

- `fs_memory_lab/judge_v1.py`
- `fs_memory_lab/judge_v1_cli.py`
- `tests/test_judge_v1.py`
- [LLM-as-Judge v1 协议](../plans/llm-as-judge-v1-protocol.md)
- [LLM-as-Judge 完成记录](2026-10-12-llm-judge-v1-completion.md)
- `experiments/locomo-conv50-v1/results/llm-judge-v1-main40-run-01/`

### 10.4 数据分析

- [E1–E7 结果分析框架与论文写作地图](../analysis/e1-e7-results-analysis-framework.md)

## 11. GitHub 提交与归档状态

两天内已经形成并推送的提交：

| Commit | 内容 |
|---|---|
| `ddb9155` | 归档 formal-v1 main-40 的 280 条完整结果 |
| `3ed4234` | 加入 LoCoMo 离线评分与结果说明 |
| `78d5d88` | 加入 Full Context baseline、源包、runner 和测试 |
| `e9d00d3` | 记录 Full Context 离线冻结状态 |
| `58ee659` | 加入可断点恢复的 LLM Judge pipeline |
| `5bbc0c5` | 修复 Judge 的 Git commit 身份校验 |
| `a2b59db` | 归档 280 条 Judge 结果并加入分析框架 |

公开归档遵守以下边界：

- 上传代码、文档、manifest、逐题结果、audit、日志和 SHA-256；
- 不上传 API key、Authorization/Bearer 内容、shell 历史、本地 secret、PID 或 run lock；
- 第三方 `sample report.pdf` 保持本地未跟踪，不作为项目结果上传。

## 12. 下一步工作地图

按当前状态，建议下一步依次进行：

1. **完成 P0 离线分析**：生成逐题合并表、关键配对统计、类别表、转移矩阵和 Pareto 图；
2. **完成 P1 机制复查**：按固定规则抽取 12–16 个 trace，区分写入、检索、预算、利用与融合错误；
3. **开始报告写作**：先完成 Methodology、Experimental Design 和 Overall Results，再写 RQ1–RQ4；
4. **单独运行 Full Context**：先 q079 preflight，再 dev-6 pilot；只有门禁通过后才运行 main-40；
5. **可选扩展**：根据时间决定是否做 action cap 4/6/8、one-shot/iterative、更多 conversation 或 Judge 重复性，不回头改 formal-v1。

截至本记录完成时，E1–E7 主实验和两套评分已经完成；Full Context 是唯一已经完整搭好但尚未真实 API 跑批的新增 baseline；A-MEM 与 Mem0 保留为未来工作。

---

## 13. 2026-10-14 至 2026-10-16 后续更新：main-60 与第二 backbone

本节把随后两天的讨论、决策和实际进展继续记在同一份长笔记中。技术参数、故障经过、
冻结文件和后续 checklist 详见
[formal-v2 main-60 扩展计划与题集记录](2026-10-14-formal-v2-main60-planning.md)。

### 13.1 为什么继续扩展

师兄提出三项关键问题：40 题规模偏小；检索 Agent 与 Answerer 只有 Qwen 一个 backbone；
Judge 不应再使用与被评系统相同的模型。因此后续主计划确定为：

1. 保留原 40 题和 280 条结果，append-only 增加 20 题，形成 main-60；
2. Qwen 作为 Model 1，增加 `x-test-2` 作为 Model 2；
3. 新的统一 Judge 计划使用 `x-test-1`，但必须先通过 served-model 与协议 preflight；
4. old-40、new-20、combined-60 分开报告，不能把事后扩展包装成事前抽样；
5. S1/S2/S3 是既有固定快照，第二 backbone 只替换查询阶段的检索与回答模型。

### 13.2 新增 20 题和 Qwen 结果

新增题从 LoCoMo `conv-50` 的可靠剩余题中确定，配额为 C1/C2/C3/C4=`3/3/0/14`，与
原 40 题组合后得到 `13/13/7/27`。旧题及其顺序、hash 和结果不改写。

Qwen extension-20 已用独立 runner 完成：

- 20 题 × E1–E7，共 140/140；
- E1–E7 各 20 条，4 个 batch 全部通过；
- pending=0，active failed keys=0；
- 11 次历史失败尝试均由 checkpoint 恢复，且保留成本/事件审计；
- pre-gold verify=`passed`，生成 `ANSWER-RUN-COMPLETED-NO-JUDGE`；
- 本阶段按要求没有运行 token-F1 或 LLM-as-Judge。

由此 Qwen 已具备 old-40 的 280 条加 new-20 的 140 条，共 420 条 main-60 答案。
去凭据公开归档位于
`experiments/locomo-conv50-v1/results/formal-v2-qwen-extension20-run-01/`。

### 13.3 Model 2 的准备、故障修复与 pilot

Model 2 的目标是做严格的 backbone 对照，而不是发明另一套检索方法。正式 preflight 已确认
requested alias=`x-test-2`，实际 served model=`deepseek-v4.1-flash`，并验证 Retrieval
Agent、Answerer、R1/R2/R3 的 JSON/动作协议。

随后建立完全独立的 Model 2 runner、manifest、checkpoint、batch audit 和恢复控制；离线
dry-run 已验证 60 题、420 个唯一 key、12×35 batch、模型身份、断点恢复、预算/caps、
store/prompt hashes 和 E7 无重新检索，且不产生正式答案。

第一次 dev-6 pilot `run-01` 在 16/36 retrieval 后暴露出一个工程恢复缺陷：恢复状态错误地
在不同 key 之间共享。该 run 被保留为 aborted 证据，绝不续跑或计入结果。修复将恢复状态
隔离到每个 execution key，没有改变题目、prompt、模型、存储、预算或检索协议；修复后用
全新 candidate-02 和 run-02 重跑。

`run-02` 已通过：

- 36/36 retrieval episodes；
- 42/42 answers，E1–E7 各 6；
- requested/served model 全程一致，无身份漂移；
- 一次 retrieval 失败已恢复并完整计费；
- final audit=`passed`，`MODEL2-PILOT-42.PASSED` 存在；
- E7 确认只复用 E2/E6，不重新检索；Judge 未运行。

pilot 通过后已建立 `formal-v2-model2` 版本级冻结，绑定 candidate-02、双 preflight、
pipeline manifest、final audit/PASSED hashes 和实现 commit `95986c3...`。截至本次更新，
Model 2 正式 main-60 的 420 条尚未启动。
去凭据 pilot 归档位于
`experiments/locomo-conv50-v1/results/formal-v2-model2-dev6-pilot-run-02/`。

### 13.4 双 backbone 是否公平

可以称为相同的科学条件包括：60 题及顺序、S1/S2/S3、E1–E7、R1/R2/R3、BM25、
Answerer prompt、temperature、B=16000、round/action caps、E7 融合、timeout 和并发。
有意改变的变量只有 backbone：

- Model 1：`coding → qwen3.8:27b`；
- Model 2：`x-test-2 → deepseek-v4.1-flash`。

Model 2 额外增加逐响应身份检查和有限自动恢复，这是工程控制差异，不改变检索/回答算法。
因此答案质量可以做受控 backbone 对照；但效率分析必须把“成功路径 token/调用”与
“失败和重试开销”分开报告，避免把不同恢复机制误当成模型质量差异。

### 13.5 后台运行与沟通方式

为避免 10 分钟一次的 heartbeat 打断研究讨论，今后冒烟测试和正式跑批采用：后台单实例
runner + 独立 Codex 监控任务。主对话不再接收周期性正常进度；独立监控只在里程碑、失败、
需要用户动作或全部完成时通知。恢复前必须检查 lock，已完成 key 不能重复执行，API key
只从 Keychain 注入，不进入日志、项目文件或 GitHub。

## 14. 更新后的执行顺序

| 顺序 | 任务 | 当前状态 | 目的 |
| ---: | --- | --- | --- |
| 1 | main-60 题集与 Qwen extension-20 | 已完成 | 将 Qwen 扩展到 420 条答案 |
| 2 | Model 2 preflight、dry-run、dev-6 pilot | 已完成 | 在正式成本前验证兼容性和恢复 |
| 3 | 冻结 formal-v2-model2 candidate-02 | 已完成 | 防止看到正式结果后改协议 |
| 4 | Model 2 正式 main-60，420 条 | 待启动 | 形成第二 backbone 完整对照 |
| 5 | Model 2 pre-gold verify | 待 Model 2 完成 | 先封存答案再加载评分信息 |
| 6 | `x-test-1` Judge preflight 与冻结 | 待完成 | 保证 Judge 独立且身份可核验 |
| 7 | 840 条统一 LoCoMo P/R/F1 | 待完成 | 给出可复现词面主指标 |
| 8 | 840 条匿名 LLM-as-Judge | 待完成 | 补充 Strict/Partial/Soft 语义指标 |
| 9 | 配对统计、类别、过程、错误与成本分析 | 待评分后 | 检验 E1–E7 排序是否跨 backbone 稳定 |

B3 Full Context 仍是候选 baseline，但不应插入或改变当前已经冻结的双-backbone主实验。
A-MEM 与 Mem0 继续作为未来扩展，不在本轮主线中临时加入。

## 15. 2026-10-16 至 2026-10-17：正式运行和统一重评分完成

此前“待启动/待完成”的双 backbone 主线已经全部跑完：

- Qwen extension-20：140/140；Model 1 合计 420 条 main-60 答案；
- Model 2 candidate-02：420/420，12/12 batch 和 continuation pre-gold verify 通过；
- Model 1 新 20 题完成官方 LoCoMo P/R/F1；
- Model 2 全 60 题完成官方 LoCoMo P/R/F1；
- 独立 Judge `x-test-1 → glm-5.3-flash` 对两模型各评 420 条，合计 840/840；
- 两个 Judge run 各 12/12 batch、verification 和 final audit 全部通过。

Model 2 在 88/420 和 238/420 两次达到 R1 安全 fuse。用户明确授权保留既有记录并把 fuse
依次从 1,000,000 提高到 2,000,000、再提高到 4,000,000。除这两个内容寻址授权外没有
改变其他科学条件，最终结果明确披露为 `not-eligible-mixed-protocol`，不能冒充原始 fuse
下的一次性 formal run。

官方 token/stem 指标显示 Model 2 总体 Precision/Recall/F1 为
0.1957/0.6884/0.2636；低 F1 主要来自 Precision。统一匿名 Judge 则显示 Model 1 与 Model 2
的 Strict 分别为 0.7262 和 0.7119，Soft 分别为 0.7619 和 0.7560。两套语义分数很接近，
说明 Model 2 的长回答和额外词面内容会显著压低 token F1；但正式结论仍需逐题配对统计。

完整过程、条件级分数、Judge 模型纠正记录和归档位置见
[2026-10-16 至 17 完成记录](2026-10-16-to-17-main60-model2-and-rescoring.md)。

---

## 16. 2026-10-18 至 2026-10-20：报告框架、前三章正文与出版资产

这两天的工作重点从实验运行转向正式报告写作。主要完成了全报告框架、Chapter 1–3
英文正文、References、附录登记册，以及前三章图片和后续 LaTeX 迁移准备。

### 16.1 完成全报告框架和核心分析路线

根据统一 Main-60、两个 backbone 和 Full Context，重新整理了完整报告结构。最终报告采用
九章结构：引言、背景与相关工作、系统设计与方法、实验设计与评价、结果与问题分析、讨论、
局限、未来工作和结论。

第 3–5 章的职责被明确分开：

- Chapter 3 解释系统是什么、各组件如何工作，以及为什么形成 E1–E7；
- Chapter 4 解释实验怎样公平实施和评价；
- Chapter 5 按架构、跨-backbone 稳健性、错误机制和质量—成本决策展开结果分析。

结果分析将 60 道题视为一个统一测试集，不再拆分 old-40 和 new-20。核心分析沿三条主线展开：

1. 架构线：存储表示与检索方式如何交互；
2. 稳健性线：结论是否跨 Qwen 与 DeepSeek 成立；
3. 机制与决策线：错误发生在哪一阶段，以及 selective retrieval 与 Full Context 如何取舍。

主要框架文件：

- `docs/analysis/main60-complete-report-outline.md`
- `docs/analysis/main60-problem-analysis-detailed-outline.md`
- `docs/analysis/main60-three-system-results-analysis-framework.md`
- `docs/analysis/chapter1-2-detailed-writing-guide.md`

### 16.2 完成 Chapter 1–3 英文正文

三章均使用简洁、专业的英文，并统一采用 `long-term memory`、`Answerer`、`Full Context`、
`backbone model` 和 `LLM judge` 等术语。

#### Chapter 1: Introduction

Chapter 1 已完成研究背景、问题陈述、研究现状与缺口、研究目标、六个研究问题、研究贡献和
研究边界。正文先抽象说明存储、检索、证据利用和长上下文问题，不提前要求读者理解
S1–S3、R1–R3 或 E1–E7；这些正式标签留到 Chapter 3 定义。

- 正文：`docs/report/chapter-1-introduction.md`

#### Chapter 2: Background and Related Work

Chapter 2 已完成长期记忆基础、外部记忆表示、检索方法、Filesystem-Based Memory、ReFind、
LoCoMo 和多维评价方法的综述。该章区分通用研究背景与本项目实现，并在结尾解释现有研究
为什么不能直接回答本文问题，从而过渡到 Chapter 3。

- 正文：`docs/report/chapter-2-background-and-related-work.md`

#### Chapter 3: System Design and Methodology

Chapter 3 首先把第二章的研究缺口转化为方法需求，再定义任务、数据结构和端到端信息流。
正文系统说明了 canonical source record 与 source map、S1–S3、R1–R3、共享
EvidenceBundle、condition-blind Answerer、E1–E7、E7 双源融合和 Full Context 诊断路径。
本章只说明系统与方法，不展开正式实验运行和本地工程控制细节。

- 正文：`docs/report/chapter-3-system-design-and-methodology.md`

### 16.3 建立并复核 References

References 采用 IEEE 数字引用格式，当前包含 14 项正式文献或软件引用。引用编号按正文首次
出现顺序排列，并已逐章核对 Chapter 1–3 的引用位置、支持论点和可复查的章节或页码。

重点规则：

- Filesystem-Based Memory 和 ReFind 按可核验的 arXiv preprint 引用，不写成已正式同行评审
  的会议论文；
- LoCoMo 的任务设计引用 ACL 2024 正式论文；
- LoCoMo 的具体评分实现引用固定 commit 的官方 evaluator；
- Main-60、S1–S3、R1–R3、E1–E7 和 Full Context 等项目事实不伪装成外部论文结论；
- 后续增加文献时，应统一更新编号，不能只修改孤立引用。

- 文件：`docs/report/references.md`

该文件同时保存正式 bibliography、Chapter 1–3 citation audit、核验位置以及版本和论断边界。
最终提交时只需把正式 bibliography 放入论文正文，审计表保留为内部核查材料。

### 16.4 建立附录登记册

已对 Chapter 1–3 逐节检查哪些内容应移入附录，并建立以下附录结构：

- Appendix A：完整 prompts；
- Appendix B：数据集和 Main-60 manifest；
- Appendix C：数据 schema、符号与 provenance；
- Appendix D：memory-store 构建与冻结快照；
- Appendix E：检索、融合和 Full Context 规格；
- Appendix F：实验条件、模型身份和固定控制；
- Appendix G：评分与成本协议；
- Appendix H：统计与错误分析协议；
- Appendix I：补充结果和案例；
- Appendix J：论文、表格、图片和资产来源。

- 文件：`docs/report/appendix-register.md`

登记册还保存了 Chapter 1–3 的附录候选项、权威源文件位置，以及今后每完成一章都要执行的
维护规则。

### 16.5 Chapter 1–3 图片的位置和用途

#### Chapter 1

图片目录：`docs/report/figures/chapter-1/`

| 图片 | 正文位置 | 用途 |
|---|---|---|
| Figure 1.1 | §1.1.1 后 | 展示跨多个 session 的长期对话记忆问题 |
| Figure 1.2 | §1.1.2 后 | 对比 Full Context 与 selective retrieval |
| Figure 1.3 | §1.1.3 后 | 展示 storage–retrieval–utilisation 管线及主要故障点 |
| Figure 1.4 | §1.3.4 后 | 总结研究版图与尚未解决的比较缺口 |
| Figure 1.5 | §1.3.5 后 | 概览本文的受控实验设计和评价层次 |

#### Chapter 2

图片目录：`docs/report/figures/chapter-2/`

| 图片 | 正文位置 | 用途 |
|---|---|---|
| Figure 2.1 | §2.1.3 后 | 展示长期记忆生命周期和 storage/retrieval/utilisation failure |
| Figure 2.2 | §2.5.5 后 | 比较 Filesystem、ReFind-style 和 Full Context 的访问路径 |
| Figure 2.3 | §2.6.3 后 | 展示 LoCoMo 多 session、题型和 gold source-turn 结构 |
| Figure 2.4 | §2.7.5 后 | 展示答案、证据和过程指标分别观察管线的哪个部分 |

Figure 2.1 和 2.4 使用黑白灰线稿；Figure 2.2 和 2.3 使用全文统一的 navy、teal、amber、
red 和 violet 视觉语言。每张图均保留 PNG 和可编辑 SVG。

#### Chapter 3

图片目录：`docs/report/figures/chapter-3/`

| 最终图号 | 正文位置 | 用途 |
|---|---|---|
| Figure 3.1 | §3.3.5 后 | 总体系统架构与证据访问路径 |
| Figure 3.2 | §3.4.5 后 | 用代码框展示一个 source turn 的完整可追溯链 |
| Figure 3.3 | §3.5.3 后 | 比较 S1、S2、S3 的实际存储组织 |
| Figure 3.4 | §3.6.3 后 | 比较 R1、R2、R3 的检索控制流 |
| Figure 3.5 | §3.7.7 后 | 展示 evidence validation、EvidenceBundle 和 Answerer 的交接 |
| Figure 3.6 | §3.9.2 后 | 对比 E7 双源融合与 Full Context |

Chapter 3 的最终图号按正文首次出现顺序确定。部分素材文件保留了审核期间的工作编号，因此
正文图号与文件名数字不完全相同；映射以 `docs/report/figures/chapter-3/README.md` 为准，
不再重命名已经批准的资产。

### 16.6 LaTeX 迁移准备

图片使用稳定的项目相对路径。各图片目录包含 manifest 和 SHA-256 文件；SVG 是可编辑的
矢量母版，PNG 用于当前 Markdown 预览。最终排版时可把 SVG 导出为 PDF，再在 LaTeX 中
替换扩展名。

Chapter 3 已另存完整的 LaTeX figure blocks：

- `docs/report/latex/chapter-3-figure-blocks.tex`

其中保存了六个 `figure` 环境、caption、label、推荐尺寸和插入位置。Figure 3.2 使用
`Verbatim` 代码框，其余图片当前引用高分辨率 PNG。LaTeX 主文档需要 `graphicx` 和
`fancyvrb`；后续可通过统一的 `\graphicspath` 管理 Chapter 1–3 资产。

### 16.7 后续维护规则

每完成一个新 chapter，需要同步完成四项工作：

1. 更新正文；
2. 更新 `references.md` 的 bibliography 和逐章 citation audit；
3. 更新 `appendix-register.md` 的附录候选和源文件位置；
4. 为新增图片保存正文位置、caption、可编辑母版、预览文件和 LaTeX 插入块。

这样可以避免正文完成后再集中补引用、附录或图片来源，也能降低最终转换为 LaTeX 时的遗漏风险。
