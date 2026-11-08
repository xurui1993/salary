"""One ZIP policy, installed once. Generator scopes may trade size for speed."""
from contextlib import contextmanager
from contextvars import ContextVar
import zipfile

_level = ContextVar('workbook_compression', default=9)


def install_zip_policy():
    if getattr(zipfile.ZipFile.__init__, '_payroll_policy', False):
        return
    original = zipfile.ZipFile.__init__

    def initialize(self, file, mode='r', compression=zipfile.ZIP_STORED,
                   allowZip64=True, compresslevel=None, **kwargs):
        if mode in ('w', 'a', 'x') and compresslevel is None:
            if compression == zipfile.ZIP_STORED:
                compression = zipfile.ZIP_DEFLATED
            if compression == zipfile.ZIP_DEFLATED:
                compresslevel = _level.get()
        original(self, file, mode, compression=compression, allowZip64=allowZip64,
                 compresslevel=compresslevel, **kwargs)

    initialize._payroll_policy = True
    zipfile.ZipFile.__init__ = initialize


@contextmanager
def compression(level=3):
    if type(level) is not int or not 0 <= level <= 9:
        raise ValueError('压缩级别必须为 0～9')
    token = _level.set(level)
    try:
        yield
    finally:
        _level.reset(token)


install_zip_policy()
