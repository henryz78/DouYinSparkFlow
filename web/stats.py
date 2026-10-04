import json
from datetime import datetime, timedelta


def load_runs(path):
    """读 runs.jsonl，按文件顺序（即时间顺序）返回；坏行直接跳过。"""
    rows = []
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                try:
                    rows.append(json.loads(line))
                except ValueError:
                    pass
    except FileNotFoundError:
        pass
    return rows


def day_status(rows):
    """{日期: 当天是否全部成功}。同一天同一账号只看最后一次（手动补跑成功就算成功）。"""
    last = {}
    for r in rows:
        last[(r["start"][:10], r["account"])] = r["status"]
    days = {}
    for (d, _), st in last.items():
        days[d] = days.get(d, True) and st == "ok"
    return days


def streaks(days, today):
    """(当前连续天数, 历史最长)。今天还没跑不断连；今天失败则当前为 0。"""
    d = today if today.isoformat() in days else today - timedelta(days=1)
    cur = 0
    while days.get(d.isoformat()):
        cur += 1
        d -= timedelta(days=1)
    best = run = 0
    prev = None
    for s in sorted(k for k, ok in days.items() if ok):
        day = datetime.strptime(s, "%Y-%m-%d").date()
        run = run + 1 if prev and day - prev == timedelta(days=1) else 1
        best = max(best, run)
        prev = day
    return cur, best


def next_window(now, hour, minute, second, window, ran_today):
    """下一次发送的时间窗 (start, end)。今天已发过或窗口已过 → 明天。"""
    start = now.replace(hour=hour, minute=minute, second=second, microsecond=0)
    if ran_today or now > start + timedelta(seconds=window):
        start += timedelta(days=1)
    return start, start + timedelta(seconds=window)


def summary(rows, now, hour=8, minute=0, second=0, window=0):
    today = now.date()
    days = day_status(rows)
    cur, best = streaks(days, today)
    recent = [ok for d, ok in days.items() if (today - datetime.strptime(d, "%Y-%m-%d").date()).days < 30]

    last = {}
    for r in rows:
        if r["start"][:10] == today.isoformat():
            last[r["account"]] = r
    todays = list(last.values())
    if not todays:
        w_end = now.replace(hour=hour, minute=minute, second=second, microsecond=0) + timedelta(seconds=window)
        state = "pending" if now <= w_end else "missing"
    elif all(r["status"] == "ok" for r in todays):
        state = "ok"
    elif any(r["sent"] > 0 for r in todays):
        state = "partial"
    else:
        state = "failed"

    start, end = next_window(now, hour, minute, second, window, bool(todays))
    return {
        "state": state,
        "sent": sum(r["sent"] for r in todays),
        "targets": sum(r["targets"] for r in todays),
        "finished": max((r["end"] for r in todays), default=None),
        "problems": [p for r in todays for p in r["problems"]],
        "streak": cur,
        "best_streak": best,
        "rate_30": round(100 * sum(recent) / len(recent)) if recent else None,
        "days_recorded": len(days),
        "next_start": start.isoformat(timespec="seconds"),
        "next_end": end.isoformat(timespec="seconds"),
    }
