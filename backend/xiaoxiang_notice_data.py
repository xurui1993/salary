"""小象灯塔通知附件批量合并导出（骑手订单明细 / 骑手出勤明细）。

数据来源为通知中心附件：
- 骑手订单明细：周通知「*骑手订单明细」中的【商配送】骑手订单明细（结算口径）-1/-2
  分片（两片行不相交，可直接合并）；【大网配送】等其余附件排除。
- 骑手出勤明细：日通知「*合作商数据下发」中的「骑手出勤明细_*.xlsx」（每期最多一份，
  个别通知缺失该附件时跳过）。

日期口径：通知标题日期与数据日期存在滞后/错位（如「10.28合作商数据下发」内数据是
10.27），因此统一按附件内日期列筛选——骑手订单明细按「业务日期」（YYYY-MM-DD，
平台个别周期曾改为 2026/10/18 斜杠格式，两种写法均识别）、
骑手出勤明细按「xxx.dt」（YYYYMMDD）。
覆盖口径：合并后校验区间内每一天都有数据，中段缺失直接报错拒绝交付，
仅容忍范围末尾尚未发布的滞后，避免静默导出残缺文件。
去重口径：多期通知可能重复覆盖同一数据日期（双发通知），按（日期, 骑手id）去重，
保留发布时间较新通知的数据。
数值口径：源附件全部为文本；编号/单量/时长等数值列转为数值，NULL、是/否、不考核
等保留原文本。
"""
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
import os
import re
import uuid

import requests
from openpyxl import Workbook, load_workbook
from openpyxl.cell import WriteOnlyCell
from openpyxl.utils import get_column_letter

import xiaoxiang_lighthouse
from excel_styles import prepared_write_only_rows, style_applier
from fengshen_bill import BillCollectionError, column_width, display_width
from xiaoxiang_board import DAILY_CENTER, DAILY_FONT, DAILY_HEADER_FILL
from xiaoxiang_lighthouse import LighthouseError, SessionExpired

BEIJING = timezone(timedelta(hours=8), 'Asia/Shanghai')

ORDER_DATASET = 'rider_order_detail'
ATTENDANCE_DATASET = 'xiaoxiang_attendance_detail'

LIST_PAGE_LIMIT = 100
LIST_PAGE_GUARD = 50
FILE_ROW_GUARD = 500_000


def _parse_iso_date(value):
    """「业务日期」列：YYYY-MM-DD 或 YYYY/M/D 文本（容忍 datetime 单元格）。

    平台个别周期曾将附件日期改为「2026/10/18」斜杠格式，两种写法都必须识别。
    """
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        match = re.fullmatch(r'(\d{4})[-/](\d{1,2})[-/](\d{1,2})', value.strip())
        if match:
            try:
                return date(*map(int, match.groups()))
            except ValueError:
                return None
    return None


def _parse_compact_date(value):
    """「xxx.dt」列：YYYYMMDD 文本（容忍 datetime 单元格）。"""
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        text = value.strip()
        if re.fullmatch(r'\d{8}', text):
            try:
                return date(int(text[:4]), int(text[4:6]), int(text[6:]))
            except ValueError:
                return None
    return None


def _numeric_cell(value):
    """数值列：整数文本转 int，小数文本转 float，其余（NULL 等）保留原文本。"""
    if isinstance(value, str):
        text = value.strip()
        if re.fullmatch(r'-?\d{1,15}', text):
            return int(text)
        if re.fullmatch(r'-?\d{1,15}\.\d{1,10}', text):
            try:
                return float(text)
            except ValueError:
                return value
    return value


_ORDER_NUMERIC = frozenset({'站点id', '骑手id', '合作商id', '三方结算公司id', '城市id', '配送单量'})
_ATTENDANCE_NUMERIC = frozenset({
    'xxx.poi_id', 'xxx.rider_id',
    '出勤小时数不含休息', '排班小时数不含休息', '计划外出勤小时数',
    '午高峰完单', '晚高峰完单', '全天完单',
    'bbb.全天工作时长', 'bbb.午高峰工作时长', 'bbb.晚高峰工作时长',
    'ccc.全天排班时长', 'ccc.午高峰排班时长', 'ccc.晚高峰排班时长',
    'ddd.是否新骑手', '有效运力折算系数',
})

