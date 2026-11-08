"""Shared internal download access, origin checks, and operation audit.

Legacy account storage is retained for historical data compatibility; local
credential and user-management HTTP endpoints have been removed.
"""

from contextlib import contextmanager
import hashlib
import hmac
import ipaddress
import os
from pathlib import Path
import re
import secrets
import sqlite3
import threading
import time
from urllib.parse import urlparse
import uuid

from fastapi import HTTPException

COOKIE_NAME = "fengshen_download_session"
SESSION_SECONDS = 8 * 60 * 60
PASSWORD_ITERATIONS = 600_000
LOGIN_WINDOW = 15 * 60
LOGIN_LIMIT = 5
_PRIVATE_V4 = tuple(ipaddress.ip_network(value) for value in ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16"))
_PRIVATE_V6 = ipaddress.ip_network("fc00::/7")
_singleton = None
_singleton_lock = threading.Lock()


def _loopback(value):
    try:
        address = ipaddress.ip_address(value)
        if address.version == 6 and address.ipv4_mapped:
            address = address.ipv4_mapped
        return address.is_loopback
    except (ValueError, TypeError):
        return False


def client_address(request):
    """Use proxy identity only with its per-launch secret and loopback peer."""
    peer = request.client.host if request.client else ""
    provided = request.headers.get("x-download-proxy-secret", "")
    if provided:
        expected = os.environ.get("FENGSHEN_DOWNLOAD_PROXY_SECRET", "")
        if not expected or not _loopback(peer) or not hmac.compare_digest(provided, expected):
            raise HTTPException(403, "下载访问来源无效")
        claimed = request.headers.get("x-download-client-address", "")
        try:
            ipaddress.ip_address(claimed)
        except ValueError:
            raise HTTPException(403, "下载访问来源无效") from None
        return claimed
    # A forged forwarded header never turns a LAN client into a local host.
    return peer


def _request_origin(request):
    try:
        host = (request.url.hostname or "").lower()
        if host != "localhost":
            address = ipaddress.ip_address(host)
            allowed = (address.is_loopback or
                       (address.version == 4 and any(address in net for net in _PRIVATE_V4)) or
                       (address.version == 6 and address in _PRIVATE_V6))
            if not allowed or address.is_unspecified or address.is_multicast:
                raise ValueError()
        scheme = request.url.scheme
        if scheme not in ("http", "https"):
            raise ValueError()
        return scheme, host, request.url.port or (443 if scheme == "https" else 80)
    except (ValueError, UnicodeError):
        raise HTTPException(403, "下载模块仅允许本机或局域网 IP 地址访问") from None


def validate_write_request(request):
    """Browser writes require an exact same-origin JSON request."""
    expected = _request_origin(request)
    client_address(request)
    if request.headers.get("content-type", "").split(";", 1)[0].strip().lower() != "application/json":
        raise HTTPException(415, "下载请求必须使用 JSON")
    try:
        value = urlparse(request.headers.get("origin", ""))
        actual = (value.scheme, (value.hostname or "").lower(), value.port or (443 if value.scheme == "https" else 80))
        valid = (value.scheme in ("http", "https") and not value.username and not value.password
                 and value.path in ("", "/") and not value.query and not value.fragment and actual == expected)
    except (ValueError, UnicodeError):
        valid = False
    if not valid:
        raise HTTPException(403, "下载操作必须从当前系统页面发起，地址、协议和端口须一致")


def bootstrap_allowed(request):
    _request_origin(request)
    return _loopback(client_address(request))


def _credentials(username, password):
    if (not isinstance(username, str) or not 2 <= len(username) <= 40
            or any(not char.isalnum() and char not in "_.-" for char in username)):
        raise HTTPException(400, "用户名须为2至40位中英文、数字、下划线、点或短横线")
    if not isinstance(password, str) or not 10 <= len(password) <= 128:
        raise HTTPException(400, "请手动设置10至128位初始密码")
    return username, username.casefold(), password


def _password_hash(password):
    salt = secrets.token_bytes(16)
    value = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, PASSWORD_ITERATIONS)
    return f"pbkdf2_sha256${PASSWORD_ITERATIONS}${salt.hex()}${value.hex()}"


def _password_matches(password, encoded):
    try:
        algorithm, iterations, salt, expected = encoded.split("$")
        count = int(iterations)
        if algorithm != "pbkdf2_sha256" or not 1 <= count <= 2_000_000:
            return False
        actual = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), bytes.fromhex(salt), count)
        return hmac.compare_digest(actual.hex(), expected)
    except (ValueError, TypeError, AttributeError):
        return False


