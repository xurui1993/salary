"""Download the original Baize employee export, without payroll or binding changes."""

import asyncio
from collections import Counter
import json
from pathlib import Path
import re
import threading
import time
from urllib.parse import urlparse
import uuid

from openpyxl import load_workbook
import psutil

from fengshen_bill import atomic_json, BillCollectionError, validate_bill_file
from parttime_source import COLLECTION_LOCK, ROOT, SourceError, label

EMPLOYEE_URL = 'https://merchant.shangyiworker.com/freelancer/merchantFreelancer'
HEADERS = {'姓名', '身份证号', '银行预留手机号', '银行卡号', '企业名称', '小组名称', '状态',
           '创建时间', '合同信息', '身份证正面', '身份证背面'}
FILTERS = ('请输入姓名', '请输入身份证号', '请输入预留手机号', '请选择区域名称', '请选择状态', '请输入服务地点')


def owned_driver(before):
    candidates = []
    for process in psutil.Process().children():
        try:
            command = ' '.join(process.cmdline()).replace('\\', '/').lower()
            identity = (process.pid, process.create_time())
            if identity not in before and '/playwright/driver/' in command and 'run-driver' in command:
                candidates.append(identity)
        except psutil.Error:
            continue
    # An ambiguous process must never be terminated by the cleanup watchdog.
    return candidates[0] if len(candidates) == 1 else None


def close_browser(browser, driver, log, timeout=15):
    def force_close():
        if driver is None:
            return
        try:
            process = psutil.Process(driver[0])
            if process.create_time() != driver[1] or process.ppid() != psutil.Process().pid:
                return
            descendants = process.children(recursive=True)
            log('[收尾] 专用浏览器关闭超时，仅清理本次创建的浏览器及驱动；原文件保留')
            for child in reversed(descendants):
                try:
                    child.terminate()
                except psutil.Error:
                    pass
            process.terminate()
        except psutil.Error:
            pass
    watchdog = threading.Timer(timeout, force_close)
    watchdog.daemon = True
    watchdog.start()
    try:
        browser.close()
    except Exception:
        log('[收尾] 专用浏览器连接已结束，下载校验结果不受影响')
    finally:
        watchdog.cancel()


def workspace_directory(workspace, root=ROOT):
    if not isinstance(workspace, str) or not workspace or len(workspace) > 128:
        raise SourceError('缺少有效工作区标识')
    if any(c not in '_-' and not c.isalnum() for c in workspace) or workspace.upper().split('.')[0] in {
            'CON', 'PRN', 'AUX', 'NUL', *(f'COM{i}' for i in range(1, 10)), *(f'LPT{i}' for i in range(1, 10))}:
        raise SourceError('工作区标识无效')
    base = (Path(root).resolve() / 'uploads').resolve()
    owner = (base / workspace).resolve()
    if not owner.is_relative_to(base) or owner == base:
        raise SourceError('白泽下载目录越界')
    owner.mkdir(parents=True, exist_ok=True)
    return owner


