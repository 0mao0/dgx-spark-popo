#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""冒烟 + 新旧差分编排（M2 DoD / M3 彩排）。

流程:
  1. 从冻结清单确定性取 n 本（single_page -> table_dense -> regular）
  2. 新库三段链（POPO_TEMPERATURE=0，直连端点）
  3. 旧库三段链（经 greedy_proxy 强制 temperature=0；不给 --old-root 则跳过）
  4. 首本新库复跑一次做确定性校验（两次构树应完全一致）
  5. diff_trees 白名单差分

端点与密钥经环境变量注入（不入仓）:
  POPO_SMOKE_API_KEY   引擎/代理 api-key
  POPO_SMOKE_MODEL     模型名，默认 Popo

用法:
  python scripts/smoke_diff.py --new-root <新库> [--old-root <旧库>] \
      --manifest <manifest.json> --corpora-root <语料根> --out <输出目录> \
      --new-endpoint http://127.0.0.1:18008/v1 [--old-endpoint http://127.0.0.1:18009/v1] [--n 3]
"""
import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "tests" / "frozen"))
from loader import load_manifest, pick, doc_dir  # noqa: E402


def build_configs(url: str) -> str:
    cfg = [{"name": "diff", "url": url,
            "api_key": os.environ.get("POPO_SMOKE_API_KEY", ""),
            "model": os.environ.get("POPO_SMOKE_MODEL", "Popo")}]
    return json.dumps(cfg)


def run_chain(popo_root: Path, docs, out: Path, endpoint: str, greedy: bool):
    env = os.environ.copy()
    env["POPO_CONFIGS"] = build_configs(endpoint)
    env["PYTHONUTF8"] = "1"
    if not greedy:
        env["POPO_TEMPERATURE"] = "0"
    cmd = [sys.executable, str(REPO / "scripts" / "run_popo_chain.py"),
           "--popo-root", str(popo_root), "--out", str(out),
           "--doc", *[str(d) for d in docs]]
    return subprocess.run(cmd, env=env, encoding="utf-8", errors="replace")


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--new-root", required=True)
    ap.add_argument("--old-root", default="")
    ap.add_argument("--manifest", required=True)
    ap.add_argument("--corpora-root", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--new-endpoint", required=True)
    ap.add_argument("--old-endpoint", default="http://127.0.0.1:18009/v1")
    ap.add_argument("--n", type=int, default=3)
    args = ap.parse_args()

    manifest = load_manifest(args.manifest)
    if manifest is None:
        sys.exit("missing manifest: pass --manifest or set POPO_FROZEN_MANIFEST")
    docs = [doc_dir(d, args.corpora_root) for d in pick(manifest, args.n)]
    for d in docs:
        if not d.is_dir():
            sys.exit(f"doc dir not found: {d}")
    print("冒烟文档:")
    for d in docs:
        print(f"  {d.name}")

    out = Path(args.out)
    rc_new = run_chain(Path(args.new_root), docs, out / "new", args.new_endpoint, greedy=False)
    print(f"新库链路退出码 {rc_new.returncode}")

    if args.old_root:
        rc_old = run_chain(Path(args.old_root), docs, out / "old", args.old_endpoint, greedy=True)
        print(f"旧库链路退出码 {rc_old.returncode}")

    # 确定性校验：首本复跑，两次构树必须逐字节一致
    rc_det = run_chain(Path(args.new_root), docs[:1], out / "new2", args.new_endpoint, greedy=False)
    print(f"确定性复跑退出码 {rc_det.returncode}")
    first = docs[0].name
    r = subprocess.run(
        [sys.executable, str(REPO / "scripts" / "diff_trees.py"),
         "--old", str(out / "new" / first / "tree"), "--new", str(out / "new2" / first / "tree"),
         "--whitelist"],
        capture_output=True, text=True, encoding="utf-8", errors="replace")
    print(f"确定性校验（temp=0 复跑应零差异）: {'通过' if r.returncode == 0 else '失败'}")
    if r.returncode != 0:
        print(r.stdout[-1500:])

    if args.old_root:
        # 正式差分对象 = 构树后 JSON（计划 §6.3）；status/raw 等运行元数据不参与
        rc_diff = 0
        for d in docs:
            r = subprocess.run(
                [sys.executable, str(REPO / "scripts" / "diff_trees.py"),
                 "--old", str(out / "old" / d.name / "tree"),
                 "--new", str(out / "new" / d.name / "tree")],
                capture_output=True, text=True, encoding="utf-8", errors="replace")
            print(f"== {d.name} 旧库 vs 新库 ==")
            print(r.stdout.strip())
            rc_diff = max(rc_diff, r.returncode)
        sys.exit(max(rc_new.returncode, rc_old.returncode, rc_diff))
    sys.exit(rc_new.returncode)


if __name__ == "__main__":
    main()
