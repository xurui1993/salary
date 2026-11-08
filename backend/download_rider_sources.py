"""Selective rider-source downloads using the download center's shared browser."""

import datetime as dt
import csv
import hashlib
import json
from pathlib import Path
import re
import shutil
import traceback
from types import SimpleNamespace
from urllib.parse import urlparse

from fengshen_bill import MonthlyBillRequest, atomic_json, safe_operation_failure
from parttime_source import SourceError
from rider_sources import RiderSourceCollector


KINDS = frozenset({"rider_detail", "receive_account", "rider_info"})
_SOURCE_FRAME = "iframe[src^='https://artemis.faas.ele.me/']:visible"
_SAFE_HOSTS = frozenset({"aeolus.ele.me", "artemis.faas.ele.me", "lpd-service-center.faas.ele.me", "mozi-login.alibaba-inc.com"})
_SAFE_FRAGMENTS = frozenset({"", "/knight/data-center/detail", "/payment/receive-account", "/export-list", "/humanResource/staffManagement/index"})
_SAFE_CONTROLS = frozenset({"agency_context", "city_trigger", "city_popup", "city_group", "city_group_label",
                            "city_option", "city_selected_option", "city_confirm", "city_close", "content_frame"})
_SAFE_SOURCE_STAGES = frozenset({"navigate", "check_city", "baseline_open_list", "baseline_wait_rows",
                                "baseline_return_detail", "baseline_check_city", "query_frame", "query", "teams",
                                "export_controls", "select_teams", "submit_export", "wait_file", "validate_file"})
_COUNT_SELECTORS = {"table_rows": "tbody tr", "empty_tables": ".el-table__empty-text", "date_inputs": "input.el-range-input",
                    "query_buttons": 'button:has-text("查询")', "export_buttons": 'button:has-text("导出")',
                    "date_popovers": '.el-picker-panel:visible', "loading_masks": '.el-loading-mask:visible',
                    "dialogs": '.el-dialog:visible'}


def _safe_identifier(value):
    return value if isinstance(value, str) and re.fullmatch(r"[A-Za-z_<>][A-Za-z0-9_<>]{0,127}", value) else "other"


def _page_diagnostic(page, collector):
    def snapshot(surface):
        result = {}
        try:
            parsed = urlparse(surface.url)
            result["host"] = parsed.hostname if parsed.hostname in _SAFE_HOSTS else "other"
            fragment = parsed.fragment.split("?", 1)[0]
            result["fragment"] = fragment if fragment in _SAFE_FRAGMENTS else "other"
        except Exception:
            result.update(host="unavailable", fragment="unavailable")
        counts = {}
        for key, selector in _COUNT_SELECTORS.items():
            try:
                count = surface.locator(selector).count()
                if type(count) is int and count >= 0:
                    counts[key] = count
            except Exception:
                pass
        result["counts"] = counts
        try:
            inputs = surface.locator('input.el-range-input')
            count = inputs.count()
            if type(count) is int:
                values = []
                for index in range(min(count, 2)):
                    value = inputs.nth(index).input_value()
                    values.append(value if isinstance(value, str) and re.fullmatch(r'\d{4}-\d{1,2}-\d{1,2}', value) else 'other')
                result["date_input_values"] = values
        except Exception:
            pass
        return result

    diagnostic = {"page": snapshot(page), "frames": []}
    try:
        if getattr(collector, "profile", {}).get("content_frame") == _SOURCE_FRAME:
            count = page.locator(_SOURCE_FRAME).count()
            if type(count) is int and count >= 0:
                diagnostic["source_frame_count"] = count
    except Exception:
        pass
    try:
        for frame in list(page.frames)[:20]:
            diagnostic["frames"].append(snapshot(frame))
    except Exception:
        pass
    return diagnostic


