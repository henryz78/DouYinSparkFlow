"""控制台里的配置编辑：只开放普通项，Cookie / Token / 密码一律不经过网页。

写入策略是就地改 .env（只替换对应的键，其余行和注释原样保留）。
文件是 Docker 的单文件挂载，不能用"写临时文件再改名"，所以直接截断重写。
"""

import json
import re
import shutil
import subprocess
from pathlib import Path

from dotenv import dotenv_values

# (键, 类型, 分组, 标签, 提示, 取值范围/选项, 默认值)
FIELDS = [
    ("CRON_HOUR", "int", "time", "小时", "", (0, 23), "9"),
    ("CRON_MINUTE", "int", "time", "分钟", "", (0, 59), "0"),
    ("CRON_SECOND", "int", "time", "秒", "", (0, 59), "0"),
    ("CRON_RANDOM_WINDOW_SECONDS", "int", "time", "随机窗口（秒）", "到点后再随机等 0 到这么多秒才发送，0 表示不随机", (0, 86400), "0"),
    ("DELIVERY_MODE", "enum", "content", "发送方式", "", ("text", "native_sticker"), "text"),
    ("NATIVE_STICKER_NAME", "str", "content", "贴纸名称", "原生贴纸方式下要点的表情包名字", (1, 30), "续火花"),
    ("MESSAGE_TEMPLATE", "str", "content", "文本模板", "文本方式用；\\n 表示换行，[API] 替换为一言", (1, 500), ""),
]
BY_KEY = {f[0]: f for f in FIELDS}
MAX_TARGETS = 50


def read(path):
    """当前值 + 各账号的好友名单。"""
    raw = dotenv_values(path) if Path(path).exists() else {}
    fields = []
    for key, typ, group, label, hint, rng, default in FIELDS:
        value = raw.get(key)
        value = default if value is None else value
        fields.append({
            "key": key, "type": typ, "group": group, "label": label, "hint": hint,
            "range": list(rng) if rng else None,
            "value": value.lower() == "true" if typ == "bool" else value,
        })
    accounts = []
    for i, task in enumerate(_tasks(raw)):
        accounts.append({
            "id": i,
            "name": task.get("username") or task.get("unique_id") or f"账号{i + 1}",
            "targets": list(task.get("targets", [])),
        })
    return {"fields": fields, "accounts": accounts}


def _tasks(raw):
    try:
        tasks = json.loads(raw.get("TASKS") or "[]")
        return tasks if isinstance(tasks, list) else []
    except ValueError:
        return []


def validate(values, targets):
    """返回 {字段: 错误}；空 dict 表示通过。values 为 {键: 值}，targets 为 {账号序号: [好友名]}。"""
    errors = {}
    for key, value in values.items():
        if key not in BY_KEY:
            errors[key] = "不是可修改的配置项"
            continue
        _, typ, _, _, _, rng, _ = BY_KEY[key]
        if typ == "int":
            if not isinstance(value, int) or isinstance(value, bool) or not rng[0] <= value <= rng[1]:
                errors[key] = f"需要 {rng[0]} 到 {rng[1]} 之间的整数"
        elif typ == "bool":
            if not isinstance(value, bool):
                errors[key] = "需要开或关"
        elif typ == "enum":
            if value not in rng:
                errors[key] = "取值不在允许范围内"
        else:
            if not isinstance(value, str) or not rng[0] <= len(value) <= rng[1]:
                errors[key] = f"长度需要 {rng[0]} 到 {rng[1]} 个字符"
            elif "#" in value or "\n" in value or "\r" in value or value != value.strip():
                errors[key] = "不能含 # 或换行，首尾不能有空格"
    for idx, names in targets.items():
        if not isinstance(names, list) or len(names) > MAX_TARGETS:
            errors[f"account-{idx}"] = f"好友名单最多 {MAX_TARGETS} 个"
        elif any(not isinstance(n, str) or not n.strip() or "#" in n or "\n" in n for n in names):
            errors[f"account-{idx}"] = "好友名不能为空，也不能含 # 或换行"
    return errors


def _update_env_text(text, updates):
    nl = "\r\n" if "\r\n" in text else "\n"
    lines = text.split(nl)
    for key, value in updates.items():
        pattern = re.compile(rf"^\s*{re.escape(key)}\s*=")
        for i, line in enumerate(lines):
            if pattern.match(line):
                lines[i] = f"{key}={value}"
                break
        else:
            if lines and lines[-1] == "":
                lines.insert(len(lines) - 1, f"{key}={value}")
            else:
                lines.append(f"{key}={value}")
    return nl.join(lines)


def save(path, values, targets, backup_path):
    """校验已通过后调用。返回写入的键列表。"""
    path = Path(path)
    text = path.read_bytes().decode("utf-8")  # 不经换行转换，CRLF 文件原样保留
    updates = {k: (str(v).lower() if isinstance(v, bool) else str(v)) for k, v in values.items()}
    if targets:
        tasks = _tasks(dotenv_values(path))
        for idx, names in targets.items():
            tasks[int(idx)]["targets"] = [n.strip() for n in names]
        updates["TASKS"] = json.dumps(tasks, ensure_ascii=False)
    Path(backup_path).parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(path, backup_path)  # 保留上一版，写坏了能恢复
    path.write_text(_update_env_text(text, updates), encoding="utf-8", newline="")
    return list(updates)


def apply(script="/app/docker/apply-config.sh"):
    """让新配置对运行中的容器生效（重写环境快照和 cron 计划）。返回 (是否成功, 说明)。"""
    if not Path(script).exists():
        return True, "已保存（当前环境没有 cron，未重载）"
    try:
        r = subprocess.run(["bash", script], capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return False, f"已保存，但应用失败：{exc}"
    if r.returncode != 0:
        return False, "已保存，但应用失败：" + (r.stderr.strip() or r.stdout.strip())[-200:]
    return True, "已保存并生效"
