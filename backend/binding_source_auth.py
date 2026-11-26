"""Authentication-only browser handoff; business downloads use HTTPS requests."""
import base64
import functools
import hashlib
import json
from datetime import datetime, timezone
from collections import deque
import secrets
import logging
import os
from pathlib import Path
import re
import tempfile
import threading
import time
from urllib.parse import unquote, urlparse, urljoin

import requests
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import Response
from download_accounts import can_manage_shared_auth, require_admin, require_account, require_shared_auth_manage
from fengshen_auth import dpapi
from fengshen_bill import BillCollectionError

_log = logging.getLogger(__name__)

SOURCES = {
    'lanorange': {'host': 'madouren.cdevelopment.cn', 'entry': '/admin/login', 'token': 'Admin-Token',
                  'label': '蓝橙', 'clientid': 'e5cd7e4891bf95d1d19206ce24a7b32e',
                  'dingtalk_qr': True,
                  # 钉钉授权会话一并加密保存，令牌过期时可直接确认跳转，不必重新扫码
                  'state_hosts': ('login.dingtalk.com', 'dingtalk.com')},
    'lanorange_mdr': {'host': 'mdr.lanchengsz.cn', 'entry': '/login', 'token': 'hr_admin_token',
                      'label': '新蓝橙', 'cookie_auth': True, 'identity_path': '/api/admin/userInfo',
                      'identity_codes': (200,), 'dingtalk_qr': True,
                      'state_hosts': ('login.dingtalk.com', 'dingtalk.com')},
    'baize': {'host': 'merchant.shangyiworker.com', 'entry': '/freelancer/merchantFreelancer',
              'token': 'Yunke-Mer-Token', 'label': '白泽'},
    # 本来人力把登录态放在浏览器会话里：官方前端用 Cookies.get('fengxin-saas')
    # 拼接 Authorization，因此以加密 storage_state 为认证载体。
    'benlai': {'host': 'b.icp88.com', 'entry': '/login', 'label': '本来人力',
               'cookie_auth': True, 'identity_path': '/api/getUserInfo',
               'identity_codes': (0,), 'token': 'fengxin-saas'},
}
DINGTALK_CONFIRM_LABELS = ('同意', '确认登录', '确认授权', '继续登录')
_DEFAULT_AUTH_ROOT = Path(__file__).parent / '.local_auth'
ROOT = _DEFAULT_AUTH_ROOT
SHARED_SOURCES = frozenset({'benlai'})
STATE_LIMIT = 256 * 1024
KEEPALIVE_SECONDS = 300
CONSENT_TOGGLE = """(e,want)=>{
  if(!!e.checked===want)return true;
  let label=e.closest('label');
  if(!label&&e.labels&&e.labels.length)label=e.labels[0];
  (label||e).click();
  return !!e.checked===want;
}"""


def _configured_keepalive():
    try:
        return max(0, int(os.environ.get('SOURCE_AUTH_KEEPALIVE_SECONDS', str(KEEPALIVE_SECONDS))))
    except ValueError:
        return KEEPALIVE_SECONDS


KEEPALIVE_SECONDS = _configured_keepalive()


def _source_root(source: str) -> Path:
    if ROOT != _DEFAULT_AUTH_ROOT or source in SHARED_SOURCES:
        return ROOT
    from workspace_context import workspace_auth_dir
    return workspace_auth_dir()


def session_path(source):
    if source not in SOURCES:
        raise BillCollectionError('外部资料来源无效')
    return _source_root(source) / (source + '.dpapi')


def state_path(source):
    if source not in SOURCES:
        raise BillCollectionError('外部资料来源无效')
    return _source_root(source) / (source + '.storage')


def _write_encrypted(path, payload):
    encrypted = dpapi(payload)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, suffix='.encrypted.part', delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(encrypted)
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def _host_matches(domain, host):
    domain = str(domain or '').lower().lstrip('.')
    if domain == host:
        return True
    return '.' in domain and host.endswith('.' + domain)


def _safe_detail(exc):
    """异常摘要用于日志，去掉查询串里的临时令牌并截断。"""
    return ' '.join(str(exc).split()).split('?', 1)[0][:200]


def _response_diagnostic(response):
    """身份接口异常响应的安全摘要，用于区分网关拦截页、BOM 与编码异常。"""
    headers = getattr(response, 'headers', None) or {}
    content_type = headers.get('Content-Type', '?')
    raw = getattr(response, 'content', b'') or b''
    try: text = getattr(response, 'text', '') or ''
    except Exception: text = ''
    body = ''
    if 'json' not in str(content_type).lower() and not text.lstrip().startswith(('{', '[')):
        body = ' body=' + ' '.join(text.split())[:120]
    prefix = bytes(raw)[:24].hex() if isinstance(raw, (bytes, bytearray)) else ''
    return 'status=%s content_type=%s bytes=%s encrypted=%s prefix=%s%s' % (
        getattr(response, 'status_code', '?'), content_type, len(raw) or len(text),
        'yes' if headers.get('encrypt-key') else 'no', prefix, body)


# 商翼前端把响应解密私钥直接打包在 JS 里（jsencrypt 模块），服务器用对应公钥
# 加密本次 AES 密钥并通过 encrypt-key 响应头下发；这里复用同一套公开方案。
_BAIZE_RESPONSE_RSA_KEY = (
    'MIIBVAIBADANBgkqhkiG9w0BAQEFAASCAT4wggE6AgEAAkEAqhHyZfSsYourNxaY7Nt+PrgrxkiA50efORdI5U5lsW79MmFnusUA355oaSXcLhu5xxB38SMSyP2KvuKNPuH3owIDAQABAkAfoiLyL+Z4lf4Myxk6xUDgLaWGximj20CUf+5BKKnlrK+Ed8gAkM0HqoTt2UZwA5E2MzS4EI2gjfQhz5X28uqxAiEA3wNFxfrCZlSZHb0gn2zDpWowcSxQAgiCstxGUoOqlW8CIQDDOerGKH5OmCJ4Z21v+F25WaHYPxCFMvwxpcw99EcvDQIgIdhDTIqD2jfYjPTY8Jj3EDGPbH2HHuffvflECt3Ek60CIQCFRlCkHpi7hthhYhovyloRYsM+IS9h/0BzlEAuO0ktMQIgSPT3aFAgJYwKpqRYKlLDVcflZFCKY7u3UP8iWi1Qw0Y='
)


@functools.lru_cache(maxsize=1)
def _baize_response_private_key():
    from cryptography.hazmat.primitives import serialization
    return serialization.load_der_private_key(base64.b64decode(_BAIZE_RESPONSE_RSA_KEY), password=None)


def _decrypt_official_payload(text, header):
    from cryptography.hazmat.primitives import padding as sym_padding
    from cryptography.hazmat.primitives.asymmetric import padding as asym_padding
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
    key = base64.b64decode(_baize_response_private_key().decrypt(
        base64.b64decode(header), asym_padding.PKCS1v15()))
    if len(key) not in (16, 24, 32):
        raise ValueError('encrypted response key length unexpected')
    decryptor = Cipher(algorithms.AES(key), modes.ECB()).decryptor()
    padded = decryptor.update(base64.b64decode(text)) + decryptor.finalize()
    unpadder = sym_padding.PKCS7(128).unpadder()
    plain = unpadder.update(padded) + unpadder.finalize()
    return json.loads(plain.decode('utf-8'), strict=False)


def _response_json(response):
    """官方返回 200 JSON、响应加密或带 BOM/控制字符时尽量还原载荷。"""
    headers = getattr(response, 'headers', None) or {}
    header = headers.get('encrypt-key')
    if header:
        try:
            text = getattr(response, 'text', '') or ''
            if not text:
                text = bytes(getattr(response, 'content', b'') or b'').decode('ascii')
            return _decrypt_official_payload(text.strip(), header)
        except Exception:
            pass
    try:
        return response.json()
    except (ValueError, TypeError) as first:
        raw = getattr(response, 'content', b'') or b''
        encodings = []
        if isinstance(raw, (bytes, bytearray)):
            for encoding in ('utf-8-sig', getattr(response, 'encoding', None), 'gb18030'):
                if encoding and encoding not in encodings:
                    encodings.append(encoding)
        for encoding in encodings:
            try:
                return json.loads(bytes(raw).decode(encoding), strict=False)
            except (UnicodeDecodeError, ValueError, TypeError):
                continue
        try:
            return json.loads(getattr(response, 'text', '').lstrip('\ufeff'), strict=False)
        except (ValueError, TypeError, AttributeError):
            raise first


def _host_filter(hosts):
    hosts = tuple(str(item).lower() for item in hosts)

    def allowed(domain):
        domain = str(domain or '').lower().lstrip('.')
        return any(_host_matches(domain, item) or _host_matches(item, domain) for item in hosts)

    return allowed


def _state_for_hosts(state, hosts):
    """按域名筛出会话片段，用于重建上下文时保留钉钉授权、丢掉过期令牌。"""
    hosts = tuple(str(item).lower() for item in hosts)
    if not hosts:
        return None
    allowed = _host_filter(hosts)
    origins_allowed = tuple('https://' + item for item in hosts)
    cookies = [cookie for cookie in state.get('cookies', [])
               if isinstance(cookie, dict) and allowed(cookie.get('domain'))]
    origins = [origin for origin in state.get('origins', [])
               if isinstance(origin, dict) and origin.get('origin') in origins_allowed]
    if not cookies and not origins:
        return None
    return {'cookies': cookies, 'origins': origins}


