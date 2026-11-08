"""Bounded handoff of the exact exported binding values to follow-up generation."""
from dataclasses import dataclass
from datetime import date, datetime, timedelta
import hashlib
import math
from pathlib import Path
import re
from types import SimpleNamespace
from xml.etree import ElementTree
from zipfile import ZipFile

import pandas as pd
from openpyxl.utils import get_column_letter
from openpyxl.utils.datetime import to_excel

REQUIRED = ('骑手绑定情况', '骑手详情表', '骑手信息表')
TEXT = {'骑手身份证', '收款人身份证号码', '骑手手机号', '收款人手机号码', '身份证', '手机号'}
NUMERIC = {'骑手ID', '收款人ID'}


@dataclass(frozen=True)
class ValueCell:
    value: object
    row: int
    column: int


class TableSheet:
    def __init__(self, name, header, rows, widths):
        self.title, self.header, self.values = name, header, rows
        self.max_row, self.max_column = len(rows) + 1, len(header)
        self.column_dimensions = {key: SimpleNamespace(width=value) for key, value in widths.items()}
        self.row_dimensions = {}
        self.merged_cells = SimpleNamespace(ranges=())

    def iter_rows(self, min_row=1, max_row=None, min_col=1, max_col=None, values_only=False):
        for row_number in range(min_row, min(max_row or self.max_row, self.max_row) + 1):
            row = self.header if row_number == 1 else self.values[row_number - 2]
            values = tuple(row[column - 1] if column <= len(row) else None
                           for column in range(min_col, (max_col or self.max_column) + 1))
            yield values if values_only else tuple(ValueCell(value, row_number, column)
                  for column, value in enumerate(values, min_col))


class TableBook:
    def __init__(self, tables):
        self.worksheets = [TableSheet(**table) for table in tables]

    def close(self):
        pass


def exported_value(value, column):
    """Match XlsxWriter output as read by openpyxl; exotic strings use disk fallback."""
    if value is None or pd.isna(value) or value == '':
        return None
    if column in TEXT:
        value = str(value)
    elif column in NUMERIC:
        from salary_bind_processor import _to_num_safe
        value = _to_num_safe(value)
    if isinstance(value, str):
        if re.search(r'[\x00-\x08\x0b-\x1f]|_x[0-9A-Fa-f]{4}_', value):
            raise ValueError('Use workbook decoding for escaped strings')
        return value[:32767]
    if isinstance(value, (datetime, date, timedelta)):
        value = to_excel(value) if not isinstance(value, timedelta) else value.total_seconds() / 86400
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        if not math.isfinite(value):
            raise ValueError('Nonfinite exported number')
        text = '%.16G' % value
        return float(text) if any(char in text for char in '.Ee') else int(text)
    raise ValueError('Unsupported exported value type')


def capture_binding_tables(file, sheets, layout, max_bytes=64 * 1024 * 1024):
    selected = [(index, name, frame) for index, (name, frame, _) in enumerate(sheets, 1)
                if name.endswith(REQUIRED)]
    estimated = sum(int(frame.memory_usage(index=True, deep=True).sum()) + len(frame) * (64 + len(frame.columns) * 8)
                    for _, _, frame in selected)
    if len(selected) != 3 or estimated > max_bytes:
        return {}
    tables = []
    try:
        with ZipFile(file) as archive:
            for index, name, frame in selected:
                widths = {}
                # Read only the small worksheet prefix, never parse exported cells again.
                with archive.open(f'xl/worksheets/sheet{index}.xml') as stream:
                    for event, element in ElementTree.iterparse(stream, events=('start',)):
                        if element.tag.endswith('}col'):
                            widths[get_column_letter(int(element.attrib['min']))] = float(element.attrib['width'])
                        elif element.tag.endswith('}sheetData'):
                            break
                header = tuple(str(value) for value in frame.columns)
                rows = [tuple(exported_value(value, header[index]) for index, value in enumerate(row))
                        for row in frame.itertuples(index=False, name=None)]
                tables.append({'name': name, 'header': header, 'rows': rows, 'widths': widths})
        path = Path(file)
        with path.open('rb') as stream:
            digest = hashlib.file_digest(stream, 'sha256').hexdigest()
        return {'tables': tables, 'sha256': digest, 'bytes': path.stat().st_size, '_retained_bytes': estimated}
    except (ValueError, TypeError, OSError):
        # Optimization is optional; the original verified workbook remains authoritative.
        return {}


def verified_book(exchange, path):
    if not exchange or not exchange.get('tables'):
        return None
    path = Path(path)
    if path.stat().st_size != exchange.get('bytes'):
        return None
    with path.open('rb') as stream:
        if hashlib.file_digest(stream, 'sha256').hexdigest() != exchange.get('sha256'):
            return None
    return TableBook(exchange['tables'])
