"""Explicit payroll deduction review, bound to retained input hashes and station identity."""
import csv
import codecs
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import re
import threading

from openpyxl import load_workbook
from parttime_source import SourceError, identifier
from fengshen_bill import atomic_json

LOCK = threading.RLock()
META = ('城市', '团队名称', '团队ID')
DEFAULT_COLUMNS = ('安全基金', '保险费', '使用费', '循环物资使用费', '附加险', '非蜂卡', '月费')
SUPPORTED = {*DEFAULT_COLUMNS, '招聘来源'}
TEAM = ('团队名称', '骑手所属站点名称', '骑手所属团队名称', '站点名称', '站点', '所属站点', '团队', '站点名')
RID = ('骑手ID', '风神骑手ID', '蜂鸟骑手ID', '骑手编号', '工号', 'riderid')


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False).encode()).hexdigest()


def normalize(value):
    return re.sub(r'_?新专送', '', str(value or '').strip())


def platform_for(state):
    return 'xiaoxiang' if state['mode'] == 'xiaoxiang' else 'fengshen'


def station_key(station):
    return digest([station['platform'], station['city_id'], station['id']])


def station_codes(station):
    # 灯塔账单里的「站点ID」是 poiId，与站点目录的 siteId 属于两套编号。
    return {str(station.get(key) or '') for key in ('id', 'poi_id')} - {''}


def profile(platform, root):
    if platform not in ('fengshen', 'xiaoxiang'):
        raise SourceError('扣款平台无效')
    path = Path(root) / 'data' / 'deduction_profiles' / (platform + '.json')
    if path.is_symlink() or path.parent.is_symlink():
        raise SourceError('扣款配置路径异常')
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding='utf-8'))
            if not isinstance(data, dict) or not isinstance(data['entries'], dict) or not isinstance(data.get('cities', {}), dict):
                raise ValueError()
        except (OSError, ValueError, KeyError):
            raise SourceError('站点扣款默认配置无法读取，请检查原文件') from None
    else:
        data = {'entries': {}}
    return {**data, 'cities': data.get('cities', {}), 'version': digest([data['entries'], data.get('cities', {})])}


def city_station(platform, city):
    return {'platform': platform, 'city_id': city['id'], 'city': city['name'], 'id': '*', 'name': '城市统一扣款'}


def legacy_rows(platform, root):
    if platform != 'fengshen':
        return []
    from workbench import read_defaults
    return read_defaults(root)['rows']


def columns_for(platform, root):
    columns = list(DEFAULT_COLUMNS if platform != 'xiaoxiang' else ('安全基金', '使用费', '非蜂卡', '月费'))
    for row in legacy_rows(platform, root):
        for key in row:
            if (key in SUPPORTED or (key.endswith('_maxDays') and key[:-8] in SUPPORTED)) and key not in columns:
                columns.append(key)
    defaults = profile(platform, root)
    for entry in [*defaults['entries'].values(), *defaults['cities'].values()]:
        for key in entry['row']:
            if (key in SUPPORTED or (key.endswith('_maxDays') and key[:-8] in SUPPORTED)) and key not in columns:
                columns.append(key)
    return columns


