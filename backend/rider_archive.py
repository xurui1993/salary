"""蓝橙骑手档案的成品契约：14 列投影与「项目」升序。

平台原表仍保留在原始资料目录；交付副本只保留约定列并按项目排序。全量成品
保留全部项目与城市，异常骑手跟进子表再按城市/项目筛选。
"""
from __future__ import annotations

import locale
import uuid
from pathlib import Path

from openpyxl import Workbook, load_workbook
from openpyxl.cell import WriteOnlyCell
from openpyxl.styles import Alignment, Font
from openpyxl.utils import get_column_letter
from excel_styles import style_applier, prepared_write_only_rows
from generation_performance import measured
from workbook_policy import compression

from fengshen_bill import BillCollectionError, column_width, display_width

COLUMNS = (
    '项目', '城市', '站点', '骑手ID', '姓名', '身份证号', '合作类型', '当前生效兼职价格',
    '合作日期', '推荐人身份证号', '三方公司/推荐人', '招聘来源', '状态', '是否寒暑假工',
)
PROJECTS = ('U+B', '饿了么', '淘鲜达')

CENTER = Alignment(horizontal='center', vertical='center')
DATA_FONT = Font(name='微软雅黑', size=10)
HEADER_FONT = Font(name='微软雅黑', size=10, bold=True)

_COLLATE = None


def _collation():
    global _COLLATE
    if _COLLATE is None:
        try:
            locale.setlocale(locale.LC_COLLATE, '')
        except locale.Error:
            pass
        _COLLATE = locale.strxfrm
    return _COLLATE


def normalize_city(value):
    return str(value or '').strip().removesuffix('市')


def project_text(value):
    return '' if value is None else str(value).strip()


def project_sort_key(value):
    """项目升序（中文按系统拼音排序），空项目排在最后。"""
    text = project_text(value)
    if not text:
        return (1, '', '')
    return (0, _collation()(text), text)


def _checkpoint(cancelled):
    if cancelled is not None and cancelled.is_set():
        raise BillCollectionError('蓝橙骑手档案处理已取消')


def _positions(header):
    positions = {}
    for index, value in enumerate(header):
        text = str(value).strip() if value is not None else ''
        if text in COLUMNS and text not in positions:
            positions[text] = index
    missing = [name for name in COLUMNS if name not in positions]
    if missing:
        raise BillCollectionError('蓝橙骑手档案缺少字段：' + '、'.join(missing))
    return [positions[name] for name in COLUMNS]


class _PackedRow:
    __slots__ = ('values', 'metadata')

    def __init__(self, values, metadata):
        self.values, self.metadata = values, metadata


def read_archive(sheet, cancelled=None, city=None, projects=None, *, compact=False):
    """读取并筛选骑手档案，返回 (按项目排序的源单元格行, 各列显示宽度)。"""
    rows = sheet.iter_rows()
    header = next(rows, None)
    if header is None:
        raise BillCollectionError('蓝橙骑手档案缺少表头')
    order = _positions([cell.value for cell in header])
    widths = [display_width(name) for name in COLUMNS]
    kept = []
    metadata_cache = {}
    for row in rows:
        _checkpoint(cancelled)
        selected = [row[index] if index < len(row) else None for index in order]
        values = [cell.value if cell is not None else None for cell in selected]
        if not any(value is not None for value in values):
            continue
        if city is not None and normalize_city(values[1]) != city:
            continue
        if projects is not None and project_text(values[0]) not in projects:
            continue
        if compact:
            metadata = tuple((cell.data_type, cell.number_format) if cell is not None else (None, None)
                             for cell in selected)
            metadata = metadata_cache.setdefault(metadata, metadata)
            kept.append(_PackedRow(tuple(values), metadata))
        else:
            kept.append(selected)
        for index, value in enumerate(values):
            width = display_width(value)
            if width > widths[index]:
                widths[index] = width
    kept.sort(key=lambda row: project_sort_key(row.values[0] if compact else row[0].value if row[0] is not None else None))
    return kept, widths


