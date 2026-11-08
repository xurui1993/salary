"""Recover existing rider exports with mocked list/download events, never submission."""

import csv
import datetime as dt
import io
import json
from pathlib import Path
import sys
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import download_rider_recovery as recovery
from parttime_source import SourceError
from rider_sources import DETAIL_EXPORT, TEAMS_URL, RiderSourceCollector


class ExistingExportRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=Path(__file__).parent)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        from profile_fixtures import rider_profile
        fixture_profile = patch('rider_sources.source_profile', side_effect=rider_profile)
        fixture_profile.start()
        self.addCleanup(fixture_profile.stop)
        self.source, self.raw = self.root / "source", self.root / "recovery"
        self.source.mkdir()
        self.plan = SimpleNamespace(city="测试城市", agency_id="31029436", start="2026-10-01", end="2026-10-15", month="2026-10")
        self.evidence = {"agency_id": self.plan.agency_id, "start": self.plan.start, "end": self.plan.end,
                         "request_observed": True, "http_status": 200, "response_code": 200,
                         "status": "rejected_or_unknown", "selected_team_ids": ["123"], "existing_task_ids": ["100"],
                         "submitted_at": "2026-10-16T12:00:00"}
        self.save_evidence()
        self.handlers, self.guards = {}, {}
        self.page = Mock()
        self.page.url = recovery.EXPORT_LIST_URL
        self.page.frames = []
        self.page.is_closed.return_value = False
        self.page.on.side_effect = lambda event, handler: self.handlers.setdefault(event, []).append(handler)
        self.page.remove_listener.side_effect = lambda event, handler: self.handlers.get(event, []).remove(handler)
        context = self.page.context
        context.pages = [self.page]
        context.route.side_effect = lambda pattern, handler: self.guards.update({pattern: handler})
        context.unroute.side_effect = lambda pattern, handler: self.guards.pop(pattern)
        self.team_payload = {"code": 0, "result": {"code": "200", "data": [
            {"id": 123, "agencyId": int(self.plan.agency_id), "team_name": "测试站"},
            {"id": 456, "agencyId": 31030116, "team_name": "其他城市站"}]}}
        def team_query(url, **kwargs):
            self.assertEqual(url, TEAMS_URL)
            return SimpleNamespace(ok=True, json=lambda: self.team_payload, dispose=lambda: None)
        context.request.post.side_effect = team_query
        self.auth = SimpleNamespace(navigate=Mock(), ensure=Mock())
        self.cancelled = threading.Event()
        self.download = SimpleNamespace(suggested_filename="synthetic.csv", failure=lambda: None, save_as=self.save_download)
        self.rows = []
        self.clicks = []

    def save_evidence(self):
        (self.source / "detail_submission.json").write_text(json.dumps(self.evidence), encoding="utf-8")

    def save_download(self, path):
        content = io.StringIO(newline="")
        csv.writer(content).writerows([["日期", "骑手ID", "团队ID", "团队名称", "有效完成单"],
                                      ["2026-10-05", "001", "123", "测试站", 3]])
        if Path(path).suffix == ".zip":
            with zipfile.ZipFile(path, "w") as archive:
                archive.writestr("part.csv", content.getvalue().encode("utf-8-sig"))
        else:
            Path(path).write_text(content.getvalue(), encoding="utf-8-sig", newline="")

    def row(self, identity="101", created="2026-10-16 12:00:02", state="导出完成"):
        row = Mock()
        row.is_visible.return_value = True
        row.inner_text.return_value = f"{self.plan.start}-{self.plan.end}.骑手数据明细.{identity}.zip {state}"
        row.locator.return_value.nth.return_value.inner_text.return_value = created
        link = row.get_by_text.return_value
        link.count.return_value = 1
        link.is_visible.return_value = True
        def click():
            self.clicks.append(identity)
            for handler in list(self.handlers.get("download", [])):
                handler(self.download)
        link.click.side_effect = click
        return row

    def execute(self):
        frame = Mock(url="https://lpd-service-center.faas.ele.me/#/export-list")
        frame.locator.return_value.all.side_effect = lambda: self.rows
        with patch.object(RiderSourceCollector, "collect", side_effect=AssertionError("must not collect")), \
             patch.object(RiderSourceCollector, "_select_teams", side_effect=AssertionError("must not select")), \
             patch.object(RiderSourceCollector, "_check_agency_context") as city_check, \
             patch.object(RiderSourceCollector, "_detail_list_frame", return_value=frame):
            info = recovery.recover_rider_detail(self.page, self.auth, self.plan, self.raw, self.source, Mock(), self.cancelled)
        city_check.assert_called_once()
        return info

    def test_unknown_task_id_recovers_one_new_matching_task_without_submitting(self):
        original = (self.source / "detail_submission.json").read_bytes()
        self.rows = [self.row("100", "2026-10-16 11:59:00"), self.row()]
        result = self.execute()
        self.assertEqual(self.clicks, ["101"])
        self.assertEqual((result["task_id"], result["rows"], result["scope"]), ("101", 1, "target_city"))
        self.assertEqual(result["team_agency_ids"], {"123": self.plan.agency_id})
        self.assertFalse(result["recovery"]["resubmitted"])
        self.assertEqual(result["recovery"]["blocked_export_requests"], 0)
        self.auth.navigate.assert_called_once_with(recovery.EXPORT_LIST_URL)
        self.page.context.request.post.assert_called_once_with(TEAMS_URL, data={}, timeout=30000)
        self.assertFalse(self.guards)
        self.assertEqual(json.loads((self.raw / "source_receipt.json").read_text(encoding="utf-8")), result)
        self.assertEqual((self.source / "detail_submission.json").read_bytes(), original)
        self.assertFalse(result["payroll_executed"])
        self.assertFalse(result["binding_generated"])

    def test_known_task_receipt_is_reused_and_cannot_switch_to_another_task(self):
        task = {"task_id": "101", "start": self.plan.start, "end": self.plan.end, "selected_team_ids": ["123"]}
        (self.source / "detail_task.json").write_text(json.dumps(task), encoding="utf-8")
        self.rows = [self.row("102"), self.row("101")]
        result = self.execute()
        self.assertEqual(result["task_id"], "101")
        self.assertEqual(self.clicks, ["101"])
        self.assertTrue(result["recovery"]["source_task_sha256"])

    def test_zip_original_is_retained_and_validated_merged_csv_is_returned(self):
        self.download.suggested_filename = "synthetic.zip"
        self.rows = [self.row()]
        result = self.execute()
        self.assertTrue(result["path"].endswith(".csv"))
        self.assertTrue((self.raw / result["original_archive"]).is_file())
        self.assertEqual(result["archive_members"], 1)

    def test_recovery_navigation_failure_never_claims_original_export_was_unsubmitted(self):
        self.auth.navigate.side_effect = RuntimeError("synthetic navigation unavailable")
        with self.assertRaises(RuntimeError):
            self.execute()
        proof = json.loads((self.raw / "source_failure.json").read_text(encoding="utf-8"))
        self.assertEqual((proof["failure_phase"], proof["submission_state"]), ("waiting_export", "unknown"))
        self.assertFalse(self.clicks)
        self.assertFalse(self.guards)

    def test_recovery_save_and_integrity_failures_keep_submission_proof_and_distinct_phases(self):
        save = self.download.save_as
        for name, saving, expected in (
            ("save-failure", Mock(side_effect=OSError("synthetic disk full")), "downloading"),
            ("invalid-file", lambda path: Path(path).write_text("invalid synthetic document", encoding="utf-8"), "validating"),
        ):
            with self.subTest(name=name):
                self.raw = self.root / name
                self.rows = [self.row()]
                self.download.save_as = saving
                with self.assertRaises(Exception):
                    self.execute()
                proof = json.loads((self.raw / "source_failure.json").read_text(encoding="utf-8"))
                self.assertEqual((proof["failure_phase"], proof["submission_state"]), (expected, "submitted"))
                self.assertFalse((self.raw / "source_receipt.json").exists())
                self.assertFalse(self.guards)
        self.download.save_as = save

    def test_ambiguous_new_tasks_are_never_downloaded(self):
        self.rows = [self.row("101"), self.row("102")]
        with self.assertRaisesRegex(SourceError, "多个候选"):
            self.execute()
        self.assertFalse(self.clicks)
        self.assertFalse(self.guards)
        result = json.loads((self.raw / "recovery.json").read_text(encoding="utf-8"))
        self.assertEqual(result["status"], "error")
        self.assertFalse(result["resubmitted"])

    def test_task_outside_submission_window_cannot_be_used_as_known_id(self):
        self.evidence["task_id"] = "101"
        self.save_evidence()
        self.rows = [self.row(created="2026-10-16 12:10:00")]
        with self.assertRaisesRegex(SourceError, "创建时间"):
            self.execute()
        self.assertFalse(self.clicks)

    def test_later_unrelated_task_is_ignored_while_original_unique_task_is_downloaded(self):
        self.rows = [self.row("102", "2026-10-16 12:10:00"), self.row("101")]
        self.assertEqual(self.execute()["task_id"], "101")
        self.assertEqual(self.clicks, ["101"])

    def test_export_endpoint_is_aborted_even_if_navigation_accidentally_triggers_it(self):
        route = SimpleNamespace(abort=Mock())
        self.auth.navigate.side_effect = lambda *_: self.guards[DETAIL_EXPORT + "*"](route)
        with self.assertRaisesRegex(SourceError, "阻止"):
            self.execute()
        route.abort.assert_called_once()
        self.page.context.request.post.assert_not_called()
        self.assertFalse(self.clicks)
        self.assertFalse(self.guards)

    def test_foreign_or_unknown_team_provenance_stops_before_list_download(self):
        for index, team in enumerate(({"id": 123, "agencyId": 31030116, "team_name": "其他城市"},
                                      {"id": 123, "team_name": "未知城市"})):
            self.raw = self.root / f"failed-{index}"
            self.team_payload["result"]["data"] = [team]
            with self.subTest(team=team), self.assertRaises(SourceError):
                self.execute()
            self.assertFalse(self.clicks)

    def test_invalid_or_unconfirmed_submission_is_rejected_without_browser_calls(self):
        original = dict(self.evidence)
        for changes in ({"http_status": 500}, {"response_code": True}, {"request_observed": False},
                        {"start": "2026-10-02"}, {"agency_id": "31030116"}, {"selected_team_ids": ["123", "123"]},
                        {"existing_task_ids": None}, {"submitted_at": "invalid"}, {"task_id": "100"}):
            self.evidence = {**original, **changes}
            self.save_evidence()
            with self.subTest(changes=changes), self.assertRaises(SourceError):
                self.execute()
        self.auth.navigate.assert_not_called()
        self.page.context.request.post.assert_not_called()
        self.assertFalse(self.raw.exists())

    def test_precancelled_recovery_never_enters_browser_or_mutates_source(self):
        original = (self.source / "detail_submission.json").read_bytes()
        self.cancelled.set()
        with self.assertRaisesRegex(SourceError, "取消"):
            self.execute()
        self.auth.navigate.assert_not_called()
        self.assertFalse(self.raw.exists())
        self.assertEqual((self.source / "detail_submission.json").read_bytes(), original)

    def snapshot_collector(self, rows, pagination=None):
        self.raw.mkdir(exist_ok=True)
        collector = recovery._RecoveryCollector(self.page, self.plan, self.raw, Mock(), self.cancelled,
                                                detail_target_city_only=True)
        collector.detail_baseline = {"100"}
        collector.detail_submitted_at = dt.datetime(2026, 10, 16, 12, 0)
        collector.detail_task = None
        frame = Mock(url="https://lpd-service-center.faas.ele.me/#/export-list")
        table = SimpleNamespace(all=lambda: rows)
        def locate(selector):
            if selector == 'tbody tr':
                return table
            if pagination and selector in pagination:
                return pagination[selector]
            return SimpleNamespace(count=lambda: 0)
        frame.locator.side_effect = locate
        return collector, frame

    def test_snapshot_is_safe_and_distinguishes_wide_metadata_from_strict_eligibility(self):
        original = self.row("100", "2026-10-16 11:59:00")
        mismatch = self.row("102")
        mismatch.inner_text.return_value = 'secret-user https://signed.invalid/?token=secret-token 2026-10-01至2026-10-15_骑手数据明细_102.zip 导出中 secret-account'
        unrelated = self.row("103")
        unrelated.inner_text.return_value = 'secret-user other report secret-account'
        ready = self.row("101")
        collector, frame = self.snapshot_collector([original, mismatch, unrelated, ready])
        with patch.object(RiderSourceCollector, '_detail_list_frame', return_value=frame):
            view = collector._detail_list_frame()
            collector._detail_list_frame()
        self.assertEqual(view.locator('tbody tr').all(), [ready])
        text = (self.raw / 'detail_list_snapshot.json').read_text(encoding='utf-8')
        snapshot = json.loads(text)
        self.assertEqual((snapshot['observed_rows'], snapshot['rider_detail_rows'], snapshot['strict_name_matches'], snapshot['eligible_count']), (4, 3, 2, 1))
        self.assertTrue(snapshot['current_dom_only'])
        self.assertEqual(snapshot['nonmatching_rows'], 2)
        wide = snapshot['rows'][1]
        self.assertEqual((wide['task_id'], wide['start'], wide['end'], wide['status']),
                         ('102', '2026-10-01', '2026-10-15', 'processing'))
        self.assertFalse(wide['strict_name_match'])
        self.assertFalse(wide['eligible'])
        self.assertTrue(snapshot['rows'][0]['baseline'])
        self.assertFalse(snapshot['rows'][0]['in_window'])
        self.assertFalse(snapshot['rows'][2]['rider_detail_marker'])
        self.assertIsNone(snapshot['rows'][2]['task_id'])
        for secret in ('secret-user', 'secret-token', 'secret-account', 'signed.invalid', 'https://'):
            self.assertNotIn(secret, text)
        collector.log.assert_called_once()
        self.assertEqual(self.clicks, [])

    def test_snapshot_limits_rows_and_extracts_only_numeric_pagination_values(self):
        def locator(text='', disabled=False, value=None):
            return SimpleNamespace(count=lambda: 1, inner_text=lambda: text, is_disabled=lambda: disabled,
                                   input_value=lambda: value)
        paging = {'.el-pagination .el-pager li.active': locator('2'),
                  '.el-pagination .el-pagination__total': locator('共 245 条'),
                  '.el-pagination .el-pagination__sizes input': locator(value='20条/页'),
                  '.el-pagination .btn-prev': locator(disabled=False), '.el-pagination .btn-next': locator(disabled=False)}
        rows = [self.row('200', '2026-10-16 12:10:00') for _ in range(105)]
        collector, frame = self.snapshot_collector(rows, paging)
        with patch.object(RiderSourceCollector, '_detail_list_frame', return_value=frame):
            self.assertEqual(collector._detail_list_frame().locator('tbody tr').all(), [])
        snapshot = json.loads((self.raw / 'detail_list_snapshot.json').read_text(encoding='utf-8'))
        self.assertEqual(snapshot['observed_rows'], 105)
        self.assertEqual(len(snapshot['rows']), 100)
        self.assertTrue(snapshot['truncated'])
        self.assertEqual(snapshot['pagination']['current'], 2)
        self.assertEqual(snapshot['pagination']['total_rows'], 245)
        self.assertEqual(snapshot['pagination']['page_count'], 13)
        self.assertEqual(snapshot['pagination']['page_size'], 20)
        self.assertFalse(snapshot['pagination']['next_disabled'])
        paging['.el-pagination .el-pager li.active'] = locator('secret-user 2')
        paging['.el-pagination .el-pagination__total'] = locator('secret-account 245')
        paging['.el-pagination .el-pagination__sizes input'] = locator(value='secret-token')
        with patch.object(RiderSourceCollector, '_detail_list_frame', return_value=frame):
            collector._detail_list_frame()
        snapshot = json.loads((self.raw / 'detail_list_snapshot.json').read_text(encoding='utf-8'))
        self.assertNotIn('current', snapshot['pagination'])
        self.assertNotIn('total_rows', snapshot['pagination'])
        self.assertNotIn('page_count', snapshot['pagination'])

    def test_snapshot_is_saved_before_ambiguous_or_unparseable_candidate_is_rejected(self):
        row = self.row()
        row.locator.return_value.nth.return_value.inner_text.return_value = 'secret-created-time'
        collector, frame = self.snapshot_collector([row])
        with patch.object(RiderSourceCollector, '_detail_list_frame', return_value=frame):
            with self.assertRaisesRegex(SourceError, '创建时间'):
                collector._detail_list_frame()
        text = (self.raw / 'detail_list_snapshot.json').read_text(encoding='utf-8')
        self.assertNotIn('secret-created-time', text)
        self.assertIsNone(json.loads(text)['rows'][0]['created_at'])
        collector, frame = self.snapshot_collector([self.row('101'), self.row('102')])
        with patch.object(RiderSourceCollector, '_detail_list_frame', return_value=frame):
            with self.assertRaisesRegex(SourceError, '多个候选'):
                collector._detail_list_frame()
        self.assertEqual(json.loads((self.raw / 'detail_list_snapshot.json').read_text(encoding='utf-8'))['eligible_count'], 2)

    def test_snapshot_io_failure_does_not_change_strict_candidate_selection(self):
        row = self.row()
        collector, frame = self.snapshot_collector([row])
        with patch.object(RiderSourceCollector, '_detail_list_frame', return_value=frame), \
             patch.object(recovery, 'atomic_json', side_effect=OSError('synthetic disk error')):
            self.assertEqual(collector._detail_list_frame().locator('tbody tr').all(), [row])


if __name__ == "__main__":
    unittest.main()
