"""运单数据成品工作簿：按参考样例输出（雅黑10号居中、表头 FCE6D5、冻结首行、
自适应列宽），数据行超过 100 万时按「运单明细N」分片；流式写出，不整表驻留内存。"""
import csv
from itertools import islice
import xml.etree.ElementTree as ET
from contextlib import contextmanager
from pathlib import Path

from fengshen_bill import BillCollectionError
from price_export_workbook import NS, REL, WorkbookStream, package_xml
from tabular_export_workbook import TabularWorkbook, value_cell

# 表头与列序以 2026-11-06 平台真实导出样例为准（52 列，A..AZ）。
WAYBILL_TITLES = (
    "商id", "商名称", "站点id", "站点名称", "商圈id", "商圈名称", "运单id", "订单号",
    "骑手id", "骑手名称", "平台商家id", "平台商家名称", "商家订单流水号", "运单类型",
    "运单状态", "配送标品", "订单来源", "订单距离(km)", "订单金额(元)", "订单重量(kg)",
    "用户下单时间", "用户支付时间", "运单创建时间", "团队接单时间", "骑手接单时间",
    "骑手到店时间", "实际出餐时间", "骑手取餐时间", "骑手送达时间", "运单完成时间",
    "用户期望时间", "骑手考核时间", "运单取消时间", "平台期望时间", "是否超平台期望时间",
    "超平台期望送达时长", "是否超用户T", "是否超骑手T", "配送时长", "天气等级", "天气",
    "欺诈是否成立", "违规取餐是否成立", "违规到店是否成立", "违规送达是否成立",
    "是否逆向单", "是否发生转单", "是否发生改派", "索赔是否成立", "索赔原因",
    "是否异常报备", "异常报备项",
)
SHEET_ROW_LIMIT = 1_000_001  # 表头 1 行 + 100 万数据行，低于 xlsx 单表上限
HEADER_FILL = 'FCE6D5'
MAX_COLUMN_WIDTH, MIN_COLUMN_WIDTH = 60, 9
# 列宽按每批前若干行估算，避免为计算列宽重复解析整批大文件。
WIDTH_SAMPLE_ROWS = 5000


def _display_width(value):
    if value is None:
        return 0
    text = value.isoformat(sep=' ') if hasattr(value, 'isoformat') else str(value)
    return sum(2 if ord(char) > 127 else 1 for char in text)


@contextmanager
def _openpyxl_rows(path):
    from openpyxl import load_workbook
    book = load_workbook(path, read_only=True, data_only=True)
    try:
        sheet = book[book.sheetnames[0]]
        # 平台流式导出会写入错误的 <dimension ref="A1"/>；只读模式必须重置，
        # 否则 openpyxl 会按声明维度把实际列截断成首列。
        sheet.reset_dimensions()
        rows = sheet.iter_rows(values_only=True)
        titles = next(rows, None)
        if not titles:
            raise BillCollectionError('运单原始文件缺少表头，不能生成成品')
        yield ['' if value is None else value for value in titles], rows
    finally:
        book.close()


@contextmanager
def waybill_rows(path):
    path = Path(path)
    if path.suffix.lower() == '.csv':
        with path.open(encoding='utf-8-sig', newline='') as stream:
            rows = csv.reader(stream)
            titles = next(rows, None)
            if not titles:
                raise BillCollectionError('运单原始文件缺少表头，不能生成成品')
            yield titles, rows
    elif path.suffix.lower() == '.xlsx':
        try:
            from python_calamine import CalamineWorkbook
        except ImportError:
            with _openpyxl_rows(path) as payload:
                yield payload
        else:
            # calamine 直接解析 OOXML，不依赖工作表 dimension 声明，读取平台大文件更快；
            # 本项目生成的模板工作簿可能不被 calamine 识别，此时回退 openpyxl。
            book = None
            try:
                book = CalamineWorkbook.from_path(str(path))
                if not book.sheet_names:
                    raise ValueError()
                rows = book.get_sheet_by_name(book.sheet_names[0]).iter_rows()
                titles = next(rows, None)
                if not titles:
                    raise BillCollectionError('运单原始文件缺少表头，不能生成成品')
            except BillCollectionError:
                if book is not None:
                    book.close()
                raise
            except Exception:
                if book is not None:
                    book.close()
                with _openpyxl_rows(path) as payload:
                    yield payload
            else:
                try:
                    yield ['' if value is None else value for value in titles], rows
                finally:
                    book.close()
    else:
        raise BillCollectionError('运单原始文件仅接受平台导出的 XLSX 或 CSV')


def title_indexes(titles):
    names = [str(value).strip() for value in titles]
    missing = [title for title in WAYBILL_TITLES if title not in names]
    duplicated = [title for title in WAYBILL_TITLES if names.count(title) > 1]
    if missing or duplicated:
        detail = '；'.join(part for part in (
            '缺少 ' + '、'.join(missing) if missing else '',
            '重复 ' + '、'.join(duplicated) if duplicated else '') if part)
        raise BillCollectionError('运单导出表头与已确认协议不一致，已停止生成成品（{}）'.format(detail))
    # 已确认的 52 列必须齐全；平台新增列不影响成品协议，按名称映射后忽略。
    return [names.index(title) for title in WAYBILL_TITLES]


