# 2026-10-14 formal-v2 main-60 扩展计划与题集记录

## 1. 师兄反馈与本轮决策

本轮讨论提出三项必须处理的问题：

1. 正式测试的 40 题规模偏小，最低扩展到 60 题；
2. 检索 Agent 与 Answerer 不能只使用一个 Qwen backbone，需要增加学校 API 的
   `x-test-2`；师兄说明其背后是 DeepSeek V4.1 Flash，但正式文稿只能在 API
   `served_model` 验证后写成已确认事实；
3. LLM-as-Judge 不应与被评系统使用同一模型，新的统一 Judge 改用 `x-test-1`；
   师兄说明其背后是 GLM 5.3 Flash，同样需要以真实 API 返回值为准。

这不是废弃原 40 题。正式口径固定为：

> `main-60-v2 = 原 main-40-v1（全量保留） + 新 extension-20-v2（追加）`。

原 main-40 的问题、顺序、文件、hash、280 条 Qwen 答案和官方 LoCoMo 分数均保留。
扩容决定发生在已经查看原 40 题结果之后，因此论文必须同时报告 `old-40`、
`new-20` 和 `combined-60`，并明确称为 append-only extension，不能包装成一个
事前全新抽取的 60 题集合。

## 2. 不可变边界

以下内容不因 formal-v2 改写：

- `formal-v1-main40` 的冻结 manifest、结果和评分归档；
- 原 `main-40-v1` 的 40 个 question IDs 及运行顺序；
- dev-6 的 6 道开发题；
- S1、S2、S3 store 内容与 snapshot hashes；
- E1–E7 的条件定义；
- R1/R2/R3 prompt、工具、BM25/RRF 参数和停止条件；
- evidence budget `B=16,000 characters`；
- R1 round caps：E1/E3 为 20，E5 为 40；
- R2/R3 action cap：4；
- E7 的 E2 + E6 确定性融合规则；
- 共享 EvidenceBundle 与 Answerer 输出 schema；
- timeout、retry、串行执行、引用验证、store 不变性和成本统计口径。

S2/S3 是先前由 Qwen 参与构建的固定记忆快照。本轮第二 backbone 只替换查询阶段的
检索 Agent 和 Answerer，因此研究的是**固定记忆上的下游 backbone 稳健性**，不是
“使用不同 backbone 重新构建记忆”的端到端比较。该边界必须写入报告限制。

## 3. 为什么 main-60 使用两层组合，而不是重写旧 40 题

原 280 条 RunRecord 绑定了 `locomo-conv50-main40-v1` 的 question-set identity。
如果把原 40 题复制进一个全新的在线 `main-60` 文件并修改 `question_set_id`，旧记录
将无法通过现有 evaluator 的身份验证。为合法复用旧结果，本轮采用两层组合：

| 全局位置 | 层 | 在线 question set | 用途 |
| ---: | --- | --- | --- |
| 1–40 | core | `locomo-conv50-main40-v1` | 原题与原 Qwen 结果保持有效 |
| 41–60 | extension | `locomo-conv50-extension20-v2` | 新增 20 题独立运行 |

`main-60-composition.json` 冻结全局 1–60 顺序以及每题所属的真实 source set，分析时再按
question ID 合并两层。不得修改旧记录的 `question_set_id`，也不得把旧运行伪装成新运行。

## 4. 新增 20 题的候选池与配额

候选池继续来自官方 LoCoMo `conv-50`：

| 筛选步骤 | 数量 |
| --- | ---: |
| 官方 QA | 204 |
| 排除 category 5 adversarial 后 | 158 |
| 排除四道 catalogued defective-gold 问题后 | 154 |
| 再排除 main-40 和 dev-6 后 | 108 |

108 道干净剩余题的类别为 C1/C2/C3/C4 = `18/20/0/70`。C3 之所以为 0，是因为
可靠池总共只有 7 道 open-domain，已经全部进入原 main-40。

项目在缩成 40 题之前的原始 60 题计划使用 `13/13/7/27`。因此 append-only 扩展采用：

| Category | 原 40 | 新增 20 | 合并 60 |
| --- | ---: | ---: | ---: |
| C1 Multi-hop | 10 | 3 | 13 |
| C2 Temporal | 10 | 3 | 13 |
| C3 Open-domain | 7 | 0 | 7 |
| C4 Single-hop | 13 | 14 | 27 |
| 合计 | 40 | 20 | 60 |

## 5. 抽样规则与防止结果导向选择

