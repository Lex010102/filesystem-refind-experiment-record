# Center / Agent-curated 复现对齐记录

论文：*Filesystem-Based Memory for LLM Agents: Organization, Evolution, and Sustainability*，本地源文件 [`../../papers/primary/filesystem-based-memory-for-llm-agents.pdf`](../../papers/primary/filesystem-based-memory-for-llm-agents.pdf)（arXiv:2607.26637v1）。这里的“对齐”指已公开的默认 Center 设置；不能把代码通过测试等同于论文实验分数复现。

| 项目 | 论文出处 | 本地实现 | 状态 |
| --- | --- | --- | --- |
| 管理 system prompt | Appendix A.1，Prompt 1，PDF 第 25–28 页 | `fs_memory_lab/management_prompt.py` 的 `BUILDER_BASE` | 从官方 arXiv v1 TeX 的 Prompt 1 promptbox 逐字节提取并固定 SHA-256 `6f122e…a4a3` |
| LoCoMo 来源标注扩展 | Appendix A.1，Prompt 2，PDF 第 28 页 | 同文件 `LOCOMO_ATTRIBUTION`，拼在 Prompt 1 后 | 从官方 Prompt 2 promptbox 逐字节提取，SHA-256 `a8e35d…cf0b`；合并 prompt 为 `2ceb39…be26` |
| S3 per-chunk user wrapper | 论文只说明每个 chunk 一个 build episode，未刊出这一 user message | `fs_memory_lab/s3_protocol.py` | 本项目固定为最小 instruction + 两个换行 + 原样 chunk；明确标注 project-defined，不冒充论文原文 |
| S3 prompt contract | Appendix A.1 Prompt 1/2 | `manifests/s3-management-prompt.json` | contract 文件 SHA-256 `2b16c9…18a20`；合并 system prompt SHA-256 `2ceb39…be26`；论文文字、组合边界和本地 user wrapper 的来源分开记录 |
| S2 Foldered sessions 建库行为 | Section 3，PDF 第 7 页 | `fs_memory_lab/foldering_prompt.py` 的 `FOLDERING_PROMPT` | 论文规定 LLM 设计 taxonomy、整文件 move-only、zero-byte edits，但没有公开建库 prompt 全文；本地文本是明确标注的重建版 |
| S2 建库工具 | Appendix C.4，Table 12，PDF 第 49–50 页 | `FOLDERING_PROFILE=(view, grep, rename)`；`MemoryFS.foldering_rename` 再强制同 basename、目标 topic folder 和字节不变 | 工具集合对齐；本地 guard 比论文通用 `rename` 更严格，以隔离“只有父目录变化”这一变量 |
| S2 建库配置 | Appendix C.1，Table 11，PDF 第 47–48 页 | `FOLDERING`：`gpt-5.4-mini`、high、60 rounds、32,768 completion cap | 模型/effort/通用 build rounds 对齐；论文未单列 foldering completion cap，32,768 是本地重建选择 |
| S2 安全执行与验收 | 论文只规定 move-only、zero-byte edits；未公开发布 runner | `fs_memory_lab/s2.py`：冻结输入/prompt、staging、失败隔离、全局 hash gate、路径映射、trace/manifest 和 COMMITTED 标记 | 本项目为了保护正式 S1 和保证可审计性增加的工程协议，不是论文作者代码 |
| Center 层级检索 system prompt | Appendix A.3，Prompt 5，PDF 第 31–33 页 | 同文件 `SEARCH_PROMPT` | 按公开文本转录；byte-exact 未证实 |
| 工具说明和参数 | Appendix C.4，Table 12，PDF 第 49–50 页 | `fs_memory_lab/paper_tools.py`，7 个管理工具、4 个检索工具；S3 runtime contract 冻结管理工具顺序 `view/create/str_replace/insert/delete/rename/grep` | 描述/参数/required 标志按表转录；论文未给完整 JSON 包装或顺序。S3 有序 profile/schema/wire hashes 分别为 `e4541d…945e`、`3f4b2e…4b56`、`f36506…c282`，完整 wrapper 仍是本地重建 |
| 管理/检索模型 | Appendix C.1，Table 11，PDF 第 47–48 页 | 论文目标：`fs_memory_lab/paper_config.py` 的 `gpt-5.4-mini`、high；S3 本地实际 contract：NUS portable、requested `coding`、expected served `qwen3.8:27b` | 必须分层报告；本地 NUS backbone 不是论文同模型复现，且 runner 对每次返回的 served model fail closed |
| 输出上限 | 同表 | 论文目标 build 32,768、search 8,192；本地 S3 NUS portable 请求省略 `max_completion_tokens` | 论文目标值已冻结，但学校网关实际请求不能声称发送了该字段 |
| 工具轮次上限 | 同表 | build 60；Center search 40；正式 S3 每 episode 本地强制 60 | S3 正式 CLI 不提供临时覆盖；通用调试 CLI 的覆盖不属于正式 S3 协议 |
| 数据流分块 | 同表和 C.1 Stream units；Prompt 8；Figure 5 | `fs_memory_lab/s3_chunks.py` 直接按 canonical source-turn records 切分；自然 session 内最多 8 turns，最终模型可见 payload 最多 3,000 Unicode code points，每块一个管理 episode | 双上限和每块一个 episode 为论文明文；session 硬边界由论文 chunk 命名及 85-step LoCoMo trajectory 推定；header、分隔符、字符度量和超长拒绝策略为本地冻结协议，作者未公开 byte-exact chunker |
| 随机种子 | 同表 | 每次 CLI 调用设置 Python seed 42；S3 runtime contract 明记 provider request 不发送 seed | 只对本地随机流程生效，不能据此宣称真实 LLM 输出可重复 |
| 查询并发 | 同表 | 常量 8，单题 CLI 不启用 | 批量 benchmark 环节未实现 |
| 上下文压缩 | 同表及 C.1 Generation and episode parameters | 超过 96k prompt tokens 时，用运行摘要代替旧轮，保留最近 3 轮；摘要 prompt、旧消息序列化、8,192-token/1-round 摘要配置和 trace 字段均随 S3 runtime contract 冻结；仅压缩请求遇到瞬时 timeout 时最多尝试 3 次，退避 2/4 秒 | 形状对齐；具体摘要 prompt/表示方式和 timeout retry 是本地近似/可靠性措施，作者未公开；普通管理请求与文件工具不自动重试 |
| 文件视图 | 同表 | `view` 不截断文件，目录最多显示相对 3 层 | 对齐 |
| 工具删除 | Table 12 | 虚拟 `/memories` 中删除；本地保留可恢复副本，不向模型展示主机路径 | 模型可见行为近似；磁盘副作用不同 |
| API 适配 | Appendix A 开头、C.4 | 论文目标为 Chat Completions、高努力与输出上限；本地 S3 固定 NUS endpoint、`portable`、`stream=false`、有工具时 `tool_choice=auto`、300 秒 timeout、20 MB response cap；普通请求零自动重试，仅只读压缩请求有 timeout retry | `portable` 实际省略 reasoning、completion cap、temperature 和 seed；论文未提供原始请求 JSON 或版本锁定 |
| S3 runtime contract | 论文的 build/runtime 参数分散于 Appendix C.1/C.4 | `manifests/s3-management-runtime.json`、`fs_memory_lab/s3_runtime.py` | runner v4 contract 文件 SHA-256 `bd3f42…93eb5`；canonical runtime config SHA-256 `612fa8…7005`；同时记录论文目标与 NUS 实际配置，不把本地 operationalization 冒充原文 |
| S3 安全执行与发布 | 论文说明逐 chunk build episode，但未公开事务 runner | `fs_memory_lab/s3_runner.py` 与 `s3-preflight/build-s3/verify-s3` | 本地新增：输入/contract freeze、空 staging、85 个新上下文串行 episodes、跨块持久 filesystem、checkpoint、增量 trace、资源 gate、失败 quarantine/rollback、marker-last 发布和离线复核；v2 另加 post-tool locator 错误反馈供同一 Agent 修复，严格终态 gate 不变。这些都不是作者代码 |

