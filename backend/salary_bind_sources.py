"""All authorized logistics-partner cities for the independent binding module."""

import asyncio
import csv
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import re
import shutil
import threading
import uuid

from openpyxl import load_workbook

from fengshen_bill import atomic_json, BillCollectionError, safe_operation_failure
from parttime_source import COLLECTION_LOCK, SourceError, TemplatePlan, label, owned_upload, parse_date, source_files
from rider_sources import DOWNLOAD_ORDER, HEADERS, NAMES, PAGES, RiderSourceCollector, source_profile
from shangyi_sources import download_employees_http, validate_employees, workspace_directory

BINDING_LOCK = threading.Lock()


def date_scope(start, end):
    first, last = parse_date(start), parse_date(end)
    if first > last:
        raise SourceError('开始日期不能晚于结束日期')
    if (first.year, first.month) != (last.year, last.month):
        raise SourceError('支付绑定日期只能选择同一个月，不能跨月')
    return {'start': first.isoformat(), 'end': last.isoformat(), 'month': first.strftime('%Y-%m')}


def city_plans(texts, scope):
    plans, ids = [], set()
    for text in texts:
        match = re.match(r'^\s*\[(\d{1,20})\]\s*\[([^\[\]]+)\]', text)
        if not match or match[1] in ids:
            raise SourceError('物流合作商城市列表结构变化或编号重复，不能确认全部城市')
        ids.add(match[1])
        city = label(match[2])
        if not city:
            raise SourceError('物流合作商城市名称缺失')
        plans.append(TemplatePlan(city, match[1], scope['start'], scope['end'], scope['month'], '', '', 0))
    if not plans:
        raise SourceError('物流合作商列表为空，未获取不等于无数据')
    return plans


def collect_cities(scope, run, owner, log, cancelled, notify):
    from fengshen_auth import BROKER, BrowserAuth, open_context, launch_background_edge, reveal_edge, conceal_edge
    from playwright.sync_api import sync_playwright
    if not COLLECTION_LOCK.acquire(blocking=False):
        raise SourceError('另一项资料采集正在运行，请等待完成')
    try:
        with BROKER.operation(owner.name, cancelled, notify), sync_playwright() as pw:
            browser = launch_background_edge(pw)
            try:
                context = open_context(browser, BROKER)
                page = context.new_page()
                conceal_edge(page)
                auth = BrowserAuth(page, context, BROKER, cancelled, log, reveal=reveal_edge, conceal=conceal_edge)
                seed = TemplatePlan('', '31029436', scope['start'], scope['end'], scope['month'], '', '', 0)
                auth.navigate(PAGES['rider_detail'])
                auth.ensure(PAGES['rider_detail'], source_profile(seed))
                probe = RiderSourceCollector(page, seed, run, log, cancelled)
                probe._dismiss_notice()
                probe._control('city_trigger').click()
                popup = probe._control('city_popup')
                group = probe._logistics_partner_group(popup)
                plans = city_plans(group.locator('p.info').all_inner_texts(), scope)
                probe._close_city_popup(popup)
                atomic_json(run / 'cities.json', [asdict(plan) for plan in plans])
                log(f'[城市] 已读取物流合作商全部 {len(plans)} 个授权城市；不使用物流服务商')
                results = []
                def navigate(url, profile):
                    auth.navigate(url)
                    auth.ensure(url, profile)
                for index, plan in enumerate(plans, 1):
                    if cancelled.is_set():
                        raise SourceError('下载已取消')
                    directory = run / plan.agency_id
                    directory.mkdir()
                    manifest = {'status': 'running', 'plan': asdict(plan), 'datasets': {}}
                    atomic_json(directory / 'manifest.json', manifest)
                    collector = RiderSourceCollector(page, plan, directory, log, cancelled, auth=navigate,
                                                      reveal=reveal_edge, conceal=conceal_edge)
                    log(f'[城市 {index}/{len(plans)}] {plan.city} / {plan.agency_id}')
                    for kind in DOWNLOAD_ORDER:
                        manifest['stage'] = kind
                        atomic_json(directory / 'manifest.json', manifest)
                        try:
                            manifest['datasets'][kind] = collector.collect(kind)
                        except Exception as exc:
                            message = str(exc) if isinstance(exc, BillCollectionError) else f'网页操作未完成（{type(exc).__name__}）'
                            manifest.update(status='error', error=message, failure=safe_operation_failure(exc),
                                            control=getattr(collector, 'last_control', None))
                            atomic_json(directory / 'manifest.json', manifest)
                            raise SourceError(f'{plan.city} / {NAMES[kind]}：{message}；失败阶段已保存') from None
                        atomic_json(directory / 'manifest.json', manifest)
                    manifest['status'] = 'success'
                    atomic_json(directory / 'manifest.json', manifest)
                    results.append((directory, manifest))
                return results
            finally:
                browser.close()
    finally:
        COLLECTION_LOCK.release()


