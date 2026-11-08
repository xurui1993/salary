"""Task-only immutable source rows, retaining Excel value types and formats."""
from contextlib import contextmanager
from dataclasses import dataclass
import sys

from openpyxl import load_workbook
from generation_performance import shared_cache


@dataclass(frozen=True, slots=True)
class SourceCell:
    value: object
    row: int
    column: int
    data_type: str
    number_format: str


class SourceTooLarge(Exception):
    pass


class SourceSheet:
    def __init__(self, sheet, cancelled, limit):
        if (sheet.max_row or 0) * (sheet.max_column or 0) * 160 > limit:
            raise SourceTooLarge()
        self.title = sheet.title
        rows, size = [], 0
        for row in sheet.iter_rows():
            if cancelled is not None and cancelled.is_set():
                from fengshen_bill import BillCollectionError
                raise BillCollectionError('资料读取已取消')
            values = tuple(SourceCell(cell.value, len(rows) + 1, index, cell.data_type, cell.number_format)
                           for index, cell in enumerate(row, 1))
            size += sys.getsizeof(values) + sum(sys.getsizeof(cell) + sys.getsizeof(cell.value) for cell in values)
            if size > limit:
                raise SourceTooLarge()
            rows.append(values)
        self.values = tuple(rows)
        self.nbytes = size + sys.getsizeof(self.values)
        self.max_row = len(rows)
        self.max_column = max((len(row) for row in rows), default=0)

    def iter_rows(self, min_row=1, max_row=None, values_only=False):
        for row in self.values[min_row - 1:max_row]:
            yield tuple(cell.value for cell in row) if values_only else row


@contextmanager
def source_sheet(path, suffix, find_sheet, cancelled=None):
    cache = shared_cache()
    if cache is None or not cache.reuse_tables:
        book = load_workbook(path, read_only=True, data_only=False)
        try:
            yield find_sheet(book, suffix)
        finally:
            book.close()
        return

    def load(file):
        book = load_workbook(file, read_only=True, data_only=False)
        try:
            return SourceSheet(find_sheet(book, suffix), cancelled, cache.limit)
        finally:
            book.close()
    try:
        value = cache.immutable(path, ('source_sheet', suffix, 'formulas'), load)
    except SourceTooLarge:
        book = load_workbook(path, read_only=True, data_only=False)
        try:
            yield find_sheet(book, suffix)
        finally:
            book.close()
        return
    yield value
