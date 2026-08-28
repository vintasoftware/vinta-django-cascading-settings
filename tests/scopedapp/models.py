"""What a multi-tenant project does with ``QUESTIONNAIRES_SCOPE_MODEL``.

The tenant here is the organization that is already the top level of the
settings hierarchy, which is the ordinary shape: an installation's tenants are
the objects at the outermost level it holds settings for, with the global level
above all of them holding what everyone falls back to.
"""

from __future__ import annotations

from typing import ClassVar

from django.db import models
from vinta_django_questionnaires.models import AbstractQuestionnaireScope, ScopeType

from tests.testapp.models import Organization


class OrganizationScope(AbstractQuestionnaireScope):
    """A scope that is an organization, or the installation at large."""

    organization = models.ForeignKey(
        Organization,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="questionnaire_scopes",
    )

    class Meta:
        swappable = "QUESTIONNAIRES_SCOPE_MODEL"
        constraints: ClassVar = [
            models.CheckConstraint(
                condition=(
                    models.Q(scope_type=ScopeType.GLOBAL, organization__isnull=True)
                    | (
                        ~models.Q(scope_type=ScopeType.GLOBAL)
                        & models.Q(organization__isnull=False)
                    )
                ),
                name="organization_scope_type_and_value_agree",
            ),
        ]

    @property
    def scope(self) -> Organization | None:
        return self.organization

    @scope.setter
    def scope(self, value: Organization | None) -> None:
        self.organization = value
        self.scope_type = ScopeType.GLOBAL if value is None else ScopeType.SCOPED

    def build_scope_key(self) -> str:
        # The primary key, not the name: a key has to be stable for the life of
        # the scope, and a name is exactly the kind of thing someone renames.
        organization_id = getattr(self, "organization_id", None)
        return "" if organization_id is None else str(organization_id)
