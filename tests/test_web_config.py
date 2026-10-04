import json
import tempfile
import unittest
from pathlib import Path

from web import config_edit

TASKS = [{"username": "海阔山遥", "unique_id": "abc", "targets": ["Rick", "Ken"], "fingerprint": 44671}]
ENV = "\n".join([
    "# 注释保留",
    "CRON_HOUR=08",
    "CRON_RANDOM_WINDOW_SECONDS=7200",
    "COOKIES_ABC=[{\"name\":\"sessionid\",\"value\":\"SECRET\"}]",
    "TASKS=" + json.dumps(TASKS, ensure_ascii=False),
    "NOTIFY=[{\"type\":\"bark\",\"bark_url\":\"https://api.day.app/NOTIFYKEY\"}]",
    "",
])


class ConfigEditTests(unittest.TestCase):
    def setUp(self):
        d = tempfile.TemporaryDirectory()
        self.addCleanup(d.cleanup)
        self.dir = Path(d.name)
        self.env = self.dir / ".env"
        self.env.write_text(ENV, encoding="utf-8")

    def test_read_never_exposes_secrets(self):
        out = json.dumps(config_edit.read(self.env), ensure_ascii=False)
        self.assertNotIn("SECRET", out)
        self.assertNotIn("NOTIFYKEY", out)
        keys = {f["key"] for f in config_edit.read(self.env)["fields"]}
        self.assertFalse(keys & {"NOTIFY", "DASH_PASSWORD_HASH", "TASKS"})

    def test_read_defaults_and_accounts(self):
        data = config_edit.read(self.env)
        val = {f["key"]: f["value"] for f in data["fields"]}
        self.assertEqual((val["CRON_HOUR"], val["DELIVERY_MODE"]), ("08", "text"))
        self.assertEqual(data["accounts"], [{"id": 0, "name": "海阔山遥", "targets": ["Rick", "Ken"]}])

    def test_save_updates_only_given_keys_and_keeps_the_rest(self):
        config_edit.save(self.env, {"CRON_HOUR": 9, "DELIVERY_MODE": "native_sticker"}, {"0": ["Rick", " Peter "]}, self.dir / "bak" / "env.bak")
        text = self.env.read_text(encoding="utf-8")
        self.assertIn("# 注释保留", text)
        self.assertIn("CRON_HOUR=9\n", text)
        self.assertIn("DELIVERY_MODE=native_sticker", text)  # 原来没有这个键 → 追加
        self.assertIn("CRON_RANDOM_WINDOW_SECONDS=7200", text)
        self.assertIn("SECRET", text)
        self.assertIn("NOTIFYKEY", text)
        tasks = json.loads([l for l in text.splitlines() if l.startswith("TASKS=")][0][6:])
        self.assertEqual(tasks[0]["targets"], ["Rick", "Peter"])
        self.assertEqual((tasks[0]["unique_id"], tasks[0]["fingerprint"]), ("abc", 44671))  # 其余字段不动
        self.assertEqual((self.dir / "bak" / "env.bak").read_text(encoding="utf-8"), ENV)  # 备份是改之前的

    def test_save_keeps_crlf(self):
        self.env.write_bytes(ENV.replace("\n", "\r\n").encode())
        config_edit.save(self.env, {"CRON_HOUR": 7}, {}, self.dir / "env.bak")
        raw = self.env.read_bytes()
        self.assertIn(b"CRON_HOUR=7\r\n", raw)
        self.assertNotIn(b"\n", raw.replace(b"\r\n", b""))

    def test_validation(self):
        v = config_edit.validate
        self.assertEqual(v({"CRON_HOUR": 8, "DELIVERY_MODE": "text"}, {"0": ["a"]}), {})
        self.assertIn("CRON_HOUR", v({"CRON_HOUR": 24}, {}))
        self.assertIn("CRON_HOUR", v({"CRON_HOUR": "8"}, {}))
        self.assertIn("CRON_HOUR", v({"CRON_HOUR": True}, {}))
        self.assertIn("DELIVERY_MODE", v({"DELIVERY_MODE": "rm -rf"}, {}))
        self.assertIn("NATIVE_STICKER_NAME", v({"NATIVE_STICKER_NAME": "a#b"}, {}))
        self.assertIn("NOTIFY", v({"NOTIFY": "x"}, {}))  # 敏感项不可改
        self.assertIn("TASKS", v({"TASKS": "[]"}, {}))
        self.assertIn("account-0", v({}, {"0": ["ok", ""]}))
        self.assertIn("account-0", v({}, {"0": ["x"] * 51}))


if __name__ == "__main__":
    unittest.main()
