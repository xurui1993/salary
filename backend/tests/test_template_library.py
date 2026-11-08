import asyncio
import hashlib
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

    def template(self, headers=library.REQUIRED_HEADERS):
        path = self.root / 'system_templates/北京-template.xlsx'
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


if __name__ == '__main__':
    unittest.main()
