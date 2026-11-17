import csv
import sys
import tempfile
import threading
from pathlib import Path
from types import SimpleNamespace
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from fengshen_bill import BillCollectionError
import batch_detail


HEADER = ["日期", "骑手ID", "团队ID", "团队名称", "有效完成单"]


class FakeClient:
    def __init__(self, rows):
        self.rows = rows
        self.cities = []

    def checkpoint(self):
        pass

    def select_city(self, agency):
        self.cities.append(agency)

    def request_json(self, method, url, params=None, body=None):
        return {"data": {"totalCount": 1}}

    def download_request(self, method, url, target, params=None, body=None):
        with Path(target).open("w", encoding="utf-8-sig", newline="") as stream:
            writer = csv.writer(stream)
            writer.writerow(HEADER)
            writer.writerows(self.rows)


class FakeCollector:
    def __init__(self, teams):
        self.teams = teams

    def _teams(self, plan):
        values = self.teams[plan.city]
        return values, {key: plan.agency_id for key in values}

    def _fields(self):
        return ["validCompleteCount"]


class FakeAccountClient(FakeClient):
    def __init__(self, rows, accounts):
        super().__init__(rows)
        self.accounts = accounts

    def request_json(self, method, url, params=None, body=None):
        if url.endswith("queryReceiveAccount"):
            return {"data": {"datas": self.accounts, "rowcount": len(self.accounts)}}
        return {"data": {"totalCount": 1}}


