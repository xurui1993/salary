import asyncio
import csv
import json
from pathlib import Path
from types import SimpleNamespace
import threading
import contextlib
from unittest import TestCase
from unittest.mock import patch,Mock
import test_deduction_confirmation as fixtures
import payroll_inputs as inputs
import payroll_readable_policy as policy
from payroll_unified_download import execute,merge_tables
from parttime_source import SourceError


class ReadablePolicyTests(TestCase):
    setUp=fixtures.ConfirmationTests.setUp
    bill=fixtures.ConfirmationTests.bill
    sha=fixtures.ConfirmationTests.sha

    def manager(self,corrupt=False):
        self.state.update(mode='fengshen',input_policy=policy.POLICY,workflow='two_step_v1',download_owner='download_shared',jobs=['one'])
        self.state['items']={kind:{'label':label,'status':'pending'} for kind,label in inputs.LABELS.items()}
        bad=self.root/'bad.xlsx';bad.write_bytes(b'not an Excel file')
        run={'id':'one','status':'partial','items':[{'dataset':kind,'status':'success' if kind in ('delivery_fee','payment_binding') else 'error'} for kind in inputs.LABELS],
             'files':[{'id':'fee','dataset':'delivery_fee','name':'配送费.csv','bytes':1,'sha256':'obsolete'},{'id':'binding','dataset':'payment_binding','name':'绑定.xlsx'}]}
        def get_file(owner,job,key,verify_integrity=True):
            self.assertFalse(verify_integrity)
            return (bad if key=='binding' or corrupt else self.input/'bill.csv'),key
        return SimpleNamespace(get_run=lambda *args:run,get_file=get_file),run

    def test_readable_delivery_runs_without_hash_or_binding_price_and_no_failure_ledger(self):
        manager,_=self.manager()
        with patch.object(inputs,'digest',side_effect=AssertionError('No SHA gate')):
            policy.collect(self.folder,self.state,manager)
            actual=policy.inputs(self.folder,self.state)
        self.assertEqual(actual,self.input/'usable');self.assertEqual(self.state['status'],'ready')
        self.assertEqual(self.state['items']['payment_binding']['status'],'omitted')
        self.assertEqual(self.state['items']['lanorange_part_price']['status'],'omitted')
        self.assertFalse(any('error' in value or value['status']=='failed' for value in self.state['items'].values()))
        self.assertEqual(sorted(p.name for p in actual.iterdir()),['template.xlsx','配送费.csv'])

    def test_corrupt_delivery_stops_with_log_reason(self):
        manager,_=self.manager(True);policy.collect(self.folder,self.state,manager)
        self.assertEqual(self.state['status'],'waiting_materials')
        with self.assertRaisesRegex(SourceError,'本次任务结束'):policy.inputs(self.folder,self.state)

    def test_unavailable_sources_keep_download_and_parse_causes_in_notes_and_logs(self):
        manager,run=self.manager()
        next(item for item in run['items'] if item['dataset']=='penalty')['error']='平台导出文件下载超时'
        policy.collect(self.folder,self.state,manager)
        self.assertIn('平台导出文件下载超时',self.state['items']['penalty']['note'])
        self.assertIn('文件无法读取',self.state['items']['payment_binding']['note'])
        self.assertTrue(any('违规扣款' in entry['text'] and '平台导出文件下载超时' in entry['text'] for entry in self.state['execution_logs']))
        self.assertTrue(any('骑手支付绑定' in entry['text'] and '文件无法读取' in entry['text'] for entry in self.state['execution_logs']))
        self.assertFalse(any('error' in value or value['status']=='failed' for value in self.state['items'].values()))

    def test_site_differences_and_old_digest_do_not_block_rule_selection(self):
        manager,_=self.manager();policy.collect(self.folder,self.state,manager)
        self.state['template_hash']='intentionally-outdated'
        policy.capture_rules(self.folder,self.state,self.root)
        self.assertEqual(self.state['deductions']['rows'][0]['安全基金'],10)
        self.assertNotIn('deduction_confirmation',self.state)

    def test_unified_task_is_created_once_even_when_separation_is_enabled(self):
        manager,_=self.manager();self.state['jobs']=[];self.state.update(exclude_separation=False,include_separation=True,separation_agencies=['200','300'])
        created=[]
        manager.create=lambda owner,config,request_id:(created.append(config) or {'id':'unified'})
        with patch('download_service.validate_request',side_effect=lambda config:config):inputs.start_download(self.folder,self.state,manager)
        self.assertEqual(len(created),1);self.assertTrue(created[0]['payroll_unified'])
        self.assertEqual(created[0]['payroll_scope_mode'],'single');self.assertIs(created[0]['exclude_separation'],False);self.assertNotIn('include_separation',created[0]);self.assertNotIn('payroll_scope_agencies',created[0]);self.assertEqual(self.state['jobs'],['unified'])

    def test_unified_export_contains_both_scopes_in_one_file_per_dataset(self):
        config={'task_kind':'payroll_source','payroll_unified':True,'payroll_scope_agencies':['200'],
                'cities':['测试城'],'datasets':['delivery_fee','penalty'],'months':['2026-10'],'start':'2026-10-01','end':'2026-10-15'}
        calls=[];updates=[]
        def provider(child,root,log,cancelled,changed,runner_factory=None):
            root=Path(root);root.mkdir(parents=True,exist_ok=True);calls.append(child)
            for kind in child['datasets']:
                path=root/(kind+'.csv')
                with path.open('w',encoding='utf-8-sig',newline='') as f:
                    writer=csv.writer(f);writer.writerow(['骑手ID','日期','团队名称']);writer.writerow(['2' if child.get('include_separation') else '1','2026-10-01','取分离' if child.get('include_separation') else '普通'])
                entry={'city':'测试城','dataset':kind,'start':config['start'],'end':config['end'],'relative_path':path.name}
                changed({**entry,'status':'success','phase':'completed','files':[entry]})
            return []
        with patch('download_service.execute_downloads',side_effect=provider):files=execute(config,self.root/'download',lambda *a:None,threading.Event(),updates.append)
        self.assertEqual(len(files),2)
        for info in files:
            with (self.root/'download'/info['relative_path']).open(encoding='utf-8-sig') as f:rows=list(csv.reader(f))
            self.assertEqual(len(rows),3);self.assertEqual({r[0] for r in rows[1:]},{'1','2'})
        self.assertEqual(len([e for e in updates if e.get('status')=='success' and e.get('dataset')=='delivery_fee']),1)

    def test_real_download_executor_merges_authorized_platform_scopes_in_one_delivery_file(self):
        import download_service as service
        from test_download_service import FakeRunner
        runner=FakeRunner();client=Mock()
        client.request_json.return_value={'data':[{'agencyId':'200','agencyCityName':'测试城','agencySubTypeName':'物流服务商'}]}
        config={'task_kind':'payroll_source','payroll_unified':True,'payroll_scope_agencies':['200'],'cities':['测试城'],
                'datasets':['delivery_fee'],'months':['2026-10'],'start':'2026-10-01','end':'2026-10-15'}
        updates=[]
        with patch.object(service,'cities',return_value={'测试城':'100'}),patch('deduction_stations._fengshen_client',return_value=client):
            files=service.execute_downloads(config,self.root/'real-executor',lambda *a:None,threading.Event(),updates.append,lambda *args:contextlib.nullcontext(runner))
        self.assertEqual(len(files),1)
        with (self.root/'real-executor'/files[0]['relative_path']).open(encoding='utf-8-sig') as f:rows=list(csv.DictReader(f))
        self.assertEqual(len(rows),2)
        self.assertEqual(sum('取分离' in str(row) for row in rows),1)
        self.assertEqual(sum(e.get('status')=='success' and e.get('dataset')=='delivery_fee' for e in updates),1)

    def test_single_selection_matches_download_center_without_fetching_second_agency(self):
        import download_service as service
        from test_download_service import FakeRunner
        for field,selected,count in (('exclude_separation',False,2),('exclude_separation',True,1),('include_separation',False,1),('include_separation',True,1)):
            runner=FakeRunner()
            config={'task_kind':'payroll_source','payroll_unified':True,'payroll_scope_mode':'single',field:selected,
                    'payroll_scope_agencies':['200'],'cities':['测试城'],'datasets':['delivery_fee'],
                    'months':['2026-10'],'start':'2026-10-01','end':'2026-10-15'}
            root=self.root/(field+str(selected))
            with patch.object(service,'cities',return_value={'测试城':'100'}),patch('deduction_stations._fengshen_client') as directory_client:
                files=service.execute_downloads(config,root,lambda *a:None,threading.Event(),lambda *a:None,lambda *args:contextlib.nullcontext(runner))
            directory_client.assert_not_called()
            self.assertEqual(len(files),1);self.assertEqual(len(runner.calls),1)
            with (root/files[0]['relative_path']).open(encoding='utf-8-sig') as f:rows=list(csv.DictReader(f))
            self.assertEqual(len(rows),count)
            self.assertEqual(sum('取分离' in str(row) for row in rows),int(not selected if field=='exclude_separation' else selected))

    def test_scope_column_differences_are_aligned_without_consistency_gate(self):
        a=self.root/'a.csv';b=self.root/'b.csv';target=self.root/'merged.csv'
        a.write_text('骑手ID,日期\n1,2026-10-01\n',encoding='utf-8-sig');b.write_text('日期,骑手ID,备注\n2026-10-01,2,原文\n',encoding='utf-8-sig')
        merge_tables([a,b],target)
        with target.open(encoding='utf-8-sig') as f:rows=list(csv.DictReader(f))
        self.assertEqual([r['骑手ID'] for r in rows],['1','2']);self.assertEqual(rows[1]['备注'],'原文')

    def test_binding_login_keeps_the_original_task_waiting_and_never_silently_skips(self):
        from download_service import DownloadCancelled
        config={'task_kind':'payroll_source','payroll_unified':True,'payroll_scope_agencies':[],
                'cities':['测试城'],'datasets':['delivery_fee','payment_binding'],'months':['2026-10'],'start':'2026-10-01','end':'2026-10-15'}
        updates=[]
        def provider(child,root,log,cancelled,changed,runner_factory=None):
            if child['datasets']==['delivery_fee']:
                root=Path(root);root.mkdir(parents=True,exist_ok=True);p=root/'fee.csv';p.write_text('骑手ID,日期\n1,2026-10-01\n',encoding='utf-8-sig')
                d={'city':'测试城','dataset':'delivery_fee','start':config['start'],'end':config['end'],'relative_path':'fee.csv'}
                changed({**d,'status':'success','files':[d]})
            else:
                changed({'_run_event':True,'status':'waiting_login','phase':'waiting_login'})
                self.assertFalse(cancelled.is_set());raise DownloadCancelled('verification not completed')
            return []
        with patch('download_service.execute_downloads',side_effect=provider), self.assertRaisesRegex(SourceError,'未生成工资表'):
            execute(config,self.root/'download',lambda *a:None,threading.Event(),updates.append)
        self.assertTrue(any(e.get('status')=='waiting_login' and e.get('payroll_verification_required') for e in updates))

    def test_readable_policy_calls_engine_without_hashes_and_with_unknown_binding_price(self):
        manager,run=self.manager();self.state['status']='pending_download';self.state['jobs']=[]
        created=[];manager.create=lambda owner,config,request_id:(created.append(config) or run)
        inputs.save(self.folder,self.state)
        async def engine(*args,**kw):
            self.assertEqual(kw['verified_inputs'],{})
            self.assertTrue(kw['skip_binding_check']);self.assertTrue(kw['force_no_price'])
            self.assertEqual(Path(args[2]).name,'usable')
            yield 'data: '+json.dumps({'type':'finish','status':'success','out_file':'','stats':{}})+'\n\n'
        config=SimpleNamespace(payrollSourceMode='fengshen',payrollPreparationId=self.state['id'],basePath='',theme='',enableInterceptor=True,enableCrossStationMerge=False)
        async def go():return [e async for e in inputs.run_payroll(config,None)]
        with patch.object(inputs,'ROOT',self.root),patch.object(inputs,'workspace',return_value='shared'),patch.object(inputs,'account',return_value='download_shared'),patch('download_jobs.get_manager',return_value=manager),patch('download_service.validate_request',side_effect=lambda value:value),patch('tasks.run_main_calculation_gen',engine),patch.object(inputs,'publish_result',side_effect=SourceError('synthetic not published')):
            events=asyncio.run(go())
        messages=[json.loads(e[6:]) for e in events if e.startswith('data: ')]
        self.assertTrue(any(e.get('type')=='finish' and e.get('status')=='success' for e in messages))
        self.assertEqual(len(created),1)
        stored=inputs.load('shared',self.state['id'],'download_shared',self.root)[1]
        self.assertFalse(stored['result']['input_hashes_verified']);self.assertNotIn('SHA256校验输入',stored['result']['review_summary']['input_check'])

    def test_unreadable_delivery_ends_and_only_exposes_reason_in_execution_logs(self):
        manager,run=self.manager(True);self.state.update(status='pending_download',jobs=[])
        manager.create=lambda *args,**kwargs:run
        inputs.save(self.folder,self.state)
        config=SimpleNamespace(payrollSourceMode='fengshen',payrollPreparationId=self.state['id'])
        async def go():return [e async for e in inputs.run_payroll(config,None)]
        with patch.object(inputs,'ROOT',self.root),patch.object(inputs,'workspace',return_value='shared'),patch.object(inputs,'account',return_value='download_shared'),patch('download_jobs.get_manager',return_value=manager),patch('download_service.validate_request',side_effect=lambda value:value),patch('tasks.run_main_calculation_gen') as engine:
            events=asyncio.run(go())
        engine.assert_not_called()
        messages=[json.loads(e[6:]) for e in events if e.startswith('data: ')]
        finish=[e for e in messages if e.get('type')=='finish'][-1]
        self.assertEqual(finish['status'],'error');self.assertEqual(finish['result_msg'],'任务已结束，详情见执行日志')
        stored=inputs.load('shared',self.state['id'],'download_shared',self.root)[1]
        self.assertEqual(stored['status'],'error');self.assertNotIn('pause_reason',stored)
        self.assertTrue(any('配送费无法读取' in e['text'] for e in stored['execution_logs']))
        self.assertFalse(any('重新上传' in e['text'] for e in stored['execution_logs']))
