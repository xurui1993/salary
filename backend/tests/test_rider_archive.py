import datetime as dt
import hashlib
from pathlib import Path
import sys
import tempfile
import unittest

from openpyxl import Workbook, load_workbook

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from fengshen_bill import BillCollectionError
from rider_archive import COLUMNS, format_full_workbook, read_archive

SOURCE_HEADER = ['备注', '姓名', '项目', '城市', '站点', '骑手ID', '身份证号', '合作类型',
                 '当前生效兼职价格', '合作日期', '推荐人身份证号', '三方公司/推荐人',
                 '招聘来源', '状态', '是否寒暑假工']


def source_row(name, project, city, status='正常'):
    return ['', name, project, city, '站点A', 'R001', '460200199001010011', '全职', 8.5,
            dt.datetime(2026, 1, 2), None, None, '骑手内推', status, '否']


def build_source(path, rows, extra_sheets=True):
    book = Workbook()
    sheet = book.active
    sheet.title = '骑手档案'
    sheet.append(SOURCE_HEADER)
    for values in rows:
        sheet.append(values)
    if extra_sheets:
        note = book.create_sheet('全量下载说明')
        note.append(['文件性质', '系统合并'])
        hidden = book.create_sheet('options_0')
        hidden.append(['option'])
        hidden.sheet_state = 'hidden'
    book.save(path)
    book.close()


class RiderArchiveTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=Path(__file__).parent)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def test_full_workbook_keeps_all_rows_projects_14_columns_and_sorts_blanks_last(self):
        source = self.root / '原始.xlsx'
        build_source(source, [
            source_row('孙八', '淘鲜达', '三亚市', '=待定'),
            source_row('李四', 'U+B', '海口市'),
            source_row('赵六', None, '三亚市'),
            source_row('王五', '城代', '三亚市'),
            source_row('张三', '饿了么', '三亚市'),
            source_row('周九', '饿了么', '海口市'),
        ])
        book = load_workbook(source)
        book['骑手档案'].cell(2, 14).data_type = 's'
        book.save(source)
        book.close()
        before = hashlib.sha256(source.read_bytes()).hexdigest()

        output, stats = format_full_workbook(source, self.root)

        self.assertEqual(stats, {'rows': 6, 'columns': list(COLUMNS)})
        self.assertEqual(hashlib.sha256(source.read_bytes()).hexdigest(), before)
        book = load_workbook(output, data_only=False)
        try:
            self.assertEqual(book.sheetnames, ['骑手档案', '全量下载说明'])
            sheet = book['骑手档案']
            self.assertEqual([cell.value for cell in sheet[1]], list(COLUMNS))
            self.assertEqual(sheet.freeze_panes, 'A2')
            self.assertIsNotNone(sheet.column_dimensions['A'].width)
            self.assertEqual(sheet.max_row, 7)
            self.assertEqual([sheet.cell(row, 1).value for row in range(2, 8)],
                             ['U+B', '城代', '饿了么', '饿了么', '淘鲜达', None])
            self.assertEqual([sheet.cell(row, 5).value for row in range(2, 8)],
                             ['李四', '王五', '张三', '周九', '孙八', '赵六'])
            self.assertEqual(sheet.cell(2, 9).value, dt.datetime(2026, 1, 2))
            self.assertEqual(sheet.cell(2, 9).data_type, 'd')
            self.assertEqual(sheet.cell(2, 9).number_format, 'yyyy-mm-dd h:mm:ss')
            self.assertEqual(sheet.cell(6, 13).value, '=待定')
            self.assertEqual(sheet.cell(6, 13).data_type, 's')
            self.assertEqual(book['全量下载说明'].cell(1, 1).value, '文件性质')
        finally:
            book.close()

    def test_read_archive_applies_city_and_project_filters(self):
        source = self.root / '原始.xlsx'
        build_source(source, [
            source_row('孙八', '淘鲜达', '三亚市'),
            source_row('赵六', None, '三亚市'),
            source_row('王五', '城代', '三亚市'),
            source_row('张三', '饿了么', '三亚市'),
            source_row('李四', 'U+B', '海口市'),
        ], extra_sheets=False)
        book = load_workbook(source, read_only=True, data_only=False)
        try:
            rows, widths = read_archive(book['骑手档案'], city='三亚', projects=('U+B', '饿了么', '淘鲜达'))
        finally:
            book.close()
        self.assertEqual([[cell.value for cell in row][4] for row in rows], ['张三', '孙八'])
        self.assertEqual(len(widths), 14)

    def test_missing_contract_columns_raise(self):
        source = self.root / '冲突.xlsx'
        book = Workbook()
        book.active.title = '骑手档案'
        book.active.append(['城市', '姓名'])
        book.active.append(['三亚', '张三'])
        book.save(source)
        book.close()
        with self.assertRaisesRegex(BillCollectionError, '缺少字段'):
            format_full_workbook(source, self.root)


if __name__ == '__main__':
    unittest.main()
