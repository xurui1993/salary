import io
import json
from pathlib import Path
import sys
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
from contextlib import redirect_stdout

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import fengshen_bill as bill


class Context:
    def __init__(self):
        self.pages, self.listeners = [], {}

    def on(self, event, callback):
        self.listeners.setdefault(event, []).append(callback)

    def remove_listener(self, event, callback):
        self.listeners[event].remove(callback)

    def emit(self, event, value):
        for callback in list(self.listeners.get(event, [])):
            callback(value)


class Page(Context):
    def __init__(self, context):
        super().__init__()
        self.context, self.url = context, bill.BILL_URL
        self.closed, self.waits, self.navigations = False, 0, []
        self.frames = [self]
        self.tick = lambda: None
        context.pages.append(self)

    def is_closed(self):
        return self.closed

    def wait_for_timeout(self, _):
        self.waits += 1
        self.tick()

    def goto(self, url, **kwargs):
        self.url = url
        self.navigations.append(url)

    def locator(self, _):
        return SimpleNamespace(evaluate_all=lambda _: [])


def response(host="httpizza.ele.me"):
    url = f"https://{host}/observed/export?token=synthetic-secret"
    return SimpleNamespace(url=url, status=200,
        request=SimpleNamespace(url=url, resource_type="xhr", method="POST", post_data_json={"phone": "13800138000"}),
        json=lambda: {"success": True, "result": {"taskId": "synthetic-task-id", "url": "synthetic-signed-url"}})


class InspectionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=Path(__file__).parent)
        self.root = Path(self.temp.name)
        self.context = Context()
        self.page = Page(self.context)

    def tearDown(self):
        self.temp.cleanup()

    def inspect(self, prompt=lambda _: None, navigate=None):
        return bill.inspect_page(self.page, self.root / "capture", prompt=prompt, navigate=navigate)

    def test_observer_is_attached_before_navigation_and_removes_sensitive_values(self):
        output = self.inspect(navigate=lambda: self.context.emit("response", response()))
        data = json.loads(output.read_text(encoding="utf-8"))
        schema = data["response_schemas"]["POST https://httpizza.ele.me/observed/export"]
        self.assertEqual(schema["http_status"], 200)
        self.assertEqual(schema["response"]["result"]["taskId"], "str")
        for secret in ("13800138000", "synthetic-secret", "synthetic-task-id", "synthetic-signed-url"):
            self.assertNotIn(secret, json.dumps(data))
        self.assertTrue(data["inspection_only"])

    def test_foreign_host_response_is_not_recorded(self):
        output = self.inspect(navigate=lambda: self.context.emit("response", response("foreign.example")))
        self.assertEqual(json.loads(output.read_text(encoding="utf-8"))["response_schemas"], {})

    def test_finance_frame_origin_is_recorded_without_values(self):
        output = self.inspect(navigate=lambda: self.context.emit("response", response("freyja.ele.me")))
        data = json.loads(output.read_text(encoding="utf-8"))
        self.assertIn("POST https://freyja.ele.me/observed/export", data["response_schemas"])
        self.assertNotIn("synthetic-secret", json.dumps(data))

    def test_lookalike_domain_is_not_recorded(self):
        output = self.inspect(navigate=lambda: self.context.emit("response", response("freyja.ele.me.foreign.example")))
        self.assertEqual(json.loads(output.read_text(encoding="utf-8"))["response_schemas"], {})

    def test_get_query_names_are_recorded_without_values(self):
        item = response("freyja.ele.me")
        item.request.method = "GET"
        item.request.post_data_json = None
        output = self.inspect(navigate=lambda: self.context.emit("response", item))
        data = json.loads(output.read_text(encoding="utf-8"))
        self.assertEqual(data["response_schemas"]["GET https://freyja.ele.me/observed/export"]["request"], {"token": "str"})
        self.assertNotIn("synthetic-secret", json.dumps(data))

    def test_non_json_response_retains_endpoint_without_body_or_error_details(self):
        item = response("freyja.ele.me")
        item.json = Mock(side_effect=ValueError("synthetic-private-response"))
        output = self.inspect(navigate=lambda: self.context.emit("response", item))
        data = json.loads(output.read_text(encoding="utf-8"))
        observed = data["response_schemas"]["POST https://freyja.ele.me/observed/export"]
        self.assertEqual(observed["response_format"], "non_json")
        self.assertEqual(observed["http_status"], 200)
        self.assertIsNone(observed["response"])
        self.assertNotIn("synthetic-private-response", json.dumps(data))

    def test_request_without_response_is_retained_but_never_claimed_successful(self):
        item = response("freyja.ele.me")
        output = self.inspect(navigate=lambda: self.context.emit("request", item.request))
        data = json.loads(output.read_text(encoding="utf-8"))
        observed = data["response_schemas"]["POST https://freyja.ele.me/observed/export"]
        self.assertEqual(observed["response_format"], "pending_or_no_response")
        self.assertIsNone(observed["http_status"])
        self.assertNotIn("13800138000", json.dumps(data))

    def test_freyja_form_request_is_observed_without_parsing_download_body(self):
        item = response("freyja.ele.me")
        item.url = item.request.url = "https://freyja.ele.me/api/freyja/bill/create?token=synthetic-secret"
        item.request.resource_type = "document"
        item.json = Mock(side_effect=ValueError("synthetic-private-response"))
        output = self.inspect(navigate=lambda: self.context.emit("response", item))
        data = json.loads(output.read_text(encoding="utf-8"))
        self.assertIn("POST https://freyja.ele.me/api/freyja/bill/create", data["response_schemas"])
        self.assertNotIn("synthetic-secret", json.dumps(data))

    def test_first_party_salary_frame_is_included(self):
        frame = SimpleNamespace(url="https://salary.ele.me/report?token=synthetic-secret", locator=self.page.locator)
        self.page.frames.append(frame)
        output = self.inspect()
        data = json.loads(output.read_text(encoding="utf-8"))
        self.assertEqual(data["frames"][1]["url"], "https://salary.ele.me/report")
        self.assertIn("https://salary.ele.me", data["frame_origins"])
        self.assertNotIn("synthetic-secret", json.dumps(data))

    def test_read_only_snapshot_does_not_wait_for_console_or_download(self):
        with patch("builtins.input", side_effect=AssertionError("No console")):
            output = bill.inspect_page(self.page, self.root / "capture", snapshot_only=True, expected_url=bill.BILL_URL)
        data = json.loads(output.read_text(encoding="utf-8"))
        self.assertTrue(data["inspection_only"])
        self.assertEqual(data["downloads"], [])
        self.assertEqual(self.page.waits, 2)

    def test_snapshot_restores_dashboard_once_and_checks_target(self):
        self.page.url = "https://aeolus.ele.me/#/app/dashboard/index.html"
        output = bill.inspect_page(self.page, self.root / "capture", snapshot_only=True, expected_url=bill.RIDER_BILL_URL)
        self.assertEqual(self.page.navigations, [bill.RIDER_BILL_URL])
        self.assertEqual(json.loads(output.read_text(encoding="utf-8"))["observed_dataset"], "rider_monthly")

    def test_snapshot_cannot_mark_wrong_route_as_target_controls(self):
        self.page.url = "https://mozi-login.alibaba-inc.com/"
        with self.assertRaisesRegex(bill.BillCollectionError, "未进入目标账单页"):
            bill.inspect_page(self.page, self.root / "capture", snapshot_only=True, expected_url=bill.RIDER_BILL_URL)
        self.assertFalse((self.root / "capture" / "page_controls.json").exists())

    def test_snapshot_flag_is_restricted_to_single_page_inspection(self):
        for args in (["--snapshot-only"], ["--inspect-flow", "--snapshot-only"],
                     ["--inspect", "--snapshot-only", "--finish-on-download"]):
            with self.subTest(args=args), redirect_stdout(io.StringIO()):
                self.assertEqual(bill.main(args), 1)

    def test_observe_controls_flag_cannot_enable_export(self):
        for args in (["--observe-controls"], ["--inspect-flow", "--observe-controls"],
                     ["--inspect", "--observe-controls", "--finish-on-download"],
                     ["--inspect", "--observe-controls", "--snapshot-only"]):
            with self.subTest(args=args), redirect_stdout(io.StringIO()):
                self.assertEqual(bill.main(args), 1)

    def test_control_observation_finishes_without_console_or_download(self):
        def tick():
            (self.root / "capture" / "finish_inspection.flag").touch()
        self.page.tick = tick
        with patch("builtins.input", side_effect=AssertionError("No console")), redirect_stdout(io.StringIO()):
            output = bill.inspect_page(self.page, self.root / "capture", observe_controls=True, expected_url=bill.BILL_URL)
        data = json.loads(output.read_text(encoding="utf-8"))
        self.assertEqual(data["downloads"], [])
        self.assertTrue(data["inspection_only"])
        self.assertTrue((output.parent / "page_controls_progress.json").is_file())

    def test_control_observation_stop_during_login_does_not_confirm_report(self):
        self.page.url = "https://mozi-login.alibaba-inc.com/"
        self.page.tick = lambda: (self.root / "capture" / "finish_inspection.flag").touch()
        with redirect_stdout(io.StringIO()), self.assertRaisesRegex(bill.BillCollectionError, "未确认目标"):
            bill.inspect_page(self.page, self.root / "capture", observe_controls=True, expected_url=bill.BILL_URL)
        self.assertFalse((self.root / "capture" / "page_controls.json").exists())

    def test_control_observation_refuses_foreign_page(self):
        self.page.url = "https://foreign.example/"
        with redirect_stdout(io.StringIO()), self.assertRaises(bill.BillCollectionError):
            bill.inspect_page(self.page, self.root / "capture", observe_controls=True, expected_url=bill.BILL_URL)

    def test_monthly_scope_diagnostics_keep_format_not_value_or_credentials(self):
        for value, expected in (("2026-08", "%Y-%m"), ("202608", "%Y%m")):
            request = SimpleNamespace(
                url="https://httpizza.ele.me/xtop/xtop.lpd.price.mng.zsSalaryBillQueryFs.pageQuerySalaryBill/1.0",
                post_data_json={"phone": "synthetic-private-phone", "params": {"request": {
                    "billCycle": value, "teamIds": None, "settleStatusList": [], "token": "synthetic-secret"}}})
            result = bill.monthly_request_diagnostics(request)
            self.assertEqual(result, {"bill_cycle_format": expected, "all_stations": True, "all_statuses": True})
            self.assertNotIn(value, json.dumps(result))
            self.assertNotIn("synthetic", json.dumps(result))
        request.url = "https://foreign.example/xtop/xtop.lpd.price.mng.zsSalaryBillQueryFs.pageQuerySalaryBill/1.0"
        self.assertIsNone(bill.monthly_request_diagnostics(request))

    def test_download_from_new_tab_is_retained_without_using_original_filename(self):
        def prompt(_):
            popup = Page(self.context)
            self.context.emit("page", popup)
            popup.emit("download", SimpleNamespace(suggested_filename="../../private-person.xlsx",
                save_as=lambda path: Path(path).write_bytes(b"synthetic-inspection-file")))
        output = self.inspect(prompt)
        data = json.loads(output.read_text(encoding="utf-8"))
        sample = data["downloads"][0]
        self.assertEqual(sample["status"], "saved")
        self.assertFalse(sample["validated_for_payroll"])
        self.assertEqual((output.parent / sample["path"]).read_bytes(), b"synthetic-inspection-file")
        self.assertNotIn("private-person", json.dumps(data))
        self.assertFalse((self.root / "private-person.xlsx").exists())

    def test_unknown_download_type_is_not_saved(self):
        save = Mock()
        output = self.inspect(lambda _: self.page.emit("download", SimpleNamespace(suggested_filename="installer.exe", save_as=save)))
        self.assertEqual(json.loads(output.read_text(encoding="utf-8"))["downloads"][0]["status"], "error")
        save.assert_not_called()

    def test_failed_inspection_keeps_only_sanitized_evidence(self):
        def fail(_):
            self.context.emit("response", response())
            raise RuntimeError("synthetic-private-credential")
        with self.assertRaisesRegex(bill.BillCollectionError, "脱敏记录"):
            self.inspect(fail)
        data = json.loads((self.root / "capture" / "inspection_error.json").read_text(encoding="utf-8"))
        self.assertTrue(data["response_schemas"])
        self.assertEqual(data["failure_code"], "browser_operation_failed")
        self.assertNotIn("synthetic-private-credential", json.dumps(data))
        self.assertTrue(all(not listeners for listeners in self.context.listeners.values()))
        self.assertFalse(self.page.listeners["download"])

    def test_closed_initial_tab_can_snapshot_single_business_popup(self):
        def prompt(_):
            self.page.closed = True
            popup = Page(self.context)
            self.context.emit("page", popup)
        output = self.inspect(prompt)
        self.assertTrue(json.loads(output.read_text(encoding="utf-8"))["frames"])

    def test_ambiguous_business_tabs_stop_inspection(self):
        def prompt(_):
            self.page.closed = True
            Page(self.context)
            Page(self.context)
        with self.assertRaisesRegex(bill.BillCollectionError, "唯一"):
            self.inspect(prompt)

    def test_prompt_keeps_browser_events_on_original_thread(self):
        visited = threading.Event()
        done = threading.Event()
        ui_threads, reader_threads = [], []
        def reader(_):
            reader_threads.append(threading.get_ident())
            self.assertTrue(visited.wait(2))
            done.set()
        def tick():
            ui_threads.append(threading.get_ident())
            visited.set()
            self.assertTrue(done.wait(2))
        self.page.tick = tick
        self.assertIs(bill.browser_prompt(self.page, "Enter", reader=reader), self.page)
        self.assertEqual(set(ui_threads), {threading.get_ident()})
        self.assertNotIn(threading.get_ident(), reader_threads)

    def test_prompt_closed_browser_stops_without_waiting_for_stdin(self):
        release = threading.Event()
        self.page.closed = True
        try:
            with self.assertRaisesRegex(bill.BillCollectionError, "浏览器已关闭"):
                bill.browser_prompt(self.page, "Enter", reader=lambda _: release.wait(2))
        finally:
            release.set()

    def test_prompt_timeout_is_bounded(self):
        release = threading.Event()
        self.page.tick = lambda: None
        try:
            with self.assertRaisesRegex(bill.BillCollectionError, "30 分钟"):
                bill.browser_prompt(self.page, "Enter", reader=lambda _: release.wait(2), timeout=1,
                                    clock=iter([0, 0, 2]).__next__)
        finally:
            release.set()

    def test_cli_session_reuse_is_inspection_only(self):
        with redirect_stdout(io.StringIO()):
            self.assertEqual(bill.main(["--reuse-session"]), 1)

    def test_cli_restores_session_and_inspects_both_pages_without_resaving(self):
        state = {"cookies": [], "origins": []}
        vault = SimpleNamespace(load=Mock(return_value=state), save=Mock())
        browser = Mock()
        browser.new_context.return_value = self.context
        self.context.new_page = lambda: self.page
        manager = Mock()
        manager.__enter__ = Mock(return_value=SimpleNamespace(chromium=SimpleNamespace(launch=lambda **kwargs: browser)))
        manager.__exit__ = Mock(return_value=False)
        def inspect(page, output, navigate):
            navigate()
            return output / "page_controls.json"
        with patch("playwright.sync_api.sync_playwright", return_value=manager), patch("fengshen_auth.SessionVault", return_value=vault), \
                patch.object(bill, "inspect_page", side_effect=inspect), redirect_stdout(io.StringIO()):
            self.assertEqual(bill.main(["--inspect-flow", "--reuse-session", "--output", str(self.root)]), 0)
        browser.new_context.assert_called_once_with(accept_downloads=True, storage_state=state)
        vault.save.assert_not_called()
        self.assertEqual(self.page.navigations, [bill.BILL_URL, bill.RIDER_BILL_URL])
        browser.close.assert_called_once()


if __name__ == "__main__":
    unittest.main()
