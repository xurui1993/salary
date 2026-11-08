"""Blue QR-only reauthentication: scoped snapshots and no SMS entry, offline only."""
import asyncio
import copy
import threading
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch
from fastapi import FastAPI, HTTPException
import binding_source_auth as module
from binding_source_auth import SourceAuth

PNG=b'\x89PNG\r\n\x1a\nsynthetic-qr'


class BlueQrTests(unittest.TestCase):
    def setUp(self):
        self.auth=SourceAuth();self.auth.states['lanorange']={'state':'waiting_login','session_id':'sid'}
        self.region={'x':100,'y':80,'width':268,'height':268}
        self.meta={'form_id':'form','fields':[],'controls':[], 'qr_state':'visible','regions':{'qr':self.region}}
        self.page=Mock();self.page.url='https://login.dingtalk.com/';self.page.screenshot.return_value=PNG

    def capture(self,meta=None,bindings=None,source='lanorange'):
        with patch('desktop_auth_page.inspect_login_page',return_value=(copy.deepcopy(meta or self.meta),bindings or {})):
            self.auth._capture_desktop(source,self.page)

    def send(self,**data):
        return self.auth.interact('lanorange',{'session_id':'sid','form_id':self.auth.desktop.get('lanorange',{}).get('form_id'),**data})

    def test_blue_only_defaults_to_qr(self):
        self.assertEqual(self.auth.login_mode('lanorange'),'qr')
        for source in ('baize','xiaoxiang'):self.assertEqual(self.auth.login_mode(source),'sms')

    def test_qr_snapshot_is_cropped_bounded_and_not_in_status(self):
        self.capture()
        self.page.screenshot.assert_called_once_with(type='png',clip=self.region,timeout=1500)
        status=self.auth.status('lanorange');self.assertTrue(status['has_qr']);self.assertEqual(len(status['qr_version']),20)
        self.assertNotIn(PNG.decode('latin1'),repr(status));self.assertNotIn('image',status)

    def test_repeated_capture_is_throttled_and_version_stable(self):
        self.capture();first=self.auth.status('lanorange')['qr_version'];self.capture()
        self.page.screenshot.assert_called_once();self.assertEqual(self.auth.status('lanorange')['qr_version'],first)

    def test_bad_image_or_oversize_clears_old_qr(self):
        for data in (b'not-a-png',PNG+b'x'*(512*1024)):
            self.auth.qr_captured_at.clear();self.auth.states['lanorange']['image']=PNG
            self.page.screenshot.return_value=data;self.capture()
            self.assertFalse(self.auth.status('lanorange')['has_qr'])

    def test_missing_or_untrusted_qr_clears_previous_image(self):
        self.capture();self.meta['regions']={};self.capture();self.assertFalse(self.auth.status('lanorange')['has_qr'])
        self.page.url='https://login.dingtalk.com.attacker.example/';self.meta['regions']={'qr':self.region}
        self.page.screenshot.reset_mock();self.capture();self.page.screenshot.assert_not_called()

    def test_default_never_selects_sms_mode(self):
        mode=Mock();meta={**self.meta,'regions':{},'qr_state':'not_detected','controls':[{'id':'smsmode','kind':'mode','label':'短信登录'}]}
        self.capture(meta,{'smsmode':mode});mode.click.assert_not_called()

    def test_default_selects_official_qr_mode_without_sending_sms(self):
        mode=Mock();sms=Mock();first={**self.meta,'regions':{},'qr_state':'not_detected','controls':[{'id':'qr','kind':'mode','label':'扫码登录'},{'id':'sms','kind':'sms','label':'获取验证码'}]}
        with patch('desktop_auth_page.inspect_login_page',side_effect=[(first,{'qr':mode,'sms':sms}),(self.meta,{})]):self.auth._capture_desktop('lanorange',self.page)
        mode.click.assert_called_once();sms.click.assert_not_called();self.assertTrue(self.auth.status('lanorange')['has_qr'])

    def test_blue_rejects_form_and_legacy_coordinate_commands(self):
        self.capture()
        for command in ({'action':'fill_fields','values':[]},{'action':'fill','text':'secret'},{'action':'click','x':.5,'y':.5},{'action':'key','key':'Enter'},{'action':'scroll','direction':'up'}):
            with self.subTest(command=command),self.assertRaises(HTTPException):self.send(**command)
        self.assertFalse(self.auth.inputs)

    def test_removed_mode_command_cannot_restore_sms(self):
        self.capture()
        with self.assertRaises(HTTPException):self.send(action='login_mode',mode='sms')
        with self.assertRaises(HTTPException):self.auth.interact('baize',{'action':'login_mode','mode':'qr','session_id':'sid'})

    def test_stale_queued_refresh_does_not_click_new_form(self):
        refresh=Mock();self.capture({**self.meta,'controls':[{'id':'refresh','kind':'qr_refresh'}]},{'refresh':refresh})
        self.send(action='control',id='refresh',values=[]);self.auth.desktop['lanorange']['form_id']='new-form'
        self.auth._apply_inputs('lanorange',self.page,{'width':1100,'height':850})
        refresh.click.assert_not_called();self.assertTrue(self.auth.status('lanorange')['input_error'])

    def test_cancel_prevents_pending_qr_refresh(self):
        refresh=Mock();self.capture({**self.meta,'controls':[{'id':'refresh','kind':'qr_refresh'}]},{'refresh':refresh})
        self.send(action='control',id='refresh',values=[]);event=threading.Event();event.set();self.auth.cancelled['lanorange']=event
        self.auth._apply_inputs('lanorange',self.page,{'width':1100,'height':850});refresh.click.assert_not_called()

    def test_qr_mode_cannot_send_sms_even_when_dom_contains_sms_control(self):
        self.capture({**self.meta,'controls':[{'id':'sms','kind':'sms'}]},{'sms':Mock()})
        with self.assertRaises(HTTPException) as caught:self.send(action='control',id='sms',values=[])
        self.assertEqual(caught.exception.status_code,400);self.assertFalse(self.auth.inputs)

    def test_refresh_is_explicit_queued_once_and_keeps_qr_mode(self):
        refresh=Mock();self.capture({**self.meta,'controls':[{'id':'refresh','kind':'qr_refresh'}]},{'refresh':refresh})
        self.send(action='control',id='refresh',values=[]);refresh.click.assert_not_called()
        self.auth._apply_inputs('lanorange',self.page,{'width':1100,'height':850});refresh.click.assert_called_once()
        self.assertEqual(self.auth.login_mode('lanorange'),'qr')

    def response(self,query):
        app=FastAPI();app.include_router(module.router)
        async def run():
            messages=[]
            async def receive():return {'type':'http.request','body':b'','more_body':False}
            async def send(value):messages.append(value)
            with patch.object(module,'AUTH',self.auth):
                await app({'type':'http','http_version':'1.1','scheme':'http','server':('localhost',80),'client':('127.0.0.1',1234),'method':'GET','path':'/api/fengshen-downloads/source-auth/lanorange/qr','query_string':query.encode(),'headers':[(b'host',b'localhost')]},receive,send)
            return next(m for m in messages if m['type']=='http.response.start'),b''.join(m.get('body',b'') for m in messages if m['type']=='http.response.body')
        return asyncio.run(run())

    def test_qr_http_requires_current_session_and_never_caches(self):
        self.capture();self.assertEqual(self.response('')[0]['status'],409);self.assertEqual(self.response('session_id=old')[0]['status'],409)
        start,body=self.response('session_id=sid');self.assertEqual(start['status'],200);self.assertEqual(body,PNG)
        self.assertIn((b'cache-control',b'no-store'),start['headers'])

    def test_qr_http_rejects_ready_or_cancelling_even_with_old_image(self):
        self.capture()
        for updates in ({'state':'ready'},{'state':'waiting_login','cancelling':True}):
            self.auth.states['lanorange'].update(updates);self.assertEqual(self.response('session_id=sid')[0]['status'],409)


if __name__=='__main__':unittest.main()
