"""Confirmed aliases, scoped to official account/city; suggestions never grant readiness."""
from datetime import datetime, timezone
from difflib import SequenceMatcher
import hashlib
import json
from pathlib import Path
import re
import threading

from fengshen_bill import atomic_json
from parttime_source import SourceError

LOCK = threading.RLock()


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def identity_scope(identity, session_version):
    # Never use an agency selected temporarily by a download as the account identity.
    tenant = [str(identity.get(k) or '') for k in ('tenantId', 'companyId', 'supplierId')]
    for index, row in enumerate([identity] + [identity.get(k) for k in ('user', 'userInfo', 'sysUser') if isinstance(identity.get(k), dict)]):
        for key in (('userId', 'user_id', 'loginName', 'userName') if index == 0 else ('userId', 'user_id', 'id', 'loginName', 'userName')):
            value = row.get(key)
            if type(value) in (str, int) and str(value).strip():
                return digest(['official-user', tenant, key, str(value).strip()])
    # If the platform does not expose stable identity, reuse only this login session.
    return digest(['session', session_version])


def scope(directory):
    return directory.get('account_scope') or (digest(['session', directory['session_version']]) if directory.get('session_version') else '')


def separation(name, station=None):
    return bool((station or {}).get('separation') or '取分离' in name)


def compatible(name, station):
    return separation(name) == separation(station['name'], station)


def path_for(root, platform):
    if platform not in ('fengshen', 'xiaoxiang'):
        raise SourceError('站点关联平台无效')
    path = Path(root) / 'data' / 'station_associations' / (platform + '.json')
    if path.is_symlink() or path.parent.is_symlink() or path.parent.parent.is_symlink():
        raise SourceError('站点关联配置路径异常')
    return path


def load(root, platform):
    path = path_for(root, platform)
    if not path.exists():
        entries = {}
    else:
        try:
            entries = json.loads(path.read_text(encoding='utf-8'))['entries']
            if not isinstance(entries, dict) or any(not isinstance(v, dict) for v in entries.values()):
                raise ValueError()
        except (OSError, ValueError, KeyError, TypeError):
            raise SourceError('历史站点关联无法读取，原文件保留，请检查配置') from None
    return {'entries': entries, 'version': digest(entries)}


def alias_key(directory, city_id, name):
    return digest([scope(directory), city_id, name])


def remembered(saved, directory, name, candidates):
    if not scope(directory):
        return None
    for entry in candidates:
        station = entry['station']
        previous = saved['entries'].get(alias_key(directory, station['city_id'], name))
        if previous and previous.get('target') == entry['key'] and previous.get('separation') == separation(name) and compatible(name, station):
            return entry
    return None


def has_history(saved, directory, city, name):
    city_ids = {s['city_id'] for s in directory['stations'] if s['city'] == city}
    city_ids.update(c['id'] for c in directory.get('cities', []) if c['name'] == city)
    return bool(scope(directory) and any(alias_key(directory, code, name) in saved['entries'] for code in city_ids))


def save(root, platform, directory, links, expected_version):
    """Caller supplies validated official targets under LOCK; keep a reversible history."""
    with LOCK:
        current = load(root, platform)
        if current['version'] != expected_version:
            raise SourceError('历史关联已被其他人修改，请重新读取后确认')
        if not scope(directory):
            raise SourceError('平台身份尚未确认，不能保存跨批次关联')
        now = datetime.now(timezone.utc).isoformat()
        for name, entry in links.items():
            station = entry['station']
            if not compatible(name, station):
                raise SourceError('取分离与普通站点不能混用关联')
            current['entries'][alias_key(directory, station['city_id'], name)] = {
                'name': name, 'city_id': station['city_id'], 'target': entry['key'],
                'separation': separation(name), 'confirmed_at': now,
            }
        path = path_for(root, platform)
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists():
            history = path.parent / 'history' / (platform + '_' + datetime.now().strftime('%Y%m%d_%H%M%S_%f') + '.json')
            history.parent.mkdir(parents=True, exist_ok=True)
            atomic_json(history, json.loads(path.read_text(encoding='utf-8')))
        atomic_json(path, {'entries': current['entries']})


def recommendation(name, candidates, city):
    def core(value):
        value = re.sub(r'[\s_（）()\-·]', '', value)
        value = value.replace('取分离', '').replace('新专送', '')
        if city and value.startswith(city): value = value[len(city):]
        # Business prefixes only influence suggestions, never automatic identity.
        value = re.sub(r'^(麻豆人|取分离)', '', value)
        return value.removesuffix('站')
    source = core(name)
    if len(source) < 2:
        return []
    ranked = []
    for entry in candidates:
        target = core(entry['station']['name'])
        score = SequenceMatcher(None, source, target).ratio() if target else 0
        if score >= .62:
            ranked.append({'key': entry['key'], 'score': round(score, 3), 'reason': '名称相似，需确认'})
    return sorted(ranked, key=lambda e: (-e['score'], e['key']))[:3]
