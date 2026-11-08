"""Workbench settings and immutable deduction versions for payroll batches."""
from datetime import datetime
import asyncio
import hashlib
import json
import math
from pathlib import Path
import shutil
import threading

from fastapi import APIRouter, HTTPException, Request
from fengshen_bill import atomic_json
from parttime_source import ROOT, SourceError

router = APIRouter(prefix='/api/workbench')
SETTINGS_LOCK = threading.RLock()
RUNNERS = set()


async def detached_events(generator):
    """A browser disconnect must not abandon a running payroll generator."""
    queue = asyncio.Queue(maxsize=512)

    def offer(value):
        if queue.full():
            queue.get_nowait()
        queue.put_nowait(value)

    async def produce():
        try:
            async for event in generator:
                offer(event)
        finally:
            offer(None)

    task = asyncio.create_task(produce())
    RUNNERS.add(task)
    task.add_done_callback(RUNNERS.discard)
    while True:
        value = await queue.get()
        if value is None:
            break
        yield value


def validate_rows(rows):
    if not isinstance(rows, list) or not rows or len(rows) > 10000:
        raise SourceError('扣款配置需要 1 至 10000 个站点')
    seen = set()
    for row in rows:
        if not isinstance(row, dict) or not str(row.get('城市') or '').strip() or not str(row.get('团队名称') or '').strip():
            raise SourceError('每个站点都需要城市和团队名称')
        if any(value is not None and (not isinstance(value, (str, int, float, bool)) or
               isinstance(value, float) and not math.isfinite(value)) for value in row.values()):
            raise SourceError('扣款字段必须为文本、有效数字或开关')
        key = tuple(str(row.get(field) or '') for field in ('城市', '团队名称', '团队ID'))
        if key in seen:
            raise SourceError('存在重复站点，请核对城市、团队名称和团队 ID')
        seen.add(key)
    return rows


def version(rows):
    return hashlib.sha256(json.dumps(rows, ensure_ascii=False, sort_keys=True, allow_nan=False).encode()).hexdigest()


def read_defaults(root=None):
    path = Path(root or ROOT) / 'data' / 'config.json'
    try:
        rows = validate_rows(json.loads(path.read_text(encoding='utf-8-sig')))
    except (OSError, ValueError) as exc:
        raise SourceError('默认扣款配置无法读取，请先检查扣款设置') from exc
    return {'rows': rows, 'version': version(rows)}


def deduction_snapshot(state, root=None):
    # A failed run reuses the exact same version; later default edits cannot
    # silently change a batch that has already started calculating.
    previous = state.get('deductions')
    if previous and previous.get('frozen'):
        if version(previous['rows']) != previous['version']:
            raise SourceError('批次扣款快照校验失败')
        return previous
    data = previous or {**read_defaults(root), 'scope': 'default'}
    return {**data, 'rows': validate_rows(data['rows']), 'frozen': True,
            'captured_at': datetime.now().isoformat()}


@router.get('/deductions')
def get_defaults():
    try:
        return read_defaults()
    except SourceError as exc:
        raise HTTPException(400, str(exc)) from None


@router.get('/deduction-stations')
async def deduction_stations(request: Request, platform: str = 'fengshen', city: str = '', refresh: bool = False):
    """Read platform options only. Selection and saving deductions remain separate."""
    from download_accounts import require_account
    require_account(request)
    if platform not in ('fengshen', 'xiaoxiang'):
        raise HTTPException(400, '请选择风神或灯塔')
    if len(city) > 100 or any(ord(char) < 32 for char in city):
        raise HTTPException(400, '城市参数无效')
    from deduction_stations import catalog
    try:
        return await asyncio.to_thread(catalog, platform, city.strip(), refresh)
    except HTTPException:
        raise
    except SourceError as error:
        raise HTTPException(400, str(error)) from None
    except Exception:
        raise HTTPException(502, '站点列表暂不可用，请检查平台连接后重试；原配置保持不变') from None


@router.get('/station-directory')
async def station_directory(request: Request, platform: str = 'fengshen', refresh: bool = False):
    from download_accounts import require_account
    from station_directory import snapshot
    require_account(request)
    return await asyncio.to_thread(snapshot, platform, refresh)


