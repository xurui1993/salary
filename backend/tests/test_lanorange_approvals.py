import copy
import asyncio
import json
from pathlib import Path
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import FastAPI,HTTPException
import lanorange_approvals as jobs
from lanorange_approval_client import OfficialApprovalClient,ApprovalError,SubmissionUncertain,FLOW,FORM,task_revision,digest,price_view,eligible


def task(key='t1',**changes):
    return dict(id=key,businessId='b'+key,instanceId='i'+key,definitionId='definition',flowCode=FLOW,flowStatus='waiting',nodeCode='node1',nodeType=1,formPath=FORM,formCustom='N',assigneeIds='u1,u2',processedBy='',businessCode='210000000000000001',businessTitle='价格申请',cityName='测试城市',siteName='测试站点',nodeName='中间节点',createByName='合成申请人',createTime='2026-10-01',**changes)


class World:
    def __init__(self):
        self.tasks=[task('t1'),task('t2')];self.actor='u1';self.version='version1';self.done=set();self.mode='success';self.writes=[];self.reads=[];self.price='6.00';self.pop=False;self.copy=[{'userId':'copy1','nickName':'原默认抄送'}];self.after_write=None;self.network=False
    def client(self):return FakeClient(self)


class FakeClient(OfficialApprovalClient):
    def __init__(self,world):self.world=world
    def __enter__(self):self.actor=self.world.actor;self.actor_label='合成审批人';return self
    def __exit__(self,*args):pass
    def _get(self,path,params=None):
        w=self.world;w.reads.append(path)
        if w.network:raise ApprovalError('查询未完成')
        params=params or {}
        if path=='workflow/task/pageByTaskWait':
            assert params['flowCode']==FLOW
            rows=[r for r in w.tasks if r['id'] not in w.done and (not params.get('cityName') or params['cityName'] in r['cityName']) and (not params.get('siteName') or params['siteName'] in r['siteName'])]
            page,size=params['pageNum'],params['pageSize'];return {'code':200,'rows':copy.deepcopy(rows[(page-1)*size:page*size]),'total':len(rows)}
        if path.startswith('workflow/task/getTask/'):
            row=next(r for r in w.tasks if r['id']==path.rsplit('/',1)[-1]);return {'code':200,'data':{**copy.deepcopy(row),'applyNode':False,'buttonList':[{'code':'pop','show':w.pop},{'code':'copy','show':True}],'copyList':copy.deepcopy(w.copy),'varList':{}}}
        if path.startswith('salary/partPriceBatch/'):
            key=path.rsplit('/',1)[-1];return {'code':200,'data':{'id':key,'settleMonth':'2026-10','settleStartDate':'2026-10-01','settleEndDate':'2026-10-02','riderNum':1,'progressStatus':'waiting','version':1,'remark':'仅用于测试'}}
        if path=='salary/partPriceBatchDetail/list':
            return {'code':200,'total':1,'rows':[{'id':'r'+params['batchId'],'batchId':params['batchId'],'riderId':'rider-001','riderName':'合成骑手','idCard':'not-exposed','day1':w.price,'day2':'7.00','lastPrice':'5.00','oldStatus':'1'}]}
        if path.startswith('workflow/instance/flowHisTaskList/'):
            business=path.rsplit('/',1)[-1];row=next(r for r in w.tasks if r['businessId']==business);done=row['id'] in w.done
            history={'id':'h'+row['id'],'instanceId':row['instanceId'],'taskId':row['id'],'nodeCode':'node1','approver':w.actor if done else 'u1,u2','flowStatus':'pass' if done else 'waiting','skipType':'PASS' if done else None,'message':'同意' if done else None}
            return {'code':200,'data':{'instanceId':row['instanceId'],'list':[history]}}
        raise AssertionError(path)
    def complete(self,payload):
        w=self.world;w.writes.append(copy.deepcopy(payload))
        if w.mode=='rejected':raise ApprovalError('官方拒绝','rejected')
        if w.mode=='login':raise ApprovalError('登录失效','login')
        if w.mode=='timeout':raise SubmissionUncertain('结果待核实','uncertain')
        w.done.add(payload['taskId'])
        if w.after_write:w.after_write()
        if w.mode=='timeout_after_commit':raise SubmissionUncertain('结果待核实','uncertain')
        return {'accepted':True}


class ApprovalTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.path=Path(self.temp.name)/'approval.sqlite3';self.world=World();self.manager=jobs.ApprovalManager(self.path,self.world.client,lambda:self.world.version)
        self.sleep=patch.object(jobs.time,'sleep');self.sleep.start();self.addCleanup(self.sleep.stop)
    def preview(self,keys=('t1','t2')):
        return self.manager.preview('space1',{'selected':[{'id':r['id'],'revision':task_revision(r)} for r in self.world.tasks if r['id'] in keys],'filters':{},'session_version':self.world.version})
    def start(self,preview=None,request_id='request-0001'):
        preview=preview or self.preview();return self.manager.start('space1',{'preview_id':preview['id'],'request_id':request_id,'confirm':True},background=False)
    def test_pending_only_exposes_exact_flow_and_does_not_misread_processed_by_as_history(self):
        self.world.tasks=[task('own'),{**task('other'),'assigneeIds':'u9'},{**task('processed'),'processedBy':'u1'},{**task('wrong'),'flowCode':FLOW+'-other'}]
        value=self.manager.pending({});self.assertEqual(value['total'],3)
        self.assertFalse(value['rows'][0]['reason']);self.assertTrue(value['rows'][1]['reason']);self.assertFalse(value['rows'][2]['reason'])
    def test_cross_page_listing_is_complete_and_filters_are_preserved(self):
        self.world.tasks=[task(str(i)) for i in range(125)]
        value=self.manager.pending({'city':'测试','station':'站点','period':'2026-10'},6,20)
        self.assertEqual(value['total'],125);self.assertEqual(len(value['rows']),20);self.assertEqual(value['rows'][0]['id'],'100')
    def test_preview_is_readonly_and_contains_all_daily_prices_without_id_card(self):
        value=self.preview();self.assertEqual(value['eligible_count'],2);self.assertFalse(self.world.writes)
        self.assertEqual(value['items'][0]['price']['rows'][0]['day1'],'6.00');self.assertNotIn('not-exposed',str(value))
    def test_wrong_workflow_or_non_owner_cannot_be_approved(self):
        self.world.tasks[0]['flowCode']='other';self.world.tasks[1]['assigneeIds']='u9'
        preview=self.preview();self.assertEqual(preview['eligible_count'],0)
        with self.assertRaises(ApprovalError):self.start(preview)
        self.assertFalse(self.world.writes)
    def test_changed_selection_revision_is_not_silently_used(self):
        row=self.world.tasks[0];revision=task_revision(row);row['nodeCode']='new'
        preview=self.manager.preview('space1',{'selected':[{'id':'t1','revision':revision}],'filters':{},'session_version':'version1'})
        self.assertEqual(preview['eligible_count'],0)
    def test_actor_and_session_switch_block_before_any_write(self):
        batch=self.start();self.world.actor='u2';self.manager.run(batch['id']);self.assertFalse(self.world.writes)
        self.world.actor='u1';self.world.version='version2'
        with self.assertRaises(ApprovalError):self.manager.start('space1',{'preview_id':batch['preview_id'],'request_id':'different-request','confirm':True},background=False)
    def test_detail_rejects_arbitrary_task_or_stale_session(self):
        for key,version in [('not-own','version1'),('t1','old')]:
            with self.assertRaises(ApprovalError):self.manager.detail(key,version)
        self.assertFalse(self.world.writes)
    def test_start_requires_confirm_and_no_client_supplied_opinion_or_payload(self):
        preview=self.preview()
        for payload in [{'preview_id':preview['id'],'request_id':'request-0001','confirm':False},{'preview_id':preview['id'],'request_id':'request-0001','confirm':True,'message':'拒绝'}]:
            with self.assertRaises(ApprovalError):self.manager.start('space1',payload,background=False)
        self.assertFalse(self.world.writes)
    def test_success_sends_only_same_node_fixed_agree_and_preserves_official_defaults(self):
        batch=self.start();self.manager.run(batch['id']);result=self.manager.batch('space1',batch['id'])
        self.assertEqual(result['counts'],{'success':2});self.assertEqual([p['taskId'] for p in self.world.writes],['t1','t2'])
        for p in self.world.writes:
            self.assertEqual(p['message'],'同意');self.assertEqual(p['variables'],{});self.assertEqual(p['messageType'],['1']);self.assertEqual(p['flowCopyList'],[{'userId':'copy1','userName':'原默认抄送'}]);self.assertNotIn('fileId',p)
    def test_duplicate_request_returns_same_batch_and_changed_preview_conflicts(self):
        preview=self.preview();first=self.start(preview);second=self.start(preview);self.assertEqual(first['id'],second['id'])
        with self.assertRaises(ApprovalError):self.start(self.preview())
        self.manager.run(first['id']);self.assertEqual(len(self.world.writes),2)
    def test_same_task_cannot_be_claimed_from_another_tab_or_batch(self):
        first=self.start();self.manager.run(first['id']);self.world.done.clear()
        preview=self.preview();self.assertEqual(preview['eligible_count'],0);self.assertEqual(len(self.world.writes),2)
    def test_price_or_default_copy_change_after_preview_is_not_submitted(self):
        batch=self.start();self.world.price='9.00';self.manager.run(batch['id']);self.assertFalse(self.world.writes);self.assertEqual(self.manager.batch('space1',batch['id'])['counts'],{'changed':2})
    def test_popup_assignee_selection_is_manual_not_invented(self):
        self.world.pop=True;value=self.preview();self.assertEqual(value['eligible_count'],0);self.assertIn('手动选择',value['items'][0]['reason'])
    def test_expired_preview_requires_new_review(self):
        value=self.preview()
        with self.manager.connection() as db:db.execute('UPDATE previews SET expires=0')
        with self.assertRaises(ApprovalError):self.start(value)
    def test_timeout_never_reposts_and_stops_following_items(self):
        batch=self.start();self.world.mode='timeout';self.manager.run(batch['id']);value=self.manager.batch('space1',batch['id'])
        self.assertEqual(value['counts'],{'uncertain':1,'not_sent':1});self.assertEqual(len(self.world.writes),1)
        preview=self.preview(('t1',));self.assertEqual(preview['eligible_count'],0)
        self.manager.recheck('space1',batch['id']);self.assertEqual(len(self.world.writes),1);self.assertEqual(self.manager.batch('space1',batch['id'])['counts']['uncertain'],1)
    def test_lost_response_can_be_reconciled_from_actual_actor_node_history_without_write(self):
        batch=self.start();self.world.mode='timeout_after_commit';self.manager.run(batch['id'])
        value=self.manager.recheck('space1',batch['id']);self.assertEqual(value['counts'],{'success':1,'not_sent':1});self.assertEqual(len(self.world.writes),1)
    def test_readback_failure_after_ack_is_uncertain(self):
        batch=self.start();self.world.after_write=lambda:setattr(self.world,'network',True);self.manager.run(batch['id'])
        self.assertEqual(self.manager.batch('space1',batch['id'])['counts']['uncertain'],1);self.assertEqual(len(self.world.writes),1)
    def test_explicit_rejection_continues_other_items_without_retries(self):
        batch=self.start();self.world.mode='rejected';self.manager.run(batch['id'])
        self.assertEqual(self.manager.batch('space1',batch['id'])['counts'],{'failed':2});self.assertEqual(len(self.world.writes),2)
    def test_stop_before_start_sends_nothing(self):
        batch=self.start();self.manager.stop('space1',batch['id']);self.manager.run(batch['id']);self.assertFalse(self.world.writes)
    def test_restart_marks_inflight_unknown_and_does_not_resume_pending(self):
        batch=self.start()
        with self.manager.connection() as db:
            db.execute("UPDATE items SET status='submitting' WHERE task_id='t1'");db.execute("UPDATE claims SET status='submitting' WHERE task_id='t1'")
        restored=jobs.ApprovalManager(self.path,self.world.client,lambda:self.world.version)
        self.assertEqual(restored.batch('space1',batch['id'])['counts'],{'uncertain':1,'not_sent':1});self.assertFalse(self.world.writes)
    def test_workspace_cannot_read_or_export_another_preview_batch_or_request(self):
        preview=self.preview();batch=self.start(preview)
        for fn in [lambda:self.manager.get_preview('space2',preview['id']),lambda:self.manager.batch('space2',batch['id']),lambda:self.manager.export('space2',batch['id']),lambda:self.manager.by_request('space2','request-0001')]:
            with self.assertRaises(ApprovalError):fn()
    def test_result_csv_preserves_long_ids_and_escapes_formula_cells(self):
        self.world.tasks[0]['siteName']='=1+1';batch=self.start();text=self.manager.export('space1',batch['id']).decode('utf-8-sig')
        self.assertIn("'=1+1",text);self.assertIn("'210000000000000001",text)
    def test_unrelated_actor_history_is_not_claimed_as_my_approval(self):
        with self.world.client() as api:
            snapshot=api.snapshot(self.world.tasks[0]);self.world.done.add('t1')
            self.world.actor='u2'
            self.assertFalse(api.reconcile(snapshot))
    def test_filters_and_price_dates_are_validated(self):
        for value in [{'period':'2026-99'},{'city':['x']},{'taskId':'arbitrary'}]:
            with self.assertRaises(ApprovalError):jobs.filters(value)
        with self.assertRaises(ApprovalError):price_view({'settleStartDate':'2026-10-02','settleEndDate':'2026-10-01'},[])


