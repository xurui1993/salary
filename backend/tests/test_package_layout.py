import importlib.util
from pathlib import Path
import unittest
import json
import tempfile
from unittest.mock import patch
import zipfile

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('home_package', ROOT / 'scripts/pack_home_package.py')
package = importlib.util.module_from_spec(spec)
spec.loader.exec_module(package)


class PackageLayoutTests(unittest.TestCase):
    def test_migrated_project_is_complete_without_local_workspaces_or_retired_template(self):
        self.assertEqual(package.ROOT, ROOT)
        entries = package.collect()
        names = {path.as_posix() for path, _ in entries}
        self.assertTrue(set(package.REQUIRED).issubset(names))
        self.assertIn('tests/fixtures/company_baseline.json', names)
        self.assertIn('tests/fixtures/followup_header.json', names)
        self.assertNotIn('system_templates/异常骑手跟进模板.xlsx', names)
        self.assertFalse(any(name.startswith(('data/workspaces/', 'runtime/', 'archive/', 'uploads/', 'outputs/')) for name in names))
        self.assertFalse(any('/.local_auth' in name or '/.local_downloads' in name for name in names))

    def test_source_package_has_only_four_clear_root_entries(self):
        names={path.as_posix() for path,_ in package.collect_project()}
        roots={name.split('/')[0] for name in names}
        self.assertEqual(roots,{'启动系统.cmd','README.md','app','docs'})
        self.assertIn('app/backend/main.py',names);self.assertIn('app/src/App.tsx',names)

    def test_source_package_excludes_rebuildable_and_operational_files(self):
        names={path.as_posix() for path,_ in package.collect_project()}
        self.assertNotIn('app/gateway/template.zip',names)
        self.assertFalse(any(name.startswith(('app/dist/','app/node_modules/','app/runtime/','app/data/')) for name in names))

    def fixture(self):
        temporary = tempfile.TemporaryDirectory(prefix='tmp_package_', dir=Path(__file__).parent)
        self.addCleanup(temporary.cleanup)
        parent = Path(temporary.name)
        root = parent / 'repository'
        for name in package.REQUIRED:
            source = root / name
            source.parent.mkdir(parents=True, exist_ok=True)
            source.write_text('fixture source', encoding='utf-8')
        wrapper = root / 'scripts/package_root'
        wrapper.mkdir(parents=True)
        for name in ('README.md', '启动系统.cmd'):
            (wrapper / name).write_text('fixture wrapper', encoding='utf-8')
        (root / 'docs').mkdir()
        (root / 'docs/guide.md').write_text('repository guide', encoding='utf-8')
        (parent / 'docs').mkdir()
        (parent / 'docs/foreign.md').write_text('unrelated project', encoding='utf-8')
        return root, wrapper, parent

    def test_portable_package_never_reads_or_writes_parent_docs_and_verifies_fresh_extraction(self):
        root, wrapper, parent = self.fixture()
        for name in ('backend/private.sqlite', 'backend/private.sqlite3-wal', 'backend/.env.local',
                     'backend/private.key', 'backend/tests/tmp_failure/record.json', 'data/customer.json'):
            source = root / name
            source.parent.mkdir(parents=True, exist_ok=True)
            source.write_text('private fixture', encoding='utf-8')
        archive = parent / 'delivery.zip'
        with patch.object(package, 'ROOT', root), patch.object(package, 'WRAPPER_ROOT', wrapper):
            result = package.package(archive)
        self.assertTrue(result['crc_verified'])
        self.assertTrue(result['file_hashes_verified'])
        self.assertTrue(result['fresh_extraction_verified'])
        self.assertEqual({path.name for path in (parent / 'docs').iterdir()}, {'foreign.md'})
        with zipfile.ZipFile(archive) as zipped:
            names = zipped.namelist()
            self.assertIn('薪酬工作台/docs/guide.md', names)
            self.assertFalse(any('foreign' in name or 'private' in name or 'tmp_failure' in name or 'customer' in name for name in names))
            manifest = json.loads(zipped.read('薪酬工作台/docs/SOURCE_MANIFEST.json'))
            self.assertEqual(len(manifest['files']), result['files'] - 2)
        self.assertTrue(archive.with_suffix('.zip.verification.json').is_file())

    def test_corrupt_payload_is_rejected_even_when_zip_crc_is_valid(self):
        root, wrapper, parent = self.fixture()
        archive, altered = parent / 'delivery.zip', parent / 'altered.zip'
        with patch.object(package, 'ROOT', root), patch.object(package, 'WRAPPER_ROOT', wrapper):
            package.package(archive)
        with zipfile.ZipFile(archive) as source, zipfile.ZipFile(altered, 'w') as target:
            for entry in source.infolist():
                data = source.read(entry.filename)
                target.writestr(entry, b'changed source' if entry.filename.endswith('/app/server.ts') else data)
        with self.assertRaisesRegex(ValueError, 'source hash mismatch'):
            package.verify_package(altered)


if __name__ == '__main__': unittest.main()
