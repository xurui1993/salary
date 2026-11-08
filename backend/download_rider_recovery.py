"""Recover one already submitted rider-detail export; never create a new export."""

import datetime as dt
import hashlib
import json
from pathlib import Path
import re
from types import SimpleNamespace

from download_rider_sources import _checkpoint, _checked_info, _plan_for_kind, _record_failure
from fengshen_bill import atomic_json
from parttime_source import SourceError
from rider_sources import (DETAIL_EXPORT, TEAMS_URL, RiderSourceCollector, target_teams,
                           team_agencies, unpack_detail_archive, validate_document)


EXPORT_LIST_URL = "https://aeolus.ele.me/?targetId=55404#/export-list"
_SHANGHAI = dt.timezone(dt.timedelta(hours=8))


def _ids(values, allow_empty=False):
    if (not isinstance(values, list) or (not values and not allow_empty)
            or any(not isinstance(value, str) or not re.fullmatch(r"\d{1,20}", value) for value in values)
            or len(set(values)) != len(values)):
        raise SourceError("原导出回执的站点或历史任务编号无效，不能恢复")
    return values


def _read_json(path):
    if path.is_symlink() or not path.is_file() or path.stat().st_size > 1024 * 1024:
        raise SourceError("原导出回执不存在或格式无效，不能恢复")
    try:
        raw = path.read_bytes()
        data = json.loads(raw)
    except (OSError, ValueError, UnicodeError):
        raise SourceError("原导出回执无法解析，不能恢复") from None
    if not isinstance(data, dict):
        raise SourceError("原导出回执必须是对象，不能恢复")
    return data, hashlib.sha256(raw).hexdigest()


def _submission(source_dir, plan):
    evidence, digest = _read_json(source_dir / "detail_submission.json")
    if (evidence.get("agency_id") != plan.agency_id or evidence.get("start") != plan.start
            or evidence.get("end") != plan.end or evidence.get("request_observed") is not True
            or type(evidence.get("http_status")) is not int or evidence["http_status"] != 200
            or type(evidence.get("response_code")) is not int or evidence["response_code"] != 200):
        raise SourceError("原导出未确认提交成功或城市周期不符；不会创建新的导出")
    selected = _ids(evidence.get("selected_team_ids"))
    baseline = _ids(evidence.get("existing_task_ids"), allow_empty=True)
    try:
        if not isinstance(evidence.get("submitted_at"), str):
            raise ValueError()
        submitted = dt.datetime.fromisoformat(evidence["submitted_at"])
        if submitted.tzinfo is not None:
            submitted = submitted.astimezone(_SHANGHAI).replace(tzinfo=None)
    except ValueError:
        raise SourceError("原导出提交时间无效，不能唯一恢复任务") from None
    identity = evidence.get("task_id")
    task_file = source_dir / "detail_task.json"
    task_digest = None
    if task_file.exists():
        task, task_digest = _read_json(task_file)
        if (task.get("start") != plan.start or task.get("end") != plan.end
                or set(_ids(task.get("selected_team_ids"))) != set(selected)):
            raise SourceError("原导出任务编号回执与申请范围不一致")
        if identity is not None and task.get("task_id") != identity:
            raise SourceError("原导出任务编号回执冲突，不能恢复")
        identity = task.get("task_id")
    if identity is not None:
        _ids([identity])
        if identity in baseline:
            raise SourceError("原导出任务编号属于历史基线，不能恢复")
    return selected, set(baseline), submitted, identity, digest, task_digest


