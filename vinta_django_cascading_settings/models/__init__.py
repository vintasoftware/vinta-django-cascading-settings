"""The models this package stores its configuration and its values in.

There are three of them and they do three separate things.  ``SettingsLevel``
is the hierarchy: which model is a level, and which level it inherits from.
``SettingsSchema`` is the definition: the questionnaire whose questions are the
settings.  ``ScopedSettings`` is the storage: what one object has actually set,
held as a questionnaire response, with ``SettingLock`` marking the values the
levels below it may not override.
"""

from __future__ import annotations

from vinta_django_cascading_settings.models.levels import MAX_CHAIN_DEPTH, SettingsLevel
from vinta_django_cascading_settings.models.schemas import SettingsSchema
from vinta_django_cascading_settings.models.values import (
    ScopedSettings,
    SettingLock,
    level_for_model,
)

__all__ = [
    "MAX_CHAIN_DEPTH",
    "ScopedSettings",
    "SettingLock",
    "SettingsLevel",
    "SettingsSchema",
    "level_for_model",
]
