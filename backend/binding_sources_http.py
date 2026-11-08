"""Verified official export routes; no browser is used for business exports."""
import hashlib
import json
from pathlib import Path
import time
import zipfile
from collections.abc import Mapping
from urllib.parse import urlencode

import requests

from binding_source_auth import AUTH, SOURCES, client, identity, SourceAuthenticationRequired, SourceProbeUnavailable
from fengshen_bill import BillCollectionError, atomic_json
from shangyi_sources import validate_employees


def authenticated(source, log, cancelled):
    session = None
    try:
        session = client(source)
        identity(source, session)
        return session
    except requests.RequestException:
        if session is not None: session.close()
        raise BillCollectionError(SOURCES[source]['label'] + '连接失败，请检查网络后重试') from None
    except SourceAuthenticationRequired:
        if session is not None: session.close()
    except Exception:
        if session is not None: session.close()
        raise SourceProbeUnavailable('身份接口暂未确认，请检查网络或权限；原会话保留，不会自动打开认证窗口') from None
    log('[认证] 正在复用已保存的浏览器会话；仅在失效时打开登录窗口')
    if AUTH.refresh(source):
        session = None
        try:
            session = client(source)
            identity(source, session)
            log('[认证] 已复用保存的浏览器会话，继续下载')
            return session
        except SourceAuthenticationRequired:
            if session is not None: session.close()
        except Exception:
            if session is not None: session.close()
            raise SourceProbeUnavailable('复用后的身份暂未确认；原会话保留，不会自动打开认证窗口') from None
    if AUTH.status(source)['state'] == 'unknown':
        raise SourceProbeUnavailable('连接暂未确认，请检查网络后重试；不会自动打开认证窗口')
    AUTH.start(source)
    log('[等待登录] 请在下载中心的外部资料认证区域完成' + SOURCES[source]['label'] + '登录')
    deadline = time.monotonic() + 900
    while time.monotonic() < deadline:
        if cancelled.wait(.5): raise BillCollectionError('支付绑定资料下载已取消')
        state = AUTH.status(source)['state']
        if state == 'ready':
            session = client(source)
            identity(source, session)
            return session
        if state in ('error', 'unknown'):
            raise BillCollectionError(SOURCES[source]['label'] + '认证未完成，请在来源认证区域重新登录')
    raise BillCollectionError(SOURCES[source]['label'] + '登录等待超时，未提交导出')


def query(session, source, path, params=None):
    url = 'https://' + SOURCES[source]['host'] + '/prod-api/' + path
    try:
        response = session.get(url, params=params, timeout=40, allow_redirects=False)
        payload = response.json()
        if response.status_code != 200 or payload.get('code') != 200:
            raise ValueError()
        return payload
    except Exception:
        raise BillCollectionError(SOURCES[source]['label'] + '只读查询未成功，请检查登录及资料权限') from None


def export_once(session, source, path, params, output, cancelled):
    if cancelled.is_set(): raise BillCollectionError('支付绑定资料下载已取消，未提交导出')
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    receipt = output.parent / 'http_submission.json'
    with receipt.open('x', encoding='utf-8') as stream:
        json.dump({'source': source, 'scope': params, 'submission_state': 'unknown', 'started_at': time.time()}, stream)
    temporary = output.with_suffix('.download.part')
    try:
        url = 'https://' + SOURCES[source]['host'] + '/prod-api/' + path
        data = params
        if source == 'lanorange':
            # Match the official cI() form serializer, including its final '&'.
            data = urlencode(params, doseq=True)
            if data: data += '&'
        with session.post(url, data=data, stream=True, timeout=(20, 180), allow_redirects=False,
                          headers={'Content-Type': 'application/x-www-form-urlencoded',
                                   'Accept': 'application/json, text/plain, */*'}) as response:
            if response.status_code != 200:
                raise ValueError()
            size = 0
            with temporary.open('xb') as stream:
                for chunk in response.iter_content(256 * 1024):
                    if cancelled.is_set(): raise BillCollectionError('支付绑定资料下载已取消，提交记录已保留')
                    size += len(chunk)
                    if size > 200 * 1024 * 1024: raise ValueError()
                    stream.write(chunk)
        if not zipfile.is_zipfile(temporary):
            raise BillCollectionError('平台返回的 Excel 文件不完整，未发布文件')
        with zipfile.ZipFile(temporary) as workbook:
            if '[Content_Types].xml' not in workbook.namelist() or workbook.testzip() is not None:
                raise BillCollectionError('平台返回的 Excel 文件校验失败，未发布文件')
        temporary.rename(output)
        atomic_json(receipt, {'source': source, 'scope': params, 'submission_state': 'submitted',
                             'finished_at': time.time(), 'bytes': size,
                             'sha256': hashlib.sha256(output.read_bytes()).hexdigest()})
        return output
    except Exception as exc:
        response_headers = getattr(locals().get('response'), 'headers', {})
        if not isinstance(response_headers, Mapping): response_headers = {}
        try:
            atomic_json(receipt, {'source': source, 'endpoint': path, 'scope': params,
                'submission_state': 'unknown', 'failed_at': time.time(),
                'error_category': type(exc).__name__,
                'downloaded_bytes': temporary.stat().st_size if temporary.is_file() else 0,
                'response_headers': {key: str(response_headers[key])[:200] for key in
                                     ('Content-Type', 'Content-Length', 'Transfer-Encoding', 'Content-Encoding') if key in response_headers}})
        except (OSError, ValueError): pass
        if type(exc).__name__ in ('ChunkedEncodingError', 'ConnectionError', 'ReadTimeout'):
            reason = '导出文件传输中断，未收到完整文件'
        elif isinstance(exc, BillCollectionError):
            reason = str(exc)
        else:
            reason = '导出未确认完成'
        raise BillCollectionError(SOURCES[source]['label'] + reason + '；已保留回执，不会自动重复提交') from None


