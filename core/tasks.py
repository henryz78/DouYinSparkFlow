import json
import os
import re
import traceback
from utils.logger import setup_logger
from utils.config import get_config, get_userData
from utils import norm
from core.msg_builder import build_message
from core.browser import get_browser
import time

config = get_config()
userData = get_userData()
logger = setup_logger(level=config.get("logLevel", "Info"))

CONVERSATION_ITEM_SELECTOR = ".conversationConversationItemwrapper"
CONVERSATION_TITLE_SELECTOR = ".conversationConversationItemtitle"
CONVERSATION_LIST_SELECTOR = ".conversationConversationListwrapper"
CHAT_EDITOR_SELECTOR = ".messageEditorimChatEditorContainer"
CHAT_EDITABLE_SELECTOR = f'{CHAT_EDITOR_SELECTOR} [contenteditable="true"]'
SEND_BUTTON_SELECTOR = ".e2e-send-msg-btn"
RIGHT_PANEL_TITLE_SELECTOR = ".RightPanelHeadertitle"
TRUST_LOGIN_DIALOG_SELECTOR = ".trust-login-dialog-mask"
OUTGOING_MESSAGE_SELECTOR = ".messageMessageBoxcontentBox.messageMessageBoxisFromMe"
SEND_STATE_FILE = os.getenv("SEND_STATE_FILE", "logs/send_state.json")


class SendDispatchError(RuntimeError):
    """发送按钮事件派发过程报错；结果未知，必须先独立核验再决定是否重试。"""


def retry_operation(name, operation, retries=3, delay=2, *args, **kwargs):
    """
    通用的重试逻辑
    :param name: 操作名称（用于日志记录）
    :param operation: 要执行的异步操作
    :param retries: 最大重试次数
    :param delay: 每次重试之间的延迟（秒）
    :param args: 传递给操作的参数
    :param kwargs: 传递给操作的关键字参数
    """
    for attempt in range(retries):
        try:
            return operation(*args, **kwargs)
        except Exception as e:
            if attempt < retries - 1:
                logger.warning(f"{name} 失败，正在重试第 {attempt + 1} 次，错误：{e}")
                time.sleep(delay)
            else:
                logger.error(f"{name} 失败，已达到最大重试次数，错误：{e}")
                raise

def checkTargetName(targetName, targets):
    """检查 targetName 是否在目标列表里。

    命中就返回归一化后的名字，没命中返回 None。
    返回名字而不是 True/False，是因为调用方要拿它记账：yield 出去当好友名、
    从 remaining_targets 里扣掉 —— 返回布尔值这两件事都做不成。

    前提：targets 必须是归一化过的（见 runTasks），两边都归过才谈得上相等。
    """
    name = norm(targetName)
    return name if name in targets else None


def _send_day():
    """返回当前运行环境的本地日期（Docker cron 已按配置 TZ 启动 Python）。"""
    return time.strftime("%Y-%m-%d")


def load_send_state():
    """读取每日发送状态；损坏文件按空状态处理，但会留下告警。"""
    if not os.path.exists(SEND_STATE_FILE):
        return {"version": 1, "days": {}}
    try:
        with open(SEND_STATE_FILE, "r", encoding="utf-8") as f:
            state = json.load(f)
        if not isinstance(state, dict):
            raise ValueError("state root is not an object")
        state.setdefault("version", 1)
        state.setdefault("days", {})
        return state
    except Exception as e:
        logger.warning(f"读取发送状态失败，将按空状态继续：{e}")
        return {"version": 1, "days": {}}


def save_send_state(state):
    """原子写入发送状态，避免容器中途退出留下半个 JSON。"""
    directory = os.path.dirname(SEND_STATE_FILE) or "."
    os.makedirs(directory, exist_ok=True)

    # 只保留最近 7 个日期，避免状态文件无限增长。
    days = state.setdefault("days", {})
    for old_day in sorted(days)[:-7]:
        days.pop(old_day, None)

    tmp = f"{SEND_STATE_FILE}.{os.getpid()}.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, SEND_STATE_FILE)


def get_send_record(state, username, target, day=None):
    day = day or _send_day()
    return (
        state.get("days", {})
        .get(day, {})
        .get(username, {})
        .get(norm(target))
    )


def set_send_record(state, username, target, record, day=None):
    day = day or _send_day()
    account = state.setdefault("days", {}).setdefault(day, {}).setdefault(username, {})
    account[norm(target)] = record
    save_send_state(state)


