"""Shared, reversible task-list organization. Never removes jobs or artifacts."""
import copy
import datetime as dt
from contextlib import contextmanager
import json
import os
from pathlib import Path
import re
import sqlite3
import tempfile
import threading
import time
import zipfile

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse
from starlette.background import BackgroundTask
from download_accounts import require_account, validate_write_request, bootstrap_allowed
from parttime_source import ROOT

router = APIRouter(prefix='/api/workbench/task-center')
LOCK = threading.RLock()
COLLECT_TTL = 1.5
COLLECT_ACTIVE_TTL = 0.5
_COLLECT_CACHE = {}
_REFRESHING = set()
ENDED = {'success', 'partial', 'error', 'cancelled', 'interrupted'}
ACTIVE = {'queued', 'running', 'waiting_login', 'waiting_manual', 'cancelling', 'preparing', 'stopping'}
ATTENTION = {'waiting_login', 'waiting_manual', 'waiting_materials', 'pending_download', 'ready', 'partial', 'error', 'interrupted', 'needs_review'}
ATTENTION.add('awaiting_confirmation')


@contextmanager
def database():
    path = Path(ROOT) / 'backend' / '.local_downloads' / 'task_center.sqlite3'
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path, timeout=15)
    try:
        with db:
            db.execute("CREATE TABLE IF NOT EXISTS hidden (id TEXT PRIMARY KEY, created TEXT NOT NULL, signature TEXT NOT NULL DEFAULT '')")
            if 'signature' not in {row[1] for row in db.execute('PRAGMA table_info(hidden)')}:
                db.execute("ALTER TABLE hidden ADD COLUMN signature TEXT NOT NULL DEFAULT ''")
            db.execute('CREATE TABLE IF NOT EXISTS pending_hide (id TEXT PRIMARY KEY, created TEXT NOT NULL)')
            if 'members' not in {row[1] for row in db.execute('PRAGMA table_info(pending_hide)')}:
                db.execute("ALTER TABLE pending_hide ADD COLUMN members TEXT NOT NULL DEFAULT ''")
            yield db
    finally:
        db.close()


def _collect_records(request):
    from workbench import task_records
    from lanorange_approvals import get_manager as approvals, scope
    from lanorange_price_export import manager as exports, owner
    records = task_records(request)['records']
    warnings = []
    for kind, read in [('approval', lambda: price_summaries(approvals(), scope(request), 'approval')),
                       ('price-export', lambda: price_summaries(exports(), owner(request), 'price-export'))]:
        try:
            for item in read():
                status = {'completed': 'success', 'failed': 'error', 'stopped': 'cancelled'}.get(item['status'], item['status'])
                records.append(dict(id=f"{kind}:{item['id']}", kind=kind, price_id=item['id'],
                    title='价格批量审批' if kind == 'approval' else '待审每日价格导出',
                    cities=['按业务筛选范围'], datasets=[], systems=['蓝橙'],
                    start='', end='', created_at=dt.datetime.fromtimestamp(item['created'], dt.timezone.utc).isoformat(),
                    updated_at=dt.datetime.fromtimestamp(item['created'], dt.timezone.utc).isoformat(),
                    status=status, files=[], member_ids=[], attempts=[], action_run_id='',
                    available_files=int(item.get('available', False)),
                    completed_items=item.get('completed', 0), total_items=item.get('total', 0), failed_items=0))
        except (HTTPException, sqlite3.Error, OSError):
            warnings.append('价格审批记录暂不可读' if kind == 'approval' else '每日价格记录暂不可读')
    return records, warnings


def _refresh_cache(key, request):
    try:
        value = _collect_records(request)
        with LOCK:
            _COLLECT_CACHE[key] = (time.monotonic(), copy.deepcopy(value))
            if len(_COLLECT_CACHE) > 8:
                oldest = min(_COLLECT_CACHE, key=lambda item: _COLLECT_CACHE[item][0])
                _COLLECT_CACHE.pop(oldest, None)
        return value
    finally:
        with LOCK:
            _REFRESHING.discard(key)


def _refresh_quiet(key, request):
    try:
        _refresh_cache(key, request)
    except Exception:
        pass


