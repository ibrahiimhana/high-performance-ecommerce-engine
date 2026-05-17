"""
Celery entry point.

Req #3 (Asynchronous Queues):
    Heavy or user-non-blocking work — invoice rendering, notification
    fan-out — is dispatched to a queue here so the checkout HTTP call
    returns to the client immediately after stock is reserved.

Req #4 (Batch Processing):
    Beat schedule below kicks off the daily sales rollup, which itself
    streams through orders in chunks (see apps.orders.tasks).
"""
import os

from celery import Celery
from celery.schedules import crontab

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

app = Celery("ecommerce_engine")
app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks()

app.conf.beat_schedule = {
    # Req #4 — runs every day at 00:05 UTC, processes prior day in chunks.
    "daily-sales-rollup": {
        "task": "apps.orders.tasks.rollup_daily_sales",
        "schedule": crontab(hour=0, minute=5),
    },
}
