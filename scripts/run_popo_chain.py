#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""对若干文档跑 PoPo 客户端三段链：label_normalization -> run_inference -> get_json_tree。

调用契约与既有生产调用方保持一致：
  输入  <doc>/parsed/mineru_raw/middle.json（回退 content_list.json）+ <doc>/source/*.pdf
  链路  label_normalization.py -> 修补 input_label -> run_inference.py -> get_json_tree.py
  环境  POPO_CONFIGS / POPO_API_TIMEOUT / POPO_MAX_TOKENS / POPO_TEMPERATURE 由调用方注入

用法:
  python scripts/run_popo_chain.py --popo-root <lib根> --doc <doc目录> [...] \
      --out <输出根> [--timeout-inference 3600]

产物: <out>/<doc_id>/{input,normalized,enriched,tree,tree_txt} 与 status.json
"""
import argparse
import json
import shutil
import subprocess
import sys
import time
from pathlib import Path


def find_pdf(doc: Path) -> Path:
    src = doc / "source"
    pdfs = sorted(src.glob("*.pdf")) if src.is_dir() else []
    if not pdfs:
        raise FileNotFoundError(f"no source pdf under {src}")
    return pdfs[0]


def prepare_input(doc: Path, work: Path) -> Path:
    doc_id = doc.name
    vlm = work / "input" / doc_id / "vlm"
    vlm.mkdir(parents=True, exist_ok=True)
    raw = doc / "parsed" / "mineru_raw"
    if (raw / "middle.json").is_file():
        src = raw / "middle.json"
        dst = vlm / f"{doc_id}_middle.json"
    elif (raw / "content_list.json").is_file():
        src = raw / "content_list.json"
        dst = vlm / f"{doc_id}_content_list.json"
    else:
        raise FileNotFoundError(f"no mineru_raw under {raw}")
    shutil.copy2(src, dst)
    return dst


def patch_input_label(normalized: Path, doc_id: str, pdf: Path) -> int:
    """把 normalized 输出里的 input_label 指到真实 PDF（与生产调用方相同）。"""
    n = 0
    for nf in normalized.rglob(f"{doc_id}.json"):
        data = json.loads(nf.read_text(encoding="utf-8"))
        if isinstance(data, list):
            for item in data:
                if isinstance(item, dict) and item.get("doc_id") == doc_id:
                    item["input_label"] = str(pdf)
                    n += 1
        elif isinstance(data, dict) and data.get("doc_id") == doc_id:
            data["input_label"] = str(pdf)
            n += 1
        nf.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return n


def run_stage(args, timeout: int) -> str:
    proc = subprocess.run(
        args, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout,
    )
    if proc.returncode != 0:
        tail = (proc.stderr or proc.stdout or "")[-2000:]
        raise RuntimeError(f"exit {proc.returncode}: {tail}")
    return proc.stdout or ""


def process_doc(popo_root: Path, doc: Path, out_root: Path, timeouts: dict) -> dict:
    doc_id = doc.name
    work = out_root / doc_id
    if work.exists():
        shutil.rmtree(work)
    work.mkdir(parents=True)
    py = sys.executable
    pdf = find_pdf(doc)
    t0 = time.time()
    stages = {}

    prepare_input(doc, work)

    normalized = work / "normalized"
    run_stage(
        [py, str(popo_root / "post_processing" / "label_normalization.py"),
         "--model", "mineru", "--input-dir", str(work / "input"),
         "--output-dir", str(normalized), "--doc-id", doc_id],
        timeouts["label"],
    )
    patched = patch_input_label(normalized, doc_id, pdf)
    stages["input_label_patched"] = patched

    enriched = work / "enriched"
    run_stage(
        [py, str(popo_root / "post_processing" / "run_inference.py"),
         "--model", "mineru", "--input-dir", str(normalized),
         "--output-dir", str(enriched), "--limit", "0",
         "--raw-output-root", str(work / "inference_raw")],
        timeouts["inference"],
    )
    stages["inference"] = "done"

    tree = work / "tree"
    run_stage(
        [py, str(popo_root / "post_processing" / "get_json_tree.py"),
         "--input-dir", str(enriched), "--output-dir", str(tree),
         "--txt-dir", str(work / "tree_txt")],
        timeouts["tree"],
    )
    stages["tree"] = "done"

    trees = sorted(tree.rglob("*.json"))
    return {"doc_id": doc_id, "status": "ok", "seconds": round(time.time() - t0, 1),
            "tree_files": [str(p.relative_to(work)) for p in trees], **stages}


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--popo-root", required=True, help="被测 popo 库根（含 post_processing/）")
    ap.add_argument("--doc", required=True, nargs="+", help="文档目录（含 parsed/mineru_raw 与 source/）")
    ap.add_argument("--out", required=True, help="输出根目录")
    ap.add_argument("--timeout-label", type=int, default=300)
    ap.add_argument("--timeout-inference", type=int, default=3600)
    ap.add_argument("--timeout-tree", type=int, default=300)
    args = ap.parse_args()

    popo_root = Path(args.popo_root).resolve()
    out_root = Path(args.out).resolve()
    out_root.mkdir(parents=True, exist_ok=True)
    timeouts = {"label": args.timeout_label, "inference": args.timeout_inference,
                "tree": args.timeout_tree}

    results = []
    for d in args.doc:
        doc = Path(d).resolve()
        try:
            r = process_doc(popo_root, doc, out_root, timeouts)
        except Exception as exc:
            r = {"doc_id": doc.name, "status": "failed",
                 "error": f"{type(exc).__name__}: {str(exc)[:500]}"}
        results.append(r)
        print(json.dumps(r, ensure_ascii=False), flush=True)

    (out_root / "status.json").write_text(
        json.dumps(results, ensure_ascii=False, indent=1), encoding="utf-8")
    failed = [r for r in results if r["status"] != "ok"]
    print(f"完成 {len(results) - len(failed)}/{len(results)}；输出 {out_root}")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
