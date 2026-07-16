from django.conf import settings
from django.db import models


class Product(models.Model):
    """
    Product available for purchase.

    In a real e-commerce system, historical order pricing should generally
    not depend on the current Product.price value because product prices can
    change after an order has been placed.

    Therefore, OrderItem stores unit_price as a snapshot of the price at the
    time of purchase.
    """

    name = models.CharField(max_length=255)

    # Current catalog price.
    # Historical orders use OrderItem.unit_price instead.
    price = models.DecimalField(
        max_digits=12,
        decimal_places=2,
    )

    def __str__(self):
        return self.name


class Order(models.Model):
    """
    Represents an order belonging to exactly one authenticated user.

    Django automatically creates a database index for ForeignKey fields,
    including user_id. Therefore, adding another basic index on user_id
    would normally be redundant.
    """

    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        COMPLETED = "completed", "Completed"
        CANCELLED = "cancelled", "Cancelled"

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="orders",
    )

    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.PENDING,
    )

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        # Explicit deterministic ordering is important for pagination.
        # created_at alone is not guaranteed to be unique. If two orders have
        # the same timestamp, id acts as a deterministic tie-breaker.
        ordering = ("-created_at", "-id")

    def __str__(self):
        return f"Order {self.pk}"


class OrderItem(models.Model):
    """
    Represents a product purchased as part of an order.

    The reverse relationship is:

        order.items.all()

    Accessing this relationship repeatedly inside a loop without
    prefetch_related() creates an N+1 query pattern.
    """

    order = models.ForeignKey(
        Order,
        on_delete=models.CASCADE,
        related_name="items",
    )

    # PROTECT prevents deletion of a product referenced by historical orders.
    # Depending on business requirements, SET_NULL plus snapshot fields could
    # also be appropriate.
    product = models.ForeignKey(
        Product,
        on_delete=models.PROTECT,
        related_name="order_items",
    )

    quantity = models.PositiveIntegerField()

    # Snapshot of the purchase-time price.
    unit_price = models.DecimalField(
        max_digits=12,
        decimal_places=2,
    )

    def __str__(self):
        return f"OrderItem {self.pk} for Order {self.order_id}"