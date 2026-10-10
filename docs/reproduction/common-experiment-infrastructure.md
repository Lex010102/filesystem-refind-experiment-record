# E1–E7 共同实验基础设施（阶段 1）

更新时间：2026-10-10

状态：四个环节均已完成；B=16000 的完整 dev-6 × E1–E7 pilot 已 42/42 通过并冻结为 `formal-v1`。尚未启动 main-40。

## 1. 为什么需要这一层

E1–E7 的存储和检索方式不同，但如果每个条件各自回答、保存结果或评分，差异就可能来自隐藏的实现变化。阶段 1 把四项共同机制冻结，使实验中的主要自变量只剩“存储 × 检索”。

| 环节 | 固定内容 | 主要文件 |
| --- | --- | --- |
| 1 | 所有条件共用同一 Answerer、prompt、JSON 输出和重试规则 | `fs_memory_lab/answerer.py` |
| 2 | E7 只融合 E2 与 E6 已取回的证据，不重新搜索或摘要 | `fs_memory_lab/fusion.py` |
| 3 | 统一 plan、RunRecord、失败记录、成本口径与安全续跑 | `fs_memory_lab/run_records.py` |
| 4 | 官方 LoCoMo F1、证据/引用/成本指标和可选匿名 judge | `fs_memory_lab/evaluation.py`、`fs_memory_lab/evaluation_cli.py` |

## 2. 共同 Answerer

Answerer 只能看到问题与 EvidenceBundle，不能看到条件名称、gold answer、gold evidence、检索 trace 或文件工具。七个条件共用：

- system prompt：`project-defined-shared-evidence-answerer-v1`；
- prompt SHA-256：`6ee299d5a5095aaaac19c0a7b61321af3b1c87e7f6aec818f47749097b87a572`；
- 无工具、temperature 0、最多一次格式修复；
- 严格输出 `answer`、`citations`、`insufficient_evidence` 三个字段；
- 引用只能使用输入 EvidenceBundle 中真实存在的 `evidence_id`；
- 原回答、模型名称、每次 usage、响应 ID 与修复次数进入 content-addressed AnswerResult。

格式修复只接收上一次的错误 JSON，不再次发送证据，避免一次格式错误造成额外证据暴露。该 prompt 是本项目为公平比较设计的，不是 Filesystem 或 ReFind 论文逐字 prompt。

## 3. E7 确定性双源融合

E7 输入固定为同一题、同一预算单位和同一单源预算 B 的 E2（S1/R2 raw）和 E6（S3/R3 curated）EvidenceBundle。融合规则：

1. 验证两个源 bundle 的 hash、问题、condition 和 store 完整性；
2. 源内顺序不变，按 `RAW → CURATED → RAW → CURATED` 交替；
3. 精确去重键为 `(source_kind, dia_ids, text_sha256)`；
4. 相同 locator 但文字不同的 raw/curated 证据均保留；
5. 不新增检索、不调用 LLM、不生成摘要；总 evidence 上限为 `2B`；
6. 复用的两路检索成本计入 E7，E2/E6 各自的 Answerer 成本不计入 E7；E7 只加自己的共享 Answerer 成本。

协议：`e7-deterministic-fusion-v1`；合同 hash：`035770f66df01bfdc937227a819ada720163fd6fa03416d88e5484ea54ae0abb`。

## 4. 统一运行记录与续跑

一次正式实验先冻结 ExperimentRunPlan，包括问题集、条件、执行顺序和所有配置 hash。E1–E6 对每道题轮换首发条件，减少时间/服务波动与固定条件顺序重合；E7 必须排在该题 E2、E6 之后。

每个成功单元写成不可覆盖、content-addressed RunRecord，包含：问题、EvidenceBundle、AnswerResult、retrieval/answer/deployment 成本和关联 hash。写入采用 staging + atomic replace + fsync，发布后立即重新读取验证。续跑只有在完整验证已有成功记录后才跳过；失败按 attempt 保留，仍属于 pending，不能伪装为成功。篡改、plan 漂移、question/condition 错配均 fail closed。

E7 的部署成本口径为：`复用的 E2+E6 retrieval + E7 自己的 answer`。不会重复计入 E2/E6 的 answer。

## 5. 自动评测器

### 5.1 官方规则

确定性答案分数严格复刻 LoCoMo 官方 `task_eval/evaluation.py`：

- 仓库：`https://github.com/snap-research/locomo`；
- 固定 commit：`cbfbc1dba6bc53d00625212a0f22d55ffee7c1fc`；
- 官方脚本 SHA-256：`8e3be5d57ff2ff9ec5cd05939592f468c5f3f1fd95d13e431932bdf6bf0fd6fd`；
- NLTK：3.8.1，默认 `PorterStemmer.NLTK_EXTENSIONS`；
- category 1 使用逗号拆分后的 multi-answer F1；category 3 在 gold 分号前截断；category 2/3/4 使用 stemmed token F1。

为了保持本项目零第三方运行依赖，`fs_memory_lab/vendor/locomo_porter.py` 是 NLTK 3.8.1 默认模式的最小兼容实现。它已针对 LoCoMo 全数据中的 13,178 个英文 token 与官方源码逐词比对，差异为 0；溯源见 `fs_memory_lab/vendor/README.md`。

### 5.2 同时输出的指标

- answer：每题 LoCoMo F1、每条件 micro F1、category F1、category macro F1；
- post-stratified F1：四类均存在时，按可靠池 `30/32/7/85` 加权；
- evidence：Evidence Recall、Any-hit、All-hit；官方无 gold evidence 的题不进入 evidence 指标分母；
- citation：引用数、有效引用数、citation validity、被引用 dia_ids；
- cost：RunRecord 中统一口径的模型调用与 token；
- optional judge：只接收 question、reference answer、candidate answer，不接收条件名；输出 correct/partial/incorrect。它是补充指标，官方 LoCoMo F1 仍是可复现的主指标。

Gold 只允许在检索与回答全部结束后的 evaluation module 加载，并必须显式给出固定 SHA-256。整批入口会先复验全部 RunRecord，任何 pending、gold hash 错误、问题集合错配都会拒绝评测。

## 6. 正式运行后的离线用法

main-40 的 gold hash 已冻结为 `a6833ca585ca26efcdd038a5cf202fd46657999053ebd7b8cc73793f7544718b`。当一轮 280 个 RunRecord 全部完成后，运行：

```bash
cd '/Users/wangwenqi/Desktop/memory bench'
python3 -m fs_memory_lab.evaluation_cli offline \
  --run-root '<正式 RunRecord 根目录>' \
  --run-id '<冻结 run-id>' \
  --gold 'experiments/locomo-conv50-v1/question-sets/main-40-gold.jsonl' \
  --gold-sha256 a6833ca585ca26efcdd038a5cf202fd46657999053ebd7b8cc73793f7544718b \
  --output '<新的 report.json 路径>'
```

命令不调用 API，且拒绝覆盖已有报告。dev-6 已完成并把正式预算冻结为
16,000 characters；main-40 必须遵守 `formal-v1` manifest，不得依据正式分数调参。

## 7. 验证范围

新增聚焦测试覆盖 Answerer 输入隔离/格式修复/引用验证、E7 去重/顺序/预算、RunRecord 原子发布/篡改检测/失败续跑，以及官方 F1/gold hash/整批完整性/evidence/citation/cost/匿名 judge。最终通过数量以阶段完成时的测试输出和 Git commit 为准。
