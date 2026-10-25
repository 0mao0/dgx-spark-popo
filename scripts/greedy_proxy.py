#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""确定性差分用的本地转发代理：把 chat/completions 的 temperature 强制改写后转发。

用途：旧库代码不可修改、且显式发送 temperature=1（生产代理是 setdefault 语义，
不会覆盖），因此旧库侧经本代理实现贪心解码；新库直接用 POPO_TEMPERATURE=0。
仅缓冲转发（非流式），差分/回归是串行场景，够用。

用法:
  python scripts/greedy_proxy.py --listen 18009 --upstream http://127.0.0.1:18008 [--temperature 0]
"""
import argparse
import json
import threading
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ARGS = None
HOP_BY_HOP = {"host", "content-length", "connection", "transfer-encoding",
              "content-encoding", "keep-alive", "accept-encoding"}
UPSTREAM_SEM = threading.Semaphore(4)


def fetch_upstream(url, data, headers, method):
    """上游访问：并发闸门 + 对拒绝/超时短重试（ssh -L 在并发洪峰下会间歇拒连）。"""
    last = None
    for attempt in range(3):
        with UPSTREAM_SEM:
            req = urllib.request.Request(url, data=data if data else None, method=method)
            for k, v in headers.items():
                if k.lower() not in HOP_BY_HOP:
                    req.add_header(k, v)
            try:
                with urllib.request.urlopen(req, timeout=ARGS.timeout) as resp:
                    return resp.read(), resp.status, dict(resp.headers)
            except urllib.error.HTTPError as e:
                return e.read(), e.code, dict(e.headers)
            except Exception as exc:
                last = exc
        time.sleep(2 * (attempt + 1))
    payload = json.dumps({"error": {"message": f"proxy error: {last}"}},
                         ensure_ascii=False).encode("utf-8")
    return payload, 502, {"Content-Type": "application/json"}


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *a):
        pass

    def _proxy(self):
        length = int(self.headers.get("content-length", 0) or 0)
        body = self.rfile.read(length) if length else b""
        forced = None
        if (self.command == "POST"
                and self.path.rstrip("/").endswith("chat/completions") and body):
            try:
                b = json.loads(body)
                forced = b.get("temperature")
                b["temperature"] = ARGS.temperature
                body = json.dumps(b).encode("utf-8")
            except Exception:
                pass
        url = ARGS.upstream.rstrip("/") + self.path
        payload, status, headers = fetch_upstream(url, body, dict(self.headers), self.command)

        self.send_response(status)
        for k, v in headers.items():
            if k.lower() not in HOP_BY_HOP:
                self.send_header(k, v)
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)
        if ARGS.log_file:
            snippet = ""
            try:
                snippet = json.loads(payload).get("choices", [{}])[0].get("message", {}).get("content") or ""
            except Exception:
                snippet = payload[:80].decode("utf-8", "replace")
            with open(ARGS.log_file, "a", encoding="utf-8") as f:
                f.write(json.dumps({"path": self.path, "req_bytes": length,
                                    "client_temp": forced, "forced": ARGS.temperature,
                                    "status": status, "resp_bytes": len(payload),
                                    "content": snippet[:120]}, ensure_ascii=False) + "\n")

    do_GET = do_POST = do_PUT = do_DELETE = do_PATCH = do_OPTIONS = _proxy


def main():
    global ARGS, UPSTREAM_SEM
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--listen", type=int, default=18009)
    ap.add_argument("--upstream", default="http://127.0.0.1:18008")
    ap.add_argument("--temperature", type=float, default=0.0)
    ap.add_argument("--timeout", type=int, default=600)
    ap.add_argument("--max-concurrent", type=int, default=4,
                    help="上游并发闸门；ssh -L 隧道场景建议 2-4")
    ap.add_argument("--log-file", default="")
    ARGS = ap.parse_args()
    UPSTREAM_SEM = threading.Semaphore(ARGS.max_concurrent)
    ThreadingHTTPServer(("127.0.0.1", ARGS.listen), Handler).serve_forever()


if __name__ == "__main__":
    main()
