import contextlib
from pathlib import Path
import sys
import threading
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import fengshen_auth
import parttime_source as source
from collection_errors import CollectionFailure


class CollectionStartupTests(unittest.TestCase):
    def setUp(self):
        api = ModuleType("playwright.sync_api")
        api.sync_playwright = Mock(return_value=contextlib.nullcontext(Mock()))
        self.patches = [
            patch.dict(sys.modules, {"playwright.sync_api": api}),
            patch.object(fengshen_auth.BROKER, "operation", return_value=contextlib.nullcontext()),
            patch.object(fengshen_auth.BROKER, "update"),
            patch.object(fengshen_auth, "launch_background_edge", return_value=Mock()),
            patch.object(fengshen_auth, "open_context", return_value=Mock()),
            patch.object(fengshen_auth, "conceal_edge"),
            patch.object(fengshen_auth, "BrowserAuth", return_value=Mock()),
        ]
        self.mocks = [item.start() for item in self.patches]
        for item in self.patches:
            self.addCleanup(item.stop)
        self.update, self.launch, self.context, self.conceal, self.auth = self.mocks[2:]
        self.logs = []
        self.profiles = [{"dataset": "agency_daily"}, {"dataset": "rider_monthly"}, {}]
        self.plan = SimpleNamespace(start="2026-09-16", end="2026-09-30", month="2026-09", agency_id="31029436")

    def collect(self):
        return source.collect_browser(self.plan, self.profiles, Path("uploads/test/run/raw"),
                                      self.logs.append, threading.Event())

    def test_launch_failure_updates_status_and_preserves_phase(self):
        self.launch.side_effect = RuntimeError("Executable doesn't exist secret-token")
        with self.assertRaises(CollectionFailure) as caught:
            self.collect()
        self.assertEqual(caught.exception.diagnostics["phase"], "browser_launch")
        self.update.assert_called_once_with("error", str(caught.exception))
        self.assertNotIn("secret-token", str(caught.exception))

    def test_rejected_concurrent_operation_does_not_change_other_login(self):
        self.mocks[1].side_effect = fengshen_auth.AuthError("另一项风神登录或采集正在进行，请等待完成")
        with self.assertRaises(CollectionFailure):
            self.collect()
        self.update.assert_not_called()
        self.launch.assert_not_called()

    def test_session_restore_failure_is_not_hidden_by_close_failure(self):
        self.context.side_effect = RuntimeError("storage_state invalid token=private")
        self.launch.return_value.close.side_effect = RuntimeError("closed")
        with self.assertRaises(CollectionFailure) as caught:
            self.collect()
        self.assertEqual(caught.exception.diagnostics["phase"], "session_restore")
        self.assertNotIn("private", str(caught.exception))
        self.assertTrue(any("浏览器关闭" in message for message in self.logs))

    def test_page_and_window_failures_have_distinct_stages(self):
        for stage in ("page_create", "window_conceal"):
            with self.subTest(stage=stage):
                self.context.return_value.new_page.side_effect = RuntimeError("private") if stage == "page_create" else None
                self.conceal.side_effect = RuntimeError("private") if stage == "window_conceal" else None
                with self.assertRaises(CollectionFailure) as caught:
                    self.collect()
                self.assertEqual(caught.exception.diagnostics["phase"], stage)

    def test_navigation_failure_has_dataset_and_safe_reason(self):
        self.auth.return_value.navigate.side_effect = RuntimeError("net::ERR_CONNECTION_RESET https://aeolus.ele.me/?token=private")
        with self.assertRaises(CollectionFailure) as caught:
            self.collect()
        self.assertEqual(caught.exception.diagnostics["phase"], "navigation")
        self.assertEqual(caught.exception.diagnostics["dataset"], "agency_daily")
        self.assertNotIn("private", str(caught.exception))
        self.launch.return_value.close.assert_called_once()

    def test_auth_business_failure_keeps_actionable_message(self):
        self.auth.return_value.ensure.side_effect = fengshen_auth.AuthError("本机会话无法读取，请清除会话后重新登录")
        with self.assertRaises(CollectionFailure) as caught:
            self.collect()
        self.assertEqual(caught.exception.diagnostics["phase"], "auth_check")
        self.assertIn("重新登录", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
