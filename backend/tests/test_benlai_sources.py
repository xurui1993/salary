import hashlib
import sys
from pathlib import Path
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import Mock

from openpyxl import Workbook

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import benlai_sources
from fengshen_bill import BillCollectionError


def response(payload, status=200):
    return SimpleNamespace(status_code=status, json=lambda: payload,
                           headers={'Content-Type': 'application/json'}, text='')


class BenlaiSourcesTests(unittest.TestCase):
    def test_signing_cities_keeps_visible_custom_entries_only(self):
        payload = {'code': 0, 'data': [
            {'cityName': '泉州市', 'cityCode': '350500', 'isDefault': False, 'isvalid': True},
            {'cityName': '泉州', 'cityCode': '350500', 'isDefault': False, 'isvalid': True},
            {'cityName': '深圳市', 'cityCode': '440300', 'isDefault': True, 'isvalid': True},
            {'cityName': ' ', 'cityCode': '000000', 'isDefault': False, 'isvalid': True},
            {'cityName': '总部', 'isDefault': True, 'isvalid': True},
        ]}
        session = Mock(); session.get.return_value = response(payload)
        links = benlai_sources.signing_cities(session)
        self.assertEqual(links['cities'], ['泉州'])
        self.assertEqual([entry['cityCode'] for entry in links['entries']], ['350500', '350500', '000000'])
        self.assertTrue(links['template_enabled'])

    def test_signing_cities_without_custom_entries_falls_back_to_shangyi(self):
        session = Mock(); session.get.return_value = response({'code': 0, 'data': [
            {'cityName': '深圳市', 'isDefault': True}]})
        self.assertEqual(benlai_sources.signing_cities(session)['cities'], [])

    def test_signing_cities_auth_and_structure_errors_are_explicit(self):
        session = Mock()
        session.get.return_value = response({}, status=401)
        with self.assertRaises(BillCollectionError) as error:
            benlai_sources.signing_cities(session)
        self.assertIn('登录', str(error.exception))
        session.get.return_value = response({'code': 500, 'msg': '权限不足'})
        with self.assertRaises(BillCollectionError) as error:
            benlai_sources.signing_cities(session)
        self.assertIn('权限不足', str(error.exception))
        session.get.return_value = response({'code': 0, 'data': {'unexpected': True}})
        with self.assertRaises(BillCollectionError):
            benlai_sources.signing_cities(session)

    def test_validate_employees_counts_signed_text_and_numeric_status(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / '本来人力灵工全量.xlsx'
            book = Workbook(); sheet = book.active
            sheet.append(['姓名', '身份证号', '签约城市', '签约状态', '手机号'])
            sheet.append(['甲', '110000000000000001', '泉州市', '已签约', '13800000001'])
            sheet.append(['乙', '110000000000000002', '深圳市', 2, '13800000002'])
            sheet.append(['丙', '110000000000000003', '深圳市', '未签约', ''])
            book.save(path); book.close()
            proof = benlai_sources.validate_employees(path)
            self.assertEqual(proof['rows'], 3)
            self.assertEqual(proof['signed_rows'], 2)
            self.assertEqual(proof['cities'], {'泉州': 1, '深圳': 2})
            self.assertEqual(proof['identity_masked'], 0)
            self.assertTrue(proof['has_phone'])
            self.assertEqual(proof['sha256'], hashlib.sha256(path.read_bytes()).hexdigest())
            self.assertEqual(proof['bytes'], path.stat().st_size)

    def test_validate_employees_rejects_numeric_identity(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / '本来人力灵工全量.xlsx'
            book = Workbook(); sheet = book.active
            sheet.append(['姓名', '身份证号', '签约城市', '签约状态'])
            sheet.append(['甲', 110000000000000001, '泉州', '已签约'])
            book.save(path); book.close()
            with self.assertRaises(BillCollectionError) as error:
                benlai_sources.validate_employees(path)
            self.assertIn('文本', str(error.exception))


if __name__ == '__main__':
    unittest.main()