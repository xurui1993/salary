"""异常骑手整理（生成表）组装器。

以本任务已发布的蓝橙成品为来源，组装多 sheet 整理工作簿，替代原
「异常骑手整理」手动上传模块（src/components/ResignationArchive.tsx）：

- 异常汇总：批量离职/离职报备/骑手离职/骑手请假 四类记录逐行映射为统一
  12 列，按身份证号从骑手档案回填合作日期/合作状态；备注为
  「【档案状态】类型：日期审批(类别)」（骑手请假为 日期类型(审批)）；
- 蓝橙骑手档案：全量 14 列投影原样交付，「合作日期」前移至「身份证号」前；
- 汇总：按骑手ID/姓名合并四类来源备注与合作状态，判定是否跑单未入职、
  是否解除跑单未入职；若任务同时下载了风神骑手数据明细/骑手信息成品，
  则补总单量、活跃是否异常与跨站团队归属（团队取单量最多站点，同量取先
  出现站点），未提供时总单量写 0、活跃异常写 否。

口径说明：原模块的 Excel 数值日期换算偏早一天，这里按 1900 体系正确换算。
"""
from __future__ import annotations

from datetime import date, datetime, timedelta
from pathlib import Path
import json
import re
import uuid

from openpyxl import Workbook, load_workbook
from generation_performance import profiled, measured, stage
from excel_styles import style_applier, prepared_write_only_rows
from openpyxl.cell import WriteOnlyCell
from openpyxl.styles import Alignment, Font
from openpyxl.utils import get_column_letter

from fengshen_bill import BillCollectionError, column_width, display_width

CONFIG_PATH = Path(__file__).resolve().parent.parent / 'data' / 'config.json'

_DATA_FONT = Font(name='微软雅黑', size=10)
_HEADER_FONT = Font(name='微软雅黑', size=10, bold=True)
_CENTER = Alignment(horizontal='center', vertical='center')

# 异常汇总固定列与列宽（对齐原模块导出）
ABNORMAL_FIELDS = ('城市名称', '站点', '风神骑手ID', '骑手姓名', '身份证', '合作日期',
                   '离职申请日', '合作状态', '离职类型', '审批状态', '类型', '备注')
ABNORMAL_WIDTHS = (12, 18, 15, 12, 22, 16, 16, 16, 16, 16, 12, 45)

# 汇总固定列与列宽
SUMMARY_FIELDS = ('城市', '团队名称', '骑手ID', '骑手姓名', '批量离职', '骑手离职',
                  '离职报备', '骑手请假', '合作状态', '是否跑单未入职',
                  '是否解除跑单未入职', '活跃是否异常', '总单量', '骑手身份证号')
SUMMARY_WIDTHS = (12, 18, 15, 12, 30, 30, 30, 30, 16, 16, 16, 16, 10, 22)

# 蓝橙骑手档案输出列：14 列投影中「合作日期」前移至「身份证号」前
ARCHIVE_FIELDS = ('项目', '城市', '站点', '骑手ID', '姓名', '合作日期', '身份证号',
                  '合作类型', '当前生效兼职价格', '推荐人身份证号', '三方公司/推荐人',
                  '招聘来源', '状态', '是否寒暑假工')

