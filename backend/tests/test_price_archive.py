import datetime as dt
from pathlib import Path
import sys
import tempfile
import threading
import unittest

from openpyxl import Workbook, load_workbook

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from fengshen_bill import BillCollectionError
from price_archive import filter_workbook, month_of, write_filtered_sheet


def write_price(path, sheets):
    book = Workbook()
    book.remove(book.active)
    for title, rows in sheets.items():
        sheet = book.create_sheet(title)
        for row in rows:
            sheet.append(row)
    book.save(path)
    book.close()


class PriceArchiveTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=Path(__file__).parent)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def source(self):
        path = self.root / 'price.xlsx'
        write_price(path, {
            '价格档案': [
                ['城市名称', '站点名称', '日期', '骑手姓名', '价格', '备注'],
                ['三亚市', '三亚一组', '2026-10-01', '张三', 10, None],
                ['三亚市', '三亚一组', '2026-09-30', '李四', 20, None],
                ['海口市', '海口一组', '2026-10-02', '王五', 30, None],
                ['三亚市', '三亚一组', '', '赵六', 40, None],
                ['三亚市', '三亚一组', 'bad-date', '钱七', 50, None],
                ['三亚市', '三亚一组', '2026-10-03', '孙八', 60, '=待定'],
                [None, None, None, None, None, None],
            ],
            '全量下载说明': [['完整性', '所有分批数量核对通过'],
                         ['数据范围', '账号全部可访问数据；全部状态、不按日期筛选']],
            'options_0': [['选项']],
        })
        book = load_workbook(path)
        book['options_0'].sheet_state = 'hidden'
        book.save(path)
        book.close()
        return path

    def test_filter_workbook_keeps_selected_months_and_drops_hidden_sheets(self):
        path = self.source()
        before = path.read_bytes()
        result, stats = filter_workbook(path, self.root, ['2026-10'], cancelled=threading.Event())
        self.assertEqual(path.read_bytes(), before)
        self.assertEqual(stats['before'], 6)
        self.assertEqual(stats['after'], 3)
        self.assertEqual(stats['month'], 1)
        self.assertEqual(stats['invalid'], 2)
        book = load_workbook(result, data_only=False)
        try:
            self.assertEqual(book.sheetnames, ['价格档案', '全量下载说明'])
            rows = list(book['价格档案'].iter_rows(values_only=True))
            self.assertEqual(rows[0], ('城市名称', '站点名称', '日期', '骑手姓名', '价格', '备注'))
            self.assertEqual([row[3] for row in rows[1:]], ['张三', '王五', '孙八'])
            self.assertEqual(rows[-1][5], '=待定')
            note = list(book['全量下载说明'].iter_rows(values_only=True))
            self.assertEqual(note[1][0], '数据范围')
            self.assertIn('2026-10', note[1][1])
            self.assertIn('6 → 3 行', note[1][1])
            self.assertNotIn('不按日期筛选', note[1][1])
        finally:
            book.close()

    def test_multiple_months_keep_every_covered_month(self):
        result, stats = filter_workbook(self.source(), self.root, ['2026-09', '2026-10'])
        self.assertEqual(stats['after'], 4)
        book = load_workbook(result, read_only=True)
        try:
            names = [row[3] for row in book['价格档案'].iter_rows(min_row=2, values_only=True)]
        finally:
            book.close()
        self.assertEqual(names, ['张三', '李四', '王五', '孙八'])

    def test_city_filter_normalizes_suffix_and_keeps_month(self):
        result, stats = filter_workbook(self.source(), self.root, ['2026-10'], city='三亚')
        self.assertEqual(stats['after'], 2)
        self.assertEqual(stats['city'], 1)
        book = load_workbook(result, read_only=True)
        try:
            names = [row[3] for row in book['价格档案'].iter_rows(min_row=2, values_only=True)]
        finally:
            book.close()
        self.assertEqual(names, ['张三', '孙八'])

    def test_followup_writer_filters_and_centers_cells(self):
        source = load_workbook(self.source(), read_only=True, data_only=False)
        book = Workbook()
        sheet = book.active
        sheet.title = '蓝橙价格档案'
        try:
            stats = write_filtered_sheet(sheet, source['价格档案'], ['2026-10'], '三亚市')
        finally:
            source.close()
        try:
            self.assertEqual(stats['after'], 2)
            self.assertEqual((sheet.max_row, sheet.max_column), (3, 6))
            self.assertTrue(sheet.cell(1, 1).font.bold)
            self.assertEqual(sheet.cell(2, 1).alignment.horizontal, 'center')
            self.assertEqual(sheet.column_dimensions['A'].alignment.horizontal, 'center')
            self.assertIsNotNone(sheet.column_dimensions['A'].width)
            self.assertEqual(sheet.freeze_panes, 'A2')
        finally:
            book.close()

    def test_missing_date_or_city_columns_raise(self):
        no_date = self.root / 'no-date.xlsx'
        write_price(no_date, {'价格档案': [['城市名称', '价格'], ['三亚市', 10]]})
        with self.assertRaisesRegex(BillCollectionError, '缺少字段'):
            filter_workbook(no_date, self.root, ['2026-10'])
        no_city = self.root / 'no-city.xlsx'
        write_price(no_city, {'价格档案': [['日期', '价格'], ['2026-10-01', 10]]})
        with self.assertRaisesRegex(BillCollectionError, '缺少字段'):
            filter_workbook(no_city, self.root, ['2026-10'], city='三亚')

    def test_month_parser_accepts_text_and_date_values(self):
        self.assertEqual(month_of(dt.datetime(2026, 10, 1, 8)), '2026-10')
        self.assertEqual(month_of(dt.date(2026, 9, 30)), '2026-09')
        self.assertEqual(month_of('2026/10/01'), '2026-10')
        self.assertEqual(month_of('2026年10月'), '2026-10')
        self.assertIsNone(month_of(''))
        self.assertIsNone(month_of('2026-13-01'))


if __name__ == '__main__':
    unittest.main()
