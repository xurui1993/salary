from datetime import date, datetime
from io import BytesIO
import base64
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

from openpyxl import load_workbook

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import xiaoxiang_lighthouse as lh
import xiaoxiang_rider_archive as archive
from download_service import ValidationError, validate_request
from xiaoxiang_lighthouse import LighthouseError, SessionExpired


def api_response(body, status=200, url='https://maicaipeisong.meituan.com/api/s/peisong/x'):
    response = Mock()
    response.status_code = status
    response.url = url
    response.headers = {'content-type': 'application/json'}
    response.json = lambda: body
    return response


def moa_state(mis='ls_operator01'):
    payload = base64.urlsafe_b64encode(json.dumps({'uid': 1, 'mis': mis}).encode()).decode()
    return {'cookies': [{'name': 'moa_token', 'value': payload, 'domain': '.meituan.com', 'path': '/'}],
            'origins': []}


RIDER = {'id': 574350, 'mis': 'ls_rider01', 'name': '张三', 'mobile': '138****0000', 'role': 0,
         'imgUrl': 'https://img.example/avatar.jpg', 'canWork': 1, 'workSiteId': 1720,
         'workSiteName': '小象超市-测试站', 'dutyStatus': 1, 'supplierId': 106, 'supplierName': '测试供应商',
         'identityId': '4405**********001', 'healthExpiredTime': 1794153600000, 'zombieDays': 2,
         'newOldRiderTag': 20, 'qrDispatchStatus': 0, 'employeeTime': 1793183554180, 'entryTime': 0,
         'resignationTime': 0, 'leaderInfos': [{'name': '李组长'}], 'bindSiteInfos': [{'siteName': '小象超市-测试站'}],
         'attr': 10, 'cityName': '深圳', 'recruitChannel': 30, 'laborOutsourcer': '',
         'imageInfo': {'avatarImg': 'https://img.example/a.jpg', 'identityFrontImg': 'http://img.example/f.jpg',
                       'identityBackImg': None, 'holdIdentityFrontImg': None, 'holdIdentityBackImg': None,
                       'healthIdentityUrl': 'https://img.example/h.jpg', 'extendImages': []},
         'gender': 1, 'rcLevel': 0, 'uid': 'u-1', 'ytTypeList': [10], 'experienced': 1,
         'workStatusApp': 1, 'transSiteStatus': 0, 'transSiteTarget': 0, 'walletId': 0,
         'walletStatus': 0, 'walletBindCardStatus': None, 'fireEye': 10, 'leaderLabel': 0,
         'ctime': 1793200132231, 'utime': 1793351274306}
SENS = {'id': 574350, 'mobile': '13800000000', 'identityId': '440582199000000001'}


class OperatorTests(unittest.TestCase):
    def test_mis_from_base64_moa_token(self):
        self.assertEqual(archive.operator_mis(moa_state()), 'ls_operator01')

    def test_plain_json_cookie_supported(self):
        state = {'cookies': [{'name': 'moa_token', 'value': '{"mis":"ls_plain02"}',
                              'domain': '.meituan.com', 'path': '/'}], 'origins': []}
        self.assertEqual(archive.operator_mis(state), 'ls_plain02')

    def test_missing_mis_rejected(self):
        with self.assertRaises(LighthouseError):
            archive.operator_mis({'cookies': [], 'origins': []})


