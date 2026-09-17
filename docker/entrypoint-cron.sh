#!/bin/bash
set -euo pipefail

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

CRON_HOUR="$(python - <<'PY'
from dotenv import dotenv_values
values = dotenv_values('/app/.env')
print(values.get('CRON_HOUR', '9'))
PY
)"
CRON_MINUTE="$(python - <<'PY'
from dotenv import dotenv_values
values = dotenv_values('/app/.env')
print(values.get('CRON_MINUTE', '0'))
PY
)"
CRON_SECOND="$(python - <<'PY'
from dotenv import dotenv_values
values = dotenv_values('/app/.env')
print(values.get('CRON_SECOND', '0'))
PY
)"
CRON_RANDOM_WINDOW_SECONDS="$(python - <<'PY'
from dotenv import dotenv_values
values = dotenv_values('/app/.env')
print(values.get('CRON_RANDOM_WINDOW_SECONDS', '0'))
PY
)"
TZ="$(cat /tmp/douyin-spark-flow.tz)"
export TZ
export CRON_HOUR CRON_MINUTE CRON_SECOND CRON_RANDOM_WINDOW_SECONDS

if [[ -z "$CRON_HOUR" || -z "$CRON_MINUTE" || -z "$CRON_SECOND" || -z "$CRON_RANDOM_WINDOW_SECONDS" ]]; then
  echo "CRON_HOUR, CRON_MINUTE, CRON_SECOND and CRON_RANDOM_WINDOW_SECONDS are required." >&2
  exit 1
fi

if ! [[ "$CRON_RANDOM_WINDOW_SECONDS" =~ ^[0-9]+$ ]]; then
  echo "CRON_RANDOM_WINDOW_SECONDS must be a non-negative integer." >&2
  exit 1
fi

if (( CRON_RANDOM_WINDOW_SECONDS > 0 )); then
  read -r RANDOM_START_HOUR RANDOM_END_HOUR < <(python - <<'PY'
import os

hour = int(os.environ['CRON_HOUR'])
minute = int(os.environ['CRON_MINUTE'])
second = int(os.environ['CRON_SECOND'])
window = int(os.environ['CRON_RANDOM_WINDOW_SECONDS'])
start = hour * 3600 + minute * 60 + second
end_exclusive = start + window
if start < 0 or start >= 86400 or end_exclusive <= start or end_exclusive > 86400:
    raise SystemExit('random cron window must stay within one local calendar day')
print(start // 3600, (end_exclusive - 1) // 3600)
PY
  )
  CRON_SCHEDULE="* ${RANDOM_START_HOUR}-${RANDOM_END_HOUR} * * *"
  SCHEDULE_DESCRIPTION="random window ${CRON_HOUR}:${CRON_MINUTE}:${CRON_SECOND} +${CRON_RANDOM_WINDOW_SECONDS}s"
else
  CRON_SCHEDULE="${CRON_MINUTE} ${CRON_HOUR} * * *"
  SCHEDULE_DESCRIPTION="fixed ${CRON_HOUR}:${CRON_MINUTE}:${CRON_SECOND}"
fi

cat > /etc/cron.d/douyin-spark-flow <<EOF
SHELL=/bin/bash
PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
${CRON_SCHEDULE} root /app/docker/run-task.sh >> /proc/1/fd/1 2>> /proc/1/fd/2
EOF

chmod 0644 /etc/cron.d/douyin-spark-flow

echo "[docker] timezone: ${TZ:-UTC}"
echo "[docker] cron schedule: ${CRON_SCHEDULE} (${SCHEDULE_DESCRIPTION})"
echo "[docker] container started, waiting for scheduled runs"

exec cron -f
