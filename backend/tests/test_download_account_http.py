"""Exercise actual loopback HTTP with disposable accounts and no platform calls."""
from http.cookiejar import CookieJar
import json
import os
from pathlib import Path
import socket
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import build_opener, HTTPCookieProcessor, Request

from fastapi import FastAPI
import uvicorn

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import download_accounts as accounts
import download_account_routes as routes
from legacy_download_boundary import LegacyDownloadBoundary


class DownloadAccountHttpTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        private = self.root / "backend/.local_downloads"
        private.mkdir(parents=True)
        (private / "protected_roots.json").write_text(json.dumps({"roots": []}), encoding="utf-8")
        self.store = accounts.AccountStore(private / "accounts.sqlite3")
        for module in (accounts,):
            mocked = patch.object(module, "get_account_store", return_value=self.store)
            mocked.start()
            self.addCleanup(mocked.stop)
        for mocked in (patch.object(accounts, "PASSWORD_ITERATIONS", 1000),
                       patch.dict(os.environ, {"FENGSHEN_DOWNLOAD_PROXY_SECRET": "synthetic-http-proxy-secret"})):
            mocked.start()
            self.addCleanup(mocked.stop)
        app = FastAPI()
        app.add_middleware(LegacyDownloadBoundary, root=self.root)
        app.include_router(routes.router)
        @app.post("/api/run")
        def legacy_run():
            return {"ok": True}
        listener = socket.socket()
        listener.bind(("127.0.0.1", 0))
        self.base = f"http://127.0.0.1:{listener.getsockname()[1]}"
        self.server = uvicorn.Server(uvicorn.Config(app, log_level="critical", access_log=False))
        thread = threading.Thread(target=lambda: self.server.run(sockets=[listener]), daemon=True)
        thread.start()
        def stop():
            self.server.should_exit = True
            thread.join(5)
            listener.close()
            self.assertFalse(thread.is_alive(), "temporary HTTP server must finish")
        self.addCleanup(stop)
        deadline = time.monotonic() + 5
        while not self.server.started and thread.is_alive() and time.monotonic() < deadline:
            time.sleep(.01)
        self.assertTrue(self.server.started)
        self.browser = build_opener(HTTPCookieProcessor(CookieJar()))

    def call(self, route, *, body=None, method=None, browser=None, headers=None):
        values = {"Content-Type": "application/json", "Connection": "close", **(headers or {})}
        if body is not None:
            values.setdefault("Origin", self.base)
        request = Request(self.base + route, data=json.dumps(body).encode() if body is not None else None,
                          method=method, headers=values)
        try:
            with (browser or self.browser).open(request, timeout=5) as response:
                return response.status, json.load(response), response.headers
        except HTTPError as error:
            try:
                return error.code, json.load(error), error.headers
            finally:
                error.close()

    def test_login_and_user_management_are_unavailable_over_real_http(self):
        prefix = "/api/fengshen-downloads/account"
        for route in ("status", "users", "audit"):
            self.assertEqual(self.call(prefix + "/" + route)[0], 404)
        for route in ("bootstrap", "login", "logout", "users"):
            self.assertEqual(self.call(prefix + "/" + route, method="POST")[0], 404)
        self.assertEqual(self.call("/api/run", body={"sourcePath": str(self.root / "backend/.local_downloads")})[0], 403)
        self.assertEqual(self.call("/api/run", body={"sourcePath": str(self.root / "uploads/a")})[0], 200)
