"""Download the page's original XLSX with no business filters or rewriting."""
import hashlib
import hashlib_compat
import json
import posixpath
import shutil
import re
from pathlib import Path
import xml.etree.ElementTree as ElementTree
import zipfile

from openpyxl import load_workbook
from binding_sources_http import authenticated, query
from lanorange_http_export import export_once
from fengshen_bill import BillCollectionError, atomic_json
from lanorange_catalog import DATASETS, ALL_CITIES, date_range, source_filters

# The page sends these transport fields even when every business filter is empty.
EXPORT_TRANSPORT = {'pageNum': 1, 'pageSize': 10}
FLAT_LISTS = {'lanorange_rider_quit': 'info/riderQuit/list',
              'lanorange_part_price': 'salary/partRiderPrice/list',
              'lanorange_rider_archive': 'info/riderInfo/list'}
_WORKBOOK_NS = '{http://schemas.openxmlformats.org/spreadsheetml/2006/main}'
_RELATIONSHIP_NS = '{http://schemas.openxmlformats.org/officeDocument/2006/relationships}'
_ROW_CHUNK = 4 * 1024 * 1024


def _sheet_members(archive):
    workbook = ElementTree.fromstring(archive.read('xl/workbook.xml'))
    relationships = ElementTree.fromstring(archive.read('xl/_rels/workbook.xml.rels'))
    targets = {node.get('Id'): (node.get('Target') or '', node.get('Type') or '')
               for node in relationships}
    members = []
    for node in workbook.iter(_WORKBOOK_NS + 'sheet'):
        target, sheet_type = targets.get(node.get(_RELATIONSHIP_NS + 'id'), ('', ''))
        if not sheet_type.endswith('/worksheet'):
            continue
        name, state = node.get('name'), node.get('state', 'visible')
        if not name or not target or state not in ('visible', 'hidden', 'veryHidden'):
            raise ValueError('unrecognized workbook sheet')
        member = target.lstrip('/') if target.startswith('/') else posixpath.normpath(posixpath.join('xl', target))
        archive.getinfo(member)
        members.append((name, state, member))
    return members


def _row_has_value(row):
    # data_only=False keeps formula text as a value even without a cached <v>.
    if b'<f>' in row or b'<f ' in row or b'<is>' in row or b'<is ' in row:
        return True
    search = 0
    while True:
        start = row.find(b'<v>', search)
        if start < 0:
            return False
        end = row.find(b'</v>', start + 3)
        if end < 0 or end > start + 3:
            return True
        search = end + 4


def _cell_count(row):
    count = search = 0
    while True:
        start = row.find(b'<c', search)
        if start < 0:
            return count
        if row[start + 2:start + 3] in (b' ', b'>', b'/', b'\t', b'\r', b'\n'):
            count += 1
        search = start + 2


def _scan_sheet(archive, member, cancelled):
    """Count business rows without materializing every cell (292k rows ~ seconds)."""
    with archive.open(member) as stream:
        buffer, position = b'', 0
        data_seen = finished = False
        header = None
        counted = columns = 0
        while True:
            if cancelled.is_set():
                raise BillCollectionError('蓝橙资料校验已取消，原始文件已保留')
            chunk = stream.read(_ROW_CHUNK)
            buffer = buffer[position:] + chunk
            position = 0
            if not chunk:
                finished = True
            if not data_seen:
                index = buffer.find(b'<sheetData')
                if index < 0:
                    if finished:
                        break
                    buffer = buffer[-16:]
                    continue
                buffer = buffer[index:]
                data_seen = True
            if not finished:
                limit = buffer.find(b'</sheetData>')
                if limit >= 0:
                    buffer = buffer[:limit]
                    finished = True
            while True:
                start = buffer.find(b'<row', position)
                if start < 0:
                    position = max(position, len(buffer) - 4)
                    break
                tag_end = buffer.find(b'>', start)
                if tag_end < 0:
                    position = start
                    break
                if buffer[tag_end - 1:tag_end] == b'/':
                    end = tag_end + 1
                else:
                    close = buffer.find(b'</row>', tag_end + 1)
                    if close < 0:
                        position = start
                        break
                    end = close + len(b'</row>')
                row, position = buffer[start:end], end
                if header is None:
                    if not _row_has_value(row):
                        raise BillCollectionError('蓝橙原始文件缺少表头，未发布文件')
                    header, columns = row, _cell_count(row)
                elif _row_has_value(row):
                    counted += 1
            if finished:
                if b'<row' in buffer[position:]:
                    raise ValueError('incomplete worksheet row')
                break
    if header is None:
        raise BillCollectionError('蓝橙原始文件缺少表头，未发布文件')
    return counted, columns


