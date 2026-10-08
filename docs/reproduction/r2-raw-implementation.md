# R2-Raw（E2/E4）本地实现说明

状态：**离线搭建完成；未调用学校 API；未生成正式检索成绩**
实现日期：2026-10-09（Asia/Shanghai）

## 1. 现在已经有什么

本地已具备一条完整但尚未真实调用 API 的 R2-Raw 运行链：

```text
冻结的 S1/S2 store
  -> 568 source turns 完整性校验
  -> 292 exchange units
  -> tokenizer + BM25
  -> session score + RRF
  -> Top-5 + 同 session ±2 exchanges
  -> 最多 4 个动作的 Retrieval Agent
  -> take_note 选择完整结果块
  -> host 重读原文、合并重叠、执行证据预算
  -> EvidenceBundle
  -> trace + hash chain + 原子发布
```

本阶段只覆盖 E2（S1 + R2-Raw）和 E4（S2 + R2-Raw）。E6/S3 的 R2-Curated 不在本实现范围内。

## 2. 代码在哪里

| 文件 | 作用 |
| --- | --- |
| `fs_memory_lab/r2_protocol.py` | 冻结 R2 参数、来源分类和协议 hash |
| `fs_memory_lab/r2_prompts.py` | 论文 Prompt 转录、本地补充 Prompt 和 hashes |
| `docs/reproduction/r2-prompt-manifest.json` | Prompt 来源、分类和机器可读 hashes |
| `fs_memory_lab/r2_inputs.py` | 验证 S1/S2，并构造 292 个 exchanges |
| `fs_memory_lab/vendor/refind_tokenizer.py` | 作者固定 commit 的 tokenizer 原文件 |
| `fs_memory_lab/r2_tokenizer.py` | tokenizer 版本和逐字节 hash gate |
| `fs_memory_lab/r2_index.py` | BM25、session aggregate、RRF、日期、seen-session、±2 |
| `fs_memory_lab/r2_tools.py` | 三动作严格解析与 observation 格式化 |
| `fs_memory_lab/r2_agent.py` | 最多 4 动作的文本 ReAct 状态机 |
| `fs_memory_lab/r2_artifacts.py` | 原文重读、重叠合并、EvidenceBundle、失败产物与验证 |
| `fs_memory_lab/r2_runner.py` | 单题与确定性顺序批量运行 |
| `fs_memory_lab/r2_cli.py` | config、preflight、run-one、run-batch、verify 命令 |
| `tests/test_r2_*.py` | 全部 R2 离线测试 |

## 3. 已冻结的关键身份

| 项目 | SHA-256 |
| --- | --- |
| R2 方法协议 | `b338aafc73f4f4fd674ad5433e624b1a4e2f44e3422e06b9f5bb1dfa7d1dacb2` |
| 论文 Stage-1 + temporal Prompt 组合 | `20422063cc471ee1de75c38e4250e1a141a731ea2970786a6c715dc3c83cf7de` |
| 本地 derived system Prompt | `6930d93099ac20b76e881b68cbb63b46e1a0a3e2ff43453db685551c3339a6dc` |
| 三动作合同 | `3fa6b1160c2f7f9b2a8b3e232721d4ca78a161abb31af0d4f1f2e307b7354581` |
| 官方 tokenizer 源文件 | `111744fff0a766bb8248319f9d38294c9954d9d47b12c7be4c1dd8592609b9b6` |
| S1 exchange corpus | `f60302053fb2961f24db616352bc1dddb6c16ada4fa50b1b0be7e119706bac37` |
| S2 exchange corpus | `923d27922d10af72ba99137bf3f4d18a95d79a7c81fc31cec2ba261d55ce05dc` |

S1/S2 corpus hash 不同是因为 provenance path 不同；BM25 使用的 exchange 文本、日期、session 与 locator 则完全一致。

## 4. 不连接 API 时怎么检查

在仓库根目录执行：

```bash
python3 -m fs_memory_lab.r2_cli config
python3 -m fs_memory_lab.r2_cli preflight
python3 -m unittest discover -s tests -p 'test_r2*.py' -v
```

