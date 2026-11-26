"""新蓝橙真实城市/站点目录：接口契约来自平台前端脚本，城市接口返回 ID 列表。"""
import sys
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parents[1]))

import lanorange_mdr_catalog as catalog
import lanorange_mdr_directory as directory


class FakeSession:
    def close(self):
        pass


def fake_directory(project_cities=None):
    project_cities = project_cities or [{'id': 9, 'areaName': '广州市'}]

    def respond(session, path, params, log=None):
        if path == '/admin/base/area/cities':
            return [{'id': 9, 'areaName': '广州市'}, {'id': 10, 'areaName': '深圳市'}]
        if path == '/admin/base/project/list':
            return [{'projectCode': 'P1', 'projectName': '项目一'}]
        # 平台真实返回：授权城市 ID 列表，而不是城市对象列表
        if path == '/admin/base/project/cities':
            return [9, 10]
        if path == '/admin/base/project/cities-by-project':
            return project_cities if dict(params).get('projectCode') == 'P1' else []
        if path == '/admin/base/point/list':
            if dict(params).get('cityId') == '9':
                return [{'pointCode': 'S1', 'pointName': '天河站'},
                        {'pointCode': 'S2', 'pointName': '越秀站'}]
            return []
        return []

    return respond


class FetchTests(unittest.TestCase):
    def run_fetch(self, respond):
        with patch.object(directory, '_request', side_effect=respond), \
                patch('binding_source_auth.client', return_value=FakeSession()), \
                patch('binding_source_auth.identity', return_value={}):
            return directory._fetch('v1')

    def test_id_list_city_response_is_resolved_with_area_names(self):
        data = self.run_fetch(fake_directory())
        names = {city['name'] for city in data['cities']}
        self.assertEqual(names, {'广州市', '深圳市'})
        cities = {city['id']: city for city in data['cities']}
        self.assertEqual(cities['9']['project_code'], 'P1')
        self.assertEqual(cities['10']['project_code'], '')
        self.assertEqual(len(data['stations']), 2)
        self.assertTrue(all(station['city_id'] == '9' for station in data['stations']))
        row = catalog.match_city(
            [{'id': c['id'], 'cityName': c['name'], 'projectCode': c['project_code']}
             for c in data['cities']], '深圳')
        self.assertIsNotNone(row)
        self.assertEqual(catalog.city_identity(row), ('10', None))

    def test_authorization_only_contains_what_platform_reports(self):
        respond = fake_directory(project_cities=[])
        data = self.run_fetch(respond)
        # cities-by-project 为空时仍以授权 ID + 参考表为准，不会凭空生成城市
        self.assertEqual({city['name'] for city in data['cities']}, {'广州市', '深圳市'})

    def test_cached_names_normalizes_city_suffix(self):
        with directory._lock:
            directory._cache.clear()
            directory._cache['v1'] = {'at': time.monotonic(), 'data': {
                'cities': [{'id': '9', 'name': '广州市', 'project_code': 'P1'},
                           {'id': '10', 'name': '深圳', 'project_code': ''}],
                'stations': [], 'projects': [],
            }}
        with patch('platform_auth_control.version', return_value='v1'):
            self.assertEqual(directory.cached_names(), {'广州', '深圳'})
        with patch('platform_auth_control.version', return_value='v2'):
            self.assertIsNone(directory.cached_names())


class StationDirectoryTests(unittest.TestCase):
    def setUp(self):
        import station_directory
        self.module = station_directory
        with self.module._lock:
            self.module._states.clear()
            self.module._workers.clear()

    def test_snapshot_exposes_real_mdr_city_and_station_counts(self):
        payload = {
            'cities': [{'id': '9', 'name': '广州市', 'project_code': 'P1'},
                       {'id': '10', 'name': '深圳', 'project_code': ''}],
            'stations': [
                {'id': 'S1', 'name': '天河站', 'city': '广州市', 'city_id': '9', 'project_code': 'P1'},
                {'id': 'S2', 'name': '越秀站', 'city': '广州市', 'city_id': '9', 'project_code': 'P1'},
                {'id': 'S3', 'name': '南山站', 'city': '深圳', 'city_id': '10', 'project_code': ''},
            ],
            'projects': [{'code': 'P1', 'name': '项目一'}],
        }
        with patch('platform_auth_control.version', return_value='v1'), \
                patch('lanorange_mdr_directory.load', return_value=payload):
            data = self.module.snapshot('lanorange_mdr', refresh=True)
            deadline = time.monotonic() + 5
            while data['status'] == 'loading' and time.monotonic() < deadline:
                time.sleep(0.05)
                data = self.module.snapshot('lanorange_mdr')
        self.assertEqual(data['status'], 'ready')
        counts = {city['name']: city['station_count'] for city in data['cities']}
        self.assertEqual(counts, {'广州市': 2, '深圳': 1})
        self.assertEqual({station['name'] for station in data['stations']},
                         {'天河站', '越秀站', '南山站'})


if __name__ == '__main__':
    unittest.main()