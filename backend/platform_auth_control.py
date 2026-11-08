"""Per personal process: read-only probes and reversible local session disconnects."""
from contextlib import contextmanager, nullcontext
from datetime import datetime, timezone
import hashlib
import os
from pathlib import Path
import re
import threading
import time
import uuid

from fastapi import APIRouter, HTTPException, Request
from download_accounts import require_account, require_admin
from fengshen_auth import BROKER
import binding_source_auth as sources

KEYS = ('fengshen', 'lanorange', 'baize', 'xiaoxiang')
LOCKS = {key: threading.RLock() for key in KEYS}
META = {}
router = APIRouter(prefix='/api/fengshen-downloads/platform-auth')


def validate(source):
    if source not in KEYS: raise HTTPException(404, '平台不存在')


def target(source):
    if source == 'xiaoxiang':
        from xiaoxiang_source_auth import AUTH
        return AUTH
    return sources.AUTH


def files(source):
    if source == 'fengshen': return [BROKER.vault.path]
    if source == 'xiaoxiang':
        from xiaoxiang_lighthouse import SESSION_FILE
        return [SESSION_FILE]
    return [sources.session_path(source), sources.state_path(source)]


def version(source):
    digest = hashlib.sha256()
    for path in files(source):
        if path.is_symlink(): raise HTTPException(409, '会话文件路径异常，请联系管理员')
        digest.update(path.name.encode())
        if path.exists():
            if path.stat().st_size > 1024 * 1024: raise HTTPException(409, '会话文件异常，请联系管理员')
            digest.update(path.read_bytes())
    return digest.hexdigest()


def status(source):
    validate(source)
    base = BROKER.status('download_shared') if source == 'fengshen' else target(source).status() if source == 'xiaoxiang' else target(source).status(source)
    fingerprint = version(source)
    meta = META.get(source, {})
    active = base.get('busy') or base.get('state') in ('starting', 'waiting_login', 'refreshing')
    if meta.get('session_version') == fingerprint and not active and meta.get('checked_at', '') >= base.get('checked_at', ''):
        base = {**base, **{k: v for k, v in meta.items() if k != '_clock'}}
    from auth_diagnostics import history
    from function_availability import snapshot
    return {**base, 'capabilities': snapshot(source, fingerprint), 'diagnostics': history(source), 'source': source, 'session_version': fingerprint, 'saved': any(p.exists() for p in files(source))}


def display_identity(data):
    """Use explicit public identity fields only; never decode credential payloads."""
    candidates = [data] + [data.get(k) for k in ('user', 'userInfo', 'sysUser') if isinstance(data.get(k), dict)]
    result = {}
    for kind, keys in (('account_label', ('nickName', 'userName', 'loginName', 'accountName')),
                       ('organization', ('agencyName', 'companyName', 'merchantName'))):
        value = next((str(row[k]).strip() for row in candidates for k in keys if isinstance(row.get(k), (str, int)) and str(row[k]).strip()), '')
        value = re.sub(r'[\x00-\x1f\x7f]', '', value)[:80]
        value = re.sub(r'(?<!\d)1\d{10}(?!\d)', lambda m: m[0][:3]+'****'+m[0][-4:], value)
        value = re.sub(r'(?<!\d)\d{15,18}[\dXx]?(?!\d)', '***', value)
        value = re.sub(r'([^\s@])[^\s@]*@([^\s@]+)', r'\1***@\2', value)
        if value: result[kind] = value
    if not result.get('organization'):
        ref = next((str(row[k]) for row in candidates for k in ('agencyId', 'merchantId', 'companyId') if isinstance(row.get(k), (str, int)) and re.fullmatch(r'[A-Za-z0-9_-]{1,40}', str(row[k]))), '')
        if ref: result['organization_reference'] = ref
    return result


@contextmanager
def operation(source):
    validate(source)
    lock = LOCKS[source]
    if not lock.acquire(blocking=False): raise HTTPException(409, '此平台正在检测或切换，请稍候')
    try: yield
    finally: lock.release()


def probe(source, deep=False):
    from fengshen_bill import AuthenticationRequired
    from fengshen_http import FengshenHttpClient
    from xiaoxiang_lighthouse import SessionExpired
    if source == 'fengshen':
        saved = BROKER.vault.load()
        if not saved: raise AuthenticationRequired('没有已保存会话')
        client = FengshenHttpClient(saved)
        client.timeout, client.attempts = (3, 6), 1
        try: return display_identity(client.identity())
        finally: client.close()
    if source in sources.SOURCES:
        token = sources.load_token(source)
        if not token: raise AuthenticationRequired('没有已保存会话')
        with sources.client(source, token) as client:
            return display_identity(sources.identity(source, client, timeout=(3, 6)))
    import xiaoxiang_lighthouse as lighthouse
    from xiaoxiang_board import board_probe
    saved = lighthouse.load_state()
    if not saved: raise SessionExpired('没有已保存会话')
    auth = target(source)
    callbacks = [('lighthouse', auth.probe_lighthouse)]
    if deep: callbacks.append(('board', lambda state: board_probe(state, timeout=(3, 8))))
    for name, callback in callbacks:
        auth.stage(name, 'checking')
        try: callback(saved)
        except SessionExpired:
            auth.stage(name, 'error')
            raise
        except Exception:
            auth.stage(name, 'unknown')
            raise
        auth.stage(name, 'ready')
    if not deep:
        return {'verification_level': 'light', 'verification_scope': '仅验证灯塔会话；看板下载权限需单独验证', 'stages': {**auth.stages, 'board': 'unknown'}}
    return {'verification_level': 'deep', 'verification_scope': '灯塔与商配送看板两段只读查询通过；未提交导出', 'stages': dict(auth.stages)}


