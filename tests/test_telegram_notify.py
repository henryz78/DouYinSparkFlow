import json
import unittest
from unittest.mock import Mock, patch

from core.telegram_notify import notify_account


def _config(**overrides):
    config = {
        "telegramEnabled": True,
        "telegramBotToken": "bot-token",
        "telegramChatId": "chat-id",
        "telegramNotifySuccess": True,
        "telegramNotifyFailure": True,
        "deliveryMode": "native_sticker",
        "nativeStickerName": "续火花",
    }
    config.update(overrides)
    return config


class _Response:
    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self):
        return b'{"ok":true}'


def _send(config, sent_ok, problems, targets=("Rick", "Ken")):
    with patch("core.telegram_notify.urllib.request.urlopen", return_value=_Response()) as urlopen:
        result = notify_account(config, Mock(), "account", list(targets), sent_ok, problems)
    return result, urlopen


class NotifyAccountTests(unittest.TestCase):
    def test_disabled_does_not_call_telegram(self):
        result, urlopen = _send(_config(telegramEnabled=False), 2, [])
        self.assertFalse(result)
        urlopen.assert_not_called()

    def test_success_message(self):
        result, urlopen = _send(_config(), 2, [])
        self.assertTrue(result)
        payload = json.loads(urlopen.call_args.args[0].data.decode("utf-8"))
        self.assertEqual(payload["chat_id"], "chat-id")
        self.assertIn("✅", payload["text"])
        self.assertIn("2/2 已发送", payload["text"])
        self.assertNotIn("bot-token", payload["text"])

    def test_partial_failure_is_flagged_with_problems(self):
        _, urlopen = _send(_config(), 1, ["发送失败：Ken"])
        text = json.loads(urlopen.call_args.args[0].data.decode("utf-8"))["text"]
        self.assertIn("⚠️", text)
        self.assertIn("发送失败：Ken", text)

    def test_unknown_count_after_exception(self):
        _, urlopen = _send(_config(), None, ["RuntimeError: boom"])
        text = json.loads(urlopen.call_args.args[0].data.decode("utf-8"))["text"]
        self.assertIn("❌", text)
        self.assertIn("数量未确定", text)

    def test_success_and_failure_switches(self):
        result, urlopen = _send(_config(telegramNotifySuccess=False), 2, [])
        self.assertFalse(result)
        urlopen.assert_not_called()
        result, urlopen = _send(_config(telegramNotifyFailure=False), 0, ["x"])
        self.assertFalse(result)
        urlopen.assert_not_called()

    def test_network_error_does_not_raise_and_redacts_token(self):
        logger = Mock()
        with patch("core.telegram_notify.urllib.request.urlopen", side_effect=OSError("fail bot-token")):
            self.assertFalse(notify_account(_config(), logger, "account", ["Rick"], 1, []))
        self.assertNotIn("bot-token", logger.warning.call_args.args[0])


if __name__ == "__main__":
    unittest.main()
