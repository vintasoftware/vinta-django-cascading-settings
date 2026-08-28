"""URLs for the test project, so the admin's own system checks have something to bind."""

from __future__ import annotations

from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/settings/", include("vinta_django_cascading_settings.urls")),
]
