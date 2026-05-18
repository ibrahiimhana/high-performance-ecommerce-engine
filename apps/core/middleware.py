"""Middleware for capacity control, instance tagging, and request timing """
from __future__ import annotations

import logging
import threading
import time

from django.conf import settings
from django.http import JsonResponse

logger = logging.getLogger("apps.core")


# Only heavy write endpoints are throttled
HEAVY_PATH_PREFIXES = (
    "/api/orders/checkout",
    "/api/cart/",
)


class CapacityControlMiddleware:
    """Limit concurrent heavy requests per worker process."""

    
    _sem: threading.BoundedSemaphore | None = None
    _lock = threading.Lock()

    def __init__(self, get_response):
        self.get_response = get_response
        with CapacityControlMiddleware._lock:
            if CapacityControlMiddleware._sem is None:
                cap = int(settings.MAX_CONCURRENT_HEAVY_REQUESTS)
                CapacityControlMiddleware._sem = threading.BoundedSemaphore(cap)
                logger.info("CapacityControl: per-process semaphore cap=%d", cap)

    @staticmethod
    def _is_heavy(path: str) -> bool:
        return any(path.startswith(p) for p in HEAVY_PATH_PREFIXES)

    def __call__(self, request):
        if not self._is_heavy(request.path):
            return self.get_response(request)

        sem = self._sem
        # non-blocking acquire — we either get a slot now or shed load
        acquired = sem.acquire(blocking=False)
        if not acquired:
            logger.warning("CapacityControl: shed load on %s", request.path)
            return JsonResponse(
                {"detail": "Server at capacity. Please retry."},
                status=503,
            )
        try:
            return self.get_response(request)
        finally:
            sem.release()


class InstanceTagMiddleware:
    """Add the current instance name to the response headers."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        resp = self.get_response(request)
        resp["X-Instance"] = settings.INSTANCE_NAME
        return resp


class RequestTimingMiddleware:
    """Log request duration without changing view code
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        t0 = time.perf_counter()
        resp = self.get_response(request)
        dt_ms = (time.perf_counter() - t0) * 1000
        resp["X-Response-Time-Ms"] = f"{dt_ms:.1f}"
        # WARN above 250ms so bottleneck analysis (Req #10) has something to
        # grep on.
        if dt_ms > 250:
            logger.warning("slow request %s %s %.1fms",
                           request.method, request.path, dt_ms)
        else:
            logger.info("%s %s %.1fms", request.method, request.path, dt_ms)
        return resp
