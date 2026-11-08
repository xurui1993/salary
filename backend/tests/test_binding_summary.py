import hashlib
import json
from pathlib import Path
import sys
import tempfile
import threading
import time
import unittest
from unittest import mock
import zipfile

from openpyxl import Workbook, load_workbook
sys.path.insert(0, str(Path(__file__).parents[1]))
from binding_summary import build_binding_summaries
from download_jobs import DownloadManager, _initial_items, FINAL_STATUSES
from download_service import validate_request
from fengshen_bill import BillCollectionError, atomic_json


def city_output(root, item, cancelled=False):
    city, month = item['city'], item['start'][:7]
    raw = root / '原始资料' / city / 'payment_binding' / month
    raw.mkdir(parents=True)
    counts = dict(total_riders=1, total_orders=3, fengshen_bind_count=1,
                  shangyi_bind_count=1, fully_bound_count=1, black_count=0)
    atomic_json(raw / 'binding_stats.json', {'cities': {city: counts},
                'source_range': {'start': item['start'], 'end': item['end']}})
    book = Workbook(); book.remove(book.active)
    main = book.create_sheet(f'{int(month[5:])}月骑手绑定情况')
    main.append(['城市', '骑手ID', '骑手姓名', '单量汇总']); main.append([city, '001', '=测试原始文本', 3])
    main.cell(2, 3).data_type = 's'
    book.create_sheet(f'{int(month[5:])}月未绑名单').append(['城市', '骑手ID'])
    proxy = book.create_sheet(f'{int(month[5:])}月黑户代领明细')
    proxy.append(['城市名称', '风神ID', '城市'] if city == '泉州' else ['风神ID', '城市名称'])
    fengshen = book.create_sheet('风神绑定表')
    fengshen.append(['团队ID', '团队名称', '骑手ID']); fengshen.append([9, city + '-站点', '001'])
    shangyi = book.create_sheet('商翼绑定表')
    shangyi.append(['骑手姓名', '身份证']); shangyi.append(['共享骑手', '110000000000000000'])
    detail = book.create_sheet('骑手详情表')
    detail.append(['日期', '骑手ID', '有效完成单']); detail.append([item['start'], '001', 3])
    info = book.create_sheet('骑手信息表')
    info.append(['骑手ID', '姓名']); info.append(['001', '测试骑手'])
    path = root / (city + month + '.xlsx'); book.save(path); book.close()
    return {**{key: item[key] for key in ('city', 'dataset', 'start', 'end')},
            'name': path.name, 'relative_path': path.name, 'bytes': path.stat().st_size,
            'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}


class BindingSummaryTests(unittest.TestCase):
    def config(self, end='2026-09-02'):
        return validate_request({'cities': ['泉州', '上海'], 'datasets': ['payment_binding'],
                                 'start': '2026-09-01', 'end': end})

    def test_cross_month_preserves_cross_city_riders_and_sum_and_text(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as directory:
            root = Path(directory); config = self.config('2026-10-02')
            items = [{**item, 'status': 'success'} for item in _initial_items(config)]
            files = [city_output(root, item) for item in items]
            events = []
            summaries = build_binding_summaries(root, config, files, items, threading.Event(),
                                                progress=lambda current, total, city, month:
                                                events.append((month, current, total, city)))
            self.assertEqual(len(summaries), 2)
            for month in ('2026-09', '2026-10'):
                positions = [(current, total) for value_month, current, total, _ in events if value_month == month]
                self.assertEqual(positions, [(0, 2), (1, 2), (2, 2)])
                cities = {city for value_month, current, _, city in events if value_month == month and city}
                self.assertEqual(cities, {'泉州', '上海'})
            for entry in summaries:
                book = load_workbook(root / entry['relative_path'])
                try:
                    month = int(entry['start'][5:7])
                    rows = list(book[f'{month}月骑手绑定情况'].iter_rows())
                    self.assertEqual([row[1].value for row in rows[1:]], ['001', '001'])
                    self.assertEqual(rows[1][2].data_type, 's')
                    self.assertEqual(list(next(book[f'{month}月黑户代领明细'].values)), ['城市名称', '风神ID', '城市'])
                    total = list(book['城市汇总'].values)[-1]
                    self.assertEqual(total[4:10], (2, 6, 2, 2, 2, 0))
                    fengshen = list(book['风神绑定表'].iter_rows(values_only=True))
                    self.assertEqual(fengshen, [('团队ID', '团队名称', '骑手ID', '城市'),
                                                (9, '泉州-站点', '001', '泉州'), (9, '上海-站点', '001', '上海')])
                    shangyi = list(book['商翼绑定表'].iter_rows(values_only=True))
                    self.assertEqual(shangyi, [('骑手姓名', '身份证'), ('共享骑手', '110000000000000000')])
                    for label in ('骑手详情表', '骑手信息表'):
                        aggregated = list(book[label].iter_rows(values_only=True))
                        self.assertEqual(len(aggregated), 3)
                        self.assertEqual(aggregated[0][-1], '城市')
                        self.assertEqual([row[-1] for row in aggregated[1:]], ['泉州', '上海'])
                    # 自适应列宽：'城市' 列内容最长 4 个显示宽度 -> 4 + 2；
                    # xlsxwriter 会按字体度量把字符宽换算成 Excel 列宽（约 6.71）。
                    self.assertAlmostEqual(book[f'{month}月骑手绑定情况'].column_dimensions['A'].width, 6.71, places=2)
                    self.assertAlmostEqual(book['城市汇总'].column_dimensions['B'].width, 6.71, places=2)
                    self.assertEqual(book['城市汇总'].freeze_panes, 'D2')
                    self.assertEqual(book['汇总说明'].freeze_panes, 'A2')
                    for label in (f'{month}月骑手绑定情况', f'{month}月未绑名单',
                                  f'{month}月黑户代领明细', '风神绑定表', '商翼绑定表',
                                  '骑手详情表', '骑手信息表'):
                        self.assertEqual(book[label].freeze_panes, 'A2', label)
                finally: book.close()

    def test_layout_sidecar_is_used_instead_of_rescanning(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as directory:
            root = Path(directory); config = self.config()
            items = [{**item, 'status': 'success'} for item in _initial_items(config)]
            files = [city_output(root, item) for item in items]
            month = '2026-09'
            labels = [f'{int(month[5:])}月骑手绑定情况', f'{int(month[5:])}月未绑名单',
                      f'{int(month[5:])}月黑户代领明细', '风神绑定表', '商翼绑定表', '骑手详情表', '骑手信息表']
            for item, file in zip(items, files):
                source = root / file['relative_path']
                book = load_workbook(source, read_only=True, data_only=True)
                try:
                    sheets = {}
                    for label in labels:
                        header = list(next(book[label].iter_rows(values_only=True)))
                        sheets[label] = {'header': header, 'widths': [40] * len(header)}
                finally:
                    book.close()
                atomic_json(root / '原始资料' / item['city'] / 'payment_binding' / month / 'binding_layout.json',
                            {'sha256': hashlib.sha256(source.read_bytes()).hexdigest(), 'sheets': sheets})
            with mock.patch('binding_summary.scan_widths', side_effect=AssertionError('不应回扫源文件')):
                summaries = build_binding_summaries(root, config, files, items, threading.Event())
            book = load_workbook(root / summaries[0]['relative_path'])
            try:
                self.assertGreater(book['9月骑手绑定情况'].column_dimensions['A'].width, 40)
                self.assertGreater(book['城市汇总'].column_dimensions['B'].width, 6)
            finally:
                book.close()
            proof = json.loads((root / ('binding_summary_' + month + '.json')).read_text(encoding='utf-8'))
            self.assertEqual({value['layout'] for value in proof['sources']}, {'sidecar'})

    def test_failed_city_is_listed_but_excluded_and_changed_source_is_blocked(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as directory:
            root = Path(directory); config = self.config()
            items = _initial_items(config); items[0]['status'] = 'success'
            items[1].update(status='error', error='资料下载失败')
            files = [city_output(root, items[0])]
            summaries = build_binding_summaries(root, config, files, items, threading.Event())
            book = load_workbook(root / summaries[0]['relative_path'], read_only=True)
            try:
                self.assertEqual(len(list(book['9月骑手绑定情况'].values)), 2)
                rows = list(book['城市汇总'].values)
                self.assertEqual(rows[2][1:3], ('上海', '未纳入'))
                self.assertIsNone(rows[2][4])
                self.assertEqual(rows[-1][4], 1)
            finally: book.close()
            (root / files[0]['relative_path']).write_bytes(b'changed')
            with self.assertRaises(BillCollectionError):
                build_binding_summaries(root, config, files, items, threading.Event())

    def test_manager_registers_summary_bundle_and_restores_committed_summary(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as directory:
            root = Path(directory); config = self.config()
            def execute(config, run_dir, log, cancelled, update):
                items = [{**item, 'status': 'success'} for item in _initial_items(config)]
                files = [city_output(run_dir, item) for item in items]
                atomic_json(run_dir / 'manifest.json', {'config': config, 'items': items, 'files': files, 'payroll_executed': False})
                for item, file in zip(items, files): update({**item, 'files': [file]})
                return files
            manager = DownloadManager(root / 'db/tasks.sqlite3', root / 'outputs', execute)
            try:
                run = manager.create('test', config)
                deadline = time.monotonic() + 10
                while time.monotonic() < deadline:
                    run = manager.get_run('test', run['id'])
                    if run['status'] in FINAL_STATUSES: break
                    threading.Event().wait(.02)
                self.assertEqual(run['status'], 'success', run.get('error'))
                self.assertEqual(len(run['items']), 2)
                self.assertEqual(len(run['files']), 3)
                summary = next(file for file in run['files'] if file.get('artifact_role') == 'summary')
                path, _ = manager.get_file('test', run['id'], summary['id'])
                self.assertTrue(path.is_file())
                # A city bundle contains only that city's file; all-city bundle includes the summary.
                bundle = manager.get_bundle('test', run['id'])
                with zipfile.ZipFile(bundle[0]) as archive: self.assertIn(summary['name'], archive.namelist())
                with manager._connection() as connection:
                    _, state = manager._find(connection, 'test', run['id'])
                state['files'] = []
                manager._restore_checkpoint(state, config)
                self.assertEqual(len(state['files']), 3)
                invalid = {**summary, 'city': '其他城市', 'relative_path': path.name}
                with self.assertRaises(ValueError): manager._file_entry(state, invalid, config)
            finally: manager.shutdown()


if __name__ == '__main__': unittest.main()
