#!/bin/bash
set -euo pipefail

# 环境快照 + cron 计划都由 apply-config.sh 生成（控制台保存配置时也会再调用它）
/app/docker/apply-config.sh

TZ="$(cat /tmp/douyin-spark-flow.tz)"
export TZ

echo "[docker] timezone: ${TZ:-UTC}"

# 个人控制台（可选）：只有配置了 DASH_PASSWORD_HASH 才启动；崩溃后 5 秒自动重启。
# 它和 cron 互相独立，控制台出问题不影响定时任务。
if [[ -n "$(python -c "from dotenv import dotenv_values; print(dotenv_values('/app/.env').get('DASH_PASSWORD_HASH') or '')")" ]]; then
  (
    cd /app
    export DASH_HOST="${DASH_HOST:-0.0.0.0}" DASH_PORT="${DASH_PORT:-8443}"
    while true; do
      python -m web.server >> /app/logs/dashboard.log 2>&1 || true
      sleep 5
    done
  ) &
  echo "[docker] dashboard enabled on :${DASH_PORT:-8443}"
fi

echo "[docker] container started, waiting for scheduled runs"

exec cron -f
