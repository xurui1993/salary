"""City/month-isolated inputs for the existing payment-binding generator."""
import asyncio
import datetime as dt
import hashlib
import hashlib_compat
import json
import re
from pathlib import Path
import shutil
import threading

import pandas as pd
from generation_performance import profiled, read_frame, stage, capture_tables
from fengshen_bill import BillCollectionError, MonthlyBillRequest, atomic_json


def month_periods(start, end):
    first, last = dt.date.fromisoformat(start), dt.date.fromisoformat(end)
    result = []
    cursor = first.replace(day=1)
    while cursor <= last:
        next_month = (cursor.replace(day=28) + dt.timedelta(days=4)).replace(day=1)
        result.append((cursor.strftime('%Y-%m'), max(first, cursor).isoformat(),
                       min(last, next_month - dt.timedelta(days=1)).isoformat()))
        cursor = next_month
    return result


def city_key(value):
    value = str(value or '').strip()
    return value[:-1] if value.endswith('市') else value


def approved_proxies(frame, city, month):
    required = {'城市名称', '代领月份', '流程状态', '启停用', '骑手身份证', '代领人身份证'}
    if not required.issubset(frame.columns):
        raise BillCollectionError('蓝橙代领原始文件缺少月份、城市、状态或身份证字段')
    frame = frame.fillna('').copy()
    frame.columns = frame.columns.map(lambda value: str(value).strip())
    for column in required:
        frame[column] = frame[column].astype(str).str.strip()
    frame = frame.loc[frame['城市名称'].map(city_key).eq(city_key(city))
                      & frame['代领月份'].str[:7].eq(month)
                      & frame['流程状态'].isin(['审核通过', '审批中']) & frame['启停用'].eq('启用')].copy()
    # Resolve workflow priority before considering the lower-priority payee.
    # Conflicting recipients within the chosen priority remain a hard failure.
    approved = set(frame.loc[frame['流程状态'].eq('审核通过'), '骑手身份证'].str.upper())
    frame = frame.loc[frame['流程状态'].eq('审核通过') | ~frame['骑手身份证'].str.upper().isin(approved)].copy()
    for column in ('骑手身份证', '代领人身份证'):
        frame[column] = frame[column].str.upper()
        if not frame[column].str.fullmatch(r'\d{17}[\dX]').all():
            raise BillCollectionError('已通过或审批中且启用的代领记录身份证缺失或格式异常，请核对蓝橙资料')
    if frame.groupby('骑手身份证')['代领人身份证'].nunique().gt(1).any():
        raise BillCollectionError('同城市同月份骑手存在不同代领人，已停止该城市生成，请核对蓝橙代领记录')
    return frame.drop_duplicates().drop_duplicates(subset=['骑手身份证', '代领人身份证']).reset_index(drop=True)


def eligible_details(frame, plan):
    from order_dates import natural_dates
    required = {'骑手ID', '日期', '团队名称', '有效完成单'}
    if not required.issubset(frame.columns):
        raise BillCollectionError('骑手数据明细缺少日期、骑手ID、团队名称或有效完成单')
    frame = frame.fillna('').copy()
    dates = natural_dates(frame['日期'])
    if not dates.between(plan.start, plan.end).all():
        raise BillCollectionError('支付绑定骑手明细超出本次城市月份周期')
    ids = frame['骑手ID'].astype(str).str.strip()
    if not ids.str.fullmatch(r'\d{1,20}').all():
        raise BillCollectionError('支付绑定骑手明细存在缺失或异常骑手ID')
    frame['骑手ID'], frame['日期'] = ids, dates
    values = pd.to_numeric(frame['有效完成单'], errors='coerce')
    if values.isna().any() or values.lt(0).any() or values.mod(1).ne(0).any():
        raise BillCollectionError('有效完成单包含缺失或异常数值，不能按零处理')
    frame['有效完成单'] = values
    keys = ['日期', '骑手ID'] + (['团队ID'] if '团队ID' in frame else ['团队名称'])
    duplicate = frame.duplicated(keys, keep=False)
    for _, group in frame.loc[duplicate].groupby(keys):
        if len(group.drop_duplicates()) != 1:
            raise BillCollectionError('同日同骑手同团队明细存在冲突，已停止生成')
    frame = frame.drop_duplicates(keys)
    positive = frame.groupby('骑手ID')['有效完成单'].sum().loc[lambda value: value > 0].index
    frame = frame.loc[frame['骑手ID'].isin(positive)].copy()
    if frame['团队名称'].astype(str).str.strip().eq('').any():
        raise BillCollectionError('有单骑手缺少团队名称，无法沿用现有城市归属规则')
    frame['城市'] = plan.city
    return frame