def outgoing_message_texts(page):
    """返回当前会话中已渲染的、由自己发送的文本消息。"""
    try:
        return [
            norm(text)
            for text in page.locator(OUTGOING_MESSAGE_SELECTOR).all_inner_texts()
            if norm(text)
        ]
    except Exception:
        return []


def verification_text_from_message(message):
    """得到发送后聊天气泡中可见的文本。

    抖音会把 `[盖瑞]` / `[加一]` 这类表情码渲染成非文本节点，所以编辑器里的
    innerText 和最终气泡的 innerText 不完全相同。去掉方括号表情码后再归一化，
    才能跨“编辑器 -> 已发送气泡”做稳定确认。
    """
    visible = re.sub(r"\[[^\[\]]+\]", "", message or "")
    # 配置里的换行历史上以字面量 "\\n" 保存，输入时再用 Shift+Enter 还原。
    visible = visible.replace("\\n", "\n")
    return norm(visible)


def verification_text_from_record(record):
    """返回最可靠的已发送气泡确认文本。

    CloakBrowser 向 Slate 编辑器逐字输入时，抖音会把类似 ``[盖瑞]``、``[加一]``
    的方括号标记在编辑器阶段改写成最终可见文本；因此真正可靠的值是发送前从
    contenteditable 里读回来的 ``effective_text``。旧状态没有该字段时，才回退到
    之前保存的 verification_text / 原始 message 推导值。
    """
    record = record or {}
    return norm(
        record.get("verification_text")
        or record.get("effective_text")
        or verification_text_from_message(record.get("message", ""))
    )


def has_outgoing_message(page, expected_text):
    expected = norm(expected_text or "")
    if not expected:
        return False
    return expected in outgoing_message_texts(page)


def outgoing_message_match_count(page, expected_text):
    expected = norm(expected_text or "")
    if not expected:
        return 0
    return sum(1 for text in outgoing_message_texts(page) if text == expected)


def outgoing_message_count(page):
    """当前已渲染的本人消息气泡数量。用于本次发送前后做增量确认。"""
    return len(outgoing_message_texts(page))


def wait_for_outgoing_message(
    page,
    target,
    expected_text,
    baseline_count=0,
    baseline_total=None,
    timeout_ms=20_000,
):
    """发送后等待目标会话中出现新的本人消息。

    优先用同文案计数确认；同时允许“本人消息总数增加”作为本次实时发送的兜底。
    后者只用于同一个页面、同一个会话的发送前后比较，避免表情渲染或换行重排
    导致文本确认假阴性。
    """
    target = norm(target)
    expected = norm(expected_text or "")
    deadline = time.monotonic() + timeout_ms / 1000
    while time.monotonic() < deadline:
        if get_active_conversation_name(page) != target:
            raise RuntimeError(
                f"发送后会话发生切换：目标 {target}，"
                f"当前 {get_active_conversation_name(page) or '未打开'}"
            )
        if outgoing_message_match_count(page, expected) > baseline_count:
            return True
        if baseline_total is not None and outgoing_message_count(page) > baseline_total:
            return True
        time.sleep(0.25)
    return False


def click_send_button_once(page):
    """原生触发一次抖音发送按钮。

    CloakBrowser 的 humanized locator.click/press 会额外插入可操作性逻辑；聊天页实测
    会出现“输入框被清空但没有真正发出”的情况。这里使用页面自己的 e2e 发送按钮，
    直接调用 DOM click()，一次调用只产生一个 click 事件。
    """
    button = page.locator(SEND_BUTTON_SELECTOR)
    if button.count() == 0:
        raise RuntimeError("未找到抖音发送按钮")
    button = button.first
    if not button.is_visible():
        raise RuntimeError("抖音发送按钮当前不可见")
    try:
        # 发送控件本身是 SVGElement，不存在 HTMLElement.click()；dispatch_event
        # 可以直接对 SVG 派发一次标准 click，并且不会走 CloakBrowser humanized click。
        button.dispatch_event("click")
    except Exception as e:
        raise SendDispatchError(f"派发发送按钮 click 事件失败：{e}") from e


