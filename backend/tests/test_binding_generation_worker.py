import sys
from pathlib import Path
import tempfile
import unittest

from openpyxl import Workbook, load_workbook

sys.path.insert(0, str(Path(__file__).parents[1]))
from binding_generation_worker import filter_sources


class WorkerSourceFilterTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=Path(__file__).parent)
        self.root = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def workbook(self, rows):
        path = self.root / 'rider_info.xlsx'
        book = Workbook(write_only=True)
        sheet = book.create_sheet()
        sheet.append(['骑手ID', '姓名', '部门'])
        for row in rows:
            sheet.append(row)
        book.save(path)
        book.close()
        return path

    def spec(self, path, include):
        return {'paths': {'rider_info': str(path)}, 'plan': {'city': '泉州', 'month': '2026-09'},
                'directory': str(self.root), 'separation_include': include,
                'labels': {'rider_info': '骑手信息导出'}}

    def test_filter_runs_inside_worker_and_reports_proof(self):
        path = self.workbook([['1', '张三', '泉州站'], ['2', '李四', '泉州站（取分离）']])
        logs = []
        paths, seconds = filter_sources(self.spec(path, False),
                                        lambda message, *args, **kwargs: logs.append(message))
        output = paths['rider_info']
        self.assertNotEqual(output, path)
        self.assertGreaterEqual(seconds, 0)
        book = load_workbook(output, read_only=True)
        try:
            rows = list(book.active.iter_rows(values_only=True))
        finally:
            book.close()
        self.assertEqual([row[0] for row in rows[1:]], ['1'])
        self.assertEqual(logs, ['泉州 · 2026-09 骑手信息导出：取分离过滤（排除）2 → 1 行'])

    def test_no_filter_setting_keeps_sources_untouched(self):
        path = self.workbook([['1', '张三', '泉州站（取分离）']])
        paths, seconds = filter_sources(self.spec(path, None), lambda *args, **kwargs: None)
        self.assertEqual(paths['rider_info'], path)
        self.assertEqual(seconds, 0.0)


if __name__ == '__main__':
    unittest.main()