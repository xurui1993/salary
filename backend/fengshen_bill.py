"""Fengshen bill-page adapter; an observed DOM/API profile is required to export."""

import argparse
import calendar
from contextlib import contextmanager
from dataclasses import dataclass
import datetime
import hashlib
import json
import math
import os
from pathlib import Path
import queue
import re
import tempfile
import threading
import time
from atomic_files import atomic_replace
from urllib.parse import parse_qs, urlparse
import uuid
import zipfile


BILL_URL = "https://aeolus.ele.me/?targetId=58668#/bill/download"
RIDER_BILL_URL = "https://aeolus.ele.me/?targetId=58484#/salary-bill-ub"
WAYBILL_URL = "https://aeolus.ele.me/?targetId=55220#/delivery/data"
INSPECTION_URLS = {"agency_daily": BILL_URL, "rider_monthly": RIDER_BILL_URL, "waybill_fraud": WAYBILL_URL}
DAILY_CREATE_URL = "https://freyja.ele.me/api/freyja/hq/offline/bill/create"
DAILY_QUERY_URL = "https://freyja.ele.me/api/freyja/offline/bill/query"
DAILY_DOWNLOAD_URL = "https://freyja.ele.me/api/freyja/bill/export/download"
MONTHLY_QUERY_URL = "https://httpizza.ele.me/xtop/xtop.lpd.price.mng.zsSalaryBillQueryFs.pageQuerySalaryBill/1.0"
MONTHLY_EXPORT_URL = "https://httpizza.ele.me/xtop/xtop.lpd.price.mng.zsSalaryBillQuery.exportKnightSalaryBill/1.0"
PROJECT_ROOT = Path(__file__).resolve().parent.parent
DAILY_SUB_BILL_NAMES = {1: "配送费", 2: "违规扣款"}
DAILY_SUB_BILL_CONTROLS = {1: "sub_bill_delivery", 2: "sub_bill_penalty"}


class BillCollectionError(RuntimeError):
    pass


class CityPopupNotClosed(BillCollectionError):
    pass


class AuthenticationRequired(BillCollectionError):
    pass


@dataclass(frozen=True)
class BillRequest:
    start: str
    end: str
    all_agencies: bool = True
    all_sub_bills: bool = True
    agency_id: str = None
    sub_bill_types: tuple[int, ...] = (1, 2)

    def __post_init__(self):
        for value in (self.start, self.end):
            if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
                raise ValueError("日期必须为 YYYY-MM-DD")
            datetime.date.fromisoformat(value)
        if self.start > self.end:
            raise ValueError("开始日期不能晚于结束日期")
        if self.all_agencies != self.all_sub_bills:
            raise ValueError("不能混用旧全选和目标城市选择")
        if not self.all_agencies and not re.fullmatch(r"\d{1,20}", str(self.agency_id or "")):
            raise ValueError("目标城市下载必须指定固定代理商编号")
        if (not isinstance(self.sub_bill_types, tuple) or not self.sub_bill_types
                or any(type(value) is not int or value not in DAILY_SUB_BILL_NAMES for value in self.sub_bill_types)
                or len(set(self.sub_bill_types)) != len(self.sub_bill_types)):
            raise ValueError("子账单必须选择配送费(1)、违规扣款(2)中的一项或两项，不能重复")
        if self.all_sub_bills and set(self.sub_bill_types) != set(DAILY_SUB_BILL_NAMES):
            raise ValueError("单项子账单下载必须使用目标城市模式")

    @property
    def sub_bill_names(self):
        return tuple(DAILY_SUB_BILL_NAMES[value] for value in sorted(self.sub_bill_types))


@dataclass(frozen=True)
class MonthlyBillRequest:
    month: str

    def __post_init__(self):
        if not re.fullmatch(r"\d{4}-\d{2}", self.month):
            raise ValueError("账单月份必须为 YYYY-MM")
        datetime.date.fromisoformat(self.month + "-01")

    @property
    def start(self):
        return self.month + "-01"

    @property
    def end(self):
        date = datetime.date.fromisoformat(self.start)
        return f"{self.month}-{calendar.monthrange(date.year, date.month)[1]:02d}"


def validate_profile(profile, *, acceptance_only=False):
    if not isinstance(profile, dict) or (profile.get("verified") is not True and not acceptance_only):
        raise BillCollectionError("页面配置尚未核对；请先使用 --inspect 采集控件结构并验证配置")
    dataset = profile.get("dataset", "agency_daily")
    if dataset not in ("agency_daily", "rider_monthly"):
        raise BillCollectionError("未知账单类型")
    mode = profile.get("export_mode", "task")
    if mode not in ("task", "direct") or (dataset == "agency_daily" and mode != "task"):
        raise BillCollectionError("导出模式必须根据真实页面核对")
    identity = profile.get("task_identity_mode", "response_id")
    if identity not in ("response_id", "list_delta") or (identity == "list_delta" and dataset != "agency_daily"):
        raise BillCollectionError("未知任务识别方式")
    required = ["submit_button", "agency_context"]
    if not re.fullmatch(r"\d{1,20}", str(profile.get("expected_agency_id", ""))):
        raise BillCollectionError("需要明确当前授权代理商编号，避免新浏览器默认切换到其他代理商")
    selection = profile.get("selection_mode", "all")
    if selection not in ("all", "target_city"):
        raise BillCollectionError("未知代理商选择模式")
    if selection == "target_city":
        required += ["city_trigger", "city_popup", "city_group", "city_group_label", "city_option", "city_selected_option"]
        for key in ("city_option", "city_selected_option"):
            if profile.get(key, "").count("{agency_id}") != 1:
                raise BillCollectionError("物流合作商城市及选中项必须按固定代理商编号定位")
    if dataset == "agency_daily":
        required += [
            "start_input", "end_input", "agency_trigger", "agency_popup",
            "sub_bill_trigger", "sub_bill_popup",
            "bill_type_selected", "bill_cycle_selected",
        ]
        if selection == "all":
            required += ["agency_select_all", "sub_bill_select_all"]
        else:
            required += ["agency_clear", "agency_option", "agency_selected_ids",
                         "sub_bill_clear", "sub_bill_delivery", "sub_bill_penalty", "sub_bill_selected_labels"]
            if "{agency_id}" not in profile.get("agency_option", ""):
                raise BillCollectionError("关联代理商必须按目标城市固定编号定位")
    else:
        required += ["month_input", "reset_button", "query_button", "period_label", "all_status_tab"]
    if mode == "task":
        required += ["task_status", "task_download"]
        required += (["task_rows", "task_title", "task_operation_time"] if identity == "list_delta" else ["task_row"])
    for key in required:
        if not isinstance(profile.get(key), str) or not profile[key].strip():
            raise BillCollectionError(f"页面配置缺少 {key}；不能猜测控件或默认下载第一条记录")
    if mode == "task" and identity == "response_id" and profile["task_row"].count("{task_id}") != 1:
        raise BillCollectionError("task_row 必须按本次 task_id 唯一定位任务")
    endpoints = ["export_response_url"] if mode == "task" else []
    scope_mode = profile.get("request_scope_mode")
    if scope_mode is not None and (scope_mode != "all_city_riders" or dataset != "rider_monthly"):
        raise BillCollectionError("未知月账单请求范围校验模式")
    if scope_mode == "all_city_riders":
        if (profile.get("export_response_url") != MONTHLY_EXPORT_URL
                or profile.get("query_response_url") != MONTHLY_QUERY_URL
                or profile.get("query_http_method", "POST") != "POST" or mode != "direct"
                or profile.get("query_month_format", "%Y-%m") not in ("%Y-%m", "%Y%m")):
            raise BillCollectionError("月账单全城市范围必须使用已观察的查询及导出接口")
        endpoints += ["export_response_url"]
    if dataset == "rider_monthly":
        endpoints += ["query_response_url"]
        path = profile.get("query_month_path")
        if not isinstance(path, list) or not path or any(not isinstance(key, str) or not key for key in path):
            raise BillCollectionError("query_month_path 必须配置实际月份字段，不能只依赖页面标题")
        if profile.get("query_http_method", "POST") not in ("GET", "POST"):
            raise BillCollectionError("月份查询仅支持已观察的 GET 或 POST 接口")
    for key in endpoints:
        endpoint = urlparse(profile.get(key, ""))
        observed_daily = identity == "list_delta" and key == "export_response_url" and profile.get(key) == DAILY_CREATE_URL
        if (endpoint.scheme != "https" or (endpoint.hostname != "httpizza.ele.me" and not observed_daily)
                or endpoint.username or endpoint.password or endpoint.query or endpoint.fragment
                or endpoint.port not in (None, 443) or not endpoint.path.startswith("/")):
            raise BillCollectionError(f"{key} 必须为实际观察到的官方 HTTPS 接口地址（不含查询参数）")
    if mode == "task":
        if identity == "list_delta":
            if selection != "target_city" or profile.get("task_query_url") != DAILY_QUERY_URL or profile.get("task_download_url") != DAILY_DOWNLOAD_URL:
                raise BillCollectionError("列表增量模式仅适用于已观察的目标城市日账单接口")
            if profile.get("export_response_url") != DAILY_CREATE_URL:
                raise BillCollectionError("列表增量模式创建接口与真实记录不符")
        else:
            path = profile.get("export_task_id_path")
            if not isinstance(path, list) or not path or any(not isinstance(key, str) or not key for key in path):
                raise BillCollectionError("export_task_id_path 必须为真实响应中的字段路径数组")
        for key in ("success_status", "failure_status"):
            values = profile.get(key)
            if not isinstance(values, list) or not values or any(not isinstance(value, str) or not value for value in values):
                raise BillCollectionError(f"页面配置缺少有效的 {key}")
        if set(profile["success_status"]) & set(profile["failure_status"]):
            raise BillCollectionError("任务成功和失败状态不能重叠")
        mappings = profile.get("task_api_status_labels", {})
        if not isinstance(mappings, dict):
            raise BillCollectionError("任务接口状态映射必须是对象")
        for name, mapping in mappings.items():
            if (not isinstance(name, str) or not name or not isinstance(mapping, dict)
                    or set(mapping) != {"code", "label"} or isinstance(mapping["code"], bool)
                    or not isinstance(mapping["code"], int)
                    or mapping["label"] not in profile["success_status"] + profile["failure_status"]):
                raise BillCollectionError("任务接口状态映射缺少已核对的编号或网页状态")
    kind = profile.get("date_input_mode", "text")
    if kind not in ("text", "calendar"):
        raise BillCollectionError("date_input_mode 只支持 text 或 calendar")
    if kind == "calendar":
        cell_key = "calendar_day" if dataset == "agency_daily" else "calendar_month"
        placeholder = "{date}" if dataset == "agency_daily" else "{month}"
        for key in ("calendar_popup", cell_key):
            if not isinstance(profile.get(key), str) or not profile[key]:
                raise BillCollectionError(f"日历模式缺少 {key}")
        if placeholder not in profile[cell_key]:
            raise BillCollectionError(f"{cell_key} 必须包含完整日期占位符 {placeholder}")
    if profile.get("selection_widget", "checkbox") not in ("checkbox", "treeselect"):
        raise BillCollectionError("未知多选控件类型")
    if profile.get("selection_widget") == "treeselect":
        for prefix in ("agency", "sub_bill"):
            for suffix in ("menu", "input"):
                if dataset == "agency_daily" and not profile.get(prefix + "_" + suffix):
                    raise BillCollectionError(f"树形多选控件缺少 {prefix}_{suffix}")
    if profile.get("date_commit_key", "Tab") not in ("Tab", "Enter"):
        raise BillCollectionError("日期提交键只支持 Tab 或 Enter")
    if "content_frame" in profile:
        if not isinstance(profile["content_frame"], str) or not profile["content_frame"].strip():
            raise BillCollectionError("内嵌页面选择器不能为空")
    return profile


def login_rejection(payload):
    if not isinstance(payload, dict):
        return False
    for envelope in (payload, payload.get("result")):
        if not isinstance(envelope, dict):
            continue
        rejected = (envelope.get("success") is False or envelope.get("error")
                    or envelope.get("name") == "BIZ_ERROR"
                    or (envelope.get("code") is not None and str(envelope["code"]) not in ("0", "200")))
        messages = [envelope.get("message"), envelope.get("msg")]
        if isinstance(envelope.get("error"), dict):
            messages.append(envelope["error"].get("message"))
        if rejected and any(isinstance(text, str) and re.search(r"未登录|登录(?:已)?(?:失效|过期)|请先登录", text) for text in messages):
            return True
    return False


