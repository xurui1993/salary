"""Registered payroll templates with memory-cached inspection and safe CRUD management."""
import base64
import hashlib
import json
from pathlib import Path
import re
import shutil
import tempfile
import zipfile

from openpyxl import Workbook, load_workbook

CITIES = ('三亚', '上海', '东莞', '保定', '北京', '大连', '天津', '宁波', '广州', '泉州', '深圳', '韶关')
CATALOG = {f'{city}-template.xlsx': {'business_line': '淘宝闪购', 'scope': city} for city in CITIES}
CATALOG['小象-template.xlsx'] = {'business_line': '美团灯塔', 'scope': '灯塔业务'}
REQUIRED_HEADERS = ('业务城市', '骑手ID', '开始日期', '结束日期', '结算类型')
SHANGOU_HEADERS = ('业务城市', '团队名称', '骑手ID', '骑手姓名', '开始日期', '结束日期', '薪资方案', '结算类型', '防重拦截', '跨站合并')
XIAOXIANG_HEADERS = (
    '业务城市', '团队名称', '骑手ID', '骑手姓名', '开始日期', '结束日期', '薪资方案', '服务费率', '入职来源', '完成单量',
    '身份证号', '电话号', '出勤扣款', '客诉', '虚假点送达', '违规补时', '保温包', '督导扣罚', '刷单', '结算类型', '防重拦截', '跨站合并',
)
RETIRED = {'异常骑手跟进模板.xlsx'}
INVALID_SCOPE_RE = re.compile(r'[/\\:*?"<>|\x00-\x1f]|\.\.')

# Memory cache keyed by (resolved_path_str, size, sha256_hexdigest)
_INSPECT_CACHE: dict[tuple[str, int, str], dict] = {}


class TemplateError(ValueError):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


def _registry_file(root: Path) -> Path:
    return Path(root) / 'data' / 'template_registry.json'


def _backup_dir(root: Path) -> Path:
    return Path(root) / 'data' / 'system_templates_backup'


def get_catalog(root) -> dict[str, dict]:
    reg_path = _registry_file(Path(root))
    if not reg_path.is_file():
        return {k: dict(v) for k, v in CATALOG.items()}
    try:
        payload = json.loads(reg_path.read_text(encoding='utf-8'))
        entries = payload.get('entries')
        if isinstance(entries, dict):
            return {
                str(k): {
                    'business_line': str(v.get('business_line') or '淘宝闪购'),
                    'scope': str(v.get('scope') or str(k).replace('-template.xlsx', '')),
                    **({'custom': True} if v.get('custom') else {}),
                    **({'updated': True} if v.get('updated') else {}),
                }
                for k, v in entries.items()
                if isinstance(v, dict)
            }
    except Exception:
        pass
    return {k: dict(v) for k, v in CATALOG.items()}


def _save_catalog(root, catalog: dict[str, dict]) -> None:
    reg_path = _registry_file(Path(root))
    reg_path.parent.mkdir(parents=True, exist_ok=True)
    reg_path.write_text(
        json.dumps({'entries': catalog}, ensure_ascii=False, indent=2),
        encoding='utf-8',
    )


def _ensure_builtin_backup(root) -> None:
    root_path = Path(root)
    sys_dir = root_path / 'system_templates'
    bkp_dir = _backup_dir(root_path)
    if not sys_dir.is_dir():
        return
    bkp_dir.mkdir(parents=True, exist_ok=True)
    for filename in CATALOG:
        src = sys_dir / filename
        dst = bkp_dir / filename
        if src.is_file() and not src.is_symlink() and not dst.is_file():
            shutil.copy2(src, dst)


def _validate_directory_safety(directory: Path, path: Path) -> None:
    if (
        directory.is_symlink()
        or (directory.exists() and bool(getattr(directory.lstat(), 'st_file_attributes', 0) & 0x400))
        or path.is_symlink()
        or not path.resolve().is_relative_to(directory.resolve())
    ):
        raise TemplateError('模板路径无效', 400)


