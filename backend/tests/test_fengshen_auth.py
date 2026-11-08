import asyncio
import base64
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import fengshen_auth as auth
import fengshen_auth_routes as routes
from fengshen_bill import BILL_URL, BillPageCollector, BillRequest
from test_fengshen_bill import FakePage, daily_profile


STATE = {"cookies": [{"name": "session", "value": "synthetic-secret", "domain": ".ele.me",
                      "path": "/", "expires": -1, "httpOnly": True, "secure": True, "sameSite": "Lax"}], "origins": []}


def fake_crypt(data, decrypt=False):
    return base64.b64decode(data) if decrypt else base64.b64encode(data)


class Fixture(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=Path(__file__).parent)
        self.root = Path(self.temp.name)
        self.now = 0
        self.vault = auth.SessionVault(self.root / "session.dpapi", crypt=fake_crypt)
        self.broker = auth.AuthBroker(self.vault, clock=lambda: self.now)
        self.cancelled = threading.Event()

    def tearDown(self):
        self.temp.cleanup()

    def challenge(self):
        return self.broker.status("tester")["challenge_id"]


class VaultTests(Fixture):
    def test_roundtrip_and_restart_never_plaintext(self):
        self.vault.save(STATE)
        self.assertNotIn(b"synthetic-secret", self.vault.path.read_bytes())
        restarted = auth.SessionVault(self.vault.path, fake_crypt)
        self.assertEqual(restarted.load(), STATE)
        self.assertEqual(list(self.root.iterdir()), [self.vault.path])

    @unittest.skipUnless(os.name == "nt", "DPAPI is Windows-specific")
    def test_real_user_bound_dpapi_and_tamper_rejected(self):
        vault = auth.SessionVault(self.root / "real.dpapi")
        vault.save(STATE)
        self.assertNotIn(b"synthetic-secret", vault.path.read_bytes())
        self.assertEqual(auth.SessionVault(vault.path).load(), STATE)
        encrypted = bytearray(vault.path.read_bytes())
        encrypted[-1] ^= 1
        vault.path.write_bytes(encrypted)
        with self.assertRaises(auth.AuthError):
            vault.load()

    def test_encryption_failure_never_writes_plaintext(self):
        vault = auth.SessionVault(self.root / "failed", crypt=lambda _: (_ for _ in ()).throw(auth.AuthError("fail")))
        with self.assertRaises(auth.AuthError):
            vault.save(STATE)
        self.assertFalse(vault.path.exists())

    def test_corrupt_state_requires_login(self):
        self.vault.path.write_bytes(b"corrupt")
        with self.assertRaisesRegex(auth.AuthError, "重新登录"):
            self.vault.load()

    def test_unrelated_domains_are_not_saved(self):
        state = {"cookies": STATE["cookies"] + [{"domain": "evil-ele.me"}, {"domain": ".example.com"}],
                 "origins": [{"origin": "https://freyja.ele.me", "localStorage": []},
                             {"origin": "https://ele.me.evil.com", "localStorage": []}]}
        filtered = auth.safe_state(state)
        self.assertEqual(filtered["cookies"], STATE["cookies"])
        self.assertEqual(len(filtered["origins"]), 1)