def check_response_payload(payload):
    if not isinstance(payload, dict):
        raise BillCollectionError("导出接口未返回 JSON 对象")
    if login_rejection(payload):
        raise AuthenticationRequired("平台明确提示登录已失效")
    for envelope in (payload, payload.get("result")):
        if isinstance(envelope, dict) and (
            envelope.get("success") is False or envelope.get("error")
            or envelope.get("name") == "BIZ_ERROR"
            or (envelope.get("code") is not None and str(envelope["code"]) not in ("0", "200"))
        ):
            raise BillCollectionError("平台拒绝导出，请检查登录状态和账单权限")


def nested_value(payload, field_path):
    value = payload
    for key in field_path:
        if not isinstance(value, dict) or key not in value:
            raise BillCollectionError("接口缺少配置的字段，请核对真实接口结构")
        value = value[key]
    return value


def display_width(value):
    """Approximate Excel display width: CJK/fullwidth characters count as 2."""
    text = "" if value is None else str(value)
    return sum(2 if ord(char) > 127 else 1 for char in text)


def column_width(longest):
    """自适应列宽：内容最长显示宽度加 2 边距，限制在 [6, 60]。"""
    return min(max(longest + 2, 6), 60)


def response_task_id(payload, field_path):
    check_response_payload(payload)
    value = nested_value(payload, field_path)
    if isinstance(value, bool) or not isinstance(value, (str, int)):
        raise BillCollectionError("导出任务 ID 类型不正确")
    task_id = str(value)
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", task_id):
        raise BillCollectionError("导出任务 ID 格式不正确")
    return task_id


def daily_export_scope(payload, request):
    if not isinstance(payload, dict) or request.all_agencies or request.all_sub_bills:
        raise BillCollectionError("日账单请求范围无法核对")
    if (payload.get("startDate") != request.start or payload.get("endDate") != request.end
            or payload.get("agentIds") != [int(request.agency_id)]
            or any(isinstance(value, bool) or not isinstance(value, int) for value in payload.get("agentIds", []))
            or not isinstance(payload.get("subBillTypes"), list)
            or len(payload["subBillTypes"]) != len(request.sub_bill_types)
            or any(isinstance(value, bool) or not isinstance(value, int) for value in payload["subBillTypes"])
            or set(payload["subBillTypes"]) != set(request.sub_bill_types)
            or any(isinstance(payload.get(key), bool) or not isinstance(payload.get(key), int) for key in ("periodType", "billType"))
            or payload.get("periodType") != 0 or payload.get("billType") != 1):
        raise BillCollectionError("实际导出请求与目标城市、日期或所选子账单不一致，已停止")


def daily_create_matches(url, agency_id):
    parsed = urlparse(url)
    if f"{parsed.scheme}://{parsed.netloc}{parsed.path}" != DAILY_CREATE_URL or parsed.fragment:
        return False
    query = parse_qs(parsed.query, keep_blank_values=True)
    return not query or query == {"agentId": [str(agency_id)]}


def daily_query_scope(url, agency_id):
    parsed = urlparse(url)
    if f"{parsed.scheme}://{parsed.netloc}{parsed.path}" != DAILY_QUERY_URL:
        raise BillCollectionError("账单列表接口与记录不符")
    query = parse_qs(parsed.query)
    if query.get("agentId") != [str(agency_id)] or any(len(query.get(key, [])) != 1 for key in ("page", "size")):
        raise BillCollectionError("账单列表不是唯一目标城市范围")
    try:
        page, size = int(query["page"][0]), int(query["size"][0])
    except ValueError:
        raise BillCollectionError("账单列表分页格式异常") from None
    if page not in (0, 1) or not 1 <= size <= 1000:
        raise BillCollectionError("必须在账单任务列表第一页核对新任务")
    return page, size, str(agency_id)


def daily_tasks(payload):
    if login_rejection(payload):
        raise AuthenticationRequired("账单列表登录已失效")
    if (not isinstance(payload, dict) or not isinstance(payload.get("data"), list)
            or isinstance(payload.get("total"), bool) or not isinstance(payload.get("total"), int)
            or payload["total"] < len(payload["data"])):
        raise BillCollectionError("账单任务列表结构与真实记录不符")
    tasks = []
    if payload["total"] and not payload["data"]:
        raise BillCollectionError("任务列表总数非零但第一页为空，不能建立历史任务基线")
    for item in payload["data"]:
        if (not isinstance(item, dict) or isinstance(item.get("id"), bool) or not isinstance(item.get("id"), int)
                or item["id"] <= 0 or "agentId" not in item or not isinstance(item.get("title"), str)
                or not isinstance(item.get("statusName"), str)
                or isinstance(item.get("operationDate"), bool) or not isinstance(item.get("operationDate"), int)):
            raise BillCollectionError("账单任务标识、状态或操作时间异常")
        timestamp = item["operationDate"]
        timestamp = timestamp / 1000 if timestamp >= 100_000_000_000 else timestamp
        if not 1_262_304_000 <= timestamp <= 7_258_118_400:
            raise BillCollectionError("账单任务时间不是有效的秒或毫秒时间戳")
        tasks.append({**item, "operation_timestamp": timestamp})
    ids = [task["id"] for task in tasks]
    # The official list is ordered by operationDate. IDs can be out of order
    # within the same timestamp, so only require unique IDs and time ordering.
    times = [task["operation_timestamp"] for task in tasks]
    if len(ids) != len(set(ids)) or times != sorted(times, reverse=True):
        raise BillCollectionError("任务列表编号不唯一或操作时间不是倒序，不能推断本次新任务")
    return tasks


def new_daily_task(baseline, current, request, started, finished):
    previous = {task["id"] for task in baseline}
    added = [task for task in current if task["id"] not in previous]
    if not added:
        return None
    if len(added) != 1:
        raise BillCollectionError("同时出现多个新账单任务，无法唯一确认本次导出")
    task = added[0]
    title = "总部账单-代理商账单-" + request.start[5:] + "-" + request.end[5:]
    if (task["id"] <= max(previous, default=0) or task["title"] != title
            or not started - 5 <= task["operation_timestamp"] <= finished + 5):
        raise BillCollectionError("新增任务不是本次提交的日期及时间范围，未下载历史账单")
    if task.get("agentId") not in (None, int(request.agency_id)):
        raise BillCollectionError("新增任务代理商编号与目标城市不符")
    return task


def daily_download_matches(url, task_id, agency_id):
    parsed = urlparse(url)
    query = parse_qs(parsed.query)
    return (f"{parsed.scheme}://{parsed.netloc}{parsed.path}" == DAILY_DOWNLOAD_URL
            and query.get("id") == [str(task_id)] and query.get("agentId") == [str(agency_id)])


def monthly_export_scope(payload, request, month_format="%Y-%m"):
    try:
        body = payload["params"]["request"]
    except (KeyError, TypeError):
        raise BillCollectionError("月账单请求结构无法核对") from None
    expected = datetime.date.fromisoformat(request.start).strftime(month_format)
    fields = {"bizType", "billCycle", "teamIds", "settleStatusList", "pageNum", "pageSize"}
    if (not isinstance(body, dict) or set(body) != fields or body.get("billCycle") != expected
            or body.get("teamIds") is not None or body.get("settleStatusList") != []
            or any(isinstance(body.get(key), bool) or not isinstance(body.get(key), int) for key in ("bizType", "pageNum", "pageSize"))):
        raise BillCollectionError("月账单必须是目标月份、全部站点和全部状态，不能附加骑手筛选")


def schema_only(value, depth=0):
    """Keep shape, never values (including signed links, tokens and bill amounts)."""
    if depth >= 5:
        return type(value).__name__
    if isinstance(value, dict):
        return {key: schema_only(item, depth + 1) for key, item in list(value.items())[:60]}
    if isinstance(value, list):
        return [schema_only(value[0], depth + 1)] if value else []
    return type(value).__name__


def atomic_json(path, data):
    path = Path(path)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent,
                                         suffix=".json.part", delete=False) as output:
            temporary = Path(output.name)
            json.dump(data, output, ensure_ascii=False, indent=2)
        atomic_replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def validate_bill_file(path, max_bytes=200 * 1024 * 1024):
    path = Path(path)
    size = path.stat().st_size
    if size == 0 or size > max_bytes:
        raise BillCollectionError("下载文件为空或超过大小限制")
    if not zipfile.is_zipfile(path):
        raise BillCollectionError("账单下载未返回有效 XLSX 或 ZIP；可能返回登录页面")
    try:
        with zipfile.ZipFile(path) as archive:
            entries = archive.infolist()
            if not entries or len(entries) > 10000 or any(entry.flag_bits & 1 for entry in entries):
                raise BillCollectionError("账单压缩文件为空、加密或条目数量异常")
            if sum(entry.file_size for entry in entries) > max_bytes * 5:
                raise BillCollectionError("账单压缩文件解压大小超过限制")
            if archive.testzip() is not None:
                raise BillCollectionError("账单压缩文件校验失败")
            names = {entry.filename for entry in entries}
            xlsx = {"[Content_Types].xml", "xl/workbook.xml"}.issubset(names)
            if not xlsx and not any(name.lower().endswith((".xlsx", ".xls", ".csv")) for name in names):
                raise BillCollectionError("ZIP 中没有账单数据文件")
    except zipfile.BadZipFile:
        raise BillCollectionError("账单压缩文件损坏") from None
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(65536), b""):
            digest.update(chunk)
    return {"bytes": size, "sha256": digest.hexdigest(), "format": "xlsx" if xlsx else "zip"}


