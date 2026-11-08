"""Bounded, credential-free local authentication diagnostics per personal space."""
import json
import os
import threading

LOCK = threading.RLock()
FIELDS = ('source', 'checked_at', 'verified_at', 'state', 'error_code', 'duration_ms', 'verification_level')


def path_for(source):
    from platform_auth_control import files
    return files(source)[0].parent / 'auth-diagnostics.json'


def history(source):
    try:
        path = path_for(source)
        if path.is_symlink() or path.stat().st_size > 128 * 1024:
            return []
        data = json.loads(path.read_text('utf8'))
        return [{key: row[key] for key in FIELDS if key in row}
                for row in data if isinstance(row, dict) and row.get('source') == source][-5:]
    except (OSError, ValueError, TypeError):
        return []


def record(source, result):
    # Only fixed result codes/timestamps; no exception strings, URLs or identities.
    row = {key: result[key] for key in FIELDS if key in result}
    row['source'] = source
    try:
        with LOCK:
            path = path_for(source)
            if path.is_symlink():
                return False
            rows = []
            for key in ('fengshen', 'lanorange', 'baize', 'xiaoxiang'):
                rows.extend(history(key))
            rows.append(row)
            rows = sorted(rows, key=lambda r: r.get('checked_at', ''))[-20:]
            path.parent.mkdir(parents=True, exist_ok=True)
            temporary = path.with_suffix('.tmp')
            temporary.write_text(json.dumps(rows, ensure_ascii=False), 'utf8')
            os.replace(temporary, path)
        return True
    except OSError:
        return False
