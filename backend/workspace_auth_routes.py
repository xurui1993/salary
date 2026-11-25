"""HTTP routes for login, self-registration, admin approval, permissions, and workspace switching."""

import hmac
import json
import os
from pathlib import Path
import shutil
from datetime import datetime

from fastapi import APIRouter, HTTPException, Request, Response

from download_accounts import (
    COOKIE_NAME,
    PERMISSION_KEYS,
    PERMISSION_LABELS,
    ROLE_TEMPLATES,
    SESSION_SECONDS,
    _loopback,
    audit_event,
    bootstrap_allowed,
    client_address,
    get_account_store,
    is_host_machine_request,
    optional_account,
    public_user,
    require_account,
    require_admin,
    validate_write_request,
)
from workspace_context import PRIMARY_WORKSPACE, PROJECT_ROOT, is_isolated_workspace, workspace_config_path

auth_router = APIRouter(prefix="/api/auth")
admin_router = APIRouter(prefix="/api/admin/accounts")


def _set_session_cookie(response: Response, request: Request, token: str) -> None:
    secure = request.url.scheme == "https"
    response.set_cookie(
        key=COOKIE_NAME,
        value=token,
        max_age=SESSION_SECONDS,
        httponly=True,
        samesite="lax",
        secure=secure,
        path="/",
    )


def _clear_session_cookie(response: Response) -> None:
    response.delete_cookie(key=COOKIE_NAME, path="/", samesite="lax")


async def _read_json(request: Request) -> dict:
    validate_write_request(request)
    try:
        payload = await request.json()
    except (ValueError, UnicodeError):
        raise HTTPException(400, "请求内容必须是有效的 JSON 对象") from None
    if not isinstance(payload, dict):
        raise HTTPException(400, "请求内容必须是 JSON 对象")
    return payload


def _session_payload(request: Request, user: dict | None) -> dict:
    store = get_account_store()
    initialized = store.initialized()
    host_client = is_host_machine_request(request)
    local_loopback = bootstrap_allowed(request)
    is_admin = bool(user and user.get("role") == "admin")
    return {
        "initialized": initialized,
        "authenticated": user is not None and user.get("id") != "shared",
        "host_machine": host_client,
        "local_loopback": local_loopback,
        "bootstrap_allowed": (not initialized) and host_client,
        "user": public_user(user) if (user and user.get("id") != "shared") else None,
        "role_templates": ROLE_TEMPLATES,
        "permission_keys": list(PERMISSION_KEYS),
        "permission_labels": PERMISSION_LABELS,
        "workspaces": store.workspace_directory_list() if is_admin else [],
        "pending_count": store.pending_count() if is_admin else 0,
    }


@auth_router.get("/session")
def get_session(request: Request):
    store = get_account_store()
    token = request.cookies.get(COOKIE_NAME, "")
    header_inspect = request.headers.get("x-inspect-workspace", "").strip() or None
    user = store.session_user(token, header_inspect=header_inspect) if token else None
    return _session_payload(request, user)


@auth_router.get("/internal/resolve")
def internal_resolve(request: Request):
    """Loopback-only gateway session resolver authenticated by per-launch secret."""
    peer = request.client.host if request.client else ""
    provided = request.headers.get("x-download-proxy-secret", "")
    expected = os.environ.get("FENGSHEN_DOWNLOAD_PROXY_SECRET", "")
    if not expected or not _loopback(peer) or not provided or not hmac.compare_digest(provided, expected):
        raise HTTPException(403, "内部鉴权通道拒绝访问")
    store = get_account_store()
    initialized = store.initialized()
    enforce = initialized or os.environ.get("REQUIRE_AUTH_SESSION") == "1"
    token = request.cookies.get(COOKIE_NAME, "")
    header_inspect = request.headers.get("x-inspect-workspace", "").strip() or None
    user = store.session_user(token, header_inspect=header_inspect) if token else None
    if user is None:
        return {
            "authenticated": False,
            "initialized": initialized,
            "enforce": enforce,
            "effective_workspace": PRIMARY_WORKSPACE,
            "user": None,
        }
    return {
        "authenticated": True,
        "initialized": initialized,
        "enforce": True,
        "effective_workspace": user["effective_workspace"],
        "user": public_user(user),
    }


