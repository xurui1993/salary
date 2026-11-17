import sys
import tempfile
from pathlib import Path
from unittest.mock import Mock, patch
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import binding_source_auth as source


class SourceCredentialTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=Path(__file__).parent)
        self.root = Path(self.temp.name)
        self.addCleanup(self.temp.cleanup)
        patcher = patch.object(source, "ROOT", self.root)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_prompt_status_never_exposes_password_and_save_is_encrypted(self):
        auth = source.SourceAuth()
        auth.pending_credentials["baize"] = {"username": "merchant-001", "password": "synthetic-secret"}
        auth.credential_prompt["baize"] = {"account": source._mask_account("merchant-001")}
        status = auth.status("baize")
        self.assertTrue(status["credential_prompt"])
        self.assertNotIn("password", status)
        self.assertNotIn("synthetic-secret", str(status))
        auth.confirm_credentials("baize", True)
        self.assertFalse(auth.status("baize")["credential_prompt"])
        self.assertEqual(source.load_credentials("baize")["password"], "synthetic-secret")
        raw = source.credentials_path("baize").read_bytes()
        self.assertNotIn(b"synthetic-secret", raw)

    def test_skip_and_logout_clear_credentials(self):
        auth = source.SourceAuth()
        source.save_credentials("benlai", "merchant-002", "synthetic-secret")
        self.assertTrue(source.credentials_path("benlai").exists())
        auth.pending_credentials["benlai"] = {"username": "merchant-002", "password": "synthetic-secret"}
        auth.confirm_credentials("benlai", False)
        self.assertIsNone(source.load_credentials("benlai"))

    def test_recover_uses_saved_credentials_only_after_refresh_fails(self):
        auth = source.SourceAuth()
        source.save_credentials("baize", "merchant-003", "synthetic-secret")
        auth.refresh = Mock(return_value=False)
        auth._auto_login = Mock(return_value=True)
        self.assertTrue(auth.recover("baize"))
        auth._auto_login.assert_called_once()
        auth.auto_login_last.clear()
        auth._auto_login = Mock(return_value=False)
        self.assertFalse(auth.recover("baize"))

    def test_refresh_success_never_attempts_auto_login(self):
        auth = source.SourceAuth()
        source.save_credentials("benlai", "merchant-004", "synthetic-secret")
        auth.refresh = Mock(return_value=True)
        auth._auto_login = Mock(return_value=True)
        self.assertTrue(auth.recover("benlai"))
        auth._auto_login.assert_not_called()


if __name__ == "__main__":
    unittest.main()