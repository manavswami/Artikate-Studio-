from django.test import TestCase
import time
from django.test.utils import CaptureQueriesContext
from django.db import connection
from orders.serializers import OrderSummarySerializer
from orders.service import (
    get_broken_order_summary_queryset,
    get_optimized_order_summary_queryset,
)
from orders.tests.factories import (
    create_orders,
    create_user,
)
from orders.models import Order

class OrderSummaryQueryPerformanceTests(TestCase):
    """
    Proves that the optimized implementation has constant query complexity.

    We test the service/queryset layer directly so authentication, sessions,
    middleware, and Silk do not pollute the ORM query count.
    """

    def setUp(self):
        self.user = create_user()

    @staticmethod
    def evaluate_and_serialize(queryset):
        """
        Force both queryset evaluation and serializer relationship access.

        Merely constructing a Django QuerySet executes no SQL because QuerySets
        are lazy. We must evaluate the queryset and access serializer.data to
        expose N+1 behaviour.
        """

        orders = list(queryset)

        return OrderSummarySerializer(
            orders,
            many=True,
        ).data

    def test_optimized_query_count_is_constant_for_one_order(self):
        create_orders(
            user=self.user,
            order_count=1,
            items_per_order=5,
        )

        queryset = get_optimized_order_summary_queryset(
            user=self.user
        )

        with self.assertNumQueries(2):
            self.evaluate_and_serialize(queryset)

    def test_optimized_query_count_is_constant_for_many_orders(self):
        create_orders(
            user=self.user,
            order_count=50,
            items_per_order=5,
        )

        queryset = get_optimized_order_summary_queryset(
            user=self.user
        )

        # Still exactly two queries:
        #
        # 1. Orders
        # 2. OrderItems JOIN Product
        with self.assertNumQueries(2):
            self.evaluate_and_serialize(queryset)

    def test_optimized_query_count_does_not_scale_with_item_count(self):
        create_orders(
            user=self.user,
            order_count=10,
            items_per_order=20,
        )

        queryset = get_optimized_order_summary_queryset(
            user=self.user
        )

        with self.assertNumQueries(2):
            self.evaluate_and_serialize(queryset)

    def test_broken_queryset_demonstrates_n_plus_one(self):
        """
        3 orders * 2 items gives:

            1 order query
            3 item queries
            6 product queries
            -----------------
            10 total queries
        """

        create_orders(
            user=self.user,
            order_count=3,
            items_per_order=2,
        )

        queryset = get_broken_order_summary_queryset(
            user=self.user
        )

        with self.assertNumQueries(10):
            self.evaluate_and_serialize(queryset)

    def test_broken_and_optimized_outputs_are_identical(self):
        """
        Optimization must not change API semantics.
        """

        create_orders(
            user=self.user,
            order_count=5,
            items_per_order=3,
        )

        broken_data = self.evaluate_and_serialize(
            get_broken_order_summary_queryset(
                user=self.user
            )
        )

        optimized_data = self.evaluate_and_serialize(
            get_optimized_order_summary_queryset(
                user=self.user
            )
        )

        self.assertEqual(
            broken_data,
            optimized_data,
        )
    def test_query_scaling_across_order_counts(self):
        """
        Observe how the broken and optimized implementations scale as the
        number of orders increases.

        This test uses multiple dataset sizes, including the scenario boundary
        of 200+ orders.

        Broken implementation:
            Query count grows with both order count and item count.

        Optimized implementation:
            Query count remains constant at two core data queries for any
            non-empty result set.

        Exact execution time is recorded for observation only. It is not used
        as a strict assertion because timing depends on hardware, operating
        system, database engine, and current machine load.
        """

        order_counts = [10, 50, 100, 200, 250]
        items_per_order = 5

        print("\n")
        print("=" * 105)
        print("SECTION 1 — N+1 QUERY SCALING OBSERVATION")
        print("=" * 105)

        print(
            f"{'Orders':<10}"
            f"{'Broken Queries':<20}"
            f"{'Optimized Queries':<22}"
            f"{'Broken Time (s)':<20}"
            f"{'Optimized Time (s)':<20}"
        )

        print("-" * 105)

        for order_count in order_counts:
            # -------------------------------------------------------------
            # Arrange
            # -------------------------------------------------------------
            #
            # Remove the previous iteration's orders so each observation
            # contains exactly the requested number of orders.
            #
            # Products may remain in the test database, which is harmless
            # because the query-count measurement starts only after setup.
            Order.objects.filter(
                user=self.user
            ).delete()

            create_orders(
                user=self.user,
                order_count=order_count,
                items_per_order=items_per_order,
            )

            # -------------------------------------------------------------
            # Measure broken implementation
            # -------------------------------------------------------------

            broken_queryset = get_broken_order_summary_queryset(
                user=self.user
            )

            broken_start = time.perf_counter()

            with CaptureQueriesContext(connection) as broken_queries:
                self.evaluate_and_serialize(broken_queryset)

            broken_duration = time.perf_counter() - broken_start

            # -------------------------------------------------------------
            # Measure optimized implementation
            # -------------------------------------------------------------

            optimized_queryset = get_optimized_order_summary_queryset(
                user=self.user
            )

            optimized_start = time.perf_counter()

            with CaptureQueriesContext(connection) as optimized_queries:
                self.evaluate_and_serialize(optimized_queryset)

            optimized_duration = time.perf_counter() - optimized_start

            # -------------------------------------------------------------
            # Calculate expected query counts
            # -------------------------------------------------------------
            #
            # Broken:
            #
            #   1 query                     -> Orders
            #   N queries                   -> OrderItems, once per Order
            #   N * items_per_order queries -> Product, once per OrderItem
            #
            expected_broken_queries = (
                1
                + order_count
                + (order_count * items_per_order)
            )

            # -------------------------------------------------------------
            # Print observation
            # -------------------------------------------------------------

            print(
                f"{order_count:<10}"
                f"{len(broken_queries):<20}"
                f"{len(optimized_queries):<22}"
                f"{broken_duration:<20.4f}"
                f"{optimized_duration:<20.4f}"
            )

            # -------------------------------------------------------------
            # Deterministic assertions
            # -------------------------------------------------------------

            self.assertEqual(
                len(broken_queries),
                expected_broken_queries,
                msg=(
                    f"Broken query count was unexpected for "
                    f"{order_count} orders."
                ),
            )

            self.assertEqual(
                len(optimized_queries),
                2,
                msg=(
                    f"Optimized query count should remain constant "
                    f"for {order_count} orders."
                ),
            )

        print("=" * 105)