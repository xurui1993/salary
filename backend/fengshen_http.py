"""Browser-free Fengshen transport for the independent download center.

Only observed endpoints are allowed. Export requests are sent once and have a
durable local receipt before transmission. Authentication is restored from the
existing user-bound encrypted vault; SMS authentication is a separate adapter.
"""
import json
import re
import threading
import time
import uuid
from pathlib import Path
from urllib.parse import urljoin, urlsplit
from urllib.parse import urlencode

import requests

from fengshen_auth import safe_state
from fengshen_bill import (
    AuthenticationRequired, BillCollectionError, DAILY_CREATE_URL,
    DAILY_QUERY_URL, DAILY_DOWNLOAD_URL, MONTHLY_QUERY_URL, MONTHLY_EXPORT_URL,
    atomic_json, check_response_payload,
)
from fengshen_orders import secure_file_url, QUERY_URL, TASKS_URL, TASK_URL, EXPORT_URL, VIOLATIONS_URL, ENUMERATE_URL
from fengshen_merchant_protocol import INVITE_AUTH,INVITE_ROOT,INVITE_TEAMS,INVITE_QUERY,GRAY_URL,ATTENDANCE_EXPORT

SESSION_ROOT = "https://httpizza.ele.me/lpd.meepo.session/aeolus/"
INIT_URL = SESSION_ROOT + "init"
AGENCIES_URL = SESSION_ROOT + "switchableAgency"
SWITCH_URL = SESSION_ROOT + "switchAgency"
RECEIVE_QUERY = "https://httpizza.ele.me/lpd.meepo.mgmt/payment/queryReceiveAccount"
RECEIVE_EXPORT = "https://httpizza.ele.me/lpd.meepo.mgmt/payment/exportReceiveAccount"
DETAIL_QUERY = "https://httpizza.ele.me/lpd_soc.dashboard/apollo/carrier_driver/analysis/index"
DETAIL_LIST = "https://httpizza.ele.me/lpd_soc.dashboard/apollo/v1.0/export/list/page"
DETAIL_EXPORT = "https://httpizza.ele.me/lpd_soc.dashboard/apollo/carrier_driver/analysis/asyncExport"
DETAIL_OSS = "https://httpizza.ele.me/lpd_soc.dashboard/apollo/v1.0/export/list/oss"
DETAIL_SWITCH = "https://httpizza.ele.me/lpd_soc.dashboard/apollo/v1.0/front/rollBack/switch"
INDICATORS = "https://httpizza.ele.me/lpd_soc.dashboard/apollo/indicator/aeolus/indicators"
TEAMS_URL = "https://httpizza.ele.me/xtop/xtop.lpd.intelligentConfig.getTeamsAll/1.0"
INFO_QUERY = "https://app2-edu.ele.me/kunkka-svr/ehr/staff/knight/list"
INFO_EXPORT = "https://app2-edu.ele.me/kunkka-svr/ehr/staff/download"
GOODS_RENT_URL = "https://httpizza.ele.me/xtop/xtop.knight.task.mng.growth.knightRentPizza.exportRentRecord/1.0"
INFO_CHECK = "https://app2-edu.ele.me/kunkka-svr/exportStaff/needCheck"
INFO_SEND = "https://app2-edu.ele.me/kunkka-svr/exportStaff/sendVerifyCode"
API_METHODS = {
    INIT_URL: "GET", AGENCIES_URL: "GET", SWITCH_URL: "POST",
    DAILY_QUERY_URL: "GET", DAILY_CREATE_URL: "POST",
    MONTHLY_QUERY_URL: "POST", MONTHLY_EXPORT_URL: "POST",
    QUERY_URL: "POST", TASKS_URL: "POST", TASK_URL: "POST",
    EXPORT_URL: "POST", VIOLATIONS_URL: "POST", ENUMERATE_URL: "POST",
    RECEIVE_QUERY: "GET", DETAIL_QUERY: "GET", DETAIL_LIST: "GET", DETAIL_EXPORT: "POST",
    DETAIL_OSS: "POST", DETAIL_SWITCH: "GET", INDICATORS: "POST", TEAMS_URL: "POST",
    INFO_QUERY: "GET", INFO_CHECK: "GET", INFO_SEND: "POST",
    GOODS_RENT_URL: "POST",
    INVITE_AUTH:'GET',INVITE_TEAMS:'GET',INVITE_QUERY:'GET',GRAY_URL:'POST',ATTENDANCE_EXPORT:'POST',
}
# Only reads may be repeated after an explicit authentication rejection.
# Creating an export is never retried by the transport, even after re-login.
READ_ONLY_URLS = frozenset({AGENCIES_URL, DAILY_QUERY_URL, MONTHLY_QUERY_URL, QUERY_URL, TASKS_URL, TASK_URL,
                          RECEIVE_QUERY, DETAIL_QUERY, DETAIL_LIST, DETAIL_OSS, DETAIL_SWITCH, INDICATORS,
                          TEAMS_URL, INFO_QUERY, INFO_CHECK, GOODS_RENT_URL, ENUMERATE_URL,
                          INVITE_AUTH,INVITE_TEAMS,INVITE_QUERY,GRAY_URL})
