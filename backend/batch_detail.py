"""Export rider detail in platform-sized batches, then split by city.

The platform rejects a single export when the selected teams/rows exceed its
limit. Each group is exported and validated independently; a group still
rejected with HTTP 400 is split again before any city file is published.
"""
import csv
from pathlib import Path
import time

import xlsxwriter
from openpyxl import Workbook, load_workbook

import workbook_policy  # noqa: F401  安装统一 ZIP 压缩策略
from download_archive import archive_component
from fengshen_bill import BillCollectionError, atomic_json
from fengshen_http import HttpTransportError
from fengshen_http_riders import DETAIL_DIRECT_EXPORT, detail_coverage_gap
from rider_sources import QUERIES, validate_document

MAX_BATCH_TEAMS = 25
SLOW_ACCOUNT_SECONDS = 8

ACCOUNT_HEADERS = ['团队ID', '团队名称', '骑手ID', '收款方式', '收款账户', '收款账户姓名', '收款账户身份证']
ACCOUNT_QUERY_PAGE = 5000
RECEIVE_TYPES = {0: '未设置', 1: '支付宝', 2: '银行卡', 3: '他人银行卡'}


def _text(value):
    return '' if value is None else str(value).strip()


def _account_row(row):
    if not isinstance(row, dict):
        raise BillCollectionError('收薪账户查询记录格式变化，未写入批量文件')
    team_id = row.get('teamId')
    knight_id = row.get('knightId')
    receive_type = row.get('receiveType')
    if (isinstance(team_id, bool) or not isinstance(team_id, (int, str))
            or isinstance(knight_id, bool) or not isinstance(knight_id, (int, str))
            or type(receive_type) is not int or receive_type not in RECEIVE_TYPES):
        raise BillCollectionError('收薪账户查询字段格式变化，未写入批量文件')
    return [team_id, _text(row.get('teamName')), knight_id, RECEIVE_TYPES[receive_type],
            _text(row.get('receiveAccount')), _text(row.get('receiveAccountName')),
            _text(row.get('receiveAccountCertificateNum'))]


def _account_rows(client, plan):
    rows, total = [], None
    for page in range(1, 1001):
        payload = client.request_json("GET", QUERIES['receive_account'],
                                      params={"month": plan.month, "pageIndex": page,
                                              "pageSize": ACCOUNT_QUERY_PAGE})
        data = payload.get('data') if isinstance(payload, dict) else None
        values = data.get('datas') if isinstance(data, dict) else None
        count = data.get('rowcount') if isinstance(data, dict) else None
        if not isinstance(values, list) or type(count) is not int or count < 0:
            raise BillCollectionError('收薪账户查询结构变化，未写入批量文件')
        if total is None:
            total = count
        elif count != total:
            raise BillCollectionError('收薪账户查询总数在翻页期间发生变化，未写入批量文件')
        rows.extend(_account_row(row) for row in values)
        if len(rows) == total:
            return rows
        if not values or len(rows) > total:
            break
    raise BillCollectionError('收薪账户查询分页不完整，未写入批量文件')


