"""An OS-held lock; process exit releases it without stale PID guessing."""
from pathlib import Path
import os


class DownloadInstanceBusy(RuntimeError):
    pass


class InstanceLock:
    def __init__(self, path):
        self.stream = None
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        stream = path.open("a+b")
        try:
            if stream.seek(0, 2) == 0:
                stream.write(b"\0")
                stream.flush()
            stream.seek(0)
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            stream.close()
            raise DownloadInstanceBusy("下载服务已经运行，请使用现有实例；原任务未改变") from None
        self.stream = stream

    def release(self):
        if self.stream is not None:
            stream, self.stream = self.stream, None
            try:
                stream.seek(0)
                if os.name == "nt":
                    import msvcrt
                    msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(stream.fileno(), fcntl.LOCK_UN)
            finally:
                stream.close()
