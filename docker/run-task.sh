#!/bin/bash
set -euo pipefail

source /etc/douyin-spark-flow.env

RANDOM_WINDOW_SECONDS="${CRON_RANDOM_WINDOW_SECONDS:-0}"

if [[ "${RUN_TASK_FORCE_NOW:-0}" != "1" && "$RANDOM_WINDOW_SECONDS" =~ ^[0-9]+$ && "$RANDOM_WINDOW_SECONDS" -gt 0 ]]; then
  mkdir -p /app/logs
  exec 9>/app/logs/random-run.lock
  if ! flock -n 9; then
    # 上一轮真实任务可能仍在执行；下一分钟 cron 会再次检查。
    exit 0
  fi

  mapfile -t RANDOM_PLAN < <(python - <<'PY'
import json
import os
import secrets
import tempfile
from datetime import datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

tz = ZoneInfo(os.environ.get('TZ', 'UTC'))
now = datetime.now(tz)
hour = int(os.environ.get('CRON_HOUR', '9'))
minute = int(os.environ.get('CRON_MINUTE', '0'))
second = int(os.environ.get('CRON_SECOND', '0'))
window = int(os.environ.get('CRON_RANDOM_WINDOW_SECONDS', '0'))
if window <= 0:
    raise SystemExit('CRON_RANDOM_WINDOW_SECONDS must be positive in random mode')

start = datetime.combine(now.date(), time(hour, minute, second), tzinfo=tz)
end = start + timedelta(seconds=window)
if end.date() != start.date():
    raise SystemExit('random cron window must stay within one local calendar day')

state_path = Path('/app/logs/random-run-schedule.json')
state = {}
try:
    state = json.loads(state_path.read_text(encoding='utf-8'))
except (FileNotFoundError, json.JSONDecodeError, OSError):
    state = {}

day = now.date().isoformat()
signature = f'{hour:02d}:{minute:02d}:{second:02d}+{window}'
created = False
if state.get('day') != day or state.get('signature') != signature:
    delay = secrets.randbelow(window)
    target = start + timedelta(seconds=delay)
    state = {
        'day': day,
        'signature': signature,
        'target_epoch': int(target.timestamp()),
        'target_local': target.isoformat(),
        'completed': False,
    }
    created = True
    state_path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix='.random-run-', suffix='.json', dir=state_path.parent)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            json.dump(state, f, ensure_ascii=False, indent=2)
            f.write('\n')
        os.replace(tmp_name, state_path)
    finally:
        try:
            os.unlink(tmp_name)
        except FileNotFoundError:
            pass

target_epoch = int(state['target_epoch'])
target = datetime.fromtimestamp(target_epoch, tz)
if state.get('completed'):
    action = 'completed'
    wait_seconds = 0
elif now < start:
    action = 'wait'
    wait_seconds = max(0, int((target - now).total_seconds()))
elif now >= target:
    action = 'run'
    wait_seconds = 0
else:
    remaining = max(0, int((target - now).total_seconds()))
    # cron 每分钟检查一次；进入目标分钟后精确 sleep 到目标秒。
    action = 'run' if remaining < 60 else 'wait'
    wait_seconds = remaining

print(action)
print(wait_seconds)
print(target.strftime('%Y-%m-%d %H:%M:%S %Z'))
print('1' if created else '0')
PY
  )

  RANDOM_ACTION="${RANDOM_PLAN[0]}"
  RANDOM_WAIT_SECONDS="${RANDOM_PLAN[1]}"
  RANDOM_TARGET_LOCAL="${RANDOM_PLAN[2]}"
  RANDOM_CREATED="${RANDOM_PLAN[3]}"

  if [[ "$RANDOM_CREATED" == "1" ]]; then
    echo "[docker] $(date '+%Y-%m-%d %H:%M:%S') today's random target: ${RANDOM_TARGET_LOCAL}"
  fi

  if [[ "$RANDOM_ACTION" == "completed" || "$RANDOM_ACTION" == "wait" ]]; then
    exit 0
  fi

  if (( RANDOM_WAIT_SECONDS > 0 )); then
    sleep "$RANDOM_WAIT_SECONDS"
  fi
fi

echo "[docker] $(date '+%Y-%m-%d %H:%M:%S') start scheduled task"

if [[ "${RUN_TASK_FORCE_NOW:-0}" == "1" && -n "${CRON_SECOND:-}" && "${CRON_SECOND}" != "0" ]]; then
  sleep "${CRON_SECOND}"
fi

cd /app
python main.py task

if [[ "${RUN_TASK_FORCE_NOW:-0}" != "1" && "$RANDOM_WINDOW_SECONDS" =~ ^[0-9]+$ && "$RANDOM_WINDOW_SECONDS" -gt 0 ]]; then
  python - <<'PY'
import json
import os
import tempfile
from pathlib import Path

state_path = Path('/app/logs/random-run-schedule.json')
try:
    state = json.loads(state_path.read_text(encoding='utf-8'))
except (FileNotFoundError, json.JSONDecodeError, OSError):
    state = {}
state['completed'] = True
fd, tmp_name = tempfile.mkstemp(prefix='.random-run-', suffix='.json', dir=state_path.parent)
try:
    with os.fdopen(fd, 'w', encoding='utf-8') as f:
        json.dump(state, f, ensure_ascii=False, indent=2)
        f.write('\n')
    os.replace(tmp_name, state_path)
finally:
    try:
        os.unlink(tmp_name)
    except FileNotFoundError:
        pass
PY
fi

echo "[docker] $(date '+%Y-%m-%d %H:%M:%S') scheduled task finished"
