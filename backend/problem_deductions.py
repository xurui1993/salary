"""Problem-order deduction rules shared by payroll configuration and calculation."""
import hashlib
import json
import math
import re

PROBLEM_ITEM = '问题单扣款'
MAX_RULES = 10000
MAX_TYPE = 80
MAX_REASON = 120
MAX_AMOUNT = 10_000_000


class ProblemRuleError(ValueError):
    pass


def normalize_team(value):
    return re.sub(r'_?新专送', '', str(value or '').strip())


def _text(value, limit, label, required=True):
    text = str(value or '').strip()
    if required and not text:
        raise ProblemRuleError(f'{label}不能为空')
    if len(text) > limit:
        raise ProblemRuleError(f'{label}不能超过 {limit} 个字符')
    if any(ord(char) < 32 for char in text):
        raise ProblemRuleError(f'{label}包含无效字符')
    return text


def amount(value):
    if isinstance(value, bool) or value is None:
        raise ProblemRuleError('单次扣款金额必须是数字')
    if isinstance(value, str):
        text = value.strip().replace(',', '').replace('，', '').replace('¥', '').replace('￥', '')
        if not text:
            raise ProblemRuleError('单次扣款金额不能为空')
        try:
            value = float(text)
        except ValueError:
            raise ProblemRuleError('单次扣款金额必须是数字') from None
    if type(value) not in (int, float) or not math.isfinite(value):
        raise ProblemRuleError('单次扣款金额必须是有效数字')
    if abs(value) > MAX_AMOUNT:
        raise ProblemRuleError(f'单次扣款金额不能超过 {MAX_AMOUNT}')
    return int(value) if float(value).is_integer() else round(float(value), 2)


def normalize_rule(rule):
    if not isinstance(rule, dict):
        raise ProblemRuleError('问题单扣款规则格式无效')
    problem_type = _text(rule.get('problem_type', rule.get('问题单类型', rule.get('问题类型'))), MAX_TYPE, '问题单类型')
    reason = _text(rule.get('reason_keyword', rule.get('判责原因关键词', rule.get('判责原因', rule.get('原因')))), MAX_REASON,
                   '判责原因关键词', required=False)
    return {'problem_type': problem_type, 'reason_keyword': reason,
            'amount': amount(rule.get('amount', rule.get('单次扣款金额', rule.get('扣款金额'))))}


def sorted_rules(rules):
    return sorted((normalize_rule(rule) for rule in rules or []),
                  key=lambda rule: (rule['problem_type'], rule['reason_keyword'], rule['amount']))


def effective_rules(city_rules, station_rules):
    """Station rules override city defaults with the same type and reason."""
    merged = {}
    for rule in [*(city_rules or []), *(station_rules or [])]:
        normalized = normalize_rule(rule)
        merged[(normalized['problem_type'], normalized['reason_keyword'])] = normalized
    return sorted(merged.values(), key=lambda rule: (rule['problem_type'], rule['reason_keyword'], rule['amount']))


def match_amount(rules, problem_type, reason):
    actual_type = normalize_team(problem_type)
    actual_reason = normalize_team(reason).casefold()
    best = None
    best_key = None
    for rule in rules or []:
        try:
            normalized = normalize_rule(rule)
        except ProblemRuleError:
            continue
        rule_type = normalize_team(normalized['problem_type'])
        if not rule_type:
            continue
        if actual_type == rule_type:
            score = 4
        elif rule_type in actual_type:
            score = 2
        elif actual_type and actual_type in rule_type:
            score = 1
        else:
            continue
        reason_text = normalize_team(normalized['reason_keyword']).casefold()
        if reason_text:
            if not actual_reason or reason_text not in actual_reason:
                continue
            score += 3
        candidate_key = (score, len(rule_type), len(reason_text))
        if best_key is None or candidate_key > best_key:
            best = normalized
            best_key = candidate_key
    return None if best is None else best['amount']


def station_key(platform, city_id, station_id):
    return hashlib.sha256(json.dumps([platform, str(city_id), str(station_id)],
                                     ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                     allow_nan=False).encode()).hexdigest()
