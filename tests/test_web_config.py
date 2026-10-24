import json
import tempfile
import unittest
from pathlib import Path

from dotenv import dotenv_values

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

    def test_page_is_described_by_data(self):
        data = config_edit.read(self.env)
        groups = {g["id"] for g in data["groups"]}
        self.assertTrue(groups >= {"time", "content", "advanced"})
        self.assertTrue(all(f["group"] in groups for f in data["fields"]))  # 每个字段都有分组
        by = {f["key"]: f for f in data["fields"]}
        self.assertEqual((by["CRON_RANDOM_WINDOW_SECONDS"]["scale"], by["CRON_RANDOM_WINDOW_SECONDS"]["unit"]), (60, "分钟"))
        self.assertEqual(by["MESSAGE_TEMPLATE"]["widget"], "textarea")
        self.assertEqual({by[k]["row"] for k in ("CRON_HOUR", "CRON_MINUTE", "CRON_SECOND")}, {"hms"})
        self.assertNotIn("default", by["CRON_HOUR"])

    def test_advanced_fields_have_defaults_and_validate(self):
        data = config_edit.read(self.env)
        val = {f["key"]: f["value"] for f in data["fields"]}
        self.assertEqual((val["LOG_LEVEL"], val["TASK_RETRY_TIMES"], val["IM_MAX_STEPS"]), ("Debug", "3", "200"))
        v = config_edit.validate
        self.assertEqual(v({"LOG_LEVEL": "Info", "IM_SCAN_TIMEOUT": 300, "TASK_RETRY_TIMES": 0}, {}), {})
        self.assertIn("LOG_LEVEL", v({"LOG_LEVEL": "Verbose"}, {}))
        self.assertIn("IM_MAX_STEPS", v({"IM_MAX_STEPS": 5}, {}))
        self.assertIn("BROWSER_ACTION_TIMEOUT", v({"BROWSER_ACTION_TIMEOUT": 601}, {}))

    def test_read_defaults_and_accounts(self):
        data = config_edit.read(self.env)
        val = {f["key"]: f["value"] for f in data["fields"]}
        self.assertEqual((val["CRON_HOUR"], val["DELIVERY_MODE"]), ("08", "text"))
        self.assertEqual(data["accounts"], [{"id": 0, "name": "海阔山遥", "targets": ["Rick", "Ken"], "chat": []}])
        self.assertEqual(data["ai"], {"enabled": True, "default_persona": "", "personas": []})

    def test_ai_settings_save_keep_api_key_and_never_leak_it(self):
        env = self.env.read_text(encoding="utf-8") + 'AI_CHAT={"providers":[{"id":"p","name":"P","kind":"deepseek","base_url":"https://x.test","model":"m","api_key":"APIKEY123"}],"active_provider":"p","system_prompt":"规则","context_turns":4}\n'
        self.env.write_text(env, encoding="utf-8")
        self.assertNotIn("APIKEY123", json.dumps(config_edit.read(self.env), ensure_ascii=False))
        ai = {"enabled": False, "default_persona": "损友",
              "personas": [{"name": "损友", "prompt": "爱吐槽"}, {"name": "温柔", "prompt": "说话软"}],
              "friends": {"0": [{"name": " Ken ", "persona": "温柔"}, {"name": "Amy", "persona": ""}]}}
        self.assertEqual(config_edit.validate({}, {}, ai), {})
        config_edit.save(self.env, {}, {}, self.dir / "env.bak", ai)
        saved = dotenv_values(self.env)
        chat = json.loads(saved["AI_CHAT"])
        self.assertEqual((chat["enabled"], chat["default_persona"], len(chat["personas"])), (False, "损友", 2))
        self.assertEqual((chat["providers"][0]["api_key"], chat["context_turns"], chat["system_prompt"]), ("APIKEY123", 4, "规则"))
        task = json.loads(saved["TASKS"])[0]
        self.assertEqual((task["ai_targets"], task["ai_personas"], task["targets"]), (["Ken", "Amy"], {"Ken": "温柔"}, ["Rick", "Ken"]))
        back = config_edit.read(self.env)
        self.assertEqual(back["accounts"][0]["chat"], [{"name": "Ken", "persona": "温柔"}, {"name": "Amy", "persona": ""}])
        self.assertFalse(back["ai"]["enabled"])

    def test_ai_settings_are_validated(self):
        ok = {"enabled": True, "default_persona": "", "personas": [{"name": "甲", "prompt": "x"}], "friends": {"0": []}}
        v = config_edit.validate
        self.assertEqual(v({}, {}, ok), {})
        self.assertIn("ai-enabled", v({}, {}, {**ok, "enabled": "yes"}))
        self.assertIn("ai-personas", v({}, {}, {**ok, "default_persona": "不存在"}))
        self.assertIn("ai-personas", v({}, {}, {**ok, "personas": [{"name": "甲", "prompt": "x"}, {"name": "甲", "prompt": "y"}]}))
        self.assertIn("ai-personas", v({}, {}, {**ok, "personas": [{"name": "", "prompt": "x"}]}))
        self.assertIn("ai-friends-0", v({}, {}, {**ok, "friends": {"0": [{"name": "", "persona": ""}]}}))
        self.assertIn("ai-friends-0", v({}, {}, {**ok, "friends": {"0": [{"name": "A", "persona": "没有"}]}}))

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
