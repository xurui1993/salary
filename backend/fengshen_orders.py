"""Template-scoped waybill and violation exports for part-time payroll."""

import argparse
from dataclasses import dataclass
import datetime as dt
import csv
import hashlib
import json
import os
from pathlib import Path
import re
import time
import uuid
from urllib.parse import urlparse

from fengshen_bill import (
    WAYBILL_URL, PROJECT_ROOT, BillCollectionError, BillPageCollector,
    AuthenticationRequired, atomic_json, check_response_payload, inspect_page,
    CityPopupNotClosed,
    nested_value, safe_operation_failure, save_inspection, schema_only, validate_bill_file,
)

SHANGHAI = dt.timezone(dt.timedelta(hours=8))
EXPORT_URL = "https://httpizza.ele.me/xtop/xtop.merchant.agencyTrackingFs.exportTracking/2.0"
TASKS_URL = "https://httpizza.ele.me/xtop/xtop.merchant.agencyTrackingFs.agencyTrackingFs.queryExportTask/2.0"
TASK_URL = "https://httpizza.ele.me/xtop/xtop.merchant.agencyTrackingFs.agencyTrackingFs.queryTaskUrl/2.0"
VIOLATIONS_URL = "https://httpizza.ele.me/xtop/xtop.lpd.quality.control.violation.violationOrderAeolusCenterApi.download/1.0"
QUERY_URL = "https://httpizza.ele.me/xtop/xtop.agencyTrackingFs.queryTracking/2.0"
ENUMERATE_URL = "https://httpizza.ele.me/xtop/xtop.merchant.agencyTrackingFs.queryEnumerate/2.0"
ALL_CITY_SEND_PRODUCT = "全城送"
LEGACY_FILE_HOST = "lpd-cs-delivery-ext-shprod-al-oss-1.oss-cn-shanghai.aliyuncs.com"
LEGACY_FILE_HOSTS = frozenset({LEGACY_FILE_HOST,
    "lpd-cs-delivery-ext-zbprod-zb1-oss-1.oss-cn-zhangjiakou.aliyuncs.com"})


def secure_file_url(url):
    try:
        parsed = urlparse(url) if isinstance(url, str) else None
        if (not parsed or parsed.username or parsed.password or parsed.fragment
                or not (parsed.hostname or "").endswith((".ele.me", ".aliyuncs.com"))):
            raise ValueError
        if parsed.scheme == "http" and parsed.hostname in LEGACY_FILE_HOSTS and parsed.port is None:
            parsed = parsed._replace(scheme="https")
        if parsed.scheme != "https" or parsed.port not in (None, 443):
            raise ValueError
        return parsed.geturl()
    except ValueError:
        raise BillCollectionError("导出文件地址不是已确认的官方 HTTPS 文件域名") from None


def validate_order_profile(profile, *, acceptance_only=False):
    if not isinstance(profile, dict) or (profile.get("verified") is not True and not acceptance_only):
        raise BillCollectionError("运单及问题单自动下载配置待真实联调，核算已停止")
    if (profile.get("dataset") != "issue_orders" or profile.get("selection_mode") != "target_city"
            or profile.get("time_basis") != "tracking_finish" or profile.get("all_city_riders") is not True):
        raise BillCollectionError("运单必须按完成时间采集目标物流合作商城市全部骑手")
    required = ("agency_context", "city_trigger", "city_popup", "city_group", "city_group_label",
                "city_option", "city_selected_option", "city_confirm", "city_close", "content_frame",
                "reset_button", "query_button", "submit_button", "date_trigger", "date_option",
                "start_input", "end_input", "all_state_value", "all_label_value")
    if any(not isinstance(profile.get(key), str) or not profile[key].strip() for key in required):
        raise BillCollectionError("运单页面配置缺少已观察的控件或不限状态标识")
    if not re.fullmatch(r"\d{1,20}", str(profile.get("expected_agency_id", ""))):
        raise BillCollectionError("运单页面配置缺少固定物流合作商编号")
    if any(profile[key].count("{agency_id}") != 1 for key in ("city_option", "city_selected_option")):
        raise BillCollectionError("运单城市必须按物流合作商固定编号定位")
    return profile


