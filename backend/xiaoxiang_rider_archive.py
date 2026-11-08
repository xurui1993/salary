"""小象灯塔骑手档案快照导出（maicaipeisong.meituan.com /riders 界面无导出按钮）。

列表接口返回打码手机号/身份证，明文由 sens/query 批量获取（上限 50 人/批）。
手机号与身份证只写入成品工作簿；日志与异常信息不得包含明文。
"""
from datetime import datetime, timedelta, timezone
from pathlib import Path
import json
import os
import re
import uuid

from openpyxl import Workbook
from openpyxl.cell import WriteOnlyCell
from openpyxl.utils import get_column_letter

import xiaoxiang_lighthouse
from excel_styles import prepared_write_only_rows, style_applier
from fengshen_bill import BillCollectionError, column_width, display_width
from xiaoxiang_board import DAILY_CENTER, DAILY_FONT, DAILY_HEADER_FILL
from xiaoxiang_lighthouse import LighthouseError, SessionExpired

BEIJING = timezone(timedelta(hours=8), 'Asia/Shanghai')
LIST_PATH = '/api/s/peisong/query/rider/list'
SENS_PATH = '/api/s/peisong/rider/sens/query'
ATTR_PATH = '/api/s/peisong/supplier/rider/attr/list/query'
LIST_PAGE_LIMIT = 2000
LIST_PAGE_GUARD = 50
SENS_BATCH_LIMIT = 50
_MIS_COOKIE = 'moa_token'
_MIS_FIELD = re.compile(r'"mis"\s*:\s*"([^"]+)"')

ATTR_NAMES = {0: '全职', 10: '时段兼职', 20: '普通全天兼职', 30: '高价兼职'}
DUTY_NAMES = {1: '在职'}
GENDER_NAMES = {1: '男', 2: '女'}
# 按参考样表固定 28 列及顺序；身份证号/手机号/配送模式/时间列保留文本。
COLUMNS = (
    ('work_site_name', '所属站点'), ('id', '骑手ID'), ('name', '姓名'),
    ('identity_id', '身份证号'), ('mobile', '手机号'), ('gender', '性别'),
    ('attr_name', '人员属性'), ('employee_time', '开始服务时间'), ('entry_time', '入职时间'),
    ('health_expired_date', '健康证到期日'), ('zombie_days', '连续未卸单天数'),
    ('yt_types', '配送模式'), ('experienced', '是否有经验'), ('rc_level', '骑手等级'),
    ('new_old_rider_tag', '新老骑手标签'), ('can_work', '是否可接单'),
    ('work_status_app', 'App工作状态'), ('qr_dispatch_status', '调度状态'),
    ('trans_site_status', '转站状态'), ('trans_site_target', '转站目标'),
    ('wallet_id', '钱袋宝ID'), ('wallet_status', '钱袋宝状态'),
    ('wallet_bind_card_status', '发薪卡状态'), ('fire_eye', '火眼状态'),
    ('leader_label', '组长标签'), ('uid', 'UID'),
    ('ctime', '资料创建时间'), ('utime', '资料更新时间'),
)
ARCHIVE_TEXT_CODES = frozenset({
    'work_site_name', 'name', 'identity_id', 'mobile', 'gender', 'attr_name',
    'employee_time', 'entry_time', 'health_expired_date', 'yt_types', 'ctime', 'utime',
})


def operator_mis(state):
    """当前登录人 mis 保存在 moa_token cookie 的 base64 JSON 体里，接口 operator 必填。"""
    import base64
    for cookie in xiaoxiang_lighthouse.scoped_state(state or {})['cookies']:
        if cookie.get('name') != _MIS_COOKIE:
            continue
        value = cookie.get('value') or ''
        match = _MIS_FIELD.search(value)
        if not match:
            try:
                decoded = base64.urlsafe_b64decode(value + '=' * (-len(value) % 4)).decode('utf-8', 'ignore')
            except Exception:
                decoded = ''
            match = _MIS_FIELD.search(decoded)
        if match:
            return match.group(1)
    raise LighthouseError('无法识别小象灯塔当前登录账号，请重新认证')