def _pagination_snapshot(frame):
    result = {}
    def numeric(selector, pattern):
        try:
            locator = frame.locator(selector)
            if locator.count() != 1:
                return None
            value = locator.inner_text().strip()
            match = re.fullmatch(pattern, value) if isinstance(value, str) else None
            return int(match.group(1)) if match else None
        except Exception:
            return None
    current = numeric('.el-pagination .el-pager li.active', r'(\d{1,9})')
    total = numeric('.el-pagination .el-pagination__total', r'共\s*(\d{1,12})\s*条')
    if current is not None:
        result['current'] = current
    if total is not None:
        result['total_rows'] = total
    for key, selector in (('previous', '.el-pagination .btn-prev'), ('next', '.el-pagination .btn-next')):
        try:
            locator = frame.locator(selector)
            count = locator.count()
            if type(count) is int and count >= 0:
                result[key + '_button_count'] = count
            if count == 1:
                disabled = locator.is_disabled()
                if type(disabled) is bool:
                    result[key + '_disabled'] = disabled
        except Exception:
            pass
    try:
        size = frame.locator('.el-pagination .el-pagination__sizes input')
        value = size.input_value().strip() if size.count() == 1 else None
        match = re.fullmatch(r'(\d{1,6})\s*(?:条/页)?', value) if isinstance(value, str) else None
        if match and int(match.group(1)) > 0:
            result['page_size'] = int(match.group(1))
            if total is not None:
                result['page_count'] = (total + result['page_size'] - 1) // result['page_size']
    except Exception:
        pass
    return result


def _row_snapshot(row, collector, prefix):
    # Parse only task metadata, never retain table text, file URLs or operator names.
    text = row.inner_text()
    compact = re.sub(r'\s+', '', text) if isinstance(text, str) else ''
    marker = '骑手数据明细' in compact
    wide_id = re.search(r'骑手数据明细[._()（）\-]+(\d{1,20})(?=[._()（）\-]|$)', compact)
    strict = re.search(prefix + r'(\d+)\.', compact)
    identity = wide_id.group(1) if wide_id else None
    interval = re.search(r'(?<!\d)(\d{4}-\d{2}-\d{2})[-_~至](\d{4}-\d{2}-\d{2})(?!\d)', compact) if marker else None
    first = last = None
    if interval:
        try:
            first, last = (dt.date.fromisoformat(value).isoformat() for value in interval.groups())
        except ValueError:
            first = last = None
    created = None
    if marker:
        try:
            value = row.locator('td').nth(2).inner_text().strip()
            if isinstance(value, str) and re.fullmatch(r'\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}', value):
                created = dt.datetime.strptime(value, '%Y-%m-%d %H:%M:%S')
        except Exception:
            pass
    state = ('failed' if '失败' in compact else 'completed' if any(value in compact for value in ('导出完成', '导出成功'))
             else 'processing' if any(value in compact for value in ('整理中', '导出中', '处理中', '生成中'))
             else 'queued' if any(value in compact for value in ('排队中', '等待中', '待处理', '待导出')) else 'unknown')
    visible = row.is_visible()
    in_window = bool(created and collector.detail_submitted_at - dt.timedelta(seconds=10) <= created
                     <= collector.detail_submitted_at + dt.timedelta(minutes=5))
    strict_id = strict.group(1) if strict else None
    baseline = identity in collector.detail_baseline if identity else False
    eligible = bool(strict_id and visible and strict_id not in collector.detail_baseline and in_window
                    and (not collector.detail_task or strict_id == collector.detail_task))
    return ({'rider_detail_marker': marker, 'task_id': identity, 'start': first, 'end': last,
             'created_at': created.isoformat() if created else None, 'status': state,
             'visible': bool(visible), 'baseline': baseline, 'in_window': in_window,
             'strict_name_match': bool(strict), 'eligible': eligible}, created, strict_id)


