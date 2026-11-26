import asyncio
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi import FastAPI, HTTPException

sys.path.insert(0, str(Path(__file__).parents[1]))
import issue_rules
import workbench

USER = {'owner': 'tester', 'effective_workspace': 'download_shared', 'role': 'admin'}


def call(method, path, payload=None):
    app = FastAPI()
    app.include_router(workbench.router)
    body = json.dumps(payload).encode() if payload is not None else b''
    messages = []

    async def run():
        scope = dict(type='http', asgi={'version': '3.0'}, http_version='1.1', method=method, scheme='http',
                     path=path, raw_path=path.encode(), query_string=b'', root_path='',
                     headers=[(b'host', b'localhost'), (b'content-type', b'application/json')],
                     client=('127.0.0.1', 1), server=('localhost', 80))
        sent = False

        async def receive():
            nonlocal sent
            if sent:
                return {'type': 'http.disconnect'}
            sent = True
            return {'type': 'http.request', 'body': body, 'more_body': False}

        async def send(message):
            messages.append(message)

        await app(scope, receive, send)

    asyncio.run(run())
    status = next(message['status'] for message in messages if message['type'] == 'http.response.start')
    content = json.loads(b''.join(message.get('body', b'') for message in messages
                                  if message['type'] == 'http.response.body') or b'{}')
    return status, content


class IssueRuleRouteTests(unittest.TestCase):
    def test_list_requires_login(self):
        with patch('download_accounts.require_account', side_effect=HTTPException(401, '请登录')):
            status, body = call('GET', '/api/workbench/issue-rules')
        self.assertEqual(status, 401)
        self.assertEqual(body['detail'], '请登录')

    def test_list_returns_default_and_saved_cities(self):
        saved = issue_rules.default_config()
        saved['grace_seconds'] = 120
        with patch('download_accounts.require_account', return_value=USER), \
                patch('issue_rules.load', return_value={'version': 1, 'cities': {'广州': saved}}):
            status, body = call('GET', '/api/workbench/issue-rules')
        self.assertEqual(status, 200)
        self.assertEqual(body['default']['grace_seconds'], 480)
        self.assertEqual(body['cities']['广州']['grace_seconds'], 120)
        self.assertIn('是否二呼单', body['fields'])
        self.assertIn('站点名称', body['fields'])

    def test_save_rejects_invalid_rules_with_reason(self):
        with patch('download_accounts.require_permission', return_value=USER), \
                patch('issue_rules.save_city', side_effect=issue_rules.IssueRuleError('宽容时长需为 0-3600 的整数秒')):
            status, body = call('PUT', '/api/workbench/issue-rules', {'city': '广州', 'rules': {}})
        self.assertEqual(status, 400)
        self.assertEqual(body['detail'], '宽容时长需为 0-3600 的整数秒')

    def test_preview_without_sample_returns_actionable_message(self):
        with patch('download_accounts.require_account', return_value=USER), \
                patch('issue_rules.preview_sample', side_effect=issue_rules.IssueRuleError('暂无可用于试算的问题单采集样本')):
            status, body = call('POST', '/api/workbench/issue-rules/preview', {'city': '广州', 'rules': {}})
        self.assertEqual(status, 400)
        self.assertIn('样本', body['detail'])


if __name__ == '__main__':
    unittest.main()