def verified_file(directory, info):
    candidate = Path(directory) / info['path']
    path = candidate.resolve()
    if not path.is_relative_to(Path(directory).resolve()) or not path.is_file() or candidate.is_symlink():
        raise SourceError('下载文件缺失或路径越界')
    if hashlib.sha256(path.read_bytes()).hexdigest() != info.get('sha256'):
        raise SourceError('下载文件校验值变化，不能生成绑定')
    return path


def rows_from(path):
    if path.suffix.lower() == '.csv':
        with path.open(encoding='utf-8-sig', newline='') as stream:
            rows = list(csv.reader(stream))
    else:
        workbook = load_workbook(path, read_only=True, data_only=False)
        try:
            if len(workbook.worksheets) != 1:
                raise SourceError('资料子表数量变化')
            workbook.worksheets[0].reset_dimensions()
            rows = list(workbook.worksheets[0].iter_rows(values_only=True))
        finally:
            workbook.close()
    if not rows:
        raise SourceError('资料没有表头')
    headers = [label(value) for value in rows[0]]
    if any(not header for header in headers) or len(headers) != len(set(headers)):
        raise SourceError('资料表头缺失或重复')
    records = []
    for row in rows[1:]:
        if not any(value is not None and str(value).strip() for value in row):
            continue
        if len(row) != len(headers):
            raise SourceError('资料行列结构损坏')
        records.append(dict(zip(headers, row)))
    return headers, records


