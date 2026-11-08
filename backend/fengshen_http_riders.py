"""Official HTTP exports for the three rider documents, without browser use.

Protocols were checked against the Artemis and service-center public clients.
Only explicit export calls create work; recovery only reads the original task.
Receipts deliberately omit phone codes, cookies, signed URLs and rider rows.
"""

import datetime as dt
import base64
import hashlib
import json
import re
import time
from pathlib import Path

from openpyxl import Workbook, load_workbook

from download_rider_sources import _checked_info, _plan_for_kind
from fengshen_bill import atomic_json, nested_value
from fengshen_http import GOODS_RENT_URL, HttpTransportError
from rider_sources import (DETAIL_EXPORT, DETAIL_LIST_QUERY, EXPORT_VERIFICATION_CHECK,
                           NAMES, QUERIES, TEAMS_URL, detail_export_scope,
                           detail_task_id, label, target_teams, team_agencies,
                           unpack_detail_archive, validate_document)
from separation_filter import kept

APOLLO = "https://httpizza.ele.me/lpd_soc.dashboard/apollo"
RECEIVE_EXPORT = "https://httpizza.ele.me/lpd.meepo.mgmt/payment/exportReceiveAccount"
INFO_EXPORT = "https://app2-edu.ele.me/kunkka-svr/ehr/staff/download"
INFO_SEND_CODE = "https://app2-edu.ele.me/kunkka-svr/exportStaff/sendVerifyCode"
DETAIL_INDICATORS = APOLLO + "/indicator/aeolus/indicators"
DETAIL_SWITCH = APOLLO + "/v1.0/front/rollBack/switch"
DETAIL_DIRECT_EXPORT = APOLLO + "/carrier_driver/analysis/pizza/export"
DETAIL_OSS = APOLLO + "/v1.0/export/list/oss"
INDICATOR_GROUPS = ["windgod_carrier_analyse_detail_" + suffix for suffix in
                    ("base", "hr", "work", "tracking", "delivery", "quality")]
_TZ = dt.timezone(dt.timedelta(hours=8))
_TASK_SOURCE = "windgod_carrier_driver_data"
_STATES = {"init", "exporting", "export_completed", "export_fail"}
_KINDS = {"receive_account", "rider_detail", "rider_info"}
TEAMS_SCOPE_ATTEMPTS = 3
GOODS_RENT_HEADERS = ('站点名称', '站点id', '骑手姓名', '骑手id', '手机号',
                      '物资大类', '物资类型', '租用数量', '租用时间', '登记人', '备注', '状态')


def _fail(message, phase="preparing", submission="not_submitted"):
    return HttpTransportError(message, phase, submission)


def _id(value):
    if isinstance(value, bool) or not isinstance(value, (int, str)) or not re.fullmatch(r"\d{1,20}", str(value)):
        raise _fail("平台任务或站点编号格式变化，已停止处理")
    return str(value)


def _ids(values, *, empty=False):
    if not isinstance(values, list) or (not empty and not values):
        raise _fail("原导出范围中的编号列表无效", "waiting_export", "unknown")
    result = [_id(value) for value in values]
    if len(set(result)) != len(result):
        raise _fail("原导出范围中的编号重复", "waiting_export", "unknown")
    return result


def _read_receipt(path):
    path = Path(path)
    if path.is_symlink() or not path.is_file() or path.stat().st_size > 1024 * 1024:
        raise _fail("原导出回执缺失或格式无效，不能恢复", "waiting_export", "unknown")
    try:
        raw = path.read_bytes()
        value = json.loads(raw)
        if not isinstance(value, dict):
            raise ValueError()
    except (OSError, ValueError, UnicodeError):
        raise _fail("原导出回执无法解析，不能恢复", "waiting_export", "unknown") from None
    return value, hashlib.sha256(raw).hexdigest()


def _timestamp(value):
    if type(value) not in (int, float) or value <= 0:
        raise _fail("平台原任务创建时间无法核实", "waiting_export", "unknown")
    return value / 1000 if value > 100_000_000_000 else value


def _submission_time(value):
    try:
        if not isinstance(value, str):
            raise ValueError()
        parsed = dt.datetime.fromisoformat(value)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=_TZ)
        return parsed.timestamp()
    except (ValueError, OverflowError):
        raise _fail("原导出提交时间无效，不能恢复", "waiting_export", "unknown") from None


