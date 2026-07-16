from django.urls import path

from .views import (
    BrokenOrderSummaryDemoView,
    OrderSummaryView,
)


urlpatterns = [
    path(
        "summary/",
        OrderSummaryView.as_view(),
        name="order-summary",
    ),
    path(
        "summary/debug-broken/",
        BrokenOrderSummaryDemoView.as_view(),
        name="order-summary-broken",
    ),
]