from django.core.cache import cache
from django.db import transaction

from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status

from .cache_services import (
    get_product_from_cache,
    increment_view_counter,
    invalidate_product_cache,
)
from .models import Product
from .serializers import ProductSerializer


class ProductList(APIView):
    def get(self, request):
        products = Product.objects.all()
        serializer = ProductSerializer(products, many=True)
        return Response(serializer.data)


class ProductDetail(APIView):
    def get(self, request, pk):
        product_data = get_product_from_cache(pk)
        if product_data is None:
            return Response(
                {"error": "Product not found"},
                status=status.HTTP_404_NOT_FOUND,
            )
        # Fire-and-forget; flushed to DB by flush_view_counters task.
        increment_view_counter(pk)
        return Response(product_data)

    @transaction.atomic
    def put(self, request, pk):
        try:
            product = Product.objects.select_for_update().get(id=pk)
            serializer = ProductSerializer(product, data=request.data, partial=True)
            serializer.is_valid(raise_exception=True)
            updated_product = serializer.save()
            updated_product.version += 1
            updated_product.save(update_fields=["version"])
            invalidate_product_cache(pk)
            return Response(ProductSerializer(updated_product).data)
        except Product.DoesNotExist:
            return Response(
                {"error": "Product not found"},
                status=status.HTTP_404_NOT_FOUND,
            )


class TopProductsView(APIView):
    def get(self, request):
        cache_key = "top_products"
        cached_products = cache.get(cache_key)
        if cached_products:
            return Response(cached_products)

        products = Product.objects.order_by("-views_count")[:20]
        serialized = ProductSerializer(products, many=True).data
        cache.set(cache_key, serialized, timeout=600)
        return Response(serialized)
