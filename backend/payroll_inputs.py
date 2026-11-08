"""Payroll input snapshots. Downloads share the download center's durable jobs."""
import asyncio
from dataclasses import asdict
import hashlib
import hashlib_compat
import json
from pathlib import Path
import re
import shutil
import threading
import uuid
import time
import weakref

from fastapi import APIRouter, HTTPException, Request
from parttime_source import (ROOT, SourceError, inspect_source, owned_upload, source_files,
                             clean_rider_bill)
from fengshen_bill import atomic_json

router = APIRouter(prefix='/api/parttime/preparations')
LABELS = {'delivery_fee': '配送费', 'penalty': '违规扣款', 'rider_monthly': '骑手账单',
          'fraud': '欺诈单', 'problem': '问题单', 'payment_binding': '骑手支付绑定',
          'lanorange_part_price': '价格档案'}
LOCK = threading.RLock()
_BATCH_LOCKS = weakref.WeakValueDictionary()
_BATCH_LOCK_GUARD = threading.Lock()


def batch_lock(folder):
    key = str(Path(folder).resolve())
    with _BATCH_LOCK_GUARD:
        value = _BATCH_LOCKS.get(key)
        if value is None:
            value = threading.RLock(); _BATCH_LOCKS[key] = value
        return value



def read_upload_timing(folder):
    file = Path(folder) / '.upload_diagnostics.json'
    try:
        if file.is_symlink() or file.stat().st_size > 16 * 1024:return {}
        value = json.loads(file.read_text(encoding='utf-8'))
        return {key: seconds for key, seconds in value.items()
                if key in ('server_seconds', 'extraction_seconds', 'indexing_seconds')
                and type(seconds) in (int, float) and 0 <= seconds <= 86400}
    except (OSError, ValueError, TypeError, AttributeError):return {}


