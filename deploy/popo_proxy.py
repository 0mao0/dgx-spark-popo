"""Popo vLLM 采样参数代理：监听 8008，转发 8010 前注入 MinerU-Popo 官方 generation_config 采样参数。

背景：MinerU-Popo 的 generation_config.json 定义 temperature=0.7 / top_p=0.8 / top_k=20，
但 vLLM OpenAI API 不带这些参数时默认 temperature=1.0（分布过平 → EOS token 概率被放大 →
图片输入首 token 即 <|im_end|> 空输出）。本代理在转发前为每个请求补上官方采样默认值，
请求端无需任何改动。EOS 修复思路：top_k=20 截断采样空间，避免 EOS 概率噪声。

用法：vllm serve 监听 127.0.0.1:8010；本代理监听 0.0.0.0:8008 并转发。
"""
import os
import json
import time

import httpx
from fastapi import FastAPI, Request, Response
from fastapi.responses import StreamingResponse

UPSTREAM = os.environ.get("POPO_PROXY_UPSTREAM", "http://127.0.0.1:8010")
LISTEN_PORT = int(os.environ.get("POPO_PROXY_PORT", "8008"))
DEFAULT_TEMPERATURE = float(os.environ.get("POPO_PROXY_TEMPERATURE", "0.7"))
DEFAULT_TOP_P = float(os.environ.get("POPO_PROXY_TOP_P", "0.8"))
DEFAULT_TOP_K = int(os.environ.get("POPO_PROXY_TOP_K", "20"))

app = FastAPI(title="popo-sampling-proxy")
client = httpx.AsyncClient(timeout=httpx.Timeout(600.0, connect=30.0))


def inject_sampling(body: dict) -> dict:
    """仅为 chat/completions 请求补默认采样参数；已有显式值则尊重请求。"""
    if not isinstance(body, dict):
        return body
    body.setdefault("temperature", DEFAULT_TEMPERATURE)
    body.setdefault("top_p", DEFAULT_TOP_P)
    body.setdefault("top_k", DEFAULT_TOP_K)
    return body


@app.api_route("/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS"])
async def proxy(path: str, request: Request):
    url = f"{UPSTREAM}/{path}"
    headers = {k: v for k, v in request.headers.items() if k.lower() not in ("host", "content-length")}
    body_bytes = await request.body()

    if request.method == "POST" and path.rstrip("/").endswith("chat/completions"):
        try:
            body = json.loads(body_bytes)
            inject_sampling(body)
            body_bytes = json.dumps(body).encode("utf-8")
        except Exception:
            pass

    # 恒流式转发：客户端断连 -> Starlette 取消生成器 -> finally aclose 关上游 -> vLLM abort 释放算力

    upstream_req = client.build_request(
        request.method, url, headers=headers, content=body_bytes,
    )
    try:
        upstream_resp = await client.send(upstream_req, stream=True)
    except Exception as exc:
        return Response(
            content=json.dumps({"error": {"message": f"upstream error: {exc}", "type": "proxy_error"}},
                               ensure_ascii=False),
            status_code=502,
            media_type="application/json",
        )

    resp_headers = {k: v for k, v in upstream_resp.headers.items()
                    if k.lower() not in ("content-length", "content-encoding", "transfer-encoding")}
    async def gen():
        try:
            async for chunk in upstream_resp.aiter_bytes():
                yield chunk
        finally:
            await upstream_resp.aclose()
    return StreamingResponse(gen(), status_code=upstream_resp.status_code, headers=resp_headers)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=LISTEN_PORT, log_level="info")
