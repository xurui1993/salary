"""Read-only deep link used by task-center handoffs, including older exports."""
import asyncio
import json
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
from fastapi import FastAPI, HTTPException
import lanorange_price_export as exports


class PriceExportDetailTests(unittest.TestCase):
    def setUp(self):
        app = FastAPI()
        app.include_router(exports.router)
        self.app = app

    def get(self, path):
        messages = []
        async def request():
            async def receive():
                return {'type': 'http.request', 'body': b'', 'more_body': False}
            async def send(message):
                messages.append(message)
            scope = dict(type='http', asgi={'version': '3.0'}, http_version='1.1', method='GET', scheme='http', path=path, raw_path=path.encode(), root_path='', query_string=b'', headers=[], client=('127.0.0.1', 1234), server=('localhost', 80))
            await self.app(scope, receive, send)
        asyncio.run(request())
        status = next(m['status'] for m in messages if m['type'] == 'http.response.start')
        body = b''.join(m.get('body', b'') for m in messages if m['type'] == 'http.response.body')
        return SimpleNamespace(status_code=status, json=lambda: json.loads(body))

    def test_reads_exact_requested_export_with_authorized_scope(self):
        manager = Mock()
        manager.get.return_value = {'id': 'older-export', 'status': 'completed'}
        with patch.object(exports, 'owner', return_value='shared') as owner, patch.object(exports, 'manager', return_value=manager):
            response = self.get('/api/fengshen-downloads/lanorange-prices/exports/older-export')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['id'], 'older-export')
        owner.assert_called_once()
        manager.get.assert_called_once_with('shared', 'older-export')
        manager.start.assert_not_called()

    def test_unauthorized_request_never_reads_record(self):
        with patch.object(exports, 'owner', side_effect=HTTPException(403, 'denied')), patch.object(exports, 'manager') as manager:
            response = self.get('/api/fengshen-downloads/lanorange-prices/exports/older-export')
        self.assertEqual(response.status_code, 403)
        manager.assert_not_called()

    def test_missing_record_is_not_replaced_with_recent_record(self):
        with patch.object(exports, 'owner', return_value='shared'), patch.object(exports, 'manager') as factory:
            factory.return_value.get.side_effect = exports.ApprovalError('missing', 'missing')
            response = self.get('/api/fengshen-downloads/lanorange-prices/exports/not-found')
        self.assertEqual(response.status_code, 404)


if __name__ == '__main__':
    unittest.main()
