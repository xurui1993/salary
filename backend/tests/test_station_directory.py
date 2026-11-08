import copy
import threading
import unittest
from unittest.mock import patch
from fastapi import HTTPException
import station_directory as directory


class DirectoryTests(unittest.TestCase):
    def test_payroll_loads_only_requested_city_without_starting_a_full_scan(self):
        with patch('deduction_stations.catalog',side_effect=self.provider) as calls,patch.object(directory,'snapshot',side_effect=AssertionError('must not scan all cities')):
            data=directory.ready_directory('fengshen','测试城')
            self.assertEqual(data['cities'][0]['station_count'],2);calls.assert_called_once_with('fengshen','测试城')
            directory.ready_directory('fengshen','测试城');self.assertEqual(calls.call_count,1)
    def test_refresh_preserves_verified_requested_city_until_replacement_is_ready(self):
        with patch('deduction_stations.catalog',side_effect=self.provider):self.scan()
        entered=threading.Event();release=threading.Event()
        def slow(platform,city=''):
            if city:entered.set();release.wait(3)
            return self.provider(platform,city)
        with patch('deduction_stations.catalog',side_effect=slow):
            directory.snapshot('fengshen',True);self.assertTrue(entered.wait(2))
            try:
                data=directory.ready_directory('fengshen','测试城');self.assertEqual(data['cities'][0]['status'],'ready');self.assertEqual(data['cities'][0]['station_count'],2)
            finally:release.set()
            worker=directory._workers.get('fengshen')
            if worker:worker.join(3)
    def test_requested_city_login_failure_is_actionable_and_does_not_fake_zero(self):
        from parttime_source import SourceError
        with patch('deduction_stations.catalog',side_effect=HTTPException(401,'login')):
            with self.assertRaisesRegex(SourceError,'登录'):directory.ready_directory('fengshen','测试城')
    def setUp(self):
        directory._states.clear();directory._workers.clear()
        self.version='account-a'
        self.patch=patch.object(directory,'_version',side_effect=lambda _:self.version);self.patch.start();self.addCleanup(self.patch.stop)
    def scan(self,platform='fengshen',refresh=False):
        directory.snapshot(platform,refresh)
        with directory._lock: worker=directory._workers.get(platform)
        if worker:worker.join(3);self.assertFalse(worker.is_alive())
        return directory.snapshot(platform)
    def provider(self,platform,city=''):
        return {'cities':[{'id':'001','name':'测试城'}], 'stations':[] if not city else [
            {'id':'0001','name':'同名','city':'测试城','city_id':'001','platform':platform},
            {'id':'0002','name':'同名','city':'测试城','city_id':'001','platform':platform}]}
    def test_count_uses_ids_not_names_and_reads_return_copies(self):
        with patch('deduction_stations.catalog',side_effect=self.provider) as calls:
            data=self.scan();self.assertEqual(data['cities'][0]['station_count'],2);self.assertEqual(calls.call_count,2)
            data['cities'][0]['station_count']=999
            self.assertEqual(directory.snapshot('fengshen')['cities'][0]['station_count'],2)
            self.assertEqual(calls.call_count,2)
    def test_expired_or_new_account_never_exposes_old_station_choices(self):
        with patch('deduction_stations.catalog',side_effect=self.provider):self.scan()
        gate=threading.Event()
        def slow(*args):gate.wait(2);return self.provider(*args)
        self.version='account-b'
        with patch('deduction_stations.catalog',side_effect=slow):
            data=directory.snapshot('fengshen');self.assertEqual(data['stations'],[]);self.assertEqual(data['session_version'],'account-b')
            gate.set()
            with directory._lock:worker=directory._workers.get('fengshen')
            if worker:worker.join(3)
    def test_auth_error_has_unknown_count_never_fake_zero(self):
        with patch('deduction_stations.catalog',side_effect=HTTPException(401,'login')):
            data=self.scan();self.assertEqual(data['status'],'unavailable');self.assertFalse(data['cities'])
    def test_same_account_refresh_does_not_append_duplicate_stations(self):
        with patch('deduction_stations.catalog',side_effect=self.provider):
            self.scan();data=self.scan(refresh=True);self.assertEqual(len(data['stations']),2)
    def test_lighthouse_catalog_is_one_request_and_preserves_zero_station_city(self):
        value={'cities':[{'id':'001','name':'甲'},{'id':'002','name':'乙'}], 'stations':[{'id':'1','name':'站','city':'甲','city_id':'001','platform':'xiaoxiang'}]}
        with patch('deduction_stations.catalog',return_value=value) as calls:
            data=self.scan('xiaoxiang');self.assertEqual(calls.call_count,1)
            self.assertEqual([c['station_count'] for c in data['cities']],[1,0])
    def test_xiaoxiang_pseudo_city_reads_whole_account_directory(self):
        value={'cities':[{'id':'001','name':'甲'},{'id':'002','name':'乙'}],
               'stations':[{'id':'1','name':'一站','city':'甲','city_id':'001','platform':'xiaoxiang'},
                           {'id':'2','name':'二站','city':'乙','city_id':'002','platform':'xiaoxiang'}]}
        with patch('deduction_stations.catalog',return_value=value) as calls:
            directory.ready_directory('xiaoxiang','小象')
            with directory._lock: worker=directory._workers.get('xiaoxiang')
            if worker: worker.join(3)
            data=directory.snapshot('xiaoxiang')
        calls.assert_called_once_with('xiaoxiang')
        self.assertEqual([c['status'] for c in data['cities']],['ready','ready'])
        self.assertEqual(len(data['stations']),2)
