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


class DailySalesReport(models.Model):
    """Output table for the Req #4 batch job."""
    date = models.DateField(unique=True)
    orders_count = models.PositiveIntegerField()
    units_sold = models.PositiveIntegerField()
    gross_revenue = models.DecimalField(max_digits=14, decimal_places=2)
    generated_at = models.DateTimeField(auto_now=True)
