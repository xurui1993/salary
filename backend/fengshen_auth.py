"""Local Fengshen authentication: encrypted state and a browser-thread command queue."""

from concurrent.futures import Future
from contextlib import contextmanager
import ctypes
import hashlib
from ctypes import wintypes
import json
import logging
import os
from pathlib import Path
import queue
import re
import secrets
import tempfile
import threading
import time
from urllib.parse import urlencode, urlparse

from fengshen_bill import BILL_URL, BillCollectionError, login_rejection


class AuthError(BillCollectionError):
    pass


def allowed_host(host):
    host = (host or "").lower().lstrip(".")
    return host == "ele.me" or host.endswith(".ele.me") or host == "alibaba-inc.com" or host.endswith(".alibaba-inc.com")


def safe_state(state):
    if not isinstance(state, dict) or not isinstance(state.get("cookies"), list) or not isinstance(state.get("origins"), list):
        raise AuthError("保存的会话格式无效，请重新登录")
    cookies = [c for c in state["cookies"] if isinstance(c, dict) and allowed_host(c.get("domain"))]
    origins = [o for o in state["origins"] if isinstance(o, dict)
               and urlparse(o.get("origin", "")).scheme == "https" and allowed_host(urlparse(o.get("origin", "")).hostname)]
    return {"cookies": cookies, "origins": origins}


def dpapi(data, decrypt=False, entropy=b"aegis-fengshen-session-v1"):
    if os.name != "nt":
        raise AuthError("本机会话加密仅支持 Windows；不会退回明文存储")

    class Blob(ctypes.Structure):
        _fields_ = [("size", wintypes.DWORD), ("data", ctypes.POINTER(ctypes.c_ubyte))]

    def blob(value):
        buffer = ctypes.create_string_buffer(value)
        return Blob(len(value), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte))), buffer

    source, source_buffer = blob(data)
    entropy_blob, entropy_buffer = blob(entropy)
    output = Blob()
    crypt = ctypes.WinDLL("crypt32", use_last_error=True)
    function = crypt.CryptUnprotectData if decrypt else crypt.CryptProtectData
    function.argtypes = [ctypes.POINTER(Blob), ctypes.c_void_p, ctypes.POINTER(Blob),
                         ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(Blob)]
    function.restype = wintypes.BOOL
    # User-bound DPAPI, never CRYPTPROTECT_LOCAL_MACHINE; no interactive OS prompts.
    if not function(ctypes.byref(source), None, ctypes.byref(entropy_blob), None, None, 1, ctypes.byref(output)):
        raise AuthError("无法解密或加密本机会话，请在当前 Windows 用户下重新登录")
    try:
        return ctypes.string_at(output.data, output.size)
    finally:
        free = ctypes.WinDLL("kernel32").LocalFree
        free.argtypes = [ctypes.c_void_p]
        free.restype = ctypes.c_void_p
        free(output.data)


class SessionVault:
    def __init__(self, path=None, crypt=dpapi):
        self.path = Path(path) if path else Path(__file__).with_name(".local_auth") / "fengshen.dpapi"
        self.crypt = crypt

    def load(self):
        if not self.path.exists():
            return None
        try:
            if self.path.is_symlink() or self.path.stat().st_size > 5 * 1024 * 1024:
                raise ValueError()
            return safe_state(json.loads(self.crypt(self.path.read_bytes(), decrypt=True)))
        except Exception:
            raise AuthError("本机会话无法读取，请清除会话后重新登录") from None

    def save(self, state):
        value = json.dumps(safe_state(state), ensure_ascii=True).encode("utf-8")
        encrypted = self.crypt(value)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(dir=self.path.parent, suffix=".encrypted.part", delete=False) as target:
                temporary = Path(target.name)
                target.write(encrypted)
            os.replace(temporary, self.path)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)

    def clear(self):
        self.path.unlink(missing_ok=True)


