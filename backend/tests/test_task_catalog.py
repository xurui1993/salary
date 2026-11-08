import copy
import datetime as dt
import json
from pathlib import Path
import sys
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import task_catalog as catalog
import download_service as service
import download_jobs as jobs
import download_records
import workbench
from test_download_jobs import make_file, request


class IntentTests(unittest.TestCase):
    def test_three_generation_scopes_and_dependency_catalog(self):
        values = {value['id']: value for value in catalog.generators()}
        self.assertEqual(set(values), set(catalog.GENERATORS))
        self.assertEqual(values['abnormal_riders']['scope'], 'all')
        self.assertEqual(values['payment_binding']['scope'], 'city_month')
        self.assertEqual(len(values['abnormal_riders']['sources']), 5)
        self.assertIn('骑手支付绑定（生成表）', values['abnormal_followup']['sources'])
        for value in values.values():
            self.assertTrue(value['label'])
            self.assertTrue(value['systems'])
            self.assertIn(value['scope'], ('city_month','city_range','all'))
            self.assertIn(value['station_rule'], ('separation','none'))
            self.assertFalse(any(key.startswith('_') for key in value))

    def test_raw_and_generation_requests_cannot_mix_business_intent(self):
        self.assertEqual(catalog.intent({'datasets': ['payment_binding']}), {})
        for payload in ({'task_kind': 'download', 'datasets': ['payment_binding']},
                        {'task_kind': 'generate', 'generation_target': 'payment_binding', 'datasets': ['payment_binding', 'delivery_fee']},
                        {'task_kind': 'generate', 'generation_target': 'unknown', 'datasets': ['unknown']},
                        {'task_kind': 'payroll_source', 'datasets': ['delivery_fee']}):
            with self.assertRaises(ValueError): catalog.intent(payload)

    def test_global_generation_ignores_city_and_date_but_keeps_intent(self):
        config = service.validate_request({'task_kind': 'generate', 'generation_target': 'abnormal_riders',
            'datasets': ['abnormal_riders'], 'cities': [], 'start': 'invalid', 'end': 'invalid'}, today=dt.date(2026, 10, 25))
        self.assertEqual(config['cities'], ['全部城市'])
        self.assertEqual(config['generation_target'], 'abnormal_riders')
        self.assertEqual(config['task_kind'], 'generate')

    def test_city_generation_requires_valid_city_and_dates(self):
        with patch.object(service.city_catalog, 'selectable_cities', return_value={'泉州': '31029436'}):
            value = {'task_kind': 'generate', 'generation_target': 'payment_binding', 'datasets': ['payment_binding'],
                     'cities': ['泉州'], 'start': '2026-09-01', 'end': '2026-10-15'}
            config = service.validate_request(value, today=dt.date(2026, 10, 25))
            self.assertEqual(config['months'], ['2026-09', '2026-10'])
            with self.assertRaises(service.ValidationError): service.validate_request({**value, 'cities': []})


class UnifiedTaskTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup); self.root = Path(self.temp.name)
    def manifest(self, wid, key, job, output=''):
        state = {'id': key, 'mode': 'fengshen', 'status': 'calculated' if output else 'ready',
                 'plan': {'city': '泉州', 'start': '2026-10-01', 'end': '2026-10-15', 'applicants': 2},
                 'items': {'delivery_fee': {'label': '配送费', 'status': 'ready'}}, 'jobs': [job], 'created_at': '2026-10-25T10:00:00'}
        if output: state['result'] = {'output': output}
        directory = self.root / 'uploads' / wid / ('payroll_' + key); directory.mkdir(parents=True)
        (directory / 'manifest.json').write_text(json.dumps(state), encoding='utf-8')
    def fixture_run(self, key, kind='download', datasets=None, parent=None):
        kinds = datasets or ['delivery_fee']
        value = {'id': key, 'task_kind': kind, 'cities': ['泉州'], 'datasets': kinds, 'status': 'success', 'created_at': '2026-10-25T10:00:00',
                 'start': '2026-10-01', 'end': '2026-10-15', 'items': [], 'files': []}
        if parent: value['retry_of'] = parent
        for index, item in enumerate(kinds):
            value['items'].append({'city': '泉州', 'dataset': item, 'start': value['start'], 'end': value['end'], 'status': 'success'})
            value['files'].append({'id': key + str(index), 'name': item+'.csv', 'city': '泉州', 'dataset': item, 'start': value['start'], 'end': value['end'], 'available': True, 'bytes': 1})
        return value
    def test_payroll_sources_hidden_under_parent_and_other_workspaces_not_exposed(self):
        output = self.root / 'output'; output.mkdir()
        self.manifest('tester', 'a'*32, 'source', str(output))
        self.manifest('other', 'b'*32, 'private_source')
        source = self.fixture_run('source', 'payroll_source'); retry = self.fixture_run('retry', 'download', parent='source')
        ordinary = self.fixture_run('ordinary'); private = self.fixture_run('private_source')
        manager = SimpleNamespace(record_snapshots=lambda owner: [source, retry, ordinary, private])
        with patch.object(workbench, 'ROOT', self.root), patch('download_jobs.get_manager', return_value=manager):
            result = workbench.task_records(request(owner='tester'))['records']
        self.assertEqual(len(result), 2)
        self.assertEqual({item['kind'] for item in result}, {'download', 'payroll'})
        payroll = next(item for item in result if item['kind'] == 'payroll')
        self.assertEqual(payroll['batch_id'], 'a'*32)
        self.assertEqual(payroll['available_files'], 1)
        self.assertNotIn('b'*32, json.dumps(result))

    def test_generation_results_and_sources_are_separated(self):
        value = self.fixture_run('generated', 'generate', ['abnormal_riders'])
        value['files'].append({**value['files'][0], 'id': 'source-file', 'name': '档案.csv', 'dataset': 'lanorange_rider_archive'})
        manager = SimpleNamespace(record_snapshots=lambda owner: [value])
        with patch.object(workbench, 'ROOT', self.root), patch('download_jobs.get_manager', return_value=manager):
            record = workbench.task_records(request(owner='tester'))['records'][0]
        self.assertEqual(record['available_files'], 1)
        self.assertEqual(record['files'][0]['dataset'], 'abnormal_riders')
        self.assertEqual(record['source_files'][0]['id'], 'source-file')


class DurableIntentTests(unittest.TestCase):
    def test_intent_persists_and_result_bundle_excludes_automatic_sources(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            def execute(config, directory, log, cancelled, update_item):
                files = []
                for item in jobs._initial_items(config):
                    file = make_file(directory, {**config, 'cities': [item['city']]}, item['dataset'], item['dataset']+'.csv', item['start'], item['end'])
                    if item['dataset']!='abnormal_riders':
                        raw=directory/'原始资料/全部城市'/item['dataset'];raw.mkdir(parents=True)
                        (raw/(item['dataset']+'.csv')).write_text(item['dataset'],encoding='utf-8')
                    update_item({**file, 'status': 'success'}); files.append(file)
                return files
            manager = jobs.DownloadManager(root/'db/tasks.sqlite3', root/'outputs', execute)
            try:
                config = service.validate_request({'task_kind': 'generate', 'generation_target': 'abnormal_riders', 'datasets': ['abnormal_riders']})
                created = manager.create('tester', config, request_id='category_test_01')
                deadline = time.monotonic()+5
                while time.monotonic() < deadline:
                    result = manager.get_run('tester', created['id'])
                    if result['status'] in jobs.FINAL_STATUSES: break
                    time.sleep(.01)
                self.assertEqual(result['status'], 'success', result.get('error'))
                self.assertEqual(result['task_kind'], 'generate')
                self.assertEqual(result['generation_target'], 'abnormal_riders')
                again = manager.create('tester', config, request_id='category_test_01')
                self.assertEqual(created['id'], again['id'])
                for purpose, checklist, count in [('results', None, 1), ('sources', '来源清单.csv', 5)]:
                    path, _ = download_records.record_bundle(manager, 'tester', created['id'], purpose=purpose)
                    with zipfile.ZipFile(path) as archive:
                        names=archive.namelist()
                        if checklist is None:
                            self.assertNotIn('文件清单.csv',names)
                            self.assertNotIn('任务清单.csv',names)
                        else:
                            self.assertIn(checklist,names)
                        self.assertEqual(len([name for name in names if name!=checklist]),count)
                        self.assertFalse(any('/' in name or name.endswith('.json') for name in names))
                    path.unlink()
                legacy = {'cities': ['泉州'], 'datasets': ['delivery_fee'], 'start': '2026-10-01', 'end': '2026-10-15', 'months': ['2026-10']}
                self.assertNotIn('task_kind', service.validate_request({**legacy, 'cities':['全部城市'], 'datasets':['abnormal_riders']}))
            finally: manager.shutdown()


if __name__ == '__main__': unittest.main()