def digest(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def workspace(request):
    from download_routes import workspace_owner
    return workspace_owner(request)


def account(request):
    from download_accounts import require_account
    return require_account(request)['owner']


def directory(wid, key, root=None):
    if not re.fullmatch(r'[a-f0-9]{32}', key or ''):
        raise SourceError('资料准备编号无效')
    base = (Path(root or ROOT) / 'uploads' / wid).resolve()
    result = (base / ('payroll_' + key)).resolve()
    if not result.is_relative_to(base):
        raise SourceError('资料目录无效')
    return result


def load(wid, key, download_owner=None, root=None):
    folder = directory(wid, key, root)
    try:
        state = json.loads((folder / 'manifest.json').read_text(encoding='utf-8'))
    except (OSError, ValueError):
        raise SourceError('本工作区资料准备记录不存在，请重新上传') from None
    if state['mode'] == 'fengshen' and state['download_owner'] != download_owner:
        raise SourceError('资料准备记录不属于当前下载账户')
    return folder, state


def save(folder, state):
    atomic_json(folder / 'manifest.json', state)


def delivery_store():
    from delivery_store import project_store, DeliveryStore
    from download_jobs import ROOT as project_root
    if Path(ROOT).resolve()==project_root.resolve():return project_store()
    return DeliveryStore(Path(ROOT)/'backend/.local_downloads/deliveries.sqlite3',Path(ROOT)/'outputs/fengshen_downloads')


def publish_result(wid, folder, state):
    from delivery_store import external_delivery
    store=delivery_store();key='payroll:'+wid+':'+state['id']
    output=Path(state.get('result',{}).get('output') or '').resolve()
    existing=store.directory(key)
    if existing is not None and output==existing:return existing
    allowed=(Path(ROOT)/'backend/.local_downloads/workspaces/payroll'/wid/state['id'],Path(ROOT)/'outputs/payroll_batches'/wid/state['id'])
    if not any(output.is_relative_to(base.resolve()) for base in allowed) or output.is_symlink():
        raise SourceError('核算结果不在本批次目录内')
    label='薪资核算_'+state['plan']['city']+'_'+state['plan']['start'][:7]
    if state['result'].get('delivery_layout') == 'payroll_workbooks_v1':
        from payroll_review import payroll_workbooks
        entries=[dict(run_id=key,id=role,path=str(path),name=path.name,city='',dataset=label)
                 for role,path in zip(('payroll','exceptions'),payroll_workbooks(output))]
        destination=store.publish(key,state['created_at'],label,entries,include_manifest=False)
    else:
        destination=external_delivery(key,state['created_at'],label,output,store=store)
    state['result']['output']=str(destination);save(folder,state)
    return destination


def public(state):
    result = {key: state[key] for key in ('id', 'mode', 'plan', 'status', 'items', 'jobs')}
    result.update({key: state[key] for key in ('created_at', 'result', 'performance', 'pause_reason', 'stop_requested', 'execution', 'downloads', 'execution_started_at', 'workflow', 'automatic_deductions', 'input_policy', 'material_note', 'only_separation', 'exclude_separation', 'download_scope', 'execution_logs') if key in state})
    if state.get('deductions'):
        result['deductions'] = {key: value for key, value in state['deductions'].items() if key != 'rows'}
    if state['status'] in ('cancelled', 'interrupted', 'stopping') and state.get('downloads'):
        result['downloads'] = [{**row, 'status':'cancelled','detail':'任务已停止，已有文件保留'} if row['status'] not in ('ready','failed','omitted') else row for row in state['downloads']]
    return result


def stage(folder, state, kind, path, origin):
    target = folder / 'input' / (LABELS[kind] + Path(path).suffix.lower())
    if kind == 'rider_monthly':
        from types import SimpleNamespace
        target = folder / 'input' / ('UB骑手账单_cleaned_' + state['plan']['month'] + '.csv')
        clean_rider_bill(path, target, SimpleNamespace(**state['plan']))
    else:
        shutil.copy2(path, target)
    state['items'][kind] = {'label': LABELS[kind], 'status': 'ready', 'file': target.name,
                            'sha256': digest(target), 'origin': origin}


def validate_upload(path, kind, readability_only=False):
    """Reject wrong/corrupt supplements before payroll can continue."""
    from openpyxl import load_workbook
    import csv
    from itertools import islice
    if not readability_only and not 0 < path.stat().st_size <= 4 * 1024 ** 3:
        raise SourceError('资料为空或超过单文件 4GiB 限制：'+path.name)
    if kind == 'rider_monthly':
        from parttime_source import read_rider_bill
        read_rider_bill(path, cleaned='UB骑手账单_cleaned_' in path.name)
        return
    def matches(row):
        columns = {re.sub(r'\s+', '', str(v or '')).lower() for v in row}
        ids = {'骑手id', '风神id', '风神骑手id', '身份证', '身份证号', '骑手姓名'}
        if kind == 'lanorange_part_price':
            return bool(columns & ids) and bool(columns & {'价格', '单价', '蓝橙单价'})
        if kind == 'payment_binding':
            return bool(columns & ids) and bool(columns & {'绑定情况', '绑定状态', '商翼绑定', '白泽绑定'})
        if kind in ('delivery_fee', 'penalty'):
            return '骑手id' in columns and bool(columns & {'账单时间', '日期'})
        if kind == 'fraud':
            return {'骑手id', '运单id', '欺诈是否成立'}.issubset(columns)
        return {'骑手id', '运单号', '类型'}.issubset(columns)
    valid = False
    try:
        if path.suffix.lower() == '.xlsx':
            from order_xlsx import read_xlsx_tables, FastXlsxUnsupported
            try:
                checks = read_xlsx_tables(path, set(), lambda rows, *_: any(matches(row) for row in islice(rows, 10)))
                valid = any(checks)
            except FastXlsxUnsupported:
                book = load_workbook(path, read_only=True, data_only=True)
                try:
                    for sheet in book:
                        sheet.reset_dimensions()
                        if any(matches(row) for row in sheet.iter_rows(max_row=10, values_only=True)):
                            valid = True
                            break
                finally:
                    book.close()
        elif path.suffix.lower() == '.csv':
            for encoding in ('utf-8-sig', 'gb18030'):
                try:
                    with path.open(encoding=encoding, newline='') as stream:
                        valid = any(matches(row) for row in islice(csv.reader(stream), 10))
                    if valid:
                        break
                except UnicodeError:
                    continue
        else:
            import pandas as pd
            with pd.ExcelFile(path, engine='calamine') as book:
                valid = any(any(matches(row) for row in book.parse(sheet, nrows=10, header=None).values)
                            for sheet in book.sheet_names)
    except Exception:
        raise SourceError(f'{LABELS[kind]} 无法解析，请检查文件是否完整') from None
    if not valid:
        raise SourceError(f'{LABELS[kind]} 缺少相应表头，请选择正确资料')


def readiness(state):
    if state.get('input_policy')=='readable_delivery_v1':
        state['status']='ready' if state['items']['delivery_fee']['status']=='ready' else 'waiting_materials'
        return
    state['status'] = 'ready' if all(value['status'] in ('ready', 'omitted')
                                     for value in state['items'].values()) else 'waiting_materials'
    if state['items']['delivery_fee']['status'] != 'ready':
        state['status'] = 'waiting_materials'
    if state['mode'] == 'fengshen' and state['items']['payment_binding']['status'] != 'ready':
        state['status'] = 'waiting_materials'
    if state['mode'] == 'fengshen' and not state.get('jobs') and any(value['status'] == 'pending' for value in state['items'].values()):
        state['status'] = 'pending_download'


def create(source, wid, mode, download_owner=None, root=None):
    preparation_started = time.perf_counter()
    if mode not in ('manual', 'fengshen', 'xiaoxiang'):
        raise SourceError('未知兼职数据来源')
    folder, _ = owned_upload(source, wid, root or ROOT)
    from payroll_business import inspect_payroll
    plan, template, mode = inspect_payroll(folder, mode)
    if mode == 'xiaoxiang':
        result_folder, result_state = create_xiaoxiang(folder, plan, template, wid, root)
        result_state['performance'] = {'preparation_seconds': time.perf_counter() - preparation_started}
        upload_metrics = read_upload_timing(folder)
        if upload_metrics:result_state['performance']['upload'] = upload_metrics
        save(result_folder, result_state)
        return result_folder, result_state
    if mode == 'fengshen':
        from download_service import validate_request, ValidationError
        try:
            validate_request({'cities': [plan.city], 'start': plan.start, 'end': plan.end,
                              'datasets': ['delivery_fee']})
        except ValidationError as exc:
            raise SourceError(str(exc)) from None
    files = source_files(folder)
    matched = {kind: [p for p in files if p != template and label in p.name]
               for kind, label in LABELS.items()}
    # The official monthly filename contains UB 账单 rather than 骑手账单.
    matched['rider_monthly'] = [p for p in files if p != template and
                              ('骑手账单' in p.name or 'UB' in p.name.upper())]
    matched['penalty'] = [p for p in files if p != template and '违规' in p.name]
    if mode == 'manual' and not matched['delivery_fee']:
        raise SourceError('手动核算必须上传 template 和配送费；其他资料可选')
    key = uuid.uuid4().hex
    output = directory(wid, key, root)
    (output / 'input').mkdir(parents=True)
    shutil.copy2(template, output / 'input' / template.name)
    state = {'id': key, 'mode': mode, 'download_owner': download_owner, 'plan': asdict(plan),
             'template_hash': digest(template), 'status': 'preparing', 'items': {}, 'jobs': [],
             'audit': []}
    state['created_at'] = __import__('datetime').datetime.now().isoformat()
    for kind, label in LABELS.items():
        state['items'][kind] = {'label': label, 'status': 'pending' if mode == 'fengshen' else 'omitted'}
        if mode == 'manual' and matched[kind]:
            staged, hashes = [], set()
            for index, path in enumerate(matched[kind]):
                validate_upload(path, kind)
                checksum = digest(path)
                if checksum in hashes:
                    raise SourceError(f'{label} 存在内容完全相同的重复文件，请核对后上传')
                hashes.add(checksum)
                # Preserve raw workbook layouts, including official UB row-four headers.
                destination = output / 'input' / (label + '_' + str(index) + '_' + path.name)
                shutil.copy2(path, destination)
                staged.append({'file': destination.name, 'sha256': checksum, 'origin': 'manual'})
            state['items'][kind] = {'label': label, 'status': 'ready', 'files': staged}
    if mode == 'manual':
        readiness(state)
    else:
        state.update(status='pending_download', workflow='two_step_v1', input_policy='readable_delivery_v1')
    state['performance'] = {'preparation_seconds': time.perf_counter() - preparation_started}
    upload_metrics = read_upload_timing(folder)
    if upload_metrics:state['performance']['upload'] = upload_metrics
    save(output, state)
    return output, state


def create_xiaoxiang(source, plan, template, wid, root=None):
    from payroll_business import xiaoxiang_delivery_files
    files = source_files(source)
    for path in source.rglob('*'):
        if path.is_file() and path.suffix.lower() in ('.json', '.txt') and not any(
                part.startswith(('~', '.')) for part in path.relative_to(source).parts):
            if path.is_symlink() or not path.resolve().is_relative_to(source.resolve()):
                raise SourceError('小象上传资料中存在越界文件')
            files.append(path)
    key = uuid.uuid4().hex
    folder = directory(wid, key, root)
    (folder / 'input').mkdir(parents=True)
    all_files = []
    for path in files:
        if not 0 < path.stat().st_size <= 200 * 1024 * 1024:
            raise SourceError('小象原始文件为空或超过单文件 200MB 限制')
        relative = path.relative_to(source)
        destination = folder / 'input' / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, destination)
        all_files.append({'file': relative.as_posix(), 'sha256': digest(destination), 'origin': 'company_manual'})
    def item(label, selected):
        return {'label': label, 'status': 'ready' if selected else 'omitted',
                'files': [entry for entry in all_files if entry['file'] in {p.relative_to(source).as_posix() for p in selected}]}
    state = {'id': key, 'mode': 'xiaoxiang', 'download_owner': None, 'plan': asdict(plan),
             'template_hash': digest(template), 'status': 'ready', 'jobs': [], 'audit': [],
             'created_at': __import__('datetime').datetime.now().isoformat(), 'all_files': all_files,
             'engine': 'company_20261016', 'items': {
                'delivery_fee': item('小象日期配送单', xiaoxiang_delivery_files(files, template)),
                'lanorange_part_price': item('小象手动价格档案', [p for p in files if p != template and '价格档案' in p.name]),
                'payment_binding': item('小象手动绑定资料', [p for p in files if p != template and
                    ('merchantfreelancer' in p.name.lower() or '骑手支付绑定' in p.name)]),
                'rider_orders': item('小象骑手订单明细', [p for p in files if p != template and '骑手订单明细' in p.name]),
             }}
    save(folder, state)
    return folder, state


