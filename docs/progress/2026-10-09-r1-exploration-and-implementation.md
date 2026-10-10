# R1 探索、改造与当前实现总记录

更新时间：2026-10-09

本笔记集中记录 R1 从论文检索方案到本地 evidence-only harness 的全部关键探索、取舍、实现和当前状态。详细逐日过程仍保留在 `docs/progress/2026-10-05-locomo-data-preparation.md`；论文逐段对照见 `docs/reproduction/r1-evidence-only-contract.md` 与 `docs/reproduction/r1-prompt-redline.md`。

## 1. R1 是什么

R1 是 Filesystem 论文的原生文件检索路线：让一个 LLM Search Agent 像使用代码代理一样查看 `/memories`，自己决定查看目录、搜索关键词、打开文件或章节，并在证据充分时停止。它不是 BM25、向量搜索或 ReFind 排名器。

本项目把同一类 R1 检索用于三个实验条件：

| 条件 | 存储 | 论文 Prompt | 最大 provider rounds | 当前正式输入 |
| --- | --- | ---: | ---: | --- |
| E1 | S1：平铺原始 session | Prompt 7 | 20 | 30个逐字原始 session 文件 |
| E3 | S2：文件夹化原始 session | Prompt 6 | 20 | 内容与S1逐字相同，只改变目录路径 |
| E5 | S3：LLM 整理文件系统 | Prompt 5 | 40 | 2个人物文件、主题标题、事实 bullets 与 locator |

三者使用同一问题集、同一 evidence budget、同一 EvidenceBundle 和后续 Answerer。主要自变量是存储组织方式；R1 搜索原则保持为各自论文 Prompt 对应的文件导航策略。

## 2. 论文直接提供了什么

主来源是 `papers/primary/filesystem-based-memory-for-llm-agents.pdf`，SHA-256 为 `4186ea9a8ca5b5534e644a2a8c36e5594226df440b167093ea406e0e9a9bf42c`。

论文直接给出的内容包括：

1. Search Agent 的职责和 filesystem-native 搜索思路，见正文 Section 2.2。
2. S1、S2、S3 等存储变体以及对应检索 Prompt 家族，见 Section 3 和 Appendix A.3。
3. Prompt 5、6、7 的正文：
   - Prompt 5：层级化、LLM 整理过的存储；
   - Prompt 6：按主题文件夹组织的原始 session；
   - Prompt 7：根目录平铺的原始 session。
4. 四个只读工具 `view`、`grep`、`toc`、`section_read` 的参数和文字描述，见 Appendix C.4 Table 12。
5. Search Agent 的目标模型、8,192 completion-token cap、20/20/40 tool-round caps、96k context-compaction trigger、保留最近3轮等运行配置，见 Appendix C.1 Table 11。
6. 检索策略：先看一次目录，使用短而有区分度的关键词，优先 scoped search，必要时扩大范围，只读完成问题所需的上下文，证据充分后停止。
7. 文件 view 不裁剪。论文没有为一道题规定累计检索 token 上限，也没有给 E5 单独设置更小的读取预算。

论文没有公开作者源码、完整 JSON function schema、精确默认值、可执行 harness、状态恢复协议、EvidenceBundle schema、Answerer 接口或 summarizer prompt。因此本项目只能称为“论文 Prompt 的规范化转录 + 明确披露的本地补全”，不能称为作者源码的逐字节复刻。

## 3. 为什么选择 evidence-only，而不是 paper-direct

论文原始 Search Agent 会边搜索边直接作答。为了公平比较 R1、R2、R3 和融合方案，本项目决定让 R1 只交证据，不直接回答：

```text
问题
  -> R1 Research Agent 搜索文件
  -> host 验证并生成 EvidenceBundle
  -> 所有实验共用同一个 Answerer 作答
```

这样做的原因：

- 避免不同检索器同时承担不同的答案推理责任；
- 可以把“没找到证据”和“看到证据但答错”分开分析；
- 可以统一统计检索召回、证据质量、Answerer 正确率和 token 成本；
- R1、ReFind-inspired R2/R3 与双源融合能使用同一个下游接口。

这是本项目的 controlled modification，不是论文原始行为。完整 redline 覆盖 Role、cost-model commitment、verify/stop、inference、multiple choice、citation、absence 和 output，不是只改 Prompt 的首尾两句。

## 4. 四个论文工具与两个本地动作

### 4.1 论文工具

R1 向模型暴露且按固定顺序冻结的文件工具只有：

1. `view`：看目录、整份文件或指定行范围；
2. `grep`：在文件树中查关键词或正则；
3. `toc`：读取 Markdown 标题结构；
4. `section_read`：按标题读取章节。

这些工具全部只读，路径被限制在正式 `/memories` 根目录内。目录 view 会显示路径、大小和完整 frontmatter description。工具 schema、wire order、默认参数、路径检查、稳定排序与输出格式都已冻结并用测试约束。

### 4.2 本地 evidence-only 动作

