"""Monthly multi-city result aggregation, using only committed city outputs."""
import hashlib
import hashlib_compat
import json
import os
from pathlib import Path
import uuid

import xlsxwriter
from openpyxl import load_workbook

from fengshen_bill import BillCollectionError, atomic_json, column_width, display_width
from download_archive import archive_filename
from workbook_policy import compression

SUMMARY_CITY = '多城市汇总'

# 全部子表样式与各城市成品（salary_bind_processor xlsxwriter 版式）逐项一致：
# 表头 = 微软雅黑10号不加粗、居中、淡橙 FFF8CBAD、细边框；数据 = 微软雅黑10号居中；
# 骑手ID/收款人ID 列数字格式 '0'；列宽按内容自适应（见 fengshen_bill.column_width）。
HEADER_FORMAT = {'bg_color': '#F8CBAD', 'font_name': '微软雅黑', 'font_size': 10,
                 'align': 'center', 'valign': 'vcenter', 'border': 1}
DATA_FORMAT = {'font_name': '微软雅黑', 'font_size': 10, 'align': 'center', 'valign': 'vcenter'}
ID_FORMAT = {'font_name': '微软雅黑', 'font_size': 10, 'align': 'center', 'valign': 'vcenter', 'num_format': '0'}
CITY_ID_FIELDS = ('骑手ID', '收款人ID')
CITY_FIELD = ('城市', '城市名称')
SHARED_PLATFORM_SHEET = '商翼绑定表'  # 平台全量导出，各城市成品一致，汇总仅取一份、不追加城市列
LAYOUT_FILE = 'binding_layout.json'