def prepare_inputs(results, employees, inputs, scope):
    all_rows = {kind: [] for kind in NAMES}
    fields, team_cities, identities = {}, {}, {}
    agencies = set()
    agency_cities = {manifest['plan']['agency_id']: manifest['plan']['city'] for _, manifest in results}
    team_agencies = {}
    for _, manifest in results:
        for team_id, agency_id in manifest['datasets']['rider_detail'].get('team_agency_ids', {}).items():
            if team_id in team_agencies and team_agencies[team_id] != agency_id:
                raise SourceError('同一团队ID对应多个合作商编号，需核对站点接口')
            team_agencies[team_id] = agency_id
    detail_rows = {}
    for directory, manifest in results:
        plan = manifest['plan']
        if manifest.get('status') != 'success' or plan['agency_id'] in agencies:
            raise SourceError('城市下载未完成或重复')
        agencies.add(plan['agency_id'])
        if any(plan[key] != scope[key] for key in ('start', 'end', 'month')):
            raise SourceError('城市下载日期不一致')
        for kind in NAMES:
            info = manifest['datasets'][kind]
            expected = {'city': plan['city'], 'agency_id': plan['agency_id'], 'requested_start': scope['start'],
                        'requested_end': scope['end'], 'requested_month': scope['month'], 'all_target_teams': True}
            if info.get('status') not in ('empty', 'validated') or any(info.get(k) != v for k, v in expected.items()):
                raise SourceError('下载清单城市、日期或全站点范围不符')
            headers, records = rows_from(verified_file(directory, info))
            if not HEADERS[kind].issubset(headers) or len(records) != info['rows']:
                raise SourceError(NAMES[kind] + '表头或记录数不一致')
            fields.setdefault(kind, [])
            fields[kind] += [header for header in headers if header not in fields[kind]]
            for row in records:
                if kind == 'rider_detail':
                    if '骑手姓名' not in headers:
                        raise SourceError('骑手数据明细缺少骑手姓名')
                    if not scope['start'] <= parse_date(row['日期']).isoformat() <= scope['end']:
                        raise SourceError('骑手明细超出选择日期')
                    team = label(row['团队名称']).replace('（', '(').replace('）', ')')
                    city = plan['city']
                    if info.get('all_available_teams'):
                        agency = team_agencies.get(label(row['团队ID']))
                        if agency not in agency_cities:
                            raise SourceError('全站点明细的团队ID缺少授权城市归属，需核对站点接口')
                        city = agency_cities[agency]
                    if team in team_cities and team_cities[team] != city:
                        raise SourceError('跨城市同名站点无法唯一归属')
                    team_cities[team] = city
                    key = (parse_date(row['日期']).isoformat(), label(row['骑手ID']), label(row['团队ID']))
                    if key in detail_rows:
                        if detail_rows[key] != row:
                            raise SourceError('重复骑手日明细内容不一致，需核对原文件')
                        continue
                    detail_rows[key] = row
                if kind == 'rider_info':
                    rid, identity = label(row['骑手ID']), label(row['身份证']).upper()
                    if rid and re.fullmatch(r'\d{17}[\dX]', identity):
                        if rid in identities and identities[rid] != identity:
                            raise SourceError('同一骑手ID对应多个完整身份证，需人工核对')
                        identities[rid] = identity
                all_rows[kind].append(row)
    if not agencies or not all_rows['rider_detail']:
        raise SourceError('所选日期全部城市没有骑手明细，未生成绑定')
    inputs.mkdir()
    for kind, records in all_rows.items():
        # Keep complete IDs from being overwritten by another city's masked version.
        if kind == 'rider_info':
            for row in records:
                if label(row['骑手ID']) in identities:
                    row['身份证'] = identities[label(row['骑手ID'])]
        with (inputs / (NAMES[kind] + '.csv')).open('w', encoding='utf-8-sig', newline='') as stream:
            writer = csv.DictWriter(stream, fieldnames=fields[kind])
            writer.writeheader()
            writer.writerows(records)
    directory, manifest = employees
    if manifest.get('status') != 'success' or manifest.get('scope') != 'all':
        raise SourceError('白泽全量资料未完成校验')
    info = manifest['datasets']['merchant_employees']
    path = verified_file(directory, info)
    checked = validate_employees(path)
    if checked['rows'] != info['rows']:
        raise SourceError('白泽记录数变化')
    shutil.copy2(path, inputs / 'merchantFreelancer_白泽全量.xlsx')
    return {**scope, 'team_cities': team_cities, 'agency_count': len(agencies)}


