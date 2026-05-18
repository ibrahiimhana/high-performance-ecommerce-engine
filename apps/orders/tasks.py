
"""Celery tasks for async notifications and daily sales rollups."""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from celery import shared_task
from django.db import transaction
from django.utils import timezone as djtz

from apps.core.aop import timed

from .models import DailySalesReport, Order, OrderItem

logger = logging.getLogger("apps.orders.tasks")

CHUNK_SIZE = 500


# Async task: runs outside the checkout request
@shared_task(bind=True, max_retries=3, default_retry_delay=10)
@timed("task.send_invoice_email")
def send_invoice_email(self, order_id: int):
    """Generate and send an invoice after checkout"""
    try:
        order = Order.objects.select_related("user").get(pk=order_id)
    except Order.DoesNotExist:
        logger.warning("invoice: order %s vanished", order_id)
        return

    
    import time, random
    time.sleep(random.uniform(0.2, 0.6))
    logger.info("invoice generated for order=%s user=%s total=%s",
                order.id, order.user_id, order.total)


@shared_task(bind=True, max_retries=3, default_retry_delay=10)
@timed("task.send_order_notifications")
def send_order_notifications(self, order_id: int):
    """Send order notifications after checkout."""
    import time, random
    time.sleep(random.uniform(0.05, 0.2))
    logger.info("notifications dispatched for order=%s", order_id)


# Batch job: process daily sales without loading all rows at once
@shared_task
@timed("task.rollup_daily_sales")
def rollup_daily_sales(target_date_str: str | None = None) -> dict:
    
    if target_date_str:
        target = datetime.strptime(target_date_str, "%Y-%m-%d").date()
    else:
        target = (djtz.now() - timedelta(days=1)).date()

    start = datetime.combine(target, datetime.min.time(), tzinfo=timezone.utc)
    end = start + timedelta(days=1)

 
    qs = (
        OrderItem.objects
        .filter(order__created_at__gte=start,
                order__created_at__lt=end,
                order__status=Order.Status.PAID)
        .values_list("order_id", "quantity", "unit_price")
    )

    orders_seen: set[int] = set()
    units = 0
    revenue = Decimal("0.00")
    chunks_processed = 0

   # Stream rows in chunks to keep memory usage stable.
    chunk: list[tuple] = []
    for row in qs.iterator(chunk_size=CHUNK_SIZE):
        chunk.append(row)
        if len(chunk) >= CHUNK_SIZE:
            units, revenue = _consume_chunk(chunk, orders_seen, units, revenue)
            chunks_processed += 1
            chunk = []
    if chunk:
        units, revenue = _consume_chunk(chunk, orders_seen, units, revenue)
        chunks_processed += 1


    with transaction.atomic():
        report, _ = DailySalesReport.objects.update_or_create(
            date=target,
            defaults={
                "orders_count": len(orders_seen),
                "units_sold": units,
                "gross_revenue": revenue,
            },
        )

    summary = {
        "date": str(target),
        "orders": report.orders_count,
        "units": report.units_sold,
        "revenue": str(report.gross_revenue),
        "chunks_processed": chunks_processed,
        "chunk_size": CHUNK_SIZE,
    }
    logger.info("rollup done %s", summary)
    return summary


def _consume_chunk(chunk, orders_seen, units, revenue):
    """Pure-Python fold over a single chunk. Kept tiny on purpose."""
    for order_id, qty, unit_price in chunk:
        orders_seen.add(order_id)
        units += qty
        revenue += Decimal(unit_price) * qty
    return units, revenue
