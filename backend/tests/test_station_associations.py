"""Synthetic batch reviews: matching, reuse, isolation and immutable input evidence."""
import asyncio
import copy
import json
from unittest import TestCase
from unittest.mock import patch

from fastapi import HTTPException
from openpyxl import load_workbook
import deduction_confirmation as review
import payroll_inputs
import station_associations as associations
import workbench
from parttime_source import SourceError
import test_deduction_confirmation as fixtures


class AssociationTests(TestCase):
    setUp = fixtures.ConfirmationTests.setUp
    bill = fixtures.ConfirmationTests.bill
    sha = fixtures.ConfirmationTests.sha
    read = fixtures.ConfirmationTests.read
    payload = fixtures.ConfirmationTests.payload

    def application(self, name, code=''):
        book = load_workbook(self.input/'template.xlsx')
        sheet = book['申请名单']; sheet['B2'] = name
        if code: sheet['D1'] = '团队ID'; sheet['D2'] = code
        book.save(self.input/'template.xlsx'); book.close()
        self.state['template_hash'] = self.sha('template.xlsx')

    def route(self, body):
        self.state['download_owner'] = None
        payroll_inputs.save(self.folder, self.state)
        class Request:
            async def json(inner): return body
        with patch.object(workbench,'ROOT',self.root),patch.object(payroll_inputs,'ROOT',self.root),patch('download_accounts.require_admin'),patch('payroll_inputs.workspace',return_value='shared'),patch('payroll_inputs.account',return_value=None),patch('station_directory.ready_directory',return_value=self.directory):
            result = asyncio.run(workbench.link_batch_stations('a'*32, Request()))
        self.state = payroll_inputs.load('shared','a'*32,None,self.root)[1]
        return result

    def test_explicit_id_resolves_changed_name_and_keeps_alias_rule(self):
        self.application('申请中的旧名称', '0001')
        data = self.read()
        self.assertFalse(data['unresolved']); self.assertFalse(data['differences'])
        row = next(r for r in data['association_rows'] if r['name']=='申请中的旧名称')
        self.assertEqual(row['method'], 'id')
        deduction,_ = review.confirm(self.folder,self.state,self.root,self.directory,self.payload(data))
        self.assertEqual({r['团队名称'] for r in deduction['rows']}, {'一站','申请中的旧名称'})
        self.assertEqual({r['团队ID'] for r in deduction['rows']}, {'0001'})

    def test_name_recommendation_never_grants_readiness_without_confirmation(self):
        self.bill('同泰时代站')
        self.directory['stations'][0]['name']='同泰时代站'
        self.application('测试城-同泰时代_新专送')
        data = self.read()
        self.assertEqual(len(data['unresolved']), 1)
        self.assertTrue(data['unresolved'][0]['recommendations'])
        with self.assertRaisesRegex(SourceError,'尚未匹配'):
            review.confirm(self.folder,self.state,self.root,self.directory,self.payload(data))

    def test_confirmed_alias_is_reused_across_batches_and_input_and_amounts_stay_intact(self):
        self.application('历史别名')
        original = (self.input/'template.xlsx').read_bytes()
        data = self.read(); key = review.station_key(self.directory['stations'][0])
        result = self.route({'confirmed':True,'links':{'历史别名':key},'review_version':data['review_version'],'save_associations':True})
        self.assertFalse(result['unresolved'])
        self.assertTrue(self.state['audit'][-1]['saved_for_reuse'])
        self.state.pop('station_links')
        again = self.read()
        self.assertFalse(again['unresolved'])
        self.assertEqual(next(r for r in again['association_rows'] if r['name']=='历史别名')['method'],'history')
        deduction,_ = review.confirm(self.folder,self.state,self.root,self.directory,self.payload(again))
        self.assertTrue(all(r['团队ID']=='0001' and r['安全基金']==10 for r in deduction['rows']))
        self.assertEqual((self.input/'template.xlsx').read_bytes(), original)
        self.assertEqual(json.loads((self.root/'data/config.json').read_text()), self.legacy)

    def test_history_is_account_city_and_type_scoped_and_missing_target_does_not_auto_resolve(self):
        self.application('别名')
        entry=self.read()['station_choices'][0]
        saved=associations.load(self.root,'fengshen')
        associations.save(self.root,'fengshen',self.directory,{'别名':entry},saved['version'])
        self.assertFalse(self.read()['unresolved'])
        for field,value in [('session_version','other-account')]:
            changed=copy.deepcopy(self.directory);changed[field]=value
            self.assertTrue(review.preflight(self.folder,self.state,self.root,changed)['unresolved'])
        changed=copy.deepcopy(self.directory);changed['stations'][0]['city_id']='other-city-id'
        self.assertTrue(review.preflight(self.folder,self.state,self.root,changed)['unresolved'])
        self.directory['stations'][0]['separation']=True
        data=self.read(); self.assertTrue(data['unresolved'])
        self.assertNotIn(entry['key'], data['unresolved'][0]['candidates'])
        self.assertEqual(associations.load(self.root,'xiaoxiang')['entries'],{})

    def test_stable_official_account_reuses_after_relogin_and_history_change_is_reversible(self):
        self.directory['account_scope']=associations.identity_scope({'userId':'user-a','companyId':'company'},'s1')
        self.application('别名');entry=self.read()['station_choices'][0]
        associations.save(self.root,'fengshen',self.directory,{'别名':entry},associations.load(self.root,'fengshen')['version'])
        self.directory['session_version']='relogin'
        self.assertFalse(self.read()['unresolved'])
        other=self.read()['station_choices'][1]
        associations.save(self.root,'fengshen',self.directory,{'别名':other},associations.load(self.root,'fengshen')['version'])
        self.assertEqual(next(r for r in self.read()['association_rows'] if r['name']=='别名')['key'],other['key'])
        self.assertEqual(len(list((self.root/'data/station_associations/history').glob('*.json'))),1)
        self.directory['account_scope']=associations.identity_scope({'userId':'user-b','companyId':'company'},'s1')
        self.assertTrue(self.read()['unresolved'])

    def test_type_and_explicit_id_conflicts_cannot_be_confirmed_or_partially_saved(self):
        self.application('一站(取分离)', '0001')
        data=self.read(); self.assertTrue(data['unresolved'])
        key=review.station_key(self.directory['stations'][0])
        with self.assertRaises(HTTPException):
            self.route({'confirmed':True,'links':{'一站(取分离)':key},'review_version':data['review_version'],'save_associations':True})
        self.assertFalse(associations.load(self.root,'fengshen')['entries'])
        self.application('别名', '0002');data=self.read()
        self.assertEqual(next(r for r in data['association_rows'] if r['name']=='别名')['key'],review.station_key(self.directory['stations'][1]))
        with self.assertRaises(HTTPException):
            self.route({'confirmed':True,'links':{'别名':key},'review_version':data['review_version'],'save_associations':True})

    def test_stale_concurrent_alias_confirmation_is_rejected(self):
        self.application('别名');data=self.read();key=data['station_choices'][0]['key']
        associations.save(self.root,'fengshen',self.directory,{'另一个别名':data['station_choices'][0]},data['association_version'])
        with self.assertRaises(HTTPException):
            self.route({'confirmed':True,'links':{'别名':key},'review_version':data['review_version'],'save_associations':True})
        self.assertNotIn('station_links', self.state)

    def test_batch_only_choice_does_not_write_history(self):
        self.application('别名');data=self.read();key=data['station_choices'][0]['key']
        result=self.route({'confirmed':True,'links':{'别名':key},'review_version':data['review_version'],'save_associations':False})
        self.assertFalse(result['unresolved']);self.assertFalse(associations.load(self.root,'fengshen')['entries'])

    def test_scope_never_uses_switchable_city_and_unidentified_account_is_session_bound(self):
        self.assertEqual(associations.identity_scope({'userId':'u','agencyId':'1'},'s1'),associations.identity_scope({'userId':'u','agencyId':'2'},'s2'))
        self.assertNotEqual(associations.identity_scope({'agencyId':'1'},'s1'),associations.identity_scope({'agencyId':'1'},'s2'))
        self.assertNotEqual(associations.identity_scope({'userId':'u','companyId':'1'},'s1'),associations.identity_scope({'userId':'u','companyId':'2'},'s1'))

    def test_deleted_historical_id_cannot_silently_remap_to_same_name_new_id(self):
        data=self.read();associations.save(self.root,'fengshen',self.directory,{'一站':data['station_choices'][0]},data['association_version'])
        self.directory['stations']=[{**self.directory['stations'][0],'id':'new-official-id'}]
        data=self.read();self.assertEqual(data['unresolved'][0]['code'],'history_invalid')
        with self.assertRaises(SourceError):
            review.confirm(self.folder,self.state,self.root,self.directory,self.payload(data))

    def test_history_swap_after_amount_confirmation_cannot_change_frozen_alias_rules(self):
        self.application('别名A')
        book=load_workbook(self.input/'template.xlsx');book['申请名单'].append(['测试城','别名B','00002']);book.save(self.input/'template.xlsx');book.close()
        self.state.update(template_hash=self.sha('template.xlsx'),mode='fengshen',status='awaiting_confirmation')
        self.state['items']['delivery_fee']={'status':'pending'}
        entries=self.read()['station_choices'];saved=associations.load(self.root,'fengshen')
        associations.save(self.root,'fengshen',self.directory,{'别名A':entries[0],'别名B':entries[1]},saved['version'])
        data=self.read();body=self.payload(data)
        for entry in body['entries']:entry['row']['安全基金']=10
        deduction,receipt=review.confirm(self.folder,self.state,self.root,self.directory,body)
        self.state.update(deductions=deduction,deduction_intent=receipt,status='ready')
        associations.save(self.root,'fengshen',self.directory,{'别名A':entries[1],'别名B':entries[0]},associations.load(self.root,'fengshen')['version'])
        (self.input/'bill.csv').write_text('骑手ID,团队名称,日期\n00001,二站,2026-10-01\n00002,一站,2026-10-01\n',encoding='utf-8-sig')
        self.state['items']['delivery_fee']={'status':'ready','file':'bill.csv','sha256':self.sha('bill.csv')}
        self.state['items']['payment_binding']={'status':'ready','file':'bill.csv','sha256':self.sha('bill.csv')}
        with self.assertRaisesRegex(SourceError,'站点关联已变化'):
            review.finalize_intent(self.folder,self.state,self.root,self.directory)
