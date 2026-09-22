# Alice Incremental-Memory Pilot

这是一个合成的小型诊断案例，用来验证 Management Agent 是否会在已经存在的文件上进行第二批增量更新。

## 输入

1. [`../../examples/alice/initial-dialogue.txt`](../../examples/alice/initial-dialogue.txt)：第一批 5 个带 `[SxTy]` locator 的 turn。
2. [`../../examples/alice/2026-05-16-update.txt`](../../examples/alice/2026-05-16-update.txt)：第二批 2 个 turn，澄清 Alice 当前不吃鱼和海鲜。

## 归档内容

- [`memories/`](memories/)：两批写入后的最终 Markdown 记忆；
- [`runs/20260915T160006217961Z/chunk-001.json`](runs/20260915T160006217961Z/chunk-001.json)：第一批写入 trace；
- [`runs/20260915T161030757261Z/chunk-001.json`](runs/20260915T161030757261Z/chunk-001.json)：第二批写入 trace；
- [`runs/20260915T161030757261Z/before-chunk-001/`](runs/20260915T161030757261Z/before-chunk-001/)：第二批写入前快照。

第一次曾有一个 API 端点/认证错误的失败尝试，没有产生成功 trace，因此没有把空运行目录作为 artifact 提交。

## 已观察到的行为

- 第一批输入创建饮食和东京行程文件；
- 第一版饮食文件仍把 seafood 写成当前偏好；
- 第二批是独立的再次 ingest；模型读取旧文件后，把 seafood/yakiniku 明确标成历史偏好，并保存新的当前状态及来源；
- trace 记录当时请求别名为 `coding`，实际 served model 为 `qwen3.8:27b`。

## 局限

Alice 是本项目自创的诊断案例，不是 Filesystem、ReFind 或 LoCoMo 官方测试。它只能说明这一次增量文件更新链路工作过，不能说明搜索答案已经验证，也不能说明长期记忆系统具有稳定效果。
