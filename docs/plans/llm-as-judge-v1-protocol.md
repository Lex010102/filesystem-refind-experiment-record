# LLM-as-Judge v1：E1–E7 补充语义评分协议

## 1. 定位

这是一项 **supplemental analysis（补充分析）**，不替换已经冻结的 LoCoMo
token F1 主评分，也不修改 formal-v1 的 280 条答案。输入固定为：同一道题、官方参考
答案、某个 E1–E7 候选答案；Judge 看不到条件编号、存储方式、检索方式、证据或 token
F1，因此是匿名评分。

## 2. 一个 Judge，一次输出三档

每条答案只由同一个 Judge 模型判断一次：

| 标签 | 含义 | Strict | Soft |
|---|---|---:|---:|
| `correct` | 语义完整正确，无实质矛盾 | 1 | 1.0 |
| `partial` | 至少一个必要事实正确，但有遗漏、实质不精确或混入矛盾 | 0 | 0.5 |
| `incorrect` | 没答到必要事实、整体错误、拒答或称无法确定 | 0 | 0.0 |

因此不是两个 LLM，也不是先打 partial 再二次归一化。一次三分类同时派生：

- `Strict Accuracy = correct / all`；
- `Partial Rate = partial / all`；
- `Soft Semantic Score = mean(correct=1, partial=0.5, incorrect=0)`。

## 3. 公平性与冻结项

- 顺序沿用 formal-v1 的 280 条执行顺序，仍分 8 批，每批 5 题 × 7 条件 = 35 条；
- requested model 固定为 `coding`，served model 必须始终为 `qwen3.8:27b`；
- 串行执行，并发为 1；temperature=0；
- prompt、模型、标签定义、映射、题目、参考答案、候选答案均以 hash 固定；
- 最多允许一次仅改变格式、不改变判断的 JSON repair；
- API 超时和可重试 HTTP 错误沿用已有的有限重试；
- 每条结果内容寻址、原子发布；恢复时只跳过重新验证成功的结果；
- 每批生成审计文件和 `PASSED` marker；全部完成后再生成汇总。

## 4. 输出位置

正式运行目录：

`local-runs/llm-judge-v1/llm-judge-v1-main40-run-01/`

- `manifest.json`：冻结协议、输入 hash、模型和 prompt；
- `records/E*/<question>.json`：每条 judgment；
- `failures/`：失败尝试，不覆盖历史；
- `status.json`、`events.jsonl`：断点和进度；
- `control/batch-XX-audit.json` 与 `.PASSED`：每批自查；
- `results.json`：280 条结果及 E1–E7 总分、category 分数；
- `verification.json`、`final-audit.json`：最终完整性审计。

## 5. 解读边界

LLM Judge 能接受同义改写，比 token F1 更接近“意思是否正确”，但它本身会有模型偏差。
报告中应把 token F1 保持为主指标，把 Strict、Partial Rate 与 Soft Semantic Score
作为补充指标，并重点分析二者不一致的样本。
