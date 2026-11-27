"""Tests for centralized Host Admin global config: channel allocation, module pause/resume, and naming."""

import asyncio
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from fastapi import HTTPException
from starlette.requests import Request

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import binding_source_auth as bsa
import download_accounts as accounts
import fengshen_auth
import global_workbench_config as gcfg
import platform_auth_control as pac
import workspace_auth_routes as auth_routes
import workspace_context as wctx
import xiaoxiang_lighthouse


def make_request(
    method: str = "GET",
    path: str = "/api/workbench/global-config",
    *,
    host: str = "192.168.1.2:3000",
    client: str = "192.168.1.60",
    token: str | None = None,
    body: dict | None = None,
) -> Request:
    hdrs = {"host": host}
    if method != "GET":
        hdrs["content-type"] = "application/json"
        hdrs["origin"] = f"http://{host}"
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


class GlobalWorkbenchConfigTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve()
        (self.root / "data").mkdir(parents=True)
        (self.root / "data" / "config.json").write_text("[]", encoding="utf-8")
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
            patch.object(gcfg, "_CONFIG_PATH", self.root / "data" / "workbench_global_config.json"),
            patch.object(gcfg, "_CACHE", None),
            patch.object(bsa, "_DEFAULT_AUTH_ROOT", self.auth_dir),
            patch.object(bsa, "ROOT", self.auth_dir),
            patch.object(xiaoxiang_lighthouse, "_DEFAULT_SESSION_FILE", self.auth_dir / "xiaoxiang_lighthouse.dpapi"),
            patch.object(xiaoxiang_lighthouse, "SESSION_FILE", self.auth_dir / "xiaoxiang_lighthouse.dpapi"),
            patch.dict(os.environ, {"REQUIRE_AUTH_SESSION": "1"}),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)

        self.admin = self.store.create_user("host_admin", "adminPass123", role="admin")
        self.alice = self.store.create_user(
            "alice",
            "alicePass123",
            role="member",
            permissions={
                "collection": True,
                "reports": True,
                "payroll": True,
                "approval": False,
                "fengshen_use": True,
                "lanorange_use": True,
                "lanorange_mdr_use": True,
                "baize_use": True,
                "xiaoxiang_use": True,
                "benlai_use": True,
                "shared_auth_manage": False,
            },
        )
        self.admin_tok = self.store.new_session(self.admin["id"])
        self.alice_tok = self.store.new_session(self.alice["id"])

    def test_dynamic_channel_allocation_affects_session_paths_and_permissions(self):
        # Default: fengshen is personal (per-workspace vault), benlai & xiaoxiang are shared (root vault)
        with wctx.bind_workspace(self.alice["workspace_id"], self.alice):
            self.assertIn(self.alice["workspace_id"], str(fengshen_auth.BROKER.vault.path))
            self.assertEqual(bsa.session_path("benlai"), self.auth_dir / "benlai.dpapi")
            self.assertEqual(
                xiaoxiang_lighthouse.session_file(),
                self.auth_dir / "xiaoxiang_lighthouse.dpapi",
            )

        # Admin assigns fengshen -> shared, benlai & xiaoxiang -> personal
        update_req = make_request(
            "PUT",
            "/api/admin/workbench/global-config",
            token=self.admin_tok,
            body={
                "channel_modes": {
                    "fengshen": "shared",
                    "benlai": "personal",
                    "xiaoxiang": "personal",
                }
            },
        )
        res = asyncio.run(auth_routes.update_workbench_global_config(update_req))
        self.assertTrue(res["ok"])
        self.assertEqual(res["config"]["channel_modes"]["fengshen"], "shared")
        self.assertEqual(res["config"]["channel_modes"]["xiaoxiang"], "personal")

        # Verify path routing flips dynamically!
        with wctx.bind_workspace(self.alice["workspace_id"], self.alice):
            self.assertNotIn(self.alice["workspace_id"], str(fengshen_auth.BROKER.vault.path))
            self.assertIn(self.alice["workspace_id"], str(bsa.session_path("benlai")))
            self.assertIn(self.alice["workspace_id"], str(xiaoxiang_lighthouse.session_file()))

        # Platform status reflects shared=True for fengshen, shared=False & can_manage=True for xiaoxiang!
        alice_fs_req = make_request("GET", "/api/fengshen-downloads/platform-auth/fengshen", token=self.alice_tok)
        with accounts.request_workspace_scope(alice_fs_req):
            fs_st = pac.get_status("fengshen", alice_fs_req)
        self.assertTrue(fs_st["shared"])
        self.assertFalse(fs_st["can_manage"])

        alice_xx_req = make_request("GET", "/api/fengshen-downloads/platform-auth/xiaoxiang", token=self.alice_tok)
        with accounts.request_workspace_scope(alice_xx_req):
            xx_st = pac.get_status("xiaoxiang", alice_xx_req)
        self.assertFalse(xx_st["shared"])
        self.assertTrue(xx_st["can_manage"])

        # Revoking alice's fengshen_use while fengshen is shared -> 403 for alice; personal mode bypasses shared check
        self.store.update_user_access(
            self.alice["id"],
            permissions={**self.alice["permissions"], "fengshen_use": False},
        )
        with self.assertRaises(HTTPException) as err:
            accounts.require_permission(
                make_request("GET", "/api/test", token=self.alice_tok),
                "fengshen_use",
            )
        self.assertEqual(err.exception.status_code, 403)

    def test_module_pause_and_global_naming_and_reset(self):
        # Non-admin cannot mutate global config (403), but can read it (200)
        read_req = make_request("GET", "/api/workbench/global-config", token=self.alice_tok)
        self.assertTrue(auth_routes.get_workbench_global_config(read_req)["ok"])

        forged_update = make_request(
            "PUT",
            "/api/admin/workbench/global-config",
            token=self.alice_tok,
            body={"module_permissions": {"reports": False}},
        )
        with self.assertRaises(HTTPException) as forbidden_err:
            asyncio.run(auth_routes.update_workbench_global_config(forged_update))
        self.assertEqual(forbidden_err.exception.status_code, 403)

        # Admin pauses reports and customizes names & dataset overrides
        upd = asyncio.run(
            auth_routes.update_workbench_global_config(
                make_request(
                    "PUT",
                    "/api/admin/workbench/global-config",
                    token=self.admin_tok,
                    body={
                        "module_permissions": {"reports": False},
                        "module_names": {
                            "groups": {"collection": "原始数据收集"},
                            "items": {"platform:fengshen": "淘宝闪购数据"},
                        },
                        "dataset_overrides": {
                            "delivery_fee": {
                                "title": "配送账单费",
                                "desc": "自定义站点配送费说明",
                            }
                        },
                    },
                )
            )
        )
        self.assertFalse(upd["config"]["module_permissions"]["reports"])
        self.assertEqual(upd["config"]["module_names"]["groups"]["collection"], "原始数据收集")
        self.assertEqual(upd["config"]["module_names"]["items"]["platform:fengshen"], "淘宝闪购数据")
        self.assertEqual(upd["config"]["dataset_overrides"]["delivery_fee"]["title"], "配送账单费")

        # Regular member is blocked on paused 'reports' module (403); admin bypasses pause
        with self.assertRaises(HTTPException) as mod_err:
            accounts.require_permission(
                make_request("GET", "/api/test", token=self.alice_tok),
                "reports",
            )
        self.assertEqual(mod_err.exception.status_code, 403)
        admin_user = accounts.require_permission(
            make_request("GET", "/api/test", token=self.admin_tok),
            "reports",
        )
        self.assertEqual(admin_user["role"], "admin")

        # Partial & full resets restore defaults cleanly
        reset_names = asyncio.run(
            auth_routes.reset_workbench_global_config(
                make_request(
                    "POST",
                    "/api/admin/workbench/global-config/reset",
                    token=self.admin_tok,
                    body={"section": "module_names"},
                )
            )
        )
        self.assertEqual(reset_names["config"]["module_names"], {"groups": {}, "items": {}})
        self.assertFalse(reset_names["config"]["module_permissions"]["reports"])

        reset_all = asyncio.run(
            auth_routes.reset_workbench_global_config(
                make_request(
                    "POST",
                    "/api/admin/workbench/global-config/reset",
                    token=self.admin_tok,
                    body={"section": "all"},
                )
            )
        )
        self.assertEqual(reset_all["config"]["channel_modes"], dict(gcfg.DEFAULT_CHANNEL_MODES))
        self.assertTrue(reset_all["config"]["module_permissions"]["reports"])
        self.assertEqual(reset_all["config"]["dataset_overrides"], {})

    def test_scoped_reset_channels_and_naming_are_independent(self):
        # Customize channels, modules, group/item names, and dataset overrides together
        asyncio.run(
            auth_routes.update_workbench_global_config(
                make_request(
                    "PUT",
                    "/api/admin/workbench/global-config",
                    token=self.admin_tok,
                    body={
                        "channel_modes": {
                            "fengshen": "shared",
                            "xiaoxiang": "personal",
                        },
                        "module_permissions": {"approval": False},
                        "module_names": {
                            "groups": {"collection": "采集中心"},
                            "items": {"platform:fengshen": "闪购采数"},
                        },
                        "dataset_overrides": {
                            "delivery_fee": {
                                "title": "配送账单费",
                                "desc": "自定义副标题",
                            }
                        },
                    },
                )
            )
        )

        # Resetting "naming" clears module_names + dataset_overrides, preserving channels + module pause
        reset_naming = asyncio.run(
            auth_routes.reset_workbench_global_config(
                make_request(
                    "POST",
                    "/api/admin/workbench/global-config/reset",
                    token=self.admin_tok,
                    body={"section": "naming"},
                )
            )
        )
        cfg_after_naming = reset_naming["config"]
        self.assertEqual(cfg_after_naming["module_names"], {"groups": {}, "items": {}})
        self.assertEqual(cfg_after_naming["dataset_overrides"], {})
        self.assertEqual(cfg_after_naming["channel_modes"]["fengshen"], "shared")
        self.assertEqual(cfg_after_naming["channel_modes"]["xiaoxiang"], "personal")
        self.assertFalse(cfg_after_naming["module_permissions"]["approval"])

        # Re-apply custom naming, then reset "channels": naming stays intact while channels/modules reset
        asyncio.run(
            auth_routes.update_workbench_global_config(
                make_request(
                    "PUT",
                    "/api/admin/workbench/global-config",
                    token=self.admin_tok,
                    body={
                        "module_names": {"groups": {"payroll": "发薪核算"}},
                        "dataset_overrides": {"delivery_fee": {"title": "配送费账单"}},
                    },
                )
            )
        )
        reset_channels = asyncio.run(
            auth_routes.reset_workbench_global_config(
                make_request(
                    "POST",
                    "/api/admin/workbench/global-config/reset",
                    token=self.admin_tok,
                    body={"section": "channels"},
                )
            )
        )
        cfg_after_channels = reset_channels["config"]
        self.assertEqual(cfg_after_channels["channel_modes"], dict(gcfg.DEFAULT_CHANNEL_MODES))
        self.assertEqual(
            cfg_after_channels["module_permissions"], dict(gcfg.DEFAULT_MODULE_PERMISSIONS)
        )
        self.assertEqual(cfg_after_channels["module_names"]["groups"]["payroll"], "发薪核算")
        self.assertEqual(
            cfg_after_channels["dataset_overrides"]["delivery_fee"]["title"], "配送费账单"
        )


if __name__ == "__main__":
    unittest.main()