def _scoped_state(source, state):
    if (not isinstance(state, dict) or not isinstance(state.get('cookies'), list)
            or not isinstance(state.get('origins'), list)):
        raise ValueError()
    hosts = (SOURCES[source]['host'],) + tuple(SOURCES[source].get('state_hosts', ()))
    allowed = _host_filter(hosts)
    origins_allowed = tuple('https://' + item for item in hosts)

    cookies = []
    for cookie in state['cookies']:
        if not isinstance(cookie, dict) or not allowed(cookie.get('domain')):
            continue
        name, value = cookie.get('name'), cookie.get('value')
        if not isinstance(name, str) or not isinstance(value, str):
            continue
        if not 0 < len(name) <= 128 or len(value) > 16384:
            continue
        cookies.append(cookie)
    origins = []
    for origin in state['origins']:
        if not isinstance(origin, dict) or origin.get('origin') not in origins_allowed:
            continue
        items = origin.get('localStorage')
        if not isinstance(items, list):
            continue
        origins.append({'origin': origin['origin'], 'localStorage': [
            item for item in items
            if isinstance(item, dict) and isinstance(item.get('name'), str) and isinstance(item.get('value'), str)
            and 0 < len(item['name']) <= 256 and len(item['value']) <= 65536]})
    if not cookies and not origins:
        raise ValueError()
    return {'cookies': cookies, 'origins': origins}


def _token_from_state(source, state):
    config = SOURCES[source]
    if config.get('cookie_auth'):
        # 浏览器会话本身就是凭据：用当前域下的 cookie/localStorage 名称生成
        # 稳定的会话标记，登录成功后新增的认证项会改变标记，错误状态不会被复用。
        names = set()
        for cookie in state.get('cookies', []):
            if isinstance(cookie, dict) and cookie.get('name') and _host_matches(cookie.get('domain'), config['host']):
                names.add(('cookie', str(cookie['name'])))
        for origin in state.get('origins', []):
            if not isinstance(origin, dict) or not str(origin.get('origin', '')).startswith('https://' + config['host']):
                continue
            for item in origin.get('localStorage', []):
                if isinstance(item, dict) and item.get('name'):
                    names.add(('storage', str(item['name'])))
        if not names:
            return None
        return 'cookie-' + hashlib.sha256(repr(sorted(names)).encode()).hexdigest()[:40]
    token = next((unquote(cookie['value']) for cookie in state.get('cookies', [])
                  if isinstance(cookie, dict) and cookie.get('name') == config['token']
                  and isinstance(cookie.get('value'), str) and _host_matches(cookie.get('domain'), config['host'])), None)
    for origin in state.get('origins', []):
        if not isinstance(origin, dict) or origin.get('origin') != 'https://' + config['host']:
            continue
        for item in origin.get('localStorage', []):
            if not isinstance(item, dict) or item.get('name') != config['token']:
                continue
            candidate = item.get('value')
            try: candidate = json.loads(candidate)
            except (TypeError, ValueError): pass
            if isinstance(candidate, str):
                token = candidate
    return token if isinstance(token, str) and 8 < len(token) < 16384 else None


def _mask_account(value):
    text = ''.join(str(value).split())
    if len(text) <= 4: return '****' if text else ''
    return text[:3] + '****' + text[-4:]


def _confirm_dingtalk(page):
    """钉钉已登录时授权页会停在确认步骤，点一下即可跳回蓝橙，不必重新扫码。"""
    parsed = urlparse(page.url)
    if parsed.scheme != 'https' or parsed.hostname != 'login.dingtalk.com':
        return None
    for label in DINGTALK_CONFIRM_LABELS:
        for locator in (page.get_by_role('button', name=label, exact=True).first,
                        page.get_by_text(label, exact=True).first):
            try:
                if locator.is_visible():
                    locator.click(timeout=2000)
                    return label
            except Exception:
                continue
    return None


def load_token(source):
    path = session_path(source)
    if not path.exists():
        return None
    if path.is_symlink() or path.stat().st_size > 65536:
        raise BillCollectionError('外部系统会话文件异常，请重新登录')
    try:
        data = json.loads(dpapi(path.read_bytes(), decrypt=True))
        token = data['token']
        if data['source'] != source or not isinstance(token, str) or not 8 < len(token) < 16384:
            raise ValueError()
        return token
    except Exception:
        raise BillCollectionError('外部系统本机会话无法解密，请重新登录') from None


def save_token(source, token):
    path = session_path(source)
    _write_encrypted(path, json.dumps({'source': source, 'token': token}).encode())


def credentials_path(source):
    if source not in ('baize', 'benlai'):
        raise BillCollectionError('此来源不支持保存登录凭据')
    return _source_root(source) / (source + '.credentials.dpapi')


def load_credentials(source):
    path = credentials_path(source)
    if not path.exists():
        return None
    if path.is_symlink() or path.stat().st_size > 16384:
        raise BillCollectionError('登录凭据文件异常，请重新保存')
    try:
        data = json.loads(dpapi(path.read_bytes(), decrypt=True))
        username, password = data.get('username'), data.get('password')
        if (data.get('source') != source or not isinstance(username, str) or not 1 <= len(username) <= 256
                or not isinstance(password, str) or not 1 <= len(password) <= 512):
            raise ValueError()
        return {'username': username, 'password': password}
    except Exception:
        raise BillCollectionError('登录凭据无法解密，请重新登录并保存') from None


def save_credentials(source, username, password):
    if (not isinstance(username, str) or not 1 <= len(username) <= 256
            or not isinstance(password, str) or not 1 <= len(password) <= 512):
        raise BillCollectionError('登录凭据格式无效')
    _write_encrypted(credentials_path(source),
                     json.dumps({'source': source, 'username': username, 'password': password}).encode())


def clear_credentials(source):
    if source not in ('baize', 'benlai'):
        return
    try:
        credentials_path(source).unlink(missing_ok=True)
    except OSError:
        pass


def load_state(source):
    path = state_path(source)
    if not path.exists():
        return None
    if path.is_symlink() or path.stat().st_size > STATE_LIMIT:
        raise BillCollectionError('外部系统浏览器会话文件异常，请重新登录')
    try:
        data = json.loads(dpapi(path.read_bytes(), decrypt=True))
        if data.get('source') != source:
            raise ValueError()
        return _scoped_state(source, data.get('state'))
    except Exception:
        raise BillCollectionError('外部系统本机浏览器会话无法解密，请重新登录') from None


def save_state(source, state):
    value = json.dumps({'source': source, 'state': _scoped_state(source, state)},
                       ensure_ascii=True, separators=(',', ':')).encode('utf-8')
    if len(value) > STATE_LIMIT:
        raise BillCollectionError('外部系统浏览器会话过大，未保存')
    _write_encrypted(state_path(source), value)


def _browser_cookies(source, state):
    config = SOURCES[source]
    cookies = []
    for cookie in (state or {}).get('cookies', []):
        if not isinstance(cookie, dict) or not _host_matches(cookie.get('domain'), config['host']):
            continue
        name, value = cookie.get('name'), cookie.get('value')
        if isinstance(name, str) and isinstance(value, str) and 0 < len(name) <= 128 and len(value) <= 16384:
            cookies.append({**cookie, 'domain': str(cookie.get('domain')).lstrip('.')})
    return cookies


def client(source, token=None, state=None):
    config = SOURCES[source]
    token = token or load_token(source)
    if not token:
        raise SourceAuthenticationRequired(config['label'] + '尚未登录，请在下载中心完成来源认证')
    session = requests.Session()
    session.headers.update({'Accept': 'application/json',
                            'Origin': 'https://' + config['host'], 'Referer': 'https://' + config['host'] + '/'})
    if not config.get('cookie_auth'):
        session.headers['Authorization'] = 'Bearer ' + token
    if config.get('clientid'):
        session.headers['clientid'] = config['clientid']
    if config.get('cookie_auth'):
        if source == 'benlai':
            session.headers.update({
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36',
                'Accept-Language': 'zh-CN,zh;q=0.9',
                'Referer': 'https://' + config['host'] + '/staff',
            })
        if state is None:
            try:
                state = load_state(source) if state_path(source).exists() else None
            except Exception:
                state = None
        for cookie in _browser_cookies(source, state):
            try:
                session.cookies.set(cookie['name'], cookie['value'], domain=cookie['domain'],
                                    path=cookie.get('path') or '/', secure=bool(cookie.get('secure')))
            except (TypeError, ValueError):
                continue
        # 官方 axios 拦截器发送 Authorization: Bearer Cookies.get('fengxin-saas')。
        token_cookie = next((str(cookie['value']) for cookie in _browser_cookies(source, state)
                             if cookie.get('name') == config['token'] and cookie.get('value')), None)
        if token_cookie:
            session.headers['Authorization'] = token_cookie if token_cookie.lower().startswith('bearer ') else 'Bearer ' + token_cookie
        # 官方前端把令牌存进 localStorage 时，同步带到 Authorization；
        # 统一从浏览器会话取，避免把令牌复制到其他文件。
        for origin in (state or {}).get('origins', []):
            if not isinstance(origin, dict) or origin.get('origin') != 'https://' + config['host']:
                continue
            for item in origin.get('localStorage', []):
                name = str(item.get('name', '')).lower() if isinstance(item, dict) else ''
                value = item.get('value') if isinstance(item, dict) else None
                if isinstance(value, str) and ('token' in name or 'authorization' in name) and value:
                    session.headers['Authorization'] = value if value.lower().startswith('bearer ') else 'Bearer ' + value
                    break
    if source == 'lanorange':
        session.headers['Content-Language'] = 'zh_CN'
        session.headers['Referer'] = 'https://' + config['host'] + '/admin/'
        session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36',
            'Accept-Language': 'zh-CN,zh;q=0.9',
            'Sec-Fetch-Dest': 'empty', 'Sec-Fetch-Mode': 'cors', 'Sec-Fetch-Site': 'same-origin',
        })
        # The official web session carries both the bearer header and its
        # first-party token cookie. Keep the same authenticated context for
        # streaming exports; never send this cookie to the other source.
        session.cookies.set(config['token'], token, domain=config['host'], path='/', secure=True)
    if source == 'baize':
        # 与浏览器一致的请求头，避免网关把身份探测当成脚本流量返回拦截页。
        session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36',
            'Accept-Language': 'zh-CN,zh;q=0.9',
        })
        # 官方网关会把缺少反爬 cookie 的请求回成 4KB 挑战体；复用浏览器
        # 会话里的 first-party cookie 才能拿到正常 JSON。
        if state is None:
            try:
                state = load_state(source) if state_path(source).exists() else None
            except Exception:
                state = None
        for cookie in _browser_cookies(source, state):
            try:
                session.cookies.set(cookie['name'], cookie['value'], domain=cookie['domain'],
                                    path=cookie.get('path') or '/', secure=bool(cookie.get('secure')))
            except (TypeError, ValueError):
                continue
    return session


