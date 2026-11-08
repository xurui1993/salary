"""Durable, per-personal-space approval batches; never resume a write on restart."""
from contextlib import contextmanager
import csv
import io
import json
import os
from pathlib import Path
import re
import sqlite3
import threading
import time
import uuid

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import Response

from download_accounts import require_account
from download_routes import workspace_owner
from lanorange_approval_client import OfficialApprovalClient, ApprovalError, SubmissionUncertain, public_task, eligible, digest, identifier

ROOT=Path(__file__).parent/'.local_downloads/lanorange_approvals.sqlite3'
ACTIVE={'queued','running','stopping'}
BLOCKED={'pending','submitting','uncertain','success'}
MAX_SELECTED=200
LABELS={'pending':'等待提交','submitting':'正在提交','success':'已同意当前节点','failed':'提交被拒绝','changed':'内容或节点已变化','not_sent':'未提交','uncertain':'结果待核实'}
router=APIRouter(prefix='/api/fengshen-downloads/lanorange-approvals')
_manager=None
_manager_lock=threading.Lock()


def filters(value):
    if not isinstance(value,dict) or set(value)-{'city','station','period'}:raise ApprovalError('筛选条件无效','input')
    result={}
    for key in ('city','station','period'):
        text=value.get(key,'')
        if not isinstance(text,str) or len(text)>80:raise ApprovalError('筛选条件格式无效','input')
        result[key]=text.strip()
    if result['period'] and not re.fullmatch(r'\d{4}-(?:0[1-9]|1[0-2])',result['period']):raise ApprovalError('结算月份请使用YYYY-MM','input')
    return result


def matches_period(header,period):
    return not period or any(str(header.get(key,''))[:7]==period for key in ('settleMonth','settleStartDate','settleEndDate'))


def current_version():
    from platform_auth_control import version
    return version('lanorange')