def template_path(root, filename):
    if filename in RETIRED:
        raise TemplateError('该报表已改为代码生成，请使用专项报表入口', 410)
    if not filename:
        raise TemplateError('请先选择对应业务的模板')
    catalog = get_catalog(root)
    if filename not in catalog:
        raise TemplateError('模板未登记，请从模板中心选择', 404)
    directory = Path(root) / 'system_templates'
    path = directory / filename
    _validate_directory_safety(directory, path)
    if not path.is_file():
        raise TemplateError('指定模板缺失，请联系维护人员恢复原模板', 404)
    return path


def inspect_template(path):
    try:
        path_obj = Path(path)
        stat = path_obj.stat()
        if stat.st_size > 50 * 1024 * 1024:
            raise ValueError('archive_size')
        with path_obj.open('rb') as source:
            checksum = hashlib.file_digest(source, 'sha256').hexdigest()
        cache_key = (str(path_obj.resolve()), stat.st_size, checksum)
        cached = _INSPECT_CACHE.get(cache_key)
        if cached is not None:
            return {
                'size': stat.st_size,
                'mtime': stat.st_mtime,
                'content_version': cached['content_version'],
                'header_count': cached['header_count'],
                'sheet_count': cached['sheet_count'],
            }

        with zipfile.ZipFile(path_obj) as archive:
            entries = archive.infolist()
            if sum(item.file_size for item in entries) > 50 * 1024 * 1024 or len(entries) > 5000 or archive.testzip():
                raise ValueError('archive')
        book = load_workbook(path_obj, read_only=True, data_only=False)
        try:
            if '申请名单' not in book.sheetnames:
                raise ValueError('sheet')
            sheet_count = len(book.sheetnames)
            sheet = book['申请名单']
            sheet.reset_dimensions()
            headers = [str(value or '').strip() for value in next(sheet.iter_rows(values_only=True), ())]
            if any(headers.count(header) != 1 for header in REQUIRED_HEADERS):
                raise ValueError('headers')
            header_count = len([h for h in headers if h])
        finally:
            book.close()

        meta = {
            'content_version': checksum[:12],
            'header_count': header_count,
            'sheet_count': sheet_count,
        }
        if len(_INSPECT_CACHE) > 256:
            _INSPECT_CACHE.clear()
        _INSPECT_CACHE[cache_key] = meta
        return {
            'size': stat.st_size,
            'mtime': stat.st_mtime,
            **meta,
        }
    except Exception as error:
        # Do not repair or overwrite the protected original on a GET request.
        raise TemplateError('模板损坏或申请名单结构不符合要求，请恢复正确版本', 409) from error


def describe(root, filename):
    catalog = get_catalog(root)
    if filename not in catalog:
        raise TemplateError('模板未登记，请从模板中心选择', 404)
    entry = catalog[filename]
    return {
        'filename': filename,
        **entry,
        'builtin': filename in CATALOG,
        **inspect_template(template_path(root, filename)),
        'available': True,
    }


def listing(root):
    catalog = get_catalog(root)
    templates = []
    for filename in sorted(catalog):
        entry = catalog[filename]
        try:
            templates.append(describe(root, filename))
        except TemplateError as error:
            templates.append({
                'filename': filename,
                **entry,
                'builtin': filename in CATALOG,
                'size': 0,
                'available': False,
                'error': str(error),
            })
    return {
        'success': True,
        'templates': templates,
        'has_customizations': _registry_file(Path(root)).is_file(),
    }


def _normalize_scope_and_filename(scope: str) -> tuple[str, str]:
    clean = str(scope or '').strip()
    if clean.endswith('-template.xlsx'):
        clean = clean[:-len('-template.xlsx')].strip()
    elif clean.endswith('.xlsx'):
        clean = clean[:-len('.xlsx')].strip()
    if not clean or len(clean) > 36 or INVALID_SCOPE_RE.search(clean):
        raise TemplateError('请输入有效的城市或模板名称（不含特殊路径字符，36字以内）', 400)
    return clean, f'{clean}-template.xlsx'


