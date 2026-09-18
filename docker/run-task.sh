#!/bin/bash
set -euo pipefail

source /etc/douyin-spark-flow.env

mkdir -p /app/logs
exec 9>/app/logs/task.lock
flock -n 9 || exit 0

RANDOM_RUN=0
if [[ "${RUN_TASK_FORCE_NOW:-0}" != "1" ]]; then
  set +e
  python /app/docker/random_scheduler.py before-run
  GATE=$?
  set -e
  case "$GATE" in
    0) ;;
    10) RANDOM_RUN=1 ;;
    11) exit 0 ;;
    *) exit "$GATE" ;;
  esac
fi

echo "[docker] $(date '+%Y-%m-%d %H:%M:%S') start scheduled task"
if [[ "$RANDOM_RUN" == "0" && -n "${CRON_SECOND:-}" && "${CRON_SECOND}" != "0" ]]; then
  sleep "${CRON_SECOND}"
fi
cd /app
python main.py task
if [[ "$RANDOM_RUN" == "1" ]]; then
  python /app/docker/random_scheduler.py complete
fi
echo "[docker] $(date '+%Y-%m-%d %H:%M:%S') scheduled task finished"
