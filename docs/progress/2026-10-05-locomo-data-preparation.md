# 2026-10-05：固定 LoCoMo 官方数据与统一记录层

## 今天完成的内容

1. 从官方 `snap-research/locomo` 仓库固定 `data/locomo10.json`，使用数据文件最后修改所在的 commit `cbfbc1dba6bc53d00625212a0f22d55ffee7c1fc`。
2. 将官方原文件保存为 `data/raw/locomo10.json`，并把 CC BY-NC 4.0 许可保存为 `data/LICENSE.locomo.txt`。
3. 新增 `fs_memory_lab.locomo` 确定性转换器；每次运行都先验证官方文件 SHA-256。
4. 从 `conv-50` 生成 568 条统一 turn-level canonical records。
5. 生成 `source_map.json`，支持 `[SxTy]`、官方 `dia_id`、JSONL 行号和原 JSON Pointer 的相互定位。
6. 生成版本 manifest，固定来源、schema、计数、输出 hash、许可与异常处理。
7. 添加离线测试：原文件校验、568 条记录逐条回溯、双向映射、QA 隔离、确定性再生成和错误 hash 拒绝。

## 固定结果

| 对象 | 结果 |
| --- | --- |
| 官方原文件 | 2,805,274 bytes |
| 原文件 SHA-256 | `79fa87e90f04081343b8c8debecb80a9a6842b76a7aa537dc9fdf651ea698ff4` |
| 选定 conversation | `conv-50`（官方数组 index 9） |
| 说话人 | Calvin、Dave |
| 自然 session | 30 |
| turn | 568 |
| 官方 QA | 204；其中非 adversarial 158，adversarial 46 |
| canonical JSONL SHA-256 | `130a5a1e1b75083358ef27a98dd215a4e75c819ace6f2ee9b560ba394e0f0394` |
| source map SHA-256 | `6e99115961bae06a48bfb7e82dbdcc18dc32ccf6c5ce57e3c266dfc7a5d4d574` |

## 数据异常及处理

官方第 70 道 QA 的 evidence 使用 `D30:05`，而对应 turn 的真实 `dia_id` 是 `D30:5`。我们不修改官方原文件，也不静默改写，而是在 manifest 和 source map 中登记唯一别名：

```text
D30:05 -> D30:5 -> [S30T5]
```

另外，官方数据存在 2 道空 evidence 的 open-domain QA，以及 1 道 evidence 列表内重复引用的问题。这些都在 manifest 中计数；canonical 对话记录不含问题、答案或 evidence，避免答案泄漏。

## 为什么先做统一记录层

后续 S1 平铺原始 session、S2 文件夹化原始 session 和 S3 LLM 整理文件系统必须从同一批源 turn 派生。这样 E1–E7 的差异只来自存储和检索方法，而不是切片内容、顺序或数据版本。

## 下一步

冻结开发/正式评测范围，然后先实现 S1 builder：严格以 LoCoMo 自然 session 为写入单位，保留 canonical locator；之后再从相同 records 实现 S2。此时不应先运行管理 LLM，也不应为六个条件分别切一次原始数据。
