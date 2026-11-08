import copy
import asyncio
import json
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import patch
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import download_records as records
import download_jobs as jobs
import download_routes as routes
from test_download_jobs import make_file, request


def run(key, status='success', parent=None, kinds=('delivery_fee',), created='2026-10-25T10:00:00'):
    result = {'id': key, 'status': status, 'created_at': created, 'cities': ['泉州'], 'datasets': list(kinds),
              'start': '2026-10-01', 'end': '2026-10-05', 'files': [], 'items': []}
    for kind in kinds:
        item = {'city': '泉州', 'dataset': kind, 'start': result['start'], 'end': result['end'], 'status': status}
        result['items'].append(item)
        if status == 'success':
            result['files'].append({**item, 'id': key + kind, 'name': kind + '.csv', 'bytes': 1, 'available': True})
    if parent:
        result['retry_of'] = parent
    return result


class GroupingTests(unittest.TestCase):
    def test_successful_retry_updates_state_and_keeps_original_success(self):
        original = run('original', kinds=('delivery_fee', 'penalty'))
        original['status'] = 'partial'; original['items'][1]['status'] = 'error'; original['files'] = original['files'][:1]
        retry = run('retry', parent='original', kinds=('penalty',), created='2026-10-25T10:01:00')
        result = records.group_records([retry, original])
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]['status'], 'success')
        self.assertEqual(result[0]['available_files'], 2)
        self.assertEqual(result[0]['failed_items'], 0)
        self.assertEqual(result[0]['member_ids'], ['original', 'retry'])
        self.assertEqual({file['run_id'] for file in result[0]['files']}, {'original', 'retry'})

    def test_active_and_failed_latest_attempts_do_not_show_completed(self):
        original = run('original', status='error')
        for state in ('running', 'waiting_login', 'error'):
            child = run('child', status=state, parent='original', created='2026-10-25T10:01:00')
            record = records.group_records([original, child])[0]
            self.assertEqual(record['status'], state)
            self.assertEqual(record['action_run_id'], 'child')

    def test_independent_same_scope_runs_remain_separate(self):
        self.assertEqual(len(records.group_records([run('a'), run('b')])), 2)

    def test_summary_failure_is_not_presented_as_complete(self):
        original = run('a'); original['status'] = 'partial'; original['summary_progress'] = {'stage': 'failed'}
        record = records.group_records([original])[0]
        self.assertEqual(record['status'], 'partial')
        self.assertTrue(record['summary_issue'])

    def test_recovery_chains_group_and_missing_or_cyclic_links_do_not_disappear(self):
        a = run('a'); b = run('b', parent='a'); c = run('c'); c['recovery_of'] = 'b'
        self.assertEqual(len(records.group_records([a, b, c])), 1)
        missing = run('missing', parent='not_loaded')
        self.assertTrue(records.group_records([missing])[0]['incomplete_lineage'])
        a['retry_of'] = 'b'
        result = records.group_records([a, b, missing])
        self.assertEqual({entry['id'] for entry in result}, {'a', 'b', 'missing'})

    def test_latest_file_version_and_old_summaries_are_not_mixed(self):
        original = run('a')
        original['files'].append({**original['files'][0], 'id': 'summary', 'artifact_role': 'summary'})
        retry = run('b', parent='a', created='2026-10-25T10:01:00')
        result = records.group_records([original, retry])[0]
        ordinary = [file for file in result['files'] if not file.get('artifact_role')]
        self.assertEqual([file['run_id'] for file in ordinary], ['b'])
        summary = next(file for file in result['files'] if file.get('artifact_role'))
        self.assertFalse(summary['available'])
        self.assertTrue(summary['outdated'])
        self.assertEqual(len(original['files']), 2)


class StorageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=Path(__file__).parent)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.patch = patch.object(jobs, '_configured_cities', return_value={'泉州': '31029436'})
        self.patch.start(); self.addCleanup(self.patch.stop)
        def executor(config, directory, emit, cancelled, update_item):
            files = []
            for kind in config['datasets']:
                file = make_file(directory, config, dataset=kind, name=kind + '.csv')
                update_item({**file, 'status': 'success'})
                files.append(file)
            return files
        self.manager = jobs.DownloadManager(self.root / 'db/tasks.sqlite3', self.root / 'outputs', executor, flat_delivery=False)
        self.addCleanup(self.manager.shutdown)

    def create(self, owner='tester', kinds=('delivery_fee',)):
        config = {'cities': ['泉州'], 'datasets': list(kinds), 'start': '2026-10-01', 'end': '2026-10-05', 'months': ['2026-10']}
        value = self.manager.create(owner, config)
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            value = self.manager.get_run(owner, value['id'])
            if value['status'] in jobs.FINAL_STATUSES:
                self.assertEqual(value['status'], 'success')
                return value
            time.sleep(.01)
        self.fail('synthetic download timed out')

    def test_bundle_combines_current_files_from_parent_and_retry_and_isolates_owners(self):
        parent = self.create(kinds=('delivery_fee', 'penalty'))
        def partial(value):
            value['status'] = 'partial'; value['items'][1]['status'] = 'error'
            value['files'] = [file for file in value['files'] if file['dataset'] == 'delivery_fee']
        self.manager._mutate('tester', parent['id'], partial)
        child = self.create(kinds=('penalty',))
        self.manager._mutate('tester', child['id'], lambda value: value.update(retry_of=parent['id']))
        record = records.list_records(self.manager, 'tester')[0]
        self.assertEqual(record['available_files'], 2)
        self.assertEqual(record['status'], 'success')
        self.assertEqual(records.list_records(self.manager, 'other'), [])
        with self.assertRaises(jobs.DownloadNotFound):
            records.record_bundle(self.manager, 'other', parent['id'])
        target, _ = records.record_bundle(self.manager, 'tester', parent['id'])
        with zipfile.ZipFile(target) as archive:
            receipt = json.loads(archive.read('下载说明.json'))
            self.assertEqual(len(receipt['files']), 2)
            self.assertEqual(len([name for name in archive.namelist() if name.endswith('.csv') and name != '任务清单.csv']), 2)
            self.assertIn('任务清单.csv', archive.namelist())
            self.assertTrue(any(name.startswith('结果/泉州/') for name in archive.namelist()))
        self.assertNotIn('relative_path', json.dumps(record))
        self.assertNotIn('sha256', json.dumps(record))

    def test_task_center_bulk_download_and_directory_use_existing_verified_files(self):
        import task_center as center
        from test_task_center import request as center_request
        first=self.create(kinds=('delivery_fee',))
        second=self.create(kinds=('penalty',))
        with patch.object(jobs,'get_manager',return_value=self.manager),patch.object(center,'collect',return_value=(records.list_records(self.manager,'tester'),[])):
            response=center.batch_bundle({'ids':[first['id'],second['id']]},center_request('POST'))
            with zipfile.ZipFile(response.path) as archive:
                self.assertEqual(len(archive.namelist()),2)
                for name in archive.namelist():
                    import io
                    with zipfile.ZipFile(io.BytesIO(archive.read(name))) as nested:
                        self.assertIn('任务清单.csv',nested.namelist())
                        self.assertTrue(any(value.startswith('结果/泉州/') for value in nested.namelist()))
            folder=center.directory(center_request(),first['id'])
            self.assertEqual(folder.parent.parent,self.manager.output_root)
            self.assertRegex(folder.parent.name,r'^\d{6}$')
            self.assertFalse((folder/'文件清单.csv').exists())
            self.assertTrue(any(path.suffix=='.csv' for path in folder.iterdir()))
            self.assertFalse(any(path.is_dir() for path in folder.iterdir()))
            asyncio.run(response.background())
            self.assertFalse(Path(response.path).exists())
            self.assertEqual(self.manager.get_run('tester',first['id'])['status'],'success')
    def test_missing_files_keep_records_and_available_files_can_still_be_downloaded(self):
        value = self.create(kinds=('delivery_fee', 'penalty'))
        path, _ = self.manager.get_file('tester', value['id'], value['files'][0]['id'])
        path.unlink()
        record = records.list_records(self.manager, 'tester')[0]
        self.assertEqual(record['available_files'], 1)
        self.assertEqual(len(record['files']), 2)
        self.assertTrue(any(file['unavailable_reason'] == '文件已不存在' for file in record['files']))
        target, _ = records.record_bundle(self.manager, 'tester', value['id'])
        with zipfile.ZipFile(target) as archive:
            self.assertEqual(len(json.loads(archive.read('下载说明.json'))['unavailable']), 1)

    def test_changed_contents_fail_bundle_and_remove_temporary_zip(self):
        value = self.create()
        path, _ = self.manager.get_file('tester', value['id'], value['files'][0]['id'])
        original = path.read_bytes(); path.write_bytes(b'x' * len(original))
        with self.assertRaisesRegex(jobs.DownloadNotFound, '变更'):
            records.record_bundle(self.manager, 'tester', value['id'])
        self.assertEqual(list((self.manager.db_path.parent / 'bundles').glob('record_*.zip')), [])

    def test_ancestors_outside_recent_list_limit_are_retained(self):
        value = self.create()
        with patch.object(self.manager, 'list_runs', return_value=[]):
            self.assertEqual(records.list_records(self.manager, 'tester')[0]['id'], value['id'])

    def test_record_route_preserves_authorization_and_cleans_download_zip(self):
        value = self.create()
        user = {'id': 'tester', 'role': 'member', 'owner': 'tester'}
        with patch.object(routes, 'get_manager', return_value=self.manager), patch.object(routes, 'require_account', return_value=user), patch.object(routes, 'audit_event'):
            self.assertEqual(len(routes.records(request())['records']), 1)
            response = routes.download_record_bundle(value['id'], request())
            target = Path(response.path)
            self.assertTrue(target.is_file())
            asyncio.run(response.background())
            self.assertFalse(target.exists())


if __name__ == '__main__':
    unittest.main()
