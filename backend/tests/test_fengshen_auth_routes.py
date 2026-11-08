import concurrent.futures
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock, patch
from urllib.parse import quote

from fastapi import HTTPException
from starlette.requests import Request

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import fengshen_auth_routes as routes
from fengshen_auth import AuthError


def request(method="GET", host="192.168.1.2:3000", origin=None, owner="tester", body=None,
            content_type="application/json", scheme="http", extra_headers=None):
    headers = {"host": host, "content-type": content_type, **(extra_headers or {})}
    if owner is not None:
        headers["x-workspace-id"] = quote(owner)
    if origin is not None:
        headers["origin"] = origin
    encoded = json.dumps(body or {}).encode()
    async def receive():
        return {"type": "http.request", "body": encoded, "more_body": False}
    return Request({"type": "http", "method": method, "scheme": scheme, "path": "/api/parttime/fengshen/auth/status",
                    "query_string": b"", "server": ("127.0.0.1", 8009), "client": ("127.0.0.1", 1234),
                    "headers": [(key.encode(), value.encode()) for key, value in headers.items()]}, receive)


def complete(coroutine):
    try:
        coroutine.send(None)
    except StopIteration as result:
        return result.value
    finally:
        coroutine.close()
    raise AssertionError("路由测试意外等待真实 I/O")


async def immediate_wait(awaitable, timeout=None):
    return await awaitable


async def immediate_future(future):
    return future.result()


