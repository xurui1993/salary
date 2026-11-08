import unittest
from types import SimpleNamespace
from unittest.mock import Mock,patch
from fastapi import HTTPException
from auth_challenge import gesture,region,apply_gesture,notice_detail,NOTICE_SCRIPT
from xiaoxiang_source_auth import XiangAuth
import binding_source_auth as source
from desktop_auth_page import official_notice

BOX={'x':400,'y':160,'width':320,'height':180}


class ChallengeTests(unittest.TestCase):
    def controller(self):
        auth=XiangAuth();auth.states['xiaoxiang']={'state':'waiting_login','session_id':'sid'}
        auth.desktop['xiaoxiang']={'has_challenge':True,'challenge_id':'widget','challenge_version':'image','regions':{'challenge':dict(BOX)}}
        widget=Mock();widget.is_visible.return_value=True;widget.bounding_box.return_value=dict(BOX)
        auth.form_bindings['xiaoxiang']={'challenge:widget':widget,'sms':Mock()}
        page=Mock();page.url='https://passport.meituan.com/'
        return auth,widget,page

    def command(self,**extra):return {'action':'challenge_gesture','session_id':'sid','challenge_id':'widget','challenge_version':'image','points':[[.1,.5],[.8,.5]],'duration_ms':500,**extra}

    def test_only_human_supplied_path_is_queued_and_applied_by_browser_owner(self):
        auth,widget,page=self.controller();result=auth.interact('xiaoxiang',self.command())
        page.mouse.down.assert_not_called();self.assertEqual(result['command_id'],1)
        auth._apply_inputs('xiaoxiang',page,{'width':1100,'height':850})
        page.mouse.move.assert_any_call(432,250);page.mouse.move.assert_any_call(656,250)
        page.mouse.down.assert_called_once();page.mouse.up.assert_called_once()
        auth.form_bindings['xiaoxiang']['sms'].click.assert_not_called();widget.fill.assert_not_called()

    def test_single_click_uses_widget_locator_instead_of_page_click(self):
        auth,widget,page=self.controller();auth.interact('xiaoxiang',self.command(points=[[.5,.5]]));auth._apply_inputs('xiaoxiang',page,{})
        widget.click.assert_called_once_with(position={'x':160.0,'y':90.0},timeout=1500);page.mouse.click.assert_not_called()

    def test_wrong_session_stale_widget_or_other_platform_rejected(self):
        auth,widget,page=self.controller()
        for cmd in (self.command(session_id='other'),self.command(challenge_id='old'),self.command(challenge_version='old')):
            with self.assertRaises(HTTPException):auth.interact('xiaoxiang',cmd)
        with self.assertRaises(HTTPException):auth.interact('baize',self.command())
        auth.desktop['xiaoxiang']['has_challenge']=False
        with self.assertRaises(HTTPException):auth.interact('xiaoxiang',self.command())
        widget.click.assert_not_called()

    def test_outside_nonfinite_oversized_paths_and_invalid_duration_rejected(self):
        for extra in ({'points':[]},{'points':[[1.1,.5]]},{'points':[[float('nan'),0]]},{'points':[[True,0]]},{'points':[[0,0]]*65},{'duration_ms':True},{'duration_ms':3001},{'duration_ms':99}):
            with self.subTest(extra=extra),self.assertRaises(HTTPException):gesture(self.command(**extra))

    def test_widget_moved_hidden_or_page_changed_prevents_mouse_action(self):
        for case in ('moved','hidden','page'):
            auth,widget,page=self.controller();auth.interact('xiaoxiang',self.command())
            if case=='moved':widget.bounding_box.return_value={**BOX,'x':0}
            if case=='hidden':widget.is_visible.return_value=False
            if case=='page':page.url='https://untrusted.example/'
            auth._apply_inputs('xiaoxiang',page,{})
            page.mouse.down.assert_not_called();self.assertTrue(auth.status()['input_error'])

    def test_pointer_released_even_when_official_widget_interrupts_drag(self):
        widget=Mock();widget.is_visible.return_value=True;widget.bounding_box.return_value=dict(BOX)
        page=Mock();page.mouse.move.side_effect=[None,RuntimeError('synthetic')]
        with self.assertRaises(RuntimeError):apply_gesture(page,widget,BOX,gesture(self.command()))
        page.mouse.up.assert_called_once()

    def test_changed_widget_after_queue_is_not_clicked(self):
        auth,widget,page=self.controller();auth.interact('xiaoxiang',self.command())
        auth.desktop['xiaoxiang']['challenge_id']='changed';auth._apply_inputs('xiaoxiang',page,{})
        page.mouse.down.assert_not_called();widget.click.assert_not_called()

    def test_refreshed_image_after_queue_is_not_clicked(self):
        auth,widget,page=self.controller();auth.interact('xiaoxiang',self.command())
        auth.desktop['xiaoxiang']['challenge_version']='refreshed';auth._apply_inputs('xiaoxiang',page,{})
        page.mouse.down.assert_not_called();widget.click.assert_not_called()

    def test_crop_refuses_full_page_offscreen_and_nonfinite_geometry(self):
        self.assertEqual(region(BOX),BOX)
        for box in ({**BOX,'width':1100},{**BOX,'x':-1},{**BOX,'height':float('inf')},{**BOX,'y':800},{**BOX,'width':10}):self.assertIsNone(region(box))

    def test_capture_exposes_only_widget_crop_then_clears_image_when_widget_disappears(self):
        auth,widget,page=self.controller();page.screenshot.return_value=b'\x89PNG\r\n\x1a\nsynthetic'
        meta={'fields':[],'controls':[],'challenge_id':'widget','_challenge':widget,'regions':{'challenge':dict(BOX)}}
        with patch('desktop_auth_page.inspect_login_page',return_value=(meta,{})):
            auth._capture_desktop('xiaoxiang',page)
        page.screenshot.assert_called_once_with(type='png',clip=BOX,timeout=1500)
        state=auth.status();self.assertTrue(state['has_challenge']);self.assertNotIn('_challenge',state)
        self.assertNotIn(widget,state.values());self.assertFalse(state['has_qr'])
        with patch('desktop_auth_page.inspect_login_page',return_value=({'fields':[],'controls':[],'regions':{}},{})):
            auth._capture_desktop('xiaoxiang',page)
        self.assertFalse(auth.status()['has_challenge']);self.assertNotIn('image',auth.states['xiaoxiang'])

    def test_invalid_or_oversized_capture_never_becomes_interactive(self):
        for image in (b'not an image',b'\x89PNG\r\n\x1a\n'+b'x'*512*1024):
            auth,widget,page=self.controller();page.screenshot.return_value=image
            with patch('desktop_auth_page.inspect_login_page',return_value=({'fields':[],'controls':[],'challenge_id':'widget','_challenge':widget,'regions':{'challenge':dict(BOX)}},{})):
                auth._capture_desktop('xiaoxiang',page)
            self.assertFalse(auth.status()['has_challenge']);self.assertNotIn('image',auth.states['xiaoxiang'])

    def test_notice_redacts_long_tokens_numbers_and_urls_without_printing_values(self):
        node=Mock();node.evaluate.return_value='环境异常，编号12345，synthetic-password，https://example.test/token'
        text=notice_detail(node)
        self.assertNotIn('12345',text);self.assertNotIn('synthetic-password',text);self.assertNotIn('example',text)
        self.assertIn('环境异常',text);self.assertIn('querySelectorAll',NOTICE_SCRIPT)

    def test_environment_rejection_is_distinct_from_visible_security_challenge(self):
        self.assertEqual(official_notice('当前环境异常')[1],'environment_rejected')
        self.assertEqual(official_notice('请完成安全验证')[1],'challenge')
        self.assertEqual(official_notice('操作失败')[1],'rejected')

    def test_challenge_frame_requires_current_session_and_is_not_cached(self):
        auth,widget,page=self.controller();auth.states['xiaoxiang']['image']=b'\x89PNG\r\n\x1a\nsynthetic'
        with patch.object(source,'require_admin'),patch('xiaoxiang_source_auth.AUTH',auth):
            for params in ({},{'session_id':'old'},{'session_id':'sid','v':'old'}):
                with self.assertRaises(HTTPException):source.qr('xiaoxiang',SimpleNamespace(query_params=params))
            response=source.qr('xiaoxiang',SimpleNamespace(query_params={'session_id':'sid','v':'image'}))
            self.assertEqual(response.headers['cache-control'],'no-store');self.assertEqual(response.body,auth.states['xiaoxiang']['image'])
