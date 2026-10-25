"""会话标题只显示数字时，按以前记下的 uid 认出好友。不联系真实好友。"""
import tempfile
import unittest
from pathlib import Path

from core import peer_ids
from core.ai.runner import matches
from core.douyin_im import DouyinIM


def im_with(ids):
    im = object.__new__(DouyinIM)
    im.peer_ids = ids
    return im


class AliasTests(unittest.TestCase):
    def test_numeric_title_matches_by_remembered_uid(self):
        im = im_with({"ken": "3778"})
        numeric = {"uid": "3778", "title": "3778", "display": "3778", "conv_id": "0:1:1:3778"}
        self.assertEqual(im._match(numeric, {"ken": "ken", "rick": "rick"}), ("ken", "alias"))
        self.assertEqual(im._match({**numeric, "uid": "9999"}, {"ken": "ken"}), (None, None))
        self.assertEqual(im._match({**numeric, "is_group": True}, {"ken": "ken"}), (None, None))

    def test_name_match_wins_and_is_learned_but_fuzzy_is_not(self):
        im = im_with({})
        named = {"uid": "3778", "nickname": "Ken", "display": "Ken"}
        im._learn_peer("ken", named, "nickname")
        im._learn_peer("rick", {"uid": "2870", "display": "Rickey"}, "fuzzy")
        im._learn_peer("3778", named, "uid")
        self.assertEqual(im.peer_ids, {"ken": "3778"})

    def test_chat_runner_matches_by_remembered_uid(self):
        hit = {"uid": "3778", "title": "3778", "conv_id": "0:1:1:3778"}
        self.assertFalse(matches(hit, "ken"))
        self.assertTrue(matches(hit, "ken", {"ken": "3778"}))
        self.assertFalse(matches({**hit, "is_group": True}, "ken", {"ken": "3778"}))


class StoreTests(unittest.TestCase):
    def test_saved_per_account_and_skips_empty(self):
        path = Path(tempfile.mkdtemp()) / "logs" / "peer_ids.json"
        peer_ids.save("a", {}, path)
        self.assertFalse(path.exists())
        peer_ids.save("a", {"ken": "1"}, path)
        peer_ids.save("b", {"ken": "2"}, path)
        self.assertEqual((peer_ids.load("a", path), peer_ids.load("b", path), peer_ids.load("c", path)),
                         ({"ken": "1"}, {"ken": "2"}, {}))


if __name__ == "__main__":
    unittest.main()
