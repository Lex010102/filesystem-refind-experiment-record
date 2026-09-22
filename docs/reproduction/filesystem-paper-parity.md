# Center / Agent-curated 复现对齐记录

论文：*Filesystem-Based Memory for LLM Agents: Organization, Evolution, and Sustainability*，本地源文件 [`../../papers/primary/filesystem-based-memory-for-llm-agents.pdf`](../../papers/primary/filesystem-based-memory-for-llm-agents.pdf)（arXiv:2607.26637v1）。这里的“对齐”指已公开的默认 Center 设置；不能把代码通过测试等同于论文实验分数复现。

| 项目 | 论文出处 | 本地实现 | 状态 |
| --- | --- | --- | --- |
| 管理 system prompt | Appendix A.1，Prompt 1，PDF 第 25–27 页 | `fs_memory_lab/paper_prompts.py` 的 `BUILDER_BASE` | 按公开文本转录；排版字符/换行不保证 byte-exact |
| LoCoMo 来源标注扩展 | Appendix A.1，Prompt 2，PDF 第 27–28 页 | 同文件 `LOCOMO_ATTRIBUTION`，拼在 Prompt 1 后 | LoCoMo 版转录；其他 benchmark 版未公开完整文本 |
| Center 层级检索 system prompt | Appendix A.3，Prompt 5，PDF 第 31–33 页 | 同文件 `SEARCH_PROMPT` | 按公开文本转录；byte-exact 未证实 |
| 工具说明和参数 | Appendix C.4，Table 12，PDF 第 49–50 页 | `fs_memory_lab/paper_tools.py`，7 个管理工具、4 个检索工具 | 描述/参数/required 标志按表转录；完整 JSON 包装、工具顺序未在论文给出 |
| 管理/检索模型 | Appendix C.1，Table 11，PDF 第 47–48 页 | `fs_memory_lab/paper_config.py`：均 `gpt-5.4-mini`、high | 默认对齐；`FSMEM_MODEL` 覆盖会失配 |
| 输出上限 | 同表 | build 32,768；search 8,192；发送为 Chat Completions `max_completion_tokens` | 默认对齐 |
| 工具轮次上限 | 同表 | build 60；Center search 40 | 默认对齐；CLI 可显式覆盖作调试 |
| 数据流分块 | 同表和 C.1 Stream units | 每块最多 8 行/3,000 字符，每块一个管理 episode | 规则对齐；“一行=一轮”仅适合准备好的输入文件 |
| 随机种子 | 同表 | 每次 CLI 调用设置 Python seed 42 | 只对本地随机流程生效；论文没有说要覆盖 API 采样 seed |
| 查询并发 | 同表 | 常量 8，单题 CLI 不启用 | 批量 benchmark 环节未实现 |
| 上下文压缩 | 同表及 C.1 Generation and episode parameters | 超过 96k prompt tokens 时，用运行摘要代替旧轮，保留最近 3 轮，记录事件 | 形状对齐；摘要 prompt/表示方式为本地近似，原文未公开 |
| 文件视图 | 同表 | `view` 不截断文件，目录最多显示相对 3 层 | 对齐 |
| 工具删除 | Table 12 | 虚拟 `/memories` 中删除；本地保留可恢复副本，不向模型展示主机路径 | 模型可见行为近似；磁盘副作用不同 |
| API 适配 | Appendix A 开头、C.4 | Chat Completions 函数调用接口，高努力、输出上限；记录返回模型/指纹/usage | API 形状对齐；论文未提供原始请求 JSON 或版本锁定 |

## 为什么还不能说“完全复现”

1. 论文没有发布原始 prompt 常量、完整函数工具 JSON 包装、上下文摘要器 prompt、固定 user turn 的精确措辞。公开排版文本只能支持高保真转录。
2. 本项目没有 LoCoMo/REALTALK/PersonaMem 的官方数据 loader、论文测试子集运行器、八题并发和 judge，因此尚不能复现论文表格分数。当前演示文件只是小样本。
3. 未用你的真实 API 做一次端到端 ingest + ask。无网络测试只能证明请求内容和工具循环按代码预期组成，不能证明真实模型可用、结果质量或费用。
4. 如果 API 不是 `gpt-5.4-mini` 的 OpenAI 服务，即便兼容函数调用，模型和提供商缓存/采样行为仍与论文不同。

先运行 `python3 -m fs_memory_lab.cli config` 核对默认值；再给终端设置 `FSMEM_API_KEY`，用演示输入做一次低成本接入验证。不要把密钥贴到聊天或代码里。
