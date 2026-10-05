# Center / Agent-curated 复现对齐记录

论文：*Filesystem-Based Memory for LLM Agents: Organization, Evolution, and Sustainability*，本地源文件 [`../../papers/primary/filesystem-based-memory-for-llm-agents.pdf`](../../papers/primary/filesystem-based-memory-for-llm-agents.pdf)（arXiv:2607.26637v1）。这里的“对齐”指已公开的默认 Center 设置；不能把代码通过测试等同于论文实验分数复现。

| 项目 | 论文出处 | 本地实现 | 状态 |
| --- | --- | --- | --- |
| 管理 system prompt | Appendix A.1，Prompt 1，PDF 第 25–27 页 | `fs_memory_lab/paper_prompts.py` 的 `BUILDER_BASE` | 按公开文本转录；排版字符/换行不保证 byte-exact |
| LoCoMo 来源标注扩展 | Appendix A.1，Prompt 2，PDF 第 27–28 页 | 同文件 `LOCOMO_ATTRIBUTION`，拼在 Prompt 1 后 | LoCoMo 版转录；其他 benchmark 版未公开完整文本 |
| S2 Foldered sessions 建库行为 | Section 3，PDF 第 7 页 | `fs_memory_lab/foldering_prompt.py` 的 `FOLDERING_PROMPT` | 论文规定 LLM 设计 taxonomy、整文件 move-only、zero-byte edits，但没有公开建库 prompt 全文；本地文本是明确标注的重建版 |
| S2 建库工具 | Appendix C.4，Table 12，PDF 第 49–50 页 | `FOLDERING_PROFILE=(view, grep, rename)`；`MemoryFS.foldering_rename` 再强制同 basename、目标 topic folder 和字节不变 | 工具集合对齐；本地 guard 比论文通用 `rename` 更严格，以隔离“只有父目录变化”这一变量 |
| S2 建库配置 | Appendix C.1，Table 11，PDF 第 47–48 页 | `FOLDERING`：`gpt-5.4-mini`、high、60 rounds、32,768 completion cap | 模型/effort/通用 build rounds 对齐；论文未单列 foldering completion cap，32,768 是本地重建选择 |
| S2 安全执行与验收 | 论文只规定 move-only、zero-byte edits；未公开发布 runner | `fs_memory_lab/s2.py`：冻结输入/prompt、staging、失败隔离、全局 hash gate、路径映射、trace/manifest 和 COMMITTED 标记 | 本项目为了保护正式 S1 和保证可审计性增加的工程协议，不是论文作者代码 |
| Center 层级检索 system prompt | Appendix A.3，Prompt 5，PDF 第 31–33 页 | 同文件 `SEARCH_PROMPT` | 按公开文本转录；byte-exact 未证实 |
| 工具说明和参数 | Appendix C.4，Table 12，PDF 第 49–50 页 | `fs_memory_lab/paper_tools.py`，7 个管理工具、4 个检索工具 | 描述/参数/required 标志按表转录；完整 JSON 包装、工具顺序未在论文给出 |
| 管理/检索模型 | Appendix C.1，Table 11，PDF 第 47–48 页 | `fs_memory_lab/paper_config.py`：均 `gpt-5.4-mini`、high | 默认对齐；`FSMEM_MODEL` 覆盖会失配 |
| 输出上限 | 同表 | build 32,768；search 8,192；发送为 Chat Completions `max_completion_tokens` | 默认对齐 |
| 工具轮次上限 | 同表 | build 60；Center search 40 | 默认对齐；CLI 可显式覆盖作调试 |
| 数据流分块 | 同表和 C.1 Stream units；Prompt 8；Figure 5 | `fs_memory_lab/s3_chunks.py` 直接按 canonical source-turn records 切分；自然 session 内最多 8 turns，最终模型可见 payload 最多 3,000 Unicode code points，每块一个管理 episode | 双上限和每块一个 episode 为论文明文；session 硬边界由论文 chunk 命名及 85-step LoCoMo trajectory 推定；header、分隔符、字符度量和超长拒绝策略为本地冻结协议，作者未公开 byte-exact chunker |
| 随机种子 | 同表 | 每次 CLI 调用设置 Python seed 42 | 只对本地随机流程生效；论文没有说要覆盖 API 采样 seed |
| 查询并发 | 同表 | 常量 8，单题 CLI 不启用 | 批量 benchmark 环节未实现 |
| 上下文压缩 | 同表及 C.1 Generation and episode parameters | 超过 96k prompt tokens 时，用运行摘要代替旧轮，保留最近 3 轮，记录事件 | 形状对齐；摘要 prompt/表示方式为本地近似，原文未公开 |
| 文件视图 | 同表 | `view` 不截断文件，目录最多显示相对 3 层 | 对齐 |
| 工具删除 | Table 12 | 虚拟 `/memories` 中删除；本地保留可恢复副本，不向模型展示主机路径 | 模型可见行为近似；磁盘副作用不同 |
| API 适配 | Appendix A 开头、C.4 | Chat Completions 函数调用接口，高努力、输出上限；记录返回模型/指纹/usage | API 形状对齐；论文未提供原始请求 JSON 或版本锁定 |

## 为什么还不能说“完全复现”

1. 论文没有发布原始 prompt 常量、完整函数工具 JSON 包装、上下文摘要器 prompt、固定 user turn 的精确措辞。公开排版文本只能支持高保真转录。
2. 本项目已固定 LoCoMo10、`conv-50` canonical records、正式 S1/S2 stores 和 85 个确定性 S3 管理输入 chunks；但尚未运行正式 S3 管理构建，也未完成统一检索/回答/评测 runner、八题并发和 judge，因此仍不能复现论文表格分数。
3. 正式 S2 已用一次 NUS API episode 构建：requested alias 为 `coding`、served model 为 `qwen3.8:27b`，12 次模型调用完成 32 次 `view` 与 30 次 `rename`，随后通过离线完整性验证。该运行不是论文所用 backbone。
4. NUS 当前实际 served model 不是论文的 `gpt-5.4-mini`；即便兼容函数调用，模型和提供商缓存/采样行为仍与论文不同。

先运行 `python3 -m fs_memory_lab.cli config` 核对默认值；再给终端设置 `FSMEM_API_KEY`，用演示输入做一次低成本接入验证。不要把密钥贴到聊天或代码里。
