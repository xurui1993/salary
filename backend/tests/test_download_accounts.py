import concurrent.futures
from contextlib import closing
from http.cookies import SimpleCookie
import json
import os
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import patch

from fastapi import HTTPException, Response
from starlette.requests import Request

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import download_accounts as accounts
import download_account_routes as routes


PASSWORD = "synthetic-passphrase-42"


def request(method="GET", *, host="127.0.0.1:3000", origin=None, client="127.0.0.1", token=None,
            body=None, headers=None, scheme="http", content_type="application/json"):
    values = {"host": host, "content-type": content_type, **(headers or {})}
    if method != "GET" and origin is None:
        origin = scheme + "://" + host
    if origin is not None:
        values["origin"] = origin
    if token:
        values["cookie"] = accounts.COOKIE_NAME + "=" + token
    encoded = json.dumps(body if body is not None else {}).encode()
    async def receive():
        return {"type": "http.request", "body": encoded, "more_body": False}
    return Request({"type": "http", "method": method, "scheme": scheme, "path": "/api/fengshen-downloads/account",
                    "query_string": b"", "client": (client, 1234), "server": ("127.0.0.1", 8009),
                    "headers": [(key.encode(), value.encode()) for key, value in values.items()]}, receive)


def complete(coroutine):
    try:
        coroutine.send(None)
    except StopIteration as result:
        return result.value
    finally:
        coroutine.close()
    raise AssertionError("合成路由测试不应等待真实I/O")


class SharedDownloadAccessTests(unittest.TestCase):
    def test_no_cookie_or_credentials_required(self):
        for req in (request(), request(token='obsolete'), request(host='192.168.1.2:3000', client='192.168.1.9')):
            self.assertEqual(accounts.require_account(req)['owner'], 'download_shared')
            self.assertEqual(accounts.require_account(req)['role'], 'admin')

    def test_workspaces_and_cookies_do_not_change_shared_identity(self):
        self.assertEqual(accounts.require_account(request(headers={'x-workspace-id': 'other'})),
                         accounts.require_account(request(token='old-cookie')))

    def test_shared_writes_keep_same_origin_validation(self):
        self.assertEqual(accounts.require_account(request('POST'))['owner'], 'download_shared')
        with self.assertRaises(HTTPException) as error:
            accounts.require_account(request('POST', origin='http://external.invalid'))
        self.assertEqual(error.exception.status_code, 403)

    def test_account_namespace_has_no_routes(self):
        self.assertEqual(routes.router.routes, [])
