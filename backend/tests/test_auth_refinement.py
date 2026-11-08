import contextlib
import json
from pathlib import Path
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from fastapi import HTTPException
import requests
import auth_browser_runtime as runtime
import auth_diagnostics as diagnostics
import binding_source_auth as sources
import platform_auth_control as control
import xiaoxiang_source_auth as xiang


def page(url, closed=False):
    return SimpleNamespace(url=url, is_closed=lambda: closed)


class AuthRefinementTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.addCleanup(self.temp.cleanup)
        self.files = patch.object(control, 'files', side_effect=lambda source: [self.root / (source + '.dpapi')])
        self.files.start(); self.addCleanup(self.files.stop)
        self.auth = sources.SourceAuth()
        self.target = patch.object(sources, 'AUTH', self.auth)
        self.target.start(); self.addCleanup(self.target.stop)
        self.source_root = patch.object(sources, 'ROOT', self.root)
        self.source_root.start(); self.addCleanup(self.source_root.stop)
        control.META.clear()
        self.addCleanup(control.META.clear)

    def test_trusted_popup_is_selected_and_unrelated_page_is_ignored(self):
        main = page('https://madouren.cdevelopment.cn/admin/login')
        popup = page('https://login.dingtalk.com/oauth')
        unrelated = page('https://untrusted.example/login')
        context = SimpleNamespace(pages=[main, popup, unrelated])
        self.assertIs(runtime.active_page('lanorange', context, main), popup)

    def test_closed_popup_returns_to_main(self):
        main = page('https://merchant.shangyiworker.com/login')
        popup = page('https://merchant.shangyiworker.com/login', closed=True)
        self.assertIs(runtime.active_page('baize', SimpleNamespace(pages=[main, popup]), popup), main)

    def test_no_trusted_page_fails_without_displaying_unrelated_site(self):
        other = page('https://untrusted.example/login')
        with self.assertRaises(RuntimeError):
            runtime.active_page('baize', SimpleNamespace(pages=[other]), other)

    def test_page_switch_drops_old_commands_and_form_bindings(self):
        main = page('https://madouren.cdevelopment.cn/admin/login')
        popup = page('https://login.dingtalk.com/oauth')
        self.auth.inputs['lanorange'] = [('fill', {'text': 'synthetic-secret'})]
        self.auth.desktop['lanorange'] = {'form_id': 'old'}
        self.auth.form_bindings['lanorange'] = {'old': Mock()}
        self.assertIs(self.auth._active_page('lanorange', SimpleNamespace(pages=[main,popup]), main), popup)
        self.assertNotIn('lanorange', self.auth.inputs)
        self.assertNotIn('lanorange', self.auth.form_bindings)

    def test_navigation_is_bounded_single_attempt_and_cancel_prevents_it(self):
        target = Mock(); cancelled = threading.Event()
        runtime.navigate(target, 'https://merchant.shangyiworker.com/login', cancelled)
        target.goto.assert_called_once_with('https://merchant.shangyiworker.com/login', wait_until='commit', timeout=10000)
        cancelled.set()
        with self.assertRaises(RuntimeError): runtime.navigate(target, 'https://merchant.shangyiworker.com/login', cancelled)
        self.assertEqual(target.goto.call_count, 1)

    def test_cancel_blocks_input_and_duplicate_start(self):
        self.auth.states['baize'] = {'state':'waiting_login','session_id':'synthetic'}
        self.auth.cancelled['baize'] = threading.Event()
        self.auth.cancel('baize')
        self.assertTrue(self.auth.status('baize')['cancelling'])
        with self.assertRaises(HTTPException): self.auth.interact('baize', {'session_id':'synthetic','action':'key','key':'Enter'})
        with patch('threading.Thread') as thread: self.auth.start('baize')
        thread.assert_not_called()

    def test_cancel_stops_queued_official_actions(self):
        target=Mock();target.url='https://merchant.shangyiworker.com/login'
        self.auth.cancelled['baize']=threading.Event();self.auth.cancelled['baize'].set()
        self.auth.inputs['baize']=[('key',{'key':'Enter'})]
        self.auth._apply_inputs('baize',target,{'width':1100,'height':850})
        target.keyboard.press.assert_not_called()

    def test_lightweight_check_does_not_query_board_or_claim_full_verification(self):
        (self.root/'xiaoxiang.dpapi').write_bytes(b'synthetic')
        auth = xiang.XiangAuth()
        with patch.object(control, 'target', return_value=auth), patch.object(xiang.xiaoxiang_lighthouse, 'load_state', return_value={'cookies':[]}), patch.object(auth,'probe_lighthouse') as light, patch('xiaoxiang_board.board_probe') as board:
            result = control.check('xiaoxiang')
        light.assert_called_once(); board.assert_not_called()
        self.assertEqual(result['state'],'partial')
        self.assertEqual(result['stages']['board'],'unknown')

    def test_deep_check_bypasses_light_cache_and_verifies_both_stages(self):
        (self.root/'xiaoxiang.dpapi').write_bytes(b'synthetic')
        auth = xiang.XiangAuth()
        with patch.object(control, 'target', return_value=auth), patch.object(xiang.xiaoxiang_lighthouse,'load_state',return_value={'cookies':[]}), patch.object(auth,'probe_lighthouse') as light, patch('xiaoxiang_board.board_probe') as board:
            control.check('xiaoxiang')
            result = control.check('xiaoxiang',deep=True)
        self.assertEqual(light.call_count,2)
        board.assert_called_once_with({'cookies':[]}, timeout=(3,8))
        self.assertEqual(result['state'],'ready')
        self.assertEqual(result['verification_level'],'deep')

    def test_deep_check_board_expiry_reports_partial_instead_of_logged_out(self):
        (self.root/'xiaoxiang.dpapi').write_bytes(b'synthetic')
        auth = xiang.XiangAuth()
        with patch.object(control, 'target', return_value=auth), patch.object(xiang.xiaoxiang_lighthouse,'load_state',return_value={'cookies':[]}), \
             patch.object(auth,'probe_lighthouse'), patch('xiaoxiang_board.board_probe',side_effect=xiang.SessionExpired('board expired')):
            result = control.check('xiaoxiang',deep=True)
        self.assertEqual(result['state'],'partial')
        self.assertIn('看板',result['message'])
        self.assertEqual(result['stages'],{'lighthouse':'ready','board':'error'})

    def test_auth_request_bound_does_not_change_business_default(self):
        session = Mock(); original = session.post
        runtime.bounded_requests(session)
        session.post('https://synthetic.invalid', timeout=60, json={})
        original.assert_called_once_with('https://synthetic.invalid',timeout=(3,8),json={})

    def test_persisted_diagnostics_are_bounded_and_do_not_restore_ready(self):
        for i in range(30):
            diagnostics.record('baize', {'state':'ready','checked_at':f'2026-10-27T00:00:{i:02d}Z', 'duration_ms':12,'password':'secret','token':'secret'})
        rows = diagnostics.history('baize')
        self.assertEqual(len(rows),5)
        self.assertNotIn('secret',(self.root/'auth-diagnostics.json').read_text('utf8'))
        self.assertLessEqual(len(json.loads((self.root/'auth-diagnostics.json').read_text('utf8'))),20)
        self.assertEqual(control.status('baize')['state'],'signed_out')
        self.assertEqual(len(control.status('baize')['diagnostics']),5)

    def test_unknown_probe_keeps_last_identity_but_never_saves_exception(self):
        (self.root/'baize.dpapi').write_bytes(b'synthetic')
        self.auth.states['baize']={'state':'ready','account_label':'Synthetic user'}
        with patch.object(control,'probe',side_effect=requests.Timeout('password=secret')):
            result=control.check('baize')
        self.assertEqual(result['state'],'unknown')
        self.assertEqual(result['account_label'],'Synthetic user')
        self.assertEqual(result['diagnostics'][-1]['error_code'],'TIMEOUT')
        self.assertNotIn('secret',str(result))

    def test_unwritable_diagnostics_do_not_fail_check(self):
        with patch.object(diagnostics,'record',return_value=False): result=control.check('baize')
        self.assertEqual(result['state'],'signed_out')
        self.assertFalse(result['diagnostics_saved'])

    def test_explicit_organization_id_is_not_invented_account_name(self):
        result=control.display_identity({'agencyId':123})
        self.assertEqual(result,{'organization_reference':'123'})


if __name__ == '__main__': unittest.main()