def _task_scope(row, plan, selected, fields=None):
    """Match the official file name and server-stored export parameters together."""
    identity = _id(row.get("id"))
    name = row.get("fileName")
    prefix = re.escape(f"{plan.start}-{plan.end}.骑手数据明细.{identity}.")
    if (row.get("source") != _TASK_SOURCE or not isinstance(name, str)
            or not re.fullmatch(prefix + r"(?:csv|zip|xlsx)", name)):
        return False
    try:
        value = row.get("exportParam")
        params = json.loads(value) if isinstance(value, str) and len(value) <= 100_000 else None
        if not isinstance(params, dict):
            return False
        # isAgency and partitionIds are platform-generated routing metadata.
        if set(params) - {"teamIds", "startAt", "endAt", "exportType", "fields", "isAgency", "partitionIds"}:
            return False
        if params.get("isAgency", False) is not False:
            return False
        exported_fields = params.get("fields")
        if (not isinstance(exported_fields, list) or not exported_fields
                or any(not isinstance(value, str) or not value for value in exported_fields)
                or len(set(exported_fields)) != len(exported_fields)):
            return False
        return (set(_ids(params.get("teamIds"))) == set(selected)
                and params.get("startAt") == plan.start and params.get("endAt") == plan.end
                and type(params.get("exportType")) is int and params["exportType"] == 2
                and (fields is None or set(exported_fields) == set(fields)))
    except (ValueError, HttpTransportError):
        return False


