"""Read-only official price filters; cached only within this personal service."""
import copy
import re
import threading
import time

from lanorange_approval_client import OfficialApprovalClient, ApprovalError, identifier

_lock = threading.Lock()
_cache = {}
TTL = 120


def load_directory(api):
    cities = api._get('base/baseCity/queryList').get('data')
    stations = api._get('base/baseSite/queryList', {'status': 0}).get('data')
    if not isinstance(cities, list) or not isinstance(stations, list) or len(cities)>1000 or len(stations)>20000:
        raise ApprovalError('蓝橙城市或站点目录未完整返回，请重新加载')
    city_names = {}
    for row in cities:
        if not isinstance(row,dict) or not isinstance(row.get('cityName'),str) or not 0<len(row['cityName'])<=80:
            raise ApprovalError('蓝橙城市目录格式已变化')
        city_names[identifier(row.get('id'))] = row['cityName']
    sites = {}
    for row in stations:
        if not isinstance(row,dict) or not isinstance(row.get('siteName'),str) or not 0<len(row['siteName'])<=80:
            raise ApprovalError('蓝橙站点目录格式已变化')
        key=identifier(row.get('id'));city_id=identifier(row.get('cityId'))
        # No unscoped/no-permission endpoint, fabricated city, or silent relabel.
        if city_id not in city_names:continue
        sites[key]={'id':key,'name':row['siteName'],'city':city_names[city_id], 'city_id':city_id}
    return {'cities': sorted(set(city_names.values())), 'city_entries': [{'id': key, 'name': name} for key, name in city_names.items()],
            'stations': sorted(sites.values(), key=lambda row:(row['city'],row['name'],row['id']))}


def load_options(api):
    directory = load_directory(api)
    months=set();seen=set();expected=None
    # Read list metadata only, never rider details or export/approval endpoints.
    for page in range(1,22):
        data=api._get('salary/riderPrice/list',{'pageNum':page,'pageSize':1000})
        total,rows=data.get('total'),data.get('rows')
        if type(total) is not int or not 0<=total<=20000 or not isinstance(rows,list):
            raise ApprovalError('蓝橙价格业务目录超出单次加载范围或未完整返回')
        if expected is not None and expected!=total:raise ApprovalError('蓝橙业务目录采集中发生变化，请重新加载')
        expected=total
        for row in rows:
            if not isinstance(row,dict):raise ApprovalError('蓝橙业务目录格式已变化')
            key=identifier(row.get('id'))
            if key in seen:raise ApprovalError('蓝橙目录分页重复，请重新加载')
            seen.add(key)
            month=str(row.get('settleMonth',''))[:7]
            if re.fullmatch(r'\d{4}-(?:0[1-9]|1[0-2])',month):months.add(month)
        if len(seen)==total:break
        if not rows or len(seen)>total:raise ApprovalError('蓝橙业务目录分页不完整，请重新加载')
    else:raise ApprovalError('蓝橙业务目录分页不完整，请重新加载')
    return {**directory, 'months':sorted(months,reverse=True),'actor_label':api.actor_label}


def options(owner,refresh=False,*,factory=OfficialApprovalClient,version_fn=None):
    if version_fn is None:
        from lanorange_approvals import current_version
        version_fn=current_version
    version=version_fn();key=(owner,version)
    # Single flight prevents rapid module switches from scanning the full list twice.
    with _lock:
        cached=_cache.get(key)
        if cached and not refresh and time.monotonic()-cached[0]<TTL:
            result=copy.deepcopy(cached[1])
        else:
            with factory() as api:result={**load_options(api),'session_version':version,'loaded_at':time.time()}
            if version_fn()!=version:raise ApprovalError('蓝橙账号已变化，请重新加载筛选条件','changed')
            _cache.clear();_cache[key]=(time.monotonic(),copy.deepcopy(result))
        if version_fn()!=version:raise ApprovalError('蓝橙账号已变化，请重新加载筛选条件','changed')
        return result
