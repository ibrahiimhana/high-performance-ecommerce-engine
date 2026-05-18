from django.db import transaction
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from .models import Cart, CartItem
from .serializers import AddToCartSerializer, CartSerializer


def _get_or_create_cart(user) -> Cart:
    cart, _ = Cart.objects.get_or_create(user=user)
    return cart


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def view_cart(request):
    cart = _get_or_create_cart(request.user)
    return Response(CartSerializer(cart).data)


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def add_item(request):
    s = AddToCartSerializer(data=request.data)
    s.is_valid(raise_exception=True)
    
    with transaction.atomic():
        cart = _get_or_create_cart(request.user)
        item, created = CartItem.objects.get_or_create(
            cart=cart,
            product_id=s.validated_data["product_id"],
            defaults={"quantity": s.validated_data["quantity"]},
        )
        if not created:
            item.quantity = item.quantity + s.validated_data["quantity"]
            item.save(update_fields=["quantity"])
    return Response(CartSerializer(cart).data, status=status.HTTP_200_OK)


@api_view(["DELETE"])
@permission_classes([IsAuthenticated])
def remove_item(request, item_id: int):
    cart = _get_or_create_cart(request.user)
    cart.items.filter(pk=item_id).delete()
    return Response(CartSerializer(cart).data)
