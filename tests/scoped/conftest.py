"""Fixtures for the swapped-scope-model run: two tenants, one questionnaire."""

from __future__ import annotations

import pytest
from django.contrib.contenttypes.models import ContentType
from vinta_django_questionnaires.models import (
    Page,
    Question,
    Questionnaire,
    QuestionnaireVersion,
    Section,
    get_global_scope,
)
from vinta_django_questionnaires.question_types import QuestionType

from tests.scopedapp.models import OrganizationScope
from tests.testapp.models import Member, Organization, Team
from vinta_django_cascading_settings.models import SettingsLevel, SettingsSchema


@pytest.fixture
def levels(db):
    """Global, then organization, team and member beneath it."""
    root = SettingsLevel.objects.create(key="global", name="Global")
    organization = SettingsLevel.objects.create(
        key="organization",
        content_type=ContentType.objects.get_for_model(Organization),
        parent=root,
    )
    team = SettingsLevel.objects.create(
        key="team",
        content_type=ContentType.objects.get_for_model(Team),
        parent=organization,
        parent_lookup="organization",
    )
    member = SettingsLevel.objects.create(
        key="member",
        content_type=ContentType.objects.get_for_model(Member),
        parent=team,
        parent_lookup="team",
    )
    return {"global": root, "organization": organization, "team": team, "member": member}


@pytest.fixture
def shared_schema(db, levels):
    """One settings questionnaire the whole installation shares."""
    questionnaire = Questionnaire.objects.create(
        key="workspace", name="Workspace settings", scope=get_global_scope()
    )
    version = QuestionnaireVersion.objects.create(
        questionnaire=questionnaire, version=1, title="Workspace settings"
    )
    page = Page.objects.create(questionnaire_version=version, key="general", title="General")
    section = Section.objects.create(page=page, key="general", title="General")
    Question.objects.create(
        section=section,
        key="support_email",
        title="Support email",
        question_type=QuestionType.FREE_TEXT,
        order=0,
    )
    Question.objects.create(
        section=section, key="seats", title="Seats", question_type=QuestionType.NUMBER, order=1
    )
    version.publish()
    return SettingsSchema.objects.create(key="workspace", questionnaire=questionnaire)


@pytest.fixture
def tenants(db):
    """Two organizations, each of them a tenant with a scope of its own."""
    made = {}
    for slug in ("acme", "globex"):
        organization = Organization.objects.create(name=slug)
        scope = OrganizationScope(label=slug)
        scope.scope = organization
        scope.scope_key = scope.build_scope_key()
        scope.save()
        team = Team.objects.create(organization=organization, name=f"{slug}-team")
        made[slug] = {"organization": organization, "scope": scope, "team": team}
    return made
