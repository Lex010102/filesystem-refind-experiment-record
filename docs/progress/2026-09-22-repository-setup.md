# 2026-09-22：仓库整理与 GitHub 备份

## 目的

把原先散落在 `memory bench/` 与 `fs-memory-lab/` 中的源码、论文、研究记录、实验计划和 Alice 试跑结果整理为一个可持续维护的 GitHub 仓库。

## 新结构

- 可运行代码：仓库根的 `fs_memory_lab/`、`tests/`、`examples/` 和 `pyproject.toml`；
- 方案与记录：`docs/plans/`、`docs/progress/`、`docs/paper-notes/`、`docs/reproduction/`；
- 论文：`papers/primary/` 与 `papers/related/`；
- 有意保留的实验产物：`artifacts/alice-pilot/`；
- 临时渲染、缓存、运行时输出和密钥文件：由根 `.gitignore` 排除。

## 本次保留

- Center / Agent-curated harness 源码与测试；
- Alice 两批输入、最终 memory、两次成功 trace 与第二批前快照；
- Filesystem 学习指南与论文对齐表；
- 2026-09-16 研究日志；
- 一个月七条件实验地图；
- 两篇核心论文和四篇相关论文。

## 本次不提交

- `.DS_Store`、`__pycache__`、`.pyc`；
- `tmp/pdfs/plan-review/` 的 PDF 文本抽取和 PNG 渲染；
- 根运行时 `memories/`、`runs/` 与未来 `local-runs/`；
- 没有成功 trace 的空 Alice 失败目录；
- 任何 API key、`.env` 或私钥文件。

提交前进行了只输出命中文件名的凭据模式检查，没有发现真实 API key、GitHub token、私钥或 Bearer token。测试中原先长得像真实 key 的假字符串已改为明显的测试占位符。