def _api_post(session, path, payload, title):
    try:
        response = session.post(xiaoxiang_lighthouse.BASE + path, json=payload, timeout=120)
    except requests.RequestException as exc:
        raise LighthouseError('连接小象灯塔骑手接口失败，请检查网络后重试') from exc
    if response.status_code != 200:
        raise LighthouseError('小象灯塔骑手接口返回 HTTP {}'.format(response.status_code))
    if 'passport.meituan.com' in str(getattr(response, 'url', '') or '') \
            or 'text/html' in str(response.headers.get('content-type') or ''):
        raise SessionExpired('小象灯塔登录已失效，请重新登录')
    try:
        body = response.json()
    except ValueError:
        raise LighthouseError('{}接口返回内容不是 JSON，页面可能已改版'.format(title)) from None
    code = body.get('code')
    if code == 5:
        raise SessionExpired('小象灯塔登录已失效，请重新登录')
    if code != 0:
        raise LighthouseError('{}接口错误：{}'.format(title, body.get('msg') or code))
    return body.get('data') or {}


def _list_body(offset, supplier_id, operator):
    return {'role': None, 'attr': None, 'dutyStatus': None, 'riderId': None, 'name': None,
            'mobile': None, 'qrDispatchStatus': None, 'needBindSites': True,
            'walletStatus': None, 'walletBindCardStatus': None,
            'needImg': False, 'needImageInfo': True,
            'paging': {'needPagination': True, 'offset': offset, 'limit': LIST_PAGE_LIMIT},
            'supplierId': str(supplier_id), 'checkSupplierAccess': True, 'operator': operator}


def query_rider_rows(session, supplier_id=xiaoxiang_lighthouse.SUPPLIER_ID, operator=None):
    """全量骑手列表（当前在职+离职状态原样返回），翻页直到取满 total。"""
    operator = operator or ''
    rows, offset = [], 0
    for _ in range(LIST_PAGE_GUARD):
        data = _api_post(session, LIST_PATH, _list_body(offset, supplier_id, operator), '骑手列表')
        page = data.get('list')
        if not isinstance(page, list) or not all(isinstance(row, dict) for row in page):
            raise LighthouseError('骑手列表数据结构无效，页面可能已改版；未发布文件')
        rows.extend(page)
        total = data.get('total')
        if isinstance(total, int) and total <= len(rows):
            return rows
        if not page:
            if isinstance(total, int) and total > len(rows):
                raise LighthouseError('骑手列表获取不完整（{} / {} 人），未发布文件'.format(len(rows), total))
            return rows
        offset += len(page)
    raise LighthouseError('骑手列表分页超出保护上限，未发布文件')


def query_sens_infos(session, rider_ids, supplier_id=xiaoxiang_lighthouse.SUPPLIER_ID, operator=None):
    """批量明文手机号与身份证号；平台单批上限 50 人。"""
    operator = operator or ''
    result = {}
    for start in range(0, len(rider_ids), SENS_BATCH_LIMIT):
        batch = rider_ids[start:start + SENS_BATCH_LIMIT]
        payload = {'sensRiderIds': batch, 'registerId': None, 'needMobile': True, 'needIdentityId': True,
                   'supplierId': str(supplier_id), 'checkSupplierAccess': True, 'operator': operator}
        data = _api_post(session, SENS_PATH, payload, '骑手联系方式')
        infos = data.get('riderSensInfos')
        if not isinstance(infos, list):
            raise LighthouseError('骑手联系方式数据结构无效，页面可能已改版；未发布文件')
        for info in infos:
            if isinstance(info, dict) and isinstance(info.get('id'), int):
                result[info['id']] = info
    return result


def query_attr_names(session, supplier_id=xiaoxiang_lighthouse.SUPPLIER_ID, operator=None):
    """人员属性字典；接口失败回落内置映射，会话过期必须向上传播。"""
    try:
        data = _api_post(session, ATTR_PATH, {'supplierId': str(supplier_id),
                                              'checkSupplierAccess': True, 'operator': operator or ''},
                         '人员属性')
    except SessionExpired:
        raise
    except LighthouseError:
        return dict(ATTR_NAMES)
    names = dict(ATTR_NAMES)
    for item in (data.get('riderAttrList') or []):
        if isinstance(item, dict) and isinstance(item.get('attrId'), int) and item.get('attrName'):
            names[item['attrId']] = str(item['attrName'])
    return names