## 为什么还不能说“完全复现”

1. Management Prompt 1/2 已可从作者官方 arXiv TeX 的 promptbox 精确提取；但论文仍没有发布 per-chunk user turn 的精确措辞、完整函数工具 JSON 包装和上下文摘要器 prompt。Prompt 1 与 Prompt 2 之间使用一个换行连接，也是本项目单独冻结的组合边界。
2. 本项目已固定 LoCoMo10、`conv-50` canonical records、正式 S1/S2 stores、85 个确定性 S3 管理输入 chunks、prompt/tool/runtime contracts，并完成 S3 safe runner 的离线 85-episode fake-provider 验证及 NUS API smoke。正式运行已验证并保留前 65 个 chunks；chunk 66 在本地近似的 context-compaction 请求上发生 timeout，未发布 S3 store。runner v4 对该只读请求增加有限重试，并支持从 `chunk-066-before` 继续。统一检索/回答/评测 runner、八题并发和 judge 也尚未完成，因此仍不能复现论文表格分数。
3. 正式 S2 已用一次 NUS API episode 构建：requested alias 为 `coding`、served model 为 `qwen3.8:27b`，12 次模型调用完成 32 次 `view` 与 30 次 `rename`，随后通过离线完整性验证。该运行不是论文所用 backbone。
4. NUS 当前实际 served model 不是论文的 `gpt-5.4-mini`；即便兼容函数调用，模型和提供商缓存/采样行为仍与论文不同。

## S3 runner 自动验证的边界

- `s3-preflight` 和 `verify-s3` 都不调用 API；正式 `build-s3` 只接受 clean 的 40 位 Git commit、受审 `CompatibleChatProvider` 与冻结 NUS profile。test artifacts 使用独立 ID 和 `test-*` revision，不能混入正式路径。
- Runner 的 trace verifier 会交叉验证 85 个 episode 输入、provider metadata、工具事件、usage、文件 before/after inventories、连续 hash chain、最终 store、manifest 与 COMMITTED marker；但它不重新 replay 全部工具调用，所以这不是“某个调用因果地产生某个差异”的形式证明。
- Store gate 能拒绝伪造/未来 locator，验证 file/section cross-reference，并要求列表或表格中的事实候选带行内 locator；自然语言段落的语义事实边界和 citation completeness 无法由正则完全判定，正式 store 仍需抽样人工审计。
- “gold 未暴露”的精确含义是 QA、answer、category、gold evidence 没有挂载到 Management Agent 的 messages 或 tools；不是声称这些数据在仓库磁盘上不存在。

当前可运行 `python3 -m fs_memory_lab.cli config` 和完全离线的 `python3 -m fs_memory_lab.cli s3-preflight`。隔离 NUS API smoke 已于 2026-10-06 通过；下一阶段是在 runner v3 的 clean commit 上严格验证失败前缀，从 `chunk-010-before` 续跑 `resume-s3`，随后离线 `verify-s3`。不要把密钥贴到聊天、代码或 trace 里。
