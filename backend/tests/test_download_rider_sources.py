"""The download center reuses one browser and exports only the requested city/source."""
import csv
import hashlib
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
import download_rider_sources as adapter
import rider_sources as sources
from parttime_source import SourceError


class DownloadRiderSourcesTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=Path(__file__).parent)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.plan = SimpleNamespace(city="测试城市", agency_id="31029436", start="2026-09-20", end="2026-10-10", month="2026-09")
        self.cancelled = threading.Event()
        self.page = Mock(spec=[])
        self.auth = SimpleNamespace(navigate=Mock(), ensure=Mock())
        self.log = Mock()
        self.original = {}

    def collect(self, kind, transform=lambda value: value, archive=False, empty=False, raw=None, **options):
        def factory(page, plan, output, log, cancelled, **kwargs):
            def execute(selected):
                self.assertEqual(selected, kind)
                kwargs["auth"](sources.PAGES[selected], {"expected_agency_id": plan.agency_id})
                headers = {'rider_detail': ['日期', '骑手ID', '团队ID', '团队名称', '有效完成单'],
                           'receive_account': ['团队ID', '团队名称', '骑手ID', '收款方式', '收款账户', '收款账户姓名', '收款账户身份证'],
                           'rider_info': ['骑手ID', '姓名', '部门', '身份证', '状态', '职位']}
                rows = [headers[selected]]
                if not empty:
                    records = {'rider_detail': [plan.start, '001', '123', '测试站', 2],
                               'receive_account': ['123', '测试站', '001', 'synthetic', 'SYNTHETIC-ACCOUNT', '合成人员', 'SYNTHETIC-CARD'],
                               'rider_info': ['001', '合成人员', '测试站', 'SYNTHETIC-CARD', '在职', '骑手']}
                    rows.append(records[selected])
                file = output / "actual_platform_name.csv"
                with file.open("w", encoding="utf-8-sig", newline="") as stream:
                    csv.writer(stream).writerows(rows)
                if archive:
                    original = output / "platform_download.zip"
                    with zipfile.ZipFile(original, "w") as bundle:
                        bundle.write(file, "synthetic-part.csv")
                    file.unlink()
                    file, info = sources.unpack_detail_archive(original, plan, {"123": "测试站"})
                    self.original[original.name] = original.read_bytes()
                else:
                    info = sources.validate_document(file, selected, plan, {"123": "测试站"})
                    self.original[file.name] = file.read_bytes()
                info.update(city=plan.city, agency_id=plan.agency_id, requested_start=plan.start,
                            requested_end=plan.end, requested_month=plan.month)
                if selected in ("rider_detail", "rider_info"):
                    info.update(scope="target_city", all_available_teams=False, selected_team_ids=["123"],
                                team_agency_ids={"123": plan.agency_id})
                else:
                    info["query_total"] = info["rows"]
                return transform(info)
            instance = Mock()
            instance.collect.side_effect = execute
            self.collector = instance
            return instance

        with patch.object(adapter, "RiderSourceCollector", side_effect=factory) as constructor:
            result = adapter.collect_rider_source(self.page, self.auth, self.plan, raw or self.root / "raw", kind,
                                                 self.log, self.cancelled, **options)
        return result, constructor

    def test_daily_source_uses_shared_browser_exact_city_and_full_cross_month_period(self):
        info, constructor = self.collect("rider_detail")
        self.assertEqual((info["dataset"], info["scope"], info["start"], info["end"]),
                         ("rider_detail", "target_city", self.plan.start, self.plan.end))
        self.assertEqual(info["team_agency_ids"], {"123": self.plan.agency_id})
        self.assertFalse(info["binding_generated"])
        self.assertFalse(info["payroll_executed"])
        self.assertIs(constructor.call_args.args[0], self.page)
        self.assertEqual(constructor.call_args.args[1].end, "2026-10-10")
        self.assertTrue(constructor.call_args.kwargs["detail_target_city_only"])
        self.collector.collect.assert_called_once_with("rider_detail")
        self.auth.navigate.assert_called_once_with(sources.PAGES["rider_detail"])
        self.auth.ensure.assert_called_once()
        self.assertEqual(self.page.mock_calls, [])
        self.assertEqual((self.root / "raw" / info["path"]).read_bytes(), self.original[info["path"]])

    def test_receive_account_downloads_whole_month_without_changing_original_plan_or_file(self):
        info, constructor = self.collect("receive_account")
        self.assertEqual((info["start"], info["end"], info["month"]), ("2026-09-01", "2026-09-30", "2026-09"))
        self.assertEqual((self.plan.start, self.plan.end), ("2026-09-20", "2026-10-10"))
        self.assertTrue(info["snapshot_only"])
        self.assertFalse(info["binding_generated"])
        self.collector.collect.assert_called_once_with("receive_account")
        self.assertIsNot(constructor.call_args.args[1], self.plan)
        self.assertEqual((self.root / "raw" / info["path"]).read_bytes(), self.original[info["path"]])

    def test_rider_information_exports_only_current_city_snapshot_unchanged(self):
        info, constructor = self.collect("rider_info")
        self.assertEqual(info["dataset"], "rider_info")
        self.assertTrue(info["snapshot_only"])
        self.assertEqual(info["time_basis"], "current_snapshot")
        self.assertEqual(info["scope"], "target_city")
        self.assertEqual(info["team_agency_ids"], {"123": self.plan.agency_id})
        self.assertFalse(info["binding_generated"])
        self.assertFalse(info["payroll_executed"])
        self.collector.collect.assert_called_once_with("rider_info")
        self.assertIs(constructor.call_args.args[0], self.page)
        self.assertEqual((self.root / "raw" / info["path"]).read_bytes(), self.original[info["path"]])
        self.auth.navigate.assert_called_once_with(sources.PAGES["rider_info"])

    def test_information_snapshot_rejects_foreign_or_unproven_city_teams(self):
        for index, changes in enumerate(({"scope": "all_available_teams"}, {"team_agency_ids": {}},
                                       {"team_agency_ids": {"123": "31030116"}}, {"selected_team_ids": ["123", "123"]})):
            with self.subTest(changes=changes), self.assertRaises(SourceError):
                self.collect("rider_info", lambda info: {**info, **changes}, raw=self.root / str(index))

    def test_leap_february_and_optional_window_callbacks(self):
        self.plan.month = "2024-02"
        reveal, conceal = Mock(), Mock()
        info, constructor = self.collect("receive_account", reveal=reveal, conceal=conceal)
        self.assertEqual((info["start"], info["end"]), ("2024-02-01", "2024-02-29"))
        self.assertIs(constructor.call_args.kwargs["reveal"], reveal)
        self.assertIs(constructor.call_args.kwargs["conceal"], conceal)

    def test_zip_retains_original_archive_and_actual_merged_csv_path(self):
        info, _ = self.collect("rider_detail", archive=True)
        self.assertEqual(info["path"], "platform_download.csv")
        self.assertEqual(info["original_archive"], "platform_download.zip")
        original = self.root / "raw" / info["original_archive"]
        self.assertEqual(original.read_bytes(), self.original[original.name])
        self.assertEqual(info["archive_sha256"], hashlib.sha256(original.read_bytes()).hexdigest())

    def test_header_only_documents_are_valid_empty_results(self):
        for kind in ("rider_detail", "receive_account", "rider_info"):
            with self.subTest(kind=kind):
                info, _ = self.collect(kind, empty=True, raw=self.root / kind)
                self.assertEqual((info["rows"], info["status"], info["team_count"]), (0, "empty", 0))

    def test_foreign_or_unproven_detail_teams_and_legacy_all_scope_are_rejected(self):
        for index, changes in enumerate((
            {"all_available_teams": True}, {"scope": "all_available_teams"}, {"team_agency_ids": {}},
            {"team_agency_ids": {"123": "31030116"}}, {"selected_team_ids": ["123", "123"]},
            {"team_agency_ids": {"123": self.plan.agency_id, "456": self.plan.agency_id}},
            {"team_count": 2}, {"date_max": "2026-10-11"}, {"date_min": None},
        )):
            with self.subTest(changes=changes), self.assertRaises(SourceError):
                self.collect("rider_detail", lambda info: {**info, **changes}, raw=self.root / str(index))

    def test_bad_schema_hash_path_and_scope_do_not_publish_results(self):
        for index, changes in enumerate(({"rows": True}, {"status": "success"}, {"sha256": "0" * 64},
            {"bytes": 1}, {"path": "../outside.csv"}, {"agency_id": "31030116"}, {"requested_end": "2026-10-11"},
            {"format": "zip"}, {"query_total": 9})):
            with self.subTest(changes=changes), self.assertRaises(SourceError):
                self.collect("receive_account", lambda info: {**info, **changes}, raw=self.root / str(index))

    def test_unsupported_kind_and_pre_cancel_never_construct_collector(self):
        with patch.object(adapter, "RiderSourceCollector") as constructor:
            for kind in ("payment_binding", "unknown", None):
                with self.subTest(kind=kind), self.assertRaises(SourceError):
                    adapter.collect_rider_source(self.page, self.auth, self.plan, self.root / "absent", kind, self.log, self.cancelled)
            self.cancelled.set()
            with self.assertRaises(SourceError):
                adapter.collect_rider_source(self.page, self.auth, self.plan, self.root / "absent", "rider_detail", self.log, self.cancelled)
            constructor.assert_not_called()
        self.assertFalse((self.root / "absent").exists())

    def test_cancellation_after_collection_keeps_raw_file_but_returns_no_info(self):
        def cancel(info):
            self.cancelled.set()
            return info
        with self.assertRaisesRegex(SourceError, "取消"):
            self.collect("rider_detail", transform=cancel)
        self.assertTrue((self.root / "raw" / "actual_platform_name.csv").is_file())

    def test_invalid_month_or_date_fails_before_collector_construction(self):
        with patch.object(adapter, "RiderSourceCollector") as constructor:
            for value in ("", "2026-13", None):
                self.plan.month = value
                with self.subTest(value=value), self.assertRaises(SourceError):
                    adapter.collect_rider_source(self.page, self.auth, self.plan, self.root, "receive_account", self.log, self.cancelled)
            self.plan.start = "invalid"
            with self.assertRaises(SourceError):
                adapter.collect_rider_source(self.page, self.auth, self.plan, self.root, "rider_detail", self.log, self.cancelled)
            constructor.assert_not_called()

    def test_success_receipt_preserves_checked_metadata_and_can_be_reverified(self):
        for kind in ("rider_detail", "receive_account", "rider_info"):
            with self.subTest(kind=kind):
                raw = self.root / kind
                info, _ = self.collect(kind, raw=raw)
                text = (raw / "source_receipt.json").read_text(encoding="utf-8")
                receipt = json.loads(text)
                self.assertEqual(receipt, info)
                effective = adapter._plan_for_kind(self.plan, kind)
                self.assertEqual(adapter._checked_info(receipt, raw.resolve(), effective, kind).name, info["path"])
                self.assertFalse(receipt["binding_generated"])
                self.assertFalse(receipt["payroll_executed"])
                self.assertNotIn("SYNTHETIC-ACCOUNT", text)
                self.assertNotIn("SYNTHETIC-CARD", text)

    def diagnostic_page(self):
        def surface(url):
            return SimpleNamespace(url=url, locator=Mock(return_value=SimpleNamespace(count=lambda: 2)))
        page = surface("https://aeolus.ele.me/?token=secret-token#/knight/data-center/detail?account=secret-account")
        page.frames = [surface("https://artemis.faas.ele.me/?identity=secret-identity#/knight/data-center/detail"),
                       surface("https://secret-account.external.invalid/?token=secret-token#secret-fragment")]
        return page

    def test_failure_saves_only_safe_traceback_stage_and_readonly_page_counts(self):
        secret = "secret-token secret-account secret-identity secret-fragment"
        failure = TimeoutError('Locator.wait_for: ' + secret + ' intercepts pointer events')
        collector = SimpleNamespace(profile={"content_frame": adapter._SOURCE_FRAME},
                                    last_control="content_frame", source_stage="baseline_wait_rows")
        def fail(kind):
            raise failure
        collector.collect = Mock(side_effect=fail)
        page = self.diagnostic_page()
        with patch.object(adapter, "RiderSourceCollector", return_value=collector):
            with self.assertRaises(TimeoutError) as raised:
                adapter.collect_rider_source(page, self.auth, self.plan, self.root / "failure", "rider_detail", self.log, self.cancelled)
        self.assertIs(raised.exception, failure)
        text = (self.root / "failure/source_failure.json").read_text(encoding="utf-8")
        result = json.loads(text)
        self.assertEqual(result["stage"], "collect")
        self.assertEqual(result["source_stage"], "baseline_wait_rows")
        self.assertEqual(result["last_control"], "content_frame")
        self.assertEqual(result["exception_type"], "TimeoutError")
        self.assertEqual(result["diagnostics"]["timeout_kind"], "locator")
        self.assertTrue(result["diagnostics"]["pointer_intercepted"])
        self.assertEqual(result["page"]["page"]["host"], "aeolus.ele.me")
        self.assertEqual(result["page"]["page"]["fragment"], "/knight/data-center/detail")
        self.assertEqual(result["page"]["source_frame_count"], 2)
        self.assertEqual(result["page"]["frames"][1]["host"], "other")
        self.assertEqual(result["page"]["frames"][1]["fragment"], "other")
        self.assertTrue(any(frame["name"] == "fail" and frame["filename"] == Path(__file__).name for frame in result["traceback"]))
        for frame in result["traceback"]:
            self.assertEqual(set(frame), {"filename", "name", "lineno"})
            self.assertNotIn("\\", frame["filename"])
            self.assertNotIn("/", frame["filename"])
            self.assertGreater(frame["lineno"], 0)
        for token in secret.split():
            self.assertNotIn(token, text)
        self.assertNotIn(str(self.root), text)
        self.assertFalse((self.root / "failure/source_receipt.json").exists())
        selectors = [call.args[0] for call in page.locator.call_args_list]
        self.assertEqual(set(selectors), set(adapter._COUNT_SELECTORS.values()) | {adapter._SOURCE_FRAME})

    def test_failure_ignores_untrusted_control_and_stage_values(self):
        failure = SourceError("curated failure")
        collector = SimpleNamespace(collect=Mock(side_effect=failure), profile={},
                                    last_control="secret-account", source_stage="secret-token")
        with patch.object(adapter, "RiderSourceCollector", return_value=collector):
            with self.assertRaises(SourceError) as raised:
                adapter.collect_rider_source(self.page, self.auth, self.plan, self.root / "ignored", "rider_detail", self.log, self.cancelled)
        self.assertIs(raised.exception, failure)
        result = json.loads((self.root / "ignored/source_failure.json").read_text(encoding="utf-8"))
        self.assertNotIn("last_control", result)
        self.assertNotIn("source_stage", result)
        self.assertNotIn("curated failure", json.dumps(result))

    def test_closed_diagnostic_page_and_failed_diagnostic_io_never_replace_original_exception(self):
        class ClosedPage:
            @property
            def url(self):
                raise RuntimeError("secret-account")
            @property
            def frames(self):
                raise RuntimeError("secret-token")
            def locator(self, selector):
                raise RuntimeError("secret-identity")
        original = SourceError("original curated error")
        collector = SimpleNamespace(collect=Mock(side_effect=original), profile={})
        with patch.object(adapter, "RiderSourceCollector", return_value=collector):
            with self.assertRaises(SourceError) as raised:
                adapter.collect_rider_source(ClosedPage(), self.auth, self.plan, self.root / "closed", "rider_detail", self.log, self.cancelled)
        self.assertIs(raised.exception, original)
        text = (self.root / "closed/source_failure.json").read_text(encoding="utf-8")
        self.assertNotIn("secret-", text)
        with patch.object(adapter, "RiderSourceCollector", return_value=collector), \
             patch.object(adapter, "atomic_json", side_effect=OSError("secret-account")):
            with self.assertRaises(SourceError) as raised:
                adapter.collect_rider_source(ClosedPage(), self.auth, self.plan, self.root / "io-error", "rider_detail", self.log, self.cancelled)
        self.assertIs(raised.exception, original)

    def test_auth_failure_stage_and_validation_failure_stage_are_distinct(self):
        original = RuntimeError("secret-token")
        self.auth.ensure.side_effect = original
        with self.assertRaises(RuntimeError) as raised:
            self.collect("rider_detail", raw=self.root / "auth")
        self.assertIs(raised.exception, original)
        auth_failure = json.loads((self.root / "auth/source_failure.json").read_text(encoding="utf-8"))
        self.assertEqual(auth_failure["stage"], "auth_check")
        self.auth.ensure.side_effect = None
        with self.assertRaises(SourceError):
            self.collect("rider_detail", lambda info: {**info, "sha256": "0" * 64}, raw=self.root / "validation")
        validation_failure = json.loads((self.root / "validation/source_failure.json").read_text(encoding="utf-8"))
        self.assertEqual(validation_failure["stage"], "receipt_validation")

    def test_failure_context_never_treats_waiting_or_unconfirmed_receipt_as_safe_resubmission(self):
        collector = SimpleNamespace(source_stage="wait_file")
        for receipt in ({}, {"request_observed": True},
                        {"request_observed": True, "status": "acknowledged", "http_status": True, "response_code": 200},
                        {"request_observed": True, "status": "acknowledged", "http_status": 200, "response_code": True}):
            with self.subTest(receipt=receipt):
                collector.detail_submission = receipt
                context = adapter._failure_context("rider_detail", "collect", collector)
                self.assertEqual(context, {"failure_phase": "waiting_export", "submission_state": "unknown"})
        collector.detail_submission = {"request_observed": True, "status": "acknowledged",
                                       "http_status": 200, "response_code": 200}
        self.assertEqual(adapter._failure_context("rider_detail", "collect", collector)["submission_state"], "submitted")

    def test_completed_manual_verification_does_not_hide_later_integrity_failure(self):
        collector = SimpleNamespace(source_stage="validate_file")
        for stage in ("collect", "receipt_validation", "receipt_write"):
            with self.subTest(stage=stage):
                self.assertEqual(adapter._failure_context("rider_info", stage, collector, manual_wait=True),
                                 {"failure_phase": "validating", "submission_state": "unknown"})
        collector.source_stage = "wait_file"
        self.assertEqual(adapter._failure_context("rider_info", "collect", collector, manual_wait=True),
                         {"failure_phase": "waiting_manual", "submission_state": "unknown"})


if __name__ == "__main__":
    unittest.main()
