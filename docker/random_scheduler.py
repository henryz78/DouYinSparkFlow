#!/usr/bin/env python3
"""Keep a once-per-day random task time stable across cron invocations."""

import json
import os
import secrets
import sys
import tempfile
import time
from datetime import datetime, time as dt_time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from dotenv import dotenv_values


ENV_PATH = Path(os.environ.get("RANDOM_SCHEDULE_ENV_FILE", "/app/.env"))
STATE_PATH = Path(
    os.environ.get("RANDOM_SCHEDULE_STATE_FILE", "/app/logs/random-run-schedule.json")
)


def settings():
    values = dotenv_values(ENV_PATH)
    tz_name = os.environ.get("TZ") or values.get("TZ") or "Asia/Shanghai"
    hour = int(os.environ.get("CRON_HOUR") or values.get("CRON_HOUR", "9"))
    minute = int(os.environ.get("CRON_MINUTE") or values.get("CRON_MINUTE", "0"))
    second = int(os.environ.get("CRON_SECOND") or values.get("CRON_SECOND", "0"))
    window = int(os.environ.get("CRON_RANDOM_WINDOW_SECONDS") or values.get("CRON_RANDOM_WINDOW_SECONDS", "0"))
    tz = ZoneInfo(tz_name)
    start_seconds = hour * 3600 + minute * 60 + second
    if not 0 <= start_seconds < 86400:
        raise SystemExit("invalid cron start time")
    if window < 0 or start_seconds + window > 86400:
        raise SystemExit("random cron window must stay within one local calendar day")
    return hour, minute, second, window, tz


def _write_state(data: dict):
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(
        prefix=".random-run-", suffix=".json", dir=STATE_PATH.parent
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(data, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_name, STATE_PATH)
    finally:
        try:
            os.unlink(tmp_name)
        except FileNotFoundError:
            pass


def _load_state():
    try:
        return json.loads(STATE_PATH.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {}


def cron_info():
    hour, minute, second, window, _ = settings()
    if window == 0:
        print(f"{minute} {hour} * * *")
        print(f"fixed {hour:02d}:{minute:02d}:{second:02d}")
        return
    start = hour * 3600 + minute * 60 + second
    end = start + window - 1
    print(f"* {start // 3600}-{end // 3600} * * *")
    print(f"random window {hour:02d}:{minute:02d}:{second:02d} +{window}s")


def before_run():
    hour, minute, second, window, tz = settings()
    if window == 0:
        raise SystemExit(0)  # fixed mode: run-task.sh keeps the old behavior

    now = datetime.now(tz)
    start = datetime.combine(now.date(), dt_time(hour, minute, second), tzinfo=tz)
    end = start + timedelta(seconds=window)
    signature = f"{hour:02d}:{minute:02d}:{second:02d}+{window}"
    state = _load_state()

    if state.get("day") != now.date().isoformat() or state.get("signature") != signature:
        if now >= end:
            target = now
        elif now > start:
            remaining_window = int((end - now).total_seconds())
            target = now + timedelta(seconds=secrets.randbelow(max(1, remaining_window)))
        else:
            target = start + timedelta(seconds=secrets.randbelow(max(1, window)))
        state = {
            "day": now.date().isoformat(),
            "signature": signature,
            "target_epoch": int(target.timestamp()),
            "target_local": target.isoformat(),
            "completed": False,
        }
        _write_state(state)
        print(
            f"[docker] {now:%Y-%m-%d %H:%M:%S} today's random target: "
            f"{target:%Y-%m-%d %H:%M:%S %Z}"
        )

    if state.get("completed"):
        raise SystemExit(11)

    target = datetime.fromtimestamp(int(state["target_epoch"]), tz)
    remaining = (target - now).total_seconds()
    if remaining <= 0:
        if remaining <= -60:
            print(
                f"[docker] {now:%Y-%m-%d %H:%M:%S} target time ({target:%H:%M:%S}) "
                "already passed, running catch-up task now"
            )
        raise SystemExit(10)
    if remaining >= 60:
        raise SystemExit(11)  # this minute is not the chosen minute
    if remaining > 0:
        time.sleep(remaining)
    raise SystemExit(10)  # run the task now


def complete():
    _, _, _, window, _ = settings()
    if window == 0:
        return
    state = _load_state()
    if state:
        state["completed"] = True
        _write_state(state)


def main():
    command = sys.argv[1] if len(sys.argv) > 1 else ""
    if command == "cron":
        cron_info()
    elif command == "before-run":
        before_run()
    elif command == "complete":
        complete()
    else:
        raise SystemExit("usage: random_scheduler.py {cron|before-run|complete}")


if __name__ == "__main__":
    main()
