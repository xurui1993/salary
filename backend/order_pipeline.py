"""One local parser process overlaps serial platform collection.

Historical cache contains validated source records, never calculated penalties,
sessions or signed URLs. Today's records are always obtained from the platform.
"""
from concurrent.futures import Future, ProcessPoolExecutor, TimeoutError as FutureTimeout
from contextlib import contextmanager
import datetime as dt
import gzip
import hashlib
import io
import json
import multiprocessing
from pathlib import Path
import sqlite3
import time
from types import SimpleNamespace

import pandas as pd

from fengshen_bill import BillCollectionError, atomic_json
from fengshen_orders import SHANGHAI
from order_metrics import measured, measurements, worker_measurements
from order_dates import natural_dates
from order_sources import (prepare_order_slice, validate_slice, WAYBILL_COLUMNS,
                           VIOLATION_COLUMNS, file_hash, merge_slices)

SCHEMA_VERSION = "orders-source-v2"
CACHE_SECONDS = 24 * 60 * 60


def _json_default(value):
    if isinstance(value, (dt.datetime, dt.date)):
        return {"$date": value.isoformat(), "$kind": type(value).__name__}
    if hasattr(value, "item"):
        return value.item()
    raise TypeError("原始表格包含不支持的单元格类型")


def _json_hook(value):
    if set(value) == {"$date", "$kind"}:
        return (dt.date.fromisoformat(value["$date"]) if value["$kind"] == "date"
                else dt.datetime.fromisoformat(value["$date"]))
    return value


FRAME_VERSION = "orders-blocks-v1"
FRAME_BLOCK_ROWS = 10000


def _write_frame(frame, stream):
    # Bounded blocks eliminate one JSON encoder/decoder call per source row.
    stream.write((json.dumps({"format": FRAME_VERSION, "columns": list(frame.columns)}, ensure_ascii=False) + "\n").encode())
    rows = []
    for row in frame.itertuples(index=False, name=None):
        rows.append(row)
        if len(rows) >= FRAME_BLOCK_ROWS:
            stream.write((json.dumps(rows, ensure_ascii=False, default=_json_default) + "\n").encode())
            rows = []
    if rows:
        stream.write((json.dumps(rows, ensure_ascii=False, default=_json_default) + "\n").encode())


def _read_frame(stream, checkpoint=None):
    header = json.loads(stream.readline())
    legacy = isinstance(header, list)
    if not legacy and (not isinstance(header, dict) or header.get("format") != FRAME_VERSION):
        raise ValueError("缓存格式版本异常")
    columns = header if legacy else header.get("columns")
    if not isinstance(columns, list) or not all(isinstance(value, str) for value in columns) or len(columns) != len(set(columns)):
        raise ValueError("缓存表头异常")
    chunks, rows = [], []
    for number, line in enumerate(stream):
        if checkpoint is not None and (not legacy or number % 1000 == 0):
            checkpoint()
        block = json.loads(line, object_hook=_json_hook)
        block = [block] if legacy else block
        if not isinstance(block, list) or (not legacy and len(block) > FRAME_BLOCK_ROWS):
            raise ValueError("缓存数据块异常")
        for row in block:
            if not isinstance(row, list) or len(row) != len(columns):
                raise ValueError("缓存记录异常")
            rows.append(row)
            if len(rows) >= FRAME_BLOCK_ROWS:
                chunks.append(pd.DataFrame(rows, columns=columns, dtype=object))
                rows = []
    if rows:
        chunks.append(pd.DataFrame(rows, columns=columns, dtype=object))
    return pd.concat(chunks, ignore_index=True).infer_objects() if chunks else pd.DataFrame(columns=columns)


class PreparedSlices:
    """Keep receipts, not decoded frames, until one source kind is needed."""
    def __init__(self, references, include_violations, checkpoint=lambda: None, timings=None):
        self.references = references
        self.include_violations = include_violations
        self.checkpoint = checkpoint
        self.timings = timings if timings is not None else {}

    def __len__(self):
        return len(self.references)

    def proof(self, number):
        return self.references[number]["proof"]

    def _load(self, ref, kind):
        self.checkpoint()
        started = time.perf_counter()
        path = ref["files"][kind]
        if file_hash(path) != ref["hashes"][kind]:
            raise BillCollectionError("本地预处理文件完整性校验失败")
        try:
            return load_frame(path, checkpoint=self.checkpoint)
        finally:
            self.timings["load_seconds"] = self.timings.get("load_seconds", 0) + time.perf_counter() - started

    def __getitem__(self, number):
        ref = self.references[number]
        return {"waybills": self._load(ref, "waybills"),
                "violations": self._load(ref, "violations") if self.include_violations else None,
                "proof": ref["proof"]}

    def merge(self, kind):
        frames = []
        try:
            for ref in self.references:
                frames.append(self._load(ref, kind))
            return merge_slices(frames, "运单id" if kind == "waybills" else "违规编号")
        finally:
            frames.clear()


