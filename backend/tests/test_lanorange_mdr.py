import contextlib
import datetime as dt
import io
import json
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parents[1]))
import auth_preflight
import download_service
import lanorange_mdr_catalog as catalog
import lanorange_mdr_download as downloader


def xlsx_bytes():
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w') as archive:
        archive.writestr('[Content_Types].xml', '<Types/>')
        archive.writestr('xl/workbook.xml', '<workbook/>')
        archive.writestr('xl/worksheets/sheet1.xml', '<sheetData/>')
    return buffer.getvalue()


class FakeResponse:
    def __init__(self, status=200, payload=None, content=b'', headers=None):
        self.status_code = status
        self._payload = payload
        self.content = content
        self.headers = headers or {'Content-Type': 'application/octet-stream'}
        self.text = ''

    def json(self):
        if self._payload is None:
            raise ValueError()
        return self._payload

    def iter_content(self, size):
        yield self.content

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


class FakeSession:
    def __init__(self):
        self.calls = []

    def get(self, url, params=None, stream=False, timeout=None, allow_redirects=True):
        self.calls.append((url, list(params or []), stream))
        if url.endswith('/page'):
            return FakeResponse(payload={'code': 200, 'data': {'list': [], 'total': 2}})
        return FakeResponse(content=xlsx_bytes())


class CatalogTests(unittest.TestCase):
    def test_params_cover_archive_price_and_commission(self):
        params = dict(catalog.build_params('lcmdr_archive', city_id='9', project_code='P1'))
        self.assertEqual(params['postType'], 'rider')
        self.assertEqual(params['cityId'], '9')
        self.assertEqual(params['projectCode'], 'P1')
        price = catalog.build_params('lcmdr_part_price', months=['2026-10', '2026-11'], city_id='9')
        self.assertIn(('startDate', '2026-10-01'), price)
        self.assertIn(('endDate', '2026-11-30'), price)
        self.assertTrue(any(key == 'cityIds' and value == '9' for key, value in price))
        commission = dict(catalog.build_params('lcmdr_commission_proxy', months=['2026-11'], city_id='9'))
        self.assertEqual(commission['proxyMonth'], '2026-11')

    def test_scope_validation_requires_contiguous_price_months_and_single_commission_month(self):
        catalog.validate_scope('lcmdr_part_price', ['2026-10', '2026-11'])
        with self.assertRaises(ValueError):
            catalog.validate_scope('lcmdr_part_price', ['2026-09', '2026-11'])
        with self.assertRaises(ValueError):
            catalog.validate_scope('lcmdr_commission_proxy', ['2026-10', '2026-11'])
        with self.assertRaises(ValueError):
            catalog.validate_scope('lcmdr_leave', ['2026-11'])

    def test_city_matching_normalizes_suffix(self):
        rows = [{'id': 9, 'cityName': '广州市', 'projectCode': 'P1'}]
        row = catalog.match_city(rows, '广州')
        self.assertEqual(catalog.city_identity(row), ('9', 'P1'))


class AuthTests(unittest.TestCase):
    def test_client_uses_bearer_token_from_local_storage(self):
        import binding_source_auth as auth
        state = {'cookies': [], 'origins': [{
            'origin': 'https://mdr.lanchengsz.cn',
            'localStorage': [{'name': 'hr_admin_token', 'value': 'synthetic-token'}],
        }]}
        session = auth.client('lanorange_mdr', token='cookie-marker', state=state)
        try:
            self.assertEqual(session.headers['Authorization'], 'Bearer synthetic-token')
        finally:
            session.close()

    def test_trusted_hosts_include_new_system_and_dingtalk(self):
        from desktop_auth_page import trusted
        self.assertTrue(trusted('lanorange_mdr', 'https://mdr.lanchengsz.cn/login'))
        self.assertTrue(trusted('lanorange_mdr', 'https://login.dingtalk.com/oauth2/auth'))
        self.assertFalse(trusted('lanorange_mdr', 'https://example.com/login'))


class IntentTests(unittest.TestCase):
    def test_mdr_task_requires_city_and_keeps_months(self):
        payload = {'task_kind': 'download', 'datasets': ['lcmdr_leave', 'lcmdr_part_price'],
                   'cities': ['广州'], 'start': '2026-11-01', 'end': '2026-11-30',
                   'lanorange_months': ['2026-11']}
        config = download_service.validate_request(payload, today=dt.date(2026, 11, 26))
        self.assertEqual(config['cities'], ['广州'])
        self.assertEqual(config['lanorange_months'], ['2026-11'])
        self.assertFalse(config.get('lanorange_full_delivery'))
        with self.assertRaises(download_service.ValidationError):
            download_service.validate_request({**payload, 'cities': []}, today=dt.date(2026, 11, 26))
        with self.assertRaises(download_service.ValidationError):
            download_service.validate_request({**payload, 'cities': ['不存在']}, today=dt.date(2026, 11, 26))

    def test_options_and_preflight_expose_new_platform(self):
        options = download_service.get_options()
        item = next(value for value in options['datasets'] if value['id'] == 'lcmdr_leave')
        self.assertEqual(item['group'], 'lanorange_mdr')
        self.assertEqual(item['scope'], 'city')
        self.assertEqual(auth_preflight.platforms_for_datasets(['lcmdr_leave']), {'lanorange_mdr'})


class DownloadTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=Path(__file__).parent)
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name) / '骑手请假'

    @contextlib.contextmanager
    def fake_auth(self, source, log, cancelled):
        session = FakeSession()
        yield session

    def test_collect_verifies_integrity_and_records_total(self):
        with patch.object(downloader, 'authenticated', self.fake_auth):
            path = downloader.collect('lcmdr_leave', self.directory, lambda *args: None,
                                      type('C', (), {'is_set': lambda self: False})(),
                                      city='广州', city_id='9', project_code='P1')
        self.assertTrue(path.is_file())
        receipt = json.loads((self.directory / 'source_receipt.json').read_text(encoding='utf-8'))
        self.assertEqual(receipt['status'], 'validated')
        self.assertEqual(receipt['query_total'], 2)
        self.assertEqual(receipt['city_id'], '9')
        self.assertEqual(receipt['validation'], 'integrity')

    def test_verify_rejects_non_workbook(self):
        path = self.directory / 'broken.xlsx'
        path.parent.mkdir(parents=True)
        path.write_bytes(b'not a workbook')
        cancelled = type('C', (), {'is_set': lambda self: False})()
        with self.assertRaises(Exception):
            downloader.verify_file(path, cancelled)


if __name__ == '__main__':
    unittest.main()