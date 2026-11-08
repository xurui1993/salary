"""Daily-query integration boundaries, with synthetic rows and no live login."""
import datetime as dt
import json
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch

from openpyxl import load_workbook
from fastapi import HTTPException
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import download_service as service
import xiaoxiang_board as board
import xiaoxiang_lighthouse as lighthouse
from xiaoxiang_source_auth import AUTH, XiangAuth
from test_xiaoxiang_board import METAS, ROWS, api_response, FAKE_STATE


class DailyIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(dir=Path(__file__).parent);self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)

    def test_text_dimensions_long_zero_prefixed_ids_and_formula_like_names_are_literal(self):
        row={**ROWS[0], 'rider_id':'00123456789012345678','rider_name':'=1+1'}
        p=self.root/'daily.xlsx';board.write_workbook({'rows':[row],'metas':METAS},p)
        b=load_workbook(p);self.addCleanup(b.close)
        self.assertEqual(b.active['A2'].value,row['rider_id']);self.assertEqual(b.active['A2'].data_type,'s')
        self.assertEqual(b.active['B2'].value,'=1+1');self.assertEqual(b.active['B2'].data_type,'s')
        self.assertEqual(b.active['D2'].value,50)

    def test_cancel_during_writing_preserves_previous_file_and_cleans_partial(self):
        p=self.root/'daily.xlsx';p.write_bytes(b'previous synthetic result')
        cancelled=Mock();cancelled.is_set.side_effect=[False,False,True]
        with self.assertRaises(lighthouse.LighthouseError):
            board.write_workbook({'rows':ROWS,'metas':METAS},p,cancelled)
        self.assertEqual(p.read_bytes(),b'previous synthetic result');self.assertEqual(list(self.root.glob('.daily_*')),[])

    def test_precision_risky_numeric_ids_are_blocked(self):
        with self.assertRaisesRegex(lighthouse.LighthouseError,'精度风险'):
            board.write_workbook({'rows':[{**ROWS[0],'rider_id':1e18}],'metas':METAS},self.root/'bad.xlsx')
        self.assertFalse((self.root/'bad.xlsx').exists())

    def test_malformed_rows_duplicate_fields_and_partial_page_are_not_silently_published(self):
        for data in [ {'data':ROWS+[None],'metas':METAS,'total':3},
                      {'data':ROWS,'metas':METAS+METAS[:1],'total':2},
                      {'data':ROWS,'metas':METAS,'total':3},
                      {'data':ROWS,'metas':METAS,'total':True} ]:
            s=Mock();s.post.return_value=api_response({'code':0,'data':data})
            with self.subTest(data=data),self.assertRaises(lighthouse.LighthouseError):
                board.query_rider_daily(s,dt.date(2026,10,25))

    def test_cancel_before_query_never_calls_platform(self):
        e=threading.Event();e.set()
        with patch.object(lighthouse,'load_state',return_value=FAKE_STATE),patch.object(board,'query_rider_daily') as query:
            with self.assertRaisesRegex(lighthouse.LighthouseError,'取消'):
                board.generate_rider_daily('2026-10-25',self.root,cancelled=e)
        query.assert_not_called()

    def test_session_expiry_is_exposed_to_system_connections_without_starting_login(self):
        with patch.object(lighthouse,'load_state',return_value=FAKE_STATE),patch.object(board,'query_rider_daily',side_effect=lighthouse.SessionExpired('expired')),patch.object(AUTH,'start') as start:
            with self.assertRaises(lighthouse.SessionExpired):board.generate_rider_daily('2026-10-25',self.root)
        self.assertEqual(AUTH.status()['state'],'login_required');start.assert_not_called()

    def test_real_service_failure_is_retryable_readonly_query_and_never_opens_fengshen(self):
        config=service.validate_request({'datasets':['rider_daily']},today=dt.date(2026,10,26));updates=[]
        with patch.object(board,'generate_rider_daily',side_effect=lighthouse.SessionExpired('expired')):
            result=service.execute_downloads(config,self.root,lambda *_:None,threading.Event(),updates.append,
                                            runner_factory=lambda *_:self.fail('unexpected Fengshen login'))
        self.assertEqual(result,[])
        failure=next(u for u in updates if u.get('status')=='error')
        self.assertEqual(failure['submission_state'],'not_submitted')

    def test_authentication_start_is_admin_only_and_status_has_no_login_side_effect(self):
        import binding_source_auth as routes
        with patch.object(routes,'require_admin',side_effect=HTTPException(403,'forbidden')),patch.object(AUTH,'start') as start:
            with self.assertRaises(HTTPException) as exc:routes.start('xiaoxiang',Mock())
        self.assertEqual(exc.exception.status_code,403);start.assert_not_called()
        instance=XiangAuth()
        with patch.object(instance,'_login') as login:
            instance.status();login.assert_not_called()

    def test_lighthouse_queue_runs_each_item_and_keeps_other_results_after_one_failure(self):
        from openpyxl import Workbook
        config=service.validate_request({'datasets':['detail_orders','rider_daily']},today=dt.date(2026,10,31))
        def fake_detail(kind,start,end,directory,log=None,cancelled=None):
            target=Path(directory)/'2026-10-30配送订单明细.xlsx'
            book=Workbook();book.active['A1']='synthetic';book.save(target);return target
        updates=[]
        with patch.object(board,'generate_rider_daily',side_effect=lighthouse.LighthouseError('synthetic failure')), \
                patch.object(board,'generate_detail',side_effect=fake_detail):
            result=service.execute_downloads(config,self.root,lambda *_:None,threading.Event(),updates.append,
                                             runner_factory=lambda *_:self.fail('unexpected Fengshen login'))
        self.assertEqual([entry['dataset'] for entry in result],['detail_orders'])
        self.assertEqual(result[0]['name'],'2026-10-30配送订单明细.xlsx')
        statuses={entry['dataset']:entry['status'] for entry in updates
                  if entry.get('dataset') in ('rider_daily','detail_orders')}
        self.assertEqual(statuses,{'rider_daily':'error','detail_orders':'success'})

    def test_default_yesterday_is_correct_across_year_boundary_and_never_joins_payroll(self):
        config=service.validate_request({'datasets':['rider_daily']},today=dt.date(2027,1,1))
        self.assertEqual((config['start'],config['end'],config['months']),('2026-12-31','2026-12-31',['2026-12']))
        with self.assertRaises(service.ValidationError):
            service.validate_request({'task_kind':'generate','generation_target':'rider_daily','datasets':['rider_daily']})
