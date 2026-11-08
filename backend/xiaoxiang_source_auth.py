"""小象灯塔来源认证：灯塔（美团 Passport）与商配送看板（知了 SSO）两段登录。

浏览器只负责登录拿会话；认证状态探测全部走 HTTPS 直连。
会话沿用 xiaoxiang_lighthouse 的 DPAPI 加密文件（覆盖 meituan.com/sankuai.com）。
"""
import os
import time
import logging
import secrets
import hashlib
import json
import threading
from urllib.parse import urlsplit
from concurrent.futures import ThreadPoolExecutor
from binding_source_auth import SourceAuth

import xiaoxiang_board
import xiaoxiang_lighthouse
from xiaoxiang_lighthouse import LighthouseError, SessionExpired, find_notice, week_range, week_title

SOURCE = 'xiaoxiang'
TIMEOUT = 900
HEADLESS_GRACE = 45
KEEPALIVE_SECONDS = 900


def _headless_default():
    # 二维码已镜像到认证面板，扫码在手机上完成，默认后台运行避免弹窗；
    # 官方页面拒绝无界面环境时会自动切到可见窗口。
    return os.environ.get('XIAOXIANG_HEADLESS', '1') != '0'


HEADLESS_DEFAULT = _headless_default()

_log = logging.getLogger(__name__)


def _configured_keepalive():
    try:
        return max(0, int(os.environ.get('XIAOXIANG_KEEPALIVE_SECONDS', str(KEEPALIVE_SECONDS))))
    except ValueError:
        return KEEPALIVE_SECONDS


KEEPALIVE_SECONDS = _configured_keepalive()


class HeadlessFallback(RuntimeError):
    """官方页面在无界面环境中无法交互，需要带界面窗口接手。"""


