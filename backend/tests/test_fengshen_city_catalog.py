import datetime as dt
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import fengshen_auth
import fengshen_city_catalog as catalog
import fengshen_http
import download_service
import parttime_source
from test_parttime_source import template


class CityCatalogTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.static = self.root / "fengshen_cities.json"
        self.static.write_text(json.dumps({"泉州": "31029436", "上海": "31019404"}), encoding="utf-8")
        self.cache = self.root / ".local_downloads" / "cities.json"
        self.patches = [patch.object(catalog, "STATIC_FILE", self.static),
                        patch.object(catalog, "CACHE_FILE", self.cache)]
        for item in self.patches:
            item.start()

    def tearDown(self):
        for item in reversed(self.patches):
            item.stop()
        self.temp.cleanup()

    def test_no_cache_uses_local_configuration(self):
        snapshot = catalog.snapshot()
        self.assertEqual(snapshot["source"], "config")
        self.assertEqual(snapshot["cities"], {"泉州": "31029436", "上海": "31019404"})
        self.assertEqual(catalog.selectable_cities(), snapshot["cities"])

    def test_refresh_caches_fengshen_cities_and_keeps_static_history(self):
        with patch.object(catalog, "_fetch", return_value={"泉州": "31029436", "三亚": "31030156"}):
            result = catalog.refresh(force=True)
        self.assertEqual(result["source"], "fengshen")
        self.assertTrue(result["updated_at"])
        self.assertEqual(catalog.selectable_cities(), {"泉州": "31029436", "三亚": "31030156"})
        # 静态配置中的上海仍可用于解析历史任务
        self.assertEqual(catalog.all_cities()["上海"], "31019404")
        self.assertEqual(catalog.all_cities()["三亚"], "31030156")

    def test_off_shelf_cities_are_disabled_but_still_resolvable(self):
        live = {"泉州": "31029436", "大连": "31029684", "保定": "31030396"}
        with patch.object(catalog, "_fetch", return_value=live):
            catalog.refresh(force=True)
        self.assertEqual(catalog.selectable_cities(), {"泉州": "31029436"})
        self.assertEqual(catalog.all_cities()["大连"], "31029684")
        self.assertEqual(catalog.all_cities()["保定"], "31030396")
        options = download_service.get_options()
        self.assertEqual([(item["name"], item.get("disabled", False), item.get("note"))
                          for item in options["cities"]],
                         [("泉州", False, None), ("大连", True, "已下架"), ("保定", True, "已下架")])
        with self.assertRaisesRegex(download_service.ValidationError, "大连 已下架"):
            download_service.validate_request({"cities": ["大连"], "datasets": ["delivery_fee"],
                                               "start": "2026-10-01", "end": "2026-10-02"})

    def test_refresh_failure_keeps_last_successful_cache(self):
        with patch.object(catalog, "_fetch", return_value={"泉州": "31029436", "大连": "31029684"}):
            catalog.refresh(force=True)
        with patch.object(catalog, "_fetch", side_effect=RuntimeError("offline")):
            result = catalog.refresh(force=True)
        self.assertEqual(result["source"], "fengshen")
        self.assertEqual(result["cities"], {"泉州": "31029436", "大连": "31029684"})

    def test_removed_city_is_hidden_but_still_resolvable(self):
        with patch.object(catalog, "_fetch", return_value={"泉州": "31029436", "三亚": "31030156"}):
            catalog.refresh(force=True)
        with patch.object(catalog, "_fetch", return_value={"泉州": "31029436"}):
            catalog.refresh(force=True)
        self.assertEqual(catalog.selectable_cities(), {"泉州": "31029436"})
        self.assertEqual(catalog.all_cities()["三亚"], "31030156")

    def test_refresh_reuses_fresh_cache(self):
        with patch.object(catalog, "_fetch", return_value={"泉州": "31029436"}) as fetch:
            catalog.refresh(force=True)
            catalog.refresh()
        fetch.assert_called_once()

    def test_payroll_template_accepts_a_city_from_the_live_catalogue(self):
        with patch.object(catalog, "_fetch", return_value={"保定": "31030396"}):
            catalog.refresh(force=True)
        path = self.root / "保定-template.xlsx"
        template(path, [["保定", "00123", dt.date(2026, 8, 16), dt.date(2026, 8, 31), "半月结"]])
        plan = parttime_source.read_template(path)
        self.assertEqual((plan.city, plan.agency_id), ("保定", "31030396"))

    def test_fetch_only_uses_logistics_partner_cities(self):
        rows = [
            {"agencyId": 22476859, "agencyCityName": "", "agencySubTypeName": "总商"},
            {"agencyId": 31029436, "agencyCityName": "泉州", "agencySubTypeName": "物流合作商"},
            {"agencyId": 99999999, "agencyCityName": "泉州", "agencySubTypeName": "物流合作商"},
            {"agencyId": 14645403, "agencyCityName": "深圳", "agencySubTypeName": "物流服务商"},
            {"agencyId": 31030156, "agencyCityName": "", "agencySubTypeName": "物流合作商"},
            "invalid-row",
        ]
        client = Mock()
        client.request_json.return_value = {"data": rows}
        vault = Mock()
        vault.load.return_value = {"cookies": [], "origins": []}
        with patch.object(fengshen_auth, "SessionVault", return_value=vault), \
             patch.object(fengshen_http, "FengshenHttpClient", return_value=client):
            self.assertEqual(catalog._fetch(), {"泉州": "31029436"})
        client.request_json.assert_called_once_with("GET", fengshen_http.AGENCIES_URL)
        self.assertEqual(client.timeout, (4, 6))
        self.assertEqual(client.attempts, 1)
        client.close.assert_called_once()


class DownloadServiceCityTests(unittest.TestCase):
    def test_validation_and_options_follow_the_live_catalogue(self):
        live = {"泉州": "31029436", "台州": "31046244"}
        snapshot = {"cities": live, "source": "fengshen", "updated_at": "2026-10-24T10:00:00+08:00"}
        with patch.object(download_service.city_catalog, "selectable_cities", return_value=live), \
             patch.object(download_service.city_catalog, "snapshot", return_value=snapshot):
            config = download_service.validate_request(
                {"cities": ["台州"], "datasets": ["delivery_fee"], "start": "2026-10-01", "end": "2026-10-02"})
            self.assertEqual(config["cities"], ["台州"])
            with self.assertRaises(download_service.ValidationError):
                download_service.validate_request(
                    {"cities": ["韶关"], "datasets": ["delivery_fee"], "start": "2026-10-01", "end": "2026-10-02"})
            with self.assertRaisesRegex(download_service.ValidationError, "已下架"):
                download_service.validate_request(
                    {"cities": ["保定"], "datasets": ["delivery_fee"], "start": "2026-10-01", "end": "2026-10-02"})
            options = download_service.get_options()
        self.assertEqual([item["name"] for item in options["cities"]], ["泉州", "台州"])
        self.assertFalse(any(item.get("disabled") for item in options["cities"]))
        self.assertEqual(options["cities_source"], "fengshen")
        self.assertEqual(options["cities_updated_at"], "2026-10-24T10:00:00+08:00")


if __name__ == "__main__":
    unittest.main()
