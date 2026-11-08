"""Official current-merchant invitation snapshots and resumable attendance segments."""
import codecs,csv,datetime as dt,hashlib,json,os,re,shutil,stat,unicodedata,zipfile
from pathlib import Path
from decimal import Decimal
from openpyxl import load_workbook
from fengshen_bill import BillCollectionError,atomic_json
from fengshen_http import HttpTransportError,TEAMS_URL
from fengshen_auth import dpapi
from fengshen_orders import secure_file_url,SHANGHAI
from tabular_export_workbook import TabularWorkbook
from fengshen_merchant_protocol import INVITATIONS,ATTENDANCE,KINDS,MERCHANT,INVITE_AUTH,INVITE_TEAMS,INVITE_QUERY,GRAY_URL,ATTENDANCE_EXPORT

# 邀请记录成品按平台全部字段展示，首列为城市；新人礼多项在单元格内逐行对齐。
HEADERS=['城市','活动ID','邀请人ID','邀请人','新人ID','新人姓名','新人手机号','邀请状态','邀请时间','入职时间','新人入职状态','邀请团队ID','邀请站点','入职团队ID','入职站点','新人礼活动ID','新人礼实例ID','新人礼活动时间','新人礼达成状态']
INVITE_STATUS={1:'进行中',2:'有效邀请',3:'无效邀请'};ENTRY_STATUS={0:'未入职',1:'已入职'}
GIFT_STATUS={0:'任务冲单中',1:'任务审核中',2:'无效邀请',3:'',4:'无效邀请',5:'无效邀请',6:'无效邀请',7:'无效邀请',8:'任务审核中',9:'无效邀请',10:'任务已打款',11:'无效邀请',12:'任务已打款',13:'进行中',14:'无效邀请'}
MAX_BYTES=200*1024*1024
WIDTH_SAMPLE_ROWS=500
INVITATION_HEADER_FILL='F8CBAD'
# 出勤明细成品列宽：逐列复刻用户确认的标准附件（原文件含合并区间7-8与13-16）。
ATTENDANCE_WIDTHS=[10.5,22,19,16.125,11.125,7.375,8,8,11.375,8,9.625,6.375,12.25,12.25,12.25,12.25,11.375]


def canonical(value):return hashlib.sha256(json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':'),default=str).encode()).hexdigest()
def checksum(path):
    with Path(path).open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()
def number(value):
    if type(value) not in (str,int) or not re.fullmatch(r'\d{1,24}',str(value)):raise BillCollectionError('官方编号格式变化，未猜测范围')
    return str(value)
def load(path):
    path=Path(path)
    if path.is_symlink() or not path.is_file() or path.stat().st_size>8*1024*1024:raise BillCollectionError('分段回执不可用')
    return json.loads(path.read_text('utf8'))
def date_value(value):
    if isinstance(value,dt.datetime):return value.date()
    if isinstance(value,dt.date):return value
    if isinstance(value,(int,float)) and not isinstance(value,bool):
        if 20000<value<100000:return dt.date(1899,12,30)+dt.timedelta(days=int(value))
        return dt.datetime.fromtimestamp(value/1000 if value>100000000000 else value,SHANGHAI).date()
    match=re.match(r'^(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})',str(value or ''))
    if not match:raise BillCollectionError('官方日期无法识别，未猜测归属日期')
    return dt.date(*(int(p) for p in match.groups()))
def display_time(value):
    if value in (None,'',0):return ''
    if type(value) in (int,float) or isinstance(value,str) and value.isdigit():
        value=float(value);return dt.datetime.fromtimestamp(value/1000 if value>100000000000 else value,SHANGHAI).strftime('%Y-%m-%d %H:%M:%S')
    parsed=dt.datetime.fromisoformat(str(value).replace('Z','+00:00'))
    return (parsed.astimezone(SHANGHAI) if parsed.tzinfo else parsed).strftime('%Y-%m-%d %H:%M:%S')
def label(value,labels):
    if value in (None,''):return ''
    try:return labels[int(value)]
    except (ValueError,KeyError,TypeError):return '未识别状态（'+str(value)+'）'
