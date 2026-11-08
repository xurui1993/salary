"""Bounded retries for Windows readers briefly denying an atomic replacement."""
import os
import time


def atomic_replace(source, destination, attempts=8):
    for attempt in range(attempts):
        try:
            os.replace(source, destination)
            return
        except OSError as exc:
            if getattr(exc, 'winerror', None) not in (5, 32, 33) or attempt == attempts - 1:
                raise
            time.sleep(min(.01 * (2 ** attempt), .2))