class BrokerTests(Fixture):
    def test_saved_state_is_not_claimed_authenticated_after_restart(self):
        self.vault.save(STATE)
        self.assertEqual(auth.AuthBroker(self.vault).status("tester")["state"], "saved")

    def test_no_sms_is_sent_on_expiry_detection(self):
        with self.broker.operation("tester", self.cancelled):
            self.broker.update("login_required", "expired")
            self.assertTrue(self.broker.commands.empty())
            self.assertEqual(self.broker.send_count, 0)

    def test_owner_nonce_and_concurrency(self):
        with self.broker.operation("tester", self.cancelled):
            self.broker.update("login_required", "expired")
            self.assertIsNone(self.broker.status("other")["challenge_id"])
            for owner, challenge in (("other", self.challenge()), ("tester", "wrong")):
                with self.assertRaises(auth.AuthError):
                    self.broker.submit(owner, challenge, "send", "13800138000")
            with self.assertRaises(auth.AuthError), self.broker.operation("other", threading.Event()):
                pass

    def test_cooldown_and_max_send_count(self):
        with self.broker.operation("tester", self.cancelled):
            for attempt in range(3):
                self.broker.update("login_required", "expired")
                self.broker.submit("tester", self.challenge(), "send", "13800138000")
                action, value, future = self.broker.commands.get_nowait()
                self.assertEqual((action, value), ("send", "13800138000"))
                future.set_result({"ok": True})
                self.broker.update("sms_sent", "sent")
                with self.assertRaises(auth.AuthError):
                    self.broker.submit("tester", self.challenge(), "send", "13800138000")
                self.now += 61
            self.assertFalse(self.broker.status("tester")["can_send"])

    def test_verify_requires_send_and_has_attempt_limit(self):
        with self.broker.operation("tester", self.cancelled):
            self.broker.update("login_required", "expired")
            with self.assertRaises(auth.AuthError):
                self.broker.submit("tester", self.challenge(), "verify", "123456")
            for _ in range(5):
                self.broker.update("sms_sent", "sent")
                self.broker.submit("tester", self.challenge(), "verify", "123456")
                self.broker.commands.get_nowait()[2].set_result({"ok": False})
            self.broker.update("sms_sent", "sent")
            self.assertFalse(self.broker.status("tester")["can_verify"])

    def test_clear_cancels_task_and_prevents_resaving(self):
        with self.broker.operation("tester", self.cancelled):
            self.broker.save(STATE)
            self.broker.clear()
            self.assertTrue(self.cancelled.is_set())
            self.assertFalse(self.vault.path.exists())
            with self.assertRaises(auth.AuthError):
                self.broker.save(STATE)

    def test_pending_commands_are_released_on_close(self):
        with self.broker.operation("tester", self.cancelled):
            self.broker.update("login_required", "expired")
            future = self.broker.submit("tester", self.challenge(), "send", "13800138000")
        with self.assertRaises(auth.AuthError):
            future.result()
        self.assertFalse(self.broker.status("tester")["busy"])

    def test_status_does_not_expose_phone_or_cookie(self):
        with self.broker.operation("tester", self.cancelled):
            self.broker.update("login_required", "expired")
            self.broker.submit("tester", self.challenge(), "send", "13800138000")
            serialized = json.dumps(self.broker.status("tester"))
            self.assertNotIn("13800138000", serialized)
            self.assertNotIn("synthetic-secret", serialized)


class Locator:
    def __init__(self, page, kind):
        self.page, self.kind = page, kind

    def count(self):
        if self.kind == "header" and self.page.header_as_value:
            return 0
        return 1

    def nth(self, _):
        return self

    def is_visible(self):
        return self.page.logged_in if self.kind.startswith("header") else not self.page.logged_in

    def get_attribute(self, _, **kwargs):
        return None

    def inner_text(self, **kwargs):
        return "[31029436][泉州] 测试合作商" if self.kind.startswith("header") else ""

    def evaluate(self, _):
        return self.inner_text()

    def fill(self, value):
        self.page.values[self.kind] = value

    def click(self):
        if self.kind == "send":
            self.page.sends += 1
        if self.kind == "login" and self.page.values.get("code") == "123456":
            self.page.logged_in = True
            self.page.url = BILL_URL
            self.page.emit("framenavigated", self.page.main_frame)


class AuthPage:
    def __init__(self, logged_in=False):
        self.url = BILL_URL if logged_in else "https://mozi-login.alibaba-inc.com/"
        self.logged_in, self.closed = logged_in, False
        self.frames, self.values, self.sends, self.now = [], {}, 0, 0
        self.tick = lambda: None
        self.listeners = {}
        self.main_frame = self
        self.header_as_value = False
        self.navigations = []

    def on(self, event, listener):
        self.listeners.setdefault(event, []).append(listener)

    def emit(self, event, value):
        for listener in self.listeners.get(event, []):
            listener(value)

    def is_closed(self):
        return self.closed

    def goto(self, url, **kwargs):
        self.navigations.append(url)
        self.url = url
        if "mozi-login" in url:
            self.logged_in = False
        self.emit("framenavigated", self.main_frame)

    def locator(self, selector):
        kind = ("phone" if 'type="tel"' in selector else "code" if 'maxlength="6"' in selector
                else "header_value" if "input[readonly]" in selector else "header")
        return Locator(self, kind)

    def get_by_text(self, pattern):
        kind = "send" if "获取验证码" in pattern.pattern else "tab" if "短信登录" in pattern.pattern else "header"
        return Locator(self, kind)

    def get_by_role(self, *args, **kwargs):
        return Locator(self, "login")

    def wait_for_timeout(self, ms):
        self.now += ms / 1000
        self.tick()