def _ws_prefix(request=None) -> str:
    from workspace_context import PRIMARY_WORKSPACE, current_workspace
    if request is not None:
        from download_routes import workspace_owner
        try:
            wid = workspace_owner(request)
        except Exception:
            wid = current_workspace()
    else:
        wid = current_workspace()
    return '' if not wid or wid == PRIMARY_WORKSPACE else f'{wid}::'


def _encode_hid(prefix: str, item_id: str) -> str:
    return prefix + item_id


def _decode_hid(prefix: str, stored_id: str) -> str | None:
    if not prefix:
        return None if '::' in stored_id else stored_id
    return stored_id[len(prefix):] if stored_id.startswith(prefix) else None


def collect(request, force_fresh: bool = False):
    from download_routes import workspace_owner
    try:
        wid = workspace_owner(request)
    except Exception:
        wid = request.headers.get('x-workspace-id', '')
    key = (wid, request.headers.get('x-download-account', ''))
    want_fresh = force_fresh or request.query_params.get('fresh') == '1'
    now = time.monotonic()
    with LOCK:
        hit = _COLLECT_CACHE.get(key)
        if hit and not want_fresh:
            has_active = any(r.get('status') in ACTIVE for r in hit[1][0])
            ttl = COLLECT_ACTIVE_TTL if has_active else COLLECT_TTL
            if now - hit[0] < ttl:
                return copy.deepcopy(hit[1])
            if has_active:
                stale = None
                start = False
            else:
                stale = copy.deepcopy(hit[1])
                start = key not in _REFRESHING
                if start:
                    _REFRESHING.add(key)
        else:
            stale = None
            start = False
    if stale is not None and start:
        from workspace_context import spawn_in_context
        # 仅在空闲态下使用后台静默刷新；存在进行中任务或显式 fresh=1 时同步读取最新状态。
        spawn_in_context(_refresh_quiet, key, request, name='task-center-refresh').start()
        return stale
    return _refresh_cache(key, request)


def _invalidate_cache():
    with LOCK:
        _COLLECT_CACHE.clear()


def price_summaries(manager, scope, kind):
    """List metadata only; never decode approval snapshots or price worksheets."""
    if kind == 'approval':
        with manager.connection() as db:
            rows = [dict(row) for row in db.execute('''SELECT b.id,b.created,b.status,
                (SELECT COUNT(*) FROM items i WHERE i.batch_id=b.id) AS total,
                (SELECT COUNT(*) FROM items i WHERE i.batch_id=b.id AND i.status='success') AS completed
                FROM batches b WHERE b.scope=? ORDER BY b.created DESC''', (scope,))]
        for row in rows:
            row['available'] = row['status'] not in ACTIVE
        return rows
    with manager.db() as db:
        rows = [dict(row) for row in db.execute('SELECT id,created,status,completed,total,rows,bytes FROM exports WHERE scope=? ORDER BY created DESC', (scope,))]
    for row in rows:
        path = (manager.root / row['id'] / 'result.xlsx').resolve()
        from lanorange_price_export import ROOT as price_root
        if manager.root.resolve()==price_root.resolve():
            from delivery_store import project_store
            path=project_store().location('price-export:'+row['id'],'result') or path
        row['available'] = (row['status'] in ('completed','partial')
                            and path.is_file() and path.stat().st_size == row['bytes'])
    return rows


def dataset_group(key):
    if key == 'baize_employees':
        return 'baize'
    if key in ('rider_daily', 'detail_orders', 'detail_kesu', 'detail_reviews', 'rider_archive'):
        return 'xiaoxiang'
    return 'lanorange' if key.startswith('lanorange_') or key == 'abnormal_riders' else 'fengshen'


def created_day(record):
    value = record.get('created_at', '')
    try:
        return dt.datetime.fromisoformat(value.replace('Z', '+00:00')).astimezone(dt.timezone(dt.timedelta(hours=8))).date().isoformat()
    except (ValueError, TypeError):
        return value[:10]


