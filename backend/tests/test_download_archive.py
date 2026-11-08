import codecs
import datetime as dt
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import download_archive as archive


class DownloadArchiveTests(unittest.TestCase):
    def test_checklist_scope_distinguishes_full_snapshots_and_business_dates(self):
        item={'start':'2026-10-01','end':'2026-10-31'}
        for dataset in ('lanorange_rider_quit','baize_employees','abnormal_riders'):
            self.assertEqual(archive.artifact_scope({**item,'dataset':dataset}),('全量',''))
        self.assertEqual(archive.artifact_scope({**item,'dataset':'rider_archive'}),('当前快照',''))
        self.assertEqual(archive.artifact_scope({**item,'dataset':'rider_monthly'}),('2026-10-01','2026-10-31'))

    def test_price_archive_months_are_written_into_the_workbook_name(self):
        args = ('全部城市', 'lanorange_part_price', '2026-11-07', '2026-11-07')
        self.assertEqual(archive.archive_filename(*args, suffix='.xlsx', stamp='2026-11-07',
                                                  months=['2026-10']),
                         '全部城市蓝橙价格档案2026-10_1107.xlsx')
        self.assertEqual(archive.archive_filename(*args, suffix='.xlsx', stamp='2026-11-07',
                                                  months=['2026-09', '2026-10']),
                         '全部城市蓝橙价格档案2026-09至2026-10_1107.xlsx')
        self.assertEqual(archive.archive_filename(*args, suffix='.xlsx', stamp='2026-11-07',
                                                  months=['2026-08', '2026-10']),
                         '全部城市蓝橙价格档案2026-08、2026-10_1107.xlsx')
        self.assertEqual(archive.archive_filename(*args, suffix='.xlsx', stamp='2026-11-07'),
                         '全部城市蓝橙价格档案1107.xlsx')

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=Path(__file__).parent)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.run = {
            "id": "a1b2c3" + "0" * 26, "status": "partial", "created_at": "2026-10-16T11:30:25+00:00",
            "start": "2026-09-20", "end": "2026-10-10", "cities": ["泉州"],
            "archive_version": 1, "archive_relative_dir": "2026-10/20261016_193025_泉州_A1B2C3",
            "items": [{"city": "泉州", "dataset": "rider_monthly", "start": "2026-09-01",
                       "end": "2026-09-30", "status": "success", "error": ""},
                      {"city": "泉州", "dataset": "rider_info", "start": "2026-09-20",
                       "end": "2026-10-10", "status": "error", "error": "未取得官方资料"}],
            "files": [{"city": "泉州", "name": "泉州_风神骑手月度UB账单_2026-09_下载20261016-193025.xlsx",
                       "bytes": 123, "sha256": "a" * 64}], "error": "未取得官方资料",
        }

    def test_creation_month_uses_beijing_boundary(self):
        result = archive.archive_relative_dir(self.run["id"], "2026-09-30T16:00:01+00:00", ["泉州"])
        self.assertEqual(result, "2026-10/20261001_000001_泉州_A1B2C3")

    def test_multiple_cities_and_full_ids_keep_distinct_archives(self):
        first = archive.archive_relative_dir(self.run["id"], self.run["created_at"], ["泉州", "广州", "宁波"])
        second = archive.archive_relative_dir("a1b2c4" + "0" * 26, self.run["created_at"], ["泉州", "广州", "宁波"])
        self.assertEqual(first, "2026-10/20261016_193025_3个城市_A1B2C3")
        self.assertNotEqual(first, second)

    def test_delivery_folder_uses_business_month_and_beijing_timestamp(self):
        created = "2026-11-07T02:12:34+00:00"
        self.assertEqual(archive.delivery_folder_label(['rider_monthly'], '2026-10-01', created),
                         '10月骑手月度UB账单261107101234')
        self.assertEqual(archive.delivery_folder_label(['rider_daily'], '2026-11-01', created),
                         '11月日维度骑手分析261107101234')
        self.assertEqual(archive.delivery_folder_label(['rider_archive'], '2026-10-31', created),
                         '11月骑手档案261107101234')
        self.assertEqual(archive.delivery_folder_label(['rider_daily', 'rider_archive'], '2026-11-01', created),
                         '11月日维度骑手分析_骑手档案261107101234')

    def test_fixed_period_example_preserves_actual_csv(self):
        result = archive.archive_filename("泉州", "delivery_fee", "2026-10-01", "2026-10-15", ".csv")
        self.assertEqual(result, "泉州_配送费_2026-10-01至2026-10-15.csv")

    def test_monthly_workbooks_use_city_month_title_and_generation_mmdd(self):
        stamp = "2026-10-23T10:00:00+08:00"
        result = archive.archive_filename("泉州", "rider_monthly", "2026-09-01", "2026-09-30", ".xlsx",
                                          stamp=stamp)
        self.assertEqual(result, "泉州9月风神骑手月度UB账单1023.xlsx")
        example = archive.archive_filename("三亚", "abnormal_followup", "2026-10-01", "2026-10-31",
                                           ".xlsx", stamp=stamp)
        self.assertEqual(example, "三亚10月异常骑手跟进明细表1023.xlsx")
        binding = archive.archive_filename("泉州", "receive_account", "2026-10-01", "2026-10-31", ".CSV",
                                           stamp=stamp)
        self.assertEqual(binding, "泉州_骑手风神绑定_2026-10.CSV")

    def test_date_range_workbook_keeps_period_and_snapshot_keeps_no_historical_month(self):
        stamp = dt.date(2026, 10, 23)
        detail = archive.archive_filename("泉州", "rider_detail", "2026-10-01", "2026-10-15", ".xlsx",
                                          stamp=stamp)
        self.assertEqual(detail, "泉州骑手数据明细2026-10-01至2026-10-15_1023.xlsx")
        result = archive.archive_filename("泉州", "rider_info", "2025-01-01", "2025-02-01", ".xlsx",
                                          stamp=stamp)
        self.assertEqual(result, "泉州骑手信息1023.xlsx")
        self.assertNotIn("2025", result)
        self.assertNotIn("快照", result)
        riders = archive.archive_filename("全部城市", "abnormal_riders", "2026-10-16", "2026-10-16",
                                          ".xlsx", stamp=stamp)
        self.assertEqual(riders, "全部城市异常骑手整理明细表1023.xlsx")
        self.assertNotIn("2026", riders)

    def test_workbook_variants_stay_explicit(self):
        stamp = dt.date(2026, 10, 23)
        merged = archive.archive_filename("全部城市", "lanorange_rider_quit", "2026-10-01", "2026-10-31",
                                          ".xlsx", stamp=stamp, variant="系统合并")
        self.assertEqual(merged, "全部城市蓝橙骑手离职（系统合并）1023.xlsx")
        batch = archive.archive_filename("泉州", "lanorange_batch_quit", "2026-10-01", "2026-10-31",
                                         ".xlsx", stamp=stamp)
        self.assertEqual(batch, "泉州蓝橙批量离职（城市批次原表）1023.xlsx")

    def test_generation_mmdd_is_dynamic_and_uses_beijing_boundary(self):
        first = archive.archive_filename("三亚", "abnormal_followup", "2026-10-01", "2026-10-31",
                                         ".xlsx", stamp="2026-10-23T10:00:00+08:00")
        second = archive.archive_filename("三亚", "abnormal_followup", "2026-10-01", "2026-10-31",
                                          ".xlsx", stamp="2026-10-24T10:00:00+08:00")
        self.assertTrue(first.endswith("1023.xlsx"))
        self.assertTrue(second.endswith("1024.xlsx"))
        boundary = archive.archive_filename("三亚", "abnormal_followup", "2026-10-01", "2026-10-31",
                                            ".xlsx", stamp="2026-10-23T16:00:01+00:00")
        self.assertTrue(boundary.endswith("1024.xlsx"))

    def test_names_contain_no_download_stamp(self):
        self.assertNotIn("下载", archive.archive_filename("泉州", "payment_binding",
                                                         "2026-10-01", "2026-10-22", ".xlsx",
                                                         stamp=dt.date(2026, 10, 23)))

    def test_unsafe_windows_components_rejected_without_merging_cities(self):
        for city in ("../泉州", "泉州/广州", "泉州\\广州", "C:泉州", "CON", "nul.csv", "LPT1", "COM¹",
                     "..", ".", "泉州.", "泉州 ", " 泉州", "泉\n州", "泉州|", "泉州\x00", ""):
            with self.subTest(city=repr(city)), self.assertRaises(ValueError):
                archive.archive_component(city)
        self.assertEqual(archive.archive_component("泉州"), "泉州")

    def test_bad_identity_time_and_period_do_not_generate_ambiguous_names(self):
        for ident, cities in (("../a", ["泉州"]), (self.run["id"], []), (self.run["id"], ["泉州", "泉州"])):
            with self.subTest(ident=ident, cities=cities), self.assertRaises(ValueError):
                archive.archive_relative_dir(ident, self.run["created_at"], cities)
        with self.assertRaises(ValueError):
            archive.beijing_time("2026-10-16T19:30:25")
        for dataset, start, end, suffix in (("rider_monthly", "2026-09-01", "2026-10-31", ".xlsx"),
                                           ("fraud", "2026-10-05", "2026-10-01", ".csv"),
                                           ("unknown", "2026-10-01", "2026-10-05", ".csv"),
                                           ("fraud", "2026-10-01", "2026-10-05", ".exe")):
            with self.subTest(dataset=dataset, suffix=suffix), self.assertRaises(ValueError):
                archive.archive_filename("泉州", dataset, start, end, suffix)

    def test_summary_has_scope_results_integrity_and_utf8_windows_encoding(self):
        path = archive.write_download_summary(self.root / "run", self.run)
        data = path.read_bytes()
        self.assertTrue(data.startswith(codecs.BOM_UTF8))
        self.assertNotIn(b"\n", data.replace(b"\r\n", b""))
        text = data.decode("utf-8-sig")
        for expected in ("2026-10-16 19:30:25", "部分完成", "2026-09 整月", "当前人员快照",
                         "未取得官方资料", "SHA-256：" + "a" * 64, self.run["files"][0]["name"]):
            self.assertIn(expected, text)

    def test_summary_does_not_publish_credentials_owner_or_absolute_paths(self):
        self.run.update(_archive_root="C:\\private\\secret", owner="private_workspace",
                        logs=[{"message": "token=private-log"}], error="token=private-secret")
        self.run["items"][1]["error"] = "主机诊断：C:\\private\\receipt.json"
        text = archive.write_download_summary(self.root, self.run).read_text(encoding="utf-8-sig")
        for secret in ("private_workspace", "private-secret", "private-log", "C:\\private", "receipt.json"):
            self.assertNotIn(secret, text)
        self.assertIn("部分诊断信息已隐藏", text)

    def test_summary_refresh_preserves_business_files_and_tracks_recovery(self):
        business = self.root / "existing.csv"
        business.write_bytes(b"original business file")
        self.run["recovery_of"] = "b" * 32
        path = archive.write_download_summary(self.root, self.run)
        self.run["status"] = "cancelled"
        archive.write_download_summary(self.root, self.run)
        text = path.read_text(encoding="utf-8-sig")
        self.assertIn("任务状态：已取消", text)
        self.assertIn("恢复自原任务：" + "b" * 32, text)
        self.assertEqual(business.read_bytes(), b"original business file")
        self.assertEqual(list(self.root.glob("*.tmp")), [])

    def test_failed_atomic_write_keeps_previous_receipt_and_cleans_temp(self):
        path = archive.write_download_summary(self.root, self.run)
        before = path.read_bytes()
        with patch.object(archive.os, "replace", side_effect=OSError("synthetic disk failure")):
            with self.assertRaises(OSError):
                archive.write_download_summary(self.root, self.run)
        self.assertEqual(path.read_bytes(), before)
        self.assertEqual(list(self.root.glob("*.tmp")), [])

    def test_legacy_receipt_uses_old_directory_statement(self):
        self.run.pop("archive_version")
        self.run.pop("archive_relative_dir")
        text = archive.write_download_summary(self.root, self.run).read_text(encoding="utf-8-sig")
        self.assertIn("历史任务原目录", text)


if __name__ == "__main__":
    unittest.main()
