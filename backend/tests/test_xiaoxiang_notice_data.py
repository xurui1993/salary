"""通知附件合并导出（骑手订单明细 / 骑手出勤明细）单元测试。"""
from datetime import date, datetime
from io import BytesIO
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

from openpyxl import Workbook, load_workbook

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import download_archive as archive
import xiaoxiang_notice_data as notice_data
from xiaoxiang_notice_data import (ATTENDANCE_DATASET, ORDER_DATASET,
                                   LighthouseError, _DATASET_SPECS)


def list_response(total, records):
    body = Mock()
    body.status_code = 200
    body.headers = {'content-type': 'application/json'}
    body.json = lambda: {'code': 0, 'data': {'total': total, 'noticeRecordList': records}}
    return body


def detail_response(files):
    body = Mock()
    body.status_code = 200
    body.headers = {'content-type': 'application/json'}
    body.json = lambda: {'code': 0, 'data': {'recordDetail': {'fileInfoList': files}}}
    return body


def notice(nid, title, publish_ms):
    return {'id': nid, 'title': title, 'noticeTypeStr': '数据分发', 'publishTime': publish_ms}


# 2026-10-31 08:00 北京时间
OCT31_MS = 1793481600000
NOV2_MS = 1793654400000

ORDER_HEADER = ['合作商名称', '站点名称', '站点id', '业务日期', '骑手id', '骑手名称',
                '合作商id', '配送方', '三方结算公司id', '城市id', '城市名称', '配送单量']


def order_row(site, biz_date, rider, name, qty):
    return ['深圳市麻豆人配送服务有限公司', site, '10001735', biz_date, str(rider), name,
            '106', '商', '106', '7', '深圳', str(qty)]


ATTEND_HEADER = ['合作商名称', '站点名称', '站点id', '运力方', 'xxx.dt', 'xxx.city_name',
                 'xxx.poi_id', 'xxx.rider_id', 'xxx.rider_name', 'xxx.是否有效出勤',
                 '出勤小时数不含休息', 'bbb.全天工作时长', '有效运力折算系数']


def attend_row(dt, rider, name, hours):
    return ['深圳市麻豆人配送服务有限公司', '小象超市-测试站', '1720', '麻豆人', dt, '深圳',
            '10001462', str(rider), name, '是', hours, '12.2408333333', '1']


def write_workbook(path, header, rows):
    book = Workbook()
    sheet = book.active
    sheet.append(header)
    for row in rows:
        sheet.append(row)
    book.save(path)


class DateParserTests(unittest.TestCase):
    def test_iso_date_accepts_text_and_datetime(self):
        self.assertEqual(notice_data._parse_iso_date('2026-10-30'), date(2026, 10, 30))
        self.assertEqual(notice_data._parse_iso_date('2026/10/30'), date(2026, 10, 30))
        self.assertEqual(notice_data._parse_iso_date('2026/10/1'), date(2026, 10, 1))
        self.assertEqual(notice_data._parse_iso_date(datetime(2026, 10, 30, 8, 0)),
                         date(2026, 10, 30))
        self.assertIsNone(notice_data._parse_iso_date('2026-13-01'))
        self.assertIsNone(notice_data._parse_iso_date('2026/13/01'))
        self.assertIsNone(notice_data._parse_iso_date('2026/10/32'))
        self.assertIsNone(notice_data._parse_iso_date(None))

    def test_compact_date_accepts_text(self):
        self.assertEqual(notice_data._parse_compact_date('20261030'), date(2026, 10, 30))
        self.assertIsNone(notice_data._parse_compact_date('2026-10-30'))
        self.assertIsNone(notice_data._parse_compact_date('20261032'))
        self.assertIsNone(notice_data._parse_compact_date('NULL'))

    def test_numeric_cell_keeps_null_and_converts_numbers(self):
        self.assertEqual(notice_data._numeric_cell('636728'), 636728)
        self.assertEqual(notice_data._numeric_cell('12.2408333333'), 12.2408333333)
        self.assertEqual(notice_data._numeric_cell('NULL'), 'NULL')
        self.assertEqual(notice_data._numeric_cell('是'), '是')
        self.assertEqual(notice_data._numeric_cell('不考核'), '不考核')


