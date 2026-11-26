"""Account authentication, registration approval, module permissions, and workspace binding.

Supports multi-account LAN collaboration with isolated per-user workspaces,
admin approval workflow, preset role templates + module switches, and admin
cross-workspace inspection. When uninitialized without REQUIRE_AUTH_SESSION=1,
retains shared fallback compatibility for offline unit tests.
"""

from contextlib import contextmanager
import hashlib
import hmac
import ipaddress
import json
import os
from pathlib import Path
import re
import secrets
import socket
import sqlite3
import threading
import time
from urllib.parse import unquote, urlparse
import uuid

from fastapi import HTTPException

from workspace_context import (
    PRIMARY_WORKSPACE,
    bind_workspace,
    initialize_workspace_storage,
    valid_workspace_id,
)

COOKIE_NAME = "fengshen_download_session"
SESSION_SECONDS = 24 * 60 * 60
PASSWORD_ITERATIONS = 600_000
HOST_LOCAL_ONLY_HASH = "!host-local-only!"
HOST_BUILTIN_USERNAME = "host_admin"
LOGIN_WINDOW = 15 * 60
LOGIN_LIMIT = 5
REGISTER_WINDOW = 15 * 60
_PRIVATE_V4 = tuple(ipaddress.ip_network(value) for value in ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16"))
_PRIVATE_V6 = ipaddress.ip_network("fc00::/7")
_singleton = None
_singleton_lock = threading.Lock()

PERMISSION_KEYS = (
    "collection",          # 数据采集
    "reports",             # 业务报表
    "payroll",             # 薪资核算与扣款设置
    "approval",            # 价格审批与每日价格导出
    "xiaoxiang_use",       # 使用共享小象灯塔采集
    "benlai_use",          # 使用共享本来人力采集
    "shared_auth_manage",  # 登录/断开共享平台连接（小象灯塔、本来人力）
)

PERMISSION_LABELS = {
    "collection": "数据采集",
    "reports": "业务报表",
    "payroll": "薪资核算",
    "approval": "价格审批",
    "xiaoxiang_use": "共享小象·使用权",
    "benlai_use": "共享本来·使用权",
    "shared_auth_manage": "共享连接·维护权(小象/本来)",
}

ROLE_TEMPLATES = {
    "admin": {
        "label": "系统管理员",
        "description": "全部业务模块、共享连接(小象/本来)维护、账户审批管理与跨空间巡检",
        "role": "admin",
        "permissions": {key: True for key in PERMISSION_KEYS},
    },
    "payroll_specialist": {
        "label": "薪酬核算员",
        "description": "数据采集、业务报表、薪资核算与共享小象/本来采集使用权",
        "role": "member",
        "permissions": {
            "collection": True,
            "reports": True,
            "payroll": True,
            "approval": False,
            "xiaoxiang_use": True,
            "benlai_use": True,
            "shared_auth_manage": False,
        },
    },
    "ops_specialist": {
        "label": "运营审批专员",
        "description": "数据采集、业务报表、蓝橙价格审批导出与共享小象/本来使用权",
        "role": "member",
        "permissions": {
            "collection": True,
            "reports": True,
            "payroll": False,
            "approval": True,
            "xiaoxiang_use": True,
            "benlai_use": True,
            "shared_auth_manage": False,
        },
    },
    "custom": {
        "label": "自定义权限",
        "description": "按需自由组合勾选各项功能模块权限",
        "role": "member",
        "permissions": {
            "collection": True,
            "reports": True,
            "payroll": False,
            "approval": False,
            "xiaoxiang_use": True,
            "benlai_use": True,
            "shared_auth_manage": False,
        },
    },
}


def normalize_permissions(role: str, role_template: str = "custom", overrides: dict | None = None) -> dict[str, bool]:
    if role == "admin" or role_template == "admin":
        return {key: True for key in PERMISSION_KEYS}
    preset = ROLE_TEMPLATES.get(role_template, ROLE_TEMPLATES["custom"])["permissions"]
    merged = {key: bool(preset.get(key, False)) for key in PERMISSION_KEYS}
    if isinstance(overrides, dict):
        for key in PERMISSION_KEYS:
            if key in overrides and isinstance(overrides[key], bool):
                merged[key] = overrides[key]
    return merged


def _loopback(value):
    try:
        address = ipaddress.ip_address(value)
        if address.version == 6 and address.ipv4_mapped:
            address = address.ipv4_mapped
        return address.is_loopback
    except (ValueError, TypeError):
        return False


def _host_interface_addresses() -> set[str]:
    result = {"127.0.0.1", "::1"}
    try:
        import psutil
        for addrs in psutil.net_if_addrs().values():
            for item in addrs:
                raw = (item.address or "").split("%", 1)[0].strip()
                try:
                    parsed = ipaddress.ip_address(raw)
                    if parsed.version == 6 and parsed.ipv4_mapped:
                        parsed = parsed.ipv4_mapped
                    result.add(str(parsed))
                except ValueError:
                    continue
    except Exception:
        pass
    return result


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
            addr = ipaddress.ip_address(claimed)
            if addr.version == 6 and addr.ipv4_mapped:
                addr = addr.ipv4_mapped
            return str(addr)
        except ValueError:
            raise HTTPException(403, "下载访问来源无效") from None
    try:
        addr = ipaddress.ip_address(peer)
        if addr.version == 6 and addr.ipv4_mapped:
            addr = addr.ipv4_mapped
        return str(addr)
    except ValueError:
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
        raise HTTPException(403, "本系统仅允许本机或局域网 IP 地址访问") from None


def validate_write_request(request):
    """Browser writes require an exact same-origin JSON request."""
    expected = _request_origin(request)
    client_address(request)
    if request.headers.get("content-type", "").split(";", 1)[0].strip().lower() != "application/json":
        raise HTTPException(415, "请求必须使用 JSON")
    try:
        value = urlparse(request.headers.get("origin", ""))
        actual = (value.scheme, (value.hostname or "").lower(), value.port or (443 if value.scheme == "https" else 80))
        valid = (value.scheme in ("http", "https") and not value.username and not value.password
                 and value.path in ("", "/") and not value.query and not value.fragment and actual == expected)
    except (ValueError, UnicodeError):
        valid = False
    if not valid:
        raise HTTPException(403, "写操作必须从当前系统页面发起，地址、协议和端口须一致")


def bootstrap_allowed(request):
    _request_origin(request)
    return _loopback(client_address(request))


def is_host_machine_request(request) -> bool:
    _request_origin(request)
    addr = client_address(request)
    return _loopback(addr) or addr in _host_interface_addresses()


def _credentials(username, password, *, min_password_len=6):
    if not isinstance(username, str):
        raise HTTPException(400, "请输入有效的用户名")
    username = username.strip()
    if not 2 <= len(username) <= 40 or any(not char.isalnum() and char not in "_.-" for char in username):
        raise HTTPException(400, "用户名须为2至40位中英文、数字、下划线、点或短横线")
    if not isinstance(password, str) or not min_password_len <= len(password) <= 128:
        raise HTTPException(400, f"密码长度须为{min_password_len}至128位字符")
    return username, username.casefold(), password


def _clean_text(value, max_len: int, label: str, required: bool = False) -> str:
    if value is None:
        text = ""
    elif isinstance(value, str):
        text = re.sub(r"[\x00-\x1f\x7f]", "", value).strip()
    else:
        raise HTTPException(400, f"{label}格式无效")
    if required and not text:
        raise HTTPException(400, f"请填写{label}")
    if len(text) > max_len:
        raise HTTPException(400, f"{label}长度不能超过 {max_len} 个字符")
    return text


def _password_hash(password):
    salt = secrets.token_bytes(16)
    value = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, PASSWORD_ITERATIONS)
    return f"pbkdf2_sha256${PASSWORD_ITERATIONS}${salt.hex()}${value.hex()}"


