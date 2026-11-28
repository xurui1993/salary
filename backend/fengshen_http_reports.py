"""HTTP adapters for monthly UB bills and city-wide order/violation reports.

Parameters follow the official salary-bill-ub bundle and the previously
observed order interfaces. No browser or DOM automation is used at runtime.
Export receipts are durable and submissions are never automatically replayed.
"""
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait as wait_futures
import csv
import datetime as dt
import hashlib
import json
import math
import shutil
import threading
import time
from pathlib import Path

from fengshen_bill import (
    BillCollectionError, MonthlyBillRequest, MONTHLY_EXPORT_URL,
    MONTHLY_QUERY_URL, atomic_json, monthly_export_scope, nested_value,
    validate_bill_file,
)
from order_metrics import _current as _current_timings, measured
from fengshen_http import HttpTransportError
from fengshen_orders import (
    EXPORT_URL, QUERY_URL, TASKS_URL, TASK_URL, VIOLATIONS_URL, ENUMERATE_URL,
    ALL_CITY_SEND_PRODUCT, OrderRequest, ORDER_BATCH_SPAN, date_batches, new_task,
    query_count, task_rows, waybill_scope, SHANGHAI,
)

MONTHLY_SCOPE_ATTEMPTS = 3
DEFAULT_ORDER_EXPORT_CONCURRENCY = 3
ORDER_EXPORT_MIN_INTERVAL = 6.0
ADAPTIVE_SPLIT_ROW_THRESHOLD = 235_000
ADAPTIVE_TARGET_BATCH_ROWS = 155_000
OSS_DOWNLOAD_WORKERS = 4
WAYBILL_FETCH_ATTEMPTS = 8
# High-volume cities expand about 10x (7 days ~1.7GB); the default cap targets small bills.
ORDER_WAYBILL_MAX_UNPACKED = 4 * 1024 ** 3


class _CombinedCancel:
    def __init__(self, primary, secondary):
        self.primary, self.secondary = primary, secondary

    def is_set(self):
        return self.primary.is_set() or self.secondary.is_set()

    def wait(self, timeout):
        deadline = time.monotonic() + max(0.0, float(timeout))
        while not self.is_set():
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return False
            if self.secondary.wait(min(0.2, remaining)):
                return True
        return True


def _fetch_and_validate_waybill(download_fn, file_url, target):
    target = Path(target)
    dl_started = time.perf_counter()
    file = download_fn(file_url, target)
    dl_seconds = time.perf_counter() - dl_started
    val_started = time.perf_counter()
    proof = validate_bill_file(file, max_unpacked=ORDER_WAYBILL_MAX_UNPACKED)
    if proof["format"] != "xlsx":
        raise BillCollectionError("运单导出不是有效 XLSX 文件")
    val_seconds = time.perf_counter() - val_started
    info = {"path": Path(file).name, "bytes": proof["bytes"], "sha256": proof["sha256"]}
    return info, proof.get("xlsx_data_rows"), dl_seconds, dl_seconds + val_seconds


def _fetch_violation_file(download_fn, file_url, target):
    target = Path(target)
    dl_started = time.perf_counter()
    file = download_fn(file_url, target)
    dl_seconds = time.perf_counter() - dl_started
    return file_info(file), dl_seconds


def _is_oss_not_ready_404(exc):
    return isinstance(exc, HttpTransportError) and "HTTP 404" in str(exc)


class MonthlyScopeMismatch(BillCollectionError):
    """First query page held records outside the target city, month or type."""

    def __init__(self, problem):
        # Only the three checked fields are echoed; never amounts or tokens.
        super().__init__("月度 UB 查询返回了非目标城市、月份或业务类型记录："
                         + json.dumps(problem, ensure_ascii=False, sort_keys=True))
        self.problem = problem


def monthly_scope_problem(rows, request, agency_id):
    """Checked fields of the first row outside the target scope, else None."""
    for row in rows:
        if (not isinstance(row, dict) or str(row.get("agencyId")) != agency_id
                or row.get("billCycle") not in (request.month, request.start + "至" + request.end)
                or row.get("bizType") != 3):
            if isinstance(row, dict):
                return {key: row.get(key) for key in ("agencyId", "billCycle", "bizType")}
            return {"row": type(row).__name__}
    return None


def monthly_body(request):
    # Official UB route: bizType=3; no team, rider, or status restriction.
    body = {"params": {"request": {"bizType": 3, "billCycle": request.month,
            "teamIds": None, "settleStatusList": [], "pageNum": 1, "pageSize": 10}}}
    monthly_export_scope(body, request)
    return body


def order_body(request, *, export=False, created=False, product_id=None):
    first, last = request.timestamps
    start_key = "trackingCreatedStart" if created else "trackingFinishStart"
    end_key = "trackingCreatedEnd" if created else "trackingFinishEnd"
    period_key = "trackingCreatedTimePeriodList" if created else "trackingFinishTimePeriodList"
    fields = {
        start_key: first, end_key: last,
        period_key: ["0-86400"],
        "trackingStateKey": "all", "trackingLabelKey": "all",
        "current": 1, "pageSize": 10,
    }
    if product_id is not None:
        fields["productIdList"] = [product_id]
    body = {"params": {"request": fields}}
    if export:
        body["params"]["request"]["exportType"] = 1
    if not waybill_scope(body, request, {"all_state_value": "all", "all_label_value": "all"}, export,
                         created=created, product_id=product_id):
        raise BillCollectionError("运单接口参数未覆盖所选城市全部骑手和日期")
    return body


def monthly_count(payload, request, agency_id):
    data = payload.get("result") if isinstance(payload, dict) else None
    if not isinstance(data, dict) or type(data.get("total")) is not int or data["total"] < 0:
        raise BillCollectionError("月度 UB 账单查询总数格式变化，已停止导出")
    rows = data.get("data")
    if not isinstance(rows, list) or len(rows) > data["total"]:
        raise BillCollectionError("月度 UB 账单查询记录数与总数不一致，已停止导出")
    problem = monthly_scope_problem(rows, request, agency_id)
    if problem is not None:
        raise MonthlyScopeMismatch(problem)
    return data["total"]


def file_info(path):
    path = Path(path)
    with path.open("rb") as stream:
        checksum = hashlib.file_digest(stream, "sha256").hexdigest()
    return {"path": path.name, "bytes": path.stat().st_size, "sha256": checksum}


def _split_date_range(first, last, parts):
    start_date = dt.date.fromisoformat(first)
    days = [(start_date + dt.timedelta(days=i)).isoformat()
            for i in range((dt.date.fromisoformat(last) - start_date).days + 1)]
    parts = max(1, min(len(days), int(parts)))
    base, extra = divmod(len(days), parts)
    result, cursor = [], 0
    for idx in range(parts):
        size = base + (1 if idx < extra else 0)
        chunk = days[cursor:cursor + size]
        result.append((chunk[0], chunk[-1]))
        cursor += size
    return result


