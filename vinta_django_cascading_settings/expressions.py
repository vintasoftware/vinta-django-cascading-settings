"""Settings resolution, expressed as SQL.

Nothing in this package merges values in Python.  A resolved setting is one
correlated subquery over the answers, restricted to the settings held anywhere
along the object's chain of levels, ordered so that the row that wins is the
first one, and cut off at one row:

* a value set closer to the object beats one set further away, and
* a locked value beats every value below the level that locked it, with the
  outermost lock winning when more than one level locked the same key.

Because it is an expression, it goes wherever an expression goes -- annotate,
filter, order, aggregate, subquery -- and reading one object's setting is the
same query with the object's own primary key in front of it.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from django.db.models import (
    Case,
    CharField,
    Exists,
    Expression,
    F,
    IntegerField,
    JSONField,
    OuterRef,
    Q,
    Subquery,
    Value,
    When,
)
from django.db.models.functions import Cast, JSONObject
from vinta_django_questionnaires.models import Answer, PageResponseStatus

from vinta_django_cascading_settings.casting import JSONScalar, output_field_for
from vinta_django_cascading_settings.chain import ChainLink, build_chain
from vinta_django_cascading_settings.lookups import OBJECT_ID_MAX_LENGTH
from vinta_django_cascading_settings.models import SettingLock
from vinta_django_cascading_settings.tenancy import scope_key_for

if TYPE_CHECKING:
    from django.db.models import Model, QuerySet

#: What annotated settings are called unless the caller says otherwise.
SETTINGS_PREFIX = "setting_"

#: Where the answers hang off the row that says whose settings they are.
HOLDER = "response__scoped_settings"


def setting_alias(key: str, prefix: str = SETTINGS_PREFIX) -> str:
    """The annotation name a setting key is given.

    Setting keys are slugs and may contain hyphens, which no annotation name
    can, so those become underscores.
    """
    return f"{prefix}{key.replace('-', '_')}"


def _held_by(link: ChainLink, scope_key: str | None = None) -> Q:
    """What marks a stored settings row as this level's, for *this* object.

    Only this carries a reference to the row being resolved, and it is only
    ever used in the ``WHERE`` clause: SQLite will not resolve an outer column
    anywhere else in a subquery, the ``ORDER BY`` included.

    The tenant is checked here too, and the global level is where it is not:
    its values are the installation's defaults, so every tenant reads them,
    while everything below it is read by the tenant that set it and no other.
    """
    if link.is_global:
        return Q(**{f"{HOLDER}__content_type__isnull": True, f"{HOLDER}__level": link.level.pk})
    held: dict[str, Any] = {
        f"{HOLDER}__content_type": link.level.content_type_id,
        f"{HOLDER}__object_id": Cast(
            OuterRef(link.pk_path),
            output_field=CharField(max_length=OBJECT_ID_MAX_LENGTH),
        ),
    }
    if scope_key is not None:
        held[f"{HOLDER}__scope_key"] = scope_key
    return Q(**held)


def _at_level(link: ChainLink) -> Q:
    """What marks a row as this level's, without looking at the outer row.

    A level appears once in a chain, so its own column is enough to say how
    far from the object a value was set -- which is what keeps the ordering
    free of the outer references SQLite will not have there.
    """
    return Q(**{f"{HOLDER}__level": link.level.pk})


def candidates(
    model: type[Model],
    key: str,
    *,
    schema: str | None = None,
    scope_key: str | None = None,
) -> QuerySet[Answer]:
    """Every value of *key* anywhere on *model*'s chain, best first.

    The ordering is the whole of the cascade.  Locked values come first, and
    among them the one furthest from the object wins, because a lock is set by
    an ancestor to stop the levels beneath it from having their way.  Among
    unlocked values the nearest wins, which is the ordinary case.
    """
    matches = Q()
    depths: list[When] = []
    for link in build_chain(model):
        matches |= _held_by(link, scope_key)
        depths.append(When(_at_level(link), then=Value(link.depth)))

    queryset = (
        Answer.objects.filter(matches)
        .filter(
            question__key=key,
            page_response__status=PageResponseStatus.COMPLETED,
            **{f"{HOLDER}__isnull": False},
        )
        .annotate(
            settings_depth=Case(*depths, output_field=IntegerField()),
            settings_locked=Exists(
                SettingLock.objects.filter(
                    scoped_settings__response=OuterRef("response"),
                    key=OuterRef("question__key"),
                )
            ),
        )
    )
    if schema is None:
        queryset = queryset.filter(**{f"{HOLDER}__schema__is_active": True})
    else:
        queryset = queryset.filter(**{f"{HOLDER}__schema__key": schema})
    return queryset.order_by(
        F("settings_locked").desc(),
        Case(
            When(settings_locked=True, then=F("settings_depth") * Value(-1)),
            default=F("settings_depth"),
            output_field=IntegerField(),
        ).asc(),
        # Two schemas may ask the same key at the same level; pick the same one
        # every time rather than whatever the database happens to hand back.
        f"{HOLDER}__schema__key",
        "pk",
    )


class SettingExpression(Expression):
    """An expression that only knows what to build once it sees the query.

    The chain depends on the model being queried, and that is not known until
    the expression is resolved, so building the subquery waits until then.
    """

    def __init__(
        self,
        key: str,
        *,
        schema: str | None = None,
        scope: Any = None,
        output_field: Any = None,
    ) -> None:
        self.key = key
        self.schema = schema
        self.scope_key = scope_key_for(scope)
        self.declared_output_field = output_field
        super().__init__(output_field=output_field or JSONField())

    def resolved_output_field(self) -> Any:
        """What the value is read as: what the caller asked for, or the type
        the question says it is, or JSON when it is not a scalar."""
        if self.declared_output_field is not None:
            return self.declared_output_field
        return output_field_for(self.key, schema=self.schema) or JSONField()

    def build(self, model: type[Model]) -> Subquery:
        raise NotImplementedError

    def resolve_expression(
        self,
        query: Any = None,
        allow_joins: bool = True,
        reuse: Any = None,
        summarize: bool = False,
        for_save: bool = False,
    ) -> Any:
        if query is None or getattr(query, "model", None) is None:
            raise TypeError(
                f"{type(self).__name__} has to be used against a queryset, so that it knows "
                "which chain of levels to resolve through."
            )
        subquery = self.build(query.model)
        return subquery.resolve_expression(query, allow_joins, reuse, summarize, for_save)

    def __repr__(self) -> str:
        schema = f", schema={self.schema!r}" if self.schema else ""
        scope = f", scope={self.scope_key!r}" if self.scope_key is not None else ""
        return f"{type(self).__name__}({self.key!r}{schema}{scope})"


class SettingValue(SettingExpression):
    """The value of one setting, resolved through the whole chain.

    It comes back as the type the question says it is -- a number as a number,
    a date as a date -- because the subquery reads the scalar out of the JSON
    and casts it before handing it over.  So ``__gt`` means what it says, an
    ordering is not lexicographic, and ``Sum`` works.  A value that is not a
    scalar, such as a multiple choice, stays JSON, and so does one whose
    question type the schemas disagree about.  Pass ``output_field`` to
    override all of that.
    """

    def build(self, model: type[Model]) -> Subquery:
        field = self.resolved_output_field()
        rows = candidates(model, self.key, schema=self.schema, scope_key=self.scope_key)
        selected: QuerySet[Any]
        if isinstance(field, JSONField):
            selected = rows.values("value")[:1]
        else:
            selected = rows.values(settings_value=Cast(JSONScalar("value"), output_field=field))[
                :1
            ]
        return Subquery(selected, output_field=field)


class SettingSource(SettingExpression):
    """Where the value came from: the level, the object, and how it won.

    Null when nothing on the chain has an opinion, which is what tells a value
    that was deliberately set to null apart from one nobody ever set.
    """

    def build(self, model: type[Model]) -> Subquery:
        rows = candidates(model, self.key, schema=self.schema, scope_key=self.scope_key).values(
            source=JSONObject(
                level=F(f"{HOLDER}__level__key"),
                schema=F(f"{HOLDER}__schema__key"),
                contentType=F(f"{HOLDER}__content_type"),
                objectId=F(f"{HOLDER}__object_id"),
                depth=F("settings_depth"),
                locked=F("settings_locked"),
                scopeKey=F(f"{HOLDER}__scope_key"),
            )
        )[:1]
        return Subquery(rows, output_field=self.output_field)


def annotate_settings(
    queryset: QuerySet[Any],
    *keys: str,
    schema: str | None = None,
    scope: Any = None,
    prefix: str = SETTINGS_PREFIX,
    sources: bool = False,
) -> QuerySet[Any]:
    """Annotate *queryset* with each of *keys*, resolved through the chain.

    Each key becomes ``setting_<key>``, and with ``sources=True`` each also
    gets a ``setting_<key>_source`` saying which level it came from.  Pass
    *scope* in a multi-tenant installation: everything below the global level
    is then read from that tenant and no other, while the global level's
    defaults are read by every tenant.
    """
    annotations: dict[str, SettingExpression] = {}
    for key in keys:
        alias = setting_alias(key, prefix)
        annotations[alias] = SettingValue(key, schema=schema, scope=scope)
        if sources:
            annotations[f"{alias}_source"] = SettingSource(key, schema=schema, scope=scope)
    annotated: QuerySet[Any] = queryset.annotate(**annotations)
    return annotated


class CascadingSettingsQuerySetMixin:
    """Adds ``with_settings()`` to a queryset of a model that is a level."""

    def with_settings(
        self,
        *keys: str,
        schema: str | None = None,
        scope: Any = None,
        prefix: str = SETTINGS_PREFIX,
        sources: bool = False,
    ) -> QuerySet[Any]:
        queryset: QuerySet[Any] = self  # type: ignore[assignment]
        return annotate_settings(
            queryset, *keys, schema=schema, scope=scope, prefix=prefix, sources=sources
        )


__all__ = [
    "SETTINGS_PREFIX",
    "CascadingSettingsQuerySetMixin",
    "SettingExpression",
    "SettingSource",
    "SettingValue",
    "annotate_settings",
    "candidates",
    "setting_alias",
]
