#!/bin/bash
set -euo pipefail

source /etc/douyin-spark-flow.env

echo "[docker] $(date '+%Y-%m-%d %H:%M:%S') start ${MANUAL_RUN:+manual }scheduled task"
cd /app
# 手动运行（控制台"立即运行"）不等待也不跳过；定时运行才走下面的延迟和"今天已完成则跳过"
if [[ "${MANUAL_RUN:-}" != "1" ]]; then
  if [[ -n "${CRON_SECOND:-}" && "${CRON_SECOND}" != "0" ]]; then
    sleep "${CRON_SECOND}"
  fi
  # 随机延迟：cron 到点后再随机等 0~N 秒。例：CRON_HOUR=8 + 窗口 7200 = 每天 08:00–10:00 随机执行
  if [[ "${CRON_RANDOM_WINDOW_SECONDS:-0}" -gt 0 ]]; then
    delay=$(( (RANDOM * 32768 + RANDOM) % (CRON_RANDOM_WINDOW_SECONDS + 1) ))
    echo "[docker] $(date '+%Y-%m-%d %H:%M:%S') random delay ${delay}s (window ${CRON_RANDOM_WINDOW_SECONDS}s)"
    sleep "$delay"
  fi
  # 延迟之后再判断：等待期间若已手动成功运行过，就不重复发送
  if python -m core.run_log; then
    echo "[docker] $(date '+%Y-%m-%d %H:%M:%S') today already done, skip"
    exit 0
  fi
fi
# 同一时刻只允许一个任务（定时和手动共用这把锁，控制台也靠它判断"是否正在运行"）
exec 9>/tmp/douyin-run.lock
if ! flock -n 9; then
  echo "[docker] $(date '+%Y-%m-%d %H:%M:%S') another run in progress, skip"
  exit 0
fi
python main.py task
echo "[docker] $(date '+%Y-%m-%d %H:%M:%S') scheduled task finished"
