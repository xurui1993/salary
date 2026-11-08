"""Interaction boundary; input is ephemeral and Playwright stays on its owning thread."""
import sys
import asyncio
import json
from types import SimpleNamespace
from pathlib import Path
from unittest import TestCase
from unittest.mock import Mock
from unittest.mock import patch
from fastapi import FastAPI, HTTPException

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from binding_source_auth import SourceAuth
import binding_source_auth as auth_module


class SourceInteractionTests(TestCase):
    def setUp(self):
        self.auth = SourceAuth()
        self.auth.states['baize'] = {'state': 'waiting_login', 'session_id': 'current'}

    def send(self, **command):
        return self.auth.interact('baize', {'session_id': 'current', **command})

    def test_actions_run_in_order_and_clear_sensitive_queue(self):
        self.send(action='click', x=.5, y=.2)
        self.send(action='fill', text='synthetic-password')
        self.send(action='key', key='Enter')
        page = Mock(); page.url = 'https://merchant.shangyiworker.com/login'
        self.auth._apply_inputs('baize', page, {'width': 1100, 'height': 850})
        page.mouse.click.assert_called_once_with(550, 170)
        page.locator.return_value.fill.assert_called_once_with('synthetic-password', timeout=1500)
        page.keyboard.press.assert_called_once_with('Enter')
        self.assertNotIn('baize', self.auth.inputs)
        self.assertNotIn('synthetic-password', repr(self.auth.states))

    def test_rejects_stale_or_completed_authentication(self):
        for state, sid in [('waiting_login', 'previous'), ('ready', 'current')]:
            self.auth.states['baize']['state'] = state
            with self.assertRaises(HTTPException) as error:
                self.auth.interact('baize', {'action': 'click', 'x': .1, 'y': .1, 'session_id': sid})
            self.assertEqual(error.exception.status_code, 409)

    def test_rejects_arbitrary_actions_keys_and_invalid_coordinates(self):
        for command in [None, [], {'action': 'navigate', 'url': 'file:///secret'},
                        {'action': 'key', 'key': 'Control+L'}, {'action': 'fill', 'text': 'a' * 4097},
                        *[{'action': 'click', 'x': x, 'y': .1} for x in [-1, 2, float('nan'), float('inf'), True, '1']]]:
            with self.subTest(command=repr(command)[:80]), self.assertRaises(HTTPException):
                self.auth.interact('baize', command)

    def test_bounded_queue_and_source_isolation(self):
        for _ in range(32): self.send(action='key', key='Tab')
        with self.assertRaises(HTTPException) as error: self.send(action='key', key='Enter')
        self.assertEqual(error.exception.status_code, 429)
        with self.assertRaises(HTTPException):
            self.auth.interact('lanorange', {'session_id': 'current', 'action': 'key', 'key': 'Tab'})

    def test_failed_input_does_not_expose_password_in_error(self):
        self.send(action='fill', text='synthetic-password')
        page = Mock(); page.url = 'https://merchant.shangyiworker.com/login'
        page.locator.return_value.fill.side_effect = RuntimeError('synthetic-password')
        self.auth._apply_inputs('baize', page, {'width': 1100, 'height': 850})
        self.assertNotIn('synthetic-password', repr(self.auth.states))
        self.assertTrue(self.auth.status('baize')['input_error'])

    def test_coordinate_boundary_stays_inside_viewport(self):
        self.send(action='click', x=1, y=1)
        page = Mock(); page.url = 'https://merchant.shangyiworker.com/login'
        self.auth._apply_inputs('baize', page, {'width': 1100, 'height': 850})
        page.mouse.click.assert_called_once_with(1099, 849)

    def request(self, method, suffix, *, json_body=None, content=None, origin=None):
        app = FastAPI()
        app.include_router(auth_module.router)
        body = content.encode() if content is not None else json.dumps(json_body or {}).encode()
        headers = [(b'host', b'localhost'), (b'content-type', b'application/json')]
        if origin: headers.append((b'origin', origin.encode()))
        async def run():
            messages = []
            async def receive(): return {'type': 'http.request', 'body': body, 'more_body': False}
            async def send(message): messages.append(message)
            with patch.object(auth_module, 'AUTH', self.auth):
                await app({'type': 'http', 'http_version': '1.1', 'scheme': 'http', 'server': ('localhost', 80),
                           'client': ('127.0.0.1', 12345), 'method': method, 'path': '/api/fengshen-downloads/source-auth/baize/' + suffix,
                           'query_string': b'', 'headers': headers}, receive, send)
            start = next(m for m in messages if m['type'] == 'http.response.start')
            return SimpleNamespace(status_code=start['status'], headers={k.decode(): v.decode() for k,v in start['headers']},
                                   content=b''.join(m.get('body', b'') for m in messages if m['type'] == 'http.response.body'))
        return asyncio.run(run())

    def test_http_routes_keep_origin_guard_and_frame_no_store(self):
        self.auth.states['baize']['image'] = b'synthetic-png'
        response = self.request('GET', 'frame')
        self.assertEqual(response.content, b'synthetic-png')
        self.assertEqual(response.headers['cache-control'], 'no-store')
        command = {'action': 'key', 'key': 'Tab', 'session_id': 'current'}
        self.assertEqual(self.request('POST', 'interact', json_body=command).status_code, 403)
        self.assertEqual(self.request('POST', 'interact', json_body=command, origin='http://other.example').status_code, 403)
        self.assertEqual(self.request('POST', 'interact', json_body=command, origin='http://localhost').status_code, 200)
        self.assertEqual(len(self.auth.inputs['baize']), 1)

    def test_http_rejects_malformed_or_oversized_body_before_queueing(self):
        self.assertEqual(self.request('POST', 'interact', content='{bad', origin='http://localhost').status_code, 400)
        self.assertEqual(self.request('POST', 'interact', content='x' * 32769, origin='http://localhost').status_code, 413)
        self.assertFalse(self.auth.inputs)
