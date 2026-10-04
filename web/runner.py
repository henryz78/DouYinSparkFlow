"""手动运行：起 run-task.sh，并用它持有的文件锁判断"是否正在运行"。"""

import os
import subprocess
import threading
import time

try:
    import fcntl
except ImportError:  # Windows 本地预览：没有锁，手动运行不可用
    fcntl = None

LOCK = "/tmp/douyin-run.lock"
SCRIPT = "/app/docker/run-task.sh"
_started_at = 0.0


def is_running(lock=LOCK):
    # 刚点过"运行"的几秒内脚本还没拿到锁，也按运行中算，防止连点两次
    if time.time() - _started_at < 5:
        return True
    if fcntl is None or not os.path.exists(lock):
        return False
    with open(lock, "a") as f:
        try:
            fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            return True
        fcntl.flock(f, fcntl.LOCK_UN)
    return False


def start(log_path, script=SCRIPT):
    """返回是否真的启动了。已有任务在跑（定时的或手动的）则不启动。"""
    global _started_at
    if fcntl is None or not os.path.exists(script) or is_running():
        return False
    out = open(log_path, "ab")
    proc = subprocess.Popen(
        ["bash", script], env={**os.environ, "MANUAL_RUN": "1"},
        stdout=out, stderr=out, start_new_session=True,
    )
    _started_at = time.time()
    threading.Thread(target=proc.wait, daemon=True).start()  # 回收子进程，避免僵尸
    return True
