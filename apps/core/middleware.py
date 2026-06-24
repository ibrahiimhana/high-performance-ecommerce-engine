"""Cross-cutting middleware: capacity cap, instance tagging, request timing."""
from __future__ import annotations

import logging
import threading
import time

from django.conf import settings
from django.http import JsonResponse

logger = logging.getLogger("apps.core")


# Endpoints that mutate stock or money — these get capacity-gated.
# Browse endpoints are intentionally unthrottled.
HEAVY_PATH_PREFIXES = (
    "/api/orders/checkout",
    "/api/cart/",
)


class CapacityControlMiddleware:
    

    _sem: threading.BoundedSemaphore | None = None
    _lock = threading.Lock()

    def __init__(self, get_response):
        self.get_response = get_response
        with CapacityControlMiddleware._lock:
            if CapacityControlMiddleware._sem is None:
                cap = int(settings.MAX_CONCURRENT_HEAVY_REQUESTS)
                CapacityControlMiddleware._sem = threading.BoundedSemaphore(cap)
                logger.info("CapacityControl: per-process cap=%d", cap)

    @staticmethod
    def _is_heavy(path: str) -> bool:
        return any(path.startswith(p) for p in HEAVY_PATH_PREFIXES)

    def __call__(self, request):
        if not self._is_heavy(request.path):
            return self.get_response(request)

        # Non-blocking acquire: get a slot now or shed load.
        if not self._sem.acquire(blocking=False):
            logger.warning("CapacityControl: shed load on %s", request.path)
            return JsonResponse(
                {"detail": "Server at capacity. Please retry."},
                status=503,
            )
        try:
            return self.get_response(request)
        finally:
            self._sem.release()


class InstanceTagMiddleware:
    #Stamp X-Instance on every response so we can see which worker served it.

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        resp = self.get_response(request)
        resp["X-Instance"] = settings.INSTANCE_NAME
        return resp


class RequestTimingMiddleware:
    

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        t0 = time.perf_counter()
        resp = self.get_response(request)
        dt_ms = (time.perf_counter() - t0) * 1000
        resp["X-Response-Time-Ms"] = f"{dt_ms:.1f}"
        if dt_ms > 250:
            logger.warning("slow request %s %s %.1fms",
                           request.method, request.path, dt_ms)
        else:
            logger.info("%s %s %.1fms", request.method, request.path, dt_ms)
        return resp
