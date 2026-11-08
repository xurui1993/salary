import contextlib
from pathlib import Path
import json,tempfile,threading,unittest
from types import SimpleNamespace
from unittest.mock import Mock,patch

from fastapi import HTTPException
import auth_math_captcha as math
import binding_source_auth as source
import platform_auth_control as control
from desktop_auth_page import field_role


class MathTests(unittest.TestCase):
    def test_arithmetic_uses_strict_small_expressions(self):
        for text,answer in [('8+7=?','15'),('2-9 = ?','-7'),('3×4','12'),('12÷3=?','4'),('３＋４＝？','7')]:
            with self.subTest(text=text):self.assertEqual(math.solve_expression(text)['answer'],answer)
        for text in ['1/0','3/2','1+2+3','__import__("os")','999999*1','x=3','eval(1+2)',None]:
            with self.subTest(text=text):self.assertIsNone(math.solve_expression(text))

    def test_ocr_requires_two_scale_agreement_and_caches_only_image(self):
        math.recognize_image.cache_clear()
        with patch.object(math.subprocess,'run',return_value=SimpleNamespace(stdout=json.dumps({'texts':['8+7=?','8 + 7 = ?']}))) as run:
            self.assertEqual(math.recognize_image(b'\x89PNGsynthetic-A')['answer'],'15')
            self.assertEqual(math.recognize_image(b'\x89PNGsynthetic-A')['answer'],'15')
        run.assert_called_once();self.assertNotIn('shell',run.call_args.kwargs)

    def test_disagreement_missing_or_malformed_ocr_falls_back_to_manual(self):
        for index,payload in enumerate([{'texts':['8+7','3+7']},{'texts':['8+7']},{'texts':['abc','abc']},[]]):
            with patch.object(math.subprocess,'run',return_value=SimpleNamespace(stdout=json.dumps(payload))):
                self.assertIsNone(math.recognize_image(b'\x89PNGsynthetic-'+bytes([index])))

    def test_password_and_non_image_input_never_reach_ocr(self):
        with patch.object(math.subprocess,'run') as run:
            self.assertIsNone(math.recognize_image(b'not-an-image'))
        run.assert_not_called()

    def test_field_roles_separate_math_from_sms_and_password(self):
        self.assertEqual(field_role('baize','text','验证码 code'),'math')
        self.assertEqual(field_role('lanorange','text','短信验证码'),'sms_code')
        self.assertEqual(field_role('xiaoxiang','tel','手机号码'),'phone')
        self.assertEqual(field_role('baize','password','password'),'password')


