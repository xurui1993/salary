"""Keep official authentication in one embedded panel, including SSO popups."""
import os
import time
from pathlib import Path

from desktop_auth_page import trusted


def edge_executable():
    """按 channel 解析 Edge 在本机要十几秒，直接定位可执行文件可降到半秒内。"""
    candidates = [os.environ.get('EDGE_EXECUTABLE')]
    for root in (os.environ.get('PROGRAMFILES(X86)'), os.environ.get('PROGRAMFILES'), os.environ.get('LOCALAPPDATA')):
        if root:
            candidates.append(str(Path(root) / 'Microsoft' / 'Edge' / 'Application' / 'msedge.exe'))
    for candidate in candidates:
        if candidate and Path(candidate).is_file():
            return candidate
    return None


def chrome_executable():
    candidates = [os.environ.get('CHROME_EXECUTABLE')]
    for root in (os.environ.get('PROGRAMFILES'), os.environ.get('PROGRAMFILES(X86)'), os.environ.get('LOCALAPPDATA')):
        if root:
            candidates.append(str(Path(root) / 'Google' / 'Chrome' / 'Application' / 'chrome.exe'))
    for candidate in candidates:
        if candidate and Path(candidate).is_file():
            return candidate
    return None


def launch_auth_browser(playwright, headless=True, args=None):
    """认证扫码页优先 Chrome：本机无头 Edge 启动波动 4~18 秒，Chrome 稳定在 0.5 秒内。"""
    options = {'headless': headless}
    if args:
        options['args'] = args
    path = chrome_executable() or edge_executable()
    if path:
        options['executable_path'] = path
    else:
        options['channel'] = 'msedge'
    return playwright.chromium.launch(**options)


def launch_edge(playwright, headless=True, args=None):
    path = edge_executable()
    options = {'headless': headless}
    if args:
        options['args'] = args
    if path:
        options['executable_path'] = path
    else:
        options['channel'] = 'msedge'
    return playwright.chromium.launch(**options)


def active_page(source, context, current):
    # Prefer the latest trusted page; never expose or control unrelated popups.
    pages = context.pages
    if not isinstance(pages, (list, tuple)):
        return current
    candidates = [page for page in pages if not page.is_closed() and trusted(source, page.url)]
    if candidates:
        return candidates[-1]
    if not current.is_closed() and trusted(source, current.url):
        return current
    raise RuntimeError('Official authentication page closed')


def navigate(page, url, cancelled):
    if cancelled.is_set():
        raise RuntimeError('Authentication cancelled')
    # Commit is enough: the worker continues rendering while the page loads.
    # No retry: repeating navigation can repeat upstream authentication actions.
    try:
        page.goto(url, wait_until='commit', timeout=10000)
    except Exception:
        if page.is_closed() or not trusted_url_loaded(page, url):
            raise
    if cancelled.is_set():
        raise RuntimeError('Authentication cancelled')


def trusted_url_loaded(page, expected):
    from urllib.parse import urlparse
    actual, wanted = urlparse(page.url), urlparse(expected)
    return actual.scheme == 'https' and actual.hostname == wanted.hostname


def phase_fields(name):
    return {'phase': name, 'phase_started_at': time.time()}


def bounded_requests(session, timeout=(3, 8)):
    original = session.post
    def post(*args, **kwargs):
        kwargs['timeout'] = timeout
        return original(*args, **kwargs)
    session.post = post
    return session