def _discovered_recovery_batches(start, end, source, *, max_days=60):
    source = Path(source)
    if not source.is_dir():
        return None
    first_day, last_day = dt.date.fromisoformat(start), dt.date.fromisoformat(end)
    if not 0 <= (last_day - first_day).days < max_days:
        return None
    by_start = {}
    for entry in source.iterdir():
        if not entry.is_dir() or entry.is_symlink() or "_" not in entry.name:
            continue
        parts = entry.name.split("_")
        if len(parts) != 2:
            continue
        try:
            b_start, b_end = dt.date.fromisoformat(parts[0]), dt.date.fromisoformat(parts[1])
        except ValueError:
            continue
        if 0 <= (b_end - b_start).days < ORDER_BATCH_SPAN:
            by_start.setdefault(parts[0], []).append((parts[0], parts[1], b_end))
    result, cursor = [], first_day
    while cursor <= last_day:
        candidates = by_start.get(cursor.isoformat(), ())
        if len(candidates) != 1:
            return None
        b_first, b_last, b_end_date = candidates[0]
        result.append((b_first, b_last))
        cursor = b_end_date + dt.timedelta(days=1)
    return result if result and result[-1][1] == end else None


def order_recovery_batches(plan, source, *, max_days=60):
    """Use actual contiguous batch directories if present, else standard spans."""
    source = Path(source)
    discovered = _discovered_recovery_batches(plan.start, plan.end, source, max_days=max_days)
    if discovered is not None:
        return discovered
    for span in (ORDER_BATCH_SPAN, 5):
        batches = date_batches(plan.start, plan.end, span=span, max_days=max_days)
        if all((source / (first + "_" + last)).is_dir() for first, last in batches):
            return batches
    return date_batches(plan.start, plan.end, span=ORDER_BATCH_SPAN, max_days=max_days)


def order_recovery_manifests(plan, source, selected):
    """Validate retained files and submission scope without platform requests."""
    source = Path(source)
    result = []
    if not selected or not set(selected) <= {"fraud", "problem"} or source.is_symlink():
        raise BillCollectionError("原运单恢复范围无效")
    max_days = 90 if set(selected) == {"problem"} else 60
    for first, last in order_recovery_batches(plan, source, max_days=max_days):
        directory = source / (first + "_" + last)
        def proof(name):
            path = directory / name
            if (directory.is_symlink() or path.is_symlink() or not path.is_file()
                    or not 0 < path.stat().st_size <= 128 * 1024):
                raise BillCollectionError("原运单回执缺失，不能恢复")
            value = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(value, dict):
                raise BillCollectionError("原运单回执格式无效")
            return value
        query, task, ledger = proof("query_state.json"), proof("task.json"), proof("http_submission.json")
        for value in (query, task, ledger.get("scope", {})):
            if (value.get("agency_id") != plan.agency_id or value.get("start") != first or value.get("end") != last):
                raise BillCollectionError("原运单城市或日期回执不符")
        total, counts = query.get("expected_waybills"), query.get("expected_waybills_by_date")
        days = [(dt.date.fromisoformat(first) + dt.timedelta(days=n)).isoformat()
                for n in range((dt.date.fromisoformat(last) - dt.date.fromisoformat(first)).days + 1)]
        valid_counts = (
            (counts is None and query.get("count_basis") == "batch_total" and type(total) is int and total > 0)
            or (isinstance(counts, dict) and set(counts) == set(days)
                and all(type(v) is int and v >= 0 for v in counts.values()))
        )
        if (query.get("status") != "success" or ledger.get("submission_state") != "submitted"
                or ledger.get("scope", {}).get("dataset") != "issue_orders"
                or not isinstance(task.get("task_id"), str) or not task["task_id"].isdigit()
                or type(total) is not int or total < 0 or not valid_counts):
            raise BillCollectionError("原运单提交或数量回执不完整")
        # The platform's range total may differ from the daily query sum.
        # prepare_order_files enforces every exported day's actual row count;
        # retain both proofs instead of rejecting a recoverable original file.
        files = {"waybills": "waybills.xlsx"}
        if "problem" in selected:
            violation = proof("violation_submission.json")
            if (violation.get("submission_state") != "submitted" or violation.get("scope") != {
                    "agency_id": plan.agency_id, "start": first, "end": last, "dataset": "violations"}):
                raise BillCollectionError("原服务奖惩报告提交回执不符")
            files["violations"] = ("violations_empty.csv"
                                   if not (directory / "violations.csv").is_file()
                                   and (directory / "violations_empty.csv").is_file()
                                   else "violations.csv")
        checks = {}
        for kind, name in files.items():
            path = directory / name
            if path.is_symlink() or not path.is_file() or not 0 < path.stat().st_size <= 200 * 1024 * 1024:
                raise BillCollectionError("原运单或服务奖惩文件不可用，未重新导出")
            checks[kind] = file_info(path)
        result.append((directory, {"dataset": "issue_orders", "transport": "http", "status": "success",
            "agency_id": plan.agency_id, "start": first, "end": last, "time_basis": "tracking_finish",
            "merchant_group": "物流合作商", "all_city_riders": True, "files": files, "file_checks": checks,
            "task_id": task["task_id"], "expected_waybills": total, "expected_waybills_by_date": counts,
            **({"count_basis": query["count_basis"]} if "count_basis" in query else {}),
            **({"live_day_snapshot": query["live_day_snapshot"]} if "live_day_snapshot" in query else {}),
            "recovery_only": True}))
    return result


