import datetime as dt
from pathlib import Path
import shutil
import sys
import tempfile
import threading
import unittest

from openpyxl import Workbook, load_workbook
from openpyxl.utils import get_column_letter

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from abnormal_followup import (_binding_statuses, _pay_binding_value, _prune_ub_sheet,
                               _write_analysis_sheet, build_followup_summaries,
                               generate_abnormal_followup)
from fengshen_bill import BillCollectionError
from followup_workbook import create_followup_workbook


def write_book(path, sheets):
    book = Workbook()
    book.remove(book.active)
    for title, rows in sheets.items():
        sheet = book.create_sheet(title)
        for row in rows:
            sheet.append(row)
        sheet.column_dimensions['A'].width = 18
    book.save(path)
    book.close()


def detail_row(day, rider, name, team, orders):
    return [day, rider, name, None, None, team] + [None] * 10 + [orders]


UB_HEADERS = ['账单ID', '骑手ID', '骑手姓名', '代理商ID', '骑手所属站点ID',
              '骑手所属站点名称', '账单周期', '在职时间', '基础薪资方案名称ID',
              '扣款方案名称ID', '排班内单量', '排班外单单量', '住宿费用（只能下调）',
              '车辆租金（只能下调）', '账单状态', '非一口价单量', '一口价单量', '总单量']


def ub_row(bill, rider, name, team, salary, deduction):
    return [bill, rider, name, None, None, team, None, None, salary, deduction] + [None] * 8


def has_thin_border(cell):
    return all(getattr(cell.border, side).style == 'thin'
               for side in ('left', 'right', 'top', 'bottom'))


def has_no_border(cell):
    return all(getattr(cell.border, side).style is None
               for side in ('left', 'right', 'top', 'bottom'))


PAY_HEADERS = ['城市', '团队名称', '骑手ID', '骑手姓名', '骑手身份证',
               '骑手手机号', '风神绑定', '发薪平台绑定', '绑定情况']


def pay_sheet(rows):
    book = Workbook()
    sheet = book.active
    sheet.append(PAY_HEADERS)
    for row in rows:
        sheet.append(row)
    return book, sheet


class PayBindingTests(unittest.TestCase):
    def test_uses_binding_status_not_platform_column(self):
        book, sheet = pay_sheet([
            ['三亚', '一组', 'R1', '张三', 'CARD-A', '', '已绑定', '已绑定', '风神未绑定']])
        self.addCleanup(book.close)
        self.assertEqual(_pay_binding_value(_binding_statuses(sheet), 'CARD-A'), '未绑定')

    def test_first_match_wins(self):
        book, sheet = pay_sheet([
            ['三亚', '一组', 'R1', '张三', 'CARD-A', '', '', '', '已绑定'],
            ['三亚', '二组', 'R1', '张三', 'CARD-A', '', '', '', '未绑定']])
        self.addCleanup(book.close)
        self.assertEqual(_pay_binding_value(_binding_statuses(sheet), 'CARD-A'), '已绑定')

    def test_proxy_text_is_bound_and_unknown_is_unbound(self):
        book, sheet = pay_sheet([
            ['三亚', '一组', 'R1', '张三', 'CARD-B', '', '', '', '【审批中】代发（李四）']])
        self.addCleanup(book.close)
        statuses = _binding_statuses(sheet)
        self.assertEqual(_pay_binding_value(statuses, 'CARD-B'), '已绑定')
        self.assertEqual(_pay_binding_value(statuses, 'CARD-MISSING'), '未绑定')
        self.assertEqual(_pay_binding_value(statuses, None), '未绑定')
        self.assertEqual(_pay_binding_value(statuses, ''), '未绑定')

    def test_missing_columns_raise(self):
        book = Workbook()
        sheet = book.active
        self.addCleanup(book.close)
        sheet.append(['骑手ID', '发薪平台绑定'])
        with self.assertRaises(BillCollectionError):
            _binding_statuses(sheet)


class AbnormalFollowupTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=Path(__file__).parent)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def sources(self):
        binding = self.root / 'binding.xlsx'
        write_book(binding, {
            '10月骑手绑定情况': [
                ['城市', '团队名称', '骑手ID', '骑手姓名', '骑手身份证', '发薪平台绑定', '绑定情况'],
                ['三亚', '三亚一组', 'R001', '张三', '110101199001010011', '已绑定', '已绑定'],
                ['三亚', '三亚二组(测试)', 'R002', '李四', '110101199002020022', '未绑定', '未绑定'],
                ['三亚', '三亚三组', 'R005', '钱七', '110101199005050055', '已绑定', '已绑定'],
                ['三亚', '三亚四组', 'R006', '孙八', '110101199006060066', '已绑定', '已绑定'],
                ['三亚', '三亚五组', 'R007', '周九', '110101199007070077', '已绑定', '已绑定'],
            ],
            '骑手详情表': [
                ['日期', '骑手ID', '骑手姓名', '骑手手机号', '团队ID', '团队名称',
                 '所属管理分组', '骑手等级', '最新入职时间', '最新离职时间', '在职状态',
                 '入职时长', '活跃天数', '有效在线时长', '午高峰有效在线时长',
                 '晚高峰有效在线时长', '有效完成单'],
                detail_row('2026-10-01', 'R001', '张三', '三亚一组', 5),
                detail_row('2026-10-02', 'R001', '张三', '三亚一组', 0),
                detail_row('2026-10-03', 'R001', '张三', '三亚一组', 3),
                detail_row('2026-10-01', 'R002', '李四', '三亚二组（测试）', 7),
                detail_row('2026-10-05', 'R002', '李四', '三亚二组（测试）', 2),
                detail_row('2026-10-02', 'R005', '钱七', '三亚三组', 0),
                detail_row('2026-10-03', 'R002', '李四', '三亚三组', 4),
                detail_row('2026-10-06', 'R006', '孙八', '三亚四组', 6),
                detail_row('2026-10-07', 'R007', '周九', '三亚五组', 3),
            ],
            '骑手信息表': [
                ['骑手ID', '姓名', '手机号', '身份证'],
                ['R001', '张三', '13800000000', '110101199001010011'],
                ['R002', '李四', '13900000000', '110101199002020022'],
                ['R005', '钱七', '13700000000', '110101199005050055'],
                ['R006', '孙八', '13600000000', '110101199006060066'],
                ['R007', '周九', '13500000000', '110101199007070077'],
            ],
        })
        ub = self.root / 'ub.xlsx'
        write_book(ub, {
            '骑手薪资文件': [
                ['账单期间不可编辑的提示'],
                ['账单基础信息', '三亚'],
                ['方案基本信息', '2026-10'],
                UB_HEADERS,
                ub_row('B1', 'R001', '张三', '三亚一组', '方案A(1)', '扣款A(1)'),
                ub_row('B2', 'R002', '李四', '三亚二组（测试）', '方案B(2)', ''),
                ub_row('B3', 'R006', '孙八', '三亚四组', '方案C(3)', '扣款C(3)'),
                ub_row('B4', 'R007', '周九', '三亚五组', '方案D(4)', '扣款D(4)'),
            ],
        })
        price = self.root / 'price.xlsx'
        write_book(price, {'价格档案': [
            ['城市名称', '日期', '站点名称', '骑手姓名', '价格', '身份证号'],
            ['三亚市', '2026-10-01', '三亚一组', '张三', 10, '110101199001010011'],
            ['三亚市', '2026-09-30', '三亚一组', '李四', 20, '110101199002020022'],
            ['海口市', '2026-10-02', '海口一组', '王五', 30, '110101199003030033'],
            ['三亚市', '', '三亚一组', '赵六', 40, '110101199004040044'],
            ['三亚市', '2026-10-03', '三亚一组', '钱七', 50, '110101199005050055'],
            ['三亚市', '2026-10-04', '三亚六组', '孙八', 0, '110101199006060066'],
        ]})
        archive = self.root / 'archive.xlsx'
        write_book(archive, {'骑手档案': [
            ['姓名', '城市', '项目', '站点', '骑手ID', '身份证号', '合作类型', '当前生效兼职价格',
             '合作日期', '推荐人身份证号', '三方公司/推荐人', '招聘来源', '状态', '是否寒暑假工', '备注'],
            ['孙八', '三亚', '淘鲜达', '三亚站', 'R006', '110101199006060066', '兼职', 8.5, '2026-01-01', None, None,
             '骑手内推', '正常', '否', ''],
            ['王五', '三亚', '城代', '三亚站', 'R003', '110101199003030033', '全职', 8.5, '2026-01-01', None, None,
             '骑手内推', '正常', '否', ''],
            ['李四', '三亚', 'U+B', '三亚站', 'R002', '110101199002020022', '全职', 8.5, '2026-01-01', None, None,
             '骑手内推', '正常', '否', ''],
            ['赵六', '三亚', None, '三亚站', 'R004', '110101199004040044', '全职', 8.5, '2026-01-01', None, None,
             '骑手内推', '正常', '否', ''],
            ['钱七', '海口', 'U+B', '海口站', 'R005', '110101199005050055', '全职', 8.5, '2026-01-01', None, None,
             '骑手内推', '正常', '否', ''],
            ['张三', '三亚', '饿了么', '三亚站', 'R001', '110101199001010011', '兼职', 8.5, '2026-01-01', None, None,
             '管理内推', '合作', '否', ''],
            ['周九', '三亚', '饿了么', '三亚站', 'R007', '110101199007070077', '兼职', 8.5, '2026-01-01', None, None,
             '骑手内推', '正常', '否', ''],
            # 同一身份证两行：合作日期不同，用于验证按项目排序后的首行匹配
            ['李四', '三亚', '淘鲜达', '三亚站', 'R002', '110101199002020022', '兼职', 8.5, '2026-02-01', None, None,
             '地推', '离职', '是', ''],
        ]})
        goods = self.root / 'goods.xlsx'
        write_book(goods, {'电动车住宿租用': [
            ['站点名称', '站点id', '骑手姓名', '骑手id', '手机号', '物资大类', '物资类型',
             '租用数量', '租用时间', '登记人', '备注', '状态'],
            ['三亚一组', '1', '张三', 'R001', '13800000000', '租用', '电动车', 1,
             '2026-09-01至2026-09-30', '陈阵威', '', '进行中'],
            ['三亚一组', '1', '张三', 'R001', '13800000000', '租用', '住宿', 1,
             '2026-10-01至2026-10-31', '陈阵威', '', '进行中'],
            ['三亚一组', '1', '张三', 'R001', '13800000000', '租用', '电动车', 1,
             '2026-09-20至2026-10-02', '陈阵威', '', '进行中'],
            ['三亚二组（测试）', '2', '李四', 'R002', '13900000000', '租用', '电动车', 1,
             '2026-10-30至2026-11-05', '陈阵威', '', '进行中'],
            ['三亚三组', '3', '钱七', 'R005', '13700000000', '租用', '住宿', 1,
             '2026-10-01至2026-10-31', '陈阵威', '', '撤销'],
            ['三亚四组', '4', '孙八', 'R006', '13600000000', '租用', '电动车', 1,
             '时间未知', '陈阵威', '', '进行中'],
            ['三亚五组', '5', '周九', 'R007', '13500000000', '租用', '住宿', 1,
             '2026-09-01至2026-10-01', '陈阵威', '', '进行中'],
            ['三亚一组', '1', '吴十', 'R009', '13400000000', '租用', '住宿', 1,
             '2026-11-01至2026-11-30', '陈阵威', '', '进行中'],
            ['三亚三组', '3', '李四', 'R002', '13900000000', '租用', '住宿', 1,
             '2026-10-31至2026-12-31', '陈阵威', '', '进行中'],
        ]})
        return binding, ub, price, archive, goods

    def test_analysis_hij_include_running_riders_independent_of_abnormal_flag(self):
        book = Workbook()
        main = book.active
        headers = ['城市', '团队名称', '骑手ID', '合作类型', '状态', '是否寒暑假工', '备注',
                   '薪资方案是否绑定', '扣款方案是否绑定', '兼职无单价报备骑手',
                   '发薪工具是否绑定', '10月活跃天', '是否异常骑手', '合作日期']
        for column, name in enumerate(headers, 1):
            main.cell(3, column, name)
        rows = [
            ['三亚', '一组', '1', '全职', '正常', '否', None, '是', '是', '否', '已绑', 10, '否',
             dt.datetime(2026, 10, 1)],
            ['三亚', '一组', '2', '全职', '正常', '否', None, '是', '是', '否', '已绑', 10, '否',
             '2026-10-15'],
            ['三亚', '一组', '3', '全职', '正常', '否', None, '是', '是', '否', '已绑', 10, '否',
             '2026-09-30'],
            ['三亚', '一组', '4', '全职', '正常', '否', None, '是', '是', '否', '已绑', 10, '否',
             '蓝橙未入职'],
            ['三亚', '一组', '5', '全职', '正常', '否', '住宿天数少于出勤天数', '是', '是', '否',
             '已绑', 10, '是', dt.datetime(2026, 10, 20)],
            # 有备注、方案未绑但异常=否：仍计入H/J；正常且无备注也计入I。
            ['三亚', '一组', '6', '全职', '正常', '否', '租车天数少于出勤天数', '否', '否', '否',
             '已绑', 10, '否', dt.datetime(2026, 10, 5)],
            # 异常但未跑单：不计入三列，但首跑仍按合作日期计数
            ['三亚', '二组', '7', '全职', '正常', '否', None, '否', '否', '否', '已绑', 0, '是',
             '2026-10-02'],
        ]
        for row_index, values in enumerate(rows, 4):
            for column, value in enumerate(values, 1):
                main.cell(row_index, column, value)
        analysis = book.create_sheet('分析表')
        try:
            _write_analysis_sheet(analysis, main, '2026-10')
            # 拼音升序：二组(èr) 在 一组(yī) 之前；占比列跑单为 0 时留空
            self.assertEqual([[analysis.cell(row, column).value
                               for column in range(3, 16)] for row in range(3, 6)],
                             [[0, 0, 0, 0, None, 0, 0, 0, None, 0, 0, 0, 1],
                              [6, 0, 6, 0, 0.0, 2, 4, 1, None, 0, 0, 0, 4],
                              [6, 0, 6, 0, 0.0, 2, 4, 1, None, 0, 0, 0, 5]])
            original_flags=[main.cell(row,13).value for row in range(4,11)]
            _write_analysis_sheet(analysis,main,'2026-10',summary=True)
            self.assertEqual([analysis.cell(3,c).value for c in (8,9,10)],[2,4,1])
            self.assertEqual([main.cell(row,13).value for row in range(4,11)],original_flags)
        finally:
            book.close()

    def test_workbook_uses_required_name_header_rows_and_centered_cells(self):
        output = self.root / 'out'
        target = generate_abnormal_followup(
            *self.sources(), '三亚', '2026-10', output, stamp=dt.date(2026, 10, 23))
        self.assertEqual(target.name, '三亚10月异常骑手跟进明细表1023.xlsx')

        book = load_workbook(target, data_only=False)
        try:
            guide = book['说明']
            self.assertEqual(book.sheetnames[0], '说明')
            self.assertEqual(guide['A1'].value, '三亚 · 10月异常骑手跟进说明')
            self.assertEqual(guide.freeze_panes, 'A2')
            self.assertEqual([guide.cell(row, 2).value for row in range(4, 12)],
                             ['三亚', '2026-10-01 至 2026-10-31', '6', '6', '5',
                      '4（在跑单 3）', '4 / 1', '0'])
            self.assertEqual(guide.cell(14, 1).value, '异常原因')
            self.assertEqual(guide.cell(15, 1).value, '状态解除合作')
            self.assertEqual(guide.cell(21, 5).value, '薪资组/城市')
            self.assertEqual(guide.cell(37, 1).value, '问题')

            binding = book['10月风神薪资方案绑定']
            self.assertEqual([cell.value for cell in binding[1]], UB_HEADERS)
            self.assertEqual(binding.max_column, 18)
            self.assertEqual([binding.cell(2, column).value for column in (1, 2, 3, 6, 9, 10)],
                             ['B1', 'R001', '张三', '三亚一组', '方案A(1)', '扣款A(1)'])
            self.assertEqual(binding.cell(3, 3).value, '李四')
            self.assertEqual(binding.freeze_panes, 'A2')

            main = book['10月异常骑手跟进表']
            self.assertIn('10月', main['A1'].value)
            self.assertEqual(main.freeze_panes, 'A4')
            self.assertEqual([main.cell(4, column).value for column in range(1, 6)],
                             ['三亚', '三亚一组', 'R001', '张三', '110101199001010011'])
            self.assertEqual(main.cell(4, 11).value, '已绑定')
            self.assertEqual([main.cell(5, column).value for column in range(1, 6)],
                             ['三亚', '三亚二组（测试）', 'R002', '李四', '110101199002020022'])
            self.assertEqual(main.cell(5, 11).value, '未绑定')
            self.assertEqual([main.cell(7, column).value for column in range(1, 6)],
                             ['三亚', '三亚三组', 'R002', '李四', '110101199002020022'])
            self.assertEqual([main.cell(4, column).value for column in range(6, 10)],
                             ['兼职', '合作', '管理内推', '否'])
            self.assertEqual([main.cell(5, column).value for column in range(6, 10)],
                             ['全职', '正常', '骑手内推', '否'])
            self.assertEqual([main.cell(6, column).value for column in range(6, 10)],
                             ['蓝橙未入职'] * 4)
            self.assertEqual([main.cell(7, column).value for column in range(6, 10)],
                             ['全职', '正常', '骑手内推', '否'])
            self.assertEqual([main.cell(row, 10).value for row in range(4, 10)],
                             ['否', '否', '否', '否', '是', '是'])
            self.assertEqual([main.cell(4, column).value for column in range(12, 15)],
                             [2, 8, dt.datetime(2026, 10, 3)])
            self.assertEqual([main.cell(5, column).value for column in range(12, 15)],
                             [2, 9, dt.datetime(2026, 10, 5)])
            self.assertEqual([main.cell(7, column).value for column in range(12, 15)],
                             [1, 4, dt.datetime(2026, 10, 3)])
            self.assertEqual([main.cell(6, column).value for column in range(12, 14)], [0, 0])
            self.assertIsNone(main.cell(6, 14).value)
            self.assertEqual(main.cell(4, 14).number_format, 'yyyy-mm-dd')
            self.assertEqual(main.cell(6, 14).number_format, 'yyyy-mm-dd')

            # 是否异常骑手：状态命中 / 距详情表最大日期(10-07)≥3天 / 薪资或扣款方案未绑定
            self.assertEqual([main.cell(row, 15).value for row in range(4, 10)],
                             ['是', '是', '是', '是', '否', '否'])
            self.assertEqual([main.cell(row, 16).value or None for row in range(4, 10)],
                             ['3天以上未出勤', '扣款方案未绑定',
                              '状态蓝橙未入职；当月无有效完单；薪资方案未绑定；扣款方案未绑定',
                              # 李四在风神只有二组账单：三组行按严格配对判否，不按骑手ID兜底
                              '3天以上未出勤；薪资方案未绑定；扣款方案未绑定', None, None])
            self.assertEqual([main.cell(row, 24).value for row in range(4, 10)],
                             ['是', '是', '否', '否', '是', '是'])
            self.assertEqual([main.cell(row, 25).value for row in range(4, 10)],
                             ['是', '否', '否', '否', '是', '是'])

            # 租车/住宿天数：按站点+骑手ID 配对租用子表月内天数，无记录写 0
            self.assertEqual([main.cell(row, 21).value for row in range(4, 10)], [2, 2, 0, 0, 0, 0])
            self.assertEqual([main.cell(row, 22).value for row in range(4, 10)], [31, 0, 0, 1, 0, 1])
            self.assertEqual([has_thin_border(main.cell(row, 21)) for row in range(4, 10)],
                             [True] * 6)

            # W 备注：活跃天大于租车/住宿天数即标注缺口（租车在前，；拼接）；Z 列按备注是否为空
            self.assertEqual([main.cell(row, 23).value for row in range(4, 10)],
                             [None, '住宿天数少于出勤天数', None,
                              '租车天数少于出勤天数',
                              '租车天数少于出勤天数；住宿天数少于出勤天数',
                              '租车天数少于出勤天数'])
            self.assertEqual([main.cell(row, 26).value for row in range(4, 10)],
                             ['否', '是', '否', '是', '是', '是'])
            self.assertTrue(main.cell(5, 23).alignment.wrap_text)
            self.assertFalse(main.cell(4, 23).alignment.wrap_text)
            # 异常原因/备注列宽在全部数据写入后自适应，上限 60
            self.assertGreater(main.column_dimensions['P'].width, 30)
            self.assertLessEqual(main.column_dimensions['P'].width, 60)
            self.assertEqual(main.column_dimensions['W'].width, 44.0)

            # 合作日期：蓝橙员工档案按身份证首行匹配（李四取 U+B 行，非淘鲜达行），
            # 文本日期转真实日期；未匹配沿用「蓝橙未入职」
            joined = dt.datetime(2026, 1, 1)
            self.assertEqual([main.cell(row, 31).value for row in range(4, 10)],
                             [joined, joined, '蓝橙未入职', joined, joined, joined])
            self.assertEqual([main.cell(row, 31).number_format for row in range(4, 10)],
                             ['yyyy-mm-dd'] * 6)

            price_sheet = book['10月蓝橙价格档案']
            self.assertEqual([price_sheet.cell(1, column).value for column in range(1, 6)],
                             ['城市名称', '日期', '站点名称', '骑手姓名', '价格'])
            self.assertEqual([price_sheet.cell(row, 4).value for row in (2, 3, 4)],
                             ['张三', '钱七', '孙八'])
            self.assertEqual(price_sheet.max_row, 4)
            self.assertEqual(price_sheet.freeze_panes, 'A2')

            archive = book['10月蓝橙员工档案']
            self.assertEqual([cell.value for cell in archive[1]],
                             ['项目', '城市', '站点', '骑手ID', '姓名', '身份证号', '合作类型',
                              '当前生效兼职价格', '合作日期', '推荐人身份证号', '三方公司/推荐人',
                              '招聘来源', '状态', '是否寒暑假工'])
            self.assertEqual(archive.max_column, 14)
            self.assertEqual(archive.max_row, 6)
            self.assertEqual([archive.cell(row, 1).value for row in range(2, 7)],
                             ['U+B', '饿了么', '饿了么', '淘鲜达', '淘鲜达'])
            self.assertEqual([archive.cell(row, 5).value for row in range(2, 7)],
                             ['李四', '张三', '周九', '孙八', '李四'])
            self.assertTrue(all(archive.cell(row, 2).value == '三亚' for row in range(2, 7)))
            self.assertEqual(archive.freeze_panes, 'A2')

            rental = book['10月电动车住宿租用']
            self.assertEqual([cell.value for cell in rental[1]],
                             ['站点名称', '站点id', '骑手姓名', '骑手id', '手机号', '物资大类',
                              '物资类型', '租用数量', '租用时间', '租用天数', '登记人', '备注', '状态'])
            self.assertEqual(rental.max_column, 13)
            # 撤销、租用时间无法识别、与 10 月无交集的记录都不保留
            self.assertEqual(rental.max_row, 6)
            self.assertEqual([rental.cell(row, 3).value for row in range(2, 7)],
                             ['张三', '张三', '李四', '周九', '李四'])
            self.assertEqual([rental.cell(row, 7).value for row in range(2, 7)],
                             ['住宿', '电动车', '电动车', '住宿', '住宿'])
            self.assertEqual([rental.cell(row, 9).value for row in range(2, 7)],
                             ['2026-10-01至2026-10-31', '2026-09-20至2026-10-02',
                              '2026-10-30至2026-11-05', '2026-09-01至2026-10-01',
                              '2026-10-31至2026-12-31'])
            self.assertEqual([rental.cell(row, 10).value for row in range(2, 7)],
                             [31, 2, 2, 1, 1])
            self.assertEqual(rental.freeze_panes, 'A2')

            # 分析表：按站点汇总额外，表头两行 + 合计行，活动金额留空；
            # H/I/J统计所有在跑单骑手，不再要求异常；其余统计口径不变。
            analysis = book['分析表']
            self.assertEqual(analysis.freeze_panes, 'A3')
            self.assertEqual(analysis.max_row, 8)
            self.assertEqual([analysis.cell(1, column).value
                              for column in (1, 2, 3, 8, 12, 13, 14, 15)],
                             ['城市', '站点', '10月跑单骑手类型', '异常骑手',
                              '兼职无单价报备骑手', '解除合作仍在跑单骑手',
                              '发薪工具未绑骑手数量', '10月首跑(含兼职转全职)'])
            self.assertEqual([analysis.cell(2, column).value for column in range(3, 12)],
                             ['跑单骑手', '兼职骑手', '全职骑手', '跑单未入职骑手',
                              '兼职占比', '未维护或维护天数少于出勤天', '已维护',
                              '风神未绑薪资方案/扣款方案', '涉及活动金额'])
            self.assertEqual({str(rng) for rng in analysis.merged_cells.ranges},
                             {'A1:A2', 'B1:B2', 'C1:G1', 'H1:K1',
                              'L1:L2', 'M1:M2', 'N1:N2', 'O1:O2'})
            # 站点按拼音升序（Windows 简体中文排序规则），兼职占比=兼职/跑单
            self.assertEqual([analysis.cell(row, 2).value for row in range(3, 9)],
                             ['三亚二组（测试）', '三亚三组', '三亚四组', '三亚五组',
                              '三亚一组', '合计'])
            self.assertEqual([[analysis.cell(row, column).value for column in range(3, 16)]
                              for row in range(3, 9)],
                             [[1, 0, 1, 0, 0.0, 1, 0, 1, None, 0, 0, 1, 0],
                              [1, 0, 1, 0, 0.0, 1, 0, 1, None, 0, 0, 1, 0],
                              [1, 1, 0, 0, 1.0, 1, 0, 0, None, 1, 0, 0, 0],
                              [1, 1, 0, 0, 1.0, 1, 0, 0, None, 1, 0, 0, 0],
                              [1, 1, 0, 0, 1.0, 0, 1, 0, None, 0, 0, 0, 0],
                              [5, 3, 2, 0, 0.6, 4, 1, 2, None, 2, 0, 2, 0]])
            self.assertEqual([analysis.cell(row, 1).value for row in range(3, 9)],
                             ['三亚', '三亚', '三亚', '三亚', '三亚', None])
            self.assertEqual(analysis.cell(3, 7).number_format, '0.00%')
            self.assertEqual(analysis.cell(8, 7).number_format, '0.00%')
            conditional = next(iter(analysis.conditional_formatting))
            self.assertEqual(str(conditional.sqref), 'G3:G8')
            self.assertEqual(conditional.rules[0].type, 'dataBar')
            # 表头配色与截图一致：城市/站点与异常骑手黄、骑手类型绿、右侧四列橙；合计行蓝
            self.assertEqual([analysis.cell(1, column).fill.fgColor.rgb
                              for column in (1, 3, 8, 12)],
                             ['FFFFFF00', 'FF92D050', 'FFFFFF00', 'FFFFC000'])
            self.assertEqual([analysis.cell(2, column).fill.fgColor.rgb
                              for column in (5, 9)],
                             ['FF92D050', 'FFFFFF00'])
            self.assertEqual([analysis.cell(1, column).fill.fgColor.rgb
                              for column in (12, 15)],
                             ['FFFFC000', 'FFFFC000'])
            self.assertEqual([analysis.cell(8, column).fill.fgColor.rgb
                              for column in (1, 8, 15)],
                             ['FF00B0F0', 'FF00B0F0', 'FF00B0F0'])

            for name, header_rows in (('10月骑手绑定情况', 1), ('10月骑手详情表', 1),
                                      ('10月骑手信息表', 1), ('10月风神薪资方案绑定', 1),
                                      ('10月蓝橙价格档案', 1), ('10月蓝橙员工档案', 1),
                                      ('10月电动车住宿租用', 1)):
                sheet = book[name]
                self.assertEqual(sheet.freeze_panes, f'A{header_rows + 1}')
                for row in range(1, header_rows + 1):
                    for column in range(1, sheet.max_column + 1):
                        self.assertEqual(sheet.cell(row=row, column=column).fill.fgColor.rgb,
                                         'FFFBE5D6', f'{name}!r{row}c{column}')

            for sheet in book.worksheets:
                if sheet.title == '说明':
                    continue
                for row in sheet.iter_rows():
                    for cell in row:
                        if cell.value is not None:
                            self.assertEqual((cell.alignment.horizontal, cell.alignment.vertical),
                                             ('center', 'center'),
                                             f'{sheet.title}!{cell.coordinate}')
                for column in range(1, sheet.max_column + 1):
                    alignment = sheet.column_dimensions[get_column_letter(column)].alignment
                    self.assertEqual((alignment.horizontal, alignment.vertical), ('center', 'center'),
                                     f'{sheet.title}!{get_column_letter(column)}')
        finally:
            book.close()

    def test_sub_sheet_freeze_follows_header_rows_not_source_position(self):
        binding, ub, price, archive, goods = self.sources()
        source = load_workbook(binding)
        source['骑手详情表'].freeze_panes = 'D9'
        source['10月骑手绑定情况'].freeze_panes = 'C3'
        source.save(binding)
        source.close()
        target = generate_abnormal_followup(
            binding, ub, price, archive, goods, '三亚', '2026-10', self.root / 'out',
            stamp=dt.date(2026, 10, 23))
        book = load_workbook(target)
        try:
            self.assertEqual(book['10月骑手详情表'].freeze_panes, 'A2')
            self.assertEqual(book['10月骑手绑定情况'].freeze_panes, 'A2')
            self.assertEqual(book['10月异常骑手跟进表'].freeze_panes, 'A4')
        finally:
            book.close()

    def test_ub_source_formatted_layout_copies_without_preamble(self):
        from parttime_source import format_rider_monthly_workbook
        binding, ub, price, archive, goods = self.sources()
        formatted = format_rider_monthly_workbook(ub, self.root / 'ub_formatted.xlsx')
        book = load_workbook(formatted)
        try:
            self.assertEqual(book.active['A1'].value, '账单ID')
        finally:
            book.close()
        target = generate_abnormal_followup(
            binding, formatted, price, archive, goods, '三亚', '2026-10', self.root / 'out',
            stamp=dt.date(2026, 10, 23))
        book = load_workbook(target)
        try:
            sheet = book['10月风神薪资方案绑定']
            self.assertEqual([cell.value for cell in sheet[1]], UB_HEADERS)
            self.assertEqual(sheet.max_column, 18)
            self.assertEqual([sheet.cell(row, 1).value for row in range(2, sheet.max_row + 1)],
                             ['B1', 'B2', 'B3', 'B4'])
            self.assertEqual(sheet.freeze_panes, 'A2')
        finally:
            book.close()

    def test_ub_sheet_keeps_eighteen_columns_in_order_and_rejects_missing(self):
        book = create_followup_workbook('2026-10')
        self.addCleanup(book.close)
        sheet = book['10月风神薪资方案绑定']
        for column, name in enumerate(UB_HEADERS + ['薪资合计'], 1):
            sheet.cell(1, column, name)
        sheet.cell(2, 1, 'B1')
        sheet.cell(2, 9, '方案A')
        sheet.cell(2, 13, '773.42')
        sheet.cell(2, 13).number_format = '0.00'
        _prune_ub_sheet(book)
        sheet = book['10月风神薪资方案绑定']
        self.assertEqual([cell.value for cell in sheet[1]], UB_HEADERS)
        self.assertEqual(sheet.max_column, 18)
        self.assertEqual([sheet.cell(2, column).value for column in (1, 9, 13)],
                         ['B1', '方案A', '773.42'])
        self.assertEqual(sheet.cell(2, 13).number_format, '0.00')
        self.assertEqual(sheet.freeze_panes, 'A2')

        incomplete = create_followup_workbook('2026-10')
        self.addCleanup(incomplete.close)
        sheet = incomplete['10月风神薪资方案绑定']
        for column, name in enumerate(UB_HEADERS[:-1], 1):
            sheet.cell(1, column, name)
        with self.assertRaises(BillCollectionError) as error:
            _prune_ub_sheet(incomplete)
        self.assertIn('总单量', str(error.exception))

    def test_main_cross_station_split_and_missing_card_is_unbound(self):
        sources = self.sources()
        write_book(sources[0], {
            '10月骑手绑定情况': [
                ['城市', '团队名称', '骑手ID', '骑手姓名', '骑手身份证', '发薪平台绑定', '绑定情况'],
                ['三亚', 'A站', 'R001', '张三', '110101199001010011', '已绑定', '已绑定'],
            ],
            '骑手详情表': [
                ['日期', '骑手ID', '骑手姓名', '骑手手机号', '团队ID', '团队名称',
                 '所属管理分组', '骑手等级', '最新入职时间', '最新离职时间', '在职状态',
                 '入职时长', '活跃天数', '有效在线时长', '午高峰有效在线时长',
                 '晚高峰有效在线时长', '有效完成单'],
                detail_row('2026-10-01', 'R001', '张三', 'A站', 5),
                detail_row('2026-10-02', 'R001', '张三', 'B站', 2),
                detail_row('2026-10-03', 'R002', '李四', 'A站', 1),
            ],
            '骑手信息表': [
                ['骑手ID', '姓名', '手机号', '身份证'],
                ['R001', '张三', '13800000000', '110101199001010011'],
            ],
        })
        target = generate_abnormal_followup(
            *sources, '三亚', '2026-10', self.root / 'out', stamp=dt.date(2026, 10, 23))
        book = load_workbook(target, data_only=False)
        try:
            main = book['10月异常骑手跟进表']
            self.assertEqual(main.max_row, 6)
            self.assertEqual([main.cell(4, column).value for column in range(1, 6)],
                             ['三亚', 'A站', 'R001', '张三', '110101199001010011'])
            self.assertEqual(main.cell(4, 11).value, '已绑定')
            self.assertEqual([main.cell(5, column).value for column in range(1, 6)],
                             ['三亚', 'B站', 'R001', '张三', '110101199001010011'])
            self.assertEqual(main.cell(5, 11).value, '已绑定')
            self.assertEqual([main.cell(6, column).value for column in range(1, 6)],
                             ['三亚', 'A站', 'R002', '李四', None])
            # 骑手信息表没有该骑手身份证，绑定表无从匹配，按约定记未绑定
            self.assertEqual(main.cell(6, 11).value, '未绑定')
            self.assertTrue(has_thin_border(main.cell(6, 3)))
            self.assertTrue(has_thin_border(main.cell(6, 11)))
        finally:
            book.close()

    def test_main_rider_id_numeric_and_header_fill(self):
        sources = self.sources()
        write_book(sources[0], {
            '10月骑手绑定情况': [
                ['城市', '团队名称', '骑手ID', '骑手姓名', '骑手身份证', '发薪平台绑定', '绑定情况'],
                ['三亚', 'A站', '111234567890123', '张三', '110101199001010011', '已绑定', '已绑定'],
            ],
            '骑手详情表': [
                ['日期', '骑手ID', '骑手姓名', '骑手手机号', '团队ID', '团队名称',
                 '所属管理分组', '骑手等级', '最新入职时间', '最新离职时间', '在职状态',
                 '入职时长', '活跃天数', '有效在线时长', '午高峰有效在线时长',
                 '晚高峰有效在线时长', '有效完成单'],
                detail_row('2026-10-01', '111234567890123', '张三', 'A站', 5),
            ],
            '骑手信息表': [
                ['骑手ID', '姓名', '手机号', '身份证'],
                ['111234567890123', '张三', '13800000000', '110101199001010011'],
            ],
        })
        target = generate_abnormal_followup(
            *sources, '三亚', '2026-10', self.root / 'out', stamp=dt.date(2026, 10, 23))
        book = load_workbook(target, data_only=False)
        try:
            main = book['10月异常骑手跟进表']
            cell = main.cell(4, 3)
            self.assertIs(type(cell.value), int)
            self.assertEqual(cell.value, 111234567890123)
            self.assertEqual(cell.number_format, '0')
            self.assertEqual([main.cell(4, column).value for column in (1, 2, 4, 5)],
                             ['三亚', 'A站', '张三', '110101199001010011'])
            self.assertEqual([main.cell(4, column).value for column in range(12, 15)],
                             [1, 5, dt.datetime(2026, 10, 1)])
            sheet = book['10月骑手绑定情况']
            self.assertEqual(sheet.cell(1, 1).fill.fgColor.rgb, 'FFFBE5D6')
        finally:
            book.close()

    def test_main_data_rows_fully_bordered_and_header_keeps_non_empty_only(self):
        target = generate_abnormal_followup(
            *self.sources(), '三亚', '2026-10', self.root / 'out', stamp=dt.date(2026, 10, 23))
        book = load_workbook(target, data_only=False)
        try:
            main = book['10月异常骑手跟进表']
            # 数据行（含空单元格）统一细实线边框
            for row in range(4, main.max_row + 1):
                for column in range(1, main.max_column + 1):
                    cell = main.cell(row, column)
                    self.assertTrue(has_thin_border(cell), cell.coordinate)
            for column in range(1, main.max_column + 1):
                cell = main.cell(3, column)
                self.assertTrue(has_thin_border(cell), cell.coordinate)
            # 分表不受主表边框规则影响
            self.assertTrue(has_no_border(book['10月骑手详情表'].cell(2, 1)))
        finally:
            book.close()

    def test_abnormal_flag_status_values_and_three_day_boundary(self):
        sources = self.sources()
        write_book(sources[0], {
            '10月骑手绑定情况': [
                ['城市', '团队名称', '骑手ID', '骑手姓名', '骑手身份证', '发薪平台绑定', '绑定情况'],
                ['三亚', 'A站', 'R001', '张三', '110101199001010011', '已绑定', '已绑定'],
                ['三亚', 'A站', 'R002', '李四', '110101199002020022', '已绑定', '已绑定'],
                ['三亚', 'A站', 'R003', '王五', '110101199003030033', '已绑定', '已绑定'],
                ['三亚', 'A站', 'R004', '赵六', '110101199004040044', '已绑定', '已绑定'],
            ],
            '骑手详情表': [
                ['日期', '骑手ID', '骑手姓名', '骑手手机号', '团队ID', '团队名称',
                 '所属管理分组', '骑手等级', '最新入职时间', '最新离职时间', '在职状态',
                 '入职时长', '活跃天数', '有效在线时长', '午高峰有效在线时长',
                 '晚高峰有效在线时长', '有效完成单'],
                detail_row('2026-10-01', 'R001', '张三', 'A站', 5),
                detail_row('2026-10-02', 'R002', '李四', 'A站', 1),
                detail_row('2026-10-04', 'R003', '王五', 'A站', 2),
                detail_row('2026-10-04', 'R004', '赵六', 'A站', 2),
            ],
            '骑手信息表': [
                ['骑手ID', '姓名', '手机号', '身份证'],
                ['R001', '张三', '13800000000', '110101199001010011'],
                ['R002', '李四', '13900000000', '110101199002020022'],
                ['R003', '王五', '13700000000', '110101199003030033'],
                ['R004', '赵六', '13600000000', '110101199004040044'],
            ],
        })
        write_book(sources[1], {'骑手薪资文件': [
            ['账单期间不可编辑的提示'], ['账单基础信息'], ['方案基本信息'],
            UB_HEADERS,
            ub_row('B1', 'R001', '张三', 'A站', '方案A', '扣款A'),
            ub_row('B2', 'R002', '李四', 'A站', '方案B', '扣款B'),
            ub_row('B3', 'R003', '王五', 'A站', '方案C', '扣款C'),
            ub_row('B4', 'R004', '赵六', 'A站', '方案D', '扣款D'),
            # 同站点同骑手第二份账单缺扣款方案：任一缺方案即判否
            ub_row('B5', 'R002', '李四', 'A站', '方案B2', ''),
        ]})
        write_book(sources[3], {'骑手档案': [
            ['姓名', '城市', '项目', '站点', '骑手ID', '身份证号', '合作类型', '当前生效兼职价格',
             '合作日期', '推荐人身份证号', '三方公司/推荐人', '招聘来源', '状态', '是否寒暑假工', '备注'],
            ['张三', '三亚', '饿了么', '三亚站', 'R001', '110101199001010011', '全职', 8.5,
             '2026-01-01', None, None, '骑手内推', '合作', '否', ''],
            ['李四', '三亚', '饿了么', '三亚站', 'R002', '110101199002020022', '全职', 8.5,
             '2026-01-01', None, None, '骑手内推', '预解除', '否', ''],
            ['王五', '三亚', 'U+B', '三亚站', 'R003', '110101199003030033', '全职', 8.5,
             '2026-01-01', None, None, '骑手内推', '解除合作', '否', ''],
            ['赵六', '三亚', '淘鲜达', '三亚站', 'R004', '110101199004040044', '全职', 8.5,
             '2026-01-01', None, None, '骑手内推', '正常', '否', ''],
        ]})
        target = generate_abnormal_followup(
            *sources, '三亚', '2026-10', self.root / 'out', stamp=dt.date(2026, 10, 23))
        book = load_workbook(target, data_only=False)
        try:
            main = book['10月异常骑手跟进表']
            self.assertEqual([main.cell(row, 7).value for row in range(4, 8)],
                             ['合作', '预解除', '解除合作', '正常'])
            self.assertEqual([main.cell(row, 15).value for row in range(4, 8)],
                             ['是', '是', '是', '否'])
            self.assertEqual([main.cell(row, 16).value or None for row in range(4, 8)],
                             ['3天以上未出勤', '状态预解除；扣款方案未绑定', '状态解除合作', None])
            self.assertEqual([main.cell(row, 24).value for row in range(4, 8)], ['是'] * 4)
            self.assertEqual([main.cell(row, 25).value for row in range(4, 8)],
                             ['是', '否', '是', '是'])
        finally:
            book.close()

    def test_multi_city_summary_name_and_appended_rows_are_centered(self):
        city_file = generate_abnormal_followup(
            *self.sources(), '三亚', '2026-10', self.root / 'out', stamp=dt.date(2026, 10, 23))
        first = self.root / '三亚10月异常骑手跟进明细表1023.xlsx'
        second = self.root / '泉州10月异常骑手跟进明细表1023.xlsx'
        shutil.copy2(city_file, first)
        shutil.copy2(city_file, second)
        # 第二份成品的城市列改为泉州，用于验证汇总分析表按城市分组
        borrowed = load_workbook(second)
        try:
            sheet = borrowed['10月异常骑手跟进表']
            for row in range(4, sheet.max_row + 1):
                sheet.cell(row, 1, '泉州')
            borrowed.save(second)
        finally:
            borrowed.close()
        files = [{'city': city, 'dataset': 'abnormal_followup', 'start': '2026-10-01', 'end': '2026-10-31',
                  'relative_path': path.name}
                 for city, path in (('三亚', first), ('泉州', second))]
        items = [{**value, 'status': 'success'} for value in files]
        config = {'datasets': ['abnormal_followup'], 'cities': ['三亚', '泉州'],
                  'archive_created_at': '2026-10-23T10:00:00+08:00'}
        summaries = build_followup_summaries(self.root, config, files, items, threading.Event())
        self.assertEqual([value['name'] for value in summaries],
                         ['多城市汇总10月异常骑手跟进明细表1023.xlsx'])

        book = load_workbook(self.root / summaries[0]['name'], data_only=False)
        try:
            sheet = book['10月风神薪资方案绑定']
            self.assertEqual(sheet.cell(1, 1).value, '账单ID')
            self.assertEqual([cell.value for cell in sheet[1]], UB_HEADERS)
            self.assertEqual(sheet.max_column, 18)
            self.assertEqual(sheet.cell(9, 3).value, '周九')
            self.assertTrue(all(sheet.cell(row, 1).alignment.horizontal == 'center'
                                for row in range(2, sheet.max_row + 1)))
            self.assertEqual(sheet.column_dimensions['A'].alignment.horizontal, 'center')
            main = book['10月异常骑手跟进表']
            for name, frozen in (('10月异常骑手跟进表', 'A4'), ('10月风神薪资方案绑定', 'A2'),
                                 ('10月骑手绑定情况', 'A2'), ('10月骑手详情表', 'A2'),
                                 ('10月骑手信息表', 'A2'), ('10月蓝橙价格档案', 'A2'),
                                 ('10月蓝橙员工档案', 'A2'), ('10月电动车住宿租用', 'A2')):
                self.assertEqual(book[name].freeze_panes, frozen, name)
            self.assertEqual(main.cell(9, 14).value, dt.datetime(2026, 10, 7))
            self.assertEqual(main.cell(9, 14).number_format, 'yyyy-mm-dd')
            self.assertEqual(main.cell(10, 14).value, dt.datetime(2026, 10, 3))
            self.assertTrue(has_thin_border(main.cell(10, 14)))
            self.assertEqual([main.cell(row, 15).value for row in (9, 10, 14, 15)],
                             ['否', '是', '否', '否'])
            price_sheet = book['10月蓝橙价格档案']
            self.assertEqual(price_sheet.max_row, 7)
            self.assertEqual([price_sheet.cell(row, 4).value for row in range(2, 8)],
                             ['张三', '钱七', '孙八', '张三', '钱七', '孙八'])

            archive = book['10月蓝橙员工档案']
            self.assertEqual(archive.max_row, 11)
            self.assertEqual([archive.cell(row, 1).value for row in range(2, 12)],
                             ['U+B', 'U+B', '饿了么', '饿了么', '饿了么', '饿了么',
                              '淘鲜达', '淘鲜达', '淘鲜达', '淘鲜达'])
            self.assertEqual([archive.cell(row, 5).value for row in range(2, 12)],
                             ['李四', '李四', '张三', '周九', '张三', '周九',
                              '孙八', '李四', '孙八', '李四'])
            self.assertTrue(all(archive.cell(row, 1).alignment.horizontal == 'center'
                                for row in range(2, 12)))

            # 汇总分析表：拼音升序城市块 + 汇总行 + 站点明细（无末尾合计），
            # 按「站点+骑手ID」分行计数（李四跨站计两次）
            analysis = book['分析表']
            self.assertEqual(analysis.max_row, 15)
            self.assertEqual([analysis.cell(row, 1).value for row in range(3, 6)],
                             ['泉州', '三亚', '汇总'])
            self.assertEqual([analysis.cell(3, column).value for column in range(3, 16)],
                             [5, 3, 2, 0, 0.6, 4, 1, 2, None, 2, 0, 2, 0])
            self.assertEqual([analysis.cell(4, column).value for column in range(3, 16)],
                             [5, 3, 2, 0, 0.6, 4, 1, 2, None, 2, 0, 2, 0])
            self.assertEqual([analysis.cell(5, column).value for column in range(3, 16)],
                             [10, 6, 4, 0, 0.6, 8, 2, 4, None, 4, 0, 4, 0])
            self.assertIsNone(analysis.cell(5, 2).value)
            # 城市块 B 列按截图重复填城市名；站点明细按城市+站点拼音排序
            self.assertEqual([analysis.cell(row, 2).value for row in (3, 4)],
                             ['泉州', '三亚'])
            self.assertEqual([analysis.cell(row, 1).value for row in range(6, 16)],
                             ['泉州'] * 5 + ['三亚'] * 5)
            self.assertEqual([analysis.cell(row, 2).value for row in range(6, 16)],
                             ['三亚二组（测试）', '三亚三组', '三亚四组', '三亚五组',
                              '三亚一组'] * 2)
            self.assertEqual(analysis.freeze_panes, 'A3')

            # 汇总说明按合并后的主表重新统计，标题城市为多城市汇总
            guide = book['说明']
            self.assertEqual(guide['A1'].value, '多城市汇总 · 10月异常骑手跟进说明')
            self.assertEqual(guide.cell(4, 2).value, '多城市汇总')
            self.assertEqual([guide.cell(row, 2).value for row in range(8, 12)],
                             ['10', '8（在跑单 6）', '8 / 2', '0'])
        finally:
            book.close()


if __name__ == '__main__':
    unittest.main()
