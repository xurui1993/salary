"""文件领取：本机成品共享信息与局域网 Windows 共享文件夹（只读、限定共享根目录）。"""
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout
from datetime import datetime, timezone
import json
import mimetypes
import ntpath
import os
from pathlib import Path
import re
import socket
import subprocess
import threading
import time
import uuid

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse

from download_accounts import bootstrap_allowed, require_account, validate_write_request

router = APIRouter(prefix='/api/workbench/file-pickup')
ROOT = Path(__file__).parent / '.local_downloads'
CONFIG = ROOT / 'file_pickup_sources.json'
LOCK = threading.RLock()
LIST_TIMEOUT = 20.0
PROBE_TIMEOUT = 5.0
MAX_SOURCES = 20
MAX_ENTRIES = 3000
_BAD_CHARS = re.compile(r'[\x00-\x1f<>:"|?*]')
_HOST = re.compile(r'[A-Za-z0-9][A-Za-z0-9._-]{0,253}')
_POOL = ThreadPoolExecutor(max_workers=4, thread_name_prefix='file-pickup')
_SHARES_CACHE = {'at': 0.0, 'value': []}

_WINERROR = {
    5: '没有访问权限，请确认共享授权与登录凭据',
    53: '找不到网络路径，请确认对方电脑在线且共享名正确',
    64: '对方电脑已离线或网络中断',
    67: '找不到网络名称，请确认共享名填写正确',
    1219: '存在旧的网络连接，请先在资源管理器断开后重试',
    1326: '登录失败，请先在资源管理器访问该共享并勾选记住凭据',
}


def _fail(status, detail):
    raise HTTPException(status, detail)


def parse_unc(value):
    """只接受 UNC 共享路径（电脑名 + 共享名），避免读取本机磁盘或设备路径。"""
    text = str(value or '').strip().replace('/', '\\')
    if len(text) > 400 or not text.startswith('\\\\'):
        _fail(400, '共享路径必须是 \\\\电脑\\共享名 的形式')
    parts = [part for part in text[2:].split('\\') if part]
    if len(parts) < 2:
        _fail(400, '共享路径需包含电脑名或 IP 与共享名')
    if not _HOST.fullmatch(parts[0]):
        _fail(400, '共享路径中的电脑名或 IP 格式无效')
    for part in parts:
        if part in ('.', '..') or _BAD_CHARS.search(part) or len(part) > 120 or part != part.strip():
            _fail(400, '共享路径包含无效字符或相对路径')
    return '\\\\' + '\\'.join(parts)


def clean_relative(value):
    text = str(value or '').replace('/', '\\').strip('\\')
    if len(text) > 1000:
        _fail(400, '目录层级过深')
    parts = [part for part in text.split('\\') if part]
    for part in parts:
        if part in ('.', '..') or _BAD_CHARS.search(part) or part != part.strip():
            _fail(400, '目录路径无效')
    return '\\'.join(parts)


def confined_target(root, relative):
    base = root.rstrip('\\')
    target = ntpath.normpath(ntpath.join(base, relative)) if relative else base
    norm_base = ntpath.normcase(base)
    norm_target = ntpath.normcase(target)
    if norm_target != norm_base and not norm_target.startswith(norm_base + '\\'):
        _fail(403, '路径超出共享文件夹范围')
    return target


def _timed(fn, *args):
    future = _POOL.submit(fn, *args)
    try:
        return future.result(timeout=LIST_TIMEOUT)
    except FutureTimeout:
        _fail(504, '共享文件夹访问超时，请确认对方电脑在线且共享可访问')
    except OSError as error:
        _fail(502, '无法读取共享文件夹：' + _WINERROR.get(getattr(error, 'winerror', None), '网络或权限异常，请先在资源管理器访问该共享'))


def _probe(path):
    future = _POOL.submit(os.path.isdir, path)
    try:
        return bool(future.result(timeout=PROBE_TIMEOUT))
    except Exception:
        return False


def _config_file() -> Path:
    if CONFIG != (ROOT / 'file_pickup_sources.json'):
        return CONFIG
    try:
        from workspace_context import current_workspace, is_isolated_workspace
        wid = current_workspace()
        if is_isolated_workspace(wid):
            target = ROOT / 'workspaces' / wid / 'file_pickup_sources.json'
            target.parent.mkdir(parents=True, exist_ok=True)
            return target
    except Exception:
        pass
    return CONFIG


def _load():
    cfg = _config_file()
    with LOCK:
        if not cfg.is_file():
            return []
        try:
            value = json.loads(cfg.read_text('utf-8'))
        except (OSError, ValueError):
            return []
    rows = value.get('sources') if isinstance(value, dict) else None
    if not isinstance(rows, list):
        return []
    result = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        if not isinstance(row.get('id'), str) or not isinstance(row.get('name'), str) or not isinstance(row.get('unc'), str):
            continue
        result.append({'id': row['id'], 'name': row['name'][:40], 'unc': row['unc'][:400], 'created': row.get('created', '')})
    return result


def _save(rows):
    cfg = _config_file()
    with LOCK:
        cfg.parent.mkdir(parents=True, exist_ok=True)
        temp = cfg.with_suffix('.json.tmp')
        temp.write_text(json.dumps({'sources': rows}, ensure_ascii=False, indent=2), 'utf-8')
        os.replace(temp, cfg)


def _source(key):
    return next((row for row in _load() if row['id'] == key), None)


def _list_dir(path):
    result = []
    with os.scandir(path) as entries:
        for entry in entries:
            try:
                is_dir = entry.is_dir()
                stat = entry.stat()
            except OSError:
                continue
            result.append({
                'name': entry.name,
                'dir': is_dir,
                'size': 0 if is_dir else stat.st_size,
                'mtime': stat.st_mtime,
            })
            if len(result) >= MAX_ENTRIES:
                break
    result.sort(key=lambda row: (not row['dir'], row['name'].casefold()))
    return result


