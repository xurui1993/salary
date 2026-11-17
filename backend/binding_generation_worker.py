"""Process entry point for one city's payment-binding generation."""
from pathlib import Path
from types import SimpleNamespace


class _NotCancelled:
    # 进程内无共享取消事件；父进程停止等待并在 shutdown 时丢弃排队任务。
    @staticmethod
    def is_set():
        return False


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
    logs = []
    try:
        def log(message, *args, **kwargs):
            safe = tuple(value if isinstance(value, (str, int, float, bool, type(None))) else str(value)
                         for value in args)
            logs.append((str(message), safe, {}))
        paths, filter_seconds = filter_sources(spec, log)
        plan = SimpleNamespace(**spec['plan'])
        benlai = None
        if spec.get('benlai'):
            benlai = (Path(spec['benlai'][0]), list(spec['benlai'][1]))
        file, stats = generate_binding(
            paths, Path(spec['employees']), Path(spec['proxies']), plan, Path(spec['directory']),
            log, _NotCancelled(), benlai=benlai,
            full_binding_dir=Path(spec['full_binding_dir']) if spec.get('full_binding_dir') else None,
            write_full_binding=bool(spec.get('write_full_binding')))
        return {'file': str(file), 'stats': stats, 'logs': logs, 'filter_seconds': filter_seconds}
    except Exception as exc:
        return {'error': str(exc) or type(exc).__name__, 'error_type': type(exc).__name__,
                'logs': logs}