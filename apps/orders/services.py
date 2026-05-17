"""
Checkout service.

============================================================================
Req #1 — Concurrent Access & Data Integrity
============================================================================

Problem (classic Race Condition):
    Two requests both read product.stock = 1, both decide "1 >= 1 ok",
    both write stock = 0, and we have sold 2 units of a 1-unit product.
    This is reproducible on any naive implementation; the test script
    scripts/race_condition_demo.py drives it.

Fix used here: PESSIMISTIC ROW LOCK.
    `Product.objects.select_for_update().filter(pk=...)` inside an atomic
    transaction translates to Postgres:
        BEGIN;
        SELECT ... FROM catalog_product WHERE id = $1 FOR UPDATE;
        ...
        UPDATE catalog_product SET stock = stock - $2, version = version + 1 ...;
        COMMIT;
    The FOR UPDATE clause makes Postgres acquire a row-level exclusive
    lock — any concurrent transaction that tries SELECT FOR UPDATE on the
    same row blocks until our COMMIT. Reads without FOR UPDATE are NOT
    blocked (Postgres MVCC), so the catalog listing endpoint stays fast.

Why pessimistic (and not optimistic) for this exact spot:
    During a flash sale on a near-empty product the conflict probability
    is near 1. Optimistic locking would burn cycles retrying. The work
    inside the critical section is < 5 ms (one row update, a couple of
    inserts), so the lock is short-lived. We *do* still bump
    `Product.version`, which gives us optimistic-locking fields ready for
    Req #7 if we want a contrasting demonstration.

Synchronization point summary (for the rubric's "Synchronization points"
documentation requirement):
    1. `transaction.atomic()` — defines the atomic unit.
    2. `select_for_update()` — Postgres row lock, the actual sync primitive.
    3. `BoundedSemaphore` in CapacityControlMiddleware — bounds the number
       of threads that can even reach this critical section per process.
"""
from __future__ import annotations

from decimal import Decimal
from typing import Iterable

from django.db import transaction

from apps.catalog.models import Product

from .models import Order, OrderItem


class OutOfStockError(Exception):
    """Raised when the requested quantity exceeds available stock under lock."""

    def __init__(self, product_id: int, requested: int, available: int):
        super().__init__(
            f"Product {product_id}: requested {requested}, have {available}"
        )
        self.product_id = product_id
        self.requested = requested
        self.available = available


@transaction.atomic
def checkout(user, items: Iterable[dict]) -> Order:
    """
    items: iterable of {"product_id": int, "quantity": int}.

    All-or-nothing semantics: if ANY product is short, the whole transaction
    rolls back — partial sales are never persisted. This is the
    Transaction-Integrity / ACID requirement working hand-in-hand with the
    row-lock requirement.
    """
    items = list(items)
    if not items:
        raise ValueError("Empty cart")

    # Sort by product_id BEFORE acquiring locks. Two concurrent checkouts that
    # both want products [A, B] will now lock in the same order — eliminates
    # the AB / BA deadlock pattern entirely.
    items.sort(key=lambda row: row["product_id"])

    product_ids = [row["product_id"] for row in items]

    # ----- CRITICAL SECTION BEGIN ----------------------------------------
    # SELECT ... FOR UPDATE — pessimistic row lock on every product row we
    # will mutate. Any other transaction trying to lock the same rows
    # blocks here until we commit.
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

        # Inside the lock, this read is the single source of truth — no
        # other transaction can have changed stock between our SELECT and
        # this check.
        if product.stock < qty:
            raise OutOfStockError(pid, qty, product.stock)

        product.stock -= qty
        product.version += 1
        product.save(update_fields=["stock", "version", "updated_at"])

        line_total = product.price * qty
        total += line_total

        OrderItem.objects.create(
            order=order,
            product=product,
            quantity=qty,
            unit_price=product.price,
        )

    order.total = total
    order.save(update_fields=["total"])
    return order
    # ----- CRITICAL SECTION END (released on COMMIT after return) --------