@router.get('/deduction-profiles/{platform}')
async def deduction_profiles(platform: str, request: Request):
    from download_accounts import require_account
    from station_directory import snapshot
    from deduction_confirmation import station_drafts
    require_account(request)
    try:
        return await asyncio.to_thread(station_drafts, platform, ROOT, snapshot(platform))
    except SourceError as error:
        raise HTTPException(400, str(error)) from None


@router.put('/deduction-profiles/{platform}')
async def update_deduction_profiles(platform: str, request: Request):
    from download_accounts import require_admin
    from station_directory import ready_directory
    from deduction_confirmation import save_profile
    require_admin(request)
    payload = await request.json()
    try:
        return await asyncio.to_thread(save_profile, platform, ROOT, payload, ready_directory(platform))
    except SourceError as error:
        raise HTTPException(409, str(error)) from None


@router.get('/batches/{key}/deduction-review')
async def deduction_review(key: str, request: Request, city_id: str = '', refresh: bool = False):
    from download_accounts import require_account
    from payroll_inputs import load, workspace, account, directory, batch_lock
    from station_directory import ready_directory
    from deduction_confirmation import preflight, platform_for
    require_account(request)
    def read():
        with batch_lock(directory(workspace(request), key)):
            folder, state = load(workspace(request), key, account(request))
            if state.get('include_separation'):
                from station_directory import sync_separation
                current = ready_directory('fengshen', city_id or state['plan']['city'])
                choices = [c for c in current['cities'] if c['name'] == state['plan']['city']]
                if not choices or choices[0]['id'] not in current.get('separation_cities', []):
                    sync_separation(state['plan']['city'])
            data = ready_directory(platform_for(state), city_id or state['plan']['city'], refresh=True) if refresh else ready_directory(platform_for(state), city_id or state['plan']['city'])
            return preflight(folder, state, ROOT, data, city_id)
    try:
        return await asyncio.to_thread(read)
    except SourceError as error:
        raise HTTPException(409, str(error)) from None


@router.post('/batches/{key}/separation')
async def enable_separation(key: str, request: Request):
    from download_accounts import require_admin
    from payroll_inputs import load, save, workspace, account, batch_lock, directory, public
    from station_directory import sync_separation
    require_admin(request)
    payload = await request.json()
    if payload != {'enabled': True}:
        raise HTTPException(400, '取分离关联参数无效')
    def write():
        with batch_lock(directory(workspace(request), key)):
            folder, state = load(workspace(request), key, account(request))
            refreshing = state.get('include_separation') is True
            if state['mode'] != 'fengshen' or state['status'] not in ('awaiting_confirmation','pending_download','ready') or (state.get('jobs') and not refreshing) or state.get('deductions', {}).get('frozen'):
                raise SourceError('本批次已开始获取资料或已冻结，不能改写原范围。请收起清单，点击“重新上传”新建含取分离站点的批次；原资料和文件保留。')
            data = sync_separation(state['plan']['city'])
            state['include_separation'] = True
            if not state.get('jobs'):
                state['separation_agencies'] = sorted({s.get('agency_id') or s['city_id'] for s in data['stations'] if '取分离' in s['name'] and s['city'] == state['plan']['city']})
            if not refreshing:
                state.pop('deduction_confirmation', None);state.pop('deduction_intent', None)
                state['status'] = 'awaiting_confirmation'
            save(folder, state)
            return public(state)
    try:
        return await asyncio.to_thread(write)
    except SourceError as error:
        raise HTTPException(409, str(error)) from None


