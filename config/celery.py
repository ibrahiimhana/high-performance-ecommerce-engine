"""Celery entry point + beat schedule."""
import os

from celery import Celery
from celery.schedules import crontab

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

app = Celery("ecommerce_engine")
app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks()

app.conf.beat_schedule = {
    # 00:05 UTC daily — process the previous day's orders into a summary row.
    "daily-sales-rollup": {
        "task": "apps.orders.tasks.rollup_daily_sales",
        "schedule": crontab(hour=0, minute=5),
    },
    # Flush per-product view counters from Redis to Postgres every minute.
    "flush-view-counters": {
        "task": "apps.catalog.tasks.flush_view_counters",
        "schedule": 60.0,
    },
}