def validate_employees(path, expected_rows=None):
    # Compatibility argument only: page totals are never compared or required.
    path = Path(path)
    if path.suffix.lower() != '.xlsx':
        raise SourceError('白泽员工导出必须为原始 XLSX 文件')
    info = validate_bill_file(path)
    if info['format'] != 'xlsx':
        raise SourceError('白泽员工导出不是 XLSX 工作簿')
    book = None
    try:
        book = load_workbook(path, read_only=True, data_only=False)
        if len(book.worksheets) != 1:
            raise SourceError('白泽员工导出子表数量变化，请核对原文件')
        sheet = book.worksheets[0]
        sheet.reset_dimensions()
        rows = iter(sheet.iter_rows())
        headers = [label(c.value) for c in next(rows, ())]
        if not HEADERS.issubset(headers) or any(not h for h in headers) or len(headers) != len(set(headers)):
            raise SourceError('白泽员工导出缺少约定表头或存在重复表头')
        count = masked = blank = 0
        groups, statuses = Counter(), Counter()
        for cells in rows:
            if not any(c.value is not None and str(c.value).strip() for c in cells):
                continue
            if len(cells) != len(headers):
                raise SourceError('白泽员工导出行列结构损坏')
            values = dict(zip(headers, cells))
            # Long identifiers must remain text; never repair rounded numbers.
            for field in ('身份证号', '银行卡号', '银行预留手机号'):
                cell = values[field]
                if cell.value is not None and (cell.data_type == 'f' or not isinstance(cell.value, str)):
                    raise SourceError(f'白泽{field}不是文本，存在编号精度风险；原文件已保留')
            identity = str(values['身份证号'].value or '').strip()
            masked += bool(re.search(r'[*＊]', identity))
            blank += not bool(identity)
            groups[label(values['小组名称'].value)] += 1
            statuses[label(values['状态'].value)] += 1
            count += 1
        result = {**info, 'path': path.name, 'rows': count, 'count_comparison': 'disabled',
                'identity_masked': masked, 'identity_blank': blank, 'groups': dict(groups),
                'statuses': dict(statuses), 'scope': 'all', 'originals_retained': True,
                'payroll_executed': False, 'binding_generated': False}
        return result
    except BillCollectionError:
        raise
    except Exception:
        raise SourceError('白泽员工文件无法解析；原文件已保留') from None
    finally:
        if book:
            book.close()


class ShangyiCollector:
    def __init__(self, page, output, log, cancelled, human_timeout=1800, download_timeout=900):
        self.page, self.output, self.log, self.cancelled = page, Path(output), log, cancelled
        self.human_timeout, self.download_timeout = human_timeout, download_timeout
        self.stage = 'login'

    def checkpoint(self):
        if self.cancelled.is_set():
            raise SourceError('白泽下载已取消，原文件保留')
        if self.page.is_closed():
            raise SourceError('白泽专用 Edge 已关闭，下载未完成')

    def one(self, locator, description):
        self.checkpoint()
        locator.first.wait_for(state='visible', timeout=30000)
        if locator.count() != 1 or not locator.is_visible():
            raise SourceError(description + '未唯一匹配，请核对页面配置')
        return locator

    def logged_in(self):
        parsed = urlparse(self.page.url)
        return (parsed.scheme == 'https' and parsed.hostname == 'merchant.shangyiworker.com'
                and parsed.path.rstrip('/') == '/freelancer/merchantFreelancer'
                and self.page.get_by_role('button', name=re.compile(r'^\s*搜\s*索\s*$')).count() == 1)

    def wait_login(self):
        self.page.goto(EMPLOYEE_URL, wait_until='domcontentloaded', timeout=60000)
        deadline = time.monotonic() + self.human_timeout
        announced = False
        while not self.logged_in():
            self.checkpoint()
            if time.monotonic() >= deadline:
                raise SourceError('白泽官方登录等待超过 30 分钟；未提交导出')
            if not announced:
                self.log('[等待登录] 请在白泽专用 Edge 自行填写账号、密码和图形验证码并登录；窗口保留最多 30 分钟，不保存密码')
                self.page.bring_to_front()
                announced = True
            parsed = urlparse(self.page.url)
            if parsed.scheme != 'https' or parsed.hostname != 'merchant.shangyiworker.com':
                raise SourceError('白泽页面跳转到未确认网站；未提交导出')
            if parsed.path == '/index' or parsed.path == '/':
                self.page.goto(EMPLOYEE_URL, wait_until='domcontentloaded', timeout=60000)
            self.page.wait_for_timeout(500)
        self.log('[登录] 白泽企业员工页面已就绪')

    def prepare(self):
        self.stage = 'query'
        self.one(self.page.get_by_role('button', name=re.compile(r'^\s*重\s*置\s*$')), '白泽重置按钮').click()
        for placeholder in FILTERS:
            if self.one(self.page.get_by_placeholder(placeholder, exact=True), '白泽筛选框').input_value().strip():
                raise SourceError('白泽筛选条件未清空；未提交全量导出')
        self.one(self.page.get_by_role('button', name=re.compile(r'^\s*搜\s*索\s*$')), '白泽搜索按钮').click()
        self.one(self.page.get_by_role('columnheader', name='身份证号', exact=True), '白泽员工表头')
        self.page.wait_for_timeout(2000)
        self.log('[范围] 所有区域、所有状态、服务地点不限、无日期筛选；不比较页面与导出条数')

    def collect(self):
        self.wait_login()
        self.prepare()
        self.stage = 'export'
        downloads = []
        def downloaded(download):
            downloads.append(download)
        self.page.on('download', downloaded)
        try:
            self.one(self.page.get_by_role('button', name=re.compile(r'^\s*导\s*出\s*$')), '白泽导出按钮').click()
            self.log('[导出] 已提交一次全量导出，等待原文件；不会自动重复提交')
            deadline = time.monotonic() + self.download_timeout
            confirmed = False
            while not downloads:
                self.checkpoint()
                if not self.logged_in():
                    raise SourceError('白泽导出过程中登录失效；未重复提交，请重新登录后重试')
                if time.monotonic() >= deadline:
                    raise SourceError('白泽导出等待超时；未重复提交')
                dialogs = self.page.get_by_role('dialog').filter(visible=True)
                if dialogs.count() == 1 and not confirmed:
                    text = dialogs.inner_text()
                    if '导出' in text and not any(word in text for word in ('协议', '签署', '支付', '转账')):
                        button = dialogs.get_by_role('button', name=re.compile(r'^\s*(确\s*定|确\s*认)\s*$'))
                        if button.count() == 1:
                            self.one(button, '白泽导出确认').click()
                            confirmed = True
                self.page.wait_for_timeout(500)
            if len(downloads) != 1:
                raise SourceError('白泽收到多份下载，需核对导出任务')
            download = downloads[0]
            if download.failure():
                raise SourceError('白泽原文件下载失败')
            if Path(download.suggested_filename).suffix.lower() != '.xlsx':
                raise SourceError('白泽返回未确认文件格式，未生成绑定')
            self.stage = 'validate'
            path = self.output / 'merchantFreelancer_白泽全部员工.xlsx'
            download.save_as(path)
            self.log('[校验] 白泽原文件已保存，正在检查文件完整性、表头与编号文本格式')
            info = validate_employees(path)
            self.log(f'[完成] 白泽原始员工资料 {info["rows"]} 条，未比较页面条数；未生成绑定或核算')
            return info
        finally:
            self.page.remove_listener('download', downloaded)


