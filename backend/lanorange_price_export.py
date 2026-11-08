"""Read-only latest-version daily-price collection and durable Excel exports."""
from concurrent.futures import ThreadPoolExecutor
from collections import deque
from datetime import date,timedelta
from decimal import Decimal,InvalidOperation
import hashlib,json,os
from pathlib import Path
import re,sqlite3,threading,time,uuid
from contextlib import contextmanager

from fastapi import APIRouter,HTTPException,Request
from fastapi.responses import FileResponse
from download_accounts import require_account
from download_routes import workspace_owner
from lanorange_approval_client import OfficialApprovalClient,ApprovalError,digest,identifier,MAX_RIDERS
from lanorange_approvals import current_version,call
from price_export_workbook import WorkbookStream

ROOT=Path(__file__).parent/'.local_downloads/lanorange_price_exports'
router=APIRouter(prefix='/api/fengshen-downloads/lanorange-prices')
_manager=None;_lock=threading.Lock()


def file_hash(path):
    digest=hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda:stream.read(1024*1024),b''):digest.update(chunk)
    return digest.hexdigest()


def query(value):
    if not isinstance(value,dict) or set(value)-{'month','city','station','date_from','date_to'}:raise ApprovalError('价格导出筛选格式无效','input')
    result={key:value.get(key,'').strip() if isinstance(value.get(key,''),str) else None for key in ('month','city','station','date_from','date_to')}
    if any(v is None or len(v)>80 for v in result.values()) or not re.fullmatch(r'\d{4}-(?:0[1-9]|1[0-2])',result['month'] or ''):raise ApprovalError('请选择有效的结算月份','input')
    try:
        for key in ('date_from','date_to'):
            if result[key]:date.fromisoformat(result[key])
        if result['date_from'] and result['date_to'] and result['date_from']>result['date_to']:raise ValueError()
    except ValueError:raise ApprovalError('导出日期范围无效','input') from None
    return result


def latest(versions):
    if not versions:raise ApprovalError('此业务单没有价格提审版本','unsupported')
    try:
        numbers=[Decimal(str(r['version'])) for r in versions]
        if any(not n.is_finite() for n in numbers):raise ValueError()
    except (KeyError,InvalidOperation,ValueError):raise ApprovalError('版本号不完整，不能确定最新版本','unsupported') from None
    best=[row for row,n in zip(versions,numbers) if n==max(numbers)]
    unique={identifier(r['id']):r for r in best}
    if len(unique)!=1:raise ApprovalError('同一最新版本存在多个批次，请在蓝橙核对','unsupported')
    return next(iter(unique.values()))


def dictionaries(api,name):
    data=api._get('system/dict/data/type/'+name).get('data')
    if not isinstance(data,list) or not data:raise ApprovalError('官方字典未返回，不能猜测状态或结算模式')
    return {str(row['dictValue']):str(row['dictLabel']) for row in data if isinstance(row,dict) and row.get('dictValue') is not None and row.get('dictLabel')}


def groups(api,filters):
    parents=api._pages('salary/riderPrice/list',{'settleMonth':filters['month'],'cityName':filters['city'],'siteName':filters['station']},10000)
    result={}
    for row in parents:
        if str(row.get('settleMonth',''))[:7]!=filters['month']:continue
        if filters['city'] and filters['city'] not in str(row.get('cityName','')):continue
        if filters['station'] and filters['station'] not in str(row.get('siteName','')):continue
        key=tuple(str(row.get(k,'')) for k in ('projectCode','cityId','siteId','riderType','settleType','settleStartDate','settleEndDate'))
        result.setdefault(key,[]).append(row)
    return sorted(result.values(),key=lambda group:(str(group[0].get('cityName')),str(group[0].get('siteName')),str(group[0].get('settleStartDate'))))