class AuthBroker:
    """HTTP handlers enqueue commands; only the collecting thread touches Playwright."""

    def __init__(self, vault=None, clock=time.monotonic):
        self.vault = vault or SessionVault()
        self.clock = clock
        self.lock = threading.RLock()
        self.commands = queue.Queue(maxsize=1)
        self.active = None
        self.release = {}
        self.state = "saved" if self.vault.path.exists() else "signed_out"
        self.message = "本机会话待验证" if self.state == "saved" else "尚未登录"
        self.cooldown = 0
        self.send_count = 0
        self.verify_count = 0
        self.phone_mask = ""
        self.saved_digest = None

    def status(self, owner):
        with self.lock:
            active = self.active
            visible = bool(active and active["owner"] == owner)
            transport = active.get("transport", "browser") if visible else "browser"
            purpose = active.get("purpose", "login") if visible else "login"
            return {"state": self.state, "message": self.message, **self.release,
                    "cancelling": bool(active and active["cancelled"].is_set()),
                    "transport": transport,
                    "purpose": purpose, "phone_required": purpose != "export",
                    "saved": self.vault.path.exists(), "busy": bool(active),
                    "challenge_id": active["id"] if visible else None,
                    "stage": active["stage"] if visible else None,
                    "phone_mask": self.phone_mask if visible else "",
                    "retry_after": max(0, int(self.cooldown - self.clock() + 0.999)),
                    "can_send": visible and active["stage"] in ("login_required", "sms_sent", "manual_required")
                                and not (transport == "http" and active["stage"] == "manual_required")
                                and self.send_count < 3 and self.clock() >= self.cooldown,
                    "can_verify": visible and active["stage"] == "sms_sent" and self.verify_count < 5,
                    "can_recheck": visible and purpose != "export" and active["stage"] in ("login_required", "sms_sent", "manual_required")}

    def release_update(self, value):
        with self.lock: self.release = value

    @contextmanager
    def operation(self, owner, cancelled, notify=lambda _: None, transport="browser"):
        with self.lock:
            if self.active:
                raise AuthError("另一项风神登录或采集正在进行，请等待完成")
            self.release = {}
            self.active = {"owner": owner, "id": secrets.token_urlsafe(32), "stage": "checking", "transport": transport,
                           "cancelled": cancelled, "notify": notify}
            self.send_count = self.verify_count = 0
            self.phone_mask = ""
            self.update("checking", "正在验证风神登录状态")
        try:
            yield self
        finally:
            with self.lock:
                self.drain()
                self.active = None
                if self.state not in ("ready", "error", "signed_out"):
                    self.state = "saved" if self.vault.path.exists() else "signed_out"
                    self.message = "会话待验证" if self.state == "saved" else "登录未完成"

    def update(self, state, message):
        with self.lock:
            changed = (self.state, self.message) != (state, message)
            self.state, self.message = state, message
            if self.active:
                self.active["stage"] = state
                if changed:
                    self.active["notify"](self.status(self.active["owner"]))

    def drain(self):
        while True:
            try:
                _, _, future = self.commands.get_nowait()
                if not future.done():
                    future.set_exception(AuthError("登录操作已结束，请重新打开登录窗口"))
            except queue.Empty:
                return

    def submit(self, owner, challenge, action, value=""):
        with self.lock:
            if not self.active or self.active["owner"] != owner or not secrets.compare_digest(self.active["id"], challenge):
                raise AuthError("登录窗口已过期或不属于当前工作区")
            status = self.status(owner)
            if action == "send" and not status["can_send"]:
                raise AuthError("请等待验证码发送冷却时间，或重新打开登录窗口")
            if action == "verify" and not status["can_verify"]:
                raise AuthError("请先获取验证码；错误尝试次数过多时请重新登录")
            if action == "recheck" and not status["can_recheck"]:
                raise AuthError("正在检查登录状态，请稍后重试")
            if action == "send" and self.active.get("purpose") != "export" and not re.fullmatch(r"1[3-9]\d{9}", value):
                raise AuthError("请输入有效的手机号码")
            if action == "verify" and not re.fullmatch(r"\d{6}", value):
                raise AuthError("请输入六位短信验证码")
            if action == "cancel":
                self.active["cancelled"].set()
                self.update("signed_out", "登录已取消，任务已停止")
                return None
            if action not in ("send", "verify", "recheck"):
                raise AuthError("不支持的登录操作")
            future = Future()
            try:
                self.commands.put_nowait((action, value, future))
            except queue.Full:
                raise AuthError("正在处理登录操作，请稍后重试") from None
            if action == "send":
                self.cooldown = self.clock() + 60
                self.send_count += 1
                self.phone_mask = "平台账号绑定手机号" if self.active.get("purpose") == "export" else value[:3] + "****" + value[-4:]
                self.update("sending", "正在请求短信验证码，不会自动重发" if self.active.get("transport") == "http"
                            else "正在请求验证码；如出现额外验证，请在 Edge 中完成")
            elif action == "verify":
                self.verify_count += 1
                self.update("verifying", "正在验证登录")
            else:
                self.update("verifying", "正在重新检查登录状态，不会发送短信" if self.active.get("transport") == "http"
                            else "正在重新检查 Edge 登录状态，不会发送短信")
            return future

    def save(self, state):
        with self.lock:
            if not self.active or self.active["cancelled"].is_set():
                raise AuthError("任务已取消，会话未保存")
            digest = hashlib.sha256(json.dumps(safe_state(state), sort_keys=True).encode("utf-8")).digest()
            if digest != self.saved_digest or not self.vault.path.exists():
                self.vault.save(state)
                self.saved_digest = digest
            self.update("ready", "风神已登录，本机会话已加密保存")

    def clear(self):
        with self.lock:
            if self.active:
                self.active["cancelled"].set()
            self.drain()
            self.vault.clear()
            self.saved_digest = None
            self.update("signed_out", "本机会话已清除")


