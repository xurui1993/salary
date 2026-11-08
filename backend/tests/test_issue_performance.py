"""Behavioral safeguards for issue-order performance changes."""
import datetime as dt
import gzip
import io
import json
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch
import pandas as pd
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from fengshen_bill import BillCollectionError
from generation_performance import profiled, public_profile
from issue_orders import MergePenaltyRecords
from order_metrics import measurements
import order_pipeline as pipeline
from order_pipeline import PreparedSlices, OrderCache, dump_frame, load_frame
from order_sources import file_hash, merge_slices
import test_fengshen_orders as fixture

class IssuePerformanceTests(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)

 def test_summary_keeps_rounding_boundaries_order_ids_and_inputs(self):
  values=[-15.5,-2.5,-1.5,-1,-.999,-.5,-.001,0,.001,.5,.999,1,1.5,2.5,15.5]
  source=pd.DataFrame([dict(fixture.waybill(str(i)),超时时长=value) for i,value in enumerate(values)])
  source['unneeded']='wide';before=source.copy(deep=True)
  result=MergePenaltyRecords.__new__(MergePenaltyRecords).build_sum_data({'超时':source,'T10':source,'欺诈单':pd.DataFrame([{'运单id':'2'}])})
  expected=[]
  for value in values:
   rounded=1 if 0<value<1 else -1 if -1<value<0 else round(value)
   expected.append(f'超时{rounded}分钟' if rounded>=1 else f'提前{abs(rounded)}分钟')
  self.assertEqual(result['事件原因'].tolist(),[r for i,r in enumerate(expected) if i!=2]*2)
  self.assertEqual(result['运单号'].tolist(),[str(i) for i in range(len(values)) if i!=2]*2)
  self.assertEqual(len(result.columns),8);pd.testing.assert_frame_equal(source,before)

 def test_duration_text_matches_legacy_negative_zero_and_long_hours(self):
  source=pd.DataFrame([dict(fixture.waybill(str(i)),超平台期望送达时长=value) for i,value in enumerate(['-00:00:01','00:00:00','26:01:02'])])
  result=MergePenaltyRecords.__new__(MergePenaltyRecords).build_sum_data({'不准时单':source})
  self.assertEqual(result['事件原因'].tolist(),['超平台T1秒','超平台T0秒','超平台T26小时1分钟2秒'])

 def test_block_roundtrip_preserves_types_long_ids_and_dates(self):
  frame=pd.DataFrame({'id':['000123456789012345678','0002'],'value':[1,1.25],'date':[dt.date(2026,10,1),dt.date(2026,10,2)],'timestamp':[dt.datetime(2026,10,1,2,3,4),dt.datetime(2026,10,2)],'flag':[True,False],'mixed':['',2]})
  path=self.root/'frame.gz';dump_frame(frame,path);pd.testing.assert_frame_equal(load_frame(path),frame)

 def test_multiple_blocks_and_legacy_rows_decode_identically(self):
  frame=pd.DataFrame({'id':[f'00{i}' for i in range(20003)],'value':range(20003)})
  new=io.BytesIO();pipeline._write_frame(frame,new)
  new.seek(0);pd.testing.assert_frame_equal(pipeline._read_frame(new),frame)
  legacy=io.BytesIO((json.dumps(list(frame.columns))+'\n'+''.join(json.dumps(row)+'\n' for row in frame.itertuples(index=False,name=None))).encode())
  pd.testing.assert_frame_equal(pipeline._read_frame(legacy),frame)

 def test_invalid_block_version_shape_and_columns_are_rejected(self):
  for value in ('{"format":"unknown","columns":[]}\n','["id","id"]\n','{"format":"orders-blocks-v1","columns":["id"]}\n[["x","y"]]\n','{"format":"orders-blocks-v1","columns":["id"]}\n{}\n'):
   with self.subTest(value=value),self.assertRaises(ValueError):pipeline._read_frame(io.BytesIO(value.encode()))

 def refs(self):
  path=self.root/'frame.gz';dump_frame(pd.DataFrame([fixture.waybill()]),path)
  return [{'files':{'waybills':str(path)},'hashes':{'waybills':file_hash(path)},'proof':{'start':'2026-08-16','end':'2026-08-20'}}]

 def test_lazy_receipts_do_not_decode_until_needed(self):
  refs=self.refs();instance=pipeline.OrderPipeline.__new__(pipeline.OrderPipeline);instance.references=refs;instance.include_violations=False
  with patch.object(pipeline,'load_frame',wraps=load_frame) as loader:
   lazy=instance.load_prepared();self.assertEqual(len(lazy),1);self.assertEqual(lazy.proof(0),refs[0]['proof']);loader.assert_not_called()
   self.assertEqual(len(lazy.merge('waybills')),1);self.assertEqual(loader.call_count,1)
  self.assertFalse(any(isinstance(value,pd.DataFrame) for value in vars(lazy).values()))

 def test_lazy_rechecks_tampered_spool_at_use(self):
  refs=self.refs();lazy=PreparedSlices(refs,False);Path(refs[0]['files']['waybills']).write_bytes(b'changed')
  with self.assertRaisesRegex(BillCollectionError,'完整性'):lazy.merge('waybills')

 def test_cancelled_lazy_read_and_block_decode_stop(self):
  refs=self.refs()
  def cancelled():raise BillCollectionError('任务已取消')
  with self.assertRaisesRegex(BillCollectionError,'取消'):PreparedSlices(refs,False,cancelled).merge('waybills')
  with self.assertRaisesRegex(BillCollectionError,'取消'):load_frame(refs[0]['files']['waybills'],checkpoint=cancelled)

 def test_duplicates_keep_first_but_conflicts_stop_across_batches(self):
  frame=pd.DataFrame([fixture.waybill()]);result=merge_slices([frame,frame.copy()],'运单id');self.assertEqual(len(result),1)
  with self.assertRaisesRegex(BillCollectionError,'冲突'):merge_slices([frame,pd.DataFrame([fixture.waybill(rider_id='different')])],'运单id')
  with self.assertRaisesRegex(BillCollectionError,'表头'):merge_slices([frame,frame.assign(new='x')],'运单id')

 def test_existing_legacy_cache_remains_usable(self):
  cache=OrderCache(self.root/'cache.sqlite',today='2026-10-25',clock=lambda:100000)
  frame=pd.DataFrame([dict(fixture.waybill(),运单完成时间='2026-10-01 10:00:00')])
  def old_writer(frame,stream):
   stream.write((json.dumps(list(frame.columns),ensure_ascii=False)+'\n').encode())
   for row in frame.itertuples(index=False,name=None):stream.write((json.dumps(row,ensure_ascii=False)+'\n').encode())
  with patch.object(pipeline,'_write_frame',old_writer):cache.put('2','2026-10-01','waybills',frame,99900,{})
  self.assertEqual(cache.get('2','2026-10-01','waybills')['运单id'].tolist(),frame['运单id'].tolist())

 def test_timings_return_from_worker_and_are_scoped(self):
  timings={}
  with measurements(timings):
   path=self.root/'frame.gz';dump_frame(pd.DataFrame({'id':['001']}),path);load_frame(path)
  self.assertGreater(timings['spool_write_seconds'],0);self.assertGreater(timings['spool_read_seconds'],0)
  before=dict(timings);load_frame(path);self.assertEqual(timings,before)

 def test_download_timer_preserves_single_download_call_and_result(self):
  from fengshen_http_reports import ReportHttpCollector
  from unittest.mock import Mock
  collector=ReportHttpCollector.__new__(ReportHttpCollector);collector.client=Mock();collector.client.download.return_value='result'
  timings={}
  with measurements(timings):self.assertEqual(collector._download_order_file('synthetic-url','synthetic-file'),'result')
  collector.client.download.assert_called_once_with('synthetic-url','synthetic-file')
  self.assertGreater(timings['source_download_seconds'],0)

 def test_task_profile_collects_problem_order_timings_without_paths(self):
  @profiled('download_task',0,'directory')
  def generate(directory):
   target=Path(directory)/'原始资料/合成城/order_processed';target.mkdir(parents=True)
   (target/'performance.json').write_text(json.dumps({'collection_seconds':2,'parser_seconds':1,'finalize_seconds':.5,'timings':{'summary_seconds':.1},'secret_path':'private'}),encoding='utf-8')
  generate(self.root);report=public_profile(self.root);self.assertEqual(report['order_pipelines'][0]['timings']['summary_seconds'],.1);self.assertNotIn('secret_path',str(report))

if __name__=='__main__':unittest.main()
