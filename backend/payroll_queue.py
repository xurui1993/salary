"""Shared durable payroll queue. HTTP requests never own calculation workers."""
import asyncio
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import shutil
import sqlite3
import threading
import time
from types import SimpleNamespace
import uuid
import zipfile

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse
from starlette.background import BackgroundTask

from parttime_source import ROOT, SourceError, owned_upload, source_files

router=APIRouter(prefix='/api/parttime/queue')
ACTIVE={'preparing','calculating','stopping'}
FINISHED={'completed','error','cancelled','interrupted'}
_STORE=None
_STORE_LOCK=threading.Lock()


def now():
    return datetime.now(timezone.utc).isoformat()


def selected_ids(ids):
    if (not isinstance(ids,list) or not 1<=len(ids)<=100
            or any(not isinstance(key,str) or not re.fullmatch(r'[a-f0-9]{32}',key) for key in ids)):
        raise SourceError('请选择1–100个有效队列任务')
    return list(dict.fromkeys(ids))


def frozen_config(value,mode):
    value=value if isinstance(value,dict) else {}
    for key in ('enableInterceptor','enableCrossStationMerge','payrollExcludeSeparation'):
        if key in value and type(value[key]) is not bool:raise SourceError('核算选项必须为布尔值：'+key)
    theme=dict(value['theme']) if isinstance(value.get('theme'),dict) else {}
    defaults={'msg_start':'开始核算','msg_awake':'正在准备核算环境','msg_empty':'本次没有其他资料',
              'msg_process':'正在处理 {wb_name}','msg_success':'{wb_name}处理完成','msg_final':'正在生成结果','msg_end':'核算完成'}
    for key,message in defaults.items():
        if not isinstance(theme.get(key),list) or not theme[key] or not all(isinstance(v,str) for v in theme[key]):theme[key]=[message]
    return {'basePath':str(value.get('basePath') or ''),'theme':theme,
            'enableInterceptor':bool(value.get('enableInterceptor',False)),
            'enableCrossStationMerge':bool(value.get('enableCrossStationMerge',False)),
            'payrollExcludeSeparation':value.get('payrollExcludeSeparation',True) is not False,
            'payrollSourceMode':mode,'action':'core'}


