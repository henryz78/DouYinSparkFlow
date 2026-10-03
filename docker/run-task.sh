#!/bin/bash
set -euo pipefail

source /etc/douyin-spark-flow.env

echo "[docker] $(date '+%Y-%m-%d %H:%M:%S') start scheduled task"
if [[ -n "${CRON_SECOND:-}" && "${CRON_SECOND}" != "0" ]]; then
  sleep "${CRON_SECOND}"
fi
# 随机延迟：cron 到点后再随机等 0~N 秒。例：CRON_HOUR=8 + 窗口 7200 = 每天 08:00–10:00 随机执行
if [[ "${CRON_RANDOM_WINDOW_SECONDS:-0}" -gt 0 ]]; then
  delay=$(( (RANDOM * 32768 + RANDOM) % (CRON_RANDOM_WINDOW_SECONDS + 1) ))
  echo "[docker] $(date '+%Y-%m-%d %H:%M:%S') random delay ${delay}s (window ${CRON_RANDOM_WINDOW_SECONDS}s)"
  sleep "$delay"
fi
cd /app
python main.py task
echo "[docker] $(date '+%Y-%m-%d %H:%M:%S') scheduled task finished"
