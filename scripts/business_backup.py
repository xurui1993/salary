"""Offline, verified business snapshots. Restore only to a NEW directory.

Default commands only preview. No command deletes or replaces business data.
"""
import argparse
import datetime as dt
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import sqlite3
import uuid
from contextlib import contextmanager, closing

ROOTS = ('data', 'uploads', 'outputs', 'system_templates', 'backend/.local_downloads', 'backend/.local_auth', '.local_auth')
EPHEMERAL = ('.lock', '.part', '.partial', '-wal', '-shm', '-journal')


def sha256(path):
    with path.open('rb') as source:
        return hashlib.file_digest(source, 'sha256').hexdigest()


def linked(path):
    return path.is_symlink() or bool(getattr(path.lstat(), 'st_file_attributes', 0) & 0x400)


def offline(root):
    lock = root / 'backend/.local_downloads/server.lock'
    if lock.exists():
        try:
            pid = json.loads(lock.read_text(encoding='utf-8'))['pid']
            if not isinstance(pid, int) or pid <= 0:
                raise ValueError('invalid pid')
            # psutil avoids Windows os.kill(pid, 0) process-handle semantics.
            import psutil
            if psutil.pid_exists(pid):
                raise ValueError('请先关闭系统服务，再创建一致的资料备份')
        except (OSError, KeyError, json.JSONDecodeError) as error:
            raise ValueError('启动锁无法确认，请先检查服务状态') from error


@contextmanager
def maintenance_lock(root):
    """Use the application's startup lock so a service cannot start mid-backup."""
    offline(root)
    lock = root / 'backend/.local_downloads/server.lock'
    lock.parent.mkdir(parents=True, exist_ok=True)
    if lock.exists():
        if linked(lock):
            raise ValueError('启动锁不能是链接')
        previous = lock.read_bytes()
        offline(root)
        if lock.read_bytes() != previous:
            raise ValueError('启动锁发生变化，请重新检查服务状态')
        lock.unlink()  # Only the confirmed stale process lock, never business data.
    token = uuid.uuid4().hex
    handle = os.open(lock, os.O_WRONLY | os.O_CREAT | os.O_EXCL)
    with os.fdopen(handle, 'w', encoding='utf-8') as target:
        json.dump({'pid': os.getpid(), 'token': token, 'maintenance': 'verified-backup'}, target)
    try:
        yield
    finally:
        current = json.loads(lock.read_text(encoding='utf-8'))
        if current.get('token') != token:
            raise ValueError('维护锁被其他进程替换，请检查备份期间的运行状态')
        lock.unlink()


def inventory(root):
    root = Path(root).resolve()
    files, skipped = [], []
    for name in ROOTS:
        directory = root / name
        if not directory.exists():
            continue
        if linked(directory):
            raise ValueError('备份范围中不允许目录链接：' + name)
        for base, dirs, names in os.walk(directory, followlinks=False):
            for child in dirs:
                if linked(Path(base) / child):
                    raise ValueError('备份范围中存在目录链接')
            for child in names:
                path = Path(base) / child
                relative = path.relative_to(root).as_posix()
                if linked(path) or not path.resolve().is_relative_to(root):
                    raise ValueError('备份范围中存在越界文件')
                if child.endswith(EPHEMERAL):
                    skipped.append(relative)
                    continue
                files.append({'path': relative, 'bytes': path.stat().st_size})
    return {'roots': list(ROOTS), 'files': sorted(files, key=lambda item: item['path']),
            'file_count': len(files), 'bytes': sum(item['bytes'] for item in files),
            'excluded_ephemeral': skipped,
            'coverage': '项目内配置、上传、产出、模板、任务与会话；自定义外部资料目录须另行备份'}


def checked_path(base, relative):
    value = PurePosixPath(relative)
    reserved = {'CON', 'PRN', 'AUX', 'NUL', *(f'COM{i}' for i in range(1, 10)), *(f'LPT{i}' for i in range(1, 10))}
    if value.is_absolute() or not value.parts or any(part in ('.', '..') or part.rstrip(' .') != part or
        any(char in part for char in '<>:"\\|?*') or any(ord(char) < 32 for char in part) or
        part.split('.')[0].upper() in reserved for part in value.parts):
        raise ValueError('备份清单包含无效路径')
    path = base.joinpath(*value.parts)
    if not path.resolve().is_relative_to(base.resolve()):
        raise ValueError('备份清单路径越界')
    for parent in [path, *path.parents]:
        if parent == base.parent:
            break
        if parent.exists() and linked(parent):
            raise ValueError('备份路径不允许文件或目录链接')
    return path


def sqlite_file(path):
    with path.open('rb') as source:
        return source.read(16) == b'SQLite format 3\x00'


