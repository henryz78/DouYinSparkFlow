import re
import time

from utils.logger import setup_logger
from utils.config import get_config, get_userData
from core.msg_builder import build_message
from core.browser import get_browser
from core.douyin_im import DouyinIM, STATUS_READY, norm
from core import delivery_state


config = get_config()
userData = get_userData()
logger = setup_logger(level=config.get("logLevel", "Info"))


def _verification_text(message):
    return re.sub(r"\[[^\[\]\n]+\]", "", (message or "")).replace("\\n", "\n")


def _canonical_text(text):
    return re.sub(r"\s+", "", norm(text or ""))


def _matching_outgoing_count(messages, expected):
    expected = _canonical_text(expected)
    return sum(1 for message in messages if _canonical_text(message) == expected)


def _new_im(page, config):
    return DouyinIM(
        page,
        timeout=config["imScanTimeout"],
        ready_timeout=config["imReadyTimeout"],
        settle_ms=config["friendListSettleMs"],
        max_steps=config["imMaxSteps"],
    )


def _verify_persisted(context, account_key, record, config, logger):
    """在新页面确认这次发送已存在；失败时绝不自动再次发送。"""
    verify_page = context.new_page()
    verify_im = None
    try:
        verify_im = _new_im(verify_page, config)
        if verify_im.wait_ready().get("status") != STATUS_READY:
            return False
        target = record.get("display") or record.get("target")
        if not target:
            return False
        for hit in verify_im.iter_find_and_select([target]):
            if hit.get("conv_id") != record.get("conv_id"):
                continue
            verify_page.wait_for_timeout(800)
            current = verify_im._current_conv() or {}
            if current.get("convId") != record.get("conv_id"):
                continue
            count = _matching_outgoing_count(
                verify_im._outgoing_messages(), record.get("verification_text", "")
            )
            if count > int(record.get("baseline_count", 0) or 0):
                return True
        return False
    except Exception as exc:
        logger.warning(
            f"账号 {account_key} 好友 {record.get('display', '-')} 持久化确认失败：{exc}"
        )
        return False
    finally:
        if verify_im is not None:
            verify_im.detach()
        verify_page.close()


