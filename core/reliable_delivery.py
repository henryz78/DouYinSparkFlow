import json
import os
import random
import re
import tempfile
import time
from pathlib import Path
from urllib.parse import urlsplit

from utils import norm


CONVERSATION_ITEM_SELECTOR = ".conversationConversationItemwrapper"
CONVERSATION_TITLE_SELECTOR = ".conversationConversationItemtitle"
CONVERSATION_LIST_SELECTOR = ".conversationConversationListwrapper"
CHAT_EDITABLE_SELECTOR = '.messageEditorimChatEditorContainer [contenteditable="true"]'
SEND_BUTTON_SELECTOR = ".e2e-send-msg-btn"
RIGHT_PANEL_TITLE_SELECTOR = ".RightPanelHeadertitle"
TRUST_LOGIN_DIALOG_SELECTOR = ".trust-login-dialog-mask"
OUTGOING_MESSAGE_SELECTOR = ".messageMessageBoxcontentBox.messageMessageBoxisFromMe"
STICKER_BUTTON_SELECTOR = "svg.messageMsgInputiconAction"
STICKER_PANEL_SELECTOR = ".componentsemojiemojiPanel"
STICKER_ITEM_SELECTOR = ".emojiEmojiItememojiItem"
STICKER_DESC_SELECTOR = ".emojiEmojiItememojiItemDesc"
INPUT_TOKEN_RE = re.compile(r"(\[[^\[\]\n]+\]|\n)")


def human_pause(low: float, high: float) -> None:
    """Small randomized pause used only for visible user-like pacing."""
    if high < low:
        low, high = high, low
    time.sleep(random.uniform(max(0.0, low), max(0.0, high)))


def _message_input_tokens(message: str) -> list[tuple[str, str]]:
    """Split text into human-typed text, atomic emoji shortcodes, and newlines."""
    normalized = (message or "").replace("\\n", "\n")
    tokens: list[tuple[str, str]] = []
    for part in INPUT_TOKEN_RE.split(normalized):
        if not part:
            continue
        if part == "\n":
            tokens.append(("newline", part))
        elif part.startswith("[") and part.endswith("]"):
            tokens.append(("shortcode", part))
        else:
            tokens.append(("text", part))
    return tokens


def _human_insert_text(page, text: str) -> None:
    """Type visibly one character at a time without relying on raw key events.

    Douyin's Slate editor ignores part of CloakBrowser's ASCII keydown/keyup
    path, while insert_text is reliable for both CJK and ASCII. Per-character
    insertion plus randomized pacing keeps the visible typing gradual.
    """
    for index, char in enumerate(text):
        page.keyboard.insert_text(char)
        if index >= len(text) - 1:
            continue
        if char in "，。！？；：,.!?;:":
            human_pause(0.08, 0.22)
        elif char.isspace():
            human_pause(0.03, 0.09)
        else:
            human_pause(0.035, 0.13)


def _state_path() -> Path:
    return Path(os.getenv("SEND_STATE_FILE", "logs/send_state.json"))


def _today() -> str:
    return time.strftime("%Y-%m-%d")


def load_state(logger) -> dict:
    path = _state_path()
    if not path.exists():
        return {"version": 1, "days": {}}
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        # 状态损坏时不能按“从未发送”处理，否则可能造成重复发送。
        raise RuntimeError(f"发送状态文件无法读取，为避免重复发送已停止：{exc}") from exc
    if not isinstance(state, dict) or not isinstance(state.get("days", {}), dict):
        raise RuntimeError("发送状态文件格式无效，为避免重复发送已停止")
    state.setdefault("version", 1)
    state.setdefault("days", {})
    return state


def save_state(state: dict) -> None:
    path = _state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    days = state.setdefault("days", {})
    # Dashboard 展示最近 30 天；状态本身很小，保留 30 天即可。
    for old_day in sorted(days)[:-30]:
        days.pop(old_day, None)

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


def _record(state: dict, username: str, target: str, day: str | None = None):
    return (
        state.get("days", {})
        .get(day or _today(), {})
        .get(username, {})
        .get(norm(target))
    )


