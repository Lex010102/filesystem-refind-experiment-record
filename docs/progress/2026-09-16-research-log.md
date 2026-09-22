# 研究进度记录：Filesystem Memory → ReFind 混合检索

记录日期：2026-09-16（中国标准时间）。本记录覆盖此前搭建的本地 harness、2026-09-15 的 Alice 试跑，以及 2026-09-16 对新研究方向的讨论。**Alice 对话中的 2026-05-10／05-14／05-16 是虚构案例的事件日期，不是实验执行日期。**

最新追加：2026-09-17（中国标准时间）。第 8 节记录 ReFind 的学习与组合方案探索；保留原文件名和此前记录，便于按时间追溯。

> 目录整理说明（2026-09-22）：本项目已重组为 GitHub 仓库结构。本日志中的链接已经更新为仓库相对路径；文中 `alice-run-02` 表示现在归档在 `artifacts/alice-pilot/` 的同一次历史试跑。

## 1. 一句话状态

Filesystem 的 **Center / Agent-curated** 本地原型已通过离线单元测试与学校 API 的函数调用检查，并完成 Alice 对话的两次独立 `ingest`；第二次写入成功修正了旧的海鲜偏好。当前只能说**小案例的增量写入初步跑通**，尚未对更新后的记忆执行并记录正式 `ask` 问答测试，也没有运行论文 benchmark。ReFind 检索器和 A+B 双源系统**尚未实现**。

## 2. 本地位置：从哪里打开

项目根目录：本 Git 仓库根目录。下面所有位置均以仓库根为基准。

| 文件／目录（相对于项目根目录） | 用途与目前状态 |
| --- | --- |
| [`README.md`](../../README.md) | 运行、API 环境变量、功能范围和非论文一致之处。 |
| [Filesystem 阅读指南](../paper-notes/filesystem-memory-guide.md) | 初学者版 filesystem 论文与 harness 解读。 |
| [论文对齐记录](../reproduction/filesystem-paper-parity.md) | prompt、工具 schema、默认配置的论文出处和本地对齐表。**其中“尚未用真实 API 做端到端 ingest + ask”是写于试跑前的旧状态；现在 ingest 已做，ask 仍未做。** |
| [`fs_memory_lab/cli.py`](../../fs_memory_lab/cli.py) | `config`、`check-api`、`ingest`、`show`、`ask` 命令入口；每次 ingest 写运行 trace 和更新前快照。 |
| [`fs_memory_lab/agent.py`](../../fs_memory_lab/agent.py) | 调用兼容 Chat Completions 的 API、模型／工具循环、usage 和 trace 记录。 |
| [`fs_memory_lab/filesystem.py`](../../fs_memory_lab/filesystem.py) | `/memories` 虚拟路径到专用磁盘目录的映射、文件操作和路径验证。这里的 harness 是应用层工具隔离，不是独立 OS 容器。 |
| [`fs_memory_lab/paper_prompts.py`](../../fs_memory_lab/paper_prompts.py) | 从 filesystem 论文公开附录转录的管理与检索 prompt。 |
| [`fs_memory_lab/paper_tools.py`](../../fs_memory_lab/paper_tools.py) | Center 工具定义、参数和角色权限。 |
| [`fs_memory_lab/paper_config.py`](../../fs_memory_lab/paper_config.py) | 论文默认模型、轮数、分块等配置。学校模型覆盖默认值，不是严格论文模型复现。 |
| [`tests/test_filesystem.py`](../../tests/test_filesystem.py) | 工具、路径、角色、分块、API 兼容模式等离线测试。 |
| [`examples/alice/initial-dialogue.txt`](../../examples/alice/initial-dialogue.txt) | **第一批**虚构 Alice 对话：5 行，从 05-10 的旧喜好到 05-14 的吃素更新、05-21 航班信息。 |
| [`examples/alice/2026-05-16-update.txt`](../../examples/alice/2026-05-16-update.txt) | **第二批**虚构 Alice 对话：2 行，明确说明她当前不吃鱼和海鲜，旧喜好仅为历史。 |
| [`artifacts/alice-pilot/memories/`](../../artifacts/alice-pilot/memories/) | 两次 ingest 后的持久化记忆，现有饮食和东京行程两个 Markdown 文件。 |
| [`artifacts/alice-pilot/runs/`](../../artifacts/alice-pilot/runs/) | 每次模型操作的 JSON trace；第二次运行下有更新前快照。 |
| [Filesystem 论文](../../papers/primary/filesystem-based-memory-for-llm-agents.pdf) | Filesystem 论文原文，本地 PDF。 |
| [ReFind 论文](../../papers/primary/when-your-agent-opens-the-chat-app-refind.pdf) | ReFind 论文原文，本地 PDF。 |

