"""蓝橙价格档案的交付筛选：按任务月份（可选城市）裁剪副本。

平台原表保留在原始资料目录，交付副本只保留「日期」落在所选月份的记录。
单月下载直接写入跟进子表；多月下载保留全部覆盖月份，跟进时再按月/城市筛选。
"""
from __future__ import annotations

import datetime as dt
import re
import uuid
from pathlib import Path

from openpyxl import Workbook, load_workbook
from openpyxl.cell import WriteOnlyCell
from openpyxl.utils import get_column_letter

from fengshen_bill import BillCollectionError, column_width, display_width
from rider_archive import CENTER, DATA_FONT, HEADER_FONT, normalize_city

DATE_COLUMN = '日期'
CITY_COLUMNS = ('城市名称', '城市')
SHEET_SUFFIX = '价格档案'
_MONTH = re.compile(r'(\d{4})\s*[-/.年]\s*(\d{1,2})')
_MONTH_KEY = re.compile(r'\d{4}-\d{2}')
_UNSET = object()


def _checkpoint(cancelled):
    if cancelled is not None and cancelled.is_set():
        raise BillCollectionError('蓝橙价格档案筛选已取消')


def _month_set(months):
    result = {str(value) for value in months if value}
    if not result:
        raise BillCollectionError('蓝橙价格档案缺少筛选月份')
    invalid = sorted(value for value in result if not _MONTH_KEY.fullmatch(value))
    if invalid:
        raise BillCollectionError('蓝橙价格档案筛选月份无效：' + '、'.join(invalid))
    return result


def month_of(value):
    """把日期单元格解析为 YYYY-MM；无法识别返回 None。"""
    if isinstance(value, dt.datetime):
        return f'{value.year:04d}-{value.month:02d}'
    if isinstance(value, dt.date):
        return f'{value.year:04d}-{value.month:02d}'
    match = _MONTH.match(str(value or '').strip())
    if match is None:
        return None
    year, month = int(match.group(1)), int(match.group(2))
    return f'{year:04d}-{month:02d}' if 1 <= month <= 12 else None


def business_sheet(book):
    for sheet in book.worksheets:
        if sheet.sheet_state == 'visible' and sheet.title.endswith(SHEET_SUFFIX):
            return sheet
    return None


def _positions(header, city):
    texts = [str(value).strip() if value is not None else '' for value in header]

    def find(labels):
        for index, text in enumerate(texts):
            if text in labels:
                return index
        return None

    date_index = find((DATE_COLUMN,))
    city_index = find(('城市名称',))
    if city_index is None:
        city_index = find(('城市',))
    missing = []
    if date_index is None:
        missing.append(DATE_COLUMN)
    if city is not None and city_index is None:
        missing.append(CITY_COLUMNS[0])
    if missing:
        raise BillCollectionError('蓝橙价格档案缺少字段：' + '、'.join(missing))
    return date_index, city_index


def _stats(months):
    return {'before': 0, 'after': 0, 'invalid': 0, 'month': 0, 'city': 0,
            'months': sorted(months)}


def _filtered(source, months, city, cancelled, stats):
    """先返回表头行，再按月份/城市筛选数据行。"""
    rows = source.iter_rows()
    header = next(rows, None)
    if header is None:
        raise BillCollectionError('蓝橙价格档案缺少表头')
    date_index, city_index = _positions([cell.value for cell in header], city)
    yield header
    for row in rows:
        _checkpoint(cancelled)
        values = [cell.value for cell in row]
        if not any(value is not None for value in values):
            continue
        stats['before'] += 1
        value = values[date_index] if date_index < len(values) else None
        month = month_of(value)
        if month not in months:
            if month is None:
                stats['invalid'] += 1
            else:
                stats['month'] += 1
            continue
        if city is not None:
            value = values[city_index] if city_index < len(values) else None
            if normalize_city(value) != city:
                stats['city'] += 1
                continue
        stats['after'] += 1
        yield row


