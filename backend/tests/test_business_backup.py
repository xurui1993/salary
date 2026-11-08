import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sqlite3
import tempfile
import unittest
from contextlib import closing

SPEC = importlib.util.spec_from_file_location('business_backup', Path(__file__).resolve().parents[2] / 'scripts/business_backup.py')
backup = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(backup)


class BusinessBackupTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / 'project'
        self.destination = Path(self.temp.name) / 'snapshots'
        (self.root / 'data').mkdir(parents=True)
        (self.root / 'data/config.json').write_text('{"rule":5}', encoding='utf-8')

    def snapshot(self):
        return backup.backup(self.root, self.destination)

    def rewrite_manifest(self, path, mutate):
        file = path / 'manifest.json'
        value = json.loads(file.read_text(encoding='utf-8'))
        mutate(value)
        file.write_text(json.dumps(value), encoding='utf-8')
        (path/'manifest.sha256').write_text(backup.sha256(file), encoding='ascii')

    def test_snapshot_and_restore_preserve_exact_files_and_sqlite_rows(self):
        db = sqlite3.connect(self.root/'data/business.sqlite3')
        db.execute('CREATE TABLE records(id TEXT PRIMARY KEY,value TEXT)')
        db.execute('INSERT INTO records VALUES (?,?)', ('00123','original'))
        db.commit()
        db.close()
        before = (self.root/'data/config.json').read_bytes()
        snapshot = self.snapshot()
        value = backup.verify(snapshot)
        self.assertEqual(len(value['files']), 2)
        target = Path(self.temp.name)/'restored'
        self.assertEqual(backup.restore(snapshot, target)['files_verified'], 2)
        self.assertEqual((target/'data/config.json').read_bytes(), before)
        with closing(sqlite3.connect(target/'data/business.sqlite3')) as result:
            self.assertEqual(result.execute('select * from records').fetchall(), [('00123','original')])
        self.assertEqual((self.root/'data/config.json').read_bytes(), before)

    def test_old_business_directories_have_no_expiry(self):
        old = self.root/'uploads/old-batch'
        old.mkdir(parents=True)
        (old/'source.csv').write_text('protected', encoding='utf-8')
        os.utime(old, (1,1))
        value = backup.verify(self.snapshot())
        self.assertTrue(any(file['path']=='uploads/old-batch/source.csv' for file in value['files']))
        self.assertTrue((old/'source.csv').exists())

    def test_wal_snapshot_captures_committed_rows_without_creating_auxiliary_files(self):
        with closing(sqlite3.connect(self.root/'data/wal.sqlite3')) as original:
            original.execute('PRAGMA journal_mode=WAL')
            original.execute('CREATE TABLE evidence(value TEXT)')
            original.execute("INSERT INTO evidence VALUES ('retained')")
            original.commit()
            snapshot = self.snapshot()
            backup.verify(snapshot)
            backup.verify(snapshot)
            self.assertEqual(list((snapshot/'files').rglob('*-wal')), [])
            self.assertEqual(list((snapshot/'files').rglob('*-shm')), [])
            with closing(sqlite3.connect((snapshot/'files/data/wal.sqlite3').as_uri()+'?immutable=1', uri=True)) as restored:
                self.assertEqual(restored.execute('select value from evidence').fetchall(), [('retained',)])

    def test_running_service_blocks_backup_and_keeps_lock(self):
        lock = self.root/'backend/.local_downloads/server.lock'
        lock.parent.mkdir(parents=True)
        original = json.dumps({'pid':os.getpid(),'token':'service'})
        lock.write_text(original)
        with self.assertRaises(ValueError):
            self.snapshot()
        self.assertEqual(lock.read_text(), original)
        self.assertFalse(self.destination.exists())

    def test_restore_never_overwrites_existing_directory(self):
        snapshot = self.snapshot()
        with self.assertRaises(ValueError):
            backup.restore(snapshot, self.root)
        self.assertEqual((self.root/'data/config.json').read_text(), '{"rule":5}')

    def test_corruption_or_tampered_manifest_fails_before_restore(self):
        snapshot = self.snapshot()
        (snapshot/'files/data/config.json').write_bytes(b'changed')
        target = Path(self.temp.name)/'restored'
        with self.assertRaises(ValueError):
            backup.restore(snapshot, target)
        self.assertFalse(target.exists())

    def test_traversal_and_duplicate_paths_in_manifest_are_rejected(self):
        snapshot = self.snapshot()
        self.rewrite_manifest(snapshot, lambda value:value['files'][0].update(path='../outside'))
        with self.assertRaises(ValueError):
            backup.verify(snapshot)
        snapshot = self.snapshot()
        self.rewrite_manifest(snapshot, lambda value:value['files'].append(dict(value['files'][0])))
        with self.assertRaises(ValueError):
            backup.verify(snapshot)

    def test_backup_cannot_recurse_into_its_own_source_tree(self):
        with self.assertRaises(ValueError):
            backup.backup(self.root, self.root/'data/backups')


if __name__ == '__main__':
    unittest.main()
