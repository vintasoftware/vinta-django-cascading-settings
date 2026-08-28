"""Turning a level's parent lookup into something the database can join on.

The chain a setting resolves through is walked in SQL, so the path from one
level to the level above it has to be an ORM path -- a run of single-valued
relations the query compiler can turn into joins -- rather than an attribute
that only Python knows how to follow.  Checking that is what this module is
for, along with the other thing both sides of the join have to agree on: how
an object's primary key is spelled in the ``object_id`` column.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from django.core.exceptions import FieldDoesNotExist, ValidationError
from django.db import connection
from django.utils.translation import gettext_lazy as _

if TYPE_CHECKING:
    from django.db.models import Model

#: Long enough for a hyphenated UUID, short enough to index everywhere.
OBJECT_ID_MAX_LENGTH = 191

#: What separates the hops of an ORM path, as everywhere else in Django.
LOOKUP_SEP = "__"


def follow_lookup(model: type[Model], path: str) -> type[Model]:
    """The model *path* lands on, starting from *model*.

    Every hop has to be a forward foreign key, a one-to-one, or the reverse of
    one: those are the relations that yield exactly one row, and a lookup that
    can yield several has no single parent to inherit from.
    """
    current = model
    for part in path.split(LOOKUP_SEP):
        try:
            field = current._meta.get_field(part)
        except FieldDoesNotExist as exc:
            raise ValidationError(
                _('"%(part)s" is not a field of %(model)s.')
                % {"part": part, "model": current._meta.label}
            ) from exc
        if not (field.many_to_one or field.one_to_one):
            raise ValidationError(
                _(
                    '"%(part)s" on %(model)s is not a single-valued relation, so it cannot '
                    "name one parent to inherit from."
                )
                % {"part": part, "model": current._meta.label}
            )
        related_model = field.related_model
        if related_model is None:  # pragma: no cover -- a relation always has one
            raise ValidationError(
                _('"%(part)s" on %(model)s does not point at a model.')
                % {"part": part, "model": current._meta.label}
            )
        current = related_model
    return current


def db_object_id(instance: Model) -> str:
    """How *instance*'s primary key is written into ``object_id``.

    The resolver compares this column against the outer row's primary key cast
    to text, so the two have to be spelled the same way.  Asking the field for
    its database value is what makes them agree: a UUID primary key, say, is
    hyphenated on PostgreSQL and bare hexadecimal on SQLite, which is exactly
    what each backend's own ``CAST`` produces.
    """
    pk_field = instance._meta.pk
    if pk_field is None:  # pragma: no cover -- every concrete model has one
        raise TypeError(f"{type(instance)._meta.label} has no primary key.")
    return str(pk_field.get_db_prep_value(instance.pk, connection, prepared=False))


__all__ = ["LOOKUP_SEP", "OBJECT_ID_MAX_LENGTH", "db_object_id", "follow_lookup"]
