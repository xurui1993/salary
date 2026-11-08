import contextlib
from pathlib import Path
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, Mock, patch

import requests
from fastapi import HTTPException
import binding_source_auth as sources
import platform_auth_control as control
from fengshen_bill import AuthenticationRequired


class PlatformControlTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.session = self.root / 'baize.dpapi'
        self.session.write_bytes(b'synthetic-encrypted-token')
        self.storage = self.root / 'baize.storage'
        self.storage.write_bytes(b'synthetic-encrypted-browser-state')
        self.auth = sources.SourceAuth()
        self.patches = [patch.object(sources, 'ROOT', self.root), patch.object(sources, 'AUTH', self.auth)]
        for p in self.patches: p.start()
        control.META.clear()
        self.addCleanup(self.temp.cleanup)
        for p in self.patches: self.addCleanup(p.stop)

    def test_checks_reuse_without_login_and_deduplicate(self):
        with patch.object(control, 'probe', return_value={'account_label': 'Synthetic user'}) as probe, patch.object(self.auth, 'start') as start:
            first = control.check('baize')
            second = control.check('baize')
        self.assertEqual(first['state'], 'ready')
        self.assertEqual(first['checked_at'], second['checked_at'])
        probe.assert_called_once_with('baize')
        start.assert_not_called()
        self.assertEqual(self.session.read_bytes(), b'synthetic-encrypted-token')

    def test_network_error_is_unknown_and_does_not_discard_session(self):
        with patch.object(control, 'probe', side_effect=requests.Timeout('secret=never-render')):
            result = control.check('baize')
        self.assertEqual(result['state'], 'unknown')
        self.assertTrue(self.session.exists())
        self.assertNotIn('secret=', str(result))

    def test_confirmed_expiry_requests_login_but_retains_files(self):
        with patch.object(control, 'probe', side_effect=AuthenticationRequired('expired')):
            result = control.check('baize')
        self.assertEqual(result['state'], 'login_required')
        self.assertTrue(self.session.exists())
        self.assertTrue(self.storage.exists())

    def test_server_failure_and_permission_error_not_treated_as_expired(self):
        for status in (403, 500):
            session = Mock()
            session.get.return_value = SimpleNamespace(status_code=status, json=lambda: {'code': status})
            with self.assertRaises(sources.BillCollectionError) as caught:
                sources.identity('baize', session)
            self.assertNotIsInstance(caught.exception, sources.SourceAuthenticationRequired)
        session.get.return_value = SimpleNamespace(status_code=401)
        with self.assertRaises(sources.SourceAuthenticationRequired): sources.identity('baize', session)

    def test_identity_projection_masks_private_fields_and_excludes_tokens(self):
        result = control.display_identity({'user': {'userName':'13812345678','token':'secret','password':'private'},'merchantName':'test'})
        self.assertEqual(result['account_label'], '138****5678')
        self.assertEqual(result['organization'], 'test')
        self.assertNotIn('secret', str(result))
        self.assertNotIn('private', str(result))

    def test_disconnect_archives_only_selected_platform_and_blocks_stale_version(self):
        other = self.root / 'lanorange.dpapi'
        other.write_bytes(b'unrelated-synthetic-session')
        with patch.object(control, 'idle_guard', contextlib.nullcontext):
            with self.assertRaises(HTTPException) as caught: control.disconnect('baize', 'stale')
            self.assertEqual(caught.exception.status_code, 409)
            result = control.disconnect('baize', control.version('baize'))
        self.assertEqual(result['state'], 'signed_out')
        self.assertFalse(self.session.exists())
        self.assertFalse(self.storage.exists())
        self.assertEqual(other.read_bytes(), b'unrelated-synthetic-session')
        archived = list((self.root / '.signedout').rglob('*.dpapi'))
        self.assertEqual(len(archived), 1)
        self.assertEqual(archived[0].read_bytes(), b'synthetic-encrypted-token')

    def test_xiaoxiang_disconnect_keeps_board_sso_cache_and_says_so(self):
        path = self.root / 'xiaoxiang.dpapi'
        path.write_bytes(b'synthetic-encrypted-token')
        auth = MagicMock()
        auth.workers, auth.states = {}, {}
        auth.status.side_effect = lambda: {**auth.states.get('xiaoxiang', {}), 'busy': False}
        with patch.object(control, 'files', return_value=[path]), \
             patch.object(control, 'target', return_value=auth), \
             patch.object(control, 'idle_guard', contextlib.nullcontext), \
             patch('xiaoxiang_lighthouse.load_state', return_value={'cookies': [], 'origins': []}), \
             patch('xiaoxiang_board.save_board_state') as cache:
            result = control.disconnect('xiaoxiang', control.version('xiaoxiang'))
        cache.assert_called_once_with({'cookies': [], 'origins': []})
        self.assertFalse(path.exists())
        self.assertIn('本机保留知了看板登录态', result['message'])
        self.assertFalse(result['saved'])

    def test_failed_move_restores_original_session_files(self):
        real_replace = control.os.replace
        def replace(a, b):
            if Path(a) == self.storage: raise OSError('synthetic fault')
            real_replace(a,b)
        with patch.object(control, 'idle_guard', contextlib.nullcontext), patch.object(control.os, 'replace', side_effect=replace):
            with self.assertRaises(HTTPException): control.disconnect('baize', control.version('baize'))
        self.assertEqual(self.session.read_bytes(), b'synthetic-encrypted-token')
        self.assertEqual(self.storage.read_bytes(), b'synthetic-encrypted-browser-state')

    def test_active_auth_cannot_be_disconnected(self):
        self.auth.states['baize'] = {'state': 'waiting_login'}
        with patch.object(control, 'idle_guard', contextlib.nullcontext):
            with self.assertRaises(HTTPException): control.disconnect('baize', control.version('baize'))
        self.assertTrue(self.session.exists())

    def test_running_and_queued_jobs_block_disconnect_without_starting_exports(self):
        import parttime_source, download_jobs, workbench
        manager = Mock()
        manager._lock = threading.RLock()
        connection = Mock()
        connection.execute.return_value.fetchone.return_value = ('active-run',)
        manager._connection.return_value = contextlib.nullcontext(connection)
        with patch.object(download_jobs, 'get_manager', return_value=manager), patch.object(workbench, 'RUNNERS', set()):
            with self.assertRaises(HTTPException) as caught:
                control.disconnect('baize', control.version('baize'))
            self.assertEqual(caught.exception.status_code, 409)
        self.assertTrue(self.session.exists())
        self.assertFalse(parttime_source.COLLECTION_LOCK.locked())

    def test_late_keepalive_cannot_restore_signed_out_state(self):
        entered, release = threading.Event(), threading.Event()
        def identity(*_): entered.set(); release.wait(3)
        with patch.object(sources, 'load_token', return_value='synthetic-token'), patch.object(sources, 'client', return_value=contextlib.nullcontext(Mock())), patch.object(sources, 'identity', side_effect=identity):
            worker = threading.Thread(target=self.auth.keepalive, args=('baize',))
            worker.start()
            self.assertTrue(entered.wait(2))
            with patch.object(control, 'idle_guard', contextlib.nullcontext): control.disconnect('baize', control.version('baize'))
            release.set(); worker.join(3)
        self.assertEqual(self.auth.status('baize')['state'], 'signed_out')

    def test_wind_probe_has_bounded_read_only_http_identity(self):
        import fengshen_http
        fake = Mock()
        fake.identity.return_value = {'userName':'Synthetic wind','agencyId':123}
        with patch.object(control.BROKER.vault, 'load', return_value={'cookies':[],'origins':[]}), patch.object(fengshen_http, 'FengshenHttpClient', return_value=fake):
            result = control.probe('fengshen')
        self.assertEqual(result['account_label'], 'Synthetic wind')
        self.assertEqual(fake.attempts, 1)
        self.assertEqual(fake.timeout, (3,6))
        fake.identity.assert_called_once()
        fake.close.assert_called_once()


if __name__ == '__main__': unittest.main()