def _set_record(state: dict, username: str, target: str, record: dict, day: str | None = None):
    account = state.setdefault("days", {}).setdefault(day or _today(), {}).setdefault(username, {})
    account[norm(target)] = record
    save_state(state)


def pending_targets(username: str, targets: list[str], logger) -> list[str]:
    state = load_state(logger)
    pending = []
    for target in targets:
        record = _record(state, username, target)
        if record and record.get("status") == "confirmed":
            logger.info(f"账号 {username} 好友 {target} 今日已确认发送，跳过")
        else:
            pending.append(target)
    return pending


def dismiss_trust_login_dialog(page, config, logger) -> bool:
    try:
        dialog = page.locator(TRUST_LOGIN_DIALOG_SELECTOR)
        if dialog.count() == 0 or not dialog.first.is_visible():
            return False
        clicked = dialog.first.evaluate(
            """
            (root) => {
              const cancel = Array.from(root.querySelectorAll('*')).find(
                (el) => (el.innerText || '').trim() === '取消'
              );
              if (!cancel) return false;
              cancel.dispatchEvent(new MouseEvent('mousedown', {
                bubbles: true, button: 0, buttons: 1
              }));
              cancel.click();
              return true;
            }
            """
        )
        if clicked:
            page.wait_for_selector(
                TRUST_LOGIN_DIALOG_SELECTOR,
                state="hidden",
                timeout=min(config["browserTimeout"], 10_000),
            )
        return bool(clicked)
    except Exception as exc:
        logger.warning(f"关闭登录信息弹窗失败：{exc}")
        return False


def wait_chat_ready(page, config, logger) -> None:
    page.wait_for_selector(CONVERSATION_LIST_SELECTOR, timeout=config["browserTimeout"])
    page.wait_for_selector(CONVERSATION_ITEM_SELECTOR, timeout=config["browserTimeout"])
    time.sleep(max(config["friendListTimeout"], 0) / 1000)
    dismiss_trust_login_dialog(page, config, logger)


def active_conversation(page) -> str | None:
    header = page.locator(RIGHT_PANEL_TITLE_SELECTOR)
    try:
        if header.count() == 0 or not header.first.is_visible():
            return None
        return norm(header.first.inner_text()) or None
    except Exception:
        return None


def _find_visible_target(page, target: str):
    target = norm(target)
    try:
        elements = page.locator(CONVERSATION_ITEM_SELECTOR).all()
    except Exception:
        return None
    for element in elements:
        try:
            title = norm(element.locator(CONVERSATION_TITLE_SELECTOR).inner_text())
        except Exception:
            continue
        if title == target:
            return element
    return None


def activate_conversation(page, element, username: str, target: str, config, logger) -> None:
    """用抖音实际的 mousedown 事件切换会话，并以右侧标题作为成功判据。"""
    target = norm(target)
    retries = max(config["taskRetryTimes"], 1)
    last_active = active_conversation(page)

    for attempt in range(retries):
        dismiss_trust_login_dialog(page, config, logger)
        current = _find_visible_target(page, target) or element
        try:
            current.dispatch_event("mousedown", {"button": 0, "buttons": 1})
        except Exception as exc:
            logger.warning(
                f"账号 {username} 激活好友 {target} 失败 ({attempt + 1}/{retries})：{exc}"
            )
        else:
            deadline = time.monotonic() + min(config["browserTimeout"], 15_000) / 1000
            while time.monotonic() < deadline:
                dismiss_trust_login_dialog(page, config, logger)
                if active_conversation(page) == target:
                    return
                time.sleep(0.25)

        last_active = active_conversation(page)
        if attempt < retries - 1:
            time.sleep(0.5)

    raise RuntimeError(
        f"账号 {username} 无法确认已切换到好友 {target}，"
        f"当前聊天对象: {last_active or '未打开'}；为避免误发已停止任务"
    )


def _verification_text(message: str) -> str:
    visible = re.sub(r"\[[^\[\]]+\]", "", message or "")
    return norm(visible.replace("\\n", "\n"))


