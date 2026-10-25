# -*- coding: utf-8 -*-
"""文档级 PoPo API：POST middle.json + PDF，返回判定块与文档树。

形态对齐「服务端跑链」的部署：调用方零依赖，只需 HTTP。
内部通过子进程调用 popo-client 的三段链（label 归一化 → 4B 判定 → 构树），
引擎地址经 POPO_CONFIGS 指定（通常为本机采样代理 :8008）。

环境变量：
  POPO_REPO_PATH     popo 包根（含 post_processing/；pip 安装的 popo-client 取其 __path__）
  POPO_CONFIGS       引擎端点 JSON 列表（url 指向采样代理或 vLLM）
  POPO_DOC_API_KEY   可选；设置后要求 Authorization: Bearer <key>
  POPO_DOC_PORT      监听端口，默认 8009
  POPO_DOC_CONCURRENCY  并发链路上限，默认 1（链内部已并发发 prompt）

用法：
  uvicorn server.popo_api:app --host 0.0.0.0 --port 8009
  curl -H "Authorization: Bearer $KEY" -F middle=@middle.json -F pdf=@doc.pdf \
       http://host:8009/v1/enhance
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import uuid
from pathlib import Path

from fastapi import FastAPI, File, Form, Header, HTTPException, UploadFile

API_KEY = (os.environ.get("POPO_DOC_API_KEY") or "").strip()
PORT = int(os.environ.get("POPO_DOC_PORT", "8009"))
TIMEOUTS = {
    "label": int(os.environ.get("POPO_DOC_TIMEOUT_LABEL", "300")),
    "inference": int(os.environ.get("POPO_DOC_TIMEOUT_INFERENCE", "1800")),
    "tree": int(os.environ.get("POPO_DOC_TIMEOUT_TREE", "300")),
}


def _popo_repo() -> Path:
    env = os.environ.get("POPO_REPO_PATH", "").strip()
    if env and (Path(env) / "post_processing" / "label_normalization.py").is_file():
        return Path(env)
    import popo
    p = Path(list(popo.__path__)[0])
    if (p / "post_processing" / "label_normalization.py").is_file():
        return p
    raise RuntimeError("popo 包不可用：设 POPO_REPO_PATH 或安装 popo-client")


POPO_ROOT = _popo_repo()
app = FastAPI(title="popo-docapi")


def _check_auth(authorization: str):
    if API_KEY and authorization != f"Bearer {API_KEY}":
        raise HTTPException(status_code=401, detail="bad api key")


def _run(args, timeout: int):
    proc = subprocess.run(args, capture_output=True, text=True,
                          encoding="utf-8", errors="replace", timeout=timeout)
    if proc.returncode != 0:
        tail = (proc.stderr or proc.stdout or "")[-800:]
        raise HTTPException(status_code=502, detail=f"chain stage failed: {tail}")


@app.get("/health")
def health():
    return {"ok": True, "popo_root": str(POPO_ROOT)}


@app.post("/v1/enhance")
async def enhance(
    middle: UploadFile = File(..., description="MinerU middle.json"),
    pdf: UploadFile = File(..., description="源 PDF"),
    doc_id: str = Form(default=""),
    authorization: str = Header(default=""),
):
    _check_auth(authorization)
    doc_id = (doc_id or Path(pdf.filename or "doc").stem or "doc")[:64] \
        .replace("/", "_").replace("\\", "_") or "doc"
    work = Path(tempfile.mkdtemp(prefix=f"popo-docapi-{uuid.uuid4().hex[:8]}-"))
    try:
        middle_bytes = await middle.read()
        pdf_bytes = await pdf.read()
        try:
            json.loads(middle_bytes)
        except Exception:
            raise HTTPException(status_code=400, detail="middle 不是合法 JSON")
        if not pdf_bytes[:5] == b"%PDF-":
            raise HTTPException(status_code=400, detail="pdf 文件头不是 %PDF-")

        vlm = work / "input" / doc_id / "vlm"
        vlm.mkdir(parents=True)
        (vlm / f"{doc_id}_middle.json").write_bytes(middle_bytes)
        src = work / "src"
        src.mkdir()
        (src / f"{doc_id}.pdf").write_bytes(pdf_bytes)
        pdf_path = src / f"{doc_id}.pdf"

        t0 = time.time()
        py = sys.executable
        env = os.environ.copy()

        normalized = work / "normalized"
        _run([py, str(POPO_ROOT / "post_processing" / "label_normalization.py"),
              "--model", "mineru", "--input-dir", str(work / "input"),
              "--output-dir", str(normalized), "--doc-id", doc_id],
             TIMEOUTS["label"])

        # input_label 补丁：把 normalized 里的路径指到本服务暂存的 PDF
        for nf in normalized.rglob(f"{doc_id}.json"):
            data = json.loads(nf.read_text(encoding="utf-8"))
            items = data if isinstance(data, list) else [data]
            for it in items:
                if isinstance(it, dict) and it.get("doc_id") == doc_id:
                    it["input_label"] = str(pdf_path)
            nf.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

        enriched = work / "enriched"
        _run([py, str(POPO_ROOT / "post_processing" / "run_inference.py"),
              "--model", "mineru", "--input-dir", str(normalized),
              "--output-dir", str(enriched), "--limit", "0",
              "--raw-output-root", str(work / "raw")],
             TIMEOUTS["inference"])

        tree = work / "tree"
        _run([py, str(POPO_ROOT / "post_processing" / "get_json_tree.py"),
              "--input-dir", str(enriched), "--output-dir", str(tree),
              "--txt-dir", str(work / "tree_txt")],
             TIMEOUTS["tree"])

        tree_file = next(iter(sorted(tree.rglob("*.json"))), None)
        enriched_files = sorted(enriched.rglob("*.json"))
        if tree_file is None or not enriched_files:
            raise HTTPException(status_code=502, detail="链路未产出（判定/构树为空）")
        return {
            "doc_id": doc_id,
            "seconds": round(time.time() - t0, 1),
            "enriched_blocks": json.loads(enriched_files[0].read_text(encoding="utf-8")),
            "document_tree": json.loads(tree_file.read_text(encoding="utf-8")),
        }
    finally:
        shutil.rmtree(work, ignore_errors=True)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=PORT)
