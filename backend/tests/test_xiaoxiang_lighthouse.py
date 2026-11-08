from datetime import date
from io import BytesIO
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

from openpyxl import Workbook

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import xiaoxiang_lighthouse as lh


def workbook_bytes(headers=None, rows=1):
    headers = headers or ['合作商名称', '站点id', '业务日期', '骑手id', '合作商id', '配送方', '配送单量']
    book = Workbook()
    sheet = book.active
    sheet.append(headers)
    for index in range(rows):
        sheet.append(['深圳市麻豆人配送服务有限公司', 10001954, '2026/10/23', 842952, 106, '商', 50 + index])
    stream = BytesIO()
    book.save(stream)
    return stream.getvalue()


def fake_response(chunks, status=200):
    response = Mock()
    response.status_code = status
    response.iter_content = lambda size: iter(chunks)
    response.__enter__ = lambda *args: response
    response.__exit__ = lambda *args: False
    return response


class WeekTests(unittest.TestCase):
    def test_previous_week_on_monday(self):
        self.assertEqual(lh.week_range(date(2026, 10, 26)), (date(2026, 10, 19), date(2026, 10, 25)))

    def test_previous_week_on_sunday(self):
        self.assertEqual(lh.week_range(date(2026, 10, 25)), (date(2026, 10, 12), date(2026, 10, 18)))

    def test_week_of_mid_week_day(self):
        self.assertEqual(lh.week_of(date(2026, 10, 21)), (date(2026, 10, 19), date(2026, 10, 25)))

    def test_title_without_zero_padding(self):
        self.assertEqual(lh.week_title(date(2026, 10, 19), date(2026, 10, 25)), '10.19-10.25骑手订单明细')

    def test_title_across_month(self):
        self.assertEqual(lh.week_title(date(2026, 9, 28), date(2026, 10, 4)), '9.28-10.4骑手订单明细')

    def test_millisecond_publish_time_is_readable(self):
        text = lh.readable_time(1792982062626)
        self.assertEqual(text, '2026-10-26T10:34:22')

    def test_text_time_is_kept(self):
        self.assertEqual(lh.readable_time('2026-10-26 10:00:00'), '2026-10-26 10:00:00')


class AttachmentTests(unittest.TestCase):
    def test_keeps_only_shangpeisong_xlsx(self):
        items = [
            {'fileName': '10.19-10.25骑手订单明细-商配送-1.xlsx', 'fileUrl': 'https://s3/a'},
            {'fileName': '10.19-10.25骑手订单明细-商配送-2.xlsx', 'fileUrl': 'https://s3/b'},
            {'fileName': '10.19-10.25骑手订单明细-大网配送.xlsx', 'fileUrl': 'https://s3/c'},
            {'fileName': '10.19-10.25骑手订单明细-商配送.pdf', 'fileUrl': 'https://s3/d'},
            {'fileName': '10.19-10.25骑手订单明细.xlsx', 'fileUrl': 'https://s3/e'},
            {'fileName': '商配送.xlsx', 'fileUrl': ''},
        ]
        picked = lh.select_attachments(items)
        self.assertEqual([item['fileName'] for item in picked],
                         ['10.19-10.25骑手订单明细-商配送-1.xlsx', '10.19-10.25骑手订单明细-商配送-2.xlsx'])

    def test_empty_input(self):
        self.assertEqual(lh.select_attachments(None), [])


