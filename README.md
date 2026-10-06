# Filesystem × ReFind Experiment Record

这个仓库记录一个长期记忆实验项目：把 **LLM 自主管理的 filesystem memory** 与 **ReFind-style 多轮原始聊天检索**放在同一套受控实验里比较，并研究错误究竟来自写入、检索还是回答阶段。

GitHub：<https://github.com/Lex010102/filesystem-refind-experiment-record>

## 当前状态

- 已实现 Filesystem 论文中 Center / Agent-curated 的本地原型；
- 已通过文件工具、路径权限、函数调用和上下文压缩等离线测试；
- 已用 NUS SoC API 完成 Alice 合成案例的两批独立增量写入；
- 已固定官方 `locomo10.json`，并为 `conv-50` 生成统一 canonical records、source map 和版本 manifest；
- 已将全部 568 条 canonical records 确定性地构建为 30 个 S1 平铺原始 session 文件，并加入无损、完整性、确定性和防篡改测试；
- 已用一次正式 NUS SoC API episode 构建并离线验证 S2 Foldered verbatim store：30 个 session 在零字节修改下被归入 4 个模型自定主题目录，完整 trace、manifest、path map 和 COMMITTED 标记均已固定；
- 已把同一批 568 条 records 确定性地固定为 85 个 S3 管理输入 chunks：按自然 session 重置、每块最多 8 个 source turns、chunk payload（含 session header 与分隔符）不超过 3,000 个 Unicode code points，并提供逐 turn 字符/字节反查索引和防篡改测试；
- 已从论文官方 arXiv v1 TeX 逐字节提取并冻结 S3 Builder Prompt 1 与 LoCoMo Prompt 2；作者未公开的 per-chunk user wrapper 被单独标为本地协议；
- 已冻结 S3 Management Agent 的七工具顺序/schema、上下文压缩协议、论文目标参数与 NUS 本地实际请求配置，并实现 `s3-preflight`、`build-s3`、`verify-s3` 安全执行链；
- S3 safe runner 已用隔离的 deterministic fake provider 完整走通 85 个连续 build episodes，覆盖恢复点、增量 trace、逐块 gate、失败隔离、发布回滚和离线复核；这不是一次真实 API 运行；
- 尚未完成 ReFind-style R2、统一 Answerer、批量评测与七条件实验；
- 当前最准确的说法是：**正式数据底座、S1/S2 stores、S3 输入流、prompt/tool/runtime contracts 与安全 runner v2 已固定；首个冻结 chunk 的 NUS smoke 已通过，第一次正式尝试在 chunk 2 因模型写出畸形 locator 被安全拒绝，尚未构建正式 S3 store。**

完整的一个月工作路线见 [实验地图](docs/plans/one-month-experiment-map.md)。历史进度见 [研究进度日志](docs/progress/2026-09-16-research-log.md)，最新数据与 S1/S2 准备状态见 [LoCoMo 数据准备记录](docs/progress/2026-10-05-locomo-data-preparation.md)。

## 计划中的七个条件

| 条件 | 存储 | 检索 |
| --- | --- | --- |
| E1 | 平铺原始 session | Center 文件检索 |
| E2 | 平铺原始 session | ReFind-style 检索 |
| E3 | 文件夹化原始 session | Center 文件检索 |
| E4 | 文件夹化原始 session | ReFind-style 检索 |
| E5 | Agent-curated filesystem | Center 文件检索 |
| E6 | Agent-curated filesystem | ReFind-inspired 检索 |
| E7 | E2 raw evidence + E6 curated evidence | 双源融合回答 |

## 仓库结构

```text
.
├── fs_memory_lab/                 # Python harness 与工具循环
├── tests/                         # 离线单元测试
├── examples/alice/                # Alice 两批合成输入
├── artifacts/alice-pilot/         # 已完成试跑的记忆、trace 与说明
├── data/                           # 固定的 LoCoMo 原文件、canonical records 与 manifests
├── experiments/locomo-conv50-v1/  # 正式实验 stores、独立 manifests 与说明
├── docs/
│   ├── plans/                     # 实验方案
│   ├── progress/                  # 按日期保存的研究进度
│   ├── paper-notes/               # 论文学习笔记
│   └── reproduction/              # 论文配置与本地实现对齐
├── papers/
│   ├── primary/                   # 两篇核心论文
│   └── related/                   # 相关工作
└── pyproject.toml
```

