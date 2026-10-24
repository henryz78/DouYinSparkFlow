"""陪聊平时只读列表、有动静才切会话。不联系真实好友。"""
import threading
import time
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
        """每个周期列表里的最后一条消息依次为 descs（字符串，或带 lastKey/lastFromMe 的字典）；返回 im，用来数切换会话的次数。"""
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
                d = descs[max(min(cycle["n"], len(descs)) - 1, 0)]
                row = {"convId": "a", "desc": "hi", "unread": None}
                row.update(d if isinstance(d, dict) else {"desc": d})
                return [row]
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

    def test_same_text_but_new_message_id_triggers_a_read(self):
        # 文字完全一样的重复消息，靠消息 id 分辨
        same = lambda k: {"desc": "[图片]", "lastKey": k}
        im = self.run_cycles([same("1"), same("1"), same("1"), same("2"), same("2")])
        self.assertEqual(im.select_conversation.call_count, 3)

    def test_unchanged_message_id_is_never_swept(self):
        same = {"desc": "hi", "lastKey": "1"}
        im = self.run_cycles([same] * 8)
        self.assertEqual(im.select_conversation.call_count, 2)

    def test_own_last_message_is_not_read(self):
        # 最后一条是自己发的（机器人回复或手动回复）：只记下，不点开
        im = self.run_cycles([{"desc": "a", "lastKey": "1"}, {"desc": "a", "lastKey": "1"},
                              {"desc": "b", "lastKey": "2", "lastFromMe": True},
                              {"desc": "b", "lastKey": "2", "lastFromMe": True}])
        self.assertEqual(im.select_conversation.call_count, 2)


class BlockedUntilTests(unittest.TestCase):
    def test_cooldown_and_backoff_report_when_to_retry(self):
        from core.ai.engine import PendingReply, ReplyEngine
        engine = ReplyEngine(AIConfig(cooldown=15))
        self.assertEqual(engine.blocked_until("c"), 0)
        pending = PendingReply("c", ("1",), "x", 0)
        engine.commit(pending, "ok", now=1000)
        self.assertEqual(engine.blocked_until("c"), 1015)
        engine.failed(pending, now=1100)
        self.assertEqual(engine.blocked_until("c"), 1160)


class EchoTests(unittest.TestCase):
    def test_echo_detection(self):
        from core.ai.engine import echoes, split_reply, reply_items
        self.assertEqual(split_reply("笑死我了[笑哭]"), ["笑死我了", "[笑哭]"])
        self.assertEqual(split_reply("[捂脸]好惨 哎"), ["好惨", "哎", "[捂脸]"])
        from core.ai.config import AIConfig
        from core.ai.engine import ReplyEngine
        eng = ReplyEngine(AIConfig())
        eng.history["c"] = [{"role": "user", "content": "哭了[流泪]"}, {"role": "assistant", "content": "抱抱"}]
        self.assertEqual(eng.dedupe_emoji("c", "笑死 [笑哭]"), "笑死 [笑哭]")  # 只有对方发过，不影响
        eng.history["c"].append({"role": "assistant", "content": "哈哈 [捂脸]"})
        self.assertEqual(eng.dedupe_emoji("c", "笑死 [笑哭]"), "笑死 ")  # 我们发过，就去掉
        self.assertEqual(eng.dedupe_emoji("other", "笑死 [笑哭]"), "笑死 [笑哭]")
        from core.ai import runner
        codes = []
        def fake_exit(code):
            codes.append(code)
            raise SystemExit
        runner.HEARTBEAT.clear()
        runner.HEARTBEAT["ok"] = time.monotonic()
        runner.HEARTBEAT["stuck"] = time.monotonic() - runner.HANG_SECONDS - 1
        with self.assertRaises(SystemExit):
            runner.watch_heartbeat(interval=0, exit=fake_exit)
        runner.HEARTBEAT.clear()
        self.assertEqual(codes, [3])
        names = ("笑死", "麻了")
        self.assertEqual(reply_items("哈哈 [表情:笑死]", names), [("text", "哈哈"), ("sticker", "笑死")])
        self.assertEqual(reply_items("[表情: 麻了] 好惨 哈", names), [("text", "好惨"), ("text", "哈"), ("sticker", "麻了")])
        self.assertEqual(reply_items("哈哈[表情:不存在]", names), [("text", "哈哈")])
        self.assertEqual(reply_items("[表情:笑死][表情:麻了]", names), [("sticker", "笑死")])
        self.assertEqual(reply_items("[表情:笑死]", ()), [])
        self.assertEqual(split_reply("a b  c"), ["a", "b", "c"])
        # 英文词前后的空格不算断句，和两边的中文连成一句
        self.assertEqual(split_reply("拿我测试 这 Henry 挺会安排人呢"), ["拿我测试", "这 Henry 挺会安排人呢"])
        self.assertEqual(split_reply("拿我测试这 Henry 挺会安排人呢"), ["拿我测试这 Henry 挺会安排人呢"])
        self.assertEqual(split_reply("你好 ok"), ["你好 ok"])
        self.assertEqual(split_reply("行 iPhone 15 太贵了 哎"), ["行 iPhone 15 太贵了", "哎"])
        # 文字超过条数上限时，小表情仍然单独排在最后
        self.assertEqual(split_reply("一 二 三 四 五 六 七 [笑哭]"), ["一", "二", "三", "四", "五 六 七", "[笑哭]"])
        self.assertEqual(split_reply("哈哈 [笑哭] 真的 [捂脸]"), ["哈哈", "真的", "[笑哭]"])
        self.assertEqual(split_reply("一二三"), ["一二三"])
        self.assertEqual(split_reply("1 2 3 4 5 6 7", limit=3), ["1", "2", "3 4 5 6 7"])
        self.assertTrue(echoes("这个ai好废物啊", "这个ai好废物啊"))
        self.assertTrue(echoes("zai", "zai"))
        self.assertTrue(echoes("henry是傻逼。", "我说\nhenry是傻逼"))  # 搬回对方其中一句
        self.assertFalse(echoes("好好学", "自习"))
        self.assertFalse(echoes("好", "好好学习"))  # 太短的不算复述
        self.assertFalse(echoes("别闹", "你说henry是傻逼"))