def _verification_text_from_record(record: dict) -> str:
    return norm(
        record.get("verification_text")
        or re.sub(r"\[[^\[\]]+\]", "", record.get("message", "")).replace("\\n", "\n")
    )


def _canonical_match_text(text: str) -> str:
    """Canonical form for persisted-message matching.

    Douyin's rich-text editor can collapse spaces adjacent to native emoji
    nodes or turn them into line breaks.  Those whitespace-only differences
    are presentation details, so matching ignores whitespace while preserving
    every non-whitespace character.
    """
    return re.sub(r"\s+", "", norm(text or ""))


def _outgoing_match_count(page, expected: str) -> int:
    expected = _canonical_match_text(expected)
    if not expected:
        return 0
    try:
        texts = page.locator(OUTGOING_MESSAGE_SELECTOR).all_inner_texts()
    except Exception:
        return 0
    return sum(1 for text in texts if _canonical_match_text(text) == expected)


def _sticker_resource_key(src: str) -> str:
    """Return the stable basename Douyin uses for one native sticker asset."""
    try:
        return urlsplit(src or "").path.rsplit("/", 1)[-1]
    except Exception:
        return ""


def _outgoing_sticker_snapshot(page, resource_key: str) -> dict:
    """Snapshot matching native stickers and their stable virtual message IDs."""
    resource_key = str(resource_key or "").strip()
    empty = {
        "matching_ids": [],
        "matching_count": 0,
        "identified_outgoing_count": 0,
        "outgoing_count": 0,
    }
    if not resource_key:
        return dict(empty)
    try:
        snapshot = page.evaluate(
            """
            (resourceKey) => {
              const boxes = Array.from(document.querySelectorAll(
                '.messageMessageBoxcontentBox.messageMessageBoxisFromMe'
              ));

              function virtualIdFor(box) {
                const row = box.closest('[data-index]');
                if (!row || !row.parentElement) return '';
                const index = Number(row.getAttribute('data-index'));
                if (!Number.isInteger(index) || index < 0) return '';
                const host = row.parentElement;
                const roots = [];
                for (const key of Object.keys(host)) {
                  try {
                    if (key.startsWith('__reactProps$')) {
                      roots.push(host[key] && host[key].children);
                    } else if (key.startsWith('__reactFiber$')) {
                      roots.push(host[key] && host[key].pendingProps && host[key].pendingProps.children);
                    }
                  } catch (_) {}
                }
                for (const root of roots) {
                  const children = Array.isArray(root) ? root : [root];
                  const child = children[index];
                  const id = child && child.props && child.props.virtualItem && child.props.virtualItem.id;
                  if (id) return String(id);
                }
                return '';
              }

              const matchingIds = [];
              let matchingCount = 0;
              let identifiedOutgoingCount = 0;
              for (const box of boxes) {
                const id = virtualIdFor(box);
                if (id) identifiedOutgoingCount += 1;
                const matches = Array.from(box.querySelectorAll('img')).some(
                  image => String(image.getAttribute('src') || '').includes(resourceKey)
                );
                if (!matches) continue;
                matchingCount += 1;
                if (id) matchingIds.push(id);
              }
              return {
                matching_ids: matchingIds,
                matching_count: matchingCount,
                identified_outgoing_count: identifiedOutgoingCount,
                outgoing_count: boxes.length,
              };
            }
            """,
            resource_key,
        )
    except Exception:
        return dict(empty)
    if not isinstance(snapshot, dict):
        return dict(empty)
    snapshot["matching_ids"] = [
        str(value) for value in snapshot.get("matching_ids", []) if value
    ]
    for key in ("matching_count", "identified_outgoing_count", "outgoing_count"):
        snapshot[key] = int(snapshot.get(key, 0) or 0)
    return snapshot


