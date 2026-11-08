"""Read-only, session-scoped station choices for deduction settings.

No exports, rider/contact queries, credential refresh or configuration writes.
"""
from contextlib import contextmanager
import copy
from datetime import datetime, timezone
import re
import time

from fastapi import HTTPException

CACHE_SECONDS = 300
_cache = {}
_versions = {}


def _discard(platform):
    from function_availability import discard
    discard(platform)
    for key in list(_cache):
        if key[0] == platform:
            del _cache[key]


def _status(platform):
    from platform_auth_control import status
    return status(platform)


def _version(platform):
    from platform_auth_control import version
    return version(platform)


def _operation(platform):
    from platform_auth_control import operation
    return operation(platform)


@contextmanager
def _collection():
    from parttime_source import COLLECTION_LOCK
    if not COLLECTION_LOCK.acquire(blocking=False):
        raise HTTPException(409, '资料采集正在进行，请任务结束后再获取站点')
    try:
        yield
    finally:
        COLLECTION_LOCK.release()


def _id(value):
    if type(value) not in (str, int) or not re.fullmatch(r'\d{1,24}', str(value)):
        raise HTTPException(502, '平台站点或城市编号格式变化，未猜测编号')
    return str(value)


def _text(value):
    if not isinstance(value, str) or not value.strip() or len(value) > 200 or any(ord(char) < 32 for char in value):
        raise HTTPException(502, '平台站点名称或城市信息不完整，请暂用手动维护')
    return value.strip()


def _fengshen_client():
    from fengshen_auth import BROKER
    from fengshen_http import FengshenHttpClient
    state = BROKER.vault.load()
    if not state:
        raise HTTPException(401, '请先登录风神，再获取站点')
    client = FengshenHttpClient(state)
    client.timeout, client.attempts = (4, 12), 1
    return client


def _cities(payload):
    rows = payload.get('data') if isinstance(payload, dict) else None
    if not isinstance(rows, list):
        raise HTTPException(502, '风神城市清单结构变化，请稍后重试')
    result, seen = [], set()
    for row in rows:
        if not isinstance(row, dict) or row.get('agencySubTypeName') != '物流合作商':
            continue
        code, name = _id(row.get('agencyId')), _text(row.get('agencyCityName'))
        if code in seen:
            if any(item['id'] == code and item['name'] != name for item in result):
                raise HTTPException(502, '风神城市编号对应多个名称，未合并目录')
            continue
        seen.add(code)
        result.append({'id': code, 'name': name})
    if not result:
        raise HTTPException(502, '风神未返回可核实的物流合作商城市，请检查账号权限')
    return sorted(result, key=lambda item: (item['name'], item['id']))


def _choose_city(cities, city):
    matches = [item for item in cities if item['id'] == city]
    if not matches:
        matches = [item for item in cities if item['name'] == city]
    if len(matches) != 1:
        raise HTTPException(400, '请选择当前账号可访问的唯一城市（同名城市请按编号选择）')
    return matches[0]


def _fengshen_stations(payload, city):
    result = payload.get('result') if isinstance(payload, dict) else None
    rows = result.get('data') if isinstance(result, dict) else None
    if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
        raise HTTPException(502, '风神站点清单结构变化，请稍后重试')
    result, seen = [], set()
    for row in rows:
        code, agency = _id(row.get('id')), _id(row.get('agencyId'))
        if code in seen:
            raise HTTPException(502, '风神返回重复站点编号，未合并目录')
        seen.add(code)
        if agency == city['id']:
            result.append({'id': code, 'name': _text(row.get('team_name')), 'city': city['name'],
                           'city_id': city['id'], 'platform': 'fengshen'})
    return sorted(result, key=lambda item: (item['name'], item['id']))


