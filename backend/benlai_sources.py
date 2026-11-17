"""本来人力商户端全量灵工资料与实时签约城市，复用已保存的浏览器会话走 HTTP。"""
import hashlib
import json
import re
from pathlib import Path
import time
import uuid
import zipfile

from openpyxl import load_workbook

from binding_source_auth import _response_json
from binding_sources_http import authenticated
from fengshen_bill import atomic_json, BillCollectionError
from parttime_source import COLLECTION_LOCK, label
from shangyi_sources import workspace_directory

HOST = 'b.icp88.com'
SIGNING_PATH = '/api/staffInfo/getCitySignUrls'
EXPORT_PATH = '/api/staffInfo/exportStaffInfo'
EXPORT_NAME = '本来人力灵工全量.xlsx'
SIGNED_STATUS = '已签约'
IDENTITY_HEADERS = ('身份证号', '身份证号码', '身份证', '证件号码', '证件号')
NAME_HEADERS = ('姓名', '灵工姓名', '员工姓名', '骑手姓名')
CITY_HEADERS = ('签约城市', '城市名称', '服务城市', '城市')
STATUS_HEADERS = ('签约状态', '合同状态', '状态')
PHONE_HEADERS = ('手机号', '手机号码', '联系电话', '电话')


def city_key(value):
    text = re.sub(r'\s+', '', label(value))
    return text[:-1] if text.endswith('市') else text


def signed_status(value):
    if isinstance(value, bool) or value is None:
        return False
    text = str(value).strip()
    if text == SIGNED_STATUS:
        return True
    try:
        return int(float(text)) == 2
    except (TypeError, ValueError):
        return False


def _column(header, aliases, kind):
    for name in aliases:
        if name in header:
            return header.index(name)
    raise BillCollectionError('本来人力员工导出缺少' + kind + '列')


def validate_employees(path):
    """校验原始导出并统计签约状态；证件号必须保持文本。"""
    path = Path(path)
    if path.suffix.lower() != '.xlsx':
        raise BillCollectionError('本来人力员工导出必须为原始 XLSX 文件')
    book = None
    try:
        book = load_workbook(path, read_only=True, data_only=False)
        if len(book.worksheets) != 1:
            raise BillCollectionError('本来人力员工导出子表数量变化，请核对原文件')
        sheet = book.worksheets[0]
        sheet.reset_dimensions()
        rows = iter(sheet.iter_rows())
        header = [label(cell.value) for cell in next(rows, ())]
        if not header or any(not name for name in header) or len(header) != len(set(header)):
            raise BillCollectionError('本来人力员工导出表头为空或重复')
        identity = _column(header, IDENTITY_HEADERS, '证件号')
        name = _column(header, NAME_HEADERS, '姓名')
        city = _column(header, CITY_HEADERS, '城市')
        status = _column(header, STATUS_HEADERS, '签约状态')
        phone = next((header.index(value) for value in PHONE_HEADERS if value in header), None)
        count = signed = masked = blank = 0
        cities, statuses = {}, {}
        for cells in rows:
            if not any(cell.value is not None and str(cell.value).strip() for cell in cells):
                continue
            if len(cells) != len(header):
                raise BillCollectionError('本来人力员工导出行列结构损坏')
            cell = cells[identity]
            if cell.value is not None and (cell.data_type == 'f' or not isinstance(cell.value, str)):
                raise BillCollectionError('本来人力证件号不是文本，存在编号精度风险；原文件已保留')
            value = str(cell.value or '').strip()
            masked += bool(re.search(r'[*＊]', value))
            blank += not value
            city_name = city_key(cells[city].value)
            state = label(cells[status].value)
            if city_name:
                cities[city_name] = cities.get(city_name, 0) + 1
            statuses[state] = statuses.get(state, 0) + 1
            signed += bool(value and signed_status(cells[status].value))
            count += 1
        if not count:
            raise BillCollectionError('本来人力员工导出没有记录，请核对账号权限')
        result = {'path': path.name, 'rows': count, 'signed_rows': signed,
                  'bytes': path.stat().st_size,
                  'sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
                  'identity_masked': masked, 'identity_blank': blank,
                  'cities': cities, 'statuses': statuses, 'scope': 'all',
                  'has_phone': phone is not None, 'originals_retained': True,
                  'payroll_executed': False, 'binding_generated': False}
        return result
    except BillCollectionError:
        raise
    except Exception:
        raise BillCollectionError('本来人力员工文件无法解析；原文件已保留') from None
    finally:
        if book:
            book.close()


