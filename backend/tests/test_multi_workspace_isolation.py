"""End-to-end verification of multi-account workspaces, permissions, and shared/personal platform split."""

import asyncio
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from fastapi import HTTPException, Response
from starlette.requests import Request

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import binding_source_auth as bsa
import download_accounts as accounts
import download_routes
import fengshen_auth
import lanorange_approvals
import platform_auth_control as pac
import workbench
import workspace_auth_routes as auth_routes
import workspace_context as wctx


def make_request(
    method="GET",
    path="/api/test",
    *,
    host="192.168.1.2:3000",
    client="192.168.1.50",
    token=None,
    body=None,
    headers=None,
):
    hdrs = {"host": host, **(headers or {})}
    if method != "GET":
        hdrs.setdefault("content-type", "application/json")
        hdrs.setdefault("origin", f"http://{host}")
    if token:
        hdrs["cookie"] = f"{accounts.COOKIE_NAME}={token}"
    raw = json.dumps(body if body is not None else {}).encode("utf-8")

    async def receive():
        return {"type": "http.request", "body": raw, "more_body": False}

    return Request(
        {
            "type": "http",
            "method": method,
            "scheme": "http",
            "path": path,
            "query_string": b"",
            "client": (client, 54321),
            "server": ("127.0.0.1", 8009),
            "headers": [(k.lower().encode("latin-1"), v.encode("latin-1")) for k, v in hdrs.items()],
        },
        receive,
    )


class MultiWorkspaceIsolationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve()
        (self.root / "data").mkdir(parents=True)
        self.template_rows = [{"城市": "深圳", "团队名称": "南山一站", "团队ID": "1001", "投诉": 50}]
        (self.root / "data" / "config.json").write_text(
            json.dumps(self.template_rows, ensure_ascii=False), encoding="utf-8"
        )
        self.auth_dir = self.root / "backend" / ".local_auth"
        self.auth_dir.mkdir(parents=True)
        self.store = accounts.AccountStore(self.root / "backend" / ".local_downloads" / "accounts.sqlite3")

        patches = [
            patch.object(accounts, "PASSWORD_ITERATIONS", 1000),
            patch.object(accounts, "get_account_store", return_value=self.store),
            patch.object(auth_routes, "get_account_store", return_value=self.store),
            patch.object(auth_routes, "PROJECT_ROOT", self.root),
            patch.object(wctx, "PROJECT_ROOT", self.root),
            patch.object(wctx, "LOCAL_AUTH_ROOT", self.auth_dir),
            patch.object(bsa, "_DEFAULT_AUTH_ROOT", self.auth_dir),
            patch.object(bsa, "ROOT", self.auth_dir),
            patch.object(workbench, "ROOT", self.root),
            patch.dict(os.environ, {"REQUIRE_AUTH_SESSION": "1"}),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)

    def test_bootstrap_registration_approval_and_config_isolation(self):
        # 1. Remote LAN client cannot bootstrap host admin
        remote_req = make_request(
            "POST",
            "/api/auth/bootstrap",
            client="192.168.1.88",
            body={"username": "hacker", "password": "password123"},
        )
        with self.assertRaises(HTTPException) as ctx:
            asyncio.run(auth_routes.bootstrap_admin(remote_req, Response()))
        self.assertEqual(ctx.exception.status_code, 403)

        # 2. Host loopback client bootstraps primary admin -> inherits download_shared & existing config.json
        host_req = make_request(
            "POST",
            "/api/auth/bootstrap",
            host="127.0.0.1:3000",
            client="127.0.0.1",
            body={"username": "hostadmin", "display_name": "主机管理员", "password": "adminPassword123"},
        )
        host_res = Response()
        boot = asyncio.run(auth_routes.bootstrap_admin(host_req, host_res))
        self.assertTrue(boot["authenticated"])
        self.assertEqual(boot["user"]["workspace_id"], "download_shared")
        admin_token = self.store.new_session(boot["user"]["id"])

        # 3. Public self-registration is enabled by default (creates pending account awaiting admin approval)
        reg_req = make_request(
            "POST",
            "/api/auth/register",
            body={"username": "lisi", "display_name": "李四", "password": "lisiPassword123", "note": "深圳核算"},
        )
        reg = asyncio.run(auth_routes.register(reg_req))
        self.assertEqual(reg["status"], "pending")
        self.assertEqual(self.store.pending_count(), 1)

        # Explicitly disabling via ALLOW_SELF_REGISTRATION=0 blocks new public registrations with 403
        with patch.dict(os.environ, {"ALLOW_SELF_REGISTRATION": "0"}):
            blocked_reg_req = make_request(
                "POST",
                "/api/auth/register",
                body={"username": "wangwu", "display_name": "王五", "password": "wangwuPassword123"},
            )
            with self.assertRaises(HTTPException) as reg_err:
                asyncio.run(auth_routes.register(blocked_reg_req))
            self.assertEqual(reg_err.exception.status_code, 403)

        login_pending_req = make_request(
            "POST",
            "/api/auth/login",
            body={"username": "lisi", "password": "lisiPassword123"},
        )
        with self.assertRaises(HTTPException) as pending_err:
            asyncio.run(auth_routes.login(login_pending_req, Response()))
        self.assertEqual(pending_err.exception.status_code, 403)

        # 4. Admin approves Lisi as payroll_specialist (payroll=True, approval=False, shared_auth_manage=False)
        lisi_id = next(u["id"] for u in self.store.users() if u["username"] == "lisi")
        approve_req = make_request(
            "POST",
            f"/api/admin/accounts/{lisi_id}/approve",
            token=admin_token,
            body={"role_template": "payroll_specialist"},
        )
        approved = asyncio.run(auth_routes.admin_approve_account(lisi_id, approve_req))
        lisi_wid = approved["user"]["workspace_id"]
        self.assertTrue(lisi_wid.startswith("ws_"))

        # Verify Lisi's workspace received an independent copy of default config.json
        lisi_cfg_path = self.root / "workspaces" / lisi_wid / "data" / "config.json"
        self.assertTrue(lisi_cfg_path.is_file())
        self.assertEqual(json.loads(lisi_cfg_path.read_text("utf-8")), self.template_rows)

        # 5. Lisi logs in and modifies her own deduction config -> Admin's config remains unchanged!
        lisi_token = self.store.new_session(lisi_id)
        lisi_get_req = make_request("GET", "/api/workbench/deductions", token=lisi_token)
        current_cfg = workbench.get_defaults(lisi_get_req)
        new_rows = [{"城市": "深圳", "团队名称": "南山一站", "团队ID": "1001", "投诉": 999}]
        lisi_save_req = make_request(
            "PUT",
            "/api/workbench/deductions",
            token=lisi_token,
            body={"rows": new_rows, "version": current_cfg["version"]},
        )
        asyncio.run(workbench.save_defaults(lisi_save_req))

        # Check Lisi's config is 999 while Admin's root config is still 50!
        self.assertEqual(json.loads(lisi_cfg_path.read_text("utf-8"))[0]["投诉"], 999)
        self.assertEqual(json.loads((self.root / "data" / "config.json").read_text("utf-8"))[0]["投诉"], 50)

        # 6. Spoofing x-workspace-id header cannot escape Lisi's workspace
        spoof_req = make_request(
            "GET",
            "/api/fengshen-downloads/runs",
            token=lisi_token,
            headers={"x-workspace-id": "download_shared"},
        )
        self.assertEqual(download_routes.workspace_owner(spoof_req), lisi_wid)

        # 7. Permission enforcement: Lisi lacks 'approval' permission -> 403 on Lanorange approval scope
        with self.assertRaises(HTTPException) as perm_err:
            lanorange_approvals.scope(make_request("GET", "/api/lanorange/pending", token=lisi_token))
        self.assertEqual(perm_err.exception.status_code, 403)

        # 8. Admin cross-workspace inspection -> switches into Lisi's workspace and sees 999, then exits back to 50
        inspect_req = make_request(
            "POST",
            "/api/auth/inspect",
            token=admin_token,
            body={"workspace_id": lisi_wid},
        )
        inspected = asyncio.run(auth_routes.switch_inspect_workspace(inspect_req))
        self.assertTrue(inspected["user"]["inspecting"])
        self.assertEqual(inspected["user"]["effective_workspace"], lisi_wid)

        admin_inspect_cfg = workbench.get_defaults(make_request("GET", "/api/workbench/deductions", token=admin_token))
        self.assertEqual(admin_inspect_cfg["rows"][0]["投诉"], 999)

        exit_req = make_request("POST", "/api/auth/inspect", token=admin_token, body={"workspace_id": ""})
        exited = asyncio.run(auth_routes.switch_inspect_workspace(exit_req))
        self.assertFalse(exited["user"]["inspecting"])
        self.assertEqual(exited["user"]["effective_workspace"], "download_shared")
        admin_own_cfg = workbench.get_defaults(make_request("GET", "/api/workbench/deductions", token=admin_token))
        self.assertEqual(admin_own_cfg["rows"][0]["投诉"], 50)

    def test_shared_xiaoxiang_benlai_vs_isolated_personal_platforms(self):
        admin = self.store.create_user("admin", "adminPass123", role="admin", bootstrap=True)
        alice = self.store.create_user("alice", "alicePass123", role="member", role_template="payroll_specialist")
        bob = self.store.create_user("bob", "bobPass123", role="member", role_template="ops_specialist")

        admin_tok = self.store.new_session(admin["id"])
        alice_tok = self.store.new_session(alice["id"])

        # Personal platforms (fengshen, lanorange, baize) resolve distinct per-workspace paths & brokers!
        with wctx.bind_workspace(alice["workspace_id"], alice):
            alice_fs = fengshen_auth.BROKER.vault.path
            alice_lo = bsa.session_path("lanorange")
            alice_bz = bsa.session_path("baize")
            alice_bl = bsa.session_path("benlai")

        with wctx.bind_workspace(bob["workspace_id"], bob):
            bob_fs = fengshen_auth.BROKER.vault.path
            bob_lo = bsa.session_path("lanorange")
            bob_bz = bsa.session_path("baize")
            bob_bl = bsa.session_path("benlai")

        self.assertNotEqual(alice_fs, bob_fs)
        self.assertNotEqual(alice_lo, bob_lo)
        self.assertNotEqual(alice_bz, bob_bz)
        # Benlai is shared globally!
        self.assertEqual(alice_bl, bob_bl)
        self.assertEqual(alice_bl, self.auth_dir / "benlai.dpapi")

        # Regular member Alice CANNOT start/disconnect shared Xiaoxiang or shared Benlai
        for shared_src in ("xiaoxiang", "benlai"):
            st_req = make_request("GET", f"/api/fengshen-downloads/platform-auth/{shared_src}", token=alice_tok)
            with accounts.request_workspace_scope(st_req):
                st = pac.get_status(shared_src, st_req)
            self.assertTrue(st["shared"])
            self.assertFalse(st["can_manage"])

            start_req = make_request("POST", f"/api/fengshen-downloads/source-auth/{shared_src}/start", token=alice_tok, body={})
            with self.assertRaises(HTTPException) as err:
                bsa.start(shared_src, start_req)
            self.assertEqual(err.exception.status_code, 403)

            disc_req = make_request(
                "POST",
                f"/api/fengshen-downloads/platform-auth/{shared_src}/disconnect",
                token=alice_tok,
                body={"confirm": True, "session_version": "x"},
            )
            with self.assertRaises(HTTPException) as err2:
                asyncio.run(pac.do_disconnect(shared_src, disc_req))
            self.assertEqual(err2.exception.status_code, 403)

        # Admin has can_manage=True on both shared Xiaoxiang and shared Benlai
        for shared_src in ("xiaoxiang", "benlai"):
            adm_req = make_request("GET", f"/api/fengshen-downloads/platform-auth/{shared_src}", token=admin_tok)
            with accounts.request_workspace_scope(adm_req):
                adm_st = pac.get_status(shared_src, adm_req)
            self.assertTrue(adm_st["shared"])
            self.assertTrue(adm_st["can_manage"])

    def test_iframe_cookie_requires_authenticated_proxy_https_header(self):
        with patch.dict(os.environ, {"FENGSHEN_DOWNLOAD_PROXY_SECRET": "test-proxy-secret"}):
            # Forged header without valid proxy secret -> stays plain HTTP SameSite=Lax
            forged_req = make_request(
                "POST",
                "/api/auth/login",
                host="localhost:3000",
                client="127.0.0.1",
                headers={"x-download-proxy-https": "1"},
            )
            forged_res = Response()
            auth_routes._set_session_cookie(forged_res, forged_req, "tok-1")
            forged_cookie = forged_res.headers.get("set-cookie", "").lower()
            self.assertIn("samesite=lax", forged_cookie)
            self.assertNotIn("partitioned", forged_cookie)

            # Valid loopback proxy secret + x-download-proxy-https: 1 -> Secure + SameSite=None + Partitioned
            trusted_req = make_request(
                "POST",
                "/api/auth/login",
                host="localhost:3000",
                client="127.0.0.1",
                headers={
                    "x-download-proxy-secret": "test-proxy-secret",
                    "x-download-client-address": "127.0.0.1",
                    "x-download-proxy-https": "1",
                },
            )
            trusted_res = Response()
            auth_routes._set_session_cookie(trusted_res, trusted_req, "tok-2")
            trusted_cookie = trusted_res.headers.get("set-cookie", "").lower()
            self.assertIn("samesite=none", trusted_cookie)
            self.assertIn("secure", trusted_cookie)
            self.assertIn("httponly", trusted_cookie)
            self.assertIn("partitioned", trusted_cookie)

            clear_res = Response()
            auth_routes._clear_session_cookie(clear_res, trusted_req)
            clear_cookie = clear_res.headers.get("set-cookie", "").lower()
            self.assertIn("samesite=none", clear_cookie)
            self.assertIn("secure", clear_cookie)
            self.assertIn("partitioned", clear_cookie)

    def test_public_registration_rate_limit_and_lan_pending_approval(self):
        # Remote LAN client cannot initialize host admin (403)
        remote_boot_req = make_request(
            "POST",
            "/api/auth/bootstrap",
            host="192.168.1.10:3000",
            client="192.168.1.55",
            body={"username": "host_admin", "display_name": "主机管理员", "password": "StrongAdminPassword1!"},
        )
        with self.assertRaises(HTTPException) as remote_boot_err:
            asyncio.run(auth_routes.bootstrap_admin(remote_boot_req, Response()))
        self.assertEqual(remote_boot_err.exception.status_code, 403)

        # Host machine (loopback) can initialize host admin
        boot_req = make_request(
            "POST",
            "/api/auth/bootstrap",
            host="127.0.0.1:3000",
            client="127.0.0.1",
            body={"username": "host_admin", "display_name": "主机管理员", "password": "StrongAdminPassword1!"},
        )
        boot = asyncio.run(auth_routes.bootstrap_admin(boot_req, Response()))
        self.assertTrue(boot["self_registration_enabled"])
        self.assertTrue(self.store.initialized())

        # LAN client can submit public registration and receives pending status; rate limit enforces ceiling
        with patch.dict(os.environ, {"REGISTER_RATE_LIMIT": "2"}):
            for idx in range(2):
                lan_req = make_request(
                    "POST",
                    "/api/auth/register",
                    host="192.168.1.10:3000",
                    client="192.168.1.55",
                    body={"username": f"lan_user_{idx}", "display_name": f"局域网成员{idx}", "password": "LanUser123456"},
                )
                res = asyncio.run(auth_routes.register(lan_req))
                self.assertEqual(res["status"], "pending")

            # 3rd registration from same LAN IP within window hits 429 rate limit
            throttled_req = make_request(
                "POST",
                "/api/auth/register",
                host="192.168.1.10:3000",
                client="192.168.1.55",
                body={"username": "lan_user_2", "display_name": "局域网成员2", "password": "LanUser123456"},
            )
            with self.assertRaises(HTTPException) as limit_err:
                asyncio.run(auth_routes.register(throttled_req))
            self.assertEqual(limit_err.exception.status_code, 429)
            self.assertEqual(self.store.pending_count(), 2)

    def test_admin_self_reset_preserves_caller_session(self):
        admin = self.store.create_user("admin", "adminPass123", role="admin", bootstrap=True)
        tok_current = self.store.new_session(admin["id"])
        tok_other = self.store.new_session(admin["id"])

        req = make_request(
            "POST",
            f"/api/admin/accounts/{admin['id']}/reset-password",
            token=tok_current,
            body={"new_password": "newAdminPass456"},
        )
        res = asyncio.run(auth_routes.admin_reset_password(admin["id"], req))
        self.assertTrue(res["ok"])
        self.assertIsNotNone(self.store.session_user(tok_current))
        self.assertIsNone(self.store.session_user(tok_other))


if __name__ == "__main__":
    unittest.main()
