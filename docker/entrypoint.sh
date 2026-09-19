#!/bin/bash
set -euo pipefail

# 一个镜像两种部署形态，按启动模式分派：
#   cron（默认）→ 服务器 Docker：容器内 cron 到点跑 runTasks
#   fc          → 阿里云函数计算：起 HTTP Server，等定时触发器事件打进来再跑
#
# 选 fc 的两种办法（任选其一）：
#   1. 函数配置里把「启动命令」覆盖为 /app/docker/entrypoint-fc.sh（推荐，不依赖环境变量）
#   2. 函数环境变量设 LAUNCH_MODE=fc

# docker compose run ... <command> 这类一次性任务会把显式命令作为参数传进来。
# 显式命令优先执行并退出，避免 one-off 容器被 LAUNCH_MODE=cron 误变成第二个定时器。
if [[ $# -gt 0 ]]; then
  exec "$@"
fi

LAUNCH_MODE="${LAUNCH_MODE:-cron}"
LAUNCH_MODE="${LAUNCH_MODE,,}"  # 控制台里手打容易填成 FC / Cron，统一转小写

case "${LAUNCH_MODE}" in
  fc|fc_server|serve)
    exec /app/docker/entrypoint-fc.sh "$@"
    ;;
  cron|*)
    exec /app/docker/entrypoint-cron.sh "$@"
    ;;
esac
