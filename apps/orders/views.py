from __future__ import annotations

import logging
import time

from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response

from apps.cart.models import Cart
from apps.catalog.models import Product

from . import tasks
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

logger = logging.getLogger("apps.orders.views")


def _payment_error_response(e):
    if isinstance(e, PaymentDeclined):
        return Response({"detail": "Payment declined", "reason": str(e)}, status=402)
    return Response({"detail": "Payment gateway error", "reason": str(e)}, status=502)


def _post_checkout_dispatch(order: Order):
    tasks.send_invoice_email.delay(order.id)
    tasks.send_order_notifications.delay(order.id)


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def checkout(request):
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


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def checkout_direct(request):
    """Direct checkout (no cart). Body accepts `unsafe`, `lock`,
    and `force_payment_outcome` for the demo scripts."""
    s = CheckoutInputSerializer(data=request.data)
    s.is_valid(raise_exception=True)

    items = s.validated_data["items"]
    unsafe = s.validated_data["unsafe"]
    lock_strategy = s.validated_data["lock"]
    fpo = s.validated_data.get("force_payment_outcome") or None

    if unsafe:
        try:
            order = _unsafe_checkout(request.user, items)
        except OutOfStockError as e:
            return Response({"detail": str(e)}, status=409)
        _post_checkout_dispatch(order)
        return Response(OrderSerializer(order).data, status=201)

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
    """Racy on purpose — used by the demo to show the bug. The sleep
    widens the race window so it's reproducible on a laptop."""
    total = 0
    order = Order.objects.create(user=user, status=Order.Status.PAID, total=0)
    for row in items:
        pid = int(row["product_id"])
        qty = int(row["quantity"])
        product = Product.objects.get(pk=pid)
        if product.stock < qty:
            raise OutOfStockError(pid, qty, product.stock)
        time.sleep(0.05)
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


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def my_orders(request):
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
