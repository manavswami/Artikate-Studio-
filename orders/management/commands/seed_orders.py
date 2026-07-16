from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.db import transaction

from orders.models import Order, OrderItem, Product


User = get_user_model()


class Command(BaseCommand):
    """
    Seed realistic order data for local N+1 profiling.

    Example:

        python manage.py seed_orders \
            --orders 250 \
            --items-per-order 5
    """

    help = "Seed order data for Section 1 profiling."

    def add_arguments(self, parser):
        parser.add_argument(
            "--orders",
            type=int,
            default=250,
            help="Number of orders to create.",
        )

        parser.add_argument(
            "--items-per-order",
            type=int,
            default=5,
            help="Number of items per order.",
        )

        parser.add_argument(
            "--username",
            type=str,
            default="demo-user",
            help="Username that owns the generated orders.",
        )

    @transaction.atomic
    def handle(self, *args, **options):
        order_count = options["orders"]
        items_per_order = options["items_per_order"]
        username = options["username"]

        if order_count < 0:
            self.stderr.write(
                self.style.ERROR(
                    "--orders cannot be negative."
                )
            )
            return

        if items_per_order < 0:
            self.stderr.write(
                self.style.ERROR(
                    "--items-per-order cannot be negative."
                )
            )
            return

        user, created = User.objects.get_or_create(
            username=username,
        )

        if created:
            # Demo-only password.
            # Never use a hardcoded password in production.
            user.set_password("demo-password")
            user.save(update_fields=["password"])

        product_count = max(items_per_order, 1)

        products = Product.objects.bulk_create(
            [
                Product(
                    name=f"Demo Product {index + 1}",
                    price=Decimal("99.99"),
                )
                for index in range(product_count)
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

        if items_per_order > 0:
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

        self.stdout.write(
            self.style.SUCCESS(
                f"Created {order_count} orders with "
                f"{items_per_order} items each for "
                f"user '{username}'."
            )
        )