def build_binding_summaries(root, config, files, items, cancelled, report=None, progress=None):
    if 'payment_binding' not in config['datasets'] or len(config['cities']) < 2 or cancelled.is_set():
        return []
    report = report or (lambda _message: None)
    progress = progress or (lambda *_args: None)
    root = Path(root).resolve()
    wanted = [value for value in items if value['dataset'] == 'payment_binding']
    results = []
    for month in sorted({value['start'][:7] for value in wanted}):
        selected = [value for value in wanted if value['start'][:7] == month]
        successful = {value['city'] for value in selected if value['status'] == 'success'}
        sources = [value for value in files if value['dataset'] == 'payment_binding'
                   and value.get('artifact_role') != 'summary' and value['start'][:7] == month
                   and value['city'] in successful]
        if not sources:
            continue
        if len(sources) != len(successful) or {value['city'] for value in sources} != successful:
            raise BillCollectionError('多城市汇总的成功城市成品不完整')
        first, last = selected[0]['start'], selected[0]['end']
        if any(value['start'] != first or value['end'] != last for value in selected):
            raise BillCollectionError('同月各城市统计周期不一致，未生成汇总')
        by_city = {value['city']: value for value in sources}
        report(f'[汇总] 正在校验 {len(sources)} 个城市成品（{month}）')
        progress(0, len(successful), '', month)
        labels = [f'{int(month[5:])}月骑手绑定情况', f'{int(month[5:])}月未绑名单', f'{int(month[5:])}月黑户代领明细',
                  '风神绑定表', '商翼绑定表', '骑手详情表', '骑手信息表']
        # 阶段一：核验各城市成品、读取统计，并取得各子表表头与列宽。
        # 列宽优先读生成时落下的 layout sidecar，避免为了量列宽而再整本扫描一遍源文件。
        included, overview_rows, totals = [], [], [0] * 6
        first_scan, longest = None, {}
        input_proof = []
        for item in selected:
            checkpoint(cancelled)
            city = item['city']
            if city not in by_city:
                overview_rows.append([month, city, '未纳入', f'{first} 至 {last}', None, None, None, None,
                                      None, None, item.get('error') or '该城市未完成生成'])
                continue
            info = by_city[city]
            source = (root / info['relative_path']).resolve()
            if not source.is_relative_to(root) or not source.is_file():
                raise BillCollectionError('汇总来源文件归属无效')
            with source.open('rb') as stream:
                digest = hashlib.file_digest(stream, 'sha256').hexdigest()
            if digest != info['sha256'] or source.stat().st_size != info['bytes']:
                raise BillCollectionError('汇总来源文件完整性校验失败')
            stats = json.loads((root / '原始资料' / city / 'payment_binding' / month / 'binding_stats.json').read_text(encoding='utf-8'))
            if stats.get('source_range') != {'start': first, 'end': last}:
                raise BillCollectionError('汇总来源统计周期不一致')
            counts = [stats['cities'][city][key] for key in ('total_riders', 'total_orders', 'fengshen_bind_count',
                                                           'shangyi_bind_count', 'fully_bound_count', 'black_count')]
            if any(type(value) is not int or value < 0 for value in counts):
                raise BillCollectionError('汇总城市人数或单量无效')
            city_scan, layout_source = load_layout(root, city, month, source, labels, digest)
            if first_scan is None:
                first_scan = city_scan
            for label, (_, field_widths) in city_scan.items():
                merged = longest.setdefault(label, {})
                for field, width in field_widths.items():
                    if width > merged.get(field, 0):
                        merged[field] = width
            included.append((city, source))
            overview_rows.append([month, city, '已纳入', f'{first} 至 {last}', *counts, ''])
            totals = [a + b for a, b in zip(totals, counts)]
            input_proof.append({'city': city, 'file': source.name, 'sha256': digest, 'layout': layout_source})
        # 阶段二：先落列宽（xlsxwriter 必须在写行前确定），再单遍流式合并各城市记录。
        name = archive_filename(SUMMARY_CITY, 'payment_binding', first, last, suffix='.xlsx',
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
            header_format = book.add_format(HEADER_FORMAT)
            data_format = book.add_format(DATA_FORMAT)
            id_format = book.add_format(ID_FORMAT)
            overview_header = ['月份', '城市', '状态', '骑手明细周期', '有单骑手人数', '有效完成单',
                               '风神绑定人数', '发薪平台绑定人数', '完全绑定人数', '黑户代领人数', '说明']
            overview_total = [month, '合计', f'{len(sources)}/{len(selected)} 城市', f'{first} 至 {last}', *totals,
                              '各城市独立计数；未完成城市不计入']
            overview = book.add_worksheet('城市汇总')
            overview.freeze_panes(1, 3)
            _set_widths(overview, _content_lengths([overview_header] + overview_rows + [overview_total]), data_format)
            overview.write_row(0, 0, overview_header, header_format)
            for number, row in enumerate(overview_rows, 1):
                overview.write_row(number, 0, row, data_format)
            overview.write_row(len(overview_rows) + 1, 0, overview_total, header_format)
            notes = book.add_worksheet('汇总说明')
            notes.freeze_panes(1, 0)
            notes_rows = [
                ['汇总范围', '仅合并本任务已成功生成的城市；未完成城市见城市汇总，不计入明细及合计。'],
                ['月份规则', '跨月按月分别生成汇总；收薪账户按对应整月，骑手明细按所选周期。'],
                ['计数规则', '同一骑手跨城市分别保留，合计为各城市人数之和，不跨城市去重。'],
                ['代领规则', '对应月份且启用；审核通过优先，其次审批中。同一优先级代领人冲突停止该城市生成。'],
                ['原始资料', '本文件汇总绑定结果、未绑名单、代领明细；原始资料仍保存在各城市成品及任务目录中。'],
                [SHARED_PLATFORM_SHEET, f'平台全量导出在各城市成品中一致，汇总仅保留一份（来源城市：{included[0][0]}），不追加城市列。'],
            ]
            notes_header = ['项目', '说明']
            _set_widths(notes, _content_lengths([notes_header] + notes_rows), data_format)
            notes.write_row(0, 0, notes_header, header_format)
            for number, row in enumerate(notes_rows, 1):
                notes.write_row(number, 0, row, data_format)
            sheets = [book.add_worksheet(label) for label in labels]
            for index, label in enumerate(labels):
                sheets[index].freeze_panes(1, 0)
                header, _ = first_scan[label]
                append_city = label != SHARED_PLATFORM_SHEET and '城市' not in header
                _set_widths(sheets[index], _summary_lengths(label, first_scan, longest, included), data_format,
                            id_format, header + (['城市'] if append_city else []))
            headers = [None] * len(labels)
            id_columns = [()] * len(labels)
            row_numbers = [1] * len(labels)
            shared_city = None
            for position, (city, source) in enumerate(included, 1):
                report(f'[汇总] 正在合并 {city}（{position}/{len(included)}）')
                progress(position, len(included), city, month)
                original = load_workbook(source, read_only=True, data_only=True)
                main_rows, orders = 0, 0
                try:
                    for index, label in enumerate(labels):
                        shared = label == SHARED_PLATFORM_SHEET
                        if shared and shared_city is not None:
                            continue
                        iterator = original[label].iter_rows(values_only=True)
                        raw_header = list(next(iterator))
                        add_city = not shared and '城市' not in raw_header
                        header = raw_header + (['城市'] if add_city else [])
                        if len(set(header)) != len(header) or any(not value for value in header):
                            raise BillCollectionError('汇总来源表头为空或重复')
                        if headers[index] is None:
                            headers[index] = header
                            id_columns[index] = tuple(number for number, value in enumerate(header)
                                                      if value in CITY_ID_FIELDS)
                            sheets[index].write_row(0, 0, header, header_format)
                        elif set(headers[index]) != set(header):
                            raise BillCollectionError('各城市成品表头不一致，未生成汇总')
                        city_column = next((n for n, value in enumerate(raw_header) if value in CITY_FIELD), None)
                        if city_column is None and not add_city and not shared:
                            raise BillCollectionError('汇总成品缺少城市字段')
                        source_columns = {value: number for number, value in enumerate(raw_header)}
                        for row in iterator:
                            if not any(value is not None for value in row):
                                continue
                            checkpoint(cancelled)
                            if city_column is not None and str(row[city_column]).removesuffix('市') != city:
                                raise BillCollectionError('汇总成品包含其他城市记录')
                            if add_city:
                                values = [row[source_columns[value]] for value in headers[index][:-1]] + [city]
                            else:
                                values = [row[source_columns[value]] for value in headers[index]]
                            _write_data_row(sheets[index], row_numbers[index], values, data_format,
                                            id_format, id_columns[index])
                            row_numbers[index] += 1
                            if index == 0:
                                main_rows += 1
                                orders += int(row[source_columns['单量汇总']])
                        if shared:
                            shared_city = city
                finally:
                    original.close()
                if (main_rows, orders) != tuple(_overview_counts(overview_rows, city)[:2]):
                    raise BillCollectionError('汇总明细人数或单量与城市统计不一致')
            with compression(6):
                book.close()
            closed = True
            checkpoint(cancelled)
            os.replace(temporary, target)
            with target.open('rb') as stream:
                digest = hashlib.file_digest(stream, 'sha256').hexdigest()
            entry = {'city': SUMMARY_CITY, 'dataset': 'payment_binding', 'artifact_role': 'summary',
                     'start': first, 'end': last, 'name': name, 'relative_path': name,
                     'bytes': target.stat().st_size, 'sha256': digest}
            atomic_json(root / ('binding_summary_' + month + '.json'), {'file': entry, 'sources': input_proof,
                        'included_cities': sorted(successful), 'excluded_cities': sorted(set(config['cities']) - successful),
                        'totals': totals, 'payroll_executed': False,
                        'shared_sheet_source': {'sheet': SHARED_PLATFORM_SHEET, 'city': shared_city}})
            results.append(entry)
        finally:
            if not closed:
                try:
                    book.close()
                except Exception:
                    pass
            temporary.unlink(missing_ok=True)
    return results


def load_layout(root, city, month, source, labels, digest):
    """读取生成时落下的表头/列宽 sidecar；缺失、过期或不完整时回退整本扫描。"""
    try:
        payload = json.loads((root / '原始资料' / city / 'payment_binding' / month
                              / LAYOUT_FILE).read_text(encoding='utf-8'))
        if not isinstance(payload, dict) or payload.get('sha256') != digest:
            raise ValueError('layout 与成品不一致')
        sheets = payload['sheets']
        layout = {}
        for label in labels:
            entry = sheets[label]
            header = entry['header']
            widths = entry['widths']
            if not isinstance(header, list) or not header or not all(isinstance(value, str) and value for value in header):
                raise ValueError('layout 表头无效')
            if len(set(header)) != len(header):
                raise ValueError('layout 表头重复')
            if not isinstance(widths, list) or len(widths) != len(header):
                raise ValueError('layout 列宽无效')
            merged = {}
            for value, width in zip(header, widths):
                if isinstance(width, bool) or not isinstance(width, (int, float)) or width < 0:
                    raise ValueError('layout 列宽无效')
                merged[value] = int(width)
            layout[label] = (header, merged)
        return layout, 'sidecar'
    except (OSError, ValueError, KeyError, TypeError):
        return scan_widths(source, labels), 'scan'


def _overview_counts(overview_rows, city):
    for row in overview_rows:
        if row[1] == city and row[2] == '已纳入':
            return row[4:10]
    raise BillCollectionError('汇总城市统计缺失：' + city)


def _summary_lengths(label, first_scan, longest, included):
    header, _ = first_scan[label]
    lengths = [longest[label].get(value, 0) for value in header]
    if label != SHARED_PLATFORM_SHEET and '城市' not in header:
        lengths.append(max((display_width(city) for city, _ in included), default=0))
    return lengths


def _content_lengths(rows):
    lengths = []
    for row in rows:
        for number, value in enumerate(row):
            if number == len(lengths):
                lengths.append(0)
            width = display_width(value)
            if width > lengths[number]:
                lengths[number] = width
    return lengths


def _set_widths(sheet, lengths, data_format, id_format=None, header=()):
    id_columns = frozenset(number for number, value in enumerate(header) if value in CITY_ID_FIELDS)
    for number, length in enumerate(lengths):
        style = id_format if id_format is not None and number in id_columns else data_format
        sheet.set_column(number, number, column_width(length), style)


def _write_data_row(sheet, row_number, values, data_format, id_format, id_columns):
    start = 0
    for column in id_columns:
        if column > start:
            sheet.write_row(row_number, start, values[start:column], data_format)
        sheet.write(row_number, column, values[column], id_format)
        start = column + 1
    if start < len(values):
        sheet.write_row(row_number, start, values[start:], data_format)


def scan_widths(path, labels):
    """Per-sheet header and max display width per column of one city workbook."""
    book = load_workbook(path, read_only=True, data_only=True)
    try:
        scanned = {}
        for label in labels:
            if label not in book.sheetnames:
                raise BillCollectionError('城市成品缺少子表：' + label)
            rows = book[label].iter_rows(values_only=True)
            header = list(next(rows))
            widths = {value: display_width(value) for value in header}
            for row in rows:
                for name, value in zip(header, row):
                    if value is not None:
                        width = display_width(value)
                        if width > widths[name]:
                            widths[name] = width
            scanned[label] = (header, widths)
        return scanned
    finally:
        book.close()


def checkpoint(cancelled):
    if cancelled.is_set():
        raise BillCollectionError('多城市汇总已取消，城市成品已保留')