def waybill_scope(payload, request, profile, export=False, created=False, product_id=None):
    if not isinstance(payload, dict):
        return False
    params = payload.get("params")
    body = params.get("request") if isinstance(params, dict) else None
    if not isinstance(body, dict):
        return False
    first, last = request.timestamps
    start_key = "trackingCreatedStart" if created else "trackingFinishStart"
    end_key = "trackingCreatedEnd" if created else "trackingFinishEnd"
    period_key = "trackingCreatedTimePeriodList" if created else "trackingFinishTimePeriodList"
    if body.get(start_key) != first or body.get(end_key) != last:
        return False
    if export and "exportType" in body and (isinstance(body["exportType"], bool) or body["exportType"] != 1):
        return False
    allowed = {start_key, end_key, "exportType", "current", "pageSize"}
    for key, value in body.items():
        if key in allowed or value is None or value == "" or value == []:
            continue
        if key == period_key and value == ["0-86400"]:
            continue
        if key == "trackingStateKey" and value == profile["all_state_value"]:
            continue
        if key == "trackingLabelKey" and value == profile["all_label_value"]:
            continue
        if key in ("merchantConsumerDistanceStart", "payAmountStart", "weightStart") and str(value) == "0":
            continue
        if key in ("merchantConsumerDistanceEnd", "payAmountEnd", "weightEnd") and str(value) == "999999":
            continue
        if key == "agencyIds" and isinstance(value, list) and len(value) == 1 and str(value[0]) == request.agency_id:
            continue
        if (key == "productIdList" and product_id is not None and isinstance(value, list)
                and len(value) == 1 and type(value[0]) is int and value[0] == product_id):
            continue
        return False
    return True


def task_rows(payload):
    check_response_payload(payload)
    data = nested_value(payload, ["result", "data", "data"])
    if not isinstance(data, list):
        raise BillCollectionError("运单导出任务列表结构发生变化")
    rows = []
    for row in data:
        if not isinstance(row, dict) or isinstance(row.get("id"), bool) or not re.fullmatch(r"\d{1,20}", str(row.get("id", ""))):
            raise BillCollectionError("运单导出任务编号无效")
        rows.append(row)
    if len({str(row["id"]) for row in rows}) != len(rows):
        raise BillCollectionError("运单导出任务编号重复")
    return rows


def new_task(baseline, current, started, finished):
    candidates = []
    for row in current:
        timestamp = row.get("exportTime")
        if (str(row["id"]) not in baseline and isinstance(timestamp, int) and not isinstance(timestamp, bool)
                and started - 3000 <= timestamp <= finished + 3000):
            candidates.append(row)
    if len(candidates) > 1:
        raise BillCollectionError("同一时间出现多个新运单导出任务，不能唯一关联本批")
    return candidates[0] if candidates else None


def query_count(payload, agency_id):
    check_response_payload(payload)
    data = nested_value(payload, ["result", "data"])
    if not isinstance(data, dict) or isinstance(data.get("total"), bool) or not isinstance(data.get("total"), int) or data["total"] < 0:
        raise BillCollectionError("运单查询缺少有效数据总数")
    records = data.get("data")
    if not isinstance(records, list) or any(not isinstance(row, dict) or str(row.get("agencyId")) != agency_id for row in records):
        raise BillCollectionError("运单查询返回了非目标城市记录")
    if data["total"] == 0 and records:
        raise BillCollectionError("运单查询总数与记录不一致")
    return data["total"]


def query_response_matches(response, request):
    if response.url.split("?")[0] != QUERY_URL or response.request.method != "POST":
        return False
    try:
        body = nested_value(response.request.post_data_json, ["params", "request"])
        first, last = request.timestamps
        return isinstance(body, dict) and body.get("trackingFinishStart") == first and body.get("trackingFinishEnd") == last
    except (ValueError, TypeError, BillCollectionError):
        return False


QUERY_STAGES = {
    "city": "核对物流合作商城市", "tour": "关闭普通引导", "reset": "重置筛选",
    "date_basis": "选择完成时间口径", "dates": "填写日期", "query": "等待查询响应",
    "count": "读取查询数量", "recover": "重新载入运单页面",
}


