#!/bin/bash
set -euo pipefail

# 把 /app/.env 的当前内容应用到运行中的容器：重写环境快照（run-task.sh 会 source 它）
# 和 cron 计划。容器启动时调用一次；控制台保存配置后再调用一次，无需重启容器。
# 注意：TZ 只在容器启动时读入 cron 守护进程，改时区仍需重启容器。

CONFIG_ENV_PATH="/app/.env"

if [[ ! -f "$CONFIG_ENV_PATH" ]]; then
  echo "Config file not found: $CONFIG_ENV_PATH" >&2
  exit 1
fi

python - <<'PY'
import os
import shlex
from dotenv import dotenv_values

config_env_path = "/app/.env"
file_vars = {k: v for k, v in dotenv_values(config_env_path).items() if v is not None}
merged_vars = dict(os.environ)
merged_vars.update(file_vars)

with open('/etc/douyin-spark-flow.env', 'w', encoding='utf-8') as f:
    for key, value in merged_vars.items():
        f.write(f'export {key}={shlex.quote(value)}\n')

with open('/tmp/douyin-spark-flow.cron', 'w', encoding='utf-8') as f:
    f.write(file_vars.get('CRON_SCHEDULE', os.environ.get('CRON_SCHEDULE', '')))

with open('/tmp/douyin-spark-flow.tz', 'w', encoding='utf-8') as f:
    f.write(file_vars.get('TZ', os.environ.get('TZ', 'UTC')))
PY

read_env() {
  python - "$1" "$2" <<'PY'
import sys
from dotenv import dotenv_values
print(dotenv_values('/app/.env').get(sys.argv[1], sys.argv[2]))
PY
}

CRON_HOUR="$(read_env CRON_HOUR 9)"
CRON_MINUTE="$(read_env CRON_MINUTE 0)"
CRON_SECOND="$(read_env CRON_SECOND 0)"

if [[ -z "$CRON_HOUR" || -z "$CRON_MINUTE" || -z "$CRON_SECOND" ]]; then
  echo "CRON_HOUR, CRON_MINUTE and CRON_SECOND are required." >&2
  exit 1
fi

CRON_SCHEDULE="${CRON_MINUTE} ${CRON_HOUR} * * *"

# 先写临时文件再改名：cron 靠目录变化感知更新，原地改写它可能看不到
cat > /etc/cron.d/.douyin-spark-flow.new <<EOF
SHELL=/bin/bash
PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
${CRON_SCHEDULE} root /app/docker/run-task.sh >> /proc/1/fd/1 2>> /proc/1/fd/2
EOF
chmod 0644 /etc/cron.d/.douyin-spark-flow.new
mv /etc/cron.d/.douyin-spark-flow.new /etc/cron.d/douyin-spark-flow

echo "[docker] cron schedule: ${CRON_SCHEDULE} (+${CRON_SECOND}s)"
