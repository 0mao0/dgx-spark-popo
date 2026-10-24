# -*- coding: utf-8 -*-
"""冻结集清单加载器。

真实 manifest.json 属内部件，不入公开仓（评审 F2）；由内部评测环境经
环境变量 POPO_FROZEN_MANIFEST 注入。缺失时 load_manifest 返回 None，
CI 单测照常运行。
"""
import json
import os
from pathlib import Path

REQUIRED_DOC_KEYS = {"doc_id", "library", "sha256", "size_bytes", "pages", "stratum"}
STRATA = {
    "single_page", "long", "scanned",
    "numbered_heading", "table_dense", "image_dense", "regular",
}


def load_manifest(path=None):
    """读取并校验清单；未配置 POPO_FROZEN_MANIFEST 时返回 None。"""
    path = path or os.environ.get("POPO_FROZEN_MANIFEST", "").strip()
    if not path:
        return None
    m = json.loads(Path(path).read_text(encoding="utf-8"))
    if m.get("version") != "frozen-v1":
        raise ValueError(f"unexpected manifest version: {m.get('version')!r}")
    for d in m["docs"]:
        missing = REQUIRED_DOC_KEYS - d.keys()
        if missing:
            raise ValueError(f"{d.get('doc_id')}: missing keys {sorted(missing)}")
        if d["stratum"] not in STRATA:
            raise ValueError(f"{d['doc_id']}: bad stratum {d['stratum']!r}")
    return m


def pick(manifest, n=3, order=("single_page", "table_dense", "regular")):
    """确定性取 n 本：按 order 层优先、doc_id 升序；层内不足按全表 doc_id 补齐。"""
    docs = sorted(manifest["docs"], key=lambda x: x["doc_id"])
    out = []
    for stratum in order:
        for d in docs:
            if d["stratum"] == stratum and len(out) < n and d not in out:
                out.append(d)
        if len(out) >= n:
            break
    for d in docs:
        if len(out) >= n:
            break
        if d not in out:
            out.append(d)
    return out[:n]


def pick_differential(manifest, n_multi=8, n_single=2):
    """差分档取样（计划 §6.2）：单页 n_single 本走放宽判据，多页 n_multi 本轮转六层走严格等值。"""
    docs = sorted(manifest["docs"], key=lambda x: x["doc_id"])
    single = [d for d in docs if d["stratum"] == "single_page"][:n_single]
    multi_strata = ["table_dense", "numbered_heading", "image_dense", "scanned", "long", "regular"]
    multi, i = [], 0
    while len(multi) < n_multi:
        added = False
        for s in multi_strata:
            if len(multi) >= n_multi:
                break
            cands = [d for d in docs
                     if d["stratum"] == s and d not in multi and d not in single]
            if i < len(cands):
                multi.append(cands[i])
                added = True
        if not added:
            break
        i += 1
    return single + multi


def doc_dir(manifest_doc, corpora_root):
    """manifest 条目 -> 语料库文档目录。"""
    return Path(corpora_root) / manifest_doc["library"] / "documents" / manifest_doc["doc_id"]