def send_and_confirm_once(
    page,
    chat_input,
    username,
    target,
    verification_text,
    baseline_count,
    baseline_total,
):
    """只派发一次发送事件，并在当前页面做一次快速确认。

    这里故意不做任何“再次点击发送”重试。即使草稿仍在，也不能证明第一次点击
    没有被服务端接收；重复点击正是旧实现产生重复消息的风险来源。真正是否允许
    再发，由上层在“全新页面重新拉取聊天记录”后决定。
    """
    target = norm(target)
    active = get_active_conversation_name(page)
    if active != target:
        raise RuntimeError(
            f"账号 {username} 点击发送前会话校验失败：目标 {target}，"
            f"当前 {active or '未打开'}"
        )

    click_send_button_once(page)
    logger.info(f"账号 {username} 已向好友 {target} 派发 1 次发送事件，正在确认结果")

    return wait_for_outgoing_message(
        page,
        target,
        verification_text,
        baseline_count=baseline_count,
        baseline_total=baseline_total,
        timeout_ms=min(config["browserTimeout"], 10_000),
    )


def dismiss_trust_login_dialog(page):
    """关闭抖音偶发的“是否保存登录信息”全屏遮罩。

    这个遮罩会盖住整个会话列表。CloakBrowser 的 force=True 会绕过
    pointer-events 检查，但不保证点击事件真的落在好友项上，因此必须先显式关闭。
    """
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
                bubbles: true,
                button: 0,
                buttons: 1,
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
            logger.debug("已关闭“是否保存登录信息”弹窗")
        return bool(clicked)
    except Exception as e:
        logger.warning(f"关闭登录信息弹窗失败：{e}")
        return False


def get_active_conversation_name(page):
    """读取右侧聊天面板当前真正打开的会话名。"""
    header = page.locator(RIGHT_PANEL_TITLE_SELECTOR)
    if header.count() == 0:
        return None
    try:
        if not header.first.is_visible():
            return None
        name = norm(header.first.inner_text())
        return name or None
    except Exception:
        return None


def wait_for_active_conversation(page, target, timeout_ms=None):
    """等待右侧聊天标题切到 target；仅输入框出现不算成功。"""
    target = norm(target)
    if timeout_ms is None:
        timeout_ms = min(config["browserTimeout"], 15_000)

    deadline = time.monotonic() + max(timeout_ms, 0) / 1000
    while True:
        dismiss_trust_login_dialog(page)
        if get_active_conversation_name(page) == target:
            return True
        if time.monotonic() >= deadline:
            return False
        time.sleep(0.25)


def find_visible_conversation_element(page, target):
    """在当前已渲染的会话列表里重新按标题定位 target。

    会话在发送新消息后会重新排序，而 Playwright 的 ``nth`` locator 是动态解析的；
    因此“几秒前代表 Ken 的 locator”稍后可能已经代表另一行。每次真正派发
    mousedown 前重新按标题找一次，可以避免 stale nth 把事件打到错误好友。
    """
    target = norm(target)
    try:
        elements = page.locator(CONVERSATION_ITEM_SELECTOR).all()
    except Exception:
        return None

    for candidate in elements:
        try:
            title = norm(candidate.locator(CONVERSATION_TITLE_SELECTOR).inner_text())
        except Exception:
            continue
        if title == target:
            return candidate
    return None


def activate_conversation(page, element, username, target):
    """点击好友并确认右侧面板真的切到了该好友，否则停止任务。

    抖音当前会话项的 React 事件绑定在 onMouseDown，而不是 onClick。
    所以直接派发 mousedown，再以右侧标题作为唯一成功判据；不能只相信
    click() 没报错，否则可能复用上一个会话的输入框并把消息错发给同一个人。
    """
    retries = max(config["taskRetryTimes"], 1)
    last_active = get_active_conversation_name(page)

    for attempt in range(retries):
        dismiss_trust_login_dialog(page)
        # 列表可能因为新消息实时重排；优先用当前 DOM 重新定位目标，避免旧 nth locator
        # 已经指向其他好友。测试桩/极端情况下找不到时再退回调用方刚拿到的 element。
        current_element = find_visible_conversation_element(page, target) or element
        try:
            current_element.dispatch_event(
                "mousedown",
                {"button": 0, "buttons": 1},
            )
        except Exception as e:
            logger.warning(
                f"账号 {username} 激活好友 {target} 失败 "
                f"({attempt + 1}/{retries})：{e}"
            )
        else:
            if wait_for_active_conversation(page, target):
                logger.debug(f"账号 {username} 已确认当前聊天对象为 {target}")
                return

        last_active = get_active_conversation_name(page)
        logger.warning(
            f"账号 {username} 激活好友 {target} 后未切换成功 "
            f"({attempt + 1}/{retries})，当前聊天对象: {last_active or '未打开'}"
        )
        if attempt < retries - 1:
            time.sleep(0.5)

    raise RuntimeError(
        f"账号 {username} 无法确认已切换到好友 {target}，"
        f"当前聊天对象: {last_active or '未打开'}；为避免误发已停止任务"
    )


