# B3 Full Context DeepSeek main-60 v3 identity re-pin

制定日期：2026-10-18

## 1. 原因

旧 v2 run 在固定 q079 长上下文 preflight 的第一次请求上正确 fail closed。请求 alias 仍为
`x-test-2`，但 NUS SoCLaaS 返回的精确 `served_model` 已从冻结值
`deepseek-v4.1-flash` 变为 `deepseek-v4.1-flash-1017`。旧 run 的
`MODEL-IDENTITY-DRIFT.json` 和失败记录必须原样保留，且不得恢复或改写。

## 2. v3 变更

本版本只重新冻结 Full Context 的精确 served-model 身份：

| 项目 | 固定值 |
| --- | --- |
| requested alias | `x-test-2` |
| required served model | `deepseek-v4.1-flash-1017` |
| 身份规则 | 每个初答及格式修复响应都必须精确匹配，否则 fail closed |
| dev run | `b3-full-context-v3-model2-1017-dev6-run-01` |
| formal run | `b3-full-context-v3-model2-1017-main60-run-01` |
| output root | `local-runs/b3-full-context-v3-model2-1017/` |

身份重冻结证据为：

```text
experiments/locomo-conv50-v1/baselines/b3-full-context-v3/identity-repin.json
```

旧 Model 2 freeze 仍用于绑定 alias、endpoint、wire profile、context limit、timeout、响应上限和
并发设置；其旧 role smoke 只作为历史基础证据，不再代表 v3 的当前 served-model 身份。

## 3. 未改变项

除精确 served-model 字符串和 run/protocol 身份外，v2 操作指南中的所有实验约束不变：

- 同一 main-60-v2 60 题及 12×5 顺序；
- 同一 dev-6 与 q079 最长上下文门禁；
- 每题完整 30-session S1，上下文不截断、不总结、不检索；
- 同一 SharedAnswerer、temperature 0、portable wire profile 和冻结重试规则；
- dev-6 6/6 verify 通过前，main-60 不得发送；
- 答题阶段不加载 gold、不评分、不运行 Judge、不运行 Qwen。

## 4. 执行顺序

1. 在新的本地实现 commit 上 prepare 并 dry-run 两个 v3 run；
2. 运行 q079 preflight；
3. preflight 通过后补齐 dev-6 6/6，并执行 verify；
4. dev gate 通过后运行 main-60 60/60，并执行 pre-gold verify；
5. 任一响应不是 `deepseek-v4.1-flash-1017`，立即停止且禁止恢复该 run。

旧 v2 run 的 35,939 tokens 作为独立失败成本保留，不并入 v3 成功记录成本，也不得丢弃。
