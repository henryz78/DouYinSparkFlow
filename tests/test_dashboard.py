import json
import os
import tempfile
import unittest
from datetime import timedelta
from pathlib import Path
from unittest.mock import patch

from dashboard import server


class DashboardTests(unittest.TestCase):
    def test_snapshot_excludes_message_content_and_counts_confirmed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            env_file = root / ".env"
            logs = root / "logs"
            logs.mkdir()
            env_file.write_text(
                'TZ=Asia/Shanghai\nCRON_HOUR=08\nCRON_MINUTE=00\nCRON_SECOND=00\n'
                'CRON_RANDOM_WINDOW_SECONDS=7200\n'
                'TASKS=[{"username":"账号","unique_id":"u","targets":["A","今心（多伦多）"]}]\n',
                encoding="utf-8",
            )
            today = server.datetime.now(server.ZoneInfo("Asia/Shanghai")).date().isoformat()
            (logs / "send_state.json").write_text(
                json.dumps(
                    {
                        "days": {
                            today: {
                                "账号": {
                                    "A": {"status": "confirmed", "message": "SECRET", "confirmed_at": 1789667600},
                                    "今心(多伦多)": {"status": "attempted", "message": "SECRET2", "attempted_at": 1789667700},
                                }
                            }
                        }
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            with patch.object(server, "ENV_PATH", env_file), patch.object(server, "LOGS_DIR", logs):
                snapshot = server.build_snapshot()
            self.assertEqual(snapshot["today_status"]["confirmed"], 1)
            self.assertEqual(snapshot["today_status"]["expected"], 2)
            self.assertEqual(snapshot["today_status"]["phase"], "running")
            self.assertEqual(len(snapshot["today_status"]["rows"]), 2)
            self.assertNotIn("SECRET", json.dumps(snapshot, ensure_ascii=False))

    def test_stale_random_schedule_is_not_shown_as_today(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            env_file = root / ".env"
            logs = root / "logs"
            logs.mkdir()
            env_file.write_text(
                'TZ=Asia/Shanghai\nCRON_HOUR=08\nCRON_MINUTE=00\nCRON_SECOND=00\n'
                'CRON_RANDOM_WINDOW_SECONDS=7200\nTASKS=[]\n',
                encoding="utf-8",
            )
            today = server.datetime.now(server.ZoneInfo("Asia/Shanghai")).date().isoformat()
            yesterday = (server.datetime.now(server.ZoneInfo("Asia/Shanghai")).date() - timedelta(days=1)).isoformat()
            (logs / "random-run-schedule.json").write_text(
                json.dumps(
                    {
                        "day": yesterday,
                        "target_epoch": 1789695509,
                        "target_local": f"{yesterday}T09:38:29+08:00",
                        "completed": True,
                    }
                ),
                encoding="utf-8",
            )
            with patch.object(server, "ENV_PATH", env_file), patch.object(server, "LOGS_DIR", logs):
                snapshot = server.build_snapshot()
            self.assertEqual(snapshot["today"], today)
            self.assertIsNone(snapshot["schedule"]["target"])
            self.assertIsNone(snapshot["schedule"]["target_local"])
            self.assertFalse(snapshot["schedule"]["completed"])
            self.assertEqual(snapshot["today_status"]["phase"], "waiting")


if __name__ == "__main__":
    unittest.main()