def scroll_and_select_user(page, username, targets):
    """尝试滚动并查找用户名"""
    # 定义目标元素和滚动容器的选择器
    target_selector = CONVERSATION_ITEM_SELECTOR
    scrollable_friends_selector = CONVERSATION_LIST_SELECTOR

    # [修复] 使用模糊匹配 no-more-tip- 前缀，不再依赖精确哈希后缀
    # 同时增加文本匹配作为兜底
    # no_more_selector = 'xpath=//div[contains(@class, "no-more-tip-")]'
    # loading_selector = 'xpath=//div[contains(@class, "semi-spin")]'

    logger.debug(f"账号 {username} 开始查找目标好友列表")
    logger.debug(f"账号 {username} 目标好友列表: {targets}")

    found_targets = set()
    # [修改] 复制一份目标列表用于追踪进度
    remaining_targets = set(targets)

    # [修复] 新增：连续空滚动计数器（滚动后没有发现新好友的次数）
    empty_scroll_count = 0
    MAX_EMPTY_SCROLLS = 10  # 连续10次滚动没有新好友，认为到底了

    while True:
        # 查找所有目标元素
        target_elements = page.locator(target_selector).all()

        # [修复] 记录本轮循环前已发现的好友数，用于判断是否有新发现
        prev_found_count = len(found_targets)

        for element in target_elements:
            try:
                # 查找子元素 span，模糊匹配 class
                span = element.locator(CONVERSATION_TITLE_SELECTOR)
                targetName = span.inner_text()

                if targetName in found_targets:
                    continue  # 已处理过，跳过

                logger.debug(f"账号 {username} 找到好友 {targetName}")
                
                targetSymbol = checkTargetName(targetName, targets)

                if targetSymbol:
                    activate_conversation(page, element, username, targetSymbol)
                    found_targets.add(targetName)
                    
                    yield targetSymbol

                    # [修改] 标记已找到，如果全找到了直接退出
                    if targetSymbol in remaining_targets:
                        remaining_targets.remove(targetSymbol)
                    if len(remaining_targets) == 0:
                        logger.debug(f"账号 {username} 所有目标好友均已找到，停止搜索")
                        return
                    break
                else:
                    # 非目标好友扫描一次即可；目标好友必须等点击成功后才能标记已处理。
                    found_targets.add(targetName)
            except RuntimeError:
                # 会话激活/校验失败属于安全错误，必须停止当前账号任务，不能吞掉后继续发送。
                raise
            except Exception as e:
                traceback.print_exc()
        else:
            # [修复] 检查本轮是否有新好友被发现
            new_found = len(found_targets) > prev_found_count
            if new_found:
                empty_scroll_count = 0  # 有新发现，重置计数器
            else:
                empty_scroll_count += 1  # 无新发现，递增计数器

            # [修复] 状态检测逻辑（多重兜底）

            # # 1. 检查是否到底（"没有更多了" —— 使用模糊类名匹配）
            # if page.locator(no_more_selector).count() > 0:
            #     logger.info(f"账号 {username} 检测到'没有更多了'标志，已到达底部")
            #     if len(remaining_targets) > 0:
            #         logger.warning(
            #             f"账号 {username} 搜索结束，仍有以下好友未找到: {remaining_targets}"
            #         )
            #     break

            # 2. [修复] 检查连续空滚动次数，防止死循环
            if empty_scroll_count >= MAX_EMPTY_SCROLLS:
                logger.warning(
                    f"账号 {username} 连续 {MAX_EMPTY_SCROLLS} 次滚动未发现新好友，判定已到达底部"
                )
                if len(remaining_targets) > 0:
                    logger.warning(
                        f"账号 {username} 搜索结束，仍有以下好友未找到: {remaining_targets}"
                    )
                break

            # 3. 检查是否正在加载
            # if page.locator(loading_selector).count() > 0:
            #     logger.debug(f"账号 {username} 列表正在加载中 (Loading)...")
            #     time.sleep(1.5)  # 给加载留点时间
            #     # 不 break，继续去滚动以触发后续内容

            # 4. 滚动容器
            scrollable_element = page.locator(
                scrollable_friends_selector
            ).element_handle()

            if scrollable_element:
                # [修复] 记录滚动前的 scrollTop，用于检测是否真的滚动了
                scroll_top_before = page.evaluate(
                    "(element) => element.scrollTop", scrollable_element
                )

                page.evaluate(
                    "(element) => element.scrollTop += 800", scrollable_element
                )

                # [修复] 检测滚动后的 scrollTop
                time.sleep(0.3)
                scroll_top_after = page.evaluate(
                    "(element) => element.scrollTop", scrollable_element
                )

                if scroll_top_before == scroll_top_after:
                    # scrollTop 没有变化，说明已经到底了
                    empty_scroll_count += 2  # 加速判定到底
                    logger.debug(
                        f"账号 {username} scrollTop 未变化 ({scroll_top_before})，可能已到底 (空滚动计数: {empty_scroll_count}/{MAX_EMPTY_SCROLLS})"
                    )
                else:
                    logger.debug(
                        f"账号 {username} 滚动好友列表以加载更多好友 (scrollTop: {scroll_top_before} -> {scroll_top_after})"
                    )

                time.sleep(1.5)
            else:
                logger.error(f"账号 {username} 未找到滚动容器，退出")
                break


