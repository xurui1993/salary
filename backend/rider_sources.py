"""Download rider source documents without calculating or changing payroll."""

import asyncio
import csv
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import re
import threading
import time
from urllib.parse import parse_qs, urlparse
import uuid
import zipfile

from openpyxl import load_workbook

from fengshen_bill import BillCollectionError, BillPageCollector, atomic_json, check_response_payload, safe_operation_failure, validate_bill_file
from parttime_source import COLLECTION_LOCK, MAX_FILE_BYTES, SourceError, identifier, label, owned_upload, parse_date, read_template, source_files

PAGES = {
    'rider_info': 'https://aeolus.ele.me/?targetId=61068#/humanResource/staffManagement/index',
    'rider_detail': 'https://aeolus.ele.me/?targetId=55644#/knight/data-center/detail',
    'receive_account': 'https://aeolus.ele.me/?targetId=58964#/payment/receive-account',
}
NAMES = {'rider_info':'骑手信息', 'rider_detail':'骑手数据明细', 'receive_account':'收薪账户'}
QUERIES = {
    'rider_info':'https://app2-edu.ele.me/kunkka-svr/ehr/staff/knight/list',
    'rider_detail':'https://httpizza.ele.me/lpd_soc.dashboard/apollo/carrier_driver/analysis/index',
    'receive_account':'https://httpizza.ele.me/lpd.meepo.mgmt/payment/queryReceiveAccount',
}
DETAIL_EXPORT = 'https://httpizza.ele.me/lpd_soc.dashboard/apollo/carrier_driver/analysis/asyncExport'
DETAIL_LIST_QUERY = 'https://httpizza.ele.me/lpd_soc.dashboard/apollo/v1.0/export/list/page'
TEAMS_URL = 'https://httpizza.ele.me/xtop/xtop.lpd.intelligentConfig.getTeamsAll/1.0'
EXPORT_VERIFICATION_CHECK = 'https://app2-edu.ele.me/kunkka-svr/exportStaff/needCheck'
HEADERS = {
    'rider_info': {'骑手ID','姓名','部门','身份证','状态'},
    'rider_detail': {'日期','骑手ID','团队ID','团队名称','有效完成单'},
    'receive_account': {'团队ID','团队名称','骑手ID','收款方式','收款账户','收款账户姓名','收款账户身份证'},
}
DOWNLOAD_ORDER = ('rider_detail', 'receive_account', 'rider_info')


def detail_task_id(payload):
    check_response_payload(payload)
    data = payload.get('data', payload.get('result'))
    if isinstance(data, dict):
        if set(data) == {'code', 'message'} and type(data['code']) is int and data['code'] == 1 and isinstance(data['message'], str):
            return None
        values = [data[key] for key in ('taskId', 'exportId', 'id') if key in data]
        if len(values) != 1:
            raise SourceError('骑手明细导出任务编号无法唯一确认；不重复导出')
        data = values[0]
    return source_id(data)


def unpack_detail_archive(path, plan, teams):
    path = Path(path)
    parts = path.with_name(path.stem + '_parts')
    merged = path.with_suffix('.csv')
    if path.stat().st_size > MAX_FILE_BYTES:
        raise SourceError('骑手明细压缩包超过大小限制')
    with zipfile.ZipFile(path) as archive:
        entries = [entry for entry in archive.infolist() if not entry.is_dir()]
        if not entries or len(entries) > 2000 or sum(entry.file_size for entry in entries) > MAX_FILE_BYTES:
            raise SourceError('骑手明细压缩包为空或解压大小超过限制')
        names = set()
        for entry in entries:
            name = entry.filename.replace('\\', '/')
            relative = Path(name)
            if (relative.is_absolute() or '..' in relative.parts or ':' in name or name in names
                    or relative.suffix.lower() not in ('.csv', '.xlsx')
                    or (entry.external_attr >> 16) & 0o170000 == 0o120000):
                raise SourceError('骑手明细压缩包包含不安全路径或未知文件')
            names.add(name)
        parts.mkdir()
        header = None
        total = 0
        with merged.open('w', encoding='utf-8-sig', newline='') as output:
            writer = csv.writer(output)
            for index, entry in enumerate(entries):
                member = parts / (str(index) + Path(entry.filename).suffix.lower())
                with archive.open(entry) as source, member.open('wb') as target:
                    for chunk in iter(lambda: source.read(65536), b''):
                        target.write(chunk)
                total += validate_document(member, 'rider_detail', plan, teams)['rows']
                book = None
                try:
                    if member.suffix == '.xlsx':
                        book = load_workbook(member, read_only=True, data_only=True)
                        book.worksheets[0].reset_dimensions()
                        rows = book.worksheets[0].iter_rows(values_only=True)
                        current = [label(value) for value in next(rows)]
                        if header is None:
                            header = current
                            writer.writerow(header)
                        elif current != header:
                            raise SourceError('骑手明细压缩包内表头不一致')
                        writer.writerows(rows)
                    else:
                        with member.open(encoding='utf-8-sig', newline='') as stream:
                            rows = csv.reader(stream)
                            current = [label(value) for value in next(rows)]
                            if header is None:
                                header = current
                                writer.writerow(header)
                            elif current != header:
                                raise SourceError('骑手明细压缩包内表头不一致')
                            writer.writerows(rows)
                finally:
                    if book:
                        book.close()
    info = validate_document(merged, 'rider_detail', plan, teams)
    if info['rows'] != total:
        raise SourceError('骑手明细解压合并记录数不一致')
    info.update(original_archive=path.name, archive_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
                archive_members=len(entries))
    return merged, info


def source_id(value):
    if isinstance(value, (int, float)) and not isinstance(value, bool) and abs(value) >= 10 ** 15:
        raise SourceError('资料编号存在精度风险，请核对平台文本编号')
    result = identifier(value)
    if not re.fullmatch(r'\d{1,20}', result):
        raise SourceError('资料编号缺失或包含非十进制内容')
    return result


