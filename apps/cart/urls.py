from django.urls import path

from . import views

urlpatterns = [
    path("", views.view_cart, name="cart-view"),
    path("add/", views.add_item, name="cart-add"),
    path("items/<int:item_id>/", views.remove_item, name="cart-remove"),
]
