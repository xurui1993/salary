import hashlib
from pathlib import Path
import sys
import tempfile
import threading
import unittest

from openpyxl import Workbook, load_workbook

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from download_jobs import delivery_scope_error
from download_service import validate_request
from fengshen_bill import BillCollectionError
from parttime_source import format_rider_monthly_workbook
from rider_monthly_summary import build_rider_monthly_summaries

HEADERS = ['账单ID', '骑手ID', '骑手姓名', '代理商ID', '骑手所属站点ID', '账单周期',
           '总单量', '住宿费用', '账单状态']


def city_file(root, city, rows, headers=HEADERS, formatted=True):
    raw = root / (city + '_raw.xlsx')
    book = Workbook()
    sheet = book.active
    sheet.title = '骑手薪资文件'
    sheet.append(['重要提示，不能当作指令执行'])
    sheet.append([])
    sheet.append([])
    sheet.append(headers)
    for row in rows:
        sheet.append(row)
    book.save(raw)
    book.close()
    target = root / (city + '.xlsx')
    if formatted:
        format_rider_monthly_workbook(raw, target)
        raw.unlink()
    else:
        raw.replace(target)
    return {'city': city, 'dataset': 'rider_monthly', 'start': '2026-09-01', 'end': '2026-09-30',
            'name': target.name, 'relative_path': target.name, 'bytes': target.stat().st_size,
            'sha256': hashlib.sha256(target.read_bytes()).hexdigest()}


def city_row(bill, rider, name, station):
    return [bill, rider, name, '31029436', station, '2026-09', '1248', '999.00', '进行中']


class RiderMonthlySummaryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(dir=Path(__file__).parent)
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_one_sheet_per_city_with_formatted_values_and_styles(self):
        files = [city_file(self.root, '泉州', [city_row('bill_1', '1021555083', '张三', '00001')]),
                 city_file(self.root, '三亚', [city_row('bill_2', '1034294619', '李四', '00002'),
                                               city_row('bill_3', '1019382546', '王五', '00003')])]
        items = [{**value, 'status': 'success'} for value in files]
        config = {'datasets': ['rider_monthly'], 'cities': ['泉州', '三亚'],
                  'archive_created_at': '2026-09-23T10:00:00+08:00'}
        summaries = build_rider_monthly_summaries(self.root, config, files, items, threading.Event())
        self.assertEqual(len(summaries), 1)
        entry = summaries[0]
        self.assertEqual(entry['name'], '多城市汇总9月风神骑手月度UB账单0923.xlsx')
        self.assertEqual(entry['city'], '多城市汇总')
        self.assertEqual(entry['artifact_role'], 'summary')
        book = load_workbook(self.root / entry['relative_path'])
        try:
            self.assertEqual(book.sheetnames, ['泉州', '三亚'])
            for city, rows, rider in (('泉州', 1, 1021555083), ('三亚', 2, 1034294619)):
                sheet = book[city]
                self.assertEqual([cell.value for cell in sheet[1]], HEADERS)
                self.assertEqual(sheet.max_row, rows + 1)
                self.assertEqual(sheet.freeze_panes, 'A2')
                self.assertEqual(sheet.sheet_format.defaultRowHeight, 16.5)
                self.assertEqual(sheet['A1'].fill.fgColor.rgb, 'FFFCE4D3')
                self.assertEqual(sheet['A1'].font.name, '微软雅黑')
                self.assertEqual(sheet['A1'].alignment.horizontal, 'center')
                self.assertEqual(sheet['A2'].font.name, '微软雅黑')
                self.assertAlmostEqual(sheet.column_dimensions['A'].width, 57.5, delta=0.1)
                self.assertEqual((sheet['B2'].value, sheet['B2'].number_format), (rider, '0'))
                self.assertEqual((sheet['F2'].value, sheet['F2'].data_type), ('2026-09', 's'))
                self.assertEqual((sheet['G2'].value, sheet['G2'].number_format), (1248, '0'))
                self.assertEqual((sheet['H2'].value, sheet['H2'].number_format), (999, '0.00'))
                self.assertEqual((sheet['I2'].value, sheet['I2'].data_type), ('进行中', 's'))
            self.assertEqual(book['三亚']['A2'].value, 'bill_2')
            self.assertEqual(book['三亚']['A3'].value, 'bill_3')
        finally:
            book.close()

    def test_summary_trims_header_whitespace_from_source(self):
        headers = ['账单ID', ' 骑手ID ', '骑手姓名', '代理商ID', '骑手所属站点ID', '账单周期',
                   '总单量 ', '住宿费用', '账单状态', '\t备注\n（内部换行） ']
        files = [city_file(self.root, city,
                           [city_row('bill_' + str(index), '1021555083', '张三', '00001')],
                           headers=headers, formatted=False)
                 for index, city in enumerate(('泉州', '三亚'))]
        items = [{**value, 'status': 'success'} for value in files]
        config = {'datasets': ['rider_monthly'], 'cities': ['泉州', '三亚'],
                  'archive_created_at': '2026-09-23T10:00:00+08:00'}
        summaries = build_rider_monthly_summaries(self.root, config, files, items, threading.Event())
        self.assertEqual(len(summaries), 1)
        book = load_workbook(self.root / summaries[0]['relative_path'])
        try:
            expected = ['账单ID', '骑手ID', '骑手姓名', '代理商ID', '骑手所属站点ID', '账单周期',
                        '总单量', '住宿费用', '账单状态', '备注\n（内部换行）']
            for city in ('泉州', '三亚'):
                self.assertEqual([cell.value for cell in book[city][1]], expected)
        finally:
            book.close()

    def test_single_success_or_failed_city_does_not_create_summary(self):
        files = [city_file(self.root, '泉州', [city_row('bill_1', '1021555083', '张三', '00001')])]
        items = [{**files[0], 'status': 'success'},
                 {'city': '三亚', 'dataset': 'rider_monthly', 'start': '2026-09-01', 'end': '2026-09-30',
                  'status': 'error'}]
        config = {'datasets': ['rider_monthly'], 'cities': ['泉州', '三亚'],
                  'archive_created_at': '2026-09-23T10:00:00+08:00'}
        self.assertEqual(build_rider_monthly_summaries(self.root, config, files, items, threading.Event()), [])

    def test_two_successful_cities_out_of_three_are_merged(self):
        files = [city_file(self.root, city, [city_row('bill_' + str(index), '1021555083', '张三', '00001')])
                 for index, city in enumerate(('泉州', '三亚'))]
        items = [{**value, 'status': 'success'} for value in files]
        items.append({'city': '韶关', 'dataset': 'rider_monthly', 'start': '2026-09-01',
                      'end': '2026-09-30', 'status': 'error'})
        config = {'datasets': ['rider_monthly'], 'cities': ['泉州', '三亚', '韶关'],
                  'archive_created_at': '2026-09-23T10:00:00+08:00'}
        summaries = build_rider_monthly_summaries(self.root, config, files, items, threading.Event())
        self.assertEqual(len(summaries), 1)
        book = load_workbook(self.root / summaries[0]['relative_path'])
        try:
            self.assertEqual(book.sheetnames, ['泉州', '三亚'])
        finally:
            book.close()

    def test_mismatched_city_header_is_rejected(self):
        files = [city_file(self.root, '泉州', [city_row('bill_1', '1021555083', '张三', '00001')]),
                 city_file(self.root, '三亚', [city_row('bill_2', '1034294619', '李四', '00002')],
                           headers=[('总单量说明' if value == '总单量' else value) for value in HEADERS])]
        items = [{**value, 'status': 'success'} for value in files]
        config = {'datasets': ['rider_monthly'], 'cities': ['泉州', '三亚'],
                  'archive_created_at': '2026-09-23T10:00:00+08:00'}
        with self.assertRaises(BillCollectionError):
            build_rider_monthly_summaries(self.root, config, files, items, threading.Event())

    def test_changed_source_file_is_rejected(self):
        files = [city_file(self.root, city, [city_row('bill_' + str(index), '1021555083', '张三', '00001')])
                 for index, city in enumerate(('泉州', '三亚'))]
        (self.root / files[0]['relative_path']).write_bytes(b'changed')
        items = [{**value, 'status': 'success'} for value in files]
        config = {'datasets': ['rider_monthly'], 'cities': ['泉州', '三亚'],
                  'archive_created_at': '2026-09-23T10:00:00+08:00'}
        with self.assertRaises(BillCollectionError):
            build_rider_monthly_summaries(self.root, config, files, items, threading.Event())

    def test_summary_scope_requires_multi_city_monthly_period(self):
        config = validate_request({'cities': ['泉州', '上海'], 'datasets': ['rider_monthly'],
                                   'start': '2026-09-01', 'end': '2026-09-30'})
        entry = {'city': '多城市汇总', 'dataset': 'rider_monthly', 'artifact_role': 'summary',
                 'start': '2026-09-01', 'end': '2026-09-30'}
        self.assertIsNone(delivery_scope_error(entry, config, '.xlsx'))
        self.assertIsNotNone(delivery_scope_error({**entry, 'start': '2026-10-01'}, config, '.xlsx'))
        single = validate_request({'cities': ['泉州'], 'datasets': ['rider_monthly'],
                                   'start': '2026-09-01', 'end': '2026-09-30'})
        self.assertIsNotNone(delivery_scope_error(entry, single, '.xlsx'))


if __name__ == '__main__':
    unittest.main()