def _ms_time(value, date_only=False):
    if not isinstance(value, int) or value <= 0:
        return None
    moment = datetime.fromtimestamp(value / 1000, BEIJING)
    return moment.strftime('%Y-%m-%d' if date_only else '%Y-%m-%d %H:%M:%S')


def _names(values, *keys):
    if not isinstance(values, list):
        return None
    parts = []
    for item in values:
        if isinstance(item, dict):
            part = next((str(item[key]) for key in keys if item.get(key)), None)
            parts.append(part or json.dumps(item, ensure_ascii=False))
        else:
            parts.append(str(item))
    return '、'.join(parts) or None


def rider_row_values(row, sens, attr_names):
    image = row.get('imageInfo') if isinstance(row.get('imageInfo'), dict) else {}
    sens = sens if isinstance(sens, dict) else {}
    attr = row.get('attr')
    values = {
        'id': row.get('id') if isinstance(row.get('id'), int) else None,
        'name': row.get('name'),
        'mobile': sens.get('mobile') or row.get('mobile'),
        'identity_id': sens.get('identityId') or row.get('identityId'),
        'mis': row.get('mis'),
        'gender': GENDER_NAMES.get(row.get('gender'), str(row.get('gender')) if row.get('gender') is not None else None),
        'role': row.get('role'),
        'attr_name': attr_names.get(attr, str(attr) if attr is not None else None),
        'duty_name': DUTY_NAMES.get(row.get('dutyStatus'), str(row.get('dutyStatus')) if row.get('dutyStatus') is not None else None),
        'work_site_name': row.get('workSiteName'),
        'city_name': row.get('cityName'),
        'bind_sites': _names(row.get('bindSiteInfos'), 'siteName'),
        'leader_names': _names(row.get('leaderInfos'), 'name', 'leaderName', 'mis'),
        'supplier_name': row.get('supplierName'),
        'recruit_channel': row.get('recruitChannel'),
        'labor_outsourcer': row.get('laborOutsourcer') or None,
        'employee_time': _ms_time(row.get('employeeTime')),
        'entry_time': _ms_time(row.get('entryTime')),
        'resignation_time': _ms_time(row.get('resignationTime')),
        'health_expired_date': _ms_time(row.get('healthExpiredTime'), date_only=True),
        'zombie_days': row.get('zombieDays') if isinstance(row.get('zombieDays'), int) else None,
        'yt_types': _names(row.get('ytTypeList')),
        'experienced': row.get('experienced'),
        'rc_level': row.get('rcLevel'),
        'new_old_rider_tag': row.get('newOldRiderTag'),
        'can_work': row.get('canWork'),
        'work_status_app': row.get('workStatusApp'),
        'qr_dispatch_status': row.get('qrDispatchStatus'),
        'trans_site_status': row.get('transSiteStatus'),
        'trans_site_target': row.get('transSiteTarget'),
        'wallet_id': row.get('walletId'),
        'wallet_status': row.get('walletStatus'),
        'wallet_bind_card_status': row.get('walletBindCardStatus'),
        'fire_eye': row.get('fireEye'),
        'leader_label': row.get('leaderLabel'),
        'uid': row.get('uid'),
        'avatar_url': row.get('imgUrl') or image.get('avatarImg') or None,
        'identity_front_url': image.get('identityFrontImg') or None,
        'identity_back_url': image.get('identityBackImg') or None,
        'hold_identity_front_url': image.get('holdIdentityFrontImg') or None,
        'hold_identity_back_url': image.get('holdIdentityBackImg') or None,
        'health_identity_url': image.get('healthIdentityUrl') or None,
        'extend_images': _names(image.get('extendImages')),
        'ctime': _ms_time(row.get('ctime')),
        'utime': _ms_time(row.get('utime')),
    }
    return [
        _numeric_code(values.get(code)) if code not in ARCHIVE_TEXT_CODES else values.get(code)
        for code, _ in COLUMNS
    ]


def _numeric_code(value):
    """状态/编号类字段：纯数字文本转数值，其余原样。"""
    if isinstance(value, str):
        text = value.strip()
        if re.fullmatch(r'-?\d{1,15}', text):
            return int(text)
    return value


