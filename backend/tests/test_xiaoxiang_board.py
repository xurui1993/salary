from datetime import date, timedelta
from io import BytesIO
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

from openpyxl import load_workbook

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import xiaoxiang_board as board
import xiaoxiang_lighthouse as lh
from download_service import ValidationError, validate_request
from fengshen_bill import BillCollectionError
from xiaoxiang_lighthouse import LighthouseError, SessionExpired


METAS = [
    {'fieldCode': 'rider_id', 'name': '骑手ID'},
    {'fieldCode': 'rider_name', 'name': '骑手名称'},
    {'fieldCode': 'site_name', 'name': '所属站点'},
    {'fieldCode': 'transport_push_order_cnt', 'name': '配送单量'},
    {'fieldCode': 'supplier_transport_ontime_rate', 'name': '准时率'},
]
ROWS = [
    {'rider_id': '842952', 'rider_name': '张三', 'site_name': '荣盛站',
     'transport_push_order_cnt': '50', 'supplier_transport_ontime_rate': '99.20%'},
    {'rider_id': '842953', 'rider_name': '李四', 'site_name': '荣盛站',
     'transport_push_order_cnt': '48', 'supplier_transport_ontime_rate': '98.75%'},
]
COMPLETION_METAS = [
    {'fieldCode': 'rider_id', 'name': '骑手ID'},
    {'fieldCode': 'transport_end_order_cnt', 'name': '配送完成单量'},
]


def api_response(body, status=200, url='https://zl.meituan.com/api/m/mustang/one/app/query'):
    response = Mock()
    response.status_code = status
    response.url = url
    response.headers = {'content-type': 'application/json'}
    response.json = lambda: body
    return response


class QueryBodyTests(unittest.TestCase):
    def test_single_day_structure(self):
        body = board.query_body(date(2026, 10, 25))
        query = body['queries'][0]
        self.assertEqual(body['applicationId'], board.APPLICATION_ID)
        self.assertEqual(query['dateDim']['dateKey'], ['20261025', '20261025'])
        self.assertEqual(query['dateDim']['dateType'], 'DAY')
        self.assertEqual(query['pageInfo'], {})
        self.assertEqual(query['filters'][0]['ruleValue'], '106')
        self.assertEqual(len(query['measures']), 14)
        self.assertEqual(body['extra']['moduleId'], board.MODULE_ID)

    def test_supplier_override(self):
        body = board.query_body(date(2026, 10, 25), supplier_id=207)
        self.assertEqual(body['queries'][0]['filters'][0]['ruleValue'], '207')


class QueryTests(unittest.TestCase):
    def session_with(self, response):
        session = Mock()
        session.post = Mock(return_value=response)
        return session

    def test_success_returns_rows_and_metas(self):
        body = {'code': 0, 'msg': '成功', 'data': {'data': ROWS, 'metas': METAS, 'total': 2}}
        result = board.query_rider_daily(self.session_with(api_response(body)), date(2026, 10, 25))
        self.assertEqual(result['rows'], ROWS)
        self.assertEqual(result['metas'], METAS)
        self.assertEqual(result['total'], 2)

    def test_business_error(self):
        body = {'code': 500, 'msg': '内部错误'}
        with self.assertRaises(LighthouseError):
            board.query_rider_daily(self.session_with(api_response(body)), date(2026, 10, 25))

    def test_sso_redirect_is_session_expired(self):
        response = api_response({}, url='https://ssosv.sankuai.com/sson/login')
        with self.assertRaises(SessionExpired):
            board.query_rider_daily(self.session_with(response), date(2026, 10, 25))

    def test_unauthorized_api_is_session_expired(self):
        with self.assertRaises(SessionExpired):
            board.query_rider_daily(self.session_with(api_response({}, status=401)), date(2026, 10, 25))

    def test_html_response_is_session_expired(self):
        response = api_response({})
        response.headers = {'content-type': 'text/html; charset=utf-8'}
        with self.assertRaises(SessionExpired):
            board.query_rider_daily(self.session_with(response), date(2026, 10, 25))

    def test_network_error(self):
        session = self.session_with(Mock(side_effect=ConnectionError('boom')))
        with self.assertRaises(LighthouseError):
            board.query_rider_daily(session, date(2026, 10, 25))


