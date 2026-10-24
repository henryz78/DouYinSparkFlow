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

from core.ai.config import AIConfig

# 配置页完全由这里描述：前端按 GROUPS 分组、按字段的 type 画控件，不写死任何键。
# 以后想在页面上多开放一项，只要在 FIELDS 里加一行（放进已有分组，或在 GROUPS 里加新分组）。
GROUPS = [
    {"id": "time", "label": "发送时间", "note": "每天这个时刻触发，再叠加下面的随机窗口。"},
    {"id": "content", "label": "发送内容", "note": ""},
    {"id": "advanced", "label": "高级（一般不用改）", "note": "下一次运行时生效。"},
]


def _f(key, typ, group, label, default, rng, hint="", **ui):
    """ui 可选：row=同一行显示的组名；scale/unit=页面按这个倍数换算成更大的单位显示；widget=textarea。"""
    return {"key": key, "type": typ, "group": group, "label": label, "hint": hint,
            "range": rng, "default": default, **ui}


FIELDS = [
    _f("CRON_HOUR", "int", "time", "小时", "9", (0, 23), row="hms"),
    _f("CRON_MINUTE", "int", "time", "分钟", "0", (0, 59), row="hms"),
    _f("CRON_SECOND", "int", "time", "秒", "0", (0, 59), row="hms"),
    _f("CRON_RANDOM_WINDOW_SECONDS", "int", "time", "随机窗口", "0", (0, 86400),
       "到点后再随机等 0 到这么多分钟才发送，0 表示不随机", scale=60, unit="分钟"),
    _f("DELIVERY_MODE", "enum", "content", "发送方式", "text", ("text", "native_sticker")),
    _f("NATIVE_STICKER_NAME", "str", "content", "贴纸名称", "续火花", (1, 30), "原生贴纸方式下要点的表情包名字"),
    _f("MESSAGE_TEMPLATE", "str", "content", "文本模板", "", (1, 500),
       "文本方式用；\\n 表示换行，[API] 替换为一言", widget="textarea"),
    _f("TASK_RETRY_TIMES", "int", "advanced", "任务失败重试次数", "3", (0, 10)),
    _f("LOG_LEVEL", "enum", "advanced", "日志级别", "Debug", ("Debug", "Info", "Warning", "Error")),
    _f("BROWSER_ACTION_TIMEOUT", "int", "advanced", "浏览器单步超时（秒）", "120", (10, 600)),
    _f("IM_READY_TIMEOUT", "int", "advanced", "等聊天页就绪的上限（秒）", "120", (10, 600)),
    _f("IM_SCAN_TIMEOUT", "int", "advanced", "滚动找好友的总时限（秒）", "120", (10, 1800)),
    _f("IM_MAX_STEPS", "int", "advanced", "滚动步数上限", "200", (10, 2000)),
    _f("FRIEND_LIST_WAIT_TIME", "int", "advanced", "好友资料静默等待（秒）", "3", (1, 30),
       "调大会明显拖慢找好友"),
]
BY_KEY = {f["key"]: f for f in FIELDS}
MAX_TARGETS = 50


def read(path):
    """当前值 + 各账号的好友名单。"""
    raw = dotenv_values(path) if Path(path).exists() else {}
    fields = []
    for f in FIELDS:
        value = raw.get(f["key"])
        value = f["default"] if value is None else value
        item = {k: v for k, v in f.items() if k != "default"}
        item["range"] = list(f["range"]) if f["range"] else None
        item["value"] = value.lower() == "true" if f["type"] == "bool" else value
        fields.append(item)
    accounts = []
    for i, task in enumerate(_tasks(raw)):
        chosen = task.get("ai_personas") if isinstance(task.get("ai_personas"), dict) else {}
        accounts.append({
            "id": i,
            "name": task.get("username") or task.get("unique_id") or f"账号{i + 1}",
            "targets": list(task.get("targets", [])),
            "chat": [{"name": n, "persona": chosen.get(n, "")} for n in task.get("ai_targets", [])],
        })
    ai = _ai_dict(raw)  # 只给陪聊的开关和性格；服务商、API Key 不出服务器
    return {"groups": GROUPS, "fields": fields, "accounts": accounts,
            "ai": {"enabled": ai.enabled, "default_persona": ai.default_persona, "personas": ai.personas}}


def _ai_dict(raw):
    try:
        return AIConfig.from_value(raw.get("AI_CHAT") or "{}")
    except (ValueError, TypeError):
        return AIConfig()


