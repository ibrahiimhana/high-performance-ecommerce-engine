"""Checkout service.
Handles order creation and stock updates inside a database transaction.
The main synchronization point is the row lock on Product records.
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
   
    items = list(items)
    if not items:
        raise ValueError("Empty cart")

    # Lock products in a fixed order to reduce deadlock risk.
    items.sort(key=lambda row: row["product_id"])

    product_ids = [row["product_id"] for row in items]

    # lock product rows before checking and updating stock.
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

        # Stock is checked while the row lock is held.
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
   #Transaction commits after the function returns successfully