class ApiTests(unittest.TestCase):
    def test_find_notice_requires_exact_title(self):
        session = Mock()
        with patch.object(lh, '_post', return_value={'noticeRecordList': [
                {'id': 1, 'title': '10.18-10.25骑手订单明细'},
                {'id': 2, 'title': '10.19-10.25骑手订单明细'}]}):
            self.assertEqual(lh.find_notice(session, '10.19-10.25骑手订单明细')['id'], 2)

    def test_find_notice_missing(self):
        session = Mock()
        with patch.object(lh, '_post', return_value={'noticeRecordList': []}):
            self.assertIsNone(lh.find_notice(session, '10.19-10.25骑手订单明细'))

    def test_list_payload_carries_paging_and_supplier(self):
        session = Mock()
        with patch.object(lh, '_post', return_value={}) as post:
            lh.find_notice(session, '10.19-10.25骑手订单明细')
        payload = post.call_args[0][2]
        self.assertEqual(payload, {'title': '10.19-10.25骑手订单明细', 'paging': {}, 'supplierId': 106})

    def test_not_logged_in_raises_session_expired(self):
        response = Mock(status_code=200)
        response.json.return_value = {'code': 5, 'error': {'msg': '未登录'}}
        session = Mock()
        session.post.return_value = response
        with self.assertRaises(lh.SessionExpired):
            lh._post(session, lh.LIST_PATH, {})

    def test_other_api_error_is_not_auth_error(self):
        response = Mock(status_code=200)
        response.json.return_value = {'code': 2, 'msg': '分页参数必传'}
        session = Mock()
        session.post.return_value = response
        with self.assertRaises(lh.LighthouseError) as raised:
            lh._post(session, lh.LIST_PATH, {})
        self.assertNotIsInstance(raised.exception, lh.SessionExpired)
        self.assertIn('分页参数必传', str(raised.exception))


class StateTests(unittest.TestCase):
    def state(self):
        return {'cookies': [
            {'name': 'u', 'value': '4996639396', 'domain': '.meituan.com', 'path': '/', 'expires': -1},
            {'name': 'token', 'value': 'secret', 'domain': 'maicaipeisong.meituan.com', 'path': '/', 'expires': -1},
            {'name': 'x', 'value': 'y', 'domain': 's3plus.sankuai.com', 'path': '/', 'expires': -1},
            {'name': 'other', 'value': 'z', 'domain': 'example.com', 'path': '/', 'expires': -1}],
            'origins': [{'origin': 'https://maicaipeisong.meituan.com',
                         'localStorage': [{'name': 'rss_supplier_id', 'value': '106'}]},
                        {'origin': 'https://example.com', 'localStorage': []}]}

    def test_scoped_state_drops_foreign_domains(self):
        scoped = lh.scoped_state(self.state())
        self.assertEqual([cookie['name'] for cookie in scoped['cookies']], ['u', 'token', 'x'])
        self.assertEqual([origin['origin'] for origin in scoped['origins']], ['https://maicaipeisong.meituan.com'])

    def test_scoped_state_requires_cookies(self):
        with self.assertRaises(lh.LighthouseError):
            lh.scoped_state({'cookies': [{'name': 'a', 'value': 'b', 'domain': 'example.com'}], 'origins': []})

    def test_session_replays_cookies(self):
        session = lh.session_from_state(self.state())
        names = {cookie.name for cookie in session.cookies}
        self.assertEqual(names, {'u', 'token', 'x'})
        self.assertEqual(session.headers['Referer'], lh.ENTRY)

    @unittest.skipUnless(os.name == 'nt', 'DPAPI 仅支持 Windows')
    def test_state_roundtrip_is_encrypted(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'session.dpapi'
            lh.save_state(self.state(), path)
            raw = path.read_bytes()
            self.assertNotIn(b'4996639396', raw)
            loaded = lh.load_state(path)
            self.assertEqual(loaded['cookies'][1]['value'], 'secret')


class ValidationTests(unittest.TestCase):
    def test_valid_workbook_reports_rows(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'a.xlsx'
            path.write_bytes(workbook_bytes(rows=3))
            info = lh.validate_workbook(path)
            self.assertEqual(info['rows'], 3)
            self.assertEqual(info['columns'], 7)

    def test_missing_column_is_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'a.xlsx'
            path.write_bytes(workbook_bytes(headers=['合作商名称', '站点id']))
            with self.assertRaises(lh.LighthouseError):
                lh.validate_workbook(path)

    def test_non_zip_is_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'a.xlsx'
            path.write_bytes(b'<html>login</html>')
            with self.assertRaises(lh.LighthouseError):
                lh.validate_workbook(path)

    def test_empty_sheet_is_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'a.xlsx'
            path.write_bytes(workbook_bytes(rows=0))
            with self.assertRaises(lh.LighthouseError):
                lh.validate_workbook(path)

    def test_download_writes_valid_file(self):
        payload = workbook_bytes()
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder) / '商配送-1.xlsx'
            with patch.object(lh.requests, 'get', return_value=fake_response([payload[:100], payload[100:]])):
                info = lh._download('https://s3.example/a', target)
            self.assertTrue(target.is_file())
            self.assertFalse(Path(str(target) + '.part').exists())
            self.assertEqual(info['rows'], 1)
            self.assertEqual(info['bytes'], len(payload))
            self.assertEqual(len(info['sha256']), 64)

    def test_download_rejects_invalid_payload(self):
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder) / 'a.xlsx'
            with patch.object(lh.requests, 'get', return_value=fake_response([b'not a zip'])):
                with self.assertRaises(lh.LighthouseError):
                    lh._download('https://s3.example/a', target)
            self.assertFalse(target.exists())


