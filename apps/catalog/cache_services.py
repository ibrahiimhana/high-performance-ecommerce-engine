"""
Product cache + deferred view counter.

============================================================================
Req #6 — Distributed Caching
Req #10 — Bottleneck fix
============================================================================

Original implementation (Salma, June 16) cached the serialised product but
keyed it by `product:{id}:v{version}`. To compute the cache key the code
had to first `SELECT * FROM catalog_product` — so every supposed "cache
hit" actually still incurred one Postgres round-trip. On top of that the
view layer issued another SELECT and an UPDATE on every request to bump
`views_count` synchronously. The "cached" endpoint was doing three DB
operations per request.

This rewrite keeps the same external behaviour but:

  1. Caches by `product:{id}` alone, so a cache hit returns with ZERO DB
     queries. Invalidation moves into `apps.orders.services.checkout`
     (called immediately after a stock decrement).

  2. Defers `views_count` updates to Redis (`INCR view_counter:{id}`).
     A Celery beat task flushes the counters to Postgres every 60 s in
     a single bulk UPDATE — see `apps/catalog/tasks.py`.

The trade-off is that view counts lag by up to 60 s and stock changes
must explicitly call `invalidate_product_cache`. Both are documented
in BENCHMARK_REPORT.md.
"""
from __future__ import annotations

import logging

import redis
from django.conf import settings
from django.core.cache import cache

from .models import Product
from .serializers import ProductSerializer

logger = logging.getLogger("apps.catalog.cache")

CACHE_TIMEOUT = 60 * 5  # 5 minutes (also bounded by invalidation on writes)

# Module-level Redis client used for the view-counter INCR (Django's
# cache.incr cannot be used reliably here because it raises ValueError on
# missing keys, defeating the "no extra round trips" goal).
_redis = redis.from_url(settings.REDIS_URL)


def _product_key(product_id) -> str:
    return f"product:{product_id}"


def _view_counter_key(product_id) -> str:
    # Single namespaced bucket so the flush task can SCAN them efficiently.
    return f"view_counter:{product_id}"


def get_product_from_cache(product_id):
    """Return the serialised product dict, hitting the DB only on miss."""
    key = _product_key(product_id)
    cached = cache.get(key)
    if cached is not None:
        logger.info("CACHE HIT  -> %s", key)
        return cached

    logger.info("CACHE MISS -> %s", key)
    try:
        product = Product.objects.get(id=product_id)
    except Product.DoesNotExist:
        return None

    data = ProductSerializer(product).data
    cache.set(key, data, timeout=CACHE_TIMEOUT)
    return data


def invalidate_product_cache(product_id) -> None:
    """Drop the cached copy. Called from services.checkout after every
    stock decrement."""
    cache.delete(_product_key(product_id))


def increment_view_counter(product_id) -> None:
    """Single INCR on a Redis counter. ~50 µs round-trip; no DB."""
    try:
        _redis.incr(_view_counter_key(product_id))
    except Exception:  # noqa: BLE001
        # Counter is best-effort — if Redis hiccups we don't want to fail
        # the request.
        logger.warning("view_counter incr failed for %s", product_id)
