"""Batch-scoped, content-checked reads and best-effort payroll diagnostics."""
from collections import OrderedDict
from contextlib import contextmanager
from contextvars import ContextVar
from functools import wraps
import hashlib,json,math,os,threading,time
from pathlib import Path

from generation_performance import Profile
from workbook_policy import compression

_current=ContextVar('payroll_calculation',default=None)
_slots=threading.BoundedSemaphore(1)
_plan_lock=threading.Lock()
_plans=OrderedDict()


def digest(path):
    with Path(path).open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()


def cached_plan(path,options,loader):
    path=Path(path).resolve();checksum=digest(path)
    # Metadata only; no rider names, application rows or workbook objects.
    key=(str(path.parent),path.name,checksum,repr(options))
    now=time.monotonic()
    with _plan_lock:
        cached=_plans.get(key)
        if cached is not None and now-cached[0]<300:
            _plans.move_to_end(key);return cached[1]
    value=loader()
    if digest(path)!=checksum:
        from parttime_source import SourceError
        raise SourceError('模板在预检期间发生变化，请重新上传')
    with _plan_lock:
        _plans[key]=(now,value);_plans.move_to_end(key)
        while len(_plans)>128:_plans.popitem(last=False)
    return value


class PayrollSession:
    def __init__(self,directory,batch_id='',on_stage=None,verified_inputs=None,max_bytes=64*1024*1024):
        self.directory=Path(directory);self.batch_id=batch_id;self.on_stage=on_stage
        self.profile=Profile('payroll',directory);self.started=time.perf_counter()
        self.stages={};self.frames=OrderedDict();self.bytes=0;self.limit=max_bytes
        self.books=OrderedDict();self.native={};self.hits=0;self.misses=0
        self.expected={str(Path(path).resolve()):value for path,value in (verified_inputs or {}).items()}
        self.wait_seconds=0;self.status='running';self.phase=None;self.phase_started=self.started

    @contextmanager
    def stage(self,name,label=None):
        started=time.perf_counter()
        if self.on_stage is not None and label:
            try:self.on_stage(label)
            except Exception:pass
        try:yield
        finally:self.stages[name]=self.stages.get(name,0)+time.perf_counter()-started

    def fingerprint(self,path):
        checksum=digest(path);expected=self.expected.get(str(Path(path).resolve()))
        if expected is not None and checksum!=expected:
            raise ValueError('核算资料与已确认快照不一致，已停止本次核算')
        return checksum

    def native_ok(self,path,checksum):
        if checksum in self.native:return self.native[checksum]
        from order_xlsx import read_xlsx_tables,FastXlsxUnsupported
        def check(rows,*_):
            for row in rows:
                for value in row:
                    if isinstance(value,(int,float)) and not isinstance(value,bool) and (not math.isfinite(value) or abs(value)>=10**15):
                        raise FastXlsxUnsupported('large numeric values require the original pandas reader')
            return True
        try:
            with self.stage('native_guard_seconds'):
                read_xlsx_tables(path,set(),check)
            value=True
        except FastXlsxUnsupported:value=False
        self.native[checksum]=value;return value

    def remember(self,key,value,retain):
        if not retain:return value
        size=int(value.memory_usage(index=True,deep=True).sum())
        if size>self.limit:return value
        while self.frames and self.bytes+size>self.limit:
            _,(_,removed)=self.frames.popitem(last=False);self.bytes-=removed
        self.frames[key]=(value.copy(deep=True),size);self.bytes+=size
        return value

    def book(self,path,checksum,engine):
        import pandas as pd
        key=(str(path.resolve()),checksum,engine)
        if key in self.books:return self.books[key]
        for old in self.books.values():old.close()
        self.books.clear()
        book=pd.ExcelFile(path,engine=engine);self.books[key]=book;return book

    def public(self):
        stages=dict(self.stages)
        if self.phase:stages['phase:'+self.phase]=stages.get('phase:'+self.phase,0)+time.perf_counter()-self.phase_started
        return {'version':1,'status':self.status,'elapsed_seconds':round(time.perf_counter()-self.started,6),
                'queue_seconds':round(self.wait_seconds,6),'sampled_process_peak_rss_bytes':self.profile.peak_rss,
                'stages':{key:round(value,6) for key,value in stages.items()},
                'source_cache':{'hits':self.hits,'misses':self.misses,'retained_bytes':self.bytes,'limit_bytes':self.limit}}

    def close(self):
        for book in self.books.values():book.close()
        self.books.clear();self.frames.clear();self.bytes=0


