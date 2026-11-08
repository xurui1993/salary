"""多城市风神骑手月度UB账单汇总：每个城市一个子表，沿用城市成品版式。"""

import datetime as dt
import hashlib
import math
import os
import uuid
from pathlib import Path

import xlsxwriter
from openpyxl import load_workbook
from openpyxl.utils import get_column_letter

from download_archive import archive_filename
from fengshen_bill import BillCollectionError
from parttime_source import label, _locate_ub_sheet

SUMMARY_CITY = '多城市汇总'
UB_HEADER_STYLE = {'font_name': '微软雅黑', 'font_size': 10, 'font_color': '#000000',
                   'bg_color': '#FCE4D3', 'align': 'center', 'valign': 'vcenter'}
UB_DATA_STYLE = {'font_name': '微软雅黑', 'font_size': 10, 'font_color': '#000000',
                 'align': 'center', 'valign': 'vcenter'}
UB_ROW_HEIGHT = 16.5
_INVALID_SHEET_CHARS = set('[]:*?/\\')


def _source_path(root, info):
    path = (root / info['relative_path']).resolve()
    if not path.is_relative_to(root) or not path.is_file():
        raise BillCollectionError('汇总来源文件归属无效')
    if info.get('sha256') is not None:
        with path.open('rb') as stream:
            digest = hashlib.file_digest(stream, 'sha256').hexdigest()
        if (digest != info['sha256']
                or (info.get('bytes') is not None and path.stat().st_size != info['bytes'])):
            raise BillCollectionError('汇总来源文件完整性校验失败')
    return path


def _sheet_title(city):
    if (not isinstance(city, str) or not city or len(city) > 31
            or any(char in _INVALID_SHEET_CHARS for char in city)):
        raise BillCollectionError('汇总城市名称无法作为工作表名')
    return city


def _source_layout(path):
    workbook = load_workbook(path, data_only=False)
    try:
        sheet, header_row = _locate_ub_sheet(workbook)
        headers = [cell.value.strip() if isinstance(cell.value, str) else cell.value
                   for cell in sheet[header_row]]
        while headers and headers[-1] is None:
            headers.pop()
        widths = {}
        for index in range(1, len(headers) + 1):
            dimension = sheet.column_dimensions.get(get_column_letter(index))
            if dimension is not None and dimension.width is not None:
                widths[index] = dimension.width
        height = sheet.sheet_format.defaultRowHeight or UB_ROW_HEIGHT
        return headers, [label(value) for value in headers], widths, height, header_row
    finally:
        workbook.close()


def _source_rows(path, header_row, columns, expected_labels):
    workbook = load_workbook(path, read_only=True, data_only=False)
    try:
        sheet, located = _locate_ub_sheet(workbook)
        if located != header_row:
            raise BillCollectionError('汇总来源表头位置不一致')
        header = next(sheet.iter_rows(min_row=header_row, max_row=header_row, max_col=columns), ())
        if [label(cell.value) for cell in header] != expected_labels:
            raise BillCollectionError('多城市骑手月度账单表头不一致，未生成汇总')
        if sheet.max_column is not None and sheet.max_column > columns:
            raise BillCollectionError('汇总来源存在无表头的数据列')
        for row in sheet.iter_rows(min_row=header_row + 1, max_col=columns):
            yield row
    finally:
        workbook.close()


def _date_number_format(number_format, value):
    if number_format and number_format != 'General':
        return number_format
    return 'yyyy-mm-dd hh:mm:ss' if hasattr(value, 'hour') else 'yyyy-mm-dd'