def start_download(folder, state, manager):
    from download_service import validate_request
    plan = state['plan']
    config = validate_request({'cities': [plan['city']], 'start': plan['start'], 'end': plan['end'],
                               'datasets': ['delivery_fee'], 'refresh_history': True})
    # Optional order-window restrictions are evaluated per item by the executor;
    # they must not prevent collection of the mandatory delivery bill.
    config['datasets'] = [kind for kind in LABELS if state['items'][kind]['status'] == 'pending']
    if not config['datasets']:
        readiness(state)
        save(folder, state)
        return
    # Payroll needs this city; standalone Blue Orange retains its full export policy.
    config.pop('lanorange_full_delivery', None)
    config['lanorange_by_city'] = True
    config.update(task_kind='payroll_source', parent_batch_id=state['id'], parent_workspace=folder.parent.name)
    if state.get('input_policy')=='readable_delivery_v1':
        config.update(payroll_unified=True,payroll_scope_mode='single')
        if 'exclude_separation' in state:
            config['exclude_separation']=state['exclude_separation']
        else:
            config['include_separation']=bool(state.get('only_separation'))
        run=manager.create(state['download_owner'],config,request_id='payroll_'+state['id']+'_unified')
        if run['id'] not in state['jobs']:state['jobs'].append(run['id'])
        save(folder,state)
        return
    run = manager.create(state['download_owner'], config, request_id='payroll_' + state['id'])
    if run['id'] not in state['jobs']: state['jobs'].append(run['id'])
    if state.get('include_separation'):
        state.setdefault('job_scopes', {})[run['id']] = 'normal'
        for agency in state.get('separation_agencies', []):
            extra = {**config, 'datasets': [k for k in config['datasets'] if k != 'lanorange_part_price'],
                     'include_separation': True, 'payroll_agencies': {plan['city']: agency}}
            separate = manager.create(state['download_owner'], extra, request_id='payroll_' + state['id'] + '_split_' + agency)
            if separate['id'] not in state['jobs']: state['jobs'].append(separate['id'])
            state['job_scopes'][separate['id']] = agency
    save(folder, state)


def start_download_resumable(folder, state, manager):
    try:
        start_download(folder, state, manager)
    except OSError as exc:
        # manager.create is idempotent under payroll_<batch id>. Keep a job id
        # already obtained, even if the first manifest replacement was locked.
        state['status'] = 'pending_download'
        try:
            save(folder, state)
        except OSError:
            pass
        raise SourceError('资料准备状态保存失败，请继续检查原下载任务；系统将沿用原批次编号，不重复提交导出') from exc


def collect_finished(folder, state, manager):
    if state.get('input_policy')=='readable_delivery_v1':
        from payroll_readable_policy import collect
        return collect(folder,state,manager)
    if state.get('job_scopes'):
        return collect_scoped(folder, state, manager)
    for job_id in state['jobs']:
        run = manager.get_run(state['download_owner'], job_id)
        for item in run['items']:
            kind = item['dataset']
            if kind not in state['items'] or state['items'][kind]['status'] in ('ready', 'omitted'):
                continue
            if item['status'] != 'success':
                state['items'][kind].update(status='failed', error=item.get('error') or '下载未完成',
                    recovery_allowed=item.get('recovery', {}).get('mode') in ('resume_existing', 'retry_unsubmitted'),
                    run_id=job_id, recovery_reason=item.get('recovery', {}).get('reason', ''))
                continue
            candidates = [f for f in run['files'] if f['dataset'] == kind and f.get('artifact_role') != 'summary']
            if len(candidates) != 1:
                state['items'][kind].update(status='failed', error='已完成任务缺少唯一成品')
                continue
            try:
                path, _ = manager.get_file(state['download_owner'], job_id, candidates[0]['id'])
                stage(folder, state, kind, path, {'run_id': job_id, 'file_id': candidates[0]['id']})
            except SourceError as exc:
                state['items'][kind].update(status='failed', error='成品校验失败：' + str(exc),
                                            run_id=job_id, recovery_allowed=False)
            except Exception:
                state['items'][kind].update(status='failed', error='成品读取失败，请核对原任务文件完整性',
                                            run_id=job_id, recovery_allowed=False)
    readiness(state)
    save(folder, state)