class OrderPageCollector(BillPageCollector):
    page_url = WAYBILL_URL
    profile_validator = staticmethod(validate_order_profile)

    def checkpoint(self):
        if self.cancelled is not None and self.cancelled.is_set():
            raise BillCollectionError("任务已取消，运单采集及核算已停止")

    def _post(self, url, body):
        self.checkpoint()
        response = self.page.context.request.post(url, data=body, timeout=30000)
        try:
            if response.status == 401 or urlparse(response.url).hostname == "mozi-login.alibaba-inc.com":
                raise AuthenticationRequired("运单采集登录已失效")
            if response.status != 200:
                raise BillCollectionError("运单或服务奖惩接口失败")
            payload = response.json()
            check_response_payload(payload)
            return payload
        finally:
            response.dispose()

    def _tasks(self):
        return task_rows(self._post(TASKS_URL, {"params": {"request": {"current": 1, "pageSize": 20}}}))

    def _wait(self):
        for _ in range(int(self.poll_interval * 5)):
            self.checkpoint()
            self.page.wait_for_timeout(200)

    def apply_request(self, request):
        from playwright.sync_api import TimeoutError as BrowserTimeout
        self.operation_stage = "query"
        self.query_context = {"start": request.start, "end": request.end, "agency_id": request.agency_id}        # Only read-only queries can be replayed. Export submission never enters this retry loop.
        for attempt in range(3):
            self.checkpoint()
            self.query_attempt = attempt + 1
            try:
                if attempt:
                    self.query_stage = "recover"
                    self.page.goto(WAYBILL_URL, wait_until="domcontentloaded", timeout=60000)
                result = self._apply_request_once(request)
                atomic_json(self.output_dir / "query_state.json", {
                    "status": "success", **self.query_context, "attempt": self.query_attempt, "total": result,
                })
                if not hasattr(self, "query_history"):
                    self.query_history = []
                self.query_history.append({**self.query_context, "attempts": self.query_attempt, "total": result})
                atomic_json(self.output_dir / "query_history.json", self.query_history)
                return result
            except (BrowserTimeout, CityPopupNotClosed) as exc:
                self._record_query_failure(exc)
                self.checkpoint()
                if urlparse(self.page.url).hostname == "mozi-login.alibaba-inc.com":
                    raise AuthenticationRequired("运单查询超时后发现登录已失效") from None
                stage = QUERY_STAGES.get(getattr(self, "query_stage", ""), "网页操作")
                if attempt == 2:
                    raise BillCollectionError(
                        f"运单 {request.start} 至 {request.end}：{stage}超时，3 次只读尝试均未完成；核算已停止，详见 query_failure_*.json"
                    ) from None
                self.log(f"[查询重试] {request.start} 至 {request.end}：{stage}超时，正在第 {attempt + 2}/3 次只读尝试；不会重复创建导出任务")
                self.page.wait_for_timeout(1000 * (attempt + 1))

    def _record_query_failure(self, exc):
        atomic_json(self.output_dir / f"query_failure_{self.query_context['start']}_{self.query_context['end']}_{self.query_attempt}.json", {
            "status": "error", **self.query_context, "attempt": self.query_attempt,
            "stage": getattr(self, "query_stage", "unknown"), "control": self.last_control,
            "failure": safe_operation_failure(exc),
        })

    def _apply_request_once(self, request):
        parsed = urlparse(self.page.url)
        if parsed.hostname != "aeolus.ele.me" or parsed.fragment != urlparse(WAYBILL_URL).fragment:
            raise AuthenticationRequired("尚未进入运单数据页，请完成风神登录")
        self.query_stage = "city"
        self._check_agency_context()
        self.query_stage = "tour"
        frame = self._content()
        tour = frame.locator("button.ant-tour-close:visible")
        if tour.count() == 1:
            tour.click()
        self.query_stage = "reset"
        self._control("reset_button").click()
        self.query_stage = "date_basis"
        self._control("date_trigger").click()
        self._control("date_option").click()
        self.query_stage = "dates"
        for key, value in (("start_input", request.start), ("end_input", request.end)):
            self._set_date(key, value)
        self.query_stage = "query"
        with self.page.expect_response(lambda response: query_response_matches(response, request), timeout=30000) as pending:
            self._control("query_button").click()
        response = pending.value
        if response.status == 401:
            raise AuthenticationRequired("运单查询登录已失效")
        if response.status != 200 or not waybill_scope(response.request.post_data_json, request, self.profile):
            raise BillCollectionError("实际运单查询不是本批完成时间和全城市范围")
        self.query_stage = "count"
        payload = response.json()
        return query_count(payload, request.agency_id)

    def daily_counts(self, request):
        result = {}
        first, last = dt.date.fromisoformat(request.start), dt.date.fromisoformat(request.end)
        while first <= last:
            date = first.isoformat()
            day = OrderRequest(date, date, request.agency_id)
            self.log(f"[逐日校验] 正在查询 {date} 完成时间的全城市运单数量")
            result[date] = self.apply_request(day)
            first += dt.timedelta(days=1)
        return result

    def _download(self, url, name, xlsx=False):
        import requests
        parsed = urlparse(url) if isinstance(url, str) else None
        atomic_json(self.output_dir / (name + ".origin.json"), {
            "scheme": parsed.scheme if parsed else None,
            "hostname": parsed.hostname if parsed else None,
            "port": parsed.port if parsed else None,
            "has_credentials": bool(parsed and (parsed.username or parsed.password)),
        })
        url = secure_file_url(url)
        temporary, destination = self.output_dir / (name + ".part"), self.output_dir / name
        size, checksum = 0, hashlib.sha256()
        try:
            with requests.get(url, stream=True, timeout=(10, 60), allow_redirects=False) as response:
                if response.status_code != 200:
                    raise BillCollectionError("本批原始文件下载失败")
                with temporary.open("wb") as output:
                    for chunk in response.iter_content(1024 * 1024):
                        self.checkpoint()
                        size += len(chunk)
                        if size > 200 * 1024 * 1024:
                            raise BillCollectionError("本批导出文件超过大小限制")
                        output.write(chunk)
                        checksum.update(chunk)
            if not size:
                raise BillCollectionError("下载文件为空，不能作为无记录处理")
            if xlsx and validate_bill_file(temporary)["format"] != "xlsx":
                raise BillCollectionError("运单导出不是 XLSX 文件")
            os.replace(temporary, destination)
            return {"path": name, "bytes": size, "sha256": checksum.hexdigest()}
        except BillCollectionError:
            raise
        except Exception:
            raise BillCollectionError("原始文件下载中断，核算已停止") from None
        finally:
            temporary.unlink(missing_ok=True)

    def _empty_file(self, name, columns):
        path = self.output_dir / name
        with path.open("w", encoding="utf-8-sig", newline="") as output:
            csv.writer(output).writerow(sorted(columns))
        return {"path": name, "bytes": path.stat().st_size,
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "platform_confirmed_empty": True}

    def _export_waybills(self, request, state):
        if state.get("task_id"):
            task_id = state["task_id"]
        else:
            state["expected_waybills_by_date"] = self.daily_counts(request)
            total = self.apply_request(request)
            state["expected_waybills"] = total
            if total == 0:
                from order_sources import WAYBILL_COLUMNS
                return self._empty_file("waybills_empty.csv", WAYBILL_COLUMNS)
            self.operation_stage = "task_baseline"
            baseline = {str(row["id"]) for row in self._tasks()}
            checked = {"matched": False, "blocked": False}
            def guard(route):
                atomic_json(self.output_dir / "export_scope.json", {"request_schema": schema_only(route.request.post_data_json),
                            "scope_matched": waybill_scope(route.request.post_data_json, request, self.profile, export=True)})
                if waybill_scope(route.request.post_data_json, request, self.profile, export=True):
                    checked["matched"] = True
                    route.continue_()
                else:
                    checked["blocked"] = True
                    route.abort()
            state["submitted"] = True
            self.operation_stage = "export_submission"
            started = int(time.time() * 1000)
            self.page.context.route(EXPORT_URL, guard)
            try:
                with self.page.expect_response(lambda response: response.url.split("?")[0] == EXPORT_URL
                        and response.request.method == "POST", timeout=30000) as pending:
                    self._control("submit_button").click()
                response = pending.value
                if checked["blocked"] or not checked["matched"]:
                    raise BillCollectionError("实际运单导出范围不符，已阻止提交")
                if response.status == 401:
                    state["submitted"] = False
                    raise AuthenticationRequired("平台在创建运单任务前拒绝了登录")
                if response.status != 200:
                    raise BillCollectionError("运单创建任务响应失败，未重复提交")
                try:
                    check_response_payload(response.json())
                except AuthenticationRequired:
                    state["submitted"] = False
                    raise
                finished = int(time.time() * 1000)
            except Exception:
                if checked["blocked"]:
                    raise BillCollectionError("实际运单导出范围不符，已阻止提交") from None
                raise
            finally:
                self.page.context.unroute(EXPORT_URL, guard)
            deadline = time.monotonic() + 30
            self.operation_stage = "task_association"
            while True:
                row = new_task(baseline, self._tasks(), started, finished)
                if row is not None:
                    task_id = str(row["id"])
                    state["task_id"] = task_id
                    atomic_json(self.output_dir / "task.json", {"task_id": task_id, "agency_id": request.agency_id,
                                "start": request.start, "end": request.end, "time_basis": "tracking_finish"})
                    break
                if time.monotonic() >= deadline:
                    raise BillCollectionError("无法唯一关联本批新运单导出任务，未下载旧记录")
                self._wait()
        deadline = time.monotonic() + self.timeout
        self.operation_stage = "task_poll"
        while time.monotonic() < deadline:
            matches = [row for row in self._tasks() if str(row["id"]) == task_id]
            if len(matches) != 1:
                raise BillCollectionError("本批运单任务已无法唯一定位")
            row = matches[0]
            if row.get("statusDesc") == "导出成功":
                if row.get("status") != 1 or isinstance(row.get("status"), bool):
                    raise BillCollectionError("运单成功状态编号与已观察结果不一致")
                payload = self._post(TASK_URL, {"params": {"request": {"taskId": int(task_id)}}})
                self.operation_stage = "waybill_download"
                return self._download(nested_value(payload, ["result", "data"]), "waybills.xlsx", xlsx=True)
            if row.get("statusDesc") in ("导出失败", "失败"):
                raise BillCollectionError("本批运单导出失败，核算已停止")
            self._wait()
        raise BillCollectionError("本批运单生成超时，保留任务编号；核算已停止")

    def collect_batches(self, start, end, cancelled=None, include_violations=True):
        self.cancelled = cancelled
        outputs = []
        base = self.output_dir
        batches = date_batches(start, end)
        number, first, last, state = 0, start, end, {}
        try:
            for number, (first, last) in enumerate(batches, 1):
                state = {}
                self.query_history = []
                self.operation_stage = "batch_start"
                self.output_dir = base / (first + "_" + last)
                self.output_dir.mkdir(parents=True, exist_ok=False)
                request = OrderRequest(first, last, str(self.profile["expected_agency_id"]))
                self.log(f"[运单采集] 第 {number}/{len(batches)} 批：{first} 至 {last}，按完成时间")
                files = {}
                for attempt in range(2):
                    try:
                        files["waybills"] = self._export_waybills(request, state)
                        if include_violations:
                            self.operation_stage = "violation_export"
                            first_ms, last_ms = request.timestamps
                            payload = self._post(VIOLATIONS_URL, {"params": {"request": {
                                "violationStartTime": first_ms, "violationEndTime": last_ms, "appealStatus": []}}})
                            file_url = nested_value(payload, ["result", "data", "fileUrl"])
                            if file_url == "":
                                from order_sources import VIOLATION_COLUMNS
                                files["violations"] = self._empty_file("violations_empty.csv", VIOLATION_COLUMNS)
                            else:
                                self.operation_stage = "violation_download"
                                files["violations"] = self._download(file_url, "violations.csv")
                        break
                    except AuthenticationRequired:
                        if attempt or not self.auth or (state.get("submitted") and not state.get("task_id")):
                            raise BillCollectionError("运单登录失效或任务归属未确认，核算已停止；不会重复创建未知任务") from None
                        self.auth(force=True)
                        self._check_agency_context()
                manifest = {"dataset": "issue_orders", "status": "success", "agency_id": request.agency_id,
                            "start": first, "end": last, "time_basis": "tracking_finish", "merchant_group": "物流合作商",
                            "all_city_riders": True, "files": {key: info["path"] for key, info in files.items()},
                            "file_checks": files, "task_id": state.get("task_id"),
                            "expected_waybills": state.get("expected_waybills"),
                            "expected_waybills_by_date": state.get("expected_waybills_by_date")}
                atomic_json(self.output_dir / "manifest.json", manifest)
                outputs.append(manifest)
            return outputs
        except Exception as exc:
            atomic_json(self.output_dir / "failure.json", {
                "status": "error", "batch": number, "batches": len(batches), "start": first, "end": last,
                "query": getattr(self, "query_context", None), "stage": self.operation_stage,
                "query_stage": getattr(self, "query_stage", None),
                "control": self.last_control, "task_id": state.get("task_id"),
                "submitted": bool(state.get("submitted")), "failure": safe_operation_failure(exc),
            })
            message = str(exc) if isinstance(exc, BillCollectionError) else f"网页操作未完成（{type(exc).__name__}），请查看本批 failure.json"
            raise BillCollectionError(f"第 {number}/{len(batches)} 批运单（{first} 至 {last}）：{message}") from None
        finally:
            self.output_dir = base


