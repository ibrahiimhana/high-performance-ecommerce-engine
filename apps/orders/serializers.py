from rest_framework import serializers

from .models import DailySalesReport, Order, OrderItem, Payment


class OrderItemSerializer(serializers.ModelSerializer):
    class Meta:
        model = OrderItem
        fields = ("id", "product", "quantity", "unit_price")


class PaymentSerializer(serializers.ModelSerializer):
    class Meta:
        model = Payment
        fields = ("id", "status", "amount", "provider_ref", "failure_reason", "created_at")


class OrderSerializer(serializers.ModelSerializer):
    items = OrderItemSerializer(many=True, read_only=True)
    payment = PaymentSerializer(read_only=True)

    class Meta:
        model = Order
        fields = ("id", "status", "total", "created_at", "items", "payment")


class CheckoutLine(serializers.Serializer):
    product_id = serializers.IntegerField()
    quantity = serializers.IntegerField(min_value=1)


class CheckoutInputSerializer(serializers.Serializer):
    """
    Direct-checkout input. The three optional fields are demo levers:

      unsafe:                 Req #1 — bypass locking entirely.
      lock:                   Req #7 — choose pessimistic or optimistic.
      force_payment_outcome:  Req #8 — force a specific gateway outcome.
    """
    items = CheckoutLine(many=True)
    unsafe = serializers.BooleanField(default=False)
    lock = serializers.ChoiceField(
        choices=["pessimistic", "optimistic"], default="pessimistic"
    )
    force_payment_outcome = serializers.ChoiceField(
        choices=["approved", "declined", "error"],
        required=False, allow_null=True, default=None,
    )


class DailySalesReportSerializer(serializers.ModelSerializer):
    class Meta:
        model = DailySalesReport
        fields = "__all__"
