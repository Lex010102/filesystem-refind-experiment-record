# Filesystem × ReFind Experiment Record

这个仓库记录一个长期记忆实验项目：把 **LLM 自主管理的 filesystem memory** 与 **ReFind-style 多轮原始聊天检索**放在同一套受控实验里比较，并研究错误究竟来自写入、检索还是回答阶段。

GitHub：<https://github.com/Lex010102/filesystem-refind-experiment-record>

## 当前状态

- 已实现 Filesystem 论文中 Center / Agent-curated 的本地原型；
- 已通过文件工具、路径权限、函数调用和上下文压缩等离线测试；
- 已用 NUS SoC API 完成 Alice 合成案例的两批独立增量写入；
- 尚未完成正式 LoCoMo loader、S1/S2 builder、ReFind-style R2、统一 Answerer、批量评测与七条件实验；
- 当前最准确的说法是：**S3+R1 底层原型已跑通，正式 benchmark 平台仍在建设中。**

完整的一个月工作路线见 [实验地图](docs/plans/one-month-experiment-map.md)。历史进度见 [研究进度日志](docs/progress/2026-09-16-research-log.md)。

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
python3 -m unittest discover -s tests -v
```

`demo` 使用临时目录，不调用 API。

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