def _local_addresses():
    values = {'127.0.0.1'}
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            values.add(info[4][0])
    except OSError:
        pass
    return values


def _local_client(request):
    """本机通过局域网 IP 打开时也算本机，便于看到共享给同事的信息。"""
    if bootstrap_allowed(request):
        return True
    peer = request.client.host if request.client else ''
    return bool(peer) and peer in _local_addresses()


def _lan_urls(port):
    urls = set()
    for address in _local_addresses():
        if address.startswith('127.') or address.startswith('169.254.'):
            continue
        urls.add(f'http://{address}:{port}')
    return sorted(urls)


def _smb_shares():
    now = time.monotonic()
    if now - _SHARES_CACHE['at'] < 60:
        return _SHARES_CACHE['value']
    script = '[Console]::OutputEncoding=[Text.Encoding]::UTF8; Get-SmbShare | Select-Object Name,Path | ConvertTo-Json -Compress'
    shares = []
    try:
        completed = subprocess.run(
            ['powershell', '-NoProfile', '-Command', script],
            capture_output=True, timeout=10,
            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0),
        )
        raw = completed.stdout.decode('utf-8-sig', 'ignore').strip()
        value = json.loads(raw) if raw else []
        if isinstance(value, dict):
            value = [value]
        for row in value if isinstance(value, list) else []:
            if isinstance(row, dict) and isinstance(row.get('Name'), str) and isinstance(row.get('Path'), str):
                shares.append({'name': row['Name'], 'path': row['Path']})
    except (OSError, ValueError, subprocess.SubprocessError):
        shares = []
    _SHARES_CACHE.update(at=now, value=shares)
    return shares


@router.get('/sources')
def sources(request: Request):
    require_account(request)
    return {'sources': _load(), 'max': MAX_SOURCES}


@router.post('/sources')
def add_source(payload: dict, request: Request):
    validate_write_request(request)
    require_account(request)
    if not isinstance(payload, dict) or set(payload) != {'name', 'unc'}:
        _fail(400, '请填写电脑名称与共享路径')
    name = payload.get('name')
    if not isinstance(name, str) or not 1 <= len(name.strip()) <= 30 or _BAD_CHARS.search(name):
        _fail(400, '电脑名称需为 1 至 30 个有效字符')
    unc = parse_unc(payload.get('unc'))
    with LOCK:
        rows = _load()
        if len(rows) >= MAX_SOURCES:
            _fail(409, f'最多添加 {MAX_SOURCES} 台共享电脑')
        if any(row['unc'].casefold() == unc.casefold() for row in rows):
            _fail(409, '该共享路径已存在')
        row = {'id': uuid.uuid4().hex, 'name': name.strip(), 'unc': unc,
               'created': datetime.now(timezone.utc).isoformat()}
        _save(rows + [row])
    return {'source': {**row, 'reachable': _probe(unc)}}


@router.post('/sources/{key}/check')
def check_source(key: str, payload: dict, request: Request):
    validate_write_request(request)
    require_account(request)
    if payload != {}:
        _fail(400, '检查请求无效')
    row = _source(key)
    if row is None:
        _fail(404, '共享电脑不存在')
    return {'reachable': _probe(row['unc'])}


@router.delete('/sources/{key}')
def remove_source(key: str, request: Request):
    validate_write_request(request)
    require_account(request)
    with LOCK:
        rows = _load()
        remain = [row for row in rows if row['id'] != key]
        if len(remain) == len(rows):
            _fail(404, '共享电脑不存在')
        _save(remain)
    return {'removed': True}


@router.get('/sources/{key}/list')
def list_shared(key: str, request: Request, path: str = ''):
    require_account(request)
    row = _source(key)
    if row is None:
        _fail(404, '共享电脑不存在')
    relative = clean_relative(path)
    target = confined_target(row['unc'], relative)
    entries = _timed(_list_dir, target)
    return {
        'path': relative,
        'parent': '\\'.join(relative.split('\\')[:-1]) if relative else None,
        'entries': entries,
    }


@router.get('/sources/{key}/download')
def download_shared(key: str, request: Request, path: str = ''):
    require_account(request)
    row = _source(key)
    if row is None:
        _fail(404, '共享电脑不存在')
    relative = clean_relative(path)
    if not relative:
        _fail(400, '请选择要下载的文件')
    target = confined_target(row['unc'], relative)
    if not _timed(os.path.isfile, target):
        _fail(404, '文件不存在或已被移动')
    media = mimetypes.guess_type(target)[0] or 'application/octet-stream'
    return FileResponse(target, filename=os.path.basename(target), media_type=media,
                        headers={'Cache-Control': 'no-store'})


@router.get('/share-info')
def share_info(request: Request):
    require_account(request)
    local = _local_client(request)
    try:
        from download_jobs import configured_output_root
        root = str(configured_output_root())
    except Exception:
        return {'local': local, 'path': '', 'shared': False, 'share_name': '', 'shares': [],
                'lan_urls': [], 'error': '本机成品目录不可用'}
    if not local:
        return {'local': False, 'path': '', 'shared': False, 'share_name': '', 'shares': [],
                'lan_urls': [], 'error': ''}
    shares = _smb_shares()
    match = next((item for item in shares
                  if item['path'].rstrip('\\').casefold() == root.rstrip('\\').casefold()), None)
    port = request.url.port or 3000
    return {
        'local': True,
        'path': root,
        'shared': bool(match),
        'share_name': match['name'] if match else '',
        'shares': shares,
        'lan_urls': _lan_urls(port),
        'error': '' if shares else '未能读取本机共享列表，请在 Windows 中手动确认',
    }