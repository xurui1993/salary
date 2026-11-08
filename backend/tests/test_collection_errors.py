import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from collection_errors import CollectionFailure, PHASE_LABELS, collection_failure
from fengshen_bill import BillCollectionError


class CollectionErrorTests(unittest.TestCase):
    def test_unknown_errors_have_stage_guidance_and_original_type(self):
        failure = collection_failure(RuntimeError("private response payload"), "session_restore")
        self.assertIsInstance(failure, BillCollectionError)
        self.assertIn("无法恢复本机风神会话", str(failure))
        self.assertEqual(failure.message, str(failure))
        self.assertEqual(failure.diagnostics["phase"], "session_restore")
        self.assertEqual(failure.diagnostics["exception_type"], "RuntimeError")
        self.assertEqual(failure.diagnostics["reason_code"], "operation_failed")
        self.assertNotIn("private response payload", str(failure))

    def test_all_preparation_phases_provide_fixed_guidance(self):
        for phase in PHASE_LABELS:
            with self.subTest(phase=phase):
                failure = collection_failure(RuntimeError("private"), phase)
                self.assertEqual(failure.diagnostics["phase"], phase)
                self.assertNotIn("private", str(failure))
                self.assertIn("核算已停止", str(failure))
        self.assertIn("资料校验", str(collection_failure(RuntimeError(), "input_validation")))

    def test_known_browser_failures_use_finite_reason_codes(self):
        cases = (
            ("net::ERR_CERT_AUTHORITY_INVALID", "certificate_error", "证书"),
            ("net::ERR_NAME_NOT_RESOLVED", "name_resolution_failed", "DNS"),
            ("net::ERR_CONNECTION_RESET", "connection_error", "连接"),
            ("net::ERR_INTERNET_DISCONNECTED", "connection_error", "网络"),
            ("net::ERR_ABORTED", "navigation_interrupted", "跳转"),
            ("Execution context was destroyed", "context_destroyed", "上下文"),
            ("Frame was detached", "context_destroyed", "上下文"),
            ("Target page, context or browser has been closed", "target_closed", "已关闭"),
            ("Executable doesn't exist", "browser_unavailable", "Edge"),
        )
        for original, code, hint in cases:
            with self.subTest(code=code, original=original):
                failure = collection_failure(RuntimeError(original), "navigation", "agency_daily")
                self.assertEqual(failure.diagnostics["reason_code"], code)
                self.assertIn(hint, str(failure))
                self.assertIn("配送费和违规扣款", str(failure))
                self.assertNotIn(original, str(failure))

    def test_timeout_category_preserves_safe_diagnostics(self):
        for original, kind in (
            ('waiting for event "response"', "response"),
            ('waiting for event "download"', "download"),
            ("Locator.click: Timeout", "locator"),
            ("page timed out", "other"),
        ):
            with self.subTest(kind=kind):
                failure = collection_failure(TimeoutError(original), "collect", "rider_monthly")
                self.assertEqual(failure.diagnostics["reason_code"], "timeout_" + kind)
                self.assertEqual(failure.diagnostics["timeout_kind"], kind)
                self.assertEqual(failure.diagnostics["exception_type"], "TimeoutError")

    def test_known_python_failures_are_classified(self):
        for exc, code in (
            (ModuleNotFoundError("sensitive module path"), "dependency_missing"),
            (PermissionError("sensitive file path"), "permission_denied"),
        ):
            with self.subTest(code=code):
                failure = collection_failure(exc, "input_validation")
                self.assertEqual(failure.diagnostics["reason_code"], code)
                self.assertNotIn("sensitive", str(failure))

    def test_raw_browser_errors_do_not_leak_credentials_or_personal_data(self):
        private = "https://example.invalid/report?token=secret-token cookie=secret-cookie phone=13800138000"
        for exc in (RuntimeError(private), TimeoutError(private), RuntimeError("net::ERR_CERT_AUTHORITY_INVALID " + private)):
            with self.subTest(error_type=type(exc).__name__):
                failure = collection_failure(exc, "navigation", "issue_orders")
                rendered = str(failure) + json.dumps(failure.diagnostics, ensure_ascii=False)
                for value in ("https://", "secret-token", "secret-cookie", "13800138000", "example.invalid"):
                    self.assertNotIn(value, rendered)

    def test_safe_business_error_is_preserved(self):
        message = "下载清单周期错误"
        failure = collection_failure(BillCollectionError(message), "input_validation")
        self.assertEqual(str(failure), message)
        self.assertEqual(failure.diagnostics["reason_code"], "business_error")

    def test_business_error_cannot_smuggle_sensitive_payloads(self):
        for message in (
            "下载失败：https://example.invalid/?token=secret",
            "cookie=secret-cookie",
            "Authorization: Bearer secret-auth",
            "手机号：13800138000",
            "身份证号=110101199001010011",
            "验证码=123456",
        ):
            with self.subTest(message=message):
                failure = collection_failure(BillCollectionError(message), "input_validation")
                self.assertNotEqual(str(failure), message)
                self.assertNotIn(message, json.dumps(failure.diagnostics, ensure_ascii=False))
                self.assertIn("资料校验", str(failure))

    def test_wrapping_existing_failure_preserves_original_diagnostics(self):
        failure = collection_failure(RuntimeError("private"), "navigation", "agency_daily")
        self.assertIs(collection_failure(failure, "input_validation"), failure)
        self.assertEqual(failure.diagnostics["exception_type"], "RuntimeError")
        self.assertEqual(failure.diagnostics["phase"], "navigation")

    def test_untrusted_stage_or_dataset_is_not_included(self):
        failure = collection_failure(RuntimeError("private"), "token=private-phase", "13800138000")
        self.assertEqual(failure.diagnostics["phase"], "unknown")
        self.assertEqual(failure.diagnostics["dataset"], "")
        rendered = str(failure) + json.dumps(failure.diagnostics, ensure_ascii=False)
        self.assertNotIn("private-phase", rendered)
        self.assertNotIn("13800138000", rendered)


if __name__ == "__main__":
    unittest.main()
