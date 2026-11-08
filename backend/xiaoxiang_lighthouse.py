"""小象超市灯塔：商配送骑手订单明细附件下载。

浏览器只用于美团 Passport 登录；通知查询、附件下载全部走 HTTPS 直连。
会话按 Windows 用户加密保存在 backend/.local_auth/xiaoxiang_lighthouse.dpapi。

用法：
  python xiaoxiang_lighthouse.py                # 上一个完整自然周
  python xiaoxiang_lighthouse.py --week 2026-10-19
  python xiaoxiang_lighthouse.py --week 2026-10-19 --out D:/tmp/lighthouse
"""
from argparse import ArgumentParser
from datetime import date, datetime, timedelta
import hashlib
import json
import os
from pathlib import Path
import tempfile
import time
import warnings
import zipfile

import requests

from fengshen_auth import dpapi
from fengshen_bill import atomic_json, BillCollectionError

BASE = 'https://maicaipeisong.meituan.com'
ENTRY = BASE + '/notice/list.html'
LIST_PATH = '/api/s/peisong/rideroms/supplier/notice/record/list'
DETAIL_PATH = '/api/s/peisong/rideroms/supplier/notice/record/detail'
SUPPLIER_ID = 106
PROJECT = Path(__file__).resolve().parent.parent
SESSION_FILE = Path(__file__).resolve().parent / '.local_auth' / 'xiaoxiang_lighthouse.dpapi'
SESSION_ENTROPY = b'aegis-xiaoxiang-lighthouse-v1'
STATE_LIMIT = 256 * 1024
REQUIRED_COLUMNS = {'合作商id', '骑手id', '站点id', '业务日期', '配送方', '配送单量'}
HEADERS = {
    'User-Agent': ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
                   '(KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36 Edg/141.0.0.0'),
    'Accept': 'application/json, text/plain, */*',
    'Content-Type': 'application/json',
    'Origin': BASE,
    'Referer': ENTRY,
}


# 继承业务错误类：下载中心的固定文案脱敏机制会把业务提示原样透出，
# 否则用户只能看到「采集未完成」这类笼统提示。
class LighthouseError(BillCollectionError):
    pass


def _say(message):
    # 登录可能等待数分钟，重定向到日志时也要立即看到提示
    print(message, flush=True)


class SessionExpired(LighthouseError):
    pass


def week_range(today=None):
    """上一个完整自然周（周一至周日）。"""
    today = today or date.today()
    monday = today - timedelta(days=today.weekday())
    return monday - timedelta(days=7), monday - timedelta(days=1)


def week_of(day):
    """day 所在自然周（周一至周日）。"""
    monday = day - timedelta(days=day.weekday())
    return monday, monday + timedelta(days=6)


def week_title(start, end):
    # 灯塔标题不补零：9.28-10.4骑手订单明细
    return '{}.{}-{}.{}骑手订单明细'.format(start.month, start.day, end.month, end.day)


def readable_time(value):
    if isinstance(value, (int, float)) and value > 0:
        stamp = value / 1000 if value > 10_000_000_000 else value
        try:
            return datetime.fromtimestamp(stamp).isoformat(timespec='seconds')
        except (OverflowError, OSError, ValueError):
            return str(value)
    return value


def _host_allowed(domain):
    domain = str(domain or '').lower().lstrip('.')
    return domain in ('meituan.com', 'sankuai.com') or domain.endswith(('.meituan.com', '.sankuai.com'))


def scoped_state(state):
    if (not isinstance(state, dict) or not isinstance(state.get('cookies'), list)
            or not isinstance(state.get('origins'), list)):
        raise LighthouseError('本机会话格式无效，请重新登录')
    cookies = []
    for cookie in state['cookies']:
        if not isinstance(cookie, dict) or not _host_allowed(cookie.get('domain')):
            continue
        name, value = cookie.get('name'), cookie.get('value')
        if not isinstance(name, str) or not isinstance(value, str):
            continue
        if not 0 < len(name) <= 128 or len(value) > 16384:
            continue
        cookies.append(cookie)
    origins = [origin for origin in state['origins']
               if isinstance(origin, dict)
               and str(origin.get('origin', '')).startswith('https://')
               and _host_allowed(origin.get('origin', '').split('://', 1)[-1].split('/', 1)[0])]
    if not cookies:
        raise LighthouseError('本机会话缺少灯塔 Cookie，请重新登录')
    return {'cookies': cookies, 'origins': origins}