def download_employees(workspace, log, cancelled, collector=None):
    owner = workspace_directory(workspace)
    if not COLLECTION_LOCK.acquire(blocking=False):
        raise SourceError('另一项资料采集正在运行，请等待完成')
    run = owner / ('shangyi_sources_' + uuid.uuid4().hex)
    manifest = {'status': 'running', 'scope': 'all', 'datasets': {}, 'originals_retained': True,
                'payroll_executed': False, 'binding_generated': False, 'credentials_saved': False}
    current = None
    def failure(exc):
        if manifest['status'] == 'error' and not isinstance(exc, BillCollectionError):
            return manifest['error']
        message = str(exc) if isinstance(exc, BillCollectionError) else '白泽资料下载失败，请核对官方页面或网络；未核算'
        manifest.update(status='error', stage=current.stage if current else 'browser', error=message,
                        failure_type=type(exc).__name__)
        if run.is_dir():
            atomic_json(run / 'manifest.json', manifest)
        return message
    try:
        run.mkdir()
        atomic_json(run / 'manifest.json', manifest)
        if collector:
            current = collector(run, log, cancelled)
            info = current.collect()
        else:
            from playwright.sync_api import sync_playwright
            before = {(p.pid, p.create_time()) for p in psutil.Process().children()}
            with sync_playwright() as pw:
                driver = owned_driver(before)
                browser = pw.chromium.launch(channel='msedge', headless=False)
                try:
                    context = browser.new_context(accept_downloads=True)
                    current = ShangyiCollector(context.new_page(), run, log, cancelled)
                    info = current.collect()
                except Exception as exc:
                    log('[校验失败] ' + failure(exc))
                    raise
                finally:
                    close_browser(browser, driver, log)
        manifest.update(status='success', stage='complete', datasets={'merchant_employees': info})
        atomic_json(run / 'manifest.json', manifest)
        return run, manifest
    except Exception as exc:
        message = failure(exc)
        if run.is_dir():
            log(f'[诊断] 白泽原文件及失败阶段保留在：{run}')
        raise SourceError(message) from None
    finally:
        COLLECTION_LOCK.release()


