import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from core import tasks
from core.douyin_im import (
    DouyinIM,
    SEL_STICKER_CLICK_TARGET,
    SEL_STICKER_PANEL,
    SEL_STICKER_TARGET_MARKER,
)


class _Locator:
    def __init__(self, *, visible=False, text="", src="", children=None):
        self.first = self
        self.visible = visible
        self.text = text
        self.src = src
        self.children = children or []
        self.events = []
        self.calls = []

    def count(self):
        return 1

    def is_visible(self):
        return self.visible

    def dispatch_event(self, event):
        self.events.append(event)

    def locator(self, selector):
        if selector == ".emojiEmojiItememojiItem":
            return _Items(self.children)
        if selector == ".emojiEmojiItememojiItemDesc":
            return _Locator(text=self.text)
        if selector == SEL_STICKER_CLICK_TARGET:
            return self
        if selector == "img":
            return _Locator(src=self.src)
        raise AssertionError(selector)

    def inner_text(self):
        return self.text

    def get_attribute(self, _name):
        return self.src

    def nth(self, _index):
        return self

    def click(self, **kwargs):
        self.calls.append(kwargs)

    def evaluate(self, _script, *_args):
        return True


class _Items:
    def __init__(self, items):
        self.items = items

    def count(self):
        return len(self.items)

    def nth(self, index):
        return self.items[index]


class _Page:
    def __init__(self):
        self.button = _Locator(visible=True)
        self.panel = _Locator(visible=False)
        self.click_target = _Locator()
        self.panel.children = [
            _Locator(
                text="续火花",
                src="https://example.test/1687263281313-sticker?sig=temporary",
            )
        ]

    def locator(self, selector):
        if selector == SEL_STICKER_PANEL:
            return self.panel
        if selector == "svg.messageMsgInputiconAction":
            return self.button
        if selector == f"{SEL_STICKER_PANEL} {SEL_STICKER_CLICK_TARGET}":
            return self.click_target
        if selector == SEL_STICKER_TARGET_MARKER:
            return self.click_target
        raise AssertionError(selector)

    def wait_for_selector(self, selector, **_kwargs):
        self.panel.visible = selector == SEL_STICKER_PANEL

    def evaluate(self, _script, _resource_key):
        return {
            "matching_ids": ["old-id"],
            "matching_count": 1,
        }


class StickerProbeTests(unittest.TestCase):
    def test_resolves_exact_sticker_without_clicking_item(self):
        probe = object.__new__(DouyinIM)
        probe.page = _Page()
        probe.ready_timeout = 120

        result = probe.prepare_native_sticker("续火花")

        self.assertEqual(result["name"], "续火花")
        self.assertEqual(result["resource_key"], "1687263281313-sticker")
        self.assertEqual(result["snapshot"]["matching_ids"], ["old-id"])
        self.assertEqual(probe.page.button.events, ["click"])
        self.assertIs(result["item"], probe.page.click_target)
        self.assertEqual(result["item"].events, [])

    def test_native_sticker_uses_trusted_locator_click(self):
        class Item:
            def __init__(self):
                self.calls = []

            def dispatch_event(self, event):
                self.calls.append(event)

        probe = object.__new__(DouyinIM)
        probe._current_conv = lambda: {"convId": "conv:Ken"}
        item = Item()

        result = probe.send_native_sticker(
            {"conv_id": "conv:Ken", "display": "Ken"},
            {"item": item},
            wait_receipt=False,
        )

        self.assertTrue(result["ok"])
        self.assertEqual(item.calls, ["click"])

    def test_native_sticker_waits_for_same_http_dom_receipt_as_text(self):
        """贴纸发送复用文字那套 HTTP/DOM 回执监听，不再是发了就当成功的桩。"""
        class Mon:
            def __init__(self):
                self.sends = []

        class Item:
            def __init__(self, mon):
                self.mon = mon

            def dispatch_event(self, _event):
                # 模拟点击触发网络请求，监听器随后把回执塞进 mon.sends。
                self.mon.sends.append(
                    {"ok": True, "code": 0, "status": "OK", "message_id": "123456"}
                )

        class MsgState:
            def __init__(self):
                self.calls = 0

            def __call__(self):
                self.calls += 1
                if self.calls == 1:
                    return {"count": 0, "lastFromMe": False, "lastText": ""}
                return {"count": 1, "lastFromMe": True, "lastText": "🔥"}

        probe = object.__new__(DouyinIM)
        probe._current_conv = lambda: {"convId": "conv:Ken"}
        probe.mon = Mon()
        probe._msg_state = MsgState()
        probe.page = _Page()

        result = probe.send_native_sticker(
            {"conv_id": "conv:Ken", "display": "Ken"},
            {"item": Item(probe.mon)},
        )

        self.assertTrue(result["ok"])
        self.assertEqual(result["via"], "http+dom")
        self.assertEqual(result["message_id"], "123456")


