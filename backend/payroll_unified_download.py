"""One public payroll download job; platform permission scopes stay internal."""
import copy
import csv
import hashlib
from pathlib import Path
import threading
import time


def merge_tables(paths, target):
    """Align source columns, without rejecting different schemas or deleting rows."""
    from deduction_confirmation import tables
    from openpyxl import Workbook, load_workbook
    paths=[Path(p) for p in paths];target=Path(target);target.parent.mkdir(parents=True,exist_ok=True)
    if target.suffix.lower()=='.csv':
        headers=[]
        for path in paths:
            for rows in tables(path):
                for col in next(iter(rows),[]):
                    if col not in headers:headers.append(col)
        with target.open('w',encoding='utf-8-sig',newline='') as stream:
            writer=csv.writer(stream);writer.writerow(headers)
            for path in paths:
                for rows in tables(path):
                    iterator=iter(rows);header=list(next(iterator,[]));indices=[header.index(c) if c in header else None for c in headers]
                    for row in iterator:writer.writerow([row[i] if i is not None and i<len(row) else None for i in indices])
    else:
        # Read headers first so all rows stay on the same logical sheet even
        # when individual platform exports add or reorder columns.
        headers={};shared=set()
        for path in paths:
            source=load_workbook(path,read_only=True,data_only=True)
            try:
                for sheet in source:
                    sheet.reset_dimensions()
                    for col in next(iter(sheet.iter_rows(values_only=True)),[]):
                        if col not in headers.setdefault(sheet.title,[]):headers[sheet.title].append(col)
            finally:source.close()
        book=Workbook(write_only=True);sheets={name:book.create_sheet(name) for name in headers}
        for name,header in headers.items():sheets[name].append(header)
        try:
            for path in paths:
                source=load_workbook(path,read_only=True,data_only=True)
                try:
                    for sheet in source:
                        sheet.reset_dimensions();iterator=iter(sheet.iter_rows(values_only=True));header=list(next(iterator,[]))
                        indices=[header.index(col) if col in header else None for col in headers[sheet.title]]
                        destination=sheets[sheet.title]
                        for row in iterator:
                            values=[row[i] if i is not None and i<len(row) else None for i in indices]
                            if sheet.title=='商翼绑定表':
                                identity=tuple(str(v) for v in values)
                                if identity in shared:continue
                                shared.add(identity)
                            from openpyxl.cell import WriteOnlyCell
                            cells=[]
                            for value in values:
                                cell=WriteOnlyCell(destination,value=value)
                                if isinstance(value,str):cell.data_type='s'
                                cells.append(cell)
                            destination.append(cells)
                finally:source.close()
            book.save(target)
        finally:book.close()