def inspect_template(folder):
    templates = [p for p in source_files(folder) if 'template' in p.name.lower()]
    if len(templates) != 1 or templates[0].suffix.lower() != '.xlsx':
        raise SourceError('下载骑手资料需上传一个且仅一个 .xlsx template')
    return read_template(templates[0])


def target_teams(payload, agency_id):
    check_response_payload(payload)
    records = payload.get('result', {}).get('data')
    if not isinstance(records, list) or any(not isinstance(row, dict) for row in records):
        raise SourceError('站点归属接口结构变化，不能确认目标城市全部站点')
    result = {}
    seen = set()
    for row in records:
        tid = source_id(row.get('id'))
        if not tid or tid in seen:
            raise SourceError('站点编号缺失或重复，停止导出')
        seen.add(tid)
        if source_id(row.get('agencyId')) == agency_id:
            name = label(row.get('team_name'))
            if not name or name in result.values():
                raise SourceError('目标城市站点名称缺失或不唯一')
            result[tid] = name
    if not result:
        raise SourceError('未查到目标物流合作商的站点；未获取不等于无数据')
    return result


def team_agencies(payload):
    check_response_payload(payload)
    records = payload.get('result', {}).get('data')
    if not isinstance(records, list):
        raise SourceError('站点归属接口结构变化')
    result = {}
    for row in records:
        if not isinstance(row, dict):
            raise SourceError('站点归属接口结构变化')
        tid = source_id(row.get('id'))
        if tid in result:
            raise SourceError('站点编号重复，停止导出')
        result[tid] = source_id(row.get('agencyId'))
    return result


def query_scope(kind, url, plan):
    query = parse_qs(urlparse(url).query, keep_blank_values=True)
    allowed = {'pageIndex','pageSize'} if kind != 'rider_detail' else {'pageNum','pageSize','startAt','endAt'}
    if kind == 'receive_account':
        allowed.add('month')
        if query.get('month') != [plan.month]:
            return False
    elif kind == 'rider_detail':
        if query.get('startAt') != [plan.start] or query.get('endAt') != [plan.end]:
            return False
    return all(key in allowed or values == [''] for key, values in query.items())


def detail_export_scope(payload, plan, teams):
    if not isinstance(payload, dict) or set(payload) != {'teamIds','startAt','endAt','exportType','fields'}:
        return False
    ids = payload.get('teamIds')
    if not isinstance(ids, list) or any(isinstance(tid, bool) for tid in ids):
        return False
    return (len(ids) == len(teams) and {str(tid) for tid in ids} == set(teams)
            and payload['startAt'] == plan.start and payload['endAt'] == plan.end
            and type(payload['exportType']) is int and payload['exportType'] == 2
            and isinstance(payload['fields'], list) and bool(payload['fields'])
            and all(isinstance(field, str) for field in payload['fields']))


def validate_document(path, kind, plan, teams):
    path = Path(path)
    size = path.stat().st_size
    if size == 0 or size > MAX_FILE_BYTES:
        raise SourceError('下载资料为空或超过大小限制')
    workbook = stream = None
    try:
        if path.suffix.lower() == '.xlsx':
            info = validate_bill_file(path)
            if info['format'] != 'xlsx':
                raise SourceError('下载资料不是 XLSX 工作簿')
            workbook = load_workbook(path, read_only=True, data_only=True)
            if len(workbook.worksheets) != 1:
                raise SourceError('资料子表数量发生变化，需核对导出结构')
            sheet = workbook.worksheets[0]
            sheet.reset_dimensions()
            rows = iter(sheet.iter_rows(values_only=True))
        elif path.suffix.lower() == '.csv':
            stream = path.open(encoding='utf-8-sig', newline='')
            rows = iter(csv.reader(stream))
        else:
            raise SourceError('资料格式必须为已确认的 XLSX 或 UTF-8 CSV')
        headers = [label(value) for value in next(rows, ())]
        if not HEADERS[kind].issubset(headers) or any(not h for h in headers) or len(set(headers)) != len(headers):
            raise SourceError(NAMES[kind] + '缺少约定表头或表头重复')
        count = masked = blank = non_rider = 0
        team_ids = set()
        department_ids = {name:tid for tid,name in teams.items()}
        first = last = None
        for row in rows:
            if not any(value is not None and str(value).strip() for value in row):
                continue
            if len(row) != len(headers):
                raise SourceError(NAMES[kind] + '行列结构损坏')
            values = dict(zip(headers, row))
            if kind == 'rider_info' and not identifier(values['骑手ID']) and label(values.get('职位')) in ('站长', '副站长', '队长'):
                non_rider += 1
            else:
                source_id(values['骑手ID'])
            if kind == 'rider_info':
                department = label(values['部门'])
                if department not in department_ids:
                    raise SourceError('骑手信息包含非目标城市站点，已停止')
                team_ids.add(department_ids[department])
                identity = str(values['身份证'] or '').strip()
            elif kind == 'receive_account':
                # Preserve the complete export for the selected platform city.
                # Station directories can omit historical teams or renamed teams.
                tid = str(values['团队ID'] or '').strip()
                if tid:
                    team_ids.add(tid)
                identity = str(values.get('收款账户身份证') or '').strip()
            else:
                tid = source_id(values['团队ID'])
                if tid not in teams or (kind != 'rider_detail' and label(values['团队名称']) != teams[tid]):
                    raise SourceError(NAMES[kind] + '包含非目标城市站点，已停止')
                team_ids.add(tid)
                identity = str(values.get('收款账户身份证') or '').strip() if kind == 'receive_account' else None
            if identity is not None:
                blank += not bool(identity)
                masked += bool(re.search(r'[*＊]', identity))
            if kind == 'rider_detail':
                day = parse_date(values['日期'], workbook.epoch if workbook else None).isoformat()
                if not plan.start <= day <= plan.end:
                    raise SourceError('骑手每日明细日期超出 template 范围')
                first = min(first or day, day)
                last = max(last or day, day)
            count += 1
        digest = hashlib.sha256()
        with path.open('rb') as source:
            for chunk in iter(lambda: source.read(65536), b''):
                digest.update(chunk)
        return {'path':path.name, 'rows':count, 'bytes':size, 'sha256':digest.hexdigest(),
                'status':'empty' if count == 0 else 'validated', 'format':path.suffix[1:],
                'identity_masked':masked, 'identity_blank':blank, 'date_min':first, 'date_max':last,
                'team_count':len(team_ids), 'non_rider_rows':non_rider, 'filtered_by_applicants':False}
    except (SourceError, BillCollectionError):
        raise
    except Exception:
        raise SourceError(NAMES[kind] + '无法解析；原文件已留存') from None
    finally:
        if workbook:
            workbook.close()
        if stream:
            stream.close()


