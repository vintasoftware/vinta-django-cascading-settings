"""Django application definition."""

from django.apps import AppConfig
from django.utils.translation import gettext_lazy as _


class VintaDjangoCascadingSettingsConfig(AppConfig):
    name = "vinta_django_cascading_settings"
    label = "vinta_django_cascading_settings"
    verbose_name = _("Vinta Django Cascading Settings")
    default_auto_field = "django.db.models.BigAutoField"
