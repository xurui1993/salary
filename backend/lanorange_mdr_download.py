"""新蓝橙原始资料下载：分页总数核对 + 官方导出文件留存。"""
import hashlib
import json
import time
import zipfile
from pathlib import Path

import requests

from binding_source_auth import SOURCES, SourceAuthenticationRequired
from binding_sources_http import authenticated
from fengshen_bill import BillCollectionError, atomic_json
from lanorange_mdr_catalog import (API_PREFIX, build_params, city_identity, dataset_meta,
                                   match_city)

SOURCE = 'lanorange_mdr'
MAX_BYTES = 512 * 1024 * 1024
TIMEOUT = (10, 300)


def _base(path):
    return 'https://' + SOURCES[SOURCE]['host'] + API_PREFIX + path


def _json(session, path, params, log=None):
    response = session.get(_base(path), params=params, timeout=TIMEOUT, allow_redirects=False)
    if response.status_code in (401, 403):
        raise SourceAuthenticationRequired('新蓝橙登录已失效，请重新扫码认证')
    if response.status_code != 200:
        raise BillCollectionError(f'新蓝橙查询失败（HTTP {response.status_code}）')
    try:
        payload = response.json()
    except ValueError:
        raise BillCollectionError('新蓝橙查询返回内容无法解析，请检查平台状态') from None
    if not isinstance(payload, dict):
        raise BillCollectionError('新蓝橙查询响应结构异常')
    code = str(payload.get('code'))
    if code == '401':
        raise SourceAuthenticationRequired('新蓝橙登录已失效，请重新扫码认证')
    if code not in ('200', '0'):
        message = str(payload.get('msg') or payload.get('message') or '查询失败')
        raise BillCollectionError('新蓝橙查询失败：' + message[:120])
    return payload.get('data')


def platform_cities(log, cancelled):
    # 平台 /admin/base/project/cities 返回的是授权城市 ID 列表，名称需结合
    # /admin/base/area/cities 参考表；统一由目录模块归一化为 {cityName, id, projectCode}。
    from lanorange_mdr_directory import platform_rows
    rows = platform_rows(log, cancelled)
    if not isinstance(rows, list):
        raise BillCollectionError('新蓝橙城市清单结构异常，未提交导出')
    return rows


def resolve_city(log, cancelled, city):
    rows = platform_cities(log, cancelled)
    matched = match_city(rows, city)
    if matched is None:
        available = [str(row.get('cityName')) for row in rows
                     if isinstance(row, dict) and row.get('cityName')]
        hint = '、'.join(dict.fromkeys(available))[:160]
        raise BillCollectionError(
            f'新蓝橙未找到城市“{city}”，请确认平台授权范围'
            + (f'（当前账号可用城市：{hint}）' if hint else ''))
    city_id, project_code = city_identity(matched)
    if city_id is None:
        raise BillCollectionError(f'新蓝橙城市“{city}”编号异常，未提交导出')
    return city_id, project_code


def _export(session, path, params, target, cancelled):
    target = Path(target)
    if target.exists():
        target.unlink()
    ledger = target.parent / 'http_submission.json'
    started = time.time()
    with ledger.open('w', encoding='utf-8') as stream:
        json.dump({'source': SOURCE, 'endpoint': path, 'params': params,
                   'submission_state': 'unknown', 'transport': 'http', 'started_at': started},
                  stream, ensure_ascii=False)
    temporary = target.with_suffix(target.suffix + '.part')
    try:
        with session.get(_base(path), params=params, stream=True, timeout=TIMEOUT,
                         allow_redirects=False) as response:
            if response.status_code in (401, 403):
                raise SourceAuthenticationRequired('新蓝橙登录已失效，请重新扫码认证')
            if response.status_code != 200:
                raise BillCollectionError(f'新蓝橙导出失败（HTTP {response.status_code}）')
            content_type = str(response.headers.get('Content-Type') or '').lower()
            if 'json' in content_type or 'html' in content_type:
                detail = response.text[:200] if 'json' in content_type else ''
                raise BillCollectionError('新蓝橙导出未返回文件' + (f'：{detail}' if detail else ''))
            written = 0
            with temporary.open('wb') as stream:
                for chunk in response.iter_content(1024 * 256):
                    if cancelled.is_set():
                        raise BillCollectionError('新蓝橙下载已取消，提交回执已保留')
                    if not chunk:
                        continue
                    written += len(chunk)
                    if written > MAX_BYTES:
                        raise BillCollectionError('新蓝橙导出文件超过大小限制')
                    stream.write(chunk)
            if written == 0:
                raise BillCollectionError('新蓝橙导出文件为空')
            temporary.replace(target)
        atomic_json(ledger, {'source': SOURCE, 'endpoint': path, 'params': params,
                             'submission_state': 'submitted', 'bytes': written})
        return target
    finally:
        if temporary.exists():
            temporary.unlink(missing_ok=True)


