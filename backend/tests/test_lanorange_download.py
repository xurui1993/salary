import contextlib
import datetime as dt
import hashlib
import io
import json
from pathlib import Path
import re
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import MagicMock, Mock, patch
import zipfile

from openpyxl import Workbook, load_workbook
sys.path.insert(0, str(Path(__file__).parents[1]))
from lanorange_catalog import DATASETS, ALL_CITIES, source_directory
from lanorange_download import collect, validate_original, business_rows
from binding_sources_http import export_once
from binding_source_auth import client
from lanorange_http_export import export_once as native_export
from requests.exceptions import ChunkedEncodingError
from download_jobs import DownloadManager, _initial_items, FINAL_STATUSES
from download_service import validate_request, execute_downloads, _requested_items
from fengshen_bill import BillCollectionError, atomic_json


def workbook_bytes():
    book = Workbook(); sheet = book.active
    sheet.append(['城市名称', '流程状态', '启停用'])
    for city, status, enabled in [('泉州', '审核通过', '启用'), ('上海', '审批中', '启用'),
                                  ('韶关', '审核拒绝', '停用'), ('大连', '待审核', '启用')]:
        sheet.append([city, status, enabled])
    stream = io.BytesIO(); book.save(stream); book.close(); return stream.getvalue()


def passthrough_format(path, output_dir, cancelled=None):
    """测试用格式化占位：复制原文并返回副本，避免依赖真实骑手档案表结构。"""
    import shutil
    import uuid as _uuid
    target = Path(output_dir) / ('.formatted_' + _uuid.uuid4().hex + '.xlsx')
    shutil.copy2(path, target)
    return target, {'rows': 1}


class LanorangeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=Path(__file__).parent)
        self.root = Path(self.temp.name).resolve(); self.content = workbook_bytes()
        self.city_patch = patch('lanorange_download.load_cities', return_value={'泉州':'123','上海':'456'}); self.city_patch.start()

    def tearDown(self): self.city_patch.stop(); self.temp.cleanup()

    def config(self):
        return {'cities':['泉州'],'datasets':list(DATASETS),'start':'2026-10-18','end':'2026-10-18','months':['2026-10'],'lanorange_by_city':True}

    def fake_collect(self, kind, directory, *args, **kwargs):
        directory.mkdir(parents=True, exist_ok=True); file = directory / (kind + '.xlsx')
        file.write_bytes(self.content); return file

    def test_blue_scope_honours_selected_cities_and_ignores_dates(self):
        a = validate_request({'datasets':list(DATASETS)},today=dt.date(2026,10,18))
        b = validate_request({'datasets':list(DATASETS),'cities':['泉州'],'start':'bad','end':'1900-01-01'},
                             today=dt.date(2026,10,18))
        self.assertEqual(a['cities'],[ALL_CITIES]);self.assertTrue(a['lanorange_full_delivery'])
        self.assertEqual(b['cities'],['泉州']);self.assertTrue(b['lanorange_by_city'])
        self.assertNotIn('lanorange_full_delivery',b);self.assertEqual(b['start'],'2026-10-18')
        self.assertEqual(len(_initial_items(a)),8)
        self.assertEqual([tuple(i[k] for k in ('city','dataset','start','end')) for i in _initial_items(a)],
                         [tuple(i[k] for k in ('city','dataset','start','end')) for i in _requested_items(a)])
        self.assertEqual(len(_initial_items(b)),8)
        self.assertEqual({item['city'] for item in _initial_items(b)}, {'泉州'})
        self.assertEqual(len(a['datasets']),8)

    def test_hidden_option_sheets_are_preserved_but_not_counted_as_riders(self):
        book = Workbook(); sheet = book.active; sheet.title = '骑手离职'
        sheet.append(['骑手ID']); sheet.append(['123'])
        options = book.create_sheet('options_0'); options.append(['选项一']); options.append(['选项二'])
        options.sheet_state = 'hidden'
        file = self.root / 'with-options.xlsx'; book.save(file); book.close()
        before = file.read_bytes()
        sheets = validate_original(file, threading.Event())
        self.assertEqual(business_rows(sheets), 1)
        self.assertEqual(len(sheets), 2); self.assertEqual(sheets[1]['state'], 'hidden')
        self.assertEqual(file.read_bytes(), before)

    def test_all_city_fast_validation_matches_strict_parser(self):
        book = Workbook(); sheet = book.active; sheet.title = '数据'
        sheet.append(['城市', '数量', '公式', '备注'])
        sheet.append(['泉州', 1, None, None])
        sheet.append([None, None, None, None])
        sheet.append(['上海', None, '=A2', None])
        options = book.create_sheet('选项'); options.append(['选项一', '说明']); options.append(['甲', '乙'])
        options.sheet_state = 'hidden'
        file = self.root / 'parity.xlsx'; book.save(file); book.close()
        fast = validate_original(file, threading.Event())
        with patch('lanorange_download._validate_all_cities', side_effect=ValueError('force strict')):
            strict = validate_original(file, threading.Event())
        self.assertEqual(fast, strict)
        self.assertEqual(fast[0], {'name': '数据', 'rows': 2, 'columns': 4, 'state': 'visible'})
        self.assertEqual(fast[1], {'name': '选项', 'rows': 1, 'columns': 2, 'state': 'hidden'})

    def test_all_city_fast_validation_honours_cancellation(self):
        file = self.root / 'cancelled.xlsx'; file.write_bytes(self.content)
        cancelled = threading.Event(); cancelled.set()
        with self.assertRaisesRegex(BillCollectionError, '校验已取消，原始文件已保留'):
            validate_original(file, cancelled)

    def test_blue_headers_follow_official_language_and_entry(self):
        with client('lanorange', token='test-only-token') as session:
            self.assertEqual(session.headers['Content-Language'], 'zh_CN')
            self.assertEqual(session.headers['Referer'], 'https://madouren.cdevelopment.cn/admin/')
            cookie = next(iter(session.cookies))
            self.assertEqual(cookie.name, 'Admin-Token'); self.assertTrue(cookie.secure)
            self.assertEqual(cookie.domain, 'madouren.cdevelopment.cn')
            self.assertEqual(cookie.value, 'test-only-token')
        with client('baize', token='test-only-token') as session:
            self.assertEqual(len(session.cookies), 0)

    def test_native_http_preserves_bytes_and_keeps_credentials_out_of_argv_and_receipt(self):
        process = Mock(); process.poll.return_value=0; process.returncode=0
        process.stdout=io.BytesIO(b'{"ok":true,"status":200}')
        payloads=[]
        def write(payload):
            data=json.loads(payload);payloads.append(data);Path(data['output']).write_bytes(self.content)
        process.stdin.write.side_effect=write;process.stdin.closed=False
        target=self.root/'native'/'original.xlsx'
        with client('lanorange',token='private-test-token') as session, \
             patch('lanorange_http_export.shutil.which',return_value='node'), \
             patch('lanorange_http_export.subprocess.Popen',return_value=process) as launch:
            native_export(session,'lanorange',DATASETS['lanorange_rider_quit'][1],{'cityIds[0]':'123'},target,threading.Event())
        self.assertEqual(target.read_bytes(),self.content)
        self.assertNotIn('private-test-token',str(launch.call_args))
        self.assertEqual(payloads[0]['headers']['Cookie'],'Admin-Token=private-test-token')
        receipt=(target.parent/'http_submission.json').read_text('utf-8')
        self.assertNotIn('private-test-token',receipt);self.assertEqual(json.loads(receipt)['submission_state'],'submitted')

    def test_native_http_rejects_truncated_file_even_on_normal_http_close(self):
        process=Mock();process.poll.return_value=0;process.returncode=0
        process.stdout=io.BytesIO(b'{"ok":true,"status":200}')
        process.stdin.write.side_effect=lambda payload:Path(json.loads(payload)['output']).write_bytes(self.content[:100])
        process.stdin.closed=False;target=self.root/'native-broken'/'original.xlsx'
        with client('lanorange',token='private-test-token') as session, \
             patch('lanorange_http_export.shutil.which',return_value='node'), \
             patch('lanorange_http_export.subprocess.Popen',return_value=process) as launch:
            with self.assertRaisesRegex(BillCollectionError,'不完整'):
                native_export(session,'lanorange',DATASETS['lanorange_rider_quit'][1],{},target,threading.Event())
        self.assertFalse(target.exists());self.assertEqual(launch.call_count,1)
        info=json.loads((target.parent/'http_submission.json').read_text('utf-8'))
        self.assertEqual(info['submission_state'],'unknown')

    def test_native_http_cancellation_kills_transfer_without_retry(self):
        cancel=threading.Event();process=Mock();process.poll.side_effect=[None,0];process.returncode=-9
        process.stdin.write.side_effect=lambda _:cancel.set();process.stdin.closed=False
        process.stdout=io.BytesIO(b'');target=self.root/'native-cancelled'/'original.xlsx'
        with client('lanorange',token='private-test-token') as session, \
             patch('lanorange_http_export.shutil.which',return_value='node'), \
             patch('lanorange_http_export.subprocess.Popen',return_value=process) as launch:
            with self.assertRaisesRegex(BillCollectionError,'取消'):
                native_export(session,'lanorange',DATASETS['lanorange_rider_quit'][1],{},target,cancel)
        process.kill.assert_called_once();self.assertEqual(launch.call_count,1)
        self.assertFalse(target.exists())


    def test_official_endpoint_no_filters_original_bytes_all_statuses_and_resume(self):
        session = Mock()
        def export(session, source, endpoint, params, file, cancelled):
            self.assertEqual(source, 'lanorange'); self.assertEqual(params, {'pageNum': 1, 'pageSize': 10})
            self.assertEqual(endpoint, DATASETS['lanorange_rider_archive'][1])
            file.parent.mkdir(parents=True, exist_ok=True); file.write_bytes(self.content); return file
        with patch('lanorange_download.authenticated', return_value=contextlib.nullcontext(session)), \
             patch('lanorange_download.export_once', side_effect=export) as submit, \
             patch('lanorange_download.query', return_value={'total': 4}):
            file = collect('lanorange_rider_archive', self.root / 'source', lambda *_: None, threading.Event())
        self.assertEqual(file.read_bytes(), self.content)
        info = json.loads((file.parent / 'source_receipt.json').read_text(encoding='utf-8'))
        self.assertEqual(info['filters'], {}); self.assertEqual(info['sheets'][0]['rows'], 4)
        with patch('lanorange_download.authenticated', side_effect=AssertionError('must not authenticate on recovery')):
            recovered = collect('lanorange_rider_archive', self.root / 'resumed', lambda *_:None, threading.Event(), file.parent)
        self.assertEqual(recovered.read_bytes(), self.content); self.assertEqual(submit.call_count, 1)
        file.write_bytes(b'tampered')
        with self.assertRaises(BillCollectionError):
            collect('lanorange_rider_archive', self.root / 'bad', lambda *_:None, threading.Event(), file.parent)

    def test_price_archive_month_range_filters_platform_export_and_receipt(self):
        session = Mock()
        def export(session, source, endpoint, params, file, cancelled):
            self.assertEqual(endpoint, DATASETS['lanorange_part_price'][1])
            self.assertEqual(params['params[beginTime]'], '2026-08-01')
            self.assertEqual(params['params[endTime]'], '2026-10-31')
            file.parent.mkdir(parents=True, exist_ok=True); file.write_bytes(self.content); return file
        with patch('lanorange_download.authenticated', return_value=contextlib.nullcontext(session)), \
             patch('lanorange_download.export_once', side_effect=export), \
             patch('lanorange_download.query', return_value={'total': 4}) as query:
            path = collect('lanorange_part_price', self.root / 'months', lambda *_: None, threading.Event(),
                           months=['2026-08', '2026-10'])
        self.assertEqual(query.call_args.args[3]['params[beginTime]'], '2026-08-01')
        self.assertEqual(query.call_args.args[3]['params[endTime]'], '2026-10-31')
        info = json.loads((path.parent / 'source_receipt.json').read_text('utf-8'))
        self.assertEqual(info['filters'], {'months': ['2026-08', '2026-10']})
        with patch('lanorange_download.authenticated', side_effect=AssertionError('must not authenticate')):
            recovered = collect('lanorange_part_price', self.root / 'months-resumed', lambda *_: None,
                                threading.Event(), path.parent, months=['2026-08', '2026-10'])
        self.assertEqual(recovered.read_bytes(), self.content)

    def test_legacy_unfiltered_receipt_recovers_into_month_scoped_task(self):
        session = Mock()
        def export(session, source, endpoint, params, file, cancelled):
            file.parent.mkdir(parents=True, exist_ok=True); file.write_bytes(self.content); return file
        with patch('lanorange_download.authenticated', return_value=contextlib.nullcontext(session)), \
             patch('lanorange_download.export_once', side_effect=export), \
             patch('lanorange_download.query', return_value={'total': 4}):
            path = collect('lanorange_part_price', self.root / 'legacy', lambda *_: None, threading.Event())
        with patch('lanorange_download.authenticated', side_effect=AssertionError('must not authenticate')):
            recovered = collect('lanorange_part_price', self.root / 'legacy-resumed', lambda *_: None,
                                threading.Event(), path.parent, months=['2026-10'])
        self.assertEqual(recovered.read_bytes(), self.content)

    def test_platform_months_scope_and_ranges(self):
        from lanorange_catalog import platform_months, months_contiguous, date_range, clean_months
        self.assertEqual(platform_months({'datasets': ['lanorange_part_price'],
                                          'lanorange_months': ['2026-10']}, 'lanorange_part_price'), ['2026-10'])
        self.assertIsNone(platform_months({'datasets': ['lanorange_part_price'],
                                           'months': ['2026-11']}, 'lanorange_part_price'))
        self.assertEqual(platform_months({'datasets': ['lanorange_part_price', 'delivery_fee'],
                                          'months': ['2026-10', '2026-11']}, 'lanorange_part_price'),
                         ['2026-10', '2026-11'])
        self.assertIsNone(platform_months({'datasets': ['delivery_fee'], 'months': ['2026-10']}, 'delivery_fee'))
        self.assertIsNone(platform_months({'datasets': ['abnormal_riders'], 'months': ['2026-10']},
                                          'lanorange_part_price'))
        self.assertTrue(months_contiguous(['2026-09', '2026-10']))
        self.assertFalse(months_contiguous(['2026-08', '2026-10']))
        self.assertEqual(date_range(['2026-10']), ('2026-10-01', '2026-10-31'))
        self.assertEqual(date_range(['2026-12', '2027-01']), ('2026-12-01', '2027-01-31'))
        self.assertEqual(clean_months(['2026-10', '2026-08', '2026-10']), ['2026-08', '2026-10'])

    def test_price_archive_months_validation_and_scope(self):
        from download_service import ValidationError
        value = validate_request({'datasets': ['lanorange_part_price'],
                                  'lanorange_months': ['2026-10', '2026-08', '2026-10']},
                                 today=dt.date(2026, 11, 7))
        self.assertEqual(value['lanorange_months'], ['2026-08', '2026-10'])
        self.assertEqual(value['months'], ['2026-08', '2026-10'])
        with self.assertRaises(ValidationError):
            validate_request({'datasets': ['lanorange_part_price'], 'lanorange_months': ['2026-13']},
                             today=dt.date(2026, 11, 7))
        with self.assertRaises(ValidationError):
            validate_request({'datasets': ['lanorange_part_price', 'delivery_fee'],
                              'lanorange_months': ['2026-10']}, today=dt.date(2026, 11, 7))

    def test_selected_cities_are_scoped_and_checked_against_the_allowlist(self):
        from download_service import ValidationError
        value = validate_request({'datasets': ['lanorange_rider_archive', 'lanorange_part_price'],
                                  'cities': ['深圳市', '三亚']}, today=dt.date(2026, 11, 7))
        self.assertEqual(value['cities'], ['深圳', '三亚'])
        self.assertTrue(value['lanorange_by_city'])
        self.assertNotIn('lanorange_full_delivery', value)
        self.assertEqual(len(_initial_items(value)), 4)
        legacy = validate_request({'datasets': ['lanorange_rider_archive'], 'cities': ['全部城市']},
                                  today=dt.date(2026, 11, 7))
        self.assertEqual(legacy['cities'], [ALL_CITIES])
        self.assertTrue(legacy['lanorange_full_delivery'])
        self.assertEqual(validate_request({'datasets': ['lanorange_rider_archive']},
                                          today=dt.date(2026, 11, 7))['cities'], [ALL_CITIES])
        with self.assertRaises(ValidationError):
            validate_request({'datasets': ['lanorange_rider_archive'], 'cities': ['佛山']},
                             today=dt.date(2026, 11, 7))

    def test_city_export_uses_official_array_parameter_and_recovery_cannot_cross_city(self):
        session = Mock()
        book=Workbook();book.active.append(['城市名称']);book.active.append(['泉州市'])
        stream=io.BytesIO();book.save(stream);book.close();city_content=stream.getvalue()
        def export(session, source, endpoint, params, file, cancelled):
            self.assertEqual(params, {'pageNum':1,'pageSize':10,'cityIds[0]':'123','cityId':'123'})
            file.write_bytes(city_content); return file
        with patch('lanorange_download.authenticated', return_value=contextlib.nullcontext(session)), \
             patch('lanorange_download.export_once', side_effect=export), \
             patch('lanorange_download.query', return_value={'total':1}) as query:
            path=collect('lanorange_rider_archive',self.root/'city',lambda *_:None,threading.Event(),city='泉州',city_id='123')
        self.assertEqual(query.call_args.args[3]['cityIds[0]'],'123')
        info=json.loads((path.parent/'source_receipt.json').read_text('utf-8'))
        self.assertEqual(info['filters'],{'city':'泉州'});self.assertEqual(path.read_bytes(),city_content)
        with self.assertRaises(BillCollectionError):
            collect('lanorange_rider_archive',self.root/'wrong',lambda *_:None,threading.Event(),path.parent,city='上海',city_id='456')

    def test_ignored_city_filter_is_rejected_but_original_batch_context_is_documented(self):
        session=Mock()
        def export(session, source, endpoint, params, file, cancelled):
            file.write_bytes(self.content);return file
        with patch('lanorange_download.authenticated',side_effect=lambda *_:contextlib.nullcontext(session)), \
             patch('lanorange_download.export_once',side_effect=export):
            with self.assertRaisesRegex(BillCollectionError,'城市筛选未生效'):
                collect('lanorange_rider_report',self.root/'mixed-report',lambda *_:None,threading.Event(),city='泉州',city_id='123')
            self.assertFalse((self.root/'mixed-report/source_receipt.json').exists())
            path=collect('lanorange_batch_quit',self.root/'batch',lambda *_:None,threading.Event(),city='泉州',city_id='123')
        info=json.loads((path.parent/'source_receipt.json').read_text('utf-8'))
        self.assertEqual(path.read_bytes(),self.content)
        self.assertEqual(info['other_city_rows'],3)
        self.assertEqual(info['scope_validation'],'batch_with_other_cities')

    def test_two_city_originals_and_combined_workbook_are_all_downloadable(self):
        def execute(config, root, log, cancel, update):
            with patch('lanorange_download.collect',side_effect=self.fake_collect), \
                 patch('rider_archive.format_full_workbook',side_effect=passthrough_format):
                return execute_downloads(config,root,log,cancel,update)
        manager=DownloadManager(self.root/'combined/tasks.sqlite3',self.root/'combined/outputs',execute)
        try:
            config={**self.config(),'cities':['泉州','上海'],'datasets':['lanorange_rider_archive']}
            run=manager.create('test',config);deadline=time.monotonic()+10
            while time.monotonic()<deadline:
                run=manager.get_run('test',run['id'])
                if run['status'] in FINAL_STATUSES:break
                threading.Event().wait(.02)
            self.assertEqual(run['status'],'success',run.get('error'));self.assertEqual(len(run['files']),3)
            summary=next(f for f in run['files'] if f.get('artifact_role')=='summary')
            path,_=manager.get_file('test',run['id'],summary['id'])
            book=load_workbook(path,read_only=True)
            try:
                rows=list(book['骑手档案'].values)
                self.assertEqual(len(rows),3)
                self.assertEqual(rows[0][0],'来源城市')
                self.assertEqual([r[0] for r in rows[1:]],['泉州','上海'])
            finally:book.close()
            for f in run['files']:
                if f.get('artifact_role')=='summary':continue
                original,_=manager.get_file('test',run['id'],f['id']);self.assertEqual(original.read_bytes(),self.content)
            bundle,_=manager.get_bundle('test',run['id'])
            with zipfile.ZipFile(bundle) as archive:
                self.assertEqual(len(archive.namelist()),3)
                self.assertNotIn('文件清单.csv',archive.namelist())
        finally:manager.shutdown()

    def test_blue_only_skips_runner_and_one_failure_does_not_stop_other_items(self):
        runner = Mock(side_effect=AssertionError('must not connect to Fengshen'))
        updates = []
        def download(kind, directory, *args, **kwargs):
            if kind == 'lanorange_rider_quit': raise BillCollectionError('测试失败')
            return self.fake_collect(kind, directory)
        with patch('lanorange_download.collect', side_effect=download) as collector, \
             patch('rider_archive.format_full_workbook', side_effect=passthrough_format):
            files = execute_downloads(self.config(), self.root / 'run', lambda *_:None,
                                      threading.Event(), updates.append, runner)
        self.assertEqual(collector.call_count, 8); self.assertEqual(len(files), 7); runner.assert_not_called()
        self.assertTrue(any(i['status']=='error' for i in updates))
        for value in files:
            if value['dataset'] == 'lanorange_batch_quit':
                self.assertRegex(value['name'], r'^泉州.+（城市批次原表）\d{4}\.xlsx$')
            else:
                self.assertRegex(value['name'], r'^泉州.+\d{4}\.xlsx$')

    def test_success_callback_failure_keeps_published_files_and_continues(self):
        logs = []
        def execute(config, root, log, cancel, update):
            with patch('lanorange_download.collect', side_effect=self.fake_collect), \
                 patch('rider_archive.format_full_workbook', side_effect=passthrough_format):
                return execute_downloads(config, root, log, cancel, update)
        def update(change):
            if change.get('status') == 'success':
                raise RuntimeError('database unavailable')
        files = execute(self.config(), self.root / 'callback', logs.append, threading.Event(), update)
        self.assertEqual(len(files), 8)
        self.assertTrue(any('状态回写未完成' in message and 'RuntimeError' in message for message in logs))
        for info in files:
            self.assertTrue((self.root / 'callback' / info['relative_path']).is_file())

    def test_truncated_stream_keeps_receipt_and_never_retries_or_publishes(self):
        session = MagicMock()
        response = session.post.return_value.__enter__.return_value
        response.status_code = 200
        response.headers = {'Content-Type': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
                            'Transfer-Encoding': 'chunked', 'Set-Cookie': 'must-not-be-recorded'}
        def chunks(*args):
            yield self.content[:100]
            raise ChunkedEncodingError('sensitive upstream details')
        response.iter_content.side_effect = chunks
        target = self.root / 'broken' / 'original.xlsx'
        with self.assertRaisesRegex(BillCollectionError, '传输中断'):
            export_once(session, 'lanorange', DATASETS['lanorange_rider_archive'][1],
                        {'pageNum': 1, 'pageSize': 10}, target, threading.Event())
        self.assertFalse(target.exists()); self.assertEqual(session.post.call_count, 1)
        info = json.loads((target.parent / 'http_submission.json').read_text(encoding='utf-8'))
        self.assertEqual(info['submission_state'], 'unknown')
        self.assertEqual(info['error_category'], 'ChunkedEncodingError')
        self.assertEqual(info['downloaded_bytes'], 100)
        self.assertNotIn('Set-Cookie', info['response_headers'])
        self.assertNotIn('sensitive', json.dumps(info))

    def test_orderly_close_without_zip_directory_is_not_success(self):
        session = MagicMock()
        response = session.post.return_value.__enter__.return_value
        response.status_code = 200; response.headers = {}
        response.iter_content.return_value = [self.content[:100]]
        target = self.root / 'incomplete' / 'original.xlsx'
        with self.assertRaisesRegex(BillCollectionError, '不完整'):
            export_once(session, 'lanorange', DATASETS['lanorange_rider_archive'][1], {}, target, threading.Event())
        self.assertFalse(target.exists()); self.assertEqual(session.post.call_count, 1)

    def test_complete_stream_preserves_exact_official_bytes(self):
        session = MagicMock()
        response = session.post.return_value.__enter__.return_value
        response.status_code = 200; response.headers = {}
        response.iter_content.return_value = [self.content[:100], self.content[100:]]
        target = self.root / 'complete' / 'original.xlsx'
        export_once(session, 'lanorange', DATASETS['lanorange_rider_archive'][1],
                    {'pageNum': 1, 'pageSize': 10}, target, threading.Event())
        self.assertEqual(target.read_bytes(), self.content)
        self.assertEqual(session.post.call_args.kwargs['data'], 'pageNum=1&pageSize=10&')
        info = json.loads((target.parent / 'http_submission.json').read_text(encoding='utf-8'))
        self.assertEqual(info['submission_state'], 'submitted')
        self.assertEqual(info['sha256'], hashlib.sha256(self.content).hexdigest())

    def test_mixed_scope_has_one_global_item_not_one_per_city(self):
        config = validate_request({'cities':['泉州','上海'],'datasets':['rider_info','lanorange_rider_archive'],
                                   'start':'2026-09-01','end':'2026-09-02'})
        self.assertEqual(len(_requested_items(config)),3)
        self.assertEqual(len([i for i in _initial_items(config) if i['dataset']=='lanorange_rider_archive']),1)

    def test_manager_publishes_all_originals_and_zip(self):
        def execute(config, root, log, cancel, update):
            with patch('lanorange_download.collect', side_effect=self.fake_collect), \
                 patch('rider_archive.format_full_workbook', side_effect=passthrough_format):
                return execute_downloads(config, root, log, cancel, update)
        manager = DownloadManager(self.root / 'db/tasks.sqlite3', self.root / 'outputs', execute)
        try:
            run = manager.create('test',self.config()); deadline=time.monotonic()+10
            while time.monotonic()<deadline:
                run=manager.get_run('test',run['id'])
                if run['status'] in FINAL_STATUSES:break
                threading.Event().wait(.02)
            self.assertEqual(run['status'],'success',run.get('error'));self.assertEqual(len(run['files']),8)
            for entry in run['files']:
                file,_=manager.get_file('test',run['id'],entry['id']); self.assertEqual(file.read_bytes(),self.content)
            bundle=manager.get_bundle('test',run['id'])
            with zipfile.ZipFile(bundle[0]) as archive:
                self.assertEqual(len(archive.namelist()),8)
                self.assertNotIn('文件清单.csv',archive.namelist())
            receipt,_=manager.get_summary('test',run['id'])
            self.assertIn('全部状态',receipt.read_text(encoding='utf-8-sig'))
        finally:manager.shutdown()

    def test_unknown_submission_is_never_automatically_retried(self):
        def execute(config, root, log, cancel, update):
            item=_initial_items(config)[0];raw=source_directory(root,item['city'],item['dataset']);raw.mkdir(parents=True)
            atomic_json(raw/'http_submission.json',{'submission_state':'unknown'})
            update({**item,'status':'error','error':'导出未确认','submission_state':'unknown'})
            return []
        manager=DownloadManager(self.root/'db/tasks.sqlite3',self.root/'outputs',execute)
        try:
            config=self.config();config['datasets']=[next(iter(DATASETS))]
            run=manager.create('test',config);deadline=time.monotonic()+10
            while time.monotonic()<deadline:
                run=manager.get_run('test',run['id'])
                if run['status'] in FINAL_STATUSES:break
                threading.Event().wait(.02)
            self.assertEqual(run['items'][0]['recovery']['mode'],'blocked')
        finally:manager.shutdown()


if __name__ == '__main__':unittest.main()