def station_drafts(platform, root, directory):
    defaults = profile(platform, root)
    legacy = legacy_rows(platform, root)
    columns = columns_for(platform, root)
    result = []
    for station in directory['stations']:
        key = station_key(station)
        previous = defaults['entries'].get(key)
        candidates = [r for r in legacy if r.get('城市') == station['city'] and normalize(r.get('团队名称')) == normalize(station['name'])]
        inherited = candidates[0] if len(candidates) == 1 else {}
        city_default = defaults['cities'].get(digest([platform, station['city_id']]))
        values = previous['row'] if previous else {**inherited, **city_default['row']} if city_default else inherited
        row = {**values, '城市': station['city'], '团队名称': station['name'], '团队ID': station['id']}
        for col in columns:
            row.setdefault(col, None)
        result.append({'key': key, 'station': station, 'row': row, 'configured': bool(previous or city_default),
                       'inherited_city': bool(city_default and not previous), 'station_override': bool(previous),
                       'zero_confirmed': bool((previous or city_default or {}).get('zero_confirmed')), 'legacy': bool(inherited and not previous and not city_default)})
    cities = []
    for city in directory.get('cities', []):
        station = city_station(platform, city)
        key = digest([platform, city['id']])
        previous = defaults['cities'].get(key)
        row = {**((previous or {}).get('row', {})), **dict(zip(META, (city['name'], station['name'], '*')))}
        for col in columns: row.setdefault(col, None)
        cities.append({'key': key, 'station': station, 'row': row, 'configured': bool(previous), 'zero_confirmed': bool(previous and previous.get('zero_confirmed'))})
    return {'entries': result, 'cities': cities, 'columns': columns, 'version': defaults['version'], 'directory': directory}


def validate_entry(entry, station, columns, retained=None):
    if not isinstance(entry, dict):
        raise SourceError('扣款站点参数无效')
    row = entry.get('row')
    if not isinstance(row, dict) or any(row.get(k) != v for k, v in zip(META, (station['city'], station['name'], station['id']))):
        raise SourceError('站点名称或编号已变化，请重新加载扣款清单')
    retained = retained or {}
    if set(row) != set(META) | set(columns) | set(retained) or any(row[k] != v for k, v in retained.items()):
        raise SourceError('扣款列已变化，请重新加载后确认')
    for col in columns:
        value = row[col]
        if col.endswith('_maxDays') and value is None:
            continue
        if col == '招聘来源' or (col not in DEFAULT_COLUMNS and isinstance(value, (str, bool))):
            if value is None:
                raise SourceError('请明确填写招聘来源配置')
        elif value is None or value == '' or type(value) not in (int, float) or not math.isfinite(value):
            raise SourceError('请填写全部扣款值；未配置的站点不能自动视为零扣款')
    monetary = [row[c] for c in columns if c in DEFAULT_COLUMNS and type(row[c]) in (int, float)]
    keyword_charge = str(row.get('招聘来源') or '').strip() not in ('', '0', '0.0')
    if not any(monetary) and not keyword_charge and entry.get('zero_confirmed') is not True:
        raise SourceError('全零扣款站点需要明确确认零扣款')
    return {'row': row, 'zero_confirmed': entry.get('zero_confirmed') is True}


def save_profile(platform, root, payload, directory):
    if not isinstance(payload, dict) or not isinstance(payload.get('entries', []), list) or not isinstance(payload.get('cities', []), list) or not (payload.get('entries') or payload.get('cities')):
        raise SourceError('请提交已配置的站点扣款清单')
    with LOCK:
        current = profile(platform, root)
        if current['version'] != payload.get('version'):
            raise SourceError('默认扣款已被其他人修改，请重新加载')
        lookup = {station_key(s): s for s in directory['stations']}
        columns = columns_for(platform, root)
        drafts = {e['key']: e for e in station_drafts(platform, root, directory)['entries']}
        city_lookup = {digest([platform, c['id']]): city_station(platform, c) for c in directory.get('cities', [])}
        for entry in payload.get('cities', []):
            if not isinstance(entry, dict) or entry.get('key') not in city_lookup:
                raise SourceError('城市不在当前后台目录中')
            current['cities'][entry['key']] = validate_entry(entry, city_lookup[entry['key']], columns)
        for entry in payload.get('entries', []):
            if not isinstance(entry, dict):
                raise SourceError('扣款站点参数无效')
            key = entry.get('key')
            if key not in lookup:
                raise SourceError('站点已不在当前目录，未覆盖原配置')
            retained = {k: v for k, v in drafts[key]['row'].items() if k not in META and k not in columns}
            validated = validate_entry(entry, lookup[key], columns, retained)
            city_rule = current['cities'].get(digest([platform, lookup[key]['city_id']]))
            if key not in current['entries'] and entry.get('inherited_city') and city_rule and all(validated['row'][c] == city_rule['row'][c] for c in columns) and validated['zero_confirmed'] == city_rule['zero_confirmed']:
                continue
            if not (drafts[key].get('inherited_city') and not entry.get('edited') and validated['row'] == drafts[key]['row']):
                current['entries'][key] = validated
        path = Path(root) / 'data' / 'deduction_profiles' / (platform + '.json')
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists():
            backup = path.parent / 'history' / (platform + '_' + datetime.now().strftime('%Y%m%d_%H%M%S_%f') + '.json')
            backup.parent.mkdir(parents=True, exist_ok=True)
            atomic_json(backup, json.loads(path.read_text(encoding='utf-8')))
        atomic_json(path, {'entries': current['entries'], 'cities': current['cities']})
        return profile(platform, root)


