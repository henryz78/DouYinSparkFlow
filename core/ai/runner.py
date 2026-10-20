"""每账号一个浏览器线程，模型请求交给独立线程，持续泵 Playwright 事件。"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from contextlib import suppress
import os
import threading
import time

from core.ai.config import AIConfig
from core.ai.engine import ReplyEngine, echoes
from core.ai.providers import create_provider
from core.session_store import SessionStore, capture_state
from core.douyin_im import DouyinIM, STATUS_READY, JS_LOGIN_DOM, JS_COLLECT, norm

# 平时只读会话列表（不点开会话）；列表上出现未读角标，或最后一条消息变了才切过去读。
# “变了”优先看消息 id（lastKey），文字相同的重复消息也分得出来。
# 只有读不到消息 id 的会话才退回按文字判断，并每隔这么久巡检一次。
SWEEP_SECONDS = 90


def passive_rows(page):
    """读会话列表（纯 DOM 读取，不点击、不切换会话）。读不到返回 None，调用方退回逐个切换。"""
    try:
        rows = page.evaluate(JS_COLLECT)
    except Exception:
        return None
    if not isinstance(rows, list) or not rows:
        return None
    return {str(r["convId"]): r for r in rows if isinstance(r, dict) and r.get("convId")}


def resolve_targets(im, targets, stop):
    wanted = {norm(t) for t in targets if norm(t)}
    matches = {t: {} for t in wanted}
    for hit in im.iter_conversations():
        if stop.is_set():
            return []
        for key in wanted:
            fields = ("title", "conv_id") if hit.get("is_group") else (
                "remark", "nickname", "douyin_id", "uid", "sec_uid", "title", "conv_id")
            if any(norm(hit.get(field) or "") == key for field in fields):
                matches[key][str(hit["conv_id"])] = dict(hit)
    if not (im.last_scan or {}).get("scanned_all"):
        raise ValueError("会话列表未扫描完整，暂不启动陪聊，请增加扫描预算后重试")
    result = {}
    for key, found in matches.items():
        if not found:
            raise ValueError(f"未找到陪聊会话：{key}")
        if len(found) != 1:
            raise ValueError(f"陪聊会话存在重名：{key}，请改用会话 ID；好友也可用抖音号或 UID")
        hit = next(iter(found.values()))
        result[str(hit["conv_id"])] = hit
    return list(result.values())


def run_account(account, config: AIConfig, browser_config, stop: threading.Event, emit):
    from cloakbrowser import launch
    # 不复用 get_browser：它缓存全局环境配置；陪聊使用界面启动时的快照。
    browser = context = im = provider = None
    executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="ai-api")
    name = account.username or account.unique_id
    started_at = time.time()
    try:
        provider = create_provider(config)
        args = ["--no-first-run", "--no-default-browser-check"]
        if account.fingerprint:
            args.append(f"--fingerprint={account.fingerprint}")
        kwargs = {"headless": True, "humanize": True, "args": args}
        if browser_config.proxy_address:
            kwargs["proxy"] = browser_config.proxy_address
        emit("status", f"{name}：正在连接抖音")
        browser = launch(**kwargs)
        import json
        cookies = json.loads(account.cookies)
        sessions = SessionStore(account.unique_id, cookies, account.fingerprint)
        state = sessions.load()
        context = browser.new_context(**({'storage_state':state} if state else {}))
        if state is None:
            context.add_cookies([{k: v for k, v in cookie.items() if k != "sameSite"}
                                for cookie in cookies])
        context.set_default_timeout(browser_config.browser_action_timeout * 1000)
        context.set_default_navigation_timeout(browser_config.browser_action_timeout * 1000)
        page = context.new_page()
        im = DouyinIM(page, timeout=browser_config.im_scan_timeout,
                      ready_timeout=browser_config.im_ready_timeout,
                      settle_ms=browser_config.friend_list_wait_time * 1000,
                      max_steps=browser_config.im_max_steps)
        if im.wait_ready().get("status") != STATUS_READY:
            raise ValueError(f"{name} 登录不可用，请刷新登录信息")
        def checkpoint():
            try:
                sessions.save(capture_state(context))
            except Exception:
                emit('status', f'{name}：登录状态保存失败，请检查数据目录权限')
        checkpoint()
        last_checkpoint = time.monotonic()
        emit("status", f"{name}：已连接，正在扫描好友和群聊会话")
        hits = resolve_targets(im, account.ai_targets, stop)
        engine = ReplyEngine(config, started_at=started_at)
        emit("status", f"{name}：正在初始化会话，跳过现有消息")
        for hit in hits:
            if stop.is_set():
                return
            if not im.select_conversation(hit['conv_id']):
                raise ValueError(f"无法初始化会话：{hit['display']}，请重新启动陪聊")
            page.wait_for_timeout(600)
            engine.seed(str(hit['conv_id']), im.read_chat_messages(str(hit['conv_id']), include_media=True))
        emit("status", f"{name}：已监听 {len(hits)} 个会话（含 {sum(bool(h.get('is_group')) for h in hits)} 个群聊），回复监听就绪后的新文字、emoji、表情及视频分享消息")
        unavailable_cycles = 0
        last_key = {}     # 会话 → 上次处理时列表里的"最后一条消息"（id，没有就用文字）
        next_check = {}   # 会话 → 到点必须再读一次（monotonic）；0 表示马上读，inf 表示只在有变化时读
        while not stop.is_set():
            # READY is cached by the IM client. A later page navigation or
            # disappearing chat root must not leave the worker alive forever.
            dom = page.evaluate(JS_LOGIN_DOM)
            page_missing = isinstance(dom, dict) and not dom.get("hasChatRoot")
            selected_count = 0
            rows = None if page_missing else passive_rows(page)
            for hit in hits:
                if stop.is_set():
                    break
                if page_missing:
                    break
                cid = str(hit["conv_id"])
                if not im.ready:
                    raise ValueError(f"{name} 登录已失效，请刷新登录信息")
                row = rows.get(cid) if rows is not None else None
                if rows is not None:
                    key = (row.get("lastKey") or row.get("desc")) if row else None
                    changed = row is not None and bool(row.get("unread") or key != last_key.get(cid))
                    if changed and row.get("lastFromMe") and not row.get("unread"):
                        last_key[cid] = key  # 最后一条是我们自己发的（含手动回复），没有要回的
                        changed = False
                    if not changed and time.monotonic() < next_check.get(cid, 0):
                        selected_count += 1  # 列表读得到、没有新动静：页面是健康的，不用切会话
                        continue
                if not im.select_conversation(hit["conv_id"]):
                    continue
                selected_count += 1
                next_check[cid] = time.monotonic() + (
                    float("inf") if row and row.get("lastKey") else SWEEP_SECONDS)
                if row is not None:
                    last_key[cid] = row.get("lastKey") or row.get("desc")
                page.wait_for_timeout(600)
                pending = engine.prepare(cid, im.read_chat_messages(cid, include_media=True), is_group=bool(hit.get("is_group")))
                if pending is None:
                    # 冷却中被跳过的消息：列表不会再变，到点自己回来读
                    wait = engine.blocked_until(cid) - time.time()
                    if wait > 0:
                        next_check[cid] = min(next_check[cid], time.monotonic() + wait)
                    continue
                emit("status", f"{name} → {hit['display']}：正在生成回复")
                future = executor.submit(provider.reply, engine.messages(pending))
                while not future.done() and not stop.is_set():
                    page.wait_for_timeout(150)
                if stop.is_set():
                    break
                try:
                    reply = future.result()
                except Exception as exc:
                    engine.failed(pending)
                    # 仅允许我们自己的安全错误文本出现在事件中。
                    from core.ai.providers import ProviderError
                    message = str(exc) if isinstance(exc, ProviderError) else "AI 生成失败"
                    emit("error", f"{name}：{message}，60 秒后再试")
                    next_check[cid] = min(next_check[cid], time.monotonic() + 60)
                    continue
                # API 等待期间有新消息或手动回复，丢弃过时结果，下轮重新判断。
                fresh = engine.prepare(cid, im.read_chat_messages(cid, include_media=True), is_group=bool(hit.get("is_group")))
                if fresh is None or fresh.ids != pending.ids or stop.is_set():
                    continue
                # 发送前就去重；回执缺失不重发，防止同一回复发送两次。
                engine.consume(pending)
                if echoes(reply, pending.text):
                    emit("error", f"{name} → {hit['display']}：回复只是复述对方的话，已丢弃")
                    continue
                result = im.type_and_send(hit, reply, log_content=False)
                if result.get("ok"):
                    engine.commit(pending, reply)
                    emit("sent", f"{name} → {hit['display']}：回复成功")
                else:
                    emit("error", f"{name} → {hit['display']}：未确认发送成功，未自动重发")
            if stop.is_set():
                break
            if selected_count:
                unavailable_cycles = 0
                if time.monotonic() - last_checkpoint >= 300:
                    checkpoint()
                    last_checkpoint = time.monotonic()
            else:
                unavailable_cycles += 1
                if unavailable_cycles == 1:
                    emit("status", f"{name}：会话页面暂不可用，正在检查连接")
                if unavailable_cycles >= 3:
                    login_visible = bool(dom.get("loginVisible")) if isinstance(dom, dict) else False
                    raise ValueError(f"{name}：会话页面连续 3 次不可用（登录窗口={login_visible}），停止连接以便重新启动")
            remaining = config.poll_interval * 1000
            while remaining > 0 and not stop.is_set():
                page.wait_for_timeout(min(remaining, 150))
                remaining -= 150
    finally:
        if context is not None and im is not None and im.ready:
            with suppress(Exception):
                dom = context.pages[-1].evaluate(JS_LOGIN_DOM)
                if isinstance(dom, dict) and dom.get('hasChatRoot') and not dom.get('loginVisible'):
                    checkpoint()
        executor.shutdown(wait=True, cancel_futures=True)
        for resource, method in ((provider, "close"), (im, "detach"),
                                 (context, "close"), (browser, "close")):
            if resource is not None:
                with suppress(Exception):
                    getattr(resource, method)()


def cli():
    from app.config.env_store import load_config
    from app.ai_chat import ChatController
    from app.paths import browser_binary
    binary = browser_binary()
    if binary.is_file():
        os.environ.setdefault("CLOAKBROWSER_BINARY_PATH", str(binary))
    os.environ.setdefault("CLOAKBROWSER_AUTO_UPDATE", "false")
    config, _ = load_config()
    controller = ChatController(lambda kind, message: print(message, flush=True))
    try:
        controller.start(config)
        while controller.status()["running"]:
            time.sleep(0.3)
        return 1 if controller.status()["errors"] else 0
    except KeyboardInterrupt:
        print("正在停止陪聊…", flush=True)
        return 0
    except ValueError as exc:
        print(str(exc), flush=True)
        return 1
    finally:
        controller.stop()
        controller.wait()