@measured("spool_write_seconds")
def dump_frame(frame, path):
    with gzip.open(path, "wb", compresslevel=1) as stream:
        _write_frame(frame, stream)


@measured("spool_read_seconds")
def load_frame(path, *, checkpoint=None):
    with gzip.open(path, "rb") as stream:
        return _read_frame(stream, checkpoint=checkpoint)


class CacheMiss(BillCollectionError):
    pass


class OrderCache:
    def __init__(self, path, *, today=None, clock=time.time):
        self.path, self.clock = Path(path), clock
        self.today = today or dt.datetime.now(SHANGHAI).date().isoformat()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.execute("CREATE TABLE IF NOT EXISTS slices (agency TEXT,day TEXT,kind TEXT,version TEXT,"
                       "captured REAL,payload BLOB,digest TEXT,rows INTEGER,source_json TEXT,"
                       "PRIMARY KEY(agency,day,kind,version))")
            db.execute("DELETE FROM slices WHERE captured < ?", (self.clock() - 7 * CACHE_SECONDS,))

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=30)
        try:
            db.row_factory = sqlite3.Row
            with db:
                yield db
        finally:
            db.close()

    @measured("cache_read_seconds")
    def get(self, agency, day, kind, *, decode=True):
        if day >= self.today:
            raise CacheMiss("当天资料必须刷新")
        with self.connect() as db:
            row = db.execute("SELECT * FROM slices WHERE agency=? AND day=? AND kind=? AND version=?",
                             (agency, day, kind, SCHEMA_VERSION)).fetchone()
        if (row is None or not 0 <= self.clock() - row["captured"] < CACHE_SECONDS
                or hashlib.sha256(row["payload"]).hexdigest() != row["digest"]):
            raise CacheMiss("历史缓存缺失、过期或完整性校验失败")
        if not decode:
            return None
        try:
            with gzip.GzipFile(fileobj=io.BytesIO(row["payload"]), mode="rb") as stream:
                frame = _read_frame(stream)
            required = WAYBILL_COLUMNS if kind == "waybills" else VIOLATION_COLUMNS
            if not required.issubset(frame.columns) or len(frame) != row["rows"]:
                raise ValueError()
            request = SimpleNamespace(start=day, end=day, agency_id=agency)
            frame = validate_slice(frame, request, "运单完成时间" if kind == "waybills" else "违规时间",
                                  ("运单id", "骑手id") if kind == "waybills" else ("违规编号", "运单号", "骑手ID"))
            frame.attrs["cache_order"] = json.loads(row["source_json"])
            return frame
        except Exception:
            raise CacheMiss("历史缓存内容校验失败，需重新获取") from None

    @measured("cache_write_seconds")
    def put(self, agency, day, kind, frame, captured, source):
        if day >= self.today or not 0 <= self.clock() - captured < CACHE_SECONDS:
            return
        buffer = io.BytesIO()
        with gzip.GzipFile(fileobj=buffer, mode="wb", compresslevel=1) as stream:
            _write_frame(frame, stream)
        payload = buffer.getvalue()
        with self.connect() as db:
            db.execute("INSERT OR REPLACE INTO slices VALUES(?,?,?,?,?,?,?,?,?)",
                       (agency, day, kind, SCHEMA_VERSION, captured, payload,
                        hashlib.sha256(payload).hexdigest(), len(frame), json.dumps(source)))

    def available(self, agency, day, include_violations):
        try:
            for kind in (("waybills", "violations") if include_violations else ("waybills",)):
                self.get(agency, day, kind, decode=False)
            return True
        except CacheMiss:
            return False


def _days(start, end):
    first, last = dt.date.fromisoformat(start), dt.date.fromisoformat(end)
    return [(first + dt.timedelta(days=n)).isoformat() for n in range((last - first).days + 1)]


