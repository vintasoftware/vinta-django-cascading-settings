"""Where one level's values live, and which of them it will not let go of.

A level's values for one schema are a questionnaire response: the answers are
the values, keyed by question.  ``ScopedSettings`` is what ties that response
to the object holding it, and it is what the resolver joins against -- one row
per (schema, object), found by content type and primary key.

Only the keys an object actually set have an answer, which is what makes the
cascade unambiguous: no answer means "ask the level above", and an answer of
``null`` means "nothing, and stop asking".

A row also carries the tenant it belongs to, copied from its response.  The
global level is the exception and the point: its values are the installation's
defaults, so they are held in the global scope and every tenant reads them.
Everything below it belongs to one tenant and is read by that tenant alone.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ValidationError
from django.db import models, transaction
from django.utils.translation import gettext_lazy as _
from vinta_django_questionnaires.models import BaseModel, QuestionnaireResponse

from vinta_django_cascading_settings.exceptions import LevelNotAllowed, LevelNotConfigured
from vinta_django_cascading_settings.lookups import OBJECT_ID_MAX_LENGTH, db_object_id
from vinta_django_cascading_settings.models.levels import SettingsLevel
from vinta_django_cascading_settings.models.schemas import SettingsSchema
from vinta_django_cascading_settings.tenancy import (
    GLOBAL_SCOPE_KEY,
    scope_instance_for,
    scope_key_for,
)

if TYPE_CHECKING:
    from django.db.models import Model


class ScopedSettings(BaseModel):
    """The values one object holds for one schema."""

    schema = models.ForeignKey(
        SettingsSchema,
        on_delete=models.CASCADE,
        related_name="scoped_settings",
        verbose_name=_("schema"),
    )
    level = models.ForeignKey(
        SettingsLevel,
        on_delete=models.PROTECT,
        related_name="scoped_settings",
        verbose_name=_("level"),
    )
    content_type = models.ForeignKey(
        ContentType,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="+",
        verbose_name=_("content type"),
    )
    object_id = models.CharField(
        _("object id"),
        max_length=OBJECT_ID_MAX_LENGTH,
        blank=True,
        default="",
        help_text=_("The holder's primary key as the database writes it. Empty when global."),
    )
    target = GenericForeignKey("content_type", "object_id")
    scope_key = models.CharField(
        _("scope key"),
        max_length=255,
        blank=True,
        default="",
        db_index=True,
        help_text=_(
            "The tenant these values belong to, copied from the response. "
            "Empty at the global level, whose values are the installation's."
        ),
    )
    response = models.OneToOneField(
        QuestionnaireResponse,
        on_delete=models.CASCADE,
        related_name="scoped_settings",
        verbose_name=_("response"),
        help_text=_("The response whose answers are these values."),
    )

    class Meta:
        verbose_name = _("scoped settings")
        verbose_name_plural = _("scoped settings")
        ordering = ["schema", "level", "object_id"]
        constraints = [
            # One row per object per schema, whichever tenant holds it: an
            # object belongs to one tenant, so a second row for it would be two
            # answers to the same question with nothing to choose between them.
            models.UniqueConstraint(
                fields=["schema", "content_type", "object_id"],
                condition=models.Q(content_type__isnull=False),
                name="unique_scoped_settings_per_object_and_schema",
            ),
            # And one global row per schema, because the global level is the
            # installation's: its defaults are not a tenant's to have twice.
            models.UniqueConstraint(
                fields=["schema"],
                condition=models.Q(content_type__isnull=True),
                name="unique_global_settings_per_schema",
            ),
        ]
        indexes = [
            models.Index(fields=["content_type", "object_id"], name="cascading_settings_holder"),
        ]

    def __str__(self) -> str:
        holder = self.object_id or _("global")
        return f"{self.schema_id and self.schema.key}: {self.level_id and self.level.key} {holder}"

    def save(self, *args: Any, validate: bool = True, **kwargs: Any) -> None:
        # The tenant is the response's, and is written once: a scope that could
        # move would take every value under it somewhere it was never set.
        if self.response_id and not self.scope_key:
            self.scope_key = self.response.scope_key
        super().save(*args, validate=validate, **kwargs)

    # -- finding and making them -------------------------------------------
    @classmethod
    def for_instance(
        cls,
        instance: Model,
        schema: SettingsSchema,
        *,
        scope: Any = None,
        create: bool = True,
    ) -> ScopedSettings | None:
        """The row holding *instance*'s values for *schema*, made if it has none.

        *scope* says which tenant the values belong to.  Left out, they belong
        to whoever owns the questionnaire, which is what a schema a tenant has
        to itself already means; an installation sharing one questionnaire
        between tenants passes the tenant, its scope, or its key.
        """
        settings_level = level_for_model(type(instance))
        return cls._get_or_create(
            schema,
            settings_level,
            content_type=settings_level.content_type,
            object_id=db_object_id(instance),
            scope=scope,
            create=create,
        )

    @classmethod
    def for_global(cls, schema: SettingsSchema, *, create: bool = True) -> ScopedSettings | None:
        """The row holding the defaults every tenant falls back to.

        There is no scope to pass. The global level is the installation's, and
        a tenant that wants its own answer sets it at a level it owns.
        """
        try:
            settings_level = SettingsLevel.objects.get(content_type__isnull=True)
        except SettingsLevel.DoesNotExist as exc:
            raise LevelNotAllowed(schema.key, "global") from exc
        return cls._get_or_create(
            schema,
            settings_level,
            content_type=None,
            object_id="",
            scope=GLOBAL_SCOPE_KEY,
            create=create,
        )

    @classmethod
    def _get_or_create(
        cls,
        schema: SettingsSchema,
        settings_level: SettingsLevel,
        *,
        content_type: ContentType | None,
        object_id: str,
        scope: Any = None,
        create: bool,
    ) -> ScopedSettings | None:
        existing = cls.objects.filter(
            schema=schema, content_type=content_type, object_id=object_id
        ).first()
        scope_key = scope_key_for(scope)
        if existing is not None:
            if scope_key is not None and existing.scope_key != scope_key:
                raise LevelNotAllowed(schema.key, settings_level.key)
            return existing
        if not create:
            return None
        if not schema.allows(settings_level):
            raise LevelNotAllowed(schema.key, settings_level.key)
        with transaction.atomic():
            tenant = scope_instance_for(scope)
            response = QuestionnaireResponse(questionnaire_version=schema.version)
            if tenant is not None:
                response.scope = tenant
            response.save()
            return cls.objects.create(
                schema=schema,
                level=settings_level,
                content_type=content_type,
                object_id=object_id,
                response=response,
            )

    # -- integrity ---------------------------------------------------------
    def clean(self) -> None:
        super().clean()
        if not self.level_id:
            return
        errors: dict[str, list[str]] = {}
        level = self.level
        if level.is_global:
            if self.content_type_id is not None:
                errors["content_type"] = [str(_("The global level holds no object."))]
            if self.object_id:
                errors["object_id"] = [str(_("The global level holds no object."))]
        else:
            if self.content_type_id != level.content_type_id:
                errors["content_type"] = [
                    str(_('The "%(level)s" level is not about this model.') % {"level": level.key})
                ]
            if not self.object_id:
                errors["object_id"] = [str(_("Say which object holds these values."))]
        if self.schema_id and not self.schema.allows(level):
            errors["level"] = [
                str(
                    _('The "%(schema)s" settings are not held at the "%(level)s" level.')
                    % {"schema": self.schema.key, "level": level.key}
                )
            ]
        if self.schema_id and self.response_id:
            version = self.response.questionnaire_version
            if version.questionnaire_id != self.schema.questionnaire_id:
                errors["response"] = [str(_("This response answers another questionnaire."))]
        if level.is_global and self.response_id and self.response.scope_key != GLOBAL_SCOPE_KEY:
            errors["response"] = [
                str(
                    _(
                        "The global level holds the installation's defaults, so its values "
                        "cannot belong to one tenant. Set this at a level the tenant owns."
                    )
                )
            ]
        if errors:
            raise ValidationError(errors)


class SettingLock(BaseModel):
    """A value the levels below are not allowed to override.

    Locks are rows rather than a list on the settings, because the resolver
    reads them in the same query it reads the values, and a JSON containment
    lookup is not something every backend this package supports can do.
    """

    scoped_settings = models.ForeignKey(
        ScopedSettings,
        on_delete=models.CASCADE,
        related_name="locks",
        verbose_name=_("scoped settings"),
    )
    key = models.SlugField(_("key"), max_length=100)
    reason = models.CharField(_("reason"), max_length=255, blank=True, default="")

    class Meta:
        verbose_name = _("setting lock")
        verbose_name_plural = _("setting locks")
        ordering = ["scoped_settings", "key"]
        constraints = [
            models.UniqueConstraint(
                fields=["scoped_settings", "key"], name="unique_setting_lock_per_key"
            )
        ]

    def __str__(self) -> str:
        return self.key


def level_for_model(model: type[Model]) -> SettingsLevel:
    """The level *model* is, raising if it is not one."""
    content_type = ContentType.objects.get_for_model(model, for_concrete_model=True)
    try:
        return SettingsLevel.objects.get(content_type=content_type)
    except SettingsLevel.DoesNotExist as exc:
        raise LevelNotConfigured(model) from exc


__all__ = ["ScopedSettings", "SettingLock", "level_for_model"]
