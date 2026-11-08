"""Company baseline preservation and independent Xiaoxiang manual routing."""
import ast
import asyncio
import datetime as dt
import hashlib
import json
from pathlib import Path
import re
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from openpyxl import Workbook, load_workbook
from openpyxl.worksheet.table import Table
from starlette.requests import Request

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import payroll_inputs
import payroll_business
import processor
import fengshen_processor
import test_optional_payroll_inputs as optional_fixture
THEME = optional_fixture.THEME

ROOT = Path(__file__).resolve().parents[2]


def fixture(folder):
    helper = optional_fixture.OptionalPayrollInputsTests()
    helper.root = folder
    source = helper.fixture(xiaoxiang=True)
    helper.add_price(source)
    # Original vendor exports need no 配送费 prefix.
    for path in source.glob('配送费_*.xlsx'):
        path.rename(path.with_name(path.name.removeprefix('配送费_')))
    template = source / '小象-template.xlsx'
    book = load_workbook(template)
    application = book['申请名单']
    second = [cell.value for cell in application[2]]
    second[1], second[2] = '2002', '第二合成人员'
    application.append(second)
    third = [cell.value for cell in application[2]]
    third[0] = '第二申请站'
    application.append(third)
    income = book['配送所得表']
    income.append([2, '测试站', '2002', '第二合成人员', 88, '', '旧绑定', '', ''])
    book.create_sheet('骑手订单明细').append(['合成模板表头'])
    management = book.create_sheet('管理费')
    management.append(['团队名称', '骑手ID', '骑手姓名', '取数1', '取数2', '取数3', '取数4', '取数5', '取数6', '招聘来源'])
    management.append(['测试站', '1001', '合成人员'] + [f'=B2*0+{i}' for i in range(1, 7)] + ['样例来源'])
    management.append(['旧团队', 'OLD', '旧人员'] + [None] * 7)
    management.append(['待清理旧团队', 'OLD2', '旧人员2'] + [None] * 7)
    management.add_table(Table(displayName='Table1', ref='A1:J2'))
    book.save(template)
    book.close()
    for path in source.glob('2026-*.xlsx'):
        book = load_workbook(path)
        book.active.append(['2002', '第二合成人员', '测试站', 4])
        book.active.append(['1001', '合成人员', '第二申请站', 5])
        book.active.append(['1001', '合成人员', '测试站', 0])
        book.save(path)
        book.close()
    orders = Workbook()
    orders.active.append(['合作商名称', '站点名称', '站点id', '业务日期', '骑手id', '骑手名称',
                          '合作商id', '配送方', '三方结算公司id', '城市id', '城市名称', '配送单量'])
    orders.active.append(['合成合作商', '测试站', '1', '2026-08-01', '1001', '合成人员',
                          '1', '合成配送方', '1', '1', '测试城市', 3])
    orders.active.append(['合成合作商', '第二申请站', '2', '2026-08-01', '1001', '合成人员',
                          '1', '合成配送方', '1', '1', '测试城市', 5])
    orders.active.append(['合成合作商', '非申请站点', '3', '2026-08-01', '1001', '合成人员',
                          '1', '合成配送方', '1', '1', '测试城市', 99])
    orders.save(source / '商配送骑手订单明细_样例.xlsx')
    orders.close()
    binding = Workbook()
    binding.active.append(['姓名', '证件号码', '小组名称'])
    binding.active.append(['合成人员', 'SYNTHETIC-CARD-001', '小象超市'])
    binding.save(source / 'merchantFreelancer_样例.xlsx')
    binding.close()
    return source