def _column_widths(sources, checkpoint):
    widths = [_display_width(title) for title in WAYBILL_TITLES]
    remaining = WIDTH_SAMPLE_ROWS
    for source in sources:
        if remaining <= 0:
            break
        with waybill_rows(source) as (titles, rows):
            indexes = title_indexes(titles)
            for row in islice(rows, remaining):
                checkpoint()
                remaining -= 1
                for out, source_index in enumerate(indexes):
                    width = _display_width(row[source_index] if source_index < len(row) else None)
                    if width > widths[out]:
                        widths[out] = width
    return [min(MAX_COLUMN_WIDTH, max(MIN_COLUMN_WIDTH, int(width * 1.15) + 2)) for width in widths]


class WaybillWorkbook(TabularWorkbook):
    def __init__(self, path, widths):
        super().__init__(path, list(WAYBILL_TITLES), '运单明细', '运单数据', widths=widths,
                         header_fill=HEADER_FILL, row_height=None, default_row_height=16,
                         show_gridlines=True, auto_filter=False, row_limit=SHEET_ROW_LIMIT)
    def _open_main(self):
        header_style = self.header_style if self.header_style is not None else '0'
        row = '<row r="1">' + ''.join(
            value_cell(index, 1, title, header_style) for index, title in enumerate(self.titles)) + '</row>'
        widths = (list(self.widths) + [20] * len(self.titles))[:len(self.titles)]
        cols = '<cols>' + ''.join(
            f'<col min="{index + 1}" max="{index + 1}" width="{width}" customWidth="1"/>'
            for index, width in enumerate(widths)) + '</cols>'
        self._open(f'运单明细{len(self.names) + 1}', [row], cols, 1)
    def finish(self):
        self._close()
        workbook = ET.fromstring(self.template.read('xl/workbook.xml'))
        sheets = workbook.find('{%s}sheets' % NS)
        sheets.clear()
        relationships = ET.fromstring(self.template.read('xl/_rels/workbook.xml.rels'))
        sheet_type = REL + '/worksheet'
        for item in list(relationships):
            if item.attrib.get('Type') == sheet_type:
                relationships.remove(item)
        used = {item.attrib['Id'] for item in relationships}
        index = 1
        types = ET.fromstring(self.template.read('[Content_Types].xml'))
        for item in list(types):
            if item.attrib.get('PartName', '').startswith('/xl/worksheets/'):
                types.remove(item)
        for number, name in enumerate(self.names, 1):
            while f'rId{index}' in used:
                index += 1
            rid = f'rId{index}'
            used.add(rid)
            ET.SubElement(sheets, '{%s}sheet' % NS, {'name': name, 'sheetId': str(number), '{%s}id' % REL: rid})
            ET.SubElement(relationships, '{http://schemas.openxmlformats.org/package/2006/relationships}Relationship',
                          {'Id': rid, 'Type': sheet_type, 'Target': f'worksheets/sheet{number}.xml'})
            ET.SubElement(types, '{http://schemas.openxmlformats.org/package/2006/content-types}Override',
                          {'PartName': f'/xl/worksheets/sheet{number}.xml',
                           'ContentType': 'application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml'})
        self.output.writestr('xl/workbook.xml', ET.tostring(workbook, encoding='utf-8', xml_declaration=True))
        for name, root in (('xl/_rels/workbook.xml.rels', relationships), ('[Content_Types].xml', types)):
            self.output.writestr(name, package_xml(root))


def _checkpoint(cancelled):
    if cancelled is not None and cancelled():
        from download_jobs import DownloadCancelled
        raise DownloadCancelled('下载任务已取消')


def _write(sources, destination, cancelled):
    destination = Path(destination)
    checkpoint = lambda: _checkpoint(cancelled)  # noqa: E731
    widths = _column_widths(sources, checkpoint)
    total = 0
    with WaybillWorkbook(destination, widths) as book:
        for source in sources:
            with waybill_rows(source) as (titles, rows):
                indexes = title_indexes(titles)
                for row in rows:
                    checkpoint()
                    book.append([None if (value := row[index] if index < len(row) else None) == '' else value
                                 for index in indexes])
                    total += 1
        book.finish()
    return {'path': destination, 'rows': total, 'sheets': len(book.names)}


def write_waybill_workbook(source, destination, cancelled=None):
    return _write([source], destination, cancelled)


def merge_waybill_workbooks(sources, destination, cancelled=None):
    sources = [Path(source) for source in sources]
    if len(sources) < 2:
        raise BillCollectionError('运单数据汇总至少需要两个城市的成品')
    return _write(sources, destination, cancelled)
