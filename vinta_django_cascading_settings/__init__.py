"""Settings that cascade through levels of a hierarchy.

The public API is re-exported here lazily, because importing it eagerly would
touch the models before Django has loaded its applications::

    from vinta_django_cascading_settings import get_setting, annotate_settings

    get_setting(team, "support_email")
    Team.objects.filter(organization=org).with_settings("support_email")
"""

from __future__ import annotations

import importlib
from typing import Any

_EXPORTS = {
    "AmbiguousSetting": "vinta_django_cascading_settings.exceptions",
    "CascadingSettingsError": "vinta_django_cascading_settings.exceptions",
    "CascadingSettingsQuerySetMixin": "vinta_django_cascading_settings.expressions",
    "ResolvedSetting": "vinta_django_cascading_settings.api",
    "LevelNotAllowed": "vinta_django_cascading_settings.exceptions",
    "LevelNotConfigured": "vinta_django_cascading_settings.exceptions",
    "SettingLocked": "vinta_django_cascading_settings.exceptions",
    "SettingSource": "vinta_django_cascading_settings.expressions",
    "SettingValue": "vinta_django_cascading_settings.expressions",
    "SettingsConfigurationError": "vinta_django_cascading_settings.exceptions",
    "SettingsValidationError": "vinta_django_cascading_settings.exceptions",
    "UnknownSetting": "vinta_django_cascading_settings.exceptions",
    "annotate_settings": "vinta_django_cascading_settings.expressions",
    "check_not_locked": "vinta_django_cascading_settings.api",
    "explain_setting": "vinta_django_cascading_settings.api",
    "explain_settings": "vinta_django_cascading_settings.api",
    "get_setting": "vinta_django_cascading_settings.api",
    "get_settings": "vinta_django_cascading_settings.api",
    "lock_setting": "vinta_django_cascading_settings.api",
    "resolve_schema": "vinta_django_cascading_settings.api",
    "schema_keys": "vinta_django_cascading_settings.api",
    "set_setting": "vinta_django_cascading_settings.api",
    "set_settings": "vinta_django_cascading_settings.api",
    "setting_alias": "vinta_django_cascading_settings.expressions",
    "unlock_setting": "vinta_django_cascading_settings.api",
    "unset_setting": "vinta_django_cascading_settings.api",
    "unset_settings": "vinta_django_cascading_settings.api",
    "validate_settings": "vinta_django_cascading_settings.api",
}

__all__ = sorted(_EXPORTS)


def __getattr__(name: str) -> Any:
    try:
        module = _EXPORTS[name]
    except KeyError:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}") from None
    return getattr(importlib.import_module(module), name)


def __dir__() -> list[str]:
    return __all__