def load_state(path=SESSION_FILE):
    path = Path(path)
    if not path.exists():
        return None
    if path.is_symlink() or path.stat().st_size > STATE_LIMIT:
        raise LighthouseError('本机会话文件异常，请删除后重新登录')
    try:
        data = json.loads(dpapi(path.read_bytes(), decrypt=True, entropy=SESSION_ENTROPY))
        if data.get('source') != 'xiaoxiang_lighthouse':
            raise ValueError()
        return scoped_state(data.get('state'))
    except LighthouseError:
        raise
    except Exception:
        raise LighthouseError('本机会话无法解密，请删除后重新登录') from None


def save_state(state, path=SESSION_FILE):
    path = Path(path)
    payload = json.dumps({'source': 'xiaoxiang_lighthouse', 'state': scoped_state(state)},
                         ensure_ascii=True, separators=(',', ':')).encode('utf-8')
    if len(payload) > STATE_LIMIT:
        raise LighthouseError('本机会话过大，未保存')
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, suffix='.encrypted.part', delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(dpapi(payload, entropy=SESSION_ENTROPY))
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def session_from_state(state):
    session = requests.Session()
    session.headers.update(HEADERS)
    for cookie in scoped_state(state)['cookies']:
        session.cookies.set(cookie['name'], cookie['value'],
                            domain=cookie.get('domain'), path=cookie.get('path') or '/')
    return session


def _post(session, path, payload):
    try:
        response = session.post(BASE + path, json=payload, timeout=30)
    except requests.RequestException as exc:
        raise LighthouseError('连接小象灯塔失败，请检查网络后重试') from exc
    if response.status_code != 200:
        raise LighthouseError('小象灯塔接口返回 HTTP {}'.format(response.status_code))
    if 'passport.meituan.com' in str(getattr(response, 'url', '') or '') \
            or 'text/html' in str(response.headers.get('content-type') or ''):
        raise SessionExpired('小象灯塔登录已失效，请重新登录')
    try:
        body = response.json()
    except ValueError:
        raise LighthouseError('小象灯塔接口返回内容不是 JSON，页面可能已改版') from None
    code = body.get('code')
    if code == 5:
        raise SessionExpired('小象灯塔登录已失效，请重新登录')
    if code != 0:
        detail = (body.get('error') or {}).get('msg') or body.get('msg') or code
        raise LighthouseError('小象灯塔接口错误：{}'.format(detail))
    return body.get('data') or {}


def find_notice(session, title, supplier_id=SUPPLIER_ID):
    data = _post(session, LIST_PATH, {'title': title, 'paging': {}, 'supplierId': supplier_id})
    for record in data.get('noticeRecordList') or []:
        if str(record.get('title') or '').strip() == title:
            return record
    return None


def notice_detail(session, notice_id, supplier_id=SUPPLIER_ID):
    data = _post(session, DETAIL_PATH, {'noticeRecordId': notice_id, 'supplierId': supplier_id})
    return data.get('recordDetail') or {}


def select_attachments(items):
    picked = []
    for item in items or []:
        if not isinstance(item, dict):
            continue
        name = str(item.get('fileName') or '').strip()
        url = str(item.get('fileUrl') or '').strip()
        if not name or not url:
            continue
        if '商配送' not in name or '骑手订单明细' not in name:
            continue
        if '.xlsx' not in name.lower():
            continue
        picked.append({'fileName': name, 'fileUrl': url})
    return picked