class PersonaTests(unittest.TestCase):
    def config(self):
        return AIConfig.from_value({
            "providers": [{"id": "p", "name": "P", "kind": "deepseek", "base_url": "https://x.test", "model": "m", "api_key": "k"}],
            "active_provider": "p", "system_prompt": "规则",
            "personas": [{"name": "损友", "prompt": "爱吐槽"}, {"name": "温柔", "prompt": "说话软"}],
            "default_persona": "损友"})

    def test_friend_persona_falls_back_to_default_then_nothing(self):
        c = self.config()
        self.assertEqual(c.persona_prompt("温柔"), "说话软")
        self.assertEqual(c.persona_prompt(None), "爱吐槽")
        self.assertEqual(c.persona_prompt("已删除的"), "爱吐槽")
        c.default_persona = ""
        self.assertEqual(c.persona_prompt("已删除的"), "")

    def test_persona_goes_into_that_conversations_prompt_only(self):
        from core.ai.engine import PendingReply, ReplyEngine
        engine = ReplyEngine(self.config())
        engine.personas["a"] = "说话软"
        mine = engine.messages(PendingReply("a", ("1",), "在吗", 0))[0]["content"]
        other = engine.messages(PendingReply("b", ("2",), "在吗", 0))[0]["content"]
        self.assertTrue(mine.startswith("规则") and "说话软" in mine)
        self.assertNotIn("说话软", other)

    def test_runner_gives_each_friend_the_chosen_persona(self):
        from core.ai.runner import matches
        from core.douyin_im import norm
        account = Account(unique_id="u", ai_targets=["Ken", "Amy"], ai_personas={"Ken": "温柔"})
        c = self.config()
        hit = {"conv_id": "1", "remark": "Ken", "title": "Ken"}
        self.assertTrue(matches(hit, norm("Ken")))
        chosen = {norm(k): v for k, v in account.ai_personas.items()}
        self.assertEqual(c.persona_prompt(chosen.get(norm("Ken"))), "说话软")
        self.assertEqual(c.persona_prompt(chosen.get(norm("Amy"))), "爱吐槽")
        self.assertEqual(account.to_task()["ai_personas"], {"Ken": "温柔"})

    def test_bad_personas_are_rejected(self):
        for bad in ([{"name": "", "prompt": "x"}], [{"name": "a", "prompt": "x"}] * 2, "no"):
            with self.assertRaises(ValueError):
                AIConfig.from_value({"personas": bad})


if __name__ == "__main__":
    unittest.main()
