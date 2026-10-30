import json
from datetime import datetime
from pathlib import Path

# 每个账号每次运行追加一行 JSON，供控制台读历史/连续天数；放在已挂载的 logs/ 里。
RUNS_FILE = Path(__file__).resolve().parent.parent / "logs" / "runs.jsonl"


def record_run(logger, username, targets, sent_ok, problems, started, friends=(), method=""):
    """尽力而为：写失败只告警，绝不影响任务结果。sent_ok=None 表示中途异常。
    friends=[{name,status}] 逐人结果。"""
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
        "method": method,
    }
    try:
        RUNS_FILE.parent.mkdir(parents=True, exist_ok=True)
        with RUNS_FILE.open("a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    except Exception as exc:
        logger.warning(f"运行记录写入失败：{exc}")


def _last_today(path=None, now=None):
    """今天每个账号的最后一条运行记录：{账号: 记录}。"""
    last = {}
    today = (now or datetime.now().astimezone()).date().isoformat()
    try:
        with open(path or RUNS_FILE, encoding="utf-8") as f:
            for line in f:
                try:
                    r = json.loads(line)
                except ValueError:
                    continue
                if r["start"][:10] == today:
                    last[r["account"]] = r
    except FileNotFoundError:
        pass
    return last


def today_done(path=None, now=None):
    """今天每个账号最后一次运行都成功了吗？定时任务据此跳过，避免手动运行后又重复发一遍。"""
    last = _last_today(path, now)
    return bool(last) and all(r["status"] == "ok" for r in last.values())


def retry_plan(account, names, path=None, now=None):
    """补发：今天最后一次运行里已经发到的好友不再发。
    返回（还要发的好友, 之前已经算数的逐人记录）；今天还没跑过就是全部要发。
    「待确认」的人可能已经发出去了，不自动重发，也不算成功。"""
    friends = (_last_today(path, now).get(account) or {}).get("friends") or []
    done = [f for f in friends if f.get("status") in ("ok", "uncertain") and f.get("name") in names]
    skip = {f["name"] for f in done}
    return [n for n in names if n not in skip], done


if __name__ == "__main__":  # run-task.sh 用：退出码 0 = 今天已完成
    raise SystemExit(0 if today_done() else 1)