class BrowserAuthTests(Fixture):
    def driver(self, page, timeout=60, pages=None, replace_closed_page=False):
        self.context = SimpleNamespace(storage_state=lambda: STATE, pages=pages or [page], on=lambda *args: None)
        return auth.BrowserAuth(page, self.context, self.broker, self.cancelled, timeout=timeout,
                                replace_closed_page=replace_closed_page)

    def test_valid_session_reuses_without_sms(self):
        page = AuthPage(True)
        with self.broker.operation("tester", self.cancelled):
            driver = self.driver(page)
            driver.reveal = Mock()
            driver.conceal = Mock()
            self.assertFalse(driver.ensure(BILL_URL))
            driver.reveal.assert_not_called()
            driver.conceal.assert_not_called()
            self.assertEqual(self.vault.load(), STATE)
            self.assertEqual(page.sends, 0)

    def test_expired_session_reveals_once_and_resumes_in_background_without_sms(self):
        page = AuthPage()
        def tick():
            page.logged_in = True
            page.url = BILL_URL
        page.tick = tick
        with self.broker.operation("tester", self.cancelled):
            driver = self.driver(page)
            driver.reveal = Mock()
            driver.conceal = Mock()
            self.assertTrue(driver.ensure(BILL_URL))
            driver.reveal.assert_called_once_with(page)
            driver.conceal.assert_called_once_with(page)
            self.assertEqual(page.sends, 0)
            self.assertEqual(self.vault.load(), STATE)

    def test_401_is_expiry_but_403_is_not(self):
        driver = self.driver(AuthPage(True))
        for status, expired in ((403, False), (500, False), (401, True)):
            driver.response(SimpleNamespace(url="https://httpizza.ele.me/test", status=status,
                                            request=SimpleNamespace(resource_type="xhr")))
            self.assertEqual(driver.expired(), expired)

    def test_200_login_rejection_is_expiry_not_permission_error(self):
        driver = self.driver(AuthPage(True))
        for message, expired in (("无权限", False), ("登录已失效", True)):
            driver.response(SimpleNamespace(url="https://httpizza.ele.me/test", status=200,
                request=SimpleNamespace(resource_type="xhr"),
                json=lambda message=message: {"success": False, "message": message}))
            self.assertEqual(driver.expired(), expired)

    def test_network_or_unknown_page_does_not_send_sms(self):
        page = AuthPage(True)
        page.logged_in = False
        with self.broker.operation("tester", self.cancelled), patch("fengshen_auth.time.monotonic", side_effect=lambda: page.now):
            with self.assertRaisesRegex(auth.AuthError, "未触发短信"):
                self.driver(page).ensure(BILL_URL)
            self.assertEqual(page.sends, 0)
            self.assertFalse(self.vault.path.exists())

    def test_expiry_manual_send_verify_saves_and_resumes(self):
        page = AuthPage()
        futures = []
        sent = verified = False
        def tick():
            nonlocal sent, verified
            status = self.broker.status("tester")
            if status["can_send"] and not sent:
                sent = True
                futures.append(self.broker.submit("tester", self.challenge(), "send", "13800138000"))
            elif status["can_verify"] and not verified:
                verified = True
                futures.append(self.broker.submit("tester", self.challenge(), "verify", "123456"))
        page.tick = tick
        with self.broker.operation("tester", self.cancelled), patch("fengshen_auth.time.monotonic", side_effect=lambda: page.now):
            self.assertTrue(self.driver(page).ensure(BILL_URL))
            self.assertEqual(page.sends, 1)
            self.assertTrue(all(f.result()["ok"] for f in futures))
            self.assertEqual(self.vault.load(), STATE)

    def test_wrong_code_never_saves_or_resumes(self):
        page = AuthPage()
        future = None
        sent = False
        def tick():
            nonlocal sent, future
            status = self.broker.status("tester")
            if status["can_send"] and not sent:
                sent = True
                self.broker.submit("tester", self.challenge(), "send", "13800138000")
            elif status["can_verify"] and future is None:
                future = self.broker.submit("tester", self.challenge(), "verify", "000000")
            if future and future.done():
                self.cancelled.set()
        page.tick = tick
        with self.broker.operation("tester", self.cancelled), patch("fengshen_auth.time.monotonic", side_effect=lambda: page.now):
            with self.assertRaises(auth.AuthError):
                self.driver(page).ensure(BILL_URL)
            self.assertFalse(future.result()["ok"])
            self.assertFalse(self.vault.path.exists())

    def test_user_closes_browser_stops(self):
        page = AuthPage()
        page.closed = True
        with self.broker.operation("tester", self.cancelled):
            with self.assertRaisesRegex(auth.AuthError, "浏览器已关闭"):
                self.driver(page).ensure(BILL_URL)

    def test_visible_login_frame_means_expired(self):
        page = AuthPage(True)
        page.frames = [SimpleNamespace(url="https://mozi-login.alibaba-inc.com/",
                                      frame_element=lambda: SimpleNamespace(is_visible=lambda: True))]
        self.assertTrue(self.driver(page).expired())

    def test_hidden_stale_login_frame_does_not_block_success(self):
        page = AuthPage(True)
        page.frames = [SimpleNamespace(url="https://mozi-login.alibaba-inc.com/",
                                      frame_element=lambda: SimpleNamespace(is_visible=lambda: False))]
        with self.broker.operation("tester", self.cancelled):
            self.assertFalse(self.driver(page).ensure(BILL_URL))
            self.assertTrue(self.vault.path.exists())

    def test_dashboard_login_is_saved_without_requiring_report_permission(self):
        page = AuthPage(True)
        page.url = "https://aeolus.ele.me/?targetId=51388#/app/dashboard/index.html"
        with self.broker.operation("tester", self.cancelled):
            self.assertFalse(self.driver(page).ensure(BILL_URL))
            self.assertEqual(page.navigations, [])
            self.assertEqual(self.vault.load(), STATE)

    def test_value_only_merchant_header_is_recognized(self):
        page = AuthPage(True)
        page.header_as_value = True
        with self.broker.operation("tester", self.cancelled):
            self.assertFalse(self.driver(page).ensure(BILL_URL))
            self.assertTrue(self.vault.path.exists())

    def test_url_without_gated_header_is_not_authenticated(self):
        page = AuthPage(True)
        page.logged_in = False
        self.assertFalse(self.driver(page).ready(BILL_URL))
        self.assertFalse(self.vault.path.exists())

    def test_authenticated_new_tab_in_same_context_is_saved_without_sms(self):
        original, popup = AuthPage(), AuthPage(True)
        popup.url = "https://aeolus.ele.me/#/app/dashboard/index.html"
        with self.broker.operation("tester", self.cancelled):
            self.assertFalse(self.driver(original, pages=[original, popup]).ensure(BILL_URL))
            self.assertEqual(original.sends, 0)
            self.assertTrue(self.vault.path.exists())

    def test_untrusted_or_closed_popup_is_not_login_proof(self):
        original, popup = AuthPage(), AuthPage(True)
        popup.url = "https://aeolus.ele.me.evil.example/#/bill/download"
        driver = self.driver(original, pages=[original, popup])
        self.assertFalse(driver.ready(BILL_URL))
        popup.url = BILL_URL
        popup.closed = True
        self.assertFalse(driver.ready(BILL_URL))

    def test_standalone_can_use_popup_when_original_login_tab_closes(self):
        original, popup = AuthPage(), AuthPage(True)
        original.closed = True
        with self.broker.operation("tester", self.cancelled):
            driver = self.driver(original, pages=[original, popup], replace_closed_page=True)
            self.assertFalse(driver.ensure(BILL_URL))
            self.assertIs(driver.page, popup)
            self.assertTrue(self.vault.path.exists())

    def test_login_tab_closing_during_wait_switches_to_live_popup(self):
        original, popup = AuthPage(), AuthPage(True)
        driver = self.driver(original, pages=[original, popup], replace_closed_page=True)
        def close_during_wait(_):
            original.closed = True
            raise RuntimeError("Target page, context or browser has been closed")
        original.wait_for_timeout = close_during_wait
        driver.wait(200)
        self.assertIs(driver.page, popup)

    def test_whole_browser_closing_during_wait_gives_explicit_message(self):
        page = AuthPage()
        driver = self.driver(page, replace_closed_page=True)
        def close_during_wait(_):
            page.closed = True
            raise RuntimeError("Target page, context or browser has been closed")
        page.wait_for_timeout = close_during_wait
        with self.assertRaisesRegex(auth.AuthError, "浏览器已关闭"):
            driver.wait(200)
        self.assertFalse(self.vault.path.exists())

    def test_delayed_401_from_before_navigation_is_ignored_but_current_401_blocks(self):
        page = AuthPage(True)
        driver = self.driver(page)
        request = SimpleNamespace(url="https://httpizza.ele.me/test", resource_type="xhr")
        page.emit("request", request)
        page.emit("framenavigated", page.main_frame)
        driver.response(SimpleNamespace(url=request.url, status=401, request=request))
        self.assertFalse(driver.expired())
        page.emit("request", request)
        driver.response(SimpleNamespace(url=request.url, status=401, request=request))
        self.assertTrue(driver.expired())
        self.assertFalse(driver.ready(BILL_URL))

    def test_transient_redirect_then_real_dashboard_login_is_not_missed(self):
        page = AuthPage()
        def tick():
            if page.now < 1:
                page.url = "https://aeolus.ele.me/#/dashboard"
            elif page.now < 2:
                page.url = "https://mozi-login.alibaba-inc.com/"
            else:
                page.logged_in = True
                page.url = "https://aeolus.ele.me/#/app/dashboard/index.html"
        page.tick = tick
        with self.broker.operation("tester", self.cancelled), patch("fengshen_auth.time.monotonic", side_effect=lambda: page.now):
            self.assertTrue(self.driver(page).ensure(BILL_URL))
            self.assertTrue(self.vault.path.exists())
            self.assertEqual(page.sends, 0)

    def test_collector_restores_original_report_after_new_tab_login(self):
        original, popup = AuthPage(), AuthPage(True)
        popup.url = "https://aeolus.ele.me/#/dashboard"
        original.goto = lambda url, **kwargs: (setattr(original, "url", url), setattr(original, "logged_in", True))
        with self.broker.operation("tester", self.cancelled):
            driver = self.driver(original, pages=[original, popup])
            self.assertFalse(driver.ensure(BILL_URL, {"agency_context": "#context"}))
            self.assertEqual(original.url, BILL_URL)
            self.assertTrue(driver.ready(BILL_URL, {"agency_context": "#context"}))

    def test_recheck_does_not_send_sms_or_increment_verify_attempts(self):
        page = AuthPage()
        future = None
        def tick():
            nonlocal future
            if self.broker.status("tester")["can_recheck"] and future is None:
                future = self.broker.submit("tester", self.challenge(), "recheck")
            if page.now >= 1:
                page.logged_in = True
                page.url = "https://aeolus.ele.me/#/dashboard"
        page.tick = tick
        with self.broker.operation("tester", self.cancelled), patch("fengshen_auth.time.monotonic", side_effect=lambda: page.now):
            self.assertTrue(self.driver(page).ensure(BILL_URL))
            self.assertTrue(future.result()["ok"])
            self.assertEqual((page.sends, self.broker.send_count, self.broker.verify_count), (0, 0, 0))

    def test_recheck_failure_stays_waiting_without_claiming_bad_code(self):
        page = AuthPage()
        future = None
        def tick():
            nonlocal future
            if self.broker.status("tester")["can_recheck"] and future is None:
                future = self.broker.submit("tester", self.challenge(), "recheck")
            if future and future.done():
                self.cancelled.set()
        page.tick = tick
        with self.broker.operation("tester", self.cancelled), patch("fengshen_auth.time.monotonic", side_effect=lambda: page.now):
            with self.assertRaises(auth.AuthError):
                self.driver(page).ensure(BILL_URL)
            self.assertFalse(future.result()["ok"])
            self.assertIn("合作商页面", future.result()["message"])
            self.assertFalse(self.vault.path.exists())
            self.assertEqual(page.sends, 0)

    def test_redirect_replacing_document_is_not_success(self):
        page = AuthPage(True)
        page.get_by_text = lambda *args: SimpleNamespace(count=lambda: (_ for _ in ()).throw(RuntimeError("document replaced")))
        self.assertFalse(self.driver(page).ready(BILL_URL))
        self.assertFalse(self.vault.path.exists())

    def test_certificate_error_is_not_ignored(self):
        page = AuthPage(True)
        page.goto = lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("net::ERR_CERT_AUTHORITY_INVALID"))
        with self.assertRaises(RuntimeError):
            self.driver(page).navigate(BILL_URL)

    def test_repeated_login_cycles_are_bounded(self):
        driver = self.driver(AuthPage())
        driver.login_attempts = 3
        with self.assertRaisesRegex(auth.AuthError, "反复失效"):
            driver.login(BILL_URL)


