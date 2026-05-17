"""
Cross-cutting middleware.

Three concerns live here, each a textbook AOP "advice" wrapped around the
view layer rather than being scattered into every view:

  CapacityControlMiddleware  — Req #2  (bounded in-flight concurrency)
  InstanceTagMiddleware      — Req #5  (X-Served-By header for LB demo)
  RequestTimingMiddleware    — Req #10 hook (per-request latency log)

Each Gunicorn worker process holds an independent BoundedSemaphore. With
3 web containers x 3 worker processes x cap=8, the cluster's hard ceiling
on simultaneous heavy requests is 72 — well below what Postgres can serve,
but high enough to keep the pipeline busy. If we ever hit the cap, the
middleware responds 503 instead of queueing forever and starving the
worker thread pool.
"""
from __future__ import annotations

import logging
import threading
import time

from django.conf import settings
from django.http import JsonResponse

logger = logging.getLogger("apps.core")


# Endpoints that mutate stock / money. Light reads (catalog list) are NOT
# throttled so browsing stays snappy even during heavy checkout traffic.
HEAVY_PATH_PREFIXES = (
    "/api/orders/checkout",
    "/api/cart/",
)


class CapacityControlMiddleware:
    """Req #2 — bounded semaphore around heavy endpoints.

    Why a *bounded* semaphore and not a queue?
      A queue would let arbitrary requests pile up in worker memory
      while the user's HTTP client times out anyway. Failing fast with 503
      lets the load balancer route the retry to a less busy peer
      (Req #5 + Req #2 working together).
    """

    # Class-level so it survives Django's per-request middleware re-init in
    # some servers. Each *process* gets its own semaphore, which is exactly
    # what we want — the cap is per-worker, the cluster-wide ceiling falls
    # out from (workers * cap).
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
        # non-blocking acquire — we either get a slot now or shed load.
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
    """Req #5 — stamp every response with the worker that served it.

    Combined with Nginx's add_header X-Served-By $upstream_addr, this lets a
    student fire `curl -I http://localhost:8080/api/health/` repeatedly and
    visually observe least_conn balancing across web1/web2/web3.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        resp = self.get_response(request)
        resp["X-Instance"] = settings.INSTANCE_NAME
        return resp


class RequestTimingMiddleware:
    """AOP-style cross-cutting concern: latency log, no view changes needed.

    Required by the project's documentation point (a): "explain how AOP was
    applied to monitor performance." Middleware *is* Django's flavor of AOP
    — advice that wraps a join point (the view call) without modifying it.
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