class ASGIClient:
    def __init__(self,app):self.app=app
    def request(self,method,path,json=None,headers=None):
        messages=[];body=__import__('json').dumps(json).encode() if json is not None else b''
        scope={'type':'http','asgi':{'version':'3.0'},'http_version':'1.1','method':method,'scheme':'http','path':path,'raw_path':path.encode(),'root_path':'','query_string':b'','server':('localhost',80),'client':('127.0.0.1',12345),'headers':[(b'host',b'localhost'),(b'content-type',b'application/json')]+[(k.lower().encode(),v.encode()) for k,v in (headers or {}).items()]}
        async def receive():return {'type':'http.request','body':body,'more_body':False}
        async def send(message):messages.append(message)
        asyncio.run(self.app(scope,receive,send))
        raw=b''.join(m.get('body',b'') for m in messages);return SimpleNamespace(status_code=next(m['status'] for m in messages if m['type']=='http.response.start'),json=lambda:__import__('json').loads(raw))
    def get(self,path,**kwargs):return self.request('GET',path,**kwargs)
    def post(self,path,**kwargs):return self.request('POST',path,**kwargs)


class RouteTests(unittest.TestCase):
    preview=ApprovalTests.preview
    start=ApprovalTests.start
    def setUp(self):
        ApprovalTests.setUp(self);app=FastAPI();app.include_router(jobs.router);self.client=ASGIClient(app)
        patcher=patch.object(jobs,'get_manager',return_value=self.manager);patcher.start();self.addCleanup(patcher.stop)
        self.headers={'x-workspace-id':'space1','origin':'http://localhost'}
    def test_routes_enforce_same_origin_and_scope_before_any_write(self):
        preview=self.preview()
        response=self.client.post('/api/fengshen-downloads/lanorange-approvals/batches',json={'preview_id':preview['id'],'request_id':'request-0001','confirm':True},headers={'x-workspace-id':'space1','origin':'http://other.invalid'})
        self.assertEqual(response.status_code,403);self.assertFalse(self.world.writes)
        batch=self.start(preview)
        response=self.client.get('/api/fengshen-downloads/lanorange-approvals/batches/'+batch['id'],headers={'x-workspace-id':'space2'})
        self.assertEqual(response.status_code,404)
    def test_pending_route_returns_local_selection_metadata_without_mutation(self):
        response=self.client.get('/api/fengshen-downloads/lanorange-approvals/pending',headers=self.headers)
        self.assertEqual(response.status_code,200);self.assertEqual(response.json()['total'],2);self.assertFalse(self.world.writes)
    def test_auth_start_and_logout_guard_refuse_an_active_approval(self):
        from binding_source_auth import SourceAuth
        from platform_auth_control import idle_guard
        with patch.object(jobs,'has_active',return_value=True):
            with self.assertRaises(HTTPException):SourceAuth().start('lanorange')
            with self.assertRaises(HTTPException):
                with idle_guard():pass


class PendingScopeTests(unittest.TestCase):
    def test_scope_reads_only_own_actionable_tasks_and_no_write_or_rider_details(self):
        with tempfile.TemporaryDirectory() as temp:
            world=World();foreign=task('foreign');foreign['assigneeIds']='someone-else';world.tasks.append(foreign)
            manager=jobs.ApprovalManager(Path(temp)/'test.sqlite3',world.client,lambda:world.version)
            with patch.object(jobs,'scope',return_value='shared'),patch.object(jobs,'get_manager',return_value=manager):
                value=jobs.pending_scope(None)
            self.assertEqual(value['total'],2);self.assertEqual({r['id'] for r in value['rows']},{'t1','t2'})
            self.assertFalse(world.writes);self.assertFalse(any('Detail' in path or 'complete' in path for path in world.reads))


if __name__=='__main__':unittest.main()