新增题使用 seed 42 的 SHA-256 排序。对每个类别 `c`，排序键为：

```text
SHA256("42|main60-v2-extension|category-{c}|{question_id}")
```

按类别取前 `3/3/0/14`，随后用下式固定 extension 内部运行顺序：

```text
SHA256("42|main60-v2-extension-run-order|{question_id}")
```

选择阶段只读取 `question_id` 与 `category`：

- 不读取 answer 文本；
- 不读取 evidence 文本；
- 不读取 caption、session 或 history-zone 元数据来筛选；
- 不读取任何 E1–E7 答案、分数、错误类型或成本；
- caption、session 和 zone 只在选定后统计并公开。

采用这一简单规则，是因为扩容决定发生在旧结果产生之后；此时不应再枚举多个候选并
挑选“看起来更好”的元数据组合。旧 40 题已经覆盖全部 30 sessions 和主要证据形态，
extension 的首要作用是按事前 60 题类别配额增加样本量。

## 6. 冻结的新增 20 题顺序

| Extension position | Global position | Question ID | Category |
| ---: | ---: | --- | --- |
| 1 | 41 | `conv-50-q147` | C4 |
| 2 | 42 | `conv-50-q126` | C4 |
| 3 | 43 | `conv-50-q075` | C4 |
| 4 | 44 | `conv-50-q144` | C4 |
| 5 | 45 | `conv-50-q019` | C1 |
| 6 | 46 | `conv-50-q114` | C4 |
| 7 | 47 | `conv-50-q121` | C4 |
| 8 | 48 | `conv-50-q044` | C2 |
| 9 | 49 | `conv-50-q057` | C1 |
| 10 | 50 | `conv-50-q058` | C2 |
| 11 | 51 | `conv-50-q111` | C4 |
| 12 | 52 | `conv-50-q078` | C4 |
| 13 | 53 | `conv-50-q074` | C4 |
| 14 | 54 | `conv-50-q082` | C4 |
| 15 | 55 | `conv-50-q104` | C4 |
| 16 | 56 | `conv-50-q089` | C4 |
| 17 | 57 | `conv-50-q012` | C1 |
| 18 | 58 | `conv-50-q132` | C4 |
| 19 | 59 | `conv-50-q028` | C2 |
| 20 | 60 | `conv-50-q118` | C4 |

这是生成器输出，不是人工挑题结果。

## 7. 选定后的覆盖统计

这些统计没有参与选择，仅用于描述样本：

- extension-20：5 道 caption-evidence、15 道 text-only、0 道 zero-gold-evidence；
- extension-20 的 gold evidence 覆盖 16 个 sessions；
- combined-60：25 道 caption-evidence、33 道 text-only、2 道 zero-gold-evidence；
- combined-60 的 gold evidence 仍覆盖全部 30/30 sessions；
- C1、C2、C4 在 combined-60 中均继续覆盖早期、中期和后期；
- 两道 zero-gold-evidence 均来自原 40 题中的 open-domain，仍只参加答案正确性评分，
  不进入 Evidence Recall 分母。

## 8. 两个 backbone 的正式矩阵

主实验先采用两个完整的查询阶段 backbone，不做四格角色交叉：

| Retrieval Agent | Answerer | 问题数 | 条件数 | 最终答案数 |
| --- | --- | ---: | ---: | ---: |
| Qwen `qwen3.8:27b` | 同一 Qwen | 60 | 7 | 420 |
| `x-test-2`（实际 served model 待验证） | 同一 `x-test-2` | 60 | 7 | 420 |
| 合计 |  |  |  | 840 |

Qwen 的原 40 题已有 280 条答案。通过兼容性审计后，只需补跑新增 20 题的
`20 × 7 = 140` 条；`x-test-2` 需运行完整 60 题的 `60 × 7 = 420` 条。因此计划
新增 560 条答案，而不是废弃旧结果后重跑全部 840 条。

只跑两条对角线意味着结果回答的是“整套查询阶段换 backbone 后结论是否稳定”，不能
严格分离 Retrieval Agent 和 Answerer 各自的因果贡献。如果以后需要拆分，可将
Qwen-retrieval/DeepSeek-answer 和 DeepSeek-retrieval/Qwen-answer 作为附加实验，
不在当前主实验中扩张。

## 9. 独立 Judge 口径

新的主语义 Judge 统一使用 `x-test-1`，并在 preflight 后冻结真实 served model。

