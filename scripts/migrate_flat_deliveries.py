"""Offline, backed-up migration. No platform requests or business calculations.

Run with --apply only after stopping this project's service. A worker lock and
active-state check prevent moving a live task. A failed migration rolls back
directories and both SQLite indexes; failed copies remain in the backup.
"""
import argparse
from contextlib import closing
import datetime as dt
import json
import os
from pathlib import Path
import shutil
import sqlite3
import sys
import uuid

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'backend'))
from delivery_store import digest


def safe(path, base):
    path=Path(path).absolute();base=Path(base).resolve()
    if path==base or not path.is_relative_to(base) or path.resolve()!=path:
        raise ValueError('迁移路径越界或含链接')
    for part in (path,*path.parents):
        if part==base:break
        if part.is_symlink() or part.is_junction():raise ValueError('不迁移链接目录')
    return path


def inventory(folder):
    result={}
    for current,dirs,files in os.walk(folder,followlinks=False):
        for name in dirs+files:safe(Path(current)/name,folder)
        for name in files:
            path=Path(current)/name
            result[str(path.relative_to(folder))]={'bytes':path.stat().st_size,'sha256':digest(path)}
    return result


def snapshot(source,target):
    with closing(sqlite3.connect(source)) as original,closing(sqlite3.connect(target)) as backup:original.backup(backup)


def plan(database):
    with closing(sqlite3.connect(database)) as db:
        rows=[{**json.loads(row[0]),'owner':row[1]} for row in db.execute('SELECT state_json,owner FROM download_runs ORDER BY created_at,rowid')]
    if any(row['status'] in ('queued','running','waiting_login','cancelling') for row in rows):
        raise RuntimeError('仍有执行中任务，未迁移任何文件')
    # A family with a failed or recoverable member stays entirely in place.
    from download_records import group_records
    groups=group_records([{**row,'_record_order':i} for i,row in enumerate(rows)])
    eligible={key for group in groups if group['status']=='success' and all(next(r for r in rows if r['id']==key)['status']=='success' for key in group['member_ids']) for key in group['member_ids']}
    return [row for row in rows if row['id'] in eligible and row.get('result_layout',1)<3]


def migrate(database,output_root,apply=False):
    database=Path(database).resolve();output_root=Path(output_root).resolve()
    rows=plan(database)
    report={'eligible':len(rows),'tasks':[],'applied':False}
    if not apply:
        report['tasks']=[{'id':r['id'],'status':r['status'],'source':str(Path(r['_archive_root'])/r['archive_relative_dir'])} for r in rows]
        return report
    from download_jobs import DownloadManager
    from download_records import get_record
    manager=DownloadManager(database,output_root)
    backup=database.parent/'layout_migration'/(dt.datetime.now().strftime('%Y%m%d_%H%M%S')+'_'+uuid.uuid4().hex[:6])
    backup.mkdir(parents=True)
    report['backup']=str(backup)
    snapshot(database,backup/'tasks.sqlite3')
    snapshot(manager.deliveries.path,backup/'deliveries.sqlite3')
    copied=[];moved=[];published=[]
    def write_report():
        temporary=backup/'journal.tmp';temporary.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8');os.replace(temporary,backup/'journal.json')
    try:
        # Complete and verify every backup before moving the first workspace.
        for row in rows:
            source=manager._run_directory(row['owner'],row['id'])
            safe(source,output_root)
            target=safe(manager.workspace_root/row['archive_relative_dir'],database.parent)
            if target.exists():raise ValueError('内部目标目录已存在，未覆盖')
            saved=backup/'originals'/row['id']
            before=inventory(source);shutil.copytree(source,saved)
            if inventory(saved)!=before:raise ValueError('备份校验失败')
            copied.append((row,source,target,saved,before))
            report['tasks'].append({'id':row['id'],'source':str(source),'workspace':str(target),'files':len(before),'bytes':sum(f['bytes'] for f in before.values()),'backup_verified':True,'inventory':before})
        write_report()
        for row,source,target,saved,before in copied:
            target.parent.mkdir(parents=True,exist_ok=True)
            copied_workspace=False
            try:os.replace(source,target)
            except PermissionError:
                # Explorer or an antivirus can deny a directory rename while
                # permitting reads. Verify a complete workspace copy first.
                moved.append((source,target,saved,True))
                shutil.copytree(source,target)
                if inventory(target)!=before:raise ValueError('工作目录复制校验失败')
                copied_workspace=True
            if not copied_workspace:moved.append((source,target,saved,False))
            manager._mutate(row['owner'],row['id'],lambda run:run.update(_archive_root=str(manager.workspace_root),result_layout=3))
            write_report()
        seen=set()
        for row,source,target,saved,before in copied:
            record=get_record(manager,row['owner'],row['id'])
            if record['id'] in seen:continue
            seen.add(record['id'])
            folder=manager.publish_delivery(row['owner'],row['id']);published.append(folder)
            task=next(item for item in report['tasks'] if item['id']==row['id']);task['delivery']=str(folder)
            canonical={digest(p):p for p in folder.iterdir() if p.is_file() and p.suffix.lower() in ('.xlsx','.xls')}
            removed=[]
            # Only proven generated copies, never retained inputs or receipts.
            for path in sorted(target.rglob('*')):
                if not path.is_file() or path.suffix.lower() not in ('.xlsx','.xls'):continue
                relative=path.relative_to(target)
                if 'generated' not in relative.parts and len(relative.parts)!=1:continue
                checksum=digest(path)
                if checksum in canonical and before.get(str(relative),{}).get('sha256')==checksum:
                    safe(path,target);path.unlink();removed.append(str(relative))
            task['generated_copies_removed']=removed
            write_report()
        report['applied']=True;write_report()
        for source,target,saved,was_copy in moved:
            if not was_copy:continue
            before=inventory(saved);pending=[]
            for relative,expected in before.items():
                path=safe(source/relative,source)
                try:
                    if path.stat().st_size!=expected['bytes'] or digest(path)!=expected['sha256']:
                        pending.append(relative);continue
                    path.unlink()
                except OSError:pending.append(relative)
            for directory in sorted((p for p in source.rglob('*') if p.is_dir()),key=lambda p:len(p.parts),reverse=True):
                safe(directory,source)
                try:directory.rmdir()
                except OSError:pass
            try:source.rmdir()
            except OSError:pending.append('[原目录仍被占用]')
            task=next(t for t in report['tasks'] if t['source']==str(source))
            task['copy_fallback']=True;task['cleanup_pending']=pending
        write_report()
        # An empty month container can be removed; never remove nonempty trees.
        for _,source,_,_,_ in copied:
            if source.parent!=output_root:
                safe(source.parent,output_root)
                try:source.parent.rmdir()
                except OSError:pass
        return report
    except BaseException:
        manager.shutdown()
        for index,folder in enumerate(published):
            safe(folder,output_root)
            if folder.exists():os.replace(folder,backup/('failed_delivery_'+str(index)))
        # Include folders created before publish returned.
        with manager.deliveries.db() as db:
            current=[Path(row[0]) for row in db.execute('SELECT folder FROM deliveries')]
        with closing(sqlite3.connect(backup/'deliveries.sqlite3')) as db:
            original={Path(row[0]) for row in db.execute('SELECT folder FROM deliveries')}
        for index,folder in enumerate(current):
            if folder not in original and folder.exists():
                safe(folder,output_root);os.replace(folder,backup/('failed_partial_'+str(index)))
        for index,(source,target,saved,was_copy) in enumerate(reversed(moved)):
            if target.exists():
                safe(target,database.parent);os.replace(target,backup/('failed_workspace_'+str(index)))
            if source.exists():
                if not was_copy or inventory(source)!=inventory(saved):raise RuntimeError('回滚原位置被占用，备份已保留：'+str(backup))
            else:
                source.parent.mkdir(parents=True,exist_ok=True);shutil.copytree(saved,source)
            if inventory(saved)!=inventory(source):raise RuntimeError('回滚校验失败：'+str(backup))
        snapshot(backup/'tasks.sqlite3',database)
        snapshot(backup/'deliveries.sqlite3',manager.deliveries.path)
        report['rolled_back']=True;write_report()
        raise
    finally:
        manager.shutdown()


