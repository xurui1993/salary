"""Task-local measurements and bounded, content-addressed parsing reuse."""
from collections import OrderedDict
from concurrent.futures import Future
from contextlib import contextmanager, nullcontext
from contextvars import ContextVar
from functools import wraps
import hashlib
import json
import os
import re
from pathlib import Path
import threading
import tempfile
import uuid
import time

from workbook_policy import compression

_profile = ContextVar('generation_profile', default=None)
_cache = ContextVar('generation_source_cache', default=None)
_exchange = ContextVar('generation_table_exchange', default=None)
_slots = threading.BoundedSemaphore(2)


class _SpilledStringFrame:
    """Task-owned CSV; no executable serialization or cross-task persistence."""
    def __init__(self, path, frame):
        self.path = path
        self.columns = tuple(frame.columns)
        self.dtypes = frame.dtypes.to_dict()
        self.rows = len(frame)
        self.index_name, self.columns_name = frame.index.name, frame.columns.name
        self.size = path.stat().st_size
        with path.open('rb') as stream:
            self.sha256 = hashlib.file_digest(stream, 'sha256').hexdigest()

    def copy(self, deep=True):
        import pandas as pd
        with self.path.open('rb') as stream:
            digest = hashlib.file_digest(stream, 'sha256').hexdigest()
            if digest != self.sha256:
                raise ValueError('任务临时资料缓存已变化，停止复用')
            stream.seek(0)
            frame = pd.read_csv(stream, encoding='utf-8', dtype=self.dtypes,
                                keep_default_na=False, skip_blank_lines=False)
            stream.seek(0)
            if hashlib.file_digest(stream, 'sha256').hexdigest() != digest:
                raise ValueError('任务临时资料缓存读取期间发生变化，停止复用')
        if tuple(frame.columns) != self.columns or len(frame) != self.rows:
            raise ValueError('任务临时资料缓存结构变化，停止复用')
        frame.index.name, frame.columns.name = self.index_name, self.columns_name
        return frame


class SourceCache:
    """Never crosses task/account boundaries; callers receive mutable copies."""
    def __init__(self, max_bytes=64 * 1024 * 1024, reuse_tables=True, spill_frames=False, spill_max_bytes=256 * 1024 * 1024):
        self.spill_frames, self.spill_limit = spill_frames, spill_max_bytes
        self.spill_bytes = self.spill_reserved = self.spill_files = 0
        self.spill_directory = None
        self.reuse_tables = reuse_tables
        self.limit = max_bytes
        self.entries, self.pending = OrderedDict(), {}
        self.bytes = self.hits = self.misses = 0
        self.handoff_bytes = self.handoff_peak = 0
        self.lock = threading.Lock()

    def _value(self, path, variant, loader, sizer):
        path = Path(path).resolve()
        with path.open('rb') as stream:
            key = (hashlib.file_digest(stream, 'sha256').hexdigest(), variant)
        with self.lock:
            if key in self.entries:
                value, _ = self.entries[key]; self.entries.move_to_end(key); self.hits += 1
                return value
            owner = key not in self.pending
            if owner:
                self.pending[key] = Future(); self.misses += 1
            else:
                self.hits += 1
            pending = self.pending[key]
        if not owner:
            return pending.result()
        try:
            value = loader(str(path))
            with path.open('rb') as stream:
                if hashlib.file_digest(stream, 'sha256').hexdigest() != key[0]:
                    from fengshen_bill import BillCollectionError
                    raise BillCollectionError('来源资料在读取期间发生变化，已停止本次生成')
            size = int(sizer(value))
            with self.lock:
                if size <= self.limit:
                    while self.entries and self.bytes + size > self.limit:
                        _, (_, removed) = self.entries.popitem(last=False); self.bytes -= removed
                    self.entries[key] = (value, size); self.bytes += size
                pending.set_result(value)
                self.pending.pop(key, None)
            return value
        except BaseException as error:
            with self.lock:
                pending.set_exception(error); self.pending.pop(key, None)
            raise

    def _maybe_spill(self, frame):
        size = int(frame.memory_usage(index=True, deep=True).sum())
        if not self.spill_frames or size <= self.limit:
            return frame
        import pandas as pd
        if (not isinstance(frame.index, pd.RangeIndex) or frame.index.start != 0 or frame.index.step != 1
                or not frame.columns.is_unique or not all(isinstance(c, str) and c and '\x00' not in c and not c.startswith('\ufeff') for c in frame.columns)
                or not all(isinstance(v, str) and '\x00' not in v for v in frame.to_numpy().flat)):
            return frame
        with self.lock:
            if size + self.spill_bytes + self.spill_reserved > self.spill_limit:
                return frame
            try:
                if self.spill_directory is None:
                    self.spill_directory = tempfile.TemporaryDirectory(prefix='payroll_source_cache_')
                path = Path(self.spill_directory.name) / (uuid.uuid4().hex + '.csv')
            except OSError:
                return frame
            self.spill_reserved += size
        try:
            frame.to_csv(path, index=False, encoding='utf-8', mode='x')
            value = _SpilledStringFrame(path, frame)
            with self.lock:
                if value.size + self.spill_bytes > self.spill_limit:
                    path.unlink(missing_ok=True)
                    return frame
                self.spill_bytes += value.size
                self.spill_files += 1
            return value
        except (OSError, ValueError, TypeError):
            try:
                path.unlink(missing_ok=True)
            except OSError:
                pass
            return frame
        finally:
            with self.lock:
                self.spill_reserved -= size

    def read(self, path, loader):
        # Keep every original column. Large all-string frames can reuse a checked
        # task-private CSV rather than repeatedly parsing the same Excel workbook.
        value = self._value(path, ('frame', Path(path).name),
                            lambda file: self._maybe_spill(loader(file)),
                            lambda frame: 4096 if isinstance(frame, _SpilledStringFrame)
                            else frame.memory_usage(index=True, deep=True).sum())
        return value.copy(deep=True)

    def close(self):
        directory, self.spill_directory = self.spill_directory, None
        if directory is not None:
            try:
                directory.cleanup()
            except OSError:
                pass

    def immutable(self, path, variant, loader):
        return self._value(path, variant, loader, lambda value: value.nbytes)

    def summary(self):
        with self.lock:
            return {'hits': self.hits, 'misses': self.misses, 'retained_bytes': self.bytes,
                    'limit_bytes': self.limit, 'handoff_bytes': self.handoff_bytes,
                    'handoff_peak_bytes': self.handoff_peak, 'spill_files': self.spill_files,
                    'spill_bytes': self.spill_bytes, 'spill_limit_bytes': self.spill_limit}


