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

## S2：Foldered verbatim sessions

独立 Foldering Agent 和本项目重建的 system prompt 已实现于 `fs_memory_lab/foldering_prompt.py`。模型只能看到 `view`、`grep` 和受限 `rename`；工具层强制每次操作只能改变一个 `.md` 文件的父目录，不能改变 basename 或字节。

可在仓库根目录离线查看将要发送给模型的完整 prompt；该命令不读取 API key，也不调用 API：

```bash
python3 -m fs_memory_lab.cli foldering-prompt
```

安全执行层已实现于 `fs_memory_lab/s2.py`。它会先核对冻结的 S1 manifest 和30个正式文件，再建立独立 staging；模型只操作 staging。成功 episode 必须通过文件数、basename 集、逐文件完整/正文 hash、根目录残留、目录 slug、空目录和路径敏感 layout hash 等全量 gate，随后才发布 store、path map、trace、manifest，并最后写入 `s2-foldered.COMMITTED`。API、模型或 gate 失败只会产生位于 `local-runs/` 的隔离诊断，不会生成可被下游接受的正式 S2。

正式 S2 已于 run `20261005T155659458241Z-9391e1f0` 一次构建成功，并由独立离线 verifier 重新计算全部正式产物。实际请求模型别名为 `coding`，NUS SoC 返回 `qwen3.8:27b`；因此这是论文方法在本地 backbone 上的复现，不能表述为论文同模型复现。

| 结果 | 正式值 |
| --- | --- |
| 文件与目录 | 30 个 session、4 个一级主题目录、根目录 0 个 `.md` |
| 主题目录 | `cars-and-auto-work` 11；`music-and-performance` 14；`photography` 2；`travel-and-outdoors` 3 |
| 内容 hash | `5a58a8cca8616b91f3c231671271f6dbbedc669330b91e410980223ad2488ad8`，与 S1 完全相同 |
| 布局 hash | `13060ab52750d7b9ca0ab5b667a6aac69fb38021190bbff7ebd7336150508d6a` |
| 模型调用 | 12 rounds；32 次 `view`；30 次 `rename`；合计 62 次工具调用 |
| Token | prompt 380,653；completion 15,096；total 395,749 |
| 运行代码 | Git commit `b05732e0886ea56d6813021e7e3c01b24c7d10a7` |

正式产物分别位于：

```text
stores/s2-foldered/                       # 供 E3/E4 共用的只读 store
manifests/s2-foldered.json               # 输入、配置、成本与完整性承诺
manifests/s2-foldered-path-map.json      # S1 path -> S2 path
traces/s2-foldering.json                 # 12 轮完整 agent trace
manifests/s2-foldered.COMMITTED          # 最后发布的有效性标记
```

当前 checkout 已经存在正式产物，不应再次运行 `build-s2`。在仓库根目录随时可以完全离线复核：

```bash
# 完全离线地重新计算 store、manifest、path map、trace 和 marker 的交叉一致性
python3 -m fs_memory_lab.cli verify-s2
```

`build-s2` 不提供覆盖模式。只要正式 store、manifest、path map、trace 或 COMMITTED 标记中任意一个已经存在，它就会在调用模型前停止。真实模型的 taxonomy 不保证多次相同；manifest 分别记录 requested model alias、API 返回的 served model、Prompt/code hash、轮数、工具调用和 token usage。当前 adapter 没有向提供商发送 seed，因此不能把本地 Python seed 42 宣称为真实 LLM 采样可重复性保证，也不能为了挑选更好看的 taxonomy 删除后重跑。