def retained_employee_export(output, params):
    """Reuse only an intact completed export for this same merchant and scope."""
    output = Path(output)
    receipt = output.parent / 'http_submission.json'
    if not output.exists() and not receipt.exists():
        return False
    try:
        proof = json.loads(receipt.read_text(encoding='utf-8'))
        valid = (proof.get('source') == 'baize' and proof.get('scope') == params
                 and proof.get('submission_state') == 'submitted' and output.is_file()
                 and proof.get('bytes') == output.stat().st_size
                 and proof.get('sha256') == hashlib.sha256(output.read_bytes()).hexdigest())
    except (OSError, ValueError):
        valid = False
    if not valid:
        raise BillCollectionError('白泽已有导出回执或文件未通过完整性核对，保留原资料，不重复提交导出')
    return True


class BindingSources:
    def __init__(self, root, log, cancelled):
        self.root, self.log, self.cancelled = Path(root), log, cancelled
        self.results = {}

    def employees(self):
        if 'baize' in self.results: return self.results['baize']
        with authenticated('baize', self.log, self.cancelled) as session:
            user = identity('baize', session).get('user', {})
            merchant = user.get('userRelateId')
            if not isinstance(merchant, (str, int)) or not str(merchant).isdigit():
                raise BillCollectionError('白泽企业身份未确认，不能导出全量员工资料')
            params = {'merId': str(merchant), 'pageNum': 1, 'pageSize': 10}
            file = self.root / 'baize' / 'merchantFreelancer_白泽全量.xlsx'
            if retained_employee_export(file, params):
                self.log('[恢复] 白泽已保留原表与回执哈希一致，继续使用，不重复导出')
            else:
                query(session, 'baize', 'web/merchantFreelancer/checkSecrecy')
                self.log('[下载] 正在通过白泽 HTTP 接口导出最新全量员工资料')
                file = export_once(session, 'baize', 'web/merchantFreelancer/export', params,
                                   file, self.cancelled)
            proof = validate_employees(file)
            atomic_json(file.parent / 'manifest.json', {'status': 'success', 'scope': 'all', 'transport': 'http', **proof})
            self.results['baize'] = file
            return file

    def proxies(self, month):
        key = 'lanorange:' + month
        if key in self.results: return self.results[key]
        with authenticated('lanorange', self.log, self.cancelled) as session:
            params = {'replaceMonth': month, 'pageNum': 1, 'pageSize': 10}
            before = query(session, 'lanorange', 'info/riderSalaryReplace/list', params)
            total = before.get('total')
            if type(total) is not int or total < 0: raise BillCollectionError('蓝橙代领查询总数无效')
            self.log('[下载] 正在通过蓝橙 HTTP 接口导出对应月份代领原始资料')
            file = export_once(session, 'lanorange', 'info/riderSalaryReplace/export', params,
                               self.root / 'lanorange' / month / '薪资代领.xlsx', self.cancelled)
            from salary_bind_processor import _read_file_fast
            frame = _read_file_fast(str(file))
            required = {'城市名称', '代领月份', '流程状态', '启停用', '代领人身份证'}
            if not required.issubset(frame.columns) or len(frame) != total:
                raise BillCollectionError('蓝橙原始导出表头或行数与当月查询不一致，未生成绑定')
            if not frame['代领月份'].astype(str).str[:7].eq(month).all():
                raise BillCollectionError('蓝橙导出包含非目标月份资料，未生成绑定')
            atomic_json(file.parent / 'manifest.json', {'status': 'success', 'month': month, 'rows': len(frame),
                         'transport': 'http', 'scope': 'all_cities_month',
                         'approval_filter': 'local_enabled_approved_or_pending_approved_first'})
            self.results[key] = file
            return file
