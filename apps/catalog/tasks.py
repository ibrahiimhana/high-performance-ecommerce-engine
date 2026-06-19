"""Flush Redis view counters to Postgres once a minute."""
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
    cursor = 0
    pattern = _view_counter_key("*")
    flushed: dict[int, int] = {}

    while True:
        cursor, keys = _r.scan(cursor=cursor, match=pattern, count=500)
        for raw_key in keys:
            key = raw_key.decode() if isinstance(raw_key, bytes) else raw_key
            try:
                product_id = int(key.split(":")[-1])
            except ValueError:
                continue
            # GETSET atomically grabs the current value and resets to 0
            # so no concurrent INCR is lost.
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

    summary = {"products": len(flushed), "total_views": sum(flushed.values())}
    logger.info("flush_view_counters: %s", summary)
    return summary
