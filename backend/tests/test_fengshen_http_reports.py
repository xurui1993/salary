import datetime as dt
import csv as csv_module
import json
from pathlib import Path
import sys
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

from openpyxl import Workbook

sys.path.insert(0, str(Path(__file__).parents[1]))
from fengshen_bill import BillCollectionError, MONTHLY_EXPORT_URL, MONTHLY_QUERY_URL, MonthlyBillRequest
from fengshen_http import FengshenHttpClient, HttpTransportError
from fengshen_http_reports import ReportHttpCollector, monthly_body, monthly_count
from fengshen_orders import (
    ENUMERATE_URL, ALL_CITY_SEND_PRODUCT, EXPORT_URL, QUERY_URL, TASKS_URL, TASK_URL,
    VIOLATIONS_URL, SHANGHAI, secure_file_url,
)
from order_sources import prepare_order_files


class ProtocolFixture:
    """Real submission ledger, deterministic platform responses, no network."""
    def __init__(self):
        self.client = FengshenHttpClient()
        self.client.select_city = Mock()
        self.client.assert_city = Mock()
        self.client.request_json = Mock(side_effect=self.request)
        self.client.download = Mock(side_effect=self.download)
        self.total = 1
        self.tasks = []
        self.ambiguous = False
        self.monthly_valid = True
        self.monthly_row = {"agencyId": 2, "billCycle": "2026-09", "bizType": 3}
        self.monthly_pages = []
        self.order_agency = 2
        self.exports = 0
        self.export_error = None
        self.products = {"6865": ALL_CITY_SEND_PRODUCT, "44": "饿了么-蜂鸟专送", "8281": "淘宝全城送"}
        self.hold_until_exports = 0
        self.fail_first_after_two = False
        self.downloads_at_second_export = None

    def request(self, method, url, *, body=None, params=None):
        assert method == "POST"
        if url == ENUMERATE_URL:
            return {"result": {"data": {"product": dict(self.products)}}}
        if url == MONTHLY_QUERY_URL:
            rows = [self.monthly_pages.pop(0)] if self.monthly_pages else [self.monthly_row]
            return {"result": {"total": 1, "data": rows}}
        if url == MONTHLY_EXPORT_URL:
            self.exports += 1
            return {"result": {"data": {"validRes": self.monthly_valid, "fileUrl": "https://files.ele.me/bill"}}}
        if url == QUERY_URL:
            return {"result": {"data": {"total": self.total,
                    "data": [{"agencyId": self.order_agency}] if self.total else []}}}
        if url == TASKS_URL:
            rows = []
            for task in self.tasks:
                row = dict(task)
                if self.hold_until_exports and self.exports < self.hold_until_exports:
                    row["statusDesc"] = "生成中"
                elif self.fail_first_after_two and self.exports >= 2 and row["id"] == 1:
                    row["statusDesc"] = "导出失败"
                rows.append(row)
            return {"result": {"data": {"data": rows}}}
        if url == EXPORT_URL:
            self.exports += 1
            if self.export_error:
                raise self.export_error
            for _ in range(2 if self.ambiguous else 1):
                self.tasks.append({"id": len(self.tasks) + 1, "fileName": "运单", "exportTime": int(time.time()*1000),
                                   "status": 1, "statusDesc": "导出成功"})
            if self.exports == 2:
                self.downloads_at_second_export = self.client.download.call_count
            return {"result": {"code": "200"}}
        if url == TASK_URL:
            return {"result": {"data": "https://files.ele.me/waybills"}}
        if url == VIOLATIONS_URL:
            return {"result": {"data": {"fileUrl": ""}}}
        raise AssertionError(url)

    @staticmethod
    def download(url, target):
        workbook = Workbook()
        workbook.active.append(["原始表头", "金额"])
        workbook.save(target)
        workbook.close()
        return target


class ReportTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=Path(__file__).parent)
        self.root = Path(self.temp.name)
        self.fixture = ProtocolFixture()
        self.client = self.fixture.client
        self.collector = ReportHttpCollector(self.client, poll_interval=.001, timeout=.05)
        self.collector.scope_recheck_delay = 0
        today = dt.datetime.now(SHANGHAI).date()
        self.plan = SimpleNamespace(agency_id="2", city="泉州", month="2026-09",
                                   start=(today-dt.timedelta(days=1)).isoformat(), end=(today-dt.timedelta(days=1)).isoformat())

    def tearDown(self):
        self.client.close()
        self.temp.cleanup()

    def test_monthly_uses_full_calendar_month_and_all_teams_statuses(self):
        request = MonthlyBillRequest("2024-02")
        body = monthly_body(request)["params"]["request"]
        self.assertEqual(request.end, "2024-02-29")
        self.assertEqual(body, {"bizType": 3, "billCycle": "2024-02", "teamIds": None,
                               "settleStatusList": [], "pageNum": 1, "pageSize": 10})

    def test_monthly_success_keeps_original_file_with_checksum(self):
        result = self.collector.monthly(self.plan, self.root)
        self.assertEqual((result["start"], result["end"]), ("2026-09-01", "2026-09-30"))
        self.assertEqual(result["expected_rows"], 1)
        self.assertEqual(result["status"], "success")
        self.assertEqual(len(result["files"][0]["sha256"]), 64)
        self.assertTrue((self.root / result["files"][0]["path"]).is_file())
        query = self.client.request_json.call_args_list[0].kwargs["body"]
        export = self.client.request_json.call_args_list[1].kwargs["body"]
        self.assertEqual(query, export)

    def test_monthly_accepts_platform_full_month_label(self):
        self.fixture.monthly_row["billCycle"] = "2026-09-01至2026-09-30"
        self.assertEqual(self.collector.monthly(self.plan, self.root)["status"], "success")

    def test_single_day_queries_count_only_once(self):
        self.fixture.total = 0
        self.collector.orders(self.plan, self.root, {"fraud"})
        queries = [call for call in self.client.request_json.call_args_list if call.args[1] == QUERY_URL]
        self.assertEqual(len(queries), 1)

    def test_live_export_records_after_count_and_legacy_resume_only_queries(self):
        self.plan.start = self.plan.end = dt.datetime.now(SHANGHAI).date().isoformat()
        original_download = self.fixture.download
        def download(url, target):
            result = original_download(url, target)
            self.fixture.total = 2
            return result
        self.client.download.side_effect = download
        source = self.root / 'live'
        manifest = self.collector.orders(self.plan, source, {'fraud'})[0]
        snapshot = manifest['live_day_snapshot']
        self.assertEqual((snapshot['before'], snapshot['after'], snapshot['task_id']), (1, 2, manifest['task_id']))
        query_path = next(source.glob('*/query_state.json'))
        query = json.loads(query_path.read_text(encoding='utf-8'))
        self.assertEqual(query.pop('live_day_snapshot'), snapshot)
        query_path.write_text(json.dumps(query), encoding='utf-8')
        self.fixture.total = 3
        resumed = self.collector.resume_orders(self.plan, self.root / 'resumed_live', {'fraud'}, source)[0]
        self.assertEqual(resumed['live_day_snapshot']['after'], 3)
        self.assertEqual(self.fixture.exports, 1)

    def test_recovery_reuses_retained_waybills_without_export(self):
        source = self.root / "original"
        self.collector.orders(self.plan, source, {"fraud"})
        exports = self.fixture.exports
        self.client.request_json.reset_mock()
        result = self.collector.resume_orders(self.plan, self.root / "restored", {"fraud"}, source)
        self.assertTrue(result[0]["recovery_only"])
        self.assertEqual(exports, self.fixture.exports)
        self.client.request_json.assert_not_called()
        query_path = next(source.glob("*/query_state.json"))
        query = json.loads(query_path.read_text(encoding="utf-8"))
        query["expected_waybills"] += 1
        query_path.write_text(json.dumps(query), encoding="utf-8")
        # Recovery retains both counts; downstream validation proves each day.
        recovered = self.collector.resume_orders(self.plan, self.root / "daily_basis", {"fraud"}, source)
        self.assertEqual(recovered[0]["expected_waybills"], query["expected_waybills"])
        task_path = next(source.glob("*/task.json"))
        task = json.loads(task_path.read_text(encoding="utf-8"))
        task["agency_id"] = "9"
        task_path.write_text(json.dumps(task), encoding="utf-8")
        with self.assertRaises(BillCollectionError):
            self.collector.resume_orders(self.plan, self.root / "bad", {"fraud"}, source)

    def test_observed_zhangjiakou_legacy_host_requires_https(self):
        host = "lpd-cs-delivery-ext-zbprod-zb1-oss-1.oss-cn-zhangjiakou.aliyuncs.com"
        self.assertEqual(secure_file_url("http://" + host + "/file?x=1"), "https://" + host + "/file?x=1")
        with self.assertRaises(BillCollectionError):
            secure_file_url("http://other.aliyuncs.com/file")

    def test_monthly_invalid_scope_stops_before_export(self):
        for field, value in (("agencyId", 9), ("billCycle", "2026-08"), ("bizType", 2)):
            with self.subTest(field=field):
                row = dict(self.fixture.monthly_row, **{field: value})
                with self.assertRaises(BillCollectionError):
                    monthly_count({"result": {"total": 1, "data": [row]}}, MonthlyBillRequest(self.plan.month), "2")
        self.fixture.monthly_row["agencyId"] = 9
        with self.assertRaises(BillCollectionError) as raised:
            self.collector.monthly(self.plan, self.root)
        self.assertIn("agencyId", str(raised.exception))
        self.assertEqual(self.fixture.exports, 0)
        queries = [call for call in self.client.request_json.call_args_list if call.args[1] == MONTHLY_QUERY_URL]
        self.assertEqual(len(queries), 3)

    def test_monthly_scope_mismatch_rechecks_read_only_query_once(self):
        # Observed 2026-10-22: right after a city switch the platform briefly
        # returned another agency's page; the identical read succeeded later.
        self.fixture.monthly_pages = [dict(self.fixture.monthly_row, agencyId=9)]
        result = self.collector.monthly(self.plan, self.root)
        self.assertEqual(result["status"], "success")
        queries = [call for call in self.client.request_json.call_args_list if call.args[1] == MONTHLY_QUERY_URL]
        self.assertEqual(len(queries), 2)
        self.assertEqual(self.fixture.exports, 1)

    def test_monthly_rejected_export_never_creates_second_submission(self):
        self.fixture.monthly_valid = False
        for _ in range(2):
            with self.assertRaises(BillCollectionError): self.collector.monthly(self.plan, self.root)
        self.assertEqual(self.fixture.exports, 1)
        self.client.download.assert_not_called()

    def test_monthly_empty_records_require_consistent_total(self):
        request = MonthlyBillRequest(self.plan.month)
        self.assertEqual(monthly_count({"result": {"total": 0, "data": []}}, request, "2"), 0)
        for invalid in (True, -1, "0", None):
            with self.subTest(total=invalid), self.assertRaises(BillCollectionError):
                monthly_count({"result": {"total": invalid, "data": []}}, request, "2")
        with self.assertRaises(BillCollectionError):
            monthly_count({"result": {"total": 0, "data": [self.fixture.monthly_row]}}, request, "2")

    def test_fraud_uses_completed_dates_and_does_not_export_violations(self):
        result = self.collector.orders(self.plan, self.root, {"fraud"})
        self.assertEqual(len(result), 1)
        self.assertEqual(set(result[0]["files"]), {"waybills"})
        self.assertEqual(result[0]["task_id"], "1")
        calls = self.client.request_json.call_args_list
        self.assertNotIn(VIOLATIONS_URL, [call.args[1] for call in calls])
        body = next(call.kwargs["body"]["params"]["request"] for call in calls if call.args[1] == EXPORT_URL)
        self.assertEqual(body["exportType"], 1)
        self.assertEqual(body["trackingStateKey"], "all")
        self.assertEqual(body["trackingLabelKey"], "all")
        self.assertEqual(body["trackingFinishTimePeriodList"], ["0-86400"])
        self.assertEqual(body["trackingFinishEnd"] - body["trackingFinishStart"], 86399000)
        self.assertNotIn("knightIds", body)

    def test_problem_uses_same_period_for_violations(self):
        result = self.collector.orders(self.plan, self.root, {"problem"})
        self.assertEqual(set(result[0]["files"]), {"waybills", "violations"})
        self.assertTrue(result[0]["file_checks"]["violations"]["platform_confirmed_empty"])
        calls = self.client.request_json.call_args_list
        order = next(c.kwargs["body"]["params"]["request"] for c in calls if c.args[1] == EXPORT_URL)
        violation = next(c.kwargs["body"]["params"]["request"] for c in calls if c.args[1] == VIOLATIONS_URL)
        self.assertEqual(violation, {"violationStartTime": order["trackingFinishStart"],
                                    "violationEndTime": order["trackingFinishEnd"], "appealStatus": []})

    def test_empty_city_data_preserves_downstream_manifest_contract(self):
        self.fixture.total = 0
        raw, generated = self.root / "raw", self.root / "processed"
        generated.mkdir()
        reports = self.collector.orders(self.plan, raw / "issue_orders", {"fraud", "problem"})
        outcome = prepare_order_files(reports, raw, generated, self.plan, [(self.plan.start, self.plan.end)])
        self.assertEqual(outcome["欺诈单"]["rows"], 0)
        self.assertEqual(outcome["问题单"]["rows"], 0)
        self.assertFalse(outcome["欺诈单"]["filtered_by_applicants"])
        self.assertEqual(self.fixture.exports, 0)

    def test_eight_day_range_splits_seven_plus_one(self):
        self.fixture.total = 0
        self.plan.start = (dt.date.fromisoformat(self.plan.end) - dt.timedelta(days=7)).isoformat()
        reports = self.collector.orders(self.plan, self.root, {"fraud"})
        self.assertEqual(len(reports), 2)
        self.assertEqual(len(reports[0]["expected_waybills_by_date"]), 7)
        self.assertEqual(len(reports[1]["expected_waybills_by_date"]), 1)
        self.assertEqual(reports[0]["start"], self.plan.start)
        self.assertEqual(reports[1]["end"], self.plan.end)
        self.assertEqual(self.fixture.exports, 0)

    def test_corrupt_waybill_download_is_fetched_once_more(self):
        original = ProtocolFixture.download
        calls = []
        def download(url, target):
            calls.append(target)
            if len(calls) == 1:
                Path(target).write_bytes(b"not a zip")
                return target
            return original(url, target)
        self.client.download.side_effect = download
        reports = list(self.collector.orders_stream(self.plan, self.root, {"problem"}))
        self.assertEqual(len(reports), 1)
        self.assertEqual(reports[0]["status"], "success")
        self.assertEqual(len(calls), 2)
        self.assertEqual(reports[0]["expected_waybills"], 1)

    def test_concurrent_exports_start_before_the_first_download(self):
        self.fixture.hold_until_exports = 2
        self.plan.start = (dt.date.fromisoformat(self.plan.end) - dt.timedelta(days=11)).isoformat()
        reports = list(self.collector.orders_stream(self.plan, self.root, {"fraud"}, concurrency=2))
        self.assertEqual(self.fixture.exports, 2)
        self.assertEqual(self.fixture.downloads_at_second_export, 0)
        self.assertEqual(len(reports), 2)
        self.assertEqual([report["task_id"] for report in reports], ["1", "2"])
        self.assertEqual([report["start"] for report in reports], sorted(report["start"] for report in reports))

    def test_serial_mode_downloads_the_first_batch_before_submitting_the_second(self):
        self.plan.start = (dt.date.fromisoformat(self.plan.end) - dt.timedelta(days=11)).isoformat()
        reports = list(self.collector.orders_stream(self.plan, self.root, {"fraud"}, concurrency=1))
        self.assertEqual(self.fixture.exports, 2)
        self.assertEqual(self.fixture.downloads_at_second_export, 1)
        self.assertEqual(len(reports), 2)

    def test_failure_with_two_exports_retains_both_receipts_and_interrupts_the_other(self):
        self.fixture.hold_until_exports = 2
        self.fixture.fail_first_after_two = True
        self.plan.start = (dt.date.fromisoformat(self.plan.end) - dt.timedelta(days=11)).isoformat()
        with self.assertRaises(BillCollectionError):
            list(self.collector.orders_stream(self.plan, self.root, {"fraud"}, concurrency=2))
        self.assertEqual(self.fixture.exports, 2)
        manifests = {json.loads(path.read_text(encoding="utf-8"))["start"]:
                     json.loads(path.read_text(encoding="utf-8"))
                     for path in self.root.glob("*/manifest.json")}
        self.assertEqual(len(manifests), 2)
        self.assertEqual({value["status"] for value in manifests.values()}, {"failed", "interrupted"})
        self.assertEqual(len(list(self.root.glob("*/http_submission.json"))), 2)
        with self.assertRaises(HttpTransportError):
            list(self.collector.orders_stream(self.plan, self.root, {"fraud"}, concurrency=2))

    def test_foreign_city_response_never_exports(self):
        self.fixture.order_agency = 9
        with self.assertRaises(BillCollectionError): self.collector.orders(self.plan, self.root, {"fraud"})
        self.assertEqual(self.fixture.exports, 0)
        self.client.download.assert_not_called()

    def test_ambiguous_new_task_is_not_downloaded_or_resubmitted(self):
        self.fixture.ambiguous = True
        for _ in range(2):
            with self.assertRaises(BillCollectionError): self.collector.orders(self.plan, self.root, {"fraud"})
        self.assertEqual(self.fixture.exports, 1)
        self.client.download.assert_not_called()

    def test_network_failure_preserves_unknown_ledger_and_no_duplicate(self):
        self.fixture.export_error = TimeoutError("private-token")
        for _ in range(2):
            with self.assertRaises(BillCollectionError) as error:
                self.collector.orders(self.plan, self.root, {"fraud"})
            self.assertEqual(error.exception.download_submission_state, "unknown")
            self.assertNotIn("private-token", str(error.exception))
        ledger = next(self.root.rglob("http_submission.json"))
        self.assertEqual(json.loads(ledger.read_text())["submission_state"], "unknown")
        self.assertNotIn("private-token", ledger.read_text())
        self.assertEqual(self.fixture.exports, 1)

    def test_download_failure_keeps_task_id_and_never_reexports(self):
        self.client.download.side_effect = HttpTransportError("文件连接中断", "downloading", "submitted")
        for _ in range(2):
            with self.assertRaises(BillCollectionError): self.collector.orders(self.plan, self.root, {"fraud"})
        task = json.loads(next(self.root.rglob("task.json")).read_text())
        self.assertEqual(task["task_id"], "1")
        self.assertEqual(self.fixture.exports, 1)

    def test_bad_success_status_stops_download(self):
        original = self.fixture.request
        def changed(method, url, **kwargs):
            result = original(method, url, **kwargs)
            if url == TASKS_URL:
                for row in result["result"]["data"]["data"]: row["status"] = True
            return result
        self.client.request_json.side_effect = changed
        with self.assertRaises(BillCollectionError): self.collector.orders(self.plan, self.root, {"fraud"})
        self.client.download.assert_not_called()

    def test_html_file_is_not_published_as_workbook(self):
        def html(url, path):
            path.write_text("<html>login required</html>")
            return path
        self.client.download.side_effect = html
        with self.assertRaises(BillCollectionError): self.collector.orders(self.plan, self.root, {"fraud"})
        manifest = json.loads(next(self.root.rglob("manifest.json")).read_text(encoding="utf-8"))
        self.assertEqual(manifest["status"], "failed")
        self.assertNotIn("files", manifest)

    def test_old_or_future_period_never_calls_network(self):
        today = dt.datetime.now(SHANGHAI).date()
        for day in (today-dt.timedelta(days=60), today+dt.timedelta(days=1)):
            self.plan.start = self.plan.end = day.isoformat()
            with self.assertRaises(BillCollectionError): self.collector.orders(self.plan, self.root, {"fraud"})
        self.client.request_json.assert_not_called()

    def test_cancelled_before_batch_never_calls_network(self):
        self.client.cancelled.set()
        with self.assertRaises(BillCollectionError): self.collector.orders(self.plan, self.root, {"fraud"})
        self.client.request_json.assert_not_called()

    def test_large_batch_adaptively_splits_and_recovers(self):
        self.fixture.total = 400_000
        self.plan.start = (dt.date.fromisoformat(self.plan.end) - dt.timedelta(days=6)).isoformat()
        source = self.root / "split_source"
        self.collector.export_interval = 0.02
        self.fixture.hold_until_exports = 2
        reports = list(self.collector.orders_stream(self.plan, source, {"problem"}, concurrency=2))
        self.assertEqual(len(reports), 3)
        self.assertEqual(sum(len(r["expected_waybills_by_date"]) for r in reports), 7)
        self.assertEqual(reports[0]["start"], self.plan.start)
        self.assertEqual(reports[-1]["end"], self.plan.end)
        recovered = self.collector.resume_orders(self.plan, self.root / "split_recovered", {"problem"}, source)
        self.assertEqual([(r["start"], r["end"]) for r in recovered],
                         [(r["start"], r["end"]) for r in reports])

    def test_transient_task_url_biz_error_reselects_city_and_recovers(self):
        original = self.fixture.request
        task_url_calls = []
        def flaky_task_url(method, url, **kwargs):
            if url == TASK_URL:
                task_url_calls.append(1)
                if len(task_url_calls) == 1:
                    raise BillCollectionError("平台拒绝导出，请检查登录状态和账单权限")
            return original(method, url, **kwargs)
        self.client.request_json.side_effect = flaky_task_url
        reports = list(self.collector.orders_stream(self.plan, self.root / "flaky_url", {"problem"}))
        self.assertEqual(len(reports), 1)
        self.assertEqual(reports[0]["status"], "success")
        self.assertEqual(len(task_url_calls), 2)
        self.assertEqual(self.fixture.exports, 1)

    def test_matching_xlsx_rows_skips_daily_queries_and_recovers_and_prepares(self):
        from test_fengshen_orders import waybill, WAYBILL_COLUMNS
        self.fixture.total = 2
        d1 = (dt.date.fromisoformat(self.plan.end) - dt.timedelta(days=6)).isoformat()
        d2 = self.plan.end
        self.plan.start = d1
        cols = sorted(WAYBILL_COLUMNS)
        r1 = dict(waybill(waybill_id="W1"), 运单完成时间=d1 + " 10:00:00")
        r2 = dict(waybill(waybill_id="W2"), 运单完成时间=d2 + " 11:00:00")
        def write_matching_xlsx(url, target):
            wb = Workbook()
            ws = wb.active
            ws.append(cols)
            for row in (r1, r2):
                ws.append([row.get(c, "") for c in cols])
            wb.save(target)
            wb.close()
            return target
        self.client.download.side_effect = write_matching_xlsx
        raw_dir = self.root / "raw_skip"
        out_dir = self.root / "out_skip"
        out_dir.mkdir()
        reports = list(self.collector.orders_stream(self.plan, raw_dir / "issue_orders", {"problem"}, concurrency=2))
        self.assertEqual(len(reports), 1)
        self.assertIsNone(reports[0]["expected_waybills_by_date"])
        self.assertEqual(reports[0]["count_basis"], "batch_total")
        queries = [call for call in self.client.request_json.call_args_list if call.args[1] == QUERY_URL]
        self.assertEqual(len(queries), 1)
        outcome = prepare_order_files(reports, raw_dir, out_dir, self.plan, [(d1, d2)], selected_kinds={"问题单"})
        self.assertIn("问题单", outcome)
        self.client.request_json.reset_mock()
        recovered = self.collector.resume_orders(self.plan, self.root / "recovered_skip" / "issue_orders",
                                                 {"problem"}, raw_dir / "issue_orders")
        self.assertEqual(len(recovered), 1)
        self.assertIsNone(recovered[0]["expected_waybills_by_date"])
        self.assertEqual(recovered[0]["count_basis"], "batch_total")
        self.client.request_json.assert_not_called()

    def test_mismatching_xlsx_rows_falls_back_to_daily_queries(self):
        self.fixture.total = 3
        self.plan.start = (dt.date.fromisoformat(self.plan.end) - dt.timedelta(days=3)).isoformat()
        reports = list(self.collector.orders_stream(self.plan, self.root / "mismatch", {"fraud"}, concurrency=2))
        self.assertEqual(len(reports), 1)
        self.assertEqual(len(reports[0]["expected_waybills_by_date"]), 4)
        queries = [call for call in self.client.request_json.call_args_list if call.args[1] == QUERY_URL]
        self.assertEqual(len(queries), 5)

    def test_parallel_isolated_downloads_free_export_slot_immediately(self):
        import threading
        self.fixture.total = 1
        self.plan.start = (dt.date.fromisoformat(self.plan.end) - dt.timedelta(days=15)).isoformat()
        release_first_download = threading.Event()
        first_download_started = threading.Event()
        exports_when_first_blocked = []
        dl_lock = threading.Lock()
        dl_count = [0]
        def isolated_download(url, target):
            with dl_lock:
                dl_count[0] += 1
                idx = dl_count[0]
            if idx == 1:
                first_download_started.set()
                release_first_download.wait(timeout=2.0)
            wb = Workbook()
            ws = wb.active
            ws.append(["原始表头", "金额"])
            ws.append(["A", 1])
            wb.save(target)
            wb.close()
            return target
        orig_request = self.fixture.request
        def tracked_request(method, url, **kwargs):
            res = orig_request(method, url, **kwargs)
            if url == EXPORT_URL and self.fixture.exports == 3:
                exports_when_first_blocked.append(release_first_download.is_set())
                release_first_download.set()
            return res
        self.client.request_json.side_effect = tracked_request
        self.client.download_isolated = Mock(side_effect=isolated_download)
        reports = list(self.collector.orders_stream(self.plan, self.root / "parallel_oss", {"fraud"}, concurrency=2))
        self.assertEqual(len(reports), 3)
        self.assertEqual(exports_when_first_blocked, [False])
        for report in reports:
            if report["start"] < report["end"]:
                self.assertIsNone(report["expected_waybills_by_date"])
                self.assertEqual(report["count_basis"], "batch_total")

    def test_validate_bill_file_counts_xlsx_rows_across_tiny_chunk_boundaries(self):
        from fengshen_bill import validate_bill_file
        import zipfile
        xlsx_path = self.root / "rows_check.xlsx"
        wb = Workbook()
        ws = wb.active
        ws.append(["col1", "col2"])
        for i in range(17):
            ws.append([f"v{i}", i])
        wb.save(xlsx_path)
        wb.close()
        orig_open = zipfile.ZipFile.open
        class TinyStream:
            def __init__(self, inner):
                self.inner = inner
            def __enter__(self):
                self.inner.__enter__()
                return self
            def __exit__(self, *args):
                return self.inner.__exit__(*args)
            def read(self, _n=-1):
                return self.inner.read(3)
        def tiny_open(zf_self, name, mode="r", *args, **kwargs):
            return TinyStream(orig_open(zf_self, name, mode, *args, **kwargs))
        with unittest.mock.patch.object(zipfile.ZipFile, "open", tiny_open):
            proof = validate_bill_file(xlsx_path)
        self.assertEqual(proof["xlsx_data_rows"], 17)

    def test_oss_404_and_delayed_task_url_recover_in_async_stream(self):
        calls = {"task": 0, "dl": 0}
        orig_req = self.fixture.request
        def delayed_req(method, url, **kwargs):
            if url == TASK_URL:
                calls["task"] += 1
                if calls["task"] <= 2:
                    raise BillCollectionError("平台拒绝导出，请检查登录状态和账单权限")
            return orig_req(method, url, **kwargs)
        def delayed_dl(url, target):
            calls["dl"] += 1
            if calls["dl"] == 1:
                raise HttpTransportError("平台文件下载失败（HTTP 404）", "downloading", "submitted")
            wb = Workbook()
            ws = wb.active
            ws.append(["原始表头", "金额"])
            ws.append(["A", 1])
            wb.save(target)
            wb.close()
            return target
        self.client.request_json.side_effect = delayed_req
        self.client.download_isolated = Mock(side_effect=delayed_dl)
        reports = list(self.collector.orders_stream(self.plan, self.root / "oss404", {"problem"}, concurrency=3))
        self.assertEqual(len(reports), 1)
        self.assertEqual(reports[0]["status"], "success")
        self.assertGreaterEqual(calls["task"], 4)
        self.assertEqual(calls["dl"], 2)


