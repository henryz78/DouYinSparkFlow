"""陪聊平时只读列表、有动静才切会话。不联系真实好友。"""
import threading
import unittest
from unittest.mock import MagicMock, patch

from app.config.models import Account, Config
from core.ai.config import AIConfig, ProviderConfig
from core.ai.runner import passive_rows, run_account
from core.douyin_im import JS_COLLECT, JS_LOGIN_DOM


class PassiveRowsTests(unittest.TestCase):
    def test_unreadable_list_falls_back(self):
        page = MagicMock()
        page.evaluate.return_value = {"not": "a list"}
        self.assertIsNone(passive_rows(page))
        page.evaluate.side_effect = RuntimeError("x")
        self.assertIsNone(passive_rows(page))
        page.evaluate.side_effect = None
        page.evaluate.return_value = [{"convId": "a", "desc": "hi"}]
        self.assertEqual(passive_rows(page)["a"]["desc"], "hi")


class RunnerTests(unittest.TestCase):
    def run_cycles(self, descs):
        """每个周期列表里的最后一条消息依次为 descs；返回 im，用来数切换会话的次数。"""
        stop = threading.Event()
        cycle = {"n": 0}
        page = MagicMock()

        def evaluate(arg, *a):
            if arg == JS_LOGIN_DOM:
                cycle["n"] += 1
                if cycle["n"] > len(descs):
                    stop.set()
                return {"hasChatRoot": True, "loginVisible": False}
            if arg == JS_COLLECT:
                i = min(cycle["n"], len(descs)) - 1
                return [{"convId": "a", "desc": descs[max(i, 0)], "unread": None}]
        page.evaluate.side_effect = evaluate
        im = MagicMock(ready=True, last_scan={"scanned_all": True})
        im.wait_ready.return_value = {"status": "READY"}
        im.iter_conversations.return_value = [{"conv_id": "a", "display": "好友", "title": "好友", "is_group": False}]
        im.read_chat_messages.return_value = []
        with patch("cloakbrowser.launch") as launch, patch("core.ai.runner.DouyinIM", return_value=im), \
                patch("core.ai.runner.create_provider", return_value=MagicMock()):
            launch.return_value.new_context.return_value.new_page.return_value = page
            account = Account(username="t", cookies="[]", ai_targets=["好友"])
            conf = Config(ai_chat=AIConfig(providers=[ProviderConfig(api_key="k")], cooldown=0, poll_interval=2))
            run_account(account, conf.ai_chat, conf, stop, lambda *_: None)
        return im

    def test_idle_list_does_not_switch_conversations(self):
        im = self.run_cycles(["hi"] * 6)
        # 开头初始化 1 次 + 第一轮（还没记录过最后一条消息）1 次，之后列表没变化就不再切
        self.assertEqual(im.select_conversation.call_count, 2)

    def test_changed_last_message_triggers_a_read(self):
        im = self.run_cycles(["hi", "hi", "hi", "新消息", "新消息"])
        self.assertEqual(im.select_conversation.call_count, 3)


if __name__ == "__main__":
    unittest.main()
