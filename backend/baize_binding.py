"""Build the payroll binding table from the Xiaoxiang Baize employee export."""
from pathlib import Path

import pandas as pd
from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill


def build_binding(employee_path, target, region_name=''):
    frame = pd.read_excel(employee_path, dtype=object)
    id_column = next((column for column in frame.columns
                      if str(column).strip() in ('身份证号', '身份证', '身份证号码')), None)
    if id_column is None:
        raise ValueError('商翼员工导出缺少身份证号列')
    name_column = next((column for column in frame.columns
                        if str(column).strip() in ('姓名', '员工姓名')), None)
    phone_column = next((column for column in frame.columns
                         if str(column).strip() in ('银行预留手机号', '手机号', '手机号码')), None)
    records = {}
    for _, row in frame.iterrows():
        identity = str(row[id_column] or '').strip().upper()
        identity = identity.replace('.0', '')
        if not identity or identity.lower() in ('nan', 'none'):
            continue
        records.setdefault(identity, {
            'idcard': identity,
            'name': str(row[name_column] or '').strip() if name_column else '',
            'phone': str(row[phone_column] or '').strip() if phone_column else '',
        })
    if not records:
        raise ValueError('商翼员工导出没有可用身份证号')
    target = Path(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    book = Workbook()
    sheet = book.active
    sheet.title = '骑手支付绑定'
    headers = ['身份证号', '姓名', '手机号', '绑定情况', '区域名称']
    sheet.append(headers)
    for cell in sheet[1]:
        cell.font = Font(name='微软雅黑', size=10, bold=True)
        cell.fill = PatternFill('solid', fgColor='FFF8CBAD')
        cell.alignment = Alignment(horizontal='center', vertical='center')
    for record in records.values():
        sheet.append([record['idcard'], record['name'], record['phone'], '已绑定', region_name])
    for row in sheet.iter_rows(min_row=2):
        for cell in row:
            cell.font = Font(name='微软雅黑', size=10)
            cell.alignment = Alignment(horizontal='center', vertical='center')
    for column, width in zip('ABCDE', (24, 14, 18, 14, 28)):
        sheet.column_dimensions[column].width = width
    sheet.freeze_panes = 'A2'
    book.save(target)
    book.close()
    return len(records)