class QueryTests(unittest.TestCase):
    def session_with(self, responses):
        session = Mock()
        session.post = Mock(side_effect=responses)
        return session

    def list_body(self, offset):
        return archive._list_body(offset, '106', 'ls_operator01')

    def test_query_rider_rows_single_page(self):
        body = {'code': 0, 'data': {'total': 1, 'list': [RIDER]}}
        session = self.session_with([api_response(body)])
        rows = archive.query_rider_rows(session, operator='ls_operator01')
        self.assertEqual(rows, [RIDER])
        payload = session.post.call_args.kwargs['json']
        self.assertEqual(payload['operator'], 'ls_operator01')
        self.assertEqual(payload['supplierId'], '106')
        self.assertTrue(payload['needImageInfo'])
        self.assertFalse(payload['needImg'])
        self.assertEqual(payload['paging'], {'needPagination': True, 'offset': 0, 'limit': archive.LIST_PAGE_LIMIT})

    def test_query_rider_rows_paginates_until_total(self):
        first = {'code': 0, 'data': {'total': 2, 'list': [RIDER]}}
        second = {'code': 0, 'data': {'total': 2, 'list': [dict(RIDER, id=574351)]}}
        session = self.session_with([api_response(first), api_response(second)])
        rows = archive.query_rider_rows(session, operator='ls_operator01')
        self.assertEqual([row['id'] for row in rows], [574350, 574351])
        second_payload = session.post.call_args_list[1].kwargs['json']
        self.assertEqual(second_payload['paging']['offset'], 1)

    def test_query_rider_rows_rejects_truncated(self):
        first = {'code': 0, 'data': {'total': 3, 'list': [RIDER]}}
        empty = {'code': 0, 'data': {'total': 3, 'list': []}}
        session = self.session_with([api_response(first), api_response(empty), api_response(empty)])
        with self.assertRaisesRegex(LighthouseError, '不完整'):
            archive.query_rider_rows(session, operator='ls_operator01')

    def test_query_sens_batches_of_50_and_merges(self):
        ids = list(range(1, 121))
        responses = [api_response({'code': 0, 'data': {'riderSensInfos': [
            {'id': value, 'mobile': '13800000000', 'identityId': None} for value in ids[index:index + 50]]}})
            for index in range(0, 120, 50)]
        session = self.session_with(responses)
        infos = archive.query_sens_infos(session, ids, operator='ls_operator01')
        self.assertEqual(len(infos), 120)
        self.assertEqual(len(session.post.call_args_list), 3)
        self.assertEqual(session.post.call_args_list[0].kwargs['json']['sensRiderIds'], ids[:50])
        self.assertTrue(session.post.call_args_list[0].kwargs['json']['needIdentityId'])

    def test_query_sens_business_error(self):
        session = self.session_with([api_response({'code': 2, 'msg': '骑手id个数大于上限'})])
        with self.assertRaisesRegex(LighthouseError, '骑手联系方式'):
            archive.query_sens_infos(session, [1], operator='ls_operator01')

    def test_session_expired_and_html_responses(self):
        with self.assertRaises(SessionExpired):
            archive.query_rider_rows(self.session_with([api_response({'code': 5})]), operator='x')
        response = api_response({})
        response.headers = {'content-type': 'text/html'}
        with self.assertRaises(SessionExpired):
            archive.query_rider_rows(self.session_with([response]), operator='x')

    def test_query_attr_names_falls_back_to_builtin(self):
        session = self.session_with([api_response({'code': 0, 'data': {'riderAttrList': [
            {'attrId': 40, 'attrName': '试验属性'}]}})])
        names = archive.query_attr_names(session, operator='ls_operator01')
        self.assertEqual(names[10], '时段兼职')
        self.assertEqual(names[40], '试验属性')

    def test_query_attr_names_ignores_failure(self):
        session = self.session_with([api_response({'code': 500, 'msg': 'boom'})])
        self.assertEqual(archive.query_attr_names(session, operator='ls_operator01'), archive.ATTR_NAMES)

    def test_query_attr_names_propagates_session_expired(self):
        session = self.session_with([api_response({'code': 5})])
        with self.assertRaises(SessionExpired):
            archive.query_attr_names(session, operator='ls_operator01')


class RowValueTests(unittest.TestCase):
    def test_row_values_merge_sens_and_numeric_codes(self):
        values = archive.rider_row_values(RIDER, SENS, archive.ATTR_NAMES)
        self.assertEqual(len(values), len(archive.COLUMNS))
        by_code = dict(zip((code for code, _ in archive.COLUMNS), values))
        self.assertEqual(by_code['work_site_name'], '小象超市-测试站')
        self.assertEqual(by_code['id'], 574350)
        self.assertEqual(by_code['mobile'], '13800000000')
        self.assertEqual(by_code['identity_id'], '440582199000000001')
        self.assertEqual(by_code['attr_name'], '时段兼职')
        self.assertEqual(by_code['gender'], '男')
        self.assertEqual(by_code['employee_time'], '2026-10-28 18:32:34')
        self.assertEqual(by_code['entry_time'], None)
        self.assertEqual(by_code['health_expired_date'], '2026-11-09')
        self.assertEqual(by_code['yt_types'], '10')
        self.assertEqual(by_code['zombie_days'], 2)
        self.assertEqual(by_code['experienced'], 1)
        self.assertEqual(by_code['new_old_rider_tag'], 20)
        self.assertEqual(by_code['uid'], 'u-1')
        self.assertEqual(by_code['wallet_id'], 0)
        self.assertEqual(by_code['utime'], '2026-10-30 17:07:54')

    def test_masked_values_used_without_sens(self):
        values = archive.rider_row_values(RIDER, None, archive.ATTR_NAMES)
        by_code = dict(zip((code for code, _ in archive.COLUMNS), values))
        self.assertEqual(by_code['mobile'], '138****0000')
        self.assertEqual(by_code['identity_id'], '4405**********001')