文档入口见 [docs/README.md](docs/README.md)，论文索引和校验值见 [papers/README.md](papers/README.md)。

## Harness 的简单理解

模型不直接操作电脑文件。它只能请求 `view`、`create`、`grep` 等函数工具；本地 harness 验证路径和参数、执行操作、再把结果返回给模型。

一次管理 episode：

```text
conversation chunk
  -> model requests a file tool
  -> harness validates and executes it
  -> observation returns to model
  -> repeat until the model finishes
```

管理 Agent 可使用 `view`、`grep`、`create`、`str_replace`、`insert`、`delete`、`rename`。当前 Search Agent 使用只读的 `view`、`grep`、`toc`、`section_read`。

## 本地快速检查

要求 Python 3.11 或更高版本。仓库当前没有第三方 Python 依赖。

```bash
python3 -m fs_memory_lab.cli demo
python3 -m fs_memory_lab.cli config
python3 -m fs_memory_lab.cli foldering-prompt
python3 -m fs_memory_lab.cli management-prompt
python3 -m fs_memory_lab.cli verify-s2
python3 -m fs_memory_lab.cli s3-preflight
python3 -m fs_memory_lab.locomo prepare
python3 -m fs_memory_lab.stores build-s1
python3 -m fs_memory_lab.s3_chunks
python3 -m unittest discover -s tests -v
```

`demo` 使用临时目录，不调用 API。

`s3-preflight` 也完全离线：它核对固定的 85-chunk stream、prompt/runtime contracts、七工具 hashes 和正式输出目标是否为空。`build-s3` 只接受 clean、40 位 Git commit 上的受审 `CompatibleChatProvider` 与冻结的 NUS profile。2026-10-06 的第一次正式尝试在 chunk 2 被严格 gate 安全拒绝，没有发布半成品；v2 增加写后 locator 校验反馈，允许同一 Agent 自行修正但不放宽最终 gate。下一次仍必须从空 store 和 chunk 1 开始。

LoCoMo 的官方来源、许可、固定 commit、schema 和校验值见 [数据说明](data/README.md)。S1/S2 stores 与 S3 管理输入流的格式、位置、生成命令和完整性保证见 [实验产物说明](experiments/locomo-conv50-v1/README.md)。

## 连接 API

只在自己的终端里设置密钥。不要把密钥写入源码、文档、截图、shell 脚本、trace 或 Git commit。

```bash
export FSMEM_API_KEY='YOUR_KEY'
export FSMEM_API_BASE_URL='YOUR_OPENAI_COMPATIBLE_BASE_URL'
export FSMEM_MODEL='YOUR_MODEL_ALIAS'
export FSMEM_API_STYLE='portable'

python3 -m fs_memory_lab.cli check-api
```

本项目的 API adapter 需要兼容非流式 Chat Completions function calling。模型别名与实际服务模型可能不同，正式实验必须记录每次返回的 `served_model`。

## 重新运行 Alice 小案例

建议使用被 `.gitignore` 排除的 `local-runs/`，避免修改已归档的历史 artifact：

```bash
python3 -m fs_memory_lab.cli \
  --project local-runs/alice \
  ingest \
  --input examples/alice/initial-dialogue.txt

python3 -m fs_memory_lab.cli \
  --project local-runs/alice \
  ingest \
  --input examples/alice/2026-05-16-update.txt

python3 -m fs_memory_lab.cli \
  --project local-runs/alice \
  show
```

已归档的成功结果见 [artifacts/alice-pilot/README.md](artifacts/alice-pilot/README.md)。它只是功能诊断，不是论文官方测试集，也不能证明长期记忆效果。

## 论文对齐边界

公开 prompt、工具 schema 和论文默认配置的对应关系见 [Filesystem 复现对齐记录](docs/reproduction/filesystem-paper-parity.md)。当前实现不是作者原始代码，也没有使用论文相同的模型服务，因此不能把本地通过测试等同于论文分数复现。

## 安全与版本管理

- `.env`、密钥文件、运行时 `memories/`、`runs/`、`local-runs/`、缓存和临时 PDF 渲染不会提交；
- 有意保存的、小型且已检查的结果放在 `artifacts/`；
- 每次正式实验应记录 dataset、store、prompt、config 和 code hash；
- 第三方论文 PDF 作为本项目研究资料归档；公开再分发前请自行确认相应许可。