def _tasks(raw):
    try:
        tasks = json.loads(raw.get("TASKS") or "[]")
        return tasks if isinstance(tasks, list) else []
    except ValueError:
        return []


def validate_ai(ai):
    """陪聊设置：{"enabled", "default_persona", "personas", "friends": {账号序号: [{"name", "persona"}]}}。"""
    errors = {}
    if not isinstance(ai.get("enabled"), bool):
        errors["ai-enabled"] = "需要开或关"
    try:
        names = [p["name"] for p in AIConfig.clean_personas(ai.get("personas"))]
    except (ValueError, TypeError, AttributeError) as exc:
        errors["ai-personas"] = str(exc)
        names = []
    if ai.get("default_persona") and ai["default_persona"] not in names:
        errors["ai-personas"] = "默认性格不在性格列表里"
    friends = ai.get("friends") if isinstance(ai.get("friends"), dict) else {}
    for idx, rows in friends.items():
        key = f"ai-friends-{idx}"
        if not isinstance(rows, list) or len(rows) > MAX_TARGETS:
            errors[key] = f"好友最多 {MAX_TARGETS} 个"
        elif any(not isinstance(r, dict) or not isinstance(r.get("name"), str) or not r["name"].strip()
                 or "#" in r["name"] or "\n" in r["name"] for r in rows):
            errors[key] = "好友名不能为空，也不能含 # 或换行"
        elif any(r.get("persona") and r["persona"] not in names for r in rows):
            errors[key] = "选的性格不在性格列表里"
    return errors


def validate(values, targets, ai=None):
    """返回 {字段: 错误}；空 dict 表示通过。values 为 {键: 值}，targets 为 {账号序号: [好友名]}。"""
    errors = validate_ai(ai) if ai is not None else {}
    for key, value in values.items():
        if key not in BY_KEY:
            errors[key] = "不是可修改的配置项"
            continue
        typ, rng = BY_KEY[key]["type"], BY_KEY[key]["range"]
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


def save(path, values, targets, backup_path, ai=None):
    """校验已通过后调用。返回写入的键列表。"""
    path = Path(path)
    text = path.read_bytes().decode("utf-8")  # 不经换行转换，CRLF 文件原样保留
    updates = {k: (str(v).lower() if isinstance(v, bool) else str(v)) for k, v in values.items()}
    friends = ai.get("friends", {}) if ai else {}
    if targets or friends:
        tasks = _tasks(dotenv_values(path))
        for idx, names in targets.items():
            tasks[int(idx)]["targets"] = [n.strip() for n in names]
        for idx, rows in friends.items():
            task = tasks[int(idx)]
            task["ai_targets"] = [r["name"].strip() for r in rows]
            task["ai_personas"] = {r["name"].strip(): r["persona"] for r in rows if r.get("persona")}
        updates["TASKS"] = json.dumps(tasks, ensure_ascii=False)
    if ai:
        raw = json.loads(dotenv_values(path).get("AI_CHAT") or "{}")  # 保留服务商和 API Key 原样
        raw.update(enabled=ai["enabled"], personas=ai["personas"], default_persona=ai.get("default_persona", ""))
        updates["AI_CHAT"] = json.dumps(raw, ensure_ascii=False, separators=(",", ":"))
    Path(backup_path).parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(path, backup_path)  # 保留上一版，写坏了能恢复
    path.write_text(_update_env_text(text, updates), encoding="utf-8", newline="")
    return list(updates)


def restart_chat():
    """杀掉陪聊进程；容器里的守护循环会按新配置重新拉起（开关关着就不拉起）。"""
    try:
        subprocess.run(["pkill", "-f", "main.py chat"], timeout=10)
    except (OSError, subprocess.TimeoutExpired):
        pass


def apply(script="/app/docker/apply-config.sh", chat=False):
    """让新配置对运行中的容器生效（重写环境快照和 cron 计划）。chat=True 时同时重启陪聊。返回 (是否成功, 说明)。"""
    if chat:
        restart_chat()
    if not Path(script).exists():
        return True, "已保存（当前环境没有 cron，未重载）"
    try:
        r = subprocess.run(["bash", script], capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return False, f"已保存，但应用失败：{exc}"
    if r.returncode != 0:
        return False, "已保存，但应用失败：" + (r.stderr.strip() or r.stdout.strip())[-200:]
    return True, "已保存并生效" + ("；陪聊约 1 分钟内按新设置重新启动" if chat else "")
