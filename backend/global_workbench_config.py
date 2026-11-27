"""Centralized host-admin workbench configuration: channel allocation, module visibility, and global naming.

Persisted atomically in JSON so all LAN clients sync channel modes (`personal` vs `shared`),
enabled business modules, navigation labels, and collection dataset card copy in real time.
"""

import json
import os
from pathlib import Path
import re
import tempfile
import threading
import time

from fastapi import HTTPException

from workspace_context import PROJECT_ROOT

PLATFORM_CHANNEL_KEYS = (
    "fengshen",
    "lanorange",
    "lanorange_mdr",
    "baize",
    "xiaoxiang",
    "benlai",
)

PLATFORM_DEFAULT_LABELS = {
    "fengshen": "风神",
    "lanorange": "蓝橙",
    "lanorange_mdr": "新蓝橙",
    "baize": "商翼",
    "xiaoxiang": "小象灯塔",
    "benlai": "本来人力",
}

DEFAULT_CHANNEL_MODES = {
    "fengshen": "personal",
    "lanorange": "personal",
    "lanorange_mdr": "personal",
    "baize": "personal",
    "xiaoxiang": "shared",
    "benlai": "shared",
}

BUSINESS_MODULE_KEYS = ("collection", "reports", "payroll", "approval")

DEFAULT_MODULE_PERMISSIONS = {
    "collection": True,
    "reports": True,
    "payroll": True,
    "approval": True,
}

DEFAULT_GROUP_NAMES = {
    "collection": "数据采集",
    "reports": "业务报表",
    "payroll": "薪资核算",
    "admin": "平台管理",
}

DEFAULT_ITEM_NAMES = {
    "platform:fengshen": "风神数据",
    "platform:lanorange": "蓝橙数据",
    "platform:lanorange_mdr": "新蓝橙数据",
    "platform:payout": "发薪平台",
    "platform:xiaoxiang": "小象灯塔",
    "workspace:history": "任务下载",
    "report:payment_binding": "支付绑定",
    "report:abnormal_followup": "异常跟进",
    "report:abnormal_riders": "异常名单",
    "report:problem": "问题单",
    "payroll:batches": "兼职核算",
    "payroll:deductions": "扣款配置",
    "payroll:templates": "模板中心",
    "workspace:approval": "价格审批",
    "workspace:pickup": "组内共享",
    "workspace:platform-auth": "授权管理",
    "workspace:accounts": "用户权限分配",
    "workspace:global-config": "全局配置",
}

_CTRL_RE = re.compile(r"[\x00-\x1f\x7f]")
_CONFIG_LOCK = threading.RLock()
_CONFIG_PATH: Path | None = None
_CACHE: dict | None = None
_CACHE_MTIME_NS: int | None = None
_CACHE_PATH: Path | None = None


def config_path() -> Path:
    if _CONFIG_PATH is not None:
        return _CONFIG_PATH
    env_path = os.environ.get("WORKBENCH_GLOBAL_CONFIG_PATH", "").strip()
    if env_path:
        return Path(env_path)
    return PROJECT_ROOT / "data" / "workbench_global_config.json"


def _clean_str(value, max_len: int, field_label: str) -> str:
    if value is None:
        return ""
    if not isinstance(value, str):
        raise HTTPException(400, f"{field_label}必须是文本")
    cleaned = _CTRL_RE.sub("", value).strip()
    if len(cleaned) > max_len:
        raise HTTPException(400, f"{field_label}长度不能超过 {max_len} 个字符")
    return cleaned


def default_global_config(*, version: int = 1, updated_at: float = 0.0) -> dict:
    return {
        "version": int(version),
        "updated_at": float(updated_at),
        "channel_modes": dict(DEFAULT_CHANNEL_MODES),
        "module_permissions": dict(DEFAULT_MODULE_PERMISSIONS),
        "module_names": {
            "groups": {},
            "items": {},
        },
        "dataset_overrides": {},
    }


