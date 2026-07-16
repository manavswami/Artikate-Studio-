from rest_framework import serializers

from .models import Order, OrderItem


class OrderItemSerializer(serializers.ModelSerializer):
    """
    Serializes one order item.

    IMPORTANT:
    Accessing source="product.name" is safe only when Product has already been
    loaded efficiently.

    Without select_related("product"), Django performs a separate SQL query
    when item.product is accessed for each OrderItem instance.
    """

    product_id = serializers.IntegerField(read_only=True)

    product_name = serializers.CharField(
        source="product.name",
        read_only=True,
    )

    class Meta:
        model = OrderItem
        fields = (
            "product_id",
            "product_name",
            "quantity",
            "unit_price",
        )


class OrderSummarySerializer(serializers.ModelSerializer):
    """
    Serializer for the mobile dashboard's order summary.

    Without prefetch_related("items"), serializing items for each individual
    Order causes one additional SQL query per order.
    """

    items = OrderItemSerializer(
        many=True,
        read_only=True,
    )

    class Meta:
        model = Order
        fields = (
            "id",
            "status",
            "created_at",
            "items",
        )