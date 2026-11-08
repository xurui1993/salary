"""Owner-isolated jobs: serial collection, bounded cooperative local handoff."""

import atexit
import calendar
from contextlib import contextmanager
import datetime as dt
import hashlib
import hashlib_compat
import json
import math
import os
from pathlib import Path
import queue
import re
import sqlite3
import threading
import time
import uuid
import tempfile
from types import SimpleNamespace
import zipfile

from collection_errors import CollectionFailure
from download_archive import ARCHIVE_VERSION, archive_component, archive_relative_dir, write_download_summary, task_archive_label, delivery_folder_label, write_task_checklist
from download_single_instance import InstanceLock


ROOT = Path(__file__).resolve().parent.parent
ACTIVE_STATUSES = frozenset({"queued", "running", "waiting_login", "cancelling"})
FINAL_STATUSES = frozenset({"cancelled", "success", "partial", "error", "interrupted"})
ITEM_STATUSES = frozenset({"queued", "running", "waiting_login", "success", "error", "cancelled", "interrupted"})
PHASES = frozenset({"queued", "waiting_collection", "waiting_login", "waiting_manual", "preparing", "submitting",
                    "waiting_export", "downloading", "validating", "generating", "publishing", "summarizing",
                    "completed", "failed", "cancelled", "interrupted"})
FAILURE_MESSAGE = "下载任务执行失败，请检查安全诊断后重试"
_PRIVATE_TEXT = re.compile(
    r"https?://|wss?://|\bBearer\s+|"
    r"\b(?:access[_-]?token|refresh[_-]?token|token|cookie|authorization|password|secret|"
    r"sms[_-]?code)\s*[=:]|"
    r"(?:手机号|手机号码|验证码|身份证(?:号)?)\s*[=:]\s*\S+|"
    r"(?<!\d)1[3-9]\d{9}(?!\d)|(?<!\d)\d{17}[\dXx](?!\d)",
    re.IGNORECASE,
)


class DownloadNotFound(LookupError):
    pass


class DownloadManagerClosed(RuntimeError):
    pass


class DownloadResumeError(RuntimeError):
    """A fixed, public reason that an existing export cannot be resumed safely."""


class DownloadRootError(ValueError):
    pass


class DownloadArchiveError(RuntimeError):
    pass


class DownloadSummaryError(RuntimeError):
    pass


class DownloadSummaryPending(RuntimeError):
    pass


class DownloadRequestConflict(ValueError):
    pass