def _failure_context(kind, stage, collector, manual_wait=False):
    source_stage = getattr(collector, "source_stage", None)
    phase, submission = "preparing", "unknown"
    if stage in ("collector_init", "auth_navigation", "auth_check"):
        submission = "not_submitted"
        phase = "waiting_login" if stage.startswith("auth_") else "preparing"
    elif stage in ("receipt_validation", "receipt_write") or source_stage == "validate_file":
        phase = "validating"
    elif source_stage == "wait_file":
        phase = "waiting_export"
    elif source_stage in ("navigate", "check_city", "baseline_open_list", "baseline_wait_rows", "baseline_return_detail",
                           "baseline_check_city", "query_frame", "query", "teams"):
        submission = "not_submitted"
    elif kind in ("rider_detail", "rider_info") and source_stage == "export_controls":
        # These controls only open the station selection. receive_account's
        # similarly named control can submit directly, so it stays unknown.
        submission = "not_submitted"
    elif kind == "rider_detail" and source_stage == "select_teams":
        submission = "not_submitted"
    elif source_stage == "submit_export":
        phase = "submitting"
    if manual_wait and stage == "collect" and source_stage != "validate_file":
        # Manual verification can finish before saving/validating the file.
        # Its earlier log must not hide a subsequent integrity failure.
        phase, submission = "waiting_manual", "unknown"
    receipt = getattr(collector, "detail_submission", None)
    if isinstance(receipt, dict) and receipt.get("request_observed") is True:
        submission = "unknown"
        if (receipt.get("status") == "acknowledged" and type(receipt.get("http_status")) is int
                and receipt["http_status"] == 200 and type(receipt.get("response_code")) is int
                and receipt["response_code"] == 200):
            submission = "submitted"
    if stage.startswith("recovery_"):
        # A navigation failure in recovery says nothing about the original
        # submission. Only a unique matched official task proves it exists.
        phase = {"recovery_save_file": "downloading", "recovery_validate_file": "validating"}.get(stage, "waiting_export")
        submission = "submitted" if (isinstance(getattr(collector, "detail_task", None), str)
                                      and re.fullmatch(r"\d{1,20}", collector.detail_task)
                                      and isinstance(getattr(collector, "recovery_matched_at", None), str)) else "unknown"
    return {"failure_phase": phase, "submission_state": submission}


def _record_failure(output, kind, stage, exc, page, collector, manual_wait=False):
    """Best-effort metadata only; never format an exception or traceback text."""
    try:
        context = _failure_context(kind, stage, collector, manual_wait)
    except Exception:
        context = {"failure_phase": "preparing", "submission_state": "unknown"}
    try:
        for field, value in context.items():
            setattr(exc, "download_" + field, value)
    except Exception:
        pass
    try:
        source = safe_operation_failure(exc)
        diagnostics = {key: source[key] for key in ("pointer_intercepted", "target_closed", "navigation_interrupted")
                       if type(source.get(key)) is bool}
        if source.get("timeout_kind") in ("response", "download", "locator", "other", None):
            diagnostics["timeout_kind"] = source.get("timeout_kind")
        frames = [{"filename": Path(frame.filename).name, "name": _safe_identifier(frame.name), "lineno": frame.lineno}
                  for frame in traceback.extract_tb(exc.__traceback__)[-20:]]
        result = {"kind": kind, "stage": stage, "exception_type": _safe_identifier(type(exc).__name__),
                  "diagnostics": diagnostics, "traceback": frames,
                  "binding_generated": False, "payroll_executed": False, **context}
        control = getattr(collector, "last_control", None)
        if isinstance(control, str) and control in _SAFE_CONTROLS:
            result["last_control"] = control
        source_stage = getattr(collector, "source_stage", None)
        if isinstance(source_stage, str) and source_stage in _SAFE_SOURCE_STAGES:
            result["source_stage"] = source_stage
        result["page"] = _page_diagnostic(page, collector)
        atomic_json(output / "source_failure.json", result)
    except Exception:
        # Diagnostic I/O or a closed page must not replace the original failure.
        pass


def _checkpoint(cancelled):
    if cancelled.is_set():
        raise SourceError("骑手资料下载已取消；不会继续导出")