class ApprovalManager:
    def __init__(self,path=None,factory=OfficialApprovalClient,version=current_version):
        self.path=Path(path or ROOT);self.path.parent.mkdir(parents=True,exist_ok=True)
        self.factory=factory;self.version=version;self.lock=threading.RLock();self.workers={}
        with self.connection() as db:
            db.executescript('''PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS previews(id TEXT PRIMARY KEY,scope TEXT NOT NULL,actor TEXT NOT NULL,session_version TEXT NOT NULL,created REAL NOT NULL,expires REAL NOT NULL,body TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS batches(id TEXT PRIMARY KEY,scope TEXT NOT NULL,actor TEXT NOT NULL,actor_label TEXT NOT NULL,session_version TEXT NOT NULL,request_id TEXT NOT NULL,preview_id TEXT NOT NULL,status TEXT NOT NULL,created REAL NOT NULL,finished REAL,stop INTEGER NOT NULL DEFAULT 0,UNIQUE(scope,request_id));
                CREATE TABLE IF NOT EXISTS items(batch_id TEXT NOT NULL,position INTEGER NOT NULL,task_id TEXT NOT NULL,status TEXT NOT NULL,message TEXT NOT NULL,snapshot TEXT NOT NULL,submitted REAL,finished REAL,PRIMARY KEY(batch_id,position));
                CREATE TABLE IF NOT EXISTS claims(actor TEXT NOT NULL,task_id TEXT NOT NULL,batch_id TEXT NOT NULL,status TEXT NOT NULL,PRIMARY KEY(actor,task_id));''')
            # The durable submitting marker precedes the only official write.
            db.execute("UPDATE items SET status='uncertain',message='服务曾中断，需读取官方记录核实；不会自动重发' WHERE status='submitting'")
            db.execute("UPDATE claims SET status='uncertain' WHERE status='submitting'")
            db.execute("UPDATE items SET status='not_sent',message='服务中断，此条尚未提交' WHERE status='pending'")
            db.execute("UPDATE claims SET status='not_sent' WHERE status='pending'")
            db.execute("UPDATE batches SET status='interrupted',finished=? WHERE status IN ('queued','running','stopping')",(time.time(),))

    @contextmanager
    def connection(self):
        db=sqlite3.connect(self.path,timeout=10)
        try:
            db.row_factory=sqlite3.Row;db.execute('PRAGMA busy_timeout=10000')
            with db:yield db
        finally:db.close()

    def active(self):
        with self.connection() as db:return bool(db.execute("SELECT 1 FROM batches WHERE status IN ('queued','running','stopping') LIMIT 1").fetchone())

    def blocked(self,actor,task_id):
        with self.connection() as db:row=db.execute('SELECT status FROM claims WHERE actor=? AND task_id=?',(actor,task_id)).fetchone()
        return bool(row and row['status'] in BLOCKED)

    def pending(self,query,page=1,page_size=20):
        query=filters(query)
        if type(page) is not int or page<1 or page_size not in (20,50,100):raise ApprovalError('页码或每页条数无效','input')
        version=self.version()
        with self.factory() as api:
            rows=api.pending(query);headers={}
            if query['period']:
                for row in rows:headers[str(row['businessId'])]=api.header(row['businessId'])
                rows=[r for r in rows if matches_period(headers[str(r['businessId'])],query['period'])]
            total=len(rows);selected=rows[(page-1)*page_size:page*page_size];result=[]
            for row in selected:
                header=headers.get(str(row['businessId'])) or api.header(row['businessId'])
                task=public_task(row,header,api.actor)
                if self.blocked(api.actor,task['id']):task['reason']='此节点已有提交或待核实记录，请先查看批次结果'
                result.append(task)
            if version!=self.version():raise ApprovalError('蓝橙账号已切换，请重新读取待办','changed')
            return {'rows':result,'total':total,'page':page,'page_size':page_size,'actor_label':api.actor_label,'session_version':version,'max_selected':MAX_SELECTED}

    def detail(self,task_id,version):
        if version!=self.version():raise ApprovalError('蓝橙账号已切换，请重新读取待办','changed')
        with self.factory() as api:
            row=next((r for r in api.pending() if str(r['id'])==task_id),None)
            if not row:raise ApprovalError('此流程已不在本人待办中，请刷新','changed')
            value=api.snapshot(row)
            if version!=self.version():raise ApprovalError('蓝橙账号已切换，请重新读取待办','changed')
            return {'task':value['task'],'price':value['price']}

    def preview(self,scope,payload):
        if not isinstance(payload,dict) or set(payload)-{'selected','filters','session_version'}:raise ApprovalError('预览请求无效','input')
        query=filters(payload.get('filters',{}));selected=payload.get('selected');version=payload.get('session_version')
        if not isinstance(selected,list) or not 1<=len(selected)<=MAX_SELECTED:raise ApprovalError(f'请选择1至{MAX_SELECTED}条流程','input')
        if any(not isinstance(r,dict) or set(r)!={'id','revision'} or not isinstance(r.get('revision'),str) or not re.fullmatch(r'[a-f0-9]{64}',r['revision']) for r in selected):raise ApprovalError('所选流程版本无效，请重新勾选','input')
        keys=[identifier(r.get('id')) for r in selected]
        if len(set(keys))!=len(keys):raise ApprovalError('流程不能重复选择','input')
        if not isinstance(version,str) or version!=self.version():raise ApprovalError('蓝橙账号已切换，请重新读取待办','changed')
        with self.factory() as api:
            own={str(r['id']):r for r in api.pending(query)};items=[];rider_count=0
            for choice,key in zip(selected,keys):
                row=own.get(key)
                try:
                    if not row:raise ApprovalError('此流程已不在当前筛选范围的本人待办中','changed')
                    if self.blocked(api.actor,key):raise ApprovalError('已有提交或待核实记录，不能重复提交','changed')
                    from lanorange_approval_client import task_revision
                    if choice['revision']!=task_revision(row):raise ApprovalError('勾选后流程内容已变化，请重新读取','changed')
                    snapshot=api.snapshot(row)
                    if not matches_period({'settleMonth':snapshot['task']['settle_month'],'settleStartDate':snapshot['task']['period_start'],'settleEndDate':snapshot['task']['period_end']},query['period']):raise ApprovalError('结算周期已变化，请重新读取','changed')
                    rider_count+=len(snapshot['price']['rows'])
                    if rider_count>20000:raise ApprovalError('本批价格明细过多，请减少勾选数量','input')
                    items.append({'eligible':True,'snapshot':snapshot})
                except ApprovalError as error:
                    if error.category in ('login','unavailable','permission','input'):raise
                    task=public_task(row,actor=api.actor) if row else {'id':key,'business_id':'','businessCode':key}
                    items.append({'eligible':False,'reason':str(error),'snapshot':{'task':task}})
            if version!=self.version():raise ApprovalError('蓝橙账号已切换，请重新预览','changed')
            key=uuid.uuid4().hex;now=time.time();body={'filters':query,'items':items,'actor_label':api.actor_label}
            with self.lock,self.connection() as db:db.execute('INSERT INTO previews VALUES (?,?,?,?,?,?,?)',(key,scope,api.actor,version,now,now+1800,json.dumps(body,ensure_ascii=False)))
        return self.get_preview(scope,key)

    def get_preview(self,scope,key):
        with self.connection() as db:row=db.execute('SELECT * FROM previews WHERE id=? AND scope=?',(key,scope)).fetchone()
        if not row:raise ApprovalError('预览不存在或不属于当前工作空间','missing')
        body=json.loads(row['body'])
        return {'id':row['id'],'expires_at':row['expires'],'actor_label':body['actor_label'],'filters':body['filters'],'opinion':'同意','eligible_count':sum(i['eligible'] for i in body['items']),'items':[{'eligible':i['eligible'],'reason':i.get('reason',''),'task':i['snapshot']['task'],'price':i['snapshot'].get('price')} for i in body['items']]}

    def start(self,scope,payload,*,background=True):
        if not isinstance(payload,dict) or set(payload)!={'preview_id','request_id','confirm'} or payload.get('confirm') is not True:raise ApprovalError('请预览本批明细后点击同意提交','input')
        request_id=payload['request_id'];key=payload['preview_id']
        if not isinstance(request_id,str) or not re.fullmatch(r'[A-Za-z0-9_-]{8,128}',request_id):raise ApprovalError('缺少有效提交标识','input')
        with self.lock,self.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            old=db.execute('SELECT id,preview_id FROM batches WHERE scope=? AND request_id=?',(scope,request_id)).fetchone()
            if old:
                if old['preview_id']!=key:raise ApprovalError('同一提交标识不能用于不同预览','changed')
                batch_id=old['id']
            else:
                if db.execute("SELECT 1 FROM batches WHERE status IN ('queued','running','stopping') LIMIT 1").fetchone():raise ApprovalError('已有价格审批批次执行中，请完成后再提交','busy')
                row=db.execute('SELECT * FROM previews WHERE id=? AND scope=?',(key,scope)).fetchone()
                if not row or row['expires']<time.time():raise ApprovalError('预览已过期，请重新预览','changed')
                if row['session_version']!=self.version():raise ApprovalError('蓝橙账号已切换，请重新预览','changed')
                body=json.loads(row['body'])
                if not any(i['eligible'] for i in body['items']):raise ApprovalError('本批没有可提交的流程','input')
                batch_id=uuid.uuid4().hex
                db.execute('INSERT INTO batches(id,scope,actor,actor_label,session_version,request_id,preview_id,status,created) VALUES (?,?,?,?,?,?,?,?,?)',(batch_id,scope,row['actor'],body['actor_label'],row['session_version'],request_id,key,'queued',time.time()))
                for position,item in enumerate(body['items']):
                    task_id=item['snapshot']['task']['id'];state='pending' if item['eligible'] else 'not_sent'
                    if item['eligible']:
                        claim=db.execute('SELECT status FROM claims WHERE actor=? AND task_id=?',(row['actor'],task_id)).fetchone()
                        if claim and claim['status'] in BLOCKED:raise ApprovalError('所选节点已有提交记录，请重新预览','changed')
                        db.execute('INSERT OR REPLACE INTO claims VALUES (?,?,?,?)',(row['actor'],task_id,batch_id,'pending'))
                    db.execute('INSERT INTO items(batch_id,position,task_id,status,message,snapshot) VALUES (?,?,?,?,?,?)',(batch_id,position,task_id,state,item.get('reason','等待提交'),json.dumps(item['snapshot'],ensure_ascii=False)))
        if not old and background:
            worker=threading.Thread(target=self.run,args=(batch_id,),daemon=True,name='lanorange-price-approval')
            with self.lock:self.workers[batch_id]=worker
            worker.start()
        return self.batch(scope,batch_id)

    def _item(self,batch_id,position,state,message):
        with self.lock,self.connection() as db:
            db.execute('UPDATE items SET status=?,message=?,finished=? WHERE batch_id=? AND position=?',(state,message,time.time(),batch_id,position))
            db.execute('UPDATE claims SET status=? WHERE batch_id=? AND task_id=(SELECT task_id FROM items WHERE batch_id=? AND position=?)',(state,batch_id,batch_id,position))

    def _stop(self,batch_id):
        with self.connection() as db:return bool(db.execute('SELECT stop FROM batches WHERE id=?',(batch_id,)).fetchone()['stop'])

    def run(self,batch_id):
        from parttime_source import COLLECTION_LOCK
        from platform_auth_control import operation
        acquired=False;reason='批次已结束，后续条目未提交'
        try:
            acquired=COLLECTION_LOCK.acquire(blocking=False)
            if not acquired:raise ApprovalError('当前资料采集正在运行，本批尚未提交，请稍后重新预览','busy')
            with operation('lanorange'),self.factory() as api:
                with self.connection() as db:
                    batch=dict(db.execute('SELECT * FROM batches WHERE id=?',(batch_id,)).fetchone());items=db.execute("SELECT * FROM items WHERE batch_id=? AND status='pending' ORDER BY position",(batch_id,)).fetchall()
                    db.execute("UPDATE batches SET status='running' WHERE id=?",(batch_id,))
                if api.actor!=batch['actor']:raise ApprovalError('蓝橙账号已变化，本批未继续提交','changed')
                for item in items:
                    if self._stop(batch_id):reason='已停止后续审批，此条未提交';break
                    if batch['session_version']!=self.version():reason='蓝橙会话已变化，此条未提交；请重新登录并预览';break
                    snapshot=json.loads(item['snapshot']);posted=False
                    try:
                        row=next((r for r in api.pending() if str(r['id'])==item['task_id']),None)
                        if not row:raise ApprovalError('此流程已不在本人待办中，未重复提交','changed')
                        current=api.snapshot(row)
                        if current['fingerprint']!=snapshot['fingerprint']:raise ApprovalError('预览后节点、价格或抄送发生变化，请重新预览','changed')
                        if self._stop(batch_id) or batch['session_version']!=self.version():reason='批次已停止或会话变化，此条未提交';break
                        # Commit this state before entering the network write.
                        with self.lock,self.connection() as db:
                            db.execute("UPDATE items SET status='submitting',message='正在等待官方确认',submitted=? WHERE batch_id=? AND position=?",(time.time(),batch_id,item['position']))
                            db.execute("UPDATE claims SET status='submitting' WHERE actor=? AND task_id=?",(api.actor,item['task_id']))
                        posted=True;api.complete(snapshot['payload'])
                        # Official acknowledgement plus a fresh own-task/history check.
                        confirmed=False
                        for attempt in range(2):
                            if api.reconcile(snapshot):confirmed=True;break
                            if not any(str(r['id'])==item['task_id'] and not eligible(r,api.actor) for r in api.pending()):confirmed=True;break
                            if attempt==0:time.sleep(.4)
                        if not confirmed:raise SubmissionUncertain('官方已接收，当前节点结果仍待核实；不会重发','uncertain')
                        self._item(batch_id,item['position'],'success','官方确认已同意本人当前节点')
                    except SubmissionUncertain as error:
                        self._item(batch_id,item['position'],'uncertain',str(error));reason='前一条结果待核实，已暂停后续提交';break
                    except ApprovalError as error:
                        if posted and error.category not in ('login','rejected'):
                            self._item(batch_id,item['position'],'uncertain','提交后的状态查询未完成，请核实；不会重发');reason='提交结果待核实，已暂停后续提交';break
                        self._item(batch_id,item['position'],'failed' if posted else 'changed',str(error))
                        if error.category in ('login','unavailable','permission'):
                            reason='蓝橙连接或权限未确认，后续条目未提交';break
                    except Exception:
                        self._item(batch_id,item['position'],'uncertain' if posted else 'not_sent','提交结果待核实，不会自动重发' if posted else '本条检查未完成，尚未提交');reason='本批已暂停，后续条目未提交';break
                    time.sleep(.25)
        except Exception as error:
            reason=str(error) if isinstance(error,ApprovalError) else '本批启动检查未完成，未继续提交'
        finally:
            with self.lock,self.connection() as db:
                db.execute("UPDATE items SET status='uncertain',message='提交处理中断，需核实官方记录；不会重发' WHERE batch_id=? AND status='submitting'",(batch_id,))
                db.execute("UPDATE claims SET status='uncertain' WHERE batch_id=? AND status='submitting'",(batch_id,))
                db.execute("UPDATE items SET status='not_sent',message=?,finished=? WHERE batch_id=? AND status='pending'",(reason,time.time(),batch_id))
                db.execute("UPDATE claims SET status='not_sent' WHERE batch_id=? AND status='pending'",(batch_id,))
                rows=db.execute('SELECT status FROM items WHERE batch_id=?',(batch_id,)).fetchall();states=[r['status'] for r in rows]
                state='needs_review' if 'uncertain' in states else 'completed' if states and all(s=='success' for s in states) else 'partial'
                db.execute('UPDATE batches SET status=?,finished=? WHERE id=?',(state,time.time(),batch_id))
            if acquired:COLLECTION_LOCK.release()
            with self.lock:self.workers.pop(batch_id,None)
            if self.path.resolve()==ROOT.resolve():
                try:
                    from delivery_store import approval_delivery
                    with self.connection() as db:owner=db.execute('SELECT scope FROM batches WHERE id=?',(batch_id,)).fetchone()['scope']
                    approval_delivery(self,owner,batch_id)
                except Exception:
                    import logging
                    logging.getLogger(__name__).warning('审批回执目录发布未完成，领取时重试；审批记录已保留')

    def batch(self,scope,key):
        with self.connection() as db:
            row=db.execute('SELECT * FROM batches WHERE id=? AND scope=?',(key,scope)).fetchone()
            if not row:raise ApprovalError('审批批次不存在或不属于当前工作空间','missing')
            items=db.execute('SELECT * FROM items WHERE batch_id=? ORDER BY position',(key,)).fetchall()
        result={k:row[k] for k in ('id','actor_label','request_id','preview_id','status','created','finished','stop')};result['counts']={};result['items']=[]
        for item in items:
            state=item['status'];result['counts'][state]=result['counts'].get(state,0)+1
            task=json.loads(item['snapshot'])['task'];result['items'].append({'task':task,'status':state,'status_label':LABELS.get(state,state),'message':item['message'],'submitted':item['submitted'],'finished':item['finished']})
        return result

    def batches(self,scope):
        with self.connection() as db:keys=[r['id'] for r in db.execute('SELECT id FROM batches WHERE scope=? ORDER BY created DESC LIMIT 30',(scope,))]
        return [self.batch(scope,key) for key in keys]

    def by_request(self,scope,request_id):
        with self.connection() as db:row=db.execute('SELECT id FROM batches WHERE scope=? AND request_id=?',(scope,request_id)).fetchone()
        if not row:raise ApprovalError('尚未找到此提交标识对应的批次，可用原提交标识再次提交','missing')
        return self.batch(scope,row['id'])

    def stop(self,scope,key):
        self.batch(scope,key)
        with self.lock,self.connection() as db:db.execute("UPDATE batches SET stop=1,status='stopping' WHERE id=? AND scope=? AND status IN ('queued','running')",(key,scope))
        return self.batch(scope,key)

    def recheck(self,scope,key):
        batch=self.batch(scope,key)
        if batch['status'] in ACTIVE:raise ApprovalError('本批仍在执行，请稍后核实','busy')
        with self.connection() as db:
            original=db.execute('SELECT actor FROM batches WHERE id=?',(key,)).fetchone()
            items=db.execute("SELECT * FROM items WHERE batch_id=? AND status='uncertain'",(key,)).fetchall()
        with self.factory() as api:
            if api.actor!=original['actor']:raise ApprovalError('请登录原审批账号后核实结果','changed')
            for item in items:
                if api.reconcile(json.loads(item['snapshot'])):self._item(key,item['position'],'success','已从官方记录核实本人当前节点的同意结果，未重复提交')
        with self.connection() as db:
            states=[r['status'] for r in db.execute('SELECT status FROM items WHERE batch_id=?',(key,))]
            db.execute('UPDATE batches SET status=? WHERE id=?',('needs_review' if 'uncertain' in states else 'completed' if all(s=='success' for s in states) else 'partial',key))
        if self.path.resolve()==ROOT.resolve():
            try:
                from delivery_store import approval_delivery
                approval_delivery(self,scope,key)
            except Exception:
                import logging
                logging.getLogger(__name__).warning('已保存核实结果，回执目录将在领取时重新发布')
        return self.batch(scope,key)

    def export(self,scope,key):
        batch=self.batch(scope,key);stream=io.StringIO();writer=csv.writer(stream)
        writer.writerow(['批次','业务编号','城市','站点','结算开始','结算结束','节点','结果','说明'])
        def cell(value):
            text='' if value is None else str(value)
            return "'"+text if text.lstrip().startswith(('=','+','-','@','\t','\r')) or re.fullmatch(r'\d{15,}',text) else text
        for row in batch['items']:
            task=row['task'];writer.writerow([cell(v) for v in (key,task.get('businessCode') or task['id'],task.get('cityName'),task.get('siteName'),task.get('period_start'),task.get('period_end'),task.get('nodeName'),row['status_label'],row['message'])])
        return ('\ufeff'+stream.getvalue()).encode('utf8')


