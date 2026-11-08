import asyncio
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from fastapi import HTTPException

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import workbench
import payroll_inputs as inputs
import test_payroll_inputs as fixtures


class DeductionVersionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / 'data').mkdir()
        self.rows = [{'城市': '测试城', '团队名称': '站点', '团队ID': '00123', '投诉': 5, '扩展说明': '原样保留'}]
        self.write(self.rows)

    def write(self, rows):
        (self.root / 'data/config.json').write_text(json.dumps(rows), encoding='utf-8')

    def test_default_snapshot_survives_later_default_changes(self):
        snapshot = workbench.deduction_snapshot({}, self.root)
        self.write([{**self.rows[0], '投诉': 200}])
        reused = workbench.deduction_snapshot({'deductions': snapshot}, self.root)
        self.assertEqual(reused['rows'][0]['投诉'], 5)
        self.assertEqual(reused['rows'][0]['团队ID'], '00123')
        self.assertEqual(reused['rows'][0]['扩展说明'], '原样保留')
        self.assertEqual(reused['version'], snapshot['version'])

    def test_batch_override_does_not_modify_defaults(self):
        rows = [{**self.rows[0], '投诉': 10}]
        snapshot = workbench.deduction_snapshot({'deductions': {'rows': rows, 'version': workbench.version(rows), 'scope': 'batch'}}, self.root)
        self.assertEqual(snapshot['rows'][0]['投诉'], 10)
        self.assertEqual(workbench.read_defaults(self.root)['rows'][0]['投诉'], 5)
        self.assertTrue(snapshot['frozen'])

    def test_tampered_snapshot_and_invalid_rules_are_rejected(self):
        snapshot = workbench.deduction_snapshot({}, self.root)
        snapshot['rows'][0]['投诉'] = 999
        with self.assertRaisesRegex(inputs.SourceError, '校验失败'):
            workbench.deduction_snapshot({'deductions': snapshot}, self.root)
        for rows in ([], [self.rows[0], self.rows[0]], [{'城市': '测试'}], [{**self.rows[0], '投诉': float('nan')}], [{**self.rows[0], '投诉': {}}]):
            with self.assertRaises(inputs.SourceError):
                workbench.validate_rows(rows)

    def test_default_save_conflict_and_backup(self):
        current = workbench.read_defaults(self.root)
        class Request:
            async def json(inner):
                return {'rows': [{**self.rows[0], '投诉': 20}], 'version': current['version']}
        with patch.object(workbench, 'ROOT', self.root), patch('download_accounts.require_admin'):
            response = asyncio.run(workbench.save_defaults(Request()))
            self.assertNotEqual(response['version'], current['version'])
            backups = list((self.root / 'data/config_history').glob('*.json'))
            self.assertEqual(json.loads(backups[0].read_text(encoding='utf-8')), self.rows)
            with self.assertRaises(HTTPException) as raised:
                asyncio.run(workbench.save_defaults(Request()))
            self.assertEqual(raised.exception.status_code, 409)


class ReuseTests(unittest.TestCase):
    def setUp(self):
        self.state = {'download_owner': 'download_shared', 'plan': {'city': '测试城', 'start': '2026-08-16', 'end': '2026-08-31', 'month': '2026-08'}, 'items': {'delivery_fee': {'status': 'pending'}, 'rider_monthly': {'status': 'pending'}}}
        self.file = {'id': 'file', 'name': '配送费.csv', 'city': '测试城', 'dataset': 'delivery_fee', 'start': '2026-08-16', 'end': '2026-08-31'}
        self.run = {'id': 'run', 'status': 'success', 'files': [self.file], 'items': [{**self.file, 'status': 'success'}]}
        self.manager = SimpleNamespace(list_runs=lambda owner: [self.run], get_run=lambda owner, key: self.run)

    def test_reuse_rejects_other_city_period_and_partial_exports(self):
        self.assertEqual(len(workbench.reusable_files(self.state, self.manager)), 1)
        for field, value in [('city', '其他城'), ('start', '2026-08-01')]:
            old = self.file[field]
            self.file[field] = value
            self.assertEqual(workbench.reusable_files(self.state, self.manager), [])
            self.file[field] = old
        self.run['status'] = 'partial'
        self.assertEqual(workbench.reusable_files(self.state, self.manager), [])

    def test_monthly_requires_complete_month(self):
        self.file['dataset'] = 'rider_monthly'
        self.assertEqual(workbench.reusable_files(self.state, self.manager), [])
        self.file['start'] = '2026-08-01'
        self.run['items'] = [{**self.file, 'status': 'success'}]
        self.assertEqual(len(workbench.reusable_files(self.state, self.manager)), 1)


