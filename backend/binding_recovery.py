"""Recover generation from complete, verified material; never submit an export."""
import hashlib
import hashlib_compat
import json
from pathlib import Path
from types import SimpleNamespace

from fengshen_bill import BillCollectionError, MonthlyBillRequest


def verified_file(directory, receipt):
    base = Path(directory).resolve()
    relative = Path(receipt.get('path', ''))
    path = base / relative
    if (not relative.name or relative.is_absolute() or '..' in relative.parts or path.is_symlink()
            or not path.resolve().is_relative_to(base) or not path.is_file()
            or receipt.get('bytes') != path.stat().st_size):
        raise BillCollectionError('恢复资料文件归属或大小不符')
    with path.open('rb') as stream:
        if receipt.get('sha256') != hashlib.file_digest(stream, 'sha256').hexdigest():
            raise BillCollectionError('恢复资料完整性校验失败')
    return str(path.resolve())


def completed_materials(root, city, agency, start, end, snapshot=None):
    from download_service import _rider_source_file
    root = Path(root).resolve()
    month = start[:7]
    plan = SimpleNamespace(city=city, agency_id=agency, start=start, end=end, month=month)
    directory = root / '原始资料' / city / 'payment_binding' / month
    paths = {}
    for kind in ('rider_detail', 'receive_account', 'rider_info'):
        raw = Path(snapshot) if kind == 'rider_info' and snapshot else directory / kind
        info = json.loads((raw / 'source_receipt.json').read_text(encoding='utf-8'))
        if kind == 'receive_account':
            calendar = MonthlyBillRequest(month)
            source_plan = SimpleNamespace(**{**vars(plan), 'start': calendar.start, 'end': calendar.end})
        elif kind == 'rider_info':
            if info.get('snapshot_only') is not True:
                raise BillCollectionError('骑手信息不是已校验的当前快照')
            source_plan = SimpleNamespace(**{**vars(plan), 'start': info['start'], 'end': info['end']})
        else:
            source_plan = plan
        paths[kind] = str(_rider_source_file(info, raw, kind, source_plan))
    common = root / '原始资料' / '支付绑定公共来源'
    for source, subdir, key in (('baize', common / 'baize', 'employees'),
                                ('lanorange', common / 'lanorange' / month, 'proxies')):
        manifest = json.loads((subdir / 'manifest.json').read_text(encoding='utf-8'))
        receipt = json.loads((subdir / 'http_submission.json').read_text(encoding='utf-8'))
        if manifest.get('status') != 'success' or receipt.get('source') != source or receipt.get('submission_state') != 'submitted':
            raise BillCollectionError('跨系统原始资料未确认完整，不能恢复生成')
        if source == 'baize':
            name = manifest['path']
        else:
            if manifest.get('month') != month or receipt.get('scope', {}).get('replaceMonth') != month:
                raise BillCollectionError('代领原始资料月份不符')
            name = '薪资代领.xlsx'
        paths[key] = verified_file(subdir, {**receipt, 'path': name})
    return {key: {'path': value, 'bytes': Path(value).stat().st_size,
                  'sha256': hashlib.sha256(Path(value).read_bytes()).hexdigest()} for key, value in paths.items()}


def copy_materials(materials, destination):
    import shutil
    destination = Path(destination)
    destination.mkdir(parents=True, exist_ok=True)
    if set(materials) != {'rider_detail', 'receive_account', 'rider_info', 'employees', 'proxies'}:
        raise BillCollectionError('恢复生成所需资料不完整')
    paths = {}
    for key, receipt in materials.items():
        source = Path(receipt['path'])
        verified_file(source.parent, {**receipt, 'path': source.name})
        target = destination / (key + source.suffix.lower())
        shutil.copy2(source, target)
        paths[key] = target
    return paths