class _RecoveryCollector(RiderSourceCollector):
    def _detail_list_frame(self):
        frame = super()._detail_list_frame()
        prefix = re.escape(f"{self.plan.start}-{self.plan.end}.骑手数据明细.")
        rows = frame.locator('tbody tr').all()
        eligible, snapshots, fatal = [], [], None
        detail_count = strict_count = 0
        for row in rows:
            entry, created, identity = _row_snapshot(row, self, prefix)
            detail_count += entry['rider_detail_marker']
            strict_count += entry['strict_name_match']
            if len(snapshots) < 100:
                snapshots.append(entry)
            candidate = bool(identity and entry['visible'] and identity not in self.detail_baseline
                             and (not self.detail_task or identity == self.detail_task))
            if candidate and created is None:
                fatal = SourceError('候选导出任务创建时间无法核对，不下载其他记录')
            elif candidate and not entry['in_window'] and self.detail_task:
                fatal = SourceError('原任务编号的创建时间与本次提交不一致')
            if entry['eligible']:
                eligible.append(row)
                self.recovery_matched_at = created.isoformat()
        snapshot = {'observed_at': dt.datetime.now(_SHANGHAI).isoformat(), 'current_dom_only': True,
                    'observed_rows': len(rows), 'rider_detail_rows': detail_count, 'strict_name_matches': strict_count,
                    'nonmatching_rows': len(rows) - strict_count, 'eligible_count': len(eligible),
                    'truncated': len(rows) > 100, 'rows': snapshots, 'pagination': _pagination_snapshot(frame),
                    'resubmitted': False}
        try:
            atomic_json(self.output_dir / 'detail_list_snapshot.json', snapshot)
        except Exception:
            pass
        if not getattr(self, '_recovery_snapshot_logged', False):
            self.log(f'[恢复列表] 当前页 {len(rows)} 行，明细 {detail_count} 行，严格名称匹配 {strict_count} 行，合格候选 {len(eligible)} 个；未翻页、不会重新导出')
            self._recovery_snapshot_logged = True
        if fatal is not None:
            raise fatal
        if len(eligible) > 1:
            raise SourceError("本次提交时间窗口内存在多个候选任务，不猜测也不重新导出")
        return SimpleNamespace(url=frame.url, locator=lambda selector: SimpleNamespace(all=lambda: eligible)
                               if selector == "tbody tr" else frame.locator(selector))