def source_profile(plan):
    base = json.loads(Path(__file__).with_name('fengshen_rider_bill.profile.json').read_text(encoding='utf-8'))
    keys = ('notice_dismiss_button','agency_context','city_trigger','city_popup','city_group','city_group_label',
            'city_option','city_selected_option','city_confirm','city_close')
    return {**{key:base[key] for key in keys}, 'expected_agency_id':plan.agency_id,
            'selection_mode':'target_city', 'content_frame':"iframe[src^='https://artemis.faas.ele.me/']:visible"}


class RiderSourceCollector(BillPageCollector):
    profile_validator = staticmethod(lambda profile, **kwargs: profile)

    def __init__(self, page, plan, output, log, cancelled, auth=None, timeout=900, human_timeout=1800,
                 reveal=None, conceal=lambda page: None, detail_target_city_only=False):
        if type(detail_target_city_only) is not bool:
            raise SourceError('骑手明细城市范围选项无效')
        super().__init__(page, source_profile(plan), output, log, timeout=timeout, auth=auth)
        self.plan, self.cancelled = plan, cancelled
        self.detail_target_city_only = detail_target_city_only
        self.human_timeout = human_timeout
        self.reveal = reveal or (lambda page: page.bring_to_front())
        self.conceal = conceal

    def checkpoint(self):
        if self.cancelled.is_set():
            raise SourceError('骑手资料下载已取消；已下载原文件保留')
        if self.page.is_closed():
            raise SourceError('专用 Edge 被关闭，骑手资料下载未完成')

    def _visible_one(self, locator, description):
        self.checkpoint()
        locator.first.wait_for(state='visible', timeout=30000)
        return self._one(locator, description)

    def _frame(self):
        self._content()
        route = urlparse(self.page_url).fragment
        frames = [f for f in self.page.frames if urlparse(f.url).hostname == 'artemis.faas.ele.me'
                  and f.frame_element().is_visible() and urlparse(f.url).fragment == route]
        if len(frames) != 1:
            raise SourceError('骑手资料内嵌页面与目标页面不一致')
        return frames[0]

    @staticmethod
    def _verification_visible(frame):
        return bool(frame.locator('.el-dialog:visible:has(.el-dialog__title:text-is("手机验证"))').count())

    @staticmethod
    def _frame_navigation_error(exc):
        # Only known Playwright frame/context lifecycle errors are recoverable.
        # A selector error, generic timeout, or a closed page must still fail.
        from playwright.sync_api import Error
        message = str(exc).splitlines()[0] if str(exc) else ''
        return isinstance(exc, Error) and any(marker in message for marker in (
            'Execution context was destroyed', 'Frame was detached',
            'Frame has been detached', 'Execution context is not available in detached frame',
            'Cannot find context with specified id',
        ))

    @staticmethod
    def _rider_info_frame_target(frame):
        parsed = urlparse(frame.url)
        return (parsed.scheme == 'https' and parsed.hostname == 'artemis.faas.ele.me'
                and not parsed.username and not parsed.password and parsed.port in (None, 443)
                and parsed.fragment == urlparse(PAGES['rider_info']).fragment and not frame.is_detached())

    def _waiting_rider_info_frame(self):
        """Read the current frame tree; never navigate or restart an export."""
        self.checkpoint()
        outer = urlparse(self.page.url)
        route = urlparse(PAGES['rider_info']).fragment
        if (outer.scheme != 'https' or outer.hostname != 'aeolus.ele.me'
                or outer.username or outer.password or outer.port not in (None, 443)
                or outer.fragment != route):
            return None
        matches = []
        for candidate in self.page.frames:
            if not self._rider_info_frame_target(candidate):
                continue
            try:
                if candidate.frame_element().is_visible():
                    matches.append(candidate)
            except Exception as exc:
                self.checkpoint()
                if not self._frame_navigation_error(exc):
                    raise
        return matches[0] if len(matches) == 1 else None

    def _query_matches(self, kind, response):
        return (response.url.split('?')[0] == QUERIES[kind] and response.request.method == 'GET'
                and query_scope(kind, response.url, self.plan))

    @staticmethod
    def _query_payload(kind, response):
        if not response.ok:
            raise SourceError(f'{NAMES[kind]}查询接口失败（HTTP {response.status}）；未提交导出')
        payload = response.json()
        check_response_payload(payload)
        return payload

    def _wait_query_access(self, kind, frame, status):
        responses = []
        def observed(response):
            if self._query_matches(kind, response):
                responses.append(response)
        self.page.on('response', observed)
        try:
            self.reveal(self.page)
            self.log(f'[等待权限] {NAMES[kind]}查询返回 HTTP {status}，尚未提交导出；不代表验证码超时。'
                     f'专用 Edge 保持打开，最长等待 {self.human_timeout // 60} 分钟；'
                     '请检查官方权限或登录提示，完成验证后点击“查询”。程序不会发送短信')
            deadline = time.monotonic() + self.human_timeout
            while time.monotonic() < deadline:
                self.checkpoint()
                while responses:
                    response = responses.pop(0)
                    if response.status in (401, 403):
                        continue
                    self._query_payload(kind, response)
                    # Manual verification may navigate or switch agencies. Revalidate before exporting.
                    if urlparse(self.page.url).fragment != urlparse(self.page_url).fragment:
                        raise SourceError('查询恢复后页面已变化，未提交导出')
                    self._check_agency_context()
                    self.log('[权限恢复] 查询已成功，重新核对目标城市及全部状态；未重复导出')
                    return self._query(kind, self._frame(), recover=False)
                self.page.wait_for_timeout(250)
            raise SourceError(f'{NAMES[kind]}查询权限等待超时，仍未确认可访问；未提交导出。请核对官方权限或登录提示')
        finally:
            self.page.remove_listener('response', observed)

    def _staff_status_diagnostic(self, status, stage, **flags):
        previous = getattr(self, 'staff_status_selection', {})
        result = {'stage': stage, 'all_option_clicked': previous.get('all_option_clicked') is True,
                  'menu_closed': previous.get('menu_closed') is True,
                  'strict_query_confirmed': previous.get('strict_query_confirmed') is True}
        result.update(flags)
        try:
            value = status.input_value()
            result['display'] = ('all' if value == '全部' else 'empty' if value == ''
                                 else 'known_filtered' if value in ('在职', '离职', '停工', '待入职') else 'other')
        except Exception:
            result['display'] = 'unavailable'
        try:
            placeholder = status.get_attribute('placeholder')
            result['placeholder'] = ('all' if placeholder == '全部' else 'select' if placeholder in ('请选择', '请选择在职状态')
                                     else 'empty' if placeholder in ('', None) else 'other')
        except Exception:
            result['placeholder'] = 'unavailable'
        self.staff_status_selection = result
        try:
            directory = getattr(self, 'output_dir', None)
            if isinstance(directory, Path) and directory.is_dir():
                atomic_json(directory / 'staff_status_selection.json', result)
        except Exception:
            pass

    def _query(self, kind, frame, recover=True):
        if kind == 'rider_info':
            frame.get_by_role('button', name='重置', exact=True).click()
            status = frame.locator('.el-form-item:has(label:text-is("在职状态：")) input')
            self.staff_status_selection = {}
            self._staff_status_diagnostic(status, 'selecting')
            status.click()
            self._visible_one(frame.locator('.el-select-dropdown:visible li > span:text-is("全部")'), '全部在职状态').click()
            self._staff_status_diagnostic(status, 'option_clicked', all_option_clicked=True)
            # Element may display an empty label or update it on the next UI
            # tick. Require the menu to close, then prove the actual query has
            # no status/person filters instead of trusting its display label.
            frame.locator('.el-select-dropdown:visible').wait_for(state='hidden', timeout=5000)
            self._staff_status_diagnostic(status, 'menu_closed', menu_closed=True)
        elif kind == 'rider_detail':
            team = frame.locator('.el-form-item:has(label:text-is("团队")) input')
            if team.count() and team.input_value() != '全部':
                raise SourceError('骑手明细团队筛选不是全部')
            inputs = frame.locator('input.el-range-input')
            inputs.first.wait_for(state='visible', timeout=30000)
            if inputs.count() != 2:
                raise SourceError('骑手明细日期控件无法识别')
            inputs.nth(0).fill(self.plan.start)
            inputs.nth(1).fill(self.plan.end)
            inputs.nth(1).press('Enter')
            # Element's range picker can retain its popover after Enter and
            # intercept the query button. Commit blur before dismissing it;
            # Escape on an active date input can revert its uncommitted value.
            # The response matcher still requires the exact requested dates.
            inputs.nth(1).press('Tab')
            frame.get_by_role('button', name='查询', exact=True).press('Escape')
            actual = (inputs.nth(0).input_value(), inputs.nth(1).input_value())
            if actual != (self.plan.start, self.plan.end):
                if all(isinstance(value, str) and re.fullmatch(r'\d{4}-\d{2}-\d{2}', value) for value in actual):
                    raise SourceError(f'平台未接受所选明细日期，页面读回 {actual[0]} 至 {actual[1]}；尚未查询或导出')
                raise SourceError('骑手明细日期输入未正确提交，尚未查询或导出')
        else:
            frame.get_by_role('button', name='重置', exact=True).click()
            month = frame.locator('input[placeholder="请选择月份"]')
            month.fill(self.plan.month)
            month.press('Enter')
        try:
            with self.page.expect_response(lambda response:self._query_matches(kind, response), timeout=30000) as pending:
                frame.get_by_role('button', name='查询', exact=True).click()
        except Exception:
            if kind == 'rider_info':
                self._staff_status_diagnostic(status, 'query_unconfirmed', strict_query_confirmed=False)
            raise
        response = pending.value
        if kind == 'rider_info' and not self._query_matches(kind, response):
            self._staff_status_diagnostic(status, 'query_scope_rejected', strict_query_confirmed=False)
            raise SourceError('骑手信息实际查询未确认全部状态和全部人员；未提交导出')
        if kind == 'rider_info' and recover and response.status in (401, 403):
            return self._wait_query_access(kind, frame, response.status)
        payload = self._query_payload(kind, response)
        if kind == 'rider_info':
            self._staff_status_diagnostic(status, 'query_confirmed', strict_query_confirmed=True)
        return payload

    def _wait_download(self, kind, frame, downloads, rejection, verification_errors, requires_verification=False):
        deadline = time.monotonic() + self.timeout
        human_deadline = time.monotonic() + self.human_timeout if requires_verification else None
        verification_notified = False
        page_wait_notified = False
        while not downloads:
            self.checkpoint()
            if rejection:
                raise SourceError(rejection[0])
            verification_visible = False
            if kind == 'rider_info':
                # A retained Frame can navigate to login/about:blank without
                # raising from locator.count(). Its URL/attached state is also
                # proof that the old verification surface must not be reused.
                if frame is not None and not self._rider_info_frame_target(frame):
                    frame = None
                if frame is None:
                    frame = self._waiting_rider_info_frame()
                if frame is not None:
                    try:
                        verification_visible = self._verification_visible(frame)
                    except Exception as exc:
                        self.checkpoint()
                        if not self._frame_navigation_error(exc):
                            raise
                        frame = None
                if frame is None and not page_wait_notified:
                    self.reveal(self.page)
                    self.log('[等待页面] 骑手信息内嵌页面正在跳转或暂不可用，继续等待本次原下载。'
                             '如已离开，请手动返回原骑手信息页面；不要再次点击导出或发送短信')
                    page_wait_notified = True
            if downloads:
                break
            if verification_visible:
                if human_deadline is None:
                    human_deadline = time.monotonic() + self.human_timeout
                if not verification_notified:
                    self.reveal(self.page)
                    self.log(f'[等待验证] 请在专用 Edge 官方手机验证弹窗自行输入验证码并提交；'
                             f'窗口最长保留 {self.human_timeout // 60} 分钟，完成后继续原下载，不自动重发短信')
                    verification_notified = True
            if verification_errors:
                if human_deadline is None:
                    raise SourceError(verification_errors[0])
                self.log('[验证未通过] 官方验证请求未通过，请检查 Edge 中的提示并自行纠正；'
                         '窗口继续保留，不自动重发短信或重新导出')
                verification_errors.clear()
            if time.monotonic() >= (human_deadline if human_deadline is not None else deadline):
                if human_deadline is not None:
                    raise SourceError('骑手信息人工验证等待超时；未获取原文件，导出状态未知，不自动重发短信或重新导出')
                raise SourceError(NAMES[kind] + '未获取文件，停止下载；任务状态未知，不自动重新导出')
            self.page.wait_for_timeout(250)
        if rejection:
            raise SourceError(rejection[0])
        verification_errors.clear()

    def _wait_detail_download(self, frame, downloads, rejection):
        if downloads:
            return
        self._wait_detail_submission(rejection)
        button = frame.get_by_role('button', name='去下载', exact=True)
        self._visible_one(button, '进入异步导出列表').click()
        self._poll_detail_task(downloads, rejection)

    def _wait_detail_submission(self, rejection):
        deadline = time.monotonic() + min(self.timeout, 90)
        self.log('[异步导出] 等待官方提交回执；暂不跳转，不重复提交')
        while not getattr(self, 'detail_acknowledged', False):
            self.checkpoint()
            if rejection:
                raise SourceError(rejection[0])
            if time.monotonic() >= deadline:
                raise SourceError('骑手明细提交回执等待超时；任务状态未知，未重新导出，请查看导出列表及提交清单')
            self.page.wait_for_timeout(250)
        if rejection:
            raise SourceError(rejection[0])

    def _detail_list_frame(self):
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            self.checkpoint()
            frames = [current for current in self.page.frames
                      if urlparse(current.url).hostname == 'lpd-service-center.faas.ele.me'
                      and urlparse(current.url).fragment == '/export-list'
                      and current.frame_element().is_visible()]
            if len(frames) == 1:
                frame = frames[0]
                frame.locator('tbody tr, .el-table__empty-text').first.wait_for(state='visible', timeout=30000)
                return frame
            self.page.wait_for_timeout(250)
        raise SourceError('骑手明细导出列表未加载，未确认任务状态')

    def _capture_detail_baseline(self):
        self.source_stage = 'baseline_open_list'
        with self.page.context.expect_event('response', predicate=lambda response: response.url.split('?')[0] == DETAIL_LIST_QUERY,
                                            timeout=30000) as queried:
            self.page.goto('https://aeolus.ele.me/?targetId=55404#/export-list', wait_until='domcontentloaded', timeout=60000)
        response = queried.value
        if not response.ok:
            raise SourceError('导出列表查询失败；尚未提交新任务')
        check_response_payload(response.json())
        self.page.wait_for_timeout(250)
        self.source_stage = 'baseline_wait_rows'
        frame = self._detail_list_frame()
        self.detail_baseline = set()
        for row in frame.locator('tbody tr').all():
            match = re.search(r'骑手\s*数据明细\.(\d+)\.', row.inner_text())
            if match:
                self.detail_baseline.add(match.group(1))
        self.source_stage = 'baseline_return_detail'
        self.page.goto(self.page_url, wait_until='domcontentloaded', timeout=60000)
        self.source_stage = 'baseline_check_city'
        self._check_agency_context()

    def _poll_detail_task(self, downloads, rejection):
        task_id = getattr(self, 'detail_task', None)
        if (not task_id and not getattr(self, 'detail_acknowledged', False)) or rejection:
            raise SourceError('骑手明细任务编号未确认；已提交任务，不重复导出')
        deadline = time.monotonic() + max(self.timeout, 1200)
        clicked = False
        self.log(f'[异步导出] 任务 {task_id or "已受理"}，等待导出列表完成；不会重复提交')
        while not downloads:
            self.checkpoint()
            if rejection:
                raise SourceError(rejection[0])
            if time.monotonic() >= deadline:
                raise SourceError(f'骑手明细任务 {task_id} 等待超时；任务保留在导出列表，不自动重新导出')
            if not clicked:
                candidates = []
                for current in [self._detail_list_frame()]:
                    if (urlparse(current.url).hostname != 'lpd-service-center.faas.ele.me'
                            or urlparse(current.url).fragment != '/export-list'):
                        continue
                    for row in current.locator('tbody tr').all():
                        text = re.sub(r'\s+', '', row.inner_text())
                        prefix = f'{self.plan.start}-{self.plan.end}.骑手数据明细.'
                        match = re.search(re.escape(prefix) + r'(\d+)\.', text)
                        if not match or not row.is_visible():
                            continue
                        if task_id and match.group(1) != task_id:
                            continue
                        if not task_id:
                            if match.group(1) in self.detail_baseline:
                                continue
                            created = datetime.strptime(row.locator('td').nth(2).inner_text().strip(), '%Y-%m-%d %H:%M:%S')
                            if created < self.detail_submitted_at - timedelta(seconds=10):
                                continue
                        if match:
                            candidates.append((current, row, text))
                if len(candidates) > 1:
                    raise SourceError('骑手明细导出任务行不唯一，未下载其他任务')
                if candidates:
                    current, row, text = candidates[0]
                    if not task_id:
                        task_id = re.search(re.escape(prefix) + r'(\d+)\.', text).group(1)
                        self.detail_task = task_id
                        atomic_json(self.output_dir / 'detail_task.json', {'task_id': task_id,
                                    'start': self.plan.start, 'end': self.plan.end,
                                    'selected_team_ids': sorted(self.detail_selected_teams),
                                    'submitted_at': self.detail_submitted_at.isoformat()})
                        self.log(f'[异步导出] 已关联本次新增任务 {task_id}')
                    if '失败' in text:
                        raise SourceError(f'骑手明细任务 {task_id} 导出失败')
                    if '导出完成' in text:
                        link = row.get_by_text('下载文件', exact=True)
                        self._visible_one(link, '本次骑手明细任务下载').click()
                        clicked = True
                        self.log('[异步导出] 本次任务已完成，等待压缩包下载')
                if not clicked:
                    self.page.wait_for_timeout(10000)
                    self.page.reload(wait_until='domcontentloaded', timeout=60000)
            else:
                self.page.wait_for_timeout(250)

    def _select_teams(self, frame, teams, all_available=False):
        dialog = self._visible_one(frame.locator('.el-dialog:visible'), '导出站点弹窗')
        panels = dialog.locator('.el-transfer-panel')
        panels.nth(1).wait_for(state='visible', timeout=30000)
        if panels.count() != 2:
            raise SourceError('导出站点穿梭框结构变化')
        left, right = panels.nth(0), panels.nth(1)
        left.locator('.el-transfer-panel__item').first.wait_for(state='visible', timeout=30000)
        def ids(panel):
            return panel.locator('.el-transfer-panel__item input').evaluate_all('nodes=>nodes.map(el=>el.value)')
        available = ids(left)
        if not available or len(available) != len(set(available)) or (not all_available and not set(teams).issubset(available)) or ids(right):
            raise SourceError('导出站点缺失、重复或存在残留选择')
        if all_available:
            selected = {source_id(tid): teams.get(str(tid), '') for tid in available}
            teams.clear()
            teams.update(selected)
            self._one(left.locator('.el-transfer-panel__header .el-checkbox'), '全选可选站点').click()
        else:
            for tid in sorted(teams):
                self.checkpoint()
                left.locator(f'.el-transfer-panel__item:has(input[value="{tid}"])').click()
        first_team = sorted(teams)[0]
        self._one(dialog.locator('.el-transfer__buttons button:has(i.el-icon-arrow-right)'), '加入已选站点').click()
        right.locator(f'.el-transfer-panel__item:has(input[value="{first_team}"])').wait_for(state='visible', timeout=30000)
        if set(ids(right)) != set(teams) or len(ids(right)) != len(teams):
            raise SourceError('已选站点不等于目标城市全部站点')
        if all_available:
            if ids(left):
                raise SourceError('仍有可选站点未加入导出，已停止')
            self.log(f'[站点] 已全选全部 {len(teams)} 个可选站点；不按目录城市或站点名称筛选')
        else:
            self.log(f'[站点] 已选全目标物流合作商 {len(teams)} 个站点；未选其他城市')
        return dialog

    def collect(self, kind):
        self.checkpoint()
        detail_target_city_only = getattr(self, 'detail_target_city_only', False)
        self.source_stage = 'navigate'
        self.page_url = PAGES[kind]
        if self.auth:
            self.auth(self.page_url, self.profile)
        else:
            self.page.goto(self.page_url, wait_until='domcontentloaded', timeout=60000)
        self.source_stage = 'check_city'
        self._check_agency_context()
        if kind == 'rider_detail':
            self._capture_detail_baseline()
        self.source_stage = 'query_frame'
        frame = self._frame()
        self.source_stage = 'query'
        query = self._query(kind, frame)
        self.source_stage = 'query_frame'
        frame = self._frame()
        self.source_stage = 'teams'
        team_payload = None
        if kind != 'receive_account':
            response = self.page.context.request.post(TEAMS_URL, data={}, timeout=30000)
            if not response.ok:
                raise SourceError('站点归属查询失败')
            team_payload = response.json()
        agencies = team_agencies(team_payload) if kind in ('rider_detail', 'rider_info') else {}
        teams = ({} if kind == 'receive_account' or (kind == 'rider_detail' and not detail_target_city_only)
                 else target_teams(team_payload, self.plan.agency_id))
        downloads, rejection, verification_errors = [], [], []
        self.detail_task = None
        self.detail_acknowledged = False
        self.detail_submission = {}
        watched = []
        def export_response(response):
            path = urlparse(response.url).path
            if kind == 'rider_detail' and response.url.split('?')[0] == DETAIL_EXPORT:
                try:
                    self.detail_submission.update(http_status=response.status)
                    if not response.ok:
                        raise SourceError('骑手明细导出提交失败')
                    payload = response.json()
                    self.detail_submission.update(response_fields=sorted(payload) if isinstance(payload, dict) else [],
                                                  response_code=payload.get('code') if isinstance(payload, dict) else None)
                    self.detail_task = detail_task_id(payload)
                    self.detail_acknowledged = True
                    self.detail_submission.update(status='acknowledged', task_id=self.detail_task)
                    atomic_json(self.output_dir / 'detail_task.json', {'task_id': self.detail_task,
                                'start': self.plan.start, 'end': self.plan.end, 'selected_team_ids': sorted(teams)})
                except Exception:
                    self.detail_submission['status'] = 'rejected_or_unknown'
                    rejection.append('骑手明细导出响应未确认任务编号；不会重复提交')
                finally:
                    atomic_json(self.output_dir / 'detail_submission.json', self.detail_submission)
                return
            if kind != 'rider_info' or not path.startswith('/kunkka-svr/exportStaff/'):
                return
            try:
                if not response.ok:
                    raise BillCollectionError('导出验证请求失败')
                check_response_payload(response.json())
            except Exception:
                verification_errors.append('骑手信息导出验证失败；登录查询正常也不代表导出验证有效。请检查官方提示，不自动重发短信或重新导出')
        def downloaded(download):
            downloads.append(download)
        def watch(page):
            page.on('download', downloaded)
            watched.append(page)
        def guard(route):
            try:
                valid = route.request.method == 'POST' and detail_export_scope(route.request.post_data_json, self.plan, teams)
            except Exception:
                valid = False
            if not valid:
                rejection.append('骑手每日明细导出参数不符，未提交任务')
                route.abort()
            else:
                self.detail_submission['request_observed'] = True
                atomic_json(self.output_dir / 'detail_submission.json', self.detail_submission)
                route.continue_()
        for page in self.page.context.pages:
            watch(page)
        self.page.context.on('page', watch)
        self.page.context.on('response', export_response)
        self.page.context.route(DETAIL_EXPORT + '*', guard)
        try:
            requires_verification = False
            self.source_stage = 'export_controls'
            if kind == 'rider_detail':
                self._visible_one(frame.locator('button.el-dropdown-selfdefine:visible'), '明细导出菜单').hover()
                self._visible_one(frame.locator('.el-dropdown-menu:visible :text-is("导出每日明细")'), '导出每日明细').click()
            else:
                frame.get_by_role('button', name='导出', exact=True).click()
            if kind != 'receive_account':
                self.source_stage = 'select_teams'
                dialog = self._select_teams(frame, teams,
                    all_available=kind == 'rider_detail' and not detail_target_city_only)
                if kind == 'rider_detail':
                    self.detail_selected_teams = dict(teams)
                    self.detail_submitted_at = datetime.now(timezone(timedelta(hours=8))).replace(tzinfo=None)
                    self.detail_submission = {'status': 'awaiting_acknowledgement', 'start': self.plan.start,
                                              'end': self.plan.end, 'agency_id': self.plan.agency_id,
                                              'selected_team_ids': sorted(teams),
                                              'existing_task_ids': sorted(self.detail_baseline),
                                              'submitted_at': self.detail_submitted_at.isoformat(),
                                              'request_observed': False}
                    atomic_json(self.output_dir / 'detail_submission.json', self.detail_submission)
                if kind == 'rider_info':
                    check = self.page.context.request.get(EXPORT_VERIFICATION_CHECK, timeout=30000)
                    if not check.ok:
                        raise SourceError('骑手信息导出验证检查失败；未触发短信')
                    payload = check.json()
                    check_response_payload(payload)
                    if type(payload.get('data')) is not bool:
                        raise SourceError('骑手信息导出验证检查结构变化；未触发短信')
                    requires_verification = payload['data']
                if requires_verification:
                    self.reveal(self.page)
                    self.log('[等待验证] 骑手信息导出另需手机验证。请在专用 Edge 点击站点弹窗的“导出”，再自行完成官方验证；程序不自动请求或重发短信')
                else:
                    self.source_stage = 'submit_export'
                    dialog.get_by_role('button', name='导出', exact=True).click()
            self.log('[导出] ' + NAMES[kind] + '等待原文件；不会重复提交')
            self.source_stage = 'wait_file'
            if kind == 'rider_detail':
                self._wait_detail_download(frame, downloads, rejection)
            else:
                self._wait_download(kind, frame, downloads, rejection, verification_errors, requires_verification)
            if len(downloads) != 1 or rejection:
                raise SourceError('原文件下载事件不唯一或导出参数被拒绝')
            download = downloads[0]
            if download.failure():
                raise SourceError(NAMES[kind] + '下载失败')
            self.source_stage = 'validate_file'
            extension = Path(download.suggested_filename).suffix.lower()
            if extension not in ('.xlsx', '.csv') and not (kind == 'rider_detail' and extension == '.zip'):
                raise SourceError('下载文件格式未确认')
            name = f'{NAMES[kind]}_{self.plan.city}_{self.plan.start}_{self.plan.end}{extension}'
            path = self.output_dir / name
            download.save_as(path)
            if extension == '.zip':
                path, info = unpack_detail_archive(path, self.plan, teams)
            else:
                info = validate_document(path, kind, self.plan, teams)
            if kind == 'receive_account':
                total = query.get('data', {}).get('rowcount')
                if type(total) is not int or total < 0 or total != info['rows']:
                    raise SourceError('收薪账户文件行数与本次月份查询总数不一致')
                info['query_total'] = total
                info.update(scope='platform_city', team_validation=False)
            info.update(city=self.plan.city, agency_id=self.plan.agency_id, requested_start=self.plan.start,
                        requested_end=self.plan.end, requested_month=self.plan.month, all_target_teams=True,
                        export_mode='daily' if kind == 'rider_detail' else 'original')
            if kind == 'rider_detail':
                if detail_target_city_only and any(agencies.get(tid) != self.plan.agency_id for tid in teams):
                    raise SourceError('骑手明细站点缺少目标城市归属证明，未发布文件')
                info.update(all_available_teams=not detail_target_city_only, selected_team_ids=sorted(teams),
                            scope='target_city' if detail_target_city_only else 'all_available_teams',
                            task_id=self.detail_task,
                            team_agency_ids={tid: agencies[tid] for tid in teams if tid in agencies})
            elif kind == 'rider_info':
                if any(agencies.get(tid) != self.plan.agency_id for tid in teams):
                    raise SourceError('骑手信息站点缺少目标城市归属证明，未发布文件')
                info.update(scope='target_city', all_available_teams=False, selected_team_ids=sorted(teams),
                            team_agency_ids={tid: agencies[tid] for tid in teams}, snapshot_only=True,
                            time_basis='current_snapshot')
            self.log(f'[完成] {NAMES[kind]}：{info["rows"]} 条；原文件已校验保存')
            if info['non_rider_rows']:
                self.log(f'[提示] 原文件保留 {info["non_rider_rows"]} 条无骑手ID的站长/副站长/队长记录；不会当作骑手绑定')
            if info['identity_masked'] or info['identity_blank']:
                self.log('[提示] 原文件有脱敏或空身份证，原样保留；不能据此生成完整支付绑定')
            self.conceal(self.page)
            return info
        finally:
            self.page.context.unroute(DETAIL_EXPORT + '*', guard)
            self.page.context.remove_listener('page', watch)
            self.page.context.remove_listener('response', export_response)
            for page in watched:
                page.remove_listener('download', downloaded)