> 安全：学校 API 密钥只应保存在自己的终端环境／密钥管理器中。此文档、代码和运行记录不应包含密钥；不要把密钥粘贴进报告。

## 3. 已做的本地操作与证据

| 操作 | 实际执行／来源 | 已确认结果 | 能证明什么；不能证明什么 |
| --- | --- | --- | --- |
| 离线测试 | 2026-09-16，在项目根目录运行 `python3 -m unittest discover -s tests -v` | **15 个测试全部通过**。 | 工具接口、路径边界、角色权限等按本地代码工作；不说明真实模型的记忆质量。 |
| 学校 API 接入 | 用户终端将目标从 OpenAI 默认地址改为 NUS SoCLaas 网关 `https://soclaas-api.comp.nus.edu.sg/v1`；采用 `FSMEM_MODEL=coding` 和 `FSMEM_API_STYLE=portable` 的兼容调用。先前向 OpenAI 默认地址请求返回 HTTP 401。 | 用户终端 `check-api` 输出 `API function calling OK: requested_model=coding, served_model=qwen3.8:27b`。两次 ingest trace 也记录服务模型为 `qwen3.8:27b`。 | 学校端点能提供本 harness 必需的函数调用；不代表论文使用的 `gpt-5.4-mini` 已复现。模型别名将来可能改路由，正式实验应记录每次 `served_model`。 |
| 第一批 ingest | 2026-09-15，输入 [`examples/alice/initial-dialogue.txt`](../../examples/alice/initial-dialogue.txt)，当时项目名为 `alice-run-02`；[第一批 trace](../../artifacts/alice-pilot/runs/20260915T160006217961Z/chunk-001.json)。 | 输入 **5 行＝5 个供应给模型的 turn，1 个 chunk，1 次 CLI ingest／管理 episode**；模型 3 轮、3 次成功工具调用：`view`，随后 `create` 饮食与行程文件。trace 各轮 `total_tokens` 相加为 16,179（是 API 报告的轮次用量之和，不是费用）。 | 记忆创建链路可用。第一次生成的饮食文件仍将“Likes seafood”写成当前偏好，属于该案例的**记忆质量问题**，不能把首次结果称为完全正确。 |
| 第二批 ingest | 2026-09-15，**独立的第二次 CLI ingest**，输入 [`examples/alice/2026-05-16-update.txt`](../../examples/alice/2026-05-16-update.txt)，仍使用同一历史项目；[第二批 trace](../../artifacts/alice-pilot/runs/20260915T161030757261Z/chunk-001.json)。 | 输入 **2 行＝2 个 turn，1 个 chunk**。模型 8 轮、8 次成功工具调用：读目录与两文件、`grep`、3 次 `str_replace`、复读核对。trace 各轮 `total_tokens` 相加为 47,825。 | 验证了在旧文件基础上的真实增量更新，而不是把 05-16 内容预先混入第一批。单个虚构案例不足以证明长期稳定。 |
| 第二批前后比较 | [更新前快照](../../artifacts/alice-pilot/runs/20260915T161030757261Z/before-chunk-001/alice-dietary-preferences.md) → [当前饮食记忆](../../artifacts/alice-pilot/memories/alice-dietary-preferences.md)、[当前东京行程](../../artifacts/alice-pilot/memories/alice-tokyo-trip.md)。 | 更新前 frontmatter 和正文有当前 `likes seafood`；更新后写明 05-16 起不吃鱼／海鲜，05-10 的海鲜和烤肉是过去偏好，保留 `[S1T1]`、`[S7T1]` 等出处。 | 证明这次管理 agent 修正了可见的旧偏好污染；**尚未证明搜索 agent 能正确回答，亦未证明其他案例会成功。** |

