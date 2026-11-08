import csv
import json
from pathlib import Path
import sys
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import pandas as pd
from openpyxl import load_workbook
sys.path.insert(0, str(Path(__file__).parents[1]))
from binding_download import month_periods, approved_proxies, eligible_details, generate_binding, merge_binding_history
from binding_download import binding_history
from binding_sources_http import export_once
from fengshen_bill import BillCollectionError
from download_service import validate_request, _requested_items
from download_jobs import _initial_items
import test_salary_bind_sources as source_fixtures
import test_download_service as download_fixtures


def proxy(**changes):
    return {'城市名称': '泉州市', '代领月份': '2026-09', '流程状态': '审核通过', '启停用': '启用',
            '骑手身份证': '110101199001010010', '代领人身份证': '110101199001010029', **changes}


class BindingRuleTests(unittest.TestCase):
    def test_complete_material_recovery_does_not_open_platform_or_export(self):
        import hashlib
        import download_service as service
        from binding_recovery import copy_materials
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as directory:
            root = Path(directory)
            contents = {
                'rider_detail': '日期,骑手ID,团队名称,有效完成单\n2026-09-01,1,测试站,5\n',
                'receive_account': '团队名称,骑手ID\n测试站,1\n',
                'rider_info': '骑手ID,部门\n1,测试站\n',
            }
            materials = {}
            for key in ('rider_detail', 'receive_account', 'rider_info', 'employees', 'proxies'):
                source = root / (key + '.csv')
                source.write_text(contents.get(key, key), encoding='utf-8')
                materials[key] = {'path': str(source.resolve()), 'bytes': source.stat().st_size,
                                  'sha256': hashlib.sha256(source.read_bytes()).hexdigest()}
            config = service.validate_request({'cities': ['泉州'], 'datasets': ['payment_binding'],
                                              'start': '2026-09-01', 'end': '2026-09-02'})
            config['resume_binding_materials'] = {'泉州|2026-09': materials}
            factory = Mock(side_effect=AssertionError('must not connect to platform'))
            def generate(paths, employees, proxies, plan, raw, *args):
                self.assertEqual(set(paths), {'rider_detail', 'receive_account', 'rider_info'})
                file = Path(raw) / 'result.xlsx'; file.write_bytes(b'fixture'); return file, {}
            with patch('binding_sources_http.BindingSources') as sources, \
                 patch('binding_download.generate_binding', side_effect=generate):
                files = service.execute_downloads(config, root / 'run', lambda *_: None, threading.Event(), lambda *_: None, factory)
            self.assertEqual(len(files), 1)
            factory.assert_not_called()
            sources.return_value.employees.assert_not_called()
            sources.return_value.proxies.assert_not_called()
            Path(materials['rider_info']['path']).write_bytes(b'tampered')
            with self.assertRaises(BillCollectionError):
                copy_materials(materials, root / 'tampered')

    def test_recovery_requires_exact_city_period_month_and_completed_sources(self):
        import hashlib
        from binding_recovery import completed_materials
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as directory:
            root = Path(directory)
            def write_json(path, data):
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(json.dumps(data), encoding='utf-8')
            def file_receipt(raw, name):
                raw.mkdir(parents=True, exist_ok=True)
                (raw / name).write_bytes(b'fixture')
                return {'path': name, 'bytes': 7, 'sha256': hashlib.sha256(b'fixture').hexdigest()}
            for kind in ('rider_detail', 'receive_account', 'rider_info'):
                raw = root / '原始资料/泉州/payment_binding/2026-09' / kind
                info = {**file_receipt(raw, 'file.csv'), 'dataset': kind, 'status': 'validated', 'rows': 1,
                        'scope': 'target_city', 'city': '泉州', 'agency_id': '31029436',
                        'start': '2026-09-01', 'end': '2026-09-30' if kind == 'receive_account' else '2026-09-02',
                        'month': '2026-09', 'snapshot_only': kind == 'rider_info'}
                write_json(raw / 'source_receipt.json', info)
            for source, subdir, name in [('baize', 'baize', 'employee.csv'),
                                         ('lanorange', 'lanorange/2026-09', '薪资代领.xlsx')]:
                raw = root / '原始资料/支付绑定公共来源' / subdir
                receipt = file_receipt(raw, name)
                write_json(raw / 'manifest.json', {**receipt, 'status': 'success', 'month': '2026-09'})
                write_json(raw / 'http_submission.json', {**receipt, 'source': source,
                           'submission_state': 'submitted', 'scope': {'replaceMonth': '2026-09'}})
            args = (root, '泉州', '31029436', '2026-09-01', '2026-09-02')
            self.assertEqual(len(completed_materials(*args)), 5)
            with self.assertRaises(BillCollectionError):
                completed_materials(root, '泉州', 'wrong-city', args[3], args[4])
            with self.assertRaises(BillCollectionError):
                completed_materials(root, '泉州', '31029436', args[3], '2026-09-03')
            raw = root / '原始资料/支付绑定公共来源/lanorange/2026-09'
            receipt = json.loads((raw / 'http_submission.json').read_text(encoding='utf-8'))
            for changes in ({'submission_state': 'unknown'}, {'scope': {'replaceMonth': '2026-10'}}):
                write_json(raw / 'http_submission.json', {**receipt, **changes})
                with self.assertRaises(BillCollectionError): completed_materials(*args)

    def test_cross_month_intersections_match_manager_and_executor(self):
        config = validate_request({'cities': ['泉州'], 'datasets': ['payment_binding'],
                                   'start': '2026-09-20', 'end': '2026-10-10'})
        self.assertEqual(month_periods(config['start'], config['end']),
                         [('2026-09', '2026-09-20', '2026-09-30'), ('2026-10', '2026-10-01', '2026-10-10')])
        self.assertEqual([(i['city'], i['start'], i['end']) for i in _requested_items(config)],
                         [(i['city'], i['start'], i['end']) for i in _initial_items(config)])

    def test_proxy_filters_city_month_approval_enabled_and_duplicate(self):
        rows = [proxy(), proxy(), proxy(流程状态='审批中'), proxy(流程状态='待审核'),
                proxy(流程状态='审核拒绝'), proxy(启停用='停用'), proxy(代领月份='2026-10'), proxy(城市名称='上海市')]
        self.assertEqual(len(approved_proxies(pd.DataFrame(rows), '泉州', '2026-09')), 1)
        self.assertEqual(len(approved_proxies(pd.DataFrame(rows), '广州', '2026-09')), 0)

    def test_conflicting_payees_stop_only_the_target_city(self):
        rows = pd.DataFrame([proxy(), proxy(代领人身份证='110101199001010037')])
        with self.assertRaisesRegex(BillCollectionError, '不同代领人'):
            approved_proxies(rows, '泉州', '2026-09')
        self.assertTrue(approved_proxies(rows, '广州', '2026-09').empty)
        with self.assertRaises(BillCollectionError):
            approved_proxies(pd.DataFrame([proxy(代领人身份证='')]), '泉州', '2026-09')

    def test_pending_is_eligible_and_approved_wins_independent_of_row_order(self):
        pending = proxy(流程状态='审批中', 代领人身份证='110101199001010037')
        result = approved_proxies(pd.DataFrame([pending, pending]), '泉州', '2026-09')
        self.assertEqual(result['流程状态'].tolist(), ['审批中'])
        for rows in ([pending, proxy()], [proxy(), pending]):
            result = approved_proxies(pd.DataFrame(rows), '泉州', '2026-09')
            self.assertEqual(result['流程状态'].tolist(), ['审核通过'])
            self.assertEqual(result['代领人身份证'].tolist(), [proxy()['代领人身份证']])
        for rows in ([pending, proxy(流程状态='审批中')], [pending, proxy(), proxy(代领人身份证='110101199001010045')]):
            with self.assertRaisesRegex(BillCollectionError, '不同代领人'):
                approved_proxies(pd.DataFrame(rows), '泉州', '2026-09')
        rows = [pending, proxy(流程状态='审核通过', 启停用='停用')]
        self.assertEqual(approved_proxies(pd.DataFrame(rows), '泉州', '2026-09')['流程状态'].tolist(), ['审批中'])

    def test_eligibility_is_exact_column_sum_and_preserves_separate_city(self):
        data = pd.DataFrame([{'日期': '2026-09-01', '骑手ID': '10', '团队名称': '站点', '有效完成单': '2'},
                             {'日期': '2026-09-02', '骑手ID': '10', '团队名称': '站点', '有效完成单': '3'},
                             {'日期': '2026-09-01', '骑手ID': '11', '团队名称': '站点', '有效完成单': '0'}])
        for city in ('泉州', '上海'):
            result = eligible_details(data, SimpleNamespace(city=city, start='2026-09-01', end='2026-09-02'))
            self.assertEqual(result['骑手ID'].unique().tolist(), ['10'])
            self.assertEqual(result['有效完成单'].sum(), 5)
            self.assertEqual(result['城市'].unique().tolist(), [city])
        for value in ('', 'bad', '-1', '0.5'):
            changed = data.copy(); changed.loc[0, '有效完成单'] = value
            with self.assertRaises(BillCollectionError):
                eligible_details(changed, SimpleNamespace(city='泉州', start='2026-09-01', end='2026-09-02'))

    def test_legacy_merge_retains_other_cities(self):
        old = {'month': '2026年09月', 'stats': {'cities': {'上海': {'total_riders': 2, 'total_orders': 5,
            'fengshen_bind_count': 2, 'shangyi_bind_count': 1, 'fully_bound_count': 1, 'black_count': 0}}, 'overall': {}}}
        fresh = {'month': old['month'], 'stats': {'cities': {'泉州': {'total_riders': 1, 'total_orders': 3,
            'fengshen_bind_count': 1, 'shangyi_bind_count': 1, 'fully_bound_count': 1, 'black_count': 0}}}}
        result = merge_binding_history([old], [fresh])[0]['stats']
        self.assertEqual(set(result['cities']), {'上海', '泉州'})
        self.assertEqual(result['overall']['total_riders'], 3)
        self.assertEqual(result['overall']['shangyi_bind_count'], 2)

    def test_export_timeout_leaves_receipt_and_never_replays(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as directory:
            session = Mock(); session.post.side_effect = TimeoutError()
            target = Path(directory) / 'file.xlsx'
            with self.assertRaises(BillCollectionError):
                export_once(session, 'lanorange', 'info/riderSalaryReplace/export', {'replaceMonth': '2026-09'}, target, threading.Event())
            receipt = json.loads((target.parent / 'http_submission.json').read_text(encoding='utf-8'))
            self.assertEqual(receipt['submission_state'], 'unknown')
            with self.assertRaises(FileExistsError):
                export_once(session, 'lanorange', 'info/riderSalaryReplace/export', {}, target, threading.Event())
            self.assertEqual(session.post.call_count, 1)

    def test_real_existing_generator_retains_workbook_structure(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as directory:
            root = Path(directory)
            fixture = source_fixtures.BindingSourceTests(); fixture.root = root
            fixture.scope = {'month': '2026-07', 'start': '2026-07-01', 'end': '2026-07-29'}
            results, employees = fixture.fixture()
            raw = root / 'new'; raw.mkdir()
            proxies = root / 'proxy.csv'
            with proxies.open('w', encoding='utf-8-sig', newline='') as stream:
                csv.DictWriter(stream, fieldnames=list(proxy())).writeheader()
            paths = {kind: results[0][0] / info['path'] for kind, info in results[0][1]['datasets'].items()}
            plan = SimpleNamespace(city='泉州', agency_id='31029436', **fixture.scope)
            path, stats = generate_binding(paths, employees[0] / 'merchantFreelancer.xlsx', proxies,
                                           plan, raw, lambda *_: None, threading.Event())
            self.assertEqual(stats['overall']['total_riders'], 1)
            self.assertEqual(set(stats['cities']), {'泉州'})
            book = load_workbook(path)
            try:
                self.assertEqual(book.sheetnames, ['站点汇总', '7月骑手绑定情况', '7月未绑名单', '7月黑户代领明细',
                                                   '风神绑定表', '商翼绑定表', '骑手详情表', '骑手信息表'])
                for name in book.sheetnames:
                    self.assertEqual(book[name].freeze_panes, 'A2', name)
                station = list(book['站点汇总'].iter_rows(values_only=True))
                self.assertEqual(station[0][:4], ('月份', '城市', '站点名称', '骑手明细周期'))
                self.assertEqual(station[1][3], '2026-07-01 至 2026-07-29')
                self.assertEqual(station[-1][2], '1/1 站点')
                self.assertEqual(station[-1][3], '2026-07-01 至 2026-07-29')
                total_row = book['站点汇总'].max_row
                self.assertEqual(book['站点汇总'].cell(total_row, 1).fill.fgColor.rgb, 'FFF8CBAD')
                headers = next(book.worksheets[1].iter_rows(values_only=True))
                self.assertIn('收款人身份证号码', headers)
            finally: book.close()
            # 单城市任务主工作簿即城市成品，不再重复写一份四表城市工作簿。
            self.assertEqual(sorted((raw / 'generated').rglob('*.xlsx')), [path])
            layout = json.loads((raw / 'binding_layout.json').read_text(encoding='utf-8'))
            self.assertEqual(list(layout['sheets']), book.sheetnames)
            self.assertEqual(layout['sheets']['站点汇总']['header'][:2], ['月份', '城市'])

    def test_service_failure_is_city_month_isolated_and_sources_have_exact_periods(self):
        import download_service as service
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as directory:
            runner = download_fixtures.FakeRunner()
            sources = Mock(); sources.employees.return_value = Path('employee.xlsx'); sources.proxies.return_value = Path('proxy.xlsx')
            config = service.validate_request({'cities': ['泉州', '上海'], 'datasets': ['payment_binding'],
                'start': '2026-09-20', 'end': '2026-10-10'})
            config['owner'] = 'test'
            updates = []
            def generate(paths, employees, proxies, plan, raw, log, cancelled):
                if plan.city == '泉州' and plan.month == '2026-09':
                    raise BillCollectionError('代领人冲突')
                path = Path(raw) / 'generated.xlsx'; path.write_bytes(b'fixture')
                return path, {}
            import contextlib
            @contextlib.contextmanager
            def factory(*_): yield runner
            with patch('binding_sources_http.BindingSources', return_value=sources), patch('binding_download.generate_binding', side_effect=generate):
                files = service.execute_downloads(config, Path(directory) / 'run', lambda *_: None,
                                                  threading.Event(), updates.append, factory)
            self.assertEqual(len(files), 3)
            self.assertTrue(any(i.get('status') == 'error' and i['city'] == '泉州' and i['start'] == '2026-09-20' for i in updates))
            calls = [call for call in runner.calls if call[1] == 'receive_account']
            self.assertIn(('泉州', 'receive_account', '2026-09-01', '2026-09-30'), calls)
            self.assertIn(('上海', 'receive_account', '2026-10-01', '2026-10-31'), calls)

    def test_followup_in_same_task_runs_after_binding_publish(self):
        import download_service as service
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as directory:
            root = Path(directory) / 'run'
            runner = download_fixtures.FakeRunner()
            sources = Mock(); sources.employees.return_value = Path('employee.xlsx'); sources.proxies.return_value = Path('proxy.xlsx')
            config = service.validate_request({'cities': ['泉州'], 'start': '2026-09-01', 'end': '2026-09-02',
                                               'datasets': ['payment_binding', 'rider_monthly', 'goods_rent',
                                                            'abnormal_followup', 'lanorange_part_price',
                                                            'lanorange_rider_archive']})
            config['owner'] = 'test'
            config['lanorange_full_delivery'] = False
            updates, seen = [], []
            def generate(paths, employees, proxies, plan, raw, log, cancelled):
                path = Path(raw) / 'generated.xlsx'; path.write_bytes(b'fixture')
                return path, {}
            def blue_collect(kind, directory, log, cancelled, resume=None, **kwargs):
                directory = Path(directory); directory.mkdir(parents=True, exist_ok=True)
                path = directory / 'blue.xlsx'; path.write_bytes(b'fixture')
                return path
            def followup(binding_file, *args, **kwargs):
                # 跟进表生成时，本任务的支付绑定成品必须已经发布到归档目录
                seen.append(Path(binding_file).is_file())
                out = Path(args[6]); out.mkdir(parents=True, exist_ok=True)
                generated = out / 'followup.xlsx'; generated.write_bytes(b'fixture')
                return generated
            import contextlib
            @contextlib.contextmanager
            def factory(*_): yield runner
            with patch('binding_sources_http.BindingSources', return_value=sources), \
                 patch('binding_download.generate_binding', side_effect=generate), \
                 patch('lanorange_download.collect', side_effect=blue_collect), \
                 patch('abnormal_followup.generate_abnormal_followup', side_effect=followup):
                files = service.execute_downloads(config, root, lambda *_: None,
                                                  threading.Event(), updates.append, factory)
            self.assertEqual(seen, [True])
            self.assertFalse([value for value in updates if value.get('status') == 'error'])
            self.assertEqual({value['dataset'] for value in files},
                             {'payment_binding', 'rider_monthly', 'goods_rent', 'abnormal_followup',
                              'lanorange_part_price', 'lanorange_rider_archive'})

    def test_history_reads_only_committed_success_and_keeps_older_success_after_failure(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as directory:
            root = Path(directory); output = root / 'file.xlsx'; output.write_bytes(b'fixture')
            raw = root / '原始资料/泉州/payment_binding/2026-09'; raw.mkdir(parents=True)
            city = {'total_riders': 1, 'total_orders': 2, 'fengshen_bind_count': 1, 'shangyi_bind_count': 0,
                    'fully_bound_count': 0, 'black_count': 0, 'stations': []}
            (raw / 'binding_stats.json').write_text(json.dumps({'month': '2026年09月', 'cities': {'泉州': city},
                'source_range': {'start': '2026-09-01', 'end': '2026-09-02'}}), encoding='utf-8')
            file = {'id': 'file', 'dataset': 'payment_binding', 'city': '泉州', 'start': '2026-09-01', 'name': output.name}
            success = {'id': 'old', 'files': [file], 'items': [{**file, 'status': 'success'}]}
            failed = {'id': 'new', 'files': [file], 'items': [{**file, 'status': 'error'}]}
            manager = Mock(); manager.binding_runs.return_value = [failed, success]
            manager.get_file.return_value = (output, output.name)
            with patch('download_jobs.get_manager', return_value=manager):
                history = binding_history()
            self.assertEqual(history[0]['stats']['cities']['泉州']['download_run_id'], 'old')
            self.assertEqual(history[0]['stats']['overall']['total_orders'], 2)
            manager.get_file.assert_called_once()

    def test_external_session_is_encrypted_and_source_bound(self):
        import binding_source_auth as auth
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as directory, patch.object(auth, 'ROOT', Path(directory)):
            token = 'synthetic-session-test-never-printed'
            auth.save_token('lanorange', token)
            self.assertNotIn(token.encode(), auth.session_path('lanorange').read_bytes())
            self.assertEqual(auth.load_token('lanorange'), token)
            auth.session_path('baize').write_bytes(auth.session_path('lanorange').read_bytes())
            with self.assertRaises(BillCollectionError): auth.load_token('baize')


if __name__ == '__main__': unittest.main()