def identifier(value):
    if value in (None,''):return ''
    if isinstance(value,bool) or not isinstance(value,(str,int)):raise BillCollectionError('邀请记录编号类型变化，未猜测展示')
    return str(value)
def display_width(value):
    width=0
    for line in str('' if value is None else value).split('\n'):
        width=max(width,sum(2 if unicodedata.east_asian_width(ch) in 'WF' else 1 for ch in line))
    return width
def invitation_widths(rows):
    widths=[display_width(header) for header in HEADERS]
    for row in rows:
        for index,value in enumerate(row):
            widths[index]=max(widths[index],display_width(value))
    return [min(60,max(10,width+2)) for width in widths]
def invitation_row(record, city=MERCHANT):
    gifts=record.get('itemVOList') or []
    if not isinstance(gifts,list) or any(not isinstance(g,dict) for g in gifts):raise BillCollectionError('新人礼列表结构变化')
    times=['至'.join([date_value(g['startDate']).isoformat(),date_value(g['endDate']).isoformat()]) if g.get('startDate') else '-' for g in gifts]
    statuses=[label(g.get('inviteStatus'),GIFT_STATUS) for g in gifts]
    mobile=record.get('inviteMobile')
    return [city,number(record['templateId']),identifier(record.get('invitingParticipantId')),
            record.get('invitingParticipantName'),identifier(record.get('invitedParticipantId')),
            record.get('invitedName'),'' if mobile in (None,'') else identifier(mobile),
            label(record.get('inviteStatus'),INVITE_STATUS),display_time(record.get('inviteDate')),
            display_time(record.get('entryDate')),label(record.get('entryStatus'),ENTRY_STATUS),
            identifier(record.get('teamId')),record.get('teamName'),identifier(record.get('entryTeamId')),
            record.get('entryTeamName') or '-',
            '\n'.join(identifier(g.get('activityId')) for g in gifts) if gifts else '-',
            '\n'.join(identifier(g.get('instanceId')) for g in gifts) if gifts else '-',
            '\n'.join(times) if times else '-','\n'.join(statuses) if statuses else '-']
def segments(start,end,gray_dates=(),days=7):
    first,last=dt.date.fromisoformat(start),dt.date.fromisoformat(end);breaks={date_value(d) for d in gray_dates};result=[]
    while first<=last:
        stop=min(last,first+dt.timedelta(days=days-1));next_break=min((d for d in breaks if first<d<=stop),default=None)
        if next_break:stop=next_break-dt.timedelta(days=1)
        result.append((first.isoformat(),stop.isoformat()));first=stop+dt.timedelta(days=1)
    return result
def receipt_line(scope,rows,result='已导出',message=''):
    period='全量记录（不按日期筛选）' if scope['kind']==INVITATIONS else scope.get('start','')+' 至 '+scope.get('end','')
    return {'business_id':scope['agency_id'],'city':scope.get('city',MERCHANT),'station':'全部可见站点','period':period,'version':'','status':'','row_count':rows,'result':result,'message':message}
def checked_file(path,proof):
    return path.is_file() and not path.is_symlink() and 0<path.stat().st_size<=MAX_BYTES and path.stat().st_size==proof.get('bytes') and checksum(path)==proof.get('sha256')
def source_key(city,kind):return kind if city==MERCHANT else city+'|'+kind
def source_directory(root,kind,city=MERCHANT):
    if kind not in KINDS:raise BillCollectionError('商家下载资料类型无效')
    from download_archive import archive_component
    return Path(root)/'merchant_sources'/kind if city==MERCHANT else Path(root)/'merchant_sources'/archive_component(city)/kind


def merchant_teams(payload,agency):
    rows=payload.get('result',{}).get('data')
    if not isinstance(rows,list) or any(not isinstance(row,dict) for row in rows):raise BillCollectionError('团队归属结构变化，未猜测全部范围')
    result={};seen=set()
    for row in rows:
        key=number(row.get('id'))
        if key in seen:raise BillCollectionError('团队编号重复')
        seen.add(key)
        if number(row.get('agencyId'))==agency:result[key]=str(row.get('team_name') or '')
    if not result:raise BillCollectionError('当前商家没有可核实的可见团队，未提交导出')
    return result