def has_usable_password(encoded) -> bool:
    return isinstance(encoded, str) and encoded.startswith("pbkdf2_sha256$")


def _password_matches(password, encoded):
    if not has_usable_password(encoded):
        return False
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
    return {
        "id": user["id"],
        "username": user["username"],
        "display_name": user.get("display_name") or user["username"],
        "role": user["role"],
        "role_template": user.get("role_template", "admin" if user["role"] == "admin" else "custom"),
        "status": user.get("status", "active" if user.get("enabled", True) else "disabled"),
        "enabled": bool(user.get("enabled", True)),
        "has_password": bool(user.get("has_password", True)),
        "workspace_id": user.get("workspace_id", PRIMARY_WORKSPACE),
        "effective_workspace": user.get("effective_workspace", user.get("workspace_id", PRIMARY_WORKSPACE)),
        "inspecting": bool(user.get("inspecting", False)),
        "inspect_target": user.get("inspect_target"),
        "permissions": user.get("permissions", normalize_permissions(user["role"])),
        "note": user.get("note", ""),
        "created_at": user.get("created_at", 0),
        "updated_at": user.get("updated_at", 0),
    }


def _row_to_user(row) -> dict:
    keys = row.keys()
    role = row["role"]
    enabled = bool(row["enabled"])
    status = (row["status"] if "status" in keys and row["status"] else ("active" if enabled else "disabled"))
    role_template = row["role_template"] if "role_template" in keys and row["role_template"] else ("admin" if role == "admin" else "payroll_specialist")
    raw_perms = {}
    if "permissions_json" in keys and row["permissions_json"]:
        try:
            parsed = json.loads(row["permissions_json"])
            if isinstance(parsed, dict):
                raw_perms = parsed
        except ValueError:
            raw_perms = {}
    permissions = normalize_permissions(role, role_template, raw_perms)
    wid = row["workspace_id"] if "workspace_id" in keys and row["workspace_id"] else (
        PRIMARY_WORKSPACE if role == "admin" else f"ws_{row['id'][:12]}"
    )
    display_name = (row["display_name"] if "display_name" in keys and row["display_name"] else row["username"])
    encoded_pw = row["password_hash"] if "password_hash" in keys else ""
    return {
        "id": row["id"],
        "username": row["username"],
        "display_name": display_name,
        "role": role,
        "role_template": "admin" if role == "admin" else role_template,
        "status": status,
        "enabled": enabled and status == "active",
        "has_password": has_usable_password(encoded_pw),
        "workspace_id": wid,
        "effective_workspace": wid,
        "owner": wid,
        "inspecting": False,
        "inspect_target": None,
        "permissions": permissions,
        "note": row["note"] if "note" in keys and row["note"] else "",
        "created_at": row["created_at"] if "created_at" in keys else 0,
        "updated_at": row["updated_at"] if "updated_at" in keys else 0,
    }


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
            acc_cols = {row["name"] for row in connection.execute("PRAGMA table_info(accounts)").fetchall()}
            migrations = [
                ("display_name", "TEXT NOT NULL DEFAULT ''"),
                ("status", "TEXT NOT NULL DEFAULT 'active'"),
                ("workspace_id", "TEXT NOT NULL DEFAULT ''"),
                ("role_template", "TEXT NOT NULL DEFAULT 'payroll_specialist'"),
                ("permissions_json", "TEXT NOT NULL DEFAULT '{}'"),
                ("note", "TEXT NOT NULL DEFAULT ''"),
                ("updated_at", "REAL NOT NULL DEFAULT 0"),
            ]
            for col, ddl in migrations:
                if col not in acc_cols:
                    connection.execute(f"ALTER TABLE accounts ADD COLUMN {col} {ddl}")

            sess_cols = {row["name"] for row in connection.execute("PRAGMA table_info(account_sessions)").fetchall()}
            if "inspect_workspace" not in sess_cols:
                connection.execute("ALTER TABLE account_sessions ADD COLUMN inspect_workspace TEXT NOT NULL DEFAULT ''")

            # Backfill legacy rows missing workspace_id or status
            rows = connection.execute("SELECT * FROM accounts WHERE workspace_id = ''").fetchall()
            first_admin_assigned = connection.execute(
                "SELECT 1 FROM accounts WHERE workspace_id = ?", (PRIMARY_WORKSPACE,)
            ).fetchone() is not None
            for row in rows:
                if row["role"] == "admin" and not first_admin_assigned:
                    wid = PRIMARY_WORKSPACE
                    first_admin_assigned = True
                else:
                    wid = f"ws_{row['id'][:12]}"
                status = "active" if row["enabled"] else "disabled"
                tmpl = "admin" if row["role"] == "admin" else "payroll_specialist"
                perms = json.dumps(normalize_permissions(row["role"], tmpl), ensure_ascii=False)
                connection.execute(
                    "UPDATE accounts SET workspace_id = ?, status = ?, role_template = ?, permissions_json = ?, "
                    "display_name = CASE WHEN display_name = '' THEN username ELSE display_name END WHERE id = ?",
                    (wid, status, tmpl, perms, row["id"]),
                )

    @contextmanager
    def _connection(self):
        connection = sqlite3.connect(self.db_path, timeout=15)
        connection.row_factory = sqlite3.Row
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def initialized(self) -> bool:
        with self._connection() as connection:
            return connection.execute(
                "SELECT 1 FROM accounts WHERE role = 'admin' AND enabled = 1 AND status = 'active' LIMIT 1"
            ).fetchone() is not None

    def _apply_admin_inspect(self, connection, user: dict, candidate_workspace: str | None) -> dict:
        if user.get("role") != "admin":
            return user
        candidate = (candidate_workspace or "").strip()
        if candidate and candidate != user["workspace_id"]:
            try:
                valid_workspace_id(candidate)
                target_row = connection.execute(
                    "SELECT id, username, display_name, workspace_id, role FROM accounts WHERE workspace_id = ?",
                    (candidate,),
                ).fetchone()
            except ValueError:
                target_row = None
            if target_row is not None:
                user["effective_workspace"] = candidate
                user["owner"] = candidate
                user["inspecting"] = True
                user["inspect_target"] = {
                    "id": target_row["id"],
                    "username": target_row["username"],
                    "display_name": target_row["display_name"] or target_row["username"],
                    "workspace_id": target_row["workspace_id"],
                }
        return user

    def get_primary_host_admin(self) -> dict | None:
        with self._connection() as connection:
            row = connection.execute(
                "SELECT * FROM accounts WHERE role = 'admin' AND enabled = 1 AND status = 'active' "
                "ORDER BY CASE WHEN workspace_id = ? THEN 0 ELSE 1 END, created_at ASC, id ASC LIMIT 1",
                (PRIMARY_WORKSPACE,),
            ).fetchone()
            return _row_to_user(row) if row is not None else None

    def ensure_host_admin(self, *, header_inspect: str | None = None) -> dict:
        """Return the primary active host admin, creating the built-in local super-admin on first run."""
        now = time.time()
        perms_json = json.dumps(normalize_permissions("admin", "admin"), ensure_ascii=False)
        with self._lock, self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT * FROM accounts WHERE role = 'admin' AND enabled = 1 AND status = 'active' "
                "ORDER BY CASE WHEN workspace_id = ? THEN 0 ELSE 1 END, created_at ASC, id ASC LIMIT 1",
                (PRIMARY_WORKSPACE,),
            ).fetchone()
            if row is None:
                existing_builtin = connection.execute(
                    "SELECT * FROM accounts WHERE username_key = ?",
                    (HOST_BUILTIN_USERNAME,),
                ).fetchone()
                if existing_builtin is not None:
                    wid = existing_builtin["workspace_id"] or PRIMARY_WORKSPACE
                    connection.execute(
                        "UPDATE accounts SET role = 'admin', role_template = 'admin', permissions_json = ?, "
                        "status = 'active', enabled = 1, workspace_id = ?, updated_at = ? WHERE id = ?",
                        (perms_json, wid, now, existing_builtin["id"]),
                    )
                    row = connection.execute(
                        "SELECT * FROM accounts WHERE id = ?",
                        (existing_builtin["id"],),
                    ).fetchone()
                else:
                    primary_taken = connection.execute(
                        "SELECT 1 FROM accounts WHERE workspace_id = ? LIMIT 1",
                        (PRIMARY_WORKSPACE,),
                    ).fetchone() is not None
                    user_id = uuid.uuid4().hex
                    wid = PRIMARY_WORKSPACE if not primary_taken else f"ws_{user_id[:12]}"
                    connection.execute(
                        "INSERT INTO accounts (id, username, username_key, password_hash, role, enabled, created_at, "
                        "display_name, status, workspace_id, role_template, permissions_json, note, updated_at) "
                        "VALUES (?, ?, ?, ?, 'admin', 1, ?, ?, 'active', ?, 'admin', ?, ?, ?)",
                        (
                            user_id,
                            HOST_BUILTIN_USERNAME,
                            HOST_BUILTIN_USERNAME,
                            HOST_LOCAL_ONLY_HASH,
                            now,
                            "主机管理员",
                            wid,
                            perms_json,
                            "本机免登内置超级管理员",
                            now,
                        ),
                    )
                    row = connection.execute(
                        "SELECT * FROM accounts WHERE id = ?",
                        (user_id,),
                    ).fetchone()
            user = self._apply_admin_inspect(connection, _row_to_user(row), header_inspect)
        initialize_workspace_storage(user["workspace_id"])
        return user

    def create_user(
        self,
        username,
        password,
        role="member",
        *,
        bootstrap=False,
        display_name="",
        role_template=None,
        permissions=None,
        note="",
    ):
        username, key, password = _credentials(username, password)
        if role not in ("member", "admin"):
            raise HTTPException(400, "账号角色无效")
        tmpl = role_template or ("admin" if role == "admin" else "payroll_specialist")
        if tmpl not in ROLE_TEMPLATES:
            tmpl = "custom"
        if tmpl == "admin":
            role = "admin"
        elif role == "admin":
            tmpl = "admin"
        clean_display = _clean_text(display_name, 40, "姓名/显示名") or username
        clean_note = _clean_text(note, 120, "备注")
        perms = normalize_permissions(role, tmpl, permissions)
        encoded = _password_hash(password)
        now = time.time()
        with self._lock, self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            has_admin = connection.execute(
                "SELECT 1 FROM accounts WHERE role = 'admin' AND enabled = 1 AND status = 'active' LIMIT 1"
            ).fetchone() is not None
            if bootstrap and has_admin:
                raise HTTPException(409, "主机管理员已初始化，请直接使用已有管理员账号登录")
            primary_taken = connection.execute(
                "SELECT 1 FROM accounts WHERE workspace_id = ? LIMIT 1", (PRIMARY_WORKSPACE,)
            ).fetchone() is not None
            user_id = uuid.uuid4().hex
            wid = PRIMARY_WORKSPACE if (bootstrap or (role == "admin" and not primary_taken)) else f"ws_{user_id[:12]}"
            try:
                connection.execute(
                    "INSERT INTO accounts (id, username, username_key, password_hash, role, enabled, created_at, "
                    "display_name, status, workspace_id, role_template, permissions_json, note, updated_at) "
                    "VALUES (?, ?, ?, ?, ?, 1, ?, ?, 'active', ?, ?, ?, ?, ?)",
                    (user_id, username, key, encoded, role, now, clean_display, wid, tmpl, json.dumps(perms, ensure_ascii=False), clean_note, now),
                )
            except sqlite3.IntegrityError:
                raise HTTPException(409, "用户名已存在") from None
            row = connection.execute("SELECT * FROM accounts WHERE id = ?", (user_id,)).fetchone()
        initialize_workspace_storage(wid)
        return _row_to_user(row)

    def register_user(
        self,
        username: str,
        password: str,
        *,
        display_name: str = "",
        note: str = "",
        address: str = "",
    ) -> dict:
        """Public colleague registration: creates a pending account awaiting admin approval."""
        if not self.initialized():
            raise HTTPException(409, "系统尚未初始化主机管理员，请先由管理员在本机完成初始化")
        username, key, password = _credentials(username, password)
        clean_display = _clean_text(display_name, 40, "姓名/显示名") or username
        clean_note = _clean_text(note, 120, "申请说明/负责区域")
        encoded = _password_hash(password)
        default_perms = normalize_permissions("member", "payroll_specialist")
        now = time.time()
        try:
            register_limit = max(1, int(os.environ.get("REGISTER_RATE_LIMIT", "10")))
        except ValueError:
            register_limit = 10
        try:
            pending_cap = max(1, int(os.environ.get("PENDING_QUEUE_LIMIT", "100")))
        except ValueError:
            pending_cap = 100
        addr_bucket = (
            hashlib.sha256(("register:" + address.strip()).encode()).hexdigest()
            if address and address.strip()
            else ""
        )
        with self._lock, self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            if addr_bucket:
                limit_row = connection.execute(
                    "SELECT * FROM login_limits WHERE key = ?",
                    (addr_bucket,),
                ).fetchone()
                if (
                    limit_row
                    and now - limit_row["started_at"] < REGISTER_WINDOW
                    and limit_row["failures"] >= register_limit
                ):
                    raise HTTPException(
                        429,
                        "当前网络注册请求过于频繁，请15分钟后再试",
                        headers={"Retry-After": str(REGISTER_WINDOW)},
                    )
            existing = connection.execute("SELECT * FROM accounts WHERE username_key = ?", (key,)).fetchone()
            if existing is not None:
                if existing["status"] == "pending":
                    raise HTTPException(409, "该用户名已提交过注册申请，正在等待管理员审批")
                if existing["status"] == "rejected":
                    pending_total = int(
                        connection.execute("SELECT COUNT(*) FROM accounts WHERE status = 'pending'").fetchone()[0]
                    )
                    if pending_total >= pending_cap:
                        raise HTTPException(429, "当前待审批申请队列已满，请联系系统管理员处理后再提交")
                    connection.execute(
                        "UPDATE accounts SET username = ?, password_hash = ?, display_name = ?, note = ?, "
                        "status = 'pending', enabled = 0, updated_at = ? WHERE id = ?",
                        (username, encoded, clean_display, clean_note, now, existing["id"]),
                    )
                    if addr_bucket:
                        connection.execute(
                            "INSERT INTO login_limits VALUES (?, ?, 1) ON CONFLICT(key) DO UPDATE SET "
                            "failures = CASE WHEN ? - started_at >= ? THEN 1 ELSE failures + 1 END, "
                            "started_at = CASE WHEN ? - started_at >= ? THEN ? ELSE started_at END",
                            (addr_bucket, now, now, REGISTER_WINDOW, now, REGISTER_WINDOW, now),
                        )
                    row = connection.execute("SELECT * FROM accounts WHERE id = ?", (existing["id"],)).fetchone()
                    return _row_to_user(row)
                raise HTTPException(409, "该用户名已被使用，请更换其他用户名")
            pending_total = int(
                connection.execute("SELECT COUNT(*) FROM accounts WHERE status = 'pending'").fetchone()[0]
            )
            if pending_total >= pending_cap:
                raise HTTPException(429, "当前待审批申请队列已满，请联系系统管理员处理后再提交")
            user_id = uuid.uuid4().hex
            wid = f"ws_{user_id[:12]}"
            connection.execute(
                "INSERT INTO accounts (id, username, username_key, password_hash, role, enabled, created_at, "
                "display_name, status, workspace_id, role_template, permissions_json, note, updated_at) "
                "VALUES (?, ?, ?, ?, 'member', 0, ?, ?, 'pending', ?, 'payroll_specialist', ?, ?, ?)",
                (user_id, username, key, encoded, now, clean_display, wid, json.dumps(default_perms, ensure_ascii=False), clean_note, now),
            )
            if addr_bucket:
                connection.execute(
                    "INSERT INTO login_limits VALUES (?, ?, 1) ON CONFLICT(key) DO UPDATE SET "
                    "failures = CASE WHEN ? - started_at >= ? THEN 1 ELSE failures + 1 END, "
                    "started_at = CASE WHEN ? - started_at >= ? THEN ? ELSE started_at END",
                    (addr_bucket, now, now, REGISTER_WINDOW, now, REGISTER_WINDOW, now),
                )
            row = connection.execute("SELECT * FROM accounts WHERE id = ?", (user_id,)).fetchone()
        return _row_to_user(row)

    def approve_user(
        self,
        user_id: str,
        *,
        role_template: str = "payroll_specialist",
        permissions: dict | None = None,
        display_name: str | None = None,
        note: str | None = None,
    ) -> dict:
        if role_template not in ROLE_TEMPLATES:
            raise HTTPException(400, "预设角色无效")
        role = "admin" if role_template == "admin" else "member"
        perms = normalize_permissions(role, role_template, permissions)
        now = time.time()
        with self._lock, self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute("SELECT * FROM accounts WHERE id = ?", (user_id,)).fetchone()
            if row is None:
                raise HTTPException(404, "账号不存在")
            wid = row["workspace_id"] or f"ws_{row['id'][:12]}"
            next_display = _clean_text(display_name, 40, "姓名/显示名") if display_name is not None else row["display_name"]
            next_note = _clean_text(note, 120, "备注") if note is not None else row["note"]
            connection.execute(
                "UPDATE accounts SET role = ?, role_template = ?, permissions_json = ?, status = 'active', "
                "enabled = 1, workspace_id = ?, display_name = ?, note = ?, updated_at = ? WHERE id = ?",
                (role, role_template, json.dumps(perms, ensure_ascii=False), wid, next_display or row["username"], next_note, now, user_id),
            )
            updated = connection.execute("SELECT * FROM accounts WHERE id = ?", (user_id,)).fetchone()
        initialize_workspace_storage(wid)
        return _row_to_user(updated)

    def reject_user(self, user_id: str) -> dict:
        now = time.time()
        with self._lock, self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute("SELECT * FROM accounts WHERE id = ?", (user_id,)).fetchone()
            if row is None:
                raise HTTPException(404, "账号不存在")
            if row["role"] == "admin" and row["enabled"]:
                raise HTTPException(409, "不能驳回已启用的管理员账号")
            connection.execute(
                "UPDATE accounts SET status = 'rejected', enabled = 0, updated_at = ? WHERE id = ?",
                (now, user_id),
            )
            connection.execute("DELETE FROM account_sessions WHERE user_id = ?", (user_id,))
            updated = connection.execute("SELECT * FROM accounts WHERE id = ?", (user_id,)).fetchone()
        return _row_to_user(updated)

    def update_user_access(
        self,
        user_id: str,
        *,
        display_name: str | None = None,
        role_template: str | None = None,
        permissions: dict | None = None,
        enabled: bool | None = None,
        note: str | None = None,
    ) -> dict:
        now = time.time()
        with self._lock, self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute("SELECT * FROM accounts WHERE id = ?", (user_id,)).fetchone()
            if row is None:
                raise HTTPException(404, "账号不存在")
            current = _row_to_user(row)
            next_tmpl = role_template if role_template is not None else current["role_template"]
            if next_tmpl not in ROLE_TEMPLATES:
                raise HTTPException(400, "角色模板无效")
            next_role = "admin" if next_tmpl == "admin" else "member"
            next_enabled = current["enabled"] if enabled is None else bool(enabled)

            # Prevent removing or disabling the last active admin
            if row["role"] == "admin" and row["enabled"] and row["status"] == "active" and (next_role != "admin" or not next_enabled):
                admin_count = connection.execute(
                    "SELECT COUNT(*) FROM accounts WHERE role = 'admin' AND enabled = 1 AND status = 'active'"
                ).fetchone()[0]
                if admin_count <= 1:
                    raise HTTPException(409, "系统必须至少保留一个处于启用状态的管理员账号")

            base_perms = current["permissions"] if role_template is None else None
            merged_overrides = {**(base_perms or {}), **(permissions or {})} if permissions is not None or base_perms is not None else None
            if role_template is not None and permissions is None:
                merged_overrides = None
            next_perms = normalize_permissions(next_role, next_tmpl, merged_overrides)
            next_status = "active" if next_enabled else ("pending" if row["status"] == "pending" and enabled is None else "disabled")
            next_display = _clean_text(display_name, 40, "姓名/显示名") if display_name is not None else current["display_name"]
            next_note = _clean_text(note, 120, "备注") if note is not None else current["note"]
            wid = current["workspace_id"]

            connection.execute(
                "UPDATE accounts SET role = ?, role_template = ?, permissions_json = ?, enabled = ?, status = ?, "
                "display_name = ?, note = ?, workspace_id = ?, updated_at = ? WHERE id = ?",
                (
                    next_role,
                    next_tmpl,
                    json.dumps(next_perms, ensure_ascii=False),
                    int(next_status == "active"),
                    next_status,
                    next_display or current["username"],
                    next_note,
                    wid,
                    now,
                    user_id,
                ),
            )
            if next_status != "active":
                connection.execute("DELETE FROM account_sessions WHERE user_id = ?", (user_id,))
            elif next_role != "admin":
                connection.execute("UPDATE account_sessions SET inspect_workspace = '' WHERE user_id = ?", (user_id,))
            updated = connection.execute("SELECT * FROM accounts WHERE id = ?", (user_id,)).fetchone()
        if next_status == "active":
            initialize_workspace_storage(wid)
        return _row_to_user(updated)

    def reset_password(self, user_id: str, new_password: str, *, keep_session_token: str | None = None) -> None:
        _, _, clean_pw = _credentials("placeholder", new_password)
        encoded = _password_hash(clean_pw)
        now = time.time()
        keep_digest = (
            hashlib.sha256(keep_session_token.encode()).hexdigest()
            if isinstance(keep_session_token, str) and 20 <= len(keep_session_token) <= 128
            else None
        )
        with self._lock, self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute("SELECT id FROM accounts WHERE id = ?", (user_id,)).fetchone()
            if row is None:
                raise HTTPException(404, "账号不存在")
            connection.execute(
                "UPDATE accounts SET password_hash = ?, updated_at = ? WHERE id = ?",
                (encoded, now, user_id),
            )
            if keep_digest:
                connection.execute(
                    "DELETE FROM account_sessions WHERE user_id = ? AND digest != ?",
                    (user_id, keep_digest),
                )
            else:
                connection.execute("DELETE FROM account_sessions WHERE user_id = ?", (user_id,))

    def change_password(self, user_id: str, current_password: str, new_password: str) -> None:
        if not isinstance(current_password, str) or not current_password:
            raise HTTPException(400, "请输入当前密码")
        _, _, clean_pw = _credentials("placeholder", new_password)
        encoded = _password_hash(clean_pw)
        now = time.time()
        with self._lock, self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute("SELECT * FROM accounts WHERE id = ?", (user_id,)).fetchone()
            if row is None:
                raise HTTPException(401, "当前原密码不正确")
            if not has_usable_password(row["password_hash"]):
                raise HTTPException(400, "当前本机免登管理员未设置远程密码，如需启用密码请在权限管理中设置")
            if not _password_matches(current_password, row["password_hash"]):
                raise HTTPException(401, "当前原密码不正确")
            connection.execute(
                "UPDATE accounts SET password_hash = ?, updated_at = ? WHERE id = ?",
                (encoded, now, user_id),
            )

    def new_session(self, user_id):
        value = secrets.token_urlsafe(32)
        digest = hashlib.sha256(value.encode()).hexdigest()
        with self._lock, self._connection() as connection:
            row = connection.execute("SELECT enabled, status FROM accounts WHERE id = ?", (user_id,)).fetchone()
            if row is None or not row["enabled"] or row["status"] != "active":
                raise HTTPException(401, "账号不可用，请重新登录")
            connection.execute("DELETE FROM account_sessions WHERE expires_at <= ?", (time.time(),))
            connection.execute(
                "INSERT INTO account_sessions (digest, user_id, expires_at, inspect_workspace) VALUES (?, ?, ?, '')",
                (digest, user_id, time.time() + SESSION_SECONDS),
            )
        return value

    def set_session_inspect_workspace(self, session_token: str, target_workspace: str | None) -> dict:
        if not isinstance(session_token, str) or not 20 <= len(session_token) <= 128:
            raise HTTPException(401, "会话无效，请重新登录")
        digest = hashlib.sha256(session_token.encode()).hexdigest()
        cleaned = (target_workspace or "").strip()
        with self._lock, self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            sess = connection.execute(
                "SELECT a.*, s.inspect_workspace FROM accounts a JOIN account_sessions s ON s.user_id = a.id "
                "WHERE s.digest = ? AND s.expires_at > ? AND a.enabled = 1 AND a.status = 'active'",
                (digest, time.time()),
            ).fetchone()
            if sess is None:
                raise HTTPException(401, "会话已过期，请重新登录")
            admin_user = _row_to_user(sess)
            if admin_user["role"] != "admin":
                raise HTTPException(403, "仅管理员可切换跨空间巡检视角")
            if not cleaned or cleaned == admin_user["workspace_id"]:
                connection.execute("UPDATE account_sessions SET inspect_workspace = '' WHERE digest = ?", (digest,))
            else:
                try:
                    valid_workspace_id(cleaned)
                except ValueError:
                    raise HTTPException(400, "目标空间标识无效") from None
                target_row = connection.execute(
                    "SELECT * FROM accounts WHERE workspace_id = ? AND status != 'rejected'",
                    (cleaned,),
                ).fetchone()
                if target_row is None:
                    raise HTTPException(404, "目标同事空间不存在")
                initialize_workspace_storage(cleaned)
                connection.execute(
                    "UPDATE account_sessions SET inspect_workspace = ? WHERE digest = ?",
                    (cleaned, digest),
                )
        resolved = self.session_user(session_token)
        if not resolved:
            raise HTTPException(401, "会话已失效")
        return resolved

    def workspace_directory_list(self) -> list[dict]:
        """List available workspaces for admin switcher."""
        with self._connection() as connection:
            rows = connection.execute(
                "SELECT * FROM accounts WHERE status IN ('active', 'disabled') ORDER BY CASE WHEN role = 'admin' THEN 0 ELSE 1 END, created_at"
            ).fetchall()
        result = []
        seen = set()
        for row in rows:
            u = _row_to_user(row)
            wid = u["workspace_id"]
            if wid in seen:
                continue
            seen.add(wid)
            result.append({
                "workspace_id": wid,
                "user_id": u["id"],
                "username": u["username"],
                "display_name": u["display_name"],
                "role": u["role"],
                "status": u["status"],
                "is_primary": wid == PRIMARY_WORKSPACE,
            })
        return result

    def session_user(self, value, header_inspect: str | None = None):
        if not isinstance(value, str) or not 20 <= len(value) <= 128:
            return None
        digest = hashlib.sha256(value.encode()).hexdigest()
        with self._connection() as connection:
            row = connection.execute(
                "SELECT a.*, s.inspect_workspace FROM accounts a JOIN account_sessions s ON s.user_id = a.id "
                "WHERE s.digest = ? AND s.expires_at > ? AND a.enabled = 1 AND a.status = 'active'",
                (digest, time.time()),
            ).fetchone()
            if not row:
                return None
            user = _row_to_user(row)
            return self._apply_admin_inspect(connection, user, header_inspect or row["inspect_workspace"])

    def logout(self, value):
        digest = hashlib.sha256((value or "").encode()).hexdigest()
        with self._lock, self._connection() as connection:
            connection.execute("DELETE FROM account_sessions WHERE digest = ?", (digest,))

    def login(self, username, password, address):
        if not isinstance(username, str) or not isinstance(password, str) or len(username) > 128 or len(password) > 128:
            raise HTTPException(400, "登录参数无效")
        key = username.strip().casefold()
        buckets = [hashlib.sha256((kind + ":" + value).encode()).hexdigest()
                   for kind, value in (("user", key), ("address", address))]
        now = time.time()
        pending_status = None
        with self._lock, self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            for bucket, limit in zip(buckets, (LOGIN_LIMIT, LOGIN_LIMIT * 6)):
                row = connection.execute("SELECT * FROM login_limits WHERE key = ?", (bucket,)).fetchone()
                if row and now - row["started_at"] < LOGIN_WINDOW and row["failures"] >= limit:
                    raise HTTPException(429, "登录失败次数较多，请15分钟后重试", headers={"Retry-After": str(LOGIN_WINDOW)})
            row = connection.execute("SELECT * FROM accounts WHERE username_key = ?", (key,)).fetchone()
            pw_ok = bool(row and _password_matches(password, row["password_hash"]))
            if not row:
                hashlib.pbkdf2_hmac("sha256", password.encode(), b"download-login-missing", PASSWORD_ITERATIONS)
            if pw_ok:
                connection.execute("DELETE FROM login_limits WHERE key = ?", (buckets[0],))
                if row["status"] == "pending":
                    pending_status = "pending"
                    user = None
                elif row["status"] == "rejected":
                    pending_status = "rejected"
                    user = None
                elif not row["enabled"] or row["status"] != "active":
                    pending_status = "disabled"
                    user = None
                else:
                    user = _row_to_user(row)
            else:
                for bucket in buckets:
                    connection.execute(
                        "INSERT INTO login_limits VALUES (?, ?, 1) ON CONFLICT(key) DO UPDATE SET "
                        "failures = CASE WHEN ? - started_at >= ? THEN 1 ELSE failures + 1 END, "
                        "started_at = CASE WHEN ? - started_at >= ? THEN ? ELSE started_at END",
                        (bucket, now, now, LOGIN_WINDOW, now, LOGIN_WINDOW, now),
                    )
                user = None
        if pending_status == "pending":
            raise HTTPException(403, "您的注册申请已提交，正在等待主机管理员审批开通独立空间")
        if pending_status == "rejected":
            raise HTTPException(403, "您的注册申请未获通过，可联系管理员或重新提交申请")
        if pending_status == "disabled":
            raise HTTPException(403, "该账号已被停用，请联系系统管理员")
        if not user:
            raise HTTPException(401, "用户名或密码错误")
        initialize_workspace_storage(user["workspace_id"])
        return user

    def users(self):
        with self._connection() as connection:
            rows = connection.execute(
                "SELECT * FROM accounts ORDER BY CASE status WHEN 'pending' THEN 0 WHEN 'active' THEN 1 ELSE 2 END, created_at DESC, id"
            ).fetchall()
        return [public_user(_row_to_user(row)) for row in rows]

    def pending_count(self) -> int:
        with self._connection() as connection:
            return int(connection.execute("SELECT COUNT(*) FROM accounts WHERE status = 'pending'").fetchone()[0])

    def set_enabled(self, user_id, enabled):
        if type(enabled) is not bool:
            raise HTTPException(400, "enabled须为布尔值")
        return self.update_user_access(user_id, enabled=enabled)

    def audit(self, user, action, run_id="", detail=""):
        action = action if isinstance(action, str) and re.fullmatch(r"[a-z][a-z0-9_.-]{0,63}", action) else "operation"
        run_id = run_id if isinstance(run_id, str) and re.fullmatch(r"[A-Za-z0-9_-]{1,64}", run_id) else ""
        detail = detail if detail in {
            "", "success", "failed", "enabled", "disabled", "admin", "member",
            "cancelled", "partial", "approved", "rejected", "registered", "inspect",
        } else ""
        with self._connection() as connection:
            connection.execute(
                "INSERT INTO account_audit(time, user_id, username, action, run_id, detail) VALUES (?, ?, ?, ?, ?, ?)",
                (time.time(), user["id"], user["username"], action, run_id, detail),
            )

    def audit_events(self):
        with self._connection() as connection:
            return [dict(row) for row in connection.execute("SELECT * FROM account_audit ORDER BY id DESC LIMIT 500")]