@contextmanager
def calculation_context(directory,batch_id='',on_stage=None,verified_inputs=None,max_bytes=64*1024*1024):
    previous=_current.get()
    if previous is not None:
        yield previous;return
    session=PayrollSession(directory,batch_id,on_stage,verified_inputs,max_bytes)
    session.profile.sampler.start();waiting=time.perf_counter()
    if on_stage:
        try:on_stage('等待核算资源')
        except Exception:pass
    _slots.acquire();session.wait_seconds=time.perf_counter()-waiting
    token=_current.set(session)
    try:
        with compression(6):yield session
    except BaseException:
        session.status='error';raise
    finally:
        if session.status=='running':session.status='success'
        report=session.public()
        session.profile.stopped.set();session.profile.sampler.join(timeout=1)
        try:
            session.close()
        except Exception:pass
        finally:
            _current.reset(token);_slots.release()
        try:
            from fengshen_bill import atomic_json
            session.directory.mkdir(parents=True,exist_ok=True)
            atomic_json(session.directory/'payroll_performance.json',report)
        except Exception:pass


def current_session():return _current.get()


@contextmanager
def timed(name,label=None):
    session=_current.get()
    if session is None:yield
    else:
        with session.stage(name,label):yield


def read_excel(io,*args,**kwargs):
    import pandas as pd
    session=_current.get()
    if session is None or args or not isinstance(io,(str,Path)):
        return pd.read_excel(io,*args,**kwargs)
    path=Path(io);checksum=session.fingerprint(path)
    supplied_engine=kwargs.get('engine');engine=supplied_engine or 'openpyxl'
    basic=set(kwargs)<= {'sheet_name','dtype','header','nrows','engine'}
    if any(key in kwargs for key in ('engine_kwargs','storage_options')):return pd.read_excel(io,**kwargs)
    if path.suffix.lower()=='.xlsx' and supplied_engine is None and basic and 'template' not in path.name.lower():
        if session.native_ok(path,checksum):engine='calamine'
    elif path.suffix.lower()!='.xlsx' and supplied_engine is None:engine=None
    if engine is None:return pd.read_excel(io,**kwargs)
    retain=any(word in path.name.lower() for word in ('template','价格','绑定','账单'))
    with session.stage('read_excel_seconds','读取核算资料：'+path.name):
        book=session.book(path,checksum,engine)
        options=dict(kwargs);options.pop('engine',None)
        sheet=options.pop('sheet_name',0)
        actual=book.sheet_names[sheet] if isinstance(sheet,int) else sheet
        key=(checksum,path.name,'excel',engine,str(actual),repr(sorted(options.items())))
        if key in session.frames:
            session.hits+=1;session.frames.move_to_end(key);return session.frames[key][0].copy(deep=True)
        session.misses+=1
        value=book.parse(sheet_name=actual,**options)
        if session.fingerprint(path)!=checksum:raise ValueError('核算资料在读取期间发生变化，已停止')
        if not isinstance(value,pd.DataFrame):return value
        value=session.remember(key,value,retain)
        if not retain:
            book.close();session.books.clear()
        return value


def read_csv(io,*args,**kwargs):
    import pandas as pd
    session=_current.get()
    if session is None or args or kwargs.get('chunksize') or kwargs.get('iterator') or not isinstance(io,(str,Path)):
        return pd.read_csv(io,*args,**kwargs)
    path=Path(io);checksum=session.fingerprint(path);key=(checksum,path.name,'csv',repr(sorted(kwargs.items())))
    with session.stage('read_csv_seconds','读取核算资料：'+path.name):
        if key in session.frames:
            session.hits+=1;session.frames.move_to_end(key);return session.frames[key][0].copy(deep=True)
        session.misses+=1;value=pd.read_csv(io,**kwargs)
        if session.fingerprint(path)!=checksum:raise ValueError('核算资料在读取期间发生变化，已停止')
        return session.remember(key,value,any(word in path.name for word in ('价格','绑定','账单')))


def append_frame_rows(sheet,frame,chunk_rows=10000):
    """Write bounded row chunks and calculate the same display widths in one pass."""
    import pandas as pd
    from openpyxl.utils import get_column_letter
    widths={};width_cache={}
    def measure(row):
        for column,value in enumerate(row,1):
            if value is None or widths.get(column,0)>=60:continue
            text=str(value)
            width=width_cache.get(text)
            if width is None:
                width=min(60,sum(2 if ord(char)>127 else 1 for char in text)+2)
                if len(width_cache)<4096:width_cache[text]=width
            widths[column]=max(widths.get(column,8),width)
    measure([cell.value for cell in sheet[1]])
    with timed('write_details_seconds','生成配送明细工作表'):
        for first in range(0,len(frame),chunk_rows):
            chunk=frame.iloc[first:first+chunk_rows].astype(object)
            chunk[pd.isna(chunk)]=None
            for row in chunk.itertuples(index=False,name=None):
                sheet.append(row);measure(row)
        for column,width in widths.items():sheet.column_dimensions[get_column_letter(column)].width=width


def phase(name,label):
    session=_current.get()
    if session is None:return
    now=time.perf_counter()
    if session.phase:
        key='phase:'+session.phase;session.stages[key]=session.stages.get(key,0)+now-session.phase_started
    session.phase=name;session.phase_started=now
    if session.on_stage:
        try:session.on_stage(label)
        except Exception:pass