class PreparationGateTests(unittest.TestCase):
    setUp = fixtures.PayrollInputTests.setUp
    delivery = fixtures.PayrollInputTests.delivery
    def test_automatic_batch_starts_download_without_confirmation(self):
        config = SimpleNamespace(sourcePath=str(self.source), payrollSourceMode='fengshen', payrollPreparationId='', preparationOnly=True)
        with patch.object(inputs, 'workspace', return_value='tester'), patch.object(inputs, 'account', return_value='download_shared'), patch('download_jobs.get_manager') as manager, patch('payroll_automatic.prepare_scope'), patch.object(inputs,'start_download_resumable',side_effect=inputs.SourceError('合成下载暂停')) as start:
            async def collect():
                return [event async for event in inputs.run_payroll(config, None)]
            events = asyncio.run(collect())
        manager.assert_called_once();start.assert_called_once()
        decoded = [json.loads(event[6:]) for event in events if event.startswith('data: ')]
        preparations = [event['preparation'] for event in decoded if event['type'] == 'payroll_preparation']
        self.assertTrue(preparations)
        self.assertTrue(all(p['status'] != 'awaiting_confirmation' for p in preparations))
        self.assertEqual(preparations[-1]['status'], 'error')

    def test_preparation_only_never_calls_calculation(self):
        self.delivery()
        config = SimpleNamespace(sourcePath=str(self.source), payrollSourceMode='manual', payrollPreparationId='', preparationOnly=True)
        with patch.object(inputs, 'workspace', return_value='tester'), patch('tasks.run_main_calculation_gen') as calculate:
            async def collect():
                return [event async for event in inputs.run_payroll(config, None)]
            events = asyncio.run(collect())
        calculate.assert_not_called()
        decoded = [json.loads(event[6:]) for event in events if event.startswith('data: ')]
        self.assertEqual(decoded[-1]['status'], 'paused')
        preparation = next(event['preparation'] for event in decoded if event['type'] == 'payroll_preparation')
        _, state = inputs.load('tester', preparation['id'])
        self.assertEqual(state['status'], 'ready')
        self.assertNotIn('deductions', state)

    def test_changed_rules_stop_before_calculation(self):
        self.delivery()
        config = SimpleNamespace(sourcePath=str(self.source), payrollSourceMode='manual', payrollPreparationId='', preparationOnly=False, deductionConfigVersion='old-version')
        with patch.object(inputs, 'workspace', return_value='tester'), patch('workbench.deduction_snapshot', return_value={'version': 'new-version', 'rows': []}), patch('tasks.run_main_calculation_gen') as calculate:
            async def collect():
                return [event async for event in inputs.run_payroll(config, None)]
            with self.assertRaisesRegex(inputs.SourceError, '请先确认'):
                asyncio.run(collect())
        calculate.assert_not_called()
        manifest = next((self.root / 'uploads/tester').glob('payroll_*/manifest.json'))
        self.assertEqual(json.loads(manifest.read_text(encoding='utf-8'))['status'], 'ready')


class DetachedRunTests(unittest.IsolatedAsyncioTestCase):
    async def test_disconnect_keeps_worker_running(self):
        completed = asyncio.Event()
        async def worker():
            yield 'first'
            await asyncio.sleep(.02)
            completed.set()
            yield 'done'
        stream = workbench.detached_events(worker())
        self.assertEqual(await anext(stream), 'first')
        await stream.aclose()
        await asyncio.wait_for(completed.wait(), 1)


if __name__ == '__main__':
    unittest.main()
