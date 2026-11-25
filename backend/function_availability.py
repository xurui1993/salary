"""Query evidence only; a saved credential is not proof of resource access."""
import threading
import time

_lock = threading.Lock()
_evidence = {}


def _scope(source: str) -> str:
    if source in ('xiaoxiang', 'benlai'):
        return 'shared'
    from workspace_context import current_workspace
    return current_workspace()


def record(source, version, capability):
    scope = _scope(source)
    with _lock:
        _evidence[(scope, source, capability)] = (version, time.time())


def snapshot(source, version):
    scope = _scope(source)
    with _lock:
        return {key: {'verified': True, 'checked_at': checked}
                for (entry_scope, platform, key), (saved, checked) in _evidence.items()
                if entry_scope == scope and platform == source and saved == version and time.time() - checked < 300}


def discard(source):
    scope = _scope(source)
    with _lock:
        for key in list(_evidence):
            if key[0] == scope and key[1] == source:
                del _evidence[key]
