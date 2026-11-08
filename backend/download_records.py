"""Read-only download records: group retries without changing source jobs."""
import hashlib
import json
import os
from pathlib import Path
import tempfile
import zipfile

ACTIVE = {'queued', 'running', 'waiting_login', 'waiting_manual', 'cancelling'}


def item_key(item):
    return tuple(item.get(key, '') for key in ('city', 'dataset', 'start', 'end'))


def file_key(file):
    return (*item_key(file), file.get('artifact_role', ''))


def group_records(runs):
    from task_catalog import category
    """Newest attempt determines state; source files and attempts remain intact."""
    by_id = {run['id']: run for run in runs}
    def root_for(key):
        seen = set()
        while key in by_id:
            if key in seen:
                return None
            seen.add(key)
            parent = by_id[key].get('retry_of') or by_id[key].get('recovery_of')
            if not parent or parent not in by_id:
                return key
            key = parent
        return None
    groups = {}
    for run in runs:
        root = root_for(run['id']) or run['id']
        groups.setdefault(root, []).append(run)
    records = []
    for root_id, members in groups.items():
        # Stable chronological order also covers attempts sharing a timestamp.
        members.sort(key=lambda run: (run.get('created_at', ''), run.get('_record_order', 0)))
        root = by_id[root_id]
        effective, file_versions, summary_files = {}, {}, []
        for run in members:
            for item in run.get('items', []):
                effective[item_key(item)] = {**item, 'run_id': run['id']}
            scopes = {}
            for file in run.get('files', []):
                entry = {**file, 'run_id': run['id']}
                if file.get('artifact_role') == 'summary':
                    summary_files.append((run, entry))
                else:
                    scopes.setdefault(file_key(file), []).append(entry)
            file_versions.update(scopes)
        files = [file for entries in file_versions.values() for file in entries]
        # A root summary cannot be presented as current after its inputs change.
        summaries = {}
        for source_run, file in summary_files:
            later = members[members.index(source_run) + 1:]
            stale = any(any(item.get('dataset') == file.get('dataset') for item in run.get('items', [])) for run in later)
            summaries[file_key(file)] = {**file, **({'available': False, 'unavailable_reason': '资料已有后续处理，原汇总保留在处理记录中', 'outdated': True} if stale else {})}
        files.extend(summaries.values())
        items = list(effective.values())
        active = [run for run in members if run['status'] in ACTIVE]
        summary_failures = [run for run in members if run.get('summary_progress', {}).get('stage') == 'failed']
        failed = [item for item in items if item['status'] not in ('success', *ACTIVE)]
        succeeded = sum(item['status'] == 'success' for item in items)
        if active:
            status = active[-1]['status']
        elif items and succeeded == len(items):
            status = 'partial' if summary_failures else 'success'
        elif succeeded:
            status = 'partial'
        elif items and all(item['status'] == 'cancelled' for item in items):
            status = 'cancelled'
        else:
            status = members[-1]['status']
        if len(members) == 1:
            status = root['status']
        target = active[-1]['id'] if active else failed[-1]['run_id'] if failed else summary_failures[-1]['id'] if summary_failures else root_id
        records.append({
            'kind': category(root), 'generation_target': root.get('generation_target'),
            'parent_batch_id': root.get('parent_batch_id'), 'parent_workspace': root.get('parent_workspace'),
            'id': root_id, 'cities': root['cities'], 'datasets': root['datasets'],
            'start': root['start'], 'end': root['end'], 'created_at': root['created_at'],
            'updated_at': members[-1]['created_at'], 'status': status,
            'phase': active[-1].get('phase') if active else None,
            'files': files, 'available_files': sum(file.get('available', True) for file in files),
            'total_items': len(items), 'completed_items': succeeded, 'failed_items': len(failed),
            'incomplete_items': [{key: item.get(key, '') for key in ('city', 'dataset', 'start', 'end', 'status')} for item in failed],
            'action_run_id': target, 'member_ids': [run['id'] for run in members],
            'attempts': [{key: run.get(key) for key in ('id', 'created_at', 'status', 'retry_of', 'recovery_of', 'archive_code')} for run in members],
            'incomplete_lineage': bool(root.get('retry_of') or root.get('recovery_of')),
            'summary_issue': bool(summary_failures),
            'lanorange_full_delivery': root.get('lanorange_full_delivery', False),
            'result_layout': root.get('result_layout', 1),
        })
    return sorted(records, key=lambda record: record['updated_at'], reverse=True)


