import asyncio
import json
import unittest
from unittest.mock import patch
from urllib.parse import urlencode
from fastapi import FastAPI, HTTPException
import workbench


class DeductionStationRouteTests(unittest.TestCase):
    def get(self, **params):
        app = FastAPI()
        app.include_router(workbench.router)
        messages = []
        async def run():
            scope = dict(type='http', asgi={'version':'3.0'}, http_version='1.1', method='GET', scheme='http',
                path='/api/workbench/deduction-stations', raw_path=b'/api/workbench/deduction-stations',
                query_string=urlencode(params).encode(), root_path='', headers=[(b'host', b'localhost')],
                client=('127.0.0.1',1), server=('localhost',80))
            async def receive():
                return {'type':'http.request','body':b'','more_body':False}
            async def send(message):
                messages.append(message)
            await app(scope,receive,send)
        asyncio.run(run())
        status = next(m['status'] for m in messages if m['type']=='http.response.start')
        body = json.loads(b''.join(m.get('body',b'') for m in messages if m['type']=='http.response.body'))
        return status, body

    def test_read_options_never_saves_deductions(self):
        expected = {'platform':'fengshen','cities':[{'id':'001','name':'测试城'}],
                    'stations':[{'id':'9007199254740993123','name':'测试站','city':'测试城','city_id':'001','platform':'fengshen'}],
                    'fetched_at':'synthetic','cached':False,'scope_note':'授权站点','warnings':[]}
        with patch('download_accounts.require_account') as access, patch('deduction_stations.catalog',return_value=expected) as read, patch.object(workbench,'atomic_json') as write:
            code, body = self.get(platform='fengshen',city=' 测试城 ',refresh='1')
        self.assertEqual(code,200)
        self.assertEqual(body,expected)
        read.assert_called_once_with('fengshen','测试城',True)
        access.assert_called_once()
        write.assert_not_called()

    def test_access_failure_never_queries_platform(self):
        with patch('download_accounts.require_account',side_effect=HTTPException(403,'denied')), patch('deduction_stations.catalog') as read:
            code, body = self.get(platform='fengshen')
        self.assertEqual(code,403)
        read.assert_not_called()

    def test_invalid_platform_is_rejected_before_query(self):
        with patch('download_accounts.require_account'), patch('deduction_stations.catalog') as read:
            code, _ = self.get(platform='unregistered')
        self.assertEqual(code,400)
        read.assert_not_called()

    def test_auth_and_busy_results_stay_actionable_without_leaking_unexpected_errors(self):
        for expected in (401,409):
            with patch('download_accounts.require_account'), patch('deduction_stations.catalog',side_effect=HTTPException(expected,'请登录或稍后获取')):
                code, body = self.get(platform='xiaoxiang')
            self.assertEqual(code,expected)
            self.assertEqual(body['detail'],'请登录或稍后获取')
        with patch('download_accounts.require_account'), patch('deduction_stations.catalog',side_effect=RuntimeError('private-internal-details')):
            code, body = self.get(platform='fengshen')
        self.assertEqual(code,502)
        self.assertNotIn('private-internal-details',json.dumps(body))


if __name__=='__main__':
    unittest.main()