@auth_router.post("/bootstrap")
async def bootstrap_admin(request: Request, response: Response):
    payload = await _read_json(request)
    store = get_account_store()
    if store.initialized():
        raise HTTPException(409, "主机管理员已初始化，请直接登录")
    if not is_host_machine_request(request):
        raise HTTPException(403, "首次初始化主机管理员仅允许在运行服务的主机电脑上操作")
    user = store.create_user(
        payload.get("username", ""),
        payload.get("password", ""),
        role="admin",
        bootstrap=True,
        display_name=payload.get("display_name", ""),
        note="主机超级管理员",
    )
    token = store.new_session(user["id"])
    _set_session_cookie(response, request, token)
    audit_event(user, "account.bootstrap", detail="admin")
    return _session_payload(request, user)


@auth_router.post("/register")
async def register(request: Request):
    payload = await _read_json(request)
    store = get_account_store()
    user = store.register_user(
        payload.get("username", ""),
        payload.get("password", ""),
        display_name=payload.get("display_name", ""),
        note=payload.get("note", ""),
    )
    audit_event(user, "account.register", detail="registered")
    return {
        "ok": True,
        "status": "pending",
        "message": "注册申请已提交！请等待主机管理员审批并分配权限，审批通过后即可登录进入您的专属独立工作空间。",
        "username": user["username"],
    }


@auth_router.post("/login")
async def login(request: Request, response: Response):
    payload = await _read_json(request)
    store = get_account_store()
    if not store.initialized():
        raise HTTPException(409, "系统尚未初始化主机管理员，请先在主机完成管理员创建")
    addr = client_address(request)
    user = store.login(payload.get("username", ""), payload.get("password", ""), addr)
    token = store.new_session(user["id"])
    _set_session_cookie(response, request, token)
    audit_event(user, "account.login", detail="success")
    return _session_payload(request, user)


@auth_router.post("/logout")
async def logout(request: Request, response: Response):
    validate_write_request(request)
    store = get_account_store()
    token = request.cookies.get(COOKIE_NAME, "")
    if token:
        user = store.session_user(token)
        store.logout(token)
        if user:
            audit_event(user, "account.logout", detail="success")
    _clear_session_cookie(response)
    return {"ok": True}


@auth_router.post("/password")
async def change_own_password(request: Request):
    payload = await _read_json(request)
    user = require_account(request)
    if user.get("id") == "shared":
        raise HTTPException(400, "当前未启用独立账号")
    store = get_account_store()
    store.change_password(
        user["id"],
        payload.get("current_password", ""),
        payload.get("new_password", ""),
    )
    audit_event(user, "account.password.change", detail="success")
    return {"ok": True, "message": "密码已更新"}


@auth_router.post("/inspect")
async def switch_inspect_workspace(request: Request):
    payload = await _read_json(request)
    admin = require_admin(request)
    token = request.cookies.get(COOKIE_NAME, "")
    target_wid = payload.get("workspace_id", "")
    if target_wid is not None and not isinstance(target_wid, str):
        raise HTTPException(400, "工作空间参数格式无效")
    store = get_account_store()
    updated_user = store.set_session_inspect_workspace(token, target_wid)
    audit_event(admin, "account.inspect", run_id=updated_user["effective_workspace"], detail="inspect")
    return _session_payload(request, updated_user)


@admin_router.get("")
def list_accounts(request: Request):
    require_admin(request)
    store = get_account_store()
    return {
        "users": store.users(),
        "pending_count": store.pending_count(),
        "workspaces": store.workspace_directory_list(),
        "role_templates": ROLE_TEMPLATES,
        "permission_keys": list(PERMISSION_KEYS),
        "permission_labels": PERMISSION_LABELS,
    }