为了不让 Search Agent 直接输出答案，本项目额外增加：

- `take_note`：只能引用此前真实工具 observation 的 `observation_id + path + line_start + line_end`；
- `finish_search`：只能提交结构化停止理由和缺失信息标签，不能携带答案或自由文本证据。

二者不是论文工具，代码和报告必须始终与四个论文 filesystem tools 分开统计。

## 5. EvidenceBundle 与证据防伪

每次成功文件工具调用都会产生不可变 observation。模型不能自己提供 evidence text、locator、说话人、日期或答案；host 会重新读取冻结文件并验证：

- 选择范围确实被较早轮次的 observation 完整覆盖；
- S1/S2 证据包含完整 source-turn block；
- S3 证据是带合法 `[SxTy]` 的事实正文行；
- locator 能通过固定 `source_map.json` 回到 canonical record；
- store、manifest、目录树和文件 hashes 没有变化；
- 重复、相邻或重叠证据按确定性规则处理；
- evidence budget 超限时整项跳过，绝不截断证据文字。

成功检索产生 hash-addressed EvidenceBundle；异常运行产生独立 RetrievalFailureArtifact，不能把半成品伪装成成功结果。公开 trace、bundle/failure、episode index 和完成 marker 构成 hash chain。每个 episode 的 observation receipt secret 只保存在权限为0600的私有 checkpoint 中，不进入公开 trace。

## 6. Agent 状态机与停止规则

一个 provider completion 计为一个 R1 round；同一 completion 中可批量调用多个相互独立的文件工具。每个模型响应只能选择一种模式：

- filesystem mode：一个或多个四工具调用；
- note mode：一个或多个 `take_note`；
- finish mode：唯一一个 `finish_search`。

混合模式、未知工具、重复 tool-call ID、自由文本答案或不兼容 wrapper 均 fail closed。普通工具参数错误、尚未观察的 note 或尚不满足条件的 finish 会返回结构化错误，让 Agent 下一轮纠正。

合法停止包括证据充分、全局兜底后确实未找到、全局兜底后连续两轮无进展、evidence budget reached，以及 host 强制 round limit。absence/no-progress 必须有“先 root survey、再 whole-tree grep”的真实 observation 证明，不能只凭模型声称没找到。

## 7. Prompt、上下文压缩与 NUS 模型适配

Prompt 5/6/7 被保存为 normalized published transcriptions；派生 evidence-only prompts、user wrapper 和全部 SHA-256 位于 `fs_memory_lab/r1_prompts.py` 与 `docs/reproduction/r1-prompt-manifest.json`。

论文给了 96k prompt-token trigger 和保留最近3轮，但没有给 summarizer prompt。本项目因此实现了明确标注为 local approximation 的 compaction：旧消息由单独一次只读模型调用摘要，保留最新3轮；compaction 的请求次数、served model 和 token usage 单独记录。

真实 E1 smoke 暴露了 NUS served model `qwen3.8:27b` 的 wire-format 偏差：模型找到了正确证据并接受 note，但后续合法工具调用旁夹带了 assistant prose。为避免把偶发格式问题误判成检索失败，Agent v2 增加受限纠正：

- 只有工具结构除此之外完全合法时才允许纠正；
- 污染响应的文字和 actions 都不执行；
- 每轮最多纠正1次，每题最多3次；
- 纠正 prompt 不回显污染文字；
- 纠正调用完整计入请求次数和 token 成本，但不算完成的 retrieval round；
- 第二次污染、纯自由文本答案或其他结构错误仍安全失败。

## 8. E5 成本探索与统一安全熔断

论文没有给 S1/S2/E5 设置累计检索 token 上限，也明确文件 view 不裁剪。S1/S2 并非理论上不会超标，只是当前 store 较小：

| Store | 文件数 | 目录 descriptions 总长度 | 平均文件大小 |
| --- | ---: | ---: | ---: |
| S1 | 30 | 约1,461字符 | 约3.8 KB |
| S2 | 30 | 约1,461字符 | 约3.8 KB |
| S3 | 2 | 约64,877字符 | 约152 KB |

S3 的两个 description 形式上是一行，但远大于论文所表达的简短“one-line summary”路标。因为目录 view 会返回完整 description，E5 即使 rounds 更少，也可能拥有更高 prompt cost。这被保留为待验证的 `metadata bloat` empirical finding，而不是在主实验前悄悄修改 S3。

当前决定：

- E5 保持论文式 R1，不单独限制目录、description、文件或 section 的读取长度；
- 暂不建立 `S3-short-description`；
- E1/E3/E5 统一使用每题 `1,000,000 provider_reported_total_tokens` emergency fuse；
- fuse 包含正常检索、协议纠正和 context compaction 的全部成功 API completions；
- 达到阈值的响应会被记录，但其中工具/actions 不执行，也不会再发下一次 API 请求；
- 触发后发布 `token_safety_fuse` failure artifact，不生成部分成功 bundle；
- fuse 是异常保护，不是 evidence budget，也不参与排名或截断 `view` 内容；`grep max_results` 仍是正常工具行为。

