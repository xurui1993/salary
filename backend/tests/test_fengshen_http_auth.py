import json
from pathlib import Path
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import Mock, patch

import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from fengshen_auth import AuthBroker, AuthError, SessionVault
from fengshen_bill import AuthenticationRequired
import fengshen_http_auth as auth
import fengshen_auth_routes as routes
from test_fengshen_auth_routes import request


MODULUS = "b1" * 128
CONFIG = {"APP_NAME": "LOGISTICS_COMPANY", "authTypeList": "[ACCOUNT, SMS]", "enableRsa": "true",
          "rsaPublicKey": MODULUS, "_sso_csrftoken_": "synthetic-csrf", "needCheckCodeList": "[]",
          "queryString": "APP_NAME=LOGISTICS_COMPANY&amp;sample=1", "umidTokenId": "synthetic-device",
          "phoneNumToken": ""}


def document(**changes):
    return "<script>window.ssoConfig = " + json.dumps({**CONFIG, **changes}) + ";</script>"


class Response:
    def __init__(self, body, status=200, headers=None):
        self.body = json.dumps(body).encode() if isinstance(body, dict) else body.encode()
        self.status_code, self.headers = status, headers or {}

    def __enter__(self):
        return self

    def __exit__(self, *_):
        pass

    def iter_content(self, _):
        yield self.body


