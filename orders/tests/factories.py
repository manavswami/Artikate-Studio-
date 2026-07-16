from decimal import Decimal

from django.contrib.auth import get_user_model

from orders.models import Order, OrderItem, Product


User = get_user_model()


def create_user(
    *,
    username="test-user",
):
    """
    Create a user for endpoint and queryset tests.
    """

    return User.objects.create_user(
        username=username,
        password="test-password-123",
    )


def create_orders(
    *,
    user,
    order_count,
    items_per_order,
):
    """
    Create deterministic test data.

    bulk_create() is used because setup performance is not what we are testing.
    This allows performance tests to create hundreds of orders quickly.
    """

    products = Product.objects.bulk_create(
        [
            Product(
                name=f"Product {index}",
                price=Decimal("99.99"),
            )
            for index in range(max(items_per_order, 1))
        ]
    )

    orders = Order.objects.bulk_create(
        [
            Order(
                user=user,
                status=Order.Status.COMPLETED,
            )
            for _ in range(order_count)
        ]
    )

    if items_per_order == 0:
        return orders

    items = []

    for order in orders:
        for index in range(items_per_order):
            product = products[index]

            items.append(
                OrderItem(
                    order=order,
                    product=product,
                    quantity=1,
                    unit_price=product.price,
                )
            )

    OrderItem.objects.bulk_create(items)

    return orders