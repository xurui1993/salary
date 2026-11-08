"""Synthetic station directories; no live logins, exports or personnel queries."""
from contextlib import nullcontext
from pathlib import Path
import sys
import unittest
from unittest.mock import MagicMock, Mock, patch

from fastapi import HTTPException

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import deduction_stations as stations
from fengshen_http import AGENCIES_URL, TEAMS_URL, HttpTransportError


def directory(name='站点'):
    return {'cities': [{'id':'020','name':'测试市'}],
            'stations':[{'id':'0001','name':name,'city':'测试市','city_id':'020','platform':'fengshen'}],
            'scope_note':'合成范围','warnings':[]}


class Client:
    def __init__(self):
        self.current = '010'
        self.switches = []
        self.closed = False
        self.fail = False

    def request_json(self, method, url, **kwargs):
        if url == AGENCIES_URL:
            return {'data':[{'agencyId':'010','agencyCityName':'原城市','agencySubTypeName':'物流合作商'},
                            {'agencyId':'020','agencyCityName':'测试市','agencySubTypeName':'物流合作商'}]}
        assert url == TEAMS_URL
        assert method == 'POST' and kwargs == {'body':{}}
        if self.fail:
            raise HttpTransportError('synthetic secret')
        return {'result':{'data':[{'id':'0001','agencyId':'020','team_name':'同名站点'},
                                  {'id':'0002','agencyId':'020','team_name':'同名站点'},
                                  {'id':'9999','agencyId':'010','team_name':'其他城市'}]}}

    def identity(self):
        return {'agencyId':self.current}

    def select_city(self, city):
        self.current = city
        self.switches.append(city)

    def assert_city(self, city):
        assert self.current == city

    def close(self):
        self.closed = True