class TableExchange(dict):
    """All queued city/month handoffs share one task-level retention budget."""
    def __init__(self, cache):
        super().__init__()
        self.cache, self.reserved = cache, 0

    @property
    def available_bytes(self):
        with self.cache.lock:
            return max(0, self.cache.limit - self.cache.handoff_bytes)

    def update(self, value):
        size = value.get('_retained_bytes', 0)
        if not value.get('tables'):
            return
        with self.cache.lock:
            if self.cache.handoff_bytes + size > self.cache.limit:
                return
            self.cache.handoff_bytes += size
            self.cache.handoff_peak = max(self.cache.handoff_peak, self.cache.handoff_bytes)
            self.reserved += size
        super().update(value)

    def clear(self):
        super().clear()
        with self.cache.lock:
            self.cache.handoff_bytes -= self.reserved
            self.reserved = 0


class Profile:
    def __init__(self, name, directory):
        self.name, self.directory = name, Path(directory)
        self.started = time.perf_counter()
        self.stages = {}
        self.phase = None
        self.phase_started = self.started
        self.peak_rss = 0
        self.lock = threading.Lock()
        self.stopped = threading.Event()
        self.sampler = threading.Thread(target=self._sample, daemon=True)

    def _sample(self):
        try:
            import psutil
            process = psutil.Process()
            while True:
                self.peak_rss = max(self.peak_rss, process.memory_info().rss)
                if self.stopped.wait(.1):
                    return
        except Exception:
            return

    def add(self, name, seconds):
        with self.lock:
            row = self.stages.setdefault(name, {'seconds': 0, 'calls': 0})
            row['seconds'] += seconds; row['calls'] += 1

    def transition(self, phase):
        now = time.perf_counter()
        if phase == self.phase:
            return
        if self.phase:
            self.add('phase:' + self.phase, now - self.phase_started)
        self.phase, self.phase_started = phase, now

    def finish(self, failed):
        if self.phase:
            self.add('phase:' + self.phase, time.perf_counter() - self.phase_started)
        self.stopped.set(); self.sampler.join(timeout=1)
        value = {'version': 1, 'name': self.name, 'elapsed_seconds': round(time.perf_counter() - self.started, 6),
                 'sampled_process_peak_rss_bytes': self.peak_rss, 'failed': failed,
                 'stages': {key: {'seconds': round(row['seconds'], 6), 'calls': row['calls']}
                            for key, row in self.stages.items()}}
        if re.fullmatch(r'\d{4}-\d{2}', self.directory.name) and self.directory.parent.name == self.name:
            value['scope'] = {'city': self.directory.parent.parent.name, 'month': self.directory.name}
        cache = _cache.get()
        if cache:
            value['source_cache'] = cache.summary()
        if self.name == 'download_task':
            children = []
            for file in (self.directory / '原始资料').rglob('performance.json'):
                try:
                    if file.is_symlink() or file.stat().st_size > 128 * 1024:
                        continue
                    child = json.loads(file.read_text(encoding='utf-8'))
                    if child.get('name') in ('payment_binding', 'abnormal_followup', 'abnormal_riders'):
                        children.append({key: child[key] for key in ('name', 'elapsed_seconds', 'stages', 'scope') if key in child})
                except (OSError, ValueError, TypeError, KeyError):
                    continue
            value['generators'] = children
            orders = []
            for file in (self.directory / '原始资料').glob('*/order_processed/performance.json'):
                try:
                    if file.is_symlink() or file.stat().st_size > 128 * 1024:
                        continue
                    report = json.loads(file.read_text(encoding='utf-8'))
                    orders.append({key: report[key] for key in ('collection_seconds', 'parser_seconds',
                                  'finalize_seconds', 'timings') if key in report})
                except (OSError, ValueError, TypeError):
                    continue
            value['order_pipelines'] = orders
        # Diagnostics must never mask a successful result or the original failure.
        try:
            from fengshen_bill import atomic_json
            self.directory.mkdir(parents=True, exist_ok=True)
            atomic_json(self.directory / 'performance.json', value)
        except Exception:
            pass


