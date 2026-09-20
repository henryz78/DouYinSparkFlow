import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from core import delivery_state


class DeliveryStateTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.path = Path(self.tempdir.name) / "send_state.json"
        self.env = patch.dict(os.environ, {"SEND_STATE_FILE": str(self.path)}, clear=False)
        self.env.start()

    def tearDown(self):
        self.env.stop()
        self.tempdir.cleanup()

    def test_missing_state_is_empty(self):
        self.assertEqual(delivery_state.load(), {"version": 1, "days": {}})

    def test_put_is_reloadable_and_keeps_record(self):
        delivery_state.put("account-1", "Rick", {"status": "attempted"}, day="2026-09-20")
        self.assertEqual(
            delivery_state.get("account-1", "Rick", day="2026-09-20"),
            {"status": "attempted"},
        )
        self.assertEqual(json.loads(self.path.read_text(encoding="utf-8"))["version"], 1)

    def test_corrupt_state_fails_closed(self):
        self.path.write_text("{not-json", encoding="utf-8")
        with self.assertRaisesRegex(RuntimeError, "无法读取"):
            delivery_state.load()

    def test_old_days_are_trimmed(self):
        state = {"version": 1, "days": {f"2026-01-{day:02d}": {} for day in range(1, 33)}}
        delivery_state.save(state)
        self.assertEqual(len(delivery_state.load()["days"]), 30)


if __name__ == "__main__":
    unittest.main()