class AttachmentSelectionTests(unittest.TestCase):
    def test_order_spec_selects_commercial_and_excludes_datanet(self):
        spec = _DATASET_SPECS[ORDER_DATASET]
        files = [{'fileName': 'x_10.26~11.1【商配送】骑手订单明细（结算口径）-1.xlsxsu_1_106.xlsx',
                  'fileUrl': 'https://s3plus.example/a.xlsx'},
                 {'fileName': 'x_10.26~11.1【大网配送】骑手订单明细（结算口径）.xlsxsu_2_106.xlsx',
                  'fileUrl': 'https://s3plus.example/b.xlsx'},
                 {'fileName': '其他附件.xlsx', 'fileUrl': 'https://s3plus.example/c.xlsx'}]
        picked = notice_data.select_notice_attachments({'fileInfoList': files}, spec)
        self.assertEqual([item['fileName'] for item in picked],
                         ['x_10.26~11.1【商配送】骑手订单明细（结算口径）-1.xlsxsu_1_106.xlsx'])

    def test_attendance_spec_selects_attendance_only(self):
        spec = _DATASET_SPECS[ATTENDANCE_DATASET]
        files = [{'fileName': '91941_骑手出勤明细_1748662550_0_20261101.xlsxsu_17060_106.xlsx',
                  'fileUrl': 'https://s3plus.example/a.xlsx'},
                 {'fileName': '91941_骑手疑似作弊明细_1_0_20261101.xlsxsu_1_106.xlsx',
                  'fileUrl': 'https://s3plus.example/b.xlsx'}]
        picked = notice_data.select_notice_attachments({'fileInfoList': files}, spec)
        self.assertEqual(len(picked), 1)
        self.assertIn('骑手出勤明细_', picked[0]['fileName'])

    def test_missing_attachments_return_empty(self):
        self.assertEqual(notice_data.select_notice_attachments({'fileInfoList': []},
                                                               _DATASET_SPECS[ATTENDANCE_DATASET]), [])


class NoticeListTests(unittest.TestCase):
    def spec(self, dataset):
        return _DATASET_SPECS[dataset]

    def session_with(self, responses):
        session = Mock()
        session.post = Mock(side_effect=responses)
        return session

    def test_filters_by_title_and_publish_floor(self):
        records = [notice(1, '10.26-11.1骑手订单明细', NOV2_MS),
                   notice(2, '10.19-10.25骑手订单明细', NOV2_MS - 7 * 86400 * 1000),
                   notice(3, '深圳2026年11月合作商站点考核方案', NOV2_MS),
                   notice(4, '【重要】10月限流罚款明细', NOV2_MS)]
        session = self.session_with([list_response(4, records)])
        matched = notice_data.list_keyword_notices(session, self.spec(ORDER_DATASET),
                                                   date(2026, 10, 26))
        self.assertEqual([item['id'] for item in matched], [2, 1])
        payload = session.post.call_args.kwargs['json']
        self.assertEqual(payload['paging'], {'offset': 0, 'limit': notice_data.LIST_PAGE_LIMIT})

    def test_paging_walks_until_total(self):
        first = [notice(i, '10.26-11.1骑手订单明细', NOV2_MS) for i in range(100)]
        second = [notice(200, '10.26-11.1骑手订单明细', NOV2_MS)]
        session = self.session_with([list_response(101, first), list_response(101, second)])
        matched = notice_data.list_keyword_notices(session, self.spec(ORDER_DATASET),
                                                   date(2026, 10, 26))
        self.assertEqual(len(matched), 101)
        self.assertEqual(session.post.call_count, 2)

    def test_publish_guard_excludes_stale_notices(self):
        records = [notice(1, '10.19-10.25骑手订单明细', NOV2_MS - 30 * 86400 * 1000)]
        session = self.session_with([list_response(1, records)])
        matched = notice_data.list_keyword_notices(session, self.spec(ORDER_DATASET),
                                                   date(2026, 10, 26))
        self.assertEqual(matched, [])

    def test_invalid_structure_rejected(self):
        session = self.session_with([list_response(1, 'not-a-list')])
        with self.assertRaises(LighthouseError):
            notice_data.list_keyword_notices(session, self.spec(ORDER_DATASET),
                                             date(2026, 10, 26))


class CollectTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.downloads = {}

        def fake_download(url, target):
            header, rows = self.downloads[url]
            write_workbook(target, header, rows)
            return target

        patcher = patch.object(notice_data, '_download_attachment', side_effect=fake_download)
        patcher.start()
        self.addCleanup(patcher.stop)

    def session_with(self, responses):
        session = Mock()
        session.post = Mock(side_effect=responses)
        return session

    def register_order(self, url, rows):
        self.downloads[url] = (ORDER_HEADER, rows)

    def register_attendance(self, url, rows):
        self.downloads[url] = (ATTEND_HEADER, rows)

    def test_merge_filters_dates_and_dedups_keeping_latest(self):
        self.register_order('s3://old', [order_row('A站', '2026-10-26', 1, '甲', 10),
                                         order_row('A站', '2026-10-20', 2, '乙', 5)])
        self.register_order('s3://new', [order_row('A站', '2026-10-26', 1, '甲', 12)])
        session = self.session_with([
            list_response(2, [notice(1, '10.19-10.25骑手订单明细', NOV2_MS - 7 * 86400 * 1000),
                              notice(2, '10.26-11.1骑手订单明细', NOV2_MS)]),
            detail_response([{'fileName': 'a【商配送】骑手订单明细-1.xlsx', 'fileUrl': 's3://old'}]),
            detail_response([{'fileName': 'b【商配送】骑手订单明细-2.xlsx', 'fileUrl': 's3://new'}]),
        ])
        header, records = notice_data.collect_notice_rows(
            session, _DATASET_SPECS[ORDER_DATASET], date(2026, 10, 26), date(2026, 11, 1))
        self.assertEqual(header, ORDER_HEADER)
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0][header.index('配送单量')], '12')

    def test_missing_attendance_notice_is_skipped(self):
        self.register_attendance('s3://a', [attend_row('20261030', 1, '甲', '13')])
        session = self.session_with([
            list_response(2, [notice(1, '10.30合作商数据下发', NOV2_MS),
                              notice(2, '10.31合作商数据下发', NOV2_MS)]),
            detail_response([{'fileName': '91941_带盔明细数据.xlsx', 'fileUrl': 's3://none'}]),
            detail_response([{'fileName': '91941_骑手出勤明细_1_0_20261031.xlsx',
                              'fileUrl': 's3://a'}]),
        ])
        header, records = notice_data.collect_notice_rows(
            session, _DATASET_SPECS[ATTENDANCE_DATASET], date(2026, 10, 30), date(2026, 10, 30))
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0][header.index('xxx.rider_id')], '1')

    def test_slash_format_dates_are_merged(self):
        self.register_order('s3://a', [order_row('A站', '2026/10/26', 1, '甲', 10)])
        session = self.session_with([
            list_response(1, [notice(1, '10.26-11.1骑手订单明细', NOV2_MS)]),
            detail_response([{'fileName': 'a【商配送】骑手订单明细-1.xlsx', 'fileUrl': 's3://a'}]),
        ])
        header, records = notice_data.collect_notice_rows(
            session, _DATASET_SPECS[ORDER_DATASET], date(2026, 10, 26), date(2026, 11, 1))
        self.assertEqual(len(records), 1)

    def test_interior_date_gap_rejects_delivery(self):
        self.register_order('s3://a', [order_row('A站', '2026-10-26', 1, '甲', 10),
                                       order_row('A站', '2026-11-01', 2, '乙', 5)])
        session = self.session_with([
            list_response(1, [notice(1, '10.26-11.1骑手订单明细', NOV2_MS)]),
            detail_response([{'fileName': 'a【商配送】骑手订单明细-1.xlsx', 'fileUrl': 's3://a'}]),
        ])
        with self.assertRaises(LighthouseError) as caught:
            notice_data.collect_notice_rows(
                session, _DATASET_SPECS[ORDER_DATASET], date(2026, 10, 26), date(2026, 11, 1))
        self.assertIn('2026-10-27', str(caught.exception))

    def test_trailing_missing_dates_are_tolerated(self):
        self.register_order('s3://a', [order_row('A站', '2026-10-26', 1, '甲', 10)])
        session = self.session_with([
            list_response(1, [notice(1, '10.26-11.1骑手订单明细', NOV2_MS)]),
            detail_response([{'fileName': 'a【商配送】骑手订单明细-1.xlsx', 'fileUrl': 's3://a'}]),
        ])
        logs = []
        header, records = notice_data.collect_notice_rows(
            session, _DATASET_SPECS[ORDER_DATASET], date(2026, 10, 26), date(2026, 11, 1),
            log=logs.append)
        self.assertEqual(len(records), 1)
        self.assertTrue(any('暂无数据' in line for line in logs))

    def test_no_rows_in_range_raises(self):
        self.register_order('s3://a', [order_row('A站', '2026-09-01', 1, '甲', 10)])
        session = self.session_with([
            list_response(1, [notice(1, '10.26-11.1骑手订单明细', NOV2_MS)]),
            detail_response([{'fileName': 'a【商配送】骑手订单明细-1.xlsx', 'fileUrl': 's3://a'}]),
        ])
        with self.assertRaises(LighthouseError):
            notice_data.collect_notice_rows(
                session, _DATASET_SPECS[ORDER_DATASET], date(2026, 10, 26), date(2026, 11, 1))

    def test_header_mismatch_rejected(self):
        self.register_order('s3://a', [order_row('A站', '2026-10-26', 1, '甲', 10)])
        bad = ORDER_HEADER[:-1]
        self.downloads['s3://b'] = (bad, [order_row('A站', '2026-10-27', 2, '乙', 10)[:-1]])
        session = self.session_with([
            list_response(2, [notice(1, '10.26-11.1骑手订单明细', NOV2_MS),
                              notice(2, '10.26-11.1骑手订单明细', NOV2_MS - 1000)]),
            detail_response([{'fileName': 'a【商配送】-1.xlsx', 'fileUrl': 's3://a'}]),
            detail_response([{'fileName': 'a【商配送】-2.xlsx', 'fileUrl': 's3://b'}]),
        ])
        with self.assertRaises(LighthouseError):
            notice_data.collect_notice_rows(
                session, _DATASET_SPECS[ORDER_DATASET], date(2026, 10, 26), date(2026, 11, 1))


class WorkbookTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)

    def test_write_applies_standard_style_and_types(self):
        spec = _DATASET_SPECS[ORDER_DATASET]
        rows = [order_row('A站', '2026-10-26', 636728, '甲', 46)]
        target = Path(self.temp.name) / 'out.xlsx'
        info = notice_data.write_notice_workbook(ORDER_HEADER, rows, spec, target)
        self.assertEqual(info, {'rows': 1, 'columns': len(ORDER_HEADER)})
        book = load_workbook(target)
        sheet = book[spec['label']]
        self.assertEqual(sheet.freeze_panes, 'A2')
        self.assertEqual(sheet['A1'].fill.start_color.rgb, 'FFFDEADA')
        self.assertEqual(sheet['A1'].font.name, '微软雅黑')
        self.assertEqual(sheet['D2'].value, '2026-10-26')
        self.assertEqual(sheet['E2'].value, 636728)
        self.assertEqual(sheet['L2'].value, 46)
        self.assertEqual(sheet['B2'].value, 'A站')
        book.close()

    def test_slash_date_is_normalized_to_iso(self):
        spec = _DATASET_SPECS[ORDER_DATASET]
        rows = [order_row('A站', '2026/10/12', 636728, '甲', 3)]
        target = Path(self.temp.name) / 'slash.xlsx'
        notice_data.write_notice_workbook(ORDER_HEADER, rows, spec, target)
        book = load_workbook(target)
        sheet = book[spec['label']]
        self.assertEqual(sheet['D2'].value, '2026-10-12')
        book.close()

    def test_attendance_null_and_decimal_survive_conversion(self):
        spec = _DATASET_SPECS[ATTENDANCE_DATASET]
        rows = [attend_row('20261030', 799921, '江宇权', 'NULL')]
        target = Path(self.temp.name) / 'attend.xlsx'
        notice_data.write_notice_workbook(ATTEND_HEADER, rows, spec, target)
        book = load_workbook(target)
        sheet = book[spec['label']]
        self.assertEqual(sheet['J2'].value, '是')
        self.assertEqual(sheet['K2'].value, 'NULL')
        self.assertEqual(sheet['L2'].value, 12.2408333333)
        self.assertEqual(sheet['M2'].value, 1)
        book.close()


class ArchiveNameTests(unittest.TestCase):
    def test_range_workbook_naming(self):
        stamp = date(2026, 11, 2)
        self.assertEqual(
            archive.archive_filename('全部城市', 'rider_order_detail', '2026-10-26', '2026-11-01',
                                     '.xlsx', stamp=stamp),
            '骑手订单明细_2026-10-26_2026-11-01.xlsx')
        self.assertEqual(
            archive.archive_filename('全部城市', 'xiaoxiang_attendance_detail', '2026-10-25',
                                     '2026-10-31', '.xlsx', stamp=stamp),
            '骑手出勤明细_2026-10-25_2026-10-31.xlsx')
        self.assertEqual(
            archive.archive_filename('全部城市', 'rider_order_detail', '2026-10-26', '2026-10-26',
                                     '.xlsx', stamp=stamp),
            '骑手订单明细_2026-10-26.xlsx')

    def test_labels_and_group(self):
        self.assertEqual(archive.LABELS['rider_order_detail'], '骑手订单明细')
        self.assertEqual(archive.LABELS['xiaoxiang_attendance_detail'], '骑手出勤明细')
        self.assertIn('灯塔', archive.task_archive_label(['rider_order_detail']))
        self.assertEqual(archive.artifact_scope({'dataset': 'rider_order_detail',
                                                 'start': '2026-10-26', 'end': '2026-11-01'}),
                         ('2026-10-26', '2026-11-01'))


if __name__ == '__main__':
    unittest.main()
