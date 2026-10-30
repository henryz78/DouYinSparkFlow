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
    # 把"今天随机到的发送时间"写给控制台显示
    date -d "@$(( $(date +%s) + delay ))" -Iseconds > /app/logs/planned_run || true
    sleep "$delay"
  fi
  # 延迟之后再判断：等待期间若已手动成功运行过，就不重复发送
  if python -m core.run_log; then
    echo "[docker] $(date '+%Y-%m-%d %H:%M:%S') today already done, skip"
    exit 0
  fi
fi
# 同一时刻只允许一个任务（定时和手动共用这把锁，控制台也靠它判断"是否正在运行"）。
# 锁只在任务运行期间持有，补发前的等待不占锁。拿不到锁说明另一个任务在跑，直接跳过。
run_once() {
  (
    if ! flock -n 9; then
      echo "[docker] $(date '+%Y-%m-%d %H:%M:%S') another run in progress, skip"
      exit 0
    fi
    "$@"
  ) 9>/tmp/douyin-run.lock
}

rc=0
run_once python main.py task || rc=$?
echo "[docker] $(date '+%Y-%m-%d %H:%M:%S') scheduled task finished"

# 定时运行后还有人没发到（会话列表偶尔加载不全，隔一阵再来多半就有了）：
# 隔 RETRY_INTERVAL_SECONDS 秒只补发没成功的人，最多 RETRY_MAX 次；手动运行不补发。
if [[ "${MANUAL_RUN:-}" != "1" ]]; then
  for ((i = 1; i <= ${RETRY_MAX:-3}; i++)); do
    python -m core.run_log && break
    sleep "${RETRY_INTERVAL_SECONDS:-3600}"
    python -m core.run_log && break  # 等待期间被手动补发成功了
    echo "[docker] $(date '+%Y-%m-%d %H:%M:%S') retry ${i}/${RETRY_MAX:-3}: resend to those not done"
    run_once env RETRY_MISSING=1 python main.py task || true
  done
fi
exit "$rc"