def build_rider_monthly_summaries(root, config, files, items, cancelled, report=None):
    if 'rider_monthly' not in config.get('datasets', ()) or len(config.get('cities', ())) < 2:
        return []
    report = report or (lambda _message: None)
    root = Path(root).resolve()
    wanted = [value for value in items if value.get('dataset') == 'rider_monthly']
    city_order = {city: index for index, city in enumerate(config['cities'])}
    results = []
    for month in sorted({value['start'][:7] for value in wanted}):
        if cancelled.is_set():
            return results
        selected = [value for value in wanted if value['start'][:7] == month]
        successful = {value['city'] for value in selected if value.get('status') == 'success'}
        by_city = {}
        for info in files:
            if (info.get('dataset') == 'rider_monthly' and info.get('artifact_role') != 'summary'
                    and info.get('start', '')[:7] == month and info.get('city') in successful):
                by_city.setdefault(info['city'], info)
        sources = sorted(by_city.values(),
                         key=lambda value: (city_order.get(value['city'], len(city_order)), value['city']))
        if not sources:
            continue
        if len(sources) != len(successful) or {value['city'] for value in sources} != successful:
            raise BillCollectionError('多城市骑手月度账单的成功城市成品不完整')
        if len(sources) < 2:
            continue
        first, last = selected[0]['start'], selected[0]['end']
        if any(value['start'] != first or value['end'] != last for value in selected):
            raise BillCollectionError('同月各城市骑手月度账单周期不一致，未生成汇总')
        source_paths = [(value['city'], _source_path(root, value)) for value in sources]
        headers, header_labels, widths, row_height, header_row = _source_layout(source_paths[0][1])
        if not headers:
            raise BillCollectionError('汇总来源缺少表头')
        name = archive_filename(SUMMARY_CITY, 'rider_monthly', first, last, suffix='.xlsx',
                                stamp=config.get('archive_created_at'))
        target = root / name
        if target.exists():
            raise BillCollectionError('汇总文件已存在，未覆盖')
        temporary = root / ('.汇总临时_' + uuid.uuid4().hex + '.xlsx')
        book = xlsxwriter.Workbook(str(temporary), {'constant_memory': True,
                                                    'strings_to_formulas': False,
                                                    'strings_to_urls': False})
        closed = False
        try:
            header_format = book.add_format(UB_HEADER_STYLE)
            base_format = book.add_format(UB_DATA_STYLE)
            number_formats = {}

            def number_format(value):
                key = '' if value in (None, '', 'General') else value
                if key not in number_formats:
                    style = dict(UB_DATA_STYLE)
                    if key:
                        style['num_format'] = key
                    number_formats[key] = book.add_format(style)
                return number_formats[key]

            for position, (city, path) in enumerate(source_paths, 1):
                if cancelled.is_set():
                    raise BillCollectionError('下载任务已取消，未生成汇总')
                report(f'[汇总] 正在合并 {city}（{position}/{len(source_paths)}）')
                sheet = book.add_worksheet(_sheet_title(city))
                for index, width in widths.items():
                    # xlsxwriter 按字体度量给列宽额外加了约 5/7 字符的内边距。
                    sheet.set_column(index - 1, index - 1, width - 5 / 7)
                sheet.set_default_row(row_height)
                sheet.freeze_panes(1, 0)
                for column, value in enumerate(headers):
                    if value is not None:
                        sheet.write_string(0, column, str(value), header_format)
                used_header_row = header_row
                for row_number, row in enumerate(
                        _source_rows(path, used_header_row, len(headers), header_labels), 1):
                    for column, cell in enumerate(row):
                        value = cell.value
                        if value is None:
                            continue
                        style = base_format
                        if isinstance(value, (dt.datetime, dt.date, dt.time, dt.timedelta)):
                            sheet.write_datetime(row_number, column, value,
                                                 number_format(_date_number_format(cell.number_format, value)))
                            continue
                        if isinstance(value, bool):
                            sheet.write_boolean(row_number, column, value, style)
                        elif isinstance(value, (int, float)):
                            if not math.isfinite(value):
                                sheet.write_string(row_number, column, str(value), style)
                            else:
                                sheet.write_number(row_number, column, value,
                                                   number_format(cell.number_format))
                        elif cell.data_type == 'f' and str(value).startswith('='):
                            sheet.write_formula(row_number, column, value, style)
                        else:
                            sheet.write_string(row_number, column, str(value), style)
            book.close()
            closed = True
            os.replace(temporary, target)
        except Exception:
            if not closed:
                book.close()
            temporary.unlink(missing_ok=True)
            raise
        results.append({'city': SUMMARY_CITY, 'dataset': 'rider_monthly', 'artifact_role': 'summary',
                        'start': first, 'end': last, 'name': target.name, 'relative_path': target.name,
                        'bytes': target.stat().st_size,
                        'sha256': hashlib.sha256(target.read_bytes()).hexdigest()})
        report(f'[汇总] 多城市骑手月度账单已生成：{target.name}')
    return results
