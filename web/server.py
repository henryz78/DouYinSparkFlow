"""个人控制台：python -m web.server。

纯标准库，和 fc_server.py 一样不引入框架。
监听非本机地址时必须设 DASH_PASSWORD_HASH（见 web/passwd.py）并走 HTTPS。
"""

import json
import os
import time
from datetime import datetime
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from dotenv import dotenv_values

from web import auth, config_edit, runner
from web.stats import load_runs, summary

ROOT = Path(__file__).resolve().parent.parent
STATIC = Path(__file__).resolve().parent / "static"
LOGS = Path(os.getenv("DASH_LOGS_DIR") or ROOT / "logs")
ENV_FILE = Path(os.getenv("DASH_ENV_FILE") or ROOT / ".env")
STARTED = time.time()
TYPES = {".html": "text/html", ".css": "text/css", ".js": "text/javascript"}
CSP = ("default-src 'self'; style-src 'self' https://fonts.googleapis.com; "
       "font-src https://fonts.gstatic.com; frame-ancestors 'none'")

sessions = auth.Sessions()
throttle = auth.Throttle()
TLS = False  # serve() 里按是否启用 HTTPS 设置，决定 cookie 是否带 Secure


def cfg(name, default=""):
    """读 .env（保存配置后立刻生效，不用重启）；没有就退回进程环境变量。"""
    return dotenv_values(ENV_FILE).get(name) or os.getenv(name) or default


def cfg_int(name, default):
    try:
        return int(cfg(name, default))
    except ValueError:
        return default


def version():
    try:
        return (ROOT / "VERSION").read_text(encoding="utf-8").strip()
    except OSError:
        return os.getenv("IMAGE_VERSION", "")


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


class Server(ThreadingHTTPServer):
    daemon_threads = True

    def handle_error(self, request, client_address):
        pass  # 端口扫描/握手失败很常见，不往日志里刷堆栈


class Handler(BaseHTTPRequestHandler):
    ssl_ctx = None
    timeout = 30

    def setup(self):
        # TLS 握手放在每个连接自己的线程里做，卡住的客户端不会堵住 accept
        if self.ssl_ctx:
            self.request.settimeout(10)
            self.request = self.ssl_ctx.wrap_socket(self.request, server_side=True)
        super().setup()

    def _send(self, code, body, ctype, headers=()):
        data = body if isinstance(body, bytes) else body.encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype + "; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Security-Policy", CSP)
        for k, v in headers:
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(data)

    def _json(self, obj, code=200, headers=()):
        self._send(code, json.dumps(obj, ensure_ascii=False), "application/json", headers)

    def _token(self):
        c = SimpleCookie(self.headers.get("Cookie", ""))
        return c["session"].value if "session" in c else None

    def _authed(self):
        return not cfg("DASH_PASSWORD_HASH") or sessions.valid(self._token())

    def _body(self):
        try:
            n = int(self.headers.get("Content-Length") or 0)
            return json.loads(self.rfile.read(min(n, 65536)) or b"{}")
        except ValueError:
            return {}

    def do_POST(self):
        path = urlparse(self.path).path
        body = self._body()
        ip = self.client_address[0]
        if path == "/api/login":
            if not throttle.allowed(ip):
                return self._json({"error": "尝试次数过多，请 15 分钟后再试"}, 429)
            if auth.verify_password(str(body.get("password", "")), cfg("DASH_PASSWORD_HASH")):
                throttle.ok(ip)
                cookie = f"session={sessions.new()}; HttpOnly; SameSite=Strict; Path=/; Max-Age={auth.SESSION_TTL}"
                return self._json({"ok": True}, headers=[("Set-Cookie", cookie + ("; Secure" if TLS else ""))])
            time.sleep(1)  # 拖慢暴力尝试
            throttle.fail(ip)
            return self._json({"error": "密码不对"}, 401)
        if not self._authed():
            return self._json({"error": "未登录"}, 401)
        if path == "/api/logout":
            sessions.drop(self._token())
            return self._json({"ok": True}, headers=[("Set-Cookie", "session=; Max-Age=0; Path=/")])
        if path == "/api/run":
            if runner.start(LOGS / "manual-run.log"):
                return self._json({"ok": True})
            return self._json({"error": "已有任务在运行，或当前环境不支持手动运行"}, 409)
        if path == "/api/config":
            return self._save_config(body)
        self._json({"error": "not found"}, 404)

    def _save_config(self, body):
        values = body.get("values") if isinstance(body.get("values"), dict) else {}
        raw = body.get("targets") if isinstance(body.get("targets"), dict) else {}
        targets = dict(raw)
        errors = config_edit.validate(values, targets)
        known = {str(a["id"]) for a in config_edit.read(ENV_FILE)["accounts"]}
        errors.update({f"account-{k}": "没有这个账号" for k in targets if k not in known})
        if errors:
            return self._json({"errors": errors}, 400)
        if not ENV_FILE.exists():
            return self._json({"error": "找不到配置文件"}, 500)
        config_edit.save(ENV_FILE, values, targets, LOGS / "env.bak")
        ok, message = config_edit.apply()
        self._json({"ok": ok, "message": message})

    def do_GET(self):
        url = urlparse(self.path)
        q = parse_qs(url.query)

        def num(key, default, hi):
            try:
                return max(1, min(int(q[key][0]), hi))
            except (KeyError, ValueError):
                return default

        if url.path.startswith("/api/"):
            if not self._authed():
                return self._json({"error": "未登录"}, 401)
            if url.path == "/api/summary":
                out = summary(
                    load_runs(LOGS / "runs.jsonl"), datetime.now().astimezone(),
                    cfg_int("CRON_HOUR", 8), cfg_int("CRON_MINUTE", 0),
                    cfg_int("CRON_SECOND", 0), cfg_int("CRON_RANDOM_WINDOW_SECONDS", 0),
                )
                # 控制台和任务在同一个容器里，进程运行多久 ≈ 容器运行多久
                out["health"]["uptime"] = int(time.time() - STARTED)
                out["health"]["version"] = version()
                out["running"] = runner.is_running()
                return self._json(out)
            if url.path == "/api/config":
                return self._json(config_edit.read(ENV_FILE))
            if url.path == "/api/runs":
                return self._json(load_runs(LOGS / "runs.jsonl")[::-1][: num("limit", 100, 1000)])
            if url.path == "/api/logs":
                return self._json(tail(LOGS / "app.log", num("lines", 300, 2000)))
            return self._json({"error": "not found"}, 404)

        name = "index.html" if url.path == "/" else url.path.lstrip("/")
        f = STATIC / name
        if "/" in name or not f.is_file():
            self._send(404, "not found", "text/plain")
        else:
            self._send(200, f.read_bytes(), TYPES.get(f.suffix, "application/octet-stream"))

    def log_message(self, *a):
        pass


def serve():
    global TLS
    host = cfg("DASH_HOST", "127.0.0.1")
    port = int(cfg("DASH_PORT", 8080))
    local = host in ("127.0.0.1", "localhost", "::1")
    if not local and not cfg("DASH_PASSWORD_HASH"):
        raise SystemExit("控制台监听公网地址必须先设 DASH_PASSWORD_HASH（python -m web.passwd 生成）")
    server = Server((host, port), Handler)
    TLS = cfg("DASH_TLS", "0" if local else "1") == "1"
    if TLS:
        from web.tls import make_context

        Handler.ssl_ctx = make_context(LOGS / "dashboard-tls", cfg("DASH_CERT_IP"))
    print(f"控制台 {'https' if TLS else 'http'}://{host}:{port}")
    server.serve_forever()


if __name__ == "__main__":
    serve()