# 各来源表的精取列；fallback 为表头缺失时的固定列兜底（0 基，列序号对齐平台原表）
LIST_SPECS = {
    'batch_quit': {
        'fields': ('城市名称', '站点名称', '骑手ID', '骑手姓名', '身份证',
                   '解除合作申请日', '解除合作类别', '状态'),
        'fallback': {'解除合作申请日': 11, '解除合作类别': 13},
        'dates': ('解除合作申请日',),
        'name_field': '骑手姓名', 'id_card_field': '身份证', 'rider_field': '骑手ID',
    },
    'rider_quit': {
        'fields': ('城市名称', '站点', '风神骑手ID', '骑手姓名', '身份证',
                   '离职申请日', '离职类型', '状态'),
        'fallback': {'离职申请日': 16, '离职类型': 18},
        'dates': ('离职申请日',),
        'name_field': '骑手姓名', 'id_card_field': '身份证', 'rider_field': '风神骑手ID',
    },
    'rider_report': {
        'fields': ('城市名称', '站点名称', '风神骑手ID', '骑手姓名', '身份证',
                   '解除合作申请日', '解除合作类别', '状态'),
        'fallback': {'解除合作申请日': 13, '解除合作类别': 12},
        'dates': ('解除合作申请日',),
        'name_field': '骑手姓名', 'id_card_field': '身份证', 'rider_field': '风神骑手ID',
    },
    'rider_leave': {
        'fields': ('城市', '站点', '风神骑手ID', '姓名', '身份证号',
                   '请假结束时间', '类型', '审核状态'),
        'fallback': {'请假结束时间': 13},
        'dates': ('请假结束时间',),
        'name_field': '姓名', 'id_card_field': '身份证号', 'rider_field': '风神骑手ID',
    },
}

# 四类来源在异常汇总里的映射：目标列 -> 源列
ABNORMAL_MAPPINGS = {
    'batch_quit': {'城市名称': '城市名称', '站点': '站点名称', '风神骑手ID': '骑手ID',
                   '骑手姓名': '骑手姓名', '身份证': '身份证', '离职申请日': '解除合作申请日',
                   '离职类型': '解除合作类别', '审批状态': '状态'},
    'rider_report': {'城市名称': '城市名称', '站点': '站点名称', '风神骑手ID': '风神骑手ID',
                     '骑手姓名': '骑手姓名', '身份证': '身份证', '离职申请日': '解除合作申请日',
                     '离职类型': '解除合作类别', '审批状态': '状态'},
    'rider_quit': {'城市名称': '城市名称', '站点': '站点', '风神骑手ID': '风神骑手ID',
                   '骑手姓名': '骑手姓名', '身份证': '身份证', '离职申请日': '离职申请日',
                   '离职类型': '离职类型', '审批状态': '状态'},
    'rider_leave': {'城市名称': '城市', '站点': '站点', '风神骑手ID': '风神骑手ID',
                    '骑手姓名': '姓名', '身份证': '身份证号', '离职申请日': '请假结束时间',
                    '离职类型': '类型', '审批状态': '审核状态'},
}
TYPE_LABELS = {'batch_quit': '批量离职', 'rider_report': '离职报备',
               'rider_quit': '骑手离职', 'rider_leave': '骑手请假'}

# 模糊表头匹配的候选优先级与子串特征（对齐原模块）
RID_KEYS = ('骑手ID', '工号', 'RiderID', '卡号', 'ID', '骑手工号', '人员工号', 'riderId', '工号ID')
NAME_KEYS = ('骑手姓名', '姓名', 'Name', '人员', '员工', '骑手名', '姓名/名称', '姓名/工号')
IDCARD_KEYS = ('骑手身份证号', '身份证号', '身份证', 'IDCard', '证件号', '身份证号码', '证件号码')
CITY_KEYS = ('城市', '所属城市', 'City', '区域', '地区', '运营城市')
TEAM_KEYS = ('团队名称', '团队', '所属团队', 'Team', '网点', '站点', '所属站点', '工作网点', '配送站')
ORDER_KEYS = ('有效完成单', '总单量', '单量', '完成单量', '配送单量')


def _checkpoint(cancelled):
    if cancelled is not None and cancelled.is_set():
        raise BillCollectionError('异常骑手整理生成已取消')


def _text(value):
    if value is None:
        return ''
    return str(value).strip()


def _excel_date(serial):
    # Excel 1900 体系：序列 60 为虚构的 1900-02-29，其后序列比真实天数多 1。
    try:
        days = int(serial) - 1 if serial > 60 else int(serial)
        return (date(1899, 12, 31) + timedelta(days=days)).isoformat()
    except (OverflowError, ValueError):
        return _text(serial)


