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
            return {"result": {"data": {"data": [dict(task) for task in self.tasks]}}}
        if url == EXPORT_URL:
            self.exports += 1
            if self.export_error:
                raise self.export_error
            for _ in range(2 if self.ambiguous else 1):
                self.tasks.append({"id": len(self.tasks) + 1, "fileName": "运单", "exportTime": int(time.time()*1000),
                                   "status": 1, "statusDesc": "导出成功"})
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

    def test_six_day_range_splits_five_plus_one(self):
        self.fixture.total = 0
        self.plan.start = (dt.date.fromisoformat(self.plan.end) - dt.timedelta(days=5)).isoformat()
        reports = self.collector.orders(self.plan, self.root, {"fraud"})
        self.assertEqual(len(reports), 2)
        self.assertEqual(len(reports[0]["expected_waybills_by_date"]), 5)
        self.assertEqual(len(reports[1]["expected_waybills_by_date"]), 1)
        self.assertEqual(reports[0]["start"], self.plan.start)
        self.assertEqual(reports[1]["end"], self.plan.end)
        self.assertEqual(self.fixture.exports, 0)

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