def _plan_for_kind(plan, kind):
    city = getattr(plan, "city", None)
    agency = getattr(plan, "agency_id", None)
    if not isinstance(city, str) or not city.strip() or not isinstance(agency, str) or not re.fullmatch(r"\d{1,20}", agency):
        raise SourceError("骑手资料下载必须指定城市和物流合作商编号")
    try:
        dates = []
        for value in (getattr(plan, "start", None), getattr(plan, "end", None)):
            if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
                raise ValueError()
            dates.append(dt.date.fromisoformat(value))
        if dates[0] > dates[1]:
            raise ValueError()
        if kind == "receive_account":
            month = MonthlyBillRequest(getattr(plan, "month", None))
            return SimpleNamespace(city=city, agency_id=agency, start=month.start, end=month.end, month=month.month)
    except (TypeError, ValueError):
        raise SourceError("骑手资料下载的日期或月份无效") from None
    # RiderSourceCollector also records month for daily files; it does not use
    # that field to narrow their date range, which may span several months.
    return SimpleNamespace(city=city, agency_id=agency, start=plan.start, end=plan.end, month=plan.start[:7])


def _checked_info(info, output, plan, kind):
    if not isinstance(info, dict):
        raise SourceError("骑手资料采集未返回有效校验清单")
    if (info.get("status") not in ("validated", "empty")
            or type(info.get("rows")) is not int or info["rows"] < 0
            or (info["status"] == "empty") != (info["rows"] == 0)
            or type(info.get("bytes")) is not int or info["bytes"] <= 0
            or not isinstance(info.get("sha256"), str) or not re.fullmatch(r"[0-9a-f]{64}", info["sha256"])
            or type(info.get("team_count")) is not int or info["team_count"] < 0):
        raise SourceError("骑手资料校验清单缺少完整的行数或文件校验信息")
    name = info.get("path")
    if not isinstance(name, str) or not name or Path(name).name != name or "/" in name or "\\" in name:
        raise SourceError("骑手资料返回路径不属于本次目录")
    file = (output / name).resolve()
    if not file.is_relative_to(output) or not file.is_file() or file.suffix.lower() not in (".csv", ".xlsx"):
        raise SourceError("骑手资料文件缺失、路径越界或格式未确认")
    with file.open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    if info["bytes"] != file.stat().st_size or info["sha256"] != digest or info.get("format") != file.suffix[1:]:
        raise SourceError("骑手资料文件完整性校验失败")
    for field, expected in (("city", plan.city), ("agency_id", plan.agency_id),
                            ("requested_start", plan.start), ("requested_end", plan.end), ("requested_month", plan.month)):
        if info.get(field) != expected:
            raise SourceError("骑手资料校验清单的城市、日期或月份与请求不一致")
    if kind in ("rider_detail", "rider_info"):
        teams, agencies = info.get("selected_team_ids"), info.get("team_agency_ids")
        if (info.get("scope") != "target_city" or info.get("all_available_teams") is not False
                or not isinstance(teams, list) or not teams
                or any(not isinstance(team, str) or not re.fullmatch(r"\d{1,20}", team) for team in teams)
                or len(set(teams)) != len(teams) or not isinstance(agencies, dict)
                or set(agencies) != set(teams) or any(agency != plan.agency_id for agency in agencies.values())):
            raise SourceError("骑手资料所选站点缺少唯一目标城市归属证明")
        if info["team_count"] > len(teams):
            raise SourceError("骑手资料文件的站点数量超出所选城市范围")
    if kind == "rider_detail":
        for field in ("date_min", "date_max"):
            value = info.get(field)
            if value is None and info["rows"] > 0:
                raise SourceError("骑手明细非空文件缺少日期范围证明")
            if value is not None and (not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value)
                                      or not plan.start <= value <= plan.end):
                raise SourceError("骑手明细文件日期超出所选范围")
    elif kind == "receive_account":
        if type(info.get("query_total")) is not int or info["query_total"] != info["rows"]:
            raise SourceError("收薪账户文件行数与本月查询结果不一致")
    return file