def normalize_date(value):
    """数值序列/常见字符串日期统一为 YYYY-MM-DD；无法识别时原样返回文本。"""
    if value is None or value == '':
        return ''
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, (int, float)):
        return _excel_date(float(value))
    text = _text(value)
    if re.fullmatch(r'\d{5}(\.\d+)?', text):
        return _excel_date(float(text))
    match = re.match(r'^(\d{4})[-/.年](\d{1,2})[-/.月](\d{1,2})日?', text)
    if match:
        try:
            return date(int(match.group(1)), int(match.group(2)), int(match.group(3))).isoformat()
        except ValueError:
            return text
    if re.match(r'^\d{4}-\d{2}-\d{2}[ T]', text):
        try:
            return datetime.fromisoformat(text[:19]).date().isoformat()
        except ValueError:
            return text
    return text


def _header_index(header, field):
    if field in header:
        return header.index(field)
    lowered = field.lower()
    for index, name in enumerate(header):
        if name and name.lower() == lowered:
            return index
    return None


def _fuzzy_header(header, candidates, *substrings):
    """先按候选名（忽略大小写）精确命中，再按子串特征模糊命中。"""
    for candidate in candidates:
        index = _header_index(header, candidate)
        if index is not None:
            return index
    for index, name in enumerate(header):
        lowered = name.lower()
        if name and any(part.lower() in lowered for part in substrings):
            return index
    return None


def _business_sheets(path):
    """产出 (sheet 名, 表头列表, 行值迭代器)；跳过隐藏表、options 与下载说明表。"""
    book = load_workbook(path, read_only=True, data_only=True)
    try:
        for sheet in book.worksheets:
            if sheet.sheet_state != 'visible':
                continue
            if sheet.title.startswith('options') or sheet.title == '全量下载说明':
                continue
            rows = sheet.iter_rows(values_only=True)
            header = next(rows, None)
            if header is None or not any(value is not None for value in header):
                continue
            yield _text(sheet.title), [_text(name) for name in header], rows
    finally:
        book.close()


def _cell(row, index):
    return row[index] if index is not None and index < len(row) else None


@measured('read_sources')
def _read_list(path, kind, log, cancelled):
    """读取一类离职/请假来源成品，返回精取后的字典行列表。"""
    spec = LIST_SPECS[kind]
    rows_out = []
    for _sheet, header, rows in _business_sheets(path):
        positions = {field: _header_index(header, field) for field in spec['fields']}
        for field, fallback in spec['fallback'].items():
            if positions.get(field) is None and fallback < len(header):
                positions[field] = fallback
        for row in rows:
            _checkpoint(cancelled)
            values = {field: _cell(row, index) for field, index in positions.items()}
            for field in spec['dates']:
                values[field] = normalize_date(values[field])
            name = _text(values.get(spec['name_field']))
            id_card = _text(values.get(spec['id_card_field']))
            rider_id = _text(values.get(spec['rider_field']))
            if not name and not id_card and not rider_id:
                continue
            values['_name'] = name
            values['_id_card'] = id_card
            values['_rider_id'] = rider_id
            rows_out.append(values)
    log(f'[异常骑手整理] {TYPE_LABELS[kind]}来源提取 {len(rows_out)} 行：{Path(path).name}')
    return rows_out


@measured('read_sources')
def _read_archive(path, log, cancelled):
    """读取蓝橙骑手档案成品（14 列投影或平台原表），返回字典行列表。"""
    rows_out = []
    for _sheet, header, rows in _business_sheets(path):
        positions = {field: _header_index(header, field) for field in ARCHIVE_FIELDS}
        if positions['身份证号'] is None:
            positions['身份证号'] = _fuzzy_header(header, IDCARD_KEYS, '身份证', '证件')
        for row in rows:
            _checkpoint(cancelled)
            values = {field: _cell(row, index) for field, index in positions.items()}
            values['合作日期'] = normalize_date(values['合作日期'])
            if not any(_text(value) for key, value in values.items() if key != '项目'):
                continue
            values['_name'] = _text(values['姓名'])
            values['_id_card'] = _text(values['身份证号'])
            values['_rider_id'] = _text(values['骑手ID'])
            rows_out.append(values)
    log(f'[异常骑手整理] 蓝橙骑手档案提取 {len(rows_out)} 行：{Path(path).name}')
    return rows_out