class CatalogTests(unittest.TestCase):
    def test_separation_reads_same_city_service_group_and_restores_original(self):
        client=Client();original=client.request_json
        def query(method,url,**kwargs):
            if url==AGENCIES_URL:
                data=original(method,url,**kwargs);data['data'].append({'agencyId':'030','agencyCityName':'测试市','agencySubTypeName':'物流服务商'});return data
            if client.current=='030':return {'result':{'data':[{'id':'003','agencyId':'030','team_name':'测试(取分离)'}]}}
            return original(method,url,**kwargs)
        client.request_json=query
        with patch.object(stations,'_fengshen_client',return_value=client):result=stations.catalog('fengshen','020',True,True)
        split=next(s for s in result['stations'] if s.get('separation'))
        self.assertEqual((split['city_id'],split['agency_id'],split['id']),('020','030','003'))
        self.assertEqual(client.current,'010');self.assertTrue(client.closed)

    def setUp(self):
        stations._cache.clear()
        stations._versions.clear()
        for name, replacement in [('_operation', lambda _:nullcontext()),
                                  ('_collection', lambda:nullcontext()),
                                  ('_status', lambda _:{'saved':True,'state':'ready'}),
                                  ('_version', lambda _:'version-1')]:
            mocked = patch.object(stations,name,replacement)
            mocked.start()
            self.addCleanup(mocked.stop)

    def test_city_choices_do_not_switch_city_or_collect_personnel(self):
        client = Client()
        with patch.object(stations,'_fengshen_client',return_value=client):
            result = stations.catalog('fengshen')
        self.assertEqual(len(result['cities']),2)
        self.assertEqual(result['stations'],[])
        self.assertEqual(client.switches,[])
        self.assertTrue(client.closed)

    def test_station_ids_are_strings_same_names_are_distinct_and_city_is_restored(self):
        client = Client()
        with patch.object(stations,'_fengshen_client',return_value=client):
            result = stations.catalog('fengshen','020')
        self.assertEqual([item['id'] for item in result['stations']],['0001','0002'])
        self.assertTrue(all(item['city_id']=='020' for item in result['stations']))
        self.assertEqual(client.switches,['020','010'])
        self.assertEqual(client.current,'010')
        self.assertTrue(client.closed)

    def test_platform_error_keeps_original_context_and_sanitizes_error(self):
        client = Client()
        client.fail = True
        with patch.object(stations,'_fengshen_client',return_value=client), self.assertRaises(HTTPException) as caught:
            stations.catalog('fengshen','020')
        self.assertEqual(caught.exception.status_code,502)
        self.assertNotIn('secret',caught.exception.detail)
        self.assertEqual(client.current,'010')
        self.assertTrue(client.closed)

    def test_failed_context_restore_is_explicit_and_does_not_cache_success(self):
        client = Client()
        original = client.select_city
        def select(city):
            if city == '010':
                raise HttpTransportError('synthetic failure')
            original(city)
        client.select_city = select
        with patch.object(stations,'_fengshen_client',return_value=client), self.assertRaises(HTTPException) as caught:
            stations.catalog('fengshen','020')
        self.assertEqual(caught.exception.status_code,409)
        self.assertIn('原城市恢复尚未确认',caught.exception.detail)
        self.assertEqual(stations._cache,{})
        self.assertTrue(client.closed)

    def test_cache_is_bound_to_session_and_explicit_refresh_requeries(self):
        provider = Mock(side_effect=[directory('旧站点'),directory('新站点'),directory('切换账号')])
        with patch.object(stations,'_fengshen',provider):
            first=stations.catalog('fengshen','020')
            cached=stations.catalog('fengshen','020')
            self.assertFalse(first['cached'])
            self.assertTrue(cached['cached'])
            fresh=stations.catalog('fengshen','020',True)
            self.assertEqual(fresh['stations'][0]['name'],'新站点')
            with patch.object(stations,'_version',return_value='version-2'):
                switched=stations.catalog('fengshen','020')
            self.assertFalse(switched['cached'])
            self.assertEqual(switched['stations'][0]['name'],'切换账号')
        self.assertEqual(provider.call_count,3)

    def test_auth_busy_or_expired_never_returns_cached_choices(self):
        with patch.object(stations,'_fengshen',return_value=directory()):
            stations.catalog('fengshen','020')
        for status,expected in [({'saved':False},401),({'saved':True,'state':'waiting_login'},409),
                                ({'saved':True,'state':'login_required'},401)]:
            with self.subTest(status=status), patch.object(stations,'_status',return_value=status), self.assertRaises(HTTPException) as caught:
                stations.catalog('fengshen','020')
            self.assertEqual(caught.exception.status_code,expected)

    def test_session_change_during_query_is_rejected_without_cache(self):
        with patch.object(stations,'_version',side_effect=['v1','v2']), patch.object(stations,'_fengshen',return_value=directory()), self.assertRaises(HTTPException) as caught:
            stations.catalog('fengshen','020')
        self.assertEqual(caught.exception.status_code,409)
        self.assertEqual(stations._cache,{})

    def test_lighthouse_scope_is_explicit_and_names_are_not_guessed(self):
        rows=[{'siteId':'001','poiId':10001954,'siteName':'灯塔站','cityName':'城市甲','cityId':'021',
               'managementCityName':'管理甲','managementCityId':'901'},
              {'siteId':'002','siteName':'灯塔站','cityName':'城市乙','cityId':'022'},
              {'siteId':'003'}]
        with patch.object(stations,'_station_rows',return_value=rows):
            result=stations.catalog('xiaoxiang')
            filtered=stations.catalog('xiaoxiang','城市乙')
        self.assertEqual(sorted(item['id'] for item in result['stations']),['001','002'])
        self.assertEqual([item['id'] for item in filtered['stations']],['002'])
        self.assertEqual(filtered['stations'][0]['city_id'],'022')
        city_one=next(item for item in result['stations'] if item['id']=='001')
        self.assertEqual(city_one['management_city'],'管理甲')
        self.assertEqual(city_one['city'],'城市甲')
        self.assertEqual(city_one['poi_id'],'10001954')
        self.assertEqual(next(item for item in result['stations'] if item['id']=='002')['poi_id'],'')
        self.assertEqual({item['id']:item['name'] for item in result['cities']},{'021':'城市甲','022':'城市乙'})
        self.assertIn('权限内',result['scope_note'])
        self.assertNotIn('31天',result['scope_note'])
        self.assertTrue(any('1 个站点' in warning for warning in result['warnings']))

    def test_lighthouse_missing_names_does_not_fabricate_station_names(self):
        with patch.object(stations,'_station_rows',return_value=[{'siteId':'1'}]), self.assertRaises(HTTPException) as caught:
            stations.catalog('xiaoxiang')
        self.assertEqual(caught.exception.status_code,502)

    def test_lighthouse_partial_board_login_does_not_block_official_station_directory(self):
        status={'saved':True,'state':'partial','stages':{'lighthouse':'ready','board':'error'}}
        rows=[{'siteId':'001','siteName':'无近期业务站点','cityId':'002','cityName':'城市'}]
        with patch.object(stations,'_status',return_value=status), patch.object(stations,'_station_rows',return_value=rows):
            result=stations.catalog('xiaoxiang')
        self.assertEqual(result['stations'][0]['name'],'无近期业务站点')

    def test_lighthouse_empty_directory_explains_scope_and_never_invents_stations(self):
        with patch.object(stations,'_station_rows',return_value=[]):
            result=stations.catalog('xiaoxiang')
        self.assertEqual(result['stations'],[])
        self.assertEqual(result['cities'],[])
        self.assertTrue(any('不代表平台没有站点' in warning for warning in result['warnings']))

    def test_cache_expiry_and_returned_value_mutations_do_not_change_source(self):
        provider=Mock(return_value=directory())
        with patch.object(stations,'_fengshen',provider), patch.object(stations.time,'monotonic',side_effect=[10,11,400,401]):
            first=stations.catalog('fengshen','020')
            first['stations'][0]['name']='本地篡改'
            cached=stations.catalog('fengshen','020')
            self.assertNotEqual(cached['stations'][0]['name'],'本地篡改')
            fresh=stations.catalog('fengshen','020')
        self.assertFalse(fresh['cached'])
        self.assertEqual(provider.call_count,2)

    def test_malformed_or_duplicate_station_identifiers_fail_closed(self):
        for rows in ([{'id':1.2,'agencyId':'020','team_name':'站'}],
                     [{'id':'1','agencyId':'020','team_name':'站'},{'id':'1','agencyId':'020','team_name':'站'}]):
            with self.subTest(rows=rows),self.assertRaises(HTTPException):
                stations._fengshen_stations({'result':{'data':rows}},{'id':'020','name':'测试市'})
        with self.assertRaises(HTTPException):
            stations._fengshen_stations({'result':None},{'id':'020','name':'测试市'})


