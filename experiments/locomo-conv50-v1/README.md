# LoCoMo `conv-50` 实验产物

本目录存放从固定 canonical records 派生的正式实验 stores 与输入 streams。它们都以 `data/processed/conv-50.jsonl` 为唯一语义来源；S1/S2 还使用 `data/manifests/source_map.json` 做来源一致性校验，S3 chunk generator 则刻意不读取其中由 QA evidence 派生的 alias 信息。问题、标准答案、题目类别和 gold evidence 不参与 store/stream 构建。

## S1：平铺原始 session

```text
experiments/locomo-conv50-v1/
├── stores/s1-flat/
│   ├── session-01.md
│   ├── ...
│   └── session-30.md
└── manifests/s1-flat.json
```

- 30 个 LoCoMo 自然 session 对应 30 个平铺 Markdown 文件；
- 共覆盖 568 个 source turns，顺序不变；
- 每条发言保留原 speaker、原始 text、`[SxTy]` 和官方 `dia_id`；
- 125 条官方 `blip_caption` 作为固定文本代理保留；不写入或访问图片 URL；
- 不摘要、不改写、不按主题合并，也不调用 LLM；
- manifest 独立放在 store 外，避免检索器把校验信息当成记忆内容；
- 当前 store SHA-256 为 `5a58a8cca8616b91f3c231671271f6dbbedc669330b91e410980223ad2488ad8`。

Filesystem 论文明确了“一次自然 session 一个原文文件、S1 平铺、零模型构建成本”的语义规则，但没有公开原始 session 文件的逐字节模板。这里的 Markdown/frontmatter 和来源标签排版是本项目公开、确定性的实现，不应表述成作者发布的原始模板。

## 重新生成

在仓库根目录执行：

```bash
python3 -m fs_memory_lab.stores build-s1
```

第一次写入会报告 `write_status: created`；文件已存在且与确定性结果完全相同时会报告 `verified-existing`。如果已有文件被改动、遗漏或多出文件，构建器会停止，不会静默覆盖。

如需安装为命令行入口，也可以使用：

```bash
fs-stores build-s1
```

## 自动完整性测试

```bash
python3 -m unittest tests.test_stores -v
```

测试会逐条反查 568 条记录，验证 30 个文件、原顺序、原始换行、125 条 caption、locator/`dia_id` 唯一性、逐文件完整/正文 hash、总体 store hash、跨目录确定性、重复构建幂等性、输入不变、防篡改和 gold 字段隔离。完整测试套件可运行：

```bash
python3 -m unittest discover -s tests -v
```

## S2：Foldered verbatim sessions

独立 Foldering Agent 和本项目重建的 system prompt 已实现于 `fs_memory_lab/foldering_prompt.py`。模型只能看到 `view`、`grep` 和受限 `rename`；工具层强制每次操作只能改变一个 `.md` 文件的父目录，不能改变 basename 或字节。

可在仓库根目录离线查看将要发送给模型的完整 prompt；该命令不读取 API key，也不调用 API：

```bash
python3 -m fs_memory_lab.cli foldering-prompt
```

安全执行层已实现于 `fs_memory_lab/s2.py`。它会先核对冻结的 S1 manifest 和30个正式文件，再建立独立 staging；模型只操作 staging。成功 episode 必须通过文件数、basename 集、逐文件完整/正文 hash、根目录残留、目录 slug、空目录和路径敏感 layout hash 等全量 gate，随后才发布 store、path map、trace、manifest，并最后写入 `s2-foldered.COMMITTED`。API、模型或 gate 失败只会产生位于 `local-runs/` 的隔离诊断，不会生成可被下游接受的正式 S2。

正式 S2 已于 run `20261005T155659458241Z-9391e1f0` 一次构建成功，并由独立离线 verifier 重新计算全部正式产物。实际请求模型别名为 `coding`，NUS SoC 返回 `qwen3.8:27b`；因此这是论文方法在本地 backbone 上的复现，不能表述为论文同模型复现。

| 结果 | 正式值 |
| --- | --- |
| 文件与目录 | 30 个 session、4 个一级主题目录、根目录 0 个 `.md` |
| 主题目录 | `cars-and-auto-work` 11；`music-and-performance` 14；`photography` 2；`travel-and-outdoors` 3 |
| 内容 hash | `5a58a8cca8616b91f3c231671271f6dbbedc669330b91e410980223ad2488ad8`，与 S1 完全相同 |
| 布局 hash | `13060ab52750d7b9ca0ab5b667a6aac69fb38021190bbff7ebd7336150508d6a` |
| 模型调用 | 12 rounds；32 次 `view`；30 次 `rename`；合计 62 次工具调用 |
| Token | prompt 380,653；completion 15,096；total 395,749 |
| 运行代码 | Git commit `b05732e0886ea56d6813021e7e3c01b24c7d10a7` |

正式产物分别位于：

```text
stores/s2-foldered/                       # 供 E3/E4 共用的只读 store
manifests/s2-foldered.json               # 输入、配置、成本与完整性承诺
manifests/s2-foldered-path-map.json      # S1 path -> S2 path
traces/s2-foldering.json                 # 12 轮完整 agent trace
manifests/s2-foldered.COMMITTED          # 最后发布的有效性标记
```

