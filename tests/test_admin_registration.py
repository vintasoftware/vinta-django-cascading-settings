"""Registering the admin, including under a theme's own base classes."""

from __future__ import annotations

import pytest
from django.contrib import admin

from vinta_django_cascading_settings.admin import REGISTRY, register, unregister
from vinta_django_cascading_settings.models import ScopedSettings, SettingsLevel

pytestmark = pytest.mark.django_db


@pytest.fixture
def site():
    return admin.AdminSite(name="settings_test")


def test_registering_puts_every_model_on_the_site(site):
    register(site)

    assert {model for model, _admin in REGISTRY} <= set(site._registry)


def test_an_admin_of_your_own_is_left_alone(site):
    class MyScopeAdmin(admin.ModelAdmin):
        pass

    site.register(SettingsLevel, MyScopeAdmin)
    register(site)

    assert isinstance(site._registry[SettingsLevel], MyScopeAdmin)


def test_forcing_replaces_what_is_there(site):
    class MyScopeAdmin(admin.ModelAdmin):
        pass

    site.register(SettingsLevel, MyScopeAdmin)
    register(site, force=True)

    assert not isinstance(site._registry[SettingsLevel], MyScopeAdmin)


def test_a_theme_puts_its_own_bases_underneath(site):
    class ThemedModelAdmin(admin.ModelAdmin):
        theme = "dark"

    class ThemedInline(admin.TabularInline):
        theme = "dark"

    register(site, model_admin_base=ThemedModelAdmin, inline_base=ThemedInline)

    scoped_admin = site._registry[ScopedSettings]
    assert isinstance(scoped_admin, ThemedModelAdmin)
    assert issubclass(scoped_admin.inlines[0], ThemedInline)


def test_unregistering_takes_them_all_back_off(site):
    register(site)
    unregister(site)

    assert not set(site._registry)