class BillPageCollector:
    page_url = BILL_URL
    profile_validator = staticmethod(validate_profile)

    def __init__(self, page, profile, output_dir, log=print, timeout=900, poll_interval=4, auth=None, acceptance_only=False):
        self.page = page
        self.profile = self.profile_validator(profile, acceptance_only=acceptance_only)
        self.acceptance_only = bool(acceptance_only)
        self.last_control = "initializing"
        self.failure_diagnostics = None
        self.output_dir = Path(output_dir)
        self.log = log
        self.timeout = float(timeout)
        self.poll_interval = float(poll_interval)
        self.auth = auth
        if not all(math.isfinite(value) and value > 0 for value in (self.timeout, self.poll_interval)):
            raise ValueError("超时和轮询间隔必须为正数")

    @staticmethod
    def _one(locator, description):
        count = locator.count()
        if count != 1:
            raise BillCollectionError(f"{description}应唯一匹配，实际为 {count} 个；需核对页面配置")
        if not locator.is_visible():
            raise BillCollectionError(f"{description}不可见，请检查登录状态和页面")
        return locator

    def _control(self, key, root=None):
        self.last_control = key
        if root is None:
            root = self.page if key in ("agency_context", "city_trigger", "city_popup") else self._content()
        locator = root.locator(self.profile[key])
        if locator.count() == 0:
            locator.wait_for(state="visible", timeout=30000)
        return self._one(locator, key)

    def _content(self):
        selector = self.profile.get("content_frame")
        if not selector:
            return self.page
        frame = self.page.locator(selector)
        frame.wait_for(state="visible", timeout=30000)
        self._one(frame, "风神账单内嵌页面")
        return self.page.frame_locator(selector)

    @staticmethod
    def _value_or_text(control):
        try:
            value = control.input_value().strip()
            if value:
                return value
        except Exception:
            pass
        return control.inner_text().strip()

    def _check_agency_context(self):
        self._dismiss_notice()
        context = self._control("agency_context")
        text = self._value_or_text(context)
        agency_id = str(self.profile["expected_agency_id"])
        def matches(value):
            return bool(re.search(r"(?<!\d)" + re.escape(agency_id) + r"(?!\d)", value))
        if self.profile.get("selection_mode") != "target_city":
            if matches(text):
                return
            raise BillCollectionError("当前代理商与指定范围不一致，请人工确认授权代理商，不自动切换")
        self._control("city_trigger").click()
        popup = self._control("city_popup")
        group = self._logistics_partner_group(popup)
        option = self._one(group.locator(self.profile["city_option"].replace("{agency_id}", agency_id)), "物流合作商城市")
        if not matches(self._value_or_text(option)):
            raise BillCollectionError("物流合作商城市选项编号不符，已停止")
        if matches(text) and self._city_selected(group, agency_id):
            self._record_city_proof("selected_before_close", agency_id)
            self._close_city_popup(popup)
            self._restore_report_after_city(agency_id)
            return
        if not option.is_enabled():
            raise BillCollectionError("目标物流合作商城市不可选择，请核对城市权限；不会改选物流服务商")
        option.click()
        if self.profile.get("city_confirm") and popup.is_visible():
            self._control("city_confirm", self.page).click()
            self._wait_city_popup_closed(popup)
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            context = self._control("agency_context")
            if matches(self._value_or_text(context)):
                if not popup.is_visible():
                    self._control("city_trigger").click()
                    popup = self._control("city_popup")
                group = self._logistics_partner_group(popup)
                if self._city_selected(group, agency_id):
                    self._record_city_proof("selected_before_close", agency_id)
                    self._close_city_popup(popup)
                    self._restore_report_after_city(agency_id)
                    self.log(f"[城市] 已核对物流合作商分组下的目标城市：{agency_id}")
                    return
            self.page.wait_for_timeout(200)
        raise BillCollectionError("物流合作商城市切换或分组选中状态未确认，已停止；不使用物流服务商城市")

    def _record_city_proof(self, phase, agency_id):
        if self.acceptance_only:
            diagnostics = self.output_dir.with_name(self.output_dir.name + "-diagnostics")
            diagnostics.mkdir(parents=True, exist_ok=True)
            atomic_json(diagnostics / f"city_{agency_id}_{phase}.json", {
                "acceptance_only": True, "expected_agency_id": agency_id,
                "header_ids": re.findall(r"\[(\d+)\]", self._value_or_text(self._control("agency_context"))),
                "groups": inspect_city_groups(self.page),
            })

    def _dismiss_notice(self):
        notice_selector = self.profile.get("notice_dismiss_button")
        if notice_selector:
            notices = self.page.locator(notice_selector)
            if notices.count():
                notice = self._one(notices, "普通引导关闭按钮")
                if notice.inner_text().strip() != "知道了":
                    raise BillCollectionError("普通引导关闭按钮文字不符，未点击")
                notice.click()

    def _logistics_partner_group(self, popup):
        group = self._control("city_group", popup)
        label = self._control("city_group_label", group)
        if self._value_or_text(label) != "物流合作商":
            raise BillCollectionError("城市分组必须是物流合作商，不能使用物流服务商或其他分组")
        if re.search(r"(?:^|\n)\s*(?:物流服务商|总商)\s*(?:\n|$)", group.inner_text()):
            raise BillCollectionError("城市分组定位包含其他分组，必须仅限定物流合作商")
        return group

    def _city_selected(self, group, agency_id):
        selector = self.profile["city_selected_option"].replace("{agency_id}", agency_id)
        selected = group.locator(selector)
        if selected.count() == 0:
            return False
        selected = self._one(selected, "物流合作商分组内选中的城市")
        if not re.search(r"(?<!\d)" + re.escape(agency_id) + r"(?!\d)", self._value_or_text(selected)):
            raise BillCollectionError("物流合作商分组选中城市编号不符，已停止")
        return True

    def _close_city_popup(self, popup):
        self._dismiss_notice()
        for attempt in range(3):
            if not popup.is_visible():
                return
            if self.profile.get("city_close") and attempt != 1:
                self._control("city_close", self.page).click()
            else:
                popup.press("Escape")
            try:
                self._wait_city_popup_closed(popup)
                return
            except CityPopupNotClosed:
                if attempt == 2:
                    raise
                self.log("[页面恢复] 城市面板尚未关闭，正在重新关闭；未确认切换或提交导出")

    def _wait_city_popup_closed(self, popup):
        deadline = time.monotonic() + 5
        while popup.is_visible():
            if time.monotonic() >= deadline:
                raise CityPopupNotClosed("城市选择面板未关闭，已停止")
            self.page.wait_for_timeout(100)

    def _restore_report_after_city(self, agency_id):
        parsed = urlparse(self.page.url)
        if parsed.hostname == "mozi-login.alibaba-inc.com":
            raise AuthenticationRequired("城市切换后需要重新登录")
        if parsed.scheme != "https" or parsed.hostname != "aeolus.ele.me":
            raise BillCollectionError("城市切换后离开风神页面，已停止")
        if parsed.fragment != urlparse(self.page_url).fragment:
            self.page.goto(self.page_url, wait_until="domcontentloaded", timeout=60000)
        deadline = time.monotonic() + 30
        stable = 0
        restored = parsed.fragment != urlparse(self.page_url).fragment
        while True:
            parsed = urlparse(self.page.url)
            if parsed.hostname == "mozi-login.alibaba-inc.com":
                raise AuthenticationRequired("城市切换后需要重新登录")
            if parsed.scheme != "https" or parsed.hostname != "aeolus.ele.me":
                raise BillCollectionError("城市切换后离开风神页面，已停止")
            if parsed.fragment != urlparse(self.page_url).fragment and not restored:
                self.page.goto(self.page_url, wait_until="domcontentloaded", timeout=60000)
                restored = True
                stable = 0
                continue
            header = self.page.locator(self.profile["agency_context"])
            count = header.count()
            if count > 1:
                raise BillCollectionError("切换后目标城市匹配不唯一，已停止")
            matched = (count == 1 and header.is_visible()
                       and re.search(r"(?<!\d)" + re.escape(agency_id) + r"(?!\d)", self._value_or_text(header))
                       and parsed.fragment == urlparse(self.page_url).fragment)
            stable = stable + 1 if matched else 0
            if stable >= 2:
                break
            if time.monotonic() >= deadline:
                self._record_city_proof("incorrect_after_close", agency_id)
                raise BillCollectionError("返回报表后目标城市编号发生变化，已停止")
            self.page.wait_for_timeout(200)
        self._record_city_proof("confirmed_after_close", agency_id)

    def _calendar_target(self, popup, selector, target, monthly=False):
        for _ in range(120):
            cell = popup.locator(selector)
            if cell.count() == 1 and cell.is_visible():
                return cell
            if cell.count() > 1:
                raise BillCollectionError("日历目标匹配多个日期，需核对控件配置")
            if not all(self.profile.get(key) for key in ("calendar_heading", "calendar_previous", "calendar_next")):
                raise BillCollectionError("目标日期不在当前日历中，需要真实月份/年份导航控件配置")
            heading = self._control("calendar_heading", popup)
            before = heading.inner_text().strip()
            default_format = "%Y" if monthly else "%Y-%m"
            try:
                displayed = datetime.datetime.strptime(before, self.profile.get("calendar_heading_format", default_format))
            except ValueError:
                raise BillCollectionError("日历年月标题格式无法识别") from None
            delta = target.year - displayed.year
            if not monthly:
                delta = delta * 12 + target.month - displayed.month
            if delta == 0:
                raise BillCollectionError("日历年月正确但找不到目标日期，需核对完整日期选择器")
            self._control("calendar_next" if delta > 0 else "calendar_previous", popup).click()
            deadline = time.monotonic() + 5
            while heading.inner_text().strip() == before:
                if time.monotonic() >= deadline:
                    raise BillCollectionError("日历年月切换未生效")
                self.page.wait_for_timeout(100)
        raise BillCollectionError("日历导航超过限制，已停止")

    def _set_date(self, key, value):
        control = self._control(key)
        if self.profile.get("date_input_mode", "text") == "text":
            if control.get_attribute("readonly") is not None:
                raise BillCollectionError("日期输入框为只读，需根据真实日历配置 calendar 模式")
            control.fill(value)
            control.press(self.profile.get("date_commit_key", "Tab"))
        else:
            control.click()
            popup = self._control("calendar_popup")
            selector = self.profile["calendar_day"].replace("{date}", value)
            self._calendar_target(popup, selector, datetime.date.fromisoformat(value)).click()
        expected = datetime.date.fromisoformat(value).strftime(self.profile.get("date_display_format", "%Y-%m-%d"))
        if control.input_value().strip() != expected:
            raise BillCollectionError("网页日期未正确应用，已停止提交")

    def _select_all(self, prefix):
        self._control(prefix + "_trigger").click()
        popup = self._control(prefix + "_popup")
        checkbox = self._control(prefix + "_select_all", popup)
        if not checkbox.is_enabled():
            raise BillCollectionError(f"{prefix} 全选不可用")
        checkbox.set_checked(True)
        if not checkbox.is_checked():
            raise BillCollectionError(f"{prefix} 全选未生效")
        popup.press("Escape")
        if popup.is_visible():
            close_key = prefix + "_close"
            if not self.profile.get(close_key):
                raise BillCollectionError(f"{prefix} 选项面板未关闭，需配置关闭控件")
            self._control(close_key, popup).click()

    def _select_target(self, prefix, request):
        if self.profile.get("selection_widget") == "treeselect":
            return self._select_tree_target(prefix, request)
        self._control(prefix + "_trigger").click()
        popup = self._control(prefix + "_popup")
        self._control(prefix + "_clear", popup).click()
        if prefix == "agency":
            selector = self.profile["agency_option"].replace("{agency_id}", request.agency_id)
            self._one(popup.locator(selector), "目标城市关联代理商").set_checked(True)
            values = popup.locator(self.profile["agency_selected_ids"]).evaluate_all(
                "(nodes, attr) => nodes.map(n => attr ? n.getAttribute(attr) : n.textContent.trim())",
                self.profile.get("agency_selected_id_attribute"),
            )
            if values != [request.agency_id]:
                raise BillCollectionError("关联代理商选择结果不是唯一目标城市")
        else:
            for key in (DAILY_SUB_BILL_CONTROLS[value] for value in sorted(request.sub_bill_types)):
                self._control(key, popup).set_checked(True)
            values = popup.locator(self.profile["sub_bill_selected_labels"]).all_text_contents()
            if set(value.strip() for value in values) != set(request.sub_bill_names):
                raise BillCollectionError("子账单选择结果与本次请求不一致")
            if len(values) != len(request.sub_bill_types):
                raise BillCollectionError("子账单选择数量异常")
        popup.press("Escape")
        if popup.is_visible():
            key = prefix + "_close"
            if not self.profile.get(key):
                raise BillCollectionError("选择面板未关闭，需核对真实关闭控件")
            self._control(key, popup).click()

    def _select_tree_target(self, prefix, request):
        self._control(prefix + "_trigger").click()
        tree = self._control(prefix + "_popup")
        clear = tree.locator(self.profile[prefix + "_clear"])
        if clear.count() > 1:
            raise BillCollectionError("多选清空控件匹配不唯一")
        if clear.count() == 1 and clear.is_visible():
            clear.click()
        self._control(prefix + "_input", tree).fill("")
        keys = (("agency_option",) if prefix == "agency" else
                tuple(DAILY_SUB_BILL_CONTROLS[value] for value in sorted(request.sub_bill_types)))
        for key in keys:
            selector = self.profile[key].replace("{agency_id}", request.agency_id)
            option = tree.locator(selector)
            option.wait_for(state="visible", timeout=30000)
            self._one(option, key).click()
        selected_key = "agency_selected_ids" if prefix == "agency" else "sub_bill_selected_labels"
        values = [text.strip() for text in tree.locator(self.profile[selected_key]).all_text_contents()]
        if prefix == "agency":
            ids = [re.match(r"^(\d+)(?:-|$)", text) for text in values]
            if len(ids) != 1 or ids[0] is None or ids[0].group(1) != request.agency_id:
                raise BillCollectionError("关联代理商选择结果不是唯一目标城市")
        elif len(values) != len(request.sub_bill_types) or set(values) != set(request.sub_bill_names):
            raise BillCollectionError("子账单选择结果与本次请求不一致")
        self._control(prefix + "_input", tree).press("Escape")
        menu = tree.locator(self.profile[prefix + "_menu"])
        deadline = time.monotonic() + 5
        while menu.is_visible():
            if time.monotonic() >= deadline:
                raise BillCollectionError("树形多选面板未关闭，已停止")
            self.page.wait_for_timeout(100)

    def apply_request(self, request):
        if not isinstance(request, BillRequest) or self.profile.get("dataset", "agency_daily") != "agency_daily":
            raise BillCollectionError("代理商日账单必须使用日期范围和对应页面配置")
        if urlparse(self.page.url).hostname != "aeolus.ele.me" or not self.page.url.endswith("#/bill/download"):
            raise BillCollectionError("当前不在风神账单下载页面，请完成正常登录")
        self._check_agency_context()
        targeted = self.profile.get("selection_mode") == "target_city"
        if targeted != (not request.all_agencies) or (targeted and request.agency_id != str(self.profile["expected_agency_id"])):
            raise BillCollectionError("采集请求与代理商选择模式不一致")
        if targeted:
            self._select_target("agency", request)
        else:
            self._select_all("agency")
        if self._value_or_text(self._control("bill_type_selected")) != "代理商账单":
            raise BillCollectionError("当前账单类型不是代理商账单，已停止")
        if self._value_or_text(self._control("bill_cycle_selected")) != "日账单":
            raise BillCollectionError("当前账单周期不是日账单，已停止")
        if self.profile.get("date_input_mode", "text") == "text" and self.profile.get("date_commit_key") == "Enter":
            for key, value in (("start_input", request.start), ("end_input", request.end)):
                control = self._control(key)
                if control.get_attribute("readonly") is not None:
                    raise BillCollectionError("日期输入框只读，需核对日历控件")
                control.fill(value)
            self._control("end_input").press("Enter")
        else:
            self._set_date("start_input", request.start)
            self._set_date("end_input", request.end)
        if targeted:
            self._select_target("sub_bill", request)
        else:
            self._select_all("sub_bill")
        # A range-picker may overwrite its start when the end is entered.
        for key, value in (("start_input", request.start), ("end_input", request.end)):
            expected = datetime.date.fromisoformat(value).strftime(self.profile.get("date_display_format", "%Y-%m-%d"))
            if self._control(key).input_value().strip() != expected:
                raise BillCollectionError("账单日期在选择过程中发生变化，已停止提交")

    def _save_download(self, download, request, suffix="direct"):
        if download.failure():
            raise BillCollectionError("浏览器账单下载失败")
        temporary = self.output_dir / "bill.download.part"
        try:
            download.save_as(str(temporary))
            info = validate_bill_file(temporary)
            path = self.output_dir / f"bill_{request.start}_{request.end}_{suffix}.{info['format']}"
            atomic_replace(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)
        return {"path": path.name, **info}

    def _click_export(self):
        self._control("submit_button").click()
        if self.profile.get("export_confirm_button"):
            self._control("export_confirm_button").click()

    @contextmanager
    def _bill_download_capture(self):
        context = self.page.context
        watched, downloads = {}, []
        def watch(page):
            if page in watched:
                return
            def record(download):
                downloads.append(download)
            watched[page] = record
            page.on("download", record)
        context.on("page", watch)
        for page in context.pages:
            watch(page)
        def wait(file_url):
            deadline = time.monotonic() + 60
            while time.monotonic() < deadline:
                matching = [item for item in downloads if item.url == file_url]
                if len(matching) > 1:
                    raise BillCollectionError("本次导出产生多个相同地址的文件，已停止")
                if matching:
                    return matching[0]
                self.page.wait_for_timeout(100)
            raise BillCollectionError("未收到与本次账单导出地址一致的浏览器下载，未保存其他文件")
        try:
            yield wait
        finally:
            context.remove_listener("page", watch)
            for page, record in watched.items():
                page.remove_listener("download", record)

    def _collect_monthly_direct(self, request):
        checked = {"matched": False, "blocked": False}
        def guard(route):
            try:
                if route.request.url != MONTHLY_EXPORT_URL or route.request.method != "POST":
                    raise BillCollectionError("月账单导出接口不符")
                monthly_export_scope(route.request.post_data_json, request, self.profile.get("query_month_format", "%Y-%m"))
            except Exception:
                checked["blocked"] = True
                route.abort()
            else:
                checked["matched"] = True
                route.continue_()
        pattern = MONTHLY_EXPORT_URL + "**"
        self.page.route(pattern, guard)
        try:
            try:
                with self._bill_download_capture() as wait_download:
                    with self.page.expect_response(lambda response: response.url == MONTHLY_EXPORT_URL
                                                   and response.request.method == "POST", timeout=60000) as pending:
                        self._click_export()
                    response = pending.value
                    if response.status == 401:
                        raise AuthenticationRequired("月账单导出登录已失效")
                    if response.status != 200:
                        raise BillCollectionError("月账单导出接口失败")
                    payload = response.json()
                    check_response_payload(payload)
                    if nested_value(payload, ["result", "data", "validRes"]) is not True:
                        raise BillCollectionError("月账单导出未被平台确认有效")
                    file_url = nested_value(payload, ["result", "data", "fileUrl"])
                    if not isinstance(file_url, str):
                        raise BillCollectionError("月账单导出缺少有效文件地址")
                    parsed = urlparse(file_url)
                    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password or parsed.fragment:
                        raise BillCollectionError("月账单导出文件地址不是有效 HTTPS 地址")
                    if self.acceptance_only:
                        diagnostics = self.output_dir.with_name(self.output_dir.name + "-diagnostics")
                        diagnostics.mkdir(parents=True, exist_ok=True)
                        atomic_json(diagnostics / "monthly_export.json", {
                            "http_status": response.status, "valid_response": True,
                            "file_origin": f"https://{parsed.hostname}", "full_scope_checked": checked["matched"],
                        })
                    download = wait_download(file_url)
            except Exception:
                if checked["blocked"]:
                    raise BillCollectionError("月账单实际导出范围不符，已阻止提交") from None
                raise
            if checked["blocked"]:
                raise BillCollectionError("月账单实际导出范围不符，已阻止提交")
            if not checked["matched"]:
                raise BillCollectionError("月账单未经过实际请求范围校验，未保存")
            return self._save_download(download, request)
        finally:
            self.page.unroute(pattern, guard)

    def _read_daily_list(self):
        def is_list(response):
            parsed = urlparse(response.url)
            return (f"{parsed.scheme}://{parsed.netloc}{parsed.path}" == DAILY_QUERY_URL
                    and response.request.method == "GET")
        with self.page.expect_response(is_list, timeout=60000) as pending:
            self.page.reload(wait_until="domcontentloaded", timeout=60000)
        response = pending.value
        if response.status == 401:
            raise AuthenticationRequired("账单列表登录已失效")
        if response.status != 200:
            raise BillCollectionError("账单列表查询失败")
        scope = daily_query_scope(response.url, self.profile["expected_agency_id"])
        try:
            tasks = daily_tasks(response.json())
        except ValueError:
            raise BillCollectionError("账单列表未返回有效 JSON") from None
        return scope, tasks

    def _daily_task_row(self, task):
        rows = self._content().locator(self.profile["task_rows"])
        matches = []
        candidates = []
        operation_time = datetime.datetime.fromtimestamp(task["operation_timestamp"]).strftime("%Y-%m-%d %H:%M:%S")
        if rows.count() > 1000:
            raise BillCollectionError("账单任务行数超出检查限制")
        for index in range(rows.count()):
            row = rows.nth(index)
            if not row.is_visible():
                continue
            title = self._control("task_title", row).inner_text().strip()
            actual_time = self._control("task_operation_time", row).inner_text().strip()
            if title == task["title"] and re.fullmatch(r"\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2}", actual_time):
                candidates.append(actual_time)
            if title == task["title"] and actual_time == operation_time:
                matches.append(row)
        if self.acceptance_only:
            diagnostics = self.output_dir.with_name(self.output_dir.name + "-diagnostics")
            diagnostics.mkdir(parents=True, exist_ok=True)
            atomic_json(diagnostics / "daily_row_match.json", {
                "task_id": str(task["id"]), "expected_operation_time": operation_time,
                "candidate_operation_times": candidates, "matching_rows": len(matches),
                "platform_status": task["statusName"] if re.fullmatch(r"[A-Za-z\u4e00-\u9fff _-]{1,24}", task["statusName"]) else "unknown",
                "platform_status_code": task["status"] if isinstance(task["status"], int) else None,
            })
        if len(matches) > 1:
            raise BillCollectionError("本次任务标题和时间对应多行，未点击下载")
        return matches[0] if matches else None

    def _download_daily_task(self, task, request):
        row = self._daily_task_row(task)
        if row is None:
            return None
        status = self._control("task_status", row).inner_text().strip()
        if self.acceptance_only:
            diagnostics = self.output_dir.with_name(self.output_dir.name + "-diagnostics")
            atomic_json(diagnostics / "daily_task_status.json", {
                "task_id": str(task["id"]), "row_status": status if status in self.profile["success_status"] + self.profile["failure_status"] else "unknown",
            })
        if status in self.profile["failure_status"]:
            raise BillCollectionError("平台账单导出失败")
        api_label = task["statusName"]
        mapping = self.profile.get("task_api_status_labels", {}).get(api_label)
        if mapping is not None:
            if task["status"] != mapping["code"] or isinstance(task["status"], bool):
                raise BillCollectionError("本次任务接口状态码与已观察状态名称不一致")
            api_label = mapping["label"]
        if status != api_label:
            return None
        if status not in self.profile["success_status"]:
            return None
        checked = {"matched": False, "blocked": False}
        def guard(route):
            if (route.request.method == "GET"
                    and daily_download_matches(route.request.url, task["id"], request.agency_id)):
                checked["matched"] = True
                route.continue_()
            else:
                checked["blocked"] = True
                route.abort()
        pattern = DAILY_DOWNLOAD_URL + "**"
        self.page.route(pattern, guard)
        try:
            try:
                with self._bill_download_capture() as wait_download:
                    def is_file(response):
                        parsed = urlparse(response.url)
                        return f"{parsed.scheme}://{parsed.netloc}{parsed.path}" == DAILY_DOWNLOAD_URL and response.request.method == "GET"
                    with self.page.expect_response(is_file, timeout=60000) as pending:
                        self._control("task_download", row).click()
                    if checked["blocked"] or not checked["matched"]:
                        raise BillCollectionError("文件下载未经过本次任务编号校验，未保存账单")
                    response = pending.value
                    if response.status == 401:
                        raise AuthenticationRequired("本次账单下载登录已失效")
                    if response.status != 200:
                        raise BillCollectionError("本次账单下载接口失败")
                    file_url = response.json()
                    if not isinstance(file_url, str):
                        raise BillCollectionError("本次账单下载未返回已观察的文件地址")
                    parsed = urlparse(file_url)
                    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password or parsed.fragment:
                        raise BillCollectionError("本次账单文件地址不是有效 HTTPS 地址")
                    download = wait_download(file_url)
            except Exception:
                if checked["blocked"]:
                    raise BillCollectionError("下载请求编号不是本次新任务，已阻止下载且未保存账单") from None
                raise
            if checked["blocked"] or not checked["matched"]:
                raise BillCollectionError("文件下载未经过本次任务编号校验，未保存账单")
            return self._save_download(download, request, str(task["id"]))
        finally:
            self.page.unroute(pattern, guard)

    def resume_daily_acceptance(self, request):
        if not self.acceptance_only or self.profile.get("dataset") != "agency_daily":
            raise BillCollectionError("仅隔离验收可以继续已确认的日账单任务")
        manifest_path = self.output_dir / "manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if (manifest.get("acceptance_only") is not True or manifest.get("payroll_executed") is not False
                or manifest.get("production_profile_enabled") is not False or manifest.get("status") == "success"
                or manifest.get("dataset") != "agency_daily" or manifest.get("merchant_group") != "物流合作商"
                or manifest.get("agency_id") != request.agency_id or manifest.get("start") != request.start
                or manifest.get("end") != request.end or manifest.get("sub_bill_scope") != list(request.sub_bill_names)
                or not re.fullmatch(r"[1-9]\d*", str(manifest.get("task_id", "")))):
            raise BillCollectionError("待继续的验收任务范围或已确认编号不符")
        created = datetime.datetime.fromisoformat(manifest["created_at"]).timestamp()
        self._check_agency_context()
        manifest["status"] = "resuming_existing_task"
        atomic_json(manifest_path, manifest)
        self.log("[继续] 仅下载已确认任务，不创建新的导出任务")
        deadline = time.monotonic() + self.timeout
        while time.monotonic() < deadline:
            _, tasks = self._read_daily_list()
            found = [task for task in tasks if str(task["id"]) == manifest["task_id"]]
            if len(found) != 1:
                raise BillCollectionError("已确认任务不在目标城市列表，未改选其他任务")
            task = found[0]
            title = f"总部账单-代理商账单-{request.start[5:]}-{request.end[5:]}"
            if task["title"] != title or task["agentId"] not in (None, int(request.agency_id), request.agency_id) or not created - 5 <= task["operation_timestamp"] <= created + 300:
                raise BillCollectionError("已确认任务标题、城市或原始提交时间不符")
            file = self._download_daily_task(task, request)
            if file is not None:
                manifest.update(files=[file], status="success", resumed_without_submission=True)
                atomic_json(manifest_path, manifest)
                self.log(f"[完成] 原任务已下载并校验：{self.output_dir}")
                return manifest
            self.page.wait_for_timeout(self.poll_interval * 1000)
        raise BillCollectionError("继续本次账单任务等待超时，未创建新任务")

    def _submit_daily_delta(self, request):
        retries = 0
        while True:
            try:
                if self.auth:
                    self.auth()
                self.apply_request(request)
                scope, baseline = self._read_daily_list()
                # Reload supplies a fresh baseline but clears the form; reapply and recheck it.
                self.apply_request(request)
                break
            except Exception as exc:
                if isinstance(exc, CityPopupNotClosed) and retries < 2:
                    retries += 1
                    self.page.goto(self.page_url, wait_until="domcontentloaded", timeout=60000)
                    continue
                if not self.auth or retries >= 2:
                    raise
                restored = self.auth(force=True) if isinstance(exc, AuthenticationRequired) else self.auth()
                if not restored:
                    raise
                retries += 1
        checked = {"matched": False, "error": None}
        def guard(route):
            try:
                if self.acceptance_only:
                    parsed = urlparse(route.request.url)
                    diagnostics = self.output_dir.with_name(self.output_dir.name + "-diagnostics")
                    diagnostics.mkdir(parents=True, exist_ok=True)
                    atomic_json(diagnostics / "daily_create_endpoint.json", {
                        "method": route.request.method, "origin": f"{parsed.scheme}://{parsed.hostname}",
                        "path": parsed.path, "query_keys": sorted(parse_qs(parsed.query)),
                    })
                if not daily_create_matches(route.request.url, request.agency_id) or route.request.method != "POST":
                    raise BillCollectionError("创建任务接口或请求方式不符")
                payload = route.request.post_data_json
                if self.acceptance_only and isinstance(payload, dict):
                    safe = {key: value for key, value in payload.items() if key in ("periodType", "billType")
                            and isinstance(value, int) and not isinstance(value, bool)}
                    for key in ("agentIds", "subBillTypes"):
                        values = payload.get(key)
                        if isinstance(values, list) and len(values) <= 10 and all(isinstance(v, int) and not isinstance(v, bool) for v in values):
                            safe[key] = values
                    for key in ("startDate", "endDate"):
                        value = payload.get(key)
                        if isinstance(value, str) and re.fullmatch(r"\d{4}(?:-?\d{2}){2}(?:[ T]\d{2}:\d{2}:\d{2}(?:\.\d{1,3})?(?:Z|[+-]\d{2}:\d{2})?)?", value):
                            safe[key] = value
                    diagnostics = self.output_dir.with_name(self.output_dir.name + "-diagnostics")
                    diagnostics.mkdir(parents=True, exist_ok=True)
                    atomic_json(diagnostics / "daily_create_scope.json", {"business_scope": safe, "schema": schema_only(payload)})
                daily_export_scope(payload, request)
            except Exception:
                checked["error"] = "实际导出请求范围不符，已阻止提交"
                route.abort()
            else:
                checked["matched"] = True
                route.continue_()
        def is_create(response):
            return daily_create_matches(response.url, request.agency_id) and response.request.method == "POST"
        started = time.time()
        pattern = DAILY_CREATE_URL + "**"
        self.page.route(pattern, guard)
        try:
            self.log("[账单] 已记录目标城市历史任务，仅识别本次新增任务")
            try:
                with self.page.expect_response(is_create, timeout=60000) as pending:
                    self._click_export()
                response = pending.value
            except Exception:
                if checked["error"]:
                    raise BillCollectionError(checked["error"]) from None
                raise
            if not checked["matched"] or checked["error"]:
                raise BillCollectionError("未确认实际创建请求范围，已停止")
            if response.status == 401:
                raise AuthenticationRequired("创建任务接口明确拒绝登录，需验证后继续")
            if response.status != 200:
                raise BillCollectionError("创建账单任务接口失败，未重复提交")
            try:
                payload = response.json()
            except ValueError:
                payload = None
            if payload is not None:
                check_response_payload(payload)
        finally:
            self.page.unroute(pattern, guard)
        finished = time.time()
        return scope, baseline, started, finished

    def _collect_daily_delta(self, request, manifest, manifest_path):
        for attempt in range(3):
            try:
                scope, baseline, started, finished = self._submit_daily_delta(request)
                break
            except AuthenticationRequired:
                if not self.auth or attempt == 2:
                    raise BillCollectionError("创建前登录反复失效，已停止核算") from None
                self.auth(force=True)
        manifest["task_identity_mode"] = "list_delta"
        manifest["status"] = "waiting_for_new_task"
        atomic_json(manifest_path, manifest)
        deadline = time.monotonic() + self.timeout
        task = None
        while time.monotonic() < deadline:
            try:
                if self.auth:
                    before = time.monotonic()
                    restored = self.auth()
                    deadline += time.monotonic() - before
                    if restored:
                        self._check_agency_context()
                current_scope, current = self._read_daily_list()
                if current_scope != scope:
                    raise BillCollectionError("任务列表分页或城市范围发生变化，已停止")
                if task is None:
                    task = new_daily_task(baseline, current, request, started, finished)
                    if task is not None:
                        manifest["task_id"] = str(task["id"])
                        atomic_json(manifest_path, manifest)
                else:
                    found = [item for item in current if item["id"] == task["id"]]
                    if not found:
                        raise BillCollectionError("已确认的新任务不在当前列表，未改选历史任务")
                    if any(found[0][key] != task[key] for key in ("title", "operationDate", "agentId")):
                        raise BillCollectionError("本次新任务标识发生变化，已停止")
                    task = found[0]
                if task is not None:
                    file = self._download_daily_task(task, request)
                    if file is not None:
                        manifest.update({"files": [file], "status": "success"})
                        atomic_json(manifest_path, manifest)
                        self.log(f"[完成] 本次新任务已下载并校验：{self.output_dir}")
                        return manifest
            except Exception as exc:
                if not self.auth:
                    raise
                before = time.monotonic()
                restored = self.auth(force=True) if isinstance(exc, AuthenticationRequired) else self.auth()
                deadline += time.monotonic() - before
                if not restored:
                    raise
                self._check_agency_context()
                # Submission already happened, even if the ID is not yet known. Never resubmit.
                continue
            remaining = deadline - time.monotonic()
            if remaining > 0:
                self.page.wait_for_timeout(min(self.poll_interval, remaining) * 1000)
        raise BillCollectionError("未唯一确认或等到本次新账单任务完成，不下载旧记录")

    def collect(self, request):
        self.output_dir.mkdir(parents=True, exist_ok=False)
        manifest = {
            "platform": "fengshen", "page": self.page_url,
            "dataset": self.profile.get("dataset", "agency_daily"),
            "agency_id": str(self.profile["expected_agency_id"]),
            "start": request.start, "end": request.end,
            "status": "running", "created_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "files": [],
        }
        if self.acceptance_only:
            manifest.update({"acceptance_only": True, "payroll_executed": False,
                             "production_profile_enabled": False})
        if self.profile.get("selection_mode") == "target_city":
            manifest["merchant_group"] = "物流合作商"
        if isinstance(request, MonthlyBillRequest):
            manifest.update({"month": request.month, "station_scope": "all_in_current_agency",
                             "bill_status": "all", "snapshot_only": True})
        else:
            manifest.update({"agency_scope": "target_city" if not request.all_agencies else "all_authorized",
                             "sub_bill_scope": list(request.sub_bill_names) if not request.all_sub_bills else "all_available"})
        manifest_path = self.output_dir / "manifest.json"
        atomic_json(manifest_path, manifest)
        try:
            if self.profile.get("task_identity_mode") == "list_delta":
                return self._collect_daily_delta(request, manifest, manifest_path)
            retries = 0
            while True:
                try:
                    if self.auth:
                        self.auth()
                    try:
                        self.apply_request(request)
                    except Exception as exc:
                        if isinstance(exc, CityPopupNotClosed) and retries < 2:
                            retries += 1
                            self.page.goto(self.page_url, wait_until="domcontentloaded", timeout=60000)
                            continue
                        if not self.auth or not self.auth() or retries >= 2:
                            raise
                        retries += 1
                        continue
                    if self.auth and self.auth():
                        if retries >= 2:
                            raise BillCollectionError("登录重复失效，已停止核算")
                        retries += 1
                        continue
                    if self.profile.get("export_mode", "task") == "direct":
                        if self.profile.get("request_scope_mode") == "all_city_riders":
                            file = self._collect_monthly_direct(request)
                        else:
                            with self.page.expect_download(timeout=60000) as pending_download:
                                self._click_export()
                            file = self._save_download(pending_download.value, request)
                        manifest["files"] = [file]
                        manifest["status"] = "success"
                        atomic_json(manifest_path, manifest)
                        self.log(f"[完成] 风神骑手月度 UB 账单已下载并校验：{self.output_dir}")
                        return manifest
                    endpoint = self.profile["export_response_url"]
                    def is_export(response):
                        parsed = urlparse(response.url)
                        actual = f"{parsed.scheme}://{parsed.netloc}{parsed.path}"
                        return actual == endpoint and response.request.method == "POST"
                    self.log("[账单] 日期、代理商和子账单范围已核对，提交导出")
                    with self.page.expect_response(is_export, timeout=60000) as pending:
                        self._click_export()
                    response = pending.value
                    if response.status == 401:
                        raise AuthenticationRequired("风神登录已失效")
                    if response.status == 403:
                        raise BillCollectionError("当前账号无账单导出权限，未触发短信登录")
                    if response.status != 200:
                        raise BillCollectionError("账单导出接口 HTTP 失败")
                    try:
                        payload = response.json()
                    except ValueError:
                        raise BillCollectionError("导出接口返回非 JSON 内容") from None
                    task_id = response_task_id(payload, self.profile["export_task_id_path"])
                    break
                except AuthenticationRequired:
                    if not self.auth or retries >= 2:
                        raise BillCollectionError("登录重复失效，已停止核算，请检查账号状态") from None
                    retries += 1
                    self.auth(force=True)
            manifest["task_id"] = task_id
            atomic_json(manifest_path, manifest)
            row_selector = self.profile["task_row"].replace("{task_id}", task_id)
            deadline = time.monotonic() + self.timeout
            while time.monotonic() < deadline:
                if self.auth:
                    started = time.monotonic()
                    if self.auth():
                        self._check_agency_context()
                    deadline += time.monotonic() - started
                try:
                    rows = self._content().locator(row_selector)
                    if rows.count() > 1:
                        raise BillCollectionError("当前任务匹配多条账单，已停止")
                    if rows.count() == 1 and rows.is_visible():
                        status = self._control("task_status", rows).inner_text().strip()
                        if status in self.profile["failure_status"]:
                            raise BillCollectionError("平台账单导出失败")
                        if status in self.profile["success_status"]:
                            with self.page.expect_download(timeout=60000) as pending_download:
                                self._control("task_download", rows).click()
                            manifest["files"] = [self._save_download(pending_download.value, request, task_id)]
                            manifest["status"] = "success"
                            atomic_json(manifest_path, manifest)
                            self.log(f"[完成] 已下载并校验：{self.output_dir}")
                            return manifest
                except Exception:
                    started = time.monotonic()
                    if not self.auth or not self.auth():
                        raise
                    deadline += time.monotonic() - started
                    self._check_agency_context()
                    # A known export ID survives reauthentication; never submit another export here.
                    continue
                remaining = deadline - time.monotonic()
                if remaining > 0:
                    self.page.wait_for_timeout(min(self.poll_interval, remaining) * 1000)
                    if self.profile.get("reload_while_waiting") is True:
                        self.page.reload(wait_until="domcontentloaded", timeout=30000)
            raise BillCollectionError("等待本次账单导出超时，不下载列表中的旧记录")
        except Exception as exc:
            manifest["status"] = "error"
            self.failure_diagnostics = {"control": self.last_control, **safe_operation_failure(exc)}
            manifest["failure"] = self.failure_diagnostics
            # Playwright exception messages can contain URLs and response payloads.
            manifest["error"] = str(exc) if isinstance(exc, BillCollectionError) else (
                f"账单页面操作异常（控件 {self.last_control}，{type(exc).__name__}），核算已停止；请查看本次 manifest.json"
            )
            atomic_json(manifest_path, manifest)
            if urlparse(self.page.url).hostname == "aeolus.ele.me":
                try:
                    diagnostics = self.output_dir / "failure_diagnostics"
                    diagnostics.mkdir(exist_ok=True)
                    save_inspection(self.page, diagnostics, {}, [])
                except Exception:
                    pass
            if isinstance(exc, BillCollectionError):
                raise
            raise BillCollectionError(manifest["error"]) from None