def _prepare_native_sticker(page, sticker_name: str, config):
    """Open sticker panel and return exact item without clicking the item."""
    sticker_name = norm(sticker_name)
    if not sticker_name:
        raise RuntimeError("原生贴纸名称为空")

    panel = page.locator(STICKER_PANEL_SELECTOR).first
    try:
        panel_visible = bool(panel.count() and panel.is_visible())
    except Exception:
        panel_visible = False
    if not panel_visible:
        button = page.locator(STICKER_BUTTON_SELECTOR)
        if button.count() == 0 or not button.first.is_visible():
            raise RuntimeError("未找到可见的抖音表情按钮")
        # CloakBrowser 当前页面上物理 click 不会触发这个 React 控件。
        # synthetic click 这里只打开面板，不发送任何消息。
        button.first.dispatch_event("click")
        page.wait_for_selector(
            STICKER_PANEL_SELECTOR,
            state="visible",
            timeout=min(config.get("browserTimeout", 120_000), 10_000),
        )
        panel = page.locator(STICKER_PANEL_SELECTOR).first

    items = panel.locator(STICKER_ITEM_SELECTOR)
    for index in range(items.count()):
        item = items.nth(index)
        desc = item.locator(STICKER_DESC_SELECTOR)
        if not desc.count() or norm(desc.first.inner_text()) != sticker_name:
            continue
        image = item.locator("img").first
        src = image.get_attribute("src") if image.count() else ""
        resource_key = _sticker_resource_key(src)
        if not resource_key:
            raise RuntimeError(f"原生贴纸 {sticker_name} 缺少可验证的资源标识")
        return item, resource_key, _outgoing_sticker_snapshot(page, resource_key)

    raise RuntimeError(f"在抖音表情面板中找不到原生贴纸: {sticker_name}")


def _type_message(page, username: str, friend: str, message: str, config):
    page.wait_for_selector(
        CHAT_EDITABLE_SELECTOR,
        state="visible",
        timeout=config["browserTimeout"],
    )
    editor = page.locator(CHAT_EDITABLE_SELECTOR).first
    if norm(editor.inner_text()):
        editor.focus()
        human_pause(0.08, 0.18)
        # Slate 中第一次 Ctrl+A 可能只选中当前块；第二次才稳定全选草稿。
        page.keyboard.press("Control+A")
        human_pause(0.04, 0.09)
        page.keyboard.press("Control+A")
        human_pause(0.05, 0.11)
        page.keyboard.press("Backspace")
        human_pause(0.12, 0.28)
    if norm(editor.inner_text()):
        raise RuntimeError(
            f"账号 {username} 好友 {friend} 输入框存在无法清理的旧草稿，已阻止发送"
        )
    editor.focus()
    # 聚焦后留一个很短的自然反应时间，再开始输入第一字符。
    human_pause(0.12, 0.30)
    for kind, value in _message_input_tokens(message):
        if kind == "shortcode":
            # 抖音会在逐字输入过程中提前解析 [display_name]；整块插入才稳定。
            page.keyboard.insert_text(value)
            human_pause(0.06, 0.16)
        elif kind == "newline":
            # 官方实现使用 Shift+Enter；保留键盘路径，不把换行当成整段文本注入。
            editor.press("Shift+Enter", force=True)
            human_pause(0.06, 0.18)
        else:
            _human_insert_text(page, value)
    human_pause(0.25, 0.65)
    if not norm(editor.inner_text()):
        raise RuntimeError(f"账号 {username} 好友 {friend} 输入后仍为空，已阻止发送")


def _open_target(page, username: str, target: str, config, logger, select_friend) -> bool:
    wait_chat_ready(page, config, logger)
    for selected in select_friend(page, username, [target]):
        return norm(selected) == norm(target)
    return False


def verify_persisted(
    context,
    username: str,
    target: str,
    expected: str,
    baseline_count: int,
    config,
    logger,
    select_friend,
    attempts: int = 3,
    delay: float = 5,
) -> bool:
    """从全新页面重新拉取聊天记录；仅精确匹配本次文案，不用总消息数兜底。"""
    for attempt in range(max(1, attempts)):
        verify_page = context.new_page()
        try:
            verify_page.goto("https://www.douyin.com/chat", wait_until="domcontentloaded")
            if _open_target(verify_page, username, target, config, logger, select_friend):
                time.sleep(1)
                if _outgoing_match_count(verify_page, expected) > baseline_count:
                    return True
        except Exception as exc:
            logger.warning(
                f"账号 {username} 好友 {target} 第 {attempt + 1}/{attempts} 次持久化检查失败：{exc}"
            )
        finally:
            verify_page.close()
        if attempt < attempts - 1:
            time.sleep(delay)
    return False