def get_account_store():
    global _singleton
    with _singleton_lock:
        if _singleton is None:
            _singleton = AccountStore(Path(__file__).resolve().parent / ".local_downloads" / "accounts.sqlite3")
        return _singleton


def _shared_fallback_user() -> dict:
    return {
        "id": "shared",
        "username": "小组共享",
        "display_name": "小组共享",
        "role": "admin",
        "role_template": "admin",
        "status": "active",
        "enabled": True,
        "owner": PRIMARY_WORKSPACE,
        "workspace_id": PRIMARY_WORKSPACE,
        "effective_workspace": PRIMARY_WORKSPACE,
        "inspecting": False,
        "inspect_target": None,
        "permissions": {key: True for key in PERMISSION_KEYS},
    }


def _extract_inspect_header(request) -> str | None:
    raw = request.headers.get("x-inspect-workspace", "").strip()
    if not raw:
        return None
    try:
        return unquote(raw, errors="strict").strip()
    except (UnicodeError, ValueError):
        return None


def optional_account(request):
    _request_origin(request)
    addr = client_address(request)
    store = get_account_store()
    header_inspect = _extract_inspect_header(request)
    token = request.cookies.get(COOKIE_NAME, "")
    if token:
        user = store.session_user(token, header_inspect=header_inspect)
        if user:
            return user
    if _loopback(addr) or addr in _host_interface_addresses():
        return store.ensure_host_admin(header_inspect=header_inspect)
    return None


