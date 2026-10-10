# 2026-10-10 `formal-v1` 冻结过程、问题与解决方案

## 1. 今天完成了什么

今天的目标不是运行 main-40，而是把已经通过 dev-6 pilot 的实验方案收口成一个
以后可以复验、解释和追责的正式版本。最终完成：

1. 完成 B=16000 的 E1–E6 dev-6 检索，36/36 通过；
2. 完成 E1–E7 dev-6 pilot，42/42 通过；
3. 复验 citation、store hash、served model、E2/E4 backend 排名、E7 无重新检索
   和成本口径；
4. 把 40 题顺序、S1/S2/S3、R1/R2/R3、Answerer、E7、预算、caps、模型、
   timeout/retry、并发和评分规则统一写入 content-addressed manifest；
5. 建立离线 verifier、Git 实现快照、冻结声明 commit 和 `formal-v1` tag；
6. 明确冻结后不得依据 main-40 分数调参，程序错误必须建立新版本重跑。

正式冻结说明见 `docs/reproduction/formal-v1-freeze.md`；机器权威文件见
`experiments/locomo-conv50-v1/formal-v1/manifest.json`。

## 2. 探索时间线

### 2.1 第一轮：B=6000 暴露预算不足

第一轮 dev-6 使用 6000-character evidence budget。36 条检索虽然全部完成，且没有
空证据，但 8/36 episode 因预算跳过至少一个候选，占 22.2%，超过预注册的 20%
工程门槛。因此没有因为“程序跑完了”就宣布成功，而是按规则完整重跑。

离线回放显示 8000 只勉强越过门槛，10000 在证据完整性与 Answerer 上下文成本之间
看起来更合理，所以把 B=10000 作为下一轮候选。这个决定只看 dev-6 工程指标，未看
main-40。

### 2.2 第二轮：B=10000 暴露空证据判定缺陷

B=10000 的 36 条检索完成后，E6/`conv-50-q129` 选中的关键 evidence item 长度为
15,242 characters，整项无法装入预算，最终 EvidenceBundle 为空。但 controller 已经
先到 R3 四动作上限，`stop_reason` 保留为 `round_limit`。

旧预算 gate 只在 `stop_reason == evidence_budget_reached` 时把空 bundle 判为失败，
因此错误地产生了 `freeze-candidate-10000`。这属于实质性工程 bug，而不是模型效果差。

解决方案：预算判定改为检查最终打包事实——只要 `empty_evidence == true` 且
`budget_skipped_items > 0`，无论 controller 的停止原因是什么，都必须判定整轮 dev-6
需要重跑。旧运行与旧审计均保留，不覆盖、不当作正式结果。

### 2.3 第三轮：B=16000 通过冻结门槛

离线回放表明 B=12000 仍装不下 15,242-character item，B=16000 才能消除当前 dev-6
trace 中的空 bundle，因此选择 16000 作为新的、也是最后的候选值，并完整重跑 36 条。

最终结果：36/36 完成、0 系统失败、0 空证据、3/36 存在预算候选跳过（8.33%），
低于 20% 门槛；requested model 始终是 `coding`，served model 始终是
`qwen3.8:27b`；所有 store hash 查询前后不变。因此正式冻结 B=16000 characters。

## 3. 今天遇到的主要问题与解决方案

| 问题 | 风险 | 解决方案 | 最终规则 |
| --- | --- | --- | --- |
| 学校网关偶尔返回 `null` 或空 content | R2/R3 被当作不可恢复 schema 崩溃，或偷偷增加动作 | 把空 content 变成一次明确的 `invalid_action` observation，仍消耗原四动作预算；失败恢复绑定具体 artifact | 不增加 action cap，不伪造 evidence，所有恢复可追溯 |
| `urllib` socket timeout 不能阻止“持续收到少量字节但整体不结束”的响应 | 单个请求可能挂住很久，整个批次不推进 | 在 macOS 主线程增加 300 秒 wall-clock deadline，同时保留 socket timeout | 单请求 300 秒；timeout 最多 3 次，2/4 秒退避 |
| B=10000 空 bundle 被 `round_limit` 掩盖 | 错误冻结预算，并让 Answerer在无证据下作答 | 预算 gate 改看最终 `empty + skipped`，不依赖 controller stop reason | 任意由预算造成的空 bundle 都阻止冻结 |
| 原 audit 要求 E2/E4 controller 关键词逐字相同 | 把 LLM 查询措辞随机性误当成 S1/S2 backend 不一致 | 固定同一个 query 分别送入 S1/S2 backend 比较 Top-5；关键词逐字一致只作诊断 | 正式验收 backend ranking invariant，不要求两次 LLM 文本相同 |
| E5 token 明显高于其他条件 | 容易通过给 E5 特殊预算“优化”而破坏公平 | 保留论文式 R1，不给 E5 单独 evidence budget；仅保留 100 万 token 安全熔断并完整报告成本 | E1–E6 共用 B=16000；E5 高成本作为 empirical finding |
| 模型别名与实际模型不是同一个字符串 | 只记录 `coding` 无法证明实际部署一致 | 同时记录 requested alias 和每次 API 返回的 served model | `coding → qwen3.8:27b`；任一次 served model 漂移即失败 |
| 论文配置写 batch concurrency 8，但本地学校网关和现有 runner 是串行 | 并发会引入限流、顺序和恢复差异，且未被 pilot 验证 | 冻结实际通过 pilot 的执行方式 | formal-v1 concurrency=1 |
| 可选 LLM judge 尚未在 pilot 中运行 | 临时加入会新增 prompt、模型成本和不稳定 API 环节 | 正式主指标采用官方 LoCoMo F1；judge 在 v1 明确关闭 | 若以后加入 judge，必须建新版本 |
| 单靠说明文档容易发生配置漂移 | 人能读懂但程序无法判断是否被改过 | 生成包含所有 hash 和规则的 manifest，并实现离线 verifier | 任一 store、题目、prompt、代码或规则漂移都 fail closed |
| Git commit SHA 无法安全写入同一个将被提交的 manifest | 会产生自引用：写入 SHA 后文件变化，commit SHA 又变化 | 使用两个 commit：实现快照 + 冻结声明；tag 指向冻结声明 | manifest 绑定实现 commit，`formal-v1` tag 绑定完整声明 |

