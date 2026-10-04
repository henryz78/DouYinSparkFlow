import json
import logging
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest import mock

from core import run_log


class RecordRunTests(unittest.TestCase):
    def _record(self, sent_ok, problems):
        with tempfile.TemporaryDirectory() as d:
            f = Path(d) / "logs" / "runs.jsonl"
            with mock.patch.object(run_log, "RUNS_FILE", f):
                run_log.record_run(
                    logging.getLogger("t"), "acc", ["a", "b"], sent_ok, problems,
                    datetime.now().astimezone(),
                )
                run_log.record_run(
                    logging.getLogger("t"), "acc", ["a", "b"], sent_ok, problems,
                    datetime.now().astimezone(),
                )
            return [json.loads(x) for x in f.read_text(encoding="utf-8").splitlines()]

    def test_status(self):
        self.assertEqual(self._record(2, [])[0]["status"], "ok")
        self.assertEqual(self._record(1, ["未找到：b"])[0]["status"], "partial")
        self.assertEqual(self._record(0, ["x"])[0]["status"], "failed")
        self.assertEqual(self._record(None, ["boom"])[0]["status"], "error")

    def test_appends_one_line_per_call_and_fields(self):
        rows = self._record(2, [])
        self.assertEqual(len(rows), 2)
        self.assertEqual((rows[0]["sent"], rows[0]["targets"], rows[0]["account"]), (2, 2, "acc"))

    def test_friends_and_notified_recorded(self):
        with tempfile.TemporaryDirectory() as d:
            f = Path(d) / "runs.jsonl"
            with mock.patch.object(run_log, "RUNS_FILE", f):
                run_log.record_run(logging.getLogger("t"), "a", ["x"], 1, [], datetime.now().astimezone(),
                                   [{"name": "x", "status": "ok"}], True)
            row = json.loads(f.read_text(encoding="utf-8"))
        self.assertEqual((row["friends"], row["notified"]), ([{"name": "x", "status": "ok"}], True))

    def test_write_failure_is_swallowed(self):
        with mock.patch.object(run_log, "RUNS_FILE", Path("/proc/nope/x/runs.jsonl")):
            run_log.record_run(logging.getLogger("t"), "a", [], 0, [], datetime.now().astimezone())


class TodayDoneTests(unittest.TestCase):
    def _rows(self, *rows):
        d = tempfile.TemporaryDirectory()
        self.addCleanup(d.cleanup)
        f = Path(d.name) / "runs.jsonl"
        lines = [json.dumps(r) for r in rows] + ["garbage"]
        f.write_text(chr(10).join(lines) + chr(10), encoding="utf-8")
        return f

    def _row(self, account, status, day=None):
        day = day or datetime.now().astimezone().date().isoformat()
        return {"start": f"{day}T08:00:00+08:00", "account": account, "status": status}

    def test_done_only_when_every_account_last_run_ok(self):
        self.assertTrue(run_log.today_done(self._rows(self._row("a", "ok"))))
        self.assertFalse(run_log.today_done(self._rows(self._row("a", "ok"), self._row("b", "failed"))))
        # 先失败后手动补发成功 → 算完成
        self.assertTrue(run_log.today_done(self._rows(self._row("a", "failed"), self._row("a", "ok"))))

    def test_not_done_without_todays_rows(self):
        self.assertFalse(run_log.today_done(self._rows(self._row("a", "ok", "2020-01-01"))))
        self.assertFalse(run_log.today_done(Path("/nonexistent/runs.jsonl")))


if __name__ == "__main__":
    unittest.main()