def require_account(request):
    if request.method not in ("GET", "HEAD", "OPTIONS"):
        validate_write_request(request)
    user = optional_account(request)
    if user is None:
        raise HTTPException(401, "尚未登录或登录状态已过期，请先登录工作空间账号")
    return user


def require_admin(request):
    user = require_account(request)
    if user["role"] != "admin":
        raise HTTPException(403, "此操作需要系统管理员权限")
    return user


def check_user_permission(user: dict | None, *perm_keys: str, any_of: bool = False):
    if not user or user.get("role") == "admin" or "permissions" not in user:
        return user
    perms = user.get("permissions") or {}
    if any_of:
        if any(perms.get(k) for k in perm_keys):
            return user
    else:
        if all(perms.get(k) for k in perm_keys):
            return user
    missing_labels = " / ".join(PERMISSION_LABELS.get(k, k) for k in perm_keys if not perms.get(k))
    raise HTTPException(403, f"当前账号尚未开通【{missing_labels or '对应模块'}】操作权限，请联系管理员分配")


def require_permission(request, *perm_keys: str, any_of: bool = False):
    if not hasattr(request, "method"):
        return require_admin(request) or _shared_fallback_user()
    user = require_account(request)
    return check_user_permission(user, *perm_keys, any_of=any_of)


