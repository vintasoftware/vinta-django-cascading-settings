"""Which tenant a level's values belong to.

The questionnaires package makes a questionnaire and a response belong to a
scope -- a tenant, a workspace, or the installation at large -- and settings
inherit that boundary, with one rule of their own on top of it:

**The global level is the installation's, and every other level is a tenant's.**

Defaults that apply to everyone are what the global level is for, so its values
are held in the global scope and nowhere else; a tenant that wants its own
answer sets it at a level it owns.  Everything below the global level belongs
to exactly one tenant, and resolution never crosses from one to another.

An installation that never configures a scope model has one scope, the global
one, and all of this is a no-op: every row lands in it, and the filter that
would separate tenants separates nothing.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from django.utils.translation import gettext_lazy as _
from vinta_django_questionnaires.models import ScopeType, get_global_scope
from vinta_django_questionnaires.models_registry import get_scope_model

from vinta_django_cascading_settings.exceptions import SettingsConfigurationError

if TYPE_CHECKING:
    from django.db.models import Model

#: What the global scope's key is, on every scope model: a scope with nothing
#: behind it has nothing to spell.
GLOBAL_SCOPE_KEY = ""


def scope_key_for(scope: Any) -> str | None:
    """The key *scope* filters on, or ``None`` to filter on nothing.

    Takes a scope, a scope key, or the tenant object a scope stands for, so a
    caller can pass whichever of the three it happens to be holding.
    """
    if scope is None:
        return None
    if isinstance(scope, str):
        return scope
    key = getattr(scope, "scope_key", None)
    if key is not None:
        return str(key)
    return str(_scope_of(scope).scope_key)


def scope_instance_for(scope: Any) -> Any:
    """The scope row to write, or ``None`` to let the questionnaire decide.

    A response takes its questionnaire's scope when it is given none, which is
    the right default for a settings questionnaire a tenant owns.  Passing a
    scope is what an installation does when one questionnaire is shared and the
    values under it are not.
    """
    if scope is None:
        return None
    model = get_scope_model()
    if isinstance(scope, model):
        return scope
    if isinstance(scope, str):
        if scope == GLOBAL_SCOPE_KEY:
            return get_global_scope()
        found = model._default_manager.filter(scope_key=scope).first()
        if found is None:
            raise SettingsConfigurationError(
                _('There is no scope with the key "%(key)s".') % {"key": scope}
            )
        return found
    return _scope_of(scope)


def _scope_of(tenant: Model) -> Any:
    """The scope standing for *tenant*, which the project has to have made."""
    model = get_scope_model()
    found = (
        model._default_manager.filter(scope_type=ScopeType.SCOPED)
        .filter(**{_scope_field(model): tenant})
        .first()
    )
    if found is None:
        raise SettingsConfigurationError(
            _("%(tenant)s has no questionnaire scope. Create one before writing its settings.")
            % {"tenant": tenant}
        )
    return found


def _scope_field(model: type[Model]) -> str:
    """The field a project's scope model points at its tenant with."""
    for field in model._meta.get_fields():
        if field.is_relation and field.many_to_one and field.name not in {"scope"}:
            return field.name
    raise SettingsConfigurationError(
        _("%(model)s does not point at a tenant, so a tenant cannot be turned into a scope.")
        % {"model": model._meta.label}
    )


def is_global_scope(scope: Any) -> bool:
    """Whether *scope* is the installation-wide one."""
    return scope is None or getattr(scope, "scope_type", None) == ScopeType.GLOBAL


__all__ = [
    "GLOBAL_SCOPE_KEY",
    "is_global_scope",
    "scope_instance_for",
    "scope_key_for",
]
