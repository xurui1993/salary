import asyncio
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from legacy_download_boundary import LegacyDownloadBoundary


class LegacyBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name) / "project"
        self.historic = Path(self.directory.name) / "old-archive"
        self.registry = self.root / "backend/.local_downloads/protected_roots.json"
        self.registry.parent.mkdir(parents=True)
        self.registry.write_text(json.dumps({"roots": [str(self.historic)]}), encoding="utf-8")
        self.boundary = LegacyDownloadBoundary(None, self.root)

    def test_sensitive_default_and_historical_paths_are_not_legacy_files(self):
        for path in (self.root / "backend/.local_downloads/accounts.sqlite3", self.root / "backend/.local_auth/fengshen.dpapi",
                     self.root / "outputs/fengshen_downloads/2026-10/a.csv", self.historic / "city/a.csv"):
            self.assertFalse(self.boundary.allowed_path(path))
        self.assertTrue(self.boundary.allowed_path(str(self.historic) + "-sibling/a.csv"))

    def test_personal_instance_rejects_colleague_and_parent_paths(self):
        from unittest.mock import patch
        with patch.dict('os.environ', {'PERSONAL_INSTANCE_ROOT': str(self.root)}):
            self.assertFalse(self.boundary.allowed_path(self.root.parent / 'colleague/data/config.json'))
            self.assertFalse(self.boundary.allowed_path(self.root.parent))
            self.assertTrue(self.boundary.allowed_path(self.root / 'data/config.json'))

    def test_recursive_parent_and_code_replacement_are_refused(self):
        outputs = str(self.root / "outputs")
        self.assertTrue(self.boundary.body_allowed({"path": outputs}, "/api/files"))
        self.assertFalse(self.boundary.body_allowed({"path": outputs}, "/api/files_tree"))
        self.assertFalse(self.boundary.body_allowed({"path": outputs, "action": "delete"}, "/api/action_file"))
        self.assertTrue(self.boundary.body_allowed({"basePath": outputs, "sourcePath": str(self.root / "uploads/a")}, "/api/run"))
        self.assertFalse(self.boundary.allowed_path(self.root / "backend/main.py", write=True))
        self.assertFalse(self.boundary.allowed_path(self.root / "dist/server.cjs", write=True))
        self.assertTrue(self.boundary.allowed_path(self.root / "uploads/a/template.xlsx", write=True))

    def test_nested_tasks_obey_boundary_and_registry_failure_is_closed(self):
        self.assertFalse(self.boundary.body_allowed({"taskQueue": [{"sourcePath": str(self.historic)}]}, "/api/run"))
        self.registry.write_text("broken", encoding="utf-8")
        self.assertFalse(self.boundary.allowed_path(self.root / "uploads/a"))
        self.registry.unlink()
        self.assertFalse(self.boundary.allowed_path(self.root / "uploads/a"))

    def test_registry_refresh_is_observed_without_restart(self):
        other = Path(self.directory.name) / "new-archive"
        self.assertTrue(self.boundary.allowed_path(other))
        self.registry.write_text(json.dumps({"roots": [str(other)]}), encoding="utf-8")
        self.assertFalse(self.boundary.allowed_path(other))

    def invoke(self, *, route="/api/run", body=None, owner="ordinary", query="", method="POST"):
        async def run():
            calls = []
            messages = []
            async def app(scope, receive, send):
                calls.append((await receive()).get("body", b""))
                await send({"type": "http.response.start", "status": 200, "headers": []})
                await send({"type": "http.response.body", "body": b"ok"})
            async def receive():
                return {"type": "http.request", "body": json.dumps(body or {}).encode(), "more_body": False}
            async def send(message):
                messages.append(message)
            middleware = LegacyDownloadBoundary(app, self.root)
            await middleware({"type": "http", "path": route, "method": method, "query_string": query.encode(),
                "headers": [(b"x-workspace-id", owner.encode()), (b"content-type", b"application/json")]}, receive, send)
            return messages[0]["status"], calls
        return asyncio.run(run())

    def test_asgi_rejects_header_or_query_reserved_namespace_before_worker(self):
        for owner in ("account_" + "a" * 32, "%61ccount_" + "a" * 32, "ACCOUNT_" + "a" * 32):
            status, calls = self.invoke(owner=owner)
            self.assertEqual(status, 403)
            self.assertEqual(calls, [])
        self.assertEqual(self.invoke(owner="", query="workspace_id=account_" + "a" * 32)[0], 403)

    def test_asgi_rejects_protected_path_and_replays_ordinary_json_unchanged(self):
        status, calls = self.invoke(body={"sourcePath": str(self.historic)})
        self.assertEqual(status, 403)
        self.assertEqual(calls, [])
        body = {"sourcePath": str(self.root / "uploads/a"), "city": "synthetic"}
        status, calls = self.invoke(body=body)
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(calls[0]), body)

    def test_authenticated_routes_keep_their_own_cookie_authorization(self):
        status, calls = self.invoke(route="/api/fengshen-downloads/runs", owner="account_" + "a" * 32)
        self.assertEqual(status, 200)
        self.assertEqual(len(calls), 1)


if __name__ == "__main__":
    unittest.main()
