from django.urls import path

from .views import (
    ProductList,
    ProductDetail,
    TopProductsView,
)

urlpatterns = [
    path(
        "products/",
        ProductList.as_view(),
        name="product-list"
    ),

    path(
        "products/<int:pk>/",
        ProductDetail.as_view(),
        name="product-detail"
    ),

    path(
        "top-products/",
        TopProductsView.as_view(),
        name="top-products"
    ),
]