@router.post('/batches/{key}/station-links')
async def link_batch_stations(key: str, request: Request):
    from download_accounts import require_admin
    from payroll_inputs import load, save, workspace, account, directory, batch_lock
    from station_directory import ready_directory
    from deduction_confirmation import preflight, platform_for
    from station_associations import LOCK as ASSOCIATION_LOCK, save as save_associations
    require_admin(request)
    payload = await request.json()
    if not isinstance(payload, dict) or payload.get('confirmed') is not True or not isinstance(payload.get('links'), dict) or not payload['links']:
        raise HTTPException(400, '请明确确认本次站点关联')
    def write():
        with batch_lock(directory(workspace(request), key)), ASSOCIATION_LOCK:
            folder, state = load(workspace(request), key, account(request))
            if state['status'] not in ('ready','awaiting_confirmation','pending_download') or state.get('deductions', {}).get('frozen'):
                raise SourceError('本批次当前不可更改站点关联')
            data = ready_directory(platform_for(state), payload.get('city_id') or state['plan']['city'])
            reviewed = preflight(folder, state, ROOT, data, payload.get('city_id', ''))
            if payload.get('review_version') != reviewed['review_version']:
                raise SourceError('目录或资料已变化，请重新读取后关联')
            allowed = {r['name']: set(r['candidates']) for r in reviewed['association_rows']}
            links = dict(state.get('station_links', {}))
            for name, target in payload['links'].items():
                if name not in allowed or not isinstance(target, str) or (target and target not in allowed[name]):
                    raise SourceError('关联目标不属于当前城市可核实的后台站点，或与申请编号冲突')
                if target: links[name] = target
                else: links.pop(name, None)
            candidate = {**state, 'station_links': links}
            result = preflight(folder, candidate, ROOT, data, payload.get('city_id', ''))
            rejected = {r['name'] for r in result['unresolved']}
            if any(target and name in rejected for name, target in payload['links'].items()):
                raise SourceError('关联与申请编号或当前目录不一致，未保存，请重新核对')
            if payload.get('save_associations') is True:
                choices = {entry['key']: entry for entry in reviewed['station_choices']}
                save_associations(ROOT, platform_for(state), data, {name:choices[target] for name,target in payload['links'].items() if target}, reviewed['association_version'])
            state['station_links'] = links
            state.pop('deduction_confirmation', None)
            state.pop('deduction_intent', None)
            state.setdefault('audit', []).append({'action':'confirm_station_links','links':payload['links'],'saved_for_reuse':payload.get('save_associations') is True,'directory_version':data['session_version'],'at':datetime.now().isoformat()})
            save(folder, state)
            return preflight(folder, state, ROOT, data, payload.get('city_id', ''))
    try:
        return await asyncio.to_thread(write)
    except SourceError as error:
        raise HTTPException(409, str(error)) from None


@router.post('/batches/{key}/deduction-review')
async def confirm_deduction_review(key: str, request: Request):
    from download_accounts import require_account, require_admin
    from payroll_inputs import load, save, workspace, account, directory, batch_lock, public, LOCK
    from station_directory import ready_directory
    from deduction_confirmation import confirm, platform_for
    require_account(request)
    require_admin(request)
    payload = await request.json()
    if not isinstance(payload, dict):
        raise HTTPException(400, '扣款确认参数无效')
    if payload.get('save_defaults') is True:
        require_admin(request)
    def write():
        with batch_lock(directory(workspace(request), key)), LOCK:
            folder, state = load(workspace(request), key, account(request))
            if state['status'] not in ('ready', 'awaiting_confirmation', 'pending_download') or state.get('deductions', {}).get('frozen'):
                raise SourceError('本批次不可再修改，请核对当前状态')
            deduction, receipt = confirm(folder, state, ROOT, ready_directory(platform_for(state), payload.get('city_id') or state['plan']['city']), payload)
            state.update(deductions=deduction, deduction_confirmation=receipt)
            if receipt['stage'] == 'intent':
                state['deduction_intent'] = receipt
                state['status'] = 'pending_download'
            save(folder, state)
            return {**public(state), 'deduction_version': deduction['version']}
    try:
        return await asyncio.to_thread(write)
    except SourceError as error:
        raise HTTPException(409, str(error)) from None


@router.put('/deductions')
async def save_defaults(request: Request):
    from download_accounts import require_admin
    require_admin(request)
    payload = await request.json()
    try:
        if not isinstance(payload, dict):
            raise SourceError('配置参数无效')
        rows = validate_rows(payload.get('rows'))
        with SETTINGS_LOCK:
            current = read_defaults()
            if payload.get('version') != current['version']:
                raise HTTPException(409, '默认配置已被其他页面修改，请重新打开后再保存')
            path = Path(ROOT) / 'data' / 'config.json'
            backup = path.parent / 'config_history' / (datetime.now().strftime('%Y%m%d_%H%M%S_%f') + '.json')
            backup.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, backup)
            atomic_json(path, rows)
        return {'rows': rows, 'version': version(rows)}
    except SourceError as exc:
        raise HTTPException(400, str(exc)) from None


