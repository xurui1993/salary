import base64
import io
import sys
from pathlib import Path
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

from openpyxl import Workbook, load_workbook

sys.path.insert(0, str(Path(__file__).parents[1]))
from fengshen_http import FengshenHttpClient, GOODS_RENT_URL
from fengshen_http_riders import RiderHttpCollector, GOODS_RENT_HEADERS
from rider_sources import TEAMS_URL

TEAMS = {"result": {"data": [
    {"id": 917580497, "agencyId": 31030116, "team_name": "深圳麻豆人-平湖南站_新专送"},
    {"id": 917580500, "agencyId": 31030116, "team_name": "深圳麻豆人-佳漾汇站（取分离）"},
]}}
PLAN = SimpleNamespace(city="深圳", agency_id="31030116", start="2026-10-01",
                       end="2026-10-22", month="2026-10")


def rent_workbook(rows):
    book = Workbook(write_only=True)
    sheet = book.create_sheet()
    sheet.append(list(GOODS_RENT_HEADERS))
    for row in rows:
        sheet.append(row)
    buffer = io.BytesIO()
    book.save(buffer)
    book.close()
    return base64.b64encode(buffer.getvalue()).decode()


ROWS = [["深圳麻豆人-平湖南站_新专送", "917580497", "邓子迪", "1111130318", "15171558368", "租用", "住宿", "1.0", "2026-10-09至2026-12-31", "孙坤", "", "进行中"],
        ["深圳麻豆人-佳漾汇站（取分离）", "917580500", "王五", "2222222222", "15100000000", "租用", "电动车", "1.0", "2026-10-01至2026-12-31", "孙坤", "", "进行中"]]


class GoodsRentTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=Path(__file__).parent)
        self.root = Path(self.temp.name)
        self.client = Mock(spec=FengshenHttpClient, cancelled=threading.Event())
        self.collector = RiderHttpCollector(self.client)
        self.collector.scope_recheck_delay = 0

    def tearDown(self):
        self.temp.cleanup()

    def collect(self, include, rows=None):
        # 真实接口只返回所请求站点的记录：夹具按勾选方向构造对应导出内容。
        if rows is None:
            rows = [ROWS[1]] if include else [ROWS[0]]
        self.client.request_json = Mock(side_effect=[TEAMS, {"result": {"data": rent_workbook(rows)}}])
        return self.collector.goods_rent(SimpleNamespace(**vars(PLAN), include_separation=include), self.root)

    def test_include_keeps_only_separation_stations(self):
        result = self.collect(True)
        body = self.client.request_json.call_args_list[1].kwargs["body"]
        self.assertEqual(body["params"]["goodsBusinessRentQueryDto"]["teamIds"], [917580500])
        self.assertEqual(result["rows"], 1)
        self.assertEqual(result["status"], "validated")
        self.assertEqual(result["separation_mode"], "include")
        book = load_workbook(self.root / result["path"], read_only=True)
        rows = list(book.worksheets[0].iter_rows(values_only=True))
        book.close()
        self.assertEqual(rows[1][0], "深圳麻豆人-佳漾汇站（取分离）")

    def test_exclusion_option_requests_all_teams_unless_checked(self):
        for exclude in (False,True):
            self.client.request_json=Mock(side_effect=[TEAMS,{'result':{'data':rent_workbook([ROWS[0]] if exclude else ROWS)}}])
            result=self.collector.goods_rent(SimpleNamespace(**vars(PLAN),exclude_separation=exclude),self.root)
            body=self.client.request_json.call_args_list[1].kwargs['body']
            self.assertEqual(body['params']['goodsBusinessRentQueryDto']['teamIds'],[917580497] if exclude else [917580497,917580500])
            self.assertEqual(result['rows'],1 if exclude else 2)
            self.assertEqual(result['separation_mode'],'exclude' if exclude else 'all')

    def test_exclude_removes_separation_stations(self):
        result = self.collect(False)
        body = self.client.request_json.call_args_list[1].kwargs["body"]
        self.assertEqual(body["params"]["goodsBusinessRentQueryDto"]["teamIds"], [917580497])
        self.assertEqual(result["rows"], 1)
        self.assertEqual(result["separation_mode"], "exclude")

    def test_empty_station_set_yields_empty_workbook(self):
        result = self.collect(True, rows=[])  # 平台返回空导出
        self.assertEqual(result["status"], "empty")
        self.assertEqual(result["rows"], 0)
        book = load_workbook(self.root / result["path"], read_only=True)
        rows = list(book.worksheets[0].iter_rows(values_only=True))
        book.close()
        self.assertEqual(rows, [tuple(GOODS_RENT_HEADERS)])

    def test_foreign_station_rows_are_rejected(self):
        self.client.request_json = Mock(side_effect=[TEAMS, {"result": {"data": rent_workbook([
            ROWS[0], ["深圳麻豆人-外来站", "999", "李四", "3333", "1511", "租用", "住宿", "1.0", "x", "y", "", "进行中"]])}}])
        from fengshen_http import HttpTransportError
        with self.assertRaises(HttpTransportError):
            self.collector.goods_rent(SimpleNamespace(**vars(PLAN), include_separation=False), self.root)

    def test_export_endpoint_registered(self):
        self.client.request_json = Mock(side_effect=[TEAMS, {"result": {"data": rent_workbook(ROWS)}}])
        self.collect(True)
        self.assertEqual(self.client.request_json.call_args_list[1].args[1], GOODS_RENT_URL)
        self.client.assert_city.assert_called_once()


if __name__ == '__main__':
    unittest.main()
