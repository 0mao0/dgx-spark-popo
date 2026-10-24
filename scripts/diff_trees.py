#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""构树 JSON 差分（计划 §6.3）：白名单外任何结构/值差异 = 失败。

白名单字段（默认 img_path / caption / table_body）只允许"新增字段"这一种差异；
字段两侧都有但值不同，仍然算失败。

用法:
  python scripts/diff_trees.py --old <目录或文件> --new <目录或文件> [--whitelist ...]

目录模式按相对路径配对 *.json；单侧缺失的文件记为失败。退出码 0=通过。
"""
import argparse
import json
import sys
from pathlib import Path

DEFAULT_WHITELIST = ("img_path", "caption", "table_body")
MAX_PRINT = 30


def collect_json(root: Path) -> dict:
    return {str(p.relative_to(root)).replace("\\", "/"): p for p in sorted(root.rglob("*.json"))}


def compare(old, new, path, wl, out):
    if isinstance(old, dict) and isinstance(new, dict):
        for k in new.keys() - old.keys():
            (out["allowed"] if k in wl else out["violations"]).append(f"{path}.{k}: 新库新增字段")
        for k in old.keys() - new.keys():
            out["violations"].append(f"{path}.{k}: 旧库有、新库无")
        for k in old.keys() & new.keys():
            compare(old[k], new[k], f"{path}.{k}", wl, out)
    elif isinstance(old, list) and isinstance(new, list):
        if len(old) != len(new):
            out["violations"].append(f"{path}: 列表长度 {len(old)} -> {len(new)}")
        for i, (a, b) in enumerate(zip(old, new)):
            compare(a, b, f"{path}[{i}]", wl, out)
    elif old != new:
        out["violations"].append(f"{path}: 值差异 {json.dumps(old, ensure_ascii=False)[:60]} -> "
                                 f"{json.dumps(new, ensure_ascii=False)[:60]}")


def diff_file(old_path: Path, new_path: Path, wl):
    out = {"allowed": [], "violations": []}
    try:
        old = json.loads(old_path.read_text(encoding="utf-8"))
        new = json.loads(new_path.read_text(encoding="utf-8"))
    except Exception as exc:
        out["violations"].append(f"解析失败: {exc}")
        return out
    compare(old, new, "$", wl, out)
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--old", required=True)
    ap.add_argument("--new", required=True)
    ap.add_argument("--whitelist", nargs="*", default=list(DEFAULT_WHITELIST))
    args = ap.parse_args()

    old_p, new_p = Path(args.old), Path(args.new)
    wl = set(args.whitelist)
    pairs = []
    if old_p.is_file() and new_p.is_file():
        pairs.append(("$", old_p, new_p))
    else:
        old_files, new_files = collect_json(old_p), collect_json(new_p)
        for name in sorted(old_files.keys() | new_files.keys()):
            if name not in old_files:
                pairs.append((name, None, new_files[name]))
            elif name not in new_files:
                pairs.append((name, old_files[name], None))
            else:
                pairs.append((name, old_files[name], new_files[name]))

    total_allowed = total_bad = 0
    failed_files = 0
    for name, o, n in pairs:
        if o is None:
            print(f"[FAIL] {name}: 旧库缺文件")
            failed_files += 1
            continue
        if n is None:
            print(f"[FAIL] {name}: 新库缺文件")
            failed_files += 1
            continue
        r = diff_file(o, n, wl)
        total_allowed += len(r["allowed"])
        total_bad += len(r["violations"])
        if r["violations"]:
            failed_files += 1
            print(f"[FAIL] {name}: {len(r['violations'])} 处白名单外差异")
            for v in r["violations"][:MAX_PRINT]:
                print(f"       {v}")
        elif r["violations"] == 0 and r["allowed"]:
            print(f"[PASS] {name}: 白名单内新增字段 {len(r['allowed'])} 处")
        else:
            print(f"[PASS] {name}: 完全一致")

    print(f"\n文件 {len(pairs)} 个：失败 {failed_files}；白名单外差异 {total_bad} 处；"
          f"白名单内新增 {total_allowed} 处")
    sys.exit(1 if (failed_files or total_bad) else 0)


if __name__ == "__main__":
    main()
