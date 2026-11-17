import datetime as dt
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from openpyxl import Workbook

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import payroll_business
import payroll_inputs
import rider_identity


class XiaoxiangAutomaticTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / 'upload'
        self.source.mkdir()
        self.account_patch = patch('baize_accounts.snapshot',
                                   return_value={'account_type': 'xiaoxiang',
                                                 'region_text': '小象超市'})
        self.account_patch.start()
        self.addCleanup(self.account_patch.stop)

    def template(self):
        path = self.source / '小象-template.xlsx'
        book = Workbook()
        sheet = book.active
        sheet.title = '申请名单'
        sheet.append(['业务城市', '团队名称', '骑手ID', '骑手姓名', '开始日期', '结束日期', '身份证号', '电话号'])
        sheet.append(['小象超市', '测试站', '1001', '合成人员', dt.date(2026, 7, 1), dt.date(2026, 9, 10), '', ''])
        book.save(path)
        book.close()
        return path

    def test_template_only_creates_automatic_pending_state(self):
        template = self.template()
        plan = payroll_business.company_plan(template, self.source)
        folder, state = payroll_inputs.create_xiaoxiang(
            self.source, plan, template, 'u_' + 'a' * 20, self.root, 'owner')
        self.assertEqual(state['workflow'], 'two_step_v1')
        self.assertEqual(state['status'], 'pending_download')
        self.assertEqual(state['download_owner'], 'owner')
        self.assertEqual(state['jobs'], [])
        self.assertEqual(state['items']['payment_binding']['status'], 'pending')
        for key in ('delivery_fee', 'rider_orders', 'rider_archive', 'lanorange_part_price'):
            self.assertEqual(state['items'][key]['status'], 'pending')
        self.assertTrue((folder / 'input' / template.name).is_file())

    def test_shanggou_account_blocks_before_any_download(self):
        template = self.template()
        plan = payroll_business.company_plan(template, self.source)
        with patch('baize_accounts.snapshot',
                   return_value={'account_type': 'shanggou', 'region_text': '台州、上海'}):
            folder, state = payroll_inputs.create_xiaoxiang(
                self.source, plan, template, 'u_' + 'd' * 20, self.root, 'owner')
        self.assertEqual(state['status'], 'waiting_materials')
        self.assertEqual(state['jobs'], [])
        self.assertIn('小象超市', state['pause_reason'])
        calls = []
        class Manager:
            def create(self, owner, config, request_id):
                calls.append(config)
                return {'id': 'job'}
            def get_run(self, owner, job_id):
                return {'items': [], 'files': []}
        with patch('baize_accounts.snapshot',
                   return_value={'account_type': 'shanggou', 'region_text': '台州、上海'}):
            payroll_inputs.start_xiaoxiang_download(folder, state, Manager())
        self.assertEqual(calls, [])
        self.assertEqual(state['jobs'], [])

    def test_start_creates_daily_chunks_and_all_city_price_job(self):
        template = self.template()
        plan = payroll_business.company_plan(template, self.source)
        folder, state = payroll_inputs.create_xiaoxiang(
            self.source, plan, template, 'u_' + 'b' * 20, self.root, 'owner')
        calls = []
        class Manager:
            def create(self, owner, config, request_id):
                calls.append({'owner': owner, 'config': config, 'request_id': request_id})
                return {'id': 'job' + str(len(calls))}
        payroll_inputs.start_xiaoxiang_download(folder, state, Manager())
        daily = [call for call in calls if call['config']['datasets'] == ['rider_daily']]
        self.assertEqual(len(daily), 3)
        self.assertTrue(all(call['config']['cities'] == ['全部城市'] for call in daily))
        self.assertEqual({call['config']['datasets'][0] for call in calls},
                         {'rider_daily', 'rider_order_detail', 'rider_archive', 'lanorange_part_price', 'baize_employees'})
        price = next(call for call in calls if call['config']['datasets'] == ['lanorange_part_price'])
        self.assertEqual(price['config']['cities'], ['全部城市'])
        self.assertEqual(price['config']['lanorange_months'], ['2026-07', '2026-08', '2026-09'])
        self.assertEqual(len(state['jobs']), 9)

    def test_collect_maps_all_sources_and_copies_multiple_daily_files(self):
        template = self.template()
        plan = payroll_business.company_plan(template, self.source)
        folder, state = payroll_inputs.create_xiaoxiang(
            self.source, plan, template, 'u_' + 'c' * 20, self.root, 'owner')
        state['jobs'] = ['daily1', 'daily2', 'orders', 'archive', 'price', 'baize']
        paths = {
            'daily1': folder / '日维度骑手分析2026-07-01.xlsx',
            'daily2': folder / '日维度骑手分析2026-08-01.xlsx',
            'orders': folder / '骑手订单明细_2026-07-01_2026-09-10.xlsx',
            'archive': folder / '灯塔骑手档案1117.xlsx',
            'price': folder / '价格档案_2026-07至2026-09.xlsx',
            'baize': folder / 'merchantFreelancer_商翼全量.xlsx',
        }
        for name, path in paths.items():
            if name == 'baize':
                book = Workbook()
                sheet = book.active
                sheet.append(['姓名', '身份证号', '银行预留手机号'])
                sheet.append(['测试骑手', 'SYNTHETIC-CARD-001', '13800000000'])
                book.save(path)
                book.close()
            else:
                path.write_text(path.name, encoding='utf-8')
        runs = {
            'daily1': {'items': [{'dataset': 'rider_daily', 'status': 'success'}],
                       'files': [{'id': 'f1', 'dataset': 'rider_daily', 'name': paths['daily1'].name}]},
            'daily2': {'items': [{'dataset': 'rider_daily', 'status': 'success'}],
                       'files': [{'id': 'f2', 'dataset': 'rider_daily', 'name': paths['daily2'].name}]},
            'orders': {'items': [{'dataset': 'rider_order_detail', 'status': 'success'}],
                       'files': [{'id': 'f3', 'dataset': 'rider_order_detail', 'name': paths['orders'].name}]},
            'archive': {'items': [{'dataset': 'rider_archive', 'status': 'success'}],
                        'files': [{'id': 'f4', 'dataset': 'rider_archive', 'name': paths['archive'].name}]},
            'price': {'items': [{'dataset': 'lanorange_part_price', 'status': 'success'}],
                      'files': [{'id': 'f5', 'dataset': 'lanorange_part_price', 'name': paths['price'].name}]},
            'baize': {'items': [{'dataset': 'baize_employees', 'status': 'success'}],
                      'files': [{'id': 'f6', 'dataset': 'baize_employees', 'name': paths['baize'].name}]},
        }
        class Manager:
            def get_run(self, owner, job_id):
                return runs[job_id]
            def get_file(self, owner, job_id, file_id):
                job = next(key for key, value in runs.items()
                           if value['files'][0]['id'] == file_id)
                return paths[job], paths[job]
        payroll_inputs.collect_xiaoxiang(folder, state, Manager())
        self.assertEqual(state['status'], 'ready')
        self.assertEqual(len(state['items']['delivery_fee']['files']), 2)
        self.assertEqual(state['items']['rider_orders']['files'][0]['file'], paths['orders'].name)
        self.assertEqual(state['items']['rider_archive']['files'][0]['file'], paths['archive'].name)
        self.assertEqual(state['items']['lanorange_part_price']['files'][0]['file'], paths['price'].name)
        self.assertEqual(state['items']['payment_binding']['status'], 'ready')
        self.assertTrue((folder / 'input' / '骑手支付绑定.xlsx').is_file())
        for entry in state['items']['delivery_fee']['files']:
            self.assertTrue((folder / 'input' / entry['file']).is_file())

    def test_rider_archive_identity_fallback(self):
        path = self.source / '灯塔骑手档案1117.xlsx'
        book = Workbook()
        sheet = book.active
        sheet.title = '骑手档案'
        sheet.append(['所属站点', '骑手ID', '姓名', '身份证号', '手机号'])
        sheet.append(['测试站', 1001, '合成人员', 'SYNTHETIC-CARD', '13800000000'])
        book.save(path)
        book.close()
        archive = rider_identity.load_archive(self.source)
        self.assertEqual(archive['1001']['station'], '测试站')
        self.assertEqual(archive['1001']['idcard'], 'SYNTHETIC-CARD')
        self.assertEqual(archive['1001']['phone'], '13800000000')


if __name__ == '__main__':
    unittest.main()