class SourceAuthenticationRequired(BillCollectionError):
    pass


class SourceProbeUnavailable(BillCollectionError):
    pass


def identity(source, session, timeout=20):
    config = SOURCES[source]
    response = session.get('https://' + config['host'] + (config.get('identity_path') or '/prod-api/system/user/getInfo'),
                           timeout=timeout, allow_redirects=False)
    if response.status_code == 401 or (config.get('cookie_auth') and response.status_code == 403):
        raise SourceAuthenticationRequired('登录已失效，请重新认证')
    if response.status_code in (301, 302, 303, 307, 308):
        location = response.headers.get('Location', '')
        parsed = urlparse(urljoin('https://' + config['host'], location))
        own_login = parsed.hostname == config['host'] and (parsed.path.rstrip('/').endswith('/login') or parsed.fragment.rstrip('/').endswith('/login'))
        dingtalk_login = bool(config.get('dingtalk_qr')) and (parsed.hostname or '').endswith('dingtalk.com')
        if parsed.scheme == 'https' and (own_login or dingtalk_login):
            raise SourceAuthenticationRequired('官方身份接口要求重新登录')
    if response.status_code != 200:
        raise SourceProbeUnavailable('官方身份接口暂不可用或权限待确认；原会话保留')
    try: data = _response_json(response)
    except (ValueError, TypeError) as exc:
        _log.warning('官方身份接口响应无法解析 source=%s error=%s %s', source, _safe_detail(exc), _response_diagnostic(response))
        raise SourceProbeUnavailable('官方身份接口未能确认，请检查网络后重试；原会话保留') from None
    if isinstance(data, dict) and (str(data.get('code')) == '401' or (config.get('cookie_auth') and str(data.get('code')) == '403')):
        raise SourceAuthenticationRequired('登录已失效，请重新认证')
    if config.get('cookie_auth'):
        if (isinstance(data, dict) and data.get('code') in config.get('identity_codes', (0,))
                and isinstance(data.get('data'), dict)):
            return data['data']
        message = str(data.get('msg') or data.get('message') or '') if isinstance(data, dict) else ''
        if re.search(r'未登录|登录.{0,6}(失效|过期)|请重新登录', message):
            raise SourceAuthenticationRequired('登录已失效，请重新认证')
        raise SourceProbeUnavailable('官方身份接口暂不可用或权限待确认；原会话保留')
    if response.status_code != 200 or not isinstance(data, dict) or str(data.get('code')) != '200' or not isinstance(data.get('data'), dict):
        raise SourceProbeUnavailable('官方身份接口暂不可用或权限待确认；原会话保留')
    return data['data']


def _probe_identity(source, session, timeout=None, attempts=2):
    """短暂网络抖动时重试身份探测；令牌失效立即上抛，避免把断网误判成过期。"""
    attempts = max(1, attempts)
    for index in range(attempts):
        try:
            return identity(source, session) if timeout is None else identity(source, session, timeout=timeout)
        except SourceAuthenticationRequired:
            raise
        except Exception as exc:
            if index + 1 >= attempts:
                raise
            _log.warning('来源身份校验暂未确认 source=%s attempt=%s/%s error=%s: %s',
                         source, index + 1, attempts, type(exc).__name__, _safe_detail(exc))
            time.sleep(0.5)