class WorkbookTests(unittest.TestCase):
    def test_headers_values_and_numeric_conversion(self):
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder) / '日维度骑手分析2026-10-25.xlsx'
            info = board.write_workbook({'rows': ROWS, 'metas': METAS, 'total': 2}, target)
            self.assertEqual(info, {'rows': 2, 'columns': 5})
            book = load_workbook(target)
            sheet = book.active
            rows = list(sheet.iter_rows(values_only=True))
            self.assertEqual(len(rows), 3)
            first, second = rows[0], rows[1]
            self.assertEqual(list(first), ['骑手ID', '骑手名称', '所属站点', '配送单量', '准时率'])
            self.assertEqual(second[0], 842952)
            self.assertEqual(second[3], 50)
            self.assertEqual(second[4], 0.992)
            self.assertEqual(sheet['E2'].number_format, '0.00%')
            self.assertEqual(sheet['B2'].number_format, 'General')
            self.assertEqual(sheet.freeze_panes, 'A2')
            for coordinate in ('A1', 'B2', 'E2'):
                cell = sheet[coordinate]
                self.assertEqual(cell.font.name, '微软雅黑')
                self.assertEqual(cell.font.sz, 10)
                self.assertFalse(cell.font.b)
                self.assertEqual(cell.alignment.horizontal, 'center')
                self.assertEqual(cell.alignment.vertical, 'center')
            for cell in sheet[1]:
                self.assertEqual(cell.fill.patternType, 'solid')
                self.assertEqual(cell.fill.fgColor.rgb, 'FFFDEADA')
            self.assertIsNone(sheet['B2'].fill.patternType)
            self.assertGreaterEqual(sheet.column_dimensions['B'].width, 7)

    def test_empty_rows_rejected(self):
        with self.assertRaises(LighthouseError):
            board.write_workbook({'rows': [], 'metas': METAS, 'total': 0}, Path('unused.xlsx'))

    def test_drops_zero_empty_and_non_numeric_completion_rows(self):
        rows = [
            {'rider_id': '842952', 'transport_end_order_cnt': '40'},
            {'rider_id': '842953', 'transport_end_order_cnt': '0'},
            {'rider_id': '842954', 'transport_end_order_cnt': '0.00'},
            {'rider_id': '842955', 'transport_end_order_cnt': None},
            {'rider_id': '842956', 'transport_end_order_cnt': ''},
            {'rider_id': '842957', 'transport_end_order_cnt': '  '},
            {'rider_id': '842958', 'transport_end_order_cnt': '--'},
            {'rider_id': '842959', 'transport_end_order_cnt': '-1'},
            {'rider_id': '842960', 'transport_end_order_cnt': 38},
        ]
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder) / 'daily.xlsx'
            info = board.write_workbook({'rows': rows, 'metas': COMPLETION_METAS,
                                         'total': len(rows)}, target)
            self.assertEqual(info, {'rows': 2, 'columns': 2})
            values = [list(row) for row in load_workbook(target).active.iter_rows(values_only=True)]
            self.assertEqual(values, [
                ['骑手ID', '配送完成单量'],
                [842952, 40],
                [842960, 38],
            ])

    def test_rejects_when_every_completion_row_is_invalid(self):
        rows = [
            {'rider_id': '842952', 'transport_end_order_cnt': '0'},
            {'rider_id': '842953', 'transport_end_order_cnt': None},
        ]
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaisesRegex(LighthouseError, '配送完成单量'):
                board.write_workbook({'rows': rows, 'metas': COMPLETION_METAS,
                                      'total': len(rows)}, Path(folder) / 'daily.xlsx')


class ValueConversionTests(unittest.TestCase):
    def test_rate_values_accept_percent_and_decimal(self):
        self.assertEqual(board._rate_value('0.8800000000'), 0.88)
        self.assertEqual(board._rate_value('88.00%'), 0.88)
        self.assertAlmostEqual(board._rate_value('-13.95%'), -0.1395)
        self.assertEqual(board._rate_value(0.9), 0.9)
        self.assertIsNone(board._rate_value(None))
        self.assertIsNone(board._rate_value(''))
        self.assertEqual(board._rate_value('--'), '--')

    def test_numeric_identifiers_keep_leading_zeros_and_text(self):
        self.assertEqual(board._numeric_identifier('250'), 250)
        self.assertEqual(board._numeric_identifier('008'), '008')
        self.assertEqual(board._numeric_identifier('SZ0170'), 'SZ0170')
        self.assertEqual(board._numeric_identifier(250.0), 250)
        self.assertEqual(board._numeric_identifier(None), None)