def date_batches(start, end, today=None):
    today = today or dt.datetime.now(SHANGHAI).date()
    first, last = dt.date.fromisoformat(start), dt.date.fromisoformat(end)
    if first > last:
        raise BillCollectionError("运单开始日期不能晚于结束日期")
    earliest = today - dt.timedelta(days=59)
    if first < earliest or last > today:
        raise BillCollectionError(f"运单仅支持近 60 个自然日：{earliest.isoformat()} 至 {today.isoformat()}；申请周期超出范围，核算已停止")
    batches = []
    while first <= last:
        batch_end = min(first + dt.timedelta(days=4), last)
        batches.append((first.isoformat(), batch_end.isoformat()))
        first = batch_end + dt.timedelta(days=1)
    return batches


@dataclass(frozen=True)
class OrderRequest:
    start: str
    end: str
    agency_id: str

    def __post_init__(self):
        if not re.fullmatch(r"\d{1,20}", str(self.agency_id)):
            raise BillCollectionError("运单采集必须指定目标城市物流合作商编号")
        first, last = dt.date.fromisoformat(self.start), dt.date.fromisoformat(self.end)
        if not 0 <= (last - first).days < 5:
            raise BillCollectionError("每批运单只能采集 1 至 5 个自然日")

    @property
    def timestamps(self):
        first = dt.datetime.combine(dt.date.fromisoformat(self.start), dt.time.min, SHANGHAI)
        last = dt.datetime.combine(dt.date.fromisoformat(self.end), dt.time(23, 59, 59), SHANGHAI)
        return int(first.timestamp() * 1000), int(last.timestamp() * 1000)