当前 checkout 已经存在正式产物，不应再次运行 `build-s2`。在仓库根目录随时可以完全离线复核：

```bash
# 完全离线地重新计算 store、manifest、path map、trace 和 marker 的交叉一致性
python3 -m fs_memory_lab.cli verify-s2
```

`build-s2` 不提供覆盖模式。只要正式 store、manifest、path map、trace 或 COMMITTED 标记中任意一个已经存在，它就会在调用模型前停止。真实模型的 taxonomy 不保证多次相同；manifest 分别记录 requested model alias、API 返回的 served model、Prompt/code hash、轮数、工具调用和 token usage。当前 adapter 没有向提供商发送 seed，因此不能把本地 Python seed 42 宣称为真实 LLM 采样可重复性保证，也不能为了挑选更好看的 taxonomy 删除后重跑。

## S3：固定的 Management Agent 输入流

正式 S3 store 还没有调用模型构建；目前先完成了第一阶段：把同一份 `conv-50.jsonl` 确定性地序列化为以后逐块交给 Management Agent 的固定输入。

```text
experiments/locomo-conv50-v1/
├── streams/s3-management-v1/
│   ├── session_01_chunk_01.txt
│   ├── ...
│   └── session_30_chunk_03.txt
└── manifests/s3-management-stream.json
```

冻结规则如下：

- 一个 source turn 是一位 speaker 的一次 utterance，即一条 canonical JSONL record；不是“一来一回”；
- 每个自然 session 单独从 chunk 1 开始，不让一个 chunk 横跨两个日期/session；
- session 内按原顺序贪心装入完整 source turns，每块最多 8 条；加入下一条后若会超过 3,000 characters，就先封闭当前块；单条 turn 永不拆分或截断；
- characters 指 Python `len(str)` 的 Unicode code points，作用于 chunk 文件中未来会原样交给模型的全部文本，包括 `Session N · YYYY-MM-DD` header 和空行分隔符；文件没有额外终止换行；
- 每条 turn 仍使用 S1/S2 共用 renderer，保留 speaker、原 text、官方 `blip_caption`、`[SxTy]` 和 `dia_id`，不写入或访问 URL；
- 这些 `.txt` 位于 `streams/` 而非 `stores/`，避免未来检索器误把输入清单当成已经形成的记忆；
- generator 只读取无 QA/gold 的 canonical JSONL，并强制其 SHA-256 必须是固定的 `130a5a…f0394`；不读取 `locomo10.json`、问题、答案、evidence 或 `source_map.json`。

这里“共用 renderer”只指逐 turn block。S1 的文件头还含原始时分，S3 header 只含 Figure 1 风格的 ISO 日期；两者完整输入并非 byte-identical。`conv-50` 每个 session 的日期均不同，主实验的 temporal questions 也不依赖同日时分区分，因此当前题集没有可见时间答案被删去，但报告仍需披露这一序列化差异。

Filesystem 论文 Appendix C.1/Table 11 明确规定连续 dialogue turns、最多 8 turns、3,000-character cap 和每 chunk 一个 build episode。论文没有发布 byte-exact chunker，也没有用单独一句话写明 session boundary；本项目根据刊出 Prompt 8 中与实际 store 命名对齐的 `session_04_chunk_02.md` 示例路径、Figure 5 的 85-step LoCoMo 构建轨迹和本数据逐 session 计数固定“不跨 session”。Header 格式、Unicode 计数、分隔符和超长 turn 的 fail-closed 行为是本地公开的操作化规则。

固定结果：

| 项目 | 值 |
| --- | ---: |
| Natural sessions | 30 |
| Source turns | 568 |
| Chunks | 85 |
| 带 caption 的 turns | 125 |
| 每块 turns | 1–8 |
| 每块 characters | 121–2,387 |
| 全部 chunk payload characters | 110,949 |
| 全部 UTF-8 bytes | 111,056 |
| Stream SHA-256 | `f599b8d35f55ac08b68595f728aaa7a20f30e14a529c7dcb0f1631857b6594ec` |
| Manifest SHA-256 | `6323382879ddafdb21c1207bf22a3d11c277d323faabfa28d1ae3144e78025d5` |
| 构建成本 | 0 LLM calls / 0 tokens / 0 tool calls |

重新计算并核对已有产物：

```bash
python3 -m fs_memory_lab.s3_chunks
python3 -m unittest tests.test_s3_chunks -v
```

已有 stream 与 manifest 完全一致时命令返回 `verified-existing`；任何 chunk/manifest 被改动、丢失、多出文件、变成 symlink 或只剩半套产物时都会停止，且不会静默覆盖。Manifest 为每个 locator 保存 chunk、顺序及字符/UTF-8 byte offsets，因此测试能从 85 个文件逐字节取回 568 个 renderer blocks，证明没有漏、重、乱序或把内嵌换行误当成新 turn。

下一阶段才是：冻结 S3 Management Prompt 与固定 user wrapper，建立只能消费上述 manifest/hash 的安全 runner，做一次低成本 smoke test，然后从空 store 串行运行 85 个独立 build episodes。每个 episode 只延续 filesystem 状态，不延续前一个 episode 的聊天上下文；正式建库只运行一次，成功后冻结供 E5/E6 共用。
