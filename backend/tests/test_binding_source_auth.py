import contextlib
from pathlib import Path
import sys
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import binding_source_auth as auth
import binding_sources_http as http
from binding_source_auth import BillCollectionError

HOST = 'merchant.shangyiworker.com'
ENTRY = 'https://' + HOST + '/freelancer/merchantFreelancer'
LOGIN = 'https://' + HOST + '/login?redirect=/freelancer/merchantFreelancer'
LANORANGE_HOST = 'madouren.cdevelopment.cn'
LANORANGE_ENTRY = 'https://' + LANORANGE_HOST + '/admin/login'


def storage_state(token='fresh-token-value'):
    return {
        'cookies': [
            {'name': 'Yunke-Mer-Token', 'value': 'cookie-token-value', 'domain': HOST,
             'path': '/', 'expires': -1, 'httpOnly': False, 'secure': True, 'sameSite': 'Lax'},
            {'name': 'third-party', 'value': 'unrelated-cookie', 'domain': 'other.example',
             'path': '/', 'expires': -1, 'httpOnly': False, 'secure': True, 'sameSite': 'Lax'},
        ],
        'origins': [
            {'origin': 'https://' + HOST, 'localStorage': [{'name': 'Yunke-Mer-Token', 'value': token}]},
            {'origin': 'https://other.example', 'localStorage': [{'name': 'other', 'value': 'unrelated'}]},
        ],
    }


def lanorange_state(token='lanorange-token-value'):
    return {
        'cookies': [{'name': 'Admin-Token', 'value': 'cookie-token-value', 'domain': LANORANGE_HOST,
                     'path': '/', 'expires': -1, 'httpOnly': True, 'secure': True, 'sameSite': 'Lax'}],
        'origins': [{'origin': 'https://' + LANORANGE_HOST,
                     'localStorage': [{'name': 'Admin-Token', 'value': token}]}],
    }


def dingtalk_state(token='dingtalk-session-value'):
    return {
        'cookies': [
            {'name': 'Admin-Token', 'value': 'cookie-token-value', 'domain': LANORANGE_HOST,
             'path': '/', 'httpOnly': True, 'secure': True, 'sameSite': 'Lax'},
            {'name': 'login_token', 'value': token, 'domain': 'login.dingtalk.com',
             'path': '/', 'expires': -1, 'httpOnly': True, 'secure': True, 'sameSite': 'Lax'},
            {'name': 'dingtalk_session', 'value': token, 'domain': '.dingtalk.com',
             'path': '/', 'expires': -1, 'httpOnly': True, 'secure': True, 'sameSite': 'Lax'},
            {'name': 'tracking', 'value': 'unrelated', 'domain': '.mmstat.com',
             'path': '/', 'expires': -1, 'httpOnly': False, 'secure': True, 'sameSite': 'Lax'},
        ],
        'origins': [
            {'origin': 'https://' + LANORANGE_HOST,
             'localStorage': [{'name': 'Admin-Token', 'value': token}]},
            {'origin': 'https://login.dingtalk.com',
             'localStorage': [{'name': 'dingtalk-ls', 'value': token}]},
            {'origin': 'https://other.example', 'localStorage': [{'name': 'other', 'value': 'unrelated'}]},
        ],
    }


class FakePage:
    def __init__(self, context):
        self.context = context
        self.clicks = []
        self.shots = 0

    @property
    def url(self):
        return self.context.url

    def is_closed(self):
        return self.context.closed

    def goto(self, url, **kwargs):
        self.context.url = self.context.landing

    def get_by_role(self, role, name=None, exact=False):
        self.clicks.append(name)
        return SimpleNamespace(click=lambda timeout=None: None,
                               first=SimpleNamespace(is_visible=lambda: False,
                                                      click=lambda timeout=None: None))

    def get_by_text(self, text, exact=False):
        return SimpleNamespace(first=SimpleNamespace(is_visible=lambda: False,
                                                      click=lambda timeout=None: None))

    def screenshot(self, **kwargs):
        self.shots += 1
        return b'png'

    def wait_for_timeout(self, milliseconds):
        pass


