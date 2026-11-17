"""Read the Xiaoxiang rider archive as a fallback identity source."""
import os
from pathlib import Path


def _column(frame, names):
    for name in names:
        for column in frame.columns:
            if name in str(column):
                return column
    return None


def _text(value):
    if value is None:
        return ''
    text = str(value).strip()
    return '' if text.lower() in ('', 'nan', 'none') else text


def load_archive(folder, read_excel=None):
    paths = [Path(root) / name for root, _, files in os.walk(folder)
             for name in files if '骑手档案' in name and name.lower().endswith(('.xlsx', '.xls'))]
    if not paths:
        return {}
    if read_excel is None:
        import pandas as pd
        read_excel = lambda path: pd.read_excel(path, sheet_name=0, dtype=object)
    result = {}
    for path in paths:
        try:
            frame = read_excel(path)
        except Exception:
            continue
        if frame is None or not hasattr(frame, 'columns'):
            continue
        rid_col = _column(frame, ('骑手ID', '骑手id', '骑手编号'))
        if rid_col is None:
            continue
        name_col = _column(frame, ('姓名', '骑手姓名'))
        id_col = _column(frame, ('身份证号', '身份证'))
        phone_col = _column(frame, ('手机号', '手机号码', '电话号'))
        station_col = _column(frame, ('所属站点', '站点名称', '站点'))
        for _, row in frame.iterrows():
            rid = _text(row[rid_col]).replace('.0', '')
            if not rid:
                continue
            info = result.setdefault(rid, {})
            for key, column in (('name', name_col), ('idcard', id_col),
                                ('phone', phone_col), ('station', station_col)):
                value = _text(row[column]) if column is not None else ''
                if value and not info.get(key):
                    info[key] = value
    return result