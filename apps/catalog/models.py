from django.db import models


class Product(models.Model):
    sku = models.CharField(max_length=64, unique=True)
    name = models.CharField(max_length=200)
    description = models.TextField(blank=True, default="")
    price = models.DecimalField(max_digits=10, decimal_places=2)

    # `stock` is the contended shared resource (Req #1). Every write to this
    # field goes through services.reserve_stock(), which holds a Postgres row
    # lock for the duration of the critical section.
    stock = models.PositiveIntegerField(default=0)

    # Monotonic counter, incremented on every stock mutation. Used today to
    # invalidate the per-product cache (Req #6 prep) and reserved for
    # optimistic-lock retries in Req #7.
    version = models.PositiveBigIntegerField(default=0)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [models.Index(fields=["sku"])]

    def __str__(self) -> str:
        return f"{self.sku} :: {self.name}"