def write_archive_workbook(records, target, cancelled=None):
    """微软雅黑 10、居中、自适应列宽、冻结首行、表头浅橙底色；口径与参考样表一致。"""
    if not records:
        raise LighthouseError('账号内没有可导出的骑手档案')
    if cancelled is not None and cancelled.is_set():
        raise LighthouseError('骑手档案已取消')
    target = Path(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name('.rider_archive_' + uuid.uuid4().hex + '.xlsx')
    header = [name for _, name in COLUMNS]
    widths = [display_width(name) for name in header]
    for values in records:
        for index, value in enumerate(values):
            widths[index] = max(widths[index], display_width(value))
    workbook = Workbook(write_only=True)
    sheet = workbook.create_sheet('骑手档案')
    prepared_write_only_rows(sheet)
    sheet.freeze_panes = 'A2'
    apply_style = style_applier(sheet, font=DAILY_FONT, alignment=DAILY_CENTER)
    for index, width in enumerate(widths, 1):
        sheet.column_dimensions[get_column_letter(index)].width = column_width(width)
    formats = ['0' if code == 'wallet_id' else None for code, _ in COLUMNS]

    def cells(values, fill=None):
        result = []
        for index, value in enumerate(values):
            cell = WriteOnlyCell(sheet, value=value)
            if isinstance(value, str):
                cell.data_type = 's'
            apply_style(cell)
            if fill is not None:
                cell.fill = fill
            if formats[index]:
                cell.number_format = formats[index]
            result.append(cell)
        return result

    saved = False
    try:
        sheet.append(cells(header, DAILY_HEADER_FILL))
        for values in records:
            if cancelled is not None and cancelled.is_set():
                raise LighthouseError('骑手档案已取消')
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
    return {'rows': len(records), 'columns': len(COLUMNS)}


def generate_rider_archive(directory, log=None, cancelled=None,
                           supplier_id=xiaoxiang_lighthouse.SUPPLIER_ID):
    """导出全部站点骑手档案快照（明文手机号/身份证），返回工作簿路径。"""
    title = '骑手档案'
    log = log or (lambda message, *args, **kwargs: None)
    try:
        state = xiaoxiang_lighthouse.load_state()
    except LighthouseError as exc:
        from xiaoxiang_source_auth import AUTH
        AUTH.invalidate()
        raise BillCollectionError('小象灯塔会话不可用（{}），请先在系统通道完成小象灯塔认证'.format(exc)) from None
    if state is None:
        from xiaoxiang_source_auth import AUTH
        AUTH.invalidate()
        raise BillCollectionError('尚未保存小象灯塔会话，请先在系统通道完成小象灯塔认证')
    operator = operator_mis(state)
    if cancelled is not None and cancelled.is_set():
        raise LighthouseError('{}已取消'.format(title))
    session = xiaoxiang_lighthouse.session_from_state(state)
    session.headers.update({'Origin': xiaoxiang_lighthouse.BASE,
                            'Referer': xiaoxiang_lighthouse.BASE + '/riders/list.html'})
    log('[下载] 正在查询小象灯塔{}（全部站点当前快照）'.format(title))
    try:
        rows = query_rider_rows(session, supplier_id, operator)
        log('[进度] 骑手 {} 人'.format(len(rows)))
        attr_names = query_attr_names(session, supplier_id, operator)
        ids = [row['id'] for row in rows if isinstance(row.get('id'), int)]
        sens = query_sens_infos(session, ids, supplier_id, operator)
        log('[进度] 明文联系方式 {} 人'.format(len(sens)))
    except SessionExpired:
        from xiaoxiang_source_auth import AUTH
        AUTH.invalidate()
        raise
    finally:
        session.close()
    if cancelled is not None and cancelled.is_set():
        raise LighthouseError('{}已取消'.format(title))
    records = [rider_row_values(row, sens.get(row.get('id')), attr_names) for row in rows]
    snapshot = datetime.now(BEIJING).date()
    target = Path(directory) / '灯塔骑手档案{}.xlsx'.format(snapshot.strftime('%m%d'))
    info = write_archive_workbook(records, target, cancelled)
    log('[校验] {}：{} 行 / {} 列'.format(title, info['rows'], info['columns']))
    return target