class PayrollQueue:
    def __init__(self,root=ROOT,runner=None,autostart=True):
        self.root=Path(root).resolve();self.path=self.root/'backend/.local_downloads/payroll_queue.sqlite3'
        self.path.parent.mkdir(parents=True,exist_ok=True)
        self.lock=threading.RLock();self.wake=threading.Event();self.closing=threading.Event()
        self.thread=None;self.runner=runner;self.autostart=autostart
        self.instance_lock=None
        if autostart:
            from download_single_instance import InstanceLock
            self.instance_lock=InstanceLock(self.path.with_suffix('.worker.lock'))
        with self.connection() as db:
            db.executescript('''CREATE TABLE IF NOT EXISTS tasks(id TEXT PRIMARY KEY,wid TEXT NOT NULL,owner TEXT NOT NULL,status TEXT NOT NULL,hidden INTEGER NOT NULL DEFAULT 0,created REAL NOT NULL,body TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS submissions(wid TEXT NOT NULL,owner TEXT NOT NULL,request_id TEXT NOT NULL,fingerprint TEXT NOT NULL,ids TEXT NOT NULL,PRIMARY KEY(wid,owner,request_id));''')
            rows=db.execute("SELECT id,body FROM tasks WHERE status IN ('preparing','calculating','stopping')").fetchall()
            for row in rows:
                task=json.loads(row['body']);task.update(status='interrupted',current_action='服务曾中断，原资料和结果保留；未自动重跑',finished_at=now())
                self._write(db,task)
        if autostart:self.start()

    @contextmanager
    def connection(self):
        db=sqlite3.connect(self.path,timeout=20);db.row_factory=sqlite3.Row
        try:
            yield db;db.commit()
        except BaseException:
            db.rollback();raise
        finally:db.close()

    def start(self):
        with self.lock:
            if self.thread is None:
                self.thread=threading.Thread(target=self._work,name='payroll-queue',daemon=True);self.thread.start()

    def _work(self):
        try:self._worker()
        finally:
            if self.instance_lock is not None:self.instance_lock.release()

    def _write(self,db,task):
        db.execute('UPDATE tasks SET status=?,hidden=?,body=? WHERE id=?',(task['status'],int(task.get('hidden',False)),json.dumps(task,ensure_ascii=False),task['id']))

    def _find(self,db,wid,owner,key):
        row=db.execute('SELECT body FROM tasks WHERE id=? AND wid=? AND owner=?',(key,wid,owner)).fetchone()
        if not row:raise SourceError('本工作区队列任务不存在')
        return json.loads(row['body'])

    def _public(self,task):
        value={k:v for k,v in task.items() if not k.startswith('_') and k not in ('wid','owner','config','source_path','template_path','stop_requested')}
        start=task.get('_started_clock');finish=task.get('_finished_clock')
        value['elapsed_seconds']=max(0,int((finish or time.time())-start)) if start else 0
        return value

    def view(self,wid,owner,hidden=False,detail_id=''):
        tasks=self.list(wid,owner,hidden)
        selected=detail_id or (tasks[0]['id'] if tasks else '')
        for task in tasks:
            if task['id']==selected:continue
            task['logs']=[]
            preparation=task.get('preparation')
            if preparation:task['preparation']={k:preparation[k] for k in ('id','mode','status','plan','deductions') if k in preparation}
        return tasks

    def list(self,wid,owner,hidden=False):
        with self.lock,self.connection() as db:
            rows=db.execute('SELECT body FROM tasks WHERE wid=? AND owner=? AND hidden=? ORDER BY created,rowid',(wid,owner,int(hidden))).fetchall()
            return [self._public(json.loads(row['body'])) for row in rows]

    def get(self,wid,owner,key):
        with self.lock,self.connection() as db:return self._public(self._find(db,wid,owner,key))

    def enqueue(self,wid,owner,source,mode,config,request_id):
        if mode not in ('fengshen','manual','xiaoxiang'):raise SourceError('未知核算方式')
        if not isinstance(source,str) or not source:raise SourceError('请从系统上传入口添加资料')
        if not isinstance(request_id,str) or not re.fullmatch(r'[A-Za-z0-9_-]{8,128}',request_id):raise SourceError('提交标识无效，请重新选择资料')
        folder,_=owned_upload(source,wid,self.root)
        files=source_files(folder)
        templates=sorted([p for p in files if 'template' in p.name.lower() and p.suffix.lower()=='.xlsx'])
        if not templates:raise SourceError('没有找到 .xlsx template 薪资申请表')
        if len(templates)>100:raise SourceError('单次最多添加100份薪资模板，请分批提交')
        config=frozen_config(config,mode)
        fingerprint=hashlib.sha256(json.dumps([str(folder),mode,config,[str(p.relative_to(folder)) for p in templates]],sort_keys=True,ensure_ascii=False).encode()).hexdigest()
        with self.lock,self.connection() as db:
            old=db.execute('SELECT fingerprint,ids FROM submissions WHERE wid=? AND owner=? AND request_id=?',(wid,owner,request_id)).fetchone()
            if old:
                if old['fingerprint']!=fingerprint:raise SourceError('提交标识对应的资料范围已变化，请重新添加')
                return [self._public(self._find(db,wid,owner,key)) for key in json.loads(old['ids'])]
            ids=[];tasks=[]
            for template in templates:
                key=uuid.uuid4().hex
                from payroll_business import xiaoxiang_template
                actual_mode='xiaoxiang' if mode=='manual' and xiaoxiang_template(template) else mode
                task={'id':key,'wid':wid,'owner':owner,'mode':actual_mode,'source_path':str(folder),'template_path':template.relative_to(folder).as_posix(),
                      'template_name':template.name,'status':'queued','progress':0,'current_action':'排队中','created_at':now(),
                      'batch_id':None,'plan':None,'preparation':None,'logs':[],'hidden':False,'config':{**config,'payrollSourceMode':actual_mode},'stop_requested':False}
                db.execute('INSERT INTO tasks VALUES (?,?,?,?,?,?,?)',(key,wid,owner,'queued',0,time.time(),json.dumps(task,ensure_ascii=False)))
                ids.append(key);tasks.append(self._public(task))
            db.execute('INSERT INTO submissions VALUES (?,?,?,?,?)',(wid,owner,request_id,fingerprint,json.dumps(ids)))
        if self.autostart:self.start()
        self.wake.set();return tasks

    def _update(self,key,changes,log=None):
        with self.lock,self.connection() as db:
            row=db.execute('SELECT body FROM tasks WHERE id=?',(key,)).fetchone()
            if not row:return
            task=json.loads(row['body']);task.update(changes)
            if task.get('stop_requested') and task['status'] in ('preparing','calculating'):
                task.update(status='stopping',current_action='正在停止任务')
            if log:
                logs=task.setdefault('logs',[])
                if not logs or logs[-1]['text']!=log['text']:logs.append({**log,'time':now()})
                task['logs']=logs[-500:]
            self._write(db,task)

    def _stopped(self,key):
        with self.connection() as db:
            row=db.execute('SELECT body FROM tasks WHERE id=?',(key,)).fetchone()
            return not row or json.loads(row['body']).get('stop_requested',False)

    def _stage(self,task):
        """Associate materials with the nearest directory that owns templates."""
        source,_=owned_upload(task['source_path'],task['wid'],self.root)
        template=source/task['template_path']
        files=source_files(source)
        templates=[p for p in files if 'template' in p.name.lower() and p.suffix.lower()=='.xlsx']
        if template not in templates:raise SourceError('原上传模板暂不可访问，已保留任务记录')
        parents={p.parent for p in templates};group=template.parent
        if task['mode']=='manual':
            peers=[p for p in templates if p.parent==group]
            if len(peers)>1:
                from parttime_source import read_template
                scopes=set()
                for peer in peers:
                    try:
                        plan=read_template(peer,require_agency=False);scopes.add((plan.city,plan.start,plan.end))
                    except SourceError:continue
                if len(scopes)>1:raise SourceError('同目录多个模板的城市或账期不同，资料归属不明确；请按模板分别放入资料目录后添加')
        target=self.root/'uploads'/task['wid']/('upload_queue_'+task['id'])
        if target.exists():raise SourceError('队列资料目录已存在，未覆盖保留资料')
        target.mkdir(parents=True)
        selected=[template]
        if task['mode']!='fengshen':
            for path in files:
                if path in templates:continue
                owners=[parent for parent in parents if path.is_relative_to(parent)]
                nearest=max(owners,key=lambda p:len(p.parts)) if owners else None
                if nearest==group:selected.append(path)
        for path in selected:
            if self._stopped(task['id']):raise QueueStopped()
            relative=path.relative_to(group);destination=target/relative
            destination.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(path,destination)
        return target

    def _worker(self):
        while not self.closing.is_set():
            task=None
            with self.lock,self.connection() as db:
                row=db.execute("SELECT body FROM tasks WHERE status='queued' AND hidden=0 ORDER BY created,rowid LIMIT 1").fetchone()
                if row:
                    task=json.loads(row['body']);task.update(status='preparing',current_action='正在准备本任务资料',_started_clock=time.time(),_finished_clock=None);self._write(db,task)
            if task:
                try:asyncio.run(self._run(task))
                except QueueStopped:self._update(task['id'],{'status':'cancelled','current_action':'已停止，资料和结果保留','_finished_clock':time.time()})
                except Exception as error:
                    if self._stopped(task['id']):
                        self._update(task['id'],{'status':'cancelled','current_action':'已停止，资料和结果保留','_finished_clock':time.time()});continue
                    from payroll_source_notes import source_reason
                    reason=str(error) if isinstance(error,SourceError) else source_reason(error)
                    self._update(task['id'],{'status':'error','current_action':reason,'_finished_clock':time.time()}, {'text':reason,'level':'ERROR'})
                continue
            self.wake.wait(.5);self.wake.clear()

    async def _run(self,task):
        from payroll_inputs import run_payroll,load,public
        if self._stopped(task['id']):raise QueueStopped()
        source=await asyncio.to_thread(self._stage,task) if not task.get('batch_id') else Path(task['source_path'])
        if self._stopped(task['id']):raise QueueStopped()
        values={**task['config'],'sourcePath':str(source),'city':task.get('plan',{}).get('city','') if task.get('plan') else '',
                'payrollPreparationId':task.get('batch_id') or '',
                'preparationOnly':task['mode']!='fengshen' and not task.get('_continue_version'),
                'deductionConfigVersion':task.get('_continue_version',''),
                '_queue_cancelled':lambda:self._stopped(task['id']) or self.closing.is_set()}
        runner=self.runner or run_payroll
        last=None
        async for event in runner(SimpleNamespace(**values),None,context=(task['wid'],task['owner'])):
            if not event.startswith('data: '):continue
            try:data=json.loads(event[6:])
            except ValueError:continue
            kind=data.get('type')
            if kind=='payroll_preparation':
                prep=data['preparation'];last=prep;task['batch_id']=prep['id']
                status='calculating' if prep['status']=='calculating' else 'preparing'
                action='正在核算工资' if status=='calculating' else '正在准备资料'
                material=next((row for row in prep.get('downloads',[]) if row.get('status') in ('running','waiting_login')),None)
                if material:action=material['label']+'：'+material.get('detail','正在获取')
                self._update(task['id'],{'batch_id':prep['id'],'preparation':prep,'plan':prep['plan'],'status':status,'current_action':action})
            elif kind=='log':
                message=data.get('msg') or data.get('message') or ''
                self._update(task['id'],{'current_action':message} if message=='等待其他核算任务完成' else {}, {'text':message,'level':data.get('level','INFO')})
            elif kind=='progress':
                progress=data.get('value',0)
                try:progress=max(0,min(100,round(float(progress)*100)))
                except (ValueError,TypeError,OverflowError):progress=0
                self._update(task['id'],{'progress':progress,'current_action':data.get('text') or '正在处理'})
            elif kind=='finish':
                status=data.get('status')
                if task.get('batch_id'):
                    try:
                        _,stored=load(task['wid'],task['batch_id'],task['owner'],self.root);last=public(stored)
                    except SourceError:pass
                mapped='completed' if status=='success' else 'waiting_confirmation' if status=='paused' and task['mode']!='fengshen' else 'cancelled' if status=='cancelled' else 'error'
                self._update(task['id'],{'status':mapped,'preparation':last,'progress':100 if mapped=='completed' else 0,
                                        'current_action':'核算完成，可下载结果' if mapped=='completed' else '资料已准备，请确认扣款' if mapped=='waiting_confirmation' else '任务已停止，资料保留' if mapped=='cancelled' else '任务已结束，请查看日志',
                                        '_finished_clock':time.time()})
            if self._stopped(task['id']) and not (kind=='finish' and data.get('status')=='success'):
                if task.get('batch_id'):
                    from payroll_control import stop
                    await asyncio.to_thread(stop,task['wid'],task['batch_id'],task['owner'])
                # Let the generator persist its cooperative cancellation receipt.
        with self.connection() as db:
            latest=json.loads(db.execute('SELECT body FROM tasks WHERE id=?',(task['id'],)).fetchone()['body'])
        if self._stopped(task['id']) and latest['status']!='completed':raise QueueStopped()
        if latest['status'] in ACTIVE:self._update(task['id'],{'status':'error','current_action':'执行未正常结束，请查看日志','_finished_clock':time.time()})

    def stop(self,wid,owner,key):
        with self.lock,self.connection() as db:
            task=self._find(db,wid,owner,key)
            if task['status'] in FINISHED:return self._public(task)
            active=task['status'] in ACTIVE
            task.update(stop_requested=True,status='stopping' if active else 'cancelled',current_action='正在停止任务' if active else '已停止，资料保留')
            self._write(db,task)
        if task.get('batch_id'):
            from payroll_control import stop
            stop(wid,task['batch_id'],owner)
        self.wake.set();return self.get(wid,owner,key)

    def visibility(self,wid,owner,ids,restore=False,stop_first=False):
        ids=selected_ids(ids)
        with self.lock,self.connection() as db:
            tasks=[self._find(db,wid,owner,key) for key in ids]
            if not restore and not stop_first and any(t['status'] in ACTIVE for t in tasks):raise SourceError('请先停止执行中的任务再移出')
        if not restore and stop_first:
            for task in tasks:self.stop(wid,owner,task['id'])
        with self.lock,self.connection() as db:
            for key in ids:
                task=self._find(db,wid,owner,key)
                if not restore and task['status']=='queued':task.update(status='cancelled',stop_requested=True,current_action='已移出，资料保留')
                task['hidden']=not restore;self._write(db,task)
        return [self.get(wid,owner,key) for key in ids]

    def continue_task(self,wid,owner,key,version=''):
        from payroll_inputs import load
        from deduction_confirmation import require_confirmation
        with self.lock,self.connection() as db:
            task=self._find(db,wid,owner,key)
            if task.get('hidden') or task['status']!='waiting_confirmation' or not task.get('batch_id'):raise SourceError('本任务当前不等待扣款确认')
            _,state=load(wid,task['batch_id'],owner,self.root)
            stored=state.get('deductions',{}).get('version')
            if not stored or (version and stored!=version):raise SourceError('请先完成本任务扣款确认，再继续核算')
            require_confirmation(state,stored)
            task.update(status='queued',current_action='已确认扣款，等待核算',_continue_version=stored,stop_requested=False)
            self._write(db,task)
        self.wake.set();return self.get(wid,owner,key)

    def bundle(self,wid,owner,ids):
        from payroll_inputs import load,delivery_store,publish_result
        from delivery_store import delivery_bundle
        from download_archive import archive_component
        ids=selected_ids(ids)
        with self.lock,self.connection() as db:tasks=[self._find(db,wid,owner,key) for key in ids]
        if any(t['status']!='completed' or not t.get('batch_id') for t in tasks):raise SourceError('仅可下载已完成任务')
        directory=self.root/'backend/.local_downloads/bundles';directory.mkdir(parents=True,exist_ok=True)
        target=directory/('payroll_queue_'+uuid.uuid4().hex+'.zip')
        try:
            with zipfile.ZipFile(target,'x',zipfile.ZIP_STORED,allowZip64=True) as archive:
                for task in tasks:
                    folder,state=load(wid,task['batch_id'],owner,self.root);publish_result(wid,folder,state)
                    part,name=delivery_bundle(delivery_store(),'payroll:'+wid+':'+task['batch_id'])
                    prefix=archive_component(Path(task['template_name']).stem)+'_'+task['id'][:6]
                    try:
                        # A single ZIP with one shallow folder per template;
                        # users need not unpack an inner archive for each task.
                        with zipfile.ZipFile(part) as prepared:
                            for entry in prepared.infolist():
                                if entry.is_dir():continue
                                filename=Path(entry.filename).name
                                if not filename or filename!=entry.filename:raise SourceError('交付文件目录结构无效')
                                with prepared.open(entry) as incoming,archive.open(prefix+'/'+filename,'w',force_zip64=True) as outgoing:
                                    shutil.copyfileobj(incoming,outgoing,length=1024*1024)
                    finally:part.unlink(missing_ok=True)
            return target
        except BaseException:
            target.unlink(missing_ok=True);raise

    def shutdown(self):
        self.closing.set();self.wake.set()
        with self.connection() as db:rows=db.execute("SELECT body FROM tasks WHERE status IN ('preparing','calculating','stopping')").fetchall()
        for row in rows:
            task=json.loads(row['body'])
            try:self.stop(task['wid'],task['owner'],task['id'])
            except (SourceError,ValueError):pass
        if self.thread and self.thread is not threading.current_thread():self.thread.join(timeout=3)
        if self.instance_lock is not None and (self.thread is None or not self.thread.is_alive()):self.instance_lock.release()