@worker_measurements
def _worker_prepare(download, raw, plan_data, include_violations, spool, cache_path, today, cancel_path):
    def checkpoint():
        if Path(cancel_path).exists():
            raise BillCollectionError("任务已取消")
    checkpoint()
    started = time.perf_counter()
    plan = SimpleNamespace(**plan_data)
    prepared = prepare_order_slice(download, raw, plan, download["start"], download["end"], include_violations,
                                   checkpoint=checkpoint)
    cache = OrderCache(cache_path, today=today)
    source_dir = Path(raw) / "issue_orders" / (download["start"] + "_" + download["end"])
    captured = min((source_dir / name).stat().st_mtime for name in download["files"].values())
    source = {"task_id": download.get("task_id"), "file_checks": download["file_checks"]}
    files = {}
    for kind in (("waybills", "violations") if include_violations else ("waybills",)):
        if Path(cancel_path).exists():
            raise BillCollectionError("任务已取消")
        frame = prepared[kind]
        date_values = natural_dates(frame["运单完成时间" if kind == "waybills" else "违规时间"])
        for day in _days(download["start"], download["end"]):
            selected = date_values.eq(day)
            cache.put(plan.agency_id, day, kind, frame.loc[selected], captured,
                      {**source, "batch": download["start"] + "_" + download["end"],
                       "positions": [int(index) for index in frame.index[selected]]})
        path = Path(spool) / (download["start"] + "_" + download["end"] + "_" + kind + ".json.gz")
        dump_frame(frame, path)
        files[kind] = str(path)
    return {"files": files, "hashes": {kind: file_hash(path) for kind, path in files.items()},
            "proof": prepared["proof"], "seconds": time.perf_counter() - started}


@worker_measurements
def _cached_prepare(cache_path, today, plan_data, include_violations, spool):
    plan = SimpleNamespace(**plan_data)
    cache = OrderCache(cache_path, today=today)
    days, frames, counts = _days(plan.start, plan.end), {}, {}
    for kind in (("waybills", "violations") if include_violations else ("waybills",)):
        pieces = [cache.get(plan.agency_id, day, kind) for day in days]
        if kind == "waybills":
            counts = dict(zip(days, map(len, pieces)))
        ordered = []
        for piece, day in zip(pieces, days):
            order = piece.attrs.get("cache_order", {})
            positions = order.get("positions", list(range(len(piece))))
            if len(positions) != len(piece):
                raise CacheMiss("历史缓存排序信息损坏")
            piece.attrs = {}
            piece["__source_batch"] = order.get("batch", day)
            piece["__source_position"] = positions
            ordered.append(piece)
        frame = pd.concat(ordered, ignore_index=True).sort_values(["__source_batch", "__source_position"], kind="stable")
        frame = frame.drop(columns=["__source_batch", "__source_position"]).reset_index(drop=True)
        frame = merge_slices([frame], "运单id" if kind == "waybills" else "违规编号")
        path = Path(spool) / (plan.start + "_" + plan.end + "_" + kind + ".json.gz")
        dump_frame(frame, path)
        frames[kind] = str(path)
    return {"files": frames, "hashes": {kind: file_hash(path) for kind, path in frames.items()},
            "counts": counts, "proof": {"start": plan.start, "end": plan.end,
             "waybills": sum(counts.values()), "count_basis": "daily_verified", "query_total": sum(counts.values()),
             "batch_total_inconsistent": False, **({"violations": len(frame)} if include_violations else {})}, "seconds": 0}


