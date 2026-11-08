"""Session-bound directory snapshots. Refresh is serialized and never submits exports."""
import copy
import threading
import time
from datetime import datetime, timezone

_lock = threading.RLock()
_states = {}
_workers = {}
TTL = 300


def _version(platform):
    from platform_auth_control import version
    return version(platform)


def _publish(platform, version, change):
    with _lock:
        if _states.get(platform, {}).get('session_version') == version and _version(platform) == version:
            change(_states[platform])


def _scan(platform, version):
    from deduction_stations import catalog
    try:
        if platform == 'lanorange':
            from station_city_resolution import read_directory
            directory = read_directory(expected_version=version)
            cities = directory['city_entries']
            stations = [{**s, 'platform': platform} for s in directory['stations']]
        else:
            first = catalog(platform)
            cities, stations = first['cities'], first['stations']
        def initial(state):
            if platform != 'lanorange' and first.get('account_scope'): state['account_scope'] = first['account_scope']
            existing = {c['id']: c for c in state['cities']}
            state.update(cities=[{**c, 'station_count': existing.get(c['id'], {}).get('station_count'), 'status': existing.get(c['id'], {}).get('status', 'pending')} for c in cities],
                         stations=state['stations'] if platform == 'fengshen' else stations)
        _publish(platform, version, initial)
        if platform == 'fengshen':
            for city in cities:
                if _version(platform) != version:
                    return
                try:
                    with _lock:
                        include = city['id'] in _states.get(platform, {}).get('separation_cities', [])
                    result = catalog(platform, city['id'], include_separation=True) if include else catalog(platform, city['id'])
                    def success(state):
                        if result.get('account_scope'): state['account_scope'] = result['account_scope']
                        state['stations'] = [s for s in state['stations'] if s['city_id'] != city['id']] + result['stations']
                        state.setdefault('_city_verified', {})[city['id']] = time.monotonic()
                        next(c for c in state['cities'] if c['id'] == city['id']).update(station_count=len({s['id'] for s in result['stations']}), status='ready')
                    _publish(platform, version, success)
                except Exception as error:
                    def failure(state):
                        next(c for c in state['cities'] if c['id'] == city['id']).update(status='unavailable')
                    _publish(platform, version, failure)
                    if getattr(error, 'status_code', None) in (401, 403, 409):
                        raise
        else:
            def counts(state):
                for city in state['cities']:
                    city.update(station_count=len({s['id'] for s in stations if s['city_id'] == city['id']}), status='ready')
            _publish(platform, version, counts)
        _publish(platform, version, lambda state: state.update(status='ready', fetched_at=datetime.now(timezone.utc).isoformat()))
    except Exception as error:
        code = getattr(error, 'status_code', None)
        def failed(state):
            state.update(status='unavailable', message='请先完成平台登录后刷新' if code in (401, 403) else '目录暂不可用，请在当前采集或认证结束后刷新')
            detail = str(getattr(error, 'detail', ''))
            if code == 409 and detail:
                state['message'] = detail
            if code == 409 and '恢复' not in detail and ('正在' in detail or '忙' in detail):
                state['_retry_at'] = time.monotonic() + 10
        _publish(platform, version, failed)
    finally:
        with _lock:
            _workers.pop(platform, None)


def snapshot(platform, refresh=False):
    if platform not in ('fengshen', 'xiaoxiang', 'lanorange'):
        from fastapi import HTTPException
        raise HTTPException(400, '平台无效')
    version = _version(platform)
    with _lock:
        state = _states.get(platform)
        changed = state is None or state['session_version'] != version
        if changed:
            state = {'platform': platform, 'session_version': version, 'cities': [], 'stations': [],
                     'status': 'loading', 'message': '', 'fetched_at': '', '_started': 0}
            _states[platform] = state
        expired = time.monotonic() - state['_started'] > TTL or (state.get('_retry_at') is not None and time.monotonic() >= state['_retry_at'])
        if platform not in _workers and (changed or refresh or expired or state['_started'] == 0 or (state['status']=='loading' and any(c['status']=='pending' for c in state['cities']))):
            # Keep previous visible data during a same-account refresh, mark it as refreshing.
            state.update(status='loading', message='', _started=time.monotonic())
            state.pop('_retry_at', None)
            worker = threading.Thread(target=_scan, args=(platform, version), daemon=True, name='station-directory-' + platform)
            _workers[platform] = worker
            worker.start()
        return copy.deepcopy({k: v for k, v in state.items() if not k.startswith('_')})


