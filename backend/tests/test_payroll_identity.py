"""Run the payroll engine against name variants without changing raw orders."""
from pathlib import Path
import unittest

from openpyxl import Workbook, load_workbook

import test_optional_payroll_inputs as fixtures
import processor


class PayrollIdentityTests(unittest.TestCase):
    setUp = fixtures.OptionalPayrollInputsTests.setUp
    fixture = fixtures.OptionalPayrollInputsTests.fixture
    add_price = fixtures.OptionalPayrollInputsTests.add_price

    def delivery(self, source, rows):
        book = Workbook()
        sheet = book.active
        sheet.append(['账单时间', '团队ID', '团队名称', '骑手ID', '骑手名称', '详情', '运单号'])
        for index, (day, site, name) in enumerate(rows):
            sheet.append([f'2026-08-{day:02d}', 'T001' if site == '测试站' else 'T002',
                          site, '1001', name, '完成单', f'UNIQUE-ORDER-{index}'])
        book.save(source / '配送费.xlsx')
        book.close()

    def calculate(self, source):
        results, logs = [], []
        processor.process_rider_data(
            '测试城市', '半月结', str(source), '', lambda message, *_: logs.append(message),
            lambda *_: None, lambda *value: results.append(value), fixtures.THEME,
            output_root=str(source / 'output'), strict_inputs=True,
            skip_binding_check=True,
            deductionRules=[{'城市': '测试城市', '团队名称': site,
                             '团队ID': 'T001' if site == '测试站' else 'T002',
                             '安全基金': 10, '保险费': -0.5, '月费': 2.5}
                            for site in ('测试站', '另一站')],
        )
        self.assertEqual(results[-1][0], 'success', '\n'.join(logs))
        main = next(p for p in Path(results[-1][1]).glob('*.xlsx') if '蓝橙无单价&未绑名单' not in p.name)
        book = load_workbook(main)
        self.addCleanup(book.close)
        return book

    def fund_rows(self, book):
        values = list(book['安全基金'].iter_rows(values_only=True))
        return [dict(zip(values[0], row)) for row in values[1:] if row[1] is not None]

    def income_rows(self, book):
        # The existing income template has one header followed by the rider rows.
        return [row for row in book['配送所得表'].iter_rows(min_row=4, values_only=True)
                if len(row) > 2 and str(row[2]).removesuffix('.0') == '1001']

    def daily_orders(self, book):
        rows = list(book['日单量'].iter_rows(values_only=True))
        quantity = list(rows[0]).index('日单量')
        return sum(row[quantity] for row in rows[1:] if isinstance(row[quantity], (int, float)))

    def test_same_site_name_variants_create_one_wage_and_one_deduction_row(self):
        source = self.fixture()
        self.add_price(source)
        self.delivery(source, [(1, '测试站', '旧姓名'), (1, '测试站', '新姓名'), (2, '测试站', '新姓名')])
        book = self.calculate(source)
        fund = self.fund_rows(book)
        self.assertEqual(len(fund), 1)
        self.assertEqual(fund[0]['骑手姓名'], '合成人员')  # Application is the displayed name.
        self.assertEqual(fund[0]['出勤天数'], 2)
        self.assertEqual(fund[0]['安全基金'], 20)
        self.assertEqual(fund[0]['保险费'], -1)
        self.assertEqual(fund[0]['月费'], 2.5)  # Existing monthly fee remains a single fixed deduction.
        self.assertEqual(len(self.income_rows(book)), 1)
        self.assertEqual(self.daily_orders(book), 3)
        self.assertEqual(book['配送单'].max_row - 1, 3)

    def test_cross_site_wages_remain_separate_despite_same_rider_and_name_variants(self):
        source = self.fixture()
        self.delivery(source, [(1, '测试站', '旧姓名'), (2, '另一站', '新姓名')])
        book = self.calculate(source)
        fund = self.fund_rows(book)
        self.assertEqual({row['团队名称'] for row in fund}, {'测试站', '另一站'})
        self.assertEqual(len(fund), 2)
        self.assertEqual(len(self.income_rows(book)), 2)
        self.assertEqual(sum(row['出勤天数'] for row in fund), 2)
        self.assertEqual(sum(row['安全基金'] for row in fund), 20)
        self.assertEqual(self.daily_orders(book), 2)

    def test_missing_application_name_uses_latest_source_name(self):
        source = self.fixture()
        template = source / '兼职-template.xlsx'
        book = load_workbook(template)
        book['申请名单']['C2'] = None
        book.save(template)
        book.close()
        # The older name is placed last deliberately: selection follows the date.
        self.delivery(source, [(2, '测试站', '最新姓名'), (1, '测试站', '旧姓名')])
        book = self.calculate(source)
        fund = self.fund_rows(book)
        self.assertEqual(len(fund), 1)
        self.assertEqual(fund[0]['骑手姓名'], '最新姓名')
        self.assertEqual(fund[0]['出勤天数'], 2)
        self.assertEqual(self.daily_orders(book), 2)


if __name__ == '__main__':
    unittest.main()
