import copy
import csv
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
import asyncio
from types import SimpleNamespace
from unittest.mock import patch
from openpyxl import Workbook, load_workbook
import deduction_confirmation as review
import payroll_inputs
from parttime_source import SourceError


class ConfirmationTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);(self.root/'data').mkdir()
        self.legacy=[{'城市':'测试城','团队名称':'一站','团队ID':'0001','安全基金':10}]
        (self.root/'data/config.json').write_text(json.dumps(self.legacy),encoding='utf-8')
        self.folder=self.root/'uploads'/'shared'/('payroll_'+'a'*32);self.input=self.folder/'input';self.input.mkdir(parents=True)
        book=Workbook();book.active.title='申请名单';book.active.append(['业务城市','团队名称','骑手ID']);book.active.append(['测试城','一站','00001']);book.save(self.input/'template.xlsx');book.close()
        self.bill('一站')
        self.directory={'platform':'fengshen','session_version':'session-v1','stations':[
            {'platform':'fengshen','city':'测试城','city_id':'001','id':'0001','name':'一站'},
            {'platform':'fengshen','city':'测试城','city_id':'001','id':'0002','name':'二站'}]}

    def bill(self,team):
        with (self.input/'bill.csv').open('w',encoding='utf-8-sig',newline='') as f:
            writer=csv.writer(f);writer.writerow(['骑手ID','团队名称','日期']);writer.writerow(['00001',team,'2026-10-01'])
        self.state={'id':'a'*32,'mode':'manual','status':'ready','jobs':[],
                    'template_hash':self.sha('template.xlsx'),
                    'plan':{'city':'测试城','start':'2026-10-01','end':'2026-10-15','month':'2026-10','cycle':'半月结','template':'template.xlsx','applicants':1},
                    'items':{'delivery_fee':{'status':'ready','file':'bill.csv','sha256':self.sha('bill.csv')},'penalty':{'status':'omitted'}}}

    def sha(self,name):return hashlib.sha256((self.input/name).read_bytes()).hexdigest()
    def read(self):return review.preflight(self.folder,self.state,self.root,self.directory)
    def payload(self,data=None,zero=False):
        data=data or self.read();entries=copy.deepcopy(data['entries'])
        for entry in entries:
            for col in data['columns']:
                if entry['row'][col] is None:entry['row'][col]=0
            if zero:
                for col in data['columns']:entry['row'][col]=0
                entry['zero_confirmed']=True
        return {'entries':entries,'review_version':data['review_version'],'accepted_differences':[d['id'] for d in data['differences']], 'confirmed':True,'save_defaults':False}

    def test_xiaoxiang_pseudo_city_matches_stations_across_all_cities(self):
        book=Workbook();book.active.title='申请名单'
        book.active.append(['业务城市','团队名称','骑手ID'])
        book.active.append(['测试城','一站','00001'])
        book.active.append(['邻城','三站','00002'])
        book.save(self.input/'xiaoxiang.xlsx');book.close()
        self.bill('一站')
        self.state={'id':'a'*32,'mode':'xiaoxiang','status':'ready','jobs':[],
                    'template_hash':self.sha('xiaoxiang.xlsx'),
                    'plan':{'city':'小象','start':'2026-10-26','end':'2026-11-01','month':'2026-10','cycle':'周结','template':'xiaoxiang.xlsx','applicants':2},
                    'items':{'delivery_fee':{'status':'ready','file':'bill.csv','sha256':self.sha('bill.csv')},'penalty':{'status':'omitted'}}}
        self.directory={'platform':'xiaoxiang','session_version':'session-v1','cities':[
                            {'id':'001','name':'测试城'},{'id':'002','name':'邻城'}],
                        'stations':[
                            {'platform':'xiaoxiang','city':'测试城','city_id':'001','id':'0001','name':'一站'},
                            {'platform':'xiaoxiang','city':'邻城','city_id':'002','id':'0003','name':'三站'}]}
        data=self.read()
        self.assertEqual({e['station']['id'] for e in data['entries']},{'0001','0003'})
        self.assertEqual(data['unresolved'],[])

    def test_xiaoxiang_bill_station_id_matches_poi_id_of_directory(self):
        with (self.input/'poi.csv').open('w',encoding='utf-8-sig',newline='') as f:
            writer=csv.writer(f);writer.writerow(['骑手ID','团队名称','站点ID','日期']);writer.writerow(['00001','一站','10001954','2026-10-01'])
        book=Workbook();book.active.title='申请名单'
        book.active.append(['业务城市','团队名称','骑手ID']);book.active.append(['测试城','一站','00001'])
        book.save(self.input/'poi.xlsx');book.close()
        self.state={'id':'a'*32,'mode':'xiaoxiang','status':'ready','jobs':[],
                    'template_hash':self.sha('poi.xlsx'),
                    'plan':{'city':'测试城','start':'2026-10-26','end':'2026-11-01','month':'2026-10','cycle':'周结','template':'poi.xlsx','applicants':1},
                    'items':{'delivery_fee':{'status':'ready','file':'poi.csv','sha256':self.sha('poi.csv')},'penalty':{'status':'omitted'}}}
        self.directory={'platform':'xiaoxiang','session_version':'session-v1','cities':[{'id':'001','name':'测试城'}],
                        'stations':[{'platform':'xiaoxiang','city':'测试城','city_id':'001','id':'2155','poi_id':'10001954','name':'一站'},
                                    {'platform':'xiaoxiang','city':'测试城','city_id':'001','id':'2448','poi_id':'10002360','name':'二站'}]}
        data=self.read()
        self.assertEqual(data['unresolved'],[])
        self.assertEqual({e['station']['id'] for e in data['entries']},{'2155'})
        self.assertEqual(data['entries'][0]['row']['团队ID'],'2155')

    def test_new_station_and_legacy_candidates_are_pending_until_explicit_confirmation(self):
        data=self.read();self.assertEqual(len(data['entries']),1);self.assertFalse(data['entries'][0]['configured'])
        self.assertEqual(data['entries'][0]['row']['团队ID'],'0001');self.assertEqual(data['entries'][0]['row']['安全基金'],10)
        body=self.payload(data);body['entries'][0]['row']['使用费']=None
        with self.assertRaisesRegex(SourceError,'全部扣款'):review.confirm(self.folder,self.state,self.root,self.directory,body)

    def test_zero_requires_explicit_acknowledgement(self):
        body=self.payload(zero=True);body['entries'][0]['zero_confirmed']=False
        with self.assertRaisesRegex(SourceError,'零扣款'):review.confirm(self.folder,self.state,self.root,self.directory,body)
        body['entries'][0]['zero_confirmed']=True
        deduction,receipt=review.confirm(self.folder,self.state,self.root,self.directory,body)
        self.assertEqual(deduction['rows'][0]['安全基金'],0);self.assertEqual(receipt['rules_version'],deduction['version'])

    def test_batch_alias_uses_official_identity_and_keeps_shared_name_and_input_unchanged(self):
        book=load_workbook(self.input/'template.xlsx');book['申请名单']['B2']='申请别名';book.save(self.input/'template.xlsx');book.close()
        self.state['template_hash']=self.sha('template.xlsx');before=(self.input/'template.xlsx').read_bytes()
        data=self.read();self.assertEqual(data['unresolved'][0]['code'],'missing')
        self.state['station_links']={'申请别名':review.station_key(self.directory['stations'][0])}
        data=self.read();self.assertFalse(data['unresolved']);self.assertFalse(data['differences'])
        deduction,receipt=review.confirm(self.folder,self.state,self.root,self.directory,self.payload(data))
        self.assertEqual({r['团队名称'] for r in deduction['rows']},{'一站','申请别名'})
        self.assertTrue(all(r['团队ID']=='0001' and r['安全基金']==10 for r in deduction['rows']))
        self.assertEqual(receipt['station_links'],self.state['station_links'])
        self.assertEqual((self.input/'template.xlsx').read_bytes(),before)
        self.assertEqual(json.loads((self.root/'data/config.json').read_text()),self.legacy)

    def test_unlinked_existing_batch_signature_stays_compatible_and_link_change_revokes_it(self):
        legacy=review.digest({'template':self.state['template_hash'],'items':self.state['items'],'all_files':[],'plan':self.state['plan']})
        self.assertEqual(review.input_signature(self.state),legacy)
        self.state['station_links']={};self.assertEqual(review.input_signature(self.state),legacy)
        self.state['station_links']={'别名':'target'};self.assertNotEqual(review.input_signature(self.state),legacy)

    def test_alias_cannot_cross_city_override_explicit_id_or_collide_with_other_rule(self):
        book=load_workbook(self.input/'template.xlsx');sheet=book['申请名单'];sheet['B2']='别名';sheet.cell(1,4,'团队ID');sheet.cell(2,4,'0002');book.save(self.input/'template.xlsx');book.close()
        self.state['template_hash']=self.sha('template.xlsx');self.state['station_links']={'别名':review.station_key(self.directory['stations'][0])}
        data=self.read();self.assertTrue(data['unresolved']);self.assertEqual(data['unresolved'][0]['code'],'id_conflict')
        self.directory['stations'][0]['city']='其他城市'
        self.assertTrue(self.read()['unresolved'])

    def test_link_route_rejects_stale_or_foreign_choice_and_records_valid_mapping(self):
        import workbench
        from fastapi import HTTPException
        book=load_workbook(self.input/'template.xlsx');book['申请名单']['B2']='别名';book.save(self.input/'template.xlsx');book.close();self.state['template_hash']=self.sha('template.xlsx');self.state['download_owner']=None
        payroll_inputs.save(self.folder,self.state)
        body={'confirmed':True,'links':{'别名':'foreign'},'review_version':self.read()['review_version']}
        class Request:
            async def json(inner):return body
        with patch.object(workbench,'ROOT',self.root),patch.object(payroll_inputs,'ROOT',self.root),patch('download_accounts.require_admin'),patch('payroll_inputs.workspace',return_value='shared'),patch('payroll_inputs.account',return_value=None),patch('station_directory.ready_directory',return_value=self.directory):
            with self.assertRaises(HTTPException):asyncio.run(workbench.link_batch_stations('a'*32,Request()))
            body['links']['别名']=review.station_key(self.directory['stations'][0]);body['review_version']='stale'
            with self.assertRaises(HTTPException):asyncio.run(workbench.link_batch_stations('a'*32,Request()))
            body['review_version']=self.read()['review_version']
            result=asyncio.run(workbench.link_batch_stations('a'*32,Request()))
            self.assertFalse(result['unresolved'])
            stored=payroll_inputs.load('shared','a'*32,None,self.root)[1];self.assertEqual(stored['audit'][-1]['action'],'confirm_station_links');self.assertIn('别名',stored['station_links'])

    def test_city_default_applies_to_new_and_separation_sites_without_overriding_saved_site(self):
        self.directory['cities']=[{'id':'001','name':'测试城'}]
        initial=self.read();station=self.payload(initial)['entries'][0]
        review.save_profile('fengshen',self.root,{'version':initial['version'],'entries':[station]},self.directory)
        draft=review.station_drafts('fengshen',self.root,self.directory)
        city=copy.deepcopy(draft['cities'][0]);city['row'].update({c:0 for c in draft['columns']});city['row']['安全基金']=25
        review.save_profile('fengshen',self.root,{'version':draft['version'],'cities':[city]},self.directory)
        self.directory['stations'].append({**self.directory['stations'][1],'id':'0003','name':'三站(取分离)'})
        again=review.station_drafts('fengshen',self.root,self.directory)
        self.assertEqual([e['row']['安全基金'] for e in again['entries']],[10,25,25])
        self.assertTrue(again['entries'][2]['inherited_city']);self.assertTrue(again['entries'][0]['station_override'])
        review.save_profile('fengshen',self.root,{'version':again['version'],'entries':again['entries'][1:]},self.directory)
        self.assertEqual(len(review.profile('fengshen',self.root)['entries']),1)

    def test_zero_city_requires_ack_and_unknown_city_cannot_be_created(self):
        self.directory['cities']=[{'id':'001','name':'测试城'}]
        draft=review.station_drafts('fengshen',self.root,self.directory);city=copy.deepcopy(draft['cities'][0]);city['row'].update({c:0 for c in draft['columns']})
        with self.assertRaisesRegex(SourceError,'零扣款'):review.save_profile('fengshen',self.root,{'version':draft['version'],'cities':[city]},self.directory)
        city['zero_confirmed']=True;city['key']='not-authorized'
        with self.assertRaises(SourceError):review.save_profile('fengshen',self.root,{'version':draft['version'],'cities':[city]},self.directory)

    def test_differences_cannot_be_omitted_or_bypassed_by_dropping_stations(self):
        self.bill('二站');data=self.read();self.assertEqual(len(data['entries']),2);self.assertEqual(len(data['differences']),1)
        body=self.payload(data);body['accepted_differences']=[]
        with self.assertRaisesRegex(SourceError,'逐项'):review.confirm(self.folder,self.state,self.root,self.directory,body)
        body=self.payload(data);body['entries'].pop()
        with self.assertRaisesRegex(SourceError,'清单不完整'):review.confirm(self.folder,self.state,self.root,self.directory,body)

    def test_defaults_reused_by_platform_and_station_with_conflict_check_and_backup(self):
        data=self.read();body=self.payload(data);body['save_defaults']=True
        review.confirm(self.folder,self.state,self.root,self.directory,body)
        again=self.read();self.assertTrue(again['entries'][0]['configured']);self.assertEqual(again['entries'][0]['row']['安全基金'],10)
        with self.assertRaisesRegex(SourceError,'已变化'):review.confirm(self.folder,self.state,self.root,self.directory,body)
        review.confirm(self.folder,self.state,self.root,self.directory,self.payload(again)|{'save_defaults':True})
        self.assertTrue(list((self.root/'data/deduction_profiles/history').glob('*.json')))
        self.assertEqual(review.profile('xiaoxiang',self.root)['entries'],{})
        self.assertEqual(json.loads((self.root/'data/config.json').read_text()),self.legacy)

    def test_changed_inputs_directory_or_rules_revoke_confirmation(self):
        body=self.payload();deduction,receipt=review.confirm(self.folder,self.state,self.root,self.directory,body)
        self.state.update(deductions=deduction,deduction_confirmation=receipt)
        review.require_confirmation(self.state,deduction['version'])
        self.state['deductions']['rows'][0]['安全基金']=999
        with self.assertRaises(SourceError):review.require_confirmation(self.state,deduction['version'])
        self.state['deductions']=deduction=copy.deepcopy(deduction)
        self.state['items']['penalty']['status']='pending'
        with self.assertRaises(SourceError):review.require_confirmation(self.state,deduction['version'])
        self.state['items']['penalty']['status']='omitted'
        with self.assertRaisesRegex(SourceError,'请先确认'):review.require_confirmation(self.state,'')
        changed=copy.deepcopy(self.directory);changed['session_version']='other-account'
        with self.assertRaisesRegex(SourceError,'已变化'):review.confirm(self.folder,self.state,self.root,changed,body)

    def test_unknown_ambiguous_or_empty_team_never_silently_matches(self):
        self.bill('未知站');data=self.read();self.assertTrue(data['unresolved'])
        with self.assertRaisesRegex(SourceError,'尚未匹配'):review.confirm(self.folder,self.state,self.root,self.directory,self.payload(data))
        self.directory['stations'].append({**self.directory['stations'][0],'id':'999'})
        self.assertTrue(self.read()['unresolved'])

    def test_modified_retained_file_is_rejected_before_confirmation(self):
        (self.input/'bill.csv').write_text('modified',encoding='utf-8')
        with self.assertRaisesRegex(SourceError,'被修改'):self.read()

    def test_intent_before_download_requires_explicit_amounts_and_cannot_claim(self):
        self.state.update(mode='fengshen',status='awaiting_confirmation')
        self.state['items']['delivery_fee']={'status':'pending'}
        (self.input/'bill.csv').unlink()
        data=self.read()
        self.assertEqual(data['stage'],'intent');self.assertFalse(data['differences'])
        deduction,receipt=review.confirm(self.folder,self.state,self.root,self.directory,self.payload(data))
        self.state.update(deductions=deduction,deduction_confirmation=receipt)
        with self.assertRaisesRegex(SourceError,'先确认'):review.require_confirmation(self.state,deduction['version'])

    def test_download_finalizes_only_unchanged_sites_and_keeps_approved_money(self):
        self.state.update(mode='fengshen',status='awaiting_confirmation')
        deduction,intent=review.confirm(self.folder,self.state,self.root,self.directory,self.payload())
        self.state.update(status='ready',deductions=deduction,deduction_intent=intent,
                          deduction_confirmation=intent)
        self.state['items']['payment_binding']={'status':'ready','file':'bill.csv','sha256':self.sha('bill.csv')}
        (self.root/'data/config.json').write_text(json.dumps([{**self.legacy[0],'安全基金':999}]),encoding='utf-8')
        review.finalize_intent(self.folder,self.state,self.root,self.directory)
        self.assertEqual(self.state['deductions']['rows'][0]['安全基金'],10)
        self.assertEqual(self.state['deduction_confirmation']['stage'],'final')
        review.require_confirmation(self.state,deduction['version'])

    def test_download_difference_pauses_without_auto_acknowledgement(self):
        self.state.update(mode='fengshen',status='awaiting_confirmation')
        deduction,intent=review.confirm(self.folder,self.state,self.root,self.directory,self.payload())
        self.bill('二站')
        self.state.update(mode='fengshen',deductions=deduction,deduction_intent=intent)
        self.state['items']['payment_binding']={'status':'ready','file':'bill.csv','sha256':self.sha('bill.csv')}
        with self.assertRaisesRegex(SourceError,'存在差异'):review.finalize_intent(self.folder,self.state,self.root,self.directory)
        self.assertNotIn('deduction_confirmation',self.state)

    def test_amount_change_in_legacy_defaults_revokes_review_token(self):
        body=self.payload()
        (self.root/'data/config.json').write_text(json.dumps([{**self.legacy[0],'安全基金':20}]),encoding='utf-8')
        with self.assertRaisesRegex(SourceError,'已变化'):review.confirm(self.folder,self.state,self.root,self.directory,body)

    def test_legacy_extra_fields_and_blank_thresholds_are_preserved_not_invented_as_charges(self):
        row={**self.legacy[0],'历史扩展说明':'保留','安全基金_maxDays':None,'未接入固定费用':123}
        (self.root/'data/config.json').write_text(json.dumps([row]),encoding='utf-8')
        data=self.read();self.assertNotIn('未接入固定费用',data['columns']);self.assertIn('安全基金_maxDays',data['columns'])
        body=self.payload(data);body['entries'][0]['row']['安全基金_maxDays']=None
        deduction,_=review.confirm(self.folder,self.state,self.root,self.directory,body)
        self.assertIsNone(deduction['rows'][0]['安全基金_maxDays']);self.assertEqual(deduction['rows'][0]['历史扩展说明'],'保留')
        body['entries'][0]['row']['历史扩展说明']='篡改'
        with self.assertRaises(SourceError):review.confirm(self.folder,self.state,self.root,self.directory,body)

    def test_application_reads_only_application_sheet_and_uses_explicit_station_ids(self):
        book=Workbook();book.active.title='申请名单';book.active.append(['团队名称','骑手ID','团队ID']);book.active.append(['一站','00001','0001']);extra=book.create_sheet('其他资料');extra.append(['团队名称','骑手ID']);extra.append(['无关站','999']);book.save(self.input/'template.xlsx');book.close()
        self.state['template_hash']=self.sha('template.xlsx')
        self.directory['stations'].append({**self.directory['stations'][0],'id':'other'})
        data=self.read();self.assertEqual(len(data['entries']),1);self.assertFalse(data['unresolved'])

    def test_http_confirmation_route_preserves_admin_permission_and_fixed_batch_guard(self):
        from fastapi import HTTPException
        import workbench
        self.folder.joinpath('manifest.json').write_text(json.dumps(self.state),encoding='utf-8')
        body=self.payload()
        class Request:
            async def json(inner):return body
        with patch.object(workbench,'ROOT',self.root),patch.object(payroll_inputs,'ROOT',self.root),patch('download_accounts.require_account'),patch('download_accounts.require_admin',side_effect=HTTPException(403,'admin required')),patch('payroll_inputs.workspace',return_value='shared'),patch('payroll_inputs.account',return_value=None),patch('station_directory.ready_directory',return_value=self.directory):
            with self.assertRaises(HTTPException) as error:asyncio.run(workbench.confirm_deduction_review('a'*32,Request()))
            self.assertEqual(error.exception.status_code,403)
        with patch.object(workbench,'ROOT',self.root),patch.object(payroll_inputs,'ROOT',self.root),patch('download_accounts.require_account'),patch('download_accounts.require_admin'),patch('payroll_inputs.workspace',return_value='shared'),patch('payroll_inputs.account',return_value=None),patch('station_directory.ready_directory',return_value=self.directory):
            result=asyncio.run(workbench.confirm_deduction_review('a'*32,Request()))
            self.assertTrue(result['deduction_version'])
            stored=json.loads(self.folder.joinpath('manifest.json').read_text(encoding='utf-8'));stored['deductions']['frozen']=True;self.folder.joinpath('manifest.json').write_text(json.dumps(stored),encoding='utf-8')
            with self.assertRaises(HTTPException) as error:asyncio.run(workbench.confirm_deduction_review('a'*32,Request()))
            self.assertEqual(error.exception.status_code,409)

    def test_frozen_rules_and_receipt_are_retained_at_calculation_claim(self):
        deduction,receipt=review.confirm(self.folder,self.state,self.root,self.directory,self.payload())
        self.state.update(deductions=deduction,deduction_confirmation=receipt)
        self.folder.joinpath('manifest.json').write_text(json.dumps(self.state),encoding='utf-8')
        _,claimed,_=payroll_inputs.claim_calculation('shared','a'*32,None,deduction['version'],self.root)
        self.assertTrue(claimed['deductions']['frozen']);self.assertEqual(claimed['deductions']['rows'],deduction['rows'])
        self.assertEqual(claimed['deduction_confirmation'],receipt)


if __name__=='__main__':unittest.main()