FAKE_STATE = {'cookies': [{'name': 'l', 'value': 'v', 'domain': '.meituan.com', 'path': '/'}], 'origins': []}


class GenerateTests(unittest.TestCase):
    def test_missing_session_guides_to_source_auth(self):
        with patch.object(lh, 'load_state', return_value=None):
            with self.assertRaises(BillCollectionError):
                board.generate_rider_daily('2026-10-25', Path(tempfile.gettempdir()))

    def test_generates_workbook_with_query_result(self):
        logs = []
        data = {'rows': ROWS, 'metas': METAS, 'total': 2}
        with tempfile.TemporaryDirectory() as folder, \
                patch.object(lh, 'load_state', return_value=FAKE_STATE), \
                patch.object(board, 'query_rider_daily', return_value=data):
            target = board.generate_rider_daily('2026-10-25', Path(folder), log=logs.append)
            self.assertTrue(target.is_file())
            self.assertEqual(target.name, '日维度骑手分析2026-10-25.xlsx')
            self.assertTrue(any('商配送数据看板' in message for message in logs))
            self.assertTrue(any('2 行' in message for message in logs))

    def test_board_session_headers(self):
        session = board.board_session(FAKE_STATE)
        self.assertEqual(session.headers['Origin'], board.BOARD_BASE)
        self.assertEqual(session.headers['Referer'], board.BOARD_ENTRY)


class ValidateRequestTests(unittest.TestCase):
    TODAY = date(2026, 10, 26)

    def test_defaults_to_yesterday_all_cities(self):
        config = validate_request({'datasets': ['rider_daily']}, today=self.TODAY)
        self.assertEqual(config['datasets'], ['rider_daily'])
        self.assertEqual(config['cities'], ['全部城市'])
        self.assertEqual(config['start'], '2026-10-25')
        self.assertEqual(config['end'], '2026-10-25')

    def test_mixed_selection_rejected(self):
        with self.assertRaises(ValidationError):
            validate_request({'cities': ['泉州'], 'datasets': ['rider_daily', 'delivery_fee'],
                              'start': '2026-10-01', 'end': '2026-10-25'}, today=self.TODAY)

    def test_group_and_scope_exposed(self):
        from download_service import get_options
        options = {item['id']: item for item in get_options()['datasets']}
        self.assertEqual(options['rider_daily']['group'], 'xiaoxiang')
        self.assertEqual(options['rider_daily']['scope'], 'all')

    def test_archive_name_uses_no_period(self):
        from download_archive import archive_filename
        name = archive_filename('全部城市', 'rider_daily', '2026-10-25', '2026-10-25', suffix='.xlsx', stamp='2026-10-26')
        self.assertEqual(name, '日维度骑手分析2026-10-25.xlsx')


def daily_row(rider_id, site_id, push, ontime='90.00%'):
    return {'rider_id': rider_id, 'rider_name': '骑手{}'.format(rider_id), 'site_name': '站点{}'.format(site_id),
            'site_id': site_id, 'transport_push_order_cnt': push, 'transport_end_order_cnt': push,
            'subscribe_partner_advance_arrive_order_cnt': '0',
            'supplier_transport_ontime_rate': ontime, 'supplier_serious_overtime_rate': '0.00%',
            'supplier_illegal_point_finish_rate': '0.00%', 'fast_30min_delivery_order_rate': '80.00%',
            'supplier_transport_bad_rate': '0.00%'}