def _normalize_business_line(business_line: str) -> str:
    val = str(business_line or '').strip()
    if val in ('美团小象', '美团灯塔', '小象', '灯塔'):
        return '美团灯塔'
    return '淘宝闪购'


def _write_generated_template(root: Path, target_path: Path, norm_line: str) -> None:
    """Clone an existing verified reference workbook if available, else build a valid standard workbook."""
    candidates: list[Path] = []
    bkp_dir = _backup_dir(root)
    sys_dir = root / 'system_templates'
    if norm_line == '美团灯塔':
        candidates.extend([bkp_dir / '小象-template.xlsx', sys_dir / '小象-template.xlsx'])
    else:
        for city in ('三亚', '上海', '广州', '深圳', '北京'):
            candidates.extend([bkp_dir / f'{city}-template.xlsx', sys_dir / f'{city}-template.xlsx'])

    for candidate in candidates:
        if candidate.is_file() and not candidate.is_symlink():
            try:
                inspect_template(candidate)
                shutil.copyfile(candidate, target_path)
                return
            except Exception:
                continue

    book = Workbook()
    sheet = book.active
    sheet.title = '申请名单'
    headers = XIAOXIANG_HEADERS if norm_line == '美团灯塔' else SHANGOU_HEADERS
    sheet.append(list(headers))
    book.save(target_path)
    book.close()


def _validate_and_write_uploaded_bytes(raw_bytes: bytes, target_path: Path) -> None:
    if not raw_bytes or len(raw_bytes) > 50 * 1024 * 1024:
        raise TemplateError('上传的模板文件大小无效（需在 50MB 以内）', 400)
    target_path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=target_path.parent, suffix='.xlsx', delete=False) as tmp:
        tmp_path = Path(tmp.name)
        tmp.write(raw_bytes)
    try:
        inspect_template(tmp_path)
        tmp_path.replace(target_path)
    except TemplateError as err:
        tmp_path.unlink(missing_ok=True)
        raise TemplateError(
            '上传的 Excel 校验未通过：需包含「申请名单」工作表及必填列（业务城市、骑手ID、开始日期、结束日期、结算类型）',
            400,
        ) from err
    except Exception as err:
        tmp_path.unlink(missing_ok=True)
        raise TemplateError('上传的 Excel 文件格式损坏或无法解析', 400) from err


def create_template(root, scope: str, business_line: str = '淘宝闪购', mode: str = 'generate', file_base64: str | None = None):
    root_path = Path(root)
    clean_scope, filename = _normalize_scope_and_filename(scope)
    norm_line = _normalize_business_line(business_line)
    catalog = get_catalog(root_path)
    if filename in catalog:
        raise TemplateError(f'模板「{filename}」已存在，请直接在列表中点击修改', 409)

    _ensure_builtin_backup(root_path)
    sys_dir = root_path / 'system_templates'
    sys_dir.mkdir(parents=True, exist_ok=True)
    target_path = sys_dir / filename
    _validate_directory_safety(sys_dir, target_path)

    if mode == 'upload' or file_base64:
        if not file_base64:
            raise TemplateError('请选择要上传的 .xlsx 模板文件', 400)
        try:
            raw_bytes = base64.b64decode(file_base64)
        except Exception as err:
            raise TemplateError('上传文件内容编码无效', 400) from err
        _validate_and_write_uploaded_bytes(raw_bytes, target_path)
    else:
        _write_generated_template(root_path, target_path, norm_line)

    catalog[filename] = {
        'business_line': norm_line,
        'scope': clean_scope,
        'custom': filename not in CATALOG,
    }
    _save_catalog(root_path, catalog)
    return {'success': True, 'template': describe(root_path, filename)}


