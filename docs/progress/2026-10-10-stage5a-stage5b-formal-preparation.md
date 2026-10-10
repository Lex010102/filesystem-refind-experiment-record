# 2026-10-10 Stage 5A / 5B 正式跑批准备记录

状态：**Stage 5A 已实现并固定；Stage 5B 无 API dry-run 已通过；main-40 真实 API 跑批尚未启动。**

完整的后续操作地图见 `docs/plans/formal-v1-main40-batch-guide.md`。

## 1. 本阶段目标

本阶段不追求模型分数，而是把已经冻结的 `formal-v1` 变成一个可以安全执行、停止、
恢复和审计的正式 main-40 运行。具体分成：

- **Stage 5A**：实现正式调度与审计层，生成不可变的 280 项计划；
- **Stage 5B**：在完全不调用 API 的情况下，用真实 40 题和 S1/S2/S3 做全链路 dry-run。

本阶段没有运行任何正式问题，没有生成模型答案，也没有打开 gold 的语义记录。

## 2. Stage 5A 实现

新增：

| 文件 | 作用 |
| --- | --- |
| `fs_memory_lab/formal_batch.py` | 正式计划、检查点、串行执行、恢复、pre-gold audit 和最终评分编排 |
| `fs_memory_lab/formal_batch_cli.py` | `prepare/dry-run/status/run/verify/finalize` 六个入口 |
| `tests/test_formal_batch.py` | 使用真实 40 题与三套 store 的无 API 单元测试 |
| `docs/plans/formal-v1-main40-batch-guide.md` | 后续正式跑批的完整操作地图 |

调度层只调用被冻结的 R1/R2/R3、Shared Answerer、E7 fusion、RunRecord 和 evaluator，
没有复制或修改这些算法。CLI 不提供 model、B、cap、prompt 或搜索参数的 override。

正式调度器实现 commit：

```text
cfeca86cc723c81acd0077218e1cfc627399b98a
```

`prepare` 会拒绝未被 Git 跟踪或相对 HEAD 有改动的 `formal_batch.py`，并把 commit 与文件
SHA-256 一起写入正式运行 manifest。这样不能用一个未提交的临时代码版本开始正式跑批。

## 3. Stage 5A 正式运行身份

已创建的正式运行目录：

```text
/Users/wangwenqi/Desktop/memory bench/local-runs/formal-v1-main40/formal-v1-main40-run-01
```

固定身份：

| 项目 | 值 |
| --- | --- |
| run ID | `formal-v1-main40-run-01` |
| plan ID | `plan-4b2cec9a16bb51b32a615e1acea37aece9008ea35d753330259ddc0d65f9e6da` |
| formal run manifest ID | `formal-run-d50540d54dff9343e6fe33b6bbd2a1e002332dc3303fdaa4ac9221135c4c3a14` |
| upstream formal manifest ID | `formal-337ebb2061b34493a2e81cad19453eb85481d82a646ce4c40a750e2222d08925` |
| planned records | 280 |
| question blocks | 8 × 5 questions |

关键文件 SHA-256：

| 文件 | SHA-256 |
| --- | --- |
| `plan.json` | `5f57178dfcceccc662075fb090e759a1f2e558dadc55b0380e4b8e1989f1be03` |
| `formal-run-manifest.json` | `ffacca66476b2c69fb556ea65bb813ba6e3b6c729030e3c4030661f80a1ec964` |
| `dry-run.json` | `29be4b34ceb02d840b02ea76f5ad2bf48b956373cdf7b8d648acef5aa4130213` |

运行目录位于被 `.gitignore` 排除的 `local-runs/` 下。代码和说明进入 Git，正式运行结果
保留在本地运行目录，不把可能很大的 trace、结果或未来敏感运行信息直接提交仓库。

## 4. Stage 5B 实际结果

dry-run ID：

```text
dry-run-51b8f17c4a275c3172c64cc679fd500855784b6f9385906d671b0594a765a559
```

以下 18 项全部为 `true`：