- Judge 只看 question、reference answer、candidate answer；
- 不看 condition、store、retrieval method、answer backbone、trace 或成本；
- 所有 840 条候选答案都由同一个 Judge 协议评分；
- 输出继续为 `correct / partial / incorrect`；
- 主报告计算 Strict Accuracy、Partial Rate 和 Soft Semantic Score；
- LoCoMo 官方 token/stem Precision、Recall、F1 仍是确定性主指标；
- 旧 Qwen Judge 的 280 条结果不删除，只能作为历史或 Judge 敏感性分析，不能与
  新 `x-test-1` 标签混合成一张主表。

## 10. 分阶段 TODO 与验收门

### 阶段 A：main-60-v2 数据集（本轮已完成）

- [x] 保持 main-40 与 dev-6 原文件不变；
- [x] 构造 108 道干净 extension 候选池；
- [x] 按 `3/3/0/14` 确定性选择 20 题；
- [x] 生成 extension input/gold、main-60 composition、audit、manifest 和 verification；
- [x] 建立自动测试并验证重新生成逐字节一致；
- [x] 验证 combined-60 为 `13/13/7/27` 且覆盖 30/30 sessions。

验收结果：旧/新题集共 8 项单元测试全部通过。

### 阶段 B：模型能力与身份 preflight

- [ ] 只读确认学校 API 暴露 `x-test-2`、`x-test-1`；
- [ ] 对 `x-test-2` 验证 R1 function/tool calling；
- [ ] 验证 R2/R3 action JSON、停止动作和 usage；
- [ ] 验证共享 Answerer 严格 JSON；
- [ ] 对 `x-test-1` 验证 Judge 三分类 JSON；
- [ ] 记录两者的 requested alias、真实 `served_model`、可用参数及 context limit；
- [ ] 任一正式响应发生 served-model 漂移时 fail closed。

### 阶段 C：formal-v2 运行基础设施

- [ ] 新建 formal-v2 配置和 runner，不原地修改 formal-v1；
- [ ] 分开记录 retrieval model、answer model、judge model；
- [ ] 为 Qwen 与 `x-test-2` 建立独立正式 run，避免 RunKey 冲突；
- [ ] 增加 main-60 两层组合加载和按 question ID 汇总；
- [ ] 建立 main40→formal-v2 的逐条兼容审计；
- [ ] 测试 store hash、prompt hash、预算、cap、引用和 served model 门禁；
- [ ] E7 必须复用同一 backbone 的 E2/E6 bundle，不重新检索。

### 阶段 D：dev-6 pilot

- [ ] `x-test-2` 完成 dev-6 × E1–E7，即 42/42；
- [ ] `x-test-1` 对两 backbone 的 dev 输出做匿名 Judge pilot；
- [ ] 核对 schema、空证据、hit-cap、引用、模型漂移、token 和失败恢复；
- [ ] pilot 通过后冻结 formal-v2，不得因 main-60 分数调整 prompt 或参数。

### 阶段 E：formal-v2 冻结

- [ ] 冻结 Git commit；
- [ ] 冻结 core/extension/composition hashes 与60题顺序；
- [ ] 冻结 S1/S2/S3 hashes；
- [ ] 冻结 R1/R2/R3、Answerer、Judge prompt hashes；
- [ ] 冻结两个 backbone 的 alias 与实际 served model；
- [ ] 冻结预算、caps、E7规则、timeout、retry、并发、评分和复用规则。

### 阶段 F：正式答案跑批

- [ ] Qwen补跑 extension-20 × E1–E7，共140条；
- [ ] `x-test-2`运行 combined-60 × E1–E7，共420条；
- [ ] 每批完成后做结构审计、store hash验证和PASSED marker；
- [ ] 最终形成两个backbone各420条、合计840条答案；
- [ ] 旧280条若任何兼容项不一致，只重跑受影响部分，不能静默混用版本。

### 阶段 G：统一评分

- [ ] 对840条答案计算官方 LoCoMo Precision、Recall、F1；
- [ ] 使用 `x-test-1`匿名评价全部840条；
- [ ] 统计 Strict Accuracy、Partial Rate、Soft Semantic Score；
- [ ] 统计 Judge token、调用、重试、失败和成本；
- [ ] 对少量分层样本做人审校准，报告与Judge的一致性；
- [ ] 旧 Qwen Judge 结果只放附录敏感性分析。

### 阶段 H：结果分析与论文