def verify(snapshot):
    snapshot = Path(snapshot).resolve()
    manifest = snapshot / 'manifest.json'
    if sha256(manifest) != (snapshot / 'manifest.sha256').read_text(encoding='ascii').strip():
        raise ValueError('备份清单校验失败')
    value = json.loads(manifest.read_text(encoding='utf-8'))
    if value.get('version') != 1 or not isinstance(value.get('files'), list):
        raise ValueError('备份版本或清单无效')
    seen = set()
    for item in value['files']:
        relative = item['path']
        if relative.casefold() in seen:
            raise ValueError('备份清单存在重复路径')
        seen.add(relative.casefold())
        path = checked_path(snapshot / 'files', relative)
        if not path.is_file() or path.stat().st_size != item['bytes'] or sha256(path) != item['sha256']:
            raise ValueError('备份文件校验失败：' + relative)
        if item.get('sqlite'):
            # These files are completed snapshots, not live WAL databases.
            # immutable prevents a verification read from creating WAL/SHM files.
            with closing(sqlite3.connect(path.as_uri() + '?mode=ro&immutable=1', uri=True)) as db:
                if db.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
                    raise ValueError('数据库备份完整性校验失败')
    actual = {p.relative_to(snapshot / 'files').as_posix().casefold() for p in (snapshot / 'files').rglob('*') if p.is_file()}
    if actual != seen:
        raise ValueError('备份目录文件数量与清单不一致')
    return value


def backup(root, destination):
    root, destination = Path(root).resolve(), Path(destination).resolve()
    if destination == root or any(destination.is_relative_to(root / name) for name in ROOTS):
        raise ValueError('备份位置不能位于被备份的资料目录中')
    with maintenance_lock(root):
        return copy_snapshot(root, destination)


def copy_snapshot(root, destination):
    plan = inventory(root)
    destination.mkdir(parents=True, exist_ok=True)
    if shutil.disk_usage(destination).free < plan['bytes'] + 64 * 1024 * 1024:
        raise ValueError('目标磁盘可用空间不足')
    name = dt.datetime.now().strftime('%Y%m%d_%H%M%S') + '_' + uuid.uuid4().hex[:8]
    partial = destination / (name + '.partial')
    partial.mkdir()
    files = []
    for item in plan['files']:
        source = checked_path(root, item['path'])
        target = checked_path(partial / 'files', item['path'])
        target.parent.mkdir(parents=True, exist_ok=True)
        before = source.stat()
        is_db = sqlite_file(source)
        if is_db:
            with closing(sqlite3.connect(source.as_uri() + '?mode=ro', uri=True)) as original, closing(sqlite3.connect(target)) as saved:
                original.backup(saved)
                saved.commit()
                saved.execute('PRAGMA journal_mode=DELETE')
        else:
            shutil.copy2(source, target)
        after = source.stat()
        if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
            raise ValueError('备份期间资料发生变化，未发布完整备份')
        checksum = sha256(target)
        if not is_db and checksum != sha256(source):
            raise ValueError('复制后校验不一致，未发布完整备份')
        files.append({'path': item['path'], 'bytes': target.stat().st_size, 'sha256': checksum, 'sqlite': is_db})
    if inventory(root)['files'] != plan['files']:
        raise ValueError('备份期间资料清单发生变化，未发布完整备份')
    value = {**plan, 'version': 1, 'created_at': dt.datetime.now(dt.timezone.utc).isoformat(), 'files': files}
    manifest = partial / 'manifest.json'
    manifest.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')
    (partial / 'manifest.sha256').write_text(sha256(manifest), encoding='ascii')
    verify(partial)
    final = destination / name
    if partial.resolve().parent != destination or final.parent != destination:
        raise ValueError('备份发布路径越界')
    partial.rename(final)
    return final


def restore(snapshot, target):
    snapshot, target = Path(snapshot).resolve(), Path(target).resolve()
    value = verify(snapshot)
    if target.exists():
        raise ValueError('恢复目录必须不存在；不会覆盖任何现有业务资料')
    target.mkdir(parents=True)
    for item in value['files']:
        source = checked_path(snapshot / 'files', item['path'])
        destination = checked_path(target, item['path'])
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
        if sha256(destination) != item['sha256']:
            raise ValueError('恢复文件校验失败，原备份仍保留')
    return {'target': str(target), 'files_verified': len(value['files'])}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('plan', 'backup', 'verify', 'restore'))
    parser.add_argument('--root', type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument('--destination', type=Path)
    parser.add_argument('--snapshot', type=Path)
    parser.add_argument('--target', type=Path)
    parser.add_argument('--apply', action='store_true', help='执行创建备份或恢复到新目录；默认仅预览')
    args = parser.parse_args()
    if args.command == 'plan':
        value = inventory(args.root)
        value.pop('files')
    elif args.command == 'backup':
        if not args.destination:
            parser.error('backup 需要 --destination')
        value = {'snapshot': str(backup(args.root, args.destination))} if args.apply else {'preview': inventory(args.root), 'destination': str(args.destination)}
    elif args.command == 'verify':
        if not args.snapshot:
            parser.error('verify 需要 --snapshot')
        value = {'verified_files': len(verify(args.snapshot)['files'])}
    else:
        if not args.snapshot or not args.target:
            parser.error('restore 需要 --snapshot 和 --target')
        value = restore(args.snapshot, args.target) if args.apply else {'verified_files': len(verify(args.snapshot)['files']), 'target': str(args.target), 'apply': False}
    print(json.dumps(value, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
