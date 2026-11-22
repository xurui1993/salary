import asyncio
import base64
import hashlib
import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from openpyxl import Workbook
from fastapi import HTTPException
import main
import template_library as library


class TemplateLibraryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / 'system_templates').mkdir()

    def template(self, headers=library.REQUIRED_HEADERS, filename='北京-template.xlsx'):
        path = self.root / 'system_templates' / filename
        book = Workbook()
        book.active.title = '申请名单'
        book.active.append(list(headers))
        book.save(path)
        book.close()
        return path

    def test_missing_file_is_never_generated_even_if_data_fallback_exists(self):
        (self.root / 'data').mkdir()
        fallback = self.root / 'data/北京-template.xlsx'
        fallback.write_bytes(b'original-business-input')
        with patch.object(main, 'get_project_root', return_value=self.root):
            with self.assertRaises(HTTPException) as caught:
                asyncio.run(main.download_template('北京-template.xlsx'))
            self.assertEqual(caught.exception.status_code, 404)
        self.assertFalse((self.root / 'system_templates/北京-template.xlsx').exists())
        self.assertEqual(fallback.read_bytes(), b'original-business-input')

    def test_unregistered_traversal_and_configuration_files_are_not_downloadable(self):
        for value in ('', '../北京-template.xlsx', '..\\北京-template.xlsx', 'config.json', 'other.xlsx'):
            with self.subTest(value=value), self.assertRaises(library.TemplateError):
                library.template_path(self.root, value)

    def test_valid_template_exposes_real_content_identifier_and_is_not_modified(self):
        path = self.template()
        before = path.read_bytes()
        value = library.describe(self.root, path.name)
        self.assertEqual(value['content_version'], hashlib.sha256(before).hexdigest()[:12])
        self.assertEqual(value['scope'], '北京')
        self.assertEqual(path.read_bytes(), before)
        with patch.object(main, 'get_project_root', return_value=self.root):
            response = asyncio.run(main.download_template(path.name))
        self.assertEqual(Path(response.path), path)

    def test_wrong_or_duplicate_headers_and_corrupt_file_are_rejected_without_repair(self):
        for headers in (['骑手姓名'], [*library.REQUIRED_HEADERS, '骑手ID']):
            path = self.template(headers)
            before = path.read_bytes()
            with self.assertRaises(library.TemplateError):
                library.inspect_template(path)
            self.assertEqual(path.read_bytes(), before)
        path.write_bytes(b'not-an-xlsx')
        with self.assertRaises(library.TemplateError):
            library.inspect_template(path)
        self.assertEqual(path.read_bytes(), b'not-an-xlsx')

    def test_listing_missing_templates_only_reports_unavailable(self):
        value = library.listing(self.root)
        self.assertEqual(len(value['templates']), len(library.CATALOG))
        self.assertTrue(all(item['available'] is False for item in value['templates']))
        self.assertEqual(list((self.root / 'system_templates').iterdir()), [])

    def test_inspect_template_uses_memory_cache_for_unchanged_file(self):
        path = self.template()
        first = library.inspect_template(path)
        with patch.object(library, 'load_workbook', side_effect=AssertionError('should hit cache')):
            second = library.inspect_template(path)
        self.assertEqual(first['content_version'], second['content_version'])
        self.assertEqual(first['header_count'], len(library.REQUIRED_HEADERS))

    def test_crud_create_update_delete_and_reset_templates(self):
        # Seed a built-in template first so backup captures it
        beijing_path = self.template(filename='北京-template.xlsx')
        beijing_original = beijing_path.read_bytes()

        # 1. Create via standard header generation
        created = library.create_template(self.root, '杭州', '淘宝闪购', mode='generate')
        self.assertTrue(created['success'])
        self.assertEqual(created['template']['filename'], '杭州-template.xlsx')
        self.assertEqual(created['template']['scope'], '杭州')
        self.assertTrue(created['template']['custom'])
        self.assertTrue(created['template']['available'])

        # Duplicate create is rejected with 409
        with self.assertRaises(library.TemplateError) as dup:
            library.create_template(self.root, '杭州', '淘宝闪购', mode='generate')
        self.assertEqual(dup.exception.status, 409)

        # 2. Update: rename scope and switch business line
        updated = library.update_template(
            self.root,
            '杭州-template.xlsx',
            scope='杭州余杭',
            business_line='美团小象',
        )
        self.assertTrue(updated['success'])
        self.assertEqual(updated['template']['filename'], '杭州余杭-template.xlsx')
        self.assertEqual(updated['template']['scope'], '杭州余杭')
        self.assertEqual(updated['template']['business_line'], '美团灯塔')
        self.assertFalse((self.root / 'system_templates/杭州-template.xlsx').exists())

        # 3. Upload mode validation: invalid xlsx is rejected
        bad_b64 = base64.b64encode(b'not-a-valid-xlsx').decode('ascii')
        with self.assertRaises(library.TemplateError):
            library.create_template(self.root, '苏州', '淘宝闪购', mode='upload', file_base64=bad_b64)

        # Valid upload succeeds
        buf = io.BytesIO()
        wb = Workbook()
        wb.active.title = '申请名单'
        wb.active.append(list(library.SHANGOU_HEADERS))
        wb.save(buf)
        wb.close()
        good_b64 = base64.b64encode(buf.getvalue()).decode('ascii')
        suzhou = library.create_template(self.root, '苏州', '淘宝闪购', mode='upload', file_base64=good_b64)
        self.assertEqual(suzhou['template']['filename'], '苏州-template.xlsx')

        # 4. Delete both a custom template and the built-in 北京 template
        library.delete_template(self.root, '杭州余杭-template.xlsx')
        library.delete_template(self.root, '北京-template.xlsx')
        self.assertFalse((self.root / 'system_templates/北京-template.xlsx').exists())

        # 5. Reset restores built-in 北京 template and removes custom 苏州 template
        reset_res = library.reset_templates(self.root)
        self.assertFalse(reset_res['has_customizations'])
        self.assertTrue((self.root / 'system_templates/北京-template.xlsx').exists())
        self.assertEqual((self.root / 'system_templates/北京-template.xlsx').read_bytes(), beijing_original)
        self.assertFalse((self.root / 'system_templates/苏州-template.xlsx').exists())


if __name__ == '__main__':
    unittest.main()
