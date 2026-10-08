# Documentation Index

项目文档按用途分开存放，避免研究记录和可运行代码混在一起。

## Plans

- [一个月实验地图](plans/one-month-experiment-map.md)：七个实验条件、数据预处理、检索、评测、错误归因、逐日安排和完成标准。

## Progress

- [2026-09-16 研究进度](progress/2026-09-16-research-log.md)：本地 harness、Alice 两批增量写入、ReFind 学习和组合思路。
- [2026-09-22 仓库整理与 GitHub 备份](progress/2026-09-22-repository-setup.md)：本次目录重组、保留内容与安全规则。
- [2026-10-05/06 LoCoMo 与 S1–S3 准备](progress/2026-10-05-locomo-data-preparation.md)：官方数据、canonical records、S1/S2、85-chunk S3 stream、Management prompt、七工具/runtime contract、smoke、第一次安全失败及 runner v2 修复；正式 S3 store 尚未发布。

## Data

- [LoCoMo 数据说明](../data/README.md)：官方来源、许可、统一 turn schema、生成命令和 source map 用法。

## Paper notes

- [Filesystem memory 初学者阅读指南](paper-notes/filesystem-memory-guide.md)。

## Reproduction records

- [Filesystem 论文配置对齐记录](reproduction/filesystem-paper-parity.md)：公开 prompt、工具 schema、论文目标配置、NUS portable 实际配置、S3 safe runner 与仍未对齐部分的逐项边界。
- [R2-Raw（S1/S2）正式检索协议](reproduction/r2-raw-protocol.md)：exchange-level 输入、BM25/session RRF、Top-5、±2、seen-session、三动作、EvidenceBundle、论文/作者代码/本项目补全的来源边界和实现验收门槛。
- [R2-Raw 本地实现说明](reproduction/r2-raw-implementation.md)：已完成模块、冻结 hashes、离线检查命令、未来真实 smoke 入口、产物结构和当前边界。

## Source papers

本地论文文件、题名、公开入口与 SHA-256 见 [papers/README.md](../papers/README.md)。
