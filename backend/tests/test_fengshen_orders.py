import csv
import datetime as dt
import json
from pathlib import Path
import sys
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from fengshen_bill import AuthenticationRequired, BillCollectionError, CityPopupNotClosed
from fengshen_orders import LEGACY_FILE_HOST, OrderPageCollector, OrderRequest, QUERY_URL, WAYBILL_URL, date_batches, new_task, query_count, query_response_matches, task_rows, secure_file_url, validate_order_profile, waybill_scope
from issue_orders import issue_types
from order_sources import (
    WAYBILL_COLUMNS, VIOLATION_COLUMNS, clean_violations, merge_slices,
    file_hash, prepare_order_files, read_table, validate_slice,
)
import pandas as pd
from profile_fixtures import order_profile


def write_csv(path, columns, rows=(), encoding="utf-8-sig"):
    with Path(path).open("w", encoding=encoding, newline="") as output:
        writer = csv.DictWriter(output, fieldnames=sorted(columns))
        writer.writeheader()
        writer.writerows(rows)


def file_checks(base, files):
    return {key: {"path": name, "bytes": (base / name).stat().st_size, "sha256": file_hash(base / name)}
            for key, name in files.items()}


def waybill(waybill_id="000123456789012345678", rider_id="002", fraud="否", late="否"):
    row = {key: "" for key in WAYBILL_COLUMNS}
    row.update({"运单id": waybill_id, "骑手id": rider_id, "骑手名称": "测试骑手", "站点名称": "泉州测试站",
                "运单完成时间": "2026-08-16 10:00:00", "欺诈是否成立": fraud,
                "运单状态": "配送成功", "运单类型": "即时单", "是否超平台期望时间": late,
                "平台期望时间": "2026-08-16 09:00:00", "配送标品": "普通", "订单来源": "普通",
                "超平台期望送达时长": "01:00:00", "是否超骑手T": "否", "骑手考核时间": "2026-08-16 09:00:00",
                "是否超用户T": "否", "用户期望时间": "2026-08-16 09:00:00"})
    return row


def violation(number="v1", waybill_id="other", rider_id="999"):
    row = {key: "" for key in VIOLATION_COLUMNS}
    row.update({"违规编号": number, "违规时间": "2026-08-16 11:00:00", "运单号": waybill_id,
                "团队名称": "泉州测试站", "骑手ID": rider_id, "骑手名称": "测试骑手",
                "违规分类": "差评", "违规类型": "差评", "违规原因": "测试", "违规状态": "成立",
                "申诉状态": "未申诉", "处罚": "-2.50元"})
    return row


class OrderTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(dir=Path(__file__).parent)
        self.root = Path(self.tmp.name)
        self.request = OrderRequest("2026-08-16", "2026-08-20", "31029436")
        self.profile = order_profile()

    def tearDown(self):
        self.tmp.cleanup()

    def test_inclusive_five_day_batches_have_no_gaps_or_overlap(self):
        self.assertEqual(date_batches("2026-08-16", "2026-08-31", dt.date(2026, 10, 11)), [
            ("2026-08-16", "2026-08-20"), ("2026-08-21", "2026-08-25"),
            ("2026-08-26", "2026-08-30"), ("2026-08-31", "2026-08-31")])

    def test_sixty_day_window_is_checked_before_collection(self):
        today = dt.date(2026, 10, 11)
        self.assertEqual(date_batches("2026-08-13", "2026-08-13", today), [("2026-08-13", "2026-08-13")])
        for start, end in (("2026-08-12", "2026-08-20"), ("2026-10-11", "2026-10-12")):
            with self.subTest(start=start), self.assertRaisesRegex(BillCollectionError, "近 60"):
                date_batches(start, end, today)

    def test_reversed_or_six_day_batch_is_rejected(self):
        for start, end in (("2026-08-20", "2026-08-16"), ("2026-08-16", "2026-08-21")):
            with self.assertRaises(BillCollectionError):
                OrderRequest(start, end, "31029436")

    def test_timestamps_include_the_whole_last_day_in_shanghai(self):
        self.assertEqual(self.request.timestamps, (1786809600000, 1787241599000))

    def test_unverified_profile_is_only_usable_in_isolated_acceptance(self):
        with self.assertRaises(BillCollectionError):
            validate_order_profile({**self.profile, "verified": False})
        validate_order_profile(self.profile, acceptance_only=True)

    def test_profile_cannot_use_other_time_basis_or_city_group_mode(self):
        for key, value in (("time_basis", "tracking_create"), ("selection_mode", "all"), ("all_city_riders", False)):
            with self.assertRaises(BillCollectionError):
                validate_order_profile({**self.profile, key: value}, acceptance_only=True)

    def body(self):
        first, last = self.request.timestamps
        return {"params": {"request": {"trackingFinishStart": first, "trackingFinishEnd": last,
                "trackingFinishTimePeriodList": ["0-86400"], "trackingStateKey": "all", "trackingLabelKey": "all", "exportType": 1}}}

    def test_scope_accepts_only_completed_dates_and_unrestricted_city_riders(self):
        body = self.body()
        self.assertTrue(waybill_scope(body, self.request, self.profile, export=True))
        for key, value in (("trackingFinishEnd", 0), ("knightInfo", "001"), ("teamIds", [1]),
                           ("isCheat", 1), ("trackingStateKey", "completed"), ("trackingLabelKey", "late"),
                           ("trackingCreatedStart", self.request.timestamps[0]), ("exportType", True)):
            changed = self.body()
            changed["params"]["request"][key] = value
            self.assertFalse(waybill_scope(changed, self.request, self.profile, export=True), key)

    def test_tasks_are_not_selected_by_first_row(self):
        old = {"id": 10, "exportTime": 1000}
        unrelated = {"id": 11, "exportTime": 1000}
        fresh = {"id": 12, "exportTime": 10000}
        self.assertEqual(new_task({"10"}, [old, unrelated, fresh], 10000, 11000)["id"], 12)

    def test_observed_browser_export_omits_export_type(self):
        body = self.body()
        del body["params"]["request"]["exportType"]
        self.assertTrue(waybill_scope(body, self.request, self.profile, export=True))
        for value in (False, 0, 2, None):
            body["params"]["request"]["exportType"] = value
            self.assertFalse(waybill_scope(body, self.request, self.profile, export=True))

    def test_malformed_scope_payload_is_rejected(self):
        for payload in (None, [], {}, {"params": None}, {"params": []}, {"params": {"request": None}}):
            self.assertFalse(waybill_scope(payload, self.request, self.profile, export=True))

    def test_only_observed_legacy_file_host_can_be_upgraded_to_https(self):
        self.assertEqual(secure_file_url("http://" + LEGACY_FILE_HOST + "/test.csv?q=signed"),
                         "https://" + LEGACY_FILE_HOST + "/test.csv?q=signed")
        for url in (None, "http://other.aliyuncs.com/test.csv", "https://ele.me.evil.test/a",
                    "https://user:password@files.ele.me/a", "https://files.ele.me:8080/a",
                    "https://files.ele.me/a#fragment", "file:///test.csv"):
            with self.assertRaises(BillCollectionError):
                secure_file_url(url)

    def test_multiple_new_tasks_or_duplicate_ids_stop(self):
        with self.assertRaises(BillCollectionError):
            new_task(set(), [{"id": 1, "exportTime": 10000}, {"id": 2, "exportTime": 10000}], 10000, 11000)
        with self.assertRaises(BillCollectionError):
            task_rows({"code": 200, "result": {"code": "200", "data": {"data": [{"id": 1}, {"id": 1}]}}})

    def test_query_count_requires_target_city_and_valid_total(self):
        payload = lambda total, rows: {"code": 200, "result": {"code": "200", "data": {"total": total, "data": rows}}}
        self.assertEqual(query_count(payload(0, []), "31029436"), 0)
        self.assertEqual(query_count(payload(2, [{"agencyId": 31029436}]), "31029436"), 2)
        for total, rows in ((True, []), (-1, []), (0, [{"agencyId": 31029436}]), (1, [{"agencyId": 31021076}])):
            with self.assertRaises(BillCollectionError):
                query_count(payload(total, rows), "31029436")

    def test_query_response_ignores_delayed_responses_for_other_dates(self):
        response = SimpleNamespace(url=QUERY_URL + "?callback=observed", request=SimpleNamespace(method="POST", post_data_json=self.body()))
        self.assertTrue(query_response_matches(response, self.request))
        other = OrderRequest("2026-08-21", "2026-08-25", self.request.agency_id)
        self.assertFalse(query_response_matches(response, other))
        response.request.post_data_json = {"params": None}
        self.assertFalse(query_response_matches(response, self.request))
        response.request.post_data_json = self.body()
        response.request.post_data_json["params"]["request"]["knightInfo"] = "restricted"
        self.assertTrue(query_response_matches(response, self.request))
        self.assertFalse(waybill_scope(response.request.post_data_json, self.request, self.profile))

    def query_collector(self):
        collector = self.collector()
        collector.page = Mock(url=WAYBILL_URL)
        collector.cancelled = threading.Event()
        collector.output_dir.mkdir(parents=True)
        collector.query_stage = "query"
        collector.last_control = "query_button"
        return collector

    def test_readonly_timeout_recovers_without_export_submission(self):
        from playwright.sync_api import TimeoutError
        collector = self.query_collector()
        with patch.object(collector, "_apply_request_once", side_effect=[TimeoutError("secret signed URL"), 7]) as query, \
             patch.object(collector, "_export_waybills") as export:
            self.assertEqual(collector.apply_request(self.request), 7)
        self.assertEqual(query.call_count, 2)
        export.assert_not_called()
        collector.page.goto.assert_called_once_with(WAYBILL_URL, wait_until="domcontentloaded", timeout=60000)
        failure = (collector.output_dir / "query_failure_2026-08-16_2026-08-20_1.json").read_text(encoding="utf-8")
        self.assertNotIn("secret", failure)
        self.assertEqual(json.loads(failure)["stage"], "query")
        self.assertEqual(json.loads((collector.output_dir / "query_state.json").read_text(encoding="utf-8"))["attempt"], 2)

    def test_readonly_retries_are_bounded_and_explain_dates_and_stage(self):
        from playwright.sync_api import TimeoutError
        collector = self.query_collector()
        with patch.object(collector, "_apply_request_once", side_effect=TimeoutError("timeout")) as query:
            with self.assertRaisesRegex(BillCollectionError, "2026-08-16.*3 次只读"):
                collector.apply_request(self.request)
        self.assertEqual(query.call_count, 3)
        self.assertEqual(collector.page.goto.call_count, 2)
        self.assertEqual(len(list(collector.output_dir.glob("query_failure_*.json"))), 3)

    def test_scope_failure_is_never_retried(self):
        collector = self.query_collector()
        with patch.object(collector, "_apply_request_once", side_effect=BillCollectionError("wrong scope")) as query:
            with self.assertRaisesRegex(BillCollectionError, "wrong scope"):
                collector.apply_request(self.request)
        self.assertEqual(query.call_count, 1)
        collector.page.goto.assert_not_called()

    def test_stuck_city_popup_recovers_only_during_readonly_query(self):
        collector = self.query_collector()
        collector.query_stage = "city"
        with patch.object(collector, "_apply_request_once", side_effect=[CityPopupNotClosed("stuck"), 9]) as query, \
             patch.object(collector, "_export_waybills") as export:
            self.assertEqual(collector.apply_request(self.request), 9)
        self.assertEqual(query.call_count, 2)
        export.assert_not_called()

    def test_cancellation_during_timeout_does_not_replay_query(self):
        from playwright.sync_api import TimeoutError
        collector = self.query_collector()
        def timeout(request):
            collector.cancelled.set()
            raise TimeoutError("timeout")
        with patch.object(collector, "_apply_request_once", side_effect=timeout) as query:
            with self.assertRaisesRegex(BillCollectionError, "取消"):
                collector.apply_request(self.request)
        self.assertEqual(query.call_count, 1)
        collector.page.goto.assert_not_called()

    def test_timeout_on_login_page_triggers_auth_not_query_retry(self):
        from playwright.sync_api import TimeoutError
        collector = self.query_collector()
        def timeout(request):
            collector.page.url = "https://mozi-login.alibaba-inc.com/"
            raise TimeoutError("timeout")
        with patch.object(collector, "_apply_request_once", side_effect=timeout):
            with self.assertRaises(AuthenticationRequired):
                collector.apply_request(self.request)
        collector.page.goto.assert_not_called()

    def test_reading_retains_long_text_identifiers(self):
        path = self.root / "orders.csv"
        write_csv(path, WAYBILL_COLUMNS, [waybill()])
        rows = validate_slice(read_table(path, WAYBILL_COLUMNS), self.request, "运单完成时间", ("运单id", "骑手id"))
        self.assertEqual(rows.iloc[0]["运单id"], "000123456789012345678")
        self.assertEqual(rows.iloc[0]["骑手id"], "002")

    def test_legacy_text_normalization_preserves_ids_and_internal_whitespace(self):
        row = violation(waybill_id="000123456789012345678", rider_id="002")
        row["违规原因"] = "内部 空格\t仍保留"
        padded = {key: " \t" + value + "\t\u3000" for key, value in row.items()}
        for encoding in ("utf-8-sig", "gb18030"):
            with self.subTest(encoding=encoding):
                path = self.root / (encoding + ".csv")
                write_csv(path, VIOLATION_COLUMNS, [padded], encoding=encoding)
                result = read_table(path, VIOLATION_COLUMNS)
                self.assertEqual(result.iloc[0].to_dict(), row)

    def test_invalid_file_header_is_not_empty(self):
        path = self.root / "orders.csv"
        write_csv(path, {"wrong"})
        with self.assertRaises(BillCollectionError):
            read_table(path, WAYBILL_COLUMNS)

    def test_out_of_batch_date_and_other_city_are_rejected(self):
        for fields in ({"运单完成时间": "2026-08-21 00:00:00"}, {"代理商ID": "31021076"}):
            frame = pd.DataFrame([{**waybill(), **fields}])
            with self.assertRaises(BillCollectionError):
                validate_slice(frame, self.request, "运单完成时间", ("运单id", "骑手id"))

    def test_missing_or_numeric_long_ids_are_rejected(self):
        for value in ("", 123456789012345678, 1e18):
            with self.assertRaises(BillCollectionError):
                validate_slice(pd.DataFrame([waybill(waybill_id=value)]), self.request, "运单完成时间", ("运单id", "骑手id"))

    def test_unassigned_nonfraud_failed_waybill_is_retained(self):
        row = {**waybill(rider_id=""), "运单状态": "配送失败"}
        result = validate_slice(pd.DataFrame([row]), self.request, "运单完成时间", ("运单id", "骑手id"))
        self.assertEqual(len(result), 1)
        for changes in ({"欺诈是否成立": "是"}, {"运单状态": "配送成功"}):
            with self.assertRaises(BillCollectionError):
                validate_slice(pd.DataFrame([{**row, **changes}]), self.request, "运单完成时间", ("运单id", "骑手id"))

    def test_identical_duplicates_collapse_but_conflicting_ids_stop(self):
        frame = pd.DataFrame([waybill()])
        self.assertEqual(len(merge_slices([frame, frame.copy()], "运单id")), 1)
        with self.assertRaises(BillCollectionError):
            merge_slices([frame, pd.DataFrame([waybill(rider_id="other")])], "运单id")

    def test_multiple_events_for_one_waybill_are_not_collapsed(self):
        frame = pd.DataFrame([violation("1"), violation("2")])
        self.assertEqual(len(merge_slices([frame], "违规编号")), 2)

    def test_penalty_conversion_keeps_negative_amount_and_id(self):
        frame = clean_violations(pd.DataFrame([violation()]))
        self.assertEqual((frame.iloc[0]["处罚金额"], frame.iloc[0]["骑手id"]), ("-2.50", "999"))

    def bundle(self, orders=(), penalties=()):
        raw, inputs = self.root / "raw", self.root / "input"
        base = raw / "issue_orders" / "2026-08-16_2026-08-20"
        base.mkdir(parents=True)
        inputs.mkdir()
        write_csv(base / "orders.csv", WAYBILL_COLUMNS, orders)
        write_csv(base / "penalties.csv", VIOLATION_COLUMNS, penalties)
        record = {"dataset": "issue_orders", "status": "success", "agency_id": "31029436", "start": "2026-08-16",
                  "end": "2026-08-20", "time_basis": "tracking_finish", "merchant_group": "物流合作商", "all_city_riders": True,
                  "files": {"waybills": "orders.csv", "violations": "penalties.csv"}}
        record["file_checks"] = file_checks(base, record["files"])
        plan = SimpleNamespace(city="泉州", agency_id="31029436")
        return record, raw, inputs, plan

    def test_header_only_sources_produce_valid_empty_fraud_and_problem_files(self):
        record, raw, inputs, plan = self.bundle()
        result = prepare_order_files([record], raw, inputs, plan, [("2026-08-16", "2026-08-20")])
        self.assertEqual(result["欺诈单"]["status"], "empty")
        self.assertEqual(result["问题单"]["status"], "empty")
        self.assertTrue((inputs / "泉州-问题单_auto.csv").is_file())

    def test_service_categories_and_excluded_statuses_with_export_whitespace(self):
        penalties = []
        for category in ("差评", "投诉", "取消"):
            for suffix, status, appeal in (("valid", "成立", "申诉失败"),
                                           ("invalid", "不成立", "未申诉"),
                                           ("appealed", "成立", "申诉成功")):
                row = violation(category + suffix, category + suffix)
                row.update({"违规分类": category, "违规状态": status, "申诉状态": appeal})
                penalties.append({key: value + "\t" for key, value in row.items()})
        record, raw, inputs, plan = self.bundle([waybill(late="是")], penalties)
        result = prepare_order_files([record], raw, inputs, plan, [("2026-08-16", "2026-08-20")])
        with (inputs / "泉州-问题单_auto.csv").open(encoding="utf-8-sig", newline="") as source:
            rows = list(csv.DictReader(source))
        self.assertEqual({row["类型"] for row in rows}, {"差评", "投诉", "物流责", "不准时单"})
        self.assertEqual(len(rows), 4)
        self.assertEqual({row["运单号"] for row in rows if row["类型"] != "不准时单"},
                         {"差评valid", "投诉valid", "取消valid"})
        self.assertEqual(result["问题单"]["type_counts"], {"差评": 1, "投诉": 1, "物流责": 1, "不准时单": 1})
        self.assertEqual(result["问题单"]["service_excluded_rows"], 6)

    def test_service_and_waybill_dates_use_one_daily_csv_format(self):
        record, raw, inputs, plan = self.bundle([waybill(late="是")], [violation()])
        prepare_order_files([record], raw, inputs, plan, [("2026-08-16", "2026-08-20")])
        with (inputs / "泉州-问题单_auto.csv").open(encoding="utf-8-sig", newline="") as source:
            dates = [row["日期"] for row in csv.DictReader(source)]
        self.assertEqual(dates, ["2026-08-16", "2026-08-16"])
        self.assertFalse(pd.to_datetime(pd.Series(dates), errors="coerce").isna().any())

    def test_padded_fraud_and_service_ids_do_not_duplicate_problem_records(self):
        order = {key: value + "\t" for key, value in waybill(fraud="是", late="是").items()}
        penalty = {key: value + "\t" for key, value in violation("v1", waybill()["运单id"]).items()}
        record, raw, inputs, plan = self.bundle([order], [penalty])
        result = prepare_order_files([record], raw, inputs, plan, [("2026-08-16", "2026-08-20")])
        self.assertEqual((result["欺诈单"]["rows"], result["问题单"]["rows"]), (1, 0))

    def test_empty_batch_headers_can_merge_with_full_export_headers(self):
        full = pd.DataFrame([{**waybill(), "商id": "31029436"}])
        empty = pd.DataFrame(columns=sorted(WAYBILL_COLUMNS))
        self.assertEqual(len(merge_slices([empty, full, empty], "运单id")), 1)

    def test_changed_download_or_incorrect_platform_count_stops(self):
        record, raw, inputs, plan = self.bundle([waybill()])
        for modified in ({**record, "file_checks": {}}, {**record, "expected_waybills": 2}):
            with self.assertRaises(BillCollectionError):
                prepare_order_files([modified], raw, inputs, plan, [("2026-08-16", "2026-08-20")])
        path = raw / "issue_orders" / "2026-08-16_2026-08-20" / "orders.csv"
        with path.open("ab") as source:
            source.write(b"\n")
        with self.assertRaises(BillCollectionError):
            prepare_order_files([record], raw, inputs, plan, [("2026-08-16", "2026-08-20")])
        self.assertFalse(list(inputs.iterdir()))

    def test_cross_day_total_discrepancy_requires_every_daily_count_to_match(self):
        record, raw, inputs, plan = self.bundle([waybill()])
        daily = {"2026-08-" + str(day): int(day == 16) for day in range(16, 21)}
        record.update(expected_waybills=2, expected_waybills_by_date=daily)
        result = prepare_order_files([record], raw, inputs, plan, [("2026-08-16", "2026-08-20")])
        self.assertEqual(result["order_batches"][0]["count_basis"], "daily_verified")
        self.assertTrue(result["order_batches"][0]["batch_total_inconsistent"])

    def test_incomplete_or_mismatched_daily_counts_stop(self):
        record, raw, inputs, plan = self.bundle([waybill()])
        daily = {"2026-08-" + str(day): int(day == 16) for day in range(16, 21)}
        for counts in ({}, {**daily, "2026-08-16": 0}, {**daily, "2026-08-16": True}):
            record.update(expected_waybills=1, expected_waybills_by_date=counts)
            with self.assertRaises(BillCollectionError):
                prepare_order_files([record], raw, inputs, plan, [("2026-08-16", "2026-08-20")])
        self.assertFalse(list(inputs.iterdir()))

    def test_live_snapshot_allows_growth_without_replacing_original_query_counts(self):
        record, raw, inputs, plan = self.bundle([waybill(), waybill(waybill_id="another")])
        day = "2026-08-16"
        daily = {"2026-08-" + str(n): int(n == 16) for n in range(16, 21)}
        stamp = dt.datetime(2026, 8, 16, 10, tzinfo=dt.timezone(dt.timedelta(hours=8))).timestamp()
        record.update(task_id="123", expected_waybills=1, expected_waybills_by_date=daily,
                      live_day_snapshot={"date": day, "before": 1, "after": 3, "task_id": "123",
                                         "started_at": stamp, "checked_at": stamp + 30})
        result = prepare_order_files([record], raw, inputs, plan, [("2026-08-16", "2026-08-20")])
        proof = result["order_batches"][0]
        self.assertEqual(proof["count_basis"], "live_snapshot_verified")
        self.assertEqual(proof["live_day_snapshot"]["exported"], 2)
        self.assertEqual(record["expected_waybills_by_date"][day], 1)

    def test_fraud_is_removed_from_problems_but_nonapplicants_are_retained(self):
        record, raw, inputs, plan = self.bundle([waybill(fraud="是", late="是")], [violation("1", waybill()["运单id"]), violation("2")])
        result = prepare_order_files([record], raw, inputs, plan, [("2026-08-16", "2026-08-20")])
        self.assertEqual((result["欺诈单"]["rows"], result["问题单"]["rows"]), (1, 1))
        with (inputs / "泉州-问题单_auto.csv").open(encoding="utf-8-sig", newline="") as source:
            row = next(csv.DictReader(source))
        self.assertEqual(row["骑手id"], "999")

    def test_old_notpunctual_and_city_type_rules_are_preserved(self):
        record, raw, inputs, plan = self.bundle([waybill(late="是")])
        result = prepare_order_files([record], raw, inputs, plan, [("2026-08-16", "2026-08-20")])
        self.assertEqual(result["问题单"]["rows"], 1)
        self.assertIn("T10", issue_types("东莞"))
        self.assertIn("用户T", issue_types("安宁"))
        self.assertIn("不准时单", issue_types("泉州"))

    def test_partial_or_unconfirmed_batch_stops_before_output(self):
        record, raw, inputs, plan = self.bundle()
        for records in ([], [{**record, "all_city_riders": False}], [{**record, "time_basis": "tracking_create"}],
                        [{**record, "files": {"waybills": "../orders.csv", "violations": "penalties.csv"}}]):
            with self.assertRaises(BillCollectionError):
                prepare_order_files(records, raw, inputs, plan, [("2026-08-16", "2026-08-20")])
        self.assertFalse(list(inputs.iterdir()))

    def collector(self, auth=None):
        return OrderPageCollector(SimpleNamespace(), self.profile, self.root / "raw", log=lambda _: None,
                                  auth=auth, acceptance_only=True)

    def test_known_task_can_resume_after_login_without_creating_another_task(self):
        auth = Mock()
        collector = self.collector(auth)
        calls = []
        def export(request, state):
            calls.append(dict(state))
            if len(calls) == 1:
                state.update(task_id="123", submitted=True)
                raise AuthenticationRequired("expired")
            return collector._empty_file("orders.csv", WAYBILL_COLUMNS)
        with patch("fengshen_orders.date_batches", return_value=[(self.request.start, self.request.end)]), \
             patch.object(collector, "_export_waybills", side_effect=export), \
             patch.object(collector, "_check_agency_context"), \
             patch.object(collector, "_post", return_value={"result": {"data": {"fileUrl": ""}}}):
            result = collector.collect_batches(self.request.start, self.request.end)
        auth.assert_called_once_with(force=True)
        self.assertEqual(calls[1]["task_id"], "123")
        self.assertEqual(result[0]["task_id"], "123")

    def test_unconfirmed_submission_is_never_retried_after_expiry(self):
        auth = Mock()
        collector = self.collector(auth)
        def export(request, state):
            state["submitted"] = True
            raise AuthenticationRequired("expired")
        with patch("fengshen_orders.date_batches", return_value=[(self.request.start, self.request.end)]), \
             patch.object(collector, "_export_waybills", side_effect=export) as submit:
            with self.assertRaises(BillCollectionError):
                collector.collect_batches(self.request.start, self.request.end)
        auth.assert_not_called()
        self.assertEqual(submit.call_count, 1)
        self.assertFalse(list((self.root / "raw").rglob("manifest.json")))

    def test_cancellation_blocks_network_request(self):
        collector = self.collector()
        collector.cancelled = threading.Event()
        collector.cancelled.set()
        with self.assertRaisesRegex(BillCollectionError, "取消"):
            collector._post("https://example.test", {})


if __name__ == "__main__":
    unittest.main()