class AuthRouteTests(unittest.TestCase):
    def setUp(self):
        self.broker = Mock()
        self.broker.active = None
        self.broker.status.return_value = {"state": "signed_out", "message": "等待登录", "saved": False,
                                           "busy": False, "challenge_id": None, "can_send": False,
                                           "can_verify": False, "can_recheck": False}
        mocked = patch.object(routes, "BROKER", self.broker)
        mocked.start()
        self.addCleanup(mocked.stop)

    def assert_rejected(self, req, status=403):
        with self.assertRaises(HTTPException) as result:
            routes.auth_owner(req)
        self.assertEqual(result.exception.status_code, status)
        return result.exception.detail

    def test_lan_get_status_without_origin_is_allowed(self):
        response = routes.status(request())
        self.assertEqual(response["state"], "signed_out")
        self.broker.status.assert_called_once_with("tester")

    def test_rfc1918_and_ula_literal_hosts_are_allowed(self):
        for host in ("10.0.0.1:3000", "172.16.0.1:3000", "172.31.255.254:3000", "192.168.1.2:3000",
                     "[fd12:3456::1]:3000", "[fc00::1]:3000"):
            with self.subTest(host=host):
                self.assertEqual(routes.auth_owner(request(host=host)), "tester")

    def test_public_dns_unspecified_multicast_and_link_local_hosts_are_rejected(self):
        for host in ("8.8.8.8:3000", "172.15.0.1:3000", "172.32.0.1:3000", "100.64.0.1:3000",
                     "192.0.2.1:3000", "169.254.1.2:3000", "example.com:3000", "evil.local:3000",
                     "0.0.0.0:3000", "224.0.0.1:3000", "[::]:3000", "[ff02::1]:3000",
                     "[fe80::1]:3000", "[2001:db8::1]:3000", "[::ffff:192.168.1.2]:3000"):
            with self.subTest(host=host):
                self.assert_rejected(request(host=host))

    def test_loopback_without_origin_stays_compatible(self):
        for host in ("localhost:3000", "127.0.0.1:3000", "127.10.20.30:3000", "[::1]:3000"):
            with self.subTest(host=host):
                self.assertEqual(routes.auth_owner(request("POST", host=host)), "tester")

    def test_lan_posts_require_origin_and_same_origin_is_allowed(self):
        self.assert_rejected(request("POST"))
        self.assertEqual(routes.auth_owner(request("POST", origin="http://192.168.1.2:3000")), "tester")

    def test_origin_must_match_scheme_host_and_effective_port(self):
        for origin in ("https://192.168.1.2:3000", "http://192.168.1.3:3000", "http://192.168.1.2:3001",
                       "http://192.168.1.2", "https://evil.example", "null", "file:///", "http://localhost:3000",
                       "http://user:password@192.168.1.2:3000", "http://192.168.1.2:3000/path",
                       "http://192.168.1.2:3000/?token=x", "http://192.168.1.2:3000/#x",
                       "http://192.168.1.2:invalid"):
            with self.subTest(origin=origin):
                self.assert_rejected(request("POST", origin=origin))

    def test_default_ports_are_normalized(self):
        for host, origin, scheme in (("192.168.1.2", "http://192.168.1.2:80", "http"),
                                     ("192.168.1.2:80", "http://192.168.1.2", "http"),
                                     ("192.168.1.2", "https://192.168.1.2:443", "https"),
                                     ("[fd00::1]:443", "https://[fd00::1]", "https")):
            with self.subTest(host=host, origin=origin):
                self.assertEqual(routes.auth_owner(request("POST", host=host, origin=origin, scheme=scheme)), "tester")

    def test_forwarded_headers_cannot_override_an_untrusted_host_or_origin(self):
        self.assert_rejected(request("POST", host="evil.example", origin="http://192.168.1.2:3000",
                                     extra_headers={"x-forwarded-host": "192.168.1.2:3000", "x-forwarded-proto": "http"}))
        self.assert_rejected(request("POST", origin="https://evil.example",
                                     extra_headers={"x-forwarded-host": "evil.example", "x-forwarded-proto": "https"}))

    def test_workspace_and_json_validation_are_shared(self):
        for helper, host in ((routes.auth_owner, "192.168.1.2:3000"), (routes.local_owner, "localhost:3000")):
            for owner in (None, "", "bad/path", "bad\\path", "a" * 129):
                with self.subTest(helper=helper.__name__, owner=owner), self.assertRaises(HTTPException) as result:
                    helper(request(host=host, owner=owner))
                self.assertEqual(result.exception.status_code, 400)
            self.assertEqual(helper(request(host=host, owner="测试_1")), "测试_1")
            with self.assertRaises(HTTPException) as result:
                helper(request("POST", host=host, origin="http://" + host, content_type="text/plain"))
            self.assertEqual(result.exception.status_code, 415)

    def test_local_owner_still_rejects_lan_workflows(self):
        with self.assertRaises(HTTPException) as result:
            routes.local_owner(request())
        self.assertEqual(result.exception.status_code, 403)

    def test_account_namespace_cannot_be_forged_as_a_workspace(self):
        for owner in ("account_" + "a" * 32, "ACCOUNT_admin"):
            self.assert_rejected(request(owner=owner))
            with self.assertRaises(HTTPException):
                routes.local_owner(request(host="localhost:3000", owner=owner))

    def test_download_login_owner_comes_from_account_session(self):
        user = {"id": "a" * 32, "username": "synthetic", "role": "member", "owner": "account_" + "a" * 32}
        with patch("download_accounts.require_account", return_value=user) as require:
            response = routes.status(request(owner="forged", extra_headers={"x-download-account": "1"}))
        self.assertEqual(response["state"], "signed_out")
        require.assert_called_once()
        self.broker.status.assert_called_once_with(user["owner"])

    def test_download_login_cannot_fallback_to_workspace_when_not_logged_in(self):
        with patch("download_accounts.require_account", side_effect=HTTPException(401, "请先登录")):
            self.assert_rejected(request(extra_headers={"x-download-account": "1"}), status=401)
        self.broker.status.assert_not_called()
        with self.assertRaises(HTTPException) as result:
            routes.local_owner(request(host="127.0.0.1:8009", origin="http://192.168.1.2:3000"))
        self.assertEqual(result.exception.status_code, 403)

    def test_lan_start_uses_mocked_login_and_decoded_workspace(self):
        with patch.object(routes, "start_http_login", return_value={"state": "checking"}) as start:
            result = routes.start(request("POST", origin="http://192.168.1.2:3000", owner="测试_1"))
        self.assertTrue(result["ok"])
        start.assert_called_once_with("测试_1")
        self.broker.submit.assert_not_called()

    def test_all_page_login_entries_use_http_without_starting_browser(self):
        for host in ('localhost:3000','192.168.1.2:3000'):
            with self.subTest(host=host), patch.object(routes,'start_http_login',return_value={'state':'login_required','busy':True,'transport':'http'}) as http, patch('fengshen_auth.start_login') as browser, patch('playwright.sync_api.sync_playwright') as playwright:
                result=routes.start(request('POST',host=host,origin='http://'+host))
            http.assert_called_once_with('tester');browser.assert_not_called();playwright.assert_not_called()
            self.assertEqual(result['status']['transport'],'http')

    def test_download_account_entry_still_uses_http_and_its_own_identity(self):
        with patch('download_accounts.require_account',return_value={'owner':'download_shared'}),patch.object(routes,'start_http_login',return_value={'state':'ready','busy':False}) as http,patch('fengshen_auth.start_login') as browser:
            result=routes.start(request('POST',origin='http://192.168.1.2:3000',extra_headers={'x-download-account':'1'}))
        http.assert_called_once_with('download_shared');browser.assert_not_called()
        self.assertEqual(result['status']['transport'],'http')

    def test_idle_status_selects_internal_flow_without_download_header(self):
        self.assertEqual(routes.status(request())['transport'],'http')
        self.broker.submit.assert_not_called()

    def test_existing_active_browser_operation_is_not_mislabelled_or_restarted(self):
        self.broker.status.return_value={'state':'manual_required','busy':True,'transport':'browser','challenge_id':'synthetic'}
        with patch('download_accounts.require_account',return_value={'owner':'download_shared'}):
            result=routes.status(request(extra_headers={'x-download-account':'1'}))
        self.assertEqual(result['transport'],'browser')
        self.assertEqual(result['challenge_id'],'synthetic')

    def test_lan_send_and_recheck_route_only_to_the_owned_challenge(self):
        for action, body, value in (("send", {"phone": "13800138000"}, "13800138000"), ("recheck", {}, "")):
            future = concurrent.futures.Future()
            future.set_result({"ok": True, "message": "测试已处理"})
            self.broker.submit.return_value = future
            with self.subTest(action=action), patch.object(routes.asyncio, "wrap_future", side_effect=immediate_future), \
                    patch.object(routes.asyncio, "wait_for", side_effect=immediate_wait):
                result = complete(routes.command(action, request("POST", origin="http://192.168.1.2:3000",
                                                                 body={"challenge_id": "synthetic-challenge", **body})))
            self.assertTrue(result["ok"])
            self.broker.submit.assert_called_with("tester", "synthetic-challenge", action, value)

    def test_other_owner_cannot_submit_or_clear_an_owned_challenge(self):
        self.broker.submit.side_effect = AuthError("登录窗口已过期或不属于当前工作区")
        result = complete(routes.command("send", request("POST", origin="http://192.168.1.2:3000", owner="other",
                                                         body={"challenge_id": "synthetic-challenge", "phone": "13800138000"})))
        self.assertFalse(result["ok"])
        self.broker.submit.assert_called_once_with("other", "synthetic-challenge", "send", "13800138000")
        self.broker.active = {"owner": "tester"}
        with self.assertRaises(HTTPException) as result:
            routes.clear(request("POST", origin="http://192.168.1.2:3000", owner="other"))
        self.assertEqual(result.exception.status_code, 409)
        self.broker.clear.assert_not_called()

    def test_rejected_lan_origin_never_reaches_start_or_submit(self):
        with patch.object(routes, "start_http_login") as start:
            with self.assertRaises(HTTPException):
                routes.start(request("POST", origin="http://192.168.1.2:3001"))
            with self.assertRaises(HTTPException):
                complete(routes.command("send", request("POST", origin="http://evil.example",
                                                        body={"challenge_id": "synthetic", "phone": "13800138000"})))
        start.assert_not_called()
        self.broker.submit.assert_not_called()


if __name__ == "__main__":
    unittest.main()