class SourceAuth:
    def __init__(self, wid: str | None = None):
        self._wid = wid
        self.lock = threading.RLock()
        self.states = {}
        self.inputs = {}
        self.desktop = {}
        self.form_bindings = {}
        self.cancelled = {}
        self.epochs = {}
        self.workers = {}
        self.releases = {}
        self.guards = {}
        self.sms_until = {}
        self.mode_attempts = {}
        self.qr_captured_at = {}
        self.consent_choice = {}
        self.consent_attempts = {}
        self.transitions = {}
        self.retry_forms = {}
        self.pending_credentials = {}
        self.credential_prompt = {}
        self.auto_login_last = {}
        self.auto_login_failed_until = {}

    def login_mode(self, source):
        return 'qr' if SOURCES.get(source, {}).get('dingtalk_qr') else 'sms'

    def sms_key(self,source,control_id=None):
        control=next((c for c in self.desktop.get(source,{}).get('controls',[]) if c.get('kind')=='sms' and (control_id is None or c.get('id')==control_id)),{})
        return (source,control.get('issuer','default'))

    def sms_delay(self,source):
        return max(0,int(self.sms_until.get(self.sms_key(source),0)-time.monotonic()+.999))

    def status(self, source):
        session_path(source)
        with self.lock:
            state = self.states.get(source, {})
            return {'source': source, 'login_mode':self.login_mode(source), 'state': state.get('state', 'saved' if session_path(source).exists() else 'signed_out'),
                    'sms_retry_after':self.sms_delay(source),
                    'busy': bool(self.workers.get(source) and self.workers[source].is_alive()),
                    **self.releases.get(source, {}),
                    'message': state.get('message', ''), 'has_qr': bool(state.get('image')),
                    **{key: state[key] for key in ('checked_at', 'verified_at', 'account_label', 'organization', 'organization_reference', 'input_pending', 'input_seq', 'input_completed', 'cancelling', 'phase', 'phase_started_at') if key in state},
                    'input_error': state.get('input_error', ''), 'input_result': state.get('input_result', ''),
                    'session_id': state.get('session_id'), 'interactive': state.get('state') == 'waiting_login',
                    **({'credential_prompt': True, 'credential_account': self.credential_prompt[source].get('account', '')}
                       if source in ('baize', 'benlai') and self.credential_prompt.get(source)
                       else {'credential_prompt': False}),
                    **{k: v for k, v in self.desktop.get(source, {}).items() if not k.startswith('_')}}

    def interact(self, source, command):
        if not isinstance(command, dict):
            raise HTTPException(400, '认证操作格式无效')
        action = command.get('action')
        if SOURCES.get(source, {}).get('dingtalk_qr') and (action not in ('inspect','control') or command.get('values')):
            raise HTTPException(400, SOURCES[source]['label'] + '仅支持扫码登录')
        if action == 'click':
            if any(type(command.get(k)) not in (int, float) or not 0 <= command[k] <= 1 for k in ('x', 'y')):
                raise HTTPException(400, '点击位置无效')
            payload = {k: command[k] for k in ('x', 'y')}
        elif action == 'fill_fields':
            values = command.get('values')
            if not isinstance(values, list) or len(values) > 12 or any(not isinstance(v, dict) or not isinstance(v.get('id'), str) or not isinstance(v.get('text'), str) or len(v['text']) > 4096 for v in values):
                raise HTTPException(400, '表单输入无效')
            payload = {'values': values, 'form_id': command.get('form_id'), 'submit_id': command.get('submit_id')}
        elif action == 'control':
            if not isinstance(command.get('id'), str): raise HTTPException(400, '认证按钮标识无效')
            values=command.get('values',[])
            if not isinstance(values,list) or len(values)>12 or any(not isinstance(v,dict) or not isinstance(v.get('id'),str) or not isinstance(v.get('text'),str) or len(v['text'])>4096 for v in values):raise HTTPException(400,'表单输入无效')
            payload = {'id': command.get('id'), 'form_id': command.get('form_id'),'values':values}
        elif action == 'challenge_gesture' and source=='xiaoxiang':
            from auth_challenge import gesture
            payload=gesture(command)
        elif action == 'inspect':
            payload = {}
        elif action == 'fill':
            value = command.get('text')
            if not isinstance(value, str) or len(value) > 4096:
                raise HTTPException(400, '输入内容过长或无效')
            payload = {'text': value}
        elif action == 'key' and command.get('key') in ('Tab', 'Shift+Tab', 'Enter', 'Backspace', 'Escape', 'ArrowUp', 'ArrowDown', 'ArrowLeft', 'ArrowRight', 'Space'):
            payload = {'key': command['key']}
        elif action == 'scroll' and command.get('direction') in ('up', 'down'):
            payload = {'direction': command['direction']}
        else:
            raise HTTPException(400, '不支持的认证操作')
        with self.lock:
            state = self.states.get(source, {})
            if self.releases.get(source, {}).get('release_state') in ('releasing','timeout','terminated','unconfirmed') or state.get('cancelling') or state.get('state') != 'waiting_login' or not state.get('session_id') or command.get('session_id') != state['session_id']:
                raise HTTPException(409, '认证页面已变化，请等待刷新后重试')
            if action=='challenge_gesture':
                desktop=self.desktop.get(source,{})
                if not desktop.get('has_challenge') or payload['challenge_id']!=desktop.get('challenge_id') or payload['challenge_version']!=desktop.get('challenge_version') or 'challenge:'+payload['challenge_id'] not in self.form_bindings.get(source,{}):
                    raise HTTPException(409,'官方验证区域已变化，请等待刷新后操作')
            if action in ('fill_fields', 'control'):
                if payload.get('submit_id') is not None and not isinstance(payload['submit_id'], str):
                    raise HTTPException(400, '认证提交按钮无效')
                desktop = self.desktop.get(source, {})
                allowed = self.form_bindings.get(source, {})
                identifiers = [v['id'] for v in payload.get('values', [])] + [v for v in [payload.get('id'), payload.get('submit_id')] if v]
                if not desktop.get('form_id') or any(v not in allowed for v in identifiers):
                    raise HTTPException(409, '官方表单已变化，请等待刷新后重新填写')
                if payload.get('form_id') != desktop['form_id']:
                    # 用户填表期间表单可能因官方刷新验证码而换版；输入项仍属于当前
                    # 表单时按当前页面执行，但按钮类操作仍要求版本一致，避免误发短信。
                    if action == 'control':
                        raise HTTPException(409, '官方表单已变化，请等待刷新后重新填写')
                    _log.warning('认证表单版本已更新 source=%s action=%s stale=%s current=%s',
                                 source, action, str(payload.get('form_id'))[:8], str(desktop['form_id'])[:8])
                field_ids = {v['id'] for v in desktop.get('fields', [])}
                controls = {v['id']: v['kind'] for v in desktop.get('controls', [])}
                if (any(v['id'] not in field_ids for v in payload.get('values', []))
                        or (payload.get('submit_id') and controls.get(payload['submit_id']) != 'submit')
                        or (action == 'control' and payload.get('id') not in controls)):
                    raise HTTPException(400, '认证表单操作类型无效')
                if SOURCES.get(source, {}).get('dingtalk_qr') and controls.get(payload.get('id'))!='qr_refresh':
                    raise HTTPException(400, SOURCES[source]['label'] + '仅支持扫码和刷新二维码')
                # 记录用户对协议勾选的明确选择；取消后不再自动勾选。
                consent_ids={f['id'] for f in desktop.get('fields',[]) if f.get('role')=='consent'}
                for value in payload.get('values',[]):
                    if value['id'] in consent_ids and value['text'] in ('true','false'):
                        self.consent_choice[source]={'form_id':payload['form_id'],'choice':'checked' if value['text']=='true' else 'unchecked'}
                if source in ('baize', 'benlai') and payload.get('values'):
                    roles = {f['id']: f.get('role') for f in desktop.get('fields', [])}
                    pending = self.pending_credentials.setdefault(source, {})
                    for value in payload['values']:
                        role = roles.get(value['id'])
                        if role in ('username', 'phone') and value['text'].strip():
                            pending['username'] = value['text'].strip()
                        elif role == 'password' and value['text']:
                            pending['password'] = value['text']
                if source == 'baize' and action == 'fill_fields' and payload.get('submit_id'):
                    roles = {f['id']: f.get('role') for f in desktop.get('fields', [])}
                    account = next((v['text'] for v in payload.get('values', []) if roles.get(v['id']) == 'username'), '')
                    parts = desktop.get('_signature_parts') or ()
                    self.transitions[source] = {'started': time.monotonic(), 'signature': desktop.get('_signature'),
                                                'step': hashlib.sha256(''.join(map(str, parts[:2])).encode()).hexdigest(),
                                                'account': _mask_account(account), 'stable': 0, 'last': None}
                    self.retry_forms.pop(source, None)
                    current = self.desktop.setdefault(source, {})
                    current['transitioning'] = True
                    current['submitted'] = {'account': _mask_account(account)}
                    current.pop('retry', None)
            if action=='control' and controls.get(payload.get('id'))=='sms':
                if time.monotonic()<self.sms_until.get(self.sms_key(source,payload.get('id')),0):raise HTTPException(429,'请等待短信发送冷却时间结束后再操作')
                self.sms_until[self.sms_key(source,payload.get('id'))]=time.monotonic()+60
            queue = self.inputs.setdefault(source, deque())
            if len(queue) >= 32:
                raise HTTPException(429, '操作较快，请稍候')
            state.pop('input_error', None)
            state.pop('input_result', None)
            state['input_seq'] = state.get('input_seq', 0) + 1
            state['input_pending'] = True
            payload['_command_id'] = state['input_seq']
            queue.append((action, payload))
        return {'accepted': True, 'command_id': payload['_command_id']}

    def _apply_inputs(self, source, page, viewport):
        with self.lock:
            commands = list(self.inputs.pop(source, ()))
        for action, payload in commands:
            if self.cancelled.get(source) and self.cancelled[source].is_set(): break
            try:
                from desktop_auth_page import trusted
                if not trusted(source, page.url):
                    raise ValueError('untrusted login page')
                if action in ('fill_fields', 'control'):
                    desktop_now = self.desktop.get(source, {})
                    if action == 'control' and payload.get('form_id') and desktop_now.get('form_id') and payload.get('form_id') != desktop_now.get('form_id'):
                        raise ValueError('stale form')
                    bindings = self.form_bindings.get(source, {})
                    fields={f['id']:f for f in desktop_now.get('fields',[])}
                    for value in payload.get('values',[]):
                        if self.cancelled.get(source) and self.cancelled[source].is_set():raise ValueError('cancelled')
                        field=fields.get(value['id'],{})
                        if field.get('type')=='checkbox':
                            if value['text'] not in ('true','false'):raise ValueError('invalid consent')
                            want=value['text']=='true'
                            if field.get('auto'):
                                if not self._toggle_consent(bindings[value['id']],want):raise ValueError('consent unchanged')
                            else:bindings[value['id']].set_checked(want,timeout=3000)
                            field['filled']=want
                        else:bindings[value['id']].fill(value['text'],timeout=3000)
                    if action=='fill_fields':
                        if payload.get('submit_id'):bindings[payload['submit_id']].click(timeout=3000)
                    else:bindings[payload['id']].click(timeout=3000)
                elif action == 'inspect':
                    self._capture_desktop(source, page)
                elif action == 'challenge_gesture':
                    from auth_challenge import apply_gesture
                    desktop=self.desktop.get(source,{})
                    if not desktop.get('has_challenge') or desktop.get('challenge_id')!=payload['challenge_id'] or desktop.get('challenge_version')!=payload['challenge_version']:
                        raise ValueError('Challenge changed')
                    widget=self.form_bindings.get(source,{})['challenge:'+payload['challenge_id']]
                    apply_gesture(page,widget,desktop['regions']['challenge'],payload)
                elif action == 'click':
                    page.mouse.click(min(viewport['width'] - 1, payload['x'] * viewport['width']),
                                     min(viewport['height'] - 1, payload['y'] * viewport['height']))
                elif action == 'fill':
                    page.locator('input:focus, textarea:focus').fill(payload['text'], timeout=1500)
                elif action == 'key':
                    page.keyboard.press(payload['key'])
                elif action == 'scroll':
                    page.mouse.wheel(0, 500 if payload['direction'] == 'down' else -500)
                with self.lock:
                    self.states.get(source, {}).update(input_result='操作已在官方页面执行；登录结果以官方验证为准', input_completed=payload.get('_command_id', 0), input_pending=payload.get('_command_id', 0) < self.states.get(source, {}).get('input_seq', 0))
            except Exception:
                # Never log input values, selectors or browser exceptions containing passwords.
                with self.lock:
                    self.states.get(source, {}).update(input_error='操作未完成，请检查官方页面或重新识别输入项后重试', input_completed=payload.get('_command_id', 0), input_pending=payload.get('_command_id', 0) < self.states.get(source, {}).get('input_seq', 0))
        commands.clear()

    def _active_page(self, source, context, page):
        from auth_browser_runtime import active_page
        selected = active_page(source, context, page)
        if selected is not page:
            with self.lock:
                self.inputs.pop(source, None)
                self.desktop.pop(source, None)
                self.form_bindings.pop(source, None)
                self.qr_captured_at.pop(source, None)
                self.qr_captured_at.pop(source + ':qr', None)
                self.states.setdefault(source, {}).pop('image', None)
                self.states.setdefault(source, {}).pop('image_qr', None)
                self.states.setdefault(source, {}).update(input_pending=False,
                    input_result='官方认证页面已切换，请在新页面继续操作')
                transition = self.transitions.get(source)
                if transition is not None:
                    self.desktop[source] = {'transitioning': True, 'submitted': {'account': transition['account']}}
        return selected

    @staticmethod
    def _toggle_consent(element, checked):
        """官方协议框多为隐藏 input，只能通过关联 label 触发页面自身的变更事件。"""
        return bool(element.evaluate(CONSENT_TOGGLE, checked))

    def _auto_consent(self, source, desktop, bindings):
        field = next((item for item in desktop.get('fields', []) if item.get('role') == 'consent' and item.get('auto')), None)
        if field is None or field.get('filled'):
            return False
        form_id = desktop.get('form_id')
        choice = self.consent_choice.get(source)
        if choice and choice.get('form_id') == form_id and choice.get('choice') == 'unchecked':
            # 用户明确取消过协议，本轮不再代为勾选。
            return False
        element = bindings.get(field['id'])
        if element is None:
            return False
        attempt = self.consent_attempts.get(source, {})
        if attempt.get('form_id') != form_id:
            attempt = {'form_id': form_id, 'count': 0, 'last': 0}
        if attempt['count'] >= 3 or time.monotonic() - attempt['last'] < 2:
            return False
        attempt['count'] += 1
        attempt['last'] = time.monotonic()
        self.consent_attempts[source] = attempt
        try:
            if not self._toggle_consent(element, True):
                return False
        except Exception:
            return False
        field['filled'] = True
        desktop['consent_auto'] = True
        return True

    def _capture_desktop(self, source, page):
        try:
            from desktop_auth_page import inspect_login_page
            previous = self.desktop.get(source)
            desktop, bindings = inspect_login_page(source, page, previous)
            challenge=desktop.pop('_challenge',None)
            qr_element=desktop.pop('_qr_element',None)
            for flag in ('transitioning', 'submitted', 'retry'): desktop.pop(flag, None)
            transition = self.transitions.get(source) if source == 'baize' else None
            if transition is not None:
                # 提交后先展示“验证中”，页面签名稳定两轮才恢复表单，
                # 避免跳转动画或中间页把同一张表闪回成一张空白表。
                elapsed = time.monotonic() - transition['started']
                parts = desktop.get('_signature_parts') or ()
                step = hashlib.sha256(''.join(map(str, parts[:2])).encode()).hexdigest()
                has_form = bool(desktop.get('fields'))
                if desktop.get('_signature') == transition['signature']:
                    transition['stable'] = 0
                    settled = elapsed > 4 or bool(desktop.get('official_feedback'))
                    retry = settled
                else:
                    if desktop.get('_signature') == transition.get('last'):
                        transition['stable'] += 1
                    else:
                        transition['stable'], transition['last'] = 1, desktop.get('_signature')
                    retry = has_form and step == transition['step']
                    settled = transition['stable'] >= 2 and (has_form or retry)
                if settled:
                    self.transitions.pop(source, None)
                    if has_form and retry:
                        # 同一登录步骤重新出现：保留摘要，只补填密码/算式。
                        self.retry_forms[source] = {'step': transition['step'], 'account': transition['account']}
                    elif has_form:
                        self.retry_forms.pop(source, None)
                elif elapsed > 30:
                    self.transitions.pop(source, None)
                else:
                    desktop['transitioning'] = True
                    desktop['submitted'] = {'account': transition['account']}
            if source == 'baize' and source not in self.transitions:
                retry_state = self.retry_forms.get(source)
                if retry_state is not None:
                    parts = desktop.get('_signature_parts') or ()
                    step = hashlib.sha256(''.join(map(str, parts[:2])).encode()).hexdigest()
                    if desktop.get('fields') and step == retry_state['step']:
                        desktop['retry'] = True
                        desktop['submitted'] = {'account': retry_state['account']}
                    else:
                        self.retry_forms.pop(source, None)
            if source=='lanorange_mdr' and desktop.get('qr_state') not in ('visible', 'expired'):
                attempted = self.mode_attempts.setdefault(source, set())
                choice = next((c for c in desktop.get('controls', [])
                               if c.get('enabled', True) and '钉钉' in str(c.get('label', ''))
                               and (page.url, c.get('label')) not in attempted), None)
                if choice is not None:
                    attempted.add((page.url, choice.get('label')))
                    bindings[choice['id']].click(timeout=2500)
                    desktop,bindings=inspect_login_page(source,page,desktop)
                    desktop.pop('_challenge',None);desktop.pop('_qr_element',None)
            if source=='lanorange':
                preferred=self.login_mode(source)
                # 小象灯塔的官方 SSO 入口默认就是美团App扫码页，保持扫码视图；
                # 需要手机号登录时由用户在窗口中自行切换，系统不代点。
                need_mode=desktop.get('qr_state') not in ('visible','expired')
                if need_mode:
                    modes=[c for c in desktop.get('controls',[]) if c.get('kind')=='mode' and c.get('enabled',True)]
                    attempted=self.mode_attempts.setdefault(source,set())
                    # 每轮登录最多自动切换 4 次：官方页面在扫码/账号视图间跳转时，
                    # 无上限的切换会变成窗口反复刷新，用户无法手动操作。
                    labels=() if len(attempted)>=4 else ('扫码登录','二维码登录')
                    choice=next((c for label in labels for c in modes if c['label']==label and (page.url,c['label']) not in attempted),None)
                    key=(page.url,choice['label']) if choice else None
                    if choice:
                        attempted.add(key);bindings[choice['id']].click(timeout=2500)
                        desktop,bindings=inspect_login_page(source,page,desktop)
                        challenge=desktop.pop('_challenge',None)
                        qr_element=desktop.pop('_qr_element',None)
            if SOURCES.get(source, {}).get('dingtalk_qr'):
                from desktop_auth_page import trusted
                preferred=self.login_mode(source);desktop['login_mode']=preferred
                region=desktop.get('regions',{}).get('qr')
                with self.lock:old_image=self.states.get(source,{}).get('image')
                image=None
                if preferred=='qr' and region and trusted(source,page.url):
                    if not old_image or time.monotonic()-self.qr_captured_at.get(source,0)>=1:
                        candidate=None
                        try:
                            candidate=page.screenshot(type='png',clip=region,timeout=1500)
                        except Exception:
                            candidate=None
                        if (not (isinstance(candidate,bytes) and candidate.startswith(b'\x89PNG\r\n\x1a\n') and len(candidate)<=512*1024)) and qr_element is not None:
                            try:
                                candidate=qr_element.screenshot(type='png',timeout=1500)
                            except Exception:
                                candidate=None
                        if isinstance(candidate,bytes) and candidate.startswith(b'\x89PNG\r\n\x1a\n') and len(candidate)<=512*1024:image=candidate
                        self.qr_captured_at[source]=time.monotonic()
                    else:image=old_image
                with self.lock:
                    if image:
                        self.states.setdefault(source,{})['image']=image
                        desktop['qr_version']=hashlib.sha256(image).hexdigest()[:20]
                    else:self.states.setdefault(source,{}).pop('image',None)
            if source=='xiaoxiang':
                from urllib.parse import urlsplit
                from desktop_auth_page import trusted
                host=urlsplit(page.url).hostname or ''
                board_page=host=='ssosv.sankuai.com' or host.endswith('.sankuai.com') or host=='zl.meituan.com' or host.endswith('.zl.meituan.com')
                qr_region=desktop.get('regions',{}).get('qr')
                qr_image=None
                key=source+':qr'
                if qr_region and trusted(source,page.url) and desktop.get('qr_state')!='expired':
                    old_qr=self.states.get(source,{}).get('image_qr')
                    if old_qr and time.monotonic()-self.qr_captured_at.get(key,0)<1:
                        qr_image=old_qr
                    else:
                        candidate=None
                        # 截二维码元素本身，避免把上方“扫一扫”说明文字截掉半行。
                        if qr_element is not None:
                            try:
                                candidate=qr_element.screenshot(type='png',timeout=1500)
                            except Exception:
                                candidate=None
                        if not (isinstance(candidate,bytes) and candidate.startswith(b'\x89PNG\r\n\x1a\n') and len(candidate)<=512*1024):
                            candidate=page.screenshot(type='png',clip=qr_region,timeout=1500)
                        if isinstance(candidate,bytes) and candidate.startswith(b'\x89PNG\r\n\x1a\n') and len(candidate)<=512*1024:qr_image=candidate
                        self.qr_captured_at[key]=time.monotonic()
                with self.lock:
                    # 灯塔登录（美团App扫码）和知了看板（大象扫码）都可能出现二维码，
                    # 由页面域名区分阶段，面板据此显示对应文案。
                    desktop['has_qr']=bool(qr_region)
                    desktop['qr_stage']='board' if board_page else 'lighthouse'
                    if qr_image:
                        self.states.setdefault(source,{})['image_qr']=qr_image
                        desktop['qr_version']=hashlib.sha256(qr_image).hexdigest()[:20]
                    else:
                        self.states.setdefault(source,{}).pop('image_qr',None)
                region=desktop.get('regions',{}).get('challenge');image=None
                if challenge is not None and region and desktop.get('challenge_id'):
                    if previous and previous.get('challenge_id')==desktop['challenge_id'] and time.monotonic()-self.qr_captured_at.get(source,0)<1:
                        image=self.states.get(source,{}).get('image')
                    if image is None:
                        candidate=page.screenshot(type='png',clip=region,timeout=1500)
                        if isinstance(candidate,bytes) and candidate.startswith(b'\x89PNG\r\n\x1a\n') and len(candidate)<=512*1024:image=candidate
                        self.qr_captured_at[source]=time.monotonic()
                    if image:bindings['challenge:'+desktop['challenge_id']]=challenge
                desktop['has_challenge']=bool(image)
                with self.lock:
                    if image:
                        self.states.setdefault(source,{})['image']=image
                        desktop['challenge_version']=hashlib.sha256(image).hexdigest()[:20]
                    else:self.states.setdefault(source,{}).pop('image',None)
                try:
                    self._auto_consent(source, desktop, bindings)
                except Exception:
                    # 自动代操作失败只影响便利性，不能中断页面识别与手动操作。
                    pass
        except Exception:
            desktop, bindings = {'form_detection': 'unavailable'}, {}
            transition = self.transitions.get(source)
            if transition is not None and time.monotonic() - transition['started'] <= 30:
                desktop.update(transitioning=True, submitted={'account': transition['account']})
            if source in ('lanorange','lanorange_mdr','xiaoxiang'):
                if source in ('lanorange','lanorange_mdr'):desktop['login_mode']=self.login_mode(source)
                with self.lock:self.states.setdefault(source,{}).pop('image',None)
        with self.lock:
            self.desktop[source], self.form_bindings[source] = desktop, bindings

    def cancel(self, source):
        with self.lock:
            event = self.cancelled.get(source)
            if event and self.states.get(source, {}).get('state') in ('starting', 'waiting_login'):
                event.set()
                self.states[source].update(cancelling=True, phase='ending', message='正在安全结束认证，原有加密会话保留；当前官方请求结束后关闭窗口')
                self.inputs.pop(source, None)
            return self.status() if source == 'xiaoxiang' else self.status(source)

    def _release_update(self, source, value):
        with self.lock: self.releases[source] = value

    def _close_browser(self, source, browser):
        guard = self.guards.get(source)
        if guard: guard.closing()
        try: browser.close()
        except Exception: pass

    def start(self, source):
        session_path(source)
        if source=='lanorange':
            from lanorange_approvals import has_active
            from lanorange_price_export import has_active as prices_active
            from workspace_context import current_workspace
            scope_id = self._wid or current_workspace()
            if has_active(scope_id) or prices_active(scope_id):
                raise HTTPException(409,'当前空间有蓝橙价格审批或导出正在执行，请结束任务后再登录或切换账号')
        with self.lock:
            if (self.workers.get(source) and self.workers[source].is_alive()) or self.states.get(source, {}).get('state') in ('starting', 'waiting_login', 'refreshing'):
                return self.status(source)
            from auth_browser_runtime import phase_fields
            self.states[source] = {'state': 'starting', 'message': '正在检查已保存会话，必要时准备钉钉扫码' if SOURCES[source].get('dingtalk_qr') else '正在打开官方认证入口', **phase_fields('connecting')}
            self.cancelled[source] = threading.Event()
            self.epochs[source] = self.epochs.get(source, 0) + 1
            self.inputs.pop(source, None)
            self.releases.pop(source, None)
            self.mode_attempts.pop(source, None)
            self.consent_choice.pop(source, None)
            self.consent_attempts.pop(source, None)
            self.qr_captured_at.pop(source, None)
            self.qr_captured_at.pop(source + ':qr', None)
            self.pending_credentials.pop(source, None)
            self.credential_prompt.pop(source, None)
            self.auto_login_failed_until.pop(source, None)
            self.transitions.pop(source, None)
            self.retry_forms.pop(source, None)
            self.states.setdefault(source, {}).pop('image_qr', None)
            from workspace_context import spawn_in_context
            worker = spawn_in_context(self._login, source, name=f'source-auth-{source}')
            self.workers[source] = worker
            worker.start()
            return self.status(source)

    def _probe_result(self, source, state, message, data=None, epoch=None):
        with self.lock:
            if epoch is not None and self.epochs.get(source, 0) != epoch: return
            now = datetime.now(timezone.utc).isoformat()
            result = {'state': state, 'message': message, 'checked_at': now}
            previous = self.states.get(source, {})
            for key in ('account_label', 'organization', 'organization_reference', 'verified_at'):
                if key in previous: result[key] = previous[key]
            if state == 'ready':
                result['verified_at'] = now
                if isinstance(data, dict):
                    from platform_auth_control import display_identity
                    result.update(display_identity(data))
            self.states[source] = result

    def refresh(self, source):
        session_path(source)
        with self.lock:
            if self.states.get(source, {}).get('state') in ('starting', 'waiting_login', 'refreshing'): return False
            epoch = self.epochs.get(source, 0) + 1
            self.epochs[source] = epoch
            self.states[source] = {'state': 'refreshing', 'message': '正在复用已保存的浏览器会话'}
        try:
            state = load_state(source)
            refreshed = state is not None and self._refresh(source, state)
        except Exception:
            self._probe_result(source, 'unknown', '连接或会话读取暂未确认，请检查网络后重试；原会话保留', epoch=epoch)
            return False
        self._probe_result(source, 'ready' if refreshed else 'saved' if session_path(source).exists() else 'signed_out',
                           '已复用浏览器会话，下载使用 HTTP 接口' if refreshed else '已保存的浏览器会话需要重新登录' if state is not None else '没有可复用的浏览器会话，需要登录一次', epoch=epoch)
        return bool(refreshed)

    def _offer_credentials(self, source):
        if source not in ('baize', 'benlai'):
            return
        pending = self.pending_credentials.get(source)
        if not pending or not pending.get('username') or not pending.get('password'):
            return
        try:
            saved = load_credentials(source)
        except Exception:
            saved = None
        if saved and saved.get('username') == pending['username'] and saved.get('password') == pending['password']:
            self.pending_credentials.pop(source, None)
            self.credential_prompt.pop(source, None)
            return
        self.credential_prompt[source] = {'account': _mask_account(pending['username'])}

    def confirm_credentials(self, source, save):
        if source not in ('baize', 'benlai'):
            raise BillCollectionError('此来源不支持保存登录凭据')
        with self.lock:
            pending = self.pending_credentials.pop(source, None)
            self.credential_prompt.pop(source, None)
        if save:
            if not pending or not pending.get('username') or not pending.get('password'):
                raise BillCollectionError('没有可保存的登录凭据，请重新登录')
            save_credentials(source, pending['username'], pending['password'])
        else:
            clear_credentials(source)
        return self.status(source)

    def recover(self, source):
        """Try SSO refresh, then saved credentials, without making the user log in."""
        if source not in ('baize', 'benlai'):
            return False
        with self.lock:
            if self.states.get(source, {}).get('state') in ('starting', 'waiting_login', 'refreshing'):
                return False
        try:
            if self.refresh(source):
                return True
        except Exception as exc:
            _log.warning('来源会话静默续期失败 source=%s error=%s: %s', source, type(exc).__name__, _safe_detail(exc))
        try:
            credentials = load_credentials(source)
        except Exception:
            credentials = None
        if not credentials:
            return False
        now = time.monotonic()
        if now < self.auto_login_failed_until.get(source, 0):
            return False
        if now - self.auto_login_last.get(source, 0) < 300:
            return False
        self.auto_login_last[source] = now
        with self.lock:
            if self.states.get(source, {}).get('state') in ('starting', 'waiting_login', 'refreshing'):
                return False
            self.states[source] = {'state': 'refreshing', 'message': '正在使用保存的账号密码尝试自动登录'}
        try:
            if self._auto_login(source, credentials):
                self.auto_login_failed_until.pop(source, None)
                return True
        except Exception as exc:
            _log.warning('来源自动登录失败 source=%s error=%s: %s', source, type(exc).__name__, _safe_detail(exc))
        self.auto_login_failed_until[source] = now + 1800
        with self.lock:
            if self.states.get(source, {}).get('state') == 'refreshing':
                self.states[source] = {'state': 'saved', 'message': '自动登录未完成，请人工登录；原会话保留'}
        return False

    def _auto_login(self, source, credentials):
        from playwright.sync_api import sync_playwright
        from auth_browser_runtime import launch_edge, navigate
        from desktop_auth_page import inspect_login_page, trusted
        config = SOURCES[source]
        entry = 'https://' + config['host'] + config['entry']
        try:
            state = load_state(source)
        except Exception:
            state = None
        with sync_playwright() as pw:
            browser = launch_edge(pw, headless=True)
            try:
                options = {'viewport': {'width': 1100, 'height': 850}, 'locale': 'zh-CN', 'timezone_id': 'Asia/Shanghai'}
                if state is not None:
                    options['storage_state'] = state
                context = browser.new_context(**options)
                getattr(context, 'set_default_timeout', lambda _: None)(2000)
                page = context.new_page()
                page.goto(entry, wait_until='domcontentloaded', timeout=30000)
                page.wait_for_timeout(1200)
                if not trusted(source, page.url):
                    return False
                desktop, bindings = inspect_login_page(source, page, None)
                fields = desktop.get('fields', [])
                roles = {field['id']: field.get('role') for field in fields}
                if any(role in ('sms_code', 'voice_code', 'math') for role in roles.values()):
                    return False
                if any(control.get('kind') == 'sms' for control in desktop.get('controls', [])):
                    return False
                if any(role == 'consent' and not field.get('filled') for field, role in
                       ((field, field.get('role')) for field in fields)):
                    return False
                filled = 0
                for field in fields:
                    role = field.get('role')
                    element = bindings.get(field['id'])
                    if element is None:
                        continue
                    if role in ('username', 'phone'):
                        element.fill(credentials['username'], timeout=3000)
                        filled += 1
                    elif role == 'password':
                        element.fill(credentials['password'], timeout=3000)
                        filled += 1
                submit = next((control for control in desktop.get('controls', [])
                               if control.get('kind') == 'submit' and control.get('enabled', True)), None)
                if not filled or submit is None or submit['id'] not in bindings:
                    return False
                bindings[submit['id']].click(timeout=3000)
                deadline = time.monotonic() + 30
                while time.monotonic() < deadline:
                    current = context.storage_state()
                    token = _token_from_state(source, current)
                    if token:
                        try:
                            with client(source, token, current) as session:
                                identity(source, session, timeout=(5, 15))
                        except SourceAuthenticationRequired:
                            token = None
                        except Exception:
                            token = None
                        if token:
                            save_token(source, token)
                            try:
                                save_state(source, current)
                            except Exception:
                                pass
                            with self.lock:
                                self.states[source] = {'state': 'ready',
                                                       'message': '已使用保存的账号密码自动登录，下载使用 HTTP 接口'}
                            self.auto_login_last.pop(source, None)
                            return True
                    page.wait_for_timeout(500)
                return False
            finally:
                browser.close()

    def keepalive(self, source):
        with self.lock:
            epoch = self.epochs.get(source, 0)
            if self.states.get(source, {}).get('state') in ('starting', 'waiting_login', 'refreshing'): return False
        try:
            token = load_token(source)
            if not token: return False
            with client(source, token) as session: data = _probe_identity(source, session)
        except SourceAuthenticationRequired:
            if self.recover(source):
                return True
            with self.lock:
                epoch = self.epochs.get(source, 0)
            self._probe_result(source, 'login_required', SOURCES[source]['label'] + '官方已确认会话失效，请重新认证；原会话保留', epoch=epoch)
            return False
        except Exception as exc:
            _log.warning('来源会话保活校验失败 source=%s error=%s: %s', source, type(exc).__name__, _safe_detail(exc))
            self._probe_result(source, 'unknown', '连接暂未确认，请检查网络后重试；原会话保留', epoch=epoch)
            return False
        with self.lock:
            if self.states.get(source, {}).get('state') in ('starting', 'waiting_login', 'refreshing'): return False
            self._probe_result(source, 'ready', '会话保持中，下载使用 HTTP 接口', data, epoch)
        return True

    def start_keepalive(self):
        if KEEPALIVE_SECONDS <= 0:
            return
        with self.lock:
            if getattr(self, '_keepalive', None) is not None and self._keepalive.is_alive():
                return
            self._keepalive = threading.Thread(target=self._keepalive_loop, daemon=True,
                                               name='source-auth-keepalive')
            self._keepalive.start()

    def _keepalive_loop(self):
        from workspace_context import bind_workspace
        while True:
            for source in SOURCES:
                try:
                    with bind_workspace(self._wid):
                        self.keepalive(source)
                except Exception as exc:
                    _log.warning('来源会话保活失败 source=%s error=%s: %s',
                                 source, type(exc).__name__, _safe_detail(exc))
            for wid, ws_auth in list(_WORKSPACE_AUTHS.items()):
                for source in SOURCES:
                    if source in SHARED_SOURCES:
                        continue
                    try:
                        with bind_workspace(wid):
                            ws_auth.keepalive(source)
                    except Exception as exc:
                        _log.warning('空间来源会话保活失败 wid=%s source=%s error=%s: %s',
                                     wid, source, type(exc).__name__, _safe_detail(exc))
            time.sleep(KEEPALIVE_SECONDS)

    @staticmethod
    def _discard_state(source):
        try:
            state_path(source).unlink(missing_ok=True)
        except OSError:
            pass

    @staticmethod
    def _reuse_context(source, context, cancelled=None):
        """已保存会话仍有效时直接复用，避免在已登录页面上等「钉钉登录」按钮超时。"""
        try:
            current = context.storage_state()
        except Exception:
            return False
        token = _token_from_state(source, current)
        if not token:
            return False
        try:
            with client(source, token, current) as session:
                _probe_identity(source, session, timeout=(5, 20))
        except SourceAuthenticationRequired:
            return False
        except Exception as exc:
            _log.warning('来源身份校验失败 source=%s phase=reuse_context error=%s: %s', source, type(exc).__name__, _safe_detail(exc))
            raise SourceProbeUnavailable('连接暂未确认，请检查网络后重试；原会话保留') from None
        if cancelled is not None and cancelled.is_set():
            raise BillCollectionError('认证已取消，原会话保留')
        save_token(source, token)
        try:
            save_state(source, current)
        except Exception:
            pass
        return True

    @staticmethod
    def _reuse_saved(source):
        """本地已存令牌仍有效时直接复用，不启动登录窗口。"""
        try:
            token = load_token(source)
        except Exception:
            return False
        if not token:
            return False
        try:
            with client(source, token) as session:
                _probe_identity(source, session, timeout=(5, 20))
        except SourceAuthenticationRequired:
            return False
        except Exception as exc:
            _log.warning('来源身份校验失败 source=%s phase=reuse_saved error=%s: %s', source, type(exc).__name__, _safe_detail(exc))
            raise SourceProbeUnavailable('连接暂未确认，请检查网络后重试；原会话保留') from None
        return True

    def _refresh(self, source, state):
        config = SOURCES[source]
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            return False
        with sync_playwright() as pw:
            from auth_browser_runtime import launch_edge
            browser = launch_edge(pw, headless=True)
            try:
                context = browser.new_context(storage_state=state)
                getattr(context,'set_default_timeout',lambda _:None)(2000)
                page = context.new_page()
                page.goto('https://' + config['host'] + config['entry'], wait_until='domcontentloaded', timeout=30000)
                deadline = time.monotonic() + 20
                while time.monotonic() < deadline:
                    current = context.storage_state()
                    token = _token_from_state(source, current)
                    if token:
                        try:
                            with client(source, token, current) as session:
                                _probe_identity(source, session, timeout=(5, 20))
                        except SourceAuthenticationRequired:
                            return False
                        except Exception as exc:
                            _log.warning('来源身份校验失败 source=%s phase=refresh error=%s: %s', source, type(exc).__name__, _safe_detail(exc))
                            raise SourceProbeUnavailable('连接暂未确认，请检查网络后重试；原会话保留') from None
                        save_token(source, token)
                        try:
                            save_state(source, current)
                        except Exception:
                            pass
                        return True
                    parsed = urlparse(page.url)
                    host = parsed.hostname or ''
                    own_login = host == config['host'] and parsed.path.rstrip('/').endswith('/login')
                    foreign_login = host == 'dingtalk.com' or host.endswith('.dingtalk.com')
                    if parsed.scheme == 'https' and own_login:
                        return False
                    if parsed.scheme == 'https' and foreign_login:
                        # Retain the previous encrypted state; only a successful login may replace it.
                        return False
                    page.wait_for_timeout(500)
                return False
            finally:
                browser.close()

    def _login(self, source):
        from auth_browser_runtime import navigate, phase_fields
        config = SOURCES[source]
        entry = 'https://' + config['host'] + config['entry']
        viewport = {'width': 1100, 'height': 850}
        browser = None
        authenticated = False
        cancelled = self.cancelled.get(source, threading.Event())
        try:
            # 所有来源先验证现有令牌；有效会话不依赖浏览器，也无需再次进入扫码页。
            # 网络异常由 _reuse_saved 报错，不能把暂时断网误判成会话失效。
            if self._reuse_saved(source):
                if cancelled.is_set(): raise BillCollectionError('认证已取消，原会话保留')
                authenticated = True
                with self.lock:
                    self.states[source] = {'state': 'ready', 'message': '已复用本机加密会话，无需重新登录'}
                return
            try:
                from playwright.sync_api import sync_playwright
            except ImportError:
                raise BillCollectionError('服务器缺少 Playwright 运行环境，无法打开认证窗口，请联系管理员安装')
            try:
                stored = load_state(source)
            except Exception:
                stored = None
            from auth_browser_guard import guarded_playwright
            from auth_browser_runtime import launch_edge
            from workspace_context import acquire_login_browser_slot
            with acquire_login_browser_slot(), guarded_playwright(cancelled, lambda value: self._release_update(source, value), lambda guard: self.guards.__setitem__(source, guard)) as pw:
                browser = launch_edge(pw, headless=True)
                options = {'viewport': viewport,'locale':'zh-CN','timezone_id':'Asia/Shanghai'}
                if stored is not None:
                    options['storage_state'] = stored
                context = browser.new_context(**options)
                getattr(context,'set_default_timeout',lambda _:None)(2000)
                page = context.new_page()
                navigate(page, entry, cancelled)
                if SOURCES[source].get('dingtalk_qr'):
                    # 有效的已保存会话会被登录页直接放行到首页，页面上没有「钉钉登录」按钮，
                    # 无条件点击只会等到动作超时；先校验会话，失效才丢弃并重建干净的上下文再点击。
                    if self._reuse_context(source, context, cancelled):
                        authenticated = True
                        with self.lock:
                            self.states[source] = {'state': 'ready', 'message': '已复用已保存的浏览器会话，下载使用 HTTP 接口'}
                        return
                    if stored is not None:
                        # 蓝橙令牌过期不代表钉钉授权过期：重建上下文时把钉钉会话带过去，
                        # 这样还能直接确认跳转；旧令牌文件留到登录成功后再覆盖。
                        context.close()
                        options = {'viewport': viewport,'locale':'zh-CN','timezone_id':'Asia/Shanghai'}
                        kept = _state_for_hosts(stored, config.get('state_hosts', ()))
                        if kept is not None:
                            options['storage_state'] = kept
                        context = browser.new_context(**options)
                        getattr(context,'set_default_timeout',lambda _:None)(2000)
                        page = context.new_page()
                        navigate(page, entry, cancelled)
                    try:
                        page.get_by_role('button', name='钉钉登录', exact=True).click(timeout=3500)
                    except Exception:
                        if self._reuse_context(source, context, cancelled):
                            authenticated = True
                            with self.lock:
                                self.states[source] = {'state': 'ready', 'message': '认证成功，下载使用 HTTP 接口'}
                            return
                        current_host = (urlparse(page.url).hostname or '').lower()
                        if not (current_host == 'dingtalk.com' or current_host.endswith('.dingtalk.com')):
                            clicked_fallback = False
                            try:
                                fallback_btn = page.locator('button:visible, a:visible, [role=button]:visible, [role=tab]:visible').filter(has_text='钉钉').first
                                if fallback_btn.is_visible():
                                    fallback_btn.click(timeout=2000)
                                    clicked_fallback = True
                            except Exception:
                                clicked_fallback = False
                            if not clicked_fallback and source == 'lanorange':
                                raise BillCollectionError('蓝橙登录页未出现「钉钉登录」入口，页面可能已改版') from None
                elif stored is not None:
                    # 失效令牌留在会话里会让下面的循环立刻校验失败并关闭窗口，用户来不及登录；
                    # 先确认旧会话，失效则丢弃并用干净的上下文重新打开登录页。
                    if self._reuse_context(source, context, cancelled):
                        authenticated = True
                        with self.lock:
                            self.states[source] = {'state': 'ready', 'message': '已复用已保存的浏览器会话，下载使用 HTTP 接口'}
                        return
                    # Keep the prior encrypted state until a successful login replaces it.
                    context.close()
                    context = browser.new_context(viewport=viewport,locale='zh-CN',timezone_id='Asia/Shanghai')
                    getattr(context,'set_default_timeout',lambda _:None)(2000)
                    page = context.new_page()
                    navigate(page, entry, cancelled)
                with self.lock:
                    self.states.setdefault(source, {}).update(**phase_fields('waiting_user'))
                deadline, last_image, last_confirm = time.monotonic() + 900, 0, 0
                session_id = secrets.token_urlsafe(24)
                rejected_token = None
                probe_failures = 0
                while time.monotonic() < deadline:
                    if cancelled.is_set(): raise BillCollectionError('认证已取消，原会话保留')
                    page = self._active_page(source, context, page)
                    if source not in ('baize', 'benlai'):
                        self._capture_desktop(source, page)
                        self._apply_inputs(source, page, viewport)
                    state = context.storage_state()
                    token = _token_from_state(source, state)
                    if token and token==rejected_token:token=None
                    if token:
                        try:
                            with client(source, token, state) as session:
                                identity(source, session, timeout=(5, 20))
                        except SourceAuthenticationRequired:
                            rejected_token = token
                            token = None
                            probe_failures = 0
                        except Exception as exc:
                            # 官方已在浏览器下发令牌；校验失败多为网络抖动或网关拦截页，
                            # 保留登录窗口并退避重试，不能因一次失败终止整个认证。
                            probe_failures += 1
                            _log.warning('来源身份校验暂未确认 source=%s phase=login_probe attempt=%s error=%s: %s',
                                         source, probe_failures, type(exc).__name__, _safe_detail(exc))
                            if probe_failures >= 6:
                                raise SourceProbeUnavailable('连接暂未确认，请检查网络后重试；原会话保留') from None
                            token = None
                            try: page.wait_for_timeout(500 * probe_failures)
                            except Exception: time.sleep(0.5 * probe_failures)
                        else:
                            probe_failures = 0
                    if token:
                        if cancelled.is_set(): raise BillCollectionError('认证已取消，原会话保留')
                        save_token(source, token)
                        try:
                            save_state(source, context.storage_state())
                        except Exception:
                            pass
                        authenticated = True
                        self._offer_credentials(source)
                        with self.lock:
                            self.states[source] = {'state': 'ready', 'message': '认证成功，下载使用 HTTP 接口'}
                        break
                    if source in ('baize', 'benlai'):
                        # Confirm a newly issued token before scanning the old
                        # login page. OCR never blocks this worker or a submit.
                        self._capture_desktop(source,page)
                        self._apply_inputs(source,page,viewport)
                    image, confirmed = None, False
                    if SOURCES[source].get('dingtalk_qr') and urlparse(page.url).scheme == 'https' and (urlparse(page.url).hostname or '').endswith('dingtalk.com'):
                        # 钉钉授权会话仍在时会停在确认步骤，自动点一次即可跳回；确认成功就不再截图，
                        # 没有会话才会落到扫码页，那时才需要把二维码送回前端。
                        if time.monotonic() - last_confirm > 4:
                            last_confirm = time.monotonic()
                            confirmed = _confirm_dingtalk(page) is not None
                    if not confirmed and time.monotonic() - last_image > 1:
                        image = None
                        last_image = time.monotonic()
                    with self.lock:
                        entry = self.states.setdefault(source, {})
                        entry.update(state='waiting_login', session_id=session_id, message='请使用手机钉钉扫码，确认后自动连接' + SOURCES[source]['label']
                                     if source in ('lanorange', 'lanorange_mdr') or SOURCES[source].get('dingtalk_qr')
                                     else '请输入本来人力商户号/手机号与登录密码，验证通过后自动同步会话' if source == 'benlai'
                                     else '请输入商翼企业账号、密码与算式答案，验证通过后自动同步会话' if source == 'baize'
                                     else '请在当前窗口完成平台安全认证')
                        if image: entry['image'] = image
                        elif confirmed: entry.pop('image', None)
                    with self.lock:
                        has_qr_now = bool(self.states.get(source, {}).get('image'))
                    page.wait_for_timeout(150 if source in ('baize', 'benlai') else 250 if not has_qr_now else 450)
                else:
                    raise BillCollectionError('官方认证等待超时，请重新打开登录')
                self._close_browser(source, browser); browser = None
        except Exception as exc:
            _log.warning('来源认证失败 source=%s error=%s: %s', source, type(exc).__name__, _safe_detail(exc))
            with self.lock:
                if not authenticated:
                    message = (str(exc) if isinstance(exc, BillCollectionError)
                               else '官方认证未完成或连接中断，请重新打开认证入口')
                    if cancelled.is_set(): message = '认证已取消，原会话保留'
                    self.states[source] = {'state': ('saved' if session_path(source).exists() else 'signed_out') if cancelled.is_set() else 'unknown' if isinstance(exc, SourceProbeUnavailable) else 'error', 'message': message}
        finally:
            with self.lock:
                self.states.get(source, {})['checked_at'] = datetime.now(timezone.utc).isoformat()
                self.guards.pop(source, None)
                self.inputs.pop(source, None)
                self.desktop.pop(source, None)
                self.form_bindings.pop(source, None)
                self.transitions.pop(source, None)
                self.retry_forms.pop(source, None)
                self.states.get(source, {}).pop('image', None)
                self.states.get(source, {}).pop('session_id', None)
            if browser is not None:
                try: self._close_browser(source, browser)
                except Exception: pass


