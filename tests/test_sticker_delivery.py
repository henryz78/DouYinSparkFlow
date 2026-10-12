"""Sticker sends follow the same delivery_state contract as text (no resend once clicked)."""
import unittest
from unittest.mock import Mock

from core.douyin_im import DouyinIM


class StickerDeliveryTests(unittest.TestCase):
    def setUp(self):
        self.im = object.__new__(DouyinIM)
        self.hit = {"conv_id": "c1", "display": "好友"}

    def test_failure_before_click_is_safe_to_retry(self):
        self.im._send_native_sticker = Mock(side_effect=RuntimeError("找不到贴纸"))
        r = self.im.send_native_sticker(self.hit)
        self.assertEqual((r["delivery_state"], r["safe_to_retry"], r["ok"]), ("not_sent", True, False))

    def test_no_receipt_after_click_is_uncertain(self):
        def inner(hit, name, wait, timeout, before_click):
            before_click()
            return {"ok": False}
        self.im._send_native_sticker = inner
        r = self.im.send_native_sticker(self.hit)
        self.assertEqual((r["delivery_state"], r["safe_to_retry"]), ("uncertain", False))

    def test_receipt_is_confirmed(self):
        def inner(hit, name, wait, timeout, before_click):
            before_click()
            return {"ok": True}
        self.im._send_native_sticker = inner
        r = self.im.send_native_sticker(self.hit)
        self.assertEqual((r["delivery_state"], r["ok"]), ("confirmed", True))


if __name__ == "__main__":
    unittest.main()
