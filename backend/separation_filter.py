"""按「取分离」站点关键字过滤风神成品的行级工具。

识别依据（用户确认）：团队/站点名称包含「取分离」关键字。原始全量文件始终
保留在原始资料目录；成品为过滤副本，回执记录过滤方向与前后行数，可追溯。
"""
import csv
import uuid
from pathlib import Path

from openpyxl import Workbook, load_workbook
from openpyxl.cell import WriteOnlyCell

from fengshen_bill import BillCollectionError
from generation_performance import measured
from workbook_policy import compression

MARK = '取分离'
# 各资料成品中用于识别站点的列名；缺失即结构变化，直接停止。
COLUMNS = {
    'delivery_fee': '团队名称', 'penalty': '团队名称', 'receive_account': '团队名称',
    'rider_detail': '团队名称', 'rider_info': '部门', 'problem': '团队名称',
    'fraud': '站点名称', 'rider_monthly': '骑手所属站点名称',
}


def filter_direction(config):
    """None keeps all rows; bool preserves the legacy only/exclude directions.

    Explicit exclude_separation=False must survive request normalization: its
    absence belongs to historical requests with the original two-way filter.
    """
    if 'exclude_separation' in config:
        return False if config['exclude_separation'] else None
    return bool(config.get('include_separation'))


def kept(value, include):
    hit = MARK in str(value if value is not None else '')
    return hit if include else not hit


@measured('source_row_filter')
def filter_table(path, dataset, include, output_dir):
    """按站点列过滤成品；返回 (过滤副本路径, {'column','rows_before','rows_after'})。"""
    path, output_dir = Path(path), Path(output_dir)
    column = COLUMNS.get(dataset)
    if not column:
        raise BillCollectionError('资料类型不支持取分离过滤：' + str(dataset))
    suffix = path.suffix.lower()
    if suffix == '.csv':
        return _filter_csv(path, column, include, output_dir)
    if suffix == '.xlsx':
        return _filter_xlsx(path, column, include, output_dir)
    raise BillCollectionError('取分离过滤仅支持 CSV/XLSX 成品：' + path.name)


def _text_cell(sheet, value):
    cell = WriteOnlyCell(sheet, value=value)
    if isinstance(value, str):
        cell.data_type = 's'
    return cell


def _missing(path, column):
    return BillCollectionError('成品缺少站点列 ' + column + '，无法执行取分离过滤：' + path.name)


def _filter_csv(path, column, include, output_dir):
    # 大日账单不能一次性 list(reader)：只保留当前行，过滤规则与行序不变。
    output = output_dir / ('.取分离_' + uuid.uuid4().hex + path.suffix)
    before, after = 0, 0
    created = False
    try:
        with path.open(encoding='utf-8-sig', newline='') as stream:
            rows = csv.reader(stream)
            header = next(rows, None)
            if header is None:
                raise BillCollectionError('成品为空，无法执行取分离过滤：' + path.name)
            if column not in header:
                raise _missing(path, column)
            position = header.index(column)
            with output.open('x', encoding='utf-8-sig', newline='') as target:
                created = True
                writer = csv.writer(target)
                writer.writerow(header)
                for row in rows:
                    before += 1
                    if position < len(row) and kept(row[position], include):
                        writer.writerow(row)
                        after += 1
        return output, {'column': column, 'rows_before': before, 'rows_after': after}
    except Exception:
        if created:
            output.unlink(missing_ok=True)
        raise


def _legacy_filter_xlsx(path, column, include, output_dir):
    # 普通模式：平台导出文件 dimension 标签可能损坏（如骑手信息快照标为 A1），
    # 只读模式会按损坏维度漏读数据。
    book = load_workbook(path, data_only=True)
    try:
        if len(book.worksheets) != 1:
            raise BillCollectionError('成品子表数量变化，无法执行取分离过滤：' + path.name)
        rows = book.worksheets[0].iter_rows(values_only=True)
        preamble, header, position = [], None, None
        for offset, row in enumerate(rows):
            values = list(row)
            if column in [str(value) if value is not None else '' for value in values]:
                header, position = values, values.index(column)
                break
            preamble.append(values)
            if offset >= 9:
                raise _missing(path, column)
        if header is None:
            raise _missing(path, column)
        kept_rows, total = [], 0
        for row in rows:
            values = list(row) + [None] * max(0, len(header) - len(row))
            if not any(value is not None and str(value).strip() for value in values):
                continue
            total += 1
            if kept(values[position], include):
                kept_rows.append(values[:len(header)])
        output = output_dir / ('.取分离_' + uuid.uuid4().hex + '.xlsx')
        target = Workbook(write_only=True)
        sheet = target.create_sheet()
        for values in preamble:
            sheet.append([_text_cell(sheet, value) for value in values])
        sheet.append([_text_cell(sheet, value) for value in header])
        for values in kept_rows:
            sheet.append([_text_cell(sheet, value) for value in values])
        target.save(output)
        return output, {'column': column, 'rows_before': total, 'rows_after': len(kept_rows)}
    finally:
        book.close()


class _WideDataRow(Exception):
    pass


def _filter_xlsx(path, column, include, output_dir):
    # Reset stale dimensions rather than materializing every Cell in memory.
    # If later rows contain extra data columns, retain the old global-width path.
    try:
        return _stream_filter_xlsx(path, column, include, output_dir)
    except _WideDataRow:
        return _legacy_filter_xlsx(path, column, include, output_dir)


def _stream_filter_xlsx(path, column, include, output_dir):
    book = load_workbook(path, data_only=True, read_only=True)
    target = None
    output = output_dir / ('.取分离_' + uuid.uuid4().hex + '.xlsx')
    saved = False
    try:
        if len(book.worksheets) != 1:
            raise BillCollectionError('成品子表数量变化，无法执行取分离过滤：' + path.name)
        source = book.worksheets[0]
        source.reset_dimensions()
        rows = source.iter_rows(values_only=True)
        preamble, header, position = [], None, None
        for offset, row in enumerate(rows):
            values = list(row)
            if column in [str(value) if value is not None else '' for value in values]:
                header, position = values, values.index(column)
                break
            preamble.append(values)
            if offset >= 9:
                raise _missing(path, column)
        if header is None:
            raise _missing(path, column)
        target = Workbook(write_only=True)
        sheet = target.create_sheet()
        for values in preamble:
            sheet.append([_text_cell(sheet, value) for value in values])
        sheet.append([_text_cell(sheet, value) for value in header])
        before = after = 0
        for row in rows:
            if len(row) > len(header) and any(value is not None for value in row[len(header):]):
                raise _WideDataRow()
            values = list(row) + [None] * max(0, len(header) - len(row))
            if not any(value is not None and str(value).strip() for value in values):
                continue
            before += 1
            if kept(values[position], include):
                sheet.append([_text_cell(sheet, value) for value in values[:len(header)]])
                after += 1
        with compression(6):
            target.save(output)
        saved = True
        return output, {'column': column, 'rows_before': before, 'rows_after': after}
    finally:
        book.close()
        if target is not None and not saved:
            # Close write-only XML streams before discarding a failed/fallback file.
            try:
                target.save(output)
            except Exception:
                pass
            try:
                output.unlink(missing_ok=True)
            except OSError:
                pass
