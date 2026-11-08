from pathlib import Path
import stat
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from upload_archive import extract_archive, Limits, UploadArchiveError


class UploadArchiveTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=Path(__file__).parent)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / 'source.zip'

    def archive(self, entries):
        with zipfile.ZipFile(self.source, 'w', zipfile.ZIP_STORED, compresslevel=0) as archive:
            for name, value in entries: archive.writestr(name, value)

    def test_unicode_paths_and_nested_files_preserve_bytes(self):
        self.archive([('深圳/配送费.csv', b'123'), ('深圳/template.xlsx', b'456')])
        before = self.source.read_bytes()
        result = extract_archive(self.source, self.root / 'output')
        self.assertEqual(result, {'success': True, 'files': 2, 'bytes': 6})
        self.assertEqual((self.root/'output/深圳/配送费.csv').read_bytes(), b'123')
        self.assertEqual(self.source.read_bytes(), before)

    def test_file_and_batch_size_have_distinct_errors_before_writing(self):
        self.archive([('配送费.csv', b'x' * 65)])
        with self.assertRaisesRegex(UploadArchiveError, '文件大小超限：配送费.csv'):
            extract_archive(self.source, self.root/'file-limit', Limits(file_bytes=64, total_bytes=128, reserve_bytes=0))
        self.assertEqual(list((self.root/'file-limit').iterdir()), [])
        self.archive([('a.csv', b'x' * 64), ('b.csv', b'y' * 64)])
        with self.assertRaisesRegex(UploadArchiveError, '总大小超限'):
            extract_archive(self.source, self.root/'batch-limit', Limits(file_bytes=64, total_bytes=127, reserve_bytes=0))
        self.assertEqual(list((self.root/'batch-limit').iterdir()), [])

    def test_paths_links_windows_collisions_and_duplicates_are_rejected(self):
        cases = [('../escape.csv', b'x'), ('C:/escape.csv', b'x'), ('\\server\\share.csv', b'x'),
                 ('CON.csv', b'x'), ('a./file.csv', b'x')]
        for i, entry in enumerate(cases):
            with self.subTest(entry=entry[0]):
                self.archive([entry])
                with self.assertRaises(UploadArchiveError):extract_archive(self.source, self.root/str(i))
        self.archive([('A.csv', b'x'), ('a.csv', b'y')])
        with self.assertRaisesRegex(UploadArchiveError, '重复文件路径'):extract_archive(self.source, self.root/'duplicate')
        self.archive([('a.csv', b'x'), ('a.csv/b.csv', b'y')])
        with self.assertRaisesRegex(UploadArchiveError, '路径冲突'):extract_archive(self.source, self.root/'collision')
        self.archive([('bad_tail.csv', b'x')]);self.source.write_bytes(self.source.read_bytes().replace(b'bad_tail.csv',b'bad\x00tail.csv'))
        with self.assertRaisesRegex(UploadArchiveError, '路径无效'):extract_archive(self.source, self.root/'nul-case')
        link = zipfile.ZipInfo('link.csv');link.create_system=3;link.external_attr=(stat.S_IFLNK | 0o777) << 16
        self.archive([(link, b'../escape')])
        with self.assertRaisesRegex(UploadArchiveError, '链接或特殊文件'):extract_archive(self.source, self.root/'link')

    def test_insufficient_disk_space_is_reported_without_extracting(self):
        self.archive([('a.csv', b'x' * 64)])
        with patch('upload_archive.shutil.disk_usage', return_value=type('Disk', (), {'free': 32})()):
            with self.assertRaisesRegex(UploadArchiveError, '磁盘空间不足'):extract_archive(self.source, self.root/'disk')
        self.assertEqual(list((self.root/'disk').iterdir()), [])

    def test_crc_corruption_reports_the_file_and_retains_upload(self):
        self.archive([('a.csv', b'one two three')])
        body = bytearray(self.source.read_bytes());start=body.find(b'one two three');self.assertGreater(start, 0);body[start] ^= 1;self.source.write_bytes(body)
        with self.assertRaisesRegex(UploadArchiveError, '解压失败：a.csv'):extract_archive(self.source, self.root/'corrupt')
        self.assertTrue(self.source.is_file())

    def test_default_limit_accepts_over_previous_200_mib_without_whole_file_read(self):
        # The actual large-file benchmark is isolated from the fast regression suite.
        self.assertEqual(Limits().file_bytes, 4 * 1024**3)
        self.assertEqual(Limits().total_bytes, 10 * 1024**3)
        self.archive([('a.csv', b'x' * (2 * 1024**2 + 17))])
        original = zipfile.ZipExtFile.read
        reads=[]
        def bounded(stream, n=-1):
            reads.append(n);self.assertGreater(n, 0);self.assertLessEqual(n, 1024**2)
            return original(stream, n)
        with patch.object(zipfile.ZipExtFile, 'read', bounded):extract_archive(self.source, self.root/'bounded')
        self.assertGreater(len(reads), 2)
