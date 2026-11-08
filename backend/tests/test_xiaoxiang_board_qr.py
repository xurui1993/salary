"""小象两段扫码：灯塔（美团App）与知了看板（大象）分别截取，短信页不得暴露二维码。"""
import copy
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch
from fastapi import HTTPException
import binding_source_auth as module
import xiaoxiang_source_auth as xiang

PNG=b'\x89PNG\r\n\x1a\nsynthetic-qr'


class BoardQrCaptureTests(unittest.TestCase):
    def setUp(self):
        self.auth=xiang.XiangAuth();self.auth.states['xiaoxiang']={'state':'waiting_login','session_id':'sid'}
        self.region={'x':820,'y':300,'width':180,'height':180}
        self.meta={'form_id':'form','fields':[],'controls':[],'qr_state':'visible','regions':{'qr':self.region}}
        self.page=Mock();self.page.screenshot.return_value=PNG

    def capture(self,url):
        self.page.url=url
        with patch('desktop_auth_page.inspect_login_page',return_value=(copy.deepcopy(self.meta),{})):
            self.auth._capture_desktop('xiaoxiang',self.page)
        return self.auth.desktop['xiaoxiang']

    def test_board_sso_qr_is_cropped_and_exposed_to_panel(self):
        desktop=self.capture('https://ssosv.sankuai.com/sson/login?x=1')
        self.page.screenshot.assert_called_once_with(type='png',clip=self.region,timeout=1500)
        self.assertTrue(desktop['has_qr']);self.assertEqual(len(desktop['qr_version']),20)
        self.assertEqual(self.auth.states['xiaoxiang']['image_qr'],PNG)
        status=self.auth.status();self.assertNotIn('image_qr',status);self.assertTrue(status['has_qr'])

    def test_board_page_on_zl_host_also_serves_qr(self):
        self.assertTrue(self.capture('https://zl.meituan.com/board/delivery.html')['has_qr'])

    def test_lighthouse_passport_qr_is_exposed_as_first_stage(self):
        desktop=self.capture('https://passport.meituan.com/useraccount/login?continue=x')
        self.page.screenshot.assert_called_once_with(type='png',clip=self.region,timeout=1500)
        self.assertTrue(desktop['has_qr']);self.assertEqual(desktop['qr_stage'],'lighthouse')

    def test_sms_stage_never_exposes_a_qr(self):
        self.meta.pop('regions')
        desktop=self.capture('https://passport.meituan.com/account/unitivelogin')
        self.page.screenshot.assert_not_called();self.assertFalse(desktop['has_qr'])
        self.assertNotIn('image_qr',self.auth.states['xiaoxiang'])

    def test_expired_board_qr_stays_refreshable_without_stale_image(self):
        self.meta['qr_state']='expired'
        desktop=self.capture('https://zl.meituan.com/board/delivery.html')
        self.page.screenshot.assert_not_called();self.assertTrue(desktop['has_qr'])
        self.assertNotIn('qr_version',desktop);self.assertNotIn('image_qr',self.auth.states['xiaoxiang'])


class BoardQrEndpointTests(unittest.TestCase):
    def setUp(self):
        self.auth=xiang.XiangAuth()
        self.auth.states['xiaoxiang']={'state':'waiting_login','session_id':'sid','image':PNG,'image_qr':b'board-qr'}
        self.auth.desktop['xiaoxiang']={'qr_version':'v1','challenge_version':'v2','regions':{}}

    def request(self,**params):return SimpleNamespace(query_params=params)

    def test_serves_board_qr_for_matching_version(self):
        with patch.object(module,'require_admin'),patch.object(xiang,'AUTH',self.auth):
            response=module.qr('xiaoxiang',self.request(session_id='sid',v='v1'))
        self.assertEqual(response.body,b'board-qr');self.assertEqual(response.media_type,'image/png')

    def test_serves_challenge_image_for_matching_version(self):
        with patch.object(module,'require_admin'),patch.object(xiang,'AUTH',self.auth):
            response=module.qr('xiaoxiang',self.request(session_id='sid',v='v2'))
        self.assertEqual(response.body,PNG)

    def test_stale_version_or_session_is_rejected(self):
        for params in ({'session_id':'sid','v':'old'},{'session_id':'other','v':'v1'},{'v':'v1'}):
            with self.subTest(params=params),patch.object(module,'require_admin'),patch.object(xiang,'AUTH',self.auth),self.assertRaises(HTTPException):
                module.qr('xiaoxiang',self.request(**params))


if __name__=='__main__':unittest.main()
