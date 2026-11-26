import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pandas as pd

sys.path.insert(0, str(Path(__file__).parents[1]))
import issue_rules
from issue_orders import DataCleaner

COLUMNS = ['运单id', '运单状态', '运单类型', '是否超平台期望时间', '平台期望时间', '运单完成时间',
           '站点名称', '配送标品', '订单来源', '是否超骑手T', '是否二呼单', '超平台期望送达时长']


def waybill(number, station='广州站', finish='2026-11-25 10:08:20', expected='2026-11-25 10:00:00',
            kind='即时单', product='普通', origin='商家', carrier='否', second='否', over='是'):
    return {'运单id': str(number), '运单状态': '配送成功', '运单类型': kind,
            '是否超平台期望时间': over, '平台期望时间': expected, '运单完成时间': finish,
            '站点名称': station, '配送标品': product, '订单来源': origin,
            '是否超骑手T': carrier, '是否二呼单': second, '超平台期望送达时长': '20分钟'}


def cleaner(frame, config=None):
    empty = pd.DataFrame(columns=['日期', '违规状态', '申诉状态'])
    return DataCleaner.from_frames(frame, empty, issue_rules=config)


def ids(frame):
    return sorted(frame['运单id'].tolist())


class RuleEngineTests(unittest.TestCase):
    def test_defaults_keep_boundary_and_include_sanya_darunfa(self):
        rows = [
            waybill(1, station='三亚站', finish='2026-11-25 10:08:20'),
            waybill(2, station='三亚大润发店', finish='2026-11-25 09:55:00', carrier='是'),
            waybill(3, station='大润发广州店', finish='2026-11-25 10:08:20'),
            waybill(4, finish='2026-11-25 10:01:40'),
            waybill(5, finish='2026-11-25 10:00:10', product='星专送'),
            waybill(6, finish='2026-11-25 10:08:20', second='是'),
        ]
        frame = pd.DataFrame(rows, columns=COLUMNS)
        result = cleaner(frame).notpunctual()
        self.assertEqual(ids(result), ['1', '2', '5'])

    def test_second_call_rule_is_configurable(self):
        frame = pd.DataFrame([waybill(1, second='是'), waybill(2)], columns=COLUMNS)
        config = issue_rules.default_config()
        config['rules'] = [rule for rule in config['rules'] if rule['id'] != 'exclude-second-call']
        self.assertEqual(ids(cleaner(frame).notpunctual()), ['2'])
        self.assertEqual(ids(cleaner(frame, config).notpunctual()), ['1', '2'])

    def test_grace_seconds_and_strict_conditions_come_from_config(self):
        frame = pd.DataFrame([waybill(1, finish='2026-11-25 10:00:40'),
                              waybill(2, finish='2026-11-25 10:00:10', product='星专送')], columns=COLUMNS)
        config = issue_rules.default_config()
        config['grace_seconds'] = 30
        config['strict_conditions'] = []
        self.assertEqual(ids(cleaner(frame, config).notpunctual()), ['1'])

    def test_missing_column_only_warns_and_keeps_other_rules(self):
        frame = pd.DataFrame([waybill(1, second='是'), waybill(2)], columns=COLUMNS).drop(columns=['是否二呼单'])
        instance = cleaner(frame)
        self.assertEqual(ids(instance.notpunctual()), ['1', '2'])
        self.assertEqual(instance.rule_warnings, {'是否二呼单'})

    def test_validation_rejects_unknown_operator_and_bad_grace(self):
        with self.assertRaises(issue_rules.IssueRuleError):
            issue_rules.normalize_condition({'field': '站点名称', 'op': 'sql', 'value': 'x'})
        with self.assertRaises(issue_rules.IssueRuleError):
            issue_rules.normalize_config({'grace_seconds': -1, 'rules': []})
        with self.assertRaises(issue_rules.IssueRuleError):
            issue_rules.normalize_rule({'action': 'exclude', 'conditions': []})

    def test_preview_reports_saved_versus_candidate_counts(self):
        frame = pd.DataFrame([waybill(1, second='是'), waybill(2)], columns=COLUMNS)
        candidate = issue_rules.default_config()
        candidate['rules'] = [rule for rule in candidate['rules'] if rule['id'] != 'exclude-second-call']
        result = issue_rules.preview(frame, candidate, issue_rules.default_config())
        self.assertEqual((result['before'], result['after'], result['delta']), (1, 2, 1))


class RuleStorageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=Path(__file__).parent)
        self.addCleanup(self.temp.cleanup)
        self.patch = patch('workspace_context.workspace_data_root', return_value=Path(self.temp.name))
        self.patch.start()
        self.addCleanup(self.patch.stop)

    def test_save_load_and_reset_are_scoped_per_city(self):
        config = issue_rules.default_config()
        config['grace_seconds'] = 120
        issue_rules.save_city('广州', config)
        data = issue_rules.load()
        self.assertEqual(data['cities']['广州']['grace_seconds'], 120)
        self.assertNotIn('深圳', data['cities'])
        self.assertEqual(issue_rules.default_config()['grace_seconds'], 480)
        self.assertEqual(issue_rules.config_for('深圳')['grace_seconds'], 480)
        issue_rules.reset_city('广州')
        self.assertNotIn('广州', issue_rules.load()['cities'])

    def test_corrupt_config_is_reported_not_ignored(self):
        path = Path(self.temp.name) / 'data' / 'issue_rules' / 'fengshen.json'
        path.parent.mkdir(parents=True)
        path.write_text(json.dumps({'cities': {'广州': {'grace_seconds': 'x', 'rules': []}}}), encoding='utf-8')
        with self.assertRaises(issue_rules.IssueRuleError):
            issue_rules.load()


class SampleDiscoveryTests(unittest.TestCase):
    def setUp(self):
        import download_jobs
        self.temp = tempfile.TemporaryDirectory(dir=Path(__file__).parent)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.manager = download_jobs.DownloadManager(self.root / 'db' / 'tasks.sqlite3', self.root / 'outputs',
                                                     lambda *args: None)
        self.addCleanup(self.manager.shutdown, False)

    def insert_run(self, run_id, cities, dataset='problem', status='success'):
        directory = self.root / 'outputs' / run_id / '原始资料' / cities[0] / 'issue_orders' / '2026-11-01_2026-11-02'
        directory.mkdir(parents=True)
        (directory / 'waybills.xlsx').write_bytes(b'sample')
        state = {'id': run_id, 'cities': cities, 'datasets': [dataset], 'status': status,
                 'start': '2026-11-01', 'end': '2026-11-02', 'created_at': '2026-11-26T00:00:00'}
        with self.manager._connection() as connection:
            connection.execute('INSERT INTO download_runs(id, owner, created_at, status, config_json, state_json) '
                               'VALUES (?, ?, ?, ?, ?, ?)',
                               (run_id, 'owner', state['created_at'], status, '{}', json.dumps(state)))

    def test_finds_newest_retained_problem_sample(self):
        from download_jobs import DownloadNotFound
        self.insert_run('a' * 32, ['广州'])
        sample = self.manager.order_sample_dir('owner', '广州')
        self.assertEqual(sample['run_id'], 'a' * 32)
        self.assertTrue(sample['path'].name.startswith('waybills'))
        with self.assertRaises(DownloadNotFound):
            self.manager.order_sample_dir('owner', '深圳')

    def test_finds_samples_in_nested_archive_layout(self):
        run_id = 'd' * 32
        directory = (self.root / 'outputs' / run_id / '原始资料' / '平台读取' / 'selected' / '其他资料' / 'fraud'
                     / '原始资料' / '三亚' / 'issue_orders' / '2026-11-15_2026-11-21')
        directory.mkdir(parents=True)
        (directory / 'waybills.xlsx').write_bytes(b'sample')
        state = {'id': run_id, 'cities': ['三亚'], 'datasets': ['problem'], 'status': 'success',
                 'start': '2026-11-15', 'end': '2026-11-21', 'created_at': '2026-11-26T00:00:00'}
        with self.manager._connection() as connection:
            connection.execute('INSERT INTO download_runs(id, owner, created_at, status, config_json, state_json) '
                               'VALUES (?, ?, ?, ?, ?, ?)',
                               (run_id, 'owner', state['created_at'], 'success', '{}', json.dumps(state)))
        sample = self.manager.order_sample_dir('owner', '三亚')
        self.assertEqual(sample['run_id'], run_id)
        self.assertEqual(sample['path'].name, 'waybills.xlsx')

    def test_ignores_failed_runs_without_problem_dataset(self):
        from download_jobs import DownloadNotFound
        self.insert_run('b' * 32, ['广州'], dataset='delivery_waybill')
        self.insert_run('c' * 32, ['广州'], status='failed')
        with self.assertRaises(DownloadNotFound):
            self.manager.order_sample_dir('owner', '广州')


if __name__ == '__main__':
    unittest.main()