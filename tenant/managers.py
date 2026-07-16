from django.db import models

from .context import get_current_tenant


class TenantManager(models.Manager):
    """
    Automatically scopes every queryset to the current tenant.

    Example:

        Order.objects.all()

    becomes

        Order.objects.filter(
            tenant=current_tenant
        )

    without requiring developers to remember the filter.
    """

    def get_queryset(self):
        queryset = super().get_queryset()

        tenant = get_current_tenant()

        # No tenant has been bound to this request.
        #
        # This usually means:
        #
        # - middleware has not run
        # - shell
        # - migrations
        # - management command
        #
        # Returning queryset.none() is safer than returning
        # every tenant's data.
        if tenant is None:
            return queryset.none()

        return queryset.filter(
            tenant=tenant,
        )