def validate_workbook(path):
    path = Path(path)
    if not zipfile.is_zipfile(path):
        raise LighthouseError('附件不是有效的 xlsx 文件：' + path.name)
    with zipfile.ZipFile(path) as book:
        if '[Content_Types].xml' not in book.namelist() or book.testzip() is not None:
            raise LighthouseError('附件 xlsx 校验失败：' + path.name)
    from openpyxl import load_workbook
    try:
        # 传入文件对象：下载中的 .part 后缀不会被 openpyxl 当成非法扩展名
        with path.open('rb') as stream, warnings.catch_warnings():
            # 灯塔导出的工作簿没有默认样式，openpyxl 的 UserWarning 对校验无意义
            warnings.simplefilter('ignore', UserWarning)
            workbook = load_workbook(stream, data_only=True)
    except Exception as exc:
        raise LighthouseError('附件无法作为 Excel 打开：{}（{}）'.format(path.name, type(exc).__name__)) from None
    try:
        sheet = workbook[workbook.sheetnames[0]]
        first = next(sheet.iter_rows(min_row=1, max_row=1, values_only=True), ())
        headers = [str(value).strip() for value in first if value is not None and str(value).strip()]
        missing = REQUIRED_COLUMNS - set(headers)
        if missing:
            raise LighthouseError('附件缺少关键列：{}（{}）'.format('、'.join(sorted(missing)), path.name))
        rows = int(sheet.max_row or 1) - 1
        if rows <= 0:
            raise LighthouseError('附件没有数据行：' + path.name)
        return {'sheet': sheet.title, 'rows': rows, 'columns': len(headers), 'headers': headers}
    finally:
        workbook.close()