class MonthlyBillPageCollector(BillPageCollector):
    page_url = RIDER_BILL_URL

    def apply_request(self, request):
        if not isinstance(request, MonthlyBillRequest) or self.profile.get("dataset") != "rider_monthly":
            raise BillCollectionError("月账单必须使用对应的月份和页面配置")
        if urlparse(self.page.url).hostname != "aeolus.ele.me" or not self.page.url.endswith("#/salary-bill-ub"):
            raise BillCollectionError("当前不在骑手薪资账单页")
        self._check_agency_context()
        self._control("reset_button").click()
        control = self._control("month_input")
        if self.profile.get("date_input_mode", "text") == "text":
            if control.get_attribute("readonly") is not None:
                raise BillCollectionError("账单月份只读，需配置真实月份日历控件")
            control.fill(request.month)
            control.press(self.profile.get("date_commit_key", "Tab"))
        else:
            control.click()
            popup = self._control("calendar_popup")
            selector = self.profile["calendar_month"].replace("{month}", request.month)
            self._calendar_target(popup, selector, datetime.date.fromisoformat(request.start), monthly=True).click()
        if control.input_value().strip() != request.month:
            raise BillCollectionError("账单月份未应用，已停止")
        self._control("all_status_tab").click()
        endpoint = self.profile["query_response_url"]
        expected = datetime.date.fromisoformat(request.start).strftime(self.profile.get("query_month_format", "%Y-%m"))
        def is_query(response):
            parsed = urlparse(response.url)
            method = self.profile.get("query_http_method", "POST")
            if f"{parsed.scheme}://{parsed.netloc}{parsed.path}" != endpoint or response.request.method != method:
                return False
            try:
                if method == "GET":
                    payload = {key: values[0] for key, values in parse_qs(parsed.query).items() if len(values) == 1}
                else:
                    payload = response.request.post_data_json
                return str(nested_value(payload, self.profile["query_month_path"])) == expected
            except (BillCollectionError, ValueError):
                return False
        with self.page.expect_response(is_query, timeout=60000) as pending:
            self._control("query_button").click()
        if self.profile.get("request_scope_mode") == "all_city_riders":
            monthly_export_scope(pending.value.request.post_data_json, request, self.profile.get("query_month_format", "%Y-%m"))
        if pending.value.status == 401:
            raise AuthenticationRequired("骑手账单查询时登录已失效")
        if pending.value.status != 200:
            raise BillCollectionError("骑手账单查询失败，已停止导出")
        check_response_payload(pending.value.json())
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            text = self._control("period_label").inner_text()
            dates = re.findall(r"\d{4}-\d{2}-\d{2}", text)
            if dates == [request.start, request.end]:
                if self._control("month_input").input_value().strip() != request.month:
                    raise BillCollectionError("查询期间账单月份发生变化")
                self.log(f"[月份] 页面账单周期已核对为 {request.start} 至 {request.end}")
                return
            self.page.wait_for_timeout(200)
        raise BillCollectionError("页面账单周期与所选月份不一致，已停止导出")


