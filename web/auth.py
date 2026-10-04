"""单密码登录：scrypt 哈希、内存会话、按 IP 的失败限速。纯标准库。"""

import hashlib
import hmac
import secrets
import time

SESSION_TTL = 7 * 86400
MAX_FAILS = 5
LOCK_SECONDS = 15 * 60


def hash_password(password, salt=None, n=2**14):
    """返回 'scrypt:N:盐:哈希'；故意不用 $，免得被 .env/shell 当成变量展开。"""
    salt = salt or secrets.token_hex(16)
    digest = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt), n=n, r=8, p=1, dklen=32)
    return f"scrypt:{n}:{salt}:{digest.hex()}"


def verify_password(password, stored):
    try:
        scheme, n, salt, _ = stored.split(":")
        if scheme != "scrypt":
            return False
        return hmac.compare_digest(hash_password(password, salt, int(n)), stored)
    except (ValueError, AttributeError):
        return False


class Sessions:
    # ponytail: 会话只存内存，容器重启后要重新登录；单人使用够了
    def __init__(self):
        self._tokens = {}

    def new(self):
        token = secrets.token_urlsafe(32)
        self._tokens[token] = time.time() + SESSION_TTL
        return token

    def valid(self, token):
        exp = self._tokens.get(token or "")
        if exp and exp > time.time():
            return True
        self._tokens.pop(token or "", None)
        return False

    def drop(self, token):
        self._tokens.pop(token or "", None)


class Throttle:
    """同一 IP 连续输错 MAX_FAILS 次后锁 LOCK_SECONDS。"""

    def __init__(self):
        self._fails = {}  # ip -> (次数, 锁到什么时候)

    def allowed(self, ip):
        n, until = self._fails.get(ip, (0, 0))
        return until <= time.time()

    def fail(self, ip):
        n, until = self._fails.get(ip, (0, 0))
        if until and until <= time.time():
            n = 0  # 锁已过期，重新计数
        n += 1
        self._fails[ip] = (n, time.time() + LOCK_SECONDS if n >= MAX_FAILS else 0)

    def ok(self, ip):
        self._fails.pop(ip, None)
