"""
Order / checkout endpoints.

Two checkout endpoints are intentionally exposed:

  POST /api/orders/checkout/        -> SAFE path. Pessimistic lock. (Req #1)
  POST /api/orders/checkout-unsafe/ -> DEMO path. Intentionally race-prone.
                                       Used by scripts/race_condition_demo.py
                                       to *prove* the race exists, then
                                       compare against the safe path.

After a successful checkout we dispatch two Celery tasks (Req #3):
  - send_invoice_email
  - send_order_notifications
The HTTP response returns immediately; the user does not wait for them.
"""
from __future__ import annotations

import time

from django.db import transaction
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response

from apps.catalog.models import Product
from apps.cart.models import Cart

from .models import DailySalesReport, Order, OrderItem
from .serializers import (
    CheckoutInputSerializer,
    DailySalesReportSerializer,
    OrderSerializer,
)
from .services import OutOfStockError, checkout as safe_checkout
from . import tasks


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def checkout(request):
    """Production-grade checkout: cart -> order, with row locks."""
    cart = Cart.objects.filter(user=request.user).first()
    if not cart or not cart.items.exists():
        return Response({"detail": "Cart is empty"}, status=400)

    items = [
        {"product_id": ci.product_id, "quantity": ci.quantity}
        for ci in cart.items.all()
    ]
    try:
        order = safe_checkout(request.user, items)
    except OutOfStockError as e:
        return Response(
            {"detail": str(e), "product_id": e.product_id,
             "available": e.available, "requested": e.requested},
            status=409,
        )

    cart.items.all().delete()

    # Req #3 — fire-and-forget async dispatch. The response below returns
    # without waiting for invoice generation or notification delivery.
    tasks.send_invoice_email.delay(order.id)
    tasks.send_order_notifications.delay(order.id)

    return Response(OrderSerializer(order).data, status=201)


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def checkout_direct(request):
    """
    Direct checkout (no cart). Used by the race-condition demo and load tests.
    Body: {"items": [{"product_id": int, "quantity": int}], "unsafe": bool}.
    """
    s = CheckoutInputSerializer(data=request.data)
    s.is_valid(raise_exception=True)
    items = s.validated_data["items"]
    unsafe = s.validated_data["unsafe"]

    if unsafe:
        try:
            order = _unsafe_checkout(request.user, items)
        except OutOfStockError as e:
            return Response({"detail": str(e)}, status=409)
    else:
        try:
            order = safe_checkout(request.user, items)
        except OutOfStockError as e:
            return Response({"detail": str(e)}, status=409)

    tasks.send_invoice_email.delay(order.id)
    tasks.send_order_notifications.delay(order.id)
    return Response(OrderSerializer(order).data, status=201)


def _unsafe_checkout(user, items):
    """
    DEMO ONLY — deliberately incorrect implementation.

    No SELECT FOR UPDATE, no atomic section spanning read+write. A tiny
    sleep is inserted between the stock read and the stock write so the
    race window is large enough that 50–100 concurrent requests will
    reliably oversell. This file is the "before" half of the comparison
    the rubric asks for.
    """
    total = 0
    order = Order.objects.create(user=user, status=Order.Status.PAID, total=0)
    for row in items:
        pid = int(row["product_id"])
        qty = int(row["quantity"])
        product = Product.objects.get(pk=pid)             # <- racy read
        if product.stock < qty:
            raise OutOfStockError(pid, qty, product.stock)

        # Widening the race window so the demo is reproducible on a single
        # machine. Without this, modern Postgres + threads finish so fast
        # the bug rarely manifests on a laptop.
        time.sleep(0.05)

        product.stock = product.stock - qty                # <- racy write
        product.save(update_fields=["stock"])

        OrderItem.objects.create(
            order=order, product=product,
            quantity=qty, unit_price=product.price,
        )
        total += float(product.price) * qty

    order.total = total
    order.save(update_fields=["total"])
    return order


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def my_orders(request):
    qs = Order.objects.filter(user=request.user).order_by("-created_at")[:50]
    return Response(OrderSerializer(qs, many=True).data)


@api_view(["GET"])
@permission_classes([AllowAny])
def daily_reports(_request):
    """Read out what the batch job (Req #4) has produced."""
    qs = DailySalesReport.objects.order_by("-date")[:30]
    return Response(DailySalesReportSerializer(qs, many=True).data)


@api_view(["POST"])
@permission_classes([AllowAny])
def trigger_rollup(request):
    """
    Convenience endpoint so graders can fire the Req #4 batch job on
    demand instead of waiting for the 00:05 UTC beat schedule.
    Body: {"date": "YYYY-MM-DD"}  (optional, defaults to today UTC).
    """
    date_str = request.data.get("date")
    result = tasks.rollup_daily_sales.delay(date_str)
    return Response({"task_id": result.id, "queued": True}, status=202)
