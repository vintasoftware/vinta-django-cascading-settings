"""What can go wrong, and what each one means.

Configuration problems and lookup problems are kept apart on purpose: the
first are a mistake in how the levels were set up and are the same for every
object, while the second depend on the key being asked for.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from django.utils.translation import gettext_lazy as _

if TYPE_CHECKING:
    from django.db.models import Model
    from vinta_django_questionnaires.validators.base import ValidationIssue


class CascadingSettingsError(Exception):
    """Base class for everything this package raises."""


class SettingsConfigurationError(CascadingSettingsError):
    """The levels are not set up in a way settings can be resolved through."""


class LevelNotConfigured(SettingsConfigurationError):
    """A model was asked for its settings without being a level."""

    def __init__(self, model: type[Model]) -> None:
        self.model = model
        super().__init__(
            _(
                'No settings level is configured for "%(label)s". Create a SettingsLevel '
                "pointing at its content type."
            )
            % {"label": model._meta.label}
        )


class UnknownSetting(CascadingSettingsError):
    """No settings schema in use asks this question."""

    def __init__(self, key: str) -> None:
        self.key = key
        super().__init__(_('No settings schema defines "%(key)s".') % {"key": key})


class AmbiguousSetting(CascadingSettingsError):
    """Several schemas ask it, so the caller has to say which one they mean."""

    def __init__(self, key: str, schema_keys: list[str]) -> None:
        self.key = key
        self.schema_keys = schema_keys
        super().__init__(
            _(
                'More than one settings schema defines "%(key)s" (%(schemas)s). '
                "Pass schema= to say which one."
            )
            % {"key": key, "schemas": ", ".join(schema_keys)}
        )


class LevelNotAllowed(CascadingSettingsError):
    """This schema is not held at this level."""

    def __init__(self, schema_key: str, scope_key: str) -> None:
        self.schema_key = schema_key
        self.scope_key = scope_key
        super().__init__(
            _('The "%(schema)s" settings are not held at the "%(scope)s" level.')
            % {"schema": schema_key, "scope": scope_key}
        )


class SettingLocked(CascadingSettingsError):
    """A level above this one locked the key, so this one may not set it."""

    def __init__(self, key: str, scope: str | None) -> None:
        self.key = key
        self.scope = scope
        super().__init__(
            _('"%(key)s" is locked at the "%(scope)s" level.')
            % {"key": key, "scope": scope or "?"}
        )


class SettingsValidationError(CascadingSettingsError):
    """One or more values did not pass the question's validator chain."""

    def __init__(self, issues: dict[str, list[ValidationIssue]]) -> None:
        self.issues = issues
        super().__init__(_("Some settings have values that need fixing."))

    def as_dict(self) -> dict[str, list[dict[str, Any]]]:
        """The issues in the same shape the questionnaire API already uses."""
        from vinta_django_questionnaires.submissions import PageValidation

        return PageValidation(issues=self.issues).as_dict()


__all__ = [
    "AmbiguousSetting",
    "CascadingSettingsError",
    "LevelNotAllowed",
    "LevelNotConfigured",
    "SettingLocked",
    "SettingsConfigurationError",
    "SettingsValidationError",
    "UnknownSetting",
]