_DATASET_SPECS = {
    ORDER_DATASET: {
        'label': '骑手订单明细',
        'notice_keyword': '骑手订单明细',
        'attachment_keywords': ('【商配送】', '骑手订单明细'),
        'date_column': '业务日期',
        'date_parser': _parse_iso_date,
        'rider_column': '骑手id',
        'numeric_columns': _ORDER_NUMERIC,
        'missing_note': '通知中没有【商配送】骑手订单明细附件',
        # 周通知发布于周期结束后约 1~2 天，回溯 10 天足够覆盖 7 天周期。
        'publish_margin': 10,
    },
    ATTENDANCE_DATASET: {
        'label': '骑手出勤明细',
        'notice_keyword': '合作商数据下发',
        'attachment_keywords': ('骑手出勤明细',),
        'date_column': 'xxx.dt',
        'date_parser': _parse_compact_date,
        'rider_column': 'xxx.rider_id',
        'numeric_columns': _ATTENDANCE_NUMERIC,
        'missing_note': '通知中没有骑手出勤明细附件',
        # 合作商数据下发存在多期合并通知（如 1016-1018），数据日期最迟约滞后 4 天。
        'publish_margin': 5,
    },
}


def _publish_date(record):
    value = record.get('publishTime')
    if isinstance(value, (int, float)) and value > 0:
        return datetime.fromtimestamp(value / 1000, BEIJING).date()
    return None


def list_keyword_notices(session, spec, start, supplier_id=xiaoxiang_lighthouse.SUPPLIER_ID,
                         cancelled=None):
    """遍历通知列表（接口标题为前缀匹配，故取全量后客户端按关键字筛选）。

    仅保留发布日期不早于「范围开始 - 回溯余量」的通知：附件数据日期不会晚于其
    发布日期，更早发布的通知不可能包含范围内数据。
    """
    keyword = spec['notice_keyword']
    floor = start - timedelta(days=spec['publish_margin'])
    records, offset = [], 0
    for _ in range(LIST_PAGE_GUARD):
        if cancelled is not None and cancelled.is_set():
            raise LighthouseError('已取消')
        data = xiaoxiang_lighthouse._post(
            session, xiaoxiang_lighthouse.LIST_PATH,
            {'supplierId': supplier_id, 'paging': {'offset': offset, 'limit': LIST_PAGE_LIMIT}})
        page = data.get('noticeRecordList')
        if not isinstance(page, list):
            raise LighthouseError('通知列表数据结构无效，页面可能已改版')
        records.extend(item for item in page if isinstance(item, dict))
        total = data.get('total')
        offset += len(page)
        if not page or (isinstance(total, int) and offset >= total):
            break
    else:
        raise LighthouseError('通知列表分页超出保护上限，未发布文件')
    matched = [item for item in records
               if keyword in str(item.get('title') or '')
               and (_publish_date(item) is None or _publish_date(item) >= floor)]
    matched.sort(key=lambda item: (item.get('publishTime') or 0, item.get('id') or 0))
    return matched


def select_notice_attachments(detail, spec):
    """筛选通知内关键字附件（.xlsx），返回 [(fileName, fileUrl)]。"""
    picked = []
    for item in detail.get('fileInfoList') or []:
        if not isinstance(item, dict):
            continue
        name = str(item.get('fileName') or '').strip()
        url = str(item.get('fileUrl') or '').strip()
        if not name or not url:
            continue
        if all(keyword in name for keyword in spec['attachment_keywords']) \
                and name.lower().endswith('.xlsx'):
            picked.append({'fileName': name, 'fileUrl': url})
    return picked


