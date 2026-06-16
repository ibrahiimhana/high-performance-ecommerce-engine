from django.core.cache import cache

from .models import Product
from .serializers import ProductSerializer

CACHE_TIMEOUT = 60 * 5  # 5 minutes


def get_product_cache_key(product_id, version):
    return f"product:{product_id}:v{version}"


def get_product_from_cache(product_id):

    try:
        product = Product.objects.get(id=product_id)

        cache_key = get_product_cache_key(
            product.id,
            product.version
        )

        cached_data = cache.get(cache_key)

        if cached_data:
            print(f"CACHE HIT -> {cache_key}")
            return cached_data

        print(f"CACHE MISS -> {cache_key}")

        serialized_data = ProductSerializer(product).data

        cache.set(
            cache_key,
            serialized_data,
            timeout=CACHE_TIMEOUT
        )

        return serialized_data

    except Product.DoesNotExist:
        return None


def invalidate_product_cache(product):

    cache_key = get_product_cache_key(
        product.id,
        product.version
    )

    cache.delete(cache_key)