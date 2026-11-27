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

    def test_multi_account_pool_concurrent_login_switch_alias_and_remove(self):
        import platform_account_pool as pool
        with patch.object(control, 'probe', return_value={'account_label': '闪购账号A', 'organization': '杭州商翼'}):
            st1 = control.check('baize')
        self.assertEqual(len(st1['accounts']), 1)
        slot1_id = st1['active_account_id']
        self.assertEqual(st1['accounts'][0]['account_label'], '闪购账号A')
        self.assertTrue(st1['accounts'][0]['is_active'])

        # Prepare adding a 2nd account: active files are cleared while Account A stays in pool
        pool.prepare_add_account('baize', control.files('baize'), st1)
        control._reset_controller_for_new_account('baize')
        st_pending = control.status('baize')
        self.assertFalse(st_pending['saved'])
        self.assertEqual(len(st_pending['accounts']), 1)
        self.assertFalse(st_pending['accounts'][0]['is_active'])

        # Log into Account B
        self.session.write_bytes(b'synthetic-encrypted-token-account-B')
        self.storage.write_bytes(b'synthetic-encrypted-state-account-B')
        with patch.object(control, 'probe', return_value={'account_label': '小象账号B', 'organization': '上海商翼'}):
            st2 = control.check('baize', force=True)
        self.assertEqual(len(st2['accounts']), 2)
        slot2_id = st2['active_account_id']
        self.assertNotEqual(slot1_id, slot2_id)

        # Switch back to Account A in 1 click without re-login
        slot1_data = pool.activate_slot('baize', control.files('baize'), slot1_id, st2)
        control._apply_slot_to_controller('baize', slot1_data)
        st_switched = control.status('baize')
        self.assertEqual(st_switched['active_account_id'], slot1_id)
        self.assertEqual(self.session.read_bytes(), b'synthetic-encrypted-token')
        self.assertEqual(st_switched['account_label'], '闪购账号A')

        # Set custom alias on Account A
        pool.update_slot_alias('baize', control.files('baize'), slot1_id, '华东闪购主号')
        st_aliased = control.status('baize')
        acct1 = next(a for a in st_aliased['accounts'] if a['slot_id'] == slot1_id)
        self.assertEqual(acct1['alias'], '华东闪购主号')

        # Remove active Account A -> automatically recommends next slot (Account B)
        was_active, next_slot_id = pool.remove_slot('baize', control.files('baize'), slot1_id)
        self.assertTrue(was_active)
        self.assertEqual(next_slot_id, slot2_id)
        slot2_data = pool.activate_slot('baize', control.files('baize'), next_slot_id, {'saved': False})
        control._apply_slot_to_controller('baize', slot2_data)
        st_after_remove = control.status('baize')
        self.assertEqual(len(st_after_remove['accounts']), 1)
        self.assertEqual(st_after_remove['active_account_id'], slot2_id)
        self.assertEqual(self.session.read_bytes(), b'synthetic-encrypted-token-account-B')

    def test_summary_aggregates_all_six_platform_statuses(self):
        fake_req = Mock()
        with patch.object(control, 'require_account', return_value={'owner': 'admin', 'role': 'admin'}):
            summary = control.get_summary(fake_req)
        self.assertIn('statuses', summary)
        self.assertIn('checked_at', summary)
        self.assertEqual(set(summary['statuses'].keys()), set(control.KEYS))
        self.assertTrue(summary['statuses']['baize']['saved'])

    def test_activate_account_cancels_in_progress_login_session(self):
        import platform_account_pool as pool
        user = {'owner': 'admin', 'role': 'admin'}
        with patch.object(control, 'probe', return_value={'account_label': '商翼账号1'}):
            st1 = control.check('baize')
        slot1_id = st1['active_account_id']
        pool.prepare_add_account('baize', control.files('baize'), st1)
        control._reset_controller_for_new_account('baize')

        # Simulate an in-progress login worker / waiting_login state when user changes mind and clicks 切换使用
        self.auth.states['baize'] = {'state': 'waiting_login'}
        cancelled = []
        def fake_cancel(src):
            cancelled.append(src)
            self.auth.states[src] = {'state': 'signed_out'}

        with patch.object(control, 'idle_guard', contextlib.nullcontext), \
             patch.object(self.auth, 'cancel', side_effect=fake_cancel):
            switched = control._activate_account_sync('baize', slot1_id, user)
        self.assertEqual(cancelled, ['baize'])
        self.assertEqual(switched['active_account_id'], slot1_id)
        self.assertTrue(switched['saved'])

    def test_activate_account_cancels_fengshen_login_but_blocks_export_verification(self):
        import platform_account_pool as pool
        user = {'owner': 'admin', 'role': 'admin'}
        fs_file = self.root / 'fengshen.dpapi'
        fs_file.write_bytes(b'synthetic-fs-session')
        fake_broker = MagicMock()
        fake_broker.lock = threading.RLock()
        fake_broker.vault = SimpleNamespace(path=fs_file)
        fake_broker.status.return_value = {'state': 'ready', 'saved': True, 'busy': False}
        fake_broker.active = None

        with patch.object(control, 'BROKER', fake_broker), \
             patch.object(control, 'files', return_value=[fs_file]), \
             patch.object(control, 'idle_guard', contextlib.nullcontext), \
             patch.object(control, 'probe', return_value={'account_label': '风神账号1'}):
            st1 = control.check('fengshen')
            slot1_id = st1['active_account_id']
            pool.prepare_add_account('fengshen', [fs_file], st1)

            # 1) Active login-purpose Fengshen session should be cancelled automatically on switch
            fake_broker.active = {'owner': 'admin', 'id': 'chal-login', 'purpose': 'login'}
            def cancel_submit(owner, cid, action):
                self.assertEqual(action, 'cancel')
                fake_broker.active = None
            fake_broker.submit.side_effect = cancel_submit
            switched = control._activate_account_sync('fengshen', slot1_id, user)
            self.assertEqual(switched['active_account_id'], slot1_id)
            fake_broker.submit.assert_called_once_with('admin', 'chal-login', 'cancel')

            # 2) Active export-purpose verification must still reject switching with 409
            fake_broker.active = {'owner': 'admin', 'id': 'chal-export', 'purpose': 'export'}
            with self.assertRaises(HTTPException) as caught:
                control._activate_account_sync('fengshen', slot1_id, user)
            self.assertEqual(caught.exception.status_code, 409)

    def test_slow_probe_does_not_block_status_or_cause_409_on_switch(self):
        user = {'owner': 'admin', 'role': 'admin'}
        with patch.object(control, 'probe', return_value={'account_label': '商翼主号'}):
            st1 = control.check('baize')
        slot1_id = st1['active_account_id']

        probe_entered = threading.Event()
        probe_release = threading.Event()
        probe_errors = []

        def slow_probe(src):
            probe_entered.set()
            probe_release.wait(3)
            return {'account_label': '过时检测结果'}

        def run_check():
            try:
                control.check('baize', force=True)
            except Exception as exc:
                probe_errors.append(exc)

        with patch.object(control, 'probe', side_effect=slow_probe), \
             patch.object(control, 'idle_guard', contextlib.nullcontext), \
             patch.object(control, 'require_account', return_value=user):
            worker = threading.Thread(target=run_check)
            worker.start()
            self.assertTrue(probe_entered.wait(2))

            # status() and get_summary() stay non-blocking while probe() is in flight
            summary = control.get_summary(Mock())
            self.assertIn('baize', summary['statuses'])

            # Switching / preparing new account mid-probe must NOT fail with 409
            pending = control._prepare_add_account_sync('baize', user)
            self.assertTrue(pending['pending_new_account'])
            switched = control._activate_account_sync('baize', slot1_id, user)
            self.assertEqual(switched['active_account_id'], slot1_id)
            self.assertFalse(switched['pending_new_account'])

            probe_release.set()
            worker.join(3)

        self.assertEqual(probe_errors, [])
        # Stale probe result must not clobber the switched slot state
        latest = control.status('baize', user=user)
        self.assertEqual(latest['active_account_id'], slot1_id)
        self.assertEqual(latest['account_label'], '商翼主号')

    def test_concurrent_checks_coalesce_without_409(self):
        entered = threading.Event()
        release = threading.Event()
        calls = 0

        def slow_probe(src):
            nonlocal calls
            calls += 1
            entered.set()
            release.wait(2)
            return {'account_label': '并发复用账号'}

        results = []
        errors = []

        def worker():
            try:
                results.append(control.check('baize', force=True))
            except Exception as exc:
                errors.append(exc)

        with patch.object(control, 'probe', side_effect=slow_probe):
            t1 = threading.Thread(target=worker)
            t1.start()
            self.assertTrue(entered.wait(2))
            t2 = threading.Thread(target=worker)
            t2.start()
            release.set()
            t1.join(3)
            t2.join(3)

        self.assertEqual(errors, [])
        self.assertEqual(len(results), 2)
        self.assertEqual(calls, 1)
        self.assertEqual(results[0]['state'], 'ready')
        self.assertEqual(results[1]['state'], 'ready')

    def test_activate_account_cancels_busy_login_outside_source_lock(self):
        import platform_account_pool as pool
        user = {'owner': 'admin', 'role': 'admin'}
        with patch.object(control, 'probe', return_value={'account_label': '商翼账号A'}):
            st1 = control.check('baize')
        slot1_id = st1['active_account_id']
        pool.prepare_add_account('baize', control.files('baize'), st1)
        control._reset_controller_for_new_account('baize')

        self.auth.states['baize'] = {'state': 'waiting_login'}
        lock_acquired_by_other_thread = []

        def fake_cancel(src):
            def probe_lock():
                lock = control._source_lock(src)
                got = lock.acquire(blocking=False)
                if got:
                    lock.release()
                lock_acquired_by_other_thread.append(got)
            t = threading.Thread(target=probe_lock)
            t.start()
            t.join(2)
            self.auth.states[src] = {'state': 'signed_out'}

        with patch.object(control, 'idle_guard', contextlib.nullcontext), \
             patch.object(self.auth, 'cancel', side_effect=fake_cancel):
            switched = control._activate_account_sync('baize', slot1_id, user)

        self.assertEqual(lock_acquired_by_other_thread, [True])
        self.assertEqual(switched['active_account_id'], slot1_id)


if __name__ == '__main__': unittest.main()