def select_records(records, hidden, filters):
    # An archived task that resumes must be visible again, including its retry chain.
    for record in records:
        record['hidden'] = record['id'] in hidden and record['status'] not in ACTIVE
    archived = filters.get('archived') == '1'
    base = [r for r in records if r['hidden'] == archived]
    def matches(r, ignore_status=False):
        status = filters.get('status', '')
        if not ignore_status and status and not (r['status'] in ACTIVE if status == 'active' else r['status'] in ATTENTION if status == 'attention' else r['status'] == status):
            return False
        if filters.get('kind') and r.get('kind') != filters['kind']:
            return False
        groups = r.get('systems') or [dataset_group(key) for key in r['datasets']]
        tag = filters.get('system', '')
        if tag and tag not in groups and {'lanorange': '蓝橙'}.get(tag) not in groups:
            return False
        module = filters.get('module', '')
        if module:
            if module == 'generate':
                if r.get('kind') != 'generate':
                    return False
            elif module == 'fengshen':
                from task_catalog import GENERATORS
                is_fengshen_gen = r.get('kind') == 'generate' and any(key in GENERATORS for key in r.get('datasets', []))
                if not is_fengshen_gen and (r.get('kind') not in ('download', 'payroll_source') or 'fengshen' not in groups):
                    return False
            elif r.get('kind') not in ('download', 'payroll_source') or module not in groups:
                return False
        date = created_day(r)
        if filters.get('from') and date < filters['from'] or filters.get('to') and date > filters['to']:
            return False
        from download_archive import LABELS
        text = ' '.join([r['id'], r.get('title', ''), *r['cities'], *(LABELS.get(key, key) for key in r['datasets']), *(f['name'] for f in r['files'])]).casefold()
        return filters.get('q', '').strip().casefold() in text
    counted = [r for r in base if matches(r, ignore_status=True)]
    counts = {'all': len(counted), 'active': sum(r['status'] in ACTIVE for r in counted),
              'attention': sum(r['status'] in ATTENTION for r in counted), 'success': sum(r['status'] == 'success' for r in counted)}
    rows = sorted((r for r in counted if matches(r)), key=lambda r: (r.get('created_at', ''), r['id']), reverse=True)
    return rows, counts


def signature(record):
    return json.dumps([record['status'], sorted(record.get('member_ids', []))], ensure_ascii=False)


def hidden_ids(records=None, request=None):
    prefix = _ws_prefix(request)
    with database() as db:
        if records is not None:
            raw_pending = db.execute('SELECT id,created,members FROM pending_hide').fetchall()
            pending = {}
            for stored_id, created, members in raw_pending:
                item_id = _decode_hid(prefix, stored_id)
                if item_id is not None:
                    pending[item_id] = (stored_id, created, members)
            for record in records:
                if record['id'] in pending and record['status'] not in ACTIVE:
                    stored_id, created, members = pending[record['id']]
                    if not members or members == json.dumps(sorted(record.get('member_ids', []))):
                        db.execute('INSERT OR REPLACE INTO hidden (id,created,signature) VALUES (?,?,?)', (_encode_hid(prefix, record['id']), created, signature(record)))
                    db.execute('DELETE FROM pending_hide WHERE id=?', (stored_id,))
            hidden = {}
            for stored_id, sig in db.execute('SELECT id, signature FROM hidden').fetchall():
                item_id = _decode_hid(prefix, stored_id)
                if item_id is not None:
                    hidden[item_id] = (stored_id, sig)
            changed = [(hidden[r['id']][0],) for r in records if r['id'] in hidden and
                       (r['status'] in ACTIVE or hidden[r['id']][1] and hidden[r['id']][1] != signature(r))]
            db.executemany('DELETE FROM hidden WHERE id=?', changed)
        result = set()
        for (stored_id,) in db.execute('SELECT id FROM hidden').fetchall():
            item_id = _decode_hid(prefix, stored_id)
            if item_id is not None:
                result.add(item_id)
        return result


