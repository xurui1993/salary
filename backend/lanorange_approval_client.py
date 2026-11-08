"""The official rider-price workflow contract. No generic write/proxy API."""
from datetime import date, timedelta
import hashlib
import json
import re

import requests

from binding_source_auth import client, identity, SourceAuthenticationRequired

FLOW = 'salary-rider-price'
FORM = '/workflow/salaryRiderPriceBatchEdit/index'
ORIGIN = 'https://madouren.cdevelopment.cn/prod-api/'
MAX_TASKS = 10000
MAX_RIDERS = 10000


class ApprovalError(Exception):
    def __init__(self, message, category='unavailable'):
        super().__init__(message)
        self.category = category


class SubmissionUncertain(ApprovalError):
    pass


def identifier(value):
    if type(value) not in (str, int) or not re.fullmatch(r'[A-Za-z0-9_\-]{1,128}', str(value)):
        raise ApprovalError('官方流程标识不完整，不能批量处理', 'unsupported')
    return str(value)


def ids(value):
    if value is None:return set()
    if isinstance(value, list):return {str(item) for item in value if type(item) in (str,int)}
    return {part for part in re.split(r'[,\s]+', str(value)) if part}


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def task_revision(row):
    return digest({key:row.get(key) for key in ('id','definitionId','instanceId','businessId','nodeCode','nodeType','flowCode','formPath','flowStatus','updateTime','assigneeIds','processedBy')})


def eligible(row, actor):
    if row.get('flowCode') != FLOW:return '不是骑手价格提审'
    if row.get('flowStatus') != 'waiting':return '当前节点已不在待审核状态'
    if str(actor) not in ids(row.get('assigneeIds')):return '当前账号不在该节点的明确办理人中'
    if row.get('formPath') != FORM:return '官方价格表单已变化，暂需在蓝橙处理'
    return ''


def public_task(row, header=None, actor=''):
    header=header or {}
    result={key:row.get(key) for key in ('businessCode','businessTitle','cityName','siteName','nodeName','createByName','createTime','flowStatus')}
    result.update(id=identifier(row['id']),business_id=identifier(row['businessId']),revision=task_revision(row),reason=eligible(row,actor),period_start=header.get('settleStartDate',''),period_end=header.get('settleEndDate',''),settle_month=header.get('settleMonth',''),rider_count=header.get('riderNum'))
    return result


def price_view(header, rows):
    try:
        start=date.fromisoformat(str(header['settleStartDate'])[:10]);end=date.fromisoformat(str(header['settleEndDate'])[:10])
        if end<start or (end-start).days>62:raise ValueError()
    except (ValueError, KeyError):raise ApprovalError('结算日期不完整，无法展示每日价格', 'unsupported') from None
    columns=[{'key':'oldStatus','label':'标签（平台值）'}, {'key':'riderName','label':'骑手姓名'}, {'key':'rider_id','label':'骑手ID'}, {'key':'lastPrice','label':'上周期单价'}, {'key':'remark','label':'备注'}]
    current=start
    while current<=end:
        columns.append({'key':f'day{current.day}','label':current.isoformat()});current+=timedelta(days=1)
    # Official columns use day-of-month, so cross-month repeats are ambiguous.
    if len({c['key'] for c in columns})!=len(columns):raise ApprovalError('跨月价格字段重复，需在蓝橙核对', 'unsupported')
    columns.extend([{'key':'refereeName','label':'推荐人'}, {'key':'partPrice','label':'推荐单价'}])
    visible=[]
    for source in rows:
        row={c['key']:source.get(c['key']) for c in columns}
        row['rider_id']=str(source.get('fsRiderId') or source.get('riderId') or '')
        row['oldStatus']='' if source.get('oldStatus') is None else str(source['oldStatus'])
        visible.append(row)
    return {'columns':columns,'rows':visible,'remark':header.get('remark') or '', 'version':header.get('version'),'version_change':header.get('versionChange') or ''}