class EdgeWindowTests(unittest.TestCase):
    def test_launch_is_headed_but_starts_minimized(self):
        playwright = Mock()
        auth.launch_background_edge(playwright)
        launch=playwright.chromium.launch.call_args.kwargs
        self.assertFalse(launch['headless'])
        self.assertEqual(launch['args'], ["--start-minimized"])
        self.assertTrue('executable_path' in launch or launch.get('channel')=='msedge')

    def test_restore_precedes_focus_and_minimize_never_focuses(self):
        page = Mock()
        session = page.context.new_cdp_session.return_value
        session.send.return_value = {"windowId": 17}
        auth.reveal_edge(page)
        self.assertEqual(session.send.call_args_list[1].args,
                         ("Browser.setWindowBounds", {"windowId": 17, "bounds": {"windowState": "normal"}}))
        page.bring_to_front.assert_called_once()
        session.detach.assert_called_once()
        page.reset_mock()
        auth.conceal_edge(page)
        self.assertEqual(session.send.call_args.args,
                         ("Browser.setWindowBounds", {"windowId": 17, "bounds": {"windowState": "minimized"}}))
        page.bring_to_front.assert_not_called()

    def test_restore_failure_is_explicit_and_detaches_session(self):
        page = Mock()
        session = page.context.new_cdp_session.return_value
        session.send.side_effect = RuntimeError("private data")
        with self.assertRaisesRegex(auth.AuthError, "无法恢复") as raised:
            auth.reveal_edge(page)
        self.assertNotIn("private data", str(raised.exception))
        session.detach.assert_called_once()


