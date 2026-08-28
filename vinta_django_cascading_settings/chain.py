"""The chain of levels one model's settings resolve through.

Building the chain reads the configuration -- which levels there are, and how
each one reaches the level above it.  That is the only part of resolution that
happens outside the database, and it settles what the query looks like rather
than what any value is: the chain is the same for every row of a queryset,
whereas the values it resolves are read per row, in SQL.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from django.contrib.contenttypes.models import ContentType
from django.utils.translation import gettext_lazy as _

from vinta_django_cascading_settings.exceptions import (
    LevelNotConfigured,
    SettingsConfigurationError,
)
from vinta_django_cascading_settings.lookups import LOOKUP_SEP
from vinta_django_cascading_settings.models import MAX_CHAIN_DEPTH, SettingsLevel

if TYPE_CHECKING:
    from django.db.models import Model


@dataclass(frozen=True)
class ChainLink:
    """One level of the chain, seen from the model being queried."""

    level: SettingsLevel
    depth: int
    #: The ORM path from the queried model to this level's object: empty for
    #: the model itself, ``None`` for the global level, which has no object.
    lookup: str | None

    @property
    def is_global(self) -> bool:
        return self.lookup is None

    @property
    def pk_path(self) -> str:
        """The path to this level's primary key, from the queried model."""
        if self.lookup is None:
            raise ValueError("The global level is not reached through a path.")
        return f"{self.lookup}{LOOKUP_SEP}pk" if self.lookup else "pk"


def build_chain(model: type[Model]) -> tuple[ChainLink, ...]:
    """*model*'s own level, then every level it inherits from, closest first."""
    levels = {level.pk: level for level in SettingsLevel.objects.all()}
    content_type = ContentType.objects.get_for_model(model, for_concrete_model=True)
    start = next(
        (level for level in levels.values() if level.content_type_id == content_type.pk), None
    )
    if start is None:
        raise LevelNotConfigured(model)

    links: list[ChainLink] = []
    seen: set[int] = set()
    current = start
    prefix = ""
    depth = 0
    while True:
        if current.pk in seen or depth > MAX_CHAIN_DEPTH:
            raise SettingsConfigurationError(
                _('The levels above "%(key)s" loop back on themselves.') % {"key": start.key}
            )
        seen.add(current.pk)
        links.append(ChainLink(current, depth, None if current.is_global else prefix))
        if current.parent_id is None:
            break
        parent = levels.get(current.parent_id)
        if parent is None:  # pragma: no cover -- the foreign key is protected
            break
        if not parent.is_global:
            if not current.parent_lookup:
                raise SettingsConfigurationError(
                    _('The "%(key)s" level does not say how to reach "%(parent)s".')
                    % {"key": current.key, "parent": parent.key}
                )
            prefix = (
                f"{prefix}{LOOKUP_SEP}{current.parent_lookup}" if prefix else current.parent_lookup
            )
        current = parent
        depth += 1
    return tuple(links)


__all__ = ["ChainLink", "build_chain"]
