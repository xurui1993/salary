from concurrent.futures import ThreadPoolExecutor
import datetime as dt
import json
from pathlib import Path
import sys
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import zipfile

import pandas as pd
from openpyxl import Workbook

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'backend'))
sys.path.insert(0, str(ROOT / 'scripts'))
from workbook_policy import compression, install_zip_policy
from generation_performance import SourceCache, TableExchange, generation_context, profiled, public_profile
from binding_tables import verified_book, exported_value
from binding_download import generate_binding
from abnormal_followup import generate_abnormal_followup, _source_sheet
from source_tables import source_sheet
from compare_generator_workbooks import workbook_contract
import test_salary_bind_sources as fixtures
import test_abnormal_followup as followup_fixtures


class PerformanceTests(unittest.TestCase):
    def test_diagnostic_failure_preserves_result_and_context(self):
        import generation_performance as metrics
        @profiled('abnormal_riders', 0, 'directory')
        def generate(directory, fail=False):
            if fail:
                raise ValueError('original failure')
            return 'result'
        with tempfile.TemporaryDirectory() as folder, patch.object(metrics.Profile, 'finish', side_effect=OSError('diagnostics unavailable')):
            self.assertEqual(generate(folder), 'result')
            self.assertIsNone(metrics.shared_cache())
            with self.assertRaisesRegex(ValueError, 'original failure'):
                generate(folder, fail=True)
            self.assertIsNone(metrics.shared_cache())

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def test_zip_policy_is_single_install_and_explicit_compression_wins(self):
        before = zipfile.ZipFile.__init__
        install_zip_policy(); install_zip_policy()
        self.assertIs(before, zipfile.ZipFile.__init__)
        data = ('synthetic-row-' * 10000).encode()
        sizes = []
        for level, explicit in ((1, None), (9, None), (1, 9)):
            path = self.root / f'{len(sizes)}.zip'
            with compression(level), zipfile.ZipFile(path, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=explicit) as book:
                book.writestr('data', data)
            with zipfile.ZipFile(path) as book:
                self.assertEqual(book.read('data'), data)
                sizes.append(book.getinfo('data').compress_size)
        self.assertGreater(sizes[0], sizes[1])
        self.assertEqual(sizes[1], sizes[2])

    def test_cache_is_content_checked_filename_sensitive_and_copies_mutable_frames(self):
        path = self.root / 'input.csv'; path.write_text('a')
        calls = []
        def load(file):
            calls.append(file)
            return pd.DataFrame({'id': ['00123'], 'value': [Path(file).read_text()]})
        cache = SourceCache()
        first = cache.read(path, load); first.loc[0, 'id'] = 'changed'
        self.assertEqual(cache.read(path, load).loc[0, 'id'], '00123')
        path.write_text('b')
        self.assertEqual(cache.read(path, load).loc[0, 'value'], 'b')
        other = self.root / '数据明细.csv'; other.write_text('b')
        cache.read(other, load)
        self.assertEqual(len(calls), 3)
        SourceCache().read(path, load)
        self.assertEqual(len(calls), 4)

    def test_parallel_readers_parse_once_and_respect_retained_budget(self):
        path = self.root / 'data.csv'; path.write_text('source')
        cache = SourceCache(max_bytes=1024)
        calls = []
        def load(_):
            calls.append(1); time.sleep(.03)
            return pd.DataFrame({'value': ['synthetic']})
        with ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(lambda _: cache.read(path, load), range(4)))
        self.assertEqual(len(calls), 1)
        self.assertTrue(all(frame.iloc[0, 0] == 'synthetic' for frame in results))
        self.assertLessEqual(cache.summary()['retained_bytes'], 1024)
        too_small = SourceCache(max_bytes=1)
        too_small.read(path, load)
        self.assertEqual(too_small.summary()['retained_bytes'], 0)

    def test_profile_is_written_on_failure_without_masking_it(self):
        @profiled('synthetic', 0, 'directory')
        def fail(directory):
            raise RuntimeError('synthetic failure')
        with self.assertRaisesRegex(RuntimeError, 'synthetic failure'):
            fail(self.root)
        report = public_profile(self.root)
        self.assertTrue(report['failed'])
        self.assertGreaterEqual(report['elapsed_seconds'], 0)
        (self.root / 'performance.json').write_text('invalid')
        self.assertIsNone(public_profile(self.root))

    def test_large_source_cache_falls_back_to_read_only_and_keeps_formats(self):
        path = self.root / 'source.xlsx'
        book = Workbook(); ws = book.active; ws.title = '价格档案'
        ws.append(['日期', 'ID']); ws.append([dt.datetime(2026, 10, 1), '00123'])
        ws['A2'].number_format = 'yyyy-mm-dd'; book.save(path); book.close()
        for limit in (1, 100000):
            cache = SourceCache(max_bytes=limit)
            with generation_context(cache), source_sheet(path, '价格档案', _source_sheet) as sheet:
                rows = list(sheet.iter_rows())
                self.assertEqual(rows[1][0].number_format, 'yyyy-mm-dd')
                self.assertEqual(rows[1][0].value, dt.datetime(2026, 10, 1))
                self.assertEqual(rows[1][1].value, '00123')
            self.assertLessEqual(cache.summary()['retained_bytes'], limit)

    def test_shared_binding_matches_authoritative_file_and_tampering_disables_handoff(self):
        fixture = fixtures.BindingSourceTests(); fixture.root = self.root
        fixture.scope = {'month': '2026-07', 'start': '2026-07-01', 'end': '2026-07-29'}
        sources, employees = fixture.fixture()
        proxy = self.root / 'proxy.csv'
        proxy.write_text('城市名称,代领月份,流程状态,启停用,骑手身份证,代领人身份证\n', encoding='utf-8-sig')
        paths = {key: sources[0][0] / item['path'] for key, item in sources[0][1]['datasets'].items()}
        raw = self.root / 'binding'; raw.mkdir()
        cache, exchange = SourceCache(), {}
        with generation_context(cache, exchange):
            file, _ = generate_binding(paths, employees[0] / 'merchantFreelancer.xlsx', proxy,
                                      SimpleNamespace(city='泉州', **fixture.scope), raw, lambda *_: None, threading.Event())
        self.assertEqual(len(exchange['tables']), 3)
        self.assertFalse(list((raw / 'inputs').glob('*.csv')))
        self.assertIsNotNone(verified_book(exchange, file))
        helper = followup_fixtures.AbnormalFollowupTests(); helper.root = self.root / 'followup-inputs'; helper.root.mkdir()
        _, ub, price, archive, rental = helper.sources()
        disk = generate_abnormal_followup(file, ub, price, archive, rental, '泉州', '2026-07', self.root / 'disk')
        with generation_context(cache, exchange):
            memory = generate_abnormal_followup(file, ub, price, archive, rental, '泉州', '2026-07', self.root / 'memory')
        self.assertEqual(workbook_contract(disk), workbook_contract(memory))
        with file.open('ab') as stream:
            stream.write(b'changed')
        self.assertIsNone(verified_book(exchange, file))

    def test_unusual_escaped_strings_require_authoritative_file_decoding(self):
        with self.assertRaises(ValueError):
            exported_value('literal_x000D_value', '骑手姓名')
        self.assertEqual(exported_value('00123', '骑手身份证'), '00123')

    def test_queued_handoffs_share_a_budget_and_release_it_after_consumption(self):
        cache = SourceCache(max_bytes=10)
        first, second = TableExchange(cache), TableExchange(cache)
        payload = {'tables': ['synthetic'], '_retained_bytes': 7}
        first.update(payload); second.update(payload)
        self.assertTrue(first)
        self.assertFalse(second)
        self.assertEqual(cache.summary()['handoff_bytes'], 7)
        first.clear(); second.update(payload)
        self.assertTrue(second)
        second.clear(); second.clear()
        self.assertEqual(cache.summary()['handoff_bytes'], 0)

    def test_mutation_during_parse_is_not_committed_to_cache(self):
        path = self.root / 'source.csv'; path.write_text('before')
        def load(file):
            Path(file).write_text('after')
            return pd.DataFrame({'value': ['untrusted']})
        with self.assertRaisesRegex(Exception, '读取期间发生变化'):
            SourceCache().read(path, load)

    def test_followup_waits_for_its_month_without_waiting_for_other_months(self):
        import contextlib
        import download_service as service
        import test_download_service as download_fixtures
        from unittest.mock import Mock
        release = threading.Event()
        completed = []
        config = service.validate_request({'cities': ['泉州'], 'datasets': ['abnormal_followup'],
                                           'start': '2026-09-01', 'end': '2026-10-10'})
        config.update(owner='synthetic', lanorange_full_delivery=False)
        sources = Mock(); sources.employees.return_value = Path('employee.xlsx')
        sources.proxies.return_value = Path('proxy.xlsx')
        def binding(paths, employees, proxies, plan, raw, logger, cancelled):
            if plan.month == '2026-10' and not release.wait(5):
                raise RuntimeError('unrelated month blocked earlier follow-up')
            file = Path(raw) / 'generated.xlsx'; file.write_bytes(b'synthetic')
            completed.append(plan.month)
            return file, {}
        def collect(kind, directory, *args, **kwargs):
            directory = Path(directory); directory.mkdir(parents=True, exist_ok=True)
            file = directory / 'blue.xlsx'; file.write_bytes(b'synthetic')
            return file
        seen = []
        def followup(binding_file, *args, **kwargs):
            month = args[5]
            if month == '2026-09':
                self.assertNotIn('2026-10', completed)
                release.set()
            self.assertTrue(Path(binding_file).is_file())
            seen.append(month)
            out = Path(args[6]); out.mkdir(parents=True, exist_ok=True)
            file = out / f'{month}.xlsx'; file.write_bytes(b'synthetic')
            return file
        @contextlib.contextmanager
        def factory(*_):
            yield download_fixtures.FakeRunner()
        try:
            with patch('binding_sources_http.BindingSources', return_value=sources), \
                 patch('binding_download.generate_binding', side_effect=binding), \
                 patch('lanorange_download.collect', side_effect=collect), \
                 patch('abnormal_followup.generate_abnormal_followup', side_effect=followup):
                updates = []
                service.execute_downloads(config, self.root / 'run', lambda *_: None,
                                          threading.Event(), updates.append, factory)
            self.assertEqual(seen, ['2026-09', '2026-10'])
            self.assertFalse([value for value in updates if value.get('status') == 'error'])
        finally:
            release.set()

    def test_finished_task_persists_performance_for_page_and_history(self):
        from download_jobs import DownloadManager
        from test_download_jobs import make_file
        @profiled('download_task', 1, 'run_dir')
        def execute(config, run_dir, log, cancelled, update):
            return [make_file(run_dir, config)]
        manager = DownloadManager(self.root / 'tasks.sqlite3', self.root / 'outputs', execute)
        self.addCleanup(manager.shutdown)
        run = manager.create('synthetic', {'cities': ['泉州'], 'datasets': ['delivery_fee'],
                             'start': '2026-10-01', 'end': '2026-10-01', 'months': ['2026-10']},
                             request_id='performance_persistence_01')
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            run = manager.get_run('synthetic', run['id'])
            if run['status'] == 'success':
                break
            time.sleep(.01)
        self.assertEqual(run['status'], 'success')
        self.assertIn('performance', run)
        self.assertGreaterEqual(run['performance']['total_seconds'], 0)
        self.assertGreaterEqual(run['performance']['queued_seconds'], 0)


if __name__ == '__main__': unittest.main()
