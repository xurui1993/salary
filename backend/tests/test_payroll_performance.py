"""Payroll output, isolation, integrity and responsive-claim regressions."""
from concurrent.futures import ThreadPoolExecutor
import datetime as dt
import json
from pathlib import Path
import sys,tempfile,threading,unittest
from unittest.mock import patch
import pandas as pd
from openpyxl import Workbook,load_workbook
sys.path[:0]=[str(Path(__file__).resolve().parents[1]),str(Path(__file__).resolve().parents[2]/'scripts')]
import payroll_performance as perf
import payroll_inputs as inputs
import parttime_source as source
from compare_generator_workbooks import workbook_contract
from fengshen_processor import _auto_fit_columns
import test_parttime_source as fixture

class PayrollPerformanceTests(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)
 def data(self,name='价格档案.xlsx'):
  path=self.root/name;book=Workbook();sheet=book.active;sheet.title='数据';sheet.append(['骑手ID','金额']);sheet.append(['000123456789012345678',2.5]);sheet.append(['0002',3]);book.save(path);book.close();return path
 def test_same_sheet_alias_reuses_immutable_frame_and_preserves_long_text_ids(self):
  path=self.data()
  with perf.calculation_context(self.root/'profile') as session:
   first=perf.read_excel(path,dtype=object);first.iloc[0,1]=999
   second=perf.read_excel(path,sheet_name='数据',dtype=object)
   self.assertEqual(second.iloc[0,1],2.5);self.assertEqual(second.iloc[0,0],'000123456789012345678');self.assertEqual(session.hits,1)
 def test_reader_options_and_contexts_never_share_mutable_results(self):
  path=self.data()
  with perf.calculation_context(self.root/'a') as first:
   one=perf.read_excel(path,nrows=1,dtype=object);two=perf.read_excel(path,dtype=object);self.assertEqual((len(one),len(two)),(1,2));self.assertEqual(first.hits,0)
  with perf.calculation_context(self.root/'b') as second:
   self.assertEqual(len(perf.read_excel(path,dtype=object)),2);self.assertEqual(second.hits,0)
 def test_verified_inputs_are_checked_even_when_frame_is_cached(self):
  path=self.data();expected=perf.digest(path)
  with perf.calculation_context(self.root/'profile',verified_inputs={str(path):expected}):
   perf.read_excel(path,dtype=object)
   book=load_workbook(path);book.active['B2']=9;book.save(path);book.close()
   with self.assertRaisesRegex(ValueError,'快照'):perf.read_excel(path,dtype=object)
 def test_budget_skips_retaining_large_frames_and_closes_workbooks(self):
  path=self.data()
  with perf.calculation_context(self.root/'profile',max_bytes=1) as session:
   perf.read_excel(path,dtype=object);self.assertEqual(session.bytes,0);self.assertFalse(session.frames)
  self.assertFalse(session.books)
 def test_template_date_formula_and_large_numeric_reads_match_original(self):
  path=self.data('工资-template.xlsx');book=load_workbook(path);sheet=book.active;sheet['C1']='日期';sheet['C2']=dt.datetime(2026,10,1);sheet['D1']='公式';sheet['D2']='=1+1';sheet['E1']='大数';sheet['E2']=123456789012345678;book.save(path);book.close()
  expected=pd.read_excel(path,dtype=object)
  with perf.calculation_context(self.root/'profile'):pd.testing.assert_frame_equal(perf.read_excel(path,dtype=object),expected)
 def test_non_template_complex_cells_and_large_numbers_use_original_engine(self):
  for number in (123456789012345678,dt.datetime(2026,10,1),'=1+1'):
   path=self.data();book=load_workbook(path);book.active['B2']=number;book.save(path);book.close()
   with perf.calculation_context(self.root/'profile') as session:
    pd.testing.assert_frame_equal(perf.read_excel(path,dtype=object),pd.read_excel(path,dtype=object));self.assertFalse(next(iter(session.native.values())))
 def test_csv_chunks_stay_streaming_and_options_do_not_collide(self):
  path=self.root/'价格档案.csv';pd.DataFrame({'id':['0001','0002'],'value':[1,2]}).to_csv(path,index=False)
  with perf.calculation_context(self.root/'profile') as session:
   reader=perf.read_csv(path,dtype=str,chunksize=1);self.assertEqual([len(frame) for frame in reader],[1,1]);reader.close();self.assertFalse(session.frames)
   first=perf.read_csv(path,dtype=str);first.loc[0,'id']='changed';self.assertEqual(perf.read_csv(path,dtype=str).loc[0,'id'],'0001');self.assertEqual(session.hits,1)
 def test_diagnostic_failures_do_not_mask_success_or_original_error(self):
  with patch('fengshen_bill.atomic_json',side_effect=OSError('diagnostics unavailable')):
   with perf.calculation_context(self.root/'ok'):pass
   with self.assertRaisesRegex(ValueError,'original failure'):
    with perf.calculation_context(self.root/'bad'):raise ValueError('original failure')
  self.assertIsNone(perf.current_session())
 def test_chunked_detail_write_keeps_values_types_widths_and_formats(self):
  frame=pd.DataFrame({'编号':['0001','0002','0003'],'中文':['短','很长的中文标题',None],'数值':[1.5,float('nan'),2],'日期':[dt.datetime(2026,10,1),None,dt.datetime(2026,10,3)],'公式':['=1+1',None,'=2+2']})
  first=Workbook();old=first.active;old.append(list(frame.columns));values=frame.astype(object);values[pd.isna(values)]=None
  for row in values.values.tolist():old.append(row)
  _auto_fit_columns(old);a=self.root/'a.xlsx';first.save(a);first.close()
  second=Workbook();new=second.active;new.append(list(frame.columns));perf.append_frame_rows(new,frame,chunk_rows=1);b=self.root/'b.xlsx';second.save(b);second.close()
  self.assertEqual(workbook_contract(a),workbook_contract(b))
 def test_plan_cache_is_scoped_and_rechecks_contents_and_city_mapping(self):
  path=self.data('template.xlsx');calls=[]
  loader=lambda:calls.append('loaded') or 'immutable-plan'
  for _ in range(2):self.assertEqual(perf.cached_plan(path,('city','1'),loader),'immutable-plan')
  self.assertEqual(len(calls),1);perf.cached_plan(path,('city','2'),loader);self.assertEqual(len(calls),2)
  other=self.root/'another';other.mkdir();other_path=other/path.name;other_path.write_bytes(path.read_bytes());perf.cached_plan(other_path,('city','1'),loader);self.assertEqual(len(calls),3)
  book=load_workbook(path);book.active['B2']=3;book.save(path);book.close();perf.cached_plan(path,('city','1'),loader);self.assertEqual(len(calls),4)
 def test_actual_payroll_stream_persists_timings_and_verified_result(self):
  import asyncio
  from types import SimpleNamespace
  from starlette.requests import Request
  import processor
  import test_optional_payroll_inputs as fixtures
  container=self.root/'uploads/scope/upload_synthetic';container.mkdir(parents=True)
  helper=fixtures.OptionalPayrollInputsTests();helper.root=container;upload=helper.fixture(False)
  folder,state=inputs.create(str(upload),'scope','manual',root=self.root)
  config=SimpleNamespace(payrollSourceMode='manual',payrollPreparationId=state['id'],basePath='',theme=fixtures.THEME,enableInterceptor=False,enableCrossStationMerge=False,preparationOnly=False)
  request=Request({'type':'http','method':'POST','scheme':'http','path':'/api/run','headers':[(b'host',b'localhost'),(b'x-workspace-id',b'scope')],'client':('127.0.0.1',1)})
  original=processor.process_rider_data
  def calculate(*args,**kwargs):
   self.assertIn(state['id'],kwargs['output_root']);return original(*args,**kwargs)
  async def collect():return [event async for event in inputs.run_payroll(config,request)]
  rules={'rows':[{'城市':'测试城市','团队名称':'测试站','团队ID':'T001'}],'version':'synthetic','frozen':True}
  with patch.object(inputs,'ROOT',self.root),patch.object(processor,'process_rider_data',calculate),patch('workbench.deduction_snapshot',return_value=rules):events=asyncio.run(collect())
  fresh=inputs.load('scope',state['id'],root=self.root)[1]
  self.assertEqual(fresh['status'],'calculated');self.assertTrue(fresh['result']['input_hashes_verified'])
  self.assertGreater(fresh['performance']['stages']['read_excel_seconds'],0);self.assertEqual(fresh['performance']['status'],'success')
  self.assertTrue(any('payroll_stage' in event for event in events));self.assertTrue((folder/'payroll_performance.json').is_file())
 def test_upload_diagnostics_are_bounded_and_do_not_become_business_inputs(self):
  file=self.root/'.upload_diagnostics.json';file.write_text(json.dumps({'server_seconds':1,'extraction_seconds':.2,'secret':'omitted','indexing_seconds':-1}),encoding='utf-8')
  self.assertEqual(inputs.read_upload_timing(self.root),{'server_seconds':1,'extraction_seconds':.2})
  file.write_bytes(b'x'*17000);self.assertEqual(inputs.read_upload_timing(self.root),{})
 def claim_state(self,key):
  folder=inputs.directory('scope',key,root=self.root);(folder/'input').mkdir(parents=True);path=folder/'input/template.xlsx';path.write_bytes(b'synthetic')
  state={'id':key,'mode':'manual','status':'ready','plan':{'template':'template.xlsx'},'template_hash':inputs.digest(path),'items':{},'jobs':[]}
  inputs.save(folder,state);return folder,state
 def test_hashing_does_not_hold_global_lock_or_block_other_batches(self):
  one,two='1'*32,'2'*32;self.claim_state(one);self.claim_state(two);entered=threading.Event();release=threading.Event();original=inputs.checked_inputs
  def slow(folder,state):
   if state['id']==one:entered.set();self.assertTrue(release.wait(5))
   return original(folder,state)
  with patch.object(inputs,'checked_inputs',side_effect=slow),patch('workbench.deduction_snapshot',return_value={'rows':[],'version':'v','frozen':True}),ThreadPoolExecutor(2) as pool:
   first=pool.submit(inputs.claim_calculation,'scope',one,None,'',self.root)
   self.assertTrue(entered.wait(3));acquired=inputs.LOCK.acquire(blocking=False);self.assertTrue(acquired)
   if acquired:inputs.LOCK.release()
   second=pool.submit(inputs.claim_calculation,'scope',two,None,'',self.root)
   try:self.assertEqual(second.result(timeout=3)[1]['status'],'calculating')
   finally:release.set()
   self.assertEqual(first.result(timeout=3)[1]['status'],'calculating')
 def test_state_change_during_hashing_does_not_overwrite_new_configuration(self):
  folder,state=self.claim_state('3'*32);original=inputs.checked_inputs
  def change(folder,value):
   result=original(folder,value);fresh=dict(value);fresh['deductions']={'version':'changed'};inputs.save(folder,fresh);return result
  with patch.object(inputs,'checked_inputs',side_effect=change):
   with self.assertRaisesRegex(source.SourceError,'发生变化'):inputs.claim_calculation('scope',state['id'],None,root=self.root)
  self.assertEqual(inputs.load('scope',state['id'],root=self.root)[1]['status'],'ready')
 def test_duplicate_claim_is_rejected_and_keeps_frozen_configuration(self):
  folder,state=self.claim_state('4'*32)
  with patch('workbench.deduction_snapshot',return_value={'rows':[],'version':'v','frozen':True}):
   first=inputs.claim_calculation('scope',state['id'],None,root=self.root)
   with self.assertRaisesRegex(source.SourceError,'正在核算'):inputs.claim_calculation('scope',state['id'],None,root=self.root)
  self.assertEqual(inputs.load('scope',state['id'],root=self.root)[1]['deductions'],first[1]['deductions'])
 def test_identical_snapshot_paths_are_hashed_once_but_conflicts_stop(self):
  folder,state=self.claim_state('5'*32);state['all_files']=[{'file':'template.xlsx','sha256':state['template_hash']}];state['items']={'same':{'status':'ready','file':'template.xlsx','sha256':state['template_hash']}}
  with patch.object(inputs,'digest',wraps=inputs.digest) as reader:inputs.checked_inputs(folder,state);self.assertEqual(reader.call_count,1)
  state['items']['same']['sha256']='changed'
  with self.assertRaisesRegex(source.SourceError,'冲突'):inputs.checked_inputs(folder,state)
if __name__=='__main__':unittest.main()