def collect_scoped(folder, state, manager):
    """Preserve independently verified normal/separation files and retry lineage."""
    latest = {}
    for job_id in state['jobs']:
        run = manager.get_run(state['download_owner'], job_id)
        scope = state['job_scopes'].get(job_id, 'normal')
        for item in run['items']:
            if item['dataset'] in LABELS:
                latest[(scope, item['dataset'])] = (job_id, run, item)
    for kind, value in state['items'].items():
        entries = []; errors = []
        for (scope, dataset), (job_id, run, item) in latest.items():
            if dataset != kind: continue
            candidates = [f for f in run['files'] if f['dataset'] == kind and f.get('artifact_role') != 'summary']
            if item['status'] != 'success' or len(candidates) != 1:
                errors.append((job_id, item));continue
            path, _ = manager.get_file(state['download_owner'], job_id, candidates[0]['id'])
            # Unique paths keep the regular and separation workbooks intact.
            (folder/'evidence').mkdir(exist_ok=True)
            target = folder/'evidence'/(LABELS[kind]+'_'+scope+'_'+job_id[:8]+Path(path).suffix.lower())
            if kind == 'rider_monthly':
                from types import SimpleNamespace
                target = target.with_name('UB骑手账单_cleaned_'+state['plan']['month']+'_'+scope+'.csv')
                clean_rider_bill(path,target,SimpleNamespace(**state['plan']))
            else: shutil.copy2(path,target)
            entries.append({'file':target.name,'sha256':digest(target),'origin':{'run_id':job_id,'file_id':candidates[0]['id']}})
        if errors:
            job, item = errors[-1]
            state['items'][kind] = {'label':LABELS[kind],'status':'failed','source_files':entries,'run_id':job,
                                    'error':item.get('error') or '普通或取分离资料未全部获取成功'}
        elif entries:
            try:
                source_paths = [folder/'evidence'/entry['file'] for entry in entries]
                suffix = source_paths[0].suffix
                name = ('UB骑手账单_cleaned_'+state['plan']['month'] if kind == 'rider_monthly' else LABELS[kind]) + suffix
                merged = folder/'input'/name
                merge_scope_files(source_paths, merged)
                state['items'][kind] = {'label':LABELS[kind],'status':'ready','file':name,'sha256':digest(merged),'source_files':entries}
            except (SourceError, ValueError, OSError) as error:
                state['items'][kind] = {'label':LABELS[kind],'status':'failed','source_files':entries,'error':'普通与取分离资料合并未完成：'+str(error)}
    readiness(state);save(folder,state)


def merge_scope_files(paths, target):
    """Concatenate identical table schemas. Never discard business rows or source evidence."""
    from deduction_confirmation import tables
    import csv
    import os
    if len({p.suffix.lower() for p in paths}) != 1:
        raise SourceError('同类来源文件格式不同，请核对原件')
    temporary = target.with_name('.merge_'+uuid.uuid4().hex+target.suffix)
    try:
        if target.suffix.lower() == '.csv':
            header = None
            with temporary.open('w', encoding='utf-8-sig', newline='') as stream:
                writer = csv.writer(stream)
                for path in paths:
                    for rows in tables(path):
                        iterator = iter(rows);current = next(iterator, None)
                        if current is None: raise SourceError('来源文件缺少表头')
                        if header is None: header = list(current);writer.writerow(header)
                        elif list(current) != header: raise SourceError('来源表头不一致，未猜测列映射')
                        writer.writerows(iterator)
        elif target.suffix.lower() == '.xlsx':
            from openpyxl import Workbook, load_workbook
            output = Workbook(write_only=True);sheets={};headers={};names=None;shared_hash=None
            try:
                for path in paths:
                    book = load_workbook(path, read_only=True, data_only=True)
                    try:
                        if names is not None and book.sheetnames != names: raise SourceError('来源工作簿子表不一致')
                        names = book.sheetnames
                        for sheet in book:
                            sheet.reset_dimensions();rows=iter(sheet.iter_rows(values_only=True));header=next(rows,None)
                            if header is None: raise SourceError('来源子表缺少表头')
                            shared = sheet.title == '商翼绑定表' and sheet.title in sheets
                            hasher = hashlib.sha256()
                            if sheet.title not in sheets:
                                sheets[sheet.title]=output.create_sheet(sheet.title);headers[sheet.title]=header;sheets[sheet.title].append(header)
                            elif headers[sheet.title] != header: raise SourceError('来源子表表头不一致')
                            for row in rows:
                                if sheet.title == '商翼绑定表': hasher.update(json.dumps(row,ensure_ascii=False,default=str).encode()+b'\n')
                                if shared: continue
                                # Force original text to remain text, including formula-like identifiers.
                                from openpyxl.cell import WriteOnlyCell
                                values=[]
                                for value in row:
                                    cell=WriteOnlyCell(sheets[sheet.title],value=value)
                                    if isinstance(value,str):cell.data_type='s'
                                    values.append(cell)
                                sheets[sheet.title].append(values)
                            if sheet.title == '商翼绑定表':
                                if shared and shared_hash != hasher.hexdigest(): raise SourceError('共享商翼资料在两组获取期间已变化，未混用版本')
                                shared_hash = hasher.hexdigest()
                    finally: book.close()
                output.save(temporary)
            finally:
                for sheet in output:
                    if not sheet.closed: sheet.close()
                    writer = getattr(sheet, '_writer', None)
                    if writer is not None and Path(writer.out).exists(): writer.cleanup()
                output.close()
        else:
            raise SourceError('无法合并此来源格式')
        os.replace(temporary,target)
    finally:
        temporary.unlink(missing_ok=True)


def verified_hashes(folder, state):
    inputs = folder / 'input'
    entries = [(state['plan']['template'], state['template_hash'], 'template 在预检后被修改，请重新提交')]
    entries.extend((entry['file'], entry['sha256'], '小象原始资料在准备后被修改，请重新上传')
                   for entry in state.get('all_files', []))
    for value in state['items'].values():
        entries.extend(('../evidence/'+entry['file'],entry['sha256'],'普通或取分离原始凭据已变化，请核对原件') for entry in value.get('source_files', []))
        if value['status'] == 'ready':
            entries.extend((entry['file'], entry['sha256'], '核算资料在校验后被修改，请重新准备')
                           for entry in value.get('files', [value]))
    result = {}
    for name, checksum, message in entries:
        path = inputs / name
        if path in result and result[path][0] != checksum:
            raise SourceError('核算资料校验记录冲突，请重新准备')
        result.setdefault(path, (checksum, message))
    return result


