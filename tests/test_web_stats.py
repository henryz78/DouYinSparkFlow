import unittest
from datetime import date, datetime, timedelta, timezone

from web.stats import day_status, next_window, streaks, summary

TZ = timezone(timedelta(hours=8))


def row(day, status="ok", account="a", sent=2, targets=2, problems=()):
    return {"start": f"{day}T08:30:00+08:00", "end": f"{day}T08:31:00+08:00",
            "account": account, "status": status, "sent": sent, "targets": targets,
            "problems": list(problems)}


class StreakTests(unittest.TestCase):
    def test_today_missing_does_not_break_streak(self):
        days = day_status([row("2026-10-01"), row("2026-10-02")])
        self.assertEqual(streaks(days, date(2026, 10, 3)), (2, 2))

    def test_today_failed_resets_current_but_keeps_best(self):
        days = day_status([row("2026-10-01"), row("2026-10-02"), row("2026-10-03", "failed", sent=0)])
        self.assertEqual(streaks(days, date(2026, 10, 3)), (0, 2))

    def test_gap_splits_best(self):
        days = day_status([row("2026-09-28"), row("2026-09-29"), row("2026-10-01")])
        self.assertEqual(streaks(days, date(2026, 10, 1)), (1, 2))

    def test_manual_rerun_fixes_the_day(self):
        days = day_status([row("2026-10-03", "failed", sent=0), row("2026-10-03")])
        self.assertEqual(days, {"2026-10-03": True})


class SummaryTests(unittest.TestCase):
    now = datetime(2026, 10, 3, 9, 0, tzinfo=TZ)

    def test_states(self):
        s = lambda rows, now=self.now: summary(rows, now, 8, 0, 0, 7200)["state"]
        self.assertEqual(s([row("2026-10-03")]), "ok")
        self.assertEqual(s([row("2026-10-03", "partial", sent=1, problems=["x"])]), "partial")
        self.assertEqual(s([row("2026-10-03", "failed", sent=0)]), "failed")
        self.assertEqual(s([]), "pending")  # 09:00 仍在 08:00–10:00 窗口内
        self.assertEqual(s([], self.now.replace(hour=11)), "missing")

    def test_next_window_rolls_to_tomorrow(self):
        a, b = next_window(self.now, 8, 0, 0, 7200, ran_today=True)
        self.assertEqual((a.day, a.hour, b.hour), (4, 8, 10))
        a, _ = next_window(self.now, 8, 0, 0, 7200, ran_today=False)
        self.assertEqual(a.day, 3)  # 窗口内、还没跑

    def test_rate(self):
        rows = [row("2026-10-01"), row("2026-10-02", "failed", sent=0)]
        self.assertEqual(summary(rows, self.now)["rate_30"], 50)

    def test_calendar_friends_health(self):
        f = [{"name": "Rick", "status": "ok"}]
        rows = [dict(row("2026-10-02"), friends=f, notified=True),
                dict(row("2026-10-03", "failed", sent=0, problems=["登录已失效"]), friends=[], notified=False)]
        out = summary(rows, self.now)
        self.assertEqual(len(out["calendar"]), 30)
        self.assertEqual([c["status"] for c in out["calendar"][-3:]], ["none", "ok", "failed"])
        self.assertEqual(out["health"], {"login": "bad", "telegram": "failed"})
        # 今天还没跑：沿用上次名单，标记等待
        out = summary(rows[:1], self.now.replace(day=4))
        self.assertEqual(out["friends"], [{"name": "Rick", "status": "waiting"}])

    def test_health_empty(self):
        self.assertEqual(summary([], self.now)["health"], {"login": "unknown", "telegram": "unknown"})


if __name__ == "__main__":
    unittest.main()