def publish_existing_receipts(backup):
    """Read existing approval/export records only; never call an official API."""
    from delivery_store import approval_delivery
    from lanorange_approvals import ApprovalManager,ROOT as approvals_path
    from lanorange_price_export import PriceExports,ROOT as prices_root
    report={'approvals':0,'price_exports':0,'payroll_batches':0,'errors':[]}
    for path,table in ((approvals_path,'batches'),(prices_root/'exports.sqlite3','exports')):
        if path.is_file():
            with closing(sqlite3.connect(path)) as db:
                if db.execute("SELECT 1 FROM "+table+" WHERE status IN ('queued','running','stopping') LIMIT 1").fetchone():
                    raise RuntimeError('仍有价格任务执行中，未整理价格记录')
            snapshot(path,backup/('original_'+table+'.sqlite3'))
    if approvals_path.is_file():
        approvals=ApprovalManager()
        with approvals.connection() as db:rows=[dict(row) for row in db.execute('SELECT id,scope FROM batches')]
        for row in rows:
            try:approval_delivery(approvals,row['scope'],row['id']);report['approvals']+=1
            except Exception:report['errors'].append({'type':'approval','id':row['id']})
    if (prices_root/'exports.sqlite3').is_file():
        prices=PriceExports()
        with prices.db() as db:rows=[dict(row) for row in db.execute("SELECT id,scope FROM exports WHERE status IN ('completed','partial')")]
        for row in rows:
            try:
                source=prices_root/row['id']
                if source.is_dir():
                    safe(source,prices_root);saved=backup/'prices'/row['id'];before=inventory(source);shutil.copytree(source,saved)
                    if inventory(saved)!=before:raise ValueError('价格备份校验失败')
                prices.result(row['scope'],row['id']);report['price_exports']+=1
            except Exception:report['errors'].append({'type':'price-export','id':row['id']})
    from payroll_inputs import publish_result,save
    for manifest in (ROOT/'uploads').glob('*/payroll_*/manifest.json'):
        try:
            state=json.loads(manifest.read_text(encoding='utf-8'))
            if state['status']!='calculated':continue
            wid=manifest.parent.parent.name;key=state['id'];source=Path(state['result']['output']).resolve()
            safe(source,ROOT/'outputs/payroll_batches'/wid/key)
            saved=backup/'payroll'/key;before=inventory(source)
            shutil.copytree(source,saved/'output');shutil.copy2(manifest,saved/'manifest.json')
            if inventory(saved/'output')!=before:raise ValueError('核算备份校验失败')
            publish_result(wid,manifest.parent,state);report['payroll_batches']+=1
        except Exception:report['errors'].append({'type':'payroll','manifest':str(manifest)})
    (backup/'other_deliveries.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    return report


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--apply',action='store_true');args=parser.parse_args()
    from download_jobs import configured_output_root
    value=migrate(ROOT/'backend/.local_downloads/tasks.sqlite3',configured_output_root(),args.apply)
    if args.apply:value['other_deliveries']=publish_existing_receipts(Path(value['backup']))
    print(json.dumps({**value,'tasks':[{k:v for k,v in task.items() if k!='inventory'} for task in value['tasks']]},ensure_ascii=False,indent=2))
