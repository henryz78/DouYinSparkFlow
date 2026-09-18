import io
import unittest
from contextlib import redirect_stdout
from datetime import timezone
from unittest.mock import patch

from docker import random_scheduler


class RandomSchedulerTests(unittest.TestCase):
    def test_random_window_cron_covers_only_window_hours(self):
        with patch.object(
            random_scheduler,
            "settings",
            return_value=(8, 0, 0, 7200, timezone.utc),
        ):
            output = io.StringIO()
            with redirect_stdout(output):
                random_scheduler.cron_info()
        self.assertEqual(
            output.getvalue().splitlines(),
            ["* 8-9 * * *", "random window 08:00:00 +7200s"],
        )

    def test_fixed_cron_keeps_official_schedule_shape(self):
        with patch.object(
            random_scheduler,
            "settings",
            return_value=(9, 15, 20, 0, timezone.utc),
        ):
            output = io.StringIO()
            with redirect_stdout(output):
                random_scheduler.cron_info()
        self.assertEqual(
            output.getvalue().splitlines(),
            ["15 9 * * *", "fixed 09:15:20"],
        )


if __name__ == "__main__":
    unittest.main()
