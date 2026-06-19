"""
Order / checkout endpoints.

Three checkout endpoints are exposed:

  POST /api/orders/checkout/             -> SAFE pessimistic checkout
                                            (Req #1 + Req #8, cart-based)
  POST /api/orders/checkout-direct/      -> Configurable demo path.
                                            Accepts {"unsafe": bool,
                                                     "lock":"pessimistic"|"optimistic",
                                                     "force_payment_outcome":...}
                                            Used by the race-condition,
                                            optimistic-lock, and ACID demos.
  POST /api/orders/checkout-unsafe/      -> (legacy, kept for back-compat)

After a successful checkout we dispatch two Celery tasks (Req #3):
  - send_invoice_email
  - send_order_notifications
"""
from __future__ import annotations

import time
import logging

from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response

from apps.catalog.models import Product
from apps.cart.models import Cart

from .models import DailySalesReport, Order, OrderItem
from .payments import PaymentDeclined, PaymentGatewayError
from .serializers import (
    CheckoutInputSerializer,
    DailySalesReportSerializer,
    OrderSerializer,
)
from .services import (
    OptimisticLockConflict,
    OutOfStockError,
    checkout as safe_checkout,
    checkout_optimistic,
)
from . import tasks

logger = logging.getLogger("apps.orders.views")


# ---------- helpers ---------------------------------------------------------
def _payment_error_response(e):
    if isinstance(e, PaymentDeclined):
        return Response({"detail": "Payment declined", "reason": str(e)},
                        status=402)  # 402 Payment Required
    return Response({"detail": "Payment gateway error", "reason": str(e)},
                    status=502)  # 502 Bad Gateway


def _post_checkout_dispatch(order: Order):
    """Req #3 — fire-and-forget Celery tasks."""
    tasks.send_invoice_email.delay(order.id)
    tasks.send_order_notifications.delay(order.id)


# ---------- production-grade cart checkout ----------------------------------
@api_view(["POST"])
@permission_classes([IsAuthenticated])
def checkout(request):
    """Cart-based checkout. Pessimistic lock + atomic payment."""
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
    except (PaymentDeclined, PaymentGatewayError) as e:
        return _payment_error_response(e)

    cart.items.all().delete()
    _post_checkout_dispatch(order)
    return Response(OrderSerializer(order).data, status=201)


# ---------- demo / direct-buy endpoint --------------------------------------
@api_view(["POST"])
@permission_classes([IsAuthenticated])
def checkout_direct(request):
    """
    Direct checkout (no cart). Accepts:
        {
          "items": [{"product_id": int, "quantity": int}],
          "unsafe": bool,                       # Req-1 demo
          "lock":   "pessimistic" | "optimistic",  # Req-7 demo
          "force_payment_outcome":
              null | "approved" | "declined" | "error"   # Req-8 demo
        }
    """
    s = CheckoutInputSerializer(data=request.data)
    s.is_valid(raise_exception=True)

    items = s.validated_data["items"]
    unsafe = s.validated_data["unsafe"]
    lock_strategy = s.validated_data["lock"]
    fpo = s.validated_data.get("force_payment_outcome") or None

    # Branch 1 — deliberately broken path for the race-condition demo
    # (Req #1). Skips locks AND payment so the demo stays focused.
    if unsafe:
        try:
            order = _unsafe_checkout(request.user, items)
        except OutOfStockError as e:
            return Response({"detail": str(e)}, status=409)
        _post_checkout_dispatch(order)
        return Response(OrderSerializer(order).data, status=201)

    # Branch 2 — optimistic concurrency control (Req #7).
    if lock_strategy == "optimistic":
        try:
            order = checkout_optimistic(
                request.user, items, force_payment_outcome=fpo,
            )
        except OutOfStockError as e:
            return Response({"detail": str(e)}, status=409)
        except OptimisticLockConflict as e:
            return Response(
                {"detail": "Concurrent update — please retry",
                 "product_id": e.product_id, "attempts": e.attempts},
                status=409,
            )
        except (PaymentDeclined, PaymentGatewayError) as e:
            return _payment_error_response(e)
        _post_checkout_dispatch(order)
        return Response(OrderSerializer(order).data, status=201)

    # Branch 3 — pessimistic (default, Req #1 + Req #8).
    try:
        order = safe_checkout(
            request.user, items, force_payment_outcome=fpo,
        )
    except OutOfStockError as e:
        return Response({"detail": str(e)}, status=409)
    except (PaymentDeclined, PaymentGatewayError) as e:
        return _payment_error_response(e)
    _post_checkout_dispatch(order)
    return Response(OrderSerializer(order).data, status=201)


def _unsafe_checkout(user, items):
    """
    DEMO ONLY — intentionally racy. Kept exactly as in Req #1.
    Skips payment because the only thing this path is supposed to
    demonstrate is the stock race.
    """
    total = 0
    order = Order.objects.create(user=user, status=Order.Status.PAID, total=0)
    for row in items:
        pid = int(row["product_id"])
        qty = int(row["quantity"])
        product = Product.objects.get(pk=pid)
        if product.stock < qty:
            raise OutOfStockError(pid, qty, product.stock)
        time.sleep(0.05)  # widen the race window
        product.stock = product.stock - qty
        product.save(update_fields=["stock"])
        OrderItem.objects.create(
            order=order, product=product,
            quantity=qty, unit_price=product.price,
        )
        total += float(product.price) * qty
    order.total = total
    order.save(update_fields=["total"])
    return order


# ---------- read endpoints --------------------------------------------------
@api_view(["GET"])
@permission_classes([IsAuthenticated])
def my_orders(request):
    # Configurable cap so the Req-8 demo can verify deltas of >50 orders.
    try:
        limit = max(1, min(int(request.query_params.get("limit", "50")), 5000))
    except ValueError:
        limit = 50
    qs = Order.objects.filter(user=request.user).order_by("-created_at")[:limit]
    return Response(OrderSerializer(qs, many=True).data)


@api_view(["GET"])
@permission_classes([AllowAny])
def daily_reports(_request):
    qs = DailySalesReport.objects.order_by("-date")[:30]
    return Response(DailySalesReportSerializer(qs, many=True).data)


@api_view(["POST"])
@permission_classes([AllowAny])
def trigger_rollup(request):
    date_str = request.data.get("date")
    result = tasks.rollup_daily_sales.delay(date_str)
    return Response({"task_id": result.id, "queued": True}, status=202)