class CollectorRecoveryTests(Fixture):
    def test_rejected_401_revalidates_and_retries_only_once(self):
        page = FakePage(daily_profile())
        page.status = 401
        calls = []
        def recover(force=False):
            calls.append(force)
            if force:
                page.status = 200
                return True
            return False
        result = BillPageCollector(page, page.profile, self.root / "run", auth=recover).collect(BillRequest("2026-09-01", "2026-09-01"))
        self.assertEqual(result["task_id"], "NEW_17")
        self.assertEqual(calls.count(True), 1)
        self.assertEqual(sum(e == ("click", "#submit_button") for e in page.events), 2)

    def test_rejected_login_payload_can_resume_without_old_task(self):
        page = FakePage(daily_profile())
        page.payload = {"success": False, "message": "登录已失效"}
        calls = []
        def recover(force=False):
            calls.append(force)
            if force:
                page.payload = {"code": 200, "result": {"data": {"taskId": "NEW_17"}}}
            return force
        result = BillPageCollector(page, page.profile, self.root / "run", log=lambda _: None, auth=recover).collect(BillRequest("2026-09-01", "2026-09-01"))
        self.assertEqual(result["task_id"], "NEW_17")
        self.assertEqual(calls.count(True), 1)

    def test_repeated_expiry_stops_after_bounded_reauthentication(self):
        page = FakePage(daily_profile())
        page.status = 401
        calls = []
        with self.assertRaisesRegex(auth.BillCollectionError, "重复失效"):
            BillPageCollector(page, page.profile, self.root / "run", log=lambda _: None,
                auth=lambda force=False: calls.append(force)).collect(BillRequest("2026-09-01", "2026-09-01"))
        self.assertEqual(calls.count(True), 2)
        self.assertEqual(sum(e == ("click", "#submit_button") for e in page.events), 3)

    def test_403_never_triggers_sms_login(self):
        page = FakePage(daily_profile())
        page.status = 403
        calls = []
        with self.assertRaisesRegex(auth.BillCollectionError, "无账单导出权限"):
            BillPageCollector(page, page.profile, self.root / "run", auth=lambda force=False: calls.append(force)).collect(BillRequest("2026-09-01", "2026-09-01"))
        self.assertNotIn(True, calls)

    def test_expiry_while_waiting_keeps_same_export_task(self):
        page = FakePage(daily_profile())
        calls = 0
        def recover(force=False):
            nonlocal calls
            calls += 1
            return calls == 3
        result = BillPageCollector(page, page.profile, self.root / "run", auth=recover).collect(BillRequest("2026-09-01", "2026-09-01"))
        self.assertEqual(result["task_id"], "NEW_17")
        self.assertEqual(sum(e == ("click", "#submit_button") for e in page.events), 1)

    def test_unknown_export_response_is_not_resubmitted(self):
        page = FakePage(daily_profile())
        page.expect_response = lambda *args, **kwargs: (_ for _ in ()).throw(TimeoutError("unknown"))
        with self.assertRaises(auth.BillCollectionError):
            BillPageCollector(page, page.profile, self.root / "run", auth=lambda **kwargs: False).collect(BillRequest("2026-09-01", "2026-09-01"))
        self.assertEqual(sum(e == ("click", "#submit_button") for e in page.events), 0)

    def test_page_replaced_during_task_poll_resumes_same_id(self):
        page = FakePage(daily_profile())
        original = page.locator
        failed = False
        def locator(selector):
            nonlocal failed
            if selector == "[data-task-id='NEW_17']" and not failed:
                failed = True
                raise RuntimeError("document replaced")
            return original(selector)
        page.locator = locator
        renewed = False
        def recover(force=False):
            nonlocal renewed
            if failed and not renewed:
                renewed = True
                return True
            return False
        result = BillPageCollector(page, page.profile, self.root / "run", log=lambda _: None, auth=recover).collect(BillRequest("2026-09-01", "2026-09-01"))
        self.assertEqual(result["task_id"], "NEW_17")
        self.assertEqual(sum(e == ("click", "#submit_button") for e in page.events), 1)