def verify_persisted_outgoing_message(
    context,
    username,
    target,
    expected_text,
    baseline_count=0,
    baseline_total=None,
    attempts=3,
    delay=5,
):
    """用全新页面重新拉取聊天记录，确认消息确实已在服务器侧持久化。

    当前抖音 Web 会先在本地插入“乐观消息”节点；服务器拒绝后该节点会消失。
    因此当前页面里看到新气泡不能作为最终成功判据。这里每次都开一个新 page，
    重新进入 /chat、重新激活目标好友，再检查同文案气泡数量是否超过发送前基线。
    """
    target = norm(target)
    expected_text = norm(expected_text or "")
    attempts = max(int(attempts or 1), 1)

    for attempt in range(attempts):
        verify_page = context.new_page()
        try:
            retry_operation(
                f"重新加载好友 {target} 的聊天记录",
                verify_page.goto,
                retries=max(config["taskRetryTimes"], 1),
                delay=2,
                url="https://www.douyin.com/chat",
                wait_until="domcontentloaded",
            )
            verify_page.wait_for_selector(
                CONVERSATION_LIST_SELECTOR,
                timeout=config["browserTimeout"],
            )
            verify_page.wait_for_selector(
                CONVERSATION_ITEM_SELECTOR,
                timeout=config["browserTimeout"],
            )
            time.sleep(max(config["friendListTimeout"], 0) / 1000)
            dismiss_trust_login_dialog(verify_page)

            selected = None
            for selected in scroll_and_select_user(
                verify_page,
                username,
                [target],
            ):
                break

            if selected == target:
                # 给刚切换的会话一点时间把历史消息真正渲染出来。
                time.sleep(1)
                count = outgoing_message_match_count(verify_page, expected_text)
                total = outgoing_message_count(verify_page)
                if count > baseline_count or (
                    baseline_total is not None and total > baseline_total
                ):
                    logger.info(
                        f"账号 {username} 好友 {target} 已通过全新页面确认消息持久化"
                    )
                    return True

            logger.warning(
                f"账号 {username} 好友 {target} 第 {attempt + 1}/{attempts} 次"
                "独立持久化检查未发现本次消息"
            )
        finally:
            verify_page.close()

        if attempt < attempts - 1:
            time.sleep(delay)

    return False


