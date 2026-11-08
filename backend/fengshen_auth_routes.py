"""Fengshen login control for local and same-origin private-network clients."""

import asyncio
import ipaddress
from urllib.parse import unquote, urlparse

from fastapi import APIRouter, HTTPException, Request, Body

from fengshen_auth import AuthError, BROKER
from fengshen_http_auth import start_http_login

router = APIRouter(prefix="/api/parttime/fengshen/auth")


def _workspace_owner(request):
    try:
        owner = unquote(request.headers.get("x-workspace-id", ""), errors="strict")
    except (UnicodeError, ValueError):
        raise HTTPException(400, "缺少有效工作区标识") from None
    if not owner or len(owner) > 128 or any(c not in "_-" and not c.isalnum() for c in owner):
        raise HTTPException(400, "缺少有效工作区标识")
    if owner.casefold().startswith("account_"):
        raise HTTPException(403, "下载账号须通过下载中心登录，不能使用工作区标识代替")
    if request.method != "GET" and request.headers.get("content-type", "").split(";", 1)[0] != "application/json":
        raise HTTPException(415, "登录请求必须使用 JSON")
    return owner


def local_owner(request):
    """Retain loopback-only access for other workflows importing this helper."""
    host = (request.url.hostname or "").lower()
    if host not in ("localhost", "127.0.0.1", "::1"):
        raise HTTPException(403, "登录功能仅供本机使用")
    origin = request.headers.get("origin")
    if origin:
        parsed = urlparse(origin)
        if parsed.scheme not in ("http", "https") or parsed.hostname not in ("localhost", "127.0.0.1", "::1"):
            raise HTTPException(403, "不允许外部网页操作本机会话")
    return _workspace_owner(request)


_PRIVATE_V4 = tuple(ipaddress.ip_network(network) for network in ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16"))
_PRIVATE_V6 = ipaddress.ip_network("fc00::/7")


def _allowed_host(host):
    if host == "localhost":
        return True, True
    if not host or "%" in host:
        return False, False
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return False, False
    if address.is_unspecified or address.is_multicast:
        return False, False
    if address.is_loopback:
        return True, True
    private = (any(address in network for network in _PRIVATE_V4) if address.version == 4
               else address in _PRIVATE_V6)
    return private, False


def _origin_tuple(scheme, hostname, port):
    return scheme.lower(), (hostname or "").lower(), port if port is not None else (443 if scheme.lower() == "https" else 80)


def auth_owner(request):
    """Allow literal private hosts while requiring same-origin browser writes.

    The Node authentication proxy preserves the original Host header. Forwarded
    headers are intentionally ignored: arbitrary DNS names and public addresses
    must not become trusted through client-supplied proxy metadata.
    """
    if request.headers.get("x-download-account") == "1":
        from download_accounts import require_account
        return require_account(request)["owner"]
    try:
        host = (request.url.hostname or "").lower()
        allowed, loopback = _allowed_host(host)
        request_origin = _origin_tuple(request.url.scheme, host, request.url.port)
    except (ValueError, UnicodeError):
        raise HTTPException(403, "登录访问地址无效") from None
    if not allowed or request.url.scheme not in ("http", "https"):
        raise HTTPException(403, "登录功能仅允许本机或局域网 IP 地址访问")
    origin = request.headers.get("origin")
    if origin:
        try:
            parsed = urlparse(origin)
            valid = (parsed.scheme in ("http", "https") and parsed.hostname and parsed.username is None
                     and parsed.password is None and parsed.path in ("", "/") and not parsed.query
                     and not parsed.fragment
                     and _origin_tuple(parsed.scheme, parsed.hostname, parsed.port) == request_origin)
        except (ValueError, UnicodeError):
            valid = False
        if not valid:
            raise HTTPException(403, "登录请求必须来自当前系统页面，地址、协议和端口须一致")
    elif not loopback and request.method != "GET":
        raise HTTPException(403, "局域网登录操作必须从当前系统页面发起")
    return _workspace_owner(request)


@router.get("/status")
def status(request: Request):
    result = BROKER.status(auth_owner(request))
    from platform_auth_control import status as platform_status
    identity = platform_status('fengshen')
    result.update({key: identity[key] for key in ('session_version', 'account_label', 'organization') if key in identity})
    # Idle login always uses the in-page HTTP flow. Preserve an existing active
    # operation's real transport rather than mislabelling a legacy challenge.
    if not result.get("busy"):
        result = {**result, "transport": "http"}
    return result


@router.post("/start")
def start(request: Request):
    owner = auth_owner(request)
    from platform_auth_control import operation, META
    with operation('fengshen'):
        META.pop('fengshen', None)
        result = start_http_login(owner)
    if not result.get("busy"):
        result = {**result, "transport": "http"}
    return {"ok": True, "status": result}


@router.post("/clear")
def clear(request: Request, data: dict = Body(default=None)):
    owner = auth_owner(request)
    if BROKER.active:
        raise HTTPException(409, '风神认证或采集正在进行，请结束后再退出连接')
    if not isinstance(data, dict) or not isinstance(data.get('session_version'), str) or data.get('confirm') is not True:
        raise HTTPException(409, '退出确认已过期，请刷新连接状态后重新确认')
    from platform_auth_control import disconnect
    disconnect('fengshen', data['session_version'])
    return {"ok": True, "status": BROKER.status(owner)}


@router.post("/{action}")
async def command(action: str, request: Request):
    owner = auth_owner(request)
    try:
        data = await request.json()
        if not isinstance(data, dict):
            raise AuthError("登录参数无效")
        challenge = data.get("challenge_id", "")
        value = data.get("phone" if action == "send" else "code", "")
        if not isinstance(challenge, str) or not isinstance(value, str):
            raise AuthError("登录参数无效")
        future = BROKER.submit(owner, challenge, action, value.strip())
        if future is None:
            return {"ok": True, "message": "登录已取消，任务已停止"}
        try:
            return await asyncio.wait_for(asyncio.wrap_future(future), timeout=90)
        except asyncio.TimeoutError:
            message = "操作结果尚未确认，请重新检查状态；不会自动重发短信或重复提交"
            return {"ok": False, "message": message}
    except AuthError as exc:
        return {"ok": False, "message": str(exc)}
    except (ValueError, TypeError):
        return {"ok": False, "message": "登录参数无效"}