def check(source, force=False, deep=False):
    from fengshen_bill import AuthenticationRequired
    from xiaoxiang_lighthouse import SessionExpired
    with operation(source):
        before = status(source)
        if before.get('busy') or before['state'] in ('starting', 'waiting_login', 'refreshing'):
            raise HTTPException(409, '认证正在进行，请先完成或取消认证')
        meta = META.get(source, {})
        if not force and (not deep or meta.get('verification_level') == 'deep') and meta.get('session_version') == before['session_version'] and time.monotonic()-meta.get('_clock', 0) < 20:
            return before
        started = time.monotonic()
        result = {'session_version': before['session_version'], 'checked_at': datetime.now(timezone.utc).isoformat(), '_clock': time.monotonic()}
        if not before['saved']:
            result.update(state='signed_out', message='尚未保存此平台会话，请点击登录')
        else:
            try:
                result.update(probe(source, deep=True) if deep else probe(source), state='ready', message='已复用本机加密会话，无需重新登录')
                if result.get('verification_level') == 'light':
                    result.update(state='partial', message='灯塔会话有效；商配送看板下载权限尚未在本次检测中验证')
                result['verified_at'] = result['checked_at']
            except (AuthenticationRequired, SessionExpired, sources.SourceAuthenticationRequired):
                if source == 'xiaoxiang' and target(source).stages.get('board') == 'error':
                    result.update(state='partial', message='灯塔会话仍有效；知了看板登录已失效，仅在下载日维度骑手分析时需要重新扫码')
                elif source == 'xiaoxiang':
                    message = ('灯塔会话仍有效；知了看板登录未完成，请点击登录继续（无需重新发送短信）'
                               if target(source).stages.get('lighthouse') == 'ready'
                               else '官方已确认需要重新认证，原会话保留，请点击登录')
                    result.update(state='login_required', error_code='AUTH_REQUIRED', message=message)
                else:
                    message = '蓝橙会话已失效，请重新扫码；原会话保留' if source=='lanorange' else '官方已确认需要重新认证，原会话保留，请点击登录'
                    result.update(state='login_required', error_code='AUTH_REQUIRED', message=message)
            except Exception as exc:
                import requests
                cause = exc
                for _ in range(4):
                    if not getattr(cause, '__cause__', None): break
                    cause = cause.__cause__
                code = 'TIMEOUT' if isinstance(cause, requests.Timeout) else 'NETWORK' if isinstance(cause, requests.ConnectionError) else 'UNCONFIRMED'
                result.update(state='unknown', error_code=code, message='本次连接未能确认，请检查网络后重试；原会话保留')
        if result['state'] not in ('ready', 'partial'):
            for key in ('account_label', 'organization', 'organization_reference', 'verified_at'):
                if key in before: result[key] = before[key]
        if version(source) != before['session_version']: raise HTTPException(409, '会话已变化，请重新检查')
        controller = BROKER if source == 'fengshen' else target(source)
        with controller.lock:
            if source == 'fengshen':
                if not BROKER.active: BROKER.update(result['state'], result['message'])
            elif controller.states.get(source, {}).get('state') not in ('starting', 'waiting_login', 'refreshing'):
                controller.states[source] = {key: value for key, value in result.items() if not key.startswith('_')}
        result['duration_ms'] = round((time.monotonic() - started) * 1000)
        from auth_diagnostics import record
        result['diagnostics_saved'] = record(source, result)
        META[source] = result
        return status(source)


@contextmanager
def idle_guard():
    """Hold the task creation lock and collection lock through local credential moves."""
    from parttime_source import COLLECTION_LOCK
    from download_jobs import get_manager, ACTIVE_STATUSES
    from workbench import RUNNERS
    if not COLLECTION_LOCK.acquire(blocking=False): raise HTTPException(409, '资料采集正在进行，请任务结束后再切换账号')
    try:
        from lanorange_approvals import has_active
        from lanorange_price_export import has_active as prices_active
        if has_active() or prices_active():raise HTTPException(409, '蓝橙价格审批或导出正在执行，请结束任务后再退出或切换平台账号')
        manager = get_manager()
        with manager._lock:
            with manager._connection() as db:
                active = db.execute('SELECT 1 FROM download_runs WHERE status IN (?,?,?,?) LIMIT 1', tuple(sorted(ACTIVE_STATUSES))).fetchone()
            if active or any(not task.done() for task in list(RUNNERS)):
                raise HTTPException(409, '当前有排队或运行中的任务，请结束后再退出或切换平台账号')
            yield
    finally: COLLECTION_LOCK.release()