def execute(config, run_dir, log, cancelled, update_item, runner_factory=None):
    from download_service import execute_downloads, _requested_items, _item_key, DownloadCancelled, _checkpoint, DATASETS
    from download_archive import archive_filename
    from payroll_source_notes import source_reason
    root=Path(run_dir).resolve();root.mkdir(parents=True,exist_ok=True)
    available={};failures={};published={}
    single=config.get('payroll_scope_mode')=='single'
    scopes=[('selected',None)] if single else [('city',None)]+[(str(agency),agency) for agency in config.get('payroll_scope_agencies',[])]
    requested=_requested_items(config)
    def publish_available(final=False):
        for description in requested:
            key=_item_key(description)
            if key in published:continue
            sources=available.get(key,[])
            if not sources:
                if final:update_item({**description,'status':'error','phase':'failed','error':'；'.join(failures.get(key,[])) or '采集已结束，但没有取得可用文件'})
                continue
            if not final and description['dataset']!='delivery_fee':continue
            suffix=Path(sources[0]).suffix
            name=archive_filename(description['city'],description['dataset'],description['start'],description['end'],suffix=suffix,stamp=config.get('archive_created_at'))
            target=root/'结果'/name
            try:
                if len(sources)==1:
                    import shutil
                    target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(sources[0],target)
                else:merge_tables(sources,target)
                with target.open('rb') as stream:checksum=hashlib.file_digest(stream,'sha256').hexdigest()
                info={**description,'name':name,'relative_path':str(target.relative_to(root)),'bytes':target.stat().st_size,
                      'sha256':checksum}
                published[key]=info;update_item({**description,'status':'success','phase':'completed','files':[info]})
            except Exception as exc:
                if cancelled.is_set():raise DownloadCancelled('任务已停止')
                reason='文件归档未完成：'+source_reason(exc,'input_validation')
                if final:
                    log(f"【{description['city']} · {description['dataset']}】{reason}")
                    update_item({**description,'status':'error','phase':'failed','error':reason})
    # Ask for the rider export verification while the user is still present.
    priority=[kind for kind in ('payment_binding','delivery_fee') if kind in config['datasets']]
    # Fraud and problem share the same waybill export: one child run collects both.
    order_kinds=[kind for kind in ('fraud','problem') if kind in config['datasets']]
    batches=[[kind] for kind in priority]
    for kind in config['datasets']:
        if kind in priority:continue
        if kind in order_kinds:
            if order_kinds not in batches:batches.append(order_kinds)
        else:batches.append([kind])
    for datasets in batches:
        mandatory=datasets==['delivery_fee']
        wait_for_binding=datasets==['payment_binding']
        for scope,agency in scopes:
            _checkpoint(cancelled)
            if agency is not None and datasets==['lanorange_part_price']:continue
            child=copy.deepcopy(config)
            for field in ('payroll_unified','payroll_scope_mode','payroll_scope_agencies','retry_items'):child.pop(field,None)
            child['datasets']=datasets
            if single and 'exclude_separation' in config:
                child.pop('include_separation',None)
            else:
                child.pop('exclude_separation',None)
                child['include_separation']=bool(config.get('include_separation')) if single else agency is not None
            if agency is not None:child['payroll_agencies']={config['cities'][0]:str(agency)}
            child_dir=root/'原始资料'/'平台读取'/scope/('配送资料' if mandatory else '其他资料')/datasets[0]
            child_requested=_requested_items(child)
            authentication_needed=False
            def remember_failure(key,reason):
                reason=source_reason(reason)
                if reason not in failures.setdefault(key,[]):failures[key].append(reason)
            internal_stop=threading.Event()
            class Cancellation:
                def is_set(self):return cancelled.is_set() or internal_stop.is_set()
                def wait(self,timeout=None):
                    deadline=None if timeout is None else time.monotonic()+timeout
                    while not self.is_set():
                        remaining=.1 if deadline is None else deadline-time.monotonic()
                        if remaining<=0:return False
                        internal_stop.wait(min(remaining,.1))
                    return True
                def set(self):internal_stop.set()
            def changed(event):
                nonlocal authentication_needed
                if event.get('_run_event'):
                    if event.get('status')=='waiting_login' and wait_for_binding:
                        authentication_needed=True
                        update_item({**event,'payroll_verification_required':True})
                    elif event.get('status')=='waiting_login' and not mandatory:
                        authentication_needed=True
                        for description in child_requested:
                            remember_failure(_item_key(description),'需要完成平台验证' if event.get('phase')=='waiting_manual' else '需要登录来源平台')
                        internal_stop.set()
                    else:update_item(event)
                    return
                key=_item_key(event)
                for info in event.get('files',[]):
                    path=(child_dir/info['relative_path']).resolve()
                    if path.is_relative_to(child_dir.resolve()) and path.is_file() and path not in available.setdefault(key,[]):available[key].append(path)
                if wait_for_binding and event.get('status') in ('waiting_login','running'):
                    if event['status']=='waiting_login':authentication_needed=True
                    # Dependency events belong to the public payment-binding item.
                    for description in child_requested:
                        update_item({**description,'status':event['status'],'phase':event.get('phase','preparing'),
                                     **({'payroll_verification_required':True} if event['status']=='waiting_login' else {})})
                elif event.get('status')=='waiting_login' and not mandatory:
                    authentication_needed=True
                    for description in child_requested:
                        remember_failure(_item_key(description),'需要完成平台验证' if event.get('phase')=='waiting_manual' else '需要登录来源平台')
                    internal_stop.set()
                elif event.get('status') in ('error','interrupted') and event.get('error'):
                    affected=[description for description in child_requested if _item_key(description)==key] or child_requested
                    for description in affected:remember_failure(_item_key(description),event['error'])
                elif event.get('status') not in ('success','error','cancelled'):
                    update_item({**{k:event[k] for k in ('city','dataset','start','end')},'status':'running','phase':event.get('phase','downloading')})
            try:
                execute_downloads(child,child_dir,log,Cancellation(),changed,runner_factory)
            except DownloadCancelled as exc:
                if cancelled.is_set():raise
                for description in child_requested:
                    key=_item_key(description)
                    if key not in available and not authentication_needed:remember_failure(key,'本项采集已中断，未取得文件')
            except Exception as exc:
                if cancelled.is_set():raise DownloadCancelled('任务已停止')
                for description in child_requested:
                    if _item_key(description) not in available:remember_failure(_item_key(description),source_reason(exc))
            if wait_for_binding and authentication_needed and any(_item_key(description) not in available for description in child_requested):
                from parttime_source import SourceError
                raise SourceError('骑手支付绑定的平台验证或导出未完成，本次未生成工资表；已有资料保留')
            for description in child_requested:
                key=_item_key(description)
                if key not in available and key in failures:
                    label=DATASETS.get(description['dataset'],description['dataset'])
                    log(f"【{description['city']} · {label}】{'；'.join(failures[key])}；未参与本次核算" if not mandatory else f"【{description['city']} · {label}】{'；'.join(failures[key])}")
        if mandatory:publish_available()
    publish_available(True)
    return list(published.values())