def verify_file(path, cancelled):
    path = Path(path)
    if not path.is_file() or path.stat().st_size <= 0:
        raise BillCollectionError('新蓝橙导出文件缺失或为空')
    if path.suffix.lower() in ('.xlsx', '.xlsm') or zipfile.is_zipfile(path):
        try:
            with zipfile.ZipFile(path) as archive:
                if archive.testzip() is not None:
                    raise BillCollectionError('新蓝橙导出工作簿损坏')
                names = archive.namelist()
                if not any(name.startswith('xl/worksheets/') for name in names):
                    raise BillCollectionError('新蓝橙导出文件缺少工作表')
        except zipfile.BadZipFile:
            raise BillCollectionError('新蓝橙导出文件无法读取') from None
    elif path.suffix.lower() != '.csv':
        raise BillCollectionError('新蓝橙导出文件格式无法识别')
    if cancelled.is_set():
        raise BillCollectionError('新蓝橙校验已取消，原始文件已保留')
    with path.open('rb') as stream:
        digest = hashlib.file_digest(stream, 'sha256').hexdigest()
    return {'path': path.name, 'bytes': path.stat().st_size, 'sha256': digest}


def collect(dataset, directory, log, cancelled, resume=None, *, city, city_id=None,
            project_code=None, months=None):
    meta = dataset_meta(dataset)
    label = meta['label']
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    receipt_path = directory / 'source_receipt.json'
    if resume:
        source = Path(resume)
        try:
            info = json.loads((source / 'source_receipt.json').read_text(encoding='utf-8'))
        except (OSError, ValueError):
            raise BillCollectionError('新蓝橙原始文件恢复凭据无法读取') from None
        if info.get('dataset') != dataset or info.get('status') != 'validated' or info.get('city') != city:
            raise BillCollectionError('新蓝橙原始文件恢复凭据不符')
        path = source / info['path']
        verified = verify_file(path, cancelled)
        if verified['sha256'] != info.get('sha256') or verified['bytes'] != info.get('bytes'):
            raise BillCollectionError('新蓝橙原始文件校验失败，不能复用')
        target = directory / path.name
        target.write_bytes(path.read_bytes())
        atomic_json(receipt_path, info)
        log('[恢复] 仅复用已完成新蓝橙原始导出，不重新下载')
        return target
    if not city_id:
        city_id, project_code = resolve_city(log, cancelled, city)
    params = build_params(dataset, months=months, city_id=city_id, project_code=project_code)
    with authenticated(SOURCE, log, cancelled) as session:
        page = _json(session, meta['page'], params + [('pageNum', '1'), ('pageSize', '1')], log)
        total = page.get('total') if isinstance(page, dict) else None
        if type(total) is not int or total < 0:
            raise BillCollectionError('新蓝橙分页总数未确认，未提交导出')
        atomic_json(directory / 'query_receipt.json',
                    {'dataset': dataset, 'endpoint': meta['page'], 'params': params, 'query_total': total})
        log(f'[下载] 新蓝橙{label}：{city}，页面总数 {total} 条')
        target = _export(session, meta['export'], params, directory / (label + '.xlsx'), cancelled)
    verified = verify_file(target, cancelled)
    atomic_json(receipt_path, {
        'dataset': dataset, 'label': label, 'status': 'validated', 'city': city,
        'city_id': city_id, 'project_code': project_code, 'months': list(months or []),
        'params': params, 'query_total': total, 'validation': 'integrity',
        'transport': 'http', 'original_unchanged': True, 'payroll_executed': False, **verified})
    log(f'[完成] 新蓝橙{label}：{city} 原始文件已校验，页面总数 {total} 条')
    return target