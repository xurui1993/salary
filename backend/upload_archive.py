"""Bounded ZIP extraction for uploaded payroll sources; never load file bodies whole."""
from dataclasses import dataclass
import json
from pathlib import Path
import re
import shutil
import stat
import sys
import unicodedata
import zipfile


GiB = 1024 ** 3
CHUNK = 1024 ** 2


@dataclass(frozen=True)
class Limits:
    file_bytes: int = 4 * GiB
    total_bytes: int = 10 * GiB
    entries: int = 2000
    reserve_bytes: int = 64 * 1024 ** 2


class UploadArchiveError(ValueError):
    pass


def _name(entry):
    name = entry.orig_filename.replace('\\', '/')
    parts = name.rstrip('/').split('/')
    if (not name or name.startswith('/') or any(p in ('', '.', '..') for p in parts)
            or any(re.search(r'[\x00-\x1f<>:"|?*]', p) or p.endswith((' ', '.'))
                   or re.fullmatch(r'(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\..*)?', p, re.I) for p in parts)):
        raise UploadArchiveError('压缩包文件路径无效或越界：' + name)
    mode = entry.external_attr >> 16
    if stat.S_ISLNK(mode) or stat.S_IFMT(mode) not in (0, stat.S_IFREG, stat.S_IFDIR):
        raise UploadArchiveError('压缩包不支持链接或特殊文件：' + name)
    if entry.flag_bits & 1:
        raise UploadArchiveError('压缩包包含加密文件，请先解除密码：' + name)
    return name, parts


def extract_archive(source, target, limits=Limits()):
    source, target = Path(source), Path(target)
    target.mkdir(parents=True, exist_ok=True)
    root = target.resolve()
    if target.is_symlink() or target.absolute() != root or any(target.iterdir()):
        raise UploadArchiveError('上传接收目录不可用，请重新发起上传')
    with zipfile.ZipFile(source) as archive:
        entries = archive.infolist()
        if not entries:
            raise UploadArchiveError('上传压缩包为空')
        if len(entries) > limits.entries:
            raise UploadArchiveError(f'压缩包文件数量超过 {limits.entries} 项限制')
        seen, planned, total = {}, [], 0
        for entry in entries:
            name, parts = _name(entry)
            key = unicodedata.normalize('NFC', '/'.join(parts)).casefold()
            if key in seen:
                raise UploadArchiveError('压缩包包含重复文件路径：' + name)
            seen[key] = entry.is_dir()
            if entry.file_size > limits.file_bytes:
                raise UploadArchiveError(f'文件大小超限：{name}（{entry.file_size:,} 字节，单文件最多 {limits.file_bytes:,} 字节）')
            total += entry.file_size
            if total > limits.total_bytes:
                raise UploadArchiveError(f'资料解压后总大小超限（单批最多 {limits.total_bytes:,} 字节）')
            planned.append((entry, name, parts, key))
        for entry, name, parts, key in planned:
            if any(seen.get('/'.join(key.split('/')[:i])) is False for i in range(1, len(parts))):
                raise UploadArchiveError('压缩包文件与目录路径冲突：' + name)
        if shutil.disk_usage(root).free < total + limits.reserve_bytes:
            raise UploadArchiveError(f'上传目录磁盘空间不足：解压至少需要 {total + limits.reserve_bytes:,} 字节可用空间')
        actual, files = 0, 0
        for entry, name, parts, key in planned:
            path = root.joinpath(*parts)
            if not path.resolve().is_relative_to(root):
                raise UploadArchiveError('压缩包文件路径越界：' + name)
            if entry.is_dir():
                path.mkdir(parents=True, exist_ok=True)
                continue
            path.parent.mkdir(parents=True, exist_ok=True)
            written = 0
            try:
                with archive.open(entry) as incoming, path.open('xb') as outgoing:
                    while chunk := incoming.read(CHUNK):
                        written += len(chunk)
                        actual += len(chunk)
                        if written > limits.file_bytes or actual > limits.total_bytes or written > entry.file_size:
                            raise UploadArchiveError('解压实际文件大小超限：' + name)
                        outgoing.write(chunk)
            except UploadArchiveError:
                raise
            except (OSError, RuntimeError, zipfile.BadZipFile, NotImplementedError) as error:
                reason = '磁盘空间不足' if isinstance(error, OSError) and error.errno == 28 else '文件损坏或ZIP格式不支持'
                raise UploadArchiveError(f'解压失败：{name}（{reason}）；已接收资料保留') from error
            if written != entry.file_size:
                raise UploadArchiveError('解压文件大小与目录记录不一致：' + name)
            files += 1
    return {'success': True, 'files': files, 'bytes': actual}


if __name__ == '__main__':
    try:
        print(json.dumps(extract_archive(sys.argv[1], sys.argv[2]), ensure_ascii=True))
    except (UploadArchiveError, zipfile.BadZipFile, OSError) as error:
        message = str(error) if isinstance(error, UploadArchiveError) else '无法读取上传压缩包：文件损坏或格式无效'
        print(json.dumps({'success': False, 'error': message}, ensure_ascii=True))
        sys.exit(2)