def tables(path, sheet_name=None):
    """Stream retained CSV/XLSX inputs; only the first twelve rows can be headers."""
    suffix = path.suffix.lower()
    if suffix == '.csv':
        encoding = 'utf-8-sig'
        with path.open('rb') as stream:
            sample = stream.read(65536)
        try:
            codecs.getincrementaldecoder('utf-8-sig')().decode(sample, final=False)
        except UnicodeDecodeError:
            encoding = 'gb18030'
        with path.open(encoding=encoding, newline='') as stream:
            yield csv.reader(stream)
    elif suffix == '.xlsx':
        book = load_workbook(path, read_only=True, data_only=True)
        try:
            for sheet in book:
                if sheet_name and sheet.title != sheet_name:
                    continue
                sheet.reset_dimensions()
                yield sheet.iter_rows(values_only=True)
        finally:
            book.close()
    elif suffix == '.xls':
        import pandas as pd
        with pd.ExcelFile(path, engine='calamine') as book:
            for name in book.sheet_names:
                if sheet_name and name != sheet_name:
                    continue
                yield book.parse(name, header=None).fillna('').itertuples(index=False, name=None)
    else:
        raise SourceError('核对清单不支持此资料格式，请补传可核对的账单')


def affiliations(path, with_station_id=False, sheet_name=None):
    found = False
    for rows in tables(path, sheet_name):
        iterator = iter(rows)
        for offset, row in enumerate(iterator):
            headers = [str(v or '').strip().lower() for v in row]
            rid = next((headers.index(name.lower()) for name in RID if name.lower() in headers), None)
            team = next((headers.index(name.lower()) for name in TEAM if name.lower() in headers), None)
            site = next((headers.index(name.lower()) for name in ('团队ID','站点ID','骑手所属站点ID','siteId') if name.lower() in headers), None)
            if rid is not None and team is not None:
                found = True
                for number, value in enumerate(iterator, offset + 2):
                    if len(value) > max(rid, team) and identifier(value[rid]):
                        base = (identifier(value[rid]), str(value[team] or '').strip(), number)
                        yield (*base, identifier(value[site]) if site is not None and len(value)>site else '') if with_station_id else base
                break
            if offset >= 11:
                break
    if not found:
        raise SourceError('资料未提供可核对的骑手编号和站点列')


def input_signature(state):
    # Relative file names and expected bytes are already verified again at claim time.
    basis = {'template': state['template_hash'], 'items': state['items'], 'all_files': state.get('all_files', []), 'plan': state['plan']}
    if state.get('station_links'): basis['station_links'] = state['station_links']
    return digest(basis)