@measured('read_sources')
def _read_detail(path, log, cancelled):
    """可选：读取风神骑手数据明细，返回模糊列提取后的行列表。"""
    detail_rows = []
    for _sheet, header, rows in _business_sheets(path):
        indexes = {
            'rider': _fuzzy_header(header, RID_KEYS, 'id', '工号'),
            'name': _fuzzy_header(header, NAME_KEYS, '姓名', '人员', '员工', 'name'),
            'team': _fuzzy_header(header, TEAM_KEYS, '团队', '网点', '站点', '配送站'),
            'id_card': _fuzzy_header(header, IDCARD_KEYS, '身份证', '证件'),
            'orders': _fuzzy_header(header, ORDER_KEYS, '有效完成单', '单量'),
        }
        if indexes['rider'] is None and indexes['name'] is None:
            continue
        for row in rows:
            _checkpoint(cancelled)
            rider_id, name = _text(_cell(row, indexes['rider'])), _text(_cell(row, indexes['name']))
            if not rider_id and not name:
                continue
            try:
                orders = float(_cell(row, indexes['orders']) or 0)
            except (TypeError, ValueError):
                orders = 0
            detail_rows.append({'rider': rider_id, 'name': name,
                                'team': _text(_cell(row, indexes['team'])) or '其他团队',
                                'id_card': _text(_cell(row, indexes['id_card'])), 'orders': orders})
    log(f'[异常骑手整理] 骑手数据明细提取 {len(detail_rows)} 行：{Path(path).name}')
    return detail_rows


def _read_info_ids(path, log, cancelled):
    """可选：读取风神骑手信息成品，返回骑手ID集合。"""
    ids = set()
    for _sheet, header, rows in _business_sheets(path):
        index = _fuzzy_header(header, RID_KEYS, 'id', '工号')
        for row in rows:
            _checkpoint(cancelled)
            value = _text(_cell(row, index))
            if value:
                ids.add(value)
    log(f'[异常骑手整理] 骑手信息提取 {len(ids)} 个骑手ID：{Path(path).name}')
    return ids


