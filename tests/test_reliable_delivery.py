import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from core import reliable_delivery as delivery


class _Editor:
    def __init__(self):
        self.text = ""
        self.actions = []

    def inner_text(self):
        return self.text

    def focus(self):
        return None

    def type(self, text, force=False):
        self.actions.append(("type", text, force))
        self.text += text

    def press(self, key, force=False):
        self.actions.append(("press", key, force))
        if key == "Shift+Enter":
            self.text += "\n"


class _Locator:
    def __init__(self, editor):
        self.first = editor


class _Keyboard:
    def __init__(self, editor):
        self.editor = editor
        self.inserted = []

    def press(self, key):
        if key == "Backspace":
            self.editor.text = ""

    def insert_text(self, text):
        self.inserted.append(text)
        self.editor.actions.append(("insert_text", text))
        self.editor.text += text


class _Page:
    def __init__(self):
        self.editor = _Editor()
        self.keyboard = _Keyboard(self.editor)

    def wait_for_selector(self, *args, **kwargs):
        return None

    def locator(self, selector):
        return _Locator(self.editor)


class ReliableDeliveryTests(unittest.TestCase):
    def test_input_preserves_native_emoji_shortcodes_and_newlines(self):
        page = _Page()
        with patch.object(delivery, "human_pause"):
            delivery._type_message(
                page,
                "account",
                "Ken",
                "[盖瑞]今日火花[加一]\\n—— [右边] 每日一言 [左边] ——\\n正文",
                {"browserTimeout": 1000},
            )
        self.assertEqual(
            page.editor.text,
            "[盖瑞]今日火花[加一]\n—— [右边] 每日一言 [左边] ——\n正文",
        )
        self.assertEqual(
            page.keyboard.inserted,
            [
                "[盖瑞]", "今", "日", "火", "花", "[加一]",
                "—", "—", " ", "[右边]", " ", "每", "日", "一", "言", " ",
                "[左边]", " ", "—", "—", "正", "文",
            ],
        )
        self.assertEqual(
            [action for action in page.editor.actions if action[0] == "press"],
            [("press", "Shift+Enter", True), ("press", "Shift+Enter", True)],
        )

    def test_message_input_tokens_only_make_shortcodes_atomic(self):
        self.assertEqual(
            delivery._message_input_tokens("普通文字[盖瑞]继续\\n下一行"),
            [
                ("text", "普通文字"),
                ("shortcode", "[盖瑞]"),
                ("text", "继续"),
                ("newline", "\n"),
                ("text", "下一行"),
            ],
        )

    def test_human_insert_text_preserves_ascii_spaces_and_shift_symbols(self):
        page = _Page()
        with patch.object(delivery, "human_pause"):
            delivery._human_insert_text(page, "中文 ABC (括号) 123 OK")
        self.assertEqual(page.editor.text, "中文 ABC (括号) 123 OK")

    def test_outgoing_match_ignores_whitespace_only_differences(self):
        class Messages:
            def all_inner_texts(self):
                return ["今日火花\n—— \n 每日一言 \n ——且壮士不死则已"]

        class Page:
            def locator(self, selector):
                return Messages()

        self.assertEqual(
            delivery._outgoing_match_count(
                Page(), "今日火花 —— 每日一言 —— 且壮士不死则已"
            ),
            1,
        )

    def test_outgoing_match_still_requires_same_non_whitespace_text(self):
        class Messages:
            def all_inner_texts(self):
                return ["今日火花\n——\n每日一言\n——完全不同的正文"]

        class Page:
            def locator(self, selector):
                return Messages()

        self.assertEqual(
            delivery._outgoing_match_count(
                Page(), "今日火花 —— 每日一言 —— 正确正文"
            ),
            0,
        )

    def test_state_keeps_thirty_days(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "state.json"
            state = {"version": 1, "days": {f"2026-08-{day:02d}": {} for day in range(1, 32)}}
            with patch.dict("os.environ", {"SEND_STATE_FILE": str(path)}):
                delivery.save_state(state)
                saved = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(len(saved["days"]), 30)

    def test_attempted_record_is_not_automatically_resent(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "state.json"
            day = delivery._today()
            path.write_text(
                json.dumps(
                    {
                        "version": 1,
                        "days": {
                            day: {
                                "account": {
                                    "Ken": {
                                        "status": "attempted",
                                        "verification_text": "unique text",
                                        "baseline_count": 0,
                                    }
                                }
                            }
                        },
                    }
                ),
                encoding="utf-8",
            )
            called = {"message": 0}

            def message_factory():
                called["message"] += 1
                return "must not be built"

            class Logger:
                def info(self, *args): pass
                def warning(self, *args): pass
                def error(self, *args): pass

            with patch.dict("os.environ", {"SEND_STATE_FILE": str(path)}), patch.object(
                delivery, "verify_persisted", return_value=False
            ):
                result = delivery.deliver_once(
                    object(),
                    object(),
                    "account",
                    "Ken",
                    message_factory,
                    {"taskRetryTimes": 3},
                    Logger(),
                    lambda *args: iter(()),
                )
            self.assertFalse(result)
            self.assertEqual(called["message"], 0)

    def test_new_send_records_attempted_before_single_click_and_never_clicks_twice(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "state.json"
            clicks = {"count": 0}

            class Button:
                first = None

                def __init__(self):
                    self.first = self

                def count(self): return 1
                def is_visible(self): return True

                def dispatch_event(self, event):
                    self.assert_state_attempted()
                    clicks["count"] += 1

                def assert_state_attempted(self):
                    state = json.loads(path.read_text(encoding="utf-8"))
                    record = state["days"][delivery._today()]["account"]["Ken"]
                    if record["status"] != "attempted":
                        raise AssertionError("state must be attempted before click")

            class Page:
                def __init__(self):
                    self.button = Button()

                def locator(self, selector):
                    return self.button

            class Logger:
                def info(self, *args): pass
                def warning(self, *args): pass
                def error(self, *args): pass

            page = Page()
            with patch.dict("os.environ", {"SEND_STATE_FILE": str(path)}), patch.object(
                delivery, "active_conversation", return_value="Ken"
            ), patch.object(delivery, "_type_message"), patch.object(
                delivery, "_outgoing_match_count", return_value=0
            ), patch.object(delivery, "verify_persisted", return_value=False):
                first = delivery.deliver_once(
                    object(), page, "account", "Ken", lambda: "hello", {}, Logger(), lambda *args: iter(())
                )
                second = delivery.deliver_once(
                    object(), page, "account", "Ken", lambda: "hello", {}, Logger(), lambda *args: iter(())
                )

            self.assertFalse(first)
            self.assertFalse(second)
            self.assertEqual(clicks["count"], 1)

    def test_corrupt_state_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "state.json"
            path.write_text("not-json", encoding="utf-8")

            class Logger:
                def info(self, *args): pass
                def warning(self, *args): pass
                def error(self, *args): pass

            with patch.dict("os.environ", {"SEND_STATE_FILE": str(path)}):
                with self.assertRaises(RuntimeError):
                    delivery.pending_targets("account", ["Ken"], Logger())


if __name__ == "__main__":
    unittest.main()
