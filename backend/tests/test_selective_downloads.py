"""Selective downloads retain scope/integrity checks and write selected outputs only."""
import datetime as dt
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from fengshen_bill import BillCollectionError, BillPageCollector, BillRequest, daily_export_scope
from fengshen_orders import OrderPageCollector
from order_sources import WAYBILL_COLUMNS, VIOLATION_COLUMNS, prepare_order_files
from parttime_source import SourceError, unpack_daily
import test_fengshen_daily_delta as daily_fixtures
import test_fengshen_orders as order_fixtures
import test_parttime_source as source_fixtures


class SelectiveDownloadsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=Path(__file__).parent)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.start, self.end = "2026-08-16", "2026-08-20"
        self.agency_id = "31029436"

    def request(self, types=(1, 2)):
        return BillRequest(self.start, self.end, False, False, self.agency_id, sub_bill_types=types)

    def test_bill_request_accepts_single_combined_and_default_types(self):
        for values, names in (((1,), ("配送费",)), ((2,), ("违规扣款",)),
                              ((1, 2), ("配送费", "违规扣款")), ((2, 1), ("配送费", "违规扣款"))):
            with self.subTest(values=values):
                self.assertEqual(self.request(values).sub_bill_names, names)
        self.assertEqual(BillRequest(self.start, self.end).sub_bill_types, (1, 2))

    def test_bill_request_rejects_empty_duplicate_unknown_and_boolean_types(self):
        for values in ((), (1, 1), (0,), (3,), (True,), (False, 2), (1.0,), ("1",), [1], None):
            with self.subTest(values=values), self.assertRaises(ValueError):
                self.request(values)
        with self.assertRaisesRegex(ValueError, "目标城市"):
            BillRequest(self.start, self.end, sub_bill_types=(1,))

    def test_export_payload_matches_exact_selected_sub_bills(self):
        for values in ((1,), (2,), (1, 2)):
            request = self.request(values)
            payload = {"periodType": 0, "billType": 1, "agentIds": [int(self.agency_id)],
                       "subBillTypes": list(reversed(values)), "startDate": self.start, "endDate": self.end}
            daily_export_scope(payload, request)
            wrong = ([1, 2], [2], [1, 1], [True], []) if values == (1,) else ([1], [2, 2], [1, True], [])
            for types in wrong:
                if set(types) == set(values) and len(types) == len(values) and all(type(value) is int for value in types):
                    continue
                with self.subTest(request=values, types=types), self.assertRaises(BillCollectionError):
                    daily_export_scope({**payload, "subBillTypes": types}, request)
            with self.assertRaises(BillCollectionError):
                daily_export_scope({**payload, "agentIds": [int(self.agency_id), 31030156]}, request)

    def test_both_widget_implementations_select_only_requested_options(self):
        for tree in (False, True):
            for values in ((1,), (2,), (1, 2)):
                with self.subTest(tree=tree, values=values):
                    fixture = source_fixtures.ObservedWidgetTests() if tree else source_fixtures.TargetSelectionTests()
                    profile, page = fixture.tree_page() if tree else fixture.target_page()
                    request = BillRequest(self.start, self.end, False, False, "31030156", values)
                    page.controls["#sub_bill_popup #sub_bill_selected_labels"].all_text_contents = lambda: list(request.sub_bill_names)
                    BillPageCollector(page, profile, self.root / "unused").apply_request(request)
                    event = "click" if tree else "check"
                    selected = {item[1] for item in page.events if item[0] == event and item[1].startswith("#sub_bill_popup #sub_bill_")}
                    expected = {"#sub_bill_popup #sub_bill_delivery" if value == 1 else "#sub_bill_popup #sub_bill_penalty" for value in values}
                    self.assertEqual(selected, expected)

    def test_extra_sub_bill_selection_is_rejected_by_both_widgets(self):
        for tree in (False, True):
            fixture = source_fixtures.ObservedWidgetTests() if tree else source_fixtures.TargetSelectionTests()
            profile, page = fixture.tree_page() if tree else fixture.target_page()
            request = BillRequest(self.start, self.end, False, False, "31030156", (1,))
            with self.subTest(tree=tree), self.assertRaises(BillCollectionError):
                BillPageCollector(page, profile, self.root / "unused").apply_request(request)
            self.assertNotIn(("click", "#submit_button"), page.events)

    def test_daily_collection_records_selected_scope(self):
        request = BillRequest("2026-08-16", "2026-08-31", False, False, self.agency_id, (2,))
        page = daily_fixtures.DeltaPage()
        page.creation_payload["subBillTypes"] = [2]
        collector = BillPageCollector(page, page.profile, self.root / "daily", log=lambda _: None, timeout=2, poll_interval=1)
        collector.apply_request = Mock()
        with patch("fengshen_bill.time.time", return_value=daily_fixtures.NOW), \
             patch("fengshen_bill.time.monotonic", side_effect=lambda: page.now):
            result = collector.collect(request)
        self.assertEqual(result["sub_bill_scope"], ["违规扣款"])
        self.assertEqual(json.loads((self.root / "daily" / "manifest.json").read_text(encoding="utf-8"))["sub_bill_scope"], ["违规扣款"])

    def test_resuming_existing_task_checks_selected_scope(self):
        request = self.request((1,))
        run = self.root / "resume"
        run.mkdir()
        manifest = {"acceptance_only": True, "payroll_executed": False, "production_profile_enabled": False,
                    "status": "waiting", "dataset": "agency_daily", "merchant_group": "物流合作商",
                    "agency_id": self.agency_id, "start": self.start, "end": self.end,
                    "sub_bill_scope": ["配送费"], "task_id": "6",
                    "created_at": dt.datetime.fromtimestamp(daily_fixtures.NOW, dt.timezone.utc).isoformat()}
        collector = BillPageCollector(SimpleNamespace(), daily_fixtures.profile(), run, log=lambda _: None, acceptance_only=True)
        collector._check_agency_context = Mock()
        collector._read_daily_list = Mock(return_value=(None, [{"id": 6, "title": "总部账单-代理商账单-08-16-08-20",
            "agentId": int(self.agency_id), "operation_timestamp": daily_fixtures.NOW}]))
        collector._download_daily_task = Mock(return_value={"path": "synthetic.zip"})
        path = run / "manifest.json"
        path.write_text(json.dumps(manifest), encoding="utf-8")
        self.assertEqual(collector.resume_daily_acceptance(request)["status"], "success")
        path.write_text(json.dumps({**manifest, "sub_bill_scope": ["配送费", "违规扣款"]}), encoding="utf-8")
        with self.assertRaisesRegex(BillCollectionError, "范围"):
            collector.resume_daily_acceptance(request)
        self.assertEqual(collector._download_daily_task.call_count, 1)

    def zip_file(self, name, kinds):
        path = self.root / name
        with zipfile.ZipFile(path, "w") as archive:
            for kind in kinds:
                archive.writestr(kind + ".csv", "加盟商ID,账单时间,骑手ID,金额\n")
        return path

    def test_unzip_accepts_selected_and_default_files_without_extra_outputs(self):
        for index, kinds in enumerate(({"配送费"}, {"违规扣款"}, {"配送费", "违规扣款"})):
            with self.subTest(kinds=kinds):
                archive = self.zip_file(f"bill-{index}.zip", kinds)
                target = self.root / f"unpacked-{index}"
                result = unpack_daily(archive, target, expected_kinds=kinds)
                self.assertEqual(set(result), kinds)
                self.assertEqual({path.stem for path in target.iterdir()}, kinds)
        archive = self.zip_file("default.zip", ("配送费", "违规扣款"))
        self.assertEqual(set(unpack_daily(archive, self.root / "default")), {"配送费", "违规扣款"})

    def test_unzip_rejects_missing_extra_and_invalid_requested_files(self):
        archive = self.zip_file("all.zip", ("配送费", "违规扣款"))
        with self.assertRaisesRegex(SourceError, "未选择"):
            unpack_daily(archive, self.root / "extra", expected_kinds={"配送费"})
        archive = self.zip_file("one.zip", ("配送费",))
        with self.assertRaisesRegex(SourceError, "缺少"):
            unpack_daily(archive, self.root / "missing")
        for index, kinds in enumerate((set(), {"其他"})):
            with self.assertRaises(SourceError):
                unpack_daily(archive, self.root / f"bad-{index}", expected_kinds=kinds)

    def test_order_collector_can_skip_service_export_and_retains_default(self):
        from profile_fixtures import order_profile
        profile = order_profile()
        for include in (False, True):
            with self.subTest(include_violations=include):
                collector = OrderPageCollector(SimpleNamespace(), profile, self.root / str(include), log=lambda _: None, acceptance_only=True)
                with patch("fengshen_orders.date_batches", return_value=[(self.start, self.end)]), \
                     patch.object(collector, "_export_waybills", side_effect=lambda *_: collector._empty_file("orders.csv", WAYBILL_COLUMNS)), \
                     patch.object(collector, "_post", return_value={"result": {"data": {"fileUrl": ""}}}) as service:
                    kwargs = {} if include else {"include_violations": False}
                    manifests = collector.collect_batches(self.start, self.end, **kwargs)
                expected = {"waybills", "violations"} if include else {"waybills"}
                self.assertEqual(set(manifests[0]["files"]), expected)
                self.assertEqual(set(manifests[0]["file_checks"]), expected)
                self.assertEqual(service.call_count, int(include))

    def bundle(self, case, include_violations=True):
        root = self.root / case
        raw, inputs = root / "raw", root / "input"
        base = raw / "issue_orders" / (self.start + "_" + self.end)
        base.mkdir(parents=True)
        inputs.mkdir()
        order_fixtures.write_csv(base / "orders.csv", WAYBILL_COLUMNS, [order_fixtures.waybill(fraud="是", late="是")])
        files = {"waybills": "orders.csv"}
        if include_violations:
            order_fixtures.write_csv(base / "penalties.csv", VIOLATION_COLUMNS, [
                order_fixtures.violation("v1", order_fixtures.waybill()["运单id"]), order_fixtures.violation("v2", "other")])
            files["violations"] = "penalties.csv"
        manifest = {"dataset": "issue_orders", "status": "success", "agency_id": self.agency_id,
                    "start": self.start, "end": self.end, "time_basis": "tracking_finish", "merchant_group": "物流合作商",
                    "all_city_riders": True, "files": files, "file_checks": order_fixtures.file_checks(base, files), "expected_waybills": 1}
        return manifest, raw, inputs, SimpleNamespace(city="泉州", agency_id=self.agency_id)

    def test_selected_fraud_problem_combined_and_default_write_only_selected_files(self):
        for index, selected in enumerate(({"欺诈单"}, {"问题单"}, {"欺诈单", "问题单"}, None)):
            with self.subTest(selected=selected):
                kinds = {"欺诈单", "问题单"} if selected is None else selected
                manifest, raw, inputs, plan = self.bundle(str(index), "问题单" in kinds)
                result = prepare_order_files([manifest], raw, inputs, plan, [(self.start, self.end)], selected_kinds=selected)
                self.assertEqual(set(result), kinds | {"order_batches"})
                self.assertEqual({path.name for path in inputs.iterdir()}, {"泉州-" + kind + "_auto.csv" for kind in kinds})
                if "欺诈单" in kinds:
                    self.assertEqual(result["欺诈单"]["rows"], 1)
                if "问题单" in kinds:
                    # The penalty for the fraud waybill is excluded even when no fraud file was requested.
                    self.assertEqual(result["问题单"]["rows"], 1)
                else:
                    self.assertNotIn("violations", result["order_batches"][0])

    def test_fraud_only_keeps_hash_count_and_city_scope_validation(self):
        manifest, raw, inputs, plan = self.bundle("integrity", False)
        for changed in ({**manifest, "file_checks": {}}, {**manifest, "expected_waybills": 2},
                        {**manifest, "agency_id": "999"}, {**manifest, "all_city_riders": False}):
            with self.subTest(changed=changed), self.assertRaises(BillCollectionError):
                prepare_order_files([changed], raw, inputs, plan, [(self.start, self.end)], selected_kinds={"欺诈单"})
        path = raw / "issue_orders" / (self.start + "_" + self.end) / "orders.csv"
        with path.open("ab") as output:
            output.write(b"\n")
        with self.assertRaisesRegex(BillCollectionError, "完整性"):
            prepare_order_files([manifest], raw, inputs, plan, [(self.start, self.end)], selected_kinds={"欺诈单"})
        self.assertFalse(list(inputs.iterdir()))

    def test_problem_only_requires_service_raw_and_invalid_selection_fails(self):
        manifest, raw, inputs, plan = self.bundle("required", False)
        for selected in ({"问题单"}, set(), {"其他"}, "欺诈单"):
            with self.subTest(selected=selected), self.assertRaises(BillCollectionError):
                prepare_order_files([manifest], raw, inputs, plan, [(self.start, self.end)], selected_kinds=selected)
        self.assertFalse(list(inputs.iterdir()))


if __name__ == "__main__":
    unittest.main()
