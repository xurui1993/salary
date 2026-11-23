from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import binding_platforms as platforms


class BindingPlatformTests(unittest.TestCase):
    def test_normalizes_tianjin_shangyi_and_rejects_invalid_values(self):
        self.assertEqual(platforms.normalized({' 上海 ': '天津商翼'}), {'上海': '商翼'})
        self.assertEqual(platforms.normalized({'广州': '本来人力'}), {'广州': '本来人力'})
        for value in ({'': '商翼'}, {'上海': '未知'}, {'上海': 1}, []):
            with self.assertRaises(ValueError):
                platforms.normalized(value)

    def test_round_trip_and_city_filter(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'binding_platforms.json'
            with patch.object(platforms, 'PATH', path):
                saved = platforms.save({'上海': '商翼', '广州': '本来人力'})
                self.assertEqual(saved, {'上海': '商翼', '广州': '本来人力'})
                self.assertEqual(platforms.load(), saved)
                self.assertEqual(platforms.for_cities(saved, ['上海']), {'上海': '商翼'})
                path.write_text('{"platforms": {"上海": "未知"}}', encoding='utf-8')
                self.assertEqual(platforms.load(), {})


if __name__ == '__main__':
    unittest.main()