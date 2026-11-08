import json
from pathlib import Path
import sys
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
import zipfile

import requests

sys.path.insert(0, str(Path(__file__).parents[1]))
from fengshen_bill import AuthenticationRequired, BillCollectionError, DAILY_CREATE_URL, DAILY_DOWNLOAD_URL
from fengshen_http import FengshenHttpClient, HttpTransportError, INIT_URL, AGENCIES_URL, SWITCH_URL
from fengshen_http_daily import DailyHttpCollector
from fengshen_http import PlatformRateLimited
from fengshen_orders import QUERY_URL


class Response:
    def __init__(self, value=None, status=200, body=None, headers=None):
        self.status_code, self.headers = status, headers or {}
        self.body = body if body is not None else json.dumps(value).encode()
    def __enter__(self): return self
    def __exit__(self, *args): pass
    def iter_content(self, size):
        for i in range(0, len(self.body), size): yield self.body[i:i + size]


class HttpTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(dir=Path(__file__).parent)
        self.root = Path(self.directory.name)
        self.client = FengshenHttpClient()
        self.client.session.request = Mock()
        self.client.files_session.get = Mock()
    def tearDown(self):
        self.client.close()
        self.directory.cleanup()

    def test_restores_only_platform_cookies_and_ignores_expired(self):
        cookies = [{"name": n, "value": "secret", "domain": d, "expires": e} for n, d, e in
                   (("valid", ".ele.me", -1), ("old", ".ele.me", 10), ("unrelated", "example.com", -1))]
        with_client = FengshenHttpClient({"cookies": cookies, "origins": []})
        try:
            self.assertEqual([c.name for c in with_client.session.cookies], ["valid"])
            self.assertTrue(with_client.storage_state()["cookies"][0]["secure"])
        finally: with_client.close()

    def test_shard_is_scoped_to_api_host(self):
        self.client.session.cookies.set("PASSPORT_AGENTS_SHARD", "wrong", domain="other.ele.me")
        self.client.session.cookies.set("PASSPORT_AGENTS_SHARD", "right", domain=".ele.me")
        self.assertEqual(self.client._headers(INIT_URL)["X-Shard"], "right")
        self.assertNotIn("X-Shard", self.client._headers(DAILY_DOWNLOAD_URL))

    def test_endpoint_and_method_must_be_observed(self):
        for method, url in (("POST", INIT_URL), ("GET", INIT_URL + "?x=1"), ("GET", "https://example.com/")):
            with self.subTest(url=url), self.assertRaises(HttpTransportError):
                self.client.request_json(method, url)
        self.client.session.request.assert_not_called()

    def test_cancellation_prevents_network(self):
        self.client.cancelled.set()
        with self.assertRaises(HttpTransportError): self.client.identity()
        self.client.session.request.assert_not_called()

    def test_auth_redirect_does_not_follow_or_leak_url(self):
        self.client.session.request.return_value = Response(status=302, headers={"Location": "https://example.com/?token=secret"})
        with self.assertRaises(AuthenticationRequired) as error: self.client.identity()
        self.assertNotIn("secret", str(error.exception))
        self.assertFalse(self.client.session.request.call_args.kwargs["allow_redirects"])

    def test_network_error_is_redacted_and_not_retried(self):
        self.client.session.request.side_effect = requests.Timeout("token=private-secret")
        with self.assertRaises(HttpTransportError) as error: self.client.identity()
        self.assertNotIn("private-secret", str(error.exception))
        self.assertEqual(self.client.session.request.call_count, 1)

    def test_invalid_json_and_oversized_response(self):
        for body in (b"<html>login</html>", b"x" * 70):
            self.client.session.request.return_value = Response(body=body)
            with patch("fengshen_http.MAX_JSON", 64), self.assertRaises(HttpTransportError): self.client.identity()

    def test_login_rejection_not_treated_as_empty_data(self):
        self.client.session.request.return_value = Response({"code": 401, "message": "请先登录"})
        with self.assertRaises(AuthenticationRequired): self.client.identity()

    def test_city_switch_requires_authorization_and_readback(self):
        self.client.request_json = Mock(side_effect=[{"data": [{"agencyId": 2}]}, {"data": {"agencyId": 1}},
                                                    {"code": 200}, {"data": {"agencyId": 2}}])
        self.client.select_city("2")
        self.assertEqual(self.client.request_json.call_args_list[2].args, ("POST", SWITCH_URL))
        self.assertEqual(self.client.request_json.call_args_list[2].kwargs["body"], {"toAgencyId": 2})

    def test_city_permission_failure_never_switches(self):
        self.client.request_json = Mock(return_value={"data": [{"agencyId": 1}]})
        with self.assertRaises(HttpTransportError): self.client.select_city("2")
        self.assertEqual(self.client.request_json.call_count, 1)

    def test_switch_response_alone_is_not_city_proof(self):
        self.client.request_json = Mock(side_effect=[{"data": [{"agencyId": 2}]}, {"data": {"agencyId": 1}},
                                                    {"code": 200}, {"data": {"agencyId": 1}}])
        with self.assertRaises(HttpTransportError): self.client.select_city("2")

    def test_unknown_submission_survives_timeout_and_blocks_retry(self):
        self.client.request_json = Mock(side_effect=requests.Timeout("secret"))
        receipt = self.root / "attempt.json"
        for _ in range(2):
            with self.assertRaises(HttpTransportError) as error:
                self.client.submit_once(DAILY_CREATE_URL, {"secret": "do-not-log"}, receipt, {"agency_id": "2"})
            self.assertEqual(error.exception.download_submission_state, "unknown")
        self.assertEqual(self.client.request_json.call_count, 1)
        self.assertEqual(json.loads(receipt.read_text())["submission_state"], "unknown")
        self.assertNotIn("secret", receipt.read_text())

    def test_successful_submission_still_blocks_duplicate(self):
        self.client.request_json = Mock(return_value={"code": 200})
        receipt = self.root / "attempt.json"
        self.client.submit_once(DAILY_CREATE_URL, {}, receipt, {})
        with self.assertRaises(HttpTransportError): self.client.submit_once(DAILY_CREATE_URL, {}, receipt, {})
        self.assertEqual(json.loads(receipt.read_text())["submission_state"], "submitted")
        self.assertEqual(self.client.request_json.call_count, 1)

    def test_redirected_file_has_no_platform_auth_headers(self):
        self.client.session.get = Mock(return_value=Response(status=302, headers={"Location": "https://bucket.oss-cn-shanghai.aliyuncs.com/file?signature=private"}))
        self.client.files_session.get.return_value = Response(body=b"file")
        target = self.root / "bill.zip"
        self.client.download(DAILY_DOWNLOAD_URL + "?id=1&agentId=2", target, authenticated=True)
        self.assertEqual(target.read_bytes(), b"file")
        headers = self.client.files_session.get.call_args.kwargs["headers"]
        self.assertEqual(headers, {"Accept": "application/octet-stream"})
        self.assertEqual(len(self.client.files_session.cookies), 0)

    def test_bad_redirect_never_requested(self):
        self.client.files_session.get.return_value = Response(status=302, headers={"Location": "http://127.0.0.1/private"})
        with self.assertRaises(BillCollectionError): self.client.download("https://file.ele.me/a", self.root / "file.zip")
        self.assertEqual(self.client.files_session.get.call_count, 1)
        self.assertFalse(list(self.root.iterdir()))

    def test_size_limit_cleans_partial_file(self):
        self.client.files_session.get.return_value = Response(body=b"x" * 65)
        with patch("fengshen_http.MAX_FILE", 64), self.assertRaises(HttpTransportError):
            self.client.download("https://file.ele.me/a", self.root / "file.zip")
        self.assertFalse(list(self.root.iterdir()))

    def test_download_never_overwrites_existing_file(self):
        target = self.root / "file.zip"
        target.write_bytes(b"original")
        with self.assertRaises(HttpTransportError): self.client.download("https://file.ele.me/a", target)
        self.assertEqual(target.read_bytes(), b"original")
        self.client.files_session.get.assert_not_called()

    def test_download_retries_transient_connection_error(self):
        self.client.cancelled = Mock(is_set=Mock(return_value=False))
        self.client.files_session.get.side_effect = [requests.ConnectionError("connection reset"),
                                                     Response(body=b"file")]
        target = self.root / "violations.csv"
        self.assertEqual(self.client.download("https://file.ele.me/a", target), target)
        self.assertEqual(target.read_bytes(), b"file")
        self.assertEqual(self.client.files_session.get.call_count, 2)
        self.client.cancelled.wait.assert_called_once_with(2)
        self.assertEqual(list(self.root.iterdir()), [target])

    def test_download_midstream_break_recovers_on_retry(self):
        class Broken(Response):
            def iter_content(self, size):
                yield self.body[:4]
                raise requests.exceptions.ChunkedEncodingError("传输中断")
        self.client.cancelled = Mock(is_set=Mock(return_value=False))
        self.client.files_session.get.side_effect = [Broken(body=b"partial-body"), Response(body=b"complete")]
        target = self.root / "violations.csv"
        self.assertEqual(self.client.download("https://file.ele.me/a", target), target)
        self.assertEqual(target.read_bytes(), b"complete")
        self.assertEqual(self.client.files_session.get.call_count, 2)
        self.assertEqual(list(self.root.iterdir()), [target])

    def test_download_connection_failure_stops_after_three_attempts(self):
        self.client.cancelled = Mock(is_set=Mock(return_value=False))
        self.client.files_session.get.side_effect = requests.ConnectionError("connection reset")
        with self.assertRaises(HttpTransportError) as error:
            self.client.download("https://file.ele.me/a", self.root / "violations.csv")
        self.assertEqual(error.exception.download_failure_phase, "downloading")
        self.assertEqual(error.exception.download_submission_state, "submitted")
        self.assertEqual(self.client.files_session.get.call_count, 3)
        self.client.cancelled.wait.assert_any_call(2)
        self.client.cancelled.wait.assert_any_call(4)
        self.assertEqual(list(self.root.iterdir()), [])

    def test_download_platform_rejection_is_never_retried(self):
        self.client.files_session.get.return_value = Response(status=404, body=b"")
        with self.assertRaises(HttpTransportError) as error:
            self.client.download("https://file.ele.me/a", self.root / "file.zip")
        self.assertEqual(self.client.files_session.get.call_count, 1)
        self.assertEqual(list(self.root.iterdir()), [])

    def test_cancel_during_download_backoff_prevents_retry(self):
        event = Mock(is_set=Mock(return_value=False))
        event.wait.side_effect = lambda _: setattr(event.is_set, "return_value", True)
        self.client.cancelled = event
        self.client.files_session.get.side_effect = requests.ConnectionError("connection reset")
        with self.assertRaises(HttpTransportError) as error:
            self.client.download("https://file.ele.me/a", self.root / "file.zip")
        self.assertIn("取消", str(error.exception))
        self.assertEqual(self.client.files_session.get.call_count, 1)

    def test_daily_adapter_submits_exact_selection_and_validates_file(self):
        now = int(time.time())
        task = {"id": 7, "agentId": 2, "title": "总部账单-代理商账单-09-01-09-15",
                "operationDate": now, "status": 2, "statusName": "导出成功"}
        fake = Mock(spec=FengshenHttpClient, cancelled=threading.Event())
        fake.submit_once.return_value = ({"code": 200}, {"started_at": now, "finished_at": now})
        fake.request_json.side_effect = [{"data": [], "total": 0}, {"data": [task], "total": 1}]
        def download(url, target, **kwargs):
            with zipfile.ZipFile(target, "w") as archive: archive.writestr("sample.csv", "示例,金额\n")
            return target
        fake.download.side_effect = download
        fake.daily_file_url.return_value = "https://files.aliyuncs.com/daily.zip"
        result = DailyHttpCollector(fake).daily(SimpleNamespace(start="2026-09-01", end="2026-09-15", agency_id="2"), self.root, {"penalty"})
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["task_id"], "7")
        self.assertEqual(len(result["files"][0]["sha256"]), 64)
        self.assertEqual(fake.submit_once.call_args.args[1]["subBillTypes"], [2])
        self.assertEqual(fake.submit_once.call_count, 1)
        fake.daily_file_url.assert_called_once_with(7, "2")

    def test_rate_limited_read_uses_bounded_backoff_without_login(self):
        self.client.cancelled = Mock(is_set=Mock(return_value=False))
        self.client.auth_handler = Mock()
        self.client.session.request.side_effect = [Response({"result": {"code": "REQUEST_TOO_FREQUENT"}}),
                                                   Response({"code": 200})]
        self.assertEqual(self.client.request_json("POST", QUERY_URL, body={}), {"code": 200})
        self.assertEqual(self.client.session.request.call_count, 2)
        self.client.cancelled.wait.assert_any_call(2)
        self.client.auth_handler.assert_not_called()

    def test_rate_limited_export_is_never_replayed(self):
        self.client.session.request.return_value = Response({"result": {"code": "REQUEST_TOO_FREQUENT"}})
        with self.assertRaises(HttpTransportError) as error:
            self.client.submit_once(DAILY_CREATE_URL, {}, self.root / "limited.json", {})
        self.assertEqual(error.exception.download_submission_state, "unknown")
        self.assertEqual(self.client.session.request.call_count, 1)

    def test_rate_limit_read_retries_stop_after_four_attempts(self):
        self.client.cancelled = Mock(is_set=Mock(return_value=False))
        self.client.session.request.side_effect = lambda *a, **k: Response(status=429)
        with self.assertRaises(PlatformRateLimited):
            self.client.request_json("POST", QUERY_URL, body={})
        self.assertEqual(self.client.session.request.call_count, 4)

    def test_cancel_during_rate_backoff_prevents_next_request(self):
        event = Mock(is_set=Mock(return_value=False))
        event.wait.side_effect = lambda _: setattr(event.is_set, "return_value", True)
        self.client.cancelled = event
        self.client.session.request.return_value = Response(status=429)
        with self.assertRaises(HttpTransportError):
            self.client.request_json("POST", QUERY_URL, body={})
        self.assertEqual(self.client.session.request.call_count, 1)

    def test_daily_file_url_reads_json_string_for_original_task(self):
        url = "https://bill.oss-cn-shanghai.aliyuncs.com/original.zip?signature=private"
        self.client.session.get = Mock()
        self.client.session.get.return_value = Response(body=json.dumps(url).encode(),
                                                          headers={"Content-Type": "application/json"})
        self.assertEqual(self.client.daily_file_url(7, "2"), url)
        self.assertIn("id=7&agentId=2", self.client.session.get.call_args.args[0])
        self.client.session.request.assert_not_called()

    def test_daily_adapter_never_selects_ambiguous_new_task(self):
        now = int(time.time())
        fake = Mock(spec=FengshenHttpClient, cancelled=threading.Event())
        fake.submit_once.return_value = ({}, {"started_at": now, "finished_at": now})
        rows = [{"id": i, "agentId": 2, "title": "总部账单-代理商账单-09-01-09-15", "operationDate": now,
                 "status": 2, "statusName": "导出成功"} for i in (8, 7)]
        fake.request_json.side_effect = [{"data": [], "total": 0}, {"data": rows, "total": 2}]
        with self.assertRaises(BillCollectionError) as error:
            DailyHttpCollector(fake).daily(SimpleNamespace(start="2026-09-01", end="2026-09-15", agency_id="2"), self.root, {"delivery_fee"})
        self.assertEqual(error.exception.download_submission_state, "submitted")
        fake.download.assert_not_called()
        self.assertEqual(fake.submit_once.call_count, 1)

    def test_uncertain_daily_create_reconciles_unique_platform_task_without_resubmit(self):
        now = int(time.time())
        task = {"id": 7, "agentId": 2, "title": "总部账单-代理商账单-09-01-09-15",
                "operationDate": now, "status": 2, "statusName": "导出成功"}
        fake = Mock(spec=FengshenHttpClient, cancelled=threading.Event())
        fake.request_json.side_effect = [{"data": [], "total": 0}, {"data": [task], "total": 1}]
        fake.daily_file_url.return_value = "https://files.aliyuncs.com/daily.zip"
        def uncertain(_url, _body, receipt_path, scope):
            Path(receipt_path).write_text(json.dumps({"transport": "http", "scope": scope,
                "submission_state": "unknown", "started_at": now}), encoding="utf-8")
            raise HttpTransportError("unknown", "submitting", "unknown")
        fake.submit_once.side_effect = uncertain
        def download(url, target):
            with zipfile.ZipFile(target, "w") as archive:
                archive.writestr("sample.csv", "示例,金额\n")
            return target
        fake.download.side_effect = download
        result = DailyHttpCollector(fake).daily(
            SimpleNamespace(start="2026-09-01", end="2026-09-15", agency_id="2"),
            self.root / "attempt", {"delivery_fee"})
        receipt = json.loads((self.root / "attempt" / "http_submission.json").read_text(encoding="utf-8"))
        self.assertEqual((result["status"], receipt["submission_state"], receipt["task_id"]),
                         ("success", "submitted", "7"))
        fake.submit_once.assert_called_once()

    def test_daily_recovery_downloads_only_unique_original_task_without_export(self):
        now = int(time.time())
        source, target = self.root / "source", self.root / "recovered"
        source.mkdir()
        (source / "http_baseline.json").write_text('{"task_ids":[5]}', encoding="utf-8")
        (source / "http_submission.json").write_text(json.dumps({"transport": "http",
            "scope": {"agency_id": "2", "start": "2026-09-01", "end": "2026-09-15",
                      "datasets": ["delivery_fee"]}, "started_at": now}), encoding="utf-8")
        task = {"id": 7, "agentId": 2, "title": "总部账单-代理商账单-09-01-09-15",
                "operationDate": now, "status": 2, "statusName": "导出成功"}
        fake = Mock(spec=FengshenHttpClient, cancelled=threading.Event())
        fake.request_json.return_value = {"data": [task], "total": 1}
        def download(url, path, **kwargs):
            with zipfile.ZipFile(path, "w") as archive:
                archive.writestr("sample.csv", "示例,金额\n")
            return path
        fake.download.side_effect = download
        fake.daily_file_url.return_value = "https://files.aliyuncs.com/daily.zip"
        result = DailyHttpCollector(fake).resume_daily(
            SimpleNamespace(start="2026-09-01", end="2026-09-15", agency_id="2"),
            target, {"delivery_fee"}, source)
        self.assertEqual((result["status"], result["task_id"]), ("success", "7"))
        fake.submit_once.assert_not_called()
        fake.download.assert_called_once()
        fake.daily_file_url.assert_called_once_with(7, "2")


if __name__ == "__main__": unittest.main()