class QueueStopped(BaseException):
    pass


def get_queue():
    global _STORE
    with _STORE_LOCK:
        if _STORE is None:_STORE=PayrollQueue()
        return _STORE


def shutdown_queue():
    global _STORE
    with _STORE_LOCK:
        if _STORE is not None:_STORE.shutdown();_STORE=None


def identity(request):
    from download_accounts import require_account
    from payroll_inputs import workspace
    user=require_account(request);return workspace(request),user['owner']


async def payload(request):
    try:value=await request.json()
    except ValueError:raise HTTPException(400,'队列参数必须为JSON对象') from None
    if not isinstance(value,dict):raise HTTPException(400,'队列参数必须为JSON对象')
    return value


def call(work,*args,**kwargs):
    try:return work(*args,**kwargs)
    except SourceError as error:raise HTTPException(409,str(error)) from None


@router.get('')
def list_tasks(request:Request,hidden:bool=False,detail_id:str=''):
    wid,owner=identity(request);return {'tasks':get_queue().view(wid,owner,hidden,detail_id)}


@router.post('')
async def add_tasks(request:Request):
    wid,owner=identity(request);data=await payload(request)
    if data.get('mode','fengshen')=='fengshen':
        from auth_preflight import ensure_ready
        await asyncio.to_thread(ensure_ready,{'fengshen','lanorange','baize'})
    tasks=await asyncio.to_thread(call,get_queue().enqueue,wid,owner,data.get('source_path',''),data.get('mode','fengshen'),data.get('config',{}),data.get('request_id'))
    return {'tasks':tasks}


@router.post('/visibility')
async def hide_tasks(request:Request):
    wid,owner=identity(request);data=await payload(request)
    return {'tasks':call(get_queue().visibility,wid,owner,data.get('ids'),data.get('restore') is True,data.get('stop_first') is True)}


@router.post('/bundle')
async def bundle_tasks(request:Request):
    wid,owner=identity(request);data=await payload(request)
    file=await asyncio.to_thread(call,get_queue().bundle,wid,owner,data.get('ids'))
    return FileResponse(file,filename='薪资核算结果.zip',media_type='application/zip',background=BackgroundTask(file.unlink,missing_ok=True))


@router.post('/{key}/stop')
def stop_task(key:str,request:Request):
    wid,owner=identity(request);return {'task':call(get_queue().stop,wid,owner,key)}


@router.post('/{key}/continue')
async def continue_task(key:str,request:Request):
    wid,owner=identity(request);data=await payload(request)
    return {'task':call(get_queue().continue_task,wid,owner,key,data.get('version',''))}