def verify_sticker_persisted(
    context,
    username: str,
    target: str,
    resource_key: str,
    baseline_message_ids,
    config,
    logger,
    select_friend,
    attempts: int = 3,
    delay: float = 5,
) -> bool:
    """Fresh-page verify a native sticker by a newly persisted message ID."""
    baseline_ids = {str(value) for value in (baseline_message_ids or []) if value}
    for attempt in range(max(1, attempts)):
        verify_page = context.new_page()
        try:
            verify_page.goto("https://www.douyin.com/chat", wait_until="domcontentloaded")
            if _open_target(verify_page, username, target, config, logger, select_friend):
                time.sleep(1)
                snapshot = _outgoing_sticker_snapshot(verify_page, resource_key)
                current_ids = set(snapshot["matching_ids"])
                if current_ids - baseline_ids:
                    return True
        except Exception as exc:
            logger.warning(
                f"账号 {username} 好友 {target} 第 {attempt + 1}/{attempts} 次贴纸持久化检查失败：{exc}"
            )
        finally:
            verify_page.close()
        if attempt < attempts - 1:
            time.sleep(delay)
    return False


def deliver_once(
    context,
    page,
    username: str,
    friend: str,
    message_factory,
    config,
    logger,
    select_friend,
) -> bool:
    """一天内对一个好友最多派发一次发送事件；不确定时宁可漏发也不自动重发。"""
    friend = norm(friend)
    state = load_state(logger)
    record = _record(state, username, friend) or {}

    if record.get("status") == "confirmed":
        logger.info(f"账号 {username} 好友 {friend} 今日已确认发送，跳过")
        return True

    if record.get("status") == "attempted":
        delivery_kind = record.get("delivery_kind", "text")
        confirmed = False
        if delivery_kind == "douyin_sticker":
            resource_key = str(record.get("resource_key") or "")
            baseline_ids = record.get("baseline_message_ids") or []
            if resource_key:
                confirmed = verify_sticker_persisted(
                    context,
                    username,
                    friend,
                    resource_key,
                    baseline_ids,
                    config,
                    logger,
                    select_friend,
                )
        else:
            expected = _verification_text_from_record(record)
            baseline = int(record.get("baseline_count", 0) or 0)
            if expected:
                confirmed = verify_persisted(
                    context,
                    username,
                    friend,
                    expected,
                    baseline,
                    config,
                    logger,
                    select_friend,
                )
        if confirmed:
            record["status"] = "confirmed"
            record["confirmed_at"] = time.time()
            _set_record(state, username, friend, record)
            logger.info(f"账号 {username} 好友 {friend} 已确认上次发送服务器侧存在")
            return True
        logger.error(
            f"账号 {username} 好友 {friend} 今日已有 attempted 记录但仍无法确认；"
            "为避免重复发送，本日不会自动再次派发"
        )
        return False

    if active_conversation(page) != friend:
        raise RuntimeError(
            f"账号 {username} 发送前会话校验失败：目标 {friend}，"
            f"当前 {active_conversation(page) or '未打开'}"
        )

    delivery_mode = str(config.get("deliveryMode", "text") or "text").strip().lower()
    if delivery_mode == "native_sticker":
        sticker_name = norm(config.get("nativeStickerName", "续火花"))
        item, resource_key, baseline_snapshot = _prepare_native_sticker(
            page, sticker_name, config
        )

        # If Douyin changes the virtual-list internals, fail before the
        # irreversible click rather than silently degrading to a weak counter.
        if (
            baseline_snapshot["outgoing_count"] > 0
            and baseline_snapshot["identified_outgoing_count"] == 0
        ):
            raise RuntimeError("无法读取抖音消息稳定 ID，已阻止原生贴纸发送")
        if len(baseline_snapshot["matching_ids"]) < baseline_snapshot["matching_count"]:
            raise RuntimeError("部分历史同款贴纸缺少稳定消息 ID，已阻止原生贴纸发送")

        # Opening the popup must never weaken recipient binding. Re-check the
        # active title immediately before recording attempted + dispatching.
        if active_conversation(page) != friend:
            raise RuntimeError(
                f"账号 {username} 贴纸发送前会话校验失败：目标 {friend}，"
                f"当前 {active_conversation(page) or '未打开'}"
            )

        record = {
            "status": "attempted",
            "delivery_kind": "douyin_sticker",
            "sticker_name": sticker_name,
            "resource_key": resource_key,
            "baseline_message_ids": baseline_snapshot["matching_ids"],
            "baseline_count": baseline_snapshot["matching_count"],
            "attempted_at": time.time(),
        }
        _set_record(state, username, friend, record)

        try:
            # This is the only irreversible UI action. Never click again and
            # never press the regular send button as an automatic fallback.
            item.dispatch_event("click")
        except Exception as exc:
            record["dispatch_error"] = str(exc)
            _set_record(state, username, friend, record)
            logger.error(
                f"账号 {username} 好友 {friend} 原生贴纸事件结果未知：{exc}；"
                "已进入 at-most-once 保护，不会自动重发"
            )
        else:
            logger.info(
                f"账号 {username} 已向好友 {friend} 派发 1 次原生贴纸 {sticker_name}"
            )

        if verify_sticker_persisted(
            context,
            username,
            friend,
            resource_key,
            baseline_snapshot["matching_ids"],
            config,
            logger,
            select_friend,
        ):
            record["status"] = "confirmed"
            record["confirmed_at"] = time.time()
            _set_record(state, username, friend, record)
            logger.info(
                f"账号 {username} 好友 {friend} 已通过全新页面确认原生贴纸持久化"
            )
            return True

        logger.error(
            f"账号 {username} 好友 {friend} 原生贴纸暂未确认服务器持久化；"
            "状态保留 attempted，本日不会自动重发"
        )
        return False

    if delivery_mode != "text":
        raise RuntimeError(f"不支持的 DELIVERY_MODE: {delivery_mode}")

    message = message_factory()
    _type_message(page, username, friend, message, config)
    expected = _verification_text(message)
    baseline = _outgoing_match_count(page, expected)

    # 明确的“尚未派发”错误可以安全失败；只有进入 dispatch_event 前才锁定 attempted。
    button = page.locator(SEND_BUTTON_SELECTOR)
    if button.count() == 0 or not button.first.is_visible():
        raise RuntimeError("未找到可见的抖音发送按钮")

    # 先落 attempted 再触发发送：即使进程恰好在 click 附近崩溃，也不会自动重发。
    record = {
        "status": "attempted",
        "delivery_kind": "text",
        "verification_text": expected,
        "baseline_count": baseline,
        "attempted_at": time.time(),
    }
    _set_record(state, username, friend, record)

    try:
        button.first.dispatch_event("click")
    except Exception as exc:
        # click 失败也无法证明事件一定没到页面；保持 attempted，绝不自动补发。
        record["dispatch_error"] = str(exc)
        _set_record(state, username, friend, record)
        logger.error(
            f"账号 {username} 好友 {friend} 发送事件结果未知：{exc}；"
            "已进入 at-most-once 保护，不会自动重发"
        )
    else:
        logger.info(f"账号 {username} 已向好友 {friend} 派发 1 次发送事件")

    if verify_persisted(
        context,
        username,
        friend,
        expected,
        baseline,
        config,
        logger,
        select_friend,
    ):
        record["status"] = "confirmed"
        record["confirmed_at"] = time.time()
        _set_record(state, username, friend, record)
        logger.info(f"账号 {username} 好友 {friend} 已通过全新页面确认消息持久化")
        return True

    logger.error(
        f"账号 {username} 好友 {friend} 暂未确认服务器持久化；"
        "状态保留 attempted，本日不会自动重发"
    )
    return False
