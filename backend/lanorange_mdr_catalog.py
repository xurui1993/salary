"""新蓝橙（MDR）页面导出接口：以线上页面脚本为准，只做原始文件下载。"""
import datetime as dt
import re

from lanorange_catalog import SELECTABLE_CITIES

ALL_CITIES = '全部城市'
# 与老蓝橙共用同一批业务城市；实际 cityId 以平台城市清单为准，下载时再映射。
MDR_CITIES = tuple(SELECTABLE_CITIES)
API_PREFIX = '/api'
CITY_REQUIRED = True

DATASETS = {
    'lcmdr_archive': {'label': '骑手档案', 'page': '/admin/hr/archive/page',
                      'export': '/admin/hr/archive/export', 'fixed': {'postType': 'rider'}},
    'lcmdr_exit': {'label': '骑手离职', 'page': '/admin/rider/exit/page',
                   'export': '/admin/rider/exit/export'},
    'lcmdr_batch_exit': {'label': '批量离职', 'page': '/admin/rider/batch-exit/page',
                         'export': '/admin/rider/batch-exit/export'},
    'lcmdr_exit_report': {'label': '离职报备', 'page': '/admin/rider/exit-report/page',
                          'export': '/admin/rider/exit-report/export'},
    'lcmdr_leave': {'label': '骑手请假', 'page': '/admin/rider/leave/page',
                    'export': '/admin/rider/leave/export'},
    'lcmdr_type_change': {'label': '骑手兼全职变更', 'page': '/admin/rider/type-change/page',
                          'export': '/admin/rider/type-change/export'},
    'lcmdr_commission_proxy': {'label': '佣金代领', 'page': '/admin/rider/commission-proxy/page',
                               'export': '/admin/rider/commission-proxy/export', 'month_param': 'proxyMonth'},
    'lcmdr_part_price': {'label': '兼职价格档案', 'page': '/admin/part-time-price/archive/page',
                         'export': '/admin/part-time-price/archive/export', 'range': True, 'array_city': True},
}

MONTH_DATASETS = frozenset(key for key, meta in DATASETS.items() if meta.get('month_param'))
PRICE_DATASETS = frozenset(key for key, meta in DATASETS.items() if meta.get('range'))
SINGLE_MONTH_DATASETS = MONTH_DATASETS


def dataset_meta(dataset):
    try:
        return DATASETS[dataset]
    except KeyError:
        raise ValueError('新蓝橙下载项不在支持范围') from None


def source_directory(root, city, dataset):
    from download_archive import archive_component
    base = root / '原始资料' / '新蓝橙'
    return base / archive_component(city) / dataset


def normalize_city(value):
    text = str(value or '').strip()
    text = re.sub(r'市$', '', text)
    return re.sub(r'\s+', '', text)


def match_city(rows, city):
    """Match a configured city name against the platform city list."""
    wanted = normalize_city(city)
    for row in rows or ():
        if not isinstance(row, dict):
            continue
        name = row.get('cityName') or row.get('name') or row.get('city')
        if name is not None and normalize_city(name) == wanted:
            return row
    return None


def city_identity(row):
    if not isinstance(row, dict):
        return None, None
    city_id = row.get('id') or row.get('cityId')
    if city_id is None:
        return None, None
    city_id = str(city_id)
    if not re.fullmatch(r'\d{1,20}', city_id):
        return None, None
    project = row.get('projectCode') or row.get('project') or None
    return city_id, (str(project) if project else None)


def clean_months(values):
    from lanorange_catalog import clean_months as clean
    return clean(values)


def date_range(months):
    from lanorange_catalog import date_range as bounds
    return bounds(months)


def months_contiguous(months):
    from lanorange_catalog import months_contiguous as contiguous
    return contiguous(months)


def build_params(dataset, months=None, city_id=None, project_code=None):
    """Return a list of (key, value) pairs so array filters survive encoding."""
    meta = dataset_meta(dataset)
    params = [(key, str(value)) for key, value in (meta.get('fixed') or {}).items()]
    if project_code:
        params.append(('projectCode', project_code))
    if city_id:
        if meta.get('array_city'):
            # 页面用 cityIds 数组；同时给出 [] 写法，兼容后端的数组绑定。
            params.extend([('cityIds', city_id), ('cityIds[]', city_id)])
        else:
            params.append(('cityId', city_id))
    if months:
        if meta.get('range'):
            first, last = date_range(months)
            params.extend([('startDate', first), ('endDate', last)])
        elif meta.get('month_param'):
            params.append((meta['month_param'], months[0]))
    return params


def validate_scope(dataset, months):
    meta = dataset_meta(dataset)
    months = clean_months(months) if months else []
    if meta.get('range'):
        if not months:
            raise ValueError('兼职价格档案需要选择月份')
        if not months_contiguous(months):
            raise ValueError('兼职价格档案的月份必须连续')
    elif meta.get('month_param'):
        if not months:
            raise ValueError('佣金代领需要选择一个代领月份')
        if len(months) != 1:
            raise ValueError('佣金代领一次只能导出一个月份，请拆分任务')
    elif months:
        raise ValueError('该新蓝橙资料不支持按月份筛选')
    return months


def full_period(months):
    if not months:
        return None
    first, last = date_range(months)
    return dt.date.fromisoformat(first), dt.date.fromisoformat(last)