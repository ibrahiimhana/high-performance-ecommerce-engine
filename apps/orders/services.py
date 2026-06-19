"""Checkout services. Pessimistic + optimistic variants, both atomic with payment."""
from __future__ import annotations

import logging
import random
import time
from decimal import Decimal
from typing import Iterable

from django.db import transaction

from apps.catalog.cache_services import invalidate_product_cache
from apps.catalog.models import Product
from apps.core.aop import timed

from . import payments
from .models import Order, OrderItem, Payment

logger = logging.getLogger("apps.orders.services")


class OutOfStockError(Exception):
    def __init__(self, product_id: int, requested: int, available: int):
        super().__init__(
            f"Product {product_id}: requested {requested}, have {available}"
        )
        self.product_id = product_id
        self.requested = requested
        self.available = available


class OptimisticLockConflict(Exception):
    def __init__(self, product_id: int, attempts: int):
        super().__init__(
            f"Product {product_id}: optimistic lock failed after {attempts} attempts"
        )
        self.product_id = product_id
        self.attempts = attempts


@timed("checkout.pessimistic")
@transaction.atomic
def checkout(user, items: Iterable[dict], *, force_payment_outcome: str | None = None) -> Order:
    items = list(items)
    if not items:
        raise ValueError("Empty cart")

    # Sort before locking so concurrent checkouts of overlapping items
    # always acquire locks in the same order -> no AB/BA deadlock.
    items.sort(key=lambda row: row["product_id"])
    product_ids = [row["product_id"] for row in items]

    locked = {
        p.id: p
        for p in Product.objects.select_for_update().filter(pk__in=product_ids)
    }

    total = Decimal("0.00")
    order = Order.objects.create(user=user, status=Order.Status.PAID, total=Decimal("0.00"))

    for row in items:
        pid = row["product_id"]
        qty = int(row["quantity"])
        if qty <= 0:
            raise ValueError(f"Bad quantity for product {pid}")

        product = locked.get(pid)
        if product is None:
            raise OutOfStockError(pid, qty, 0)
        if product.stock < qty:
            raise OutOfStockError(pid, qty, product.stock)

        product.stock -= qty
        product.version += 1
        product.save(update_fields=["stock", "version", "updated_at"])
        invalidate_product_cache(product.id)

        total += product.price * qty
        OrderItem.objects.create(
            order=order, product=product,
            quantity=qty, unit_price=product.price,
        )

    order.total = total
    order.save(update_fields=["total"])

    # Payment is inside the atomic block on purpose: if charge fails,
    # everything above rolls back (stock + order + items).
    _charge_or_rollback(order, total, force_payment_outcome)
    return order


MAX_OPTIMISTIC_RETRIES = 5
RETRY_BACKOFF_BASE_MS = 5


@timed("checkout.optimistic")
@transaction.atomic
def checkout_optimistic(user, items: Iterable[dict], *, force_payment_outcome: str | None = None) -> Order:
    items = list(items)
    if not items:
        raise ValueError("Empty cart")

    items.sort(key=lambda row: row["product_id"])

    total = Decimal("0.00")
    order = Order.objects.create(
        user=user, status=Order.Status.PAID, total=Decimal("0.00")
    )

    for row in items:
        pid = row["product_id"]
        qty = int(row["quantity"])
        if qty <= 0:
            raise ValueError(f"Bad quantity for product {pid}")

        product, attempts = _decrement_stock_optimistic(pid, qty)
        invalidate_product_cache(product.id)

        total += product.price * qty
        OrderItem.objects.create(
            order=order, product=product,
            quantity=qty, unit_price=product.price,
        )
        logger.info("optimistic decrement product=%s qty=%s attempts=%s",
                    pid, qty, attempts)

    order.total = total
    order.save(update_fields=["total"])

    _charge_or_rollback(order, total, force_payment_outcome)
    return order


def _decrement_stock_optimistic(product_id: int, qty: int) -> tuple[Product, int]:
    for attempt in range(1, MAX_OPTIMISTIC_RETRIES + 1):
        try:
            product = Product.objects.get(pk=product_id)
        except Product.DoesNotExist:
            raise OutOfStockError(product_id, qty, 0)

        if product.stock < qty:
            raise OutOfStockError(product_id, qty, product.stock)

        # Conditional UPDATE = compare-and-swap. Postgres won't let two
        # transactions both succeed against the same (id, version).
        affected = (
            Product.objects
            .filter(pk=product_id, version=product.version, stock__gte=qty)
            .update(
                stock=product.stock - qty,
                version=product.version + 1,
            )
        )
        if affected == 1:
            product.refresh_from_db()
            return product, attempt

        # Lost the race; jitter the backoff so two losers don't collide again.
        time.sleep(
            (RETRY_BACKOFF_BASE_MS * attempt + random.uniform(0, 5)) / 1000.0
        )

    raise OptimisticLockConflict(product_id, MAX_OPTIMISTIC_RETRIES)


def _charge_or_rollback(order: Order, amount: Decimal, force_outcome: str | None) -> Payment:
    try:
        ref = payments.simulate_charge(
            order_id=order.id, amount=amount, force_outcome=force_outcome,
        )
    except payments.PaymentDeclined as e:
        logger.warning("rollback (declined) order=%s err=%s", order.id, e)
        raise
    except payments.PaymentGatewayError as e:
        logger.error("rollback (gateway-error) order=%s err=%s", order.id, e)
        raise

    return Payment.objects.create(
        order=order,
        amount=amount,
        status=Payment.Status.APPROVED,
        provider_ref=ref,
    )
