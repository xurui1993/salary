"""Explain existing payroll evidence; never change salary calculations or approve it."""
import datetime as dt
import os
from pathlib import Path
import posixpath
import uuid
from xml.dom import minidom
from xml.etree import ElementTree as ET
import zipfile

from openpyxl import load_workbook
from parttime_source import identifier

METRICS = (
    ('riders', '引擎统计人数', '人', '沿用引擎原口径，不与申请行数直接相减'),
    ('orders', '配送记录数', '条', '沿用引擎导入统计，不代表去重完成单量'),
    ('no_price', '无单价记录', '条', '请查看工作簿的蓝橙无单价明细'),
    ('unbound', '未绑定记录', '条', '请查看工作簿的发薪工具未绑名单'),
    ('intercepted', '拦截记录', '条', '请查看工作簿的拦截溯源及日维度单量拦截'),
)


def application_summary(path):
    book = load_workbook(path, read_only=True, data_only=True)
    try:
        sheet = book['申请名单']
        sheet.reset_dimensions()
        rows = iter(sheet.iter_rows(values_only=True))
        headers = [str(value or '').strip() for value in next(rows)]
        index = headers.index('骑手ID')
        riders, seen, duplicates, count = set(), {}, [], 0
        for number, row in enumerate(rows, 2):
            if not any(value is not None and str(value).strip() for value in row):
                continue
            count += 1
            riders.add(identifier(row[index]))
            key = tuple(value.isoformat() if isinstance(value, (dt.date, dt.datetime)) else str(value) if value is not None else '' for value in row)
            if key in seen:
                duplicates.append({'row': number, 'same_as': seen[key]})
            else:
                seen[key] = number
        return {'records': count, 'unique_riders': len(riders), 'duplicate_rows': duplicates,
                'file': Path(path).name, 'sheet': '申请名单'}
    finally:
        book.close()


def metric_value(stats, key):
    batches = list(stats['batch_stats'].values()) if isinstance(stats, dict) and isinstance(stats.get('batch_stats'), dict) else [stats]
    values = [batch.get(key) if isinstance(batch, dict) else None for batch in batches]
    if not values or any(type(value) is not int or value < 0 for value in values):
        return None
    return sum(values)


def build_review(state, stats, application=None):
    metrics = [{'key': 'applicants', 'label': '申请记录数', 'value': state['plan'].get('applicants'), 'unit': '条', 'note': '预检通过的申请行数，同一骑手可能存在多行'}]
    metrics.extend({'key': key, 'label': label, 'value': metric_value(stats, key), 'unit': unit, 'note': note} for key, label, unit, note in METRICS)
    issues = []
    zero_stations = state.get('automatic_deductions', {}).get('zero_stations', [])
    if zero_stations:
        issues.append({'code':'automatic_zero_deductions','label':'无扣款配置站点按零扣款计算','count':len(zero_stations),'location':'、'.join(zero_stations)})
    if application:
        metrics.insert(1, {'key': 'unique_applicants', 'label': '申请骑手去重数', 'value': application['unique_riders'], 'unit': '人', 'note': '仅按申请名单骑手ID去重，不等于输出覆盖人数'})
        if application['duplicate_rows']:
            issues.append({'code': 'duplicate_application', 'label': '申请名单存在完全相同的行', 'count': len(application['duplicate_rows']),
                           'location': application['file'] + ' / 申请名单', 'rows': application['duplicate_rows']})
    else:
        issues.append({'code': 'application_unknown', 'label': '申请名单去重情况未统计，请复核原表'})
    for metric in metrics:
        if metric['value'] is None:
            issues.append({'code': 'unknown_' + metric['key'], 'label': metric['label'] + '未提供统计'})
        elif metric['key'] in ('no_price', 'unbound', 'intercepted') and metric['value'] > 0:
            issues.append({'code': metric['key'], 'label': metric['label'] + '需复核', 'count': metric['value'], 'location': metric['note']})
    sources = []
    for kind, item in state['items'].items():
        files = item.get('files') or ([item] if item.get('file') else [])
        sources.append({'kind': kind, 'label': item['label'], 'status': item['status'],
                        'files': [{'name': Path(file['file']).as_posix() if not Path(file['file']).is_absolute() and '..' not in Path(file['file']).parts else Path(file['file']).name,
                                   'sha256': file.get('sha256')} for file in files]})
        if item['status'] == 'omitted':
            issues.append({'code': 'omitted_' + kind, 'label': '本批次确认不提供：' + item['label']})
        elif item['status'] != 'ready':
            issues.append({'code': 'source_' + kind, 'label': '资料状态需核对：' + item['label']})
    return {'version': 1, 'status': 'pending_review', 'batch_id': state['id'],
            'created_at': dt.datetime.now(dt.timezone.utc).isoformat(), 'city': state['plan']['city'],
            'start': state['plan']['start'], 'end': state['plan']['end'], 'metrics': metrics,
            'issues': issues, 'sources': sources, 'application': application,
            'template': {'name': state['plan']['template'], 'sha256': state.get('template_hash')},
            'deduction_version': state.get('deductions', {}).get('version'),
            'input_check': '按可读取资料执行；未进行站点归属、SHA256及跨来源一致性校验' if state.get('input_policy')=='readable_delivery_v1' else '运行前已按保存的SHA256校验输入；不代表业务数据本身准确完整',
            'money_check': '待用Excel/WPS重算并人工核对金额；系统未确认发薪或业务验收'}


