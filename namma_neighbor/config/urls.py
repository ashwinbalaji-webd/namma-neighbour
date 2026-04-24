from django.contrib import admin
from django.urls import path, include

from apps.core.views import health_check

urlpatterns = [
    path("health/", health_check, name="health-check"),
    path("admin/", admin.site.urls),
    path("api/v1/auth/", include("apps.users.urls")),
    path("api/v1/communities/", include("apps.communities.urls")),
    path("api/v1/", include("apps.vendors.urls")),
    path("api/v1/webhooks/", include("apps.core.urls_webhooks")),
]