_PRIMARY_AUTH = SourceAuth()
_WORKSPACE_AUTHS: dict[str, SourceAuth] = {}
_AUTHS_LOCK = threading.RLock()


def get_source_auth(source: str | None = None, wid: str | None = None) -> SourceAuth:
    if source in SHARED_SOURCES:
        return _PRIMARY_AUTH
    from workspace_context import current_workspace, is_isolated_workspace
    resolved = wid or current_workspace()
    if not is_isolated_workspace(resolved):
        return _PRIMARY_AUTH
    with _AUTHS_LOCK:
        inst = _WORKSPACE_AUTHS.get(resolved)
        if inst is None:
            inst = SourceAuth(wid=resolved)
            _WORKSPACE_AUTHS[resolved] = inst
        return inst


class _WorkspaceSourceAuthProxy:
    """Routes per-source auth calls to global shared instance (benlai) or workspace instance (lanorange/baize)."""

    def _inst(self, source: str | None = None) -> SourceAuth:
        return get_source_auth(source)

    @property
    def lock(self):
        return self._inst().lock

    @property
    def states(self):
        return self._inst().states

    @property
    def desktop(self):
        return self._inst().desktop

    @property
    def workers(self):
        return self._inst().workers

    @property
    def epochs(self):
        return self._inst().epochs

    @property
    def form_bindings(self):
        return self._inst().form_bindings

    @property
    def inputs(self):
        return self._inst().inputs

    @property
    def pending_credentials(self):
        return self._inst().pending_credentials

    @property
    def credential_prompt(self):
        return self._inst().credential_prompt

    def status(self, source):
        return get_source_auth(source).status(source)

    def start(self, source):
        return get_source_auth(source).start(source)

    def cancel(self, source):
        return get_source_auth(source).cancel(source)

    def interact(self, source, command):
        return get_source_auth(source).interact(source, command)

    def refresh(self, source):
        return get_source_auth(source).refresh(source)

    def recover(self, source):
        return get_source_auth(source).recover(source)

    def confirm_credentials(self, source, save):
        return get_source_auth(source).confirm_credentials(source, save)

    def keepalive(self, source):
        return get_source_auth(source).keepalive(source)

    def start_keepalive(self):
        return _PRIMARY_AUTH.start_keepalive()


