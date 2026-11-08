import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from fengshen_bill import BillCollectionError, BillPageCollector, MonthlyBillPageCollector, validate_profile
from test_fengshen_bill import FakeLocator, FakePage, monthly_profile
import test_parttime_source as fixtures


class LogisticsPartnerCityTests(unittest.TestCase):
    def collector(self, agency_id="31029436", monthly=False, selected=False, header_matches=True):
        profile = fixtures.TargetSelectionTests().profile()
        if monthly:
            city_keys = {key: value for key, value in profile.items() if key.startswith("city_")}
            profile = {**monthly_profile(), **city_keys, "selection_mode": "target_city"}
        profile["expected_agency_id"] = agency_id
        page = FakePage(profile, monthly=monthly)
        page.controls["#agency_context"].wait_for = lambda **kwargs: None
        page.controls["#agency_context"].text = f"[{agency_id}] 测试城市" if header_matches else "[22476859] 总商"
        root, option, active = fixtures.TargetSelectionTests.add_city_group(page, agency_id, selected)
        wrong = "#city_popup #city_" + agency_id
        page.controls[wrong] = FakeLocator(page, wrong, text=f"[{agency_id}] 同编号物流服务商")
        cls = MonthlyBillPageCollector if monthly else BillPageCollector
        return cls(page, profile, Path("unused"), log=lambda _: None), page, root, option, active, wrong

    def test_all_configured_cities_use_logistics_partner_group_for_both_datasets(self):
        cities = json.loads((Path(__file__).resolve().parents[1] / "fengshen_cities.json").read_text(encoding="utf-8"))
        for city, agency_id in cities.items():
            for monthly in (False, True):
                with self.subTest(city=city, monthly=monthly):
                    collector, page, _, option, _, wrong = self.collector(agency_id, monthly)
                    collector._check_agency_context()
                    self.assertIn(("click", option), page.events)
                    self.assertNotIn(("click", wrong), page.events)
                    self.assertFalse(page.controls["#city_popup"].visible)

    def test_correct_header_id_does_not_skip_wrong_group_correction(self):
        collector, page, _, option, _, wrong = self.collector()
        collector._check_agency_context()
        self.assertIn(("click", option), page.events)
        self.assertNotIn(("click", wrong), page.events)

    def test_already_selected_logistics_partner_only_checks_without_reselecting(self):
        collector, page, _, option, _, _ = self.collector(selected=True)
        collector._check_agency_context()
        self.assertNotIn(("click", option), page.events)
        self.assertFalse(page.controls["#city_popup"].visible)

    def test_logistics_service_provider_or_parent_group_is_rejected(self):
        for label in ("物流服务商", "总商"):
            with self.subTest(group=label):
                collector, page, root, option, _, _ = self.collector()
                page.controls[root + " #city_group_label"].text = label
                with self.assertRaisesRegex(BillCollectionError, "必须是物流合作商"):
                    collector._check_agency_context()
                self.assertNotIn(("click", option), page.events)

    def test_group_scope_covering_other_group_is_rejected(self):
        collector, page, root, option, _, _ = self.collector()
        page.controls[root].text += "\n物流服务商\n[31029436] 其他分组"
        with self.assertRaisesRegex(BillCollectionError, "包含其他分组"):
            collector._check_agency_context()
        self.assertNotIn(("click", option), page.events)

    def test_matching_header_without_selected_group_proof_stops(self):
        collector, page, _, option, _, _ = self.collector()
        page.controls[option].click = lambda: page.events.append(("click", option))
        with patch("fengshen_bill.time.monotonic", side_effect=lambda: page.now):
            with self.assertRaisesRegex(BillCollectionError, "分组选中状态未确认"):
                collector._check_agency_context()
        self.assertFalse(any(event == ("click", "#submit_button") for event in page.events))

    def test_selected_group_without_matching_header_stops(self):
        collector, page, _, option, active, _ = self.collector(header_matches=False)
        page.controls[option].click = lambda: setattr(page.controls[active], "matches", 1)
        with patch("fengshen_bill.time.monotonic", side_effect=lambda: page.now):
            with self.assertRaisesRegex(BillCollectionError, "切换或分组选中状态未确认"):
                collector._check_agency_context()

    def test_disabled_target_does_not_fall_back_to_service_provider(self):
        collector, page, _, option, _, wrong = self.collector()
        page.controls[option].is_enabled = lambda: False
        with self.assertRaisesRegex(BillCollectionError, "不会改选物流服务商"):
            collector._check_agency_context()
        self.assertNotIn(("click", wrong), page.events)

    def test_duplicate_selected_cities_stop(self):
        collector, page, _, _, active, _ = self.collector(selected=True)
        page.controls[active].matches = 2
        with self.assertRaisesRegex(BillCollectionError, "应唯一匹配"):
            collector._check_agency_context()

    def test_profile_requires_observed_group_and_selected_state_controls(self):
        for key in ("city_group", "city_group_label", "city_selected_option"):
            profile = fixtures.TargetSelectionTests().profile()
            del profile[key]
            with self.subTest(missing=key), self.assertRaises(BillCollectionError):
                validate_profile(profile)
        profile = fixtures.TargetSelectionTests().profile()
        profile["city_selected_option"] = "first-selected-city"
        with self.assertRaises(BillCollectionError):
            validate_profile(profile)

    def test_header_input_property_is_read_even_without_value_attribute(self):
        collector, page, _, option, _, _ = self.collector(selected=True)
        page.controls["#agency_context"].text = ""
        page.controls["#agency_context"].value = "[31029436][泉州] 测试物流合作商"
        collector._check_agency_context()
        self.assertNotIn(("click", option), page.events)

    def test_known_guide_is_closed_before_city_check_without_opening_feedback(self):
        collector, page, _, _, _, _ = self.collector(selected=True)
        collector.profile["notice_dismiss_button"] = "#notice"
        page.controls["#notice"] = FakeLocator(page, "#notice", text="知道了")
        collector._check_agency_context()
        self.assertEqual(page.events[0], ("click", "#notice"))
        self.assertFalse(any("feedback" in str(event) for event in page.events))

    def test_different_guide_button_text_is_never_clicked(self):
        collector, page, _, _, _, _ = self.collector(selected=True)
        collector.profile["notice_dismiss_button"] = "#notice"
        page.controls["#notice"] = FakeLocator(page, "#notice", text="提工单")
        with self.assertRaisesRegex(BillCollectionError, "文字不符"):
            collector._check_agency_context()
        self.assertFalse(page.events)

    def test_missing_optional_guide_does_not_stop_city_verification(self):
        collector, page, _, _, _, _ = self.collector(selected=True)
        collector.profile["notice_dismiss_button"] = "#notice"
        page.controls["#notice"] = FakeLocator(page, "#notice")
        page.controls["#notice"].matches = 0
        collector._check_agency_context()
        self.assertNotIn(("click", "#notice"), page.events)


    def test_observed_city_close_button_is_used_without_relying_on_escape(self):
        collector, page, _, _, _, _ = self.collector(selected=True)
        collector.profile["city_close"] = "#city_close"
        button = FakeLocator(page, "#city_close")
        button.click = lambda: setattr(page.controls["#city_popup"], "visible", False)
        page.controls["#city_close"] = button
        page.controls["#city_popup"].press = lambda _: self.fail("Should use observed close button")
        collector._check_agency_context()
        self.assertFalse(page.controls["#city_popup"].visible)

    def test_city_switch_dashboard_is_restored_before_form_operations(self):
        collector, page, _, option, _, _ = self.collector()
        original = page.controls[option].click
        def choose():
            original()
            page.url = "https://aeolus.ele.me/#/app/dashboard/index.html"
        page.controls[option].click = choose
        navigations = []
        def goto(url, **kwargs):
            navigations.append(url)
            page.url = url
        page.goto = goto
        page.controls["#agency_context"].wait_for = lambda **kwargs: None
        collector._check_agency_context()
        self.assertEqual(navigations, [collector.page_url])

    def test_city_restore_rejects_lost_target_city(self):
        collector, page, _, _, _, _ = self.collector()
        page.url = "https://aeolus.ele.me/#/app/dashboard/index.html"
        def goto(url, **kwargs):
            page.url = url
            page.controls["#agency_context"].text = "[22476859] 总商"
        page.goto = goto
        page.controls["#agency_context"].wait_for = lambda **kwargs: None
        with patch("fengshen_bill.time.monotonic", side_effect=lambda: page.now), self.assertRaisesRegex(BillCollectionError, "编号发生变化"):
            collector._restore_report_after_city("31029436")

    def test_city_confirmation_precedes_reopened_group_verification(self):
        collector, page, _, option, _, _ = self.collector(header_matches=False)
        collector.profile["city_confirm"] = "#city_confirm"
        original = page.controls[option].click
        def choose():
            original()
            page.controls["#city_popup"].visible = True
            page.controls["#agency_context"].text = "[31029428] 测试城市"
        page.controls[option].click = choose
        button = FakeLocator(page, "#city_confirm")
        def confirm():
            page.events.append(("click", "#city_confirm"))
            page.controls["#agency_context"].text = "[31029436] 测试城市"
            page.controls["#city_popup"].visible = False
        page.controls["#city_confirm"] = button
        button.click = confirm
        collector._check_agency_context()
        self.assertLess(page.events.index(("click", option)), page.events.index(("click", "#city_confirm")))
        self.assertEqual(page.events.count(("click", "#city_trigger")), 2)
        self.assertFalse(page.controls["#city_popup"].visible)

    def test_auto_closing_selection_does_not_click_detached_confirmation(self):
        collector, page, _, option, _, _ = self.collector(header_matches=False)
        collector.profile["city_confirm"] = "#city_confirm"
        page.controls["#city_confirm"] = FakeLocator(page, "#city_confirm", count=0)
        collector._check_agency_context()
        self.assertIn(("click", option), page.events)
        self.assertNotIn(("click", "#city_confirm"), page.events)

    def test_already_selected_city_is_not_confirmed_again(self):
        collector, page, _, _, _, _ = self.collector(selected=True)
        collector.profile["city_confirm"] = "#city_confirm"
        page.controls["#city_confirm"] = FakeLocator(page, "#city_confirm")
        collector._check_agency_context()
        self.assertNotIn(("click", "#city_confirm"), page.events)

    def test_closing_city_popup_cannot_silently_revert_same_report_city(self):
        collector, page, _, _, _, _ = self.collector(selected=True)
        collector.profile["city_close"] = "#city_close"
        button = FakeLocator(page, "#city_close")
        def cancel():
            page.controls["#city_popup"].visible = False
            page.controls["#agency_context"].text = "[31029428] 测试城市"
        button.click = cancel
        page.controls["#city_close"] = button
        with patch("fengshen_bill.time.monotonic", side_effect=lambda: page.now), self.assertRaisesRegex(BillCollectionError, "编号发生变化"):
            collector._check_agency_context()

    def test_city_header_refresh_is_allowed_but_must_reach_target(self):
        collector, page, _, _, _, _ = self.collector(header_matches=False)
        def wait(milliseconds):
            page.now += milliseconds / 1000
            page.controls["#agency_context"].text = "[31029436] 测试城市"
        page.wait_for_timeout = wait
        collector._restore_report_after_city("31029436")
        self.assertGreater(page.now, 0)

    def test_header_disappearing_during_city_refresh_is_not_a_duplicate(self):
        collector, page, _, _, _, _ = self.collector(selected=True)
        header = page.controls["#agency_context"]
        header.matches = 0
        def wait(milliseconds):
            page.now += milliseconds / 1000
            header.matches = 1
        page.wait_for_timeout = wait
        collector._restore_report_after_city("31029436")

    def test_dashboard_redirect_during_header_refresh_restores_report_once(self):
        collector, page, _, _, _, _ = self.collector(selected=True)
        page.controls["#agency_context"].matches = 0
        def wait(milliseconds):
            page.now += milliseconds / 1000
            if page.now < 0.4:
                page.url = "https://aeolus.ele.me/#/app/dashboard/index.html"
        page.wait_for_timeout = wait
        navigations = []
        def goto(url, **kwargs):
            navigations.append(url)
            page.url = url
            page.controls["#agency_context"].matches = 1
        page.goto = goto
        collector._restore_report_after_city("31029436")
        self.assertEqual(navigations, [collector.page_url])


if __name__ == "__main__":
    unittest.main()
