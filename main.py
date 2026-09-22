"""程序入口 —— 按启动模式分派。

一个镜像要同时支持两种定时部署形态，靠这里分流：

    python main.py        跑一轮任务（= task）。GitHub Actions、服务器 cron 都走这条，
                          不带参数，和以前完全一样。
    python main.py task   同上，显式写法。
    python main.py fc     云函数模式：起 HTTP Server，等定时触发器事件打进来才跑任务。
                          为什么云函数也必须自备 HTTP Server，见 fc_server.py 顶部说明。

也支持环境变量 RUN_MODE 指定模式（命令行参数优先）。
"""

import os
import sys

# 尝试从 .env 文件加载环境变量
if os.path.exists(".env"):
    from dotenv import load_dotenv

    load_dotenv(".env")

def main():
    args = [arg.strip().lower() for arg in sys.argv[1:]]
    normalized_flags = {arg.lstrip("-") for arg in args}
    env_mode = os.getenv("RUN_MODE", "task").strip().lower().lstrip("-")

    # 优先判定安全测试模式与贴纸探测模式（防止 'task --selection-only' 误入正式发送）
    if normalized_flags & {"selection", "select", "selection_only", "selection-only"} or (
        not args and env_mode in {"selection", "select", "selection_only", "selection-only"}
    ):
        from core.tasks import runTasks

        runTasks(selection_only=True)
        return

    if normalized_flags & {"sticker_probe", "sticker-probe"} or (
        not args and env_mode in {"sticker_probe", "sticker-probe"}
    ):
        from core.tasks import runTasks

        runTasks(sticker_probe=True)
        return

    if normalized_flags & {"fc", "serve"} or (not args and env_mode in {"fc", "serve"}):
        from fc_server import serve

        serve()
        return

    # 有 argv 时只信任 argv 本身；没有 argv 时才退回看 RUN_MODE。
    # 二者不能混着判——否则任何拼写错误的子命令都会因为 RUN_MODE 默认值是
    # "task" 而被无声地当成正式发送模式放行（曾经的真实回归）。
    if not args:
        if env_mode in {"task", "run", "cli", ""}:
            from core.tasks import runTasks

            runTasks()
            return
    elif normalized_flags & {"task", "run", "cli", ""}:
        from core.tasks import runTasks

        runTasks()
        return

    print(
        f"未知启动模式: {' '.join(sys.argv[1:]) or ('RUN_MODE=' + env_mode)}"
        "（可选：task / selection / sticker_probe / fc）",
        file=sys.stderr,
    )
    sys.exit(2)


if __name__ == "__main__":
    main()