def signing_cities(session):
    """读取与官方「签约链接」弹窗一致的城市清单。"""
    url = 'https://' + HOST + SIGNING_PATH
    response = session.get(url, timeout=40, allow_redirects=False)
    if response.status_code == 401 or response.status_code == 403:
        raise BillCollectionError('本来人力登录已失效，请重新认证')
    if response.status_code != 200:
        raise BillCollectionError('本来人力签约城市接口暂不可用，请稍后重试')
    try:
        payload = _response_json(response)
    except (ValueError, TypeError):
        raise BillCollectionError('本来人力签约城市响应无法解析，未生成绑定') from None
    if not isinstance(payload, dict) or payload.get('code') != 0:
        message = str(payload.get('msg') or '') if isinstance(payload, dict) else ''
        raise BillCollectionError('本来人力签约城市读取失败' + ('：' + message if message else ''))
    entries = payload.get('data')
    if not isinstance(entries, list):
        raise BillCollectionError('本来人力签约城市结构变化，未生成绑定')
    for entry in entries:
        if not isinstance(entry, dict):
            raise BillCollectionError('本来人力签约城市结构变化，未生成绑定')
    custom = [entry for entry in entries if entry.get('cityCode')]
    visible = [entry for entry in custom if not entry.get('isDefault')] if custom else []
    cities = list(dict.fromkeys(city_key(entry.get('cityName')) for entry in visible
                                if city_key(entry.get('cityName'))))
    proof = [{'cityCode': entry.get('cityCode'), 'cityName': label(entry.get('cityName')),
              'isDefault': bool(entry.get('isDefault')), 'isvalid': bool(entry.get('isvalid'))}
             for entry in visible]
    return {'cities': cities, 'entries': proof, 'captured_at': time.time(),
            'template_enabled': bool(entries)}


def export_workbook(session, output, cancelled):
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    receipt = output.parent / 'http_submission.json'
    scope = {'currentPage': 1, 'pageSize': 10}
    with receipt.open('x', encoding='utf-8') as stream:
        json.dump({'source': 'benlai', 'scope': scope, 'submission_state': 'unknown',
                   'started_at': time.time()}, stream)
    temporary = output.with_suffix('.download.part')
    try:
        with session.post('https://' + HOST + EXPORT_PATH, json=scope, stream=True,
                          timeout=(20, 180), allow_redirects=False,
                          headers={'Content-Type': 'application/json',
                                   'Accept': 'application/json, text/plain, */*'}) as response:
            if response.status_code != 200:
                raise BillCollectionError('本来人力导出未成功，请检查登录及导出权限')
            size = 0
            with temporary.open('xb') as stream:
                for chunk in response.iter_content(256 * 1024):
                    if cancelled.is_set():
                        raise BillCollectionError('本来人力资料下载已取消，提交记录已保留')
                    size += len(chunk)
                    if size > 200 * 1024 * 1024:
                        raise BillCollectionError('本来人力导出文件超出预期，未发布文件')
                    stream.write(chunk)
        if not zipfile.is_zipfile(temporary):
            try:
                message = json.loads(temporary.read_text(encoding='utf-8', errors='replace')).get('msg')
            except (OSError, ValueError):
                message = None
            raise BillCollectionError('本来人力未返回 Excel 文件' + ('：' + message if message else '，请检查导出权限'))
        with zipfile.ZipFile(temporary) as workbook:
            if '[Content_Types].xml' not in workbook.namelist() or workbook.testzip() is not None:
                raise BillCollectionError('本来人力返回的 Excel 文件校验失败，未发布文件')
        temporary.rename(output)
        atomic_json(receipt, {'source': 'benlai', 'scope': scope, 'submission_state': 'submitted',
                              'finished_at': time.time(), 'bytes': size,
                              'sha256': hashlib.sha256(output.read_bytes()).hexdigest()})
        return output
    except Exception as exc:
        if isinstance(exc, BillCollectionError):
            reason = str(exc)
        else:
            reason = '本来人力导出未确认完成，请检查网络后重试；已保留回执'
        try:
            atomic_json(receipt, {'source': 'benlai', 'scope': scope,
                                  'submission_state': 'unknown', 'failed_at': time.time(),
                                  'error_category': type(exc).__name__,
                                  'downloaded_bytes': temporary.stat().st_size if temporary.is_file() else 0})
        except (OSError, ValueError):
            pass
        raise BillCollectionError(reason) from None
    finally:
        temporary.unlink(missing_ok=True)