`preflight` 的固定结果应包含：`source_turns=568`、`sessions=30`、`singleton_exchanges=16`、`exchange_units=292`、`content_parity=true`、`path_difference_count=292`、`index_documents_per_store=292` 和 `first_search_ranking_parity=true`。最后两个字段证明预检确实为 S1/S2 构造了完整索引，并以固定的 `Japan` probe 验证首轮 backend 排名一致。以上命令都不会读取 API key，也不会发出网络请求。

当前验收结果：R2 专项 33/33；全仓标准库测试（排除需要外部 `pytest` 收集器的 R1 prompt 文件）245/245；R1 prompt 的 8 个参数展开 cases 另行等价执行并全部通过，总计 253/253。`compileall` 和 `git diff --check` 同样通过。

## 5. 后续真实运行入口（本阶段没有执行）

真实 smoke 应先从 dev-6 的一题开始，不能直接跑 main-40：

```bash
python3 -m fs_memory_lab.r2_cli run-one \
  --cell E2 \
  --question-set dev-6 \
  --position 1 \
  --run-id r2-smoke-e2-001 \
  --output-root '/Users/wangwenqi/Desktop/memory bench/local-runs/r2-raw' \
  --model coding \
  --budget-unit characters \
  --budget-limit 20000
```

这里的 `20000` 只是工程 smoke 示例，不是正式冻结预算。必须先在 dev-6 观察 evidence completeness 和成本，再在看 main-40 结果之前冻结 E1–E6 共用预算。

学校 API key 仍只通过 `FSMEM_API_KEY` 环境变量提供。runner 不显示、不保存、不清除 key。正式 CLI 强制 `FSMEM_API_STYLE=portable`；请求显式发送 `temperature=0`，但按既有学校适配器省略 `reasoning_effort` 和 `max_completion_tokens`。代码同时保留论文目标 high / 4096，并在 trace 与 runtime hash 中把“论文目标”和“实际 wire”分开绑定。若学校网关不支持 temperature 0，请求应失败并留下 failure artifact，不能静默删参后冒充同一配置。`FSMEM_MODEL` 若已设置，还必须与 `--model` 一致，避免产物记录的 requested alias 与真实请求不一致。

## 6. 一题运行后会保存什么

成功目录：

```text
<output-root>/<run-id>/<E2-or-E4>/<question-id>/
├── trace.jsonl
├── bundle.json
├── episode.json
└── COMPLETED
```

失败目录以 `.failed-<id>` 结尾，包含 `trace.jsonl`、`failure.json`、`episode.json` 和 `FAILED`。

`bundle.json` 才是交给统一 Answerer 的证据输入；`trace.jsonl` 第一条 `runtime_start` 记录 API style、论文目标配置与实际 wire profile，后续事件用于分析模型搜了什么、何时记 note、为什么停止。`episode.json` 和 marker 把 bundle/failure 与 trace 的 SHA-256 串起来，任何修改都会被 verifier 检出。

## 7. 论文原有与本项目补全

直接按 ReFind 论文/作者代码落实的部分包括：raw chat、exchange 配对、BM25 参数、stopwords 与 compact Porter stemmer、session aggregate、RRF、Top-5、±2、最多 4 个动作、时间过滤和三动作 evidence-only Retrieval Agent。

本项目补全的部分包括：LoCoMo singleton 规则、S1/S2 Markdown adapter、严格 `YYYY/MM/DD` 参数校验、过滤先于排名、canonical tie-break、S2 path 只显示不打分、`[SxTy]`/`dia_id` 回溯、完整响应后绝不重放 action、共享 EvidenceBundle、重叠区间合并、统一证据预算、失败产物、原子发布和离线 hash verifier。

## 8. 下一道门槛

1. E2/dev-6 单题真实 API smoke；
2. E4 同题 smoke，确认第一轮 deterministic backend 一致并观察路径是否改变后续 query；
3. dev-6 全部题的成本与 evidence completeness 检查；
4. 在不看 main-40 结果前冻结 evidence budget；
5. 才能启动 E2/E4 main-40。

因此当前准确表述是“R2-Raw harness 离线搭建完成”，不是“R2 实验已经跑完”。
