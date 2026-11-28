import sys
from pathlib import Path
import tempfile
import unittest

from openpyxl import Workbook, load_workbook

sys.path.insert(0, str(Path(__file__).parents[1]))
from binding_generation_worker import (
    _worker_cache,
    filter_sources,
    generate_binding_and_followup_process,
)


class WorkerSourceFilterTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=Path(__file__).parent)
        self.root = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def workbook(self, rows):
        path = self.root / 'rider_info.xlsx'
        book = Workbook(write_only=True)
        sheet = book.create_sheet()
        sheet.append(['骑手ID', '姓名', '部门'])
        for row in rows:
            sheet.append(row)
        book.save(path)
        book.close()
        return path

    def spec(self, path, include):
        return {'paths': {'rider_info': str(path)}, 'plan': {'city': '泉州', 'month': '2026-09'},
                'directory': str(self.root), 'separation_include': include,
                'labels': {'rider_info': '骑手信息导出'}}

    def test_filter_runs_inside_worker_and_reports_proof(self):
        path = self.workbook([['1', '张三', '泉州站'], ['2', '李四', '泉州站（取分离）']])
        logs = []
        paths, seconds = filter_sources(self.spec(path, False),
                                        lambda message, *args, **kwargs: logs.append(message))
        output = paths['rider_info']
        self.assertNotEqual(output, path)
        self.assertGreaterEqual(seconds, 0)
        book = load_workbook(output, read_only=True)
        try:
            rows = list(book.active.iter_rows(values_only=True))
        finally:
            book.close()
        self.assertEqual([row[0] for row in rows[1:]], ['1'])
        self.assertEqual(logs, ['泉州 · 2026-09 骑手信息导出：取分离过滤（排除）2 → 1 行'])

    def test_no_filter_setting_keeps_sources_untouched(self):
        path = self.workbook([['1', '张三', '泉州站（取分离）']])
        paths, seconds = filter_sources(self.spec(path, None), lambda *args, **kwargs: None)
        self.assertEqual(paths['rider_info'], path)
        self.assertEqual(seconds, 0.0)

    def test_worker_cache_reuses_within_same_task_and_resets_across_tasks(self):
        cache_a1, ephemeral_a1 = _worker_cache('task-a')
        cache_a2, ephemeral_a2 = _worker_cache('task-a')
        cache_b, ephemeral_b = _worker_cache('task-b')
        self.assertFalse(ephemeral_a1)
        self.assertFalse(ephemeral_a2)
        self.assertFalse(ephemeral_b)
        self.assertIs(cache_a1, cache_a2)
        self.assertIsNot(cache_a1, cache_b)

    def test_combined_binding_and_followup_keeps_binding_when_followup_errors(self):
        from unittest.mock import patch
        binding_out = self.root / '泉州10月骑手支付绑定.xlsx'
        binding_out.write_bytes(b'placeholder')
        spec = {
            'paths': {},
            'labels': {},
            'separation_include': None,
            'employees': str(self.root / 'employees.xlsx'),
            'proxies': str(self.root / 'proxies.xlsx'),
            'plan': {'city': '泉州', 'agency_id': '31029436',
                     'start': '2026-10-01', 'end': '2026-10-31', 'month': '2026-10'},
            'directory': str(self.root / 'binding'),
            'benlai': None,
            'full_binding_dir': None,
            'write_full_binding': False,
            'binding_platforms': {},
            'task_cache_key': 'unit-task-1',
            'ub_file': str(self.root / 'ub.xlsx'),
            'price_file': str(self.root / 'price.xlsx'),
            'archive_file': str(self.root / 'archive.xlsx'),
            'goods_file': str(self.root / 'goods.xlsx'),
            'followup_dir': str(self.root / 'followup'),
        }
        with patch('binding_download.generate_binding', return_value=(binding_out, {'cities': {'泉州': {'bind_platform': '商翼'}}})):
            with patch('abnormal_followup.generate_abnormal_followup', side_effect=RuntimeError('模拟跟进失败')):
                result = generate_binding_and_followup_process(spec)
        self.assertEqual(result['binding']['file'], str(binding_out))
        self.assertNotIn('error', result['binding'])
        self.assertIn('模拟跟进失败', result['followup']['error'])


if __name__ == '__main__':
    unittest.main()