def _employee_info(run, path):
    source_manifest = path.parent / 'manifest.json'
    try:
        receipt = json.loads(source_manifest.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        raise BillCollectionError('白泽 HTTP 导出清单缺失或损坏，未生成绑定') from None
    if receipt.get('status') != 'success' or receipt.get('scope') != 'all':
        raise BillCollectionError('白泽全量资料未完成校验，未生成绑定')
    rows = receipt.get('rows')
    if type(rows) is not int or rows < 0:
        raise BillCollectionError('白泽 HTTP 导出缺少记录数，未生成绑定')
    if (receipt.get('path') != path.name or receipt.get('format') != 'xlsx'
            or not isinstance(receipt.get('sha256'), str) or len(receipt['sha256']) != 64
            or type(receipt.get('bytes')) is not int or receipt['bytes'] <= 0):
        raise BillCollectionError('白泽 HTTP 导出清单文件信息不完整，未生成绑定')
    try:
        relative = path.resolve().relative_to(run.resolve()).as_posix()
    except (OSError, ValueError):
        raise BillCollectionError('白泽 HTTP 导出路径越界，未生成绑定') from None
    return {**receipt, 'path': relative}


def download_employees_http(workspace, log, cancelled):
    owner = workspace_directory(workspace)
    if not COLLECTION_LOCK.acquire(blocking=False):
        raise SourceError('另一项资料采集正在运行，请等待完成')
    run = owner / ('shangyi_sources_' + uuid.uuid4().hex)
    manifest = {'status': 'running', 'scope': 'all', 'transport': 'http', 'datasets': {},
                'originals_retained': True, 'payroll_executed': False,
                'binding_generated': False, 'credentials_saved': False}
    stage = 'http'
    try:
        run.mkdir()
        atomic_json(run / 'manifest.json', manifest)
        from binding_sources_http import BindingSources
        path = BindingSources(run, log, cancelled).employees()
        stage = 'validate'
        manifest['stage'] = stage
        atomic_json(run / 'manifest.json', manifest)
        info = _employee_info(run, path)
        manifest.update(status='success', stage='complete', datasets={'merchant_employees': info})
        atomic_json(run / 'manifest.json', manifest)
        log(f'[完成] 白泽原始员工资料 {info["rows"]} 条；未生成绑定或核算')
        return run, manifest
    except Exception as exc:
        message = str(exc) if isinstance(exc, BillCollectionError) else '白泽资料下载失败，请核对官方页面或网络；未核算'
        manifest.update(status='error', stage=stage, error=message, failure_type=type(exc).__name__)
        if run.is_dir():
            source_manifest = run / 'baize' / 'manifest.json'
            try:
                if source_manifest.is_file() and not source_manifest.is_symlink():
                    manifest['datasets'] = {'merchant_employees': json.loads(
                        source_manifest.read_text(encoding='utf-8'))}
            except (OSError, ValueError):
                pass
            atomic_json(run / 'manifest.json', manifest)
            log(f'[诊断] 白泽原文件及失败阶段保留在：{run}')
        raise SourceError(message) from None
    finally:
        COLLECTION_LOCK.release()


async def run_shangyi_sources(config, workspace):
    import tasks
    cancelled, queue = threading.Event(), asyncio.Queue()
    loop = asyncio.get_running_loop()
    worker = None
    def log(message):
        if not cancelled.is_set():
            loop.call_soon_threadsafe(queue.put_nowait, tasks.create_log_event(message))
    try:
        worker = asyncio.create_task(asyncio.to_thread(download_employees_http, workspace, log, cancelled))
        while not worker.done() or not queue.empty():
            try:
                yield await asyncio.wait_for(queue.get(), timeout=0.5)
            except asyncio.TimeoutError:
                yield ': heartbeat\n\n'
        run, manifest = await worker
        yield tasks.create_finish_event('success', '白泽全部员工原文件已下载并校验，未执行核算', str(run), manifest)
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
