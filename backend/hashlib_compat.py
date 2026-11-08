"""Compatibility shim for hashlib in Python < 3.11.

Python 3.11 introduced hashlib.file_digest to compute hash digests directly from file streams.
This shim provides an equivalent implementation for Python 3.10 and older.
"""
import hashlib

if not hasattr(hashlib, "file_digest"):
    def file_digest(fileobj, digest, /, *, _bufsize=2**18):
        digestobj = hashlib.new(digest) if isinstance(digest, str) else digest()
        while True:
            chunk = fileobj.read(_bufsize)
            if not chunk:
                break
            digestobj.update(chunk)
        return digestobj

    hashlib.file_digest = file_digest
