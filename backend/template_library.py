"""Registered payroll templates. Read-only: missing files are never generated."""
import hashlib
from pathlib import Path
import zipfile

from openpyxl import load_workbook

CITIES = ('三亚', '上海', '东莞', '保定', '北京', '大连', '天津', '宁波', '广州', '泉州', '深圳', '韶关')
CATALOG = {f'{city}-template.xlsx': {'business_line': '淘宝闪购', 'scope': city} for city in CITIES}
CATALOG['小象-template.xlsx'] = {'business_line': '美团灯塔', 'scope': '灯塔业务'}
REQUIRED_HEADERS = ('业务城市', '骑手ID', '开始日期', '结束日期', '结算类型')
RETIRED = {'异常骑手跟进模板.xlsx'}


class TemplateError(ValueError):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


def template_path(root, filename):
    if filename in RETIRED:
        raise TemplateError('该报表已改为代码生成，请使用专项报表入口', 410)
    if not filename:
        raise TemplateError('请先选择对应业务的模板')
    if filename not in CATALOG:
        raise TemplateError('模板未登记，请从模板中心选择', 404)
    directory = Path(root) / 'system_templates'
    path = directory / filename
    if directory.is_symlink() or (directory.exists() and bool(getattr(directory.lstat(), 'st_file_attributes', 0) & 0x400)) or path.is_symlink() or not path.resolve().is_relative_to(directory.resolve()):
        raise TemplateError('模板路径无效', 400)
    if not path.is_file():
        raise TemplateError('指定模板缺失，请联系维护人员恢复原模板', 404)
    return path


def inspect_template(path):
    try:
        with zipfile.ZipFile(path) as archive:
            entries = archive.infolist()
            if sum(item.file_size for item in entries) > 50 * 1024 * 1024 or len(entries) > 5000 or archive.testzip():
                raise ValueError('archive')
        book = load_workbook(path, read_only=True, data_only=False)
        try:
            if '申请名单' not in book.sheetnames:
                raise ValueError('sheet')
            sheet = book['申请名单']
            sheet.reset_dimensions()
            headers = [str(value or '').strip() for value in next(sheet.iter_rows(values_only=True), ())]
            if any(headers.count(header) != 1 for header in REQUIRED_HEADERS):
                raise ValueError('headers')
        finally:
            book.close()
        with path.open('rb') as source:
            checksum = hashlib.file_digest(source, 'sha256').hexdigest()
        stat = path.stat()
        return {'size': stat.st_size, 'mtime': stat.st_mtime, 'content_version': checksum[:12]}
    except Exception as error:
        # Do not repair or overwrite the protected original on a GET request.
        raise TemplateError('模板损坏或申请名单结构不符合要求，请恢复正确版本', 409) from error


def describe(root, filename):
    return {'filename': filename, **CATALOG[filename], **inspect_template(template_path(root, filename)), 'available': True}


def listing(root):
    templates = []
    for filename in sorted(CATALOG):
        try:
            templates.append(describe(root, filename))
        except TemplateError as error:
            templates.append({'filename': filename, **CATALOG[filename], 'size': 0, 'available': False, 'error': str(error)})
    return {'success': True, 'templates': templates}
