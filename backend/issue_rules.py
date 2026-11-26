"""问题单判定条件：按城市配置的条件组合规则。

默认配置与原有写死逻辑等价（大润发排除、三亚大润发计入、普通单 480 秒宽容、
预订单/星专送/开放平台严格判定），并内置「二呼单且未超骑手T 不计入不准时单」。
"""
import copy
import json
import math
from pathlib import Path

CATEGORY = '不准时单'
VERSION = 1
PLATFORM = 'fengshen'
MAX_RULES = 50
MAX_CONDITIONS = 20
MAX_FIELD = 40
MAX_VALUE = 200
MAX_LIST = 50
MAX_GRACE = 3600
OPS = ('eq', 'neq', 'contains', 'not_contains', 'in', 'not_in',
       'gt', 'gte', 'lt', 'lte', 'between', 'is_blank', 'is_not_blank')

DEFAULT_CONFIG = {
    'version': VERSION,
    'grace_seconds': 480,
    'strict_conditions': [
        {'field': '运单类型', 'op': 'eq', 'value': '预订单'},
        {'field': '配送标品', 'op': 'eq', 'value': '星专送'},
        {'field': '订单来源', 'op': 'eq', 'value': '开放平台'},
    ],
    'rules': [
        {'id': 'exclude-darunfa', 'name': '大润发不计入不准时单', 'action': 'exclude', 'when': [],
         'conditions': [{'field': '站点名称', 'op': 'contains', 'value': '大润发'}]},
        {'id': 'exclude-second-call', 'name': '二呼单且未超骑手T不计入', 'action': 'exclude', 'when': [],
         'conditions': [{'field': '是否二呼单', 'op': 'eq', 'value': '是'},
                        {'field': '是否超骑手T', 'op': 'eq', 'value': '否'}]},
        {'id': 'include-sanya-darunfa', 'name': '三亚大润发超骑手T计入', 'action': 'include',
         'when': [{'field': '站点名称', 'op': 'contains', 'value': '三亚'}],
         'conditions': [{'field': '站点名称', 'op': 'contains', 'value': '大润发'},
                        {'field': '是否超骑手T', 'op': 'eq', 'value': '是'}]},
    ],
}


class IssueRuleError(ValueError):
    pass


def default_config():
    return normalize_config(copy.deepcopy(DEFAULT_CONFIG))


def _text(value, limit, label, required=True):
    text = '' if value is None else str(value).strip()
    if required and not text:
        raise IssueRuleError(f'{label}不能为空')
    if len(text) > limit:
        raise IssueRuleError(f'{label}不能超过 {limit} 个字符')
    if any(ord(char) < 32 or ord(char) == 127 for char in text):
        raise IssueRuleError(f'{label}包含无效字符')
    return text


def _scalar(value):
    if isinstance(value, bool) or value is None:
        raise IssueRuleError('判定值无效')
    if isinstance(value, (int, float)):
        if not math.isfinite(value):
            raise IssueRuleError('判定值无效')
        return value
    return _text(value, MAX_VALUE, '判定值')


def _number(value):
    if isinstance(value, bool) or value is None:
        raise IssueRuleError('判定阈值必须是数字')
    if isinstance(value, str):
        try:
            value = float(value.strip())
        except ValueError:
            raise IssueRuleError('判定阈值必须是数字') from None
    if not isinstance(value, (int, float)) or not math.isfinite(value):
        raise IssueRuleError('判定阈值必须是数字')
    return value


def normalize_condition(condition):
    if not isinstance(condition, dict):
        raise IssueRuleError('判定条件格式无效')
    field = _text(condition.get('field'), MAX_FIELD, '判定字段')
    op = condition.get('op')
    if op not in OPS:
        raise IssueRuleError('判定运算符无效')
    if op in ('is_blank', 'is_not_blank'):
        return {'field': field, 'op': op}
    if op in ('in', 'not_in'):
        values = condition.get('value')
        if not isinstance(values, list) or not 0 < len(values) <= MAX_LIST:
            raise IssueRuleError(f'判定值列表需为 1-{MAX_LIST} 项')
        return {'field': field, 'op': op, 'value': [_scalar(item) for item in values]}
    if op == 'between':
        low, high = _number(condition.get('value')), _number(condition.get('value2'))
        return {'field': field, 'op': op, 'value': min(low, high), 'value2': max(low, high)}
    return {'field': field, 'op': op, 'value': _scalar(condition.get('value'))}


