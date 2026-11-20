import unittest

from station_names import station_code, station_core, station_key, station_match


class StationNameTests(unittest.TestCase):
    def test_code_takes_priority_over_station_word_variants(self):
        self.assertEqual(station_code("小象超市-云梯店-CZ4001"), "CZ4001")
        self.assertEqual(station_key("小象超市-云梯店-CZ4001"), "CZ4001")
        self.assertTrue(station_match("小象超市-云梯店-CZ4001", "小象超市-云梯站-CZ4001"))

    def test_core_name_handles_prefix_suffix_and_spaces(self):
        self.assertEqual(station_core(" 小象超市-马安站-HZ1010 "), "马安站")
        self.assertEqual(station_core("惠州金山湖站"), "金山湖站")
        self.assertTrue(station_match("惠州金山湖站", "金山湖站"))
        self.assertTrue(station_match(" 小象超市-潮南站-ST0006 ", "小象超市-潮南站"))

    def test_different_stations_never_match(self):
        self.assertFalse(station_match("小象超市-云梯站-CZ4001", "小象超市-荣盛站-CZ4002"))
        self.assertFalse(station_match("惠州金山湖站", "马安站"))