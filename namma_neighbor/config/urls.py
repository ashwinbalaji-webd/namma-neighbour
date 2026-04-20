from django.contrib import admin
from django.urls import path, include

from apps.core.views import health_check

urlpatterns = [
    path("health/", health_check, name="health-check"),
    path("admin/", admin.site.urls),
    path("api/v1/auth/", include("apps.users.urls")),
]