@profiled('payment_binding', 4, 'raw')
def generate_binding(paths, employees, proxies, plan, raw, log, cancelled):
    from salary_bind_processor import _read_file_fast, run_salary_bind_gen
    raw = Path(raw)
    inputs, outputs = raw / 'inputs', raw / 'generated'
    inputs.mkdir()
    outputs.mkdir()
    from salary_bind_processor import process_rider_detail_df
    from concurrent.futures import ThreadPoolExecutor
    from contextvars import copy_context
    with stage('prepare_inputs'):
        details = eligible_details(read_frame(paths['rider_detail'], _read_file_fast), plan)
        selected_proxies = approved_proxies(read_frame(proxies, _read_file_fast), plan.city, plan.month)
        # Match the established CSV->reader normalization without writing that CSV.
        prepared = {'骑手数据明细.csv': process_rider_detail_df(details.fillna('').astype(str).copy()),
                    '薪资代领.csv': selected_proxies.fillna('').astype(str).copy()}
        sources = [(paths['rider_info'], '骑手信息.csv'), (paths['receive_account'], '收薪账户.csv'),
                   (employees, 'merchantFreelancer_白泽全量.csv')]
        with ThreadPoolExecutor(max_workers=3) as readers:
            futures = [(name, readers.submit(copy_context().run, read_frame, source, _read_file_fast))
                       for source, name in sources]
            for name, future in futures:
                prepared[name] = future.result()
        atomic_json(inputs / 'input_manifest.json', {'mode': 'verified_in_memory',
                    'source_files_retained': True, 'detail_rows': len(details), 'proxy_rows': len(selected_proxies)})
    scope = {'month': plan.month, 'start': plan.start, 'end': plan.end,
             'team_cities': {re.sub(r'[\s\u200b\u200c\u200d\u2060\ufeff]+', '', str(team)).replace('（', '(').replace('）', ')'):
                             plan.city for team in details['团队名称'].unique()}}
    final = {}
    async def run():
        async for event in run_salary_bind_gen(str(inputs), str(outputs), verified_scope=scope, prepared_inputs=prepared, table_sink=capture_tables()):
            if cancelled.is_set():
                raise BillCollectionError('支付绑定生成已取消')
            if not event.startswith('data: '):
                continue
            value = json.loads(event[6:])
            if value.get('type') == 'finish':
                final.update(value)
    asyncio.run(run())
    file = final.get('out_file', '')
    if final.get('error') or not file or not Path(file).is_file() or not Path(file).resolve().is_relative_to(outputs.resolve()):
        raise BillCollectionError('现有支付绑定生成器未成功生成成品，原始资料已保留')
    stats = final.get('stats', {})
    if len(details) and stats.get('overall', {}).get('total_riders') != details['骑手ID'].nunique():
        raise BillCollectionError('支付绑定成品人数与本次有效完成单骑手范围不一致')
    if not stats:
        zero = {key: 0 for key in ('total_riders', 'total_orders', 'fengshen_bind_count', 'shangyi_bind_count',
                                    'fully_bound_count', 'black_count')}
        zero.update(fengshen_bind_rate='0.00%', shangyi_bind_rate='0.00%', stations=[])
        stats = {'overall': {key: value for key, value in zero.items() if key != 'stations'},
                 'cities': {plan.city: dict(zero)}}
    for field in ('fengshen_bind_count', 'shangyi_bind_count'):
        stats['cities'][plan.city][field] = stats['overall'][field]
    stats.update(month=f'{plan.month[:4]}年{plan.month[5:]}月',
                 source_range={'start': plan.start, 'end': plan.end}, source='download_center')
    atomic_json(raw / 'binding_stats.json', stats)
    layout = final.get('layout')
    if isinstance(layout, dict) and layout:
        with open(file, 'rb') as stream:
            digest = hashlib.file_digest(stream, 'sha256').hexdigest()
        atomic_json(raw / 'binding_layout.json', {'sha256': digest, 'sheets': layout})
    atomic_json(raw / 'binding_proof.json', {'city': plan.city, 'month': plan.month, 'start': plan.start,
                'end': plan.end, 'positive_riders': int(details['骑手ID'].nunique()),
                'eligible_enabled_proxy_rows': len(selected_proxies),
                'approved_enabled_proxy_rows': int(selected_proxies['流程状态'].eq('审核通过').sum()),
                'pending_enabled_proxy_rows': int(selected_proxies['流程状态'].eq('审批中').sum()),
                'proxy_rule_version': 2, 'status': 'success',
                'latest_sources': True, 'payroll_executed': False})
    log('[完成] 骑手支付绑定已沿用现有生成器生成并核对人数')
    return Path(file), stats


