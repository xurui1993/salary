import threading,time,unittest
from unittest.mock import patch
import auth_math_captcha as captcha


class DeferredTests(unittest.TestCase):
    def test_slow_ocr_does_not_hold_form_or_requeue_same_image(self):
        entered=threading.Event();release=threading.Event();calls=[];image=b'\x89PNGslow-synthetic-captcha'
        def slow(value):
            calls.append(value);entered.set();release.wait(3);return {'expression':'2 + 3','answer':'5'}
        try:
            with patch.object(captcha,'recognize_image',slow):
                start=time.perf_counter();state,answer=captcha.deferred_answer(image)
                self.assertLess(time.perf_counter()-start,.5);self.assertEqual(state,'recognizing');self.assertIsNone(answer)
                self.assertTrue(entered.wait(1));self.assertEqual(captcha.deferred_answer(image)[0],'recognizing');self.assertEqual(len(calls),1)
                release.set();captcha._ocr_queue.join()
                self.assertEqual(captcha.deferred_answer(image),('solved',{'expression':'2 + 3','answer':'5'}))
                # A prior image result can never be returned as the next image's answer.
                self.assertEqual(captcha.deferred_answer(image+b'new')[0],'recognizing');captcha._ocr_queue.join()
        finally:release.set()
    def test_ocr_failure_returns_manual_and_worker_remains_usable(self):
        with patch.object(captcha,'recognize_image',side_effect=RuntimeError('synthetic')):
            image=b'\x89PNGsynthetic-failure';captcha.deferred_answer(image);captcha._ocr_queue.join()
            self.assertEqual(captcha.deferred_answer(image),('manual',None))

if __name__=='__main__':unittest.main()