def normalized_company_tree(text):
    tree = ast.parse(text)
    # Compression setup is infrastructure. Restore its exact legacy AST solely
    # for the existing whole-module business-preservation checksum.
    policy_import = ast.parse('from workbook_policy import install_zip_policy').body[0]
    policy_call = ast.parse('install_zip_policy()').body[0]
    for index, node in enumerate(tree.body):
        if ast.dump(node) == ast.dump(policy_import):
            assert ast.dump(tree.body[index + 1]) == ast.dump(policy_call)
            legacy = ast.parse('_original_zipfile_init = zipfile.ZipFile.__init__\ndef _compressed_zipfile_init(self, file, mode="r", compression=zipfile.ZIP_STORED, allowZip64=True, compresslevel=None, **kwargs):\n    if mode in ("w", "a", "x"):\n        compression = zipfile.ZIP_DEFLATED\n        compresslevel = 9\n    _original_zipfile_init(self, file, mode, compression=compression, allowZip64=allowZip64, compresslevel=compresslevel, **kwargs)\nzipfile.ZipFile.__init__ = _compressed_zipfile_init\n').body
            tree.body[index:index + 2] = legacy
            break
    function = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == 'process_rider_data')
    assert isinstance(function.body[0], ast.ImportFrom) and function.body[0].module == 'payroll_business'
    assert isinstance(function.body[1], ast.If)
    function.body = function.body[2:]
    changed = 0
    for node in ast.walk(function):
        if isinstance(node, ast.Assign) and any(isinstance(target, ast.Name) and target.id == 'output_base' for target in node.targets):
            node.value = ast.parse('os.path.abspath(os.path.join(project_root, "outputs", output_type))', mode='eval').body
            changed += 1
    assert changed == 1
    return tree


# 引擎把运行当天日期（%m%d）写进标题与文件名，例如「测试城市08.01-08.02半月结兼职1018」。
# 合成对照需要跨天稳定，只归一化标题尾部的运行日期后缀，其余单元格原样比较。
_RUN_DATE_TITLE = re.compile(r'^(.*)(兼职)(\d{4})$')


def _norm_title(value):
    if isinstance(value, str):
        return _RUN_DATE_TITLE.sub(r'\1\2<RUN_DATE>', value)
    return value


def workbook_grid(path):
    book = load_workbook(path, data_only=False)
    try:
        return {sheet.title: {'rows': [[_norm_title(cell.value.isoformat() if isinstance(cell.value, (dt.date, dt.datetime)) else cell.value) for cell in row] for row in sheet.iter_rows()],
                              'formats': [[cell.number_format for cell in row] for row in sheet.iter_rows()],
                              'tables': {name: sheet.tables[name].ref for name in sheet.tables}}
                for sheet in book}
    finally:
        book.close()


class CompanyMergeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=Path(__file__).parent)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.patch = patch.object(payroll_inputs, 'ROOT', self.root)
        self.patch.start()
        self.addCleanup(self.patch.stop)

    def uploaded_fixture(self):
        source = fixture(self.root)
        upload = self.root / 'uploads' / 'company_test' / 'upload_fixture'
        upload.parent.mkdir(parents=True)
        import shutil
        shutil.copytree(source, upload)
        return upload

    def test_parttime_business_ast_matches_approved_removal_scope(self):
        proof = json.loads((ROOT / 'tests/fixtures/company_baseline.json').read_text(encoding='utf-8'))
        tree = normalized_company_tree((ROOT / 'backend/processor.py').read_text(encoding='utf-8'))
        checksum = hashlib.sha256(ast.dump(tree, include_attributes=False).encode()).hexdigest()
        self.assertEqual(checksum, proof['parttime_processor_ast_sha256'])
        self.assertEqual(processor.XIAOXIANG_STATION_KEYWORD_MAP['小象超市-荣盛站-CZ4002'], '荣盛站')

    def test_date_exports_and_vendor_filenames_survive_snapshot(self):
        source = self.uploaded_fixture()
        (source / '本次配置.json').write_text('{"synthetic":true}', encoding='utf-8')
        with patch('download_jobs.get_manager', side_effect=AssertionError('小象不得访问下载管理器')):
            folder, state = payroll_inputs.create(str(source), 'company_test', 'xiaoxiang')
        self.assertEqual(state['mode'], 'xiaoxiang')
        self.assertEqual(state['engine'], 'company_20261016')
        self.assertEqual(state['jobs'], [])
        self.assertEqual({path.name for path in (folder / 'input').iterdir()}, {path.name for path in source.iterdir()})
        self.assertEqual(state['items']['payment_binding']['status'], 'ready')
        self.assertEqual(state['items']['rider_orders']['status'], 'ready')
        for path in source.iterdir():
            self.assertEqual(payroll_inputs.digest(path), payroll_inputs.digest(folder / 'input' / path.name))
        payroll_inputs.checked_inputs(folder, state)

    def test_old_manual_selection_auto_detects_xiaoxiang_but_automatic_is_rejected(self):
        source = self.uploaded_fixture()
        _, _, mode = payroll_business.inspect_payroll(source, 'manual')
        self.assertEqual(mode, 'xiaoxiang')
        with self.assertRaisesRegex(payroll_inputs.SourceError, '仅支持独立手动'):
            payroll_inputs.create(str(source), 'company_test', 'fengshen', 'download_shared')
        for file in source.glob('2026-*.xlsx'):
            file.unlink()
        with self.assertRaisesRegex(payroll_inputs.SourceError, '日期命名'):
            payroll_business.inspect_payroll(source, 'xiaoxiang')

    def test_ordinary_dispatch_uses_new_engine(self):
        source = self.root / 'ordinary'
        source.mkdir()
        with patch.object(fengshen_processor, 'process_rider_data', return_value='new_engine') as call:
            result = processor.process_rider_data('测试城市', '半月结', str(source), '', None, None, None, THEME)
        self.assertEqual(result, 'new_engine')
        call.assert_called_once()

    def test_xiaoxiang_pipeline_does_not_apply_ordinary_price_binding_or_snapshot_rules(self):
        source = self.uploaded_fixture()
        calls = []
        async def calculate(*args, **kwargs):
            calls.append((args, kwargs))
            yield 'data: {"type":"finish","status":"success","out_file":""}\n\n'
        request = Request({'type': 'http', 'method': 'POST', 'scheme': 'http', 'path': '/api/run',
            'headers': [(b'host', b'localhost'), (b'x-workspace-id', b'company_test')],
            'client': ('127.0.0.1', 1), 'server': ('localhost', 80), 'query_string': b''})
        config = SimpleNamespace(payrollSourceMode='xiaoxiang', payrollPreparationId='',
            sourcePath=str(source), basePath='', theme=THEME, enableInterceptor=False,
            enableCrossStationMerge=False, deductionRules=[])
        async def run():
            return [event async for event in payroll_inputs.run_payroll(config, request)]
        with patch('tasks.run_main_calculation_gen', calculate), patch('download_jobs.get_manager', side_effect=AssertionError('自动下载被调用')):
            asyncio.run(run())
        self.assertEqual(len(calls), 1)
        self.assertIsNone(calls[0][1]['input_snapshot'])
        self.assertFalse(calls[0][1]['force_no_price'])
        self.assertFalse(calls[0][1]['skip_binding_check'])

    def test_company_result_matches_recorded_original_synthetic_result(self):
        source = fixture(self.root)
        results, logs = [], []
        with patch.object(fengshen_processor, 'process_rider_data', side_effect=AssertionError('小象误入普通引擎')):
            processor.process_rider_data('测试城市', '半月结', str(source), '', lambda message, *_: logs.append(message),
                lambda *_: None, lambda *args: results.append(args), THEME,
                output_root=str(self.root / 'output'), deductionRules=[{'城市': '测试城市', '团队名称': '测试站', '团队ID': 'T001'}])
        self.assertEqual(results[-1][0], 'success', '\n'.join(logs))
        actual = {}
        for file in Path(results[-1][1]).glob('*.xlsx'):
            role = 'exceptions' if '蓝橙无单价&未绑名单' in file.name else 'payroll'
            actual[role] = workbook_grid(file)
        expected_path = ROOT / 'tests/fixtures/xiaoxiang_company_expected.json'
        expected = json.loads(expected_path.read_text(encoding='utf-8'))
        from company_reference import expected_with_blank_placeholders
        # The six old "nan" strings are N2:N7 of a generated placeholder column,
        # not business values. Keep the original captured JSON and engine intact.
        expected = expected_with_blank_placeholders(expected, list(source.glob('2026-*.xlsx')), expected_path.read_bytes())
        self.assertEqual([row[13] for row in actual['payroll']['配送单']['rows'][1:]], [None] * 6)
        self.assertEqual(actual, expected)
        rows = actual['payroll']['骑手订单明细']['rows']
        self.assertEqual(len(rows), 3)  # header plus two approved application sites
        self.assertNotIn('非申请站点', str(rows))
        management = actual['payroll']['管理费']
        self.assertTrue(str(management['rows'][2][3]).startswith('='))
        self.assertEqual(management['tables']['Table1'], 'A1:J4')


if __name__ == '__main__':
    unittest.main()
