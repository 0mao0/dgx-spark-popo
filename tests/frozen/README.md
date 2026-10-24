# tests/frozen（M2 交付占位）

冻结集清单与回归报告为**内部件**，存内部 ops 仓，不放本仓（评审 F2）。

本目录只提供清单加载器与 schema 示例。真实 `manifest.json` 由内部评测环境注入。

## manifest schema

```json
{
  "version": "frozen-v1",
  "seed": 20261024,
  "thresholds": {"version": "thresholds-v1", "long_pages": 200},
  "docs": [
    {"doc_id": "doc-0002000a", "library": "lab-firm-full",
     "sha256": "<64 hex>", "size_bytes": 0, "pages": 1, "stratum": "regular"}
  ]
}
```

字段说明：`stratum` ∈ single_page / long / scanned / numbered_heading / table_dense / image_dense / regular；`sha256` 为 source PDF 摘要，跑测前校验一致性，不一致视为语料漂移、立即停。

## 加载器约定（M2 实现）

- `tests/frozen/loader.py` 读取环境变量 `POPO_FROZEN_MANIFEST` 指向的真实清单；
- 缺失或 schema 不符时跳过（CI 环境无清单属正常，pytest 只跑单测）。
