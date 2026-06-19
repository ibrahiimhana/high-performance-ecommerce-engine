"""Product cache + deferred view counter (Redis-backed)."""
from __future__ import annotations

import logging

import redis
from django.conf import settings
from django.core.cache import cache

from .models import Product
from .serializers import ProductSerializer

logger = logging.getLogger("apps.catalog.cache")

CACHE_TIMEOUT = 60 * 5

# Direct redis client for INCR — django's cache.incr raises if the key is
# missing, which would force an extra round-trip per call.
_redis = redis.from_url(settings.REDIS_URL)


def _product_key(product_id) -> str:
    return f"product:{product_id}"


def _view_counter_key(product_id) -> str:
    return f"view_counter:{product_id}"


def get_product_from_cache(product_id):
    """Cache-hit path returns with zero DB queries."""
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
    """Called from services.checkout after every stock change."""
    cache.delete(_product_key(product_id))


def increment_view_counter(product_id) -> None:
    try:
        _redis.incr(_view_counter_key(product_id))
    except Exception:  # noqa: BLE001
        # Best-effort; a missed view count is not worth failing a request.
        logger.warning("view_counter incr failed for %s", product_id)
