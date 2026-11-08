import io
from contextlib import redirect_stdout
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import fengshen_bill as bill
from test_fengshen_bill import FakePage, FakePending, monthly_profile

REQUEST = bill.MonthlyBillRequest("2026-09")


def payload():
    return {"params": {"request": {"bizType": 1, "billCycle": "2026-09", "teamIds": None,
                                    "settleStatusList": [], "pageNum": 1, "pageSize": 20}}}


def profile():
    result = monthly_profile()
    result.update(request_scope_mode="all_city_riders", query_response_url=bill.MONTHLY_QUERY_URL,
                  export_response_url=bill.MONTHLY_EXPORT_URL, query_month_path=["params", "request", "billCycle"])
    return result


class ScopedPage(FakePage):
    def __init__(self):
        super().__init__(profile(), monthly=True)
        self.body, self.routes, self.forwarded, self.blocked = payload(), {}, [], []
        self.valid, self.http_status = True, 200
        self.download.url = "https://download.ele.me/bill.xlsx"
        self.handlers = {}
        self.context = SimpleNamespace(pages=[self], on=lambda event, handler: None,
                                       remove_listener=lambda event, handler: None)
        def submit():
            request = SimpleNamespace(url=bill.MONTHLY_EXPORT_URL, method="POST", post_data_json=self.body)
            for handler in self.routes.values():
                handler(SimpleNamespace(request=request, continue_=lambda: self.forwarded.append(request.url),
                                        abort=lambda: self.blocked.append(request.url)))
            for handler in self.handlers.get("download", []):
                handler(self.download)
        self.controls["#submit_button"].click = submit

    def route(self, pattern, handler):
        self.routes[pattern] = handler

    def on(self, event, handler):
        self.handlers.setdefault(event, []).append(handler)

    def remove_listener(self, event, handler):
        self.handlers[event].remove(handler)

    def unroute(self, pattern, handler):
        assert self.routes.pop(pattern) == handler

    def expect_response(self, predicate, timeout):
        for endpoint in (bill.MONTHLY_QUERY_URL, bill.MONTHLY_EXPORT_URL):
            response = SimpleNamespace(url=endpoint, status=self.http_status,
                request=SimpleNamespace(method="POST", post_data_json=self.body),
                json=lambda: {"code": 200, "result": {"success": True, "code": None,
                               "data": {"validRes": self.valid, "fileUrl": "https://download.ele.me/bill.xlsx"}}})
            if predicate(response):
                return FakePending(response)
        raise TimeoutError("No matching response")


class MonthlyScopeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=Path(__file__).parent)
        self.root = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def test_all_city_scope_contract(self):
        bill.monthly_export_scope(payload(), REQUEST)
        for key, value in (("billCycle", "2026-08"), ("teamIds", [123]), ("settleStatusList", [1]),
                           ("knightId", "123"), ("pageNum", True)):
            data = payload()
            data["params"]["request"][key] = value
            with self.subTest(key=key), self.assertRaises(bill.BillCollectionError):
                bill.monthly_export_scope(data, REQUEST)

    def test_observed_success_envelope_accepts_null_business_error_code(self):
        response = {"code": 200, "error": None, "result": {"success": True, "code": None, "message": None}}
        bill.check_response_payload(response)
        self.assertFalse(bill.login_rejection(response))

    def test_null_error_code_does_not_override_explicit_failure(self):
        response = {"code": 200, "error": None, "result": {"success": False, "code": None, "message": None}}
        with self.assertRaises(bill.BillCollectionError):
            bill.check_response_payload(response)

    def test_direct_export_confirms_actual_scope_before_save(self):
        page = ScopedPage()
        collector = bill.MonthlyBillPageCollector(page, page.profile, self.root, log=lambda _: None)
        result = collector._collect_monthly_direct(REQUEST)
        self.assertEqual(result["format"], "xlsx")
        self.assertEqual(page.forwarded, [bill.MONTHLY_EXPORT_URL])
        self.assertFalse(page.routes)

    def test_filtered_export_is_blocked_and_never_saved(self):
        page = ScopedPage()
        page.body["params"]["request"]["settleStatusList"] = [1]
        collector = bill.MonthlyBillPageCollector(page, page.profile, self.root, log=lambda _: None)
        with self.assertRaisesRegex(bill.BillCollectionError, "阻止提交"):
            collector._collect_monthly_direct(REQUEST)
        self.assertTrue(page.blocked)
        self.assertFalse(page.forwarded)
        self.assertFalse(list(self.root.glob("bill*")))
        self.assertFalse(page.routes)

    def test_unrelated_file_download_is_not_saved(self):
        page = ScopedPage()
        page.download.url = "https://download.ele.me/old.xlsx"
        collector = bill.MonthlyBillPageCollector(page, page.profile, self.root, log=lambda _: None)
        with patch("fengshen_bill.time.monotonic", side_effect=lambda: page.now):
            with self.assertRaisesRegex(bill.BillCollectionError, "一致的浏览器下载"):
                collector._collect_monthly_direct(REQUEST)
        self.assertFalse(list(self.root.glob("bill*")))
        self.assertFalse(page.handlers["download"])

    def test_new_tab_download_matches_only_export_response_url(self):
        page = ScopedPage()
        context_handlers = {}
        page.context.on = lambda event, handler: context_handlers.update({event: handler})
        page.context.remove_listener = lambda event, handler: context_handlers.pop(event)
        popup = ScopedPage()
        def submit():
            request = SimpleNamespace(url=bill.MONTHLY_EXPORT_URL, method="POST", post_data_json=page.body)
            for handler in page.routes.values():
                handler(SimpleNamespace(request=request, continue_=lambda: page.forwarded.append(request.url),
                                        abort=lambda: page.blocked.append(request.url)))
            context_handlers["page"](popup)
            for handler in popup.handlers.get("download", []):
                handler(popup.download)
        page.controls["#submit_button"].click = submit
        collector = bill.MonthlyBillPageCollector(page, page.profile, self.root, log=lambda _: None)
        result = collector._collect_monthly_direct(REQUEST)
        self.assertEqual(result["format"], "xlsx")
        self.assertFalse(context_handlers)
        self.assertFalse(popup.handlers["download"])

    def test_query_with_filtered_status_stops_before_export(self):
        page = ScopedPage()
        page.body["params"]["request"]["settleStatusList"] = [1]
        collector = bill.MonthlyBillPageCollector(page, page.profile, self.root, log=lambda _: None)
        with self.assertRaisesRegex(bill.BillCollectionError, "全部状态"):
            collector.apply_request(REQUEST)
        self.assertFalse(page.forwarded)

    def test_invalid_export_or_auth_failure_never_saves_file(self):
        for status, valid, error in ((401, True, bill.AuthenticationRequired), (403, True, bill.BillCollectionError),
                                     (200, False, bill.BillCollectionError)):
            page = ScopedPage()
            page.http_status, page.valid = status, valid
            collector = bill.MonthlyBillPageCollector(page, page.profile, self.root, log=lambda _: None)
            with self.subTest(status=status), self.assertRaises(error):
                collector._collect_monthly_direct(REQUEST)
            self.assertFalse(page.routes)
            self.assertFalse(list(self.root.glob("bill*")))

    def test_acceptance_override_does_not_change_production_verification(self):
        candidate = profile()
        candidate["verified"] = False
        with self.assertRaises(bill.BillCollectionError):
            bill.validate_profile(candidate)
        self.assertIs(bill.validate_profile(candidate, acceptance_only=True), candidate)
        self.assertFalse(candidate["verified"])
        with self.assertRaises(bill.BillCollectionError):
            bill.validate_profile(candidate)

    def test_acceptance_and_switch_flags_cannot_enable_normal_collection(self):
        for args in (["--acceptance"], ["--switch-from", "31029428"],
                     ["--acceptance", "--reuse-session", "--inspect"],
                     ["--acceptance", "--reuse-session", "--observe-controls"]):
            with self.subTest(args=args), redirect_stdout(io.StringIO()):
                self.assertEqual(bill.main(args), 1)


if __name__ == "__main__":
    unittest.main()