class DailyRangeTests(unittest.TestCase):
    def test_range_workbook_keeps_raw_columns_and_prepends_each_date(self):
        rows = [daily_row('842952', 7, '40'), daily_row('842953', 7, '38')]
        days = [(date(2026, 10, 28), rows[:1]), (date(2026, 10, 30), rows[1:])]
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder) / 'range.xlsx'
            info = board.write_daily_range_workbook(days, METAS, target)
            self.assertEqual(info, {'rows': 2, 'columns': 6})
            book = load_workbook(target)
            values = list(book.active.iter_rows(values_only=True))
            self.assertEqual(list(values[0]), ['日期', '骑手ID', '骑手名称', '所属站点', '配送单量', '准时率'])
            self.assertEqual(values[1][0], '2026-10-28')
            self.assertEqual(values[2][0], '2026-10-30')
            self.assertEqual(values[1][1], 842952)
            self.assertEqual(values[1][4], 40)
            self.assertEqual(values[1][5], 0.9)
            sheet = book.active
            self.assertEqual(sheet['F2'].number_format, '0.00%')
            self.assertEqual(sheet['B2'].number_format, 'General')
            self.assertEqual(sheet.freeze_panes, 'A2')
            self.assertEqual(sheet['A1'].font.name, '微软雅黑')
            self.assertEqual(sheet['A1'].font.sz, 10)
            self.assertFalse(sheet['A1'].font.b)
            self.assertEqual(sheet['A1'].alignment.horizontal, 'center')
            self.assertEqual(sheet['A1'].alignment.vertical, 'center')
            for cell in sheet[1]:
                self.assertEqual(cell.fill.patternType, 'solid')
                self.assertEqual(cell.fill.fgColor.rgb, 'FFFDEADA')
            self.assertIsNone(sheet['A2'].fill.patternType)
            self.assertIsNotNone(sheet.column_dimensions['A'].width)
            self.assertGreaterEqual(sheet.column_dimensions['A'].width, 6)

    def test_range_skips_empty_days_and_names_by_period(self):
        logs = []
        def query(_session, day):
            if day == date(2026, 10, 29):
                return {'rows': [], 'metas': METAS, 'total': 0}
            return {'rows': [daily_row('842952', 7, '40')], 'metas': METAS, 'total': 1}
        with tempfile.TemporaryDirectory() as folder, \
                patch.object(lh, 'load_state', return_value=FAKE_STATE), \
                patch.object(board, 'query_rider_daily', side_effect=query) as query_mock:
            target = board.generate_rider_daily_range('2026-10-28', '2026-10-30', Path(folder),
                                                      log=logs.append)
            self.assertEqual(target.name, '日维度骑手分析2026-10-28-2026-10-30.xlsx')
            names = [call.args[1] for call in query_mock.call_args_list]
            self.assertEqual(names, [date(2026, 10, 28), date(2026, 10, 29), date(2026, 10, 30)])
            book = load_workbook(target)
            values = list(book.active.iter_rows(values_only=True))
            self.assertEqual(len(values), 3)
            self.assertEqual(values[1][0], '2026-10-28')
            self.assertEqual(values[2][0], '2026-10-30')
        self.assertTrue(any('跳过' in message and '2026-10-29' in message for message in logs))

    def test_range_drops_invalid_completion_rows(self):
        days = [
            (date(2026, 10, 28), [
                {'rider_id': '842952', 'transport_end_order_cnt': '2'},
                {'rider_id': '842953', 'transport_end_order_cnt': '0'},
            ]),
            (date(2026, 10, 29), [
                {'rider_id': '842954', 'transport_end_order_cnt': None},
                {'rider_id': '842955', 'transport_end_order_cnt': '3'},
            ]),
            (date(2026, 10, 30), [
                {'rider_id': '842956', 'transport_end_order_cnt': '--'},
            ]),
        ]
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder) / 'range.xlsx'
            info = board.write_daily_range_workbook(days, COMPLETION_METAS, target)
            self.assertEqual(info, {'rows': 2, 'columns': 3})
            values = [list(row) for row in load_workbook(target).active.iter_rows(values_only=True)]
            self.assertEqual(values, [
                ['日期', '骑手ID', '配送完成单量'],
                ['2026-10-28', 842952, 2],
                ['2026-10-29', 842955, 3],
            ])

    def test_range_rejects_when_all_completion_rows_are_invalid(self):
        days = [(date(2026, 10, 28), [
            {'rider_id': '842952', 'transport_end_order_cnt': '0'},
        ])]
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaisesRegex(LighthouseError, '没有骑手分析数据'):
                board.write_daily_range_workbook(days, COMPLETION_METAS, Path(folder) / 'range.xlsx')

    def test_range_rejects_changing_column_definition(self):
        other = [{'fieldCode': 'rider_id', 'name': '骑手ID'}]
        def query(_session, day):
            metas = other if day == date(2026, 10, 30) else METAS
            return {'rows': [daily_row('842952', 7, '40')], 'metas': metas, 'total': 1}
        with tempfile.TemporaryDirectory() as folder, \
                patch.object(lh, 'load_state', return_value=FAKE_STATE), \
                patch.object(board, 'query_rider_daily', side_effect=query):
            with self.assertRaisesRegex(LighthouseError, '列定义'):
                board.generate_rider_daily_range('2026-10-29', '2026-10-30', Path(folder))

    def test_range_rejects_more_than_31_days_and_all_empty_days(self):
        with self.assertRaises(LighthouseError):
            board.generate_rider_daily_range('2026-09-01', '2026-10-02', Path(tempfile.gettempdir()))
        with patch.object(lh, 'load_state', return_value=FAKE_STATE), \
                patch.object(board, 'query_rider_daily', return_value={'rows': [], 'metas': METAS, 'total': 0}):
            with self.assertRaisesRegex(LighthouseError, '均无骑手分析数据'):
                board.generate_rider_daily_range('2026-10-28', '2026-10-29', Path(tempfile.gettempdir()))

    def test_validate_request_accepts_range_and_rejects_out_of_bounds(self):
        today = date(2026, 10, 31)
        config = validate_request({'datasets': ['rider_daily'], 'start': '2026-10-01', 'end': '2026-10-30'},
                                  today=today)
        self.assertEqual((config['start'], config['end'], config['months']), ('2026-10-01', '2026-10-30',
                                                                              ['2026-10']))
        for payload in ({'start': '2026-10-01', 'end': '2026-10-31'},
                        {'start': '2026-09-01', 'end': '2026-10-02'},
                        {'start': '2026-10-20', 'end': '2026-10-01'},
                        {'start': '2026-10-01'}):
            with self.subTest(payload=payload), self.assertRaises(ValidationError):
                validate_request({'datasets': ['rider_daily'], **payload}, today=today)

    def test_archive_name_for_range_has_no_city_prefix(self):
        from download_archive import archive_filename
        name = archive_filename('全部城市', 'rider_daily', '2026-10-01', '2026-10-30', suffix='.xlsx',
                                stamp='2026-10-31')
        self.assertEqual(name, '日维度骑手分析2026-10-01-2026-10-30.xlsx')

    def test_multiple_lighthouse_datasets_form_one_item_per_dataset(self):
        config = validate_request({'datasets': ['detail_orders', 'rider_daily']}, today=date(2026, 10, 31))
        self.assertEqual(config['datasets'], ['rider_daily', 'detail_orders'])
        items = __import__('download_service')._requested_items(config)
        self.assertEqual([(item['dataset'], item['city']) for item in items],
                         [('rider_daily', '全部城市'), ('detail_orders', '全部城市')])


