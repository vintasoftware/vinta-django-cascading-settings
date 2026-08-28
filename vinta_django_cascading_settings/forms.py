"""The form behind the settings page: one box per setting, JSON in each.

Values are written as JSON rather than through a widget per question type,
because the point of the box is to say one of three different things and a
typed widget can only say two of them: a value, no value at all -- which means
inherit -- and the value ``null``, which means "nothing, and stop asking".  An
empty box is the first; ``null`` typed into it is the second.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from django import forms
from django.utils.translation import gettext_lazy as _

from vinta_django_cascading_settings.api import (
    explain_settings,
    lock_setting,
    set_settings,
    unlock_setting,
    unset_settings,
    validate_settings,
)
from vinta_django_cascading_settings.exceptions import SettingsValidationError

if TYPE_CHECKING:
    from django.db.models import Model

    from vinta_django_cascading_settings.api import ResolvedSetting
    from vinta_django_cascading_settings.models import SettingsSchema

VALUE_PREFIX = "value_"
LOCK_PREFIX = "lock_"


class SettingsForm(forms.Form):
    """Every setting of one schema, as one level holds them.

    The form edits *this* level and nothing else: a box left empty means the
    setting is inherited, and what it would be inherited as is in the help
    text next to it.
    """

    def __init__(
        self,
        *args: Any,
        schema: SettingsSchema,
        holder: Model | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(*args, **kwargs)
        self.schema = schema
        self.holder = holder
        self.questions = {question.key: question for question in schema.questions()}
        self.resolved: dict[str, ResolvedSetting] = explain_settings(
            holder, *self.questions, schema=schema.key
        )
        self.to_set: dict[str, Any] = {}
        self.to_unset: list[str] = []
        self.locks: dict[str, bool] = {}
        for key, question in self.questions.items():
            resolved = self.resolved[key]
            self.fields[value_field(key)] = forms.CharField(
                label=question.title or key,
                required=False,
                initial=_as_json(resolved.value) if resolved.is_own else "",
                widget=forms.Textarea(attrs={"rows": 1, "class": "vLargeTextField"}),
                help_text=self.describe(resolved),
            )
            self.fields[lock_field(key)] = forms.BooleanField(
                label=_("Locked"),
                required=False,
                initial=resolved.is_locked and resolved.is_own,
                help_text=_("The levels below this one may not override it."),
            )

    def describe(self, resolved: ResolvedSetting) -> str:
        """What the help text under one box says about where it stands."""
        question = self.questions[resolved.key]
        shape = str(
            _("%(key)s, %(type)s. JSON: leave it empty to inherit.")
            % {"key": resolved.key, "type": question.question_type}
        )
        held: str
        if resolved.is_own:
            held = str(_("Set here."))
        elif resolved.is_set:
            held = str(
                _('Inherited from the "%(level)s" level as %(value)s.')
                % {"level": resolved.level, "value": _as_json(resolved.value)}
            )
        else:
            held = str(_("No level has set this."))
        locked = (
            str(
                _(' Locked at the "%(level)s" level, so this cannot override it.')
                % {"level": resolved.level}
            )
            if resolved.is_locked and not resolved.is_own
            else ""
        )
        return f"{held} {shape}{locked}"

    # -- what the boxes say ------------------------------------------------
    def clean(self) -> dict[str, Any]:
        cleaned: dict[str, Any] = super().clean() or {}
        for key in self.questions:
            raw = (cleaned.get(value_field(key)) or "").strip()
            self.locks[key] = bool(cleaned.get(lock_field(key)))
            if not raw:
                self.to_unset.append(key)
                continue
            try:
                self.to_set[key] = json.loads(raw)
            except ValueError:
                self.add_error(
                    value_field(key),
                    _("This is not valid JSON. Text goes in quotes, as in “yes”."),
                )
        if self.to_set:
            self._run_validators()
        return cleaned

    def _run_validators(self) -> None:
        """Fail the right box, rather than the form, when a value is refused."""
        try:
            validate_settings(self.to_set, schema=self.schema)
        except SettingsValidationError as error:
            for key, issues in error.issues.items():
                for issue in issues:
                    self.add_error(value_field(key), issue.message)
            for key in error.issues:
                self.to_set.pop(key, None)

    # -- writing it down ---------------------------------------------------
    def save(self) -> None:
        """Record what the boxes said, at this level only."""
        if self.to_set:
            set_settings(self.holder, self.to_set, schema=self.schema)
        if self.to_unset:
            unset_settings(self.holder, *self.to_unset, schema=self.schema)
        for key, locked in self.locks.items():
            if key in self.to_unset:
                continue
            if locked:
                lock_setting(self.holder, key, schema=self.schema)
            else:
                unlock_setting(self.holder, key, schema=self.schema)

    def rows(self) -> list[dict[str, Any]]:
        """The fields paired up, so a template can lay them out per setting."""
        return [
            {
                "key": key,
                "question": question,
                "resolved": self.resolved[key],
                "value": self[value_field(key)],
                "lock": self[lock_field(key)],
            }
            for key, question in self.questions.items()
        ]


def value_field(key: str) -> str:
    return f"{VALUE_PREFIX}{key}"


def lock_field(key: str) -> str:
    return f"{LOCK_PREFIX}{key}"


def _as_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False)


__all__ = ["LOCK_PREFIX", "VALUE_PREFIX", "SettingsForm", "lock_field", "value_field"]
