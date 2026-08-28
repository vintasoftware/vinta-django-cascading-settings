"""URLs for the settings API.

Include them where you want them::

    (path("api/settings/", include("vinta_django_cascading_settings.urls")),)

Mount them under a prefix that captures a ``scope_key`` and every view below
reads that tenant, the way the questionnaires package does it::

    path("api/<str:scope_key>/settings/", include("vinta_django_cascading_settings.urls"))

An installation that mounts them unprefixed reads whatever tenant a level's
values were written under, which is what a single-tenant installation wants.
"""

from __future__ import annotations

from django.urls import path

from vinta_django_cascading_settings.views import SettingsView

app_name = "cascading_settings"

urlpatterns = [
    path("<slug:schema>/global/", SettingsView.as_view(), name="global-settings"),
    path(
        "<slug:schema>/<slug:level>/<path:object_id>/",
        SettingsView.as_view(),
        name="object-settings",
    ),
]
