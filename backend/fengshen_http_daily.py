"""Direct daily-bill collection and safe recovery of an original platform task."""
import json
import time
from pathlib import Path

from fengshen_bill import (
    BillCollectionError, BillRequest, DAILY_CREATE_URL, DAILY_QUERY_URL,
    DAILY_DOWNLOAD_URL, atomic_json, daily_export_scope, daily_tasks,
    new_daily_task, validate_bill_file,
)
from fengshen_http import HttpTransportError


class DailyHttpCollector:
    def __init__(self, client, *, timeout=900, poll_interval=4, log=lambda _: None):
        self.client, self.timeout, self.poll_interval, self.log = client, timeout, poll_interval, log

    def _tasks(self, agency_id):
        return daily_tasks(self.client.request_json("GET", DAILY_QUERY_URL,
                          params={"agentId": agency_id, "page": 1, "size": 100}))

    def daily(self, plan, raw, selected):
        if not selected or not set(selected) <= {"delivery_fee", "penalty"}:
            raise HttpTransportError("日账单下载项无效")
        request = BillRequest(plan.start, plan.end, False, False, plan.agency_id,
                              sub_bill_types=tuple(v for v, k in ((1, "delivery_fee"), (2, "penalty")) if k in selected))
        body = {"startDate": request.start, "endDate": request.end,
                "agentIds": [int(request.agency_id)], "subBillTypes": list(request.sub_bill_types),
                "periodType": 0, "billType": 1}
        daily_export_scope(body, request)
        raw = Path(raw)
        # Reconciliation, rather than another export, is required if this
        # directory contains an attempt from an earlier process.
        if (raw / "http_submission.json").exists():
            raise HttpTransportError("本目录已有导出记录，请继续查询原任务", "waiting_export", "unknown")
        raw.mkdir(parents=True, exist_ok=True)
        manifest = {"platform": "fengshen", "transport": "http", "dataset": "agency_daily",
                    "agency_id": request.agency_id, "start": request.start, "end": request.end,
                    "status": "preparing", "files": [], "sub_bill_scope": list(request.sub_bill_names),
                    "agency_scope": "target_city", "task_identity_mode": "list_delta"}
        path = raw / "manifest.json"
        atomic_json(path, manifest)
        phase, submission = "preparing", "not_submitted"
        try:
            self.client.select_city(request.agency_id)
            baseline = self._tasks(request.agency_id)
            # Persist only task identity metadata, never account or rider rows.
            atomic_json(raw / "http_baseline.json", {"task_ids": [t["id"] for t in baseline]})
            self.client.assert_city(request.agency_id)
            phase, submission = "submitting", "unknown"
            uncertain = False
            try:
                _, receipt = self.client.submit_once(DAILY_CREATE_URL, body, raw / "http_submission.json",
                                                     {"agency_id": request.agency_id, "start": request.start,
                                                      "end": request.end, "datasets": sorted(selected)})
                submission = "submitted"
            except HttpTransportError as exc:
                if exc.download_submission_state != "unknown":
                    raise
                uncertain = True
                receipt = json.loads((raw / "http_submission.json").read_text(encoding="utf-8"))
                self.log("[恢复] 创建响应未确认，仅查询原任务列表，不重新提交导出")
            phase = "waiting_export"
            manifest.update(status="waiting_for_new_task")
            atomic_json(path, manifest)
            deadline, task = time.monotonic() + self.timeout, None
            association_deadline = time.monotonic() + min(60, self.timeout)
            self.log("[账单] 已通过接口提交，正在等待本次导出任务")
            while time.monotonic() < deadline:
                self.client.checkpoint()
                current = self._tasks(request.agency_id)
                if task is None:
                    task = new_daily_task(baseline, current, request, receipt["started_at"],
                                          receipt.get("finished_at", receipt["started_at"] + 60))
                    if task:
                        manifest["task_id"] = str(task["id"])
                        atomic_json(path, manifest)
                        if uncertain:
                            receipt.update(submission_state="submitted", task_id=str(task["id"]),
                                           reconciled_from="unique_platform_task_delta")
                            atomic_json(raw / "http_submission.json", receipt)
                            submission = "submitted"
                    elif uncertain and time.monotonic() >= association_deadline:
                        raise HttpTransportError("创建响应未确认且无法唯一关联新账单任务，已保留原回执",
                                                 "waiting_export", "unknown")
                else:
                    matched = [row for row in current if row["id"] == task["id"]]
                    if len(matched) != 1 or any(matched[0][k] != task[k] for k in ("title", "operationDate", "agentId")):
                        raise BillCollectionError("已确认的导出任务不再唯一，未下载其他记录")
                    task = matched[0]
                if task:
                    if task["agentId"] is not None and str(task["agentId"]) != request.agency_id:
                        raise BillCollectionError("导出任务的城市与请求不符")
                    if task["statusName"] in ("失败", "导出失败"):
                        raise BillCollectionError("平台账单导出失败")
                    if task["statusName"] == "导出成功":
                        if type(task.get("status")) is not int or task["status"] != 2:
                            raise BillCollectionError("平台成功状态码与已核实协议不一致")
                        self.client.assert_city(request.agency_id)
                        phase = "downloading"
                        url = self.client.daily_file_url(task["id"], request.agency_id)
                        file = self.client.download(url, raw / "daily-bill.zip")
                        phase = "validating"
                        info = validate_bill_file(file)
                        manifest.update(status="success", files=[{"path": file.name, **info}])
                        atomic_json(path, manifest)
                        return manifest
                self.client.cancelled.wait(min(self.poll_interval, max(0, deadline - time.monotonic())))
            raise BillCollectionError("等待本次账单导出超时，已保留原任务，不会重复导出")
        except Exception as exc:
            manifest.update(status="failed", failure_phase=phase, submission_state=submission)
            atomic_json(path, manifest)
            if isinstance(exc, BillCollectionError):
                exc.download_failure_phase = phase
                exc.download_submission_state = submission
                raise
            raise HttpTransportError("接口采集未完成，已保留本次记录", phase, submission) from None

    def resume_daily(self, plan, raw, selected, source_dir):
        """Download a uniquely matched original task; never submit an export."""
        if not selected or not set(selected) <= {"delivery_fee", "penalty"}:
            raise HttpTransportError("日账单恢复资料范围无效", "preparing", "unknown")
        source, raw = Path(source_dir).resolve(), Path(raw)
        try:
            ledger = json.loads((source / "http_submission.json").read_text(encoding="utf-8"))
            baseline = json.loads((source / "http_baseline.json").read_text(encoding="utf-8"))["task_ids"]
            scope = ledger["scope"]
            started = ledger["started_at"]
        except (OSError, ValueError, KeyError, TypeError):
            raise HttpTransportError("原日账单提交凭据不完整，未重新提交", "waiting_export", "unknown") from None
        if (scope.get("agency_id") != plan.agency_id or scope.get("start") != plan.start
                or scope.get("end") != plan.end or not set(selected) <= set(scope.get("datasets", []))
                or ledger.get("transport") != "http" or not isinstance(started, (int, float))
                or isinstance(started, bool) or not isinstance(baseline, list) or len(baseline) > 100
                or any(type(value) is not int or value <= 0 for value in baseline)
                or len(set(baseline)) != len(baseline)):
            raise HttpTransportError("原日账单城市、日期或任务基线不符，未重新提交", "waiting_export", "unknown")
        request = BillRequest(plan.start, plan.end, False, False, plan.agency_id,
                              sub_bill_types=tuple(v for v, k in ((1, "delivery_fee"), (2, "penalty")) if k in selected))
        raw.mkdir(parents=True, exist_ok=True)
        manifest = {"platform": "fengshen", "transport": "http", "dataset": "agency_daily",
                    "agency_id": request.agency_id, "start": request.start, "end": request.end,
                    "status": "waiting_for_original_task", "files": [], "recovery_only": True}
        path = raw / "manifest.json"
        atomic_json(path, manifest)
        phase = "waiting_export"
        try:
            self.client.select_city(request.agency_id)
            deadline, task = time.monotonic() + self.timeout, None
            previous = [{"id": value} for value in baseline]
            while time.monotonic() < deadline:
                self.client.checkpoint()
                current = self._tasks(request.agency_id)
                if task is None:
                    task = new_daily_task(previous, current, request, started, started + 60)
                    if task is not None:
                        manifest["task_id"] = str(task["id"])
                        atomic_json(path, manifest)
                else:
                    matched = [row for row in current if row["id"] == task["id"]]
                    if len(matched) != 1 or any(matched[0][k] != task[k] for k in ("title", "operationDate", "agentId")):
                        raise BillCollectionError("原日账单任务身份发生变化，未下载其他记录")
                    task = matched[0]
                if task is not None:
                    if task.get("agentId") not in (None, int(request.agency_id)):
                        raise BillCollectionError("原日账单任务城市不符")
                    if task["statusName"] in ("失败", "导出失败"):
                        raise BillCollectionError("原日账单平台导出失败")
                    if task["statusName"] == "导出成功":
                        if type(task.get("status")) is not int or task["status"] != 2:
                            raise BillCollectionError("原日账单成功状态码无效")
                        self.client.assert_city(request.agency_id)
                        phase = "downloading"
                        url = self.client.daily_file_url(task["id"], request.agency_id)
                        file = self.client.download(url, raw / "daily-bill.zip")
                        phase = "validating"
                        proof = validate_bill_file(file)
                        manifest.update(status="success", files=[{"path": file.name, **proof}])
                        atomic_json(path, manifest)
                        return manifest
                self.client.cancelled.wait(min(self.poll_interval, max(0, deadline - time.monotonic())))
            raise BillCollectionError("原日账单任务仍未完成，已保留编号")
        except Exception as exc:
            manifest.update(status="failed", failure_phase=phase, submission_state="submitted")
            atomic_json(path, manifest)
            if isinstance(exc, BillCollectionError):
                exc.download_failure_phase = phase
                exc.download_submission_state = "submitted"
                raise
            raise HttpTransportError("原日账单恢复未完成，未重新提交", phase, "submitted") from None
