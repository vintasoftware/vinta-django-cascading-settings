"""The app holding a scope model this package does not own."""

from django.apps import AppConfig


class ScopedAppConfig(AppConfig):
    name = "tests.scopedapp"
    label = "scopedapp"
    default_auto_field = "django.db.models.BigAutoField"
