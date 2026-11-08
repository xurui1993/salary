import datetime
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from fengshen_bill import (
    AuthenticationRequired, BillCollectionError, BillPageCollector, BillRequest,
    DAILY_CREATE_URL, DAILY_DOWNLOAD_URL, DAILY_QUERY_URL, daily_create_matches, daily_download_matches,
    daily_export_scope, daily_query_scope, daily_tasks, new_daily_task, validate_profile,
)
from test_fengshen_bill import FakeLocator, FakePage, FakePending
import test_parttime_source as fixtures


REQUEST = BillRequest("2026-08-16", "2026-08-31", False, False, "31029436")
NOW = 1_791_462_000


def profile():
    result = fixtures.TargetSelectionTests().profile()
    result.update({
        "expected_agency_id": REQUEST.agency_id, "task_identity_mode": "list_delta",
        "export_response_url": DAILY_CREATE_URL, "task_query_url": DAILY_QUERY_URL,
        "task_download_url": DAILY_DOWNLOAD_URL, "task_rows": "#rows",
        "task_title": "#title", "task_operation_time": "#time",
    })
    result.pop("task_row")
    result.pop("export_task_id_path")
    return result


def task(identity, timestamp=NOW, title="总部账单-代理商账单-08-16-08-31", status="成功"):
    return {"id": identity, "agentId": None, "title": title, "operationDate": timestamp * 1000,
            "status": 1, "billType": 1, "statusName": status}


def payload(tasks):
    return {"total": len(tasks), "data": tasks}


def scope_payload():
    return {"periodType": 0, "billType": 1, "agentIds": [31029436], "subBillTypes": [2, 1],
            "startDate": REQUEST.start, "endDate": REQUEST.end}


class DailyDeltaContractTests(unittest.TestCase):
    def test_observed_create_query_cannot_expand_agency_scope(self):
        self.assertTrue(daily_create_matches(DAILY_CREATE_URL + "?agentId=31029436", "31029436"))
        for query in ("?agentId=31029428", "?agentId=31029436&agentId=31029428", "?agentId=", "?other=31029436"):
            self.assertFalse(daily_create_matches(DAILY_CREATE_URL + query, "31029436"))

    def test_actual_non_json_strategy_does_not_require_response_task_id(self):
        self.assertEqual(validate_profile(profile())["task_identity_mode"], "list_delta")

    def test_only_observed_endpoints_and_target_mode_allowed(self):
        for key, value in (("export_response_url", "https://freyja.ele.me/unknown"),
                           ("task_query_url", "https://other.ele.me/query"),
                           ("task_download_url", DAILY_DOWNLOAD_URL + "?id=1"),
                           ("selection_mode", "all"), ("task_rows", "")):
            changed = profile()
            changed[key] = value
            with self.subTest(key=key), self.assertRaises(BillCollectionError):
                validate_profile(changed)

    def test_actual_export_scope_is_checked_not_just_dom(self):
        daily_export_scope(scope_payload(), REQUEST)
        for key, value in (("agentIds", [31029436, 31030156]), ("agentIds", [True]),
                           ("subBillTypes", [1, True]), ("subBillTypes", [1, 2, 3]),
                           ("subBillTypes", [1, {}]), ("startDate", "2026-08-01"),
                           ("endDate", "2026-09-01"), ("periodType", True), ("periodType", 1), ("billType", 2)):
            changed = scope_payload()
            changed[key] = value
            with self.subTest(key=key, value=value), self.assertRaises(BillCollectionError):
                daily_export_scope(changed, REQUEST)

    def test_api_status_mapping_requires_numeric_code_and_known_ui_status(self):
        for mapping in ({"code": True, "label": "成功"}, {"code": 2, "label": "完成"}, {"label": "成功"}):
            candidate = profile()
            candidate["task_api_status_labels"] = {"导出成功": mapping}
            with self.assertRaises(BillCollectionError):
                validate_profile(candidate)

    def test_query_requires_first_page_and_single_target_city(self):
        good = DAILY_QUERY_URL + "?page=1&size=10&agentId=31029436"
        self.assertEqual(daily_query_scope(good, REQUEST.agency_id), (1, 10, REQUEST.agency_id))
        for suffix in ("?page=2&size=10&agentId=31029436", "?page=1&size=10&agentId=31030156",
                       "?page=1&size=10&agentId=31029436&agentId=31030156", "?page=1&size=no&agentId=31029436"):
            with self.subTest(suffix=suffix), self.assertRaises(BillCollectionError):
                daily_query_scope(DAILY_QUERY_URL + suffix, REQUEST.agency_id)

    def test_task_timestamps_accept_seconds_and_milliseconds(self):
        seconds = task(2)
        seconds["operationDate"] = NOW
        for item in (seconds, task(2)):
            self.assertEqual(daily_tasks(payload([item]))[0]["operation_timestamp"], NOW)

    def test_invalid_duplicate_or_unordered_tasks_stop(self):
        bad_time = task(3)
        bad_time["operationDate"] = 123
        for data in (payload([task(2, NOW - 60), task(3)]), payload([task(3), task(3)]), payload([bad_time]),
                     {"data": [], "total": False}, {"data": [], "total": -1}):
            with self.subTest(data=data), self.assertRaises(BillCollectionError):
                daily_tasks(data)

    def test_ids_may_be_out_of_order_within_same_operation_time(self):
        self.assertEqual([row["id"] for row in daily_tasks(payload([task(2), task(3)]))], [2, 3])

    def test_explicit_auth_failure_is_preserved(self):
        with self.assertRaises(AuthenticationRequired):
            daily_tasks({"success": False, "message": "请先登录"})

    def test_exactly_one_new_id_matching_scope_is_required(self):
        old = daily_tasks(payload([task(5, NOW - 3600)]))
        current = daily_tasks(payload([task(6), task(5, NOW - 3600)]))
        self.assertEqual(new_daily_task(old, current, REQUEST, NOW, NOW + 1)["id"], 6)
        self.assertIsNone(new_daily_task(old, old, REQUEST, NOW, NOW + 1))
        for data in ([task(7), task(6), task(5, NOW - 3600)],
                     [task(6, NOW - 20), task(5, NOW - 3600)],
                     [task(6, title="总部账单-代理商账单-09-01-09-15"), task(5, NOW - 3600)],
                     [task(5, NOW - 3600), task(4)]):
            with self.subTest(data=data), self.assertRaises(BillCollectionError):
                new_daily_task(old, daily_tasks(payload(data)), REQUEST, NOW, NOW + 1)

    def test_download_guard_requires_unique_expected_id_and_city(self):
        self.assertTrue(daily_download_matches(DAILY_DOWNLOAD_URL + "?id=6&agentId=31029436", 6, REQUEST.agency_id))
        for url in (DAILY_DOWNLOAD_URL + "?id=5&agentId=31029436",
                    DAILY_DOWNLOAD_URL + "?id=6&id=5&agentId=31029436",
                    DAILY_DOWNLOAD_URL + "?id=6&agentId=31030156",
                    "https://freyja.ele.me.evil.com/api/freyja/bill/export/download?id=6&agentId=31029436"):
            self.assertFalse(daily_download_matches(url, 6, REQUEST.agency_id))


