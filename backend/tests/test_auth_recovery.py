import contextlib
import tempfile
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import requests
from fastapi import HTTPException
import binding_source_auth as source
import binding_sources_http as http
import platform_auth_control as control
import xiaoxiang_source_auth as xiang
import fengshen_auth_routes as wind


class RecoveryTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        self.addCleanup(self.temp.cleanup)
        patcher=patch.object(source,'ROOT',self.root);patcher.start();self.addCleanup(patcher.stop)
        self.auth=source.SourceAuth()
        self.token=self.root/'baize.dpapi';self.token.write_bytes(b'synthetic-encrypted-session')

    def test_server_error_keepalive_preserves_session_without_claiming_expiry(self):
        with patch.object(source,'load_token',return_value='synthetic-token'),patch.object(source,'client',return_value=contextlib.nullcontext(Mock())),patch.object(source,'identity',side_effect=source.SourceProbeUnavailable('500')):
            self.assertFalse(self.auth.keepalive('baize'))
        status=self.auth.status('baize');self.assertEqual(status['state'],'unknown');self.assertNotIn('过期',status['message']);self.assertEqual(self.token.read_bytes(),b'synthetic-encrypted-session')

    def test_explicit_unauthorized_keepalive_requests_login_without_deleting(self):
        with patch.object(source,'load_token',return_value='synthetic-token'),patch.object(source,'client',return_value=contextlib.nullcontext(Mock())),patch.object(source,'identity',side_effect=source.SourceAuthenticationRequired('401')):
            self.assertFalse(self.auth.keepalive('baize'))
        self.assertEqual(self.auth.status('baize')['state'],'login_required');self.assertTrue(self.token.exists())

    def test_business_identity_error_never_opens_login_or_refreshes(self):
        session=Mock()
        with patch.object(http,'client',return_value=session),patch.object(http,'identity',side_effect=source.SourceProbeUnavailable('500')),patch.object(http.AUTH,'refresh') as refresh,patch.object(http.AUTH,'start') as start:
            with self.assertRaises(source.SourceProbeUnavailable):http.authenticated('baize',lambda *_:None,Mock())
        refresh.assert_not_called();start.assert_not_called();session.close.assert_called_once()

    def test_unconfirmed_refresh_does_not_start_authentication(self):
        with patch.object(http,'client',side_effect=source.SourceAuthenticationRequired('401')),patch.object(http.AUTH,'refresh',return_value=False),patch.object(http.AUTH,'status',return_value={'state':'unknown'}),patch.object(http.AUTH,'start') as start:
            with self.assertRaises(source.SourceProbeUnavailable):http.authenticated('baize',lambda *_:None,Mock())
        start.assert_not_called()

    def test_http_probe_rejects_unexpected_payload_as_unknown(self):
        for payload in ([],{'code':500},{'code':403},{'code':200,'data':[]}):
            session=Mock();session.get.return_value=SimpleNamespace(status_code=200,json=lambda:payload)
            with self.assertRaises(source.SourceProbeUnavailable):source.identity('baize',session)

    def test_http_status_precedes_body_and_only_trusted_login_redirect_is_expired(self):
        session=Mock()
        session.get.return_value=SimpleNamespace(status_code=500,json=lambda:{'code':401})
        with self.assertRaises(source.SourceProbeUnavailable):source.identity('baize',session)
        session.get.return_value=SimpleNamespace(status_code=302,headers={'Location':'https://merchant.shangyiworker.com/login'})
        with self.assertRaises(source.SourceAuthenticationRequired):source.identity('baize',session)
        session.get.return_value=SimpleNamespace(status_code=302,headers={'Location':'https://untrusted.example/login'})
        with self.assertRaises(source.SourceProbeUnavailable):source.identity('baize',session)

    def test_old_manual_probe_does_not_mask_new_keepalive_failure(self):
        self.auth.states['baize']={'state':'unknown','message':'latest failure','checked_at':'2026-10-27T02:00:00+00:00'}
        with patch.object(source,'AUTH',self.auth),patch.dict(control.META,{'baize':{'state':'ready','checked_at':'2026-10-27T01:00:00+00:00','session_version':control.version('baize')}},clear=True):
            self.assertEqual(control.status('baize')['state'],'unknown')

    def test_legacy_wind_clear_requires_confirmed_session_version(self):
        broker=Mock();broker.active=None
        with patch.object(wind,'auth_owner',return_value='owner'),patch.object(wind,'BROKER',broker),patch.object(control,'disconnect') as disconnect,patch.object(control,'version') as current_version:
            with self.assertRaises(HTTPException):wind.clear(Mock(),{})
            wind.clear(Mock(),{'confirm':True,'session_version':'snapshot-before-switch'})
        disconnect.assert_called_once_with('fengshen','snapshot-before-switch');current_version.assert_not_called()

    def test_partial_xiang_auth_can_resume_board_without_first_login(self):
        auth=xiang.XiangAuth();auth.resume_state={'cookies':[],'origins':[]};auth.resume_until=float('inf')
        auth.probe_lighthouse=Mock(return_value=None);auth._wait_lighthouse=Mock(side_effect=AssertionError('must not ask for first login again'));auth._wait_board=Mock(return_value=True)
        with patch('playwright.sync_api.sync_playwright') as pw,patch.object(xiang.xiaoxiang_lighthouse,'load_state') as load,patch.object(xiang.xiaoxiang_lighthouse,'save_state') as save,patch.object(xiang.xiaoxiang_board,'board_probe',side_effect=xiang.SessionExpired('board expired')):
            auth._login()
        auth.probe_lighthouse.assert_called_once();auth._wait_lighthouse.assert_not_called();auth._wait_board.assert_called_once();load.assert_not_called();save.assert_called_once()
        self.assertEqual(auth.status()['stages'],{'lighthouse':'ready','board':'ready'});self.assertIsNone(auth.resume_state)

    def test_partial_xiang_network_failure_preserves_memory_and_avoids_browser(self):
        auth=xiang.XiangAuth();saved={'cookies':[],'origins':[]};auth.resume_state=saved;auth.resume_until=float('inf');auth.probe_lighthouse=Mock(side_effect=requests.Timeout())
        with patch('playwright.sync_api.sync_playwright') as pw,patch.object(xiang.xiaoxiang_lighthouse,'save_state') as save:
            auth._login()
        self.assertEqual(auth.status()['state'],'unknown');self.assertIs(auth.resume_state,saved);pw.assert_not_called();save.assert_not_called()

    def test_second_stage_failure_persists_partial_and_keeps_resume_in_memory(self):
        auth=xiang.XiangAuth();auth._wait_lighthouse=Mock(return_value=True);auth._wait_board=Mock(side_effect=xiang.SessionExpired('board expired'))
        with patch('playwright.sync_api.sync_playwright') as pw,patch.object(xiang.xiaoxiang_lighthouse,'load_state',return_value=None),patch.object(xiang.xiaoxiang_board,'load_board_state',return_value=None),patch.object(xiang.xiaoxiang_lighthouse,'save_state') as save:
            context=pw.return_value.__enter__.return_value.chromium.launch.return_value.new_context.return_value
            context.storage_state.return_value={'cookies':[],'origins':[]}
            auth._login()
        save.assert_called_once_with({'cookies':[],'origins':[]});self.assertEqual(auth.status()['state'],'saved')
        self.assertIsNotNone(auth.resume_state);self.assertEqual(auth.status()['stages'],{'lighthouse':'ready','board':'error'})

    def test_board_sso_cache_needs_only_the_meituan_scan(self):
        auth=xiang.XiangAuth();auth._wait_lighthouse=Mock(return_value=True);auth._wait_board=Mock(return_value=True)
        seed={'cookies':[{'name':'mall.fe.pc_ssoid','value':'synthetic','domain':'zl.meituan.com','path':'/'}],'origins':[]}
        final={'cookies':seed['cookies']+[{'name':'token2','value':'synthetic','domain':'.meituan.com','path':'/'}],'origins':[]}
        with patch('playwright.sync_api.sync_playwright') as pw, \
             patch.object(xiang.xiaoxiang_lighthouse,'load_state',return_value=None), \
             patch.object(xiang.xiaoxiang_board,'load_board_state',return_value=seed), \
             patch.object(xiang.xiaoxiang_board,'board_probe') as board_probe, \
             patch.object(xiang.xiaoxiang_lighthouse,'save_state') as save, \
             patch.object(xiang.xiaoxiang_board,'save_board_state') as save_board:
            context=pw.return_value.__enter__.return_value.chromium.launch.return_value.new_context.return_value
            context.storage_state.return_value=final
            auth._login()
        board_probe.assert_called_once_with(seed,timeout=(3,8))
        launch=pw.return_value.__enter__.return_value.chromium.launch
        self.assertEqual(launch.return_value.new_context.call_args.kwargs['storage_state'],seed)
        save.assert_called_once_with(final);save_board.assert_called_once_with(final)
        status=auth.status();self.assertEqual(status['state'],'ready');self.assertTrue(status['board_reused'])
        self.assertFalse(status['lighthouse_reused'])
        self.assertEqual(status['stages'],{'lighthouse':'ready','board':'ready'})

    def test_expired_board_cache_is_discarded_and_board_scan_remains(self):
        auth=xiang.XiangAuth();auth._wait_lighthouse=Mock(return_value=True);auth._wait_board=Mock(return_value=True)
        seed={'cookies':[{'name':'mall.fe.pc_ssoid','value':'synthetic','domain':'zl.meituan.com','path':'/'}],'origins':[]}
        with patch('playwright.sync_api.sync_playwright') as pw, \
             patch.object(xiang.xiaoxiang_lighthouse,'load_state',return_value=None), \
             patch.object(xiang.xiaoxiang_board,'load_board_state',return_value=seed), \
             patch.object(xiang.xiaoxiang_board,'board_probe',side_effect=xiang.SessionExpired('board expired')), \
             patch.object(xiang.xiaoxiang_board,'discard_board_state') as discard, \
             patch.object(xiang.xiaoxiang_lighthouse,'save_state'), \
             patch.object(xiang.xiaoxiang_board,'save_board_state'):
            pw.return_value.__enter__.return_value.chromium.launch.return_value.new_context.return_value.storage_state.return_value={'cookies':[],'origins':[]}
            auth._login()
        discard.assert_called_once()
        launch=pw.return_value.__enter__.return_value.chromium.launch
        self.assertNotIn('storage_state',launch.return_value.new_context.call_args.kwargs)
        self.assertFalse(auth.status()['board_reused'])


if __name__=='__main__':unittest.main()