class XiangAuth(SourceAuth):
    def __init__(self):
        super().__init__()
        self.lock = threading.RLock()
        self.states = {}
        self.stages = {'lighthouse': 'pending', 'board': 'pending'}
        self.resume_state = None
        self.resume_until = 0
        self._headless = HEADLESS_DEFAULT
        self._fallback_state = None
        self._keepalive = None
        self.lighthouse_reused = False
        self.board_reused = False

    def stage(self, name, state):
        with self.lock: self.stages[name] = state

    @staticmethod
    def probe_lighthouse(state):
        from auth_browser_runtime import bounded_requests
        with xiaoxiang_lighthouse.session_from_state(state) as session:
            bounded_requests(session)
            return find_notice(session, week_title(*week_range()))

    def status(self):
        with self.lock:
            state = self.states.get(SOURCE, {})
        saved = xiaoxiang_lighthouse.SESSION_FILE.exists()
        return {'source': SOURCE, 'sms_retry_after':self.sms_delay(SOURCE), 'busy': bool(self.workers.get(SOURCE) and self.workers[SOURCE].is_alive()), **self.releases.get(SOURCE, {}), 'state': state.get('state') or ('saved' if saved else 'signed_out'),
                'stages': dict(self.stages),
                **{key: state[key] for key in ('input_seq', 'input_completed', 'input_pending', 'checked_at', 'verified_at', 'cancelling', 'phase', 'phase_started_at') if key in state},
                'message': state.get('message', ''), 'has_qr': False, 'auth_network':state.get('auth_network',[]),
                'session_id': state.get('session_id'), 'input_error': state.get('input_error', ''), 'input_result': state.get('input_result', ''),
                **{k: v for k, v in self.desktop.get(SOURCE, {}).items() if not k.startswith('_')},
                'interactive': state.get('state') == 'waiting_login',
                'lighthouse_reused': self.lighthouse_reused,
                'board_reused': self.board_reused,
                'window_visible': bool(self.workers.get(SOURCE) and self.workers[SOURCE].is_alive() and not self._headless)}

    def _set(self, state, message):
        with self.lock:
            from auth_browser_runtime import phase_fields
            from datetime import datetime, timezone
            phase = 'waiting_user' if state == 'waiting_login' else 'finished'
            previous=self.states.get(SOURCE,{}).get('auth_network',[])
            self.states[SOURCE] = {'state': state, 'message': message, 'auth_network':previous,
                                   'checked_at': datetime.now(timezone.utc).isoformat(), **phase_fields(phase)}

    def _persist_resume(self):
        """灯塔已验证时立即落盘；知了看板失败后重试不再重复短信与安全验证。"""
        state = self.resume_state
        if not state:
            return False
        try:
            xiaoxiang_lighthouse.save_state(state)
            return True
        except Exception:
            return False

    def _cache_board_state(self, state):
        try:
            xiaoxiang_board.save_board_state(state)
            return True
        except Exception:
            return False

    def invalidate(self):
        self._set('login_required', '小象灯塔会话不可用或已失效，请在系统通道重新完成两段认证')

    def start(self):
        with self.lock:
            if (self.workers.get(SOURCE) and self.workers[SOURCE].is_alive()) or self.states.get(SOURCE, {}).get('state') in ('starting', 'waiting_login'):
                return self.status()
            from auth_browser_runtime import phase_fields
            self.states[SOURCE] = {'state': 'starting', 'message': '正在准备小象灯塔扫码登录', **phase_fields('connecting')}
            self.stages = {'lighthouse': 'checking', 'board': 'pending'}
            self._headless = HEADLESS_DEFAULT
            self._fallback_state = None
            self.lighthouse_reused = False
            self.board_reused = False
            self.cancelled[SOURCE] = threading.Event()
            self.epochs[SOURCE] = self.epochs.get(SOURCE, 0) + 1
            self.releases.pop(SOURCE, None)
            self.mode_attempts.pop(SOURCE, None)
            self.consent_choice.pop(SOURCE, None)
            self.consent_attempts.pop(SOURCE, None)
            worker = threading.Thread(target=self._login, daemon=True)
            self.workers[SOURCE] = worker
            worker.start()
        return self.status()

    def _login(self):
        from auth_browser_runtime import navigate
        import threading
        cancelled = self.cancelled.setdefault(SOURCE, threading.Event())
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            self._set('error', '服务器缺少 Playwright 运行环境，无法打开认证窗口，请联系管理员安装')
            return
        resume = self.resume_state if self.resume_state is not None and time.monotonic() < self.resume_until else None
        first_verified = False
        try:
            if resume is not None:
                try:
                    self.probe_lighthouse(resume)
                    first_verified = True
                    self.lighthouse_reused = True
                except SessionExpired:
                    resume = None
                    self.resume_state = None
                except Exception:
                    self.stage('lighthouse', 'unknown')
                    self._set('unknown', '第一段认证状态暂未确认，请检查网络后重试；不会重新发送短信')
                    return
            stored = resume if resume is not None else xiaoxiang_lighthouse.load_state()
            if stored is not None and not first_verified:
                try:
                    self.probe_lighthouse(stored)
                    first_verified=True
                    self.lighthouse_reused=True
                    self.stage('lighthouse','ready')
                except SessionExpired:
                    pass
                except Exception:
                    self.stage('lighthouse','unknown')
                    self._set('unknown','灯塔会话暂未确认，请检查网络后重试；原会话保留，不会重新发送短信')
                    return
            if first_verified:
                try:
                    xiaoxiang_board.board_probe(stored,timeout=(3,8))
                    if cancelled.is_set():
                        self._set('saved' if xiaoxiang_lighthouse.SESSION_FILE.exists() else 'signed_out', '认证已取消，原会话保留')
                        return
                    if resume is not None:
                        xiaoxiang_lighthouse.save_state(stored)
                        self.resume_state=None
                    self._cache_board_state(stored)
                    self.stage('lighthouse','ready')
                    self.stage('board','ready')
                    self._set('ready','已复用本机加密会话，无需重新登录')
                    return
                except SessionExpired:
                    pass
                except Exception:
                    self.stage('board','unknown')
                    self._set('unknown','看板会话暂未确认，请检查网络后重试；已完成灯塔认证，无需重发短信')
                    return
        except LighthouseError:
            stored = None
        # 退出登录只归档灯塔会话（passport），看板 SSO（ssosv/zl）按浏览器习惯保留：
        # 预置进新浏览器后，美团扫码即可自动带上看板，无需再扫大象。
        board_only = False
        if stored is None and not cancelled.is_set():
            seed = xiaoxiang_board.load_board_state()
            if seed is not None:
                try:
                    xiaoxiang_board.board_probe(seed, timeout=(3, 8))
                    self.board_reused = True
                    self.stage('board', 'ready')
                except SessionExpired:
                    xiaoxiang_board.discard_board_state()
                    seed = None
                except Exception:
                    pass
                if seed is not None:
                    stored = seed
                    board_only = True
                    self.stage('lighthouse', 'waiting_login')
                    if not self.board_reused:
                        self.stage('board', 'unknown')
        if self.lighthouse_reused:
            self._set('waiting_login', '灯塔会话仍有效，已跳过美团扫码；正在打开知了看板登录页，请用大象扫码登录'
                      if not HEADLESS_DEFAULT else
                      '灯塔会话仍有效，已跳过美团扫码；正在后台准备知了看板登录页，请用大象扫描认证面板中的二维码')
        elif self.board_reused:
            self._set('waiting_login', '本机保留知了看板登录态；已打开官方登录窗口，请用美团App扫码完成灯塔登录，无需再扫大象'
                      if not HEADLESS_DEFAULT else
                      '本机保留知了看板登录态，本次只需用美团App扫描认证面板中的二维码完成灯塔登录，无需再扫大象')
        elif board_only:
            self._set('waiting_login', '本机保留的知了看板登录态暂未确认；请用美团App扫码完成灯塔登录，完成后会自动尝试连接看板'
                      if not HEADLESS_DEFAULT else
                      '本机保留的知了看板登录态暂未确认；请用美团App扫描认证面板中的二维码完成灯塔登录，完成后会自动尝试连接看板')
        else:
            self._set('waiting_login', '已打开官方登录窗口；请用美团App扫描认证面板中的二维码登录，认证面板会同步状态'
                      if not HEADLESS_DEFAULT else
                      '正在无界面环境中准备官方登录；请用美团App扫描认证面板中的二维码，如官方要求安全验证会自动打开登录窗口')
        try:
            from auth_browser_guard import guarded_playwright
            from auth_browser_runtime import launch_auth_browser
            with guarded_playwright(cancelled, lambda value: self._release_update(SOURCE, value), lambda guard: self.guards.__setitem__(SOURCE, guard)) as pw:
                headless = HEADLESS_DEFAULT
                while True:
                    self._headless = headless
                    self._fallback_state = None
                    browser = launch_auth_browser(pw, headless=headless)
                    try:
                        self._run_session(browser, stored, first_verified, cancelled, navigate)
                        return
                    except HeadlessFallback:
                        if not headless:
                            raise
                        if self.stages['lighthouse'] == 'ready':
                            self._persist_resume()
                            first_verified = True
                        stored = self._fallback_state
                        self._set('waiting_login', '自动登录未完成，已打开官方登录窗口；请在窗口内完成官方验证，认证面板会继续同步状态')
                    finally:
                        # 回退重启时只关闭本浏览器，不能让守卫提前认定整轮认证结束。
                        try: browser.close()
                        except Exception: pass
                    headless = False
        except SessionExpired as exc:
            if self.stages['lighthouse'] == 'ready' and self._persist_resume():
                self.stage('board', 'error')
                self._set('saved', '等待知了看板登录超时；灯塔登录已保存，请再次点击登录继续（无需重新发送短信）')
            else:
                self.stage('board' if self.stages['lighthouse'] == 'ready' else 'lighthouse', 'error')
                self._set('error', str(exc))
        except Exception as exc:
            _log.warning('小象灯塔登录中断 error=%s: %s', type(exc).__name__, exc)
            if self.stages['lighthouse'] == 'ready' and self._persist_resume():
                self.stage('board', 'unknown')
                self._set('saved', '知了看板登录未完成（窗口可能已关闭）；灯塔登录已保存，请再次点击登录继续（无需重新发送短信）')
            else:
                self.stage('board' if self.stages['lighthouse'] == 'ready' else 'lighthouse', 'unknown')
                self._set('error', '官方认证未完成或连接中断，请重新打开认证入口')
        finally:
            if cancelled.is_set():
                self._set('saved' if xiaoxiang_lighthouse.SESSION_FILE.exists() else 'signed_out', '认证已取消，原会话保留')
                if self.stages.get('lighthouse') != 'ready':
                    self.stages = {'lighthouse': 'pending', 'board': 'pending'}
            with self.lock:
                from datetime import datetime, timezone
                self.states.get(SOURCE, {})['checked_at'] = datetime.now(timezone.utc).isoformat()
                self.guards.pop(SOURCE, None)
                self.inputs.pop(SOURCE, None)
                self.desktop.pop(SOURCE, None)
                self.form_bindings.pop(SOURCE, None)
                for key in ('image', 'session_id'):
                    self.states.get(SOURCE, {}).pop(key, None)

    def _run_session(self, browser, stored, first_verified, cancelled, navigate):
        options = {'viewport': {'width': 1100, 'height': 850},'locale':'zh-CN','timezone_id':'Asia/Shanghai'}
        if stored is not None:
            options['storage_state'] = stored
        context = browser.new_context(**options)
        from official_auth_trace import OfficialAuthTrace
        def publish_trace(events):
            with self.lock:self.states.setdefault(SOURCE,{})['auth_network']=events
        trace=OfficialAuthTrace(publish_trace)
        trace.attach(context)
        context.set_default_timeout(2000)
        page = context.new_page()
        if not first_verified:
            self.stage('lighthouse', 'waiting_login')
            navigate(page, xiaoxiang_lighthouse.ENTRY, cancelled)
            if not self._wait_lighthouse(context, page): return
            page = self._active_page(SOURCE, context, page)
        self.stage('lighthouse', 'ready')
        self.resume_state = context.storage_state()
        self.resume_until = time.monotonic() + TIMEOUT
        if self.cancelled.get(SOURCE) and self.cancelled[SOURCE].is_set():
            self._persist_resume()
            self._set('saved' if xiaoxiang_lighthouse.SESSION_FILE.exists() else 'signed_out', '认证已取消，原会话保留')
            return
        self._set('waiting_login', '灯塔会话仍有效，已跳过美团扫码；请用大象扫码完成商配送数据看板（知了）登录' if self.lighthouse_reused else
                  '灯塔登录成功；正在使用本机保留的看板登录态连接知了看板，无需再扫大象' if self.board_reused else
                  '灯塔登录成功；请在内部认证面板扫码完成商配送数据看板（知了）登录，无需再发送短信')
        self.stage('board', 'waiting_login')
        navigate(page, xiaoxiang_board.BOARD_ENTRY, cancelled)
        if not self._wait_board(context, page):
            self._persist_resume()
            return
        if self.cancelled.get(SOURCE) and self.cancelled[SOURCE].is_set():
            self._persist_resume()
            self._set('saved' if xiaoxiang_lighthouse.SESSION_FILE.exists() else 'signed_out', '认证已取消，原会话保留')
            return
        xiaoxiang_lighthouse.save_state(context.storage_state())
        self.resume_state = None
        self._cache_board_state(context.storage_state())
        self.stage('board', 'ready')
        self._set('ready', '认证成功，下载使用 HTTP 接口')

    def _probe_until(self, context, page, probe):
        # HTTP probes receive immutable cookie snapshots only. A slow official
        # status endpoint must never hold the browser's input/submit queue.
        executor=ThreadPoolExecutor(max_workers=1,thread_name_prefix='lighthouse-auth-probe')
        try:return self._probe_loop(context,page,probe,executor)
        finally:executor.shutdown(wait=False,cancel_futures=True)

    def _probe_loop(self, context, page, probe, executor):
        deadline = time.monotonic() + TIMEOUT
        last = -float('inf');future=None;probe_signature=None
        stuck_since=None
        session_id = secrets.token_urlsafe(24)
        while time.monotonic() < deadline:
            if self.cancelled.get(SOURCE) and self.cancelled[SOURCE].is_set():
                self._set('saved' if xiaoxiang_lighthouse.SESSION_FILE.exists() else 'signed_out', '认证已取消，原会话保留')
                return False
            page = self._active_page(SOURCE, context, page)
            self._capture_desktop(SOURCE, page)
            self._apply_inputs(SOURCE, page, {'width': 1100, 'height': 850})
            desktop=self.desktop.get(SOURCE,{})
            with self.lock:
                self.states.setdefault(SOURCE, {}).update(state='waiting_login', session_id=session_id)
                if desktop.get('has_qr') and desktop.get('qr_state') != 'expired':
                    self.states[SOURCE]['message'] = (
                        '请用大象扫描认证面板中的二维码完成知了看板登录'
                        if desktop.get('qr_stage') == 'board' else
                        '本机保留知了看板登录态；请用美团App扫描认证面板中的二维码完成灯塔登录，无需再扫大象'
                        if self.board_reused else
                        '请用美团App扫描认证面板中的二维码完成灯塔登录')
            state=context.storage_state()
            signature=hashlib.sha256(json.dumps(state,sort_keys=True,default=lambda value:type(value).__name__).encode()).hexdigest()
            if self._headless:
                stage1=self.stages.get('lighthouse')!='ready'
                interactive=bool(desktop.get('fields')) or bool(desktop.get('has_challenge')) or bool(desktop.get('has_qr'))
                if desktop.get('official_feedback_kind')=='environment_rejected' or (stage1 and desktop.get('official_feedback_kind')=='rejected'):
                    self._fallback_state=state
                    raise HeadlessFallback('官方拒绝了当前无界面环境中的操作，需要可见窗口完成认证')
                if interactive:
                    stuck_since=None
                elif stuck_since is None:
                    stuck_since=time.monotonic()
                elif time.monotonic()-stuck_since>=HEADLESS_GRACE:
                    self._fallback_state=state
                    raise HeadlessFallback('官方登录页面在无界面环境中没有可操作的入口')
            if future is not None and future.done():
                try:
                    future.result()
                except SessionExpired:
                    self.stage('board' if self.stages['lighthouse'] == 'ready' else 'lighthouse', 'waiting_login')
                except LighthouseError:
                    self.stage('board' if self.stages['lighthouse'] == 'ready' else 'lighthouse', 'unknown')
                    with self.lock:
                        self.states.setdefault(SOURCE, {})['message'] = '认证连接暂未确认；网络恢复后继续检查，不会自动发送短信'
                else:
                    if signature==probe_signature:
                        if self.cancelled.get(SOURCE) and self.cancelled[SOURCE].is_set():
                            continue
                        return True
                future=None
            # Wait for the official login redirect before querying business
            # data; an unauthenticated SMS form has no session to validate.
            try:login_page=urlsplit(page.url).hostname in ('passport.meituan.com','verify.meituan.com','ssosv.sankuai.com')
            except (TypeError,ValueError,AttributeError):login_page=False
            if not login_page and future is None and (signature!=probe_signature or time.monotonic()-last>=3):
                last=time.monotonic();probe_signature=signature;future=executor.submit(probe,state)
            page.wait_for_timeout(150)
        raise SessionExpired('等待登录超时（{} 秒），请重新打开认证入口'.format(TIMEOUT))

    def _wait_lighthouse(self, context, page):
        return self._probe_until(context, page, self.probe_lighthouse)

    def _wait_board(self, context, page):
        return self._probe_until(context, page, lambda state: xiaoxiang_board.board_probe(state, timeout=(3, 8)))

    def _keepalive_result(self, epoch, state, message):
        with self.lock:
            if self.epochs.get(SOURCE, 0) != epoch:
                return
            if self.workers.get(SOURCE) and self.workers[SOURCE].is_alive():
                return
            self._set(state, message)

    def keepalive(self):
        """轻量 HTTPS 探活：及时发现会话过期，不启动浏览器、不写入任何凭据。"""
        try:
            from platform_auth_control import LOCKS
            lock = LOCKS[SOURCE]
        except Exception:
            lock = None
        if lock is not None and not lock.acquire(blocking=False):
            return False
        try:
            return self._keepalive_probe()
        finally:
            if lock is not None:
                lock.release()

    def _keepalive_probe(self):
        with self.lock:
            epoch = self.epochs.get(SOURCE, 0)
            if self.workers.get(SOURCE) and self.workers[SOURCE].is_alive():
                return False
            if self.states.get(SOURCE, {}).get('state') in ('starting', 'waiting_login', 'refreshing'):
                return False
        try:
            state = xiaoxiang_lighthouse.load_state()
        except LighthouseError:
            self._keepalive_result(epoch, 'login_required', '本机会话无法读取，请重新认证；原会话保留')
            return False
        if state is None:
            return False
        try:
            self.probe_lighthouse(state)
        except SessionExpired:
            self._keepalive_result(epoch, 'login_required', '灯塔会话已失效，请重新完成认证；原会话保留')
            return False
        except Exception:
            self._keepalive_result(epoch, 'unknown', '会话保持检查暂未确认，请检查网络后重试；原会话保留')
            return False
        try:
            xiaoxiang_board.board_probe(state, timeout=(3, 8))
        except SessionExpired:
            self.stage('lighthouse', 'ready')
            self.stage('board', 'waiting_login')
            self._keepalive_result(epoch, 'partial', '灯塔会话仍有效；知了看板登录已失效，仅在下载日维度骑手分析时需要重新扫码')
            return True
        except Exception:
            self._keepalive_result(epoch, 'unknown', '灯塔会话有效；知了看板状态暂未确认，请检查网络')
            return False
        self.stage('lighthouse', 'ready')
        self.stage('board', 'ready')
        self._cache_board_state(state)
        self._keepalive_result(epoch, 'ready', '会话保持中，下载使用 HTTP 接口')
        return True

    def start_keepalive(self):
        if KEEPALIVE_SECONDS <= 0:
            return
        with self.lock:
            if self._keepalive is not None and self._keepalive.is_alive():
                return
            self._keepalive = threading.Thread(target=self._keepalive_loop, daemon=True,
                                               name='xiaoxiang-auth-keepalive')
            self._keepalive.start()

    def _keepalive_loop(self):
        while True:
            time.sleep(KEEPALIVE_SECONDS)
            try:
                self.keepalive()
            except Exception as exc:
                _log.warning('小象灯塔会话保活失败 error=%s: %s', type(exc).__name__, exc)


AUTH = XiangAuth()
