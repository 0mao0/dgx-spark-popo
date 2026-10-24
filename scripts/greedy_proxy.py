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
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ARGS = None
HOP_BY_HOP = {"host", "content-length", "connection", "transfer-encoding",
              "content-encoding", "keep-alive"}


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *a):
        pass

    def _proxy(self):
        length = int(self.headers.get("content-length", 0) or 0)
        body = self.rfile.read(length) if length else b""
        if (self.command == "POST"
                and self.path.rstrip("/").endswith("chat/completions") and body):
            try:
                b = json.loads(body)
                b["temperature"] = ARGS.temperature
                body = json.dumps(b).encode("utf-8")
            except Exception:
                pass
        url = ARGS.upstream.rstrip("/") + self.path
        req = urllib.request.Request(url, data=body if body else None, method=self.command)
        for k, v in self.headers.items():
            if k.lower() not in HOP_BY_HOP:
                req.add_header(k, v)
        try:
            with urllib.request.urlopen(req, timeout=ARGS.timeout) as resp:
                payload, status, headers = resp.read(), resp.status, dict(resp.headers)
        except urllib.error.HTTPError as e:
            payload, status, headers = e.read(), e.code, dict(e.headers)
        except Exception as exc:
            payload = json.dumps({"error": {"message": f"proxy error: {exc}"}},
                                 ensure_ascii=False).encode("utf-8")
            status, headers = 502, {"Content-Type": "application/json"}

        self.send_response(status)
        for k, v in headers.items():
            if k.lower() not in HOP_BY_HOP:
                self.send_header(k, v)
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    do_GET = do_POST = do_PUT = do_DELETE = do_PATCH = do_OPTIONS = _proxy


def main():
    global ARGS
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--listen", type=int, default=18009)
    ap.add_argument("--upstream", default="http://127.0.0.1:18008")
    ap.add_argument("--temperature", type=float, default=0.0)
    ap.add_argument("--timeout", type=int, default=600)
    ARGS = ap.parse_args()
    ThreadingHTTPServer(("127.0.0.1", ARGS.listen), Handler).serve_forever()


if __name__ == "__main__":
    main()
