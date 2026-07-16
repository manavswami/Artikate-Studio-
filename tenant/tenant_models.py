from django.contrib.auth import get_user_model
from django.db import models

from tenant.managers import TenantManager
from tenant.models import Tenant


User = get_user_model()


class Product(models.Model):
    """
    Simple product model used only for the
    multi-tenant assessment.
    """

    name = models.CharField(
        max_length=255,
    )

    price = models.DecimalField(
        max_digits=10,
        decimal_places=2,
    )

    def __str__(self):
        return self.name


class Order(models.Model):
    """
    Every order belongs to exactly one tenant.

    The important part is:

        objects = TenantManager()

    which automatically scopes every query.
    """

    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        COMPLETED = "completed", "Completed"
        CANCELLED = "cancelled", "Cancelled"

    tenant = models.ForeignKey(
        Tenant,
        on_delete=models.CASCADE,
        related_name="orders",
    )

    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="tenant_orders",
    )

    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.PENDING,
    )

    created_at = models.DateTimeField(
        auto_now_add=True,
    )

    # -----------------------------
    # Automatic tenant isolation
    # -----------------------------
    objects = TenantManager()

    class Meta:
        ordering = [
            "-created_at",
        ]

    def __str__(self):
        return (
            f"Order #{self.pk}"
        )


class OrderItem(models.Model):

    order = models.ForeignKey(
        Order,
        on_delete=models.CASCADE,
        related_name="items",
    )

    product = models.ForeignKey(
        Product,
        on_delete=models.CASCADE,
    )

    quantity = models.PositiveIntegerField()

    unit_price = models.DecimalField(
        max_digits=10,
        decimal_places=2,
    )

    def __str__(self):
        return (
            f"{self.product.name} x {self.quantity}"
        )