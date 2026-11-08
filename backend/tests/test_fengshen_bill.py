import io
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from fengshen_bill import (
    BILL_URL, RIDER_BILL_URL, BillCollectionError, BillPageCollector, BillRequest,
    MonthlyBillPageCollector, MonthlyBillRequest, response_task_id, schema_only,
    CityPopupNotClosed,
    validate_bill_file, validate_profile,
)


def workbook_bytes():
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        archive.writestr("[Content_Types].xml", "<Types/>")
        archive.writestr("xl/workbook.xml", "<workbook/>")
    return output.getvalue()


def daily_profile():
    profile = {key: "#" + key for key in (
        "start_input", "end_input", "agency_trigger", "agency_popup", "agency_select_all",
        "sub_bill_trigger", "sub_bill_popup", "sub_bill_select_all", "submit_button",
        "task_status", "task_download", "bill_type_selected", "bill_cycle_selected",
    )}
    profile.update({
        "verified": True, "dataset": "agency_daily", "export_mode": "task",
        "export_response_url": "https://httpizza.ele.me/test/export",
        "export_task_id_path": ["result", "data", "taskId"],
        "task_row": "[data-task-id='{task_id}']", "success_status": ["成功"],
        "failure_status": ["失败"],
        "expected_agency_id": "31030156", "agency_context": "#agency_context",
    })
    return profile


def monthly_profile():
    profile = {key: "#" + key for key in (
        "month_input", "reset_button", "query_button", "period_label", "all_status_tab", "submit_button",
    )}
    profile.update({
        "verified": True, "dataset": "rider_monthly", "export_mode": "direct",
        "query_response_url": "https://httpizza.ele.me/test/query",
        "query_month_path": ["params", "request", "month"],
        "expected_agency_id": "31030156", "agency_context": "#agency_context",
    })
    return profile


class FakeLocator:
    def __init__(self, page, key, count=1, text="", value="", visible=True):
        self.page, self.key, self.matches = page, key, count
        self.text, self.value, self.visible = text, value, visible
        self.checked, self.readonly = False, False

    def count(self):
        return self.matches

    def is_visible(self):
        return self.visible

    def wait_for(self, **kwargs):
        self.page.events.append(("wait_for", self.key))

    def is_enabled(self):
        return True

    def is_checked(self):
        return self.checked

    def set_checked(self, value):
        self.checked = value
        self.page.events.append(("check", self.key, value))

    def get_attribute(self, key):
        return "" if key == "readonly" and self.readonly else None

    def fill(self, value):
        self.value = value
        self.page.events.append(("fill", self.key, value))

    def press(self, value):
        if value == "Escape":
            self.visible = False

    def click(self):
        self.page.events.append(("click", self.key))
        if self.key in ("#agency_trigger", "#sub_bill_trigger", "#city_trigger"):
            self.page.controls[self.key.replace("trigger", "popup")].visible = True

    def inner_text(self):
        return self.text

    def input_value(self):
        return self.value

    def locator(self, selector):
        return self.page.locator(self.key + " " + selector)


class FakeDownload:
    def __init__(self):
        self.content = workbook_bytes()
        self.failed = False

    def failure(self):
        return "network" if self.failed else None

    def save_as(self, path):
        Path(path).write_bytes(self.content)


class FakePending:
    def __init__(self, value):
        self.value = value

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


