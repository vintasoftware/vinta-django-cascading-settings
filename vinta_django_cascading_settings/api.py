"""What a project calls: a model instance and a key in, a value out.

Reading is a thin wrapper over the expressions in ``expressions``: the query
resolves the whole chain, and these functions only put one object's primary
key in front of it and hand back the column.  Writing is ordinary Django, one
answer per setting the caller names -- and only the ones it names, so a level
overriding one setting does not quietly take ownership of the rest.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from django.db import transaction
from django.utils import timezone
from django.utils.translation import gettext_lazy as _
from vinta_django_questionnaires.models import Answer, PageResponse, PageResponseStatus

from vinta_django_cascading_settings.exceptions import (
    AmbiguousSetting,
    SettingLocked,
    SettingsConfigurationError,
    SettingsValidationError,
    UnknownSetting,
)
from vinta_django_cascading_settings.expressions import annotate_settings, setting_alias
from vinta_django_cascading_settings.models import ScopedSettings, SettingLock, SettingsSchema
from vinta_django_cascading_settings.tenancy import GLOBAL_SCOPE_KEY

if TYPE_CHECKING:
    from django.db.models import Model
    from vinta_django_questionnaires.models import Question, QuestionnaireVersion
    from vinta_django_questionnaires.validators.base import ValidationIssue

#: What a caller passes when it means the level that has no object.
GLOBAL = None


@dataclass(frozen=True)
class ResolvedSetting:
    """One setting, and the account of where its value came from."""

    key: str
    value: Any = None
    is_set: bool = False
    level: str | None = None
    schema: str | None = None
    depth: int | None = None
    object_id: str = ""
    scope_key: str = ""
    is_locked: bool = False

    @property
    def is_inherited(self) -> bool:
        """Whether the value came from a level above the object's own."""
        return self.is_set and bool(self.depth)

    @property
    def is_own(self) -> bool:
        """Whether the object itself set this."""
        return self.is_set and self.depth == 0


# ---------------------------------------------------------------- schemas
def resolve_schema(
    schema: str | SettingsSchema | None = None, *, keys: list[str] | None = None
) -> SettingsSchema:
    """The schema *keys* belong to, or the one named by *schema*."""
    if isinstance(schema, SettingsSchema):
        return schema
    if schema is not None:
        try:
            return SettingsSchema.objects.get(key=schema)
        except SettingsSchema.DoesNotExist as exc:
            raise SettingsConfigurationError(
                _('There is no settings schema called "%(key)s".') % {"key": schema}
            ) from exc
    wanted = list(keys or [])
    if not wanted:
        raise SettingsConfigurationError(_("Say which settings schema this is about."))
    matches = list(
        SettingsSchema.objects.filter(
            is_active=True,
            questionnaire__versions__pages__sections__questions__key__in=wanted,
        ).distinct()
    )
    if not matches:
        raise UnknownSetting(wanted[0])
    if len(matches) > 1:
        raise AmbiguousSetting(wanted[0], sorted(match.key for match in matches))
    return matches[0]


def schema_keys(schema: str | SettingsSchema | None = None) -> list[str]:
    """Every setting key *schema* defines, or every one in use."""
    schemas = (
        [resolve_schema(schema)]
        if schema is not None
        else list(SettingsSchema.objects.filter(is_active=True))
    )
    keys: list[str] = []
    for entry in schemas:
        for key in entry.question_keys():
            if key not in keys:
                keys.append(key)
    return keys


# ---------------------------------------------------------------- reading
def explain_settings(
    holder: Model | None,
    *keys: str,
    schema: str | None = None,
    scope: Any = None,
) -> dict[str, ResolvedSetting]:
    """Resolve *keys* for *holder*, with where each value came from.

    Pass no keys to resolve everything the schema defines, and ``None`` as the
    holder to read the global level on its own.  *scope* is the tenant to read
    from: everything below the global level is read from it and no other, while
    the global level's defaults are read by every tenant.
    """
    wanted = list(keys) or schema_keys(schema)
    if not wanted:
        return {}
    if holder is None:
        return _global_settings(wanted, schema)

    model = type(holder)
    queryset = annotate_settings(
        model._base_manager.filter(pk=holder.pk),
        *wanted,
        schema=schema,
        scope=scope,
        sources=True,
    )
    columns: list[str] = []
    for key in wanted:
        alias = setting_alias(key)
        columns += [alias, f"{alias}_source"]
    row = queryset.values(*columns).first()
    if row is None:
        return {key: ResolvedSetting(key=key) for key in wanted}
    return {key: _resolved(key, row) for key in wanted}


def explain_setting(
    holder: Model | None, key: str, *, schema: str | None = None, scope: Any = None
) -> ResolvedSetting:
    """Resolve one key for *holder*, with where its value came from."""
    return explain_settings(holder, key, schema=schema, scope=scope)[key]


def get_settings(
    holder: Model | None, *keys: str, schema: str | None = None, scope: Any = None
) -> dict[str, Any]:
    """Resolve *keys* for *holder* as plain values, unset ones left out."""
    resolved = explain_settings(holder, *keys, schema=schema, scope=scope)
    return {key: entry.value for key, entry in resolved.items() if entry.is_set}