class FakeContext:
    def __init__(self, state, url):
        self.state, self.landing, self.url = state, url, url
        self.pages, self.closed = [], False

    def new_page(self):
        page = FakePage(self)
        self.pages.append(page)
        return page

    def storage_state(self):
        return self.state

    def close(self):
        self.closed = True


class SequenceContext(FakeContext):
    def __init__(self, states, url):
        super().__init__(states[0], url)
        self.sequence = list(states)

    def storage_state(self):
        if len(self.sequence) > 1:
            return self.sequence.pop(0)
        return self.sequence[0]


class BrowserAuthTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.root_patch = patch.object(auth, 'ROOT', self.root)
        self.root_patch.start()
        auth.AUTH.states.clear()

    def tearDown(self):
        auth.AUTH.states.clear()
        self.root_patch.stop()
        self.temp.cleanup()

    def browser(self, context):
        browser = SimpleNamespace(new_context=Mock(return_value=context), close=Mock())
        playwright = SimpleNamespace(chromium=SimpleNamespace(launch=Mock(return_value=browser)))
        return browser, playwright

    def test_saved_browser_state_is_encrypted_scoped_and_source_bound(self):
        auth.save_state('baize', storage_state())
        raw = auth.state_path('baize').read_bytes()
        self.assertNotIn(b'fresh-token-value', raw)
        self.assertNotIn(b'other.example', raw)
        loaded = auth.load_state('baize')
        self.assertEqual([cookie['domain'] for cookie in loaded['cookies']], [HOST])
        self.assertEqual([origin['origin'] for origin in loaded['origins']], ['https://' + HOST])
        self.assertEqual(auth._token_from_state('baize', loaded), 'fresh-token-value')
        auth.state_path('lanorange').write_bytes(raw)
        with self.assertRaises(BillCollectionError):
            auth.load_state('lanorange')

    def test_silent_refresh_replays_saved_session_without_a_login_window(self):
        auth.save_token('baize', 'old-token-value')
        auth.save_state('baize', storage_state())
        saved = auth.load_state('baize')
        context = FakeContext(saved, ENTRY)
        browser, playwright = self.browser(context)
        with patch('playwright.sync_api.sync_playwright', return_value=contextlib.nullcontext(playwright)), \
             patch.object(auth, 'identity') as identity:
            self.assertTrue(auth.AUTH.refresh('baize'))
        identity.assert_called_once()
        launch=playwright.chromium.launch.call_args.kwargs
        # 优先用可执行文件路径启动 Edge，避免 channel 解析在本机多耗十几秒。
        self.assertTrue('executable_path' in launch or launch.get('channel')=='msedge')
        self.assertTrue(launch['headless'])
        browser.new_context.assert_called_once_with(storage_state=saved)
        self.assertEqual(auth.load_token('baize'), 'fresh-token-value')
        self.assertEqual(auth.AUTH.status('baize')['state'], 'ready')

    def test_expired_saved_session_is_retained_and_requires_login(self):
        auth.save_token('baize', 'old-token-value')
        auth.save_state('baize', {
            'cookies': [{'name': 'session', 'value': 'expired', 'domain': HOST, 'path': '/'}],
            'origins': [{'origin': 'https://' + HOST, 'localStorage': []}],
        })
        context = FakeContext(auth.load_state('baize'), LOGIN)
        _, playwright = self.browser(context)
        with patch('playwright.sync_api.sync_playwright', return_value=contextlib.nullcontext(playwright)), \
             patch.object(auth, 'identity') as identity:
            self.assertFalse(auth.AUTH.refresh('baize'))
        identity.assert_not_called()
        self.assertTrue(auth.state_path('baize').exists())
        status = auth.AUTH.status('baize')
        self.assertEqual(status['state'], 'saved')
        self.assertIn('重新登录', status['message'])

    def test_lanorange_login_pages_end_silent_refresh_without_waiting(self):
        state = {
            'cookies': [{'name': 'JSESSIONID', 'value': 'expired', 'domain': 'madouren.cdevelopment.cn',
                         'path': '/', 'secure': True, 'httpOnly': True}],
            'origins': [{'origin': 'https://madouren.cdevelopment.cn', 'localStorage': []}],
        }
        for landing in ('https://madouren.cdevelopment.cn/admin/login',
                        'https://login.dingtalk.com/oauth2/challenge.htm?client_id=test'):
            with self.subTest(landing=landing):
                auth.save_token('lanorange', 'old-token-value')
                auth.save_state('lanorange', state)
                context = FakeContext(auth.load_state('lanorange'), landing)
                _, playwright = self.browser(context)
                with patch('playwright.sync_api.sync_playwright',
                           return_value=contextlib.nullcontext(playwright)), \
                     patch.object(auth, 'identity') as identity:
                    self.assertFalse(auth.AUTH.refresh('lanorange'))
                identity.assert_not_called()
                self.assertTrue(auth.state_path('lanorange').exists())

    def test_lanorange_silent_refresh_keeps_dingtalk_session_when_token_is_gone(self):
        auth.save_token('lanorange', 'old-token-value')
        auth.save_state('lanorange', dingtalk_state())
        saved = auth.load_state('lanorange')
        auth.save_state('lanorange', {'cookies': saved['cookies'][1:], 'origins': saved['origins'][1:]})
        context = FakeContext(auth.load_state('lanorange'),
                              'https://login.dingtalk.com/oauth2/challenge.htm?client_id=test')
        _, playwright = self.browser(context)
        with patch('playwright.sync_api.sync_playwright', return_value=contextlib.nullcontext(playwright)), \
             patch.object(auth, 'identity') as identity:
            self.assertFalse(auth.AUTH.refresh('lanorange'))
        identity.assert_not_called()
        remaining = auth.load_state('lanorange')
        self.assertEqual([cookie['name'] for cookie in remaining['cookies']],
                         ['login_token', 'dingtalk_session'])

    def test_lanorange_valid_token_never_opens_browser_or_reads_browser_state(self):
        auth.save_token('lanorange', 'valid-lanorange-token')
        with patch('playwright.sync_api.sync_playwright') as playwright, \
             patch.object(auth, 'load_state') as load_state, \
             patch.object(auth, 'client'), \
             patch.object(auth, 'identity') as identity:
            auth.AUTH._login('lanorange')
        playwright.assert_not_called()
        load_state.assert_not_called()
        identity.assert_called_once()
        self.assertEqual(auth.AUTH.status('lanorange')['state'], 'ready')
        self.assertEqual(auth.load_token('lanorange'), 'valid-lanorange-token')

    def test_lanorange_network_failure_preserves_session_without_opening_browser(self):
        auth.save_token('lanorange', 'valid-lanorange-token')
        with patch('playwright.sync_api.sync_playwright') as playwright, \
             patch.object(auth, 'client'), \
             patch.object(auth, 'identity', side_effect=requests.ConnectionError()):
            auth.AUTH._login('lanorange')
        playwright.assert_not_called()
        self.assertEqual(auth.load_token('lanorange'), 'valid-lanorange-token')
        self.assertIn('连接暂未确认', auth.AUTH.status('lanorange')['message'])

    def test_dingtalk_confirmation_rejects_lookalike_or_insecure_hosts(self):
        for url in ('https://other.example/login.dingtalk.com/',
                    'https://login.dingtalk.com.evil.example/',
                    'http://login.dingtalk.com/oauth2/challenge.htm'):
            page = Mock(url=url)
            self.assertIsNone(auth._confirm_dingtalk(page))
            page.get_by_role.assert_not_called()

    def test_lanorange_valid_session_reaches_ready_without_clicking_login(self):
        auth.save_state('lanorange', lanorange_state())
        context = FakeContext(auth.load_state('lanorange'), 'https://' + LANORANGE_HOST + '/admin/index')
        browser, playwright = self.browser(context)
        with patch('playwright.sync_api.sync_playwright', return_value=contextlib.nullcontext(playwright)), \
             patch.object(auth, 'client') as client, \
             patch.object(auth, 'identity') as identity:
            auth.AUTH._login('lanorange')
        identity.assert_called_once()
        client.assert_called_once()
        self.assertEqual(context.pages[0].clicks, [])
        self.assertFalse(context.closed)
        self.assertEqual(auth.AUTH.status('lanorange')['state'], 'ready')
        self.assertEqual(auth.load_token('lanorange'), 'lanorange-token-value')
        browser.close.assert_called_once()

    def test_lanorange_stale_session_is_rebuilt_before_clicking_login(self):
        auth.save_state('lanorange', lanorange_state())
        stale = FakeContext(auth.load_state('lanorange'), LANORANGE_ENTRY)
        fresh = FakeContext(lanorange_state('new-token-value'), LANORANGE_ENTRY)
        browser, playwright = self.browser(stale)
        browser.new_context.side_effect = [stale, fresh]
        with patch('playwright.sync_api.sync_playwright', return_value=contextlib.nullcontext(playwright)), \
             patch.object(auth, 'client'), \
             patch.object(auth, 'identity', side_effect=[auth.SourceAuthenticationRequired('expired'), {}]) as identity:
            auth.AUTH._login('lanorange')
        self.assertTrue(stale.closed)
        self.assertEqual(stale.pages[0].clicks, [])
        self.assertEqual(fresh.pages[0].clicks, ['钉钉登录'])
        self.assertEqual(identity.call_count, 2)
        self.assertEqual(auth.AUTH.status('lanorange')['state'], 'ready')
        self.assertEqual(auth.load_token('lanorange'), 'new-token-value')
        self.assertTrue(auth.state_path('lanorange').exists())

    def test_lanorange_state_keeps_dingtalk_session_and_drops_tracking(self):
        auth.save_state('lanorange', dingtalk_state())
        loaded = auth.load_state('lanorange')
        self.assertEqual(sorted(cookie['domain'] for cookie in loaded['cookies']),
                         sorted([LANORANGE_HOST, 'login.dingtalk.com', '.dingtalk.com']))
        self.assertEqual(sorted(origin['origin'] for origin in loaded['origins']),
                         sorted(['https://' + LANORANGE_HOST, 'https://login.dingtalk.com']))
        self.assertEqual(auth._token_from_state('lanorange', loaded), 'dingtalk-session-value')

        auth.save_state('baize', {
            'cookies': [
                {'name': 'Yunke-Mer-Token', 'value': 'baize-token', 'domain': HOST, 'path': '/'},
                {'name': 'dingtalk_session', 'value': 'dingtalk-session-value', 'domain': '.dingtalk.com',
                 'path': '/'},
            ],
            'origins': [{'origin': 'https://' + HOST, 'localStorage': []},
                        {'origin': 'https://login.dingtalk.com', 'localStorage': []}],
        })
        baize = auth.load_state('baize')
        self.assertEqual([cookie['domain'] for cookie in baize['cookies']], [HOST])
        self.assertEqual([origin['origin'] for origin in baize['origins']], ['https://' + HOST])

    def test_dingtalk_confirm_clicks_visible_consent_once(self):
        visible = SimpleNamespace(is_visible=lambda: True, click=Mock())
        page = Mock()
        page.url = 'https://login.dingtalk.com/oauth2/challenge.htm'
        page.get_by_role.return_value.first = visible
        page.get_by_text.return_value.first = SimpleNamespace(is_visible=lambda: False, click=Mock())
        self.assertEqual(auth._confirm_dingtalk(page), '同意')
        visible.click.assert_called_once_with(timeout=2000)

        hidden = SimpleNamespace(is_visible=lambda: False, click=Mock())
        page = Mock()
        page.url = 'https://login.dingtalk.com/oauth2/challenge.htm'
        page.get_by_role.return_value.first = hidden
        page.get_by_text.return_value.first = hidden
        self.assertIsNone(auth._confirm_dingtalk(page))
        hidden.click.assert_not_called()

    def test_lanorange_reused_dingtalk_session_skips_qr_screenshot(self):
        auth.save_state('lanorange', dingtalk_state())
        saved = auth.load_state('lanorange')
        stale = FakeContext({'cookies': saved['cookies'][1:], 'origins': saved['origins'][1:]}, LANORANGE_ENTRY)
        fresh = SequenceContext([stale.state, saved, saved], 'https://login.dingtalk.com/oauth2/challenge.htm?client_id=test')
        browser, playwright = self.browser(stale)
        browser.new_context.side_effect = [stale, fresh]
        with patch('playwright.sync_api.sync_playwright', return_value=contextlib.nullcontext(playwright)), \
             patch.object(auth, 'client'), \
             patch.object(auth, 'identity', return_value={}), \
             patch.object(auth, '_confirm_dingtalk', return_value='同意') as confirm:
            auth.AUTH._login('lanorange')
        rebuilt = browser.new_context.call_args_list[1].kwargs
        self.assertEqual([cookie['name'] for cookie in rebuilt['storage_state']['cookies']],
                         ['login_token', 'dingtalk_session'])
        self.assertEqual([origin['origin'] for origin in rebuilt['storage_state']['origins']],
                         ['https://login.dingtalk.com'])
        confirm.assert_called_once()
        self.assertEqual(fresh.pages[0].shots, 0)
        self.assertEqual(fresh.pages[0].clicks, ['钉钉登录'])
        self.assertEqual(auth.AUTH.status('lanorange')['state'], 'ready')
        self.assertEqual(auth.load_token('lanorange'), 'dingtalk-session-value')
        self.assertEqual(sorted(cookie['name'] for cookie in auth.load_state('lanorange')['cookies']),
                         sorted(['Admin-Token', 'login_token', 'dingtalk_session']))


        auth.save_token('baize', 'valid-baize-token')
        with patch('playwright.sync_api.sync_playwright') as playwright, \
             patch.object(auth, 'client'), \
             patch.object(auth, 'identity') as identity:
            auth.AUTH._login('baize')
        playwright.assert_not_called()
        identity.assert_called_once()
        self.assertEqual(auth.AUTH.status('baize')['state'], 'ready')
        self.assertIn('复用', auth.AUTH.status('baize')['message'])

    def test_baize_stale_session_is_rebuilt_and_window_stays_until_login(self):
        auth.save_token('baize', 'stale-baize-token')
        auth.save_state('baize', storage_state())
        stale = FakeContext(auth.load_state('baize'), ENTRY)
        clean = FakeContext({'cookies': [], 'origins': []}, ENTRY)
        browser, playwright = self.browser(stale)
        browser.new_context.side_effect = [stale, clean]
        with patch('playwright.sync_api.sync_playwright', return_value=contextlib.nullcontext(playwright)), \
             patch.object(auth, 'client'), \
             patch.object(auth, 'identity', side_effect=auth.SourceAuthenticationRequired('expired')) as identity, \
             patch.object(auth.time, 'monotonic', side_effect=[0, 0, 2, 2, 1000]):
            auth.AUTH._login('baize')
        self.assertTrue(stale.closed)
        self.assertFalse(clean.closed)
        self.assertEqual(browser.new_context.call_args_list[1].kwargs, {'viewport': {'width': 1100, 'height': 850},'locale':'zh-CN','timezone_id':'Asia/Shanghai'})
        self.assertTrue(auth.state_path('baize').exists())
        self.assertEqual(auth.load_token('baize'), 'stale-baize-token')
        status = auth.AUTH.status('baize')
        self.assertEqual(status['state'], 'error')
        self.assertIn('等待超时', status['message'])
        self.assertNotIn('登录已失效', status['message'])

    def test_keepalive_refreshes_server_session_and_reports_expiry(self):
        auth.save_token('baize', 'valid-token-value')
        with patch.object(auth, 'client'), \
             patch.object(auth, 'identity') as identity:
            self.assertTrue(auth.AUTH.keepalive('baize'))
        identity.assert_called_once()
        self.assertEqual(auth.AUTH.status('baize')['state'], 'ready')

        with patch.object(auth, 'client'), \
             patch.object(auth, 'identity', side_effect=auth.SourceAuthenticationRequired('expired')):
            self.assertFalse(auth.AUTH.keepalive('baize'))
        status = auth.AUTH.status('baize')
        self.assertEqual(status['state'], 'login_required')
        self.assertIn('已确认会话失效', status['message'])

    def test_keepalive_skips_while_login_window_is_waiting(self):
        auth.save_token('baize', 'valid-token-value')
        auth.AUTH.states['baize'] = {'state': 'waiting_login', 'message': ''}
        with patch.object(auth, 'client') as client:
            self.assertFalse(auth.AUTH.keepalive('baize'))
        client.assert_not_called()
        self.assertEqual(auth.AUTH.status('baize')['state'], 'waiting_login')

    def test_keepalive_ignores_network_errors_without_signing_out(self):
        auth.save_token('baize', 'valid-token-value')
        auth.AUTH.states['baize'] = {'state': 'ready', 'message': ''}
        with patch.object(auth, 'client', side_effect=requests.ConnectionError()):
            self.assertFalse(auth.AUTH.keepalive('baize'))
        self.assertEqual(auth.AUTH.status('baize')['state'], 'unknown')

    def test_refresh_without_saved_session_does_not_open_a_browser(self):
        auth.save_token('baize', 'old-token-value')
        with patch('playwright.sync_api.sync_playwright') as playwright:
            self.assertFalse(auth.AUTH.refresh('baize'))
        playwright.assert_not_called()
        self.assertIn('没有可复用', auth.AUTH.status('baize')['message'])

    def test_http_source_refreshes_before_opening_the_login_window(self):
        session = Mock()
        logs = []
        with patch.object(http, 'client', side_effect=[auth.SourceAuthenticationRequired('expired'), session]) as client, \
             patch.object(http, 'identity', return_value={}), \
             patch.object(http.AUTH, 'refresh', return_value=True) as refresh, \
             patch.object(http.AUTH, 'start') as start:
            result = http.authenticated('baize', logs.append, threading.Event())
        self.assertIs(result, session)
        self.assertEqual(client.call_count, 2)
        refresh.assert_called_once_with('baize')
        start.assert_not_called()
        self.assertTrue(any('复用' in message for message in logs))

    def test_http_source_opens_login_only_after_refresh_fails(self):
        with patch.object(http, 'client', side_effect=auth.SourceAuthenticationRequired('expired')), \
             patch.object(http.AUTH, 'refresh', return_value=False), \
             patch.object(http.AUTH, 'start') as start, \
             patch.object(http.AUTH, 'status', return_value={'state': 'error'}):
            with self.assertRaises(BillCollectionError):
                http.authenticated('baize', lambda *_: None, threading.Event())
        start.assert_called_once_with('baize')

    def test_network_error_never_triggers_login(self):
        session = Mock()
        with patch.object(http, 'client', return_value=session), \
             patch.object(http, 'identity', side_effect=requests.ConnectionError()), \
             patch.object(http.AUTH, 'refresh') as refresh, \
             patch.object(http.AUTH, 'start') as start:
            with self.assertRaisesRegex(BillCollectionError, '连接失败'):
                http.authenticated('baize', lambda *_: None, threading.Event())
        session.close.assert_called_once()
        refresh.assert_not_called()
        start.assert_not_called()

    def test_source_bound_state_rejects_tampered_payload(self):
        path = auth.state_path('baize')
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b'not-an-encrypted-session')
        with self.assertRaises(BillCollectionError):
            auth.load_state('baize')


if __name__ == '__main__':
    unittest.main()