def write_sheet(sheet, rows, widths):
    """把 14 列数据写入普通工作表，表头加粗、全表居中、冻结首行。"""
    if sheet.max_row > 0:
        sheet.delete_rows(1, sheet.max_row)
    for column, name in enumerate(COLUMNS, 1):
        cell = sheet.cell(row=1, column=column, value=name)
        cell.font = HEADER_FONT
        cell.alignment = CENTER
        dimension = sheet.column_dimensions[get_column_letter(column)]
        dimension.width = column_width(widths[column - 1])
        dimension.alignment = CENTER
    for row_index, source_row in enumerate(rows, 2):
        for column, source in enumerate(source_row, 1):
            value = source.value if source is not None else None
            cell = sheet.cell(row=row_index, column=column, value=value)
            if source is not None and value is not None:
                cell.data_type = source.data_type
                if source.number_format is not None:
                    cell.number_format = source.number_format
            cell.font = DATA_FONT
            cell.alignment = CENTER
    sheet.freeze_panes = 'A2'


def _header_row(sheet):
    cells = []
    for name in COLUMNS:
        cell = WriteOnlyCell(sheet, value=name)
        cell.font = HEADER_FONT
        cell.alignment = CENTER
        cells.append(cell)
    return cells


def _data_row(sheet, source_row, apply_style=None):
    cells = []
    source_values = (zip(source_row.values, source_row.metadata) if isinstance(source_row, _PackedRow)
                     else ((source.value if source is not None else None,
                            (source.data_type, source.number_format) if source is not None else (None, None))
                           for source in source_row))
    for value, (data_type, number_format) in source_values:
        cell = WriteOnlyCell(sheet, value=value)
        if data_type is not None and value is not None:
            cell.data_type = data_type
            if number_format is not None:
                cell.number_format = number_format
        if apply_style is not None:
            apply_style(cell)
        else:
            cell.font = DATA_FONT
            cell.alignment = CENTER
        cells.append(cell)
    return cells


def _copy_visible_sheet(source, target):
    for row in source.iter_rows():
        cells = []
        for cell in row:
            copied = WriteOnlyCell(target, value=cell.value)
            if cell.value is not None:
                copied.data_type = cell.data_type
                if cell.number_format is not None:
                    copied.number_format = cell.number_format
            cells.append(copied)
        target.append(cells)


@measured('archive_projection')
def format_full_workbook(path, output_dir, cancelled=None):
    """生成 14 列、按项目升序的全量交付副本；隐藏选项表不纳入。

    返回 (临时副本路径, {'rows': 行数, 'columns': 列名列表})，原文件不变。
    """
    path, output_dir = Path(path), Path(output_dir)
    source = load_workbook(path, read_only=True, data_only=False)
    target = Workbook(write_only=True)
    try:
        business = next((ws for ws in source.worksheets if ws.title.endswith('骑手档案')), None)
        if business is None:
            raise BillCollectionError('蓝橙全量成品缺少骑手档案工作表')
        rows, widths = read_archive(business, cancelled, compact=True)
        visible = [ws for ws in source.worksheets if ws.sheet_state == 'visible']
        if not visible:
            raise BillCollectionError('蓝橙全量成品没有可交付工作表')
        for sheet in visible:
            output = target.create_sheet(sheet.title[:31])
            prepared_write_only_rows(output)
            if sheet is business:
                # 写只模式在首行写入时固化表头，列宽与冻结必须在 append 前设置。
                for column, width in enumerate(widths, 1):
                    output.column_dimensions[get_column_letter(column)].width = column_width(width)
                output.freeze_panes = 'A2'
                output.append(_header_row(output))
                apply_style = style_applier(output, font=DATA_FONT, alignment=CENTER)
                for row in rows:
                    _checkpoint(cancelled)
                    output.append(_data_row(output, row, apply_style))
            else:
                _copy_visible_sheet(sheet, output)
        if not target.worksheets:
            raise BillCollectionError('蓝橙全量成品没有可交付工作表')
        output = output_dir / ('.骑手档案_' + uuid.uuid4().hex + '.xlsx')
        try:
            with compression(6):
                target.save(output)
        except Exception:
            output.unlink(missing_ok=True)
            raise
        return output, {'rows': len(rows), 'columns': list(COLUMNS)}
    finally:
        source.close()
        target.close()