def get_setting(
    holder: Model | None,
    key: str,
    *,
    schema: str | None = None,
    scope: Any = None,
    default: Any = None,
) -> Any:
    """The value of *key* for *holder*, or *default* if no level set it.

    A level that set it to ``null`` has set it: the answer is ``None`` rather
    than the default, and the levels above are not consulted.
    """
    resolved = explain_setting(holder, key, schema=schema, scope=scope)
    return resolved.value if resolved.is_set else default


def _resolved(key: str, row: dict[str, Any]) -> ResolvedSetting:
    alias = setting_alias(key)
    source = row.get(f"{alias}_source")
    if not source:
        return ResolvedSetting(key=key)
    return ResolvedSetting(
        key=key,
        value=row.get(alias),
        is_set=True,
        level=source.get("level"),
        schema=source.get("schema"),
        depth=source.get("depth"),
        object_id=source.get("objectId") or "",
        scope_key=source.get("scopeKey") or "",
        is_locked=bool(source.get("locked")),
    )


def _global_settings(keys: list[str], schema: str | None) -> dict[str, ResolvedSetting]:
    """The global level read on its own, which needs no chain to walk."""
    answers = Answer.objects.filter(
        question__key__in=keys,
        page_response__status=PageResponseStatus.COMPLETED,
        response__scoped_settings__content_type__isnull=True,
        response__scoped_settings__isnull=False,
        # The global level is the installation's, so its values are held in the
        # global scope. A tenant with its own answer sets it at a level it owns.
        response__scoped_settings__scope_key=GLOBAL_SCOPE_KEY,
    )
    answers = (
        answers.filter(response__scoped_settings__schema__key=schema)
        if schema is not None
        else answers.filter(response__scoped_settings__schema__is_active=True)
    )
    rows = answers.values(
        "question__key",
        "value",
        "response__scoped_settings__level__key",
        "response__scoped_settings__schema__key",
    ).order_by("response__scoped_settings__schema__key", "pk")
    locked = set(
        SettingLock.objects.filter(
            scoped_settings__content_type__isnull=True, key__in=keys
        ).values_list("key", flat=True)
    )
    found = {
        row["question__key"]: ResolvedSetting(
            key=row["question__key"],
            value=row["value"],
            is_set=True,
            level=row["response__scoped_settings__level__key"],
            schema=row["response__scoped_settings__schema__key"],
            depth=0,
            is_locked=row["question__key"] in locked,
        )
        for row in rows
    }
    return {key: found.get(key, ResolvedSetting(key=key)) for key in keys}


# ---------------------------------------------------------------- writing
def validate_settings(
    values: dict[str, Any], *, schema: str | SettingsSchema | None = None
) -> dict[str, Any]:
    """Run each value through its question's validator chain, without saving.

    Returns the values as the chain coerced them, and raises
    ``SettingsValidationError`` with one entry per key that did not hold up.
    """
    settings_schema = resolve_schema(schema, keys=list(values))
    return _clean(_questions(settings_schema.version, list(values)), values)


@transaction.atomic
def set_settings(
    holder: Model | None,
    values: dict[str, Any],
    *,
    schema: str | SettingsSchema | None = None,
    scope: Any = None,
    locked: bool | None = None,
    validate: bool = True,
    force: bool = False,
) -> ScopedSettings:
    """Record *values* at *holder*'s own level, and nothing else.

    Only the keys named are written, so overriding one setting leaves every
    other one inherited.  ``locked=True`` also stops the levels below from
    overriding what was written; ``locked=False`` lets them again.

    A key a level above has locked is refused, because writing it would be
    recorded and then never read.  Pass ``force=True`` to write it anyway.
    """
    settings_schema = resolve_schema(schema, keys=list(values))
    if not force:
        check_not_locked(holder, list(values), schema=settings_schema, scope=scope)
    scoped = _scoped_settings(holder, settings_schema, scope=scope)
    questions = _questions(scoped.response.questionnaire_version, list(values))
    cleaned = _clean(questions, values) if validate else dict(values)

    now = timezone.now()
    for key, question in questions.items():
        page_response, _created = PageResponse.objects.update_or_create(
            response=scoped.response,
            page=question.section.page,
            defaults={
                "status": PageResponseStatus.COMPLETED,
                "skip_reason": "",
                "submitted_at": now,
            },
        )
        Answer.objects.update_or_create(
            response=scoped.response,
            question=question,
            defaults={"page_response": page_response, "value": cleaned[key]},
        )
        if locked is True:
            SettingLock.objects.get_or_create(scoped_settings=scoped, key=key)
        elif locked is False:
            SettingLock.objects.filter(scoped_settings=scoped, key=key).delete()
    return scoped


def set_setting(
    holder: Model | None,
    key: str,
    value: Any,
    *,
    schema: str | SettingsSchema | None = None,
    scope: Any = None,
    locked: bool | None = None,
    validate: bool = True,
    force: bool = False,
) -> ScopedSettings:
    """Record one setting at *holder*'s own level."""
    return set_settings(
        holder,
        {key: value},
        schema=schema,
        scope=scope,
        locked=locked,
        validate=validate,
        force=force,
    )