class RiderHttpCollector:
    def __init__(self, client, log=lambda *_: None, cancelled=None, *, auth=None,
                 wait_seconds=660, poll_seconds=3, clock=time.time, sleep=time.sleep):
        self.client, self.log, self.auth = client, log, auth
        self.cancelled = cancelled if cancelled is not None else getattr(client, "cancelled", None)
        self.wait_seconds, self.poll_seconds = wait_seconds, poll_seconds
        self.clock, self.sleep = clock, sleep
        self.scope_recheck_delay = 3.0

    def _checkpoint(self):
        if self.cancelled is not None and self.cancelled.is_set():
            raise _fail("骑手资料下载已取消", "waiting_export", "unknown")
        self.client.checkpoint()

    def _teams(self, plan):
        # getTeamsAll now returns only the currently selected agency's teams
        # (observed 2026-10-22: it used to list every agency with an agencyId
        # per row). Right after a city switch the platform's config service
        # can briefly still serve the previous agency, so a page without the
        # target agency is re-queried after re-selecting the city. The query
        # is read-only and no export has been submitted at this point.
        payload = None
        for attempt in range(1, TEAMS_SCOPE_ATTEMPTS + 1):
            payload = self.client.request_json("POST", TEAMS_URL, body={})
            result = payload.get("result") if isinstance(payload, dict) else None
            records = result.get("data") if isinstance(result, dict) else None
            if isinstance(records, list) and any(
                    isinstance(row, dict) and str(row.get("agencyId")) == plan.agency_id
                    for row in records):
                teams = target_teams(payload, plan.agency_id)
                agencies = team_agencies(payload)
                return teams, {key: agencies[key] for key in teams}
            if attempt == TEAMS_SCOPE_ATTEMPTS:
                break
            self.log(f"[校验] 第 {attempt} 次站点归属查询未包含目标合作商，正在重查")
            if self.cancelled is not None:
                self.cancelled.wait(self.scope_recheck_delay)
            self._checkpoint()
            self.client.select_city(plan.agency_id)
        if isinstance(records, list):
            found = sorted({str(row.get("agencyId")) for row in records if isinstance(row, dict)})
            self.log("[校验] 站点归属查询始终未包含目标合作商 "
                     + (f"（本次返回合作商：{', '.join(found) or '空'}）" if found else "（返回记录异常）")
                     + f"，已重查 {TEAMS_SCOPE_ATTEMPTS} 次")
        return self._teams_checked(payload, plan)

    def _teams_checked(self, payload, plan):
        teams = target_teams(payload, plan.agency_id)
        agencies = team_agencies(payload)
        return teams, {key: agencies[key] for key in teams}

    def _fields(self):
        payload = self.client.request_json("POST", DETAIL_INDICATORS, body={"groupCodes": INDICATOR_GROUPS})
        rows = payload.get("data") if isinstance(payload, dict) else None
        if (not isinstance(rows, list) or not rows or any(not isinstance(row, dict) for row in rows)):
            raise _fail("骑手明细导出字段接口结构变化，未提交导出")
        fields = []
        for row in rows:
            name = row.get("indicatorCode")
            if (not isinstance(name, str) or not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{0,127}", name)
                    or type(row.get("checkState")) not in (int, bool) or row["checkState"] not in (0, 1)):
                raise _fail("骑手明细导出字段无效，未提交导出")
            if row["checkState"]:
                fields.append(name)
        if not fields or len(set(fields)) != len(fields) or "validCompleteCount" not in fields:
            raise _fail("骑手明细已选字段缺少有效完成单或存在重复，未提交导出")
        return fields

    def _tasks(self):
        result, total = {}, None
        for page in range(1, 201):
            self._checkpoint()
            payload = self.client.request_json("GET", DETAIL_LIST_QUERY, params={"pageIndex": page, "pageSize": 10})
            data = payload.get("data") if isinstance(payload, dict) else None
            if (not isinstance(data, dict) or not isinstance(data.get("list"), list)
                    or type(data.get("totalCount")) is not int or not 0 <= data["totalCount"] <= 2000
                    or data.get("pageNum") != page or data.get("pageSize") != 10):
                raise _fail("平台导出列表结构变化，不能唯一识别原任务", "waiting_export", "unknown")
            if total is None:
                total = data["totalCount"]
            if total != data["totalCount"]:
                raise _fail("平台导出列表在翻页期间发生变化，请恢复查询原任务", "waiting_export", "unknown")
            for row in data["list"]:
                if not isinstance(row, dict):
                    raise _fail("平台导出列表记录格式变化", "waiting_export", "unknown")
                key = _id(row.get("id"))
                if key in result:
                    raise _fail("平台导出列表任务编号重复，不能唯一匹配", "waiting_export", "unknown")
                result[key] = row
            if len(result) == total:
                return result
            if not data["list"] or len(result) > total:
                break
        raise _fail("平台导出列表分页不完整，不能确认原任务", "waiting_export", "unknown")

    def _finish(self, path, kind, plan, teams, agencies, *, total=None, task_id=None):
        path = Path(path)
        self._checkpoint()
        self.client.assert_city(plan.agency_id)
        if path.suffix.lower() == ".zip":
            path, info = unpack_detail_archive(path, plan, teams)
        else:
            info = validate_document(path, kind, plan, teams)
        info.update(city=plan.city, agency_id=plan.agency_id, requested_start=plan.start,
                    requested_end=plan.end, requested_month=plan.month, all_target_teams=True,
                    scope="target_city", export_mode="daily" if kind == "rider_detail" else "original")
        if kind == "receive_account":
            if type(total) is not int or info["rows"] != total:
                raise _fail("收薪账户原文件行数与所选月份查询总数不一致", "validating", "submitted")
            info.update(query_total=total, team_validation=False, snapshot_only=True)
        else:
            info.update(all_available_teams=False, selected_team_ids=sorted(teams), team_agency_ids=agencies)
            if kind == "rider_info":
                info.update(snapshot_only=True, time_basis="current_snapshot")
            else:
                info["task_id"] = task_id
        _checked_info(info, path.parent.resolve(), plan, kind)
        result = {**info, "dataset": kind, "kind": kind, "start": plan.start, "end": plan.end,
                  "month": plan.month if kind == "receive_account" else None,
                  "target_city_only": True, "binding_generated": False, "payroll_executed": False,
                  "transport": "http"}
        atomic_json(path.parent / "source_receipt.json", result)
        self.log(f'[完成] {NAMES[kind]}：{info["rows"]} 条；原文件已校验保存')
        return result

    def _download_sync(self, kind, plan, output, *, body=None, total=None, teams=None, agencies=None, receipt_path=None):
        self.client.assert_city(plan.agency_id)
        method, url, params, extension = "POST", INFO_EXPORT, None, ".xlsx"
        if kind == "receive_account":
            method, url, params = "GET", RECEIVE_EXPORT, {"month": plan.month}
        elif kind == "rider_detail":
            url, extension = DETAIL_DIRECT_EXPORT, ".csv"
        target = output / f"{NAMES[kind]}_{plan.start}_{plan.end}{extension}"
        # scope never contains the one-use export verification code.
        scope = {"kind": kind, "city": plan.city, "agency_id": plan.agency_id,
                 "start": plan.start, "end": plan.end, "month": plan.month,
                 "selected_team_ids": sorted(teams or {})}
        self.client.download_once(method, url, target, receipt_path or output / "source_http_submission.json", scope,
                                  params=params, body=body)
        return self._finish(target, kind, plan, teams or {}, agencies or {}, total=total)

    def goods_rent(self, plan, raw):
        """物资租用登记：全历史快照；站点集合按「是否含取分离」过滤后一次导出。

        接口 2026-10-22 观察：POST exportRentRecord，请求体
        {"params":{"goodsBusinessRentQueryDto":{"page":"1","pageSize":"20",
        "teamIds":[...],"queryType":2}}}，响应 result.data 为 base64 XLSX
        （单子表「租用记录」，全历史行，不受分页参数限制）。
        """
        self._checkpoint()
        teams, _ = self._teams(plan)
        from separation_filter import filter_direction
        include = filter_direction(vars(plan))
        selected = {tid: name for tid, name in teams.items() if include is None or kept(name, include)}
        output = Path(raw).resolve()
        output.mkdir(parents=True, exist_ok=True)
        target = output / f"goods_rent_{plan.start}_{plan.end}.xlsx"
        if selected:
            self.client.assert_city(plan.agency_id)
            body = {"params": {"goodsBusinessRentQueryDto": {
                "page": "1", "pageSize": "20",
                "teamIds": sorted(int(tid) for tid in selected), "queryType": 2}}}
            payload = self.client.request_json("POST", GOODS_RENT_URL, body=body)
            encoded = nested_value(payload, ["result", "data"])
            if not isinstance(encoded, str) or not re.fullmatch(r"[A-Za-z0-9+/=]+", encoded):
                raise _fail("物资租用登记导出返回格式变化，未发布文件")
            content = base64.b64decode(encoded)
            if not content.startswith(b"PK\x03\x04"):
                raise _fail("物资租用登记导出不是有效 XLSX 文件")
            target.write_bytes(content)
        else:
            book = Workbook(write_only=True)
            sheet = book.create_sheet()
            sheet.append([_text_cell(sheet, name) for name in GOODS_RENT_HEADERS])
            book.save(target)
            book.close()
        rows = self._validate_goods_rent(target, selected)
        digest = hashlib.sha256(target.read_bytes()).hexdigest()
        info = {"rows": rows, "status": "validated" if rows else "empty", "scope": "target_city",
                "city": plan.city, "agency_id": plan.agency_id,
                "requested_start": plan.start, "requested_end": plan.end, "requested_month": plan.month,
                "all_target_teams": include is None,
                "selected_team_ids": sorted(selected), "team_count": len(teams),
                "separation_mode": "all" if include is None else "include" if include else "exclude",
                "snapshot_only": True, "time_basis": "current_snapshot",
                "path": target.name, "bytes": target.stat().st_size, "sha256": digest}
        result = {**info, "dataset": "goods_rent", "kind": "goods_rent", "start": plan.start,
                  "end": plan.end, "month": plan.month, "target_city_only": True,
                  "binding_generated": False, "payroll_executed": False, "transport": "http"}
        atomic_json(output / "source_receipt.json", result)
        scope = '全部站点' if include is None else '仅取分离站点' if include else '排除取分离站点'
        self.log(f'[完成] 物资租用登记：{rows} 条（{scope}）；原文件已校验保存')
        return result

    def _validate_goods_rent(self, path, selected):
        book = load_workbook(path, read_only=True, data_only=True)
        try:
            if len(book.worksheets) != 1:
                raise _fail("物资租用登记子表数量变化，需核对导出结构")
            sheet = book.worksheets[0]
            sheet.reset_dimensions()
            iterator = sheet.iter_rows(values_only=True)
            headers = [label(value) for value in next(iterator, ())]
            if (not set(GOODS_RENT_HEADERS).issubset(headers) or any(not h for h in headers)
                    or len(set(headers)) != len(headers)):
                raise _fail("物资租用登记缺少约定表头或表头重复")
            id_index = headers.index("站点id")
            count = 0
            for row in iterator:
                if not any(value is not None and str(value).strip() for value in row):
                    continue
                if len(row) != len(headers):
                    raise _fail("物资租用登记行列结构损坏")
                if str(row[id_index]) not in selected:
                    raise _fail("物资租用登记包含未请求站点的记录")
                count += 1
            return count
        finally:
            book.close()

    def rider_source(self, plan, raw, kind):
        if kind not in _KINDS:
            raise _fail("未知骑手资料下载类型")
        plan = _plan_for_kind(plan, kind)
        output = Path(raw).resolve()
        output.mkdir(parents=True, exist_ok=True)
        self._checkpoint()
        self.client.assert_city(plan.agency_id)
        if kind == "receive_account":
            payload = self.client.request_json("GET", QUERIES[kind],
                                               params={"month": plan.month, "pageIndex": 1, "pageSize": 1})
            data = payload.get("data") if isinstance(payload, dict) else None
            total = data.get("rowcount") if isinstance(data, dict) else None
            if type(total) is not int or total < 0:
                raise _fail("收薪账户查询总数无效，未提交导出")
            return self._download_sync(kind, plan, output, total=total)
        teams, agencies = self._teams(plan)
        if kind == "rider_info":
            # Empty optional filters export all personnel in the selected city.
            self.client.request_json("GET", QUERIES[kind], params={"pageIndex": 1, "pageSize": 1})
            check = self.client.request_json("GET", EXPORT_VERIFICATION_CHECK)
            if not isinstance(check, dict) or type(check.get("data")) is not bool:
                raise _fail("骑手信息导出验证状态无效；未发送验证码")
            body = {"departmentIds": [int(key) for key in sorted(teams)]}
            if check["data"]:
                if not callable(getattr(self.auth, "export_code", None)):
                    raise _fail("骑手信息导出需要额外短信验证，请在系统中完成导出验证", "waiting_manual")
                code = self.auth.export_code(self.client)
                if not isinstance(code, str) or not re.fullmatch(r"\d{4,8}", code):
                    raise _fail("骑手信息导出验证码格式无效", "waiting_manual")
                body["verifyCode"] = code
            try:
                return self._download_sync(kind, plan, output, body=body, teams=teams, agencies=agencies)
            finally:
                body.pop("verifyCode", None)
        return self._detail(plan, output, teams, agencies)

    def _detail(self, plan, output, teams, agencies):
        # Existing receipts must be resolved before any second export call.
        if (output / "detail_submission.json").exists() or (output / "detail_http_submission.json").exists():
            raise _fail("已有骑手明细导出回执，请恢复原任务，不能重复导出", "waiting_export", "unknown")
        self.client.request_json("GET", QUERIES["rider_detail"],
                                 params={"startAt": plan.start, "endAt": plan.end, "pageNum": 1, "pageSize": 1})
        fields = self._fields()
        body = {"teamIds": [int(value) for value in sorted(teams)], "startAt": plan.start,
                "endAt": plan.end, "exportType": 2, "fields": fields}
        if not detail_export_scope(body, plan, teams):
            raise _fail("骑手明细导出范围核对失败，未提交导出")
        switch = self.client.request_json("GET", DETAIL_SWITCH, params={"name": "windgod_export_roll_back_switch"})
        if not isinstance(switch, dict) or type(switch.get("data")) is not int or switch["data"] not in (0, 1):
            raise _fail("平台骑手明细导出方式未知，未提交导出")
        if switch["data"] == 0:
            return self._download_sync("rider_detail", plan, output, body=body, teams=teams, agencies=agencies)
        baseline = set(self._tasks())
        self.client.assert_city(plan.agency_id)
        started = self.clock()
        receipt = {"transport": "http", "status": "awaiting_acknowledgement", "start": plan.start,
                   "end": plan.end, "agency_id": plan.agency_id, "city": plan.city,
                   "selected_team_ids": sorted(teams), "existing_task_ids": sorted(baseline), "fields": fields,
                   "submitted_at": dt.datetime.fromtimestamp(started, _TZ).isoformat(), "request_observed": True}
        atomic_json(output / "detail_submission.json", receipt)
        payload, _ = self.client.submit_once(DETAIL_EXPORT, body, output / "detail_http_submission.json",
                                             {"kind": "rider_detail", "agency_id": plan.agency_id, "request": body})
        data = payload.get("data") if isinstance(payload, dict) else None
        code = data.get("code") if isinstance(data, dict) else None
        if code == 4 and type(code) is int:
            # The official UI explicitly routes this acknowledgement to its
            # synchronous endpoint. A network timeout never takes this branch.
            receipt.update(status="direct_export_required", response_code=payload.get("code"), http_status=200)
            atomic_json(output / "detail_submission.json", receipt)
            return self._download_sync("rider_detail", plan, output, body=body, teams=teams, agencies=agencies)
        identity = detail_task_id(payload)
        receipt.update(status="acknowledged", task_id=identity, http_status=200, response_code=payload.get("code"))
        atomic_json(output / "detail_submission.json", receipt)
        atomic_json(output / "detail_task.json", {"task_id": identity, "start": plan.start, "end": plan.end,
                                                  "selected_team_ids": sorted(teams)})
        self.log("[导出] 骑手数据明细已提交，正在查询原任务；不会重复提交")
        return self._wait_detail(plan, output, teams, agencies, baseline, started, identity, fields)

    def _wait_detail(self, plan, output, teams, agencies, baseline, started, identity, fields=None):
        deadline = self.clock() + self.wait_seconds
        while True:
            self._checkpoint()
            tasks = self._tasks()
            candidates = []
            for key, row in tasks.items():
                if key in baseline or (identity is not None and key != identity):
                    continue
                if not _task_scope(row, plan, teams, fields):
                    if identity == key:
                        raise _fail("原导出任务编号对应的城市范围或日期不符，已停止", "waiting_export", "submitted")
                    continue
                created = _timestamp(row.get("exportAt"))
                if not started - 10 <= created <= started + 300:
                    if identity == key:
                        raise _fail("原导出任务创建时间与回执不符，已停止", "waiting_export", "submitted")
                    continue
                candidates.append((key, row))
            if len(candidates) > 1:
                raise _fail("同一范围存在多个候选导出任务，不猜测也不重新导出", "waiting_export", "unknown")
            if candidates:
                identity, row = candidates[0]
                state = row.get("state")
                if state not in _STATES:
                    raise _fail("平台原导出任务状态未知", "waiting_export", "submitted")
                atomic_json(output / "detail_task.json", {"task_id": identity, "start": plan.start, "end": plan.end,
                                                          "selected_team_ids": sorted(teams), "state": state,
                                                          "created_at": dt.datetime.fromtimestamp(_timestamp(row["exportAt"]), _TZ).isoformat()})
                if state == "export_fail":
                    raise _fail("平台原骑手明细导出任务失败；未重新提交", "waiting_export", "submitted")
                if state == "export_completed":
                    return self._download_detail(row, plan, output, teams, agencies)
            if self.clock() >= deadline:
                raise _fail("骑手明细尚未生成；已保留原任务回执，请继续恢复下载", "waiting_export",
                            "submitted" if identity is not None else "unknown")
            self.sleep(self.poll_seconds)

    def _download_detail(self, row, plan, output, teams, agencies):
        self.client.assert_city(plan.agency_id)
        bucket, shard = row.get("bucketName"), row.get("ossShardid")
        if not isinstance(bucket, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{1,127}", bucket):
            raise _fail("原导出文件存储位置无法核实", "downloading", "submitted")
        shard = _id(shard)
        payload = self.client.request_json("POST", DETAIL_OSS,
                                           body={"bucketName": bucket, "objectName": row["fileName"]}, shard_id=shard)
        url = payload.get("data") if isinstance(payload, dict) else None
        if not isinstance(url, str) or not url:
            raise _fail("原导出任务未返回有效文件地址", "downloading", "submitted")
        extension = Path(row["fileName"]).suffix.lower()
        if extension not in (".csv", ".xlsx", ".zip"):
            raise _fail("原导出文件格式未确认", "downloading", "submitted")
        path = output / f"骑手数据明细_{plan.start}_{plan.end}{extension}"
        self.client.download(url, path)
        return self._finish(path, "rider_detail", plan, teams, agencies, task_id=_id(row["id"]))

    def resume_detail(self, plan, raw, source_dir):
        plan = _plan_for_kind(plan, "rider_detail")
        output, source = Path(raw).resolve(), Path(source_dir).resolve()
        output.mkdir(parents=True, exist_ok=True)
        receipt, digest = _read_receipt(source / "detail_submission.json")
        fields = None
        if receipt.get("transport") == "http":
            if (receipt.get("agency_id") != plan.agency_id or receipt.get("start") != plan.start
                    or receipt.get("end") != plan.end or receipt.get("request_observed") is not True
                    or receipt.get("status") not in ("awaiting_acknowledgement", "acknowledged", "direct_export_required")):
                raise _fail("原导出回执范围不符或不是异步任务，不会重新导出", "waiting_export", "unknown")
            selected = _ids(receipt.get("selected_team_ids"))
            baseline = set(_ids(receipt.get("existing_task_ids"), empty=True))
            started = _submission_time(receipt.get("submitted_at"))
            identity = receipt.get("task_id")
            if identity is not None:
                identity = _id(identity)
            fields = receipt.get("fields")
            if not isinstance(fields, list) or not fields or any(not isinstance(field, str) or not field for field in fields):
                raise _fail("原导出字段回执不完整，不能恢复", "waiting_export", "unknown")
            ledger, _ = _read_receipt(source / "detail_http_submission.json")
            expected = {"kind": "rider_detail", "agency_id": plan.agency_id,
                        "request": {"teamIds": [int(value) for value in sorted(selected)], "startAt": plan.start,
                                    "endAt": plan.end, "exportType": 2, "fields": fields}}
            if ledger.get("transport") != "http" or ledger.get("scope") != expected:
                raise _fail("HTTP 导出提交记录与原范围不一致，不能恢复", "waiting_export", "unknown")
        else:
            # Preserve browser-era receipts: the same official task list can be
            # queried by HTTP, without launching or submitting through a page.
            from download_rider_recovery import _submission
            selected, baseline, submitted, identity, digest, _ = _submission(source, plan)
            started = submitted.replace(tzinfo=_TZ).timestamp()
        if identity in baseline:
            raise _fail("原导出编号属于历史基线，不能恢复", "waiting_export", "unknown")
        if (source / "detail_task.json").exists():
            task, _ = _read_receipt(source / "detail_task.json")
            if (task.get("start") != plan.start or task.get("end") != plan.end
                    or set(_ids(task.get("selected_team_ids"))) != set(selected)):
                raise _fail("原任务编号回执与城市日期范围冲突", "waiting_export", "unknown")
            task_id = task.get("task_id")
            if task_id is not None:
                task_id = _id(task_id)
                if (identity is not None and identity != task_id) or task_id in baseline:
                    raise _fail("原导出任务编号回执冲突，不能恢复", "waiting_export", "unknown")
                identity = task_id
        self.client.assert_city(plan.agency_id)
        teams, agencies = self._teams(plan)
        if set(selected) != set(teams):
            raise _fail("当前城市全部站点与原导出范围不一致，已保留任务待核对", "waiting_export", "unknown")
        if receipt.get("transport") == "http" and receipt.get("status") == "direct_export_required":
            if (receipt.get("http_status") != 200 or receipt.get("response_code") != 200
                    or ledger.get("submission_state") != "submitted"
                    or (source / "source_http_submission.json").exists()):
                raise _fail("原同步导出已尝试或回执不完整，不会重复提交", "downloading", "unknown")
            self.log("[恢复] 平台原回执要求同步下载，仅执行尚未调用的原同步步骤")
            return self._download_sync("rider_detail", plan, output, body=expected["request"],
                                       teams=teams, agencies=agencies,
                                       receipt_path=source / "source_http_submission.json")
        recovery = {"mode": "existing_export_only", "transport": "http", "status": "running",
                    "agency_id": plan.agency_id, "start": plan.start, "end": plan.end,
                    "source_submission_sha256": digest, "resubmitted": False,
                    "binding_generated": False, "payroll_executed": False}
        atomic_json(output / "recovery.json", recovery)
        result = self._wait_detail(plan, output, teams, agencies, baseline, started, identity, fields)
        recovery.update(status="completed", task_id=result.get("task_id"))
        atomic_json(output / "recovery.json", recovery)
        return result