class ReportHttpCollector:
    def __init__(self, client, *, timeout=900, poll_interval=4, log=lambda _: None):
        if any(not math.isfinite(float(v)) or v <= 0 for v in (timeout, poll_interval)):
            raise ValueError("超时和轮询间隔必须为正数")
        self.client, self.timeout, self.poll_interval, self.log = client, timeout, poll_interval, log
        self.scope_recheck_delay = 3.0
        self.export_interval = ORDER_EXPORT_MIN_INTERVAL if poll_interval >= 1.0 else 0.0
        self._last_export_at = None

    @measured("platform_poll_wait_seconds")
    def _wait(self, deadline, started=None):
        self.client.checkpoint()
        since = time.monotonic() - (started if started is not None else time.monotonic())
        interval = min(self.poll_interval, 2.0) if since < 60 else self.poll_interval
        self.client.cancelled.wait(min(interval, max(0, deadline - time.monotonic())))
        self.client.checkpoint()

    @measured("platform_poll_wait_seconds")
    def _wait_seconds(self, seconds):
        self.client.checkpoint()
        self.client.cancelled.wait(max(0.0, float(seconds)))
        self.client.checkpoint()

    @staticmethod
    def _record_source_download_seconds(seconds):
        value = _current_timings.get()
        if value is not None:
            value["source_download_seconds"] = value.get("source_download_seconds", 0) + seconds

    def _isolated_downloader(self, cancelled=None):
        client_vars = vars(self.client) if hasattr(self.client, "__dict__") else {}
        if "download_isolated" in client_vars:
            fn = self.client.download_isolated
            return lambda url, target: fn(url, target)
        if "download" in client_vars:
            return None
        if hasattr(self.client, "download_isolated"):
            return lambda url, target: self.client.download_isolated(url, target, cancelled=cancelled)
        return None

    @staticmethod
    def _failure(exc, manifest, path, phase, submission):
        # A transport exception can carry more precise submission information.
        phase = getattr(exc, "download_failure_phase", phase)
        submission = getattr(exc, "download_submission_state", submission)
        manifest.update(status="failed", failure_phase=phase, submission_state=submission)
        atomic_json(path, manifest)
        if isinstance(exc, BillCollectionError):
            exc.download_failure_phase = phase
            exc.download_submission_state = submission
            raise exc
        raise HttpTransportError("风神接口采集未完成，已保留本次记录", phase, submission) from None

    def monthly(self, plan, raw):
        request, raw = MonthlyBillRequest(plan.month), Path(raw)
        if (raw / "http_submission.json").exists():
            raise HttpTransportError("月度账单已有提交记录，不能重复导出", "waiting_export", "unknown")
        raw.mkdir(parents=True, exist_ok=True)
        body = monthly_body(request)
        manifest = {"platform": "fengshen", "transport": "http", "dataset": "rider_monthly",
                    "agency_id": plan.agency_id, "start": request.start, "end": request.end,
                    "month": request.month, "merchant_group": "物流合作商",
                    "station_scope": "all_in_current_agency", "bill_status": "all",
                    "snapshot_only": True, "status": "preparing", "files": []}
        path = raw / "manifest.json"
        atomic_json(path, manifest)
        phase, submission = "preparing", "not_submitted"
        try:
            # A scope mismatch right after a city switch is a transient
            # platform-side inconsistency (observed 2026-10-22: same request
            # succeeded minutes later). The query is read-only and no export
            # was submitted, so re-selecting the city and re-checking is safe.
            for attempt in range(1, MONTHLY_SCOPE_ATTEMPTS + 1):
                self.client.select_city(plan.agency_id)
                payload = self.client.request_json("POST", MONTHLY_QUERY_URL, body=body)
                try:
                    manifest["expected_rows"] = monthly_count(payload, request, plan.agency_id)
                except MonthlyScopeMismatch as exc:
                    if attempt == MONTHLY_SCOPE_ATTEMPTS:
                        raise
                    self.log(f"[校验] 第 {attempt} 次月度账单范围核对未通过（{exc.problem}），正在重查")
                    self.client.cancelled.wait(self.scope_recheck_delay)
                    self.client.checkpoint()
                else:
                    break
            self.client.assert_city(plan.agency_id)
            phase, submission = "submitting", "unknown"
            self.log("[账单] 月份和全城市范围已核对，正在提交月度 UB 账单导出")
            payload, _ = self.client.submit_once(MONTHLY_EXPORT_URL, body, raw / "http_submission.json",
                                               {"agency_id": plan.agency_id, "month": request.month,
                                                "dataset": "rider_monthly"})
            submission = "submitted"
            if nested_value(payload, ["result", "data", "validRes"]) is not True:
                raise BillCollectionError("平台未确认月度 UB 账单导出有效，未重复提交")
            url = nested_value(payload, ["result", "data", "fileUrl"])
            self.client.assert_city(plan.agency_id)
            phase = "downloading"
            self.log("[下载] 正在获取月度 UB 账单原始文件")
            temporary = self.client.download(url, raw / "monthly.download")
            phase = "validating"
            proof = validate_bill_file(temporary)
            destination = raw / (f"bill_{request.start}_{request.end}_direct." + proof["format"])
            if destination.exists():
                raise BillCollectionError("本次月度账单文件已存在，未覆盖")
            temporary.rename(destination)
            manifest.update(status="success", files=[{"path": destination.name, **proof}])
            atomic_json(path, manifest)
            self.log("[完成] 月度 UB 账单已通过接口下载并校验")
            return manifest
        except Exception as exc:
            self._failure(exc, manifest, path, phase, submission)

    def _tasks(self):
        return task_rows(self.client.request_json("POST", TASKS_URL,
                         body={"params": {"request": {"current": 1, "pageSize": 20}}}))

    def _count(self, request, created=False, product_id=None):
        if getattr(self.client, "current_agency", None) != request.agency_id:
            self.client.assert_city(request.agency_id)
        return query_count(self.client.request_json("POST", QUERY_URL,
                           body=order_body(request, created=created, product_id=product_id)),
                           request.agency_id)

    def _daily_counts(self, request, created=False, product_id=None):
        result = {}
        first, last = dt.date.fromisoformat(request.start), dt.date.fromisoformat(request.end)
        while first <= last:
            day = first.isoformat()
            result[day] = self._count(OrderRequest(day, day, request.agency_id), created, product_id)
            first += dt.timedelta(days=1)
        return result

    def _live_snapshot(self, request, state, started_at, task_id, created=False, product_id=None):
        today = dt.datetime.now(SHANGHAI).date().isoformat()
        # Do not relax historical dates or reconstruct an old day's live counts.
        if (request.start <= today <= request.end
                and dt.datetime.fromtimestamp(started_at, SHANGHAI).date().isoformat() == today):
            self.client.select_city(request.agency_id)
            after = self._count(OrderRequest(today, today, request.agency_id), created, product_id)
            self.log("[校验] 当天运单持续新增，正在核对导出前后实时快照数量")
            daily = state.get("expected_waybills_by_date")
            before = daily[today] if isinstance(daily, dict) and today in daily else after
            return {"date": today, "before": before,
                    "after": after, "task_id": task_id, "started_at": started_at, "checked_at": time.time()}
        return None

    @staticmethod
    def _empty(raw, name, columns):
        path = raw / name
        with path.open("x", encoding="utf-8-sig", newline="") as output:
            csv.writer(output).writerow(sorted(columns))
        return {**file_info(path), "platform_confirmed_empty": True}

    @measured("source_download_seconds")
    def _download_order_file(self, url, target):
        return self.client.download(url, target)

    def _download_waybill_file(self, state, target, *, with_info=False, with_rows=False, agency_id=None):
        """Fetch the completed export; large OSS uploads or URL lookups can lag behind status=1."""
        from fengshen_bill import AuthenticationRequired
        target = Path(target)
        max_attempts = WAYBILL_FETCH_ATTEMPTS if self.poll_interval >= 1.0 else 4
        for attempt in range(1, max_attempts + 1):
            state["failure_phase"] = "downloading"
            try:
                if attempt > 1 and agency_id is not None:
                    if hasattr(self.client, "current_agency"):
                        self.client.current_agency = None
                    self.client.select_city(agency_id)
                self.log("[下载] 正在获取本批运单原始文件")
                payload = self.client.request_json("POST", TASK_URL,
                            body={"params": {"request": {"taskId": int(state["task_id"])}}})
                file_url = nested_value(payload, ["result", "data"])
                if not isinstance(file_url, str) or not file_url.strip():
                    raise BillCollectionError("运单导出文件地址尚未就绪")
                file = self._download_order_file(file_url, target)
                state["failure_phase"] = "validating"
                proof = validate_bill_file(file, max_unpacked=ORDER_WAYBILL_MAX_UNPACKED)
                if proof["format"] != "xlsx":
                    raise BillCollectionError("运单导出不是有效 XLSX 文件")
                info = {"path": Path(file).name, "bytes": proof["bytes"], "sha256": proof["sha256"]}
                if with_info and with_rows:
                    return file, info, proof.get("xlsx_data_rows")
                if with_info:
                    return file, info
                return file
            except AuthenticationRequired:
                target.unlink(missing_ok=True)
                raise
            except (BillCollectionError, HttpTransportError) as exc:
                target.unlink(missing_ok=True)
                if isinstance(exc, HttpTransportError) and not _is_oss_not_ready_404(exc):
                    raise
                files_session = getattr(self.client, "files_session", None)
                if files_session is not None:
                    files_session.close()
                if attempt == max_attempts:
                    raise
                self.log(f"[下载] 本批运单文件获取或校验未通过，正在重新获取（第 {attempt + 1}/{max_attempts} 次）")
                if self.poll_interval >= 1.0:
                    self.client.cancelled.wait(min(10.0, 2.0 * attempt))
                    self.client.checkpoint()

    def _try_waybill_url(self, item, *, reselect=False):
        from fengshen_bill import AuthenticationRequired
        request, state = item["request"], item["state"]
        state["failure_phase"] = "downloading"
        try:
            if reselect:
                if hasattr(self.client, "current_agency"):
                    self.client.current_agency = None
                self.client.select_city(request.agency_id)
            elif getattr(self.client, "current_agency", None) != request.agency_id:
                self.client.select_city(request.agency_id)
            self.log("[下载] 正在获取本批运单原始文件")
            payload = self.client.request_json("POST", TASK_URL,
                        body={"params": {"request": {"taskId": int(state["task_id"])}}})
            file_url = nested_value(payload, ["result", "data"])
            if not isinstance(file_url, str) or not file_url.strip():
                raise BillCollectionError("运单导出文件地址尚未就绪")
            return file_url
        except (AuthenticationRequired, HttpTransportError) as exc:
            self._fail_item(item, exc)

    @measured("order_counts_seconds")
    def _prepare_counts(self, request, created=False, product_id=None):
        self.client.select_city(request.agency_id)
        counts = self._daily_counts(request, created, product_id)
        # A single-day total is already proven by the identical daily query.
        # Repeating it immediately triggers REQUEST_TOO_FREQUENT on the platform.
        total = (counts[request.start] if request.start == request.end
                 else self._count(request, created, product_id))
        if not total and any(counts.values()):
            raise BillCollectionError("运单批次查询为空但逐日查询非空，已停止导出")
        return {"expected_waybills_by_date": counts, "expected_waybills": total}

    def _waybills(self, request, raw, state, created=False, time_basis=None, product_id=None, prepared=None):
        basis = time_basis or ("tracking_created" if created else "tracking_finish")
        dates_created = basis == "tracking_created"
        prepared = prepared or self._prepare_counts(request, dates_created, product_id)
        state.update(prepared)
        atomic_json(raw / "query_state.json", {"status": "success", "agency_id": request.agency_id,
                    "start": request.start, "end": request.end, **state})
        if state["expected_waybills"] == 0:
            if created:
                from waybill_workbook import WAYBILL_TITLES
            else:
                from order_sources import WAYBILL_COLUMNS
            return self._empty(raw, "waybills_created_empty.csv" if created else "waybills_empty.csv",
                               WAYBILL_TITLES if created else WAYBILL_COLUMNS)
        baseline = self._tasks()
        atomic_json(raw / "http_baseline.json", {"task_ids": [str(row["id"]) for row in baseline]})
        self.client.assert_city(request.agency_id)
        state.update(failure_phase="submitting", submission_state="unknown")
        scope_text = "全城市" + ("、全城送标品" if product_id is not None else "")
        self.log("[账单] 运单{}和{}范围已核对，正在提交导出".format("生成日期" if dates_created else "完成日期", scope_text))
        _, receipt = self.client.submit_once(EXPORT_URL, order_body(request, export=True, created=dates_created,
                                                             product_id=product_id),
                                            raw / "http_submission.json",
                                            {"agency_id": request.agency_id, "start": request.start,
                                             "end": request.end,
                                             "dataset": "delivery_waybill" if created else "issue_orders"})
        state.update(failure_phase="waiting_export", submission_state="submitted")
        deadline, matched = time.monotonic() + self.timeout, None
        started = time.monotonic()
        association_deadline = started + min(30, self.timeout)
        baseline_ids = {str(row["id"]) for row in baseline}
        while time.monotonic() < deadline:
            self.client.assert_city(request.agency_id)
            current = self._tasks()
            if matched is None:
                matched = new_task(baseline_ids, current, int(receipt["started_at"] * 1000),
                                   int(receipt["finished_at"] * 1000))
                if matched is not None:
                    state["task_id"] = str(matched["id"])
                    atomic_json(raw / "task.json", {"task_id": state["task_id"],
                                "agency_id": request.agency_id, "start": request.start,
                                "end": request.end,
                                "time_basis": basis})
                elif time.monotonic() >= association_deadline:
                    raise HttpTransportError("无法唯一关联本批新运单导出任务，已保留提交记录",
                                             "waiting_export", "unknown")
            else:
                rows = [row for row in current if str(row["id"]) == state["task_id"]]
                if len(rows) != 1 or any(rows[0].get(k) != matched.get(k) for k in ("exportTime", "fileName")):
                    raise BillCollectionError("本批运单任务身份发生变化，未下载其他记录")
                matched = rows[0]
            if matched is not None:
                if matched.get("statusDesc") in ("导出失败", "失败"):
                    raise BillCollectionError("本批运单导出失败，已保留原任务")
                if matched.get("statusDesc") == "导出成功":
                    if type(matched.get("status")) is not int or matched["status"] != 1:
                        raise BillCollectionError("运单导出成功状态与已核实协议不符")
                    file = self._download_waybill_file(
                        state, raw / ("waybills_created.xlsx" if created else "waybills.xlsx"),
                        agency_id=request.agency_id)
                    snapshot = self._live_snapshot(request, state, receipt["started_at"], state["task_id"],
                                                   dates_created, product_id)
                    if snapshot is not None:
                        state["live_day_snapshot"] = snapshot
                        atomic_json(raw / "query_state.json", {"status": "success", "agency_id": request.agency_id,
                                    "start": request.start, "end": request.end, **state})
                    return file_info(file)
            self._wait(deadline, started)
        raise HttpTransportError("本批运单生成超时，已保留原任务编号", "waiting_export", "submitted")

    def _violations(self, request, raw, state):
        first, last = request.timestamps
        body = {"params": {"request": {"violationStartTime": first,
                                      "violationEndTime": last, "appealStatus": []}}}
        self.client.assert_city(request.agency_id)
        state.update(failure_phase="submitting", submission_state="unknown")
        payload, _ = self.client.submit_once(VIOLATIONS_URL, body, raw / "violation_submission.json",
                                            {"agency_id": request.agency_id, "start": request.start,
                                             "end": request.end, "dataset": "violations"})
        state["submission_state"] = "submitted"
        url = nested_value(payload, ["result", "data", "fileUrl"])
        if url == "":
            from order_sources import VIOLATION_COLUMNS
            return self._empty(raw, "violations_empty.csv", VIOLATION_COLUMNS)
        state["failure_phase"] = "downloading"
        self.log("[下载] 正在获取本批服务奖惩原始文件")
        return file_info(self._download_order_file(url, raw / "violations.csv"))

    @staticmethod
    def _order_manifest(request):
        return {"dataset": "issue_orders", "transport": "http", "status": "preparing",
                "agency_id": request.agency_id, "start": request.start, "end": request.end,
                "time_basis": "tracking_finish", "merchant_group": "物流合作商",
                "all_city_riders": True}

    @staticmethod
    def _mark(item, name, seconds):
        item["timings"][name] = item["timings"].get(name, 0.0) + seconds

    def _empty_waybills(self, raw):
        from order_sources import WAYBILL_COLUMNS
        return self._empty(raw, "waybills_empty.csv", WAYBILL_COLUMNS)

    def _success(self, item, files):
        manifest, state = item["manifest"], item["state"]
        manifest.update(status="success", files={key: info["path"] for key, info in files.items()},
                        file_checks=files, task_id=state.get("task_id"),
                        expected_waybills=state.get("expected_waybills"),
                        expected_waybills_by_date=state.get("expected_waybills_by_date"),
                        timings={key: round(value, 3) for key, value in item["timings"].items()})
        if "count_basis" in state:
            manifest["count_basis"] = state["count_basis"]
        if "live_day_snapshot" in state:
            manifest["live_day_snapshot"] = state["live_day_snapshot"]
        atomic_json(item["path"], manifest)
        item["settled"] = True
        return manifest

    def _fail_item(self, item, exc):
        item["settled"] = True
        item["manifest"]["timings"] = {key: round(value, 3) for key, value in item["timings"].items()}
        state = item["state"]
        self._failure(exc, item["manifest"], item["path"],
                      state.get("failure_phase", "preparing"),
                      state.get("submission_state", "not_submitted"))

    @staticmethod
    def _interrupt(item):
        state = item["state"]
        item["manifest"].update(status="interrupted",
                                failure_phase=state.get("failure_phase", "waiting_export"),
                                submission_state=state.get("submission_state", "submitted"),
                                task_id=state.get("task_id"),
                                timings={key: round(value, 3) for key, value in item["timings"].items()})
        atomic_json(item["path"], item["manifest"])
        item["settled"] = True

    @measured("order_counts_seconds")
    def _initial_counts(self, request):
        if getattr(self.client, "current_agency", None) != request.agency_id:
            self.client.select_city(request.agency_id)
        total = self._count(request)
        first, last = dt.date.fromisoformat(request.start), dt.date.fromisoformat(request.end)
        days = [(first + dt.timedelta(days=n)).isoformat() for n in range((last - first).days + 1)]
        if total == 0:
            counts = {request.start: 0} if request.start == request.end else self._daily_counts(request)
            if any(counts.values()):
                raise BillCollectionError("运单批次查询为空但逐日查询非空，已停止导出")
            return {"expected_waybills": 0, "expected_waybills_by_date": counts, "pending_days": []}
        if request.start == request.end:
            return {"expected_waybills": total, "expected_waybills_by_date": {request.start: total}, "pending_days": []}
        counts = {}
        today = dt.datetime.now(SHANGHAI).date().isoformat()
        if request.start <= today <= request.end:
            counts[today] = self._count(OrderRequest(today, today, request.agency_id))
        pending = [day for day in days if day not in counts]
        return {"expected_waybills": total, "expected_waybills_by_date": counts, "pending_days": pending}

    @measured("order_counts_seconds")
    def _step_daily_count(self, item):
        pending = item.get("pending_days")
        if not pending:
            return False
        request, directory, state = item["request"], item["directory"], item["state"]
        day = pending[0]
        try:
            started = time.perf_counter()
            if getattr(self.client, "current_agency", None) != request.agency_id:
                self.client.select_city(request.agency_id)
            count = self._count(OrderRequest(day, day, request.agency_id))
            self._mark(item, "counts", time.perf_counter() - started)
            pending.pop(0)
            state["expected_waybills_by_date"][day] = count
            if not pending:
                atomic_json(directory / "query_state.json", {
                    "status": "success", "agency_id": request.agency_id,
                    "start": request.start, "end": request.end, **state})
            return True
        except Exception as exc:
            self._fail_item(item, exc)

    def _finish_daily_counts(self, item):
        while item.get("pending_days"):
            self._step_daily_count(item)

    def _prepare_batch(self, item, counts_info, include_violations):
        request, directory, state = item["request"], item["directory"], item["state"]
        try:
            pending_days = list(counts_info.get("pending_days", ()))
            item["pending_days"] = pending_days
            state.update(
                expected_waybills=counts_info["expected_waybills"],
                expected_waybills_by_date=dict(counts_info["expected_waybills_by_date"]),
            )
            if not pending_days:
                atomic_json(directory / "query_state.json", {"status": "success", "agency_id": request.agency_id,
                            "start": request.start, "end": request.end, **state})
            if state["expected_waybills"] == 0:
                files = {"waybills": self._empty_waybills(directory)}
                if include_violations:
                    started = time.perf_counter()
                    files["violations"] = self._violations(request, directory, state)
                    self._mark(item, "violations", time.perf_counter() - started)
                return self._success(item, files)
            started = time.perf_counter()
            baseline = self._tasks()
            self._mark(item, "baseline", time.perf_counter() - started)
            atomic_json(directory / "http_baseline.json", {"task_ids": [str(row["id"]) for row in baseline]})
            if self._last_export_at is not None and self.export_interval > 0:
                remaining = self.export_interval - (time.monotonic() - self._last_export_at)
                if remaining > 0:
                    self.client.cancelled.wait(remaining)
                    self.client.checkpoint()
            self.client.assert_city(request.agency_id)
            state.update(failure_phase="submitting", submission_state="unknown")
            self.log("[账单] 运单完成日期和全城市范围已核对，正在提交导出")
            started = time.perf_counter()
            try:
                _, receipt = self.client.submit_once(EXPORT_URL, order_body(request, export=True),
                                                    directory / "http_submission.json",
                                                    {"agency_id": request.agency_id, "start": request.start,
                                                     "end": request.end, "dataset": "issue_orders"})
            finally:
                self._last_export_at = time.monotonic()
            self._mark(item, "submit", time.perf_counter() - started)
            state.update(failure_phase="waiting_export", submission_state="submitted")
            item.update(receipt=receipt, baseline_ids={str(row["id"]) for row in baseline},
                        matched=None, deadline=time.monotonic() + self.timeout,
                        submitted_at=time.monotonic())
            return None
        except Exception as exc:
            self._fail_item(item, exc)

    @measured("order_association_seconds")
    def _associate(self, item):
        request, state = item["request"], item["state"]
        limit = time.monotonic() + min(30, self.timeout)
        try:
            while time.monotonic() < limit:
                self.client.assert_city(request.agency_id)
                current = self._tasks()
                matched = new_task(item["baseline_ids"], current,
                                   int(item["receipt"]["started_at"] * 1000),
                                   int(item["receipt"]["finished_at"] * 1000))
                if matched is not None:
                    state["task_id"] = str(matched["id"])
                    item["matched"] = matched
                    atomic_json(item["directory"] / "task.json", {
                        "task_id": state["task_id"], "agency_id": request.agency_id,
                        "start": request.start, "end": request.end, "time_basis": "tracking_finish"})
                    return
                self._wait(limit, item["submitted_at"])
            raise HttpTransportError("无法唯一关联本批新运单导出任务，已保留提交记录",
                                     "waiting_export", "unknown")
        except Exception as exc:
            self._fail_item(item, exc)

    def _poll_batches(self, active):
        self.client.checkpoint()
        started = time.perf_counter()
        current = self._tasks()
        elapsed = time.perf_counter() - started
        finished = []
        for index in sorted(active):
            item = active[index]
            self._mark(item, "poll", elapsed)
            try:
                rows = [row for row in current if str(row["id"]) == item["state"].get("task_id")]
                if len(rows) != 1 or any(rows[0].get(key) != item["matched"].get(key)
                                         for key in ("exportTime", "fileName")):
                    raise BillCollectionError("本批运单任务身份发生变化，未下载其他记录")
                matched = item["matched"] = rows[0]
                if matched.get("statusDesc") in ("导出失败", "失败"):
                    raise BillCollectionError("本批运单导出失败，已保留原任务")
                if matched.get("statusDesc") == "导出成功":
                    if type(matched.get("status")) is not int or matched["status"] != 1:
                        raise BillCollectionError("运单导出成功状态与已核实协议不符")
                    finished.append(index)
                elif time.monotonic() >= item["deadline"]:
                    raise HttpTransportError("本批运单生成超时，已保留原任务编号",
                                             "waiting_export", "submitted")
            except Exception as exc:
                self._fail_item(item, exc)
        return finished

    def _prefetch_violations(self, item, oss_pool=None, isolated_download=None):
        request, directory = item["request"], item["directory"]
        v_state = {}
        try:
            started = time.perf_counter()
            if oss_pool is None or isolated_download is None:
                item["violations_info"] = self._violations(request, directory, v_state)
                self._mark(item, "violations", time.perf_counter() - started)
                return
            first, last = request.timestamps
            body = {"params": {"request": {"violationStartTime": first,
                                          "violationEndTime": last, "appealStatus": []}}}
            self.client.assert_city(request.agency_id)
            v_state.update(failure_phase="submitting", submission_state="unknown")
            payload, _ = self.client.submit_once(VIOLATIONS_URL, body, directory / "violation_submission.json",
                                                {"agency_id": request.agency_id, "start": request.start,
                                                 "end": request.end, "dataset": "violations"})
            v_state["submission_state"] = "submitted"
            url = nested_value(payload, ["result", "data", "fileUrl"])
            self._mark(item, "violations", time.perf_counter() - started)
            if url == "":
                from order_sources import VIOLATION_COLUMNS
                item["violations_info"] = self._empty(directory, "violations_empty.csv", VIOLATION_COLUMNS)
            else:
                self.log("[下载] 正在获取本批服务奖惩原始文件")
                target = directory / "violations.csv"
                fut = oss_pool.submit(_fetch_violation_file, isolated_download, url, target)
                item["violations_future"] = (fut, url, isolated_download)
        except Exception as exc:
            item["state"].update(v_state)
            self._fail_item(item, exc)

    def _resolve_violations_future(self, item):
        fut, url, isolated_download = item.pop("violations_future")
        target = item["directory"] / "violations.csv"
        max_attempts = 4
        for attempt in range(1, max_attempts + 1):
            try:
                if attempt == 1:
                    info, dl_seconds = fut.result()
                else:
                    info, dl_seconds = _fetch_violation_file(isolated_download, url, target)
                self._record_source_download_seconds(dl_seconds)
                self._mark(item, "violations", dl_seconds)
                item["violations_info"] = info
                return info
            except (BillCollectionError, HttpTransportError) as exc:
                target.unlink(missing_ok=True)
                if isinstance(exc, HttpTransportError) and not _is_oss_not_ready_404(exc):
                    raise
                if attempt == max_attempts:
                    raise
                if self.poll_interval >= 1.0:
                    self.client.cancelled.wait(min(6.0, 2.0 * attempt))
                    self.client.checkpoint()

    def _schedule_waybill_download(self, item, oss_pool, isolated_download, *, reselect=False):
        max_attempts = WAYBILL_FETCH_ATTEMPTS if self.poll_interval >= 1.0 else 4
        attempt = item.get("download_attempt", 1)
        try:
            file_url = self._try_waybill_url(item, reselect=reselect)
        except BillCollectionError as exc:
            if attempt >= max_attempts:
                self._fail_item(item, exc)
            item["download_attempt"] = attempt + 1
            item["download_future"] = None
            self.log(f"[下载] 本批运单文件地址尚未就绪，正在等待重取（第 {attempt + 1}/{max_attempts} 次）")
            delay = min(10.0, 2.0 * attempt) if self.poll_interval >= 1.0 else 0.0
            item["retry_after"] = time.monotonic() + delay
            return False
        target = item["directory"] / "waybills.xlsx"
        item["download_future"] = oss_pool.submit(
            _fetch_and_validate_waybill, isolated_download, file_url, target)
        return True

    def _apply_waybill_count_proof(self, item, xlsx_rows):
        if not item.get("pending_days"):
            return
        request, directory, state = item["request"], item["directory"], item["state"]
        today = dt.datetime.now(SHANGHAI).date().isoformat()
        if (xlsx_rows is not None and xlsx_rows == state.get("expected_waybills")
                and not (request.start <= today <= request.end)):
            item["pending_days"] = []
            state["expected_waybills_by_date"] = None
            state["count_basis"] = "batch_total"
            atomic_json(directory / "query_state.json", {
                "status": "success", "agency_id": request.agency_id,
                "start": request.start, "end": request.end, **state})

    def _finalize_downloaded_item(self, item, total_batches):
        request, directory, state = item["request"], item["directory"], item["state"]
        try:
            started = time.perf_counter()
            snapshot = self._live_snapshot(request, state, item["receipt"]["started_at"],
                                           state["task_id"])
            self._mark(item, "snapshot", time.perf_counter() - started)
            if snapshot is not None:
                state["live_day_snapshot"] = snapshot
                atomic_json(directory / "query_state.json", {"status": "success",
                            "agency_id": request.agency_id, "start": request.start,
                            "end": request.end, **state})
            files = {"waybills": item["waybill_info"]}
            if item["include_violations"]:
                if "violations_info" in item:
                    files["violations"] = item["violations_info"]
                elif "violations_future" in item:
                    state["failure_phase"] = "downloading"
                    files["violations"] = self._resolve_violations_future(item)
                else:
                    started = time.perf_counter()
                    files["violations"] = self._violations(request, directory, state)
                    self._mark(item, "violations", time.perf_counter() - started)
            manifest = self._success(item, files)
            manifest["total_stream_batches"] = total_batches
            return manifest
        except Exception as exc:
            self._fail_item(item, exc)

    def _download_batch(self, item):
        request, directory, state = item["request"], item["directory"], item["state"]
        try:
            started = time.perf_counter()
            _, waybill_info, xlsx_rows = self._download_waybill_file(
                state, directory / "waybills.xlsx", with_info=True, with_rows=True,
                agency_id=request.agency_id)
            self._mark(item, "download", time.perf_counter() - started)
            item["waybill_info"] = waybill_info
            self._apply_waybill_count_proof(item, xlsx_rows)
            self._finish_daily_counts(item)
        except Exception as exc:
            self._fail_item(item, exc)
        return self._finalize_downloaded_item(item, item["manifest"].get("total_stream_batches", 1))

    def orders_stream(self, plan, raw, selected, batches=None, *,
                      concurrency=DEFAULT_ORDER_EXPORT_CONCURRENCY,
                      allow_existing_batches=False):
        """Yield completed batch manifests while up to `concurrency` exports wait."""
        from fengshen_bill import AuthenticationRequired
        if not selected or not set(selected) <= {"fraud", "problem"}:
            raise HttpTransportError("运单下载项无效")
        try:
            concurrency = int(concurrency)
        except (TypeError, ValueError):
            raise HttpTransportError("运单导出并发数无效") from None
        if concurrency not in (1, 2, 3):
            raise HttpTransportError("运单导出并发数只能为 1、2 或 3")
        raw = Path(raw)
        max_days = 90 if set(selected) == {"problem"} else 60
        batches = list(batches if batches is not None
                       else date_batches(plan.start, plan.end, span=ORDER_BATCH_SPAN, max_days=max_days))
        if not batches:
            return
        if not allow_existing_batches and raw.exists() and any(raw.rglob("*submission.json")):
            raise HttpTransportError("本目录已有运单导出记录，请查询原任务，不能重复提交",
                                     "waiting_export", "unknown")
        self.client.checkpoint()
        if hasattr(self.client, "current_agency"):
            self.client.current_agency = None
        self.client.select_city(plan.agency_id)
        include_violations = "problem" in selected
        queue = [[first, last, True] for first, last in batches]
        stream_abort = threading.Event()
        stream_cancel = _CombinedCancel(self.client.cancelled, stream_abort)
        isolated_download = self._isolated_downloader(stream_cancel) if concurrency >= 2 else None
        oss_pool = ThreadPoolExecutor(max_workers=OSS_DOWNLOAD_WORKERS) if isolated_download is not None else None
        max_fetch_attempts = WAYBILL_FETCH_ATTEMPTS if self.poll_interval >= 1.0 else 4
        active = {}
        downloading = {}
        counting = {}
        last_poll_at = None
        next_index = 0
        try:
            while next_index < len(queue) or active or downloading or counting:
                self.client.checkpoint()
                progressed = False
                for index in list(sorted(downloading)):
                    item = downloading[index]
                    fut = item.get("download_future")
                    if fut is None:
                        if time.monotonic() >= item.get("retry_after", 0):
                            try:
                                self._schedule_waybill_download(
                                    item, oss_pool, isolated_download, reselect=True)
                            except BaseException:
                                downloading.pop(index, None)
                                raise
                            progressed = True
                        continue
                    if not fut.done():
                        continue
                    target = item["directory"] / "waybills.xlsx"
                    try:
                        waybill_info, xlsx_rows, dl_seconds, total_dl_seconds = fut.result()
                    except AuthenticationRequired as exc:
                        target.unlink(missing_ok=True)
                        downloading.pop(index, None)
                        self._fail_item(item, exc)
                    except (BillCollectionError, HttpTransportError) as exc:
                        target.unlink(missing_ok=True)
                        if isinstance(exc, HttpTransportError) and not _is_oss_not_ready_404(exc):
                            downloading.pop(index, None)
                            self._fail_item(item, exc)
                        attempt = item["download_attempt"]
                        if attempt >= max_fetch_attempts:
                            downloading.pop(index, None)
                            self._fail_item(item, exc)
                        item["download_attempt"] = attempt + 1
                        item["download_future"] = None
                        self.log(f"[下载] 本批运单文件获取或校验未通过，正在重新获取（第 {attempt + 1}/{max_fetch_attempts} 次）")
                        delay = min(10.0, 2.0 * attempt) if self.poll_interval >= 1.0 else 0.0
                        item["retry_after"] = time.monotonic() + delay
                        progressed = True
                        continue
                    except Exception as exc:
                        target.unlink(missing_ok=True)
                        downloading.pop(index, None)
                        self._fail_item(item, exc)
                    downloading.pop(index)
                    self._record_source_download_seconds(dl_seconds)
                    self._mark(item, "download", total_dl_seconds)
                    item["waybill_info"] = waybill_info
                    self._apply_waybill_count_proof(item, xlsx_rows)
                    progressed = True
                    if item.get("pending_days"):
                        counting[index] = item
                    else:
                        yield self._finalize_downloaded_item(item, len(queue))

                just_submitted = False
                while (next_index < len(queue) and len(active) < concurrency
                       and len(downloading) < OSS_DOWNLOAD_WORKERS):
                    if ((active or downloading or counting) and self.export_interval > 0
                            and self._last_export_at is not None
                            and time.monotonic() - self._last_export_at < self.export_interval):
                        break
                    index = next_index
                    first, last, can_split = queue[index]
                    request = OrderRequest(first, last, plan.agency_id)
                    directory = raw / (first + "_" + last)
                    manifest = self._order_manifest(request)
                    path = directory / "manifest.json"
                    item = {"index": index, "request": request, "directory": directory,
                            "manifest": manifest, "path": path,
                            "state": {"failure_phase": "preparing",
                                      "submission_state": "not_submitted"},
                            "timings": {}, "settled": False,
                            "include_violations": include_violations}
                    try:
                        started = time.perf_counter()
                        counts_info = self._initial_counts(request)
                        self._mark(item, "counts", time.perf_counter() - started)
                    except Exception as exc:
                        directory.mkdir(parents=True, exist_ok=True)
                        self._fail_item(item, exc)
                    if can_split and first < last and counts_info["expected_waybills"] > ADAPTIVE_SPLIT_ROW_THRESHOLD:
                        parts = math.ceil(counts_info["expected_waybills"] / ADAPTIVE_TARGET_BATCH_ROWS)
                        sub_ranges = _split_date_range(first, last, parts)
                        if len(sub_ranges) > 1:
                            self.log(f"[分批] 周期 {first} 至 {last} 共 {counts_info['expected_waybills']} 单，"
                                     f"自动拆分为 {len(sub_ranges)} 个子批次加速生成")
                            queue[index:index + 1] = [[sf, sl, False] for sf, sl in sub_ranges]
                            continue
                    directory.mkdir(parents=True, exist_ok=False)
                    manifest["total_stream_batches"] = len(queue)
                    atomic_json(path, manifest)
                    self.log(f"[资料] 正在通过接口采集运单第 {index + 1}/{len(queue)} 批：{first} 至 {last}")
                    next_index += 1
                    progressed = True
                    completed = self._prepare_batch(item, counts_info, include_violations)
                    if completed is not None:
                        completed["total_stream_batches"] = len(queue)
                        yield completed
                    else:
                        active[index] = item
                        self._associate(item)
                        just_submitted = True

                poll_due = (active and (
                    last_poll_at is None or just_submitted or self.poll_interval < 1.0
                    or time.monotonic() - last_poll_at >= min(self.poll_interval, 1.5)))
                if poll_due:
                    last_poll_at = time.monotonic()
                    finished = self._poll_batches(active)
                    for index in finished:
                        item = active.pop(index)
                        progressed = True
                        if oss_pool is None:
                            result_manifest = self._download_batch(item)
                            result_manifest["total_stream_batches"] = len(queue)
                            yield result_manifest
                        else:
                            if (item["include_violations"]
                                    and "violations_info" not in item
                                    and "violations_future" not in item):
                                self._prefetch_violations(item, oss_pool, isolated_download)
                            item["download_attempt"] = 1
                            self._schedule_waybill_download(
                                item, oss_pool, isolated_download, reselect=False)
                            downloading[index] = item

                if progressed:
                    continue

                if counting:
                    index = min(counting)
                    item = counting[index]
                    self._step_daily_count(item)
                    if not item.get("pending_days"):
                        counting.pop(index)
                        yield self._finalize_downloaded_item(item, len(queue))
                    continue

                viol_done = False
                for index in sorted(active):
                    item = active[index]
                    if (item["include_violations"]
                            and "violations_info" not in item
                            and "violations_future" not in item):
                        self._prefetch_violations(item, oss_pool, isolated_download)
                        viol_done = True
                        break
                if viol_done:
                    continue

                now = time.monotonic()
                wait_candidates = []
                if (next_index < len(queue) and len(active) < concurrency
                        and len(downloading) < OSS_DOWNLOAD_WORKERS
                        and self.export_interval > 0 and self._last_export_at is not None):
                    wait_candidates.append(max(0.0, (self._last_export_at + self.export_interval) - now))
                if active:
                    earliest = min(item["submitted_at"] for item in active.values())
                    deadline = min(item["deadline"] for item in active.values())
                    poll_span = min(self.poll_interval, 2.0) if (now - earliest) < 60 else self.poll_interval
                    next_poll_in = 0.0 if last_poll_at is None else max(0.0, (last_poll_at + poll_span) - now)
                    wait_candidates.append(min(next_poll_in, max(0.0, deadline - now)))
                for item in downloading.values():
                    if item.get("download_future") is None:
                        wait_candidates.append(max(0.0, item.get("retry_after", now) - now))
                dl_futures = [item["download_future"] for item in downloading.values()
                              if item.get("download_future") is not None]
                if dl_futures:
                    budget = min(wait_candidates) if wait_candidates else 0.5
                    wait_futures(dl_futures, timeout=min(max(0.0, budget), 0.5), return_when=FIRST_COMPLETED)
                    self.client.checkpoint()
                elif wait_candidates:
                    self._wait_seconds(min(wait_candidates))
                elif active:
                    earliest = min(item["submitted_at"] for item in active.values())
                    deadline = min(item["deadline"] for item in active.values())
                    self._wait(deadline, earliest)
                else:
                    self._wait_seconds(min(self.poll_interval, 0.2))
        except BaseException:
            stream_abort.set()
            if oss_pool is not None:
                oss_pool.shutdown(wait=True, cancel_futures=True)
                oss_pool = None
            for group in (active, downloading, counting):
                for item in group.values():
                    if not item["settled"]:
                        self._interrupt(item)
            raise
        finally:
            stream_abort.set()
            if oss_pool is not None:
                oss_pool.shutdown(wait=True, cancel_futures=True)

    def orders(self, plan, raw, selected, *, allow_existing_batches=False):
        max_days = 90 if set(selected) == {"problem"} else 60
        manifests = list(self.orders_stream(
            plan, raw, selected,
            date_batches(plan.start, plan.end, span=ORDER_BATCH_SPAN, max_days=max_days),
            concurrency=1, allow_existing_batches=allow_existing_batches))
        return sorted(manifests, key=lambda manifest: manifest["start"])

    def all_city_send_product_id(self):
        """Resolve the 全城送 productId from the platform enumeration for the selected city."""
        payload = self.client.request_json("POST", ENUMERATE_URL)
        result = payload.get("result") if isinstance(payload, dict) else None
        data = result.get("data") if isinstance(result, dict) else None
        products = data.get("product") if isinstance(data, dict) else None
        if not isinstance(products, dict):
            raise BillCollectionError("平台标品枚举结构变化，无法确认全城送筛选，已停止导出")
        matched = [int(key) for key, name in products.items() if name == ALL_CITY_SEND_PRODUCT
                   and str(key).isdigit()]
        if len(matched) != 1:
            raise BillCollectionError("平台未提供唯一的「全城送」标品，无法按全城送导出")
        return matched[0]

    def waybills_created(self, plan, raw, *, time_basis="tracking_finish", all_city_send=False):
        batches, raw = date_batches(plan.start, plan.end), Path(raw)
        if raw.exists() and any(raw.rglob("*submission.json")):
            raise HttpTransportError("本目录已有运单导出记录，请查询原任务，不能重复提交",
                                     "waiting_export", "unknown")
        product_id = self.all_city_send_product_id() if all_city_send else None
        if product_id is not None:
            self.log(f"[账单] 已确认全城送标品筛选编号 {product_id}，本任务仅导出全城送运单")
        result = []
        for number, (first, last) in enumerate(batches, 1):
            self.client.checkpoint()
            request, directory = OrderRequest(first, last, plan.agency_id), raw / (first + "_" + last)
            directory.mkdir(parents=True, exist_ok=False)
            state = {"failure_phase": "preparing", "submission_state": "not_submitted"}
            manifest = {"dataset": "delivery_waybill", "transport": "http", "status": "preparing",
                        "agency_id": request.agency_id, "start": first, "end": last,
                        "time_basis": time_basis, "merchant_group": "物流合作商",
                        "all_city_riders": True,
                        **({"all_city_send": True, "all_city_send_product_id": product_id}
                           if product_id is not None else {})}
            path = directory / "manifest.json"
            atomic_json(path, manifest)
            self.log(f"[资料] 正在通过接口采集运单数据第 {number}/{len(batches)} 批：{first} 至 {last}")
            try:
                info = self._waybills(request, directory, state, created=True,
                                      time_basis=time_basis, product_id=product_id)
                manifest.update(status="success", files=[info],
                                file_checks={"waybills_created": info}, task_id=state.get("task_id"),
                                expected_waybills=state["expected_waybills"],
                                expected_waybills_by_date=state["expected_waybills_by_date"])
                if "live_day_snapshot" in state:
                    manifest["live_day_snapshot"] = state["live_day_snapshot"]
                atomic_json(path, manifest)
                result.append(manifest)
            except Exception as exc:
                manifest["task_id"] = state.get("task_id")
                self._failure(exc, manifest, path, state["failure_phase"], state["submission_state"])
        return result

    def resume_orders(self, plan, raw, selected, source_dir):
        result = []
        for source, manifest in order_recovery_manifests(plan, source_dir, selected):
            self.client.checkpoint()
            directory = Path(raw) / source.name
            directory.mkdir(parents=True, exist_ok=False)
            for kind, name in manifest["files"].items():
                target = directory / name
                shutil.copyfile(source / name, target)
                if file_info(target) != manifest["file_checks"][kind]:
                    raise BillCollectionError("原运单恢复副本哈希不一致")
            if "live_day_snapshot" not in manifest:
                receipt = json.loads((source / "http_submission.json").read_text(encoding="utf-8"))
                snapshot = self._live_snapshot(OrderRequest(manifest["start"], manifest["end"], plan.agency_id),
                                               manifest, receipt["started_at"], manifest["task_id"])
                if snapshot is not None:
                    manifest["live_day_snapshot"] = snapshot
            atomic_json(directory / "manifest.json", manifest)
            result.append(manifest)
        return result