def _fengshen(city, version, include_separation=False):
    from fengshen_http import AGENCIES_URL, TEAMS_URL
    with _collection():
        client = _fengshen_client()
        original, attempted = None, False
        try:
            agencies = client.request_json('GET', AGENCIES_URL)
            cities = _cities(agencies)
            if not city:
                return {'cities': cities, 'stations': [], 'scope_note': '当前风神账号可访问的物流合作商城市；选择城市后获取其站点。', 'warnings': []}
            chosen = _choose_city(cities, city)
            identity = client.identity()
            original = _id(identity['agencyId'])
            from station_associations import identity_scope
            account_scope = identity_scope(identity, version)
            attempted = True
            client.select_city(chosen['id'])
            client.assert_city(chosen['id'])
            stations = _fengshen_stations(client.request_json('POST', TEAMS_URL, body={}), chosen)
            client.assert_city(chosen['id'])
            # The existing protocol observes a brief old-city response after a switch.
            if not stations:
                client.select_city(chosen['id'])
                stations = _fengshen_stations(client.request_json('POST', TEAMS_URL, body={}), chosen)
                client.assert_city(chosen['id'])
            if not stations:
                raise HTTPException(502, '风神未返回该城市可核实的站点；未获取不等于没有站点')
            if include_separation:
                for row in agencies['data']:
                    if row.get('agencyCityName') != chosen['name'] or row.get('agencySubTypeName') != '物流服务商':
                        continue
                    other = {**chosen, 'id': _id(row['agencyId'])}
                    client.select_city(other['id']);client.assert_city(other['id'])
                    extra = _fengshen_stations(client.request_json('POST', TEAMS_URL, body={}), other)
                    stations.extend({**s, 'city_id': chosen['id'], 'agency_id': other['id'], 'separation': True} for s in extra if '取分离' in s['name'])
                if len({s['id'] for s in stations}) != len(stations):
                    raise HTTPException(502, '跨合作商站点编号重复，请核对后台目录')
            return {'cities': cities, 'stations': stations, 'account_scope': account_scope, 'scope_note': '所选物流合作商城市下，当前账号可见的风神站点。', 'warnings': []}
        finally:
            try:
                if attempted and original:
                    if _version('fengshen') != version:
                        raise HTTPException(409, '风神会话已变化，请重新获取站点')
                    try:
                        client.select_city(original)
                        client.assert_city(original)
                    except Exception as error:
                        from fengshen_bill import AuthenticationRequired
                        if isinstance(error, AuthenticationRequired):
                            raise HTTPException(401, '风神登录已失效，原城市恢复尚未确认，请重新登录') from None
                        raise HTTPException(409, '站点获取后原城市恢复尚未确认，请重新选择城市后再操作') from None
            finally:
                client.close()


def _lighthouse_context(state):
    """Use the active supplier saved by the official RSS page, never a fixed account."""
    import xiaoxiang_lighthouse as lighthouse
    storage = {}
    for origin in lighthouse.scoped_state(state)['origins']:
        if origin.get('origin', '').rstrip('/') != lighthouse.BASE:
            continue
        for item in origin.get('localStorage', []):
            if isinstance(item, dict) and item.get('name') in ('rss_supplier_id', 'rss_supplier_operator_mis'):
                key, value = item['name'], item.get('value')
                if key in storage and storage[key] != value:
                    raise HTTPException(409, '灯塔保存的合作商上下文不一致，请重新登录后获取站点')
                storage[key] = value
    supplier = storage.get('rss_supplier_id')
    if not isinstance(supplier, str) or not re.fullmatch(r'\d{1,24}', supplier):
        raise HTTPException(401, '灯塔会话未保存当前合作商，请重新登录后获取站点')
    operator = storage.get('rss_supplier_operator_mis')
    if not operator:
        from xiaoxiang_rider_archive import operator_mis
        operator = operator_mis(state)
    if not isinstance(operator, str) or not operator.strip() or len(operator) > 200 or any(ord(char) < 32 for char in operator):
        raise HTTPException(401, '灯塔当前登录账号无法确认，请重新登录后获取站点')
    return supplier, operator


def _station_rows(context=None):
    """Verified official RSS station selector; no board/rider queries or exports."""
    import requests
    import xiaoxiang_lighthouse as lighthouse
    from auth_browser_runtime import bounded_requests
    state = lighthouse.load_state()
    if not state:
        raise HTTPException(401, '请先登录灯塔，再获取站点')
    supplier, operator = _lighthouse_context(state)
    payload = {'needManagementCityInfo': True, 'supplierId': supplier,
               'checkSupplierAccess': True, 'operator': operator}
    with lighthouse.session_from_state(state) as session:
        session.headers.update({'mall-login-type': 'passport', 'Referer': lighthouse.BASE + '/rss/riders/list.html'})
        bounded_requests(session)
        try:
            response = session.post(lighthouse.BASE + '/api/s/peisong/supplier/dept/list', json=payload)
        except requests.RequestException:
            raise HTTPException(502, '灯塔站点连接失败，请稍后重试') from None
    if response.status_code == 401 or 'passport.meituan.com' in str(response.url) or 'text/html' in str(response.headers.get('content-type', '')):
        raise lighthouse.SessionExpired('灯塔登录已失效')
    if response.status_code == 403:
        raise HTTPException(403, '当前灯塔账号没有站点目录访问权限，请联系平台管理员')
    if response.status_code != 200:
        raise HTTPException(502, '灯塔站点接口暂不可用，请稍后重试')
    try:
        body = response.json()
    except ValueError:
        raise HTTPException(502, '灯塔站点接口未返回有效目录，请稍后重试') from None
    if not isinstance(body, dict):
        raise HTTPException(502, '灯塔站点目录结构变化，请暂用手动维护')
    if body.get('code') == 5:
        raise lighthouse.SessionExpired('灯塔登录已失效')
    if type(body.get('code')) is not int or body['code'] != 0:
        raise HTTPException(502, '灯塔未允许读取站点目录，请检查账号权限后重试')
    rows = body.get('data')
    if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
        raise HTTPException(502, '灯塔站点目录结构变化，请暂用手动维护')
    if context is not None:
        from station_associations import identity_scope
        context['account_scope'] = identity_scope({'supplierId':supplier,'userId':operator}, _version('xiaoxiang'))
    return rows


