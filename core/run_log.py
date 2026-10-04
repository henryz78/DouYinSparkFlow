import json
from datetime import datetime
from pathlib import Path

# 每个账号每次运行追加一行 JSON，供控制台读历史/连续天数；放在已挂载的 logs/ 里。
RUNS_FILE = Path(__file__).resolve().parent.parent / "logs" / "runs.jsonl"


def record_run(logger, username, targets, sent_ok, problems, started, friends=(), notified=None, method=""):
    """尽力而为：写失败只告警，绝不影响任务结果。sent_ok=None 表示中途异常。
    friends=[{name,status}] 逐人结果；notified=Telegram 是否送达（None=没发）。"""
    if sent_ok is None:
        status = "error"
    elif not problems:
        status = "ok"
    else:
        status = "partial" if sent_ok else "failed"
    now = datetime.now().astimezone()
    row = {
        "start": started.isoformat(timespec="seconds"),
        "end": now.isoformat(timespec="seconds"),
        "account": username,
        "status": status,
        "sent": sent_ok or 0,
        "targets": len(targets),
        "target_names": list(targets),
        "problems": problems,
        "friends": list(friends),
        "notified": notified,
        "method": method,
    }
    try:
        RUNS_FILE.parent.mkdir(parents=True, exist_ok=True)
        with RUNS_FILE.open("a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    except Exception as exc:
        logger.warning(f"运行记录写入失败：{exc}")