class BatchDetailTests(unittest.TestCase):
    def plans(self):
        return [SimpleNamespace(city="泉州", agency_id="1", start="2026-10-01", end="2026-10-03", month="2026-10"),
                SimpleNamespace(city="上海", agency_id="2", start="2026-10-01", end="2026-10-03", month="2026-10")]

    def test_batch_export_splits_by_team_and_writes_receipts(self):
        teams = {"泉州": {"100": "泉州站"}, "上海": {"200": "上海站"}}
        rows = []
        for day in ("2026-10-01", "2026-10-02", "2026-10-03"):
            rows.append([day, "001", "100", "泉州站", 5])
            rows.append([day, "002", "200", "上海站", 3])
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as directory:
            paths = batch_detail.collect_batch_detail(
                FakeClient(rows), FakeCollector(teams), self.plans(), Path(directory),
                lambda *_: None, threading.Event())
            self.assertEqual(set(paths), {("泉州", "2026-10"), ("上海", "2026-10")})
            for city, path in paths.items():
                self.assertTrue(path.is_file())
                receipt = path.parent / "source_receipt.json"
                self.assertTrue(receipt.is_file())
            self.assertTrue((Path(directory) / "原始资料" / "支付绑定平台表" / "明细批量" / "2026-10"
                             / "batch_detail.json").is_file())


    def test_groups_keep_team_count_under_platform_limit(self):
        plans = [SimpleNamespace(city=name) for name in ('A', 'B', 'C')]
        scopes = {name: (plan, {name + str(index): '站点' for index in range(30)}, {})
                  for name, plan in zip(('A', 'B', 'C'), plans)}
        totals = {'A': 1000, 'B': 1000, 'C': 1000}
        groups = batch_detail._groups(plans, scopes, totals)
        self.assertEqual([[plan.city for plan in group] for group in groups], [['A'], ['B'], ['C']])

    def test_unknown_team_rejects_the_whole_batch(self):
        teams = {"泉州": {"100": "泉州站"}, "上海": {"200": "上海站"}}
        rows = [["2026-10-01", "001", "100", "泉州站", 5],
                ["2026-10-01", "002", "999", "未知站", 3]]
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as directory:
            with self.assertRaises(BillCollectionError):
                batch_detail.collect_batch_detail(
                    FakeClient(rows), FakeCollector(teams), self.plans(), Path(directory),
                    lambda *_: None, threading.Event())
            self.assertFalse(list((Path(directory) / "原始资料").glob("*/payment_binding/*/rider_detail/骑手数据明细_*.csv")))

    def test_partial_batch_coverage_is_rejected(self):
        teams = {"泉州": {"100": "泉州站"}, "上海": {"200": "上海站"}}
        rows = [["2026-10-01", "001", "100", "泉州站", 5],
                ["2026-10-01", "002", "200", "上海站", 3]]
        plans = self.plans()
        for plan in plans:
            plan.end = "2026-10-10"
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as directory:
            with self.assertRaises(BillCollectionError):
                batch_detail.collect_batch_detail(
                    FakeClient(rows), FakeCollector(teams), plans, Path(directory),
                    lambda *_: None, threading.Event())

    def test_rider_info_batch_splits_by_department_and_rejects_unknown(self):
        from openpyxl import Workbook, load_workbook
        plans = self.plans()
        scopes = {plan.city: (plan, {"100" if plan.city == "泉州" else "200":
                                     "泉州站" if plan.city == "泉州" else "上海站"}, {})
                  for plan in plans}
        header = ["骑手ID", "姓名", "部门", "身份证", "状态"]
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as directory:
            root = Path(directory)
            source = root / "batch.xlsx"
            book = Workbook(); sheet = book.active
            sheet.append(header)
            sheet.append([1, "甲", "泉州站", "110101199001011234", "在职"])
            sheet.append([2, "乙", "上海站", "310101199001011234", "在职"])
            book.save(source); book.close()
            paths = batch_detail._split_rider_info(source, plans, scopes, root, 2)
            self.assertEqual(set(paths), {"泉州", "上海"})
            for city, path in paths.items():
                self.assertTrue(path.is_file())
                self.assertTrue((path.parent / "source_receipt.json").is_file())
            work = load_workbook(paths["泉州"], read_only=True, data_only=True)
            rows = list(work.worksheets[0].iter_rows(values_only=True))
            work.close()
            self.assertEqual(rows[0], tuple(header))
            self.assertEqual(len(rows), 2)

            bad = root / "bad.xlsx"
            book = Workbook(); sheet = book.active
            sheet.append(header)
            sheet.append([3, "丙", "未知站", "110101199001011234", "在职"])
            book.save(bad); book.close()
            with self.assertRaises(BillCollectionError):
                batch_detail._split_rider_info(bad, plans, scopes, root, 1)

    def test_slow_account_query_is_logged(self):
        import itertools
        from unittest.mock import patch
        teams = {"泉州": {"100": "泉州站"}}
        rows = [["2026-10-01", "001", "100", "泉州站", 5]]
        accounts = [{"teamId": 100, "teamName": "泉州站", "knightId": 1, "receiveType": 1,
                     "receiveAccount": "180****9801", "receiveAccountName": "张三",
                     "receiveAccountCertificateNum": "**************6936"}]
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as directory:
            logs = []
            counter = itertools.count()
            with patch('batch_detail.time.perf_counter', side_effect=lambda: next(counter) * 1.5):
                batch_detail.collect_batch_detail(
                    FakeAccountClient(rows, accounts), FakeCollector(teams), self.plans()[:1],
                    Path(directory), logs.append, threading.Event())
            slow = next(line for line in logs if line.startswith("[慢] 泉州"))
            self.assertIn("切城", slow)
            self.assertIn("分页查询", slow)
            self.assertIn("429 重试 0 次", slow)

    def test_city_mismatch_retries_once_after_reselect(self):
        calls = []
        class Client:
            def select_city(self, agency):
                calls.append(("select", agency))
        def action():
            calls.append("action")
            if calls.count("action") == 1:
                from fengshen_http import HttpTransportError
                raise HttpTransportError("平台当前城市与所选城市不一致，已停止下载")
            return "ok"
        self.assertEqual(batch_detail._retry_city_mismatch(Client(), "2", action), "ok")
        self.assertEqual(calls, ["action", ("select", "2"), "action"])

    def test_other_export_errors_are_not_retried(self):
        calls = []
        class Client:
            def select_city(self, agency):
                calls.append("select")
        def action():
            calls.append("action")
            from fengshen_http import HttpTransportError
            raise HttpTransportError("同步导出未完成，已保留提交记录")
        with self.assertRaises(Exception):
            batch_detail._retry_city_mismatch(Client(), "2", action)
        self.assertEqual(calls, ["action"])

    def test_account_query_is_saved_per_city_with_masked_values(self):
        from openpyxl import load_workbook
        teams = {"泉州": {"100": "泉州站"}}
        rows = [["2026-10-01", "001", "100", "泉州站", 5]]
        accounts = [{"teamId": 100, "teamName": "泉州站", "knightId": 1, "receiveType": 1,
                     "receiveAccount": "180****9801", "receiveAccountName": "张三",
                     "receiveAccountCertificateNum": "**************6936"}]
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as directory:
            paths = {}
            batch_detail.collect_batch_detail(
                FakeAccountClient(rows, accounts), FakeCollector(teams), self.plans()[:1],
                Path(directory), lambda *_: None, threading.Event(), paths)
            path = paths[("泉州", "2026-10")]
            book = load_workbook(path, read_only=True, data_only=True)
            sheet = book.worksheets[0]
            sheet.reset_dimensions()
            values = list(sheet.iter_rows(values_only=True))
            book.close()
            self.assertEqual(values[0], tuple(batch_detail.ACCOUNT_HEADERS))
            self.assertEqual(values[1], (100, "泉州站", 1, "支付宝", "180****9801", "张三",
                                         "**************6936"))
            receipt = path.parent / "source_receipt.json"
            self.assertTrue(receipt.is_file())


def test_account_xlsx_keeps_trailing_blank_columns(self):
        from rider_sources import validate_document
        rows = [[100, "泉州站", 1, "支付宝", "180****9801", "", ""]]
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as directory:
            path = Path(directory) / "account.xlsx"
            batch_detail._write_account_xlsx(path, rows)
            info = validate_document(path, "receive_account", self.plans()[0], {})
            self.assertEqual(info["rows"], 1)
            self.assertEqual(info["identity_masked"], 1)
            self.assertEqual(info["identity_blank"], 1)


if __name__ == "__main__":
    unittest.main()