def read_station(factory,parents,filters,actor,version,version_fn,audit_labels,settle_labels,stopped):
    parent=parents[0];receipt={'business_id':','.join(str(r['id']) for r in parents),'city':parent.get('cityName',''),'station':parent.get('siteName',''),'period':str(parent.get('settleStartDate',''))+' 至 '+str(parent.get('settleEndDate','')),'version':'','status':'','row_count':0,'result':'未导出','message':''}
    try:
        if stopped() or version_fn()!=version:raise ApprovalError('已停止或蓝橙会话已变化，此站点未继续采集','changed')
        with factory() as api:
            if api.actor!=actor:raise ApprovalError('蓝橙账号发生变化，此站点未采集','changed')
            def versions():
                rows=[]
                for source in parents:
                    data=api._pages('salary/partPriceBatch/list',{'priceId':identifier(source['id'])},10000)
                    if any(str(r.get('priceId'))!=str(source['id']) for r in data):raise ApprovalError('版本数据所属业务单不一致')
                    rows.extend(data)
                return rows
            selected=latest(versions());receipt['version']=str(selected['version'])
            if str(selected.get('status')) not in audit_labels:raise ApprovalError('最新版本的状态不在官方字典中，不能确定是否符合范围')
            receipt['status']=audit_labels[str(selected['status'])]
            if receipt['status'] not in ('审批中','待审核'):receipt.update(result='已跳过',message='最新版本不属于审批中或待审核，未回退旧版');return receipt,None
            header=api.header(selected['id'])
            if str(header.get('status'))!=str(selected.get('status')) or str(header.get('version'))!=str(selected.get('version')):raise ApprovalError('采集中版本或状态发生变化，请重试该站点','changed')
            if str(header.get('priceId')) not in {str(r['id']) for r in parents}:raise ApprovalError('版本与业务单不匹配')
            source=next(r for r in parents if str(r['id'])==str(header['priceId']))
            if any(str(header.get(k,''))[:10]!=str(source.get(k,''))[:10] for k in ('settleStartDate','settleEndDate')):raise ApprovalError('版本结算周期与业务列表不一致，请重新读取该站点','changed')
            start=date.fromisoformat(str(header['settleStartDate'])[:10]);end=date.fromisoformat(str(header['settleEndDate'])[:10])
            if end<start or (end-start).days>62:raise ApprovalError('结算周期异常，请在蓝橙核对')
            days=[];current=start
            while current<=end:
                if (not filters['date_from'] or current.isoformat()>=filters['date_from']) and (not filters['date_to'] or current.isoformat()<=filters['date_to']):days.append(current)
                current+=timedelta(days=1)
            if len({day.day for day in days})!=len(days):raise ApprovalError('跨月价格字段重复，不能猜测日期对应关系')
            if not days:receipt.update(result='已跳过',message='结算周期与指定日期没有交集');return receipt,None
            records=api._pages('salary/partPriceBatchDetail/list',{'batchId':identifier(selected['id']),'delFlag':'1'},MAX_RIDERS)
            expected=header.get('riderNum')
            if expected is not None and (not str(expected).isdigit() or int(expected)!=len(records)):raise ApprovalError('官方骑手人数与完整明细数不一致，此站点未导出，请单独核对')
            for row in records:
                if str(row.get('batchId'))!=str(selected['id']):raise ApprovalError('骑手明细不属于当前版本')
                if type(row.get('idCard')) not in (str,int,type(None)):raise ApprovalError('身份证字段格式异常，不能恢复完整文本')
                for day in days:
                    key='day'+str(day.day)
                    if key not in row:raise ApprovalError('官方未返回完整的每日价格字段，未将缺列伪装为空值')
                    value=row[key]
                    if value is not None and value!='':
                        if isinstance(value,bool) or not Decimal(str(value)).is_finite():raise ApprovalError('价格不是有效数字，请核对该站点')
            again=api._pages('salary/partPriceBatchDetail/list',{'batchId':identifier(selected['id']),'delFlag':'1'},MAX_RIDERS)
            sort=lambda rows:sorted(rows,key=lambda r:str(r['id']))
            if digest(sort(records))!=digest(sort(again)) or digest(header)!=digest(api.header(selected['id'])) or digest(latest(versions()))!=digest(selected):raise ApprovalError('采集中价格或最新版本已变化，此站点未导出','changed')
            if stopped() or version_fn()!=version:raise ApprovalError('已停止或蓝橙会话已变化，此站点未导出','changed')
            mode=settle_labels.get(str(header.get('settleType')))
            if not mode:raise ApprovalError('官方结算模式无法识别，未使用猜测值')
            kept=[{key:row.get(key) for key in ['riderName','idCard',*['day'+str(d.day) for d in days]]} for row in records]
            kept.sort(key=lambda r:(str(r.get('riderName','')),str(r.get('idCard',''))))
            receipt.update(result='已导出',row_count=len(kept)*len(days),message='')
            return receipt,{'header':header,'rows':kept,'days':days,'mode':mode}
    except Exception as error:
        receipt.update(result='失败',message=str(error) if isinstance(error,ApprovalError) else '该站点资料读取或格式校验失败，请单独重试');return receipt,None


def long_rows(snapshot):
    header=snapshot['header']
    for row in snapshot['rows']:
        for day in snapshot['days']:
            value=row['day'+str(day.day)];price=None if value is None or value=='' else Decimal(str(value))
            yield [snapshot['mode'],day,str(header.get('cityName') or ''),str(header.get('areaName') or ''),str(header.get('siteName') or ''),str(row.get('riderName') or ''),'' if row.get('idCard') is None else str(row['idCard']),price]


