"""@timed decorator: wraps any callable to log its wall time."""
from __future__ import annotations

import functools
import logging
import time
from typing import Callable

logger = logging.getLogger("apps.core")


def timed(label: str) -> Callable:
    def decorator(fn):
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            t0 = time.perf_counter()
            try:
                return fn(*args, **kwargs)
            finally:
                dt_ms = (time.perf_counter() - t0) * 1000
                logger.info("timed[%s] %.2fms", label, dt_ms)
        return wrapper
    return decorator