1. `formal_manifest_verified`；
2. `run_plan_280_unique_keys`；
3. `question_order_exact`；
4. `execution_order_exact`；
5. `conditions_40_each`；
6. `e7_after_e2_e6_for_every_question`；
7. `stores_exact`；
8. `r2_s1_s2_same_exchange_count`；
9. `r2_sessions_30`；
10. `r2_s1_s2_content_parity`；
11. `r2_s1_s2_probe_ranking_parity`；
12. `r3_fact_units_390`；
13. `r3_groups_35`；
14. `empty_run_store`；
15. `api_provider_not_constructed`；
16. `semantic_gold_not_loaded`；
17. `no_runtime_method_overrides`；
18. `serial_concurrency`。

条件计数为 E1–E7 各 40。语料统计为：

- S1 R2 exchange：292；
- S2 R2 exchange：292；
- session：30；
- S1/S2 的 292 个 exchange 内容一致、文件路径均不同；
- S3 fact units：390；
- S3 groups：35。

三套正式 store tree SHA-256：

| Store | Tree SHA-256 |
| --- | --- |
| S1 | `ca39361e8e23f204a9fda55fc83e3ce7f411c7c8d582939aa63688c1923c7679` |
| S2 | `e9b96bcd4e036f4ea4599edb06e9c0527c929442b09efe05d09ea416b8a4469d` |
| S3 | `983238fddc77a88ef4ae3d06b50bcfd25a429f497e89c6af4d9477cefca9cad2` |

Stage 5B 结束后的状态：

```text
planned_records   280
completed_records 0
pending_records   280
failure_attempts  0
active_failed_keys 0
next_key          E1 / conv-50-q023
```

这证明“运行地图和所有输入已经对齐”，不代表模型已经答题，也不能把 dry-run 当作实验结果。

## 5. 保护与恢复设计

正式 runner 做了以下保护：

- 每次打开运行都重新验证 upstream `formal-v1`、计划、调度器 hash 和 stores；
- 同一 run 使用非阻塞文件锁，拒绝两个进程并发写入；
- 每条记录成功后原子发布，再重新读取验证；
- 第一条明确失败即停止，失败历史 append-only 保存；
- 恢复时只跳过已经过内容验证的完成记录；
- 检索成功而 Answerer 失败时，恢复会复用已验证的 retrieval artifact；
- E7 必须读取本次 run 同题的 E2、E6，不能重新检索；
- 只有 280/280 通过 pre-gold audit 后，`finalize` 才加载 gold；
- API 错误文本会移除 provider key 以及常见 `sk_` / `clsk_` 形式的密钥。

## 6. 测试与环境问题

本阶段针对性回归：17/17 通过，包括 formal manifest、RunRecord、pilot audit、Answerer
和新的 formal batch 测试。`python3 -m fs_memory_lab.formal_v1_cli --repo-root . verify`
也再次通过，说明 Stage 5 调度层没有改变冻结的正式核心。

尝试运行全仓 `unittest discover` 时，316 个已加载测试通过，但
`tests/test_r1_prompts.py` 因当前系统 Python 未安装 `pytest` 而无法导入；随后尝试使用
已有 Anaconda pytest，Anaconda 在导入自身 `rlcompleter` 时发生解释器 segmentation
fault。这个问题与 Stage 5 代码逻辑无关，因此没有临时安装依赖或更改正式环境，也没有
把全仓回归误写成“全部通过”。正式 Stage 5 相关测试和真实 dry-run 均已独立通过。

## 7. 当前边界和下一步

现在已经具备启动真实 main-40 的必要离线条件，但尚未执行 `run`。下一步应按独立指南：

1. 人工确认学校 VPN 与四个 `FSMEM_*` 环境变量；
2. 只查看布尔值，不打印 API key；
3. 确认 `status` 仍是 `0/280`；
4. 用同一 output root 和 run ID 执行 `run`；
5. 失败时保留记录并用相同命令显式恢复；
6. 280/280 后先 `verify`，最后才 `finalize`。