def _download(url, target):
    target = Path(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    part = target.with_suffix(target.suffix + '.part')
    try:
        with requests.get(url, stream=True, timeout=(10, 180), headers={'User-Agent': HEADERS['User-Agent']}) as response:
            if response.status_code != 200:
                raise LighthouseError('附件下载返回 HTTP {}'.format(response.status_code))
            with part.open('wb') as stream:
                for chunk in response.iter_content(1024 * 1024):
                    if chunk:
                        stream.write(chunk)
        info = validate_workbook(part)
        os.replace(part, target)
    except requests.RequestException as exc:
        raise LighthouseError('附件下载中断，请重试') from exc
    finally:
        part.unlink(missing_ok=True)
    with target.open('rb') as stream:
        digest = hashlib.file_digest(stream, 'sha256').hexdigest()
    info.update({'bytes': target.stat().st_size, 'sha256': digest})
    return info

def _batch_names(names):
    """同一批附件内重名才加序号；重跑同一周时按原名覆盖，不产生副本。"""
    used = set()
    for name in names:
        candidate = name
        if candidate in used:
            stem, suffix = os.path.splitext(name)
            index = 2
            while '{}-{}{}'.format(stem, index, suffix) in used:
                index += 1
            candidate = '{}-{}{}'.format(stem, index, suffix)
        used.add(candidate)
        yield candidate


def interactive_login(title, headless=False, timeout=900):
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        raise LighthouseError('缺少 Playwright 运行环境，无法打开登录窗口') from None
    try:
        stored = load_state()
    except LighthouseError:
        stored = None
    if headless and stored is None:
        raise LighthouseError('没有已保存的会话时无法后台登录，请先有界面登录一次')
    with sync_playwright() as pw:
        browser = pw.chromium.launch(channel='msedge', headless=headless)
        try:
            options = {'viewport': {'width': 1180, 'height': 820}}
            if stored is not None:
                options['storage_state'] = stored
            context = browser.new_context(**options)
            page = context.new_page()
            page.goto(ENTRY, wait_until='domcontentloaded', timeout=60000)
            if not headless:
                _say('>>> 请在打开的 Edge 窗口完成美团短信登录；登录成功后窗口会自动关闭')
            deadline = time.monotonic() + timeout
            last_probe = 0.0
            while time.monotonic() < deadline:
                if time.monotonic() - last_probe >= 3:
                    last_probe = time.monotonic()
                    state = context.storage_state()
                    try:
                        find_notice(session_from_state(state), title)
                    except LighthouseError:
                        pass
                    else:
                        save_state(state)
                        _say('>>> 登录成功，会话已加密保存')
                        return session_from_state(state)
                page.wait_for_timeout(1000)
            raise SessionExpired('等待登录超时（{} 秒），请重新运行脚本'.format(timeout))
        finally:
            browser.close()


def _authenticated_session(title, allow_login, headless):
    try:
        stored = load_state()
    except LighthouseError:
        stored = None
    if stored is not None:
        session = session_from_state(stored)
        try:
            find_notice(session, title)
            return session
        except SessionExpired:
            if not allow_login:
                raise SessionExpired('小象灯塔登录已失效；加 --no-login 时不会打开登录窗口') from None
    elif not allow_login:
        raise SessionExpired('尚未保存小象灯塔会话，请先运行一次登录')
    return interactive_login(title, headless=headless)


def download_week(week=None, output_dir=None, supplier_id=SUPPLIER_ID,
                  allow_login=True, headless=False, today=None):
    if week is None:
        start, end = week_range(today)
    else:
        start, end = week_of(week)
    title = week_title(start, end)
    session = _authenticated_session(title, allow_login, headless)

    record = find_notice(session, title, supplier_id)
    if record is None:
        raise LighthouseError('灯塔未找到通知：{}（可能尚未发布）'.format(title))
    notice_id = record.get('id')
    detail = notice_detail(session, notice_id, supplier_id)
    attachments = select_attachments(detail.get('fileInfoList') or [])
    if not attachments:
        available = [str(item.get('fileName') or '') for item in detail.get('fileInfoList') or []
                     if isinstance(item, dict)]
        raise LighthouseError('通知中没有商配送 xlsx 附件；现有附件：{}'.format(
            '、'.join(available) or '无'))

    target_dir = Path(output_dir) if output_dir else PROJECT / 'outputs' / '小象灯塔' / '{}_{}'.format(start, end)
    target_dir.mkdir(parents=True, exist_ok=True)
    files = []
    for attachment, name in zip(attachments, _batch_names([item['fileName'] for item in attachments])):
        target = target_dir / name
        info = _download(attachment['fileUrl'], target)
        info['name'] = target.name
        files.append(info)
        _say('  ✓ {}  {} 行 / {} 列  {:.0f} KB'.format(
            target.name, info['rows'], info['columns'], info['bytes'] / 1024))

    report = {
        'supplierId': supplier_id,
        'week': {'start': start.isoformat(), 'end': end.isoformat()},
        'title': title,
        'noticeId': notice_id,
        'publishTime': readable_time(detail.get('publishTime') or record.get('publishTime')),
        'publisher': detail.get('publisher') or record.get('publisher'),
        'fetchedAt': datetime.now().isoformat(timespec='seconds'),
        'files': files,
    }
    atomic_json(target_dir / 'manifest.json', report)
    _say('[OK] {} → {} 个附件，目录：{}'.format(title, len(files), target_dir))
    return report


def main(argv=None):
    parser = ArgumentParser(description='下载小象超市灯塔商配送骑手订单明细附件')
    parser.add_argument('--week', help='目标周的任意一天（YYYY-MM-DD）；默认上一个完整自然周')
    parser.add_argument('--out', help='输出目录；默认 outputs/小象灯塔/<开始>_<结束>')
    parser.add_argument('--supplier-id', type=int, default=SUPPLIER_ID, help='采购商 ID，默认 106')
    parser.add_argument('--no-login', action='store_true', help='会话失效时直接失败，不打开浏览器')
    parser.add_argument('--headless', action='store_true', help='无界面运行（仅复用已保存会话）')
    args = parser.parse_args(argv)
    try:
        week = date.fromisoformat(args.week) if args.week else None
    except ValueError:
        _say('[失败] --week 需要 YYYY-MM-DD 格式')
        return 1
    try:
        download_week(week=week, output_dir=args.out, supplier_id=args.supplier_id,
                      allow_login=not args.no_login, headless=args.headless)
    except SessionExpired as exc:
        _say('[需要登录] {}'.format(exc))
        return 2
    except LighthouseError as exc:
        _say('[失败] {}'.format(exc))
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
