from pathlib import Path
import sys, tempfile, threading, unittest
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch
import pandas as pd
from openpyxl import Workbook
sys.path[:0]=[str(Path(__file__).parents[1]),str(Path(__file__).parents[2]/'scripts')]
from generation_performance import SourceCache, generation_context, profiled, read_frame, public_profile
from separation_filter import filter_table, _legacy_filter_xlsx
from compare_generator_workbooks import workbook_contract

class BindingPerformanceTuningTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
    def tearDown(self): self.temp.cleanup()
    def frame(self):
        return pd.DataFrame({'身份证号':['00000000000000000X']*250,'状态':['已签约']*250,'说明':(['NA','nan','', '中文,引号"\n换行\r回车']*63)[:250]})
    def test_large_string_frame_roundtrip_and_mutation_isolation(self):
        p=self.root/'source';p.write_text('original');calls=[];frame=self.frame()
        cache=SourceCache(max_bytes=8192,spill_frames=True)
        try:
            def load(_):calls.append(1);return frame.copy(deep=True)
            a=cache.read(p,load);pd.testing.assert_frame_equal(a,frame);a.iloc[0,0]='changed'
            pd.testing.assert_frame_equal(cache.read(p,load),frame)
            self.assertEqual(len(calls),1);self.assertEqual(cache.summary()['spill_files'],1)
            self.assertLessEqual(cache.summary()['spill_bytes'],cache.spill_limit)
            directory=Path(cache.spill_directory.name)
        finally:cache.close()
        self.assertFalse(directory.exists())
    def test_cache_tampering_is_blocked_without_reparsing_source(self):
        p=self.root/'source';p.write_text('original');cache=SourceCache(max_bytes=8192,spill_frames=True)
        try:
            cache.read(p,lambda _:self.frame())
            next(Path(cache.spill_directory.name).glob('*.csv')).write_text('tampered')
            with self.assertRaisesRegex(ValueError,'缓存已变化'):cache.read(p,lambda _:self.fail('no silent reparse'))
        finally:cache.close()
    def test_budget_and_unsupported_values_fall_back_without_changing_data(self):
        p=self.root/'source';p.write_text('original')
        for frame,budget in [(self.frame(),0),(pd.DataFrame({'text':['a\x00b']*500}),1000000),(pd.DataFrame({'number':list(range(5000))}),1000000)]:
            cache=SourceCache(max_bytes=8192,spill_frames=True,spill_max_bytes=budget)
            try:
                pd.testing.assert_frame_equal(cache.read(p,lambda _:frame),frame)
                self.assertEqual(cache.summary()['spill_files'],0)
            finally:cache.close()
    def test_parallel_reads_create_only_one_spill_and_task_boundary_isolated(self):
        p=self.root/'source';p.write_text('original');frame=self.frame();calls=[]
        cache=SourceCache(max_bytes=8192,spill_frames=True)
        try:
            def load(_):calls.append(1);return frame.copy(deep=True)
            with ThreadPoolExecutor(max_workers=3) as pool:
                results=list(pool.map(lambda _:cache.read(p,load),range(3)))
            for result in results:pd.testing.assert_frame_equal(result,frame)
            self.assertEqual(len(calls),1);self.assertEqual(cache.summary()['spill_files'],1)
            other=SourceCache(max_bytes=8192,spill_frames=True)
            try:other.read(p,load)
            finally:other.close()
            self.assertEqual(len(calls),2)
        finally:cache.close()
    def test_profile_owner_cleans_temporary_cache_on_failure(self):
        p=self.root/'source';p.write_text('original');cache=SourceCache(max_bytes=8192,spill_frames=True)
        @profiled('download_task',0,'directory')
        def fail(directory):
            read_frame(p,lambda _:self.frame());raise RuntimeError('original error')
        with patch('generation_performance.SourceCache',return_value=cache), self.assertRaisesRegex(RuntimeError,'original error'):
            fail(self.root/'profile')
        self.assertIsNone(cache.spill_directory)
        self.assertTrue(public_profile(self.root/'profile')['failed'])
    def test_stream_filter_retains_full_contract_and_wide_column_fallback(self):
        for wide in [False,True]:
            with self.subTest(wide=wide):
                p=self.root/('wide.xlsx' if wide else 'ordinary.xlsx');book=Workbook();s=book.active
                s.append(['说明']);s.append(['骑手ID','部门','备注']);s.append(['0001','普通站','=原始文字'])
                s.cell(3,3).data_type='s';s.append(['0002','取分离站','保留原始行序'])
                if wide:s.cell(3,5,'额外原始字段')
                book.save(p);book.close()
                expected,proof=_legacy_filter_xlsx(p,'部门',False,self.root)
                actual,other=filter_table(p,'rider_info',False,self.root)
                self.assertEqual(proof,other)
                self.assertEqual(workbook_contract(expected),workbook_contract(actual))
                self.assertEqual(len(list(self.root.glob('.取分离_*.xlsx'))),2)
                expected.unlink();actual.unlink()

    def test_unwritable_temp_falls_back_to_original_parser(self):
        p=self.root/'source';p.write_text('original');cache=SourceCache(max_bytes=8192,spill_frames=True);frame=self.frame()
        with patch('generation_performance.tempfile.TemporaryDirectory',side_effect=PermissionError('temporary directory denied')):
            pd.testing.assert_frame_equal(cache.read(p,lambda _:frame),frame)
        self.assertEqual(cache.spill_reserved,0);cache.close()
    def test_mutation_while_reading_spill_is_detected(self):
        p=self.root/'source';p.write_text('original');cache=SourceCache(max_bytes=8192,spill_frames=True)
        try:
            cache.read(p,lambda _:self.frame());artifact=next(Path(cache.spill_directory.name).glob('*.csv'));original=pd.read_csv
            def changed(*args,**kwargs):
                result=original(*args,**kwargs);artifact.write_text('changed');return result
            with patch.object(pd,'read_csv',side_effect=changed),self.assertRaisesRegex(ValueError,'读取期间发生变化'):
                cache.read(p,lambda _:self.fail('no source reparse'))
        finally:cache.close()
    def test_real_binding_generator_keeps_every_sheet_field_value_and_style(self):
        import csv
        from types import SimpleNamespace
        from binding_download import generate_binding
        import test_salary_bind_sources as fixtures
        from test_shangyi_sources import HEADERS,ROW
        fixture=fixtures.BindingSourceTests();fixture.root=self.root;fixture.scope={'month':'2026-07','start':'2026-07-01','end':'2026-07-29'}
        sources,employees=fixture.fixture();employee=employees[0]/'merchantFreelancer.xlsx'
        book=Workbook();book.active.append(HEADERS)
        for i in range(100):
            row=ROW.copy();row[-1]='https://example.invalid/合成图片/'+str(i)+'x'*100;book.active.append(row)
        book.save(employee);book.close()
        from test_binding_download import proxy
        proxies=self.root/'proxy.csv'
        with proxies.open('w',encoding='utf-8-sig',newline='') as stream:csv.DictWriter(stream,fieldnames=list(proxy())).writeheader()
        paths={kind:sources[0][0]/info['path'] for kind,info in sources[0][1]['datasets'].items()};plan=SimpleNamespace(city='泉州',agency_id='31029436',**fixture.scope)
        results=[]
        for enabled in [False,True]:
            cache=SourceCache(max_bytes=8192,spill_frames=enabled);raw=self.root/str(enabled);raw.mkdir()
            try:
                with generation_context(cache):
                    output,stats=generate_binding(paths,employee,proxies,plan,raw,lambda *_:None,threading.Event())
                results.append((workbook_contract(output),stats))
                if enabled:self.assertGreater(cache.summary()['spill_files'],0)
            finally:cache.close()
        self.assertEqual(results[0],results[1])

    def test_summary_compression_retains_all_content_and_styles(self):
        from binding_summary import build_binding_summaries
        from test_binding_summary import BindingSummaryTests,city_output
        from download_jobs import _initial_items
        from workbook_policy import compression
        config=BindingSummaryTests().config();items=[{**item,'status':'success'} for item in _initial_items(config)];contracts=[]
        for level in [9,6]:
            root=self.root/str(level);root.mkdir();files=[city_output(root,item) for item in items]
            with patch('binding_summary.compression',side_effect=lambda ignored,level=level:compression(level)):
                summaries=build_binding_summaries(root,config,files,items,threading.Event())
            contracts.append(workbook_contract(root/summaries[0]['relative_path']))
        self.assertEqual(contracts[0],contracts[1])
