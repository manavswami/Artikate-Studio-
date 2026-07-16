from django.shortcuts import render

# Create your views here.
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .serializers import OrderSummarySerializer
from .service import (
    get_broken_order_summary_queryset,
    get_optimized_order_summary_queryset,
)


DEFAULT_PAGE_SIZE = 50
MAX_PAGE_SIZE = 100


def parse_positive_integer(
    raw_value,
    *,
    default,
    maximum=None,
):
    """
    Parse and validate a positive integer query parameter.

    Raises:
        ValueError:
            If the supplied value is not an integer or is less than 1.

    Why enforce a maximum?

    Without a page-size limit, a caller could request an extremely large
    response, causing:

        - high database load,
        - high application memory usage,
        - slow serialization,
        - large network payloads.

    For a mobile dashboard, bounded pagination is safer.
    """

    if raw_value is None:
        return default

    try:
        value = int(raw_value)
    except (TypeError, ValueError):
        raise ValueError("Must be a valid integer.")

    if value < 1:
        raise ValueError("Must be greater than zero.")

    if maximum is not None:
        value = min(value, maximum)

    return value


class BaseOrderSummaryView(APIView):
    """
    Shared endpoint behaviour.

    Subclasses only decide which queryset implementation is used.

    Authentication is required so a caller can only retrieve orders belonging
    to request.user.
    """

    permission_classes = [IsAuthenticated]

    queryset_factory = None

    def get(self, request):
        try:
            page = parse_positive_integer(
                request.query_params.get("page"),
                default=1,
            )

            page_size = parse_positive_integer(
                request.query_params.get("page_size"),
                default=DEFAULT_PAGE_SIZE,
                maximum=MAX_PAGE_SIZE,
            )

        except ValueError as exc:
            return Response(
                {
                    "detail": str(exc),
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        queryset = self.queryset_factory(user=request.user)

        # Calculate slice boundaries without loading unnecessary rows.
        start = (page - 1) * page_size
        end = start + page_size

        # Django applies LIMIT/OFFSET at the SQL level.
        orders = queryset[start:end]

        serializer = OrderSummarySerializer(
            orders,
            many=True,
        )

        return Response(
            {
                "page": page,
                "page_size": page_size,
                "orders": serializer.data,
            },
            status=status.HTTP_200_OK,
        )


class OrderSummaryView(BaseOrderSummaryView):
    """
    Production endpoint.

    Uses the optimized queryset.
    """

    queryset_factory = staticmethod(
        get_optimized_order_summary_queryset
    )


class BrokenOrderSummaryDemoView(BaseOrderSummaryView):
    """
    Development-only endpoint used to reproduce the original N+1 regression.

    IMPORTANT:
    This should not be exposed in production.
    """

    queryset_factory = staticmethod(
        get_broken_order_summary_queryset
    )