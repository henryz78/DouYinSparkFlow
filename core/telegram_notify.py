"""Telegram 结果通知。

尽力而为：通知失败只记一条日志，绝不影响任务结果，也绝不触发重发。
"""

import json
import os
import urllib.request
from datetime import datetime
from zoneinfo import ZoneInfo


def _now():
    try:
        return datetime.now(ZoneInfo(os.getenv("TZ") or "Asia/Shanghai")).strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _post(config, logger, text):
    token, chat_id = config["telegramBotToken"], config["telegramChatId"]
    if not (token and chat_id):
        logger.warning("Telegram 通知已开启，但 TELEGRAM_BOT_TOKEN 或 TELEGRAM_CHAT_ID 未配置")
        return False
    body = json.dumps(
        {"chat_id": chat_id, "text": text[:3900], "disable_web_page_preview": True},
        ensure_ascii=False,
    ).encode("utf-8")
    req = urllib.request.Request(
        f"https://api.telegram.org/bot{token}/sendMessage",
        data=body,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            ok = bool(json.loads(resp.read().decode("utf-8")).get("ok"))
        if ok:
            logger.info("Telegram 通知已发送")
        return ok
    except Exception as exc:
        # 异常文本可能带请求 URL（含 token），脱敏后再记
        logger.warning(f"Telegram 通知发送失败：{type(exc).__name__} {str(exc).replace(token, '<token>')[:160]}")
        return False


def notify_account(config, logger, username, targets, sent_ok, problems):
    """一个账号跑完发一条总结。problems 为空且 sent_ok>0 才算成功；sent_ok=None 表示中途异常、数量未确定。"""
    if not config["telegramEnabled"]:
        return False
    ok = bool(sent_ok) and not problems
    if not (config["telegramNotifySuccess"] if ok else config["telegramNotifyFailure"]):
        return False
    header = "✅ 火花任务完成" if ok else ("⚠️ 火花任务未完全完成" if sent_ok else "❌ 火花任务失败")
    method = "原生贴纸「" + config["nativeStickerName"] + "」" if config["deliveryMode"] == "native_sticker" else "文本消息"
    lines = [
        header,
        "",
        f"时间：{_now()}",
        f"账号：{username}",
        f"方式：{method}",
        f"结果：{'任务中断（完成数量未确定）' if sent_ok is None else f'{sent_ok}/{len(targets)} 已发送'}",
        f"目标好友：{'、'.join(targets) or '无'}",
    ]
    if problems:
        lines.append("问题：" + "；".join(problems))
    return _post(config, logger, "\n".join(lines))
