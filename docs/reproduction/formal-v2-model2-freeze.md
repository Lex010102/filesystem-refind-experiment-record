# Model 2 main-60 `formal-v2-model2` 冻结说明

冻结日期：2026-10-16
状态：**dev-6 pilot 已通过；candidate-02 已冻结；正式跑批仅可在本冻结提交后启动**

## 1. 冻结结论

本次冻结把 `formal-v2-model2-main60-candidate-02` 固定为 Model 2 的正式
main-60 套件。机器可读权威文件为：

- `experiments/locomo-conv50-v1/formal-v2-model2/manifest.json`
- freeze manifest ID：
  `formal-v2-model2-freeze-05bd1fbe832c471f20c5c855823d46c88e66601788391730f52ac04697fd79e8`
- 实现快照 Git commit：`95986c3588f404526d7f0aa0235030643e430007`
- suite manifest ID：
  `model2-suite-b6ea58a8b11937b8fc63e5c822d91dbd45df4721aa77fae02c98eaa1e7b2bde3`
- requested alias：`x-test-2`
- API 验证的 required served model：`deepseek-v4.1-flash`

manifest 通过 content hash 绑定 candidate-02 suite manifest、runner、CLI、
测试、题集 composition、三个 store、方法协议、部署协议与 pilot 审计。它不包含
API key、问题文本、检索证据、答案或 semantic gold。

## 2. Pilot 门禁

`formal-v2-model2-dev6-pilot-run-02` 已通过预注册 final audit：

- retrieval：36/36；
- answers：42/42；
- active failed keys：0；
- identity drift：无；
- empty EvidenceBundle：0；
- retrieval 系统失败尝试：1，失败率 2.70%，低于预注册 5% 上限；
- Answerer 系统失败尝试：0；
- final audit：`passed`；
- audit ID：
  `model2-pilot-audit-552fddad512bfba4e3cb24e68735b544ab4b38ee8ec00a16652aaa82d021aabf`。

这次失败尝试已由同配置、同协议的有界恢复处理，未修改题目、prompt、预算、cap、
模型、证据规则或回答协议，因此不构成需要重做 candidate 的程序错误。

## 3. 正式矩阵

| Child | 题目 | 条件 | 记录 | 正式批次 |
| --- | ---: | ---: | ---: | --- |
| main40 | 40 | 7 | 280 | B01–B08 |
| extension20 | 20 | 7 | 140 | B09–B12 |
| 合计 | 60 | 7 | 420 | 12 |

顺序固定为：main40 的 8 个 local block 全部完成并逐批审计，随后运行 extension20
的 4 个 local block；extension child 仍接收 local block 1–4，不能把 9–12 传给
child runner。最后执行 combined pre-gold verify，达到 420/420 后停止，不启动 Judge。

## 4. 冻结的实验边界

- 同一 main-40、extension-20、main-60 composition 与全局 1–60 顺序；
- 同一 S1、S2、S3 内容树和 manifest hashes；
- 同一 E1–E7 定义；
- evidence budget `B=16,000 characters`；E7 每路 B、总计最多 2B；
- R1 round cap：E1/E3 为 20，E5 为 40；
- R2/R3 action cap：4；
- 同一 R1/R2/R3 prompt、工具、搜索参数和停止条件；
- 同一 Answerer prompt 与 citation 验证；
- E7 只复用同一 run 的 E2/E6 EvidenceBundle，不重新检索；
- portable API profile，单请求 timeout 300 秒，并发 1；
- requested alias 必须为 `x-test-2`，每次响应的 served model 必须精确为
  `deepseek-v4.1-flash`，否则 fail closed；
- 回答阶段禁止读取 semantic gold，禁止 Judge 调用。

## 5. 续跑与失败控制

正式 runner 每次恢复都必须重新验证 suite、child plan、代码与输入 hashes。只跳过
已经通过内容验证的完成记录，只允许当前失败 key 按冻结白名单恢复。身份漂移、
hash/plan/order 漂移、citation/E7 provenance/成本验证失败或需要修改科学参数的错误
一律停止。

如果发现实质性程序错误，必须保留本版本，建立新的 candidate/formal 版本，并重跑
全部受影响条件；不得把不同版本的记录混入同一结果。

## 6. 正式完成条件

正式跑批只有同时满足下列条件才算完成：

- main40 280/280，B01–B08 audit 与 PASSED marker 全部通过；
- extension20 140/140，B09–B12 audit 与 PASSED marker 全部通过；
- suite 420/420，E1–E7 各 60 条；
- active failed keys = 0，next key = null；
- 模型身份、citations、stores、retrieval/RunRecord 对应、E7 与成本规则全部通过；
- semantic gold 未加载，Judge calls = 0；
- combined pre-gold verify 通过并生成完成标记。

达到这些条件后停止，等待独立评分阶段；本冻结不授权启动 Judge。
