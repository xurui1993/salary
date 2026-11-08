import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from fengshen_bill import validate_bill_file
from parttime_source import SourceError
from test_fengshen_bill import workbook_bytes
from verify_fengshen_acceptance import accepted_file


class AcceptanceVerificationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=Path(__file__).parent)
        self.root = Path(self.temp.name) / "run"
        self.root.mkdir()
        self.plan = SimpleNamespace(agency_id="31029436", start="2026-08-16", end="2026-08-31", month="2026-08")
        self.file = self.root / "bill.xlsx"
        self.file.write_bytes(workbook_bytes())
        self.manifest = {"status": "success", "acceptance_only": True, "payroll_executed": False,
                         "production_profile_enabled": False, "dataset": "rider_monthly", "agency_id": "31029436",
                         "merchant_group": "物流合作商", "month": "2026-08", "bill_status": "all",
                         "files": [{"path": "bill.xlsx", **validate_bill_file(self.file)}]}
        self.proof = {"header_ids": ["31029436"], "groups": [{"label": "物流合作商", "options":
                     [{"agencyId": "31029436", "selected": True}]}, {"label": "物流服务商", "options": []}]}
        self.diagnostics = self.root.with_name("run-diagnostics")
        self.diagnostics.mkdir()

    def tearDown(self):
        self.temp.cleanup()

    def write(self):
        (self.root / "manifest.json").write_text(json.dumps(self.manifest), encoding="utf-8")
        for phase in ("selected_before_close", "confirmed_after_close"):
            (self.diagnostics / f"city_31029436_{phase}.json").write_text(json.dumps(self.proof), encoding="utf-8")

    def test_success_requires_scoped_city_proof_and_original_download_hash(self):
        self.write()
        self.assertEqual(accepted_file(self.root, "rider_monthly", self.plan), self.file)

    def test_manual_inspection_cannot_be_marked_automatic_success(self):
        self.manifest["acceptance_only"] = False
        self.write()
        with self.assertRaises(SourceError):
            accepted_file(self.root, "rider_monthly", self.plan)

    def test_wrong_group_or_ambiguous_selected_city_stops_verification(self):
        self.proof["groups"][1]["options"] = [{"agencyId": "31029436", "selected": True}]
        self.write()
        with self.assertRaisesRegex(SourceError, "物流合作商唯一选中"):
            accepted_file(self.root, "rider_monthly", self.plan)

    def test_modified_file_cannot_pass_original_manifest(self):
        self.manifest["files"][0]["sha256"] = "0" * 64
        self.write()
        with self.assertRaisesRegex(SourceError, "原始清单"):
            accepted_file(self.root, "rider_monthly", self.plan)


if __name__ == "__main__":
    unittest.main()
