import asyncio
import copy
import json
from pathlib import Path
import tempfile
import threading
import time
from unittest import TestCase
from unittest.mock import patch
import uuid

from fastapi import HTTPException
from starlette.requests import Request

from parttime_source import SourceError
from payroll_queue import PayrollQueue, QueueStopped, identity, frozen_config


class QueueTests(TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(dir=Path(__file__).parent);self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.source=self.root/'uploads/shared/upload_fixture';self.source.mkdir(parents=True)
        self.queues=[]
        self.addCleanup(lambda:[q.shutdown() for q in self.queues])

    def template(self,name='深圳-template.xlsx',contents=b'original'):
        path=self.source/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(contents);return path

    def queue(self,runner=None,autostart=False):
        q=PayrollQueue(self.root,runner,autostart);self.queues.append(q);return q

    def enqueue(self,q,mode='fengshen',key='request_001',config=None):
        return q.enqueue('shared','download_shared',str(self.source),mode,config or {},key)

    def raw(self,q,key):
        with q.connection() as db:return q._find(db,'shared','download_shared',key)

    def wait(self,q,condition):
        deadline=time.monotonic()+5
        while time.monotonic()<deadline:
            values=q.list('shared','download_shared')
            if condition(values):return values
            threading.Event().wait(.01)
        self.fail('队列未在限定时间内完成')

    def test_multiple_templates_are_idempotent_and_freeze_config(self):
        self.template('深圳/template.xlsx');self.template('广州/template.xlsx')
        q=self.queue();config={'payrollExcludeSeparation':False,'theme':{'msg_start':['original']}}
        tasks=self.enqueue(q,config=config);config['theme']['msg_start'][0]='changed'
        self.assertEqual(len(tasks),2);self.assertNotEqual(tasks[0]['id'],tasks[1]['id'])
        self.assertEqual([t['id'] for t in tasks],[t['id'] for t in self.enqueue(q,config={'payrollExcludeSeparation':False,'theme':{'msg_start':['original']}})])
        for task in tasks:
            saved=self.raw(q,task['id']);self.assertIs(saved['config']['payrollExcludeSeparation'],False)
            self.assertEqual(saved['config']['theme']['msg_start'],['original'])
        with self.assertRaises(SourceError):self.enqueue(q,config={'payrollExcludeSeparation':True})

    def test_queue_scope_never_reads_other_workspaces_or_accounts(self):
        self.template();q=self.queue();key=self.enqueue(q)[0]['id']
        self.assertEqual(q.list('other','download_shared'),[])
        for wid,owner in [('other','download_shared'),('shared','different')]:
            with self.assertRaises(SourceError):q.stop(wid,owner,key)
            with self.assertRaises(SourceError):q.visibility(wid,owner,[key])
        with self.assertRaises(SourceError):q.enqueue('other','download_shared',str(self.source),'fengshen',{},'request_foreign')

    def test_stage_associates_nearest_template_directory_and_preserves_originals(self):
        self.template('深圳/template.xlsx');self.template('广州/template.xlsx')
        for name in ('深圳/配送费.csv','广州/配送费.csv','深圳/资料/违规扣款.csv'):
            (self.source/name).parent.mkdir(parents=True,exist_ok=True);(self.source/name).write_text(name,encoding='utf-8')
        before={p:p.read_bytes() for p in self.source.rglob('*') if p.is_file()}
        q=self.queue();task=next(self.raw(q,t['id']) for t in self.enqueue(q,'manual') if t['template_name']=='template.xlsx' and '深圳' in self.raw(q,t['id'])['template_path'])
        staged=q._stage(task)
        self.assertEqual(sorted(p.relative_to(staged).as_posix() for p in staged.rglob('*') if p.is_file()),['template.xlsx','资料/违规扣款.csv','配送费.csv'])
        self.assertEqual({p:p.read_bytes() for p in before},before)
        with self.assertRaises(SourceError):q._stage(task) # never overwrite retained staging evidence

    def test_ambiguous_same_directory_manual_templates_are_not_silently_shared(self):
        self.template('深圳-template.xlsx');self.template('广州-template.xlsx');q=self.queue();task=self.raw(q,self.enqueue(q,'manual')[0]['id'])
        from types import SimpleNamespace
        def plan(path,**kwargs):return SimpleNamespace(city='深圳' if '深圳' in path.name else '广州',start='2026-10-01',end='2026-10-15')
        with patch('parttime_source.read_template',side_effect=plan),self.assertRaisesRegex(SourceError,'归属不明确'):q._stage(task)

    def test_stopped_queued_entry_does_not_run_and_hide_restore_preserves_files(self):
        original=self.template();q=self.queue();task=self.enqueue(q)[0]
        self.assertEqual(q.stop('shared','download_shared',task['id'])['status'],'cancelled')
        q.visibility('shared','download_shared',[task['id']]);self.assertEqual(q.list('shared','download_shared'),[])
        self.assertEqual(len(q.list('shared','download_shared',hidden=True)),1)
        q.visibility('shared','download_shared',[task['id']],restore=True)
        self.assertEqual(q.get('shared','download_shared',task['id'])['status'],'cancelled')
        self.assertEqual(original.read_bytes(),b'original')

    def test_restart_interrupts_unknown_active_work_but_keeps_queued_entries(self):
        self.template('one-template.xlsx');self.template('two-template.xlsx');q=self.queue();tasks=self.enqueue(q)
        q._update(tasks[0]['id'],{'status':'calculating','batch_id':'a'*32})
        restored=self.queue();rows=restored.list('shared','download_shared')
        self.assertEqual([r['status'] for r in rows],['interrupted','queued'])
        self.assertIn('未自动重跑',rows[0]['current_action'])

    def test_worker_is_serial_failure_isolated_and_accepts_more_while_running(self):
        self.template('one-template.xlsx');entered=threading.Event();release=threading.Event();calls=[];active=[]
        async def runner(config,request,*,context):
            calls.append(Path(config.sourcePath).name);active.append(len(calls))
            self.assertEqual(context,('shared','download_shared'))
            if len(calls)==1:
                entered.set()
                while not release.is_set():await asyncio.sleep(.01)
                raise SourceError('第一份模板损坏')
            yield 'data: '+json.dumps({'type':'finish','status':'success'})+'\n\n'
        q=self.queue(runner,True);first=self.enqueue(q)
        self.assertTrue(entered.wait(3));self.template('two-template.xlsx')
        self.enqueue(q,key='request_second')
        release.set();rows=self.wait(q,lambda rows:all(r['status'] in ('completed','error') for r in rows))
        self.assertEqual(rows[0]['status'],'error');self.assertTrue(all(r['status']=='completed' for r in rows[1:]))
        self.assertEqual(len(calls),3);self.assertTrue(any('损坏' in e['text'] for e in rows[0]['logs']))

    def test_manual_confirmation_does_not_block_next_task_and_requires_saved_version(self):
        self.template('one-template.xlsx');self.template('two-template.xlsx');calls=[]
        async def runner(config,request,*,context):
            calls.append(config.preparationOnly)
            key=uuid.uuid4().hex
            prep={'id':key,'mode':'manual','status':'ready','items':{},'jobs':[],'plan':{'city':'测试城','start':'2026-10-01','end':'2026-10-15','applicants':1}}
            yield 'data: '+json.dumps({'type':'payroll_preparation','preparation':prep})+'\n\n'
            yield 'data: '+json.dumps({'type':'finish','status':'paused'})+'\n\n'
        q=self.queue(runner,True)
        # Separate folders avoid ambiguous material ownership for this lifecycle test.
        (self.source/'one-template.xlsx').unlink();(self.source/'two-template.xlsx').unlink()
        self.template('one/one-template.xlsx');self.template('two/two-template.xlsx')
        rows=self.enqueue(q,'manual');rows=self.wait(q,lambda rows:all(r['status']=='waiting_confirmation' for r in rows))
        self.assertEqual(calls,[True,True])
        with patch('payroll_inputs.load',return_value=(None,{'deductions':{}})),self.assertRaisesRegex(SourceError,'先完成'):q.continue_task('shared','download_shared',rows[0]['id'])
        with patch('payroll_inputs.load',return_value=(None,{'deductions':{'version':'confirmed'}})),self.assertRaisesRegex(SourceError,'先确认'):
            q.continue_task('shared','download_shared',rows[0]['id'],'confirmed')
        q.autostart=False;q.closing.set();q.wake.set();q.thread.join(2)
        with patch('payroll_inputs.load',return_value=(None,{'deductions':{'version':'confirmed'}})),patch('deduction_confirmation.require_confirmation') as confirmation:
            continued=q.continue_task('shared','download_shared',rows[0]['id'],'confirmed')
        confirmation.assert_called_once()
        self.assertEqual(continued['status'],'queued');self.assertEqual(self.raw(q,continued['id'])['_continue_version'],'confirmed')

    def test_http_identity_keeps_same_origin_write_boundary(self):
        headers=[(b'host',b'127.0.0.1:3000'),(b'x-workspace-id',b'shared'),(b'content-type',b'application/json'),(b'origin',b'https://wrong.invalid')]
        request=Request({'type':'http','method':'POST','path':'/api/parttime/queue','scheme':'http','headers':headers,'server':('127.0.0.1',3000),'client':('127.0.0.1',1234),'query_string':b''})
        with self.assertRaises(HTTPException):identity(request)

    def test_default_log_theme_is_complete_and_never_exposes_unformatted_placeholder(self):
        config=frozen_config({},'fengshen');theme=config['theme']
        for key in ('msg_start','msg_awake','msg_empty','msg_final','msg_end'):self.assertNotIn('{wb_name}',theme[key][0])
        self.assertEqual(theme['msg_process'][0].format(wb_name='配送费'),'正在处理 配送费')
        self.assertEqual(frozen_config({'theme':{'msg_start':[]}},'manual')['theme']['msg_start'],['开始核算'])
        self.assertTrue(config['payrollExcludeSeparation'])

    def test_stop_after_source_copy_never_starts_calculation_or_export(self):
        self.template();called=[]
        async def runner(*args,**kwargs):
            called.append(True)
            yield 'data: {}\n\n'
        q=self.queue(runner);task=self.raw(q,self.enqueue(q)[0]['id'])
        def stage(value):
            q.stop('shared','download_shared',value['id']);return self.source
        with patch.object(q,'_stage',side_effect=stage),self.assertRaises(QueueStopped):asyncio.run(q._run(task))
        self.assertEqual(called,[])

    def test_process_instance_lock_prevents_a_second_queue_worker(self):
        from download_single_instance import DownloadInstanceBusy
        self.queue(autostart=True)
        with self.assertRaises(DownloadInstanceBusy):PayrollQueue(self.root,autostart=True)

    def test_batch_download_has_one_shallow_folder_per_template_without_nested_zips(self):
        import zipfile
        self.template('深圳-template.xlsx');self.template('广州-template.xlsx');q=self.queue();tasks=self.enqueue(q)
        for index,task in enumerate(tasks):q._update(task['id'],{'status':'completed','batch_id':str(index)*32})
        count=[]
        def prepared(store,key):
            part=self.root/('part_'+str(len(count))+'.zip');count.append(part)
            with zipfile.ZipFile(part,'w') as archive:archive.writestr('结果.xlsx',b'preserved result bytes')
            return part,'result.zip'
        with patch('payroll_inputs.load',return_value=(None,{})),patch('payroll_inputs.publish_result'),patch('payroll_inputs.delivery_store'),patch('delivery_store.delivery_bundle',side_effect=prepared):
            target=q.bundle('shared','download_shared',[t['id'] for t in tasks])
        with zipfile.ZipFile(target) as archive:
            names=archive.namelist();self.assertEqual(len(names),2)
            self.assertTrue(all(name.endswith('/结果.xlsx') and name.count('/')==1 for name in names))
            self.assertEqual([archive.read(name) for name in names],[b'preserved result bytes']*2)
        self.assertFalse(any(path.exists() for path in count))

    def test_list_transfers_only_selected_detail_without_deleting_retained_logs(self):
        self.template('one-template.xlsx');self.template('two-template.xlsx');q=self.queue();tasks=self.enqueue(q)
        for task in tasks:q._update(task['id'],{'logs':[{'text':'retained '+str(n),'level':'INFO'} for n in range(500)],'preparation':{'id':'a'*32,'mode':'manual','status':'ready','plan':{},'items':{'large':'data'},'execution_logs':[{'text':'technical'}]}})
        rows=q.view('shared','download_shared',detail_id=tasks[1]['id'])
        self.assertEqual(rows[0]['logs'],[]);self.assertNotIn('items',rows[0]['preparation'])
        self.assertEqual(len(rows[1]['logs']),500);self.assertIn('items',rows[1]['preparation'])
        self.assertEqual(len(q.get('shared','download_shared',tasks[0]['id'])['logs']),500)

    def test_legacy_and_queue_runs_share_one_execution_slot(self):
        import payroll_inputs as inputs
        entered=[];maximum=[];running=[0]
        async def inside(config,request,*,context=None):
            running[0]+=1;maximum.append(running[0]);entered.append(config.name)
            try:
                await asyncio.sleep(.06)
                yield 'data: '+json.dumps({'type':'finish','status':'success'})+'\n\n'
            finally:running[0]-=1
        async def go():
            from types import SimpleNamespace
            async def consume(name,context):return [event async for event in inputs.run_payroll(SimpleNamespace(name=name),None,context=context)]
            return await asyncio.gather(consume('legacy',None),consume('queue',('shared','download_shared')))
        with patch.object(inputs,'_run_payroll_in_slot',side_effect=inside):events=asyncio.run(go())
        self.assertEqual(max(maximum),1);self.assertEqual(entered,['legacy','queue'])
        self.assertTrue(any(json.loads(event[6:]).get('msg')=='等待其他核算任务完成' for event in events[1] if event.startswith('data: ')))

    def test_stopped_queue_waiter_never_enters_legacy_execution_slot(self):
        import payroll_inputs as inputs
        import payroll_control as control
        from types import SimpleNamespace
        async def go():return [e async for e in inputs.run_payroll(SimpleNamespace(_queue_cancelled=lambda:True),None,context=('shared','download_shared'))]
        control.EXECUTION_LOCK.acquire()
        try:
            with patch.object(inputs,'_run_payroll_in_slot') as inside,self.assertRaisesRegex(SourceError,'已停止'):asyncio.run(go())
            inside.assert_not_called()
        finally:control.EXECUTION_LOCK.release()

    def test_real_manual_preparation_runs_without_retaining_an_http_request(self):
        import csv
        import payroll_inputs as inputs
        from parttime_source import TemplatePlan
        from test_parttime_source import template
        template(self.source/'template.xlsx')
        with (self.source/'配送费.csv').open('w',encoding='utf-8-sig',newline='') as stream:
            writer=csv.writer(stream);writer.writerow(['账单时间','团队ID','团队名称','骑手ID','骑手名称','详情','订单号','运单号','业务交易时间','订单来源','标品','门店ID','门店名称','订单标签'])
            writer.writerow(['2026-08-20','100','测试站','00123','测试骑手','完成单','o1','w1','2026-08-20','test','','','',''])
        plan=TemplatePlan('泉州','31029436','2026-08-16','2026-08-31','2026-08','半月结','template.xlsx',1)
        with patch.object(inputs,'ROOT',self.root),patch('parttime_source.read_template',return_value=plan):
            q=self.queue(autostart=True);self.enqueue(q,'manual')
            task=self.wait(q,lambda rows:rows and rows[0]['status']=='waiting_confirmation')[0]
            self.assertTrue(task['batch_id']);self.assertEqual(task['preparation']['mode'],'manual')
            _,state=inputs.load('shared',task['batch_id'],'download_shared',self.root)
            self.assertEqual(state['items']['delivery_fee']['status'],'ready')
            self.assertEqual(state['status'],'ready')
            q.shutdown()
