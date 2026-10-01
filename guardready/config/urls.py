"""Main URL list. Each app has its own urls.py."""

from django.contrib import admin
from django.urls import include, path

from accounts import views as account_views


def superuser_only(request):
    """The Django admin is for the superuser only."""
    return request.user.is_active and request.user.is_superuser


admin.site.has_permission = superuser_only

urlpatterns = [
    path("", account_views.home, name="home"),
    path("accounts/", include("accounts.urls")),
    path("", include("guards.urls")),
    path("audit/", include("audit.urls")),
    path("admin/", admin.site.urls),
]
