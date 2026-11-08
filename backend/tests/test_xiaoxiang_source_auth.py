"""Two-stage authentication state machine; the browser and session store are mocked."""
from pathlib import Path
import sys
import threading
import time
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import xiaoxiang_source_auth as auth
from xiaoxiang_lighthouse import SessionExpired


class XiangAuthTests(unittest.TestCase):
    def test_auth_browser_prefers_chrome_executable(self):
        from auth_browser_runtime import launch_auth_browser
        pw=Mock()
        with patch('auth_browser_runtime.chrome_executable',return_value=r'C:\Chrome\chrome.exe'):
            launch_auth_browser(pw,headless=True)
        options=pw.chromium.launch.call_args.kwargs
        self.assertEqual(options['executable_path'],r'C:\Chrome\chrome.exe')
        self.assertTrue(options['headless'])
        self.assertNotIn('channel',options)

    def test_auth_browser_falls_back_to_edge_without_chrome(self):
        from auth_browser_runtime import launch_auth_browser
        pw=Mock()
        with patch('auth_browser_runtime.chrome_executable',return_value=None), \
             patch('auth_browser_runtime.edge_executable',return_value=r'C:\Edge\msedge.exe'):
            launch_auth_browser(pw,headless=True)
        self.assertEqual(pw.chromium.launch.call_args.kwargs['executable_path'],r'C:\Edge\msedge.exe')

    def test_valid_saved_both_stages_skip_browser_without_resaving(self):
        instance=auth.XiangAuth();state={'cookies': [],'origins': []}
        with patch.object(auth.xiaoxiang_lighthouse,'load_state',return_value=state), \
             patch.object(instance,'probe_lighthouse') as first, \
             patch.object(auth.xiaoxiang_board,'board_probe') as second, \
             patch.object(auth.xiaoxiang_lighthouse,'save_state') as save, \
             patch('playwright.sync_api.sync_playwright') as browser:
            instance._login()
        first.assert_called_once_with(state);second.assert_called_once_with(state,timeout=(3,8))
        browser.assert_not_called();save.assert_not_called()
        self.assertEqual(instance.status()['state'],'ready')
        self.assertTrue(instance.status()['lighthouse_reused'])
        self.assertEqual(instance.stages,{'lighthouse':'ready','board':'ready'})

    def test_saved_first_stage_resumes_directly_on_board_without_reading_blank_page(self):
        instance=auth.XiangAuth();instance._wait_lighthouse=Mock();instance._wait_board=Mock(return_value=True)
        messages=[];published=instance._set
        instance._set=lambda state,message:(messages.append(message),published(state,message))[1]
        state={'cookies': [],'origins': []}
        def trusted_page(source,context,page):
            self.assertNotEqual(page.url,'about:blank')
            return page
        instance._active_page=Mock(side_effect=trusted_page)
        with patch.object(auth.xiaoxiang_lighthouse,'load_state',return_value=state), \
             patch.object(instance,'probe_lighthouse'), \
             patch.object(auth.xiaoxiang_board,'board_probe',side_effect=SessionExpired('board expired')), \
             patch.object(auth.xiaoxiang_lighthouse,'save_state') as save, \
             patch('playwright.sync_api.sync_playwright') as pw:
            context=pw.return_value.__enter__.return_value.chromium.launch.return_value.new_context.return_value
            page=context.new_page.return_value;page.url='about:blank'
            page.goto.side_effect=lambda url,**kw:setattr(page,'url',url)
            instance._login()
        instance._wait_lighthouse.assert_not_called();instance._wait_board.assert_called_once()
        self.assertEqual([call.args[0] for call in page.goto.call_args_list],[auth.xiaoxiang_board.BOARD_ENTRY])
        save.assert_called_once();self.assertEqual(instance.status()['state'],'ready')
        self.assertTrue(any('已跳过美团扫码' in message for message in messages))
        self.assertTrue(instance.status()['lighthouse_reused'])

    def test_saved_network_failure_preserves_session_and_does_not_open_browser(self):
        instance=auth.XiangAuth()
        with patch.object(auth.xiaoxiang_lighthouse,'load_state',return_value={'cookies': []}), \
             patch.object(instance,'probe_lighthouse',side_effect=auth.LighthouseError('network')), \
             patch.object(auth.xiaoxiang_lighthouse,'save_state') as save, \
             patch('playwright.sync_api.sync_playwright') as browser:
            instance._login()
        browser.assert_not_called();save.assert_not_called();self.assertEqual(instance.status()['state'],'unknown')

    def test_cancel_during_saved_probe_cannot_save_resume_or_report_ready(self):
        instance=auth.XiangAuth();instance.resume_state={'cookies': []};instance.resume_until=time.monotonic()+60
        cancel=threading.Event();instance.cancelled[auth.SOURCE]=cancel
        with patch.object(instance,'probe_lighthouse'), \
             patch.object(auth.xiaoxiang_board,'board_probe',side_effect=lambda *a,**kw:cancel.set()), \
             patch.object(auth.xiaoxiang_lighthouse,'save_state') as save:
            instance._login()
        save.assert_not_called();self.assertNotEqual(instance.status()['state'],'ready')

    def test_slow_http_probe_does_not_block_form_input_processing(self):
        instance=auth.XiangAuth();started=threading.Event();release=threading.Event();processed=threading.Event()
        page=Mock();context=Mock();context.storage_state.return_value={'cookies': []}
        page.wait_for_timeout.side_effect=lambda _:time.sleep(.005)
        instance._active_page=Mock(return_value=page);instance._capture_desktop=Mock()
        def apply(*_):
            if started.is_set():processed.set();release.set()
        instance._apply_inputs=Mock(side_effect=apply)
        def probe(_):
            started.set()
            self.assertTrue(release.wait(2),'Input processing was blocked by status HTTP request')
        try:
            self.assertTrue(instance._probe_until(context,page,probe))
        finally:release.set()
        self.assertTrue(processed.is_set());self.assertGreater(instance._apply_inputs.call_count,1)

    def test_success_for_previous_cookie_snapshot_does_not_verify_new_session(self):
        instance=auth.XiangAuth();first_done=threading.Event();seen=[];page=Mock();context=Mock()
        context.storage_state.side_effect=lambda:{'cookies':[{'name':'session','value':'new' if first_done.is_set() else 'old'}]}
        page.wait_for_timeout.side_effect=lambda _:time.sleep(.005)
        instance._active_page=Mock(return_value=page);instance._capture_desktop=Mock();instance._apply_inputs=Mock()
        def probe(state):
            seen.append(state['cookies'][0]['value']);first_done.set()
        self.assertTrue(instance._probe_until(context,page,probe));self.assertEqual(seen,['old','new'])

    def test_cancelled_probe_worker_cannot_later_mark_login_ready(self):
        instance=auth.XiangAuth();cancel=threading.Event();instance.cancelled[auth.SOURCE]=cancel
        started=threading.Event();release=threading.Event();finished=threading.Event();page=Mock();context=Mock()
        context.storage_state.return_value={'cookies': []};page.wait_for_timeout.side_effect=lambda _:time.sleep(.005)
        instance._active_page=Mock(return_value=page);instance._capture_desktop=Mock()
        instance._apply_inputs=Mock(side_effect=lambda *_:cancel.set() if started.is_set() else None)
        def probe(_):
            started.set();release.wait(2);finished.set()
        try:self.assertFalse(instance._probe_until(context,page,probe))
        finally:release.set()
        self.assertTrue(finished.wait(2));self.assertNotEqual(instance.status()['state'],'ready')

    def test_internal_form_input_uses_owner_without_full_page_capture(self):
        instance=auth.XiangAuth();clock=[3.0];page=Mock();page.url='https://maicaipeisong.meituan.com/notice/list.html';context=Mock()
        instance._headless=False
        page.screenshot.return_value=b'synthetic-image'
        page.wait_for_timeout.side_effect=lambda ms:clock.__setitem__(0,clock[0]+ms/1000)
        seen=[]
        def probe(_):
            seen.append(instance.status())
            if len(seen)==1:
                instance.interact('xiaoxiang',{'session_id':seen[0]['session_id'],'action':'key','key':'Tab'})
                raise SessionExpired('not yet')
        with patch.object(auth.time,'monotonic',side_effect=lambda:clock[0]):
            self.assertTrue(instance._probe_until(context,page,probe))
        self.assertFalse(seen[0]['has_qr']);self.assertTrue(seen[0]['interactive'])
        page.keyboard.press.assert_called_once_with('Tab')
        page.screenshot.assert_not_called()

    def test_saved_session_is_not_claimed_to_be_verified_or_probed_on_status_read(self):
        instance=auth.XiangAuth()
        with patch.object(auth.xiaoxiang_lighthouse.SESSION_FILE.__class__,'exists',return_value=True),patch.object(auth.xiaoxiang_lighthouse,'load_state') as load:
            self.assertEqual(instance.status()['state'],'saved');load.assert_not_called()

    def test_duplicate_start_does_not_open_multiple_login_threads(self):
        instance=auth.XiangAuth()
        with patch('threading.Thread') as thread:
            self.assertEqual(instance.start()['state'],'starting')
            self.assertEqual(instance.start()['state'],'starting')
        self.assertEqual(thread.call_count,1);self.assertEqual(thread.return_value.start.call_count,1)

    def test_only_both_stages_complete_before_saving_and_reporting_ready(self):
        instance=auth.XiangAuth();stages=[]
        instance._wait_lighthouse=Mock(side_effect=lambda *_:stages.append('lighthouse') or True)
        instance._wait_board=Mock(side_effect=lambda *_:stages.append('board') or True)
        with patch.object(auth,'HEADLESS_DEFAULT',False),patch('playwright.sync_api.sync_playwright') as pw,patch.object(auth.xiaoxiang_lighthouse,'load_state',return_value=None),patch.object(auth.xiaoxiang_lighthouse,'save_state') as save:
            browser=pw.return_value.__enter__.return_value.chromium.launch.return_value
            context=browser.new_context.return_value
            instance._login()
        self.assertEqual(stages,['lighthouse','board']);save.assert_called_once_with(context.storage_state.return_value)
        self.assertEqual(instance.status()['state'],'ready');browser.close.assert_called_once()
        self.assertFalse(pw.return_value.__enter__.return_value.chromium.launch.call_args.kwargs['headless'])
        self.assertEqual([c.args[0] for c in context.new_page.return_value.goto.call_args_list],
                         [auth.xiaoxiang_lighthouse.ENTRY,auth.xiaoxiang_board.BOARD_ENTRY])

    def test_second_stage_expiry_persists_first_stage_without_claiming_ready(self):
        instance=auth.XiangAuth();instance._wait_lighthouse=Mock(return_value=True)
        instance._wait_board=Mock(side_effect=SessionExpired('synthetic expiry'))
        with patch('playwright.sync_api.sync_playwright') as pw,patch.object(auth.xiaoxiang_lighthouse,'load_state',return_value=None),patch.object(auth.xiaoxiang_lighthouse,'save_state') as save:
            browser=pw.return_value.__enter__.return_value.chromium.launch.return_value
            context=browser.new_context.return_value
            instance._login()
        save.assert_called_once_with(context.storage_state.return_value)
        status=instance.status()
        self.assertEqual(status['state'],'saved');self.assertNotEqual(status['state'],'ready')
        self.assertEqual(status['stages'],{'lighthouse':'ready','board':'error'})
        self.assertIn('无需重新发送短信',status['message'])
        browser.close.assert_called_once()

    def test_second_stage_window_close_keeps_first_stage_and_retry_skips_lighthouse(self):
        instance=auth.XiangAuth();instance._wait_lighthouse=Mock(return_value=True)
        instance._wait_board=Mock(side_effect=RuntimeError('window closed'))
        with patch('playwright.sync_api.sync_playwright'),patch.object(auth.xiaoxiang_lighthouse,'load_state',return_value=None),patch.object(auth.xiaoxiang_lighthouse,'save_state') as save:
            instance._login()
        save.assert_called_once();self.assertEqual(instance.status()['state'],'saved')
        instance._wait_lighthouse.reset_mock();instance._wait_board.reset_mock()
        instance._wait_board.side_effect=None;instance._wait_board.return_value=True
        with patch.object(instance,'probe_lighthouse'), \
             patch.object(auth.xiaoxiang_board,'board_probe',side_effect=SessionExpired('board expired')), \
             patch.object(auth.xiaoxiang_lighthouse,'save_state') as save, \
             patch('playwright.sync_api.sync_playwright') as pw:
            pw.return_value.__enter__.return_value.chromium.launch.return_value.new_context.return_value.new_page.return_value.url='about:blank'
            instance._login()
        instance._wait_lighthouse.assert_not_called();instance._wait_board.assert_called_once()
        self.assertEqual(instance.status()['state'],'ready');save.assert_called_once()

    def test_probe_retries_only_auth_status_and_returns_after_success(self):
        instance=auth.XiangAuth();instance._headless=False;clock=[0.0];page=Mock();page.url='https://maicaipeisong.meituan.com/notice/list.html';context=Mock()
        page.wait_for_timeout.side_effect=lambda ms:clock.__setitem__(0,clock[0]+ms/1000)
        probe=Mock(side_effect=[SessionExpired('not yet'),None])
        with patch.object(auth.time,'monotonic',side_effect=lambda:clock[0]):
            self.assertTrue(instance._probe_until(context,page,probe))
        self.assertEqual(probe.call_count,2);self.assertLess(clock[0],auth.TIMEOUT)

    def test_headless_fallback_opens_one_visible_window_and_finishes(self):
        instance=auth.XiangAuth();instance._wait_lighthouse=Mock(side_effect=[auth.HeadlessFallback('no fields'),True])
        instance._wait_board=Mock(return_value=True)
        with patch.object(auth,'HEADLESS_DEFAULT',True),patch('playwright.sync_api.sync_playwright') as pw,patch.object(auth.xiaoxiang_lighthouse,'load_state',return_value=None),patch.object(auth.xiaoxiang_lighthouse,'save_state'):
            launch=pw.return_value.__enter__.return_value.chromium.launch
            instance._login()
        self.assertEqual([call.kwargs['headless'] for call in launch.call_args_list],[True,False])
        self.assertEqual(instance.status()['state'],'ready')
        self.assertFalse(instance._headless)

    def test_visible_window_fallback_is_not_retried(self):
        instance=auth.XiangAuth();instance._wait_lighthouse=Mock(side_effect=auth.HeadlessFallback('still blocked'))
        with patch.object(auth,'HEADLESS_DEFAULT',True),patch('playwright.sync_api.sync_playwright') as pw,patch.object(auth.xiaoxiang_lighthouse,'load_state',return_value=None),patch.object(auth.xiaoxiang_lighthouse,'save_state') as save:
            launch=pw.return_value.__enter__.return_value.chromium.launch
            instance._login()
        self.assertEqual(launch.call_count,2);save.assert_not_called()
        self.assertEqual(instance.status()['state'],'error')

    def test_headless_watchdog_falls_back_when_official_page_has_no_interaction(self):
        instance=auth.XiangAuth();instance._headless=True;clock=[0.0];page=Mock();page.url='https://maicaipeisong.meituan.com/notice/list.html';context=Mock()
        context.storage_state.side_effect=lambda:{'cookies':[{'name':'c','value':str(clock[0])}]}
        page.wait_for_timeout.side_effect=lambda ms:clock.__setitem__(0,clock[0]+ms/1000)
        instance._active_page=Mock(return_value=page);instance._capture_desktop=Mock();instance._apply_inputs=Mock()
        with patch.object(auth.time,'monotonic',side_effect=lambda:clock[0]),patch.object(auth,'HEADLESS_GRACE',0.2):
            with self.assertRaises(auth.HeadlessFallback):
                instance._probe_until(context,page,Mock())
        self.assertIsNotNone(instance._fallback_state)

    def test_headless_environment_rejection_falls_back_immediately(self):
        instance=auth.XiangAuth();instance._headless=True;page=Mock();page.url='https://passport.meituan.com/account/unitivelogin';context=Mock()
        page.wait_for_timeout.side_effect=lambda _:None
        instance._active_page=Mock(return_value=page);instance._apply_inputs=Mock()
        instance._capture_desktop=Mock(side_effect=lambda source,page:instance.desktop.__setitem__(source,{'official_feedback_kind':'environment_rejected'}))
        with self.assertRaises(auth.HeadlessFallback):
            instance._probe_until(context,page,Mock())

    def test_headless_sms_rejection_falls_back_on_first_stage_only(self):
        instance=auth.XiangAuth();instance._headless=True;page=Mock();page.url='https://passport.meituan.com/account/unitivelogin';context=Mock()
        page.wait_for_timeout.side_effect=lambda _:None
        instance._active_page=Mock(return_value=page);instance._apply_inputs=Mock()
        instance._capture_desktop=Mock(side_effect=lambda source,page:instance.desktop.__setitem__(source,{'official_feedback_kind':'rejected','fields':[{'id':'x'}]}))
        with self.assertRaises(auth.HeadlessFallback):
            instance._probe_until(context,page,Mock())
        instance.stages['lighthouse']='ready';page.url='https://maicaipeisong.meituan.com/notice/list.html'
        instance.desktop[auth.SOURCE]={'official_feedback_kind':'rejected','fields':[{'id':'x'}]}
        instance._fallback_state=None
        page.wait_for_timeout.side_effect=lambda _:time.sleep(.005)
        with patch.object(auth.time,'monotonic',side_effect=lambda:0.0):
            self.assertTrue(instance._probe_until(context,page,Mock()))
        self.assertIsNone(instance._fallback_state)

    def test_keepalive_reports_ready_for_healthy_session(self):
        instance=auth.XiangAuth();state={'cookies':[]}
        with patch.object(auth.xiaoxiang_lighthouse,'load_state',return_value=state),patch.object(instance,'probe_lighthouse'),patch.object(auth.xiaoxiang_board,'board_probe'):
            self.assertTrue(instance.keepalive())
        status=instance.status()
        self.assertEqual(status['state'],'ready');self.assertEqual(status['stages'],{'lighthouse':'ready','board':'ready'})
        self.assertTrue(status['checked_at'])

    def test_keepalive_reports_partial_when_board_stage_expired(self):
        instance=auth.XiangAuth()
        with patch.object(auth.xiaoxiang_lighthouse,'load_state',return_value={'cookies':[]}),patch.object(instance,'probe_lighthouse'), \
             patch.object(auth.xiaoxiang_board,'board_probe',side_effect=SessionExpired('board expired')):
            self.assertTrue(instance.keepalive())
        status=instance.status()
        self.assertEqual(status['state'],'partial')
        self.assertEqual(status['stages'],{'lighthouse':'ready','board':'waiting_login'})
        self.assertIn('看板',status['message'])

    def test_keepalive_requires_login_when_lighthouse_expired(self):
        instance=auth.XiangAuth()
        with patch.object(auth.xiaoxiang_lighthouse,'load_state',return_value={'cookies':[]}), \
             patch.object(instance,'probe_lighthouse',side_effect=SessionExpired('expired')), \
             patch.object(auth.xiaoxiang_board,'board_probe') as board:
            self.assertFalse(instance.keepalive())
        board.assert_not_called();self.assertEqual(instance.status()['state'],'login_required')

    def test_keepalive_skips_when_no_session_or_login_is_running(self):
        instance=auth.XiangAuth()
        with patch.object(auth.xiaoxiang_lighthouse,'load_state',return_value=None),patch.object(instance,'probe_lighthouse') as probe:
            self.assertFalse(instance.keepalive());probe.assert_not_called()
        worker=Mock();worker.is_alive.return_value=True;instance.workers[auth.SOURCE]=worker
        with patch.object(auth.xiaoxiang_lighthouse,'load_state',return_value={'cookies':[]}),patch.object(instance,'probe_lighthouse') as probe:
            self.assertFalse(instance.keepalive());probe.assert_not_called()

    def test_window_visibility_reflects_headless_mode(self):
        instance=auth.XiangAuth();worker=Mock();worker.is_alive.return_value=True;instance.workers[auth.SOURCE]=worker
        instance._headless=True;self.assertFalse(instance.status()['window_visible'])
        instance._headless=False;self.assertTrue(instance.status()['window_visible'])