class DeltaPage(FakePage):
    def __init__(self):
        super().__init__(profile())
        self.handlers = {}
        self.context = SimpleNamespace(pages=[self], on=lambda event, handler: None,
                                       remove_listener=lambda event, handler: None)
        self.download.url = "https://download.ele.me/daily.zip"
        self.routes = {}
        self.current = [task(6), task(5, NOW - 3600)]
        self.lists = [payload([task(5, NOW - 3600)]), payload(self.current)]
        self.list_index = 0
        self.query_suffix = "?page=1&size=10&agentId=31029436"
        self.creation_payload = scope_payload()
        self.create_status = 200
        self.create_json = None
        self.download_id = 6
        self.row_duplicates = 1
        self.ui_status = None
        self.blocked = []
        self.forwarded = []
        self.controls["#submit_button"].click = lambda: self.send("POST", DAILY_CREATE_URL, self.creation_payload)

    def send(self, method, url, body=None):
        self.events.append(("request", method, url))
        request = SimpleNamespace(method=method, url=url, post_data_json=body)
        for pattern, handler in list(self.routes.items()):
            if url.startswith(pattern[:-2]):
                route = SimpleNamespace(request=request, continue_=lambda: self.forwarded.append(url),
                                        abort=lambda: self.blocked.append(url))
                handler(route)

    def route(self, pattern, handler):
        self.routes[pattern] = handler

    def on(self, event, handler):
        self.handlers.setdefault(event, []).append(handler)

    def remove_listener(self, event, handler):
        self.handlers[event].remove(handler)

    def unroute(self, pattern, handler):
        self.assert_handler = self.routes.pop(pattern)
        assert self.assert_handler == handler

    def expect_response(self, predicate, timeout):
        index = min(self.list_index, len(self.lists) - 1)
        query = SimpleNamespace(url=DAILY_QUERY_URL + self.query_suffix, status=200,
                                request=SimpleNamespace(method="GET"), json=lambda: self.lists[index])
        def creation_json():
            if self.create_json is None:
                raise ValueError("non json")
            return self.create_json
        create = SimpleNamespace(url=DAILY_CREATE_URL, status=self.create_status,
                                 request=SimpleNamespace(method="POST", post_data_json=self.creation_payload), json=creation_json)
        if predicate(query):
            self.list_index += 1
            return FakePending(query)
        if predicate(create):
            return FakePending(create)
        download = SimpleNamespace(url=DAILY_DOWNLOAD_URL + f"?id={self.download_id}&agentId=31029436", status=200,
                                   request=SimpleNamespace(method="GET"), json=lambda: "https://download.ele.me/daily.zip")
        assert predicate(download)
        return FakePending(download)

    def locator(self, selector):
        if selector != "#rows":
            return super().locator(selector)
        rows = []
        for item in self.current:
            for duplicate in range(self.row_duplicates if item["id"] == 6 else 1):
                key = "#row_" + str(item["id"]) + "_" + str(duplicate)
                row = FakeLocator(self, key)
                for selector_key, text in (("#title", item["title"]),
                                           ("#time", datetime.datetime.fromtimestamp(item["operationDate"] / 1000).strftime("%Y-%m-%d %H:%M:%S")),
                                           ("#task_status", self.ui_status or item["statusName"])):
                    self.controls[key + " " + selector_key] = FakeLocator(self, key + " " + selector_key, text=text)
                button = FakeLocator(self, key + " #task_download")
                def download():
                    self.send("GET", DAILY_DOWNLOAD_URL + f"?id={self.download_id}&agentId=31029436")
                    for handler in self.handlers.get("download", []):
                        handler(self.download)
                button.click = download
                self.controls[key + " #task_download"] = button
                rows.append(row)
        return SimpleNamespace(count=lambda: len(rows), nth=lambda index: rows[index])


class DeltaCollectorTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parent)
        self.root = Path(self.temp.name)
        self.page = DeltaPage()

    def tearDown(self):
        self.temp.cleanup()

    def collect(self, auth=None):
        collector = BillPageCollector(self.page, self.page.profile, self.root / "run", log=lambda _: None,
                                      timeout=2, poll_interval=1, auth=auth)
        collector.apply_request = lambda _: self.page.events.append(("apply",))
        with patch("fengshen_bill.time.time", return_value=NOW), patch("fengshen_bill.time.monotonic", side_effect=lambda: self.page.now):
            return collector.collect(REQUEST)

    def test_non_json_creation_downloads_only_new_task(self):
        manifest = self.collect()
        self.assertEqual((manifest["status"], manifest["task_id"]), ("success", "6"))
        self.assertEqual(len(manifest["files"]), 1)
        self.assertFalse(self.page.blocked)
        self.assertFalse(self.page.routes)
        self.assertEqual(sum(event[:2] == ("request", "POST") for event in self.page.events), 1)
        self.assertTrue(all("id=5&" not in url for url in self.page.forwarded))

    def test_observed_api_and_ui_success_status_mapping(self):
        self.page.profile["task_api_status_labels"] = {"导出成功": {"code": 2, "label": "成功"}}
        self.page.current[0].update(statusName="导出成功", status=2)
        self.page.ui_status = "成功"
        self.assertEqual(self.collect()["status"], "success")

    def test_inconsistent_api_success_code_never_downloads(self):
        self.page.profile["task_api_status_labels"] = {"导出成功": {"code": 2, "label": "成功"}}
        self.page.current[0].update(statusName="导出成功", status=1)
        self.page.ui_status = "成功"
        with self.assertRaisesRegex(BillCollectionError, "状态码"):
            self.collect()
        self.assertFalse(any("/export/download" in url for url in self.page.forwarded))

    def test_resume_downloads_original_task_without_any_create_request(self):
        run = self.root / "run"
        run.mkdir()
        manifest = {"acceptance_only": True, "payroll_executed": False, "production_profile_enabled": False,
                    "status": "waiting_for_new_task", "dataset": "agency_daily", "merchant_group": "物流合作商",
                    "agency_id": REQUEST.agency_id, "start": REQUEST.start, "end": REQUEST.end,
                    "sub_bill_scope": ["配送费", "违规扣款"], "task_id": "6",
                    "created_at": datetime.datetime.fromtimestamp(NOW - 1, datetime.timezone.utc).isoformat()}
        (run / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        self.page.lists = [payload(self.page.current)]
        collector = BillPageCollector(self.page, self.page.profile, run, log=lambda _: None, acceptance_only=True)
        collector._check_agency_context = lambda: None
        with patch("fengshen_bill.time.monotonic", side_effect=lambda: self.page.now):
            result = collector.resume_daily_acceptance(REQUEST)
        self.assertEqual(result["status"], "success")
        self.assertTrue(result["resumed_without_submission"])
        self.assertFalse(any(event[:2] == ("request", "POST") for event in self.page.events))

    def test_wrong_creation_scope_blocked_before_request_goes_out(self):
        self.page.creation_payload["agentIds"] = [31030156]
        with self.assertRaisesRegex(BillCollectionError, "未确认|阻止"):
            self.collect()
        self.assertIn(DAILY_CREATE_URL, self.page.blocked)
        self.assertFalse(self.page.forwarded)
        self.assertFalse(self.page.routes)

    def test_wrong_download_id_is_blocked_before_file_is_saved(self):
        self.page.download_id = 5
        with self.assertRaisesRegex(BillCollectionError, "未保存"):
            self.collect()
        self.assertTrue(self.page.blocked)
        self.assertFalse(list((self.root / "run").glob("bill*")))
        self.assertFalse(self.page.routes)

    def test_duplicate_row_identity_does_not_click_download(self):
        self.page.row_duplicates = 2
        with self.assertRaisesRegex(BillCollectionError, "多行"):
            self.collect()
        self.assertFalse(any("/export/download" in url for url in self.page.forwarded))

    def test_old_task_only_times_out_without_resubmission(self):
        self.page.lists[1] = self.page.lists[0]
        with self.assertRaisesRegex(BillCollectionError, "不下载旧记录"):
            self.collect()
        self.assertEqual(sum(event[:2] == ("request", "POST") for event in self.page.events), 1)
        self.assertFalse(any("/export/download" in url for url in self.page.forwarded))

    def test_multiple_new_tasks_stop(self):
        self.page.lists[1] = payload([task(7), task(6), task(5, NOW - 3600)])
        with self.assertRaisesRegex(BillCollectionError, "多个新"):
            self.collect()

    def test_business_error_stops_even_if_new_task_list_has_an_entry(self):
        self.page.create_json = {"success": False}
        with self.assertRaisesRegex(BillCollectionError, "拒绝导出"):
            self.collect()

    def test_auth_failure_after_submission_does_not_create_second_task(self):
        self.page.lists.insert(1, {"success": False, "message": "请先登录"})
        collector = BillPageCollector(self.page, self.page.profile, self.root / "run", log=lambda _: None,
                                      timeout=2, poll_interval=1, auth=lambda **kwargs: bool(kwargs.get("force")))
        collector.apply_request = lambda _: None
        collector._check_agency_context = lambda: None
        with patch("fengshen_bill.time.time", return_value=NOW), patch("fengshen_bill.time.monotonic", side_effect=lambda: self.page.now):
            result = collector.collect(REQUEST)
        self.assertEqual(result["status"], "success")
        self.assertEqual(sum(event[:2] == ("request", "POST") for event in self.page.events), 1)

    def test_known_task_id_survives_reauthentication(self):
        self.page.lists = [self.page.lists[0], payload([task(6, status="生成中"), task(5, NOW - 3600)]),
                           {"success": False, "message": "请先登录"}, payload(self.page.current)]
        collector = BillPageCollector(self.page, self.page.profile, self.root / "run", log=lambda _: None,
                                      timeout=2, poll_interval=1, auth=lambda **kwargs: bool(kwargs.get("force")))
        collector.apply_request = lambda _: None
        collector._check_agency_context = lambda: None
        with patch("fengshen_bill.time.time", return_value=NOW), patch("fengshen_bill.time.monotonic", side_effect=lambda: self.page.now):
            result = collector.collect(REQUEST)
        self.assertEqual((result["status"], result["task_id"]), ("success", "6"))
        self.assertEqual(sum(event[:2] == ("request", "POST") for event in self.page.events), 1)

    def test_explicit_401_before_creation_reauthenticates_and_continues(self):
        self.page.create_status = 401
        def auth(force=False):
            if force:
                self.page.create_status = 200
                self.page.lists.insert(self.page.list_index, self.page.lists[0])
                return True
            return False
        result = self.collect(auth)
        self.assertEqual(result["status"], "success")
        self.assertEqual(sum(event[:2] == ("request", "POST") for event in self.page.events), 2)

    def test_known_task_disappearing_does_not_switch_to_another_task(self):
        self.page.lists = [self.page.lists[0], payload([task(6, status="生成中"), task(5, NOW - 3600)]),
                           payload([task(7), task(5, NOW - 3600)])]
        with self.assertRaisesRegex(BillCollectionError, "未改选历史任务"):
            self.collect()
        self.assertEqual(sum(event[:2] == ("request", "POST") for event in self.page.events), 1)


if __name__ == "__main__":
    unittest.main()
