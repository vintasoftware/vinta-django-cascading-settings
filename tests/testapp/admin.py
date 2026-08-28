"""Admin for the test app, to exercise the settings page on a project's model."""

from __future__ import annotations

from django.contrib import admin

from tests.testapp.models import Member, Organization, Team
from vinta_django_cascading_settings.admin import CascadingSettingsAdminMixin


@admin.register(Team)
class TeamAdmin(CascadingSettingsAdminMixin, admin.ModelAdmin):
    list_display = ["name", "organization", "settings_link"]


@admin.register(Organization)
class OrganizationAdmin(CascadingSettingsAdminMixin, admin.ModelAdmin):
    list_display = ["name", "settings_link"]


admin.site.register(Member)