def preflight(folder, state, root, directory, city_id=''):
    from payroll_inputs import checked_inputs
    intent = state['mode'] == 'fengshen' and state['status'] in ('awaiting_confirmation', 'pending_download') and not state.get('jobs')
    if intent:
        from payroll_inputs import digest as file_digest
        inputs = folder / 'input'
        if file_digest(inputs / state['plan']['template']) != state['template_hash']:
            raise SourceError('申请表已变化，请重新上传')
    else:
        inputs = checked_inputs(folder, state)
    applicants = list(affiliations(inputs / state['plan']['template'], True, '申请名单'))
    if not applicants or any(not team for _, team, _, _ in applicants):
        raise SourceError('申请名单有空白团队名称，请补齐后重新上传')
    ids = {rid for rid, _, _, _ in applicants}
    selected_city = state['plan']['city']
    if city_id:
        choices = [c for c in directory['cities'] if c['id'] == city_id]
        if len(choices) != 1:
            raise SourceError('请选择当前后台目录中的城市')
        selected_city = choices[0]['name']
    elif state['mode'] == 'xiaoxiang' and selected_city not in {c['name'] for c in directory.get('cities', [])}:
        # 小象等平台伪城市：不按城市过滤，跨账号城市匹配站点。
        selected_city = ''
    hints = {}
    for _, name, _, code in applicants:
        if code:
            hints.setdefault(name, set()).add(code)
    actual = {}
    actual_codes = {}
    bill_item = state['items']['delivery_fee']
    bill_files = bill_item.get('files', [bill_item])
    gaps = []
    for entry in ([] if intent else bill_files):
        try:
            for rid, team, _, code in affiliations(inputs / entry['file'], True):
                if rid in ids and team:
                    actual.setdefault(rid, set()).add(team)
                    if code:
                        hints.setdefault(team, set()).add(code)
                        actual_codes.setdefault(rid, set()).add(code)
        except SourceError as error:
            gaps.append(str(error))
    names = {team for _, team, _, _ in applicants}
    names.update(team for values in actual.values() for team in values)
    drafts = station_drafts(platform_for(state), root, directory)
    selected = []
    unresolved = []
    links = state.get('station_links', {})
    linked = []
    resolved = {}
    from station_associations import load as load_associations, remembered, has_history, compatible, recommendation, scope
    associations = load_associations(root, platform_for(state))
    association_rows = []
    for name in sorted(names):
        candidates = [e for e in drafts['entries'] if (not selected_city or e['station']['city'] == selected_city) and compatible(name, e['station'])
                      and (not hints.get(name) or (len(hints[name]) == 1 and hints[name] & station_codes(e['station'])))]
        method = 'name'
        history_invalid = False
        matches = [e for e in candidates if normalize(e['station']['name']) == normalize(name)]
        if hints.get(name):
            matches = candidates
            method = 'id'
        elif name not in links:
            previous = remembered(associations, directory, name, candidates)
            if previous:
                matches = [previous]
                method = 'history'
            elif has_history(associations, directory, selected_city, name):
                matches = []
                history_invalid = True
        if name in links:
            matches = [e for e in candidates if e['key'] == links[name]]
            method = 'manual'
        row = {'name': name, 'candidates': [e['key'] for e in candidates], 'method': method}
        if len(matches) != 1:
            code = 'ambiguous' if len(matches) > 1 else 'id_conflict' if hints.get(name) and (not candidates or name in links) else 'history_invalid' if history_invalid else 'missing'
            reason = {'ambiguous': '有多个同名候选，请按编号确认归属', 'id_conflict': '站点编号存在冲突或未在当前目录找到，请同步或核对申请编号', 'history_invalid':'历史关联站点已失效或类型变化，请重新确认', 'missing': '申请名称未匹配后台站点，请同步目录或确认关联后台真实站点'}[code]
            suggestions = recommendation(name, candidates, selected_city) if code != 'id_conflict' else []
            row.update(reason=reason, code=code, recommendations=suggestions, key='', status='unresolved')
            unresolved.append(row)
        else:
            entry = matches[0]
            resolved[name] = entry['key']
            row.update(key=entry['key'], status='resolved', reason={'id':'编号一致','history':'历史已确认','manual':'本次已确认','name':'名称一致'}[method])
            if name in links or normalize(name) != normalize(entry['station']['name']):
                linked.append({'name': name, 'key': entry['key'], 'station': entry['station'], 'method': method})
            if entry['key'] not in {e['key'] for e in selected}: selected.append(entry)
        association_rows.append(row)
    # The current engine matches normalized team names. Two IDs must never share one rule.
    seen = set()
    for entry in selected:
        name = normalize(entry['station']['name'])
        if name in seen:
            raise SourceError('本批次存在同名站点，当前核算规则无法唯一匹配，请先核对站点名称')
        seen.add(name)
    identities = {normalize(e['station']['name']): e['key'] for e in selected}
    for alias in linked:
        name = normalize(alias['name'])
        if name in identities and identities[name] != alias['key']:
            raise SourceError('关联名称与其他站点的核算名称冲突，请核对归属')
        identities[name] = alias['key']
    differences = []
    for rid, team, number, application_code in ([] if intent else applicants):
        observed = actual.get(rid, set())
        code_difference = bool(application_code and actual_codes.get(rid) and actual_codes[rid] != {application_code})
        same_identity = bool(observed and resolved.get(team) and all(resolved.get(name) == resolved[team] for name in observed))
        if not observed or (not same_identity and {normalize(v) for v in observed} != {normalize(team)}) or code_difference:
            differences.append({'id': digest([number, rid, team, sorted(observed), application_code, sorted(actual_codes.get(rid, set()))]), 'row': number, 'application': team,
                                'bill': sorted(observed), 'reason': '申请与账单站点编号不同' if code_difference else '申请与账单站点不同' if observed else '账单未提供此申请人的可核对站点'})
    basis = {'inputs': input_signature(state), 'directory_version': directory['session_version'],
             'directory': [s for s in directory['stations'] if not selected_city or s['city'] == selected_city], 'directory_city': selected_city, 'default_version': drafts['version'],
             'draft_values': [{'key': e['key'], 'row': e['row']} for e in selected], 'columns': drafts['columns'],
             'differences': differences, 'unresolved': unresolved, 'associations': association_rows,
             'association_version': associations['version'], 'account_scope': scope(directory)}
    separation = sorted(name for name in names if '取分离' in name)
    return {**drafts, 'association_rows': association_rows, 'association_version': associations['version'], 'association_reusable': bool(scope(directory)), 'linked_stations': linked, 'station_choices': [e for e in drafts['entries'] if not selected_city or e['station']['city'] == selected_city], 'separation_stations': separation, 'separation_enabled': bool(state.get('include_separation')), 'stage': 'intent' if intent else 'final', 'entries': selected, 'differences': differences, 'unresolved': unresolved,
            'warnings': sorted(set(gaps)), 'review_version': digest(basis), 'input_signature': basis['inputs']}


