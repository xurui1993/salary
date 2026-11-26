"""Regression tests for multi-account switching deduplication across all 6 platforms
and Lanorange / New Lanorange DingTalk QR capture & fast browser launch.
"""
from __future__ import annotations

import asyncio
import copy
import json
from pathlib import Path
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, Mock, patch

from fastapi import FastAPI

import auth_browser_runtime as runtime
import baize_accounts
import binding_source_auth as sources
import desktop_auth_page as desktop_page
import platform_account_pool as pool
import platform_auth_control as control

PNG = b'\x89PNG\r\n\x1a\nsynthetic-dingtalk-qr'


class MultiAccountDeduplicationAllPlatformsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.addCleanup(self.temp.cleanup)

    def _primary_files(self, source: str) -> list[Path]:
        if source == 'fengshen':
            return [self.root / 'fengshen_session.dpapi']
        if source == 'xiaoxiang':
            return [self.root / 'xiaoxiang_session.dpapi']
        return [self.root / f'{source}.dpapi', self.root / f'{source}.storage']

    def _write_session(self, source: str, payload: bytes) -> list[Path]:
        pfiles = self._primary_files(source)
        for idx, p in enumerate(pfiles):
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(payload + f'-part{idx}'.encode())
        return pfiles

    def test_repeated_switching_never_duplicates_across_all_6_platforms(self):
        for source in ('fengshen', 'lanorange', 'lanorange_mdr', 'baize', 'xiaoxiang', 'benlai'):
            with self.subTest(source=source):
                pfiles = self._write_session(source, b'acct-A-bytes')
                st_a = {
                    'saved': True,
                    'state': 'ready',
                    'session_version': f'{source}-fp-A',
                    'account_label': '姚奕韩',
                    'credential_account': '138****8001',
                    'organization': '深圳市麻豆人配送服务有限公司',
                    'credential_saved': True,
                }
                accts, active_id_a, _ = pool.sync_pool_with_status(source, pfiles, st_a)
                self.assertEqual(len(accts), 1)
                self.assertIsNotNone(active_id_a)

                # Prepare add and log into Account B
                pool.prepare_add_account(source, pfiles, st_a)
                self._write_session(source, b'acct-B-bytes')
                st_b = {
                    'saved': True,
                    'state': 'ready',
                    'session_version': f'{source}-fp-B',
                    'account_label': '罗政',
                    'credential_account': '139****8002',
                    'organization': '深圳市麻豆人文化活动策划有限公司',
                    'credential_saved': True,
                }
                accts, active_id_b, _ = pool.sync_pool_with_status(source, pfiles, st_b)
                self.assertEqual(len(accts), 2)
                self.assertNotEqual(active_id_a, active_id_b)

                # Simulate 10 rapid back-and-forth switches WITH credential_account / account_label flip-flops
                for i in range(10):
                    target_id = active_id_a if i % 2 == 0 else active_id_b
                    cur_status = st_b if i % 2 == 0 else st_a
                    pool.activate_slot(source, pfiles, target_id, cur_status)

                    # Simulate a poll where account_label is empty and only masked credential_account arrives
                    poll_masked = {
                        'saved': True,
                        'state': 'ready',
                        'session_version': f'{source}-fp-{"A" if i % 2 == 0 else "B"}',
                        'account_label': '',
                        'credential_account': '138****8001' if i % 2 == 0 else '139****8002',
                        'organization': '',
                        'credential_saved': True,
                    }
                    accts_after_masked, active_now, _ = pool.sync_pool_with_status(source, pfiles, poll_masked)
                    self.assertEqual(len(accts_after_masked), 2)
                    self.assertEqual(active_now, target_id)
                    # Rich label must not be overwritten by masked phone
                    active_row = next(a for a in accts_after_masked if a['slot_id'] == target_id)
                    self.assertEqual(active_row['account_label'], '姚奕韩' if i % 2 == 0 else '罗政')

                    # Also simulate idempotent double-click on the already-active slot
                    pool.activate_slot(source, pfiles, target_id, poll_masked)
                    accts_double, _, _ = pool.sync_pool_with_status(source, pfiles, st_a if i % 2 == 0 else st_b)
                    self.assertEqual(len(accts_double), 2)

    def test_historical_duplicate_slots_auto_deduplicate_and_preserve_alias(self):
        source = 'baize'
        pfiles = self._write_session(source, b'yao-session')
        pdir = pool.pool_dir(source, pfiles)
        for sid, data in (
            ('acct_1', b'yao-session'),
            ('acct_2', b'yao-session-old1'),
            ('acct_3', b'yao-session-old2'),
            ('acct_4', b'luo-session'),
        ):
            sdir = pdir / sid
            sdir.mkdir(parents=True, exist_ok=True)
            (sdir / 'baize.dpapi').write_bytes(data)
            (sdir / 'baize.storage').write_bytes(data)

        manifest = {
            'active_slot_id': 'acct_1',
            'pending_new_slot': False,
            'accounts': [
                {'slot_id': 'acct_1', 'account_label': '姚奕韩', 'alias': '', 'organization': '深圳市麻豆人配送服务有限公司', 'state': 'ready', 'session_version': 'fp1', 'updated_at': '2026-11-26T00:01:00+00:00'},
                {'slot_id': 'acct_2', 'account_label': '姚奕韩', 'alias': '小象主号', 'organization': '深圳市麻豆人配送服务有限公司', 'state': 'ready', 'session_version': 'fp2', 'updated_at': '2026-11-26T00:02:00+00:00'},
                {'slot_id': 'acct_3', 'account_label': '姚奕韩', 'alias': '', 'organization': '深圳市麻豆人配送服务有限公司', 'state': 'ready', 'session_version': 'fp3', 'updated_at': '2026-11-26T00:03:00+00:00'},
                {'slot_id': 'acct_4', 'account_label': '罗政', 'alias': '', 'organization': '深圳市麻豆人文化活动策划有限公司', 'state': 'ready', 'session_version': 'fp4', 'updated_at': '2026-11-26T00:04:00+00:00'},
            ],
        }
        pool.save_manifest(source, pfiles, manifest)

        accts, active_id, _ = pool.sync_pool_with_status(
            source,
            pfiles,
            {'saved': True, 'state': 'ready', 'session_version': 'fp1', 'account_label': '姚奕韩', 'organization': '深圳市麻豆人配送服务有限公司'},
        )
        self.assertEqual(len(accts), 2)
        self.assertEqual(active_id, 'acct_1')
        labels = [a['account_label'] for a in accts]
        self.assertEqual(labels, ['姚奕韩', '罗政'])
        # Preserved alias merged from duplicate acct_2 onto active acct_1
        yao = next(a for a in accts if a['slot_id'] == 'acct_1')
        self.assertEqual(yao['alias'], '小象主号')
        # Duplicate directories removed from disk
        self.assertFalse((pdir / 'acct_2').exists())
        self.assertFalse((pdir / 'acct_3').exists())
        self.assertTrue((pdir / 'acct_1').exists())
        self.assertTrue((pdir / 'acct_4').exists())

    def test_stale_baize_enrichment_cannot_overwrite_newly_switched_account(self):
        source = 'baize'
        pfiles = self._write_session(source, b'acct-A')
        st_a = {'saved': True, 'state': 'ready', 'session_version': 'fp-A', 'account_label': '姚奕韩', 'organization': '配送公司'}
        _, id_a, _ = pool.sync_pool_with_status(source, pfiles, st_a)
        pool.prepare_add_account(source, pfiles, st_a)
        self._write_session(source, b'acct-B')
        st_b = {'saved': True, 'state': 'ready', 'session_version': 'fp-B', 'account_label': '罗政', 'organization': '策划公司'}
        _, id_b, _ = pool.sync_pool_with_status(source, pfiles, st_b)

        # In-flight enrichment from Account A arrives AFTER Account B became active
        pool.enrich_active_slot_identity(
            source,
            pfiles,
            account_label='姚奕韩',
            organization='配送公司',
            expected_session_version='fp-A',
        )
        accts, active_id, _ = pool.sync_pool_with_status(source, pfiles, st_b)
        self.assertEqual(len(accts), 2)
        self.assertEqual(active_id, id_b)
        row_b = next(a for a in accts if a['slot_id'] == id_b)
        self.assertEqual(row_b['account_label'], '罗政')
        self.assertEqual(row_b['organization'], '策划公司')

    def test_relogging_same_account_via_prepare_add_merges_in_place(self):
        source = 'lanorange'
        pfiles = self._write_session(source, b'lo-v1')
        st1 = {'saved': True, 'state': 'ready', 'session_version': 'fp-1', 'account_label': '运营甲', 'organization': '蓝橙总部'}
        _, id1, _ = pool.sync_pool_with_status(source, pfiles, st1)

        pool.prepare_add_account(source, pfiles, st1)
        self._write_session(source, b'lo-v2-new-token-same-user')
        st2 = {'saved': True, 'state': 'ready', 'session_version': 'fp-2', 'account_label': '运营甲', 'organization': '蓝橙总部'}
        accts, active_id, pending = pool.sync_pool_with_status(source, pfiles, st2)
        self.assertFalse(pending)
        self.assertEqual(len(accts), 1)
        self.assertEqual(active_id, id1)


