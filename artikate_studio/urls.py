from django.conf import settings
from django.contrib import admin
from django.urls import include, path


urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/orders/", include("orders.urls")),
]


# Expose Silk only when it is actually installed.
# During tests, Silk is removed from INSTALLED_APPS.
if "silk" in settings.INSTALLED_APPS:
    urlpatterns += [
        path(
            "silk/",
            include("silk.urls", namespace="silk"),
        ),
    ]