def ready_directory(platform, city='', refresh=False):
    from parttime_source import SourceError
    if city and platform == 'xiaoxiang' and \
            not any(item['name'] == city or item['id'] == city for item in snapshot(platform)['cities']):
        # 小象批次的城市是平台伪名（如「小象」），按账号整目录交付。
        city = ''
    if city and platform in ('fengshen', 'xiaoxiang'):
        return current_city_directory(platform, city, True) if refresh else current_city_directory(platform, city)
    data = snapshot(platform)
    chosen = [c for c in data['cities'] if c['name'] == city or c['id'] == city]
    if (not city and data['status'] != 'ready') or (city and (len(chosen) != 1 or chosen[0]['status'] != 'ready')):
        raise SourceError('后台站点目录尚未完整同步，请同步完成后再确认扣款')
    return data


def current_city_directory(platform, city, refresh=False):
    """Payroll reads its own city directly; unrelated full-directory scans are optional."""
    from deduction_stations import catalog
    from parttime_source import SourceError
    version = _version(platform)
    with _lock:
        state = _states.get(platform)
        if state and state['session_version'] == version:
            chosen = [c for c in state['cities'] if c['id'] == city or c['name'] == city]
            if not refresh and len(chosen) == 1 and chosen[0]['status'] == 'ready' and state['status'] != 'unavailable':
                verified = state.get('_city_verified', {}).get(chosen[0]['id'], state.get('_started', 0))
                if time.monotonic() - verified < TTL:
                    return copy.deepcopy({k:v for k,v in state.items() if not k.startswith('_')})
            include = len(chosen) == 1 and chosen[0]['id'] in state.get('separation_cities', [])
        else:
            include = False
            chosen = []
        query_city = chosen[0]['id'] if len(chosen)==1 else city
    try:
        options = {'refresh': True} if refresh else {}
        if include: options['include_separation'] = True
        result = catalog(platform, query_city, **options)
    except Exception as error:
        code = getattr(error, 'status_code', 0)
        if code in (401,403):
            raise SourceError('本次城市资料需要平台登录，请完成登录后继续；已填金额保留') from None
        if code == 409:
            raise SourceError('本次城市资料正在排队，当前采集或认证结束后将自动继续') from None
        if code == 400:
            raise SourceError('申请城市无法匹配后台目录，请在高级选项中确认城市映射后重试') from None
        raise SourceError('本次城市站点读取暂未完成，请检查平台连接后重试；其他城市不影响本批次') from None
    choices = [c for c in result['cities'] if c['id'] == city or c['name'] == city]
    if len(choices) != 1:
        raise SourceError('申请城市无法唯一匹配后台城市，请在高级选项中确认城市映射')
    code = choices[0]['id']
    with _lock:
        if _version(platform) != version:
            raise SourceError('平台账号已变化，请重新读取本次城市')
        state = _states.get(platform)
        if not state or state['session_version'] != version:
            state = {'platform':platform,'session_version':version,'cities':[],'stations':[], 'status':'loading','message':'','fetched_at':'','_started':time.monotonic()}
            _states[platform] = state
        previous = {c['id']:c for c in state['cities']}
        state['cities'] = [{**c,'station_count':previous.get(c['id'],{}).get('station_count'),'status':previous.get(c['id'],{}).get('status','pending')} for c in result['cities']]
        state['stations'] = [s for s in state['stations'] if s['city_id'] != code] + result['stations']
        if result.get('account_scope'): state['account_scope'] = result['account_scope']
        next(c for c in state['cities'] if c['id']==code).update(status='ready',station_count=len({s['id'] for s in result['stations']}))
        state.setdefault('_city_verified', {})[code] = time.monotonic()
        state.update(message='',fetched_at=datetime.now(timezone.utc).isoformat())
        state['status'] = 'ready' if all(c['status']=='ready' for c in state['cities']) else 'loading'
        return copy.deepcopy({k:v for k,v in state.items() if not k.startswith('_')})


def sync_separation(city):
    from deduction_stations import catalog
    from fastapi import HTTPException
    version = _version('fengshen')
    result = catalog('fengshen', city, refresh=True, include_separation=True)
    choices = [c for c in result['cities'] if c['id'] == city or c['name'] == city]
    if len(choices) != 1:
        raise HTTPException(409, '无法唯一匹配后台城市')
    code = choices[0]['id']
    with _lock:
        state = _states.get('fengshen')
        if not state or state['session_version'] != version or _version('fengshen') != version:
            raise HTTPException(409, '目录会话已变化，请重新同步')
        state.setdefault('separation_cities', [])
        if code not in state['separation_cities']: state['separation_cities'].append(code)
        state['stations'] = [s for s in state['stations'] if s['city_id'] != code] + result['stations']
        if result.get('account_scope'): state['account_scope'] = result['account_scope']
        for c in state['cities']:
            if c['id'] == code: c.update(status='ready', station_count=len(result['stations']))
        state['fetched_at'] = datetime.now(timezone.utc).isoformat()
        return copy.deepcopy(state)