def collect_rider_source(page, auth, plan, raw, kind, log, cancelled, reveal=None, conceal=None):
    """Collect exactly one selected raw document without creating a login or payroll task."""
    if not isinstance(kind, str) or kind not in KINDS:
        raise SourceError("独立下载仅支持骑手明细、骑手信息或收薪账户原始资料")
    _checkpoint(cancelled)
    effective = _plan_for_kind(plan, kind)
    if not callable(getattr(auth, "navigate", None)) or not callable(getattr(auth, "ensure", None)):
        raise SourceError("骑手资料下载需要当前共享浏览器的登录管理器")
    output = Path(raw).resolve()
    output.mkdir(parents=True, exist_ok=True)
    collector, stage = None, "collector_init"
    manual_wait = False

    def progress(message, *args, **kwargs):
        nonlocal manual_wait
        if isinstance(message, str) and message.startswith(("[等待验证]", "[验证未通过]", "[等待页面]")):
            manual_wait = True
        log(message, *args, **kwargs)

    def navigate(url, profile):
        nonlocal stage
        _checkpoint(cancelled)
        stage = "auth_navigation"
        auth.navigate(url)
        stage = "auth_check"
        auth.ensure(url, profile)
        stage = "collect"

    options = {"auth": navigate, "detail_target_city_only": True}
    if reveal is not None:
        options["reveal"] = reveal
    if conceal is not None:
        options["conceal"] = conceal
    try:
        collector = RiderSourceCollector(page, effective, output, progress, cancelled, **options)
        stage = "collect"
        info = collector.collect(kind)
        stage = "receipt_validation"
        _checkpoint(cancelled)
        _checked_info(info, output, effective, kind)
        result = {**info, "dataset": kind, "kind": kind, "start": effective.start, "end": effective.end,
                  "month": effective.month if kind == "receive_account" else None,
                  "scope": "target_city", "target_city_only": True,
                  "binding_generated": False, "payroll_executed": False}
        if kind == "receive_account":
            result["snapshot_only"] = True
        elif kind == "rider_info":
            result.update(snapshot_only=True, time_basis="current_snapshot")
        stage = "receipt_write"
        atomic_json(output / "source_receipt.json", result)
        if kind == "receive_account":
            log("[资料] 收薪账户按整月下载原始资料，不生成骑手支付绑定结果")
        elif kind == "rider_info":
            log("[资料] 骑手信息为当前城市人员快照，不按所选日期筛选，不生成支付绑定结果")
        return result
    except Exception as exc:
        _record_failure(output, kind, stage, exc, page, collector, manual_wait=manual_wait)
        raise


def same_day_rider_info_snapshot(roots, plan, target_dir, log=lambda *_: None,
                                 exclude_dir=None, today=None):
    """Reuse today's validated rider_info snapshot for the same city and agency.

    rider_info is an export-time snapshot of the current personnel state, so a
    file exported earlier the same day equals a fresh export and saves one SMS
    verification. Returns the rewritten receipt for the copied file, or None
    when no usable snapshot exists (the caller then exports normally).
    """
    today = today or dt.date.today()
    target = Path(target_dir).resolve()
    excluded = Path(exclude_dir).resolve() if exclude_dir is not None else None
    best = None
    for root in roots:
        try:
            base = Path(root).resolve()
            if not base.is_dir():
                continue
            receipts = list(base.rglob("source_receipt.json"))
        except OSError:
            continue
        for receipt in receipts:
            try:
                if receipt.is_symlink() or not receipt.is_file() or receipt.stat().st_size > 1024 * 1024:
                    continue
                info = json.loads(receipt.read_bytes())
                directory = receipt.parent.resolve()
            except (OSError, ValueError):
                continue
            if not isinstance(info, dict) or info.get("dataset") != "rider_info" \
                    or info.get("status") not in ("validated", "empty") \
                    or info.get("city") != plan.city \
                    or str(info.get("agency_id")) != str(plan.agency_id):
                continue
            if excluded is not None and (directory == excluded or directory.is_relative_to(excluded)):
                continue
            if not directory.is_relative_to(base):
                continue
            relative = info.get("path")
            if not isinstance(relative, str):
                continue
            relative = Path(relative)
            if relative.is_absolute() or relative.drive or ".." in relative.parts:
                continue
            candidate = receipt.parent / relative
            try:
                source = candidate.resolve()
                if candidate.is_symlink() or not source.is_file() \
                        or source.suffix.lower() not in (".csv", ".xlsx") \
                        or not source.is_relative_to(directory):
                    continue
                stat = source.stat()
                if type(info.get("rows")) is not int or info["rows"] < 0 \
                        or (info["status"] == "empty") != (info["rows"] == 0) \
                        or info.get("bytes") != stat.st_size \
                        or dt.date.fromtimestamp(stat.st_mtime) != today:
                    continue
                if info.get("sha256") != hashlib.sha256(source.read_bytes()).hexdigest():
                    continue
            except OSError:
                continue
            if best is None or stat.st_mtime > best[0]:
                best = (stat.st_mtime, base, directory, info, source)
    if best is None:
        return None
    _, base, directory, info, source = best
    try:
        target.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target / source.name)
    except OSError:
        log("[复用] 当日骑手信息快照复制失败，改为重新导出")
        return None
    exported = dt.datetime.fromtimestamp(source.stat().st_mtime).isoformat(timespec="seconds")
    receipt = {**info, "start": plan.start, "end": plan.end,
               "requested_start": plan.start, "requested_end": plan.end,
               "reused_from": f"{base.name}/{directory.relative_to(base).as_posix()}",
               "snapshot_exported_at": exported}
    atomic_json(target / "source_receipt.json", receipt)
    log(f"[复用] {plan.city} 骑手信息复用当日已校验快照（{exported} 导出，{info['rows']} 行），跳过重新导出")
    return receipt


