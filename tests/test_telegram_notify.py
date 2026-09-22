import json
import unittest
from unittest.mock import Mock, patch

from core.telegram_notify import TelegramNotifier


def _config(**overrides):
    config = {
        "telegramEnabled": True,
        "telegramBotToken": "bot-token",
        "telegramChatId": "chat-id",
        "telegramNotifySuccess": True,
        "telegramNotifyFailure": True,
        "telegramNotifyTest": False,
        "timezone": "UTC",
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


class TelegramNotifierTests(unittest.TestCase):
    def test_disabled_notification_does_not_call_telegram(self):
        notifier = TelegramNotifier(_config(telegramEnabled=False))
        with patch("core.telegram_notify.urllib.request.urlopen") as urlopen:
            self.assertFalse(notifier.notify_success("account", ["Rick"]))
        urlopen.assert_not_called()

    def test_success_posts_one_plain_text_message(self):
        notifier = TelegramNotifier(_config())
        with patch(
            "core.telegram_notify.urllib.request.urlopen", return_value=_Response()
        ) as urlopen:
            self.assertTrue(
                notifier.notify_success("account", ["Rick", "Ken"], "native_sticker")
            )

        request = urlopen.call_args.args[0]
        payload = json.loads(request.data.decode("utf-8"))
        self.assertEqual(payload["chat_id"], "chat-id")
        self.assertIn("原生贴纸", payload["text"])
        self.assertIn("Rick、Ken", payload["text"])
        self.assertNotIn("bot-token", payload["text"])

    def test_failure_contains_reason_and_does_not_raise_on_http_error(self):
        logger = Mock()
        notifier = TelegramNotifier(_config(), logger=logger)
        error = __import__("urllib.error", fromlist=["HTTPError"]).HTTPError(
            "https://api.telegram.org", 500, "failed", {}, None
        )
        with patch("core.telegram_notify.urllib.request.urlopen", side_effect=error):
            self.assertFalse(
                notifier.notify_failure(
                    "account",
                    ["Rick", "Ken"],
                    "账号 account 任务未完成：发送成功=1/2；发送失败=1；attempted",
                )
            )
        logger.warning.assert_called_once()
        self.assertIn("HTTP 500", logger.warning.call_args.args[0])

    def test_test_modes_are_silent_by_default(self):
        notifier = TelegramNotifier(_config())
        with patch.object(notifier, "_post") as post:
            self.assertFalse(
                notifier.notify_failure("account", ["Rick"], "测试失败", test_mode=True)
            )
        post.assert_not_called()


if __name__ == "__main__":
    unittest.main()