class LanorangeQrAndFastLaunchTests(unittest.TestCase):
    def test_lanorange_and_lanorange_mdr_both_enable_dingtalk_qr_and_trust_subdomains(self):
        self.assertTrue(sources.SOURCES['lanorange'].get('dingtalk_qr'))
        self.assertTrue(sources.SOURCES['lanorange_mdr'].get('dingtalk_qr'))
        auth = sources.SourceAuth()
        self.assertEqual(auth.login_mode('lanorange'), 'qr')
        self.assertEqual(auth.login_mode('lanorange_mdr'), 'qr')
        self.assertEqual(auth.login_mode('baize'), 'sms')
        self.assertEqual(auth.login_mode('benlai'), 'sms')
        self.assertEqual(auth.login_mode('xiaoxiang'), 'sms')

        for src in ('lanorange', 'lanorange_mdr'):
            self.assertTrue(desktop_page.trusted(src, 'https://login.dingtalk.com/oauth2/auth'))
            self.assertTrue(desktop_page.trusted(src, 'https://oapi.dingtalk.com/connect/qrconnect'))
            self.assertFalse(desktop_page.trusted(src, 'https://evil-dingtalk.com/oauth2/auth'))

    def test_qr_capture_and_http_endpoint_work_for_both_lanorange_and_mdr(self):
        for src in ('lanorange', 'lanorange_mdr'):
            with self.subTest(source=src):
                auth = sources.SourceAuth()
                auth.states[src] = {'state': 'waiting_login', 'session_id': 'sid-123'}
                region = {'x': 120, 'y': 90, 'width': 240, 'height': 240}
                meta = {'form_id': 'f1', 'fields': [], 'controls': [], 'qr_state': 'visible', 'regions': {'qr': region}}
                page = Mock()
                page.url = 'https://login.dingtalk.com/oauth2/auth'
                page.screenshot.return_value = PNG

                with patch('desktop_auth_page.inspect_login_page', return_value=(copy.deepcopy(meta), {})):
                    auth._capture_desktop(src, page)

                st = auth.status(src)
                self.assertTrue(st['has_qr'])
                self.assertEqual(len(st['qr_version']), 20)

                app = FastAPI()
                app.include_router(sources.router)

                async def call_qr(query: str):
                    messages = []
                    async def receive():
                        return {'type': 'http.request', 'body': b'', 'more_body': False}
                    async def send(val):
                        messages.append(val)
                    with patch.object(sources, 'get_source_auth', return_value=auth):
                        await app(
                            {
                                'type': 'http',
                                'http_version': '1.1',
                                'scheme': 'http',
                                'server': ('localhost', 80),
                                'client': ('127.0.0.1', 1234),
                                'method': 'GET',
                                'path': f'/api/fengshen-downloads/source-auth/{src}/qr',
                                'query_string': query.encode(),
                                'headers': [(b'host', b'localhost')],
                            },
                            receive,
                            send,
                        )
                    start = next(m for m in messages if m['type'] == 'http.response.start')
                    body = b''.join(m.get('body', b'') for m in messages if m['type'] == 'http.response.body')
                    return start, body

                start_bad, _ = asyncio.run(call_qr('session_id=wrong'))
                self.assertEqual(start_bad['status'], 409)
                start_ok, body_ok = asyncio.run(call_qr('session_id=sid-123'))
                self.assertEqual(start_ok['status'], 200)
                self.assertEqual(body_ok, PNG)

    def test_desktop_inspector_detects_dingtalk_data_uri_img_qr(self):
        qr_img = Mock()
        qr_img.bounding_box.return_value = {'x': 350, 'y': 200, 'width': 200, 'height': 200}
        qr_img.get_attribute.side_effect = lambda k: 'data:image/png;base64,iVBORw0KGgo=' if k == 'src' else ''
        qr_img.evaluate.return_value = 'IMG'

        frame = Mock()
        frame.url = 'https://oapi.dingtalk.com/connect/qrconnect'
        frame.get_by_text.return_value.all.return_value = []
        expired = Mock()
        expired.is_visible.return_value = False
        frame.get_by_text.return_value.first = expired

        def fake_locator(query):
            if query.startswith('canvas:'):
                return SimpleNamespace(all=lambda: [qr_img])
            return SimpleNamespace(all=lambda: [])

        frame.locator.side_effect = fake_locator
        page = SimpleNamespace(url='https://login.dingtalk.com/oauth2/auth', frames=[frame])

        metadata, _ = desktop_page.inspect_login_page('lanorange', page)
        self.assertEqual(metadata['qr_state'], 'visible')
        self.assertIn('qr', metadata['regions'])

    def test_headless_launch_edge_prefers_fast_chrome_executable(self):
        pw = MagicMock()
        with patch.object(runtime, 'chrome_executable', return_value='/usr/bin/chrome'), \
             patch.object(runtime, 'edge_executable', return_value='/usr/bin/msedge'):
            runtime.launch_edge(pw, headless=True)
        pw.chromium.launch.assert_called_once_with(headless=True, executable_path='/usr/bin/chrome')


if __name__ == '__main__':
    unittest.main()