class LighthouseProtocolTests(unittest.TestCase):
    """Official static selector contract; synthetic sessions never reach the network."""
    def setUp(self):
        CatalogTests.setUp(self)
        self.state={'cookies':[{'name':'synthetic','value':'synthetic','domain':'.meituan.com'}],
                    'origins':[{'origin':'https://maicaipeisong.meituan.com','localStorage':[
                        {'name':'rss_supplier_id','value':'000106'},
                        {'name':'rss_supplier_operator_mis','value':'synthetic.operator'}]}]}
        self.response=Mock(status_code=200,url='https://maicaipeisong.meituan.com/api/s/peisong/supplier/dept/list',headers={'content-type':'application/json'})
        self.response.json.return_value={'code':0,'data':[
            {'siteId':'001','siteName':'静态目录站','cityId':'021','cityName':'城市甲'}]}
        self.session=MagicMock()
        self.session.headers={}
        self.session.__enter__.return_value=self.session
        self.post=self.session.post
        self.post.return_value=self.response
        for name,replacement in [('load_state',Mock(return_value=self.state)),
                                 ('session_from_state',Mock(return_value=self.session))]:
            mocked=patch('xiaoxiang_lighthouse.'+name,replacement)
            mocked.start()
            self.addCleanup(mocked.stop)

    def test_selector_uses_only_verified_read_only_endpoint_and_active_supplier(self):
        result=stations.catalog('xiaoxiang')
        self.assertEqual(len(result['stations']),1)
        self.post.assert_called_once_with(
            'https://maicaipeisong.meituan.com/api/s/peisong/supplier/dept/list',
            json={'needManagementCityInfo':True,'supplierId':'000106','checkSupplierAccess':True,'operator':'synthetic.operator'},
            timeout=(3,8))
        self.assertEqual(self.session.headers['mall-login-type'],'passport')
        self.assertTrue(self.session.__exit__.called)

    def test_missing_supplier_context_never_uses_default_supplier(self):
        self.state['origins']=[]
        with self.assertRaises(HTTPException) as caught:
            stations.catalog('xiaoxiang')
        self.assertEqual(caught.exception.status_code,401)
        self.post.assert_not_called()

    def test_authentication_and_permission_failures_are_distinct_and_never_cached(self):
        for http_status,body,expected in [(401,{},401),(403,{},403),(200,{'code':5},401),
                                          (200,{'code':7,'msg':'synthetic secret'},502)]:
            with self.subTest(http_status=http_status,body=body):
                self.response.status_code=http_status
                self.response.json.return_value=body
                with self.assertRaises(HTTPException) as caught:
                    stations.catalog('xiaoxiang',refresh=True)
                self.assertEqual(caught.exception.status_code,expected)
                self.assertNotIn('secret',caught.exception.detail)
                self.assertEqual(stations._cache,{})

    def test_empty_array_and_malformed_payload_are_not_confused(self):
        self.response.json.return_value={'code':0,'data':[]}
        result=stations.catalog('xiaoxiang')
        self.assertEqual(result['stations'],[])
        for body in ({'code':0,'data':{}}, {'code':0,'data':[None]}, [], None):
            with self.subTest(body=body):
                self.response.json.return_value=body
                with self.assertRaises(HTTPException) as caught:
                    stations.catalog('xiaoxiang',refresh=True)
                self.assertEqual(caught.exception.status_code,502)


class CollectionLockTests(unittest.TestCase):
    def test_busy_collection_fails_immediately(self):
        from parttime_source import COLLECTION_LOCK
        self.assertTrue(COLLECTION_LOCK.acquire(blocking=False))
        try:
            with self.assertRaises(HTTPException) as caught:
                with stations._collection():
                    pass
            self.assertEqual(caught.exception.status_code,409)
        finally:
            COLLECTION_LOCK.release()


if __name__=='__main__':
    unittest.main()
