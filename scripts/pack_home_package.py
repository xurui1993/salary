"""Build and verify a portable source-only package from this repository alone."""
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import stat
import subprocess
import tempfile
import zipfile

ROOT = Path(__file__).resolve().parents[1]
WRAPPER_ROOT = ROOT / 'scripts' / 'package_root'
ARCHIVE_ROOT = '薪酬工作台'
REQUIRED = ('package.json', 'package-lock.json', 'server.ts', 'src/App.tsx',
            'backend/main.py', 'backend/requirements.txt', 'start.ps1')
AREAS = {'backend', 'src', 'public', 'scripts', 'server', 'system_templates', 'tests'}
ROOT_FILES = {'.env.example', '.gitignore', 'README.md', 'LICENSE', 'package.json', 'package-lock.json',
              'server.ts', 'index.html', 'start.ps1', 'tsconfig.json', 'vite.config.ts'}
SKIP_DIRS = {'node_modules', '.venv', 'venv', '.git', '__pycache__', '.pytest_cache',
             '.mypy_cache', '.cache', '.local_auth', '.local_downloads', 'personal-runtime',
             'runtime', 'data', 'uploads', 'outputs', 'archive', 'coverage', 'config_history', 'dist'}
PRIVATE_PREFIXES = ('.local_auth', '.local_downloads')
PRIVATE_SUFFIXES = {'.pyc', '.log', '.dpapi', '.sqlite', '.sqlite3', '.db', '.storage',
                    '.part', '.pem', '.key', '.pfx', '.p12', '.bak', '.tmp'}


def walk(folder):
    for entry in os.scandir(folder):
        path = Path(entry.path)
        info = entry.stat(follow_symlinks=False)
        if (entry.is_symlink() or getattr(info, 'st_file_attributes', 0)
                & getattr(stat, 'FILE_ATTRIBUTE_REPARSE_POINT', 0)):
            continue
        if entry.is_dir(follow_symlinks=False):
            if any(entry.name.startswith(prefix) for prefix in PRIVATE_PREFIXES):
                continue
            if entry.name not in SKIP_DIRS and not ('tests' in path.parts and entry.name.startswith('tmp')):
                yield from walk(path)
        elif entry.is_file(follow_symlinks=False):
            yield path


def public_file(source):
    name = source.name.lower()
    return (source.suffix.lower() not in PRIVATE_SUFFIXES
            and not name.endswith(('.sqlite-wal', '.sqlite-shm', '.sqlite3-wal', '.sqlite3-shm', '.db-wal', '.db-shm'))
            and not (name.startswith('.env') and name != '.env.example')
            and name != '异常骑手跟进模板.xlsx')


def collect():
    entries = []
    for source in walk(ROOT):
        relative = source.relative_to(ROOT)
        if not ((len(relative.parts) == 1 and source.name in ROOT_FILES) or relative.parts[0] in AREAS):
            continue
        if public_file(source):
            entries.append((relative, source))
    names = {name.as_posix() for name, _ in entries}
    if not set(REQUIRED).issubset(names):
        raise ValueError('Package missing required source files')
    return sorted(entries)


def collect_project():
    entries = [(Path('app') / name, source) for name, source in collect()]
    for name in ('README.md', '启动系统.cmd'):
        source = WRAPPER_ROOT / name
        if not source.is_file():
            raise ValueError('Repository packaging wrapper missing: ' + name)
        entries.append((Path(name), source))
    # The parent directory can contain unrelated projects.
    for source in walk(ROOT / 'docs'):
        if (source.suffix.lower() in ('.md', '.json') and public_file(source)
                and source.name not in ('SOURCE_MANIFEST.json', 'SHA256.txt')):
            entries.append((source.relative_to(ROOT), source))
    return sorted(entries)


def revision():
    try:
        value = subprocess.run(['git', '-C', str(ROOT), 'rev-parse', 'HEAD'],
                               capture_output=True, text=True, check=True).stdout.strip()
        return value if len(value) == 40 else None
    except (OSError, subprocess.SubprocessError):
        return None