class OfficialApprovalClient:
    def __enter__(self):
        self.session=None
        try:
            from binding_source_auth import AUTH
            status=AUTH.status('lanorange')
            if status.get('busy') or status.get('state') in ('starting','waiting_login','refreshing'):raise ApprovalError('蓝橙登录正在进行，请登录完成后再处理价格业务','busy')
            self.session=client('lanorange');who=identity('lanorange',self.session,timeout=(5,15))
            user=who.get('user',{});self.actor=identifier(user.get('userId'))
            self.actor_label=str(user.get('nickName') or user.get('userName') or self.actor)[:80]
            return self
        except Exception as error:
            if self.session is not None:self.session.close()
            if isinstance(error,SourceAuthenticationRequired):raise ApprovalError('请先登录蓝橙，再读取本人待办', 'login') from None
            if isinstance(error,ApprovalError):raise
            raise ApprovalError('蓝橙身份读取失败，请稍后重试；未提交审批') from None

    def __exit__(self,*args):self.session.close()

    def _get(self,path,params=None):
        try:
            response=self.session.get(ORIGIN+path,params=params,timeout=(5,20),allow_redirects=False)
            if response.status_code==401:raise ApprovalError('蓝橙登录已失效，请重新登录', 'login')
            if response.status_code!=200 or len(response.content)>8*1024*1024:raise ApprovalError('蓝橙查询暂不可用；未提交审批')
            data=response.json()
            if not isinstance(data,dict):raise ValueError()
            if str(data.get('code'))=='401':raise ApprovalError('蓝橙登录已失效，请重新登录', 'login')
            if str(data.get('code'))!='200':raise ApprovalError('蓝橙未允许读取此资料，请核对当前账号权限', 'permission')
            return data
        except ApprovalError:raise
        except Exception:raise ApprovalError('蓝橙查询未完成，请稍后重试；未提交审批') from None

    def _pages(self,path,params,limit):
        result=[];seen=set()
        for page in range(1,1+limit//100+1):
            data=self._get(path,{**params,'pageNum':page,'pageSize':100});rows=data.get('rows');total=data.get('total')
            if not isinstance(rows,list) or type(total) is not int or total<0 or total>limit:raise ApprovalError('蓝橙资料数量超出单次处理范围，请缩小筛选范围', 'unsupported')
            for row in rows:
                if not isinstance(row,dict):raise ApprovalError('蓝橙资料结构异常')
                key=identifier(row.get('id'))
                if key in seen:raise ApprovalError('蓝橙分页内容发生变化，请重新读取待办')
                seen.add(key);result.append(row)
            if len(result)>=total:return result
            if not rows:raise ApprovalError('蓝橙分页未完整返回，请重新读取')
        raise ApprovalError('蓝橙分页未完整返回')

    def pending(self,filters=None):
        filters=filters or {}
        params={'flowCode':FLOW}
        for field,key in (('city','cityName'),('station','siteName')):
            if filters.get(field):params[key]=filters[field]
        return [row for row in self._pages('workflow/task/pageByTaskWait',params,MAX_TASKS) if row.get('flowCode')==FLOW]

    def header(self,business_id):
        data=self._get('salary/partPriceBatch/'+identifier(business_id)).get('data')
        if not isinstance(data,dict) or str(data.get('id'))!=str(business_id):raise ApprovalError('业务单与流程不匹配', 'unsupported')
        return data

    def history(self,business_id):
        data=self._get('workflow/instance/flowHisTaskList/'+identifier(business_id)).get('data')
        if not isinstance(data,dict) or not isinstance(data.get('list'),list):raise ApprovalError('官方审批记录未完整返回')
        return data

    def snapshot(self,row):
        reason=eligible(row,self.actor)
        if reason:raise ApprovalError(reason,'changed')
        task=self._get('workflow/task/getTask/'+identifier(row['id'])).get('data')
        if not isinstance(task,dict):raise ApprovalError('官方任务详情不完整')
        for key in ('id','businessId','instanceId','nodeCode','flowCode','formPath'):
            if str(task.get(key))!=str(row.get(key)):raise ApprovalError('官方当前节点已变化，请重新预览', 'changed')
        if task.get('flowStatus')!='waiting' or task.get('applyNode') is not False:raise ApprovalError('当前不是可批量同意的审核节点', 'changed')
        buttons=task.get('buttonList')
        if not isinstance(buttons,list):raise ApprovalError('官方节点按钮配置不完整', 'unsupported')
        if any(c.get('code')=='pop' and c.get('show') for c in buttons):raise ApprovalError('此节点需手动选择下一步审批人，请在蓝橙处理', 'manual')
        header=self.header(row['businessId'])
        if header.get('progressStatus')!='waiting':raise ApprovalError('价格提审已不在审核中', 'changed')
        rows=self._pages('salary/partPriceBatchDetail/list',{'delFlag':'1','batchId':identifier(row['businessId'])},MAX_RIDERS)
        if not rows:raise ApprovalError('价格明细为空，请在蓝橙核对', 'manual')
        if any(str(r.get('batchId'))!=str(row['businessId']) for r in rows):raise ApprovalError('价格明细所属业务单不一致', 'unsupported')
        copies=task.get('copyList')
        if not isinstance(copies,list):raise ApprovalError('官方默认抄送配置不完整', 'unsupported')
        copy_list=[{'userId':identifier(r.get('userId')),'userName':str(r.get('userName') or r.get('nickName') or '')} for r in copies]
        payload={'taskId':identifier(row['id']),'message':'同意','assigneeMap':{},'variables':{},'messageType':['1'],'flowCopyList':copy_list}
        task_data={key:task.get(key) for key in ('id','businessId','instanceId','nodeCode','flowCode','flowStatus','applyNode','nodeRatio','buttonList','copyList','varList')}
        material={'task':task_data,'row_revision':task_revision(row),'header':header,'riders':sorted(rows,key=lambda r:str(r['id']))}
        history=self.history(row['businessId'])
        if str(history.get('instanceId'))!=str(row.get('instanceId')):raise ApprovalError('审批记录与当前流程实例不一致', 'changed')
        for record in history['list']:
            same_task=str(record.get('taskId') or record.get('id'))==str(row['id'])
            if same_task and record.get('nodeCode')==row['nodeCode'] and ids(record.get('approver'))=={self.actor} and record.get('skipType')=='PASS' and record.get('flowStatus')=='pass':raise ApprovalError('官方记录确认本人已同意此节点，不能重复提交','changed')
        return {'task':public_task(row,header,self.actor),'fingerprint':digest(material),'payload':payload,'node_code':row['nodeCode'],'instance_id':row['instanceId'],'price':price_view(header,rows),'history_before':[digest(r) for r in history['list']]}

    def complete(self,payload):
        # Exactly one official write. Requests' default adapter has no retries.
        try:
            response=self.session.post(ORIGIN+'workflow/task/completeTask',json=payload,timeout=(5,25),allow_redirects=False)
            if response.status_code==401:raise ApprovalError('蓝橙登录失效，此条未获接受', 'login')
            if response.status_code not in (200,400,403) or len(response.content)>1024*1024:raise ValueError()
            data=response.json()
            if not isinstance(data,dict):raise ValueError()
            code=str(data.get('code'))
            if code in ('400','401','403'):
                raise ApprovalError('官方拒绝此次提交，请核对登录或节点权限', 'login' if code=='401' else 'rejected')
            if response.status_code!=200 or code!='200':raise ValueError()
            return {'accepted':True,'official_code':code}
        except ApprovalError:raise
        except Exception:raise SubmissionUncertain('提交结果待核实，系统不会自动重发此审批', 'uncertain') from None

    def reconcile(self,snapshot):
        task=snapshot['task'];pending=self.pending()
        own=next((row for row in pending if str(row.get('id'))==task['id']),None)
        history=self.history(task['business_id'])
        if str(history.get('instanceId'))!=str(snapshot['instance_id']):return False
        before=set(snapshot['history_before'])
        for row in history['list']:
            if digest(row) in before:continue
            if str(row.get('instanceId'))!=str(snapshot['instance_id']) or row.get('nodeCode')!=snapshot['node_code']:continue
            if row.get('taskId') is not None and str(row['taskId'])!=task['id']:continue
            if ids(row.get('approver'))!={self.actor}:continue
            if row.get('skipType')=='PASS' and row.get('flowStatus')=='pass' and row.get('message')=='同意':return True
        return False