- [ ] 每个backbone内部比较E1–E7；
- [ ] 同题同条件比较Qwen与`x-test-2`；
- [ ] 比较两backbone下方法排序是否稳定；
- [ ] 分category、存储、检索、错误阶段、cap、证据召回与成本分析；
- [ ] bootstrap按question重采样，不能把840条当作独立问题；
- [ ] 分别报告old-40、new-20、combined-60；
- [ ] 明确固定store由Qwen构建以及append-after-results的限制。

### 阶段 I：归档

- [ ] 保存每批status/audit/PASSED、final verify、评分和成本；
- [ ] 更新实验笔记、正式协议、README和GitHub；
- [ ] API key、私有checkpoint和本地敏感trace不得入库。

## 11. 当前题集产物与复现方式

产物目录：

```text
experiments/locomo-conv50-v1/question-sets-main60-v2/
├── README.md
├── extension-20-input.jsonl
├── extension-20-gold.jsonl
├── main-60-composition.json
├── main-60-audit.md
├── manifest.json
└── verification.json
```

生成器与测试：

```text
fs_memory_lab/question_sets_v2.py
tests/test_question_sets_v2.py
```

离线重新生成：

```bash
python3 -m fs_memory_lab.question_sets_v2
```

只读验证：

```bash
python3 -m fs_memory_lab.question_sets_v2 --verify-only
```

本轮没有调用任何学校 API，也没有运行新的检索、回答或 Judge。

## 12. 2026-10-14 至 2026-10-16：Qwen extension-20 正式运行

### 12.1 为什么单独补跑 20 题

新增 20 题的目的，是在不作废原 main-40 结果的前提下，把主测试集扩展到师兄建议的
至少 60 题。Qwen 旧 40 题的 280 条答案保持冻结；新增题使用独立 runner 运行
`20 题 × E1–E7 = 140 条`，最后再按 question ID 与旧 40 题组合。这样既保留历史结果，
也避免改写旧记录的 question-set identity。

### 12.2 如何运行

- 独立运行：`formal-v2-qwen-extension20-run-01`；
- 模型：requested alias=`coding`，served model=`qwen3.8:27b`；
- E1–E7、S1/S2/S3、prompt、BM25、Answerer、预算和 cap 均沿用冻结协议；
- `B=16,000 characters`；R1 caps=`20/20/40`；R2/R3 cap=`4`；
- timeout=`300s`、并发=`1`，按 35 条划为 4 个 batch；
- 凭据只从 macOS Keychain 注入运行进程，未写入项目文件；
- runner 支持 checkpoint、单实例锁和有限重试，已完成记录不会重复计入。

### 12.3 已核验结果

| 项目 | 结果 |
| --- | ---: |
| 总完成数 | 140/140 |
| E1–E7 | 各 20/20 |
| 完成问题数 | 20/20 |
| 完成 batch | 4/4 |
| pending | 0 |
| active failed keys | 0 |
| 历史失败尝试 | 11（均已恢复，保留审计） |
| 最终状态 | `completed` |

4 个 batch 的 audit 和 `PASSED` marker 均存在；只读 pre-gold verify 为 `passed`，并生成
`ANSWER-RUN-COMPLETED-NO-JUDGE`。核验覆盖记录数、每条件 20 条、served model、真实引用、
store 不变、检索 bundle 一致、E7 无隐藏重检索及成本一致性。按用户要求，本阶段**没有运行
token-F1、LLM-as-Judge 或其他评分**。

公开、去凭据结果归档位于：
`experiments/locomo-conv50-v1/results/formal-v2-qwen-extension20-run-01/`。

因此，截至本节记录时间，Qwen 在答案层面已经具备 `旧 280 + 新 140 = 420 条` main-60
结果；但旧 40 与新增 20 来自两个相互独立且兼容的 run，后续评分和汇总必须保留
`old-40 / new-20 / combined-60` 三个口径。

## 13. Model 2 的 preflight、独立 runner 与离线 dry-run

### 13.1 研究目的

Model 2 不是替换 Qwen，而是增加第二个检索与回答 backbone，用来回答：当存储快照、
检索协议、Answerer prompt 和题目完全不变时，E1–E7 的结论是否能跨 backbone 保持稳定。
唯一计划中的科学变量是 backbone：

| 系统 | requested alias | 实际 served model |
| --- | --- | --- |
| Model 1 | `coding` | `qwen3.8:27b` |
| Model 2 | `x-test-2` | `deepseek-v4.1-flash` |

### 13.2 preflight

正式运行前先做小规模 API preflight，确认：

