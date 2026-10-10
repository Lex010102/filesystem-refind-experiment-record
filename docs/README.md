# Documentation Index

项目文档按用途分开存放，避免研究记录和可运行代码混在一起。

## Plans

- [一个月实验地图](plans/one-month-experiment-map.md)：七个实验条件、数据预处理、检索、评测、错误归因、逐日安排和完成标准。
- [`formal-v1` main-40 正式跑批指南](plans/formal-v1-main40-batch-guide.md)：Stage 5A/5B、280 条正式运行、检查点/恢复、pre-gold 审计、评分和结果分析的完整操作地图。

## Progress

- [2026-09-16 研究进度](progress/2026-09-16-research-log.md)：本地 harness、Alice 两批增量写入、ReFind 学习和组合思路。
- [2026-09-22 仓库整理与 GitHub 备份](progress/2026-09-22-repository-setup.md)：本次目录重组、保留内容与安全规则。
- [2026-10-05/06 LoCoMo 与 S1–S3 准备](progress/2026-10-05-locomo-data-preparation.md)：官方数据、canonical records、S1/S2、85-chunk S3 stream、Management prompt、七工具/runtime contract、smoke、第一次安全失败及 runner v2 修复；正式 S3 store 尚未发布。
- [2026-10-09 阶段 1 共同基础设施](progress/2026-10-09-stage1-common-infrastructure.md)：共享 Answerer、E7 确定性融合、统一 RunRecord/续跑及自动评测器的完成与验证记录。
- [2026-10-10 阶段 2 E1 真实单题测试](progress/2026-10-10-stage2-e1-real-smoke.md)：E1 检索、共享 Answerer、RunRecord 与离线评测的真实端到端结果。
- [2026-10-10 阶段 3 dev-6 检索预算校准](progress/2026-10-10-stage3-dev6-retrieval.md)：从 B=6000/10000 的失败门槛到 B=16000 的 36/36 最终冻结依据。
- [2026-10-10 阶段 4 dev-6 × E1–E7 pilot](progress/2026-10-10-stage4-dev6-e1-e7-pilot.md)：B=16000 下 42/42 Answerer、E7、评分和结构审计全部通过。
- [2026-10-10 formal-v1 冻结过程](progress/2026-10-10-formal-v1-freeze-process.md)：记录 B=6000→10000→16000、空证据 gate、审计口径、超时、模型/并发/评分取舍、双 Git commit 及问题解决过程。
- [2026-10-10 Stage 5A/5B 正式跑批准备](progress/2026-10-10-stage5a-stage5b-formal-preparation.md)：正式 280 项调度层、运行身份、无 API dry-run 的 18 项检查、测试与恢复边界。

## Data

- [LoCoMo 数据说明](../data/README.md)：官方来源、许可、统一 turn schema、生成命令和 source map 用法。

## Paper notes

- [Filesystem memory 初学者阅读指南](paper-notes/filesystem-memory-guide.md)。

## Reproduction records

- [main-40 formal-v1 正式冻结说明](reproduction/formal-v1-freeze.md)：Git 实现快照、S1/S2/S3 与问题顺序、prompt、Answerer、E7、预算/cap、模型、retry、并发、评分和版本变更规则。
- [Filesystem 论文配置对齐记录](reproduction/filesystem-paper-parity.md)：公开 prompt、工具 schema、论文目标配置、NUS portable 实际配置、S3 safe runner 与仍未对齐部分的逐项边界。
- [R2-Raw（S1/S2）正式检索协议](reproduction/r2-raw-protocol.md)：exchange-level 输入、BM25/session RRF、Top-5、±2、seen-session、三动作、EvidenceBundle、论文/作者代码/本项目补全的来源边界和实现验收门槛。
- [R2-Raw 本地实现说明](reproduction/r2-raw-implementation.md)：已完成模块、冻结 hashes、离线检查命令、未来真实 smoke 入口、产物结构和当前边界。
- [R3 / R2-Curated 详细设计与溯源记录](reproduction/r3-curated-design-and-provenance.md)：E6 的 fact-bullet→H2-topic 适配、真实 S3 统计、BM25/RRF、multi-date、EvidenceBundle、公平比较、风险和验收标准。
- [R3 / R2-Curated 本地实现说明](reproduction/r3-curated-implementation.md)：已完成模块、冻结 hashes、离线检查命令、未来真实 smoke 入口、产物结构和当前边界。
- [E1–E7 共同实验基础设施](reproduction/common-experiment-infrastructure.md)：共享 Answerer、E7 双源融合、统一 RunRecord/续跑及官方 LoCoMo 自动评测器。

## Source papers

本地论文文件、题名、公开入口与 SHA-256 见 [papers/README.md](../papers/README.md)。