def _validate_all_cities(path, cancelled):
    with zipfile.ZipFile(path) as archive:
        sheets = []
        for name, state, member in _sheet_members(archive):
            rows, columns = _scan_sheet(archive, member, cancelled)
            sheets.append({'name': name, 'rows': rows, 'columns': columns, 'state': state})
    if not sheets:
        raise BillCollectionError('蓝橙原始文件没有工作表')
    return sheets


def validate_original(path, cancelled, city=None):
    # Full delivery reaches hundreds of thousands of rows; stream the sheet XML.
    # City-scoped exports still use the strict parser because they inspect each
    # cell's city value. Structural surprises fall back to the strict parser.
    if city is None:
        try:
            return _validate_all_cities(path, cancelled)
        except BillCollectionError:
            raise
        except Exception:
            pass
    book = load_workbook(path, read_only=True, data_only=False)
    sheets = []
    try:
        for sheet in book:
            rows = sheet.iter_rows(values_only=True)
            header = next(rows, None)
            if header is None or not any(value is not None for value in header):
                raise BillCollectionError('蓝橙原始文件缺少表头，未发布文件')
            count = 0
            city_columns = [i for i, value in enumerate(header) if value in ('城市', '城市名称')]
            selected_rows = other_rows = 0
            for row in rows:
                if cancelled.is_set():
                    raise BillCollectionError('蓝橙资料校验已取消，原始文件已保留')
                if any(value is not None for value in row):
                    count += 1
                    if city and sheet.sheet_state == 'visible':
                        if not city_columns: raise BillCollectionError('蓝橙原始业务表缺少城市字段，未发布城市资料')
                        if all(str(row[i] or '').removesuffix('市') == city.removesuffix('市') for i in city_columns): selected_rows += 1
                        else: other_rows += 1
            sheets.append({'name': sheet.title, 'rows': count, 'columns': len(header),
                           'state': sheet.sheet_state,
                           **({'selected_rows':selected_rows,'other_city_rows':other_rows} if city else {})})
    finally:
        book.close()
    if not sheets: raise BillCollectionError('蓝橙原始文件没有工作表')
    return sheets


def business_rows(sheets):
    # Official exports may include hidden validation-option sheets. They are
    # retained and parsed, but are not business records returned by /list.
    return sum(sheet['rows'] for sheet in sheets if sheet.get('state', 'visible') == 'visible')


def load_cities(log, cancelled):
    with authenticated('lanorange', log, cancelled) as session:
        rows = query(session, 'lanorange', 'base/baseCity/queryList').get('data')
    if not isinstance(rows, list): raise BillCollectionError('蓝橙城市目录未确认，未提交导出')
    result = {}
    for row in rows:
        name = str(row.get('cityName', '')).removesuffix('市')
        code = str(row.get('id', ''))
        if not name or not re.fullmatch(r'\d{1,20}', code) or name in result:
            raise BillCollectionError('蓝橙城市名称或编号异常，未提交导出')
        result[name] = code
    return result