def _download_attachment(url, target):
    """通知附件直链下载（S3 公网地址，仅校验 HTTP 状态；结构由 _load_table 校验）。"""
    target = Path(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    part = target.with_suffix(target.suffix + '.part')
    try:
        with requests.get(url, stream=True, timeout=(10, 180),
                          headers={'User-Agent': xiaoxiang_lighthouse.HEADERS['User-Agent']}) as response:
            if response.status_code != 200:
                raise LighthouseError('附件下载返回 HTTP {}'.format(response.status_code))
            with part.open('wb') as stream:
                for chunk in response.iter_content(1024 * 1024):
                    if chunk:
                        stream.write(chunk)
        os.replace(part, target)
    except requests.RequestException as exc:
        raise LighthouseError('附件下载中断，请重试') from exc
    finally:
        part.unlink(missing_ok=True)
    return target


def _load_table(path, spec):
    """读取附件为 (header, rows)，附件行数超保护上限时拒绝。"""
    book = load_workbook(path, read_only=True)
    try:
        sheet = book[book.sheetnames[0]]
        sheet.reset_dimensions()
        iterator = sheet.iter_rows(values_only=True)
        header = list(next(iterator, ()) or ())
        if not header:
            raise LighthouseError('附件没有数据表头：{}'.format(path.name))
        rows = []
        for row in iterator:
            rows.append(list(row))
            if len(rows) > FILE_ROW_GUARD:
                raise LighthouseError('附件行数超出保护上限：{}'.format(path.name))
    finally:
        book.close()
    return header, rows


def _sort_rider(value):
    if isinstance(value, int):
        return (0, value, '')
    text = str(value or '').strip()
    if re.fullmatch(r'\d{1,15}', text):
        return (0, int(text), '')
    return (1, 0, text)


def collect_notice_rows(session, spec, start, end,
                        supplier_id=xiaoxiang_lighthouse.SUPPLIER_ID,
                        log=None, cancelled=None, temp_dir=None):
    """下载各期附件并合并：日期筛选 + （日期, 骑手id）去重，返回 (header, records)。"""
    log = log or (lambda message, *args, **kwargs: None)
    notices = list_keyword_notices(session, spec, start, supplier_id, cancelled)
    label = spec['label']
    log('[进度] 匹配到 {} 期「{}」通知'.format(len(notices), spec['notice_keyword']))
    merged, header, date_index, rider_index = {}, None, None, None
    with TemporaryDirectory(prefix='xiaoxiang_notice_') as owned_dir:
        temp_root = Path(temp_dir or owned_dir)
        for notice in notices:
            if cancelled is not None and cancelled.is_set():
                raise LighthouseError('{}已取消'.format(label))
            detail = xiaoxiang_lighthouse.notice_detail(session, notice['id'], supplier_id)
            attachments = select_notice_attachments(detail, spec)
            if not attachments:
                log('[跳过] {}（{}）'.format(notice.get('title'), spec['missing_note']))
                continue
            log('[进度] {}：下载 {} 个附件'.format(notice.get('title'), len(attachments)))
            for attachment in attachments:
                if cancelled is not None and cancelled.is_set():
                    raise LighthouseError('{}已取消'.format(label))
                target = temp_root / (uuid.uuid4().hex + '.xlsx')
                _download_attachment(attachment['fileUrl'], target)
                rows_header, rows = _load_table(target, spec)
                if header is None:
                    header = rows_header
                    if spec['date_column'] not in header or spec['rider_column'] not in header:
                        raise LighthouseError('{}附件缺少关键列：{}、{}'.format(
                            label, spec['date_column'], spec['rider_column']))
                    date_index, rider_index = header.index(spec['date_column']), header.index(spec['rider_column'])
                elif rows_header != header:
                    raise LighthouseError('{}附件表头不一致：{}'.format(label, attachment['fileName']))
                for row in rows:
                    row_date = spec['date_parser'](row[date_index]) if date_index < len(row) else None
                    if row_date is None or not start <= row_date <= end:
                        continue
                    rider = row[rider_index] if rider_index < len(row) else None
                    merged[(row_date, _sort_rider(rider))] = row
    if not merged:
        raise LighthouseError('{} 范围内没有可合并的{}数据'.format(label, spec['notice_keyword']))
    _check_date_coverage(merged, spec, start, end, log)
    records = [merged[key] for key in sorted(merged, key=lambda item: (item[0], item[1]))]
    return header, records


def _check_date_coverage(merged, spec, start, end, log):
    """区间中段出现无数据日期时拒绝交付，仅容忍范围末尾尚未发布的滞后。"""
    covered = {key[0] for key in merged}
    last = max(covered)
    gaps = []
    day = start
    while day <= last:
        if day not in covered:
            gaps.append(day)
        day += timedelta(days=1)
    if gaps:
        shown = '、'.join(item.isoformat() for item in gaps[:10]) + ('等' if len(gaps) > 10 else '')
        raise LighthouseError('{} {} 至 {} 中以下日期在全部通知附件中均无数据：{}。'
                              '已拒绝生成不完整文件，请核查源附件日期格式或通知是否完整'
                              .format(spec['label'], start.isoformat(), end.isoformat(), shown))
    if last < end:
        log('[警告] {} 至 {} 暂无数据（可能尚未发布）'.format((last + timedelta(days=1)).isoformat(),
                                                        end.isoformat()))


def _convert_row(row, header, spec, date_index):
    """数值列转数值，日期列统一为 ISO 格式；其余保留原文本。"""
    numeric_columns = spec['numeric_columns']
    values = []
    for index, name in enumerate(header):
        value = row[index] if index < len(row) else None
        if value is None:
            value = ''
        elif index == date_index:
            parsed = spec['date_parser'](value)
            value = parsed.isoformat() if parsed is not None else str(value)
        elif name in numeric_columns:
            value = _numeric_cell(value)
        elif not isinstance(value, str):
            value = str(value)
        values.append(value)
    return values


def write_notice_workbook(header, records, spec, target, cancelled=None):
    """系统标准样式：微软雅黑 10、居中、自适应列宽、冻结首行、表头浅橙底色。"""
    if not records:
        raise LighthouseError('没有可写入的{}数据'.format(spec['label']))
    if cancelled is not None and cancelled.is_set():
        raise LighthouseError('{}已取消'.format(spec['label']))
    label = spec['label']
    target = Path(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name('.{}_'.format(label) + uuid.uuid4().hex + '.xlsx')
    widths = [display_width(name) for name in header]
    converted = [_convert_row(row, header, spec,
                              header.index(spec['date_column']) if spec['date_column'] in header else None)
                 for row in records]
    for values in converted:
        for index, value in enumerate(values):
            widths[index] = max(widths[index], display_width(value))
    workbook = Workbook(write_only=True)
    sheet = workbook.create_sheet(label)
    prepared_write_only_rows(sheet)
    sheet.freeze_panes = 'A2'
    apply_style = style_applier(sheet, font=DAILY_FONT, alignment=DAILY_CENTER)
    for index, width in enumerate(widths, 1):
        sheet.column_dimensions[get_column_letter(index)].width = column_width(width)

    def cells(values, fill=None):
        result = []
        for value in values:
            cell = WriteOnlyCell(sheet, value=value)
            if isinstance(value, str):
                cell.data_type = 's'
            apply_style(cell)
            if fill is not None:
                cell.fill = fill
            result.append(cell)
        return result

    saved = False
    try:
        sheet.append(cells(header, DAILY_HEADER_FILL))
        for values in converted:
            if cancelled is not None and cancelled.is_set():
                raise LighthouseError('{}已取消'.format(label))
            sheet.append(cells(values))
        workbook.save(temporary)
        saved = True
        os.replace(temporary, target)
    finally:
        if not saved:
            try:
                workbook.save(temporary)
            except Exception:
                pass
        workbook.close()
        temporary.unlink(missing_ok=True)
    return {'rows': len(converted), 'columns': len(header)}


def _session():
    """复用系统通道保存的小象灯塔会话；不可用时提示先认证。"""
    from xiaoxiang_source_auth import AUTH
    try:
        state = xiaoxiang_lighthouse.load_state()
    except LighthouseError as exc:
        AUTH.invalidate()
        raise BillCollectionError('小象灯塔会话不可用（{}），请先在系统通道完成小象灯塔认证'.format(exc)) from None
    if state is None:
        AUTH.invalidate()
        raise BillCollectionError('尚未保存小象灯塔会话，请先在系统通道完成小象灯塔认证')
    session = xiaoxiang_lighthouse.session_from_state(state)
    session.headers.update({'Origin': xiaoxiang_lighthouse.BASE,
                            'Referer': xiaoxiang_lighthouse.BASE + '/rideroms/notice.html'})
    return session


def generate_notice_merge(dataset, start, end, directory, log=None, cancelled=None,
                          supplier_id=xiaoxiang_lighthouse.SUPPLIER_ID):
    """合并指定日期范围的骑手订单明细/骑手出勤明细通知附件，返回工作簿路径。"""
    spec = _DATASET_SPECS[dataset]
    label = spec['label']
    log = log or (lambda message, *args, **kwargs: None)
    try:
        first, last = date.fromisoformat(start), date.fromisoformat(end)
    except (TypeError, ValueError):
        raise LighthouseError('{}日期区间无效：{} 至 {}'.format(label, start, end)) from None
    if first > last:
        raise LighthouseError('{}开始日期不能晚于结束日期'.format(label))
    if cancelled is not None and cancelled.is_set():
        raise LighthouseError('{}已取消'.format(label))
    session = _session()
    log('[下载] 正在查询小象灯塔{}（{} 至 {}，按附件数据日期筛选）'.format(label, start, end))
    try:
        header, records = collect_notice_rows(
            session, spec, first, last, supplier_id, log, cancelled)
    except SessionExpired:
        from xiaoxiang_source_auth import AUTH
        AUTH.invalidate()
        raise
    finally:
        session.close()
    target = Path(directory) / '{}_{}_{}.xlsx'.format(label, first.isoformat(), last.isoformat())
    info = write_notice_workbook(header, records, spec, target, cancelled)
    log('[校验] {}：{} 行 / {} 列'.format(label, info['rows'], info['columns']))
    return target
