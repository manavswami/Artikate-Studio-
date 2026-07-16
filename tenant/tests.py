from django.contrib.auth import get_user_model
from django.test import TestCase

from tenant.context import (
    clear_current_tenant,
    set_current_tenant,
)
from tenant.models import (
    Order,
    Tenant,
)


User = get_user_model()


class TenantIsolationTests(TestCase):
    """
    Verify automatic tenant isolation.

    Developers should be able to write:

        Order.objects.all()

    without manually filtering by tenant.
    """

    def setUp(self):
        self.user = User.objects.create_user(
            username="demo",
            password="password123",
        )

        self.tenant_a = Tenant.objects.create(
            name="Company A",
        )

        self.tenant_b = Tenant.objects.create(
            name="Company B",
        )

        # Company A Orders
        Order.objects.create(
            tenant=self.tenant_a,
            user=self.user,
            status=Order.Status.COMPLETED,
        )

        Order.objects.create(
            tenant=self.tenant_a,
            user=self.user,
            status=Order.Status.PENDING,
        )

        # Company B Orders
        Order.objects.create(
            tenant=self.tenant_b,
            user=self.user,
            status=Order.Status.COMPLETED,
        )

        Order.objects.create(
            tenant=self.tenant_b,
            user=self.user,
            status=Order.Status.CANCELLED,
        )

    def tearDown(self):
        clear_current_tenant()

    def test_company_a_only_sees_company_a_orders(self):
        """
        Tenant A should never see Tenant B data.
        """

        set_current_tenant(self.tenant_a)

        orders = Order.objects.all()

        self.assertEqual(
            orders.count(),
            2,
        )

        for order in orders:
            self.assertEqual(
                order.tenant,
                self.tenant_a,
            )

    def test_company_b_only_sees_company_b_orders(self):
        """
        Tenant B should never see Tenant A data.
        """

        set_current_tenant(self.tenant_b)

        orders = Order.objects.all()

        self.assertEqual(
            orders.count(),
            2,
        )

        for order in orders:
            self.assertEqual(
                order.tenant,
                self.tenant_b,
            )

    def test_without_tenant_returns_no_rows(self):
        """
        Missing tenant context should fail closed.
        """

        clear_current_tenant()

        orders = Order.objects.all()

        self.assertEqual(
            orders.count(),
            0,
        )

    def test_filter_is_also_scoped(self):
        """
        Even filter() should automatically
        remain tenant-scoped.
        """

        set_current_tenant(self.tenant_a)

        orders = Order.objects.filter(
            status=Order.Status.COMPLETED,
        )

        self.assertEqual(
            orders.count(),
            1,
        )

        self.assertEqual(
            orders.first().tenant,
            self.tenant_a,
        )