def checked_inputs(folder, state):
    if state.get('input_policy')=='readable_delivery_v1':
        from payroll_readable_policy import inputs
        return inputs(folder,state)
    if state['status'] != 'ready':
        raise SourceError('资料尚未准备齐全，核算已暂停')
    if state['mode'] == 'fengshen' and state['items'].get('payment_binding', {}).get('status') != 'ready':
        raise SourceError('支付绑定未获取成功，核算已暂停，请完成登录或重试')
    for path, (checksum, message) in verified_hashes(folder, state).items():
        if digest(path) != checksum:
            raise SourceError(message)
    return folder / 'input'


def claim_calculation(wid, key, owner, deduction_version='', root=None):
    """Hash outside the global lock; recheck state before the atomic claim."""
    folder = directory(wid, key, root)
    with batch_lock(folder):
        with LOCK:
            folder, state = load(wid, key, owner, root)
            if state['status'] in ('calculating', 'calculated'):
                raise SourceError('本次资料正在核算或已核算，请先核对原结果')
            signature = json.dumps(state, ensure_ascii=False, sort_keys=True)
        started = time.perf_counter()
        inputs = checked_inputs(folder, state)
        checked_seconds = time.perf_counter() - started
        with LOCK:
            folder, current = load(wid, key, owner, root)
            if json.dumps(current, ensure_ascii=False, sort_keys=True) != signature:
                raise SourceError('资料或扣款配置在校验期间发生变化，请刷新后重新确认')
            from workbench import deduction_snapshot
            from deduction_confirmation import require_confirmation
            relaxed=current.get('input_policy')=='readable_delivery_v1'
            if not relaxed: require_confirmation(current, deduction_version)
            selected = {**current['deductions'],'frozen':True} if relaxed else deduction_snapshot(current)
            if deduction_version and selected['version'] != deduction_version:
                raise SourceError('扣款配置已变化，请重新查看配置并确认后再核算')
            current['deductions'] = selected
            current['calculation_attempt'] = int(current.get('calculation_attempt', 0)) + 1
            current['status'] = 'calculating'
            current['performance'] = {'preparation_seconds': current.get('performance', {}).get('preparation_seconds', 0),
                                      'integrity_seconds': checked_seconds,
                                      **({'upload': current.get('performance', {})['upload']} if 'upload' in current.get('performance', {}) else {})}
            save(folder, current)
        return folder, current, inputs


async def run_payroll(config, request, *, context=None):
    """Serialize queue jobs and historical single-batch execution together."""
    import payroll_control as control
    cancelled=getattr(config,'_queue_cancelled',lambda:False)
    announced=False
    while not control.EXECUTION_LOCK.acquire(blocking=False):
        if cancelled():raise SourceError('任务已停止，尚未开始核算')
        if not announced:
            import tasks
            yield tasks.create_log_event('等待其他核算任务完成','INFO');announced=True
        yield ': heartbeat\n\n'
        await asyncio.sleep(.25)
    try:
        if cancelled():raise SourceError('任务已停止，尚未开始核算')
        async for result in _run_payroll_in_slot(config,request,context=context):yield result
    finally:
        control.EXECUTION_LOCK.release()


async def _run_payroll_in_slot(config, request, *, context=None):
    import tasks
    import payroll_control as control
    wid = context[0] if context is not None else workspace(request)
    mode = config.payrollSourceMode
    owner = (context[1] if context is not None else account(request)) if mode == 'fengshen' else None
    if config.payrollPreparationId:
        folder, state = load(wid, config.payrollPreparationId, owner)
        if state['mode'] != mode:
            raise SourceError('资料模式与准备记录不一致')
        if state['status'] in ('calculated', 'calculating'):
            raise SourceError('本次资料已核算或正在核算，请先核对原结果；重新上传可发起新核算')
    else:
        folder, state = await asyncio.to_thread(create, config.sourcePath, wid, mode, owner)
        if mode=='fengshen':
            state.update(exclude_separation=bool(getattr(config,'payrollExcludeSeparation',True)), download_scope='single_selection')
            save(folder,state)
    with batch_lock(folder):
        folder, state = load(wid, state['id'], owner)
        control.reconcile(folder, state)
        if mode == 'fengshen':
            state['workflow'] = 'two_step_v1'
            state['input_policy'] = 'readable_delivery_v1'
            if state['status'] == 'awaiting_confirmation': state['status'] = 'pending_download'
        if state['status'] in ('cancelled', 'stopping', 'interrupted'):
            raise SourceError('本批次已停止或中断；资料保留，请核对原结果后发起新批次')
        event = control.acquire(folder)
        state['execution_runtime'] = control.RUNTIME_ID
        try:
            save(folder, state)
        except BaseException:
            control.release(folder, event)
            raise
    try:
        async for result in _run_payroll(config, request, folder, state, event, context=context):
            yield result
    except (SourceError, HTTPException) as error:
        if state.get('workflow') != 'two_step_v1': raise
        message = error.detail if isinstance(error, HTTPException) and isinstance(error.detail, str) else str(error)
        relaxed=state.get('input_policy')=='readable_delivery_v1'
        with batch_lock(folder):
            if relaxed:
                state['status']='error';state.pop('pause_reason',None)
                state.setdefault('execution_logs',[]).append({'text':message,'level':'ERROR'})
            else:
                state['pause_reason'] = message
                if state['status'] == 'preparing': state['status'] = 'waiting_materials' if state.get('jobs') else 'pending_download'
                if state['status'] == 'calculating': state['status'] = 'ready'
            state.pop('execution', None)
            save(folder, state)
        yield 'data: ' + json.dumps({'type':'payroll_preparation','preparation':public(state)},ensure_ascii=False) + '\n\n'
        yield tasks.create_log_event(message, 'WARN')
        yield tasks.create_finish_event('error' if relaxed else 'paused', '任务已结束，详情见执行日志' if relaxed else message)
    except control.PayrollStopped:
        with batch_lock(folder):
            folder, state = load(wid, state['id'], owner)
            state.update(status='cancelled', stop_requested=True)
            save(folder, state)
        yield 'data: ' + json.dumps({'type': 'payroll_preparation', 'preparation': public(state)}, ensure_ascii=False) + '\n\n'
        yield tasks.create_finish_event('cancelled', '任务已停止，已下载资料和生成文件保留')
    finally:
        control.release(folder, event)