def recoverable_source(path,kind,start,end,city=MERCHANT):
    path=Path(path);scope=load(path/'scope.json')
    if scope.get('kind')!=kind or (kind==ATTENDANCE and (scope.get('start'),scope.get('end'))!=(start,end)):raise BillCollectionError('商家原始范围不符')
    if city!=MERCHANT and scope.get('city')!=city:raise BillCollectionError('原商家资料不属于所选城市，未复用其他城市分段')
    if kind==ATTENDANCE:
        plan=load(path/'plan.json')
        if plan.get('scope')!=scope or not isinstance(plan.get('teams'),dict) or not plan['teams'] or plan.get('segments')!=[list(v) for v in segments(start,end,plan.get('gray_dates',[]))]:raise BillCollectionError('分段计划与原始范围不符')
        for first,last in plan['segments']:
            folder=path/(first+'_'+last);file=folder/'source.bin';proof=folder/'download.json';sent=folder/'submission.json'
            expected={**scope,'start':first,'end':last,'teams':sorted(plan['teams'],key=int)}
            if proof.exists():
                metadata=load(proof)
                if metadata.get('scope')!=expected or not checked_file(file,metadata):raise BillCollectionError('已完成分段校验失败，未重新提交')
            elif sent.exists():
                receipt=load(sent)
                url_path=folder/'file-url.dpapi'
                if receipt.get('scope')!=expected or receipt.get('submission_state')!='submitted' or not url_path.is_file() or url_path.is_symlink() or url_path.stat().st_size>65536:raise BillCollectionError(f'{first}至{last}分段提交结果未知，不能重复导出')
    return path


def _source_tables(path,folder):
    path=Path(path)
    with path.open('rb') as stream:magic=stream.read(4)
    if magic==b'PK\x03\x04':
        with zipfile.ZipFile(path) as archive:
            if 'xl/workbook.xml' not in archive.namelist():
                entries=[v for v in archive.infolist() if not v.is_dir()]
                if not entries or len(entries)>1000 or sum(v.file_size for v in entries)>MAX_BYTES*3:raise BillCollectionError('出勤压缩包内容异常或过大')
                for index,entry in enumerate(entries):
                    if stat.S_ISLNK(entry.external_attr>>16) or entry.filename.replace('\\','/').startswith('/') or '..' in entry.filename.replace('\\','/').split('/') or ':' in entry.filename or Path(entry.filename).suffix.lower() not in ('.csv','.xlsx'):raise BillCollectionError('出勤压缩包包含未支持的条目')
                    target=folder/f'part-{index}';
                    with archive.open(entry) as source,target.open('wb') as output:shutil.copyfileobj(source,output)
                    yield from _source_tables(target,folder)
                return
        with path.open('rb') as stream:
            book=load_workbook(stream,read_only=True,data_only=False)
            try:
                for sheet in book:
                    sheet.reset_dimensions()
                    def rows():
                        for row in sheet:
                            if any(c.data_type=='f' for c in row):raise BillCollectionError('官方明细含公式，不能静默改写为缓存值')
                            yield [c.value for c in row]
                    yield rows()
            finally:book.close()
    else:
        with path.open('rb') as stream:sample=stream.read(65536)
        encoding=None
        for candidate in ('utf-8-sig','gb18030'):
            try:codecs.getincrementaldecoder(candidate)(errors='strict').decode(sample,final=False);encoding=candidate;break
            except UnicodeError:pass
        if not encoding:raise BillCollectionError('出勤文件编码无法识别')
        with path.open('r',encoding=encoding,newline='') as stream:yield csv.reader(stream)


_HOURS_PATTERN=re.compile(r'^\d{2}小时\d{2}分钟$')


def hours_value(value):
    text=str(value or '').strip()
    if not text:return None
    if not _HOURS_PATTERN.match(text):raise BillCollectionError(f'有效在线时长格式变化（{text[:20]}），未猜测小时值')
    hours,minutes=text.split('小时');minutes=minutes.replace('分钟','')
    return round(int(hours)+int(minutes)/60,2)


