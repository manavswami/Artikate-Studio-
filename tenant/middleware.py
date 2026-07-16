from django.http import Http404

from tenant.context import (
    clear_current_tenant,
    set_current_tenant,
)
from tenant.models import Tenant


class TenantMiddleware:
    """
    Resolve the current tenant for every request.

    For this assessment the tenant is identified using the
    `X-Tenant` request header.

    Example:

        X-Tenant: Company A

    In a production system the tenant would typically be
    resolved from one of the following:

    - JWT claims
    - Request subdomain
    - API Gateway
    - API Key
    """

    HEADER_NAME = "HTTP_X_TENANT"

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        """
        Resolve the tenant before the request reaches the view.

        The resolved tenant is stored in thread-local storage so
        TenantManager can automatically scope all ORM queries.

        The tenant is always cleared afterwards to prevent tenant
        leakage between requests handled by the same worker thread.
        """
        try:
            tenant_name = request.META.get(
                self.HEADER_NAME
            )

            if tenant_name:
                try:
                    tenant = Tenant.objects.get(
                        name=tenant_name
                    )
                except Tenant.DoesNotExist:
                    raise Http404(
                        "Tenant does not exist."
                    )

                set_current_tenant(
                    tenant
                )

            return self.get_response(
                request
            )

        finally:
            # Always clear the tenant context.
            #
            # Prevents tenant leakage if the same
            # worker thread handles another request.
            clear_current_tenant()