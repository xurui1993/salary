"""Merge per-city invitation workbooks into one multi-city summary workbook."""
import json
import os
from pathlib import Path

from openpyxl import load_workbook

from fengshen_bill import BillCollectionError
from fengshen_merchant_exports import (HEADERS, INVITATION_HEADER_FILL, WIDTH_SAMPLE_ROWS,
                                       invitation_widths)
from tabular_export_workbook import TabularWorkbook


def merge_invitation_workbooks(sources, target, scope):
    """Stream all city workbooks into one workbook with the same 19 confirmed columns."""
    sources = [Path(source) for source in sources]
    if len(sources) < 2:
        raise BillCollectionError("邀请记录汇总至少需要两个城市文件")
    target = Path(target)
    temporary = target.with_name(target.name + '.part')
    book, sample, rows_total = None, [], 0

    def open_book(rows):
        writer = TabularWorkbook(temporary, HEADERS, '邀请记录汇总',
                                 json.dumps(scope, ensure_ascii=False), invitation_widths(rows),
                                 header_fill=INVITATION_HEADER_FILL)
        writer.__enter__()
        return writer

    def emit(row):
        nonlocal book, sample
        if book is None:
            sample.append(row)
            if len(sample) >= WIDTH_SAMPLE_ROWS:
                book = open_book(sample)
                for pending in sample:
                    book.append(pending)
                sample = []
        else:
            book.append(row)

    try:
        for source in sources:
            if source.is_symlink() or not source.is_file():
                raise BillCollectionError("邀请记录城市文件不可用，未生成汇总")
            workbook = load_workbook(source, read_only=True, data_only=True)
            try:
                sheet = workbook.active
                sheet.reset_dimensions()
                rows = sheet.iter_rows(values_only=True)
                header = next(rows, None)
                if header is None or [str(value or '').strip() for value in header] != HEADERS:
                    raise BillCollectionError("邀请记录城市文件表头不一致，未生成汇总")
                for row in rows:
                    values = ['' if value is None else str(value) for value in row]
                    if len(values) > len(HEADERS):
                        raise BillCollectionError("邀请记录城市文件列数变化，未生成汇总")
                    values += [''] * (len(HEADERS) - len(values))
                    if not any(values):
                        continue
                    emit(values)
                    rows_total += 1
            finally:
                workbook.close()
        if book is None:
            book = open_book(sample)
            for pending in sample:
                book.append(pending)
            sample = []
        book.finish([{'business_id': scope.get('商家编号', ''), 'city': '多城市', 'station': '全部城市',
                      'period': '全部邀请记录（不按日期筛选）', 'version': f'{len(sources)}个城市',
                      'status': '邀请记录汇总', 'row_count': rows_total, 'result': '已生成', 'message': ''}])
    finally:
        if book is not None:
            book.__exit__(None, None, None)
    os.replace(temporary, target)
    return {'rows': rows_total, 'sources': len(sources)}