def binding_history():
    """Read only committed successful items; failed cities never replace history."""
    from download_jobs import get_manager
    manager = get_manager()
    grouped, seen = {}, set()
    for run in manager.binding_runs():
        for file in run.get('files', []):
            if file.get('dataset') != 'payment_binding' or file.get('artifact_role') == 'summary':
                continue
            key = (file['city'], file['start'][:7])
            if key in seen:
                continue
            if not any(item.get('status') == 'success' and item.get('city') == file['city']
                       and item.get('dataset') == 'payment_binding' and item.get('start') == file['start']
                       for item in run.get('items', [])):
                continue
            try:
                owner = manager.run_owner(run['id'])
                published, _ = manager.get_file(owner, run['id'], file['id'])
                raw = published.parent / '原始资料' / file['city'] / 'payment_binding' / key[1]
                stats = json.loads((raw / 'binding_stats.json').read_text(encoding='utf-8'))
                city_stats = stats.get('cities', {}).get(file['city'])
                if city_stats is None:
                    continue
            except (OSError, ValueError, KeyError):
                continue
            seen.add(key)
            month = stats['month']
            entry = grouped.setdefault(month, {'month': month, 'stats': {'month': month, 'cities': {},
                                               'overall': {}, 'source': 'download_center'}, 'mtime': 0})
            entry['stats']['cities'][file['city']] = {**city_stats, 'source_range': stats['source_range'],
                'download_run_id': run['id'], 'download_file_id': file['id'], 'download_file_name': file['name']}
            entry['mtime'] = max(entry['mtime'], published.stat().st_mtime)
    for entry in grouped.values():
        recompute_overall(entry['stats'])
    return list(grouped.values())


def recompute_overall(stats):
    fields = ('total_riders', 'total_orders', 'fengshen_bind_count', 'shangyi_bind_count', 'fully_bound_count', 'black_count')
    for city in stats['cities'].values():
        for count, rate in (('fengshen_bind_count', 'fengshen_bind_rate'), ('shangyi_bind_count', 'shangyi_bind_rate')):
            if count not in city:
                total = city.get('total_riders', 0)
                percentage = float(str(city.get(rate, '0%')).removesuffix('%'))
                candidate = round(percentage * total / 100)
                possible = [n for n in range(max(0, candidate - 2), min(total, candidate + 2) + 1)
                            if f'{n / total * 100:.2f}' == f'{percentage:.2f}'] if total else [0]
                city[count] = possible[0] if len(possible) == 1 else None
    overall = {key: (None if any(city.get(key) is None for city in stats['cities'].values()) else
                     sum(city[key] for city in stats['cities'].values())) for key in fields}
    for rate, count in (('fengshen_bind_rate', 'fengshen_bind_count'), ('shangyi_bind_rate', 'shangyi_bind_count')):
        overall[rate] = ('待刷新旧统计' if overall[count] is None else
                         f"{overall[count] / overall['total_riders'] * 100:.2f}%" if overall['total_riders'] else '0.00%')
    stats['overall'] = overall


def merge_binding_history(legacy, fresh):
    by_month = {item['month']: item for item in legacy}
    for incoming in fresh:
        previous = by_month.get(incoming['month'])
        if previous:
            stats = {**previous['stats'], **incoming['stats'], 'cities': {
                **previous['stats'].get('cities', {}), **incoming['stats'].get('cities', {})}}
            recompute_overall(stats)
            incoming = {**incoming, 'stats': stats}
        by_month[incoming['month']] = incoming
    return list(by_month.values())