async def _run_payroll(config, request, folder, state, cancelled, *, context=None):
    import tasks
    from payroll_control import checkpoint
    wid, mode = context[0] if context is not None else workspace(request), state['mode']
    owner = (context[1] if context is not None else account(request)) if mode == 'fengshen' else None
    automatic = state.get('workflow') == 'two_step_v1'
    relaxed = state.get('input_policy') == 'readable_delivery_v1'
    def log_event(message,level='INFO'):
        entries=state.setdefault('execution_logs',[])
        if not entries or entries[-1]['text']!=message:
            entries.append({'text':message,'level':level});entries[:]=entries[-300:]
        return tasks.create_log_event(message,level)

    if not automatic and (state['status'] == 'awaiting_confirmation' or (mode == 'fengshen' and not state.get('deduction_intent') and state['status'] != 'ready')):
        state['status'] = 'awaiting_confirmation'
        save(folder, state)
        yield 'data: ' + json.dumps({'type': 'payroll_preparation', 'preparation': public(state)}, ensure_ascii=False) + '\n\n'
        yield tasks.create_finish_event('paused', '请确认扣款清单，确认后自动采集并核算')
        return
    checkpoint(cancelled)
    if state['status'] == 'pending_download':
        from datetime import datetime, timezone
        state.setdefault('execution_started_at', datetime.now(timezone.utc).isoformat())
        state['status'] = 'preparing'
        save(folder, state)
    yield 'data: ' + json.dumps({'type': 'payroll_preparation', 'preparation': public(state)}, ensure_ascii=False) + '\n\n'
    if mode == 'fengshen' and state['status'] == 'preparing':
        if relaxed and state.get('download_scope')=='single_selection':
            if 'exclude_separation' in state:
                scope='普通站点（排除取分离）' if state['exclude_separation'] else '全部站点（含取分离）'
            else:
                scope='仅取分离站点' if state.get('only_separation') else '普通站点（排除取分离）'
            yield log_event('下载范围：'+scope)
        from download_jobs import get_manager, ACTIVE_STATUSES
        manager = get_manager()
        if automatic and not relaxed:
            from payroll_automatic import prepare_scope
            yield log_event('正在识别本次申请范围，取分离资料按模板自动处理')
            try:
                await asyncio.to_thread(prepare_scope, folder, state)
            except (SourceError, HTTPException):
                if not relaxed: raise
                state['material_note']='部分平台范围未提供，本次使用可读取的配送资料核算'
                save(folder,state)
            checkpoint(cancelled)
        if not state['jobs'] or (not relaxed and state.get('include_separation') and not {'normal', *state.get('separation_agencies', [])}.issubset(set(state.get('job_scopes', {}).values()))):
            await asyncio.to_thread(start_download_resumable, folder, state, manager)
        last = None
        last_material_log = {}
        while True:
            runs = [await asyncio.to_thread(manager.get_run, owner, key) for key in state['jobs']]
            if cancelled.is_set():
                for run in runs:
                    if run['status'] in ACTIVE_STATUSES and run['status'] != 'cancelling':
                        await asyncio.to_thread(manager.cancel, owner, run['id'])
            from payroll_material_progress import material_progress
            materials = material_progress(state, runs)
            progress = [(run['id'], run['status'], run.get('phase'), run.get('progress')) for run in runs], materials
            if progress != last:
                state['execution'] = {'waiting_login': any(run['status'] == 'waiting_login' for run in runs),
                                      'waiting_verification': any(run['status'] == 'waiting_login' and run.get('phase') == 'waiting_manual' for run in runs),
                                      'phase': '；'.join(str(run.get('phase') or run['status']) for run in runs)}
                state['downloads'] = materials
                save(folder, state)
                yield 'data: ' + json.dumps({'type': 'payroll_preparation', 'preparation': public(state)}, ensure_ascii=False) + '\n\n'
                from payroll_material_progress import material_log_changes
                messages, last_material_log = material_log_changes(materials, last_material_log)
                for message in messages:
                    yield log_event(message)
                last = progress
            if all(run['status'] not in ACTIVE_STATUSES for run in runs):
                break
            yield ': heartbeat\n\n'
            await asyncio.sleep(1)
        checkpoint(cancelled)
        state['execution'] = {'waiting_login': False, 'phase': 'validating'}
        for row in state.get('downloads', []):
            if row['status'] == 'validating': row['detail'] = '正在整理资料' if relaxed else '正在核对文件完整性并归档'
        save(folder, state)
        yield 'data: ' + json.dumps({'type':'payroll_preparation','preparation':public(state)},ensure_ascii=False) + '\n\n'
        await asyncio.to_thread(collect_finished, folder, state, manager)
        if any(run.get('payroll_verification_required') for run in runs) and state['items']['payment_binding']['status'] != 'ready':
            raise SourceError('骑手支付绑定的平台验证或导出未完成，本次未生成工资表；已有资料保留')
        state['downloads'] = material_progress(state, runs)
        save(folder, state)
        state.pop('execution', None)
    yield 'data: ' + json.dumps({'type': 'payroll_preparation', 'preparation': public(state)}, ensure_ascii=False) + '\n\n'
    if state['status'] != 'ready':
        if relaxed:
            message='模板或配送费无法读取，本次任务结束'
            state['status']='error';state.pop('pause_reason',None)
            state.setdefault('execution_logs',[]).append({'text':message,'level':'ERROR'})
            save(folder,state)
            yield 'data: '+json.dumps({'type':'payroll_preparation','preparation':public(state)},ensure_ascii=False)+'\n\n'
            yield log_event(message,'ERROR')
            yield tasks.create_finish_event('error','任务已结束，详情见执行日志')
        else:
            yield log_event('资料获取未完成，任务已暂停。请完成平台登录或重试失败项；已有资料保留。' if mode == 'fengshen' else '资料未齐全，请核对缺项。','WARN')
            yield tasks.create_finish_event('paused','等待处理资料，尚未执行核算')
        return
    checkpoint(cancelled)
    if not automatic and mode == 'fengshen' and state.get('deduction_intent') and (state.get('deduction_confirmation') or {}).get('stage') != 'final':
        from deduction_confirmation import finalize_intent, platform_for
        from station_directory import ready_directory
        try:
            def finalize():
                data = ready_directory(platform_for(state), state['deduction_intent'].get('city_id') or state['plan']['city'])
                finalize_intent(folder, state, ROOT, data)
            await asyncio.to_thread(finalize)
            state.pop('pause_reason', None)
            save(folder, state)
        except SourceError as error:
            state['pause_reason'] = str(error)
            save(folder, state)
            yield 'data: ' + json.dumps({'type': 'payroll_preparation', 'preparation': public(state)}, ensure_ascii=False) + '\n\n'
            yield tasks.create_finish_event('paused', str(error))
            return
    if automatic:
        from payroll_automatic import capture_rules
        from deduction_confirmation import platform_for
        from station_directory import ready_directory
        yield log_event('正在自动应用已有扣款配置；无配置站点按零扣款计算')
        def capture():
            if relaxed:
                from payroll_readable_policy import capture_rules as capture_available_rules
                capture_available_rules(folder,state,ROOT)
            else:
                retained = state.get('deductions', {}).get('frozen') or (bool(state.get('deduction_confirmation')) and state['deduction_confirmation'].get('stage', 'final') == 'final')
                data = None if retained else ready_directory(platform_for(state), state['plan']['city'])
                capture_rules(folder, state, ROOT, data)
            state.pop('pause_reason', None)
            save(folder, state)
        await asyncio.to_thread(capture)
    if not automatic and (getattr(config, 'preparationOnly', False) or not getattr(config, 'deductionConfigVersion', '')):
        yield log_event('资料已准备完成，请确认扣款配置后点击开始核算')
        yield tasks.create_finish_event('paused', '资料已就绪，等待确认核算')
        return
    yield tasks.create_progress_event(0.01, '正在读取本次核算资料' if relaxed else '正在校验资料快照与扣款配置')
    checkpoint(cancelled)
    folder, state, inputs = await asyncio.to_thread(claim_calculation, wid, state['id'], owner,
                                                   state['deductions']['version'] if automatic else getattr(config, 'deductionConfigVersion', ''))
    yield 'data: ' + json.dumps({'type': 'payroll_preparation', 'preparation': public(state)}, ensure_ascii=False) + '\n\n'
    plan = state['plan']
    omitted = [v['label'] for v in state['items'].values() if v['status'] == 'omitted']
    if omitted:
        yield log_event('本次未提供：' + '、'.join(omitted), 'WARN')
    yield log_event(f"核算范围：{plan['city']} / {plan['start']} 至 {plan['end']} / {plan['applicants']} 条申请；各骑手仍按申请周期核算")
    from payroll_review import application_summary, build_review, write_review
    try:
        application = await asyncio.to_thread(application_summary, inputs / plan['template'])
    except Exception:
        application = None
        yield log_event('申请名单复核统计不可用，核算仍按原规则执行；请人工核对申请记录。', 'WARN')
    async for event in tasks.run_main_calculation_gen(plan['city'], plan['cycle'], str(inputs),
            config.basePath, config.theme, config.enableInterceptor, config.enableCrossStationMerge,
            deductionRules=state['deductions']['rows'], taskQueue=[Path(plan['template']).name if relaxed else plan['template']], strict_inputs=True,
            manual_template_only=True, force_no_price=state['mode'] != 'xiaoxiang' and state['items']['lanorange_part_price']['status'] == 'omitted',
            skip_binding_check=state['mode'] != 'xiaoxiang' and state['items']['payment_binding']['status'] == 'omitted',
            input_snapshot=public(state) if state['mode'] != 'xiaoxiang' else None,
            prepared_plan={**plan,'template':Path(plan['template']).name} if relaxed else plan, verified_inputs={} if relaxed else {str(path): value[0] for path, value in verified_hashes(folder, state).items()},
            output_root=str((Path(ROOT) / 'backend/.local_downloads/workspaces/payroll' / wid / state['id'] / ('attempt_' + str(state.get('calculation_attempt', 1)))).resolve()), cancelled=cancelled):
        if event.startswith('data: '):
            result = json.loads(event[6:])
            if result.get('type') == 'log':
                message=result.get('msg') or result.get('message')
                if message: log_event(message,result.get('level','INFO'))
            elif result.get('type') == 'payroll_performance':
                if cancelled.is_set():
                    continue
                state['performance'] = {**state.get('performance', {}), **result['performance']}
                save(folder, state)
                yield 'data: ' + json.dumps({'type': 'payroll_preparation', 'preparation': public(state)}, ensure_ascii=False) + '\n\n'
            elif result.get('type') == 'finish' and result.get('status') == 'success':
                with batch_lock(folder):
                    checkpoint(cancelled)
                    state['status'] = 'calculated'
                    state['result'] = {'output': result.get('out_file'), 'input_hashes_verified': not relaxed}
                    save(folder, state)
                review = build_review(state, result.get('stats'), application)
                result['review_summary'] = review
                state['result'] = {'output': result.get('out_file'), 'input_hashes_verified': not relaxed, 'review_summary': review,
                                   'delivery_layout':'payroll_workbooks_v1'}
                save(folder, state)
                output = Path(result.get('out_file') or '')
                if result.get('out_file') and output.is_dir():
                    try:
                        await asyncio.to_thread(write_review, output, review)
                    except Exception:
                        review['export_error'] = '复核清单导出未完成，请在批次页面查看摘要并复核原工作簿'
                        save(folder, state)
                        yield log_event(review['export_error'], 'WARN')
                try:
                    destination=publish_result(wid,folder,state)
                    result['out_file']=str(destination)
                    event='data: '+json.dumps(result,ensure_ascii=False)+'\n\n'
                except (OSError,ValueError,SourceError):
                    yield log_event('核算已完成，结果目录发布未完成；原结果已保留，可在任务中心重新领取。','WARN')
                event='data: '+json.dumps(result,ensure_ascii=False)+'\n\n'
                yield 'data: ' + json.dumps({'type': 'payroll_preparation', 'preparation': public(state)}, ensure_ascii=False) + '\n\n'
            elif result.get('type') == 'finish' and result.get('status') == 'error':
                if relaxed:
                    reason=str(result.get('result_msg') or '本次核算未完成')
                    state['status']='error';state.pop('pause_reason',None)
                    log_event(reason,'ERROR');save(folder,state)
                    yield 'data: '+json.dumps({'type':'payroll_preparation','preparation':public(state)},ensure_ascii=False)+'\n\n'
                    yield tasks.create_log_event(reason,'ERROR')
                    event=tasks.create_finish_event('error','任务已结束，详情见执行日志')
                else:
                    state['status'] = 'ready'
                    state['pause_reason'] = '核算未完成，原资料和已确认规则保留：' + str(result.get('result_msg') or '请查看执行记录')
                    save(folder, state)
        yield event


