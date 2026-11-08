"""Host-private roots retained to keep legacy file APIs outside download data."""
import json
import os
from pathlib import Path
import sqlite3
import uuid
from atomic_files import atomic_replace


def refresh_protected_roots(db_path=None, output_root=None):
    if db_path is None:
        db_path = Path(__file__).parent / ".local_downloads" / "tasks.sqlite3"
    if output_root is None:
        from download_jobs import configured_output_root
        output_root = configured_output_root()
    db_path = Path(db_path).resolve()
    target = db_path.parent / "protected_roots.json"
    roots = {str(Path(output_root).resolve())}
    if target.exists():
        data = json.loads(target.read_text(encoding="utf-8"))
        if (not isinstance(data, dict) or not isinstance(data.get("roots"), list)
                or any(not isinstance(root, str) or not Path(root).is_absolute() for root in data["roots"])):
            raise ValueError("下载资料保护目录清单无效，请由主机管理员检查")
        roots.update(str(Path(root).resolve()) for root in data["roots"])
    if db_path.is_file():
        # Never instantiate a worker just to read historical archive locations.
        connection = sqlite3.connect(db_path.as_uri() + "?mode=ro", uri=True, timeout=15)
        try:
            table = connection.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='download_runs'").fetchone()
            if table:
                for row in connection.execute("SELECT state_json FROM download_runs"):
                    state = json.loads(row[0])
                    root = state.get("_archive_root")
                    if isinstance(root, str) and Path(root).is_absolute():
                        roots.add(str(Path(root).resolve()))
        finally:
            connection.close()
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(".protected_roots_" + uuid.uuid4().hex + ".tmp")
    try:
        with temporary.open("x", encoding="utf-8") as stream:
            json.dump({"roots": sorted(roots)}, stream, ensure_ascii=False)
        atomic_replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)
    return sorted(roots)