DETAIL_ROWS = [
    {'dt': '20261029', 'order_id': '1666006861726754', 'delivery_id': '3236048707',
     'time_package': '小象40分', 'order_source': '外卖', 'total_pay': '44.300000',
     'pkg_weight': '4.300000', 'is_sanfang': '否', 'city_name': '深圳',
     'supplier_name': '某某配送有限公司', 'rider_mis': 'ls_demo', 'rider_id': '431261',
     'rider_name': '张三', 'site_name': '塘尾站', 'push_time': '2026-10-29 00:00:19',
     'rider_take_time': '2026-10-29 00:07:23', 'transport_estimate_time': '2026-10-29 00:19:02',
     'latest_delivery_time': '2026-10-29 00:23:19', 'arrived_time': '2026-10-29 00:16:30',
     'distance': '2.193000', 'user_rate': 'null', 'is_overtime': '否',
     'is_poi_delivery_overtime': '是', 'is_transport_overtime': '否', 'is_advance_arrive': '否'},
]
REVIEW_ROWS = [
    {'review_id': '20036444476', 'rider_mis': 'ls_demo', 'review_type': '好评',
     'dt': '20261029', 'site_name': '塘尾站', 'city_name': '深圳', 'rider_name': '张三',
     'site_id': '493', 'review_time': '2026-10-29 00:08:52',
     'supplier_name': '某某配送有限公司', 'order_id': '1666007302884993', 'rider_id': 431261,
     'comments_tags': '2#骑手评价满意,3001#准时送达'},
]


