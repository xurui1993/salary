"""Query evidence only; a saved credential is not proof of resource access."""
import threading
import time

_lock = threading.Lock()
_evidence = {}


def record(source, version, capability):
    with _lock:
        _evidence[(source, capability)] = (version, time.time())


def snapshot(source, version):
    with _lock:
        return {key: {'verified': True, 'checked_at': checked}
                for (platform, key), (saved, checked) in _evidence.items()
                if platform == source and saved == version and time.time() - checked < 300}


def discard(source):
    with _lock:
        for key in list(_evidence):
            if key[0] == source:
                del _evidence[key]
