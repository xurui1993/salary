"""All explicit payroll modes use their verified preparation entry."""
import asyncio
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import main
import payroll_inputs


class TemplatePayrollApiTests(unittest.TestCase):
    def setUp(self):
        preflight = patch("auth_preflight.ensure_ready", lambda *args, **kwargs: None)
        preflight.start()
        self.addCleanup(preflight.stop)

    def test_three_modes_route_to_input_preparation(self):
        for mode in ("manual", "fengshen", "xiaoxiang"):
            with self.subTest(mode=mode):
                calls = []
                async def collect(config, request):
                    calls.append((config.payrollSourceMode, request.headers["x-workspace-id"]))
                    yield 'data: {"type":"finish","status":"success"}\n\n'
                async def run():
                    config = main.ConfigRequest(city="泉州", sourcePath="test-upload", action="core", payrollSourceMode=mode)
                    response = await main.run_calculation(config, SimpleNamespace(headers={"x-workspace-id": "test-owner"}))
                    return [chunk async for chunk in response.body_iterator]
                with patch.object(payroll_inputs, "run_payroll", collect):
                    events = asyncio.run(run())
                self.assertEqual(calls, [(mode, "test-owner")])
                self.assertIn('"status":"success"', events[-1])


if __name__ == "__main__":
    unittest.main()
