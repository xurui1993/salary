"""The download service must use only the verified HTTP collectors."""
from contextlib import contextmanager
from pathlib import Path
import sys
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import download_service


class DownloadHttpRunnerTests(unittest.TestCase):
    def test_default_runner_routes_every_dataset_without_browser(self):
        broker = Mock()
        broker.status.return_value = {"busy": False}
        broker.vault.load.return_value = None

        @contextmanager
        def operation(*_args, **_kwargs):
            yield broker

        broker.operation.side_effect = operation
        client = Mock()
        auth = Mock()
        daily, reports, riders = Mock(), Mock(), Mock()
        plan = SimpleNamespace(agency_id="31029436", city="泉州", start="2026-10-14",
                               end="2026-10-14", month="2026-10")
        with patch("fengshen_auth.BROKER", broker), \
             patch("fengshen_http.FengshenHttpClient", return_value=client), \
             patch("fengshen_http_auth.HTTPAuth", return_value=auth), \
             patch("fengshen_http_daily.DailyHttpCollector", return_value=daily), \
             patch("fengshen_http_reports.ReportHttpCollector", return_value=reports), \
             patch("fengshen_http_riders.RiderHttpCollector", return_value=riders), \
             patch("playwright.sync_api.sync_playwright", side_effect=AssertionError("browser launched")):
            with download_service._open_runner({"owner": "test"}, Mock(), threading.Event(), Mock()) as runner:
                runner.daily(plan, "raw", {"delivery_fee"})
                runner.resume_daily(plan, "raw", {"delivery_fee"}, "old")
                runner.monthly(plan, "raw")
                runner.orders(plan, "raw", {"fraud"})
                runner.orders_batch(plan, "batch-raw", {"problem"})
                runner.resume_orders(plan, "raw", {"fraud"}, "old")
                runner.rider_source(plan, "raw", "receive_account")
                runner.rider_source(plan, "raw", "rider_info")
                runner.rider_source(plan, "raw", "rider_detail")
                runner.resume_detail(plan, "raw", "old")

        auth.ensure.assert_called_once_with()
        daily.daily.assert_called_once_with(plan, "raw", {"delivery_fee"})
        daily.resume_daily.assert_called_once_with(plan, "raw", {"delivery_fee"}, "old")
        reports.monthly.assert_called_once_with(plan, "raw")
        self.assertEqual(reports.orders.call_count, 2)
        reports.orders.assert_any_call(plan, "raw", {"fraud"})
        reports.orders.assert_any_call(plan, "batch-raw", {"problem"}, allow_existing_batches=True)
        reports.resume_orders.assert_called_once_with(plan, "raw", {"fraud"}, "old")
        self.assertEqual(riders.rider_source.call_count, 3)
        riders.resume_detail.assert_called_once_with(plan, "raw", "old")
        self.assertEqual(client.select_city.call_count, 4)
        client.close.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