def browser_prompt(page, message, reader=input, timeout=1800, clock=time.monotonic):
    """Keep browser events flowing while the user finishes a manual inspection."""
    completed = queue.Queue(maxsize=1)
    def read():
        try:
            reader(message)
            completed.put(True)
        except Exception:
            completed.put(False)
    threading.Thread(target=read, name="inspection-console", daemon=True).start()
    deadline = clock() + timeout
    while clock() < deadline:
        try:
            if not completed.get_nowait():
                raise BillCollectionError("联调输入已结束，请重新启动检查")
            return page
        except queue.Empty:
            pass
        if page.is_closed():
            pages = [item for item in page.context.pages if not item.is_closed()
                     and urlparse(item.url).hostname in ("aeolus.ele.me", "mozi-login.alibaba-inc.com")]
            if not pages:
                raise BillCollectionError("联调浏览器已关闭，检查未完成")
            page = pages[-1]
        try:
            page.wait_for_timeout(200)
        except Exception:
            if not page.is_closed():
                raise
    raise BillCollectionError("联调等待超过 30 分钟，请重新启动检查")


def wait_for_inspection_download(page, downloads, expected_url, checkpoint,
                                 timeout=1800, clock=time.monotonic, alternate_url=None):
    if expected_url not in INSPECTION_URLS.values():
        raise BillCollectionError("自动检查仅支持已知风神账单页面")
    if alternate_url is not None and (alternate_url not in (BILL_URL, RIDER_BILL_URL) or alternate_url == expected_url):
        raise BillCollectionError("额外检查页面必须是另一张已知风神账单")
    expected_fragment = urlparse(expected_url).fragment
    alternate_fragment = urlparse(alternate_url).fragment if alternate_url else None
    alternate_dataset = "rider_monthly" if alternate_url == RIDER_BILL_URL else "agency_daily"
    deadline = clock() + timeout
    next_checkpoint = 0
    restored_report = False
    while clock() < deadline:
        if page.is_closed():
            pages = [item for item in page.context.pages if not item.is_closed()
                     and urlparse(item.url).hostname == "aeolus.ele.me"
                     and urlparse(item.url).fragment in (expected_fragment, alternate_fragment)]
            if len(pages) != 1:
                raise BillCollectionError("无法唯一确认目标账单页，联调浏览器可能已关闭")
            page = pages[0]
        parsed = urlparse(page.url)
        if parsed.scheme != "https" or parsed.hostname not in ("aeolus.ele.me", "mozi-login.alibaba-inc.com"):
            raise BillCollectionError("联调离开了风神官方页面，已停止")
        on_report = parsed.hostname == "aeolus.ele.me" and parsed.fragment == expected_fragment
        if any(item["status"] == "error" for item in downloads):
            raise BillCollectionError("原始账单下载未保存完成，未进入下一页")
        if downloads:
            alternate_saved = alternate_url and parsed.hostname == "aeolus.ele.me" and parsed.fragment == alternate_fragment and all(
                item.get("source_dataset") == alternate_dataset for item in downloads)
            if not ((on_report and all(item.get("source_is_target") for item in downloads)) or alternate_saved):
                raise BillCollectionError("下载来源不是目标账单页，需重新核对")
            checkpoint(page)
            return page
        if (parsed.hostname == "aeolus.ele.me" and "dashboard" in parsed.fragment
                and not restored_report):
            # SSO may return to the dashboard instead of the original report.
            restored_report = True
            page.goto(expected_url, wait_until="domcontentloaded", timeout=60000)
            continue
        if clock() >= next_checkpoint:
            checkpoint(page)
            next_checkpoint = clock() + 5
        page.wait_for_timeout(200)
    raise BillCollectionError("等待原始账单下载超过 30 分钟，检查未完成")