def list_records(manager, owner):
    return group_records(manager.record_snapshots(owner))


def get_record(manager, owner, record_id):
    from download_jobs import DownloadNotFound
    result = next((record for record in list_records(manager, owner) if record_id in record['member_ids']), None)
    if result is None:
        raise DownloadNotFound('下载记录不存在')
    return result


def record_bundle(manager, owner, record_id, city=None, purpose='results'):
    from download_jobs import DownloadNotFound, DownloadArchiveError
    from download_archive import archive_component, artifact_scope
    record = get_record(manager, owner, record_id)
    if purpose == 'sources':
        return review_bundle(manager,owner,record_id,city)
    if record.get('result_layout')==3 and record['status'] not in ACTIVE:
        manager.publish_delivery(owner,record_id)
        record=get_record(manager,owner,record_id)
    from task_catalog import GENERATORS
    targets = {value for value in record['datasets'] if value in GENERATORS}
    if purpose not in ('results', 'sources'):
        raise DownloadNotFound('文件领取范围无效')
    eligible = record['files']
    if record['kind'] == 'generate':
        eligible = [file for file in eligible if (file['dataset'] in targets) == (purpose == 'results')]
    elif purpose == 'sources':
        raise DownloadNotFound('此任务没有独立的来源资料包')
    entries = [file for file in eligible if file.get('available', True) and (not city or file['city'] == city)]
    if not entries:
        raise DownloadNotFound('本次记录暂无可领取文件')
    bundle_root = manager.db_path.parent / 'bundles'
    bundle_root.mkdir(parents=True, exist_ok=True)
    handle, filename = tempfile.mkstemp(prefix='record_', suffix='.zip', dir=bundle_root)
    os.close(handle)
    target = Path(filename)
    try:
        receipt = {'record_id': record['id'], 'status': record['status'], 'city': city, 'purpose': purpose,
                   'files': entries, 'unavailable': [file for file in eligible if not file.get('available', True)],
                   'note': '汇集关联任务当前可用版本，原始处理记录与文件未修改。'}
        with zipfile.ZipFile(target, 'w', zipfile.ZIP_DEFLATED, allowZip64=True) as archive:
            if record.get('result_layout',1) < 3:
                archive.writestr('下载说明.json', json.dumps(receipt, ensure_ascii=False, indent=2))
            if record.get('result_layout',1) >= 2:
                import csv
                import io
                table = io.StringIO(newline='')
                writer = csv.writer(table)
                writer.writerow(['任务编号','任务状态','城市','资料','开始日期','结束日期','文件','可用状态'])
                for file in eligible:
                    writer.writerow([record['id'],record['status'],file['city'],file['dataset'],*artifact_scope(file),file['name'],'可用' if file.get('available',True) else file.get('unavailable_reason','不可用')])
                writer.writerow(['未完成资料项',record['failed_items']])
                for item in record.get('incomplete_items', []):
                    writer.writerow([record['id'],item['status'],item['city'],item['dataset'],*artifact_scope(item),'未生成文件','未完成'])
                if record.get('result_layout') != 3:
                    archive.writestr('任务清单.csv', table.getvalue().encode('utf-8-sig'))
            used = set()
            for file in entries:
                run_owner = manager.run_owner(file['run_id']) if owner is None else owner
                source, name = manager.get_file(run_owner, file['run_id'], file['id'])
                if (not isinstance(name, str) or name in ('.', '..') or Path(name).name != name
                        or any(char in name for char in '/\\:\r\n\x00')):
                    raise DownloadArchiveError('成品名称无效，已停止打包')
                with manager._lock, manager._connection() as connection:
                    _, run = manager._find(connection, run_owner, file['run_id'])
                    expected = next(item for item in run['files'] if item['id'] == file['id'])
                prefix = ('来源/' if purpose == 'sources' else '结果/') if record.get('result_layout') == 2 else ''
                relative = name if record.get('result_layout') == 3 else f"{prefix}{archive_component(file['city'])}/{name}"
                if relative.casefold() in used:
                    relative = f"{file['run_id'][:8]}_{file['id'][:8]}_{name}" if record.get('result_layout') == 3 else f"{prefix}{archive_component(file['city'])}/{file['run_id'][:8]}_{file['id'][:8]}_{name}"
                if relative.casefold() in used:
                    raise DownloadArchiveError('文件名重复，已停止打包')
                used.add(relative.casefold())
                digest, size = hashlib.sha256(), 0
                with source.open('rb') as stream, archive.open(relative, 'w', force_zip64=True) as output:
                    while block := stream.read(1024 * 1024):
                        digest.update(block); size += len(block); output.write(block)
                if size != expected['bytes'] or digest.hexdigest() != expected['sha256']:
                    raise DownloadNotFound('文件在打包期间发生变化，请重新检查下载记录')
        return target, f"下载记录_{record['id'][:8].upper()}.zip"
    except BaseException:
        target.unlink(missing_ok=True)
        raise