class BenlaiSources:
    def __init__(self, root, log, cancelled):
        self.root, self.log, self.cancelled = Path(root), log, cancelled
        self.result = None

    def employees(self):
        if self.result is not None:
            return self.result
        self.root.mkdir(parents=True, exist_ok=True)
        with authenticated('benlai', self.log, self.cancelled) as session:
            links = signing_cities(session)
            atomic_json(self.root / 'signing_cities.json', links)
            if links['cities']:
                self.log('[城市] 本来人力签约链接覆盖 ' + str(len(links['cities'])) + ' 个城市：'
                         + '、'.join(links['cities']))
            else:
                self.log('[城市] 本来人力签约链接未返回具体城市；这些城市将按商翼判定')
            self.log('[下载] 正在通过本来人力 HTTP 接口导出全量灵工资料')
            file = export_workbook(session, self.root / EXPORT_NAME, self.cancelled)
            proof = validate_employees(file)
            proof.update(benlai_cities=links['cities'], transport='http')
            atomic_json(self.root / 'manifest.json', {'status': 'success', 'scope': 'all',
                                                      'transport': 'http', **proof})
        self.result = file
        self.log('[完成] 本来人力原始灵工资料 ' + str(proof['rows']) + ' 条，已签约 '
                 + str(proof['signed_rows']) + ' 条')
        return file


def download_employees_http(workspace, log, cancelled):
    owner = workspace_directory(workspace)
    if not COLLECTION_LOCK.acquire(blocking=False):
        raise BillCollectionError('另一项资料采集正在运行，请等待完成')
    run = owner / ('benlai_sources_' + uuid.uuid4().hex)
    manifest = {'status': 'running', 'scope': 'all', 'transport': 'http', 'datasets': {},
                'originals_retained': True, 'payroll_executed': False, 'binding_generated': False}
    try:
        run.mkdir()
        atomic_json(run / 'manifest.json', manifest)
        file = BenlaiSources(run, log, cancelled).employees()
        info = validate_employees(file)
        links = json.loads((run / 'signing_cities.json').read_text(encoding='utf-8'))
        info.update(benlai_cities=links['cities'], transport='http')
        manifest.update(status='success', stage='complete', datasets={'benlai_employees': info})
        atomic_json(run / 'manifest.json', manifest)
        return run, manifest
    except Exception as exc:
        message = str(exc) if isinstance(exc, BillCollectionError) else '本来人力资料下载失败，请检查网络或登录状态'
        manifest.update(status='error', error=message, failure_type=type(exc).__name__)
        if run.is_dir():
            atomic_json(run / 'manifest.json', manifest)
            log('[诊断] 本来人力原文件及失败阶段保留在：' + str(run))
        raise BillCollectionError(message) from None
    finally:
        COLLECTION_LOCK.release()