@contextmanager
def stage(name):
    start = time.perf_counter()
    try:
        yield
    finally:
        value = _profile.get()
        if value:
            value.add(name, time.perf_counter() - start)


def measured(name):
    def decorate(function):
        @wraps(function)
        def run(*args, **kwargs):
            with stage(name):
                return function(*args, **kwargs)
        return run
    return decorate


def profiled(name, output_index, output_name):
    def decorate(function):
        @wraps(function)
        def run(*args, **kwargs):
            directory = args[output_index] if len(args) > output_index else kwargs[output_name]
            profile = Profile(name, directory)
            profile.sampler.start()
            token = _profile.set(profile)
            parent_cache = _cache.get()
            active_cache = parent_cache or SourceCache(reuse_tables=name == 'download_task', spill_frames=name == 'download_task')
            cache_token = _cache.set(active_cache)
            failed = True
            try:
                with (_slots if name != 'download_task' else nullcontext()), compression(9 if name == 'download_task' else int(os.environ.get('PAYROLL_GENERATION_COMPRESSION', '6'))):
                    result = function(*args, **kwargs)
                    failed = False
                    return result
            finally:
                try:
                    profile.finish(failed)
                except Exception:
                    # Measurements are best effort, including child-report scanning.
                    profile.stopped.set()
                finally:
                    _cache.reset(cache_token); _profile.reset(token)
                    if parent_cache is None:
                        active_cache.close()
        return run
    return decorate


def transition(phase):
    if _profile.get():
        _profile.get().transition(phase)


def read_frame(path, loader):
    with stage('read_sources'):
        cache = _cache.get()
        return cache.read(path, loader) if cache else loader(str(path))


def shared_cache():
    return _cache.get()


@contextmanager
def generation_context(cache, exchange=None):
    token = _cache.set(cache)
    exchange_token = _exchange.set(exchange)
    try:
        yield
    finally:
        _exchange.reset(exchange_token); _cache.reset(token)


def capture_tables():
    return _exchange.get()


def public_profile(directory):
    try:
        file = Path(directory) / 'performance.json'
        if file.is_symlink() or file.stat().st_size > 128 * 1024:
            return None
        value = json.loads(file.read_text(encoding='utf-8'))
        if value.get('version') != 1 or not isinstance(value.get('stages'), dict):
            return None
        return value
    except (OSError, ValueError, TypeError):
        return None
