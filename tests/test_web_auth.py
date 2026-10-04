import http.client
import json
import tempfile
import threading
import unittest
from unittest import mock

from web import auth, server


class AuthUnitTests(unittest.TestCase):
    def test_hash_roundtrip(self):
        h = auth.hash_password("correct horse", n=2**10)
        self.assertTrue(auth.verify_password("correct horse", h))
        self.assertFalse(auth.verify_password("wrong", h))
        self.assertNotIn("$", h)

    def test_verify_rejects_garbage(self):
        self.assertFalse(auth.verify_password("x", ""))
        self.assertFalse(auth.verify_password("x", "plain-text"))

    def test_throttle_locks_after_max_fails_and_ok_resets(self):
        t = auth.Throttle()
        for _ in range(auth.MAX_FAILS - 1):
            t.fail("1.1.1.1")
        self.assertTrue(t.allowed("1.1.1.1"))
        t.fail("1.1.1.1")
        self.assertFalse(t.allowed("1.1.1.1"))
        self.assertTrue(t.allowed("2.2.2.2"))
        t.ok("1.1.1.1")
        self.assertTrue(t.allowed("1.1.1.1"))

    def test_session_expiry(self):
        s = auth.Sessions()
        tok = s.new()
        self.assertTrue(s.valid(tok))
        s._tokens[tok] = 0
        self.assertFalse(s.valid(tok))
        self.assertFalse(s.valid(None))


class HttpTests(unittest.TestCase):
    """真起一个服务，走完 未登录 → 登录 → 带 cookie 访问 → 限速。"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        patches = [
            mock.patch.object(server, "LOGS", __import__("pathlib").Path(self.tmp.name)),
            mock.patch.dict("os.environ", {"DASH_PASSWORD_HASH": auth.hash_password("secret-pw", n=2**10)}),
            mock.patch.object(server, "sessions", auth.Sessions()),
            mock.patch.object(server, "throttle", auth.Throttle()),
            mock.patch("web.server.time.sleep"),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        self.srv = server.Server(("127.0.0.1", 0), server.Handler)
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.addCleanup(self.srv.server_close)
        self.addCleanup(self.srv.shutdown)

    def call(self, method, path, body=None, cookie=None):
        c = http.client.HTTPConnection("127.0.0.1", self.srv.server_address[1], timeout=5)
        headers = {"Content-Type": "application/json"}
        if cookie:
            headers["Cookie"] = cookie
        c.request(method, path, json.dumps(body) if body is not None else None, headers)
        r = c.getresponse()
        return r.status, r.getheader("Set-Cookie"), r.read()

    def test_api_requires_login_but_shell_is_public(self):
        self.assertEqual(self.call("GET", "/api/summary")[0], 401)
        self.assertEqual(self.call("GET", "/api/runs")[0], 401)
        self.assertEqual(self.call("POST", "/api/run", {})[0], 401)
        self.assertEqual(self.call("GET", "/")[0], 200)

    def test_login_flow(self):
        self.assertEqual(self.call("POST", "/api/login", {"password": "nope"})[0], 401)
        status, set_cookie, _ = self.call("POST", "/api/login", {"password": "secret-pw"})
        self.assertEqual(status, 200)
        self.assertIn("HttpOnly", set_cookie)
        self.assertIn("SameSite=Strict", set_cookie)
        cookie = set_cookie.split(";")[0]
        self.assertEqual(self.call("GET", "/api/summary", cookie=cookie)[0], 200)
        self.call("POST", "/api/logout", {}, cookie=cookie)
        self.assertEqual(self.call("GET", "/api/summary", cookie=cookie)[0], 401)

    def test_bruteforce_is_locked_out(self):
        for _ in range(auth.MAX_FAILS):
            self.assertEqual(self.call("POST", "/api/login", {"password": "x"})[0], 401)
        self.assertEqual(self.call("POST", "/api/login", {"password": "secret-pw"})[0], 429)

    def test_static_traversal_blocked(self):
        self.assertEqual(self.call("GET", "/../server.py")[0], 404)
        self.assertEqual(self.call("GET", "/%2e%2e/server.py")[0], 404)


class TlsTests(unittest.TestCase):
    def test_self_signed_https_roundtrip(self):
        import ssl

        from web.tls import make_context

        with tempfile.TemporaryDirectory() as d:
            ctx = make_context(d, "127.0.0.1")
            self.assertTrue((__import__("pathlib").Path(d) / "cert.pem").exists())
            self.assertIs(make_context(d, "127.0.0.1").__class__, ctx.__class__)  # 第二次复用已有证书
            with mock.patch.object(server.Handler, "ssl_ctx", ctx),                     mock.patch.dict("os.environ", {"DASH_PASSWORD_HASH": ""}),                     mock.patch.object(server, "LOGS", __import__("pathlib").Path(d)):
                srv = server.Server(("127.0.0.1", 0), server.Handler)
                threading.Thread(target=srv.serve_forever, daemon=True).start()
                try:
                    client = ssl.create_default_context()
                    client.check_hostname = False
                    client.verify_mode = ssl.CERT_NONE
                    c = http.client.HTTPSConnection("127.0.0.1", srv.server_address[1], context=client, timeout=5)
                    c.request("GET", "/")
                    self.assertEqual(c.getresponse().status, 200)
                finally:
                    srv.shutdown()
                    srv.server_close()


if __name__ == "__main__":
    unittest.main()