def type_message_into_editor(page, username, friend, message):
    """清理当前草稿并写入 message，返回编辑器和实际可见文本。"""
    page.wait_for_selector(
        CHAT_EDITABLE_SELECTOR,
        state="visible",
        timeout=config["browserTimeout"],
    )
    chat_input = page.locator(CHAT_EDITABLE_SELECTOR).first

    if norm(chat_input.inner_text()):
        # Slate contenteditable 对 fill("") 并不可靠：页面上看似清空，内部 state
        # 仍可能保留旧草稿。使用真实的全选 + Backspace，让 Slate 自己处理删除。
        chat_input.focus()
        page.keyboard.press("Control+A")
        page.keyboard.press("Backspace")
        time.sleep(0.2)
    if norm(chat_input.inner_text()):
        raise RuntimeError(
            f"账号 {username} 好友 {friend} 输入框存在无法清理的旧草稿，已阻止发送"
        )

    # 不能用 Locator.type() 输入抖音 emoji 短码。当前聊天编辑器会把
    # [盖瑞] / [加一] / [右边] / [左边] 之类的 display_name 方括号吞掉，
    # 最终只剩“盖瑞/加一/右边/左边”纯文本。一次性 insert_text() 不仅会完整
    # 保留短码，也会让 Slate 正确把真实换行拆成多个 ace-line。
    chat_input.focus()
    page.keyboard.insert_text(message.replace("\\n", "\n"))

    effective_text = norm(chat_input.inner_text())
    if not effective_text:
        raise RuntimeError(f"账号 {username} 好友 {friend} 输入后仍为空，已阻止发送")
    return chat_input, effective_text


def deliver_message_with_persistence(
    context,
    page,
    username,
    friend,
    message,
    send_state,
    send_day,
):
    """把同一文案可靠送达一个好友，并以独立页面持久化检查作为最终成功条件。

    如果发送后只出现本地乐观气泡、但全新页面连续看不到该消息，则说明服务器没有
    真正落库。只有在这个条件成立时才允许重新输入同一文案再试，避免正常延迟造成重复。
    """
    friend = norm(friend)
    delivery_retries = max(config["taskRetryTimes"], 1)

    for delivery_attempt in range(delivery_retries):
        if get_active_conversation_name(page) != friend:
            raise RuntimeError(
                f"账号 {username} 发送前会话校验失败：目标 {friend}，"
                f"当前 {get_active_conversation_name(page) or '未打开'}"
            )

        chat_input, effective_text = type_message_into_editor(
            page,
            username,
            friend,
            message,
        )
        # 编辑器里保留的是 [盖瑞] 这类原始短码；发送后的聊天气泡则渲染为 img
        # emoji，innerText 不包含这些短码。因此持久化验证要匹配“去掉 emoji 短码”
        # 后的可见正文，而不是直接拿编辑器 innerText 比。
        verification_text = verification_text_from_message(message)
        baseline_count = outgoing_message_match_count(page, verification_text)
        baseline_total = outgoing_message_count(page)

        record = {
            "status": "attempted",
            "message": message,
            "effective_text": effective_text,
            "verification_text": verification_text,
            "baseline_count": baseline_count,
            "baseline_total": baseline_total,
            "attempted_at": time.time(),
            "delivery_attempt": delivery_attempt + 1,
        }
        set_send_record(send_state, username, friend, record, send_day)

        try:
            local_confirmed = send_and_confirm_once(
                page,
                chat_input,
                username,
                friend,
                verification_text,
                baseline_count,
                baseline_total,
            )
        except SendDispatchError as e:
            # 即使 dispatch_event 抛错，也不能百分百证明浏览器端事件没有已经被派发。
            # 先按“结果未知”处理，必须从全新页面重新拉取确认后才能决定是否重试。
            logger.warning(
                f"账号 {username} 好友 {friend} 发送事件派发报错，将先独立核验：{e}"
            )
            persisted = verify_persisted_outgoing_message(
                context,
                username,
                friend,
                verification_text,
                baseline_count=baseline_count,
                baseline_total=baseline_total,
                attempts=3,
                delay=5,
            )
            if persisted:
                record["status"] = "confirmed"
                record["confirmed_at"] = time.time()
                record["dispatch_error"] = str(e)
                set_send_record(send_state, username, friend, record, send_day)
                logger.info(
                    f"账号 {username} 好友 {friend} 虽然派发接口报错，但服务器侧已确认送达"
                )
                return True

            record = {
                "status": "prepared",
                "message": message,
                "source": "dispatch_error_not_persisted",
                "last_error": str(e),
                "updated_at": time.time(),
            }
            set_send_record(send_state, username, friend, record, send_day)
            if delivery_attempt < delivery_retries - 1:
                time.sleep(5)
                continue
            raise

        # 无论当前页面是否看到乐观气泡，都必须从全新页面重新拉取一次。
        persisted = verify_persisted_outgoing_message(
            context,
            username,
            friend,
            verification_text,
            baseline_count=baseline_count,
            baseline_total=baseline_total,
            attempts=3,
            delay=5,
        )
        if persisted:
            record["status"] = "confirmed"
            record["confirmed_at"] = time.time()
            record["local_confirmed"] = bool(local_confirmed)
            set_send_record(send_state, username, friend, record, send_day)
            logger.info(f"账号 {username} 已确认好友 {friend} 服务器侧新增 1 条本人消息")
            return True

        # 三次全新页面、跨时间重新拉取仍不存在，才认定本次没有真正持久化。
        # 此时可以重试同一文案；不会把“仅当前页乐观显示”误当成功。
        record = {
            "status": "prepared",
            "message": message,
            "source": "not_persisted_after_independent_checks",
            "last_attempt_at": time.time(),
        }
        set_send_record(send_state, username, friend, record, send_day)

        if delivery_attempt < delivery_retries - 1:
            logger.warning(
                f"账号 {username} 好友 {friend} 本次消息未持久化，"
                f"将在冷却后重试 ({delivery_attempt + 1}/{delivery_retries})"
            )
            # 避免紧挨着重发触发平台限速/风控。
            time.sleep(10)

            # 清掉当前页可能残留的本地乐观气泡，再从服务器重新加载同一会话。
            # 这样下一次发送前的 baseline 不会把已经回滚的本地节点算进去。
            retry_operation(
                f"重载好友 {friend} 聊天页",
                page.goto,
                retries=max(config["taskRetryTimes"], 1),
                delay=2,
                url="https://www.douyin.com/chat",
                wait_until="domcontentloaded",
            )
            page.wait_for_selector(
                CONVERSATION_LIST_SELECTOR,
                timeout=config["browserTimeout"],
            )
            page.wait_for_selector(
                CONVERSATION_ITEM_SELECTOR,
                timeout=config["browserTimeout"],
            )
            time.sleep(max(config["friendListTimeout"], 0) / 1000)
            dismiss_trust_login_dialog(page)
            selected = None
            for selected in scroll_and_select_user(page, username, [friend]):
                break
            if selected != friend:
                raise RuntimeError(
                    f"账号 {username} 重试前无法重新打开好友 {friend} 的聊天"
                )
            continue

        raise RuntimeError(
            f"账号 {username} 好友 {friend} 连续 {delivery_retries} 次发送均未通过"
            "独立持久化验证"
        )

    return False