def inspection_profile(agency_id):
    profile = json.loads(Path(__file__).with_name("fengshen_bill.profile.json").read_text(encoding="utf-8"))
    profile["expected_agency_id"] = agency_id
    return profile


def inspect_orders(start, end, agency_id):
    """Read controls and export-list structure without creating an export."""
    from playwright.sync_api import sync_playwright
    from fengshen_auth import SessionVault
    request = OrderRequest(start, end, agency_id)
    state = SessionVault().load()
    if state is None:
        raise BillCollectionError("请先在薪酬系统完成风神登录")
    run = PROJECT_ROOT / "outputs" / "fengshen_order_inspection" / uuid.uuid4().hex
    with sync_playwright() as pw:
        browser = pw.chromium.launch(channel="msedge", headless=False)
        try:
            context = browser.new_context(storage_state=state, accept_downloads=True)
            state = None
            page = context.new_page()
            def navigate():
                page.goto(WAYBILL_URL, wait_until="domcontentloaded", timeout=60000)
                page.wait_for_timeout(3000)
                if "dashboard" in urlparse(page.url).fragment:
                    page.goto(WAYBILL_URL, wait_until="domcontentloaded", timeout=60000)
                scope = BillPageCollector(page, inspection_profile(agency_id), run, acceptance_only=True)
                scope.page_url = WAYBILL_URL
                scope._check_agency_context()
                frame = page.frame_locator("iframe[name='sirong-app']")
                tour = frame.locator("button.ant-tour-close:visible")
                if tour.count() == 1:
                    tour.click()
                expand = frame.get_by_text("展开筛选", exact=True)
                if expand.count() == 1 and expand.is_visible():
                    expand.click()
                page.wait_for_timeout(500)
                dropdown = frame.locator(".ant-space-compact:has(input[placeholder='开始日期']) .ant-select-selector")
                BillPageCollector._one(dropdown, "运单时间口径").click()
                choices = frame.locator(".ant-select-dropdown:visible .ant-select-item-option-content").all_text_contents()
                atomic_json(run / "date_options.json", {"inspection_only": True, "options": choices})
                choice = frame.locator(".ant-select-dropdown:visible .ant-select-item-option-content").filter(has_text=re.compile(r"^运单终态时间$"))
                BillPageCollector._one(choice, "运单终态时间").click()
                for placeholder, value in (("开始日期", request.start), ("结束日期", request.end)):
                    control = frame.get_by_placeholder(placeholder, exact=True)
                    BillPageCollector._one(control, placeholder).fill(value)
                    control.press("Enter")
                page.wait_for_timeout(500)
                frame.get_by_role("button", name=re.compile(r"^查\s*询$")).click()
                page.wait_for_timeout(1000)
            report = inspect_page(page, run, navigate=navigate, snapshot_only=True, expected_url=WAYBILL_URL)
            response = context.request.post(TASKS_URL, data={"params": {"request": {"current": 1, "pageSize": 20}}}, timeout=30000)
            payload = response.json()
            atomic_json(run / "task_schema.json", {"inspection_only": True, "http_status": response.status,
                        "response": schema_only(payload), "code": payload.get("code"),
                        "result_code": payload.get("result", {}).get("code"),
                        "statuses": sorted({(row.get("status"), row.get("statusDesc")) for row in
                            payload.get("result", {}).get("data", {}).get("data", [])})})
            print(f"运单只读检查已保存：{report}")
        finally:
            browser.close()
    return run


