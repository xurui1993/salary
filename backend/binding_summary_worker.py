"""Process entry points for multi-city binding, followup, and UB monthly summaries."""
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


def _cancelled(spec):
    return _FlagCancelled(spec['cancel_file']) if spec.get('cancel_file') else _NeverCancelled()


def build_platform_summary(spec):
    from binding_summary import build_binding_summaries
    from workbook_policy import compression

    cancelled = _cancelled(spec)
    started = perf_counter()
    try:
        with compression(3):
            files = build_binding_summaries(
                Path(spec['root']), spec['config'], spec['files'], spec['items'], cancelled,
                platform=spec['platform'], summary_city=spec['summary_city'],
                shared_sheets=tuple(spec['shared_sheets']), proof_suffix=spec['proof_suffix'],
                shared_sources={label: Path(path) for label, path in spec['shared_sources'].items()})
        return {'kind': 'platform', 'files': files, 'seconds': round(perf_counter() - started, 3)}
    except Exception as exc:
        return {'kind': 'platform', 'error': str(exc) or type(exc).__name__, 'error_type': type(exc).__name__}


def build_followup_summary_process(spec):
    from abnormal_followup import build_followup_summaries
    from workbook_policy import compression

    cancelled = _cancelled(spec)
    started = perf_counter()
    try:
        with compression(3):
            files = build_followup_summaries(
                Path(spec['root']), spec['config'], spec['files'], spec['items'], cancelled)
        return {'kind': 'followup', 'files': files, 'seconds': round(perf_counter() - started, 3)}
    except Exception as exc:
        return {'kind': 'followup', 'error': str(exc) or type(exc).__name__, 'error_type': type(exc).__name__}


def build_rider_monthly_summary_process(spec):
    from rider_monthly_summary import build_rider_monthly_summaries

    cancelled = _cancelled(spec)
    started = perf_counter()
    logs = []
    try:
        files = build_rider_monthly_summaries(
            Path(spec['root']), spec['config'], spec['files'], spec['items'], cancelled,
            report=lambda msg: logs.append(str(msg)))
        return {'kind': 'rider_monthly', 'files': files, 'logs': logs,
                'seconds': round(perf_counter() - started, 3)}
    except Exception as exc:
        return {'kind': 'rider_monthly', 'error': str(exc) or type(exc).__name__,
                'error_type': type(exc).__name__, 'logs': logs}
