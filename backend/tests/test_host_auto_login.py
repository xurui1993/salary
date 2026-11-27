import asyncio
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi import HTTPException, Request, Response

import download_accounts as da
import global_workbench_config as gcfg
import workspace_auth_routes as auth_routes
import workspace_context as wctx


def make_request(
    method: str,
    path: str,
    *,
    host: str = "127.0.0.1:3000",
    client: str = "127.0.0.1",
    cookie: str = "",
    body: dict | None = None,
    extra_headers: dict[str, str] | None = None,
) -> Request:
    raw_body = json.dumps(body).encode("utf-8") if body is not None else b""
    headers = [
        (b"host", host.encode("latin-1")),
        (b"origin", f"http://{host}".encode("latin-1")),
    ]
    if body is not None:
        headers.append((b"content-type", b"application/json"))
    if cookie:
        headers.append((b"cookie", cookie.encode("latin-1")))
    for k, v in (extra_headers or {}).items():
        headers.append((k.lower().encode("latin-1"), v.encode("latin-1")))

    sent = False

    async def receive():
        nonlocal sent
        if sent:
            return {"type": "http.request", "body": b"", "more_body": False}
        sent = True
        return {"type": "http.request", "body": raw_body, "more_body": False}

    scope = {
        "type": "http",
        "http_version": "1.1",
        "method": method,
        "scheme": "http",
        "path": path,
        "raw_path": path.encode("latin-1"),
        "query_string": b"",
        "headers": headers,
        "client": (client, 54321),
        "server": (host.split(":")[0], int(host.split(":")[1]) if ":" in host else 80),
    }
    return Request(scope, receive)


def extract_session_cookie(response: Response) -> str:
    for name, value in response.raw_headers:
        if name.lower() == b"set-cookie":
            text = value.decode("latin-1")
            if text.startswith(f"{da.COOKIE_NAME}="):
                return text.split(";", 1)[0]
    return ""


class HostAutoLoginTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        (self.root / "data").mkdir(parents=True, exist_ok=True)
        (self.root / "data" / "config.json").write_text("[]", encoding="utf-8")
        self.store = da.AccountStore(self.root / "accounts.sqlite3")
        self.proxy_secret = "unit-test-proxy-secret-0123456789"
        self.host_lan_ip = "192.168.10.2"
        self.remote_lan_ip = "192.168.10.99"

        patches = [
            patch.object(da, "get_account_store", return_value=self.store),
            patch.object(auth_routes, "get_account_store", return_value=self.store),
            patch.object(auth_routes, "PROJECT_ROOT", self.root),
            patch.object(wctx, "PROJECT_ROOT", self.root),
            patch.object(gcfg, "_CONFIG_PATH", self.root / "data" / "workbench_global_config.json"),
            patch.object(gcfg, "_CACHE", None),
            patch.object(da, "_host_interface_addresses", return_value={"127.0.0.1", "::1", self.host_lan_ip}),
            patch.object(auth_routes, "_host_interface_addresses", return_value={"127.0.0.1", "::1", self.host_lan_ip}),
            patch.dict(os.environ, {"FENGSHEN_DOWNLOAD_PROXY_SECRET": self.proxy_secret}, clear=False),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)

    def test_host_loopback_and_host_nic_auto_login_without_bootstrap(self):
        # Fresh DB: loopback host auto-logs in immediately as built-in host super-admin
        res1 = Response()
        req1 = make_request("GET", "/api/auth/session", host="127.0.0.1:3000", client="127.0.0.1")
        sess1 = auth_routes.get_session(req1, res1)
        self.assertTrue(sess1["authenticated"])
        self.assertTrue(sess1["initialized"])
        self.assertTrue(sess1["host_machine"])
        self.assertTrue(sess1["host_auto_login"])
        self.assertFalse(sess1["can_switch_to_host"])
        self.assertFalse(sess1["bootstrap_allowed"])
        self.assertEqual(sess1["user"]["role"], "admin")
        self.assertEqual(sess1["user"]["display_name"], "主机管理员")
        self.assertEqual(sess1["user"]["workspace_id"], wctx.PRIMARY_WORKSPACE)
        self.assertFalse(sess1["user"]["has_password"])
        self.assertTrue(extract_session_cookie(res1).startswith(f"{da.COOKIE_NAME}="))

        # Host machine accessing via its own LAN NIC IP also auto-logs in as the same admin
        res2 = Response()
        req2 = make_request("GET", "/api/auth/session", host=f"{self.host_lan_ip}:3000", client=self.host_lan_ip)
        sess2 = auth_routes.get_session(req2, res2)
        self.assertTrue(sess2["authenticated"])
        self.assertTrue(sess2["host_auto_login"])
        self.assertEqual(sess2["user"]["id"], sess1["user"]["id"])
        self.assertEqual(len(self.store.users()), 1)

    def test_non_host_lan_client_requires_login_and_fails_closed(self):
        # Non-host LAN client gets unauthenticated login portal state (never auto-login, never bootstrap)
        res = Response()
        req = make_request(
            "GET",
            "/api/auth/session",
            host=f"{self.host_lan_ip}:3000",
            client=self.remote_lan_ip,
        )
        sess = auth_routes.get_session(req, res)
        self.assertFalse(sess["authenticated"])
        self.assertTrue(sess["initialized"])
        self.assertFalse(sess["host_machine"])
        self.assertFalse(sess["host_auto_login"])
        self.assertFalse(sess["can_switch_to_host"])
        self.assertFalse(sess["bootstrap_allowed"])
        self.assertIsNone(sess["user"])
        self.assertEqual(sess["workspaces"], [])
        self.assertEqual(extract_session_cookie(res), "")

        # Protected endpoint rejects unauthenticated LAN client with 401
        with self.assertRaises(HTTPException) as err:
            da.require_account(req)
        self.assertEqual(err.exception.status_code, 401)

        # Internal gateway resolver rejects LAN client without cookie (even though peer is loopback)
        resolve_lan = make_request(
            "GET",
            "/api/auth/internal/resolve",
            host="127.0.0.1:8765",
            client="127.0.0.1",
            extra_headers={
                "x-download-proxy-secret": self.proxy_secret,
                "x-download-client-address": self.remote_lan_ip,
            },
        )
        resolved_lan = auth_routes.internal_resolve(resolve_lan)
        self.assertFalse(resolved_lan["authenticated"])
        self.assertTrue(resolved_lan["enforce"])

        # Missing client address header fails closed (does NOT grant host auto-login)
        resolve_missing = make_request(
            "GET",
            "/api/auth/internal/resolve",
            host="127.0.0.1:8765",
            client="127.0.0.1",
            extra_headers={"x-download-proxy-secret": self.proxy_secret},
        )
        resolved_missing = auth_routes.internal_resolve(resolve_missing)
        self.assertFalse(resolved_missing["authenticated"])
        self.assertTrue(resolved_missing["enforce"])

        # Loopback client address through trusted proxy DOES grant host auto-login
        resolve_host = make_request(
            "GET",
            "/api/auth/internal/resolve",
            host="127.0.0.1:8765",
            client="127.0.0.1",
            extra_headers={
                "x-download-proxy-secret": self.proxy_secret,
                "x-download-client-address": "127.0.0.1",
            },
        )
        resolved_host = auth_routes.internal_resolve(resolve_host)
        self.assertTrue(resolved_host["authenticated"])
        self.assertEqual(resolved_host["user"]["role"], "admin")

        # Remote client forging x-download-client-address with invalid proxy secret gets 403
        forged_req = make_request(
            "GET",
            "/api/auth/session",
            host=f"{self.host_lan_ip}:3000",
            client=self.remote_lan_ip,
            extra_headers={
                "x-download-proxy-secret": "wrong-secret",
                "x-download-client-address": "127.0.0.1",
            },
        )
        with self.assertRaises(HTTPException) as forge_err:
            auth_routes.get_session(forged_req, Response())
        self.assertEqual(forge_err.exception.status_code, 403)

        # Remote client cannot password-login as built-in passwordless host_admin
        self.store.ensure_host_admin()
        login_builtin_req = make_request(
            "POST",
            "/api/auth/login",
            host=f"{self.host_lan_ip}:3000",
            client=self.remote_lan_ip,
            body={"username": "host_admin", "password": "!host-local-only!"},
        )
        with self.assertRaises(HTTPException) as login_err:
            asyncio.run(auth_routes.login(login_builtin_req, Response()))
        self.assertEqual(login_err.exception.status_code, 401)

        # Bootstrap route is retired (410) and registration/approval routes have been removed completely
        boot_req = make_request(
            "POST",
            "/api/auth/bootstrap",
            host="127.0.0.1:3000",
            client="127.0.0.1",
            body={"username": "admin", "password": "password123"},
        )
        with self.assertRaises(HTTPException) as boot_err:
            asyncio.run(auth_routes.bootstrap_admin(boot_req, Response()))
        self.assertEqual(boot_err.exception.status_code, 410)
        self.assertFalse(hasattr(auth_routes, "register"))
        self.assertFalse(hasattr(auth_routes, "admin_approve_account"))
        self.assertFalse(hasattr(auth_routes, "admin_reject_account"))

    def test_host_switch_account_and_one_click_return_and_remote_login(self):
        # Host admin creates member account directly without prior manual login
        create_req = make_request(
            "POST",
            "/api/admin/accounts",
            host="127.0.0.1:3000",
            client="127.0.0.1",
            body={
                "username": "alice",
                "display_name": "爱丽丝",
                "password": "alicePassword123",
                "permissions": {
                    "collection": True,
                    "reports": True,
                    "payroll": True,
                    "approval": False,
                },
            },
        )
        created = asyncio.run(auth_routes.admin_create_account(create_req))
        self.assertTrue(created["ok"])

        # Host switches to member account via /api/auth/login
        host_switch_res = Response()
        host_switch_req = make_request(
            "POST",
            "/api/auth/login",
            host="127.0.0.1:3000",
            client="127.0.0.1",
            body={"username": "alice", "password": "alicePassword123"},
        )
        switched = asyncio.run(auth_routes.login(host_switch_req, host_switch_res))
        self.assertTrue(switched["authenticated"])
        self.assertEqual(switched["user"]["username"], "alice")
        self.assertTrue(switched["host_machine"])
        self.assertFalse(switched["host_auto_login"])
        self.assertTrue(switched["can_switch_to_host"])
        alice_cookie = extract_session_cookie(host_switch_res)
        self.assertTrue(alice_cookie)

        # Remote LAN client cannot call /api/auth/switch-host (403)
        remote_switch_host = make_request(
            "POST",
            "/api/auth/switch-host",
            host=f"{self.host_lan_ip}:3000",
            client=self.remote_lan_ip,
            cookie=alice_cookie,
            body={},
        )
        with self.assertRaises(HTTPException) as sh_err:
            asyncio.run(auth_routes.switch_to_host_admin(remote_switch_host, Response()))
        self.assertEqual(sh_err.exception.status_code, 403)

        # Host clicks one-click return -> back to built-in host super-admin & old member cookie invalidated
        back_res = Response()
        back_req = make_request(
            "POST",
            "/api/auth/switch-host",
            host="127.0.0.1:3000",
            client="127.0.0.1",
            cookie=alice_cookie,
            body={},
        )
        back = asyncio.run(auth_routes.switch_to_host_admin(back_req, back_res))
        self.assertTrue(back["authenticated"])
        self.assertEqual(back["user"]["role"], "admin")
        self.assertTrue(back["host_auto_login"])
        self.assertFalse(back["can_switch_to_host"])
        self.assertIsNone(self.store.session_user(alice_cookie.split("=", 1)[1]))

        # Non-host LAN client logs in as alice, then logs out cleanly
        remote_login_res = Response()
        remote_login_req = make_request(
            "POST",
            "/api/auth/login",
            host=f"{self.host_lan_ip}:3000",
            client=self.remote_lan_ip,
            body={"username": "alice", "password": "alicePassword123"},
        )
        remote_sess = asyncio.run(auth_routes.login(remote_login_req, remote_login_res))
        self.assertTrue(remote_sess["authenticated"])
        self.assertFalse(remote_sess["host_machine"])
        self.assertFalse(remote_sess["can_switch_to_host"])
        remote_cookie = extract_session_cookie(remote_login_res)

        logout_req = make_request(
            "POST",
            "/api/auth/logout",
            host=f"{self.host_lan_ip}:3000",
            client=self.remote_lan_ip,
            cookie=remote_cookie,
            body={},
        )
        asyncio.run(auth_routes.logout(logout_req, Response()))

        after_logout = auth_routes.get_session(
            make_request(
                "GET",
                "/api/auth/session",
                host=f"{self.host_lan_ip}:3000",
                client=self.remote_lan_ip,
                cookie=remote_cookie,
            ),
            Response(),
        )
        self.assertFalse(after_logout["authenticated"])

    def test_existing_primary_admin_preserved_for_host_auto_login(self):
        existing = self.store.create_user(
            "boss",
            "bossPassword123",
            role="admin",
            display_name="原有管理员",
        )
        sess = auth_routes.get_session(
            make_request("GET", "/api/auth/session", host="127.0.0.1:3000", client="127.0.0.1"),
            Response(),
        )
        self.assertTrue(sess["authenticated"])
        self.assertTrue(sess["host_auto_login"])
        self.assertEqual(sess["user"]["id"], existing["id"])
        self.assertEqual(sess["user"]["display_name"], "原有管理员")
        self.assertTrue(sess["user"]["has_password"])


if __name__ == "__main__":
    unittest.main()