@router.get('/batches')
def batches(request: Request):
    from payroll_inputs import workspace, public
    base = (Path(ROOT) / 'uploads' / workspace(request)).resolve()
    entries = []
    for path in base.glob('payroll_*/manifest.json'):
        if not path.resolve().is_relative_to(base):
            continue
        try:
            state = json.loads(path.read_text(encoding='utf-8'))
            entries.append(public(state))
        except (OSError, ValueError, KeyError):
            continue
    return {'batches': sorted(entries, key=lambda item: item.get('created_at', ''), reverse=True)[:100]}


@router.get('/tasks')
def task_records(request: Request):
    from download_accounts import require_account
    from download_jobs import get_manager
    from download_records import list_records
    from payroll_inputs import workspace, public
    user = require_account(request)
    wid = workspace(request)
    root = (Path(ROOT) / 'uploads').resolve()
    known_jobs, known_batches, payroll = set(), set(), []
    # Only manifests are inspected. Source workbooks and business rows are not
    # read to build the task list, and other workspaces' batches stay private.
    for path in root.glob('*/payroll_*/manifest.json'):
        if not path.resolve().is_relative_to(root):
            continue
        try:
            state = json.loads(path.read_text(encoding='utf-8'))
            owner = path.parent.parent.name
            known_batches.add((owner, state['id']))
            known_jobs.update(state.get('jobs', []))
            if owner != wid:
                continue
            from payroll_control import reconcile
            from payroll_inputs import batch_lock
            with batch_lock(path.parent):
                state = json.loads(path.read_text(encoding='utf-8'))
                reconcile(path.parent, state)
            value = public(state)
            output = state.get('result', {}).get('output') or ''
            try:
                available = bool(output and Path(output).exists())
            except OSError:
                available = False
            mapped = {'calculating': 'running', 'calculated': 'success'}.get(state['status'], state['status'])
            payroll.append({
                'id': 'payroll_' + state['id'], 'kind': 'payroll', 'batch_id': state['id'],
                'cities': [state['plan']['city']], 'datasets': ['payroll'],
                'start': state['plan']['start'], 'end': state['plan']['end'],
                'created_at': state.get('created_at', ''), 'updated_at': state.get('created_at', ''),
                'status': mapped, 'batch_status': state['status'], 'files': [],
                'available_files': int(available), 'output': output,
                'completed_items': sum(item['status'] in ('ready', 'omitted') for item in state['items'].values()),
                'total_items': len(state['items']), 'applicants': state['plan'].get('applicants', 0),
                'failed_items': sum(item['status'] == 'failed' for item in state['items'].values()),
                'member_ids': [], 'attempts': [], 'action_run_id': '',
                'deductions': value.get('deductions'), 'jobs': state.get('jobs', []),
            })
        except (OSError, ValueError, KeyError, TypeError):
            continue
    downloads = list_records(get_manager(), None if user['role'] == 'admin' else user['owner'])
    visible = [record for record in downloads
               if not known_jobs.intersection(record['member_ids'])
               and (record.get('parent_workspace'), record.get('parent_batch_id')) not in known_batches]
    from task_catalog import GENERATORS
    for record in visible:
        if record['kind'] == 'generate':
            targets = set(record['datasets']).intersection(GENERATORS)
            record['source_files'] = [file for file in record['files'] if file['dataset'] not in targets]
            record['files'] = [file for file in record['files'] if file['dataset'] in targets]
            record['available_files'] = sum(file.get('available', True) for file in record['files'])
    return {'records': sorted([*visible, *payroll], key=lambda item: item.get('updated_at', ''), reverse=True)}


@router.get('/batches/{key}/deductions')
def get_batch_deductions(key: str, request: Request):
    from payroll_inputs import load, workspace, account
    try:
        _, state = load(workspace(request), key, account(request))
        return state.get('deductions') or {**read_defaults(), 'scope': 'default', 'frozen': False}
    except SourceError as exc:
        raise HTTPException(400, str(exc)) from None