@admin_router.post("")
async def admin_create_account(request: Request):
    payload = await _read_json(request)
    admin = require_admin(request)
    store = get_account_store()
    role_template = payload.get("role_template", "payroll_specialist")
    role = "admin" if role_template == "admin" else "member"
    created = store.create_user(
        payload.get("username", ""),
        payload.get("password", ""),
        role=role,
        display_name=payload.get("display_name", ""),
        role_template=role_template,
        permissions=payload.get("permissions"),
        note=payload.get("note", ""),
    )
    audit_event(admin, "account.create", run_id=created["workspace_id"], detail=created["role"])
    return {"ok": True, "user": public_user(created), "users": store.users(), "workspaces": store.workspace_directory_list()}


@admin_router.post("/{user_id}/approve")
async def admin_approve_account(user_id: str, request: Request):
    payload = await _read_json(request)
    admin = require_admin(request)
    store = get_account_store()
    approved = store.approve_user(
        user_id,
        role_template=payload.get("role_template", "payroll_specialist"),
        permissions=payload.get("permissions"),
        display_name=payload.get("display_name"),
        note=payload.get("note"),
    )
    audit_event(admin, "account.approve", run_id=approved["workspace_id"], detail="approved")
    return {
        "ok": True,
        "user": public_user(approved),
        "users": store.users(),
        "pending_count": store.pending_count(),
        "workspaces": store.workspace_directory_list(),
    }


@admin_router.post("/{user_id}/reject")
async def admin_reject_account(user_id: str, request: Request):
    await _read_json(request)
    admin = require_admin(request)
    store = get_account_store()
    rejected = store.reject_user(user_id)
    audit_event(admin, "account.reject", run_id=rejected["workspace_id"], detail="rejected")
    return {
        "ok": True,
        "user": public_user(rejected),
        "users": store.users(),
        "pending_count": store.pending_count(),
    }


@admin_router.put("/{user_id}")
async def admin_update_account(user_id: str, request: Request):
    payload = await _read_json(request)
    admin = require_admin(request)
    store = get_account_store()
    updated = store.update_user_access(
        user_id,
        display_name=payload.get("display_name"),
        role_template=payload.get("role_template"),
        permissions=payload.get("permissions"),
        enabled=payload.get("enabled"),
        note=payload.get("note"),
    )
    audit_event(admin, "account.update", run_id=updated["workspace_id"], detail="enabled" if updated["enabled"] else "disabled")
    return {
        "ok": True,
        "user": public_user(updated),
        "users": store.users(),
        "pending_count": store.pending_count(),
        "workspaces": store.workspace_directory_list(),
    }


@admin_router.post("/{user_id}/reset-password")
async def admin_reset_password(user_id: str, request: Request):
    payload = await _read_json(request)
    admin = require_admin(request)
    store = get_account_store()
    store.reset_password(user_id, payload.get("new_password", ""))
    audit_event(admin, "account.password.reset", detail="success")
    return {"ok": True, "message": "已重置该成员登录密码并使其旧登录会话失效"}


@admin_router.post("/{user_id}/sync-default-config")
async def admin_sync_default_config(user_id: str, request: Request):
    await _read_json(request)
    admin = require_admin(request)
    store = get_account_store()
    users = store.users()
    target = next((u for u in users if u["id"] == user_id), None)
    if target is None:
        raise HTTPException(404, "成员不存在")
    wid = target["workspace_id"]
    if not is_isolated_workspace(wid):
        raise HTTPException(400, "管理员主空间本身即为标准默认扣款模板源")
    src = PROJECT_ROOT / "data" / "config.json"
    if not src.is_file():
        raise HTTPException(404, "主机标准默认扣款配置不存在")
    dst = workspace_config_path(wid)
    dst.parent.mkdir(parents=True, exist_ok=True)
    if dst.is_file():
        backup = dst.parent / "config_history" / (datetime.now().strftime("%Y%m%d_%H%M%S_%f") + ".json")
        backup.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(dst, backup)
    shutil.copy2(src, dst)
    audit_event(admin, "account.config.sync", run_id=wid, detail="success")
    return {"ok": True, "message": f"已将最新标准默认扣款配置同步至 {target['display_name']} 的独立空间"}


@admin_router.get("/audit")
def admin_audit_logs(request: Request):
    require_admin(request)
    return {"events": get_account_store().audit_events()}