def _team_city_catalog():
    """团队名称 -> 城市 映射（data/config.json）；缺失或损坏时退化为空映射。"""
    try:
        data = json.loads(CONFIG_PATH.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return {}
    return {_text(item.get('团队名称')): _text(item.get('城市'))
            for item in data if isinstance(item, dict) and _text(item.get('团队名称'))}


def match_city(team_name, catalog):
    """团队名称精确命中城市；否则取团队名中包含的最长城市名；未命中返回 ''。"""
    team = _text(team_name)
    if not team or team in ('其他团队', '未知团队'):
        return ''
    city = catalog.get(team)
    if city:
        return city
    for name in sorted({value for value in catalog.values() if value}, key=len, reverse=True):
        if name in team:
            return name
    return ''


def _city_matcher(catalog):
    # One catalog sort per workbook, one lookup per distinct team. Preserve the
    # exact-match and longest-city rules of match_city without per-rider sorting.
    names = sorted({value for value in catalog.values() if value}, key=len, reverse=True)
    cache = {}

    def resolve(team_name):
        team = _text(team_name)
        if team not in cache:
            cache[team] = ('' if not team or team in ('其他团队', '未知团队') else
                           catalog.get(team) or next((name for name in names if name in team), ''))
        return cache[team]
    return resolve


def _remark(kind, row, status):
    """备注：【档案状态】类型：日期审批(类别)；骑手请假为 日期类型(审批)。"""
    date = _text(row.get(LIST_SPECS[kind]['dates'][0])).replace('/', '-')
    if kind == 'batch_quit':
        return (f'【{status}】批量离职：{date}{_text(row.get("状态"))}'
                f'({_text(row.get("解除合作类别"))})')
    if kind == 'rider_quit':
        return (f'【{status}】骑手离职：{date}{_text(row.get("状态"))}'
                f'({_text(row.get("离职类型"))})')
    if kind == 'rider_report':
        return (f'【{status}】离职报备：{date}{_text(row.get("状态"))}'
                f'({_text(row.get("解除合作类别"))})')
    return (f'【{status}】骑手请假：{date}{_text(row.get("类型"))}'
            f'({_text(row.get("审核状态"))})')


class _Riders:
    """按 骑手ID||姓名 合并档案与四类来源的骑手视图（插入序保留首见）。"""

    def __init__(self):
        self._map = {}

    def get(self, rider_id, name):
        key = rider_id or name
        if not key:
            return None
        if key not in self._map:
            self._map[key] = {'city': '其他', 'team': '其他团队', 'rider_id': rider_id,
                              'name': name, 'id_card': '', 'coop_status': '在职'}
        return self._map[key]

    def values(self):
        return list(self._map.values())


@measured('write_sheets')
def _write_sheet(book, title, fields, widths, rows, cancelled, dynamic_widths=None):
    """写入一个 sheet：表头加粗、全表微软雅黑 10、居中、冻结首行。"""
    sheet = book.create_sheet(title[:31])
    prepared_write_only_rows(sheet)
    # 写只模式在首行写入时固化表头；冻结与列宽必须在 append 前设置。
    sheet.freeze_panes = 'A2'
    style_header = style_applier(sheet, font=_HEADER_FONT, alignment=_CENTER)
    style_data = style_applier(sheet, font=_DATA_FONT, alignment=_CENTER)
    if dynamic_widths is not None:
        widths = dynamic_widths
    for index, width in enumerate(widths[:len(fields)], 1):
        sheet.column_dimensions[get_column_letter(index)].width = column_width(width)
    header = []
    for name in fields:
        cell = WriteOnlyCell(sheet, value=name)
        style_header(cell)
        header.append(cell)
    sheet.append(header)
    for row in rows:
        _checkpoint(cancelled)
        values = []
        for field in fields:
            cell = WriteOnlyCell(sheet, value=row.get(field, ''))
            style_data(cell)
            values.append(cell)
        sheet.append(values)


@profiled('abnormal_riders', 5, 'output_dir')
def generate_abnormal_riders(batch_quit_file, rider_quit_file, rider_report_file, rider_leave_file,
                             archive_file, output_dir, log=None, cancelled=None,
                             detail_file=None, info_file=None, station_directory=None):
    """组装异常骑手整理工作簿，返回成品文件 Path（归档命名由发布层完成）。

    前五项为 5 类蓝橙成品路径；detail_file/info_file 为同任务可选的风神
    骑手数据明细/骑手信息成品，提供时补总单量与活跃异常判定。
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    def progress(message):
        if log is not None:
            log(message)

    lists = {'batch_quit': _read_list(batch_quit_file, 'batch_quit', progress, cancelled),
             'rider_report': _read_list(rider_report_file, 'rider_report', progress, cancelled),
             'rider_quit': _read_list(rider_quit_file, 'rider_quit', progress, cancelled),
             'rider_leave': _read_list(rider_leave_file, 'rider_leave', progress, cancelled)}
    archive = _read_archive(archive_file, progress, cancelled)
    detail_rows = _read_detail(detail_file, progress, cancelled) if detail_file else []
    info_ids = _read_info_ids(info_file, progress, cancelled) if info_file else set()

    # 档案按身份证号首见回填合作状态/合作日期
    status_by_id, join_date_by_id = {}, {}
    for row in archive:
        id_card = row['_id_card']
        if not id_card:
            continue
        status_by_id.setdefault(id_card, _text(row.get('状态')))
        join_date_by_id.setdefault(id_card, _text(row.get('合作日期')))
    total_rows = sum(len(kind) for kind in lists.values())
    matched = sum(1 for rows in lists.values() for row in rows
                  if row['_id_card'] and row['_id_card'] in status_by_id)
    progress(f'[异常骑手整理] 四类来源共 {total_rows} 行，档案状态按身份证号匹配 {matched} 行'
             f'（蓝橙骑手档案 {len(archive)} 行）')

    # 骑手合并视图：档案先入（城市/团队/身份证/状态最全），四类来源随后补充
    riders = _Riders()
    archive_ids = set()
    for row in archive:
        archive_ids.add(row['_rider_id'])
        rider = riders.get(row['_rider_id'], row['_name'])
        if rider is None:
            continue
        if row['_rider_id']:
            rider['rider_id'] = row['_rider_id']
        if row['_name']:
            rider['name'] = row['_name']
        if row['_id_card']:
            rider['id_card'] = row['_id_card']
        city, team, status = _text(row.get('城市')), _text(row.get('站点')), _text(row.get('状态'))
        if city:
            rider['city'] = city
        if team:
            rider['team'] = team
        if status:
            rider['coop_status'] = status
    remarks_by_kind = {}
    for kind, rows in lists.items():
        remarks_by_kind[kind] = {}
        for row in rows:
            status = status_by_id.get(row['_id_card'], '') if row['_id_card'] else ''
            row['备注'] = _remark(kind, row, status)
            rider = riders.get(row['_rider_id'], row['_name'])
            if rider is not None:
                if row['_rider_id']:
                    rider['rider_id'] = row['_rider_id']
                if row['_name']:
                    rider['name'] = row['_name']
                if row['_id_card'] and not rider['id_card']:
                    rider['id_card'] = row['_id_card']
                city = _text(row.get('城市名称'))
                if city and rider['city'] == '其他':
                    rider['city'] = city
            if row['_id_card']:
                remarks_by_kind[kind].setdefault(row['_id_card'], []).append(row['备注'])

    def joined_remarks(kind, id_card):
        bucket = remarks_by_kind[kind].get(id_card) if id_card else None
        return '；'.join(bucket) if bucket else ''

    # 单量按 骑手ID+团队 求和；跨站团队取单量最多站点，同量取全局先出现站点
    orders_map, team_first = {}, {}
    for entry in detail_rows:
        key = (entry['rider'], entry['team'])
        orders_map[key] = orders_map.get(key, 0) + entry['orders']
        team_first.setdefault(key, len(team_first))
    groups = {}
    for entry in detail_rows:
        group = groups.setdefault(entry['rider'] or entry['name'], {'rider_id': '', 'name': '', 'teams': {}})
        if entry['rider']:
            group['rider_id'] = entry['rider']
        if entry['name']:
            group['name'] = entry['name']
        team = group['teams'].setdefault(entry['team'],
                                         {'orders': 0.0, 'first': team_first[(entry['rider'], entry['team'])]})
        team['orders'] += entry['orders']
    detail_riders = []
    for group in groups.values():
        best, best_orders, best_first = '其他团队', -1.0, None
        for team, info in group['teams'].items():
            if info['orders'] > best_orders or (info['orders'] == best_orders
                                                and (best_first is None or info['first'] < best_first)):
                best, best_orders, best_first = team, info['orders'], info['first']
        detail_riders.append({'team': best, 'rider_id': group['rider_id'], 'name': group['name']})

    catalog = _team_city_catalog()
    from station_city_resolution import resolver
    city_for_team, city_issues = resolver(station_directory or {}, catalog)

    def build_summary(team, rider_id, name, rider):
        id_card = _text((rider or {}).get('id_card'))
        status = status_by_id.get(id_card) if id_card else None
        coop_status = status or (rider or {}).get('coop_status') or '在职'
        quit_remark = joined_remarks('rider_quit', id_card)
        batch_remark = joined_remarks('batch_quit', id_card)
        leave_remark = joined_remarks('rider_leave', id_card)
        orders = 0
        if rider_id and team:
            orders = int(orders_map.get((rider_id, team), 0) or 0)
        elif rider_id:
            orders = int(sum(quantity for (rid, _team), quantity in orders_map.items() if rid == rider_id))
        run_no_entry = '是' if ('跑单' in coop_status or '未入职' in coop_status) else '否'
        if run_no_entry == '否' and orders > 0 and rider_id \
                and rider_id not in archive_ids and rider_id not in info_ids:
            run_no_entry = '是'
        released = '否' if coop_status in ('合作', '预解除') else '是'
        is_quit = bool(quit_remark or batch_remark) or '离职' in coop_status or '注销' in coop_status
        if is_quit and orders > 0:
            abnormal = '是(离职仍有单量)'
        elif leave_remark and orders > 0:
            abnormal = '是(请假仍有单量)'
        else:
            abnormal = '否'
        city = city_for_team(team) or (rider or {}).get('city') or '待核对'
        return dict(zip(SUMMARY_FIELDS, (
            city, team, rider_id, name,
            joined_remarks('batch_quit', id_card), quit_remark,
            joined_remarks('rider_report', id_card), leave_remark,
            coop_status, run_no_entry, released, abnormal, orders, id_card)))

    summary_count = len(detail_riders) if detail_riders else len(riders._map)

    def summary_rows():
        if detail_riders:
            for entry in detail_riders:
                _checkpoint(cancelled)
                rider = riders.get(entry['rider_id'], entry['name'])
                yield build_summary(entry['team'], entry['rider_id'], entry['name'], rider)
        else:
            for rider in riders._map.values():
                _checkpoint(cancelled)
                yield build_summary(rider['team'], rider['rider_id'], rider['name'], rider)
    progress(f'[异常骑手整理] 汇总待写入 {summary_count} 名骑手'
             f'（{"骑手数据明细驱动" if detail_riders else "档案与来源合并驱动"}）')

    # 异常汇总按 批量离职 → 离职报备 → 骑手离职 → 骑手请假 的顺序拼接
    def abnormal_rows():
        for kind in ('batch_quit', 'rider_report', 'rider_quit', 'rider_leave'):
            mapping = ABNORMAL_MAPPINGS[kind]
            for row in lists[kind]:
                _checkpoint(cancelled)
                id_card = row['_id_card']
                yield {
                **{target: _text(row.get(source)) for target, source in mapping.items()},
                '合作日期': join_date_by_id.get(id_card, '') if id_card else '',
                '合作状态': status_by_id.get(id_card, '') if id_card else '',
                '类型': TYPE_LABELS[kind],
                '备注': row['备注'],
                }

    archive_widths = [display_width(name) for name in ARCHIVE_FIELDS]
    for row in archive:
        for index, field in enumerate(ARCHIVE_FIELDS):
            width = display_width(row.get(field, ''))
            if width > archive_widths[index]:
                archive_widths[index] = width

    book = Workbook(write_only=True)
    try:
        _write_sheet(book, '异常汇总', ABNORMAL_FIELDS, ABNORMAL_WIDTHS, abnormal_rows(), cancelled)
        _write_sheet(book, '蓝橙骑手档案', ARCHIVE_FIELDS, (), archive, cancelled,
                     dynamic_widths=archive_widths)
        _write_sheet(book, '汇总', SUMMARY_FIELDS, SUMMARY_WIDTHS, summary_rows(), cancelled)
        if station_directory:
            _write_sheet(book, '站点城市目录', ('站点编号', '站点名称', '城市编号', '城市'), (24, 30, 24, 18),
                         (dict(zip(('站点编号', '站点名称', '城市编号', '城市'), (s['id'], s['name'], s.get('city_id', ''), s['city']))) for s in station_directory.get('stations', [])), cancelled)
        if city_issues:
            _write_sheet(book, '城市归属待核对', ('站点名称', '人工配置城市', '后台城市', '核对原因'), (30, 18, 30, 50),
                         (dict(zip(('站点名称', '人工配置城市', '后台城市', '核对原因'), row)) for row in city_issues.values()), cancelled)
        _checkpoint(cancelled)
        target = output_dir / ('.异常骑手整理_' + uuid.uuid4().hex + '.xlsx')
        try:
            with stage('save_workbook'):
                book.save(target)
        except Exception:
            target.unlink(missing_ok=True)
            raise
        progress(f'[异常骑手整理] 成品已生成：异常汇总 {total_rows} 行、'
                 f'蓝橙骑手档案 {len(archive)} 行、汇总 {summary_count} 行')
        return target
    finally:
        book.close()
