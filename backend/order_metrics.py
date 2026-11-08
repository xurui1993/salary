"""Nested local timings; child-process measurements are returned explicitly."""
from contextlib import contextmanager
from contextvars import ContextVar
from functools import wraps
from time import perf_counter
from generation_performance import stage

_current = ContextVar('order_timings', default=None)

@contextmanager
def measurements(value):
    token = _current.set(value)
    try:
        yield
    finally:
        _current.reset(token)


def measured(name):
    def decorate(function):
        @wraps(function)
        def call(*args, **kwargs):
            started = perf_counter()
            try:
                with stage('orders:' + name):
                    return function(*args, **kwargs)
            finally:
                value = _current.get()
                if value is not None:
                    value[name] = value.get(name, 0) + perf_counter() - started
        return call
    return decorate


def worker_measurements(function):
    @wraps(function)
    def call(*args, **kwargs):
        value = {}
        with measurements(value):
            result = function(*args, **kwargs)
        result['timings'] = value
        return result
    return call
