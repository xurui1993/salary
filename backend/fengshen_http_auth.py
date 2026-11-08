"""Official Mozi SMS login over HTTP, with no browser or automatic SMS sends.

Protocol: mozi-sso/1.0.29/login_app.js and vendor_7594ef29.js (modules
1308/81939), inspected 2026-10-17. Never execute platform JavaScript here.
The existing DPAPI vault and broker remain shared with legacy collectors.
"""
import ast
import html
import json
import queue
import re
import threading
import time
from urllib.parse import quote, urlencode, urljoin, urlsplit

import requests

from fengshen_auth import AuthError, BROKER, START_LOCK, allowed_host
from fengshen_bill import AuthenticationRequired


LOGIN_ORIGIN = "https://mozi-login.alibaba-inc.com"
LOGIN_URL = LOGIN_ORIGIN + "/?" + urlencode({
    "APP_NAME": "LOGISTICS_COMPANY",
    "BACK_URL": "https://aeolus.ele.me/?_tplCode=mknnjrtsvw9cj96u&moziAppType=LOGISTICS_COMPANY",
})
SEND_URL = LOGIN_ORIGIN + "/rpc/sms/send_login_sms_code.json"
VERIFY_URL = LOGIN_ORIGIN + "/rpc/login/doLogin.json"
EXPORT_SMS_URL = "https://app2-edu.ele.me/kunkka-svr/exportStaff/sendVerifyCode"
MAX_LOGIN_BODY = 2 * 1024 * 1024
EXTRA_MESSAGE = "风神要求额外安全验证，当前短信接口无法完成；任务已暂停，未启动浏览器或绕过验证"


class ExtraVerificationRequired(AuthError):
    pass


class LoginRequestUncertain(AuthError):
    """The request may have reached the platform; never resend automatically."""


def official_login_url(url):
    try:
        parsed = urlsplit(url)
        if (parsed.scheme != "https" or not allowed_host(parsed.hostname)
                or parsed.username is not None or parsed.password is not None
                or parsed.port not in (None, 443) or "\\" in url or any(ord(c) < 32 for c in url)):
            raise ValueError()
    except (ValueError, TypeError):
        raise AuthError("登录返回了未经允许的跳转地址，已停止认证") from None
    return url


def parse_login_config(document):
    """Extract string literals only. Functions and arbitrary JS are never run."""
    marker = re.search(r"window\.ssoConfig\s*=\s*\{", document)
    if marker is None:
        raise AuthError("风神短信登录页面结构变化，未发送验证码")
    source = document[marker.end():].split("</script>", 1)[0]
    keys = ("APP_NAME", "authTypeList", "enableRsa", "rsaPublicKey", "rsaExponent", "rsaMaxDigit",
            "needCheckCodeList", "_sso_csrftoken_", "queryString", "umidTokenId", "phoneNumToken")
    config = {}
    for key in keys:
        pattern = r"(?:['\"]" + re.escape(key) + r"['\"]|\b" + re.escape(key) + r"\b)\s*:\s*((?:'(?:\\.|[^'\\])*')|(?:\"(?:\\.|[^\"\\])*\"))"
        match = re.search(pattern, source)
        if match:
            try:
                value = ast.literal_eval(match.group(1))
            except (ValueError, SyntaxError):
                raise AuthError("风神登录参数格式变化，未发送验证码") from None
            if not isinstance(value, str) or len(value) > 16384:
                raise AuthError("风神登录参数格式无效")
            config[key] = value
    if (config.get("APP_NAME") != "LOGISTICS_COMPANY"
            or not re.search(r"\bSMS\b", config.get("authTypeList", ""))
            or not config.get("_sso_csrftoken_")):
        raise AuthError("当前风神登录页面不支持已核实的合作商短信登录")
    checks = config.get("needCheckCodeList", "").strip()
    if checks not in ("", "[]"):
        raise ExtraVerificationRequired(EXTRA_MESSAGE)
    for key in ("faceVerification", "trustEnvConf"):
        if re.search(r"['\"]" + key + r"['\"]\s*:\s*\{[^}]*['\"]enable['\"]\s*:\s*true", source):
            raise ExtraVerificationRequired(EXTRA_MESSAGE)
    config["queryString"] = html.unescape(config.get("queryString", "")).lstrip("?")
    return config