def confirm(folder, state, root, directory, payload):
    from workbench import version
    if not isinstance(payload, dict):
        raise SourceError('扣款确认参数无效')
    reviewed = preflight(folder, state, root, directory, payload.get('city_id', ''))
    if payload.get('review_version') != reviewed['review_version']:
        raise SourceError('资料、站点目录或默认金额已变化，请重新核对扣款清单')
    if reviewed['unresolved']:
        raise SourceError('有站点归属尚未匹配，核算已暂停')
    if reviewed['separation_stations'] and not state.get('include_separation') and state['mode'] == 'fengshen':
        raise SourceError('申请名单含取分离站点，请先启用关联取分离站点')
    accepted = payload.get('accepted_differences', [])
    if set(accepted) != {d['id'] for d in reviewed['differences']}:
        raise SourceError('请逐项核对申请名单与账单站点差异')
    if payload.get('confirmed') is not True:
        raise SourceError('请明确确认本次扣款清单')
    submitted = payload.get('entries', [])
    if not isinstance(submitted, list) or any(not isinstance(e, dict) for e in submitted):
        raise SourceError('扣款站点参数无效')
    expected = {e['key']: e for e in reviewed['entries']}
    if len(submitted) != len(expected) or {e.get('key') for e in submitted} != set(expected):
        raise SourceError('本次站点清单不完整或重复')
    rows = [validate_entry(e, expected[e['key']]['station'], reviewed['columns'],
                           {k:v for k,v in expected[e['key']]['row'].items() if k not in META and k not in reviewed['columns']})['row'] for e in submitted]
    if not rows:
        raise SourceError('本次没有已确认的扣款站点')
    if payload.get('save_defaults') is True:
        # Authorization is enforced by the route before any default write.
        save_profile(platform_for(state), root, {'entries': submitted, 'cities': payload.get('cities', []), 'version': reviewed['version']}, directory)
    # Aliases are batch-only calculation rules; source sheets and shared defaults keep official identity.
    canonical = {entry['key']: row for entry, row in zip(submitted, rows)}
    existing = {normalize(row['团队名称']) for row in rows}
    for link in reviewed['linked_stations']:
        if normalize(link['name']) not in existing:
            rows.append({**canonical[link['key']], '团队名称': link['name']})
            existing.add(normalize(link['name']))
    deduction = {'rows': rows, 'version': version(rows), 'scope': 'batch', 'frozen': False}
    receipt = {'rules_version': deduction['version'], 'input_signature': reviewed['input_signature'],
               'accepted_differences': sorted(accepted), 'confirmed_at': datetime.now(timezone.utc).isoformat(),
               'directory_version': directory['session_version'], 'stage': reviewed['stage'],
               'city_id': payload.get('city_id', ''), 'template_hash': state['template_hash'],
               'plan': state['plan'], 'entries': submitted, 'station_links': state.get('station_links', {}),
               'association_resolution': {r['name']:r['key'] for r in reviewed['association_rows'] if r['key']}}
    return deduction, receipt