class DetailTests(unittest.TestCase):
    def session_with(self, responses):
        session = Mock()
        session.post = Mock(side_effect=responses)
        return session

    def test_query_detail_rows_requests_expected_custom_params(self):
        body = {'code': 0, 'data': {'body': DETAIL_ROWS, 'total': 1}}
        session = self.session_with([api_response(body, url='https://zl.meituan.com/api/mall/mustang/13793')])
        rows = board.query_detail_rows(session, 'detail_orders', date(2026, 10, 29), [493, 975])
        self.assertEqual(len(rows), 1)
        request = session.post.call_args
        self.assertEqual(request.args[0], 'https://zl.meituan.com/api/mall/mustang/13793')
        custom = json.loads(request.kwargs['json']['customParams'])
        self.assertEqual(custom['referenceDatekey'], ['20261029', '20261029'])
        self.assertEqual(custom['siteIds'], [493, 975])
        self.assertEqual(custom['is_transport_overtime'], '-1')
        self.assertEqual(custom['limit'], board.DETAIL_PAGE_LIMIT)
        self.assertEqual(custom['page'], 1)

    def test_query_detail_rows_paginates_until_total_reached(self):
        first = {'code': 0, 'data': {'body': DETAIL_ROWS, 'total': 2}}
        second = {'code': 0, 'data': {'body': [dict(DETAIL_ROWS[0], order_id='x')], 'total': 2}}
        session = self.session_with([api_response(first), api_response(second)])
        rows = board.query_detail_rows(session, 'detail_orders', date(2026, 10, 29), [493])
        self.assertEqual(len(rows), 2)
        self.assertEqual(session.post.call_args.kwargs['json'] and
                         json.loads(session.post.call_args.kwargs['json']['customParams'])['page'], 2)

    def test_query_detail_rows_rejects_truncated_single_day(self):
        first = {'code': 0, 'data': {'body': DETAIL_ROWS, 'total': 90000}}
        empty = {'code': 0, 'data': {'body': [], 'total': 90000}}
        session = self.session_with([api_response(first), api_response(empty)])
        with self.assertRaisesRegex(LighthouseError, '不完整'):
            board.query_detail_rows(session, 'detail_orders', date(2026, 10, 29), [493])

    def test_query_detail_rows_missing_site_ids_param(self):
        body = {'code': 0, 'data': {'body': [], 'total': 0}}
        session = self.session_with([api_response(body)])
        rows = board.query_detail_rows(session, 'detail_kesu', date(2026, 10, 29), [493])
        self.assertEqual(rows, [])
        custom = json.loads(session.post.call_args.kwargs['json']['customParams'])
        self.assertEqual(custom['$apipathname'], '/$fe//kesuDetail/table')
        self.assertNotIn('is_transport_overtime', custom)

    def test_detail_row_values_formats_date_and_rider_id(self):
        values = board.detail_row_values(board.DETAIL_TABLES['detail_orders'], date(2026, 10, 29), DETAIL_ROWS[0])
        self.assertEqual(len(values), len(board.DETAIL_TABLES['detail_orders']['columns']))
        self.assertEqual(values[0], '2026-10-29')
        self.assertEqual(values[1], '1666006861726754')
        self.assertEqual(values[11], 431261)
        review = board.detail_row_values(board.DETAIL_TABLES['detail_reviews'], date(2026, 10, 29), REVIEW_ROWS[0])
        self.assertEqual(review[1], '20036444476')
        self.assertEqual(review[7], 431261)

    def test_workbook_writes_official_headers(self):
        spec = board.DETAIL_TABLES['detail_reviews']
        records = [board.detail_row_values(spec, date(2026, 10, 29), REVIEW_ROWS[0])]
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder) / 'detail.xlsx'
            info = board.write_detail_workbook(spec, records, target)
            self.assertEqual(info, {'rows': 1, 'columns': 12})
            book = load_workbook(target)
            rows = list(book.active.iter_rows(values_only=True))
            self.assertEqual(list(rows[0]), [name for _, name in spec['columns']])
            self.assertEqual(rows[1][0], '2026-10-29')
            self.assertEqual(rows[1][7], 431261)

    def test_generate_detail_merges_days_skips_empty_and_names_by_period(self):
        logs = []
        def query_rows(_session, kind, day, site_ids):
            if day == date(2026, 10, 29):
                return []
            return [dict(REVIEW_ROWS[0])]
        with tempfile.TemporaryDirectory() as folder, \
                patch.object(lh, 'load_state', return_value=FAKE_STATE), \
                patch.object(board, 'query_site_ids', return_value=[493, 975]) as site_mock, \
                patch.object(board, 'query_detail_rows', side_effect=query_rows) as query_mock:
            target = board.generate_detail('detail_reviews', '2026-10-28', '2026-10-29', Path(folder),
                                           log=logs.append)
            self.assertEqual(target.name, '2026-10-28-2026-10-29配送评价明细.xlsx')
            site_mock.assert_called_once()
            self.assertEqual(query_mock.call_args_list[0].args[2], date(2026, 10, 28))
            book = load_workbook(target)
            values = list(book.active.iter_rows(values_only=True))
            self.assertEqual(len(values), 2)
            self.assertEqual(values[1][0], '2026-10-28')
        self.assertTrue(any('跳过' in message and '2026-10-29' in message for message in logs))
        self.assertTrue(any('[校验]' in message and '1 行 / 12 列' in message for message in logs))

    def test_generate_detail_rejects_long_range_and_all_empty(self):
        with self.assertRaises(LighthouseError):
            board.generate_detail('detail_orders', '2026-09-01', '2026-10-02', Path(tempfile.gettempdir()))
        with patch.object(lh, 'load_state', return_value=FAKE_STATE), \
                patch.object(board, 'query_site_ids', return_value=[493]), \
                patch.object(board, 'query_detail_rows', return_value=[]):
            with self.assertRaisesRegex(LighthouseError, '均无配送订单明细数据'):
                board.generate_detail('detail_orders', '2026-10-28', '2026-10-29', Path(tempfile.gettempdir()))

    def test_generate_detail_single_day_name(self):
        with tempfile.TemporaryDirectory() as folder, \
                patch.object(lh, 'load_state', return_value=FAKE_STATE), \
                patch.object(board, 'query_site_ids', return_value=[493]), \
                patch.object(board, 'query_detail_rows', return_value=REVIEW_ROWS):
            target = board.generate_detail('detail_reviews', '2026-10-29', '2026-10-29', Path(folder))
            self.assertEqual(target.name, '2026-10-29配送评价明细.xlsx')

    def test_validate_request_accepts_each_detail_dataset(self):
        today = date(2026, 10, 31)
        for dataset in ('detail_orders', 'detail_kesu', 'detail_reviews'):
            with self.subTest(dataset=dataset):
                config = validate_request({'datasets': [dataset]}, today=today)
                self.assertEqual(config['datasets'], [dataset])
                self.assertEqual((config['start'], config['end']), ('2026-10-30', '2026-10-30'))
                self.assertEqual(config['cities'], ['全部城市'])
        multi = validate_request({'datasets': ['detail_orders', 'detail_kesu', 'rider_daily']}, today=today)
        self.assertEqual(multi['datasets'], ['rider_daily', 'detail_orders', 'detail_kesu'])
        self.assertEqual((multi['start'], multi['end']), ('2026-10-30', '2026-10-30'))
        with self.assertRaises(ValidationError):
            validate_request({'datasets': ['detail_orders', 'delivery_fee']}, today=today)
        with self.assertRaises(ValidationError):
            validate_request({'datasets': ['detail_orders'], 'start': '2026-10-01', 'end': '2026-10-31'},
                             today=today)

    def test_group_and_scope_exposed_for_details(self):
        options = __import__('download_service').get_options()
        by_id = {item['id']: item for item in options['datasets']}
        for dataset in ('detail_orders', 'detail_kesu', 'detail_reviews'):
            self.assertEqual(by_id[dataset]['group'], 'xiaoxiang')
            self.assertEqual(by_id[dataset]['scope'], 'all')

    def test_archive_names_for_details(self):
        from download_archive import archive_filename
        self.assertEqual(archive_filename('全部城市', 'detail_orders', '2026-10-29', '2026-10-29',
                                          suffix='.xlsx', stamp='2026-10-31'),
                         '2026-10-29配送订单明细.xlsx')
        self.assertEqual(archive_filename('全部城市', 'detail_reviews', '2026-10-01', '2026-10-07',
                                          suffix='.xlsx', stamp='2026-10-31'),
                         '2026-10-01-2026-10-07配送评价明细.xlsx')


if __name__ == '__main__':
    unittest.main()