def get_manager():
    global _manager
    with _manager_lock:
        if _manager is None:_manager=ApprovalManager()
        return _manager


def has_active():
    if _manager is not None:return _manager.active()
    return get_manager().active() if ROOT.exists() else False


def shutdown():
    if _manager is None:return
    with _manager.lock,_manager.connection() as db:
        db.execute("UPDATE batches SET stop=1 WHERE status IN ('queued','running','stopping')")
        workers=list(_manager.workers.values())
    deadline=time.monotonic()+2
    for worker in workers:worker.join(max(0,deadline-time.monotonic()))


def call(fn):
    try:return fn()
    except ApprovalError as error:
        raise HTTPException({'input':400,'missing':404,'login':401,'permission':403,'changed':409,'busy':409}.get(error.category,503),str(error)) from None


def scope(request):
    require_account(request)
    return workspace_owner(request)


@router.get('/pending')
def pending(request:Request,city:str='',station:str='',period:str='',page:int=1,page_size:int=20):
    scope(request);return call(lambda:get_manager().pending({'city':city,'station':station,'period':period},page,page_size))


@router.get('/pending-scope')
def pending_scope(request:Request):
    scope(request)
    def read():
        manager=get_manager();version=manager.version()
        with manager.factory() as api:
            rows=[];headers={}
            for item in api.pending():
                if eligible(item,api.actor) or manager.blocked(api.actor,str(item['id'])):continue
                key=str(item['businessId'])
                if key not in headers:headers[key]=api.header(key)
                rows.append(public_task(item,headers[key],api.actor))
            if version!=manager.version():raise ApprovalError('蓝橙账号已变化，请重新读取待办','changed')
            return {'rows':rows,'total':len(rows),'actor_label':api.actor_label,'session_version':version,'max_selected':MAX_SELECTED}
    return call(read)