def finalize_intent(folder, state, root, directory):
    """Bind approved amounts to collected files; never accept new sites or differences."""
    from workbench import version
    intent = state.get('deduction_intent') or {}
    deduction = state.get('deductions') or {}
    if (intent.get('stage') != 'intent' or intent.get('template_hash') != state['template_hash']
            or intent.get('plan') != state['plan'] or intent.get('station_links', {}) != state.get('station_links', {}) or version(deduction.get('rows', [])) != intent.get('rules_version')):
        raise SourceError('申请或扣款金额已变化，请重新确认扣款清单')
    reviewed = preflight(folder, state, root, directory, intent.get('city_id', ''))
    approved = {e['key']: e for e in intent['entries']}
    current = {e['key']: e for e in reviewed['entries']}
    if reviewed['differences'] or reviewed['unresolved'] or set(approved) != set(current):
        raise SourceError('下载后的账单与申请站点存在差异，请确认归属和扣款后继续')
    resolution = {r['name']:r['key'] for r in reviewed['association_rows']}
    if any(resolution.get(name) != target for name,target in intent.get('association_resolution', {}).items()):
        raise SourceError('站点关联已变化，请重新确认归属和扣款')
    rule_names = {normalize(row['团队名称']) for row in deduction['rows']}
    if any(normalize(name) not in rule_names for name in resolution):
        raise SourceError('账单新增站点名称，请确认关联及扣款后继续')
    for key, entry in approved.items():
        if any(entry['row'][col] != current[key]['row'][col] for col in META):
            raise SourceError('后台站点身份已变化，请重新确认扣款清单')
    # Defaults may have changed while downloading. This batch keeps exactly the approved rows.
    state['deduction_confirmation'] = {**intent, 'stage': 'final', 'input_signature': input_signature(state),
                                       'directory_version': directory['session_version']}


def require_confirmation(state, expected_version):
    from workbench import version
    deduction = state.get('deductions', {})
    receipt = state.get('deduction_confirmation') or {}
    if receipt.get('stage') == 'intent' or not expected_version or expected_version != deduction.get('version') or receipt.get('rules_version') != expected_version:
        raise SourceError('请先确认本批次扣款清单，再开始核算')
    if version(deduction.get('rows', [])) != expected_version or receipt.get('input_signature') != input_signature(state):
        raise SourceError('资料或扣款金额已变化，请重新确认扣款清单')