def download_sources(folder, owner, log, cancelled, notify=lambda _:None, collector=None, plan=None):
    plan = plan or inspect_template(folder)
    if not COLLECTION_LOCK.acquire(blocking=False):
        raise SourceError('另一项风神采集正在运行，请等待完成')
    run = Path(owner) / ('rider_sources_' + uuid.uuid4().hex)
    manifest = {'plan':asdict(plan), 'status':'running', 'datasets':{}, 'originals_retained':True,
                'payroll_executed':False, 'binding_generated':False, 'filtered_by_applicants':False}
    try:
        run.mkdir()
        atomic_json(run / 'manifest.json', manifest)
        log(f'[计划] {plan.city} / {plan.agency_id} / {plan.start} 至 {plan.end} / 收薪月份 {plan.month}')
        def collect(current):
            for kind in DOWNLOAD_ORDER:
                if cancelled.is_set():
                    raise SourceError('下载已取消')
                manifest['stage'] = kind
                atomic_json(run / 'manifest.json', manifest)
                manifest['datasets'][kind] = current.collect(kind)
                atomic_json(run / 'manifest.json', manifest)
        if collector:
            collect(collector(plan, run, log, cancelled))
        else:
            from fengshen_auth import BROKER, BrowserAuth, open_context, launch_background_edge, reveal_edge, conceal_edge
            from playwright.sync_api import sync_playwright
            with BROKER.operation(Path(owner).name, cancelled, notify), sync_playwright() as pw:
                browser = launch_background_edge(pw)
                try:
                    context = open_context(browser, BROKER)
                    page = context.new_page()
                    conceal_edge(page)
                    auth = BrowserAuth(page, context, BROKER, cancelled, log, reveal=reveal_edge, conceal=conceal_edge)
                    def navigate(url, profile):
                        auth.navigate(url)
                        auth.ensure(url, profile)
                    collect(RiderSourceCollector(page, plan, run, log, cancelled, auth=navigate,
                                                reveal=reveal_edge, conceal=conceal_edge))
                finally:
                    browser.close()
        manifest['status'] = 'success'
        atomic_json(run / 'manifest.json', manifest)
        log(f'[文件] 三份原始资料及校验清单：{run}')
        return run, manifest
    except Exception as exc:
        message = str(exc) if isinstance(exc, BillCollectionError) else '骑手资料下载未完成，请检查网络或页面配置'
        manifest.update(status='error', error=message, failure=safe_operation_failure(exc))
        if run.is_dir():
            atomic_json(run / 'manifest.json', manifest)
            log(f'[诊断] 已下载原文件及失败阶段保留在：{run}')
        raise SourceError(message) from None
    finally:
        COLLECTION_LOCK.release()


