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

# AI 陪聊：一直有个守护循环在看配置。总开关打开、且某个账号配了 ai_targets 时才启动 main.py chat；
# 退出或崩溃后 60 秒自动重启。控制台改了陪聊设置会杀掉它，让它按新配置重新起来，无需重启容器。
# 和 cron、控制台互相独立，不影响定时任务。
(
  cd /app
  source /etc/douyin-spark-flow.env
  while true; do
    if [[ "$(python -c "from app.config.env_store import load_config; c = load_config()[0]; print(int(c.ai_chat.enabled and any(a.ai_targets for a in c.accounts)))" 2>/dev/null || echo 0)" == "1" ]]; then
      code=0
      python main.py chat >> /app/logs/ai-chat.log 2>&1 || code=$?
      echo "[docker] chat exited code=$code" >> /app/logs/ai-chat.log
      sleep 60
    else
      sleep 20
    fi
  done
) &
echo "[docker] AI chat watcher started (logs/ai-chat.log)"

echo "[docker] container started, waiting for scheduled runs"

exec cron -f
