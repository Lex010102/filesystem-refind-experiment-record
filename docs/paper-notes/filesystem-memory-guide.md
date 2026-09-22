# 从零理解论文中的 filesystem memory

原论文：[`../../papers/primary/filesystem-based-memory-for-llm-agents.pdf`](../../papers/primary/filesystem-based-memory-for-llm-agents.pdf)。建议先读 Figure 1、Figure 2 和 Section 2
（论文页 4-6），再读 Section 3（页 7-9）、Appendix A.1/A.3（页 25-33）
与 Appendix C.4 的 Table 12（页 49-50）。本项目仅实现对话记忆中的
Agent-curated store + Center tools，不试图复现所有实验分数。

## 0. 先认识四个词

- **Memory store**：一组目录和 Markdown 文件。磁盘上的长期信息，不是
  模型一次调用中的临时上下文。
- **Chunk**：一次交给管理 Agent 的新内容。在论文的对话实验中，最多
  8 个连续对话 turn、3,000 字符。
- **Harness**：模型与文件之间的中介。模型只能选择被提供的工具并给
  参数；工具负责验证参数、读写文件、返回观察结果。
- **Tool loop**：`模型 -> 工具调用 -> 工具结果 -> 模型`，反复进行，
  直到模型给出最终文本或达到轮数上限。

## 1. Figure 1 到底说了什么

论文把一个系统拆成三种角色：

1. Management Agent：写入并维护记忆。收到第 t 段新内容后，把旧
   记忆 `M_(t-1)` 变成新记忆 `M_t`（Equation 1）。
2. Search Agent：在固定的记忆上回答问题，并给文件引用（Equation 2）。
3. Execution Agent：真正做外部任务。在 ALFWorld 技能实验中出现；
   普通对话问答可以先没有这个角色。

初学阶段只需要实现前两个角色，并先把 Management Agent 跑通。

## 2. Figure 2 为什么要用 Markdown + YAML

目录列表只展示文件名和 frontmatter 的一行 `description`。模型在没有
打开正文前，就要凭它们判断去哪里找。文件内部的 `#`、`##` 标题把
分类树继续延伸到章节。每条事实旁边的 `[S6T5]` 表示原始对话中
Session 6 Turn 5；它和搜索 Agent 最终引用的文件路径是两层不同来源。

例如：

```markdown
---
name: alice
description: Alice's current diet and earlier dining preferences.
---

# Current diet
- Vegetarian since 2026-05-14 [S6T5]

# History
- Previously enjoyed yakiniku and seafood [S1T1]
```

这比把“喜欢烤肉”和“吃素”都放在一个不带日期的 `Preferences`
列表里更可靠；后者会造成旧事实污染。

## 3. Harness 的核心：模型不直接碰磁盘

如果模型输出：

```json
{"name":"create","arguments":{"path":"/memories/people/alice.md","file_text":"..."}}
```

本地 `MemoryFS` 会：

1. 确认路径在专用 memory root 内，禁止 `..` 和指向外部的符号链接；
2. 确认目标是 `.md`，且不存在；
3. 检查 frontmatter 的 `name` 与文件名一致、`description` 非空；
4. 写入文件并给模型返回 `Created ...`。

模型看到这个结果后，才可以决定下一步。

论文 Center harness 中，管理 Agent 使用 7 个工具：`view`、`grep`、
`create`、`str_replace`、`insert`、`delete`、`rename`。搜索 Agent 使用
4 个只读工具：`view`、`grep`、`toc`、`section_read`。Table 12 给出
这些工具的参数和操作语义。

## 4. 跟着样例走一遍

输入文件 [`examples/alice/initial-dialogue.txt`](../../examples/alice/initial-dialogue.txt) 有先前的烤肉偏好和后来的吃素
更新。管理 Agent 理想的操作顺序是：

```text
第一段：view /memories -> create people/alice.md
下一段：view /memories -> grep Alice/vegetarian -> 查看相关文件
       -> 更新当前状态 -> 把烤肉偏好标为历史状态 -> 校验描述
```

随后搜索 Agent 面对“她现在吃什么、过去喜欢什么”应：

```text
view /memories -> grep / toc -> section_read 或 view 行范围
              -> 回答，引用 /memories/people/alice.md 的证据行
```

真实模型可能选择不同的工具顺序。Harness 保证的是**工具可用、
路径安全、结果可追踪**，并不保证模型每次都能写出高质量记忆。

## 5. 为什么不能只看目录是否整齐

论文在 Table 1（页 9）显示：Agent-curated store 在 LoCoMo 为
86.1% 正确率，但在 PersonaMem 32k 只有 37.5%，低于原始对话文件
的 78.1%。Appendix D.1（页 51-52）指出，关键事实其实仍在文件中；
问题是旧偏好继续被写成当前特征，情绪和变化过程被摘要抹平或拆散。

所以你的本地试跑要检查三件事：

- **工具正确**：文件能否安全读写；
- **记忆正确**：当前与历史状态是否表达清楚、来源是否保留；
- **检索正确**：搜索能否找到证据并给出准确引用。

## 6. 你现在可以亲手做的三步

1. `python3 -m fs_memory_lab.cli demo`：不需要 API，看到文件工具的结果。
2. `python3 -m unittest discover -s tests -v`：验证路径边界和角色权限。
3. 配置 API 后，运行 README 中的 `ingest -> show -> ask`，打开
   `memories/` 文件，逐条核对 `[S...]` 和时间状态。

跑通后才进入第二阶段：加载真实 benchmark，对原始日志与
Agent-curated store 的答案质量、检索成本和文件健康做系统比较。