def verify_package(output):
    """CRC, manifest hashes, checksum readback and a fresh extraction/layout check."""
    output = Path(output).resolve()
    with zipfile.ZipFile(output) as archive:
        names = archive.namelist()
        if len(names) != len(set(names)) or archive.testzip() is not None:
            raise ValueError('Package CRC or duplicate-entry check failed')
        prefix = ARCHIVE_ROOT + '/'
        if any(not name.startswith(prefix) or '..' in Path(name).parts for name in names):
            raise ValueError('Package archive root is invalid')
        manifest = json.loads(archive.read(prefix + 'docs/SOURCE_MANIFEST.json'))
        expected = {entry['path'] for entry in manifest['files']}
        if {name.removeprefix(prefix) for name in names} != expected | {'docs/SOURCE_MANIFEST.json', 'docs/SHA256.txt'}:
            raise ValueError('Package content differs from its source manifest')
        for entry in manifest['files']:
            data = archive.read(prefix + entry['path'])
            if len(data) != entry['bytes'] or hashlib.sha256(data).hexdigest() != entry['sha256']:
                raise ValueError('Package source hash mismatch: ' + entry['path'])
        checksums = archive.read(prefix + 'docs/SHA256.txt').decode('utf-8').splitlines()
        if {line.split('  ', 1)[1] for line in checksums} != expected | {'docs/SOURCE_MANIFEST.json'}:
            raise ValueError('Package checksum coverage is incomplete')
        for line in checksums:
            digest, name = line.split('  ', 1)
            if hashlib.sha256(archive.read(prefix + name)).hexdigest() != digest:
                raise ValueError('Package checksum mismatch: ' + name)
        with tempfile.TemporaryDirectory(prefix='source-package-verify-', dir=output.parent) as temporary:
            target = Path(temporary).resolve()
            if not target.is_relative_to(output.parent):
                raise ValueError('Verification directory escaped its delivery directory')
            archive.extractall(target)
            project = target / ARCHIVE_ROOT
            if {p.name for p in project.iterdir()} != {'README.md', '启动系统.cmd', 'app', 'docs'}:
                raise ValueError('Fresh extraction has unexpected root entries')
            if not all((project / 'app' / name).is_file() for name in REQUIRED):
                raise ValueError('Fresh extraction missing required application source')
            for entry in manifest['files']:
                source = project / entry['path']
                with source.open('rb') as stream:
                    if hashlib.file_digest(stream, 'sha256').hexdigest() != entry['sha256']:
                        raise ValueError('Extracted source hash mismatch: ' + entry['path'])
    return {'crc_verified': True, 'file_hashes_verified': True, 'fresh_extraction_verified': True}


def package(output):
    output = Path(output).resolve()
    files = {name.as_posix(): source.read_bytes() for name, source in collect_project()}
    manifest = {'format': 'source-only', 'version': 2, 'revision': revision(),
                'created_at': datetime.now(timezone.utc).isoformat(),
                'root_entries': ['启动系统.cmd', 'README.md', 'app/', 'docs/'],
                'excluded': ['dependencies', 'builds', 'business data', 'uploads and results',
                             'platform sessions', 'history and logs', 'temporary tests', 'private environment files'],
                'files': [{'path': name, 'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest()}
                          for name, data in sorted(files.items())]}
    files['docs/SOURCE_MANIFEST.json'] = json.dumps(manifest, ensure_ascii=False, indent=2).encode('utf-8')
    files['docs/SHA256.txt'] = ''.join(hashlib.sha256(data).hexdigest() + '  ' + name + '\n'
                                        for name, data in sorted(files.items())).encode('utf-8')
    output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output, 'x', zipfile.ZIP_DEFLATED) as archive:
        for name, data in sorted(files.items()):
            info = zipfile.ZipInfo(ARCHIVE_ROOT + '/' + name, (1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(info, data)
    verified = verify_package(output)
    with output.open('rb') as stream:
        digest = hashlib.file_digest(stream, 'sha256').hexdigest()
    result = {'archive': str(output), 'files': len(files), 'bytes': output.stat().st_size,
              'sha256': digest, 'revision': manifest['revision'], 'root_entries': len(manifest['root_entries']), **verified}
    output.with_suffix(output.suffix + '.verification.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    return result


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('output', type=Path)
    print(json.dumps(package(parser.parse_args().output), ensure_ascii=True))
