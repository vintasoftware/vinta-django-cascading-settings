"""The levels settings cascade through, and how one finds the level above it."""

from __future__ import annotations

from typing import TYPE_CHECKING

from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Value
from django.db.models.functions import Coalesce
from django.utils.translation import gettext_lazy as _
from vinta_django_questionnaires.models import BaseModel

from vinta_django_cascading_settings.lookups import follow_lookup

if TYPE_CHECKING:
    from collections.abc import Iterator

    from django.db.models import Model

#: How far a chain may be walked before it is treated as a mistake.
MAX_CHAIN_DEPTH = 20


class SettingsLevel(BaseModel):
    """One level of the hierarchy, tied to a model through its content type.

    A level knows the level above it and the ORM path that gets there, which
    is what lets the resolver walk the whole chain inside a single query.  The
    level with no content type is the global one: it holds the values that
    apply when nothing closer to the object has an opinion, and every chain
    that reaches it ends there.
    """

    key = models.SlugField(
        _("key"),
        max_length=100,
        unique=True,
        help_text=_('How this level is referred to, such as "organization" or "team".'),
    )
    name = models.CharField(_("name"), max_length=255, blank=True, default="")
    content_type = models.ForeignKey(
        ContentType,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="cascading_settings_levels",
        verbose_name=_("content type"),
        help_text=_(
            "The model this level attaches to. Leave it empty for the global level, "
            "which holds the values everything else falls back to."
        ),
    )
    parent = models.ForeignKey(
        "self",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="children",
        verbose_name=_("parent"),
        help_text=_("The level this one inherits from."),
    )
    parent_lookup = models.CharField(
        _("parent lookup"),
        max_length=255,
        blank=True,
        default="",
        help_text=_(
            "The ORM path from this level's model to the parent level's instance, such "
            'as "organization" or "team__organization". Every hop has to be a foreign key '
            "or a one-to-one, because the resolver follows it in SQL. Leave it empty when "
            "the parent is the global level."
        ),
    )

    class Meta:
        verbose_name = _("settings level")
        verbose_name_plural = _("settings levels")
        ordering = ["key"]
        constraints = [
            models.UniqueConstraint(
                Coalesce("content_type", Value(0), output_field=models.IntegerField()),
                name="unique_settings_level_per_content_type",
            )
        ]

    def __str__(self) -> str:
        return self.name or self.key

    # -- what this level is ------------------------------------------------
    @property
    def is_global(self) -> bool:
        """Whether this is the level that is not attached to any object."""
        return self.content_type_id is None

    @property
    def model(self) -> type[Model] | None:
        """The model this level attaches to, or ``None`` for the global one."""
        content_type = self.content_type
        if content_type is None:
            return None
        return content_type.model_class()

    def ancestors(self) -> Iterator[SettingsLevel]:
        """This level, then every level above it, closest first."""
        current: SettingsLevel | None = self
        seen: set[int] = set()
        while current is not None:
            if current.pk in seen or len(seen) >= MAX_CHAIN_DEPTH:
                raise ValidationError(
                    _('The levels above "%(key)s" loop back on themselves.') % {"key": self.key}
                )
            seen.add(current.pk)
            yield current
            current = current.parent

    # -- integrity ---------------------------------------------------------
    def clean(self) -> None:
        super().clean()
        errors: dict[str, list[str]] = {}
        self._check_global(errors)
        self._check_parent(errors)
        if errors:
            raise ValidationError(errors)

    def _check_global(self, errors: dict[str, list[str]]) -> None:
        if not self.is_global:
            return
        if self.parent_id is not None:
            errors["parent"] = [str(_("The global level has nothing above it."))]
        if self.parent_lookup:
            errors["parent_lookup"] = [
                str(_("The global level is not attached to an object, so it has no path."))
            ]

    def _check_parent(self, errors: dict[str, list[str]]) -> None:
        if self.parent_id is None:
            if self.parent_lookup:
                errors["parent_lookup"] = [
                    str(_("There is no parent level for this path to lead to."))
                ]
            return
        parent = self.parent
        if parent is None:  # pragma: no cover -- the id is set, so the object is there
            return
        if parent.pk == self.pk or any(ancestor.pk == self.pk for ancestor in parent.ancestors()):
            errors["parent"] = [str(_("A level cannot inherit from itself."))]
            return
        if parent.is_global:
            if self.parent_lookup:
                errors["parent_lookup"] = [
                    str(_("The global level is not attached to an object, so leave this empty."))
                ]
            return
        if not self.parent_lookup:
            errors["parent_lookup"] = [
                str(
                    _('Say how to get from %(model)s to the "%(parent)s" level, as an ORM path.')
                    % {"model": self._label(), "parent": parent.key}
                )
            ]
            return
        self._check_parent_lookup_resolves(parent, errors)

    def _check_parent_lookup_resolves(
        self, parent: SettingsLevel, errors: dict[str, list[str]]
    ) -> None:
        model, parent_model = self.model, parent.model
        if model is None or parent_model is None:
            return
        try:
            target = follow_lookup(model, self.parent_lookup)
        except ValidationError as exc:
            errors["parent_lookup"] = list(exc.messages)
            return
        if target is not parent_model and not issubclass(target, parent_model):
            errors["parent_lookup"] = [
                str(
                    _(
                        '"%(path)s" leads to %(target)s, but the "%(parent)s" level '
                        "is %(expected)s."
                    )
                    % {
                        "path": self.parent_lookup,
                        "target": target._meta.label,
                        "parent": parent.key,
                        "expected": parent_model._meta.label,
                    }
                )
            ]

    def _label(self) -> str:
        model = self.model
        return model._meta.label if model is not None else self.key


__all__ = ["MAX_CHAIN_DEPTH", "SettingsLevel"]