def _normalize_config(raw: dict | None) -> dict:
    base = default_global_config(
        version=raw.get("version", 1) if isinstance(raw, dict) and isinstance(raw.get("version"), int) and raw.get("version") >= 1 else 1,
        updated_at=float(raw.get("updated_at", 0.0)) if isinstance(raw, dict) and isinstance(raw.get("updated_at"), (int, float)) else 0.0,
    )
    if not isinstance(raw, dict):
        return base

    raw_channels = raw.get("channel_modes")
    if isinstance(raw_channels, dict):
        for key in PLATFORM_CHANNEL_KEYS:
            val = raw_channels.get(key)
            if val in ("personal", "shared"):
                base["channel_modes"][key] = val

    raw_modules = raw.get("module_permissions")
    if isinstance(raw_modules, dict):
        for key in BUSINESS_MODULE_KEYS:
            if isinstance(raw_modules.get(key), bool):
                base["module_permissions"][key] = raw_modules[key]

    raw_names = raw.get("module_names")
    if isinstance(raw_names, dict):
        raw_groups = raw_names.get("groups")
        if isinstance(raw_groups, dict):
            for key, default_val in DEFAULT_GROUP_NAMES.items():
                val = raw_groups.get(key)
                if isinstance(val, str):
                    cleaned = _CTRL_RE.sub("", val).strip()[:40]
                    if cleaned and cleaned != default_val:
                        base["module_names"]["groups"][key] = cleaned
        raw_items = raw_names.get("items")
        if isinstance(raw_items, dict):
            for key, default_val in DEFAULT_ITEM_NAMES.items():
                val = raw_items.get(key)
                if isinstance(val, str):
                    cleaned = _CTRL_RE.sub("", val).strip()[:40]
                    if cleaned and cleaned != default_val:
                        base["module_names"]["items"][key] = cleaned

    raw_datasets = raw.get("dataset_overrides")
    if isinstance(raw_datasets, dict):
        for ds_id, entry in raw_datasets.items():
            if not isinstance(ds_id, str) or not re.fullmatch(r"[A-Za-z0-9_.-]{1,64}", ds_id):
                continue
            if not isinstance(entry, dict):
                continue
            cleaned_entry = {}
            if isinstance(entry.get("title"), str):
                title = _CTRL_RE.sub("", entry["title"]).strip()[:40]
                if title:
                    cleaned_entry["title"] = title
            if isinstance(entry.get("desc"), str):
                desc = _CTRL_RE.sub("", entry["desc"]).strip()[:160]
                if desc:
                    cleaned_entry["desc"] = desc
            if cleaned_entry:
                base["dataset_overrides"][ds_id] = cleaned_entry

    return base


def _clone(cfg: dict) -> dict:
    return {
        "version": cfg["version"],
        "updated_at": cfg["updated_at"],
        "channel_modes": dict(cfg["channel_modes"]),
        "module_permissions": dict(cfg["module_permissions"]),
        "module_names": {
            "groups": dict(cfg["module_names"]["groups"]),
            "items": dict(cfg["module_names"]["items"]),
        },
        "dataset_overrides": {k: dict(v) for k, v in cfg["dataset_overrides"].items()},
    }


def _persist_locked(cfg: dict) -> dict:
    global _CACHE, _CACHE_MTIME_NS, _CACHE_PATH
    target = config_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(cfg, ensure_ascii=False, indent=2)
    tmp = None
    try:
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=target.parent, suffix=".tmp", delete=False) as f:
            tmp = Path(f.name)
            f.write(payload)
        os.replace(tmp, target)
    finally:
        if tmp is not None:
            tmp.unlink(missing_ok=True)
    _CACHE = _clone(cfg)
    _CACHE_PATH = target
    try:
        _CACHE_MTIME_NS = target.stat().st_mtime_ns
    except OSError:
        _CACHE_MTIME_NS = None
    return _clone(cfg)