class NamingTests(unittest.TestCase):
    def test_duplicate_batch_names_get_suffix(self):
        self.assertEqual(list(lh._batch_names(['a.xlsx', 'a.xlsx', 'b.xlsx'])),
                         ['a.xlsx', 'a-2.xlsx', 'b.xlsx'])

    def test_rerun_overwrites_instead_of_copying(self):
        detail = {'fileInfoList': [{'fileName': '10.19-10.25骑手订单明细-商配送-1.xlsx',
                                    'fileUrl': 'https://s3/a'}]}

        def write_part(url, target):
            Path(target).write_bytes(b'x')
            return {'sheet': 's', 'rows': 1, 'columns': 12, 'headers': [], 'bytes': 1, 'sha256': 'x' * 64}

        with tempfile.TemporaryDirectory() as folder, \
                patch.object(lh, '_authenticated_session', return_value=Mock()), \
                patch.object(lh, 'find_notice', return_value={'id': 1}), \
                patch.object(lh, 'notice_detail', return_value=detail), \
                patch.object(lh, '_download', side_effect=write_part):
            lh.download_week(week=date(2026, 10, 21), output_dir=folder)
            lh.download_week(week=date(2026, 10, 21), output_dir=folder)
            downloaded = sorted(p.name for p in Path(folder).glob('*.xlsx'))
        self.assertEqual(downloaded, ['10.19-10.25骑手订单明细-商配送-1.xlsx'])


class OrchestrationTests(unittest.TestCase):
    def test_download_week_writes_manifest(self):
        detail = {'publishTime': '2026-10-26 10:00:00', 'publisher': '系统',
                  'fileInfoList': [
                      {'fileName': '10.19-10.25骑手订单明细-商配送-1.xlsx', 'fileUrl': 'https://s3/a'},
                      {'fileName': '10.19-10.25骑手订单明细-大网配送.xlsx', 'fileUrl': 'https://s3/b'}]}
        with tempfile.TemporaryDirectory() as folder, \
                patch.object(lh, '_authenticated_session', return_value=Mock()), \
                patch.object(lh, 'find_notice', return_value={'id': 22103323, 'publishTime': '2026-10-26 10:00:00'}), \
                patch.object(lh, 'notice_detail', return_value=detail), \
                patch.object(lh, '_download', return_value={'sheet': 's', 'rows': 3650, 'columns': 12,
                                                            'headers': [], 'bytes': 221178, 'sha256': 'x' * 64}):
            report = lh.download_week(week=date(2026, 10, 21), output_dir=folder)
            self.assertEqual(report['title'], '10.19-10.25骑手订单明细')
            self.assertEqual(len(report['files']), 1)
            manifest = json.loads((Path(folder) / 'manifest.json').read_text(encoding='utf-8'))
            self.assertEqual(manifest['noticeId'], 22103323)
            self.assertEqual(manifest['files'][0]['name'], '10.19-10.25骑手订单明细-商配送-1.xlsx')


if __name__ == '__main__':
    unittest.main()
