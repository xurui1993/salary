import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from openpyxl import Workbook
from company_reference import expected_with_blank_placeholders
from profile_fixtures import order_profile
from fengshen_bill import BillCollectionError
from fengshen_orders import validate_order_profile
from run_tests import local_host, offline_network
from check_live_environment import inspect

ROOT=Path(__file__).resolve().parents[2]


class ReliabilityBoundaryTests(unittest.TestCase):
    def test_synthetic_profile_cannot_pass_production_validation(self):
        p=order_profile()
        self.assertFalse(p['verified']);self.assertTrue(p['test_only'])
        with self.assertRaises(BillCollectionError):validate_order_profile(p)
        validate_order_profile(p,acceptance_only=True)

    def test_live_missing_configuration_is_blocked_without_login_or_exports(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as d:
            result=inspect(d)
        self.assertEqual(result['status'],'blocked');self.assertEqual(result['live_tests_run'],0)
        self.assertEqual(result['exports_submitted'],0);self.assertFalse(result['login_checked'])

    def test_offline_guard_blocks_external_hosts_without_connecting(self):
        import socket
        denied=[]
        with offline_network(denied):
            with self.assertRaisesRegex(RuntimeError,'external hosts'):socket.getaddrinfo('official.invalid',443)
        self.assertEqual(denied,['official.invalid']);self.assertTrue(local_host('127.0.0.1'));self.assertTrue(local_host('::1'))
        self.assertFalse(local_host('127.0.0.1.evil.invalid'));self.assertFalse(local_host('192.168.1.1'))

    def test_blank_reference_correction_is_exact_and_keeps_captured_reference_immutable(self):
        path=ROOT/'tests/fixtures/xiaoxiang_company_expected.json';raw=path.read_bytes();original=json.loads(raw);snapshot=copy.deepcopy(original)
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as d:
            files=[]
            for name in ['a.xlsx','b.xlsx']:
                p=Path(d)/name;b=Workbook();b.active.append(['a','b','c','d']);b.save(p);b.close();files.append(p)
            corrected=expected_with_blank_placeholders(original,files,raw)
            self.assertEqual(original,snapshot);self.assertEqual(path.read_bytes(),raw)
            for row in range(1,7):
                self.assertIsNone(corrected['payroll']['配送单']['rows'][row][13])
                corrected['payroll']['配送单']['rows'][row][13]='nan'
            self.assertEqual(corrected,original)
            with self.assertRaises(AssertionError):expected_with_blank_placeholders(original,files,raw+b' ')
            with self.assertRaises(AssertionError):expected_with_blank_placeholders(original,[],raw)
            b=Workbook();b.active.append(list(range(14)));b.save(files[0]);b.close()
            with self.assertRaises(AssertionError):expected_with_blank_placeholders(original,files,raw)
