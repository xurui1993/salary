"""Process entry point for one platform's multi-city binding summary."""
from pathlib import Path
from time import perf_counter


class _NeverCancelled:
    @staticmethod
    def is_set():
        return False


class _FlagCancelled:
    """取消信号用文件传递：multiprocessing 同步对象无法经进程池参数 pickle。"""

    def __init__(self, path):
        self.path = Path(path)

    def is_set(self):
        return self.path.exists()


def build_platform_summary(spec):
    from binding_summary import build_binding_summaries
    cancelled = _FlagCancelled(spec['cancel_file']) if spec.get('cancel_file') else _NeverCancelled()
    started = perf_counter()
    try:
        files = build_binding_summaries(
            Path(spec['root']), spec['config'], spec['files'], spec['items'], cancelled,
            platform=spec['platform'], summary_city=spec['summary_city'],
            shared_sheets=tuple(spec['shared_sheets']), proof_suffix=spec['proof_suffix'],
            shared_sources={label: Path(path) for label, path in spec['shared_sources'].items()})
        return {'files': files, 'seconds': round(perf_counter() - started, 3)}
    except Exception as exc:
        return {'error': str(exc) or type(exc).__name__, 'error_type': type(exc).__name__}