def prepare(config, workspace, log, cancelled, notify):
    scope = date_scope(config.salaryBindStartDate, config.salaryBindEndDate)
    owner = workspace_directory(workspace)
    supplements = []
    if config.sourcePath and config.sourcePath not in ('./uploads', './data', '/mock/data'):
        folder, _ = owned_upload(config.sourcePath, workspace)
        supplements = source_files(folder)
        if any(not any(word in path.name for word in ('代领', '代发', '黑户')) for path in supplements):
            raise SourceError('自动生成只需上传代领明细，不使用 template 或手动平台资料')
    if not supplements:
        raise SourceError('请先上传当月代领明细；无代领记录时可提供仅含表头的文件')
    for path in supplements:
        if path.suffix.lower() not in ('.xlsx', '.csv'):
            raise SourceError('自动生成的代领明细请提供 XLSX 或 UTF-8 CSV')
        headers, _ = rows_from(path)
        if not set(headers).intersection({'骑手ID', '身份证', '身份证号', '身份证号码', '骑手姓名', '姓名'}):
            raise SourceError('代领明细缺少骑手ID、身份证或姓名识别列')
    run = owner / ('salary_bind_sources_' + uuid.uuid4().hex)
    run.mkdir()
    manifest = {'scope': 'all_logistics_partner_cities', **scope, 'status': 'running', 'stage': 'fengshen',
                'originals_retained': True, 'binding_generated': False, 'payroll_executed': False}
    atomic_json(run / 'manifest.json', manifest)
    try:
        results = collect_cities(scope, run, owner, log, cancelled, notify)
        if cancelled.is_set():
            raise SourceError('任务已取消')
        manifest['stage'] = 'baize'
        atomic_json(run / 'manifest.json', manifest)
        employees = download_employees_http(workspace, log, cancelled)
        manifest['baize_sources'] = str(employees[0])
        manifest['stage'] = 'prepare'
        atomic_json(run / 'manifest.json', manifest)
        if cancelled.is_set():
            raise SourceError('任务已取消')
        inputs = run / 'inputs'
        verified = prepare_inputs(results, employees, inputs, scope)
        for index, path in enumerate(supplements):
            shutil.copy2(path, inputs / f'代领补充_{index}{path.suffix.lower()}')
        manifest.update(status='ready', stage='generate', verified_scope=verified, input_path=str(inputs))
        atomic_json(run / 'manifest.json', manifest)
        log('[校验] 全部城市及白泽全量资料已通过；开始生成支付绑定，未执行薪资核算或发薪')
        return run, inputs, verified
    except Exception as exc:
        message = str(exc) if isinstance(exc, BillCollectionError) else '支付绑定自动下载未完成，请检查诊断清单'
        manifest.update(status='error', error=message, failure=safe_operation_failure(exc))
        atomic_json(run / 'manifest.json', manifest)
        log(f'[诊断] 原文件及失败阶段保留在：{run}')
        raise SourceError(message) from None


async def run_automatic_binding(config, workspace):
    import tasks
    from salary_bind_processor import run_salary_bind_gen
    if not BINDING_LOCK.acquire(blocking=False):
        yield tasks.create_finish_event('error', '另一项支付绑定自动生成正在运行')
        return
    cancelled, queue = threading.Event(), asyncio.Queue()
    loop, worker = asyncio.get_running_loop(), None
    def log(message):
        if not cancelled.is_set():
            loop.call_soon_threadsafe(queue.put_nowait, tasks.create_log_event(message))
    def notify(status):
        if not cancelled.is_set():
            event = 'data: ' + json.dumps({'type': 'fengshen_auth', 'status': status}) + '\n\n'
            loop.call_soon_threadsafe(queue.put_nowait, event)
    try:
        date_scope(config.salaryBindStartDate, config.salaryBindEndDate)
        worker = asyncio.create_task(asyncio.to_thread(prepare, config, workspace, log, cancelled, notify))
        while not worker.done() or not queue.empty():
            try:
                yield await asyncio.wait_for(queue.get(), timeout=0.5)
            except asyncio.TimeoutError:
                yield ': heartbeat\n\n'
        run, inputs, verified = await worker
        async for event in run_salary_bind_gen(str(inputs), config.targetPath, config.basePath,
                                              deductionRules=config.deductionRules, verified_scope=verified):
            if event.startswith('data: '):
                payload = json.loads(event[6:])
                if payload.get('type') == 'finish':
                    manifest = json.loads((run / 'manifest.json').read_text(encoding='utf-8'))
                    manifest.update(status=payload['status'], binding_generated=payload['status'] == 'success',
                                    output=payload.get('out_file', ''))
                    atomic_json(run / 'manifest.json', manifest)
            yield event
    except Exception as exc:
        message = str(exc) if isinstance(exc, BillCollectionError) else '自动生成失败，请检查已保留的诊断资料'
        yield tasks.create_log_event(message, 'ERROR')
        yield tasks.create_finish_event('error', message)
    finally:
        cancelled.set()
        try:
            if worker is not None:
                try:
                    await asyncio.shield(worker)
                except Exception:
                    pass
        finally:
            BINDING_LOCK.release()