def get_global_config() -> dict:
    global _CACHE, _CACHE_MTIME_NS, _CACHE_PATH
    with _CONFIG_LOCK:
        target = config_path()
        try:
            st = target.stat()
            mtime_ns = st.st_mtime_ns
        except OSError:
            mtime_ns = None
        if _CACHE is not None and _CACHE_PATH == target and _CACHE_MTIME_NS == mtime_ns:
            return _clone(_CACHE)
        raw = None
        if mtime_ns is not None:
            try:
                raw = json.loads(target.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                raw = None
        normalized = _normalize_config(raw)
        _CACHE = _clone(normalized)
        _CACHE_PATH = target
        _CACHE_MTIME_NS = mtime_ns
        return _clone(normalized)


def update_global_config(patch: dict) -> dict:
    if not isinstance(patch, dict):
        raise HTTPException(400, "全局配置参数必须是 JSON 对象")
    with _CONFIG_LOCK:
        current = get_global_config()
        next_cfg = _clone(current)

        if "channel_modes" in patch:
            raw_channels = patch.get("channel_modes")
            if not isinstance(raw_channels, dict):
                raise HTTPException(400, "通道模式配置格式无效")
            for key, mode in raw_channels.items():
                if key not in PLATFORM_CHANNEL_KEYS:
                    raise HTTPException(400, f"未知平台通道：{key}")
                if mode not in ("personal", "shared"):
                    raise HTTPException(400, f"平台 {key} 的通道模式仅支持 personal 或 shared")
                next_cfg["channel_modes"][key] = mode

        if "module_permissions" in patch:
            raw_modules = patch.get("module_permissions")
            if not isinstance(raw_modules, dict):
                raise HTTPException(400, "业务模块开关格式无效")
            for key, flag in raw_modules.items():
                if key not in BUSINESS_MODULE_KEYS:
                    raise HTTPException(400, f"未知业务模块：{key}")
                if type(flag) is not bool:
                    raise HTTPException(400, f"模块开关 {key} 必须为布尔值")
                next_cfg["module_permissions"][key] = flag

        if "module_names" in patch:
            raw_names = patch.get("module_names")
            if not isinstance(raw_names, dict):
                raise HTTPException(400, "模块名称配置格式无效")
            if "groups" in raw_names:
                raw_groups = raw_names.get("groups")
                if not isinstance(raw_groups, dict):
                    raise HTTPException(400, "一级模块名称格式无效")
                merged_groups = dict(next_cfg["module_names"]["groups"])
                for key, val in raw_groups.items():
                    if key not in DEFAULT_GROUP_NAMES:
                        raise HTTPException(400, f"未知一级模块：{key}")
                    cleaned = _clean_str(val, 40, "一级模块名称")
                    if cleaned and cleaned != DEFAULT_GROUP_NAMES[key]:
                        merged_groups[key] = cleaned
                    else:
                        merged_groups.pop(key, None)
                next_cfg["module_names"]["groups"] = merged_groups
            if "items" in raw_names:
                raw_items = raw_names.get("items")
                if not isinstance(raw_items, dict):
                    raise HTTPException(400, "子模块名称格式无效")
                merged_items = dict(next_cfg["module_names"]["items"])
                for key, val in raw_items.items():
                    if key not in DEFAULT_ITEM_NAMES:
                        raise HTTPException(400, f"未知子模块：{key}")
                    cleaned = _clean_str(val, 40, "子模块名称")
                    if cleaned and cleaned != DEFAULT_ITEM_NAMES[key]:
                        merged_items[key] = cleaned
                    else:
                        merged_items.pop(key, None)
                next_cfg["module_names"]["items"] = merged_items

        if "dataset_overrides" in patch:
            raw_datasets = patch.get("dataset_overrides")
            if not isinstance(raw_datasets, dict):
                raise HTTPException(400, "资料名称配置格式无效")
            merged_datasets = {k: dict(v) for k, v in next_cfg["dataset_overrides"].items()}
            for ds_id, entry in raw_datasets.items():
                if not isinstance(ds_id, str) or not re.fullmatch(r"[A-Za-z0-9_.-]{1,64}", ds_id):
                    raise HTTPException(400, f"资料标识无效：{ds_id}")
                if entry is None:
                    merged_datasets.pop(ds_id, None)
                    continue
                if not isinstance(entry, dict):
                    raise HTTPException(400, f"资料 {ds_id} 配置格式无效")
                title = _clean_str(entry.get("title"), 40, "资料名称") if "title" in entry else merged_datasets.get(ds_id, {}).get("title", "")
                desc = _clean_str(entry.get("desc"), 160, "资料副标题") if "desc" in entry else merged_datasets.get(ds_id, {}).get("desc", "")
                cleaned_entry = {}
                if title:
                    cleaned_entry["title"] = title
                if desc:
                    cleaned_entry["desc"] = desc
                if cleaned_entry:
                    merged_datasets[ds_id] = cleaned_entry
                else:
                    merged_datasets.pop(ds_id, None)
            next_cfg["dataset_overrides"] = merged_datasets

        next_cfg["version"] = current["version"] + 1
        next_cfg["updated_at"] = time.time()
        return _persist_locked(next_cfg)


def reset_global_config(section: str = "all") -> dict:
    if section not in ("all", "channels", "module_names", "datasets", "naming"):
        raise HTTPException(400, "不支持的还原范围")
    with _CONFIG_LOCK:
        current = get_global_config()
        next_cfg = _clone(current)
        if section == "all":
            next_cfg = default_global_config(version=current["version"] + 1, updated_at=time.time())
            return _persist_locked(next_cfg)
        if section == "channels":
            next_cfg["channel_modes"] = dict(DEFAULT_CHANNEL_MODES)
            next_cfg["module_permissions"] = dict(DEFAULT_MODULE_PERMISSIONS)
        elif section == "module_names":
            next_cfg["module_names"] = {"groups": {}, "items": {}}
        elif section == "datasets":
            next_cfg["dataset_overrides"] = {}
        elif section == "naming":
            next_cfg["module_names"] = {"groups": {}, "items": {}}
            next_cfg["dataset_overrides"] = {}
        next_cfg["version"] = current["version"] + 1
        next_cfg["updated_at"] = time.time()
        return _persist_locked(next_cfg)


def config_version() -> int:
    return int(get_global_config().get("version", 1))


def shared_sources() -> frozenset[str]:
    modes = get_global_config()["channel_modes"]
    return frozenset(key for key in PLATFORM_CHANNEL_KEYS if modes.get(key) == "shared")


def is_shared_source(source: str) -> bool:
    return get_global_config()["channel_modes"].get(source) == "shared"


def module_enabled(module_key: str) -> bool:
    return bool(get_global_config()["module_permissions"].get(module_key, True))


def platform_label(source: str) -> str:
    return PLATFORM_DEFAULT_LABELS.get(source, source)