def write_review(output, summary):
    main, _ = payroll_workbooks(output)
    _append_review_sheet(main, review_rows(summary))


def payroll_workbooks(output):
    """Only new calculation directories use this two-attachment contract."""
    paths = sorted(path for path in Path(output).rglob('*.xlsx') if path.is_file() and not path.is_symlink() and not path.name.startswith(('~$', '.')))
    special = [path for path in paths if '蓝橙无单价&未绑名单' in path.name]
    main = [path for path in paths if path not in special]
    if len(main) != 1 or len(special) != 1:
        raise ValueError('核算结果应包含一份工资表和一份蓝橙无单价&未绑名单')
    return main[0], special[0]


def provider(kind):
    if kind == 'lanorange_part_price':
        return '蓝橙后台'
    if kind in ('delivery_fee', 'penalty', 'rider_monthly', 'fraud', 'problem'):
        return '风神后台'
    return '系统核算'


def review_rows(summary):
    system = '系统核算'
    rows = [('类别', '提供方', '项目', '数值或状态', '口径与复核位置'),
            ('范围', system, '城市与业务周期', summary['city'], summary['start'] + ' 至 ' + summary['end']),
            ('范围', system, '核算批次', '本次核算', '批次编号保存在系统内部记录'),
            ('结论', system, '业务复核', '待人工复核', summary['money_check'])]
    for metric in summary['metrics']:
        rows.append(('统计', system, metric['label'], metric['value'], metric['note']))
    for issue in summary['issues']:
        kind = next((source['kind'] for source in summary['sources'] if issue['code'] in ('omitted_' + source['kind'], 'source_' + source['kind'])), '')
        rows.append(('待核对', provider(kind), issue['label'], issue.get('count', '需确认'), issue.get('location', '本表来源记录')))
        for duplicate in issue.get('rows', []):
            rows.append(('申请行', system, '完全相同的申请记录', duplicate['row'], '与第' + str(duplicate['same_as']) + '行相同；不自动删除'))
    rows.append(('凭据', system, '扣款配置', '已保存本批配置' if summary['deduction_version'] else '未记录', summary['input_check'].replace('SHA256', '文件摘要')))
    rows.append(('凭据', system, summary['template']['name'], '已保留原模板', '申请名单；文件摘要保存在系统内部记录'))
    statuses = {'ready':'已提供', 'omitted':'未参与本次核算', 'pending':'等待获取', 'failed':'获取失败',
                'unavailable':'资料不可用', 'running':'获取中', 'waiting_login':'等待平台验证', 'cancelled':'已停止'}
    for source in summary['sources']:
        rows.append(('来源', provider(source['kind']), source['label'], statuses.get(source['status'], '状态待核对'), ''))
        for file in source['files']:
            rows.append(('来源文件', provider(source['kind']), file['name'], '已保留原件', source['label'] + '；文件摘要保存在系统内部记录'))
    return rows


