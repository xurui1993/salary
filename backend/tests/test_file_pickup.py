import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from fastapi import HTTPException
from starlette.requests import Request

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import file_pickup as pickup


def request(method='GET', client='127.0.0.1'):
    return Request({
        'type': 'http', 'method': method, 'scheme': 'http', 'path': '/api/workbench/file-pickup',
        'query_string': b'', 'server': ('localhost', 3000), 'client': (client, 1234),
        'headers': [(b'host', b'localhost:3000'), (b'origin', b'http://localhost:3000'),
                    (b'content-type', b'application/json')],
    })


class UncTests(unittest.TestCase):
    def test_unc_accepts_ip_hostname_and_subfolders(self):
        self.assertEqual(pickup.parse_unc('\\\\192.168.1.20\\薪酬文件'), '\\\\192.168.1.20\\薪酬文件')
        self.assertEqual(pickup.parse_unc('//server/Share/2026'), '\\\\server\\Share\\2026')

    def test_unc_rejects_local_drives_and_traversal(self):
        for value in ['D:\\outputs', '\\\\host', '\\\\host\\..\\x', '\\\\host\\share\\a:b',
                      '\\\\host\\share \\sub', '\\\\\\share', '\\\\ho st\\share']:
            with self.assertRaises(HTTPException):
                pickup.parse_unc(value)

    def test_relative_path_rejects_traversal(self):
        self.assertEqual(pickup.clean_relative('a\\b'), 'a\\b')
        for value in ['..', '..\\x', 'a\\..\\b', 'a\x01b']:
            with self.assertRaises(HTTPException):
                pickup.clean_relative(value)

    def test_confined_target_blocks_escape(self):
        self.assertEqual(pickup.confined_target('\\\\host\\share', 'a\\b'), '\\\\host\\share\\a\\b')
        # UNC 的 .. 会被 ntpath 钳制在共享根；本地盘根仍须拦截越界
        self.assertEqual(pickup.confined_target('\\\\host\\share', '..\\x'), '\\\\host\\share\\x')
        with self.assertRaises(HTTPException):
            pickup.confined_target('C:\\outputs\\shared', '..\\Windows')


class SourceStoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        patches = [patch.object(pickup, 'ROOT', root), patch.object(pickup, 'CONFIG', root / 'sources.json'),
                   patch.object(pickup, '_probe', lambda _: True)]
        for item in patches:
            item.start()
            self.addCleanup(item.stop)

    def test_add_list_and_remove_round_trip(self):
        added = pickup.add_source({'name': '同事老王', 'unc': '\\\\192.168.1.20\\薪酬成品'}, request('POST'))
        self.assertTrue(added['source']['reachable'])
        rows = pickup.sources(request())['sources']
        self.assertEqual([row['name'] for row in rows], ['同事老王'])
        with self.assertRaises(HTTPException):
            pickup.add_source({'name': '重复', 'unc': '\\\\192.168.1.20\\薪酬成品'}, request('POST'))
        pickup.remove_source(rows[0]['id'], request('DELETE'))
        self.assertEqual(pickup.sources(request())['sources'], [])

    def test_add_requires_plain_name_and_valid_unc(self):
        with self.assertRaises(HTTPException):
            pickup.add_source({'name': '', 'unc': '\\\\host\\share'}, request('POST'))
        with self.assertRaises(HTTPException):
            pickup.add_source({'name': '同事', 'unc': 'D:\\outputs'}, request('POST'))


@unittest.skipUnless(os.name == 'nt', 'Windows path semantics are required to read local folders')
class SharedListingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        (self.base / '子目录').mkdir()
        (self.base / '结果.xlsx').write_bytes(b'demo')
        root = self.base.parent
        patches = [patch.object(pickup, 'ROOT', root / 'meta'),
                   patch.object(pickup, 'CONFIG', root / 'meta' / 'sources.json')]
        for item in patches:
            item.start()
            self.addCleanup(item.stop)
        pickup._save([{'id': 'local-source', 'name': '本机测试', 'unc': str(self.base), 'created': ''}])

    def test_list_orders_folders_first_and_scopes_to_root(self):
        value = pickup.list_shared('local-source', request(), '')
        self.assertEqual([row['name'] for row in value['entries']], ['子目录', '结果.xlsx'])
        self.assertTrue(value['entries'][0]['dir'])
        with self.assertRaises(HTTPException):
            pickup.list_shared('local-source', request(), '..')

    def test_download_rejects_directories_and_missing_files(self):
        with self.assertRaises(HTTPException):
            pickup.download_shared('local-source', request(), '子目录')
        with self.assertRaises(HTTPException):
            pickup.download_shared('local-source', request(), '缺失.xlsx')
        response = pickup.download_shared('local-source', request(), '结果.xlsx')
        self.assertEqual(Path(response.path).name, '结果.xlsx')


class ShareInfoTests(unittest.TestCase):
    def test_loopback_reports_share_status_and_lan_urls(self):
        with patch.object(pickup, 'bootstrap_allowed', lambda _: True), \
                patch('download_jobs.configured_output_root', lambda: Path(r'D:\outputs\fengshen_downloads')), \
                patch.object(pickup, '_smb_shares', lambda: [{'name': '薪酬成品', 'path': r'D:\outputs\fengshen_downloads'}]), \
                patch.object(pickup, '_lan_urls', lambda port: [f'http://192.168.1.68:{port}']):
            value = pickup.share_info(request())
        self.assertTrue(value['local'])
        self.assertTrue(value['shared'])
        self.assertEqual(value['share_name'], '薪酬成品')
        self.assertEqual(value['lan_urls'], ['http://192.168.1.68:3000'])

    def test_remote_client_gets_no_host_paths(self):
        with patch.object(pickup, 'bootstrap_allowed', lambda _: False), \
                patch('download_jobs.configured_output_root', lambda: Path(r'D:\outputs')):
            value = pickup.share_info(request(client='192.168.1.20'))
        self.assertFalse(value['local'])
        self.assertEqual(value['path'], '')
        self.assertEqual(value['lan_urls'], [])