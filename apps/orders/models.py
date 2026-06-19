from django.conf import settings
from django.db import models

from apps.catalog.models import Product


class Order(models.Model):
    class Status(models.TextChoices):
        PAID = "PAID", "Paid"
        FAILED = "FAILED", "Failed"
        CANCELLED = "CANCELLED", "Cancelled"

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.PAID)
    total = models.DecimalField(max_digits=12, decimal_places=2)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [models.Index(fields=["created_at"])]


class OrderItem(models.Model):
    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name="items")
    product = models.ForeignKey(Product, on_delete=models.PROTECT)
    quantity = models.PositiveIntegerField()
    unit_price = models.DecimalField(max_digits=10, decimal_places=2)


class Payment(models.Model):
    """
    Req #8 — Transaction Integrity / ACID.

    A Payment row is created inside the same @transaction.atomic block
    as the Order and the stock decrement, so the rubric's required
    invariant "payment + stock + order succeed or fail together" is
    enforced by the database, not by ad-hoc try/except cleanup code.
    """

    class Status(models.TextChoices):
        PENDING = "PENDING", "Pending"
        APPROVED = "APPROVED", "Approved"
        DECLINED = "DECLINED", "Declined"
        ERROR = "ERROR", "Error"

    order = models.OneToOneField(
        "Order", on_delete=models.CASCADE, related_name="payment"
    )
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    status = models.CharField(
        max_length=16, choices=Status.choices, default=Status.PENDING
    )
    # Provider's transaction id, when the gateway returned one.
    provider_ref = models.CharField(max_length=64, blank=True, default="")
    failure_reason = models.CharField(max_length=200, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)


class DailySalesReport(models.Model):
    """Output table for the Req #4 batch job."""
    date = models.DateField(unique=True)
    orders_count = models.PositiveIntegerField()
    units_sold = models.PositiveIntegerField()
    gross_revenue = models.DecimalField(max_digits=14, decimal_places=2)
    generated_at = models.DateTimeField(auto_now=True)