def collect(dataset, directory, log, cancelled, resume=None, *, city=ALL_CITIES, city_id=None, months=None):
    label, endpoint = DATASETS[dataset]
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    try:
        filters = source_filters(city, months)
        params = dict(EXPORT_TRANSPORT)
        if months:
            begin, end = date_range(months)
            params['params[beginTime]'] = begin
            params['params[endTime]'] = end
        if resume:
            from binding_recovery import verified_file
            source = Path(resume)
            info = json.loads((source / 'source_receipt.json').read_text(encoding='utf-8'))
            legacy = source_filters(city, None)
            if (info.get('dataset') != dataset or info.get('status') != 'validated'
                    or info.get('filters') not in (filters, legacy)):
                raise BillCollectionError('蓝橙原始文件恢复凭据不符')
            path = Path(verified_file(source, info))
            if city != ALL_CITIES:
                checked = validate_original(path, cancelled, city)
                extra = sum(sheet.get('other_city_rows',0) for sheet in checked)
                if extra and dataset != 'lanorange_batch_quit':
                    raise BillCollectionError('蓝橙原始文件包含其他城市，不能恢复为本城市成品')
                info.update(sheets=checked, business_rows=business_rows(checked), other_city_rows=extra,
                            scope_validation='batch_with_other_cities' if extra else 'exact')
            log('[恢复] 仅复用已完成蓝橙原始导出，不重新提交')
            target = directory / path.name
            shutil.copy2(path, target)
            atomic_json(directory / 'source_receipt.json', info)
            return target
        if city != ALL_CITIES:
            if not re.fullmatch(r'\d{1,20}', str(city_id or '')):
                raise BillCollectionError('蓝橙未找到所选城市编号，未提交导出')
            params['cityIds[0]'] = str(city_id)
            # Detail exports use scalar cityId while batch/list pages use
            # cityIds. Send the same city in both official fields.
            params['cityId'] = str(city_id)
        with authenticated('lanorange', log, cancelled) as session:
            total = None
            if dataset in FLAT_LISTS:
                total = query(session, 'lanorange', FLAT_LISTS[dataset], {**params, 'pageSize': 1}).get('total')
                if type(total) is not int or total < 0:
                    raise BillCollectionError('蓝橙全量查询总数未确认，未提交导出')
                atomic_json(directory / 'query_receipt.json', {'dataset': dataset, 'query_total': total,
                            'endpoint': FLAT_LISTS[dataset], 'filters': filters})
            log('[下载] 蓝橙' + label + '：' + city + '，全部状态、'
                + ('日期 ' + '、'.join(months) if months else '不按日期筛选'))
            path = export_once(session, 'lanorange', endpoint, params, directory / (label + '.xlsx'), cancelled)
        sheets = validate_original(path, cancelled, city if city != ALL_CITIES else None)
        rows = business_rows(sheets)
        other_rows = sum(sheet.get('other_city_rows',0) for sheet in sheets)
        if other_rows and dataset != 'lanorange_batch_quit':
            raise BillCollectionError('蓝橙导出城市筛选未生效，原始表包含其他城市，未发布文件')
        if other_rows:
            log(f'[说明] {city}批量离职平台原始批次中含其他城市 {other_rows} 条；原表保持原样，汇总仅纳入所选城市')
        if total is not None and rows != total:
            atomic_json(directory / 'validation_failure.json', {'dataset': dataset, 'query_total': total,
                        'business_rows': rows, 'sheets': sheets, 'reason': 'row_count_mismatch'})
            raise BillCollectionError(f'蓝橙业务表 {rows} 行与无筛选查询 {total} 条不符，未发布文件')
        with path.open('rb') as stream:
            digest = hashlib.file_digest(stream, 'sha256').hexdigest()
        atomic_json(directory / 'source_receipt.json', {'dataset': dataset, 'path': path.name,
                    'bytes': path.stat().st_size, 'sha256': digest, 'status': 'validated',
                    'scope': 'all_authorized_data' if city == ALL_CITIES else 'target_city',
                    'filters': filters, 'city': city, 'city_id': city_id, 'sheets': sheets,
                    'scope_validation': 'batch_with_other_cities' if other_rows else 'exact',
                    'other_city_rows': other_rows,
                    'transport_params': params, 'query_total': total, 'business_rows': rows,
                    'transport': 'http', 'original_unchanged': True, 'payroll_executed': False})
        log('[完成] 蓝橙' + label + '：' + str(rows) + ' 条原始记录')
        return path
    except Exception as exc:
        ledger = directory / 'http_submission.json'
        state = 'unknown'
        if not ledger.exists(): state = 'not_submitted'
        else:
            try: state = json.loads(ledger.read_text(encoding='utf-8')).get('submission_state', 'unknown')
            except (OSError, ValueError): pass
        if state not in ('submitted', 'not_submitted', 'unknown'): state = 'unknown'
        failure = BillCollectionError(str(exc) if isinstance(exc, BillCollectionError) else '蓝橙原始导出未通过文件校验，回执已保留')
        failure.download_submission_state = state
        raise failure from None