def check_not_locked(
    holder: Model | None,
    keys: list[str],
    *,
    schema: str | SettingsSchema | None = None,
    scope: Any = None,
) -> None:
    """Raise if a level above *holder* has locked any of *keys*."""
    if holder is None:
        return
    settings_schema = resolve_schema(schema, keys=keys)
    resolved_keys = explain_settings(holder, *keys, schema=settings_schema.key, scope=scope)
    for key, resolved in resolved_keys.items():
        if resolved.is_locked and not resolved.is_own:
            raise SettingLocked(key, resolved.level)


@transaction.atomic
def unset_settings(
    holder: Model | None,
    *keys: str,
    schema: str | SettingsSchema | None = None,
    scope: Any = None,
) -> int:
    """Drop *keys* from *holder*'s own level, so they are inherited again."""
    settings_schema = resolve_schema(schema, keys=list(keys))
    scoped = _find_scoped_settings(holder, settings_schema, scope=scope)
    if scoped is None:
        return 0
    SettingLock.objects.filter(scoped_settings=scoped, key__in=keys).delete()
    deleted, _details = Answer.objects.filter(
        response=scoped.response, question__key__in=keys
    ).delete()
    return deleted


def unset_setting(
    holder: Model | None,
    key: str,
    *,
    schema: str | SettingsSchema | None = None,
    scope: Any = None,
) -> bool:
    """Drop one setting from *holder*'s own level."""
    return bool(unset_settings(holder, key, schema=schema, scope=scope))


def lock_setting(
    holder: Model | None,
    key: str,
    *,
    schema: str | SettingsSchema | None = None,
    scope: Any = None,
    reason: str = "",
) -> SettingLock:
    """Stop the levels below *holder* from overriding *key*.

    A lock bites where there is a value to lock: locking a key this level only
    inherits records the intent but changes nothing until it sets one.
    """
    settings_schema = resolve_schema(schema, keys=[key])
    scoped = _scoped_settings(holder, settings_schema, scope=scope)
    lock, _created = SettingLock.objects.get_or_create(
        scoped_settings=scoped, key=key, defaults={"reason": reason}
    )
    if reason and lock.reason != reason:
        lock.reason = reason
        lock.save()
    return lock


def unlock_setting(
    holder: Model | None,
    key: str,
    *,
    schema: str | SettingsSchema | None = None,
    scope: Any = None,
) -> bool:
    """Let the levels below *holder* override *key* again."""
    settings_schema = resolve_schema(schema, keys=[key])
    scoped = _find_scoped_settings(holder, settings_schema, scope=scope)
    if scoped is None:
        return False
    deleted, _details = SettingLock.objects.filter(scoped_settings=scoped, key=key).delete()
    return bool(deleted)


# ---------------------------------------------------------------- internals
def _find_scoped_settings(
    holder: Model | None, schema: SettingsSchema, *, scope: Any = None
) -> ScopedSettings | None:
    """The row holding *holder*'s own values, if it has any."""
    if holder is None:
        return ScopedSettings.for_global(schema, create=False)
    return ScopedSettings.for_instance(holder, schema, scope=scope, create=False)


def _scoped_settings(
    holder: Model | None, schema: SettingsSchema, *, scope: Any = None
) -> ScopedSettings:
    """The row holding *holder*'s own values, made if it has none yet."""
    scoped = (
        ScopedSettings.for_global(schema)
        if holder is None
        else ScopedSettings.for_instance(holder, schema, scope=scope)
    )
    if scoped is None:  # pragma: no cover -- it is created when it is missing
        raise SettingsConfigurationError(_("These settings could not be stored."))
    return scoped


def _questions(version: QuestionnaireVersion, keys: list[str]) -> dict[str, Question]:
    questions = {question.key: question for question in version.iter_questions()}
    for key in keys:
        if key not in questions:
            raise UnknownSetting(key)
    return {key: questions[key] for key in keys}


def _clean(questions: dict[str, Question], values: dict[str, Any]) -> dict[str, Any]:
    """Run each question's validator chain, and keep what it coerced."""
    issues: dict[str, list[ValidationIssue]] = {}
    cleaned: dict[str, Any] = {}
    for key, question in questions.items():
        context = question.run_validators(values[key], answers=dict(values))
        if context.issues:
            issues[key] = context.issues
        cleaned[key] = context.outcomes[-1].value if context.outcomes else values[key]
    if issues:
        raise SettingsValidationError(issues)
    return cleaned


__all__ = [
    "GLOBAL",
    "ResolvedSetting",
    "check_not_locked",
    "explain_setting",
    "explain_settings",
    "get_setting",
    "get_settings",
    "lock_setting",
    "resolve_schema",
    "schema_keys",
    "set_setting",
    "set_settings",
    "unlock_setting",
    "unset_setting",
    "unset_settings",
    "validate_settings",
]
