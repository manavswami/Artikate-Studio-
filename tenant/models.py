from django.db import models

from django.conf import settings

from tenant.managers import TenantManager

class Tenant(models.Model):
    """
    Represents one customer (tenant) in the SaaS application.

    Every business object (orders, invoices, etc.)
    belongs to exactly one tenant.
    """

    name = models.CharField(
        max_length=255,
        unique=True,
    )

    created_at = models.DateTimeField(
        auto_now_add=True,
    )

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name
    




# Register additional models with Django
from .tenant_models import Product, Order, OrderItem