@router.get('/{key}')
def get_preparation(key: str, request: Request):
    try:
        folder = directory(workspace(request), key)
        with batch_lock(folder):
            folder, state = load(workspace(request), key, account(request))
            from payroll_control import reconcile
            reconcile(folder, state)
        return public(state)
    except SourceError as exc:
        raise HTTPException(400, str(exc)) from None


@router.post('/{key}/resolve')
async def resolve(key: str, request: Request):
    owner, wid = account(request), workspace(request)
    payload = await request.json()
    if not isinstance(payload, dict):
        raise HTTPException(400, '资料处理参数必须为对象')
    kind, action = payload.get('dataset'), payload.get('action')
    if kind not in LABELS or action not in ('omit', 'retry'):
        raise HTTPException(400, '资料处理参数无效')
    with LOCK:
        try:
            folder, state = load(wid, key, owner)
        except SourceError as exc:
            raise HTTPException(400, str(exc)) from None
        value = state['items'][kind]
        if state.get('input_policy')=='readable_delivery_v1':
            raise HTTPException(410,'自动核算不提供失败项处理或重试入口，请重新上传模板发起新任务')
        if state['status'] == 'preparing' or value['status'] not in ('failed', 'pending'):
            raise HTTPException(409, '资料状态已变化，请刷新资料清单')
        if action == 'omit':
            if state['mode'] == 'fengshen':
                raise HTTPException(400, '自动核算不支持跳过资料，请完成登录或重试获取')
            if kind == 'delivery_fee':
                raise HTTPException(400, '配送费为必需资料，不可跳过')
            value.update(status='omitted', confirmed_at=__import__('datetime').datetime.now().isoformat())
            state['audit'].append({'dataset': kind, 'action': 'explicit_omit', 'at': value['confirmed_at']})
            readiness(state)
        else:
            from download_jobs import get_manager
            manager = get_manager()
            run = manager.get_run(owner, value['run_id'])
            items = [{k: item[k] for k in ('city', 'dataset', 'start', 'end')}
                     for item in run['items'] if item['dataset'] == kind and item['status'] != 'success']
            from download_routes import _call
            retry = _call(lambda: manager.retry(owner, run['id'], items, 'payroll_retry_' + uuid.uuid4().hex))
            state['jobs'].append(retry['id'])
            if state.get('job_scopes'):
                state['job_scopes'][retry['id']] = state['job_scopes'].get(run['id'], 'normal')
            value['status'] = 'pending'
            state['status'] = 'preparing'
        save(folder, state)
        return public(state)