def do_user_task(browser, username, cookies, targets):
    context = browser.new_context()  # 每个任务使用独立的上下文
    context.set_default_navigation_timeout(
        config["browserTimeout"]
    )  # 设置导航超时时间为 120 秒
    context.set_default_timeout(
        config["browserTimeout"]
    )  # 设置所有操作的默认超时时间为 120 秒

    page = context.new_page()

    # 注入 Cookie
    context.add_cookies(cookies)

    # 打开抖音网页聊天页面
    retry_operation(
        "打开抖音网页聊天页面",
        page.goto,
        retries=config["taskRetryTimes"],
        delay=5,
        url="https://www.douyin.com/chat",
        wait_until="domcontentloaded",
    )

    # 不再依赖固定 sleep。聊天页完整 load 事件可能长期不结束，而会话列表本身通常
    # 会在 DOMContentLoaded 之后异步出现；直接等待真正需要的 DOM 更稳定。
    page.wait_for_selector(CONVERSATION_LIST_SELECTOR, timeout=config["browserTimeout"])
    page.wait_for_selector(CONVERSATION_ITEM_SELECTOR, timeout=config["browserTimeout"])
    # 会话骨架出现后，抖音还会把部分纯数字占位 ID 异步替换成昵称/备注名。
    # 项目本来就有 FRIEND_LIST_WAIT_TIME 配置，但此前完全没有使用；这里用它
    # 给好友信息一次短暂的解析窗口，避免把占位 ID 当成最终用户名后过早滚到底。
    time.sleep(max(config["friendListTimeout"], 0) / 1000)
    dismiss_trust_login_dialog(page)

    send_state = load_send_state()
    send_day = _send_day()
    pending_targets = []
    for target in targets:
        record = get_send_record(send_state, username, target, send_day)
        if record and record.get("status") == "confirmed":
            logger.info(f"账号 {username} 好友 {target} 今日已确认发送，跳过")
        else:
            pending_targets.append(target)

    if not pending_targets:
        logger.info(f"账号 {username} 今日所有目标好友都已确认发送，无需重复执行")
        context.close()
        return

    logger.debug(f"账号 {username} 开始发送消息，待处理: {pending_targets}")
    # 滚动并选择用户
    # 生成器迭代出的是「选中的好友名」，不要用来覆盖 username（账号名），否则日志会串
    for friend in scroll_and_select_user(page, username, pending_targets):
        logger.debug(f"账号 {username} 已选中好友 {friend} 发送消息")
        if get_active_conversation_name(page) != norm(friend):
            raise RuntimeError(
                f"账号 {username} 发送前会话校验失败：目标 {friend}，"
                f"当前 {get_active_conversation_name(page) or '未打开'}"
            )
        record = get_send_record(send_state, username, friend, send_day) or {}

        # 上次已经尝试发送但进程没有写到 confirmed：先从当前新加载页面检查，
        # 再用额外的新页面独立复核。只有多次服务端视图都不存在该消息时，
        # 才恢复为 prepared 允许重试，避免“本地乐观气泡”造成假成功或重复发送。
        if record.get("status") == "attempted":
            expected = verification_text_from_record(record)
            baseline_count = int(record.get("baseline_count", 0) or 0)
            baseline_total = record.get("baseline_total")
            if baseline_total is not None:
                baseline_total = int(baseline_total or 0)
            persisted = outgoing_message_match_count(page, expected) > baseline_count
            if not persisted and baseline_total is not None:
                persisted = outgoing_message_count(page) > baseline_total
            if not persisted:
                persisted = verify_persisted_outgoing_message(
                    context,
                    username,
                    friend,
                    expected,
                    baseline_count=baseline_count,
                    baseline_total=baseline_total,
                    attempts=3,
                    delay=5,
                )

            if persisted:
                record["status"] = "confirmed"
                record["confirmed_at"] = time.time()
                set_send_record(send_state, username, friend, record, send_day)
                logger.info(
                    f"账号 {username} 好友 {friend} 已确认上次消息服务器侧存在，跳过重发"
                )
                continue

            record = {
                "status": "prepared",
                "message": record.get("message") or build_message(),
                "source": "previous_attempt_not_persisted",
                "recovered_at": time.time(),
            }
            set_send_record(send_state, username, friend, record, send_day)
            logger.warning(
                f"账号 {username} 好友 {friend} 上次 attempted 经独立页面确认未持久化，"
                "允许使用同一文案安全重试"
            )

        # prepared 表示上次只准备了文案但还没进入“已尝试发送”阶段，可以安全复用同一文案。
        message = record.get("message") if record.get("status") == "prepared" else None
        if not message:
            message = build_message()
        logger.debug(f"账号 {username} 准备发送消息给好友 {friend}：\n\t{message}")
        deliver_message_with_persistence(
            context,
            page,
            username,
            friend,
            message,
            send_state,
            send_day,
        )

    context.close()  # 任务完成后关闭上下文


