"""Output-contract and cooperative scheduling regression, using synthetic data."""
import hashlib
import datetime as dt
import json
import shutil
from pathlib import Path
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from openpyxl import load_workbook
import abnormal_riders as ar
import rider_archive as ra
import download_jobs as jobs
from download_pipeline import PipelineTurn, pipeline_scope, release_collection_for_local_work
from fengshen_bill import BillCollectionError
from test_rider_archive import build_source, source_row
import test_abnormal_riders as abnormal_fixture
from test_download_jobs import CONFIG, make_file


def contract(path):
    b = load_workbook(path, data_only=False)
    try:
        return [(s.title, s.freeze_panes, [(k, v.width) for k, v in s.column_dimensions.items()],
                 [[(c.value, c.data_type, c.number_format, str(c.font), str(c.alignment)) for c in row] for row in s]) for s in b]
    finally:
        b.close()


class AnomalyPerformanceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=Path(__file__).parent)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def test_compact_archive_matches_cell_path_including_dates_text_formulas_and_order(self):
        source = self.root/'source.xlsx'
        rows = [source_row('合成甲', '饿了么', '三亚市'), source_row('合成乙', 'U+B', '泉州市'),
                source_row('合成丙', None, '其他'), source_row('合成丁', '饿了么', '三亚市')]
        build_source(source, rows)
        b=load_workbook(source)
        b['骑手档案'].cell(2, 6, '001234567890123456')
        b['骑手档案'].cell(2, 14, '=literal').data_type='s'
        b['骑手档案'].cell(3, 14, '=1+1')
        b.save(source);b.close()
        digest=hashlib.sha256(source.read_bytes()).hexdigest()
        original=ra.read_archive
        a,_=ra.format_full_workbook(source,self.root)
        with patch.object(ra, 'read_archive', side_effect=lambda *args, **kw: original(*args, **{**kw,'compact':False})), patch.object(ra, 'prepared_write_only_rows'):
            b,_=ra.format_full_workbook(source,self.root)
        self.assertEqual(contract(a),contract(b))
        self.assertEqual(hashlib.sha256(source.read_bytes()).hexdigest(),digest)

    def test_city_matcher_preserves_exact_longest_unknown_and_blank_rules(self):
        catalog={'北京专站':'北京','北京海淀专站':'北京海淀','测试':'其他城市'}
        resolve=ar._city_matcher(catalog)
        for team in ['北京专站','北京海淀外部站','不匹配','其他团队','未知团队',None,' 北京专站 ']:
            self.assertEqual(resolve(team), ar.match_city(team,catalog))

    def test_streamed_output_matches_eager_rows_and_preserves_duplicate_remarks(self):
        fixture=abnormal_fixture.AbnormalRidersTests();fixture.root=self.root
        sources=fixture.sources()
        output=ar.generate_abnormal_riders(*sources,self.root/'stream')
        original=ar._write_sheet
        with patch.object(ar, '_write_sheet', side_effect=lambda book,title,fields,widths,rows,*args,**kw: original(book,title,fields,widths,list(rows),*args,**kw)), patch.object(ar, 'prepared_write_only_rows'):
            eager=ar.generate_abnormal_riders(*sources,self.root/'eager')
        self.assertEqual(contract(output),contract(eager))

    def test_cancelled_local_wait_never_hands_off_or_releases_another_turns_lock(self):
        gate=threading.Lock();gate.acquire();event=threading.Event();event.set();calls=[]
        with self.assertRaises(BillCollectionError):
            with pipeline_scope(PipelineTurn(gate,lambda:calls.append(True),event)):
                release_collection_for_local_work()
        self.assertEqual(calls,[]);self.assertFalse(gate.acquire(blocking=False));gate.release()

    def test_handoff_is_once_and_original_failure_releases_gate(self):
        gate=threading.Lock();calls=[]
        with self.assertRaisesRegex(ValueError,'original'):
            with pipeline_scope(PipelineTurn(gate,lambda:calls.append(True),threading.Event())):
                release_collection_for_local_work();release_collection_for_local_work()
                raise ValueError('original')
        self.assertEqual(calls,[True]);self.assertTrue(gate.acquire(blocking=False));gate.release()

    def test_real_service_handoff_occurs_after_five_sources_and_never_collects_again(self):
        import download_service as service
        fixture=abnormal_fixture.AbnormalRidersTests();fixture.root=self.root
        sources=fixture.sources()
        names=['lanorange_batch_quit','lanorange_rider_quit','lanorange_rider_report',
               'lanorange_rider_leave','lanorange_rider_archive']
        mapping=dict(zip(names,sources));collected=[];handoffs=[];run_dir=self.root/'run'
        def collect(kind,directory,*args,**kwargs):
            self.assertFalse(handoffs)
            directory=Path(directory);directory.mkdir(parents=True,exist_ok=True)
            output=directory/'source.xlsx';shutil.copyfile(mapping[kind],output)
            (directory/'source_receipt.json').write_text(json.dumps({'delivery_kind':'platform_original'}),'utf-8')
            collected.append(kind);return output
        def handoff():
            self.assertEqual(set(collected),set(names))
            manifest=json.loads((run_dir/'manifest.json').read_text('utf-8'))
            self.assertEqual(len(manifest['files']),5)
            for item in manifest['files']:
                self.assertEqual(hashlib.sha256((run_dir/item['relative_path']).read_bytes()).hexdigest(),item['sha256'])
            handoffs.append(True)
        cancelled=threading.Event();turn=PipelineTurn(threading.Lock(),handoff,cancelled)
        config=service.validate_request({'datasets':['abnormal_riders']},today=dt.date(2026,10,26))
        with patch('lanorange_full.collect_full',side_effect=collect), pipeline_scope(turn):
            files=service.execute_downloads({**config,'owner':'synthetic','archive_created_at':'2026-10-26T00:00:00+00:00'},
                  run_dir,lambda *_:None,cancelled,lambda *_:None,
                  runner_factory=lambda *_:self.fail('unexpected Fengshen login'))
        self.assertEqual(handoffs,[True]);self.assertEqual(len(files),6)


class PipelineManagerTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(dir=Path(__file__).parent)
        self.root=Path(self.temp.name);self.managers=[];self.releases=[]
        self.catalog=patch.object(jobs,'_configured_cities',return_value={'泉州':'31029436'})
        self.catalog.start()

    def tearDown(self):
        for e in self.releases:e.set()
        for m in self.managers:m.shutdown()
        self.catalog.stop();self.temp.cleanup()

    def manager(self,execute):
        m=jobs.DownloadManager(self.root/'tasks.sqlite3',self.root/'outputs',execute);self.managers.append(m);return m

    def wait_finished(self,m,r):
        end=time.monotonic()+5
        while time.monotonic()<end:
            state=m.get_run('tester',r['id'])
            if state['status'] in jobs.FINAL_STATUSES:return state
            threading.Event().wait(.01)
        self.fail('task did not finish')

    def test_handoff_overlaps_next_collection_but_bounds_inflight_and_serializes_local_work(self):
        collected=[threading.Event() for _ in range(3)];local=[threading.Event() for _ in range(3)]
        release=threading.Event();self.releases.append(release);counter=[0];lock=threading.Lock()
        def execute(config,directory,log,cancelled,update):
            with lock:i=counter[0];counter[0]+=1
            collected[i].set()
            release_collection_for_local_work();local[i].set()
            if i==0:self.assertTrue(release.wait(5))
            f=make_file(directory,config);update({**f,'status':'success'});return [f]
        m=self.manager(execute)
        a=m.create('tester',CONFIG);self.assertTrue(local[0].wait(3))
        b=m.create('tester',CONFIG);self.assertTrue(collected[1].wait(3))
        c=m.create('tester',CONFIG)
        self.assertFalse(local[1].wait(.15));self.assertFalse(collected[2].is_set())
        self.assertEqual(m.get_run('tester',c['id'])['queue_wait_reason'],'local_capacity')
        release.set()
        for r in [a,b,c]:self.assertEqual(self.wait_finished(m,r)['status'],'success')
        m._queue.join();self.assertEqual(len(m._processing_threads),0)

    def test_failure_after_handoff_does_not_stop_next_task_or_lose_checkpoint(self):
        entered=threading.Event();release=threading.Event();self.releases.append(release);counter=[0]
        def execute(config,directory,log,cancelled,update):
            counter[0]+=1;first=counter[0]==1
            f=make_file(directory,config);update({**f,'status':'success','files':[f]})
            if first:
                release_collection_for_local_work();entered.set();self.assertTrue(release.wait(5))
                raise BillCollectionError('合成故障')
            return [f]
        m=self.manager(execute);a=m.create('tester',CONFIG);self.assertTrue(entered.wait(3))
        b=m.create('tester',CONFIG);self.assertEqual(self.wait_finished(m,b)['status'],'success')
        release.set();state=self.wait_finished(m,a)
        self.assertEqual(state['status'],'partial');self.assertEqual(len(state['files']),1)

    def test_cancel_waiting_local_turn_does_not_cancel_previous_task_or_reexport(self):
        entered=threading.Event();second=threading.Event();release=threading.Event();self.releases.append(release);counter=[0]
        def execute(config,directory,log,cancelled,update):
            counter[0]+=1;first=counter[0]==1
            if not first:second.set()
            release_collection_for_local_work()
            if first:entered.set();self.assertTrue(release.wait(5))
            f=make_file(directory,config);update({**f,'status':'success'});return [f]
        m=self.manager(execute);a=m.create('tester',CONFIG);self.assertTrue(entered.wait(3))
        b=m.create('tester',CONFIG);self.assertTrue(second.wait(3));m.cancel('tester',b['id'])
        self.assertEqual(self.wait_finished(m,b)['status'],'cancelled');self.assertEqual(counter[0],2)
        self.assertEqual(m.get_run('tester',a['id'])['status'],'running');release.set()
        self.assertEqual(self.wait_finished(m,a)['status'],'success')

    def test_worker_start_failure_does_not_kill_dispatcher_or_leak_capacity(self):
        def execute(config,directory,log,cancelled,update):
            f=make_file(directory,config);update({**f,'status':'success'});return [f]
        m=self.manager(execute);original=threading.Thread.start;failed=[]
        def start(thread):
            if thread.name.startswith('download-turn-') and not failed:
                failed.append(True);raise RuntimeError('synthetic thread failure')
            return original(thread)
        with patch.object(threading.Thread,'start',start):
            a=m.create('tester',CONFIG)
            self.assertEqual(self.wait_finished(m,a)['status'],'error')
            b=m.create('tester',CONFIG)
            self.assertEqual(self.wait_finished(m,b)['status'],'success')
        m._queue.join();self.assertTrue(m._thread.is_alive())
