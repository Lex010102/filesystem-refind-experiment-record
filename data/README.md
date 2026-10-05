# LoCoMo 数据固定与 canonical records

本目录保存正式实验的数据底座。原始数据只做固定和校验，不在原文件上清洗；后续六个单源条件和一个双源条件都必须从同一份 canonical records 构建，以免不同实验看到不同的源对话。

## 官方来源与版本

| 项目 | 固定值 |
| --- | --- |
| 官方仓库 | `snap-research/locomo` |
| 官方路径 | `data/locomo10.json` |
| 数据文件 commit | `cbfbc1dba6bc53d00625212a0f22d55ffee7c1fc` |
| 本地原始文件 | `raw/locomo10.json` |
| 文件大小 | `2,805,274` bytes |
| SHA-256 | `79fa87e90f04081343b8c8debecb80a9a6842b76a7aa537dc9fdf651ea698ff4` |
| 许可 | CC BY-NC 4.0；本地副本为 `LICENSE.locomo.txt` |

固定的原始文件含 10 个 conversation。本阶段选定 `conv-50` 作为正式开发 conversation：30 个自然 session、568 个 turn、204 道官方 QA。选择信息、计数、输出校验值和已知数据异常都记录在 `manifests/locomo-conv-50-v1.json`。

## 生成物

```text
data/
├── LICENSE.locomo.txt
├── raw/
│   └── locomo10.json                    # 官方原文件，不修改
├── processed/
│   └── conv-50.jsonl                    # 568 条统一 turn record
└── manifests/
    ├── locomo-conv-50-v1.json           # 来源、版本、计数和输出 hash
    └── source_map.json                   # locator、dia_id、JSONL 行号和原 JSON 指针
```

`conv-50.jsonl` 每一行只代表一个原始对话 turn，并按官方自然 session 和 turn 顺序排列。字段如下：

| 字段 | 含义 |
| --- | --- |
| `conversation_id` | 官方 `sample_id`，本阶段为 `conv-50` |
| `session_id` / `session_index` | 官方 session 名和数值序号 |
| `session_date` | 从官方时间字符串解析出的 ISO 日期 |
| `session_datetime` | ISO 格式的本地钟表时间；官方没有时区，因此不附加时区 |
| `session_datetime_raw` | 官方时间字符串原文 |
| `turn_index` | session 内从 1 开始的 turn 序号 |
| `global_turn_index` | 整个 conversation 内从 1 开始的序号，也等于 JSONL 行号 |
| `locator` | 本项目派生的 `[S{session}T{turn}]` 引用标记 |
| `dia_id` | 官方 turn 主键，例如 `D1:1` |
| `speaker` / `text` | 官方说话人与原始文本，不改写 |
| `media` | 官方可选的 `img_url`、`blip_caption`、`query`、`re-download` |
| `source_sha256` | 原始 `text` UTF-8 字节的 SHA-256 |
| `raw_turn_sha256` | 完整官方 turn 对象 canonical JSON 的 SHA-256 |

问题、标准答案和证据标签不进入 canonical turn records，避免在构建存储或检索索引时泄漏测试答案。它们目前只用于完整性审计；正式评测加载器将在后续单独实现。

## `source_map.json` 怎么用

- `by_locator["[S3T4]"]`：找到对应 `dia_id`、JSONL 行号和官方 JSON Pointer；
- `by_dia_id["D3:4"]`：反查本项目 locator 和 JSONL 行号；
- `sessions`：找到每个自然 session 覆盖的首尾行；
- `dia_id_aliases`：记录官方 QA 证据中的安全格式归一化。

官方 `conv-50` 的第 70 道 QA 把证据写成 `D30:05`，实际 turn 主键是 `D30:5`。原始文件保持不变；`source_map.json` 仅记录别名 `D30:05 -> D30:5 -> [S30T5]`，便于评测时可追溯地解析。

## 重新生成与验证

从仓库根目录运行：

```bash
python3 -m fs_memory_lab.locomo prepare
python3 -m unittest discover -s tests -v
```

转换器会先强制核对官方原文件 SHA-256；不匹配就停止，且不写输出。重复运行会得到字节完全相同的 canonical records、source map 和 manifest。

下游的 S1 平铺原始 session 已从这份固定记录生成在 `../experiments/locomo-conv50-v1/stores/s1-flat/`；其独立 manifest、生成方法和自动完整性测试见 `../experiments/locomo-conv50-v1/README.md`。

## 使用边界

LoCoMo 数据按 CC BY-NC 4.0 提供。本仓库保存许可全文并注明来源；数据和衍生实验材料只能在许可允许的范围内使用，尤其注意非商业限制。
