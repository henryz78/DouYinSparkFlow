"""Optional Telegram notifications for task results.

Telegram is deliberately best-effort: a notification outage must never change
the Douyin task result or cause a second delivery attempt.
"""

from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from datetime import datetime
from zoneinfo import ZoneInfo


_TRUE_VALUES = {"1", "true", "yes", "on"}
_MAX_REASON_LENGTH = 700
_MAX_MESSAGE_LENGTH = 3900


def _as_bool(value, default=False):
    if value is None:
        return default
    return str(value).strip().lower() in _TRUE_VALUES


def _clean(value, limit):
    text = " ".join(str(value or "").split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _failure_stage(reason):
    text = str(reason or "")
    if "操作前检查" in text or "未登录" in text or "登录" in text:
        return "登录 / 页面准备"
    if "未找到" in text or "扫描" in text:
        return "好友扫描"
    if "选中" in text or "会话校验" in text:
        return "好友选择"
    if "发送" in text or "持久化" in text or "attempted" in text:
        return "发送 / 发送后确认"
    return "任务执行"


def _success_count(reason):
    match = re.search(r"(?:发送|选择)成功\s*=\s*(\d+)\s*/\s*(\d+)", str(reason or ""))
    return (int(match.group(1)), int(match.group(2))) if match else None


class TelegramNotifier:
    def __init__(self, config=None, logger=None):
        config = config or {}
        self.enabled = _as_bool(config.get("telegramEnabled"), False)
        self.token = str(config.get("telegramBotToken") or "").strip()
        self.chat_id = str(config.get("telegramChatId") or "").strip()
        self._notify_success_enabled = _as_bool(
            config.get("telegramNotifySuccess"), True
        )
        self._notify_failure_enabled = _as_bool(
            config.get("telegramNotifyFailure"), True
        )
        self.notify_test = _as_bool(config.get("telegramNotifyTest"), False)
        self.timezone = str(config.get("timezone") or os.getenv("TZ") or "Asia/Shanghai")
        self.logger = logger

    @property
    def configured(self):
        return self.enabled and bool(self.token and self.chat_id)

    def _now(self):
        try:
            return datetime.now(ZoneInfo(self.timezone)).strftime("%Y-%m-%d %H:%M:%S")
        except Exception:
            return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    def _log_warning(self, message):
        if self.logger is not None:
            self.logger.warning(message)

    def _error_text(self, exc):
        text = _clean(exc, 160)
        if self.token:
            text = text.replace(self.token, "<redacted>")
        return text

    def _post(self, text):
        if not self.enabled:
            return False
        if not self.token or not self.chat_id:
            self._log_warning("Telegram 通知已开启，但 TELEGRAM_BOT_TOKEN 或 TELEGRAM_CHAT_ID 未配置")
            return False
        payload = json.dumps(
            {
                "chat_id": self.chat_id,
                "text": text[:_MAX_MESSAGE_LENGTH],
                "disable_web_page_preview": True,
            },
            ensure_ascii=False,
        ).encode("utf-8")
        try:
            request = urllib.request.Request(
                f"https://api.telegram.org/bot{self.token}/sendMessage",
                data=payload,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(request, timeout=10) as response:
                result = json.loads(response.read().decode("utf-8"))
            if not result.get("ok"):
                raise RuntimeError("Telegram API 返回 ok=false")
            return True
        except urllib.error.HTTPError as exc:
            self._log_warning(f"Telegram 通知发送失败：HTTP {exc.code}")
        except urllib.error.URLError as exc:
            self._log_warning(f"Telegram 通知发送失败：网络错误 {self._error_text(exc.reason)}")
        except Exception as exc:
            self._log_warning(
                f"Telegram 通知发送失败：{type(exc).__name__} {self._error_text(exc)}"
            )
        return False

    def notify_success(self, username, targets, delivery_mode="text", test_mode=False):
        if not self._notify_success_enabled or (test_mode and not self.notify_test):
            return False
        target_list = list(
            dict.fromkeys(str(target) for target in targets if str(target).strip())
        )
        method = "原生贴纸「续火花」" if delivery_mode == "native_sticker" else "文本消息"
        text = "\n".join(
            [
                "✅ 火花任务完成",
                "",
                f"时间：{self._now()}（北京时间）",
                f"账号：{_clean(username, 120)}",
                f"方式：{method}",
                f"结果：{len(target_list)}/{len(target_list)} 已确认完成",
                f"已处理好友：{_clean('、'.join(target_list) or '无', 600)}",
            ]
        )
        return self._post(text)

    def notify_failure(self, username, targets, reason, delivery_mode="text", test_mode=False):
        if not self._notify_failure_enabled or (test_mode and not self.notify_test):
            return False
        target_list = list(
            dict.fromkeys(str(target) for target in targets if str(target).strip())
        )
        count = _success_count(reason)
        header = "⚠️ 火花任务未完全完成" if count and count[0] else "❌ 火花任务失败"
        result = (
            f"{count[0]}/{count[1]} 已完成"
            if count
            else "任务中断（完成数量未确定）"
        )
        lines = [
            header,
            "",
            f"时间：{self._now()}（北京时间）",
            f"账号：{_clean(username, 120)}",
            f"方式：{'原生贴纸「续火花」' if delivery_mode == 'native_sticker' else '文本消息'}",
            f"结果：{result}",
            f"目标好友：{_clean('、'.join(target_list) or '无', 600)}",
            f"失败阶段：{_failure_stage(reason)}",
            f"原因：{_clean(reason, _MAX_REASON_LENGTH)}",
        ]
        if "attempted" in str(reason) or "不自动重发" in str(reason):
            lines.append("处理：已保留发送状态，本日不会自动重复发送。")
        return self._post("\n".join(lines))