class ProtocolTests(unittest.TestCase):
    def setUp(self):
        self.client = Mock()
        self.client.session.request = Mock()
        self.protocol = auth.MoziSmsProtocol(self.client)

    def replies(self, *responses):
        self.client.session.request.side_effect = responses

    def test_rsa_matches_official_module_81939_vector(self):
        # Expected produced by official module with a synthetic public modulus.
        expected = ("3f7bbcbb7b2c673f6615b021d1937943be7c90ca36f6999c375ca064ea3164882"
                    "c24b6b4ab009fcfd0155ba267cec05f91b4a4b58a725a020a52c8ad5c8e5f3f3"
                    "e5e2dacea5baf8a2b2efcea3645661fe1b905f5e60505c2ae1ddcd8f26dd31db9"
                    "4411adf236bcdaa64519d73341cc22e3b69dc46ddff8a689e69ceacb91ec3b")
        self.assertEqual(auth.encrypt_phone("13800138000", CONFIG), expected)

    def test_config_extracts_fields_without_evaluating_javascript(self):
        source = document().replace("};", ',"unexpected":function(){throw Error("not run")}};')
        result = auth.parse_login_config(source)
        self.assertEqual(result["queryString"], "APP_NAME=LOGISTICS_COMPANY&sample=1")
        self.assertNotIn("unexpected", result)

    def test_config_accepts_official_single_quoted_keys(self):
        source = "window.ssoConfig = {" + ",".join(repr(k) + ":" + repr(v) for k, v in CONFIG.items()) + "};"
        self.assertEqual(auth.parse_login_config(source)["APP_NAME"], "LOGISTICS_COMPANY")

    def test_unverified_app_and_no_sms_rejected(self):
        for change in ({"APP_NAME": "OTHER"}, {"authTypeList": "[ACCOUNT]"}, {"_sso_csrftoken_": ""}):
            with self.subTest(change=list(change)), self.assertRaises(AuthError):
                auth.parse_login_config(document(**change))

    def test_extra_verification_stops_before_send(self):
        for change in ({"needCheckCodeList": "[buc]"}, {"trustEnvConf": {"enable": True}},
                       {"faceVerification": {"enable": True}}):
            self.replies(Response(document(**change)))
            with self.assertRaises(auth.ExtraVerificationRequired):
                self.protocol.send("13800138000")
            self.assertEqual(self.client.session.request.call_args.args[0], "GET")
            self.protocol.config = None

    def test_send_matches_observed_form_and_does_not_submit_login(self):
        self.replies(Response(document()), Response({"success": True}))
        self.protocol.send("13800138000")
        call = self.client.session.request.call_args
        self.assertEqual(call.args, ("POST", auth.SEND_URL))
        self.assertFalse(call.kwargs["allow_redirects"])
        form = call.kwargs["data"]
        self.assertNotEqual(form["phone"], "13800138000")
        self.assertEqual(form["areaCode"], "86")
        self.assertEqual(form["identity"], "sms")
        self.assertEqual(form["_sso_csrftoken_"], "synthetic-csrf")
        self.client.identity.assert_not_called()

    def test_send_network_unknown_never_resends(self):
        self.replies(Response(document()), requests.Timeout("do not echo credentials"))
        with self.assertRaises(auth.LoginRequestUncertain) as error:
            self.protocol.send("13800138000")
        self.assertNotIn("credentials", str(error.exception))
        self.assertEqual(self.client.session.request.call_count, 2)
        self.assertEqual(self.protocol.phone, "13800138000")

    def test_alternate_sms_flow_is_not_automatically_sent(self):
        self.replies(Response(document()), Response({"success": False, "errorMsg": "240020"}))
        with self.assertRaises(auth.ExtraVerificationRequired):
            self.protocol.send("13800138000")
        self.assertEqual(self.client.session.request.call_count, 2)

    def test_verify_follows_official_redirect_then_checks_business_identity(self):
        self.protocol.config = auth.parse_login_config(document())
        self.protocol.phone = "13800138000"
        self.replies(Response({"content": {"success": True, "type": "redirect", "extInfo": {
            "redirectURL": "https://httpizza.ele.me/sso/callback?ticket=synthetic"}}}),
            Response("", 302, {"Location": "https://aeolus.ele.me/"}), Response("application"))
        self.protocol.verify("123456")
        call = self.client.session.request.call_args_list[0]
        self.assertEqual(call.args[1], auth.VERIFY_URL + "?APP_NAME=LOGISTICS_COMPANY&sample=1")
        self.assertEqual(call.kwargs["data"]["phoneNumber"], "13800138000")
        self.assertEqual(call.kwargs["data"]["phoneCode"], "123456")
        self.client.identity.assert_called_once()
        self.assertEqual(self.protocol.phone, "")

    def test_sms_success_without_business_identity_is_not_success(self):
        self.protocol.config, self.protocol.phone = CONFIG, "13800138000"
        self.replies(Response({"content": {"success": True}}))
        self.client.identity.side_effect = AuthenticationRequired("expired")
        with self.assertRaises(AuthenticationRequired):
            self.protocol.verify("123456")

    def test_wrong_code_does_not_follow_redirect_or_check_identity(self):
        self.protocol.config, self.protocol.phone = CONFIG, "13800138000"
        self.replies(Response({"content": {"success": False, "msg": "untrusted secret"}}))
        with self.assertRaises(AuthError) as error:
            self.protocol.verify("123456")
        self.assertNotIn("secret", str(error.exception))
        self.client.identity.assert_not_called()

    def test_captcha_and_forced_password_flows_stop(self):
        for content in ({"success": False, "isNeedCheckCode": True}, {"success": True, "code": 240218}):
            self.protocol.config, self.protocol.phone = CONFIG, "13800138000"
            self.replies(Response({"content": content}))
            with self.assertRaises(auth.ExtraVerificationRequired):
                self.protocol.verify("123456")
        self.client.identity.assert_not_called()

    def test_untrusted_redirect_cannot_receive_session(self):
        for url in ("http://aeolus.ele.me/", "https://ele.me.evil.test/", "https://evil.test/", "https://user:pw@ele.me/",
                    "https://127.0.0.1/", "https://aeolus.ele.me:8443/", "https://ele.me\\@evil.test/"):
            with self.subTest(url=url), self.assertRaises(AuthError):
                auth.official_login_url(url)

    def test_post_redirect_is_not_followed(self):
        self.protocol.config = CONFIG
        self.replies(Response("", 302, {"Location": "https://aeolus.ele.me/"}))
        with self.assertRaises(auth.ExtraVerificationRequired):
            self.protocol.send("13800138000")
        self.assertEqual(self.client.session.request.call_count, 1)

    def test_missing_and_invalid_public_key_fail_before_sms(self):
        for key in ("", "nothex", "00" * 128):
            self.protocol.config = {**CONFIG, "rsaPublicKey": key}
            with self.assertRaises(AuthError):
                self.protocol.send("13800138000")
        self.client.session.request.assert_not_called()


class BrokerWorkerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.cancelled = threading.Event()
        self.broker = AuthBroker(SessionVault(Path(self.temp.name) / "session", crypt=lambda value, **_: value))
        self.client = Mock()
        self.client.cancelled = self.cancelled
        self.client.storage_state.return_value = {"cookies": [], "origins": []}
        self.protocol = Mock()
        self.protocol.phone = ""
        self.worker = auth.HTTPAuth(self.client, self.broker, self.cancelled, protocol=self.protocol, timeout=5)
        self.errors = []
        self.result = None

    def start(self, export=False):
        self.client.identity.side_effect = AuthenticationRequired("expired")
        def run():
            try:
                with self.broker.operation("tester", self.cancelled, transport="http"):
                    self.result = self.worker.export_code() if export else self.worker.ensure()
            except Exception as error:
                self.errors.append(error)
        self.thread = threading.Thread(target=run)
        self.thread.start()
        self.addCleanup(self.stop)
        self.wait_state("login_required")

    def stop(self):
        self.cancelled.set()
        self.thread.join(2)

    def wait_state(self, state):
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline:
            if self.broker.state == state:
                return
            time.sleep(0.01)
        self.fail("state not reached: " + state)

    def command(self, action, value=""):
        challenge = self.broker.status("tester")["challenge_id"]
        return self.broker.submit("tester", challenge, action, value).result(timeout=2)

    def test_restored_identity_needs_no_sms_or_login_page(self):
        with self.broker.operation("tester", self.cancelled):
            self.assertTrue(self.worker.ensure())
        self.protocol.send.assert_not_called()
        self.protocol.prepare.assert_not_called()

    def test_expired_session_waits_for_explicit_send_verify_and_saves(self):
        self.start()
        self.protocol.send.assert_not_called()
        self.assertTrue(self.command("send", "13800138000")["ok"])
        # The real verify protocol checks the business session and restores it.
        self.client.identity.side_effect = None
        self.assertTrue(self.command("verify", "123456")["ok"])
        self.thread.join(2)
        self.assertTrue(self.result)
        self.assertTrue(self.broker.vault.path.exists())
        self.protocol.send.assert_called_once_with("13800138000")
        self.protocol.verify.assert_called_once_with("123456")

    def test_extra_verification_remains_blocked_after_failed_recheck(self):
        self.protocol.send.side_effect = auth.ExtraVerificationRequired(auth.EXTRA_MESSAGE)
        self.start()
        self.assertFalse(self.command("send", "13800138000")["ok"])
        self.assertFalse(self.broker.status("tester")["can_send"])
        self.assertFalse(self.command("recheck")["ok"])
        self.assertEqual(self.broker.state, "manual_required")
        self.assertFalse(self.broker.status("tester")["can_send"])

    def test_export_requires_click_sends_to_bound_phone_and_returns_only_in_memory(self):
        self.client.request_json.return_value = {"code": 200, "data": True}
        self.start(export=True)
        status = self.broker.status("tester")
        self.assertFalse(status["phone_required"])
        self.assertEqual(status["purpose"], "export")
        self.assertFalse(status["can_recheck"])
        self.client.request_json.assert_not_called()
        self.assertTrue(self.command("send")["ok"])
        self.client.request_json.assert_called_once_with("POST", auth.EXPORT_SMS_URL)
        response = self.command("verify", "123456")
        self.assertNotIn("123456", json.dumps(response))
        self.thread.join(2)
        self.assertEqual(self.result, "123456")
        self.assertFalse(self.broker.vault.path.exists())

    def test_export_timeout_never_resends_and_accepts_possibly_received_code(self):
        self.client.request_json.side_effect = requests.Timeout()
        self.start(export=True)
        self.assertFalse(self.command("send")["ok"])
        self.assertTrue(self.broker.status("tester")["can_verify"])
        self.assertTrue(self.command("verify", "123456")["ok"])
        self.thread.join(2)
        self.assertEqual(self.result, "123456")
        self.assertEqual(self.client.request_json.call_count, 1)

    def test_payroll_export_keeps_waiting_past_login_timeout_without_sending_sms(self):
        self.worker.wait_export_indefinitely=True
        self.worker.timeout=.02
        self.start(export=True)
        self.thread.join(.08)
        self.assertTrue(self.thread.is_alive())
        self.client.request_json.assert_not_called()
        self.client.request_json.return_value={'code':200,'data':True}
        self.assertTrue(self.command('send')['ok'])
        self.assertTrue(self.command('verify','123456')['ok'])
        self.thread.join(2)
        self.assertEqual(self.result,'123456')

    def test_export_uses_a_fresh_challenge_after_a_previously_hidden_login(self):
        original=self.broker.operation
        challenges=[]
        from contextlib import contextmanager
        @contextmanager
        def operation(*args,**kwargs):
            with original(*args,**kwargs):
                challenges.append(self.broker.status('tester')['challenge_id'])
                yield self.broker
        with patch.object(self.broker,'operation',operation):
            self.start(export=True)
        self.assertNotEqual(self.broker.status('tester')['challenge_id'],challenges[0])
        self.stop()

    def test_cancellation_does_not_save(self):
        self.start()
        self.stop()
        self.assertFalse(self.broker.vault.path.exists())
        self.assertIsInstance(self.errors[0], AuthError)


class HttpRouteTests(unittest.TestCase):
    def test_download_start_only_uses_http_worker(self):
        req = request("POST", origin="http://192.168.1.2:3000", extra_headers={"x-download-account": "1"})
        with patch("download_accounts.require_account", return_value={"owner": "download_shared"}), \
                patch.object(routes, "start_http_login", return_value={"state": "checking"}) as http_start, \
                patch("fengshen_auth.start_login") as browser_start:
            result = routes.start(req)
        http_start.assert_called_once_with("download_shared")
        browser_start.assert_not_called()
        self.assertEqual(result["status"]["transport"], "http")


if __name__ == "__main__":
    unittest.main()
