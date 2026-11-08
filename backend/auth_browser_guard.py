"""Bound cleanup to this attempt's own Playwright driver and its child processes."""
from contextlib import contextmanager
from pathlib import Path
import threading
import time

import psutil


class BrowserGuard:
    def __init__(self, pw, cancelled, publish, timeout=15):
        self.cancelled, self.publish, self.timeout = cancelled, publish, timeout
        self.done = threading.Event()
        self.ending = threading.Event()
        self.owner = None
        self.timed_out = False
        try:
            # Python Playwright has no public driver PID API. Confine the private
            # lookup to here and fail closed if its structure/command changes.
            pid = pw._impl_obj._connection._transport._proc.pid
            if type(pid) is int:
                process = psutil.Process(pid)
                if self._is_driver(process): self.owner = (pid, process.create_time())
        except (AttributeError, psutil.Error, TypeError):
            pass
        self.thread = threading.Thread(target=self._watch, daemon=True, name='auth-browser-cleanup')
        self.thread.start()

    @staticmethod
    def _is_driver(process):
        import playwright
        expected = (Path(playwright.__file__).parent / 'driver/package/cli.js').resolve()
        args = process.cmdline()
        return 'run-driver' in args and any(Path(arg).resolve() == expected for arg in args if arg.endswith('cli.js'))

    def terminate_owned(self):
        if self.owner is None: return False
        try:
            process = psutil.Process(self.owner[0])
            if process.create_time() != self.owner[1] or not self._is_driver(process): return False
            # Capture identity before termination so PID reuse cannot target a
            # subsequently started browser or any other platform's process.
            owned = [(child, child.create_time()) for child in process.children(recursive=True)]
            owned.append((process, self.owner[1]))
            for child, created in reversed(owned):
                try:
                    if child.create_time() == created: child.terminate()
                except psutil.NoSuchProcess: pass
            _, alive = psutil.wait_procs([p for p, _ in owned], timeout=2)
            identities = {p.pid: created for p, created in owned}
            for child in alive:
                try:
                    if child.create_time() == identities[child.pid]: child.kill()
                except psutil.NoSuchProcess: pass
            return True
        except psutil.Error:
            return False

    def closing(self):
        self.ending.set()

    def finish(self):
        self.done.set()
        self.publish({'release_state': 'released', 'release_message': '认证进程已结束'})

    def _watch(self):
        started = None
        while not self.done.wait(.2):
            if not (self.ending.is_set() or self.cancelled.is_set()): continue
            if started is None:
                started = time.monotonic()
                self.publish({'release_state': 'releasing', 'release_message': '正在结束本次认证'})
            if time.monotonic() - started < self.timeout: continue
            self.timed_out = True
            self.publish({'release_state': 'timeout', 'release_message': '认证结束超时，正在释放本次认证进程'})
            released = self.terminate_owned()
            if self.done.is_set(): return
            self.publish({'release_state': 'terminated' if released else 'unconfirmed',
                          'release_message': '本次认证进程已释放，正在确认结果' if released else '无法确认进程归属，未强制结束；请重新读取状态，仍未恢复时联系管理员'})
            return


@contextmanager
def guarded_playwright(cancelled, publish, holder):
    from playwright.sync_api import sync_playwright
    guard = None
    try:
        with sync_playwright() as pw:
            guard = BrowserGuard(pw, cancelled, publish)
            holder(guard)
            try: yield pw
            finally: guard.closing()
    finally:
        if guard: guard.finish()
