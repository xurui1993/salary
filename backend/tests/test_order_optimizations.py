import datetime as dt
from pathlib import Path
import sqlite3
import sys
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import pandas as pd

sys.path.insert(0, str(Path(__file__).parents[1]))
from fengshen_bill import BillCollectionError
from fengshen_orders import SHANGHAI
from issue_orders import DataCleaner
from order_dates import natural_dates
from order_pipeline import OrderCache, CacheMiss, OrderPipeline
from order_sources import prepare_order_files
from test_fengshen_orders import waybill, write_csv, file_checks, WAYBILL_COLUMNS, VIOLATION_COLUMNS


class RuleOptimizationTests(unittest.TestCase):
    def cleaner(self, rows):
        violations = pd.DataFrame(columns=["日期", "违规状态", "申诉状态"])
        return DataCleaner.from_frames(pd.DataFrame(rows), violations)

    def test_notpunctual_boundary_matrix_matches_legacy_scalar_rule(self):
        rows, expected = [], []
        base = pd.Timestamp("2026-10-01 12:00:00")
        for kind, product, origin in (("预订单", "普通", "普通"), ("即时单", "普通", "普通"),
                                      ("即时单", "星专送", "普通"), ("即时单", "普通", "开放平台")):
            for delta in (-600, 0, .001, 480, 480.001, 600):
                row = waybill(waybill_id=str(len(rows)))
                row.update(运单类型=kind, 配送标品=product, 订单来源=origin,
                           运单完成时间=(base + pd.Timedelta(seconds=delta)).isoformat(), 平台期望时间=str(base))
                rows.append(row)
                threshold = 0 if kind == "预订单" or product == "星专送" or origin == "开放平台" else 480
                if delta > threshold:
                    expected.append(row["运单id"])
        for kind in ("预订单", "即时单"):
            row = waybill(waybill_id=str(len(rows)))
            row.update(运单类型=kind, 运单完成时间="2026-10-01 13:00:00",
                       平台期望时间="2026-10-01 11:00:00~2026-10-01 12:00:00")
            rows.append(row)
            if kind == "预订单":
                expected.append(row["运单id"])
        for late in ("是", "否"):
            row = waybill(waybill_id=str(len(rows)), late=late)
            row["平台期望时间"] = ""
            rows.append(row)
            if late == "是":
                expected.append(row["运单id"])
        result = self.cleaner(rows).notpunctual_period(pd.DataFrame(rows))
        self.assertEqual(result["运单id"].tolist(), expected)

    def test_timeout_windows_rounding_and_shared_carrier_computation(self):
        rows = []
        for station in ("普通站", "塘厦站", "沃尔玛站"):
            for seconds in (-600.3, -600, -599.7, 0, 599.7, 600, 600.3):
                row = waybill(waybill_id=str(len(rows)))
                row.update(站点名称=station, 是否超骑手T="是", 是否超用户T="是",
                           运单完成时间=(pd.Timestamp("2026-10-01 12:00:00") + pd.Timedelta(seconds=seconds)).isoformat(),
                           骑手考核时间="2026-10-01 12:00:00", 用户期望时间="2026-10-01 12:00:00")
                rows.append(row)
        cleaner = self.cleaner(rows)
        expected = [cleaner.CarrierT_period(pd.Series({**row, "运单完成时间": pd.Timestamp(row["运单完成时间"])})) for row in rows]
        with patch.object(cleaner._dates(), "window", wraps=cleaner._dates().window) as calculation:
            carrier, t10 = cleaner.time_outCarrierT(), cleaner.time_outten()
            self.assertEqual(calculation.call_count, 1)
        self.assertEqual(cleaner._carrier_timeouts()["超时时长"].tolist(), expected)
        expected_carrier = [row["运单id"] for row, minutes in zip(rows, expected)
                            if not ("塘厦" in row["站点名称"] and abs(minutes) >= 10)]
        expected_t10 = [row["运单id"] for row, minutes in zip(rows, expected)
                        if row["站点名称"] != "普通站" and abs(minutes) >= 10]
        self.assertEqual(carrier["运单id"].tolist(), expected_carrier)
        self.assertEqual(t10["运单id"].tolist(), expected_t10)
        self.assertEqual(cleaner.time_outUserT()["超时时长"].tolist(), expected)
        for finish in ("2026-10-01 10:00:00", "2026-10-01 11:30:00", "2026-10-01 13:00:00"):
            values = pd.Series(["2026-10-01 11:00:00~2026-10-01 12:00:00"])
            actual = cleaner._dates().window(values, pd.Series([pd.Timestamp(finish)])).iloc[0]
            legacy = cleaner.CarrierT_period(pd.Series({"运单完成时间": pd.Timestamp(finish), "骑手考核时间": values[0]}))
            self.assertEqual(actual, legacy)

    def test_normalized_natural_dates_preserve_accepted_shapes(self):
        values = pd.Series(["2026/1/2", "2026-01-02 23:59:59.999", dt.date(2026, 1, 2)])
        self.assertEqual(natural_dates(values).tolist(), ["2026-01-02"] * 3)
        for value in ("2026-02-30", "2026-01-02 junk", "", None):
            with self.assertRaises(BillCollectionError):
                natural_dates(pd.Series([value]))


class CacheAndPipelineTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=Path(__file__).parent)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.today = dt.datetime.now(SHANGHAI).date()

    def test_cache_ttl_city_today_and_hash_are_enforced(self):
        cache = OrderCache(self.root / "cache.sqlite", today="2026-10-18", clock=lambda: 100000)
        frame = pd.DataFrame([dict(waybill(), 运单完成时间="2026-10-17 12:00:00")])
        cache.put("2", "2026-10-17", "waybills", frame, 99900, {})
        self.assertEqual(len(cache.get("2", "2026-10-17", "waybills")), 1)
        for agency, day in (("3", "2026-10-17"), ("2", "2026-10-18")):
            with self.assertRaises(CacheMiss):
                cache.get(agency, day, "waybills")
        cache.clock = lambda: 200000
        with self.assertRaises(CacheMiss):
            cache.get("2", "2026-10-17", "waybills")
        cache.clock = lambda: 100000
        with cache.connect() as db:
            db.execute("UPDATE slices SET payload=?", (b"corrupt",))
        with self.assertRaises(CacheMiss):
            cache.get("2", "2026-10-17", "waybills")

    def runner(self):
        parent = self
        class Runner:
            def __init__(self): self.calls = []
            def orders_batch(self, plan, raw, selected):
                self.calls.append((plan.start, plan.end))
                if len(self.calls) == 2 and len(self.calls[0]) == 2:
                    # A simulated platform wait gives the local process time
                    # to finish the first file while this next batch is pending.
                    until = time.monotonic() + 15
                    while not list(Path(raw).parent.glob("order_processed/prepared/*waybills*")) and time.monotonic() < until:
                        time.sleep(.05)
                    parent.assertTrue(list(Path(raw).parent.glob("order_processed/prepared/*waybills*")))
                directory = Path(raw) / (plan.start + "_" + plan.end)
                directory.mkdir(parents=True)
                first, last = dt.date.fromisoformat(plan.start), dt.date.fromisoformat(plan.end)
                days = [(first + dt.timedelta(days=n)).isoformat() for n in range((last-first).days+1)]
                rows = [dict(waybill(waybill_id=day), 运单完成时间=day + " 12:00:00") for day in days]
                write_csv(directory / "waybills.csv", WAYBILL_COLUMNS, rows)
                write_csv(directory / "violations.csv", VIOLATION_COLUMNS)
                files = {"waybills": "waybills.csv", "violations": "violations.csv"}
                return [{"dataset": "issue_orders", "status": "success", "agency_id": plan.agency_id,
                         "start": plan.start, "end": plan.end, "time_basis": "tracking_finish",
                         "merchant_group": "物流合作商", "all_city_riders": True, "files": files,
                         "file_checks": file_checks(directory, files), "expected_waybills": len(rows),
                         "expected_waybills_by_date": {day:1 for day in days}}]
        return Runner()

    def test_batch_overlap_cache_reuse_and_today_refresh(self):
        plan = SimpleNamespace(city="泉州", agency_id="2", start=(self.today-dt.timedelta(days=6)).isoformat(),
                               end=(self.today-dt.timedelta(days=1)).isoformat())
        cache_path = self.root / "cache.sqlite"
        runner = self.runner()
        pipeline = OrderPipeline(self.root / "cold", plan, {"fraud","problem"}, cache_path, threading.Event())
        downloads, prepared, batches = pipeline.collect(runner)
        self.assertEqual(len(runner.calls), 2)
        self.assertEqual(len(prepared), 2)
        warm_runner = self.runner()
        warm = OrderPipeline(self.root / "warm", plan, {"fraud","problem"}, cache_path, threading.Event())
        warm.collect(warm_runner)
        self.assertEqual(warm_runner.calls, [])
        self.assertEqual(warm.metrics["cached_days"], 6)
        plan.start, plan.end = (self.today-dt.timedelta(days=1)).isoformat(), self.today.isoformat()
        refresh_runner = self.runner()
        today = OrderPipeline(self.root / "today", plan, {"fraud","problem"}, cache_path, threading.Event())
        today.collect(refresh_runner)
        self.assertEqual(refresh_runner.calls, [(self.today.isoformat(), self.today.isoformat())])
        self.assertEqual(today.metrics["cached_days"], 1)
        forced_runner = self.runner()
        forced = OrderPipeline(self.root / "forced", plan, {"fraud","problem"}, cache_path, threading.Event(), refresh=True)
        forced.collect(forced_runner)
        self.assertEqual(forced.metrics["cached_days"], 0)

    def test_cancelled_pipeline_does_not_collect(self):
        plan = SimpleNamespace(city="泉州", agency_id="2", start=self.today.isoformat(), end=self.today.isoformat())
        cancelled = threading.Event(); cancelled.set()
        runner = self.runner()
        pipeline = OrderPipeline(self.root / "cancel", plan, {"fraud"}, self.root / "cache.sqlite", cancelled)
        with self.assertRaises(BillCollectionError):
            pipeline.collect(runner)
        self.assertEqual(runner.calls, [])


if __name__ == "__main__":
    unittest.main()
