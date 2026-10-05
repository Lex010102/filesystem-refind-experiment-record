# LoCoMo `conv-50` 实验产物

本目录存放从固定 canonical records 派生的正式实验 store。输入始终是 `data/processed/conv-50.jsonl` 和 `data/manifests/source_map.json`；问题、标准答案、题目类别和 gold evidence 不参与 store 构建。

## S1：平铺原始 session

```text
experiments/locomo-conv50-v1/
├── stores/s1-flat/
│   ├── session-01.md
│   ├── ...
│   └── session-30.md
└── manifests/s1-flat.json
```

- 30 个 LoCoMo 自然 session 对应 30 个平铺 Markdown 文件；
- 共覆盖 568 个 source turns，顺序不变；
- 每条发言保留原 speaker、原始 text、`[SxTy]` 和官方 `dia_id`；
- 125 条官方 `blip_caption` 作为固定文本代理保留；不写入或访问图片 URL；
- 不摘要、不改写、不按主题合并，也不调用 LLM；
- manifest 独立放在 store 外，避免检索器把校验信息当成记忆内容；
- 当前 store SHA-256 为 `5a58a8cca8616b91f3c231671271f6dbbedc669330b91e410980223ad2488ad8`。

Filesystem 论文明确了“一次自然 session 一个原文文件、S1 平铺、零模型构建成本”的语义规则，但没有公开原始 session 文件的逐字节模板。这里的 Markdown/frontmatter 和来源标签排版是本项目公开、确定性的实现，不应表述成作者发布的原始模板。

## 重新生成

在仓库根目录执行：

```bash
python3 -m fs_memory_lab.stores build-s1
```

第一次写入会报告 `write_status: created`；文件已存在且与确定性结果完全相同时会报告 `verified-existing`。如果已有文件被改动、遗漏或多出文件，构建器会停止，不会静默覆盖。

如需安装为命令行入口，也可以使用：

```bash
fs-stores build-s1
```

## 自动完整性测试

```bash
python3 -m unittest tests.test_stores -v
```

测试会逐条反查 568 条记录，验证 30 个文件、原顺序、原始换行、125 条 caption、locator/`dia_id` 唯一性、逐文件完整/正文 hash、总体 store hash、跨目录确定性、重复构建幂等性、输入不变、防篡改和 gold 字段隔离。完整测试套件可运行：

```bash
python3 -m unittest discover -s tests -v
```

## S2 当前边界

独立 Foldering Agent 和本项目重建的 system prompt 已实现于 `fs_memory_lab/foldering_prompt.py`。模型只能看到 `view`、`grep` 和受限 `rename`；工具层强制每次操作只能改变一个 `.md` 文件的父目录，不能改变 basename 或字节。

可在仓库根目录离线查看将要发送给模型的完整 prompt；该命令不读取 API key，也不调用 API：

```bash
python3 -m fs_memory_lab.cli foldering-prompt
```

目前尚未调用 API，也尚未生成 `stores/s2-foldered/`。正式运行前仍需实现安全执行层：从不可变 S1 复制到 staging，运行 Foldering Agent，验证 30 个 basename 和逐文件 SHA-256 全部不变后，再原子发布 S2。绝不能把本目录中的正式 S1 直接挂载为可写运行目录。
