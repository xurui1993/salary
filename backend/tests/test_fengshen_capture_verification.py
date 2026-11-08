import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import verify_fengshen_capture as verification


class CaptureVerificationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=Path(__file__).parent)
        self.root = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def flow(self, complete=True, wrong_source=False):
        captures = {}
        for dataset in ("agency_daily", "rider_monthly"):
            folder = self.root / dataset
            folder.mkdir()
            (folder / "sample.zip").write_bytes(b"synthetic")
            controls = folder / "page_controls.json"
            controls.write_text(json.dumps({"observed_dataset": dataset, "downloads": [{
                "status": "saved", "source_dataset": "unknown" if wrong_source else dataset,
                "path": "sample.zip"}]}), encoding="utf-8")
            captures[dataset] = controls.relative_to(self.root).as_posix()
        (self.root / "inspection_flow.json").write_text(json.dumps({
            "inspection_only": True, "complete": complete, "captures": captures}), encoding="utf-8")

    def test_capture_reference_cannot_escape_inspection_directory(self):
        with self.assertRaises(verification.SourceError):
            verification.within(self.root, "../outside.xlsx")

    def test_incomplete_or_unattributed_capture_is_not_validated(self):
        self.flow(complete=False)
        with patch.object(verification, "validate_bill_file") as validate:
            with self.assertRaises(verification.SourceError):
                verification.captured_files(self.root)
            validate.assert_not_called()

    def test_matching_route_does_not_make_unknown_download_source_valid(self):
        self.flow(wrong_source=True)
        with patch.object(verification, "validate_bill_file") as validate:
            with self.assertRaises(verification.SourceError):
                verification.captured_files(self.root)
            validate.assert_not_called()


if __name__ == "__main__":
    unittest.main()