- `/v1/models` 中存在 `x-test-2`；
- 实际响应的 `served_model` 为 `deepseek-v4.1-flash`；
- Retrieval Agent、Answerer、R1/R2/R3 所需 JSON/动作协议可解析；
- portable API profile、usage、finish reason、context limit 和超时行为可记录；
- requested alias 与 served model 任一漂移都 fail closed。

preflight 只用于协议兼容性验证，不计入正式答案或分数。

### 13.3 独立 Model 2 suite

Model 2 使用独立目录、manifest、checkpoint、审计和恢复脚本，不修改 Qwen 代码冻结版本或
结果。正式候选为 `formal-v2-model2-main60-candidate-02`，绑定实现 commit
`95986c3588f404526d7f0aa0235030643e430007`，并冻结：

- 60 题及顺序、420 个唯一执行 key、12 个 batch × 35；
- S1/S2/S3 store hashes；
- E1–E7、R1/R2/R3、BM25、Answerer prompt 与 temperature=0；
- `B=16000`、R1 caps=`20/20/40`、R2/R3 cap=`4`；
- E7 复用同 backbone 的 E2+E6 bundle，不重新检索；
- timeout=`300s`、response cap=`20 MB`、concurrency=`1`；
- 模型 alias=`x-test-2` 和 served model=`deepseek-v4.1-flash`。

离线 dry-run 不调用 API、不生成答案、不加载 semantic gold，也不运行 Judge；它已通过
420 个唯一 key、E1–E7 各 60 条、12×35 batch、题序、hash、预算、cap、E7 复用、模型身份
门禁和断点恢复等检查。

## 14. Model 2 dev-6 pilot：故障、修复与验收

### 14.1 为什么先跑 dev-6

正式 420 条成本较高，因此先运行 `6 题 × E1–E7 = 42 条答案`。其中需先完成 36 个独立
retrieval episodes；E7 直接复用 E2/E6，不增加第 7 组检索。pilot 只验证兼容性、恢复、
身份和审计，不用于调整科学协议。

### 14.2 run-01 的控制缺陷

旧 pilot `run-01` 在 16/36 retrieval 后中止。问题不是题目、prompt 或模型漂移，而是恢复
控制状态按整个 run 共享：某个 key 留下的恢复状态会让后续 key 的第一次失败被误判成
“已耗尽重试”。`run-01` 被明确标记为 aborted，只保留为故障证据；其输出没有复制、续跑
或计入新 pilot。

修复方式是把恢复状态改为**按 execution key 隔离**，并补充最小测试；没有修改题目、
store、prompt、工具、预算、cap、模型或评分口径。修复形成 commit
`95986c3588f404526d7f0aa0235030643e430007`，随后建立全新的 candidate-02 和 run-02，
避免混用故障前后的运行。

### 14.3 run-02 验收结果

| 项目 | 结果 |
| --- | ---: |
| Retrieval episodes | 36/36 |
| Answers | 42/42 |
| E1–E7 | 各 6/6 |
| Retrieval failure attempts | 1（已恢复并完整计费） |
| Answer failure attempts | 0 |
| Active failures | 0 |
| 模型身份漂移 | 0 |
| Final audit | `passed` |

`model2-final-audit.json` 与 `MODEL2-PILOT-42.PASSED` 已生成。最终审计确认 requested
alias、所有 served model、预算、caps、引用、store hashes、E2/E4 检索不变量、E7 无重新
检索、失败尝试成本、无空 bundle、gold 只在全部 42 条完成后进入审计，以及 Judge 未调用。

公开、去凭据 pilot 归档位于：
`experiments/locomo-conv50-v1/results/formal-v2-model2-dev6-pilot-run-02/`。

## 15. formal-v2-model2 冻结

pilot 通过后已建立版本级冻结说明和机器可读 manifest，并形成本地 Git commit
`1768257`（`Freeze formal-v2 Model 2 candidate-02`）。冻结文件包括：

```text
docs/reproduction/formal-v2-model2-freeze.md
experiments/locomo-conv50-v1/formal-v2-model2/README.md
experiments/locomo-conv50-v1/formal-v2-model2/manifest.json
```

冻结绑定 candidate-02 suite manifest/dry-run、双 preflight hashes、run-02 pipeline manifest、
final audit/PASSED hashes，以及实现 commit `95986c3...`。这表示 Model 2 已具备正式运行条件，
但**截至本节记录时间，正式 60 题 × 7 条件的 420 条尚未启动，Judge 也未启动**。

## 16. 双 backbone 对照的公平性边界

### 16.1 可以称为相同的部分

