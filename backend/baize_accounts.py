"""Read-only Baize merchant/region identity for the two business accounts."""
import time

import binding_source_auth

CACHE_SECONDS = 30
_cache = {'at': 0, 'value': None, 'key': None}


def _text(value):
    return str(value or '').strip()


def _query(session, path, params=None):
    response = session.get('https://merchant.shangyiworker.com/prod-api/' + path,
                           params=params or {}, timeout=30)
    if response.status_code != 200:
        raise ValueError(str(response.status_code))
    return binding_source_auth._response_json(response)


def _key():
    parts = []
    for path in (binding_source_auth.session_path('baize'), binding_source_auth.state_path('baize')):
        try:
            stat = path.stat()
            parts.append((path.name, stat.st_mtime_ns, stat.st_size))
        except OSError:
            parts.append((path.name, 0, 0))
    return tuple(parts)


def snapshot(force=False):
    key = _key()
    now = time.monotonic()
    if not force and _cache['value'] is not None and _cache['key'] == key and now - _cache['at'] < CACHE_SECONDS:
        return dict(_cache['value'])
    value = {'state': 'signed_out', 'account_type': 'unknown', 'account_label': '',
             'organization': '', 'regions': [], 'region_text': '', 'merchant_name': ''}
    try:
        session = binding_source_auth.client('baize')
        try:
            identity = binding_source_auth.identity('baize', session)
            user = identity.get('user') if isinstance(identity, dict) else {}
            user = user if isinstance(user, dict) else {}
            merchant = _query(session, 'web/merchantInfo/queryList', {'pageNum': 1, 'pageSize': 20})
            merchant_rows = merchant.get('data') if isinstance(merchant, dict) else None
            merchant = merchant_rows[0] if isinstance(merchant_rows, list) and merchant_rows else {}
            merchant = merchant if isinstance(merchant, dict) else {}
            groups = _query(session, 'web/merchantGroup/queryList', {'pageNum': 1, 'pageSize': 500})
            rows = groups.get('data') if isinstance(groups, dict) else None
            rows = rows if isinstance(rows, list) else []
            regions = []
            for row in rows:
                if not isinstance(row, dict):
                    continue
                name = _text(row.get('groupName') or row.get('name'))
                if name and name not in regions:
                    regions.append(name)
            organization = _text(merchant.get('merName') or merchant.get('shortName') or
                                 merchant.get('agentName'))
            label = _text(user.get('nickName') or user.get('userName')) or organization
            identity_text = ' '.join([organization, _text(merchant.get('shortName')),
                                      _text(merchant.get('regAreaName')),
                                      _text(merchant.get('openAreaName')), *regions])
            account_type = 'xiaoxiang' if '小象超市' in identity_text else 'shanggou' if regions or organization else 'unknown'
            value.update(state='ready', account_type=account_type, account_label=label,
                         organization=organization, regions=regions, region_text='、'.join(regions[:12]),
                         merchant_name=organization)
        finally:
            session.close()
    except Exception:
        value.update(state='unknown', account_type='unknown')
    _cache.update(at=now, value=dict(value), key=key)
    return value