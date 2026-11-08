"""Keep company Xiaoxiang uploads separate from Fengshen material acquisition."""
from pathlib import Path
import re

from parttime_source import SourceError, TemplatePlan, inspect_source, source_files

DATE_FILE = re.compile(r'(\d{4}[-/]\d{1,2}[-/]\d{1,2}|(?<!\d)\d{8}(?!\d))(?=\D|$)')


def xiaoxiang_template(path):
    name = Path(path).name
    return ('小象' in name and 'template' in name.lower() and
            Path(name).suffix.lower() in ('.xlsx', '.xls') and not name.startswith(('~', '.')))


def is_xiaoxiang_source(folder, template=None):
    if template:
        return xiaoxiang_template(template)
    return any(xiaoxiang_template(path) for path in Path(folder).rglob('*') if path.is_file())


def xiaoxiang_delivery_files(files, template):
    # Same date filename recognition as the company's original processor. Do
    # not rename date files, merchantFreelancer, or rider order detail exports.
    return [path for path in files if path != template and
            'merchantfreelancer' not in path.name.lower() and DATE_FILE.search(path.name)]


def company_plan(template, folder):
    from payroll_performance import cached_plan
    return cached_plan(template, ('company', str(Path(folder).resolve())),
                       lambda: _company_plan_checked(template, folder))


def _company_plan_checked(template, folder):
    import pandas as pd
    from processor import safe_parse_date
    try:
        frame = pd.read_excel(template, sheet_name='申请名单', dtype=object).dropna(how='all')
        if frame.empty:
            raise SourceError('小象申请名单为空')
        def column(words, fallback):
            return next((name for name in frame.columns if any(word in str(name) for word in words)),
                        frame.columns[fallback] if fallback is not None and len(frame.columns) > fallback else None)
        def first(name, default):
            if name is None:
                return default
            values = frame[name].dropna().astype(str).str.strip()
            values = values[~values.str.lower().isin(('', 'nan', 'none'))]
            return values.iloc[0] if len(values) else default
        start_column, end_column = column(['开始日期', '开始时间', '开始'], 3), column(['结束日期', '结束时间', '结束'], 4)
        if start_column is None or end_column is None:
            raise SourceError('小象申请名单缺少开始、结束日期')
        first_dates, last_dates = safe_parse_date(frame[start_column]), safe_parse_date(frame[end_column])
        if first_dates.isna().any() or last_dates.isna().any() or first_dates.gt(last_dates).any():
            raise SourceError('小象申请名单存在无效或倒置日期')
        start, end = first_dates.min(), last_dates.max()
        return TemplatePlan(first(column(['城市'], None), '小象超市'), '', start.date().isoformat(),
            end.date().isoformat(), end.strftime('%Y-%m'), first(column(['结算'], None), '半月结'),
            template.relative_to(Path(folder)).as_posix(), len(frame))
    except SourceError:
        raise
    except Exception:
        raise SourceError('小象 template 无法读取，请使用公司版本的申请名单结构') from None


def inspect_payroll(folder, mode):
    if mode not in ('manual', 'fengshen', 'xiaoxiang'):
        raise SourceError('未知兼职资料准备方式')
    files = source_files(folder)
    templates = [path for path in files if 'template' in path.name.lower()]
    if len(templates) != 1:
        raise SourceError('每次核算须上传一个且仅一个 template；普通与小象资料请分开提交')
    template = templates[0]
    if xiaoxiang_template(template):
        if mode == 'fengshen':
            raise SourceError('小象超市仅支持独立手动上传，请切换“小象超市（手动）”；不会调用风神或蓝橙下载')
        if not xiaoxiang_delivery_files(files, template):
            raise SourceError('小象须上传日期命名的配送单，如 2026-09-01.xlsx 或 20260901.xlsx；无需改名为配送费')
        return company_plan(template, folder), template, 'xiaoxiang'
    if mode == 'xiaoxiang':
        raise SourceError('小象手动入口须上传文件名含“小象”和“template”的模板')
    plan, template, _ = inspect_source(folder, require_agency=mode == 'fengshen')
    if mode == 'manual' and not any('配送费' in path.name for path in files if path != template):
        raise SourceError('普通业务手动核算必须上传 template 和配送费，其他资料可选')
    return plan, template, mode
