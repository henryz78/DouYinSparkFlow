"""Small, crash-safe at-most-once delivery state store."""

import json
import os
import tempfile
import time
from pathlib import Path


def state_path() -> Path:
    return Path(os.getenv("SEND_STATE_FILE", "logs/send_state.json"))


def backup_path() -> Path:
    return state_path().with_name(state_path().name + ".bak")


def today() -> str:
    tz_name = os.getenv("TZ", "Asia/Shanghai").strip() or "Asia/Shanghai"
    try:
        from zoneinfo import ZoneInfo
        from datetime import datetime
        return datetime.now(ZoneInfo(tz_name)).strftime("%Y-%m-%d")
    except Exception:
        return time.strftime("%Y-%m-%d")


def _read(path: Path) -> dict:
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise RuntimeError(f"发送状态文件无法读取，为避免重复发送已停止：{exc}") from exc
    if not isinstance(state, dict) or not isinstance(state.get("days", {}), dict):
        raise RuntimeError("发送状态文件格式无效，为避免重复发送已停止")
    state.setdefault("version", 1)
    state.setdefault("days", {})
    return state


def _write(path: Path, state: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(state, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_name, path)
    finally:
        try:
            os.unlink(tmp_name)
        except FileNotFoundError:
            pass


def load() -> dict:
    path = state_path()
    backup = backup_path()
    if not path.exists() and not backup.exists():
        return {"version": 1, "days": {}}

    try:
        return _read(path)
    except RuntimeError as primary_error:
        if not backup.exists():
            raise primary_error
        try:
            recovered = _read(backup)
        except RuntimeError:
            raise primary_error
        # The backup is known-good. Repairing the primary is best effort; the
        # valid backup remains available if the volume is temporarily read-only.
        try:
            _write(path, recovered)
        except OSError:
            pass
        return recovered


def save(state: dict) -> None:
    path = state_path()
    days = state.setdefault("days", {})
    for old_day in sorted(days)[:-30]:
        days.pop(old_day, None)

    if path.exists():
        try:
            previous = _read(path)
        except RuntimeError:
            previous = None
        if previous is not None:
            _write(backup_path(), previous)
    _write(path, state)
    if not backup_path().exists():
        try:
            _write(backup_path(), state)
        except OSError:
            # The primary write is already atomic and valid; keep the older backup.
            pass


def get(account: str, target: str, day: str | None = None) -> dict | None:
    return (
        load().get("days", {})
        .get(day or today(), {})
        .get(str(account), {})
        .get(str(target))
    )


def put(account: str, target: str, record: dict, day: str | None = None) -> None:
    state = load()
    account_records = (
        state.setdefault("days", {})
        .setdefault(day or today(), {})
        .setdefault(str(account), {})
    )
    account_records[str(target)] = dict(record)
    save(state)