class PriceExports:
    def __init__(self,root=None,factory=OfficialApprovalClient,version_fn=current_version):
        self.root=Path(root or ROOT);self.root.mkdir(parents=True,exist_ok=True);self.factory=factory;self.version_fn=version_fn;self.lock=threading.RLock();self.workers={}
        with self.db() as db:
            db.execute('CREATE TABLE IF NOT EXISTS exports(id TEXT PRIMARY KEY,scope TEXT,request_id TEXT,query TEXT,status TEXT,created REAL,finished REAL,message TEXT,completed INTEGER DEFAULT 0,total INTEGER DEFAULT 0,rows INTEGER DEFAULT 0,receipts TEXT DEFAULT "[]",actor TEXT,sha256 TEXT,bytes INTEGER,stop INTEGER DEFAULT 0,UNIQUE(scope,request_id))')
            db.execute("UPDATE exports SET status='interrupted',message='服务中断，未自动重新采集' WHERE status IN ('queued','running','stopping')")
    @contextmanager
    def db(self):
        connection=sqlite3.connect(self.root/'exports.sqlite3',timeout=10);connection.row_factory=sqlite3.Row
        try:
            with connection:yield connection
        finally:connection.close()
    def active(self):
        with self.db() as db:return bool(db.execute("SELECT 1 FROM exports WHERE status IN ('queued','running','stopping') LIMIT 1").fetchone())
    def start(self,scope,payload,background=True):
        if not isinstance(payload,dict) or set(payload)!={'query','request_id'} or not isinstance(payload['request_id'],str) or not re.fullmatch(r'[A-Za-z0-9_-]{8,128}',payload['request_id']):raise ApprovalError('价格导出请求无效','input')
        filters=query(payload['query'])
        with self.lock,self.db() as db:
            db.execute('BEGIN IMMEDIATE');old=db.execute('SELECT * FROM exports WHERE scope=? AND request_id=?',(scope,payload['request_id'])).fetchone()
            if old:
                if json.loads(old['query'])!=filters:raise ApprovalError('提交标识与筛选条件不一致','changed')
                return self.get(scope,old['id'])
            if self.active():raise ApprovalError('已有每日价格导出在执行，请完成后再创建','busy')
            key=uuid.uuid4().hex;db.execute('INSERT INTO exports(id,scope,request_id,query,status,created,message) VALUES(?,?,?,?,?,?,?)',(key,scope,payload['request_id'],json.dumps(filters,ensure_ascii=False),'queued',time.time(),'等待采集'))
        if background:
            thread=threading.Thread(target=self.run,args=(key,),daemon=True,name='lanorange-price-export');self.workers[key]=thread;thread.start()
        return self.get(scope,key)
    def update(self,key,**fields):
        with self.lock,self.db() as db:db.execute('UPDATE exports SET '+','.join(name+'=?' for name in fields)+' WHERE id=?',(*fields.values(),key))
    def stopped(self,key):
        with self.db() as db:return bool(db.execute('SELECT stop FROM exports WHERE id=?',(key,)).fetchone()['stop'])
    def run(self,key):
        from parttime_source import COLLECTION_LOCK
        from platform_auth_control import operation
        acquired=False;directory=self.root/key;directory.mkdir(exist_ok=True);partial=directory/'result.xlsx.part';receipts=[]
        try:
            acquired=COLLECTION_LOCK.acquire(blocking=False)
            if not acquired:raise ApprovalError('当前采集或审批正在执行，本次未开始；请稍后重试','busy')
            with self.db() as db:row=dict(db.execute('SELECT * FROM exports WHERE id=?',(key,)).fetchone())
            filters=json.loads(row['query']);version=self.version_fn()
            with operation('lanorange'),self.factory() as api:
                actor=api.actor;status=dictionaries(api,'audit_status');settle=dictionaries(api,'settle_type');work=groups(api,filters)
                self.update(key,status='running',actor=actor,total=len(work),message='正在读取最新版本和每日价格')
                stop=lambda:self.stopped(key)
                with WorkbookStream(partial,json.dumps({'蓝橙账号':api.actor_label,'筛选':filters},ensure_ascii=False)) as book,ThreadPoolExecutor(max_workers=3,thread_name_prefix='price-read') as pool:
                    waiting=deque();source=iter(work)
                    def submit_one():
                        item=next(source,None)
                        if item is not None:waiting.append(pool.submit(read_station,self.factory,item,filters,actor,version,self.version_fn,status,settle,stop))
                    for _ in range(3):submit_one()
                    while waiting:
                        receipt,snapshot=waiting.popleft().result();receipts.append(receipt)
                        if snapshot:
                            for values in long_rows(snapshot):book.append(values)
                        self.update(key,completed=len(receipts),rows=book.count,receipts=json.dumps(receipts,ensure_ascii=False),message=f'已处理{len(receipts)}/{len(work)}个站点周期')
                        if not stop():submit_one()
                    book.finish(receipts)
                if stop():self.update(key,status='cancelled',finished=time.time(),message='已停止，未发布不完整导出文件');partial.unlink(missing_ok=True);return
                result=directory/'result.xlsx';os.replace(partial,result)
                failed=sum(r['result']=='失败' for r in receipts);self.update(key,status='partial' if failed else 'completed',finished=time.time(),message=f'导出完成，{failed}个站点失败' if failed else '导出完成；0价格和空值均保留',sha256=file_hash(result),bytes=result.stat().st_size)
                if self.root.resolve()==ROOT.resolve():
                    try:self.result(row['scope'],key)
                    except Exception:self.update(key,message='结果已生成，目录发布未完成；领取时可重试，原资料保留')
        except Exception as error:
            self.update(key,status='failed',finished=time.time(),message=str(error) if isinstance(error,ApprovalError) else '导出未完成，请检查连接或模板；原资料未修改');partial.unlink(missing_ok=True)
        finally:
            if acquired:COLLECTION_LOCK.release()
            self.workers.pop(key,None)
    def get(self,scope,key):
        with self.db() as db:row=db.execute('SELECT * FROM exports WHERE id=? AND scope=?',(key,scope)).fetchone()
        if not row:raise ApprovalError('导出任务不存在或不属于当前空间','missing')
        value={k:row[k] for k in ('id','request_id','status','created','finished','message','completed','total','rows','sha256','bytes','stop')};value['query']=json.loads(row['query']);value['receipts']=json.loads(row['receipts']);return value
    def history(self,scope):
        with self.db() as db:keys=[r['id'] for r in db.execute('SELECT id FROM exports WHERE scope=? ORDER BY created DESC LIMIT 20',(scope,))]
        return [self.get(scope,k) for k in keys]
    def result(self,scope,key):
        value=self.get(scope,key);path=(self.root/key/'result.xlsx').resolve()
        if not path.is_relative_to(self.root.resolve()):raise ApprovalError('导出路径无效','changed')
        if self.root.resolve() == ROOT.resolve():
            from delivery_store import project_store
            import datetime as dt
            store=project_store();published=store.location('price-export:'+key,'result')
            if published is None and not path.is_file():path=store.relocated(path) or path
            if published is None and path.is_file() and value['status'] in ('completed','partial'):
                store.publish('price-export:'+key,dt.datetime.fromtimestamp(value['created'],dt.timezone.utc),'蓝橙_每日价格',
                    [dict(run_id='price-export:'+key,id='result',path=str(path),name='蓝橙_每日价格.xlsx',dataset='每日价格',bytes=value['bytes'],sha256=value['sha256'])])
                published=store.location('price-export:'+key,'result')
            if published is not None:path=published
        if value['status'] not in ('completed','partial') or not path.is_file() or path.stat().st_size!=value['bytes'] or file_hash(path)!=value['sha256']:raise ApprovalError('导出文件尚未就绪或校验不通过','changed')
        return path