AUTH = _WorkspaceSourceAuthProxy()
router = APIRouter(prefix='/api/fengshen-downloads/source-auth')


def _require_source_operator(request: Request, source: str):
    if source == 'xiaoxiang':
        return require_shared_auth_manage(request, '小象灯塔')
    if source in SHARED_SOURCES:
        return require_shared_auth_manage(request, SOURCES[source]['label'])
    return require_account(request)


@router.get('/{source}')
def status(source: str, request: Request):
    user = require_account(request)
    is_shared = source == 'xiaoxiang' or source in SHARED_SOURCES
    can_manage = can_manage_shared_auth(user) if is_shared else True
    if source == 'xiaoxiang':
        from xiaoxiang_source_auth import AUTH as xiang
        return {**xiang.status(), 'shared': True, 'can_manage': can_manage}
    if source not in SOURCES: raise HTTPException(404, '资料来源不存在')
    return {**get_source_auth(source).status(source), 'shared': is_shared, 'can_manage': can_manage}


@router.post('/{source}/start')
def start(source: str, request: Request):
    _require_source_operator(request, source)
    from platform_auth_control import operation, discard_meta
    with operation(source):
        discard_meta(source)
        if source == 'xiaoxiang':
            from xiaoxiang_source_auth import AUTH as xiang
            return xiang.start()
        if source not in SOURCES: raise HTTPException(404, '资料来源不存在')
        return get_source_auth(source).start(source)