@router.get('')
def listing(request: Request, page: int = 1, page_size: int = 20):
    require_account(request)
    if page < 1 or page_size not in (20, 50, 100):
        raise HTTPException(400, '分页参数无效')
    records, warnings = collect(request)
    rows, counts = select_records(records, hidden_ids(records, request), request.query_params)
    pages = max(1, (len(rows) + page_size - 1) // page_size)
    page = min(page, pages)
    focus = next((r for r in records if r['id'] == request.query_params.get('focus')), None)
    return dict(records=rows[(page-1)*page_size:page*page_size], focused=focus, total=len(rows), page=page, pages=pages,
                counts=counts, warnings=warnings)


@router.get('/organize-preview')
def organize_preview(request: Request):
    require_account(request)
    records, warnings = collect(request)
    if warnings:
        raise HTTPException(503, '部分记录暂不可读，请恢复连接后整理')
    filters = dict(request.query_params)
    filters.update(status='success', archived='0')
    rows, _ = select_records(records, hidden_ids(records, request), filters)
    if len(rows) > 10000:
        raise HTTPException(400, '任务过多，请缩小创建日期范围后整理')
    return {'records': [{key:r.get(key) for key in ('id','kind','title','datasets')} for r in rows]}


@router.post('/visibility')
def visibility(payload: dict, request: Request):
    validate_write_request(request)
    require_account(request)
    prefix = _ws_prefix(request)
    ids = payload.get('ids')
    restore = payload.get('restore', False)
    if not isinstance(ids, list) or not ids or len(ids) > 10000 or any(not isinstance(key, str) for key in ids) or type(restore) is not bool:
        raise HTTPException(400, '请选择 1 至 10000 个任务')
    with LOCK:
        records, _ = collect(request)
        by_id = {r['id']: r for r in records}
        if any(key not in by_id for key in ids):
            raise HTTPException(404, '部分任务已变化，请刷新列表后重试')
        active = [by_id[key] for key in ids if by_id[key]['status'] in ACTIVE]
        if not restore and active and payload.get('stop_first') is not True:
            raise HTTPException(409, '进行中任务需确认停止后移出')
        if not restore:
            for record in active:
                stop_record(record, request)
        with database() as db:
            if restore:
                db.executemany('DELETE FROM hidden WHERE id=?', [(_encode_hid(prefix, key),) for key in set(ids)])
                db.executemany('DELETE FROM pending_hide WHERE id=?', [(_encode_hid(prefix, key),) for key in set(ids)])
            else:
                now = dt.datetime.now(dt.timezone.utc).isoformat()
                db.executemany('INSERT OR REPLACE INTO hidden (id,created,signature) VALUES (?, ?, ?)', [(_encode_hid(prefix, key), now, signature(by_id[key])) for key in set(ids) if by_id[key]['status'] not in ACTIVE])
                db.executemany('INSERT OR REPLACE INTO pending_hide (id,created,members) VALUES (?,?,?)', [(_encode_hid(prefix, r['id']), now, json.dumps(sorted(r.get('member_ids', [])))) for r in active])
        _invalidate_cache()
    return {'changed': len(set(ids))}


@router.post('/delete')
def delete_tasks(payload: dict, request: Request):
    """Permanently delete finished task center records and optionally clean confined output files."""
    validate_write_request(request)
    user = require_account(request)
    ids = payload.get('ids')
    delete_files = payload.get('delete_files', True)
    if (
        not isinstance(ids, list)
        or not 1 <= len(ids) <= 200
        or any(not isinstance(key, str) or not key.strip() for key in ids)
        or type(delete_files) is not bool
    ):
        raise HTTPException(400, '请选择 1 至 200 个有效任务')
    unique_ids = list(dict.fromkeys(ids))
    with LOCK:
        _invalidate_cache()
        records, _ = collect(request)
        by_id = {r['id']: r for r in records}
        missing = [key for key in unique_ids if key not in by_id]
        if missing:
            raise HTTPException(404, '部分任务不存在或已删除，请刷新列表后重试')
        active = [by_id[key] for key in unique_ids if by_id[key]['status'] in ACTIVE]
        if active:
            raise HTTPException(409, '请先停止执行中或排队中的任务再彻底删除')
        owner = None if user['role'] == 'admin' else user['owner']
        for key in unique_ids:
            record = by_id[key]
            kind = record.get('kind')
            if kind == 'approval':
                from lanorange_approvals import get_manager as approvals, scope as approval_scope, ApprovalError
                from delivery_store import project_store
                try:
                    approvals().delete_batch(approval_scope(request), record['price_id'])
                except ApprovalError as error:
                    raise HTTPException(409 if error.kind == 'busy' else 404, str(error)) from None
                project_store().purge('approval:' + record['price_id'], delete_files=delete_files)
            elif kind == 'price-export':
                from lanorange_price_export import manager as exports, owner as price_owner
                from lanorange_approvals import ApprovalError
                from delivery_store import project_store
                try:
                    exports().delete_export(price_owner(request), record['price_id'], delete_files=delete_files)
                except ApprovalError as error:
                    raise HTTPException(409 if error.kind == 'busy' else 404, str(error)) from None
                project_store().purge('price-export:' + record['price_id'], delete_files=delete_files)
            elif kind == 'payroll' and key.startswith('payroll_'):
                import shutil
                from payroll_inputs import workspace, directory as batch_directory, delivery_store
                wid = workspace(request)
                batch_id = record.get('batch_id') or key[len('payroll_'):]
                delivery_store().purge('payroll:' + wid + ':' + batch_id, delete_files=delete_files)
                if delete_files:
                    upload_base = (Path(ROOT) / 'uploads' / wid).resolve()
                    folder = batch_directory(wid, batch_id).resolve()
                    if folder != upload_base and folder.is_relative_to(upload_base) and folder.is_dir() and not folder.is_symlink():
                        shutil.rmtree(folder, ignore_errors=True)
            else:
                from download_jobs import get_manager, DownloadRequestConflict
                manager = get_manager()
                member_ids = record.get('member_ids') or [record.get('action_run_id') or key]
                try:
                    manager.purge_runs(owner, member_ids, delete_files=delete_files)
                except DownloadRequestConflict as error:
                    raise HTTPException(409, str(error)) from None
                manager.deliveries.purge(key, delete_files=delete_files)
        prefix = _ws_prefix(request)
        with database() as db:
            db.executemany('DELETE FROM hidden WHERE id=?', [(_encode_hid(prefix, key),) for key in unique_ids])
            db.executemany('DELETE FROM pending_hide WHERE id=?', [(_encode_hid(prefix, key),) for key in unique_ids])
        _invalidate_cache()
    return {'deleted': len(unique_ids), 'ids': unique_ids, 'delete_files': delete_files}


def stop_record(record, request):
    if record['kind'] == 'payroll':
        from payroll_inputs import workspace, account
        from payroll_control import stop
        return stop(workspace(request), record['batch_id'], account(request))
    if record['kind'] == 'approval':
        from lanorange_approvals import stop
        return stop(record['price_id'], {'confirm': True}, request)
    if record['kind'] == 'price-export':
        from lanorange_price_export import stop
        return stop(record['price_id'], {}, request)
    from download_jobs import get_manager, ACTIVE_STATUSES
    manager = get_manager()
    user = require_account(request)
    results = []
    for key in record.get('member_ids', []) or [record['action_run_id'] or record['id']]:
        owner = manager.run_owner(key) if user['role'] == 'admin' else user['owner']
        if manager.get_run(owner, key)['status'] in ACTIVE_STATUSES:
            results.append(manager.cancel(owner, key))
    return results


@router.post('/stop')
def stop_task(payload: dict, request: Request):
    validate_write_request(request)
    require_account(request)
    if set(payload) != {'id'} or not isinstance(payload['id'], str):
        raise HTTPException(400, '任务编号无效')
    with LOCK:
        records, _ = collect(request)
        record = next((r for r in records if r['id'] == payload['id']), None)
        if record is None:
            raise HTTPException(404, '任务不存在或不可访问')
        if record['status'] not in ENDED:
            stop_record(record, request)
        _invalidate_cache()
    return {'requested': True}


def directory(request, record_id=None):
    from download_jobs import get_manager, configured_output_root
    from download_records import get_record
    user = require_account(request)
    if record_id is None:
        root = configured_output_root()
        try:
            root.mkdir(parents=True, exist_ok=True)
        except Exception:
            pass
        return root
    if record_id.startswith('payroll_'):
        match = re.fullmatch(r'payroll_([a-f0-9]{32})', record_id)
        if not match:
            raise HTTPException(404, '核算批次编号无效')
        from payroll_inputs import workspace,load,publish_result
        wid=workspace(request)
        try:
            folder,state=load(wid,match.group(1),user['owner'])
        except Exception:
            raise HTTPException(404, '本任务尚无结果目录') from None
        if state.get('status')!='calculated' or not state.get('result',{}).get('output'):
            raise HTTPException(404, '本任务尚未完成核算，暂无结果目录')
        try:
            return publish_result(wid,folder,state)
        except Exception:
            raise HTTPException(404, '核算结果目录不可用或已被移动') from None
    manager = get_manager()
    owner = None if user['role'] == 'admin' else user['owner']
    if record_id.startswith('price-export:'):
        from lanorange_price_export import manager as prices, owner as price_owner
        try:
            return prices().result(price_owner(request), record_id.split(':',1)[1]).parent
        except Exception:
            raise HTTPException(404, '价格导出文件尚未生成或不可用') from None
    if record_id.startswith('approval:'):
        from lanorange_approvals import get_manager as approvals, scope
        from delivery_store import approval_delivery
        return approval_delivery(approvals(),scope(request),record_id.split(':',1)[1]).parent
    try:
        record = get_record(manager, owner, record_id)
    except Exception:
        raise HTTPException(404, '任务目录不存在或不可访问') from None
    run_id = record_id if record_id != record['id'] and record_id in (record.get('member_ids') or ()) else record.get('action_run_id') or record['id']
    run_owner = manager.run_owner(run_id) if owner is None else owner
    published = manager.deliveries.directory(record['id'])
    if published is not None and published.is_dir():
        return published
    try:
        target = manager.publish_delivery(owner, record['id'])
        if target is not None:
            return target
    except Exception:
        pass
    try:
        run_dir = manager._run_directory(run_owner, run_id)
        if run_dir is not None and run_dir.is_dir():
            return run_dir
    except Exception:
        pass
    root = configured_output_root()
    try:
        root.mkdir(parents=True, exist_ok=True)
    except Exception:
        pass
    return root


@router.get('/directory')
def directory_info(request: Request, record_id: str | None = None):
    path = directory(request, record_id)
    return {'path': str(path), 'exists': path.is_dir(), 'can_open': bootstrap_allowed(request) and os.name == 'nt'}


@router.post('/directory/open')
def open_directory(payload: dict, request: Request):
    validate_write_request(request)
    if not bootstrap_allowed(request):
        raise HTTPException(403, '仅运行本系统的电脑可以打开本机目录，请下载文件或复制共享路径')
    key = payload.get('record_id')
    if set(payload) - {'record_id'}:
        raise HTTPException(400, '目录只能由任务编号定位，不能传入任意路径')
    if key is not None and not isinstance(key, str):
        raise HTTPException(400, '任务编号无效')
    path = directory(request, key)
    if not path.is_dir():
        raise HTTPException(404, '目录尚未生成或已被移动')
    if os.name != 'nt':
        raise HTTPException(400, '当前主机不支持打开 Windows 目录，请复制路径')
    os.startfile(str(path))
    return {'opened': True, 'path': str(path)}


@router.post('/bundle')
def batch_bundle(payload: dict, request: Request):
    validate_write_request(request)
    user = require_account(request)
    ids = payload.get('ids')
    if not isinstance(ids, list) or not 1 <= len(ids) <= 20 or any(not isinstance(key, str) for key in ids):
        raise HTTPException(400, '每次可打包 1 至 20 个资料下载或报表任务')
    from download_jobs import get_manager
    from download_records import record_bundle
    manager = get_manager()
    owner = None if user['role'] == 'admin' else user['owner']
    records, _ = collect(request)
    by_id = {r['id']: r for r in records}
    if any(key not in by_id or by_id[key].get('kind') not in ('download', 'generate', 'payroll_source') or not by_id[key]['available_files'] for key in ids):
        raise HTTPException(409, '批量领取只支持有可用文件的资料下载和报表任务，其他任务请单独领取')
    base = manager.db_path.parent / 'bundles'
    base.mkdir(parents=True, exist_ok=True)
    handle, name = tempfile.mkstemp(suffix='.zip', dir=base)
    os.close(handle)
    target = Path(name)
    try:
        with zipfile.ZipFile(target, 'w', zipfile.ZIP_STORED, allowZip64=True) as archive:
            for key in dict.fromkeys(ids):
                path, filename = record_bundle(manager, owner, key)
                try:
                    archive.write(path, f"{key[:8]}_{filename}")
                finally:
                    path.unlink(missing_ok=True)
        return FileResponse(target, filename='批量任务结果.zip', media_type='application/zip',
                            background=BackgroundTask(target.unlink, missing_ok=True))
    except BaseException:
        target.unlink(missing_ok=True)
        raise
