"""Fast value-only XLSX reads for large generated workbooks."""
from contextlib import contextmanager
from pathlib import Path

try:
    from python_calamine import CalamineWorkbook
except Exception:
    CalamineWorkbook = None


def _clean(value):
    return None if value == '' else value


@contextmanager
def open_values(path):
    path = Path(path)
    if CalamineWorkbook is not None:
        book = CalamineWorkbook.from_path(str(path))
        class Book:
            sheetnames = list(book.sheet_names)
            def rows(self, name):
                for row in book.get_sheet_by_name(name).to_python():
                    yield tuple(_clean(value) for value in row)
        yield Book()
        return
    from openpyxl import load_workbook
    book = load_workbook(path, read_only=True, data_only=True)
    try:
        class Book:
            sheetnames = list(book.sheetnames)
            def rows(self, name):
                yield from book[name].iter_rows(values_only=True)
        yield Book()
    finally:
        book.close()


def sheet_names(path):
    path = Path(path)
    if CalamineWorkbook is not None:
        return list(CalamineWorkbook.from_path(str(path)).sheet_names)
    from openpyxl import load_workbook
    book = load_workbook(path, read_only=True)
    try:
        return list(book.sheetnames)
    finally:
        book.close()