class WorkbookTests(unittest.TestCase):
    def test_workbook_headers_rows_and_styles(self):
        records = [archive.rider_row_values(RIDER, SENS, archive.ATTR_NAMES)]
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder) / '灯塔骑手档案1030.xlsx'
            info = archive.write_archive_workbook(records, target)
            self.assertEqual(info, {'rows': 1, 'columns': len(archive.COLUMNS)})
            book = load_workbook(target)
            sheet = book.active
            rows = list(sheet.iter_rows(values_only=True))
            self.assertEqual(list(rows[0]), [name for _, name in archive.COLUMNS])
            self.assertEqual(rows[1][0], '小象超市-测试站')
            self.assertEqual(rows[1][1], 574350)
            self.assertEqual(rows[1][4], '13800000000')
            self.assertEqual(sheet.freeze_panes, 'A2')
            for cell in sheet[1]:
                self.assertEqual(cell.font.name, '微软雅黑')
                self.assertEqual(cell.font.sz, 10)
                self.assertFalse(cell.font.b)
                self.assertEqual(cell.alignment.horizontal, 'center')
                self.assertEqual(cell.fill.patternType, 'solid')
                self.assertEqual(cell.fill.fgColor.rgb, 'FFFDEADA')
            self.assertIsNone(sheet['B2'].fill.patternType)
            wallet_index = [code for code, _ in archive.COLUMNS].index('wallet_id')
            self.assertEqual(sheet.cell(row=2, column=wallet_index + 1).number_format, '0')
            self.assertGreaterEqual(sheet.column_dimensions['A'].width, 12)

    def test_empty_records_rejected(self):
        with self.assertRaises(LighthouseError):
            archive.write_archive_workbook([], Path('unused.xlsx'))


class GenerateTests(unittest.TestCase):
    def test_missing_session_guides_to_source_auth(self):
        from fengshen_bill import BillCollectionError
        with patch.object(lh, 'load_state', return_value=None):
            with self.assertRaises(BillCollectionError):
                archive.generate_rider_archive(Path(tempfile.gettempdir()))

    def test_generates_snapshot_workbook(self):
        logs = []
        session = Mock()
        session.headers = {}
        with tempfile.TemporaryDirectory() as folder, \
                patch.object(lh, 'load_state', return_value=moa_state()), \
                patch.object(lh, 'session_from_state', return_value=session), \
                patch.object(archive, 'query_rider_rows', return_value=[RIDER]) as rows_mock, \
                patch.object(archive, 'query_sens_infos', return_value={574350: SENS}) as sens_mock:
            target = archive.generate_rider_archive(Path(folder), log=logs.append)
            expected = datetime.now(archive.BEIJING).strftime('灯塔骑手档案%m%d')
            self.assertEqual(target.name, expected + '.xlsx')
            rows_mock.assert_called_once()
            sens_mock.assert_called_once()
            self.assertEqual(sens_mock.call_args.args[1], [574350])
            book = load_workbook(target)
            values = list(book.active.iter_rows(values_only=True))
            self.assertEqual(len(values), 2)
            self.assertEqual(values[1][4], '13800000000')
            session.close.assert_called_once()
        self.assertTrue(any('骑手 1 人' in m for m in logs))
        self.assertTrue(any('[校验]' in m and '1 行 / 28 列' in m for m in logs))


class ValidateRequestTests(unittest.TestCase):
    def test_validate_accepts_snapshot_without_dates(self):
        config = validate_request({'datasets': ['rider_archive']}, today=date(2026, 10, 31))
        self.assertEqual(config['datasets'], ['rider_archive'])
        self.assertEqual((config['start'], config['end']), ('2026-10-31', '2026-10-31'))
        self.assertEqual(config['cities'], ['全部城市'])

    def test_validate_accepts_snapshot_with_other_lighthouse_items_and_rejects_generator(self):
        config = validate_request({'datasets': ['rider_archive', 'detail_orders']}, today=date(2026, 10, 31))
        self.assertEqual(config['datasets'], ['rider_archive', 'detail_orders'])
        self.assertEqual((config['start'], config['end']), ('2026-10-30', '2026-10-30'))
        config = validate_request({'datasets': ['rider_archive', 'rider_daily']}, today=date(2026, 10, 31))
        self.assertEqual(config['datasets'], ['rider_daily', 'rider_archive'])
        with self.assertRaises(ValidationError):
            validate_request({'datasets': ['rider_archive'], 'task_kind': 'generate'}, today=date(2026, 10, 31))
        with self.assertRaises(ValidationError):
            validate_request({'datasets': ['rider_archive', 'delivery_fee']}, today=date(2026, 10, 31))

    def test_group_and_scope_exposed(self):
        options = __import__('download_service').get_options()
        by_id = {item['id']: item for item in options['datasets']}
        self.assertEqual(by_id['rider_archive']['group'], 'xiaoxiang')
        self.assertEqual(by_id['rider_archive']['scope'], 'all')


class ArchiveNameTests(unittest.TestCase):
    def test_snapshot_name_uses_generation_mmdd_without_city_prefix(self):
        from download_archive import archive_filename
        self.assertEqual(archive_filename('全部城市', 'rider_archive', '2026-10-30', '2026-10-30',
                                          suffix='.xlsx', stamp='2026-10-30'),
                         '灯塔骑手档案1030.xlsx')


if __name__ == '__main__':
    unittest.main()
