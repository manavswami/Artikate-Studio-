from django.db.models import Prefetch, QuerySet

from .models import Order, OrderItem


def get_broken_order_summary_queryset(*, user) -> QuerySet[Order]:
    """
    Return the intentionally unoptimized queryset.

    This function exists ONLY to reproduce and demonstrate the incident.

    Expected query behaviour:

        1 query:
            Fetch all Order rows.

        N queries:
            For each order:
                order.items.all()

        M additional queries:
            For each OrderItem:
                item.product

    Example:

        200 orders
        5 items per order

        1    order query
        200  order-item queries
        1000 product queries
        --------------------
        1201 total queries

    This is a nested N+1 query problem.
    """

    return (
        Order.objects
        .filter(user=user)
        .order_by("-created_at", "-id")
    )


def get_optimized_order_summary_queryset(*, user) -> QuerySet[Order]:
    """
    Return the optimized queryset.

    ORM strategy:

    1. Fetch Order objects in the main query.

    2. Use prefetch_related() for the reverse ForeignKey relationship:

           Order -> OrderItem

       A reverse ForeignKey is a one-to-many relationship, so using
       select_related() directly on "items" is not appropriate.

       prefetch_related() executes a separate SQL query for OrderItem rows and
       associates them with their corresponding Order objects in Python.

    3. Inside the OrderItem prefetch query, use:

           select_related("product")

       OrderItem -> Product is a forward ForeignKey relationship.

       select_related() performs a SQL JOIN, loading Product in the same query
       as OrderItem.

    Expected query behaviour for the core queryset:

        Query 1:
            SELECT orders ...

        Query 2:
            SELECT order_items ...
            INNER JOIN products ...

    The query count remains constant as the number of orders and items grows,
    within the evaluated page.
    """

    optimized_items = (
        OrderItem.objects
        .select_related("product")
        .order_by("id")
    )

    return (
        Order.objects
        .filter(user=user)
        .order_by("-created_at", "-id")
        .prefetch_related(
            Prefetch(
                "items",
                queryset=optimized_items,
            )
        )
    )