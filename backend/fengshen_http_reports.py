"""HTTP adapters for monthly UB bills and city-wide order/violation reports.

Parameters follow the official salary-bill-ub bundle and the previously
observed order interfaces. No browser or DOM automation is used at runtime.
Export receipts are durable and submissions are never automatically replayed.
"""
import csv
import datetime as dt
import hashlib
import json
import math
import shutil
import time
from pathlib import Path

from fengshen_bill import (
    BillCollectionError, MonthlyBillRequest, MONTHLY_EXPORT_URL,
    MONTHLY_QUERY_URL, atomic_json, monthly_export_scope, nested_value,
    validate_bill_file,
)
from order_metrics import measured
from fengshen_http import HttpTransportError
from fengshen_orders import (
    EXPORT_URL, QUERY_URL, TASKS_URL, TASK_URL, VIOLATIONS_URL, ENUMERATE_URL,
    ALL_CITY_SEND_PRODUCT, OrderRequest, date_batches, new_task, query_count, task_rows,
    waybill_scope, SHANGHAI,
)

MONTHLY_SCOPE_ATTEMPTS = 3


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


def order_recovery_manifests(plan, source, selected):
    """Validate retained files and submission scope without platform requests."""
    source = Path(source)
    result = []
    if not selected or not set(selected) <= {"fraud", "problem"} or source.is_symlink():
        raise BillCollectionError("原运单恢复范围无效")
    for first, last in date_batches(plan.start, plan.end):
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
        if (query.get("status") != "success" or ledger.get("submission_state") != "submitted"
                or ledger.get("scope", {}).get("dataset") != "issue_orders"
                or not isinstance(task.get("task_id"), str) or not task["task_id"].isdigit()
                or type(total) is not int or total < 0 or not isinstance(counts, dict)
                or set(counts) != set(days) or any(type(v) is not int or v < 0 for v in counts.values())):
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
            files["violations"] = "violations.csv"
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
            **({"live_day_snapshot": query["live_day_snapshot"]} if "live_day_snapshot" in query else {}),
            "recovery_only": True}))
    return result


class ReportHttpCollector:
    def __init__(self, client, *, timeout=900, poll_interval=4, log=lambda _: None):
        if any(not math.isfinite(float(v)) or v <= 0 for v in (timeout, poll_interval)):
            raise ValueError("超时和轮询间隔必须为正数")
        self.client, self.timeout, self.poll_interval, self.log = client, timeout, poll_interval, log
        self.scope_recheck_delay = 3.0

    @measured("platform_poll_wait_seconds")
    def _wait(self, deadline):
        self.client.checkpoint()
        self.client.cancelled.wait(min(self.poll_interval, max(0, deadline - time.monotonic())))
        self.client.checkpoint()

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
            return {"date": today, "before": state["expected_waybills_by_date"][today],
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

    def _waybills(self, request, raw, state, created=False, time_basis=None, product_id=None):
        basis = time_basis or ("tracking_created" if created else "tracking_finish")
        dates_created = basis == "tracking_created"
        self.client.select_city(request.agency_id)
        state["expected_waybills_by_date"] = self._daily_counts(request, dates_created, product_id)
        # A single-day total is already proven by the identical daily query.
        # Repeating it immediately triggers REQUEST_TOO_FREQUENT on the platform.
        state["expected_waybills"] = total = (state["expected_waybills_by_date"][request.start]
                                             if request.start == request.end else self._count(request, dates_created, product_id))
        if not total and any(state["expected_waybills_by_date"].values()):
            raise BillCollectionError("运单批次查询为空但逐日查询非空，已停止导出")
        atomic_json(raw / "query_state.json", {"status": "success", "agency_id": request.agency_id,
                    "start": request.start, "end": request.end, **state})
        if total == 0:
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
        association_deadline = time.monotonic() + min(30, self.timeout)
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
                    payload = self.client.request_json("POST", TASK_URL,
                                body={"params": {"request": {"taskId": int(state["task_id"])}}})
                    state["failure_phase"] = "downloading"
                    self.log("[下载] 正在获取本批运单原始文件")
                    file = self._download_order_file(nested_value(payload, ["result", "data"]),
                                                     raw / ("waybills_created.xlsx" if created else "waybills.xlsx"))
                    state["failure_phase"] = "validating"
                    if validate_bill_file(file)["format"] != "xlsx":
                        raise BillCollectionError("运单导出不是有效 XLSX 文件")
                    snapshot = self._live_snapshot(request, state, receipt["started_at"], state["task_id"],
                                                   dates_created, product_id)
                    if snapshot is not None:
                        state["live_day_snapshot"] = snapshot
                        atomic_json(raw / "query_state.json", {"status": "success", "agency_id": request.agency_id,
                                    "start": request.start, "end": request.end, **state})
                    return file_info(file)
            self._wait(deadline)
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

    def orders(self, plan, raw, selected, *, allow_existing_batches=False):
        if not selected or not set(selected) <= {"fraud", "problem"}:
            raise HttpTransportError("运单下载项无效")
        batches, raw = date_batches(plan.start, plan.end), Path(raw)
        # Never create a later batch if an earlier attempt already exists.
        # Recovery must reconcile the retained task, not start another export.
        if not allow_existing_batches and raw.exists() and any(raw.rglob("*submission.json")):
            raise HttpTransportError("本目录已有运单导出记录，请查询原任务，不能重复提交",
                                     "waiting_export", "unknown")
        result = []
        for number, (first, last) in enumerate(batches, 1):
            self.client.checkpoint()
            request, directory = OrderRequest(first, last, plan.agency_id), raw / (first + "_" + last)
            directory.mkdir(parents=True, exist_ok=False)
            state = {"failure_phase": "preparing", "submission_state": "not_submitted"}
            manifest = {"dataset": "issue_orders", "transport": "http", "status": "preparing",
                        "agency_id": request.agency_id, "start": first, "end": last,
                        "time_basis": "tracking_finish", "merchant_group": "物流合作商",
                        "all_city_riders": True}
            path = directory / "manifest.json"
            atomic_json(path, manifest)
            self.log(f"[资料] 正在通过接口采集运单第 {number}/{len(batches)} 批：{first} 至 {last}")
            try:
                files = {"waybills": self._waybills(request, directory, state)}
                if "problem" in selected:
                    files["violations"] = self._violations(request, directory, state)
                manifest.update(status="success", files={key: info["path"] for key, info in files.items()},
                                file_checks=files, task_id=state.get("task_id"),
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
