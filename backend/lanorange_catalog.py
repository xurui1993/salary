"""Official page-export endpoints, verified against deployed page scripts."""
import datetime as dt
import re

ALL_CITIES = '全部城市'
PART_PRICE = 'lanorange_part_price'
# 蓝橙下载可选的 16 个城市（不含“市”后缀，与平台目录名称一致）；其余平台城市不展示。
SELECTABLE_CITIES = ('保定', '北京', '潮州', '大连', '东莞', '广州', '惠州', '宁波',
                     '泉州', '三亚', '汕头', '上海', '韶关', '深圳', '台州', '天津')
# 价格档案页的日期区间筛选：params[beginTime]/params[endTime]（YYYY-MM-DD）。
_MONTH = re.compile(r'(\d{4})-(0[1-9]|1[0-2])')
DATASETS = {
    'lanorange_rider_quit': ('骑手离职', 'info/riderQuit/export'),
    'lanorange_rider_report': ('离职报备', 'info/riderReportDetail/export'),
    'lanorange_batch_quit': ('批量离职', 'info/riderBatchQuit/export'),
    'lanorange_rider_leave': ('骑手请假', 'info/riderLeave/export'),
    'lanorange_identity_change': ('骑手兼全职变更', 'info/riderIdentityChange/export'),
    'lanorange_salary_replace': ('佣金代领', 'info/riderSalaryReplace/export'),
    PART_PRICE: ('价格档案', 'salary/partRiderPrice/export'),
    'lanorange_rider_archive': ('骑手档案', 'info/riderInfo/export'),
}


def city_scoped(config, dataset):
    # Historical jobs retain their original global scope.
    return bool(config.get('lanorange_by_city')) and dataset in DATASETS


def source_key(city, dataset):
    return dataset if city == ALL_CITIES else city + '|' + dataset


def source_directory(root, city, dataset):
    from download_archive import archive_component
    base = root / '原始资料' / '蓝橙'
    return base / dataset if city == ALL_CITIES else base / archive_component(city) / dataset


def clean_months(values):
    """校验并返回去重排序的 YYYY-MM 月份列表；格式不符直接报错。"""
    if values is None:
        return []
    if not isinstance(values, list) or any(not isinstance(value, str) or not _MONTH.fullmatch(value)
                                           for value in values):
        raise ValueError('蓝橙价格档案月份格式无效')
    unique = sorted(set(values))
    if len(unique) > 36:
        raise ValueError('蓝橙价格档案月份数量超出范围')
    return unique


def platform_months(config, dataset):
    """价格档案的平台侧月份筛选：纯蓝橙按所选月份；混合任务按风神日期区间月份。"""
    if dataset != PART_PRICE:
        return None
    selected = clean_months(config.get('lanorange_months'))
    if selected:
        return selected
    datasets = config.get('datasets') or []
    if not datasets or all(kind in DATASETS or kind == 'abnormal_riders' for kind in datasets):
        return None
    months = clean_months(config.get('months'))
    return months or None


def date_range(months):
    """月份列表转换为平台日期区间首日与月末。"""
    first = months[0] + '-01'
    year, month = int(months[-1][:4]), int(months[-1][5:7])
    if month == 12:
        next_first = f'{year + 1}-01-01'
    else:
        next_first = f'{year}-{month + 1:02d}-01'
    last = (dt.date.fromisoformat(next_first) - dt.timedelta(days=1)).isoformat()
    return first, last


def source_filters(city, months=None):
    filters = {} if city == ALL_CITIES else {'city': city}
    if months:
        filters['months'] = list(months)
    return filters


def months_contiguous(months):
    """月份列表是否连续（如 2026-09、2026-10）；连续时平台区间导出即精确范围。"""
    for earlier, later in zip(months, months[1:]):
        year, month = int(earlier[:4]), int(earlier[5:7])
        expected = f'{year + 1}-01' if month == 12 else f'{year}-{month + 1:02d}'
        if later != expected:
            return False
    return True
