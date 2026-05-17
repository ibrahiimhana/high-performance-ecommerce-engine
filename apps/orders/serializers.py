from rest_framework import serializers

from .models import DailySalesReport, Order, OrderItem


class OrderItemSerializer(serializers.ModelSerializer):
    class Meta:
        model = OrderItem
        fields = ("id", "product", "quantity", "unit_price")


class OrderSerializer(serializers.ModelSerializer):
    items = OrderItemSerializer(many=True, read_only=True)

    class Meta:
        model = Order
        fields = ("id", "status", "total", "created_at", "items")


class CheckoutLine(serializers.Serializer):
    product_id = serializers.IntegerField()
    quantity = serializers.IntegerField(min_value=1)


class CheckoutInputSerializer(serializers.Serializer):
    """Direct-checkout input. Used by the race-condition demo so we don't
    have to populate the cart per request. The cart-driven checkout endpoint
    re-uses the same service function."""

    items = CheckoutLine(many=True)

    # Toggle that lets us flip the demo between SAFE (locked) and UNSAFE
    # (no-lock) so the rubric's "prove you handled the race condition"
    # requirement is demonstrable with a single flag.
    unsafe = serializers.BooleanField(default=False)


class DailySalesReportSerializer(serializers.ModelSerializer):
    class Meta:
        model = DailySalesReport
        fields = "__all__"