def recover_rider_detail(page, auth, plan, raw, source_dir, log, cancelled, reveal=None, conceal=None):
    """Read a prior export receipt and download its unique existing task only."""
    _checkpoint(cancelled)
    effective = _plan_for_kind(plan, "rider_detail")
    selected, baseline, submitted, identity, submission_hash, task_hash = _submission(Path(source_dir).resolve(), effective)
    output = Path(raw).resolve()
    output.mkdir(parents=True, exist_ok=True)
    context = page.context
    downloads, rejection, watched = [], [], []
    collector, stage = None, "recovery_init"
    recovery = {"mode": "existing_export_only", "status": "running", "agency_id": effective.agency_id,
                "start": effective.start, "end": effective.end, "submitted_at": submitted.isoformat(),
                "source_submission_sha256": submission_hash, "source_task_sha256": task_hash,
                "selected_team_ids": sorted(selected), "resubmitted": False,
                "binding_generated": False, "payroll_executed": False}

    def block_export(route):
        rejection.append("恢复期间已阻止创建导出请求；不会重新提交")
        route.abort()

    def downloaded(download):
        downloads.append(download)

    def watch(current):
        if any(current is existing for existing in watched):
            return
        current.on("download", downloaded)
        watched.append(current)

    pattern = DETAIL_EXPORT + "*"
    context.route(pattern, block_export)
    try:
        atomic_json(output / "recovery.json", recovery)
        options = {"detail_target_city_only": True}
        if reveal is not None:
            options["reveal"] = reveal
        if conceal is not None:
            options["conceal"] = conceal
        collector = _RecoveryCollector(page, effective, output, log, cancelled, **options)
        collector.page_url = EXPORT_LIST_URL
        collector.detail_acknowledged = True
        collector.detail_task = identity
        collector.detail_baseline = baseline
        collector.detail_submitted_at = submitted
        collector.detail_selected_teams = {value: "" for value in selected}
        for current in context.pages:
            watch(current)
        context.on("page", watch)
        stage = "recovery_navigation"
        auth.navigate(EXPORT_LIST_URL)
        auth.ensure(EXPORT_LIST_URL, collector.profile)
        _checkpoint(cancelled)
        if rejection:
            raise SourceError(rejection[0])
        stage = "recovery_city"
        collector._check_agency_context()
        stage = "recovery_teams"
        response = context.request.post(TEAMS_URL, data={}, timeout=30000)
        try:
            if not response.ok:
                raise SourceError("恢复任务的站点归属查询失败，不下载未知城市资料")
            payload = response.json()
            agencies = team_agencies(payload)
            names = target_teams(payload, effective.agency_id)
        finally:
            if callable(getattr(response, "dispose", None)):
                try:
                    response.dispose()
                except Exception:
                    pass
        if any(agencies.get(value) != effective.agency_id or value not in names for value in selected):
            raise SourceError("原任务所选站点包含其他城市或未知归属，停止恢复")
        teams = {value: names[value] for value in selected}
        collector.detail_selected_teams = teams
        stage = "recovery_poll_existing"
        if downloads:
            raise SourceError("恢复列表关联前出现其他下载事件，未使用未知文件")
        collector._poll_detail_task(downloads, rejection)
        _checkpoint(cancelled)
        if rejection or len(downloads) != 1:
            raise SourceError("恢复下载事件不唯一或发生禁止的导出请求")
        if (not isinstance(collector.detail_task, str) or not re.fullmatch(r"\d{1,20}", collector.detail_task)
                or collector.detail_task in baseline or not getattr(collector, "recovery_matched_at", None)):
            raise SourceError("下载文件未关联本次提交的唯一平台任务")
        download = downloads[0]
        if download.failure():
            raise SourceError("原导出任务文件下载失败，未创建新任务")
        extension = Path(download.suggested_filename).suffix.lower()
        if extension not in (".csv", ".xlsx", ".zip"):
            raise SourceError("原导出任务返回未确认的文件格式")
        path = output / f"骑手数据明细_{effective.city}_{effective.start}_{effective.end}_recovered{extension}"
        log("[下载] 已关联原任务文件，正在保存原件；未重新提交导出")
        stage = "recovery_save_file"
        download.save_as(path)
        log("[校验] 正在核对原任务文件的城市、日期和完整性")
        stage = "recovery_validate_file"
        if extension == ".zip":
            path, info = unpack_detail_archive(path, effective, teams)
        else:
            info = validate_document(path, "rider_detail", effective, teams)
        info.update(city=effective.city, agency_id=effective.agency_id, requested_start=effective.start,
                    requested_end=effective.end, requested_month=effective.month, scope="target_city",
                    all_available_teams=False, all_target_teams=set(teams) == set(names),
                    selected_team_ids=sorted(teams), team_agency_ids={value: agencies[value] for value in teams},
                    task_id=collector.detail_task, export_mode="daily", dataset="rider_detail", kind="rider_detail",
                    start=effective.start, end=effective.end, month=None, target_city_only=True,
                    binding_generated=False, payroll_executed=False)
        _checked_info(info, output, effective, "rider_detail")
        _checkpoint(cancelled)
        recovery.update(status="success", task_id=collector.detail_task,
                        matched_task_created_at=getattr(collector, "recovery_matched_at", None),
                        blocked_export_requests=len(rejection))
        info["recovery"] = recovery
        atomic_json(output / "detail_task.json", {**recovery, "existing_task_recovered": True})
        atomic_json(output / "source_receipt.json", info)
        atomic_json(output / "recovery.json", recovery)
        return info
    except Exception as exc:
        _record_failure(output, "rider_detail", stage, exc, page, collector)
        try:
            atomic_json(output / "recovery.json", {**recovery, "status": "error", "stage": stage,
                                                  "blocked_export_requests": len(rejection)})
        except Exception:
            pass
        raise
    finally:
        try:
            context.unroute(pattern, block_export)
        except Exception:
            pass
        try:
            context.remove_listener("page", watch)
        except Exception:
            pass
        for current in watched:
            try:
                current.remove_listener("download", downloaded)
            except Exception:
                pass