def _write_cell(target, source, value=_UNSET):
    if value is _UNSET:
        value = source.value if source is not None else None
    cell = WriteOnlyCell(target, value=value)
    if source is not None and value is not None:
        cell.data_type = source.data_type
        if source.number_format is not None:
            cell.number_format = source.number_format
    return cell


def _copy_visible(source, target, note=None):
    for row in source.iter_rows():
        cells = []
        for index, cell in enumerate(row):
            value = cell.value
            if note is not None and index == 1 and isinstance(value, str) and '不按日期筛选' in value:
                value = note
            cells.append(_write_cell(target, cell, value))
        target.append(cells)


def filter_workbook(path, output_dir, months, city=None, cancelled=None):
    """生成按月份/城市筛选的临时副本，返回 (副本路径, 统计)，原文件不变。"""
    months = _month_set(months)
    city = normalize_city(city) if city is not None else None
    path, output_dir = Path(path), Path(output_dir)
    source = load_workbook(path, read_only=True, data_only=False)
    target = Workbook(write_only=True)
    stats = _stats(months)
    try:
        sheet = business_sheet(source)
        if sheet is None:
            raise BillCollectionError('蓝橙价格档案缺少「价格档案」工作表')
        visible = [ws for ws in source.worksheets if ws.sheet_state == 'visible']
        if not visible:
            raise BillCollectionError('蓝橙价格档案没有可交付工作表')
        # 业务表先写，说明表按最终统计更新“不按日期筛选”的描述。
        for current in [sheet] + [ws for ws in visible if ws is not sheet]:
            output = target.create_sheet(current.title[:31])
            if current is sheet:
                rows = _filtered(current, months, city, cancelled, stats)
                output.append([_write_cell(output, cell) for cell in next(rows)])
                for row in rows:
                    output.append([_write_cell(output, cell) for cell in row])
            else:
                note = None
                if current.title.endswith('下载说明'):
                    note = ('账号全部可访问数据；全部状态；按月份筛选 '
                            + '、'.join(sorted(months))
                            + f'（{stats["before"]} → {stats["after"]} 行；平台导出原件保留于后台）')
                _copy_visible(current, output, note)
        result = output_dir / ('.价格档案_' + uuid.uuid4().hex + '.xlsx')
        try:
            target.save(result)
        except Exception:
            result.unlink(missing_ok=True)
            raise
        return result, stats
    finally:
        source.close()
        target.close()


def write_filtered_sheet(destination, source, months, city, cancelled=None):
    """把筛选后的价格档案写入目标工作表，表头加粗、全表居中、冻结首行。"""
    months = _month_set(months)
    city = normalize_city(city) if city is not None else None
    stats = _stats(months)
    rows = _filtered(source, months, city, cancelled, stats)
    if destination.max_row > 0:
        destination.delete_rows(1, destination.max_row)
    header = next(rows)
    widths = [display_width(cell.value) for cell in header]
    for column, source_cell in enumerate(header, 1):
        cell = destination.cell(row=1, column=column, value=source_cell.value)
        cell.font = HEADER_FONT
        cell.alignment = CENTER
        widths[column - 1] = max(widths[column - 1], display_width(source_cell.value))
    row_index = 1
    for row in rows:
        row_index += 1
        for column, source_cell in enumerate(row, 1):
            value = source_cell.value
            cell = destination.cell(row=row_index, column=column, value=value)
            if value is not None:
                cell.data_type = source_cell.data_type
                if source_cell.number_format is not None:
                    cell.number_format = source_cell.number_format
            cell.font = DATA_FONT
            cell.alignment = CENTER
            widths[column - 1] = max(widths[column - 1], display_width(value))
    for column, width in enumerate(widths, 1):
        dimension = destination.column_dimensions[get_column_letter(column)]
        dimension.width = column_width(width)
        dimension.alignment = CENTER
    destination.freeze_panes = 'A2'
    return stats