def main(argv=None):
    parser = argparse.ArgumentParser(description="兼职运单和问题单联调")
    parser.add_argument("--inspect", action="store_true")
    parser.add_argument("--acceptance", action="store_true")
    parser.add_argument("--start")
    parser.add_argument("--end")
    parser.add_argument("--agency-id")
    parser.add_argument("--template", type=Path)
    args = parser.parse_args(argv)
    try:
        if args.inspect == args.acceptance:
            raise BillCollectionError("请选择单页只读检查或隔离验收")
        if args.inspect:
            if args.template or not all((args.start, args.end, args.agency_id)):
                raise BillCollectionError("只读检查需要开始、结束日期及固定物流合作商编号")
            inspect_orders(args.start, args.end, args.agency_id)
        else:
            if not args.template or any((args.start, args.end, args.agency_id)):
                raise BillCollectionError("隔离验收只从指定 template 申请名单读取城市和日期")
            from parttime_source import read_template
            from order_sources import prepare_order_files
            from playwright.sync_api import sync_playwright
            from fengshen_auth import SessionVault
            plan = read_template(args.template)
            batches = date_batches(plan.start, plan.end)
            profile = json.loads(Path(__file__).with_name("fengshen_orders.profile.json").read_text(encoding="utf-8"))
            profile["expected_agency_id"] = plan.agency_id
            validate_order_profile(profile, acceptance_only=True)
            state = SessionVault().load()
            if state is None:
                raise BillCollectionError("请先在系统完成风神登录")
            run = PROJECT_ROOT / "outputs" / "fengshen_order_acceptance" / uuid.uuid4().hex
            raw, inputs = run / "raw", run / "input"
            inputs.mkdir(parents=True)
            with sync_playwright() as pw:
                browser = pw.chromium.launch(channel="msedge", headless=False)
                try:
                    context = browser.new_context(storage_state=state, accept_downloads=True)
                    state = None
                    page = context.new_page()
                    page.goto(WAYBILL_URL, wait_until="domcontentloaded", timeout=60000)
                    page.wait_for_timeout(3000)
                    if "dashboard" in urlparse(page.url).fragment:
                        page.goto(WAYBILL_URL, wait_until="domcontentloaded", timeout=60000)
                    collector = OrderPageCollector(page, profile, raw / "issue_orders", acceptance_only=True)
                    try:
                        downloads = collector.collect_batches(plan.start, plan.end)
                        result = prepare_order_files(downloads, raw, inputs, plan, batches)
                        atomic_json(run / "verification.json", {"status": "success", "city": plan.city,
                                    "agency_id": plan.agency_id, "start": plan.start, "end": plan.end,
                                    "time_basis": "tracking_finish", "merchant_group": "物流合作商",
                                    "batches": len(batches), "datasets": result, "payroll_executed": False})
                        print(f"运单及问题单隔离验收已完成：{run / 'verification.json'}")
                    except Exception as exc:
                        atomic_json(run / "verification.json", {"status": "error", "failure": safe_operation_failure(exc),
                                    "control": collector.last_control, "payroll_executed": False,
                                    "error": str(exc) if isinstance(exc, BillCollectionError) else "采集或清洗未完成"})
                        try:
                            diagnostics = run / "diagnostics"
                            diagnostics.mkdir()
                            save_inspection(page, diagnostics, {}, [])
                        except Exception:
                            pass
                        print(f"运单验收失败记录：{run / 'verification.json'}")
                        raise
                finally:
                    browser.close()
        return 0
    except Exception as exc:
        print(str(exc) if isinstance(exc, BillCollectionError) else f"运单检查未完成：{type(exc).__name__}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
