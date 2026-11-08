import asyncio
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from followup_workbook import create_followup_workbook
import main


class CodeWorkbookTests(unittest.TestCase):
    def test_schema_and_styles_match_preserved_header_contract(self):
        fixture = json.loads((Path(__file__).resolve().parents[2] / 'tests/fixtures/followup_header.json').read_text(encoding='utf-8'))
        for month in ('2026-10', '2027-02'):
            book = create_followup_workbook(month)
            self.addCleanup(book.close)
            label = f'{int(month[-2:])}月'
            replace = lambda value: value.replace('10月', label)
            self.assertEqual(book.sheetnames, list(map(replace, fixture['sheetnames'])))
            ws = book.worksheets[2]
            self.assertEqual(ws.max_row, 3)
            self.assertEqual(ws.max_column, 31)
            self.assertEqual([cell.value for cell in ws[3]], list(map(replace, fixture['headers'])))
            self.assertEqual(set(map(str, ws.merged_cells.ranges)), set(fixture['merges']))
            for coordinate, value in fixture['groups']:
                self.assertEqual(ws[coordinate].value, replace(value))
            for coordinate, (fill, color, size, bold, wrap, number) in fixture['styles'].items():
                cell = ws[coordinate]
                self.assertEqual((cell.fill.fgColor.rgb, cell.font.color.rgb, cell.font.sz, cell.font.bold, bool(cell.alignment.wrap_text), cell.number_format),
                                 (fill, color, size, bold, wrap, number))
            for column, width in fixture['widths'].items():
                self.assertEqual(ws.column_dimensions[column].width, width)
            self.assertEqual(ws.freeze_panes, 'A4')

    def test_retired_template_is_neither_listed_nor_downloaded(self):
        with tempfile.TemporaryDirectory() as folder:
            templates = Path(folder) / 'system_templates'; templates.mkdir()
            (templates / '城市-template.xlsx').touch()
            (templates / '异常骑手跟进模板.xlsx').touch()
            with patch.object(main, 'get_project_root', return_value=folder):
                values = asyncio.run(main.list_templates())['templates']
                self.assertEqual([item['filename'] for item in values], ['城市-template.xlsx'])
                with self.assertRaises(main.HTTPException) as error:
                    asyncio.run(main.download_template('异常骑手跟进模板.xlsx'))
                self.assertEqual(error.exception.status_code, 410)


if __name__ == '__main__': unittest.main()