class WaybillCreatedTests(unittest.TestCase):
    """运单数据按运单终态时间采集：请求键、回执口径、全城送筛选与空结果契约。"""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=Path(__file__).parent)
        self.root = Path(self.temp.name)
        self.fixture = ProtocolFixture()
        self.client = self.fixture.client
        self.fixture.total = 2
        self.collector = ReportHttpCollector(self.client, poll_interval=.001, timeout=.05)
        self.collector.scope_recheck_delay = 0
        today = dt.datetime.now(SHANGHAI).date()
        self.plan = SimpleNamespace(agency_id="2", city="泉州",
                                    start=(today-dt.timedelta(days=3)).isoformat(),
                                    end=(today-dt.timedelta(days=2)).isoformat())

    def tearDown(self):
        self.client.close()
        self.temp.cleanup()

    def bodies(self, url):
        return [call.kwargs["body"] for call in self.client.request_json.call_args_list
                if call.args[1] == url]

    def test_finish_basis_uses_tracking_finish_keys_and_receipt(self):
        result = self.collector.waybills_created(self.plan, self.root / "raw")
        self.assertEqual(len(result), 1)
        manifest = result[0]
        self.assertEqual(manifest["dataset"], "delivery_waybill")
        self.assertEqual(manifest["time_basis"], "tracking_finish")
        self.assertEqual(manifest["status"], "success")
        self.assertEqual(len(manifest["files"]), 1)
        self.assertIn("waybills_created.xlsx", manifest["files"][0]["path"])
        query = self.bodies(QUERY_URL)[0]["params"]["request"]
        self.assertIn("trackingFinishStart", query)
        self.assertIn("trackingFinishEnd", query)
        self.assertIn("trackingFinishTimePeriodList", query)
        self.assertNotIn("trackingCreatedStart", query)
        export = self.bodies(EXPORT_URL)[0]["params"]["request"]
        self.assertEqual(export["exportType"], 1)
        self.assertIn("trackingFinishStart", export)
        receipt = json.loads(next(self.root.rglob("http_submission.json")).read_text(encoding="utf-8"))
        self.assertEqual(receipt["scope"]["dataset"], "delivery_waybill")
        task = json.loads(next(self.root.rglob("task.json")).read_text(encoding="utf-8"))
        self.assertEqual(task["time_basis"], "tracking_finish")

    def test_created_basis_remains_available_for_legacy_recovery(self):
        result = self.collector.waybills_created(self.plan, self.root / "raw", time_basis="tracking_created")
        manifest = result[0]
        self.assertEqual(manifest["time_basis"], "tracking_created")
        query = self.bodies(QUERY_URL)[0]["params"]["request"]
        self.assertIn("trackingCreatedStart", query)
        self.assertNotIn("trackingFinishStart", query)
        task = json.loads(next(self.root.rglob("task.json")).read_text(encoding="utf-8"))
        self.assertEqual(task["time_basis"], "tracking_created")

    def test_all_city_send_filters_queries_and_is_recorded(self):
        result = self.collector.waybills_created(self.plan, self.root / "raw", all_city_send=True)
        manifest = result[0]
        self.assertTrue(manifest["all_city_send"])
        self.assertEqual(manifest["all_city_send_product_id"], 6865)
        expected = [call.kwargs["body"]["params"]["request"] for call in self.client.request_json.call_args_list
                    if call.args[1] in (QUERY_URL, EXPORT_URL)]
        self.assertTrue(expected)
        for body in expected:
            self.assertEqual(body["productIdList"], [6865])
        self.assertEqual(self.client.request_json.call_count >= 2, True)
        enumerate_calls = [call for call in self.client.request_json.call_args_list
                           if call.args[1] == ENUMERATE_URL]
        self.assertEqual(len(enumerate_calls), 1)

    def test_all_city_send_without_unique_product_stops_before_submit(self):
        self.fixture.products = {"8281": "淘宝全城送"}
        with self.assertRaises(BillCollectionError):
            self.collector.waybills_created(self.plan, self.root / "raw", all_city_send=True)
        exports = [call for call in self.client.request_json.call_args_list if call.args[1] == EXPORT_URL]
        self.assertEqual(exports, [])

    def test_created_empty_result_writes_header_only_csv(self):
        self.fixture.total = 0
        result = self.collector.waybills_created(self.plan, self.root / "raw")
        info = result[0]["files"][0]
        self.assertEqual(info["path"], "waybills_created_empty.csv")
        self.assertTrue(info["platform_confirmed_empty"])
        from waybill_workbook import WAYBILL_TITLES
        with next(self.root.rglob(info["path"])).open(encoding="utf-8-sig", newline="") as stream:
            self.assertEqual(next(csv_module.reader(stream)), sorted(WAYBILL_TITLES))

    def test_created_second_submission_in_same_directory_is_rejected(self):
        self.collector.waybills_created(self.plan, self.root / "raw")
        with self.assertRaises(HttpTransportError):
            self.collector.waybills_created(self.plan, self.root / "raw")

    def test_created_multi_batch_splits_by_date_batches(self):
        today = dt.datetime.now(SHANGHAI).date()
        self.plan.start = (today-dt.timedelta(days=7)).isoformat()
        self.plan.end = (today-dt.timedelta(days=2)).isoformat()
        result = self.collector.waybills_created(self.plan, self.root / "raw")
        self.assertEqual([len(batch["expected_waybills_by_date"]) for batch in result], [5, 1])
        self.assertEqual(len(self.bodies(EXPORT_URL)), 2)


if __name__ == "__main__": unittest.main()