def _append_review_sheet(path, rows):
    """Add one OOXML part without resaving salary cells, formulas or cached values."""
    main_ns = 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'
    rel_ns = 'http://schemas.openxmlformats.org/officeDocument/2006/relationships'
    package_ns = 'http://schemas.openxmlformats.org/package/2006/relationships'
    sheet = ET.Element('worksheet', xmlns=main_ns)
    views = ET.SubElement(sheet, 'sheetViews')
    view = ET.SubElement(views, 'sheetView', workbookViewId='0')
    ET.SubElement(view, 'pane', ySplit='1', topLeftCell='A2', activePane='bottomLeft', state='frozen')
    columns = ET.SubElement(sheet, 'cols')
    for i, width in enumerate((12, 16, 42, 24, 85), 1):
        ET.SubElement(columns, 'col', min=str(i), max=str(i), width=str(width), customWidth='1')
    data = ET.SubElement(sheet, 'sheetData')
    for i, values in enumerate(rows, 1):
        row = ET.SubElement(data, 'row', r=str(i))
        for j, value in enumerate(values):
            cell = ET.SubElement(row, 'c', r=f'{chr(65+j)}{i}', t='n' if type(value) in (int, float) else 'inlineStr')
            if type(value) in (int, float):
                ET.SubElement(cell, 'v').text = str(value)
            else:
                # Inline strings keep user filenames literal, including leading '='.
                ET.SubElement(ET.SubElement(cell, 'is'), 't').text = str(value) if value is not None else '未统计'
    ET.SubElement(sheet, 'autoFilter', ref=f'A1:E{len(rows)}')
    temporary = path.with_name('.复核_' + uuid.uuid4().hex + '.tmp')
    try:
        with zipfile.ZipFile(path) as original:
            workbook = minidom.parseString(original.read('xl/workbook.xml'))
            relationships = minidom.parseString(original.read('xl/_rels/workbook.xml.rels'))
            types = minidom.parseString(original.read('[Content_Types].xml'))
            sheets = workbook.getElementsByTagNameNS(main_ns, 'sheets')[0]
            entries = list(sheets.getElementsByTagNameNS(main_ns, 'sheet'))
            existing = next((entry for entry in entries if entry.getAttribute('name') == '核算复核清单'), None)
            links = relationships.getElementsByTagNameNS(package_ns, 'Relationship')
            if existing is not None:
                link = next(link for link in links if link.getAttribute('Id') == existing.getAttributeNS(rel_ns, 'id'))
                target = link.getAttribute('Target')
                part = posixpath.normpath(target.lstrip('/') if target.startswith('/') else 'xl/' + target)
                if not part.startswith('xl/worksheets/') or part not in original.namelist():
                    raise ValueError('复核工作表位置无效，原工资表保留')
            else:
                number = max((int(entry.getAttribute('sheetId')) for entry in entries), default=0) + 1
                part = f'xl/worksheets/payroll_review_{uuid.uuid4().hex}.xml'
                used = {link.getAttribute('Id') for link in links}
                rid = 'rIdPayrollReview'
                while rid in used:rid += '_'
                prefix = sheets.prefix + ':' if sheets.prefix else ''
                entry = workbook.createElementNS(main_ns, prefix + 'sheet')
                entry.setAttribute('name', '核算复核清单');entry.setAttribute('sheetId', str(number))
                entry.setAttribute('xmlns:r', rel_ns);entry.setAttributeNS(rel_ns, 'r:id', rid)
                sheets.appendChild(entry)
                link = relationships.createElementNS(package_ns, 'Relationship')
                link.setAttribute('Id', rid);link.setAttribute('Type', rel_ns + '/worksheet');link.setAttribute('Target', part[3:])
                relationships.documentElement.appendChild(link)
                override = types.createElementNS(types.documentElement.namespaceURI, 'Override')
                override.setAttribute('PartName', '/' + part)
                override.setAttribute('ContentType', 'application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml')
                types.documentElement.appendChild(override)
            replacements = {'xl/workbook.xml':workbook.toxml(encoding='utf-8'),
                            'xl/_rels/workbook.xml.rels':relationships.toxml(encoding='utf-8'),
                            '[Content_Types].xml':types.toxml(encoding='utf-8'), part:ET.tostring(sheet, encoding='utf-8', xml_declaration=True)}
            with zipfile.ZipFile(temporary, 'w', zipfile.ZIP_DEFLATED, compresslevel=6, allowZip64=True) as result:
                result.comment = original.comment
                for info in original.infolist():
                    if info.filename in replacements:
                        result.writestr(info, replacements.pop(info.filename))
                    else:
                        with original.open(info) as source, result.open(info, 'w', force_zip64=True) as target:
                            import shutil
                            shutil.copyfileobj(source, target, length=1024*1024)
                for name, content in replacements.items():result.writestr(name, content)
        with zipfile.ZipFile(temporary) as check:
            if check.testzip() is not None:raise ValueError('复核工作表写入校验失败')
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)
