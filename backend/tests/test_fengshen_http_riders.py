import json
from pathlib import Path
import sys
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

sys.path.insert(0, str(Path(__file__).parents[1]))
from fengshen_http import FengshenHttpClient, HttpTransportError, FILE_METHODS
from fengshen_http_riders import (RiderHttpCollector, DETAIL_DIRECT_EXPORT, detail_coverage_gap,
                                  detail_no_data_message)


class DetailCoverageTests(unittest.TestCase):
    plan = SimpleNamespace(city="台州", start="2026-10-01", end="2026-10-31")

    def test_partial_sync_export_is_detected(self):
        self.assertEqual(detail_coverage_gap({"rows": 834, "date_max": "2026-10-09"}, self.plan), 22)

    def test_current_month_data_lag_is_allowed(self):
        self.assertEqual(detail_coverage_gap({"rows": 1, "date_max": "2026-10-29"}, self.plan), 2)

    def test_empty_or_unparsed_export_has_no_coverage_claim(self):
        self.assertIsNone(detail_coverage_gap({"rows": 0, "date_max": "2026-10-09"}, self.plan))
        self.assertIsNone(detail_coverage_gap({"rows": 1, "date_max": None}, self.plan))

    def test_platform_no_data_payload_is_recognized(self):
        self.assertEqual(detail_no_data_message(
            {"code": 200, "data": {"code": 2, "message": "没有搜索到任何数据"}}), "没有搜索到任何数据")
        self.assertIsNone(detail_no_data_message({"code": 200, "data": {"code": 4, "message": "使用同步导出"}}))

    def test_zero_total_range_fails_before_export(self):
        from types import SimpleNamespace
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as temporary:
            client = Mock(spec=FengshenHttpClient, cancelled=threading.Event())
            client.request_json.return_value = {"code": 200, "data": {"totalCount": 0}}
            collector = RiderHttpCollector(client)
            plan = SimpleNamespace(city="深圳", agency_id="2", start="2026-11-01", end="2026-11-15", month="2026-11")
            with self.assertRaises(HttpTransportError) as raised:
                collector._detail(plan, Path(temporary), {"1": "站点"}, {"1": "2"})
            self.assertIn("没有骑手明细数据", str(raised.exception))
            client.submit_once.assert_not_called()

    def test_platform_no_data_after_submit_is_not_reported_as_ambiguous_task(self):
        from types import SimpleNamespace
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as temporary:
            client = Mock(spec=FengshenHttpClient, cancelled=threading.Event())
            client.request_json.side_effect = [
                {"code": 200, "data": {"totalCount": 1}},
                {"code": 200, "data": 1},
                {"code": 200, "data": {"list": [], "totalCount": 0, "pageNum": 1, "pageSize": 10}},
            ]
            client.submit_once.return_value = (
                {"code": 200, "data": {"code": 2, "message": "没有搜索到任何数据"}}, {})
            collector = RiderHttpCollector(client)
            collector._fields = Mock(return_value=["validCompleteCount"])
            plan = SimpleNamespace(city="深圳", agency_id="2", start="2026-11-01", end="2026-11-15", month="2026-11")
            with self.assertRaises(HttpTransportError) as raised:
                collector._detail(plan, Path(temporary), {"1": "站点"}, {"1": "2"})
            self.assertIn("没有搜索到任何数据", str(raised.exception))
            self.assertNotIn("任务编号", str(raised.exception))


