import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch
from fastapi import HTTPException
from binding_source_auth import SourceAuth
from desktop_auth_page import inspect_login_page, official_notice


class DesktopAuthTests(unittest.TestCase):
    def test_sms_notice_classifies_rejections_without_exposing_phone_or_server_detail(self):
        for raw in ('发送过于频繁 phone-secret','手机号无效 phone-secret','请输入正确的手机号 phone-secret','短信发送失败 phone-secret'):
            message,kind=official_notice(raw)
            self.assertEqual(kind,'sms_rejected');self.assertNotIn('phone-secret',message)
        message,kind=official_notice('验证码已发送，请稍候 phone-secret')
        self.assertEqual(kind,'sms_sent');self.assertIn('手机为准',message);self.assertNotIn('phone-secret',message)
        for raw in ('请先阅读并勾选用户协议 phone-secret','为了您的账号安全，请阅读并同意《美团用户协议》《隐私政策》 phone-secret'):
            message,kind=official_notice(raw)
            self.assertEqual(kind,'consent_required');self.assertIn('勾选',message);self.assertNotIn('phone-secret',message)
        message,kind=official_notice('随意文字 phone-secret');self.assertEqual(kind,'unknown');self.assertNotIn('phone-secret',message)
        self.assertEqual(official_notice(''),('',''))

    def test_meituan_official_error_selector_and_security_challenge_are_read(self):
        page,_,_=self.page();frame=page.frames[0];page.url=frame.url='https://passport.meituan.com/'
        original=frame.locator.side_effect;alert=Mock();alert.inner_text.return_value='验证码发送次数上限 phone-secret'
        def locator(query):
            if query.startswith('[role=alert]'):
                self.assertIn('#iLoginCompShowTip:visible',query);self.assertIn('.error-info:visible',query);self.assertIn('#firstTip:visible',query)
                return SimpleNamespace(all=lambda:[alert])
            if query.startswith('#smdcodeYodaRoot'):return SimpleNamespace(all=lambda:[])
            return original(query)
        frame.locator.side_effect=locator
        metadata,_=inspect_login_page('xiaoxiang',page)
        self.assertEqual(metadata['official_feedback_kind'],'sms_rejected');self.assertNotIn('phone-secret',str(metadata))
        challenge=Mock();challenge.is_visible.return_value=True;challenge.evaluate.return_value=True
        frame.locator.side_effect=lambda query:SimpleNamespace(all=lambda:[challenge]) if query.startswith('#smdcodeYodaRoot') else locator(query)
        metadata,_=inspect_login_page('xiaoxiang',page)
        self.assertEqual(metadata['official_feedback_kind'],'challenge');self.assertIn('尚未确认发送',metadata['official_feedback'])

    def test_countdown_span_remains_discoverable_without_scanning_decorative_spans(self):
        page,_,button=self.page();page.url=page.frames[0].url='https://passport.meituan.com/'
        button.evaluate.side_effect=lambda script:True if 'elementFromPoint' in script else '47s'
        metadata,_=inspect_login_page('xiaoxiang',page)
        control=metadata['controls'][0];self.assertEqual(control['kind'],'sms');self.assertEqual(control['retry_after'],47);self.assertFalse(control['enabled'])
        patterns=[call.args[0] for call in page.frames[0].get_by_text.call_args_list]
        self.assertTrue(any(p.fullmatch('47s') for p in patterns))

    def page(self, password='secret-one'):
        field=Mock()
        # Inspector returns presence booleans, not the actual input value.
        field.evaluate.return_value={'type':'password','name':'password','label':'密码','filled':bool(password),'focused':True}
        field.evaluate.side_effect=lambda script:True if 'elementFromPoint' in script else field.evaluate.return_value
        field.bounding_box.return_value={'x':350,'y':300,'width':360,'height':40}
        button=Mock();button.inner_text.return_value='登录';button.is_enabled.return_value=True
        button.evaluate.side_effect=lambda script:True if 'elementFromPoint' in script else '登录'
        button.bounding_box.return_value={'x':350,'y':360,'width':360,'height':40}
        qr=Mock();qr.bounding_box.return_value={'x':390,'y':200,'width':220,'height':220}
        qr.get_attribute.side_effect=lambda key:'qr-code' if key=='class' else ''
        qr.evaluate.return_value='CANVAS'
        frame=Mock();frame.url='https://merchant.shangyiworker.com/login'
        frame.get_by_text.return_value.all.return_value=[]
        frame.locator.side_effect=lambda query:SimpleNamespace(all=lambda:[field] if query.startswith('input:') else [button] if query.startswith('button:') else [qr])
        page=SimpleNamespace(url=frame.url,frames=[frame])
        return page,field,button

    def test_metadata_omits_credentials_and_version_stable_across_value_changes(self):
        page,field,_=self.page()
        first,bindings=inspect_login_page('baize',page)
        self.assertNotIn('secret-one',str(first))
        self.assertNotIn('value',str(first))
        self.assertEqual(first['fields'][0]['label'],'密码')
        field.evaluate.return_value['filled']=False
        second,_=inspect_login_page('baize',page,first)
        self.assertEqual(second['form_id'],first['form_id'])
        self.assertTrue(first['regions']['qr']['width']>220)
        field.evaluate.return_value['name']='changed-form'
        third,_=inspect_login_page('baize',page,first)
        self.assertNotEqual(third['form_id'],first['form_id'])
        self.assertEqual(len(bindings),2)

    def test_untrusted_frames_are_not_exposed(self):
        page,_,_=self.page()
        page.frames[0].url='https://merchant.shangyiworker.com.attacker.example/login'
        result,bindings=inspect_login_page('baize',page)
        self.assertFalse(result['fields']);self.assertFalse(bindings)

    def test_dingtalk_expired_click_to_refresh_is_scoped_qr_control(self):
        page,_,button=self.page();page.url=page.frames[0].url='https://login.dingtalk.com/'
        button.evaluate.side_effect=lambda script:True if 'elementFromPoint' in script else '点击刷新'
        expired=Mock();expired.is_visible.return_value=True;page.frames[0].get_by_text.return_value.first=expired
        metadata,_=inspect_login_page('lanorange',page)
        self.assertEqual(metadata['qr_state'],'expired');self.assertEqual(metadata['controls'][0]['kind'],'qr_refresh')

    def test_named_form_fills_and_submits_only_on_owning_worker(self):
        page,field,button=self.page();metadata,bindings=inspect_login_page('baize',page)
        auth=SourceAuth();auth.states['baize']={'state':'waiting_login','session_id':'sid'}
        auth.desktop['baize']=metadata;auth.form_bindings['baize']=bindings
        command={'action':'fill_fields','session_id':'sid','form_id':metadata['form_id'],'values':[{'id':metadata['fields'][0]['id'],'text':'synthetic-password'}],'submit_id':metadata['controls'][0]['id']}
        auth.interact('baize',command)
        field.fill.assert_not_called();button.click.assert_not_called()
        auth._apply_inputs('baize',page,{'width':1100,'height':850})
        field.fill.assert_called_once_with('synthetic-password',timeout=3000)
        button.click.assert_called_once()
        self.assertNotIn('synthetic-password',str(auth.status('baize')))
        self.assertNotIn('baize',auth.inputs)
        command['form_id']='stale'
        with self.assertRaises(HTTPException):auth.interact('baize',command)

    def test_redirect_prevents_queued_credential_fill(self):
        page,field,_=self.page();metadata,bindings=inspect_login_page('baize',page)
        auth=SourceAuth();auth.states['baize']={'state':'waiting_login','session_id':'sid'}
        auth.desktop['baize']=metadata;auth.form_bindings['baize']=bindings
        auth.interact('baize',{'action':'fill_fields','session_id':'sid','form_id':metadata['form_id'],'values':[{'id':metadata['fields'][0]['id'],'text':'synthetic-secret'}]})
        page.url='https://untrusted.example/login'
        auth._apply_inputs('baize',page,{'width':1100,'height':850})
        field.fill.assert_not_called()
        self.assertTrue(auth.status('baize')['input_error'])

    def test_official_error_and_expired_qr_are_reported_without_echoing_values(self):
        page,_,_=self.page();frame=page.frames[0]
        expired=Mock();expired.is_visible.return_value=True
        frame.get_by_text.return_value.first=expired
        original=frame.locator.side_effect
        alert=Mock();alert.inner_text.return_value='密码错误 synthetic-secret-password'
        frame.locator.side_effect=lambda query:SimpleNamespace(all=lambda:[alert]) if query.startswith('[role=alert]') else original(query)
        metadata,_=inspect_login_page('baize',page)
        self.assertEqual(metadata['qr_state'],'expired')
        self.assertIn('官方未接受',metadata['official_feedback'])
        self.assertNotIn('synthetic-secret-password',str(metadata))

    def test_lighthouse_qr_keeps_scan_view_and_is_captured_for_the_panel(self):
        auth=SourceAuth();page=Mock()
        page.url='https://passport.meituan.com/useraccount/login'
        page.screenshot.return_value=b'\x89PNG\r\n\x1a\n'+b'0'*64
        mode=Mock()
        desktop={'form_id':'qr-form','fields':[],'controls':[{'id':'mode','kind':'mode','label':'账号登录','enabled':True}],
                 'regions':{'qr':{'x':10,'y':10,'width':200,'height':200}},'qr_state':'visible','form_detection':'qr_only'}
        with patch('desktop_auth_page.inspect_login_page',return_value=(desktop,{'mode':mode})):
            auth._capture_desktop('xiaoxiang',page)
        # 灯塔默认扫码页不能被自动切到手机号登录
        mode.click.assert_not_called()
        captured=auth.desktop['xiaoxiang']
        self.assertTrue(captured['has_qr']);self.assertEqual(captured['qr_stage'],'lighthouse')
        self.assertTrue(captured['qr_version'])
        self.assertTrue(auth.states['xiaoxiang']['image_qr'].startswith(b'\x89PNG'))
        page.screenshot.assert_called_once_with(type='png',clip={'x':10,'y':10,'width':200,'height':200},timeout=1500)

    def test_board_qr_is_labelled_as_the_second_stage(self):
        auth=SourceAuth();page=Mock()
        page.url='https://ssosv.sankuai.com/login'
        page.screenshot.return_value=b'\x89PNG\r\n\x1a\n'+b'0'*64
        desktop={'form_id':'board-form','fields':[],'controls':[],
                 'regions':{'qr':{'x':10,'y':10,'width':200,'height':200}},'qr_state':'visible','form_detection':'qr_only'}
        with patch('desktop_auth_page.inspect_login_page',return_value=(desktop,{})):
            auth._capture_desktop('xiaoxiang',page)
        self.assertEqual(auth.desktop['xiaoxiang']['qr_stage'],'board')

    def test_voice_dynamic_code_field_is_recognized_and_not_prefilled(self):
        page,field,button=self.page()
        page.url=page.frames[0].url='https://passport.meituan.com/useraccount/login'
        field.evaluate.side_effect=lambda script:True if 'elementFromPoint' in script else {'type':'text','name':'voiceCode','label':'请输入语音电话里的验证码','filled':False,'focused':False}
        button.evaluate.side_effect=lambda script:True if 'elementFromPoint' in script else '验证'
        original=page.frames[0].locator.side_effect
        yoda=Mock();yoda.is_visible.return_value=True;yoda.evaluate.return_value=True;yoda.bounding_box.return_value={'x':0,'y':0,'width':100,'height':100}
        page.frames[0].locator.side_effect=lambda query:SimpleNamespace(all=lambda:[yoda]) if query.startswith('#smdcodeYodaRoot') else original(query)
        metadata,_=inspect_login_page('xiaoxiang',page)
        self.assertEqual(metadata['fields'][0]['role'],'voice_code')
        self.assertNotIn('preset',metadata['fields'][0])
        self.assertEqual(metadata['controls'][0]['kind'],'submit')
        # 语音页残留的 Yoda 根节点不算安全验证
        self.assertEqual(metadata['official_feedback_kind'],'voice_required')
        self.assertIsNone(metadata['challenge_id']);self.assertNotIn('challenge',metadata['regions'])

    def test_hidden_consent_checkbox_is_exposed_as_auto_consent(self):
        page,field,_=self.page()
        page.url=page.frames[0].url='https://passport.meituan.com/useraccount/login'
        field.evaluate.side_effect=lambda script:True if 'elementFromPoint' in script else {'type':'text','name':'phone','label':'手机号','filled':False,'focused':False}
        consent=Mock();consent.evaluate.return_value={'checked':False}
        original=page.frames[0].locator.side_effect
        page.frames[0].locator.side_effect=lambda query:SimpleNamespace(all=lambda:[consent]) if query.startswith('#iloginUserConfirm') else original(query)
        metadata,bindings=inspect_login_page('xiaoxiang',page)
        item=next(f for f in metadata['fields'] if f['role']=='consent')
        self.assertTrue(item['auto']);self.assertFalse(item['filled'])
        self.assertIn(item['id'],bindings);self.assertTrue(bindings[item['id']] is consent)

    def test_consent_is_auto_checked_but_user_cancel_is_respected(self):
        auth=SourceAuth()
        desktop={'form_id':'form-1','fields':[{'id':'agree','type':'checkbox','role':'consent','filled':False,'auto':True}]}
        element=Mock();element.evaluate.return_value=True
        self.assertTrue(auth._auto_consent('xiaoxiang',desktop,{'agree':element}))
        self.assertTrue(desktop['fields'][0]['filled']);self.assertTrue(desktop['consent_auto'])
        desktop['fields'][0]['filled']=False
        auth.consent_choice['xiaoxiang']={'form_id':'form-1','choice':'unchecked'}
        self.assertFalse(auth._auto_consent('xiaoxiang',desktop,{'agree':element}))

    def test_user_consent_choice_is_recorded_from_panel(self):
        auth=SourceAuth();auth.states['xiaoxiang']={'state':'waiting_login','session_id':'sid'}
        auth.desktop['xiaoxiang']={'form_id':'form-1','fields':[{'id':'agree','type':'checkbox','role':'consent','filled':True,'auto':True}],'controls':[]}
        auth.form_bindings['xiaoxiang']={'agree':Mock()}
        auth.interact('xiaoxiang',{'action':'fill_fields','session_id':'sid','form_id':'form-1','values':[{'id':'agree','text':'false'}]})
        self.assertEqual(auth.consent_choice['xiaoxiang'],{'form_id':'form-1','choice':'unchecked'})

    def test_reinspect_has_command_id_and_never_submits_or_fills(self):
        page,field,button=self.page();auth=SourceAuth();auth.states['baize']={'state':'waiting_login','session_id':'sid'}
        result=auth.interact('baize',{'action':'inspect','session_id':'sid'})
        self.assertEqual(result['command_id'],1);self.assertTrue(auth.status('baize')['input_pending'])
        auth._apply_inputs('baize',page,{'width':1100,'height':850})
        self.assertEqual(auth.status('baize')['input_completed'],1)
        self.assertFalse(auth.status('baize')['input_pending'])
        self.assertEqual(auth.status('baize')['form_detection'],'fields_detected')
        field.fill.assert_not_called();button.click.assert_not_called()


if __name__=='__main__':unittest.main()
