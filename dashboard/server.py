from __future__ import annotations

import json
import os
import re
import unicodedata
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

from dotenv import dotenv_values


def norm(value: str) -> str:
    text = unicodedata.normalize("NFKC", str(value or ""))
    text = text.replace("\u3000", " ").replace("\xa0", " ")
    text = text.replace("\u200b", "").replace("\ufeff", "")
    return re.sub(r"\s+", " ", text).strip()


ROOT = Path(__file__).resolve().parent
INDEX_PATH = ROOT / "index.html"
LOGS_DIR = Path(os.environ.get("DASHBOARD_DATA_DIR", "/app/logs"))
ENV_PATH = Path(os.environ.get("DASHBOARD_ENV_FILE", "/app/.env"))


def _read_json(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return default


def _load_config() -> dict:
    values = {k: v for k, v in dotenv_values(ENV_PATH).items() if v is not None}
    try:
        tasks = json.loads(values.get("TASKS", "[]") or "[]")
    except json.JSONDecodeError:
        tasks = []
    if not isinstance(tasks, list):
        tasks = []
    return {"values": values, "tasks": tasks}


def _expected_targets(tasks: list) -> list[dict]:
    result: list[dict] = []
    for task in tasks:
        if not isinstance(task, dict):
            continue
        account = str(task.get("username") or task.get("unique_id") or "账号")
        targets = task.get("targets") or []
        if not isinstance(targets, list):
            targets = [targets]
        for target in targets:
            name = str(target).strip()
            if name:
                result.append(
                    {
                        "account": account,
                        "friend": name,
                        "account_key": norm(account),
                        "friend_key": norm(name),
                    }
                )
    return result


def _flatten_day(day_state: dict) -> list[dict]:
    rows: list[dict] = []
    if not isinstance(day_state, dict):
        return rows
    for account, friends in day_state.items():
        if not isinstance(friends, dict):
            continue
        for friend, record in friends.items():
            if not isinstance(record, dict):
                continue
            rows.append(
                {
                    "account": str(account),
                    "friend": str(friend),
                    "status": str(record.get("status") or "unknown"),
                    "attempted_at": record.get("attempted_at"),
                    "confirmed_at": record.get("confirmed_at"),
                }
            )
    return rows


def _fmt_epoch(value, tz: ZoneInfo) -> str | None:
    try:
        return datetime.fromtimestamp(float(value), tz).strftime("%H:%M:%S")
    except (TypeError, ValueError, OSError, OverflowError):
        return None


def _epoch_seconds_of_day(value, tz: ZoneInfo) -> int | None:
    try:
        dt = datetime.fromtimestamp(float(value), tz)
    except (TypeError, ValueError, OSError, OverflowError):
        return None
    return dt.hour * 3600 + dt.minute * 60 + dt.second


def _recent_log_summary() -> list[dict]:
    path = LOGS_DIR / "app.log"
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()[-400:]
    except OSError:
        return []
    pattern = re.compile(r"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}).*? - (INFO|WARNING|ERROR) - .*? - (.*)$")
    keep: list[dict] = []
    keywords = ("任务完成", "确认消息持久化", "今日已确认发送", "ERROR", "失败", "异常")
    for line in lines:
        match = pattern.match(line)
        if not match:
            continue
        ts, level, message = match.groups()
        if level == "ERROR" or any(key in message for key in keywords):
            keep.append({"time": ts, "level": level, "message": message[:180]})
    return keep[-12:][::-1]


def build_snapshot() -> dict:
    config = _load_config()
    values = config["values"]
    tasks = config["tasks"]
    tz_name = values.get("TZ", "Asia/Shanghai")
    try:
        tz = ZoneInfo(tz_name)
    except Exception:
        tz_name = "UTC"
        tz = ZoneInfo("UTC")
    now = datetime.now(tz)
    today = now.date().isoformat()

    expected = _expected_targets(tasks)
    expected_total = len(expected)
    send_state = _read_json(LOGS_DIR / "send_state.json", {"days": {}})
    days = send_state.get("days") if isinstance(send_state, dict) else {}
    if not isinstance(days, dict):
        days = {}
    today_state = days.get(today, {})
    today_rows_existing = _flatten_day(today_state)
    existing_map = {(norm(r["account"]), norm(r["friend"])): r for r in today_rows_existing}

    today_rows: list[dict] = []
    for item in expected:
        record = existing_map.get((item["account_key"], item["friend_key"]), {})
        today_rows.append(
            {
                "account": item["account"],
                "friend": item["friend"],
                "status": record.get("status", "pending"),
                "attempted_time": _fmt_epoch(record.get("attempted_at"), tz),
                "confirmed_time": _fmt_epoch(record.get("confirmed_at"), tz),
            }
        )
    for key, record in existing_map.items():
        if not any(norm(r["account"]) == key[0] and norm(r["friend"]) == key[1] for r in today_rows):
            today_rows.append(
                {
                    "account": record["account"],
                    "friend": record["friend"],
                    "status": record["status"],
                    "attempted_time": _fmt_epoch(record.get("attempted_at"), tz),
                    "confirmed_time": _fmt_epoch(record.get("confirmed_at"), tz),
                }
            )

    confirmed_today = sum(1 for r in today_rows if r["status"] == "confirmed")
    attempted_today = sum(1 for r in today_rows if r["status"] == "attempted")

    schedule = _read_json(LOGS_DIR / "random-run-schedule.json", {})
    target_local = schedule.get("target_local") if isinstance(schedule, dict) else None
    target_display = None
    target_epoch = schedule.get("target_epoch") if isinstance(schedule, dict) else None
    if target_epoch is not None:
        try:
            target_display = datetime.fromtimestamp(float(target_epoch), tz).strftime("%H:%M:%S")
        except (TypeError, ValueError, OSError, OverflowError):
            target_display = None

    if expected_total and confirmed_today >= expected_total:
        phase = "completed"
    elif attempted_today:
        phase = "running"
    elif schedule.get("day") == today and schedule.get("completed"):
        phase = "completed"
    elif target_epoch is not None:
        try:
            phase = "waiting" if now.timestamp() < float(target_epoch) else "due"
        except (TypeError, ValueError):
            phase = "waiting"
    else:
        phase = "waiting"

    observed_days: list[dict] = []
    for day in sorted(days.keys()):
        rows = _flatten_day(days.get(day, {}))
        if not rows:
            continue
        confirmed = sum(1 for r in rows if r["status"] == "confirmed")
        unresolved = sum(1 for r in rows if r["status"] != "confirmed")
        event_epochs = [
            r.get("attempted_at") or r.get("confirmed_at")
            for r in rows
            if r.get("attempted_at") or r.get("confirmed_at")
        ]
        first_event = min(event_epochs) if event_epochs else None
        observed_days.append(
            {
                "day": day,
                "confirmed": confirmed,
                "unresolved": unresolved,
                "total": len(rows),
                "execution_time": _fmt_epoch(first_event, tz),
                "execution_second": _epoch_seconds_of_day(first_event, tz),
            }
        )
    observed_days = observed_days[-30:]
    total_records = sum(item["total"] for item in observed_days)
    total_confirmed = sum(item["confirmed"] for item in observed_days)
    total_unresolved = sum(item["unresolved"] for item in observed_days)
    success_rate = round(total_confirmed * 100 / total_records, 1) if total_records else 0.0

    return {
        "generated_at": now.isoformat(),
        "timezone": tz_name,
        "today": today,
        "service": {"dashboard": "online", "scheduler": "enabled"},
        "schedule": {
            "mode": "random_window" if int(values.get("CRON_RANDOM_WINDOW_SECONDS", "0") or 0) > 0 else "fixed",
            "start": f"{int(values.get('CRON_HOUR', '9')):02d}:{int(values.get('CRON_MINUTE', '0')):02d}:{int(values.get('CRON_SECOND', '0')):02d}",
            "window_seconds": int(values.get("CRON_RANDOM_WINDOW_SECONDS", "0") or 0),
            "target": target_display,
            "target_local": target_local,
            "completed": bool(schedule.get("completed")) if isinstance(schedule, dict) else False,
        },
        "today_status": {
            "phase": phase,
            "confirmed": confirmed_today,
            "expected": expected_total,
            "rows": today_rows,
        },
        "stats": {
            "observed_days": len(observed_days),
            "confirmed": total_confirmed,
            "unresolved": total_unresolved,
            "records": total_records,
            "success_rate": success_rate,
        },
        "daily": observed_days,
        "recent_events": _recent_log_summary(),
    }


class DashboardHandler(BaseHTTPRequestHandler):
    server_version = "DouYinSparkDashboard/1.0"

    def _send(self, status: int, content_type: str, body: bytes, cache: str = "no-store") -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", cache)
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        path = urlparse(self.path).path
        if path == "/health":
            self._send(200, "text/plain; charset=utf-8", b"ok\n")
            return
        if path == "/api/status":
            try:
                body = json.dumps(build_snapshot(), ensure_ascii=False, separators=(",", ":")).encode("utf-8")
            except Exception as exc:
                body = json.dumps({"error": str(exc)}, ensure_ascii=False).encode("utf-8")
                self._send(500, "application/json; charset=utf-8", body)
                return
            self._send(200, "application/json; charset=utf-8", body)
            return
        if path in ("/", "/index.html"):
            try:
                body = INDEX_PATH.read_bytes()
            except OSError:
                self._send(500, "text/plain; charset=utf-8", b"dashboard UI missing\n")
                return
            self._send(200, "text/html; charset=utf-8", body)
            return
        self._send(404, "text/plain; charset=utf-8", b"not found\n")

    def log_message(self, fmt: str, *args) -> None:
        print(f"[dashboard] {self.address_string()} - {fmt % args}", flush=True)


def main() -> None:
    host = os.environ.get("DASHBOARD_HOST", "0.0.0.0")
    port = int(os.environ.get("DASHBOARD_PORT", "8787"))
    server = ThreadingHTTPServer((host, port), DashboardHandler)
    print(f"[dashboard] listening on http://{host}:{port}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