def can_manage_shared_auth(user: dict | None) -> bool:
    if not user:
        return False
    if user.get("role") == "admin":
        return True
    perms = user.get("permissions") or {}
    return bool(perms.get("shared_auth_manage") or perms.get("xiaoxiang_manage"))


def require_shared_auth_manage(request, source_label: str = "共享平台"):
    user = require_account(request)
    if can_manage_shared_auth(user):
        return user
    raise HTTPException(
        403,
        f"{source_label}为全局共享连接，仅系统管理员或授权维护人可登录/断开，您可以直接复用已就绪状态",
    )


def require_xiaoxiang_manage(request):
    return require_shared_auth_manage(request, "小象灯塔")


@contextmanager
def request_workspace_scope(request):
    """Bind ContextVars if a valid user exists for this request (including host auto-login)."""
    try:
        token = request.cookies.get(COOKIE_NAME, "")
        store = get_account_store()
        header_inspect = _extract_inspect_header(request)
        user = store.session_user(token, header_inspect=header_inspect) if token else None
        if user is None and is_host_machine_request(request):
            user = store.ensure_host_admin(header_inspect=header_inspect)
        if user is not None:
            with bind_workspace(user["effective_workspace"], user):
                yield
            return
    except Exception:
        pass
    yield


def audit_event(user, action, run_id="", detail=""):
    get_account_store().audit(user, action, run_id, detail)