DETAIL_COLUMNS = ("日期", "骑手ID", "骑手姓名", "骑手手机号", "团队ID", "团队名称", "所属管理分组",
                  "骑手等级", "最新入职时间", "最新离职时间", "在职状态", "入职时长", "活跃天数",
                  "有效在线时长", "午高峰有效在线时长", "晚高峰有效在线时长", "有效完成单")
_DETAIL_DATE_COLUMNS = frozenset({"日期", "最新入职时间", "最新离职时间"})
_DETAIL_DATE_VALUE = re.compile(r"(\d{4})-(\d{1,2})-(\d{1,2})")


def _detail_date(value):
    match = _DETAIL_DATE_VALUE.fullmatch(value)
    return f"{int(match[1])}/{int(match[2])}/{int(match[3])}" if match else value


def _detail_positions(header):
    if any(not name for name in header) or len(set(header)) != len(header):
        raise SourceError("骑手数据明细表头缺失或重复，未生成成品")
    index = {name: position for position, name in enumerate(header)}
    missing = [name for name in DETAIL_COLUMNS if name not in index]
    if missing:
        raise SourceError("骑手数据明细缺少约定列：" + "、".join(missing))
    return [index[name] for name in DETAIL_COLUMNS]


def _write_detail_rows(writer, header, rows, city=None):
    positions = _detail_positions(header)
    date_positions = {position for name, position in zip(DETAIL_COLUMNS, positions)
                      if name in _DETAIL_DATE_COLUMNS}
    for row in rows:
        if not row or not any(str(value).strip() for value in row):
            continue
        values = [row[position] if position < len(row) else "" for position in positions]
        projected = [_detail_date(value) if position in date_positions else value
                     for position, value in zip(positions, values)]
        writer.writerow([city] + projected if city is not None else projected)


def format_rider_detail_csv(source, target):
    """成品按业务口径保留 17 列并将日期列转为 2026/10/1；已含城市列的合并稿原样保留。"""
    with open(source, encoding="utf-8-sig", newline="") as stream:
        rows = list(csv.reader(stream))
    if not rows:
        raise SourceError("骑手数据明细为空文件，未生成成品")
    prefix = ("城市",) if rows[0][:1] == ["城市"] else ()
    with open(target, "w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(prefix + DETAIL_COLUMNS)
        _write_detail_rows(writer, rows[0], rows[1:])
    return Path(target)


def merge_rider_detail_csv(pairs, target):
    """多城市成品合并：pairs 为（城市, 已校验成品路径）顺序列表，最前加「城市」列。"""
    with open(target, "w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(("城市",) + DETAIL_COLUMNS)
        for city, path in pairs:
            with open(path, encoding="utf-8-sig", newline="") as stream:
                rows = list(csv.reader(stream))
            if not rows:
                raise SourceError(f"{city} 骑手数据明细成品为空文件，未生成合并成品")
            _write_detail_rows(writer, rows[0], rows[1:], city=city)
    return Path(target)
