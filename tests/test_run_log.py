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

    def test_write_failure_is_swallowed(self):
        with mock.patch.object(run_log, "RUNS_FILE", Path("/proc/nope/x/runs.jsonl")):
            run_log.record_run(logging.getLogger("t"), "a", [], 0, [], datetime.now().astimezone())


if __name__ == "__main__":
    unittest.main()
