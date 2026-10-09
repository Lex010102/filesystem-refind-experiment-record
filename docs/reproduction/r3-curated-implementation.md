# R3 / R2-Curated 本地实现说明

日期：2026-10-09
状态：**独立离线 harness 已完成；未调用 R3 真实 API；未产生 dev-6/main-40 的 E6 结果**

## 1. 这套代码是什么

R3 是本项目对 E6 的工程简称。报告中应称：

> R2-Curated: ReFind-inspired retrieval over agent-curated filesystem memory.

它不是 ReFind 论文提出的第三种算法。它把 ReFind 的 BM25、group 聚合、RRF、多轮关键词搜索、时间过滤、seen-group 和 note-taking 机制适配到已经由 Management Agent 整理好的 S3 Markdown 记忆。

完整链路为：

```text
正式只读 S3
  -> fact/H2 parser
  -> fact BM25 + H2 group sum + RRF
  -> Top-5 center facts + 同 H2 ±2 facts
  -> 四动作 evidence-only Retrieval Agent
  -> take_note 选择结果编号
  -> host 重读并验证 S3 原文与 locators
  -> 合并重叠范围 + 统一 evidence budget
  -> EvidenceBundle / FailureArtifact
```

本阶段没有 Answerer，也没有对问题给出最终答案。R3 只负责证据检索。

## 2. 模块地图

| 文件 | 作用 |
| --- | --- |
| `fs_memory_lab/r3_protocol.py` | 冻结 E6/S3 身份、390 facts、35 groups、BM25/RRF、Top-5、±2、四动作和运行限制 |
| `fs_memory_lab/r3_inputs.py` | 只读验证正式 S3；排除 frontmatter；解析 fact units、H2 groups、dates、locators 和稳定 ID |
| `fs_memory_lab/r3_index.py` | tokenizer、BM25、H2 分数求和、RRF、日期 set-overlap、seen-group、上下文扩展 |
| `fs_memory_lab/r3_prompts.py` | 冻结 ReFind published prompt transcription 和 R3 curated adapter addendum |
| `fs_memory_lab/r3_tools.py` | 严格解析三种文本动作，并格式化包含完整 provenance 的 Top-5 observation |
| `fs_memory_lab/r3_agent.py` | 最多四个 planner actions 的 evidence-only 状态机、retry、usage 和 trace |
| `fs_memory_lab/r3_artifacts.py` | EvidenceBundle、预算、窗口合并、失败产物、原子发布和 hash-chain verifier |
| `fs_memory_lab/r3_runner.py` | 单题与顺序批量运行，默认遇到失败停止，生成 batch summary |
| `fs_memory_lab/r3_cli.py` | config、preflight、run-one、run-batch、verify 命令入口 |
| `tests/test_r3_*.py` | 解析、排名、动作、Agent、artifact 和 runner 的离线回归 |

## 3. 冻结输入与关键 hashes

| 项目 | 值 |
| --- | --- |
| S3 manifest SHA-256 | `70fb5ad56ff11bb849ce60b193cd6db29be601e613ca3afb76aac336e3b36e00` |
| 共享 S3 snapshot tree SHA-256 | `983238fddc77a88ef4ae3d06b50bcfd25a429f497e89c6af4d9477cefca9cad2` |
| R3 protocol SHA-256 | `0535a229b856dd73be89f4b617dfb9c046e9bde178e9e6689f3ac062397b0878` |
| R3 parsed corpus SHA-256 | `9f968d7848b468e6519d428c40b24f30cb662bd0cc6b674e1c4deab4e263f086` |
| R3 action contract SHA-256 | `115512fb955e8c7fca557e4b995c5bfd8717ca72dfb184810b04343bc595cd08` |
| ReFind tokenizer source SHA-256 | `111744fff0a766bb8248319f9d38294c9954d9d47b12c7be4c1dd8592609b9b6` |

机器可读协议位于 `docs/reproduction/r3-protocol-manifest.json`。Prompt 各组成部分的 hashes 用 `config` 命令查看。

## 4. Parser 实际输出

离线 preflight 必须稳定得到：

