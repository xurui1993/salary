import sys
from pathlib import Path
import tempfile
import unittest

from openpyxl import Workbook

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from fast_xlsx import open_values, sheet_names


class FastXlsxTests(unittest.TestCase):
    def test_values_and_blank_cells_match_generated_workbooks(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as directory:
            path = Path(directory) / 'values.xlsx'
            book = Workbook(); sheet = book.active
            sheet.title = '结果'
            sheet.append(['ID', '姓名', '数量', '空值'])
            sheet.append(['0001', '张三', 12, None])
            sheet.append(['0002', '李四', 0, None])
            book.save(path); book.close()
            self.assertEqual(sheet_names(path), ['结果'])
            with open_values(path) as source:
                rows = list(source.rows('结果'))
            self.assertEqual(rows[0], ('ID', '姓名', '数量', '空值'))
            self.assertEqual([row[0] for row in rows[1:]], ['0001', '0002'])
            self.assertEqual([row[2] for row in rows[1:]], [12, 0])
            self.assertEqual([row[3] for row in rows[1:]], [None, None])


if __name__ == '__main__':
    unittest.main()