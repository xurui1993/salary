"""Process entry points for per-city payment-binding and abnormal-followup generation."""
from pathlib import Path
from types import SimpleNamespace


class _NotCancelled:
    # 进程内无共享取消事件；支持通过文件标记传递取消信号。
    @staticmethod
    def is_set():
        return False


class _FlagCancelled:
    def __init__(self, path):
        self.path = Path(path)

    def is_set(self):
        return self.path.exists()


_WORKER_CACHE_KEY = None
_WORKER_CACHE = None


def _worker_cache(task_key):
    """同一任务在子进程内跨城市复用公共大表缓存，跨任务立即隔离销毁。"""
    global _WORKER_CACHE_KEY, _WORKER_CACHE
    from generation_performance import SourceCache

    if not task_key:
        return SourceCache(
            max_bytes=256 * 1024 * 1024,
            reuse_tables=True,
            spill_frames=True,
            spill_max_bytes=384 * 1024 * 1024,
        ), True
    if _WORKER_CACHE is not None and _WORKER_CACHE_KEY == task_key:
        return _WORKER_CACHE, False
    if _WORKER_CACHE is not None:
        _WORKER_CACHE.close()
    _WORKER_CACHE = SourceCache(
        max_bytes=256 * 1024 * 1024,
        reuse_tables=True,
        spill_frames=True,
        spill_max_bytes=384 * 1024 * 1024,
    )
    _WORKER_CACHE_KEY = task_key
    return _WORKER_CACHE, False


def _cancelled_for(spec):
    return _FlagCancelled(spec['cancel_file']) if spec.get('cancel_file') else _NotCancelled()


def _make_logger(logs):
    def log(message, *args, **kwargs):
        safe = tuple(
            value if isinstance(value, (str, int, float, bool, type(None))) else str(value)
            for value in args
        )
        logs.append((str(message), safe, {}))
    return log


def filter_sources(spec, log):
    """取分离过滤随生成一起下沉到子进程，父进程不再串行阻塞提交。"""
    from separation_filter import COLUMNS, filter_table
    include = spec.get('separation_include')
    paths = {kind: Path(value) for kind, value in spec['paths'].items()}
    if include is None or not any(kind in COLUMNS for kind in paths):
        return paths, 0.0
    from time import perf_counter
    labels = spec.get('labels') or {}
    started = perf_counter()
    filtered = {}
    for kind, path in paths.items():
        if kind not in COLUMNS:
            filtered[kind] = path
            continue
        path, proof = filter_table(path, kind, include, Path(spec['directory']), skip_unchanged=True)
        displayed = labels.get(kind) or kind
        log(f"{spec['plan']['city']} · {spec['plan']['month']} {displayed}：取分离过滤"
            f"（{'仅保留' if include else '排除'}）"
            f"{proof['rows_before']} → {proof['rows_after']} 行")
        filtered[kind] = path
    return filtered, perf_counter() - started


def generate_binding_process(spec):
    from binding_download import generate_binding
    from generation_performance import generation_context

    logs = []
    cache, ephemeral = _worker_cache(spec.get('task_cache_key'))
    try:
        log = _make_logger(logs)
        cancelled = _cancelled_for(spec)
        paths, filter_seconds = filter_sources(spec, log)
        plan = SimpleNamespace(**spec['plan'])
        benlai = None
        if spec.get('benlai'):
            benlai = (Path(spec['benlai'][0]), list(spec['benlai'][1]))
        with generation_context(cache):
            file, stats = generate_binding(
                paths, Path(spec['employees']), Path(spec['proxies']), plan, Path(spec['directory']),
                log, cancelled, benlai=benlai,
                full_binding_dir=Path(spec['full_binding_dir']) if spec.get('full_binding_dir') else None,
                write_full_binding=bool(spec.get('write_full_binding')),
                binding_platforms=spec.get('binding_platforms') or {})
        return {'file': str(file), 'stats': stats, 'logs': logs, 'filter_seconds': filter_seconds}
    except Exception as exc:
        return {'error': str(exc) or type(exc).__name__, 'error_type': type(exc).__name__,
                'logs': logs}
    finally:
        if ephemeral:
            cache.close()


def generate_binding_and_followup_process(spec):
    """单子进程串联完成同城支付绑定与异常跟进：内存直传 TableExchange，且跨城复用公共来源缓存。"""
    from abnormal_followup import generate_abnormal_followup
    from binding_download import generate_binding
    from generation_performance import TableExchange, generation_context

    binding_logs = []
    followup_logs = []
    cache, ephemeral = _worker_cache(spec.get('task_cache_key'))
    exchange = TableExchange(cache)
    try:
        b_log = _make_logger(binding_logs)
        cancelled = _cancelled_for(spec)
        try:
            paths, filter_seconds = filter_sources(spec, b_log)
            plan = SimpleNamespace(**spec['plan'])
            benlai = None
            if spec.get('benlai'):
                benlai = (Path(spec['benlai'][0]), list(spec['benlai'][1]))
            with generation_context(cache, exchange):
                binding_file, stats = generate_binding(
                    paths, Path(spec['employees']), Path(spec['proxies']), plan, Path(spec['directory']),
                    b_log, cancelled, benlai=benlai,
                    full_binding_dir=Path(spec['full_binding_dir']) if spec.get('full_binding_dir') else None,
                    write_full_binding=bool(spec.get('write_full_binding')),
                    binding_platforms=spec.get('binding_platforms') or {})
        except Exception as exc:
            return {
                'binding': {
                    'error': str(exc) or type(exc).__name__,
                    'error_type': type(exc).__name__,
                    'logs': binding_logs,
                },
            }

        binding_info = {
            'file': str(binding_file),
            'stats': stats,
            'logs': binding_logs,
            'filter_seconds': filter_seconds,
        }

        f_log = _make_logger(followup_logs)
        try:
            followup_dir = Path(spec['followup_dir'])
            followup_dir.mkdir(parents=True, exist_ok=True)
            with generation_context(cache, exchange):
                followup_file = generate_abnormal_followup(
                    Path(binding_file),
                    Path(spec['ub_file']),
                    Path(spec['price_file']),
                    Path(spec['archive_file']),
                    Path(spec['goods_file']),
                    plan.city,
                    plan.month,
                    followup_dir,
                    log=f_log,
                    cancelled=cancelled,
                    stamp=spec.get('stamp'),
                )
            return {
                'binding': binding_info,
                'followup': {'file': str(followup_file), 'logs': followup_logs},
            }
        except Exception as exc:
            return {
                'binding': binding_info,
                'followup': {
                    'error': str(exc) or type(exc).__name__,
                    'error_type': type(exc).__name__,
                    'logs': followup_logs,
                },
            }
    finally:
        exchange.clear()
        if ephemeral:
            cache.close()
