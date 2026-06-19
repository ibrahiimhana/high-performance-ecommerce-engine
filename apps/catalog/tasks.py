"""
Periodic flush of the per-product view counters from Redis to Postgres.

Supports the Req #10 bottleneck fix. The hot read path (`ProductDetail.get`)
no longer issues an `UPDATE catalog_product SET views_count = ...` per
request; instead it does `INCR view_counter:{id}` in Redis. This task
collects the buffered counts every minute and applies them to the database
in a single bulk UPDATE.

Trade-off acknowledged: view counts lag by up to 60 s. Acceptable for an
analytics counter; not acceptable for stock (which is why stock still goes
through the synchronous SELECT FOR UPDATE path in apps.orders.services).
"""
from __future__ import annotations

import logging

import redis
from celery import shared_task
from django.conf import settings
from django.db import transaction
from django.db.models import F

from apps.core.aop import timed

from .cache_services import _view_counter_key  # noqa: PLC2701
from .models import Product

logger = logging.getLogger("apps.catalog.tasks")

_r = redis.from_url(settings.REDIS_URL)


@shared_task
@timed("task.flush_view_counters")
def flush_view_counters() -> dict:
    """SCAN view_counter:* keys, atomically GETSET each to 0, apply totals
    to Postgres in one UPDATE per product."""
    cursor = 0
    pattern = _view_counter_key("*")
    flushed: dict[int, int] = {}

    while True:
        cursor, keys = _r.scan(cursor=cursor, match=pattern, count=500)
        for raw_key in keys:
            key = raw_key.decode() if isinstance(raw_key, bytes) else raw_key
            product_id_str = key.split(":")[-1]
            try:
                product_id = int(product_id_str)
            except ValueError:
                continue
            # GETSET returns the previous value and atomically resets to 0
            # — no race with concurrent INCRs from the web tier.
            old = _r.getset(key, 0)
            if old is None:
                continue
            try:
                old_int = int(old)
            except (TypeError, ValueError):
                continue
            if old_int > 0:
                flushed[product_id] = flushed.get(product_id, 0) + old_int
        if cursor == 0:
            break

    if not flushed:
        logger.info("flush_view_counters: nothing to flush")
        return {"products": 0, "total_views": 0}

    with transaction.atomic():
        for pid, delta in flushed.items():
            Product.objects.filter(pk=pid).update(
                views_count=F("views_count") + delta
            )

    summary = {
        "products": len(flushed),
        "total_views": sum(flushed.values()),
    }
    logger.info("flush_view_counters: %s", summary)
    return summary
