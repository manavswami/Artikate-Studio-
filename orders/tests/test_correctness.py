from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase

from orders.tests.factories import (
    create_orders,
    create_user,
)


class OrderSummaryCorrectnessTests(APITestCase):
    """
    Tests correctness and important endpoint edge cases.

    Performance is tested separately so correctness failures are easier to
    diagnose.
    """

    def setUp(self):
        self.user = create_user(username="user-a")

        self.url = reverse("order-summary")

        self.client.force_authenticate(user=self.user)

    def test_unauthenticated_request_is_rejected(self):
        """
        Orders contain user-specific data, so anonymous access must fail.
        """

        self.client.force_authenticate(user=None)

        response = self.client.get(self.url)

        self.assertEqual(
            response.status_code,
            status.HTTP_403_FORBIDDEN,
        )

    def test_user_with_no_orders_gets_empty_list(self):
        response = self.client.get(self.url)

        self.assertEqual(
            response.status_code,
            status.HTTP_200_OK,
        )

        self.assertEqual(
            response.data["orders"],
            [],
        )

    def test_user_cannot_see_another_users_orders(self):
        """
        Negative authorization test.

        This proves that filtering is based on request.user.
        """

        another_user = create_user(username="user-b")

        create_orders(
            user=another_user,
            order_count=5,
            items_per_order=2,
        )

        response = self.client.get(self.url)

        self.assertEqual(
            response.status_code,
            status.HTTP_200_OK,
        )

        self.assertEqual(
            response.data["orders"],
            [],
        )

    def test_order_without_items_is_supported(self):
        create_orders(
            user=self.user,
            order_count=1,
            items_per_order=0,
        )

        response = self.client.get(self.url)

        self.assertEqual(
            response.status_code,
            status.HTTP_200_OK,
        )

        self.assertEqual(
            len(response.data["orders"]),
            1,
        )

        self.assertEqual(
            response.data["orders"][0]["items"],
            [],
        )

    def test_page_size_is_capped_at_maximum(self):
        create_orders(
            user=self.user,
            order_count=150,
            items_per_order=0,
        )

        response = self.client.get(
            self.url,
            {
                "page_size": 1000,
            },
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_200_OK,
        )

        # MAX_PAGE_SIZE is 100.
        self.assertEqual(
            len(response.data["orders"]),
            100,
        )

        self.assertEqual(
            response.data["page_size"],
            100,
        )

    def test_invalid_page_size_is_rejected(self):
        response = self.client.get(
            self.url,
            {
                "page_size": "not-an-integer",
            },
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_400_BAD_REQUEST,
        )

    def test_zero_page_size_is_rejected(self):
        response = self.client.get(
            self.url,
            {
                "page_size": 0,
            },
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_400_BAD_REQUEST,
        )