def _fingerprint(config):
    public = {key: config[key] for key in ("cities", "datasets", "start", "end", "months")}
    public["cities"] = sorted(public["cities"])
    # Manifests record follow-up dependencies expanded; normalize both sides so
    # a committed checkpoint can be restored against the original selection.
    from download_service import expand_followup_datasets
    public["datasets"] = sorted(expand_followup_datasets(public["datasets"]))
    if config.get("refresh_history"):
        public["refresh_history"] = True
    if config.get("include_separation"):
        public["include_separation"] = True
    if 'exclude_separation' in config:
        public['exclude_separation'] = config['exclude_separation']
    if config.get('lanorange_by_city'): public['lanorange_by_city'] = True
    if config.get('lanorange_full_delivery'): public['lanorange_full_delivery'] = True
    if config.get('lanorange_months'): public['lanorange_months'] = sorted(config['lanorange_months'])
    if config.get('merchant_by_city'): public['merchant_by_city'] = True
    if config.get('payroll_agencies'): public['payroll_agencies'] = config['payroll_agencies']
    for key in ("resume_detail_from", "retry_of", "retry_items"):
        if key in config:
            public[key] = config[key]
    for key in ('task_kind', 'generation_target', 'parent_batch_id', 'parent_workspace'):
        if key in config:
            public[key] = config[key]
    return hashlib.sha256(json.dumps(public, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def configured_output_root():
    value = os.environ.get("FENGSHEN_DOWNLOAD_ROOT", "").strip()
    if not value:
        return (ROOT / "outputs" / "fengshen_downloads").resolve()
    try:
        path = Path(value)
        if not path.is_absolute():
            raise ValueError()
        return path.resolve()
    except (OSError, ValueError, RuntimeError):
        raise DownloadRootError("FENGSHEN_DOWNLOAD_ROOT 必须是有效的绝对目录路径，请修正配置后重启服务") from None


def _configured_cities():
    from download_service import cities
    return cities()


def _now():
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


def _safe_text(value, fallback=FAILURE_MESSAGE):
    if isinstance(value, CollectionFailure):
        value = value.message
    if not isinstance(value, str) or not value.strip() or _PRIVATE_TEXT.search(value):
        return fallback
    return value[:2000]


def _safe_exception(exc):
    if isinstance(exc, CollectionFailure):
        return _safe_text(exc.message)
    name = type(exc).__name__
    if (isinstance(name, str) and re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,80}", name)
            and not _PRIVATE_TEXT.search(name)):
        return FAILURE_MESSAGE + "（内部诊断：" + name + "）"
    return FAILURE_MESSAGE


def _key(item):
    return tuple(item.get(field, "") for field in ("city", "dataset", "start", "end"))


def _add_log(run, message):
    run["logs"].append({"time": _now(), "message": _safe_text(message, "部分诊断信息已隐藏")})
    run["logs"] = run["logs"][-500:]


def _refresh(run):
    statuses = [item["status"] for item in run["items"]]
    success, errors = statuses.count("success"), statuses.count("error")
    completed = sum(status in FINAL_STATUSES for status in statuses)
    run["summary"] = {"total": len(statuses), "completed": completed, "success": success,
                      "error": errors, "cancelled": statuses.count("cancelled"), "files": len(run["files"])}
    progress = round(completed * 100 / len(statuses)) if statuses else 0
    # 资料项全部结束后仍需合并多城市汇总，不能提前显示 100%。
    detail = run.get("summary_progress")
    if isinstance(detail, dict):
        stage = detail.get("stage")
        if stage == "completed":
            progress = 100
        elif stage in ("merging", "failed"):
            total, current = detail.get("total"), detail.get("current")
            valid = (type(total) is int and type(current) is int and total > 0)
            ratio = min(1.0, max(0.0, current / total)) if valid else 0
            progress = 99 if stage == "failed" else min(99, 90 + round(9 * ratio))
    run["progress"] = progress


def _without_private(value):
    if isinstance(value, dict):
        return {key: _without_private(item) for key, item in value.items() if not key.startswith("_")}
    if isinstance(value, list):
        return [_without_private(item) for item in value]
    return value


def _public(run):
    result = _without_private(json.loads(json.dumps(run, ensure_ascii=False)))
    result["files"] = [{key: value for key, value in entry.items() if key not in ("relative_path", "sha256")}
                       for entry in result["files"]]
    return result


def _initial_items(config):
    from lanorange_catalog import DATASETS as blue, ALL_CITIES, city_scoped
    from download_service import expand_followup_datasets, GENERATOR_DEPENDENCIES
    datasets = expand_followup_datasets(config['datasets'])
    items = [{'city': ALL_CITIES, 'dataset': kind, 'start': config['start'], 'end': config['end'],
              'status': 'queued', 'phase': 'queued', 'error': '', 'submission_state': 'not_submitted'}
             for kind in datasets if kind in blue and not city_scoped(config, kind)]
    if 'abnormal_riders' in datasets:
        # 异常骑手整理按「全部城市」生成一份工作簿，不进入按城市子项。
        items.append({'city': ALL_CITIES, 'dataset': 'abnormal_riders',
                      'start': config['start'], 'end': config['end'],
                      'status': 'queued', 'phase': 'queued', 'error': '',
                      'submission_state': 'not_submitted'})
    for city in config["cities"]:
        for dataset in datasets:
            if dataset in blue and not city_scoped(config, dataset): continue
            if dataset == 'abnormal_riders': continue
            periods = [(config["start"], config["end"])]
            if dataset in ("rider_monthly", "receive_account"):
                periods = []
                for month in config["months"]:
                    first = dt.date.fromisoformat(month + "-01")
                    last = first.replace(day=calendar.monthrange(first.year, first.month)[1])
                    periods.append((first.isoformat(), last.isoformat()))
            elif dataset in ('payment_binding', 'abnormal_followup'):
                from binding_download import month_periods
                periods = [(first, last) for _, first, last in month_periods(config['start'], config['end'])]
            for start, end in periods:
                items.append({"city": city, "dataset": dataset, "start": start, "end": end,
                              "status": "queued", "phase": "queued", "error": "", "submission_state": "not_submitted"})
    if config.get("retry_items"):
        allowed = {_key(item) for item in config["retry_items"]}
        keep = [item for item in items if _key(item) in allowed]
        # 生成表重试时自动补回来源资料，与执行清单保持一致。
        chosen = {_key(item) for item in keep}
        for generator, dependencies in GENERATOR_DEPENDENCIES.items():
            if any(item['dataset'] == generator for item in keep):
                keep.extend(item for item in items
                            if item['dataset'] in dependencies and _key(item) not in chosen)
                chosen = {_key(item) for item in keep}
        items = keep
    return items


def delivery_scope_error(info, config, suffix):
    # 发布（download_service.publish）与注册校验（_file_entry）共用的范围/周期口径；
    # 新增伪城市或汇总件只需改这里，两侧同步生效。
    from lanorange_catalog import DATASETS as blue, ALL_CITIES
    from download_service import expand_followup_datasets
    is_summary = info.get('artifact_role') == 'summary'
    suffix = suffix.lower()
    summary_scope = (is_summary and info.get('city') == '多城市汇总' and info.get('dataset') == 'payment_binding'
                     and 'payment_binding' in config['datasets'] and len(config['cities']) > 1
                     and suffix == '.xlsx'
                     and any(item['dataset'] == 'payment_binding' and item['start'] == info.get('start')
                             and item['end'] == info.get('end') for item in _initial_items(config)))
    summary_scope = summary_scope or (is_summary and info.get('city') == '多城市汇总'
                     and info.get('dataset') == 'abnormal_followup'
                     and 'abnormal_followup' in config['datasets'] and len(config['cities']) > 1
                     and suffix == '.xlsx'
                     and any(item['dataset'] == 'abnormal_followup' and item['start'] == info.get('start')
                             and item['end'] == info.get('end') for item in _initial_items(config)))
    summary_scope = summary_scope or (is_summary and info.get('city') == '多城市汇总'
                     and info.get('dataset') == 'rider_monthly'
                     and 'rider_monthly' in config['datasets'] and len(config['cities']) > 1
                     and suffix == '.xlsx'
                     and any(item['dataset'] == 'rider_monthly' and item['start'] == info.get('start')
                             and item['end'] == info.get('end') for item in _initial_items(config)))
    summary_scope = summary_scope or (is_summary and info.get('city') == '多城市汇总'
                     and config.get('lanorange_by_city') and info.get('dataset') == 'lanorange_summary'
                     and any(kind in blue for kind in config['datasets']) and len(config['cities']) > 1
                     and suffix == '.xlsx' and info.get('start') == config['start'] and info.get('end') == config['end'])
    summary_scope = summary_scope or (is_summary and info.get('city') == '多城市'
                     and info.get('dataset') == 'invitation_summary'
                     and 'invitation_records' in config['datasets'] and len(config['cities']) > 1
                     and suffix == '.xlsx' and info.get('start') == config['start'] and info.get('end') == config['end'])
    allowed_datasets = set(expand_followup_datasets(config['datasets']))
    global_scope = not is_summary and info.get('city') == ALL_CITIES and info.get('dataset') in blue and info.get('dataset') in allowed_datasets
    merged_scope = (not is_summary and info.get('city') == '多城市' and info.get('dataset') == 'rider_detail'
                    and 'rider_detail' in allowed_datasets and len(config['cities']) > 1
                    and suffix == '.csv'
                    and info.get('start') == config['start'] and info.get('end') == config['end'])
    merged_scope = merged_scope or (not is_summary and info.get('city') == '多城市'
                    and info.get('dataset') == 'delivery_waybill'
                    and 'delivery_waybill' in allowed_datasets and len(config['cities']) > 1
                    and suffix == '.xlsx'
                    and info.get('start') == config['start'] and info.get('end') == config['end'])
    if not summary_scope and not merged_scope and not global_scope and (is_summary or info.get("city") not in config["cities"] or info.get("dataset") not in allowed_datasets):
        return "下载文件范围无效"
    if not summary_scope and not merged_scope and _key(info) not in {_key(item) for item in _initial_items(config)}:
        return "下载文件周期无效"
    return None


def _default_executor(config, run_dir, log, cancelled, update_item):
    # Importing the routes or listing historical jobs must not load a browser.
    from download_service import execute_downloads
    return execute_downloads(config, run_dir, log, cancelled, update_item)


class DownloadManager:
    def __init__(self, db_path, output_root, executor_fn=None, flat_delivery=True):
        self.db_path = Path(db_path)
        self.output_root = Path(output_root).resolve()
        self.flat_delivery = flat_delivery
        self.workspace_root = self.db_path.parent.resolve() / 'workspaces' / 'downloads'
        from delivery_store import DeliveryStore
        self.deliveries = DeliveryStore(self.db_path.parent / 'deliveries.sqlite3',self.output_root)
        self.executor_fn = executor_fn or _default_executor
        self._lock = threading.RLock()
        self._queue = queue.Queue()
        self._inflight = threading.BoundedSemaphore(2)
        self._local_gate = threading.Lock()
        self._processing_threads = set()
        self._collection_released = set()
        self._events = {}
        self._closed = False
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.output_root.mkdir(parents=True, exist_ok=True)
        self._instance_lock = InstanceLock(self.db_path.with_suffix(".worker.lock"))
        try:
            interrupted = self._initialize()
            from download_path_registry import refresh_protected_roots
            refresh_protected_roots(self.db_path, self.output_root)
        except BaseException:
            self._instance_lock.release()
            raise
        for owner, run_id in interrupted:
            self._summary_best_effort(owner, run_id)
        self._thread = threading.Thread(target=self._worker, name="fengshen-download-worker", daemon=True)
        self._thread.start()

    @contextmanager
    def _connection(self):
        connection = sqlite3.connect(str(self.db_path), timeout=15)
        connection.row_factory = sqlite3.Row
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def _initialize(self):
        interrupted = []
        with self._connection() as connection:
            connection.execute("PRAGMA journal_mode=WAL")
            connection.execute("""CREATE TABLE IF NOT EXISTS download_runs (
                id TEXT PRIMARY KEY, owner TEXT NOT NULL, created_at TEXT NOT NULL,
                status TEXT NOT NULL, config_json TEXT NOT NULL, state_json TEXT NOT NULL
            )""")
            connection.execute("CREATE INDEX IF NOT EXISTS download_runs_owner ON download_runs(owner, created_at)")
            connection.execute("""CREATE TABLE IF NOT EXISTS download_requests (
                owner TEXT NOT NULL, request_id TEXT NOT NULL, config_hash TEXT NOT NULL,
                run_id TEXT NOT NULL, PRIMARY KEY(owner, request_id))""")
            connection.execute("""CREATE TABLE IF NOT EXISTS download_recovery_heads (
                origin_id TEXT NOT NULL, city TEXT NOT NULL, dataset TEXT NOT NULL, start TEXT NOT NULL, end TEXT NOT NULL,
                run_id TEXT NOT NULL, PRIMARY KEY(origin_id, city, dataset, start, end))""")
            historical = connection.execute("SELECT state_json,config_json FROM download_runs ORDER BY rowid").fetchall()
            for previous in historical:
                previous_config = json.loads(previous["config_json"])
                if previous_config.get("retry_of") or previous_config.get("resume_detail_from"):
                    self._record_recovery_heads(connection, json.loads(previous["state_json"]), previous_config)
            rows = connection.execute("SELECT id, owner, config_json, state_json FROM download_runs WHERE status IN (?, ?, ?, ?)",
                                      tuple(sorted(ACTIVE_STATUSES))).fetchall()
            for row in rows:
                run = json.loads(row["state_json"])
                self._restore_checkpoint(run, json.loads(row["config_json"]))
                run["status"] = "interrupted"
                run["error"] = "服务已重启，任务中断；已完成文件保留，请按各失败项的恢复提示处理"
                run.update(phase="interrupted", phase_since=_now())
                for item in run["items"]:
                    if item["status"] not in ("success", "error", "cancelled"):
                        item.update(status="interrupted", phase="interrupted", error=run["error"],
                                    submission_state="not_submitted" if item["status"] == "queued" else item.get("submission_state", "unknown"))
                _add_log(run, run["error"])
                _refresh(run)
                self._save(connection, run)
                interrupted.append((row["owner"], row["id"]))
        return interrupted

    @staticmethod
    def _save(connection, run):
        connection.execute("UPDATE download_runs SET status = ?, state_json = ? WHERE id = ?",
                           (run["status"], json.dumps(run, ensure_ascii=False), run["id"]))

    @staticmethod
    def _find(connection, owner, run_id):
        row = connection.execute("SELECT * FROM download_runs WHERE id = ? AND owner = ?", (run_id, owner)).fetchone()
        if row is None:
            raise DownloadNotFound("下载任务不存在")
        return row, json.loads(row["state_json"])

    def create(self, owner, config, request_id=None):
        return self._create(owner, config, request_id=request_id)

    def _create(self, owner, config, recovery_of=None, resume_detail_source_dir=None,
                request_id=None, retry_items=None, resume_detail_sources=None, resume_daily_sources=None,
                resume_order_sources=None, resume_waybill_sources=None, retry_of=None, resume_binding_materials=None,
                resume_lanorange_sources=None,resume_merchant_sources=None):
        # Keep credentials and client-supplied ownership outside durable config.
        refresh_history = config.get("refresh_history") is True
        lanorange_by_city = config.get('lanorange_by_city') is True
        lanorange_full_delivery = config.get('lanorange_full_delivery') is True
        merchant_by_city = config.get('merchant_by_city') is True
        business_intent = {key: config[key] for key in ('task_kind', 'generation_target', 'parent_batch_id', 'parent_workspace') if key in config}
        if config.get('include_separation') is True: business_intent['include_separation'] = True
        if 'exclude_separation' in config: business_intent['exclude_separation'] = config['exclude_separation']
        if config.get('payroll_agencies'): business_intent['payroll_agencies'] = config['payroll_agencies']
        if config.get('task_kind')=='payroll_source' and config.get('payroll_unified'):
            business_intent.update(payroll_unified=True,payroll_scope_mode=config.get('payroll_scope_mode','legacy'),payroll_scope_agencies=config.get('payroll_scope_agencies',[]))
        config = json.loads(json.dumps({key: config[key] for key in ("cities", "datasets", "start", "end", "months", "lanorange_months")
                                       if key in config}, ensure_ascii=False))
        config.update(business_intent)
        if refresh_history:
            config["refresh_history"] = True
        if lanorange_by_city: config['lanorange_by_city'] = True
        if lanorange_full_delivery: config['lanorange_full_delivery'] = True
        if merchant_by_city: config['merchant_by_city'] = True
        if recovery_of is not None:
            config["resume_detail_from"] = recovery_of
            if resume_detail_source_dir is not None:
                config["resume_detail_source_dir"] = str(resume_detail_source_dir)
        if retry_items is not None:
            config["retry_items"] = sorted(retry_items, key=_key)
        if retry_of is not None:
            config["retry_of"] = retry_of
        if resume_detail_sources:
            config["resume_detail_sources"] = {city: str(path) for city, path in resume_detail_sources.items()}
        if resume_daily_sources:
            config["resume_daily_sources"] = {city: str(path) for city, path in resume_daily_sources.items()}
        if resume_order_sources:
            config["resume_order_sources"] = {city: str(path) for city, path in resume_order_sources.items()}
        if resume_waybill_sources:
            config["resume_waybill_sources"] = {city: str(path) for city, path in resume_waybill_sources.items()}
        if resume_binding_materials:
            config['resume_binding_materials'] = resume_binding_materials
        if resume_lanorange_sources:
            config['resume_lanorange_sources'] = {key: str(value) for key, value in resume_lanorange_sources.items()}
        if resume_merchant_sources:config['resume_merchant_sources']={key:str(value) for key,value in resume_merchant_sources.items()}
        if request_id is not None and (not isinstance(request_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]{8,128}", request_id)):
            raise DownloadRequestConflict("提交标识无效，请刷新页面后重试")
        fingerprint = _fingerprint(config)
        with self._lock:
            if self._closed:
                raise DownloadManagerClosed("下载服务已停止")
            created_at = _now()
            with self._connection() as connection:
                if request_id is not None:
                    previous = connection.execute("SELECT config_hash, run_id FROM download_requests WHERE owner=? AND request_id=?",
                                                   (owner, request_id)).fetchone()
                    if previous:
                        if previous["config_hash"] != fingerprint:
                            raise DownloadRequestConflict("同一次提交的参数已改变，请先查看原任务，再明确创建新任务")
                        _, existing_run = self._find(connection, owner, previous["run_id"])
                        return self._public_run(connection, existing_run)
                    active = connection.execute("SELECT config_json,state_json FROM download_runs WHERE owner=? AND status IN (?,?,?,?) ORDER BY rowid",
                                                (owner, *sorted(ACTIVE_STATUSES))).fetchall()
                    for candidate in active:
                        if _fingerprint(json.loads(candidate["config_json"])) == fingerprint:
                            existing_run = json.loads(candidate["state_json"])
                            connection.execute("INSERT INTO download_requests VALUES(?,?,?,?)",
                                               (owner, request_id, fingerprint, existing_run["id"]))
                            return self._public_run(connection, existing_run)
                registered = [json.loads(row["state_json"]) for row in connection.execute(
                    "SELECT state_json FROM download_runs WHERE created_at = ?", (created_at,)).fetchall()]
                for _ in range(32):
                    run_id = uuid.uuid4().hex
                    label = task_archive_label(config['datasets'])
                    relative = archive_relative_dir(run_id, created_at, config["cities"], label)
                    archive_root = self.workspace_root if self.flat_delivery else self.output_root
                    target = archive_root / relative
                    registered_collision = any(
                        state.get("archive_version") == ARCHIVE_VERSION
                        and Path(state.get("_archive_root", "")).resolve() == archive_root
                        and Path(state.get("archive_relative_dir", "")) == Path(relative)
                        for state in registered)
                    if (not registered_collision and not target.exists() and not target.is_symlink()
                            and connection.execute("SELECT 1 FROM download_runs WHERE id = ?", (run_id,)).fetchone() is None):
                        break
                else:
                    raise DownloadArchiveError("无法分配唯一归档目录，请稍后重试；已有任务未改变")
                run = {"id": run_id, "status": "queued", "created_at": created_at,
                       **{key: config[key] for key in ('task_kind', 'generation_target', 'parent_batch_id', 'parent_workspace') if key in config},
                       **{key: config[key] for key in ('include_separation', 'exclude_separation') if key in config},
                       **({'lanorange_by_city': True} if config.get('lanorange_by_city') else {}),
                       **({'lanorange_full_delivery': True} if config.get('lanorange_full_delivery') else {}),
                       **({'lanorange_months': list(config['lanorange_months'])} if config.get('lanorange_months') else {}),
                       **({'merchant_by_city': True} if config.get('merchant_by_city') else {}),
                       "start": config["start"], "end": config["end"], "cities": config["cities"],
                       "datasets": config["datasets"], "progress": 0, "summary": {}, "error": "",
                       "logs": [], "items": _initial_items(config), "files": [],
                       "phase": "queued", "phase_since": created_at, "last_activity_at": created_at,
                       "_archive_root": str(archive_root), "archive_version": ARCHIVE_VERSION,
                       "archive_relative_dir": relative, "archive_code": run_id[:6].upper(),
                       "archive_label": label, "result_layout": 3 if self.flat_delivery else 2}
                if recovery_of is not None:
                    run["recovery_of"] = recovery_of
                if retry_of is not None:
                    run["retry_of"] = retry_of
                if refresh_history:
                    run["refresh_history"] = True
                _add_log(run, "已排队恢复原骑手明细导出，仅查询和下载原任务，不重新提交导出"
                         if recovery_of is not None else "下载任务已排队，离开页面后仍会继续执行")
                _refresh(run)
                connection.execute("INSERT INTO download_runs(id, owner, created_at, status, config_json, state_json) VALUES (?, ?, ?, ?, ?, ?)",
                                   (run_id, owner, run["created_at"], run["status"], json.dumps(config, ensure_ascii=False),
                                    json.dumps(run, ensure_ascii=False)))
                if request_id is not None:
                    connection.execute("INSERT INTO download_requests VALUES(?,?,?,?)", (owner, request_id, fingerprint, run_id))
                self._record_recovery_heads(connection, run, config)
            self._events[run_id] = threading.Event()
            self._queue.put(run_id)
        return _public(run)

    @staticmethod
    def _origin_id(connection, run_id):
        visited = set()
        for _ in range(64):
            if run_id in visited:
                raise DownloadResumeError("恢复任务关联出现循环，已停止继续提交")
            visited.add(run_id)
            row = connection.execute("SELECT config_json FROM download_runs WHERE id=?", (run_id,)).fetchone()
            if row is None:
                raise DownloadResumeError("恢复来源记录缺失，请核对原平台任务")
            config = json.loads(row["config_json"])
            parent = config.get("retry_of") or config.get("resume_detail_from")
            if not parent:
                return run_id
            run_id = parent
        raise DownloadResumeError("恢复关联过长，请由管理员核对原任务")

    def _record_recovery_heads(self, connection, run, config):
        if not (config.get("retry_of") or config.get("resume_detail_from")):
            return
        origin = self._origin_id(connection, run["id"])
        for item in run["items"]:
            connection.execute("INSERT INTO download_recovery_heads VALUES(?,?,?,?,?,?) "
                               "ON CONFLICT(origin_id,city,dataset,start,end) DO UPDATE SET run_id=excluded.run_id",
                               (origin, *_key(item), run["id"]))

    def _effective_attempt(self, connection, run, config, item):
        origin = self._origin_id(connection, run["id"])
        head = connection.execute("SELECT run_id FROM download_recovery_heads WHERE origin_id=? AND city=? AND dataset=? AND start=? AND end=?",
                                  (origin, *_key(item))).fetchone()
        if not head or head["run_id"] == run["id"]:
            return run, config, item
        row = connection.execute("SELECT state_json,config_json FROM download_runs WHERE id=?", (head["run_id"],)).fetchone()
        if row is None or self._origin_id(connection, head["run_id"]) != origin:
            raise DownloadResumeError("后续恢复记录不完整，请核对平台原任务")
        latest = json.loads(row["state_json"])
        target = next((value for value in latest["items"] if _key(value) == _key(item)), None)
        if target is None:
            raise DownloadResumeError("后续恢复范围不符，请核对平台原任务")
        return latest, json.loads(row["config_json"]), target

    def _detail_source(self, run, config, item):
        visited = set()
        with self._connection() as connection:
            for _ in range(64):
                if run["id"] in visited:
                    break
                visited.add(run["id"])
                if not any(_key(value) == _key(item) for value in run["items"]):
                    break
                try:
                    return self._check_detail_receipt(run, {**config, "cities": [item["city"]], "start": item["start"], "end": item["end"]})
                except DownloadResumeError:
                    parent = config.get("retry_of") or config.get("resume_detail_from")
                    if not parent:
                        break
                    row = connection.execute("SELECT state_json,config_json FROM download_runs WHERE id=?", (parent,)).fetchone()
                    if row is None:
                        break
                    run, config = json.loads(row["state_json"]), json.loads(row["config_json"])
        raise DownloadResumeError("未取得可核验的原明细提交凭据，不能恢复下载")

    def _check_daily_receipt(self, run, config, item):
        try:
            agency = str(_configured_cities()[item["city"]])
            source = self._archive_directory(run)
            raw = (source / "原始资料" / archive_component(item["city"]) / "agency_daily"
                   if run.get("archive_version") == ARCHIVE_VERSION else source / agency / "raw" / "agency_daily")
            ledger_path, baseline_path = raw / "http_submission.json", raw / "http_baseline.json"
            components = (source, raw.parent.parent, raw.parent, raw, ledger_path, baseline_path)
            if (any(path.is_symlink() for path in components) or raw.resolve() != raw
                    or not raw.is_relative_to(source) or any(not path.is_file() or not 0 < path.stat().st_size <= 65536
                                                           for path in (ledger_path, baseline_path))):
                raise ValueError()
            ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
            baseline = json.loads(baseline_path.read_text(encoding="utf-8"))
            scope = ledger["scope"]
            ids = baseline["task_ids"]
            if (ledger.get("transport") != "http" or scope.get("agency_id") != agency
                    or scope.get("start") != item["start"] or scope.get("end") != item["end"]
                    or item["dataset"] not in scope.get("datasets", [])
                    or not isinstance(ledger.get("started_at"), (int, float))
                    or isinstance(ledger["started_at"], bool) or not isinstance(ids, list)
                    or len(ids) > 100 or len(set(ids)) != len(ids)
                    or any(type(value) is not int or value <= 0 for value in ids)):
                raise ValueError()
            return raw
        except (OSError, ValueError, KeyError, TypeError):
            raise DownloadResumeError("缺少可核验的原日账单提交凭据，不能恢复下载") from None

    def _daily_source(self, run, config, item):
        visited = set()
        with self._connection() as connection:
            for _ in range(64):
                if run["id"] in visited:
                    break
                visited.add(run["id"])
                if not any(_key(value) == _key(item) for value in run["items"]):
                    break
                try:
                    return self._check_daily_receipt(run, config, item)
                except DownloadResumeError:
                    parent = config.get("retry_of")
                    if not parent:
                        break
                    row = connection.execute("SELECT state_json,config_json FROM download_runs WHERE id=?", (parent,)).fetchone()
                    if row is None:
                        break
                    run, config = json.loads(row["state_json"]), json.loads(row["config_json"])
        raise DownloadResumeError("未取得可核验的原日账单提交凭据，不能恢复下载")

    def _order_source(self, run, config, item):
        from fengshen_http_reports import order_recovery_manifests
        visited = set()
        with self._connection() as connection:
            for _ in range(64):
                if run["id"] in visited:
                    break
                visited.add(run["id"])
                try:
                    agency = str(_configured_cities()[item["city"]])
                    source = self._archive_directory(run)
                    raw = (source / "原始资料" / archive_component(item["city"]) / "issue_orders"
                           if run.get("archive_version") == ARCHIVE_VERSION else source / agency / "raw" / "issue_orders")
                    if any(p.is_symlink() for p in (source, raw.parent.parent, raw.parent, raw)) or raw.resolve() != raw:
                        raise ValueError()
                    plan = SimpleNamespace(agency_id=agency, start=item["start"], end=item["end"])
                    order_recovery_manifests(plan, raw, {item["dataset"]})
                    return raw
                except Exception:
                    parent = config.get("retry_of")
                    if not parent:
                        break
                    row = connection.execute("SELECT state_json,config_json FROM download_runs WHERE id=?", (parent,)).fetchone()
                    if row is None:
                        break
                    run, config = json.loads(row["state_json"]), json.loads(row["config_json"])
        raise DownloadResumeError("原运单回执或文件不完整，不能恢复下载")

    def _waybill_source(self, run, config, item, verify=True):
        from binding_recovery import verified_file
        from fengshen_bill import BillCollectionError
        from fengshen_orders import date_batches
        try:
            source = self._archive_directory(run)
            raw = source / "原始资料" / archive_component(item["city"]) / "delivery_waybill"
            if any(p.is_symlink() for p in (source, raw.parent.parent, raw.parent, raw)) or raw.resolve() != raw:
                raise DownloadResumeError("原运单原始目录无效，不能恢复")
            batches = date_batches(item["start"], item["end"], today=dt.date.fromisoformat(item["end"]))
            for start, end in batches:
                directory = raw / f"{start}_{end}"
                if directory.is_symlink() or not directory.is_dir():
                    raise DownloadResumeError("原运单原始文件不完整，不能恢复")
                manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
                if (manifest.get("status") != "success" or manifest.get("start") != start
                        or manifest.get("end") != end or not isinstance(manifest.get("files"), list)
                        or not manifest["files"]):
                    raise DownloadResumeError("原运单原始文件不完整，不能恢复")
                for receipt in manifest["files"]:
                    if verify:
                        verified_file(directory, receipt)
                    else:
                        path = directory / receipt["path"]
                        if path.is_symlink() or not path.is_file() or receipt.get("bytes") != path.stat().st_size:
                            raise DownloadResumeError("原运单原始文件不完整，不能恢复")
            return raw
        except DownloadResumeError:
            raise
        except (OSError, ValueError, KeyError, TypeError, BillCollectionError):
            raise DownloadResumeError("原运单原始文件不完整，不能恢复") from None

    def _lanorange_source(self, run, item, config=None):
        from binding_recovery import verified_file
        from lanorange_catalog import source_directory, platform_months, source_filters
        raw = source_directory(self._archive_directory(run), item['city'], item['dataset'])
        try:
            info = json.loads((raw / 'source_receipt.json').read_text(encoding='utf-8'))
            months = platform_months(config or run, item['dataset'])
            expected = source_filters(item['city'], months)
            legacy = source_filters(item['city'])
            if (info.get('dataset') != item['dataset'] or info.get('status') != 'validated'
                    or info.get('filters') not in (expected, legacy)):
                raise ValueError()
            verified_file(raw, info)
            return raw
        except (OSError, ValueError, KeyError, TypeError, RuntimeError):
            raise DownloadResumeError('蓝橙原始资料未完整校验，不能恢复文件') from None

    def _lanorange_recovery_source(self, run, config, item):
        try: return self._lanorange_source(run,item,config)
        except DownloadResumeError:
            if not config.get('lanorange_full_delivery'): raise
        from lanorange_catalog import source_directory
        raw=source_directory(self._archive_directory(run),item['city'],item['dataset'])
        try:
            if not raw.resolve().is_relative_to(self._archive_directory(run).resolve()):raise ValueError()
            path=raw/'full_strategy.json'
            if path.is_symlink() or path.stat().st_size>1024*1024: raise ValueError()
            state=json.loads(path.read_text(encoding='utf-8'))
            complete_original=state.get('phase')=='full' and (raw/'全量原表/source_receipt.json').is_file()
            if state.get('version')!=1 or state.get('dataset')!=item['dataset'] or not (state.get('fallback_allowed') or complete_original):
                raise ValueError()
            return raw
        except (OSError,ValueError,TypeError):
            raise DownloadResumeError('蓝橙全量请求或分批回执未确认，不能自动重新提交') from None

    def _binding_materials(self, run, item):
        from binding_recovery import completed_materials
        root = self._archive_directory(run)
        agency = str(_configured_cities()[item['city']])
        candidates = [None]
        with self._connection() as connection:
            rows = connection.execute('SELECT state_json FROM download_runs WHERE owner=? AND created_at>=? ORDER BY created_at DESC',
                                      (self.run_owner(run['id']), run['created_at'])).fetchall()
        for row in rows:
            other = json.loads(row['state_json'])
            if any(value.get('status') == 'success' and value.get('dataset') == 'rider_info'
                   and value.get('city') == item['city'] for value in other.get('items', [])):
                candidates.append(self._archive_directory(other) / '原始资料' / item['city'] / 'rider_info')
        for snapshot in candidates:
            try:
                return completed_materials(root, item['city'], agency, item['start'], item['end'], snapshot)
            except (OSError, ValueError, KeyError, TypeError, RuntimeError):
                continue
        raise DownloadResumeError('支付绑定资料尚未完整校验，不能只恢复生成；请先补齐缺失资料')

    def _merchant_source(self,run,config,item):
        from fengshen_merchant_exports import source_directory,recoverable_source,source_key
        from fengshen_bill import BillCollectionError
        key=source_key(item['city'],item['dataset'])
        raw=source_directory(self._archive_directory(run),item['dataset'],item['city'])
        if not raw.exists() and config.get('resume_merchant_sources',{}).get(key):raw=Path(config['resume_merchant_sources'][key])
        resolved=raw.resolve()
        if raw.is_symlink() or not (resolved.is_relative_to(self.output_root.resolve()) or resolved.is_relative_to(self.workspace_root)):raise DownloadResumeError('商家分段缓存路径异常')
        try:return recoverable_source(raw,item['dataset'],item['start'],item['end'],item['city'])
        except Exception as error:raise DownloadResumeError(str(error) if isinstance(error,BillCollectionError) else '商家分段回执或文件暂不可访问') from None

    def _recovery_info(self, run, config, item, connection=None):
        if item.get("status") not in ("error", "cancelled", "interrupted"):
            return {"mode": "blocked", "reason": "该项无需恢复"}
        if connection is None:
            with self._connection() as lookup:
                return self._recovery_info(run, config, item, lookup)
        try:
            run, config, item = self._effective_attempt(connection, run, config, item)
        except DownloadResumeError as exc:
            return {"mode": "blocked", "reason": str(exc)}
        if run["status"] in ACTIVE_STATUSES:
            return {"mode": "blocked", "reason": "该项已有恢复任务正在执行，请查看下载记录"}
        if item.get("status") == "success":
            return {"mode": "blocked", "reason": "该项已在后续恢复任务完成，请领取已有成品"}
        from lanorange_catalog import DATASETS as blue
        from fengshen_merchant_protocol import KINDS as merchant_kinds
        if item['dataset'] in merchant_kinds:
            try:
                self._merchant_source(run,config,item)
                return {'mode':'resume_existing','reason':'复用已完成分段；已提交分段仅重新领取，未提交分段继续导出'}
            except DownloadResumeError as error:
                if item.get('submission_state')=='not_submitted':return {'mode':'retry_unsubmitted','reason':'尚未提交导出，可重新读取当前商家资料'}
                return {'mode':'blocked','reason':str(error)}
        if item['dataset'] in blue:
            try:
                self._lanorange_recovery_source(run, config, item)
                return {'mode': 'resume_existing', 'reason': '复用已完成文件和分批回执，只补失败或未提交批次' if config.get('lanorange_full_delivery') else '已有完整原始文件，仅恢复归档，不重新导出'}
            except DownloadResumeError:
                try:
                    from lanorange_catalog import source_directory
                    raw = source_directory(self._archive_directory(run), item['city'], item['dataset'])
                    if config.get('lanorange_full_delivery') and (raw/'full_strategy.json').exists():
                        return {'mode':'blocked','reason':'全量请求状态或分批覆盖尚未确认，请查看后台回执；不会重复提交未知请求'}
                    if not (raw / 'http_submission.json').exists():
                        return {'mode': 'retry_unsubmitted', 'reason': '确认没有导出提交记录，可重新执行'}
                    return {'mode': 'blocked', 'reason': '蓝橙导出已提交或结果未确认，请核对原始回执，避免重复导出'}
                except Exception:
                    return {'mode': 'blocked', 'reason': '蓝橙原始文件或归档暂不可访问'}
            except Exception:
                return {'mode': 'blocked', 'reason': '蓝橙原始文件或归档暂不可访问'}
        if item['dataset'] == 'payment_binding':
            try:
                self._binding_materials(run, item)
                return {'mode': 'resume_existing', 'reason': '五类资料已完整校验，仅恢复本地生成，不重新提交平台导出'}
            except DownloadResumeError as exc:
                return {'mode': 'blocked', 'reason': str(exc)}
            except Exception:
                return {'mode': 'blocked', 'reason': '支付绑定资料暂不可访问'}
        if item["dataset"] == "rider_detail":
            try:
                self._detail_source(run, config, item)
                return {"mode": "resume_existing", "reason": "已有有效提交凭据，只查询并下载原平台任务"}
            except (DownloadResumeError, Exception):
                pass
        if item["dataset"] == "delivery_waybill":
            try:
                self._waybill_source(run, config, item, verify=False)
                return {"mode": "resume_existing",
                        "reason": "已下载的运单原始文件完整，仅重新校验并生成成品，不重新提交导出"}
            except DownloadResumeError as exc:
                return {"mode": "blocked", "reason": str(exc)}
        if item["dataset"] in ("delivery_fee", "penalty") and item.get("submission_state") != "not_submitted":
            try:
                self._daily_source(run, config, item)
                return {"mode": "resume_existing", "reason": "已有日账单提交凭据，只查询并下载原平台任务"}
            except (DownloadResumeError, Exception):
                pass
        if item["dataset"] in ("fraud", "problem") and item.get("submission_state") != "not_submitted":
            try:
                self._order_source(run, config, item)
                return {"mode": "resume_existing", "reason": "原运单与报告文件已保留，仅校验和生成成品"}
            except (DownloadResumeError, Exception):
                pass
        if item.get("submission_state") == "not_submitted":
            return {"mode": "retry_unsubmitted", "reason": "确认尚未提交平台导出，可重新执行本项"}
        return {"mode": "blocked", "reason": "提交状态未确认或暂不支持安全恢复，请核对平台原任务，避免重复导出"}

    def _public_run(self, connection, run):
        result = _public(run)
        for file in result['files']:
            try:
                published=self.deliveries.location(run['id'],file['id'])
                if published is not None:file['name']=published.name
            except (OSError,ValueError):
                pass
        if run.get("status") == "queued":
            active_ids = [row["id"] for row in connection.execute(
                "SELECT id FROM download_runs WHERE status IN (?,?,?,?) ORDER BY created_at,rowid", tuple(sorted(ACTIVE_STATUSES))).fetchall()
                          if row['id'] not in self._collection_released]
            result["queue_position"] = active_ids.index(run["id"]) + 1 if run["id"] in active_ids else 0
            result['queue_wait_reason'] = ('local_capacity' if len(self._processing_threads) >= 2
                                           else 'collection_busy' if self._processing_threads else 'queued')
        else:
            result["queue_position"] = 0
        row = connection.execute("SELECT config_json FROM download_runs WHERE id=?", (run["id"],)).fetchone()
        if row:
            config = json.loads(row["config_json"])
            for item in result["items"]:
                try:
                    item["recovery"] = self._recovery_info(run, config, item, connection)
                except Exception:
                    item["recovery"] = {"mode": "blocked", "reason": "无法读取恢复信息"}
        return result

    def _run_dir(self, run):
        if not re.fullmatch(r"[0-9a-f]{32}", run.get("id", "")):
            raise DownloadNotFound("归档目录无效")
        if "archive_version" in run:
            root_value, relative_value = run.get("_archive_root"), run.get("archive_relative_dir")
            if (type(run["archive_version"]) is not int or run["archive_version"] != ARCHIVE_VERSION
                    or not isinstance(root_value, str) or not Path(root_value).is_absolute()
                    or not isinstance(relative_value, str)):
                raise DownloadNotFound("归档目录无效")
            root = Path(root_value).resolve()
            relative = Path(relative_value)
            if (relative.is_absolute() or relative.drive or not relative.parts
                    or any(part in (".", "..") for part in relative.parts)):
                raise DownloadNotFound("归档目录无效")
            expected = archive_relative_dir(run["id"], run["created_at"], run["cities"], run.get('archive_label'))
            if relative != Path(expected):
                raise DownloadNotFound("归档目录无效")
            candidate = root / relative
            resolved = candidate.resolve()
            if not resolved.is_relative_to(root) or resolved != candidate:
                raise DownloadNotFound("归档目录无效")
            return resolved
        roots = [self.output_root, (ROOT / "outputs" / "fengshen_downloads").resolve()]
        for root in roots:
            candidate = root / run["id"]
            resolved = candidate.resolve()
            if resolved != candidate or not resolved.is_relative_to(root):
                raise DownloadNotFound("归档目录无效")
            if candidate.is_dir():
                return resolved
        return self.output_root / run["id"]

    def _run_directory(self, owner, run_id):
        with self._lock, self._connection() as connection:
            _, run = self._find(connection, owner, run_id)
            return self._run_dir(run)

    def _archive_directory(self, run, create=False, exclusive=False):
        directory = self._run_dir(run)
        if "archive_version" not in run:
            if create:
                directory.mkdir(parents=True, exist_ok=not exclusive)
            return directory
        marker = directory / ".archive_task.json"
        if create:
            directory.parent.mkdir(parents=True, exist_ok=True)
            try:
                directory.mkdir()
            except FileExistsError:
                if exclusive:
                    raise DownloadArchiveError("归档目录已经存在，未重新执行下载任务") from None
            else:
                with marker.open("x", encoding="utf-8") as stream:
                    json.dump({"id": run["id"], "version": ARCHIVE_VERSION}, stream)
        try:
            if marker.is_symlink() or not marker.is_file() or marker.stat().st_size > 1024:
                raise ValueError()
            identity = json.loads(marker.read_text(encoding="utf-8"))
            if identity != {"id": run["id"], "version": ARCHIVE_VERSION}:
                raise ValueError()
        except (OSError, ValueError, UnicodeError):
            raise DownloadNotFound("归档目录身份不符，未读取或修改已有文件") from None
        return directory

    def _check_detail_receipt(self, run, config):
        """Validate an on-disk receipt without changing the failed job's files."""
        try:
            agency = str(_configured_cities()[config["cities"][0]])
        except Exception:
            raise DownloadResumeError("原任务城市配置无法确认，不能恢复下载") from None
        if not re.fullmatch(r"\d{1,20}", agency):
            raise DownloadResumeError("原任务城市或目录标识无效，不能恢复下载")
        try:
            source = self._archive_directory(run)
            raw = (source / "原始资料" / archive_component(config["cities"][0]) / "rider_detail"
                   if run.get("archive_version") == ARCHIVE_VERSION else source / agency / "raw" / "rider_detail")
        except Exception:
            raise DownloadResumeError("原任务归档目录无效，不能恢复下载") from None
        receipt = raw / "detail_submission.json"
        try:
            # Reject aliases at every component, including links to another
            # source inside this run. Only its own rider_detail receipt counts.
            components = (source, raw.parent.parent, raw.parent, raw, receipt)
            if (any(path.is_symlink() for path in components)
                    or raw.resolve() != raw
                    or not receipt.resolve().is_relative_to(raw.resolve())
                    or not raw.resolve().is_relative_to(source.resolve())
                    or not receipt.is_file() or not 0 < receipt.stat().st_size <= 2 * 1024 * 1024):
                raise ValueError()
            proof = json.loads(receipt.read_text(encoding="utf-8"))
        except (OSError, ValueError, UnicodeError):
            raise DownloadResumeError("缺少本次骑手明细提交凭据，不能恢复下载") from None
        if (not isinstance(proof, dict) or proof.get("agency_id") != agency
                or proof.get("start") != config["start"] or proof.get("end") != config["end"]
                or proof.get("request_observed") is not True
                or type(proof.get("http_status")) is not int or proof["http_status"] != 200
                or type(proof.get("response_code")) is not int or proof["response_code"] != 200):
            raise DownloadResumeError("原导出的城市、日期或成功提交凭据不完整，不能恢复下载")
        for field, allow_empty in (("selected_team_ids", False), ("existing_task_ids", True)):
            values = proof.get(field)
            if (not isinstance(values, list) or (not values and not allow_empty) or len(values) > 10000
                    or any(not isinstance(value, str) or not re.fullmatch(r"\d{1,20}", value) for value in values)
                    or len(set(values)) != len(values)):
                raise DownloadResumeError("原导出缺少有效站点或历史任务基线，不能恢复下载")
        submitted = proof.get("submitted_at")
        try:
            if not isinstance(submitted, str) or not re.match(r"^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}", submitted):
                raise ValueError()
            dt.datetime.fromisoformat(submitted)
        except ValueError:
            raise DownloadResumeError("原导出提交时间无效，不能恢复下载") from None
        if proof.get("task_id") is not None and (not isinstance(proof["task_id"], str)
                                                 or not re.fullmatch(r"\d{1,20}", proof["task_id"])):
            raise DownloadResumeError("原导出任务编号无效，不能恢复下载")
        return raw

    def recover_detail(self, owner, run_id):
        # Keep lookup, eligibility and creation under the same process lock so
        # simultaneous clicks cannot enqueue two recovery jobs for one export.
        with self._lock:
            with self._connection() as connection:
                row, run = self._find(connection, owner, run_id)
                config = json.loads(row["config_json"])
                if (run["status"] not in ("error", "partial") or row["status"] not in ("error", "partial")
                        or "rider_detail" not in config.get("datasets", [])
                        or not isinstance(config.get("cities"), list) or len(config["cities"]) != 1
                        or any(item.get("dataset") == "rider_detail" and item.get("status") == "success"
                               for item in run.get("items", []))
                        or any(file.get("dataset") == "rider_detail" for file in run.get("files", []))):
                    raise DownloadResumeError("仅能恢复单城市失败任务中尚未成功下载的骑手明细")
                selected = [{key: item[key] for key in ("city", "dataset", "start", "end")}
                            for item in run["items"] if item["dataset"] == "rider_detail"]
            return self.retry(owner, run_id, selected, "legacy_resume_" + run_id, existing_only=True)

    def binding_runs(self):
        """Durable binding history must outlive the recent-task UI limit."""
        with self._lock, self._connection() as connection:
            rows = connection.execute("SELECT state_json FROM download_runs WHERE config_json LIKE ? ORDER BY created_at DESC,rowid DESC",
                                      ('%"payment_binding"%',)).fetchall()
        return [value for row in rows if 'payment_binding' in (value := json.loads(row['state_json'])).get('datasets', [])]

    def list_runs(self, owner):
        with self._lock, self._connection() as connection:
            rows = (connection.execute("SELECT state_json FROM download_runs ORDER BY created_at DESC,rowid DESC LIMIT 200").fetchall()
                    if owner is None else connection.execute("SELECT state_json FROM download_runs WHERE owner = ? ORDER BY created_at DESC, rowid DESC LIMIT 100",
                                                            (owner,)).fetchall())
            runs = []
            for row in rows:
                try:
                    runs.append(self._public_run(connection, json.loads(row["state_json"])))
                except Exception:
                    try:
                        runs.append(_public(json.loads(row["state_json"])))
                    except Exception:
                        pass
            return runs

    def record_snapshots(self, owner):
        """Include ancestors beyond the recent-task limit; never expose paths."""
        with self._lock, self._connection() as connection:
            rows = (connection.execute('SELECT state_json FROM download_runs ORDER BY created_at,rowid').fetchall()
                    if owner is None else connection.execute('SELECT state_json FROM download_runs WHERE owner=? ORDER BY created_at,rowid', (owner,)).fetchall())
            result = []
            for order, row in enumerate(rows):
                run = json.loads(row['state_json'])
                public = _public(run)
                public['_record_order'] = order
                for file in public['files']:
                    raw = next(entry for entry in run['files'] if entry['id'] == file['id'])
                    try:
                        directory = self._archive_directory(run)
                        path = self._artifact_path(run, raw)
                        exists = path.is_file()
                        file['name'] = path.name
                        available = exists and path.stat().st_size == raw['bytes']
                        reason = '' if available else '文件已变更' if exists else '文件已不存在'
                    except (OSError, ValueError, DownloadNotFound, DownloadRootError, DownloadArchiveError):
                        available, reason = False, '文件位置暂不可访问'
                    file.update(available=available, unavailable_reason=reason)
                result.append(public)
            return result

    def get_run(self, owner, run_id):
        with self._lock, self._connection() as connection:
            _, run = self._find(connection, owner, run_id)
            return self._public_run(connection, run)

    def run_owner(self, run_id):
        with self._lock, self._connection() as connection:
            row = connection.execute("SELECT owner FROM download_runs WHERE id=?", (run_id,)).fetchone()
            if row is None:
                raise DownloadNotFound("下载任务不存在")
            return row["owner"]

    def retry(self, owner, run_id, items, request_id, actor_owner=None, allow_shared_result=False, existing_only=False):
        with self._lock:
            return self._retry_locked(owner, run_id, items, request_id, actor_owner, allow_shared_result, existing_only)

    def _retry_locked(self, owner, run_id, items, request_id, actor_owner, allow_shared_result, existing_only):
        if not isinstance(items, list) or not items or len(items) > 1000:
            raise DownloadResumeError("请选择需要恢复的失败子项")
        if any(not isinstance(item, dict) or set(item) != {"city", "dataset", "start", "end"}
               or any(not isinstance(value, str) for value in item.values()) for item in items):
            raise DownloadResumeError("恢复子项参数无效")
        keys = [_key(item) for item in items]
        if len(set(keys)) != len(keys):
            raise DownloadResumeError("恢复子项不能重复")
        with self._lock, self._connection() as connection:
            row, run = self._find(connection, owner, run_id)
            config = json.loads(row["config_json"])
            original = {_key(item): item for item in run["items"]}
            if any(key not in original for key in keys):
                raise DownloadResumeError("子项不属于原任务")
            selected_cities = [city for city in config["cities"] if any(key[0] == city for key in keys)]
            if not selected_cities:
                from lanorange_catalog import ALL_CITIES
                selected_cities = [ALL_CITIES]
            selected_datasets = [kind for kind in config["datasets"] if any(key[1] == kind for key in keys)]
            requested_config = {key: config[key] for key in ("cities", "datasets", "start", "end", "months")}
            if config.get('lanorange_months'): requested_config['lanorange_months'] = list(config['lanorange_months'])
            if config.get('lanorange_by_city'): requested_config['lanorange_by_city'] = True
            if config.get('lanorange_full_delivery'): requested_config['lanorange_full_delivery'] = True
            if config.get('merchant_by_city'): requested_config['merchant_by_city'] = True
            for option in ('include_separation', 'exclude_separation', 'payroll_agencies', 'task_kind', 'generation_target', 'parent_batch_id', 'parent_workspace'):
                if option in config: requested_config[option] = config[option]
            requested_config.update(cities=selected_cities, datasets=selected_datasets,
                                    retry_of=run_id, retry_items=sorted(items, key=_key))
            if config.get("refresh_history"):
                requested_config["refresh_history"] = True
            fingerprint = _fingerprint(requested_config)
            actor_owner = actor_owner or owner
            if not isinstance(request_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]{8,128}", request_id):
                raise DownloadRequestConflict("提交标识无效")
            previous = connection.execute("SELECT config_hash,run_id FROM download_requests WHERE owner=? AND request_id=?",
                                           (actor_owner, request_id)).fetchone()
            if previous:
                if previous["config_hash"] != fingerprint:
                    raise DownloadRequestConflict("同一次恢复的子项已改变，请先查看原恢复任务")
                _, existing = self._find(connection, self.run_owner(previous["run_id"]), previous["run_id"])
                return self._public_run(connection, existing)
            if run["status"] not in FINAL_STATUSES:
                raise DownloadResumeError("原任务仍在执行，请等待其结束后再恢复失败项")
            effective = [self._effective_attempt(connection, run, config, original[key]) for key in keys]
            occupied = [(latest, latest_item) for latest, _, latest_item in effective
                        if latest["status"] in ACTIVE_STATUSES or latest_item.get("status") == "success"]
            if occupied:
                if (len(occupied) == len(keys) and len({value[0]["id"] for value in occupied}) == 1
                        and occupied[0][0]["id"] != run_id):
                    existing = occupied[0][0]
                    existing_owner = self.run_owner(existing["id"])
                    if existing_owner != actor_owner and not allow_shared_result:
                        raise DownloadResumeError("该项已有恢复记录，请联系管理员查看")
                    connection.execute("INSERT INTO download_requests VALUES(?,?,?,?)", (actor_owner, request_id, fingerprint, existing["id"]))
                    return self._public_run(connection, existing)
                raise DownloadResumeError("所选项中已有正在执行或已完成的恢复记录，请只选择未完成子项")
            sources, daily_sources, order_sources, waybill_sources, binding_materials, blue_sources,merchant_sources = {}, {}, {}, {}, {}, {},{}
            for latest, latest_config, item in effective:
                recovery = self._recovery_info(latest, latest_config, item, connection)
                if recovery["mode"] == "blocked":
                    raise DownloadResumeError(recovery["reason"])
                if existing_only and recovery["mode"] != "resume_existing":
                    raise DownloadResumeError("此入口仅恢复已提交的原平台任务，不会重新提交导出")
                if recovery["mode"] == "resume_existing":
                    from lanorange_catalog import DATASETS as blue
                    from fengshen_merchant_protocol import KINDS as merchant_kinds
                    if item['dataset'] in merchant_kinds:
                        from fengshen_merchant_exports import source_key
                        merchant_sources[source_key(item['city'],item['dataset'])]=self._merchant_source(latest,latest_config,item)
                    elif item['dataset'] in blue:
                        from lanorange_catalog import source_key
                        blue_sources[source_key(item['city'], item['dataset'])] = self._lanorange_recovery_source(latest, config, item)
                    elif item['dataset'] == 'payment_binding':
                        binding_materials[item['city'] + '|' + item['start'][:7]] = self._binding_materials(latest, item)
                    elif item["dataset"] == "rider_detail":
                        sources[item["city"]] = self._detail_source(latest, latest_config, item)
                    elif item["dataset"] in ("delivery_fee", "penalty"):
                        daily_sources[item["city"]] = self._daily_source(latest, latest_config, item)
                    elif item["dataset"] in ("fraud", "problem"):
                        order_sources[item["city"]] = self._order_source(latest, latest_config, item)
                    elif item["dataset"] == "delivery_waybill":
                        waybill_sources[item["city"]] = self._waybill_source(latest, latest_config, item)
        return self._create(actor_owner, {**config, "cities": selected_cities, "datasets": selected_datasets},
                            request_id=request_id, retry_of=run_id, retry_items=items,
                            resume_detail_sources=sources, resume_daily_sources=daily_sources,
                            resume_order_sources=order_sources, resume_waybill_sources=waybill_sources,
                            resume_binding_materials=binding_materials,
                            resume_lanorange_sources=blue_sources,resume_merchant_sources=merchant_sources)

    def cancel(self, owner, run_id):
        with self._lock, self._connection() as connection:
            _, run = self._find(connection, owner, run_id)
            if run["status"] in FINAL_STATUSES:
                return _public(run)
            event = self._events.get(run_id)
            if event is not None:
                event.set()
            if run["status"] == "queued":
                run["status"] = "cancelled"
                run.update(phase="cancelled", phase_since=_now(), last_activity_at=_now())
                for item in run["items"]:
                    item.update(status="cancelled", phase="cancelled", error="")
                _add_log(run, "排队中的任务已取消")
            elif run["status"] != "cancelling":
                run["status"] = "cancelling"
                _add_log(run, "正在取消任务，已完成的文件将保留")
            _refresh(run)
            self._save(connection, run)
            result = _public(run)
        if result["status"] in FINAL_STATUSES:
            self._summary_best_effort(owner, run_id)
        return result

    def get_summary(self, owner, run_id):
        with self._lock:
            with self._connection() as connection:
                _, run = self._find(connection, owner, run_id)
            if run["status"] not in FINAL_STATUSES:
                raise DownloadSummaryPending("任务结束后才能下载说明")
            try:
                directory = self._archive_directory(run, create=True)
                summary = Path(write_download_summary(directory, _without_private(json.loads(json.dumps(run))))).resolve()
                if run.get('result_layout') == 2:
                    write_task_checklist(directory, run)
                if summary.parent != directory or summary.name != "下载说明.txt" or not summary.is_file():
                    raise ValueError()
                return summary, "下载说明.txt"
            except Exception:
                self._mutate(owner, run_id, lambda current: _add_log(
                    current, "下载说明写入失败，业务下载结果保持不变；请检查归档目录权限后重试"))
                raise DownloadSummaryError("下载说明暂时无法生成，请检查归档目录权限后重试") from None

    def _summary_best_effort(self, owner, run_id):
        try:
            self.get_summary(owner, run_id)
        except Exception:
            pass
        if self.flat_delivery:
            try:
                self.publish_delivery(owner,run_id)
            except DownloadSummaryPending:
                pass
            except Exception:
                # Keep successful business work and its sources; surface delivery
                # failure without losing a result or silently reporting it ready.
                self._mutate(owner,run_id,lambda run: _add_log(run,'结果目录发布未完成；原资料已保留，可重新打开任务目录重试'))

    def _artifact_path(self, run, entry):
        published = self.deliveries.location(run['id'],entry['id'])
        if published is not None:
            return published
        directory = self._archive_directory(run)
        candidate = (directory / entry['relative_path']).resolve()
        if not candidate.is_relative_to(directory):
            raise DownloadNotFound('文件路径无效')
        return candidate if candidate.is_file() else self.deliveries.relocated(candidate) or candidate

    def publish_delivery(self, owner, run_id):
        from download_records import get_record
        from task_catalog import GENERATORS
        with self._lock:
            record = get_record(self,owner,run_id)
            if record['status'] not in FINAL_STATUSES:
                raise DownloadSummaryPending('任务结束后发布结果')
            selected = [f for f in record['files'] if f.get('available',True) and
                        (record['kind'] != 'generate' or f['dataset'] in GENERATORS)]
            if not selected:
                raise DownloadNotFound('暂无可发布结果')
            entries=[]
            for file in selected:
                file_owner=self.run_owner(file['run_id']) if owner is None else owner
                path,name=self.get_file(file_owner,file['run_id'],file['id'])
                entries.append({**file,'path':str(path),'name':name})
            label=delivery_folder_label(record['datasets'],record['start'],record['created_at'])
            return self.deliveries.publish(record['id'],record['created_at'],label,entries,
                                           record.get('incomplete_items',[]),sequence_collision=True)

    def _mutate(self, owner, run_id, update):
        with self._lock, self._connection() as connection:
            _, run = self._find(connection, owner, run_id)
            update(run)
            run["last_activity_at"] = _now()
            _refresh(run)
            self._save(connection, run)

    def _update_item(self, owner, run_id, change):
        if not isinstance(change, dict) or change.get("status") not in ITEM_STATUSES:
            raise ValueError("下载子任务状态无效")
        def update(run):
            if run["status"] in FINAL_STATUSES:
                return
            if change.get('payroll_verification_required') is True and run.get('task_kind') == 'payroll_source':
                run['payroll_verification_required'] = True
            if change.get("_run_event") is True:
                phase = change.get("phase")
                if phase not in PHASES:
                    raise ValueError("下载阶段无效")
                if run.get("phase") != phase:
                    run["phase_since"] = _now()
                run["phase"] = phase
                if isinstance(change.get("order_progress"), dict):
                    value = change["order_progress"]
                    allowed = {"batches", "batch", "downloaded", "processed", "cached_days", "download_bytes", "obtained",
                               "processed_rows", "elapsed_seconds"}
                    safe = {key: number for key, number in value.items() if key in allowed
                            and type(number) in (int, float) and math.isfinite(number) and 0 <= number <= 10**12}
                    if value.get("stage") in ("collecting", "processing", "merging", "completed"):
                        safe["stage"] = value["stage"]
                    run["order_progress"] = safe
                if isinstance(change.get("summary_progress"), dict):
                    value = change["summary_progress"]
                    detail = run.get("summary_progress") if isinstance(run.get("summary_progress"), dict) else {}
                    if value.get("stage") in ("merging", "completed", "failed"):
                        detail["stage"] = value["stage"]
                    for field in ("current", "total"):
                        if type(value.get(field)) is int and 0 <= value[field] <= 10**6:
                            detail[field] = value[field]
                    city = value.get("city")
                    if isinstance(city, str) and 0 < len(city) <= 40:
                        detail["city"] = city
                    month = value.get("month")
                    if isinstance(month, str) and re.fullmatch(r"\d{4}-\d{2}", month):
                        detail["month"] = month
                    run["summary_progress"] = detail
                if run["status"] != "cancelling":
                    run["status"] = "waiting_login" if change["status"] == "waiting_login" else "running"
                return
            target = next((item for item in run["items"] if _key(item) == _key(change)), None)
            if target is None:
                raise ValueError("下载子任务范围无效")
            if "files" in change:
                if change["status"] != "success" or not isinstance(change["files"], list) or not change["files"]:
                    raise ValueError("下载子项文件清单无效")
                with self._connection() as connection:
                    row, _ = self._find(connection, owner, run_id)
                config = json.loads(row["config_json"])
                verified = [self._file_entry(run, info, config) for info in change["files"]]
                if any(_key(entry) != _key(target) for entry in verified):
                    raise ValueError("子项文件不属于本项")
                self._merge_files(run, verified)
            phase = change.get("phase") or {"queued": "queued", "success": "completed", "error": "failed",
                                             "waiting_login": "waiting_login", "running": "preparing",
                                             "cancelled": "cancelled", "interrupted": "interrupted"}.get(change["status"])
            if phase not in PHASES:
                raise ValueError("下载子项阶段无效")
            if target.get("phase") != phase:
                target["phase_since"] = _now()
            target["phase"] = phase
            if run.get("phase") != phase:
                run["phase_since"] = _now()
            run["phase"] = phase
            if change.get("submission_state") in ("not_submitted", "submitted", "unknown"):
                target["submission_state"] = change["submission_state"]
            elif change["status"] in ("running", "waiting_login"):
                target["submission_state"] = "unknown"
            elif change["status"] == "error" and target.get("status") == "queued":
                target["submission_state"] = "unknown"
            if change.get("failure_phase") in PHASES:
                target["failure_phase"] = change["failure_phase"]
            target["status"] = change["status"]
            target["error"] = _safe_text(change.get("error")) if change["status"] == "error" and change.get("error") else ""
            if run["status"] != "cancelling":
                run["status"] = "waiting_login" if change["status"] == "waiting_login" else "running"
        self._mutate(owner, run_id, update)

    @staticmethod
    def _merge_files(run, entries):
        existing = {_key(entry): entry for entry in run["files"]}
        for entry in entries:
            previous = existing.get(_key(entry))
            if previous:
                if any(previous.get(key) != entry.get(key) for key in ("relative_path", "name", "sha256", "bytes")):
                    raise ValueError("子项文件重复且内容不一致")
            else:
                run["files"].append(entry)
                existing[_key(entry)] = entry

    def _restore_checkpoint(self, run, config):
        """Import verified committed files, never infer a new platform request."""
        try:
            directory = self._archive_directory(run)
            path = directory / "manifest.json"
            if path.is_symlink() or not path.is_file() or not 0 < path.stat().st_size <= 16 * 1024 * 1024:
                return
            checkpoint = json.loads(path.read_text(encoding="utf-8"))
            if (checkpoint.get("payroll_executed") is not False
                    or _fingerprint(checkpoint["config"]) != _fingerprint(config)):
                return
            successful = {_key(item) for item in checkpoint.get("items", []) if item.get("status") == "success"}
            for info in checkpoint.get("files", []):
                if _key(info) not in successful:
                    continue
                try:
                    self._merge_files(run, [self._file_entry(run, info, config)])
                except (OSError, ValueError, DownloadNotFound):
                    continue
            if 'payment_binding' in config['datasets'] and len(config['cities']) > 1:
                for month in config['months']:
                    proof_path = directory / ('binding_summary_' + month + '.json')
                    try:
                        if proof_path.is_symlink() or proof_path.stat().st_size > 65536:
                            continue
                        proof = json.loads(proof_path.read_text(encoding='utf-8'))
                        info = proof['file']
                        included = proof['included_cities']
                        if (not included or info.get('artifact_role') != 'summary'
                                or info.get('start', '')[:7] != month
                                or any((city, 'payment_binding', info['start'], info['end']) not in successful for city in included)
                                or {source['city'] for source in proof['sources']} != set(included)):
                            continue
                        committed = {entry['city']: entry for entry in run['files']
                                     if entry.get('dataset') == 'payment_binding' and entry.get('start') == info['start']}
                        if any(committed.get(source['city'], {}).get('sha256') != source['sha256'] for source in proof['sources']):
                            continue
                        self._merge_files(run, [self._file_entry(run, info, config)])
                    except (OSError, ValueError, KeyError, TypeError, DownloadNotFound):
                        continue
            available = {_key(entry) for entry in run["files"]}
            for item in run["items"]:
                if _key(item) in available:
                    item.update(status="success", phase="completed", error="")
        except (OSError, ValueError, KeyError, TypeError, DownloadNotFound):
            return

    def _file_entry(self, run, info, config):
        if not isinstance(info, dict) or not isinstance(info.get("relative_path"), str):
            raise ValueError("下载文件清单无效")
        relative = Path(info["relative_path"])
        run_dir = self._archive_directory(run)
        path = (run_dir / relative).resolve()
        if (relative.is_absolute() or relative.drive or ".." in relative.parts
                or not path.is_relative_to(run_dir)):
            raise ValueError("下载文件归属无效")
        restored_id=None
        if not path.is_file() and run.get('result_layout')==3:
            published=self.deliveries.location(run['id'],info.get('id',''))
            path=published or self.deliveries.relocated(path) or path
            with self.deliveries.db() as db:
                identity=db.execute('SELECT file_id FROM artifacts WHERE run_id=? AND path=?',(run['id'],str(path))).fetchone()
                if identity:restored_id=identity['file_id']
        if not path.is_file():raise ValueError('下载文件不存在')
        is_summary = info.get('artifact_role') == 'summary'
        scope_error = delivery_scope_error(info, config, path.suffix)
        if scope_error:
            raise ValueError(scope_error)
        name = info.get("name") or path.name
        if not isinstance(name, str) or Path(name).name != name or any(char in name for char in ("\r", "\n", "\x00")):
            raise ValueError("下载文件名称无效")
        with path.open("rb") as stream:
            digest = hashlib.file_digest(stream, "sha256").hexdigest()
        if info.get("sha256") is not None and info["sha256"] != digest:
            raise ValueError("下载文件完整性无效")
        if run.get('result_layout') == 2:
            from task_catalog import GENERATORS
            category = '来源' if config.get('task_kind') == 'generate' and info['dataset'] not in GENERATORS else '结果'
            destination = run_dir / category / archive_component(info['city']) / name
            if path != destination:
                destination.parent.mkdir(parents=True, exist_ok=True)
                if destination.is_symlink():
                    raise DownloadArchiveError('同名结果已存在，未覆盖原文件')
                # Publication is the final registration step, after generators have
                # consumed their intermediate paths. Preserve intermediates for recovery.
                import shutil
                copied = not destination.exists()
                if copied:
                    shutil.copy2(path, destination)
                with destination.open('rb') as stream:
                    if hashlib.file_digest(stream, 'sha256').hexdigest() != digest:
                        if copied:
                            destination.unlink(missing_ok=True)
                        raise DownloadArchiveError('结果文件复制校验失败')
                path = destination
                relative = path.relative_to(run_dir)
        return {"id": restored_id or uuid.uuid4().hex, "name": name, "relative_path": str(relative), "sha256": digest,
                "city": info["city"], "dataset": info["dataset"], "start": info.get("start", ""),
                "end": info.get("end", ""), "bytes": path.stat().st_size,
                **({'delivery_kind': info['delivery_kind']} if info.get('delivery_kind') in ('platform_original','system_merged') else {}),
                **({'artifact_role': 'summary'} if is_summary else {})}

    def get_file(self, owner, run_id, file_id, verify_integrity=True):
        with self._lock, self._connection() as connection:
            _, run = self._find(connection, owner, run_id)
            entry = next((item for item in run["files"] if item["id"] == file_id), None)
            if entry is None:
                raise DownloadNotFound("下载文件不存在")
            path = self._artifact_path(run,entry)
            if not path.is_file():
                raise DownloadNotFound("下载文件不存在")
            if not verify_integrity:
                return path, path.name
            if path.stat().st_size != entry["bytes"]:
                raise DownloadNotFound("下载文件已变更")
            with path.open("rb") as stream:
                digest = hashlib.file_digest(stream, "sha256").hexdigest()
            if digest != entry.get("sha256"):
                raise DownloadNotFound("下载文件已变更")
            return path, path.name

    def get_raw_bundle(self, owner, run_id):
        with self._lock,self._connection() as connection:
            _,run=self._find(connection,owner,run_id)
            if run['status'] in ACTIVE_STATUSES: raise DownloadSummaryPending('任务执行中，请结束后领取后台原始包')
            run_directory=self._archive_directory(run)
            directory=run_directory/'原始资料'/'蓝橙'
        if not directory.is_dir() or directory.is_symlink(): raise DownloadNotFound('本任务暂无蓝橙后台原始资料')
        if not directory.resolve().is_relative_to(run_directory.resolve()):raise DownloadArchiveError('后台资料路径无效')
        sources=[]
        for source in directory.rglob('*'):
            if source.is_symlink(): raise DownloadArchiveError('后台资料含不安全路径，已停止打包')
            if source.is_file() and source.suffix.lower() in ('.xlsx','.json','.part'):
                if not source.resolve().is_relative_to(directory.resolve()): raise DownloadArchiveError('后台资料路径无效')
                sources.append(source)
        if not sources or len(sources)>20000: raise DownloadNotFound('后台原始资料为空或文件数量异常')
        bundle_root=self.db_path.parent/'bundles';bundle_root.mkdir(parents=True,exist_ok=True)
        handle,temporary=tempfile.mkstemp(prefix='raw_bundle_',suffix='.zip',dir=bundle_root);os.close(handle)
        target=Path(temporary)
        try:
            with zipfile.ZipFile(target,'w',zipfile.ZIP_DEFLATED,allowZip64=True) as archive:
                for source in sources:archive.write(source,str(source.relative_to(directory)))
            return target,'后台原始资料_'+run_id[:6].upper()+'.zip'
        except Exception:
            target.unlink(missing_ok=True);raise

    def get_bundle(self, owner, run_id, city=None):
        with self._lock,self._connection() as connection:
            _,current=self._find(connection,owner,run_id)
            flat=current.get('result_layout')==3
        if flat:
            from download_records import record_bundle
            return record_bundle(self,owner,run_id,city)
        with self._lock, self._connection() as connection:
            _, run = self._find(connection, owner, run_id)
            from lanorange_catalog import ALL_CITIES, DATASETS as blue
            blue_bundle = city == ALL_CITIES and any(entry['city'] == ALL_CITIES and entry['dataset'] in blue for entry in run['files'])
            if city is not None and city not in run["cities"] and not blue_bundle:
                raise DownloadNotFound("城市不属于本任务")
            entries = [entry for entry in run["files"] if city is None or entry["city"] == city]
            if not entries:
                raise DownloadNotFound("暂无已校验成品可领取")
            directory = self._archive_directory(run)
            snapshot = json.loads(json.dumps(run))
        bundle_root = self.db_path.parent / "bundles"
        bundle_root.mkdir(parents=True, exist_ok=True)
        handle, temporary = tempfile.mkstemp(prefix="bundle_", suffix=".zip", dir=bundle_root)
        os.close(handle)
        path = Path(temporary)
        try:
            # ZIP reading/compression never holds the queue's state lock.
            with tempfile.TemporaryDirectory(prefix="receipt_", dir=bundle_root) as receipt_dir:
                summary = write_download_summary(Path(receipt_dir), snapshot)
                with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED, compresslevel=6, allowZip64=True) as archive:
                    archive.write(summary, "下载说明.txt")
                    used = {"下载说明.txt"}
                    for entry in entries:
                        relative = Path(entry["relative_path"])
                        source,name = self.get_file(owner,run_id,entry['id'])
                        if (relative.is_absolute() or relative.drive or ".." in relative.parts
                                or not source.is_file()
                                or not isinstance(name, str) or Path(name).name != name
                                or any(char in name for char in '/\\:\r\n\x00')):
                            raise DownloadNotFound("成品文件归属发生变化，已停止打包")
                        archive_name = name
                        if archive_name.casefold() in {value.casefold() for value in used}:
                            raise DownloadNotFound("成品文件名冲突，已停止打包")
                        used.add(archive_name)
                        digest, size = hashlib.sha256(), 0
                        with source.open("rb") as original, archive.open(archive_name, "w", force_zip64=True) as destination:
                            while chunk := original.read(1024 * 1024):
                                destination.write(chunk)
                                digest.update(chunk)
                                size += len(chunk)
                        if size != entry["bytes"] or digest.hexdigest() != entry["sha256"]:
                            raise DownloadNotFound("成品文件已变更，已停止打包")
            suffix = archive_component(city) if city else "全部成品"
            return path, f"风神下载_{run.get('archive_code', run_id[:6].upper())}_{suffix}.zip"
        except BaseException:
            path.unlink(missing_ok=True)
            raise

    def _execute(self, run_id):
        queued_cancelled = False
        with self._lock, self._connection() as connection:
            row = connection.execute("SELECT * FROM download_runs WHERE id = ?", (run_id,)).fetchone()
            if row is None:
                return
            run = json.loads(row["state_json"])
            if run["status"] != "queued":
                self._events.pop(run_id, None)
                return
            owner, config = row["owner"], json.loads(row["config_json"])
            cancelled = self._events[run_id]
            if cancelled.is_set():
                run["status"] = "cancelled"
                for item in run["items"]:
                    item.update(status="cancelled", error="")
                _add_log(run, "排队中的任务已取消")
                _refresh(run)
                self._save(connection, run)
                queued_cancelled = True
            else:
                run["status"] = "running"
                run.update(phase="preparing", phase_since=_now(), last_activity_at=_now())
                _add_log(run, "开始执行下载任务")
                self._save(connection, run)
        if queued_cancelled:
            self._summary_best_effort(owner, run_id)
            return
        execution_started = time.perf_counter()
        queued_seconds = max(0, (dt.datetime.now(dt.timezone.utc) - dt.datetime.fromisoformat(run['created_at'])).total_seconds())
        summary_started = None
        files, error = [], ""
        summary_reported = False
        summary_active = False
        pending_logs, last_flush = [], 0.0
        pending_lock = threading.RLock()
        def flush_logs(force=False):
            nonlocal last_flush
            with pending_lock:
                now = time.monotonic()
                if not pending_logs or (not force and len(pending_logs) < 50 and now - last_flush < 0.25):
                    return
                entries = list(pending_logs)
                def append(run):
                    run["logs"] = (run["logs"] + entries)[-500:]
                self._mutate(owner, run_id, append)
                pending_logs.clear()
                last_flush = now
        def log(message, *args, **kwargs):
            safe_message = _safe_text(message, "部分诊断信息已隐藏")
            with pending_lock:
                pending_logs.append({"time": _now(), "message": safe_message})
                pending_logs[:] = pending_logs[-500:]
            # A human-verification wait may emit no further logs for minutes.
            # Publish its instructions before entering that wait, even when a
            # preceding progress line was flushed in the same batch interval.
            flush_logs(force=safe_message.startswith(("[等待", "[验证", "[登录]", "正在等待")))
        def update_item(change):
            flush_logs(force=True)
            self._update_item(owner, run_id, change)
        try:
            run_dir = self._archive_directory(run, create=True, exclusive=True)
            # Mixed generators may return to platform collection later, so they
            # keep the serial lane and reserve the heavy-task slot up front.
            from download_service import GENERATOR_DEPENDENCIES, LANORANGE_DATASETS
            selected = set(config['datasets'])
            if selected.intersection(GENERATOR_DEPENDENCIES) and not selected.issubset(set(LANORANGE_DATASETS) | {'abnormal_riders'}):
                from download_pipeline import reserve_local_work
                reserve_local_work()
            result = self.executor_fn({**config, "owner": owner, "archive_created_at": run["created_at"], 'result_layout': run.get('result_layout', 1)},
                                      run_dir, log, cancelled, update_item)
            if not isinstance(result, list):
                raise ValueError("下载文件清单无效")
            for info in result:
                try:
                    files.append(self._file_entry(run, info, config))
                except Exception as exc:
                    error = "部分下载文件未通过归属或完整性检查，已阻止提供下载"
                    log(f"成品校验未通过：{exc}")
            if not error and not cancelled.is_set():
                summary_config = {**config, "archive_created_at": run["created_at"]}
                with self._connection() as connection:
                    _, current = self._find(connection, owner, run_id)
                # 各城市成品已全部提交后，汇总合并可能持续数分钟且不产生子项更新；
                # 显式切换运行阶段并逐城市记录进展，避免界面停留在“下载中”。
                update_item({"_run_event": True, "status": "running", "phase": "summarizing"})
                log("[汇总] 各城市成品已提交，正在合并多城市资料并生成汇总文件")
                def summary_progress(current, total, city='', month=''):
                    nonlocal summary_reported
                    summary_reported = True
                    update_item({"_run_event": True, "status": "running", "phase": "summarizing",
                                 "summary_progress": {"stage": "merging", "current": current, "total": total,
                                                      "city": city, "month": month}})
                summary_started = time.perf_counter()
                from workbook_policy import compression
                with compression(6):
                    from binding_summary import build_binding_summaries
                    summary_active = 'payment_binding' in summary_config['datasets'] and len(summary_config['cities']) > 1
                    for info in build_binding_summaries(run_dir, summary_config, files, current['items'], cancelled,
                                                        report=log, progress=summary_progress):
                        files.append(self._file_entry(run, info, config))
                        log('[汇总] 多城市支付绑定已按月合并，成功城市明细与城市汇总已核对')
                    summary_active = False
                    if summary_reported:
                        update_item({"_run_event": True, "status": "running", "phase": "summarizing",
                                     "summary_progress": {"stage": "completed"}})
                    from abnormal_followup import build_followup_summaries
                    log("[汇总] 正在合并异常骑手跟进成品")
                    for info in build_followup_summaries(run_dir, summary_config, files, current['items'], cancelled):
                        files.append(self._file_entry(run, info, config))
                        log('[汇总] 多城市异常骑手跟进已按月合并')
                    from rider_monthly_summary import build_rider_monthly_summaries
                    summary_active = 'rider_monthly' in summary_config['datasets'] and len(summary_config['cities']) > 1
                    log("[汇总] 正在合并多城市风神骑手月度UB账单成品")
                    for info in build_rider_monthly_summaries(run_dir, summary_config, files,
                                                              current['items'], cancelled, report=log):
                        files.append(self._file_entry(run, info, config))
                        log('[汇总] 多城市风神骑手月度UB账单已按城市生成子表')
                    summary_active = False
        except Exception as exc:
            if summary_active:
                try:
                    update_item({"_run_event": True, "status": "running", "phase": "summarizing",
                                 "summary_progress": {"stage": "failed"}})
                except Exception:
                    pass
            error = _safe_exception(exc)
        flush_logs(force=True)
        locals_for_profile = {'run_dir': run_dir} if 'run_dir' in locals() else {}
        def finish(run):
            from generation_performance import public_profile
            if 'run_dir' in locals_for_profile:
                report = public_profile(locals_for_profile['run_dir'])
                if report:
                    report.update(total_seconds=round(time.perf_counter() - execution_started, 6),
                                  queued_seconds=round(queued_seconds, 6),
                                  summary_seconds=round(time.perf_counter() - summary_started, 6) if summary_started else 0)
                    from download_pipeline import pipeline_diagnostics
                    report['scheduler'] = pipeline_diagnostics()
                    run['performance'] = report
            # Keep each committed child result even if a later child raises.
            self._restore_checkpoint(run, config)
            self._merge_files(run, files)
            verified = []
            for entry in run["files"]:
                try:
                    self._file_entry(run, entry, config)
                    verified.append(entry)
                except (OSError, ValueError, DownloadNotFound):
                    continue
            run["files"] = verified
            success_keys = {_key(info) for info in verified}
            for item in run["items"]:
                if item["status"] == "error":
                    continue
                if item["status"] == "success":
                    if _key(item) not in success_keys:
                        item.update(status="error", error=error or "本项下载未生成可验证的文件，请重试")
                    continue
                if _key(item) in success_keys:
                    item.update(status="success", error="")
                elif cancelled.is_set():
                    item.update(status="cancelled", error="")
                else:
                    item.update(status="error", error=error or "本项下载未完成，请重试")
            success = any(item["status"] == "success" for item in run["items"])
            failed = any(item["status"] == "error" for item in run["items"])
            run["error"] = error or next((item["error"] for item in run["items"] if item["status"] == "error"), "")
            if cancelled.is_set():
                run["status"] = "cancelled"
            elif failed or error:
                run["status"] = "partial" if success else "error"
            else:
                run["status"] = "success"
            run.update(phase="completed" if run["status"] == "success" else "cancelled" if cancelled.is_set() else "failed",
                       phase_since=_now())
            _add_log(run, {"cancelled": "下载任务已取消，已完成的文件已保留", "success": "下载任务已完成",
                           "partial": "下载任务部分完成，请查看各项结果", "error": "下载任务失败，请查看错误提示"}[run["status"]])
            if run["status"] in ("error", "partial") and run["error"]:
                _add_log(run, "失败诊断：" + run["error"])
        self._mutate(owner, run_id, finish)
        self._summary_best_effort(owner, run_id)
        with self._lock:
            self._events.pop(run_id, None)

    def _worker(self):
        while True:
            run_id = self._queue.get()
            dispatched = False
            try:
                if run_id is None:
                    # Do not release the database instance lock while a local
                    # tail is still finishing or writing its checkpoint.
                    with self._lock:
                        threads = list(self._processing_threads)
                    for thread in threads:
                        thread.join()
                    self._instance_lock.release()
                    return
                self._inflight.acquire()
                released = threading.Event()
                thread = threading.Thread(target=self._processing_turn, args=(run_id, released),
                                          name='download-turn-' + run_id[:6], daemon=True)
                with self._lock:
                    self._processing_threads.add(thread)
                try:
                    dispatched = True
                    thread.start()
                except BaseException:
                    dispatched = False
                    with self._lock:
                        self._processing_threads.discard(thread)
                    self._inflight.release()
                    raise
                # Only the audited pure-blue local tail can release this early.
                # Otherwise preserve the previous whole-task serial behavior.
                released.wait()
            except Exception as exc:
                self._fail_processing_turn(run_id, exc)
                with self._lock:
                    self._events.pop(run_id, None)
            finally:
                if not dispatched:
                    self._queue.task_done()

    def _processing_turn(self, run_id, released):
        from download_pipeline import PipelineTurn, pipeline_scope
        def handoff():
            with self._lock:
                self._collection_released.add(run_id)
            released.set()
        try:
            with self._lock:
                cancelled = self._events.get(run_id, threading.Event())
            with pipeline_scope(PipelineTurn(self._local_gate, handoff, cancelled)):
                self._execute(run_id)
        except Exception as exc:
            self._fail_processing_turn(run_id, exc)
        finally:
            with self._lock:
                self._events.pop(run_id, None)
                self._collection_released.discard(run_id)
                self._processing_threads.discard(threading.current_thread())
            self._inflight.release()
            released.set()
            self._queue.task_done()

    def _fail_processing_turn(self, run_id, exc):
        # A storage/thread failure must not kill the dispatcher or leak details.
        safe_error = _safe_exception(exc)
        try:
            with self._lock, self._connection() as connection:
                row = connection.execute("SELECT owner FROM download_runs WHERE id = ?", (run_id,)).fetchone()
            if row:
                def fail(run):
                    run.update(status="error", error=safe_error)
                    _add_log(run, safe_error)
                self._mutate(row["owner"], run_id, fail)
                self._summary_best_effort(row["owner"], run_id)
        except Exception:
            pass

    def shutdown(self, wait=True):
        with self._lock:
            if not self._closed:
                self._closed = True
                for event in self._events.values():
                    event.set()
                self._queue.put(None)
        if wait and threading.current_thread() is not self._thread:
            self._thread.join(timeout=5)


_manager = None
_manager_lock = threading.Lock()


def get_manager():
    global _manager
    with _manager_lock:
        if _manager is None:
            _manager = DownloadManager(Path(__file__).parent / ".local_downloads" / "tasks.sqlite3",
                                       configured_output_root())
            atexit.register(_manager.shutdown, False)
        return _manager


def shutdown_manager():
    with _manager_lock:
        if _manager is not None:
            _manager.shutdown()