`[S7T1]` = **Session 7, Turn 1** 的原对话定位标签。`[S6T5]` = Session 6, Turn 5。它们是证据出处，不是第 7 次／第 5 次模型调用，也不是文件写入次数。一次 `ingest` 可以包含多个带标签的 turn；本次确实是 **第一次 5 turn + 第二次 2 turn，分两批写入**。

## 4. 论文原文与我们做了什么：不要混写

### Filesystem 论文（`papers/primary/filesystem-based-memory-for-llm-agents.pdf`）

论文全称：*Filesystem-Based Memory for LLM Agents: Organization, Evolution, and Sustainability*（arXiv:2607.26637）。本地复现针对**对话记忆的 Agent-curated store + Center 工具**，不是全文所有架构／任务。

| 要点 | 论文原文位置（PDF 页码；请最终写报告时再次核对） | 本地状态／解释 |
| --- | --- | --- |
| Management → Search → Execution 三角色；记忆逐块演化 | Figure 1、Section 2，约 PDF 第 4–6 页 | 已实现管理与只读检索角色；对话小试验未实现 Execution。 |
| Markdown 文件、frontmatter、层级标题、来源定位 | Figure 2，约 PDF 第 5–6 页；Appendix A | 本地 memory 文件实现相同思想；生成内容由学校模型决定。 |
| 管理 7 个文件工具、检索 4 个只读工具 | Section 3 与 Appendix C.4 Table 12，约 PDF 第 7–8、49–50 页 | Center 文件工具已实现。论文另有 **Center+BM25** 和 **Shell** 变体；“原生完整 code-agent/Bash 检索”不是本地 Center 原型。 |
| Prompt、分块和运行参数 | Appendix A.1/A.3 Prompt 1/2/5，约 PDF 第 25–33 页；Appendix C.1 Table 11，约第 47–48 页 | 按公开文本和表格对齐默认值，见[论文对齐记录](../reproduction/filesystem-paper-parity.md)；原始 prompt 字节、部分固定 user turn、摘要器 prompt 未公开；学校 API 模型与参数兼容模式进一步破坏严格运行一致性。 |
| 文件整理不一定提升问答；旧偏好污染实例 | Section 4 与 Appendix D.1，约 PDF 第 9、51–52 页 | 论文 PersonaMem 32k 中 Agent-curated 正确率 37.5%，Verbatim dump 78.1%；附录分析过时偏好继续作为当前事实、细节被抹平和证据被拆散。**这是 A+B 的研究动机，不是 A+B 已被论文验证。** |
| 增加 BM25 文件检索工具的实验 | Section 4.5、Table 9/10，约 PDF 第 20–22 页 | 作者已研究 Center+BM25；仅把 BM25 加到文件检索上不能作为我们独有的新点。 |

### ReFind 论文（`papers/primary/when-your-agent-opens-the-chat-app-refind.pdf`）

论文全称：*When Your Agent Opens the Chat App: Agent-Controlled Search over Raw Chat Logs Rivals Structured Memory*（arXiv:2608.12888）。它保留**未经 LLM 改写的原始对话**；“无结构”不等于没有会话、时间和轮次元数据。BM25 是原文的检索入口，不是新写出的记忆卡片。

