"""城市清单以风神「物流合作商」分组为数据源，本地只做缓存与离线兜底。

风神 switchableAgency 同时返回总商、物流合作商和物流服务商；下载中心只使用
物流合作商分组下的城市，城市显示名取 agencyCityName，城市编号取 agencyId。
"""
import datetime as dt
import json
import os
from pathlib import Path
import re
import tempfile
import threading
import time

ROOT = Path(__file__).resolve().parent
STATIC_FILE = ROOT / "fengshen_cities.json"
CACHE_FILE = ROOT / ".local_downloads" / "cities.json"
CACHE_SECONDS = 300
PARTNER_GROUP = "物流合作商"
CODE_PATTERN = re.compile(r"\d{1,20}")
# 业务已下架但风神可能仍返回的城市：保留编号用于历史任务解析，不再允许新建下载。
OFF_SHELF_CITIES = frozenset({"大连", "保定"})

_lock = threading.Lock()


class CityCatalogError(RuntimeError):
    pass


def _mapping(value):
    if not isinstance(value, dict) or not value:
        return None
    result = {}
    for name, code in value.items():
        if not isinstance(name, str) or not name.strip():
            return None
        code = str(code)
        if not CODE_PATTERN.fullmatch(code):
            return None
        result[name.strip()] = code
    return result or None


def _read_json(path):
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, UnicodeError):
        return None
    return value if isinstance(value, dict) else None


def static_cities():
    cities = _mapping(_read_json(STATIC_FILE))
    if cities is None:
        raise CityCatalogError("城市配置无法读取，请联系管理员")
    return cities


def _cache():
    data = _read_json(CACHE_FILE)
    if not data:
        return None
    cities = _mapping(data.get("cities"))
    fetched_at = data.get("fetched_at")
    if cities is None or not isinstance(fetched_at, (int, float)) or isinstance(fetched_at, bool):
        return None
    retired = _mapping(data.get("retired")) or {}
    return {"cities": cities,
            "retired": {name: code for name, code in retired.items() if name not in cities},
            "fetched_at": float(fetched_at),
            "updated_at": str(data.get("updated_at") or "")}


def _write_cache(cities, retired, fetched_at):
    payload = {"fetched_at": fetched_at,
               "updated_at": dt.datetime.fromtimestamp(fetched_at).astimezone().isoformat(timespec="seconds"),
               "cities": cities, "retired": retired}
    CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=CACHE_FILE.parent, suffix=".part", delete=False,
                                         mode="w", encoding="utf-8") as target:
            temporary = Path(target.name)
            json.dump(payload, target, ensure_ascii=False, indent=1)
            target.write("\n")
        os.replace(temporary, CACHE_FILE)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def _fetch():
    """只读取可切换合作商列表，不触发登录、不切换当前城市。"""
    from fengshen_auth import SessionVault
    from fengshen_http import AGENCIES_URL, FengshenHttpClient

    state = SessionVault().load()
    if state is None:
        raise CityCatalogError("尚未保存风神会话")
    client = FengshenHttpClient(state)
    client.timeout = (4, 6)
    client.attempts = 1
    try:
        payload = client.request_json("GET", AGENCIES_URL)
    finally:
        client.close()
    rows = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(rows, list):
        raise CityCatalogError("风神城市清单格式变化")
    cities = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        if str(row.get("agencySubTypeName") or "").strip() != PARTNER_GROUP:
            continue
        name = str(row.get("agencyCityName") or "").strip()
        code = str(row.get("agencyId") or "")
        if not name or not CODE_PATTERN.fullmatch(code):
            continue
        cities.setdefault(name, code)
    if not cities:
        raise CityCatalogError("风神未返回可下载的物流合作商城市")
    return cities


def _snapshot(cache=None):
    cache = cache if cache is not None else _cache()
    if cache is not None:
        return {"cities": cache["cities"], "source": "fengshen", "updated_at": cache["updated_at"]}
    return {"cities": static_cities(), "source": "config", "updated_at": ""}


def refresh(force=False):
    """同步一次风神城市清单；失败时保留上次成功结果，再退回本机配置。"""
    with _lock:
        cache = _cache()
        if cache is not None and not force and time.time() - cache["fetched_at"] < CACHE_SECONDS:
            return _snapshot(cache)
        try:
            cities = _fetch()
        except Exception:
            return _snapshot(cache)
        retired = dict(cache["retired"]) if cache is not None else {}
        if cache is not None:
            retired.update({name: code for name, code in cache["cities"].items() if name not in cities})
        fetched_at = time.time()
        try:
            _write_cache(cities, retired, fetched_at)
        except OSError:
            pass
        return {"cities": cities, "source": "fengshen",
                "updated_at": dt.datetime.fromtimestamp(fetched_at).astimezone().isoformat(timespec="seconds")}


def snapshot():
    return _snapshot()


def selectable_cities():
    """当前可在下载中心新建任务的城市，已下架城市不再提供。"""
    return {name: code for name, code in _snapshot()["cities"].items() if name not in OFF_SHELF_CITIES}


def all_cities():
    """执行期可解析的城市，含已下线的历史城市，避免旧任务无法定位编号。"""
    static = static_cities()
    cache = _cache()
    if cache is None:
        return static
    return {**static, **cache["retired"], **cache["cities"]}