DETAIL_DIRECT_EXPORT = "https://httpizza.ele.me/lpd_soc.dashboard/apollo/carrier_driver/analysis/pizza/export"
FILE_METHODS = {DAILY_DOWNLOAD_URL: "GET", RECEIVE_EXPORT: "GET", INFO_EXPORT: "POST",
                DETAIL_DIRECT_EXPORT: "POST"}
MAX_JSON = 4 * 1024 * 1024
MAX_FILE = 200 * 1024 * 1024


class HttpTransportError(BillCollectionError):
    def __init__(self, message, phase="preparing", submission="not_submitted"):
        super().__init__(message)
        self.download_failure_phase = phase
        self.download_submission_state = submission


class PlatformRateLimited(HttpTransportError):
    def __init__(self):
        super().__init__("平台请求频率受限，请稍后恢复原任务；无需因此重新登录")


class FengshenHttpClient:
    """One worker owns one client; use the application collection lock outside it."""

    def __init__(self, state=None, *, session=None, files_session=None, cancelled=None):
        self.session = session if session is not None else requests.Session()
        # Signed file URLs use a different session: no platform cookies or shard.
        self.files_session = files_session if files_session is not None else requests.Session()
        self.cancelled = cancelled if cancelled is not None else threading.Event()
        self.auth_handler = None
        self.current_agency = None
        self.timeout = (10, 45)
        self.attempts = 4
        self.download_attempts = 3
        self._refreshing_auth = False
        self._last_order_query = None
        self.origins = []
        if state is not None:
            state = safe_state(state)
            self.origins = state["origins"]
            for cookie in state["cookies"]:
                if not all(isinstance(cookie.get(k), str) for k in ("name", "value", "domain")):
                    raise HttpTransportError("加密会话中的 Cookie 格式无效")
                expiry = cookie.get("expires", -1)
                if not isinstance(expiry, (int, float)) or isinstance(expiry, bool):
                    raise HttpTransportError("加密会话中的有效期格式无效")
                if expiry > 0 and expiry <= time.time():
                    continue
                self.session.cookies.set(
                    cookie["name"], cookie["value"], domain=cookie["domain"],
                    path=cookie.get("path", "/"), secure=True,
                    expires=int(expiry) if expiry > 0 else None,
                    rest={"HttpOnly": cookie.get("httpOnly", False), "SameSite": cookie.get("sameSite", "Lax")},
                )

    def close(self):
        self.session.close()
        self.files_session.close()

    def checkpoint(self):
        if self.cancelled.is_set():
            raise HttpTransportError("下载已取消")

    def storage_state(self):
        return safe_state({"origins": self.origins, "cookies": [
            {"name": c.name, "value": c.value, "domain": c.domain, "path": c.path,
             "secure": True, "expires": c.expires if c.expires is not None else -1,
             "httpOnly": bool(c.get_nonstandard_attr("HttpOnly", False)),
             "sameSite": c.get_nonstandard_attr("SameSite", "Lax")}
            for c in self.session.cookies]})

    def _headers(self, url):
        result = {"Accept": "application/json", "Origin": "https://aeolus.ele.me",
                  "Referer": "https://aeolus.ele.me/"}
        if url==INVITE_AUTH or url.startswith(INVITE_ROOT):result.update(Origin='https://aero-rush.ele.me',Referer='https://aero-rush.ele.me/team-invite/index.html')
        if urlsplit(url).hostname == "httpizza.ele.me":
            # Resolve the cookie for this actual host, never pick an unrelated
            # cookie with the same name from another platform domain.
            prepared = self.session.prepare_request(requests.Request("GET", url))
            match = re.search(r"(?:^|;\s*)PASSPORT_AGENTS_SHARD=([^;]+)", prepared.headers.get("Cookie", ""))
            if match:
                result["X-Shard"] = match.group(1)
        return result

    @staticmethod
    def _bounded_body(response, limit):
        data = bytearray()
        for chunk in response.iter_content(65536):
            data.extend(chunk)
            if len(data) > limit:
                raise HttpTransportError("平台响应超过大小限制")
        return bytes(data)

    def request_json(self, method, url, *, params=None, body=None, shard_id=None):
        try:
            return self._request_with_backoff(method, url, params=params, body=body, shard_id=shard_id)
        except AuthenticationRequired:
            if url not in READ_ONLY_URLS or not self.auth_handler or self._refreshing_auth:
                raise
            self._refreshing_auth = True
            try:
                self.auth_handler()
                if self.current_agency:
                    self.select_city(self.current_agency)
                return self._request_with_backoff(method, url, params=params, body=body, shard_id=shard_id)
            finally:
                self._refreshing_auth = False

    def _request_with_backoff(self, method, url, **kwargs):
        for attempt in range(self.attempts):
            try:
                return self._request_json_once(method, url, **kwargs)
            except PlatformRateLimited:
                # Only explicit rate rejection of a known read may be replayed.
                # Exports, SMS and city-switch mutations never enter this retry.
                if url not in READ_ONLY_URLS or attempt == self.attempts - 1:
                    raise
                self.cancelled.wait(2 ** (attempt + 1))
                self.checkpoint()

    def _request_json_once(self, method, url, *, params=None, body=None, shard_id=None):
        self.checkpoint()
        if API_METHODS.get(url) != method:
            raise HttpTransportError("接口或请求方式尚未核实，已停止调用")
        if url == QUERY_URL:
            if self._last_order_query is not None:
                self.cancelled.wait(max(0, 2.0 - (time.monotonic() - self._last_order_query)))
                self.checkpoint()
            self._last_order_query = time.monotonic()
        headers = self._headers(url)
        if shard_id is not None:
            if url != DETAIL_OSS or not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", str(shard_id)):
                raise HttpTransportError("文件分片标识无效")
            headers["X-Shard"] = "shardid=" + str(shard_id)
        try:
            response = self.session.request(method, url, params=params, json=body,
                                            headers=headers, timeout=self.timeout,
                                            allow_redirects=False, stream=True)
            with response:
                if response.status_code == 429:
                    raise PlatformRateLimited()
                if response.status_code == 401:
                    raise AuthenticationRequired("风神登录已失效")
                if response.status_code == 403:
                    raise HttpTransportError("当前账号无接口权限或平台要求额外验证")
                if 300 <= response.status_code < 400:
                    raise AuthenticationRequired("风神要求重新认证，已停止接口请求")
                if response.status_code != 200:
                    raise HttpTransportError("风神接口请求未成功，请检查网络或平台状态")
                try:
                    value = json.loads(self._bounded_body(response, MAX_JSON))
                except (ValueError, UnicodeError):
                    raise HttpTransportError("风神接口响应格式变化，已停止处理") from None
                envelopes = (value, value.get("result")) if isinstance(value, dict) else ()
                if any(isinstance(envelope, dict) and str(envelope.get("code")) in
                       ("REQUEST_TOO_FREQUENT", "429") for envelope in envelopes):
                    raise PlatformRateLimited()
                check_response_payload(value)
                return value
        except requests.RequestException:
            # Never echo request exceptions: URLs and bodies can contain tokens.
            raise HttpTransportError("风神接口连接失败或超时，不会自动重复提交") from None

    def identity(self):
        payload = self.request_json("GET", INIT_URL)
        data = payload.get("data")
        if not isinstance(data, dict) or not re.fullmatch(r"\d{1,20}", str(data.get("agencyId", ""))):
            raise AuthenticationRequired("尚未确认风神合作商登录身份")
        return data

    def select_city(self, agency_id):
        if not isinstance(agency_id, str) or not re.fullmatch(r"\d{1,20}", agency_id):
            raise HttpTransportError("目标城市编号无效")
        payload = self.request_json("GET", AGENCIES_URL)
        agencies = payload.get("data")
        if not isinstance(agencies, list) or not any(
            isinstance(row, dict) and str(row.get("agencyId")) == agency_id for row in agencies
        ):
            raise HttpTransportError("当前风神账号无所选城市访问权限")
        if str(self.identity()["agencyId"]) != agency_id:
            self.request_json("POST", SWITCH_URL, body={"toAgencyId": int(agency_id)})
        self.assert_city(agency_id)
        self.current_agency = agency_id

    def assert_city(self, agency_id):
        if str(self.identity()["agencyId"]) != agency_id:
            raise HttpTransportError("平台当前城市与所选城市不一致，已停止下载")

    def submit_once(self, url, body, receipt_path, scope):
        """A receipt blocks another submission even after a process/network crash."""
        if API_METHODS.get(url) != "POST" or url in READ_ONLY_URLS or url == INFO_SEND:
            raise HttpTransportError("导出提交接口尚未核实")
        receipt_path, receipt = self._begin_submission(receipt_path, scope)
        try:
            result = self.request_json("POST", url, body=body)
        except Exception:
            raise HttpTransportError("导出提交结果尚未确认；已保留记录，不会自动重试", "submitting", "unknown") from None
        receipt.update(submission_state="submitted", finished_at=time.time())
        atomic_json(receipt_path, receipt)
        return result, receipt

    def _begin_submission(self, receipt_path, scope):
        self.checkpoint()
        receipt_path = Path(receipt_path)
        receipt_path.parent.mkdir(parents=True, exist_ok=True)
        receipt = {"transport": "http", "submission_state": "unknown", "scope": scope,
                   "started_at": time.time()}
        try:
            # Exclusive creation, not an exists-then-write race. A truncated
            # receipt still prevents resubmission and requires reconciliation.
            with receipt_path.open("x", encoding="utf-8") as stream:
                json.dump(receipt, stream, ensure_ascii=False)
                stream.flush()
                import os
                os.fsync(stream.fileno())
        except FileExistsError:
            raise HttpTransportError("已有导出提交记录，请查询原任务，不能重复提交", "waiting_export", "unknown") from None
        return receipt_path, receipt

    def download_once(self, method, url, target, receipt_path, scope, *, params=None, body=None):
        """Synchronous file exports obey the same durable no-resubmit rule."""
        if FILE_METHODS.get(url) != method or url == DAILY_DOWNLOAD_URL:
            raise HttpTransportError("同步导出接口尚未核实")
        receipt_path, receipt = self._begin_submission(receipt_path, scope)
        try:
            result = self.download_request(method, url, target, params=params, body=body)
        except Exception:
            raise HttpTransportError("同步导出未完成，已保留提交记录，不会自动重发", "downloading", "unknown") from None
        receipt.update(submission_state="submitted", finished_at=time.time())
        atomic_json(receipt_path, receipt)
        return result

    def download_request(self, method, url, target, *, params=None, body=None):
        if FILE_METHODS.get(url) != method:
            raise HttpTransportError("认证文件接口或请求方式尚未核实")
        return self._download(method, url, target, authenticated=True, params=params, body=body)

    def download(self, url, target, *, authenticated=False):
        """Stream to a temporary file; no redirects can disclose auth headers."""
        return self._download("GET", url, target, authenticated=authenticated)

    def daily_file_url(self, task_id, agency_id):
        """Resolve an existing daily task's signed file URL; no export POST."""
        if (type(task_id) is not int or task_id <= 0 or not isinstance(agency_id, str)
                or not re.fullmatch(r"\d{1,20}", agency_id)):
            raise HttpTransportError("日账单原任务编号或城市无效", "downloading", "submitted")
        url = DAILY_DOWNLOAD_URL + "?" + urlencode({"id": task_id, "agentId": agency_id})
        self.checkpoint()
        try:
            response = self.session.get(url, headers=self._headers(url), timeout=(10, 45),
                                        allow_redirects=False, stream=True)
            with response:
                if response.status_code in (401, 302, 303, 307, 308):
                    raise AuthenticationRequired("日账单原文件读取需要重新登录")
                if response.status_code != 200:
                    raise HttpTransportError("平台未返回原日账单文件地址", "downloading", "submitted")
                try:
                    value = json.loads(self._bounded_body(response, MAX_JSON))
                except (ValueError, UnicodeError):
                    raise HttpTransportError("原日账单文件地址格式变化", "downloading", "submitted") from None
                if not isinstance(value, str):
                    raise HttpTransportError("原日账单文件地址不是字符串", "downloading", "submitted")
                return secure_file_url(value)
        except requests.RequestException:
            raise HttpTransportError("原日账单文件地址连接失败", "downloading", "submitted") from None

    def _download(self, method, url, target, *, authenticated=False, params=None, body=None):
        target = Path(target)
        if target.exists():
            raise HttpTransportError("目标文件已存在，未覆盖原文件", "downloading", "submitted")
        for attempt in range(self.download_attempts):
            if attempt:
                # 只重新领取同一签名地址的同一份文件；导出任务不重复提交。
                self.cancelled.wait(2 ** attempt)
                self.checkpoint()
            try:
                return self._download_once(method, url, target, authenticated=authenticated,
                                           params=params, body=body)
            except requests.RequestException:
                continue
        raise HttpTransportError("文件连接中断；原导出任务保留，不会重新导出", "downloading", "submitted") from None

    def _download_once(self, method, url, target, *, authenticated=False, params=None, body=None):
        target = Path(target)
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_name(target.name + "." + uuid.uuid4().hex + ".part")
        try:
            for hop in range(6):
                self.checkpoint()
                parsed = urlsplit(url)
                if authenticated:
                    if FILE_METHODS.get(parsed.scheme + "://" + parsed.netloc + parsed.path) != method or parsed.fragment:
                        raise HttpTransportError("认证下载地址不在已核实接口列表中")
                    session, headers = self.session, self._headers(url)
                else:
                    url = secure_file_url(url)
                    session, headers = self.files_session, {"Accept": "application/octet-stream"}
                options = {"headers": headers, "timeout": (10, 60), "allow_redirects": False, "stream": True}
                if params is not None:
                    options["params"] = params
                if body is not None:
                    options["json"] = body
                with (session.get if method == "GET" else session.post)(url, **options) as response:
                    if 300 <= response.status_code < 400:
                        next_url = urljoin(url, response.headers.get("Location", ""))
                        secure_file_url(next_url)
                        if not response.headers.get("Location"):
                            raise HttpTransportError("平台文件重定向缺少地址")
                        url, authenticated, method, params, body = next_url, False, "GET", None, None
                        continue
                    if response.status_code != 200:
                        raise HttpTransportError("平台文件下载失败", "downloading", "submitted")
                    if "json" in response.headers.get("Content-Type", "").lower():
                        raise HttpTransportError("平台未返回文件，请检查导出权限或验证码", "downloading", "unknown")
                    size = 0
                    with temporary.open("xb") as output:
                        for chunk in response.iter_content(65536):
                            self.checkpoint()
                            size += len(chunk)
                            if size > MAX_FILE:
                                raise HttpTransportError("平台文件超过大小限制", "downloading", "submitted")
                            output.write(chunk)
                    if not size:
                        raise HttpTransportError("平台返回了空文件", "downloading", "submitted")
                    # rename on Windows refuses an existing target.
                    temporary.rename(target)
                    return target
            raise HttpTransportError("平台文件重定向次数异常", "downloading", "submitted")
        finally:
            temporary.unlink(missing_ok=True)