def wait_for_control_inspection(page, output_dir, schemas, expected_url, timeout=1800, clock=time.monotonic):
    if expected_url not in INSPECTION_URLS.values():
        raise BillCollectionError("控件观察仅支持已知风神账单页")
    stop = Path(output_dir) / "finish_inspection.flag"
    deadline, next_checkpoint = clock() + timeout, 0
    restored = False
    print(f"只读控件观察已开始，无需创建或下载账单。结束标记：{stop}")
    while clock() < deadline:
        if page.is_closed():
            raise BillCollectionError("控件观察窗口已关闭，检查未完成")
        parsed = urlparse(page.url)
        if parsed.scheme != "https" or parsed.hostname not in ("aeolus.ele.me", "mozi-login.alibaba-inc.com"):
            raise BillCollectionError("控件观察离开官方页面，已停止")
        if parsed.hostname == "aeolus.ele.me" and "dashboard" in parsed.fragment and not restored:
            restored = True
            page.goto(expected_url, wait_until="domcontentloaded", timeout=60000)
            continue
        if clock() >= next_checkpoint or stop.is_file():
            atomic_json(Path(output_dir) / "inspection_progress.json", {
                "inspection_only": True, "stage": "observing_controls", "response_schemas": schemas,
                "on_target_report": parsed.hostname == "aeolus.ele.me" and parsed.fragment == urlparse(expected_url).fragment,
            })
            if parsed.hostname == "aeolus.ele.me":
                try:
                    atomic_json(Path(output_dir) / "page_controls_progress.json", {
                        "inspection_only": True, "complete": False, "frames": inspect_page_structure(page),
                    })
                    groups = inspect_city_groups(page)
                    if groups:
                        atomic_json(Path(output_dir) / "city_selection.json", {"inspection_only": True, "groups": groups})
                except Exception as exc:
                    if not any(marker in str(exc) for marker in ("Execution context was destroyed", "Frame was detached", "Cannot find context")):
                        raise
            next_checkpoint = clock() + 5
        if stop.is_file():
            if parsed.hostname != "aeolus.ele.me" or parsed.fragment != urlparse(expected_url).fragment:
                raise BillCollectionError("控件观察未确认目标账单页，未启用配置")
            return page
        page.wait_for_timeout(200)
    raise BillCollectionError("控件观察超过 30 分钟，已保留中途记录")


def monthly_request_diagnostics(request):
    parsed = urlparse(request.url)
    if parsed.hostname != "httpizza.ele.me" or parsed.path not in (
            "/xtop/xtop.lpd.price.mng.zsSalaryBillQueryFs.pageQuerySalaryBill/1.0",
            "/xtop/xtop.lpd.price.mng.zsSalaryBillQuery.exportKnightSalaryBill/1.0"):
        return None
    try:
        body = request.post_data_json["params"]["request"]
        value = body["billCycle"]
        month_format = "%Y-%m" if isinstance(value, str) and re.fullmatch(r"\d{4}-\d{2}", value) else (
            "%Y%m" if isinstance(value, str) and re.fullmatch(r"\d{6}", value) else "unrecognized")
        return {"bill_cycle_format": month_format,
                "all_stations": "teamIds" in body and body["teamIds"] is None,
                "all_statuses": "settleStatusList" in body and body["settleStatusList"] == []}
    except (KeyError, TypeError, ValueError):
        return None


def waybill_request_diagnostics(request):
    parsed = urlparse(request.url)
    if parsed.hostname != "httpizza.ele.me" or "agencyTrackingFs" not in parsed.path:
        return None
    try:
        body = request.post_data_json["params"]["request"]
        if not isinstance(body, dict):
            return None
        # Only filter metadata is retained; rider identities and signed URLs are not.
        fields = {}
        for key, value in body.items():
            if re.search(r"tracking.*(?:Start|End)$", key) and isinstance(value, (int, float)) and not isinstance(value, bool):
                fields[key] = value
            elif re.search(r"fraud|cheat|bogus", key, re.I) and (value is None or isinstance(value, (bool, int))):
                fields[key] = value
        return {"time_and_fraud_filters": fields,
                "status_filters": {key: body[key] for key in ("trackingStateKey", "trackingLabelKey")
                    if isinstance(body.get(key), str) and re.fullmatch(r"[A-Za-z0-9_-]{1,32}", body[key])},
                "unrestricted_filters": [key for key, value in body.items() if value is None or value == "" or value == []]}
    except (KeyError, TypeError, ValueError):
        return None