Agent v3 的 limits hash 为 `ed5f6b5077da7406b5fa2919a3c8100f4379cde23939e661f4a8caf02281024a`，并在 preflight 前验证。CLI preflight 会同时显示三 cells 共用的 fuse 配置和 `file_view_truncation: none`。

## 9. 当前真实 smoke 结果

三种存储使用同一道 dev 问题 `conv-50-q129` 和同一个 6,000-character smoke evidence budget：

| Cell | 状态 | Rounds | 文件工具调用 | Provider total tokens | 说明 |
| --- | --- | ---: | ---: | ---: | --- |
| E1/S1 | 成功并离线复验 | 12 | 4 | 85,117 | 找到 `D24:20–21`；2026-10-10 端到端 smoke 的共享 Answerer 另用 823 tokens |
| E3/S2 | 成功并离线复验 | 6 | 5 | 42,236 | 找到原始 session-24 对话 |
| E5/S3 | 成功并离线复验 | 3 | 2 | 88,349 | 找到 `dave.md > Japan` 整理事实 |

这只是连通性测试，不能据此判断哪种存储效果更好。三个 R1 条件现在都至少通过一题真实检索；E1 还进一步通过共享 Answerer、RunRecord 和自动评测。单题结果仍提示 S3 的目录元数据可能显著增加单轮输入成本，但必须在完整 dev-6 上验证。

## 10. 文件结构与各文件职责

### 程序

| 文件 | 职责 |
| --- | --- |
| `fs_memory_lab/evidence.py` | 共享 Question、StoreSnapshot、EvidenceItem、EvidenceBundle 和 failure schema |
| `fs_memory_lab/r1_tools.py` | 四个论文只读工具及安全文件系统边界 |
| `fs_memory_lab/r1_orchestration.py` | observation ledger、`take_note`、`finish_search`、预算和停止验证 |
| `fs_memory_lab/r1_prompts.py` | Prompt 5/6/7 转录及 evidence-only 派生 prompts |
| `fs_memory_lab/r1_inputs.py` | S1/S2/S3、dev-6/main-40 的冻结输入和 preflight |
| `fs_memory_lab/r1_agent.py` | Research Agent 状态机、retry、纠正、compaction、token fuse |
| `fs_memory_lab/r1_artifacts.py` | 成功/失败产物、usage 汇总、原子发布和离线校验 |
| `fs_memory_lab/r1_runner.py` | 单题与顺序批量运行 |
| `fs_memory_lab/r1_cli.py` | `preflight`、`run-one`、`run-batch`、`verify`、`verify-batch` 命令 |

### 测试与复现文档

- `tests/test_r1_*.py`：工具、orchestration、Prompt、Agent、输入、artifact、runner 测试；
- `tests/test_evidence.py`：共享 evidence schema 与攻击边界；
- `docs/reproduction/r1-evidence-only-contract.md`：R1正式实现合同；
- `docs/reproduction/r1-prompt-redline.md`：论文 direct-answer 与 evidence-only 的逐块差异；
- `docs/reproduction/r1-prompt-manifest.json`：Prompt hashes 和机器可读来源分类。

## 11. 如何查看和使用

只读预检，不调用 API：

```bash
cd '/Users/wangwenqi/Desktop/memory bench'
python3 -m fs_memory_lab.r1_cli preflight
```

正式运行前必须显式冻结 evidence character budget。单题命令形状：

```bash
python3 -m fs_memory_lab.r1_cli run-one \
  --cell E5 \
  --question-set dev-6 \
  --question-id conv-50-q129 \
  --run-id <unique-run-id> \
  --output-root '/Users/wangwenqi/Desktop/memory bench/local-runs/r1' \
  --budget-characters <frozen-budget>
```

批量命令按 cell-major 顺序串行运行，默认一题失败即停；`--continue-on-failure` 必须作为明确实验决定使用。API key 仍只通过 `FSMEM_*` 环境变量注入，代码、文档和 trace 均不得保存或显示 key。

## 12. 当前状态与下一步

当前 R1 harness 已完成，三种正式 store 和两套问题集均通过 preflight；E1、E3、E5 的真实 API smoke 均已通过，其中 E1 于 2026-10-10 完成共享 Answerer、RunRecord 与自动评测的完整链路。下一步应用完整 dev-6 同时检查三 cells 的正确性、token 分布、最大值和 fuse 是否不触发。只有在 dev-6 工程检查完成后才冻结正式 main-40 的 evidence budget 和运行配置，不能根据 main-40 结果回头调参。

本轮验证：55项 R1/evidence 聚焦测试通过；标准库全仓 discovery 中实际执行的212项测试通过；受本机 pytest/Anaconda 启动环境影响的 Prompt 模块已用 environment-neutral runner 执行其中9个 cases，全部通过。未调用学校 API。
