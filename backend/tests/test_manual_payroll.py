"""Manual payroll requires both an uploaded template and delivery data."""
import asyncio
import datetime as dt
import gc
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from openpyxl import Workbook, load_workbook

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import processor
import tasks

THEME = {key: ["test {wb_name}"] for key in (
    "msg_start", "msg_awake", "msg_empty", "msg_process", "msg_success", "msg_final", "msg_end",
)}


class ManualPayrollTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(dir=Path(__file__).parent)
        self.addCleanup(self.tmp.cleanup)
        self.addCleanup(gc.collect)
        self.root = Path(self.tmp.name)
        self.source = self.root / "input"
        self.source.mkdir()

    def template(self, name="兼职-template.xlsx"):
        book = Workbook()
        sheet = book.active
        sheet.title = "申请名单"
        sheet.append(["业务城市", "骑手ID", "骑手姓名", "开始日期", "结束日期", "结算类型"])
        sheet.append(["测试城市", "00123", "测试骑手", dt.date(2026, 8, 1), dt.date(2026, 8, 15), "半月结"])
        for name_ in ("配送单", "配送所得", "安全基金", "骑手支付绑定", "问题单", "违规索赔"):
            book.create_sheet(name_)
        path = self.source / name
        book.save(path)
        return path

    def calculate(self, **options):
        results, logs = [], []
        processor.process_rider_data(
            "测试城市", "半月结", str(self.source), "", lambda msg, level: logs.append(msg),
            lambda *_: None, lambda *result: results.append(result), THEME,
            output_root=str(self.root / "output"), **options,
        )
        return results, logs

    def test_template_only_is_rejected_for_ordinary_and_xiaoxiang(self):
        for name in ("兼职-template.XLSX", "小象-template.xlsx"):
            with self.subTest(name=name):
                path = self.template(name)
                results, logs = self.calculate(manual_template_only=True)
                self.assertEqual(results[-1][0], "error", results)
                self.assertIn("配送", results[-1][1])
                path.unlink()

    def test_missing_uploaded_template_does_not_use_system_template(self):
        self.template().rename(self.source / "普通工作簿.xlsx")
        results, _ = self.calculate(manual_template_only=True)
        self.assertEqual(results[-1][0], "error")
        self.assertIn("必须上传 template", results[-1][1])

    def test_template_with_optional_binding_without_delivery_fee(self):
        self.template()
        book = Workbook()
        book.active.append(["骑手ID", "绑定情况"])
        book.active.append(["00123", "已绑定"])
        book.save(self.source / "骑手支付绑定.xlsx")
        results, _ = self.calculate(manual_template_only=True)
        self.assertEqual(results[-1][0], "error", results)
        self.assertIn("配送费", results[-1][1])

    def test_existing_nonmanual_delivery_requirement_is_preserved(self):
        self.template()
        results, _ = self.calculate(strict_inputs=True)
        self.assertEqual(results[-1][0], "error")
        self.assertIn("配送费", results[-1][1])

    def test_task_scheduler_rejects_missing_template(self):
        async def collect():
            return [event async for event in tasks.run_main_calculation_gen(
                "测试城市", "半月结", str(self.source), "", THEME, manual_template_only=True,
            )]
        events = asyncio.run(collect())
        finishes = [json.loads(event[6:]) for event in events if event.startswith("data: ")]
        self.assertEqual(finishes[-1]["status"], "error")
        self.assertIn("必须上传 template", finishes[-1]["result_msg"])

    def test_task_scheduler_passes_manual_mode_for_uploaded_template(self):
        path = self.template()
        def calculate(*args, **kwargs):
            args[6]("success", str(self.root / "output"), {})
        async def collect():
            return [event async for event in tasks.run_main_calculation_gen(
                "测试城市", "半月结", str(self.source), "", THEME,
                taskQueue=[path.name], manual_template_only=True,
            )]
        with patch.object(processor, "process_rider_data", side_effect=calculate) as call:
            asyncio.run(collect())
        self.assertTrue(call.call_args.kwargs["manual_template_only"])


if __name__ == "__main__":
    unittest.main()