@router.get('/filter-options')
def filter_options(request:Request,refresh:bool=False):
    from lanorange_price_options import options
    owner=scope(request);return call(lambda:options(owner,refresh))


@router.get('/activity')
def activity(request:Request):
    scope(request);return {'active':has_active()}


@router.get('/pending/{task_id}')
def detail(task_id:str,request:Request,session_version:str=''):
    scope(request);return call(lambda:get_manager().detail(identifier(task_id),session_version))


@router.post('/previews')
def preview(payload:dict,request:Request):
    owner=scope(request)
    from auth_preflight import ensure_ready
    ensure_ready({'lanorange'})
    return call(lambda:get_manager().preview(owner,payload))


@router.get('/previews/{key}')
def get_preview(key:str,request:Request):
    owner=scope(request);return call(lambda:get_manager().get_preview(owner,key))


@router.post('/batches')
def start(payload:dict,request:Request):
    owner=scope(request)
    from auth_preflight import ensure_ready
    ensure_ready({'lanorange'})
    return call(lambda:get_manager().start(owner,payload))


@router.get('/batches')
def batches(request:Request):
    owner=scope(request);return {'batches':call(lambda:get_manager().batches(owner))}


@router.get('/batches/by-request/{request_id}')
def by_request(request_id:str,request:Request):
    owner=scope(request);return call(lambda:get_manager().by_request(owner,request_id))


@router.get('/batches/{key}')
def batch(key:str,request:Request):
    owner=scope(request);return call(lambda:get_manager().batch(owner,key))


@router.post('/batches/{key}/stop')
def stop(key:str,payload:dict,request:Request):
    owner=scope(request)
    if set(payload)!={'confirm'} or payload.get('confirm') is not True:raise HTTPException(400,'停止请求无效')
    return call(lambda:get_manager().stop(owner,key))


@router.post('/batches/{key}/recheck')
def recheck(key:str,payload:dict,request:Request):
    owner=scope(request)
    if payload!={}:raise HTTPException(400,'核实请求无效')
    from auth_preflight import ensure_ready
    ensure_ready({'lanorange'})
    return call(lambda:get_manager().recheck(owner,key))


@router.get('/batches/{key}/result.csv')
def export(key:str,request:Request):
    owner=scope(request)
    from delivery_store import approval_delivery
    from fastapi.responses import FileResponse
    path=call(lambda:approval_delivery(get_manager(),owner,key))
    return FileResponse(path,filename=path.name,media_type='text/csv; charset=utf-8',headers={'Cache-Control':'no-store'})
