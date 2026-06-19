from django.db import models


class Product(models.Model):
    sku = models.CharField(max_length=64, unique=True)
    name = models.CharField(max_length=200)
    description = models.TextField(blank=True, default="")
    price = models.DecimalField(max_digits=10, decimal_places=2)

    # Contended field — all writes go through services.checkout under
    # SELECT FOR UPDATE.
    stock = models.PositiveIntegerField(default=0)

    # Bumped on every stock mutation; used by the optimistic-lock CAS.
    version = models.PositiveBigIntegerField(default=0)
    views_count = models.PositiveIntegerField(default=0)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [models.Index(fields=["sku"])]

    def __str__(self) -> str:
        return f"{self.sku} :: {self.name}"