def review_bundle(manager,owner,record_id,city=None):
    """Business source files only, with provenance; excludes diagnostics and generated copies."""
    import csv
    import io
    from download_archive import archive_component
    from download_jobs import DownloadNotFound, DownloadSummaryPending
    record=get_record(manager,owner,record_id)
    if record['status'] in ACTIVE:
        raise DownloadSummaryPending('任务结束后领取复核资料')
    base=manager.db_path.parent/'bundles';base.mkdir(parents=True,exist_ok=True)
    handle,name=tempfile.mkstemp(suffix='.zip',dir=base);os.close(handle);target=Path(name)
    try:
        count=0;used={};table=io.StringIO(newline='');writer=csv.writer(table)
        writer.writerow(['来源任务','来源相对位置','领取文件','字节数','SHA256','说明'])
        with zipfile.ZipFile(target,'w',zipfile.ZIP_DEFLATED,allowZip64=True) as archive:
            for run_id in record['member_ids']:
                run_owner=manager.run_owner(run_id) if owner is None else owner
                folder=manager._run_directory(run_owner,run_id)
                raw=folder/'原始资料'
                if not raw.is_dir():continue
                for source in sorted(raw.rglob('*')):
                    if source.is_symlink() or not source.resolve().is_relative_to(raw.resolve()):
                        raise ValueError('复核来源路径无效')
                    relative=source.relative_to(raw)
                    if not source.is_file() or source.name.startswith('.') or any(part in ('generated','inputs') for part in relative.parts) or source.suffix.lower() not in ('.xlsx','.xls','.csv','.zip'):
                        continue
                    if city and relative.parts[0] not in (city,'支付绑定公共来源','蓝橙','商翼'):
                        continue
                    from delivery_store import digest
                    checksum=digest(source)
                    # Identical source bytes are exported once; every original
                    # location is still represented in the provenance table.
                    if checksum not in used:
                        context='_'.join(relative.parts[:-1])
                        context=context.replace('payment_binding','支付绑定').replace('rider_detail','骑手明细').replace('receive_account','收薪账户').replace('rider_info','骑手信息')
                        export=archive_component((context+'_'+source.stem)[:65])+'_'+checksum[:8]+source.suffix.lower()
                        actual=hashlib.sha256()
                        with source.open('rb') as original,archive.open(export,'w',force_zip64=True) as output:
                            while chunk:=original.read(1024*1024):
                                output.write(chunk);actual.update(chunk)
                        if actual.hexdigest()!=checksum:raise ValueError('复核来源在打包期间变化')
                        used[checksum]=export;count+=1
                    writer.writerow([run_id,str(relative),used[checksum],source.stat().st_size,checksum,'平台来源原件；实际采用范围及筛选规则请核对任务记录'])
            if not count:
                raise DownloadNotFound('本任务暂无可领取的来源原件')
            archive.writestr('来源清单.csv',table.getvalue().encode('utf-8-sig'))
        return target,'复核资料_'+record['id'][:8].upper()+'.zip'
    except BaseException:
        target.unlink(missing_ok=True)
        raise
