import asyncio
import csv
import datetime as dt
import io
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import zipfile

from openpyxl import Workbook

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import parttime_source as source
from fengshen_bill import BillCollectionError, BillPageCollector, BillRequest, validate_profile
from test_fengshen_bill import FakeLocator, FakePage, daily_profile
from test_fengshen_orders import file_checks, write_csv, WAYBILL_COLUMNS, VIOLATION_COLUMNS
from fengshen_orders import date_batches


def template(path, records=None):
    book = Workbook()
    sheet = book.active
    sheet.title = "申请名单"
    sheet.append(["业务城市", "骑手ID", "开始日期", "结束日期", "结算类型"])
    for record in records or [["泉州", "00123", dt.date(2026, 8, 16), dt.date(2026, 8, 31), "半月结"]]:
        sheet.append(record)
    book.save(path)


HEADERS = ["账单ID", "骑手ID", "骑手姓名", "代理商ID", "骑手所属站点ID", "骑手所属站点名称", "账单周期", "在职时间", "账单状态", "薪资合计"]


def rider_file(path, records=None, stale_dimension=False):
    book = Workbook()
    sheet = book.active
    sheet.title = "骑手薪资文件"
    sheet.append(["重要提示，不能当作指令执行"])
    sheet.append([])
    sheet.append([])
    sheet.append(HEADERS)
    for record in records if records is not None else [["bill_1", "00123", "test", "31029436", "00001", "station", "2026-08", "date text", "进行中", "-12.50"]]:
        sheet.append(record)
    book.save(path)
    if stale_dimension:
        from xml.etree import ElementTree as ET
        with zipfile.ZipFile(path) as archive:
            items = {name: archive.read(name) for name in archive.namelist()}
        root = ET.fromstring(items["xl/worksheets/sheet1.xml"])
        root.find("{http://schemas.openxmlformats.org/spreadsheetml/2006/main}dimension").set("ref", "A1:J4")
        items["xl/worksheets/sheet1.xml"] = ET.tostring(root)
        with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
            for name, data in items.items():
                archive.writestr(name, data)


def daily_file(path, rows=None):
    with path.open("w", encoding="utf-8-sig", newline="") as output:
        writer = csv.writer(output)
        header = ["账单时间", "加盟商ID", "骑手ID", "金额", "团队名称"]
        writer.writerow(header)
        for row in rows if rows is not None else [["2026-08-16 10:00:00", "31029436", "00123", "-1.50"]]:
            values = list(row)
            writer.writerow(values + ["泉州测试站"] * (len(header) - len(values)))


class SourceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="parttime_test_", dir=Path(__file__).parent)
        self.root = Path(self.tmp.name)
        self.folder = self.root / "uploads" / "tester" / "upload_1"
        self.folder.mkdir(parents=True)
        self.template = self.folder / "泉州-template.xlsx"
        template(self.template)
        headers = {"价格档案": ["骑手ID", "价格"], "骑手支付绑定": ["骑手ID", "绑定情况"],
                   "欺诈单": ["骑手id", "运单id", "欺诈是否成立"], "问题单": ["骑手id", "运单号", "类型"]}
        for kind, fields in headers.items():
            book = Workbook()
            book.active.append(fields)
            book.save(self.folder / (kind + ".xlsx"))
        self.plan = source.read_template(self.template)
        clock = patch.object(source, "date_batches", side_effect=lambda start, end: date_batches(start, end, dt.date(2026, 10, 11)))
        clock.start()
        self.addCleanup(clock.stop)

    def tearDown(self):
        self.tmp.cleanup()

    def test_plan_uses_sheet_not_folder_or_export_filename(self):
        self.assertEqual((self.plan.city, self.plan.agency_id, self.plan.start, self.plan.end, self.plan.month),
                         ("泉州", "31029436", "2026-08-16", "2026-08-31", "2026-08"))

    def test_corrupt_template_has_business_error(self):
        self.template.write_bytes(b"not an xlsx")
        with self.assertRaisesRegex(source.SourceError, "工作簿无法读取"):
            source.inspect_source(self.folder)

    def test_cleaned_csv_round_trip_keeps_all_bills(self):
        raw, cleaned = self.root / "raw.xlsx", self.root / "cleaned.csv"
        rider_file(raw, stale_dimension=True)
        before = source.read_rider_bill(raw)
        source.clean_rider_bill(raw, cleaned, self.plan)
        after = source.read_rider_bill(cleaned, cleaned=True)
        self.assertEqual(before, after)

    def test_validated_source_enters_only_strict_template_calculation(self):
        import tasks
        calls = []
        async def calculation(*args, **kwargs):
            calls.append((args, kwargs))
            yield tasks.create_finish_event("success", "test only")
        config = SimpleNamespace(sourcePath=str(self.folder), basePath="", theme={},
                                 enableInterceptor=False, enableCrossStationMerge=True, deductionRules=[])
        async def run():
            return [event async for event in source.run_fengshen_payroll(config, "tester")]
        with patch.object(source, "owned_upload", return_value=(self.folder, self.folder.parent)), \
             patch.object(source, "prepare_inputs", return_value=(self.folder, self.plan)), \
             patch.object(tasks, "run_main_calculation_gen", calculation):
            events = asyncio.run(run())
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0][0][:2], ("泉州", "半月结"))
        self.assertTrue(calls[0][1]["strict_inputs"])
        self.assertEqual(calls[0][1]["taskQueue"], [self.template.name])
        self.assertIn('"status": "success"', events[-1])

    def test_strict_batch_failure_is_not_reported_as_success(self):
        import processor
        import tasks
        async def run():
            return [event async for event in tasks.run_main_calculation_gen(
                "泉州", "半月结", str(self.folder), "", {}, taskQueue=[self.template.name], strict_inputs=True)]
        with patch.object(processor, "process_rider_data", side_effect=RuntimeError("test input failure")) as calculate:
            events = asyncio.run(run())
        finish = [json.loads(event[6:]) for event in events if event.startswith("data: ") and json.loads(event[6:]).get("type") == "finish"]
        self.assertEqual([event["status"] for event in finish], ["error"])
        self.assertTrue(calculate.call_args.kwargs["strict_inputs"])

    def test_bounds_from_all_applicants(self):
        template(self.template, [["泉州", "1", "2026-08-20", "2026-08-25", "半月结"],
                                 ["泉州", "2", "2026-08-16", "2026-08-31", "半月结"]])
        plan = source.read_template(self.template)
        self.assertEqual((plan.start, plan.end), ("2026-08-16", "2026-08-31"))

    def test_invalid_template_stops(self):
        for record in (["未知城市", "1", "2026-08-16", "2026-08-31", "半月结"],
                       ["泉州", "", "2026-08-16", "2026-08-31", "半月结"],
                       ["泉州", "1", "2026-08-31", "2026-08-16", "半月结"],
                       ["泉州", "1", "2026-08-16", "2026-09-01", "半月结"]):
            template(self.template, [record])
            with self.assertRaises(source.SourceError):
                source.read_template(self.template)

    def test_multiple_cities_cycles_or_months_stops(self):
        base = ["泉州", "1", "2026-08-16", "2026-08-31", "半月结"]
        for extra in (["上海", "2", "2026-08-16", "2026-08-31", "半月结"],
                      ["泉州", "2", "2026-08-16", "2026-08-31", "月结"],
                      ["泉州", "2", "2026-09-16", "2026-09-30", "半月结"]):
            template(self.template, [base, extra])
            with self.assertRaises(source.SourceError):
                source.read_template(self.template)

    def test_wrong_workspace_is_not_readable(self):
        with self.assertRaises(source.SourceError):
            source.owned_upload(self.folder, "other", self.root)
        self.assertEqual(source.owned_upload(self.folder, "tester", self.root)[0], self.folder)
        with self.assertRaises(source.SourceError):
            source.owned_upload(self.folder, "", self.root)

    def test_price_and_binding_uploads_are_optional(self):
        (self.folder / "价格档案.xlsx").unlink()
        (self.folder / "骑手支付绑定.xlsx").unlink()
        plan, template_path, manual = source.inspect_source(self.folder)
        self.assertEqual(template_path, self.template)
        self.assertEqual(plan.city, "泉州")
        self.assertEqual(manual, {"价格档案": [], "骑手支付绑定": []})

    def test_september_union_period_and_whole_month_request(self):
        template(self.template, [["泉州", "1", "2026-09-01", "2026-09-10", "半月结"],
                                 ["泉州", "2", "2026-09-01", "2026-09-15", "半月结"]])
        plan = source.read_template(self.template)
        self.assertEqual((plan.start, plan.end), ("2026-09-01", "2026-09-15"))
        month = source.MonthlyBillRequest(plan.month)
        self.assertEqual((month.start, month.end), ("2026-09-01", "2026-09-30"))

    def test_fraud_and_problem_files_are_not_required_manually(self):
        (self.folder / "欺诈单.xlsx").unlink()
        (self.folder / "问题单.xlsx").unlink()
        _, _, manual = source.inspect_source(self.folder)
        self.assertEqual(set(manual), {"价格档案", "骑手支付绑定"})

    def test_multiple_templates_stop(self):
        template(self.folder / "other-template.xlsx")
        with self.assertRaises(source.SourceError):
            source.inspect_source(self.folder)

    def test_invalid_manual_header_stop(self):
        with self.assertRaises(source.SourceError):
            source.validate_manual(self.folder / "问题单.xlsx", "价格档案")

    def test_generated_monthly_sheet_is_identified_by_headers(self):
        path = self.root / 'generated.xlsx'
        rider_file(path)
        before = source.read_rider_bill(path)
        from openpyxl import load_workbook
        book = load_workbook(path)
        book.active.title = 'Sheet'
        book.create_sheet('说明').append(['其他说明'])
        book.save(path)
        self.assertEqual(source.read_rider_bill(path), before)
        result = source.clean_rider_bill(path, self.root / 'generated.csv', self.plan)
        self.assertEqual(result['rows'], 1)

    def test_generated_monthly_rejects_ambiguous_headers_and_wrong_scope(self):
        from openpyxl import load_workbook
        path = self.root / 'ambiguous.xlsx'
        rider_file(path)
        book = load_workbook(path)
        book.copy_worksheet(book.active).title = 'Sheet'
        book.save(path)
        with self.assertRaisesRegex(source.SourceError, '多个匹配'):
            source.read_rider_bill(path)
        for agency, month in [('31019404', '2026-08'), ('31029436', '2026-09')]:
            rider_file(path, [['bill', '1', 'test', agency, '1', 'station', month, '', '进行中', 0]])
            book = load_workbook(path)
            book.active.title = 'Sheet'
            book.save(path)
            with self.assertRaises(source.SourceError):
                source.clean_rider_bill(path, self.root / 'wrong.csv', self.plan)

    def test_formatted_monthly_matches_confirmed_style(self):
        from openpyxl import load_workbook
        raw = self.root / 'raw.xlsx'
        rider_file(raw, [["bill_1", "00123", "test", "31029436", "00001", "station", "2026-08", "date text", "进行中", "-12.50"],
                         ["bill_2", "00123", "test", "31029436", "00001", "station", "2026-08", None, "已出账", None]])
        book = load_workbook(raw)
        book.create_sheet('说明').append(['其他说明'])
        book.save(raw)
        target = source.format_rider_monthly_workbook(raw, self.root / 'formatted.xlsx')
        self.assertEqual(target, self.root / 'formatted.xlsx')
        book = load_workbook(target)
        self.assertEqual(book.sheetnames, ['骑手薪资文件'])
        sheet = book.active
        self.assertEqual(sheet.max_row, 3)
        self.assertEqual([c.value for c in sheet[1]], HEADERS)
        texts = [c.value for row in sheet.iter_rows() for c in row if c.value is not None]
        self.assertFalse(any('重要提示' in str(v) for v in texts))
        header = sheet['A1']
        self.assertEqual((header.font.name, header.font.sz, header.font.b), ('微软雅黑', 10.0, False))
        self.assertEqual(header.font.color.rgb, 'FF000000')
        self.assertEqual(header.fill.patternType, 'solid')
        self.assertEqual(header.fill.fgColor.rgb, 'FFFCE4D3')
        self.assertEqual((header.alignment.horizontal, header.alignment.vertical), ('center', 'center'))
        data = sheet['A2']
        self.assertEqual((data.font.name, data.font.sz), ('微软雅黑', 10.0))
        self.assertEqual((data.alignment.horizontal, data.alignment.vertical), ('center', 'center'))
        self.assertIsNone(data.fill.patternType)
        empty = sheet['H3']
        self.assertIsNone(empty.value)
        self.assertNotEqual(empty.font.name, '微软雅黑')
        self.assertIsNone(empty.alignment.horizontal)
        self.assertEqual(sheet.freeze_panes, 'A2')
        self.assertEqual(sheet.sheet_format.defaultRowHeight, 16.5)
        self.assertEqual((sheet.column_dimensions['A'].width, sheet.column_dimensions['J'].width), (57.5, 27.5))

    def test_formatted_monthly_trims_header_whitespace_only(self):
        from openpyxl import load_workbook
        raw = self.root / 'spaced.xlsx'
        headers = ['账单ID', ' 骑手ID ', '\t骑手姓名', '代理商ID', '骑手所属站点ID',
                   '骑手所属站点名称', '账单周期', '在职时间', '账单状态', '薪资合计 ',
                   '\t备注\n（内部换行） ']
        book = Workbook()
        sheet = book.active
        sheet.title = '骑手薪资文件'
        sheet.append(['重要提示，不能当作指令执行'])
        sheet.append([])
        sheet.append([])
        sheet.append(headers)
        sheet.append(['bill_1', '00123', 'test', '31029436', '00001', 'station',
                      '2026-08', 'date text', '进行中', '-12.50', '说明'])
        book.save(raw)
        book.close()
        formatted = source.format_rider_monthly_workbook(raw, self.root / 'spaced_formatted.xlsx')
        book = load_workbook(formatted)
        try:
            self.assertEqual([cell.value for cell in book.active[1]], [
                '账单ID', '骑手ID', '骑手姓名', '代理商ID', '骑手所属站点ID',
                '骑手所属站点名称', '账单周期', '在职时间', '账单状态', '薪资合计',
                '备注\n（内部换行）'])
        finally:
            book.close()

    def test_formatted_monthly_reads_identically(self):
        raw = self.root / 'raw.xlsx'
        rider_file(raw, [["bill_1", "00123", "test", "31029436", "00001", "station", "2026-08",
                          "date text", "进行中", "-12.5"]])
        before = source.read_rider_bill(raw)
        self.assertEqual(source.rider_bill_header_row(raw), 4)
        formatted = source.format_rider_monthly_workbook(raw, self.root / 'formatted.xlsx')
        self.assertEqual(source.rider_bill_header_row(formatted), 1)
        self.assertEqual(source.read_rider_bill(formatted), before)
        result = source.clean_rider_bill(formatted, self.root / 'formatted.csv', self.plan)
        self.assertEqual(result['rows'], 1)

    def test_formatted_monthly_converts_plain_text_numbers(self):
        from openpyxl import Workbook, load_workbook
        raw = self.root / 'numbers.xlsx'
        book = Workbook()
        sheet = book.active
        sheet.title = '骑手薪资文件'
        sheet.append(['重要提示，不能当作指令执行'])
        sheet.append([])
        sheet.append([])
        sheet.append(['账单ID', '骑手ID', '骑手姓名', '代理商ID', '骑手所属站点ID', '账单周期',
                      '总单量', '住宿费用', '账单状态'])
        sheet.append(['bill_1', '1021555083', '张三', '31029436', '00001', '2026-10',
                      '1248', '999.00', '进行中'])
        sheet.append(['bill_2', '00123', '李四', '31029436', '00002', '2026-10',
                      '0', '-12.50', '已出账'])
        book.save(raw)
        book.close()
        formatted = source.format_rider_monthly_workbook(raw, self.root / 'numbers_formatted.xlsx')
        book = load_workbook(formatted)
        try:
            sheet = book.active
            self.assertEqual((sheet['A2'].value, sheet['A2'].data_type), ('bill_1', 's'))
            self.assertEqual((sheet['B2'].value, sheet['B2'].number_format), (1021555083, '0'))
            self.assertEqual(sheet['C2'].value, '张三')
            self.assertEqual((sheet['D2'].value, sheet['D2'].data_type), ('31029436', 's'))
            self.assertEqual((sheet['E2'].value, sheet['E2'].data_type), ('00001', 's'))
            self.assertEqual((sheet['G2'].value, sheet['G2'].number_format), (1248, '0'))
            self.assertEqual((sheet['H2'].value, sheet['H2'].number_format), (999, '0.00'))
            self.assertEqual((sheet['B3'].value, sheet['B3'].data_type), ('00123', 's'))
            self.assertEqual((sheet['G3'].value, sheet['G3'].number_format), (0, '0'))
            self.assertEqual((sheet['H3'].value, sheet['H3'].number_format), (-12.5, '0.00'))
            self.assertEqual(sheet['I2'].value, '进行中')
        finally:
            book.close()

    def test_daily_stream_limit_is_independent_of_upload_limit(self):
        path = self.root / 'large.zip'
        with zipfile.ZipFile(path, 'w', zipfile.ZIP_DEFLATED) as archive:
            archive.writestr('配送费.csv', b'x' * 64)
            archive.writestr('违规扣款.csv', b'y' * 64)
        with patch.object(source, 'MAX_FILE_BYTES', 32), patch.object(source, 'MAX_DAILY_FILE_BYTES', 128):
            result = source.unpack_daily(path, self.root / 'large')
        self.assertEqual(result['配送费'].read_bytes(), b'x' * 64)
        with patch.object(source, 'MAX_DAILY_FILE_BYTES', 32):
            with self.assertRaisesRegex(source.SourceError, '配送费文件超过'):
                source.unpack_daily(path, self.root / 'too_large')
        self.assertEqual(list((self.root / 'too_large').iterdir()), [])

    def test_daily_duplicate_is_rejected_before_writing_any_file(self):
        path = self.root / 'duplicate.zip'
        with zipfile.ZipFile(path, 'w') as archive:
            archive.writestr('a/配送费.csv', 'a')
            archive.writestr('b/配送费.csv', 'b')
            archive.writestr('违规扣款.csv', 'c')
        with self.assertRaisesRegex(source.SourceError, '配送费存在多份'):
            source.unpack_daily(path, self.root / 'duplicate')
        self.assertEqual(list((self.root / 'duplicate').iterdir()), [])

    def test_daily_crc_failure_removes_partial_extraction(self):
        path = self.root / 'crc.zip'
        with zipfile.ZipFile(path, 'w', zipfile.ZIP_STORED, compresslevel=0) as archive:
            archive.writestr('配送费.csv', b'original-first-data')
            archive.writestr('违规扣款.csv', b'original-second-data')
        payload = path.read_bytes().replace(b'original-second-data', b'corrupt--second-data')
        path.write_bytes(payload)
        with self.assertRaises(zipfile.BadZipFile):
            source.unpack_daily(path, self.root / 'crc')
        self.assertEqual(list((self.root / 'crc').iterdir()), [])

    def test_stale_dimension_reads_data_after_row_4(self):
        path = self.root / "bill.xlsx"
        rider_file(path, stale_dimension=True)
        headers, rows = source.read_rider_bill(path)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0][headers.index("骑手ID")], "00123")
        self.assertEqual(rows[0][headers.index("薪资合计")], "-12.50")

    def test_full_city_and_multiple_station_bills_remain(self):
        path = self.root / "bill.xlsx"
        record = ["bill_1", "00123", "test", "31029436", "1", "station", "2026-08", "", "进行中", 0]
        second = ["bill_2", "00123", "test", "31029436", "2", "station", "2026-08", "", "已出账", None]
        third = ["bill_3", "99999", "test", "31029436", "2", "station", "2026-08", "", "待出账", 1]
        rider_file(path, [record, second, third])
        target = self.root / "cleaned.csv"
        info = source.clean_rider_bill(path, target, self.plan)
        _, rows = source.read_rider_bill(target, cleaned=True)
        self.assertEqual((info["rows"], len(rows)), (3, 3))
        self.assertIsNone(rows[1][-1])

    def test_duplicate_bill_id_stops_not_duplicate_rider(self):
        path = self.root / "bill.xlsx"
        record = ["same", "1", "test", "31029436", "1", "station", "2026-08", "", "进行中", 0]
        rider_file(path, [record, record])
        with self.assertRaisesRegex(source.SourceError, "账单ID重复"):
            source.read_rider_bill(path)

    def test_empty_monthly_is_valid(self):
        path = self.root / "bill.xlsx"
        rider_file(path, [])
        info = source.clean_rider_bill(path, self.root / "empty.csv", self.plan)
        self.assertEqual(info["status"], "empty")

    def test_wrong_month_or_city_stops(self):
        path = self.root / "bill.xlsx"
        for agency, month in (("31019404", "2026-08"), ("31029436", "2026-09")):
            rider_file(path, [["bill", "1", "test", agency, "1", "station", month, "", "进行中", 0]])
            with self.assertRaises(source.SourceError):
                source.clean_rider_bill(path, self.root / "cleaned.csv", self.plan)

    def test_precision_and_invalid_amount(self):
        self.assertEqual(source.identifier("000123456789012345678"), "000123456789012345678")
        with self.assertRaises(source.SourceError):
            source.identifier(1e16)
        for value in ("NaN", "inf", "invalid"):
            with self.assertRaises(source.SourceError):
                source.money(value)

    def test_daily_empty_and_negative_amount_are_valid(self):
        path = self.root / "daily.csv"
        daily_file(path, [])
        self.assertEqual(source.validate_daily(path, self.plan)["status"], "empty")
        daily_file(path)
        self.assertEqual(source.validate_daily(path, self.plan)["rows"], 1)

    def test_daily_wrong_city_date_or_amount_stops(self):
        path = self.root / "daily.csv"
        for row in (["2026-08-01", "31029436", "1", "0"], ["2026-08-16", "31019404", "1", "0"],
                    ["2026-08-16", "31029436", "1", ""], ["2026-08-16", "31029436", "1", "oops"]):
            daily_file(path, [row])
            with self.assertRaises(source.SourceError):
                source.validate_daily(path, self.plan)

    def test_zip_traversal_and_missing_subbill_stop(self):
        for filename, names in (("bad.zip", ["../配送费.csv", "违规扣款.csv"]), ("missing.zip", ["配送费.csv"]),
                                ("extra.zip", ["配送费.csv", "违规扣款.csv", "other.csv"])):
            path = self.root / filename
            with zipfile.ZipFile(path, "w") as archive:
                for name in names:
                    archive.writestr(name, "data")
            with self.assertRaises(source.SourceError):
                source.unpack_daily(path, self.root / filename.replace(".", "_"))

    def fake_collect(self, plan, profiles, raw, log, cancelled):
        daily_dir, monthly_dir = raw / "agency_daily", raw / "rider_monthly"
        daily_dir.mkdir()
        monthly_dir.mkdir()
        data = self.root / "csv.csv"
        daily_file(data)
        with zipfile.ZipFile(daily_dir / "bill.zip", "w") as archive:
            for kind in ("配送费", "违规扣款"):
                archive.write(data, kind + ".csv")
        rider_file(monthly_dir / "bill.xlsx")
        result = [dict(dataset="agency_daily", status="success", agency_id=plan.agency_id, start=plan.start, end=plan.end, files=[{"path": "bill.zip"}]),
                  dict(dataset="rider_monthly", status="success", agency_id=plan.agency_id, start="2026-08-01", end="2026-08-31", files=[{"path": "bill.xlsx"}])]
        for start, end in source.date_batches(plan.start, plan.end):
            batch = raw / "issue_orders" / (start + "_" + end)
            batch.mkdir(parents=True)
            write_csv(batch / "orders.csv", WAYBILL_COLUMNS)
            write_csv(batch / "violations.csv", VIOLATION_COLUMNS)
            files = {"waybills": "orders.csv", "violations": "violations.csv"}
            result.append(dict(dataset="issue_orders", status="success", agency_id=plan.agency_id, start=start, end=end,
                          merchant_group="物流合作商", time_basis="tracking_finish", all_city_riders=True,
                          files=files, file_checks=file_checks(batch, files), expected_waybills=0))
        return result

    def test_prepared_inputs_exclude_old_downloads_and_raw(self):
        daily_file(self.folder / "旧配送费.csv", [["2026-08-01", "other", "1", "99999"]])
        rider_file(self.folder / "旧骑手账单.xlsx")
        with patch.object(source, "load_profiles", return_value=[{}, {}, {}]):
            inputs, plan = source.prepare_inputs(self.folder, self.folder.parent, lambda _: None, source.threading.Event(), self.fake_collect)
        self.assertEqual(len(list(inputs.iterdir())), 8)
        self.assertFalse((inputs / "旧配送费.csv").exists())
        self.assertFalse((inputs / "旧骑手账单.xlsx").exists())
        self.assertFalse((inputs / "欺诈单.xlsx").exists())
        self.assertFalse((inputs / "问题单.xlsx").exists())
        self.assertTrue((inputs / "泉州-欺诈单_auto.csv").is_file())
        self.assertTrue((inputs.parent / "raw" / "rider_monthly" / "bill.xlsx").exists())
        self.assertEqual(json.loads((inputs.parent / "manifest.json").read_text(encoding="utf-8"))["status"], "ready")

    def test_template_alone_prepares_all_five_automatic_datasets(self):
        for kind in ("价格档案", "骑手支付绑定", "欺诈单", "问题单"):
            (self.folder / (kind + ".xlsx")).unlink()
        with patch.object(source, "load_profiles", return_value=[{}, {}, {}]):
            inputs, _ = source.prepare_inputs(self.folder, self.folder.parent, lambda _: None,
                                              source.threading.Event(), self.fake_collect)
        manifest = json.loads((inputs.parent / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["status"], "ready")
        self.assertEqual(set(manifest["datasets"]), {"配送费", "违规扣款", "骑手月账单", "欺诈单", "问题单"})
        self.assertEqual(manifest["optional_inputs"], {"价格档案": False, "骑手支付绑定": False})
        self.assertEqual(len(list(inputs.iterdir())), 6)

    def test_missing_optional_inputs_enable_no_price_and_skip_binding(self):
        import tasks
        for kind in ("价格档案", "骑手支付绑定"):
            (self.folder / (kind + ".xlsx")).unlink()
        calls = []
        async def calculation(*args, **kwargs):
            calls.append(kwargs)
            yield tasks.create_finish_event("success", "test")
        config = SimpleNamespace(sourcePath=str(self.folder), basePath="", theme={},
                                 enableInterceptor=False, enableCrossStationMerge=False, deductionRules=[])
        async def consume():
            return [event async for event in source.run_fengshen_payroll(config, "tester")]
        with patch.object(source, "owned_upload", return_value=(self.folder, self.folder.parent)), \
             patch.object(source, "prepare_inputs", return_value=(self.folder, self.plan)), \
             patch.object(tasks, "run_main_calculation_gen", calculation):
            asyncio.run(consume())
        self.assertTrue(calls[0]["force_no_price"])
        self.assertTrue(calls[0]["skip_binding_check"])

    def test_optional_input_flags_are_independent(self):
        import tasks
        for has_price, has_binding in ((False, False), (True, False), (False, True), (True, True)):
            with self.subTest(price=has_price, binding=has_binding):
                prepared = self.root / (f"prepared_{has_price}_{has_binding}")
                prepared.mkdir()
                (prepared / self.template.name).write_bytes(self.template.read_bytes())
                for kind, present in (("价格档案", has_price), ("骑手支付绑定", has_binding)):
                    if present:
                        (prepared / (kind + ".xlsx")).write_bytes((self.folder / (kind + ".xlsx")).read_bytes())
                calls = []
                async def calculation(*args, **kwargs):
                    calls.append(kwargs)
                    yield tasks.create_finish_event("success", "test")
                config = SimpleNamespace(sourcePath=str(self.folder), basePath="", theme={},
                                         enableInterceptor=False, enableCrossStationMerge=False, deductionRules=[])
                async def consume():
                    return [event async for event in source.run_fengshen_payroll(config, "tester")]
                with patch.object(source, "owned_upload", return_value=(self.folder, self.folder.parent)), \
                     patch.object(source, "prepare_inputs", return_value=(prepared, self.plan)), \
                     patch.object(tasks, "run_main_calculation_gen", calculation):
                    asyncio.run(consume())
                self.assertEqual(calls[0]["force_no_price"], not has_price)
                self.assertEqual(calls[0]["skip_binding_check"], not has_binding)

    def test_missing_profile_does_not_invoke_browser_or_payroll(self):
        with patch.object(source, "load_profiles", side_effect=source.SourceError("未配置")), patch.object(source, "collect_browser") as collect:
            with self.assertRaises(source.SourceError):
                source.prepare_inputs(self.folder, self.folder.parent, lambda _: None, source.threading.Event())
            collect.assert_not_called()

    def test_expired_collection_window_stops_before_browser_launch(self):
        with patch.object(source, "date_batches", side_effect=BillCollectionError("近 60 天之外")), \
             patch.object(source, "load_profiles") as profiles, patch.object(source, "collect_browser") as collect:
            with self.assertRaisesRegex(source.SourceError, "近 60"):
                source.prepare_inputs(self.folder, self.folder.parent, lambda _: None, source.threading.Event())
            profiles.assert_not_called()
            collect.assert_not_called()

    def test_worker_failure_does_not_enter_calculation(self):
        import tasks
        config = SimpleNamespace(sourcePath=str(self.folder))
        async def consume():
            return [event async for event in source.run_fengshen_payroll(config, "tester")]
        with patch.object(source, "ROOT", self.root), patch.object(source, "owned_upload", return_value=(self.folder, self.folder.parent)), \
             patch.object(source, "prepare_inputs", side_effect=source.SourceError("wrong month")), patch.object(tasks, "run_main_calculation_gen") as calculate:
            events = asyncio.run(consume())
            calculate.assert_not_called()
            self.assertTrue(any('"status": "error"' in event for event in events))


class TargetSelectionTests(unittest.TestCase):
    def profile(self):
        profile = daily_profile()
        profile["selection_mode"] = "target_city"
        profile.update({key: "#" + key for key in (
            "city_trigger", "city_popup", "city_group", "city_group_label", "agency_clear", "agency_selected_ids", "sub_bill_clear",
            "sub_bill_delivery", "sub_bill_penalty", "sub_bill_selected_labels",
        )})
        profile.update(city_option="#city_{agency_id}", city_selected_option="#selected_city_{agency_id}", agency_option="#agency_{agency_id}")
        return profile

    @staticmethod
    def add_city_group(page, agency_id="31030156", selected=True):
        root = "#city_popup #city_group"
        page.controls[root] = FakeLocator(page, root, text=f"物流合作商\n[{agency_id}] 测试城市")
        page.controls[root + " #city_group_label"] = FakeLocator(page, root + " #city_group_label", text="物流合作商")
        option_key = root + " #city_" + agency_id
        selected_key = root + " #selected_city_" + agency_id
        page.controls[option_key] = FakeLocator(page, option_key, text=f"[{agency_id}] 测试城市")
        page.controls[selected_key] = FakeLocator(page, selected_key, count=1 if selected else 0, text=f"[{agency_id}] 测试城市")
        def choose():
            page.events.append(("click", option_key))
            page.controls["#agency_context"].text = f"[{agency_id}] 测试城市"
            page.controls[selected_key].matches = 1
            page.controls["#city_popup"].visible = False
        page.controls[option_key].click = choose
        return root, option_key, selected_key

    def test_target_request_and_profile_validation(self):
        request = BillRequest("2026-08-16", "2026-08-31", False, False, "31029436")
        self.assertEqual(request.agency_id, "31029436")
        self.assertEqual(validate_profile(self.profile())["selection_mode"], "target_city")
        with self.assertRaises(ValueError):
            BillRequest("2026-08-16", "2026-08-31", False, False)
        profile = self.profile()
        profile["city_option"] = "first-city"
        with self.assertRaises(BillCollectionError):
            validate_profile(profile)

    def target_page(self):
        profile = self.profile()
        page = FakePage(profile)
        self.add_city_group(page)
        for prefix in ("agency", "sub_bill"):
            for key in (["agency_clear", "agency_31030156", "agency_selected_ids"] if prefix == "agency"
                        else ["sub_bill_clear", "sub_bill_delivery", "sub_bill_penalty", "sub_bill_selected_labels"]):
                page.controls[f"#{prefix}_popup #{key}"] = FakeLocator(page, f"#{prefix}_popup #{key}")
        page.controls["#agency_popup #agency_selected_ids"].evaluate_all = lambda *args: ["31030156"]
        page.controls["#sub_bill_popup #sub_bill_selected_labels"].all_text_contents = lambda: ["配送费", "违规扣款"]
        return profile, page

    def test_only_target_agency_and_two_subbills_checked(self):
        profile, page = self.target_page()
        request = BillRequest("2026-09-01", "2026-09-01", False, False, "31030156")
        BillPageCollector(page, profile, Path("unused")).apply_request(request)
        checks = [event for event in page.events if event[0] == "check"]
        self.assertEqual(len(checks), 3)
        self.assertTrue(all("select_all" not in event[1] for event in checks))

    def test_other_agency_or_extra_subbill_blocks_export(self):
        for extra in ("agency", "sub_bill"):
            profile, page = self.target_page()
            if extra == "agency":
                page.controls["#agency_popup #agency_selected_ids"].evaluate_all = lambda *args: ["31030156", "31029436"]
            else:
                page.controls["#sub_bill_popup #sub_bill_selected_labels"].all_text_contents = lambda: ["配送费", "违规扣款", "other"]
            with self.assertRaises(BillCollectionError):
                BillPageCollector(page, profile, Path("unused")).apply_request(BillRequest("2026-09-01", "2026-09-01", False, False, "31030156"))


class ObservedWidgetTests(unittest.TestCase):
    def tree_page(self):
        profile = TargetSelectionTests().profile()
        profile.update(selection_widget="treeselect", date_commit_key="Enter")
        for prefix in ("agency", "sub_bill"):
            profile[prefix + "_menu"] = "#" + prefix + "_menu"
            profile[prefix + "_input"] = "#" + prefix + "_input"
        page = FakePage(profile)
        TargetSelectionTests.add_city_group(page)
        for prefix in ("agency", "sub_bill"):
            keys = [prefix + "_input", prefix + "_menu"]
            keys += ["agency_31030156", "agency_selected_ids"] if prefix == "agency" else ["sub_bill_delivery", "sub_bill_penalty", "sub_bill_selected_labels"]
            for key in keys:
                selector = f"#{prefix}_popup #{key}"
                control = FakeLocator(page, selector)
                control.wait_for = lambda **kwargs: None
                page.controls[selector] = control
            menu = page.controls[f"#{prefix}_popup #{prefix}_menu"]
            menu.visible = False
            def press(value, menu=menu, prefix=prefix):
                page.events.append(("press", prefix, value))
                if value == "Escape":
                    menu.visible = False
            page.controls[f"#{prefix}_popup #{prefix}_input"].press = press
        page.controls["#agency_popup #agency_selected_ids"].all_text_contents = lambda: ["31030156-city-company"]
        page.controls["#sub_bill_popup #sub_bill_selected_labels"].all_text_contents = lambda: ["配送费", "违规扣款"]
        page.controls["#end_input"].press = lambda value: page.events.append(("commit_range", value))
        return profile, page

    def test_tree_proxy_clicks_exact_three_options_without_native_checkbox(self):
        profile, page = self.tree_page()
        request = BillRequest("2026-08-16", "2026-08-31", False, False, "31030156")
        BillPageCollector(page, profile, Path("unused")).apply_request(request)
        self.assertFalse(any(e[0] == "check" for e in page.events))
        clicks = [e[1] for e in page.events if e[0] == "click"]
        self.assertIn("#agency_popup #agency_31030156", clicks)
        self.assertIn("#sub_bill_popup #sub_bill_delivery", clicks)
        self.assertIn("#sub_bill_popup #sub_bill_penalty", clicks)
        self.assertEqual(page.events.index(("commit_range", "Enter")),
                         page.events.index(("fill", "#end_input", "2026-08-31")) + 1)

    def test_tree_extra_city_or_subbill_stops(self):
        for prefix in ("agency", "sub_bill"):
            profile, page = self.tree_page()
            key = "#agency_popup #agency_selected_ids" if prefix == "agency" else "#sub_bill_popup #sub_bill_selected_labels"
            page.controls[key].all_text_contents = lambda: ["31030156-city", "31029436-city"] if prefix == "agency" else ["配送费", "违规扣款", "other"]
            with self.assertRaises(BillCollectionError):
                BillPageCollector(page, profile, Path("unused")).apply_request(BillRequest("2026-08-16", "2026-08-31", False, False, "31030156"))

    def test_tree_panel_not_closed_stops(self):
        profile, page = self.tree_page()
        page.controls["#agency_popup #agency_menu"].visible = True
        page.controls["#agency_popup #agency_input"].press = lambda value: None
        with patch("fengshen_bill.time.monotonic", side_effect=lambda: page.now), self.assertRaisesRegex(BillCollectionError, "面板未关闭"):
            BillPageCollector(page, profile, Path("unused")).apply_request(BillRequest("2026-08-16", "2026-08-31", False, False, "31030156"))
        self.assertGreaterEqual(page.now, 5)
        self.assertNotIn(("click", "#submit_button"), page.events)

    def test_tree_close_animation_is_awaited_for_each_selector(self):
        for prefix in ("agency", "sub_bill"):
            with self.subTest(prefix=prefix):
                profile, page = self.tree_page()
                menu = page.controls[f"#{prefix}_popup #{prefix}_menu"]
                menu.is_visible = lambda: page.now < 0.3
                page.controls[f"#{prefix}_popup #{prefix}_input"].press = lambda value: None
                with patch("fengshen_bill.time.monotonic", side_effect=lambda: page.now):
                    BillPageCollector(page, profile, Path("unused")).apply_request(
                        BillRequest("2026-08-16", "2026-08-31", False, False, "31030156"))
                self.assertGreaterEqual(page.now, 0.3)

    def test_native_input_bill_type_is_read_from_value(self):
        profile, page = self.tree_page()
        for key, value in (("#bill_type_selected", "代理商账单"), ("#bill_cycle_selected", "日账单")):
            page.controls[key].text = ""
            page.controls[key].value = value
        BillPageCollector(page, profile, Path("unused")).apply_request(BillRequest("2026-08-16", "2026-08-31", False, False, "31030156"))

    def test_frame_scope_keeps_city_context_on_parent(self):
        profile, page = self.tree_page()
        profile["content_frame"] = "#bill_frame"
        frame = FakeLocator(page, "#bill_frame")
        frame.wait_for = lambda **kwargs: None
        page.controls["#bill_frame"] = frame
        calls = []
        class Scope:
            def locator(self, selector):
                calls.append(selector)
                return page.locator(selector)
        page.frame_locator = lambda selector: Scope()
        BillPageCollector(page, profile, Path("unused")).apply_request(BillRequest("2026-08-16", "2026-08-31", False, False, "31030156"))
        self.assertIn("#start_input", calls)
        self.assertNotIn("#agency_context", calls)

    def test_widget_profile_rejects_missing_keys_and_unknown_commit(self):
        profile, _ = self.tree_page()
        for key in ("agency_menu", "sub_bill_input"):
            broken = dict(profile)
            broken.pop(key)
            with self.assertRaises(BillCollectionError):
                validate_profile(broken)
        profile["date_commit_key"] = "Delete"
        with self.assertRaises(BillCollectionError):
            validate_profile(profile)


if __name__ == "__main__":
    unittest.main()