| 要点 | 论文原文位置（PDF 页码） | 若实现 A+B 时的含义 |
| --- | --- | --- |
| 两阶段：先多轮检索、记笔记，再由答案模型根据笔记回答 | Section 3、Figure 1，约 PDF 第 3–5 页；Appendix A prompt，约第 13–16 页 | 不能把“在 Markdown 上加 BM25”直接称为 ReFind；原文档案和检索代理需要独立建模。 |
| turn 级 BM25、会话级分数聚合与 RRF，默认 Top-K=5 | Section 3，约 PDF 第 5 页 | 原对话需保存 turn ID、session ID、时间、文本；检索可追踪到原始 turn。 |
| 命中周围前后各 2 turn、时间范围、跨搜索轮的已看会话去重 | Figure 1、Section 3，约 PDF 第 4–5 页 | 这些“聊天原生”控制可能帮助定位更新与上下文，但效果要实验验证。 |
| 最多 4 次检索迭代、`search_chatrecord`／`take_note`／`finish_search` | Section 4、Appendix A/配置，约 PDF 第 6、13–16 页 | 是 ReFind 的运行设计；不等于我们已有代码。 |
| Benchmark 与消融 | Table 2，PDF 第 7 页；Table 4，第 8 页；Table 11，第 20 页 | 原文在 6 个 MemoryAgentBench 子任务、共 2,800 题上报告 58.2% 宏平均，但复杂多跳事实更新 FC-MH 仅 8.8%；完整接口会增加在线 token／调用负担。两篇论文数据、模型和判分不同，**不能直接比较论文报告分数来证明 A+B 优劣**。 |