def normalize_rule(rule):
    if not isinstance(rule, dict):
        raise IssueRuleError('判定规则格式无效')
    action = rule.get('action')
    if action not in ('exclude', 'include'):
        raise IssueRuleError('判定规则动作无效')
    conditions = rule.get('conditions')
    if not isinstance(conditions, list) or not 0 < len(conditions) <= MAX_CONDITIONS:
        raise IssueRuleError(f'每条规则需 1-{MAX_CONDITIONS} 个判定条件')
    when = rule.get('when') or []
    if not isinstance(when, list) or len(when) > MAX_CONDITIONS:
        raise IssueRuleError(f'触发条件不能超过 {MAX_CONDITIONS} 个')
    return {
        'id': _text(rule.get('id'), 60, '规则标识', required=False),
        'name': _text(rule.get('name'), 60, '规则名称', required=False),
        'action': action,
        'when': [normalize_condition(item) for item in when],
        'conditions': [normalize_condition(item) for item in conditions],
    }


def normalize_config(config):
    if not isinstance(config, dict):
        raise IssueRuleError('判定规则格式无效')
    grace = config.get('grace_seconds', 480)
    if isinstance(grace, bool) or not isinstance(grace, (int, float)) or not math.isfinite(grace) \
            or not 0 <= grace <= MAX_GRACE or float(grace) != int(grace):
        raise IssueRuleError(f'宽容时长需为 0-{MAX_GRACE} 的整数秒')
    strict = config.get('strict_conditions', [])
    if not isinstance(strict, list) or len(strict) > MAX_CONDITIONS:
        raise IssueRuleError(f'严格判定条件不能超过 {MAX_CONDITIONS} 个')
    rules = config.get('rules', [])
    if not isinstance(rules, list) or len(rules) > MAX_RULES:
        raise IssueRuleError(f'判定规则不能超过 {MAX_RULES} 条')
    return {
        'version': VERSION,
        'grace_seconds': int(grace),
        'strict_conditions': [normalize_condition(item) for item in strict],
        'rules': [normalize_rule(item) for item in rules],
    }


def city_name(value):
    return _text(value, 80, '城市')


def _config_path(platform=PLATFORM):
    from workspace_context import workspace_data_root
    return Path(workspace_data_root()) / 'data' / 'issue_rules' / (platform + '.json')


def load(platform=PLATFORM):
    path = _config_path(platform)
    data = {'version': VERSION, 'cities': {}}
    if not path.exists():
        return data
    if path.is_symlink() or path.parent.is_symlink():
        raise IssueRuleError('判定规则配置路径异常')
    try:
        raw = json.loads(path.read_text(encoding='utf-8-sig'))
        if not isinstance(raw, dict) or not isinstance(raw.get('cities'), dict):
            raise ValueError()
        data['cities'] = {city_name(city): normalize_config(config) for city, config in raw['cities'].items()}
    except IssueRuleError:
        raise
    except (OSError, ValueError):
        raise IssueRuleError('判定规则配置无法读取，请检查原文件') from None
    return data


def save_city(city, config, platform=PLATFORM):
    city = city_name(city)
    normalized = normalize_config(config)
    data = load(platform)
    data['cities'][city] = normalized
    path = _config_path(platform)
    path.parent.mkdir(parents=True, exist_ok=True)
    from fengshen_bill import atomic_json
    atomic_json(path, data)
    return normalized


def reset_city(city, platform=PLATFORM):
    city = city_name(city)
    data = load(platform)
    if city in data['cities']:
        del data['cities'][city]
        path = _config_path(platform)
        from fengshen_bill import atomic_json
        atomic_json(path, data)


def resolve(data, city):
    return (data.get('cities') or {}).get(city) or default_config()


def config_for(city, platform=PLATFORM):
    return resolve(load(platform), city)


# ---------------------------------------------------------------- evaluation

def _text_series(series):
    return series.map(lambda value: '' if value is None else str(value).strip())


def _blank_mask(series):
    return series.isna() | _text_series(series).eq('')


def _numeric(series):
    import pandas as pd
    return pd.to_numeric(series, errors='coerce')