def inspect_page(page, output_dir, prompt=None, navigate=None, finish_on_download=False, expected_url=None,
                 alternate_url=None, snapshot_only=False, observe_controls=False):
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=False)
    schemas = {}
    downloads = []
    context = page.context
    watched = {}
    def download_file(download, source_page):
        origin = source_page
        if expected_url and urlparse(origin.url).hostname != "aeolus.ele.me":
            opener = getattr(source_page, "opener", lambda: None)()
            if opener is not None:
                origin = opener
        source_is_target = bool(expected_url and urlparse(origin.url).scheme == "https" and urlparse(origin.url).hostname == "aeolus.ele.me"
            and urlparse(origin.url).fragment == urlparse(expected_url).fragment)
        source_dataset = None
        if urlparse(origin.url).scheme == "https" and urlparse(origin.url).hostname == "aeolus.ele.me":
            source_dataset = {urlparse(url).fragment: dataset for dataset, url in INSPECTION_URLS.items()}.get(urlparse(origin.url).fragment)
        suffix = Path(download.suggested_filename).suffix.lower()
        if suffix not in (".zip", ".xlsx", ".xls", ".csv"):
            downloads.append({"status": "error", "error": "下载文件类型无法识别"})
            return
        target = output_dir / "downloads" / ("sample_" + uuid.uuid4().hex + suffix)
        try:
            target.parent.mkdir(exist_ok=True)
            download.save_as(str(target))
            if not target.stat().st_size:
                raise BillCollectionError("下载文件为空")
            downloads.append({"status": "saved", "path": target.relative_to(output_dir).as_posix(),
                              "bytes": target.stat().st_size, "validated_for_payroll": False,
                              "source_is_target": source_is_target, "source_dataset": source_dataset})
        except Exception:
            downloads.append({"status": "error", "error": "原始下载未保存完成"})

    def watch(item):
        if item not in watched:
            handler = lambda download: download_file(download, item)
            watched[item] = handler
            item.on("download", handler)

    def observed_endpoint(request):
        parsed = urlparse(request.url)
        if (parsed.scheme != "https" or not (parsed.hostname or "").endswith(".ele.me")
                or parsed.username or parsed.password):
            return None
        if request.resource_type not in ("xhr", "fetch") and not (
                parsed.hostname == "freyja.ele.me" and parsed.path.startswith("/api/freyja/")):
            return None
        return parsed

    def request_structure(request, parsed):
        if request.method == "GET":
            request_shape = {key: "str" for key in parse_qs(parsed.query)}
        else:
            try:
                request_shape = schema_only(request.post_data_json)
            except Exception:
                request_shape = {key: "str" for key in parse_qs(parsed.query)}
        return request_shape

    def record_request(request):
        parsed = observed_endpoint(request)
        if parsed is None:
            return
        key = request.method + f" https://{parsed.netloc}{parsed.path}"
        if len(schemas) >= 200 and key not in schemas:
            return
        schemas[key] = {
            "request": request_structure(request, parsed), "response": None,
            "response_format": "pending_or_no_response", "http_status": None,
            "resource_type": request.resource_type,
        }
        diagnostics = monthly_request_diagnostics(request) or waybill_request_diagnostics(request)
        if diagnostics is not None:
            schemas[key]["scope_diagnostics"] = diagnostics

    def record(response):
        request = response.request
        parsed = observed_endpoint(request)
        if parsed is None:
            return
        key = request.method + f" https://{parsed.netloc}{parsed.path}"
        if len(schemas) >= 200 and key not in schemas:
            return
        try:
            payload, response_format = schema_only(response.json()), "json"
        except Exception:
            payload, response_format = None, "non_json"
        schemas[key] = {
            "request": request_structure(request, parsed), "response": payload,
            "response_format": response_format, "http_status": response.status,
            "resource_type": request.resource_type,
        }
        diagnostics = monthly_request_diagnostics(request) or waybill_request_diagnostics(request)
        if diagnostics is not None:
            schemas[key]["scope_diagnostics"] = diagnostics
    context.on("request", record_request)
    context.on("response", record)
    context.on("page", watch)
    for item in context.pages:
        watch(item)
    try:
        if navigate:
            navigate()
        message = "请在浏览器核对目标城市和周期，手动导出并点击下载；完成后在此按回车（勿关闭 Edge）："
        if observe_controls:
            page = wait_for_control_inspection(page, output_dir, schemas, expected_url)
        elif snapshot_only:
            page.wait_for_timeout(3000)
            if expected_url not in INSPECTION_URLS.values():
                raise BillCollectionError("只读检查必须指定已知账单页面")
            parsed = urlparse(page.url)
            if parsed.hostname == "aeolus.ele.me" and "dashboard" in parsed.fragment:
                page.goto(expected_url, wait_until="domcontentloaded", timeout=60000)
                page.wait_for_timeout(3000)
            parsed = urlparse(page.url)
            if parsed.hostname != "aeolus.ele.me" or parsed.fragment != urlparse(expected_url).fragment:
                raise BillCollectionError("只读检查未进入目标账单页；未保存可运行配置")
        elif finish_on_download:
            print("请只在本次打开的 Edge 中核对城市和周期、导出并点击下载；样本保存后自动进入下一页，无需回车。")
            def checkpoint(current):
                atomic_json(output_dir / "inspection_progress.json", {
                    "inspection_only": True, "stage": "sample_saved" if downloads else "waiting_for_download",
                    "on_target_report": urlparse(current.url).hostname == "aeolus.ele.me"
                        and urlparse(current.url).fragment == urlparse(expected_url).fragment,
                    "response_schemas": schemas, "downloads": downloads,
                })
                try:
                    groups = inspect_city_groups(current)
                    if groups:
                        atomic_json(output_dir / "city_selection.json", {"inspection_only": True, "groups": groups})
                    if urlparse(current.url).hostname == "aeolus.ele.me":
                        atomic_json(output_dir / "page_controls_progress.json", {
                            "inspection_only": True, "complete": False,
                            "frames": inspect_page_structure(current),
                        })
                except Exception as exc:
                    # A city switch can destroy the frame while its controls are read.
                    if not any(marker in str(exc) for marker in (
                        "Execution context was destroyed", "Frame was detached",
                        "Cannot find context with specified id",
                    )):
                        raise
            page = wait_for_inspection_download(page, downloads, expected_url, checkpoint, alternate_url=alternate_url)
        elif prompt:
            prompt(message)
        else:
            page = browser_prompt(page, message)
        if not page.is_closed():
            page.wait_for_timeout(200)
        if page.is_closed() or urlparse(page.url).hostname != "aeolus.ele.me":
            pages = [item for item in context.pages if not item.is_closed() and urlparse(item.url).hostname == "aeolus.ele.me"]
            if len(pages) != 1:
                raise BillCollectionError("无法唯一确认风神业务标签页，请保留一个目标账单页面")
            page = pages[0]
        return save_inspection(page, output_dir, schemas, downloads)
    except Exception as exc:
        failure_code = "inspection_stopped" if isinstance(exc, BillCollectionError) else {
            "TargetClosedError": "browser_closed", "TimeoutError": "browser_timeout",
        }.get(type(exc).__name__, "browser_operation_failed")
        atomic_json(output_dir / "inspection_error.json", {
            "inspection_only": True, "response_schemas": schemas, "downloads": downloads,
            "failure_code": failure_code,
            "error": "联调检查未完成，保留已观察的结构及原始下载；未启用自动核算",
        })
        if isinstance(exc, BillCollectionError):
            raise
        message = {
            "browser_closed": "联调浏览器已关闭，检查未完成；已保留中途记录",
            "browser_timeout": "联调网页操作超时，检查未完成；已保留中途记录",
            "browser_operation_failed": "联调网页操作失败，检查未完成；已保留脱敏记录",
        }[failure_code]
        raise BillCollectionError(message) from None
    finally:
        context.remove_listener("request", record_request)
        context.remove_listener("response", record)
        context.remove_listener("page", watch)
        for item, handler in watched.items():
            item.remove_listener("download", handler)


def inspect_city_groups(page):
    if urlparse(page.url).hostname != "aeolus.ele.me":
        return []
    return page.locator(".agency-wrapper").evaluate_all("""nodes => nodes.filter(el => el.getClientRects().length).map(el => ({
        class: el.className,
        label: ['总商', '物流合作商', '物流服务商'].includes(el.querySelector('p.title')?.textContent.trim())
            ? el.querySelector('p.title').textContent.trim() : '',
        options: Array.from(el.querySelectorAll('p.info')).map(p => ({
            agencyId: (p.textContent || '').match(/\\[(\\d+)\\]/)?.[1] || '',
            class: p.className, selected: p.classList.contains('active')
        }))
    }))""")


def safe_operation_failure(exc):
    text = str(exc)
    return {"exception_type": type(exc).__name__,
            "timeout_kind": ("response" if 'waiting for event "response"' in text else "download" if 'waiting for event "download"' in text
                             else "locator" if "Locator." in text else "other") if type(exc).__name__ == "TimeoutError" else None,
            "pointer_intercepted": "intercepts pointer events" in text,
            "target_closed": any(marker in text for marker in ("Target page, context or browser has been closed", "Target closed")),
            "navigation_interrupted": any(marker in text for marker in ("net::ERR_ABORTED", "interrupted by another navigation"))}


def inspect_page_structure(page):
    if urlparse(page.url).hostname != "aeolus.ele.me":
        raise BillCollectionError("尚未进入风神业务页面，无法检查控件")
    frames = []
    for frame in page.frames:
        parsed = urlparse(frame.url)
        if (parsed.scheme != "https" or not (parsed.hostname or "").endswith(".ele.me")
                or parsed.username or parsed.password):
            continue
        controls = frame.locator("input, button, a, select, iframe, [role=checkbox], [role=combobox], [role=listbox], [role=dialog], [role=tab], .vue-treeselect, .vue-treeselect__option, .vue-treeselect__x-container").evaluate_all(
            """nodes => nodes.filter(el => el.getClientRects().length).map(el => ({
            tag: el.tagName, type: el.getAttribute('type'), role: el.getAttribute('role'),
            id: el.id, class: el.className, placeholder: el.getAttribute('placeholder'),
            ariaLabel: el.getAttribute('aria-label'), readonly: el.hasAttribute('readonly'),
            businessValue: el.matches('input') && ['代理商账单', '日账单'].includes(el.value) ? el.value : null,
            optionId: el.matches('.vue-treeselect__option') ? el.getAttribute('data-id') : null,
            label: el.matches('button, a, [role=checkbox], [role=tab]') ? (el.textContent || '').trim().slice(0, 80)
                : el.matches('.vue-treeselect__option') ? (el.querySelector('.vue-treeselect__label')?.textContent || '').trim().slice(0, 80)
                : el.matches('input[type=checkbox], input[type=radio]') ? (el.closest('label')?.textContent || '').trim().slice(0, 80) : '',
            fieldLabel: (el.closest('.el-form-item, .ant-form-item')?.querySelector('.el-form-item__label, .ant-form-item-label label')?.textContent || '').trim().slice(0, 80),
            frameName: el.matches('iframe') ? el.getAttribute('name') : null,
            frameSource: el.matches('iframe[src]') ? ((url) => ({origin:url.origin, path:url.pathname}))(new URL(el.getAttribute('src'), location.href)) : null,
            parents: Array.from((function*(){ let p = el.parentElement; for (let i=0; p && i<3; i++, p=p.parentElement) yield p; })())
                .map(p => ({tag:p.tagName, id:p.id, class:p.className, role:p.getAttribute('role')}))
        }))"""
        )
        row_attributes = frame.locator("tr, [role=row]").evaluate_all(
            """nodes => nodes.filter(el => el.getClientRects().length).slice(0, 20).map(el => ({
            tag: el.tagName, class: el.className, attributeNames: Array.from(el.attributes).map(a => a.name)
        }))"""
        )
        calendar_controls = frame.locator(".ant-picker-dropdown button, .ant-picker-dropdown td[title]").evaluate_all(
            """nodes => nodes.filter(el => el.getClientRects().length).map(el => ({
            tag: el.tagName, class: el.className,
            title: /^\\d{4}(?:-\\d{2}(?:-\\d{2})?)?$/.test(el.getAttribute('title') || '') ? el.getAttribute('title') : null,
            ariaLabel: el.getAttribute('aria-label'),
            label: /^(?:\\d{4}年?|\\d{1,2}月?|[A-Za-z]{3,9}|[<>«»]+)$/.test(el.textContent.trim()) ? el.textContent.trim() : '',
            parents: [{tag:el.parentElement?.tagName, class:el.parentElement?.className}]
        }))"""
        )
        period_labels = frame.locator("div, span, p").evaluate_all(
            """nodes => nodes.filter(el => el.getClientRects().length && /^账单周期[：:]?\\s*\\d{4}-\\d{2}-\\d{2}\\s*至\\s*\\d{4}-\\d{2}-\\d{2}$/.test(el.textContent.trim())).slice(0, 5)
            .map(el => ({tag:el.tagName, id:el.id, class:el.className, text:el.textContent.trim()}))"""
        )
        table_columns = []
        if f"{parsed.scheme}://{parsed.netloc}{parsed.path}" == "https://freyja.ele.me/bill/download":
            table_columns = frame.locator(".el-table").evaluate_all("""nodes => nodes.filter(el => el.getClientRects().length).map(el => ({
                headers: Array.from(el.querySelectorAll('thead th')).map(th => ({
                    label: th.textContent.trim(), class:th.className
                })),
                cells: Array.from(el.querySelector('tr.el-table__row')?.children || []).map(td => ({
                    tag:td.tagName, class:td.className,
                    children:Array.from(td.children).map(child => ({tag:child.tagName,class:child.className})),
                    links:Array.from(td.querySelectorAll('a, button')).map(link => ({
                        tag:link.tagName, class:link.className,
                        label:link.textContent.trim() === '下载账单' ? '下载账单' : ''
                    }))
                })),
                taskRows:Array.from(el.querySelectorAll('tr.el-table__row')).slice(0, 20).map(tr => {
                    const cells = Array.from(tr.children).map(td => td.textContent.trim());
                    return {
                        title:/^总部账单-代理商账单-\\d{2}-\\d{2}-\\d{2}-\\d{2}$/.test(cells[1] || '') ? cells[1] : null,
                        operationTime:/^\\d{4}-\\d{2}-\\d{2} \\d{2}:\\d{2}:\\d{2}$/.test(cells[2] || '') ? cells[2] : null,
                        status:['成功','失败','处理中','正在生成','进行中','等待中'].includes(cells[3]) ? cells[3] : null
                    };
                })
            }))""")
        frames.append({"url": f"{parsed.scheme}://{parsed.netloc}{parsed.path}",
                       "controls": controls, "row_attributes": row_attributes,
                       "calendar_controls": calendar_controls, "period_labels": period_labels,
                       "table_columns": table_columns})
    return frames


def save_inspection(page, output_dir, schemas, downloads):
    atomic_json(output_dir / "page_controls.json", {
        "frames": inspect_page_structure(page), "response_schemas": schemas, "downloads": downloads,
        "inspection_only": True, "city_groups": inspect_city_groups(page),
        "frame_origins": sorted({f"https://{urlparse(frame.url).hostname}"
            for frame in page.frames if urlparse(frame.url).scheme == "https"}),
        "frame_inventory": [{"origin": f"https://{urlparse(frame.url).hostname}", "path": urlparse(frame.url).path}
            for frame in page.frames if urlparse(frame.url).scheme == "https"],
        "observed_dataset": {urlparse(url).fragment: dataset for dataset, url in INSPECTION_URLS.items()}.get(urlparse(page.url).fragment),
    })
    return output_dir / "page_controls.json"


