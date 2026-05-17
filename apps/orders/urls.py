from django.urls import path

from . import views

urlpatterns = [
    path("checkout/", views.checkout, name="checkout"),
    path("checkout-direct/", views.checkout_direct, name="checkout-direct"),
    path("mine/", views.my_orders, name="my-orders"),
    path("reports/daily/", views.daily_reports, name="daily-reports"),
    path("reports/trigger/", views.trigger_rollup, name="trigger-rollup"),
]
