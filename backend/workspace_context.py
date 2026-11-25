"""Workspace context propagation, directory isolation, and concurrency guards."""

from contextlib import contextmanager
import contextvars
import json
import os
from pathlib import Path
import re
import shutil
import threading

PRIMARY_WORKSPACE = "download_shared"
PROJECT_ROOT = Path(__file__).resolve().parent.parent
LOCAL_AUTH_ROOT = Path(__file__).resolve().parent / ".local_auth"

_WORKSPACE_RE = re.compile(r"^[\w-]{1,128}$")
_CURRENT_WORKSPACE: contextvars.ContextVar[str] = contextvars.ContextVar(
    "current_workspace", default=PRIMARY_WORKSPACE
)
_CURRENT_USER: contextvars.ContextVar[dict | None] = contextvars.ContextVar(
    "current_user", default=None
)

_INIT_LOCK = threading.RLock()
_LOGIN_BROWSER_SLOTS = threading.BoundedSemaphore(
    max(1, int(os.environ.get("MAX_CONCURRENT_AUTH_BROWSERS", "3")))
)
_HEAVY_COMPUTE_SLOTS = threading.BoundedSemaphore(
    max(1, int(os.environ.get("MAX_CONCURRENT_PAYROLL_WORKERS", "2")))
)


def valid_workspace_id(wid: str | None) -> str:
    value = (wid or "").strip()
    if not value or not _WORKSPACE_RE.fullmatch(value):
        raise ValueError("工作空间标识无效")
    return value


def is_isolated_workspace(wid: str | None) -> bool:
    return bool(wid and wid != PRIMARY_WORKSPACE and wid.startswith("ws_"))


def current_workspace() -> str:
    return _CURRENT_WORKSPACE.get() or PRIMARY_WORKSPACE


def current_user() -> dict | None:
    return _CURRENT_USER.get()


@contextmanager
def bind_workspace(wid: str | None, user: dict | None = None):
    resolved = valid_workspace_id(wid) if wid else PRIMARY_WORKSPACE
    tok_ws = _CURRENT_WORKSPACE.set(resolved)
    tok_user = _CURRENT_USER.set(user)
    try:
        yield resolved
    finally:
        _CURRENT_USER.reset(tok_user)
        _CURRENT_WORKSPACE.reset(tok_ws)


def spawn_in_context(target, *args, name: str | None = None, daemon: bool = True, **kwargs) -> threading.Thread:
    """Spawn a daemon/worker thread that inherits the caller's ContextVars."""
    ctx = contextvars.copy_context()

    def _wrapped():
        return ctx.run(target, *args, **kwargs)

    return threading.Thread(target=_wrapped, name=name, daemon=daemon)


def initialize_workspace_storage(wid: str, root: Path | str | None = None) -> Path:
    """Ensure isolated colleague workspace directories and default config copy exist."""
    wid = valid_workspace_id(wid)
    base = Path(root or PROJECT_ROOT).resolve()
    if not is_isolated_workspace(wid):
        data_dir = base / "data"
        data_dir.mkdir(parents=True, exist_ok=True)
        cfg = data_dir / "config.json"
        if not cfg.exists():
            cfg.write_text("[]", encoding="utf-8")
        return base

    ws_root = (base / "workspaces" / wid).resolve()
    if not ws_root.is_relative_to((base / "workspaces").resolve()):
        raise ValueError("工作空间路径越界")

    with _INIT_LOCK:
        ws_data = ws_root / "data"
        ws_data.mkdir(parents=True, exist_ok=True)
        target_cfg = ws_data / "config.json"
        if not target_cfg.exists():
            template_cfg = base / "data" / "config.json"
            if template_cfg.is_file() and not template_cfg.is_symlink():
                try:
                    raw = json.loads(template_cfg.read_text(encoding="utf-8-sig"))
                    if isinstance(raw, list):
                        target_cfg.write_text(
                            json.dumps(raw, ensure_ascii=False, indent=2),
                            encoding="utf-8",
                        )
                    else:
                        target_cfg.write_text("[]", encoding="utf-8")
                except (OSError, ValueError):
                    target_cfg.write_text("[]", encoding="utf-8")
            else:
                target_cfg.write_text("[]", encoding="utf-8")

        template_bp = base / "data" / "binding_platforms.json"
        target_bp = ws_data / "binding_platforms.json"
        if not target_bp.exists() and template_bp.is_file() and not template_bp.is_symlink():
            try:
                shutil.copy2(template_bp, target_bp)
            except OSError:
                pass

        (base / "uploads" / wid).mkdir(parents=True, exist_ok=True)
        (base / "outputs" / "workspaces" / wid / "fengshen_downloads").mkdir(parents=True, exist_ok=True)
        if root is None:
            (LOCAL_AUTH_ROOT / "workspaces" / wid).mkdir(parents=True, exist_ok=True)

    return ws_root