class StickerDeliveryOnceTests(unittest.TestCase):
    def test_sticker_confirmation_uses_count_when_react_id_is_missing(self):
        class Page:
            def wait_for_timeout(self, _ms):
                pass

            def close(self):
                pass

        class Context:
            def new_page(self):
                return Page()

        class IM:
            def wait_ready(self):
                return {"status": tasks.STATUS_READY}

            def iter_find_and_select(self, _targets):
                yield {"display": "Ken", "conv_id": "conv:Ken"}

            def _current_conv(self):
                return {"convId": "conv:Ken"}

            def _outgoing_sticker_snapshot(self, _resource_key):
                return {"matching_ids": [], "matching_count": 1}

            def detach(self):
                pass

        record = {
            "display": "Ken",
            "conv_id": "conv:Ken",
            "resource_key": "sticker-key",
            "baseline_message_ids": [],
            "baseline_count": 0,
        }
        with patch.object(tasks, "_new_im", return_value=IM()):
            self.assertTrue(
                tasks._verify_sticker_persisted(
                    Context(), "account", record, tasks.config, tasks.logger
                )
            )

    def test_attempted_sticker_is_not_dispatched_twice(self):
        class Page:
            def wait_for_timeout(self, _ms):
                pass

        class Context:
            def set_default_navigation_timeout(self, _timeout):
                pass

            def set_default_timeout(self, _timeout):
                pass

            def new_page(self):
                return Page()

            def add_cookies(self, _cookies):
                pass

            def close(self):
                pass

        class Browser:
            def new_context(self):
                return Context()

        class IM:
            dispatches = 0
            prepares = 0

            def __init__(self, *_args, **_kwargs):
                self.last_scan = {"stopped": "caller-break", "select_failed": []}

            def wait_ready(self):
                return {"status": tasks.STATUS_READY, "user_id": "account"}

            def iter_find_and_select(self, targets):
                for target in targets:
                    yield {"display": target, "conv_id": f"conv:{target}"}

            def _current_conv(self):
                return {"convId": "conv:Ken"}

            def prepare_native_sticker(self, _name):
                type(self).prepares += 1
                return {
                    "name": "续火花",
                    "resource_key": "sticker-key",
                    "item": object(),
                    "snapshot": {
                        "matching_ids": ["old-id"],
                        "matching_count": 1,
                    },
                }

            def send_native_sticker(self, _hit, _prepared):
                type(self).dispatches += 1

            def fold_groups(self):
                return {}

            def detach(self):
                pass

        with tempfile.TemporaryDirectory() as tempdir, patch.dict(
            os.environ,
            {"SEND_STATE_FILE": str(Path(tempdir) / "send_state.json")},
        ), patch.object(tasks, "DouyinIM", IM), patch.object(
            tasks, "_verify_sticker_persisted", return_value=False
        ), patch.object(
            tasks,
            "config",
            {**tasks.config, "deliveryMode": "native_sticker", "nativeStickerName": "续火花"},
        ):
            with self.assertRaises(RuntimeError):
                tasks.do_user_task(Browser(), "account", [], ["Ken"])
            with self.assertRaises(RuntimeError):
                tasks.do_user_task(Browser(), "account", [], ["Ken"])

        self.assertEqual(IM.prepares, 1)
        self.assertEqual(IM.dispatches, 1)

    def test_http_confirmed_sticker_skips_persistence_check(self):
        """HTTP 回执确认成功时直接放行，不强求开新页面复核也能通过（真实案例：
        Ken 收到了贴纸，但复核没扫到，这条测试防止同类回归）。"""
        class Page:
            def wait_for_timeout(self, _ms):
                pass

        class Context:
            def set_default_navigation_timeout(self, _timeout):
                pass

            def set_default_timeout(self, _timeout):
                pass

            def new_page(self):
                return Page()

            def add_cookies(self, _cookies):
                pass

            def close(self):
                pass

        class Browser:
            def new_context(self):
                return Context()

        class IM:
            def __init__(self, *_args, **_kwargs):
                self.last_scan = {"stopped": "caller-break", "select_failed": []}

            def wait_ready(self):
                return {"status": tasks.STATUS_READY, "user_id": "account"}

            def iter_find_and_select(self, targets):
                for target in targets:
                    yield {"display": target, "conv_id": f"conv:{target}"}

            def _current_conv(self):
                return {"convId": "conv:Ken"}

            def prepare_native_sticker(self, _name):
                return {
                    "name": "续火花",
                    "resource_key": "sticker-key",
                    "item": object(),
                    "snapshot": {"matching_ids": ["old-id"], "matching_count": 1},
                }

            def send_native_sticker(self, _hit, _prepared):
                return {
                    "ok": True,
                    "via": "http+dom",
                    "message_id": "123456",
                    "code": 0,
                    "status": "OK",
                }

            def fold_groups(self):
                return {}

            def detach(self):
                pass

        with tempfile.TemporaryDirectory() as tempdir, patch.dict(
            os.environ,
            {"SEND_STATE_FILE": str(Path(tempdir) / "send_state.json")},
        ), patch.object(tasks, "DouyinIM", IM), patch.object(
            tasks,
            "_verify_sticker_persisted",
            side_effect=AssertionError("http 已确认时不该再开新页面复核"),
        ), patch.object(
            tasks,
            "config",
            {**tasks.config, "deliveryMode": "native_sticker", "nativeStickerName": "续火花"},
        ):
            tasks.do_user_task(Browser(), "account", [], ["Ken"])
            record = tasks.delivery_state.get("account", "ken")
            self.assertEqual(record["status"], "confirmed")
            self.assertTrue(record["receipt_ok"])


if __name__ == "__main__":
    unittest.main()