@router.post('/{key}/supplement')
async def supplement(key: str, request: Request):
    wid, owner = workspace(request), account(request)
    payload = await request.json()
    if not isinstance(payload, dict):
        raise HTTPException(400, '补传参数必须为对象')
    dataset = payload.get('dataset')
    if dataset not in LABELS:
        raise HTTPException(400, '资料类型无效')
    try:
        upload, _ = owned_upload(payload.get('path', ''), wid, ROOT)
        files = source_files(upload)
        if len(files) != 1:
            raise SourceError('请每次补传一份对应资料')
        path = files[0]
        if not 0 < path.stat().st_size <= 200 * 1024 * 1024:
            raise SourceError('补传文件为空或超过 200MB')
        validate_upload(path, dataset)
        with LOCK:
            folder, state = load(wid, key, owner)
            if state['mode'] == 'fengshen':
                raise HTTPException(400, '闪购自动核算由系统获取资料，请完成登录或重试，无需手动补传')
            if state['status'] in ('preparing', 'calculating', 'calculated') or state['items'][dataset]['status'] == 'ready':
                raise HTTPException(409, '资料正在准备或已就绪，请重新检查')
            stage(folder, state, dataset, path, 'manual_supplement')
            state['audit'].append({'dataset': dataset, 'action': 'manual_supplement', 'sha256': digest(path)})
            readiness(state)
            save(folder, state)
            return public(state)
    except SourceError as exc:
        raise HTTPException(400, str(exc)) from None


@router.post('/{key}/retry')
def retry_preparation(key: str, request: Request):
    """One retry per original run. Manager enforces retained-receipt recovery policy."""
    from download_jobs import get_manager
    from download_routes import _call
    wid, owner = workspace(request), account(request)
    folder = directory(wid, key)
    with batch_lock(folder), LOCK:
        folder, state = load(wid, key, owner)
        if state.get('input_policy')=='readable_delivery_v1':
            raise HTTPException(410,'自动核算不提供失败项重试，请重新上传模板发起新任务')
        if state['status'] not in ('waiting_materials', 'interrupted'):
            raise HTTPException(409, '当前任务不可重试，请刷新状态')
        manager = get_manager()
        selected = {}
        for kind, value in state['items'].items():
            if value['status'] == 'failed' and value.get('run_id'):
                selected.setdefault(value['run_id'], []).append(kind)
        if state.get('job_scopes'):
            latest = {}
            for run_id in state['jobs']:
                run = manager.get_run(owner, run_id)
                for item in run['items']:
                    latest[(state['job_scopes'].get(run_id, 'normal'), item['dataset'])] = (run_id, item)
            selected = {}
            for run_id, item in latest.values():
                if item['status'] != 'success': selected.setdefault(run_id, []).append(item['dataset'])
        if not selected:
            if state.get('workflow') == 'two_step_v1':
                state['status'] = 'preparing'
                save(folder, state)
                return public(state)
            raise HTTPException(409, '没有可安全重试的下载项，请查看任务详情')
        for run_id, kinds in selected.items():
            run = manager.get_run(owner, run_id)
            from auth_preflight import gate_datasets
            gate_datasets(run['datasets'])
            # Include failed prerequisites of binding generation as well as the public target.
            items = [{k: item[k] for k in ('city', 'dataset', 'start', 'end')} for item in run['items'] if item['status'] != 'success']
            retry = _call(lambda: manager.retry(owner, run_id, items, 'payroll_retry_' + uuid.uuid4().hex))
            state['jobs'].append(retry['id'])
            if state.get('job_scopes'):
                state['job_scopes'][retry['id']] = state['job_scopes'].get(run_id, 'normal')
            for kind in kinds:
                state['items'][kind].update(status='pending', run_id=retry['id'])
            state['status'] = 'preparing'
            save(folder, state)
        return public(state)
