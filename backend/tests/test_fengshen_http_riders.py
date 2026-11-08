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
from fengshen_http_riders import RiderHttpCollector, DETAIL_DIRECT_EXPORT


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