## 4. Stage 4 pilot 中进一步确认的事情

B=16000 的 42 条 pilot 结果全部发布后，结构 audit 确认：

- citations 全部指向真实 evidence ID；
- S1/S2/S3 查询前后 tree hash 一致；
- E2/E4 在相同 query 下的 backend Top-5 invariant 12/12 通过；
- E7 六题均直接复用 E2+E6 EvidenceBundle，`search_calls=0`；
- E7 成本只计两路 retrieval 各一次和自身 Answerer，不重复计两路 Answerer；
- retrieval token 最大值 527,367，低于 1,000,000 安全熔断；
- system failure rate 为 0%。

pilot 的六题 F1 只能证明工程链路可运行，不能当作研究结论，因为样本很小且不含
category 3。category 3 的七题继续密封在 main-40，没有为了调参提前查看。

## 5. 正式冻结时做出的取舍

### 5.1 为什么是 characters 而不是 tokens

当前三个 retrieval runner 的 EvidenceBundle 已统一按 characters 计量。继续使用
characters 可以避免不同 tokenizer 和学校网关 served model 对 token 估算的影响。
模型返回的 token usage 仍完整记录，用于成本分析，但不参与 evidence 截断。

### 5.2 为什么正式并发是 1

论文中的 batch concurrency 8 是论文运行配置；本项目在学校 API 上通过验证的是串行
runner。正式版本优先冻结已经经过 36+42 条真实 API 验证的行为，避免在 main-40 前
突然引入限流和调度变量。

### 5.3 为什么关闭匿名 judge

官方 LoCoMo F1 是确定性、可复现的主指标，且已经由本地测试和 pilot 验证。匿名 judge
虽可作为补充，但没有进入本轮 pilot；临时加入会扩大正式实验协议。formal-v1 因此关闭
judge，将其留给明确的新版本或独立补充分析。

## 6. formal-v1 的 Git 与机器身份

- 实现 commit：`e2633826614fad8fdece74bc66150127f3a33082`；
- 冻结声明 commit：`a4094a73e2ac7341910e474bb1df009e434f43d7`；
- tag：`formal-v1`；
- manifest ID：`formal-337ebb2061b34493a2e81cad19453eb85481d82a646ce4c40a750e2222d08925`。

两个 commit 的原因不是重复提交，而是避免 commit SHA 的自引用。第一个固定可运行
实现，第二个提交引用第一个的 manifest、冻结说明和 tag。

## 7. 后续必须遵守的规则

1. 不因 main-40 分数不好调整 prompt、B、检索参数、cap、题目顺序、模型或评分；
2. 不把失败 episode 删除或覆盖，只允许从已验证 checkpoint 续跑；
3. 只有 280 条 RunRecord 全部完成并通过 hash 验证后才能加载 gold；
4. 如果发现实质性程序错误，建立新的 formal 版本，列明受影响条件并全部重跑；
5. 不在同一正式结果中混用两个 formal 版本；
6. 纯文档勘误不得改变 manifest 所表达的实验含义。

## 8. 当前边界与下一步

当前完成的是“正式方案冻结”，不是“正式实验完成”。main-40 尚未运行，也没有正式
结果可供比较。下一步应先让 Stage 5 runner 强制加载并验证 formal-v1 manifest，生成
新的、与 manifest ID 绑定的 main-40 run plan；确认 dry-run 和离线检查通过后，才开始
真实 API 批量运行。
