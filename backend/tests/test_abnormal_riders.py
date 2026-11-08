"""异常骑手整理（生成表）组装器测试：口径对齐原手动上传模块。"""
import datetime as dt
from pathlib import Path
import sys
import tempfile
import threading
import unittest

from openpyxl import Workbook, load_workbook

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from abnormal_riders import (generate_abnormal_riders, match_city, normalize_date,
                             ABNORMAL_FIELDS, ARCHIVE_FIELDS, SUMMARY_FIELDS)
from fengshen_bill import BillCollectionError


def write_book(path, sheets):
    book = Workbook()
    book.remove(book.active)
    for title, rows in sheets.items():
        sheet = book.create_sheet(title)
        for row in rows:
            sheet.append(list(row))
    book.save(path)
    book.close()


def sheet_rows(path, title):
    book = load_workbook(path, data_only=True)
    try:
        rows = list(book[title].iter_rows(values_only=True))
    finally:
        book.close()
    header, data = list(rows[0]), [dict(zip(rows[0], row)) for row in rows[1:]]
    return header, data


ARCHIVE_HEADER = ['项目', '城市', '站点', '骑手ID', '姓名', '身份证号', '合作类型',
                  '当前生效兼职价格', '合作日期', '推荐人身份证号', '三方公司/推荐人',
                  '招聘来源', '状态', '是否寒暑假工']


def archive_row(name, city, station, rider_id, id_card, status, join_date='2025-03-01'):
    return ['U+B', city, station, rider_id, name, id_card, '全职', 8.5, join_date,
            '', '', '骑手内推', status, '否']


class AbnormalRidersTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=Path(__file__).parent)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.logs = []

    def sources(self):
        serial = (dt.date(2025, 1, 1) - dt.date(1899, 12, 30)).days  # Excel 序列 45658
        batch = self.root / 'batch_quit.xlsx'
        write_book(batch, {
            '批量离职': [
                ['城市名称', '站点名称', '骑手ID', '骑手姓名', '身份证', '解除合作申请日', '解除合作类别', '状态'],
                ['保定', '保定一站', 'B001', '张三', '110101199001010011', serial, '劝退优化', '已解除'],
                ['保定', '保定一站', 'B001', '张三', '110101199001010011', '2026/7/1', '自离', '已解除'],
                ['北京', '北京二站', 'B004', '赵六', '110101199004040044', '2026-07-02', '合同到期', '已解除'],
            ],
            '全量下载说明': [['文件性质', '系统合并；不是平台单次导出的原始表']],
        })
        quit_file = self.root / 'rider_quit.xlsx'
        write_book(quit_file, {
            '骑手离职': [
                ['城市名称', '站点', '风神骑手ID', '骑手姓名', '身份证', '离职申请日', '离职类型', '状态'],
                ['保定', '保定二站', 'B002', '李四', '110101199002020022', '2026-08-03', '正常离职', '已离职'],
            ],
        })
        report = self.root / 'rider_report.xlsx'
        write_book(report, {
            '离职报备': [
                ['城市名称', '站点名称', '风神骑手ID', '骑手姓名', '身份证', '解除合作申请日', '解除合作类别', '状态'],
                ['保定', '保定三站', 'B003', '王五', '110101199003030033', dt.date(2026, 9, 9), '辞退', '已解除'],
            ],
        })
        leave = self.root / 'rider_leave.xlsx'
        write_book(leave, {
            '骑手请假': [
                ['城市', '站点', '风神骑手ID', '姓名', '身份证号', '请假结束时间', '类型', '审核状态'],
                ['保定', '保定一站', 'B001', '张三', '110101199001010011', '2026-09-18', '病假', '已通过'],
            ],
        })
        archive = self.root / 'archive.xlsx'
        write_book(archive, {
            '骑手档案': [
                ARCHIVE_HEADER,
                archive_row('张三', '保定', '保定一站', 'B001', '110101199001010011', '合作'),
                archive_row('李四', '保定', '保定二站', 'B002', '110101199002020022', '解除合作'),
                archive_row('王五', '保定', '保定三站', 'B003', '110101199003030033', '跑单未入职'),
                archive_row('赵六', '北京', '北京二站', 'B004', '110101199004040044', '预解除', '2026-01-05'),
            ],
        })
        return batch, quit_file, report, leave, archive

    def generate(self, **options):
        batch, quit_file, report, leave, archive = self.sources()
        return generate_abnormal_riders(batch, quit_file, report, leave, archive,
                                        self.root / 'out', log=self.logs.append, **options)

    def test_station_snapshot_and_conflicting_manual_city_are_traceable(self):
        from unittest.mock import patch
        directory={'stations':[{'id':'0001','city_id':'010','name':'保定一站','city':'后台城市'}]}
        with patch('abnormal_riders._team_city_catalog',return_value={'保定一站':'人工城市'}):
            target=self.generate(station_directory=directory)
        _,stations=sheet_rows(target,'站点城市目录')
        self.assertEqual(stations[0]['站点编号'],'0001')
        _,issues=sheet_rows(target,'城市归属待核对')
        self.assertTrue(any(row['人工配置城市']=='人工城市' for row in issues))

    def test_abnormal_summary_orders_types_and_backfills_archive_fields(self):
        target = self.generate()
        header, rows = sheet_rows(target, '异常汇总')
        self.assertEqual(list(header), list(ABNORMAL_FIELDS))
        self.assertEqual([row['类型'] for row in rows],
                         ['批量离职', '批量离职', '批量离职', '离职报备', '骑手离职', '骑手请假'])
        first = rows[0]
        self.assertEqual((first['城市名称'], first['站点'], first['风神骑手ID']), ('保定', '保定一站', 'B001'))
        self.assertEqual(first['离职申请日'], '2025-01-01')  # 数值序列正确换算
        self.assertEqual((first['合作日期'], first['合作状态']), ('2025-03-01', '合作'))
        self.assertEqual(first['备注'], '【合作】批量离职：2025-01-01已解除(劝退优化)')
        self.assertEqual(rows[3]['备注'], '【跑单未入职】离职报备：2026-09-09已解除(辞退)')
        self.assertEqual(rows[4]['备注'], '【解除合作】骑手离职：2026-08-03已离职(正常离职)')
        self.assertEqual(rows[5]['备注'], '【合作】骑手请假：2026-09-18病假(已通过)')
        book = load_workbook(target)
        try:
            self.assertEqual(book['异常汇总'].freeze_panes, 'A2')
            self.assertTrue(book['异常汇总']['A1'].font.bold)
        finally:
            book.close()

    def test_archive_sheet_moves_join_date_before_id_card(self):
        target = self.generate()
        header, rows = sheet_rows(target, '蓝橙骑手档案')
        self.assertEqual(list(header), list(ARCHIVE_FIELDS))
        self.assertEqual(header.index('合作日期') + 1, header.index('身份证号'))
        self.assertEqual([row['姓名'] for row in rows], ['张三', '李四', '王五', '赵六'])

    def test_summary_without_detail_joins_remarks_and_flags(self):
        target = self.generate()
        _, rows = sheet_rows(target, '汇总')
        by_rider = {row['骑手ID'] or row['骑手姓名']: row for row in rows}
        zhang = by_rider['B001']
        self.assertEqual(zhang['批量离职'], '【合作】批量离职：2025-01-01已解除(劝退优化)；'
                         '【合作】批量离职：2026-07-01已解除(自离)')
        self.assertEqual(zhang['骑手请假'], '【合作】骑手请假：2026-09-18病假(已通过)')
        self.assertEqual((zhang['合作状态'], zhang['是否解除跑单未入职'], zhang['是否跑单未入职']),
                         ('合作', '否', '否'))
        self.assertEqual((zhang['总单量'], zhang['活跃是否异常'], zhang['城市']), (0, '否', '保定'))
        self.assertEqual(by_rider['B003']['是否跑单未入职'], '是')  # 合作状态含「跑单未入职」
        self.assertEqual(by_rider['B004']['是否解除跑单未入职'], '否')  # 预解除视为未解除
        self.assertEqual(by_rider['B004']['城市'], '北京')

    def test_detail_and_info_sources_fill_orders_abnormal_and_run_no_entry(self):
        detail = self.root / 'detail.xlsx'
        write_book(detail, {
            '骑手数据明细': [
                ['日期', '骑手ID', '骑手姓名', '团队名称', '有效完成单'],
                ['2026-09-01', 'B001', '张三', '保定一站', 6],
                ['2026-09-02', 'B001', '张三', '保定二站', 10],
                ['2026-09-02', 'B001', '张三', '保定二站', 5],
                ['2026-09-03', 'B002', '李四', '保定二站', 5],
                ['2026-09-04', 'B099', '田十', '保定一站', 3],
            ],
        })
        info = self.root / 'info.xlsx'
        write_book(info, {'骑手信息': [['骑手ID', '姓名'], ['B099', '田十']]})
        target = self.generate(detail_file=detail, info_file=info)
        _, rows = sheet_rows(target, '汇总')
        by_rider = {row['骑手ID'] or row['骑手姓名']: row for row in rows}
        # 汇总由骑手数据明细驱动：跨站团队取单量最多站点，总单量为该站点合计
        zhang = by_rider['B001']
        self.assertEqual((zhang['团队名称'], zhang['总单量']), ('保定二站', 15))
        # B002 有骑手离职记录且有单量：活跃异常；B099 在骑手信息中：不算跑单未入职
        self.assertEqual(by_rider['B002']['活跃是否异常'], '是(离职仍有单量)')
        self.assertEqual(by_rider['B099']['是否跑单未入职'], '否')
        self.assertEqual(by_rider['B099']['活跃是否异常'], '否')

    def test_detail_without_info_still_flags_orders_without_registration(self):
        detail = self.root / 'detail.xlsx'
        write_book(detail, {
            '骑手数据明细': [
                ['日期', '骑手ID', '骑手姓名', '团队名称', '有效完成单'],
                ['2026-09-04', 'B099', '田十', '保定一站', 3],
            ],
        })
        target = self.generate(detail_file=detail)
        _, rows = sheet_rows(target, '汇总')
        by_rider = {row['骑手ID'] or row['骑手姓名']: row for row in rows}
        self.assertEqual(by_rider['B099']['是否跑单未入职'], '是')

    def test_batch_quit_falls_back_to_fixed_columns_when_headers_missing(self):
        # 表头不含「解除合作申请日/解除合作类别」时，按列 L(11)/N(13) 兜底取值
        header = ['序号', '城市名称', '站点名称', '骑手ID', '骑手姓名', '身份证', '备注1', '备注2',
                  '备注3', '备注4', '备注5', '申请日期列', '备注6', '类别列', '状态']
        row = ['1', '保定', '保定一站', 'B001', '张三', '110101199001010011', None, None, None,
               None, None, '2026-06-05', None, '劝退优化', '已解除']
        _, quit_file, report, leave, archive = self.sources()
        batch = self.root / 'batch_quit.xlsx'
        write_book(batch, {'批量离职': [header, row]})
        target = generate_abnormal_riders(batch, quit_file, report, leave, archive,
                                          self.root / 'out', log=self.logs.append)
        _, rows = sheet_rows(target, '异常汇总')
        first = [row for row in rows if row['类型'] == '批量离职'][0]
        self.assertEqual(first['离职申请日'], '2026-06-05')
        self.assertEqual(first['离职类型'], '劝退优化')
        self.assertEqual(first['审批状态'], '已解除')

    def test_cancelled_event_stops_generation(self):
        cancelled = threading.Event()
        cancelled.set()
        with self.assertRaises(BillCollectionError):
            self.generate(cancelled=cancelled)

    def test_match_city_prefers_exact_then_longest_substring(self):
        catalog = {'麻豆人-大润发保定店_新专送': '保定', '北京-高校清华站_新专送': '北京'}
        self.assertEqual(match_city('麻豆人-大润发保定店_新专送', catalog), '保定')
        self.assertEqual(match_city('北京-高校清华站_新专送', catalog), '北京')
        self.assertEqual(match_city('其他团队', catalog), '')
        self.assertEqual(match_city('未知名称', catalog), '')

    def test_normalize_date_handles_serial_string_and_text(self):
        self.assertEqual(normalize_date('45658'), '2025-01-01')
        self.assertEqual(normalize_date('2026/7/1'), '2026-07-01')
        self.assertEqual(normalize_date('2026-07-01 08:00:00'), '2026-07-01')
        self.assertEqual(normalize_date(dt.date(2026, 7, 1)), '2026-07-01')
        self.assertEqual(normalize_date(''), '')
        self.assertEqual(normalize_date('时间未知'), '时间未知')


if __name__ == '__main__':
    unittest.main()
