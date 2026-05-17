"""
One-shot seed script. Run inside a web container:

    docker compose exec web1 python scripts/seed.py
"""
import os
import sys

import django

sys.path.insert(0, "/app")
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
django.setup()

from django.contrib.auth import get_user_model  # noqa: E402

from apps.catalog.models import Product  # noqa: E402

User = get_user_model()

# Demo user used by the race-condition script. Marked staff so the demo can
# reset stock via the catalog PATCH endpoint — saves users from having to
# shell into psql between phases.
demo_user, created = User.objects.get_or_create(
    username="demo",
    defaults={"email": "demo@example.com", "is_staff": True, "is_superuser": True},
)
if created:
    demo_user.set_password("demo12345")
    demo_user.save()
    print(f"created user: {demo_user.username} / demo12345 (staff)")
elif not demo_user.is_staff:
    demo_user.is_staff = True
    demo_user.is_superuser = True
    demo_user.save(update_fields=["is_staff", "is_superuser"])
    print(f"promoted user {demo_user.username} to staff")

# A handful of products.
seed_products = [
    {"sku": "LAPTOP-001", "name": "Damascus 14\" Laptop",      "price": "999.00", "stock": 100},
    {"sku": "PHONE-001",  "name": "Damascus Phone Pro",        "price": "499.00", "stock": 100},
    {"sku": "RACE-001",   "name": "Race-Condition Demo Item",  "price": "10.00",  "stock": 50},
    {"sku": "BOOK-001",   "name": "Parallel Programming 101",  "price": "25.00",  "stock": 200},
]
for row in seed_products:
    p, was_created = Product.objects.update_or_create(sku=row["sku"], defaults=row)
    print(f"{'created' if was_created else 'updated'}: {p.sku} stock={p.stock}")

print("seed done.")