| 维度 | Model 1 与 Model 2 |
| --- | --- |
| 60 题与顺序 | 相同 |
| S1/S2/S3 内容与 hash | 相同 |
| E1–E7 条件 | 相同 |
| R1/R2/R3 实现、prompt、工具和 BM25 | 相同 |
| Answerer 实现、prompt、temperature | 相同 |
| Evidence budget 与 round/action cap | 相同 |
| E7 融合规则 | 相同，且都不重新检索 |
| API profile、timeout、并发 | 相同 |
| 有意改变的变量 | backbone/model deployment |

因此主实验可以描述为：**冻结算法与数据条件，只替换检索 Agent 和 Answerer 的
backbone**。这正是合理的双-backbone 稳健性对照。

### 16.2 必须披露的工程差异

Model 2 增加了逐响应模型身份检查、单实例锁、自动且有限的外层恢复，以及失败尝试成本
审计。Qwen 的旧 main-40 主要采用失败停止后从 checkpoint 外部续跑，extension-20 才使用
更完整的 batch 恢复。因此不能声称两个部署“逐字节完全相同”。这些差异不改变题目、
检索或回答算法，但会影响可靠性与总运行成本。

后续效率报告必须拆成两层：

1. **成功路径效率**：成功记录的 retrieval/answer token、调用、动作与时延，可用于公平的
   backbone 比较；
2. **运行恢复开销**：失败、重试和中断产生的额外 token/调用，单独报告为工程鲁棒性成本。

另外，portable API 对两个模型都不发送 `reasoning_effort` 和 `max_completion_tokens`；
请求结构保持一致，但各模型自身的默认推理行为和 tokenizer 差异属于 backbone/deployment
差异，应在论文限制中说明。

## 17. 后台运行与监控约定

为避免每 10 分钟的自动消息打断主对话，后续冒烟测试和正式跑批采用以下组织方式：

1. 真正的 runner 在纯后台运行，不占用前台终端窗口；
2. 监控放在独立 Codex 任务/窗口，不再把周期 heartbeat 插入本讨论线程；
3. 正常推进时保持安静，只在里程碑、失败、需要用户动作或全部完成时通知；
4. 监控只读 status/events/audit/PASSED 等文件，不能改变冻结协议；
5. 恢复前必须验证 run lock，确保只有一个 runner，且已完成 key 不重复执行；
6. API key 只通过 Keychain 注入进程，不显示、不写入项目、不读取终端历史。

这一决定只改变运行与通知方式，不改变实验条件。

## 18. 当前状态与下一步

### 18.1 已完成

- [x] main-60 两层题集、顺序、composition、manifest 与 verification；
- [x] Qwen extension-20 的 140/140 答案、4 个 batch audit 与 pre-gold verify；
- [x] Qwen main-60 在答案层面具备旧 280 + 新 140 共 420 条；
- [x] Model 2 `/v1/models` 与角色级 preflight；
- [x] Model 2 独立 candidate-02、420-key 离线 dry-run；
- [x] Model 2 dev-6 run-02：36/36 retrieval、42/42 answers、final audit passed；
- [x] formal-v2-model2 的版本级冻结；
- [x] 后台 runner＋独立任务监控的工作约定。

### 18.2 尚未完成

- [ ] 后台启动 Model 2 正式 main-60：420 条、12 个 batch；
- [ ] Model 2 完成后运行只读 pre-gold verification；
- [ ] 对 `x-test-1` 做 Judge preflight，并验证其真实 served model；
- [ ] 冻结独立 Judge 协议与匿名输入顺序；
- [ ] 对两个 backbone 共 840 条答案统一计算 LoCoMo P/R/F1；
- [ ] 使用独立 Judge 计算 Strict Accuracy、Partial Rate、Soft Semantic Score；
- [ ] 按 old-40/new-20/combined-60、类别、E1–E7、backbone、错误阶段和成本做配对分析；
- [ ] B3 Full Context 仍是候选 baseline，未并入本轮双-backbone正式主实验。

### 18.3 推荐执行顺序

1. 在后台按冻结 candidate-02 启动 Model 2 420 条正式运行，并在独立任务监控；
2. 12 个 batch 与 final/pre-gold audit 全部通过后，冻结 Model 2 正式答案；
3. preflight 并冻结 `x-test-1` Judge；
4. 对 840 条统一运行 deterministic LoCoMo P/R/F1，再运行匿名 LLM-as-Judge；
5. 先完成配对主效应与 backbone 稳健性分析，再决定是否补 Full Context 或其他 baseline。
