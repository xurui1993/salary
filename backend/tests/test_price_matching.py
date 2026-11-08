from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from price_matching import UniqueNamePrices, match_daily_price, price_rider_column, record_daily_name


class DailyPriceTests(unittest.TestCase):
    def setUp(self):
        self.names = UniqueNamePrices()
        self.ids, self.cards = {}, {}
        self.date, self.station = "2026-08-16", "West Station"
        self.key = f"{self.date}_{self.station}_Same Name"

    def lookup(self, **kwargs):
        return match_daily_price(self.date, self.station, "1001", "Same Name",
                                 kwargs.pop("idcards", ("CARD-A", "CARD-B")),
                                 self.ids, self.cards, self.names, **kwargs)

    def test_fengshen_id_column_wins_regardless_of_header_order(self):
        self.assertEqual(price_rider_column(["骑手ID", "姓名", "风神骑手ID"]), 2)
        self.assertEqual(price_rider_column(["风神骑手id", "骑手ID"]), 0)
        self.assertEqual(price_rider_column(["姓名", "骑手ID"]), 1)
        self.assertIsNone(price_rider_column(["姓名", "日期"]))

    def test_missing_daily_price_returns_unmatched_without_using_other_dates(self):
        self.ids[f"2026-08-15_{self.station}_1001"] = "6"
        self.assertEqual(self.lookup(), (None, "", ""))

    def test_rider_id_is_preferred_to_card_or_name(self):
        self.ids[f"{self.date}_{self.station}_1001"] = "7"
        self.cards[f"{self.date}_{self.station}_CARD-A"] = "6"
        self.names.add(self.key, "5", ("card", "CARD-A"))
        value, strategy, card = self.lookup()
        self.assertEqual(value, "7")
        self.assertIn("风神骑手ID", strategy)
        self.assertEqual(card, "")

    def test_binding_card_is_tried_when_an_earlier_card_has_no_price(self):
        self.cards[f"{self.date}_{self.station}_CARD-B"] = "6"
        self.names.add(self.key, "5", ("card", "OTHER"))
        value, strategy, card = self.lookup()
        self.assertEqual((value, card), ("6", "CARD-B"))
        self.assertIn("身份证", strategy)

    def test_unique_name_is_only_last_fallback(self):
        self.names.add(self.key, "6", ("card", "CARD-A"))
        value, strategy, _ = self.lookup()
        self.assertEqual(value, "6")
        self.assertIn("骑手姓名", strategy)

    def test_different_people_with_same_name_are_rejected_even_at_same_price(self):
        self.names.add(self.key, "6", ("card", "CARD-A"))
        self.names.add(self.key, "6", ("card", "CARD-B"))
        self.assertEqual(self.lookup(), (None, "", ""))

    def test_missing_price_on_second_person_still_makes_name_ambiguous(self):
        self.names.add(self.key, "6", ("card", "CARD-A"))
        self.names.add(self.key, "", ("card", "CARD-B"))
        self.assertEqual(self.lookup(), (None, "", ""))

    def test_name_uniqueness_is_scoped_to_date_and_station(self):
        self.names.add(self.key, "6", ("card", "CARD-A"))
        self.names.add(f"2026-08-17_{self.station}_Same Name", "7", ("card", "CARD-B"))
        self.names.add(f"{self.date}_East Station_Same Name", "8", ("card", "CARD-B"))
        self.assertEqual(self.lookup()[0], "6")

    def test_repeated_same_person_and_equivalent_price_remain_unique(self):
        self.names.add(self.key, "6", ("card", "CARD-A"))
        self.names.add(self.key, "6.0", ("card", "CARD-A"))
        self.assertEqual(self.lookup()[0], "6")

    def test_conflicting_prices_cannot_be_silently_overwritten(self):
        for value in ("6", "7", "6"):
            self.names.add(self.key, value, ("card", "CARD-A"))
        self.assertEqual(self.lookup(), (None, "", ""))

    def test_duplicate_anonymous_rows_do_not_prove_unique_identity(self):
        self.names.add(self.key, "6")
        self.names.add(self.key, "6")
        self.assertEqual(self.lookup(), (None, "", ""))

    def test_exact_rider_id_can_match_despite_ambiguous_name(self):
        self.names.add(self.key, "6", ("card", "CARD-A"))
        self.names.add(self.key, "7", ("card", "CARD-B"))
        self.ids[f"{self.date}_{self.station}_1001"] = "8"
        self.assertEqual(self.lookup()[0], "8")

    def test_nonunique_delivery_name_cannot_use_unique_archive_name(self):
        self.names.add(self.key, "6", ("card", "CARD-A"))
        self.assertEqual(self.lookup(name_is_unique=False), (None, "", ""))
        self.ids[f"{self.date}_{self.station}_1001"] = "8"
        self.assertEqual(self.lookup(name_is_unique=False)[0], "8")

    def test_delivery_name_scope_retains_nonapplicant_riders(self):
        groups = {}
        record_daily_name(groups, self.date, self.station, "Same Name", "1001")
        record_daily_name(groups, self.date, self.station, "Same Name", "2002")
        self.assertEqual(groups[(self.date, "WestStation", "Same Name")], {"1001", "2002"})

    def test_delivery_name_scope_normalizes_station_and_separates_dates(self):
        groups = {}
        record_daily_name(groups, self.date, " West Station ", " Same Name ", "1001.0")
        record_daily_name(groups, self.date, "WestStation", "Same Name", "1001")
        record_daily_name(groups, "2026-08-17", "WestStation", "Same Name", "2002")
        self.assertEqual(groups[(self.date, "WestStation", "Same Name")], {"1001"})

    def test_invalid_zero_or_nonfinite_price_remains_unmatched(self):
        for value in ("", "0", "nan", "Infinity", "pending"):
            with self.subTest(value=value):
                self.ids[f"{self.date}_{self.station}_1001"] = value
                self.assertEqual(self.lookup(), (None, "", ""))

    def test_station_keyword_fallback_is_preserved(self):
        self.cards[f"{self.date}_Short Station_CARD-B"] = "6"
        value, strategy, card = self.lookup(alternate_station="Short Station")
        self.assertEqual((value, card), ("6", "CARD-B"))
        self.assertIn("关键字", strategy)

    def test_xiaoxiang_card_precedence_can_be_preserved(self):
        self.ids[f"{self.date}_{self.station}_1001"] = "7"
        self.cards[f"{self.date}_{self.station}_CARD-A"] = "6"
        self.assertEqual(self.lookup(prefer_idcard=True)[0], "6")


if __name__ == "__main__":
    unittest.main()
