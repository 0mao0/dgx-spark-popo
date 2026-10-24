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
from loader import load_manifest, pick, pick_differential, doc_dir  # noqa: E402


def check_single_page_new(work: Path):
    """单页档放宽判据（计划 §6.3）：新库树有效且 title 判定非空。"""
    tree_dir = work / "tree"
    trees = sorted(tree_dir.rglob("*.json"))
    if not trees:
        return False, "无构树产物", 0
    try:
        has_children = any(
            json.loads(p.read_text(encoding="utf-8")).get("children") for p in trees)
    except Exception:
        return False, "构树 JSON 解析失败", 0
    titles = 0
    for p in (work / "inference_raw").rglob("summary.json"):
        try:
            titles += len(json.loads(p.read_text(encoding="utf-8")).get("title_label") or [])
        except Exception:
            pass
    reason = "树有效" if has_children else "树为空"
    return (has_children and titles > 0), reason, titles


def build_configs(url: str) -> str:
    cfg = [{"name": "diff", "url": url,
            "api_key": os.environ.get("POPO_SMOKE_API_KEY", ""),
            "model": os.environ.get("POPO_SMOKE_MODEL", "Popo")}]
    return json.dumps(cfg)


def run_chain(popo_root: Path, docs, out: Path, endpoint: str, greedy: bool,
              new_temperature="0"):
    env = os.environ.copy()
    env["POPO_CONFIGS"] = build_configs(endpoint)
    env["PYTHONUTF8"] = "1"
    if new_temperature is not None:
        env["POPO_TEMPERATURE"] = new_temperature
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
    ap.add_argument("--tier", choices=["smoke", "differential"], default="smoke",
                    help="differential=单页 2 本放宽判据 + 多页 8 本轮转严格等值（计划 §6.2）")
    ap.add_argument("--production-params", action="store_true",
                    help="M4 影子档：新库 temp=1（现产口径），跳过确定性复跑")
    args = ap.parse_args()

    manifest = load_manifest(args.manifest)
    if manifest is None:
        sys.exit("missing manifest: pass --manifest or set POPO_FROZEN_MANIFEST")
    chosen = pick(manifest, args.n) if args.tier == "smoke" \
        else pick_differential(manifest, n_multi=max(args.n - 2, 0))
    docs = [doc_dir(d, args.corpora_root) for d in chosen]
    manifest_by_id = {d["doc_id"]: d for d in manifest["docs"]}
    for d in docs:
        if not d.is_dir():
            sys.exit(f"doc dir not found: {d}")
    print("冒烟文档:")
    for d in docs:
        print(f"  {d.name}")

    out = Path(args.out)
    new_temp = None if args.production_params else "0"
    rc_new = run_chain(Path(args.new_root), docs, out / "new", args.new_endpoint,
                       greedy=False, new_temperature=new_temp)
    print(f"新库链路退出码 {rc_new.returncode}")

    if args.old_root:
        rc_old = run_chain(Path(args.old_root), docs, out / "old", args.old_endpoint, greedy=True)
        print(f"旧库链路退出码 {rc_old.returncode}")

    # 确定性校验：首本复跑，两次构树必须逐字节一致（temp=0 才有意义）
    if not args.production_params:
        rc_det = run_chain(Path(args.new_root), docs[:1], out / "new2", args.new_endpoint,
                           greedy=False, new_temperature=new_temp)
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
        # 正式差分对象 = 构树 JSON（计划 §6.3）；status/raw 等运行元数据不参与
        rc_diff = 0
        for d in docs:
            stratum = manifest_by_id[d.name]["stratum"]
            if stratum == "single_page":
                ok, reason, titles = check_single_page_new(out / "new" / d.name)
                print(f"== {d.name} 单页档（6fd49e4 放宽判据）==")
                print(f"  {reason}；title 判定 {titles} 条 -> "
                      f"{'通过' if ok else '需人工确认'}")
            r = subprocess.run(
                [sys.executable, str(REPO / "scripts" / "diff_trees.py"),
                 "--old", str(out / "old" / d.name / "tree"),
                 "--new", str(out / "new" / d.name / "tree")],
                capture_output=True, text=True, encoding="utf-8", errors="replace")
            print(r.stdout.strip())
            if stratum != "single_page":
                rc_diff = max(rc_diff, r.returncode)
        sys.exit(max(rc_new.returncode, rc_old.returncode, rc_diff))
    sys.exit(rc_new.returncode)


if __name__ == "__main__":
    main()
