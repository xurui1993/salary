"""Standalone export, payroll exclusion, and submission-safety regressions."""
import datetime as dt
import json
from pathlib import Path
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import download_service as service
import download_jobs as jobs
import payroll_inputs
from binding_sources_http import BindingSources
from fengshen_bill import BillCollectionError, atomic_json
from openpyxl import Workbook


class BaizeStandaloneTests(unittest.TestCase):
    def config(self):
        return service.validate_request({'task_kind': 'download', 'datasets': ['baize_employees']},
                                        today=dt.date(2026, 10, 26))

    def test_scope_requires_no_fengshen_city_catalog_or_dates(self):
        with patch.object(service.city_catalog, 'selectable_cities', side_effect=AssertionError('not Fengshen')):
            config = self.config()
        self.assertEqual(config['cities'], ['全部城市'])
        self.assertEqual(config['datasets'], ['baize_employees'])
        self.assertEqual(len(jobs._initial_items(config)), 1)
        for selected in (['baize_employees', 'delivery_fee'], ['baize_employees', 'baize_employees']):
            with self.assertRaises(service.ValidationError):
                service.validate_request({'datasets': selected})

    def test_exports_and_publishes_without_fengshen_or_payroll(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            def employees(obj):
                obj.root.mkdir(parents=True)
                path = obj.root / 'employees.xlsx'
                book = Workbook(); book.active.append(['姓名']); book.save(path); book.close()
                return path
            updates = []
            with patch.object(BindingSources, 'employees', employees), \
                 patch.object(service, 'cities', side_effect=AssertionError('not Fengshen')), \
                 patch.object(service, '_open_runner', side_effect=AssertionError('no Fengshen browser')):
                files = service.execute_downloads(self.config(), root, lambda *_: None,
                                                 threading.Event(), updates.append)
            self.assertEqual(len(files), 1)
            self.assertTrue((root / files[0]['relative_path']).is_file())
            self.assertEqual(files[0]['dataset'], 'baize_employees')
            manifest = json.loads((root / 'manifest.json').read_text(encoding='utf-8'))
            self.assertFalse(manifest['payroll_executed'])
            self.assertEqual(manifest['items'][0]['status'], 'success')

    def test_unknown_export_receipt_blocks_unsafe_retry(self):
        with tempfile.TemporaryDirectory() as folder:
            def interrupted(obj):
                raw = obj.root / 'baize'; raw.mkdir(parents=True)
                atomic_json(raw / 'http_submission.json', {'submission_state': 'unknown'})
                raise BillCollectionError('导出结果未知')
            with patch.object(BindingSources, 'employees', interrupted):
                result = service.execute_downloads(self.config(), folder, lambda *_: None,
                                                   threading.Event(), lambda *_: None)
            self.assertEqual(result, [])
            state = json.loads((Path(folder) / 'manifest.json').read_text(encoding='utf-8'))
            self.assertEqual(state['items'][0]['submission_state'], 'unknown')

    def test_auth_failure_before_submission_is_retryable(self):
        with tempfile.TemporaryDirectory() as folder:
            with patch.object(BindingSources, 'employees', side_effect=BillCollectionError('认证失败')):
                service.execute_downloads(self.config(), folder, lambda *_: None, threading.Event(), lambda *_: None)
            state = json.loads((Path(folder) / 'manifest.json').read_text(encoding='utf-8'))
            self.assertEqual(state['items'][0]['submission_state'], 'not_submitted')

    def test_employee_export_does_not_query_or_compare_page_total(self):
        with tempfile.TemporaryDirectory() as folder:
            session = Mock(); session.__enter__ = Mock(return_value=session); session.__exit__ = Mock()
            with patch('binding_sources_http.authenticated', return_value=session), \
                 patch('binding_sources_http.identity', return_value={'user': {'userRelateId': 1}}), \
                 patch('binding_sources_http.query', return_value={}) as query, \
                 patch('binding_sources_http.export_once', return_value=Path(folder)/'employees.xlsx'), \
                 patch('binding_sources_http.validate_employees', return_value={'rows': 12}) as validate:
                BindingSources(folder, lambda *_: None, threading.Event()).employees()
            self.assertEqual(validate.call_args.kwargs, {})
            self.assertEqual(query.call_count, 1)
            self.assertEqual(query.call_args.args[2], 'web/merchantFreelancer/checkSecrecy')

    def test_payroll_does_not_enqueue_binding_or_baize(self):
        state = {'id': 'a'*32, 'plan': {'city': '泉州', 'start': '2026-10-01', 'end': '2026-10-15'},
                 'mode': 'fengshen', 'download_owner': 'shared', 'jobs': [],
                 'items': {kind: {'status': 'pending'} for kind in payroll_inputs.LABELS}}
        manager = Mock(); manager.create.return_value = {'id': 'job'}
        config = {'cities': ['泉州'], 'datasets': ['delivery_fee'], 'start': '2026-10-01', 'end': '2026-10-15', 'months': ['2026-10']}
        with tempfile.TemporaryDirectory() as folder, patch.object(service, 'validate_request', return_value=config):
            payroll_inputs.start_download(Path(folder), state, manager)
        submitted = manager.create.call_args.args[1]
        self.assertNotIn('payment_binding', submitted['datasets'])
        self.assertNotIn('baize_employees', submitted['datasets'])
        self.assertEqual(state['items']['payment_binding']['status'], 'failed')

    def test_persistent_manager_delivers_baize_and_reuses_request_id(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            def employees(obj):
                obj.root.mkdir(parents=True)
                path = obj.root / 'employees.xlsx'
                book = Workbook(); book.active.append(['姓名']); book.save(path); book.close()
                return path
            with patch.object(BindingSources, 'employees', employees), \
                 patch.object(jobs, '_configured_cities', return_value={'泉州': '31029436'}):
                manager = jobs.DownloadManager(root/'tasks.sqlite3', root/'outputs')
                try:
                    first = manager.create('tester', self.config(), request_id='baize_test_request')
                    second = manager.create('tester', self.config(), request_id='baize_test_request')
                    self.assertEqual(first['id'], second['id'])
                    deadline = time.monotonic()+5
                    while time.monotonic()<deadline:
                        run=manager.get_run('tester',first['id'])
                        if run['status'] in jobs.FINAL_STATUSES: break
                        time.sleep(.02)
                    self.assertEqual(run['status'],'success',run)
                    path, name=manager.get_file('tester', run['id'], run['files'][0]['id'])
                    self.assertTrue(path.is_file())
                    self.assertIn('白泽员工资料',name)
                finally:
                    manager.shutdown()

    def test_smart_source_is_limited_to_current_workspace_uploads(self):
        import main
        import parttime_source
        from starlette.requests import Request
        request = Request({'type':'http','headers':[(b'x-workspace-id',b'tester')]})
        with tempfile.TemporaryDirectory() as folder, patch.object(parttime_source, 'ROOT', Path(folder)):
            foreign=Path(folder)/'uploads/other/upload_old';foreign.mkdir(parents=True)
            (foreign/'template.xlsx').write_bytes(b'not parsed in path discovery')
            result=main.check_smart_source(main.SmartSourceRequest(basePath=str(foreign)),request)
            self.assertFalse(result['smart'])
            own=Path(folder)/'uploads/tester/upload_current';own.mkdir(parents=True)
            (own/'template.xlsx').write_bytes(b'not parsed in path discovery')
            result=main.check_smart_source(main.SmartSourceRequest(),request)
            self.assertEqual(Path(result['path']),own.resolve())
        self.assertFalse(any('salary_fulltime' in getattr(route,'path','') for route in main.app.routes))


if __name__ == '__main__':
    unittest.main()


class RetainedEmployeeExportTests(unittest.TestCase):
    def test_retained_export_requires_same_scope_hash_and_completed_receipt(self):
        from binding_sources_http import retained_employee_export
        import hashlib
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)/'employees.xlsx'
            params = {'merId': '1', 'pageNum': 1, 'pageSize': 10}
            self.assertFalse(retained_employee_export(path, params))
            path.write_bytes(b'retained-file')
            proof = {'source': 'baize', 'scope': params, 'submission_state': 'submitted',
                     'bytes': path.stat().st_size, 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}
            receipt = path.parent/'http_submission.json'
            atomic_json(receipt, proof)
            self.assertTrue(retained_employee_export(path, params))
            for changed in ({**proof, 'submission_state': 'unknown'}, {**proof, 'sha256': 'bad'},
                            {**proof, 'scope': {**params, 'merId': '2'}}):
                atomic_json(receipt, changed)
                with self.assertRaisesRegex(BillCollectionError, '不重复提交'):
                    retained_employee_export(path, params)
            self.assertEqual(path.read_bytes(), b'retained-file')
