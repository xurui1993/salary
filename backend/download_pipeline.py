"""Cooperative handoff after the final platform request; never parallel collectors."""
from contextlib import contextmanager
from contextvars import ContextVar
import time

from fengshen_bill import BillCollectionError

_current = ContextVar('download_pipeline', default=None)


class PipelineTurn:
    def __init__(self, local_gate, released, cancelled):
        self.gate, self.released, self.cancelled = local_gate, released, cancelled
        self.local_owned = False
        self.handed_off = False
        self.local_wait_seconds = 0.0

    def reserve_local(self):
        if self.local_owned:
            return
        started = time.perf_counter()
        while not self.gate.acquire(timeout=.1):
            if self.cancelled.is_set():
                raise BillCollectionError('本地生成排队已取消')
        self.local_owned = True
        self.local_wait_seconds += time.perf_counter() - started
        if self.cancelled.is_set():
            raise BillCollectionError('本地生成排队已取消')

    def handoff(self):
        # Reserve the one heavy local task before allowing another collector.
        self.reserve_local()
        if not self.handed_off:
            self.handed_off = True
            self.released()

    def close(self):
        if self.local_owned:
            self.local_owned = False
            self.gate.release()


@contextmanager
def pipeline_scope(turn):
    token = _current.set(turn)
    try:
        yield
    finally:
        _current.reset(token)
        turn.close()


def reserve_local_work():
    turn = _current.get()
    if turn is not None:
        turn.reserve_local()


def release_collection_for_local_work():
    turn = _current.get()
    if turn is not None:
        turn.handoff()


def pipeline_diagnostics():
    turn = _current.get()
    if turn is None:
        return None
    return {'collection_released_before_local_work': turn.handed_off,
            'local_queue_seconds': round(turn.local_wait_seconds, 6),
            'max_inflight_tasks': 2, 'max_heavy_local_tasks': 1}