def runTasks():
    # 检查是否启用多任务和任务数量
    # 创建信号量以限制并发任务数量
    logger.info("开始执行任务")
    logger.debug(f"当前配置如下：")
    logger.debug(f"消息模板: {config.get('messageTemplate', '未找到消息模板')}")
    logger.debug(f"一言类型: {config['hitokotoTypes']}")
    for user in userData:
        logger.debug(
            f"用户: {user.get('username', '未知用户')}, 目标好友: {user['targets']}"
        )

    for user in userData:
        cookies = user["cookies"]
        # 目标好友也要归一化：DOM 里抓到的会话名在 checkTargetName 里会归一，
        # 两边都归过才谈得上相等 —— 否则配置里的「Ｌｕ瞳」永远匹配不上页面上的「Lu瞳」。
        # 同时丢掉归一后变空的项：空串留在剩余名单里永远扣不掉，会白滚到底。
        targets = [t for t in map(norm, user["targets"]) if t]
        username = user.get("username", "未知用户")
        fingerprint = user.get("fingerprint", None)
        logger.info(f"开始处理账号 {username}")
        # 创建任务
        try:
            browser = get_browser(fingerprint)
            do_user_task(browser, username, cookies, targets)
            logger.info(f"账号 {username} 任务完成")
        finally:
            # 关闭浏览器实例
            browser.close()
    