def do_user_task(
    browser, username, cookies, targets, account_key=None, selection_only=False
):
    """一个账号的流程；selection_only 只找人并校验，不输入、不发送。

    实现委托给 `core.douyin_im.DouyinIM`：
      任务一（门禁）    DouyinIM 构造时自动完成，结论在 wait_ready() 里
      任务二（找人）    iter_find_and_select —— yield 时该会话已选中且 conv_id 已校验
      任务三（发送）    im.type_and_send —— 真实键盘事件 + HTTP/DOM 回执双确认
    拟人化节奏由 cloakbrowser 的 humanize 负责，这里不再叠加延迟。
    """
    context = browser.new_context()  # 每个任务使用独立的上下文
    context.set_default_navigation_timeout(
        config["browserActionTimeout"]
    )  # 导航超时（毫秒，config 已换算好）
    context.set_default_timeout(
        config["browserActionTimeout"]
    )  # 单次操作默认超时（毫秒）

    page = context.new_page()

    # 注入 Cookie
    context.add_cookies(cookies)

    im = None
    try:
        # 打开抖音网页聊天页面由库内部完成（先挂钩子再导航，顺序不可颠倒）
        # 扫描参数全部来自配置：总预算/门禁等待是秒，静默窗是毫秒（见 utils.config）
        im = DouyinIM(
            page,
            timeout=config["imScanTimeout"],
            ready_timeout=config["imReadyTimeout"],
            settle_ms=config["friendListSettleMs"],
            max_steps=config["imMaxSteps"],
        )

        res = im.wait_ready()
        if res.get("status") != STATUS_READY:
            # 终端态都要显式打印，方便从日志一眼看出是哪种失败
            reason = {
                "LOGGED_OUT": "未登录（没有 sessionid）",
                "EXPIRED": "登录已失效（有 sessionid 但服务端不认）",
                "LOGIN_LOST": "运行期掉登录",
                "TIMEOUT": "等待超时",
                "ERROR": "内部错误",
            }.get(res.get("status"), res.get("status"))
            logger.error(f"账号 {username} 操作前检查未通过：{reason}，跳过该账号")
            raise RuntimeError(f"账号 {username} 操作前检查未通过：{reason}")

        logger.info(
            f"账号 {username} 门禁通过  user_id={res.get('user_id')} "
            f"nickname={res.get('nickname')} 会话列表就绪"
        )

        account_key = account_key or username
        sent_ok = sent_fail = selected_ok = 0
        pending_targets = list(targets) if selection_only else []
        if not selection_only:
            for target in targets:
                record = delivery_state.get(account_key, norm(target))
                if record and record.get("status") == "confirmed":
                    sent_ok += 1
                    logger.info(f"账号 {username} 好友 {target} 今日已确认发送，跳过")
                else:
                    pending_targets.append(target)

        if not pending_targets:
            logger.info(f"账号 {username} 今日所有目标好友都已确认发送，无需重复执行")
            return

        # 生成器：yield 出来的那一刻，对应好友的会话已经被选中
        for friend in im.iter_find_and_select(pending_targets):
            logger.info(
                f"账号 {username} 已选中好友 {friend['display']}，"
                f"conv_id={friend.get('conv_id')}"
                + ("（selection-only，不发送）" if selection_only else "，准备发送")
            )
            if selection_only:
                selected_ok += 1
                page.wait_for_timeout(800)
                continue

            target_key = norm(friend.get("display") or friend.get("conv_id"))
            record = delivery_state.get(account_key, target_key)

            if record and record.get("status") == "attempted":
                if _verify_persisted(context, account_key, record, config, logger):
                    record["status"] = "confirmed"
                    record["confirmed_at"] = time.time()
                    delivery_state.put(account_key, target_key, record)
                    sent_ok += 1
                    logger.info(f"账号 {username} 好友 {friend['display']} 已确认上次发送，跳过重发")
                else:
                    sent_fail += 1
                    logger.error(
                        f"账号 {username} 好友 {friend['display']} 今日已有 attempted 记录但无法确认；"
                        "为避免重复发送，本日不再派发"
                    )
                page.wait_for_timeout(800)
                continue

            message = build_message()
            verification_text = _verification_text(message)
            baseline_count = _matching_outgoing_count(
                im._outgoing_messages(), verification_text
            )
            delivery_state.put(
                account_key,
                target_key,
                {
                    "status": "attempted",
                    "target": target_key,
                    "display": friend.get("display"),
                    "conv_id": friend.get("conv_id"),
                    "verification_text": verification_text,
                    "baseline_count": baseline_count,
                    "attempted_at": time.time(),
                },
            )
            r = im.type_and_send(friend, message)
            record = delivery_state.get(account_key, target_key) or {}
            if _verify_persisted(context, account_key, record, config, logger):
                record["status"] = "confirmed"
                record["confirmed_at"] = time.time()
                record["receipt_ok"] = bool(r["ok"])
                delivery_state.put(account_key, target_key, record)
                sent_ok += 1
                logger.info(
                    f"账号 {username} → {friend['display']} 发送成功"
                    f"（{r.get('via')} message_id={r.get('message_id') or '-'}）"
                )
            else:
                sent_fail += 1
                logger.warning(
                    f"账号 {username} → {friend['display']} 未通过持久化确认；"
                    "状态保留 attempted，本轮及后续不自动重发"
                )
            # 发送完让列表状态落定，再继续滚动（发送会把该会话移到顶部）
            page.wait_for_timeout(800)

        scan = im.last_scan or {}
        logger.info(
            f"账号 {username} 扫描结束：停止原因={scan.get('stopped')} "
            f"步数={scan.get('steps')} 访问会话={scan.get('visited')} "
            f"选择成功={selected_ok if selection_only else '-'} "
            f"发送成功={sent_ok} 发送失败={sent_fail}"
        )
        if scan.get("missing"):
            # 这两句必须区分开：scanned_all=False 时"没找到"不代表"不存在"
            logger.warning(
                f"账号 {username} 未找到的目标：{scan['missing']}"
                f"（{scan.get('note')}）"
            )
        if scan.get("select_failed"):
            logger.warning(
                f"账号 {username} 找到但选中失败：{scan['select_failed']}"
            )

        # 找到但没有选中、或发送未确认，都必须让任务失败；否则调度器会把
        # "发送 0 条" 当成正常完成，下一轮又无法区分真正的成功。
        reasons = []
        if scan.get("missing"):
            reasons.append(f"未找到目标={scan['missing']}")
        if scan.get("select_failed"):
            reasons.append(f"选中失败={scan['select_failed']}")
        if sent_fail and not selection_only:
            reasons.append(f"发送失败={sent_fail}")
        expected = len(set(targets))
        completed = selected_ok if selection_only else sent_ok
        if completed != expected:
            reasons.append(
                f"{'选择成功' if selection_only else '发送成功'}={completed}/{expected}"
            )
        if reasons:
            raise RuntimeError(f"账号 {username} 任务未完成：" + "；".join(reasons))

        folds = im.fold_groups()
        if any(v for v in folds.values() if v):
            logger.warning(
                f"账号 {username} 注意：折叠组/陌生人组里有内容 {folds}，"
                f"主列表扫不到，目标可能被折叠"
            )
    finally:
        if im is not None:
            try:
                im.detach()
            except Exception:
                pass
        context.close()  # 任务完成后关闭上下文


def runTasks(selection_only=False):
    # 检查是否启用多任务和任务数量
    # 创建信号量以限制并发任务数量
    logger.info(
        "开始执行任务" + ("（selection-only：不输入、不发送）" if selection_only else "")
    )
    logger.debug(f"当前配置如下：")
    logger.debug(f"消息模板: {config.get('messageTemplate', '未找到消息模板')}")
    logger.debug(f"一言类型: {config['hitokotoTypes']}")
    for user in userData:
        logger.debug(
            f"用户: {user.get('username', '未知用户')}, 目标好友: {user['targets']}"
        )

    for user in userData:
        cookies = user["cookies"]
        # 归一化在**这里**做（配置读取端不做）：DouyinIM._match 内部用同一套 norm，
        # 两边都归过才谈得上相等 —— 否则配置里的「Ｌｕ瞳」永远匹配不上页面上的「Lu瞳」。
        # 同时丢掉归一后变空的项：空串留在剩余名单里永远扣不掉，会白滚到底。
        targets = [t for t in map(norm, user["targets"]) if t]
        username = user.get("username", "未知用户")
        fingerprint = user.get("fingerprint", None)
        logger.info(f"开始处理账号 {username}")
        # 创建任务
        try:
            browser = get_browser(fingerprint)
            do_user_task(
                browser,
                username,
                cookies,
                targets,
                # Keep the username key compatible with the existing custom
                # send_state.json format; unique_id migration can come later.
                account_key=username,
                selection_only=selection_only,
            )
            logger.info(f"账号 {username} 任务完成")
        finally:
            # 关闭浏览器实例
            browser.close()
