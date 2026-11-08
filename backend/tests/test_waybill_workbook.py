import re
import sys
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile

sys.path.insert(0, str(Path(__file__).parents[1]))
import waybill_workbook
from waybill_workbook import (SHEET_ROW_LIMIT, WAYBILL_TITLES, BillCollectionError,
                              merge_waybill_workbooks, write_waybill_workbook)


def shuffled_titles():
    values = list(WAYBILL_TITLES)
    values = values[::-1]
    return values


def make_source_xlsx(path, rows):
    from openpyxl import Workbook
    book = Workbook()
    sheet = book.active
    sheet.append(shuffled_titles())
    for row in rows:
        sheet.append([row.get(title) for title in shuffled_titles()])
    book.save(path)
    book.close()


def make_source_csv(path, rows):
    import csv
    with Path(path).open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(shuffled_titles())
        for row in rows:
            writer.writerow([row.get(title) for title in shuffled_titles()])


def make_platform_xlsx(path, rows, extra_titles=(), stale_dimension=True):
    from openpyxl import Workbook
    titles = list(WAYBILL_TITLES) + list(extra_titles)
    book = Workbook()
    sheet = book.active
    sheet.append(titles)
    for row in rows:
        sheet.append([row.get(title) for title in titles])
    book.save(path)
    book.close()
    if stale_dimension:
        with zipfile.ZipFile(path) as archive:
            items = {name: archive.read(name) for name in archive.namelist()}
        sheet_xml = items["xl/worksheets/sheet1.xml"].decode("utf-8")
        items["xl/worksheets/sheet1.xml"] = re.sub(
            r'<dimension ref="[^"]*"/>', '<dimension ref="A1"/>', sheet_xml, count=1).encode("utf-8")
        with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
            for name, data in items.items():
                archive.writestr(name, data)


class WaybillWorkbookTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=Path(__file__).parent)
        self.root = Path(self.temp.name)
        self.addCleanup(self.temp.cleanup)

    def read_result(self, path):
        from openpyxl import load_workbook
        return load_workbook(path)

    def sample_row(self, waybill_id="W-1"):
        return {"商id": "1", "商名称": "商家", "运单id": waybill_id, "订单号": "5100002026010112345678",
                "骑手id": "001", "运单状态": "配送失败", "运单创建时间": "2026-11-01 08:00:00"}

    def test_write_reorders_columns_and_keeps_style_contract(self):
        source = self.root / "source.xlsx"
        make_source_xlsx(source, [self.sample_row()])
        target = self.root / "out.xlsx"
        result = write_waybill_workbook(source, target)
        self.assertEqual(result["rows"], 1)
        self.assertEqual(result["sheets"], 1)
        book = self.read_result(target)
        self.assertEqual(book.sheetnames, ["运单明细1"])
        sheet = book["运单明细1"]
        self.assertEqual(sheet.freeze_panes, "A2")
        self.assertEqual([cell.value for cell in sheet[1]], list(WAYBILL_TITLES))
        header = sheet["A1"]
        self.assertEqual(header.font.name, "微软雅黑")
        self.assertEqual(header.font.size, 10)
        self.assertEqual(header.alignment.horizontal, "center")
        self.assertEqual(header.fill.fgColor.rgb, "FFFCE6D5")
        data = sheet["H2"]
        self.assertEqual(data.value, "5100002026010112345678")
        self.assertIsInstance(data.value, str)
        self.assertEqual(data.alignment.horizontal, "center")
        self.assertEqual(sheet["G2"].value, "W-1")
        self.assertEqual(sheet["A2"].value, "1")
        self.assertEqual(sheet["O2"].value, "配送失败")
        book.close()

    def test_platform_stale_dimension_and_new_columns_keep_confirmed_output(self):
        source = self.root / "platform.xlsx"
        make_platform_xlsx(source, [self.sample_row()],
                           extra_titles=("是否异常标记", "用户投诉内容", "用户评价等级"))
        target = self.root / "out.xlsx"
        result = write_waybill_workbook(source, target)
        self.assertEqual(result["rows"], 1)
        book = self.read_result(target)
        sheet = book["运单明细1"]
        self.assertEqual([cell.value for cell in sheet[1]], list(WAYBILL_TITLES))
        self.assertEqual(sheet["G2"].value, "W-1")
        book.close()

    def test_missing_confirmed_column_is_reported(self):
        from openpyxl import Workbook
        source = self.root / "missing.xlsx"
        book = Workbook()
        book.active.append([title for title in WAYBILL_TITLES if title != "运单状态"])
        book.save(source)
        book.close()
        with self.assertRaisesRegex(BillCollectionError, "运单状态"):
            write_waybill_workbook(source, self.root / "out.xlsx")

    def test_rows_beyond_limit_split_into_named_sheets(self):
        source = self.root / "source.csv"
        make_source_csv(source, [{"运单id": f"W-{index}"} for index in range(7)])
        target = self.root / "out.xlsx"
        with patch.object(waybill_workbook, "SHEET_ROW_LIMIT", 4):
            result = write_waybill_workbook(source, target)
        self.assertEqual(result["rows"], 7)
        # 每表容纳 SHEET_ROW_LIMIT-1 行数据（表头占 1 行），与 100 万上限同一口径。
        book = self.read_result(target)
        self.assertEqual(book.sheetnames, ["运单明细1", "运单明细2", "运单明细3"])
        first, second, third = (book[name] for name in book.sheetnames)
        self.assertEqual([first.max_row, second.max_row, third.max_row], [4, 4, 2])
        self.assertEqual([cell.value for cell in second[1]], list(WAYBILL_TITLES))
        self.assertEqual([sheet["G2"].value for sheet in (first, second, third)],
                         ["W-0", "W-3", "W-6"])
        book.close()

    def test_merge_requires_two_sources(self):
        source = self.root / "source.csv"
        make_source_csv(source, [self.sample_row()])
        with self.assertRaises(BillCollectionError):
            merge_waybill_workbooks([source], self.root / "out.xlsx")

    def test_merge_combines_rows_from_both_sources(self):
        first, second = self.root / "a.csv", self.root / "b.csv"
        make_source_csv(first, [self.sample_row("W-1")])
        make_source_csv(second, [self.sample_row("W-2"), self.sample_row("W-3")])
        target = self.root / "out.xlsx"
        result = merge_waybill_workbooks([first, second], target)
        self.assertEqual(result["rows"], 3)
        book = self.read_result(target)
        sheet = book["运单明细1"]
        self.assertEqual([sheet[f"G{row}"].value for row in (2, 3, 4)], ["W-1", "W-2", "W-3"])
        book.close()

    def test_unexpected_header_stops_generation(self):
        source = self.root / "bad.xlsx"
        from openpyxl import Workbook
        book = Workbook()
        book.active.append(list(WAYBILL_TITLES[:10]))
        book.save(source)
        book.close()
        with self.assertRaises(BillCollectionError):
            write_waybill_workbook(source, self.root / "out.xlsx")

    def test_header_only_source_produces_header_only_workbook(self):
        source = self.root / "empty.csv"
        make_source_csv(source, [])
        target = self.root / "out.xlsx"
        result = write_waybill_workbook(source, target)
        self.assertEqual(result["rows"], 0)
        book = self.read_result(target)
        sheet = book["运单明细1"]
        self.assertEqual(sheet.max_row, 1)
        self.assertEqual([cell.value for cell in sheet[1]], list(WAYBILL_TITLES))
        book.close()


if __name__ == "__main__":
    unittest.main()
