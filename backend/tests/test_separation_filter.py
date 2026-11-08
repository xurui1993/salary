import csv
import sys
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from openpyxl import Workbook, load_workbook

sys.path.insert(0, str(Path(__file__).parents[1]))
from separation_filter import COLUMNS, filter_table, kept
from fengshen_bill import BillCollectionError


class SeparationFilterTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=Path(__file__).parent)
        self.root = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def csv_file(self, name, header, rows):
        path = self.root / name
        with path.open('w', encoding='utf-8-sig', newline='') as stream:
            writer = csv.writer(stream)
            writer.writerow(header)
            writer.writerows(rows)
        return path

    def test_keyword_match_directions(self):
        self.assertTrue(kept('深圳麻豆人-佳漾汇站（取分离）', True))
        self.assertFalse(kept('深圳麻豆人-同泰站_新专送', True))
        self.assertTrue(kept('深圳麻豆人-同泰站_新专送', False))
        self.assertFalse(kept('深圳麻豆人-佳漾汇站（取分离）', False))
        self.assertFalse(kept(None, True))

    def test_csv_filters_rows_and_keeps_original(self):
        path = self.csv_file('a.csv', ['团队名称', '骑手ID'],
                             [['深圳麻豆人-佳漾汇站（取分离）', 1], ['深圳麻豆人-同泰站_新专送', 2]])
        output, proof = filter_table(path, 'delivery_fee', True, self.root)
        self.assertEqual((proof['rows_before'], proof['rows_after'], proof['column']), (2, 1, '团队名称'))
        with output.open(encoding='utf-8-sig', newline='') as stream:
            rows = list(csv.reader(stream))
        self.assertEqual(rows[1][0], '深圳麻豆人-佳漾汇站（取分离）')
        self.assertTrue(path.is_file())
        output.unlink()

    def test_csv_streams_without_materializing_reader(self):
        path = self.csv_file('stream.csv', ['团队名称', '骑手ID'], [])
        class GuardedRows:
            def __init__(self):
                self.rows = iter([['团队名称', '骑手ID'], ['普通站', '0001'], ['取分离站', '0002']])
            def __iter__(self):
                return self
            def __next__(self):
                return next(self.rows)
            def __length_hint__(self):
                raise AssertionError('CSV reader must not be materialized')
        with patch('separation_filter.csv.reader', return_value=GuardedRows()):
            output, proof = filter_table(path, 'delivery_fee', False, self.root)
        with output.open(encoding='utf-8-sig', newline='') as stream:
            rows = list(csv.reader(stream))
        self.assertEqual(rows, [['团队名称', '骑手ID'], ['普通站', '0001']])
        self.assertEqual((proof['rows_before'], proof['rows_after']), (2, 1))

    def test_xlsx_monthly_bill_keeps_preamble_and_filters(self):
        path = self.root / 'bill.xlsx'
        book = Workbook(write_only=True)
        sheet = book.create_sheet()
        sheet.append(['重要提示：账单基础信息字段不可编辑'])
        sheet.append(['账单基础信息（不可编辑）'])
        sheet.append(['方案基本信息'])
        sheet.append(['账单ID', '骑手所属站点名称', '总单量'])
        sheet.append(['b1', '深圳麻豆人-佳漾汇站（取分离）', 5])
        sheet.append(['b2', '深圳麻豆人-同泰站_新专送', 9])
        book.save(path)
        book.close()
        output, proof = filter_table(path, 'rider_monthly', False, self.root)
        self.assertEqual((proof['rows_before'], proof['rows_after']), (2, 1))
        filtered = load_workbook(output, read_only=True)
        rows = list(filtered.worksheets[0].iter_rows(values_only=True))
        filtered.close()
        self.assertEqual(len(rows), 5)
        self.assertEqual(rows[0][0], '重要提示：账单基础信息字段不可编辑')
        self.assertEqual(rows[3][1], '骑手所属站点名称')
        self.assertEqual(rows[4][1], '深圳麻豆人-同泰站_新专送')
        output.unlink()

    def test_missing_column_and_dataset_stop(self):
        path = self.csv_file('a.csv', ['城市', '骑手ID'], [['泉州', 1]])
        with self.assertRaises(BillCollectionError):
            filter_table(path, 'delivery_fee', True, self.root)
        with self.assertRaises(BillCollectionError):
            filter_table(path, 'lanorange_summary', True, self.root)

    def test_xlsx_with_stale_dimension_tag_still_filters(self):
        import zipfile
        from xml.etree import ElementTree as ET
        path = self.root / 'rider_info.xlsx'
        book = Workbook(write_only=True)
        sheet = book.create_sheet()
        sheet.append(['骑手ID', '姓名', '部门'])
        sheet.append(['1', '张三', '三亚站'])
        sheet.append(['2', '李四', '三亚站(取分离)'])
        book.save(path)
        book.close()
        with zipfile.ZipFile(path) as archive:
            items = {name: archive.read(name) for name in archive.namelist()}
        namespace = '{http://schemas.openxmlformats.org/spreadsheetml/2006/main}'
        root = ET.fromstring(items['xl/worksheets/sheet1.xml'])
        dimension = root.find(namespace + 'dimension')
        if dimension is None:
            dimension = ET.SubElement(root, namespace + 'dimension')
        dimension.set('ref', 'A1')
        items['xl/worksheets/sheet1.xml'] = ET.tostring(root)
        with zipfile.ZipFile(path, 'w', zipfile.ZIP_DEFLATED) as archive:
            for name, data in items.items():
                archive.writestr(name, data)
        output, proof = filter_table(path, 'rider_info', False, self.root)
        self.assertEqual((proof['rows_before'], proof['rows_after']), (2, 1))
        book = load_workbook(output, read_only=True)
        rows = list(book.worksheets[0].iter_rows(values_only=True))
        book.close()
        self.assertEqual(rows[1][2], '三亚站')
        output.unlink()

    def test_every_fengshen_dataset_has_column(self):
        self.assertEqual(set(COLUMNS), {'delivery_fee', 'penalty', 'receive_account', 'rider_detail',
                                        'rider_info', 'problem', 'fraud', 'rider_monthly'})


if __name__ == '__main__':
    unittest.main()