论文与公开数据入口：[Filesystem arXiv](https://arxiv.org/abs/2607.26637)、[ReFind arXiv](https://arxiv.org/abs/2608.12888)、[LoCoMo 官方数据／代码](https://github.com/snap-research/LoCoMo)、[MemoryAgentBench 官方数据／代码](https://github.com/HUST-AI-HYZ/MemoryAgentBench)。后两者是以后正式评测的候选来源；**当前 Alice 文件是自创诊断案例，不是论文给出的 Alice 官方测试集。**

## 5. 研究新方向：截至今日只讨论，尚未动工

师兄建议的 A+B：**LLM 自己维护 filesystem 记忆 + ReFind 式增强原始对话检索**。可提炼的研究问题：

> 当 LLM 管理的文件记忆遗漏细节、保留过时偏好或把更新拆散时，保留原始聊天的会话／时间感知检索，能在什么条件下恢复正确答案？恢复的 token、延迟和调用成本是多少？

建议把同一对话流同时送入两个存储层：① 只追加的原始聊天档案（原文、session／turn／timestamp）；② 管理 Agent 维护的 Markdown 文件。读取时至少比较 **F 文件独用、R 原文独用、H 两者混用**；再考虑一个 **F+普通 BM25 文件检索**控制，避免把论文已有的 Center+BM25 效果误当作我们的新发现。各读法应尽量固定同一实际服务模型、回答 prompt、检索预算和判分协议。已有的 Alice artifact 只能作为功能诊断，不适合报告主结论。

建议的 5 周阶段性里程碑：

1. 第 1 周：读 ReFind 原文，锁定问题、数据切片、评价标准、API 配额；记录事前假设与停止条件。
2. 第 2 周：实现原始聊天档案与检索器；先用小型固定案例验证 BM25、会话、时间、上下文与去重。
3. 第 3 周：接到现有 harness，做 F／R／H 统一读端，10 题 pilot 测调用、延迟和 trace 完整性。
4. 第 4 周：按学校 API 实际速度做约 30–60 道**配对**问题，记录答案与证据；若资源不足则缩成明确标注的探索性样本，不声称总体效果。
5. 第 5 周：做关键消融、人工核对误答和恢复案例，写“在哪些条件有效／无效、代价如何”的报告。

风险：全量 LoCoMo 一段对话有约 300–600 turn，写入成本可能高；ReFind 完整接口也不便宜。先以小样本估算资源，再决定是否扩展。**目标是一份严谨的小规模 empirical finding 报告，不保证一个多月内达到完整论文复现或可投稿的统计强度。**

## 6. 下一次工作从哪里接上

- **立即验证读端**：先把归档 memory 复制到被忽略的本地运行目录，再在已设置学校 API 环境变量的终端提问，避免修改 Git 中保存的历史 artifact。本记录编写时，artifact 只有两次 `chunk-001.json`，没有 `search.json`。

  ```bash
  mkdir -p local-runs/alice-read-check
  cp -R artifacts/alice-pilot/memories local-runs/alice-read-check/
  python3 -m fs_memory_lab.cli --project local-runs/alice-read-check ask --question 'As of 2026-05-16, does Alice eat seafood? What kind of restaurant should be suggested for Tokyo?'
  ```

- **动手 A+B 前**：先确定正式数据集与题目筛选规则，避免只挑对混合系统有利的例子；明确正确性、证据支持、过时事实误答、检索调用／token／时间四类指标。
- **维护对齐记录**：[论文对齐记录](../reproduction/filesystem-paper-parity.md)中的“未用真实 API”旧句需要在下一次文档维护时更新；正式实验记录每次 API 返回的实际模型、配置、代码版本／日期及数据切片。

## 7. 后续实验记录模板

每次新实验可复制下面字段到单独日志或结果表，避免报告阶段找不到条件：

| 字段 | 应记录的内容 |
| --- | --- |
| 日期、实验 ID、代码版本 | 实际运行时间、项目／trace 路径、代码快照。 |
| 数据 | 数据集版本、对话／session／turn 范围、题目 ID、选择规则。 |
| 写端 | 是否原文追加；管理模型、prompt、分块、文件数／大小、错误和构建 token。 |
| 读端 | F／R／H 或消融；实际服务模型、prompt、工具、迭代上限、检索预算。 |
| 输出 | 答案、引用的文件行／原始 turn、正确性、证据是否支持、旧事实污染标签。 |
| 资源与异常 | 请求次数、token、耗时、重试／限流、失败题目和人工误差分析。 |

## 8. 2026-09-17：ReFind 学习与 A+B 结合方式探索

本次工作性质：**论文学习、研究设计讨论、文档更新**。没有新增 ReFind 代码，没有调用模型运行 ReFind／混合检索，也没有新增 benchmark 结果。以下“推荐”“建议”“待实现”均为研究方案，不是已证实的效果或已经执行的实验。

### 8.1 今天理解清楚的核心区别

- **Filesystem**：收到新材料时，让管理 Agent 提炼、整理、更新主题笔记；以后由检索 Agent 查这些笔记。
- **ReFind**：原始记录保留，不预先让 LLM 改写成语义记忆；建立词汇索引，问题到来后由 Agent 多轮搜索、选存原文证据，再单独回答。
- ReFind 是使用已有模型的检索方法，不是新训练的大模型；标题“打开聊天 App”是找回旧消息的比喻，不意味着实际自动操作微信。
- “无结构”指不建立预先生成的语义摘要／实体图等记忆表示，**不等于没有索引、session、turn、时间元数据**。
- 重要区别：ReFind 的 `take_note` 是当前问题搜索过程中保存所选原文结果的临时证据笔记，**不是长期改写的 filesystem 记忆文件**。

### 8.2 ReFind 结构、机制与原文出处

本地原论文：[When Your Agent Opens the Chat App](../../papers/primary/when-your-agent-opens-the-chat-app-refind.pdf)；公开页面：[arXiv:2608.12888](https://arxiv.org/abs/2608.12888)。以下页码对应本地 PDF v2。

| 部分／机制 | 本次学习的解释 | 原文位置 |
| --- | --- | --- |
| 原始档案 | 保留原文、会话标识、轮次与时间；新记录加入档案并更新词汇索引，不需要 LLM 总结旧记录。 | Section 3，第 3、5 页 |
| 索引单元 | 方法部分的 turn 定义为用户发言及其助手回复，多个 turn 属于一场 session；不能直接默认等同于当前 Alice loader 的“一行=一个 turn”。 | Section 3，第 5 页 |
| BM25 | 根据词语匹配、频率和长度等对候选 turn 排序；高分代表关键词相关，不代表事实正确或当前有效。默认 `k1=1.2`、`b=0.75`。 | Section 3，第 5 页；Table 5，第 16 页 |
| 会话排名融合 | turn 自身的 BM25 排名，与其会话内分数聚合得到的 session 排名，通过 RRF 融合；默认平滑常数 60。由检索程序计算，不是模型临时提出。 | Figure 1、Section 3，第 4–5 页 |
| 相邻上下文 | 每个命中附带前后最多各 2 个 turn，不跨 session；默认 Top-K=5 是命中单元数，不等于只返回 5 句文字。 | Figure 1、Section 3，第 4–5 页 |
| 时间过滤 | 模型可指定日期范围；过滤的是记录时间，不会自动将文本里提到的事件时间抽取出来。因此 prompt 要求先广泛搜索，再按线索缩小时间，避免漏掉事后回忆。 | Section 3，第 5 页；Appendix A，第 14 页 |
| 已看会话排除 | 当前问题中先前返回过的 session，后续搜索自动排除，鼓励查新证据；不是删除原文，也不是未来所有问题永久不能查。整场排除可能漏掉尚未看见的证据，不能保证始终正确。 | Section 3，第 5–6 页 |
| 多轮控制 | Agent 根据上一轮结果换词、补证据或缩小日期；使用 `search_chatrecord`、`take_note`、`finish_search`。正文／Table 5 的迭代上限为 4，不应直接当作全流程模型调用次数。 | Section 4，第 6 页；Appendix A／Table 5，第 13–16 页 |
| 两阶段回答 | Stage 1 只找证据并选存原文，Stage 2 接收按会话、时间组织的 notes 和问题后回答。两阶段可以用同一模型，任务不同。 | Section 3，第 4 页；Appendix A，第 13–16 页 |

完整流程：问题 → Agent 选择搜索词／参数 → 程序返回命中和上下文 → Agent 选存可能相关的原文 → 不够则继续搜索 → 收集结束 → 证据按会话和时间组织 → 回答阶段根据证据作答。

接口注意：Appendix A 展示 `Thought / Action / Action Input` 的 ReAct 文本动作格式；当前 filesystem 原型使用 API function calling，不能声称这两个接口包装原样一致。ReFind 公开附录提供 prompt 和参数，**作者完整代码的发布／取得状态尚未核验**；本地没有作者 ReFind 实现。

### 8.3 学到的实验结果，以及不能过度推断的地方

| 实验 | 数据／条件 | 论文报告 | 解读边界 |
| --- | --- | --- | --- |
| 六任务比较 | MemoryAgentBench 的 SH-QA 100、MH-QA 100、LME 300、EventQA 1,500、FC-SH 400、FC-MH 400，共 2,800 题；GPT-4o-mini 检索和回答。 | ReFind 宏平均 58.2%，HippoRAG 2 53.2%，一次 BM25-RAG 48.8%；ReFind 五类最高，但 EventQA 74.1% 略低于 BM25-RAG 74.6%，FC-MH 仍仅 8.8%。Table 2，第 7 页。 | 宏平均是六类成绩等权平均，不是全部题的汇总正确率；基线大多复用其他论文结果，没有全部重新运行；不同任务使用不同官方判分方式。 |
| 更强骨干 | GPT-5-mini；固定 LongMemEval-S 50 题、M 15 题，ReFind 各重复五次。 | S 93.2% ± 3.3，M 89.3% ± 6.0；Table 3，第 8 页。 | ± 是运行波动，不是未来问题的保证；M 多答对一题约改变 6.7 个百分点，样本很小。 |
| 组件消融 | LongMemEval-S/M，相同骨干；完整方法五次，主要消融控制三次。 | 去掉全部聊天控制后 78.7%／82.2%；去掉前后文 84.0%／84.4%；去掉会话去重 92.0%／80.0%；仅一次搜索、取消后续选存和改词后 84.7%／68.9%。Table 4，第 8 页。 | 支持完整搜索接口有价值，但表中差值为描述性比较，不能说每个机制的普遍收益已被严格证明。 |
| 检索后端与资源 | 同一控制器下改为 dense／hybrid；另记录请求和 token。 | dense／hybrid 没超过 BM25 的平均成绩；完整方法每题约五次模型调用，在线 token 高于简单控制。Table 4，第 8 页；Table 11，第 20 页。 | 不是语义检索普遍没用；不用 LLM 建索引不等于答题免费或低延迟。 |

阶段性理解：论文支持“对精确证据查找、事实更新这类任务，完整原文 + 可控制的多轮检索很有竞争力”，而不是“所有语义记忆、文件整理都没有价值”。Filesystem 把较多计算放在写入时，ReFind 把计算移到提问时，成本应分开统计再合并考察。

### 8.4 A+B 有两种含义：今天作出的方向区分

| 方案 | 怎么结合 | 本次讨论的判断 |
| --- | --- | --- |
| 仅增强文件检索 | LLM 管理 Markdown；在整理后的文件上加入 BM25／多轮搜索等方法。 | 最直接接近“文件管理 + 增强检索”；但丢掉的原始细节不能救回。ReFind 的 session 排名、邻近 turn、时间规则不能直接照搬到多会话混合的主题文件上，需要重新设计、并明确叫 ReFind-inspired。 |
| 文件＋原文双源检索 | 同时保留 LLM 笔记和完整原始聊天，由读端从两边取证。 | 本次推荐作为小规模研究主方向；重点测试原文能否救回文件错误、文件能否帮助原文检索，以及总成本。**这是我们的方案建议，尚未实施，也没有预设效果更好。** |

新点边界：Filesystem Section 4.5 已比较 Center+BM25（第 20–22 页），所以“给文件加 BM25”本身不是全新的实验。双源、时间更新与恢复／干扰机制可以作为探索问题，但仍需后续查相关工作，**不能只凭这两篇论文宣布方法新颖性**。

### 8.5 推荐的最小双源版本：结构与写入

建议结构如下；**下面是拟建目录，不是已经存在的模块**：

```text
研究项目/
├── memories/       LLM 可整理、修改的主题笔记
├── raw_archive/    原始对话档案，只追加，不让管理 Agent 改写
├── indexes/        原始记录的关键词搜索索引
└── runs/           检索过程、答案、证据、usage 和异常记录
```

写入同一批材料时走两条路：

1. 程序保存原文、session／turn／timestamp／speaker 等字段，并更新检索索引。
2. 原 filesystem 管理 Agent 读取同一批材料，更新笔记、日期、出处和结构。
3. 笔记事实中的 `[SxTy]` 与原始档案的稳定 ID 对应，能够追溯原话；这些 ID 是桥梁，不是模型调用编号。

第一版建议保持现有管理 prompt，先不同时修改写端策略，否则读端效果变化时难以归因。原文追加与检索索引属于新增工程；当前 Alice 例子的存在不等于已搭好通用原文档案。

### 8.6 推荐的最小双源版本：读取与约束

第一版采用固定流程 **查文件 → 查原文 → 合并带出处的证据 → 单独回答**，暂不加入复杂自动回退／自动修复。

1. 文件检索返回相关正文、日期、文件路径／行号和原文 ID，作为候选证据与搜索线索，不提前认定为答案。
2. ReFind 风格检索从允许使用的原始历史中找证据；可以用文件中的实体名称辅助，也必须保留根据原问题直接搜索的能力。
3. **不能只查文件已引用的会话**：文件若漏掉新的更新，限定在旧出处范围会使原文层同样漏掉。文件帮助指路，不能把检索范围锁死。
4. 临时 notes 区分“文件证据”和“原文证据”，保留来源、时间与必要上下文，不混成无出处摘要。
5. 回答阶段区分当前状态、过去状态、纠正、条件、假设和不确定信息；**不采用“最新消息永远正确”的机械规则**。
6. 原文和文件冲突时检查原文含义与时间；无法判断则说明不确定，不能自动声称原文检索已经解决污染。
7. 读端不写回记忆。即便发现文件错误，也先记为待分析案例；否则后面的测试题会读到已改变的库，配对比较失去固定条件。

为什么先不做“文件答不出来才回退”？文件可能明确写错，而模型仍自信地答出来，触发不了回退。固定双源便于先测恢复、干扰和成本，再研究何时省略原文检索。这是本次推荐的实验简化，不是 ReFind 原文规定。

### 8.7 对照、预期发现与尚未定稿的实验协议

| 版本 | 可读材料 | 应回答的问题 |
| --- | --- | --- |
| F：文件独用 | Agent-curated Markdown | 文件路线本身的质量和成本如何？ |
| R：原文独用 | ReFind 风格聊天检索 | 不建文件记忆是否就足够？ |
| H：固定双源 | 文件 + 原始记录 | 文件是否帮助定位；原文是否恢复遗漏／更新，或反而引入干扰？ |

尽量固定同一实际服务模型、相同历史、问题、回答规则与明确预算；记录每种路线真实消耗。若为了共同两阶段回答框架改动了 F，需将其标记为受控文件基线，不能冒称论文原始 Center 的完整重跑。

除正确率外，记录：证据是否支持、旧事实误当现状次数、F 错 H 对的恢复案例、F 对 H 错的干扰案例、构建／更新与单题检索的调用／token／耗时。**必须与 R 比较**：若 H 和 R 一样好而多付文件构建成本，结论应是这批任务没有体现文件层价值，而不是只报 H 比 F 好。

正式运行前仍需确认：数据切片与题目选择、模型别名是否固定路由、总调用／证据量预算、重复运行次数、评分方法、gold 人工核对规则。对于增量 checkpoint，F／R／H 只能使用该点之前同一段历史，原文不能偷看未来更新；这是后续需要明确落实的防泄漏约束。

阶段性研究问题：

> 整理后的文件与原始聊天，在什么问题上互补？能否恢复因整理造成的证据遗漏或旧状态误答？这种恢复与干扰，值不值得构建和检索成本？

允许正结果、无提升或负结果；目标是带机制与失败案例的 empirical finding，不以必须取得最高总分为前提。

### 8.8 本次结束时的状态、位置和下一步

- 已完成：用初学者语言学习 ReFind 的背景、结构、工具流程、四个聊天控制和实验边界；区分“增强文件检索”和“双源原文检索”；讨论固定双源的最小版本与对照。
- 本次未做：新增检索代码、建立原文索引、调用 ReFind／H 模型测试、下载正式测试集或产生新实验成绩。本次也未重跑单元测试；第 3 节的 15 项通过结果仍属于 2026-09-16。
- 本次只读位置核对：`artifacts/alice-pilot/runs/` 仍只有两批 ingest 的 trace 和第二批前快照，没有该项目的 `search.json`；`fs_memory_lab/` 中未见新增 ReFind 模块。
- 代码和旧输出仍在第 2 节列出的路径；本学习记录追加在现有文档第 8 节，未另建第二份进度日志。
- 下一步推荐顺序：先按第 6 节测试现有 Alice 读端 → 锁定稳定原文 ID／session／时间 schema → 实现并单测 ReFind 风格检索 → 实现 F／R／H 小样本 pilot → 按资源决定正式规模。实施前再确认主方向；目前不把方案讨论当作所有设计已定稿。