def update_template(
    root,
    original_filename: str,
    scope: str | None = None,
    business_line: str | None = None,
    file_base64: str | None = None,
):
    root_path = Path(root)
    catalog = get_catalog(root_path)
    if not original_filename or original_filename not in catalog:
        raise TemplateError('待修改的模板未登记或不存在', 404)

    _ensure_builtin_backup(root_path)
    current_entry = dict(catalog[original_filename])
    norm_line = _normalize_business_line(business_line) if business_line else current_entry.get('business_line', '淘宝闪购')

    if scope is not None and str(scope).strip():
        clean_scope = str(scope).strip()
        if clean_scope.endswith('-template.xlsx'):
            clean_scope = clean_scope[:-len('-template.xlsx')].strip()
        elif clean_scope.endswith('.xlsx'):
            clean_scope = clean_scope[:-len('.xlsx')].strip()
        if not clean_scope or len(clean_scope) > 36 or INVALID_SCOPE_RE.search(clean_scope):
            raise TemplateError('请输入有效的城市或模板名称（不含特殊路径字符，36字以内）', 400)
        # Keep original filename if scope didn't change (e.g., 小象-template.xlsx has scope 灯塔业务)
        if clean_scope == current_entry.get('scope'):
            new_filename = original_filename
        else:
            new_filename = f'{clean_scope}-template.xlsx'
    else:
        clean_scope = current_entry.get('scope', original_filename.replace('-template.xlsx', ''))
        new_filename = original_filename

    if new_filename != original_filename and new_filename in catalog:
        raise TemplateError(f'目标模板「{new_filename}」已存在，请换一个名称', 409)

    sys_dir = root_path / 'system_templates'
    sys_dir.mkdir(parents=True, exist_ok=True)
    old_path = sys_dir / original_filename
    new_path = sys_dir / new_filename
    _validate_directory_safety(sys_dir, old_path)
    _validate_directory_safety(sys_dir, new_path)

    if file_base64:
        try:
            raw_bytes = base64.b64decode(file_base64)
        except Exception as err:
            raise TemplateError('上传文件内容编码无效', 400) from err
        _validate_and_write_uploaded_bytes(raw_bytes, new_path)
        if new_filename != original_filename and old_path.is_file():
            old_path.unlink(missing_ok=True)
    else:
        if new_filename != original_filename:
            if old_path.is_file():
                old_path.replace(new_path)
            else:
                _write_generated_template(root_path, new_path, norm_line)
        elif not new_path.is_file():
            _write_generated_template(root_path, new_path, norm_line)

    if new_filename != original_filename:
        del catalog[original_filename]
    catalog[new_filename] = {
        'business_line': norm_line,
        'scope': clean_scope,
        'custom': new_filename not in CATALOG,
        'updated': True,
    }
    _save_catalog(root_path, catalog)
    return {'success': True, 'template': describe(root_path, new_filename)}


def delete_template(root, filename: str):
    root_path = Path(root)
    catalog = get_catalog(root_path)
    if not filename or filename not in catalog:
        raise TemplateError('待删除的模板不存在', 404)

    _ensure_builtin_backup(root_path)
    sys_dir = root_path / 'system_templates'
    target_path = sys_dir / filename
    _validate_directory_safety(sys_dir, target_path)

    del catalog[filename]
    _save_catalog(root_path, catalog)
    if target_path.is_file():
        target_path.unlink(missing_ok=True)
    return {'success': True, 'deleted': filename}


def reset_templates(root):
    root_path = Path(root)
    sys_dir = root_path / 'system_templates'
    bkp_dir = _backup_dir(root_path)
    sys_dir.mkdir(parents=True, exist_ok=True)

    # Remove custom non-builtin .xlsx files created via CRUD
    reg_path = _registry_file(root_path)
    if reg_path.is_file():
        current_catalog = get_catalog(root_path)
        for filename in current_catalog:
            if filename not in CATALOG:
                custom_path = sys_dir / filename
                if custom_path.is_file() and not custom_path.is_symlink():
                    custom_path.unlink(missing_ok=True)
        reg_path.unlink(missing_ok=True)

    # Restore backed-up built-in templates
    if bkp_dir.is_dir():
        for filename in CATALOG:
            bkp_file = bkp_dir / filename
            dst_file = sys_dir / filename
            if bkp_file.is_file() and not bkp_file.is_symlink():
                shutil.copy2(bkp_file, dst_file)

    return listing(root_path)