@router.get('/{source}/qr')
@router.get('/{source}/frame')
def qr(source: str, request: Request):
    _require_source_operator(request, source)
    if source == 'xiaoxiang':
        from xiaoxiang_source_auth import AUTH as target
    elif source in SOURCES:
        target = get_source_auth(source)
    else:
        raise HTTPException(404, '资料来源不存在')
    with target.lock:
        state = target.states.get(source, {})
        if source in ('lanorange','lanorange_mdr','xiaoxiang') and (state.get('state')!='waiting_login' or state.get('cancelling') or not request.query_params.get('session_id') or request.query_params['session_id']!=state.get('session_id')):
            raise HTTPException(409,'认证会话已变化，请重新读取当前验证画面')
        data = target.states.get(source, {}).get('image')
        if source=='xiaoxiang':
            version=request.query_params.get('v') or ''
            desktop=target.desktop.get(source,{})
            if version and version==desktop.get('qr_version'):
                data=target.states.get(source, {}).get('image_qr')
            elif version and version==desktop.get('challenge_version'):
                data=target.states.get(source, {}).get('image')
            else:
                raise HTTPException(409,'官方验证画面已更新，请重新读取')
    if not data: raise HTTPException(404, '验证画面尚未就绪')
    geometry = target.desktop.get(source, {}).get('regions', {})
    return Response(data, media_type='image/png', headers={'Cache-Control': 'no-store', 'X-Auth-Geometry': json.dumps(geometry)})


@router.post('/{source}/interact')
async def interact(source: str, request: Request):
    _require_source_operator(request, source)
    if source == 'xiaoxiang':
        from xiaoxiang_source_auth import AUTH as target
    elif source in SOURCES:
        target = get_source_auth(source)
    else:
        raise HTTPException(404, '资料来源不存在')
    body = bytearray()
    async for chunk in request.stream():
        if len(body) + len(chunk) > 32768:
            raise HTTPException(413, '认证操作过大')
        body.extend(chunk)
    try:
        command = json.loads(body)
    except (ValueError, UnicodeDecodeError):
        raise HTTPException(400, '认证操作格式无效') from None
    return target.interact(source, command)


@router.post('/{source}/credentials')
async def credentials(source: str, request: Request):
    _require_source_operator(request, source)
    if source not in ('baize', 'benlai'):
        raise HTTPException(404, '此来源不支持保存登录凭据')
    try:
        data = await request.json()
    except (ValueError, UnicodeError):
        raise HTTPException(400, '凭据操作格式无效') from None
    if not isinstance(data, dict) or data.get('action') not in ('save', 'skip'):
        raise HTTPException(400, '凭据操作无效')
    return get_source_auth(source).confirm_credentials(source, data['action'] == 'save')
