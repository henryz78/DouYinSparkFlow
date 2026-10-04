"""个人控制台（只读版）：python -m web.server，默认只监听 127.0.0.1:8080。

纯标准库，和 fc_server.py 一样不引入框架。登录/手动运行/配置在后续步骤加。
"""

import json
import os
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from web.stats import load_runs, summary

ROOT = Path(__file__).resolve().parent.parent
STATIC = Path(__file__).resolve().parent / "static"
LOGS = Path(os.getenv("DASH_LOGS_DIR") or ROOT / "logs")
TYPES = {".html": "text/html", ".css": "text/css", ".js": "text/javascript"}


def tail(path, n):
    # ponytail: 只读文件末尾 1MB，日志按 5MB 轮转，够看最近几百行；要看更早的再加翻页
    try:
        with open(path, "rb") as f:
            f.seek(0, 2)
            f.seek(max(0, f.tell() - 1_000_000))
            lines = f.read().decode("utf-8", "replace").splitlines()
    except FileNotFoundError:
        return []
    return lines[-n:]


def env_int(name, default):
    try:
        return int(os.getenv(name, default))
    except ValueError:
        return default


class Handler(BaseHTTPRequestHandler):
    def _send(self, code, body, ctype):
        data = body if isinstance(body, bytes) else body.encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype + "; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def _json(self, obj):
        self._send(200, json.dumps(obj, ensure_ascii=False), "application/json")

    def do_GET(self):
        url = urlparse(self.path)
        q = parse_qs(url.query)

        def num(key, default, hi):
            try:
                return max(1, min(int(q[key][0]), hi))
            except (KeyError, ValueError):
                return default

        if url.path == "/api/summary":
            rows = load_runs(LOGS / "runs.jsonl")
            self._json(summary(
                rows, datetime.now().astimezone(),
                env_int("CRON_HOUR", 8), env_int("CRON_MINUTE", 0),
                env_int("CRON_SECOND", 0), env_int("CRON_RANDOM_WINDOW_SECONDS", 0),
            ))
        elif url.path == "/api/runs":
            rows = load_runs(LOGS / "runs.jsonl")
            self._json(rows[::-1][: num("limit", 100, 1000)])
        elif url.path == "/api/logs":
            self._json(tail(LOGS / "app.log", num("lines", 300, 2000)))
        else:
            name = "index.html" if url.path == "/" else url.path.lstrip("/")
            f = STATIC / name
            if "/" in name or not f.is_file():
                self._send(404, "not found", "text/plain")
            else:
                self._send(200, f.read_bytes(), TYPES.get(f.suffix, "application/octet-stream"))

    def log_message(self, *a):
        pass


def serve():
    host = os.getenv("DASH_HOST", "127.0.0.1")
    port = env_int("DASH_PORT", 8080)
    print(f"控制台 http://{host}:{port}")
    ThreadingHTTPServer((host, port), Handler).serve_forever()


if __name__ == "__main__":
    serve()