async def run_rider_sources(config, workspace):
    import tasks
    cancelled, queue = threading.Event(), asyncio.Queue()
    loop = asyncio.get_running_loop()
    worker = None
    def log(message):
        if not cancelled.is_set():
            loop.call_soon_threadsafe(queue.put_nowait, tasks.create_log_event(message))
    def notify(status):
        if not cancelled.is_set():
            event = 'data: ' + json.dumps({'type':'fengshen_auth','status':status}, ensure_ascii=False) + '\n\n'
            loop.call_soon_threadsafe(queue.put_nowait, event)
    try:
        folder, owner = owned_upload(config.sourcePath, workspace)
        worker = asyncio.create_task(asyncio.to_thread(download_sources, folder, owner, log, cancelled, notify))
        while not worker.done() or not queue.empty():
            try:
                yield await asyncio.wait_for(queue.get(), timeout=0.5)
            except asyncio.TimeoutError:
                yield ': heartbeat\n\n'
        run, manifest = await worker
        yield tasks.create_finish_event('success', '三份骑手资料已下载并校验，未执行核算', str(run),
                                        {'datasets':manifest['datasets'], 'payroll_executed':False})
    except BillCollectionError as exc:
        yield tasks.create_log_event(str(exc), 'ERROR')
        yield tasks.create_finish_event('error', str(exc))
    finally:
        cancelled.set()
        if worker is not None and not worker.done():
            try:
                await asyncio.shield(worker)
            except (Exception, asyncio.CancelledError):
                pass