class OrderPipeline:
    def __init__(self, raw, plan, selected, cache_path, cancelled, progress=lambda _: None, *, refresh=False):
        self.raw, self.plan, self.selected = Path(raw), plan, selected
        self.include_violations, self.cancelled, self.progress = "problem" in selected, cancelled, progress
        self.cache = OrderCache(cache_path)
        self.refresh = refresh
        self.spool = self.raw / "order_processed" / "prepared"
        self.spool.mkdir(parents=True, exist_ok=True)
        self.cancel_path = self.spool / ".cancelled"
        self.metrics = {"batches": 0, "downloaded": 0, "processed": 0, "cached_days": 0,
                        "obtained": 0, "download_bytes": 0, "processed_rows": 0, "stage": "collecting",
                        "collection_seconds": 0, "cache_seconds": 0}
        self.started = time.perf_counter()
        self.references, self.downloads, self.futures = [], [], []

    def emit(self, stage=None):
        if stage:
            self.metrics["stage"] = stage
        ready = [future.result() for future in self.futures if future.done() and not future.cancelled()]
        self.metrics.update(processed=len(ready), processed_rows=sum(x["proof"]["waybills"] for x in ready),
                            elapsed_seconds=round(time.perf_counter() - self.started, 1))
        self.progress(dict(self.metrics))

    def segments(self):
        segments = []
        for day in _days(self.plan.start, self.plan.end):
            cached = not self.refresh and self.cache.available(self.plan.agency_id, day, self.include_violations)
            if segments and segments[-1][2] == cached and len(_days(segments[-1][0], day)) <= 5:
                segments[-1] = (segments[-1][0], day, cached)
            else:
                segments.append((day, day, cached))
        return segments

    def _wait(self, future):
        while True:
            if self.cancelled.is_set():
                self.cancel_path.touch()
                raise BillCollectionError("任务已取消")
            try:
                return future.result(timeout=.5)
            except FutureTimeout:
                self.emit("processing")

    def collect(self, runner):
        segments = self.segments()
        self.metrics["batches"] = len(segments)
        executor = ProcessPoolExecutor(max_workers=1, mp_context=multiprocessing.get_context("spawn"))
        try:
            for number, (first, last, cached) in enumerate(segments, 1):
                if self.cancelled.is_set():
                    raise BillCollectionError("任务已取消")
                pending = [future for future in self.futures if not future.done()]
                if len(pending) >= 2:
                    self._wait(pending[0])
                self.metrics["batch"] = number
                self.emit("collecting")  # Also surfaces a completed worker failure before another export.
                plan = SimpleNamespace(**{**vars(self.plan), "start": first, "end": last})
                reference = None
                if cached:
                    cache_started = time.perf_counter()
                    future = executor.submit(_cached_prepare, str(self.cache.path), self.cache.today,
                                             vars(plan), self.include_violations, str(self.spool))
                    try:
                        reference = self._wait(future)
                    except CacheMiss:
                        cached = False
                    self.metrics["cache_seconds"] += time.perf_counter() - cache_started
                if cached:
                    directory = self.raw / "issue_orders" / (first + "_" + last)
                    directory.mkdir(parents=True, exist_ok=False)
                    manifest = {"dataset": "issue_orders", "transport": "history_cache", "status": "success",
                        "agency_id": plan.agency_id, "start": first, "end": last, "time_basis": "tracking_finish",
                        "merchant_group": "物流合作商", "all_city_riders": True, "cache_derived": True,
                        "expected_waybills": reference["proof"]["waybills"],
                        "expected_waybills_by_date": reference["counts"], "cache_ttl_seconds": CACHE_SECONDS}
                    atomic_json(directory / "manifest.json", manifest)
                    self.metrics["cached_days"] += len(_days(first, last))
                    ready_future = Future()
                    ready_future.set_result(reference)
                    self.futures.append(ready_future)
                else:
                    collection_started = time.perf_counter()
                    with measurements(self.metrics.setdefault("timings", {})):
                        manifests = runner.orders_batch(plan, self.raw / "issue_orders", self.selected)
                    self.metrics["collection_seconds"] += time.perf_counter() - collection_started
                    if len(manifests) != 1:
                        raise BillCollectionError("流水处理批次与平台下载不一致")
                    manifest = manifests[0]
                    self.metrics["downloaded"] += 1
                    self.metrics["download_bytes"] += sum(x["bytes"] for x in manifest["file_checks"].values())
                    self.futures.append(executor.submit(_worker_prepare, manifest, str(self.raw), vars(plan),
                        self.include_violations, str(self.spool), str(self.cache.path), self.cache.today, str(self.cancel_path)))
                self.downloads.append(manifest)
                self.metrics["obtained"] += 1
                self.emit()
            self.references = [self._wait(future) for future in self.futures]
        finally:
            if self.cancelled.is_set():
                self.cancel_path.touch()
            executor.shutdown(wait=True, cancel_futures=True)
        self.emit("merging")
        load_started = time.perf_counter()
        prepared = self.load_prepared()
        self.metrics["receipt_check_seconds"] = time.perf_counter() - load_started
        self.finalize_started = time.perf_counter()
        return self.downloads, prepared, [(value["start"], value["end"]) for value in self.downloads]

    def load_prepared(self):
        # Validate all receipts now; validate each file again at its actual use.
        for ref in self.references:
            for kind, path in ref["files"].items():
                if file_hash(path) != ref["hashes"][kind]:
                    raise BillCollectionError("本地预处理文件完整性校验失败")
        def checkpoint():
            cancelled = getattr(self, "cancelled", None)
            if cancelled is not None and cancelled.is_set():
                raise BillCollectionError("任务已取消")
        return PreparedSlices(self.references, self.include_violations, checkpoint,
                              getattr(self, "metrics", None))

    def complete(self):
        self.metrics["finalize_seconds"] = time.perf_counter() - self.finalize_started
        timings = self.metrics.setdefault("timings", {})
        for reference in self.references:
            for name, seconds in reference.get("timings", {}).items():
                timings[name] = timings.get(name, 0) + seconds
        self.emit("completed")
        atomic_json(self.raw / "order_processed" / "performance.json", {
            **self.metrics, "parser_seconds": round(sum(x["seconds"] for x in self.references), 3)})