def _write_account_xlsx(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name('.' + path.stem + '.tmp.xlsx')
    book = Workbook(write_only=True)
    try:
        sheet = book.create_sheet('sheet0')
        sheet.append(ACCOUNT_HEADERS)
        for row in rows:
            sheet.append(row)
        book.save(temporary)
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def _collect_account(client, plan, root, log, timings=None):
    started = time.perf_counter()
    rows = _account_rows(client, plan)
    query_seconds = time.perf_counter() - started
    directory = (root / '原始资料' / archive_component(plan.city) / 'payment_binding'
                 / plan.month / 'receive_account')
    target = directory / f"收薪账户_{plan.start}_{plan.end}.xlsx"
    started = time.perf_counter()
    _write_account_xlsx(target, rows)
    write_seconds = time.perf_counter() - started
    started = time.perf_counter()
    info = validate_document(target, 'receive_account', plan, {})
    validate_seconds = time.perf_counter() - started
    if timings is not None:
        timings.update(query=query_seconds, write=write_seconds, validate=validate_seconds)
    if info['rows'] != len(rows):
        raise BillCollectionError('收薪账户批量文件行数与查询不一致')
    info.update(city=plan.city, agency_id=plan.agency_id, requested_start=plan.start,
                requested_end=plan.end, requested_month=plan.month, all_target_teams=True,
                scope='platform_city', team_validation=False, query_total=len(rows),
                snapshot_only=True, export_mode='original')
    atomic_json(target.parent / 'source_receipt.json', {
        **info, 'dataset': 'receive_account', 'kind': 'receive_account', 'city': plan.city,
        'month': plan.month, 'target_city_only': True, 'binding_generated': False,
        'payroll_executed': False, 'transport': 'http', 'batch_source': '分页查询',
    })
    log(f"[批量] {plan.city} · {plan.month} 收薪账户：{len(rows)} 条，分页查询已保存")
    return target


def _info_groups(plans, scopes):
    if len(plans) <= 4:
        return [plans]
    total = sum(len(scopes[plan.city][1]) for plan in plans)
    target = (total + 1) // 2
    first, teams = [], 0
    for plan in plans:
        first.append(plan)
        teams += len(scopes[plan.city][1])
        if teams >= target:
            break
    if len(first) == len(plans):
        middle = len(plans) // 2
        return [plans[:middle], plans[middle:]]
    return [first, plans[len(first):]]


def _split_rider_info(combined, plans, scopes, root, total_rows):
    department_city = {}
    for plan in plans:
        for name in scopes[plan.city][1].values():
            if name in department_city and department_city[name] != plan.city:
                raise BillCollectionError(f"骑手信息站点名称跨城市重复：{name}")
            department_city[name] = plan.city
    books, sheets, temps, counts = {}, {}, {}, {plan.city: 0 for plan in plans}
    finals = {}
    try:
        source = load_workbook(combined, read_only=True, data_only=True)
        try:
            if len(source.worksheets) != 1:
                raise BillCollectionError("骑手信息批量导出子表数量变化，整批未发布")
            sheet = source.worksheets[0]
            sheet.reset_dimensions()
            rows = sheet.iter_rows(values_only=True)
            header = next(rows, None)
            if not header or "部门" not in header or "骑手ID" not in header:
                raise BillCollectionError("骑手信息批量导出缺少部门或骑手ID列，整批未发布")
            department_index = header.index("部门")
            for plan in plans:
                directory = (root / '原始资料' / archive_component(plan.city) / 'payment_binding'
                             / plan.month / 'rider_info')
                directory.mkdir(parents=True, exist_ok=True)
                temps[plan.city] = directory / f".{plan.city}.rider_info.tmp.xlsx"
                book = xlsxwriter.Workbook(str(temps[plan.city]),
                                           {'constant_memory': True,
                                            'strings_to_formulas': False,
                                            'strings_to_urls': False})
                books[plan.city] = book
                sheets[plan.city] = book.add_worksheet('sheet0')
                sheets[plan.city].write_row(0, 0, list(header))
            for row in rows:
                if not any(value is not None and str(value).strip() for value in row):
                    continue
                if len(row) != len(header):
                    raise BillCollectionError("骑手信息批量导出行列结构损坏，整批未发布")
                city = department_city.get(str(row[department_index]).strip())
                if city is None:
                    raise BillCollectionError("骑手信息批量导出包含未知站点，整批未发布")
                sheets[city].write_row(counts[city] + 1, 0, list(row))
                counts[city] += 1
        finally:
            source.close()
        for plan in plans:
            books[plan.city].close()
        if sum(counts.values()) != total_rows:
            raise BillCollectionError("骑手信息批量导出行数与拆分结果不一致，整批未发布")
        missing = [plan.city for plan in plans if not counts[plan.city]]
        if missing:
            raise BillCollectionError("骑手信息批量导出未覆盖城市：" + "、".join(missing))
        results = {}
        for plan in plans:
            final = temps[plan.city].with_name(f"骑手信息_{plan.start}_{plan.end}.xlsx")
            temps[plan.city].replace(final)
            finals[plan.city] = final
            info = validate_document(final, 'rider_info', plan, scopes[plan.city][1])
            if info['rows'] != counts[plan.city]:
                raise BillCollectionError("骑手信息批量拆分后行数不一致，整批未发布")
            atomic_json(final.parent / 'source_receipt.json', {
                **info, 'dataset': 'rider_info', 'kind': 'rider_info', 'city': plan.city,
                'agency_id': plan.agency_id, 'start': plan.start, 'end': plan.end,
                'month': plan.month, 'requested_start': plan.start, 'requested_end': plan.end,
                'requested_month': plan.month, 'target_city_only': True,
                'all_target_teams': True, 'snapshot_only': True,
                'time_basis': 'current_snapshot', 'binding_generated': False,
                'payroll_executed': False, 'transport': 'http',
                'batch_source': '全城市批量',
            })
            results[plan.city] = final
        return results
    except Exception:
        for book in books.values():
            try:
                book.close()
            except Exception:
                pass
        _cleanup(temps.values())
        for path in finals.values():
            _cleanup([path, path.parent / 'source_receipt.json'])
        raise


def _retry_city_mismatch(client, agency_id, action):
    try:
        return action()
    except HttpTransportError as exc:
        if '城市' not in str(exc):
            raise
        client.select_city(agency_id)
        return action()


def _collect_rider_info(client, collector, plans, scopes, root, log):
    produced = {}
    groups = _info_groups(plans, scopes)
    for index, group in enumerate(groups, 1):
        primary = group[0]
        teams, agencies = {}, {}
        for plan in group:
            teams.update(scopes[plan.city][1])
            agencies.update(scopes[plan.city][2])
        batch_dir = (root / '原始资料' / '支付绑定平台表' / '骑手信息批量'
                     / primary.month / f"批次{index}")
        try:
            client.select_city(primary.agency_id)
            info = _retry_city_mismatch(
                client, primary.agency_id,
                lambda: collector.rider_info_export(primary, batch_dir, teams, agencies))
            source = batch_dir / f"骑手信息_{primary.start}_{primary.end}.xlsx"
            produced.update(_split_rider_info(source, group, scopes, root, info['rows']))
        except Exception as exc:
            for path in produced.values():
                _cleanup([path, path.parent / 'source_receipt.json'])
            log(f"[降级] {primary.month} 骑手信息批量导出失败，改为逐城市导出：{exc}")
            return {}
    log(f"[批量] {primary.month} 骑手信息：{len(plans)} 城分 "
        f"{len(groups)} 批导出，已按城市拆分")
    return produced


def _cleanup(paths):
    for path in paths:
        try:
            Path(path).unlink(missing_ok=True)
        except OSError:
            pass


def _groups(plans, scopes, totals=None):
    groups, current, teams = [], [], set()
    for plan in plans:
        planned = teams | set(scopes[plan.city][1])
        if current and len(planned) > MAX_BATCH_TEAMS:
            groups.append(current)
            current, planned = [plan], set(scopes[plan.city][1])
        else:
            current.append(plan)
        teams = planned
    if current:
        groups.append(current)
    return groups


def _split(combined, scopes, root):
    plans = {city: scope[0] for city, scope in scopes.items()}
    team_city = {team: city for city, (_, teams, _) in scopes.items() for team in teams}
    city_temps, writers = {}, {}
    counts = {city: 0 for city in scopes}
    unknown = set()
    try:
        with combined.open(encoding="utf-8-sig", newline="", errors="replace") as source:
            reader = csv.reader(source)
            header = next(reader, None)
            if not header or "团队ID" not in header or "日期" not in header:
                raise BillCollectionError("全城市骑手明细缺少团队ID或日期列，未拆分")
            team_index, date_index = header.index("团队ID"), header.index("日期")
            for city in scopes:
                directory = root / "原始资料" / archive_component(city) / "payment_binding" / plans[city].month / "rider_detail"
                directory.mkdir(parents=True, exist_ok=True)
                temp = directory / f".{city}.rider_detail.part.csv"
                city_temps[city] = temp
                writers[city] = temp.open("w", encoding="utf-8-sig", newline="")
                csv.writer(writers[city]).writerow(header)
            for row in reader:
                if not row:
                    continue
                if len(row) != len(header):
                    raise BillCollectionError("全城市骑手明细行列结构损坏，未拆分")
                city = team_city.get(row[team_index])
                if city is None:
                    unknown.add(str(row[team_index]))
                    continue
                csv.writer(writers[city]).writerow(row)
                counts[city] += 1
                if date_index >= len(row):
                    raise BillCollectionError("全城市骑手明细日期列缺失，未拆分")
            if unknown:
                raise BillCollectionError("全城市骑手明细包含未知站点，未拆分：" + "、".join(sorted(unknown)[:5]))
    finally:
        for stream in writers.values():
            stream.close()
    try:
        results = {}
        for city, (_, teams, _) in scopes.items():
            plan = plans[city]
            info = validate_document(city_temps[city], "rider_detail", plan, teams)
            gap = detail_coverage_gap(info, plan)
            if gap is not None and gap > 3:
                raise BillCollectionError(
                    f"{city} 骑手明细仅覆盖到 {info['date_max']}，未覆盖至 {plan.end}；整批未发布")
            final = city_temps[city].with_name(f"骑手数据明细_{plan.start}_{plan.end}.csv")
            info["path"] = final.name
            results[city] = (final, info)
        for city, (final, info) in results.items():
            city_temps[city].replace(final)
            plan = plans[city]
            atomic_json(final.parent / "source_receipt.json", {
                **info, "dataset": "rider_detail", "kind": "rider_detail", "city": city,
                "agency_id": plan.agency_id, "start": plan.start, "end": plan.end,
                "month": plan.month, "requested_start": plan.start, "requested_end": plan.end,
                "target_city_only": True, "binding_generated": False,
                "payroll_executed": False, "transport": "http", "batch_source": "全城市批量",
            })
        return {city: results[city][0] for city in results}
    except Exception:
        _cleanup(city_temps.values())
        raise


def _export_group(client, collector, group, scopes, root, suffix, fields=None):
    primary = group[0]
    combined = {}
    for plan in group:
        combined.update(scopes[plan.city][1])
    fields = fields or collector._fields()
    body = {"teamIds": [int(value) for value in sorted(combined)],
            "startAt": primary.start, "endAt": primary.end, "exportType": 2, "fields": fields}
    batch_dir = root / "原始资料" / "支付绑定平台表" / "明细批量" / primary.month
    batch_dir.mkdir(parents=True, exist_ok=True)
    target = batch_dir / f"骑手数据明细_全城市_{primary.start}_{primary.end}_{suffix}.csv"
    client.select_city(primary.agency_id)
    try:
        client.download_request("POST", DETAIL_DIRECT_EXPORT, target, body=body)
        info = validate_document(target, "rider_detail", primary, combined)
        gap = detail_coverage_gap(info, primary)
        if gap is not None and gap > 3:
            raise BillCollectionError(
                f"全城市骑手明细仅覆盖到 {info['date_max']}，未覆盖至 {primary.end}；整批未发布")
        if info["rows"] == 0:
            raise BillCollectionError(f"平台在 {primary.start} 至 {primary.end} 没有骑手明细数据；未生成批量文件")
        subset = {plan.city: scopes[plan.city] for plan in group}
        return _split(target, subset, root), target, info
    except HttpTransportError as exc:
        if "HTTP 400" in str(exc) and len(group) > 1:
            middle = len(group) // 2
            left_paths, left_target, left_info = _export_group(
                client, collector, group[:middle], scopes, root, suffix + "_1", fields)
            right_paths, right_target, right_info = _export_group(
                client, collector, group[middle:], scopes, root, suffix + "_2", fields)
            return ({**left_paths, **right_paths}, [left_target, right_target],
                    {"rows": left_info["rows"] + right_info["rows"],
                     "sha256": left_info["sha256"] + "+" + right_info["sha256"]})
        raise


def collect_batch_detail(client, collector, plans, root, log, cancelled, account_paths=None,
                         rider_info_paths=None):
    """Return {(city, month): split path}; raise on any whole-batch ambiguity."""
    if not plans:
        return {}
    months = {plan.month for plan in plans}
    periods = {(plan.start, plan.end) for plan in plans}
    if len(months) != 1 or len(periods) != 1:
        raise BillCollectionError("全城市明细批量只支持同一月份和同一日期范围")
    month = plans[0].month
    start, end = plans[0].start, plans[0].end
    scopes, accounts = {}, {}
    scope_times = {}
    produced, account_written, info_written, batch_files = {}, [], [], []
    try:
        for plan in plans:
            client.checkpoint()
            retries_before = getattr(client, 'rate_limited_count', 0)
            started = time.perf_counter()
            client.select_city(plan.agency_id)
            selected = time.perf_counter()
            teams, agencies = _retry_city_mismatch(
                client, plan.agency_id, lambda plan=plan: collector._teams(plan))
            scope_times[plan.city] = (selected - started, time.perf_counter() - selected,
                                      getattr(client, 'rate_limited_count', 0) - retries_before)
            scopes[plan.city] = (plan, teams, agencies)
        # 骑手信息优先导出：需要短信确认时，任务开始几秒内就提示，而不是让用户干等账户查询。
        infos = _collect_rider_info(client, collector, plans, scopes, root, log)
        info_written = list(infos.values())
        for plan in plans:
            client.checkpoint()
            retries_before = getattr(client, 'rate_limited_count', 0)
            select_started = time.perf_counter()
            client.select_city(plan.agency_id)
            select_seconds = time.perf_counter() - select_started
            timings = {}
            try:
                path = _collect_account(client, plan, root, log, timings)
                accounts[plan.city] = path
                account_written.append(path)
            except Exception as exc:
                log(f"[降级] {plan.city} · {month} 收薪账户分页查询失败，改为逐城市导出：{exc}")
            finally:
                select_first, teams_seconds, retries_scope = scope_times[plan.city]
                retries = retries_scope + getattr(client, 'rate_limited_count', 0) - retries_before
                total = (select_first + teams_seconds + select_seconds
                         + timings.get('query', 0) + timings.get('write', 0)
                         + timings.get('validate', 0))
                if total >= SLOW_ACCOUNT_SECONDS:
                    log(f"[慢] {plan.city} · {month} 收薪账户批量查询 {total:.1f} 秒"
                        f"（切城 {select_first + select_seconds:.1f} / 站点 {teams_seconds:.1f}"
                        f" / 分页查询 {timings.get('query', 0):.1f}"
                        f" / 写盘校验 {timings.get('write', 0) + timings.get('validate', 0):.1f}"
                        f"，429 重试 {retries} 次）")
        groups = _groups(plans, scopes)
        fields = collector._fields()
        for index, group in enumerate(groups, 1):
            client.checkpoint()
            paths, target, info = _retry_city_mismatch(
                client, group[0].agency_id,
                lambda group=group, index=index: _export_group(
                    client, collector, group, scopes, root, f"批次{index}", fields))
            produced.update(paths)
            batch_files.append({"cities": [plan.city for plan in group],
                                "file": [Path(value).name for value in (target if isinstance(target, list) else [target])],
                                "rows": info["rows"], "sha256": info["sha256"]})
        batch_dir = root / "原始资料" / "支付绑定平台表" / "明细批量" / month
        atomic_json(batch_dir / "batch_detail.json", {
            "month": month, "start": start, "end": end, "cities": sorted(scopes),
            "groups": batch_files, "rows": sum(value["rows"] for value in batch_files),
            "team_count": sum(len(teams) for _, teams, _ in scopes.values()),
        })
        if account_paths is not None:
            account_paths.update({(city, month): path for city, path in accounts.items()})
        if rider_info_paths is not None:
            rider_info_paths.update({(city, month): path for city, path in infos.items()})
        log(f"[批量] {month} 骑手数据明细：{len(scopes)} 城分 {len(groups)} 批导出，"
            f"{sum(value['rows'] for value in batch_files)} 行，已按城市拆分")
        return {(city, month): path for city, path in produced.items()}
    except Exception:
        for path in produced.values():
            _cleanup([path, path.parent / "source_receipt.json"])
        for path in account_written:
            _cleanup([path, path.parent / "source_receipt.json"])
        for path in info_written:
            _cleanup([path, path.parent / "source_receipt.json"])
        raise