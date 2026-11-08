from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from atomic_files import atomic_replace
from fengshen_bill import atomic_json


def sharing_error():
    error = PermissionError('synthetic Windows reader lock')
    error.winerror = 32
    return error


class AtomicReplacementTests(unittest.TestCase):
    def test_short_reader_lock_is_retried_without_rewriting_data(self):
        import os
        original = os.replace
        with tempfile.TemporaryDirectory() as folder:
            source, target = Path(folder)/'new', Path(folder)/'old'
            source.write_text('new'); target.write_text('old')
            with patch('atomic_files.os.replace', side_effect=[sharing_error(), sharing_error(), None]) as replace, patch('atomic_files.time.sleep'):
                atomic_replace(source, target)
                self.assertEqual(replace.call_count, 3)
            original(source, target)
            self.assertEqual(target.read_text(), 'new')

    def test_persistent_lock_is_bounded_and_keeps_old_manifest(self):
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder)/'manifest.json'; target.write_text('{"old": true}')
            with patch('atomic_files.os.replace', side_effect=sharing_error()) as replace, patch('atomic_files.time.sleep'):
                with self.assertRaises(PermissionError): atomic_json(target, {'new': True})
                self.assertEqual(replace.call_count, 8)
            self.assertEqual(target.read_text(), '{"old": true}')
            self.assertEqual(list(Path(folder).glob('*.part')), [])

    def test_unrelated_io_error_is_not_retried(self):
        with patch('atomic_files.os.replace', side_effect=OSError('disk full')) as replace, patch('atomic_files.time.sleep') as sleep:
            with self.assertRaises(OSError): atomic_replace('new', 'old')
            replace.assert_called_once(); sleep.assert_not_called()

    def test_manifest_failure_preserves_created_job_for_resume(self):
        import payroll_inputs as inputs
        state = {'id': 'batch-original', 'jobs': []}
        def created_then_locked(folder, current, manager):
            current['jobs'].append('download-original')
            raise sharing_error()
        with patch('payroll_inputs.start_download', side_effect=created_then_locked) as start, patch('payroll_inputs.save') as save:
            with self.assertRaisesRegex(inputs.SourceError, '原批次编号'):
                inputs.start_download_resumable(Path('batch-original'), state, object())
            start.assert_called_once()
            save.assert_called_once()
        self.assertEqual(state['jobs'], ['download-original'])
        self.assertEqual(state['id'], 'batch-original')
        self.assertEqual(state['status'], 'pending_download')