def disconnect(source, expected, *, guarded=False):
    with operation(source), (nullcontext() if guarded else idle_guard()):
        if expected != version(source): raise HTTPException(409, '会话已更新，请重新检查后再确认退出')
        controller = BROKER if source == 'fengshen' else target(source)
        with controller.lock:
            if source == 'fengshen': busy = bool(BROKER.active)
            else: busy = bool(controller.workers.get(source) and controller.workers[source].is_alive()) or controller.states.get(source, {}).get('state') in ('starting', 'waiting_login', 'refreshing')
            if busy: raise HTTPException(409, '认证正在进行，请先取消认证并等待窗口结束')
            retained = False
            if source == 'xiaoxiang':
                # 退出只注销灯塔（passport）；在归档前把看板 SSO 子集留成本机缓存，
                # 下次登录预置进浏览器即可像普通浏览器一样免扫大象。
                try:
                    from xiaoxiang_lighthouse import load_state as load_xiaoxiang_state
                    from xiaoxiang_board import save_board_state as cache_xiaoxiang_board
                    snapshot = load_xiaoxiang_state()
                    if snapshot is not None:
                        cache_xiaoxiang_board(snapshot)
                        retained = True
                except Exception:
                    retained = False
            moved = []
            destination = files(source)[0].parent / '.signedout' / uuid.uuid4().hex
            try:
                for original in files(source):
                    if original.exists():
                        destination.mkdir(parents=True, exist_ok=True)
                        archived = destination / original.name
                        os.replace(original, archived)
                        moved.append((original, archived))
            except OSError:
                for original, archived in reversed(moved): os.replace(archived, original)
                raise HTTPException(409, '本机会话归档未完成，原会话已恢复') from None
            if source == 'fengshen':
                BROKER.saved_digest = None
                BROKER.update('signed_out', '已退出本系统内的风神连接')
            else:
                controller.epochs[source] = controller.epochs.get(source, 0) + 1
                controller.states[source] = {'state': 'signed_out', 'message': (
                    '已退出灯塔登录；本机保留知了看板登录态，重新登录只需美团扫码' if source == 'xiaoxiang' and retained
                    else '已退出此平台的本地连接')}
                for store in (controller.desktop, controller.form_bindings, controller.inputs): store.pop(source, None)
                if source == 'xiaoxiang':
                    controller.resume_state = None
                    controller.stages = {'lighthouse': 'pending', 'board': 'pending'}
                    controller.board_reused = False
            META.pop(source, None)
            return status(source)


def auth_busy(source):
    if source=='fengshen':return bool(BROKER.active)
    controller=target(source)
    with controller.lock:
        worker=controller.workers.get(source)
        return bool(worker.is_alive()) if worker is not None else controller.states.get(source,{}).get('state') in ('starting','waiting_login','refreshing')


def logout(source,expected,timeout=22):
    with operation(source),idle_guard():
        if expected!=version(source):raise HTTPException(409,'登录状态已变化，请重新点击退出')
        if source=='fengshen':
            with BROKER.lock:
                active=BROKER.active
                if active:
                    if active.get('purpose','login')!='login':raise HTTPException(409,'业务验证正在进行，请任务结束后退出')
                    BROKER.submit(active['owner'],active['id'],'cancel')
        elif auth_busy(source):target(source).cancel(source)
        deadline=time.monotonic()+timeout
        while auth_busy(source) and time.monotonic()<deadline:time.sleep(.1)
        if auth_busy(source):raise HTTPException(409,'认证仍在安全结束，原会话保留；请稍候再点击退出')
        return disconnect(source,expected,guarded=True)


@router.post('/{source}/logout')
async def do_logout(source:str,request:Request):
    require_admin(request)
    data=await request.json()
    if not isinstance(data,dict) or data.get('confirm') is not True or not isinstance(data.get('session_version'),str):raise HTTPException(400,'退出请求无效')
    # Run the bounded wait off the ASGI event loop.
    from starlette.concurrency import run_in_threadpool
    return await run_in_threadpool(logout,source,data['session_version'])


@router.get('/{source}')
def get_status(source: str, request: Request):
    require_account(request)
    return status(source)


@router.post('/{source}/check')
def do_check(source: str, request: Request, deep: bool = False):
    require_admin(request)
    return check(source, deep=deep)


@router.post('/{source}/disconnect')
async def do_disconnect(source: str, request: Request):
    require_admin(request)
    data = await request.json()
    if not isinstance(data, dict) or data.get('confirm') is not True: raise HTTPException(400, '请明确确认退出此平台连接')
    return disconnect(source, data.get('session_version'))


@router.post('/{source}/cancel')
def do_cancel(source: str, request: Request):
    require_admin(request)
    validate(source)
    if source == 'fengshen': raise HTTPException(409, '请在风神认证窗口内使用取消按钮；业务任务不会在此被取消')
    target(source).cancel(source)
    return status(source)