class MerchantCollector:
    def __init__(self,client,log=lambda value:None,crypt=dpapi):self.client=client;self.log=log;self.crypt=crypt
    def _check(self,scope):self.client.checkpoint();self.client.assert_city(scope['agency_id'])
    def collect(self,kind,raw,start,end,resume=None,*,city=MERCHANT,agency_id=None):
        if kind not in KINDS:raise BillCollectionError('商家资料类型无效')
        raw=Path(raw);raw.mkdir(parents=True,exist_ok=True)
        if resume:
            source=recoverable_source(resume,kind,start,end,city)
            if source.resolve()!=raw.resolve():
                files=list(source.rglob('*'))
                if len(files)>5000 or sum(p.stat().st_size for p in files if p.is_file())>MAX_BYTES*4 or any(p.is_symlink() for p in files):raise BillCollectionError('原分段缓存异常')
                shutil.copytree(source,raw,dirs_exist_ok=True)
        if city!=MERCHANT:
            target=number(agency_id);self.client.select_city(target)
        identity=self.client.identity();agency=number(identity['agencyId']);scope={'kind':kind,'agency_id':agency,'start':start,'end':end}
        if city!=MERCHANT:
            if agency!=target:raise BillCollectionError('当前风神商家与所选城市不一致，未提交导出')
            scope['city']=city
        if (raw/'scope.json').exists() and load(raw/'scope.json')!=scope:raise BillCollectionError('当前风神商家与原始分段范围不一致，未继续导出')
        atomic_json(raw/'scope.json',scope);self._check(scope)
        try:return self.invitations(raw,scope) if kind==INVITATIONS else self.attendance(raw,scope)
        except Exception as error:
            if kind==INVITATIONS or isinstance(error,HttpTransportError):raise
            receipts=list(raw.glob('*/submission.json'));state='not_submitted'
            for path in receipts:
                try:
                    if load(path).get('submission_state')!='submitted':state='unknown';break
                    state='submitted'
                except Exception:state='unknown';break
            message=str(error) if isinstance(error,BillCollectionError) else '出勤明细处理未完成，原分段已保留'
            raise HttpTransportError(message,'validating' if receipts else 'preparing',state) from None
    def invitations(self,raw,scope):
        self.client.request_json('GET',INVITE_AUTH)
        teams=self.client.request_json('GET',INVITE_TEAMS).get('data')
        if not isinstance(teams,list) or not teams:raise BillCollectionError('邀请页面未返回可见站点，未把未获取当成空数据')
        visible_ids=[number(t['id']) for t in teams]
        if len(set(visible_ids))!=len(visible_ids):raise BillCollectionError('邀请站点编号重复')
        current=merchant_teams(self.client.request_json('POST',TEAMS_URL,body={}),scope['agency_id'])
        ids=[key for key in visible_ids if key in current]
        if not ids:raise BillCollectionError('没有可核实属于当前商家的邀请站点，未扩大至其他商家')
        params={'activityType':26,'stationIds':json.dumps([int(v) for v in ids],separators=(',',':')),'pageSize':20}
        def page(n):
            data=self.client.request_json('GET',INVITE_QUERY,params={**params,'pageNum':n}).get('data')
            if not isinstance(data,dict) or type(data.get('totalItems')) is not int or not isinstance(data.get('value'),list) or not 0<=data['totalItems']<=1000000:raise BillCollectionError('邀请记录分页结构变化')
            return data
        first=page(1);total=first['totalItems'];count=0;pages=set();explicit=set();receipts=[];output=raw/'result.xlsx';temporary=raw/'result.xlsx.part'
        display_scope={'商家编号':scope['agency_id'],'站点范围':'全部可见站点','日期范围':'不按日期筛选'}
        city=scope.get('city',MERCHANT);book=None;sample=[]
        def open_book(rows):
            writer=TabularWorkbook(temporary,HEADERS,'邀请记录',json.dumps(display_scope,ensure_ascii=False),
                                   invitation_widths(rows),header_fill=INVITATION_HEADER_FILL)
            writer.__enter__();return writer
        def emit(row):
            nonlocal book,sample
            if book is None:
                sample.append(row)
                if len(sample)>=WIDTH_SAMPLE_ROWS:
                    book=open_book(sample)
                    for pending in sample:book.append(pending)
                    sample=[]
            else:book.append(row)
        try:
            for n in range(1,max(1,(total+19)//20)+1):
                self.client.checkpoint();data=first if n==1 else page(n);rows=data['value']
                if data['totalItems']!=total or len(rows)!=min(20,max(0,total-count)):raise BillCollectionError('邀请记录数量或分页发生变化，请重新读取')
                signature=canonical(rows)
                if rows and signature in pages:raise BillCollectionError('邀请接口重复返回同一页，未丢弃或重复统计')
                pages.add(signature)
                for record in rows:
                    if not isinstance(record,dict):raise BillCollectionError('邀请记录结构变化')
                    key=record.get('id',record.get('instanceId'))
                    if key is not None:
                        key=str(key)
                        if key in explicit:raise BillCollectionError('邀请记录跨页编号重复，未静默去重')
                        explicit.add(key)
                    emit(invitation_row(record,city));count+=1
                self.log(f'[下载] 邀请记录：已读取第{n}页，共{count}/{total}条')
            if canonical(page(1))!=canonical(first):raise BillCollectionError('采集期间邀请记录已变化，请重试全量读取')
            self._check(scope)
            if sorted(number(v['id']) for v in self.client.request_json('GET',INVITE_TEAMS)['data'])!=sorted(visible_ids) or merchant_teams(self.client.request_json('POST',TEAMS_URL,body={}),scope['agency_id'])!=current:raise BillCollectionError('采集期间站点权限或商家归属已变化')
            if book is None:
                book=open_book(sample)
                for pending in sample:book.append(pending)
                sample=[]
            receipts.append({**receipt_line(scope,count),'version':f'{max(1,(total+19)//20)}页','status':'邀请记录'});book.finish(receipts)
        finally:
            if book is not None:book.__exit__(None,None,None)
        os.replace(temporary,output);atomic_json(raw/'result.json',{'rows':count,'bytes':output.stat().st_size,'sha256':checksum(output),'scope':scope,'pages':max(1,(total+19)//20)})
        return output
    def attendance(self,raw,scope):
        teams=merchant_teams(self.client.request_json('POST',TEAMS_URL,body={}),scope['agency_id']);ids=sorted(teams,key=int)
        today=dt.datetime.now(SHANGHAI).date();gray=self.client.request_json('POST',GRAY_URL,body={'params':{'request':{'teamIds':[int(v) for v in ids],'startDate':today.isoformat()}}}).get('result',{}).get('data')
        if not isinstance(gray,list) or any(not isinstance(r,dict) or number(r.get('teamId')) not in teams for r in gray):raise BillCollectionError('时段切换日期信息未完整返回，未猜测分段')
        breaks=sorted({date_value(r['grayDate']).isoformat() for r in gray if r.get('grayDate') and scope['start']<date_value(r['grayDate']).isoformat()<=scope['end']})
        plan={'scope':scope,'teams':teams,'segments':segments(scope['start'],scope['end'],breaks),'gray_dates':breaks}
        if (raw/'plan.json').exists() and load(raw/'plan.json')!=json.loads(json.dumps(plan)):raise BillCollectionError('原始团队或时段规则变化，保留旧分段，请重新核对范围')
        atomic_json(raw/'plan.json',plan);sources=[];receipts=[]
        for index,(first,last) in enumerate(plan['segments'],1):
            self._check(scope);folder=raw/(first+'_'+last);folder.mkdir(exist_ok=True);path=folder/'source.bin';proof=folder/'download.json';sent=folder/'submission.json';url_path=folder/'file-url.dpapi'
            request={'teamIds':[int(v) for v in ids],'startDate':first,'endDate':last};part_scope={**scope,'start':first,'end':last,'teams':ids}
            if proof.exists():
                if not checked_file(path,load(proof)):raise HttpTransportError(f'{first}至{last}原分段文件校验失败，未重新导出','validating','submitted')
                self.log(f'[恢复] 出勤明细第{index}/{len(plan["segments"])}段复用已下载文件')
            else:
                if sent.exists():
                    old=load(sent)
                    if old.get('scope')!=part_scope or old.get('submission_state')!='submitted' or not url_path.exists():raise HttpTransportError(f'{first}至{last}分段提交结果未知，禁止重复提交','submitting','unknown')
                    url=self.crypt(url_path.read_bytes(),decrypt=True).decode('utf8')
                else:
                    self.log(f'[导出] 出勤明细第{index}/{len(plan["segments"])}段：{first}至{last}')
                    payload,_=self.client.submit_once(ATTENDANCE_EXPORT,{'params':{'request':request}},sent,part_scope)
                    data=payload.get('result',{}).get('data');url=secure_file_url(data.get('url') if isinstance(data,dict) else None)
                    encrypted=self.crypt(url.encode('utf8'));temporary=url_path.with_suffix('.part');temporary.write_bytes(encrypted);os.replace(temporary,url_path)
                if path.exists():raise HttpTransportError('原分段文件存在但无完整校验凭据，请核对缓存','validating','submitted')
                self.log(f'[下载] 领取出勤明细第{index}/{len(plan["segments"])}段')
                self.client.download(url,path)
                atomic_json(proof,{'bytes':path.stat().st_size,'sha256':checksum(path),'scope':part_scope})
            sources.append((path,first,last));self._check(scope)
        headers=None;book=None;temporary=raw/'result.xlsx.part';total=0
        try:
            for path,first,last in sources:
                folder=path.parent/'tables';folder.mkdir(exist_ok=True);part_count=0
                for rows in _source_tables(path,folder):
                    current=None
                    for _ in range(20):
                        row=next(rows,None)
                        if row is None:break
                        titles=[str(v or '').strip() for v in row]
                        date_index=next((i for i,h in enumerate(titles) if h.replace(' ','') in ('日期','出勤日期','考勤日期','统计日期','统计时间','排班日期','考核日期')),None)
                        if date_index is not None and len(titles)>2:current=titles;break
                    if current is None:raise BillCollectionError(f'{first}至{last}明细缺少可核实的日期表头，原文件已保留')
                    if headers is None:
                        hours_index=next((i for i,h in enumerate(current) if h=='有效在线时长'),None)
                        if hours_index is None:raise BillCollectionError('出勤明细缺少有效在线时长列，未添加小时值列，原文件已保留')
                        headers=current;book=TabularWorkbook(temporary,[*current,'有效在线时长'],'出勤明细',json.dumps(scope,ensure_ascii=False),ATTENDANCE_WIDTHS,numeric_columns=(len(current),),header_fill='FCE4D3',header_q_fill='FFFF00',row_height=None,default_row_height=16.5,show_gridlines=True,auto_filter=False,source_url='https://r.ele.me/pikipek/schedule.html?platform=fs&subtype=ub#/group/schedule/attendance-statistic');book.__enter__()
                    if current!=headers:raise BillCollectionError('分段表头不一致，未丢弃字段或强行合并')
                    for row in rows:
                        self.client.checkpoint();row=list(row)
                        if not any(v not in (None,'') for v in row):continue
                        if len(row)!=len(headers):raise BillCollectionError('出勤明细列数变化')
                        day=date_value(row[date_index]).isoformat()
                        if not first<=day<=last:raise BillCollectionError(f'{first}至{last}分段返回范围外日期，未合并')
                        book.append([*row,hours_value(row[hours_index])]);part_count+=1;total+=1
                receipts.append({**receipt_line({**scope,'start':first,'end':last},part_count),'version':f'{len(receipts)+1}/{len(sources)}','status':'骑手出勤明细'});self.log(f'[完成] 已合并{first}至{last}，{part_count}行')
            if book is None:raise BillCollectionError('出勤导出没有可读取的明细表头')
            self._check(scope);book.finish(receipts)
        finally:
            if book is not None:book.__exit__(None,None,None)
        output=raw/'result.xlsx';os.replace(temporary,output);atomic_json(raw/'result.json',{'rows':total,'segments':len(sources),'scope':scope,'bytes':output.stat().st_size,'sha256':checksum(output)})
        return output