class InternalFormTests(unittest.TestCase):
    def setUp(self):
        self.auth=source.SourceAuth();self.auth.states['xiaoxiang']={'state':'waiting_login','session_id':'sid'}
        self.auth.desktop['xiaoxiang']={'form_id':'form','fields':[{'id':'phone','type':'text','role':'phone'}], 'controls':[{'id':'sms','kind':'sms'}]}
        self.phone,self.sms=Mock(),Mock();self.auth.form_bindings['xiaoxiang']={'phone':self.phone,'sms':self.sms}
        self.page=SimpleNamespace(url='https://passport.meituan.com/')

    def test_sms_click_fills_entered_phone_before_click_and_never_logs_it(self):
        calls=Mock();calls.attach_mock(self.phone,'phone');calls.attach_mock(self.sms,'sms')
        self.auth.interact('xiaoxiang',{'session_id':'sid','action':'control','id':'sms','form_id':'form','values':[{'id':'phone','text':'13800138000'}]})
        self.phone.fill.assert_not_called();self.sms.click.assert_not_called()
        self.auth._apply_inputs('xiaoxiang',self.page,{'width':1100,'height':850})
        self.assertEqual([call[0] for call in calls.mock_calls],['phone.fill','sms.click'])
        self.assertNotIn('13800138000',str(self.auth.states)+str(self.auth.desktop))
        self.assertNotIn('xiaoxiang',self.auth.inputs)

    def test_second_sms_is_blocked_without_another_click(self):
        command={'session_id':'sid','action':'control','id':'sms','form_id':'form'}
        self.auth.interact('xiaoxiang',command)
        with self.assertRaises(HTTPException) as caught:self.auth.interact('xiaoxiang',command)
        self.assertEqual(caught.exception.status_code,429)
        self.assertEqual(len(self.auth.inputs['xiaoxiang']),1)

    def test_sms_cooldown_is_separate_between_official_issuers(self):
        command={'session_id':'sid','action':'control','id':'sms','form_id':'form'}
        self.auth.desktop['xiaoxiang']['controls'][0]['issuer']='first.example'
        self.auth.interact('xiaoxiang',command)
        self.assertGreater(self.auth.sms_delay('xiaoxiang'),0)
        self.auth.desktop['xiaoxiang']['controls'][0]['issuer']='second.example'
        self.assertEqual(self.auth.sms_delay('xiaoxiang'),0)
        self.auth.interact('xiaoxiang',command)
        self.assertEqual(len(self.auth.inputs['xiaoxiang']),2)

    def test_stale_form_or_unrecognised_field_cannot_send_sms(self):
        for values,form in [([{'id':'unknown','text':'secret'}],'form'),([], 'old')]:
            with self.assertRaises(HTTPException):self.auth.interact('xiaoxiang',{'session_id':'sid','action':'control','id':'sms','form_id':form,'values':values})
        self.sms.click.assert_not_called()

    def test_lighthouse_page_is_not_auto_switched_to_sms(self):
        mode=Mock();send=Mock()
        first={'fields':[],'controls':[{'id':'mode','kind':'mode','label':'短信登录','enabled':True}],'form_id':'a'}
        next_form={'fields':[{'id':'phone','role':'phone'},{'id':'otp','role':'sms_code'}],'controls':[{'id':'sms','kind':'sms','label':'获取验证码'}],'form_id':'b'}
        with patch('desktop_auth_page.inspect_login_page',side_effect=[(first,{'mode':mode}),(next_form,{'sms':send})]):self.auth._capture_desktop('xiaoxiang',self.page)
        # 默认扫码页保持原状：不代点模式切换，也不触发验证码发送。
        mode.click.assert_not_called();send.click.assert_not_called()
        self.assertEqual(self.auth.desktop['xiaoxiang']['form_id'],'a')

    def test_consent_is_only_checked_by_explicit_submitted_value(self):
        checkbox=Mock();self.auth.desktop['xiaoxiang']['fields'].append({'id':'consent','type':'checkbox','role':'consent'})
        self.auth.form_bindings['xiaoxiang']['consent']=checkbox
        self.auth.interact('xiaoxiang',{'session_id':'sid','action':'fill_fields','form_id':'form','values':[{'id':'consent','text':'true'}]})
        checkbox.set_checked.assert_not_called()
        self.auth._apply_inputs('xiaoxiang',self.page,{'width':1100,'height':850});checkbox.set_checked.assert_called_once_with(True,timeout=3000)


class LogoutTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name);self.addCleanup(self.temp.cleanup)
        self.auth=source.SourceAuth();self.path=self.root/'baize.dpapi';self.path.write_bytes(b'synthetic-encrypted')
        self.patches=[patch.object(source,'ROOT',self.root),patch.object(source,'AUTH',self.auth)]
        for value in self.patches:value.start();self.addCleanup(value.stop)
        control.META.clear()

    def test_idle_logout_removes_only_local_session(self):
        other=self.root/'lanorange.dpapi';other.write_bytes(b'other-session')
        with patch.object(control,'idle_guard',contextlib.nullcontext):result=control.logout('baize',control.version('baize'))
        self.assertEqual(result['state'],'signed_out');self.assertFalse(self.path.exists());self.assertEqual(other.read_bytes(),b'other-session')

    def test_old_version_cannot_cancel_or_clear_new_login(self):
        with patch.object(control,'idle_guard',contextlib.nullcontext),patch.object(self.auth,'cancel') as cancel:
            with self.assertRaises(HTTPException):control.logout('baize','old-version')
        cancel.assert_not_called();self.assertTrue(self.path.exists())

    def test_unreleased_auth_preserves_session_and_reports_wait(self):
        self.auth.workers['baize']=SimpleNamespace(is_alive=lambda:True);self.auth.states['baize']={'state':'waiting_login'};self.auth.cancelled['baize']=threading.Event()
        with patch.object(control,'idle_guard',contextlib.nullcontext):
            with self.assertRaises(HTTPException) as caught:control.logout('baize',control.version('baize'),timeout=0)
        self.assertEqual(caught.exception.status_code,409);self.assertTrue(self.path.exists());self.assertTrue(self.auth.cancelled['baize'].is_set())

    def test_active_business_blocks_logout_before_cancel(self):
        import download_jobs,workbench
        manager=Mock();manager._lock=threading.RLock();connection=Mock();connection.execute.return_value.fetchone.return_value=('active',);manager._connection.return_value=contextlib.nullcontext(connection)
        with patch.object(download_jobs,'get_manager',return_value=manager),patch.object(workbench,'RUNNERS',set()),patch.object(self.auth,'cancel') as cancel:
            with self.assertRaises(HTTPException):control.logout('baize',control.version('baize'))
        cancel.assert_not_called();self.assertTrue(self.path.exists())


if __name__=='__main__':unittest.main()