def _equals(series, value):
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return _numeric(series).eq(float(value))
    return _text_series(series).eq(str(value).strip())


def _condition_mask(frame, condition, warnings):
    import pandas as pd
    field = condition['field']
    if field not in frame.columns:
        warnings.add(field)
        return pd.Series(False, index=frame.index)
    series = frame[field]
    op = condition['op']
    if op == 'is_blank':
        return _blank_mask(series)
    if op == 'is_not_blank':
        return ~_blank_mask(series)
    if op in ('in', 'not_in'):
        mask = pd.Series(False, index=frame.index)
        for item in condition['value']:
            mask |= _equals(series, item)
        if op == 'not_in':
            mask = ~mask & ~_blank_mask(series)
        return mask
    if op == 'eq':
        return _equals(series, condition['value'])
    if op == 'neq':
        return ~_equals(series, condition['value']) & ~_blank_mask(series)
    if op in ('contains', 'not_contains'):
        mask = _text_series(series).str.contains(str(condition['value']).strip(), regex=False, na=False)
        return mask if op == 'contains' else ~mask & ~_blank_mask(series)
    numbers = _numeric(series)
    value = condition['value']
    if op == 'gt':
        return numbers.gt(value)
    if op == 'gte':
        return numbers.ge(value)
    if op == 'lt':
        return numbers.lt(value)
    if op == 'lte':
        return numbers.le(value)
    return numbers.between(value, condition['value2'], inclusive='both')


def conditions_mask(frame, conditions, warnings):
    import pandas as pd
    mask = pd.Series(True, index=frame.index)
    for condition in conditions:
        mask &= _condition_mask(frame, condition, warnings)
    return mask


def conditions_any_mask(frame, conditions, warnings):
    import pandas as pd
    mask = pd.Series(False, index=frame.index)
    for condition in conditions:
        mask |= _condition_mask(frame, condition, warnings)
    return mask


def exclude_mask(frame, config, warnings):
    import pandas as pd
    mask = pd.Series(False, index=frame.index)
    for rule in config.get('rules', []):
        if rule['action'] == 'exclude':
            mask |= conditions_mask(frame, rule['conditions'], warnings)
    return mask


def include_mask(raw_frame, selected_frame, config, warnings):
    import pandas as pd
    mask = pd.Series(False, index=raw_frame.index)
    for rule in config.get('rules', []):
        if rule['action'] != 'include':
            continue
        if rule.get('when') and not conditions_mask(selected_frame, rule['when'], warnings).any():
            continue
        mask |= conditions_mask(raw_frame, rule['conditions'], warnings)
    return mask


# ------------------------------------------------------------------ preview

def preview(frame, candidate, baseline=None):
    """Compare the saved rules against a candidate config on one waybill sample."""
    import pandas as pd
    from issue_orders import DataCleaner
    empty = pd.DataFrame(columns=['日期', '违规状态', '申诉状态'])

    def run(config):
        cleaner = DataCleaner.from_frames(frame, empty, copy=True)
        cleaner.issue_rules = config
        rows = cleaner.notpunctual()
        return rows, cleaner.rule_warnings

    before, _ = run(baseline or default_config())
    candidate = normalize_config(candidate)
    after, warnings = run(candidate)
    sample = []
    if '运单id' in after.columns:
        sample = [str(value) for value in after['运单id'].head(5).tolist()]
    return {
        'before': int(len(before)),
        'after': int(len(after)),
        'delta': int(len(after) - len(before)),
        'warnings': sorted(warnings),
        'sample_ids': sample,
    }


def preview_sample(owner, payload, city, platform=PLATFORM):
    """Preview candidate rules against the latest retained waybill sample."""
    from download_jobs import DownloadNotFound, get_manager
    from order_sources import WAYBILL_COLUMNS, read_table
    try:
        sample = get_manager().order_sample_dir(owner, city)
    except DownloadNotFound as error:
        raise IssueRuleError(str(error)) from None
    frame = read_table(sample['path'], WAYBILL_COLUMNS)
    result = preview(frame, payload, resolve(load(platform), city))
    result['sample'] = {
        'run_id': sample['run_id'],
        'start': sample.get('start'),
        'end': sample.get('end'),
        'file': sample['path'].name,
        'rows': int(len(frame)),
    }
    return result