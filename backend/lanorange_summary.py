"""Stream a separate summary workbook; never modify city originals."""
from pathlib import Path
from openpyxl import Workbook, load_workbook
from openpyxl.cell import WriteOnlyCell
from fengshen_bill import BillCollectionError
from lanorange_catalog import DATASETS


def build_summary(root, sources, results, cancelled):
    output = Path(root) / '蓝橙跨城市汇总.xlsx'
    book = Workbook(write_only=True)
    sheets, headers, counts = {}, {}, {}
    note = book.create_sheet('汇总说明')
    note.append(['说明', '仅汇总成功下载的城市原始表；失败项见下方，不代表缺失城市已完成'])
    note.append(['城市口径', '批量离职平台原始批次可能含跨城市骑手，原表保留；本汇总按每行城市归属筛选，隐藏选项表不纳入'])
    note.append(['城市', '资料', '状态', '说明'])
    for item in results:
        if item['dataset'] in DATASETS:
            note.append([item['city'], DATASETS[item['dataset']][0], item['status'], item.get('error', '')])
    try:
        for item, path in sources:
            source = load_workbook(path, read_only=True, data_only=False)
            try:
                for sheet in source:
                    if sheet.sheet_state != 'visible': continue
                    rows = sheet.iter_rows()
                    header = tuple(cell.value for cell in next(rows, []))
                    city_columns = [i for i,value in enumerate(header) if value in ('城市','城市名称')]
                    key = (item['dataset'], sheet.title)
                    if key not in sheets:
                        title = DATASETS[item['dataset']][0]
                        if any(k[0] == key[0] for k in sheets): title += '_' + str(len(sheets) + 1)
                        sheets[key] = book.create_sheet(title[:31])
                        sheets[key].append(['来源城市', *header]); headers[key] = header; counts[key] = 0
                    if header != headers[key]:
                        raise BillCollectionError('蓝橙城市原始表字段不一致，未生成跨城市汇总')
                    for row in rows:
                        if cancelled.is_set(): raise BillCollectionError('蓝橙跨城市汇总已取消')
                        if not any(cell.value is not None for cell in row): continue
                        if not city_columns: raise BillCollectionError('蓝橙原始业务表缺少城市字段，未生成汇总')
                        if any(str(row[i].value or '').removesuffix('市') != item['city'].removesuffix('市') for i in city_columns): continue
                        if counts[key] >= 1_048_575:
                            raise BillCollectionError('蓝橙汇总超过 Excel 单表行数上限，城市原表已保留')
                        target = sheets[key]; cells = [WriteOnlyCell(target, item['city'])]
                        cells[0].data_type = 's'
                        for cell in row:
                            value = WriteOnlyCell(target, cell.value)
                            value.data_type = cell.data_type
                            value.number_format = cell.number_format
                            cells.append(value)
                        target.append(cells); counts[key] += 1
            finally: source.close()
        note.append([]); note.append(['资料', '数据表', '合并行数'])
        for (kind, title), count in counts.items(): note.append([DATASETS[kind][0], title, count])
        book.save(output)
        return output
    finally:
        book.close()
