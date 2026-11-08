"""Optional price and binding inputs must not reuse stale template values."""
import datetime as dt
import gc
from pathlib import Path
import sys
import tempfile
import unittest

from openpyxl import Workbook, load_workbook

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import processor


THEME = {key: ["test {wb_name}"] for key in (
    "msg_start", "msg_awake", "msg_empty", "msg_process", "msg_success", "msg_final", "msg_end",
)}


class OptionalPayrollInputsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(dir=Path(__file__).parent)
        self.addCleanup(self.tmp.cleanup)
        self.addCleanup(gc.collect)
        self.root = Path(self.tmp.name)

    def fixture(self, xiaoxiang=False, old_price=88):
        source = self.root / ("xiaoxiang" if xiaoxiang else "ordinary")
        source.mkdir()
        book = Workbook()
        apply = book.active
        apply.title = "申请名单"
        apply.append(["团队名称", "骑手ID", "骑手姓名", "开始日期", "结束日期", "业务城市", "结算类型", "身份证号", "电话号"])
        apply.append(["测试站", "1001", "合成人员", dt.date(2026, 8, 1), dt.date(2026, 8, 2), "测试城市", "半月结", "SYNTHETIC-CARD-001", "SYNTHETIC-PHONE-001"])
        income = book.create_sheet("配送所得表")
        income.append(["测试模板"])
        income.append([])
        income.append(["序号", "团队名称", "骑手ID", "骑手姓名", "蓝橙单价", "备注", "商翼绑定", "收款人身份证号码", "收款人手机号码"])
        income.append([1, "测试站", "1001", "合成人员", old_price, "旧备注", '=IFERROR(1/0,"未绑定")', '=IFERROR(1/0,"")', '=IFERROR(1/0,"")'])
        fund = book.create_sheet("保险费" if xiaoxiang else "安全基金")
        fund.append(["团队名称", "骑手ID", "骑手姓名", "出勤天数"])
        book.create_sheet("配送单")
        binding = book.create_sheet("骑手支付绑定")
        binding.append(["业务城市", "骑手ID", "身份证号", "绑定情况"])
        # Template-resident historical binding data must not constitute a supplied input.
        binding.append(["测试城市", "1001", "SYNTHETIC-CARD-001", "未绑定"])
        filename = "小象-template.xlsx" if xiaoxiang else "兼职-template.xlsx"
        book.save(source / filename)
        book.close()

        if xiaoxiang:
            for day in (1, 2):
                data = Workbook()
                sheet = data.active
                headers = ["骑手ID", "骑手姓名", "所属站点", "配送完成单量"]
                sheet.append(headers)
                sheet.append(headers)
                sheet.append(["1001", "合成人员", "测试站", 3])
                data.save(source / f"配送费_2026-08-{day:02d}.xlsx")
                data.close()
        else:
            data = Workbook()
            sheet = data.active
            sheet.append(["账单时间", "团队ID", "团队名称", "骑手ID", "骑手名称", "详情", "运单号"])
            for day in (1, 2):
                sheet.append([f"2026-08-{day:02d}", "T001", "测试站", "1001", "合成人员", "完成单", f"TEST-WAYBILL-{day}"])
            data.save(source / "配送费.xlsx")
            data.close()
        return source

    def add_price(self, source):
        book = Workbook()
        sheet = book.active
        sheet.title = "兼职价格档案明细"
        sheet.append(["日期", "站点名称", "风神骑手ID", "骑手姓名", "价格", "身份证号"])
        for day in (1, 2):
            sheet.append([f"2026-08-{day:02d}", "测试站", "1001", "合成人员", 7, "SYNTHETIC-CARD-001"])
        book.save(source / "价格档案.xlsx")
        book.close()

    def calculate(self, source, **options):
        results, logs = [], []
        processor.process_rider_data(
            "测试城市", "半月结", str(source), "", lambda msg, *_: logs.append(msg),
            lambda *_: None, lambda *result: results.append(result), THEME,
            output_root=str(source / "output"),
            deductionRules=[{"城市": "测试城市", "团队名称": "测试站", "团队ID": "T001"}],
            strict_inputs=True, **options,
        )
        self.assertEqual(results[-1][0], "success", "\n".join(logs))
        output = Path(results[-1][1])
        main = next(path for path in output.glob("*.xlsx") if "蓝橙无单价&未绑名单" not in path.name)
        special = next(path for path in output.glob("*.xlsx") if "蓝橙无单价&未绑名单" in path.name)
        return load_workbook(main), load_workbook(special), results[-1][2], logs

    def test_ordinary_missing_optional_inputs_show_no_price_and_skip_binding(self):
        for xiaoxiang in (False,):
            with self.subTest(xiaoxiang=xiaoxiang):
                source = self.fixture(xiaoxiang)
                main, special, stats, logs = self.calculate(source, force_no_price=True, skip_binding_check=True)
                try:
                    daily = main["蓝橙单价报备" if xiaoxiang else "日单量"]
                    headers = [cell.value for cell in daily[1]]
                    price_col = headers.index("蓝橙单价")
                    self.assertEqual([row[price_col] for row in daily.iter_rows(min_row=2, values_only=True)], ["无单价", "无单价"])
                    self.assertEqual(main["配送所得表"]["E4"].value, "无单价")
                    self.assertEqual(main["配送所得表"]["G4"].value, "未校验")
                    self.assertEqual(stats["unbound"], 0)
                    self.assertEqual(stats["no_price"], 2)
                    self.assertEqual(special["发薪工具未绑名单"].max_row, 1)
                    self.assertIn("1-2日无单价", special["蓝橙无单价明细"]["D2"].value)
                    self.assertTrue(any("绑定校验已跳过" in log for log in logs))
                    if xiaoxiang:
                        self.assertEqual(main["配送所得表"]["H4"].value, "SYNTHETIC-CARD-001")
                        self.assertEqual(main["配送所得表"]["I4"].value, "SYNTHETIC-PHONE-001")
                finally:
                    main.close()
                    special.close()

    def test_default_flags_continue_to_use_supplied_price_and_check_binding(self):
        source = self.fixture()
        self.add_price(source)
        main, special, stats, _ = self.calculate(source)
        try:
            self.assertEqual(main["配送所得表"]["E4"].value, 7)
            self.assertEqual(stats["no_price"], 0)
            self.assertEqual(stats["unbound"], 1)
            self.assertEqual(special["发薪工具未绑名单"].max_row, 2)
        finally:
            main.close()
            special.close()

    def test_forced_no_price_does_not_match_even_when_legacy_archive_is_present(self):
        source = self.fixture(old_price="=99")
        self.add_price(source)
        main, special, stats, _ = self.calculate(source, force_no_price=True, skip_binding_check=True)
        try:
            self.assertEqual(main["配送所得表"]["E4"].value, "无单价")
            self.assertEqual(stats["no_price"], 2)
            self.assertEqual(stats["unbound"], 0)
        finally:
            main.close()
            special.close()

    def test_price_archive_is_used_when_only_binding_check_is_skipped(self):
        for xiaoxiang in (False,):
            with self.subTest(xiaoxiang=xiaoxiang):
                source = self.fixture(xiaoxiang)
                self.add_price(source)
                main, special, stats, _ = self.calculate(source, skip_binding_check=True)
                try:
                    self.assertEqual(main["配送所得表"]["E4"].value, 7)
                    self.assertEqual(main["配送所得表"]["G4"].value, "未校验")
                    self.assertEqual(stats["no_price"], 0)
                    self.assertEqual(stats["unbound"], 0)
                finally:
                    main.close()
                    special.close()

    def test_missing_price_does_not_skip_requested_binding_check(self):
        source = self.fixture()
        main, special, stats, _ = self.calculate(source, force_no_price=True)
        try:
            self.assertEqual(main["配送所得表"]["E4"].value, "无单价")
            self.assertEqual(stats["no_price"], 2)
            self.assertEqual(stats["unbound"], 1)
            self.assertEqual(special["发薪工具未绑名单"].max_row, 2)
        finally:
            main.close()
            special.close()


if __name__ == "__main__":
    unittest.main()