def workspace_data_root(wid: str | None = None, root: Path | str | None = None) -> Path:
    """Return the root folder whose `data/` subdirectory belongs to `wid`."""
    resolved_wid = wid or current_workspace()
    base = Path(root or PROJECT_ROOT).resolve()
    if is_isolated_workspace(resolved_wid):
        return initialize_workspace_storage(resolved_wid, base)
    return base


def workspace_config_path(wid: str | None = None, root: Path | str | None = None) -> Path:
    return workspace_data_root(wid, root) / "data" / "config.json"


def workspace_uploads_dir(wid: str | None = None, root: Path | str | None = None) -> Path:
    resolved_wid = valid_workspace_id(wid or current_workspace())
    base = Path(root or PROJECT_ROOT).resolve()
    target = (base / "uploads" / resolved_wid).resolve()
    if not target.is_relative_to((base / "uploads").resolve()):
        raise ValueError("上传目录越界")
    target.mkdir(parents=True, exist_ok=True)
    return target


def workspace_output_root(wid: str | None = None, root: Path | str | None = None) -> Path:
    resolved_wid = wid or current_workspace()
    base = Path(root or PROJECT_ROOT).resolve()
    if is_isolated_workspace(resolved_wid):
        target = (base / "outputs" / "workspaces" / resolved_wid / "fengshen_downloads").resolve()
        target.mkdir(parents=True, exist_ok=True)
        return target
    env_root = os.environ.get("FENGSHEN_DOWNLOAD_ROOT", "").strip()
    if env_root and root is None:
        return Path(env_root).resolve()
    target = (base / "outputs" / "fengshen_downloads").resolve()
    target.mkdir(parents=True, exist_ok=True)
    return target


def workspace_auth_dir(wid: str | None = None) -> Path:
    """Return `.local_auth` directory for personal platform sessions (non-Xiaoxiang)."""
    resolved_wid = wid or current_workspace()
    if is_isolated_workspace(resolved_wid):
        target = (LOCAL_AUTH_ROOT / "workspaces" / valid_workspace_id(resolved_wid)).resolve()
        if not target.is_relative_to((LOCAL_AUTH_ROOT / "workspaces").resolve()):
            raise ValueError("认证会话目录越界")
        target.mkdir(parents=True, exist_ok=True)
        return target
    LOCAL_AUTH_ROOT.mkdir(parents=True, exist_ok=True)
    return LOCAL_AUTH_ROOT


@contextmanager
def acquire_login_browser_slot(timeout: float = 4.0):
    acquired = _LOGIN_BROWSER_SLOTS.acquire(timeout=timeout)
    if not acquired:
        from fastapi import HTTPException
        raise HTTPException(429, "当前多位同事正在进行平台登录验证，请稍候几秒后再试")
    try:
        yield
    finally:
        _LOGIN_BROWSER_SLOTS.release()


@contextmanager
def acquire_heavy_compute_slot():
    _HEAVY_COMPUTE_SLOTS.acquire()
    try:
        yield
    finally:
        _HEAVY_COMPUTE_SLOTS.release()