class RiderHttpRecoveryTests(unittest.TestCase):
    def test_original_direct_fallback_is_allowed_once_and_never_repeats_async_export(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as temporary:
            source = Path(temporary) / "source"
            source.mkdir()
            plan = SimpleNamespace(city="泉州", agency_id="2", start="2026-10-14", end="2026-10-14", month="2026-10")
            body = {"teamIds": [1], "startAt": plan.start, "endAt": plan.end,
                    "exportType": 2, "fields": ["validCompleteCount"]}
            receipt = {"transport": "http", "status": "direct_export_required", "agency_id": "2",
                       "start": plan.start, "end": plan.end, "request_observed": True,
                       "selected_team_ids": ["1"], "existing_task_ids": [], "fields": body["fields"],
                       "submitted_at": "2026-10-17T23:00:00+08:00", "http_status": 200, "response_code": 200}
            ledger = {"transport": "http", "submission_state": "submitted",
                      "scope": {"kind": "rider_detail", "agency_id": "2", "request": body}}
            (source / "detail_submission.json").write_text(json.dumps(receipt), encoding="utf-8")
            (source / "detail_http_submission.json").write_text(json.dumps(ledger), encoding="utf-8")
            client = Mock(spec=FengshenHttpClient, cancelled=threading.Event())
            collector = RiderHttpCollector(client)
            collector._teams = Mock(return_value=({"1": "test"}, {"1": "2"}))
            collector._download_sync = Mock(return_value={"status": "validated"})
            collector.resume_detail(plan, Path(temporary) / "result", source)
            self.assertEqual(FILE_METHODS[DETAIL_DIRECT_EXPORT], "POST")
            self.assertEqual(collector._download_sync.call_args.kwargs["receipt_path"], source / "source_http_submission.json")
            client.submit_once.assert_not_called()
            (source / "source_http_submission.json").write_text("{}", encoding="utf-8")
            with self.assertRaises(HttpTransportError):
                collector.resume_detail(plan, Path(temporary) / "second", source)
            collector._download_sync.assert_called_once()


class RiderCrossCityInfoTests(unittest.TestCase):
    def test_cross_city_rider_info_receipt_skips_single_city_proof(self):
        from unittest.mock import patch
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as temporary:
            output = Path(temporary)
            target = output / "骑手信息_2026-10-01_2026-10-31.xlsx"
            target.write_bytes(b"PK")
            client = Mock(spec=FengshenHttpClient, cancelled=threading.Event())
            collector = RiderHttpCollector(client)
            plan = SimpleNamespace(city="上海", agency_id="2", start="2026-10-01",
                                   end="2026-10-31", month="2026-10")
            teams, agencies = {"1": "上海站", "2": "广州站"}, {"1": "2", "2": "3"}
            info = {"rows": 2, "bytes": 10, "sha256": "a" * 64, "status": "validated",
                    "format": "xlsx", "team_count": 2, "path": target.name}
            with patch("fengshen_http_riders.validate_document", return_value=dict(info)):
                result = collector._finish(target, "rider_info", plan, teams, agencies, cross_city=True)
            self.assertEqual(result["scope"], "platform_batch")
            receipt = json.loads((output / "source_receipt.json").read_text(encoding="utf-8"))
            self.assertEqual(receipt["team_agency_ids"], agencies)
            self.assertTrue(receipt["snapshot_only"])


class RiderTeamsScopeTests(unittest.TestCase):
    PLAN = SimpleNamespace(city="上海", agency_id="2", start="2026-09-01", end="2026-09-30", month="2026-09")

    @staticmethod
    def page(agency_id, name="站点"):
        return {"result": {"data": [{"id": 1, "agencyId": agency_id, "team_name": name}]}}

    def collector(self, pages):
        client = Mock(spec=FengshenHttpClient, cancelled=threading.Event())
        client.request_json = Mock(side_effect=list(pages))
        collector = RiderHttpCollector(client)
        collector.scope_recheck_delay = 0
        return collector, client

    def test_stale_agency_page_is_requeried_after_city_reselect(self):
        # Observed 2026-10-22: getTeamsAll now returns only the currently
        # selected agency's teams; right after a switch it briefly still
        # served the previous agency, failing 7 of 10 cities in one batch.
        collector, client = self.collector([self.page(9, "旧合作商站点"), self.page(2)])
        teams, agencies = collector._teams(self.PLAN)
        self.assertEqual(teams, {"1": "站点"})
        self.assertEqual(agencies, {"1": "2"})
        self.assertEqual(client.request_json.call_count, 2)
        client.select_city.assert_called_once_with("2")

    def test_persistent_stale_page_fails_without_export(self):
        collector, client = self.collector([self.page(9)] * 3)
        with self.assertRaises(Exception) as raised:
            collector._teams(self.PLAN)
        self.assertIn("站点", str(raised.exception))
        self.assertEqual(client.request_json.call_count, 3)
        self.assertEqual(client.select_city.call_count, 2)


if __name__ == "__main__":
    unittest.main()