BROKER = AuthBroker()


class BrowserAuth:
    def __init__(self, page, context, broker, cancelled, log=lambda _: None, timeout=1800, replace_closed_page=False,
                 reveal=lambda page: None, conceal=lambda page: None):
        self.page, self.context, self.broker = page, context, broker
        self.cancelled, self.log, self.timeout = cancelled, log, timeout
        self.replace_closed_page = replace_closed_page
        self.reveal, self.conceal = reveal, conceal
        self.pages = {}
        self.requests = {}
        self.login_attempts = 0
        for item in context.pages:
            self.watch(item)
        self.watch(page)
        context.on("page", self.watch)

    def watch(self, page):
        if page in self.pages:
            return
        self.pages[page] = {"generation": 0, "rejected": False}
        page.on("response", lambda response: self.response(response, page))
        page.on("request", lambda request: self.request(request, page))
        page.on("requestfailed", lambda request: self.requests.pop(id(request), None))
        page.on("framenavigated", lambda frame: self.navigated(frame, page))

    def navigated(self, frame, page):
        if frame == page.main_frame:
            state = self.pages[page]
            state["generation"] += 1
            state["rejected"] = False

    def request(self, request, page):
        if urlparse(request.url).hostname == "httpizza.ele.me" and request.resource_type in ("xhr", "fetch"):
            self.requests[id(request)] = (page, self.pages[page]["generation"])

    def response(self, response, page=None):
        page = page or self.page
        state = self.pages[page]
        _, generation = self.requests.pop(id(response.request), (page, state["generation"]))
        if generation != state["generation"]:
            return
        if urlparse(response.url).hostname == "httpizza.ele.me" and response.request.resource_type in ("xhr", "fetch"):
            if response.status == 401:
                state["rejected"] = True
            elif response.status == 200:
                try:
                    if login_rejection(response.json()):
                        state["rejected"] = True
                except Exception:
                    pass

    def expired(self, page=None):
        page = page or self.page
        if self.pages[page]["rejected"] or urlparse(page.url).hostname == "mozi-login.alibaba-inc.com":
            return True
        for frame in page.frames:
            if frame == page.main_frame or urlparse(frame.url).hostname != "mozi-login.alibaba-inc.com":
                continue
            try:
                if frame.frame_element().is_visible():
                    return True
            except Exception:
                continue
        return False

    def checkpoint(self):
        if self.cancelled.is_set():
            raise AuthError("登录或采集已取消，核算已停止")
        if self.page.is_closed():
            if self.replace_closed_page:
                for page in reversed(self.context.pages):
                    if not page.is_closed() and urlparse(page.url).hostname in ("aeolus.ele.me", "mozi-login.alibaba-inc.com"):
                        self.page = page
                        self.watch(page)
                        return
            raise AuthError("登录浏览器已关闭，核算已停止")

    def wait(self, milliseconds):
        previous = self.page
        try:
            previous.wait_for_timeout(milliseconds)
        except Exception:
            # SSO may close its original tab while a logged-in popup remains in this context.
            self.checkpoint()
            if self.page is previous:
                raise

    def merchant_ready(self, page, profile=None):
        if page.is_closed() or self.expired(page) or urlparse(page.url).hostname != "aeolus.ele.me":
            return False
        pattern = re.compile(r"\[(?:310\d{5}|22476859)\]")
        try:
            locators = [page.locator(profile["agency_context"])] if profile else [
                page.get_by_text(pattern),
                page.locator('input[readonly], input[role="combobox"], [role="combobox"] input, '
                             '.vue-treeselect__single-value, .ant-select-selection-item, .el-select .el-input__inner'),
            ]
            for locator in locators:
                for index in range(locator.count()):
                    item = locator.nth(index)
                    if item.is_visible():
                        text = item.evaluate("el => typeof el.value === 'string' ? el.value : el.innerText")
                        if isinstance(text, str) and pattern.search(text):
                            return True
        except Exception:
            # Mozi redirects can replace the document between reading the URL and inspecting its header.
            return False
        return False

    def signed_in_page(self):
        for page in [self.page] + list(reversed(self.context.pages)):
            self.watch(page)
            if self.merchant_ready(page):
                return page
        return None

    def ready(self, target, profile=None):
        # Login is independent of report access; collectors still require their exact report and controls.
        if profile:
            return urlparse(self.page.url).fragment == urlparse(target).fragment and self.merchant_ready(self.page, profile)
        return self.signed_in_page() is not None

    def navigate(self, url):
        try:
            self.page.goto(url, wait_until="domcontentloaded", timeout=60000)
        except Exception as exc:
            interrupted = any(text in str(exc) for text in ("net::ERR_ABORTED", "interrupted by another navigation"))
            if not interrupted or urlparse(self.page.url).hostname not in ("aeolus.ele.me", "mozi-login.alibaba-inc.com"):
                raise

    def one(self, locator):
        visible = [locator.nth(i) for i in range(locator.count()) if locator.nth(i).is_visible()]
        if len(visible) != 1:
            raise AuthError("登录控件无法唯一识别，请在 Edge 官方登录页中完成验证")
        return visible[0]

    def send(self, phone):
        if urlparse(self.page.url).hostname != "mozi-login.alibaba-inc.com":
            raise AuthError("当前不在官方登录页，请在 Edge 中确认登录状态")
        tabs = self.page.get_by_text(re.compile(r"^(短信登录|手机验证码登录|手机号登录)$"))
        visible = [tabs.nth(i) for i in range(tabs.count()) if tabs.nth(i).is_visible()]
        if len(visible) == 1:
            visible[0].click()
        self.one(self.page.locator('input[type="tel"], input[placeholder="请输入手机号"], input[placeholder="手机号码"]')).fill(phone)
        self.one(self.page.get_by_text(re.compile(r"^(获取验证码|发送验证码|获取动态码)$"))).click()
        # A click is not evidence that the platform delivered an SMS.
        self.broker.update("sms_sent", "已请求验证码；未收到短信或出现滑块时，请在 Edge 中检查")

    def verify(self, code):
        if urlparse(self.page.url).hostname != "mozi-login.alibaba-inc.com":
            raise AuthError("登录页已变化，请在 Edge 中完成验证")
        self.one(self.page.locator('input[maxlength="6"], input[placeholder="请输入验证码"], input[placeholder="短信验证码"]')).fill(code)
        pattern = re.compile(r"^(登\s*录|立即登录|确认登录)$")
        buttons = self.page.get_by_role("button", name=pattern)
        if buttons.count() == 0:
            buttons = self.page.get_by_text(pattern)
        self.one(buttons).click()

    def ensure(self, target, profile=None, force=False):
        self.checkpoint()
        if not force and self.ready(target, profile):
            self.broker.save(self.context.storage_state())
            return False
        if not force and profile and self.signed_in_page() is not None:
            if self.expired() or urlparse(self.page.url).fragment != urlparse(target).fragment:
                self.navigate(target)
        if not force and not self.expired():
            deadline = time.monotonic() + 15
            while time.monotonic() < deadline:
                self.checkpoint()
                if self.ready(target, profile):
                    self.broker.save(self.context.storage_state())
                    return False
                if self.expired():
                    break
                self.wait(200)
            if not self.expired():
                raise AuthError("无法确认风神登录状态，请检查网络、城市权限或页面配置；未触发短信发送")
        return self.login(target, profile)

    def login(self, target, profile=None):
        self.checkpoint()
        self.login_attempts += 1
        if self.login_attempts > 3:
            raise AuthError("登录反复失效，核算已停止，请检查账号状态")
        if urlparse(self.page.url).hostname != "mozi-login.alibaba-inc.com":
            login_url = "https://mozi-login.alibaba-inc.com/?" + urlencode({"APP_NAME": "LOGISTICS_COMPANY", "BACK_URL": target})
            self.navigate(login_url)
        self.reveal(self.page)
        self.broker.update("login_required", "风神需要登录，采集已暂停")
        self.log("[登录] 采集已暂停，请在系统弹窗中获取并输入验证码；额外验证在 Edge 中完成")
        deadline = time.monotonic() + self.timeout
        pending = None
        pending_action = None
        command_deadline = 0
        restore_count = 0
        restore_after = 0
        try:
            while time.monotonic() < deadline:
                self.checkpoint()
                # A transient Aeolus redirect is not proof of login. Wait for a gated merchant header.
                if profile and self.signed_in_page() is not None and time.monotonic() >= restore_after:
                    if self.expired() or urlparse(self.page.url).fragment != urlparse(target).fragment:
                        if restore_count >= 3:
                            raise AuthError("已登录风神，但无法进入账单页面，请检查业务权限或页面配置")
                        restore_count += 1
                        restore_after = time.monotonic() + 5
                        self.broker.update("verifying", "已识别风神登录，正在返回账单页面")
                        self.navigate(target)
                if self.ready(target, profile):
                    self.broker.save(self.context.storage_state())
                    if pending and not pending.done():
                        pending.set_result({"ok": True, "message": "登录成功，会话已保存，继续原任务"})
                    while True:
                        try:
                            action, _, future = self.broker.commands.get_nowait()
                        except queue.Empty:
                            break
                        if not future.done():
                            future.set_result({"ok": action != "send", "message": "已登录，会话已保存，无需再次发送验证码"})
                    self.log("[登录] 验证成功，继续原采集任务")
                    self.conceal(self.page)
                    return True
                try:
                    action, value, future = self.broker.commands.get_nowait()
                except queue.Empty:
                    action = None
                if action:
                    if future.cancelled():
                        continue
                    try:
                        if action == "send":
                            self.send(value)
                            future.set_result({"ok": True, "message": self.broker.message})
                        else:
                            if pending and not pending.done():
                                future.set_result({"ok": False, "message": "正在检查登录，请稍后重试"})
                                continue
                            if action == "verify":
                                self.verify(value)
                            pending, pending_action = future, action
                            command_deadline = time.monotonic() + (45 if action == "verify" else 15)
                    except Exception:
                        message = "登录控件操作未完成，请在 Edge 官方页面检查滑块、验证码或登录按钮"
                        self.broker.update("sms_sent" if self.broker.send_count else "manual_required", message)
                        if not future.done():
                            future.set_result({"ok": False, "message": message})
                    finally:
                        value = ""
                if pending and time.monotonic() >= command_deadline:
                    message = ("尚未检测到已登录的风神合作商页面，请检查系统打开的 Edge 窗口"
                               if pending_action == "recheck" else "尚未确认登录成功，等待 Edge 官方页面完成登录")
                    if not pending.done():
                        pending.set_result({"ok": False, "message": message})
                    pending = None
                    self.broker.update("sms_sent" if self.broker.send_count else "manual_required", message)
                self.wait(200)
            raise AuthError("登录等待超时，核算已停止；请重新启动任务")
        finally:
            if pending and not pending.done():
                pending.set_exception(AuthError("登录已结束，任务未继续"))


