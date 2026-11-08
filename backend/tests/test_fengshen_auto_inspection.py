import io
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
from contextlib import redirect_stdout

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import fengshen_bill as bill
import test_fengshen_inspection as fixtures


class AutomaticInspectionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=Path(__file__).parent)
        self.root = Path(self.temp.name)
        self.context = fixtures.Context()
        self.page = fixtures.Page(self.context)

    def tearDown(self):
        self.temp.cleanup()

    def download(self, page, content=b"synthetic-report"):
        page.emit("download", SimpleNamespace(suggested_filename="private-name.xlsx",
            save_as=lambda path: Path(path).write_bytes(content)))

    def inspect(self):
        with redirect_stdout(io.StringIO()):
            return bill.inspect_page(self.page, self.root / "capture", finish_on_download=True,
                                     expected_url=bill.BILL_URL)

    def test_download_finishes_without_console_input_and_remains_inspection_only(self):
        self.page.tick = lambda: self.download(self.page)
        with patch("builtins.input", side_effect=AssertionError("Must not read console")):
            output = self.inspect()
        data = json.loads(output.read_text(encoding="utf-8"))
        self.assertTrue(data["inspection_only"])
        self.assertTrue(data["downloads"][0]["source_is_target"])
        self.assertFalse(data["downloads"][0]["validated_for_payroll"])
        progress = json.loads((output.parent / "inspection_progress.json").read_text(encoding="utf-8"))
        self.assertEqual(progress["stage"], "sample_saved")
        controls = json.loads((output.parent / "page_controls_progress.json").read_text(encoding="utf-8"))
        self.assertTrue(controls["inspection_only"])
        self.assertFalse(controls["complete"])
        self.assertNotIn("private-name", json.dumps(data))

    def test_dashboard_redirect_returns_to_report_once(self):
        self.page.url = "https://aeolus.ele.me/#/app/dashboard/index.html"
        self.page.tick = lambda: self.download(self.page)
        self.inspect()
        self.assertEqual(self.page.navigations, [bill.BILL_URL])

    def test_login_wait_does_not_send_sms_or_navigate(self):
        self.page.url = "https://mozi-login.alibaba-inc.com/"
        checkpoint = Mock()
        with self.assertRaisesRegex(bill.BillCollectionError, "30 分钟"):
            bill.wait_for_inspection_download(self.page, [], bill.BILL_URL, checkpoint,
                timeout=1, clock=iter([0, 0, 0, 0, 2]).__next__)
        self.assertFalse(self.page.navigations)
        checkpoint.assert_called_once_with(self.page)

    def test_wrong_report_monthly_download_does_not_finish_daily_capture(self):
        self.page.url = bill.RIDER_BILL_URL
        with self.assertRaisesRegex(bill.BillCollectionError, "不是目标账单页"):
            bill.wait_for_inspection_download(self.page, [{"status": "saved", "source_is_target": True}],
                                              bill.BILL_URL, Mock())

    def test_foreign_popup_download_is_not_attributed_to_open_report(self):
        popup = fixtures.Page(self.context)
        popup.url = "https://foreign.example/"
        self.page.tick = lambda: self.download(popup)
        with self.assertRaisesRegex(bill.BillCollectionError, "不是目标账单页"):
            self.inspect()
        data = json.loads((self.root / "capture" / "inspection_error.json").read_text(encoding="utf-8"))
        self.assertFalse(data["downloads"][0]["source_is_target"])

    def test_download_popup_opener_must_be_target_report(self):
        popup = fixtures.Page(self.context)
        popup.url = "about:blank"
        popup.opener = lambda: self.page
        self.page.tick = lambda: self.download(popup)
        data = json.loads(self.inspect().read_text(encoding="utf-8"))
        self.assertTrue(data["downloads"][0]["source_is_target"])

    def test_empty_file_stops_and_keeps_failure_record(self):
        self.page.tick = lambda: self.download(self.page, b"")
        with self.assertRaisesRegex(bill.BillCollectionError, "未保存完成"):
            self.inspect()
        data = json.loads((self.root / "capture" / "inspection_error.json").read_text(encoding="utf-8"))
        self.assertEqual(data["downloads"][0]["status"], "error")

    def test_closed_browser_stops_without_console(self):
        self.page.closed = True
        with self.assertRaisesRegex(bill.BillCollectionError, "无法唯一"):
            self.inspect()

    def test_transient_frame_navigation_does_not_stop_download_inspection(self):
        self.page.tick = lambda: self.download(self.page)
        original = bill.inspect_page_structure
        with patch.object(bill, "inspect_page_structure", side_effect=[
            RuntimeError("Execution context was destroyed; synthetic-secret"),
            [], original(self.page),
        ]):
            output = self.inspect()
        self.assertTrue(json.loads(output.read_text(encoding="utf-8"))["downloads"])
        for path in output.parent.glob("*.json"):
            self.assertNotIn("synthetic-secret", path.read_text(encoding="utf-8"))

    def test_browser_close_error_has_a_safe_specific_reason(self):
        TargetClosedError = type("TargetClosedError", (Exception,), {})
        self.page.tick = lambda: (_ for _ in ()).throw(TargetClosedError("synthetic-secret"))
        with self.assertRaisesRegex(bill.BillCollectionError, "浏览器已关闭"):
            self.inspect()
        data = json.loads((self.root / "capture" / "inspection_error.json").read_text(encoding="utf-8"))
        self.assertEqual(data["failure_code"], "browser_closed")
        self.assertNotIn("synthetic-secret", json.dumps(data))

    def test_browser_timeout_does_not_expose_exception_details(self):
        self.page.tick = lambda: (_ for _ in ()).throw(TimeoutError("synthetic-secret"))
        with self.assertRaisesRegex(bill.BillCollectionError, "操作超时"):
            self.inspect()
        data = json.loads((self.root / "capture" / "inspection_error.json").read_text(encoding="utf-8"))
        self.assertEqual(data["failure_code"], "browser_timeout")
        self.assertNotIn("synthetic-secret", json.dumps(data))

    def test_closed_original_tab_can_adopt_unique_target(self):
        self.page.closed = True
        popup = fixtures.Page(self.context)
        downloads = [{"status": "saved", "source_is_target": True}]
        self.assertIs(bill.wait_for_inspection_download(self.page, downloads, bill.BILL_URL, Mock()), popup)

    def test_unknown_target_and_use_outside_inspection_are_rejected(self):
        with self.assertRaises(bill.BillCollectionError):
            bill.wait_for_inspection_download(self.page, [], "https://foreign.example/", Mock())
        with redirect_stdout(io.StringIO()):
            self.assertEqual(bill.main(["--finish-on-download"]), 1)

    def test_flow_can_capture_monthly_first_and_then_only_requests_daily(self):
        attempts = []
        def capture(page, output, **kwargs):
            attempts.append(kwargs)
            observed = "rider_monthly" if len(attempts) == 1 else "agency_daily"
            kwargs["navigate"]()
            output.mkdir(parents=True)
            target = output / "page_controls.json"
            target.write_text(json.dumps({"observed_dataset": observed,
                "downloads": [{"status": "saved", "source_dataset": observed}]}), encoding="utf-8")
            return target
        navigate = Mock()
        with patch.object(bill, "inspect_page", side_effect=capture), redirect_stdout(io.StringIO()):
            bill.inspect_download_flow(self.page, self.root / "flow", navigate)
        flow = json.loads((self.root / "flow" / "inspection_flow.json").read_text(encoding="utf-8"))
        self.assertTrue(flow["complete"])
        self.assertFalse(flow["validated_for_payroll"])
        self.assertEqual(set(flow["captures"]), {"agency_daily", "rider_monthly"})
        self.assertEqual(attempts[0]["alternate_url"], bill.RIDER_BILL_URL)
        self.assertIsNone(attempts[1]["alternate_url"])
        self.assertEqual(navigate.call_args_list, [unittest.mock.call(bill.BILL_URL, self.page)] * 2)

    def test_known_alternate_download_can_finish_flow_capture_but_not_single_report(self):
        self.page.url = bill.RIDER_BILL_URL
        downloads = [{"status": "saved", "source_is_target": False, "source_dataset": "rider_monthly"}]
        self.assertIs(bill.wait_for_inspection_download(self.page, downloads, bill.BILL_URL, Mock(),
            alternate_url=bill.RIDER_BILL_URL), self.page)
        with self.assertRaisesRegex(bill.BillCollectionError, "不是目标账单页"):
            bill.wait_for_inspection_download(self.page, downloads, bill.BILL_URL, Mock())

    def test_flow_rejects_duplicate_or_unattributed_capture(self):
        def capture(page, output, **kwargs):
            output.mkdir(parents=True)
            target = output / "page_controls.json"
            target.write_text(json.dumps({"observed_dataset": "agency_daily", "downloads": [
                {"status": "saved", "source_dataset": "rider_monthly"}]}), encoding="utf-8")
            return target
        with patch.object(bill, "inspect_page", side_effect=capture), redirect_stdout(io.StringIO()):
            with self.assertRaisesRegex(bill.BillCollectionError, "唯一归属"):
                bill.inspect_download_flow(self.page, self.root / "flow", Mock())
        self.assertFalse((self.root / "flow" / "inspection_flow.json").exists())

    def test_alternate_must_be_the_other_known_report(self):
        for url in (bill.BILL_URL, "https://foreign.example/"):
            with self.subTest(url=url), self.assertRaises(bill.BillCollectionError):
                bill.wait_for_inspection_download(self.page, [], bill.BILL_URL, Mock(), alternate_url=url)


if __name__ == "__main__":
    unittest.main()