class RouteTests(Fixture):
    def request(self, method="GET", headers=None, body=None):
        from starlette.requests import Request
        content = json.dumps(body).encode() if body is not None else b""
        fields = {"host": "127.0.0.1", "x-workspace-id": "tester", **(headers or {})}
        async def receive():
            return {"type": "http.request", "body": content, "more_body": False}
        return Request({"type": "http", "method": method, "scheme": "http", "path": "/",
                        "query_string": b"", "server": ("127.0.0.1", 80),
                        "headers": [(k.encode(), v.encode()) for k, v in fields.items()]}, receive)

    def test_external_origin_host_and_missing_owner_are_rejected(self):
        from fastapi import HTTPException
        with patch.object(routes, "BROKER", self.broker):
            for extra in ({"origin": "https://evil.example"}, {"host": "evil.example"}):
                with self.assertRaises(HTTPException) as raised:
                    routes.status(self.request(headers=extra))
                self.assertEqual(raised.exception.status_code, 403)
            with self.assertRaises(HTTPException) as raised:
                routes.status(self.request(headers={"x-workspace-id": ""}))
            self.assertEqual(raised.exception.status_code, 400)

    def test_chinese_owner_is_decoded_and_credentials_not_returned(self):
        from urllib.parse import quote
        with patch.object(routes, "BROKER", self.broker):
            with self.broker.operation("测试", self.cancelled):
                result = routes.status(self.request(headers={"x-workspace-id": quote("测试")}))
                self.assertIsNotNone(result["challenge_id"])
                self.assertNotIn("cookie", json.dumps(result))

    def test_non_json_send_is_rejected(self):
        from fastapi import HTTPException
        with patch.object(routes, "BROKER", self.broker), self.assertRaises(HTTPException) as raised:
            asyncio.run(routes.command("send", self.request("POST")))
        self.assertEqual(raised.exception.status_code, 415)

    def test_old_or_foreign_challenge_cannot_send(self):
        with patch.object(routes, "BROKER", self.broker):
            result = asyncio.run(routes.command("send", self.request("POST", {"content-type": "application/json"},
                                    {"challenge_id": "old", "phone": "13800138000"})))
            self.assertFalse(result["ok"])
            self.assertTrue(self.broker.commands.empty())


if __name__ == "__main__":
    unittest.main()