def encrypt_phone(phone, config):
    """Match official RSAKeyPair.encryptedString, not PKCS#1 padding.

    The platform encodesURIComponent then packs pairs as little-endian 16-bit
    words, pads each chunk with zero bytes and returns hex in four-digit words.
    This compatibility operation is only for the platform's request format;
    transport confidentiality is provided by HTTPS.
    """
    if config.get("enableRsa") != "true":
        return phone
    modulus_hex = config.get("rsaPublicKey", "")
    exponent_hex = config.get("rsaExponent", "10001")
    if (not re.fullmatch(r"[0-9a-fA-F]{128,1024}", modulus_hex)
            or not re.fullmatch(r"[0-9a-fA-F]{1,8}", exponent_hex)):
        raise AuthError("风神短信公钥格式变化，未发送验证码")
    modulus, exponent = int(modulus_hex, 16), int(exponent_hex, 16)
    chunk_size = 2 * ((modulus.bit_length() - 1) // 16)
    if chunk_size < 32 or exponent < 3:
        raise AuthError("风神短信公钥参数无效")
    data = quote(phone, safe="~()*!.'-").encode("ascii")
    data += b"\0" * (-len(data) % chunk_size)
    output = []
    for offset in range(0, len(data), chunk_size):
        value = pow(int.from_bytes(data[offset:offset + chunk_size], "little"), exponent, modulus)
        result = format(value, "x")
        output.append(result.zfill(((len(result) + 3) // 4) * 4))
    return " ".join(output)


class MoziSmsProtocol:
    def __init__(self, client):
        self.client = client
        self.config = None
        self.phone = ""

    def _request(self, method, url, *, form=None, redirects=False):
        """Only GET redirects are followed; POST bodies never leave Mozi."""
        if method == "POST" and urlsplit(url)._replace(query="").geturl() not in (SEND_URL, VERIFY_URL):
            raise AuthError("未核实的短信接口，已停止调用")
        for _ in range(8):
            self.client.checkpoint()
            official_login_url(url)
            headers = {"Accept": "application/json" if form is not None else "text/html"}
            if form is not None:
                headers.update({"Origin": LOGIN_ORIGIN, "Referer": LOGIN_URL,
                                "Content-Type": "application/x-www-form-urlencoded;charset=UTF-8"})
            try:
                response = self.client.session.request(method, url, data=form, headers=headers,
                                                       timeout=(10, 30), allow_redirects=False, stream=True)
                with response:
                    if 300 <= response.status_code < 400:
                        if not redirects or method != "GET" or not response.headers.get("Location"):
                            raise ExtraVerificationRequired(EXTRA_MESSAGE)
                        url = official_login_url(urljoin(url, response.headers["Location"]))
                        continue
                    if response.status_code != 200:
                        if response.status_code in (401, 403):
                            raise ExtraVerificationRequired(EXTRA_MESSAGE)
                        raise LoginRequestUncertain("风神登录接口未成功响应；不会自动重发验证码或重复登录")
                    data = bytearray()
                    for chunk in response.iter_content(65536):
                        self.client.checkpoint()
                        data.extend(chunk)
                        if len(data) > MAX_LOGIN_BODY:
                            raise AuthError("风神登录响应超过大小限制")
                    return bytes(data).decode("utf-8"), url
            except requests.RequestException:
                raise LoginRequestUncertain("风神登录连接中断或超时；不会自动重发验证码或重复登录") from None
        raise AuthError("风神登录跳转次数异常，已停止认证")

    def prepare(self):
        # 旧会话的 Mozi SSO cookie（如 BucSsoJSESSIONID）会让登录页判定 SSO 会话
        # 仍存在，直接 302 去 sendBucSSOToken.do 换发业务 token，最终落地业务首页。
        # 该页面没有 window.ssoConfig，会误报“登录页面结构变化，未发送验证码”。
        # 短信登录的语义就是重建会话：先剥离登录域旧会话 cookie，再拉取全新登录页。
        jar = self.client.session.cookies
        try:
            cookies = list(jar)
        except TypeError:
            cookies = ()
        for cookie in cookies:
            if "mozi-login" in (cookie.domain or ""):
                try:
                    jar.clear(cookie.domain, cookie.path, cookie.name)
                except (KeyError, AttributeError):
                    pass
        body, _ = self._request("GET", LOGIN_URL, redirects=True)
        self.config = parse_login_config(body)

    def _post(self, url, form):
        payload = {"_sso_csrftoken_": self.config["_sso_csrftoken_"], **form}
        body, _ = self._request("POST", url, form=payload)
        try:
            result = json.loads(body)
        except (ValueError, UnicodeError):
            raise LoginRequestUncertain("风神登录返回格式异常；请求结果未确认，不会自动重试") from None
        if not isinstance(result, dict):
            raise LoginRequestUncertain("风神登录返回格式异常；请求结果未确认，不会自动重试")
        return result

    def send(self, phone):
        if not re.fullmatch(r"1[3-9]\d{9}", phone):
            raise AuthError("请输入有效的手机号码")
        if self.config is None:
            self.prepare()
        encrypted = encrypt_phone(phone, self.config)
        # Retain in memory before transmission, so a timeout can still accept
        # a code actually received by the user. Never persist the phone/code.
        self.phone = phone
        result = self._post(SEND_URL, {"phone": encrypted, "areaCode": "86", "namespace": "buc",
                                       "appName": "LOGISTICS_COMPANY", "identity": "sms"})
        if result.get("success") is not True:
            self.phone = ""
            if str(result.get("errorMsg")) == "240020" or result.get("isNeedCheckCode"):
                raise ExtraVerificationRequired(EXTRA_MESSAGE)
            raise AuthError("平台未接受验证码发送请求，请确认手机号或稍后重试")

    def verify(self, code):
        if not self.phone or self.config is None:
            raise AuthError("请先获取短信验证码")
        if not re.fullmatch(r"\d{6}", code):
            raise AuthError("请输入六位短信验证码")
        query = self.config.get("queryString", "")
        result = self._post(VERIFY_URL + ("?" + query if query else ""), {
            "phoneNumber": self.phone, "areaCode": "86", "phoneCode": code,
            "loginType": "SMS", "namespace": "buc", "appName": "LOGISTICS_COMPANY",
            "umidTokenId": self.config.get("umidTokenId", ""),
            "phoneNumToken": self.config.get("phoneNumToken", ""),
        })
        content = result.get("content")
        if not isinstance(content, dict):
            raise LoginRequestUncertain("风神登录结果格式变化，尚未确认登录成功")
        if content.get("isNeedCheckCode") or str(content.get("code")) in ("240218", "240219", "240214", "240250"):
            raise ExtraVerificationRequired(EXTRA_MESSAGE)
        if content.get("success") is not True:
            raise AuthError("平台未通过短信验证，请检查验证码是否正确或已过期")
        redirect = content.get("extInfo", {}).get("redirectURL") if isinstance(content.get("extInfo"), dict) else None
        if content.get("type") == "redirect" and redirect:
            self._request("GET", official_login_url(urljoin(LOGIN_ORIGIN, redirect)), redirects=True)
        self.client.identity()  # A successful SMS response alone is not a business session.
        self.phone = ""
        self.config = None


class HTTPAuth:
    def __init__(self, client, broker=BROKER, cancelled=None, log=lambda _: None, timeout=1800, protocol=None, wait_export_indefinitely=False):
        self.client, self.broker = client, broker
        self.cancelled = cancelled if cancelled is not None else client.cancelled
        self.log, self.timeout = log, timeout
        self.wait_export_indefinitely = wait_export_indefinitely
        self.protocol = protocol if protocol is not None else MoziSmsProtocol(client)

    def export_code(self, client=None):
        """Wait for explicit export-SMS actions. The caller submits the export.

        The returned code only exists in the worker's memory. Receiving a code
        is not a claim that the export or platform validation has succeeded.
        """
        client = client if client is not None else self.client
        with self.broker.lock:
            if not self.broker.active:
                raise AuthError("导出验证操作尚未启动")
            import secrets
            self.broker.active.update(id=secrets.token_urlsafe(32), transport="http", purpose="export")
            self.broker.send_count = self.broker.verify_count = 0
            self.broker.phone_mask = "平台账号绑定手机号"
        self.broker.update("login_required", "骑手信息导出需要短信确认，请获取平台绑定手机号的验证码")
        sent = False
        deadline = None if self.wait_export_indefinitely else time.monotonic() + self.timeout
        try:
            while deadline is None or time.monotonic() < deadline:
                if self.cancelled.is_set():
                    raise AuthError("导出短信验证已取消")
                try:
                    action, value, future = self.broker.commands.get(timeout=0.2)
                except queue.Empty:
                    continue
                if future.cancelled():
                    value = ""
                    continue
                try:
                    if action == "send":
                        # A timeout may have sent the SMS. Permit entering a
                        # received code, but never send again automatically.
                        sent = True
                        result = client.request_json("POST", EXPORT_SMS_URL)
                        if not isinstance(result, dict) or result.get("code") not in (0, 200, "0", "200"):
                            sent = False
                            raise AuthError("平台未接受导出验证码发送请求")
                        self.broker.update("sms_sent", "导出验证码已发送，请输入平台绑定手机号收到的验证码")
                        if not future.done():
                            future.set_result({"ok": True, "message": self.broker.message})
                    elif action == "verify" and sent and re.fullmatch(r"\d{6}", value):
                        self.broker.update("ready", "已接收导出验证码，正在提交原导出任务")
                        if not future.done():
                            future.set_result({"ok": True, "message": self.broker.message})
                        return value
                    else:
                        raise AuthError("请先获取导出验证码，再输入六位验证码")
                except Exception as exc:
                    message = str(exc) if isinstance(exc, AuthError) else "导出验证码请求结果未确认；收到验证码后可输入，不会自动重发"
                    self.broker.update("sms_sent" if sent else "login_required", message)
                    if not future.done():
                        future.set_result({"ok": False, "message": message})
                finally:
                    value = ""
            raise AuthError("等待导出短信验证超时，原任务未重新提交")
        finally:
            with self.broker.lock:
                if self.broker.active:
                    self.broker.active["purpose"] = "login"


    def ensure(self, force=False):
        with self.broker.lock:
            if not self.broker.active:
                raise AuthError("登录操作尚未启动")
            self.broker.active["transport"] = "http"
        if not force:
            try:
                self.client.identity()
            except AuthenticationRequired:
                pass
            else:
                self.broker.save(self.client.storage_state())
                return True
        self.broker.update("login_required", "风神会话已失效，请在当前页面获取短信验证码")
        self.log("[登录] 等待页面内短信认证，不会自动发送验证码")
        deadline = time.monotonic() + self.timeout
        blocked = False
        while time.monotonic() < deadline:
            if self.cancelled.is_set():
                raise AuthError("登录已取消，任务已停止")
            try:
                action, value, future = self.broker.commands.get(timeout=0.2)
            except queue.Empty:
                continue
            if future.cancelled():
                value = ""
                continue
            success = False
            try:
                if action == "send":
                    self.protocol.send(value)
                    self.broker.update("sms_sent", "验证码已发送，请输入短信验证码")
                else:
                    if action == "verify":
                        self.protocol.verify(value)
                    else:
                        self.client.identity()
                    self.broker.save(self.client.storage_state())
                    success = True
                if not future.done():
                    future.set_result({"ok": True, "message": self.broker.message})
            except ExtraVerificationRequired as exc:
                blocked = True
                self.broker.update("manual_required", str(exc))
                if not future.done():
                    future.set_result({"ok": False, "message": self.broker.message})
            except Exception as exc:
                state = "manual_required" if blocked else "sms_sent" if self.protocol.phone else "login_required"
                message = (str(exc) if isinstance(exc, AuthError) else
                           "尚未确认风神业务登录状态，请重新检查；不会自动重发验证码")
                self.broker.update(state, message)
                if not future.done():
                    future.set_result({"ok": False, "message": message})
            finally:
                value = ""
            if success:
                self.log("[登录] 接口认证成功，继续原任务")
                return True
        raise AuthError("等待短信认证超时，任务已停止；请重新启动任务")


def standalone_http_login(owner, cancelled, entered):
    try:
        from fengshen_http import FengshenHttpClient
        with BROKER.operation(owner, cancelled, transport="http"):
            entered.set()
            client = None
            try:
                client = FengshenHttpClient(BROKER.vault.load(), cancelled=cancelled)
                HTTPAuth(client, BROKER, cancelled).ensure()
            except Exception as exc:
                BROKER.update("signed_out" if cancelled.is_set() else "error",
                              str(exc) if isinstance(exc, AuthError) else "风神接口登录连接失败，请检查网络后重试")
            finally:
                if client is not None:
                    client.close()
    except AuthError:
        pass  # Another active operation owns the shared broker.
    finally:
        entered.set()


def start_http_login(owner):
    with START_LOCK:
        if BROKER.active:
            return BROKER.status(owner)
        cancelled, entered = threading.Event(), threading.Event()
        threading.Thread(target=standalone_http_login, args=(owner, cancelled, entered),
                         name="fengshen-http-login", daemon=True).start()
        entered.wait(3)
        return BROKER.status(owner)