def inspect_download_flow(page, run_dir, navigate):
    pending = {"agency_daily": BILL_URL, "rider_monthly": RIDER_BILL_URL}
    captures = {}
    while pending:
        dataset, url = next(iter(pending.items()))
        alternate_url = next((item for item in pending.values() if item != url), None)
        print("当前检查：" + dataset)
        output = inspect_page(page, run_dir / ("capture_" + str(len(captures) + 1)),
            navigate=lambda: navigate(url, page), finish_on_download=True, expected_url=url,
            alternate_url=alternate_url)
        with output.open(encoding="utf-8") as source:
            data = json.load(source)
        observed = data.get("observed_dataset")
        if observed not in pending or not data.get("downloads") or any(
                item.get("status") != "saved" or item.get("source_dataset") != observed for item in data["downloads"]):
            raise BillCollectionError("检查样本无法唯一归属到待核对账单，已停止")
        captures[observed] = output.relative_to(run_dir).as_posix()
        del pending[observed]
        atomic_json(run_dir / "inspection_flow.json", {
            "inspection_only": True, "complete": not pending, "validated_for_payroll": False,
            "captures": captures, "pending": list(pending),
        })
        print(f"控件检查已保存：{output}")
        if page.is_closed() and pending:
            live = [item for item in page.context.pages if not item.is_closed()
                    and urlparse(item.url).hostname == "aeolus.ele.me"
                    and urlparse(item.url).fragment in (urlparse(BILL_URL).fragment, urlparse(RIDER_BILL_URL).fragment)]
            if len(live) != 1:
                raise BillCollectionError("无法唯一确认下一步联调页面")
            page = live[0]


def main(argv=None):
    parser = argparse.ArgumentParser(description="风神账单下载：正常登录后自动选择日期、关联代理商和子账单")
    parser.add_argument("--inspect", action="store_true", help="只采集控件与响应字段结构，不自动提交导出")
    parser.add_argument("--inspect-flow", action="store_true", help="一次登录，分别检查代理商日账单与风神骑手月度 UB 账单")
    parser.add_argument("--reuse-session", action="store_true", help="联调时复用本机已保存的加密会话，不读取其他浏览器配置")
    parser.add_argument("--finish-on-download", action="store_true", help="仅联调检查：人工下载成功保存后自动进入下一页，无需控制台回车")
    parser.add_argument("--snapshot-only", action="store_true", help="仅单页只读检查：加载后保存页面结构，不提交导出或等待下载")
    parser.add_argument("--observe-controls", action="store_true", help="仅单页只读检查：持续记录人工展开的日历等控件，等待结束标记，无需重复下载")
    parser.add_argument("--acceptance", action="store_true", help="隔离验收：用候选配置自动下载到专用目录，不启用正式配置或核算")
    parser.add_argument("--switch-from", help="仅隔离验收：先切换至另一物流合作商编号，再由采集流程切回目标城市")
    parser.add_argument("--resume-run", type=Path, help="仅日账单隔离验收：继续此验收目录中已确认的任务，不重复创建")
    parser.add_argument("--profile", type=Path, help="经真实页面核对的 JSON 控件配置")
    parser.add_argument("--start", help="账单开始日期 YYYY-MM-DD")
    parser.add_argument("--end", help="账单结束日期 YYYY-MM-DD")
    parser.add_argument("--dataset", choices=tuple(INSPECTION_URLS), default="agency_daily")
    parser.add_argument("--month", help="骑手账单月份 YYYY-MM")
    parser.add_argument("--browser", choices=("msedge", "chrome", "chromium"), default="msedge")
    parser.add_argument("--output", type=Path, default=PROJECT_ROOT / "outputs" / "fengshen_bills")
    args = parser.parse_args(argv)
    try:
        if args.dataset == "waybill_fraud" and (not args.inspect or args.inspect_flow):
            raise BillCollectionError("运单欺诈单暂仅支持单页结构联调，尚未启用自动采集")
        if args.acceptance and (not args.reuse_session or args.inspect or args.inspect_flow
                                or args.finish_on_download or args.snapshot_only or args.observe_controls):
            raise BillCollectionError("隔离验收必须复用本机会话，不能与人工检查模式混用")
        if args.switch_from and not args.acceptance:
            raise BillCollectionError("--switch-from 仅用于隔离验收")
        if args.resume_run:
            resume = args.resume_run.resolve()
            if (not args.acceptance or args.dataset != "agency_daily" or args.switch_from
                    or resume.parent != (PROJECT_ROOT / "outputs" / "fengshen_acceptance").resolve()
                    or not re.fullmatch(r"[a-f0-9]{32}", resume.name)):
                raise BillCollectionError("--resume-run 仅允许继续固定隔离目录内的日账单任务，不能与起始城市切换混用")
        if args.reuse_session and not (args.inspect or args.inspect_flow or args.acceptance):
            raise BillCollectionError("--reuse-session 仅供联调检查；正式自动采集使用系统入口")
        if args.finish_on_download and not (args.inspect or args.inspect_flow):
            raise BillCollectionError("--finish-on-download 仅供联调检查，不启用自动核算")
        if args.snapshot_only and (not args.inspect or args.inspect_flow or args.finish_on_download):
            raise BillCollectionError("--snapshot-only 仅供单页只读 --inspect，不自动导出或核算")
        if args.observe_controls and (not args.inspect or args.inspect_flow or args.finish_on_download or args.snapshot_only):
            raise BillCollectionError("--observe-controls 仅供单页只读 --inspect，不能与下载或快照模式混用")
        request = profile = None
        if not (args.inspect or args.inspect_flow):
            if args.profile is None:
                raise BillCollectionError("采集需要经核对的 --profile；首次接入请先运行 --inspect")
            if args.dataset == "rider_monthly":
                if not args.month or args.start or args.end:
                    raise BillCollectionError("风神骑手月度 UB 账单仅使用 --month，不使用开始/结束日期")
                request = MonthlyBillRequest(args.month)
            else:
                if not args.start or not args.end or args.month:
                    raise BillCollectionError("代理商日账单需要 --start 和 --end，不使用 --month")
                request = BillRequest(args.start, args.end)
            with args.profile.open(encoding="utf-8") as source:
                profile = validate_profile(json.load(source), acceptance_only=args.acceptance)
            if profile.get("dataset", "agency_daily") != args.dataset:
                raise BillCollectionError("命令指定的账单类型与页面配置不一致")
            if args.dataset == "agency_daily" and profile.get("selection_mode") == "target_city":
                request = BillRequest(args.start, args.end, False, False, str(profile["expected_agency_id"]))
            if args.acceptance:
                with (Path(__file__).parent / "fengshen_cities.json").open(encoding="utf-8") as source:
                    agencies = {str(value) for value in json.load(source).values()}
                if profile.get("selection_mode") != "target_city" or str(profile["expected_agency_id"]) not in agencies:
                    raise BillCollectionError("隔离验收只能选择已配置的物流合作商城市")
                if args.switch_from and (args.switch_from not in agencies or args.switch_from == str(profile["expected_agency_id"])):
                    raise BillCollectionError("验收起始城市必须是另一已配置物流合作商")
                if (args.dataset == "agency_daily" and profile.get("task_identity_mode") != "list_delta") or (
                        args.dataset == "rider_monthly" and profile.get("request_scope_mode") != "all_city_riders"):
                    raise BillCollectionError("隔离验收必须启用实际请求和下载范围校验")
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            raise BillCollectionError("未安装采集依赖：python -m pip install -r backend/requirements-crawler.txt") from None
        with sync_playwright() as playwright:
            launch = {"headless": False}
            if args.browser != "chromium":
                launch["channel"] = args.browser
            browser = playwright.chromium.launch(**launch)
            try:
                if args.reuse_session:
                    from fengshen_auth import SessionVault
                    state = SessionVault().load()
                    if state is None:
                        raise BillCollectionError("尚未保存本机会话，请先在薪酬系统完成风神登录")
                    context = browser.new_context(accept_downloads=True, storage_state=state)
                    state = None
                    print("已恢复本机加密会话；有效性由网页确认，不自动发送短信，不写回会话。")
                else:
                    context = browser.new_context(accept_downloads=True)
                page = context.new_page()
                def navigate(url, target=None):
                    target = target or page
                    try:
                        target.goto(url, wait_until="domcontentloaded", timeout=60000)
                    except Exception as exc:
                        interrupted = any(text in str(exc) for text in ("net::ERR_ABORTED", "interrupted by another navigation"))
                        if not interrupted or urlparse(target.url).hostname not in ("aeolus.ele.me", "mozi-login.alibaba-inc.com"):
                            raise
                run_dir = (PROJECT_ROOT / "outputs" / "fengshen_acceptance" if args.acceptance else args.output.resolve()) / uuid.uuid4().hex
                if args.resume_run:
                    run_dir = args.resume_run.resolve()
                if args.inspect_flow and args.finish_on_download:
                    inspect_download_flow(page, run_dir, navigate)
                elif args.inspect_flow:
                    for dataset, url in (("agency_daily", BILL_URL), ("rider_monthly", RIDER_BILL_URL)):
                        print("当前检查：" + dataset)
                        extra = {"finish_on_download": True, "expected_url": url} if args.finish_on_download else {}
                        print(f"控件检查已保存：{inspect_page(page, run_dir / dataset, navigate=lambda: navigate(url), **extra)}")
                        if page.is_closed():
                            live = [item for item in context.pages if not item.is_closed() and urlparse(item.url).hostname == "aeolus.ele.me"]
                            if len(live) != 1:
                                raise BillCollectionError("无法唯一确认下一步联调页面")
                            page = live[0]
                elif args.inspect:
                    url = INSPECTION_URLS[args.dataset]
                    extra = {"finish_on_download": True, "expected_url": url} if args.finish_on_download else {}
                    if args.snapshot_only:
                        extra = {"snapshot_only": True, "expected_url": url}
                    if args.observe_controls:
                        extra = {"observe_controls": True, "expected_url": url}
                    print(f"控件检查已保存：{inspect_page(page, run_dir, navigate=lambda: navigate(url), **extra)}")
                else:
                    url = RIDER_BILL_URL if args.dataset == "rider_monthly" else BILL_URL
                    instance = None
                    stage = "enter_report"
                    try:
                        navigate(url)
                        if args.acceptance:
                            print("隔离验收：只自动切换城市、筛选和下载，不执行薪资核算，不启用正式配置。")
                            page.wait_for_timeout(3000)
                            parsed = urlparse(page.url)
                            if parsed.hostname == "aeolus.ele.me" and "dashboard" in parsed.fragment:
                                navigate(url)
                            stage = "wait_for_merchant_header"
                            page.locator(profile["agency_context"]).wait_for(state="visible", timeout=30000)
                        else:
                            input("请在新开的浏览器完成正常登录并进入对应账单页，不必手动选择周期；完成后在此按回车：")
                        collector = MonthlyBillPageCollector if args.dataset == "rider_monthly" else BillPageCollector
                        instance = collector(page, profile, run_dir, acceptance_only=args.acceptance)
                        if args.acceptance and args.switch_from:
                            stage = "switch_to_start_city"
                            original = instance.profile
                            instance.profile = {**original, "expected_agency_id": args.switch_from}
                            try:
                                instance._check_agency_context()
                            finally:
                                instance.profile = original
                        stage = "collect_target_city"
                        if args.resume_run:
                            stage = "resume_confirmed_daily_task"
                            instance.resume_daily_acceptance(request)
                        else:
                            instance.collect(request)
                    except Exception as exc:
                        if args.acceptance:
                            diagnostics = run_dir.with_name(run_dir.name + "-diagnostics")
                            diagnostics.mkdir(parents=True, exist_ok=True)
                            failure = instance.failure_diagnostics if instance else None
                            atomic_json(diagnostics / "failure.json", {
                                "acceptance_only": True, "production_profile_enabled": False,
                                "stage": stage, "control": instance.last_control if instance else None,
                                "failure": failure or safe_operation_failure(exc),
                                "site": urlparse(page.url).hostname,
                            })
                            try:
                                save_inspection(page, diagnostics, {}, [])
                            except Exception:
                                pass
                            print(f"隔离验收失败记录：{diagnostics}")
                        raise
            finally:
                browser.close()
        return 0
    except (BillCollectionError, ValueError, OSError, json.JSONDecodeError) as exc:
        print(f"采集未完成：{exc}")
        return 1
    except Exception:
        print("采集未完成：浏览器启动或网页访问失败，请检查浏览器安装和网络连接")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