def public_user(user):
    return {key: user[key] for key in ("id", "username", "role")}


def _user(row):
    return {"id": row["id"], "username": row["username"], "role": row["role"],
            "enabled": bool(row["enabled"]), "owner": "account_" + row["id"]}


class AccountStore:
    def __init__(self, db_path):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        with self._connection() as connection:
            connection.executescript("""
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS accounts (
                    id TEXT PRIMARY KEY, username TEXT NOT NULL, username_key TEXT NOT NULL UNIQUE,
                    password_hash TEXT NOT NULL, role TEXT NOT NULL, enabled INTEGER NOT NULL,
                    created_at REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS account_sessions (
                    digest TEXT PRIMARY KEY, user_id TEXT NOT NULL, expires_at REAL NOT NULL);
                CREATE INDEX IF NOT EXISTS account_sessions_user ON account_sessions(user_id);
                CREATE TABLE IF NOT EXISTS login_limits (
                    key TEXT PRIMARY KEY, started_at REAL NOT NULL, failures INTEGER NOT NULL);
                CREATE TABLE IF NOT EXISTS account_audit (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, time REAL NOT NULL,
                    user_id TEXT NOT NULL, username TEXT NOT NULL, action TEXT NOT NULL,
                    run_id TEXT NOT NULL, detail TEXT NOT NULL);
            """)

    @contextmanager
    def _connection(self):
        connection = sqlite3.connect(self.db_path, timeout=15)
        connection.row_factory = sqlite3.Row
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def initialized(self):
        with self._connection() as connection:
            return connection.execute("SELECT 1 FROM accounts LIMIT 1").fetchone() is not None

    def create_user(self, username, password, role="member", *, bootstrap=False):
        username, key, password = _credentials(username, password)
        if role not in ("member", "admin"):
            raise HTTPException(400, "账号角色无效")
        encoded = _password_hash(password)
        with self._lock, self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            if bootstrap and connection.execute("SELECT 1 FROM accounts LIMIT 1").fetchone():
                raise HTTPException(409, "管理员已初始化，请使用已有账号登录")
            user_id = uuid.uuid4().hex
            try:
                connection.execute("INSERT INTO accounts VALUES (?, ?, ?, ?, ?, 1, ?)",
                                   (user_id, username, key, encoded, role, time.time()))
            except sqlite3.IntegrityError:
                raise HTTPException(409, "用户名已存在") from None
        return {"id": user_id, "username": username, "role": role, "enabled": True, "owner": "account_" + user_id}

    def new_session(self, user_id):
        value = secrets.token_urlsafe(32)
        digest = hashlib.sha256(value.encode()).hexdigest()
        with self._lock, self._connection() as connection:
            row = connection.execute("SELECT enabled FROM accounts WHERE id = ?", (user_id,)).fetchone()
            if row is None or not row["enabled"]:
                raise HTTPException(401, "账号不可用，请重新登录")
            connection.execute("DELETE FROM account_sessions WHERE expires_at <= ?", (time.time(),))
            connection.execute("INSERT INTO account_sessions VALUES (?, ?, ?)", (digest, user_id, time.time() + SESSION_SECONDS))
        return value

    def session_user(self, value):
        if not isinstance(value, str) or not 20 <= len(value) <= 128:
            return None
        digest = hashlib.sha256(value.encode()).hexdigest()
        with self._connection() as connection:
            row = connection.execute("SELECT a.* FROM accounts a JOIN account_sessions s ON s.user_id = a.id "
                                     "WHERE s.digest = ? AND s.expires_at > ? AND a.enabled = 1",
                                     (digest, time.time())).fetchone()
            return _user(row) if row else None

    def logout(self, value):
        digest = hashlib.sha256((value or "").encode()).hexdigest()
        with self._lock, self._connection() as connection:
            connection.execute("DELETE FROM account_sessions WHERE digest = ?", (digest,))

    def login(self, username, password, address):
        # Generic failures prevent username enumeration; neither address nor
        # attempted username is written as a raw audit or throttle key.
        if not isinstance(username, str) or not isinstance(password, str) or len(username) > 128 or len(password) > 128:
            raise HTTPException(400, "登录参数无效")
        key = username.casefold()
        buckets = [hashlib.sha256((kind + ":" + value).encode()).hexdigest()
                   for kind, value in (("user", key), ("address", address))]
        now = time.time()
        with self._lock, self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            for bucket, limit in zip(buckets, (LOGIN_LIMIT, LOGIN_LIMIT * 6)):
                row = connection.execute("SELECT * FROM login_limits WHERE key = ?", (bucket,)).fetchone()
                if row and now - row["started_at"] < LOGIN_WINDOW and row["failures"] >= limit:
                    raise HTTPException(429, "登录失败次数较多，请15分钟后重试", headers={"Retry-After": str(LOGIN_WINDOW)})
            row = connection.execute("SELECT * FROM accounts WHERE username_key = ?", (key,)).fetchone()
            valid = bool(row and row["enabled"] and _password_matches(password, row["password_hash"]))
            if not row:
                # Equal-cost work for a missing account.
                hashlib.pbkdf2_hmac("sha256", password.encode(), b"download-login-missing", PASSWORD_ITERATIONS)
            if valid:
                connection.execute("DELETE FROM login_limits WHERE key = ?", (buckets[0],))
                user = _user(row)
            else:
                for bucket in buckets:
                    connection.execute("INSERT INTO login_limits VALUES (?, ?, 1) ON CONFLICT(key) DO UPDATE SET "
                                       "failures = CASE WHEN ? - started_at >= ? THEN 1 ELSE failures + 1 END, "
                                       "started_at = CASE WHEN ? - started_at >= ? THEN ? ELSE started_at END",
                                       (bucket, now, now, LOGIN_WINDOW, now, LOGIN_WINDOW, now))
                user = None
        # Raise after transaction commits so the failed-attempt counter persists.
        if not user:
            raise HTTPException(401, "用户名或密码错误，或账号已停用")
        return user

    def users(self):
        with self._connection() as connection:
            return [{**public_user(_user(row)), "enabled": bool(row["enabled"])} for row in
                    connection.execute("SELECT * FROM accounts ORDER BY created_at, id").fetchall()]

    def set_enabled(self, user_id, enabled):
        if type(enabled) is not bool:
            raise HTTPException(400, "enabled须为布尔值")
        with self._lock, self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute("SELECT * FROM accounts WHERE id = ?", (user_id,)).fetchone()
            if row is None:
                raise HTTPException(404, "账号不存在")
            if not enabled and row["role"] == "admin" and row["enabled"]:
                count = connection.execute("SELECT COUNT(*) FROM accounts WHERE role = 'admin' AND enabled = 1").fetchone()[0]
                if count <= 1:
                    raise HTTPException(409, "不能停用最后一个可用管理员")
            connection.execute("UPDATE accounts SET enabled = ? WHERE id = ?", (int(enabled), user_id))
            if not enabled:
                connection.execute("DELETE FROM account_sessions WHERE user_id = ?", (user_id,))
        result = _user(row)
        result["enabled"] = enabled
        return result

    def audit(self, user, action, run_id="", detail=""):
        action = action if isinstance(action, str) and re.fullmatch(r"[a-z][a-z0-9_.-]{0,63}", action) else "operation"
        run_id = run_id if isinstance(run_id, str) and re.fullmatch(r"[a-f0-9]{32}", run_id) else ""
        # No free text: audit is an operation ledger, not a second business log.
        detail = detail if detail in {"", "success", "failed", "enabled", "disabled", "admin", "member", "cancelled", "partial"} else ""
        with self._connection() as connection:
            connection.execute("INSERT INTO account_audit(time, user_id, username, action, run_id, detail) VALUES (?, ?, ?, ?, ?, ?)",
                               (time.time(), user["id"], user["username"], action, run_id, detail))

    def audit_events(self):
        with self._connection() as connection:
            return [dict(row) for row in connection.execute("SELECT * FROM account_audit ORDER BY id DESC LIMIT 500")]


def get_account_store():
    global _singleton
    with _singleton_lock:
        if _singleton is None:
            _singleton = AccountStore(Path(__file__).resolve().parent / ".local_downloads" / "accounts.sqlite3")
        return _singleton


def optional_account(request):
    _request_origin(request)
    client_address(request)
    return {"id": "shared", "username": "小组共享", "role": "admin", "owner": "download_shared"}


def require_account(request):
    if request.method not in ("GET", "HEAD", "OPTIONS"):
        validate_write_request(request)
    user = optional_account(request)
    return user


def require_admin(request):
    user = require_account(request)
    if user["role"] != "admin":
        raise HTTPException(403, "此操作需要下载中心管理员权限")
    return user


def audit_event(user, action, run_id="", detail=""):
    get_account_store().audit(user, action, run_id, detail)