def manager():
    global _manager
    with _lock:
        if _manager is None:_manager=PriceExports()
        return _manager
def has_active():return _manager.active() if _manager is not None else manager().active() if (ROOT/'exports.sqlite3').exists() else False
def shutdown():
    if _manager is not None:
        with _manager.db() as db:db.execute("UPDATE exports SET stop=1 WHERE status IN ('queued','running','stopping')")
def owner(request):require_account(request);return workspace_owner(request)


@router.post('/exports')
def start(payload:dict,request:Request):
    scope=owner(request)
    from auth_preflight import ensure_ready
    ensure_ready({'lanorange'})
    return call(lambda:manager().start(scope,payload))
@router.get('/activity')
def activity(request:Request):
    owner(request);return {'active':has_active()}
@router.get('/exports')
def history(request:Request):
    scope=owner(request);return {'exports':call(lambda:manager().history(scope))}
@router.get('/exports/{key}')
def detail(key:str,request:Request):
    scope=owner(request);return call(lambda:manager().get(scope,key))
@router.get('/exports/{key}/result.xlsx')
def result(key:str,request:Request):
    scope=owner(request);path=call(lambda:manager().result(scope,key));return FileResponse(path,filename=path.name,media_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',headers={'Cache-Control':'no-store'})
@router.post('/exports/{key}/stop')
def stop(key:str,payload:dict,request:Request):
    scope=owner(request);call(lambda:manager().get(scope,key))
    if payload!={}:raise HTTPException(400,'停止请求无效')
    with manager().db() as db:db.execute("UPDATE exports SET stop=1,status='stopping' WHERE id=? AND status IN ('queued','running')",(key,))
    return manager().get(scope,key)