def _xiaoxiang(city, version):
    context = {}
    with _collection():
        rows = _station_rows(context)
    stations, seen, cities = [], set(), {}
    missing = 0
    for row in rows:
        code = _id(row.get('siteId'))
        if code in seen:
            raise HTTPException(502, '灯塔站点目录返回重复编号，未合并目录')
        seen.add(code)
        if not row.get('siteName') or not row.get('cityName') or row.get('cityId') is None:
            missing += 1
            continue
        city_name, city_id, name = _text(row['cityName']), _id(row['cityId']), _text(row['siteName'])
        if city_id in cities and cities[city_id] != city_name:
            raise HTTPException(502, '灯塔城市编号对应多个名称，未合并目录')
        cities[city_id] = city_name
        stations.append({'id': code, 'name': name, 'city': city_name,
                         'city_id': city_id, 'platform': 'xiaoxiang',
                         'poi_id': _id(row['poiId']) if row.get('poiId') is not None else '',
                         'management_city': _text(row['managementCityName']) if row.get('managementCityName') else '',
                         'management_city_id': _id(row['managementCityId']) if row.get('managementCityId') is not None else ''})
    cities = sorted([{'id': code, 'name': name} for code, name in cities.items()], key=lambda item: (item['name'], item['id']))
    warnings = []
    if missing:
        warnings.append(f'{missing} 个站点缺少名称或城市，未列入可选项；可暂用手动维护。')
    if not stations and rows:
        raise HTTPException(502, '灯塔当前目录未返回可核实的站点名称与城市，请暂用手动维护')
    if not stations:
        warnings.append('当前账号未返回可选站点，不代表平台没有站点；请检查合作商及站点权限。')
    if city:
        chosen = _choose_city(cities, city)
        stations = [item for item in stations if item['city_id'] == chosen['id']]
    return {**context, 'cities': cities, 'stations': sorted(stations, key=lambda item: (item['city'], item['name'], item['id'])),
            'scope_note': '当前灯塔账号及合作商权限内的站点目录；城市使用后台业务城市，管理城市另行保留。',
            'warnings': warnings}


def catalog(platform: str, city: str = '', refresh: bool = False, include_separation: bool = False) -> dict:
    if platform not in ('fengshen', 'xiaoxiang') or not isinstance(city, str) or len(city) > 200 or type(refresh) is not bool:
        raise HTTPException(400, '请选择风神或灯塔及有效城市')
    from fengshen_bill import AuthenticationRequired
    from fengshen_http import HttpTransportError
    from xiaoxiang_lighthouse import SessionExpired, LighthouseError
    with _operation(platform):
        status = _status(platform)
        if status.get('busy') or status.get('state') in ('starting', 'waiting_login', 'refreshing'):
            raise HTTPException(409, '平台登录或切换正在进行，请完成后再获取站点')
        if not status.get('saved'):
            raise HTTPException(401, '请先登录' + ('风神' if platform == 'fengshen' else '灯塔') + '，再获取站点')
        if status.get('state') in ('login_required', 'signed_out'):
            raise HTTPException(401, '平台登录已失效，请重新登录后获取站点')
        version = _version(platform)
        if _versions.get(platform) != version:
            _discard(platform)
            _versions[platform] = version
        key = (platform, version, city, include_separation)
        cached = _cache.get(key)
        if cached and not refresh and time.monotonic() - cached[0] < CACHE_SECONDS:
            return {**copy.deepcopy(cached[1]), 'cached': True}
        try:
            value = _fengshen(city, version, True) if platform == 'fengshen' and include_separation else _fengshen(city, version) if platform == 'fengshen' else _xiaoxiang(city, version)
        except (AuthenticationRequired, SessionExpired):
            _discard(platform)
            raise HTTPException(401, '平台登录已失效，请重新登录后获取站点') from None
        except HTTPException as error:
            if error.status_code in (401, 403):
                _discard(platform)
            raise
        except (HttpTransportError, LighthouseError):
            raise HTTPException(502, '平台站点查询暂不可用，请检查连接后重试；已有扣款配置保留') from None
        if _version(platform) != version:
            raise HTTPException(409, '平台会话已变化，请重新获取站点')
        result = {'platform': platform, **value, 'fetched_at': datetime.now(timezone.utc).isoformat(), 'cached': False}
        from function_availability import record
        record(platform, version, 'stations' if platform == 'xiaoxiang' or city else 'cities')
        _cache[key] = (time.monotonic(), copy.deepcopy(result))
        return result