- 2 个 Markdown 文件、304,640 bytes、472 行；
- 2 个人物 H1、35 个 H2 topic groups；
- 390 个 locator-bearing fact units，其中 3 个 nested facts；
- 正文 1,459 次 locator mentions、555 个 unique locators；
- canonical source 共 568 个 locators，因此明确缺失 13 个；
- frontmatter 中 6 次 locator mentions 全部排除；
- group 大小 1–53 facts；单 fact 长度 21–7,740 characters。

Stable ID 示例：

```text
group: calvin.md::h2-001
unit:  fact-f01-h001-u001
```

文件按相对路径排序；H2 和 facts 按文档顺序编号。同分排序、seen-group 和 ±2 都依赖这个 canonical order。

## 5. 检索与 Agent 口径

- BM25 文本：`entity_name + H2 heading + 去 locator 的完整 fact`；
- BM25：`k1=1.2, b=0.75`，全 390-unit corpus 的固定 IDF；
- group score：本轮合格且正分 facts 的 BM25 分数之和；
- `RRF = 1/(60 + unit_rank) + 1/(60 + group_rank)`；
- 固定 Top-5，每个中心 fact 在同一 H2 内扩展前后各 2 facts；
- 日期过滤在排名前进行；一个 fact 的任一 source date 落入闭区间即保留；
- 每次搜索返回过的 H2 groups 在本题后续搜索前排除；
- observation 中五个结果独立编号，不预先合并；进入 bundle 时才传递合并同路径重叠或紧邻 ranges；
- Agent 只允许 `search_chatrecord`、`take_note`、`finish_search`，最多四个 planner actions；
- 达到上限时不会自动保存最后 hits，也不会退回 direct BM25；
- 最终 evidence 由 host 重新读取冻结 S3，模型不能自己写证据文字。

## 6. 不联网的检查方法

在仓库根目录运行：

```bash
python3 -m fs_memory_lab.r3_cli config
python3 -m fs_memory_lab.r3_cli preflight
python3 -m unittest \
  tests.test_r3_protocol \
  tests.test_r3_inputs \
  tests.test_r3_index \
  tests.test_r3_tools \
  tests.test_r3_agent \
  tests.test_r3_artifacts \
  tests.test_r3_runner -v
```

`config` 和 `preflight` 不读取 API key、不创建实验结果、不发网络请求。

## 7. 以后真实 smoke 的命令

只有在学校 VPN 已连接、当前终端已经隐藏输入并 export 过 `FSMEM_API_KEY`，且以下变量与正式合同一致时才运行：

```bash
export FSMEM_API_BASE_URL='https://soclaas-api.comp.nus.edu.sg/v1'
export FSMEM_MODEL='coding'
export FSMEM_API_STYLE='portable'

python3 -m fs_memory_lab.r3_cli run-one \
  --question-set dev-6 \
  --position 1 \
  --run-id r3-dev6-smoke-01 \
  --output-root '/Users/wangwenqi/Desktop/memory bench/local-runs/r3-retrieval' \
  --model coding \
  --budget-unit characters \
  --budget-limit 20000
```

这只是未来入口。本次实现没有执行这条命令。正式 budget 数值应与 E1–E6 统一，并在查看 main-40 结果前冻结。

## 8. 单题产物怎么看

成功 episode：

```text
local-runs/r3-retrieval/<run-id>/E6/<question-id>/
├── trace.jsonl
├── bundle.json
├── episode.json
└── COMPLETED
```

失败 episode 的目录名含 `.failed-<hash>`，内部是 `failure.json` 和 `FAILED`，不会伪装成成功 bundle。批量运行还会在 run 根目录生成 `batch-summary.json`。

- `trace.jsonl`：模型调用、搜索关键词、返回 groups、take-note 和 retry；
- `bundle.json`：交给统一 Answerer 的最终证据、来源、rank、score、成本与 stop reason；
- `episode.json` / marker：hash chain；
- `verify`：重新核验 artifact 与正式只读 S3。

离线验证示例：

```bash
python3 -m fs_memory_lab.r3_cli verify --path '<episode-directory>'
```

## 9. 当前完成边界

已经完成：协议、parser、index、prompt/action、evidence-only Agent、EvidenceBundle、failure artifact、runner、CLI、fake-provider E2E 和离线 verifier。

尚未完成：学校 API smoke、dev-6、main-40、统一 Answerer、自动评分、E7 双源融合。当前只能说“R3 离线 harness 已搭好并通过测试”，不能说“E6 实验已经跑完”或“R3 效果优于 R1/R2”。