class FakePage:
    def __init__(self, profile, monthly=False):
        self.profile, self.events, self.controls = profile, [], {}
        self.url = RIDER_BILL_URL if monthly else BILL_URL
        self.now = 0
        self.download = FakeDownload()
        for value in profile.values():
            if isinstance(value, str) and value.startswith("#"):
                self.controls[value] = FakeLocator(self, value)
        self.status = 200
        self.controls["#agency_context"].text = "[31030156][三亚] 当前授权代理商"
        self.payload = {"code": 200, "result": {"data": {"taskId": "NEW_17"}}}
        self.query_month = "2026-09"
        if monthly:
            self.controls["#period_label"].text = "账单周期：2026-09-01至2026-09-30"
        else:
            self.controls["#bill_type_selected"].text = "代理商账单"
            self.controls["#bill_cycle_selected"].text = "日账单"
            for prefix in ("agency", "sub_bill"):
                key = f"#{prefix}_popup #{prefix}_select_all"
                self.controls[key] = FakeLocator(self, key)
            row = "[data-task-id='NEW_17']"
            self.controls[row] = FakeLocator(self, row)
            self.controls[row + " #task_status"] = FakeLocator(self, row + " #task_status", text="成功")
            self.controls[row + " #task_download"] = FakeLocator(self, row + " #task_download")
            old = "[data-task-id='OLD_01']"
            self.controls[old] = FakeLocator(self, old)
            self.controls[old + " #task_download"] = FakeLocator(self, old + " #task_download")

    def locator(self, selector):
        return self.controls.get(selector, FakeLocator(self, selector, count=0))

    def expect_response(self, predicate, timeout):
        endpoint = self.profile.get("query_response_url", self.profile.get("export_response_url"))
        request = SimpleNamespace(method="POST", post_data_json={"params": {"request": {"month": self.query_month}}})
        response = SimpleNamespace(url=endpoint, request=request, status=self.status, json=lambda: self.payload)
        if not predicate(response):
            raise TimeoutError("no matching response")
        return FakePending(response)

    def expect_download(self, timeout):
        return FakePending(self.download)

    def wait_for_timeout(self, milliseconds):
        self.now += milliseconds / 1000

    def reload(self, **kwargs):
        self.events.append(("reload",))


class FengshenBillTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="fengshen-test-", dir=Path(__file__).resolve().parent)
        self.root = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def collect(self, page, request, monthly=False):
        cls = MonthlyBillPageCollector if monthly else BillPageCollector
        collector = cls(page, page.profile, self.root / "run", log=lambda _: None, timeout=2, poll_interval=1)
        with patch("fengshen_bill.time.monotonic", side_effect=lambda: page.now):
            return collector.collect(request)

    def manifest(self):
        return json.loads((self.root / "run" / "manifest.json").read_text(encoding="utf-8"))

    def test_same_day_request(self):
        self.assertEqual(BillRequest("2026-09-01", "2026-09-01").end, "2026-09-01")

    def test_invalid_and_reversed_dates(self):
        for start, end in (("2026-09-31", "2026-10-01"), ("2026-9-1", "2026-09-01"), ("2026-09-02", "2026-09-01")):
            with self.subTest(start=start), self.assertRaises(ValueError):
                BillRequest(start, end)

    def test_month_boundaries(self):
        self.assertEqual(MonthlyBillRequest("2026-09").end, "2026-09-30")
        self.assertEqual(MonthlyBillRequest("2024-02").end, "2024-02-29")
        for month in ("2026-13", "2026-9", "0000-01"):
            with self.subTest(month=month), self.assertRaises(ValueError):
                MonthlyBillRequest(month)

    def test_unverified_profile_rejected(self):
        profile = daily_profile()
        profile["verified"] = False
        with self.assertRaises(BillCollectionError):
            validate_profile(profile)

    def test_unsafe_endpoint_and_missing_identity_rejected(self):
        for field, value in (("export_response_url", "https://example.com/api"), ("task_row", "table tr:first-child")):
            profile = daily_profile()
            profile[field] = value
            with self.subTest(field=field), self.assertRaises(BillCollectionError):
                validate_profile(profile)

    def test_monthly_profile_requires_month_in_request(self):
        profile = monthly_profile()
        del profile["query_month_path"]
        with self.assertRaises(BillCollectionError):
            validate_profile(profile)

    def test_business_failure_and_invalid_task_id(self):
        for payload in (
            {"code": 401}, {"success": False}, {"result": {"code": 500}},
            {"result": {"data": {"taskId": True}}}, {"result": {"data": {"taskId": "a'] *"}}},
            {"result": {"data": {"otherId": "OLD"}}},
        ):
            with self.subTest(payload=payload), self.assertRaises(BillCollectionError):
                response_task_id(payload, ["result", "data", "taskId"])

    def test_response_schema_does_not_keep_values(self):
        data = {"cookie": "TOP_SECRET", "url": "https://example.com/?token=SECRET", "items": [{"amount": 100}]}
        schema = json.dumps(schema_only(data))
        self.assertNotIn("SECRET", schema)
        self.assertNotIn("100", schema)

    def test_unexpected_page_failure_retains_safe_control_diagnostics(self):
        page = FakePage(daily_profile())
        with patch.object(BillPageCollector, "apply_request", side_effect=TimeoutError('waiting for event "response" https://example.test/?token=SECRET')), \
             self.assertRaisesRegex(BillCollectionError, "manifest.json"):
            self.collect(page, BillRequest("2026-09-01", "2026-09-01"))
        manifest = self.manifest()
        self.assertEqual(manifest["failure"]["exception_type"], "TimeoutError")
        self.assertEqual(manifest["failure"]["timeout_kind"], "response")
        self.assertIn("control", manifest["failure"])
        self.assertNotIn("SECRET", json.dumps(manifest))

    def test_ignored_city_cancel_recovers_with_escape(self):
        from unittest.mock import Mock
        page = FakePage(daily_profile())
        collector = BillPageCollector(page, page.profile, self.root / "run", log=lambda _: None)
        collector.profile["city_close"] = "#city_close"
        popup = FakeLocator(page, "popup", visible=True)
        cancel = Mock()
        with patch.object(collector, "_control", return_value=cancel), \
             patch.object(collector, "_dismiss_notice"), \
             patch("fengshen_bill.time.monotonic", side_effect=lambda: page.now):
            collector._close_city_popup(popup)
        cancel.click.assert_called_once()
        self.assertFalse(popup.is_visible())

    def test_city_popup_waits_for_close_animation(self):
        from unittest.mock import Mock
        page = FakePage(daily_profile())
        collector = BillPageCollector(page, page.profile, self.root / "run", log=lambda _: None)
        collector.profile["city_close"] = "#city_close"
        popup = Mock()
        popup.is_visible.side_effect = lambda: page.now < 0.5
        cancel = Mock()
        with patch.object(collector, "_control", return_value=cancel), \
             patch.object(collector, "_dismiss_notice"), \
             patch("fengshen_bill.time.monotonic", side_effect=lambda: page.now):
            collector._close_city_popup(popup)
        cancel.click.assert_called_once()
        popup.press.assert_not_called()

    def test_city_popup_cannot_be_ignored_when_all_dismissals_fail(self):
        from unittest.mock import Mock
        page = FakePage(daily_profile())
        collector = BillPageCollector(page, page.profile, self.root / "run", log=lambda _: None)
        collector.profile["city_close"] = "#city_close"
        popup, cancel = Mock(), Mock()
        popup.is_visible.return_value = True
        with patch.object(collector, "_control", return_value=cancel), \
             patch.object(collector, "_dismiss_notice"), \
             patch("fengshen_bill.time.monotonic", side_effect=lambda: page.now):
            with self.assertRaises(CityPopupNotClosed):
                collector._close_city_popup(popup)
        self.assertEqual(cancel.click.call_count, 2)
        popup.press.assert_called_once_with("Escape")

    def test_daily_all_select_and_new_task_only(self):
        page = FakePage(daily_profile())
        result = self.collect(page, BillRequest("2026-09-01", "2026-09-01"))
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["task_id"], "NEW_17")
        self.assertEqual(len(result["files"]), 1)
        self.assertIn(("check", "#agency_popup #agency_select_all", True), page.events)
        self.assertIn(("check", "#sub_bill_popup #sub_bill_select_all", True), page.events)
        self.assertIn(("fill", "#end_input", "2026-09-01"), page.events)
        self.assertNotIn(("click", "[data-task-id='OLD_01'] #task_download"), page.events)
        self.assertEqual(self.manifest()["status"], "success")

    def test_old_task_is_not_used_on_timeout(self):
        page = FakePage(daily_profile())
        page.controls["[data-task-id='NEW_17']"].matches = 0
        with self.assertRaisesRegex(BillCollectionError, "超时"):
            self.collect(page, BillRequest("2026-09-01", "2026-09-01"))
        self.assertEqual(self.manifest()["status"], "error")
        self.assertEqual(self.manifest()["files"], [])
        self.assertFalse(any("task_download" in event[1] for event in page.events))

    def test_failed_platform_task(self):
        page = FakePage(daily_profile())
        page.controls["[data-task-id='NEW_17'] #task_status"].text = "失败"
        with self.assertRaises(BillCollectionError):
            self.collect(page, BillRequest("2026-09-01", "2026-09-01"))
        self.assertEqual(self.manifest()["status"], "error")

    def test_ambiguous_task_row_stops(self):
        page = FakePage(daily_profile())
        page.controls["[data-task-id='NEW_17']"].matches = 2
        with self.assertRaises(BillCollectionError):
            self.collect(page, BillRequest("2026-09-01", "2026-09-01"))

    def test_readonly_date_does_not_submit(self):
        page = FakePage(daily_profile())
        page.controls["#start_input"].readonly = True
        with self.assertRaisesRegex(BillCollectionError, "只读"):
            self.collect(page, BillRequest("2026-09-01", "2026-09-01"))
        self.assertNotIn(("click", "#submit_button"), page.events)

    def test_wrong_bill_type_does_not_submit(self):
        page = FakePage(daily_profile())
        page.controls["#bill_type_selected"].text = "其他账单"
        with self.assertRaises(BillCollectionError):
            self.collect(page, BillRequest("2026-09-01", "2026-09-01"))
        self.assertNotIn(("click", "#submit_button"), page.events)

    def test_invalid_download_keeps_error_and_no_partial_file(self):
        page = FakePage(daily_profile())
        page.download.content = b"<html>login</html>"
        with self.assertRaises(BillCollectionError):
            self.collect(page, BillRequest("2026-09-01", "2026-09-01"))
        self.assertEqual(self.manifest()["status"], "error")
        self.assertFalse((self.root / "run" / "bill.download.part").exists())
        self.assertEqual(self.manifest()["files"], [])

    def test_browser_download_failure(self):
        page = FakePage(daily_profile())
        page.download.failed = True
        with self.assertRaises(BillCollectionError):
            self.collect(page, BillRequest("2026-09-01", "2026-09-01"))
        self.assertEqual(self.manifest()["files"], [])

    def test_monthly_export_all(self):
        page = FakePage(monthly_profile(), monthly=True)
        result = self.collect(page, MonthlyBillRequest("2026-09"), monthly=True)
        self.assertEqual(result["month"], "2026-09")
        self.assertEqual(result["start"], "2026-09-01")
        self.assertEqual(result["end"], "2026-09-30")
        self.assertEqual(result["dataset"], "rider_monthly")
        self.assertEqual(result["status"], "success")
        self.assertIn(("click", "#reset_button"), page.events)
        self.assertIn(("fill", "#month_input", "2026-09"), page.events)
        self.assertIn(("click", "#all_status_tab"), page.events)
        self.assertIn(("click", "#submit_button"), page.events)

    def test_wrong_month_request_does_not_export(self):
        page = FakePage(monthly_profile(), monthly=True)
        page.query_month = "2026-10"
        with self.assertRaises(BillCollectionError):
            self.collect(page, MonthlyBillRequest("2026-09"), monthly=True)
        self.assertNotIn(("click", "#submit_button"), page.events)

    def test_wrong_period_display_does_not_export(self):
        page = FakePage(monthly_profile(), monthly=True)
        page.controls["#period_label"].text = "账单周期：2026-10-01至2026-10-31"
        with self.assertRaisesRegex(BillCollectionError, "不一致"):
            self.collect(page, MonthlyBillRequest("2026-09"), monthly=True)
        self.assertNotIn(("click", "#submit_button"), page.events)

    def test_monthly_query_business_error_does_not_export(self):
        page = FakePage(monthly_profile(), monthly=True)
        page.payload = {"code": 403}
        with self.assertRaises(BillCollectionError):
            self.collect(page, MonthlyBillRequest("2026-09"), monthly=True)
        self.assertNotIn(("click", "#submit_button"), page.events)

    def test_monthly_query_http_error_does_not_export(self):
        page = FakePage(monthly_profile(), monthly=True)
        page.status = 401
        with self.assertRaises(BillCollectionError):
            self.collect(page, MonthlyBillRequest("2026-09"), monthly=True)

    def test_reusing_run_directory_is_refused(self):
        page = FakePage(daily_profile())
        (self.root / "run").mkdir()
        with self.assertRaises(FileExistsError):
            self.collect(page, BillRequest("2026-09-01", "2026-09-01"))

    def test_file_size_and_empty_archives(self):
        path = self.root / "bill.part"
        path.write_bytes(b"")
        with self.assertRaises(BillCollectionError):
            validate_bill_file(path)
        path.write_bytes(workbook_bytes())
        with self.assertRaises(BillCollectionError):
            validate_bill_file(path, max_bytes=1)

    def test_zip_bill_is_not_extracted(self):
        path = self.root / "bill.zip"
        with zipfile.ZipFile(path, "w") as archive:
            archive.writestr("statement.xlsx", workbook_bytes())
        self.assertEqual(validate_bill_file(path)["format"], "zip")
        self.assertFalse((self.root / "statement.xlsx").exists())

    def test_login_page_is_not_exported(self):
        page = FakePage(daily_profile())
        page.url = "https://mozi-login.alibaba-inc.com/"
        with self.assertRaisesRegex(BillCollectionError, "登录"):
            self.collect(page, BillRequest("2026-09-01", "2026-09-01"))
        self.assertNotIn(("click", "#submit_button"), page.events)

    def test_ambiguous_all_selection_stops_before_submit(self):
        page = FakePage(daily_profile())
        page.controls["#agency_popup #agency_select_all"].matches = 2
        with self.assertRaises(BillCollectionError):
            self.collect(page, BillRequest("2026-09-01", "2026-09-01"))
        self.assertNotIn(("click", "#submit_button"), page.events)

    def test_date_picker_cannot_overwrite_start(self):
        page = FakePage(daily_profile())
        original = page.controls["#end_input"].fill
        def reset_start(value):
            original(value)
            page.controls["#start_input"].value = "2026-10-01"
        page.controls["#end_input"].fill = reset_start
        with self.assertRaises(BillCollectionError):
            self.collect(page, BillRequest("2026-09-01", "2026-09-01"))
        self.assertNotIn(("click", "#submit_button"), page.events)

    def test_readonly_month_stops(self):
        page = FakePage(monthly_profile(), monthly=True)
        page.controls["#month_input"].readonly = True
        with self.assertRaisesRegex(BillCollectionError, "只读"):
            self.collect(page, MonthlyBillRequest("2026-09"), monthly=True)
        self.assertNotIn(("click", "#submit_button"), page.events)

    def test_invalid_timeout_stops(self):
        page = FakePage(daily_profile())
        for timeout in (0, float("inf"), float("nan")):
            with self.subTest(timeout=timeout), self.assertRaises(ValueError):
                BillPageCollector(page, page.profile, self.root / "run", timeout=timeout)

    def test_generic_errors_do_not_save_secret_urls(self):
        page = FakePage(daily_profile())
        def broken_click():
            raise RuntimeError("https://example.com/download?token=TOP_SECRET")
        page.controls["#submit_button"].click = broken_click
        with self.assertRaises(BillCollectionError):
            self.collect(page, BillRequest("2026-09-01", "2026-09-01"))
        self.assertNotIn("TOP_SECRET", json.dumps(self.manifest()))

    def test_calendar_mode_requires_full_month_identity(self):
        profile = monthly_profile()
        profile.update({"date_input_mode": "calendar", "calendar_popup": "#calendar", "calendar_month": "text=九月"})
        with self.assertRaises(BillCollectionError):
            validate_profile(profile)

    def test_calendar_navigates_to_requested_month(self):
        profile = daily_profile()
        profile.update({"calendar_heading": "#heading", "calendar_previous": "#previous", "calendar_next": "#next"})
        page = FakePage(profile)
        popup = FakeLocator(page, "#calendar")
        heading = FakeLocator(page, "#calendar #heading", text="2026-10")
        previous = FakeLocator(page, "#calendar #previous")
        cell = FakeLocator(page, "#calendar [date='2026-09-01']", count=0)
        page.controls[heading.key], page.controls[previous.key], page.controls[cell.key] = heading, previous, cell
        def change_month():
            heading.text = "2026-09"
            cell.matches = 1
        previous.click = change_month
        collector = BillPageCollector(page, profile, self.root / "run")
        import datetime
        self.assertIs(collector._calendar_target(popup, "[date='2026-09-01']", datetime.date(2026, 9, 1)), cell)

    def test_missing_calendar_navigation_fails(self):
        page = FakePage(daily_profile())
        collector = BillPageCollector(page, page.profile, self.root / "run")
        import datetime
        with self.assertRaises(BillCollectionError):
            collector._calendar_target(FakeLocator(page, "#calendar"), "[date='2026-09-01']", datetime.date(2026, 9, 1))

    def test_wrong_agency_context_stops(self):
        page = FakePage(monthly_profile(), monthly=True)
        page.controls["#agency_context"].text = "[31030116] 其他代理商"
        with self.assertRaisesRegex(BillCollectionError, "代理商"):
            self.collect(page, MonthlyBillRequest("2026-09"), monthly=True)
        self.assertNotIn(("click", "#submit_button"), page.events)

    def test_agency_id_is_matched_exactly(self):
        page = FakePage(daily_profile())
        page.controls["#agency_context"].text = "[1310301562] 其他代理商"
        with self.assertRaises(BillCollectionError):
            self.collect(page, BillRequest("2026-09-01", "2026-09-01"))


if __name__ == "__main__":
    unittest.main()