@router.put('/batches/{key}/deductions')
async def save_batch_deductions(key: str, request: Request):
    from download_accounts import require_admin
    require_admin(request)
    from payroll_inputs import LOCK, load, save, workspace, account
    payload = await request.json()
    try:
        if not isinstance(payload, dict):
            raise SourceError('配置参数无效')
        rows = validate_rows(payload.get('rows'))
        with LOCK:
            folder, state = load(workspace(request), key, account(request))
            if state['status'] in ('calculating', 'calculated') or state.get('deductions', {}).get('frozen'):
                raise HTTPException(409, '本次核算已采用固定配置，请新建批次调整')
            current = state.get('deductions') or read_defaults()
            if payload.get('version') != current['version']:
                raise HTTPException(409, '扣款配置已变化，请重新打开后再保存')
            data = {'rows': rows, 'version': version(rows), 'scope': 'batch', 'frozen': False}
            state['deductions'] = data
            save(folder, state)
            return data
    except SourceError as exc:
        raise HTTPException(400, str(exc)) from None


def reusable_files(state, manager):
    """Only completed, city/date-matching exports may enter a payroll batch."""
    import calendar
    plan = state['plan']
    result = []
    for brief in manager.list_runs(state['download_owner']):
        if brief['status'] != 'success':
            continue
        run = manager.get_run(state['download_owner'], brief['id'])
        for file in run.get('files', []):
            kind = file.get('dataset')
            if kind not in state['items'] or state['items'][kind]['status'] == 'ready' or file.get('artifact_role') == 'summary':
                continue
            if file.get('city') != plan['city']:
                continue
            start, end = plan['start'], plan['end']
            if kind == 'rider_monthly':
                year, month = map(int, plan['month'].split('-'))
                start, end = f'{year:04}-{month:02}-01', f'{year:04}-{month:02}-{calendar.monthrange(year, month)[1]}'
            if file.get('start') != start or file.get('end') != end:
                continue
            if not any(item.get('dataset') == kind and item.get('city') == plan['city'] and item.get('status') == 'success'
                       and item.get('start') == start and item.get('end') == end for item in run.get('items', [])):
                continue
            result.append({'run_id': run['id'], 'file_id': file['id'], 'dataset': kind,
                           'name': file['name'], 'created_at': run.get('created_at', '')})
    return result


@router.get('/batches/{key}/reusable')
def get_reusable(key: str, request: Request):
    from payroll_inputs import load, workspace, account
    from download_jobs import get_manager
    try:
        _, state = load(workspace(request), key, account(request))
        return {'files': reusable_files(state, get_manager()) if state['mode'] == 'fengshen' else []}
    except SourceError as exc:
        raise HTTPException(400, str(exc)) from None


@router.post('/batches/{key}/reuse')
async def reuse(key: str, request: Request):
    from download_accounts import require_admin
    from payroll_inputs import LOCK, load, save, workspace, account, stage, validate_upload, readiness, public
    from download_jobs import get_manager
    require_admin(request)
    payload = await request.json()
    if not isinstance(payload, dict):
        raise HTTPException(400, '资料参数无效')
    try:
        with LOCK:
            folder, state = load(workspace(request), key, account(request))
            if state['mode'] != 'fengshen' or state['status'] not in ('pending_download', 'waiting_materials'):
                raise HTTPException(409, '当前批次不可更换资料，请刷新后检查')
            manager = get_manager()
            candidate = next((file for file in reusable_files(state, manager) if file['run_id'] == payload.get('run_id') and file['file_id'] == payload.get('file_id')), None)
            if not candidate:
                raise SourceError('资料与本次城市、周期或完整性要求不符')
            path, _ = manager.get_file(state['download_owner'], candidate['run_id'], candidate['file_id'])
            validate_upload(path, candidate['dataset'])
            stage(folder, state, candidate['dataset'], path, {'run_id': candidate['run_id'], 'file_id': candidate['file_id'], 'reused': True})
            state['audit'].append({'action': 'reuse_download', **candidate})
            readiness(state)
            if state['status'] != 'ready' and any(item['status'] == 'pending' for item in state['items'].values()):
                state['status'] = 'pending_download'
            save(folder, state)
            return public(state)
    except SourceError as exc:
        raise HTTPException(400, str(exc)) from None
