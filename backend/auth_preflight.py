"""任务创建前的登录态预检：只读探测涉及平台，未就绪则拒绝创建并返回集中认证清单。

探测复用 platform_auth_control.check（真实只读 HTTPS、20 秒缓存、不启动浏览器）。
只保证登录态有效；风神导出短信验证仍可能在执行中出现，沿用任务内等待兜底。
"""
from concurrent.futures import ThreadPoolExecutor

from fastapi import HTTPException

LABELS = {'fengshen': '风神', 'lanorange': '蓝橙', 'baize': '商翼', 'xiaoxiang': '灯塔'}


def platforms_for_datasets(datasets):
    from download_service import expand_followup_datasets, XIAOXIANG_SELECTION, BAIZE_DATASET
    from lanorange_catalog import DATASETS as lanorange
    platforms = set()
    for kind in expand_followup_datasets(datasets or ()):
        if kind in lanorange:
            platforms.add('lanorange')
        elif kind in XIAOXIANG_SELECTION:
            platforms.add('xiaoxiang')
        elif kind == BAIZE_DATASET:
            platforms.add('baize')
        elif kind == 'payment_binding':
            platforms.update(('fengshen', 'lanorange', 'baize'))
        elif kind == 'abnormal_riders':
            # 仅读取蓝橙成品生成，依赖项已在 expand 中覆盖。
            continue
        else:
            platforms.add('fengshen')
    return platforms


def probe(platforms, deep_xiaoxiang=False):
    from platform_auth_control import check

    def inspect(source):
        try:
            state = check(source, deep=source == 'xiaoxiang' and deep_xiaoxiang)
            status = state.get('state')
            ready = status == 'ready' or (status == 'partial' and source == 'xiaoxiang' and not deep_xiaoxiang)
            return {'source': source, 'label': LABELS[source], 'state': status,
                    'ready': ready, 'message': state.get('message', '')}
        except HTTPException as exc:
            return {'source': source, 'label': LABELS[source], 'state': 'busy',
                    'ready': False, 'message': str(exc.detail)}
        except Exception:
            return {'source': source, 'label': LABELS[source], 'state': 'unknown',
                    'ready': False, 'message': '登录态检查未完成，请检查网络后重试'}

    with ThreadPoolExecutor(max_workers=4) as pool:
        return list(pool.map(inspect, sorted(platforms)))


def ensure_ready(platforms, deep_xiaoxiang=False):
    entries = probe(platforms, deep_xiaoxiang)
    if any(not entry['ready'] for entry in entries):
        raise HTTPException(409, {'code': 'AUTH_PREFLIGHT_REQUIRED',
                                  'message': '请先完成涉及平台的登录认证，认证齐备后任务将自动继续',
                                  'platforms': entries})
    return entries


def gate_datasets(datasets):
    datasets = list(datasets or ())
    from download_service import RIDER_DAILY_DATASET
    ensure_ready(platforms_for_datasets(datasets), deep_xiaoxiang=RIDER_DAILY_DATASET in datasets)
