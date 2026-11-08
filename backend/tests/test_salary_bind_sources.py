import asyncio
import csv
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from openpyxl import Workbook, load_workbook

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import salary_bind_sources as sources
from parttime_source import SourceError
from shangyi_sources import validate_employees
from test_shangyi_sources import HEADERS as EMPLOYEE_HEADERS, ROW as EMPLOYEE_ROW


class BindingSourceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.scope = sources.date_scope('2026-07-01', '2026-07-29')

    def tearDown(self):
        self.temp.cleanup()

    def fixture(self):
        results = []
        plans = sources.city_plans(['[31029436][泉州] 企业', '[31030116][深圳] 企业'], self.scope)
        for index, plan in enumerate(plans):
            directory = self.root / plan.agency_id
            directory.mkdir()
            team, rid = '测试站' + str(index), str(index + 100)
            tables = {
                'rider_info': [['骑手ID', '姓名', '部门', '身份证', '状态'], [rid, '测试', team, EMPLOYEE_ROW[1], '离职']],
                'rider_detail': [['日期', '骑手ID', '骑手姓名', '团队ID', '团队名称', '有效完成单'],
                                 [self.scope['start'], rid, '测试', str(index + 1), team, 2]],
                'receive_account': [['团队ID', '团队名称', '骑手ID', '收款方式', '收款账户', '收款账户姓名', '收款账户身份证'],
                                    [str(index + 1), team, rid, '银行卡', EMPLOYEE_ROW[3], '测试', EMPLOYEE_ROW[1]]],
            }
            datasets = {}
            for kind, rows in tables.items():
                path = directory / (kind + '.csv')
                with path.open('w', encoding='utf-8-sig', newline='') as stream:
                    csv.writer(stream).writerows(rows)
                datasets[kind] = {'path': path.name, 'sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
                                  'rows': 1, 'status': 'validated', 'city': plan.city, 'agency_id': plan.agency_id,
                                  'requested_start': plan.start, 'requested_end': plan.end,
                                  'requested_month': plan.month, 'all_target_teams': True}
            results.append((directory, {'status': 'success', 'plan': asdict(plan), 'datasets': datasets}))
        book = Workbook()
        book.active.append(EMPLOYEE_HEADERS)
        book.active.append(EMPLOYEE_ROW)
        path = self.root / 'merchantFreelancer.xlsx'
        book.save(path)
        book.close()
        employees = (self.root, {'status': 'success', 'scope': 'all',
                                 'datasets': {'merchant_employees': validate_employees(path, 1)}})
        return results, employees

    def test_dates_same_month_no_template_needed(self):
        self.assertEqual(self.scope['month'], '2026-07')
        for start, end in [('2026-07-30', '2026-08-01'), ('2026-07-30', '2026-07-01'),
                           ('', '2026-07-01'), ('2026-02-30', '2026-02-30')]:
            with self.subTest(start=start), self.assertRaises(SourceError):
                sources.date_scope(start, end)

    def test_city_list_complete_and_strict(self):
        plans = sources.city_plans(['[1][泉州] 企业', '[2][上海UB] 企业'], self.scope)
        self.assertEqual([plan.city for plan in plans], ['泉州', '上海UB'])
        for texts in ([], ['[1] 企业'], ['[1][泉州] 企业'] * 2):
            with self.assertRaises(SourceError):
                sources.city_plans(texts, self.scope)

    def test_merge_all_cities_preserves_originals_and_counts(self):
        results, employees = self.fixture()
        before = (results[0][0] / 'rider_info.csv').read_bytes()
        inputs = self.root / 'inputs'
        verified = sources.prepare_inputs(results, employees, inputs, self.scope)
        self.assertEqual(verified['team_cities'], {'测试站0': '泉州', '测试站1': '深圳'})
        self.assertEqual(verified['agency_count'], 2)
        self.assertEqual(len(list(inputs.iterdir())), 4)
        with (inputs / '骑手数据明细.csv').open(encoding='utf-8-sig', newline='') as stream:
            self.assertEqual(len(list(csv.DictReader(stream))), 2)
        self.assertEqual(before, (results[0][0] / 'rider_info.csv').read_bytes())

    def test_incomplete_city_and_wrong_dates_rejected(self):
        for change in ('state', 'date', 'scope', 'hash'):
            with self.subTest(change=change):
                results, employees = self.fixture()
                manifest = results[0][1]
                if change == 'state':
                    manifest['status'] = 'error'
                elif change == 'date':
                    manifest['plan']['start'] = '2026-07-02'
                elif change == 'scope':
                    manifest['datasets']['rider_detail']['all_target_teams'] = False
                else:
                    manifest['datasets']['rider_info']['sha256'] = 'invalid'
                with self.assertRaises(SourceError):
                    sources.prepare_inputs(results, employees, self.root / 'inputs', self.scope)
                self.temp.cleanup()
                self.temp = tempfile.TemporaryDirectory()
                self.root = Path(self.temp.name)

    def test_all_station_exports_merge_once_using_team_id_ownership(self):
        results, employees = self.fixture()
        detail_records = []
        for directory, manifest in results:
            _, records = sources.rows_from(directory / 'rider_detail.csv')
            detail_records.extend(records)
        for directory, manifest in results:
            info = manifest['datasets']['rider_detail']
            headers, _ = sources.rows_from(directory / info['path'])
            path = directory / info['path']
            with path.open('w', encoding='utf-8-sig', newline='') as stream:
                writer = csv.DictWriter(stream, fieldnames=headers)
                writer.writeheader()
                writer.writerows(detail_records)
            info.update(rows=2, sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
                        all_available_teams=True,
                        team_agency_ids={str(results.index((directory, manifest)) + 1): manifest['plan']['agency_id']})
        inputs = self.root / 'inputs'
        verified = sources.prepare_inputs(results, employees, inputs, self.scope)
        self.assertEqual(verified['team_cities'], {'测试站0': '泉州', '测试站1': '深圳'})
        _, merged = sources.rows_from(inputs / '骑手数据明细.csv')
        self.assertEqual(len(merged), 2)

    def test_all_station_export_missing_ownership_is_not_guessed_from_name(self):
        results, employees = self.fixture()
        results[0][1]['datasets']['rider_detail'].update(all_available_teams=True, team_agency_ids={})
        with self.assertRaisesRegex(SourceError, '团队ID缺少授权城市归属'):
            sources.prepare_inputs(results, employees, self.root / 'inputs', self.scope)

    def test_baize_manifest_row_change_not_accepted(self):
        results, employees = self.fixture()
        employees[1]['datasets']['merchant_employees']['rows'] = 224
        with self.assertRaisesRegex(SourceError, '记录数变化'):
            sources.prepare_inputs(results, employees, self.root / 'inputs', self.scope)

    def test_http_employee_export_without_count_evidence_is_accepted(self):
        results, _ = self.fixture()
        book = Workbook()
        book.active.append(EMPLOYEE_HEADERS)
        book.active.append(EMPLOYEE_ROW)
        book.active.append(list(EMPLOYEE_ROW))
        book.active.append([EMPLOYEE_ROW[0], '1' * 17 + 'X', *EMPLOYEE_ROW[2:]])
        path = self.root / 'http_employees.xlsx'
        book.save(path)
        book.close()
        info = validate_employees(path)
        employees = (self.root, {'status': 'success', 'scope': 'all',
                                 'datasets': {'merchant_employees': info}})
        verified = sources.prepare_inputs(results, employees, self.root / 'inputs', self.scope)
        self.assertEqual(verified['agency_count'], 2)
        self.assertTrue((self.root / 'inputs' / 'merchantFreelancer_白泽全量.xlsx').is_file())

    def test_path_escape_not_accepted(self):
        results, _ = self.fixture()
        info = dict(results[0][1]['datasets']['rider_info'], path='../merchantFreelancer.xlsx')
        with self.assertRaisesRegex(SourceError, '路径越界'):
            sources.verified_file(results[0][0], info)

    def test_missing_supplement_stops_before_network(self):
        config = SimpleNamespace(salaryBindStartDate=self.scope['start'], salaryBindEndDate=self.scope['end'],
                                 sourcePath='./uploads')
        with patch.object(sources, 'workspace_directory', return_value=self.root), patch.object(sources, 'collect_cities') as collect:
            with self.assertRaisesRegex(SourceError, '代领明细'):
                sources.prepare(config, 'test', print, sources.threading.Event(), lambda _: None)
            collect.assert_not_called()

    def test_cross_month_sse_never_starts_download(self):
        config = SimpleNamespace(salaryBindStartDate='2026-07-01', salaryBindEndDate='2026-08-01')
        async def execute():
            return [event async for event in sources.run_automatic_binding(config, 'test')]
        with patch.object(sources, 'prepare') as prepare:
            events = asyncio.run(execute())
            prepare.assert_not_called()
        self.assertEqual(json.loads(events[-1][6:])['status'], 'error')

    def test_unexpected_collection_failure_keeps_safe_diagnostics(self):
        supplement = self.root / '代领明细.csv'
        supplement.write_text('骑手ID,身份证\n', encoding='utf-8-sig')
        config = SimpleNamespace(salaryBindStartDate=self.scope['start'], salaryBindEndDate=self.scope['end'],
                                 sourcePath='supplements')
        with patch.object(sources, 'workspace_directory', return_value=self.root), \
             patch.object(sources, 'owned_upload', return_value=(self.root, self.root)), \
             patch.object(sources, 'collect_cities', side_effect=TimeoutError('sensitive request details')):
            with self.assertRaises(SourceError):
                sources.prepare(config, 'test', lambda _: None, sources.threading.Event(), lambda _: None)
        manifest = json.loads(next(self.root.glob('salary_bind_sources_*/manifest.json')).read_text(encoding='utf-8'))
        self.assertEqual(manifest['failure']['exception_type'], 'TimeoutError')
        self.assertNotIn('sensitive', json.dumps(manifest))

    def test_existing_generator_receives_verified_month_and_city_map(self):
        from salary_bind_processor import run_salary_bind_gen
        results, employees = self.fixture()
        inputs = self.root / 'inputs'
        verified = sources.prepare_inputs(results, employees, inputs, self.scope)
        with (inputs / '代领补充.csv').open('w', encoding='utf-8-sig', newline='') as stream:
            csv.writer(stream).writerow(['骑手ID', '代领月份', '身份证'])
        async def execute():
            return [json.loads(event[6:]) async for event in run_salary_bind_gen(
                str(inputs), str(self.root / 'output'), verified_scope=verified) if event.startswith('data: ')]
        events = asyncio.run(execute())
        finish = [event for event in events if event['type'] == 'finish'][-1]
        self.assertEqual(finish['status'], 'success', finish)
        self.assertEqual(finish['stats']['month'], '2026年07月')
        self.assertEqual(set(finish['stats']['cities']), {'泉州', '深圳'})
        self.assertEqual(finish['stats']['overall']['total_riders'], 2)

        city_files = sorted(path for path in (self.root / 'output').rglob('*骑手支付绑定*.xlsx')
                            if '汇总' not in path.name)
        self.assertEqual(len(city_files), 2)
        summary_files = list((self.root / 'output').rglob('*骑手支付绑定汇总*.xlsx'))
        self.assertEqual(len(summary_files), 1)
        book = load_workbook(summary_files[0])
        try:
            for name in book.sheetnames:
                self.assertEqual(book[name].freeze_panes, 'A2', name)
        finally:
            book.close()
        for path in city_files:
            book = load_workbook(path)
            try:
                self.assertEqual(book.sheetnames[0], '站点汇总')
                for name in book.sheetnames:
                    self.assertEqual(book[name].freeze_panes, 'A2', name)
                rows = list(book['站点汇总'].iter_rows(values_only=True))
                self.assertEqual(rows[0][:4], ('月份', '城市', '站点名称', '骑手明细周期'))
                self.assertEqual(rows[1][0], '2026-07')
                self.assertEqual(rows[1][2], '测试站0' if '泉州' in path.name else '测试站1')
                self.assertEqual(rows[1][3], '2026-07-01 至 2026-07-29')
                self.assertEqual(rows[1][4:6], (1, 2))
                self.assertEqual(rows[-1][2:4], ('1/1 站点', '2026-07-01 至 2026-07-29'))
                self.assertEqual(rows[-1][4:6], (1, 2))
                self.assertEqual(rows[-1][10], '各站点独立计数')
                total_row = book['站点汇总'].max_row
                self.assertEqual(book['站点汇总'].cell(total_row, 2).fill.fgColor.rgb, 'FFF8CBAD')
                self.assertEqual(book['站点汇总'].cell(total_row, 2).border.left.style, 'thin')
            finally:
                book.close()


if __name__ == '__main__':
    unittest.main()
