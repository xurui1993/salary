"""新蓝橙后台真实城市与站点目录。

接口契约取自平台前端脚本（mdr.lanchengsz.cn）：
- GET /admin/base/area/cities                       全量城市参考表（id + areaName）
- GET /admin/base/project/list                      当前账号可见项目（projectCode + projectName）
- GET /admin/base/project/cities                    账号已授权城市 ID 列表
- GET /admin/base/project/cities-by-project?projectCode=  项目下城市（id + areaName）
- GET /admin/base/point/list?cityId=&projectCode=   城市下站点（pointCode + pointName）

只做只读查询；不主动打开登录窗口，会话失效时提示先完成登录。
"""
import copy
import threading
import time

TTL = 300
_lock = threading.RLock()
_cache = {}
_CACHE_LIMIT = 3


def _rows(value):
    if isinstance(value, list):
        return value
    if isinstance(value, dict):
        for key in ('list', 'rows', 'records'):
            rows = value.get(key)
            if isinstance(rows, list):
                return rows
    return []


def _text(value):
    return str(value).strip() if value is not None else ''


def _identifier(value):
    text = _text(value)
    return text if 0 < len(text) <= 40 else None


def _city_id(row):
    if not isinstance(row, dict):
        return None
    return _identifier(row.get('id') if row.get('id') is not None else row.get('cityId'))


def _city_name(row):
    if not isinstance(row, dict):
        return ''
    return _text(row.get('areaName') or row.get('cityName') or row.get('name'))


def _point_code(row):
    if not isinstance(row, dict):
        return None
    return _identifier(row.get('pointCode') or row.get('siteId') or row.get('code')
                       or row.get('pointId') or row.get('id'))


def _point_name(row):
    if not isinstance(row, dict):
        return ''
    return _text(row.get('pointName') or row.get('siteName') or row.get('name'))


def normalize_name(value):
    return _text(value).removesuffix('市').strip()


def _request(session, path, params, log=None):
    from lanorange_mdr_download import _json
    return _json(session, path, params, log)


def _fetch(version, log=None, cancelled=None):
    from binding_source_auth import client, identity, SourceAuthenticationRequired
    session = client('lanorange_mdr')
    try:
        try:
            identity('lanorange_mdr', session)
        except SourceAuthenticationRequired:
            raise
        reference = {}
        for row in _rows(_request(session, '/admin/base/area/cities', [], log)):
            city_id = _city_id(row)
            name = _city_name(row)
            if city_id and name and city_id not in reference:
                reference[city_id] = name
        projects = []
        for row in _rows(_request(session, '/admin/base/project/list', [], log)):
            code = _identifier(row.get('projectCode')) if isinstance(row, dict) else None
            if code:
                projects.append({'code': code, 'name': _text(row.get('projectName')) or code})
        cities = {}

        def add_city(city_id, name='', project_code=''):
            if not city_id:
                return
            entry = cities.setdefault(city_id, {
                'id': city_id,
                'name': name or reference.get(city_id) or city_id,
                'projects': set(),
            })
            if name and entry['name'] == city_id:
                entry['name'] = name
            if project_code:
                entry['projects'].add(project_code)

        for row in _rows(_request(session, '/admin/base/project/cities', [], log)):
            if isinstance(row, dict):
                add_city(_city_id(row), _city_name(row))
            else:
                add_city(_identifier(row), reference.get(_identifier(row)) or '')
        for project in projects:
            rows = _rows(_request(session, '/admin/base/project/cities-by-project',
                                  [('projectCode', project['code'])], log))
            for row in rows:
                if isinstance(row, dict):
                    add_city(_city_id(row), _city_name(row), project['code'])
                else:
                    city_id = _identifier(row)
                    add_city(city_id, reference.get(city_id) or '', project['code'])
        result_cities = []
        for entry in cities.values():
            project_codes = sorted(entry.pop('projects'))
            result_cities.append({
                'id': entry['id'],
                'name': entry['name'],
                'project_code': project_codes[0] if len(project_codes) == 1 else '',
            })
        result_cities.sort(key=lambda city: (city['name'], city['id']))

        stations = []
        seen = set()
        for city in result_cities:
            params = [('cityId', city['id'])]
            if city['project_code']:
                params.append(('projectCode', city['project_code']))
            try:
                rows = _rows(_request(session, '/admin/base/point/list', params, log))
            except SourceAuthenticationRequired:
                raise
            except Exception:
                continue
            for row in rows:
                name, code = _point_name(row), _point_code(row)
                key = (city['id'], code or name)
                if not name or key in seen:
                    continue
                seen.add(key)
                stations.append({'id': code or name, 'name': name, 'city': city['name'],
                                 'city_id': city['id'], 'project_code': city['project_code']})
        stations.sort(key=lambda station: (station['city'], station['name'], station['id']))
        return {'cities': result_cities, 'stations': stations, 'projects': projects}
    finally:
        session.close()


def load(log=None, cancelled=None, *, force=False, expected_version=None):
    from platform_auth_control import version
    current = version('lanorange_mdr')
    if expected_version is not None and current != expected_version:
        raise ValueError('平台账号已变化，请重新读取城市与站点目录')
    with _lock:
        entry = _cache.get(current)
        if entry and not force and time.monotonic() - entry['at'] < TTL:
            return copy.deepcopy(entry['data'])
    data = _fetch(current, log, cancelled)
    from platform_auth_control import version as current_version
    with _lock:
        if current_version('lanorange_mdr') == current:
            _cache[current] = {'at': time.monotonic(), 'data': data}
            for key in list(_cache)[:-_CACHE_LIMIT]:
                _cache.pop(key, None)
    return copy.deepcopy(data)


def platform_rows(log=None, cancelled=None):
    """下载匹配使用的城市行；每城市一条，重名项目城市不绑定单一项目。"""
    data = load(log, cancelled)
    return [{'id': city['id'], 'cityName': city['name'],
             'projectCode': city['project_code'] or None}
            for city in data['cities']]


def cached_names():
    """供提交校验使用：仅读当前会话的缓存，不触发网络请求；无缓存返回 None。"""
    from platform_auth_control import version
    try:
        current = version('lanorange_mdr')
    except Exception:
        return None
    with _lock:
        entry = _cache.get(current)
        if not entry or time.monotonic() - entry['at'] >= TTL:
            return None
        return {normalize_name(city['name']) for city in entry['data']['cities'] if city['name']}