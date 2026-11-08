"""No live platform calls: exercise automatic policy and unchanged batch receipts."""
import asyncio
import copy
import json
from pathlib import Path
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import patch
from openpyxl import load_workbook
import payroll_inputs as inputs
import payroll_automatic as automatic
import deduction_confirmation as review
import test_deduction_confirmation as fixtures
from parttime_source import SourceError


class AutomaticTests(TestCase):
    setUp=fixtures.ConfirmationTests.setUp
    bill=fixtures.ConfirmationTests.bill
    sha=fixtures.ConfirmationTests.sha
    read=fixtures.ConfirmationTests.read
    payload=fixtures.ConfirmationTests.payload

    def test_existing_legacy_configuration_is_used_and_missing_fields_are_zero_without_shared_writes(self):
        before=(self.root/'data/config.json').read_bytes()
        automatic.capture_rules(self.folder,self.state,self.root,self.directory)
        self.assertEqual(self.state['deductions']['rows'][0]['安全基金'],10)
        self.assertEqual(self.state['deductions']['rows'][0]['月费'],0)
        self.assertEqual(self.state['deduction_confirmation']['mode'],'automatic')
        self.assertEqual(self.state['automatic_deductions']['zero_stations'],[])
        self.assertEqual((self.root/'data/config.json').read_bytes(),before)

    def test_unknown_configuration_is_zero_with_auditable_result_note(self):
        (self.root/'data/config.json').write_text('[]')
        # An empty legacy defaults file is invalid, so keep a different existing site.
        (self.root/'data/config.json').write_text(json.dumps([{'城市':'其他城','团队名称':'其他站','安全基金':20}]))
        automatic.capture_rules(self.folder,self.state,self.root,self.directory)
        row=self.state['deductions']['rows'][0]
        self.assertTrue(all(row[col]==0 for col in review.DEFAULT_COLUMNS))
        self.assertEqual(self.state['automatic_deductions']['zero_stations'],['一站'])
        from payroll_review import build_review
        self.state['items']['delivery_fee']['label']='配送费';self.state['items']['penalty']['label']='违规扣款'
        summary=build_review(self.state,{})
        self.assertIn('automatic_zero_deductions',[r['code'] for r in summary['issues']])

    def test_city_default_and_site_override_are_distinct(self):
        self.directory['cities']=[{'id':'001','name':'测试城'}]
        draft=self.read();entry=copy.deepcopy(draft['cities'][0]);entry['row'].update({col:0 for col in draft['columns']});entry['row']['安全基金']=35
        review.save_profile('fengshen',self.root,{'version':draft['version'],'cities':[entry]},self.directory)
        automatic.capture_rules(self.folder,self.state,self.root,self.directory)
        self.assertEqual(self.state['deductions']['rows'][0]['安全基金'],35)
        self.assertEqual(self.state['automatic_deductions']['sources'][0]['source'],'城市配置')
        self.state.pop('deduction_confirmation');self.state.pop('deductions')
        draft=self.read();site=copy.deepcopy(draft['entries'][0]);site['row']['安全基金']=80;site['edited']=True
        review.save_profile('fengshen',self.root,{'version':draft['version'],'entries':[site]},self.directory)
        automatic.capture_rules(self.folder,self.state,self.root,self.directory)
        self.assertEqual(self.state['deductions']['rows'][0]['安全基金'],80)

    def test_conflicting_or_unknown_identity_still_stops_without_zero_bypass(self):
        self.bill('二站')
        with self.assertRaisesRegex(SourceError,'归属不一致'):automatic.capture_rules(self.folder,self.state,self.root,self.directory)
        self.bill('后台不存在的站点')
        with self.assertRaisesRegex(SourceError,'身份无法唯一确定'):automatic.capture_rules(self.folder,self.state,self.root,self.directory)
        self.assertNotIn('deductions',self.state)

    def test_frozen_snapshot_survives_later_default_edits(self):
        automatic.capture_rules(self.folder,self.state,self.root,self.directory)
        self.state['deductions']['frozen']=True
        (self.root/'data/config.json').write_text(json.dumps([{'城市':'测试城','团队名称':'一站','安全基金':999}]))
        automatic.capture_rules(self.folder,self.state,self.root,None)
        self.assertEqual(self.state['deductions']['rows'][0]['安全基金'],10)

    def test_separation_is_discovered_and_prepared_once_from_template(self):
        book=load_workbook(self.input/'template.xlsx');book['申请名单']['B2']='同泰时代(取分离)';book.save(self.input/'template.xlsx');book.close()
        self.state.update(mode='fengshen',template_hash=self.sha('template.xlsx'))
        self.directory['stations'].append({'platform':'fengshen','city':'测试城','city_id':'001','agency_id':'200','id':'003','name':'同泰时代(取分离)','separation':True})
        with patch('station_directory.ready_directory',return_value=self.directory),patch('station_directory.sync_separation',return_value=self.directory) as sync:
            automatic.prepare_scope(self.folder,self.state);automatic.prepare_scope(self.folder,self.state)
        sync.assert_called_once();self.assertEqual(self.state['separation_agencies'],['200'])
        self.assertTrue(self.state['include_separation'])

    def test_normal_template_does_not_trigger_separation_requests(self):
        self.state['mode']='fengshen'
        with patch('station_directory.sync_separation') as sync:automatic.prepare_scope(self.folder,self.state)
        sync.assert_not_called()

    def test_entire_automatic_run_requires_no_confirmation_or_client_rule_version(self):
        self.state.update(mode='fengshen',status='pending_download',workflow=automatic.WORKFLOW,download_owner='download_shared')
        for kind,label in inputs.LABELS.items():self.state['items'][kind]={'label':label,'status':'pending'}
        inputs.save(self.folder,self.state)
        run={'id':'job1','status':'success','phase':'completed','progress':100,'items':[{'dataset':k,'status':'success','phase':'completed'} for k in inputs.LABELS],'files':[]}
        manager=SimpleNamespace(create=lambda *a,**kw:run,get_run=lambda *a:run)
        def collect(folder,state,_manager):
            for value in state['items'].values():value.update(status='ready',file='bill.csv',sha256=self.sha('bill.csv'))
            state['status']='ready';inputs.save(folder,state)
        async def engine(*args,**kw):
            self.assertEqual(kw['deductionRules'][0]['安全基金'],10)
            yield 'data: '+json.dumps({'type':'finish','status':'success','out_file':'','stats':{}})+'\n\n'
        config=SimpleNamespace(payrollSourceMode='fengshen',payrollPreparationId=self.state['id'],preparationOnly=True,deductionConfigVersion='',basePath='',theme='',enableInterceptor=True,enableCrossStationMerge=False)
        async def execute():return [event async for event in inputs.run_payroll(config,None)]
        with patch.object(inputs,'ROOT',self.root),patch.object(inputs,'workspace',return_value='shared'),patch.object(inputs,'account',return_value='download_shared'),patch('download_jobs.get_manager',return_value=manager),patch('download_service.validate_request',side_effect=lambda config:config),patch.object(inputs,'collect_finished',side_effect=collect),patch('station_directory.ready_directory',return_value=self.directory),patch('tasks.run_main_calculation_gen',engine),patch.object(inputs,'publish_result',side_effect=SourceError('合成结果不发布')):
            events=asyncio.run(execute())
        decoded=[json.loads(e[6:]) for e in events if e.startswith('data: ')]
        self.assertTrue(any(e.get('type')=='finish' and e.get('status')=='success' for e in decoded))
        self.assertFalse(any(e.get('type')=='finish' and e.get('status')=='paused' for e in decoded))
        stored=inputs.load('shared',self.state['id'],'download_shared',self.root)[1]
        self.assertEqual(stored['status'],'calculated');self.assertTrue(stored['deductions']['frozen'])