def launch_background_edge(playwright):
    # Keep the same headed context for official human verification and in-flight exports.
    from auth_browser_runtime import launch_edge
    return launch_edge(playwright, headless=False, args=["--start-minimized"])


def edge_window(page, visible):
    session = page.context.new_cdp_session(page)
    try:
        window = session.send("Browser.getWindowForTarget")
        session.send("Browser.setWindowBounds", {"windowId": window["windowId"],
                     "bounds": {"windowState": "normal" if visible else "minimized"}})
        if visible:
            page.bring_to_front()
    finally:
        session.detach()


def reveal_edge(page):
    try:
        edge_window(page, True)
    except Exception:
        raise AuthError("无法恢复专用 Edge 验证窗口；未自动发送验证码，请检查任务栏中的 Edge") from None


def conceal_edge(page):
    try:
        edge_window(page, False)
    except Exception:
        raise AuthError("无法将专用 Edge 切换到后台；任务已停止，请检查浏览器") from None


def open_context(browser, broker):
    state = broker.vault.load()
    return browser.new_context(accept_downloads=True, **({"storage_state": state} if state else {}))


def standalone_login(owner, cancelled, entered):
    try:
        from playwright.sync_api import sync_playwright
        with BROKER.operation(owner, cancelled):
            entered.set()
            phase = "browser_launch"
            try:
                from auth_browser_guard import guarded_playwright
                guards = []
                with guarded_playwright(cancelled, BROKER.release_update, guards.append) as playwright:
                    browser = launch_background_edge(playwright)
                    try:
                        phase = "session_load"
                        context = open_context(browser, BROKER)
                        page = context.new_page()
                        conceal_edge(page)
                        auth = BrowserAuth(page, context, BROKER, cancelled, replace_closed_page=True,
                                           reveal=reveal_edge, conceal=conceal_edge)
                        phase = "report_navigation"
                        auth.navigate(BILL_URL)
                        phase = "login_check"
                        auth.ensure(BILL_URL)
                    finally:
                        if guards: guards[0].closing()
                        browser.close()
            except Exception as exc:
                reasons = ("Execution context was destroyed", "net::ERR_ABORTED", "net::ERR_CERT", "net::ERR_CONNECTION", "Target page, context or browser has been closed")
                reason = next((text for text in reasons if text in str(exc)), "other")
                logging.getLogger(__name__).warning("Fengshen login stopped: phase=%s type=%s reason=%s", phase, type(exc).__name__, reason)
                hints = {"browser_launch": "无法启动 Edge 登录窗口，请检查浏览器和 Playwright 依赖",
                         "session_load": "无法恢复本机会话，请清除会话后重试",
                         "report_navigation": "无法打开风神业务页面，请检查本机网络后重试",
                         "login_check": "风神登录检查未完成，请检查官方登录页后重试"}
                BROKER.update("signed_out" if cancelled.is_set() else "error",
                              str(exc) if isinstance(exc, AuthError) else hints[phase])
    except Exception as exc:
        if not BROKER.active:
            BROKER.update("error", str(exc) if isinstance(exc, AuthError) else "登录组件无法启动，请检查采集依赖")
    finally:
        entered.set()


START_LOCK = threading.Lock()


def start_login(owner):
    with START_LOCK:
        if BROKER.active:
            return BROKER.status(owner)
        cancelled = threading.Event()
        entered = threading.Event()
        thread = threading.Thread(target=standalone_login, args=(owner, cancelled, entered), name="fengshen-login", daemon=True)
        thread.start()
        entered.wait(3)
        return BROKER.status(owner)
