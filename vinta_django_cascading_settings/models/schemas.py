"""Which questionnaire says what a set of settings is made of."""

from __future__ import annotations

from typing import TYPE_CHECKING

from django.core.exceptions import ValidationError
from django.db import models
from django.utils.translation import gettext_lazy as _
from vinta_django_questionnaires.models import BaseModel, Questionnaire

from vinta_django_cascading_settings.exceptions import SettingsConfigurationError
from vinta_django_cascading_settings.models.levels import SettingsLevel

if TYPE_CHECKING:
    from collections.abc import Iterator

    from vinta_django_questionnaires.models import Question, QuestionnaireVersion


class SettingsSchema(BaseModel):
    """A questionnaire read as a set of settings.

    The questionnaire is the definition and nothing else: its question keys are
    the setting keys, its question types say what a value looks like, and its
    validator chains are what a value has to pass.  What a given object has
    actually set lives in the answers underneath a ``ScopedSettings``.
    """

    key = models.SlugField(
        _("key"),
        max_length=100,
        unique=True,
        help_text=_('How this set of settings is referred to, such as "billing".'),
    )
    questionnaire = models.OneToOneField(
        Questionnaire,
        on_delete=models.PROTECT,
        related_name="settings_schema",
        verbose_name=_("questionnaire"),
        help_text=_("The questionnaire whose questions are the settings."),
    )
    levels = models.ManyToManyField(
        SettingsLevel,
        blank=True,
        related_name="schemas",
        verbose_name=_("levels"),
        help_text=_(
            "The levels allowed to hold values for these settings. "
            "Leave it empty to allow every level."
        ),
    )
    is_active = models.BooleanField(
        _("is active"),
        default=True,
        help_text=_("Inactive schemas are ignored when a key is looked up without one."),
    )

    class Meta:
        verbose_name = _("settings schema")
        verbose_name_plural = _("settings schemas")
        ordering = ["key"]

    def __str__(self) -> str:
        return self.key

    # -- what it is made of ------------------------------------------------
    @property
    def version(self) -> QuestionnaireVersion:
        """The version new settings are recorded against.

        The latest published one, or the latest of any status when nothing has
        been published yet, so a schema is usable while it is still a draft.
        """
        questionnaire = self.questionnaire
        version = questionnaire.latest_published_version or questionnaire.latest_version
        if version is None:
            raise SettingsConfigurationError(
                _('The "%(key)s" settings questionnaire has no version yet.') % {"key": self.key}
            )
        return version

    def questions(self) -> Iterator[Question]:
        """Every question the current version asks, in order."""
        return self.version.iter_questions()

    def question_keys(self) -> list[str]:
        return [question.key for question in self.questions()]

    def allows(self, level: SettingsLevel) -> bool:
        """Whether *level* may hold values for these settings."""
        if not self.pk:
            return True
        allowed = self.levels.all()
        return not allowed.exists() or allowed.filter(pk=level.pk).exists()

    def clean(self) -> None:
        super().clean()
        if self.questionnaire_id and not self.questionnaire.is_active and self.is_active:
            raise ValidationError(
                {"is_active": _("Its questionnaire is not active, so these settings cannot be.")}
            )


__all__ = ["SettingsSchema"]
